# GTN Command Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `content_manager.py` into a full GTN Command Center with left sidebar navigation, photo flag chips (crop/enhance/auth-hold), split upload workflow, Shutterstock + Adobe Stock API clients, and optional Claude assistant panel.

**Architecture:** stdlib `http.server` extended in-place; new routes added to `ContentHandler`; HTML/CSS/JS served from `highlight-curator/static/`; platform API clients in `highlight-curator/platforms/` subpackage; no new Python dependencies.

**Tech Stack:** Python 3.11, stdlib only (urllib.request, http.server, json, re, threading, pathlib), Pillow (already installed for thumbnails), vanilla JS (no build step).

**Security note:** All JavaScript that inserts server-derived values into the DOM uses `escHtml()` for innerHTML contexts or `textContent`/`setAttribute` for plain values. Avoid inserting API responses directly via innerHTML without escaping.

---

## File Map

**Create:**
- `highlight-curator/static/command_center.html` — sidebar shell SPA skeleton
- `highlight-curator/static/css/command_center.css` — dark theme, sidebar, grid layout
- `highlight-curator/static/js/photos.js` — photo grid with flag chip rendering and toggles
- `highlight-curator/static/js/upload.js` — split list+detail upload workflow
- `highlight-curator/static/js/platforms.js` — credential form, connection status
- `highlight-curator/static/js/claude_panel.js` — message history, context assembly, panel toggle

**Create Python:**
- `highlight-curator/platforms/__init__.py` — empty
- `highlight-curator/platforms/shutterstock.py` — Shutterstock Contributor API client
- `highlight-curator/platforms/adobe_stock.py` — Adobe Stock Contributor API client

**Modify:**
- `highlight-curator/content_manager.py` — static serving, `do_PATCH`, `do_DELETE`, new API routes, credential helpers, queue helpers, Claude proxy
- `highlight-curator/tests/test_content_manager_api.py` — tests for all new API endpoints

---

## Task 1: Static file serving + sidebar shell

**Files:**
- Modify: `highlight-curator/content_manager.py`
- Create: `highlight-curator/static/command_center.html`
- Create: `highlight-curator/static/css/command_center.css`
- Test: `highlight-curator/tests/test_content_manager_api.py`

- [ ] **Step 1: Write failing tests for static serving**

Append to `highlight-curator/tests/test_content_manager_api.py`:

```python
def test_root_serves_command_center(server):
    status, body = get(server + "/")
    assert status == 200
    assert b"command_center" in body.lower()

def test_static_css_served(server):
    status, body = get(server + "/static/css/command_center.css")
    assert status == 200

def test_static_404_for_missing(server):
    try:
        get(server + "/static/does_not_exist.xyz")
        assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404

def test_static_traversal_blocked(server):
    try:
        get(server + "/static/../content_manager.py")
        assert False, "expected 403 or 404"
    except urllib.error.HTTPError as e:
        assert e.code in (403, 404)
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd weather-station/highlight-curator
pytest tests/test_content_manager_api.py::test_root_serves_command_center \
       tests/test_content_manager_api.py::test_static_css_served -v
```

Expected: FAIL (no `/static/` route yet, root still returns old `_HTML`).

- [ ] **Step 3: Create the static directory**

```bash
mkdir -p highlight-curator/static/css highlight-curator/static/js
```

- [ ] **Step 4: Create `highlight-curator/static/command_center.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GTN Command Center</title>
<link rel="stylesheet" href="/static/css/command_center.css">
</head>
<body>
<div id="app">
  <nav id="sidebar">
    <div id="sidebar-title">GTN</div>
    <a class="nav-item active" data-tab="photos">Photos</a>
    <a class="nav-item" data-tab="timelapse">Timelapse</a>
    <a class="nav-item" data-tab="upload">Upload</a>
    <a class="nav-item" data-tab="platforms">Platforms</a>
    <a class="nav-item" data-tab="status">Status</a>
    <div id="sidebar-footer">
      <a class="nav-item" id="claude-toggle">Claude</a>
    </div>
  </nav>
  <main id="content">
    <div id="tab-photos" class="tab active"></div>
    <div id="tab-timelapse" class="tab"></div>
    <div id="tab-upload" class="tab"></div>
    <div id="tab-platforms" class="tab"></div>
    <div id="tab-status" class="tab"></div>
  </main>
  <aside id="claude-panel" class="hidden">
    <div id="claude-header">
      <span>Claude</span>
      <button id="claude-close">X</button>
    </div>
    <div id="claude-messages"></div>
    <div id="claude-input-row">
      <input id="claude-input" type="text" placeholder="Ask anything...">
      <button id="claude-send">Send</button>
    </div>
  </aside>
</div>
<div id="toast"></div>
<script src="/static/js/photos.js"></script>
<script src="/static/js/upload.js"></script>
<script src="/static/js/platforms.js"></script>
<script src="/static/js/claude_panel.js"></script>
<script>
let currentTab = 'photos';

function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.nav-item[data-tab]').forEach(n => n.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  const navItem = document.querySelector('.nav-item[data-tab="' + name + '"]');
  if (navItem) navItem.classList.add('active');
  currentTab = name;
  if (name === 'photos')    loadPhotos();
  if (name === 'upload')    loadUploadQueue();
  if (name === 'platforms') loadPlatforms();
  if (name === 'status')    loadStatus();
}

function showToast(msg, ok) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = (ok === false) ? '#c33' : '#2a7';
  t.style.display = 'block';
  setTimeout(() => { t.style.display = 'none'; }, 3000);
}

document.querySelectorAll('.nav-item[data-tab]').forEach(el => {
  el.addEventListener('click', () => switchTab(el.dataset.tab));
});
document.getElementById('claude-toggle').addEventListener('click', () => {
  document.getElementById('claude-panel').classList.toggle('hidden');
});
document.getElementById('claude-close').addEventListener('click', () => {
  document.getElementById('claude-panel').classList.add('hidden');
});

window.addEventListener('load', () => switchTab('photos'));
</script>
</body>
</html>
```

- [ ] **Step 5: Create `highlight-curator/static/css/command_center.css`**

