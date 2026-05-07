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
