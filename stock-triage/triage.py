"""Entry point: reads env vars, dispatches batch or daemon mode."""

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from manifest import add_entry, is_processed
from manifest import load as load_manifest
from manifest import save as save_manifest
from pipeline import process_image
from report import generate as gen_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("triage")

MODE            = os.getenv("TRIAGE_MODE",        "daemon")
LOCATION        = os.getenv("LOCATION_LABEL",     "wimberley")
HIGHLIGHTS_DIR  = Path(os.getenv("HIGHLIGHTS_DIR",    "/highlights"))
FRIGATE_DIR     = Path(os.getenv("FRIGATE_MEDIA_DIR",  "/frigate-media"))
FRAMES_DIR      = Path(os.getenv("FRAMES_DIR",         "/frames")) if os.getenv("FRAMES_DIR") else None
STOCK_READY_DIR = Path(os.getenv("STOCK_READY_DIR",   "/stock_ready"))
MIN_RES_MP      = float(os.getenv("MIN_RESOLUTION_MP", "4.0"))
OCR_TOP_PCT     = float(os.getenv("OCR_TOP_PCT",       "0.15"))
OCR_BOTTOM_PCT  = float(os.getenv("OCR_BOTTOM_PCT",    "0.10"))


def _iter_jpegs(root: Path):
    if not root.exists():
        return
    for ext in ("*.jpg", "*.jpeg", "*.JPG", "*.JPEG"):
        yield from sorted(root.rglob(ext))


def _iter_frame_jpegs(root: Path):
    """Yield only numbered frame shots (01.jpg, 02.jpg…) from panorama_* dirs."""
    if not root.exists():
        return
    for d in sorted(root.glob("panorama_*")):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.jpg")):
            if f.stem.isdigit():
                yield f


def _process_one(source: Path, source_root: Path, manifest: dict) -> dict | None:
    if is_processed(manifest, source):
        log.debug("skip (already in manifest): %s", source.name)
        return None
    log.info("processing: %s", source)
    try:
        entry = process_image(
            source, source_root, STOCK_READY_DIR, LOCATION,
            min_resolution_mp=MIN_RES_MP,
            ocr_top_pct=OCR_TOP_PCT,
            ocr_bottom_pct=OCR_BOTTOM_PCT,
        )
    except Exception as exc:
        log.error("error on %s: %s", source, exc)
        entry = {
            "source": str(source),
            "output": None,
            "status": "error",
            "reason": str(exc),
            "crop_top_px": 0,
            "crop_bottom_px": 0,
            "resolution_mp": 0.0,
            "processed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        }
    add_entry(manifest, entry)
    log.info("  → %s  %s", entry["status"], entry.get("output") or "(not exported)")
    return entry


def run_batch() -> None:
    log.info("=== batch mode: full catalog scan ===")
    STOCK_READY_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(STOCK_READY_DIR)
    count = 0

    sources = [(HIGHLIGHTS_DIR, _iter_jpegs), (FRIGATE_DIR, _iter_jpegs)]
    if FRAMES_DIR:
        sources.append((FRAMES_DIR, _iter_frame_jpegs))

    for source_root, iter_fn in sources:
        if not source_root.exists():
            log.warning("source dir not found, skipping: %s", source_root)
            continue
        log.info("scanning: %s", source_root)
        for source in iter_fn(source_root):
            if "panoramas" in source.relative_to(source_root).parts:
                log.debug("skip panoramas: %s", source.name)
                continue
            _process_one(source, source_root, manifest)
            count += 1
            if count % 100 == 0:
                save_manifest(manifest, STOCK_READY_DIR)
                gen_report(manifest, STOCK_READY_DIR)
                log.info("checkpoint: %d images processed", count)

    save_manifest(manifest, STOCK_READY_DIR)
    gen_report(manifest, STOCK_READY_DIR)
    log.info("=== batch complete: %d images processed ===", count)


def run_daemon() -> None:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    log.info("=== daemon mode: watching %s ===", HIGHLIGHTS_DIR)
    STOCK_READY_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(STOCK_READY_DIR)
    counter = [0]

    class _Handler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.suffix.lower() not in (".jpg", ".jpeg"):
                return
            entry = _process_one(path, HIGHLIGHTS_DIR, manifest)
            if entry:
                counter[0] += 1
                save_manifest(manifest, STOCK_READY_DIR)
                if counter[0] % 100 == 0:
                    gen_report(manifest, STOCK_READY_DIR)

    observer = Observer()
    observer.schedule(_Handler(), str(HIGHLIGHTS_DIR), recursive=True)
    observer.start()
    log.info("watching for new .jpg files — Ctrl+C to stop")
    try:
        while observer.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    if MODE == "batch":
        run_batch()
    else:
        run_daemon()
