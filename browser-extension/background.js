'use strict';

/**
 * Trainer Capture — background service worker.
 *
 * Owns the whole capture pipeline: right-click menus, pairing state, capture
 * submission, the offline queue, notifications and the deep links back into
 * the Trainer host.
 *
 * Data-channel discipline: nothing is injected into pages, no cookies or page
 * bodies are read. The worker forwards only what the user explicitly captured
 * ({url, kind, title} or a selected passage) to the local sidecar, which does
 * all fetching, snapshotting and authoritative deduplication. The single
 * destination is the resource library — there is deliberately no "pending
 * learning queue" concept anywhere in this extension.
 *
 * Two capture actions per source: "add to the library" (the base action) and,
 * for PDFs and GitHub repositories, "download into the project folder"
 * (`download: true` + `target_dir`). Downloads queue offline exactly like
 * library captures and replay with the same client_capture_id.
 */

importScripts('shared.js');

const TrainerCapture = self.TrainerCapture;

const MENU_IDS = {
  page: 'trainer-capture-page',
  link: 'trainer-capture-link',
  pdfPage: 'trainer-capture-pdf-page',
  pdfPageLibrary: 'trainer-capture-pdf-page-library',
  pdfPageDownload: 'trainer-capture-pdf-page-download',
  pdfLink: 'trainer-capture-pdf-link',
  pdfLinkLibrary: 'trainer-capture-pdf-link-library',
  pdfLinkDownload: 'trainer-capture-pdf-link-download',
  github: 'trainer-capture-github',
  githubReadme: 'trainer-capture-github-readme',
  githubDocs: 'trainer-capture-github-docs',
  githubDownload: 'trainer-capture-github-download',
  selectionCoach: 'trainer-coach-selection'
};

const FLUSH_ALARM = 'trainer-capture-flush';
const FLUSH_PERIOD_MINUTES = 1;
const RESULT_NOTIFICATION_ID = 'trainer-capture-result';
const NOTIFICATION_LINKS_KEY = 'trainerCapture.notificationLinks';
const BADGE_BACKGROUND = '#4338CA';
const GITHUB_PAGE_PATTERNS = ['https://github.com/*', 'https://www.github.com/*'];
// Match patterns are intentionally loose: the submenu only offers the PDF
// actions, the handler re-validates the real URL before capturing.
const PDF_PATTERNS = ['*://*/*.pdf*'];

// Every queue mutation runs through one serialized critical section.
// Concurrent captures, flushes and capacity checks must never read a stale
// snapshot and overwrite each other (issue T-0006).
let queueMutationChain = Promise.resolve();
function withQueueLock(task) {
  const run = queueMutationChain.then(task, task);
  queueMutationChain = run.then(
    () => undefined,
    () => undefined
  );
  return run;
}

function dict() {
  return TrainerCapture.activeCopy();
}

// ---------------------------------------------------------------- menus ----

async function ensureMenus() {
  await chrome.contextMenus.removeAll();
  const copy = dict();
  chrome.contextMenus.create({
    id: MENU_IDS.page,
    title: copy.menuPage,
    contexts: ['page']
  });
  // PDF (page and link): a submenu carrying both actions — add to the library
  // stays the base action, download is the additional one (task 二).
  chrome.contextMenus.create({
    id: MENU_IDS.pdfPage,
    title: copy.menuPdfGroup,
    contexts: ['page'],
    documentUrlPatterns: PDF_PATTERNS
  });
  chrome.contextMenus.create({
    id: MENU_IDS.pdfPageLibrary,
    parentId: MENU_IDS.pdfPage,
    title: copy.menuPdfLibrary,
    contexts: ['page'],
    documentUrlPatterns: PDF_PATTERNS
  });
  chrome.contextMenus.create({
    id: MENU_IDS.pdfPageDownload,
    parentId: MENU_IDS.pdfPage,
    title: copy.menuPdfDownload,
    contexts: ['page'],
    documentUrlPatterns: PDF_PATTERNS
  });
  chrome.contextMenus.create({
    id: MENU_IDS.link,
    title: copy.menuLink,
    contexts: ['link']
  });
  chrome.contextMenus.create({
    id: MENU_IDS.pdfLink,
    title: copy.menuPdfGroup,
    contexts: ['link'],
    targetUrlPatterns: PDF_PATTERNS
  });
  chrome.contextMenus.create({
    id: MENU_IDS.pdfLinkLibrary,
    parentId: MENU_IDS.pdfLink,
    title: copy.menuPdfLibrary,
    contexts: ['link'],
    targetUrlPatterns: PDF_PATTERNS
  });
  chrome.contextMenus.create({
    id: MENU_IDS.pdfLinkDownload,
    parentId: MENU_IDS.pdfLink,
    title: copy.menuPdfDownload,
    contexts: ['link'],
    targetUrlPatterns: PDF_PATTERNS
  });
  chrome.contextMenus.create({
    id: MENU_IDS.github,
    title: copy.menuGithubGroup,
    contexts: ['page'],
    documentUrlPatterns: GITHUB_PAGE_PATTERNS
  });
  chrome.contextMenus.create({
    id: MENU_IDS.githubReadme,
    parentId: MENU_IDS.github,
    title: copy.menuGithubReadme,
    contexts: ['page'],
    documentUrlPatterns: GITHUB_PAGE_PATTERNS
  });
  chrome.contextMenus.create({
    id: MENU_IDS.githubDocs,
    parentId: MENU_IDS.github,
    title: copy.menuGithubDocs,
    contexts: ['page'],
    documentUrlPatterns: GITHUB_PAGE_PATTERNS
  });
  chrome.contextMenus.create({
    id: MENU_IDS.githubDownload,
    parentId: MENU_IDS.github,
    title: copy.menuGithubDownload,
    contexts: ['page'],
    documentUrlPatterns: GITHUB_PAGE_PATTERNS
  });
  chrome.contextMenus.create({
    id: MENU_IDS.selectionCoach,
    title: copy.coachMenu,
    contexts: ['selection']
  });
}

// --------------------------------------------------------- notifications ----

async function readNotificationLinks() {
  const stored = await chrome.storage.local.get({ [NOTIFICATION_LINKS_KEY]: {} });
  const links = stored[NOTIFICATION_LINKS_KEY];
  return links && typeof links === 'object' ? links : {};
}

