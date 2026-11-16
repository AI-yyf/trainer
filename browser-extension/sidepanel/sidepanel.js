'use strict';

/**
 * Trainer Capture — Ask Trainer side panel.
 *
 * P4 minimal loop: the learner types one question, clicks Ask once, and the
 * current page context (title/URL, plus the selection if one exists) is
 * staged into the existing browser-capture draft channel. The draft prefills
 * the shared Trainer composer — Coach/Learning/Resources all read the same
 * staged source; the panel itself never sends a chat message.
 *
 * Reading the page is user-authorized by construction: the selection and tab
 * context are only read inside the Ask click handler.
 */

const TrainerCapture = self.TrainerCapture;

const elements = {
  pageLine: document.getElementById('ask-page-line'),
  question: document.getElementById('ask-question'),
  askSend: document.getElementById('ask-send'),
  askResult: document.getElementById('ask-result'),
  openTrainer: document.getElementById('open-trainer')
};

const copy = TrainerCapture.copyFor(TrainerCapture.browserLocale());
let currentHttpUrl = '';

function t(key, values) {
  return TrainerCapture.formatCopy(copy[key] || '', values);
}

function applyCopy() {
  document.documentElement.lang = TrainerCapture.resolveLanguageTag(TrainerCapture.browserLocale());
  document.title = t('askPanelHeading');
  for (const node of document.querySelectorAll('[data-copy]')) {
    node.textContent = t(node.getAttribute('data-copy'));
  }
  for (const node of document.querySelectorAll('[data-copy-placeholder]')) {
    node.setAttribute('placeholder', t(node.getAttribute('data-copy-placeholder')));
  }
}

function send(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      void chrome.runtime.lastError;
      resolve(response || null);
    });
  });
}

function setFeedback(node, message, tone) {
  node.textContent = message || '';
  node.className = message
    ? tone === 'error'
      ? 'feedback feedback--error'
      : 'feedback'
    : 'feedback';
}

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
  currentHttpUrl = TrainerCapture.httpUrlOnly(url) ? url : '';
  // P4: name the source kind — a PDF document or GitHub repo page asks with
  // the same flow, and the learner sees what will be staged.
  const kindLabel = currentHttpUrl
    ? t(TrainerCapture.kindCopyKey(TrainerCapture.detectKind(url)))
    : '';
  elements.pageLine.textContent = currentHttpUrl
    ? kindLabel ? `${title} · ${kindLabel}` : title
    : t('captureNoUrl');
  elements.askSend.disabled = !currentHttpUrl;
}

async function askTrainer() {
  elements.askSend.disabled = true;
  setFeedback(elements.askResult, t('askPanelBusy'), '');
  const question = elements.question.value.trim();
  // The single Ask click is the authorization: only here does the worker
  // read the tab context and the page selection.
  const result = await send({ type: 'trainer:send-tab-context', question });
  const failed = result.status === 'failed' || result.status === 'unpaired';
  setFeedback(elements.askResult, result.message || '', failed ? 'error' : '');
  if (!failed) {
    elements.question.value = '';
  }
  await renderTabLine();
}

elements.askSend.addEventListener('click', () => {
  void askTrainer();
});

elements.openTrainer.addEventListener('click', () => {
  void send({ type: 'trainer:open', url: TrainerCapture.HOST_DEEP_LINK });
});

document.addEventListener('DOMContentLoaded', () => {
  applyCopy();
  void renderTabLine();
});
