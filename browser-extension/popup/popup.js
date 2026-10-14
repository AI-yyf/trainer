'use strict';

/**
 * Trainer Capture — popup.
 *
 * Shows the sidecar connection settings (address + workspace + optional
 * access token), the last five captures, and a shortcut to the Trainer host.
 */

const TrainerCapture = self.TrainerCapture;

const KIND_LABELS = {
  web: '网页',
  pdf: 'PDF',
  github_repo: 'GitHub 仓库'
};

const elements = {
  baseUrl: document.getElementById('base-url'),
  workspaceId: document.getElementById('workspace-id'),
  token: document.getElementById('sidecar-token'),
  save: document.getElementById('save-settings'),
  feedback: document.getElementById('settings-feedback'),
  status: document.getElementById('connection-status'),
  history: document.getElementById('history-list'),
  openTrainer: document.getElementById('open-trainer')
};

function setConnectionStatus(state, message) {
  elements.status.textContent = message;
  elements.status.classList.remove('status--pending', 'status--ok', 'status--error');
  elements.status.classList.add(`status--${state}`);
}

function setFeedback(message, isError) {
  elements.feedback.textContent = message;
  elements.feedback.classList.toggle('feedback--error', Boolean(isError));
}

async function refreshConnection(settings) {
  setConnectionStatus('pending', '检查连接…');
  const health = await TrainerCapture.checkSidecarHealth(settings);
  setConnectionStatus(health.connected ? 'ok' : 'error', health.message);
  return health;
}

function renderHistory(entries) {
  elements.history.textContent = '';
  if (!entries.length) {
    const empty = document.createElement('li');
    empty.className = 'history__empty';
    empty.textContent = '还没有采集记录。';
    elements.history.appendChild(empty);
    return;
  }

  for (const entry of entries) {
    const item = document.createElement('li');
    item.className = 'history__item';
    item.title = entry.url || '';

    const dot = document.createElement('span');
    dot.className = `history__dot history__dot--${entry.status === 'ok' ? 'ok' : 'failed'}`;
    dot.setAttribute('aria-hidden', 'true');

    const body = document.createElement('div');
    body.className = 'history__body';

    const title = document.createElement('span');
    title.className = 'history__title';
    const kindLabel = KIND_LABELS[entry.kind] || '来源';
    title.textContent = entry.title || entry.url || kindLabel;

    const meta = document.createElement('span');
    meta.className = 'history__meta';
    const time = TrainerCapture.formatTimestamp(entry.at);
    meta.textContent = [kindLabel, time].filter(Boolean).join(' · ');

    body.appendChild(title);
    body.appendChild(meta);
    item.appendChild(dot);
    item.appendChild(body);
    elements.history.appendChild(item);
  }
}

async function loadAndRender() {
  const settings = await TrainerCapture.loadSettings();
  elements.baseUrl.value = settings.baseUrl;
  elements.workspaceId.value = settings.workspaceId;
  elements.token.value = settings.token;
  renderHistory(await TrainerCapture.loadHistory());
  await refreshConnection(settings);
}

elements.save.addEventListener('click', () => {
  void (async () => {
    const saved = await TrainerCapture.saveSettings({
      baseUrl: elements.baseUrl.value,
      workspaceId: elements.workspaceId.value,
      token: elements.token.value
    });
    elements.baseUrl.value = saved.baseUrl;
    elements.workspaceId.value = saved.workspaceId;
    setFeedback('已保存', false);
    await refreshConnection(saved);
  })();
});

elements.openTrainer.addEventListener('click', () => {
  void (async () => {
    try {
      // Trainer's workbench lives inside VS Code; the OS protocol handler
      // brings the host application forward. Without a handler the browser
      // reports its own error.
      await chrome.tabs.create({ url: 'vscode://' });
    } catch (error) {
      setFeedback('无法唤起 VS Code，请手动打开 Trainer。', true);
    }
  })();
});

document.addEventListener('DOMContentLoaded', () => {
  void loadAndRender();
});
