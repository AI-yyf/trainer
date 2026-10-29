'use strict';

/**
 * Trainer Capture — popup.
 *
 * Zero pairing UI: the background discovers the local sidecar and connects
 * itself, so the card is capture-only — the capture row (page / PDF / GitHub
 * repo), the optional project-folder download, and the library binding.
 * Captures taken while Trainer is unreachable queue automatically (the badge
 * carries the count); no connection status and no import history are shown.
 *
 * Copy follows the browser locale (zh-CN, en-US, es-ES, fr-FR, de-DE, ja-JP,
 * ko-KR, pt-BR — with English as the fallback). Motion is explanatory only and
 * yields to prefers-reduced-motion via the stylesheet.
 */

const TrainerCapture = self.TrainerCapture;

const elements = {
  capturePanel: document.getElementById('capture-panel'),
  pageLine: document.getElementById('page-line'),
  focusSelect: document.getElementById('focus-select'),
  capturePage: document.getElementById('capture-page'),
  captureResult: document.getElementById('capture-result'),
  downloadBlock: document.getElementById('download-block'),
  targetDir: document.getElementById('target-dir'),
  captureDownload: document.getElementById('capture-download'),
  downloadFeedback: document.getElementById('download-feedback'),
  revoke: document.getElementById('revoke'),
  openTrainer: document.getElementById('open-trainer'),
  notice: document.getElementById('notice'),
  close: document.getElementById('popup-close')
};

const copy = TrainerCapture.copyFor(TrainerCapture.browserLocale());
let currentTab = { url: '', title: '', kind: 'web' };
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
  // a panel that just became hidden. On popup open the panel is revealed from
  // `hidden`, so focus is left on the primary action instead of cascading.
  const previous = document.activeElement;
  const previousPanel = previous instanceof HTMLElement ? previous.closest('.panel') : null;
  if (previousPanel && previousPanel.hidden) {
    element.setAttribute('tabindex', '-1');
    element.focus({ preventScroll: true });
  }
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

function revealCapturePanel() {
  if (!elements.capturePanel.hidden) {
    return;
  }
  elements.capturePanel.hidden = false;
  revealPanel(elements.capturePanel);
}

function renderState(state) {
  const paired = Boolean(state && state.paired);

  // The card is capture-only. A capture taken before Trainer is reachable is
  // queued by the worker and delivered automatically, so there is no pairing
  // state to render and no reason to block the primary action.
  revealCapturePanel();
  elements.revoke.hidden = !paired;

  renderFocusOptions(state || {});

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
  if (downloadable) {
    if (!elements.targetDir.value) {
      elements.targetDir.value = TrainerCapture.DEFAULT_TARGET_DIR;
    }
    if (lastTabUrl !== url) {
      revealPanel(elements.downloadBlock);
    }
  }
  lastTabUrl = url;
}

// ------------------------------------------------------------------- run --

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
  // Re-fetch the sidecar state so the focus binding reflects the capture
  // that just landed instead of the pre-capture cache.
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

async function disconnectAndRepair() {
  if (!window.confirm(t('pairRevokeHint'))) {
    return;
  }
  const result = await send({ type: 'trainer:revoke' });
  renderState(await send({ type: 'trainer:state' }));
  setFeedback(elements.captureResult, result.message || t('pairRevokeDone'), '');
  await renderTabLine();
}

// ------------------------------------------------------------------ wiring --

async function init() {
  applyCopy();
  // Do not wait for the auto-pair probe: the card is usable (and queues)
  // immediately, even when Trainer is not running yet.
  revealCapturePanel();
  renderFocusOptions({});
  const state = await send({ type: 'trainer:state' });
  renderState(state);
  await renderTabLine();

  if (state && state.paired) {
    const refreshed = await send({ type: 'trainer:refresh' });
    renderState((refreshed && refreshed.state) || state);
  }

  window.setInterval(async () => {
    const next = await send({ type: 'trainer:state' });
    if (next && next.state) {
      renderState(next.state);
    } else if (next && typeof next.paired === 'boolean') {
      renderState(next);
    }
  }, 4000);
}

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

elements.revoke.addEventListener('click', () => {
  void disconnectAndRepair();
});

if (elements.close) {
  elements.close.addEventListener('click', () => window.close());
}

elements.openTrainer.addEventListener('click', () => {
  void send({ type: 'trainer:open', url: TrainerCapture.HOST_DEEP_LINK });
});

document.addEventListener('DOMContentLoaded', () => {
  void init();
});
