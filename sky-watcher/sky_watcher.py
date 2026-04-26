#!/usr/bin/env python3
"""
sky_watcher.py — Ground Truth Network
Adaptive sky monitor: polls sky quality, triggers panorama capture when
skies are interesting, and builds weather-event timelapse videos.

Adaptive interval:
  score < 40    → sleep POLL_LOW_MIN  (10 min)
  score 40–59   → sleep POLL_MED_MIN  (5 min)
  score ≥ 60    → trigger panorama, sleep POLL_HIGH_MIN (5 min)
  score ≥ 70    → trigger panorama + enter burst-still mode

Burst mode:
  - Grabs a still every BURST_INTERVAL_SEC while score ≥ SCORE_BURST_CONTINUE
  - Continues up to MAX_BURST_MIN minutes
  - When done, compiles frames → timelapse MP4 via ffmpeg
  - Updates weather_timelapse_manifest.json
  - Publishes MQTT cameras/events/sky_timelapse

Output paths (all under HIGHLIGHTS_DIR):
  panoramas/<ts>.jpg                    — stitched panorama
  panoramas/<ts>_thumb.jpg              — 16:9 centre-crop thumbnail
  weather_timelapse/<ts>_timelapse.mp4  — burst-still timelapse
  weather_timelapse/<ts>_thumb.jpg      — mid-burst thumbnail
  pano_manifest.json
  weather_timelapse_manifest.json
"""

import io
import json
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt
import requests
from PIL import Image
import numpy as np

# ── Config ───────────────────────────────────────────────────────────────────
FRIGATE_API    = os.getenv("FRIGATE_API",    "http://frigate:5000")
CAMERA_NAME    = os.getenv("CAMERA_NAME",    "trackmix_wide")
CAMERA_IP      = os.getenv("CAMERA_IP",      "192.168.100.131")
CAMERA_USER    = os.getenv("CAMERA_USER",    "admin")
CAMERA_PASS    = os.getenv("CAMERA_PASSWORD","")
MQTT_HOST      = os.getenv("MQTT_HOST",      "mosquitto")
MQTT_PORT      = int(os.getenv("MQTT_PORT",  "1883"))
HIGHLIGHTS_DIR = Path(os.getenv("HIGHLIGHTS_DIR", "/highlights"))

SCORE_PANO           = float(os.getenv("SCORE_PANO",    "60"))
SCORE_BURST          = float(os.getenv("SCORE_BURST",   "70"))
SCORE_BURST_CONTINUE = float(os.getenv("SCORE_BURST_CONTINUE", "55"))
POLL_LOW_MIN         = int(os.getenv("POLL_LOW_MIN",    "10"))
POLL_MED_MIN         = int(os.getenv("POLL_MED_MIN",     "5"))
POLL_HIGH_MIN        = int(os.getenv("POLL_HIGH_MIN",    "5"))
BURST_INTERVAL_SEC   = int(os.getenv("BURST_INTERVAL_SEC", "30"))
MAX_BURST_MIN        = int(os.getenv("MAX_BURST_MIN",   "15"))
PANO_SHOTS           = int(os.getenv("PANO_SHOTS",       "8"))
PANO_MOVE_SEC        = float(os.getenv("PANO_MOVE_SEC",  "2.2"))
PANO_SPEED           = int(os.getenv("PANO_SPEED",      "20"))
PANO_SETTLE_SEC      = float(os.getenv("PANO_SETTLE_SEC","1.5"))
THUMB_HEIGHT         = int(os.getenv("THUMB_HEIGHT",    "480"))
MAX_PANO_HISTORY     = int(os.getenv("MAX_PANO_HISTORY","200"))
MAX_TL_HISTORY       = int(os.getenv("MAX_TL_HISTORY",   "50"))

