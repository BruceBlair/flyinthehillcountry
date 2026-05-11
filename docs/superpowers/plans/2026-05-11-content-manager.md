# Content Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `cull_ui.py` with a unified `content_manager.py` web UI (port 8766) that adds retroactive timelapse building from Frigate MP4 recordings alongside the existing photo cull grid.

**Architecture:** `frigate_extract.py` discovers Frigate recording segments and extracts frames via ffmpeg; `content_manager.py` is an `http.server`-based single-page app with three tabs (Photos, Timelapse, Status); timelapse builds run in a background thread with polling progress. Existing `timelapse_builder._build_one()` does the ffmpeg encode step unchanged.

**Tech Stack:** Python 3.11+, `http.server`, `astral` (sunrise/sunset), `ffmpeg` (frame extraction + encode), `Pillow` (thumbnails), `threading` (background jobs) — all already in requirements.txt or standard library.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `highlight-curator/frigate_extract.py` | Segment discovery + frame extraction from Frigate recordings |
| Create | `highlight-curator/content_manager.py` | HTTP server, all API endpoints, embedded SPA HTML |
| Create | `highlight-curator/tests/__init__.py` | Makes tests a package |
| Create | `highlight-curator/tests/test_frigate_extract.py` | Unit tests for segment discovery and frame extraction |
| Create | `highlight-curator/tests/test_content_manager_api.py` | HTTP API integration tests |
| Retire | `highlight-curator/cull_ui.py` | Replaced — do not delete until Task 4 passes |

---

## Task 1: Test scaffolding + `_parse_segment_time`

**Files:**
- Create: `highlight-curator/tests/__init__.py`
- Create: `highlight-curator/tests/test_frigate_extract.py`
- Create: `highlight-curator/frigate_extract.py`

- [ ] **Create the tests package**

```bash
mkdir -p /home/HighlyReflective/weather-station/highlight-curator/tests
touch /home/HighlyReflective/weather-station/highlight-curator/tests/__init__.py
```

- [ ] **Write failing tests for `_parse_segment_time`**

Create `highlight-curator/tests/test_frigate_extract.py`:

```python
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
    # Falls back to mtime — just check it returns a datetime, not None
    assert isinstance(dt, datetime)


def test_parse_returns_none_for_missing_file():
    p = Path("/nonexistent/path/whatever.mp4")
    dt = fe._parse_segment_time(p)
    assert dt is None
```

- [ ] **Run tests to confirm they fail**

```bash
cd /home/HighlyReflective/weather-station/highlight-curator
python -m pytest tests/test_frigate_extract.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'frigate_extract'`

- [ ] **Create `frigate_extract.py` with `_parse_segment_time`**

Create `highlight-curator/frigate_extract.py`:

```python
#!/usr/bin/env python3
"""
frigate_extract.py — Ground Truth Network
Discovers Frigate recording segments for a time window and extracts
still frames via ffmpeg for timelapse building.

Public API:
    find_segments(start_dt, end_dt, frigate_dir, camera) -> list[Path]
    extract_frames(segments, start_dt, end_dt, interval_secs, out_dir) -> list[Path]
"""

import logging
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

log = logging.getLogger("frigate_extract")

# Frigate's default recording path: {camera}/YYYY-MM-DD/HH/MM.mp4
_SEG_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[/\\](\d{2})[/\\](\d{2})\.mp4$")


def _parse_segment_time(path: Path) -> datetime | None:
    """Return the segment's start datetime from its path, or mtime as fallback."""
    m = _SEG_RE.search(str(path))
    if m:
        try:
            return datetime.strptime(
                f"{m.group(1)} {m.group(2)}:{m.group(3)}:00", "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None
```

- [ ] **Run tests — all four should pass**

```bash
cd /home/HighlyReflective/weather-station/highlight-curator
python -m pytest tests/test_frigate_extract.py -v
```
Expected: 4 passed

- [ ] **Commit**

```bash
cd /home/HighlyReflective/weather-station
git add highlight-curator/frigate_extract.py highlight-curator/tests/
git commit -m "feat(content-manager): frigate_extract skeleton + _parse_segment_time"
```

---

## Task 2: `find_segments()`

**Files:**
- Modify: `highlight-curator/frigate_extract.py`
- Modify: `highlight-curator/tests/test_frigate_extract.py`

- [ ] **Add `find_segments` tests**

Append to `highlight-curator/tests/test_frigate_extract.py`:

```python
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
```

- [ ] **Run to confirm failure**

```bash
cd /home/HighlyReflective/weather-station/highlight-curator
python -m pytest tests/test_frigate_extract.py::test_find_segments_returns_overlapping -v
```
Expected: `AttributeError: module 'frigate_extract' has no attribute 'find_segments'`

- [ ] **Implement `find_segments`**

Append to `highlight-curator/frigate_extract.py`:

```python

def find_segments(start_dt: datetime, end_dt: datetime,
                  frigate_dir: Path, camera: str = "trackmix_wide") -> list[Path]:
    """
    Return MP4 segments under frigate_dir/camera that overlap [start_dt, end_dt],
    sorted chronologically. Includes segments starting up to 2h before start_dt
    to catch recordings that began before the window but extend into it.
    """
    cam_dir = frigate_dir / camera
    if not cam_dir.exists():
        return []

    cutoff_early = start_dt - timedelta(hours=2)
    results: list[tuple[datetime, Path]] = []

    for mp4 in cam_dir.rglob("*.mp4"):
        seg_start = _parse_segment_time(mp4)
        if seg_start is None:
            continue
        if cutoff_early <= seg_start <= end_dt:
            results.append((seg_start, mp4))

    return [p for _, p in sorted(results)]
```

- [ ] **Run all tests**

```bash
cd /home/HighlyReflective/weather-station/highlight-curator
python -m pytest tests/test_frigate_extract.py -v
```
Expected: 7 passed

- [ ] **Commit**

