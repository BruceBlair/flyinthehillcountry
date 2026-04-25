# Stock Triage Pipeline — Design Spec

## Goal

Scan the complete GTN image catalog for sellable photos, auto-detect and crop Reolink camera overlays (timestamp, camera name) using OCR, and output clean stock-ready images to a well-organised directory. After the initial full-catalog scan, a daemon watches for new highlights and processes them automatically.

---

## Scope

This spec covers **subsystem 1 of 3** in the stock-sales workflow:

| Subsystem | Scope |
|-----------|-------|
| **1 — Triage + Crop Pipeline** | ← this spec |
| 2 — Stock Platform Exporter | Adobe, Shutterstock, Fine Art America, Etsy, Pixels |
| 3 — Own-Site Purchase Workflow | Gallery checkout integration |

---

## Architecture

A new `stock-triage/` Docker service joins the existing GTN stack. It is a single Python script (`triage.py`) that operates in one of two modes controlled by the `TRIAGE_MODE` environment variable.

### File Structure

```
weather-station/
└── stock-triage/
    ├── Dockerfile
    ├── requirements.txt
    └── triage.py
```

### Modes

| Mode | Behaviour |
|------|-----------|
| `batch` | Scans all source directories, processes every eligible image, writes manifest + summary, then exits |
| `daemon` | Watches `/highlights` for new `.jpg` files using filesystem events (watchdog), processes each through the same pipeline, updates manifest incrementally |

### First-Time Workflow

```bash
# Step 1 — full catalog scan (run once, exits when done)
TRIAGE_MODE=batch docker compose run --rm stock-triage

# Step 2 — start the ongoing daemon
docker compose up -d stock-triage
```

---

## Sources

| Directory | Mode |
|-----------|------|
| `/volume1/highlights/` | batch + daemon |
| `/volume1/docker/frigate/media/` | batch only |

The Frigate raw archive is too large to watch continuously. The one-time batch covers it in full. The daemon watches only the curated highlights stream produced by the highlight-curator service.

---

## Output

### Directory Structure

```
/volume1/stock_ready/
└── {location}/
    ├── wildlife/
    │   ├── fox/
    │   ├── deer/
    │   ├── bird/
    │   └── {label}/
    ├── weather/
    │   ├── storm/
    │   └── lightning/
    ├── golden-hour/
    │   ├── sunrise/
    │   └── sunset/
    ├── panoramas/
    └── stars/
```

### Filename Convention

```
gtn_{location}_{YYYYMMDD}_{HHMMSS}_{label}_{status}.jpg
```

| Token | Example | Source |
|-------|---------|--------|
| `gtn` | `gtn` | hardcoded brand prefix |
| `{location}` | `wimberley` | `LOCATION_LABEL` env var |
| `{YYYYMMDD}` | `20260424` | file mtime (or EXIF DateTimeOriginal if present) |
| `{HHMMSS}` | `193215` | same |
| `{label}` | `fox`, `storm`, `sunrise`, `panorama`, `stars` | derived from source subdirectory path |
| `{status}` | `clean` or `crop` | `clean` = no overlay detected; `crop` = overlay was removed. Note: the manifest uses `"cropped"` for this same outcome — the filename uses the shorter `crop` suffix. |

**Examples:**
```
gtn_wimberley_20260424_193215_fox_clean.jpg
gtn_wimberley_20260424_193215_storm_crop.jpg
gtn_wimberley_20260424_193215_sunrise_clean.jpg
gtn_wimberley_20260424_193215_panorama_crop.jpg
gtn_wimberley_20260424_003100_stars_clean.jpg
```

### Manifest

`/volume1/stock_ready/stock_manifest.json` — one entry per processed image, never deleted (only appended / updated). Used to skip already-processed images on re-runs.

