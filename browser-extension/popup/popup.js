'use strict';

/**
 * Trainer Capture — popup.
 *
 * Three states (task 三), all reachable without Trainer running:
 *   1. unpaired — auto-discovers the local sidecar (default port + managed
 *      range) and asks for the 6-digit pairing code copied from VS Code;
 *   2. paired, Trainer not running — an explicit "Trainer is not running" card
 *      plus the full offline queue manager (list, delete one, clear, retry
 *      now); capturing and downloading keep working and queue locally;
 *   3. connected — the workspace label and the last captures with deep links
 *      into the Trainer library.
 *
 * Copy follows the browser locale (zh-CN, en-US, es-ES, fr-FR, de-DE, ja-JP,
 * ko-KR, pt-BR — with English as the fallback). Motion is explanatory only and
 * yields to prefers-reduced-motion via the stylesheet.
 */

const TrainerCapture = self.TrainerCapture;

const elements = {
  statusDot: document.getElementById('status-dot'),
  statusLine: document.getElementById('status-line'),
  queueChip: document.getElementById('queue-chip'),
  queueChipCount: document.getElementById('queue-chip-count'),
  pairPanel: document.getElementById('pair-panel'),
  detectLine: document.getElementById('detect-line'),
  pairCode: document.getElementById('pair-code'),
  pairSubmit: document.getElementById('pair-submit'),
  detectAgain: document.getElementById('detect-again'),
  pairFeedback: document.getElementById('pair-feedback'),
  offlinePanel: document.getElementById('offline-panel'),
  connectedPanel: document.getElementById('connected-panel'),
  workspaceName: document.getElementById('workspace-name'),
  capturePanel: document.getElementById('capture-panel'),
  pageLine: document.getElementById('page-line'),
  focusSelect: document.getElementById('focus-select'),
  capturePage: document.getElementById('capture-page'),
  captureResult: document.getElementById('capture-result'),
  downloadBlock: document.getElementById('download-block'),
  targetDir: document.getElementById('target-dir'),
  captureDownload: document.getElementById('capture-download'),
  downloadFeedback: document.getElementById('download-feedback'),
  queuePanel: document.getElementById('queue-panel'),
  queueCount: document.getElementById('queue-count'),
  queueList: document.getElementById('queue-list'),
  queueEmpty: document.getElementById('queue-empty'),
  queueRetry: document.getElementById('queue-retry'),
  queueClear: document.getElementById('queue-clear'),
  queueFeedback: document.getElementById('queue-feedback'),
  historyPanel: document.getElementById('history-panel'),
  history: document.getElementById('history-list'),
  revoke: document.getElementById('revoke'),
  repair: document.getElementById('repair'),
  openTrainer: document.getElementById('open-trainer'),
  notice: document.getElementById('notice'),
  close: document.getElementById('popup-close')
};

const copy = TrainerCapture.copyFor(TrainerCapture.browserLocale());
let detectedBaseUrl = '';
let detectedBaseUrls = [];
let currentTab = { url: '', title: '', kind: 'web' };
let lastQueueCount = -1;
let lastTabUrl = '';

function t(key, values) {
  return TrainerCapture.formatCopy(copy[key] || '', values);
}

function applyCopy() {
  document.documentElement.lang = TrainerCapture.resolveLanguageTag(TrainerCapture.browserLocale());
  document.title = t('appTitle');
  for (const node of document.querySelectorAll('[data-copy]')) {
    node.textContent = t(node.getAttribute('data-copy'));
  }
  for (const node of document.querySelectorAll('[data-copy-placeholder]')) {
    node.setAttribute('placeholder', t(node.getAttribute('data-copy-placeholder')));
  }
  // Icon-only controls keep their words in tooltips/accessible names, so the
  // window stays visual instead of wordy.
  for (const node of document.querySelectorAll('[data-copy-title]')) {
    node.setAttribute('title', t(node.getAttribute('data-copy-title')));
  }
  for (const node of document.querySelectorAll('[data-copy-label]')) {
    const label = t(node.getAttribute('data-copy-label'));
    node.setAttribute('aria-label', label);
    node.setAttribute('title', label);
  }
}

