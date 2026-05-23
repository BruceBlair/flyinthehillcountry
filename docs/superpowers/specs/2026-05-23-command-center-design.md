# GTN Command Center — Design Spec

**Date:** 2026-05-23
**Status:** Approved

## Overview

Extend `content_manager.py` (port 8766) into a full Command Center for the Ground Truth Network node. The Command Center replaces the existing minimal HTML with a left-sidebar shell that houses photo management, timelapse review, stock upload, platform configuration, system status, and an optional Claude assistant panel.

## Architecture

Multi-file split using stdlib `http.server`. No new dependencies beyond the existing `highlight-curator` environment. `content_manager.py` gains new route groups while continuing to serve the existing photo/timelapse API.

### File layout

```
highlight-curator/
  content_manager.py              ← extended: adds /api/upload/*, /api/flags/*, /api/claude/chat, /api/platforms/*
  static/
    command_center.html           ← sidebar shell; single-page app skeleton
    css/
      command_center.css          ← dark theme, sidebar, grid layout
    js/
      photos.js                   ← photo grid, flag chips, flag editing
      upload.js                   ← split list+detail upload workflow
      platforms.js                ← platform config, connection status
      claude_panel.js             ← Claude assistant panel
  platforms/
    __init__.py
    shutterstock.py               ← Shutterstock Contributor API client
    adobe_stock.py                ← Adobe Stock Contributor API client
```

`content_manager.py` detects the `command_center.html` shell and serves `static/` under `/static/`. All API routes are prefixed `/api/`.

## Navigation

Left sidebar with icon + label entries. Claude panel is a separate slide-in from the right edge, not a sidebar entry.

| Entry | Route fragment | Content |
|---|---|---|
| Photos | `#photos` | Highlight photo grid with flag chips |
| Timelapse | `#timelapse` | Timelapse cards (existing build queue UI) |
| Upload | `#upload` | Split list + detail upload queue |
| Platforms | `#platforms` | Platform credentials, status, history |
| Status | `#status` | Service health, queue depth, storage |
| Claude ✦ | (toggle) | Slide-in assistant panel |

Active section is highlighted in the sidebar. Tab switching swaps the main content area; sidebar always visible.

## Photo Flags

### Manifest data model

Flag fields added to each entry in `/volume1/highlights/manifest.json`:

```json
{
  "id": "evt_abc123",
  "path": "/volume1/highlights/wildlife/2026-05-21_0622_...",
  "score": 82.3,
  "timestamp": "2026-05-21T06:22:00",
  "flags": {
    "crop": false,
    "enhance": false,
    "auth_hold": false
  },
  "crop_region": null,
  "uploads": {}
}
```

`crop_region` is `null` or `{x, y, w, h}` in normalized 0.0–1.0 coordinates relative to the original image dimensions.

`uploads` tracks per-platform state:
```json
"uploads": {
  "shutterstock": { "status": "uploaded", "asset_id": "551234567" },
  "adobe_stock":  { "status": "error", "error": "missing keyword" }
}
```

Upload statuses: `pending` → `uploading` → `uploaded` | `error`

### UI — corner chip badges

Flags render as small coloured chips in the top-left corner of each photo card:

| Flag | Chip label | Colour |
|---|---|---|
| crop | CROP | orange `#fa0` |
| enhance | ENH | blue `#4af` |
| auth_hold | HOLD | red `#f44` |

Clicking a chip opens a flag popover with a toggle to set/clear the flag and, for crop, a region editor (drag handles on the photo preview).

### Crop mechanics

Setting `crop = true` requires a `crop_region` to be defined before the photo can be queued for upload. At upload time:
1. A cropped copy is written alongside the original: `<stem>_crop.<ext>`
2. Only the cropped copy is submitted to platforms
3. The original file is never modified or submitted

### API endpoints

```
GET  /api/photos                         → list entries from manifest.json
PATCH /api/photos/<id>/flags             → set/clear one or more flags
PATCH /api/photos/<id>/crop_region       → set normalized crop region
POST /api/photos/<id>/queue              → add to upload_queue.json
```

All flag writes go through `locked_manifest_update()` from `manifest_io.py`.

## Upload Workflow

### Split list + detail layout

Left column: scrollable list of queued photos (thumbnail + filename + flag indicators + status badge).
Right panel: full detail for the selected photo — large preview with optional crop overlay, title/caption field, keyword field, platform checkboxes, Upload this photo / Skip buttons.

Header bar above the split: queue depth count, Upload all / Auto-run button, platform enable toggles.

### Upload queue

Separate `upload_queue.json` at `/volume1/highlights/upload_queue.json`:

```json
{
  "mode": "manual",
  "queue": [
    {
      "id": "evt_abc123",
      "title": "Sunrise over hill country",
      "keywords": "sunrise, golden hour, Texas hill country, landscape",
      "platforms": ["shutterstock", "adobe_stock"]
    }
  ]
}
```

