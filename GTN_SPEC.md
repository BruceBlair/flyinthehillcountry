# GTN NAS Project Spec
# Ground Truth Network — HITHC LLC
# For Claude Code on UGREEN NAS (192.168.100.202)
# Last updated: 2026-06-07
# Read this file at the start of every session before touching anything.

---

## 1. WHO AND WHAT

Operator: Bruce / HighlyReflective  
Entity: High in the Hill Country LLC (HITHC)  
Venture: Ground Truth Network (GTN) / FlyInTheHillCountry  
Domain: highlyreflective.one  
NAS user: HighlyReflective  
NAS IP: 192.168.100.202  
Shutterstock: Approved contributor — first stock pipeline target  

---

## 2. CONFIRMED DIRECTORY MAP

### Weather station working tree
```
/home/HighlyReflective/weather-station/
  manifest.json                  # 1,553 entries, updated 2026-06-07
  weather/                       # 343 photos — general sky/weather scenes
  golden_hour/
    sunrise/                     # 150 photos
    sunset/                      # 150 photos
    golden_hour/                 # 47 photos
  wildlife/                      # 55 entries (bird, bear)
  stars/                         # star shots (dated filenames)
  panoramas/                     # stitched panoramas + thumbnails
  timelapse/                     # compiled MP4 timelapses by date
  ffmpeg/                        # (empty or working dir)
  data/                          # TARGET — create if not exists
    nodes.json                   # live node data (not yet created)
    forecast.json                # NWS forecast (not yet created)
    availability.json            # archive calendar (not yet created)
```

### Camera raw archive
```
/volume1/camera_raw/
  cell footage/                  # 10 cell phone MP4s, 2026-03-10, 200MB
                                 # PRIORITY: anvil cloud, lightning, Cessna
  MMDDYYYY/                      # EasyNVR motion clips by date
                                 # Mar 16 – Jun 5, ~27,860 MP4s total
                                 # Filename: "High Res In The Hill CountryCH01-01-HHMMSS-HHMMSS.mp4"
  easynvr_rec/PnyGeSySOTRTW/01/
    YYYYMMDD/                    # Dense EasyNVR coverage
                                 # 2026-03-31 through 2026-04-19
                                 # ~1,400 files/day = near-continuous
  #recycle/                      # DO NOT TOUCH — deleted files
                                 # Contains 439 Mar 16 clips — potentially recoverable
  CacheSnap/                     # Camera SDK cache — ignore
  preset-snap/                   # PTZ preset thumbnails — ignore
  timelapse/                     # Reolink-generated timelapses (89 active MP4s)
  timelapse-covers/              # Thumbnail covers — ignore
```

### Frigate
```
/volume1/frigate/
  recordings/                    # Frigate MP4 segments (inside container: /media/frigate/recordings/)
  clips/                         # Event snapshots JPEGs
```
Frigate config: `/volume1/docker/frigate/config/config.yml`  
Frigate API: `http://192.168.100.202:5000/api/`  
Camera: trackmix_wide + trackmix_zoom (Reolink TrackMix at 192.168.100.131)

### Photo pipeline (CREATE THESE — do not exist yet)
```
/volume1/photo_pipeline/
  incoming/                      # Raw ingest from Frigate events + Reolink
  working/                       # Currently being processed
  processed/                     # Ready for human review
  accepted/                      # Approved, queued for stock upload
  rejected/                      # Excluded from publishing, kept on disk
  published/                     # Confirmed uploaded to Shutterstock etc.
```

### Other
```
/volume1/video_library/          # Final stock-ready video exports
/volume1/camera_raw/cell footage/ # Founding footage — priority stock candidates
```

---

## 3. VIDEO ARCHIVE — COVERAGE PHASES

Three phases. Be honest about what each is in any UI.

