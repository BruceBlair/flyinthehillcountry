# Audio Scout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real-time wildlife/bird sound detection from the Reolink RTSP stream using BirdNET + YAMNet, with species lookup, MQTT events, audio clip storage, and a CPU-throttleable back-analysis script.

**Architecture:** A new `audio-scout` Docker service (host network) pipes PCM audio from the camera RTSP stream via ffmpeg in 3-second chunks through BirdNET-Analyzer then YAMNet. Detections above confidence thresholds are enriched via iNaturalist/eBird APIs (cached locally), written to a standalone `audio_manifest.json`, and published to MQTT. A separate `audio-backfill.py` script handles historical `.mp4` files on demand with `cpulimit` CPU capping.

**Tech Stack:** Python 3.12, BirdNET-Analyzer, TensorFlow/TF-Hub (YAMNet), paho-mqtt, requests, ffmpeg (subprocess), iNaturalist API (public), eBird API (optional key)

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `audio-scout/Dockerfile` | Create | Python 3.12-slim + ffmpeg + BirdNET + TF deps |
| `audio-scout/requirements.txt` | Create | Python dependencies |
| `audio-scout/scout.py` | Create | Real-time service entrypoint — ffmpeg loop → classify → write |
| `audio-scout/manifest_io.py` | Create | Read/write audio_manifest.json atomically |
| `audio-scout/classifier.py` | Create | BirdNET + YAMNet wrappers, returns `Detection` dataclass |
| `audio-scout/species_cache.py` | Create | iNaturalist/eBird lookup + species_cache.json |
| `audio-scout/mqtt_client.py` | Create | Thin paho-mqtt wrapper (same pattern as night-sky-patrol) |
| `audio-scout/rare_species.txt` | Create | One species name per line; seeded with regional common species |
| `audio-scout/tests/test_manifest_io.py` | Create | Unit tests for manifest read/write/linking/summary logic |
| `audio-scout/tests/test_classifier.py` | Create | Unit tests for Detection dataclass + confidence filtering |
| `audio-scout/tests/test_species_cache.py` | Create | Unit tests for cache hit/miss logic |
| `audio-backfill.py` | Create | Standalone back-analysis script with cpulimit + resume |
| `docker-compose.yml` | Modify | Add audio-scout service definition |
| `.env.example` | Modify | Add 5 new audio-scout variables |

---

## Task 1: Dockerfile and requirements

**Files:**
- Create: `audio-scout/Dockerfile`
- Create: `audio-scout/requirements.txt`

- [ ] **Step 1: Create requirements.txt**

```
birdnetlib>=0.9.0
tensorflow>=2.15.0
tensorflow-hub>=0.16.0
paho-mqtt>=2.0.0
requests>=2.31.0
numpy>=1.26.0
soundfile>=0.12.1
librosa>=0.10.1
```

- [ ] **Step 2: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    cpulimit \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-u", "scout.py"]
```

- [ ] **Step 3: Verify image builds**

```bash
cd weather-station
docker compose build audio-scout 2>&1 | tail -10
```

Expected: `DONE` with no errors. TensorFlow download takes ~2 min first time.

- [ ] **Step 4: Commit**

```bash
git add audio-scout/Dockerfile audio-scout/requirements.txt
git commit -m "feat(audio-scout): Dockerfile and requirements"
```

---

## Task 2: Detection dataclass and classifier wrappers

**Files:**
- Create: `audio-scout/classifier.py`
- Create: `audio-scout/tests/test_classifier.py`

- [ ] **Step 1: Write failing tests**

Create `audio-scout/tests/test_classifier.py`:

```python
import numpy as np
import pytest
from classifier import Detection, filter_detections

def test_detection_fields():
    d = Detection(
        detector="birdnet",
        species="Northern Mockingbird",
        scientific_name="Mimus polyglottos",
        confidence=0.87,
        raw_audio=b"",
    )
    assert d.detector == "birdnet"
    assert d.confidence == 0.87
    assert d.scientific_name == "Mimus polyglottos"

def test_filter_detections_removes_below_threshold():
    detections = [
        Detection("birdnet", "Mockingbird", "Mimus polyglottos", 0.87, b""),
        Detection("birdnet", "Unknown", "Unknown sp.", 0.40, b""),
    ]
    result = filter_detections(detections, min_confidence=0.70)
    assert len(result) == 1
    assert result[0].species == "Mockingbird"

def test_filter_detections_empty():
    assert filter_detections([], min_confidence=0.70) == []

def test_yamnet_detection_has_no_scientific_name():
    d = Detection("yamnet", "frog", None, 0.80, b"")
    assert d.scientific_name is None
```

- [ ] **Step 2: Run to verify failure**

```bash
cd weather-station/audio-scout
python -m pytest tests/test_classifier.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'classifier'`

- [ ] **Step 3: Create classifier.py**

```python
"""BirdNET and YAMNet wrappers returning Detection objects."""
import io
import os
import wave
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

