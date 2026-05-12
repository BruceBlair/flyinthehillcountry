# DEPRECATED — replaced by content_manager.py.
# This file is kept for reference only.
#!/usr/bin/env python3
"""
cull_ui.py — Ground Truth Network
Private LAN-only photo cull interface.  Run on the NAS; open in any browser
on the local network.  Do NOT expose port 8766 via cloudflare or port-forward.

Usage:
  python3 cull_ui.py
  python3 cull_ui.py --port 8766 --highlights-dir /volume1/highlights

Access: http://192.168.100.202:8766
"""

import argparse
import io
import json
import logging
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("cull-ui")

HIGHLIGHTS_DIR = Path("/volume1/highlights")
# Default sync script path — two levels up from this file → github-pages/sync.sh
_DEFAULT_SYNC = Path(__file__).parent.parent / "github-pages" / "sync.sh"
SYNC_SCRIPT: Path | None = _DEFAULT_SYNC if _DEFAULT_SYNC.exists() else None

_lock = threading.Lock()
_thumb_cache: dict[str, bytes] = {}

# ── Manifest ──────────────────────────────────────────────────────────────────

def load_manifest() -> dict:
    mf = HIGHLIGHTS_DIR / "manifest.json"
    return json.loads(mf.read_text()) if mf.exists() else {"entries": [], "updated": ""}

def save_manifest(m: dict) -> None:
    (HIGHLIGHTS_DIR / "manifest.json").write_text(json.dumps(m, indent=2))

def images_by_category() -> dict:
    cats: dict[str, list] = {}
    for e in load_manifest().get("entries", []):
        snap = e.get("snapshot")
        if not snap:
            continue
        cat = e.get("categories", ["unknown"])[0]
        cats.setdefault(cat, []).append({
            "path": snap,
            "timestamp": e.get("timestamp", ""),
            "label": e.get("label", ""),
            "score": e.get("nice_shot", 0),
        })
    for v in cats.values():
        v.sort(key=lambda x: x["timestamp"], reverse=True)
    return cats

def delete_snapshots(paths: list) -> int:
    paths_set = set(paths)
    deleted = 0
    with _lock:
        m = load_manifest()
        kept = []
        for e in m.get("entries", []):
            snap = e.get("snapshot")
            if snap and snap in paths_set:
                full = HIGHLIGHTS_DIR / snap
                if full.exists():
                    full.unlink()
                    deleted += 1
                    log.info(f"deleted  {snap}")
            else:
                kept.append(e)
        m["entries"] = kept
        save_manifest(m)
    if deleted:
        _trigger_sync()
    return deleted