```bash
cd /home/HighlyReflective/weather-station
git add highlight-curator/frigate_extract.py highlight-curator/tests/test_frigate_extract.py
git commit -m "feat(content-manager): find_segments discovers Frigate MP4s for a time window"
```

---

## Task 3: `extract_frames()`

**Files:**
- Modify: `highlight-curator/frigate_extract.py`
- Modify: `highlight-curator/tests/test_frigate_extract.py`

- [ ] **Add `extract_frames` tests**

Append to `highlight-curator/tests/test_frigate_extract.py`:

```python
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
```

- [ ] **Run to confirm failure**

```bash
cd /home/HighlyReflective/weather-station/highlight-curator
python -m pytest tests/test_frigate_extract.py::test_extract_frames_calls_ffmpeg_per_segment -v
```
Expected: `AttributeError: module 'frigate_extract' has no attribute 'extract_frames'`

- [ ] **Implement `extract_frames`**

Append to `highlight-curator/frigate_extract.py`:

```python

def extract_frames(segments: list[Path], start_dt: datetime, end_dt: datetime,
                   interval_secs: int, out_dir: Path,
                   on_progress: Callable[[int], None] | None = None) -> list[Path]:
    """
    Extract one frame every interval_secs from Frigate segments overlapping
    [start_dt, end_dt]. Frames written to out_dir as JPEG, returned sorted.

    on_progress(n) is called after each segment with the cumulative frame count.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    all_frames: list[Path] = []

    for i, seg in enumerate(segments):
        seg_start = _parse_segment_time(seg)
        if seg_start is None:
            continue

        to_secs = (end_dt - seg_start).total_seconds()
        if to_secs <= 0:
            continue  # segment starts after window ends

        ss_secs = max(0.0, (start_dt - seg_start).total_seconds())
        seg_out = out_dir / f"{i:04d}"
        seg_out.mkdir(exist_ok=True)

        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-ss", str(ss_secs), "-to", str(to_secs),
            "-i", str(seg),
            "-vf", f"fps=1/{interval_secs}",
            str(seg_out / "frame_%06d.jpg"),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log.warning(f"ffmpeg failed for {seg.name}: {result.stderr[:300]}")
            continue

        seg_frames = sorted(seg_out.glob("frame_*.jpg"))
        all_frames.extend(seg_frames)

        if on_progress:
            on_progress(len(all_frames))

    return sorted(all_frames)
```

- [ ] **Run all tests**

```bash
cd /home/HighlyReflective/weather-station/highlight-curator
python -m pytest tests/test_frigate_extract.py -v
```
Expected: 10 passed

- [ ] **Commit**

```bash
cd /home/HighlyReflective/weather-station
git add highlight-curator/frigate_extract.py highlight-curator/tests/test_frigate_extract.py
git commit -m "feat(content-manager): extract_frames pulls JPEGs from Frigate segments via ffmpeg"
```

---

## Task 4: `content_manager.py` — server + all three tabs

**Files:**
- Create: `highlight-curator/content_manager.py`
- Create: `highlight-curator/tests/test_content_manager_api.py`

- [ ] **Write failing API tests**

Create `highlight-curator/tests/test_content_manager_api.py`:

```python
"""Integration tests — spins up a real content_manager HTTP server on a random port."""
import io
import json
import sys
import threading
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture()
def server(tmp_path):
    """Start content_manager server pointing at a temp highlights dir."""
    (tmp_path / "manifest.json").write_text(json.dumps({
        "entries": [
            {"snapshot": "golden_hour/sunrise/20260511_070000_scene.jpg",
             "timestamp": "20260511_070000",
             "categories": ["golden_hour/sunrise"],
             "label": "sky", "nice_shot": 72.5},
        ]
    }))
    img_dir = tmp_path / "golden_hour" / "sunrise"
    img_dir.mkdir(parents=True)
    img_path = img_dir / "20260511_070000_scene.jpg"
    buf = io.BytesIO()
    Image.new("RGB", (4, 3), color=(200, 150, 100)).save(buf, "JPEG")
    img_path.write_bytes(buf.getvalue())

    import content_manager as cm
    cm.HIGHLIGHTS_DIR = tmp_path
    cm.SYNC_SCRIPT    = None

    httpd = HTTPServer(("127.0.0.1", 0), cm.ContentHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read()


def post(url, body: dict):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


def test_root_serves_html(server):
    status, body = get(server + "/")
    assert status == 200
    assert b"<html" in body.lower()


def test_api_images_returns_categories(server):
    status, body = get(server + "/api/images")
    data = json.loads(body)
    assert status == 200
    assert "golden_hour/sunrise" in data


def test_api_delete_removes_entry(server, tmp_path):
    status, data = post(server + "/api/delete",
                        {"paths": ["golden_hour/sunrise/20260511_070000_scene.jpg"]})
    assert status == 200
    assert data["deleted"] == 1


def test_thumb_returns_jpeg(server):
    status, body = get(
        server + "/thumb/golden_hour%2Fsunrise%2F20260511_070000_scene.jpg"
    )
    assert status == 200
    assert body[:2] == b"\xff\xd8"  # JPEG magic bytes


def test_timelapse_status_idle(server):
    status, body = get(server + "/api/timelapse/status")
    data = json.loads(body)
    assert status == 200
    assert data["state"] == "idle"


def test_timelapses_returns_entries(server, tmp_path):
    (tmp_path / "timelapse_manifest.json").write_text(
        json.dumps({"entries": [{"session_key": "test", "date": "2026-05-11",
                                  "type": "sunset", "frame_count": 100,
                                  "video": "test_timelapse.mp4", "thumbnail": ""}]})
    )
    status, body = get(server + "/api/timelapses")
    data = json.loads(body)
    assert status == 200
    assert len(data["entries"]) == 1
```

- [ ] **Run to confirm failure**

```bash
cd /home/HighlyReflective/weather-station/highlight-curator
python -m pytest tests/test_content_manager_api.py::test_root_serves_html -v
```
Expected: `ModuleNotFoundError: No module named 'content_manager'`

