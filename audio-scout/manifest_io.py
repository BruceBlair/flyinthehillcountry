"""Atomic read/write for audio_manifest.json."""
import json
import os
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
    # Atomic write: write to .tmp then rename
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
