#!/usr/bin/env python3
"""
register_timelapse.py — register daily timelapse sections in manifest.json
and data/availability.json, then commit+push.

Usage: register_timelapse.py <YYYYMMDD> <out_dir>

Called by daily_timelapse.sh after ffmpeg runs.
Idempotent: skips sections already present for that date.
"""
import json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR        = Path(__file__).parent
MANIFEST_FILE     = SCRIPT_DIR / "manifest.json"
AVAILABILITY_FILE = SCRIPT_DIR / "data" / "availability.json"

SECTIONS = ["sunrise", "day_1", "day_2", "sunset"]


def load_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))


def register(datestr: str, out_dir: str):
    out = Path(out_dir)
    date_iso = f"{datestr[:4]}-{datestr[4:6]}-{datestr[6:8]}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── manifest.json ────────────────────────────────────────────────────────
    m = load_json(MANIFEST_FILE)
    entries = m.get("entries", [])

    existing_sections = {
        e["section"]
        for e in entries
        if "timelapse" in e.get("categories", [])
        and e.get("timestamp", "")[:8] == datestr
        and "section" in e
    }

    added_sections: dict[str, str] = {}
    for section in SECTIONS:
        mp4 = out / f"{datestr}_{section}.mp4"
        if not mp4.exists():
            print(f"  skip {section}: {mp4.name} not found")
            continue
        clip = f"timelapse/{datestr}/{datestr}_{section}.mp4"
        if section not in existing_sections:
            entries.append({
                "timestamp": f"{datestr}_000000",
                "label": "timelapse",
                "section": section,
                "categories": ["timelapse"],
                "snapshot": None,
                "clip": clip,
                "source": "daily-timelapse",
            })
            print(f"  manifest: added {section}")
        else:
            print(f"  manifest: {section} already present, skipping")
            clip = next(
                e["clip"]
                for e in entries
                if e.get("section") == section and e.get("timestamp", "")[:8] == datestr
            )
        added_sections[section] = clip

    m["entries"] = entries
    m["updated"] = now
    save_json(MANIFEST_FILE, m)

    # ── data/availability.json ───────────────────────────────────────────────
    avail = load_json(AVAILABILITY_FILE)
    dates = avail.get("dates", {})
    day = dates.setdefault(date_iso, {
        "photos": False, "weather": False, "video_continuous": False,
        "video_events": False, "video_founding": False, "timelapse": False,
    })
    day["timelapse"] = bool(added_sections)
    if added_sections:
        existing_ts = day.get("timelapse_sections", {})
        existing_ts.update(added_sections)
        day["timelapse_sections"] = existing_ts
    avail["updated"] = now
    save_json(AVAILABILITY_FILE, avail)
    print(f"  availability: timelapse={day['timelapse']} for {date_iso}")

    # ── git commit + push ────────────────────────────────────────────────────
    def run(cmd):
        subprocess.run(cmd, cwd=str(SCRIPT_DIR), check=True)

    run(["git", "add", "manifest.json", "data/availability.json"])
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=str(SCRIPT_DIR)
    )
    if diff.returncode == 0:
        print("No changes to commit.")
        return
    run(["git", "commit", "-m", f"data: timelapse {date_iso} {now}"])
    subprocess.run(
        ["git", "pull", "--rebase", "--autostash", "--quiet"],
        cwd=str(SCRIPT_DIR), check=False
    )
    run(["git", "push"])
    print(f"Pushed timelapse entries for {date_iso}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: register_timelapse.py <YYYYMMDD> <out_dir>", file=sys.stderr)
        sys.exit(1)
    register(sys.argv[1], sys.argv[2])