```
Phase 1: FOUNDING
  Start:  2026-03-10
  End:    2026-03-15
  Source: /volume1/camera_raw/cell footage/
  Type:   Handheld cell phone, pre-installation
  Count:  10 MP4s, 200MB
  Notes:  Anvil cumulonimbus, lightning storm, Cessna flyby
          HIGHEST PRIORITY stock candidates in entire archive

Phase 2: SPARSE
  Start:  2026-03-16
  End:    2026-06-05
  Sources:
    EasyNVR date folders: /volume1/camera_raw/MMDDYYYY/
    EasyNVR dense:        /volume1/camera_raw/easynvr_rec/PnyGeSySOTRTW/01/YYYYMMDD/
    Frigate events:       via API /api/events (102 events, Mar 24 – May 8)
    Frigate motion:       via API /api/recordings/summary
  Type:   Motion-triggered, intermittent
  Count:  ~27,860 EasyNVR clips + 102 Frigate event clips

Phase 3: CONTINUOUS
  Start:  2026-06-06
  End:    ongoing
  Source: Frigate /volume1/frigate/recordings/
  Type:   Full continuous 24/7 recording, both lenses
  Config: record.continuous.days = 30, mode = all (set 2026-06-06)
  Storage: ~40-60 GB/day, 21TB free (~1 year headroom)
```

---

## 4. MANIFEST SCHEMA — CURRENT STATE

File: `/home/HighlyReflective/weather-station/manifest.json`  
Entries: 1,553  
Updated: 2026-06-07T11:00:26  

### Current fields (all entries)
```json
{
  "timestamp": "20260319_090720",
  "label": "scene",
  "categories": ["weather"],
  "snapshot": "weather/20260319_090720_scene_camera_raw.jpg",
  "clip": null,
  "source": "disk-repair",
  "flags": {
    "crop": false,
    "enhance": false,
    "auth_hold": false
  },
  "uploads": {},
  "nice_shot": 31.0,
  "votes": {"up": 0, "down": 0}
}
```

### Fields to ADD (migration needed)
```json
{
  "status": "pending",
  "stock_priority": null,
  "published_to": {
    "shutterstock": null,
    "adobe_stock": null
  },
  "ai_keywords": [],
  "ai_description": "",
  "weather_at_capture": null
}
```

### Current field notes
- `nice_shot`: auto-ranking score, range 0.2–78.6, nothing above 80 yet
- `votes`: manual up/down thumbs, only 1 entry has votes (up:2, down:0)
- `uploads`: always empty — stock pipeline not wired yet
- `status`: does not exist yet — needs migration
- `source` values: backfill_scene, disk-repair, backfill_raw, backfill, null
- `label` values: scene, sunrise_scene, sunset_scene, golden_hour, bird, bear, trackmix
- `categories` values: weather, golden_hour, golden_hour/sunrise, golden_hour/sunset, wildlife

### Special entries — cell footage (PRIORITY)
These 10 entries need manual tagging before AI keyword pass:
- Timestamps: 20260310_201952 through 20260310_202658
- Manual tags to add: anvil_cloud, cumulonimbus, lightning_storm, hill_country_ridge
- The Cessna clip needs identification — review all 10 and tag
- Set `stock_priority: "high"` and `status: "pending_review"` on all 10

---

## 5. JSON FILES FOR GITHUB PAGES

All three files live in: `/home/HighlyReflective/weather-station/data/`  
Create this directory if it does not exist.  
These files are pushed to GitHub repo on a cron schedule.

### nodes.json
```json
{
  "updated": "2026-06-07T14:32:00Z",
  "nodes": [
    {
      "id": "HITHC-RIDGE-N",
      "label": "North Ridge",
      "status": "active",
      "lat": null,
      "lon": null,
      "elevation_ft": null,
      "has_camera": true,
      "camera_snapshot_url": "snapshots/HITHC-RIDGE-N-latest.jpg",
      "current": {
        "timestamp": null,
        "temp_f": null,
        "humidity_pct": null,
        "pressure_msl_inhg": null,
        "wind_speed_mph": null,
        "wind_dir_deg": null,
        "wind_gust_mph": null,
        "rain_rate_in_hr": null,
        "rain_daily_in": null,
        "battery_pct": null,
        "rssi_dbm": null
      }
    },
    {
      "id": "HITHC-RIDGE-W",
      "label": "West Ridge",
      "status": "planned",
      "lat": null,
      "lon": null,
      "elevation_ft": null,
      "has_camera": false,
      "current": null,
      "notes": "Node placement target — weather only"
    },
    {
      "id": "HITHC-RIDGE-NW",
      "label": "Northwest Ridge",
      "status": "planned",
      "lat": null,
      "lon": null,
      "elevation_ft": null,
      "has_camera": false,
      "current": null,
      "notes": "Node placement target — weather only"
    }
  ]
}
```
NOTE: lat/lon/elevation_ft for RIDGE-N need to be filled in from GPS.  
Status values: active, deploying, planned, offline

