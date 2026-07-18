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


def test_find_segments_returns_overlapping(tmp_path):
    cam = tmp_path / "trackmix_wide" / "2026-05-11"
    (cam / "18").mkdir(parents=True)
    (cam / "19").mkdir()
    (cam / "20").mkdir()
    (cam / "18" / "30.mp4").write_bytes(b"")  # 18:30 — inside 2h buffer
    (cam / "19" / "00.mp4").write_bytes(b"")  # 19:00 — inside window
    (cam / "19" / "30.mp4").write_bytes(b"")  # 19:30 — inside window
    (cam / "20" / "30.mp4").write_bytes(b"")  # 20:30 — after window end (20:00)

    start = datetime(2026, 5, 11, 19, 0, 0)
    end   = datetime(2026, 5, 11, 20, 0, 0)
    segs  = fe.find_segments(start, end, tmp_path, camera="trackmix_wide")

    names = [s.name for s in segs]
    assert "00.mp4" in names   # 19:00 in
    assert "20:30" not in names
    assert len(segs) == 3      # 18:30, 19:00, 19:30


def test_find_segments_empty_when_no_camera_dir(tmp_path):
    segs = fe.find_segments(datetime(2026, 5, 11, 19, 0), datetime(2026, 5, 11, 20, 0),
                            tmp_path, camera="nonexistent")
    assert segs == []


def test_find_segments_sorted_chronologically(tmp_path):
    cam = tmp_path / "trackmix_wide" / "2026-05-11"
    (cam / "19").mkdir(parents=True)
    (cam / "19" / "30.mp4").write_bytes(b"")
    (cam / "19" / "00.mp4").write_bytes(b"")

    segs = fe.find_segments(datetime(2026, 5, 11, 19, 0), datetime(2026, 5, 11, 20, 0),
                            tmp_path, camera="trackmix_wide")
    times = [fe._parse_segment_time(s) for s in segs]
    assert times == sorted(times)


from unittest.mock import patch, MagicMock


def _make_fake_seg(tmp_path: Path, date_str: str, hour: str, minute: str) -> Path:
    d = tmp_path / "trackmix_wide" / date_str / hour
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{minute}.mp4"
    p.write_bytes(b"fake")
    return p


def test_extract_frames_calls_ffmpeg_per_segment(tmp_path):
    seg = _make_fake_seg(tmp_path, "2026-05-11", "19", "00")
    out_dir = tmp_path / "frames"

    with patch("frigate_extract.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        fe.extract_frames(
            segments=[seg],
            start_dt=datetime(2026, 5, 11, 19, 0),
            end_dt=datetime(2026, 5, 11, 20, 0),
            interval_secs=10,
            out_dir=out_dir,
        )
        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        assert "ffmpeg" in cmd
        assert "fps=1/10" in " ".join(cmd)


def test_extract_frames_skips_segment_after_window(tmp_path):
    seg = _make_fake_seg(tmp_path, "2026-05-11", "21", "00")  # after end_dt
    out_dir = tmp_path / "frames"

    with patch("frigate_extract.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        fe.extract_frames(
            segments=[seg],
            start_dt=datetime(2026, 5, 11, 19, 0),
            end_dt=datetime(2026, 5, 11, 20, 0),
            interval_secs=10,
            out_dir=out_dir,
        )
        assert not mock_run.called  # segment is entirely after window


def test_extract_frames_returns_sorted_jpgs(tmp_path):
    seg = _make_fake_seg(tmp_path, "2026-05-11", "19", "00")
    out_dir = tmp_path / "frames"

    def fake_run(cmd, **kwargs):
        seg_out = Path(cmd[-1]).parent
        seg_out.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            (seg_out / f"frame_{i:06d}.jpg").write_bytes(b"")
        return MagicMock(returncode=0, stderr="")

    with patch("frigate_extract.subprocess.run", side_effect=fake_run):
        frames = fe.extract_frames(
            segments=[seg],
            start_dt=datetime(2026, 5, 11, 19, 0),
            end_dt=datetime(2026, 5, 11, 20, 0),
            interval_secs=10,
            out_dir=out_dir,
        )

    assert len(frames) == 3
    assert all(f.suffix == ".jpg" for f in frames)
    assert frames == sorted(frames)
