// platforms.js — platform credentials config UI
// loadPlatforms() is called by switchTab('platforms') in command_center.html

const PLATFORM_DEFS = [
  {
    id: 'shutterstock',
    name: 'Shutterstock',
    fields: [
      {key: 'client_id',     label: 'Client ID',     type: 'text'},
      {key: 'client_secret', label: 'Client Secret', type: 'password'},
      {key: 'access_token',  label: 'Access Token',  type: 'password'},
    ],
  },
  {
    id: 'adobe_stock',
    name: 'Adobe Stock',
    fields: [
      {key: 'api_key', label: 'API Key', type: 'password'},
    ],
  },
  {
    id: 'anthropic',
    name: 'Claude (Anthropic)',
    fields: [
      {key: 'api_key', label: 'API Key', type: 'password'},
    ],
  },
];

async function loadPlatforms() {
  const tab = document.getElementById('tab-platforms');
  while (tab.firstChild) tab.removeChild(tab.firstChild);

  let status = {};
  try {
    const r = await fetch('/api/platforms/status');
    if (!r.ok) throw new Error(r.status);
    status = await r.json();
  } catch (_) {
    showToast('Failed to load platform status', false);
  }

  const heading = document.createElement('h2');
  heading.style.cssText = 'font-size:15px;margin-bottom:16px;color:#aaa';
  heading.textContent = 'Sales Platforms';
  tab.appendChild(heading);

  for (const def of PLATFORM_DEFS) {
    tab.appendChild(makePlatformCard(def, status[def.id] || {}));
  }
  tab.appendChild(makeLocalStub());
}

function dotClass(s) {
  if (s.has_token)  return 'dot-green';
  if (s.configured) return 'dot-amber';
  return 'dot-red';
}

function dotTitle(s) {
  if (s.has_token)  return 'Connected';
  if (s.configured) return 'Credentials saved — no access token';
  return 'Not configured';
}

function makePlatformCard(def, status) {
  const card = document.createElement('div');
  card.className = 'platform-card';

  const h3 = document.createElement('h3');
  const dot = document.createElement('span');
  dot.className = 'dot ' + dotClass(status);
  dot.title = dotTitle(status);
  h3.appendChild(dot);
  h3.appendChild(document.createTextNode(def.name));
  card.appendChild(h3);

  const form = document.createElement('div');
  form.style.cssText = 'display:flex;flex-direction:column;gap:8px;max-width:360px';

  for (const f of def.fields) {
    const wrap = document.createElement('div');
    const lbl = document.createElement('div');
    lbl.className = 'field-label';
    lbl.textContent = f.label;
    const inp = document.createElement('input');
    inp.className = 'field-input';
    inp.type = f.type;
    inp.id = 'creds-' + def.id + '-' + f.key;
    inp.placeholder = f.type === 'password' ? '••••••••' : '';
    inp.autocomplete = 'off';
    wrap.appendChild(lbl);
    wrap.appendChild(inp);
    form.appendChild(wrap);
  }

  const saveBtn = document.createElement('button');
  saveBtn.className = 'ok';
  saveBtn.style.cssText = 'margin-top:4px;align-self:flex-start';
  saveBtn.textContent = 'Save';
  saveBtn.addEventListener('click', function() { savePlatformCreds(def); });
  form.appendChild(saveBtn);

  card.appendChild(form);
  return card;
}

function makeLocalStub() {
  const card = document.createElement('div');
  card.className = 'platform-card';
  card.style.opacity = '0.4';
  const h3 = document.createElement('h3');
  const dot = document.createElement('span');
  dot.className = 'dot dot-grey';
  h3.appendChild(dot);
  h3.appendChild(document.createTextNode('Local Storefront'));
  card.appendChild(h3);
  const note = document.createElement('p');
  note.style.cssText = 'font-size:12px;color:#555';
  note.textContent = 'Coming soon';
  card.appendChild(note);
  return card;
}

async function savePlatformCreds(def) {
  const payload = {platform: def.id};
  for (const f of def.fields) {
    const inp = document.getElementById('creds-' + def.id + '-' + f.key);
    if (inp && inp.value.trim()) payload[f.key] = inp.value.trim();
  }
  const r = await fetch('/api/platforms/credentials', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  if (!r.ok) { showToast('Failed to save credentials', false); return; }
  showToast('Credentials saved');
  for (const f of def.fields) {
    if (f.type === 'password') {
      const inp = document.getElementById('creds-' + def.id + '-' + f.key);
      if (inp) inp.value = '';
    }
  }
  loadPlatforms();
}