function send(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      const error = chrome.runtime.lastError;
      if (error) {
        resolve({ ok: false, status: 'failed', message: String(error.message || '') });
        return;
      }
      resolve(response || {});
    });
  });
}

// ------------------------------------------------------------------ motion --

/** Replay the reveal animation for a panel that just became visible. */
function revealPanel(element) {
  if (!element) {
    return;
  }
  element.classList.remove('panel--reveal');
  // Reading offsetWidth restarts the CSS animation on the next paint.
  void element.offsetWidth;
  element.classList.add('panel--reveal');
  // Move focus only when the previously focused control actually sat inside
  // a panel that just became hidden (for example #pair-submit after pairing
  // succeeds). On popup open every panel is revealed from `hidden` — focusing
  // each would cascade to the last panel instead of the primary action.
  const previous = document.activeElement;
  const previousPanel = previous instanceof HTMLElement ? previous.closest('.panel') : null;
  if (previousPanel && previousPanel.hidden) {
    element.setAttribute('tabindex', '-1');
    element.focus({ preventScroll: true });
  }
}

function bump(element) {
  if (!element) {
    return;
  }
  element.classList.remove('count--bump', 'chip--bump');
  void element.offsetWidth;
  element.classList.add(element === elements.queueChip ? 'chip--bump' : 'count--bump');
}

/** One restrained shake for an error that needs attention. */
function shake(element) {
  if (!element) {
    return;
  }
  element.classList.remove('feedback--shake');
  void element.offsetWidth;
  element.classList.add('feedback--shake');
}

/** Draw the success check once, then fade back into the feedback row. */
function drawSuccessCheck() {
  const holder = elements.captureResult;
  if (!holder) {
    return;
  }
  let node = holder.querySelector('.capture-check');
  if (!node) {
    node = document.createElement('span');
    node.className = 'capture-check';
    node.innerHTML =
      '<svg class="icon" aria-hidden="true"><use href="#icon-check"></use></svg>';
    holder.prepend(node);
  }
  node.classList.remove('is-drawn');
  void node.offsetWidth;
  node.classList.add('is-drawn');
  window.setTimeout(() => {
    node.classList.remove('is-drawn');
  }, 900);
}

// ------------------------------------------------------------------ status --

function setStatus(tone, message) {
  elements.statusLine.textContent = message;
  elements.statusDot.classList.remove(
    'status__dot--pending',
    'status__dot--ok',
    'status__dot--warn',
    'status__dot--error'
  );
  elements.statusDot.classList.add(`status__dot--${tone}`);
}

function setFeedback(node, message, tone) {
  node.hidden = false;
  node.textContent = message || '';
  node.classList.remove('feedback--error', 'feedback--warn');
  if (tone === 'error') {
    node.classList.add('feedback--error');
  } else if (tone === 'warn') {
    node.classList.add('feedback--warn');
  }
  if (tone === 'error') {
    shake(node);
  }
}

// ------------------------------------------------------------------ render --

function renderFocusOptions(state) {
  elements.focusSelect.textContent = '';
  const none = document.createElement('option');
  none.value = '';
  none.textContent = t('bindingNone');
  elements.focusSelect.appendChild(none);
  for (const option of state.focusOptions || []) {
    const item = document.createElement('option');
    item.value = option.id;
    item.textContent = option.label;
    elements.focusSelect.appendChild(item);
  }
  const known = (state.focusOptions || []).some((option) => option.id === state.focusId);
  elements.focusSelect.value = known ? state.focusId : '';
}

function kindIconId(kind) {
  if (kind === 'pdf') {
    return 'icon-file-pdf';
  }
  if (kind === 'github_repo') {
    return 'icon-git-branch';
  }
  return 'icon-file-text';
}