# ── Horizon scout ─────────────────────────────────────────────────────────────
SCOUT_INTERVAL_MIN   = int(os.getenv("SCOUT_INTERVAL_MIN",   "30"))
SCOUT_POSITIONS      = int(os.getenv("SCOUT_POSITIONS",        "8"))
SCOUT_MIN_SCORE      = float(os.getenv("SCOUT_MIN_SCORE",    "45"))
SCOUT_FOCUS_SHOTS    = int(os.getenv("SCOUT_FOCUS_SHOTS",      "5"))
SCOUT_FOCUS_INTERVAL = int(os.getenv("SCOUT_FOCUS_INTERVAL",  "15"))
SCOUT_FOCUS_CONTINUE = float(os.getenv("SCOUT_FOCUS_CONTINUE","50"))
SCOUT_MAX_DWELL_MIN  = float(os.getenv("SCOUT_MAX_DWELL_MIN", "3"))

PANO_DIR      = HIGHLIGHTS_DIR / "panoramas"
TL_DIR        = HIGHLIGHTS_DIR / "weather_timelapse"
SCOUT_DIR     = HIGHLIGHTS_DIR / "weather" / "scout"
SCOUT_STATS   = HIGHLIGHTS_DIR / "scout_stats.json"
PANO_MANIFEST = HIGHLIGHTS_DIR / "pano_manifest.json"
TL_MANIFEST   = HIGHLIGHTS_DIR / "weather_timelapse_manifest.json"
STITCH_PY     = Path("/app/stitch.py")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sky-watcher")

# ── MQTT ──────────────────────────────────────────────────────────────────────
_mqtt: mqtt.Client | None = None

def mqtt_connect() -> None:
    global _mqtt
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
        client.loop_start()
        _mqtt = client
        log.info("MQTT connected")
    except Exception as e:
        log.warning(f"MQTT unavailable: {e}")

def mqtt_publish(topic: str, payload: dict) -> None:
    if _mqtt is None:
        return
    try:
        _mqtt.publish(topic, json.dumps(payload), qos=0)
    except Exception as e:
        log.warning(f"MQTT publish failed: {e}")

