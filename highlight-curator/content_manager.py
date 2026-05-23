#!/usr/bin/env python3
"""
content_manager.py — Ground Truth Network
Unified content management UI: photo cull, timelapse building, pipeline status.
Replaces cull_ui.py. LAN-only — do NOT expose port 8766 publicly.

Usage:
  python3 content_manager.py
  python3 content_manager.py --port 8766 --highlights-dir /volume1/highlights \
      --frigate-dir /volume1/frigate --sync-script ../github-pages/sync.sh
"""

import argparse
import io
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

from manifest_io import atomic_write_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("content-manager")

HIGHLIGHTS_DIR = Path(os.getenv("HIGHLIGHTS_DIR", "/volume1/highlights"))
FRIGATE_DIR    = Path(os.getenv("FRIGATE_DIR",    "/volume1/docker/frigate/media/recordings"))
SYNC_SCRIPT: Path | None = None
FRAME_DURATION  = 0.12   # seconds per frame in timelapse (~8 fps)
GOLDEN_PAD_MIN  = 30     # minutes padding before/after sunrise or sunset
STATIC_DIR = Path(__file__).parent / "static"
CREDS_PATH = Path.home() / ".gtn" / "platform_creds.json"

_thumb_cache: dict[str, bytes] = {}
_manifest_lock = threading.Lock()

# ── Job state ─────────────────────────────────────────────────────────────────

_job_lock = threading.Lock()
_job: dict = {"state": "idle", "stage": "", "frames_done": 0, "frames_total": 0, "error": ""}
_build_queue: list[tuple] = []   # list of (start_dt, end_dt, label, interval_secs)


def _job_update(**kwargs) -> None:
    with _job_lock:
        _job.update(kwargs)


def _job_snapshot() -> dict:
    with _job_lock:
        return {**_job, "queued": len(_build_queue)}


# ── Manifest helpers ──────────────────────────────────────────────────────────

def load_manifest() -> dict:
    mf = HIGHLIGHTS_DIR / "manifest.json"
    return json.loads(mf.read_text()) if mf.exists() else {"entries": []}


def save_manifest(m: dict) -> None:
    with _manifest_lock:
        atomic_write_json(HIGHLIGHTS_DIR / "manifest.json", m)


_queue_lock = threading.Lock()


def load_queue() -> dict:
    qf = HIGHLIGHTS_DIR / "upload_queue.json"
    return json.loads(qf.read_text()) if qf.exists() else {"mode": "manual", "queue": []}


def save_queue(q: dict) -> None:
    with _queue_lock:
        atomic_write_json(HIGHLIGHTS_DIR / "upload_queue.json", q)