```css
*{box-sizing:border-box;margin:0;padding:0}
body{background:#111;color:#eee;font:14px/1.4 system-ui,sans-serif;height:100vh;overflow:hidden}
#app{display:flex;height:100vh}
#sidebar{width:140px;background:#141414;border-right:1px solid #2a2a2a;
         display:flex;flex-direction:column;flex-shrink:0;padding:12px 0}
#sidebar-title{padding:10px 14px;font-weight:700;font-size:15px;color:#eee;
               border-bottom:1px solid #2a2a2a;margin-bottom:8px}
.nav-item{display:block;padding:8px 14px;color:#777;cursor:pointer;font-size:13px;
          border-radius:0 4px 4px 0;margin:1px 6px 1px 0;text-decoration:none;
          transition:background .1s,color .1s}
.nav-item:hover{background:#222;color:#bbb}
.nav-item.active{background:#0055aa;color:#fff}
#sidebar-footer{margin-top:auto;border-top:1px solid #2a2a2a;padding-top:8px}
#content{flex:1;overflow-y:auto;padding:16px}
.tab{display:none}
.tab.active{display:block}
#claude-panel{width:320px;background:#0d1a0d;border-left:1px solid #1a2a1a;
              display:flex;flex-direction:column;flex-shrink:0}
#claude-panel.hidden{display:none}
#claude-header{padding:10px 14px;border-bottom:1px solid #1a2a1a;
               display:flex;justify-content:space-between;align-items:center;
               color:#6c6;font-weight:600}
#claude-header button{background:none;border:none;color:#555;cursor:pointer;font-size:16px}
#claude-messages{flex:1;overflow-y:auto;padding:10px;display:flex;
                 flex-direction:column;gap:8px}
.msg-user{background:#1a3a1a;border-radius:6px;padding:7px 10px;font-size:13px;
          color:#9cf;align-self:flex-end;max-width:90%}
.msg-ai{background:#1e1e1e;border-radius:6px;padding:7px 10px;font-size:13px;
        color:#ccc;align-self:flex-start;max-width:90%;white-space:pre-wrap}
#claude-input-row{padding:10px;display:flex;gap:6px;border-top:1px solid #1a2a1a}
#claude-input{flex:1;background:#1a1a1a;border:1px solid #2a2a2a;color:#eee;
              padding:6px 8px;border-radius:4px;font-size:13px}
#claude-input-row button{background:#2a5a2a;color:#fff;border:none;padding:6px 12px;
                          border-radius:4px;cursor:pointer;font-size:13px}
.photo-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}
.photo-card{position:relative;border-radius:4px;overflow:hidden;border:2px solid #333;
            background:#1a1a1a;cursor:pointer;transition:border-color .12s}
.photo-card:hover{border-color:#555}
.photo-card img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block;background:#222}
.photo-meta{padding:4px 6px;font-size:11px;color:#666;border-top:1px solid #222}
.flag-chips{position:absolute;top:4px;left:4px;display:flex;flex-direction:column;gap:2px}
.chip{font-size:8px;padding:2px 5px;border-radius:2px;font-weight:700;cursor:pointer}
.chip-crop{background:#fa0;color:#000}
.chip-enh{background:#4af;color:#000}
.chip-hold{background:#f44;color:#fff}
#upload-shell{display:flex;height:calc(100vh - 48px)}
#queue-list{width:240px;border-right:1px solid #2a2a2a;overflow-y:auto;flex-shrink:0}
#queue-header{padding:8px 10px;border-bottom:1px solid #2a2a2a;display:flex;
              gap:6px;align-items:center;font-size:12px;flex-wrap:wrap}
.queue-item{padding:8px 10px;border-bottom:1px solid #1a1a1a;display:flex;gap:8px;
            align-items:center;cursor:pointer}
.queue-item:hover,.queue-item.active{background:#1e2a1e}
.queue-item img{width:40px;height:30px;object-fit:cover;border-radius:2px;background:#222}
.queue-item-info{flex:1;min-width:0}
.queue-item-name{font-size:11px;color:#aaa;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.queue-item-status{font-size:10px;margin-top:2px}
#detail-panel{flex:1;padding:14px;overflow-y:auto;display:flex;flex-direction:column;gap:10px}
#detail-preview{width:100%;max-height:320px;object-fit:contain;background:#111;border-radius:4px}
.field-label{font-size:11px;color:#666;margin-bottom:3px}
.field-input{width:100%;background:#1a1a1a;border:1px solid #333;color:#eee;
             padding:6px 8px;border-radius:4px;font-size:13px}
button{background:#c33;color:#fff;border:none;padding:6px 14px;border-radius:4px;
       cursor:pointer;font-size:13px}
button.ok{background:#2a7}
button.sec{background:#2a2a2a;color:#aaa}
.platform-card{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:6px;
               padding:14px;margin-bottom:12px}
.platform-card h3{font-size:14px;margin-bottom:8px;display:flex;align-items:center;gap:8px}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.dot-green{background:#2a7}
.dot-red{background:#c33}
.dot-grey{background:#555}
#toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);
       padding:10px 22px;border-radius:6px;display:none;font-weight:600;z-index:99;color:#fff}
```

- [ ] **Step 6: Add static serving to `content_manager.py`**

Add `import re` and `import mimetypes` to the imports at the top.

Add after the `GOLDEN_PAD_MIN` constant:

```python
STATIC_DIR = Path(__file__).parent / "static"
```

In `do_GET`, replace:

```python
        if p == "/":
            self._send(200, "text/html", _HTML.encode())
```

with:

```python
        if p == "/":
            shell = STATIC_DIR / "command_center.html"
            if shell.exists():
                self._send(200, "text/html", shell.read_bytes())
            else:
                self._send(200, "text/html", _HTML.encode())
```

Add before the final `else` in `do_GET`:

```python
        elif p.startswith("/static/"):
            rel = p[len("/static/"):]
            try:
                target = (STATIC_DIR / rel).resolve()
                target.relative_to(STATIC_DIR.resolve())
            except Exception:
                self._send(403, "text/plain", b"Forbidden"); return
            if not target.exists() or not target.is_file():
                self._send(404, "text/plain", b"Not found"); return
            ct, _ = mimetypes.guess_type(str(target))
            self._send(200, ct or "application/octet-stream", target.read_bytes())
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/test_content_manager_api.py::test_root_serves_command_center \
       tests/test_content_manager_api.py::test_static_css_served \
       tests/test_content_manager_api.py::test_static_traversal_blocked -v
```

Expected: PASS all three. (`test_static_css_served` finds the real `command_center.css` on disk — the fixture only sets `HIGHLIGHTS_DIR`, not `STATIC_DIR`.)

- [ ] **Step 8: Verify in browser**

```bash
python3 highlight-curator/content_manager.py --highlights-dir /volume1/highlights
```

Open `http://192.168.100.202:8766`. Sidebar should appear. Tab clicks switch content areas.

- [ ] **Step 9: Commit**

```bash
git add highlight-curator/content_manager.py \
        highlight-curator/static/ \
        highlight-curator/tests/test_content_manager_api.py
git commit -m "feat(cc): static file serving + sidebar shell"
```

---

## Task 2: Photos API with flags fields

**Files:**
- Modify: `highlight-curator/content_manager.py`
- Test: `highlight-curator/tests/test_content_manager_api.py`

- [ ] **Step 1: Write failing test**

```python
def test_api_photos_returns_entries_with_flags(server):
    status, body = get(server + "/api/photos")
    data = json.loads(body)
    assert status == 200
    assert "entries" in data
    for e in data["entries"]:
        assert "flags" in e
        assert set(e["flags"]) >= {"crop", "enhance", "auth_hold"}
        assert "crop_region" in e
        assert "uploads" in e
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_content_manager_api.py::test_api_photos_returns_entries_with_flags -v
```

Expected: FAIL (404 — route not yet added).

- [ ] **Step 3: Add helper and route**

Add after `load_manifest()`:

```python
_DEFAULT_FLAGS = {"crop": False, "enhance": False, "auth_hold": False}

def entries_with_defaults(m: dict) -> list:
    result = []
    for e in m.get("entries", []):
        entry = dict(e)
        entry.setdefault("flags", dict(_DEFAULT_FLAGS))
        entry.setdefault("crop_region", None)
        entry.setdefault("uploads", {})
        result.append(entry)
    return result
```

Add in `do_GET` before the `/static/` block:

```python
        elif p == "/api/photos":
            m = load_manifest()
            self._send(200, "application/json",
                       json.dumps({"entries": entries_with_defaults(m)}).encode())
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_content_manager_api.py::test_api_photos_returns_entries_with_flags -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add highlight-curator/content_manager.py \
        highlight-curator/tests/test_content_manager_api.py
git commit -m "feat(cc): GET /api/photos with flag defaults"
```

---

## Task 3: Photos tab JavaScript

**Files:**
- Create: `highlight-curator/static/js/photos.js`

No automated tests — verify in browser.

- [ ] **Step 1: Create `highlight-curator/static/js/photos.js`**

