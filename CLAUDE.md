# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Deployment

```bash
# First-time setup
cp .env.example .env   # fill in credentials first

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
- `host` network: homeassistant, frigate, mediamtx, sky-watcher, audio-scout, nginx-ssl (require direct LAN access or avoid bridge NAT)

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
| nginx-ssl | host | nginx:alpine |

## Config Files

Runtime configs for `mosquitto`, `homeassistant`, `grafana`, `mediamtx`, and `nginx` live directly under each service's own directory at the repo root (e.g. `homeassistant/config/configuration.yaml`, `mosquitto/config/mosquitto.conf`) and are edited in place — there is no separate templating step. These directories are filesystem copies, not git-tracked (see `.gitignore`).

Frigate's config is not part of this repo at all: its docker-compose mount (`/volume1/docker/frigate/config:/config`) is an absolute host path outside the repo tree.

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
| `INFLUXDB_USER/PASSWORD/TOKEN` | influxdb, grafana provisioning |
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

**HA `configuration.yaml` MUST set `homeassistant: unit_system: us_customary` explicitly.** Without it, HA's unit system can end up Metric (e.g. after an onboarding-wizard replay), and the built-in `ecowitt` integration's `_new_sensor()` filter (`homeassistant/components/ecowitt/sensor.py`) silently refuses to (re)create any imperial-typed sensor (temperature °F, wind speed/gust mph, pressure inHg) on every reload/restart — while dimensionless types (humidity %, wind_direction °) are unaffected since they aren't unit-gated. Symptom: those 4 fields frozen/`unavailable` on all Ecowitt stations despite confirmed-live upstream payloads, surviving both config-entry reload and full container restart. Diagnose by comparing entity-registry duplicates: a station whose entity_id was already taken under the old unit system gets an auto-suffixed `_2` shadow entity in the new unit — if the `_2` variant is fresh and the original is frozen, this is the cause.

**`python:3.12-slim` does not include setuptools, and setuptools ≥72 drops `pkg_resources`.** New Python services need `setuptools>=69.0.0,<72.0.0` in requirements.txt or packages like tensorflow-hub that import `pkg_resources` fail with `ModuleNotFoundError: No module named 'pkg_resources'`.

**`/volume1/highlights/` files can only be chmod'd via `docker exec highlight-curator`** — that container owns the mount; running chmod as the current user hits permission denied, and Frigate does not mount that path.

**`dict.get(key, default)` returns None when the key exists with value None** — use `e.get(key) or default` for manifest fields that may have been written as null.

**Frigate recordings are at `/volume1/docker/frigate/media/recordings/`** — `/volume1/frigate/` was a stale empty directory and has been removed (`sudo rmdir /volume1/frigate/trackmix_wide /volume1/frigate/trackmix_zoom /volume1/frigate` if it reappears). On-disk layout is `YYYY-MM-DD/HH/{camera}/{minute}.{duration}.mp4` (camera name is a subdirectory of the hour folder, not the top level).

**Two separate timelapse storage locations** — not duplicates, different producers:
- `/volume1/camera_timelapse/{sunrise,sunset}/` — raw JPEG frames captured by HA automations; also holds FFmpeg-built MP4s and `panoramas/`. Written by `ffmpeg-processor` (container path `/output/timelapse`).
- `/volume1/highlights/timelapse/` — finished timelapse MP4s built by `timelapse_builder.py` inside highlight-curator from the best-scored highlight frames.

**`hithc-gtn-depot` has no GitHub remote of its own** — the live site repo is a separate clone. `push-site.sh` rsyncs `site/` into `/volume1/senselayer-pages-repo`, a clone of `github.com/BruceBlair/ground-truth-gallery` (GitHub Pages source, branch `main`, custom domain `senselayer.io`). Don't look for site deploy history in this repo's own git log — check `ground-truth-gallery` instead.

**Cloudflare MCP plugin (`cloudflare@cloudflare`) OAuth grants DNS *read* scope only by default** — write attempts fail with `10000: Authentication error` even after the browser consent flow completes successfully. DNS record changes currently have to be made manually in the Cloudflare dashboard, not via the MCP `execute` tool, unless the OAuth flow is redone with DNS-edit explicitly granted.

## senselayer.io DNS & Domain Portfolio

`senselayer.io` DNS is authoritative on Cloudflare (zone `e688f7d9ad14450257c1610d8e2ebe64`, account `Blair.bruce@gmail.com's Account`; nameservers `bart`/`elinore`.ns.cloudflare.com; registrar is still Namecheap). As of 2026-07-20:
- Apex + `www` are proxied records pointing at GitHub Pages — A: `185.199.108-111.153`, AAAA: `2606:50c0:8000-8003::153`, `www` CNAME → `bruceblair.github.io` — serving `BruceBlair/ground-truth-gallery`.
- MX/SPF/DMARC still use legacy Namecheap email forwarding (`eforward1-5.registrar-servers.com`, SPF `include:spf.efwd.registrar-servers.com`), left untouched during the DNS repoint.
- Unlike every other zone in the same Cloudflare account (~26 other domains, mostly brand-defensive registrations like `flyinthehillcountry.*`, `highinthca.*`, `highlyreflective.*`), `senselayer.io` has **no DKIM record** and DMARC is `p=none` (monitor-only, not enforced) — the other zones all use Cloudflare Email Routing with DKIM present and `p=quarantine`. This shows up as dashboard warnings; migrating `senselayer.io` to Cloudflare Email Routing would fix it but changes mail delivery, so it's pending a decision, not yet done.
- `highestinthehillcountry.com` (same account) also still points at the Namecheap parking page — flagged but out of scope, not fixed.

