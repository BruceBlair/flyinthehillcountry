#!/usr/bin/env python3
"""
Highlight Curator — Ground Truth Network
Subscribes to Frigate + weather MQTT events, flags exceptional media
(wildlife, weather events, golden hour), and stores snapshots + clips
to /highlights for later GitHub Pages upload.
"""

import json
import logging
import os
import threading
import time

from manifest_io import locked_manifest_update
from datetime import datetime, timedelta, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
import requests
from astral import LocationInfo
from astral.sun import sun

# ── Config ────────────────────────────────────────────────────────────────────
MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
FRIGATE_API = os.getenv("FRIGATE_API", "http://frigate:5000")
HIGHLIGHTS_DIR = Path(os.getenv("HIGHLIGHTS_DIR", "/highlights"))

# Location for sunrise/sunset — set in .env
LAT = float(os.getenv("LATITUDE", "39.8"))
LON = float(os.getenv("LONGITUDE", "-98.5"))
LOCATION = LocationInfo(latitude=LAT, longitude=LON, timezone=os.getenv("TZ", "America/Chicago"))

# Minutes before/after sunrise or sunset that count as "golden hour"
GOLDEN_MINUTES = int(os.getenv("GOLDEN_MINUTES", "45"))

# Frigate confidence threshold
MIN_SCORE = float(os.getenv("MIN_SCORE", "0.60"))

# Frigate camera name (matches config.yml)
CAMERA_NAME = os.getenv("CAMERA_NAME", "reolink_ptz")

# Max snapshots per Frigate event; minimum gap between snaps (seconds)
MAX_SNAPS_PER_EVENT = int(os.getenv("MAX_SNAPS_PER_EVENT", "10"))
SNAP_INTERVAL_SEC   = int(os.getenv("SNAP_INTERVAL_SEC",   "30"))

# Labels that go into the wildlife bucket
WILDLIFE_LABELS = {
    "bird", "deer", "fox", "bear", "rabbit", "squirrel",
    "raccoon", "turkey", "dog", "cat", "cow", "horse",
}

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("curator")

# ── State ─────────────────────────────────────────────────────────────────────
# event_id → (snap_count, last_snap_time)
_snapped: dict[str, tuple[int, float]] = {}
_snapped_lock = threading.Lock()

# Track event IDs flagged as highlights so we fetch the clip on "end"
_pending_clips: dict[str, dict] = {}   # event_id → {categories, label, camera, ts}
_pending_lock = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────
def golden_hour_status(now: datetime | None = None) -> tuple[bool, str | None]:
    """Return (True, 'sunrise'|'sunset') if now is within GOLDEN_MINUTES of the transition."""
    if now is None:
        now = datetime.now()
    try:
        s = sun(LOCATION.observer, date=now.date(), tzinfo=LOCATION.tzinfo)
        window = timedelta(minutes=GOLDEN_MINUTES)
        if abs(now - s["sunrise"].replace(tzinfo=None)) <= window:
            return True, "sunrise"
        if abs(now - s["sunset"].replace(tzinfo=None)) <= window:
            return True, "sunset"
    except Exception as e:
        log.warning(f"Sun calculation failed: {e}")
    return False, None


def fetch_bytes(url: str, timeout: int = 15, stream: bool = False) -> bytes | None:
    try:
        r = requests.get(url, timeout=timeout, stream=stream)
        if r.status_code == 200:
            return r.content
        log.warning(f"HTTP {r.status_code} for {url}")
    except requests.RequestException as e:
        log.error(f"Request failed ({url}): {e}")
    return None


def save_file(path: Path, data: bytes) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        log.info(f"Saved  {path.relative_to(HIGHLIGHTS_DIR)}")
        return True
    except OSError as e:
        log.error(f"Write failed ({path}): {e}")
        return False


def update_manifest(entry: dict) -> None:
    manifest_path = HIGHLIGHTS_DIR / "manifest.json"
    try:
        def _insert(manifest):
            manifest["entries"].insert(0, entry)
            manifest["entries"] = manifest["entries"][:2000]
            manifest["updated"] = datetime.now().isoformat()
        locked_manifest_update(manifest_path, _insert)
    except Exception as e:
        log.error(f"Manifest update failed: {e}")