# ── Sky scoring ───────────────────────────────────────────────────────────────
def score_image(img: Image.Image) -> float:
    """Dramatic-quality score 0–100. Matches score_images.py algorithm."""
    img = img.convert("RGB")
    img.thumbnail((320, 320), Image.LANCZOS)
    px = np.array(img, dtype=float)
    r, g, b = px[:, :, 0], px[:, :, 1], px[:, :, 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b

    warm       = (r > 140) & (r > g * 1.2) & (r > b * 1.25)
    warm_score = min(warm.mean() * 280, 100)

    hi = px.max(axis=2); lo = px.min(axis=2)
    sat       = np.where(hi > 0, (hi - lo) / (hi + 1e-6), 0)
    sat_score = min(sat.mean() * 200, 100)

    contrast_score = min(lum.std() / 55 * 100, 100)

    blown          = ((r > 248) & (g > 248) & (b > 248)).mean()
    dark           = (lum < 25).mean()
    exposure_score = max(0.0, 100 - blown * 500 - dark * 150)

    h = lum.shape[0]
    sky_diff  = lum[: h // 2].mean() - lum[h // 2 :].mean()
    sky_score = min(max(sky_diff / 35 * 100, 0), 100)

    storm       = (b > 100) & (b > r * 1.15) & (lum < 170)
    storm_bonus = min(storm.mean() * 250, 40)

    score = (
        warm_score     * 0.30
        + sat_score    * 0.25
        + contrast_score * 0.20
        + exposure_score * 0.10
        + sky_score    * 0.10
        + storm_bonus  * 0.05
    )
    return round(float(min(max(score, 0), 100)), 1)


def grab_sky_frame() -> tuple[bytes | None, float]:
    """Fetch latest Frigate still. Returns (jpeg_bytes, score)."""
    url = f"{FRIGATE_API}/api/{CAMERA_NAME}/latest.jpg"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200 and r.content:
            img   = Image.open(io.BytesIO(r.content))
            score = score_image(img)
            return r.content, score
    except Exception as e:
        log.warning(f"grab_sky_frame failed: {e}")
    return None, 0.0

# ── Direct camera snap ────────────────────────────────────────────────────────
def _snap_direct(rs: str) -> tuple[bytes | None, float]:
    """Fetch a fresh JPEG directly from the camera (bypasses Frigate cache)."""
    url = (f"http://{CAMERA_IP}/cgi-bin/api.cgi"
           f"?cmd=Snap&channel=0&rs={rs}"
           f"&user={CAMERA_USER}&password={CAMERA_PASS}")
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200 and r.content:
            img   = Image.open(io.BytesIO(r.content))
            score = score_image(img)
            return r.content, score
    except Exception as e:
        log.warning(f"_snap_direct failed: {e}")
    return None, 0.0

# ── PTZ ───────────────────────────────────────────────────────────────────────
def _ptz(op: str) -> None:
    url = (f"http://{CAMERA_IP}/api.cgi"
           f"?user={CAMERA_USER}&password={CAMERA_PASS}&cmd=PtzCtrl")
    try:
        requests.post(
            url,
            json=[{"cmd": "PtzCtrl", "action": 0,
                   "param": {"channel": 0, "op": op, "speed": PANO_SPEED}}],
            timeout=5,
        )
    except Exception as e:
        log.warning(f"PTZ {op} failed: {e}")

# ── Panorama capture ──────────────────────────────────────────────────────────
def capture_panorama(ts: str) -> Path | None:
    """Sweep camera right→left, snap frames, stitch. Returns final JPG path."""
    if not STITCH_PY.exists():
        log.error(f"stitch.py not found at {STITCH_PY}")
        return None

    work_dir = PANO_DIR / f"_frames_{ts}"
    work_dir.mkdir(parents=True, exist_ok=True)

    log.info("Panorama: homing right 20s…")
    _ptz("Right")
    time.sleep(20)
    _ptz("Stop")
    time.sleep(2)

    frames: list[Path] = []
    for i in range(1, PANO_SHOTS + 1):
        if i > 1:
            _ptz("Left")
            time.sleep(PANO_MOVE_SEC)
            _ptz("Stop")
        time.sleep(PANO_SETTLE_SEC)
        data, _ = _snap_direct(f"{ts}_{i:02d}")
        if data:
            p = work_dir / f"{i:02d}.jpg"
            p.write_bytes(data)
            frames.append(p)
            log.info(f"  frame {i:02d}/{PANO_SHOTS}: {len(data)//1024}KB")

    if len(frames) < 3:
        log.warning(f"Only {len(frames)} frames — skipping stitch")
        return None

    cmd    = ["python3", str(STITCH_PY)] + [str(f) for f in sorted(frames)]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(work_dir))
    stitched = work_dir / "panorama_stitched.jpg"

    if result.returncode == 0 and stitched.exists():
        out_jpg = PANO_DIR / f"{ts}.jpg"
        stitched.rename(out_jpg)
        for f in frames:
            f.unlink(missing_ok=True)
        try:
            work_dir.rmdir()
        except OSError:
            pass
        log.info(f"Panorama saved: {out_jpg.name}")
        return out_jpg
    else:
        log.error(f"Stitch failed: {result.stderr[:300]}")
        return None


def make_pano_thumbnail(pano_path: Path, ts: str) -> Path | None:
    """Centre-crop 16:9 thumbnail from panorama."""
    try:
        img  = Image.open(pano_path)
        w, h = img.size
        crop_w = min(int(h * 16 / 9), w)
        x      = (w - crop_w) // 2
        crop   = img.crop((x, 0, x + crop_w, h))
        ratio  = THUMB_HEIGHT / h
        thumb  = crop.resize((int(crop_w * ratio), THUMB_HEIGHT), Image.LANCZOS)
        out    = PANO_DIR / f"{ts}_thumb.jpg"
        thumb.save(out, "JPEG", quality=85)
        return out
    except Exception as e:
        log.warning(f"Pano thumbnail failed: {e}")
        return None


def update_pano_manifest(entry: dict) -> None:
    PANO_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"entries": []}
    if PANO_MANIFEST.exists():
        try:
            manifest = json.loads(PANO_MANIFEST.read_text())
        except Exception:
            pass
    manifest.setdefault("entries", []).insert(0, entry)
    manifest["entries"] = manifest["entries"][:MAX_PANO_HISTORY]
    manifest["updated"] = datetime.now().isoformat()
    PANO_MANIFEST.write_text(json.dumps(manifest, indent=2))


