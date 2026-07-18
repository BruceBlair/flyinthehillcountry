#!/usr/bin/env python3
"""
timelapse-builder.py — Ground Truth Network
Groups golden hour snapshots by date + type (sunrise/sunset).
When a session has ≥ MIN_FRAMES it builds a timelapse MP4 and writes an
entry to timelapse_manifest.json.

Output
------
  /highlights/timelapse/{YYYYMMDD}_{sunrise|sunset}_timelapse.mp4
  /highlights/timelapse_manifest.json

Usage
-----
  python3 timelapse_builder.py [--highlights-dir /volume1/highlights] [--dry-run]

  # Via Docker:
  docker run --rm \\
    -v /volume1/highlights:/highlights \\
    weather-station-highlight-curator \\
    python3 /app/timelapse_builder.py --highlights-dir /highlights
"""

import argparse
import json
import logging
import os
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def apply_cpulimit(pid: int, cpu_percent: int) -> None:
    try:
        subprocess.Popen(
            ["cpulimit", f"--limit={cpu_percent}", f"--pid={pid}", "--background"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("timelapse")

HIGHLIGHTS_DIR = "/volume1/highlights"
MIN_FRAMES     = 3    # minimum frames per session to build a timelapse
MAX_FRAMES     = 250  # cap per timelapse; longer sessions split into parts
FRAME_DURATION = 0.12  # seconds each frame is shown (~8 fps)


# ── Core builder ─────────────────────────────────────────────────────────────
def _build_one(frames: list[Path], out_path: Path, cpu_percent: int | None) -> bool:
    """Encode one timelapse MP4 from a list of frames. Returns True on success."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, dir="/tmp") as fl:
        for frame in frames:
            fl.write(f"file '{frame}'\n")
            fl.write(f"duration {FRAME_DURATION}\n")
        fl.write(f"file '{frames[-1]}'\n")   # final frame — no duration needed
        filelist = fl.name
    try:
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-f", "concat", "-safe", "0",
            "-i", filelist,
            "-vf", "scale='min(1920,iw)':-2:flags=lanczos,format=yuv420p",
            "-c:v", "libx264", "-crf", "20", "-preset", "slow",
            "-movflags", "+faststart",
            "-y", str(out_path),
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if cpu_percent:
            apply_cpulimit(proc.pid, cpu_percent)
        _, stderr = proc.communicate()
        if proc.returncode != 0:
            log.error(f"    ffmpeg error: {stderr[:400]}")
            return False
        return True
    finally:
        try:
            os.unlink(filelist)
        except OSError:
            pass


def build_timelapses(highlights: Path, min_frames: int, max_frames: int,
                     dry_run: bool, cpu_percent: int | None = None):
    timelapse_dir = highlights / "timelapse"

    # ── Collect frames, grouped by date+type ─────────────────────────────────
    sessions: dict[str, list[Path]] = defaultdict(list)
    for golden_type in ("sunrise", "sunset"):
        src_dir = highlights / "golden_hour" / golden_type
        if not src_dir.exists():
            continue
        for img in sorted(src_dir.glob("*.jpg")):
            date_key = img.stem[:8]       # "20260316_070101_scene.jpg" → "20260316"
            sessions[f"{date_key}_{golden_type}"].append(img)

    log.info(f"Found {len(sessions)} golden hour sessions")

    # ── Load existing timelapse manifest ──────────────────────────────────────
    tl_mf = highlights / "timelapse_manifest.json"
    tl_manifest   = json.loads(tl_mf.read_text()) if tl_mf.exists() else {"entries": []}
    existing_keys = {e["session_key"] for e in tl_manifest["entries"]}

    built = skipped = 0
    for session_key, frames in sorted(sessions.items()):
        date_str, golden_type = session_key[:8], session_key[9:]
        date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

        if len(frames) < min_frames:
            log.info(f"  {session_key}: {len(frames)} frames — need {min_frames}+ (skip)")
            skipped += 1
            continue

        # Split into chunks of at most max_frames
        chunks = [frames[i:i + max_frames] for i in range(0, len(frames), max_frames)]
        multi  = len(chunks) > 1

        for part_idx, chunk in enumerate(chunks, 1):
            chunk_key  = f"{session_key}_part{part_idx}" if multi else session_key
            out_name   = f"{chunk_key}_timelapse.mp4"
            out_path   = timelapse_dir / out_name

            if chunk_key in existing_keys:
                log.info(f"  {chunk_key}: already built — skip")
                skipped += 1
                continue

            part_label = f" (part {part_idx}/{len(chunks)})" if multi else ""
            log.info(f"  {session_key}{part_label}: {len(chunk)} frames → {out_name}")

            if dry_run:
                continue

            timelapse_dir.mkdir(parents=True, exist_ok=True)

            if not _build_one(chunk, out_path, cpu_percent):
                continue

            size_mb = out_path.stat().st_size / 1_000_000
            log.info(f"    ✓ {out_name}  ({len(chunk)} frames, {size_mb:.1f} MB)")

            # Thumbnail = middle frame of this chunk
            thumb     = chunk[len(chunk) // 2]
            thumb_rel = str(thumb.relative_to(highlights))

            tl_manifest["entries"].insert(0, {
                "session_key": chunk_key,
                "date":        date_fmt,
                "type":        golden_type,
                "frame_count": len(chunk),
                "part":        part_idx if multi else None,
                "total_parts": len(chunks) if multi else None,
                "video":       out_name,
                "thumbnail":   thumb_rel,
                "created":     datetime.now().isoformat(),
            })
            built += 1

    if not dry_run:
        tl_manifest["updated"] = datetime.now().isoformat()
        tl_mf.write_text(json.dumps(tl_manifest, indent=2))
        log.info(f"timelapse_manifest.json written")

    log.info(f"Done — {built} timelapses built, {skipped} skipped")


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--highlights-dir", default=HIGHLIGHTS_DIR)
    p.add_argument("--min-frames", type=int, default=MIN_FRAMES,
                   help=f"Minimum frames per session to build a timelapse (default {MIN_FRAMES})")
    p.add_argument("--max-frames", type=int, default=MAX_FRAMES,
                   help=f"Maximum frames per timelapse; longer sessions split into parts (default {MAX_FRAMES})")
    p.add_argument("--cpu-percent", type=int, default=15, metavar="N",
                   help="Throttle each ffmpeg encode to N%% CPU via cpulimit (default 15)")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would be built without writing files")
    args = p.parse_args()

    build_timelapses(
        Path(args.highlights_dir),
        args.min_frames,
        args.max_frames,
        args.dry_run,
        cpu_percent=args.cpu_percent,
    )


if __name__ == "__main__":
    main()