- [ ] **Create `content_manager.py`**

Create `highlight-curator/content_manager.py`:

```python
#!/usr/bin/env python3
"""
content_manager.py — Ground Truth Network
Unified content management UI: photo cull, timelapse building, pipeline status.
Replaces cull_ui.py. LAN-only — do NOT expose port 8766 publicly.

Usage:
  python3 content_manager.py
  python3 content_manager.py --port 8766 --highlights-dir /volume1/highlights \
      --frigate-dir /volume1/frigate --sync-script ../github-pages/sync.sh
"""

import argparse
import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("content-manager")

HIGHLIGHTS_DIR = Path(os.getenv("HIGHLIGHTS_DIR", "/volume1/highlights"))
FRIGATE_DIR    = Path(os.getenv("FRIGATE_DIR",    "/volume1/frigate"))
SYNC_SCRIPT: Path | None = None
FRAME_DURATION  = 0.12   # seconds per frame in timelapse (~8 fps)
GOLDEN_PAD_MIN  = 30     # minutes padding before/after sunrise or sunset

_thumb_cache: dict[str, bytes] = {}
_manifest_lock = threading.Lock()

# ── Job state ─────────────────────────────────────────────────────────────────

_job_lock = threading.Lock()
_job: dict = {"state": "idle", "stage": "", "frames_done": 0, "frames_total": 0, "error": ""}


def _job_update(**kwargs) -> None:
    with _job_lock:
        _job.update(kwargs)


def _job_snapshot() -> dict:
    with _job_lock:
        return dict(_job)


# ── Manifest helpers ──────────────────────────────────────────────────────────

def load_manifest() -> dict:
    mf = HIGHLIGHTS_DIR / "manifest.json"
    return json.loads(mf.read_text()) if mf.exists() else {"entries": []}


def save_manifest(m: dict) -> None:
    with _manifest_lock:
        (HIGHLIGHTS_DIR / "manifest.json").write_text(json.dumps(m, indent=2))


def images_by_category() -> dict:
    cats: dict[str, list] = {}
    for e in load_manifest().get("entries", []):
        snap = e.get("snapshot")
        if not snap:
            continue
        cat = (e.get("categories") or ["unknown"])[0]
        cats.setdefault(cat, []).append({
            "path":      snap,
            "timestamp": e.get("timestamp", ""),
            "label":     e.get("label", ""),
            "score":     e.get("nice_shot") or 0,
        })
    for v in cats.values():
        v.sort(key=lambda x: x["timestamp"], reverse=True)
    return cats


def delete_snapshots(paths: list[str]) -> int:
    paths_set = set(paths)
    deleted = 0
    with _manifest_lock:
        m = load_manifest()
        kept = []
        for e in m.get("entries", []):
            snap = e.get("snapshot")
            if snap and snap in paths_set:
                full = HIGHLIGHTS_DIR / snap
                if full.exists():
                    full.unlink()
                    deleted += 1
                    log.info(f"deleted  {snap}")
            else:
                kept.append(e)
        m["entries"] = kept
        (HIGHLIGHTS_DIR / "manifest.json").write_text(json.dumps(m, indent=2))
    if deleted:
        _trigger_sync()
    return deleted


# ── Thumbnails ────────────────────────────────────────────────────────────────

def make_thumb(rel: str) -> bytes:
    if rel in _thumb_cache:
        return _thumb_cache[rel]
    try:
        from PIL import Image
        img = Image.open(HIGHLIGHTS_DIR / rel)
        img.thumbnail((240, 180))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=72)
        data = buf.getvalue()
    except Exception:
        data = b""
    _thumb_cache[rel] = data
    return data


# ── Sync ──────────────────────────────────────────────────────────────────────

def _trigger_sync() -> None:
    if not SYNC_SCRIPT:
        return
    try:
        subprocess.Popen(["bash", str(SYNC_SCRIPT)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.info("sync.sh triggered")
    except Exception as e:
        log.warning(f"sync trigger failed: {e}")


# ── Path safety ───────────────────────────────────────────────────────────────

def safe_rel(raw: str) -> str | None:
    try:
        resolved = (HIGHLIGHTS_DIR / raw).resolve()
        resolved.relative_to(HIGHLIGHTS_DIR.resolve())
        return raw
    except Exception:
        return None


# ── HTML ──────────────────────────────────────────────────────────────────────

_HTML = b"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GTN Content Manager</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#111;color:#eee;font:14px/1.4 system-ui,sans-serif}
#topbar{position:sticky;top:0;z-index:10;background:#1a1a1a;border-bottom:1px solid #333;
        padding:10px 16px;display:flex;align-items:center;gap:12px}
#topbar h1{font-size:15px;font-weight:600;flex:1}
#maintabs{display:flex;gap:4px;padding:8px 16px;background:#181818;border-bottom:1px solid #2a2a2a}
.mtab{padding:6px 16px;border-radius:4px;cursor:pointer;background:#2a2a2a;
      border:1px solid #444;font-size:13px;user-select:none}
.mtab.active{background:#0055aa;border-color:#0055aa}
.panel{display:none;padding:14px 16px}
.panel.active{display:block}
button{background:#c33;color:#fff;border:none;padding:7px 14px;border-radius:4px;
       cursor:pointer;font-size:13px}
button:disabled{background:#444;cursor:default}
button.ok{background:#2a7}
#toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);
       background:#2a7;color:#fff;padding:10px 22px;border-radius:6px;
       display:none;font-weight:600;z-index:99}
/* photos */
#bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px}
#count{color:#f66;font-weight:600}
#subtabs{display:flex;gap:4px;margin-bottom:10px;flex-wrap:wrap}
.stab{padding:5px 12px;border-radius:4px;cursor:pointer;background:#2a2a2a;
      border:1px solid #444;font-size:12px;user-select:none}
.stab.active{background:#0055aa;border-color:#0055aa}
.section{display:none}
.section.active{display:block}
.sec-bar{display:flex;gap:10px;margin-bottom:8px;align-items:center;font-size:12px;color:#888}
.sec-bar a{color:#69f;cursor:pointer;text-decoration:underline}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}
.card{position:relative;cursor:pointer;border-radius:4px;overflow:hidden;
      border:3px solid transparent;transition:border-color .12s}
.card.selected{border-color:#f44}
.card img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block;background:#222}
.ts{position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,.65);
    padding:3px 6px;font-size:11px;color:#ccc;overflow:hidden}
.badge{position:absolute;top:4px;right:4px;background:#f44;color:#fff;border-radius:50%;
       width:20px;height:20px;display:none;align-items:center;justify-content:center;
       font-size:13px;font-weight:bold}
.card.selected .badge{display:flex}
/* timelapse */
.tl-form{background:#1e1e1e;border:1px solid #333;border-radius:6px;padding:14px;
         margin-bottom:12px;display:flex;flex-direction:column;gap:10px}
.tl-form label{font-size:13px;color:#aaa}
.tl-form input,.tl-form select{background:#2a2a2a;border:1px solid #444;color:#eee;
  padding:6px 10px;border-radius:4px;font-size:13px;width:100%}
.mode-btns{display:flex;gap:6px;margin-bottom:10px}
.mode-btn{padding:6px 14px;border-radius:4px;cursor:pointer;background:#2a2a2a;
          border:1px solid #444;font-size:13px;color:#eee;user-select:none}
.mode-btn.active{background:#0055aa;border-color:#0055aa}
.estimate{font-size:12px;color:#6cf;margin-top:4px}
.progress-wrap{height:6px;background:#333;border-radius:3px;overflow:hidden;
               margin-top:8px;display:none}
.progress-bar{height:100%;background:#0af;width:0%;transition:width .3s}
.tl-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));
          gap:10px;margin-top:16px}
.tl-card{background:#1e1e1e;border:1px solid #333;border-radius:6px;
          overflow:hidden;cursor:pointer}
.tl-card img{width:100%;aspect-ratio:16/9;object-fit:cover;background:#222}
.tl-card-info{padding:8px 10px;font-size:12px;color:#aaa;line-height:1.6}
/* status */
.log-box{background:#0d0d0d;border:1px solid #2a2a2a;border-radius:4px;
         padding:10px;font:12px/1.6 monospace;color:#8f8;white-space:pre-wrap;
         max-height:400px;overflow-y:auto;margin-top:10px}
.status-row{display:flex;align-items:center;gap:12px;margin-bottom:12px}
</style>
</head>
<body>
<div id="topbar"><h1>GTN Content Manager</h1></div>
<div id="maintabs">
  <div class="mtab active" data-panel="photos">Photos</div>
  <div class="mtab" data-panel="timelapse">Timelapse</div>
  <div class="mtab" data-panel="status">Status</div>
</div>

<!-- PHOTOS -->
<div id="photos" class="panel active">
  <div id="bar">
    <span id="count">0 selected</span>
    <button id="delBtn" disabled onclick="confirmDelete()">Delete selected</button>
  </div>
  <div id="subtabs"></div>
  <div id="sections"></div>
</div>

<!-- TIMELAPSE -->
<div id="timelapse" class="panel">
  <div class="mode-btns">
    <div class="mode-btn active" data-mode="golden">Golden Hour</div>
    <div class="mode-btn" data-mode="fullday">Full Day</div>
    <div class="mode-btn" data-mode="custom">Custom Range</div>
  </div>

  <div class="tl-form" id="form-golden">
    <label>Date <input type="date" id="gh-date"></label>
    <label>Type
      <select id="gh-type">
        <option value="sunrise">Sunrise</option>
        <option value="sunset">Sunset</option>
      </select>
    </label>
  </div>

  <div class="tl-form" id="form-fullday" style="display:none">
    <label>Date <input type="date" id="fd-date"></label>
  </div>

  <div class="tl-form" id="form-custom" style="display:none">
    <label>Start <input type="datetime-local" id="cr-start"></label>
    <label>End   <input type="datetime-local" id="cr-end"></label>
    <label>Label <input type="text" id="cr-label" placeholder="storm_rollout"></label>
  </div>

  <div class="tl-form">
    <div style="display:flex;gap:16px;align-items:center">
      <label style="display:flex;align-items:center;gap:6px">
        <input type="radio" name="timing" value="interval" checked onchange="timingMode()">
        Interval
      </label>
      <label style="display:flex;align-items:center;gap:6px">
        <input type="radio" name="timing" value="duration" onchange="timingMode()">
        Target duration
      </label>
    </div>
    <div id="interval-row">
      <label>Extract 1 frame every
        <input type="number" id="t-interval" value="10" min="1" max="300"
               style="width:70px" oninput="recalc()"> seconds
      </label>
      <div class="estimate" id="est-duration"></div>
    </div>
    <div id="duration-row" style="display:none">
      <label>Make video
        <input type="number" id="t-duration" value="5" min="1" step="0.5"
               style="width:70px" oninput="recalc()"> minutes long
      </label>
      <div class="estimate" id="est-interval"></div>
    </div>
  </div>

  <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
    <button class="ok" onclick="buildTimelapse()">Build Timelapse</button>
    <span id="build-status" style="font-size:13px;color:#aaa"></span>
  </div>
  <div class="progress-wrap" id="prog-wrap">
    <div class="progress-bar" id="prog-bar"></div>
  </div>
  <div class="tl-list" id="tl-list"></div>
</div>

<!-- STATUS -->
<div id="status" class="panel">
  <div class="status-row">
    <button class="ok" onclick="runPipeline()">Run pipeline now</button>
    <span id="pipe-status" style="font-size:13px;color:#aaa"></span>
  </div>
  <div class="log-box" id="log-box">Loading...</div>
</div>

<div id="toast"></div>
<script>
'use strict';

// ── Tab switching ─────────────────────────────────────────────────────────────
document.querySelectorAll('.mtab').forEach(t => t.addEventListener('click', () => {
  document.querySelectorAll('.mtab').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  document.getElementById(t.dataset.panel).classList.add('active');
  if (t.dataset.panel === 'timelapse') { loadTimelapses(); recalc(); }
  if (t.dataset.panel === 'status') loadLog();
}));

// ── Photos tab ────────────────────────────────────────────────────────────────
const selected = new Set();
let allData = {};

function fmtTs(ts) {
  const m = ts.match(/^(\\d{4})(\\d{2})(\\d{2})_(\\d{2})(\\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : ts;
}

function makeCard(img) {
  const card = document.createElement('div');
  card.className = 'card';
  card.dataset.path = img.path;
  const photo = document.createElement('img');
  photo.src = '/thumb/' + encodeURIComponent(img.path);
  photo.loading = 'lazy';
  photo.alt = img.label || '';
  const ts = document.createElement('div');
  ts.className = 'ts';
  ts.textContent = fmtTs(img.timestamp);
  const badge = document.createElement('div');
  badge.className = 'badge';
  badge.textContent = '\\u2715';
  card.append(photo, ts, badge);
  card.addEventListener('click', () => toggle(card, img.path));
  return card;
}

async function initPhotos() {
  const r = await fetch('/api/images');
  allData = await r.json();
  const subtabs  = document.getElementById('subtabs');
  const sections = document.getElementById('sections');
  Object.keys(allData).sort().forEach((cat, i) => {
    const imgs = allData[cat];
    const tab = document.createElement('div');
    tab.className = 'stab' + (i === 0 ? ' active' : '');
    tab.textContent = cat + ' (' + imgs.length + ')';
    tab.dataset.cat = cat;
    tab.addEventListener('click', () => {
      document.querySelectorAll('.stab').forEach(x => x.classList.remove('active'));
      document.querySelectorAll('.section').forEach(x => x.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('sec-' + cat).classList.add('active');
    });
    subtabs.appendChild(tab);

    const sec = document.createElement('div');
    sec.className = 'section' + (i === 0 ? ' active' : '');
    sec.id = 'sec-' + cat;

    const bar = document.createElement('div');
    bar.className = 'sec-bar';
    const info = document.createElement('span');
    info.textContent = imgs.length + ' photos';
    const selAll = document.createElement('a');
    selAll.textContent = 'select all';
    selAll.addEventListener('click', () => selectAll(cat));
    const deselAll = document.createElement('a');
    deselAll.textContent = 'deselect all';
    deselAll.addEventListener('click', () => deselectAll(cat));
    bar.append(info, selAll, deselAll);

    const grid = document.createElement('div');
    grid.className = 'grid';
    imgs.forEach(img => grid.appendChild(makeCard(img)));
    sec.append(bar, grid);
    sections.appendChild(sec);
  });
}

function toggle(card, path) {
  if (selected.has(path)) { selected.delete(path); card.classList.remove('selected'); }
  else                    { selected.add(path);    card.classList.add('selected'); }
  updateCount();
}
function selectAll(cat) {
  allData[cat].forEach(img => {
    selected.add(img.path);
    document.querySelector('.card[data-path="' + CSS.escape(img.path) + '"]')
            ?.classList.add('selected');
  });
  updateCount();
}
function deselectAll(cat) {
  allData[cat].forEach(img => {
    selected.delete(img.path);
    document.querySelector('.card[data-path="' + CSS.escape(img.path) + '"]')
            ?.classList.remove('selected');
  });
  updateCount();
}
function updateCount() {
  document.getElementById('count').textContent = selected.size + ' selected';
  document.getElementById('delBtn').disabled = selected.size === 0;
}
async function confirmDelete() {
  if (!selected.size) return;
  if (!confirm('Permanently delete ' + selected.size + ' photo(s) from highlights?\\n\\nThis cannot be undone.')) return;
  const paths = [...selected];
  const r = await fetch('/api/delete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({paths}),
  });
  const j = await r.json();
  const deletedSet = new Set(j.paths);
  j.paths.forEach(p => {
    document.querySelector('.card[data-path="' + CSS.escape(p) + '"]')?.remove();
    selected.delete(p);
  });
  Object.keys(allData).forEach(cat => {
    allData[cat] = allData[cat].filter(img => !deletedSet.has(img.path));
    const n = document.querySelectorAll('#sec-' + cat + ' .card').length;
    const tab = document.querySelector('.stab[data-cat="' + cat + '"]');
    if (tab) tab.textContent = cat + ' (' + n + ')';
  });
  updateCount();
  toast('Deleted ' + j.deleted + ' photo(s)');
}

// ── Timelapse tab ─────────────────────────────────────────────────────────────
let tlMode = 'golden';
document.querySelectorAll('.mode-btn').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.mode-btn').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  tlMode = b.dataset.mode;
  document.getElementById('form-golden').style.display  = tlMode === 'golden'  ? '' : 'none';
  document.getElementById('form-fullday').style.display = tlMode === 'fullday' ? '' : 'none';
  document.getElementById('form-custom').style.display  = tlMode === 'custom'  ? '' : 'none';
  recalc();
}));

// Default dates to today
const today = new Date().toISOString().slice(0, 10);
document.getElementById('gh-date').value = today;
document.getElementById('fd-date').value = today;

function timingMode() {
  const isInterval = document.querySelector('input[name=timing]:checked').value === 'interval';
  document.getElementById('interval-row').style.display = isInterval ? '' : 'none';
  document.getElementById('duration-row').style.display = isInterval ? 'none' : '';
  recalc();
}

function windowSecs() {
  if (tlMode === 'golden')  return 60 * 60;         // ±30 min = 60 min total
  if (tlMode === 'fullday') return 15 * 60 * 60;    // ~15h with padding
  const s = document.getElementById('cr-start').value;
  const e = document.getElementById('cr-end').value;
  if (!s || !e) return 15 * 60 * 60;
  return Math.max(60, (new Date(e) - new Date(s)) / 1000);
}

function fmtSecs(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.round(s % 60);
  if (h > 0) return h + 'h ' + m + 'm';
  if (m > 0) return m + 'm ' + sec + 's';
  return sec + 's';
}

function recalc() {
  const wSecs = windowSecs();
  const isInterval = document.querySelector('input[name=timing]:checked').value === 'interval';
  if (isInterval) {
    const iv = parseFloat(document.getElementById('t-interval').value) || 10;
    const frames = Math.round(wSecs / iv);
    const dur = frames * 0.12;
    document.getElementById('est-duration').textContent =
      '→ ~' + frames + ' frames, video ≈ ' + fmtSecs(dur);
  } else {
    const dur = (parseFloat(document.getElementById('t-duration').value) || 5) * 60;
    const frames = dur / 0.12;
    const iv = (wSecs / frames).toFixed(1);
    document.getElementById('est-interval').textContent =
      '→ 1 frame every ' + iv + 's';
  }
}

let _building = false;

async function buildTimelapse() {
  if (_building) return;
  const isInterval = document.querySelector('input[name=timing]:checked').value === 'interval';
  let intervalSecs;
  if (isInterval) {
    intervalSecs = parseFloat(document.getElementById('t-interval').value) || 10;
  } else {
    const dur = (parseFloat(document.getElementById('t-duration').value) || 5) * 60;
    intervalSecs = Math.max(1, windowSecs() / (dur / 0.12));
  }

  const body = {mode: tlMode, interval_secs: Math.round(intervalSecs)};
  if (tlMode === 'golden') {
    body.date = document.getElementById('gh-date').value;
    body.type = document.getElementById('gh-type').value;
  } else if (tlMode === 'fullday') {
    body.date = document.getElementById('fd-date').value;
  } else {
    body.start = document.getElementById('cr-start').value;
    body.end   = document.getElementById('cr-end').value;
    body.label = document.getElementById('cr-label').value || 'custom';
  }

  const r = await fetch('/api/timelapse/build', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (j.error) { toast('Error: ' + j.error); return; }
  _building = true;
  document.getElementById('prog-wrap').style.display = '';
  pollBuild();
}

function pollBuild() {
  setTimeout(async () => {
    const r = await fetch('/api/timelapse/status');
    const j = await r.json();
    const st  = document.getElementById('build-status');
    const bar = document.getElementById('prog-bar');
    if (j.state === 'running') {
      const pct = j.frames_total > 0
        ? Math.round(j.frames_done / j.frames_total * 100) : 0;
      bar.style.width = pct + '%';
      st.textContent  = j.stage + '… ' + j.frames_done + '/' + j.frames_total + ' frames';
      pollBuild();
    } else {
      _building = false;
      bar.style.width = j.state === 'done' ? '100%' : '0%';
      st.textContent  = j.state === 'done' ? 'Done!' : 'Error: ' + j.error;
      if (j.state === 'done') { loadTimelapses(); toast('Timelapse built!'); }
    }
  }, 1500);
}

async function loadTimelapses() {
  const r = await fetch('/api/timelapses');
  const j = await r.json();
  const list = document.getElementById('tl-list');
  list.textContent = '';  // safe clear
  (j.entries || []).forEach(e => {
    const card = document.createElement('div');
    card.className = 'tl-card';
    card.addEventListener('click', () =>
      window.open('/timelapse/' + encodeURIComponent(e.video), '_blank'));

    const img = document.createElement('img');
    img.src = e.thumbnail ? '/thumb/' + encodeURIComponent(e.thumbnail) : '';
    img.alt = '';

    const info = document.createElement('div');
    info.className = 'tl-card-info';

    const title = document.createElement('strong');
    title.textContent = e.date + ' ' + (e.type || e.label || '');

    const detail = document.createTextNode(
      '\n' + (e.frame_count || 0) + ' frames · ~' +
      fmtSecs((e.frame_count || 0) * 0.12)
    );

    info.append(title, detail);
    card.append(img, info);
    list.appendChild(card);
  });
}

// ── Status tab ────────────────────────────────────────────────────────────────
async function loadLog() {
  const r = await fetch('/api/pipeline/log');
  document.getElementById('log-box').textContent = await r.text();
}

async function runPipeline() {
  document.getElementById('pipe-status').textContent = 'Starting…';
  await fetch('/api/pipeline/run', {method: 'POST'});
  document.getElementById('pipe-status').textContent = 'Running in background…';
  setTimeout(loadLog, 3000);
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 5000);
}

initPhotos();
recalc();
</script>
</body>
</html>
"""


# ── HTTP handler ──────────────────────────────────────────────────────────────

class ContentHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info(fmt % args)

    def do_GET(self):
        p = urlparse(self.path).path

        if p == "/":
            self._send(200, "text/html", _HTML)
        elif p == "/api/images":
            self._send(200, "application/json",
                       json.dumps(images_by_category()).encode())
        elif p == "/api/timelapse/status":
            self._send(200, "application/json",
                       json.dumps(_job_snapshot()).encode())
        elif p == "/api/timelapses":
            self._send(200, "application/json", _timelapses_json())
        elif p == "/api/pipeline/log":
            self._send(200, "text/plain", _pipeline_log())
        elif p.startswith("/thumb/"):
            rel = safe_rel(unquote(p[len("/thumb/"):]))
            if not rel:
                self._send(403, "text/plain", b"Forbidden"); return
            data = make_thumb(rel)
            self._send(200 if data else 404, "image/jpeg", data)
        elif p.startswith("/photo/"):
            rel = safe_rel(unquote(p[len("/photo/"):]))
            if not rel:
                self._send(403, "text/plain", b"Forbidden"); return
            full = HIGHLIGHTS_DIR / rel
            self._send(200 if full.exists() else 404, "image/jpeg",
                       full.read_bytes() if full.exists() else b"")
        elif p.startswith("/timelapse/"):
            name = Path(unquote(p[len("/timelapse/"):])).name  # strip directory traversal
            full = HIGHLIGHTS_DIR / "timelapse" / name
            if not full.exists():
                self._send(404, "text/plain", b"Not found"); return
            self._send(200, "video/mp4", full.read_bytes())
        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self):
        p = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            self._send(400, "application/json", b'{"error":"bad json"}'); return

        if p == "/api/delete":
            safe_paths = [r for path in payload.get("paths", [])
                          if (r := safe_rel(path))]
            deleted = delete_snapshots(safe_paths)
            self._send(200, "application/json",
                       json.dumps({"deleted": deleted, "paths": safe_paths}).encode())
        elif p == "/api/timelapse/build":
            err = _start_build(payload)
            if err:
                self._send(409, "application/json",
                           json.dumps({"error": err}).encode())
            else:
                self._send(200, "application/json", b'{"ok":true}')
        elif p == "/api/pipeline/run":
            _run_pipeline()
            self._send(200, "application/json", b'{"ok":true}')
        else:
            self._send(404, "text/plain", b"Not found")

    def _send(self, status: int, ct: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Timelapse list ────────────────────────────────────────────────────────────

def _timelapses_json() -> bytes:
    mf = HIGHLIGHTS_DIR / "timelapse_manifest.json"
    return mf.read_bytes() if mf.exists() else b'{"entries":[]}'


# ── Pipeline log ──────────────────────────────────────────────────────────────

_PIPELINE_LOG = Path("/tmp/gtn_pipeline.log")


def _pipeline_log() -> bytes:
    if not _PIPELINE_LOG.exists():
        return b"No pipeline runs yet."
    lines = _PIPELINE_LOG.read_text(errors="replace").splitlines()
    return "\n".join(lines[-50:]).encode()


def _run_pipeline() -> None:
    script = Path(__file__).parent.parent / "cron-scan-sync.sh"
    if not script.exists():
        log.warning("cron-scan-sync.sh not found")
        return
    with open(_PIPELINE_LOG, "w") as fh:
        subprocess.Popen(["bash", str(script)], stdout=fh, stderr=subprocess.STDOUT)
    log.info("pipeline started")


# ── Build dispatch ────────────────────────────────────────────────────────────

def _start_build(payload: dict) -> str | None:
    """Validate payload and start background build. Returns error string or None."""
    if _job_snapshot()["state"] == "running":
        return "A build is already in progress"

    mode = payload.get("mode")
    if mode not in ("golden", "fullday", "custom"):
        return f"Unknown mode: {mode!r}"

    interval_secs = max(1, int(payload.get("interval_secs") or 10))

    try:
        start_dt, end_dt, label = _resolve_window(payload)
    except Exception as exc:
        return str(exc)

    _job_update(state="running", stage="starting", frames_done=0, frames_total=0, error="")
    threading.Thread(
        target=_build_thread, args=(start_dt, end_dt, label, interval_secs), daemon=True
    ).start()
    return None


def _resolve_window(payload: dict) -> tuple[datetime, datetime, str]:
    """Return (start_dt, end_dt, label) for a build payload."""
    from astral import LocationInfo
    from astral.sun import sun as astral_sun

    lat = float(os.getenv("LATITUDE", "39.8"))
    lon = float(os.getenv("LONGITUDE", "-98.5"))
    tz  = os.getenv("TZ", "America/Chicago")
    loc = LocationInfo(latitude=lat, longitude=lon, timezone=tz)
    pad = timedelta(minutes=GOLDEN_PAD_MIN)
    mode = payload["mode"]

    if mode == "golden":
        date = datetime.strptime(payload["date"], "%Y-%m-%d").date()
        kind = payload.get("type", "sunset")
        s = astral_sun(loc.observer, date=date, tzinfo=loc.tzinfo)
        center = s[kind].replace(tzinfo=None)
        return center - pad, center + pad, f"{payload['date'].replace('-','')}_{kind}"

    if mode == "fullday":
        date = datetime.strptime(payload["date"], "%Y-%m-%d").date()
        s = astral_sun(loc.observer, date=date, tzinfo=loc.tzinfo)
        start_dt = s["sunrise"].replace(tzinfo=None) - pad
        end_dt   = s["sunset"].replace(tzinfo=None)  + pad
        return start_dt, end_dt, f"{payload['date'].replace('-','')}_fullday"

    # custom
    start_dt = datetime.fromisoformat(payload["start"])
    end_dt   = datetime.fromisoformat(payload["end"])
    if end_dt <= start_dt:
        raise ValueError("end must be after start")
    raw   = payload.get("label") or "custom"
    label = "".join(c if c.isalnum() or c == "_" else "_" for c in raw)
    return start_dt, end_dt, f"{start_dt.strftime('%Y%m%d')}_{label}"


def _build_thread(start_dt: datetime, end_dt: datetime,
                  label: str, interval_secs: int) -> None:
    import frigate_extract as fe
    from timelapse_builder import _build_one

    tmp_dir = Path(tempfile.mkdtemp(prefix="gtn_tl_"))
    try:
        _job_update(stage="finding segments")
        segments = fe.find_segments(start_dt, end_dt, FRIGATE_DIR)
        if not segments:
            _job_update(state="error",
                        error="No Frigate recordings found for this window"); return

        window_secs   = (end_dt - start_dt).total_seconds()
        total_estimate = int(window_secs / interval_secs)
        _job_update(stage="extracting", frames_total=total_estimate)

        frames = fe.extract_frames(
            segments, start_dt, end_dt, interval_secs,
            tmp_dir / "frames",
            on_progress=lambda n: _job_update(frames_done=n),
        )
        if not frames:
            _job_update(state="error",
                        error="No frames extracted — check Frigate paths"); return

        _job_update(stage="encoding", frames_done=len(frames), frames_total=len(frames))
        out_dir  = HIGHLIGHTS_DIR / "timelapse"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{label}_timelapse.mp4"

        if not _build_one(frames, out_path, cpu_percent=15):
            _job_update(state="error", error="ffmpeg encode failed"); return

        _write_timelapse_manifest(label, out_path, frames, start_dt, end_dt)
        _job_update(state="done", frames_done=len(frames))

    except Exception as exc:
        log.exception("build thread error")
        _job_update(state="error", error=str(exc))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _write_timelapse_manifest(label: str, out_path: Path, frames: list[Path],
                               start_dt: datetime, end_dt: datetime) -> None:
    mf_path  = HIGHLIGHTS_DIR / "timelapse_manifest.json"
    manifest = json.loads(mf_path.read_text()) if mf_path.exists() else {"entries": []}

    parts    = label.split("_", 1)
    date_fmt = (f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:]}"
                if len(parts[0]) == 8 else label)
    tl_type  = parts[1] if len(parts) > 1 else "custom"

    try:
        thumb_rel = str(frames[0].relative_to(HIGHLIGHTS_DIR))
    except (IndexError, ValueError):
        thumb_rel = ""

    manifest["entries"].insert(0, {
        "session_key": label,
        "date":        date_fmt,
        "type":        tl_type,
        "label":       label,
        "frame_count": len(frames),
        "video":       out_path.name,
        "thumbnail":   thumb_rel,
        "source":      "frigate_extract",
        "start":       start_dt.isoformat(),
        "end":         end_dt.isoformat(),
        "created":     datetime.now().isoformat(),
    })
    manifest["updated"] = datetime.now().isoformat()
    mf_path.write_text(json.dumps(manifest, indent=2))


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    global HIGHLIGHTS_DIR, FRIGATE_DIR, SYNC_SCRIPT

    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--port",           type=int, default=8766)
    ap.add_argument("--highlights-dir", default=str(HIGHLIGHTS_DIR))
    ap.add_argument("--frigate-dir",    default=str(FRIGATE_DIR))
    ap.add_argument("--sync-script",    default="")
    args = ap.parse_args()

    HIGHLIGHTS_DIR = Path(args.highlights_dir)
    FRIGATE_DIR    = Path(args.frigate_dir)
    SYNC_SCRIPT    = Path(args.sync_script) if args.sync_script else None

    server = HTTPServer(("0.0.0.0", args.port), ContentHandler)
    log.info(f"GTN Content Manager  ->  http://192.168.100.202:{args.port}")
    log.info(f"highlights: {HIGHLIGHTS_DIR}  |  frigate: {FRIGATE_DIR}")
    log.info("Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Run all API tests**

```bash
cd /home/HighlyReflective/weather-station/highlight-curator
python -m pytest tests/test_content_manager_api.py -v
```
Expected: 6 passed

- [ ] **Run full test suite**

```bash
cd /home/HighlyReflective/weather-station/highlight-curator
python -m pytest tests/ -v
```
Expected: 16 passed

- [ ] **Commit**

```bash
cd /home/HighlyReflective/weather-station
git add highlight-curator/content_manager.py highlight-curator/tests/test_content_manager_api.py
git commit -m "feat(content-manager): full web UI — Photos/Timelapse/Status tabs, replaces cull_ui.py"
```

---

## Task 5: Retire `cull_ui.py` + update docker-compose

**Files:**
- Modify: `highlight-curator/cull_ui.py`
- Modify: `docker-compose.yml` (if applicable)

- [ ] **Add deprecation header to `cull_ui.py`**

Open `highlight-curator/cull_ui.py` and add these two lines before the docstring:

```python
# DEPRECATED — replaced by content_manager.py.
# This file is kept for reference only.
```

- [ ] **Check whether docker-compose references cull_ui.py**

```bash
grep -n "cull_ui" /home/HighlyReflective/weather-station/docker-compose.yml
```

If a service runs `cull_ui.py`, change its `command:` to:
```yaml
command: python3 /app/content_manager.py
```
If no match, skip.

- [ ] **Verify `content_manager.py` starts**

```bash
cd /home/HighlyReflective/weather-station/highlight-curator
python3 content_manager.py --help
```
Expected: shows `--port`, `--highlights-dir`, `--frigate-dir`, `--sync-script`

- [ ] **Commit**

```bash
cd /home/HighlyReflective/weather-station
git add highlight-curator/cull_ui.py docker-compose.yml
git commit -m "chore(content-manager): deprecate cull_ui.py"
```

---

## Task 6: Smoke test against live data

No automated tests — confirms the UI against real NAS data.

- [ ] **Start server pointing at real highlights and Frigate dirs**

```bash
cd /home/HighlyReflective/weather-station/highlight-curator
python3 content_manager.py \
  --highlights-dir /volume1/highlights \
  --frigate-dir /volume1/frigate \
  --port 8766
```

- [ ] **Photos tab** — open `http://192.168.100.202:8766`, confirm category tabs appear, thumbnails load, select and delete a test photo works.

- [ ] **Timelapse tab — estimate** — switch to Golden Hour / sunset / today. Confirm estimate shows `~360 frames, video ~43s`. Switch timing to Duration, enter `2` minutes — confirm interval estimate updates live without page refresh.

- [ ] **Timelapse tab — Full Day estimate** — switch to Full Day. Confirm estimate shows approximately 5,000–5,400 frames and ~10–11 min.

- [ ] **Timelapse tab — build** — pick a date with known Frigate recordings, click Build. Confirm progress bar appears and `frames_done/frames_total` updates. On completion a new card appears in the list below; click it to open the video in a new tab.

- [ ] **Status tab** — click Status tab, confirm log box shows text. Click "Run pipeline now", confirm status updates.

- [ ] **Commit smoke sign-off**

```bash
cd /home/HighlyReflective/weather-station
git commit --allow-empty -m "chore: content_manager smoke tested against live data"
```