## Analytics (GA4 + Cloudflare Web Analytics)

`site/assets/nav.js` has an `ANALYTICS` config block (top of file) with `ga4MeasurementId`/`cfBeaconToken` — since every page loads `nav.js`, filling in an ID activates tracking site-wide with no other file edits (`loadAnalytics()` no-ops on empty strings). Both are now filled in and **live as of 2026-08-13**: `ga4MeasurementId: "G-HLK9H7WMX9"`, plus a Cloudflare Web Analytics beacon token for the same zone. `cloudflare-analytics/traffic-report.sh` pulls 7-day requests/pageviews/uniques/top-country straight from the Cloudflare GraphQL API as a second, no-account-needed data source alongside GA4.

**The wiring sat finished-but-unmerged on a branch for days before going live** — the three commits that built the loader and filled in both IDs (`e1f78b0e5`, `6ba751d77`, `e951b7253`, dated Aug 8-9) were made on `worktree-add-tracking-analytics`, never merged to `master`, so GA collected zero data despite looking fully configured in that branch. Cherry-picked onto `master` and deployed via `push-site.sh` on 2026-08-13. **Lesson: a locked worktree branch with real, complete-looking commits is not the same as deployed** — when investigating "is X actually live," check what `master`/the deployed artifact contains, not just what exists somewhere in the repo's branches. Verify a live change by re-fetching the actual served asset (`curl` the site URL, check `last-modified`) rather than trusting the source diff alone.

## Photo Sales Gallery (site/photo-sales.html)

A static, manifest-driven gallery replacing the old "coming soon" stub:
- `site/photos/manifest.json` — `{file, category}[]`, one entry per photo (`file` is the basename with no extension; both `thumb/` and `full/` use `<file>.jpg`). Regenerate this whenever the photo set changes; `gallery.js` reads it at page load and does not hardcode any filenames.
- `site/photos/thumb/*.jpg` and `site/photos/full/*.jpg` — pre-resized with ImageMagick before ever touching git: `convert -auto-orient -strip -resize 'WxH>' -quality Q -sampling-factor 4:2:0 [-interlace Plane] in out.jpg` (full: 1920px/q82, thumb: 480px/q75). Never commit originals straight from `/volume1/top_100_approved/` — a 106MB source set reduces to ~21MB this way.
- `site/assets/gallery.js` — renders the grid + a click-through lightbox (prev/next, Esc/arrow-key nav). Grid items interpolate `p.file`/`p.category` from the manifest, so they're built with `document.createElement`/`.textContent`, not template-string `innerHTML` — a `PostToolUse:Write` security hook flags `innerHTML` with interpolated data as XSS-risk. The lightbox's own static shell markup (no interpolated data) is fine as a plain `innerHTML` assignment.

**Publishing a large photo batch without saturating the link**: don't push it as one commit. `push-site.sh`'s rsync-mirror step makes partial `site/photos/` contents at push time naturally produce an incremental commit, so split large photo drops into several sequential `git commit` + `push-site.sh` runs (e.g. thumbnails+page first, then full-res in 2-3 batches), with a short pause (`ScheduleWakeup` or `sleep`) between the full-res batches. This was done for the initial 51-photo launch: 4 commits (4bce92f→d5a0751 in this repo, mirrored 1a3d762→de5e0b9 in `ground-truth-gallery`) instead of one ~21MB push.