async function notifyResult(title, message, deepLink) {
  const options = {
    type: 'basic',
    iconUrl: chrome.runtime.getURL('icons/icon128.png'),
    title,
    message
  };
  try {
    await chrome.notifications.create(RESULT_NOTIFICATION_ID, options);
    const links = await readNotificationLinks();
    if (deepLink) {
      links[RESULT_NOTIFICATION_ID] = deepLink;
    } else {
      delete links[RESULT_NOTIFICATION_ID];
    }
    await chrome.storage.local.set({ [NOTIFICATION_LINKS_KEY]: links });
  } catch (error) {
    console.warn('Trainer Capture notification failed:', error);
  }
}

async function openDeepLink(url) {
  const target = String(url || '').trim();
  if (!target) {
    return false;
  }
  try {
    await chrome.tabs.create({ url: target });
    return true;
  } catch (error) {
    console.warn('Trainer Capture could not open deep link:', error);
    return false;
  }
}

chrome.notifications.onClicked.addListener((notificationId) => {
  void (async () => {
    const links = await readNotificationLinks();
    const target = links[notificationId];
    if (!target) {
      return;
    }
    await openDeepLink(target);
  })();
});

// ---------------------------------------------------------------- badge ----

async function updateBadge() {
  try {
    const [auth, queue, drafts] = await Promise.all([
      TrainerCapture.loadAuth(),
      TrainerCapture.loadQueue(),
      TrainerCapture.loadDraftQueue()
    ]);
    const pending = queue.length + drafts.length;
    let text = '';
    if (!auth.credential) {
      text = pending ? String(pending) : '!';
    } else if (pending) {
      text = String(pending);
    }
    await chrome.action.setBadgeText({ text });
    if (text) {
      await chrome.action.setBadgeBackgroundColor({ color: BADGE_BACKGROUND });
    }
  } catch (error) {
    console.warn('Trainer Capture badge update failed:', error);
  }
}

// --------------------------------------------------------------- targets ----

const DOWNLOAD_MENU_IDS = new Set([
  MENU_IDS.pdfPageDownload,
  MENU_IDS.pdfLinkDownload,
  MENU_IDS.githubDownload
]);

function resolveCaptureTarget(menuId, info, tab) {
  const pageUrl = String(info.pageUrl || (tab && tab.url) || '').trim();
  const tabTitle = tab && tab.title ? String(tab.title).trim() : '';
  const download = DOWNLOAD_MENU_IDS.has(menuId);

  if (menuId === MENU_IDS.link || menuId === MENU_IDS.pdfLinkLibrary || menuId === MENU_IDS.pdfLinkDownload) {
    const url = String(info.linkUrl || '').trim();
    if (!TrainerCapture.httpUrlOnly(url)) {
      return null;
    }
    const kind = menuId === MENU_IDS.link ? TrainerCapture.detectKind(url) : 'pdf';
    return {
      url,
      kind,
      title: String(info.linkText || '').trim() || null,
      download,
      source: 'menu-link'
    };
  }

  if (!TrainerCapture.httpUrlOnly(pageUrl)) {
    return null;
  }

  if (menuId === MENU_IDS.pdfPageLibrary || menuId === MENU_IDS.pdfPageDownload) {
    if (!TrainerCapture.isPdfUrl(pageUrl)) {
      return null;
    }
    return {
      url: pageUrl,
      kind: 'pdf',
      title: tabTitle || null,
      download,
      source: 'menu-pdf'
    };
  }

  if (
    menuId === MENU_IDS.githubReadme ||
    menuId === MENU_IDS.githubDocs ||
    menuId === MENU_IDS.githubDownload
  ) {
    if (!TrainerCapture.githubRepoLabel(pageUrl)) {
      return { invalid: 'github' };
    }
    return {
      url: pageUrl,
      kind: 'github_repo',
      title: null,
      includeDocs: menuId === MENU_IDS.githubDocs,
      download,
      source: 'menu-github'
    };
  }

  return {
    url: pageUrl,
    kind: TrainerCapture.detectKind(pageUrl),
    title: tabTitle || null,
    source: 'menu-page'
  };
}

// --------------------------------------------------------------- capture ----

async function sendCaptureWithRecovery(payload, auth) {
  let result = await TrainerCapture.sendCapture(auth.baseUrl, auth.credential, payload);
  if (!result.transportError || !auth.baseUrl) {
    return result;
  }
  // The sidecar may have restarted on another managed port; re-discover once
  // and retry with the same credential (client_capture_id keeps it idempotent).
  // Only switch to an instance that actually accepts the credential.
  const recoveredBaseUrl = await findPairedBaseUrl(auth);
  if (!recoveredBaseUrl) {
    return result;
  }
  await TrainerCapture.saveAuth(recoveredBaseUrl, auth.credential);
  result = await TrainerCapture.sendCapture(recoveredBaseUrl, auth.credential, payload);
  return result;
}

function buildHistoryEntry(target, status, message, response) {
  return {
    url: target.url,
    kind: TrainerCapture.normalizeKind(target.kind),
    title: target.title || '',
    status,
    message,
    resourceId: response && response.resourceId ? response.resourceId : '',
    deepLink: response && response.deepLink ? response.deepLink : '',
    download: target.download === true,
    savedPath: (response && response.savedPath) || '',
    targetDir: target.download === true ? String(target.targetDir || '') : '',
    dedupKey: trainerDedupKey(target),
    at: new Date().toISOString()
  };
}

function trainerDedupKey(target) {
  return TrainerCapture.buildDedupKey({
    url: target.url,
    kind: target.kind,
    includeDocs: target.includeDocs,
    download: target.download,
    targetDir: target.targetDir
  });
}

/** Persist the last observed sidecar reachability for the popup's three states. */
async function recordConnection(state) {
  try {
    await TrainerCapture.saveConnection(state);
  } catch (error) {
    console.warn('Trainer Capture could not persist the connection state:', error);
  }
}

/**
 * Run one capture end to end. Returns a status payload the popup / content
 * script can render:
 *   ok | duplicated | duplicate-local | queued | unpaired | failed
 *
 * A download capture (`target.download`) is the same pipeline with
 * `download: true` + `target_dir` in the payload; the sidecar answers with
 * `saved_path`, which the notification and the history entry carry.
 */
