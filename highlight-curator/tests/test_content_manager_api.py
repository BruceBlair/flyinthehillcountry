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


def test_root_serves_command_center(server):
    status, body = get(server + "/")
    assert status == 200
    assert b'id="sidebar"' in body  # unique to the new shell


def test_static_css_served(server):
    status, body = get(server + "/static/css/command_center.css")
    assert status == 200
    assert b"nav-item" in body  # verify actual CSS content served


def test_static_404_for_missing(server):
    try:
        get(server + "/static/does_not_exist.xyz")
        assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_static_traversal_blocked(server):
    try:
        get(server + "/static/../content_manager.py")
        assert False, "expected 403 or 404"
    except urllib.error.HTTPError as e:
        assert e.code in (403, 404)


def test_api_photos_returns_entries_with_flags(server):
    status, body = get(server + "/api/photos")
    data = json.loads(body)
    assert status == 200
    assert "entries" in data
    for e in data["entries"]:
        assert "flags" in e
        assert set(e["flags"]) >= {"crop", "enhance", "auth_hold"}
        assert "crop_region" in e
        assert "uploads" in e


def patch(url, body: dict):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="PATCH")
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())

def test_patch_flags_sets_crop(server):
    snap = "golden_hour/sunrise/20260511_070000_scene.jpg"
    status, data = patch(server + "/api/photos/" + urllib.parse.quote(snap, safe='') + "/flags",
                         {"crop": True})
    assert status == 200
    assert data["flags"]["crop"] is True

def test_patch_flags_unknown_returns_404(server):
    try:
        patch(server + "/api/photos/" + urllib.parse.quote("no_such/photo.jpg", safe='') + "/flags",
              {"crop": True})
        assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404

def test_patch_crop_region(server):
    snap = "golden_hour/sunrise/20260511_070000_scene.jpg"
    region = {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}
    status, data = patch(server + "/api/photos/" + urllib.parse.quote(snap, safe='') + "/crop_region",
                         region)
    assert status == 200
    assert data["crop_region"] == region


def delete_req(url):
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


def test_queue_empty_on_start(server):
    status, body = get(server + "/api/upload/queue")
    data = json.loads(body)
    assert status == 200
    assert data["mode"] == "manual"
    assert data["queue"] == []


def test_queue_add_and_remove(server):
    status, data = post(server + "/api/upload/queue/add", {
        "snapshot": "golden_hour/sunrise/20260511_070000_scene.jpg",
        "title": "Sunrise", "keywords": "sunrise, texas", "platforms": ["shutterstock"]
    })
    assert status == 200 and data["ok"] is True

    status, body = get(server + "/api/upload/queue")
    items = json.loads(body)["queue"]
    assert len(items) == 1
    snap = items[0]["snapshot"]

    status, data = delete_req(server + "/api/upload/queue/" + urllib.parse.quote(snap, safe=''))
    assert status == 200 and data["ok"] is True

    status, body = get(server + "/api/upload/queue")
    assert json.loads(body)["queue"] == []


def test_queue_mode_switch(server):
    status, data = post(server + "/api/upload/queue/mode", {"mode": "auto"})
    assert status == 200
    _, body = get(server + "/api/upload/queue")
    assert json.loads(body)["mode"] == "auto"


def test_platforms_status_returns_structure(server, monkeypatch, tmp_path):
    import content_manager as cm
    monkeypatch.setattr(cm, "CREDS_PATH", tmp_path / "creds.json")
    status, body = get(server + "/api/platforms/status")
    data = json.loads(body)
    assert status == 200
    assert "shutterstock" in data
    assert "adobe_stock" in data
    assert "access_token" not in json.dumps(data)


def test_platforms_credentials_save(server, monkeypatch, tmp_path):
    import content_manager as cm
    monkeypatch.setattr(cm, "CREDS_PATH", tmp_path / "creds.json")
    status, data = post(server + "/api/platforms/credentials", {
        "platform": "shutterstock",
        "client_id": "test_id",
        "client_secret": "test_secret"
    })
    assert status == 200
    assert data["ok"] is True
    assert (tmp_path / "creds.json").exists()
