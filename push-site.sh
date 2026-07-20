#!/usr/bin/env bash
# push-site.sh — deploy hithc-gtn-depot/site/ to the senselayer.io GitHub Pages repo.
#
# Setup (one-time, already done as of this plan's Task 5):
#   git clone https://github.com/BruceBlair/ground-truth-gallery.git /volume1/senselayer-pages-repo
#
# Usage: bash push-site.sh
# Cron:  0 * * * * bash /home/HighlyReflective/hithc-gtn-depot/push-site.sh >> /home/HighlyReflective/site-deploy.log 2>&1

set -euo pipefail

SITE_SRC="$(cd "$(dirname "$0")/site" && pwd)"
PAGES_REPO="${PAGES_REPO:-/volume1/senselayer-pages-repo}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if [ ! -d "$PAGES_REPO/.git" ]; then
  echo "ERROR: PAGES_REPO=$PAGES_REPO is not a git repo. Clone it first (see header comment)."
  exit 1
fi

log "Syncing site files from $SITE_SRC to $PAGES_REPO ..."
rsync -av --delete \
  --exclude=".git" \
  "$SITE_SRC/" "$PAGES_REPO/"

cd "$PAGES_REPO"
git add -A
if git diff --cached --quiet; then
  log "Nothing new to deploy."
else
  git commit -m "site: deploy $(date '+%Y-%m-%d %H:%M') UTC"
  git push
  log "Deployed."
fi