**Verifying a deploy when `senselayer.io` itself is flaky**: use `raw.githubusercontent.com/BruceBlair/ground-truth-gallery/main/<path>` to check pushed file content directly — it bypasses the custom domain, Cloudflare, and the Pages build/serving layer entirely, so it can confirm a push succeeded even while the domain is mid-DNS-work or otherwise unreachable (see DNS section above for a real instance of this).

**`split -n l/N` needs a real seekable file, not a pipe** — `ls | sort | split -n l/3 -` fails with `split: cannot determine file size`. Write the list to a file first (`... > all.txt`), then `split -n l/3 -d --additional-suffix=.list all.txt batch_`.

## Live Demo Pages (Weather / Flood / Wildlife / Flight)

Four `site/demos/*.html` pages fetch `/data/*.json` client-side (plain `fetch`, no build step, `site/assets/live-data.js` has shared helpers — `fetchJSON`, `formatAge`, `isStale`/`showStaleBanner`, `renderNodeMap`). Each page's JS re-fetches on a `setInterval` so it stays live without a manual reload.

- `push-nodes.py`/`push-forecast.py` → weather-monitoring.html (pre-existing)
- `push-flood.py` → flood-monitoring.html
- `push-flight-conditions.py` → flight-routing.html (pure derivation from `nodes.json`, no new sensor query)
- `push-wildlife.py` → wildlife.html
- `push-external-stations.py` (added 2026-07-26) → weather-monitoring.html's map, plus the static hand-curated `data/preferred-locations.json` (no push script) for proposed future node sites

See GTN_SPEC.md §5 for the JSON schemas. `renderNodeMap()` in `live-data.js` takes an optional 5th `kindOf` arg (`native`/`external`/`preferred`) — weather-monitoring.js is the only caller that uses it; flood/flight/wildlife pages omit it and get the old all-native rendering unchanged.

**Ecowitt.net's public station map has no official "nearby stations" API** — only Weather Underground's PWS API does (`api.weather.com/v3/location/near?product=pws`, official and documented). Confirmed 2026-07-25 by reading Ecowitt's actual cloud API docs: every endpoint is scoped to devices registered to your own account (`application_key`/`api_key` + device IMEI/MAC), there's no discovery endpoint for other users' public stations. `push-external-stations.py` therefore only pulls from Wunderground (needs `WU_API_KEY` in `.env`, no-ops cleanly without one); Ecowitt foreign-node scraping was deliberately not built — the only way to get that data would be scraping their map's undocumented internal endpoint, which is fragile and a likely ToS problem for a site that would redistribute it continuously. If Ecowitt ever ships a real API for this, add a second branch — the `external-stations.json` schema already has a `network` field and `networks_configured.ecowitt` sitting at `false` waiting for it.

**Cron for `push-*.py` scripts lives only in `crontab -l`, not in this repo** — `cron-scan-sync.sh` is a separate hourly job for the highlight-curator scan/sync pipeline (see its own header), not a registry of all cron entries. When adding a new push script's schedule, add it directly via `crontab -e`/`crontab -l | ... | crontab -`; there's no repo file that reflects the true cron state, so `crontab -l` is the only source of truth.

## HA Command Center Dashboard

`homeassistant/config/dashboards/command-center.yaml` is a YAML-mode Lovelace dashboard registered via the `lovelace: dashboards:` block in `configuration.yaml` (2026-07-25), sitting alongside the untouched auto-generated default "Overview" dashboard rather than replacing it. Views: Overview (storm status, camera, quick toggles), Weather (North Ridge/`gw3000b_*`, Valley East/`southside1_*`, South Ridge/`ecowitt_station_2_*` — see the entity-slug gotcha above for why the prefixes don't match the device names), Soil & Flood, Camera & PTZ, Sky & Automations, System. Uses only stock Lovelace card types (`entities`, `glance`, `picture-glance`, `picture-entity`, `markdown`) — no HACS/custom cards are installed. Edit the YAML file directly and `docker compose restart homeassistant` to pick up changes (or `homeassistant.reload_core_config`/reload via the UI if just tweaking cards).

**`push-site.sh` didn't sync `data/` at all until 2026-07-23** — it only rsynced `site/` into the pages repo, so `nodes.json`/`forecast.json`/`availability.json` were never actually reaching senselayer.io despite the cron faithfully updating them every 5-30 min. Fixed by adding a second rsync pass (`$DATA_SRC` → `$PAGES_REPO/data/`, excluding `wildlife-curated.json` since that's an internal curation input, not published data). If a new push-*.py script's JSON isn't showing up live, check this rsync step exists and isn't excluding it — don't assume the script itself is broken.