async function runCapture(target, options) {
  const settings = options || {};
  const copy = dict();
  const url = TrainerCapture.normalizeCaptureUrl(target.url);
  if (!url) {
    const message = copy.captureNoUrl;
    if (settings.notify !== false) {
      await notifyResult(copy.notifyFailedTitle, message, '');
    }
    return { status: 'failed', message, deepLink: '' };
  }

  const kind = TrainerCapture.normalizeKind(target.kind);
  const download = target.download === true && TrainerCapture.supportsDownload(kind);
  const normalizedTarget = {
    url,
    kind,
    title: target.title || '',
    selection: target.selection || '',
    includeDocs: kind === 'github_repo' && target.includeDocs === true,
    download,
    targetDir: download ? String(target.targetDir || '') : ''
  };

  let [auth, history, queue, storedFocusId, storedTargetDir] = await Promise.all([
    TrainerCapture.loadAuth(),
    TrainerCapture.loadHistory(),
    TrainerCapture.loadQueue(),
    TrainerCapture.loadFocusId(),
    TrainerCapture.loadTargetDir()
  ]);
  if (!auth.credential || !auth.baseUrl) {
    const auto = await ensureAutoPair({ force: true });
    if (auto.ok) {
      auth = auto.auth;
    }
  }

  // A right-click download carries no folder of its own: it uses the folder the
  // popup last saved. Resolve it *before* the dedup key, so a menu download and
  // a popup download of the same file into the same folder share one identity.
  if (download && !normalizedTarget.targetDir) {
    normalizedTarget.targetDir = storedTargetDir || TrainerCapture.DEFAULT_TARGET_DIR;
  }
  const dedupKey = trainerDedupKey(normalizedTarget);
  const focusId =
    target.focusId !== undefined && target.focusId !== null
      ? String(target.focusId)
      : storedFocusId;
  const clientCaptureId = TrainerCapture.createClientCaptureId();

  const label = TrainerCapture.captureLabel(normalizedTarget) || url;
  // Only the pending queue may short-circuit locally: a past SUCCESS record
  // must not impersonate this capture, because the resource may have been
  // deleted or the user may want a fresh download (T-0011). The server owns
  // existence/dedupe and answers with the real result.
  const duplicate = TrainerCapture.findLocalDuplicate({ history: [], queue }, dedupKey);
  if (duplicate && duplicate.where === "queue") {
    const deepLink =
      duplicate.entry.deepLink || TrainerCapture.buildDeepLink(duplicate.entry.resourceId);
    const savedPath = duplicate.entry.savedPath || '';
    let message;
    if (download && savedPath) {
      message = TrainerCapture.formatCopy(copy.captureDownloadedDeduped, { path: savedPath });
    } else if (duplicate.where === 'queue') {
      message = TrainerCapture.formatCopy(copy.captureDuplicateQueued, { title: label });
    } else {
      message = TrainerCapture.formatCopy(copy.captureDuplicateLocal, { title: label });
    }
    if (settings.notify !== false) {
      await notifyResult(download ? copy.notifyDownloadTitle : copy.notifyLibraryTitle, message, deepLink);
    }
    return {
      status: duplicate.where === 'queue' ? 'queued' : 'duplicate-local',
      message,
      deepLink,
      resourceId: duplicate.entry.resourceId || ''
    };
  }

  if (!auth.credential || !auth.baseUrl) {
    // Zero-code onboarding: a capture taken before Trainer is reachable is
    // queued, never rejected. The queue item carries no workspace yet; the
    // sidecar binds it to whichever workspace auto-pairs first.
    const item = TrainerCapture.createQueueItem({
      url,
      kind,
      title: normalizedTarget.title,
      selection: normalizedTarget.selection,
      focusId,
      includeDocs: normalizedTarget.includeDocs,
      download: normalizedTarget.download,
      targetDir: normalizedTarget.targetDir,
      clientCaptureId,
      workspaceId: auth.workspaceId || ''
    });
    const enqueued = await withQueueLock(async () => {
      const fresh = await TrainerCapture.loadQueue();
      const next = TrainerCapture.enqueueCapture(fresh, item, TrainerCapture.LIMITS.queue);
      if (!next.rejectedFull) {
        await TrainerCapture.saveQueue(next.queue);
      }
      return next;
    });
    if (enqueued.rejectedFull) {
      const message = TrainerCapture.formatCopy(copy.captureQueueFull, {});
      if (settings.notify !== false) {
        await notifyResult(copy.notifyFailedTitle, message, '');
      }
      await updateBadge();
      return { status: 'failed', message, deepLink: '' };
    }
    const queueMessage = TrainerCapture.formatCopy(
      download ? copy.captureDownloadQueued : copy.captureQueued,
      { count: enqueued.queue.length }
    );
    await TrainerCapture.recordHistory(
      buildHistoryEntry(normalizedTarget, 'queued', queueMessage, null)
    );
    await recordConnection('offline');
    if (settings.notify !== false) {
      await notifyResult(
        download ? copy.notifyDownloadTitle : copy.notifyQueuedTitle,
        queueMessage,
        ''
      );
    }
    await updateBadge();
    return { status: 'queued', message: queueMessage, queueLength: enqueued.queue.length };
  }

  const payload = TrainerCapture.buildCapturePayload({
    url,
    kind,
    title: normalizedTarget.title,
    selection: normalizedTarget.selection,
    focusId,
    includeDocs: normalizedTarget.includeDocs,
    download: normalizedTarget.download,
    targetDir: normalizedTarget.targetDir,
    clientCaptureId,
    workspaceId: auth.workspaceId
  });

  if (settings.notify !== false) {
    await notifyResult(
      download ? copy.notifyDownloadTitle : copy.notifyLibraryTitle,
      download ? copy.downloadBusy : copy.notifyPending,
      ''
    );
  }

  const response = await sendCaptureWithRecovery(payload, auth);

  if (response.ok) {
    const status = response.deduped ? 'duplicated' : 'ok';
    const savedPath = response.savedPath || '';
    const message =
      download && savedPath
        ? TrainerCapture.formatCopy(
            response.deduped ? copy.captureDownloadedDeduped : copy.captureDownloaded,
            { path: savedPath }
          )
        : TrainerCapture.formatCopy(
            response.deduped ? copy.captureDeduped : copy.captureSuccess,
            { title: label }
          );
    await TrainerCapture.recordHistory(
      buildHistoryEntry(normalizedTarget, status, message, response)
    );
    await TrainerCapture.clearNotice();
    await recordConnection('ok');
    if (settings.notify !== false) {
      // A completed download names the saved path and offers the deep link
      // back into VS Code (clicking the notification opens it).
      const body = download && savedPath ? `${message}\n${copy.openInVsCode}` : message;
      await notifyResult(download ? copy.notifyDownloadTitle : copy.notifyLibraryTitle, body, response.deepLink);
    }
    await updateBadge();
    return {
      status,
      message,
      deepLink: response.deepLink,
      resourceId: response.resourceId,
      savedPath,
      deduped: response.deduped
    };
  }

  if (response.unauthorized) {
    // The sidecar may have been reset or re-paired while this browser kept the
    // old credential. Drop it so the next flush auto-pairs again, and keep the
    // capture instead of losing it to a stale token.
    await TrainerCapture.clearAuth();
    resetAutoPairCache();
  }

  if (!response.retryable && !response.unauthorized) {
    // Permanent failure (e.g. network-disabled workspace, read-only workspace):
    // record it and never queue it.
    const message = TrainerCapture.formatCopy(copy.captureFailed, { message: response.message });
    await TrainerCapture.recordHistory(buildHistoryEntry(normalizedTarget, 'failed', message, null));
    await recordConnection('ok');
    if (settings.notify !== false) {
      await notifyResult(copy.notifyFailedTitle, message, '');
    }
    await updateBadge();
    return { status: 'failed', message, deepLink: '' };
  }

  // Transient failure (offline / timeout / 5xx): queue for automatic delivery.
  const item = TrainerCapture.createQueueItem({
    url,
    kind,
    title: normalizedTarget.title,
    selection: normalizedTarget.selection,
    focusId,
    includeDocs: normalizedTarget.includeDocs,
    download: normalizedTarget.download,
    targetDir: normalizedTarget.targetDir,
    clientCaptureId,
    workspaceId: auth.workspaceId
  });
  // Re-read and persist under the lock: a save after the lock releases lets a
  // concurrent capture/flush read stale state and erase the just-enqueued item.
  const enqueued = await withQueueLock(async () => {
    const fresh = await TrainerCapture.loadQueue();
    const next = TrainerCapture.enqueueCapture(fresh, item, TrainerCapture.LIMITS.queue);
    if (!next.rejectedFull) {
      await TrainerCapture.saveQueue(next.queue);
    }
    return next;
  });
  if (enqueued.rejectedFull) {
    const message = TrainerCapture.formatCopy(copy.captureQueueFull, {});
    if (settings.notify !== false) {
      await notifyResult(copy.notifyFailedTitle, message, '');
    }
    await updateBadge();
    return { status: 'failed', message, deepLink: '' };
  }
  const queueMessage = TrainerCapture.formatCopy(
    download ? copy.captureDownloadQueued : copy.captureQueued,
    { count: enqueued.queue.length }
  );
  await TrainerCapture.recordHistory(
    buildHistoryEntry(normalizedTarget, 'queued', queueMessage, null)
  );
  // A 5xx/timeout means "reachable but did not finish", not "Trainer is gone".
  await recordConnection(response.status ? 'ok' : 'offline');
  await updateBadge();

  if (settings.notify !== false) {
    await notifyResult(
      download ? copy.notifyDownloadTitle : copy.notifyQueuedTitle,
      queueMessage,
      ''
    );
  }
  return { status: 'queued', message: queueMessage, queueLength: enqueued.queue.length };
}

