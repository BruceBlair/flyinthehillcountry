#!/usr/bin/env python3
"""
push-flood.py — Query InfluxDB for soil-moisture + rain-piezo readings,
derive a flood-risk tier per GTN station, write data/flood.json, and
git-push to GitHub.

Soil moisture note (found 2026-07-23): HA has THREE entity prefixes
(southside1, eastside_1, top_of_the_hill_station) all reporting identical
soil_moisture_1..5 / soil_battery_1..5 values every cycle — one physical
probe cluster got registered three times, not three separate installs.
"southside1" is treated as canonical (it matches the existing Valley East
Ecowitt prefix in push-nodes.py); the other two prefixes are ignored here.
Until a second/third probe cluster is physically installed, North Ridge and
South Ridge report soil_moisture_pct: null ("not yet installed"), not stale
or offline — there's no hardware there to be stale.

Cron (every 5 min, matches push-nodes.py cadence):
  */5 * * * * /usr/bin/python3 /home/HighlyReflective/hithc-gtn-depot/push-flood.py >> /home/HighlyReflective/push-flood.log 2>&1
"""

import json, subprocess, sys, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
FLOOD_FILE  = SCRIPT_DIR / "data" / "flood.json"
SOIL_CHANNELS = 5

# Illustrative thresholds — not yet calibrated against real flood events at
# this property. Revisit once a season of readings/rain events accumulates.
SOIL_WATCH_PCT     = 60.0
SOIL_WARNING_PCT   = 80.0
RAIN_RATE_WATCH    = 0.3   # in/hr
RAIN_RATE_WARNING  = 1.0   # in/hr
RAIN_DAILY_WARNING = 3.0   # in

STATIONS = [
    {"id": "HITHC-RIDGE-N",   "label": "North Ridge", "lat": 30.017359, "lon": -98.055174,
     "rain_prefix": "gw3000b",           "soil_prefix": None},
    {"id": "HITHC-VALLEY-E",  "label": "Valley East", "lat": 30.017007, "lon": -98.053447,
     "rain_prefix": "southside1",        "soil_prefix": "southside1"},
    {"id": "HITHC-RIDGE-S",   "label": "South Ridge", "lat": 30.014389, "lon": -98.056389,
     "rain_prefix": "ecowitt_station_2", "soil_prefix": None},
]

def load_env(path):
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env

cfg          = load_env(SCRIPT_DIR / ".env")
INFLUX_URL   = f"http://{cfg['NAS_IP']}:8086"
INFLUX_TOKEN = cfg["INFLUXDB_TOKEN"]