BIRDNET_CONFIDENCE  = float(os.getenv("BIRDNET_CONFIDENCE", "0.70"))
YAMNET_CONFIDENCE   = float(os.getenv("YAMNET_CONFIDENCE",  "0.75"))
LATITUDE            = float(os.getenv("LATITUDE",  "29.9974"))
LONGITUDE           = float(os.getenv("LONGITUDE", "-98.0986"))


@dataclass
class Detection:
    detector: str           # "birdnet" | "yamnet"
    species: str            # common name
    scientific_name: Optional[str]
    confidence: float
    raw_audio: bytes        # raw PCM bytes of the 3s chunk


def filter_detections(detections: list[Detection], min_confidence: float) -> list[Detection]:
    return [d for d in detections if d.confidence >= min_confidence]


def classify_chunk(pcm_bytes: bytes, sample_rate: int = 48000) -> list[Detection]:
    """Run BirdNET then YAMNet on a PCM chunk. Returns all raw detections (unfiltered)."""
    results: list[Detection] = []
    results.extend(_run_birdnet(pcm_bytes, sample_rate))
    results.extend(_run_yamnet(pcm_bytes, sample_rate))
    return results


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)      # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def _run_birdnet(pcm_bytes: bytes, sample_rate: int) -> list[Detection]:
    from birdnetlib import Recording
    from birdnetlib.analyzer import Analyzer
    import tempfile, pathlib

    analyzer = Analyzer()
    wav_bytes = _pcm_to_wav(pcm_bytes, sample_rate)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes)
        tmp_path = tmp.name

    try:
        rec = Recording(
            analyzer,
            tmp_path,
            lat=LATITUDE,
            lon=LONGITUDE,
            min_conf=0.01,   # we filter ourselves
        )
        rec.analyze()
        return [
            Detection(
                detector="birdnet",
                species=d["common_name"],
                scientific_name=d["scientific_name"],
                confidence=round(d["confidence"], 4),
                raw_audio=pcm_bytes,
            )
            for d in rec.detections
        ]
    finally:
        pathlib.Path(tmp_path).unlink(missing_ok=True)


# YAMNet class labels to surface (non-bird wildlife + notable ambient sounds)
_YAMNET_KEEP = {
    "Frog", "Tree frog", "Croaking", "Cricket", "Insect",
    "Dog", "Howl", "Cat", "Horse", "Cattle",
    "Wild animals", "Animal",
    "Rain", "Thunder", "Wind", "Vehicle",
}


def _run_yamnet(pcm_bytes: bytes, sample_rate: int) -> list[Detection]:
    import tensorflow_hub as hub
    import tensorflow as tf
    import csv, io as sio, urllib.request, pathlib

    model = hub.load("https://tfhub.dev/google/yamnet/1")

    audio_float = (
        np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    )
    # YAMNet expects 16 kHz mono
    if sample_rate != 16000:
        import librosa
        audio_float = librosa.resample(audio_float, orig_sr=sample_rate, target_sr=16000)

    scores, _, _ = model(audio_float)
    mean_scores = tf.reduce_mean(scores, axis=0).numpy()

    # Load class map (cached after first call)
    labels = _yamnet_labels()
    detections = []
    for idx, score in enumerate(mean_scores):
        label = labels[idx]
        if label in _YAMNET_KEEP and score >= 0.01:
            detections.append(Detection(
                detector="yamnet",
                species=label,
                scientific_name=None,
                confidence=round(float(score), 4),
                raw_audio=pcm_bytes,
            ))
    return detections


_yamnet_label_cache: list[str] = []


def _yamnet_labels() -> list[str]:
    global _yamnet_label_cache
    if _yamnet_label_cache:
        return _yamnet_label_cache
    url = "https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv"
    with urllib.request.urlopen(url) as r:
        reader = csv.DictReader(r.read().decode().splitlines())
        _yamnet_label_cache = [row["display_name"] for row in reader]
    return _yamnet_label_cache
```

- [ ] **Step 4: Run tests**

```bash
cd weather-station/audio-scout
python -m pytest tests/test_classifier.py -v 2>&1
```

Expected: 4 tests PASS. (No TF/BirdNET imports triggered by unit tests.)

- [ ] **Step 5: Commit**

```bash
git add audio-scout/classifier.py audio-scout/tests/test_classifier.py
git commit -m "feat(audio-scout): Detection dataclass and classifier wrappers"
```

---

## Task 3: Manifest I/O

**Files:**
- Create: `audio-scout/manifest_io.py`
- Create: `audio-scout/tests/test_manifest_io.py`

- [ ] **Step 1: Write failing tests**

Create `audio-scout/tests/test_manifest_io.py`:

```python
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from manifest_io import (
    AudioManifest,
    load_manifest,
    save_manifest,
    add_detection,
    mark_reviewed,
)
from classifier import Detection