```javascript
// photos.js — renders photo grid with flag chips
// All API-derived strings inserted into innerHTML must pass through escHtml() (defined in command_center.html).

let photosData = [];

async function loadPhotos() {
  const tab = document.getElementById('tab-photos');
  tab.textContent = 'Loading...';
  const r = await fetch('/api/photos');
  const data = await r.json();
  photosData = data.entries || [];
  renderPhotos(tab);
}

function renderPhotos(container) {
  while (container.firstChild) container.removeChild(container.firstChild);

  const byCategory = {};
  for (const e of photosData) {
    const cat = (e.categories || ['unknown'])[0];
    (byCategory[cat] = byCategory[cat] || []).push(e);
  }

  const bar = document.createElement('div');
  bar.style.cssText = 'display:flex;gap:6px;margin-bottom:12px;align-items:center';
  const count = document.createElement('span');
  count.style.cssText = 'color:#888;font-size:13px';
  count.textContent = photosData.length + ' photos';
  bar.appendChild(count);
  container.appendChild(bar);

  for (const [cat, entries] of Object.entries(byCategory)) {
    const section = document.createElement('div');
    section.style.marginBottom = '24px';

    const heading = document.createElement('h3');
    heading.style.cssText = 'font-size:12px;color:#666;margin-bottom:8px;text-transform:uppercase';
    heading.textContent = cat;  // textContent: no XSS risk
    section.appendChild(heading);

    const grid = document.createElement('div');
    grid.className = 'photo-grid';
    for (const entry of entries) grid.appendChild(makePhotoCard(entry));
    section.appendChild(grid);
    container.appendChild(section);
  }
}

function makePhotoCard(entry) {
  const card = document.createElement('div');
  card.className = 'photo-card';
  card.dataset.snapshot = entry.snapshot || '';

  const img = document.createElement('img');
  img.src = '/thumb/' + encodeURIComponent(entry.snapshot || '');
  img.loading = 'lazy';
  img.alt = '';
  card.appendChild(img);

  const chips = document.createElement('div');
  chips.className = 'flag-chips';
  if (entry.flags && entry.flags.crop)      chips.appendChild(makeChip('CROP', 'chip-crop', entry, 'crop'));
  if (entry.flags && entry.flags.enhance)   chips.appendChild(makeChip('ENH',  'chip-enh',  entry, 'enhance'));
  if (entry.flags && entry.flags.auth_hold) chips.appendChild(makeChip('HOLD', 'chip-hold', entry, 'auth_hold'));
  card.appendChild(chips);

  const meta = document.createElement('div');
  meta.className = 'photo-meta';
  meta.textContent = (entry.timestamp || '').replace('_', ' ');
  card.appendChild(meta);

  card.addEventListener('click', function(e) {
    if (!e.target.classList.contains('chip')) openFlagPopover(entry, card);
  });
  return card;
}

function makeChip(label, cls, entry, flagKey) {
  const chip = document.createElement('span');
  chip.className = 'chip ' + cls;
  chip.textContent = label;
  chip.addEventListener('click', function(e) {
    e.stopPropagation();
    toggleFlag(entry, flagKey);
  });
  return chip;
}

async function toggleFlag(entry, flagKey) {
  const newVal = !(entry.flags && entry.flags[flagKey]);
  const resp = await fetch('/api/photos/' + encodeURIComponent(entry.snapshot) + '/flags', {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({[flagKey]: newVal})
  });
  if (!resp.ok) { showToast('Flag update failed', false); return; }
  if (!entry.flags) entry.flags = {};
  entry.flags[flagKey] = newVal;
  const card = document.querySelector('[data-snapshot="' + CSS.escape(entry.snapshot) + '"]');
  if (card) {
    const parent = card.parentNode;
    parent.replaceChild(makePhotoCard(entry), card);
  }
  showToast(newVal ? flagKey + ' set' : flagKey + ' cleared');
}

function openFlagPopover(entry, card) {
  document.querySelectorAll('.flag-popover').forEach(function(p) { p.remove(); });

  const pop = document.createElement('div');
  pop.className = 'flag-popover';
  pop.style.cssText = 'position:fixed;background:#222;border:1px solid #444;border-radius:6px;' +
    'padding:12px;z-index:50;min-width:180px;box-shadow:0 4px 12px rgba(0,0,0,.6)';
  const rect = card.getBoundingClientRect();
  pop.style.top  = (rect.bottom + 4) + 'px';
  pop.style.left = rect.left + 'px';

  const title = document.createElement('div');
  title.style.cssText = 'font-size:12px;color:#888;margin-bottom:8px';
  title.textContent = 'Flags';
  pop.appendChild(title);

  const flagDefs = [
    {key: 'crop',      label: 'Crop'},
    {key: 'enhance',   label: 'Enhance'},
    {key: 'auth_hold', label: 'Auth Hold'},
  ];
  for (const fd of flagDefs) {
    const row = document.createElement('label');
    row.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:6px;cursor:pointer;font-size:13px';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = !!(entry.flags && entry.flags[fd.key]);
    cb.addEventListener('change', function() { toggleFlag(entry, fd.key); pop.remove(); });
    const lbl = document.createElement('span');
    lbl.textContent = fd.label;
    row.appendChild(cb);
    row.appendChild(lbl);
    pop.appendChild(row);
  }

  const queueBtn = document.createElement('button');
  queueBtn.className = 'ok';
  queueBtn.textContent = '+ Queue for upload';
  queueBtn.style.cssText = 'font-size:11px;padding:3px 8px;margin-top:8px;width:100%';
  queueBtn.addEventListener('click', function() {
    addToQueue(entry.snapshot);
    pop.remove();
  });
  pop.appendChild(queueBtn);

  const closeBtn = document.createElement('button');
  closeBtn.className = 'sec';
  closeBtn.textContent = 'Close';
  closeBtn.style.cssText = 'margin-top:4px;font-size:11px;padding:3px 8px';
  closeBtn.addEventListener('click', function() { pop.remove(); });
  pop.appendChild(closeBtn);

  document.body.appendChild(pop);
  setTimeout(function() {
    document.addEventListener('click', function handler() {
      pop.remove();
      document.removeEventListener('click', handler);
    });
  }, 50);
}

async function addToQueue(snapshot) {
  await fetch('/api/upload/queue/add', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({snapshot: snapshot, title: '', keywords: '', platforms: ['shutterstock', 'adobe_stock']})
  });
  showToast('Added to upload queue');
}
```

- [ ] **Step 2: Verify in browser**

Reload `http://192.168.100.202:8766`. Click Photos. Grid renders. Click a card — popover appears with flag checkboxes and Queue button. Toggle a flag — chip appears/disappears.

- [ ] **Step 3: Commit**

```bash
git add highlight-curator/static/js/photos.js
git commit -m "feat(cc): photos tab with flag chips and popover"
```

---

## Task 4: Flag write API (PATCH endpoints)

**Files:**
- Modify: `highlight-curator/content_manager.py`
- Test: `highlight-curator/tests/test_content_manager_api.py`

- [ ] **Step 1: Write failing tests**

Add `import urllib.parse` to imports in the test file. Then append:

```python
def patch(url, body: dict):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="PATCH")
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())

def test_patch_flags_sets_crop(server):
    snap = "golden_hour/sunrise/20260511_070000_scene.jpg"
    status, data = patch(server + "/api/photos/" + urllib.parse.quote(snap, safe='') + "/flags",
                         {"crop": True})
    assert status == 200
    assert data["flags"]["crop"] is True

def test_patch_flags_unknown_returns_404(server):
    try:
        patch(server + "/api/photos/" + urllib.parse.quote("no_such/photo.jpg", safe='') + "/flags",
              {"crop": True})
        assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404

def test_patch_crop_region(server):
    snap = "golden_hour/sunrise/20260511_070000_scene.jpg"
    region = {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}
    status, data = patch(server + "/api/photos/" + urllib.parse.quote(snap, safe='') + "/crop_region",
                         region)
    assert status == 200
    assert data["crop_region"] == region
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_content_manager_api.py::test_patch_flags_sets_crop -v
```

Expected: FAIL (`AttributeError: ContentHandler has no attribute 'do_PATCH'`).

- [ ] **Step 3: Add helper functions**

Add after `entries_with_defaults()`:

```python
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
        flags = entry.setdefault("flags", {"crop": False, "enhance": False, "auth_hold": False})
        for k, v in flag_updates.items():
            if k in {"crop", "enhance", "auth_hold"}:
                flags[k] = bool(v)
        result["flags"] = dict(flags)
    locked_manifest_update(HIGHLIGHTS_DIR / "manifest.json", _modify)
    return result if result else None


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
```

- [ ] **Step 4: Add `do_PATCH` to `ContentHandler`**

Ensure `import re` is at the top. Add after `do_POST` (before `_send`):

```python
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
            result = patch_entry_crop_region(snap, payload if payload else None)
            if result is None:
                self._send(404, "application/json", b'{"error":"not found"}'); return
            self._send(200, "application/json", json.dumps(result).encode())
            return

        self._send(404, "text/plain", b"Not found")
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_content_manager_api.py::test_patch_flags_sets_crop \
       tests/test_content_manager_api.py::test_patch_flags_unknown_returns_404 \
       tests/test_content_manager_api.py::test_patch_crop_region -v
```

Expected: PASS all three.

- [ ] **Step 6: Commit**