// ------------------------------------------------------------ queue flush --

async function flushQueue(options) {
  // Serialized against captures so items added while a flush runs are never
  // overwritten by the flush's final save.
  return withQueueLock(() => flushQueueLocked(options));
}

async function flushQueueLocked(options) {
  const settings = options || {};
  const copy = dict();
  let auth = await TrainerCapture.loadAuth();
  if (!auth.credential || !auth.baseUrl) {
    const auto = await ensureAutoPair();
    if (auto.ok) {
      auth = auto.auth;
    }
  }
  let queue = await TrainerCapture.loadQueue();
  let drafts = await TrainerCapture.loadDraftQueue();
  const pending = () => queue.length + drafts.length;

  if (!auth.credential || !auth.baseUrl) {
    return {
      ok: false,
      flushed: 0,
      remaining: pending(),
      reason: 'unpaired',
      message: copy.queueUnpaired
    };
  }
  if (!pending()) {
    await updateBadge();
    return { ok: true, flushed: 0, remaining: 0, message: copy.queueEmpty };
  }

  let flushed = 0;
  let lastError = '';
  let lastStatus = 0;
  let stop = false;
  const savedPaths = [];

  // Captures and downloads first.
  while (queue.length && !stop) {
    const item = TrainerCapture.takeNextQueueItem(queue);
    if (item.workspaceId && auth.workspaceId && item.workspaceId !== auth.workspaceId) {
      await TrainerCapture.saveNotice(copy.queueWorkspaceChanged);
      queue = TrainerCapture.markQueueAttempt(
        queue,
        item.clientCaptureId,
        copy.queueWorkspaceChanged
      );
      lastError = copy.queueWorkspaceChanged;
      lastStatus = 0;
      stop = true;
      break;
    }
    const payload = TrainerCapture.buildCapturePayload(item);
    const response = await sendCaptureWithRecovery(payload, auth);

    if (response.ok) {
      queue = TrainerCapture.dequeueCapture(queue, item.clientCaptureId);
      flushed += 1;
      const status = response.deduped ? 'duplicated' : 'ok';
      const itemLabel = TrainerCapture.captureLabel(item) || item.url;
      const message =
        item.download === true && response.savedPath
          ? TrainerCapture.formatCopy(
              response.deduped ? copy.captureDownloadedDeduped : copy.captureDownloaded,
              { path: response.savedPath }
            )
          : TrainerCapture.formatCopy(
              response.deduped ? copy.captureDeduped : copy.captureSuccess,
              { title: itemLabel }
            );
      if (item.download === true && response.savedPath) {
        savedPaths.push(response.savedPath);
      }
      await TrainerCapture.recordHistory(
        buildHistoryEntry(
          {
            url: item.url,
            kind: item.kind,
            title: item.title,
            includeDocs: item.includeDocs,
            download: item.download,
            targetDir: item.targetDir
          },
          status,
          message,
          response
        )
      );
      continue;
    }

    if (response.retryable) {
      queue = TrainerCapture.markQueueAttempt(queue, item.clientCaptureId, response.message);
      lastError = response.message;
      lastStatus = Number(response.status) || 0;
      stop = true;
      break;
    }

    if (response.unauthorized) {
      const recoveredBaseUrl = await findPairedBaseUrl(auth);
      if (recoveredBaseUrl && recoveredBaseUrl !== auth.baseUrl) {
        await TrainerCapture.saveAuth(recoveredBaseUrl, auth.credential);
        auth = { ...auth, baseUrl: recoveredBaseUrl };
        queue = TrainerCapture.markQueueAttempt(queue, item.clientCaptureId, response.message);
        continue;
      }
      await TrainerCapture.saveNotice(response.message || copy.errUnauthorized);
      // A stale credential must not wedge the queue: clear it so the next
      // flush auto-pairs again, and keep the item for that retry.
      await TrainerCapture.clearAuth();
      resetAutoPairCache();
      await recordConnection('offline');
      queue = TrainerCapture.markQueueAttempt(queue, item.clientCaptureId, response.message);
      lastError = response.message;
      lastStatus = 0;
      stop = true;
      break;
    }

    // Permanent failure: drop the item so the queue cannot wedge forever.
    queue = TrainerCapture.dequeueCapture(queue, item.clientCaptureId);
    const message = TrainerCapture.formatCopy(copy.captureFailed, { message: response.message });
    await TrainerCapture.recordHistory(
      buildHistoryEntry(
        {
          url: item.url,
          kind: item.kind,
          title: item.title,
          includeDocs: item.includeDocs,
          download: item.download,
          targetDir: item.targetDir
        },
        'failed',
        message,
        null
      )
    );
  }

  // Coach drafts (selections) follow captures, same workspace fence.
  while (drafts.length && !stop) {
    const draft = TrainerCapture.takeNextDraft(drafts);
    if (draft.workspaceId && auth.workspaceId && draft.workspaceId !== auth.workspaceId) {
      await TrainerCapture.saveNotice(copy.queueWorkspaceChanged);
      drafts = TrainerCapture.markDraftAttempt(
        drafts,
        draft.clientDraftId,
        copy.queueWorkspaceChanged
      );
      lastError = copy.queueWorkspaceChanged;
      lastStatus = 0;
      stop = true;
      break;
    }
    const payload = TrainerCapture.buildCoachDraftPayload({
      selection: draft.selection,
      url: draft.url,
      title: draft.title,
      clientId: draft.clientDraftId
    });
    const result = await TrainerCapture.sendCoachDraft(auth.baseUrl, auth.credential, payload);
    if (result.ok) {
      drafts = TrainerCapture.dequeueDraft(drafts, draft.clientDraftId);
      flushed += 1;
      await TrainerCapture.recordHistory(
        buildHistoryEntry(
          {
            url: draft.url,
            kind: 'web',
            title: draft.title || draft.selection.slice(0, 60)
          },
          'ok',
          copy.coachSent,
          null
        )
      );
      continue;
    }
    if (result.unauthorized) {
      await TrainerCapture.clearAuth();
      resetAutoPairCache();
      drafts = TrainerCapture.markDraftAttempt(
        drafts,
        draft.clientDraftId,
        result.message
      );
      lastError = result.message;
      lastStatus = 0;
      stop = true;
      break;
    }
    if (result.status && result.status !== 429 && !TrainerCapture.isRetryableStatus(result.status)) {
      drafts = TrainerCapture.dequeueDraft(drafts, draft.clientDraftId);
      const message = TrainerCapture.formatCopy(copy.coachFailed, { message: result.message });
      await TrainerCapture.recordHistory(
        buildHistoryEntry(
          {
            url: draft.url,
            kind: 'web',
            title: draft.title || draft.selection.slice(0, 60)
          },
          'failed',
          message,
          null
        )
      );
      continue;
    }
    drafts = TrainerCapture.markDraftAttempt(
      drafts,
      draft.clientDraftId,
      result.message
    );
    lastError = result.message;
    lastStatus = Number(result.status) || 0;
    stop = true;
  }

  await TrainerCapture.saveQueue(queue);
  await TrainerCapture.saveDraftQueue(drafts);
  await updateBadge();

  if (flushed > 0) {
    await recordConnection('ok');
    let message = TrainerCapture.formatCopy(copy.queueFlushed, { count: flushed });
    if (savedPaths.length === 1) {
      message = `${message}\n${TrainerCapture.formatCopy(copy.captureDownloaded, { path: savedPaths[0] })}`;
    }
    if (settings.notify !== false) {
      await notifyResult(copy.notifyQueueDoneTitle, message, '');
    }
    return { ok: true, flushed, remaining: pending(), message };
  }
  if (lastError) {
    await recordConnection(lastStatus ? 'ok' : 'offline');
    return {
      ok: false,
      flushed: 0,
      remaining: pending(),
      reason: 'offline',
      message: lastError || copy.queueOffline
    };
  }
  return { ok: true, flushed: 0, remaining: pending(), message: copy.queueNothing };
}

