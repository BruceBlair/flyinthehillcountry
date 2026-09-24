#!/usr/bin/env bash
# Fast panorama sweep for timelapse use: jumps preset-to-preset (absolute
# positioning via ToPos) at high PTZ speed instead of nudging, pausing only
# long enough for the camera to settle before each snap. Requires presets
# saved by calibrate_pano_presets_angle.py (ids 5-9, 72deg apart around the
# full circle; measured angles in data/pano_presets_cam2.json).
#
# Usage: ./pano_fast_capture.sh [settle_sec] [ptz_speed] [out_dir]
#
# Cycle time (measured 2026-09-23, calm): ~14.5s at settle 0.5, ~16.7s at
# settle 1 (default), ~22s at settle 2. Allow longer settle at night or in
# wind.
set -e
source /home/HighlyReflective/hithc-gtn-depot/.env

SETTLE_SEC="${1:-1}"   # extra settle after arrival; 0.5 suffices in calm air
PTZ_SPEED="${2:-64}"   # 1-64; 64 = fastest
OUT_DIR="${3:-/volume1/gtn_inbox/panos_incoming/fast_$(date +%Y%m%d_%H%M%S)}"
# Level presets by default; tilted sets via env, e.g. PANO_PRESETS="11 12 13 14 15"
# (panoT1-5, ~15deg up; stitch with --presets data/pano_presets_cam2_tilt16.json).
read -r -a PRESET_IDS <<< "${PANO_PRESETS:-5 6 7 8 9}"

# PANO_CAM=1 selects cam1 (CAMERA_*); default cam2 (CAMERA2_*). Same TrackMix model.
if [[ "${PANO_CAM:-2}" == 1 ]]; then CP=CAMERA_; else CP=CAMERA2_; fi
v="${CP}IP"; CAM_IP="${!v:?${CP}IP not set}"
v="${CP}USER"; CAM_USER="${!v:?}"
v="${CP}PASSWORD"; CAM_PASS="${!v:?}"

mkdir -p "${OUT_DIR}"

TOKEN=$(curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=Login" \
  -H "Content-Type: application/json" \
  -d "[{\"cmd\":\"Login\",\"action\":0,\"param\":{\"User\":{\"userName\":\"${CAM_USER}\",\"password\":\"${CAM_PASS}\"}}}]" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d[0]['value']['Token']['name'])")

rapi() { curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=${1}&token=${TOKEN}" -H "Content-Type: application/json" -d "${2}"; }
# Always release the session: the camera has a small session limit and tokens
# live ~1h, so a caller looping every 30s exhausted it in ~15 min
# ("max session", 2026-09-23) when this script never logged out.
trap 'rapi Logout "[{\"cmd\":\"Logout\",\"action\":0,\"param\":{}}]" >/dev/null 2>&1 || true' EXIT
snap() { curl -sf "http://${CAM_IP}/cgi-bin/api.cgi?cmd=Snap&channel=0&rs=${RANDOM}&token=${TOKEN}" -o "${1}"; }
ppos() { rapi GetPtzCurPos '[{"cmd":"GetPtzCurPos","action":0,"param":{"channel":0,"PtzCurPos":{"channel":0}}}]' | grep -o '"Ppos" *: *[0-9]*' | grep -o '[0-9]*$'; }

# Block until the pan position stops changing. A fixed sleep can't cover
# both cases: the 72deg hops arrive well within 2s, but the ~288deg swing
# back to stop 0 doesn't -- measured 2026-09-23, a fixed 2s settle snapped
# stop 0 mid-swing (pointing ~146deg off) on every cycle.
wait_arrival() {
  local last="" p tries=0
  sleep 0.3   # let the move start before the first read
  while (( tries++ < 60 )); do
    p=$(ppos || true)
    [[ -n "$p" && "$p" == "$last" ]] && return 0
    last="$p"
    sleep 0.25
  done
  echo "WARNING: pan position never settled" >&2
}

t0=$(date +%s.%N)
for i in "${!PRESET_IDS[@]}"; do
  pid="${PRESET_IDS[$i]}"
  rapi PtzCtrl "[{\"cmd\":\"PtzCtrl\",\"action\":0,\"param\":{\"channel\":0,\"op\":\"ToPos\",\"speed\":${PTZ_SPEED},\"id\":${pid}}}]" >/dev/null
  wait_arrival
  sleep "${SETTLE_SEC}"   # post-arrival settle: vibration damping only
  fn="${OUT_DIR}/frame_$(printf '%02d' "${i}").jpg"
  snap "${fn}"
  echo "[$(date +%H:%M:%S)] stop ${i} (preset ${pid}) -> ${fn}"
done
t1=$(date +%s.%N)
echo "capture phase: $(echo "$t1 - $t0" | bc)s for ${#PRESET_IDS[@]} stops"
echo "OUT_DIR=${OUT_DIR}"
