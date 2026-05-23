# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Deployment

```bash
# First-time setup (creates /volume1 dirs, copies configs, provisions Grafana datasource)
cp .env.example .env   # fill in credentials first
bash setup.sh

# Start / stop all services
docker compose up -d
docker compose down

# Status
docker compose ps
docker stats --no-stream

# Logs / restart a single service
docker compose logs -f <service>
docker compose restart <service>

# Pick up a rebuilt image (restart reuses old container layer):
docker compose up -d --force-recreate <service>
```

## Services

All services defined in `docker-compose.yml`. Three network modes are in use:
- `homelab` bridge: mosquitto, influxdb, grafana, highlight-curator, star-scanner, vote-server, night-sky-patrol, ffmpeg-processor
- `host` network: homeassistant, frigate, mediamtx, sky-watcher, audio-scout (require direct LAN access or avoid bridge NAT)

| Service | Port(s) | Image/Build |
|---|---|---|
| mosquitto | 1883, 9001 | eclipse-mosquitto |
| influxdb | 8086 | influxdb:2.7 |
| homeassistant | 8123 | home-assistant/home-assistant |
| grafana | 3000 | grafana/grafana |
| frigate | host (5000, 8554–8555) | blakeblackshear/frigate |
| mediamtx | host (8888/8889/8554/1935/9997) | bluenviron/mediamtx |
| ffmpeg-processor | — | linuxserver/ffmpeg (idle entrypoint) |
| highlight-curator | — | ./highlight-curator |
| star-scanner | — | ./highlight-curator (alt command) |
| vote-server | 8765 | ./highlight-curator (alt command) |
| night-sky-patrol | — | ./night-sky-patrol |
| sky-watcher | host | ./sky-watcher |
| audio-scout | host | ./audio-scout |

## Config File Relationships

`setup.sh` copies canonical source files into runtime locations. **Edit the source files** at the repo root, then re-run `setup.sh` or copy manually:

| Source (repo root) | Runtime location |
|---|---|
| `mosquitto.conf` | `mosquitto/config/mosquitto.conf` |
| `frigate-config.yml` | `frigate/config/config.yml` |
| `ha-configuration.yaml` | `homeassistant/config/configuration.yaml` |
| `ha-automations.yaml` | `homeassistant/config/automations.yaml` |
| `mediamtx/mediamtx.yml` | `mediamtx/mediamtx.yml` |
| `ffmpeg-process-media.sh` | `ffmpeg/scripts/process_media.sh` |

`setup.sh` also templates `grafana/provisioning/datasources/influxdb.yml` from `.env` values at runtime — do not edit that file directly.

**Note:** Frigate's docker-compose mounts `/volume1/docker/frigate/config:/config`, but `setup.sh` copies to `./frigate/config/`. These may diverge — verify which path Frigate is actually reading if config changes don't take effect.

## Highlight Pipeline Architecture

The highlight system is the most complex part. Data flows through several independent processes:

```
Real-time path:
  Frigate detection events (MQTT: frigate/events)
    → highlight-curator/curator.py
      → fetches snapshots + clips from Frigate API
      → writes to /volume1/highlights/{wildlife,golden_hour/sunrise|sunset,weather}/
      → updates /volume1/highlights/manifest.json

Scheduled path (cron-scan-sync.sh, runs hourly):
  1. backfill-highlights.py --mode events   # re-scans Frigate DB for last 2 days
  2. score_images.py                        # scores each snapshot 0–100 (warm colour,
                                            #   saturation, contrast, sky/ground split)
  3. cull_highlights.py                     # keeps best-N per event
  4. generate-slowmo-reel.sh                # builds slow-motion clip from last hour
  5. github-pages/sync.sh                   # pushes highlights to GitHub Pages gallery

Timelapse path:
  timelapse_builder.py                      # groups golden_hour frames by date+type,
                                            # builds MP4s when ≥ MIN_FRAMES, writes
                                            # /highlights/timelapse_manifest.json
```

Viewer votes arrive via `vote-server` (port 8765) → `/highlights/votes.json` → applied as score adjustments by `score_images.py` (net upvote = +0.5 pts, max 100).

## Sky / Astronomy Tools

