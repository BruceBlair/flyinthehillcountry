# Stock Triage Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `stock-triage` Docker service that scans the full GTN image catalog for Reolink camera overlays, crops them using OCR-guided bounding boxes, and exports clean stock-ready images to `/volume1/stock_ready/` with a location-prefixed naming convention; then watches for new highlights automatically.

**Architecture:** Six focused Python modules (naming, manifest, ocr, pipeline, report, triage) in a new `stock-triage/` directory. `TRIAGE_MODE=batch` does the one-time full-catalog scan and exits; `TRIAGE_MODE=daemon` (default) watches `/highlights` for new images using `watchdog` filesystem events.

**Tech Stack:** Python 3.11-slim, pytesseract + tesseract-ocr, Pillow, watchdog, pytest

---

## File Map

| File | Responsibility |
|------|---------------|
| `stock-triage/Dockerfile` | Python 3.11-slim + tesseract-ocr + fonts-liberation |
| `stock-triage/requirements.txt` | pytesseract, Pillow, watchdog, pytest |
| `stock-triage/naming.py` | Derives label/category from source path; builds output path + filename |
| `stock-triage/manifest.py` | Reads/writes `stock_manifest.json`; tracks processed images |
| `stock-triage/ocr.py` | Crops top/bottom bands; runs Tesseract; returns pixels to crop |
| `stock-triage/pipeline.py` | Orchestrates one image: resolution filter → OCR → crop/copy → save |
| `stock-triage/report.py` | Generates `triage_summary.html` from manifest |
| `stock-triage/triage.py` | Entry point: reads env vars, dispatches batch or daemon mode |
| `stock-triage/tests/__init__.py` | Empty — marks tests/ as a package |
| `stock-triage/tests/test_naming.py` | Unit tests for naming.py |
| `stock-triage/tests/test_manifest.py` | Unit tests for manifest.py |
| `stock-triage/tests/test_ocr.py` | Unit tests for ocr.py (Tesseract required — run inside Docker) |
| `stock-triage/tests/test_pipeline.py` | Integration tests for pipeline.py |
| `stock-triage/tests/test_report.py` | Unit tests for report.py |
| `docker-compose.yml` | Add stock-triage service definition |
| `.env.example` | Add LOCATION_LABEL, TRIAGE_MODE, MIN_RESOLUTION_MP, OCR_TOP_PCT, OCR_BOTTOM_PCT |

---

## Test Runner Setup

All tests run inside the Docker container so Tesseract is always available. Use a volume mount to avoid rebuilding the image on every code change:

```bash
# From weather-station/ directory. Build once in Task 1, then use this for all tasks:
docker compose run --rm \
  -v "$(pwd)/stock-triage:/app" \
  stock-triage python -m pytest tests/test_FILENAME.py -v
```

---

## Task 1: Scaffold — Dockerfile, requirements, empty module stubs

**Files:**
- Create: `stock-triage/Dockerfile`
- Create: `stock-triage/requirements.txt`
- Create: `stock-triage/naming.py`
- Create: `stock-triage/manifest.py`
- Create: `stock-triage/ocr.py`
- Create: `stock-triage/pipeline.py`
- Create: `stock-triage/report.py`
- Create: `stock-triage/triage.py`
- Create: `stock-triage/tests/__init__.py`

- [ ] **Step 1: Create `stock-triage/Dockerfile`**

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    fonts-liberation \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-u", "triage.py"]
```

- [ ] **Step 2: Create `stock-triage/requirements.txt`**

```
pytesseract==0.3.13
Pillow==10.4.0
watchdog==4.0.1
pytest==8.2.0
```

- [ ] **Step 3: Create empty module stubs**

Create each of these files with exactly this content (just the module docstring so imports work):

`stock-triage/naming.py`:
```python
"""Derives label/category from source path; builds output path and filename."""
```

`stock-triage/manifest.py`:
```python
"""Reads/writes stock_manifest.json; tracks processed images."""
```

`stock-triage/ocr.py`:
```python
"""OCR band detection: returns (crop_top_px, crop_bottom_px) for a PIL image."""
```

`stock-triage/pipeline.py`:
```python
"""Orchestrates one image through the full triage pipeline."""
```

`stock-triage/report.py`:
```python
"""Generates triage_summary.html from the manifest."""
```

`stock-triage/triage.py`:
```python
"""Entry point: reads env vars, dispatches batch or daemon mode."""
```

`stock-triage/tests/__init__.py`:
```python
```

- [ ] **Step 4: Build the Docker image**

```bash
cd weather-station
docker compose build stock-triage
```

Expected: build completes with no errors. The final lines should look like:
```
 => exporting to image
 => => writing image sha256:...
 => => naming to docker.io/library/weather-station-stock-triage
```

- [ ] **Step 5: Verify Tesseract is available inside the container**

```bash
docker compose run --rm stock-triage tesseract --version
```

Expected output starts with:
```
tesseract 5.x.x
```

- [ ] **Step 6: Commit**

```bash
cd weather-station
git add stock-triage/
git commit -m "feat(stock-triage): scaffold Dockerfile, requirements, empty stubs"
```

---

## Task 2: Naming Module

**Files:**
- Create: `stock-triage/naming.py` (replace stub)
- Create: `stock-triage/tests/test_naming.py`

`★ Insight ─────────────────────────────────────`
`derive_label_and_category` maps source path components to (label, category) tuples. The tricky cases are `panoramas/` (label="panorama", singular) and `golden_hour/` (category="golden-hour", hyphenated). Getting these right here means every downstream file path is correct.
`─────────────────────────────────────────────────`

- [ ] **Step 1: Write the failing tests**

Create `stock-triage/tests/test_naming.py`:

```python
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from naming import build_output_path, derive_label_and_category

HIGHLIGHTS = Path("/highlights")
LOCATION = "wimberley"


def test_wildlife_fox():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "wildlife" / "fox" / "img.jpg", HIGHLIGHTS
    )
    assert label == "fox"
    assert cat == "wildlife"


def test_wildlife_deer():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "wildlife" / "deer" / "img.jpg", HIGHLIGHTS
    )
    assert label == "deer"
    assert cat == "wildlife"


