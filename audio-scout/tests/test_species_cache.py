import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from species_cache import lookup_species, _load_cache, _save_cache


@pytest.fixture
def cache_file(tmp_path):
    return tmp_path / "species_cache.json"


def test_cache_hit_skips_api(cache_file):
    existing = {"Mimus polyglottos": {"family": "Mimidae", "conservation_status": "LC"}}
    cache_file.write_text(json.dumps(existing))
    with patch("species_cache.requests.get") as mock_get:
        result = lookup_species("Mimus polyglottos", cache_path=cache_file)
    mock_get.assert_not_called()
    assert result["family"] == "Mimidae"


def test_cache_miss_calls_inaturalist(cache_file):
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {
        "results": [{
            "name": "Mimus polyglottos",
            "preferred_common_name": "Northern Mockingbird",
            "default_photo": None,
            "conservation_status": {"status": "LC"},
            "taxon_scheme_taxa": [],
        }]
    }
    with patch("species_cache.requests.get", return_value=mock_response):
        result = lookup_species("Mimus polyglottos", cache_path=cache_file)
    assert result.get("conservation_status") == "LC"
    # Verify it was cached
    cached = json.loads(cache_file.read_text())
    assert "Mimus polyglottos" in cached


def test_unknown_scientific_name_returns_empty(cache_file):
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {"results": []}
    with patch("species_cache.requests.get", return_value=mock_response):
        result = lookup_species("Unknown species", cache_path=cache_file)
    assert result == {}


def test_api_error_returns_empty(cache_file):
    mock_response = MagicMock()
    mock_response.ok = False
    with patch("species_cache.requests.get", return_value=mock_response):
        result = lookup_species("Mimus polyglottos", cache_path=cache_file)
    assert result == {}
