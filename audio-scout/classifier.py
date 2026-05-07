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
    import csv, urllib.request

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
