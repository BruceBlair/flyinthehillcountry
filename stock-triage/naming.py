"""Derives label/category from source path; builds output path and filename."""

from datetime import datetime
from pathlib import Path

from PIL import Image, ExifTags

_CATEGORY_MAP = {
    "wildlife":    "wildlife",
    "weather":     "weather",
    "golden_hour": "golden-hour",
    "golden-hour": "golden-hour",
    "panoramas":   "panoramas",
    "stars":       "stars",
}

_LABEL_SINGLETON = {
    "panoramas": "panorama",
    "stars":     "stars",
}

_KNOWN_LABELS = {
    "bird", "deer", "fox", "bear", "rabbit", "squirrel",
    "raccoon", "turkey", "dog", "cat", "cow", "horse",
    "storm", "severe_storm", "lightning",
    "sunrise", "sunset",
}


def derive_label_and_category(source: Path, source_root: Path) -> tuple[str, str]:
    """Return (label, category) derived from source path relative to source_root."""
    try:
        parts = source.relative_to(source_root).parts
    except ValueError:
        parts = ()

    if parts:
        top = parts[0].lower()

        # panorama_YYYYMMDD_HHMMSS capture directories → landscape frames
        if top.startswith("panorama_"):
            return "landscape", "landscapes"

        category = _CATEGORY_MAP.get(top)
        if category:
            if top in _LABEL_SINGLETON:
                return _LABEL_SINGLETON[top], category
            if len(parts) >= 2 and not parts[1].lower().endswith(".jpg"):
                return parts[1].lower(), category
            return _LABEL_SINGLETON.get(top, top), category

    # Frigate media or unknown root — try to extract label from filename
    stem = source.stem.lower()
    for label in _KNOWN_LABELS:
        if label in stem:
            category = (
                "weather" if label in {"storm", "severe_storm", "lightning"} else
                "golden-hour" if label in {"sunrise", "sunset"} else
                "wildlife"
            )
            return label, category

    return "general", "wildlife"


def timestamp_from_file(source: Path) -> datetime:
    """Return EXIF DateTimeOriginal if present, else file mtime."""
    try:
        with Image.open(source) as img:
            exif = img._getexif()
            if exif:
                for tag_id, value in exif.items():
                    if ExifTags.TAGS.get(tag_id) == "DateTimeOriginal":
                        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return datetime.fromtimestamp(source.stat().st_mtime)


def build_output_path(
    source: Path,
    source_root: Path,
    stock_ready_dir: Path,
    location: str,
    status: str,
    ts: datetime | None = None,
) -> Path:
    """
    Build the full output path:
    {stock_ready_dir}/{location}/{category}/{label}/gtn_{location}_{YYYYMMDD}_{HHMMSS}_{label}_{status}.jpg

    status must be "clean" or "crop".
    Pass ts to inject a fixed datetime (useful in tests).
    """
    label, category = derive_label_and_category(source, source_root)
    if ts is None:
        ts = timestamp_from_file(source)
    date_str = ts.strftime("%Y%m%d")
    time_str = ts.strftime("%H%M%S")
    filename = f"gtn_{location}_{date_str}_{time_str}_{label}_{status}.jpg"
    return stock_ready_dir / location / category / label / filename