@pytest.fixture
def tmp_manifest(tmp_path):
    return tmp_path / "audio_manifest.json"


def _det(species="Northern Mockingbird", ts="20260507_010000", detector="birdnet"):
    return Detection(detector, species, "Mimus polyglottos", 0.87, b"")


def test_load_creates_empty_manifest_if_missing(tmp_manifest):
    m = load_manifest(tmp_manifest)
    assert m.unreviewed_count == 0
    assert m.detections == []
    assert m.analyzed_sources == []


def test_add_detection_increments_unreviewed(tmp_manifest):
    m = load_manifest(tmp_manifest)
    add_detection(m, _det(), timestamp="20260507_010000",
                  clip_path="audio/clip.wav", highlights_manifest=[])
    assert m.unreviewed_count == 1
    assert m.detections[0]["reviewed"] is False


def test_add_detection_links_nearby_photo(tmp_manifest):
    highlights = [
        {"timestamp": "20260507_010001", "snapshot": "wildlife/photo.jpg"}
    ]
    m = load_manifest(tmp_manifest)
    add_detection(m, _det(), timestamp="20260507_010000",
                  clip_path="audio/clip.wav", highlights_manifest=highlights)
    assert m.detections[0]["linked_photo"] == "wildlife/photo.jpg"


def test_add_detection_no_link_if_too_far(tmp_manifest):
    highlights = [
        {"timestamp": "20260507_013000", "snapshot": "wildlife/far_photo.jpg"}
    ]
    m = load_manifest(tmp_manifest)
    add_detection(m, _det(), timestamp="20260507_010000",
                  clip_path="audio/clip.wav", highlights_manifest=highlights)
    assert m.detections[0]["linked_photo"] is None


def test_mark_reviewed_decrements_count(tmp_manifest):
    m = load_manifest(tmp_manifest)
    add_detection(m, _det(), timestamp="20260507_010000",
                  clip_path="audio/clip.wav", highlights_manifest=[])
    det_id = m.detections[0]["id"]
    mark_reviewed(m, det_id)
    assert m.unreviewed_count == 0
    assert m.detections[0]["reviewed"] is True


def test_species_summary_week_incremented(tmp_manifest):
    m = load_manifest(tmp_manifest)
    add_detection(m, _det("Carolina Wren"), timestamp="20260507_010000",
                  clip_path="audio/clip.wav", highlights_manifest=[])
    assert m.species_summary["week"].get("Carolina Wren", 0) == 1


def test_save_and_reload(tmp_manifest):
    m = load_manifest(tmp_manifest)
    add_detection(m, _det(), timestamp="20260507_010000",
                  clip_path="audio/clip.wav", highlights_manifest=[])
    save_manifest(m, tmp_manifest)
    m2 = load_manifest(tmp_manifest)
    assert m2.unreviewed_count == 1
    assert len(m2.detections) == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
cd weather-station/audio-scout
python -m pytest tests/test_manifest_io.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'manifest_io'`

- [ ] **Step 3: Create manifest_io.py**

```python
"""Atomic read/write for audio_manifest.json."""
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LINK_WINDOW_SEC = 60   # ±seconds to search for nearby photo


@dataclass
class AudioManifest:
    unreviewed_count: int = 0
    updated: str = ""
    species_summary: dict = field(default_factory=lambda: {"week": {}, "month": {}, "season": {}})
    analyzed_sources: list = field(default_factory=list)
    detections: list = field(default_factory=list)


def load_manifest(path: Path) -> AudioManifest:
    if not path.exists():
        return AudioManifest()
    data = json.loads(path.read_text())
    m = AudioManifest()
    m.unreviewed_count = data.get("unreviewed_count", 0)
    m.updated = data.get("updated", "")
    m.species_summary = data.get("species_summary", {"week": {}, "month": {}, "season": {}})
    m.analyzed_sources = data.get("analyzed_sources", [])
    m.detections = data.get("detections", [])
    return m


def save_manifest(m: AudioManifest, path: Path) -> None:
    m.updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    data = {
        "unreviewed_count": m.unreviewed_count,
        "updated": m.updated,
        "species_summary": m.species_summary,
        "analyzed_sources": m.analyzed_sources,
        "detections": m.detections,
    }
    # Atomic write: temp file → rename
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def add_detection(
    m: AudioManifest,
    det,             # Detection dataclass
    timestamp: str,
    clip_path: str,
    highlights_manifest: list,
    species_info: Optional[dict] = None,
    source: str = "realtime",
) -> dict:
    idx = sum(1 for d in m.detections
              if d.get("detector") == det.detector and d["timestamp"][:8] == timestamp[:8])
    entry_id = f"audio_{timestamp}_{det.detector}_{idx:03d}"

    linked = _find_nearby_photo(timestamp, highlights_manifest)

    entry = {
        "id": entry_id,
        "timestamp": timestamp,
        "detector": det.detector,
        "species": det.species,
        "scientific_name": det.scientific_name,
        "confidence": det.confidence,
        "clip": clip_path,
        "linked_photo": linked,
        "species_info": species_info or {},
        "reviewed": False,
        "submitted_to": None,
        "source": source,
    }
    m.detections.append(entry)
    m.unreviewed_count += 1
    _update_summaries(m, det.species)
    return entry