def test_weather_storm():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "weather" / "storm" / "img.jpg", HIGHLIGHTS
    )
    assert label == "storm"
    assert cat == "weather"


def test_weather_lightning():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "weather" / "lightning" / "img.jpg", HIGHLIGHTS
    )
    assert label == "lightning"
    assert cat == "weather"


def test_golden_hour_sunrise():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "golden_hour" / "sunrise" / "img.jpg", HIGHLIGHTS
    )
    assert label == "sunrise"
    assert cat == "golden-hour"


def test_golden_hour_sunset():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "golden_hour" / "sunset" / "img.jpg", HIGHLIGHTS
    )
    assert label == "sunset"
    assert cat == "golden-hour"


def test_panoramas_label_is_singular():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "panoramas" / "img.jpg", HIGHLIGHTS
    )
    assert label == "panorama"
    assert cat == "panoramas"


def test_stars():
    label, cat = derive_label_and_category(
        HIGHLIGHTS / "stars" / "img.jpg", HIGHLIGHTS
    )
    assert label == "stars"
    assert cat == "stars"


def test_unknown_source_falls_back_to_general(tmp_path):
    source = tmp_path / "frigate-media" / "clips" / "trackmix_wide-abc123.jpg"
    label, cat = derive_label_and_category(source, tmp_path / "frigate-media")
    assert isinstance(label, str) and len(label) > 0
    assert isinstance(cat, str) and len(cat) > 0


def test_output_path_structure(tmp_path):
    source = HIGHLIGHTS / "wildlife" / "fox" / "img.jpg"
    fixed = datetime(2026, 4, 24, 19, 32, 15)
    with patch("naming.timestamp_from_file", return_value=fixed):
        out = build_output_path(source, HIGHLIGHTS, tmp_path, LOCATION, "clean")
    assert out.parent == tmp_path / LOCATION / "wildlife" / "fox"
    assert out.name == "gtn_wimberley_20260424_193215_fox_clean.jpg"


def test_output_path_crop_suffix(tmp_path):
    source = HIGHLIGHTS / "weather" / "storm" / "img.jpg"
    fixed = datetime(2026, 4, 24, 6, 0, 0)
    with patch("naming.timestamp_from_file", return_value=fixed):
        out = build_output_path(source, HIGHLIGHTS, tmp_path, LOCATION, "crop")
    assert out.name == "gtn_wimberley_20260424_060000_storm_crop.jpg"


def test_output_path_panorama(tmp_path):
    source = HIGHLIGHTS / "panoramas" / "img.jpg"
    fixed = datetime(2026, 4, 24, 20, 0, 0)
    with patch("naming.timestamp_from_file", return_value=fixed):
        out = build_output_path(source, HIGHLIGHTS, tmp_path, LOCATION, "clean")
    assert out.parent == tmp_path / LOCATION / "panoramas" / "panorama"
    assert "panorama" in out.name
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/test_naming.py -v
```

Expected: multiple `ImportError` or `AttributeError` failures — `naming` module has no functions yet.

- [ ] **Step 3: Implement `stock-triage/naming.py`**

```python
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
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/test_naming.py -v
```

Expected:
```
tests/test_naming.py::test_wildlife_fox PASSED
tests/test_naming.py::test_wildlife_deer PASSED
tests/test_naming.py::test_weather_storm PASSED
tests/test_naming.py::test_weather_lightning PASSED
tests/test_naming.py::test_golden_hour_sunrise PASSED
tests/test_naming.py::test_golden_hour_sunset PASSED
tests/test_naming.py::test_panoramas_label_is_singular PASSED
tests/test_naming.py::test_stars PASSED
tests/test_naming.py::test_unknown_source_falls_back_to_general PASSED
tests/test_naming.py::test_output_path_structure PASSED
tests/test_naming.py::test_output_path_crop_suffix PASSED
tests/test_naming.py::test_output_path_panorama PASSED
12 passed
```

- [ ] **Step 5: Commit**

```bash
cd weather-station
git add stock-triage/naming.py stock-triage/tests/test_naming.py
git commit -m "feat(stock-triage): naming module — label/category derivation + output path builder"
```

---

## Task 3: Manifest Module

**Files:**
- Create: `stock-triage/manifest.py` (replace stub)
- Create: `stock-triage/tests/test_manifest.py`

- [ ] **Step 1: Write the failing tests**

Create `stock-triage/tests/test_manifest.py`:

```python
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from manifest import add_entry, is_processed, load, save


def test_load_missing_dir_returns_empty(tmp_path):
    m = load(tmp_path / "nonexistent")
    assert m["images"] == []
    assert "generated" in m


def test_load_missing_file_returns_empty(tmp_path):
    m = load(tmp_path)
    assert m["images"] == []


def test_is_processed_false_for_new_source(tmp_path):
    m = load(tmp_path)
    assert not is_processed(m, Path("/highlights/wildlife/fox/img.jpg"))


def test_add_entry_then_is_processed(tmp_path):
    m = load(tmp_path)
    source = Path("/highlights/wildlife/fox/img.jpg")
    add_entry(m, {
        "source": str(source),
        "output": "/stock_ready/wimberley/wildlife/fox/gtn_wimberley_20260424_193215_fox_clean.jpg",
        "status": "clean",
        "reason": "no overlay detected",
        "crop_top_px": 0,
        "crop_bottom_px": 0,
        "resolution_mp": 8.3,
        "processed_at": "2026-04-25T12:01:23",
    })
    assert is_processed(m, source)


def test_add_entry_stores_all_fields(tmp_path):
    m = load(tmp_path)
    entry = {
        "source": "/highlights/wildlife/fox/img.jpg",
        "output": "/stock_ready/wimberley/wildlife/fox/gtn_wimberley_20260424_193215_fox_clean.jpg",
        "status": "clean",
        "reason": "no overlay detected",
        "crop_top_px": 0,
        "crop_bottom_px": 0,
        "resolution_mp": 8.3,
        "processed_at": "2026-04-25T12:01:23",
    }
    add_entry(m, entry)
    stored = m["images"][0]
    assert stored["status"] == "clean"
    assert stored["resolution_mp"] == 8.3
    assert stored["crop_top_px"] == 0
    assert stored["reason"] == "no overlay detected"


