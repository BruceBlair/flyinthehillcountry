#!/usr/bin/env python3
"""
push-wildlife.py — Aggregate audio-scout's raw detection manifest
(154K+ records) into a per-species summary, write data/wildlife-species.json
(~186 entries), and git-push to GitHub.

Per design spec (docs/superpowers/specs/2026-07-15-hithc-gtn-depot-design.md
 §4): this is a summary, not a growing per-event feed. Representative photos
and audio clips are hand-curated, not auto-picked from raw detections — see
CURATED_FILE below. A species with no curated entry yet shows as
"not yet curated" on the site rather than silently getting an unreviewed
photo auto-attached.

Cron (every 30 min — the manifest is large; no need for 5-min freshness):
  */30 * * * * /usr/bin/python3 /home/HighlyReflective/hithc-gtn-depot/push-wildlife.py >> /home/HighlyReflective/push-wildlife.log 2>&1
"""

import json, subprocess, sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR     = Path(__file__).parent
WILDLIFE_FILE  = SCRIPT_DIR / "data" / "wildlife-species.json"
CURATED_FILE   = SCRIPT_DIR / "data" / "wildlife-curated.json"
MANIFEST_PATH  = Path("/volume1/highlights/audio_manifest.json")

# YAMNet labels that aren't a wildlife species — ambient/domestic noise the
# classifier surfaces for other reasons (see audio-scout/classifier.py
# _YAMNET_KEEP). Excluded from the per-species conservancy summary.
NON_SPECIES_LABELS = {
    "Dog", "Cat", "Horse", "Cattle",
    "Rain", "Thunder", "Wind", "Vehicle",
    "Animal", "Wild animals",
}

MIN_CONFIDENCE = 0.5   # defensive floor; manifest entries are normally already thresholded upstream
QUIET_AFTER_DAYS = 30  # "gone quiet" flag

def parse_ts(ts: str):
    try:
        return datetime.strptime(ts, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def population_estimate(max_daily_count: int) -> str:
    if max_daily_count <= 3:
        return "Occasional (estimate: 1 individual)"
    if max_daily_count <= 10:
        return "Regular presence (estimate: 2-3 individuals)"
    return "Abundant activity (estimate: 4+ individuals)"

def load_curated():
    if CURATED_FILE.exists():
        return json.loads(CURATED_FILE.read_text())
    return {}

def build_wildlife(manifest: dict, curated: dict):
    now = datetime.now(timezone.utc)
    by_species = defaultdict(lambda: {
        "scientific_name": None,
        "species_info": {},
        "detections_by_day": defaultdict(int),
        "hourly_activity": [0] * 24,
        "first_seen": None,
        "last_seen": None,
        "total_detections": 0,
    })

    skipped_non_species = 0
    skipped_low_confidence = 0
    skipped_unparsable = 0

    for d in manifest.get("detections", []):
        species = d.get("species")
        if not species or species in NON_SPECIES_LABELS:
            skipped_non_species += 1
            continue
        if (d.get("confidence") or 0) < MIN_CONFIDENCE:
            skipped_low_confidence += 1
            continue
        ts = parse_ts(d.get("timestamp", ""))
        if ts is None:
            skipped_unparsable += 1
            continue

        rec = by_species[species]
        rec["total_detections"] += 1
        rec["hourly_activity"][ts.hour] += 1
        rec["detections_by_day"][ts.strftime("%Y-%m-%d")] += 1
        if rec["first_seen"] is None or ts < rec["first_seen"]:
            rec["first_seen"] = ts
        if rec["last_seen"] is None or ts > rec["last_seen"]:
            rec["last_seen"] = ts
        if not rec["scientific_name"] and d.get("scientific_name"):
            rec["scientific_name"] = d["scientific_name"]
        if not rec["species_info"] and d.get("species_info"):
            rec["species_info"] = d["species_info"]

    species_out = []
    for species, rec in by_species.items():
        max_daily = max(rec["detections_by_day"].values()) if rec["detections_by_day"] else 0
        gone_quiet = rec["last_seen"] is not None and (now - rec["last_seen"]) > timedelta(days=QUIET_AFTER_DAYS)
        curated_entry = curated.get(species, {})
        species_out.append({
            "species": species,
            "scientific_name": rec["scientific_name"],
            "family": rec["species_info"].get("family") or None,
            "conservation_status": rec["species_info"].get("conservation_status") or None,
            "description": rec["species_info"].get("description") or None,
            "representative_photo": curated_entry.get("photo"),
            "representative_audio_clip": curated_entry.get("audio_clip"),
            "curated": species in curated,
            "first_identified": rec["first_seen"].strftime("%Y-%m-%d") if rec["first_seen"] else None,
            "last_seen": rec["last_seen"].strftime("%Y-%m-%d") if rec["last_seen"] else None,
            "gone_quiet": gone_quiet,
            "total_detections": rec["total_detections"],
            "hourly_activity": rec["hourly_activity"],
            "population_estimate": population_estimate(max_daily),
        })

    species_out.sort(key=lambda s: s["total_detections"], reverse=True)

    return {
        "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_manifest_updated": manifest.get("updated"),
        "species_count": len(species_out),
        "skipped": {
            "non_species_labels": skipped_non_species,
            "low_confidence": skipped_low_confidence,
            "unparsable_timestamp": skipped_unparsable,
        },
        "species": species_out,
    }

def git_push(file_path):
    rel = str(file_path.relative_to(SCRIPT_DIR))
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "add", rel], check=True)
    diff = subprocess.run(["git", "-C", str(SCRIPT_DIR), "diff", "--cached", "--quiet"], check=False)
    if diff.returncode == 0:
        print("wildlife-species.json unchanged — no commit.")
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    subprocess.run(["git", "-C", str(SCRIPT_DIR), "commit", "-m", f"data: wildlife-species.json {ts} UTC", "--", rel], check=True)
    remotes = subprocess.run(["git", "-C", str(SCRIPT_DIR), "remote"], capture_output=True, text=True, check=False)
    if remotes.stdout.strip():
        subprocess.run(["git", "-C", str(SCRIPT_DIR), "push"], check=False)
    print(f"Committed wildlife-species.json ({ts} UTC) — deployed to senselayer.io via push-site.sh, not this repo's own remote.")

if __name__ == "__main__":
    WILDLIFE_FILE.parent.mkdir(exist_ok=True)
    try:
        manifest = json.loads(MANIFEST_PATH.read_text())
        curated  = load_curated()
        wildlife = build_wildlife(manifest, curated)
        WILDLIFE_FILE.write_text(json.dumps(wildlife, indent=2))
        print(f"Wrote wildlife-species.json ({wildlife['species_count']} species, "
              f"skipped {wildlife['skipped']})")
        git_push(WILDLIFE_FILE)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