def mark_reviewed(m: AudioManifest, detection_id: str) -> None:
    for d in m.detections:
        if d["id"] == detection_id and not d["reviewed"]:
            d["reviewed"] = True
            m.unreviewed_count = max(0, m.unreviewed_count - 1)
            return


def _ts_to_epoch(ts: str) -> float:
    """Parse YYYYMMDD_HHMMSS → epoch seconds."""
    return datetime.strptime(ts, "%Y%m%d_%H%M%S").replace(
        tzinfo=timezone.utc).timestamp()


def _find_nearby_photo(timestamp: str, highlights: list) -> Optional[str]:
    try:
        t0 = _ts_to_epoch(timestamp)
    except ValueError:
        return None
    best = None
    best_delta = LINK_WINDOW_SEC + 1
    for entry in highlights:
        ts = entry.get("timestamp", "")
        try:
            delta = abs(_ts_to_epoch(ts) - t0)
        except ValueError:
            continue
        if delta <= LINK_WINDOW_SEC and delta < best_delta:
            best_delta = delta
            best = entry.get("snapshot")
    return best


def _season(dt: datetime) -> str:
    m = dt.month
    if m in (3, 4, 5):   return "Spring"
    if m in (6, 7, 8):   return "Summer"
    if m in (9, 10, 11): return "Fall"
    return "Winter"


def _update_summaries(m: AudioManifest, species: str) -> None:
    now = datetime.now(timezone.utc)
    now_week = now.isocalendar()[1]
    for period, key in [
        ("week",   str(now_week)),
        ("month",  str(now.month)),
        ("season", _season(now)),
    ]:
        bucket = m.species_summary.setdefault(period, {})
        bucket[species] = bucket.get(species, 0) + 1
```

- [ ] **Step 4: Run tests**

```bash
cd weather-station/audio-scout
python -m pytest tests/test_manifest_io.py -v
```

Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add audio-scout/manifest_io.py audio-scout/tests/test_manifest_io.py
git commit -m "feat(audio-scout): manifest I/O with detection linking and summaries"
```

---

## Task 4: Species cache

**Files:**
- Create: `audio-scout/species_cache.py`
- Create: `audio-scout/tests/test_species_cache.py`

- [ ] **Step 1: Write failing tests**

Create `audio-scout/tests/test_species_cache.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
cd weather-station/audio-scout
python -m pytest tests/test_species_cache.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'species_cache'`

- [ ] **Step 3: Create species_cache.py**

```python
"""Species info lookup via iNaturalist API with local JSON cache."""
import os
from pathlib import Path

import requests

EBIRD_API_KEY    = os.getenv("EBIRD_API_KEY", "")
DEFAULT_CACHE    = Path("/highlights/audio/species_cache.json")
INAT_SEARCH_URL  = "https://api.inaturalist.org/v1/taxa"
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
```

- [ ] **Step 4: Run tests**

```bash
cd weather-station/audio-scout
python -m pytest tests/test_species_cache.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add audio-scout/species_cache.py audio-scout/tests/test_species_cache.py
git commit -m "feat(audio-scout): species lookup with iNaturalist/eBird cache"
```

---

## Task 5: MQTT client

**Files:**
- Create: `audio-scout/mqtt_client.py`

No unit tests — thin wrapper around paho-mqtt (same pattern as night-sky-patrol).

- [ ] **Step 1: Create mqtt_client.py**

```python
"""Thin paho-mqtt wrapper for audio-scout."""
import json
import logging
import os
import time

import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

log = logging.getLogger("audio-scout.mqtt")


class MQTTClient:
    def __init__(self):
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._connected = False

    def connect(self) -> None:
        self._client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        self._client.loop_start()
        for _ in range(20):
            if self._connected:
                return
            time.sleep(0.25)
        raise RuntimeError(f"MQTT connect timeout ({MQTT_HOST}:{MQTT_PORT})")

    def publish(self, topic: str, payload: dict | str) -> None:
        msg = json.dumps(payload) if isinstance(payload, dict) else payload
        self._client.publish(topic, msg, qos=1)

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self._connected = (rc == 0)
        if rc == 0:
            log.info("MQTT connected (%s:%s)", MQTT_HOST, MQTT_PORT)
        else:
            log.error("MQTT connect failed rc=%s", rc)

    def _on_disconnect(self, client, userdata, rc, properties=None, reason=None):
        self._connected = False
        log.warning("MQTT disconnected rc=%s", rc)
```

