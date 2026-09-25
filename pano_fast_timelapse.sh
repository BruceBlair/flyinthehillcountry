#!/usr/bin/env bash
# Panoramic timelapse for cam2 using pano_fast_capture.sh + stitch_known_angles.py.
#
# Captures a 5-stop panorama every INTERVAL seconds until END (HH:MM, today),
# stitching each one in the background at low priority so stitching never
# delays the PTZ cadence, then encodes an MP4. AI detect/track is disabled for
# the whole run (anything moving in frame can otherwise hijack the PTZ) and
# restored on exit, including on kill.
#
# Usage: ./pano_fast_timelapse.sh END_HHMM [interval_sec] [settle_sec] [out_dir]
#   env PANO_PRESETS / PANO_PRESET_JSON pick a tilted preset set, e.g.
#   PANO_PRESETS="11 12 13 14 15" \
#   PANO_PRESET_JSON=data/pano_presets_cam2_tilt16.json ./pano_fast_timelapse.sh 20:10 30 1.5
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
source /home/HighlyReflective/hithc-gtn-depot/.env

END="${1:?END time HH:MM required}"
INTERVAL="${2:-30}"
SETTLE="${3:-1.5}"
OUT="${4:-/volume1/pano_test/timelapse_$(date +%Y%m%d_%H%M)}"
PRESET_JSON="${PANO_PRESET_JSON:-/home/HighlyReflective/hithc-gtn-depot/data/pano_presets_cam2.json}"
END_TS=$(date -d "$END" +%s)
mkdir -p "$OUT/cycles" "$OUT/panos"
LOG="$OUT/timelapse.log"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

# PANO_CAM=1 selects cam1 (CAMERA_*); default cam2 (CAMERA2_*). Exported so
# pano_fast_capture.sh picks the same camera.
export PANO_CAM="${PANO_CAM:-2}"
if [[ "$PANO_CAM" == 1 ]]; then CP=CAMERA_; else CP=CAMERA2_; fi
v="${CP}IP"; CAM_IP="${!v:?}"
v="${CP}USER"; CAM_USER="${!v:?}"
v="${CP}PASSWORD"; CAM_PASS="${!v:?}"
token() {
  curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=Login" -H "Content-Type: application/json" \
    -d "[{\"cmd\":\"Login\",\"action\":0,\"param\":{\"User\":{\"userName\":\"${CAM_USER}\",\"password\":\"${CAM_PASS}\"}}}]" \
    | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['value']['Token']['name'])"
}
logout() { curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=Logout&token=$1" -H "Content-Type: application/json" \
  -d '[{"cmd":"Logout","action":0,"param":{}}]' >/dev/null || true; }
set_ai() {  # $1 = 0|1
  local t; t=$(token) || return 1
  curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=SetAiCfg&token=${t}" -H "Content-Type: application/json" \
    -d "[{\"cmd\":\"SetAiCfg\",\"action\":0,\"param\":{\"channel\":0,\"AiDetectType\":{\"people\":$1,\"vehicle\":$1,\"dog_cat\":$1}}}]" >/dev/null
  curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=SetAutoTrackCfg&token=${t}" -H "Content-Type: application/json" \
    -d "[{\"cmd\":\"SetAutoTrackCfg\",\"action\":0,\"param\":{\"channel\":0,\"AutoTrackCfg\":{\"enable\":$1}}}]" >/dev/null
  logout "$t"   # tokens otherwise live ~1h against a small session limit
}
# PANO_MOVE=pan sweeps never recall presets (a recall restores the tele zoom
# saved with it), but pan-only moves can't set tilt -- there is no tilt readout.
# So recall the first preset once to set the tilt, then put the zoom back to
# whatever it was before.
set_tilt_keep_zoom() {
  local t z first; t=$(token) || return 1
  read -r first _ <<< "${PANO_PRESETS:-5 6 7 8 9}"
  z=$(curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=GetZoomFocus&token=${t}" -H "Content-Type: application/json" \
    -d '[{"cmd":"GetZoomFocus","action":0,"param":{"channel":0}}]' \
    | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['value']['ZoomFocus']['zoom']['pos'])")
  curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=PtzCtrl&token=${t}" -H "Content-Type: application/json" \
    -d "[{\"cmd\":\"PtzCtrl\",\"action\":0,\"param\":{\"channel\":0,\"op\":\"ToPos\",\"speed\":64,\"id\":${first}}}]" >/dev/null
  sleep 8   # full-range pan + zoom travel
  [[ -n "$z" ]] && curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=StartZoomFocus&token=${t}" -H "Content-Type: application/json" \
    -d "[{\"cmd\":\"StartZoomFocus\",\"action\":0,\"param\":{\"ZoomFocus\":{\"channel\":0,\"op\":\"ZoomPos\",\"pos\":${z}}}}]" >/dev/null
  logout "$t"
  log "tilt set from preset $first; zoom restored to ${z:-unknown}"
}
finish() {
  set_ai 1 && log "AI detect/track restored" || log "WARNING: failed to restore AI detect/track"
}
trap finish EXIT
trap 'exit 130' INT TERM

set_ai 0 && log "AI detect/track disabled; capturing until $END every ${INTERVAL}s (settle ${SETTLE}s) -> $OUT"
[[ "${PANO_MOVE:-preset}" == pan ]] && set_tilt_keep_zoom
n=0
while (( $(date +%s) < END_TS )); do
  t0=$(date +%s)
  cyc=$(printf '%04d' "$n")
  if PANO_REVERSE=$(( n % 2 )) bash "$DIR/pano_fast_capture.sh" "$SETTLE" 64 "$OUT/cycles/$cyc" >>"$LOG" 2>&1; then
    nice -n 15 python3 "$DIR/stitch_known_angles.py" "$OUT/cycles/$cyc" --presets "$PRESET_JSON" \
      -o "$OUT/panos/pano_$cyc.jpg" >>"$LOG" 2>&1 &
    log "cycle $cyc captured in $(( $(date +%s) - t0 ))s"
  else
    log "cycle $cyc FAILED capture"
    # Back off while the camera is unreachable. With interval 0 a network drop
    # (2026-09-25 06:32, ~80 s) otherwise retried ~25x/s: ~1900 failed cycles
    # per camera, each a login attempt against the camera's small session limit.
    fails=$(( ${fails:-0} + 1 ))
    backoff=$(( fails < 5 ? 2 ** fails : 30 ))
    log "backing off ${backoff}s (consecutive failures: $fails)"
    sleep "$backoff"
    n=$((n + 1)); continue
  fi
  fails=0
  n=$((n + 1))
  sleep $(( INTERVAL - ($(date +%s) - t0) > 0 ? INTERVAL - ($(date +%s) - t0) : 0 ))
done
log "capture done ($n cycles); waiting for stitches"
wait
set_ai 1 && log "AI detect/track restored"
trap - EXIT

# Encode: fixed 3840-wide (H.264-friendly), 30 fps, frames in capture order.
ls "$OUT"/panos/pano_*.jpg >/dev/null 2>&1 || { log "no panoramas stitched"; exit 1; }
nice -n 10 ffmpeg -y -loglevel error -framerate 30 -pattern_type glob -i "$OUT/panos/pano_*.jpg" \
  -vf "scale=3840:-2:flags=lanczos,format=yuv420p" -c:v libx264 -crf 18 -preset slow \
  "$OUT/pano_timelapse.mp4" && log "wrote $OUT/pano_timelapse.mp4 ($(ls "$OUT"/panos/*.jpg | wc -l) frames)"
chmod -R a+rX "$OUT"
