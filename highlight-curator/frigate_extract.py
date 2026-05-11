#!/usr/bin/env python3
"""
frigate_extract.py — Ground Truth Network
Discovers Frigate recording segments for a time window and extracts
still frames via ffmpeg for timelapse building.

Public API:
    find_segments(start_dt, end_dt, frigate_dir, camera) -> list[Path]
    extract_frames(segments, start_dt, end_dt, interval_secs, out_dir) -> list[Path]
"""

import logging
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

log = logging.getLogger("frigate_extract")

# Frigate's default recording path: {camera}/YYYY-MM-DD/HH/MM.mp4
_SEG_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[/\\](\d{2})[/\\](\d{2})\.mp4$")


def _parse_segment_time(path: Path) -> datetime | None:
    """Return the segment's start datetime from its path, or mtime as fallback."""
    m = _SEG_RE.search(str(path))
    if m:
        try:
            return datetime.strptime(
                f"{m.group(1)} {m.group(2)}:{m.group(3)}:00", "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def find_segments(start_dt: datetime, end_dt: datetime,
                  frigate_dir: Path, camera: str = "trackmix_wide") -> list[Path]:
    """
    Return MP4 segments under frigate_dir/camera that overlap [start_dt, end_dt],
    sorted chronologically. Includes segments starting up to 2h before start_dt
    to catch recordings that began before the window but extend into it.
    """
    cam_dir = frigate_dir / camera
    if not cam_dir.exists():
        return []

    cutoff_early = start_dt - timedelta(hours=2)
    results: list[tuple[datetime, Path]] = []

    for mp4 in cam_dir.rglob("*.mp4"):
        seg_start = _parse_segment_time(mp4)
        if seg_start is None:
            continue
        if cutoff_early <= seg_start <= end_dt:
            results.append((seg_start, mp4))

    return [p for _, p in sorted(results)]
