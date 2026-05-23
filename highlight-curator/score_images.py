#!/usr/bin/env python3
"""
score-images.py — Ground Truth Network
Analyzes every snapshot in manifest.json and assigns a "nice_shot" score
(0–100). Scores are based on:
  • Warm color density  — golden/amber/pink tones from sunrise/sunset
  • Color saturation    — vivid vs washed-out
  • Tonal contrast      — silhouettes against bright sky
  • Exposure quality    — penalise blown-out or crushed frames
  • Sky/ground split    — bright sky above darker ground = good composition
  • Storm bonus         — deep blue/purple storm tones

After scoring, manifest.json is re-sorted so the highest-scoring entry
appears first (the default gallery view).

Usage
-----
  # Score new images only (skips already-scored entries):
  python3 score_images.py

  # Re-score everything from scratch:
  python3 score_images.py --rescore-all

  # Dry run (no writes, shows top-10 predictions):
  python3 score_images.py --dry-run

  # Run via Docker (same pattern as backfill):
  docker run --rm \\
    -v /volume1/highlights:/highlights \\
    weather-station-highlight-curator \\
    python3 /app/score_images.py --highlights-dir /highlights
"""

import argparse
import json
import logging
from pathlib import Path

from manifest_io import atomic_write_json

from PIL import Image
import numpy as np

# Vote weight: each net upvote adds this many points to nice_shot (0–100 scale).
# Tuned so ~10 upvotes ≈ 5 point boost — meaningful but doesn't override pixel scoring.
VOTE_WEIGHT = 0.5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scorer")

HIGHLIGHTS_DIR = "/volume1/highlights"

# Directories whose images get the SUNSET profile instead of DEFAULT.
SUNSET_DIRS = (
    "/volume1/highlights/golden_hour",
    "/media/camera_timelapse/sunset",
)

# Scoring profiles: weights must sum to 1.0 (storm_bonus is additive, not part of sum).
PROFILES = {
    "DEFAULT": dict(warm=0.30, sat=0.25, contrast=0.20, exposure=0.10, sky=0.10, storm=0.05),
    "SUNSET":  dict(warm=0.30, sat=0.15, contrast=0.25, exposure=0.05, sky=0.20, storm=0.05),
}


def profile_for(path: Path) -> dict:
    p = str(path)
    if any(p.startswith(d) for d in SUNSET_DIRS):
        return PROFILES["SUNSET"]
    return PROFILES["DEFAULT"]