def finish_panorama(pano_path: Path, ts: str, score: float, trigger: str) -> None:
    thumb = make_pano_thumbnail(pano_path, ts)
    try:
        img  = Image.open(pano_path)
        w, h = img.size
    except Exception:
        w = h = 0
    entry = {
        "timestamp": ts,
        "panorama":  f"panoramas/{pano_path.name}",
        "thumbnail": f"panoramas/{thumb.name}" if thumb else None,
        "score":     score,
        "width":     w,
        "height":    h,
        "trigger":   trigger,
    }
    update_pano_manifest(entry)
    mqtt_publish("cameras/events/panorama", {
        "timestamp": ts, "score": score, "panorama": entry["panorama"]
    })
    log.info(f"Panorama registered: {pano_path.name}  {w}x{h}  score={score}")

# ── Weather event timelapse ───────────────────────────────────────────────────
def run_burst_and_compile(ts: str, initial_frame: bytes) -> None:
    """Collect burst stills while sky stays interesting, then compile to MP4."""
    burst_dir = TL_DIR / f"_burst_{ts}"
    burst_dir.mkdir(parents=True, exist_ok=True)

    frames: list[Path] = []
    scores: list[float] = []

    p = burst_dir / "frame_0000.jpg"
    p.write_bytes(initial_frame)
    frames.append(p)

    deadline  = time.monotonic() + MAX_BURST_MIN * 60
    low_streak = 0

    log.info(f"Burst mode: up to {MAX_BURST_MIN} min, {BURST_INTERVAL_SEC}s per frame")

    while time.monotonic() < deadline:
        time.sleep(BURST_INTERVAL_SEC)
        data, score = grab_sky_frame()
        scores.append(score)
        log.info(f"  burst {len(frames):02d}: score={score:.1f}")
        if data:
            p = burst_dir / f"frame_{len(frames):04d}.jpg"
            p.write_bytes(data)
            frames.append(p)
        low_streak = (low_streak + 1) if score < SCORE_BURST_CONTINUE else 0
        if low_streak >= 3:
            log.info("  sky calmed — ending burst")
            break

    if len(frames) < 4:
        log.info(f"Only {len(frames)} burst frames — skipping timelapse")
        return

    out_mp4 = TL_DIR / f"{ts}_timelapse.mp4"
    frame_pattern = str(burst_dir / "frame_%04d.jpg")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", "12",
        "-i", frame_pattern,
        "-vf", "scale=1920:-2:flags=lanczos",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        str(out_mp4),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not out_mp4.exists():
        log.error(f"ffmpeg failed: {result.stderr[:300]}")
        return

    log.info(f"Timelapse compiled: {out_mp4.name} ({len(frames)} frames)")

    # Mid-burst thumbnail
    mid = frames[len(frames) // 2]
    thumb_path: Path | None = None
    try:
        img = Image.open(mid)
        img.thumbnail((960, 540), Image.LANCZOS)
        thumb_path = TL_DIR / f"{ts}_timelapse_thumb.jpg"
        img.save(thumb_path, "JPEG", quality=82)
    except Exception as e:
        log.warning(f"Timelapse thumb failed: {e}")

    peak  = max(scores) if scores else 0.0
    avg_s = round(sum(scores) / len(scores), 1) if scores else 0.0
    entry = {
        "timestamp":   ts,
        "video":       f"weather_timelapse/{out_mp4.name}",
        "thumbnail":   f"weather_timelapse/{thumb_path.name}" if thumb_path else None,
        "score":       peak,
        "avg_score":   avg_s,
        "frame_count": len(frames),
        "duration_min": round(len(frames) * BURST_INTERVAL_SEC / 60, 1),
    }
    update_tl_manifest(entry)
    mqtt_publish("cameras/events/sky_timelapse", {
        "timestamp": ts, "score": peak,
        "frame_count": len(frames), "video": entry["video"],
    })

    for f in frames:
        f.unlink(missing_ok=True)
    try:
        burst_dir.rmdir()
    except OSError:
        pass


def update_tl_manifest(entry: dict) -> None:
    TL_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"latest": None, "entries": []}
    if TL_MANIFEST.exists():
        try:
            manifest = json.loads(TL_MANIFEST.read_text())
        except Exception:
            pass
    manifest.setdefault("entries", []).insert(0, entry)
    manifest["entries"] = manifest["entries"][:MAX_TL_HISTORY]
    manifest["latest"]  = manifest["entries"][0]
    manifest["updated"] = datetime.now().isoformat()
    TL_MANIFEST.write_text(json.dumps(manifest, indent=2))