function queueMetaText(entry) {
  const parts = [t(TrainerCapture.kindCopyKey(entry.kind))];
  const time = TrainerCapture.formatTimestamp(entry.createdAt);
  if (time) {
    parts.push(time);
  }
  if (entry.download === true) {
    parts.push(entry.targetDir || TrainerCapture.DEFAULT_TARGET_DIR);
  }
  const attempts = Number(entry.attempts) || 0;
  if (attempts > 0) {
    parts.push(t('queueAttempts', { count: attempts }));
  }
  return parts.join(' · ');
}

function renderQueue(state) {
  const queue = Array.isArray(state.queue) ? state.queue : [];
  // The count slot is a number, not a sentence; the empty state lives in its
  // own line so the header stays icon-and-number quiet.
  elements.queueCount.textContent = queue.length ? String(queue.length) : '';
  elements.queueCount.hidden = queue.length === 0;

  elements.queueList.textContent = '';
  elements.queueEmpty.hidden = queue.length > 0;

  for (const entry of queue) {
    const item = document.createElement('li');
    item.className = 'queue__item';

    const icon = document.createElement('span');
    icon.className = 'queue__icon';
    icon.innerHTML = `<svg class="icon icon--xs" aria-hidden="true"><use href="#${kindIconId(
      entry.kind
    )}"></use></svg>`;

    const body = document.createElement('div');
    body.className = 'queue__body';
    const title = document.createElement('span');
    title.className = 'queue__title';
    title.textContent = entry.title || entry.url || t('kindUnknown');
    title.title = entry.url || '';
    const meta = document.createElement('span');
    meta.className = 'queue__meta';
    meta.textContent = queueMetaText(entry);
    body.appendChild(title);
    body.appendChild(meta);

    const remove = document.createElement('button');
    remove.className = 'queue__remove';
    remove.type = 'button';
    remove.title = t('queueDeleteTitle', { title: title.textContent });
    remove.setAttribute('aria-label', remove.title);
    remove.innerHTML = '<svg class="icon icon--xs" aria-hidden="true"><use href="#icon-trash"></use></svg>';
    remove.addEventListener('click', () => {
      void removeQueueEntry(entry.clientCaptureId);
    });

    item.appendChild(icon);
    item.appendChild(body);
    item.appendChild(remove);
    elements.queueList.appendChild(item);
  }

  const count = queue.length;
  if (count !== lastQueueCount) {
    if (lastQueueCount >= 0) {
      bump(elements.queueCount);
      bump(elements.queueChip);
    }
    lastQueueCount = count;
  }
  elements.queueChipCount.textContent = String(count);
  elements.queueChip.hidden = count === 0;
  elements.queueRetry.disabled = count === 0;
  elements.queueClear.disabled = count === 0;
}

function renderHistory(entries) {
  elements.history.textContent = '';
  if (!entries.length) {
    const empty = document.createElement('li');
    empty.className = 'history__empty';
    empty.textContent = t('historyEmpty');
    elements.history.appendChild(empty);
    return;
  }

  for (const entry of entries) {
    const item = document.createElement('li');
    item.className = 'history__item';
    item.title = entry.url || '';

    const success = entry.status === 'ok' || entry.status === 'duplicated';
    const dot = document.createElement('span');
    dot.className =
      entry.status === 'queued'
        ? 'history__dot history__dot--queued'
        : `history__dot history__dot--${success ? 'ok' : 'failed'}`;
    dot.setAttribute('aria-hidden', 'true');

    const body = document.createElement('div');
    body.className = 'history__body';

    const title = document.createElement('span');
    title.className = 'history__title';
    title.textContent = entry.title || entry.url || t('kindUnknown');

    const meta = document.createElement('span');
    meta.className = 'history__meta';
    const isDownload = entry.download === true;
    const kindLabel = t(isDownload ? 'downloadHeading' : TrainerCapture.kindCopyKey(entry.kind));
    const statusLabel = t(TrainerCapture.statusCopyKey(entry.status));
    const time = TrainerCapture.formatTimestamp(entry.at);
    meta.textContent = [kindLabel, statusLabel, time].filter(Boolean).join(' · ');

    body.appendChild(title);
    body.appendChild(meta);

    const savedPath = TrainerCapture.historySavedPath(entry);
    if (isDownload && savedPath) {
      const saved = document.createElement('span');
      saved.className = 'history__saved';
      saved.textContent = t('savedPathLabel', { path: savedPath });
      saved.title = savedPath;
      body.appendChild(saved);
    }

    const deepLink = entry.deepLink || TrainerCapture.buildDeepLink(entry.resourceId);
    if (deepLink) {
      const links = document.createElement('span');
      links.className = 'history__links';
      const link = document.createElement('a');
      link.className = 'history__link';
      link.href = '#';
      link.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#icon-external"></use></svg>';
      const linkLabel = document.createElement('span');
      linkLabel.textContent = t(isDownload ? 'openInVsCode' : 'openInTrainer');
      link.appendChild(linkLabel);
      link.addEventListener('click', (event) => {
        event.preventDefault();
        void send({ type: 'trainer:open', url: deepLink });
      });
      links.appendChild(link);
      body.appendChild(links);
    }

    item.appendChild(dot);
    item.appendChild(body);
    elements.history.appendChild(item);
  }
}