def load_creds() -> dict:
    _defaults = {"shutterstock": {}, "adobe_stock": {}, "anthropic": {}}
    if CREDS_PATH.exists():
        try:
            return json.loads(CREDS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("platform_creds.json is corrupt or unreadable; using defaults")
            return _defaults
    return _defaults


def save_creds(creds: dict) -> None:
    CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(CREDS_PATH, creds)
    CREDS_PATH.chmod(0o600)


def platform_status() -> dict:
    creds = load_creds()
    result = {}
    for platform in ("shutterstock", "adobe_stock"):
        pc = creds.get(platform, {})
        result[platform] = {
            "configured": bool(pc.get("client_id") or pc.get("api_key")),
            "has_token":  bool(pc.get("access_token")),
        }
    return result


_DEFAULT_FLAGS = {"crop": False, "enhance": False, "auth_hold": False}


def entries_with_defaults(m: dict) -> list:
    result = []
    for e in m.get("entries", []):
        entry = dict(e)
        entry["flags"] = {**_DEFAULT_FLAGS, **(entry.get("flags") or {})}
        entry.setdefault("crop_region", None)
        entry.setdefault("uploads", {})
        result.append(entry)
    return result


def find_entry_by_snapshot(m: dict, snapshot: str):
    for i, e in enumerate(m.get("entries", [])):
        if e.get("snapshot") == snapshot:
            return i, e
    return None, None


def patch_entry_flags(snapshot: str, flag_updates: dict) -> dict | None:
    from manifest_io import locked_manifest_update
    result = {}
    def _modify(m):
        _, entry = find_entry_by_snapshot(m, snapshot)
        if entry is None:
            return
        flags = entry.get("flags") or {"crop": False, "enhance": False, "auth_hold": False}
        entry["flags"] = flags
        for k, v in flag_updates.items():
            if k in {"crop", "enhance", "auth_hold"}:
                flags[k] = bool(v)
        result["flags"] = dict(flags)
    locked_manifest_update(HIGHLIGHTS_DIR / "manifest.json", _modify)
    return result if result else None


def _valid_crop_region(r) -> bool:
    if r is None:
        return True
    if not isinstance(r, dict):
        return False
    return all(isinstance(r.get(k), (int, float)) and 0.0 <= r[k] <= 1.0
               for k in ("x", "y", "w", "h"))


def patch_entry_crop_region(snapshot: str, region) -> dict | None:
    from manifest_io import locked_manifest_update
    result = {}
    def _modify(m):
        _, entry = find_entry_by_snapshot(m, snapshot)
        if entry is None:
            return
        entry["crop_region"] = region
        result["crop_region"] = region
    locked_manifest_update(HIGHLIGHTS_DIR / "manifest.json", _modify)
    return result if result else None


def images_by_category() -> dict:
    cats: dict[str, list] = {}
    for e in load_manifest().get("entries", []):
        snap = e.get("snapshot")
        if not snap:
            continue
        cat = (e.get("categories") or ["unknown"])[0]
        cats.setdefault(cat, []).append({
            "path":      snap,
            "timestamp": e.get("timestamp", ""),
            "label":     e.get("label", ""),
            "score":     e.get("nice_shot") or 0,
        })
    for v in cats.values():
        v.sort(key=lambda x: x["timestamp"], reverse=True)
    return cats


def delete_snapshots(paths: list[str]) -> int:
    paths_set = set(paths)
    deleted = 0
    with _manifest_lock:
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
        atomic_write_json(HIGHLIGHTS_DIR / "manifest.json", m)
    if deleted:
        _trigger_sync()
    return deleted


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


# ── Sync ──────────────────────────────────────────────────────────────────────

def _trigger_sync() -> None:
    if not SYNC_SCRIPT:
        return
    try:
        subprocess.Popen(["bash", str(SYNC_SCRIPT)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.info("sync.sh triggered")
    except Exception as e:
        log.warning(f"sync trigger failed: {e}")


# ── Path safety ───────────────────────────────────────────────────────────────

def safe_rel(raw: str) -> str | None:
    try:
        resolved = (HIGHLIGHTS_DIR / raw).resolve()
        resolved.relative_to(HIGHLIGHTS_DIR.resolve())
        return raw
    except Exception:
        return None


# ── HTML ──────────────────────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GTN Content Manager</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#111;color:#eee;font:14px/1.4 system-ui,sans-serif}
#topbar{position:sticky;top:0;z-index:10;background:#1a1a1a;border-bottom:1px solid #333;
        padding:10px 16px;display:flex;align-items:center;gap:12px}
#topbar h1{font-size:15px;font-weight:600;flex:1}
#maintabs{display:flex;gap:4px;padding:8px 16px;background:#181818;border-bottom:1px solid #2a2a2a}
.mtab{padding:6px 16px;border-radius:4px;cursor:pointer;background:#2a2a2a;
      border:1px solid #444;font-size:13px;user-select:none}
.mtab.active{background:#0055aa;border-color:#0055aa}
.panel{display:none;padding:14px 16px}
.panel.active{display:block}
button{background:#c33;color:#fff;border:none;padding:7px 14px;border-radius:4px;
       cursor:pointer;font-size:13px}
button:disabled{background:#444;cursor:default}
button.ok{background:#2a7}
#toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);
       background:#2a7;color:#fff;padding:10px 22px;border-radius:6px;
       display:none;font-weight:600;z-index:99}
/* photos */
#bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px}
#count{color:#f66;font-weight:600}
#subtabs{display:flex;gap:4px;margin-bottom:10px;flex-wrap:wrap}
.stab{padding:5px 12px;border-radius:4px;cursor:pointer;background:#2a2a2a;
      border:1px solid #444;font-size:12px;user-select:none}
.stab.active{background:#0055aa;border-color:#0055aa}
.section{display:none}
.section.active{display:block}
.sec-bar{display:flex;gap:10px;margin-bottom:8px;align-items:center;font-size:12px;color:#888}
.sec-bar a{color:#69f;cursor:pointer;text-decoration:underline}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}
.card{position:relative;cursor:pointer;border-radius:4px;overflow:hidden;
      border:3px solid transparent;transition:border-color .12s}
.card.selected{border-color:#f44}
.card img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block;background:#222}
.ts{position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,.65);
    padding:3px 6px;font-size:11px;color:#ccc;overflow:hidden}
.badge{position:absolute;top:4px;right:4px;background:#f44;color:#fff;border-radius:50%;
       width:20px;height:20px;display:none;align-items:center;justify-content:center;
       font-size:13px;font-weight:bold}
.card.selected .badge{display:flex}
/* timelapse */
.tl-form{background:#1e1e1e;border:1px solid #333;border-radius:6px;padding:14px;
         margin-bottom:12px;display:flex;flex-direction:column;gap:10px}
.tl-form label{font-size:13px;color:#aaa}
.tl-form input,.tl-form select{background:#2a2a2a;border:1px solid #444;color:#eee;
  padding:6px 10px;border-radius:4px;font-size:13px;width:100%}
.mode-btns{display:flex;gap:6px;margin-bottom:10px}
.mode-btn{padding:6px 14px;border-radius:4px;cursor:pointer;background:#2a2a2a;
          border:1px solid #444;font-size:13px;color:#eee;user-select:none}
.mode-btn.active{background:#0055aa;border-color:#0055aa}
.estimate{font-size:12px;color:#6cf;margin-top:4px}
.progress-wrap{height:6px;background:#333;border-radius:3px;overflow:hidden;
               margin-top:8px;display:none}
.progress-bar{height:100%;background:#0af;width:0%;transition:width .3s}
.tl-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));
          gap:10px;margin-top:16px}
.tl-card{background:#1e1e1e;border:2px solid #333;border-radius:6px;
          overflow:hidden;cursor:pointer;position:relative}
.tl-card.tl-selected{border-color:#0af}
.tl-card img{width:100%;aspect-ratio:16/9;object-fit:cover;background:#222}
.tl-card-info{padding:8px 10px;font-size:12px;color:#aaa;line-height:1.6}
.tl-card-play{position:absolute;top:6px;right:6px;background:rgba(0,0,0,.55);
  border:none;border-radius:50%;width:28px;height:28px;font-size:14px;
  color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center}
.tl-card-play:hover{background:rgba(0,170,255,.7)}
/* status */
.log-box{background:#0d0d0d;border:1px solid #2a2a2a;border-radius:4px;
         padding:10px;font:12px/1.6 monospace;color:#8f8;white-space:pre-wrap;
         max-height:400px;overflow-y:auto;margin-top:10px}
.status-row{display:flex;align-items:center;gap:12px;margin-bottom:12px}
</style>
</head>
<body>
<div id="topbar"><h1>GTN Content Manager</h1></div>
<div id="maintabs">
  <div class="mtab active" data-panel="photos">Photos</div>
  <div class="mtab" data-panel="timelapse">Timelapse</div>
  <div class="mtab" data-panel="status">Status</div>
</div>

<!-- PHOTOS -->
<div id="photos" class="panel active">
  <div id="bar">
    <span id="count">0 selected</span>
    <button id="delBtn" disabled onclick="confirmDelete()">Delete selected</button>
  </div>
  <div id="subtabs"></div>
  <div id="sections"></div>
</div>

<!-- TIMELAPSE -->
<div id="timelapse" class="panel">
  <div class="mode-btns">
    <div class="mode-btn active" data-mode="golden">Golden Hour</div>
    <div class="mode-btn" data-mode="fullday">Full Day</div>
    <div class="mode-btn" data-mode="custom">Custom Range</div>
  </div>

  <div class="tl-form" id="form-golden">
    <label>Date <input type="date" id="gh-date"></label>
    <label>Type
      <select id="gh-type">
        <option value="sunrise">Sunrise</option>
        <option value="sunset">Sunset</option>
      </select>
    </label>
  </div>

  <div class="tl-form" id="form-fullday" style="display:none">
    <label>Date <input type="date" id="fd-date"></label>
  </div>

  <div class="tl-form" id="form-custom" style="display:none">
    <label>Start <input type="datetime-local" id="cr-start"></label>
    <label>End   <input type="datetime-local" id="cr-end"></label>
    <label>Label <input type="text" id="cr-label" placeholder="storm_rollout"></label>
  </div>

  <div class="tl-form">
    <div style="display:flex;gap:16px;align-items:center">
      <label style="display:flex;align-items:center;gap:6px">
        <input type="radio" name="timing" value="interval" checked onchange="timingMode()">
        Interval
      </label>
      <label style="display:flex;align-items:center;gap:6px">
        <input type="radio" name="timing" value="duration" onchange="timingMode()">
        Target duration
      </label>
    </div>
    <div id="interval-row">
      <label>Extract 1 frame every
        <input type="number" id="t-interval" value="10" min="1" max="300"
               style="width:70px" oninput="recalc()"> seconds
      </label>
      <div class="estimate" id="est-duration"></div>
    </div>
    <div id="duration-row" style="display:none">
      <label>Make video
        <input type="number" id="t-duration" value="5" min="1" step="0.5"
               style="width:70px" oninput="recalc()"> minutes long
      </label>
      <div class="estimate" id="est-interval"></div>
    </div>
  </div>

  <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;flex-wrap:wrap">
    <button class="ok" onclick="buildTimelapse()">Build Timelapse</button>
    <button id="tlRebuildBtn" class="ok" style="display:none" onclick="rebuildSelected()">Rebuild selected (<span id="tlSelCount">0</span>)</button>
    <button id="tlDelBtn" class="del" style="display:none" onclick="deleteSelected()">Delete selected</button>
    <span id="build-status" style="font-size:13px;color:#aaa"></span>
  </div>
  <div class="progress-wrap" id="prog-wrap">
    <div class="progress-bar" id="prog-bar"></div>
  </div>
  <div class="tl-list" id="tl-list"></div>
</div>

<!-- STATUS -->
<div id="status" class="panel">
  <div class="status-row">
    <button class="ok" onclick="runPipeline()">Run pipeline now</button>
    <span id="pipe-status" style="font-size:13px;color:#aaa"></span>
  </div>
  <div class="log-box" id="log-box">Loading...</div>
</div>

<div id="toast"></div>
<script>
'use strict';

// ── Tab switching ─────────────────────────────────────────────
document.querySelectorAll('.mtab').forEach(t => t.addEventListener('click', () => {
  document.querySelectorAll('.mtab').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  document.getElementById(t.dataset.panel).classList.add('active');
  if (t.dataset.panel === 'timelapse') { loadTimelapses(); recalc(); }
  if (t.dataset.panel === 'status') loadLog();
}));

// ── Photos tab ────────────────────────────────────────────────
const selected = new Set();
let allData = {};

function fmtTs(ts) {
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
  photo.alt = img.label || '';
  const ts = document.createElement('div');
  ts.className = 'ts';
  ts.textContent = fmtTs(img.timestamp);
  const badge = document.createElement('div');
  badge.className = 'badge';
  badge.textContent = '\\u2715';
  card.append(photo, ts, badge);
  card.addEventListener('click', () => toggle(card, img.path));
  return card;
}

async function initPhotos() {
  const r = await fetch('/api/images');
  allData = await r.json();
  const subtabs  = document.getElementById('subtabs');
  const sections = document.getElementById('sections');
  Object.keys(allData).sort().forEach((cat, i) => {
    const imgs = allData[cat];
    const tab = document.createElement('div');
    tab.className = 'stab' + (i === 0 ? ' active' : '');
    tab.textContent = cat + ' (' + imgs.length + ')';
    tab.dataset.cat = cat;
    tab.addEventListener('click', () => {
      document.querySelectorAll('.stab').forEach(x => x.classList.remove('active'));
      document.querySelectorAll('.section').forEach(x => x.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('sec-' + cat).classList.add('active');
    });
    subtabs.appendChild(tab);

    const sec = document.createElement('div');
    sec.className = 'section' + (i === 0 ? ' active' : '');
    sec.id = 'sec-' + cat;

    const bar = document.createElement('div');
    bar.className = 'sec-bar';
    const info = document.createElement('span');
    info.textContent = imgs.length + ' photos';
    const selAll = document.createElement('a');
    selAll.textContent = 'select all';
    selAll.addEventListener('click', () => selectAll(cat));
    const deselAll = document.createElement('a');
    deselAll.textContent = 'deselect all';
    deselAll.addEventListener('click', () => deselectAll(cat));
    bar.append(info, selAll, deselAll);

    const grid = document.createElement('div');
    grid.className = 'grid';
    imgs.forEach(img => grid.appendChild(makeCard(img)));
    sec.append(bar, grid);
    sections.appendChild(sec);
  });
}

function toggle(card, path) {
  if (selected.has(path)) { selected.delete(path); card.classList.remove('selected'); }
  else                    { selected.add(path);    card.classList.add('selected'); }
  updateCount();
}
function selectAll(cat) {
  allData[cat].forEach(img => {
    selected.add(img.path);
    document.querySelector('.card[data-path="' + CSS.escape(img.path) + '"]')
            ?.classList.add('selected');
  });
  updateCount();
}
function deselectAll(cat) {
  allData[cat].forEach(img => {
    selected.delete(img.path);
    document.querySelector('.card[data-path="' + CSS.escape(img.path) + '"]')
            ?.classList.remove('selected');
  });
  updateCount();
}
function updateCount() {
  document.getElementById('count').textContent = selected.size + ' selected';
  document.getElementById('delBtn').disabled = selected.size === 0;
}
async function confirmDelete() {
  if (!selected.size) return;
  if (!confirm('Permanently delete ' + selected.size + ' photo(s) from highlights?\\n\\nThis cannot be undone.')) return;
  const paths = [...selected];
  const r = await fetch('/api/delete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({paths}),
  });
  const j = await r.json();
  const deletedSet = new Set(j.paths);
  j.paths.forEach(p => {
    document.querySelector('.card[data-path="' + CSS.escape(p) + '"]')?.remove();
    selected.delete(p);
  });
  Object.keys(allData).forEach(cat => {
    allData[cat] = allData[cat].filter(img => !deletedSet.has(img.path));
    const n = document.querySelectorAll('#sec-' + cat + ' .card').length;
    const tab = document.querySelector('.stab[data-cat="' + cat + '"]');
    if (tab) tab.textContent = cat + ' (' + n + ')';
  });
  updateCount();
  toast('Deleted ' + j.deleted + ' photo(s)');
}

// ── Timelapse tab ───────────────────────────────────────────────
let tlMode = 'golden';

function setMode(mode) {
  tlMode = mode;
  document.querySelectorAll('.mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === mode);
  });
  document.getElementById('form-golden').style.display  = mode === 'golden'  ? '' : 'none';
  document.getElementById('form-fullday').style.display = mode === 'fullday' ? '' : 'none';
  document.getElementById('form-custom').style.display  = mode === 'custom'  ? '' : 'none';
}

document.querySelectorAll('.mode-btn').forEach(b => b.addEventListener('click', () => {
  setMode(b.dataset.mode);
  recalc();
}));

// Default dates to today
const today = new Date().toISOString().slice(0, 10);
document.getElementById('gh-date').value = today;
document.getElementById('fd-date').value = today;

function timingMode() {
  const isInterval = document.querySelector('input[name=timing]:checked').value === 'interval';
  document.getElementById('interval-row').style.display = isInterval ? '' : 'none';
  document.getElementById('duration-row').style.display = isInterval ? 'none' : '';
  recalc();
}

function windowSecs() {
  if (tlMode === 'golden')  return 60 * 60;         // +-30 min = 60 min total
  if (tlMode === 'fullday') return 15 * 60 * 60;    // ~15h with padding
  const s = document.getElementById('cr-start').value;
  const e = document.getElementById('cr-end').value;
  if (!s || !e) return 15 * 60 * 60;
  return Math.max(60, (new Date(e) - new Date(s)) / 1000);
}

function fmtSecs(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.round(s % 60);
  if (h > 0) return h + 'h ' + m + 'm';
  if (m > 0) return m + 'm ' + sec + 's';
  return sec + 's';
}

function recalc() {
  const wSecs = windowSecs();
  const isInterval = document.querySelector('input[name=timing]:checked').value === 'interval';
  if (isInterval) {
    const iv = parseFloat(document.getElementById('t-interval').value) || 10;
    const frames = Math.round(wSecs / iv);
    const dur = frames * 0.12;
    document.getElementById('est-duration').textContent =
      '-> ~' + frames + ' frames, video ~' + fmtSecs(dur);
  } else {
    const dur = (parseFloat(document.getElementById('t-duration').value) || 5) * 60;
    const frames = dur / 0.12;
    const iv = (wSecs / frames).toFixed(1);
    document.getElementById('est-interval').textContent =
      '-> 1 frame every ' + iv + 's';
  }
}

let _building = false;

async function buildTimelapse() {
  const isInterval = document.querySelector('input[name=timing]:checked').value === 'interval';
  let intervalSecs;
  if (isInterval) {
    intervalSecs = parseFloat(document.getElementById('t-interval').value) || 10;
  } else {
    const dur = (parseFloat(document.getElementById('t-duration').value) || 5) * 60;
    intervalSecs = Math.max(1, windowSecs() / (dur / 0.12));
  }

  const body = {mode: tlMode, interval_secs: Math.round(intervalSecs)};
  if (tlMode === 'golden') {
    body.date = document.getElementById('gh-date').value;
    body.type = document.getElementById('gh-type').value;
  } else if (tlMode === 'fullday') {
    body.date = document.getElementById('fd-date').value;
  } else {
    body.start = document.getElementById('cr-start').value;
    body.end   = document.getElementById('cr-end').value;
    body.label = document.getElementById('cr-label').value || 'custom';
  }

  const r = await fetch('/api/timelapse/build', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (j.error) { toast('Error: ' + j.error); return; }
  if (j.position > 1) {
    toast('Queued — position ' + j.position + ' in queue');
  }
  _building = true;
  document.getElementById('prog-wrap').style.display = '';
  pollBuild();
}

function pollBuild() {
  setTimeout(async () => {
    const r = await fetch('/api/timelapse/status');
    const j = await r.json();
    const st  = document.getElementById('build-status');
    const bar = document.getElementById('prog-bar');
    const queueSuffix = j.queued > 0 ? ' \xb7 ' + j.queued + ' queued' : '';
    if (j.state === 'running') {
      const pct = j.frames_total > 0
        ? Math.round(j.frames_done / j.frames_total * 100) : 0;
      bar.style.width = pct + '%';
      st.textContent  = j.stage + '... ' + j.frames_done + '/' + j.frames_total + ' frames' + queueSuffix;
      pollBuild();
    } else if (j.queued > 0) {
      bar.style.width = '0%';
      st.textContent  = 'Waiting to start…' + queueSuffix;
      if (j.state === 'done') { loadTimelapses(); toast('Timelapse built!'); }
      pollBuild();
    } else {
      _building = false;
      document.getElementById('prog-wrap').style.display = 'none';
      bar.style.width = '0%';
      st.textContent  = j.state === 'done' ? 'Done!' : (j.error ? 'Error: ' + j.error : '');
      if (j.state === 'done') { loadTimelapses(); toast('Timelapse built!'); }
    }
  }, 1500);
}

const _tlSelected = new Map();  // video filename -> entry

function _tlUpdateButtons() {
  const n = _tlSelected.size;
  document.getElementById('tlSelCount').textContent = n;
  document.getElementById('tlRebuildBtn').style.display = n > 0 ? '' : 'none';
  document.getElementById('tlDelBtn').style.display     = n > 0 ? '' : 'none';
  // Single selection: also populate the form
  if (n === 1) {
    const e = [..._tlSelected.values()][0];
    const type = (e.type || '').toLowerCase();
    if (type === 'sunrise' || type === 'sunset') {
      setMode('golden');
      document.getElementById('gh-date').value = e.date || '';
      document.getElementById('gh-type').value = type;
    } else if (type === 'fullday') {
      setMode('fullday');
      document.getElementById('fd-date').value = e.date || '';
    } else {
      setMode('custom');
      if (e.start) document.getElementById('cr-start').value = e.start.slice(0,16);
      if (e.end)   document.getElementById('cr-end').value   = e.end.slice(0,16);
      document.getElementById('cr-label').value = e.label || '';
    }
    recalc();
  }
}

async function loadTimelapses() {
  const r = await fetch('/api/timelapses');
  const j = await r.json();
  const list = document.getElementById('tl-list');
  list.textContent = '';
  _tlSelected.clear();
  _tlUpdateButtons();

  (j.entries || []).forEach(e => {
    const card = document.createElement('div');
    card.className = 'tl-card';
    card.addEventListener('click', () => {
      if (_tlSelected.has(e.video)) {
        _tlSelected.delete(e.video);
        card.classList.remove('tl-selected');
      } else {
        _tlSelected.set(e.video, e);
        card.classList.add('tl-selected');
      }
      _tlUpdateButtons();
    });

    const img = document.createElement('img');
    img.src = e.thumbnail ? '/thumb/' + encodeURIComponent(e.thumbnail) : '';
    img.alt = '';

    const play = document.createElement('button');
    play.className = 'tl-card-play';
    play.title = 'Watch';
    play.textContent = '▶';
    play.addEventListener('click', ev => {
      ev.stopPropagation();
      window.open('/timelapse/' + encodeURIComponent(e.video), '_blank');
    });

    const info = document.createElement('div');
    info.className = 'tl-card-info';

    const title = document.createElement('strong');
    title.textContent = e.date + ' ' + (e.type || e.label || '');

    const detail = document.createTextNode(
      '\\n' + (e.frame_count || 0) + ' frames \xb7 ~' +
      fmtSecs((e.frame_count || 0) * 0.12)
    );

    info.append(title, detail);
    card.append(img, play, info);
    list.appendChild(card);
  });
}

async function rebuildSelected() {
  if (_tlSelected.size === 0) return;
  const entries = [..._tlSelected.values()];
  let queued = 0;
  for (const e of entries) {
    const body = {mode: 'custom', interval_secs: 10};
    if (e.start) body.start = e.start.slice(0,16);
    if (e.end)   body.end   = e.end.slice(0,16);
    body.label = e.label || e.type || 'rebuild';
    const r = await fetch('/api/timelapse/build', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!j.error) queued++;
  }
  toast('Queued ' + queued + ' rebuild(s).');
  _building = true;
  document.getElementById('prog-wrap').style.display = '';
  pollBuild();
}

async function deleteSelected() {
  if (_tlSelected.size === 0) return;
  if (!confirm('Delete ' + _tlSelected.size + ' timelapse(s)?\\n\\nThis cannot be undone.')) return;
  let deleted = 0;
  for (const video of _tlSelected.keys()) {
    const r = await fetch('/api/timelapse/delete', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({video}),
    });
    const j = await r.json();
    if (!j.error) deleted++;
  }
  toast('Deleted ' + deleted + '.');
  loadTimelapses();
}

// ── Status tab ────────────────────────────────────────────────
async function loadLog() {
  const r = await fetch('/api/pipeline/log');
  document.getElementById('log-box').textContent = await r.text();
}

async function runPipeline() {
  document.getElementById('pipe-status').textContent = 'Starting...';
  await fetch('/api/pipeline/run', {method: 'POST'});
  document.getElementById('pipe-status').textContent = 'Running in background...';
  setTimeout(loadLog, 3000);
}

// ── Toast ─────────────────────────────────────────────────────
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 5000);
}

initPhotos();
recalc();
</script>
</body>
</html>
"""


# ── HTTP handler ─────────────────────────────────────────────────────────────────────────────

class ContentHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info(fmt % args)

    def do_GET(self):
        p = urlparse(self.path).path

        if p == "/":
            shell = STATIC_DIR / "command_center.html"
            if shell.exists():
                self._send(200, "text/html", shell.read_bytes())
            else:
                self._send(200, "text/html", _HTML.encode())
        elif p == "/api/images":
            self._send(200, "application/json",
                       json.dumps(images_by_category()).encode())
        elif p == "/api/timelapse/status":
            self._send(200, "application/json",
                       json.dumps(_job_snapshot()).encode())
        elif p == "/api/timelapses":
            self._send(200, "application/json", _timelapses_json())
        elif p == "/api/pipeline/log":
            self._send(200, "text/plain", _pipeline_log())
        elif p.startswith("/thumb/"):
            rel = safe_rel(unquote(p[len("/thumb/"):]))
            if not rel:
                self._send(403, "text/plain", b"Forbidden"); return
            data = make_thumb(rel)
            self._send(200 if data else 404, "image/jpeg", data)
        elif p.startswith("/photo/"):
            rel = safe_rel(unquote(p[len("/photo/"):]))
            if not rel:
                self._send(403, "text/plain", b"Forbidden"); return
            full = HIGHLIGHTS_DIR / rel
            self._send(200 if full.exists() else 404, "image/jpeg",
                       full.read_bytes() if full.exists() else b"")
        elif p.startswith("/timelapse/"):
            name = Path(unquote(p[len("/timelapse/"):])).name  # strip directory traversal
            full = HIGHLIGHTS_DIR / "timelapse" / name
            if not full.exists():
                self._send(404, "text/plain", b"Not found"); return
            self._send(200, "video/mp4", full.read_bytes())
        elif p == "/api/photos":
            m = load_manifest()
            self._send(200, "application/json",
                       json.dumps({"entries": entries_with_defaults(m)}).encode())
        elif p == "/api/upload/queue":
            self._send(200, "application/json", json.dumps(load_queue()).encode())
        elif p == "/api/platforms/status":
            self._send(200, "application/json", json.dumps(platform_status()).encode())
        elif p.startswith("/static/"):
            rel = unquote(p[len("/static/"):])
            try:
                target = (STATIC_DIR / rel).resolve()
                target.relative_to(STATIC_DIR.resolve())
            except Exception:
                self._send(403, "text/plain", b"Forbidden"); return
            if not target.exists() or not target.is_file():
                self._send(404, "text/plain", b"Not found"); return
            ct, _ = mimetypes.guess_type(str(target))
            self._send(200, ct or "application/octet-stream", target.read_bytes())
        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self):
        p = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            self._send(400, "application/json", b'{"error":"bad json"}'); return

        if p == "/api/delete":
            safe_paths = [r for path in payload.get("paths", [])
                          if (r := safe_rel(path))]
            deleted = delete_snapshots(safe_paths)
            self._send(200, "application/json",
                       json.dumps({"deleted": deleted, "paths": safe_paths}).encode())
        elif p == "/api/timelapse/build":
            err, position = _start_build(payload)
            if err:
                self._send(400, "application/json",
                           json.dumps({"error": err}).encode())
            else:
                self._send(200, "application/json",
                           json.dumps({"ok": True, "position": position}).encode())
        elif p == "/api/timelapse/delete":
            err = _delete_timelapse(payload.get("video", ""))
            if err:
                self._send(400, "application/json",
                           json.dumps({"error": err}).encode())
            else:
                self._send(200, "application/json", b'{"ok":true}')
        elif p == "/api/pipeline/run":
            _run_pipeline()
            self._send(200, "application/json", b'{"ok":true}')
        elif p == "/api/upload/queue/add":
            snap = safe_rel(payload.get("snapshot", ""))
            if not snap:
                self._send(400, "application/json", b'{"error":"invalid snapshot"}'); return
            q = load_queue()
            if not any(e["snapshot"] == snap for e in q["queue"]):
                q["queue"].append({
                    "snapshot": snap,
                    "title":    payload.get("title", ""),
                    "keywords": payload.get("keywords", ""),
                    "platforms": payload.get("platforms", []),
                })
            save_queue(q)
            self._send(200, "application/json", b'{"ok":true}')
        elif p == "/api/upload/queue/mode":
            mode = payload.get("mode")
            if mode not in ("manual", "auto"):
                self._send(400, "application/json",
                           b'{"error":"mode must be manual or auto"}'); return
            q = load_queue()
            q["mode"] = mode
            save_queue(q)
            self._send(200, "application/json", b'{"ok":true}')
        elif p == "/api/platforms/credentials":
            platform = payload.get("platform")
            if platform not in ("shutterstock", "adobe_stock", "anthropic"):
                self._send(400, "application/json", b'{"error":"unknown platform"}'); return
            creds = load_creds()
            creds.setdefault(platform, {}).update(
                {k: v for k, v in payload.items() if k != "platform"}
            )
            save_creds(creds)
            self._send(200, "application/json", b'{"ok":true}')
        else:
            self._send(404, "text/plain", b"Not found")

    def do_PATCH(self):
        p = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            self._send(400, "application/json", b'{"error":"bad json"}'); return

        m = re.match(r"^/api/photos/(.+)/flags$", p)
        if m:
            snap = safe_rel(unquote(m.group(1)))
            if not snap:
                self._send(403, "text/plain", b"Forbidden"); return
            result = patch_entry_flags(snap, payload)
            if result is None:
                self._send(404, "application/json", b'{"error":"not found"}'); return
            self._send(200, "application/json", json.dumps(result).encode())
            return

        m = re.match(r"^/api/photos/(.+)/crop_region$", p)
        if m:
            snap = safe_rel(unquote(m.group(1)))
            if not snap:
                self._send(403, "text/plain", b"Forbidden"); return
            region = payload if payload else None
            if not _valid_crop_region(region):
                self._send(400, "application/json", b'{"error":"invalid crop_region"}'); return
            result = patch_entry_crop_region(snap, region)
            if result is None:
                self._send(404, "application/json", b'{"error":"not found"}'); return
            self._send(200, "application/json", json.dumps(result).encode())
            return

        self._send(404, "text/plain", b"Not found")

    def do_DELETE(self):
        p = urlparse(self.path).path
        m = re.match(r"^/api/upload/queue/(.+)$", p)
        if m:
            snap = safe_rel(unquote(m.group(1)))
            if not snap:
                self._send(403, "text/plain", b"Forbidden"); return
            q = load_queue()
            q["queue"] = [e for e in q["queue"] if e.get("snapshot") != snap]
            save_queue(q)
            self._send(200, "application/json", b'{"ok":true}')
            return
        self._send(404, "text/plain", b"Not found")

    def _send(self, status: int, ct: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Timelapse list / delete ───────────────────────────────────────────────────────────────────────

def _timelapses_json() -> bytes:
    mf = HIGHLIGHTS_DIR / "timelapse_manifest.json"
    return mf.read_bytes() if mf.exists() else b'{"entries":[]}'


def _delete_timelapse(video_name: str) -> str | None:
    """Remove a timelapse video and its manifest entry. Returns error string or None."""
    if not video_name or "/" in video_name or "\\" in video_name:
        return "Invalid video name"

    mf_path = HIGHLIGHTS_DIR / "timelapse_manifest.json"
    if not mf_path.exists():
        return "No manifest found"

    manifest = json.loads(mf_path.read_text())
    entries = manifest.get("entries", [])
    entry = next((e for e in entries if e.get("video") == video_name), None)
    if not entry:
        return f"Entry not found: {video_name}"

    video_path = HIGHLIGHTS_DIR / "timelapse" / video_name
    if video_path.exists():
        video_path.unlink()

    manifest["entries"] = [e for e in entries if e.get("video") != video_name]
    manifest["updated"] = datetime.now().isoformat()
    atomic_write_json(mf_path, manifest)
    log.info("deleted timelapse %s", video_name)
    return None


# ── Pipeline log ──────────────────────────────────────────────────────────────────────────────

_PIPELINE_LOG = Path("/tmp/gtn_pipeline.log")


def _pipeline_log() -> bytes:
    if not _PIPELINE_LOG.exists():
        return b"No pipeline runs yet."
    lines = _PIPELINE_LOG.read_text(errors="replace").splitlines()
    return "\n".join(lines[-50:]).encode()


def _run_pipeline() -> None:
    script = Path(__file__).parent.parent / "cron-scan-sync.sh"
    if not script.exists():
        log.warning("cron-scan-sync.sh not found")
        return
    with open(_PIPELINE_LOG, "w") as fh:
        subprocess.Popen(["bash", str(script)], stdout=fh, stderr=subprocess.STDOUT)
    log.info("pipeline started")


# ── Build dispatch ──────────────────────────────────────────────────────────────────────────────

def _start_build(payload: dict) -> tuple[str | None, int]:
    """Validate payload and enqueue a build. Returns (error_string_or_None, queue_position)."""
    mode = payload.get("mode")
    if mode not in ("golden", "fullday", "custom"):
        return f"Unknown mode: {mode!r}", 0

    interval_secs = max(1, int(payload.get("interval_secs") or 10))

    try:
        start_dt, end_dt, label = _resolve_window(payload)
    except Exception as exc:
        return str(exc), 0

    with _job_lock:
        _build_queue.append((start_dt, end_dt, label, interval_secs))
        position = len(_build_queue)
        already_running = _job["state"] == "running"

    if not already_running:
        _dispatch_next()

    return None, position


def _dispatch_next() -> None:
    with _job_lock:
        if not _build_queue:
            return
        args = _build_queue.pop(0)
    _job_update(state="running", stage="starting", frames_done=0, frames_total=0, error="")
    threading.Thread(target=_build_thread, args=args, daemon=True).start()


def _resolve_window(payload: dict) -> tuple[datetime, datetime, str]:
    """Return (start_dt, end_dt, label) for a build payload."""
    from astral import LocationInfo
    from astral.sun import sun as astral_sun

    lat = float(os.getenv("LATITUDE", "39.8"))
    lon = float(os.getenv("LONGITUDE", "-98.5"))
    tz  = os.getenv("TZ", "America/Chicago")
    loc = LocationInfo(latitude=lat, longitude=lon, timezone=tz)
    pad = timedelta(minutes=GOLDEN_PAD_MIN)
    mode = payload["mode"]

    if mode == "golden":
        date = datetime.strptime(payload["date"], "%Y-%m-%d").date()
        kind = payload.get("type", "sunset")
        s = astral_sun(loc.observer, date=date, tzinfo=loc.tzinfo)
        center = s[kind].replace(tzinfo=None)
        return center - pad, center + pad, f"{payload['date'].replace('-','')}_{kind}"

    if mode == "fullday":
        date = datetime.strptime(payload["date"], "%Y-%m-%d").date()
        s = astral_sun(loc.observer, date=date, tzinfo=loc.tzinfo)
        start_dt = s["sunrise"].replace(tzinfo=None) - pad
        end_dt   = s["sunset"].replace(tzinfo=None)  + pad
        return start_dt, end_dt, f"{payload['date'].replace('-','')}_fullday"

    # custom
    start_dt = datetime.fromisoformat(payload["start"])
    end_dt   = datetime.fromisoformat(payload["end"])
    if end_dt <= start_dt:
        raise ValueError("end must be after start")
    raw   = payload.get("label") or "custom"
    label = "".join(c if c.isalnum() or c == "_" else "_" for c in raw)
    return start_dt, end_dt, f"{start_dt.strftime('%Y%m%d')}_{label}"


def _build_thread(start_dt: datetime, end_dt: datetime,
                  label: str, interval_secs: int) -> None:
    import frigate_extract as fe
    from timelapse_builder import _build_one

    tmp_dir = Path(tempfile.mkdtemp(prefix="gtn_tl_"))
    try:
        _job_update(stage="finding segments")
        segments = fe.find_segments(start_dt, end_dt, FRIGATE_DIR)
        if not segments:
            _job_update(state="error",
                        error="No Frigate recordings found for this window"); return

        window_secs   = (end_dt - start_dt).total_seconds()
        total_estimate = int(window_secs / interval_secs)
        _job_update(stage="extracting", frames_total=total_estimate)

        frames = fe.extract_frames(
            segments, start_dt, end_dt, interval_secs,
            tmp_dir / "frames",
            on_progress=lambda n: _job_update(frames_done=n),
        )
        if not frames:
            _job_update(state="error",
                        error="No frames extracted — check Frigate paths"); return

        _job_update(stage="encoding", frames_done=len(frames), frames_total=len(frames))
        out_dir  = HIGHLIGHTS_DIR / "timelapse"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{label}_timelapse.mp4"

        if not _build_one(frames, out_path, cpu_percent=15):
            _job_update(state="error", error="ffmpeg encode failed"); return

        _write_timelapse_manifest(label, out_path, frames, start_dt, end_dt)
        _job_update(state="done", frames_done=len(frames))

    except Exception as exc:
        log.exception("build thread error")
        _job_update(state="error", error=str(exc))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _dispatch_next()


def _write_timelapse_manifest(label: str, out_path: Path, frames: list[Path],
                               start_dt: datetime, end_dt: datetime) -> None:
    mf_path  = HIGHLIGHTS_DIR / "timelapse_manifest.json"
    manifest = json.loads(mf_path.read_text()) if mf_path.exists() else {"entries": []}

    parts    = label.split("_", 1)
    date_fmt = (f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:]}"
                if len(parts[0]) == 8 else label)
    tl_type  = parts[1] if len(parts) > 1 else "custom"

    try:
        thumb_rel = str(frames[0].relative_to(HIGHLIGHTS_DIR))
    except (IndexError, ValueError):
        thumb_rel = ""

    manifest["entries"].insert(0, {
        "session_key": label,
        "date":        date_fmt,
        "type":        tl_type,
        "label":       label,
        "frame_count": len(frames),
        "video":       out_path.name,
        "thumbnail":   thumb_rel,
        "source":      "frigate_extract",
        "start":       start_dt.isoformat(),
        "end":         end_dt.isoformat(),
        "created":     datetime.now().isoformat(),
    })
    manifest["updated"] = datetime.now().isoformat()
    atomic_write_json(mf_path, manifest)


# ── CLI ────────────────────────────────────────────────────────────────────────────────────

def main():
    global HIGHLIGHTS_DIR, FRIGATE_DIR, SYNC_SCRIPT

    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--port",           type=int, default=8766)
    ap.add_argument("--highlights-dir", default=str(HIGHLIGHTS_DIR))
    ap.add_argument("--frigate-dir",    default=str(FRIGATE_DIR))
    ap.add_argument("--sync-script",    default="")
    args = ap.parse_args()

    HIGHLIGHTS_DIR = Path(args.highlights_dir)
    FRIGATE_DIR    = Path(args.frigate_dir)
    SYNC_SCRIPT    = Path(args.sync_script) if args.sync_script else None

    server = HTTPServer(("0.0.0.0", args.port), ContentHandler)
    log.info(f"GTN Content Manager  ->  http://192.168.100.202:{args.port}")
    log.info(f"highlights: {HIGHLIGHTS_DIR}  |  frigate: {FRIGATE_DIR}")
    log.info("Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