```bash
git add highlight-curator/content_manager.py \
        highlight-curator/tests/test_content_manager_api.py
git commit -m "feat(cc): PATCH flag and crop_region endpoints"
```

---

## Task 5: Upload queue API

**Files:**
- Modify: `highlight-curator/content_manager.py`
- Test: `highlight-curator/tests/test_content_manager_api.py`

- [ ] **Step 1: Write failing tests**

```python
def delete_req(url):
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())

def test_queue_empty_on_start(server):
    status, body = get(server + "/api/upload/queue")
    data = json.loads(body)
    assert status == 200
    assert data["mode"] == "manual"
    assert data["queue"] == []

def test_queue_add_and_remove(server):
    status, data = post(server + "/api/upload/queue/add", {
        "snapshot": "golden_hour/sunrise/20260511_070000_scene.jpg",
        "title": "Sunrise", "keywords": "sunrise, texas", "platforms": ["shutterstock"]
    })
    assert status == 200 and data["ok"] is True

    status, body = get(server + "/api/upload/queue")
    items = json.loads(body)["queue"]
    assert len(items) == 1
    snap = items[0]["snapshot"]

    status, data = delete_req(server + "/api/upload/queue/" + urllib.parse.quote(snap, safe=''))
    assert status == 200 and data["ok"] is True

    status, body = get(server + "/api/upload/queue")
    assert json.loads(body)["queue"] == []

def test_queue_mode_switch(server):
    status, data = post(server + "/api/upload/queue/mode", {"mode": "auto"})
    assert status == 200
    _, body = get(server + "/api/upload/queue")
    assert json.loads(body)["mode"] == "auto"
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_content_manager_api.py::test_queue_empty_on_start -v
```

Expected: FAIL.

- [ ] **Step 3: Add queue helpers**

Add after `save_manifest()`:

```python
_queue_lock = threading.Lock()

def load_queue() -> dict:
    qf = HIGHLIGHTS_DIR / "upload_queue.json"
    return json.loads(qf.read_text()) if qf.exists() else {"mode": "manual", "queue": []}

def save_queue(q: dict) -> None:
    with _queue_lock:
        atomic_write_json(HIGHLIGHTS_DIR / "upload_queue.json", q)
```

- [ ] **Step 4: Add routes**

In `do_GET`:

```python
        elif p == "/api/upload/queue":
            self._send(200, "application/json", json.dumps(load_queue()).encode())
```

In `do_POST` before the final `else`:

```python
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
```

Add `do_DELETE` method to `ContentHandler` after `do_PATCH`:

```python
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
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_content_manager_api.py::test_queue_empty_on_start \
       tests/test_content_manager_api.py::test_queue_add_and_remove \
       tests/test_content_manager_api.py::test_queue_mode_switch -v
```

Expected: PASS all three.

- [ ] **Step 6: Commit**

```bash
git add highlight-curator/content_manager.py \
        highlight-curator/tests/test_content_manager_api.py
git commit -m "feat(cc): upload queue API (GET/POST/DELETE)"
```

---

## Task 6: Upload tab JavaScript

**Files:**
- Create: `highlight-curator/static/js/upload.js`

- [ ] **Step 1: Create `highlight-curator/static/js/upload.js`**

```javascript
// upload.js — split list+detail upload queue workflow
// All DOM text content set via textContent; no untrusted string goes into innerHTML.

let queueData = {mode: 'manual', queue: []};
let selectedQueueItem = null;

async function loadUploadQueue() {
  const r = await fetch('/api/upload/queue');
  queueData = await r.json();
  renderUploadTab();
}

function renderUploadTab() {
  const tab = document.getElementById('tab-upload');
  while (tab.firstChild) tab.removeChild(tab.firstChild);

  const shell = document.createElement('div');
  shell.id = 'upload-shell';

  shell.appendChild(buildQueueList());
  shell.appendChild(buildDetailPanel());
  tab.appendChild(shell);
}

function buildQueueList() {
  const list = document.createElement('div');
  list.id = 'queue-list';

  const header = document.createElement('div');
  header.id = 'queue-header';

  const countSpan = document.createElement('span');
  countSpan.style.color = '#888';
  countSpan.textContent = queueData.queue.length + ' queued';
  header.appendChild(countSpan);

  const uploadAllBtn = document.createElement('button');
  uploadAllBtn.className = 'ok';
  uploadAllBtn.style.cssText = 'font-size:11px;padding:3px 8px';
  uploadAllBtn.textContent = 'Upload all';
  uploadAllBtn.addEventListener('click', uploadAll);
  header.appendChild(uploadAllBtn);

  const modeLabel = document.createElement('label');
  modeLabel.style.cssText = 'font-size:11px;color:#888;display:flex;align-items:center;gap:4px;cursor:pointer';
  const modeCheck = document.createElement('input');
  modeCheck.type = 'checkbox';
  modeCheck.checked = queueData.mode === 'auto';
  modeCheck.addEventListener('change', function() { setMode(this.checked ? 'auto' : 'manual'); });
  modeLabel.appendChild(modeCheck);
  modeLabel.appendChild(document.createTextNode('Auto'));
  header.appendChild(modeLabel);
  list.appendChild(header);

  if (queueData.queue.length === 0) {
    const empty = document.createElement('div');
    empty.style.cssText = 'padding:20px;color:#555;font-size:13px;text-align:center';
    empty.textContent = 'Queue is empty. Use the Photos tab to queue photos.';
    list.appendChild(empty);
  } else {
    for (const item of queueData.queue) list.appendChild(makeQueueItem(item));
  }
  return list;
}

function makeQueueItem(item) {
  const el = document.createElement('div');
  el.className = 'queue-item' + (item === selectedQueueItem ? ' active' : '');

  const img = document.createElement('img');
  img.src = '/thumb/' + encodeURIComponent(item.snapshot);
  img.loading = 'lazy';
  img.alt = '';
  el.appendChild(img);

  const info = document.createElement('div');
  info.className = 'queue-item-info';

  const name = document.createElement('div');
  name.className = 'queue-item-name';
  name.textContent = item.snapshot.split('/').pop();
  info.appendChild(name);

  const statusEl = document.createElement('div');
  statusEl.className = 'queue-item-status';
  statusEl.style.color = statusColor(item.uploadStatus);
  statusEl.textContent = item.uploadStatus || 'pending';
  info.appendChild(statusEl);

  el.appendChild(info);
  el.addEventListener('click', function() {
    selectedQueueItem = item;
    renderUploadTab();
  });
  return el;
}

function statusColor(s) {
  if (s === 'uploaded') return '#2a7';
  if (s === 'error')    return '#c33';
  if (s === 'uploading') return '#fa0';
  return '#555';
}

function buildDetailPanel() {
  const detail = document.createElement('div');
  detail.id = 'detail-panel';
  if (!selectedQueueItem) {
    const hint = document.createElement('div');
    hint.style.cssText = 'color:#555;padding:20px';
    hint.textContent = 'Select a photo to review';
    detail.appendChild(hint);
    return detail;
  }
  const item = selectedQueueItem;

  const img = document.createElement('img');
  img.id = 'detail-preview';
  img.src = '/photo/' + encodeURIComponent(item.snapshot);
  img.alt = '';
  detail.appendChild(img);

  detail.appendChild(makeField('Title / Caption', 'detail-title', 'text', item.title || ''));
  detail.appendChild(makeField('Keywords (comma-separated)', 'detail-keywords', 'text', item.keywords || ''));

  const platDiv = document.createElement('div');
  const platLabel = document.createElement('div');
  platLabel.className = 'field-label';
  platLabel.textContent = 'Send to';
  platDiv.appendChild(platLabel);
  platDiv.appendChild(makePlatformCheck('shutterstock', 'Shutterstock', item));
  platDiv.appendChild(makePlatformCheck('adobe_stock', 'Adobe Stock', item));
  detail.appendChild(platDiv);

  const btnRow = document.createElement('div');
  btnRow.style.cssText = 'display:flex;gap:8px;margin-top:auto';

  const uploadBtn = document.createElement('button');
  uploadBtn.className = 'ok';
  uploadBtn.textContent = 'Upload this photo';
  uploadBtn.addEventListener('click', submitOne);
  btnRow.appendChild(uploadBtn);

  const skipBtn = document.createElement('button');
  skipBtn.className = 'sec';
  skipBtn.textContent = 'Skip';
  skipBtn.addEventListener('click', skipOne);
  btnRow.appendChild(skipBtn);

  const removeBtn = document.createElement('button');
  removeBtn.style.marginLeft = 'auto';
  removeBtn.textContent = 'Remove';
  removeBtn.addEventListener('click', function() { removeFromQueue(item.snapshot); });
  btnRow.appendChild(removeBtn);

  detail.appendChild(btnRow);
  return detail;
}

function makeField(labelText, id, type, value) {
  const wrap = document.createElement('div');
  const lbl = document.createElement('div');
  lbl.className = 'field-label';
  lbl.textContent = labelText;
  const inp = document.createElement('input');
  inp.className = 'field-input';
  inp.id = id;
  inp.type = type;
  inp.value = value;
  wrap.appendChild(lbl);
  wrap.appendChild(inp);
  return wrap;
}

function makePlatformCheck(value, labelText, item) {
  const label = document.createElement('label');
  label.style.cssText = 'display:flex;gap:6px;align-items:center;margin-bottom:4px;font-size:13px';
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.id = 'plat-' + value;
  cb.checked = (item.platforms || []).includes(value);
  const txt = document.createElement('span');
  txt.textContent = labelText;
  label.appendChild(cb);
  label.appendChild(txt);
  return label;
}

async function setMode(mode) {
  await fetch('/api/upload/queue/mode', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mode})
  });
  queueData.mode = mode;
}

async function removeFromQueue(snapshot) {
  await fetch('/api/upload/queue/' + encodeURIComponent(snapshot), {method: 'DELETE'});
  selectedQueueItem = null;
  await loadUploadQueue();
}

async function submitOne() {
  if (!selectedQueueItem) return;
  const snap = selectedQueueItem.snapshot;
  const title    = document.getElementById('detail-title')?.value    || '';
  const keywords = document.getElementById('detail-keywords')?.value || '';
  const platforms = [];
  if (document.getElementById('plat-shutterstock')?.checked) platforms.push('shutterstock');
  if (document.getElementById('plat-adobe_stock')?.checked)  platforms.push('adobe_stock');
  const r = await fetch('/api/upload/' + encodeURIComponent(snap) + '/submit', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({title, keywords, platforms})
  });
  const data = await r.json();
  if (data.ok) { showToast('Uploaded'); await loadUploadQueue(); }
  else showToast('Upload failed: ' + (data.error || 'unknown'), false);
}

function skipOne() {
  if (!queueData.queue.length) return;
  const idx = queueData.queue.indexOf(selectedQueueItem);
  selectedQueueItem = queueData.queue[(idx + 1) % queueData.queue.length] || null;
  renderUploadTab();
}

async function uploadAll() {
  const r = await fetch('/api/upload/run', {method: 'POST'});
  const data = await r.json();
  showToast(data.ok ? 'Auto-run started' : ('Error: ' + (data.error || 'unknown')), data.ok);
  setTimeout(loadUploadQueue, 500);
}
```