function renderState(state) {
  const paired = Boolean(state && state.paired);
  const offline = paired && state.offline === true;
  const connected = paired && state.connected === true;
  const queueCount = Number(state && state.queueCount) || 0;

  const visible = {
    pair: !paired,
    offline: offline,
    connected: connected,
    capture: paired,
    queue: paired && (offline || queueCount > 0),
    history: paired
  };
  const panels = [
    ['pairPanel', visible.pair],
    ['offlinePanel', visible.offline],
    ['connectedPanel', visible.connected],
    ['capturePanel', visible.capture],
    ['queuePanel', visible.queue],
    ['historyPanel', visible.history]
  ];
  for (const [key, shown] of panels) {
    const node = elements[key];
    const wasHidden = node.hidden;
    node.hidden = !shown;
    if (shown && wasHidden) {
      revealPanel(node);
    }
  }

  elements.repair.hidden = !paired;
  elements.revoke.hidden = !paired;

  const workspace = (state && (state.workspaceName || state.baseUrl)) || '';
  if (!paired) {
    setStatus('error', t('needsPair'));
  } else if (offline) {
    setStatus('warn', t('statusOffline'));
  } else if (connected) {
    setStatus('ok', t('pairedAs', { workspace }));
  } else {
    setStatus('pending', t('checking'));
  }

  elements.workspaceName.textContent = workspace || '—';

  renderFocusOptions(state || {});
  renderQueue(state || {});
  renderHistory((state && state.history) || []);

  if (state && state.targetDir && document.activeElement !== elements.targetDir) {
    elements.targetDir.value = state.targetDir;
  }

  if (state && state.notice) {
    elements.notice.hidden = false;
    elements.notice.textContent = state.notice;
  } else {
    elements.notice.hidden = true;
    elements.notice.textContent = '';
  }
}

// -------------------------------------------------------------------- tab ---

async function renderTabLine() {
  let tab = null;
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    tab = tabs && tabs.length ? tabs[0] : null;
  } catch (_error) {
    tab = null;
  }
  const url = tab && tab.url ? String(tab.url) : '';
  const title = (tab && tab.title) || url;
  const http = TrainerCapture.httpUrlOnly(url);
  currentTab = {
    url,
    title,
    kind: http ? TrainerCapture.detectKind(url) : 'web'
  };
  elements.pageLine.textContent = http ? title : t('captureNoUrl');
  elements.capturePage.disabled = !http;

  // Download is an additional action for sources that map to files/folders.
  const downloadable = http && TrainerCapture.supportsDownload(currentTab.kind);
  elements.downloadBlock.hidden = !downloadable;
  elements.captureDownload.disabled = !downloadable;
  if (downloadable && lastTabUrl !== url) {
    revealPanel(elements.downloadBlock);
  }
  lastTabUrl = url;
}

// --------------------------------------------------------------- detection --

