#!/usr/bin/env python3
"""
audio-backfill.py — analyze historical .mp4 files for wildlife sounds.

Usage:
  python3 audio-backfill.py [--cpu-percent N] [--since YYYY-MM-DD] [--dry-run] <directory>

Examples:
  python3 audio-backfill.py --cpu-percent 25 /volume1/camera_raw/05072026/
  python3 audio-backfill.py --cpu-percent 15 --since 2026-05-01 /volume1/camera_raw/
  python3 audio-backfill.py --dry-run /volume1/camera_raw/05072026/
"""
import argparse
import io
import json
import logging
import os
import subprocess
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

# Add audio-scout to path for shared modules
sys.path.insert(0, str(Path(__file__).parent / "audio-scout"))

from classifier import classify_chunk, filter_detections, BIRDNET_CONFIDENCE, YAMNET_CONFIDENCE
from manifest_io import load_manifest, save_manifest, add_detection
from species_cache import lookup_species

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [audio-backfill] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("audio-backfill")

HIGHLIGHTS_DIR  = Path(os.getenv("HIGHLIGHTS_DIR", "/volume1/highlights"))
MANIFEST_PATH   = HIGHLIGHTS_DIR / "audio_manifest.json"
AUDIO_DIR       = HIGHLIGHTS_DIR / "audio"
PROGRESS_PATH   = HIGHLIGHTS_DIR / "audio" / "backfill_progress.json"
SAMPLE_RATE     = 48000
CHUNK_SEC       = 3
CHUNK_BYTES     = SAMPLE_RATE * 2 * CHUNK_SEC


def apply_cpulimit(cpu_percent: int) -> None:
    try:
        subprocess.run(
            ["cpulimit", f"--limit={cpu_percent}", f"--pid={os.getpid()}", "--background"],
            check=True, capture_output=True,
        )
        log.info("cpulimit applied: %d%%", cpu_percent)
    except FileNotFoundError:
        log.warning("cpulimit not installed — running unthrottled")
    except subprocess.CalledProcessError as e:
        log.warning("cpulimit failed: %s — running unthrottled", e)


def find_mp4_files(directory: Path, since: datetime | None) -> list[Path]:
    files = sorted(directory.rglob("*.mp4"))
    if since:
        files = [f for f in files
                 if datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc) >= since]
    return files


def extract_audio_chunks(mp4_path: Path):
    """Yield (timestamp_str, pcm_bytes) for each 3s chunk in the file."""
    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-i", str(mp4_path),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-f", "s16le", "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    chunk_index = 0
    try:
        while True:
            chunk = proc.stdout.read(CHUNK_BYTES)
            if len(chunk) < CHUNK_BYTES:
                break
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            yield ts, chunk
            chunk_index += 1
    finally:
        proc.terminate()
        proc.wait()


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text())
        except Exception:
            pass
    return {"completed": [], "in_progress": None}


def save_progress(progress: dict) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps(progress, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("directory", type=Path, help="Directory to scan for .mp4 files")
    parser.add_argument("--cpu-percent", type=int, default=25,
                        help="CPU usage cap via cpulimit (default: 25)")
    parser.add_argument("--since", type=str, default=None,
                        help="Only process files modified on or after YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be analyzed without processing")
    args = parser.parse_args()

    since_dt = (
        datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.since else None
    )

    files = find_mp4_files(args.directory, since_dt)
    manifest = load_manifest(MANIFEST_PATH)
    already_done = set(manifest.analyzed_sources)
    pending = [f for f in files if str(f) not in already_done]

    log.info("Found %d .mp4 files, %d pending analysis", len(files), len(pending))

    if args.dry_run:
        for f in pending:
            print(f"  PENDING: {f}")
        print(f"\n{len(pending)} files would be analyzed.")
        return

    if not pending:
        log.info("Nothing to analyze.")
        return

    apply_cpulimit(args.cpu_percent)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    progress = load_progress()

    for mp4 in pending:
        log.info("Analyzing: %s", mp4.name)
        progress["in_progress"] = str(mp4)
        save_progress(progress)

        detections_found = 0
        for ts, chunk in extract_audio_chunks(mp4):
            raw = classify_chunk(chunk, SAMPLE_RATE)
            hits = (
                filter_detections([d for d in raw if d.detector == "birdnet"], BIRDNET_CONFIDENCE)
                + filter_detections([d for d in raw if d.detector == "yamnet"], YAMNET_CONFIDENCE)
            )
            for det in hits:
                slug = det.species.lower().replace(" ", "_")[:30]
                clip_path = AUDIO_DIR / f"{ts}_{slug}.wav"
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(chunk)
                clip_path.write_bytes(buf.getvalue())
                rel = str(clip_path.relative_to(HIGHLIGHTS_DIR))
                info = lookup_species(det.scientific_name) if det.scientific_name else {}
                add_detection(
                    manifest, det,
                    timestamp=ts,
                    clip_path=rel,
                    highlights_manifest=[],
                    species_info=info,
                    source="backfill",
                )
                detections_found += 1

        manifest.analyzed_sources.append(str(mp4))
        save_manifest(manifest, MANIFEST_PATH)
        progress["completed"].append(str(mp4))
        progress["in_progress"] = None
        save_progress(progress)
        log.info("  → %d detections  [%d/%d]",
                 detections_found, len(progress["completed"]), len(pending))

    log.info("Backfill complete.")


if __name__ == "__main__":
    main()
