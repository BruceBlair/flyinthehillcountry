#!/usr/bin/env python3
"""
push-external-flood-gauges.py — Pull nearby USGS stream-gauge readings
(gage height + discharge) from the public NWIS Instantaneous Values API
and write data/external-flood-gauges.json, so the flood-monitoring map
can show real river/creek context around the property's own soil-moisture
+ rain-piezo stations — most relevantly the Blanco River gauge at
Wimberley (site 08171000), the same reach that flooded catastrophically
in May 2015.

Unlike push-external-stations.py (Weather Underground), USGS NWIS is a
public federal government data service with no API key, no account, and
no redistribution ToS concern — gauge sites are public infrastructure,
not private citizens' equipment, so no anonymization is applied here.

Site list is hardcoded (found via one-time bounding-box discovery query
against https://waterservices.usgs.gov/nwis/site/, see git history) rather
than queried live each run, since gauge locations change rarely and a
fixed list avoids picking up a distant/irrelevant site if USGS adds one
inside the bounding box later.

Cron (every 15 min — USGS IV data updates roughly every 15-60 min upstream):
  */15 * * * * /usr/bin/python3 /home/HighlyReflective/hithc-gtn-depot/push-external-flood-gauges.py >> /home/HighlyReflective/push-external-flood-gauges.log 2>&1
"""

import json, subprocess, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
OUTPUT_FILE = SCRIPT_DIR / "data" / "external-flood-gauges.json"

# Discovered via: waterservices.usgs.gov/nwis/site/?format=rdb&bBox=-98.15,29.92,-97.92,30.12
#                 &siteStatus=active&siteType=ST&hasDataTypeCd=iv
GAUGES = [
    {"site_no": "08171000", "name": "Blanco River at Wimberley, TX", "lat": 29.99438, "lon": -98.08893},
    {"site_no": "08158700", "name": "Onion Creek near Driftwood, TX", "lat": 30.08299, "lon": -98.00779},
    {"site_no": "08171290", "name": "Blanco River at Halifax Ranch nr Kyle, TX", "lat": 30.00556, "lon": -97.95250},
]

PARAM_GAGE_HEIGHT = "00065"  # ft
PARAM_DISCHARGE   = "00060"  # ft3/s

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

cfg       = load_env(SCRIPT_DIR / ".env")
LATITUDE  = float(cfg.get("LATITUDE", "0") or 0)
LONGITUDE = float(cfg.get("LONGITUDE", "0") or 0)

def haversine_mi(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, sqrt, atan2
    R = 3958.8
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

def fetch_gauges():
    site_list = ",".join(g["site_no"] for g in GAUGES)
    url = (
        f"https://waterservices.usgs.gov/nwis/iv/"
        f"?sites={site_list}&parameterCd={PARAM_GAGE_HEIGHT},{PARAM_DISCHARGE}&format=json"
    )
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    by_site = {g["site_no"]: {**g, "gage_height_ft": None, "discharge_cfs": None, "last_updated": None} for g in GAUGES}
    for ts in data.get("value", {}).get("timeSeries", []):
        site_no = ts["sourceInfo"]["siteCode"][0]["value"]
        var_code = ts["variable"]["variableCode"][0]["value"]
        values = ts.get("values", [{}])[0].get("value", [])
        if not values or site_no not in by_site:
            continue
        latest = values[-1]
        if var_code == PARAM_GAGE_HEIGHT:
            by_site[site_no]["gage_height_ft"] = float(latest["value"])
            by_site[site_no]["last_updated"] = latest["dateTime"]
        elif var_code == PARAM_DISCHARGE:
            by_site[site_no]["discharge_cfs"] = float(latest["value"])
            if by_site[site_no]["last_updated"] is None:
                by_site[site_no]["last_updated"] = latest["dateTime"]

    gauges = []
    for g in by_site.values():
        g["distance_mi"] = round(haversine_mi(LATITUDE, LONGITUDE, g["lat"], g["lon"]), 1)
        gauges.append(g)
    gauges.sort(key=lambda g: g["distance_mi"])
    return gauges

def git_push(file_path):
    rel = str(file_path.relative_to(SCRIPT_DIR))
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "add", rel], check=True)
    diff = subprocess.run(["git", "-C", str(SCRIPT_DIR), "diff", "--cached", "--quiet"], check=False)
    if diff.returncode == 0:
        print("external-flood-gauges.json unchanged — no commit.")
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "commit", "-m", f"data: external-flood-gauges.json {ts} UTC", "--", rel], check=True)
    remotes = subprocess.run(["git", "-C", str(SCRIPT_DIR), "remote"], capture_output=True, text=True, check=False)
    if remotes.stdout.strip():
        subprocess.run(["git", "-C", str(SCRIPT_DIR), "push"], check=False)
    print(f"Committed external-flood-gauges.json ({ts} UTC) — deployed to senselayer.io via push-site.sh, not this repo's own remote.")

if __name__ == "__main__":
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        gauges = fetch_gauges()
        output = {
            "updated": now,
            "source": "USGS NWIS Instantaneous Values (waterservices.usgs.gov)",
            "attribution": "USGS Water Data for the Nation",
            "note": "Provisional data, subject to revision (see waterdata.usgs.gov/nwis/help/?provisional). Public federal gauge data — not anonymized (see script docstring).",
            "gauges": gauges,
        }
        OUTPUT_FILE.write_text(json.dumps(output, indent=2))
        print(f"Wrote external-flood-gauges.json — {len(gauges)} USGS gauge(s).")
        git_push(OUTPUT_FILE)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
