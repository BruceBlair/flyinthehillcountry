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


def extract_frames(segments: list[Path], start_dt: datetime, end_dt: datetime,
                   interval_secs: int, out_dir: Path,
                   on_progress: Callable[[int], None] | None = None) -> list[Path]:
    """
    Extract one frame every interval_secs from Frigate segments overlapping
    [start_dt, end_dt]. Frames written to out_dir as JPEG, returned sorted.

    on_progress(n) is called after each segment with the cumulative frame count.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    all_frames: list[Path] = []

    for i, seg in enumerate(segments):
        seg_start = _parse_segment_time(seg)
        if seg_start is None:
            continue

        to_secs = (end_dt - seg_start).total_seconds()
        if to_secs <= 0:
            continue  # segment starts after window ends

        ss_secs = max(0.0, (start_dt - seg_start).total_seconds())
        seg_out = out_dir / f"{i:04d}"
        seg_out.mkdir(exist_ok=True)

        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-ss", str(ss_secs), "-to", str(to_secs),
            "-i", str(seg),
            "-vf", f"fps=1/{interval_secs}",
            str(seg_out / "frame_%06d.jpg"),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log.warning(f"ffmpeg failed for {seg.name}: {result.stderr[:300]}")
            continue

        seg_frames = sorted(seg_out.glob("frame_*.jpg"))
        all_frames.extend(seg_frames)

        if on_progress:
            on_progress(len(all_frames))

    return sorted(all_frames)
