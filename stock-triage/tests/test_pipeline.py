import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline import process_image

FONT = "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"


def _save_plain_jpeg(path: Path, width: int, height: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), color=(80, 130, 180)).save(path, "JPEG")
    return path


def _save_overlay_jpeg(path: Path, width: int = 3840, height: int = 2160) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), color=(80, 130, 180))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 36)
    draw.rectangle([(0, 0), (width, 90)], fill=(0, 0, 0))
    draw.text((20, 8),  "2026/04/25 19:32:15", fill=(255, 255, 255), font=font)
    draw.text((20, 52), "TrackMix Wide  CH1",  fill=(255, 255, 255), font=font)
    img.save(path, "JPEG")
    return path


def test_rejects_below_min_resolution(tmp_path):
    src_dir = tmp_path / "highlights" / "wildlife" / "fox"
    source = _save_plain_jpeg(src_dir / "small.jpg", width=800, height=600)
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley", min_resolution_mp=4.0)
    assert entry["status"] == "rejected_resolution"
    assert entry["output"] is None


def test_clean_image_copies_with_clean_status(tmp_path):
    src_dir = tmp_path / "highlights" / "wildlife" / "fox"
    source = _save_plain_jpeg(src_dir / "clean.jpg", width=3840, height=2160)
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley")
    assert entry["status"] == "clean"
    assert entry["output"] is not None
    assert Path(entry["output"]).exists()


def test_overlay_image_gets_cropped_status(tmp_path):
    src_dir = tmp_path / "highlights" / "wildlife" / "fox"
    source = _save_overlay_jpeg(src_dir / "overlay.jpg")
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley")
    assert entry["status"] == "cropped"
    assert entry["crop_top_px"] > 0
    assert entry["output"] is not None


def test_cropped_output_is_shorter_than_original(tmp_path):
    src_dir = tmp_path / "highlights" / "wildlife" / "fox"
    source = _save_overlay_jpeg(src_dir / "overlay.jpg")
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley")
    out_img = Image.open(entry["output"])
    assert out_img.size[1] < 2160, "cropped image height should be less than original 2160"


def test_output_path_follows_naming_convention(tmp_path):
    src_dir = tmp_path / "highlights" / "weather" / "storm"
    source = _save_plain_jpeg(src_dir / "storm.jpg", width=3840, height=2160)
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley")
    out = Path(entry["output"])
    assert out.parent.parts[-3] == "wimberley"
    assert out.parent.parts[-2] == "weather"
    assert out.parent.parts[-1] == "storm"
    assert out.name.startswith("gtn_wimberley_")
    assert out.name.endswith("_storm_clean.jpg")


def test_resolution_mp_recorded_in_entry(tmp_path):
    src_dir = tmp_path / "highlights" / "wildlife" / "fox"
    source = _save_plain_jpeg(src_dir / "hires.jpg", width=3840, height=2160)
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley")
    expected_mp = round((3840 * 2160) / 1_000_000, 2)
    assert abs(entry["resolution_mp"] - expected_mp) < 0.1


def test_entry_contains_all_required_fields(tmp_path):
    src_dir = tmp_path / "highlights" / "wildlife" / "fox"
    source = _save_plain_jpeg(src_dir / "img.jpg", width=3840, height=2160)
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley")
    for field in ("source", "output", "status", "reason", "crop_top_px",
                  "crop_bottom_px", "resolution_mp", "processed_at"):
        assert field in entry, f"missing field: {field}"
