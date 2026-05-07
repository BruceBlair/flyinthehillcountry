import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from species_cache import lookup_species, _load_cache, _save_cache


@pytest.fixture
def cache_file(tmp_path):
    return tmp_path / "species_cache.json"


def _inat_mock(status_ok=True, results=None):
    mock = MagicMock()
    mock.ok = status_ok
    mock.json.return_value = {"results": results or []}
    return mock


def _inat_species_result():
    return [{
        "name": "Mimus polyglottos",
        "preferred_common_name": "Northern Mockingbird",
        "default_photo": None,
        "conservation_status": {"status": "LC"},
        "ancestors": [{"rank": "family", "name": "Mimidae"}],
    }]


def test_cache_hit_skips_api(cache_file):
    existing = {"Mimus polyglottos": {"family": "Mimidae", "conservation_status": "LC"}}
    cache_file.write_text(json.dumps(existing))
    with patch("species_cache.requests.get") as mock_get:
        result = lookup_species("Mimus polyglottos", cache_path=cache_file)
    mock_get.assert_not_called()
    assert result["family"] == "Mimidae"


def test_cache_miss_calls_inaturalist(cache_file):
    mock_response = _inat_mock(results=_inat_species_result())
    with patch("species_cache.requests.get", return_value=mock_response):
        result = lookup_species("Mimus polyglottos", cache_path=cache_file)
    assert result.get("conservation_status") == "LC"
    assert result.get("family") == "Mimidae"
    cached = json.loads(cache_file.read_text())
    assert "Mimus polyglottos" in cached


def test_cache_miss_api_actually_called(cache_file):
    mock_response = _inat_mock(results=_inat_species_result())
    with patch("species_cache.requests.get", return_value=mock_response) as mock_get:
        lookup_species("Mimus polyglottos", cache_path=cache_file)
    mock_get.assert_called_once()


def test_unknown_scientific_name_returns_empty(cache_file):
    mock_response = _inat_mock(results=[])
    with patch("species_cache.requests.get", return_value=mock_response):
        result = lookup_species("Unknown species", cache_path=cache_file)
    assert result == {}


def test_api_error_returns_empty(cache_file):
    mock_response = _inat_mock(status_ok=False)
    with patch("species_cache.requests.get", return_value=mock_response):
        result = lookup_species("Mimus polyglottos", cache_path=cache_file)
    assert result == {}


def test_ebird_enrichment_when_key_set(cache_file):
    inat_mock = _inat_mock(results=_inat_species_result())
    ebird_mock = MagicMock()
    ebird_mock.ok = True
    ebird_mock.json.return_value = [{"speciesCode": "normoc"}]

    call_count = [0]
    def mock_get(url, **kwargs):
        call_count[0] += 1
        if "inaturalist" in url:
            return inat_mock
        return ebird_mock

    with patch("species_cache.requests.get", side_effect=mock_get):
        with patch.dict(os.environ, {"EBIRD_API_KEY": "testkey"}):
            result = lookup_species("Mimus polyglottos", cache_path=cache_file)

    assert result.get("ebird_species_code") == "normoc"
    assert call_count[0] == 2   # iNaturalist + eBird


def test_ebird_skipped_when_no_key(cache_file):
    inat_mock = _inat_mock(results=_inat_species_result())
    with patch("species_cache.requests.get", return_value=inat_mock) as mock_get:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("EBIRD_API_KEY", None)
            result = lookup_species("Mimus polyglottos", cache_path=cache_file)
    assert mock_get.call_count == 1   # only iNaturalist called
    assert "ebird_species_code" not in result


def test_save_cache_handles_write_error(cache_file):
    cache = {"Mimus polyglottos": {"family": "Mimidae"}}
    # Should not raise even on write failure
    with patch("species_cache.Path.write_text", side_effect=OSError("read-only")):
        _save_cache(cache, cache_file)   # must not raise
