#!/usr/bin/env python3
"""
push-nodes.py — Query InfluxDB for latest Ecowitt sensor readings across
all 3 GTN stations, build data/nodes.json, and git-push to GitHub.

Cron (every 5 min):
  */5 * * * * /usr/bin/python3 /home/HighlyReflective/weather-station/push-nodes.py >> /home/HighlyReflective/push-nodes.log 2>&1
"""

import json, subprocess, sys, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
NODES_FILE = SCRIPT_DIR / "data" / "nodes.json"

# ── Station config (surveyed coordinates; do not round or re-derive) ──────────
STATIONS = [
    {
        "id":                  "HITHC-RIDGE-N",
        "label":               "North Ridge",
        "lat":                 30.017359,
        "lon":                 -98.055174,
        "elevation_ft":        1115,
        "has_camera":          True,
        "camera_snapshot_url": "snapshots/HITHC-RIDGE-N-latest.jpg",
        "prefix":              "gw3000b",
    },
    {
        "id":           "HITHC-VALLEY-E",
        "label":        "Valley East",
        "lat":          30.017007,
        "lon":          -98.053447,
        "elevation_ft": 1000,
        "has_camera":   False,
        "prefix":       "southside1",
    },
    {
        "id":           "HITHC-RIDGE-S",
        "label":        "South Ridge",
        "lat":          30.014389,
        "lon":          -98.056389,
        "elevation_ft": 1148,
        "has_camera":   False,
        "prefix":       "ecowitt_station_2",
    },
]

# Sensor entity suffix → nodes.json field (same for every station prefix)
FIELD_SUFFIXES = {
    "outdoor_temperature": "temp_f",
    "humidity":            "humidity_pct",
    "relative_pressure":   "pressure_msl_inhg",
    "wind_speed":          "wind_speed_mph",
    "wind_direction":      "wind_dir_deg",
    "wind_gust":           "wind_gust_mph",
    "rain_rate_piezo":     "rain_rate_in_hr",
    "daily_rain_piezo":    "rain_daily_in",
    "wh90_capacitor":      "_batt_v",
}

# ── Load .env ─────────────────────────────────────────────────────────────────
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

# ── Helpers ───────────────────────────────────────────────────────────────────
def batt_pct(v):
    """WH90 supercapacitor voltage → battery % (2.5 V = 0%, 5.0 V = 100%)"""
    if v is None:
        return None
    return round(max(0.0, min(100.0, (v - 2.5) / (5.0 - 2.5) * 100)), 1)

def station_status(last_seen_dt):
    """Derive status string from last reading timestamp."""
    if last_seen_dt is None:
        return "offline"
    age = datetime.now(timezone.utc) - last_seen_dt
    if age < timedelta(minutes=10):
        return "active"
    if age < timedelta(hours=1):
        return "stale"
    return "offline"

