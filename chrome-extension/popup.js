// BCI Lead Control — Popup Logic

const app = document.getElementById('app');
let state = { view: 'loading', status: null, providers: [], summary: {}, confirm: null, actionLoading: false };

// ── Render ──────────────────────────────────────────────────────
function render() {
  if (state.view === 'login') {
    app.innerHTML = `
      <div class="login-form">
        <h2>Sign in to ORBIT</h2>
        <input type="text" id="username" placeholder="Username" autocomplete="username" />
        <input type="password" id="password" placeholder="Password" autocomplete="current-password" />
        <button id="loginBtn">Sign In</button>
        <div id="loginError" class="login-error"></div>
      </div>
    `;
    document.getElementById('loginBtn').addEventListener('click', handleLogin);
    document.getElementById('password').addEventListener('keydown', e => { if (e.key === 'Enter') handleLogin(); });
    return;
  }

  if (state.view === 'loading') {
    app.innerHTML = `
      <div class="status-bar unknown">
        <span class="spinner"></span> Loading...
      </div>
    `;
    return;
  }

  const { status, providers, summary, confirm, actionLoading } = state;
  const allPaused = status === 'paused';
  const allActive = status === 'active';

  // Status bar
  const statusClass = allPaused ? 'paused' : allActive ? 'active' : 'mixed';
  const statusText = allPaused ? 'All Leads Paused' :
                     allActive ? `All ${summary.total || 0} Leads Active` :
                     `${summary.active || 0} Active · ${summary.paused || 0} Paused`;

  let html = `<div class="status-bar ${statusClass}"><div class="status-dot"></div>${statusText}</div>`;

  // Confirm overlay or big button
  if (confirm) {
    const isPause = confirm === 'pause';
    html += `
      <div class="confirm-overlay">
        <div class="confirm-text" style="color: ${isPause ? '#f87171' : '#4ade80'}">
          ${isPause ? '⏸ Pause' : '▶ Activate'} ALL ${summary.total || 0} lead providers?
        </div>
        <div class="confirm-btns">
          <button class="${isPause ? 'confirm-yes-pause' : 'confirm-yes-unpause'}" id="confirmYes">
            ${actionLoading ? '<span class="spinner"></span>' : (isPause ? 'Pause All' : 'Unpause All')}
          </button>
          <button class="confirm-cancel" id="confirmNo">Cancel</button>
        </div>
      </div>
    `;
  } else {
    if (allPaused) {
      html += `<button class="big-btn unpause-btn" id="mainBtn" ${actionLoading ? 'disabled' : ''}>
        ${actionLoading ? '<span class="spinner"></span>' : '▶'} Unpause All Leads
      </button>`;
    } else {
      html += `<button class="big-btn pause-btn" id="mainBtn" ${actionLoading ? 'disabled' : ''}>
        ${actionLoading ? '<span class="spinner"></span>' : '⏸'} Pause All Leads
      </button>`;
    }
  }

  // Provider list
  html += '<div class="providers">';
  for (const p of providers) {
    const pStatus = p.is_paused ? 'paused' : 'active';
    html += `
      <div class="provider">
        <span class="provider-emoji">${p.logo_emoji || '📋'}</span>
        <span class="provider-name">${p.name}</span>
        <span class="provider-status ${pStatus}">${pStatus}</span>
      </div>
    `;
  }
  html += '</div>';

  // Footer
  html += `
    <div class="footer">
      <button class="footer-link" id="refreshBtn">↻ Refresh</button>
      <a class="footer-link" href="https://better-choice-web.onrender.com/leads" target="_blank">Open ORBIT →</a>
      <button class="footer-link" id="logoutBtn">Sign out</button>
    </div>
  `;

  app.innerHTML = html;

  // Attach events
  const mainBtn = document.getElementById('mainBtn');
  if (mainBtn) {
    mainBtn.addEventListener('click', () => {
      state.confirm = allPaused ? 'unpause' : 'pause';
      render();
    });
  }

  const confirmYes = document.getElementById('confirmYes');
  if (confirmYes) {
    confirmYes.addEventListener('click', () => {
      if (state.actionLoading) return;
      state.actionLoading = true;
      render();
      const action = state.confirm === 'pause' ? 'pauseAll' : 'unpauseAll';
      chrome.runtime.sendMessage({ action }, (resp) => {
        state.actionLoading = false;
        state.confirm = null;
        if (resp && resp.error) {
          alert('Error: ' + resp.error);
        }
        loadStatus();
      });
    });
  }

  const confirmNo = document.getElementById('confirmNo');
  if (confirmNo) {
    confirmNo.addEventListener('click', () => {
      state.confirm = null;
      render();
    });
  }

  const refreshBtn = document.getElementById('refreshBtn');
  if (refreshBtn) refreshBtn.addEventListener('click', loadStatus);

  const logoutBtn = document.getElementById('logoutBtn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      chrome.runtime.sendMessage({ action: 'logout' }, () => {
        state.view = 'login';
        render();
      });
    });
  }
}

// ── Load status from background ─────────────────────────────────
function loadStatus() {
  chrome.runtime.sendMessage({ action: 'getStatus' }, (data) => {
    if (!data) {
      state.view = 'login';
    } else {
      const { providers, summary } = data;
      const allPaused = providers && providers.length > 0 && providers.every(p => p.is_paused);
      const allActive = providers && providers.length > 0 && providers.every(p => !p.is_paused);
      state.view = 'main';
      state.status = allPaused ? 'paused' : allActive ? 'active' : 'mixed';
      state.providers = providers || [];
      state.summary = summary || {};
    }
    render();
  });
}

// ── Login handler ───────────────────────────────────────────────
function handleLogin() {
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;
  const errorEl = document.getElementById('loginError');

  if (!username || !password) {
    errorEl.textContent = 'Enter username and password';
    return;
  }

  errorEl.textContent = 'Signing in...';
  chrome.runtime.sendMessage({ action: 'login', username, password }, (resp) => {
    if (resp && resp.error) {
      errorEl.textContent = resp.error;
    } else {
      loadStatus();
    }
  });
}

// ── Init ────────────────────────────────────────────────────────
chrome.storage.local.get('bci_token', (data) => {
  if (data.bci_token) {
    loadStatus();
  } else {
    state.view = 'login';
    render();
  }
});