# ── Horizon scout ────────────────────────────────────────────────────────────
def _run_focus_dwell(ts: str) -> int:
    """
    Fixed minimum shots (SCOUT_FOCUS_SHOTS), then adaptive extension while
    score stays above SCOUT_FOCUS_CONTINUE, up to SCOUT_MAX_DWELL_MIN total.
    Returns number of shots saved.
    """
    SCOUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    deadline = time.monotonic() + SCOUT_MAX_DWELL_MIN * 60

    for i in range(SCOUT_FOCUS_SHOTS):
        if i > 0:
            time.sleep(SCOUT_FOCUS_INTERVAL)
        data, score = _snap_direct(f"{ts}_f{saved:03d}")
        if data:
            (SCOUT_DIR / f"scout_{ts}_{saved:03d}.jpg").write_bytes(data)
            saved += 1
        log.info(f"  focus shot {saved} (fixed): score={score:.1f}")

    while time.monotonic() < deadline:
        time.sleep(SCOUT_FOCUS_INTERVAL)
        data, score = _snap_direct(f"{ts}_f{saved:03d}")
        log.info(f"  focus shot {saved+1} (adaptive): score={score:.1f}")
        if score < SCOUT_FOCUS_CONTINUE:
            log.info("  score dropped — ending dwell")
            break
        if data:
            (SCOUT_DIR / f"scout_{ts}_{saved:03d}.jpg").write_bytes(data)
            saved += 1

    return saved


def _append_scout_stats(ts: str, stops: list[tuple[int, float]]) -> None:
    record = {
        "ts": ts,
        "hour": int(ts[9:11]),
        "stops": [round(score, 1) for _, score in sorted(stops, key=lambda x: x[0])],
    }
    with open(SCOUT_STATS, "a") as f:
        f.write(json.dumps(record) + "\n")


