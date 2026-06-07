#!/usr/bin/env bash
# Sync highlights + site to your GitHub Pages repo and push.
#
# Setup (one-time):
#   1. Create a GitHub repo (e.g. username/ground-truth-gallery)
#   2. Enable GitHub Pages: Settings → Pages → Deploy from branch → main / root
#   3. Clone it somewhere on the NAS:
#        git clone https://github.com/USERNAME/REPO.git /volume1/github-pages-repo
#   4. Set PAGES_REPO below (or export it in your shell / cron env)
#
# Then run manually or via cron:
#   crontab -e
#   0 * * * * bash /path/to/weather-station/cron-scan-sync.sh >> /home/HighlyReflective/gtn-sync.log 2>&1

set -e

HIGHLIGHTS_SRC="${HIGHLIGHTS_SRC:-/volume1/highlights}"
PAGES_REPO="${PAGES_REPO:-/volume1/github-pages-repo}"
# Site files live in the project root (parent of this script's directory)
SITE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [ ! -d "$PAGES_REPO/.git" ]; then
  echo "ERROR: PAGES_REPO=$PAGES_REPO is not a git repo."
  echo "Clone your GitHub Pages repo there first, or set PAGES_REPO env var."
  exit 1
fi
if [ ! -d "$HIGHLIGHTS_SRC" ]; then
  echo "ERROR: highlights dir not found: $HIGHLIGHTS_SRC"
  exit 1
fi

# ── Copy site files ───────────────────────────────────────────────────────────
log "Copying site files..."
cp "$SITE_DIR/index.html"      "$PAGES_REPO/"
cp "$SITE_DIR/panoramas.html"  "$PAGES_REPO/"
cp "$SITE_DIR/nightwatch.html" "$PAGES_REPO/"
cp "$SITE_DIR/style.css"       "$PAGES_REPO/"
cp "$SITE_DIR/app.js"          "$PAGES_REPO/"

# ── Auth-hold gate: build rsync exclude list + filtered manifest ──────────────
log "Computing auth-held entries..."
TMPWORK=$(mktemp -d)
trap 'rm -rf "$TMPWORK"' EXIT
EXCLUDE_FILE="$TMPWORK/held.txt"
FILTERED_MF="$TMPWORK/manifest.json"

HIGHLIGHTS_SRC="$HIGHLIGHTS_SRC" \
EXCLUDE_FILE="$EXCLUDE_FILE"     \
FILTERED_MF="$FILTERED_MF"       \
python3 - <<'PYEOF'
import json, os, sys

src   = os.environ["HIGHLIGHTS_SRC"] + "/manifest.json"
excl  = os.environ["EXCLUDE_FILE"]
out   = os.environ["FILTERED_MF"]

try:
    m = json.loads(open(src).read())
except Exception:
    m = {"entries": []}

held = [e for e in m.get("entries", []) if (e.get("flags") or {}).get("auth_hold")]
kept = [e for e in m.get("entries", []) if not (e.get("flags") or {}).get("auth_hold")]

with open(excl, "w") as f:
    for e in held:
        snap = e.get("snapshot", "")
        if snap:
            f.write(snap + "\n")

m["entries"] = kept
json.dump(m, open(out, "w"), indent=2)

if held:
    print(f"Auth-held: {len(held)} entries excluded from sync", flush=True)
PYEOF

# ── Sync highlights (images + JSON; clips capped at 100 MB) ──────────────────
log "Syncing highlights from $HIGHLIGHTS_SRC..."
rsync -av --delete \
  --exclude=".git"             \
  --exclude="manifest.json"    \
  --exclude-from="$EXCLUDE_FILE" \
  --include="*/"               \
  --include="*.jpg"            \
  --include="*.json"           \
  --include="*.mp4"            \
  --exclude="*"                \
  --max-size=100m              \
  "$HIGHLIGHTS_SRC/" "$PAGES_REPO/"

# Write the filtered manifest (auth-held entries stripped)
cp "$FILTERED_MF" "$PAGES_REPO/manifest.json"
log "Manifest written ($(wc -c < "$FILTERED_MF") bytes, held entries excluded)"

# ── Commit and push ───────────────────────────────────────────────────────────
GIT=$(command -v git || echo /usr/bin/git)
cd "$PAGES_REPO"
"$GIT" add -A
if "$GIT" diff --cached --quiet; then
  log "Nothing new to commit."
  # Still pull so local stays in sync with remote
  "$GIT" pull --rebase --quiet || true
else
  COUNT=$("$GIT" diff --cached --name-only | grep -c '\.\(jpg\|mp4\)' || true)
  "$GIT" commit -m "highlights: $(date '+%Y-%m-%d %H:%M') (+${COUNT} media files)"
  "$GIT" pull --rebase --quiet || true
  "$GIT" push
  log "Pushed to GitHub Pages."
fi
