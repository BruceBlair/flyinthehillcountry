#!/usr/bin/env python3
"""
Night Sky Patrol — Ground Truth Network
Subscribes to MQTT triggers from HA automations.
Computes visible celestial targets (moon, constellations, meteor showers, comets),
sweeps the TrackMix zoom lens to each compass preset, and captures snapshots.
Parks on the moon's compass direction between full patrols.
"""

import json
import logging
import math
import os
import threading
import time
import datetime
from pathlib import Path

import ephem
import paho.mqtt.client as mqtt
import requests

# ─── Config from environment ─────────────────────────────────────────────────

HA_URL        = os.getenv("HA_URL",           "http://192.168.100.202:8123")
HA_TOKEN      = os.getenv("HA_TOKEN",         "")
MQTT_HOST     = os.getenv("MQTT_HOST",        "mosquitto")
MQTT_PORT     = int(os.getenv("MQTT_PORT",    "1883"))
CAMERA_IP     = os.getenv("CAMERA_IP",        "192.168.100.131")
CAMERA_USER   = os.getenv("CAMERA_USER",      "admin")
CAMERA_PASS   = os.getenv("CAMERA_PASSWORD",  "")
LATITUDE      = float(os.getenv("LATITUDE",   "29.9974"))
LONGITUDE     = float(os.getenv("LONGITUDE",  "-98.0986"))
ELEVATION     = float(os.getenv("ELEVATION",  "300"))
MIN_ALT       = float(os.getenv("STAR_MIN_ALT",  "20.0"))
DWELL_SEC     = int(os.getenv("STAR_DWELL_SEC",  "30"))
SNAPS         = int(os.getenv("STAR_SNAPS",      "4"))
SNAP_DIR      = os.getenv("STAR_SNAP_DIR",    "/stars")
COMETS_FILE   = os.getenv("COMETS_FILE",      "/config/comets.json")
SNAP_INTERVAL = int(os.getenv("SNAP_INTERVAL_SEC", "8"))

PTZ_ENTITY = "select.high_res_in_the_hill_country_ptz_preset"

COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [night-sky] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("night-sky-patrol")

_patrol_lock = threading.Lock()   # prevents moon_track from interrupting a patrol

# ─── Astronomy ───────────────────────────────────────────────────────────────

def az_to_compass(az_deg: float) -> str:
    """Map azimuth 0–360° to the nearest of the 8 compass presets."""
    return COMPASS[round((az_deg % 360) / 45) % 8]


# Representative bright star for each constellation.
# Chosen for visibility from ~30°N latitude and spread across the year.
CONSTELLATION_STARS = [
    ("Orion",         "Betelgeuse"),
    ("Scorpius",      "Antares"),
    ("Leo",           "Regulus"),
    ("Virgo",         "Spica"),
    ("Taurus",        "Aldebaran"),
    ("Gemini",        "Pollux"),
    ("Canis Major",   "Sirius"),
    ("Bootes",        "Arcturus"),
    ("Lyra",          "Vega"),
    ("Aquila",        "Altair"),
    ("Cygnus",        "Deneb"),
    ("Ursa Major",    "Dubhe"),
    ("Perseus",       "Algol"),
    ("Auriga",        "Capella"),
    ("Sagittarius",   "Kaus Australis"),
    ("Andromeda",     "Alpheratz"),
    ("Pegasus",       "Markab"),
]

# Annual meteor showers.
# Columns: name, peak_month, peak_day, radiant_ra_hours, radiant_dec_deg, active_window_days
METEOR_SHOWERS = [
    ("Quadrantids",        1,  3,  15.33,  50,  2),
    ("Lyrids",             4, 22,  18.13,  34,  3),
    ("Eta Aquariids",      5,  6,  22.53,  -1,  5),
    ("Delta Aquariids",    7, 30,  22.67, -16,  5),
    ("Perseids",           8, 12,   3.07,  58,  5),
    ("Draconids",         10,  8,  17.47,  54,  2),
    ("Orionids",          10, 21,   6.33,  15,  5),
    ("Taurids",           11,  4,   3.73,  14,  7),
    ("Leonids",           11, 17,  10.13,  22,  3),
    ("Geminids",          12, 14,   7.53,  32,  3),
    ("Ursids",            12, 22,  14.47,  76,  2),
]


