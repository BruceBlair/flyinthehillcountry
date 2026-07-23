#!/usr/bin/env python3
"""
push-flight-conditions.py — Derive a green/yellow/red flight go/no-go
indicator from data/nodes.json's live wind readings, write
data/flight-conditions.json, and git-push to GitHub.

Pure derivation, no new sensor query: reads whatever push-nodes.py already
wrote. As of 2026-07-23, wind_speed_mph/wind_gust_mph are null on all 3
stations (open HA `ecowitt` integration binding bug — see project notes);
this script reports "unknown" rather than a false "go" when inputs are
missing. Once that bug is fixed upstream, real wind data flows through
nodes.json and this indicator starts working with no changes needed here.

Cron (every 5 min, right after push-nodes.py):
  */5 * * * * /usr/bin/python3 /home/HighlyReflective/hithc-gtn-depot/push-flight-conditions.py >> /home/HighlyReflective/push-flight-conditions.log 2>&1
"""

import json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
NODES_FILE   = SCRIPT_DIR / "data" / "nodes.json"
FLIGHT_FILE  = SCRIPT_DIR / "data" / "flight-conditions.json"

# Configurable thresholds — small-aircraft/drone go/no-go, illustrative
# defaults pending real operating limits from the flight-routing use case.
GUST_NO_GO_MPH    = 25.0
GUST_CAUTION_MPH  = 15.0
SUSTAINED_NO_GO_MPH   = 20.0
SUSTAINED_CAUTION_MPH = 12.0

def station_condition(node):
    current = node.get("current") or {}
    gust = current.get("wind_gust_mph")
    sustained = current.get("wind_speed_mph")
    direction = current.get("wind_dir_deg")

    if gust is None and sustained is None:
        return {
            "status": "unknown",
            "reason": "no live wind data (station reporting null — sensor or integration issue, not necessarily calm conditions)",
            "wind_gust_mph": None, "wind_speed_mph": None, "wind_dir_deg": direction,
        }

    status = "go"
    reasons = []
    if gust is not None and gust >= GUST_NO_GO_MPH:
        status = "no-go"; reasons.append(f"gust {gust:.0f} mph >= {GUST_NO_GO_MPH:.0f}")
    elif sustained is not None and sustained >= SUSTAINED_NO_GO_MPH:
        status = "no-go"; reasons.append(f"sustained wind {sustained:.0f} mph >= {SUSTAINED_NO_GO_MPH:.0f}")
    elif gust is not None and gust >= GUST_CAUTION_MPH:
        status = "caution"; reasons.append(f"gust {gust:.0f} mph >= {GUST_CAUTION_MPH:.0f}")
    elif sustained is not None and sustained >= SUSTAINED_CAUTION_MPH:
        status = "caution"; reasons.append(f"sustained wind {sustained:.0f} mph >= {SUSTAINED_CAUTION_MPH:.0f}")

    if not reasons:
        reasons.append("winds within limits")

    return {
        "status": status,
        "reason": "; ".join(reasons),
        "wind_gust_mph": gust, "wind_speed_mph": sustained, "wind_dir_deg": direction,
    }

def build_flight(nodes_data):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stations = []
    for node in nodes_data["nodes"]:
        cond = station_condition(node)
        stations.append({
            "id": node["id"], "label": node["label"], "lat": node["lat"], "lon": node["lon"],
            "node_status": node["status"],
            **cond,
        })

    order = {"go": 0, "caution": 1, "unknown": 2, "no-go": 3}
    overall = max((s["status"] for s in stations), key=lambda t: order[t], default="unknown")

    return {
        "updated": now,
        "nodes_data_updated": nodes_data.get("updated"),
        "overall_status": overall,
        "thresholds_mph": {
            "gust_no_go": GUST_NO_GO_MPH, "gust_caution": GUST_CAUTION_MPH,
            "sustained_no_go": SUSTAINED_NO_GO_MPH, "sustained_caution": SUSTAINED_CAUTION_MPH,
        },
        "stations": stations,
    }

def git_push(file_path):
    rel = str(file_path.relative_to(SCRIPT_DIR))
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "add", rel], check=True)
    diff = subprocess.run(["git", "-C", str(SCRIPT_DIR), "diff", "--cached", "--quiet"], check=False)
    if diff.returncode == 0:
        print("flight-conditions.json unchanged — no commit.")
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "commit", "-m", f"data: flight-conditions.json {ts} UTC", "--", rel], check=True)
    remotes = subprocess.run(["git", "-C", str(SCRIPT_DIR), "remote"], capture_output=True, text=True, check=False)
    if remotes.stdout.strip():
        subprocess.run(["git", "-C", str(SCRIPT_DIR), "push"], check=False)
    print(f"Committed flight-conditions.json ({ts} UTC) — deployed to senselayer.io via push-site.sh, not this repo's own remote.")

if __name__ == "__main__":
    FLIGHT_FILE.parent.mkdir(exist_ok=True)
    try:
        nodes_data = json.loads(NODES_FILE.read_text())
        flight = build_flight(nodes_data)
        FLIGHT_FILE.write_text(json.dumps(flight, indent=2))
        print(f"Wrote flight-conditions.json — overall: {flight['overall_status']}")
        git_push(FLIGHT_FILE)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
