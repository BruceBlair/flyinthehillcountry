#!/usr/bin/env python3
"""
push-external-stations.py — Pull nearby public Personal Weather Stations
from Weather Underground's official PWS API and write data/external-stations.json,
so the weather-monitoring map can show "richer" regional context around the
3 native GTN stations.

Only Weather Underground is wired up. Ecowitt.net's public map
(ecowitt.net/home/map) has no equivalent official API — the only documented
Ecowitt cloud API (doc.ecowitt.net/web/#/apiv3en) is scoped to devices
registered to *your own* account (application_key/api_key + device IMEI/MAC),
not third-party stations on their crowd map. Pulling those would mean
scraping an undocumented endpoint, which is fragile and a likely ToS problem
for a site that redistributes the data continuously — deliberately not done
here. If Ecowitt ever ships a real "nearby stations" API, add a second
network branch alongside the WU one below.

Anonymization (per 2026-07-25 decision — both networks' ToS restrict
redistributing other members' station data on a separate public site):
station id/name are dropped entirely, replaced with a network-scoped index
(wu-1, wu-2, ...); lat/lon are rounded to 2 decimals (~0.7 mile) rather than
published at native precision.

Requires WU_API_KEY in .env (from https://www.wunderground.com/member/api-keys,
tied to a WU account with a registered PWS). Without it, writes an empty/
not-configured file and exits 0 — no error spam, matching push-flood.py's
graceful-skip style for the git-push step.

Cron (every 20 min — PWS obs refresh every 5-15 min upstream, no need for
5-min cadence on our end):
  */20 * * * * /usr/bin/python3 /home/HighlyReflective/hithc-gtn-depot/push-external-stations.py >> /home/HighlyReflective/push-external-stations.log 2>&1
"""

import json, subprocess, sys, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
OUTPUT_FILE  = SCRIPT_DIR / "data" / "external-stations.json"
RADIUS_MI    = 20   # WU's near-by endpoint returns up to 10 stations sorted by distance; filter beyond this

def load_env(path):
    env = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env

cfg        = load_env(SCRIPT_DIR / ".env")
WU_API_KEY = cfg.get("WU_API_KEY", "").strip()
LATITUDE   = cfg.get("LATITUDE", "").strip()
LONGITUDE  = cfg.get("LONGITUDE", "").strip()

def wu_get(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode())

def fetch_nearby_stations():
    geocode = f"{LATITUDE},{LONGITUDE}"
    near_url = (
        f"https://api.weather.com/v3/location/near"
        f"?geocode={geocode}&product=pws&format=json&apiKey={WU_API_KEY}"
    )
    near = wu_get(near_url)
    location = near.get("location", {})
    station_ids = location.get("stationId", [])
    distances_km = location.get("distanceKm", [])

    stations = []
    for i, station_id in enumerate(station_ids):
        dist_mi = (distances_km[i] * 0.621371) if i < len(distances_km) else None
        if dist_mi is not None and dist_mi > RADIUS_MI:
            continue
        try:
            obs_url = (
                f"https://api.weather.com/v2/pws/observations/current"
                f"?stationId={station_id}&format=json&units=e&apiKey={WU_API_KEY}"
            )
            obs = wu_get(obs_url)
            reading = (obs.get("observations") or [{}])[0]
        except (urllib.error.HTTPError, urllib.error.URLError, IndexError, json.JSONDecodeError):
            # Some nearby stations return HTTP 204 (no body) when offline/stale —
            # qcStatus -1 in the /near response is the tell. Skip, don't fail the batch.
            reading = {}
        imperial = reading.get("imperial", {})
        lat = reading.get("lat")
        lon = reading.get("lon")
        stations.append({
            "id": f"wu-{i + 1}",
            "network": "wunderground",
            "distance_mi": round(dist_mi, 1) if dist_mi is not None else None,
            # Rounded to ~0.01 deg (~0.7 mi) — anonymized, not the station's real precision
            "approx_lat": round(lat, 2) if lat is not None else None,
            "approx_lon": round(lon, 2) if lon is not None else None,
            "temp_f": imperial.get("temp"),
            "humidity_pct": reading.get("humidity"),
            "wind_speed_mph": imperial.get("windSpeed"),
            "wind_gust_mph": imperial.get("windGust"),
            "pressure_in": imperial.get("pressure"),
            "last_updated": reading.get("obsTimeUtc"),
        })
    return stations

def git_push(file_path):
    rel = str(file_path.relative_to(SCRIPT_DIR))
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "add", rel], check=True)
    diff = subprocess.run(["git", "-C", str(SCRIPT_DIR), "diff", "--cached", "--quiet"], check=False)
    if diff.returncode == 0:
        print("external-stations.json unchanged — no commit.")
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "commit", "-m", f"data: external-stations.json {ts} UTC", "--", rel], check=True)
    remotes = subprocess.run(["git", "-C", str(SCRIPT_DIR), "remote"], capture_output=True, text=True, check=False)
    if remotes.stdout.strip():
        subprocess.run(["git", "-C", str(SCRIPT_DIR), "push"], check=False)
    print(f"Committed external-stations.json ({ts} UTC) — deployed to senselayer.io via push-site.sh, not this repo's own remote.")

if __name__ == "__main__":
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        if not WU_API_KEY:
            output = {
                "updated": now,
                "networks_configured": {"wunderground": False, "ecowitt": False},
                "source_note": (
                    "WU_API_KEY not set in .env — register a WU account/PWS at "
                    "wunderground.com/member/api-keys, then add the key to enable "
                    "nearby-station pulls. Ecowitt.net's public map has no equivalent "
                    "official API (see script docstring) and is not wired up."
                ),
                "attribution": "Weather Underground (wunderground.com)",
                "stations": [],
            }
            OUTPUT_FILE.write_text(json.dumps(output, indent=2))
            print("WU_API_KEY not configured — wrote empty external-stations.json, no error.")
            git_push(OUTPUT_FILE)
            sys.exit(0)

        stations = fetch_nearby_stations()
        output = {
            "updated": now,
            "networks_configured": {"wunderground": True, "ecowitt": False},
            "source_note": "Station identity anonymized (id/name dropped, lat/lon rounded to ~0.01 deg) before publishing, per network ToS on redistributing other members' data.",
            "attribution": "Weather Underground (wunderground.com)",
            "stations": stations,
        }
        OUTPUT_FILE.write_text(json.dumps(output, indent=2))
        print(f"Wrote external-stations.json — {len(stations)} nearby WU station(s).")
        git_push(OUTPUT_FILE)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
