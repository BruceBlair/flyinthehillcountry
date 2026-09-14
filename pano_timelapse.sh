#!/usr/bin/env bash
#
# Repeating panorama timelapse: sweeps a TrackMix PTZ camera across its arc,
# captures a frame series, swings back to start, and repeats until a
# duration elapses. Frame capture for every cycle happens back-to-back with
# no stitching in between (stitching is deferred to a second pass after the
# capture loop ends) so the swing-back cadence is limited only by the PTZ
# hardware, not by CPU-bound Hugin work.
#
# Usage:
#   ./pano_timelapse.sh <camera:1|2> <duration_min> [shots] [nudges_per_step] [move_sec] [speed] [settle_sec] [out_dir]
#
# camera           1 = existing TrackMix (CAMERA_IP),  2 = new TrackMix (CAMERA2_IP)
# duration_min     total wall-clock run time; the in-progress cycle is allowed to
#                  finish before exit, so actual runtime may exceed this slightly
# shots            frames per sweep, i.e. stops across the whole trip (default 6)
# nudges_per_step  PTZ nudges between each stop — bigger gap = fewer, wider stops
#                  (default 4; ~15deg per nudge @ default speed, so ~60deg/stop,
#                  6 shots x 4 nudges = full ~300deg trip in 5 gaps)
# move_sec         nudge duration per step in seconds (default 0.420 ~= 15 deg @ speed 5)
# speed            PTZ speed 1-64 (default 5)
# settle_sec       stabilize time after each nudge before the next snap (default 2)
# out_dir          where finished panorama JPEGs land (default INBOX below)

set -e
source /home/HighlyReflective/hithc-gtn-depot/.env

# ── Args ──────────────────────────────────────────────────────────────────────
CAMERA_SEL="${1:?usage: pano_timelapse.sh <camera:1|2> <duration_min> [shots] [nudges_per_step] [move_sec] [speed] [settle_sec] [out_dir]}"
DURATION_MIN="${2:?duration_min required}"
STEPS="${3:-6}"
NUDGES_PER_STEP="${4:-4}"
STEP_SEC="${5:-0.420}"
PTZ_SPEED="${6:-5}"
STABILIZE="${7:-2}"
INBOX="${8:-/volume1/gtn_inbox/panos_incoming}"

case "${CAMERA_SEL}" in
  1)
    CAM_IP="${CAMERA_IP}"
    CAM_USER="${CAMERA_USER}"
    CAM_PASS="${CAMERA_PASSWORD}"
    CAM_LABEL="cam1"
    ;;
  2)
    CAM_IP="${CAMERA2_IP:?CAMERA2_IP not set in .env}"
    CAM_USER="${CAMERA2_USER:?CAMERA2_USER not set in .env}"
    CAM_PASS="${CAMERA2_PASSWORD:?CAMERA2_PASSWORD not set in .env}"
    CAM_LABEL="cam2"
    ;;
  *)
    echo "ERROR: camera must be 1 or 2, got '${CAMERA_SEL}'" >&2
    exit 1
    ;;
esac

SESSION_TS="$(date +%Y%m%d_%H%M%S)"
# /tmp on this NAS is tmpfs (RAM-backed) — a multi-cycle run buffering full-res
# JPEG/TIFF frames there competes with everything else for memory and was a
# major contributor to an OOM-driven system slowdown during a live run.
# Raw frames go to real disk instead; only small transient files should use /tmp.
WORK_DIR="${INBOX}/.work_${CAM_LABEL}_${SESSION_TS}"
SESSION_OUT="${INBOX}/timelapse_${CAM_LABEL}_${SESSION_TS}"
END_EPOCH=$(( $(date +%s) + DURATION_MIN * 60 ))

mkdir -p "${WORK_DIR}" || { echo "ERROR: cannot create work dir ${WORK_DIR}" >&2; exit 1; }
mkdir -p "${SESSION_OUT}" || { echo "ERROR: cannot create output dir ${SESSION_OUT} — is /volume1 mounted and writable?" >&2; exit 1; }

