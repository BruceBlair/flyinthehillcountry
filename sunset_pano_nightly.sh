#!/usr/bin/env bash
# Nightly sunset panoramic timelapse on both TrackMix cameras (cron, ~18:00).
#
# Runs cam1 and cam2 back-to-back sweeps (interval 0, tilted preset sets) in
# parallel from launch until sunset + AFTER_MIN, computed for today at the GTN
# site, then each run encodes its own MP4. Exits without capturing after
# LAST_DATE so the cron entry can't run forever if nobody removes it.
#
# Usage: ./sunset_pano_nightly.sh            (env LAST_DATE=YYYYMMDD, AFTER_MIN=50)
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
LAST_DATE="${LAST_DATE:-20261004}"
AFTER_MIN="${AFTER_MIN:-50}"
LOG=/volume1/pano_test/nightly.log
log() { echo "[$(date '+%F %T')] $*" >>"$LOG"; }

today=$(date +%Y%m%d)
if (( today > LAST_DATE )); then log "past LAST_DATE $LAST_DATE; not capturing"; exit 0; fi

# NOAA approximate sunset (alt -0.833deg) for the site, local clock time.
END=$(python3 - "$AFTER_MIN" <<'EOF'
import math, sys, datetime as dt, time
lat, lon = 29.997, -98.098
d = dt.date.today(); N = d.timetuple().tm_yday
g = 2 * math.pi / 365 * (N - 1)
eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
               - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
dec = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
       + 0.000907 * math.sin(2 * g))
ha = math.degrees(math.acos((math.sin(math.radians(-0.833)) - math.sin(math.radians(lat)) * math.sin(dec))
                            / (math.cos(math.radians(lat)) * math.cos(dec))))
utc_min = 720 - 4 * (lon - ha) - eq
offset = -(time.altzone if time.localtime().tm_isdst else time.timezone) / 60
m = round(utc_min + offset) + int(sys.argv[1])
print(f"{m // 60:02d}:{m % 60:02d}")
EOF
)
log "start; sunset+${AFTER_MIN}min = $END"

cd "$DIR"
PANO_CAM=2 PANO_PRESETS="11 12 13 14 15" PANO_PRESET_JSON="$DIR/data/pano_presets_cam2_tilt16.json" \
  ./pano_fast_timelapse.sh "$END" 0 1.5 "/volume1/pano_test/sunset_${today}_cam2" >/dev/null 2>&1 &
p2=$!
PANO_CAM=1 PANO_PRESETS="20 21 22 23 24" PANO_PRESET_JSON="$DIR/data/pano_presets_cam1_tilt16.json" \
  ./pano_fast_timelapse.sh "$END" 0 1.5 "/volume1/pano_test/sunset_${today}_cam1" >/dev/null 2>&1 &
p1=$!
wait $p2; r2=$?
wait $p1; r1=$?
for c in cam1 cam2; do
  log "$c: $(grep -c 'captured in' "/volume1/pano_test/sunset_${today}_$c/timelapse.log" 2>/dev/null) cycles, $(grep -c FAILED "/volume1/pano_test/sunset_${today}_$c/timelapse.log" 2>/dev/null) failed, $(tail -1 "/volume1/pano_test/sunset_${today}_$c/timelapse.log" 2>/dev/null)"
done
log "done (exit cam2=$r2 cam1=$r1)"
