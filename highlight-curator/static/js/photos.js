// photos.js — renders photo grid with flag chips
// All API-derived strings inserted into innerHTML must pass through escHtml() (defined in command_center.html).

let photosData = [];

async function loadPhotos() {
  const tab = document.getElementById('tab-photos');
  tab.textContent = 'Loading...';
  try {
    const r = await fetch('/api/photos');
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();
    photosData = data.entries || [];
    renderPhotos(tab);
  } catch (err) {
    tab.textContent = '';
    showToast('Failed to load photos', false);
  }
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
  if (entry.flags && entry.flags.crop)      chips.appendChild(makeChip('CROP', 'chip-crop', entry));
  if (entry.flags && entry.flags.enhance)   chips.appendChild(makeChip('ENH',  'chip-enh',  entry));
  if (entry.flags && entry.flags.auth_hold) chips.appendChild(makeChip('HOLD', 'chip-hold', entry));
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

function makeChip(label, cls, entry) {
  const chip = document.createElement('span');
  chip.className = 'chip ' + cls;
  chip.textContent = label;
  chip.addEventListener('click', function(e) {
    e.stopPropagation();
    openFlagPopover(entry, e.currentTarget.closest('.photo-card'));
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

  const sep = document.createElement('div');
  sep.style.cssText = 'border-top:1px solid #333;margin:8px 0';
  pop.appendChild(sep);

  const cropBtn = document.createElement('button');
  cropBtn.className = 'sec';
  cropBtn.textContent = entry.crop_region ? 'Edit crop region' : 'Set crop region';
  cropBtn.style.cssText = 'font-size:11px;padding:3px 8px;width:100%';
  cropBtn.addEventListener('click', function() { pop.remove(); openCropPicker(entry); });
  pop.appendChild(cropBtn);

  if (entry.flags && entry.flags.crop && entry.crop_region) {
    const applyBtn = document.createElement('button');
    applyBtn.className = 'ok';
    applyBtn.textContent = entry.crop_applied ? 'Re-apply crop' : 'Apply crop → stock_ready';
    applyBtn.style.cssText = 'font-size:11px;padding:3px 8px;margin-top:4px;width:100%';
    applyBtn.addEventListener('click', function() { pop.remove(); applyCrop(entry); });
    pop.appendChild(applyBtn);
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

// ── Crop picker ───────────────────────────────────────────────────────────────

function openCropPicker(entry) {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:100;' +
    'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px';

  const hint = document.createElement('div');
  hint.style.cssText = 'color:#888;font-size:12px';
  hint.textContent = 'Drag to select crop region';
  overlay.appendChild(hint);

  const frame = document.createElement('div');
  frame.style.cssText = 'position:relative;display:inline-block;cursor:crosshair;user-select:none';

  const img = document.createElement('img');
  img.src = '/photo/' + encodeURIComponent(entry.snapshot);
  img.style.cssText = 'max-width:80vw;max-height:70vh;display:block';
  frame.appendChild(img);

  // Selection rectangle drawn on top of the image
  const sel = document.createElement('div');
  sel.style.cssText = 'position:absolute;border:2px solid #fa0;background:rgba(255,170,0,.12);' +
    'pointer-events:none;display:none';
  frame.appendChild(sel);
  overlay.appendChild(frame);

  const coords = document.createElement('div');
  coords.style.cssText = 'color:#fa0;font-size:12px;font-family:monospace';
  coords.textContent = entry.crop_region
    ? `saved: x=${entry.crop_region.x.toFixed(3)} y=${entry.crop_region.y.toFixed(3)} ` +
      `w=${entry.crop_region.w.toFixed(3)} h=${entry.crop_region.h.toFixed(3)}`
    : 'no region set';
  overlay.appendChild(coords);

  const btnRow = document.createElement('div');
  btnRow.style.cssText = 'display:flex;gap:8px';
  const saveBtn = document.createElement('button');
  saveBtn.className = 'ok';
  saveBtn.textContent = 'Save region';
  saveBtn.disabled = !entry.crop_region;
  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'sec';
  cancelBtn.textContent = 'Cancel';
  btnRow.appendChild(saveBtn);
  btnRow.appendChild(cancelBtn);
  overlay.appendChild(btnRow);

  let region = entry.crop_region ? {...entry.crop_region} : null;
  let dragging = false, ox = 0, oy = 0;

  function imgRect() { return img.getBoundingClientRect(); }

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function updateSel(r) {
    const ir = imgRect();
    sel.style.left   = (r.x * ir.width)  + 'px';
    sel.style.top    = (r.y * ir.height) + 'px';
    sel.style.width  = (r.w * ir.width)  + 'px';
    sel.style.height = (r.h * ir.height) + 'px';
    sel.style.display = 'block';
    coords.textContent = `x=${r.x.toFixed(3)} y=${r.y.toFixed(3)} w=${r.w.toFixed(3)} h=${r.h.toFixed(3)}`;
    saveBtn.disabled = false;
  }

  if (region) updateSel(region);

  frame.addEventListener('mousedown', function(e) {
    const ir = imgRect();
    ox = clamp((e.clientX - ir.left) / ir.width,  0, 1);
    oy = clamp((e.clientY - ir.top)  / ir.height, 0, 1);
    dragging = true;
    e.preventDefault();
  });

  window.addEventListener('mousemove', function(e) {
    if (!dragging) return;
    const ir = imgRect();
    const cx = clamp((e.clientX - ir.left) / ir.width,  0, 1);
    const cy = clamp((e.clientY - ir.top)  / ir.height, 0, 1);
    region = {
      x: Math.min(ox, cx), y: Math.min(oy, cy),
      w: Math.abs(cx - ox), h: Math.abs(cy - oy),
    };
    updateSel(region);
  });

  window.addEventListener('mouseup', function() { dragging = false; });

  saveBtn.addEventListener('click', async function() {
    if (!region || region.w < 0.01 || region.h < 0.01) {
      showToast('Selection too small', false); return;
    }
    const r = await fetch('/api/photos/' + encodeURIComponent(entry.snapshot) + '/crop_region', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(region),
    });
    if (!r.ok) { showToast('Failed to save crop region', false); return; }
    entry.crop_region = region;
    showToast('Crop region saved');
    overlay.remove();
    loadPhotos();
  });

  cancelBtn.addEventListener('click', function() { overlay.remove(); });
  overlay.addEventListener('click', function(e) {
    if (e.target === overlay) overlay.remove();
  });

  document.body.appendChild(overlay);
}

async function applyCrop(entry) {
  showToast('Applying crop…');
  const r = await fetch('/api/photos/' + encodeURIComponent(entry.snapshot) + '/crop/apply',
    {method: 'POST'});
  const data = await r.json();
  if (data.ok) {
    entry.crop_applied = {path: data.path};
    showToast('Cropped → ' + data.path.split('/').pop());
    loadPhotos();
  } else {
    showToast('Crop failed: ' + (data.error || 'unknown'), false);
  }
}

async function addToQueue(snapshot) {
  const resp = await fetch('/api/upload/queue/add', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({snapshot, title: '', keywords: '', platforms: ['shutterstock', 'adobe_stock']})
  });
  if (!resp.ok) { showToast('Failed to add to queue', false); return; }
  showToast('Added to upload queue');
}
