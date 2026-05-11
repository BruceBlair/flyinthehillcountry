"""Tests for frigate_extract — segment discovery and frame extraction."""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
import frigate_extract as fe


def test_parse_standard_frigate_path():
    p = Path("/volume1/frigate/trackmix_wide/2026-05-11/19/30.mp4")
    dt = fe._parse_segment_time(p)
    assert dt == datetime(2026, 5, 11, 19, 30, 0)


def test_parse_handles_windows_sep():
    p = Path(r"C:\frigate\trackmix_wide\2026-05-11\19\30.mp4")
    dt = fe._parse_segment_time(p)
    assert dt == datetime(2026, 5, 11, 19, 30, 0)


def test_parse_returns_mtime_for_unrecognised_path(tmp_path):
    p = tmp_path / "randomname.mp4"
    p.write_bytes(b"")
    dt = fe._parse_segment_time(p)
    assert isinstance(dt, datetime)


def test_parse_returns_none_for_missing_file():
    p = Path("/nonexistent/path/whatever.mp4")
    dt = fe._parse_segment_time(p)
    assert dt is None
