#!/usr/bin/env python3
"""
cull_highlights.py — Ground Truth Network
Prunes manifest.json to keep only the best-scored shots per event:

  golden_hour (sunrise / sunset)  → top 3 per nightly session
  weather / storm                  → top 5 per storm event
  wildlife                         → top 1 per animal encounter

"Events" are formed by clustering same-category entries that are close
in time.  Files for pruned entries are deleted from disk.

Run AFTER score_images.py (needs nice_shot scores already set).

Usage:
  # Dry-run — show what would be removed, nothing written:
  python3 cull_highlights.py --dry-run

  # Normal run:
  python3 cull_highlights.py

  # Override limits:
  python3 cull_highlights.py --keep-golden 5 --keep-storm 8 --keep-wildlife 5

  # Via Docker (same container as curator):
  docker exec highlight-curator python3 /app/cull_highlights.py --dry-run
"""

import argparse
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from manifest_io import atomic_write_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("culler")

HIGHLIGHTS_DIR = "/volume1/highlights"

# ── Defaults (override via CLI) ───────────────────────────────────────────────
KEEP_GOLDEN   = 10  # best shots per sunrise/sunset session
KEEP_STORM    = 10  # best shots per storm event
KEEP_WILDLIFE = 10  # best shots per animal encounter

# Time windows for clustering entries into one event
WINDOW_GOLDEN_MIN   = 180   # 3 hours  — one sunrise/sunset session
WINDOW_STORM_MIN    = 240   # 4 hours  — one storm passes through
WINDOW_WILDLIFE_MIN =  30   # 30 min   — same species = one encounter


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        return datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def classify(entry: dict) -> tuple[str, str]:
    """
    Return (bucket, key) for an entry.
      bucket — 'golden', 'storm', 'wildlife', or 'other'
      key    — sub-type used for grouping (e.g. 'sunrise', 'deer')
    """
    cats = entry.get("categories") or []
    for c in cats:
        if "sunrise" in c:
            return "golden", "sunrise"
        if "sunset" in c:
            return "golden", "sunset"
        if c.startswith("weather"):
            return "storm", "storm"
        if c.startswith("wildlife"):
            return "wildlife", (entry.get("label") or "animal").lower()
    return "other", "other"


def cluster_by_time(entries: list, window_minutes: int) -> list[list]:
    """
    Group entries into clusters where consecutive entries (by timestamp)
    are within window_minutes of the previous entry.
    """
    if not entries:
        return []
    sorted_e = sorted(entries, key=lambda e: e.get("timestamp") or "")
    clusters: list[list] = [[sorted_e[0]]]
    for entry in sorted_e[1:]:
        prev_ts = parse_ts(clusters[-1][-1].get("timestamp"))
        this_ts = parse_ts(entry.get("timestamp"))
        if prev_ts and this_ts and (this_ts - prev_ts) <= timedelta(minutes=window_minutes):
            clusters[-1].append(entry)
        else:
            clusters.append([entry])
    return clusters


def delete_files(entry: dict, highlights: Path) -> None:
    for field in ("snapshot", "clip"):
        rel = entry.get(field)
        if rel:
            p = highlights / rel
            if p.exists():
                p.unlink()
                log.info(f"    deleted  {rel}")


# ── Core culling ──────────────────────────────────────────────────────────────

