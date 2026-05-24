// timelapse.js — timelapse build + browse tab
// HTML structure lives in command_center.html; this file wires events and loads data.

const FRAME_DUR = 0.12; // seconds per frame (~8 fps)

let _tlInited = false;
let _tlMode = 'golden';
let _tlBuilding = false;
const _tlSelected = new Map(); // video filename -> entry

function loadTimelapse() {
  if (!_tlInited) {
    _tlWireEvents();
    const today = new Date().toISOString().slice(0, 10);
    document.getElementById('tl-gh-date').value = today;
    document.getElementById('tl-fd-date').value = today;
    _tlInited = true;
  }
  _tlLoadList();
  _tlRecalc();
}

function _tlWireEvents() {
  document.querySelectorAll('.tl-mode-btn').forEach(function(b) {
    b.addEventListener('click', function() { _tlSetMode(b.dataset.mode); _tlRecalc(); });
  });
  document.querySelectorAll('input[name="tl-timing"]').forEach(function(r) {
    r.addEventListener('change', _tlTimingMode);
  });
  ['tl-interval', 'tl-duration', 'tl-gh-date', 'tl-fd-date', 'tl-cr-start', 'tl-cr-end'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('input', _tlRecalc);
  });
  document.getElementById('tl-build-btn').addEventListener('click', buildTimelapse);
  document.getElementById('tl-rebuild-btn').addEventListener('click', _tlRebuildSelected);
  document.getElementById('tl-del-btn').addEventListener('click', _tlDeleteSelected);
}

function _tlSetMode(mode) {
  _tlMode = mode;
  document.querySelectorAll('.tl-mode-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.mode === mode);
  });
  document.getElementById('tl-form-golden').style.display  = mode === 'golden'  ? '' : 'none';
  document.getElementById('tl-form-fullday').style.display = mode === 'fullday' ? '' : 'none';
  document.getElementById('tl-form-custom').style.display  = mode === 'custom'  ? '' : 'none';
}

function _tlTimingMode() {
  var isInterval = document.querySelector('input[name="tl-timing"]:checked').value === 'interval';
  document.getElementById('tl-interval-row').style.display = isInterval ? '' : 'none';
  document.getElementById('tl-duration-row').style.display = isInterval ? 'none' : '';
  _tlRecalc();
}

function _tlWindowSecs() {
  if (_tlMode === 'golden')  return 3600;
  if (_tlMode === 'fullday') return 54000;
  var s = document.getElementById('tl-cr-start').value;
  var e = document.getElementById('tl-cr-end').value;
  if (!s || !e) return 54000;
  return Math.max(60, (new Date(e) - new Date(s)) / 1000);
}

function _tlFmtSecs(s) {
  var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.round(s % 60);
  if (h > 0) return h + 'h ' + m + 'm';
  if (m > 0) return m + 'm ' + sec + 's';
  return sec + 's';
}

function _tlRecalc() {
  var wSecs = _tlWindowSecs();
  var checked = document.querySelector('input[name="tl-timing"]:checked');
  var isInterval = checked && checked.value === 'interval';
  var estDur = document.getElementById('tl-est-dur');
  var estIv  = document.getElementById('tl-est-iv');
  if (isInterval) {
    var iv = parseFloat(document.getElementById('tl-interval').value) || 10;
    var frames = Math.round(wSecs / iv);
    if (estDur) estDur.textContent = '→ ~' + frames + ' frames, video ~' + _tlFmtSecs(frames * FRAME_DUR);
  } else {
    var dur = (parseFloat(document.getElementById('tl-duration').value) || 5) * 60;
    var iv2 = (wSecs / (dur / FRAME_DUR)).toFixed(1);
    if (estIv) estIv.textContent = '→ 1 frame every ' + iv2 + 's';
  }
}

