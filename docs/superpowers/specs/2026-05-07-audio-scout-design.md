# Audio Scout — Design Spec
**Date:** 2026-05-07  
**Status:** Approved  
**Service:** `audio-scout`

---

## Overview

Real-time wildlife and bird sound detection from the Reolink TrackMix RTSP audio stream. Detections are classified by BirdNET-Analyzer (birds) and YAMNet (broader wildlife), enriched with species info from eBird/iNaturalist, stored as standalone entries with optional linking to nearby photo events, and published to MQTT for Home Assistant integration. A separate CPU-throttleable back-analysis script handles historical video files on demand.

---

## Directory Structure

```
weather-station/
  audio-scout/
    Dockerfile
    requirements.txt
    scout.py            # real-time service entrypoint
    species_cache.py    # eBird/iNaturalist lookup + local cache
    mqtt_client.py      # thin MQTT wrapper
    rare_species.txt    # one species per line; detections trigger push notification
  audio-backfill.py     # standalone back-analysis script (not containerized)
```

New NAS paths:
```
/volume1/highlights/
  audio_manifest.json       # all detections, unreviewed count, species summaries
  audio/
    *.wav                   # 3-second audio clips, one per detection
    species_cache.json      # cached eBird/iNaturalist lookups by scientific name
    backfill_progress.json  # back-analysis progress/state
```

---

## Docker Service

Added to `docker-compose.yml`:

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
    - LATITUDE=${LATITUDE:-29.9974}
    - LONGITUDE=${LONGITUDE:--98.0986}
    - BIRDNET_CONFIDENCE=${BIRDNET_CONFIDENCE:-0.70}
    - YAMNET_CONFIDENCE=${YAMNET_CONFIDENCE:-0.75}
    - AUDIO_SUBMIT_MODE=${AUDIO_SUBMIT_MODE:-off}
    - EBIRD_API_KEY=${EBIRD_API_KEY:-}
    - RARE_SPECIES_PUSH=${RARE_SPECIES_PUSH:-false}
```

Uses `host` network mode (same as `sky-watcher`) for direct camera and MQTT access.

New `.env` variables to document:

| Variable | Default | Purpose |
|---|---|---|
| `BIRDNET_CONFIDENCE` | `0.70` | Minimum BirdNET confidence to record detection |
| `YAMNET_CONFIDENCE` | `0.75` | Minimum YAMNet confidence to record detection |
| `AUDIO_SUBMIT_MODE` | `off` | `off` / `auto` / `manual` |
| `EBIRD_API_KEY` | _(empty)_ | Required for eBird submission and range data |
| `RARE_SPECIES_PUSH` | `false` | Enable push notifications for rare species |

---

## Data Flow

### Real-Time (continuous)

```
RTSP stream (camera:554/h264Preview_01_main)
  → ffmpeg subprocess — PCM audio, 3-second chunks
    → BirdNET-Analyzer — bird species + confidence
    → YAMNet — non-bird sounds (frogs, insects, dogs, rain, vehicles, etc.)
      ↓ above confidence threshold
      → save 3s WAV to /volume1/highlights/audio/
      → species_cache.py — iNaturalist lookup, eBird if key present (cached)
      → write detection to audio_manifest.json
          reviewed=false, increment unreviewed_count
          link to photo entry if one exists in highlights manifest within ±60s
          update species_summary tallies (week / month / season)
      → MQTT: audio/detections  (all detections)
          → rare species match? → audio/detections/rare → HA push notification
```

### Back-Analysis (on-demand)

```
audio-backfill.py --cpu-percent 25 /volume1/camera_raw/05072026/
  → for each .mp4 not in analyzed_sources:
      → ffmpeg extracts audio track
      → same BirdNET → YAMNet → manifest pipeline
      → on completion: append source path to analyzed_sources
  → cpulimit -l <percent> -p <own_pid> on startup
  → progress written to backfill_progress.json (crash-safe resume)
