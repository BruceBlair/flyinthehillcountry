#!/usr/bin/env python3
"""
push-nodes.py — Query InfluxDB for latest Ecowitt sensor readings,
build data/nodes.json, and git-push to GitHub.

Cron (every 5 min):
  */5 * * * * /usr/bin/python3 /home/HighlyReflective/weather-station/push-nodes.py >> /home/HighlyReflective/push-nodes.log 2>&1
"""

import json, subprocess, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
NODES_FILE  = SCRIPT_DIR / "data" / "nodes.json"

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

cfg           = load_env(SCRIPT_DIR / ".env")
INFLUX_URL    = f"http://{cfg['NAS_IP']}:8086"
INFLUX_TOKEN  = cfg["INFLUXDB_TOKEN"]

# ── Sensor entity → nodes.json field mapping ──────────────────────────────────
ENTITY_MAP = {
    "gw3000b_outdoor_temperature": "temp_f",
    "gw3000b_humidity":            "humidity_pct",
    "gw3000b_relative_pressure":   "pressure_msl_inhg",
    "gw3000b_wind_speed":          "wind_speed_mph",
    "gw3000b_wind_direction":      "wind_dir_deg",
    "gw3000b_wind_gust":           "wind_gust_mph",
    "gw3000b_rain_rate_piezo":     "rain_rate_in_hr",
    "gw3000b_daily_rain_piezo":    "rain_daily_in",
    "gw3000b_wh90_capacitor":      "_batt_v",
}

# WH90 supercapacitor voltage → battery % (2.5 V = 0%, 5.0 V = 100%)
def batt_pct(v):
    if v is None:
        return None
    return round(max(0.0, min(100.0, (v - 2.5) / (5.0 - 2.5) * 100)), 1)

# ── InfluxDB query ────────────────────────────────────────────────────────────
def fetch_latest():
    entity_filter = "|".join(ENTITY_MAP.keys())
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
        csv = resp.read().decode()

    # Annotated CSV: data lines start with ",_result"
    # Columns: ,result,table,_time,_value,entity_id
    results = {}
    for line in csv.splitlines():
        if not line.startswith(",_result"):
            continue
        parts = line.split(",")
        try:
            results[parts[5]] = float(parts[4])  # entity_id → value
        except (ValueError, IndexError):
            continue
    return results

# ── Build nodes.json ──────────────────────────────────────────────────────────
def build_nodes(raw):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def get(entity_id):
        v = raw.get(entity_id)
        return round(v, 2) if v is not None else None

    current = {
        "timestamp":         now,
        "temp_f":            get("gw3000b_outdoor_temperature"),
        "humidity_pct":      get("gw3000b_humidity"),
        "pressure_msl_inhg": get("gw3000b_relative_pressure"),
        "wind_speed_mph":    get("gw3000b_wind_speed"),
        "wind_dir_deg":      get("gw3000b_wind_direction"),
        "wind_gust_mph":     get("gw3000b_wind_gust"),
        "rain_rate_in_hr":   get("gw3000b_rain_rate_piezo"),
        "rain_daily_in":     get("gw3000b_daily_rain_piezo"),
        "battery_pct":       batt_pct(raw.get("gw3000b_wh90_capacitor")),
        "rssi_dbm":          None,
    }

    return {
        "updated": now,
        "nodes": [
            {
                "id":                  "HITHC-RIDGE-N",
                "label":               "North Ridge",
                "status":              "active",
                "lat":                 None,
                "lon":                 None,
                "elevation_ft":        None,
                "has_camera":          True,
                "camera_snapshot_url": "snapshots/HITHC-RIDGE-N-latest.jpg",
                "current":             current,
            },
            {
                "id":           "HITHC-RIDGE-W",
                "label":        "West Ridge",
                "status":       "planned",
                "lat":          None,
                "lon":          None,
                "elevation_ft": None,
                "has_camera":   False,
                "current":      None,
                "notes":        "Node placement target — weather only",
            },
            {
                "id":           "HITHC-RIDGE-NW",
                "label":        "Northwest Ridge",
                "status":       "planned",
                "lat":          None,
                "lon":          None,
                "elevation_ft": None,
                "has_camera":   False,
                "current":      None,
                "notes":        "Node placement target — weather only",
            },
        ],
    }

# ── Git commit + push ─────────────────────────────────────────────────────────
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
        ["git", "-C", str(SCRIPT_DIR), "commit", "-m", f"data: nodes.json {ts} UTC"],
        check=True,
    )
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "pull", "--rebase", "--quiet"], check=False)
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "push"], check=True)
    print(f"Pushed nodes.json ({ts} UTC)")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    NODES_FILE.parent.mkdir(exist_ok=True)
    try:
        raw   = fetch_latest()
        nodes = build_nodes(raw)
        NODES_FILE.write_text(json.dumps(nodes, indent=2))
        non_null = sum(1 for v in nodes["nodes"][0]["current"].values() if v is not None)
        print(f"Wrote nodes.json ({len(raw)} sensors, {non_null}/10 fields populated)")
        git_push(NODES_FILE)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