```json
{
  "generated": "2026-04-25T12:00:00",
  "images": [
    {
      "source": "/highlights/wildlife/20260424_fox_abc123.jpg",
      "output": "/stock_ready/wimberley/wildlife/fox/gtn_wimberley_20260424_193215_fox_clean.jpg",
      "status": "clean",
      "reason": "no overlay detected",
      "crop_top_px": 0,
      "crop_bottom_px": 0,
      "resolution_mp": 8.3,
      "processed_at": "2026-04-25T12:01:23"
    }
  ]
}
```

**Status values:**

| Status | Meaning |
|--------|---------|
| `clean` | No overlay detected; copied as-is |
| `cropped` | Overlay detected; bounding-box crop applied |
| `rejected_resolution` | Below `MIN_RESOLUTION_MP`; not exported |
| `error` | OCR or file I/O failure; logged, not exported |

### Summary Report

`/volume1/stock_ready/triage_summary.html` — human-readable HTML page regenerated after every batch run and after every 100 daemon-processed images. Contains:
- Totals: clean / cropped / rejected / errors
- Per-image table: thumbnail, source path, output path, status, resolution, crop amounts

---

## Processing Pipeline

Each image passes through these stages in order:

```
Discover all .jpg files in source directories
            ↓
  Already in manifest? → Skip
            ↓
  Resolution < MIN_RESOLUTION_MP? → Reject, log reason
            ↓
  Extract top OCR_TOP_PCT% band + bottom OCR_BOTTOM_PCT% band
            ↓
  Run pytesseract on each band
            ↓
  Date pattern (\d{4}[/-]\d{2}) found in either band?
    YES → find text bounding boxes → compute crop bounds
        → crop image to exclude overlay bands
        → status = "cropped"
    NO  → status = "clean"
            ↓
  Save output JPEG at quality 95, preserving EXIF
            ↓
  Append manifest entry
  Update summary report
```

### OCR Band Logic

- **Top band:** extract the top `OCR_TOP_PCT` (default 15%) of the image height
- **Bottom band:** extract the bottom `OCR_BOTTOM_PCT` (default 10%) of the image height
- OCR is run only on these bands — not the full image — for performance

### Dynamic Crop Logic

- For the **top band**: find the maximum `y` coordinate of any detected text bounding box; crop the image starting at `y + 2px`
- For the **bottom band**: find the minimum `y` coordinate (relative to full image) of any detected text bounding box; crop the image ending at `y - 2px`
- If only one band has text, only that side is cropped
- EXIF metadata (camera model, DateTimeOriginal, GPS) is copied to the output file

### Resolution Filter

- Minimum: `MIN_RESOLUTION_MP` megapixels (default `4.0`)
- Calculated as: `(width_px * height_px) / 1_000_000 >= MIN_RESOLUTION_MP`
- Applied before OCR to avoid wasting time on ineligible images

---

## Configuration (Environment Variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `TRIAGE_MODE` | `daemon` | `batch` or `daemon` |
| `LOCATION_LABEL` | `wimberley` | Location slug used in filenames and directory structure |
| `HIGHLIGHTS_DIR` | `/highlights` | Curated highlights source (batch + daemon) |
| `FRIGATE_MEDIA_DIR` | `/frigate-media` | Raw Frigate archive source (batch only) |
| `STOCK_READY_DIR` | `/stock_ready` | Output root |
| `MIN_RESOLUTION_MP` | `4.0` | Minimum megapixels for stock eligibility |
| `OCR_TOP_PCT` | `0.15` | Fraction of image height to scan for top overlay |
| `OCR_BOTTOM_PCT` | `0.10` | Fraction of image height to scan for bottom overlay |

---

## Docker-Compose Addition

```yaml
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

---

## Dependencies

| Library | Purpose |
|---------|---------|
| `pytesseract` | Python wrapper for Tesseract OCR |
| `Pillow` | Image open, crop, save, EXIF handling |
| `watchdog` | Filesystem event watching for daemon mode |
| `tesseract-ocr` | System package (installed in Dockerfile) |

---

## Out of Scope

- Upload to stock platforms (subsystem 2)
- Purchase workflow on the GTN website (subsystem 3)
- Video/clip processing (JPEG only in this spec)
- Manual review UI (the summary HTML is read-only)