**`push-nodes.py`/`push-forecast.py`/`push-flood.py`/etc.'s own internal `git commit`+`push` always fails** (`hithc-gtn-depot` has no remote — see DNS/deploy section above) — this is expected and harmless, the JSON write already happened before the git step. The newer scripts (`push-flood.py`, `push-flight-conditions.py`, `push-wildlife.py`) check `git remote` first and skip the push attempt silently instead of spamming `ERROR: Command 'git push' returned non-zero exit status 1` every cycle; the older ones (`push-nodes.py`, `push-forecast.py`, `push-availability.py`) still spam that error and haven't been touched to match — cosmetic log noise only, not a functional bug.

**GitHub Pages' legacy build pipeline can silently wedge** — found 2026-07-23: builds had been failing/stuck since 2026-07-20 (2.5+ days), but `senselayer.io` kept serving 200 OK with 3-day-stale content the whole time (GH Pages serves the last good build when a new one fails, so nothing *looks* broken from the outside — check `last-modified` in the response headers, not just the status code). Recovery: `gh api -X POST repos/BruceBlair/ground-truth-gallery/pages/builds` to force a fresh build, then poll `gh api repos/BruceBlair/ground-truth-gallery/pages/builds/latest --jq .status` until it's `built` (not `queued`/`building`). Worth an occasional spot-check (`curl -sI https://senselayer.io/ | grep last-modified` vs. the last known push time) since the hourly cron gives no signal when this happens.

**Soil-moisture probe is picked up redundantly by all 3 Ecowitt gateways over RF** (`southside1`, `eastside_1`, `top_of_the_hill_station` all reported identical `soil_moisture_1..5`/`soil_battery_1..5` values within 1-4s of each other every cycle, confirmed 2026-07-23) — only one physical probe cluster exists (paired with Valley East / `southside1`), but its RF broadcast reaches the other two nearby gateways too, so each forwards it into its own HA device. Devices can't be deleted outright (`eastside_1`/`top_of_the_hill_station` host real rain/wind/temp entities for those physical stations); instead the 20 duplicate `soil_moisture_*`/`soil_battery_*` entities on those two devices were disabled in the entity registry 2026-07-25 (`disabled_by: user`), leaving only `southside1`'s soil entities live — matches what `push-flood.py` already treated as canonical.

**Each Ecowitt device has TWO entity_id slugs, one dead** — a leftover from the `unit_system` drift-to-Metric bug (see the imperial/metric fix above): while HA's unit system was wrong, the `ecowitt` integration created a second, metric-typed sensor for every imperial field, and HA slugs new entities off the device's *name at creation time*. Since the device had already been renamed for two of the three stations by the time the metric entities got created, the dead metric twins ended up under a completely different entity_id prefix than the live ones, not just a `_2` suffix:
  - North Ridge: live data is `sensor.gw3000b_*` (old pre-rename slug); the entire `sensor.top_of_the_hill_station_*` prefix is the dead metric twin.
  - South Ridge: live data is `sensor.ecowitt_station_2_*`; the entire `sensor.eastside_1_*` prefix is the dead metric twin.
  - Valley East: live and dead share the same prefix, `sensor.southside1_*` — the dead ones are the `_2`-suffixed ones (except `soil_moisture_2`/`soil_battery_2`, which are real channel-2 soil readings, not duplicates — don't disable those).
  `push-flood.py`'s `rain_prefix`/`soil_prefix` config already uses the correct live prefixes (`gw3000b`, `southside1`, `ecowitt_station_2`) — this was a display/registry cleanliness problem, not a data-pipeline bug. All 40 dead cross-station entities + 18 dead `southside1_*_2` entities + the 20 duplicate soil entities above (78 total) were disabled 2026-07-25. A stray `sensor.gw2000a_outdoor_temperature` (an orphaned single entity from an earlier discarded device) was disabled the same pass.
  If re-doing this cleanup: stop the `homeassistant` container before editing `.storage/core.entity_registry` directly (it's root-owned; use a throwaway `docker run -v ...:/target alpine cp ...` if you don't have sudo), then restart — editing while HA is running risks it overwriting your change on its own save cycle. To re-find dead entities after a similar drift, query the recorder DB for sensors whose latest state is `unavailable` and hasn't moved since the last restart timestamp — that pattern reliably flags these ghosts.

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
