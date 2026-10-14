'use strict';

/**
 * Trainer Capture — shared constants and sidecar helpers.
 *
 * This file is a plain script loaded by both the background service worker
 * (importScripts) and the popup page (<script>). It only ever talks to the
 * locally configured Trainer sidecar over HTTP: no page scripts are injected,
 * no page content is read, and captured bodies are fetched server-side.
 */
(function (global) {
  const DEFAULTS = {
    baseUrl: 'http://127.0.0.1:8765',
    workspaceId: 'workspace-default'
  };

  const STORAGE_KEYS = {
    baseUrl: 'sidecarBaseUrl',
    workspaceId: 'workspaceId',
    token: 'sidecarToken',
    history: 'captureHistory'
  };

  const HISTORY_LIMIT = 5;
  const REQUEST_TIMEOUT_MS = 120000;
  const CAPTURE_PATH = '/resources/capture';

  function normalizeBaseUrl(value) {
    const raw = String(value || '').trim() || DEFAULTS.baseUrl;
    const trimmed = raw.replace(/\/+$/, '');
    if (!/^https?:\/\//i.test(trimmed)) {
      return `http://${trimmed}`;
    }
    return trimmed;
  }

  async function loadSettings() {
    const syncStored = await chrome.storage.sync.get({
      [STORAGE_KEYS.baseUrl]: DEFAULTS.baseUrl,
      [STORAGE_KEYS.workspaceId]: DEFAULTS.workspaceId
    });
    const localStored = await chrome.storage.local.get({
      [STORAGE_KEYS.token]: ''
    });
    return {
      baseUrl: normalizeBaseUrl(syncStored[STORAGE_KEYS.baseUrl]),
      workspaceId: String(syncStored[STORAGE_KEYS.workspaceId] || DEFAULTS.workspaceId).trim(),
      token: String(localStored[STORAGE_KEYS.token] || '').trim()
    };
  }

  async function saveSettings(settings) {
    const normalized = {
      baseUrl: normalizeBaseUrl(settings.baseUrl),
      workspaceId: String(settings.workspaceId || '').trim() || DEFAULTS.workspaceId
    };
    await chrome.storage.sync.set({
      [STORAGE_KEYS.baseUrl]: normalized.baseUrl,
      [STORAGE_KEYS.workspaceId]: normalized.workspaceId
    });
    // The token is entered by hand and belongs to this browser profile only —
    // it stays out of Chrome account sync.
    await chrome.storage.local.set({
      [STORAGE_KEYS.token]: String(settings.token || '').trim()
    });
    return { ...normalized, token: String(settings.token || '').trim() };
  }

  async function loadHistory() {
    const stored = await chrome.storage.local.get({ [STORAGE_KEYS.history]: [] });
    const entries = stored[STORAGE_KEYS.history];
    return Array.isArray(entries) ? entries : [];
  }

  async function recordHistory(entry) {
    const history = await loadHistory();
    const next = [entry, ...history].slice(0, HISTORY_LIMIT);
    await chrome.storage.local.set({ [STORAGE_KEYS.history]: next });
    return next;
  }

  function isPdfUrl(url) {
    return /\.pdf(?:$|[?#])/i.test(String(url || ''));
  }

  function githubRepoLabel(url) {
    const match = String(url || '').match(
      /^https?:\/\/(?:www\.)?github\.com\/([A-Za-z0-9._-]+)\/([A-Za-z0-9._-]+?)(?:\.git)?(?:\/|$|[?#])/i
    );
    if (!match) {
      return null;
    }
    return `${match[1]}/${match[2]}`;
  }

  function detectKind(url) {
    if (githubRepoLabel(url)) {
      return 'github_repo';
    }
    if (isPdfUrl(url)) {
      return 'pdf';
    }
    return 'web';
  }

  function httpUrlOnly(url) {
    return /^https?:\/\//i.test(String(url || '').trim());
  }

  function buildCapturePayload(settings, target) {
    return {
      url: target.url,
      kind: target.kind,
      title: target.title || null,
      workspace_id: settings.workspaceId
    };
  }

  function buildHeaders(settings) {
    const headers = { 'Content-Type': 'application/json' };
    if (settings.token) {
      headers['x-trainer-token'] = settings.token;
    }
    return headers;
  }

  function describeHttpError(status, body) {
    const detail = body && typeof body === 'object' ? body.detail : null;
    const code = detail && typeof detail === 'object' ? String(detail.code || '') : '';
    const message =
      detail && typeof detail === 'object'
        ? String(detail.message || '')
        : typeof detail === 'string'
          ? detail
          : '';

    if (status === 401) {
      return 'sidecar 需要访问令牌：请在弹窗设置里填写访问令牌（x-trainer-token）后重试。';
    }
    if (status === 409 && code === 'network_disabled') {
      return 'Trainer 已关闭网络抓取，无法下载该来源。请在 Trainer 设置里开启网络访问后重试。';
    }
    if (status === 409 && code === 'browse_only_persistence_blocked') {
      return '当前 Trainer 工作区处于只读（browse-only）模式，无法写入资料库。';
    }
    if (status === 404 && code === 'readme_not_found') {
      return message || '该仓库的默认分支上没有找到 README。';
    }
    if (message) {
      return `添加失败（HTTP ${status}）：${message}`;
    }
    return `添加失败：sidecar 返回 HTTP ${status}。`;
  }

  function describeFetchError(error, settings) {
    const name = error && error.name ? String(error.name) : '';
    if (name === 'AbortError') {
      return '请求超时：Trainer 还没来得及处理这个来源（大文件可能需要更久）。';
    }
    return `无法连接 Trainer sidecar（${settings.baseUrl}）。请确认 Trainer 正在运行、地址与访问令牌正确。`;
  }

  async function sendCapture(settings, payload) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(`${settings.baseUrl}${CAPTURE_PATH}`, {
        method: 'POST',
        headers: buildHeaders(settings),
        body: JSON.stringify(payload),
        signal: controller.signal
      });
      const text = await response.text();
      let body = null;
      try {
        body = text ? JSON.parse(text) : null;
      } catch (_error) {
        body = null;
      }
      if (!response.ok) {
        return { ok: false, message: describeHttpError(response.status, body), status: response.status };
      }
      const record = body && typeof body === 'object' ? body : {};
      return {
        ok: true,
        status: response.status,
        resourceId: record.id ? String(record.id) : null,
        resourceName: record.name ? String(record.name) : '',
        message: `已添加到 Trainer 资料库：${record.name || payload.url}`
      };
    } catch (error) {
      return { ok: false, message: describeFetchError(error, settings), status: 0 };
    } finally {
      clearTimeout(timer);
    }
  }

  async function checkSidecarHealth(settings) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(`${settings.baseUrl}/health`, {
        headers: buildHeaders(settings),
        signal: controller.signal
      });
      if (response.ok) {
        return { connected: true, message: '已连接 sidecar' };
      }
      if (response.status === 401) {
        return { connected: false, message: 'sidecar 拒绝访问：访问令牌缺失或不正确' };
      }
      return { connected: false, message: `sidecar 返回 HTTP ${response.status}` };
    } catch (error) {
      return { connected: false, message: `无法连接 ${settings.baseUrl}` };
    } finally {
      clearTimeout(timer);
    }
  }

  function formatTimestamp(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return '';
    }
    const pad = (part) => String(part).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  global.TrainerCapture = {
    DEFAULTS,
    STORAGE_KEYS,
    HISTORY_LIMIT,
    CAPTURE_PATH,
    normalizeBaseUrl,
    loadSettings,
    saveSettings,
    loadHistory,
    recordHistory,
    detectKind,
    githubRepoLabel,
    isPdfUrl,
    httpUrlOnly,
    buildCapturePayload,
    buildHeaders,
    sendCapture,
    checkSidecarHealth,
    formatTimestamp
  };
})(typeof self !== 'undefined' ? self : globalThis);