// ------------------------------------------------------------- state/UI ----

let autoPairPromise = null;
let lastAutoPairAt = 0;
let lastAutoPairResult = null;

function resetAutoPairCache() {
  lastAutoPairAt = 0;
  lastAutoPairResult = null;
}

/**
 * Zero-code connection: discover the loopback sidecar and let it mint a
 * workspace-bound credential. The popup never asks for a pair code, port or
 * token. A failed probe is cached for a few seconds so opening the popup does
 * not rescan the whole managed port range twice.
 */
async function ensureAutoPair(options) {
  const force = Boolean(options && options.force);
  if (autoPairPromise) {
    return autoPairPromise;
  }
  const now = Date.now();
  if (!force && lastAutoPairResult && now - lastAutoPairAt < 5000) {
    return lastAutoPairResult;
  }
  autoPairPromise = (async () => {
    const existing = await TrainerCapture.loadAuth();
    if (existing.credential && existing.baseUrl) {
      return { ok: true, auth: existing };
    }
    const disabled = await chrome.storage.local.get({
      [TrainerCapture.STORAGE_KEYS.autoPairDisabled]: false
    });
    if (!force && disabled[TrainerCapture.STORAGE_KEYS.autoPairDisabled]) {
      return { ok: false, disabled: true };
    }
    const discovered = await TrainerCapture.discoverSidecar({});
    for (const baseUrl of discovered.baseUrls || []) {
      const paired = await TrainerCapture.autoPairSidecar(baseUrl);
      if (paired.ok) {
        const saved = await TrainerCapture.saveAuth(
          paired.baseUrl,
          paired.credential,
          paired.workspaceId
        );
        await TrainerCapture.saveWorkspaceName(paired.workspaceName);
        await chrome.storage.local.set({
          [TrainerCapture.STORAGE_KEYS.autoPairDisabled]: false
        });
        await recordConnection('ok');
        return {
          ok: true,
          auth: { ...saved, workspaceName: paired.workspaceName }
        };
      }
    }
    await recordConnection('offline');
    return { ok: false, message: dict().autoPairFailed };
  })()
    .then((result) => {
      lastAutoPairAt = Date.now();
      lastAutoPairResult = result;
      return result;
    })
    .finally(() => {
      autoPairPromise = null;
    });
  return autoPairPromise;
}

