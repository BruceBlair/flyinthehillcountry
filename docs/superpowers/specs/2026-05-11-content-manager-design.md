# Content Manager Design

**Date:** 2026-05-11
**Replaces:** `highlight-curator/cull_ui.py`
**Status:** Approved for implementation

## Overview

A unified local web UI (`content_manager.py`) that replaces `cull_ui.py` and adds timelapse building from Frigate recordings. Runs at port 8766 on the NAS, LAN-only. No live capture daemon — all timelapse work is retroactive from Frigate-recorded MP4 segments.

---

## Architecture

```
content_manager.py          (HTTP server, port 8766)
├── Photos tab              (existing cull grid — absorbed from cull_ui.py)
├── Timelapse tab           (new — build from Frigate recordings)
└── Status tab              (new — pipeline log + manual trigger)

frigate_extract.py          (new — segment discovery + ffmpeg frame extraction)

Imports (unchanged scripts):
  timelapse_builder._build_one()
  cull_highlights.py (imported as module for delete logic)
  score_images.py    (referenced but not called during build)
```

### Data flow — timelapse build

```
User clicks Build
  → POST /api/timelapse/build
    → background thread starts
      → frigate_extract.find_segments(start_dt, end_dt, camera="trackmix_wide")
          discovers /volume1/frigate/trackmix_wide/**/*.mp4 overlapping window
      → frigate_extract.extract_frames(segments, interval_secs, tmp_dir)
          ffmpeg -vf fps=1/N for each segment, clips to window bounds
      → timelapse_builder._build_one(sorted_frames, out_path, cpu_percent)
          encodes MP4 at FRAME_DURATION=0.12s/frame (~8fps)
      → writes entry to timelapse_manifest.json
      → job status updated to "done" / "error"
  ← UI polls GET /api/timelapse/status → shows progress
```

---

## Components

### `frigate_extract.py`

Two public functions:

**`find_segments(start_dt, end_dt, frigate_dir, camera) → list[Path]`**
- Walks `{frigate_dir}/{camera}/` looking for MP4 files whose filenames or modification times overlap `[start_dt, end_dt]`
- Handles Frigate's typical path pattern: `trackmix_wide/YYYY-MM-DD/HH/MM.mp4`
- Falls back to mtime-based matching if path pattern doesn't match
- Returns segments sorted chronologically

**`extract_frames(segments, start_dt, end_dt, interval_secs, out_dir) → list[Path]`**
- For each segment: calculates `-ss` / `-to` offsets to clip to the requested window
- Runs: `ffmpeg -ss {offset} -to {end} -i {seg} -vf fps=1/{interval} {out_dir}/{n:06d}.jpg`
- Frame filenames encode absolute timestamp so cross-segment sorting is correct
- Returns sorted list of extracted frame paths

### `content_manager.py`

Python `http.server.BaseHTTPRequestHandler`, same pattern as `cull_ui.py`.

**API endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve single-page HTML/JS app |
| GET | `/api/images` | Images grouped by category (from manifest.json) |
| POST | `/api/delete` | Delete selected snapshots, update manifest |
| GET | `/api/sessions` | Available golden-hour sessions (from manifest + Frigate dirs) |
| GET | `/api/timelapses` | List built timelapses from timelapse_manifest.json |
| POST | `/api/timelapse/build` | Start background build job |
| GET | `/api/timelapse/status` | Current job status + progress |
| GET | `/api/pipeline/log` | Last N lines of cron-scan-sync.sh output |
| POST | `/api/pipeline/run` | Run cron-scan-sync.sh in background |
| GET | `/thumb/{path}` | Thumbnail (240×180, cached in memory) |
| GET | `/photo/{path}` | Full-resolution image |

**Background job model:**
- One build job at a time (queue is fine for solo use)
- Job state: `idle | running | done | error`
- Progress: `{stage: "extracting|encoding", frames_done: N, frames_total: N}`
- Thread writes to a shared dict; `/api/timelapse/status` reads it under a lock

---

## UI — Timelapse Tab

### Mode selector
```
[Golden Hour]  [Full Day]  [Custom Range]
```

### Golden Hour mode
```
Date:  [2026-05-11]   Type: [sunset ▼]
```
Auto-calculates window as ±30 min around calculated sunrise/sunset for the NAS lat/lon (from `LATITUDE`/`LONGITUDE` env vars, same as curator.py). Default chosen to capture pre/post glow; overridable via interval/duration controls.

### Full Day mode
```
Date:  [2026-05-11]
```
Window = (sunrise − 30 min) to (sunset + 30 min), capturing pre-dawn and afterglow. Typically ~15 hours → ~5,400 frames at 10s interval → ~10 min 48 sec video.

### Custom Range mode
```
Start: [2026-05-11 18:30]    End: [2026-05-11 20:15]
Label: [storm_rollout]
```

### Timing controls (shared across all modes)
Two sub-modes, toggled by radio:

**Interval mode** (default):
```
Extract 1 frame every  [10] seconds
                              → video will be approx. 10 min 5 sec
```

**Duration mode:**
```
Make video  [5]  minutes long
                              → 1 frame every 20s
```

Live recalculation on input change. Formula:
- Interval → duration: `duration = (window_seconds / interval) × 0.12`
- Duration → interval: `interval = window_seconds / (duration_seconds / 0.12)`

### Build controls
```
Camera: [Wide ▼]   [Build Timelapse]   [▌▌ progress bar]
```

### Built timelapses list
Thumbnail grid below the controls — pulls from `timelapse_manifest.json`. Each card shows date, type, duration, frame count. Click opens video in new tab.

---

## UI — Photos Tab

Identical to current `cull_ui.py`: category tabs, thumbnail grid, select/delete, sync trigger. Code absorbed verbatim, no behavior changes.

---

## UI — Status Tab

- Last 50 lines of pipeline log (from a log file written by `cron-scan-sync.sh`, or captured at run-time)
- **Run pipeline now** button → POST `/api/pipeline/run`
- Active build job status (mirrors the progress bar from Timelapse tab)

---

## File Outputs

Timelapse MP4s written to: `/volume1/highlights/timelapse/`
Naming: `{YYYYMMDD}_{type}_timelapse.mp4` (golden/full-day) or `{YYYYMMDD}_{label}_timelapse.mp4` (custom range)
Manifest: `/volume1/highlights/timelapse_manifest.json` (existing schema, new `source: "frigate_extract"` field added)

---

## Environment Dependencies

| Variable | Used for |
|----------|---------|
| `LATITUDE`, `LONGITUDE` | Sunrise/sunset calculation for Golden Hour + Full Day modes |
| `CAMERA_IP` | Not used (no live capture) |
| Frigate dir | Hardcoded default `/volume1/frigate`, overridable via `--frigate-dir` CLI arg |

Sunrise/sunset calculation: use `astral` (`LocationInfo` + `sun()`) — already in requirements.txt and used identically in `curator.py`.

---

## CLI

```bash
python3 content_manager.py [--port 8766] [--highlights-dir /volume1/highlights] \
                            [--frigate-dir /volume1/frigate] \
                            [--sync-script ../github-pages/sync.sh]
```

---

## What Is Not In Scope

- Live interval capture from RTSP (deferred — retroactive Frigate extraction covers the use case)
- Score-based frame filtering in timelapse (all extracted frames included)
- Multi-job build queue (one job at a time is sufficient)
- Authentication (LAN-only, same as cull_ui.py)
- Zoom lens camera for timelapse (wide lens only for now; `--camera` flag can be added later)
