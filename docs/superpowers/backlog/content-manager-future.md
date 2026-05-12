# Content Manager — Future Work

## 1. Camera Reservation System

**Problem:** Live PTZ timelapses, sky-watcher sweeps, and star-scanner all move the camera. They need to coordinate so they don't trample each other.

**Design notes:**
- A lightweight lock — a JSON file at `/tmp/camera_reserved.json` (or MQTT topic) with `{owner, reason, reserved_until}` fields
- All camera-moving services check this before starting and back off if held by something else
- content_manager UI shows a "Camera Reserved" badge with owner/reason when lock is held
- Caller can mark a reservation as `authorized_interrupt: true` to override lower-priority holds
- Services: sky-watcher, star-scanner, content_manager (timelapse build), panorama-capture.sh

---

## 2. Live PTZ Panoramic Timelapse

**Problem:** Retroactive Frigate extraction only gets what the camera happened to be pointing at. Doesn't help for full-scene panoramic coverage.

**Design notes:**
- At each frame interval, command camera through N compass stops (4 × ~90° = 360°)
- Capture a still at each stop (Frigate snapshot API or direct RTSP frame)
- Optionally stitch 4 frames into a panoramic strip for that timestamp
- Requires camera reservation lock (feature 1) before starting
- Frame timing will be "lumpy" — move+settle takes seconds per stop. 4 stops × ~6s = ~25s minimum round-trip. Interval must be longer than round-trip time or frames will drop. This is fine and expected.
- Lens warping: wide lens is ~90° HFOV; use center crop of each shot and overlap stops slightly (e.g., 80° spacing) to reduce edge distortion before stitching
- Absolute PTZ coordinates (direct Reolink API `ptzctrl` endpoint) are faster than HA preset name round-trips — use these for timed moves

**New UI controls needed (Timelapse tab):**
```
Mode: [Golden Hour] [Full Day] [Custom Range] [Panoramic PTZ]  ← new

Panoramic PTZ mode:
  Date/time start: [2026-05-11 19:00]   Duration: [30] min
  Stops: [4 ▼]   Settle time: [2] s   Stitch: [Yes / No]
  → ~1 frame every 28s, ~64 panoramic frames, video ~7s
  [Reserve Camera + Start]
```

**Files to create/modify:**
- New: `ptz_capture.py` — moves camera to positions, captures frames, optionally stitches
- New: `camera_lock.py` — shared reservation lock (file-based, importable by all services)
- Modify: `content_manager.py` — panoramic mode in Timelapse tab, reservation status in topbar
- Modify: `sky-watcher/sky_watcher.py` — check camera_lock before starting
- Modify: `star-patrol/star_patrol.py` — check camera_lock before starting

---

## 3. Scouting-Aware Time Window Warning

**Problem:** If the user picks a retroactive Frigate extraction window that overlaps with a scouting session, the timelapse will have frames of the camera moving around, not a static scene.

**Design notes:**
- Log scouting session start/end times to `/volume1/highlights/scout_log.json` (star-patrol writes on start/stop)
- When user picks a window in content_manager Timelapse tab, check for overlapping scout sessions
- Show a yellow warning: "⚠ Camera was scanning during part of this window (19:00–19:45). Frames may show camera movement."
- User can still proceed

---

## 4. Scheduling

**Problem:** Panoramic PTZ timelapses need to start at a specific time (e.g., sunset minus 30 min), which requires scheduling.

**Design notes:**
- Simple cron-style scheduling stored in `/volume1/highlights/timelapse_schedule.json`
- content_manager Status tab shows upcoming scheduled builds
- A lightweight scheduler daemon (or cron job calling content_manager via API) triggers builds
- Scheduled builds acquire camera reservation with appropriate priority
