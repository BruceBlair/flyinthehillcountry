// status.js — service health + pipeline tab
// HTML structure lives in command_center.html; this file wires events and fetches data.

let _statusInited = false;

function loadStatus() {
  if (!_statusInited) {
    document.getElementById('st-run-btn').addEventListener('click', _stRunPipeline);
    document.getElementById('st-refresh-btn').addEventListener('click', _stRefresh);
    _statusInited = true;
  }
  _stRefresh();
}

async function _stRefresh() {
  var st = document.getElementById('st-pipe-status');
  if (st) st.textContent = '';

  var statusResp = fetch('/api/status');
  var logResp    = fetch('/api/pipeline/log');

  var data = await (await statusResp).json();
  var log  = await (await logResp).text();

  _stRenderServices(data.services  || {});
  _stRenderManifest(data.manifest  || {});
  _stRenderDisk(data.disk          || {});

  var lb = document.getElementById('st-log-box');
  if (lb) {
    lb.textContent = log;
    lb.scrollTop   = lb.scrollHeight;
  }
}

function _stRenderServices(services) {
  var grid = document.getElementById('st-service-grid');
  if (!grid) return;
  while (grid.firstChild) grid.removeChild(grid.firstChild);

  var labels = {mosquitto: 'MQTT', influxdb: 'InfluxDB', grafana: 'Grafana', frigate: 'Frigate'};
  Object.entries(services).forEach(function(pair) {
    var name = pair[0], ok = pair[1];
    var card = document.createElement('div');
    card.className = 'st-service-card';

    var dot = document.createElement('span');
    dot.className = 'dot ' + (ok ? 'dot-green' : 'dot-red');
    dot.title = ok ? 'Reachable' : 'Unreachable';

    var lbl = document.createElement('span');
    lbl.textContent = labels[name] || name;

    card.append(dot, lbl);
    grid.appendChild(card);
  });
}

function _stRenderManifest(manifest) {
  var el = document.getElementById('st-manifest-content');
  if (!el) return;
  while (el.firstChild) el.removeChild(el.firstChild);

  var row = document.createElement('div');
  row.style.cssText = 'display:flex;gap:20px;flex-wrap:wrap;margin-bottom:8px;align-items:baseline';

  var total = document.createElement('span');
  total.style.cssText = 'font-size:22px;font-weight:600;color:#eee';
  total.textContent = (manifest.total || 0) + ' photos';
  row.appendChild(total);

  var flagged = manifest.flagged || {};
  Object.entries(flagged).forEach(function(pair) {
    var key = pair[0], n = pair[1];
    if (!n) return;
    var chip = document.createElement('span');
    chip.style.cssText = 'font-size:12px;color:#888';
    chip.textContent = key.replace('_', ' ') + ': ' + n;
    row.appendChild(chip);
  });
  el.appendChild(row);

  var cats = document.createElement('div');
  cats.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap';
  Object.entries(manifest.by_category || {}).sort().forEach(function(pair) {
    var cat = pair[0], n = pair[1];
    var tag = document.createElement('span');
    tag.className = 'st-cat-tag';
    tag.textContent = cat + ' ' + n;
    cats.appendChild(tag);
  });
  el.appendChild(cats);
}

function _stRenderDisk(disk) {
  var el = document.getElementById('st-disk-content');
  if (!el) return;
  while (el.firstChild) el.removeChild(el.firstChild);

  var labels = {highlights: 'Highlights (/volume1/highlights)', stock_ready: 'Stock Ready'};
  Object.entries(disk).forEach(function(pair) {
    var name = pair[0], info = pair[1];
    if (!info) return;

    var row = document.createElement('div');
    row.style.marginBottom = '10px';

    var meta = document.createElement('div');
    meta.style.cssText = 'display:flex;justify-content:space-between;font-size:12px;color:#888;margin-bottom:4px';
    var metaLeft = document.createElement('span');
    metaLeft.textContent = labels[name] || name;
    var metaRight = document.createElement('span');
    metaRight.textContent = info.used_gb + ' / ' + info.total_gb + ' GB  (' + info.pct + '%)';
    meta.append(metaLeft, metaRight);

    var track = document.createElement('div');
    track.style.cssText = 'height:6px;background:#1e1e1e;border-radius:3px;overflow:hidden';
    var fill = document.createElement('div');
    fill.style.cssText = 'height:100%;border-radius:3px;transition:width .3s';
    fill.style.width      = Math.min(100, info.pct) + '%';
    fill.style.background = info.pct > 85 ? '#c33' : info.pct > 70 ? '#fa0' : '#2a7';
    track.appendChild(fill);

    row.append(meta, track);
    el.appendChild(row);
  });
}

async function _stRunPipeline() {
  var st = document.getElementById('st-pipe-status');
  if (st) st.textContent = 'Starting…';
  await fetch('/api/pipeline/run', {method: 'POST'});
  if (st) st.textContent = 'Running in background…';
  setTimeout(_stRefresh, 3000);
}
