#!/bin/bash
# /volume1/scripts/daily_timelapse.sh  (deploy to NAS; source in weather-station/)
#
# Runs nightly at 00:30 for the PREVIOUS day's Frigate recordings.
# Splits the day into 4 solar-relative sections:
#   sunrise, day_1 (sunrise+30m → solar noon), day_2 (noon → sunset-30m), sunset
#
# GPS coords sourced from weather-station/.env:
#   LATITUDE=30.01012
#   LONGITUDE=-98.03162

set -euo pipefail

REPO="/home/HighlyReflective/weather-station"
ENV_FILE="$REPO/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

DATE=$(date -d "yesterday" +%Y%m%d)
LAT="${LATITUDE:-}"
LON="${LONGITUDE:-}"

if [ -z "$LAT" ] || [ -z "$LON" ]; then
  echo "ERROR: LATITUDE/LONGITUDE not set in $ENV_FILE" >&2
  exit 1
fi

DATE_DASH="${DATE:0:4}-${DATE:4:2}-${DATE:6:2}"
# Frigate dirs are UTC dates; file mtimes are local (CDT).
# A CDT calendar day spans two UTC date dirs (same-day UTC 05-23 + next-day UTC 00-04).
# Search both to catch sunset recordings that spill into the next UTC date directory.
DATE_NEXT_DASH=$(date -d "${DATE_DASH} + 1 day" +%Y-%m-%d)
RECORDINGS="/volume1/docker/frigate/media/recordings"
SRC_ROOT="${RECORDINGS}/${DATE_DASH}"
SRC_ROOT_NEXT="${RECORDINGS}/${DATE_NEXT_DASH}"
OUT_DIR="/volume1/camera_raw/timelapse/${DATE}"
mkdir -p "$OUT_DIR"

echo "[$(date -u +%FT%TZ)] daily_timelapse.sh: processing $DATE"

# --- Get sunrise/sunset (seconds since local midnight) ---
read -r SUNRISE SUNSET < <(python3 "$REPO/sun_times.py" "$LAT" "$LON" "$DATE")

SOLAR_NOON=$(( (SUNRISE + SUNSET) / 2 ))
SR_START=$(( SUNRISE - 1800 ))
SR_END=$(( SUNRISE + 1800 ))
SS_START=$(( SUNSET  - 1800 ))
SS_END=$(( SUNSET   + 1800 ))

sec_to_hms() { printf '%02d:%02d:%02d\n' $(($1/3600)) $(($1%3600/60)) $(($1%60)); }

declare -A WIN_START=(
  [sunrise]="$SR_START"
  [day_1]="$SR_END"
  [day_2]="$SOLAR_NOON"
  [sunset]="$SS_START"
)
declare -A WIN_END=(
  [sunrise]="$SR_END"
  [day_1]="$SOLAR_NOON"
  [day_2]="$SS_START"
  [sunset]="$SS_END"
)

if [ ! -d "$SRC_ROOT" ]; then
  echo "WARNING: Frigate recording dir not found: $SRC_ROOT" >&2
fi

for SECTION in sunrise day_1 day_2 sunset; do
  START_HMS=$(sec_to_hms "${WIN_START[$SECTION]}")
  END_HMS=$(sec_to_hms "${WIN_END[$SECTION]}")

  FILELIST="/tmp/${DATE}_${SECTION}.txt"
  > "$FILELIST"

  # Search same-day UTC dir plus next-day UTC dir (sunset CDT window spills over midnight UTC)
  for DIR in "$SRC_ROOT" "$SRC_ROOT_NEXT"; do
    [ -d "$DIR" ] || continue
    find "$DIR" -path "*/trackmix_wide/*.mp4" \
         -newermt "${DATE_DASH} ${START_HMS}" \
         ! -newermt "${DATE_DASH} ${END_HMS}"
  done | sort | while IFS= read -r f; do
    printf "file '%s'\n" "$f" >> "$FILELIST"
  done

  if [ -s "$FILELIST" ]; then
    echo "  $SECTION: $(wc -l < "$FILELIST") segments → ${OUT_DIR}/${DATE}_${SECTION}.mp4"
    ffmpeg -y -f concat -safe 0 -i "$FILELIST" \
      -vf "setpts=0.05*PTS" -an \
      -c:v libx264 -preset medium -crf 23 \
      "${OUT_DIR}/${DATE}_${SECTION}.mp4" 2>&1 | tail -1
  else
    echo "  $SECTION: no segments in window ${START_HMS}–${END_HMS}"
  fi

  rm -f "$FILELIST"
done

# --- Register in manifest + availability, push to GitHub ---
python3 "$REPO/register_timelapse.py" "$DATE" "$OUT_DIR"

echo "[$(date -u +%FT%TZ)] daily_timelapse.sh: done"
