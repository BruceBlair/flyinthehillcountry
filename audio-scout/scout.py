#!/usr/bin/env python3
"""
Audio Scout — Ground Truth Network
Real-time wildlife and bird sound detection from Reolink RTSP audio stream.
"""
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from classifier import Detection, classify_chunk, filter_detections, BIRDNET_CONFIDENCE, YAMNET_CONFIDENCE
from manifest_io import AudioManifest, load_manifest, save_manifest, add_detection
from mqtt_client import MQTTClient
from species_cache import lookup_species

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [audio-scout] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("audio-scout")

# ─── Config ──────────────────────────────────────────────────────────────────
CAMERA_IP        = os.getenv("CAMERA_IP",       "192.168.100.131")
CAMERA_USER      = os.getenv("CAMERA_USER",     "admin")
CAMERA_PASS      = os.getenv("CAMERA_PASSWORD", "")
HIGHLIGHTS_DIR   = Path(os.getenv("HIGHLIGHTS_DIR", "/highlights"))
AUDIO_DIR        = HIGHLIGHTS_DIR / "audio"
MANIFEST_PATH    = HIGHLIGHTS_DIR / "audio_manifest.json"
HIGHLIGHTS_MANIFEST = HIGHLIGHTS_DIR / "manifest.json"
RARE_SPECIES_FILE = Path("/app/rare_species.txt")
RARE_SPECIES_PUSH = os.getenv("RARE_SPECIES_PUSH", "false").lower() == "true"

SAMPLE_RATE  = 48000
CHUNK_SEC    = 3
CHUNK_BYTES  = SAMPLE_RATE * 2 * CHUNK_SEC   # 16-bit mono = 2 bytes/sample

RTSP_URL = (
    f"rtsp://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:554/h264Preview_01_main"
)

# ─── State ───────────────────────────────────────────────────────────────────
_start_time = time.time()
_running = True


def _sigterm(sig, frame):
    global _running
    _running = False


signal.signal(signal.SIGTERM, _sigterm)
signal.signal(signal.SIGINT, _sigterm)


# ─── Rare species ─────────────────────────────────────────────────────────────
def load_rare_species() -> set[str]:
    if not RARE_SPECIES_FILE.exists():
        return set()
    return {line.strip().lower() for line in RARE_SPECIES_FILE.read_text().splitlines()
            if line.strip() and not line.startswith("#")}


# ─── Highlights manifest ──────────────────────────────────────────────────────
def load_highlights() -> list:
    if not HIGHLIGHTS_MANIFEST.exists():
        return []
    try:
        data = json.loads(HIGHLIGHTS_MANIFEST.read_text())
        return data.get("entries", data) if isinstance(data, dict) else data
    except Exception:
        return []


# ─── Audio capture ────────────────────────────────────────────────────────────
def open_ffmpeg_stream() -> subprocess.Popen:
    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", RTSP_URL,
        "-vn",                      # no video
        "-ac", "1",                 # mono
        "-ar", str(SAMPLE_RATE),
        "-f", "s16le",              # raw PCM 16-bit little-endian
        "pipe:1",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


# ─── Clip saving ─────────────────────────────────────────────────────────────
def save_clip(pcm_bytes: bytes, det: Detection, timestamp: str) -> str:
    import wave, io
    slug = det.species.lower().replace(" ", "_")[:30]
    filename = f"{timestamp}_{slug}.wav"
    path = AUDIO_DIR / filename
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    path.write_bytes(buf.getvalue())
    return str(path.relative_to(HIGHLIGHTS_DIR))


# ─── Main loop ────────────────────────────────────────────────────────────────
def main():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    mqtt = MQTTClient()
    mqtt.connect()

    log.info("Audio Scout starting — RTSP: %s", RTSP_URL.replace(CAMERA_PASS, "***"))
    log.info("  BirdNET threshold: %.2f  |  YAMNet threshold: %.2f",
             BIRDNET_CONFIDENCE, YAMNET_CONFIDENCE)

    last_heartbeat = 0.0
    proc = None

    while _running:
        try:
            if proc is None or proc.poll() is not None:
                log.info("Opening RTSP stream...")
                proc = open_ffmpeg_stream()

            chunk = proc.stdout.read(CHUNK_BYTES)
            if len(chunk) < CHUNK_BYTES:
                log.warning("Short read from ffmpeg — reconnecting")
                proc.terminate()
                proc = None
                time.sleep(5)
                continue

            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            raw_detections = classify_chunk(chunk, SAMPLE_RATE)

            birdnet_hits = filter_detections(
                [d for d in raw_detections if d.detector == "birdnet"],
                BIRDNET_CONFIDENCE,
            )
            yamnet_hits = filter_detections(
                [d for d in raw_detections if d.detector == "yamnet"],
                YAMNET_CONFIDENCE,
            )
            hits = birdnet_hits + yamnet_hits

            if hits:
                manifest = load_manifest(MANIFEST_PATH)
                highlights = load_highlights()
                rare = load_rare_species()

                for det in hits:
                    clip = save_clip(chunk, det, timestamp)
                    info = lookup_species(det.scientific_name) if det.scientific_name else {}
                    entry = add_detection(
                        manifest, det,
                        timestamp=timestamp,
                        clip_path=clip,
                        highlights_manifest=highlights,
                        species_info=info,
                    )
                    mqtt.publish("audio/detections", entry)
                    log.info("Detection: %s (%.2f) [%s]", det.species, det.confidence, det.detector)

                    if RARE_SPECIES_PUSH and det.species.lower() in rare:
                        mqtt.publish("audio/detections/rare", entry)
                        log.info("  → RARE species alert: %s", det.species)

                save_manifest(manifest, MANIFEST_PATH)

            # Heartbeat every 60s
            now = time.time()
            if now - last_heartbeat >= 60:
                mqtt.publish("audio/status", {
                    "status": "ok",
                    "uptime": int(now - _start_time),
                })
                last_heartbeat = now

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("Loop error: %s", e, exc_info=True)
            time.sleep(10)

    if proc:
        proc.terminate()
    mqtt.disconnect()
    log.info("Audio Scout stopped.")


if __name__ == "__main__":
    main()