def test_save_and_reload_roundtrip(tmp_path):
    m = load(tmp_path)
    add_entry(m, {
        "source": "/highlights/test.jpg",
        "output": "/stock_ready/test.jpg",
        "status": "clean",
        "reason": "no overlay",
        "crop_top_px": 0,
        "crop_bottom_px": 0,
        "resolution_mp": 5.0,
        "processed_at": "2026-04-25T00:00:00",
    })
    save(m, tmp_path)

    reloaded = load(tmp_path)
    assert len(reloaded["images"]) == 1
    assert reloaded["images"][0]["source"] == "/highlights/test.jpg"


def test_add_entry_updates_existing_not_duplicates(tmp_path):
    m = load(tmp_path)
    source = "/highlights/test.jpg"
    add_entry(m, {"source": source, "output": None, "status": "error",
                  "reason": "fail", "crop_top_px": 0, "crop_bottom_px": 0,
                  "resolution_mp": 5.0, "processed_at": "2026-04-25T00:00:00"})
    add_entry(m, {"source": source, "output": "/stock_ready/test.jpg",
                  "status": "clean", "reason": "ok", "crop_top_px": 0,
                  "crop_bottom_px": 0, "resolution_mp": 5.0,
                  "processed_at": "2026-04-25T00:01:00"})
    assert len(m["images"]) == 1
    assert m["images"][0]["status"] == "clean"


def test_save_creates_directory(tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    m = load(nested)
    save(m, nested)
    assert (nested / "stock_manifest.json").exists()
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/test_manifest.py -v
```

Expected: all tests fail with `ImportError` or `AttributeError`.

- [ ] **Step 3: Implement `stock-triage/manifest.py`**

```python
"""Reads/writes stock_manifest.json; tracks processed images."""

import json
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_FILENAME = "stock_manifest.json"


def _path(stock_ready_dir: Path) -> Path:
    return stock_ready_dir / MANIFEST_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def load(stock_ready_dir: Path) -> dict:
    """Load manifest from stock_ready_dir, or return an empty structure."""
    p = _path(stock_ready_dir)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {"generated": _now_iso(), "images": []}


def save(manifest: dict, stock_ready_dir: Path) -> None:
    """Write manifest to stock_ready_dir/stock_manifest.json."""
    manifest["generated"] = _now_iso()
    stock_ready_dir.mkdir(parents=True, exist_ok=True)
    with open(_path(stock_ready_dir), "w") as f:
        json.dump(manifest, f, indent=2)


def is_processed(manifest: dict, source: Path) -> bool:
    """Return True if source path already has an entry."""
    source_str = str(source)
    return any(e["source"] == source_str for e in manifest["images"])


def add_entry(manifest: dict, entry: dict) -> None:
    """Add entry, or replace existing entry with the same source path."""
    source_str = entry["source"]
    for i, existing in enumerate(manifest["images"]):
        if existing["source"] == source_str:
            manifest["images"][i] = entry
            return
    manifest["images"].append(entry)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/test_manifest.py -v
```

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
cd weather-station
git add stock-triage/manifest.py stock-triage/tests/test_manifest.py
git commit -m "feat(stock-triage): manifest module — JSON read/write, processed-image tracking"
```

---

## Task 4: OCR Module

**Files:**
- Create: `stock-triage/ocr.py` (replace stub)
- Create: `stock-triage/tests/test_ocr.py`

`★ Insight ─────────────────────────────────────`
OCR is run only on the top 15% and bottom 10% bands — not the full image. A Reolink timestamp like `2026/04/25 19:32:15` always contains a date pattern (`\d{4}[/\-]\d{2}`), which is the detection signal. Once a date is found in a band, we find the bounding box of *all* text in that band (including the camera name line) to determine the full crop amount.
`─────────────────────────────────────────────────`

- [ ] **Step 1: Write the failing tests**

Create `stock-triage/tests/test_ocr.py`:

```python
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent))
from ocr import detect_overlay_bounds

FONT = "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"


def _clean_image(width=3840, height=2160):
    return Image.new("RGB", (width, height), color=(80, 130, 180))


def _image_with_top_overlay(width=3840, height=2160):
    img = Image.new("RGB", (width, height), color=(80, 130, 180))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 36)
    draw.rectangle([(0, 0), (width, 90)], fill=(0, 0, 0))
    draw.text((20, 8),  "2026/04/25 19:32:15", fill=(255, 255, 255), font=font)
    draw.text((20, 52), "TrackMix Wide  CH1",  fill=(255, 255, 255), font=font)
    return img


def _image_with_both_overlays(width=3840, height=2160):
    img = _image_with_top_overlay(width, height)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 36)
    draw.rectangle([(0, height - 60), (width, height)], fill=(0, 0, 0))
    draw.text((20, height - 52), "2026/04/25  REOLINK", fill=(255, 255, 255), font=font)
    return img


def test_clean_image_returns_zero_zero():
    top, bot = detect_overlay_bounds(_clean_image())
    assert top == 0
    assert bot == 0


def test_top_overlay_detected():
    top, bot = detect_overlay_bounds(_image_with_top_overlay())
    assert top > 0, "expected top crop > 0 for image with timestamp overlay"
    assert bot == 0


def test_both_overlays_detected():
    top, bot = detect_overlay_bounds(_image_with_both_overlays())
    assert top > 0
    assert bot > 0


def test_top_crop_does_not_exceed_band():
    top, _ = detect_overlay_bounds(_image_with_top_overlay(3840, 2160), top_pct=0.15)
    assert top <= int(2160 * 0.15) + 10


def test_bottom_crop_does_not_exceed_band():
    _, bot = detect_overlay_bounds(_image_with_both_overlays(3840, 2160), bottom_pct=0.10)
    assert bot <= int(2160 * 0.10) + 10


def test_small_top_pct_misses_overlay_below_band():
    # overlay is in top 90px; if top_pct scans only top 2% (~43px), it should miss it
    img = _image_with_top_overlay(3840, 2160)
    top, _ = detect_overlay_bounds(img, top_pct=0.02)
    assert top == 0
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/test_ocr.py -v
```

Expected: all fail with `ImportError` — `detect_overlay_bounds` not defined yet.

- [ ] **Step 3: Implement `stock-triage/ocr.py`**

```python
"""OCR band detection: returns (crop_top_px, crop_bottom_px) for a PIL image."""

import re

import pytesseract
from PIL import Image

_DATE_RE = re.compile(r"\d{4}[/\-]\d{2}")


def detect_overlay_bounds(
    image: Image.Image,
    top_pct: float = 0.15,
    bottom_pct: float = 0.10,
) -> tuple[int, int]:
    """
    Scan top and bottom bands for Reolink camera overlay text.

    Returns (crop_top_px, crop_bottom_px):
      crop_top_px    — rows to remove from the top of the image (0 if none).
      crop_bottom_px — rows to remove from the bottom of the image (0 if none).
    """
    w, h = image.size
    top_band_h = int(h * top_pct)
    bot_band_h = int(h * bottom_pct)

    top_band = image.crop((0, 0, w, top_band_h))
    bot_band = image.crop((0, h - bot_band_h, w, h))

    crop_top = _band_crop_px(top_band, band_height=top_band_h, from_top=True)
    crop_bot = _band_crop_px(bot_band, band_height=bot_band_h, from_top=False)

    return crop_top, crop_bot


def _band_crop_px(band: Image.Image, band_height: int, from_top: bool) -> int:
    """
    Run Tesseract on band. If a date pattern is found, return pixels to crop.
    from_top=True  → return rows to remove from image top (= bottom of lowest text + 2px).
    from_top=False → return rows to remove from image bottom (= band_height - top of highest text + 2px).
    """
    data = pytesseract.image_to_data(band, output_type=pytesseract.Output.DICT)

    words = [
        (data["text"][i], data["top"][i], data["height"][i])
        for i in range(len(data["text"]))
        if data["text"][i].strip() and int(data["conf"][i]) > 0
    ]

    if not words:
        return 0

    full_text = " ".join(w for w, _, _ in words)
    if not _DATE_RE.search(full_text):
        return 0

    if from_top:
        lowest_bottom = max(top + h for _, top, h in words)
        return min(lowest_bottom + 2, band_height)
    else:
        highest_top = min(top for _, top, _ in words)
        return min(band_height - highest_top + 2, band_height)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/test_ocr.py -v
```

Expected: `6 passed`. (The OCR tests depend on Tesseract reading synthetic PIL-drawn text — they pass reliably with LiberationMono at size 36 on a black bar.)

- [ ] **Step 5: Commit**

```bash
cd weather-station
git add stock-triage/ocr.py stock-triage/tests/test_ocr.py
git commit -m "feat(stock-triage): OCR module — band detection, dynamic crop bounds"
```

---

## Task 5: Pipeline Module

**Files:**
- Create: `stock-triage/pipeline.py` (replace stub)
- Create: `stock-triage/tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `stock-triage/tests/test_pipeline.py`:

```python
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline import process_image

FONT = "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"


def _save_plain_jpeg(path: Path, width: int, height: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), color=(80, 130, 180)).save(path, "JPEG")
    return path


