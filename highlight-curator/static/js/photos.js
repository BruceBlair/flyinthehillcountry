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