- [ ] **Step 2: Verify in browser**

Reload, click Upload. Empty queue message shows. Queue a photo from Photos tab. Upload tab shows the item with thumbnail. Select it — detail panel populates. Title/keywords editable.

- [ ] **Step 3: Commit**

```bash
git add highlight-curator/static/js/upload.js
git commit -m "feat(cc): upload tab split list+detail JS"
```

---

## Task 7: Platform credentials API

**Files:**
- Modify: `highlight-curator/content_manager.py`
- Test: `highlight-curator/tests/test_content_manager_api.py`

- [ ] **Step 1: Write failing tests**

```python
def test_platforms_status_returns_structure(server, monkeypatch, tmp_path):
    import content_manager as cm
    monkeypatch.setattr(cm, "CREDS_PATH", tmp_path / "creds.json")
    status, body = get(server + "/api/platforms/status")
    data = json.loads(body)
    assert status == 200
    assert "shutterstock" in data
    assert "adobe_stock" in data
    assert "access_token" not in json.dumps(data)

def test_platforms_credentials_save(server, monkeypatch, tmp_path):
    import content_manager as cm
    monkeypatch.setattr(cm, "CREDS_PATH", tmp_path / "creds.json")
    status, data = post(server + "/api/platforms/credentials", {
        "platform": "shutterstock",
        "client_id": "test_id",
        "client_secret": "test_secret"
    })
    assert status == 200
    assert data["ok"] is True
    assert (tmp_path / "creds.json").exists()
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_content_manager_api.py::test_platforms_status_returns_structure -v
```

Expected: FAIL.

- [ ] **Step 3: Add constants and helpers**

Near the top constants:

```python
CREDS_PATH = Path.home() / ".gtn" / "platform_creds.json"
```

After `save_queue()`:

```python
def load_creds() -> dict:
    if CREDS_PATH.exists():
        return json.loads(CREDS_PATH.read_text())
    return {"shutterstock": {}, "adobe_stock": {}, "anthropic": {}}

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
```

- [ ] **Step 4: Add routes**

In `do_GET`:

```python
        elif p == "/api/platforms/status":
            self._send(200, "application/json", json.dumps(platform_status()).encode())
```

In `do_POST`:

```python
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
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_content_manager_api.py::test_platforms_status_returns_structure \
       tests/test_content_manager_api.py::test_platforms_credentials_save -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add highlight-curator/content_manager.py \
        highlight-curator/tests/test_content_manager_api.py
git commit -m "feat(cc): platform credentials API"
```

---

## Task 8: Platform API clients

**Files:**
- Create: `highlight-curator/platforms/__init__.py`
- Create: `highlight-curator/platforms/shutterstock.py`
- Create: `highlight-curator/platforms/adobe_stock.py`
- Create: `highlight-curator/tests/test_platform_clients.py`

- [ ] **Step 1: Create `highlight-curator/platforms/__init__.py`**

```python
from .shutterstock import ShutterstockClient
from .adobe_stock import AdobeStockClient

__all__ = ["ShutterstockClient", "AdobeStockClient"]
```

- [ ] **Step 2: Create `highlight-curator/platforms/shutterstock.py`**

```python
"""Shutterstock Contributor API client. Uses stdlib only."""
import base64
import json
import uuid
from pathlib import Path
from urllib import request as urlreq

BASE = "https://api.shutterstock.com/v2"


class ShutterstockClient:
    def __init__(self, client_id: str, client_secret: str, access_token: str = ""):
        self.client_id    = client_id
        self.client_secret = client_secret
        self.access_token = access_token

    def refresh_token(self) -> None:
        creds_b64 = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        req = urlreq.Request(
            f"{BASE}/oauth/access_token",
            data=b"grant_type=client_credentials",
            headers={"Authorization": f"Basic {creds_b64}",
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlreq.urlopen(req) as r:
            self.access_token = json.loads(r.read())["access_token"]

    def upload(self, image_path: Path, metadata: dict) -> dict:
        if not self.access_token:
            self.refresh_token()
        body, ct = _build_multipart(
            {"description": metadata.get("title", ""),
             "keywords":    metadata.get("keywords", "")},
            "file", image_path,
        )
        req = urlreq.Request(
            f"{BASE}/images",
            data=body,
            headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": ct},
        )
        with urlreq.urlopen(req) as r:
            return {"asset_id": str(json.loads(r.read()).get("id", ""))}

    def get_status(self, asset_id: str) -> str:
        if not self.access_token:
            self.refresh_token()
        req = urlreq.Request(
            f"{BASE}/images/{asset_id}",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )
        try:
            with urlreq.urlopen(req) as r:
                return json.loads(r.read()).get("status", "unknown")
        except Exception:
            return "unknown"


def _build_multipart(fields: dict, file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = "GTNboundary" + uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
             f"{value}\r\n").encode()
        )
    file_bytes = file_path.read_bytes()
    parts.append(
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\";"
         f" filename=\"{file_path.name}\"\r\nContent-Type: image/jpeg\r\n\r\n").encode()
        + file_bytes + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
```

- [ ] **Step 3: Create `highlight-curator/platforms/adobe_stock.py`**

