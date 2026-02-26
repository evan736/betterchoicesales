// BCI Lead Control — Background Service Worker
// Polls ORBIT every 15s for provider status, updates icon badge

const API = 'https://better-choice-api.onrender.com';
let cachedToken = null;
let lastStatus = null; // 'active' | 'paused' | 'mixed'

// ── Get stored auth token ───────────────────────────────────────
async function getToken() {
  if (cachedToken) return cachedToken;
  const data = await chrome.storage.local.get('bci_token');
  cachedToken = data.bci_token || null;
  return cachedToken;
}

// ── Fetch provider status from ORBIT ────────────────────────────
async function fetchStatus() {
  const token = await getToken();
  if (!token) {
    updateBadge('?', '#6b7280');
    return null;
  }

  try {
    const resp = await fetch(`${API}/api/lead-providers`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!resp.ok) {
      if (resp.status === 401) {
        cachedToken = null;
        await chrome.storage.local.remove('bci_token');
        updateBadge('!', '#ef4444');
      }
      return null;
    }
    const data = await resp.json();
    const summary = data.summary || {};
    const providers = data.providers || [];

    const allPaused = providers.length > 0 && providers.every(p => p.is_paused);
    const allActive = providers.length > 0 && providers.every(p => !p.is_paused);

    const status = allPaused ? 'paused' : allActive ? 'active' : 'mixed';

    if (status !== lastStatus) {
      lastStatus = status;
      if (status === 'paused') {
        updateBadge('⏸', '#ef4444');
        setIcon('paused');
      } else if (status === 'active') {
        updateBadge('', '#22c55e');
        setIcon('active');
      } else {
        updateBadge(String(summary.paused || 0), '#f59e0b');
        setIcon('mixed');
      }
    }

    return { status, summary, providers };
  } catch (e) {
    console.error('BCI status fetch error:', e);
    return null;
  }
}

// ── Update badge ────────────────────────────────────────────────
function updateBadge(text, color) {
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
}

function setIcon(status) {
  const prefix = status === 'paused' ? 'icon-paused' :
                 status === 'mixed' ? 'icon-mixed' : 'icon-active';
  chrome.action.setIcon({
    path: {
      16: `icons/${prefix}-16.png`,
      48: `icons/${prefix}-48.png`,
      128: `icons/${prefix}-128.png`,
    }
  }).catch(() => {});
}

// ── Pause / Unpause all ─────────────────────────────────────────
async function pauseAll() {
  const token = await getToken();
  if (!token) return { error: 'Not logged in' };

  try {
    const resp = await fetch(`${API}/api/lead-providers/pause-all`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    });
    const data = await resp.json();
    if (!resp.ok) return { error: data.detail || 'Failed' };
    lastStatus = null; // Force refresh
    await fetchStatus();
    return data;
  } catch (e) {
    return { error: e.message };
  }
}

async function unpauseAll() {
  const token = await getToken();
  if (!token) return { error: 'Not logged in' };

  try {
    const resp = await fetch(`${API}/api/lead-providers/unpause-all`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    });
    const data = await resp.json();
    if (!resp.ok) return { error: data.detail || 'Failed' };
    lastStatus = null;
    await fetchStatus();
    return data;
  } catch (e) {
    return { error: e.message };
  }
}

// ── Login ───────────────────────────────────────────────────────
async function login(username, password) {
  try {
    const resp = await fetch(`${API}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`
    });
    const data = await resp.json();
    if (!resp.ok) return { error: data.detail || 'Login failed' };
    cachedToken = data.access_token;
    await chrome.storage.local.set({ bci_token: data.access_token });
    lastStatus = null;
    await fetchStatus();
    return { success: true };
  } catch (e) {
    return { error: e.message };
  }
}

// ── Message handler (from popup) ────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'getStatus') {
    fetchStatus().then(data => sendResponse(data));
    return true;
  }
  if (msg.action === 'pauseAll') {
    pauseAll().then(data => sendResponse(data));
    return true;
  }
  if (msg.action === 'unpauseAll') {
    unpauseAll().then(data => sendResponse(data));
    return true;
  }
  if (msg.action === 'login') {
    login(msg.username, msg.password).then(data => sendResponse(data));
    return true;
  }
  if (msg.action === 'logout') {
    cachedToken = null;
    lastStatus = null;
    chrome.storage.local.remove('bci_token');
    updateBadge('?', '#6b7280');
    sendResponse({ success: true });
    return true;
  }
});

// ── Polling alarm ───────────────────────────────────────────────
chrome.alarms.create('statusPoll', { periodInMinutes: 0.25 }); // Every 15s
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'statusPoll') fetchStatus();
});

// ── Initial fetch on install/startup ────────────────────────────
chrome.runtime.onInstalled.addListener(() => fetchStatus());
chrome.runtime.onStartup.addListener(() => fetchStatus());
fetchStatus();