### forecast.json
```json
{
  "updated": "2026-06-07T14:00:00Z",
  "source": "NWS",
  "node_id": "HITHC-RIDGE-N",
  "periods": []
}
```
Fetch from NWS API (free, no key):  
Step 1: `https://api.weather.gov/points/{lat},{lon}` → get gridId, gridX, gridY  
Step 2: `https://api.weather.gov/gridpoints/{gridId}/{gridX},{gridY}/forecast`

### availability.json
```json
{
  "updated": "2026-06-07T00:00:00Z",
  "coverage_phases": [
    {
      "start": "2026-03-10",
      "end": "2026-03-15",
      "type": "founding",
      "description": "Pre-installation handheld footage"
    },
    {
      "start": "2026-03-16",
      "end": "2026-06-05",
      "type": "sparse",
      "description": "Motion-triggered, intermittent coverage"
    },
    {
      "start": "2026-06-06",
      "end": null,
      "type": "continuous",
      "description": "Full continuous recording"
    }
  ],
  "dates": {
    "2026-03-10": {
      "photos": false,
      "weather": false,
      "video_continuous": false,
      "video_events": false,
      "video_founding": true,
      "timelapse": false
    }
  }
}
```
The `dates` object is built by scanning all five sources:  
1. EasyNVR: `/volume1/camera_raw/MMDDYYYY/` — any MP4 = video_events true  
2. EasyNVR dense: `/volume1/camera_raw/easynvr_rec/PnyGeSySOTRTW/01/YYYYMMDD/`  
3. Frigate API: `GET /api/recordings/summary` — returns date dict  
4. Timelapse: `/volume1/camera_raw/timelapse/` — any MP4 = timelapse true  
5. Photos: manifest.json entries by date — any entry = photos true  
6. Cell footage: `/volume1/camera_raw/cell footage/` — 2026-03-10 only  

Weather data start date: UNKNOWN — query InfluxDB first() to determine.  
Update `availability.json` weather flags once confirmed.

---

## 6. DOCKER STACK ON NAS

All containers running under UGOS Pro Docker:
```
Mosquitto     MQTT broker — all sensor telemetry
InfluxDB      Time series DB, infinite retention
Grafana       Visualization
Frigate       AI camera detection
              API at http://192.168.100.202:5000/api/
              OpenVINO inference
              detect.enabled = true (re-enabled 2026-06-06)
              continuous recording = ON (set 2026-06-06, days=30)
Home Assistant Automation + alert routing
ffmpeg        Media processing
```

InfluxDB org: ground_truth  
InfluxDB bucket: sensor_data  
InfluxDB token: stored in .env (INFLUXDB_TOKEN)  
Ecowitt GW3000 → python-ecowitt → Mosquitto → InfluxDB → Grafana  

Weather data start dates (confirmed 2026-06-08):  
  - Ecowitt on-site sensors (local readings): 2026-06-05T07:08:16Z  
  - HA external weather integration (NWS/cloud): 2026-04-28T04:19:40Z  
  - For nodes.json current conditions: use Ecowitt data (measurements named by unit: °F, mph, inHg, %, etc., _field=value)  

---

## 7. GITHUB PAGES SITE STRUCTURE

Three sections on the public site:

### Section 1: Landing page
- GTN manifesto
- Graphics + design (not yet built)
- Links to gallery and GTN demo

### Section 2: Photo/video gallery
- Fed by NAS publish pipeline
- Sourced from manifest.json accepted entries

### Section 3: GTN demo page
- Live weather ticker (nodes.json, auto-refresh)
- Leaflet.js map with USGS topo base tiles
- Node markers (active=filled, planned=dashed)
- Wind arrows (SVG, rotated to wind_dir_deg)
- NWS forecast overlay (toggle, semi-transparent)
- Camera snapshot on node click
- Availability calendar (availability.json)
- Update cycle: NAS pushes JSON to GitHub every 5 minutes via cron

### Map tile source (free, no API key)
USGS National Map topo:  
`https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}`

### NWS API (free, no key required)
Point lookup: `https://api.weather.gov/points/{lat},{lon}`  
Forecast: `https://api.weather.gov/gridpoints/{office}/{x},{y}/forecast`

---

## 8. SHUTTERSTOCK PIPELINE (BUILD THIS FIRST)

