#!/usr/bin/env bash
# cron-scan-sync.sh — Ground Truth Network hourly pipeline
#
# Crontab entry:
#   0 * * * * bash /home/HighlyReflective/weather-station/cron-scan-sync.sh >> /home/HighlyReflective/gtn-sync.log 2>&1

set -uo pipefail

SYNC_SH="/home/HighlyReflective/weather-station/github-pages/sync.sh"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Backfill Frigate wildlife/detection events from the past 2 days
START_DATE=$(date -d "2 days ago" +%Y-%m-%d)
log "Backfilling Frigate events since $START_DATE ..."
docker exec highlight-curator \
  python3 /app/backfill-highlights.py --mode events --start-date "$START_DATE" \
  --frigate-db /frigate-config/frigate.db --frigate-api http://192.168.100.202:5000 \
  --highlights-dir /highlights \
  || log "WARN: backfill step failed (continuing)"
log "Backfill complete."

# Score new snapshots (skips already-scored entries)
log "Scoring new snapshots ..."
docker exec highlight-curator \
  python3 /app/score_images.py --highlights-dir /highlights \
  || log "WARN: scoring failed (continuing)"
log "Scoring complete."

# Cull to keep only the best shots per event
log "Culling to top shots per event ..."
docker exec highlight-curator \
  python3 /app/cull_highlights.py --highlights-dir /highlights \
  || log "WARN: cull failed (continuing)"
log "Cull complete."

# Optional: generate slow-motion reel from recent clips
log "Generating slow-motion reel ..."
docker exec ffmpeg-processor /scripts/generate-slowmo-reel.sh 2>&1 \
  || log "WARN: reel generation failed (continuing)"

# Sync highlights + site files to GitHub Pages
log "Syncing to GitHub Pages ..."
bash "$SYNC_SH" || log "ERROR: sync.sh failed"
log "Sync complete."