```python
"""Adobe Stock Contributor API client. Uses stdlib only."""
import json
import uuid
from pathlib import Path
from urllib import request as urlreq
from urllib.parse import urlencode

IMS_BASE   = "https://ims-na1.adobelogin.com"
STOCK_BASE = "https://stock.adobe.com/Rest/Media/1/Files"


class AdobeStockClient:
    def __init__(self, api_key: str, client_secret: str, access_token: str = ""):
        self.api_key      = api_key
        self.client_secret = client_secret
        self.access_token = access_token

    def refresh_token(self) -> None:
        data = urlencode({
            "grant_type":    "client_credentials",
            "client_id":     self.api_key,
            "client_secret": self.client_secret,
            "scope":         "openid,AdobeID,stock_contributor",
        }).encode()
        req = urlreq.Request(
            f"{IMS_BASE}/ims/token/v3",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlreq.urlopen(req) as r:
            self.access_token = json.loads(r.read())["access_token"]

    def upload(self, image_path: Path, metadata: dict) -> dict:
        if not self.access_token:
            self.refresh_token()
        body, ct = _build_multipart(
            {"title":    metadata.get("title", ""),
             "keywords": metadata.get("keywords", "")},
            "file", image_path,
        )
        req = urlreq.Request(
            STOCK_BASE,
            data=body,
            headers={"Authorization": f"Bearer {self.access_token}",
                     "x-api-key": self.api_key,
                     "Content-Type": ct},
        )
        with urlreq.urlopen(req) as r:
            return {"asset_id": str(json.loads(r.read()).get("id", ""))}

    def get_status(self, asset_id: str) -> str:
        if not self.access_token:
            self.refresh_token()
        req = urlreq.Request(
            f"{STOCK_BASE}/{asset_id}",
            headers={"Authorization": f"Bearer {self.access_token}",
                     "x-api-key": self.api_key},
        )
        try:
            with urlreq.urlopen(req) as r:
                return json.loads(r.read()).get("status", "unknown")
        except Exception:
            return "unknown"


def _build_multipart(fields: dict, file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = "GTNboundary" + uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
             f"{value}\r\n").encode()
        )
    file_bytes = file_path.read_bytes()
    parts.append(
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\";"
         f" filename=\"{file_path.name}\"\r\nContent-Type: image/jpeg\r\n\r\n").encode()
        + file_bytes + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
```

Note: `_build_multipart` is intentionally duplicated across the two client files. They are independent modules and the function is small enough that the duplication is cheaper than a shared helper that would couple them.

- [ ] **Step 4: Write unit tests**

Create `highlight-curator/tests/test_platform_clients.py`:

```python
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from platforms.shutterstock import ShutterstockClient
from platforms.adobe_stock import AdobeStockClient


def _mock_urlopen(body: dict):
    m = MagicMock()
    m.__enter__ = lambda s: s
    m.__exit__ = MagicMock(return_value=False)
    m.read.return_value = json.dumps(body).encode()
    return m


def test_shutterstock_refresh_token():
    client = ShutterstockClient("cid", "csec")
    with patch("urllib.request.urlopen", return_value=_mock_urlopen({"access_token": "tok"})):
        client.refresh_token()
    assert client.access_token == "tok"


def test_shutterstock_upload_returns_asset_id(tmp_path):
    img = tmp_path / "t.jpg"
    img.write_bytes(b"FAKEJPEG")
    client = ShutterstockClient("cid", "csec", access_token="tok")
    with patch("urllib.request.urlopen", return_value=_mock_urlopen({"id": "9876"})):
        result = client.upload(img, {"title": "Test", "keywords": "test"})
    assert result["asset_id"] == "9876"


def test_adobe_refresh_token():
    client = AdobeStockClient("apikey", "csec")
    with patch("urllib.request.urlopen", return_value=_mock_urlopen({"access_token": "adobe_tok"})):
        client.refresh_token()
    assert client.access_token == "adobe_tok"


def test_adobe_upload_returns_asset_id(tmp_path):
    img = tmp_path / "t.jpg"
    img.write_bytes(b"FAKEJPEG")
    client = AdobeStockClient("apikey", "csec", access_token="tok")
    with patch("urllib.request.urlopen", return_value=_mock_urlopen({"id": "adobe_5678"})):
        result = client.upload(img, {"title": "Test", "keywords": "nature"})
    assert result["asset_id"] == "adobe_5678"
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_platform_clients.py -v
```

Expected: PASS all four.

- [ ] **Step 6: Commit**

```bash
git add highlight-curator/platforms/ \
        highlight-curator/tests/test_platform_clients.py
git commit -m "feat(cc): Shutterstock + Adobe Stock API clients"
```

---

## Task 9: Upload submit logic

**Files:**
- Modify: `highlight-curator/content_manager.py`
- Test: `highlight-curator/tests/test_content_manager_api.py`

- [ ] **Step 1: Write failing test**

```python
def test_submit_no_platforms_returns_400(server):
    snap = "golden_hour/sunrise/20260511_070000_scene.jpg"
    post(server + "/api/upload/queue/add",
         {"snapshot": snap, "title": "T", "keywords": "k", "platforms": []})
    try:
        post(server + "/api/upload/" + urllib.parse.quote(snap, safe='') + "/submit",
             {"title": "T", "keywords": "k", "platforms": []})
        assert False, "expected 400"
    except urllib.error.HTTPError as e:
        assert e.code == 400
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_content_manager_api.py::test_submit_no_platforms_returns_400 -v
```

Expected: FAIL (404).

- [ ] **Step 3: Add crop copy helper**

Add after `delete_snapshots()`:

```python
def _make_crop_copy(entry: dict) -> Path | None:
    if not entry.get("flags", {}).get("crop"):
        return None
    region = entry.get("crop_region")
    if not region:
        return None
    from PIL import Image
    src = HIGHLIGHTS_DIR / entry["snapshot"]
    if not src.exists():
        raise FileNotFoundError(f"Source missing: {src}")
    img = Image.open(src)
    w, h = img.size
    x1 = int(region["x"] * w)
    y1 = int(region["y"] * h)
    x2 = int((region["x"] + region["w"]) * w)
    y2 = int((region["y"] + region["h"]) * h)
    cropped = img.crop((x1, y1, x2, y2))
    crop_path = src.with_name(src.stem + "_crop" + src.suffix)
    cropped.save(crop_path, quality=95)
    return crop_path
```

- [ ] **Step 4: Add submit dispatch helper**

Add after `platform_status()`:

```python
def _submit_to_platforms(entry: dict, metadata: dict) -> dict:
    from platforms import ShutterstockClient, AdobeStockClient
    image_path = _make_crop_copy(entry) or (HIGHLIGHTS_DIR / entry["snapshot"])
    creds = load_creds()
    client_map = {
        "shutterstock": lambda: ShutterstockClient(
            creds.get("shutterstock", {}).get("client_id", ""),
            creds.get("shutterstock", {}).get("client_secret", ""),
            creds.get("shutterstock", {}).get("access_token", ""),
        ),
        "adobe_stock": lambda: AdobeStockClient(
            creds.get("adobe_stock", {}).get("api_key", ""),
            creds.get("adobe_stock", {}).get("client_secret", ""),
            creds.get("adobe_stock", {}).get("access_token", ""),
        ),
    }
    results = {}
    for platform in metadata.get("platforms", []):
        if platform not in client_map:
            results[platform] = {"status": "error", "error": "unknown platform"}
            continue
        try:
            resp = client_map[platform]().upload(image_path, metadata)
            results[platform] = {"status": "uploaded", "asset_id": resp["asset_id"]}
        except Exception as exc:
            results[platform] = {"status": "error", "error": str(exc)}
    return results
```

- [ ] **Step 5: Add submit and auto-run routes**

In `do_POST` before the final `else`:

```python
        elif re.match(r"^/api/upload/.+/submit$", p):
            m_path = re.match(r"^/api/upload/(.+)/submit$", p)
            snap = safe_rel(unquote(m_path.group(1)))
            if not snap:
                self._send(403, "application/json", b'{"error":"forbidden"}'); return
            if not payload.get("platforms"):
                self._send(400, "application/json", b'{"error":"no platforms selected"}'); return
            manifest = load_manifest()
            _, entry = find_entry_by_snapshot(manifest, snap)
            if entry is None:
                self._send(404, "application/json", b'{"error":"not found"}'); return
            try:
                results = _submit_to_platforms(entry, payload)
            except Exception as exc:
                self._send(500, "application/json",
                           json.dumps({"error": str(exc)}).encode()); return
            from manifest_io import locked_manifest_update
            def _record(m, _snap=snap, _results=results):
                _, e = find_entry_by_snapshot(m, _snap)
                if e is not None:
                    e.setdefault("uploads", {}).update(_results)
            locked_manifest_update(HIGHLIGHTS_DIR / "manifest.json", _record)
            q = load_queue()
            q["queue"] = [e for e in q["queue"] if e.get("snapshot") != snap]
            save_queue(q)
            self._send(200, "application/json",
                       json.dumps({"ok": True, "results": results}).encode())
        elif p == "/api/upload/run":
            def _auto():
                q = load_queue()
                for item in list(q["queue"]):
                    m2 = load_manifest()
                    _, entry = find_entry_by_snapshot(m2, item["snapshot"])
                    if entry is None:
                        continue
                    try:
                        results = _submit_to_platforms(entry, item)
                        from manifest_io import locked_manifest_update
                        def _rec(m3, _s=item["snapshot"], _r=results):
                            _, e = find_entry_by_snapshot(m3, _s)
                            if e is not None:
                                e.setdefault("uploads", {}).update(_r)
                        locked_manifest_update(HIGHLIGHTS_DIR / "manifest.json", _rec)
                    except Exception as exc:
                        log.error("auto-run error: %s", exc)
                q2 = load_queue()
                q2["queue"] = []
                save_queue(q2)
            threading.Thread(target=_auto, daemon=True).start()
            self._send(200, "application/json", b'{"ok":true}')
```

- [ ] **Step 6: Run test**

```bash
pytest tests/test_content_manager_api.py::test_submit_no_platforms_returns_400 -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add highlight-curator/content_manager.py \
        highlight-curator/tests/test_content_manager_api.py
git commit -m "feat(cc): upload submit + auto-run + crop copy"
```

---

## Task 10: Claude proxy API

**Files:**
- Modify: `highlight-curator/content_manager.py`
- Test: `highlight-curator/tests/test_content_manager_api.py`

- [ ] **Step 1: Write failing test**

```python
def test_claude_missing_key_returns_503(server, monkeypatch, tmp_path):
    import content_manager as cm
    monkeypatch.setattr(cm, "CREDS_PATH", tmp_path / "creds.json")
    try:
        post(server + "/api/claude/chat", {"message": "Hello", "context": {}})
        assert False, "expected 503"
    except urllib.error.HTTPError as e:
        assert e.code == 503
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_content_manager_api.py::test_claude_missing_key_returns_503 -v
```

Expected: FAIL (404).

- [ ] **Step 3: Add the proxy function**

Add after `_submit_to_platforms()`:

```python
def _call_claude(message: str, context: dict) -> str:
    from urllib import request as urlreq
    creds = load_creds()
    api_key = creds.get("anthropic", {}).get("api_key", "")
    if not api_key:
        raise ValueError("No Anthropic API key — add it in the Platforms tab")
    model = creds.get("anthropic", {}).get("model", "claude-haiku-4-5-20251001")
    system = (
        "You are an assistant for the Ground Truth Network (GTN), a wildlife and weather "
        "camera system. You help the operator prepare photos for stock submission to Shutterstock "
        "and Adobe Stock. Suggest concise, stock-appropriate keywords, titles, and captions. "
        f"Current UI context: {json.dumps(context)}"
    )
    body = json.dumps({
        "model":      model,
        "max_tokens": 1024,
        "system":     system,
        "messages":   [{"role": "user", "content": message}],
    }).encode()
    req = urlreq.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={"x-api-key": api_key,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
    )
    with urlreq.urlopen(req) as r:
        return json.loads(r.read())["content"][0]["text"]
```

- [ ] **Step 4: Add the route**

In `do_POST`:

```python
        elif p == "/api/claude/chat":
            message = payload.get("message", "")
            if not message:
                self._send(400, "application/json", b'{"error":"message required"}'); return
            try:
                reply = _call_claude(message, payload.get("context", {}))
                self._send(200, "application/json", json.dumps({"reply": reply}).encode())
            except ValueError as exc:
                self._send(503, "application/json",
                           json.dumps({"error": str(exc)}).encode())
            except Exception as exc:
                log.error("Claude API error: %s", exc)
                self._send(502, "application/json",
                           json.dumps({"error": "Claude API unavailable"}).encode())
```

- [ ] **Step 5: Run test**

```bash
pytest tests/test_content_manager_api.py::test_claude_missing_key_returns_503 -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add highlight-curator/content_manager.py \
        highlight-curator/tests/test_content_manager_api.py
git commit -m "feat(cc): POST /api/claude/chat proxy"
```

---

## Task 11: Claude panel + Platforms tab JS + Status API

**Files:**
- Create: `highlight-curator/static/js/claude_panel.js`
- Create: `highlight-curator/static/js/platforms.js`
- Modify: `highlight-curator/content_manager.py`
- Test: `highlight-curator/tests/test_content_manager_api.py`

- [ ] **Step 1: Add status route and test**

In `do_GET`:

```python
        elif p == "/api/status":
            import shutil as _shutil
            try:
                usage = _shutil.disk_usage(str(HIGHLIGHTS_DIR))
                storage = {"total": usage.total, "used": usage.used, "free": usage.free}
            except Exception:
                storage = {}
            m = load_manifest()
            q = load_queue()
            self._send(200, "application/json", json.dumps({
                "storage":          storage,
                "entry_count":      len(m.get("entries", [])),
                "manifest_updated": m.get("updated", ""),
                "queue_depth":      len(q.get("queue", [])),
            }).encode())
```

Test:

```python
def test_status_endpoint(server):
    status, body = get(server + "/api/status")
    data = json.loads(body)
    assert status == 200
    assert "entry_count" in data
    assert "queue_depth" in data
```

```bash
pytest tests/test_content_manager_api.py::test_status_endpoint -v
```

Expected: PASS.

- [ ] **Step 2: Create `highlight-curator/static/js/claude_panel.js`**

```javascript
// claude_panel.js — Claude assistant panel
// All AI reply text set via textContent to prevent XSS.

function claudeContext() {
  const ctx = {current_tab: window.currentTab || 'photos'};
  if (window.selectedQueueItem) {
    ctx.selected_photo = {
      snapshot:  window.selectedQueueItem.snapshot,
      title:     window.selectedQueueItem.title,
      platforms: window.selectedQueueItem.platforms,
    };
  }
  if (window.queueData) ctx.queue_depth = (window.queueData.queue || []).length;
  if (window.photosData) ctx.total_photos = window.photosData.length;
  return ctx;
}

async function claudeSend() {
  const input = document.getElementById('claude-input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';

  const messages = document.getElementById('claude-messages');

  const userBubble = document.createElement('div');
  userBubble.className = 'msg-user';
  userBubble.textContent = msg;
  messages.appendChild(userBubble);
  messages.scrollTop = messages.scrollHeight;

  const aiBubble = document.createElement('div');
  aiBubble.className = 'msg-ai';
  aiBubble.textContent = '...';
  messages.appendChild(aiBubble);
  messages.scrollTop = messages.scrollHeight;

  try {
    const r = await fetch('/api/claude/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg, context: claudeContext()}),
    });
    const data = await r.json();
    aiBubble.textContent = data.reply || data.error || 'No response';
  } catch (err) {
    aiBubble.textContent = 'Error: ' + err.message;
    aiBubble.style.color = '#f66';
  }
  messages.scrollTop = messages.scrollHeight;
}

document.addEventListener('DOMContentLoaded', function() {
  const input = document.getElementById('claude-input');
  const sendBtn = document.getElementById('claude-send');
  if (input) {
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); claudeSend(); }
    });
  }
  if (sendBtn) sendBtn.addEventListener('click', claudeSend);
});
```

- [ ] **Step 3: Create `highlight-curator/static/js/platforms.js`**