def make_observer() -> ephem.Observer:
    obs = ephem.Observer()
    obs.lat       = str(LATITUDE)
    obs.lon       = str(LONGITUDE)
    obs.elevation = ELEVATION
    obs.pressure  = 0           # skip atmospheric refraction
    obs.date      = ephem.now()
    return obs


def compute_targets(obs: ephem.Observer, max_constellations: int = 5) -> list:
    """
    Return [(label, compass_preset, altitude_deg), ...] sorted altitude-high-first.
    Includes moon, up to max_constellations visible constellations, active meteor
    shower radiants, and any comets configured in COMETS_FILE.
    """
    obs.date = ephem.now()
    targets = []

    # Moon
    moon = ephem.Moon(obs)
    moon_alt = math.degrees(moon.alt)
    if moon_alt >= MIN_ALT:
        targets.append(("Moon", az_to_compass(math.degrees(moon.az)), moon_alt))

    # Constellations — pick highest N above minimum altitude
    visible = []
    for const_name, star_name in CONSTELLATION_STARS:
        try:
            star = ephem.star(star_name)
            star.compute(obs)
            alt = math.degrees(star.alt)
            if alt >= MIN_ALT:
                visible.append((const_name, az_to_compass(math.degrees(star.az)), alt))
        except Exception as exc:
            log.debug(f"  skip {star_name}: {exc}")
    visible.sort(key=lambda x: x[2], reverse=True)
    targets.extend(visible[:max_constellations])

    # Active meteor showers
    today = datetime.date.today()
    for name, month, day, ra_h, dec_deg, window in METEOR_SHOWERS:
        try:
            peak = datetime.date(today.year, month, day)
        except ValueError:
            continue
        if abs((today - peak).days) <= window:
            radiant = ephem.FixedBody()
            radiant._ra    = ephem.hours(ra_h * math.pi / 12)
            radiant._dec   = ephem.degrees(dec_deg * math.pi / 180)
            radiant._epoch = ephem.J2000
            radiant.compute(obs)
            alt = math.degrees(radiant.alt)
            if alt >= MIN_ALT:
                targets.append(
                    (f"{name} meteors", az_to_compass(math.degrees(radiant.az)), alt)
                )

    # Comets (optional, loaded from COMETS_FILE)
    if Path(COMETS_FILE).exists():
        try:
            with open(COMETS_FILE) as fh:
                comet_list = json.load(fh)
            for entry in comet_list:
                try:
                    body = ephem.EllipticalBody()
                    for k, v in entry["elements"].items():
                        setattr(body, k, v)
                    body.name = entry.get("name", "Comet")
                    body.compute(obs)
                    alt = math.degrees(body.alt)
                    if alt >= MIN_ALT:
                        targets.append(
                            (body.name, az_to_compass(math.degrees(body.az)), alt)
                        )
                except Exception as exc:
                    log.warning(f"  comet {entry.get('name', '?')} error: {exc}")
        except Exception as exc:
            log.warning(f"Could not load comets file: {exc}")

    return targets


def moon_compass_now() -> str | None:
    """Return compass direction of the moon, or None if below horizon."""
    obs = make_observer()
    moon = ephem.Moon(obs)
    if math.degrees(moon.alt) > 0:
        return az_to_compass(math.degrees(moon.az))
    return None


# ─── Camera / HA interaction ─────────────────────────────────────────────────

def _ha_headers() -> dict:
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }


def ptz_goto(preset: str) -> None:
    requests.post(
        f"{HA_URL}/api/services/select/select_option",
        headers=_ha_headers(),
        json={"entity_id": PTZ_ENTITY, "option": preset},
        timeout=10,
    ).raise_for_status()


def take_snapshot(label: str, preset: str) -> str:
    """Pull a snapshot directly from the Reolink zoom lens (channel 1)."""
    Path(SNAP_DIR).mkdir(parents=True, exist_ok=True)
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = label.replace(" ", "_").lower()
    path = Path(SNAP_DIR) / f"{ts}_{safe}_{preset}.jpg"

    url = (
        f"http://{CAMERA_IP}/cgi-bin/api.cgi"
        f"?cmd=Snap&channel=1&user={CAMERA_USER}&password={CAMERA_PASS}"
    )
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    path.write_bytes(resp.content)
    log.info(f"      saved {path.name}")
    return str(path)


# ─── Patrol logic ────────────────────────────────────────────────────────────

def run_full_patrol(mqttc) -> None:
    """Sweep all visible celestial targets, capture snapshots, park on moon."""
    obs     = make_observer()
    targets = compute_targets(obs)

    if not targets:
        log.info("No targets above minimum altitude — skipping patrol")
        return

    log.info(f"Starting night sky patrol — {len(targets)} target(s)")

    visited: dict[str, str] = {}   # preset → label

    for label, preset, alt in targets:
        if preset in visited:
            log.info(f"  → {label} ({preset}, {alt:.0f}°) — already covered by {visited[preset]}")
            continue

        log.info(f"  → {label} at {preset} (alt {alt:.0f}°)")
        ptz_goto(preset)
        visited[preset] = label
        time.sleep(DWELL_SEC)

        for i in range(SNAPS):
            try:
                take_snapshot(label, preset)
            except Exception as exc:
                log.warning(f"      snap {i + 1}/{SNAPS} failed: {exc}")
            if i < SNAPS - 1:
                time.sleep(SNAP_INTERVAL)

    # Park on moon after patrol
    moon_preset = moon_compass_now() or "N"
    log.info(f"Patrol complete — parking on moon: {moon_preset}")
    ptz_goto(moon_preset)

    mqttc.publish(
        "cameras/events/night_sky_patrol",
        json.dumps({
            "status":      "complete",
            "targets":     list(visited.values()),
            "presets":     list(visited.keys()),
            "moon_parked": moon_preset,
            "timestamp":   datetime.datetime.now().isoformat(),
        }),
        retain=False,
    )


def run_moon_track() -> None:
    """Move camera to the moon's current compass direction."""
    preset = moon_compass_now()
    if preset:
        log.info(f"Moon track → {preset}")
        ptz_goto(preset)
    else:
        log.info("Moon below horizon — no update")


# ─── MQTT ────────────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info("MQTT connected")
        client.subscribe("cameras/control/night_sky_patrol")
        client.subscribe("cameras/control/moon_track")
    else:
        log.error(f"MQTT connect failed rc={rc}")


def on_message(client, userdata, msg):
    topic = msg.topic
    log.info(f"MQTT ← {topic}")

    if topic == "cameras/control/night_sky_patrol":
        if _patrol_lock.acquire(blocking=False):
            try:
                run_full_patrol(client)
            except Exception as exc:
                log.error(f"Patrol error: {exc}", exc_info=True)
            finally:
                _patrol_lock.release()
        else:
            log.info("Patrol already in progress — ignoring trigger")

    elif topic == "cameras/control/moon_track":
        if _patrol_lock.acquire(blocking=False):
            try:
                run_moon_track()
            except Exception as exc:
                log.error(f"Moon track error: {exc}", exc_info=True)
            finally:
                _patrol_lock.release()
        else:
            log.info("Patrol in progress — skipping moon track")


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    log.info(f"Connecting to MQTT {MQTT_HOST}:{MQTT_PORT}")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