**star-patrol/star_patrol.py** — two modes, run directly on the NAS (not in Docker):
```bash
# Nightly astronomical PTZ sweep (Moon, planets, named stars)
python3 star-patrol/star_patrol.py

# Golden-hour sky sweep (self-skips if sun outside -6°…+12° altitude window)
python3 star-patrol/star_patrol.py --golden-scan

# Dry run — print targets without moving camera
python3 star-patrol/star_patrol.py --dry-run

# Calibrate HOME_AZ: moves to pan=0, tilt=45
python3 star-patrol/star_patrol.py --calibrate
```
Requires `CAMERA_IP/USER/PASSWORD`, `LATITUDE`, `LONGITUDE`, `STAR_HOME_AZ` env vars.
Dependencies: `skyfield`, `requests` (see `star-patrol/requirements.txt`).

**panorama-capture.sh** — sweeps PTZ left taking N shots, optionally stitches via `stitch.py`:
```bash
./panorama-capture.sh [shots] [move_sec] [speed] [settle_sec] [out_dir]
# Camera must be at rightmost position first. Default: 4 shots, 5.0s pan, speed 20.
# Wide lens is ~90° HFOV so 4 shots = full 360°; use 5 for better stitch overlap.
```

**ptz-patrol.sh** — sweeps through 8 compass presets via Home Assistant select entity:
```bash
./ptz-patrol.sh [dwell_seconds]   # default 10s per position
```
Requires `HA_TOKEN` in `.env`.

## FFmpeg Pipeline

The `ffmpeg-processor` container runs idle (`tail -f /dev/null`); execute commands via `docker exec`:

```bash
# Timelapse from patrol snapshots
docker exec ffmpeg-processor /scripts/process_media.sh timelapse YYYYMMDD

# Full daily pipeline (timelapse → watermark → stock export → storm reel)
docker exec ffmpeg-processor /scripts/process_media.sh full-pipeline YYYYMMDD

# Convert for stock platform (shutterstock | adobe | pond5)
docker exec ffmpeg-processor /scripts/process_media.sh stock <input> <output> <platform>
```

## MQTT Debugging

```bash
# Subscribe to everything
docker exec mosquitto mosquitto_sub -t '#' -v

# Watch sensor data only
docker exec mosquitto mosquitto_sub -t 'sensors/#' -v

# Watch audio detections (audio-scout)
docker exec mosquitto mosquitto_sub -t 'audio/#' -v

# Publish a test message
docker exec mosquitto mosquitto_pub -t 'sensors/outdoor/temperature' -m '72.5'
```

## InfluxDB Queries

```bash
# Last hour of sensor data
docker exec influxdb influx query '
  from(bucket:"sensor_data")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "state")
  |> filter(fn: (r) => r.entity_id =~ /weather_/)
'
```

InfluxDB org: `ground_truth`, bucket: `sensor_data`.

## Environment Variables

`.env` variables used across services:

| Variable | Used by |
|---|---|
| `NAS_IP` | ptz-patrol.sh, cron-scan-sync.sh, docker-compose defaults |
| `TZ` | homeassistant, highlight-curator, sky-watcher |
| `CAMERA_IP/USER/PASSWORD` | frigate, star-patrol, night-sky-patrol, sky-watcher, panorama-capture.sh |
| `INFLUXDB_USER/PASSWORD/TOKEN` | influxdb, setup.sh grafana provisioning |
| `GRAFANA_USER/PASSWORD` | grafana |
| `HA_TOKEN` | ptz-patrol.sh, night-sky-patrol |
| `LATITUDE/LONGITUDE` | highlight-curator (golden hour calc), star-patrol, night-sky-patrol |
| `GOLDEN_MINUTES` | highlight-curator (±min window around sunrise/sunset, default 45) |
| `MIN_SCORE` | highlight-curator (Frigate confidence threshold, default 0.60) |

## Troubleshooting

```bash
# Test camera RTSP streams directly
ffplay rtsp://admin:PASSWORD@192.168.100.131:554/h264Preview_01_main   # wide
ffplay rtsp://admin:PASSWORD@192.168.100.131:554/h264Preview_02_main   # zoom

# Check MediaMTX active paths
curl http://192.168.100.202:9997/v3/paths/list | python3 -m json.tool

# Frigate high CPU: reduce fps or resolution in frigate/config/config.yml
docker compose restart frigate

# Run the hourly cron sync manually
bash cron-scan-sync.sh
```