def _save_overlay_jpeg(path: Path, width: int = 3840, height: int = 2160) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), color=(80, 130, 180))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 36)
    draw.rectangle([(0, 0), (width, 90)], fill=(0, 0, 0))
    draw.text((20, 8),  "2026/04/25 19:32:15", fill=(255, 255, 255), font=font)
    draw.text((20, 52), "TrackMix Wide  CH1",  fill=(255, 255, 255), font=font)
    img.save(path, "JPEG")
    return path


def test_rejects_below_min_resolution(tmp_path):
    src_dir = tmp_path / "highlights" / "wildlife" / "fox"
    source = _save_plain_jpeg(src_dir / "small.jpg", width=800, height=600)
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley", min_resolution_mp=4.0)
    assert entry["status"] == "rejected_resolution"
    assert entry["output"] is None


def test_clean_image_copies_with_clean_status(tmp_path):
    src_dir = tmp_path / "highlights" / "wildlife" / "fox"
    source = _save_plain_jpeg(src_dir / "clean.jpg", width=3840, height=2160)
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley")
    assert entry["status"] == "clean"
    assert entry["output"] is not None
    assert Path(entry["output"]).exists()


def test_overlay_image_gets_cropped_status(tmp_path):
    src_dir = tmp_path / "highlights" / "wildlife" / "fox"
    source = _save_overlay_jpeg(src_dir / "overlay.jpg")
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley")
    assert entry["status"] == "cropped"
    assert entry["crop_top_px"] > 0
    assert entry["output"] is not None


def test_cropped_output_is_shorter_than_original(tmp_path):
    src_dir = tmp_path / "highlights" / "wildlife" / "fox"
    source = _save_overlay_jpeg(src_dir / "overlay.jpg")
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley")
    out_img = Image.open(entry["output"])
    assert out_img.size[1] < 2160, "cropped image height should be less than original 2160"


def test_output_path_follows_naming_convention(tmp_path):
    src_dir = tmp_path / "highlights" / "weather" / "storm"
    source = _save_plain_jpeg(src_dir / "storm.jpg", width=3840, height=2160)
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley")
    out = Path(entry["output"])
    assert out.parent.parts[-3] == "wimberley"
    assert out.parent.parts[-2] == "weather"
    assert out.parent.parts[-1] == "storm"
    assert out.name.startswith("gtn_wimberley_")
    assert out.name.endswith("_storm_clean.jpg")


def test_resolution_mp_recorded_in_entry(tmp_path):
    src_dir = tmp_path / "highlights" / "wildlife" / "fox"
    source = _save_plain_jpeg(src_dir / "hires.jpg", width=3840, height=2160)
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley")
    expected_mp = round((3840 * 2160) / 1_000_000, 2)
    assert abs(entry["resolution_mp"] - expected_mp) < 0.1


def test_entry_contains_all_required_fields(tmp_path):
    src_dir = tmp_path / "highlights" / "wildlife" / "fox"
    source = _save_plain_jpeg(src_dir / "img.jpg", width=3840, height=2160)
    entry = process_image(source, tmp_path / "highlights", tmp_path / "out", "wimberley")
    for field in ("source", "output", "status", "reason", "crop_top_px",
                  "crop_bottom_px", "resolution_mp", "processed_at"):
        assert field in entry, f"missing field: {field}"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/test_pipeline.py -v