# ── Event handlers ────────────────────────────────────────────────────────────
def handle_frigate_event(payload: dict) -> None:
    event_type = payload.get("type")          # "new" | "update" | "end"
    event = payload.get("after") or payload   # Frigate wraps in before/after on update/end
    if not event:
        return

    event_id = event.get("id")
    label = (event.get("label") or "").lower()
    score = float(event.get("score") or 0)
    camera = event.get("camera", CAMERA_NAME)
    has_snapshot = event.get("has_snapshot", False)

    if not event_id:
        return

    now = datetime.now()
    is_golden, golden_type = golden_hour_status(now)
    ts = now.strftime("%Y%m%d_%H%M%S")

    # Determine which buckets this event belongs to
    categories: list[str] = []
    if label in WILDLIFE_LABELS and score >= MIN_SCORE:
        categories.append("wildlife")
    if is_golden and (label in WILDLIFE_LABELS or event_type == "new"):
        categories.append(f"golden_hour/{golden_type}")

    if not categories:
        return

    # ── Snapshot: up to MAX_SNAPS_PER_EVENT per event, rate-limited ───────────
    with _snapped_lock:
        snap_count, last_snap_t = _snapped.get(event_id, (0, 0.0))
        now_t = time.monotonic()
        may_snap = (
            has_snapshot
            and snap_count < MAX_SNAPS_PER_EVENT
            and (snap_count == 0 or (now_t - last_snap_t) >= SNAP_INTERVAL_SEC)
        )
        if may_snap:
            _snapped[event_id] = (snap_count + 1, now_t)

    if may_snap:
        snap_url = f"{FRIGATE_API}/api/events/{event_id}/snapshot.jpg"
        data = fetch_bytes(snap_url)
        if data:
            n = snap_count + 1
            snap_name = f"{ts}_{label}_{n:02d}.jpg"
            for cat in categories:
                dest = HIGHLIGHTS_DIR / cat / snap_name
                save_file(dest, data)
            update_manifest({
                "timestamp": ts,
                "label": label,
                "score": round(score, 3),
                "categories": categories,
                "camera": camera,
                "event_id": event_id,
                "snap_seq": n,
                "snapshot": f"{categories[0]}/{snap_name}",
                "clip": None,
            })
            if snap_count == 0:
                # First snap — mark as pending for clip fetch on event end
                with _pending_lock:
                    _pending_clips[event_id] = {
                        "categories": categories,
                        "label": label,
                        "camera": camera,
                        "ts": ts,
                    }

    # ── Clip on event end ──────────────────────────────────────────────────
    if event_type == "end":
        with _snapped_lock:
            _snapped.pop(event_id, None)
        with _pending_lock:
            pending = _pending_clips.pop(event_id, None)
        if pending:
            clip_url = f"{FRIGATE_API}/api/events/{event_id}/clip.mp4"
            data = fetch_bytes(clip_url, timeout=60)
            if data:
                for cat in pending["categories"]:
                    dest = HIGHLIGHTS_DIR / cat / f"{pending['ts']}_{pending['label']}.mp4"
                    save_file(dest, data)
            log.info(f"Clip fetched for event {event_id} ({pending['label']})")


def handle_weather_alert(topic: str, payload: dict | str) -> None:
    """Grab a live camera frame whenever a storm/lightning alert fires."""
    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")

    if "lightning" in topic:
        event_type = "lightning"
    elif "severe" in topic:
        event_type = "severe_storm"
    else:
        event_type = "storm"

    dest_dir = HIGHLIGHTS_DIR / "weather"

    # Live frame from Frigate
    snap_url = f"{FRIGATE_API}/api/{CAMERA_NAME}/latest.jpg"
    data = fetch_bytes(snap_url)
    snap_rel = None
    if data:
        snap_path = dest_dir / f"{ts}_{event_type}.jpg"
        if save_file(snap_path, data):
            snap_rel = f"weather/{ts}_{event_type}.jpg"

    # Save alert metadata alongside the image
    meta_path = dest_dir / f"{ts}_{event_type}.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps({
        "timestamp": ts,
        "event_type": event_type,
        "topic": topic,
        "payload": payload,
    }, indent=2))

    update_manifest({
        "timestamp": ts,
        "label": event_type,
        "categories": ["weather"],
        "camera": CAMERA_NAME,
        "event_id": None,
        "snapshot": snap_rel,
        "clip": None,
    })
    log.info(f"Weather alert captured: {event_type}")


