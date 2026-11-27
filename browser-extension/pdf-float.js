'use strict';

/**
 * Minimal PDF-only affordance (< 2.5 KB): mounted strictly on `*://*/*.pdf*`
 * documents so normal web pages never pay content-script injection overhead.
 */
(function mountTrainerPdfAffordance() {
  const BUTTON_ID = 'trainer-capture-pdf-float';
  if (typeof document === 'undefined' || !document || document.contentType !== 'application/pdf') {
    return;
  }
  if (document.getElementById(BUTTON_ID)) {
    return;
  }
  if (typeof chrome === 'undefined' || !chrome.runtime || typeof chrome.runtime.sendMessage !== 'function') {
    return;
  }

  const locale = String((typeof navigator !== 'undefined' && navigator.language) || 'en').toLowerCase();
  const isZh = locale.startsWith('zh');
  const labels = isZh
    ? {
        idle: '加入 Trainer 资料库',
        title: '将当前 PDF 收录到配对的 Trainer 资料库',
        working: '正在收录…',
        done: '已加入资料库',
        duplicate: '已在资料库中',
        queued: '已离线暂存',
        needsPair: '请先在扩展弹窗配对',
        failed: '收录失败，点击重试',
      }
    : {
        idle: 'Save PDF to Trainer',
        title: 'Capture this PDF into the paired Trainer library',
        working: 'Saving…',
        done: 'Saved to Trainer',
        duplicate: 'Already in library',
        queued: 'Queued offline',
        needsPair: 'Pair Trainer first',
        failed: 'Capture failed — retry',
      };

  function createButton() {
    const button = document.createElement('button');
    button.id = BUTTON_ID;
    button.type = 'button';
    button.textContent = labels.idle;
    button.title = labels.title;
    button.setAttribute('aria-label', labels.title);
    button.style.cssText = [
      'position: fixed',
      'right: 18px',
      'bottom: 18px',
      'z-index: 2147483647',
      'padding: 8px 14px',
      'border: 1px solid rgba(15, 23, 42, 0.18)',
      'border-radius: 999px',
      'background: #2563eb',
      'color: #ffffff',
      'font: 600 12px/1.2 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif',
      'box-shadow: 0 6px 18px rgba(15, 23, 42, 0.28)',
      'cursor: pointer',
    ].join('; ');

    let busy = false;
    const settle = (text, disable) => {
      button.textContent = text;
      if (disable) {
        button.disabled = true;
        button.style.cursor = 'default';
      }
    };

    button.addEventListener('click', () => {
      if (busy || button.disabled) return;
      busy = true;
      button.textContent = labels.working;
      chrome.runtime.sendMessage(
        { type: 'trainer:pdf-capture', url: location.href, title: document.title || '' },
        (response) => {
          busy = false;
          if (chrome.runtime.lastError) {
            settle(labels.failed, false);
            return;
          }
          const status = response && response.status ? String(response.status) : 'failed';
          if (status === 'ok') return settle(labels.done, true);
          if (status === 'duplicated' || status === 'duplicate-local') return settle(labels.duplicate, true);
          if (status === 'queued') return settle(labels.queued, false);
          if (status === 'unpaired') return settle(labels.needsPair, false);
          settle(labels.failed, false);
        },
      );
    });
    return button;
  }

  const attach = () => {
    const root = document.body || document.documentElement;
    if (root && !document.getElementById(BUTTON_ID)) {
      root.appendChild(createButton());
    }
  };

  if (document.body) {
    attach();
  } else {
    document.addEventListener('DOMContentLoaded', attach, { once: true });
  }
})();