# ── InfluxDB query ────────────────────────────────────────────────────────────
def fetch_latest():
    """Return {entity_id: (value, last_seen_datetime)} for all known entities."""
    all_prefixes = [s["prefix"] for s in STATIONS if s["prefix"]]
    entity_ids = [
        f"{prefix}_{suffix}"
        for prefix in all_prefixes
        for suffix in FIELD_SUFFIXES
    ]
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
        headers={
            "Authorization": f"Token {INFLUX_TOKEN}",
            "Content-Type":  "application/vnd.flux",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        csv_text = resp.read().decode()

    # Annotated CSV columns (after keep): ,result,table,_time,_value,entity_id
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
        # Keep the most recent reading if entity_id appears in multiple tables.
        if entity_id not in results or last_seen > results[entity_id][1]:
            results[entity_id] = (value, last_seen)
    return results

# ── Build per-station current readings ───────────────────────────────────────
def build_current(raw, prefix):
    """Build the `current` block for one station; returns (block_dict, last_seen)."""
    last_seen = None
    values = {}
    for suffix, field in FIELD_SUFFIXES.items():
        entity_id = f"{prefix}_{suffix}"
        if entity_id in raw:
            v, ts = raw[entity_id]
            values[field] = v
            if last_seen is None or ts > last_seen:
                last_seen = ts
        else:
            values[field] = None

    current = {
        "timestamp":         last_seen.strftime("%Y-%m-%dT%H:%M:%SZ") if last_seen else None,
        "temp_f":            round(values["temp_f"], 2) if values["temp_f"] is not None else None,
        "humidity_pct":      round(values["humidity_pct"], 2) if values["humidity_pct"] is not None else None,
        "pressure_msl_inhg": round(values["pressure_msl_inhg"], 2) if values["pressure_msl_inhg"] is not None else None,
        "wind_speed_mph":    round(values["wind_speed_mph"], 2) if values["wind_speed_mph"] is not None else None,
        "wind_dir_deg":      round(values["wind_dir_deg"], 2) if values["wind_dir_deg"] is not None else None,
        "wind_gust_mph":     round(values["wind_gust_mph"], 2) if values["wind_gust_mph"] is not None else None,
        "rain_rate_in_hr":   round(values["rain_rate_in_hr"], 2) if values["rain_rate_in_hr"] is not None else None,
        "rain_daily_in":     round(values["rain_daily_in"], 2) if values["rain_daily_in"] is not None else None,
        "battery_pct":       batt_pct(values["_batt_v"]),
        "rssi_dbm":          None,
    }
    return current, last_seen

# ── Build nodes.json ──────────────────────────────────────────────────────────
def build_nodes(raw):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nodes = []
    for s in STATIONS:
        node = {
            "id":           s["id"],
            "label":        s["label"],
            "lat":          s["lat"],
            "lon":          s["lon"],
            "elevation_ft": s["elevation_ft"],
            "has_camera":   s["has_camera"],
        }
        if s.get("camera_snapshot_url"):
            node["camera_snapshot_url"] = s["camera_snapshot_url"]

        if s["prefix"] is None:
            node["status"]  = "offline"
            node["current"] = None
        else:
            current, last_seen = build_current(raw, s["prefix"])
            node["status"]  = station_status(last_seen)
            node["current"] = current

        nodes.append(node)

    return {"updated": now, "nodes": nodes}

# ── Git commit + push ─────────────────────────────────────────────────────────
def _git_push_with_retry(repo, branch="main", attempts=3):
    for _ in range(attempts):
        r = subprocess.run(["git", "-C", repo, "push", "origin", branch],
                           capture_output=True, check=False)
        if r.returncode == 0:
            return
        # Rebase onto the fetched remote instead of resetting to it — reset
        # --mixed here previously discarded *any* local commit ahead of
        # origin (not just this script's own nodes.json commit), which ate
        # unrelated work mid-session more than once. --autostash covers the
        # original concern (dirty tracked files like automations.yaml).
        subprocess.run(["git", "-C", repo, "pull", "--rebase", "--autostash",
                        "--quiet"], check=False)
    raise subprocess.CalledProcessError(1, "git push", b"Push failed after retries")

def git_push(file_path):
    rel = str(file_path.relative_to(SCRIPT_DIR))
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "add", rel], check=True)
    diff = subprocess.run(
        ["git", "-C", str(SCRIPT_DIR), "diff", "--cached", "--quiet"], check=False
    )
    if diff.returncode == 0:
        print("nodes.json unchanged — no commit.")
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    subprocess.run(
        ["git", "-C", str(SCRIPT_DIR), "commit", "-m", f"data: nodes.json {ts} UTC", "--", rel],
        check=True,
    )
    _git_push_with_retry(str(SCRIPT_DIR))
    print(f"Pushed nodes.json ({ts} UTC)")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    NODES_FILE.parent.mkdir(exist_ok=True)
    try:
        raw   = fetch_latest()
        nodes = build_nodes(raw)
        NODES_FILE.write_text(json.dumps(nodes, indent=2))
        statuses = {n["id"]: n["status"] for n in nodes["nodes"]}
        print(f"Wrote nodes.json ({len(raw)} entities) — {statuses}")
        git_push(NODES_FILE)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