def handle_golden_hour_event(payload: dict | str) -> None:
    """Snapshot when HA publishes a golden-hour window open/close."""
    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")
    _, golden_type = golden_hour_status(now)
    golden_type = golden_type or "golden_hour"

    snap_url = f"{FRIGATE_API}/api/{CAMERA_NAME}/latest.jpg"
    data = fetch_bytes(snap_url)
    snap_rel = None
    if data:
        dest = HIGHLIGHTS_DIR / "golden_hour" / golden_type / f"{ts}_scene.jpg"
        if save_file(dest, data):
            snap_rel = f"golden_hour/{golden_type}/{ts}_scene.jpg"

    update_manifest({
        "timestamp": ts,
        "label": golden_type,
        "categories": [f"golden_hour/{golden_type}"],
        "camera": CAMERA_NAME,
        "event_id": None,
        "snapshot": snap_rel,
        "clip": None,
    })


# ── Periodic golden-hour snapshots ────────────────────────────────────────────
def _golden_hour_watcher() -> None:
    """Every 2 minutes during golden hour, take a scene snapshot."""
    interval = 120  # seconds
    while True:
        time.sleep(interval)
        is_golden, golden_type = golden_hour_status()
        if not is_golden:
            continue
        now = datetime.now()
        ts = now.strftime("%Y%m%d_%H%M%S")
        snap_url = f"{FRIGATE_API}/api/{CAMERA_NAME}/latest.jpg"
        data = fetch_bytes(snap_url)
        if data:
            dest = HIGHLIGHTS_DIR / "golden_hour" / golden_type / f"{ts}_scene.jpg"
            if save_file(dest, data):
                update_manifest({
                    "timestamp": ts,
                    "label": f"{golden_type}_scene",
                    "categories": [f"golden_hour/{golden_type}"],
                    "camera": CAMERA_NAME,
                    "event_id": None,
                    "snapshot": f"golden_hour/{golden_type}/{ts}_scene.jpg",
                    "clip": None,
                })


# ── MQTT ──────────────────────────────────────────────────────────────────────
def on_connect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        log.error(f"MQTT connect failed (rc={rc})")
        return
    log.info("Connected to MQTT broker")
    client.subscribe("frigate/events")
    client.subscribe("weather/alerts/#")
    client.subscribe("weather/events/#")
    client.subscribe("cameras/events/golden_hour")
    log.info("Subscribed to: frigate/events, weather/alerts/#, weather/events/#, cameras/events/golden_hour")


def on_disconnect(client, userdata, rc, properties=None):
    log.warning(f"MQTT disconnected (rc={rc}), will auto-reconnect")


def on_message(client, userdata, msg):
    topic = msg.topic
    try:
        payload = json.loads(msg.payload.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = msg.payload.decode(errors="replace")

    try:
        if topic == "frigate/events":
            handle_frigate_event(payload)
        elif topic.startswith("weather/"):
            handle_weather_alert(topic, payload)
        elif topic == "cameras/events/golden_hour":
            handle_golden_hour_event(payload)
    except Exception as e:
        log.exception(f"Unhandled error processing {topic}: {e}")


def main():
    HIGHLIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    log.info(f"Highlights directory: {HIGHLIGHTS_DIR}")
    log.info(f"Location: {LAT}°N {LON}°E  |  Golden window: ±{GOLDEN_MINUTES} min")
    log.info(f"Wildlife labels: {sorted(WILDLIFE_LABELS)}")

    # Start golden-hour background watcher
    t = threading.Thread(target=_golden_hour_watcher, daemon=True, name="golden-hour-watcher")
    t.start()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=5, max_delay=60)

    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except (ConnectionRefusedError, OSError) as e:
            log.error(f"MQTT connection error: {e} — retrying in 10s")
            time.sleep(10)


if __name__ == "__main__":
    main()