def horizon_scout() -> None:
    """Sweep N horizon positions, score each, then dwell on the best."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log.info(f"=== horizon scout: {SCOUT_POSITIONS} positions ===")

    # Home right
    _ptz("Right")
    time.sleep(20)
    _ptz("Stop")
    time.sleep(2)

    # Scan — step left, snap and score at each stop
    stops: list[tuple[int, float]] = []
    for i in range(SCOUT_POSITIONS):
        if i > 0:
            _ptz("Left")
            time.sleep(PANO_MOVE_SEC)
            _ptz("Stop")
        time.sleep(PANO_SETTLE_SEC)
        _, score = _snap_direct(f"{ts}_s{i:02d}")
        stops.append((i, score))
        log.info(f"  stop {i+1}/{SCOUT_POSITIONS}: score={score:.1f}")

    _append_scout_stats(ts, stops)

    best_idx, best_score = max(stops, key=lambda x: x[1])
    log.info(f"  best: stop {best_idx+1}  score={best_score:.1f}")
    mqtt_publish("cameras/events/scout_scan", {
        "timestamp": ts, "positions": SCOUT_POSITIONS,
        "best_stop": best_idx, "best_score": best_score,
    })

    # Always park at best stop so the next sky-score poll sees the most interesting direction
    _ptz("Right")
    time.sleep(20)
    _ptz("Stop")
    time.sleep(2)
    for _ in range(best_idx):
        _ptz("Left")
        time.sleep(PANO_MOVE_SEC)
        _ptz("Stop")
    time.sleep(PANO_SETTLE_SEC)

    if best_score < SCOUT_MIN_SCORE:
        log.info(f"  best score {best_score:.1f} < {SCOUT_MIN_SCORE} — parked at S{best_idx+1}, skipping focus")
        return

    log.info(f"  dwelling at stop {best_idx+1} (≤{SCOUT_MAX_DWELL_MIN}m)")
    saved = _run_focus_dwell(ts)
    log.info(f"=== scout done: {saved} shots ===")
    mqtt_publish("cameras/events/scout_focus", {
        "timestamp": ts, "best_stop": best_idx,
        "best_score": best_score, "shots_saved": saved,
    })


# ── Main loop ─────────────────────────────────────────────────────────────────
def main() -> None:
    PANO_DIR.mkdir(parents=True, exist_ok=True)
    TL_DIR.mkdir(parents=True,   exist_ok=True)
    SCOUT_DIR.mkdir(parents=True, exist_ok=True)

    log.info("Sky watcher starting")
    log.info(f"  Pano threshold: {SCORE_PANO}  |  Burst threshold: {SCORE_BURST}")
    log.info(f"  Intervals — low: {POLL_LOW_MIN}m  med: {POLL_MED_MIN}m  high: {POLL_HIGH_MIN}m")
    log.info(f"  Scout: every {SCOUT_INTERVAL_MIN}m, {SCOUT_POSITIONS} positions, focus≥{SCOUT_MIN_SCORE}")

    mqtt_connect()

    last_scout = time.monotonic() - SCOUT_INTERVAL_MIN * 60  # run first scout immediately

    while True:
        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        data, score = grab_sky_frame()
        log.info(f"Sky score: {score:.1f}")
        mqtt_publish("cameras/events/sky_score", {"timestamp": ts, "score": score})

        if score >= SCORE_BURST and data is not None:
            log.info(f"Score {score:.1f} ≥ {SCORE_BURST} → panorama + burst timelapse")
            pano = capture_panorama(ts)
            if pano:
                finish_panorama(pano, ts, score, trigger="burst")
            run_burst_and_compile(ts, data)
            last_scout = time.monotonic()  # panorama sweep counts as a scout
            time.sleep(POLL_HIGH_MIN * 60)

        elif score >= SCORE_PANO:
            log.info(f"Score {score:.1f} ≥ {SCORE_PANO} → panorama")
            pano = capture_panorama(ts)
            if pano:
                finish_panorama(pano, ts, score, trigger="sky_score")
            last_scout = time.monotonic()
            time.sleep(POLL_HIGH_MIN * 60)

        else:
            # Periodic scout independent of current sky score
            if time.monotonic() - last_scout >= SCOUT_INTERVAL_MIN * 60:
                horizon_scout()
                last_scout = time.monotonic()

            sleep_min = POLL_MED_MIN if score >= 40 else POLL_LOW_MIN
            log.info(f"Score {score:.1f} → next check in {sleep_min}m")
            time.sleep(sleep_min * 60)


if __name__ == "__main__":
    main()