## Gotchas

**Deploy HA config with `docker cp`, never `docker exec ... /dev/stdin`** — the stdin method silently empties the target file:
```bash
docker cp ha-automations.yaml homeassistant:/config/automations.yaml
curl -s -X POST http://localhost:8123/api/services/automation/reload \
  -H "Authorization: Bearer $(grep HA_TOKEN .env | cut -d= -f2)" \
  -H "Content-Type: application/json"
```

**HA MQTT broker is UI-only** (Settings → Integrations → MQTT). YAML `broker:`, `port:` keys are invalid since HA 2022.3 and cause `Setup failed for 'mqtt'`.

**Reolink entity IDs** are generated from the camera name in the Reolink app, not `trackmix_*`. Current entity: `camera.high_res_in_the_hill_country_fluent_lens_0`, PTZ select: `select.high_res_in_the_hill_country_ptz_preset`. Renaming the camera in the app breaks all HA entity references.

**PTZ presets require full compass name strings** via `select.select_option`, not numeric `preset_id`. Valid options: `South, Southeast, East, Northeast, North, Northwest, West, Southwest, top centered`. Abbreviated codes (`"S"`, `"NE"`) fail at runtime with an option-validation error.

**`HA_TOKEN` must be a JWT**, not a raw refresh token. If `.env` token returns 401, exchange it:
```bash
curl -X POST http://localhost:8123/auth/token \
  -d "grant_type=refresh_token&refresh_token=RAW_HEX_TOKEN"
```

**`camera_timelapse` volume must not be `:ro`** or `camera.snapshot` can't write files (fails silently).

**`docker compose restart` does NOT pick up a rebuilt image.** After `docker compose build`, use `up -d --force-recreate <service>`.

**`python:3.12-slim` does not include setuptools, and setuptools ≥72 drops `pkg_resources`.** New Python services need `setuptools>=69.0.0,<72.0.0` in requirements.txt or packages like tensorflow-hub that import `pkg_resources` fail with `ModuleNotFoundError: No module named 'pkg_resources'`.

**`/volume1/highlights/` files can only be chmod'd via `docker exec highlight-curator`** — that container owns the mount; running chmod as the current user hits permission denied, and Frigate does not mount that path.

**`dict.get(key, default)` returns None when the key exists with value None** — use `e.get(key) or default` for manifest fields that may have been written as null.

**Frigate recordings are at `/volume1/docker/frigate/media/recordings/`** — `/volume1/frigate/` was a stale empty directory and has been removed (`sudo rmdir /volume1/frigate/trackmix_wide /volume1/frigate/trackmix_zoom /volume1/frigate` if it reappears). On-disk layout is `YYYY-MM-DD/HH/{camera}/{minute}.{duration}.mp4` (camera name is a subdirectory of the hour folder, not the top level).

**Two separate timelapse storage locations** — not duplicates, different producers:
- `/volume1/camera_timelapse/{sunrise,sunset}/` — raw JPEG frames captured by HA automations; also holds FFmpeg-built MP4s and `panoramas/`. Written by `ffmpeg-processor` (container path `/output/timelapse`).
- `/volume1/highlights/timelapse/` — finished timelapse MP4s built by `timelapse_builder.py` inside highlight-curator from the best-scored highlight frames.

**`content_manager.py`** lives in `highlight-curator/`, runs on port **8766**, started manually: `python3 highlight-curator/content_manager.py`

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Audio Scout

**`audio-backfill.py`** — back-analyzes historical MP4s at a CPU-throttled rate:
```bash
python3 audio-backfill.py --cpu-percent 25 /volume1/camera_raw/05072026/
python3 audio-backfill.py --cpu-percent 15 --since 2026-05-01 /volume1/camera_raw/
python3 audio-backfill.py --dry-run /volume1/camera_raw/05072026/
```
Audio manifest: `/volume1/highlights/audio_manifest.json`; WAV clips: `/volume1/highlights/audio/`.