async function runDetection() {
  const auth = await TrainerCapture.loadAuth();
  elements.detectLine.classList.remove('detect--error');
  elements.detectLine.textContent = t('detecting');
  elements.detectAgain.disabled = true;
  elements.pairSubmit.disabled = true;

  const discovery = await TrainerCapture.discoverSidecar({ storedBaseUrl: auth.baseUrl });
  detectedBaseUrl = discovery.found ? discovery.baseUrl : '';
  detectedBaseUrls = Array.isArray(discovery.baseUrls) && discovery.baseUrls.length
    ? discovery.baseUrls
    : (discovery.found ? [discovery.baseUrl] : []);
  if (discovery.found) {
    elements.detectLine.textContent = t('detected', { url: discovery.baseUrl });
  } else {
    elements.detectLine.classList.add('detect--error');
    elements.detectLine.textContent = t('detectFailed');
    shake(elements.detectLine);
  }
  elements.detectAgain.disabled = false;
  elements.pairSubmit.disabled = !discovery.found;
}

// ----------------------------------------------------------------- actions --

async function pairNow() {
  const code = elements.pairCode.value;
  if (!TrainerCapture.isValidPairCode(code)) {
    setFeedback(elements.pairFeedback, t('pairInvalidCode'), 'error');
    return;
  }
  if (!detectedBaseUrl) {
    setFeedback(elements.pairFeedback, t('detectFailed'), 'error');
    return;
  }
  elements.pairSubmit.disabled = true;
  setFeedback(elements.pairFeedback, t('checking'), '');
  // Try every reachable Trainer window. With two VS Code windows open the
  // sidecar that answers the fastest may not be the one holding this code.
  const bases = [detectedBaseUrl, ...detectedBaseUrls].filter(
    (value, index, list) => value && list.indexOf(value) === index,
  );
  let result = null;
  let pairedBaseUrl = '';
  for (const baseUrl of bases) {
    result = await TrainerCapture.pairSidecar(baseUrl, code);
    if (result.ok) {
      pairedBaseUrl = baseUrl;
      break;
    }
  }
  if (!result || !result.ok) {
    elements.pairSubmit.disabled = false;
    setFeedback(
      elements.pairFeedback,
      (result && (result.message || t('pairTransport'))) || t('pairTransport'),
      'error',
    );
    return;
  }
  detectedBaseUrl = pairedBaseUrl;
  elements.detectLine.textContent = t('detected', { url: pairedBaseUrl });
  await TrainerCapture.saveAuth(pairedBaseUrl, result.credential);
  await TrainerCapture.clearNotice();
  elements.pairCode.value = '';
  setFeedback(elements.pairFeedback, t('pairSuccess'), '');
  const refreshed = await send({ type: 'trainer:refresh' });
  renderState(refreshed.state || (await send({ type: 'trainer:state' })));
  elements.pairSubmit.disabled = false;
}


async function refreshStateFromHost() {
  const refreshed = await send({ type: 'trainer:refresh' });
  renderState((refreshed && refreshed.state) || (await send({ type: 'trainer:state' })));
}

async function capturePage() {
  elements.capturePage.disabled = true;
  setFeedback(elements.captureResult, t('captureBusy'), '');
  const focusId = elements.focusSelect.value || '';
  await TrainerCapture.saveFocusId(focusId);
  const result = await send({ type: 'trainer:capture-tab' });
  const failed = result.status === 'failed' || result.status === 'unpaired';
  setFeedback(elements.captureResult, result.message || '', failed ? 'error' : '');
  if (!failed) {
    drawSuccessCheck();
  }
  // Re-fetch the sidecar status so the workspace label and history reflect
  // the capture that just landed instead of the pre-capture cache.
  await refreshStateFromHost();
  await renderTabLine();
}