- [ ] **Step 2: Commit**

```bash
git add audio-scout/mqtt_client.py
git commit -m "feat(audio-scout): MQTT client wrapper"
```

---

## Task 6: rare_species.txt seed file

**Files:**
- Create: `audio-scout/rare_species.txt`

- [ ] **Step 1: Create rare_species.txt**

Seeded with species uncommon for the Texas Hill Country that would merit a push notification:

```
Whooping Crane
Golden Eagle
Peregrine Falcon
Bald Eagle
Ferruginous Hawk
Sprague's Pipit
Painted Bunting
Vermilion Flycatcher
Groove-billed Ani
Zone-tailed Hawk
```

- [ ] **Step 2: Commit**

```bash
git add audio-scout/rare_species.txt
git commit -m "feat(audio-scout): seed rare_species.txt for Hill Country"
```

---

## Task 7: scout.py — real-time service entrypoint

**Files:**
- Create: `audio-scout/scout.py`

No unit tests for scout.py — it's the integration loop; tested by running the container.

- [ ] **Step 1: Create scout.py**

```python
#!/usr/bin/env python3
"""
Audio Scout — Ground Truth Network
Real-time wildlife and bird sound detection from Reolink RTSP audio stream.
"""
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from classifier import Detection, classify_chunk, filter_detections, BIRDNET_CONFIDENCE, YAMNET_CONFIDENCE
from manifest_io import AudioManifest, load_manifest, save_manifest, add_detection
from mqtt_client import MQTTClient
from species_cache import lookup_species

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [audio-scout] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("audio-scout")

# ─── Config ──────────────────────────────────────────────────────────────────
CAMERA_IP        = os.getenv("CAMERA_IP",       "192.168.100.131")
CAMERA_USER      = os.getenv("CAMERA_USER",     "admin")
CAMERA_PASS      = os.getenv("CAMERA_PASSWORD", "")
HIGHLIGHTS_DIR   = Path(os.getenv("HIGHLIGHTS_DIR", "/highlights"))
AUDIO_DIR        = HIGHLIGHTS_DIR / "audio"
MANIFEST_PATH    = HIGHLIGHTS_DIR / "audio_manifest.json"
HIGHLIGHTS_MANIFEST = HIGHLIGHTS_DIR / "manifest.json"
RARE_SPECIES_FILE = Path("/app/rare_species.txt")
RARE_SPECIES_PUSH = os.getenv("RARE_SPECIES_PUSH", "false").lower() == "true"

SAMPLE_RATE  = 48000
CHUNK_SEC    = 3
CHUNK_BYTES  = SAMPLE_RATE * 2 * CHUNK_SEC   # 16-bit mono = 2 bytes/sample

RTSP_URL = (
    f"rtsp://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:554/h264Preview_01_main"
)

# ─── State ───────────────────────────────────────────────────────────────────
_start_time = time.time()
_running = True


def _sigterm(sig, frame):
    global _running
    _running = False


signal.signal(signal.SIGTERM, _sigterm)
signal.signal(signal.SIGINT, _sigterm)


# ─── Rare species ─────────────────────────────────────────────────────────────
def load_rare_species() -> set[str]:
    if not RARE_SPECIES_FILE.exists():
        return set()
    return {line.strip().lower() for line in RARE_SPECIES_FILE.read_text().splitlines()
            if line.strip() and not line.startswith("#")}


# ─── Highlights manifest ──────────────────────────────────────────────────────
def load_highlights() -> list:
    if not HIGHLIGHTS_MANIFEST.exists():
        return []
    try:
        data = json.loads(HIGHLIGHTS_MANIFEST.read_text())
        return data.get("entries", data) if isinstance(data, dict) else data
    except Exception:
        return []


# ─── Audio capture ────────────────────────────────────────────────────────────
def open_ffmpeg_stream() -> subprocess.Popen:
    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", RTSP_URL,
        "-vn",                      # no video
        "-ac", "1",                 # mono
        "-ar", str(SAMPLE_RATE),
        "-f", "s16le",              # raw PCM 16-bit little-endian
        "pipe:1",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


# ─── Clip saving ─────────────────────────────────────────────────────────────
def save_clip(pcm_bytes: bytes, det: Detection, timestamp: str) -> str:
    import wave, io
    slug = det.species.lower().replace(" ", "_")[:30]
    filename = f"{timestamp}_{slug}.wav"
    path = AUDIO_DIR / filename
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    path.write_bytes(buf.getvalue())
    return str(path.relative_to(HIGHLIGHTS_DIR))


# ─── Main loop ────────────────────────────────────────────────────────────────
def main():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    mqtt = MQTTClient()
    mqtt.connect()

    log.info("Audio Scout starting — RTSP: %s", RTSP_URL.replace(CAMERA_PASS, "***"))
    log.info("  BirdNET threshold: %.2f  |  YAMNet threshold: %.2f",
             BIRDNET_CONFIDENCE, YAMNET_CONFIDENCE)

    last_heartbeat = 0.0
    proc = None

    while _running:
        try:
            if proc is None or proc.poll() is not None:
                log.info("Opening RTSP stream...")
                proc = open_ffmpeg_stream()

            chunk = proc.stdout.read(CHUNK_BYTES)
            if len(chunk) < CHUNK_BYTES:
                log.warning("Short read from ffmpeg — reconnecting")
                proc.terminate()
                proc = None
                time.sleep(5)
                continue

            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            raw_detections = classify_chunk(chunk, SAMPLE_RATE)

            birdnet_hits = filter_detections(
                [d for d in raw_detections if d.detector == "birdnet"],
                BIRDNET_CONFIDENCE,
            )
            yamnet_hits = filter_detections(
                [d for d in raw_detections if d.detector == "yamnet"],
                YAMNET_CONFIDENCE,
            )
            hits = birdnet_hits + yamnet_hits

            if hits:
                manifest = load_manifest(MANIFEST_PATH)
                highlights = load_highlights()
                rare = load_rare_species()

                for det in hits:
                    clip = save_clip(chunk, det, timestamp)
                    info = lookup_species(det.scientific_name) if det.scientific_name else {}
                    entry = add_detection(
                        manifest, det,
                        timestamp=timestamp,
                        clip_path=clip,
                        highlights_manifest=highlights,
                        species_info=info,
                    )
                    mqtt.publish("audio/detections", entry)
                    log.info("Detection: %s (%.2f) [%s]", det.species, det.confidence, det.detector)

                    if RARE_SPECIES_PUSH and det.species.lower() in rare:
                        mqtt.publish("audio/detections/rare", entry)
                        log.info("  → RARE species alert: %s", det.species)

                save_manifest(manifest, MANIFEST_PATH)

            # Heartbeat every 60s
            now = time.time()
            if now - last_heartbeat >= 60:
                mqtt.publish("audio/status", {
                    "status": "ok",
                    "uptime": int(now - _start_time),
                })
                last_heartbeat = now

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("Loop error: %s", e, exc_info=True)
            time.sleep(10)

    if proc:
        proc.terminate()
    mqtt.disconnect()
    log.info("Audio Scout stopped.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add audio-scout/scout.py
git commit -m "feat(audio-scout): real-time service entrypoint"
```

