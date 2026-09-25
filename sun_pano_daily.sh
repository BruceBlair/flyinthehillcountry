#!/usr/bin/env bash
# Daily sunrise / sunset panoramic timelapse on both TrackMix cameras (cron).
#
# Cron starts this early (fixed time); it computes today's sunrise or sunset
# at the GTN site, sleeps until the window opens, then runs cam1 and cam2
# back-to-back sweeps (interval 0, tilted preset sets) in parallel until the
# window closes. Each run encodes its own MP4.
#
# Usage: ./sunset_pano_nightly.sh sunrise|sunset
#   env BEFORE_MIN / AFTER_MIN override the window (defaults: sunrise 50/40,
#   sunset 80/50); LAST_DATE=YYYYMMDD stops capturing after that date (unset =
#   run every day).
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
EVENT="${1:?sunrise|sunset}"
case "$EVENT" in
  sunrise) BEFORE_MIN="${BEFORE_MIN:-50}"; AFTER_MIN="${AFTER_MIN:-40}" ;;
  sunset)  BEFORE_MIN="${BEFORE_MIN:-80}"; AFTER_MIN="${AFTER_MIN:-50}" ;;
  *) echo "usage: $0 sunrise|sunset" >&2; exit 2 ;;
esac
LOG=/volume1/pano_test/daily.log
log() { echo "[$(date '+%F %T')] $EVENT: $*" >>"$LOG"; }

today=$(date +%Y%m%d)
if [[ -n "${LAST_DATE:-}" ]] && (( today > LAST_DATE )); then log "past LAST_DATE $LAST_DATE; not capturing"; exit 0; fi

# NOAA approximate sunrise/sunset (alt -0.833deg) for the site, as epoch seconds.
EVENT_TS=$(python3 - "$EVENT" <<'EOF'
import math, sys, datetime as dt
lat, lon = 29.997, -98.098
d = dt.date.today(); N = d.timetuple().tm_yday
g = 2 * math.pi / 365 * (N - 1)
eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
               - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
dec = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
       + 0.000907 * math.sin(2 * g))
ha = math.degrees(math.acos((math.sin(math.radians(-0.833)) - math.sin(math.radians(lat)) * math.sin(dec))
                            / (math.cos(math.radians(lat)) * math.cos(dec))))
utc_min = 720 - 4 * (lon + (ha if sys.argv[1] == "sunrise" else -ha)) - eq
t = dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc) + dt.timedelta(minutes=utc_min)
print(int(t.timestamp()))
EOF
)
START_TS=$(( EVENT_TS - BEFORE_MIN * 60 ))
END=$(date -d "@$(( EVENT_TS + AFTER_MIN * 60 ))" +%H:%M)
log "$(date -d "@$EVENT_TS" +%H:%M); window $(date -d "@$START_TS" +%H:%M)-$END"
wait_s=$(( START_TS - $(date +%s) ))
(( wait_s > 0 )) && sleep "$wait_s"

cd "$DIR"
out() { echo "/volume1/pano_test/${EVENT}_${today}_$1"; }
PANO_CAM=2 PANO_PRESETS="11 12 13 14 15" PANO_PRESET_JSON="$DIR/data/pano_presets_cam2_tilt16.json" \
  ./pano_fast_timelapse.sh "$END" 0 1.5 "$(out cam2)" >/dev/null 2>&1 &
p2=$!
PANO_CAM=1 PANO_PRESETS="20 21 22 23 24" PANO_PRESET_JSON="$DIR/data/pano_presets_cam1_tilt16.json" \
  ./pano_fast_timelapse.sh "$END" 0 1.5 "$(out cam1)" >/dev/null 2>&1 &
p1=$!
wait $p2; r2=$?
wait $p1; r1=$?
for c in cam1 cam2; do
  L="$(out $c)/timelapse.log"
  log "$c: $(grep -c 'captured in' "$L" 2>/dev/null) cycles, $(grep -c FAILED "$L" 2>/dev/null) failed, $(tail -1 "$L" 2>/dev/null)"
done
log "done (exit cam2=$r2 cam1=$r1)"