# ── Auth ──────────────────────────────────────────────────────────────────────
TOKEN=$(curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=Login" \
  -H "Content-Type: application/json" \
  -d "[{\"cmd\":\"Login\",\"action\":0,\"param\":{\"User\":{\"userName\":\"${CAM_USER}\",\"password\":\"${CAM_PASS}\"}}}]" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
if not data or 'value' not in data[0]:
    code = data[0].get('error', {}).get('rspCode', '?') if data else '?'
    sys.exit(f'Camera login failed (rspCode={code}). Check CAMERA_USER/CAMERA_PASSWORD.')
print(data[0]['value']['Token']['name'])
")

rapi() {
  curl -sf -X POST "http://${CAM_IP}/api.cgi?cmd=${1}&token=${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${2}"
}

ptz() {
  rapi PtzCtrl \
    "[{\"cmd\":\"PtzCtrl\",\"action\":0,\"param\":{\"channel\":0,\"op\":\"${1}\",\"speed\":${PTZ_SPEED}}}]"
}

snap() {
  curl -sf \
    "http://${CAM_IP}/cgi-bin/api.cgi?cmd=Snap&channel=0&rs=${RANDOM}&token=${TOKEN}" \
    -o "${1}"
}

# ── 1. Wide lens + fixed exposure ─────────────────────────────────────────────

rapi SetAiCfg \
  '[{"cmd":"SetAiCfg","action":0,"param":{"channel":0,"AiDetectType":{"people":0,"vehicle":0,"dog_cat":0},"trackType":{"people":0,"vehicle":0,"dog_cat":0}}}]'

rapi SetAutoTrackCfg \
  '[{"cmd":"SetAutoTrackCfg","action":0,"param":{"channel":0,"AutoTrackCfg":{"enable":0}}}]'

rapi SetZoomFocus \
  '[{"cmd":"SetZoomFocus","action":0,"param":{"channel":0,"ZoomFocus":{"zoom":{"pos":0},"focus":{"pos":0}}}}]'
sleep 1

rapi SetIsp \
  '[{"cmd":"SetIsp","action":0,"param":{"channel":0,"Isp":{"antiFlicker":"Close","blc":0,"wdr":0}}}]'

rapi SetImage \
  '[{"cmd":"SetImage","action":0,"param":{"channel":0,"Image":{"AutoShutter":0,"Shutter":"1/250","AutoGain":0,"Gain":50}}}]'

sleep 1

# ── 2. Capture phase: repeat sweep-out-and-back until duration elapses ───────
# Stitching is NOT done here — only raw frame capture — so the swing-back
# between series is limited by PTZ settle time, not Hugin CPU time.

cycle=0
while [ "$(date +%s)" -lt "${END_EPOCH}" ]; do
  cycle_padded=$(printf '%04d' "${cycle}")
  FRAME_DIR="${WORK_DIR}/cycle_${cycle_padded}"
  mkdir -p "${FRAME_DIR}"

  echo "[$(date +%H:%M:%S)] cycle ${cycle_padded}: driving to start position"
  ptz Left
  sleep 4.5
  ptz Stop
  sleep "${STABILIZE}"

  for i in $(seq 0 $((STEPS - 1))); do
    snap "${FRAME_DIR}/frame_$(printf '%04d' "${i}").jpg"

    if [ "${i}" -lt $((STEPS - 1)) ]; then
      for n in $(seq 1 "${NUDGES_PER_STEP}"); do
        ptz Right
        sleep "${STEP_SEC}"
        ptz Stop
        sleep "${STABILIZE}"
      done
    fi
  done

  echo "[$(date +%H:%M:%S)] cycle ${cycle_padded}: capture done, swinging back"
  cycle=$((cycle + 1))
done

# Return to home preset (best-effort; preset 0 may not exist)
rapi PtzCtrl \
  '[{"cmd":"PtzCtrl","action":0,"param":{"channel":0,"op":"ToPos","speed":5,"id":0}}]' || true

# Re-enable AI tracking
rapi SetAiCfg \
  '[{"cmd":"SetAiCfg","action":0,"param":{"channel":0,"AiDetectType":{"people":1,"vehicle":1,"dog_cat":1},"trackType":{"people":1,"vehicle":1,"dog_cat":1}}}]' || true

echo "[$(date +%H:%M:%S)] capture phase complete: ${cycle} cycles. Stitching..."

# ── 3. Stitch phase: process each cycle's frames into a panorama JPEG ────────
# A stitch failure on one cycle is logged and skipped rather than aborting
# the whole batch — a bad sweep (glare, a bird crossing frame) shouldn't
# lose every other cycle's panorama.

stitch_cycle() {
  local frame_dir="$1"
  local out_jpg="$2"
  local pto="${frame_dir}/pano.pto"

  pto_gen \
    --output="${pto}" \
    --projection=1 \
    --fov=120 \
    "${frame_dir}"/frame_*.jpg

  pano_modify \
    --projection=1 \
    --canvas=AUTO \
    --crop=AUTO \
    --output="${pto}" \
    "${pto}"

  cpfind \
    --multirow \
    --celeste \
    --output="${pto}" \
    "${pto}"

  cpclean \
    --output="${pto}" \
    "${pto}"

  if command -v pto_var &>/dev/null; then
    pto_var --opt y,p,r --output="${pto}" "${pto}"
    autooptimiser -a --output="${pto}" "${pto}"
  else
    autooptimiser -a --output="${pto}" "${pto}"
  fi

  pano_modify \
    --projection=1 \
    --canvas=AUTO \
    --crop=AUTO \
    --output="${pto}" \
    "${pto}"

  nona \
    -m TIFF_m \
    -o "${frame_dir}/remap" \
    "${pto}"

  enblend \
    --fine-mask \
    --compression=90 \
    -o "${out_jpg}" \
    "${frame_dir}"/remap*.tif
}

# 900s (15min) cap per cycle — observed live: a bad frame set (insufficient
# control points / degenerate geometry) can send pano_modify or autooptimiser
# into a near-infinite search rather than failing fast, hanging the whole
# batch for the rest of the run. timeout kills that one cycle's pipeline and
# moves on instead of blocking every cycle after it.
STITCH_TIMEOUT_SEC=900

for FRAME_DIR in "${WORK_DIR}"/cycle_*/; do
  cycle_name="$(basename "${FRAME_DIR}")"
  OUT_JPG="${SESSION_OUT}/${cycle_name}.jpg"

  if timeout "${STITCH_TIMEOUT_SEC}" bash -c "set -e; $(declare -f stitch_cycle); stitch_cycle '${FRAME_DIR}' '${OUT_JPG}'" 2>"${FRAME_DIR}/stitch.log"; then
    echo "[$(date +%H:%M:%S)] ${cycle_name}: stitched -> ${OUT_JPG}"
  else
    rc=$?
    if [ "${rc}" -eq 124 ]; then
      echo "[$(date +%H:%M:%S)] ${cycle_name}: STITCH TIMED OUT after ${STITCH_TIMEOUT_SEC}s, skipped (see ${FRAME_DIR}/stitch.log)" >&2
    else
      echo "[$(date +%H:%M:%S)] ${cycle_name}: STITCH FAILED, see ${FRAME_DIR}/stitch.log" >&2
    fi
  fi
done

rm -rf "${WORK_DIR}"
echo "Timelapse session complete: ${SESSION_OUT}"