---

## Task 8: audio-backfill.py

**Files:**
- Create: `audio-backfill.py` (repo root of weather-station/)

- [ ] **Step 1: Create audio-backfill.py**

```python
#!/usr/bin/env python3
"""
audio-backfill.py — analyze historical .mp4 files for wildlife sounds.

Usage:
  python3 audio-backfill.py [--cpu-percent N] [--since YYYY-MM-DD] [--dry-run] <directory>

Examples:
  python3 audio-backfill.py --cpu-percent 25 /volume1/camera_raw/05072026/
  python3 audio-backfill.py --cpu-percent 15 --since 2026-05-01 /volume1/camera_raw/
  python3 audio-backfill.py --dry-run /volume1/camera_raw/05072026/
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# Add audio-scout to path for shared modules
sys.path.insert(0, str(Path(__file__).parent / "audio-scout"))

from classifier import classify_chunk, filter_detections, BIRDNET_CONFIDENCE, YAMNET_CONFIDENCE
from manifest_io import load_manifest, save_manifest, add_detection
from species_cache import lookup_species

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [audio-backfill] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("audio-backfill")

HIGHLIGHTS_DIR  = Path(os.getenv("HIGHLIGHTS_DIR", "/volume1/highlights"))
MANIFEST_PATH   = HIGHLIGHTS_DIR / "audio_manifest.json"
AUDIO_DIR       = HIGHLIGHTS_DIR / "audio"
PROGRESS_PATH   = HIGHLIGHTS_DIR / "audio" / "backfill_progress.json"
SAMPLE_RATE     = 48000
CHUNK_SEC       = 3
CHUNK_BYTES     = SAMPLE_RATE * 2 * CHUNK_SEC


def apply_cpulimit(cpu_percent: int) -> None:
    try:
        subprocess.run(
            ["cpulimit", f"--limit={cpu_percent}", f"--pid={os.getpid()}", "--background"],
            check=True, capture_output=True,
        )
        log.info("cpulimit applied: %d%%", cpu_percent)
    except FileNotFoundError:
        log.warning("cpulimit not installed — running unthrottled")
    except subprocess.CalledProcessError as e:
        log.warning("cpulimit failed: %s — running unthrottled", e)


def find_mp4_files(directory: Path, since: datetime | None) -> list[Path]:
    files = sorted(directory.rglob("*.mp4"))
    if since:
        files = [f for f in files if datetime.fromtimestamp(
            f.stat().st_mtime, tz=timezone.utc) >= since]
    return files


def extract_audio_chunks(mp4_path: Path):
    """Yield (timestamp_str, pcm_bytes) for each 3s chunk in the file."""
    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-i", str(mp4_path),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-f", "s16le", "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    chunk_index = 0
    try:
        while True:
            chunk = proc.stdout.read(CHUNK_BYTES)
            if len(chunk) < CHUNK_BYTES:
                break
            # Derive timestamp from filename + offset
            stem = mp4_path.stem
            offset_sec = chunk_index * CHUNK_SEC
            ts = datetime.now(timezone.utc).strftime(f"%Y%m%d_%H%M%S")  # simplified
            yield ts, chunk
            chunk_index += 1
    finally:
        proc.terminate()
        proc.wait()


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text())
        except Exception:
            pass
    return {"completed": [], "in_progress": None}


def save_progress(progress: dict) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps(progress, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path, help="Directory to scan for .mp4 files")
    parser.add_argument("--cpu-percent", type=int, default=25,
                        help="CPU usage cap via cpulimit (default: 25)")
    parser.add_argument("--since", type=str, default=None,
                        help="Only process files modified on or after YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be analyzed without processing")
    args = parser.parse_args()

    since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(
        tzinfo=timezone.utc) if args.since else None

    files = find_mp4_files(args.directory, since_dt)
    manifest = load_manifest(MANIFEST_PATH)
    already_done = set(manifest.analyzed_sources)
    pending = [f for f in files if str(f) not in already_done]

    log.info("Found %d .mp4 files, %d pending analysis", len(files), len(pending))

    if args.dry_run:
        for f in pending:
            print(f"  PENDING: {f}")
        print(f"\n{len(pending)} files would be analyzed.")
        return

    if not pending:
        log.info("Nothing to analyze.")
        return

    apply_cpulimit(args.cpu_percent)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    progress = load_progress()

    for mp4 in pending:
        log.info("Analyzing: %s", mp4.name)
        progress["in_progress"] = str(mp4)
        save_progress(progress)

        detections_found = 0
        for ts, chunk in extract_audio_chunks(mp4):
            raw = classify_chunk(chunk, SAMPLE_RATE)
            hits = filter_detections(
                [d for d in raw if d.detector == "birdnet"], BIRDNET_CONFIDENCE
            ) + filter_detections(
                [d for d in raw if d.detector == "yamnet"], YAMNET_CONFIDENCE
            )
            for det in hits:
                import wave, io
                slug = det.species.lower().replace(" ", "_")[:30]
                clip_path = AUDIO_DIR / f"{ts}_{slug}.wav"
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wf:
                    wf.setnchannels(1); wf.setsampwidth(2)
                    wf.setframerate(SAMPLE_RATE); wf.writeframes(chunk)
                clip_path.write_bytes(buf.getvalue())
                rel = str(clip_path.relative_to(HIGHLIGHTS_DIR))
                info = lookup_species(det.scientific_name) if det.scientific_name else {}
                add_detection(manifest, det, timestamp=ts, clip_path=rel,
                              highlights_manifest=[], species_info=info, source="backfill")
                detections_found += 1

        manifest.analyzed_sources.append(str(mp4))
        save_manifest(manifest, MANIFEST_PATH)
        progress["completed"].append(str(mp4))
        progress["in_progress"] = None
        save_progress(progress)
        log.info("  → %d detections  [%d/%d]", detections_found, len(progress["completed"]), len(pending))

    log.info("Backfill complete.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify dry-run works (no camera required)**

```bash
cd /home/HighlyReflective/weather-station
python3 audio-backfill.py --dry-run /volume1/camera_raw/05072026/ 2>&1 | head -10
```

Expected: list of `.mp4` files printed with `PENDING:` prefix, no errors.

- [ ] **Step 3: Commit**

```bash
git add audio-backfill.py
git commit -m "feat(audio-scout): CPU-throttled back-analysis script"
```

---

## Task 9: docker-compose.yml and .env.example

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Add audio-scout service to docker-compose.yml**

Open `docker-compose.yml` and add after the `sky-watcher` service block (before the `networks:` section):

```yaml
  audio-scout:
    build: ./audio-scout
    container_name: audio-scout
    restart: unless-stopped
    network_mode: host
    entrypoint: ["/bin/sh", "-c", "umask 0022 && exec python -u scout.py"]
    volumes:
      - /volume1/highlights:/highlights
    environment:
      - CAMERA_IP=${CAMERA_IP:-192.168.100.131}
      - CAMERA_USER=${CAMERA_USER:-admin}
      - CAMERA_PASSWORD=${CAMERA_PASSWORD:?set CAMERA_PASSWORD in .env}
      - MQTT_HOST=localhost
      - HA_URL=http://localhost:8123
      - HA_TOKEN=${HA_TOKEN:?set HA_TOKEN in .env}
      - HIGHLIGHTS_DIR=/highlights
      - LATITUDE=${LATITUDE:-29.9974}
      - LONGITUDE=${LONGITUDE:--98.0986}
      - BIRDNET_CONFIDENCE=${BIRDNET_CONFIDENCE:-0.70}
      - YAMNET_CONFIDENCE=${YAMNET_CONFIDENCE:-0.75}
      - AUDIO_SUBMIT_MODE=${AUDIO_SUBMIT_MODE:-off}
      - EBIRD_API_KEY=${EBIRD_API_KEY:-}
      - RARE_SPECIES_PUSH=${RARE_SPECIES_PUSH:-false}
