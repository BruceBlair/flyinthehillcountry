#!/usr/bin/env python3
"""
push-availability.py — Scan all video/photo/weather sources and build
data/availability.json, then git-push to GitHub.

Sources:
  1. EasyNVR date folders  /volume1/camera_raw/MMDDYYYY/
  2. EasyNVR dense         /volume1/camera_raw/easynvr_rec/PnyGeSySOTRTW/01/YYYYMMDD/
  3. Frigate API           http://NAS_IP:5000/api/recordings/summary
  4. Reolink timelapse     /volume1/camera_raw/timelapse/<uuid>/video/  (Unix ts in name)
  5. Photos                manifest.json  (timestamp field YYYYMMDD_HHMMSS)
  6. Cell footage          /volume1/camera_raw/cell footage/  (VID20260310*.mp4)
  7. Weather               InfluxDB Ecowitt — continuous since 2026-06-05

Cron (daily at 00:05):
  5 0 * * * /usr/bin/python3 /home/HighlyReflective/weather-station/push-availability.py >> /home/HighlyReflective/push-availability.log 2>&1
"""

import json, re, subprocess, sys, urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR        = Path(__file__).parent
AVAILABILITY_FILE = SCRIPT_DIR / "data" / "availability.json"

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
NAS_IP       = cfg["NAS_IP"]
INFLUX_URL   = f"http://{NAS_IP}:8086"
INFLUX_TOKEN = cfg["INFLUXDB_TOKEN"]

# ── Paths ─────────────────────────────────────────────────────────────────────
CAMERA_RAW     = Path("/volume1/camera_raw")
EASYNVR_SPARSE = CAMERA_RAW
EASYNVR_DENSE  = CAMERA_RAW / "easynvr_rec" / "PnyGeSySOTRTW" / "01"
TIMELAPSE_ROOT = CAMERA_RAW / "timelapse"
CELL_FOOTAGE   = CAMERA_RAW / "cell footage"
MANIFEST_FILE  = SCRIPT_DIR / "manifest.json"

# Continuous recording started 2026-06-06
CONTINUOUS_START = date(2026, 6, 6)
# Ecowitt weather sensors live since 2026-06-05
WEATHER_START    = date(2026, 6, 5)
# Archive begins 2026-03-10 (founding footage)
ARCHIVE_START    = date(2026, 3, 10)

# ── Helpers ───────────────────────────────────────────────────────────────────
def iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def empty_flags():
    return {
        "photos":           False,
        "weather":          False,
        "video_continuous": False,
        "video_events":     False,
        "video_founding":   False,
        "timelapse":        False,
    }

# ── Source 1: EasyNVR sparse (MMDDYYYY folders) ───────────────────────────────
def scan_easynvr_sparse(dates: defaultdict):
    for entry in EASYNVR_SPARSE.iterdir():
        name = entry.name
        if not re.fullmatch(r"\d{8}", name) or not entry.is_dir():
            continue
        # Disambiguate MMDDYYYY vs YYYYMMDD by year position
        # MMDDYYYY: positions 4-7 = year (e.g. 03162026 → year=2026)
        # YYYYMMDD: positions 0-3 = year (e.g. 20260331 → year=2026)
        if name[4:] == "2026":
            mm, dd, yyyy = name[0:2], name[2:4], name[4:8]
        else:
            continue  # skip YYYYMMDD folders here (handled by dense scanner)
        try:
            d = iso(date(int(yyyy), int(mm), int(dd)))
            dates[d]["video_events"] = True
        except ValueError:
            continue

# ── Source 2: EasyNVR dense (YYYYMMDD folders) ───────────────────────────────
def scan_easynvr_dense(dates: defaultdict):
    if not EASYNVR_DENSE.exists():
        return
    for entry in EASYNVR_DENSE.iterdir():
        name = entry.name
        if not re.fullmatch(r"\d{8}", name) or not entry.is_dir():
            continue
        try:
            d = iso(date(int(name[0:4]), int(name[4:6]), int(name[6:8])))
            dates[d]["video_events"] = True
        except ValueError:
            continue

# ── Source 3: Frigate recordings summary ──────────────────────────────────────
def scan_frigate(dates: defaultdict):
    url = f"http://{NAS_IP}:5000/api/recordings/summary"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            summary = json.loads(resp.read().decode())
    except Exception as e:
        print(f"  WARNING: Frigate API unavailable: {e}", file=sys.stderr)
        return
    for d_str in summary:
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            continue
        if d >= CONTINUOUS_START:
            dates[d_str]["video_continuous"] = True
        else:
            dates[d_str]["video_events"] = True