```

Expected: all fail with `ImportError` — `process_image` not defined yet.

- [ ] **Step 3: Implement `stock-triage/pipeline.py`**

```python
"""Orchestrates one image through the full triage pipeline."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from naming import build_output_path
from ocr import detect_overlay_bounds

log = logging.getLogger("pipeline")

JPEG_QUALITY = 95


def process_image(
    source: Path,
    source_root: Path,
    stock_ready_dir: Path,
    location: str,
    min_resolution_mp: float = 4.0,
    ocr_top_pct: float = 0.15,
    ocr_bottom_pct: float = 0.10,
) -> dict:
    """
    Run the full pipeline for one image. Returns a manifest entry dict.
    Does NOT write to the manifest — caller does that.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    with Image.open(source) as img:
        w, h = img.size
        mp = round((w * h) / 1_000_000, 2)

        if mp < min_resolution_mp:
            return {
                "source": str(source),
                "output": None,
                "status": "rejected_resolution",
                "reason": f"{mp:.1f}MP below minimum {min_resolution_mp}MP",
                "crop_top_px": 0,
                "crop_bottom_px": 0,
                "resolution_mp": mp,
                "processed_at": now,
            }

        crop_top, crop_bot = detect_overlay_bounds(img, ocr_top_pct, ocr_bottom_pct)
        has_overlay = crop_top > 0 or crop_bot > 0
        file_status = "crop" if has_overlay else "clean"
        manifest_status = "cropped" if has_overlay else "clean"

        output = build_output_path(source, source_root, stock_ready_dir, location, file_status)
        output.parent.mkdir(parents=True, exist_ok=True)

        exif = img.info.get("exif", b"")

        if has_overlay:
            bottom_edge = h - crop_bot if crop_bot > 0 else h
            cropped = img.crop((0, crop_top, w, bottom_edge))
            cropped.save(output, "JPEG", quality=JPEG_QUALITY, exif=exif)
        else:
            img.save(output, "JPEG", quality=JPEG_QUALITY, exif=exif)

    return {
        "source": str(source),
        "output": str(output),
        "status": manifest_status,
        "reason": (
            f"overlay detected top={crop_top}px bottom={crop_bot}px"
            if has_overlay else "no overlay detected"
        ),
        "crop_top_px": crop_top,
        "crop_bottom_px": crop_bot,
        "resolution_mp": mp,
        "processed_at": now,
    }
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/test_pipeline.py -v
```

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
cd weather-station
git add stock-triage/pipeline.py stock-triage/tests/test_pipeline.py
git commit -m "feat(stock-triage): pipeline module — resolution filter, OCR crop, JPEG export"
```

---

## Task 6: Report Module

**Files:**
- Create: `stock-triage/report.py` (replace stub)
- Create: `stock-triage/tests/test_report.py`

- [ ] **Step 1: Write the failing tests**

Create `stock-triage/tests/test_report.py`:

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from report import generate


def _make_manifest(images):
    return {"generated": "2026-04-25T12:00:00", "images": images}


def test_generate_creates_html_file(tmp_path):
    manifest = _make_manifest([])
    generate(manifest, tmp_path)
    assert (tmp_path / "triage_summary.html").exists()


def test_html_contains_total_count(tmp_path):
    manifest = _make_manifest([
        {"source": "/a.jpg", "output": "/b.jpg", "status": "clean",
         "reason": "ok", "crop_top_px": 0, "crop_bottom_px": 0,
         "resolution_mp": 8.3, "processed_at": "2026-04-25T12:00:00"},
        {"source": "/c.jpg", "output": None, "status": "rejected_resolution",
         "reason": "2.0MP", "crop_top_px": 0, "crop_bottom_px": 0,
         "resolution_mp": 2.0, "processed_at": "2026-04-25T12:01:00"},
    ])
    generate(manifest, tmp_path)
    html = (tmp_path / "triage_summary.html").read_text()
    assert "2" in html  # total count


def test_html_contains_each_status(tmp_path):
    manifest = _make_manifest([
        {"source": "/a.jpg", "output": "/b.jpg", "status": "clean",
         "reason": "ok", "crop_top_px": 0, "crop_bottom_px": 0,
         "resolution_mp": 8.3, "processed_at": "2026-04-25T12:00:00"},
        {"source": "/c.jpg", "output": "/d.jpg", "status": "cropped",
         "reason": "overlay", "crop_top_px": 82, "crop_bottom_px": 0,
         "resolution_mp": 8.3, "processed_at": "2026-04-25T12:01:00"},
        {"source": "/e.jpg", "output": None, "status": "rejected_resolution",
         "reason": "2.0MP", "crop_top_px": 0, "crop_bottom_px": 0,
         "resolution_mp": 2.0, "processed_at": "2026-04-25T12:02:00"},
    ])
    generate(manifest, tmp_path)
    html = (tmp_path / "triage_summary.html").read_text()
    assert "clean" in html
    assert "cropped" in html
    assert "rejected_resolution" in html


def test_generate_creates_output_dir(tmp_path):
    nested = tmp_path / "a" / "b"
    generate(_make_manifest([]), nested)
    assert (nested / "triage_summary.html").exists()
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/test_report.py -v
```

Expected: all fail with `ImportError`.

- [ ] **Step 3: Implement `stock-triage/report.py`**

```python
"""Generates triage_summary.html from the manifest."""

from pathlib import Path

REPORT_FILENAME = "triage_summary.html"


def generate(manifest: dict, stock_ready_dir: Path) -> None:
    """Write triage_summary.html to stock_ready_dir."""
    images = manifest.get("images", [])
    counts = _count_statuses(images)
    rows = _build_rows(images)
    html = _render(counts, rows, manifest.get("generated", ""))
    stock_ready_dir.mkdir(parents=True, exist_ok=True)
    (stock_ready_dir / REPORT_FILENAME).write_text(html)


def _count_statuses(images: list) -> dict:
    counts = {"clean": 0, "cropped": 0, "rejected_resolution": 0, "error": 0, "total": len(images)}
    for img in images:
        status = img.get("status", "error")
        if status in counts:
            counts[status] += 1
    return counts