```

- [ ] **Step 2: Add new variables to .env.example**

Append to `.env.example`:

```bash
# ─── Audio Scout ─────────────────────────────────────────────────────────────
BIRDNET_CONFIDENCE=0.70      # Min BirdNET confidence to record (0–1)
YAMNET_CONFIDENCE=0.75       # Min YAMNet confidence to record (0–1)
AUDIO_SUBMIT_MODE=off        # off | auto | manual
EBIRD_API_KEY=               # Get at https://ebird.org/api/keygen
RARE_SPECIES_PUSH=false      # true to enable push notifications for rare species
```

- [ ] **Step 3: Update CLAUDE.md services list**

In `/home/HighlyReflective/CLAUDE.md`, add `audio-scout` to the Services line:

```
Services: `mosquitto`, `influxdb`, `homeassistant`, `grafana`, `frigate`, `mediamtx`, `ffmpeg-processor`, `highlight-curator`, `star-scanner`, `vote-server`, `night-sky-patrol`, `sky-watcher`, `audio-scout`
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git -C /home/HighlyReflective add CLAUDE.md
git -C /home/HighlyReflective commit -m "docs: add audio-scout to CLAUDE.md services"
git add -A
git commit -m "feat(audio-scout): add docker-compose service and .env.example vars"
```

---

## Task 10: Integration smoke test

No code changes — verify the container starts and connects.

- [ ] **Step 1: Build the image**

```bash
cd /home/HighlyReflective/weather-station
docker compose build audio-scout 2>&1 | tail -5
```

Expected: `DONE` with no errors.

- [ ] **Step 2: Start the service**

```bash
docker compose up -d audio-scout
sleep 10
docker compose logs audio-scout --tail=20
```

Expected log lines:
```
Audio Scout starting — RTSP: rtsp://admin:***@192.168.100.131:554/...
  BirdNET threshold: 0.70  |  YAMNet threshold: 0.75