async function buildState() {
  let auth = await TrainerCapture.loadAuth();
  if (!auth.credential || !auth.baseUrl) {
    const auto = await ensureAutoPair();
    if (auto.ok) {
      auth = auto.auth;
    }
  }
  const [cached, queue, drafts, history, focusId, targetDir, notice, connection, storedWorkspaceName] =
    await Promise.all([
      TrainerCapture.loadStatusCache(),
      TrainerCapture.loadQueue(),
      TrainerCapture.loadDraftQueue(),
      TrainerCapture.loadHistory(),
      TrainerCapture.loadFocusId(),
      TrainerCapture.loadTargetDir(),
      TrainerCapture.loadNotice(),
      TrainerCapture.loadConnection(),
      TrainerCapture.loadWorkspaceName()
    ]);
  const disabledState = await chrome.storage.local.get({
    [TrainerCapture.STORAGE_KEYS.autoPairDisabled]: false
  });
  const autoPairDisabled = Boolean(
    disabledState[TrainerCapture.STORAGE_KEYS.autoPairDisabled]
  );
  const paired = Boolean(auth.credential && auth.baseUrl);
  return {
    paired,
    autoPairDisabled,
    // 'connected' is only asserted from an actual sidecar answer.
    connected: paired && connection === 'ok',
    offline: !paired || connection === 'offline',
    baseUrl: auth.baseUrl,
    workspaceName:
      auth.workspaceName ||
      (cached && cached.workspaceName) ||
      storedWorkspaceName ||
      '',
    libraryCount: cached.libraryCount,
    focusOptions: cached.focusOptions,
    focusId,
    targetDir: targetDir || TrainerCapture.DEFAULT_TARGET_DIR,
    queueCount: queue.length + drafts.length,
    queue: queue.slice(),
    drafts: drafts.slice(),
    history: history.slice(0, TrainerCapture.LIMITS.historyDisplay),
    notice
  };
}

/**
 * Find another reachable Trainer window that accepts this extension's stored
 * credential. A second VS Code window answers /health too, but it will reject
 * a credential minted by a sibling instance (401) — switching to it blindly
 * turns a real "Trainer is offline" case into "credential invalid".
 */
async function findPairedBaseUrl(auth) {
  const rediscovered = await TrainerCapture.discoverSidecar({ storedBaseUrl: auth.baseUrl });
  const candidates = Array.isArray(rediscovered.baseUrls) && rediscovered.baseUrls.length
    ? rediscovered.baseUrls
    : (rediscovered.baseUrl ? [rediscovered.baseUrl] : []);
  for (const baseUrl of candidates) {
    if (!baseUrl || baseUrl === auth.baseUrl) continue;
    const probe = await TrainerCapture.fetchStatus(baseUrl, auth.credential);
    if (probe.ok) return baseUrl;
  }
  return '';
}

async function fetchStatusWithRecovery(auth) {
  let result = await TrainerCapture.fetchStatus(auth.baseUrl, auth.credential);
  if (result.ok) {
    return result;
  }
  // A 401 is "reachable, wrong identity": another window may own this port.
  // Only switching to an instance that validates the credential counts.
  if (result.unauthorized) {
    const recoveredBaseUrl = await findPairedBaseUrl(auth);
    if (recoveredBaseUrl && recoveredBaseUrl !== auth.baseUrl) {
      await TrainerCapture.saveAuth(recoveredBaseUrl, auth.credential);
      return TrainerCapture.fetchStatus(recoveredBaseUrl, auth.credential);
    }
    return result;
  }
  if (!result.transportError) {
    return result;
  }
  const recoveredBaseUrl = await findPairedBaseUrl(auth);
  if (!recoveredBaseUrl) {
    return result;
  }
  await TrainerCapture.saveAuth(recoveredBaseUrl, auth.credential);
  result = await TrainerCapture.fetchStatus(recoveredBaseUrl, auth.credential);
  return result;
}

