// upload.js — split list+detail upload queue workflow
// All DOM text content set via textContent; no untrusted string goes into innerHTML.

let queueData = {mode: 'manual', queue: []};
let selectedQueueItem = null;

async function loadUploadQueue() {
  try {
    const r = await fetch('/api/upload/queue');
    if (!r.ok) throw new Error(r.status);
    queueData = await r.json();
  } catch (err) {
    showToast('Failed to load queue', false);
    return;
  }
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
  if (s === 'uploaded')  return '#2a7';
  if (s === 'error')     return '#c33';
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
  const r = await fetch('/api/upload/queue/mode', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mode})
  });
  if (!r.ok) { showToast('Failed to set mode', false); return; }
  queueData.mode = mode;
}

async function removeFromQueue(snapshot) {
  const r = await fetch('/api/upload/queue/' + encodeURIComponent(snapshot), {method: 'DELETE'});
  if (!r.ok) { showToast('Failed to remove', false); return; }
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
