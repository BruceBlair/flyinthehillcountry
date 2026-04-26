import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from report import generate


def _make_manifest(images):
    return {"generated": "2026-04-25T12:00:00", "images": images}


def test_generate_creates_html_file(tmp_path):
    manifest = _make_manifest([])
    generate(manifest, tmp_path)
    assert (tmp_path / "triage_summary.html").exists()


def test_html_contains_total_count(tmp_path):
    manifest = _make_manifest([
        {"source": "/a.jpg", "output": "/b.jpg", "status": "clean",
         "reason": "ok", "crop_top_px": 0, "crop_bottom_px": 0,
         "resolution_mp": 8.3, "processed_at": "2026-04-25T12:00:00"},
        {"source": "/c.jpg", "output": None, "status": "rejected_resolution",
         "reason": "2.0MP", "crop_top_px": 0, "crop_bottom_px": 0,
         "resolution_mp": 2.0, "processed_at": "2026-04-25T12:01:00"},
    ])
    generate(manifest, tmp_path)
    html = (tmp_path / "triage_summary.html").read_text()
    assert "2" in html  # total count


def test_html_contains_each_status(tmp_path):
    manifest = _make_manifest([
        {"source": "/a.jpg", "output": "/b.jpg", "status": "clean",
         "reason": "ok", "crop_top_px": 0, "crop_bottom_px": 0,
         "resolution_mp": 8.3, "processed_at": "2026-04-25T12:00:00"},
        {"source": "/c.jpg", "output": "/d.jpg", "status": "cropped",
         "reason": "overlay", "crop_top_px": 82, "crop_bottom_px": 0,
         "resolution_mp": 8.3, "processed_at": "2026-04-25T12:01:00"},
        {"source": "/e.jpg", "output": None, "status": "rejected_resolution",
         "reason": "2.0MP", "crop_top_px": 0, "crop_bottom_px": 0,
         "resolution_mp": 2.0, "processed_at": "2026-04-25T12:02:00"},
    ])
    generate(manifest, tmp_path)
    html = (tmp_path / "triage_summary.html").read_text()
    assert "clean" in html
    assert "cropped" in html
    assert "rejected_resolution" in html


def test_generate_creates_output_dir(tmp_path):
    nested = tmp_path / "a" / "b"
    generate(_make_manifest([]), nested)
    assert (nested / "triage_summary.html").exists()
