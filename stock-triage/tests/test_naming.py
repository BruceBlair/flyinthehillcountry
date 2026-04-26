import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from naming import build_output_path, derive_label_and_category

HIGHLIGHTS = Path("/highlights")
LOCATION = "wimberley"


def test_wildlife_fox():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "wildlife" / "fox" / "img.jpg", HIGHLIGHTS
    )
    assert label == "fox"
    assert cat == "wildlife"


def test_wildlife_deer():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "wildlife" / "deer" / "img.jpg", HIGHLIGHTS
    )
    assert label == "deer"
    assert cat == "wildlife"


def test_weather_storm():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "weather" / "storm" / "img.jpg", HIGHLIGHTS
    )
    assert label == "storm"
    assert cat == "weather"


def test_weather_lightning():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "weather" / "lightning" / "img.jpg", HIGHLIGHTS
    )
    assert label == "lightning"
    assert cat == "weather"


def test_golden_hour_sunrise():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "golden_hour" / "sunrise" / "img.jpg", HIGHLIGHTS
    )
    assert label == "sunrise"
    assert cat == "golden-hour"


def test_golden_hour_sunset():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "golden_hour" / "sunset" / "img.jpg", HIGHLIGHTS
    )
    assert label == "sunset"
    assert cat == "golden-hour"


def test_panoramas_label_is_singular():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "panoramas" / "img.jpg", HIGHLIGHTS
    )
    assert label == "panorama"
    assert cat == "panoramas"


def test_stars():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "stars" / "img.jpg", HIGHLIGHTS
    )
    assert label == "stars"
    assert cat == "stars"


def test_unknown_source_falls_back_to_general(tmp_path):
    source = tmp_path / "frigate-media" / "clips" / "trackmix_wide-abc123.jpg"
    label, cat = derive_label_and_category(source, tmp_path / "frigate-media")
    assert isinstance(label, str) and len(label) > 0
    assert isinstance(cat, str) and len(cat) > 0


def test_output_path_structure(tmp_path):
    source = HIGHLIGHTS / "wildlife" / "fox" / "img.jpg"
    fixed = datetime(2026, 4, 24, 19, 32, 15)
    with patch("naming.timestamp_from_file", return_value=fixed):
        out = build_output_path(source, HIGHLIGHTS, tmp_path, LOCATION, "clean")
    assert out.parent == tmp_path / LOCATION / "wildlife" / "fox"
    assert out.name == "gtn_wimberley_20260424_193215_fox_clean.jpg"


def test_output_path_crop_suffix(tmp_path):
    source = HIGHLIGHTS / "weather" / "storm" / "img.jpg"
    fixed = datetime(2026, 4, 24, 6, 0, 0)
    with patch("naming.timestamp_from_file", return_value=fixed):
        out = build_output_path(source, HIGHLIGHTS, tmp_path, LOCATION, "crop")
    assert out.name == "gtn_wimberley_20260424_060000_storm_crop.jpg"


def test_output_path_panorama(tmp_path):
    source = HIGHLIGHTS / "panoramas" / "img.jpg"
    fixed = datetime(2026, 4, 24, 20, 0, 0)
    with patch("naming.timestamp_from_file", return_value=fixed):
        out = build_output_path(source, HIGHLIGHTS, tmp_path, LOCATION, "clean")
    assert out.parent == tmp_path / LOCATION / "panoramas" / "panorama"
    assert "panorama" in out.name