```

---

## audio_manifest.json Schema

Season windows use meteorological seasons: Spring Mar–May, Summer Jun–Aug, Fall Sep–Nov, Winter Dec–Feb.

```json
{
  "unreviewed_count": 14,
  "updated": "2026-05-07T01:15:00",
  "species_summary": {
    "week":   {"Northern Mockingbird": 47, "Carolina Wren": 12, "frog": 3},
    "month":  {"Northern Mockingbird": 203, "Carolina Wren": 89},
    "season": {"Northern Mockingbird": 410}
  },
  "analyzed_sources": [
    "/volume1/camera_raw/05062026/High Res In The Hill CountryCH01-00-153502-153618.mp4"
  ],
  "detections": [
    {
      "id": "audio_20260507_011500_birdnet_001",
      "timestamp": "20260507_011500",
      "detector": "birdnet",
      "species": "Northern Mockingbird",
      "scientific_name": "Mimus polyglottos",
      "confidence": 0.87,
      "clip": "audio/20260507_011500_northern_mockingbird.wav",
      "linked_photo": "wildlife/20260506_011502_snapshot.jpg",
      "species_info": {
        "family": "Mimidae",
        "conservation_status": "LC",
        "ebird_species_code": "normoc",
        "range_map_url": "https://ebird.org/species/normoc",
        "description": "..."
      },
      "reviewed": false,
      "submitted_to": null,
      "source": "realtime"
    }
  ]
}
```

`analyzed_sources` is appended only after a file completes fully — a crash mid-file forces a clean re-run of that file.

---

## Species Lookup & Submission

### Lookup (every detection, automatic)
1. Check `species_cache.json` — skip API call if species already cached
2. iNaturalist API (public, no key) — common name, scientific name, conservation status, description
3. eBird API (if `EBIRD_API_KEY` set) — range data, species code for checklist submission
4. Cache result in `species_cache.json` keyed by scientific name

### Submission Modes

**`off`** — no submissions (default)

**`auto`** — follows platform rules:
- eBird: one checklist per calendar day, submitted at midnight; all species heard with count and GPS location
- iNaturalist: one observation per species per day, confidence ≥ 0.85 only

**`manual`** — detections accumulate; `audio-submit.py` CLI lets operator review and selectively submit. Feeds the future command center review UI.

### Rare Species Push Notifications
`audio-scout/rare_species.txt` — one common or scientific name per line. Any detection matching a name publishes to `audio/detections/rare`. HA automation on that topic sends a push notification. Operator edits the list directly; container re-reads it on each detection (no restart needed).

---

## CPU Throttling (Back-Analysis)

```bash
# Analyze one day at 25% CPU (default if --cpu-percent omitted)
python3 audio-backfill.py --cpu-percent 25 /volume1/camera_raw/05072026/

# Analyze since a date
python3 audio-backfill.py --cpu-percent 15 --since 2026-05-01 /volume1/camera_raw/

# Dry run — show pending files without processing
python3 audio-backfill.py --dry-run /volume1/camera_raw/05072026/
```

- Uses `cpulimit -l <percent> -p <own_pid>` on startup
- Warns and continues unthrottled if `cpulimit` not installed
- `--cpu-percent` defaults to `25` — never accidentally runs full-tilt

---

## MQTT Topics

| Topic | Payload | Purpose |
|---|---|---|
| `audio/detections` | detection JSON | All detections above threshold |
| `audio/detections/rare` | detection JSON | Rare species list matches only |
| `audio/status` | `{"status": "ok", "uptime": ...}` | Heartbeat every 60s |

---

## Review Tracking

- Every detection written with `reviewed: false`
- `unreviewed_count` maintained in manifest root — incremented on write, decremented on review
- `audio-submit.py --mark-reviewed <id>` for CLI review
- Full review UI deferred to command center project

---

## Out of Scope (This Spec)

- Command center review UI (separate project)
- Multi-camera audio (single RTSP stream for now)
- Audio fingerprinting / individual animal identification
- Back-analysis scheduling (manual on-demand only)