def fetch_latest(entity_ids):
    entity_filter = "|".join(entity_ids)
    flux = f"""from(bucket: "sensor_data")
  |> range(start: -48h)
  |> filter(fn: (r) => r._field == "value")
  |> filter(fn: (r) => r.entity_id =~ /^({entity_filter})$/)
  |> last()
  |> keep(columns: ["_time", "_value", "entity_id"])"""

    url = f"{INFLUX_URL}/api/v2/query?org=ground_truth"
    req = urllib.request.Request(
        url, data=flux.encode(),
        headers={"Authorization": f"Token {INFLUX_TOKEN}", "Content-Type": "application/vnd.flux"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        csv_text = resp.read().decode()

    results = {}
    for line in csv_text.splitlines():
        if not line.startswith(",_result"):
            continue
        parts = line.split(",")
        try:
            entity_id = parts[5]
            value     = float(parts[4])
            ts_str    = parts[3].rstrip("Z")
            last_seen = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
        except (ValueError, IndexError):
            continue
        if entity_id not in results or last_seen > results[entity_id][1]:
            results[entity_id] = (value, last_seen)
    return results

def age_status(last_seen, active_min=10, stale_hr=1):
    if last_seen is None:
        return "offline"
    age = datetime.now(timezone.utc) - last_seen
    if age < timedelta(minutes=active_min):
        return "active"
    if age < timedelta(hours=stale_hr):
        return "stale"
    return "offline"

def risk_tier(soil_pct, rain_rate, rain_daily):
    tier = "normal"
    reasons = []
    if soil_pct is not None:
        if soil_pct >= SOIL_WARNING_PCT:
            tier = "warning"; reasons.append(f"soil moisture {soil_pct:.0f}% (>= {SOIL_WARNING_PCT:.0f}%)")
        elif soil_pct >= SOIL_WATCH_PCT:
            tier = "watch"; reasons.append(f"soil moisture {soil_pct:.0f}% (>= {SOIL_WATCH_PCT:.0f}%)")
    if rain_rate is not None and rain_rate >= RAIN_RATE_WARNING:
        tier = "warning"; reasons.append(f"rain rate {rain_rate:.2f} in/hr")
    elif rain_rate is not None and rain_rate >= RAIN_RATE_WATCH and tier == "normal":
        tier = "watch"; reasons.append(f"rain rate {rain_rate:.2f} in/hr")
    if rain_daily is not None and rain_daily >= RAIN_DAILY_WARNING:
        tier = "warning"; reasons.append(f"{rain_daily:.1f} in rain today")
    if not reasons:
        reasons.append("no elevated readings" if (soil_pct is not None or rain_rate is not None) else "no data")
    return tier, "; ".join(reasons)

def build_flood(raw):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stations_out = []
    for s in STATIONS:
        rain_rate  = raw.get(f"{s['rain_prefix']}_rain_rate_piezo")
        rain_daily = raw.get(f"{s['rain_prefix']}_daily_rain_piezo")
        rain_rate_v, rain_rate_ts   = rain_rate  if rain_rate  else (None, None)
        rain_daily_v, rain_daily_ts = rain_daily if rain_daily else (None, None)

        soil_pct = None
        soil_channels = None
        last_seen = None
        if s["soil_prefix"]:
            vals = []
            for ch in range(1, SOIL_CHANNELS + 1):
                entry = raw.get(f"{s['soil_prefix']}_soil_moisture_{ch}")
                if entry:
                    v, ts = entry
                    vals.append(v)
                    if last_seen is None or ts > last_seen:
                        last_seen = ts
            if vals:
                soil_channels = vals
                soil_pct = round(sum(vals) / len(vals), 1)

        for ts in (rain_rate_ts, rain_daily_ts):
            if ts and (last_seen is None or ts > last_seen):
                last_seen = ts

        tier, reason = risk_tier(soil_pct, rain_rate_v, rain_daily_v)

        stations_out.append({
            "id": s["id"], "label": s["label"], "lat": s["lat"], "lon": s["lon"],
            "status": age_status(last_seen),
            "soil_sensor_installed": s["soil_prefix"] is not None,
            "soil_moisture_pct": soil_pct,
            "soil_channels_pct": soil_channels,
            "rain_rate_in_hr": round(rain_rate_v, 2) if rain_rate_v is not None else None,
            "rain_daily_in": round(rain_daily_v, 2) if rain_daily_v is not None else None,
            "flood_risk": tier,
            "flood_risk_reason": reason,
            "last_updated": last_seen.strftime("%Y-%m-%dT%H:%M:%SZ") if last_seen else None,
        })

    overall_order = {"normal": 0, "watch": 1, "warning": 2}
    overall = max((s["flood_risk"] for s in stations_out), key=lambda t: overall_order[t], default="normal")

    return {
        "updated": now,
        "overall_flood_risk": overall,
        "note": "Soil-moisture thresholds are illustrative placeholders, not yet calibrated against a real flood event at this property.",
        "stations": stations_out,
    }

def git_push(file_path):
    rel = str(file_path.relative_to(SCRIPT_DIR))
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "add", rel], check=True)
    diff = subprocess.run(["git", "-C", str(SCRIPT_DIR), "diff", "--cached", "--quiet"], check=False)
    if diff.returncode == 0:
        print("flood.json unchanged — no commit.")
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "commit", "-m", f"data: flood.json {ts} UTC", "--", rel], check=True)
    remotes = subprocess.run(["git", "-C", str(SCRIPT_DIR), "remote"], capture_output=True, text=True, check=False)
    if remotes.stdout.strip():
        subprocess.run(["git", "-C", str(SCRIPT_DIR), "push"], check=False)
    print(f"Committed flood.json ({ts} UTC) — deployed to senselayer.io via push-site.sh, not this repo's own remote.")

if __name__ == "__main__":
    FLOOD_FILE.parent.mkdir(exist_ok=True)
    try:
        entity_ids = []
        for s in STATIONS:
            entity_ids += [f"{s['rain_prefix']}_rain_rate_piezo", f"{s['rain_prefix']}_daily_rain_piezo"]
            if s["soil_prefix"]:
                entity_ids += [f"{s['soil_prefix']}_soil_moisture_{ch}" for ch in range(1, SOIL_CHANNELS + 1)]
        raw = fetch_latest(entity_ids)
        flood = build_flood(raw)
        FLOOD_FILE.write_text(json.dumps(flood, indent=2))
        print(f"Wrote flood.json — overall risk: {flood['overall_flood_risk']}")
        git_push(FLOOD_FILE)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
