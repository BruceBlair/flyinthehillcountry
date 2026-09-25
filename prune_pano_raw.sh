#!/usr/bin/env bash
# Delete the raw per-stop frames (cycles/) of sunrise/sunset pano timelapse
# runs once they are older than KEEP_DAYS, keeping the stitched panos/ and the
# MP4. Only prunes runs whose video was actually built, so a failed encode
# never loses the only copy of the source frames. Raw frames are only needed
# to re-stitch (e.g. after a lens refit), which a week covers.
#
# Usage: ./prune_pano_raw.sh [--dry-run]     (env KEEP_DAYS, default 7)
set -u
KEEP_DAYS="${KEEP_DAYS:-7}"
ROOT="${PANO_ROOT:-/volume1/pano_test}"
LOG="$ROOT/daily.log"
dry=0; [[ "${1:-}" == --dry-run ]] && dry=1

find "$ROOT" -mindepth 2 -maxdepth 2 -type d -name cycles -mtime +$((KEEP_DAYS - 1)) \
     -path "$ROOT/sun[rs]*_*/cycles" | sort | while read -r c; do
  run=$(dirname "$c")
  [[ -s "$run/pano_timelapse.mp4" ]] || { echo "skip (no video): $run"; continue; }
  size=$(du -sh "$c" | cut -f1)
  if (( dry )); then
    echo "would delete $c ($size)"
  else
    rm -rf "$c" && echo "[$(date '+%F %T')] prune: deleted $c ($size)" >>"$LOG"
  fi
done