# ── Scoring ───────────────────────────────────────────────────────────────────
def score_image(path: Path) -> float:
    """Return a dramatic-quality score 0–100 for a photo."""
    try:
        img = Image.open(path).convert("RGB")
        img.thumbnail((320, 320), Image.LANCZOS)
        px = np.array(img, dtype=float)

        r, g, b = px[:, :, 0], px[:, :, 1], px[:, :, 2]
        lum = 0.299 * r + 0.587 * g + 0.114 * b

        # 1. Warm colour density — sunset/sunrise (red/orange/gold dominant)
        warm = (r > 140) & (r > g * 1.2) & (r > b * 1.25)
        warm_score = min(warm.mean() * 280, 100)

        # 2. Saturation — vivid colours score higher
        hi = px.max(axis=2)
        lo = px.min(axis=2)
        sat = np.where(hi > 0, (hi - lo) / (hi + 1e-6), 0)
        sat_score = min(sat.mean() * 200, 100)

        # 3. Tonal contrast — dark silhouettes vs bright sky
        contrast_score = min(lum.std() / 55 * 100, 100)

        # 4. Exposure quality — penalise blown-out and underexposed
        blown = ((r > 248) & (g > 248) & (b > 248)).mean()
        dark  = (lum < 25).mean()
        exposure_score = max(0.0, 100 - blown * 500 - dark * 150)

        # 5. Sky-over-ground — bright upper half, darker lower half
        h = lum.shape[0]
        sky_diff = lum[: h // 2].mean() - lum[h // 2 :].mean()
        sky_score = min(max(sky_diff / 35 * 100, 0), 100)

        # 6. Storm bonus — deep blue/purple tones (dramatic weather)
        storm = (b > 100) & (b > r * 1.15) & (lum < 170)
        storm_bonus = min(storm.mean() * 250, 40)

        w = profile_for(path)
        score = (
            warm_score     * w["warm"]
            + sat_score    * w["sat"]
            + contrast_score * w["contrast"]
            + exposure_score * w["exposure"]
            + sky_score    * w["sky"]
            + storm_bonus  * w["storm"]
        )
        return round(float(min(max(score, 0), 100)), 1)
    except Exception as exc:
        log.warning(f"  score failed for {path.name}: {exc}")
        return 0.0


# ── Main logic ────────────────────────────────────────────────────────────────
def load_votes(highlights: Path) -> dict[str, dict]:
    """Return {snapshot_path: {up, down}} from votes.json, or {} if absent."""
    vf = highlights / "votes.json"
    if not vf.exists():
        return {}
    try:
        return json.loads(vf.read_text())
    except Exception as exc:
        log.warning(f"votes.json unreadable: {exc}")
        return {}


def score_and_sort(highlights: Path, rescore_all: bool, dry_run: bool):
    mf = highlights / "manifest.json"
    if not mf.exists():
        log.error(f"manifest.json not found in {highlights}")
        return

    manifest = json.loads(mf.read_text())
    entries  = manifest.get("entries", [])
    votes    = load_votes(highlights)

    if rescore_all:
        for e in entries:
            e.pop("nice_shot", None)
        log.info("Cleared existing scores (--rescore-all)")

    scored = skipped = missing = 0
    for entry in entries:
        snap = entry.get("snapshot")
        if not snap:
            skipped += 1
            continue
        img_path = highlights / snap
        if not img_path.exists():
            missing += 1
            continue
        if "nice_shot" in entry and not rescore_all:
            skipped += 1
            continue
        score = score_image(img_path)
        entry["nice_shot"] = score
        scored += 1

    # Apply vote boost: net upvotes push nice_shot up, net downvotes pull it down
    vote_applied = 0
    for entry in entries:
        snap = entry.get("snapshot")
        if snap and snap in votes:
            v = votes[snap]
            net = v.get("up", 0) - v.get("down", 0)
            base = entry.get("nice_shot") or 0.0
            entry["nice_shot"] = round(min(max(base + net * VOTE_WEIGHT, 0), 100), 1)
            entry["votes"] = {"up": v.get("up", 0), "down": v.get("down", 0)}
            vote_applied += 1

    log.info(
        f"Scored {scored} images  |  skipped {skipped}  |  {missing} not on disk  "
        f"|  {vote_applied} vote adjustments applied"
    )

    # Sort: highest nice_shot first; unscored entries sink to bottom
    entries.sort(key=lambda e: e.get("nice_shot") or -1.0, reverse=True)
    manifest["entries"] = entries

    if dry_run:
        top10 = [(e.get("nice_shot"), e.get("snapshot", "")) for e in entries[:10]]
        log.info("[dry-run] top 10:")
        for rank, (sc, path) in enumerate(top10, 1):
            log.info(f"  #{rank:2d}  {sc:5.1f}  {path}")
    else:
        atomic_write_json(mf, manifest)
        log.info("manifest.json updated and sorted by nice_shot")


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--highlights-dir", default=HIGHLIGHTS_DIR)
    p.add_argument("--rescore-all", action="store_true",
                   help="Remove existing scores and re-score everything")
    p.add_argument("--dry-run",    action="store_true",
                   help="Show what would change without writing")
    args = p.parse_args()

    score_and_sort(Path(args.highlights_dir), args.rescore_all, args.dry_run)


if __name__ == "__main__":
    main()