```javascript
// platforms.js — platform configuration and status tab
// Dynamic data inserted via textContent; form values set via .value property (safe).

async function loadPlatforms() {
  const tab = document.getElementById('tab-platforms');
  while (tab.firstChild) tab.removeChild(tab.firstChild);
  const r = await fetch('/api/platforms/status');
  const status = await r.json();
  tab.appendChild(makePlatformCard('shutterstock', 'Shutterstock',
    status.shutterstock, ['client_id', 'client_secret']));
  tab.appendChild(makePlatformCard('adobe_stock', 'Adobe Stock',
    status.adobe_stock, ['api_key', 'client_secret']));
  tab.appendChild(makeAnthropicCard());
}

function makePlatformCard(id, name, st, fields) {
  const card = document.createElement('div');
  card.className = 'platform-card';

  const h3 = document.createElement('h3');
  const dot = document.createElement('span');
  dot.className = 'dot ' + (st && st.configured ? (st.has_token ? 'dot-green' : 'dot-grey') : 'dot-red');
  h3.appendChild(dot);
  h3.appendChild(document.createTextNode(' ' + name));
  card.appendChild(h3);

  const sub = document.createElement('p');
  sub.style.cssText = 'font-size:12px;color:#666;margin-bottom:10px';
  sub.textContent = st && st.configured ? (st.has_token ? 'Connected' : 'No token yet') : 'Not configured';
  card.appendChild(sub);

  const form = buildCredForm(id, fields);
  card.appendChild(form);
  return card;
}

function makeAnthropicCard() {
  const card = document.createElement('div');
  card.className = 'platform-card';
  const h3 = document.createElement('h3');
  h3.textContent = 'Claude (Anthropic)';
  card.appendChild(h3);
  const form = document.createElement('form');
  form.addEventListener('submit', function(e) { e.preventDefault(); saveCreds('anthropic', form); });

  form.appendChild(makeFormField('API key', 'api_key', 'password', 'sk-ant-...'));

  const lblDiv = document.createElement('div');
  lblDiv.style.marginBottom = '8px';
  const lbl = document.createElement('div');
  lbl.className = 'field-label';
  lbl.textContent = 'Model';
  const sel = document.createElement('select');
  sel.className = 'field-input';
  sel.name = 'model';
  [['claude-haiku-4-5-20251001', 'Haiku (fast, cheap)'],
   ['claude-sonnet-4-6',         'Sonnet (smarter)']].forEach(function(opt) {
    const o = document.createElement('option');
    o.value = opt[0];
    o.textContent = opt[1];
    sel.appendChild(o);
  });
  lblDiv.appendChild(lbl);
  lblDiv.appendChild(sel);
  form.appendChild(lblDiv);

  const btn = document.createElement('button');
  btn.className = 'ok';
  btn.type = 'submit';
  btn.style.cssText = 'font-size:12px;padding:5px 12px';
  btn.textContent = 'Save';
  form.appendChild(btn);
  card.appendChild(form);
  return card;
}

function buildCredForm(platform, fields) {
  const form = document.createElement('form');
  form.addEventListener('submit', function(e) { e.preventDefault(); saveCreds(platform, form); });
  for (const f of fields) {
    form.appendChild(makeFormField(f.replace(/_/g, ' '), f, 'password', ''));
  }
  const btn = document.createElement('button');
  btn.className = 'ok';
  btn.type = 'submit';
  btn.style.cssText = 'font-size:12px;padding:5px 12px';
  btn.textContent = 'Save credentials';
  form.appendChild(btn);
  return form;
}

function makeFormField(labelText, name, type, placeholder) {
  const wrap = document.createElement('div');
  wrap.style.marginBottom = '8px';
  const lbl = document.createElement('div');
  lbl.className = 'field-label';
  lbl.textContent = labelText;
  const inp = document.createElement('input');
  inp.className = 'field-input';
  inp.name = name;
  inp.type = type;
  inp.autocomplete = 'off';
  inp.placeholder = placeholder;
  wrap.appendChild(lbl);
  wrap.appendChild(inp);
  return wrap;
}

async function saveCreds(platform, form) {
  const data = {platform};
  for (const el of form.elements) {
    if (el.name && el.value) data[el.name] = el.value;
  }
  const r = await fetch('/api/platforms/credentials', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data),
  });
  const resp = await r.json();
  if (resp.ok) { showToast('Credentials saved'); loadPlatforms(); }
  else showToast('Error: ' + (resp.error || 'unknown'), false);
}

function gb(n) { return (n / 1e9).toFixed(1) + ' GB'; }

async function loadStatus() {
  const tab = document.getElementById('tab-status');
  while (tab.firstChild) tab.removeChild(tab.firstChild);
  const r = await fetch('/api/status');
  const data = await r.json();

  const h2 = document.createElement('h2');
  h2.style.cssText = 'margin-bottom:16px;font-size:15px';
  h2.textContent = 'System Status';
  tab.appendChild(h2);

  const grid = document.createElement('div');
  grid.style.cssText = 'display:grid;gap:12px;max-width:400px';

  grid.appendChild(makeStatusCard('Storage (highlights)',
    data.storage ? gb(data.storage.used) + ' used / ' + gb(data.storage.total) + ' total' : 'unavailable'));
  grid.appendChild(makeStatusCard('Manifest',
    data.entry_count + ' entries \xb7 last updated ' + (data.manifest_updated || 'never')));
  grid.appendChild(makeStatusCard('Upload Queue',
    data.queue_depth + ' item(s) pending'));
  tab.appendChild(grid);
}

function makeStatusCard(title, detail) {
  const card = document.createElement('div');
  card.className = 'platform-card';
  const h3 = document.createElement('h3');
  h3.textContent = title;
  const p = document.createElement('div');
  p.style.cssText = 'font-size:13px;color:#aaa;margin-top:6px';
  p.textContent = detail;
  card.appendChild(h3);
  card.appendChild(p);
  return card;
}
```

- [ ] **Step 4: Verify in browser**

Reload. Check all tabs:
- Platforms tab: three cards, form inputs accept credentials, Save shows toast
- Status tab: storage, manifest count, queue depth render
- Claude panel: toggle opens/closes; without key, shows 503 error text; with key configured, replies appear

- [ ] **Step 5: Commit**

```bash
git add highlight-curator/static/js/claude_panel.js \
        highlight-curator/static/js/platforms.js \
        highlight-curator/content_manager.py \
        highlight-curator/tests/test_content_manager_api.py
git commit -m "feat(cc): Claude panel, platforms tab, status tab"
```

---

## Task 12: Full test suite + golden path verification

- [ ] **Step 1: Run all tests**

```bash
cd weather-station/highlight-curator
pytest tests/ -v
```

All tests must pass before proceeding.

- [ ] **Step 2: Start server and walk golden path**

```bash
python3 highlight-curator/content_manager.py \
  --highlights-dir /volume1/highlights \
  --frigate-dir /volume1/docker/frigate/media/recordings
```

Walk through at `http://192.168.100.202:8766`:

1. **Photos** — grid loads, flag chips appear, popover opens on click, flag toggle updates chip, "Queue for upload" adds to queue
2. **Upload** — queued item appears in left list, click to see detail panel, title/keywords editable, Submit button present
3. **Platforms** — all three cards present, credentials save to `~/.gtn/platform_creds.json` (verify: `cat ~/.gtn/platform_creds.json`), file is chmod 600 (verify: `ls -la ~/.gtn/`)
4. **Status** — storage, entry count, queue depth all render
5. **Claude panel** — toggle opens/closes, sending without API key shows "add it in the Platforms tab" message, after adding key responses appear

- [ ] **Step 3: Verify backward compatibility**

- `GET /api/images` still returns category data
- `POST /api/timelapse/build` still queues builds (Timelapse tab content is blank — see note)
- `POST /api/pipeline/run` still triggers sync

**Note on Timelapse tab:** The new sidebar shell does not load the timelapse JS (it was inline in the old `_HTML` string). The Timelapse tab content area renders empty. Extract the timelapse JS from `_HTML` into `static/js/timelapse.js` as a follow-up task — the API endpoints all still work.

- [ ] **Step 4: Final commit**

```bash
git add -u
git commit -m "feat(cc): GTN Command Center complete — photos, upload, platforms, Claude panel"
```
