#!/usr/bin/env python3
"""
scan_stars.py — Ground Truth Network
Scans /highlights/stars/ for new captures, scores them, and writes
stars_manifest.json for the Nightwatch page.

Runs as an infinite loop (SCAN_INTERVAL_SEC between passes, default 300).
Safe to run alongside curator.py — only appends new files.

Filename conventions handled:
  night-sky-patrol: YYYYMMDD_HHMMSS_<target>_<PRESET>.jpg   (flat in stars/)
  star-patrol:      HHMMSS_<target>_<NN>.jpg                 (in stars/YYYYMMDD/)
"""

import io
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

from PIL import Image
import numpy as np

HIGHLIGHTS_DIR  = Path(os.getenv("HIGHLIGHTS_DIR", "/highlights"))
STARS_DIR       = HIGHLIGHTS_DIR / "stars"
MANIFEST_PATH   = HIGHLIGHTS_DIR / "stars_manifest.json"
SCAN_INTERVAL   = int(os.getenv("SCAN_INTERVAL_SEC", "300"))
MAX_ENTRIES     = int(os.getenv("MAX_STAR_ENTRIES", "500"))

COMPASS = {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scan-stars")

# Target-name display overrides (lowercased key → display name)
TARGET_DISPLAY = {
    "moon":            "Moon",
    "venus":           "Venus",
    "mars":            "Mars",
    "jupiter":         "Jupiter",
    "saturn":          "Saturn",
    "sirius":          "Sirius",
    "canopus":         "Canopus",
    "arcturus":        "Arcturus",
    "vega":            "Vega",
    "capella":         "Capella",
    "rigel":           "Rigel",
    "procyon":         "Procyon",
    "betelgeuse":      "Betelgeuse",
    "altair":          "Altair",
    "aldebaran":       "Aldebaran",
    "antares":         "Antares",
    "spica":           "Spica",
    "pollux":          "Pollux",
    "fomalhaut":       "Fomalhaut",
    "deneb":           "Deneb",
    "regulus":         "Regulus",
    "orion_nebula":    "Orion Nebula",
    "orion nebula":    "Orion Nebula",
    "pleiades":        "Pleiades",
    "milky_way_ctr":   "Milky Way Center",
    "milky way ctr":   "Milky Way Center",
    "perseids_meteors":"Perseids Meteors",
    "lyrids_meteors":  "Lyrids Meteors",
    "geminids_meteors":"Geminids Meteors",
    "leonids_meteors": "Leonids Meteors",
    "orionids_meteors":"Orionids Meteors",
}

# ── Filename parsing ──────────────────────────────────────────────────────────
_PATROL_RE  = re.compile(r'^(\d{8})_(\d{6})_(.+)$')   # YYYYMMDD_HHMMSS_rest
_STAR_RE    = re.compile(r'^(\d{6})_(.+)$')             # HHMMSS_rest (in date subdir)


def parse_filename(path: Path) -> dict | None:
    """
    Returns dict with keys: timestamp, target, preset.
    Returns None if the file doesn't match either convention.
    """
    stem = path.stem  # no extension

    m = _PATROL_RE.match(stem)
    if m:
        date, timep, rest = m.groups()
        parts = rest.split('_')
        if len(parts) < 2:
            return None
        last = parts[-1].upper()
        if last in COMPASS:
            target_key = '_'.join(parts[:-1]).lower()
            preset     = last
        else:
            target_key = '_'.join(parts).lower()
            preset     = None
        return {
            "timestamp": f"{date}_{timep}",
            "target":    _display_name(target_key),
            "preset":    preset,
        }

    # Could be star_patrol.py style (in a YYYYMMDD subdir)
    m = _STAR_RE.match(stem)
    if m and path.parent.name.isdigit() and len(path.parent.name) == 8:
        timep, rest = m.groups()
        date  = path.parent.name
        parts = rest.split('_')
        # Last part is a 2-digit seq number
        if parts and re.match(r'^\d{2}$', parts[-1]):
            target_key = '_'.join(parts[:-1]).lower()
        else:
            target_key = '_'.join(parts).lower()
        return {
            "timestamp": f"{date}_{timep}",
            "target":    _display_name(target_key),
            "preset":    None,
        }

    return None


def _display_name(key: str) -> str:
    name = TARGET_DISPLAY.get(key) or TARGET_DISPLAY.get(key.replace('_', ' '))
    if name:
        return name
    # Capitalise words as fallback
    return ' '.join(w.capitalize() for w in key.replace('_', ' ').split())


# ── Scoring (same algorithm as score_images.py) ───────────────────────────────
def score_image(path: Path) -> float:
    try:
        img = Image.open(path).convert("RGB")
        img.thumbnail((320, 320), Image.LANCZOS)
        px  = np.array(img, dtype=float)
        r, g, b = px[:, :, 0], px[:, :, 1], px[:, :, 2]
        lum = 0.299 * r + 0.587 * g + 0.114 * b

        # For star images we care mostly about contrast (stars on dark sky)
        # and penalise blown-out (IR contamination) or fully dark frames.
        contrast_score = min(lum.std() / 55 * 100, 100)

        blown = ((r > 248) & (g > 248) & (b > 248)).mean()
        dark  = (lum < 8).mean()
        exposure_score = max(0.0, 100 - blown * 400 - dark * 80)

        # Point sources: high peak / low mean ratio = interesting sky
        peak_score = min(px.max() / (lum.mean() + 1) * 20, 100)

        # Slight colour bonus (nebulae, aurora, planet colours)
        hi = px.max(axis=2); lo = px.min(axis=2)
        sat        = np.where(hi > 0, (hi - lo) / (hi + 1e-6), 0)
        color_score = min(sat.mean() * 180, 100)

        score = (
            contrast_score * 0.35
            + exposure_score * 0.25
            + peak_score     * 0.25
            + color_score    * 0.15
        )
        return round(float(min(max(score, 0), 100)), 1)
    except Exception as e:
        log.warning(f"Score failed for {path.name}: {e}")
        return 0.0


# ── Manifest ──────────────────────────────────────────────────────────────────
def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except Exception:
            pass
    return {"entries": []}


def save_manifest(manifest: dict) -> None:
    manifest["updated"] = datetime.now().isoformat()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


# ── Scanner ───────────────────────────────────────────────────────────────────
def scan_once() -> int:
    if not STARS_DIR.exists():
        return 0

    manifest = load_manifest()
    known    = {e["snapshot"] for e in manifest.get("entries", [])}
    added    = 0

    # Collect all JPGs (both flat and in date subdirs)
    all_jpgs = sorted(
        STARS_DIR.rglob("*.jpg"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for path in all_jpgs:
        try:
            rel = str(path.relative_to(HIGHLIGHTS_DIR))
        except ValueError:
            continue

        if rel in known:
            continue

        meta = parse_filename(path)
        if meta is None:
            continue

        score = score_image(path)

        entry = {
            "timestamp":  meta["timestamp"],
            "snapshot":   rel,
            "target":     meta["target"],
            "preset":     meta["preset"],
            "nice_shot":  score,
            "categories": ["stars"],
        }
        manifest.setdefault("entries", []).insert(0, entry)
        known.add(rel)
        added += 1

    if added:
        # Trim and sort by newest first (page can re-sort by score)
        manifest["entries"] = manifest["entries"][:MAX_ENTRIES]
        save_manifest(manifest)
        log.info(f"Added {added} new star captures to stars_manifest.json")

    return added


def main() -> None:
    STARS_DIR.mkdir(parents=True, exist_ok=True)
    log.info(f"Star scanner: watching {STARS_DIR}  interval={SCAN_INTERVAL}s")

    while True:
        try:
            scan_once()
        except Exception as e:
            log.error(f"Scan failed: {e}", exc_info=True)
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