def _trigger_sync() -> None:
    """Push the updated manifest to GitHub Pages in the background."""
    if not SYNC_SCRIPT:
        return
    try:
        subprocess.Popen(
            ["bash", str(SYNC_SCRIPT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info("sync.sh triggered in background")
    except Exception as e:
        log.warning(f"could not trigger sync.sh: {e}")

# ── Thumbnails ────────────────────────────────────────────────────────────────

def make_thumb(rel: str) -> bytes:
    if rel in _thumb_cache:
        return _thumb_cache[rel]
    try:
        from PIL import Image
        img = Image.open(HIGHLIGHTS_DIR / rel)
        img.thumbnail((240, 180))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=72)
        data = buf.getvalue()
    except Exception:
        data = b""
    _thumb_cache[rel] = data
    return data

# ── HTML — safe DOM construction, no innerHTML with dynamic data ──────────────

_HTML = b"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GTN Cull</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#111;color:#eee;font:14px/1.4 system-ui,sans-serif}
#bar{position:sticky;top:0;z-index:10;background:#1a1a1a;border-bottom:1px solid #333;
     padding:10px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
#bar h1{font-size:15px;font-weight:600;flex:1}
#count{color:#f66;font-weight:600;white-space:nowrap}
button{background:#c33;color:#fff;border:none;padding:7px 14px;border-radius:4px;
       cursor:pointer;font-size:13px}
button:disabled{background:#444;cursor:default}
#tabs{display:flex;gap:4px;padding:10px 16px;background:#181818;flex-wrap:wrap}
.tab{padding:5px 12px;border-radius:4px;cursor:pointer;background:#2a2a2a;
     border:1px solid #444;font-size:12px;user-select:none}
.tab.active{background:#0066cc;border-color:#0066cc}
.section{display:none;padding:12px 16px}
.section.active{display:block}
.sec-bar{display:flex;gap:10px;margin-bottom:10px;align-items:center}
.sec-bar .info{font-size:12px;color:#888;flex:1}
.sec-bar a{font-size:12px;color:#69f;cursor:pointer;text-decoration:underline}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}
.card{position:relative;cursor:pointer;border-radius:4px;overflow:hidden;
      border:3px solid transparent;transition:border-color .12s}
.card.selected{border-color:#f44}
.card img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block;background:#222}
.ts{position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,.65);
    padding:3px 6px;font-size:11px;color:#ccc;white-space:nowrap;overflow:hidden}
.badge{position:absolute;top:4px;right:4px;background:#f44;color:#fff;border-radius:50%;
       width:20px;height:20px;display:none;align-items:center;justify-content:center;
       font-size:13px;font-weight:bold}
.card.selected .badge{display:flex}
#toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);
       background:#2a7;color:#fff;padding:10px 22px;border-radius:6px;
       display:none;font-weight:600;z-index:99;text-align:center}
</style>
</head>
<body>
<div id="bar">
  <h1>GTN Photo Cull</h1>
  <span id="count">0 selected</span>
  <button id="delBtn" disabled onclick="confirmDelete()">Delete selected</button>
</div>
<div id="tabs"></div>
<div id="sections"></div>
<div id="toast"></div>
<script>
'use strict';
const selected = new Set();
let allData = {};

function fmtTs(ts) {
  // "20260503_193801" -> "2026-05-03 19:38"
  const m = ts.match(/^(\\d{4})(\\d{2})(\\d{2})_(\\d{2})(\\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : ts;
}

function makeCard(img) {
  const card = document.createElement('div');
  card.className = 'card';
  card.dataset.path = img.path;

  const photo = document.createElement('img');
  photo.src = '/thumb/' + encodeURIComponent(img.path);
  photo.loading = 'lazy';
  photo.alt = '';
  card.appendChild(photo);

  const ts = document.createElement('div');
  ts.className = 'ts';
  ts.textContent = fmtTs(img.timestamp);
  card.appendChild(ts);

  const badge = document.createElement('div');
  badge.className = 'badge';
  badge.textContent = '\\u2715';
  card.appendChild(badge);

  card.addEventListener('click', () => toggle(card, img.path));
  return card;
}

async function init() {
  const r = await fetch('/api/images');
  allData = await r.json();
  const tabs = document.getElementById('tabs');
  const sections = document.getElementById('sections');
  const cats = Object.keys(allData).sort();

  cats.forEach((cat, i) => {
    const imgs = allData[cat];

    const tab = document.createElement('div');
    tab.className = 'tab' + (i === 0 ? ' active' : '');
    tab.textContent = cat + ' (' + imgs.length + ')';
    tab.dataset.cat = cat;
    tab.addEventListener('click', () => switchTab(cat));
    tabs.appendChild(tab);

    const sec = document.createElement('div');
    sec.className = 'section' + (i === 0 ? ' active' : '');
    sec.id = 'sec-' + cat;

    const bar = document.createElement('div');
    bar.className = 'sec-bar';

    const info = document.createElement('span');
    info.className = 'info';
    info.textContent = imgs.length + ' photos';
    bar.appendChild(info);

    const selAll = document.createElement('a');
    selAll.textContent = 'select all';
    selAll.addEventListener('click', () => selectAll(cat));
    bar.appendChild(selAll);

    const deselAll = document.createElement('a');
    deselAll.textContent = 'deselect all';
    deselAll.addEventListener('click', () => deselectAll(cat));
    bar.appendChild(deselAll);

    sec.appendChild(bar);

    const grid = document.createElement('div');
    grid.className = 'grid';
    imgs.forEach(img => grid.appendChild(makeCard(img)));
    sec.appendChild(grid);
    sections.appendChild(sec);
  });
}

function switchTab(cat) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.cat === cat));
  document.querySelectorAll('.section').forEach(s => s.classList.toggle('active', s.id === 'sec-' + cat));
}

function toggle(card, path) {
  if (selected.has(path)) { selected.delete(path); card.classList.remove('selected'); }
  else { selected.add(path); card.classList.add('selected'); }
  updateCount();
}

function selectAll(cat) {
  allData[cat].forEach(img => {
    selected.add(img.path);
    document.querySelector(`.card[data-path="${CSS.escape(img.path)}"]`)?.classList.add('selected');
  });
  updateCount();
}

function deselectAll(cat) {
  allData[cat].forEach(img => {
    selected.delete(img.path);
    document.querySelector(`.card[data-path="${CSS.escape(img.path)}"]`)?.classList.remove('selected');
  });
  updateCount();
}

function updateCount() {
  document.getElementById('count').textContent = selected.size + ' selected';
  document.getElementById('delBtn').disabled = selected.size === 0;
}

async function confirmDelete() {
  if (!selected.size) return;
  if (!confirm('Permanently delete ' + selected.size + ' photo(s) from /volume1/highlights?\\n\\nThis cannot be undone.')) return;
  const paths = [...selected];
  const r = await fetch('/api/delete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({paths}),
  });
  const j = await r.json();
  const deletedSet = new Set(j.paths);
  j.paths.forEach(p => {
    document.querySelector(`.card[data-path="${CSS.escape(p)}"]`)?.remove();
    selected.delete(p);
  });
  // Keep allData in sync so select-all doesn't re-add removed items
  Object.keys(allData).forEach(cat => {
    allData[cat] = allData[cat].filter(img => !deletedSet.has(img.path));
  });
  document.querySelectorAll('.tab').forEach(tab => {
    const cat = tab.dataset.cat;
    const n = document.querySelectorAll('#sec-' + cat + ' .card').length;
    tab.textContent = cat + ' (' + n + ')';
  });
  updateCount();
  toast('Deleted ' + j.deleted + ' photo(s) - syncing to gallery now...');
}

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 5000);
}

init();
</script>
</body>
</html>
"""

# ── Path safety ───────────────────────────────────────────────────────────────

def safe_rel(raw: str) -> str | None:
    """Return rel path if it resolves inside HIGHLIGHTS_DIR, else None."""
    try:
        resolved = (HIGHLIGHTS_DIR / raw).resolve()
        resolved.relative_to(HIGHLIGHTS_DIR.resolve())
        return raw
    except Exception:
        return None

# ── HTTP handler ──────────────────────────────────────────────────────────────

class CullHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info(fmt % args)

    def do_GET(self):
        p = urlparse(self.path).path

        if p == "/":
            self._send(200, "text/html", _HTML)

        elif p == "/api/images":
            self._send(200, "application/json", json.dumps(images_by_category()).encode())

        elif p.startswith("/thumb/"):
            rel = safe_rel(unquote(p[len("/thumb/"):]))
            if not rel:
                self._send(403, "text/plain", b"Forbidden")
                return
            data = make_thumb(rel)
            self._send(200 if data else 404, "image/jpeg", data)

        elif p.startswith("/photo/"):
            rel = safe_rel(unquote(p[len("/photo/"):]))
            if not rel:
                self._send(403, "text/plain", b"Forbidden")
                return
            full = HIGHLIGHTS_DIR / rel
            self._send(200 if full.exists() else 404, "image/jpeg",
                       full.read_bytes() if full.exists() else b"")

        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self):
        if urlparse(self.path).path != "/api/delete":
            self._send(404, "text/plain", b"Not found")
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length))
        except Exception:
            self._send(400, "application/json", b'{"error":"bad json"}')
            return
        safe_paths = [r for p in payload.get("paths", []) if (r := safe_rel(p))]
        deleted = delete_snapshots(safe_paths)
        self._send(200, "application/json", json.dumps({"deleted": deleted, "paths": safe_paths}).encode())

    def _send(self, status: int, ct: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    global HIGHLIGHTS_DIR, SYNC_SCRIPT
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--highlights-dir", default=str(HIGHLIGHTS_DIR))
    ap.add_argument("--sync-script", default=str(SYNC_SCRIPT) if SYNC_SCRIPT else "",
                    help="Path to sync.sh (leave empty to disable background sync)")
    args = ap.parse_args()
    HIGHLIGHTS_DIR = Path(args.highlights_dir)
    SYNC_SCRIPT = Path(args.sync_script) if args.sync_script else None
    server = HTTPServer(("0.0.0.0", args.port), CullHandler)
    log.info(f"Cull UI  →  http://192.168.100.202:{args.port}")
    log.info(f"highlights: {HIGHLIGHTS_DIR}")
    log.info("Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
