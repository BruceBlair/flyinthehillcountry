#!/usr/bin/env bash
# One-time calibration: sweep cam2 to N evenly-spaced stops using the same
# nudge timing validated in pano_timelapse.sh (~71deg/stop, 6 stops, ~355deg
# trip), and save each stop as a PTZ preset. Run once; pano_fast_capture.sh
# then jumps preset-to-preset via ToPos for fast repeatable capture cycles.
set -e
source /home/HighlyReflective/hithc-gtn-depot/.env

STEPS=6
NUDGES_PER_STEP=4
STEP_SEC=0.44   # trimmed ~11% from 0.497 to stay clear of the right-side mechanical stop
PTZ_SPEED=5
STABILIZE=2
PRESET_IDS=(5 6 7 8 9 10)
PRESET_NAMES=(pano1 pano2 pano3 pano4 pano5 pano6)

CAM_IP="${CAMERA2_IP:?CAMERA2_IP not set}"
CAM_USER="${CAMERA2_USER:?}"
CAM_PASS="${CAMERA2_PASSWORD:?}"

TOKEN=$(curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=Login" \
  -H "Content-Type: application/json" \
  -d "[{\"cmd\":\"Login\",\"action\":0,\"param\":{\"User\":{\"userName\":\"${CAM_USER}\",\"password\":\"${CAM_PASS}\"}}}]" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d[0]['value']['Token']['name'])")

rapi() { curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=${1}&token=${TOKEN}" -H "Content-Type: application/json" -d "${2}"; }
ptz() { rapi PtzCtrl "[{\"cmd\":\"PtzCtrl\",\"action\":0,\"param\":{\"channel\":0,\"op\":\"${1}\",\"speed\":${PTZ_SPEED}}}]"; }

echo "[$(date +%H:%M:%S)] driving to start position"
ptz Left; sleep 4.5; ptz Stop; sleep "${STABILIZE}"

for i in $(seq 0 $((STEPS - 1))); do
  pid="${PRESET_IDS[$i]}"
  pname="${PRESET_NAMES[$i]}"
  echo "[$(date +%H:%M:%S)] stop ${i}: saving preset id=${pid} name=${pname}"
  rapi SetPtzPreset "[{\"cmd\":\"SetPtzPreset\",\"action\":0,\"param\":{\"channel\":0,\"PtzPreset\":{\"channel\":0,\"enable\":1,\"id\":${pid},\"name\":\"${pname}\"}}}]" >/dev/null

  if [ "${i}" -lt $((STEPS - 1)) ]; then
    for n in $(seq 1 "${NUDGES_PER_STEP}"); do
      ptz Right; sleep "${STEP_SEC}"; ptz Stop; sleep "${STABILIZE}"
    done
  fi
done

echo "[$(date +%H:%M:%S)] calibration complete: 6 presets saved (ids 5-10)"
