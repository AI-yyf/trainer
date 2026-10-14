'use strict';

/**
 * Trainer Capture — background service worker.
 *
 * Registers the three right-click capture entries and relays the clicked URL
 * to the configured Trainer sidecar. The extension never injects scripts into
 * pages and never uploads page content: it only sends {url, kind, title}, and
 * the sidecar performs the controlled fetch and extraction.
 */

importScripts('shared.js');

const MENU_IDS = {
  page: 'trainer-capture-page',
  link: 'trainer-capture-link',
  github: 'trainer-capture-github'
};

// One notification slot: the progress notice is replaced by the result, so a
// capture never leaves two stacked notifications behind.
const PROGRESS_NOTIFICATION_ID = 'trainer-capture-progress';

const TrainerCapture = self.TrainerCapture;

chrome.runtime.onInstalled.addListener(() => {
  void registerContextMenus();
});

chrome.runtime.onStartup.addListener(() => {
  void registerContextMenus();
});

async function registerContextMenus() {
  await chrome.contextMenus.removeAll();
  chrome.contextMenus.create({
    id: MENU_IDS.page,
    title: '添加到 Trainer 资料库（当前页面）',
    contexts: ['page']
  });
  chrome.contextMenus.create({
    id: MENU_IDS.link,
    title: '添加到 Trainer 资料库（此链接）',
    contexts: ['link']
  });
  chrome.contextMenus.create({
    id: MENU_IDS.github,
    title: '添加此 GitHub 仓库到 Trainer',
    contexts: ['page'],
    documentUrlPatterns: ['https://github.com/*']
  });
}

function resolveTarget(info, tab) {
  if (info.menuItemId === MENU_IDS.link) {
    const url = String(info.linkUrl || '').trim();
    if (!TrainerCapture.httpUrlOnly(url)) {
      return null;
    }
    return {
      url,
      kind: TrainerCapture.detectKind(url),
      title: String(info.linkText || '').trim() || null
    };
  }

  const pageUrl = String(info.pageUrl || (tab && tab.url) || '').trim();
  if (!TrainerCapture.httpUrlOnly(pageUrl)) {
    return null;
  }
  if (info.menuItemId === MENU_IDS.github) {
    // Let the sidecar name the resource after the repository itself.
    return { url: pageUrl, kind: 'github_repo', title: null };
  }
  const tabTitle = tab && tab.title ? String(tab.title).trim() : '';
  return {
    url: pageUrl,
    kind: TrainerCapture.detectKind(pageUrl),
    title: tabTitle || null
  };
}

async function notify(title, message, { id } = {}) {
  const options = {
    type: 'basic',
    iconUrl: chrome.runtime.getURL('icons/icon128.png'),
    title,
    message
  };
  try {
    if (id) {
      await chrome.notifications.create(id, options);
    } else {
      await chrome.notifications.create(options);
    }
  } catch (error) {
    console.warn('Trainer Capture notification failed:', error);
  }
}

async function handleMenuClick(info, tab) {
  const target = resolveTarget(info, tab);
  if (!target) {
    await notify('Trainer Capture', '这个条目没有可采集的 http/https 地址。');
    return;
  }

  const settings = await TrainerCapture.loadSettings();
  if (target.kind === 'github_repo') {
    const label = TrainerCapture.githubRepoLabel(target.url);
    if (!label) {
      await notify('Trainer Capture', 'GitHub 采集需要一个仓库地址（github.com/<owner>/<repo>）。');
      return;
    }
  }

  await notify('Trainer 正在处理…', target.url, { id: PROGRESS_NOTIFICATION_ID });
  const result = await TrainerCapture.sendCapture(
    settings,
    TrainerCapture.buildCapturePayload(settings, target)
  );

  await TrainerCapture.recordHistory({
    url: target.url,
    kind: target.kind,
    title: target.title || '',
    status: result.ok ? 'ok' : 'failed',
    message: result.message,
    resourceId: result.resourceId || null,
    at: new Date().toISOString()
  });

  await notify(
    result.ok ? '已添加到 Trainer 资料库' : 'Trainer Capture 采集失败',
    result.message,
    { id: PROGRESS_NOTIFICATION_ID }
  );
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  return handleMenuClick(info, tab);
});