Flow:
```
manifest entry (status=accepted)
  → pull weather_at_capture from InfluxDB by timestamp
  → AI keyword + description generation
  → Shutterstock API upload (multipart POST)
  → Shutterstock metadata submit
  → poll submission status
  → on success: set status=published, published_to.shutterstock=submission_id
```

Weather enrichment query: match entry timestamp to nearest InfluxDB reading.  
AI keywords: scene content + location (Hill Country ridge) + weather conditions at capture.  
Each stock site has different requirements — build Shutterstock first, then Adobe Stock, then others.  
Auto-publish toggle: stored as a config flag, not hardcoded.

---

## 9. TASK PRIORITY ORDER

Do these in order. Do not start a later task until the earlier one is confirmed working.

1. ~~Create `/home/HighlyReflective/weather-station/data/` directory~~ ✓ DONE 2026-06-08
2. ~~Confirm InfluxDB bucket name and weather data start date (first() query)~~ ✓ DONE 2026-06-08 (org=ground_truth, bucket=sensor_data, Ecowitt start=2026-06-05)
3. ~~Write script: InfluxDB → nodes.json → git push (cron every 5 min)~~ ✓ DONE 2026-06-08 (push-nodes.py, cron */5)
4. ~~Write script: NWS API → forecast.json → git push~~ ✓ DONE 2026-06-08 (push-forecast.py, cron */30, EWX/142,79)
5. ~~Write script: scan all video sources → availability.json → git push~~ ✓ DONE 2026-06-08 (push-availability.py, cron daily 00:05, 91 dates / 79 covered)
6. ~~Add `status` and `published_to` fields to all manifest entries (migration)~~ ✓ DONE 2026-06-08 (migrate-manifest.py, 1615 entries, idempotent)
7. ~~Tag cell footage entries manually (stock_priority=high, anvil/lightning/cessna labels)~~ ✓ DONE 2026-06-08 (tag-cell-footage.py; 8 entries created, all 10 tagged; 202358 = lightning flash at anvil base NOT Cessna; Cessna clip still unidentified — review remaining 9 clips and add cessna/aircraft/flyby keywords manually)
8. ~~Create `/volume1/photo_pipeline/` directory tree~~ ✓ DONE 2026-06-08 (incoming, working, processed, accepted, rejected, published)
9. ~~Wire Shutterstock upload pipeline~~ ✓ DONE 2026-06-08 (shutterstock-upload.py + shutterstock-auth-setup.py; client_credentials→refresh_token upgrade complete; run shutterstock-auth-setup.py once in browser to populate SHUTTERSTOCK_REFRESH_TOKEN in .env, then upload pipeline is fully operational)
10. ~~Build GitHub Pages display (weather ticker + Leaflet map)~~ ✓ DONE 2026-06-08 (gtn.html: ticker, Leaflet USGS topo map, node markers + wind arrows, NWS forecast panel, availability calendar; added GTN Live link to index.html nav)

---

## 10. RULES

- Never hardcode tokens, passwords, or API keys — use environment variables or config file
- Never touch `/volume1/camera_raw/#recycle/` — deleted files, potentially recoverable
- Never reformat SD cards or modify camera hardware settings
- The manifest.json is the source of truth for photo pipeline state — do not duplicate it
- Data rights: HITHC retains all rights to all telemetry — no external transfer without explicit agreement
- Stock pipeline: Shutterstock first, then Adobe Stock, then others with APIs, then manual
- The cell footage from 2026-03-10 is founding footage — treat as highest priority archive asset
- Before writing any new script, check if one already exists that does the same thing

---

## 11. WHAT DOES NOT EXIST YET

- ~~`/home/HighlyReflective/weather-station/data/` directory~~ ✓ DONE 2026-06-08
- ~~nodes.json, forecast.json, availability.json~~ ✓ DONE 2026-06-08
- ~~`/volume1/photo_pipeline/` directory tree~~ ✓ DONE 2026-06-08
- ~~status field in manifest entries~~ ✓ DONE 2026-06-08
- ~~Shutterstock upload pipeline~~ ✓ DONE 2026-06-08 (needs one-time auth-setup.py run)
- GitHub Pages site (landing page + demo page)
- InfluxDB → JSON push script
- lat/lon/elevation_ft for HITHC-RIDGE-N node

---

*End of spec. Read this file before starting any session.*