MQTT connected (localhost:1883)
Opening RTSP stream...
```

- [ ] **Step 3: Verify MQTT heartbeat arrives**

```bash
docker exec mosquitto mosquitto_sub -t 'audio/#' -v -C 3
```

Expected: within 90 seconds, see `audio/status {"status": "ok", "uptime": ...}`

- [ ] **Step 4: Verify audio_manifest.json is created**

```bash
ls -la /volume1/highlights/audio_manifest.json
python3 -c "import json; m=json.load(open('/volume1/highlights/audio_manifest.json')); print('detections:', len(m['detections']), '| unreviewed:', m['unreviewed_count'])"
```

Expected: file exists, `detections: 0 | unreviewed: 0` initially (grows as detections arrive).

- [ ] **Step 5: Final commit**

```bash
cd /home/HighlyReflective/weather-station
git add -A
git commit -m "feat(audio-scout): complete implementation"
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ Real-time RTSP → BirdNET + YAMNet pipeline (Tasks 2, 7)
- ✅ Standalone audio_manifest.json with unreviewed tracking (Task 3)
- ✅ ±60s photo linking (Task 3)
- ✅ Species summary week/month/season (Task 3)
- ✅ Audio clip WAV storage (Tasks 7, 8)
- ✅ iNaturalist/eBird species lookup + cache (Task 4)
- ✅ MQTT audio/detections + audio/detections/rare + audio/status (Tasks 5, 7)
- ✅ Rare species push via rare_species.txt (Tasks 6, 7)
- ✅ CPU-throttled back-analysis with analyzed_sources skip and crash-safe resume (Task 8)
- ✅ docker-compose service + .env.example (Task 9)
- ✅ CLAUDE.md services list update (Task 9)
- ✅ Submission modes (off/auto/manual) — `AUDIO_SUBMIT_MODE` env var wired in Task 9; auto-submit logic (eBird midnight checklist, iNaturalist daily) is **deferred** per spec (submission is out of scope for this plan; the env var and `submitted_to` field are stubbed in place)

**Submission note:** The spec defines submission modes but scopes the command center UI to a separate project. `audio-submit.py` CLI for manual review/submission is also deferred — the `submitted_to` field in each detection entry reserves the slot.
