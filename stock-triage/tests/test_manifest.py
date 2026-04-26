import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from manifest import add_entry, is_processed, load, save


def test_load_missing_dir_returns_empty(tmp_path):
    m = load(tmp_path / "nonexistent")
    assert m["images"] == []
    assert "generated" in m


def test_load_missing_file_returns_empty(tmp_path):
    m = load(tmp_path)
    assert m["images"] == []


def test_is_processed_false_for_new_source(tmp_path):
    m = load(tmp_path)
    assert not is_processed(m, Path("/highlights/wildlife/fox/img.jpg"))


def test_add_entry_then_is_processed(tmp_path):
    m = load(tmp_path)
    source = Path("/highlights/wildlife/fox/img.jpg")
    add_entry(m, {
        "source": str(source),
        "output": "/stock_ready/wimberley/wildlife/fox/gtn_wimberley_20260424_193215_fox_clean.jpg",
        "status": "clean",
        "reason": "no overlay detected",
        "crop_top_px": 0,
        "crop_bottom_px": 0,
        "resolution_mp": 8.3,
        "processed_at": "2026-04-25T12:01:23",
    })
    assert is_processed(m, source)


def test_add_entry_stores_all_fields(tmp_path):
    m = load(tmp_path)
    entry = {
        "source": "/highlights/wildlife/fox/img.jpg",
        "output": "/stock_ready/wimberley/wildlife/fox/gtn_wimberley_20260424_193215_fox_clean.jpg",
        "status": "clean",
        "reason": "no overlay detected",
        "crop_top_px": 0,
        "crop_bottom_px": 0,
        "resolution_mp": 8.3,
        "processed_at": "2026-04-25T12:01:23",
    }
    add_entry(m, entry)
    stored = m["images"][0]
    assert stored["status"] == "clean"
    assert stored["resolution_mp"] == 8.3
    assert stored["crop_top_px"] == 0
    assert stored["reason"] == "no overlay detected"


def test_save_and_reload_roundtrip(tmp_path):
    m = load(tmp_path)
    add_entry(m, {
        "source": "/highlights/test.jpg",
        "output": "/stock_ready/test.jpg",
        "status": "clean",
        "reason": "no overlay",
        "crop_top_px": 0,
        "crop_bottom_px": 0,
        "resolution_mp": 5.0,
        "processed_at": "2026-04-25T00:00:00",
    })
    save(m, tmp_path)

    reloaded = load(tmp_path)
    assert len(reloaded["images"]) == 1
    assert reloaded["images"][0]["source"] == "/highlights/test.jpg"


def test_add_entry_updates_existing_not_duplicates(tmp_path):
    m = load(tmp_path)
    source = "/highlights/test.jpg"
    add_entry(m, {"source": source, "output": None, "status": "error",
                  "reason": "fail", "crop_top_px": 0, "crop_bottom_px": 0,
                  "resolution_mp": 5.0, "processed_at": "2026-04-25T00:00:00"})
    add_entry(m, {"source": source, "output": "/stock_ready/test.jpg",
                  "status": "clean", "reason": "ok", "crop_top_px": 0,
                  "crop_bottom_px": 0, "resolution_mp": 5.0,
                  "processed_at": "2026-04-25T00:01:00"})
    assert len(m["images"]) == 1
    assert m["images"][0]["status"] == "clean"


def test_save_creates_directory(tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    m = load(nested)
    save(m, nested)
    assert (nested / "stock_manifest.json").exists()