Written atomically via `atomic_write_json()` from `manifest_io.py`.

**Manual mode:** after clicking "Upload this photo", the queue advances to the next entry and pauses for user action.

**Auto mode:** queue is drained sequentially without pausing. Each upload result is written back to the manifest entry's `uploads` field before advancing.

### Metadata submitted per photo

- Title / caption (required)
- Keywords (comma-separated, required by both platforms)
- Category (pre-filled from Frigate event category: wildlife, landscape, weather)
- Platform selection (per-photo checkboxes: Shutterstock, Adobe Stock)

Metadata is stored transiently in the queue entry and not persisted to manifest.json (it belongs to the submission, not the archive record).

### API endpoints

```
GET  /api/upload/queue                   → current queue + mode
POST /api/upload/queue/add               → add entry id to queue
DELETE /api/upload/queue/<id>            → remove from queue
POST /api/upload/queue/mode              → switch manual/auto
POST /api/upload/<id>/submit             → trigger upload for one entry (manual mode)
POST /api/upload/run                     → start auto-drain (auto mode)
GET  /api/upload/<id>/status             → poll status for one entry
```

## Platform API Clients

### Shared interface

Both clients in `platforms/` expose:

```python
def upload(self, image_path: Path, metadata: dict) -> dict
    # Returns {"asset_id": "..."} on success; raises on error

def get_status(self, asset_id: str) -> str
    # Returns "pending" | "approved" | "rejected" | "unknown"

def refresh_token(self) -> None
    # Exchanges client credentials for a new access token; writes back to creds file
```

### Shutterstock Contributor API

- Auth: OAuth 2.0 bearer token via client_id + client_secret
- Upload: multipart POST with image file and metadata fields
- Token refresh: `POST api.shutterstock.com/v2/oauth/access_token`
- Exact upload endpoint verified against Shutterstock Contributor API docs at implementation time

### Adobe Stock Contributor API

- Auth: Adobe IMS OAuth 2.0 (api_key + client_secret)
- Upload: multipart POST to contributor ingest endpoint
- Exact upload endpoint verified against Adobe Stock Contributor API docs at implementation time

### Credentials file

`~/.gtn/platform_creds.json` (outside repo, chmod 600, never committed):

```json
{
  "shutterstock": {
    "client_id": "",
    "client_secret": "",
    "access_token": "",
    "token_expiry": ""
  },
  "adobe_stock": {
    "api_key": "",
    "client_secret": "",
    "access_token": "",
    "token_expiry": ""
  },
  "anthropic": {
    "api_key": ""
  }
}
```

Credentials are entered via the Platforms tab in the UI and saved via `POST /api/platforms/credentials`. They are never returned to the frontend after initial save (GET /api/platforms/status returns connection health only, not raw credentials).

### Platforms tab UI

Per platform: connection status indicator (green = connected, red = error, grey = unconfigured), enable/disable toggle, contributor account display name, total uploads count, link to platform contributor dashboard.

## Claude Assistant Panel

### Behaviour

Optional slide-in from the right edge, toggled by "Claude ✦" in the sidebar footer. When open, narrows the main content area by ~320px.

Scrollable message history + text input at the bottom. Responses appear when complete (no streaming in v1).

### Context injection

Each message to the backend includes the current UI state:

```json
{
  "message": "Suggest keywords for this photo",
  "context": {
    "current_tab": "upload",
    "selected_photo": {
      "path": "wildlife/2026-05-21_0622_evt_abc123.jpg",
      "score": 82.3,
      "category": "wildlife",
      "flags": { "crop": true, "enhance": false, "auth_hold": false },
      "uploads": {}
    },
    "queue_depth": 7
  }
}
```

Context is assembled by `claude_panel.js` from the current app state before each send.

### Backend proxy

`POST /api/claude/chat` — receives `{message, context}`, constructs a system prompt that includes the context, calls Anthropic API with the configured model, returns `{reply}`.

System prompt primes Claude on the GTN domain: wildlife/weather camera, stock photo submission, Shutterstock + Adobe Stock platforms, Frigate detection pipeline.

### Model config

Default: `claude-haiku-4-5-20251001` (fast, low cost for keyword gen).
Switchable to `claude-sonnet-4-6` via Platforms settings for more nuanced analysis.
API key stored under `"anthropic"` in `~/.gtn/platform_creds.json`.

## System Status Tab

Displays:
- Docker service health (queried via `docker compose ps` subprocess or health endpoint)
- `/volume1/highlights/` storage usage
- Upload queue depth
- Last backfill run timestamp (from manifest `updated` field)
- Recent upload results (last 10, across all platforms)

## Out of Scope

- Local hosted sales platform (deferred — placeholder entry in Platforms tab)
- Streaming Claude responses
- Multi-node dashboard (separate project)
- Audio analysis integration
- Mobile/responsive layout