def _build_rows(images: list) -> str:
    badge = {
        "clean":                "color:#7fc",
        "cropped":              "color:#fc7",
        "rejected_resolution":  "color:#f77",
        "error":                "color:#f55",
    }
    rows = []
    for img in images:
        status = img.get("status", "error")
        style = badge.get(status, "color:#aaa")
        rows.append(
            f'<tr>'
            f'<td style="{style}">{status}</td>'
            f'<td>{img.get("source","")}</td>'
            f'<td>{img.get("output") or "—"}</td>'
            f'<td>{img.get("resolution_mp",0):.1f} MP</td>'
            f'<td>{img.get("crop_top_px",0)} / {img.get("crop_bottom_px",0)}</td>'
            f'<td>{img.get("processed_at","")}</td>'
            f'</tr>'
        )
    return "\n".join(rows)


def _render(counts: dict, rows: str, generated: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>GTN Triage Summary</title>
<style>
body{{font-family:monospace;background:#111;color:#eee;padding:2rem}}
h1{{color:#7cf}}
.stats{{display:flex;gap:2rem;margin:1rem 0 2rem}}
.stat{{background:#222;padding:1rem 1.5rem;border-radius:6px}}
.n{{font-size:2rem;font-weight:bold}}
table{{border-collapse:collapse;width:100%;font-size:.85rem}}
th,td{{border:1px solid #333;padding:.4rem .6rem;text-align:left}}
th{{background:#222}}
tr:hover{{background:#1a1a1a}}
</style>
</head>
<body>
<h1>GTN Stock Triage Summary</h1>
<p>Generated: {generated}</p>
<div class="stats">
  <div class="stat"><div class="n">{counts['total']}</div>Total</div>
  <div class="stat"><div class="n" style="color:#7fc">{counts['clean']}</div>Clean</div>
  <div class="stat"><div class="n" style="color:#fc7">{counts['cropped']}</div>Cropped</div>
  <div class="stat"><div class="n" style="color:#f77">{counts['rejected_resolution']}</div>Rejected</div>
  <div class="stat"><div class="n" style="color:#f55">{counts['error']}</div>Errors</div>
</div>
<table>
<thead><tr>
  <th>Status</th><th>Source</th><th>Output</th>
  <th>Resolution</th><th>Crop T/B px</th><th>Processed</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>"""
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/test_report.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
cd weather-station
git add stock-triage/report.py stock-triage/tests/test_report.py
git commit -m "feat(stock-triage): report module — HTML summary with status counts and image table"
```

---

## Task 7: Batch Mode

**Files:**
- Create: `stock-triage/triage.py` (replace stub)
- Create: `stock-triage/tests/test_batch.py`

- [ ] **Step 1: Write the failing integration test**

Create `stock-triage/tests/test_batch.py`:

```python
import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent.parent))

FONT = "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"


def _write_plain(path, w=3840, h=2160):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), (80, 130, 180)).save(path, "JPEG")


def _write_overlay(path, w=3840, h=2160):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (w, h), (80, 130, 180))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 36)
    draw.rectangle([(0, 0), (w, 90)], fill=(0, 0, 0))
    draw.text((20, 8),  "2026/04/25 19:32:15", fill=(255, 255, 255), font=font)
    draw.text((20, 52), "TrackMix Wide  CH1",  fill=(255, 255, 255), font=font)
    img.save(path, "JPEG")


def _write_small(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 600), (80, 130, 180)).save(path, "JPEG")


def test_batch_processes_highlights_and_frigate(tmp_path, monkeypatch):
    highlights = tmp_path / "highlights"
    frigate    = tmp_path / "frigate"
    stock_out  = tmp_path / "stock_ready"

    _write_plain(highlights / "wildlife" / "fox" / "clean.jpg")
    _write_overlay(highlights / "weather" / "storm" / "overlay.jpg")
    _write_small(highlights / "wildlife" / "deer" / "tiny.jpg")
    _write_plain(frigate / "snapshots" / "trackmix_wide" / "fox_event.jpg")

    monkeypatch.setenv("TRIAGE_MODE",        "batch")
    monkeypatch.setenv("LOCATION_LABEL",     "wimberley")
    monkeypatch.setenv("HIGHLIGHTS_DIR",     str(highlights))
    monkeypatch.setenv("FRIGATE_MEDIA_DIR",  str(frigate))
    monkeypatch.setenv("STOCK_READY_DIR",    str(stock_out))
    monkeypatch.setenv("MIN_RESOLUTION_MP",  "4.0")
    monkeypatch.setenv("OCR_TOP_PCT",        "0.15")
    monkeypatch.setenv("OCR_BOTTOM_PCT",     "0.10")

    import importlib
    import triage
    importlib.reload(triage)
    triage.run_batch()

    manifest_path = stock_out / "stock_manifest.json"
    assert manifest_path.exists(), "manifest should be written after batch"

    manifest = json.loads(manifest_path.read_text())
    statuses = {Path(e["source"]).name: e["status"] for e in manifest["images"]}

    assert statuses["clean.jpg"] == "clean"
    assert statuses["overlay.jpg"] == "cropped"
    assert statuses["tiny.jpg"] == "rejected_resolution"

    assert (stock_out / "triage_summary.html").exists()


def test_batch_skips_already_processed(tmp_path, monkeypatch):
    highlights = tmp_path / "highlights"
    stock_out  = tmp_path / "stock_ready"

    _write_plain(highlights / "wildlife" / "fox" / "img.jpg")

    monkeypatch.setenv("TRIAGE_MODE",        "batch")
    monkeypatch.setenv("LOCATION_LABEL",     "wimberley")
    monkeypatch.setenv("HIGHLIGHTS_DIR",     str(highlights))
    monkeypatch.setenv("FRIGATE_MEDIA_DIR",  str(tmp_path / "frigate_empty"))
    monkeypatch.setenv("STOCK_READY_DIR",    str(stock_out))
    monkeypatch.setenv("MIN_RESOLUTION_MP",  "4.0")
    monkeypatch.setenv("OCR_TOP_PCT",        "0.15")
    monkeypatch.setenv("OCR_BOTTOM_PCT",     "0.10")

    import importlib
    import triage
    importlib.reload(triage)

    triage.run_batch()
    manifest_after_first = json.loads((stock_out / "stock_manifest.json").read_text())
    count_first = len(manifest_after_first["images"])

    triage.run_batch()
    manifest_after_second = json.loads((stock_out / "stock_manifest.json").read_text())
    count_second = len(manifest_after_second["images"])

    assert count_first == count_second, "second batch should not add duplicate entries"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/test_batch.py -v
```

Expected: both tests fail — `triage` has no `run_batch` function yet.

- [ ] **Step 3: Implement `stock-triage/triage.py`**

```python
"""Entry point: reads env vars, dispatches batch or daemon mode."""

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from manifest import add_entry, is_processed
from manifest import load as load_manifest
from manifest import save as save_manifest
from pipeline import process_image
from report import generate as gen_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("triage")

MODE            = os.getenv("TRIAGE_MODE",        "daemon")
LOCATION        = os.getenv("LOCATION_LABEL",     "wimberley")
HIGHLIGHTS_DIR  = Path(os.getenv("HIGHLIGHTS_DIR",    "/highlights"))
FRIGATE_DIR     = Path(os.getenv("FRIGATE_MEDIA_DIR",  "/frigate-media"))
STOCK_READY_DIR = Path(os.getenv("STOCK_READY_DIR",   "/stock_ready"))
MIN_RES_MP      = float(os.getenv("MIN_RESOLUTION_MP", "4.0"))
OCR_TOP_PCT     = float(os.getenv("OCR_TOP_PCT",       "0.15"))
OCR_BOTTOM_PCT  = float(os.getenv("OCR_BOTTOM_PCT",    "0.10"))


def _iter_jpegs(root: Path):
    if not root.exists():
        return
    for ext in ("*.jpg", "*.jpeg", "*.JPG", "*.JPEG"):
        yield from sorted(root.rglob(ext))


def _process_one(source: Path, source_root: Path, manifest: dict) -> dict | None:
    if is_processed(manifest, source):
        log.debug("skip (already in manifest): %s", source.name)
        return None
    log.info("processing: %s", source)
    try:
        entry = process_image(
            source, source_root, STOCK_READY_DIR, LOCATION,
            min_resolution_mp=MIN_RES_MP,
            ocr_top_pct=OCR_TOP_PCT,
            ocr_bottom_pct=OCR_BOTTOM_PCT,
        )
    except Exception as exc:
        log.error("error on %s: %s", source, exc)
        entry = {
            "source": str(source),
            "output": None,
            "status": "error",
            "reason": str(exc),
            "crop_top_px": 0,
            "crop_bottom_px": 0,
            "resolution_mp": 0.0,
            "processed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        }
    add_entry(manifest, entry)
    log.info("  → %s  %s", entry["status"], entry.get("output") or "(not exported)")
    return entry


def run_batch() -> None:
    log.info("=== batch mode: full catalog scan ===")
    STOCK_READY_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(STOCK_READY_DIR)
    count = 0

    for source_root in (HIGHLIGHTS_DIR, FRIGATE_DIR):
        if not source_root.exists():
            log.warning("source dir not found, skipping: %s", source_root)
            continue
        log.info("scanning: %s", source_root)
        for source in _iter_jpegs(source_root):
            _process_one(source, source_root, manifest)
            count += 1
            if count % 100 == 0:
                save_manifest(manifest, STOCK_READY_DIR)
                gen_report(manifest, STOCK_READY_DIR)
                log.info("checkpoint: %d images processed", count)

    save_manifest(manifest, STOCK_READY_DIR)
    gen_report(manifest, STOCK_READY_DIR)
    log.info("=== batch complete: %d images processed ===", count)


def run_daemon() -> None:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    log.info("=== daemon mode: watching %s ===", HIGHLIGHTS_DIR)
    STOCK_READY_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(STOCK_READY_DIR)
    counter = [0]

    class _Handler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.suffix.lower() not in (".jpg", ".jpeg"):
                return
            entry = _process_one(path, HIGHLIGHTS_DIR, manifest)
            if entry:
                counter[0] += 1
                save_manifest(manifest, STOCK_READY_DIR)
                if counter[0] % 100 == 0:
                    gen_report(manifest, STOCK_READY_DIR)

    observer = Observer()
    observer.schedule(_Handler(), str(HIGHLIGHTS_DIR), recursive=True)
    observer.start()
    log.info("watching for new .jpg files — Ctrl+C to stop")
    try:
        while observer.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    if MODE == "batch":
        run_batch()
    else:
        run_daemon()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/test_batch.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Run the full test suite to confirm nothing regressed**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/ -v
```

Expected: all tests pass (naming + manifest + ocr + pipeline + report + batch).

- [ ] **Step 6: Commit**

```bash
cd weather-station
git add stock-triage/triage.py stock-triage/tests/test_batch.py
git commit -m "feat(stock-triage): triage entry point — batch mode with full-catalog scan"
```

---

## Task 8: Daemon Mode Test

**Files:**
- Modify: `stock-triage/tests/test_batch.py` (add daemon test)

The daemon uses `watchdog` filesystem events. We test it by starting it in a thread, writing a file, and checking that the manifest is updated.

- [ ] **Step 1: Add daemon test to `stock-triage/tests/test_batch.py`**

Append to the end of `stock-triage/tests/test_batch.py`:

```python
import threading
import time


def test_daemon_processes_new_file(tmp_path, monkeypatch):
    highlights = tmp_path / "highlights"
    highlights.mkdir(parents=True)
    stock_out  = tmp_path / "stock_ready"

    monkeypatch.setenv("TRIAGE_MODE",        "daemon")
    monkeypatch.setenv("LOCATION_LABEL",     "wimberley")
    monkeypatch.setenv("HIGHLIGHTS_DIR",     str(highlights))
    monkeypatch.setenv("FRIGATE_MEDIA_DIR",  str(tmp_path / "frigate_empty"))
    monkeypatch.setenv("STOCK_READY_DIR",    str(stock_out))
    monkeypatch.setenv("MIN_RESOLUTION_MP",  "4.0")
    monkeypatch.setenv("OCR_TOP_PCT",        "0.15")
    monkeypatch.setenv("OCR_BOTTOM_PCT",     "0.10")

    import importlib
    import triage
    importlib.reload(triage)

    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    from manifest import load as load_manifest, save as save_manifest, add_entry, is_processed
    from pipeline import process_image

    manifest = load_manifest(stock_out)
    processed_flag = threading.Event()

    class _TestHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.suffix.lower() not in (".jpg", ".jpeg"):
                return
            entry = triage._process_one(path, highlights, manifest)
            if entry:
                save_manifest(manifest, stock_out)
                processed_flag.set()

    observer = Observer()
    observer.schedule(_TestHandler(), str(highlights), recursive=True)
    observer.start()
    time.sleep(0.5)  # give watchdog time to initialise before writing

    # Write a new highlight after the watcher is running
    new_file = highlights / "wildlife" / "fox" / "new_arrival.jpg"
    _write_plain(new_file)

    assert processed_flag.wait(timeout=10), "daemon did not process the new file within 10 seconds"
    observer.stop()
    observer.join()

    manifest_data = json.loads((stock_out / "stock_manifest.json").read_text())
    sources = [e["source"] for e in manifest_data["images"]]
    assert str(new_file) in sources
```

- [ ] **Step 2: Run tests — verify daemon test passes**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/test_batch.py::test_daemon_processes_new_file -v
```

Expected: `1 passed`.

- [ ] **Step 3: Run full test suite**

```bash
cd weather-station
docker compose run --rm -v "$(pwd)/stock-triage:/app" stock-triage \
  python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
cd weather-station
git add stock-triage/tests/test_batch.py
git commit -m "test(stock-triage): daemon watchdog integration test"
```

---

## Task 9: Docker-Compose Wiring and .env.example

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Add stock-triage service to `docker-compose.yml`**

Open `docker-compose.yml`. Find the `# ─── FFmpeg Processor` block (near the end, before the `networks:` section). Insert the following block immediately before the `networks:` line:

```yaml
  # ─── Stock Triage (OCR overlay detection + stock-ready export) ──────────────
  stock-triage:
    build: ./stock-triage
    container_name: stock-triage
    restart: unless-stopped
    volumes:
      - /volume1/highlights:/highlights:ro
      - /volume1/docker/frigate/media:/frigate-media:ro
      - /volume1/stock_ready:/stock_ready
    environment:
      - TRIAGE_MODE=${TRIAGE_MODE:-daemon}
      - LOCATION_LABEL=${LOCATION_LABEL:-wimberley}
      - HIGHLIGHTS_DIR=/highlights
      - FRIGATE_MEDIA_DIR=/frigate-media
      - STOCK_READY_DIR=/stock_ready
      - MIN_RESOLUTION_MP=${MIN_RESOLUTION_MP:-4.0}
      - OCR_TOP_PCT=${OCR_TOP_PCT:-0.15}
      - OCR_BOTTOM_PCT=${OCR_BOTTOM_PCT:-0.10}
    networks:
      - homelab
```

- [ ] **Step 2: Add new env vars to `.env.example`**

Append the following block to the end of `.env.example`:

```bash
# ─── Stock Triage ────────────────────────────────────────────────────────────
# Location slug used in output filenames and directory structure.
# Change this when deploying to a second camera site.
LOCATION_LABEL=wimberley

# "batch" for one-time full-catalog scan (exits when done).
# "daemon" for ongoing watch mode (default for the running container).
TRIAGE_MODE=daemon

# Minimum megapixels for stock eligibility (Adobe/Shutterstock require ~4MP).
MIN_RESOLUTION_MP=4.0

# Fraction of image height to scan for overlay text.
OCR_TOP_PCT=0.15
OCR_BOTTOM_PCT=0.10
```

- [ ] **Step 3: Build the service from the compose file**

```bash
cd weather-station
docker compose build stock-triage
```

Expected: build completes with no errors.

- [ ] **Step 4: Run the batch scan against real highlights**

```bash
cd weather-station
TRIAGE_MODE=batch docker compose run --rm stock-triage
```

Expected: the service scans `/volume1/highlights/` and `/volume1/docker/frigate/media/`, logs one line per image processed, then exits cleanly:
```
2026-04-25 12:00:00  INFO     === batch mode: full catalog scan ===
2026-04-25 12:00:00  INFO     scanning: /highlights
2026-04-25 12:00:01  INFO     processing: /highlights/wildlife/fox/20260424_fox_abc.jpg
2026-04-25 12:00:04  INFO       → clean  /stock_ready/wimberley/wildlife/fox/gtn_wimberley_20260424_193215_fox_clean.jpg
...
2026-04-25 12:05:00  INFO     === batch complete: NNN images processed ===
```

- [ ] **Step 5: Verify output files exist**

```bash
ls /volume1/stock_ready/wimberley/
ls /volume1/stock_ready/
cat /volume1/stock_ready/stock_manifest.json | python3 -m json.tool | head -40
```

Expected: directories for `wildlife/`, `weather/`, `golden-hour/`, etc. under `wimberley/`. Manifest JSON with `images` array containing entries.

- [ ] **Step 6: Start the daemon**

```bash
cd weather-station
docker compose up -d stock-triage
docker compose logs -f stock-triage
```

Expected log line:
```
=== daemon mode: watching /highlights ===
watching for new .jpg files — Ctrl+C to stop
```

- [ ] **Step 7: Commit**

```bash
cd weather-station
git add docker-compose.yml .env.example
git commit -m "feat(stock-triage): wire into docker-compose, add .env.example vars"
```

---

## Done

After Task 9, the stock triage pipeline is fully operational:

```
/volume1/stock_ready/
└── wimberley/
    ├── wildlife/fox/    → gtn_wimberley_YYYYMMDD_HHMMSS_fox_clean.jpg
    ├── wildlife/deer/   → gtn_wimberley_YYYYMMDD_HHMMSS_deer_crop.jpg
    ├── weather/storm/   → ...
    ├── golden-hour/sunrise/
    ├── golden-hour/sunset/
    ├── panoramas/panorama/
    └── stars/stars/
/volume1/stock_ready/stock_manifest.json
/volume1/stock_ready/triage_summary.html
```

**Re-run batch at any time** (skips already-processed images):
```bash
TRIAGE_MODE=batch docker compose run --rm stock-triage
```

**View the triage summary:**
Open `/volume1/stock_ready/triage_summary.html` in a browser.