async function refreshState() {
  let auth = await TrainerCapture.loadAuth();
  if (!auth.credential || !auth.baseUrl) {
    const auto = await ensureAutoPair();
    if (auto.ok) {
      auth = auto.auth;
    }
  }
  if (!auth.credential || !auth.baseUrl) {
    await recordConnection('offline');
    await updateBadge();
    return buildState();
  }
  const result = await fetchStatusWithRecovery(auth);
  if (result.ok) {
    await TrainerCapture.saveStatusCache(result.status);
    // Keep the pinned identity in sync with the instance that actually
    // accepted the credential (T-0008): a re-pair or migration updates it.
    const authoritativeWorkspaceId = String(
      (result.status && result.status.workspaceId) || ''
    ).trim();
    if (authoritativeWorkspaceId && authoritativeWorkspaceId !== auth.workspaceId) {
      await TrainerCapture.saveAuth(auth.baseUrl, auth.credential, authoritativeWorkspaceId);
    }
    await TrainerCapture.clearNotice();
    await recordConnection('ok');
  } else if (result.unauthorized) {
    // Trainer answered, the credential did not: running, just not usable.
    await TrainerCapture.saveNotice(result.message);
    await recordConnection('ok');
  } else {
    await recordConnection('offline');
  }
  await flushQueue({ notify: true });
  return buildState();
}

// --------------------------------------------------------------- actions ----

async function activeTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs && tabs.length ? tabs[0] : null;
}

async function captureActiveTab(settings) {
  const options = settings || {};
  const copy = dict();
  const tab = await activeTab();
  const url = tab && tab.url ? String(tab.url).trim() : '';
  if (!TrainerCapture.httpUrlOnly(url)) {
    const message = copy.captureNoUrl;
    await notifyResult(copy.notifyFailedTitle, message, '');
    return { status: 'failed', message, deepLink: '' };
  }
  const kind = TrainerCapture.detectKind(url);
  const download = options.download === true;
  if (download && !TrainerCapture.supportsDownload(kind)) {
    const message = copy.downloadUnsupported;
    await notifyResult(copy.notifyFailedTitle, message, '');
    return { status: 'failed', message, deepLink: '' };
  }
  return runCapture({
    url,
    kind,
    title: tab && tab.title ? String(tab.title).trim() : '',
    download,
    targetDir: download ? String(options.targetDir || '') : ''
  });
}

async function revokePairing() {
  const auth = await TrainerCapture.loadAuth();
  let remote = { ok: false };
  if (auth.baseUrl && auth.credential) {
    remote = await TrainerCapture.revokePairing(auth.baseUrl, auth.credential);
  }
  await TrainerCapture.clearAuth();
  resetAutoPairCache();
  await chrome.storage.local.set({
    [TrainerCapture.STORAGE_KEYS.autoPairDisabled]: true
  });
  // Pending captures cannot be delivered without a credential; drop them so
  // the badge does not keep counting forever after an explicit revoke, and
  // clear the local capture records so a later re-capture is not short-
  // circuited by the client-side duplicate hint.
  // Queue mutations serialize with capture/flush (T-0041): a lockless save
  // here would erase a capture enqueued while revoke was running.
  await withQueueLock(async () => {
    await TrainerCapture.saveQueue([]);
    await TrainerCapture.saveDraftQueue([]);
  });
  await TrainerCapture.clearHistory();
  await recordConnection('unknown');
  await updateBadge();
  const message = remote.ok ? dict().pairRevokeDone : dict().pairRevokeLocalOnly;
  return { ok: true, remoteOk: remote.ok, message };
}

/** Queue manager: drop one pending capture (task 三). */
async function removeQueueEntry(clientCaptureId) {
  const id = String(clientCaptureId || '').trim();
  if (!id) {
    return { ok: false, message: dict().queueNothing };
  }
  const next = await withQueueLock(async () => {
    const queue = TrainerCapture.removeQueueItem(await TrainerCapture.loadQueue(), id);
    const drafts = TrainerCapture.dequeueDraft(await TrainerCapture.loadDraftQueue(), id);
    await TrainerCapture.saveQueue(queue);
    await TrainerCapture.saveDraftQueue(drafts);
    return { queue, drafts };
  });
  await updateBadge();
  return {
    ok: true,
    remaining: next.queue.length + next.drafts.length,
    state: await buildState()
  };
}

async function clearQueueEntries() {
  await withQueueLock(async () => {
    await TrainerCapture.saveQueue([]);
    await TrainerCapture.saveDraftQueue([]);
  });
  await updateBadge();
  return { ok: true, remaining: 0, state: await buildState() };
}

async function coachDraft(info, tab) {
  const copy = dict();
  const selection = String(info.selectionText || '').trim();
  if (!selection) {
    await notifyResult(copy.notifyDraftTitle, copy.coachEmptySelection, '');
    return { status: 'failed', message: copy.coachEmptySelection };
  }
  let auth = await TrainerCapture.loadAuth();
  if (!auth.credential || !auth.baseUrl) {
    const auto = await ensureAutoPair({ force: true });
    if (auto.ok) {
      auth = auto.auth;
    }
  }
  const payload = TrainerCapture.buildCoachDraftPayload({
    selection,
    url: String(info.pageUrl || (tab && tab.url) || ''),
    title: tab && tab.title ? String(tab.title) : '',
    clientId: TrainerCapture.createCoachDraftId()
  });

  if (!auth.credential || !auth.baseUrl) {
    const item = TrainerCapture.createDraftQueueItem({
      selection,
      url: payload.url,
      title: payload.title,
      workspaceId: auth.workspaceId || ''
    });
    const enqueued = await withQueueLock(async () => {
      const fresh = await TrainerCapture.loadDraftQueue();
      const next = TrainerCapture.enqueueDraft(fresh, item, TrainerCapture.LIMITS.queue);
      if (!next.rejectedFull) {
        await TrainerCapture.saveDraftQueue(next.queue);
      }
      return next;
    });
    if (enqueued.rejectedFull) {
      const message = copy.coachQueueFull;
      await notifyResult(copy.notifyDraftTitle, message, '');
      await updateBadge();
      return { status: 'failed', message };
    }
    const message = TrainerCapture.formatCopy(copy.coachQueued, {
      count: enqueued.queue.length
    });
    await notifyResult(copy.notifyDraftTitle, message, '');
    await updateBadge();
    return { status: 'queued', message, queueLength: enqueued.queue.length };
  }

  const result = await TrainerCapture.sendCoachDraft(auth.baseUrl, auth.credential, payload);
  if (result.ok) {
    await notifyResult(copy.notifyDraftTitle, copy.coachSent, TrainerCapture.HOST_DEEP_LINK);
    return { status: 'sent', message: copy.coachSent };
  }

  // Transport failures, 429 (host draft queue full), 5xx and a stale
  // credential are transient: keep the selection locally, drop the credential
  // so the next flush auto-pairs again, and retry on the next alarm/popup.
  const retryable =
    !result.status ||
    result.status === 429 ||
    result.unauthorized ||
    TrainerCapture.isRetryableStatus(result.status);
  if (retryable) {
    if (result.unauthorized) {
      await TrainerCapture.clearAuth();
      resetAutoPairCache();
    }
    const item = TrainerCapture.createDraftQueueItem({
      selection,
      url: payload.url,
      title: payload.title,
      workspaceId: auth.workspaceId || ''
    });
    const enqueued = await withQueueLock(async () => {
      const fresh = await TrainerCapture.loadDraftQueue();
      const next = TrainerCapture.enqueueDraft(fresh, item, TrainerCapture.LIMITS.queue);
      if (!next.rejectedFull) {
        await TrainerCapture.saveDraftQueue(next.queue);
      }
      return next;
    });
    if (enqueued.rejectedFull) {
      const message = copy.coachQueueFull;
      await notifyResult(copy.notifyDraftTitle, message, '');
      await updateBadge();
      return { status: 'failed', message };
    }
    const message = TrainerCapture.formatCopy(copy.coachQueued, {
      count: enqueued.queue.length
    });
    await notifyResult(copy.notifyDraftTitle, message, '');
    await updateBadge();
    return { status: 'queued', message, queueLength: enqueued.queue.length };
  }

  const message = TrainerCapture.formatCopy(copy.coachFailed, { message: result.message });
  await notifyResult(copy.notifyDraftTitle, message, '');
  return { status: 'failed', message };
}

