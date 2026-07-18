#!/usr/bin/env python3
"""
backfill-highlights.py — Ground Truth Network
Scans existing recordings and DB to extract highlights into /volume1/highlights/.

Modes
-----
  events  — query Frigate DB for past detections, fetch snapshot + clip via API
  scenes  — ffmpeg scene-change detection on Frigate recordings
  raw     — process /volume1/camera_raw/ archive (EasyNVR, Hill Country clips,
             cell footage); auto-detects golden hour vs weather events
  both    — events + scenes (default)

Examples
--------
  # Process the entire camera_raw archive:
  python3 backfill-highlights.py --mode raw

  # Dry run to see what would be extracted:
  python3 backfill-highlights.py --mode raw --dry-run

  # Only a date range:
  python3 backfill-highlights.py --mode raw --start-date 2026-03-16 --end-date 2026-03-19

  # More sensitive scene detection (lower threshold = more frames):
  python3 backfill-highlights.py --mode raw --scene-threshold 0.25

  # Frigate DB wildlife events:
  python3 backfill-highlights.py --mode events --start-date 2026-03-20
"""

import argparse
import json
import logging
import os
import re

def _atomic_write_json(path, data):
    import tempfile
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)

import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


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


def run_ffmpeg(cmd: list, cpu_percent: int | None) -> subprocess.CompletedProcess:
    """Run an ffmpeg command, optionally throttling the process via cpulimit."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if cpu_percent:
        try:
            subprocess.Popen(
                ["cpulimit", f"--limit={cpu_percent}", f"--pid={proc.pid}", "--background"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass
    stdout, stderr = proc.communicate()
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)

import requests
from astral import LocationInfo
from astral.sun import sun

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")

# ── Defaults ──────────────────────────────────────────────────────────────────
FRIGATE_DB     = "/volume1/docker/frigate/config/frigate.db"
FRIGATE_API    = "http://localhost:5000"
FRIGATE_MEDIA  = "/volume1/docker/frigate/media/recordings"
HIGHLIGHTS_DIR = "/volume1/highlights"
CAMERAS        = ["trackmix_wide", "trackmix_zoom"]
RAW_DIR        = "/volume1/camera_raw"

# Location — Wimberley TX
LOCATION = LocationInfo(
    name="Wimberley", region="TX",
    latitude=29.9974, longitude=-98.0986,
    timezone="America/Chicago",
)
GOLDEN_MINUTES = 45

# Labels considered wildlife highlights
WILDLIFE_LABELS = {
    "bird", "deer", "fox", "bear", "rabbit", "squirrel",
    "raccoon", "turkey", "dog", "cat", "cow", "horse",
}

# ffmpeg: scene-change score 0–1 (lower = more sensitive / more frames extracted)
DEFAULT_SCENE_THRESHOLD = 0.35


# ── Helpers ───────────────────────────────────────────────────────────────────
def save_bytes(path: Path, data: bytes, dry_run: bool) -> bool:
    if dry_run:
        log.info(f"    [dry-run] would save {path}")
        return True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        log.info(f"    saved  {path}")
        return True
    except OSError as e:
        log.error(f"    write failed: {e}")
        return False


def save_file(src: Path, dest: Path, dry_run: bool) -> bool:
    if dry_run:
        log.info(f"    [dry-run] would save {dest}")
        return True
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        log.info(f"    saved  {dest}")
        return True
    except OSError as e:
        log.error(f"    copy failed: {e}")
        return False


def fetch(url: str, timeout: int = 60) -> bytes | None:
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.content
        log.warning(f"    HTTP {r.status_code}  {url}")
    except requests.RequestException as e:
        log.error(f"    request error: {e}")
    return None


def update_manifest(highlights: Path, entry: dict, dry_run: bool):
    if dry_run:
        return
    mf = highlights / "manifest.json"
    try:
        manifest = json.loads(mf.read_text()) if mf.exists() else {"entries": []}
        # Skip duplicates by event_id
        if entry.get("event_id") and any(
            e.get("event_id") == entry["event_id"] for e in manifest["entries"]
        ):
            return
        manifest["entries"].insert(0, entry)
        manifest["entries"] = manifest["entries"][:2000]
        manifest["updated"] = datetime.now().isoformat()
        _atomic_write_json(mf, manifest)
    except Exception as e:
        log.error(f"    manifest update failed: {e}")


# ── Golden hour helper ────────────────────────────────────────────────────────
def golden_hour_status(dt: datetime) -> tuple[bool, str | None]:
    """Return (True, 'sunrise'|'sunset') if dt falls within the golden window."""
    try:
        s = sun(LOCATION.observer, date=dt.date(), tzinfo=LOCATION.tzinfo)
        window = timedelta(minutes=GOLDEN_MINUTES)
        if abs(dt - s["sunrise"].replace(tzinfo=None)) <= window:
            return True, "sunrise"
        if abs(dt - s["sunset"].replace(tzinfo=None)) <= window:
            return True, "sunset"
    except Exception:
        pass
    return False, None


# ── Raw archive timestamp parser ──────────────────────────────────────────────
def parse_raw_timestamp(path: Path) -> datetime | None:
    name = path.stem

    # EasyNVR: 20260316165641-61978
    m = re.match(r"(\d{14})-\d+$", name)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
        except ValueError:
            pass

    # Cell footage: VID20260310201952
    m = re.match(r"VID(\d{14})$", name)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
        except ValueError:
            pass

    # Hill Country NVR: "High Res In The Hill CountryCH01-01-075523-075554"
    # Date is in the parent folder name: MMDDYYYY
    m = re.search(r"CH\d+-\d+-(\d{6})-\d{6}$", name)
    if m:
        folder = path.parent.name
        dm = re.match(r"(\d{2})(\d{2})(\d{4})$", folder)
        if dm:
            try:
                date_str = f"{dm.group(3)}{dm.group(1)}{dm.group(2)}"
                return datetime.strptime(date_str + m.group(1), "%Y%m%d%H%M%S")
            except ValueError:
                pass

    # Fallback: file modification time
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


# ── Mode: raw archive ─────────────────────────────────────────────────────────
def run_raw_archive(args, highlights: Path):
    log.info("── Mode: raw archive ────────────────────────────────────────────")

    raw_root = Path(args.raw_dir)
    if not raw_root.exists():
        log.error(f"Raw dir not found: {raw_root}")
        return

    # Collect all video + image files, skip NAS recycle bins
    SKIP_DIRS = {"#recycle", "#snapshot", "@eaDir"}
    all_files: list[tuple[Path, datetime]] = []

    for path in sorted(raw_root.rglob("*")):
        if any(s in path.parts for s in SKIP_DIRS):
            continue
        if path.suffix.lower() not in {".mp4", ".avi", ".mkv", ".mov", ".jpg", ".jpeg", ".png"}:
            continue
        if not path.is_file():
            continue

        dt = parse_raw_timestamp(path)
        if dt is None:
            continue

        if args.start_date:
            if dt < datetime.fromisoformat(args.start_date):
                continue
        if args.end_date:
            if dt >= datetime.fromisoformat(args.end_date) + timedelta(days=1):
                continue

        all_files.append((path, dt))

    videos = [(p, dt) for p, dt in all_files if p.suffix.lower() not in {".jpg", ".jpeg", ".png"}]
    images = [(p, dt) for p, dt in all_files if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]

    log.info(f"Found {len(videos)} video files and {len(images)} images to process")

    if args.dry_run:
        golden = [(p, dt) for p, dt in videos if golden_hour_status(dt)[0]]
        other  = [(p, dt) for p, dt in videos if not golden_hour_status(dt)[0]]
        log.info(f"  [dry-run] {len(golden)} files fall in golden hour windows")
        log.info(f"  [dry-run] {len(other)} files will get scene-change detection")
        log.info(f"  [dry-run] {len(images)} images will be copied directly")
        return

    # ── Images: copy directly to appropriate bucket ───────────────────────────
    img_saved = 0
    for path, dt in images:
        is_golden, golden_type = golden_hour_status(dt)
        if is_golden:
            category = f"golden_hour/{golden_type}"
        else:
            category = "weather"
        ts       = dt.strftime("%Y%m%d_%H%M%S")
        dest     = highlights / category / f"{ts}_{path.name}"
        if dest.exists():
            continue
        if save_file(path, dest, dry_run=False):
            img_saved += 1
            update_manifest(highlights, {
                "timestamp": ts, "label": golden_type or "scene",
                "score": None, "categories": [category],
                "camera": "camera_raw", "event_id": None,
                "snapshot": f"{category}/{ts}_{path.name}",
                "clip": None, "source": "backfill_raw",
            }, dry_run=False)

    log.info(f"Images copied: {img_saved}")

    # ── Videos: golden hour → periodic frames; others → scene detection ───────
    vid_saved = 0
    for path, dt in videos:
        is_golden, golden_type = golden_hour_status(dt)
        if is_golden:
            n = extract_periodic_frames(path, dt, golden_type, highlights,
                                        cpu_percent=args.cpu_percent)
        else:
            n = extract_scene_frames(path, dt, "camera_raw", highlights,
                                     args.scene_threshold, dry_run=False,
                                     cpu_percent=args.cpu_percent)
        vid_saved += n

    log.info(f"Video frames extracted: {vid_saved}")
    log.info(f"Raw archive done — total saved: {img_saved + vid_saved}")


def extract_periodic_frames(
    video: Path, dt: datetime, golden_type: str, highlights: Path,
    interval_sec: int = 30, cpu_percent: int | None = None,
) -> int:
    """Extract one frame every interval_sec seconds (for golden hour footage)."""
    category = f"golden_hour/{golden_type}"
    with tempfile.TemporaryDirectory() as tmp:
        out_pattern = os.path.join(tmp, "frame_%05d.jpg")
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-i", str(video),
            "-vf", f"fps=1/{interval_sec},scale=1280:-2",
            "-q:v", "3",
            out_pattern,
        ]
        run_ffmpeg(cmd, cpu_percent)
        frames = sorted(Path(tmp).glob("frame_*.jpg"))
        if not frames:
            return 0
        log.info(f"  {video.name}  [{golden_type}]  → {len(frames)} frames")
        saved = 0
        for i, frame in enumerate(frames):
            frame_dt = dt + timedelta(seconds=i * interval_sec)
            ts       = frame_dt.strftime("%Y%m%d_%H%M%S")
            dest     = highlights / category / f"{ts}_scene.jpg"
            if dest.exists():
                continue
            if save_file(frame, dest, dry_run=False):
                saved += 1
                update_manifest(highlights, {
                    "timestamp": ts, "label": golden_type,
                    "score": None, "categories": [category],
                    "camera": "camera_raw", "event_id": None,
                    "snapshot": f"{category}/{ts}_scene.jpg",
                    "clip": None, "source": "backfill_raw",
                }, dry_run=False)
        return saved


# ── Mode: events ──────────────────────────────────────────────────────────────
def run_events(args, highlights: Path):
    log.info("── Mode: events ─────────────────────────────────────────────────")

    if not Path(args.frigate_db).exists():
        log.error(f"Frigate DB not found: {args.frigate_db}")
        return

    label_filter = ", ".join(f"'{l}'" for l in WILDLIFE_LABELS)
    wheres = [f"label IN ({label_filter})"]

    if args.start_date:
        wheres.append(f"start_time >= {datetime.fromisoformat(args.start_date).timestamp()}")
    if args.end_date:
        wheres.append(f"start_time < {(datetime.fromisoformat(args.end_date) + timedelta(days=1)).timestamp()}")
    if args.camera:
        wheres.append(f"camera = '{args.camera}'")

    query = f"""
        SELECT id, label, camera, start_time, top_score, has_snapshot, has_clip
        FROM event
        WHERE {' AND '.join(wheres)}
        ORDER BY start_time DESC
    """

    conn = sqlite3.connect(args.frigate_db)
    rows = conn.execute(query).fetchall()
    conn.close()

    log.info(f"Found {len(rows)} matching events in DB")
    if not rows:
        return

    snap_ok = clip_ok = snap_fail = clip_fail = 0

    for event_id, label, camera, start_ts, top_score, has_snap, has_clip in rows:
        ts    = datetime.fromtimestamp(float(start_ts)).strftime("%Y%m%d_%H%M%S")
        score = float(top_score) if top_score else 0.0
        log.info(f"  {ts}  {label:<12} score={score:.2f}  camera={camera}  id={event_id}")

        snap_path = highlights / "wildlife" / f"{ts}_{label}.jpg"
        clip_path = highlights / "wildlife" / f"{ts}_{label}.mp4"

        # Skip if already backfilled
        if snap_path.exists() and not args.force:
            log.info(f"    already exists, skipping (--force to overwrite)")
            continue

        snap_saved = False
        if has_snap:
            data = fetch(f"{args.frigate_api}/api/events/{event_id}/snapshot.jpg")
            if data:
                snap_saved = save_bytes(snap_path, data, args.dry_run)
                if snap_saved:
                    snap_ok += 1
                else:
                    snap_fail += 1
            else:
                log.warning(f"    snapshot not available from API (may have expired)")
                snap_fail += 1

        clip_saved = False
        if has_clip:
            data = fetch(f"{args.frigate_api}/api/events/{event_id}/clip.mp4", timeout=120)
            if data:
                clip_saved = save_bytes(clip_path, data, args.dry_run)
                if clip_saved:
                    clip_ok += 1
                else:
                    clip_fail += 1
            else:
                log.warning(f"    clip not available from API (may have expired)")
                clip_fail += 1

        if snap_saved or clip_saved:
            update_manifest(highlights, {
                "timestamp": ts, "label": label,
                "score": round(score, 3),
                "categories": ["wildlife"],
                "camera": camera, "event_id": event_id,
                "snapshot": f"wildlife/{ts}_{label}.jpg" if snap_saved else None,
                "clip":     f"wildlife/{ts}_{label}.mp4" if clip_saved else None,
                "source": "backfill",
            }, args.dry_run)

    log.info(f"Events done — snapshots: {snap_ok} saved / {snap_fail} failed  "
             f"| clips: {clip_ok} saved / {clip_fail} failed")


# ── Mode: scenes ─────────────────────────────────────────────────────────────
def run_scenes(args, highlights: Path):
    log.info("── Mode: scenes ─────────────────────────────────────────────────")

    media_root = Path(args.frigate_media)
    if not media_root.exists():
        log.error(f"Frigate recordings dir not found: {media_root}")
        return

    # Resolve which cameras to process
    cameras = [args.camera] if args.camera else CAMERAS

    # Collect .mp4 files matching the date range
    # Path structure: {media_root}/{YYYY-MM-DD}/{HH}/{camera}/{MM.SS.mp4}
    all_files: list[Path] = []
    for cam in cameras:
        for mp4 in sorted(media_root.rglob(f"{cam}/*.mp4")):
            # Parse date/hour from path: .../YYYY-MM-DD/HH/camera/MM.SS.mp4
            try:
                parts = mp4.parts
                cam_idx   = parts.index(cam)
                hour_str  = parts[cam_idx - 1]       # "14"
                date_str  = parts[cam_idx - 2]       # "2026-03-25"
                min_sec   = mp4.stem.replace(".", ":")  # "30.00" → "30:00"
                dt = datetime.strptime(f"{date_str} {hour_str}:{min_sec}", "%Y-%m-%d %H:%M:%S")
            except (ValueError, IndexError):
                dt = datetime.fromtimestamp(mp4.stat().st_mtime)

            if args.start_date:
                start = datetime.fromisoformat(args.start_date)
                if dt < start:
                    continue
            if args.end_date:
                end = datetime.fromisoformat(args.end_date) + timedelta(days=1)
                if dt >= end:
                    continue

            all_files.append((mp4, dt, cam))

    log.info(f"Found {len(all_files)} recording segments across cameras: {cameras}")

    if args.dry_run:
        log.info(f"  [dry-run] would run ffmpeg scene detection on {len(all_files)} files")
        log.info(f"  [dry-run] tip: narrow the run with --start-date / --end-date")
        return

    saved = failed = 0
    for mp4, dt, cam in all_files:
        n = extract_scene_frames(mp4, dt, cam, highlights, args.scene_threshold, args.dry_run,
                                 cpu_percent=args.cpu_percent)
        saved += n

    log.info(f"Scenes done — {saved} frames extracted")


def extract_scene_frames(
    video: Path,
    dt: datetime,
    camera: str,
    highlights: Path,
    threshold: float,
    dry_run: bool,
    cpu_percent: int | None = None,
) -> int:
    """
    Use ffmpeg to extract frames where the scene changes significantly.
    Returns the number of frames saved.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out_pattern = os.path.join(tmp, "frame_%05d.jpg")

        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-i", str(video),
            "-vf", f"select='gt(scene,{threshold})',scale=1280:-2",
            "-vsync", "vfr",
            "-q:v", "3",
            out_pattern,
        ]

        result = run_ffmpeg(cmd, cpu_percent)
        if result.returncode != 0 and not Path(tmp).glob("frame_*.jpg"):
            if result.stderr.strip():
                log.debug(f"  ffmpeg stderr: {result.stderr[:300]}")
            return 0

        frames = sorted(Path(tmp).glob("frame_*.jpg"))
        if not frames:
            return 0

        log.info(f"  {video.name}  ({dt.strftime('%Y-%m-%d %H:%M')})  "
                 f"→  {len(frames)} scene-change frames")
        saved = 0
        for i, frame in enumerate(frames):
            # Approximate sub-second offset within the ~1-min recording segment
            frame_dt = dt + timedelta(seconds=i * 2)
            ts = frame_dt.strftime("%Y%m%d_%H%M%S")
            dest_name = f"{ts}_scene_{camera}.jpg"
            dest = highlights / "weather" / dest_name

            if dest.exists() and not dry_run:
                continue  # already extracted

            if save_file(frame, dest, dry_run):
                saved += 1
                update_manifest(highlights, {
                    "timestamp": ts,
                    "label": "scene",
                    "score": None,
                    "categories": ["weather"],
                    "camera": camera,
                    "event_id": None,
                    "snapshot": f"weather/{dest_name}",
                    "clip": None,
                    "source": "backfill_scene",
                }, dry_run)

        return saved


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--mode", default="all", choices=["events", "scenes", "raw", "both", "all"],
                   help="What to run (default: all = events + scenes + raw)")
    p.add_argument("--camera",
                   help=f"Limit to one camera. Options: {CAMERAS}")
    p.add_argument("--start-date", metavar="YYYY-MM-DD",
                   help="Only process recordings/events on or after this date")
    p.add_argument("--end-date",   metavar="YYYY-MM-DD",
                   help="Only process recordings/events on or before this date")
    p.add_argument("--scene-threshold", type=float, default=DEFAULT_SCENE_THRESHOLD,
                   metavar="0-1",
                   help=f"ffmpeg scene-change sensitivity (default {DEFAULT_SCENE_THRESHOLD}). "
                        "Lower = more frames extracted. Try 0.25 for subtle storm skies.")
    p.add_argument("--frigate-db",    default=FRIGATE_DB)
    p.add_argument("--frigate-api",   default=FRIGATE_API)
    p.add_argument("--frigate-media", default=FRIGATE_MEDIA)
    p.add_argument("--raw-dir",       default=RAW_DIR,
                   help="Path to camera_raw archive (used by --mode raw)")
    p.add_argument("--highlights-dir",default=HIGHLIGHTS_DIR)
    p.add_argument("--force", action="store_true",
                   help="Re-download even if output file already exists")
    p.add_argument("--cpu-percent", type=int, default=15, metavar="N",
                   help="Throttle each ffmpeg process to N%% CPU via cpulimit (default 15)")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would be saved without writing any files")
    args = p.parse_args()

    highlights = Path(args.highlights_dir)
    if not args.dry_run:
        highlights.mkdir(parents=True, exist_ok=True)

    log.info(f"Backfill  mode={args.mode}  "
             f"dates={args.start_date or 'all'} → {args.end_date or 'now'}  "
             f"camera={args.camera or 'all'}  "
             f"cpu={args.cpu_percent}%%  "
             f"{'DRY RUN  ' if args.dry_run else ''}")

    if args.mode in ("events", "both", "all"):
        run_events(args, highlights)
    if args.mode in ("scenes", "both", "all"):
        run_scenes(args, highlights)
    if args.mode in ("raw", "all"):
        run_raw_archive(args, highlights)

    log.info("Done.")


if __name__ == "__main__":
    main()
