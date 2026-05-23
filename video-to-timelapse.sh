#!/usr/bin/env bash
# video-to-timelapse.sh — create a timelapse clip from a segment of a normal-speed video
#
# Usage:
#   ./video-to-timelapse.sh <input_video> <start> <end> [speed]
#
#   input_video  path to source video
#   start        segment start  (HH:MM:SS or MM:SS or seconds)
#   end          segment end    (HH:MM:SS or MM:SS or seconds)
#   speed        speedup factor, default 20 (20x = 1 min of footage → 3 sec)
#
# Examples:
#   ./video-to-timelapse.sh storm_front.mp4 4:15 10:00
#   ./video-to-timelapse.sh storm_front.mp4 4:15 10:00 30
#   ./video-to-timelapse.sh storm_front.mp4 0 120 15

set -euo pipefail

INPUT="${1:-}"
START="${2:-}"
END="${3:-}"
SPEED="${4:-20}"

if [[ -z "$INPUT" || -z "$START" || -z "$END" ]]; then
  echo "Usage: $0 <input_video> <start> <end> [speed_multiplier]"
  echo "  start/end: MM:SS or HH:MM:SS or raw seconds"
  echo "  speed:     default 20  (20x → 1 min becomes 3 sec)"
  exit 1
fi

if [[ ! -f "$INPUT" ]]; then
  echo "ERROR: file not found: $INPUT" >&2
  exit 1
fi

# Output alongside input, stamped with segment and speed
BASENAME="${INPUT%.*}"
EXT="${INPUT##*.}"
START_SAFE="${START//:/-}"
END_SAFE="${END//:/-}"
OUTPUT="${BASENAME}__timelapse_${START_SAFE}-${END_SAFE}_${SPEED}x.${EXT}"

# Human-readable duration estimate
to_seconds() {
  local t="$1"
  IFS=: read -ra parts <<< "$t"
  local s=0
  for p in "${parts[@]}"; do s=$(( s * 60 + ${p%.*} )); done
  echo "$s"
}
SEG=$(( $(to_seconds "$END") - $(to_seconds "$START") ))
OUT_SEC=$(echo "scale=1; $SEG / $SPEED" | bc)

echo "Input:    $INPUT"
echo "Segment:  $START → $END  (${SEG}s)"
echo "Speed:    ${SPEED}x"
echo "Output:   ~${OUT_SEC}s  →  $OUTPUT"
echo ""

ffmpeg -y \
  -ss "$START" -to "$END" \
  -i "$INPUT" \
  -vf "setpts=PTS/${SPEED}" \
  -an \
  -c:v libx264 -preset medium -crf 22 -threads 2 -pix_fmt yuv420p \
  "$OUTPUT"

echo ""
echo "Done: $OUTPUT"