# ── Source 4: Reolink timelapse (Unix timestamp in filename) ──────────────────
def scan_timelapse(dates: defaultdict):
    if not TIMELAPSE_ROOT.exists():
        return
    for uuid_dir in TIMELAPSE_ROOT.iterdir():
        video_dir = uuid_dir / "video"
        if not video_dir.exists():
            continue
        for f in video_dir.iterdir():
            m = re.search(r"parsed_v1_(\d+)_", f.name)
            if not m:
                continue
            ts = int(m.group(1))
            if ts > 1e12:
                ts //= 1000  # milliseconds → seconds
            try:
                d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                dates[d]["timelapse"] = True
            except (OSError, OverflowError):
                continue

# ── Source 5: Photos from manifest.json ───────────────────────────────────────
def scan_manifest(dates: defaultdict):
    if not MANIFEST_FILE.exists():
        return
    m = json.loads(MANIFEST_FILE.read_text())
    entries = m if isinstance(m, list) else m.get("entries", [])
    for e in entries:
        ts = e.get("timestamp", "")
        if len(ts) >= 8:
            raw = ts[:8]
            try:
                d = iso(date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8])))
                dates[d]["photos"] = True
            except ValueError:
                continue

# ── Source 6: Cell footage ────────────────────────────────────────────────────
def scan_cell_footage(dates: defaultdict):
    if not CELL_FOOTAGE.exists():
        return
    for f in CELL_FOOTAGE.iterdir():
        m = re.search(r"VID(\d{8})", f.name)
        if not m:
            continue
        raw = m.group(1)
        try:
            d = iso(date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8])))
            dates[d]["video_founding"] = True
        except ValueError:
            continue

# ── Source 7: Weather (InfluxDB Ecowitt, known start date) ────────────────────
def scan_weather(dates: defaultdict):
    today = date.today()
    d = WEATHER_START
    while d <= today:
        dates[iso(d)]["weather"] = True
        d += timedelta(days=1)

# ── Build full date spine ─────────────────────────────────────────────────────
def build_dates_spine(dates: defaultdict) -> dict:
    today = date.today()
    spine = {}
    d = ARCHIVE_START
    while d <= today:
        key = iso(d)
        flags = empty_flags()
        flags.update(dates.get(key, {}))
        spine[key] = flags
        d += timedelta(days=1)
    return spine

# ── Assemble availability.json ────────────────────────────────────────────────
def build_availability(dates: defaultdict) -> dict:
    return {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "coverage_phases": [
            {
                "start":       "2026-03-10",
                "end":         "2026-03-15",
                "type":        "founding",
                "description": "Pre-installation handheld footage",
            },
            {
                "start":       "2026-03-16",
                "end":         "2026-06-05",
                "type":        "sparse",
                "description": "Motion-triggered, intermittent coverage",
            },
            {
                "start":       "2026-06-06",
                "end":         None,
                "type":        "continuous",
                "description": "Full continuous recording",
            },
        ],
        "dates": build_dates_spine(dates),
    }

# ── Git commit + push ─────────────────────────────────────────────────────────
def git_push(file_path):
    rel = str(file_path.relative_to(SCRIPT_DIR))
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "add", rel], check=True)
    diff = subprocess.run(
        ["git", "-C", str(SCRIPT_DIR), "diff", "--cached", "--quiet"], check=False
    )
    if diff.returncode == 0:
        print("availability.json unchanged — no commit.")
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    subprocess.run(
        ["git", "-C", str(SCRIPT_DIR), "commit", "-m",
         f"data: availability.json {ts} UTC"],
        check=True,
    )
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "pull", "--rebase", "--quiet"], check=False)
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "push"], check=True)
    print(f"Pushed availability.json ({ts} UTC)")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    AVAILABILITY_FILE.parent.mkdir(exist_ok=True)

    dates: defaultdict = defaultdict(empty_flags)

    print("Scanning sources...")
    scan_easynvr_sparse(dates);  print(f"  EasyNVR sparse:  {sum(1 for v in dates.values() if v['video_events'])} event dates")
    scan_easynvr_dense(dates);   print(f"  EasyNVR dense:   (cumulative) {sum(1 for v in dates.values() if v['video_events'])} event dates")
    scan_frigate(dates);         print(f"  Frigate:         {sum(1 for v in dates.values() if v['video_continuous'])} continuous, {sum(1 for v in dates.values() if v['video_events'])} event dates total")
    scan_timelapse(dates);       print(f"  Timelapse:       {sum(1 for v in dates.values() if v['timelapse'])} dates")
    scan_manifest(dates);        print(f"  Manifest photos: {sum(1 for v in dates.values() if v['photos'])} dates")
    scan_cell_footage(dates);    print(f"  Cell footage:    {sum(1 for v in dates.values() if v['video_founding'])} dates")
    scan_weather(dates);         print(f"  Weather:         {sum(1 for v in dates.values() if v['weather'])} dates")

    availability = build_availability(dates)
    total_dates  = len(availability["dates"])
    covered      = sum(1 for v in availability["dates"].values() if any(v.values()))

    AVAILABILITY_FILE.write_text(json.dumps(availability, indent=2))
    print(f"\nWrote availability.json: {total_dates} dates in spine, {covered} with coverage")
    git_push(AVAILABILITY_FILE)