def cull(manifest_entries: list, keep_n: int, dry_run: bool, highlights: Path) -> tuple[list, int]:
    """
    Keep the top keep_n entries by nice_shot; delete files for the rest.
    Returns (kept_entries, n_removed).
    """
    scored   = sorted(manifest_entries, key=lambda e: e.get("nice_shot") or -1, reverse=True)
    kept     = scored[:keep_n]
    removed  = scored[keep_n:]

    if not dry_run:
        for entry in removed:
            delete_files(entry, highlights)
    else:
        for entry in removed:
            snap = entry.get("snapshot") or entry.get("clip") or "(no file)"
            score = entry.get("nice_shot")
            log.info(f"    [dry-run] would remove  score={score}  {snap}")

    return kept, len(removed)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--highlights-dir",  default=HIGHLIGHTS_DIR)
    ap.add_argument("--keep-golden",     type=int, default=KEEP_GOLDEN,
                    help=f"Best shots per sunrise/sunset session (default {KEEP_GOLDEN})")
    ap.add_argument("--keep-storm",      type=int, default=KEEP_STORM,
                    help=f"Best shots per storm event (default {KEEP_STORM})")
    ap.add_argument("--keep-wildlife",   type=int, default=KEEP_WILDLIFE,
                    help=f"Best shot per animal encounter (default {KEEP_WILDLIFE})")
    ap.add_argument("--dry-run",         action="store_true",
                    help="Show what would be removed without changing anything")
    args = ap.parse_args()

    highlights = Path(args.highlights_dir)
    mf_path    = highlights / "manifest.json"

    if not mf_path.exists():
        log.error(f"manifest.json not found in {highlights}")
        return

    manifest = json.loads(mf_path.read_text())
    entries  = manifest.get("entries", [])
    log.info(f"Loaded {len(entries)} entries from manifest")

    # Warn if many entries are unscored — culler works best after score_images.py
    unscored = sum(1 for e in entries if e.get("nice_shot") is None)
    if unscored:
        log.warning(f"{unscored} entries have no nice_shot score — run score_images.py first for best results")

    # ── Separate entries by bucket ────────────────────────────────────────────
    buckets: dict[tuple, list] = {}   # (bucket, key) → [entries]
    other_entries: list = []

    for entry in entries:
        bucket, key = classify(entry)
        if bucket == "other":
            other_entries.append(entry)
        else:
            buckets.setdefault((bucket, key), []).append(entry)

    total_removed = 0
    kept_entries: list = []

    # ── Golden hour — cluster by session, keep top N per session ─────────────
    for (bucket, key), group in buckets.items():
        if bucket != "golden":
            continue
        clusters = cluster_by_time(group, WINDOW_GOLDEN_MIN)
        log.info(f"Golden-hour {key}: {len(group)} entries in {len(clusters)} session(s)")
        for i, cluster in enumerate(clusters, 1):
            ts_start = cluster[0].get("timestamp", "?")
            log.info(f"  Session {i} ({ts_start}): {len(cluster)} entries → keeping best {args.keep_golden}")
            kept, n_rm = cull(cluster, args.keep_golden, args.dry_run, highlights)
            kept_entries.extend(kept)
            total_removed += n_rm

    # ── Storm / weather — cluster by event, keep top N per event ─────────────
    for (bucket, key), group in buckets.items():
        if bucket != "storm":
            continue
        clusters = cluster_by_time(group, WINDOW_STORM_MIN)
        log.info(f"Weather: {len(group)} entries in {len(clusters)} storm event(s)")
        for i, cluster in enumerate(clusters, 1):
            ts_start = cluster[0].get("timestamp", "?")
            log.info(f"  Storm {i} ({ts_start}): {len(cluster)} entries → keeping best {args.keep_storm}")
            kept, n_rm = cull(cluster, args.keep_storm, args.dry_run, highlights)
            kept_entries.extend(kept)
            total_removed += n_rm

    # ── Wildlife — cluster by species+time, keep top 1 per encounter ─────────
    for (bucket, key), group in buckets.items():
        if bucket != "wildlife":
            continue
        clusters = cluster_by_time(group, WINDOW_WILDLIFE_MIN)
        log.info(f"Wildlife ({key}): {len(group)} entries in {len(clusters)} encounter(s)")
        for i, cluster in enumerate(clusters, 1):
            ts_start = cluster[0].get("timestamp", "?")
            log.info(f"  Encounter {i} ({ts_start}): {len(cluster)} entries → keeping best {args.keep_wildlife}")
            kept, n_rm = cull(cluster, args.keep_wildlife, args.dry_run, highlights)
            kept_entries.extend(kept)
            total_removed += n_rm

    # ── Preserve uncategorised entries (clips, misc) ──────────────────────────
    kept_entries.extend(other_entries)

    # ── Write updated manifest ────────────────────────────────────────────────
    kept_entries.sort(key=lambda e: e.get("nice_shot") or -1, reverse=True)

    if args.dry_run:
        log.info(f"[dry-run] would remove {total_removed} entries, keeping {len(kept_entries)}")
    else:
        manifest["entries"] = kept_entries
        manifest["updated"] = datetime.now().isoformat()
        atomic_write_json(mf_path, manifest)
        log.info(f"Done — removed {total_removed} entries, {len(kept_entries)} remain in manifest")


if __name__ == "__main__":
    main()