async function downloadToProject() {
  const raw = elements.targetDir.value;
  if (!TrainerCapture.targetDirIsValid(raw)) {
    elements.targetDir.setAttribute('aria-invalid', 'true');
    setFeedback(elements.downloadFeedback, t('downloadInvalidFolder'), 'error');
    return;
  }
  elements.targetDir.removeAttribute('aria-invalid');
  elements.captureDownload.disabled = true;
  setFeedback(elements.downloadFeedback, t('downloadBusy'), '');

  const saved = await send({ type: 'trainer:set-target-dir', targetDir: raw });
  if (saved.ok === false) {
    elements.captureDownload.disabled = false;
    elements.targetDir.setAttribute('aria-invalid', 'true');
    setFeedback(elements.downloadFeedback, saved.message || t('downloadInvalidFolder'), 'error');
    return;
  }
  elements.targetDir.value = saved.targetDir || raw;

  const result = await send({
    type: 'trainer:capture-tab',
    download: true,
    targetDir: elements.targetDir.value
  });
  const failed = result.status === 'failed' || result.status === 'unpaired';
  setFeedback(elements.downloadFeedback, result.message || '', failed ? 'error' : '');
  if (!failed) {
    drawSuccessCheck();
  }
  await refreshStateFromHost();
  await renderTabLine();
}

async function removeQueueEntry(clientCaptureId) {
  const result = await send({ type: 'trainer:queue-remove', clientCaptureId });
  setFeedback(elements.queueFeedback, '', '');
  if (result && result.state) {
    renderState(result.state);
  }
}

async function flushQueueNow() {
  elements.queueRetry.disabled = true;
  setFeedback(elements.queueFeedback, t('queueFlushing'), '');
  const result = await send({ type: 'trainer:flush' });
  setFeedback(
    elements.queueFeedback,
    result.message || '',
    result.ok === false ? 'warn' : ''
  );
  renderState(result.state || (await send({ type: 'trainer:state' })));
  elements.queueRetry.disabled = Number((result.state || {}).queueCount) === 0;
}

async function clearQueue() {
  if (!window.confirm(t('queueClearConfirm'))) {
    return;
  }
  const result = await send({ type: 'trainer:queue-clear' });
  if (result && result.state) {
    renderState(result.state);
  }
  setFeedback(elements.queueFeedback, t('queueEmpty'), '');
}

async function disconnectAndRepair() {
  if (!window.confirm(t('pairRevokeHint'))) {
    return;
  }
  const result = await send({ type: 'trainer:revoke' });
  renderState(await send({ type: 'trainer:state' }));
  setFeedback(elements.pairFeedback, result.message || t('pairRevokeDone'), '');
  await renderTabLine();
  await runDetection();
}

// ------------------------------------------------------------------ wiring --

async function init() {
  applyCopy();
  const state = await send({ type: 'trainer:state' });
  renderState(state);
  await renderTabLine();

  if (state.paired) {
    const refreshed = await send({ type: 'trainer:refresh' });
    renderState(refreshed.state || state);
  } else {
    await runDetection();
  }
}

elements.detectAgain.addEventListener('click', () => {
  void runDetection();
});

elements.pairSubmit.addEventListener('click', () => {
  void pairNow();
});

elements.pairCode.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    void pairNow();
  }
});

elements.capturePage.addEventListener('click', () => {
  void capturePage();
});

elements.captureDownload.addEventListener('click', () => {
  void downloadToProject();
});

elements.targetDir.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    void downloadToProject();
  }
});

elements.targetDir.addEventListener('input', () => {
  elements.targetDir.removeAttribute('aria-invalid');
});

elements.focusSelect.addEventListener('change', () => {
  void send({ type: 'trainer:set-focus', focusId: elements.focusSelect.value || '' });
});

elements.queueRetry.addEventListener('click', () => {
  void flushQueueNow();
});

elements.queueClear.addEventListener('click', () => {
  void clearQueue();
});

elements.revoke.addEventListener('click', () => {
  void disconnectAndRepair();
});

if (elements.close) {
  elements.close.addEventListener('click', () => window.close());
}

elements.repair.addEventListener('click', () => {
  void disconnectAndRepair();
});

elements.openTrainer.addEventListener('click', () => {
  void send({ type: 'trainer:open', url: TrainerCapture.HOST_DEEP_LINK });
});

document.addEventListener('DOMContentLoaded', () => {
  void init();
});
