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
