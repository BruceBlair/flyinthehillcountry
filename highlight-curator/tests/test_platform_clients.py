import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from platforms.shutterstock import ShutterstockClient
from platforms.adobe_stock import AdobeStockClient


def _mock_urlopen(body: dict):
    m = MagicMock()
    m.__enter__ = lambda s: s
    m.__exit__ = MagicMock(return_value=False)
    m.read.return_value = json.dumps(body).encode()
    return m


def test_shutterstock_refresh_token():
    client = ShutterstockClient("cid", "csec")
    with patch("urllib.request.urlopen", return_value=_mock_urlopen({"access_token": "tok"})):
        client.refresh_token()
    assert client.access_token == "tok"


def test_shutterstock_upload_returns_asset_id(tmp_path):
    img = tmp_path / "t.jpg"
    img.write_bytes(b"FAKEJPEG")
    client = ShutterstockClient("cid", "csec", access_token="tok")
    with patch("urllib.request.urlopen", return_value=_mock_urlopen({"id": "9876"})):
        result = client.upload(img, {"title": "Test", "keywords": "test"})
    assert result["asset_id"] == "9876"


def test_adobe_refresh_token():
    client = AdobeStockClient("apikey", "csec")
    with patch("urllib.request.urlopen", return_value=_mock_urlopen({"access_token": "adobe_tok"})):
        client.refresh_token()
    assert client.access_token == "adobe_tok"


def test_adobe_upload_returns_asset_id(tmp_path):
    img = tmp_path / "t.jpg"
    img.write_bytes(b"FAKEJPEG")
    client = AdobeStockClient("apikey", "csec", access_token="tok")
    with patch("urllib.request.urlopen", return_value=_mock_urlopen({"id": "adobe_5678"})):
        result = client.upload(img, {"title": "Test", "keywords": "nature"})
    assert result["asset_id"] == "adobe_5678"
