import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent))

FONT = "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"


def _write_plain(path, w=3840, h=2160):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), (80, 130, 180)).save(path, "JPEG")


def _write_overlay(path, w=3840, h=2160):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (w, h), (80, 130, 180))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 36)
    draw.rectangle([(0, 0), (w, 90)], fill=(0, 0, 0))
    draw.text((20, 8),  "2026/04/25 19:32:15", fill=(255, 255, 255), font=font)
    draw.text((20, 52), "TrackMix Wide  CH1",  fill=(255, 255, 255), font=font)
    img.save(path, "JPEG")


def _write_small(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 600), (80, 130, 180)).save(path, "JPEG")


def test_batch_processes_highlights_and_frigate(tmp_path, monkeypatch):
    highlights = tmp_path / "highlights"
    frigate    = tmp_path / "frigate"
    stock_out  = tmp_path / "stock_ready"

    _write_plain(highlights / "wildlife" / "fox" / "clean.jpg")
    _write_overlay(highlights / "weather" / "storm" / "overlay.jpg")
    _write_small(highlights / "wildlife" / "deer" / "tiny.jpg")
    _write_plain(frigate / "snapshots" / "trackmix_wide" / "fox_event.jpg")

    monkeypatch.setenv("TRIAGE_MODE",        "batch")
    monkeypatch.setenv("LOCATION_LABEL",     "wimberley")
    monkeypatch.setenv("HIGHLIGHTS_DIR",     str(highlights))
    monkeypatch.setenv("FRIGATE_MEDIA_DIR",  str(frigate))
    monkeypatch.setenv("STOCK_READY_DIR",    str(stock_out))
    monkeypatch.setenv("MIN_RESOLUTION_MP",  "4.0")
    monkeypatch.setenv("OCR_TOP_PCT",        "0.15")
    monkeypatch.setenv("OCR_BOTTOM_PCT",     "0.10")

    import importlib
    import triage
    importlib.reload(triage)
    triage.run_batch()

    manifest_path = stock_out / "stock_manifest.json"
    assert manifest_path.exists(), "manifest should be written after batch"

    manifest = json.loads(manifest_path.read_text())
    statuses = {Path(e["source"]).name: e["status"] for e in manifest["images"]}

    assert statuses["clean.jpg"] == "clean"
    assert statuses["overlay.jpg"] == "cropped"
    assert statuses["tiny.jpg"] == "rejected_resolution"

    assert (stock_out / "triage_summary.html").exists()


def test_batch_skips_already_processed(tmp_path, monkeypatch):
    highlights = tmp_path / "highlights"
    stock_out  = tmp_path / "stock_ready"

    _write_plain(highlights / "wildlife" / "fox" / "img.jpg")

    monkeypatch.setenv("TRIAGE_MODE",        "batch")
    monkeypatch.setenv("LOCATION_LABEL",     "wimberley")
    monkeypatch.setenv("HIGHLIGHTS_DIR",     str(highlights))
    monkeypatch.setenv("FRIGATE_MEDIA_DIR",  str(tmp_path / "frigate_empty"))
    monkeypatch.setenv("STOCK_READY_DIR",    str(stock_out))
    monkeypatch.setenv("MIN_RESOLUTION_MP",  "4.0")
    monkeypatch.setenv("OCR_TOP_PCT",        "0.15")
    monkeypatch.setenv("OCR_BOTTOM_PCT",     "0.10")

    import importlib
    import triage
    importlib.reload(triage)

    triage.run_batch()
    manifest_after_first = json.loads((stock_out / "stock_manifest.json").read_text())
    count_first = len(manifest_after_first["images"])

    triage.run_batch()
    manifest_after_second = json.loads((stock_out / "stock_manifest.json").read_text())
    count_second = len(manifest_after_second["images"])

    assert count_first == count_second, "second batch should not add duplicate entries"


import threading
import time


def test_daemon_processes_new_file(tmp_path, monkeypatch):
    highlights = tmp_path / "highlights"
    highlights.mkdir(parents=True)
    stock_out  = tmp_path / "stock_ready"

    monkeypatch.setenv("TRIAGE_MODE",        "daemon")
    monkeypatch.setenv("LOCATION_LABEL",     "wimberley")
    monkeypatch.setenv("HIGHLIGHTS_DIR",     str(highlights))
    monkeypatch.setenv("FRIGATE_MEDIA_DIR",  str(tmp_path / "frigate_empty"))
    monkeypatch.setenv("STOCK_READY_DIR",    str(stock_out))
    monkeypatch.setenv("MIN_RESOLUTION_MP",  "4.0")
    monkeypatch.setenv("OCR_TOP_PCT",        "0.15")
    monkeypatch.setenv("OCR_BOTTOM_PCT",     "0.10")

    import importlib
    import triage
    importlib.reload(triage)

    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    from manifest import load as load_manifest, save as save_manifest, add_entry, is_processed
    from pipeline import process_image

    manifest = load_manifest(stock_out)
    processed_flag = threading.Event()

    class _TestHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.suffix.lower() not in (".jpg", ".jpeg"):
                return
            entry = triage._process_one(path, highlights, manifest)
            if entry:
                save_manifest(manifest, stock_out)
                processed_flag.set()

    observer = Observer()
    observer.schedule(_TestHandler(), str(highlights), recursive=True)
    observer.start()
    time.sleep(0.5)  # give watchdog time to initialise before writing

    # Write a new highlight after the watcher is running
    new_file = highlights / "wildlife" / "fox" / "new_arrival.jpg"
    _write_plain(new_file)

    assert processed_flag.wait(timeout=10), "daemon did not process the new file within 10 seconds"
    observer.stop()
    observer.join()

    manifest_data = json.loads((stock_out / "stock_manifest.json").read_text())
    sources = [e["source"] for e in manifest_data["images"]]
    assert str(new_file) in sources