async function buildTimelapse() {
  var checked = document.querySelector('input[name="tl-timing"]:checked');
  var isInterval = checked && checked.value === 'interval';
  var intervalSecs;
  if (isInterval) {
    intervalSecs = parseFloat(document.getElementById('tl-interval').value) || 10;
  } else {
    var dur = (parseFloat(document.getElementById('tl-duration').value) || 5) * 60;
    intervalSecs = Math.max(1, _tlWindowSecs() / (dur / FRAME_DUR));
  }

  var body = {mode: _tlMode, interval_secs: Math.round(intervalSecs)};
  if (_tlMode === 'golden') {
    body.date = document.getElementById('tl-gh-date').value;
    body.type = document.getElementById('tl-gh-type').value;
  } else if (_tlMode === 'fullday') {
    body.date = document.getElementById('tl-fd-date').value;
  } else {
    body.start = document.getElementById('tl-cr-start').value;
    body.end   = document.getElementById('tl-cr-end').value;
    body.label = document.getElementById('tl-cr-label').value || 'custom';
  }

  var r = await fetch('/api/timelapse/build', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  var j = await r.json();
  if (j.error) { showToast('Error: ' + j.error, false); return; }
  if (j.position > 1) showToast('Queued — position ' + j.position);
  _tlBuilding = true;
  var pw = document.getElementById('tl-prog-wrap');
  if (pw) pw.style.display = '';
  _tlPoll();
}

function _tlPoll() {
  setTimeout(async function() {
    var r = await fetch('/api/timelapse/status');
    var j = await r.json();
    var st  = document.getElementById('tl-build-status');
    var bar = document.getElementById('tl-prog-bar');
    var qs  = j.queued > 0 ? ' \xb7 ' + j.queued + ' queued' : '';

    if (j.state === 'running') {
      var pct = j.frames_total > 0 ? Math.round(j.frames_done / j.frames_total * 100) : 0;
      if (bar) bar.style.width = pct + '%';
      if (st)  st.textContent  = j.stage + '… ' + j.frames_done + '/' + j.frames_total + ' frames' + qs;
      _tlPoll();
    } else if (j.queued > 0) {
      if (bar) bar.style.width = '0%';
      if (st)  st.textContent  = 'Waiting…' + qs;
      if (j.state === 'done') { _tlLoadList(); showToast('Timelapse built!'); }
      _tlPoll();
    } else {
      _tlBuilding = false;
      var pw = document.getElementById('tl-prog-wrap');
      if (pw) pw.style.display = 'none';
      if (bar) bar.style.width = '0%';
      if (st)  st.textContent  = j.state === 'done' ? 'Done!' : (j.error ? 'Error: ' + j.error : '');
      if (j.state === 'done') { _tlLoadList(); showToast('Timelapse built!'); }
    }
  }, 1500);
}

function _tlUpdateButtons() {
  var n   = _tlSelected.size;
  var sc  = document.getElementById('tl-sel-count');
  var rb  = document.getElementById('tl-rebuild-btn');
  var del = document.getElementById('tl-del-btn');
  if (sc)  sc.textContent    = n;
  if (rb)  rb.style.display  = n > 0 ? '' : 'none';
  if (del) del.style.display = n > 0 ? '' : 'none';

  if (n === 1) {
    var e = _tlSelected.values().next().value;
    var type = (e.type || '').toLowerCase();
    if (type === 'sunrise' || type === 'sunset') {
      _tlSetMode('golden');
      var d = document.getElementById('tl-gh-date'), t = document.getElementById('tl-gh-type');
      if (d) d.value = e.date || '';
      if (t) t.value = type;
    } else if (type === 'fullday') {
      _tlSetMode('fullday');
      var fd = document.getElementById('tl-fd-date');
      if (fd) fd.value = e.date || '';
    } else {
      _tlSetMode('custom');
      var cs = document.getElementById('tl-cr-start'), ce = document.getElementById('tl-cr-end');
      var cl = document.getElementById('tl-cr-label');
      if (cs && e.start) cs.value = e.start.slice(0, 16);
      if (ce && e.end)   ce.value = e.end.slice(0, 16);
      if (cl) cl.value = e.label || '';
    }
    _tlRecalc();
  }
}

async function _tlLoadList() {
  var r = await fetch('/api/timelapses');
  var j = await r.json();
  var list = document.getElementById('tl-list');
  if (!list) return;
  while (list.firstChild) list.removeChild(list.firstChild);
  _tlSelected.clear();
  _tlUpdateButtons();

  (j.entries || []).forEach(function(e) {
    var card = document.createElement('div');
    card.className = 'tl-card';
    card.addEventListener('click', function() {
      if (_tlSelected.has(e.video)) {
        _tlSelected.delete(e.video); card.classList.remove('tl-selected');
      } else {
        _tlSelected.set(e.video, e); card.classList.add('tl-selected');
      }
      _tlUpdateButtons();
    });

    var img = document.createElement('img');
    img.src = e.thumbnail ? '/thumb/' + encodeURIComponent(e.thumbnail) : '';
    img.alt = '';

    var play = document.createElement('button');
    play.className = 'tl-card-play';
    play.title = 'Watch';
    play.textContent = '▶';
    play.addEventListener('click', function(ev) {
      ev.stopPropagation();
      window.open('/timelapse/' + encodeURIComponent(e.video), '_blank');
    });

    var info = document.createElement('div');
    info.className = 'tl-card-info';
    var title = document.createElement('strong');
    title.textContent = (e.date || '') + ' ' + (e.type || e.label || '');
    var detail = document.createElement('span');
    detail.textContent = '\n' + (e.frame_count || 0) + ' frames \xb7 ~' + _tlFmtSecs((e.frame_count || 0) * FRAME_DUR);
    info.append(title, detail);
    card.append(img, play, info);
    list.appendChild(card);
  });
}

async function _tlRebuildSelected() {
  if (_tlSelected.size === 0) return;
  var queued = 0;
  for (var e of _tlSelected.values()) {
    var body = {mode: 'custom', interval_secs: 10};
    if (e.start) body.start = e.start.slice(0, 16);
    if (e.end)   body.end   = e.end.slice(0, 16);
    body.label = e.label || e.type || 'rebuild';
    var r = await fetch('/api/timelapse/build', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    var j = await r.json();
    if (!j.error) queued++;
  }
  showToast('Queued ' + queued + ' rebuild(s).');
  _tlBuilding = true;
  var pw = document.getElementById('tl-prog-wrap');
  if (pw) pw.style.display = '';
  _tlPoll();
}

async function _tlDeleteSelected() {
  if (_tlSelected.size === 0) return;
  if (!confirm('Delete ' + _tlSelected.size + ' timelapse(s)?\n\nThis cannot be undone.')) return;
  var deleted = 0;
  for (var video of _tlSelected.keys()) {
    var r = await fetch('/api/timelapse/delete', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({video: video}),
    });
    var j = await r.json();
    if (!j.error) deleted++;
  }
  showToast('Deleted ' + deleted + '.');
  _tlLoadList();
}
