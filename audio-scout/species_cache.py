"""Species info lookup via iNaturalist API with local JSON cache."""
import os
from pathlib import Path

import requests

EBIRD_API_KEY     = os.getenv("EBIRD_API_KEY", "")
DEFAULT_CACHE     = Path("/highlights/audio/species_cache.json")
INAT_SEARCH_URL   = "https://api.inaturalist.org/v1/taxa"
EBIRD_SPECIES_URL = "https://api.ebird.org/v2/ref/taxonomy/ebird"


def lookup_species(scientific_name: str, cache_path: Path = DEFAULT_CACHE) -> dict:
    """Return species info dict; empty dict on failure. Caches by scientific name."""
    if not scientific_name:
        return {}
    cache = _load_cache(cache_path)
    if scientific_name in cache:
        return cache[scientific_name]

    info = _fetch_inaturalist(scientific_name)
    if info and EBIRD_API_KEY:
        info.update(_fetch_ebird(scientific_name))

    if info:
        cache[scientific_name] = info
        _save_cache(cache, cache_path)
    return info


def _fetch_inaturalist(scientific_name: str) -> dict:
    try:
        resp = requests.get(
            INAT_SEARCH_URL,
            params={"q": scientific_name, "rank": "species", "per_page": 1},
            timeout=10,
        )
        if not resp.ok:
            return {}
        results = resp.json().get("results", [])
        if not results:
            return {}
        taxon = results[0]
        cs = taxon.get("conservation_status") or {}
        return {
            "family": _extract_family(taxon),
            "conservation_status": cs.get("status", ""),
            "description": taxon.get("wikipedia_summary", ""),
        }
    except Exception:
        return {}


def _fetch_ebird(scientific_name: str) -> dict:
    try:
        resp = requests.get(
            EBIRD_SPECIES_URL,
            params={"sci": scientific_name, "fmt": "json"},
            headers={"X-eBirdApiToken": EBIRD_API_KEY},
            timeout=10,
        )
        if not resp.ok or not resp.json():
            return {}
        entry = resp.json()[0]
        code = entry.get("speciesCode", "")
        return {
            "ebird_species_code": code,
            "range_map_url": f"https://ebird.org/species/{code}" if code else "",
        }
    except Exception:
        return {}


def _extract_family(taxon: dict) -> str:
    for anc in taxon.get("ancestors", []):
        if anc.get("rank") == "family":
            return anc.get("name", "")
    return ""


def _load_cache(path: Path) -> dict:
    if path.exists():
        try:
            import json
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache: dict, path: Path) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2))
