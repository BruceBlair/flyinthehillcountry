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
