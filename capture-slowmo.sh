#!/usr/bin/env bash
# capture-slowmo.sh — Ground Truth Network
# Locks camera to one PTZ angle, captures live RTSP, encodes slow-motion MP4.
#
# Usage:
#   bash capture-slowmo.sh [angle] [lens] [duration_sec] [slowdown]
#
# Examples:
#   bash capture-slowmo.sh South wide 60 4       # 60s source → 4× slow → 4-min clip
#   bash capture-slowmo.sh "top centered" zoom 30 2
#
# Angles: South Southeast East Northeast North Northwest West Southwest "top centered"
# Lens:   wide | zoom
# Slowdown: 2 (= 0.5× speed) | 4 (= 0.25× speed) | 8 (= 0.125× speed)

set -euo pipefail

# ── Config ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/.env" 2>/dev/null || true

CAMERA_IP="${CAMERA_IP:-192.168.100.131}"
CAMERA_USER="${CAMERA_USER:-admin}"
CAMERA_PASSWORD="${CAMERA_PASSWORD:-}"
HA_URL="${HA_URL:-http://192.168.100.202:8123}"
HA_TOKEN="${HA_TOKEN:-}"
OUT_DIR="${OUT_DIR:-/volume1/highlights/slowmo}"

# ── Args ───────────────────────────────────────────────────────────────────────
ANGLE="${1:-South}"          # PTZ preset name
LENS="${2:-wide}"            # wide | zoom
DURATION="${3:-60}"          # seconds of source footage to capture
SLOWDOWN="${4:-4}"           # integer: output plays at 1/SLOWDOWN speed

# ── Derived ────────────────────────────────────────────────────────────────────
case "$LENS" in
  zoom) STREAM_PATH="h264Preview_02_main" ;;
  *)    STREAM_PATH="h264Preview_01_main" ;;
esac
RTSP="rtsp://${CAMERA_USER}:${CAMERA_PASSWORD}@${CAMERA_IP}:554/${STREAM_PATH}"

TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
SLUG=$(echo "$ANGLE" | tr ' ' '_' | tr '[:upper:]' '[:lower:]')
FILENAME="slowmo_${SLUG}_${LENS}_${SLOWDOWN}x_${TIMESTAMP}.mp4"
OUTPUT="${OUT_DIR}/${FILENAME}"
PARTIAL="${OUTPUT}.tmp.mp4"
RAW_CAPTURE="/tmp/slowmo_raw_${TIMESTAMP}.mp4"
OUTPUT_SECONDS=$(( DURATION * SLOWDOWN ))

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ── 1. Move camera to angle ────────────────────────────────────────────────────
log "Moving camera to preset: $ANGLE"
if [ -n "$HA_TOKEN" ]; then
  curl -sf -X POST "${HA_URL}/api/services/select/select_option" \
    -H "Authorization: Bearer ${HA_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"entity_id\": \"select.high_res_in_the_hill_country_ptz_preset\", \"option\": \"${ANGLE}\"}" \
    > /dev/null && log "PTZ command sent." || log "WARN: PTZ move failed (continuing)."
  log "Waiting 4s for camera to settle..."
  sleep 4
else
  log "WARN: HA_TOKEN not set — skipping PTZ move. Point camera manually first."
fi

# ── 2. Capture raw footage ─────────────────────────────────────────────────────
log "Capturing ${DURATION}s from ${LENS} lens (${RTSP%%@*}@...)..."
mkdir -p "$OUT_DIR"
ffmpeg -y \
  -rtsp_transport tcp \
  -i "$RTSP" \
  -t "$DURATION" \
  -c copy \
  "$RAW_CAPTURE" 2>&1 | tail -3
log "Raw capture complete → ${RAW_CAPTURE}"

# ── 3. Encode slow-motion ──────────────────────────────────────────────────────
# TODO: Implement your preferred slow-motion strategy here.
#
# The raw capture is at $RAW_CAPTURE (${DURATION}s of source footage).
# Target output: $PARTIAL → moved to $OUTPUT when done.
# Output should play at 1/${SLOWDOWN}× speed (${OUTPUT_SECONDS}s total).
#
# Approach A — simple timestamp stretch (fast, no artifacts):
#   setpts=${SLOWDOWN}.0*PTS  +  atempo chain for audio
#
# Approach B — frame interpolation (smoother, ~5× slower to encode):
#   minterpolate=fps=60:mi_mode=mci  before setpts
#
# Approach C — skip audio entirely for cleanest result
#
# Quality knobs: -crf 18 (archival) vs -crf 26 (web-share), -preset slow vs fast

log "Encoding ${SLOWDOWN}× slow-motion (${OUTPUT_SECONDS}s output) → ${OUTPUT}..."

ffmpeg -y \
  -i "$RAW_CAPTURE" \
  -vf "minterpolate=fps=60:mi_mode=blend,setpts=${SLOWDOWN}.0*PTS,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" \
  -an \
  -c:v libx264 -preset medium -crf 22 -threads 2 \
  -movflags +faststart \
  "$PARTIAL" 2>&1 | tail -5

mv "$PARTIAL" "$OUTPUT"
rm -f "$RAW_CAPTURE"
SIZE=$(du -sh "$OUTPUT" | cut -f1)
log "Done → $OUTPUT  ($SIZE, ${OUTPUT_SECONDS}s at ${SLOWDOWN}× slow)"
