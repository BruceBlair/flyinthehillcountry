#!/usr/bin/env python3
"""
push-forecast.py — Fetch NWS 7-day forecast for HITHC-RIDGE-N,
write data/forecast.json, and git-push to GitHub.

Cron (every 30 min — NWS updates at most hourly):
  */30 * * * * /usr/bin/python3 /home/HighlyReflective/weather-station/push-forecast.py >> /home/HighlyReflective/push-forecast.log 2>&1
"""

import fcntl, json, subprocess, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

GIT_LOCK = "/tmp/gtn-git-push.lock"

SCRIPT_DIR    = Path(__file__).parent
FORECAST_FILE = SCRIPT_DIR / "data" / "forecast.json"

NWS_OFFICE     = "EWX"
NWS_GRID_X     = 142
NWS_GRID_Y     = 79
NWS_USER_AGENT = "GTN/1.0 (blair.bruce@gmail.com)"

# ── NWS fetch with retry (NWS 500s are common transient failures) ─────────────
def fetch_json(url, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": NWS_USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (500, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise

# ── Build forecast.json ───────────────────────────────────────────────────────
def build_forecast(nws_data):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    periods = []
    for p in nws_data["properties"]["periods"]:
        precip = (p.get("probabilityOfPrecipitation") or {}).get("value")
        periods.append({
            "number":     p["number"],
            "name":       p["name"],
            "start":      p["startTime"],
            "end":        p["endTime"],
            "is_daytime": p["isDaytime"],
            "temp_f":     p["temperature"],
            "wind_speed": p["windSpeed"],
            "wind_dir":   p["windDirection"],
            "precip_pct": precip,
            "short":      p["shortForecast"],
            "detail":     p["detailedForecast"],
            "icon":       p["icon"],
        })
    return {
        "updated":  now,
        "source":   "NWS",
        "node_id":  "HITHC-RIDGE-N",
        "office":   NWS_OFFICE,
        "grid_x":   NWS_GRID_X,
        "grid_y":   NWS_GRID_Y,
        "periods":  periods,
    }

# ── Git commit + push ─────────────────────────────────────────────────────────
def git_push(file_path):
    rel = str(file_path.relative_to(SCRIPT_DIR))
    with open(GIT_LOCK, "w") as _lock:
        fcntl.flock(_lock, fcntl.LOCK_EX)
        subprocess.run(["git", "-C", str(SCRIPT_DIR), "add", rel], check=True)
        diff = subprocess.run(
            ["git", "-C", str(SCRIPT_DIR), "diff", "--cached", "--quiet"], check=False
        )
        if diff.returncode == 0:
            print("forecast.json unchanged — no commit.")
            return
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        subprocess.run(
            ["git", "-C", str(SCRIPT_DIR), "commit", "-m", f"data: forecast.json {ts} UTC"],
            check=True,
        )
        subprocess.run(["git", "-C", str(SCRIPT_DIR), "pull", "--rebase", "--autostash", "--quiet"], check=False)
        subprocess.run(["git", "-C", str(SCRIPT_DIR), "push"], check=True)
    print(f"Pushed forecast.json ({ts} UTC)")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    FORECAST_FILE.parent.mkdir(exist_ok=True)
    url = f"https://api.weather.gov/gridpoints/{NWS_OFFICE}/{NWS_GRID_X},{NWS_GRID_Y}/forecast"
    try:
        nws_data = fetch_json(url)
        forecast = build_forecast(nws_data)
        FORECAST_FILE.write_text(json.dumps(forecast, indent=2))
        print(f"Wrote forecast.json ({len(forecast['periods'])} periods, through {forecast['periods'][-1]['name']})")
        git_push(FORECAST_FILE)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