async function handleMenuClick(info, tab) {
  const menuId = String(info.menuItemId || '');
  if (menuId === MENU_IDS.selectionCoach) {
    await coachDraft(info, tab);
    return;
  }
  const target = resolveCaptureTarget(menuId, info, tab);
  if (!target) {
    await notifyResult(dict().notifyFailedTitle, dict().captureNoUrl, '');
    return;
  }
  if (target.invalid === 'github') {
    await notifyResult(dict().notifyFailedTitle, dict().captureGithubNeedsRepo, '');
    return;
  }
  await runCapture(target);
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  void handleMenuClick(info, tab);
});

// -------------------------------------------------------------- messages ----

const MESSAGE_HANDLERS = {
  'trainer:state': async () => buildState(),
  'trainer:auto-pair': async () => {
    await chrome.storage.local.set({
      [TrainerCapture.STORAGE_KEYS.autoPairDisabled]: false
    });
    lastAutoPairAt = 0;
    lastAutoPairResult = null;
    const result = await ensureAutoPair({ force: true });
    return { ok: result.ok, message: result.message || '', state: await buildState() };
  },
  'trainer:refresh': async () => ({ ok: true, state: await refreshState() }),
  'trainer:capture-tab': async (message) =>
    captureActiveTab({
      download: message && message.download === true,
      targetDir: message && message.targetDir ? message.targetDir : ''
    }),
  'trainer:capture': async (message) => {
    const kind = message.kind || TrainerCapture.detectKind(message.url);
    const download = message.download === true && TrainerCapture.supportsDownload(kind);
    return runCapture({
      url: message.url,
      kind,
      title: message.title || '',
      includeDocs: message.includeDocs === true,
      download,
      targetDir: download ? String(message.targetDir || '') : ''
    });
  },
  'trainer:flush': async () => {
    const result = await flushQueue({ notify: true });
    return Object.assign({}, result, { state: await buildState() });
  },
  'trainer:queue-remove': async (message) => removeQueueEntry(message && message.clientCaptureId),
  'trainer:queue-clear': async () => clearQueueEntries(),
  'trainer:revoke': async () => revokePairing(),
  'trainer:set-focus': async (message) => {
    const focusId = await TrainerCapture.saveFocusId(message.focusId);
    return { ok: true, focusId };
  },
  'trainer:set-target-dir': async (message) => {
    const raw = message && message.targetDir !== undefined ? String(message.targetDir) : '';
    if (!TrainerCapture.targetDirIsValid(raw)) {
      return { ok: false, invalid: true, message: dict().downloadInvalidFolder };
    }
    const targetDir = await TrainerCapture.saveTargetDir(raw);
    return { ok: true, targetDir };
  },
  'trainer:open': async (message) => ({ ok: await openDeepLink(message.url) }),
  'trainer:pdf-capture': async (message) =>
    runCapture(
      {
        url: message.url,
        kind: 'pdf',
        title: message.title || ''
      },
      { notify: false }
    )
};

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const type = message && message.type ? String(message.type) : '';
  const handler = MESSAGE_HANDLERS[type];
  if (!handler) {
    sendResponse({ ok: false, message: `Unknown Trainer Capture message: ${type}` });
    return false;
  }
  Promise.resolve()
    .then(() => handler(message, sender))
    .then((result) => sendResponse(result))
    .catch((error) => {
      console.warn('Trainer Capture message failed:', error);
      sendResponse({ ok: false, status: 'failed', message: String((error && error.message) || error) });
    });
  return true;
});

// ------------------------------------------------------- lifecycle/alarms ---

async function ensureAlarm() {
  const existing = await chrome.alarms.get(FLUSH_ALARM);
  if (!existing) {
    chrome.alarms.create(FLUSH_ALARM, {
      delayInMinutes: FLUSH_PERIOD_MINUTES,
      periodInMinutes: FLUSH_PERIOD_MINUTES
    });
  }
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm && alarm.name === FLUSH_ALARM) {
    void flushQueue({ notify: true });
  }
});

chrome.runtime.onInstalled.addListener(() => {
  void ensureMenus();
  void ensureAlarm();
  void flushQueue({ notify: true });
  void updateBadge();
});

chrome.runtime.onStartup.addListener(() => {
  void ensureMenus();
  void ensureAlarm();
  // Connect (or re-connect) as soon as the browser starts; a queued capture
  // should not wait for the first alarm tick when Trainer is already open.
  void flushQueue({ notify: true });
  void updateBadge();
});

// Cold-start safety: a service worker can spin up long after profile startup,
// so make sure the periodic flush and the badge state exist either way.
void ensureAlarm();
void updateBadge();
