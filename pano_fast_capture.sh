#!/usr/bin/env bash
# Fast panorama sweep for timelapse use: jumps preset-to-preset (absolute
# positioning via ToPos) at high PTZ speed instead of nudging, pausing only
# long enough for the camera to settle before each snap. Requires presets
# saved by calibrate_pano_presets.sh (ids 5-10, ~71deg apart, ~355deg trip).
#
# Usage: ./pano_fast_capture.sh [settle_sec] [ptz_speed] [out_dir]
set -e
source /home/HighlyReflective/hithc-gtn-depot/.env

SETTLE_SEC="${1:-2}"
PTZ_SPEED="${2:-64}"   # 1-64; 64 = fastest
OUT_DIR="${3:-/volume1/gtn_inbox/panos_incoming/fast_$(date +%Y%m%d_%H%M%S)}"
PRESET_IDS=(5 6 7 8 9 10)

CAM_IP="${CAMERA2_IP:?CAMERA2_IP not set}"
CAM_USER="${CAMERA2_USER:?}"
CAM_PASS="${CAMERA2_PASSWORD:?}"

mkdir -p "${OUT_DIR}"

TOKEN=$(curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=Login" \
  -H "Content-Type: application/json" \
  -d "[{\"cmd\":\"Login\",\"action\":0,\"param\":{\"User\":{\"userName\":\"${CAM_USER}\",\"password\":\"${CAM_PASS}\"}}}]" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d[0]['value']['Token']['name'])")

rapi() { curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=${1}&token=${TOKEN}" -H "Content-Type: application/json" -d "${2}"; }
snap() { curl -sf "http://${CAM_IP}/cgi-bin/api.cgi?cmd=Snap&channel=0&rs=${RANDOM}&token=${TOKEN}" -o "${1}"; }

t0=$(date +%s.%N)
for i in "${!PRESET_IDS[@]}"; do
  pid="${PRESET_IDS[$i]}"
  rapi PtzCtrl "[{\"cmd\":\"PtzCtrl\",\"action\":0,\"param\":{\"channel\":0,\"op\":\"ToPos\",\"speed\":${PTZ_SPEED},\"id\":${pid}}}]" >/dev/null
  sleep "${SETTLE_SEC}"
  fn="${OUT_DIR}/frame_$(printf '%02d' "${i}").jpg"
  snap "${fn}"
  echo "[$(date +%H:%M:%S)] stop ${i} (preset ${pid}) -> ${fn}"
done
t1=$(date +%s.%N)
echo "capture phase: $(echo "$t1 - $t0" | bc)s for ${#PRESET_IDS[@]} stops"
echo "OUT_DIR=${OUT_DIR}"
