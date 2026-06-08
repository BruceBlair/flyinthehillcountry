#!/usr/bin/env python3
"""
tag-cell-footage.py — Create missing manifest entries for cell footage clips
and apply stock priority tags to all 10 founding footage entries.

Run once. Idempotent: skips entries that already exist.
"""

import json, os
from datetime import datetime, timezone
from pathlib import Path

MANIFEST    = Path(__file__).parent / "manifest.json"
SNAPSHOT_DIR = "golden_hour/sunset"  # relative to weather-station root

# All 10 cell footage clips: timestamp → metadata
CELL_CLIPS = {
    "20260310_201952": {
        "snapshot":    f"{SNAPSHOT_DIR}/20260310_201952_scene.jpg",
        "duration_s":  None,   # snapshot already existed, duration not measured
        "keywords_extra": [],
    },
    "20260310_202034": {
        "snapshot":    f"{SNAPSHOT_DIR}/20260310_202034_scene_cell.jpg",
        "duration_s":  14.9,
        "keywords_extra": [],
    },
    "20260310_202051": {
        "snapshot":    f"{SNAPSHOT_DIR}/20260310_202051_scene_cell.jpg",
        "duration_s":  6.0,
        "keywords_extra": [],
    },
    "20260310_202146": {
        "snapshot":    f"{SNAPSHOT_DIR}/20260310_202146_scene.jpg",
        "duration_s":  None,
        "keywords_extra": [],
    },
    "20260310_202248": {
        "snapshot":    f"{SNAPSHOT_DIR}/20260310_202248_scene_cell.jpg",
        "duration_s":  26.5,
        "keywords_extra": [],
    },
    "20260310_202316": {
        "snapshot":    f"{SNAPSHOT_DIR}/20260310_202316_scene_cell.jpg",
        "duration_s":  15.9,
        "keywords_extra": [],
    },
    "20260310_202358": {
        "snapshot":    f"{SNAPSHOT_DIR}/20260310_202358_scene_cell.jpg",
        "duration_s":  0.7,
        # 0.7s clip — lightning flash illuminating anvil base, NOT the Cessna
        "keywords_extra": ["lightning_flash", "anvil_base", "cloud_illumination"],
        "ai_description": "Lightning flash illuminating the base of anvil cloud. Front foot of anvil lit up by discharge.",
    },
    "20260310_202612": {
        "snapshot":    f"{SNAPSHOT_DIR}/20260310_202612_scene_cell.jpg",
        "duration_s":  14.3,
        "keywords_extra": [],
    },
    "20260310_202628": {
        "snapshot":    f"{SNAPSHOT_DIR}/20260310_202628_scene_cell.jpg",
        "duration_s":  29.1,
        "keywords_extra": [],
    },
    "20260310_202658": {
        "snapshot":    f"{SNAPSHOT_DIR}/20260310_202658_scene_cell.jpg",
        "duration_s":  8.1,
        "keywords_extra": [],
    },
}

# Keywords applied to all 10 founding footage entries
BASE_KEYWORDS = [
    "anvil_cloud",
    "cumulonimbus",
    "lightning_storm",
    "hill_country_ridge",
    "texas_hill_country",
    "severe_weather",
    "thunderstorm",
    "founding_footage",
    "handheld",
    "dusk",
]

def make_entry(timestamp, clip_meta):
    extra_kw = clip_meta.get("keywords_extra", [])
    desc = clip_meta.get("ai_description", "")
    return {
        "timestamp":         timestamp,
        "label":             "storm",
        "score":             None,
        "categories":        ["weather"],
        "camera":            "cell_phone",
        "event_id":          None,
        "snapshot":          clip_meta["snapshot"],
        "clip":              f"camera_raw/cell footage/VID{timestamp.replace('_','')}.mp4",
        "source":            "cell_footage",
        "nice_shot":         None,
        "flags":             {"crop": False, "enhance": False, "auth_hold": False},
        "uploads":           {},
        "votes":             {"up": 0, "down": 0},
        "status":            "pending_review",
        "stock_priority":    "high",
        "published_to":      {"shutterstock": None, "adobe_stock": None},
        "ai_keywords":       BASE_KEYWORDS + extra_kw,
        "ai_description":    desc,
        "weather_at_capture": None,
    }

def main():
    data    = json.loads(MANIFEST.read_text())
    entries = data["entries"]

    existing_ts = {e["timestamp"] for e in entries}
    created = 0
    updated = 0

    for ts, meta in CELL_CLIPS.items():
        if ts not in existing_ts:
            entries.append(make_entry(ts, meta))
            created += 1
            print(f"  CREATED  {ts}")
        else:
            # Update in-place — apply stock priority tags
            for e in entries:
                if e["timestamp"] == ts:
                    changed = []
                    if e.get("status") != "pending_review":
                        e["status"] = "pending_review"
                        changed.append("status")
                    if e.get("stock_priority") != "high":
                        e["stock_priority"] = "high"
                        changed.append("stock_priority")
                    if e.get("label") != "storm":
                        e["label"] = "storm"
                        changed.append("label")
                    # Merge keywords without duplication
                    existing_kw = set(e.get("ai_keywords") or [])
                    new_kw = set(BASE_KEYWORDS + meta.get("keywords_extra", []))
                    if not new_kw.issubset(existing_kw):
                        e["ai_keywords"] = sorted(existing_kw | new_kw)
                        changed.append("ai_keywords")
                    if meta.get("ai_description") and not e.get("ai_description"):
                        e["ai_description"] = meta["ai_description"]
                        changed.append("ai_description")
                    break
            updated += 1
            print(f"  UPDATED  {ts}")

    # Sort entries by timestamp for consistency
    entries.sort(key=lambda e: e.get("timestamp", ""))
    data["entries"]  = entries
    data["updated"]  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, MANIFEST)

    print(f"\nDone: {created} created, {updated} updated → {len(entries)} total entries")
    print("NOTE: Review 20260310_202358 (0.7s) to confirm aircraft type.")

if __name__ == "__main__":
    main()
