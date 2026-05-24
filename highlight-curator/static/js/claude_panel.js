// claude_panel.js — Claude assistant panel
// Sends messages to /api/claude with conversation history.
// System context (manifest stats, queue, platforms) is injected server-side.

let claudeHistory = [];

document.getElementById('claude-send').addEventListener('click', sendClaude);
document.getElementById('claude-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendClaude(); }
});

async function sendClaude() {
  const input = document.getElementById('claude-input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  input.disabled = true;

  appendClaudeMsg('user', msg);
  claudeHistory.push({role: 'user', content: msg});

  const indicator = appendClaudeMsg('ai', '…');

  try {
    const r = await fetch('/api/claude', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg, history: claudeHistory.slice(-12)}),
    });
    const data = await r.json();
    indicator.remove();
    if (data.reply) {
      appendClaudeMsg('ai', data.reply);
      claudeHistory.push({role: 'assistant', content: data.reply});
    } else {
      appendClaudeMsg('ai', 'Error: ' + (data.error || 'unknown'));
    }
  } catch (_) {
    indicator.remove();
    appendClaudeMsg('ai', 'Connection error — is content_manager running?');
  } finally {
    input.disabled = false;
    input.focus();
  }
}

function appendClaudeMsg(role, text) {
  const msgs = document.getElementById('claude-messages');
  const el = document.createElement('div');
  el.className = role === 'user' ? 'msg-user' : 'msg-ai';
  el.textContent = text;
  msgs.appendChild(el);
  msgs.scrollTop = msgs.scrollHeight;
  return el;
}

// Seed a greeting when the panel first opens
document.getElementById('claude-toggle').addEventListener('click', function() {
  const msgs = document.getElementById('claude-messages');
  if (msgs.childElementCount === 0) {
    appendClaudeMsg('ai', 'Hi! Ask me about your photo library, upload queue, or platform status.');
  }
});
