'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

function decodeHtmlEntities(value) {
  return String(value)
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&semi;/g, ';');
}

function createDocumentShim() {
  function createEventTarget() {
    return {
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() {
        return false;
      },
    };
  }

  function createContainerShim() {
    const target = createEventTarget();
    const children = [];
    return {
      style: {},
      children,
      appendChild(child) {
        children.push(child);
        return child;
      },
      removeChild(child) {
        const index = children.indexOf(child);
        if (index >= 0) {
          children.splice(index, 1);
        }
        return child;
      },
      insertBefore(child, beforeChild) {
        const beforeIndex = children.indexOf(beforeChild);
        if (beforeIndex >= 0) {
          children.splice(beforeIndex, 0, child);
        } else {
          children.push(child);
        }
        return child;
      },
      querySelector() {
        return null;
      },
      querySelectorAll() {
        return [];
      },
      ...target,
    };
  }

  const documentShim = {
    _rootElement: undefined,
    compatMode: 'CSS1Compat',
    doctype: {
      name: 'html',
    },
    documentElement: createContainerShim(),
    body: createContainerShim(),
    head: createContainerShim(),
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return false;
    },
    getElementById() {
      if (!this._rootElement) {
        this._rootElement = this.createElement('div');
        this._rootElement.id = 'root';
      }
      return this._rootElement;
    },
    getElementsByTagName() {
      return [];
    },
    getElementsByClassName() {
      return [];
    },
    createElement(tagName) {
      let html = '';
      const node = {
        nodeType: 1,
        nodeName: String(tagName).toUpperCase(),
        tagName: String(tagName).toUpperCase(),
        ownerDocument: documentShim,
        namespaceURI: 'http://www.w3.org/1999/xhtml',
        style: {},
        attributes: [],
        children: [],
        ...createEventTarget(),
        content:
          String(tagName).toLowerCase() === 'template'
            ? {
                children: [],
              }
            : undefined,
        appendChild(child) {
          this.children.push(child);
          return child;
        },
        replaceWith() {},
        removeAttribute() {},
        setAttribute() {},
        getAttribute() {
          return null;
        },
        getAttributeNames() {
          return [];
        },
        cloneNode() {
          return documentShim.createElement(tagName);
        },
        get firstChild() {
          return this.children[0];
        },
        get childNodes() {
          return this.children;
        },
        get innerHTML() {
          return html;
        },
        set innerHTML(value) {
          html = String(value ?? '');
          if (this.content) {
            this.content.children = [];
          }
        },
        get textContent() {
          return decodeHtmlEntities(html.replace(/<[^>]*>/g, ''));
        },
        set textContent(value) {
          html = String(value ?? '');
        },
      };
      return node;
    },
    createDocumentFragment() {
      return {
        style: {},
        children: [],
        ...createEventTarget(),
        appendChild(child) {
          this.children.push(child);
          return child;
        },
        replaceWith() {},
        get firstChild() {
          return this.children[0];
        },
        get childNodes() {
          return this.children;
        },
      };
    },
  };
  return documentShim;
}

function createWindowShim() {
  const documentShim = createDocumentShim();
  const localStorageStore = new Map();
  const sessionStorageStore = new Map();
  class NodeShim {}
  class ElementShim extends NodeShim {}
  class HTMLElementShim extends ElementShim {}
  class HTMLIFrameElementShim extends HTMLElementShim {}
  class SVGElementShim extends ElementShim {}
  class DocumentFragmentShim extends NodeShim {}
  class DocumentShim extends NodeShim {}
  class DOMMatrixShim {
    constructor(init = []) {
      this.values = Array.isArray(init) ? [...init] : [];
    }
    multiplySelf() {
      return this;
    }
    translateSelf() {
      return this;
    }
    scaleSelf() {
      return this;
    }
    rotateSelf() {
      return this;
    }
    invertSelf() {
      return this;
    }
  }
  const windowShim = {
    document: documentShim,
    Node: NodeShim,
    Element: ElementShim,
    HTMLElement: HTMLElementShim,
    HTMLIFrameElement: HTMLIFrameElementShim,
    SVGElement: SVGElementShim,
    DocumentFragment: DocumentFragmentShim,
    Document: DocumentShim,
    DOMMatrix: DOMMatrixShim,
    DOMParser: class DOMParser {},
    MutationObserver:
      typeof global.MutationObserver === 'function'
        ? global.MutationObserver
        : class MutationObserver {
            observe() {}
            disconnect() {}
            takeRecords() {
              return [];
            }
          },
    ResizeObserver:
      typeof global.ResizeObserver === 'function'
        ? global.ResizeObserver
        : class ResizeObserver {
            observe() {}
            disconnect() {}
            unobserve() {}
          },
    IntersectionObserver:
      typeof global.IntersectionObserver === 'function'
        ? global.IntersectionObserver
        : class IntersectionObserver {
            observe() {}
            disconnect() {}
            unobserve() {}
            takeRecords() {
              return [];
            }
          },
    fetch: global.fetch,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    queueMicrotask,
    structuredClone: global.structuredClone?.bind(global),
    navigator: { language: 'en-US', userAgent: 'node.js' },
    location: { href: 'http://localhost/' },
    localStorage: {
      getItem(key) {
        return localStorageStore.has(key) ? localStorageStore.get(key) : null;
      },
      setItem(key, value) {
        localStorageStore.set(String(key), String(value));
      },
      removeItem(key) {
        localStorageStore.delete(String(key));
      },
      clear() {
        localStorageStore.clear();
      },
    },
    sessionStorage: {
      getItem(key) {
        return sessionStorageStore.has(key) ? sessionStorageStore.get(key) : null;
      },
      setItem(key, value) {
        sessionStorageStore.set(String(key), String(value));
      },
      removeItem(key) {
        sessionStorageStore.delete(String(key));
      },
      clear() {
        sessionStorageStore.clear();
      },
    },
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return false;
    },
    matchMedia() {
      return {
        matches: false,
        media: '',
        addEventListener() {},
        removeEventListener() {},
      };
    },
    requestAnimationFrame(callback) {
      return setTimeout(() => callback(Date.now()), 0);
    },
    cancelAnimationFrame(handle) {
      clearTimeout(handle);
    },
    getComputedStyle() {
      return {
        lineHeight: '16px',
      };
    },
    CustomEvent:
      typeof global.CustomEvent === 'function'
        ? global.CustomEvent
        : class CustomEvent {
            constructor(type, init = {}) {
              this.type = type;
              this.detail = init.detail;
            }
          },
  };
  windowShim.window = windowShim;
  windowShim.self = windowShim;
  windowShim.top = windowShim;
  documentShim.defaultView = windowShim;
  return windowShim;
}

if (typeof global.window === 'undefined') {
  global.window = createWindowShim();
} else {
  global.window.document ??= createDocumentShim();
  global.window.DOMParser ??= class DOMParser {};
}

global.document = global.window.document;
global.DOMMatrix = global.window.DOMMatrix;
global.DOMParser = global.window.DOMParser;
global.MutationObserver = global.window.MutationObserver;
global.ResizeObserver = global.window.ResizeObserver;
global.IntersectionObserver = global.window.IntersectionObserver;
if (typeof global.window.fetch !== 'function') {
  global.window.fetch = global.fetch;
}

function findBrowserSidecarBundle() {
  const bundle = path.resolve(__dirname, '..', 'webview', 'dist', 'browserSidecar-test.js');
  if (!fs.existsSync(bundle)) {
    throw new Error(`browserSidecar test module was not found at ${bundle}. Build the webview first.`);
  }
  return bundle;
}

function loadBrowserSidecarModule({ fresh = false } = {}) {
  const bundleUrl = pathToFileURL(findBrowserSidecarBundle());
  if (fresh) {
    bundleUrl.searchParams.set('browserPreviewTestReload', `${Date.now()}-${Math.random()}`);
  }
  return import(bundleUrl.href).then((module) => {
    assert.equal(typeof module.browserSidecar, 'object');
    assert.equal(typeof module.browserSidecar.sendBrowserPreviewMessage, 'function');
    assert.equal(typeof module.browserSidecar.ensureBrowserPreviewSession, 'function');
    return module.browserSidecar;
  });
}

const PREVIEW_LAYOUT_STORAGE_KEY = 'trainer:webview';
const PREVIEW_PROVIDER_SECRETS_STORAGE_KEY = 'trainer:webview:preview:provider-secrets';
const PREVIEW_LIVE_SESSION_ID_STORAGE_KEY = 'trainer:webview:preview:live-session-id';

function resetPreviewStorage() {
  global.window.localStorage.clear();
  global.window.sessionStorage.clear();
}

async function seedPreviewProviderState(providerConfig, apiKey) {
  global.window.localStorage.setItem(
    PREVIEW_LAYOUT_STORAGE_KEY,
    JSON.stringify({
      themePreference: 'dark',
      activeView: 'coach',
      composerLanguage: 'en-US',
      composerAnswerMode: 'coach-first',
      teachingStyle: 'guided',
      resourceSearchMode: 'lexical',
      includeCurrentFile: true,
      includeSelection: true,
      includeDiagnostics: true,
      includeRelatedFiles: true,
      contextDetail: 'balanced',
      followCurrentFile: true,
      coachDefaults: {
        memoryScope: 'project',
        workingSetMode: 'balanced',
        reviewCadence: 'steady',
        reviewReminderMode: 'due',
        workspaceMemoryToggles: {
          decisions: true,
          patterns: true,
          resources: true,
        },
      },
      composerDraft: '',
      previewProviderConfig: providerConfig,
    }),
  );

  const module = await loadBrowserSidecarModule();
  if (apiKey !== undefined) {
    await module.saveBrowserPreviewProvider(
      {
        name: providerConfig.name,
        protocol: providerConfig.protocol,
        baseUrl: providerConfig.baseUrl,
        model: providerConfig.model,
        contextWindowTokens: providerConfig.contextWindowTokens,
        maxOutputTokens: providerConfig.maxOutputTokens,
        modelTokenLimits: providerConfig.modelTokenLimits,
        apiKey,
      },
      'session-preview-provider-seed',
    );
  }

  return module;
}

test.beforeEach(async () => {
  resetPreviewStorage();
  delete global.window.__TRAINER_BOOTSTRAP__;
  const module = await loadBrowserSidecarModule();
  if (typeof module.clearBrowserPreviewProvider === 'function') {
    await module.clearBrowserPreviewProvider('session-preview-provider-reset');
  }
});

test('ensureBrowserPreviewSession keeps standalone Preview actions local', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  global.window.__TRAINER_BOOTSTRAP__ = {};
  let fetchCalls = 0;
  global.fetch = async () => {
    fetchCalls += 1;
    throw new Error('Standalone Preview must not require a sidecar session.');
  };

  try {
    const module = await loadBrowserSidecarModule();
    const sessionId = await module.ensureBrowserPreviewSession();

    assert.match(sessionId, /^browser-preview-local-trainer-web-preview-/);
    assert.equal(fetchCalls, 0);
  } finally {
    global.fetch = originalFetch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    delete global.window.__TRAINER_BOOTSTRAP__;
  }
});

test('live browser Preview restores its same-tab session after a module reload', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousBootstrap = global.window.__TRAINER_BOOTSTRAP__;
  const previousSearch = global.window.location.search;
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  delete global.window.__TRAINER_BOOTSTRAP__;
  global.window.location.search = '?live=1&sidecarPort=34892';
  let startRequests = 0;
  global.fetch = async (url) => {
    const href = String(url);
    if (href.endsWith(':34892/health')) {
      return new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (href.endsWith('/session/start')) {
      startRequests += 1;
      return new Response(JSON.stringify({ session_id: 'live-session-after-refresh' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const firstLoad = await loadBrowserSidecarModule({ fresh: true });
    assert.equal(await firstLoad.ensureBrowserPreviewSession(), 'live-session-after-refresh');
    assert.equal(
      global.window.sessionStorage.getItem(PREVIEW_LIVE_SESSION_ID_STORAGE_KEY),
      'live-session-after-refresh',
    );

    const refreshedLoad = await loadBrowserSidecarModule({ fresh: true });
    assert.equal(await refreshedLoad.ensureBrowserPreviewSession(), 'live-session-after-refresh');
    assert.equal(startRequests, 1);
  } finally {
    global.fetch = originalFetch;
    global.window.location.search = previousSearch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    if (previousBootstrap === undefined) {
      delete global.window.__TRAINER_BOOTSTRAP__;
    } else {
      global.window.__TRAINER_BOOTSTRAP__ = previousBootstrap;
    }
  }
});

test('fixture Preview ignores stored live sessions while explicit live sessions keep precedence', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousBootstrap = global.window.__TRAINER_BOOTSTRAP__;
  const previousSearch = global.window.location.search;
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  global.window.sessionStorage.setItem(PREVIEW_LIVE_SESSION_ID_STORAGE_KEY, 'stale-live-session');
  global.window.__TRAINER_BOOTSTRAP__ = {};
  global.fetch = async () => {
    throw new Error('Fixture Preview must not contact a sidecar for sessions.');
  };

  try {
    const fixtureModule = await loadBrowserSidecarModule();
    const fixtureSession = await fixtureModule.ensureBrowserPreviewSession();
    assert.match(fixtureSession, /^browser-preview-local-trainer-web-preview-/);
    assert.equal(
      global.window.sessionStorage.getItem(PREVIEW_LIVE_SESSION_ID_STORAGE_KEY),
      'stale-live-session',
    );

    delete global.window.__TRAINER_BOOTSTRAP__;
    global.window.location.search = '?live=1';
    const liveModule = await loadBrowserSidecarModule({ fresh: true });
    assert.equal(await liveModule.ensureBrowserPreviewSession('explicit-live-session'), 'explicit-live-session');
    assert.equal(
      global.window.sessionStorage.getItem(PREVIEW_LIVE_SESSION_ID_STORAGE_KEY),
      'stale-live-session',
    );
  } finally {
    global.fetch = originalFetch;
    global.window.location.search = previousSearch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    if (previousBootstrap === undefined) {
      delete global.window.__TRAINER_BOOTSTRAP__;
    } else {
      global.window.__TRAINER_BOOTSTRAP__ = previousBootstrap;
    }
  }
});

test('live browser Preview continues when session storage is unavailable', async () => {
  const originalFetch = global.fetch;
  const originalSessionStorage = global.window.sessionStorage;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousBootstrap = global.window.__TRAINER_BOOTSTRAP__;
  const previousSearch = global.window.location.search;
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  delete global.window.__TRAINER_BOOTSTRAP__;
  global.window.location.search = '?live=1&sidecarPort=34892';
  global.window.sessionStorage = {
    getItem() {
      throw new Error('storage blocked');
    },
    setItem() {
      throw new Error('storage blocked');
    },
  };
  global.fetch = async (url) => {
    const href = String(url);
    if (href.endsWith(':34892/health')) {
      return new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (href.endsWith('/session/start')) {
      return new Response(JSON.stringify({ session_id: 'live-session-without-storage' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule({ fresh: true });
    assert.equal(await module.ensureBrowserPreviewSession(), 'live-session-without-storage');
  } finally {
    global.fetch = originalFetch;
    global.window.sessionStorage = originalSessionStorage;
    global.window.location.search = previousSearch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    if (previousBootstrap === undefined) {
      delete global.window.__TRAINER_BOOTSTRAP__;
    } else {
      global.window.__TRAINER_BOOTSTRAP__ = previousBootstrap;
    }
  }
});

test('fixture Preview turns a first Coach goal into a local starter plan and current task', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousBootstrap = global.window.__TRAINER_BOOTSTRAP__;
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  global.window.__TRAINER_BOOTSTRAP__ = { conversation: [] };
  let fetchCalls = 0;
  global.fetch = async () => {
    fetchCalls += 1;
    throw new Error('Fixture Preview must not contact a sidecar for coach messages.');
  };

  try {
    const module = await loadBrowserSidecarModule();
    const firstGoal = 'I have never programmed and want to build a budgeting website in two months.';
    const direct = await module.sendBrowserPreviewMessage(
      {
        text: firstGoal,
        responseLanguage: 'en-US',
      },
      'fixture-coach-session',
    );

    assert.equal(direct.message.type, 'state/patch');
    assert.equal(direct.message.payload.conversation.at(-2).body, firstGoal);
    const directReply = direct.message.payload.conversation.at(-1).body;
    assert.match(directReply, /A local preview plan was created from your current goal/i);
    assert.match(directReply, /Define a first-week outcome/i);
    assert.doesNotMatch(directReply, /current file|function or component/i);
    assert.match(direct.message.payload.task.description, /budgeting website/i);
    assert.match(direct.message.payload.coachFocus.currentFocus, /budgeting website/i);
    assert.equal(direct.message.payload.hasFormalPlan, true);
    assert.match(direct.message.payload.plan.title, /budgeting website/i);
    assert.equal(direct.message.payload.plan.stages[0].status, 'active');
    assert.equal(direct.message.payload.workspaceTrainingState, undefined);

    const streamEvents = [];
    await module.streamBrowserPreviewMessage(
      {
        text: 'I can study five hours each week.',
        responseLanguage: 'en-US',
      },
      'fixture-coach-session',
      {
        onStart(message) {
          streamEvents.push({ kind: 'start', message });
        },
        onChunk(message) {
          streamEvents.push({ kind: 'chunk', message });
        },
        onComplete(message, sessionId) {
          streamEvents.push({ kind: 'complete', message, sessionId });
        },
        onError(message) {
          streamEvents.push({ kind: 'error', message });
        },
      },
    );

    assert.equal(fetchCalls, 0);
    assert.deepEqual(
      streamEvents.map((event) => `${event.kind}:${event.message.type}`),
      [
        'start:stream/start',
        'chunk:stream/chunk',
        'chunk:stream/chunk',
        'complete:stream/complete',
        'complete:state/patch',
      ],
    );
    assert.equal(streamEvents.some((event) => event.kind === 'error'), false);
    const fixtureStreamMessageIds = streamEvents
      .map((event) => event.message.payload?.messageId)
      .filter((value) => typeof value === 'string');
    assert.equal(new Set(fixtureStreamMessageIds).size, 1);
    assert.equal(streamEvents.at(-1).sessionId, 'fixture-coach-session');

    const streamedConversation = streamEvents.at(-1).message.payload.conversation;
    assert.equal(streamedConversation.at(-2).body, 'I can study five hours each week.');
    assert.match(streamedConversation.at(-1).body, /Start with one finishable outcome/i);
    assert.match(streamedConversation.at(-1).body, /The current task is ready:/i);
    assert.doesNotMatch(streamedConversation.at(-1).body, /current file|function or component/i);
    assert.match(streamEvents.at(-1).message.payload.task.description, /budgeting website/i);
    assert.equal(global.window.__TRAINER_BOOTSTRAP__.hasFormalPlan, true);
    assert.match(global.window.__TRAINER_BOOTSTRAP__.plan.title, /budgeting website/i);
  } finally {
    global.fetch = originalFetch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    if (previousBootstrap === undefined) {
      delete global.window.__TRAINER_BOOTSTRAP__;
    } else {
      global.window.__TRAINER_BOOTSTRAP__ = previousBootstrap;
    }
  }
});

test('fixture Preview keeps German metadata while using English fallback starter replies', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousBootstrap = global.window.__TRAINER_BOOTSTRAP__;
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  global.window.__TRAINER_BOOTSTRAP__ = { conversation: [] };
  global.fetch = async () => {
    throw new Error('Fixture Preview must not contact a sidecar for coach messages.');
  };

  try {
    const module = await loadBrowserSidecarModule();
    const direct = await module.sendBrowserPreviewMessage(
      {
        text: 'Ich mochte lernen, wie ich einen FastAPI-Endpunkt teste.',
        responseLanguage: 'de-DE',
      },
      'fixture-coach-de-language',
    );
    const conversation = direct.message.payload.conversation;
    const reply = conversation.at(-1).body;

    assert.equal(conversation.at(-2).author, 'Du');
    assert.equal(conversation.at(-2).timestamp, 'Gerade eben');
    assert.equal(conversation.at(-1).timestamp, 'Gerade eben');
    assert.match(reply, /A local preview plan was created from your current goal\./);
    assert.match(reply, /Define a first-week outcome/);
    assert.match(reply, /Write one visible outcome you can finish this week/);

    const continuation = await module.sendBrowserPreviewMessage(
      {
        text: 'Ich habe drei Stunden pro Woche Zeit.',
        responseLanguage: 'de-DE',
      },
      'fixture-coach-de-language',
    );
    const continuationReply = continuation.message.payload.conversation.at(-1).body;

    assert.match(continuationReply, /Start with one finishable outcome/);
    assert.match(continuationReply, /Return to Coach with the result|The current task is ready/);
  } finally {
    global.fetch = originalFetch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    if (previousBootstrap === undefined) {
      delete global.window.__TRAINER_BOOTSTRAP__;
    } else {
      global.window.__TRAINER_BOOTSTRAP__ = previousBootstrap;
    }
  }
});

test('fixture Preview turns Plan next-task turns into a current task without fabricating one before a plan exists', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousBootstrap = global.window.__TRAINER_BOOTSTRAP__;
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  let fetchCalls = 0;
  global.fetch = async () => {
    fetchCalls += 1;
    throw new Error('Fixture Preview must not contact a sidecar for next-task turns.');
  };

  try {
    const module = await loadBrowserSidecarModule();
    const formalPlan = {
      id: 'fixture-formal-plan',
      title: 'Budgeting site learning plan',
      frozen: false,
      cadence: 'weekly',
      summary: 'Build one small, testable budgeting flow.',
      currentStageId: 'fixture-plan-stage',
      currentStep: 'Build the budget-entry form.',
      verifyMethod: ['Enter one budget item and confirm it remains after refresh.'],
      stages: [
        {
          id: 'fixture-plan-stage',
          title: 'Build the first budget-entry flow',
          objective: 'Create one form that records a budget item.',
          status: 'active',
        },
      ],
    };
    global.window.__TRAINER_BOOTSTRAP__ = {
      conversation: [],
      hasFormalPlan: true,
      profile: { goals: ['Build a budgeting site'] },
      plan: formalPlan,
    };

    const ready = await module.sendBrowserPreviewMessage(
      {
        text: 'Give me the next training task.',
        intent: 'next_task',
        activeView: 'plan',
        responseLanguage: 'en-US',
      },
      'fixture-plan-next-task-ready',
    );

    assert.equal(fetchCalls, 0);
    assert.equal(ready.message.type, 'state/patch');
    assert.equal(ready.message.payload.task.title, 'Build the first budget-entry flow');
    assert.match(ready.message.payload.coachingState.summary, /current task is ready/i);
    assert.match(ready.message.payload.conversation.at(-1).body, /The current task is ready:/);
    assert.equal(ready.message.payload.coachTurn.scenario, 'next_task');
    assert.equal(global.window.__TRAINER_BOOTSTRAP__.task.id, ready.message.payload.task.id);

    global.window.__TRAINER_BOOTSTRAP__ = {
      conversation: [],
      hasFormalPlan: false,
      profile: { goals: ['Build a budgeting site'] },
      plan: formalPlan,
    };
    const blocked = await module.sendBrowserPreviewMessage(
      {
        text: 'Give me the next training task.',
        intent: 'next_task',
        activeView: 'plan',
        responseLanguage: 'en-US',
      },
      'fixture-plan-next-task-missing-plan',
    );

    assert.equal(fetchCalls, 0);
    assert.equal(blocked.message.payload.task, undefined);
    assert.match(blocked.message.payload.coachingState.summary, /create a plan/i);
    assert.equal(
      blocked.message.payload.conversation.at(-1).body,
      'Create a plan from your goal first.',
    );
    assert.equal(blocked.message.payload.coachTurn.scenario, 'plan');
  } finally {
    global.fetch = originalFetch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    if (previousBootstrap === undefined) {
      delete global.window.__TRAINER_BOOTSTRAP__;
    } else {
      global.window.__TRAINER_BOOTSTRAP__ = previousBootstrap;
    }
  }
});

test('fixture Preview imports Resources in memory without contacting a sidecar', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousBootstrap = global.window.__TRAINER_BOOTSTRAP__;
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  global.window.__TRAINER_BOOTSTRAP__ = {
    resources: [
      {
        id: 'existing-resource',
        title: 'Existing note',
        kind: 'markdown',
        status: 'ready',
        summary: 'Existing fixture resource.',
      },
    ],
  };
  let fetchCalls = 0;
  global.fetch = async () => {
    fetchCalls += 1;
    throw new Error('Fixture Preview must not contact a sidecar for resource imports.');
  };

  try {
    const module = await loadBrowserSidecarModule();
    const result = await module.uploadBrowserPreviewResources(
      [
        {
          name: 'notes/first-steps.md',
          source: 'notes/first-steps.md',
          kind: 'markdown',
          content: '# First steps',
        },
      ],
      'fixture-resource-upload-session',
    );

    assert.equal(fetchCalls, 0);
    assert.equal(result.sessionId, 'fixture-resource-upload-session');
    assert.equal(result.uploadedCount, 1);
    assert.equal(result.indexedCount, 1);
    assert.equal(result.failedIndexCount, 0);
    assert.equal(result.patch.resources.length, 2);
    assert.deepEqual(result.patch.resources.at(-1), {
      id: 'preview-resource-first-steps-md-1',
      title: 'first-steps.md',
      kind: 'markdown',
      status: 'ready',
      summary: 'A local browser-preview copy. It was not saved to your workspace.',
      source: 'notes/first-steps.md',
      collectionPath: 'Imported/notes/first-steps.md',
      collectionRoot: 'Browser preview',
      sourceItems: ['notes/first-steps.md'],
      tags: [],
      sourceType: 'file',
      freshness: 'fresh',
      indexState: 'indexed',
      previewTier: 'metadata',
      previewKind: 'markdown',
      canInjectTrainingCard: false,
      updatedAt: result.patch.resources.at(-1).updatedAt,
    });
    assert.equal(
      global.window.__TRAINER_BOOTSTRAP__.resources.at(-1).id,
      'preview-resource-first-steps-md-1',
    );
  } finally {
    global.fetch = originalFetch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    if (previousBootstrap === undefined) {
      delete global.window.__TRAINER_BOOTSTRAP__;
    } else {
      global.window.__TRAINER_BOOTSTRAP__ = previousBootstrap;
    }
  }
});

test('browser preview actions keep the goal, Plan, and Resources journey local and visible', async () => {
  const module = await loadBrowserSidecarModule();
  const bootstrap = {
    hasFormalPlan: false,
    profile: {
      learnerName: 'Preview learner',
      goals: ['Build a budgeting website in two months'],
      weeklyHours: 4,
      preferredStyle: 'guided',
      answerPolicy: 'auto',
      focusAreas: [],
    },
    memory: {
      activeThread: {
        focusArea: 'Build a budgeting website in two months',
      },
    },
    plan: {
      id: 'stale-plan',
      title: 'Stale fixture plan',
      frozen: false,
      cadence: 'weekly',
      summary: 'Stale fixture summary',
      stages: [],
    },
    resources: [
      {
        id: 'preview-notes',
        title: 'Budgeting notes',
        kind: 'markdown',
        status: 'attention',
        summary: 'Preview resource',
        freshness: 'stale',
      },
    ],
  };

  const generated = module.runBrowserPreviewAction(
    { type: 'plan/generate' },
    bootstrap,
    'en-US',
  );
  assert.equal(generated.tone, 'success');
  assert.equal(generated.patch.hasFormalPlan, true);
  assert.match(generated.patch.plan.title, /budgeting website/i);
  assert.equal(generated.patch.plan.stages[0].status, 'active');

  const planned = { ...bootstrap, ...generated.patch };
  const frozen = module.runBrowserPreviewAction(
    { type: 'plan/freeze', payload: { frozen: true } },
    planned,
    'en-US',
  );
  assert.equal(frozen.patch.plan.frozen, true);
  assert.match(frozen.message, /frozen/i);

  const nextTask = module.runBrowserPreviewAction(
    { type: 'task/next' },
    { ...planned, ...frozen.patch },
    'en-US',
  );
  assert.match(nextTask.patch.task.title, /first-week outcome/i);

  const trainingCard = module.runBrowserPreviewAction(
    {
      type: 'command/execute',
      payload: {
        commandId: 'trainer.training.generateCard',
        payload: { cardType: 'practice', submode: 'practice' },
      },
    },
    planned,
    'en-US',
  );
  assert.equal(trainingCard.tone, 'success');
  assert.match(trainingCard.message, /local demo training card/i);
  assert.equal(trainingCard.patch.workspaceTrainingState.selectedCardType, 'practice');
  assert.equal(trainingCard.patch.workspaceTrainingState.trainingCardCandidates.length, 1);
  assert.equal(
    trainingCard.patch.workspaceTrainingState.activeTrainingCardRouting.selectedCardId,
    trainingCard.patch.workspaceTrainingState.selectedCardId,
  );

  const refreshed = module.runBrowserPreviewAction(
    { type: 'command/execute', payload: { commandId: 'trainer.resource.index' } },
    planned,
    'en-US',
  );
  assert.equal(refreshed.patch.resources[0].status, 'ready');
  assert.equal(refreshed.patch.resources[0].indexState, 'indexed');

  const opened = module.runBrowserPreviewAction(
    { type: 'resource/open', payload: { resourceId: 'preview-notes' } },
    planned,
    'en-US',
  );
  assert.equal(opened.tone, 'info');
  assert.match(opened.message, /Budgeting notes/);
});

test('browser preview training actions stay local across Learn, Try, Verify, Reflect, and Return', async () => {
  const module = await loadBrowserSidecarModule();
  const bootstrap = {
    hasFormalPlan: false,
    profile: {
      learnerName: 'Preview learner',
      goals: ['Build a budgeting website in two months'],
      weeklyHours: 4,
      preferredStyle: 'guided',
      answerPolicy: 'auto',
      focusAreas: [],
    },
    memory: {
      activeThread: {
        focusArea: 'Build a budgeting website in two months',
      },
    },
  };
  const execute = (commandId, payload = {}) => ({
    type: 'command/execute',
    payload: { commandId, payload },
  });

  const generated = module.runBrowserPreviewAction(
    execute('trainer.training.generateCard', { cardType: 'practice', submode: 'practice' }),
    bootstrap,
    'en-US',
  );
  assert.equal(generated.tone, 'success');
  assert.match(generated.message, /local demo training card/i);

  const trainingBase = {
    ...bootstrap,
    ...generated.patch,
  };
  const selectedCardId = trainingBase.workspaceTrainingState.selectedCardId;
  const handoffId = trainingBase.workspaceTrainingState.latestTrainingHandoff.handoffId;

  const tryStep = module.runBrowserPreviewAction(
    execute('trainer.trainingCard.transition', {
      cardId: selectedCardId,
      newStatus: 'in_progress',
      reason: 'try the local slice first',
    }),
    trainingBase,
    'en-US',
  );
  assert.equal(tryStep.tone, 'success');
  assert.match(tryStep.message, /simulation/i);
  assert.equal(tryStep.patch.workspaceTrainingState.selectedCardStatus, 'in_progress');
  assert.match(tryStep.patch.workspaceTrainingState.trainingEventLedger.at(-1).statusSummary, /Move the training card/i);

  const flashcardAnswerStep = module.runBrowserPreviewAction(
    execute('trainer.training.flashcardAnswer', {
      cardId: selectedCardId,
      learnerAnswer: 'Use the smallest verifiable slice.',
    }),
    trainingBase,
    'en-US',
  );
  assert.equal(flashcardAnswerStep.tone, 'success');
  assert.match(flashcardAnswerStep.message, /flashcard answer recorded locally/i);
  assert.equal(flashcardAnswerStep.patch.workspaceTrainingState.selectedCardStatus, 'answered');

  const verifyStep = module.runBrowserPreviewAction(
    execute('trainer.evaluate.currentFile', {
      taskId: 'browser-preview-verify-task',
    }),
    trainingBase,
    'en-US',
  );
  assert.equal(verifyStep.tone, 'error');
  assert.match(verifyStep.message, /no current IDE file/i);
  assert.match(verifyStep.message, /Open the file in VS Code/i);
  assert.equal(verifyStep.patch, undefined);

  const evidenceStep = module.runBrowserPreviewAction(
    execute('trainer.evidence.enqueue', {
      source: 'card_result',
      summary: 'Local fixture verification was queued as evidence.',
      concepts: ['browser preview', 'training loop'],
      outcome: 'pass',
      sourceCardId: selectedCardId,
      targetPlanStageId: 'browser-preview-plan-first-outcome',
      confidence: 0.91,
    }),
    trainingBase,
    'en-US',
  );
  assert.equal(evidenceStep.tone, 'success');
  assert.match(evidenceStep.message, /evidence queued locally/i);
  assert.equal(evidenceStep.patch.memory.evidenceQueue.pending[0].summary, 'Local fixture verification was queued as evidence.');
  assert.equal(evidenceStep.patch.memory.evidenceQueue.totalCount, 1);

  const reflectStep = module.runBrowserPreviewAction(
    execute('trainer.training.reflect', {
      cardId: selectedCardId,
      handoffId,
      reflection: 'The preview stayed local and never touched a real workspace.',
    }),
    trainingBase,
    'en-US',
  );
  assert.equal(reflectStep.tone, 'success');
  assert.match(reflectStep.message, /reflection recorded locally/i);
  assert.equal(reflectStep.patch.workspaceTrainingState.selectedCardStatus, 'reflected');
  assert.equal(reflectStep.patch.workspaceTrainingState.latestTrainingHandoff.handoffStatus, 'ready_to_return');
  assert.equal(reflectStep.patch.workspaceTrainingState.latestTrainingHandoff.returnMode, 'return_required');
  assert.equal(reflectStep.patch.workspaceTrainingState.latestTrainingNextHop.status, 'return_required');

  const practiceReturnStep = module.runBrowserPreviewAction(
    execute('trainer.training.practiceReturn', {
      cardId: selectedCardId,
      passed: true,
      summary: 'Local preview verification passed.',
      nextStep: 'Return result to Coach',
      focusArea: 'Build a budgeting website in two months',
      evidenceSource: 'browser_preview_simulation',
    }),
    trainingBase,
    'en-US',
  );
  assert.equal(practiceReturnStep.tone, 'success');
  assert.match(practiceReturnStep.message, /practice return recorded locally/i);
  assert.equal(practiceReturnStep.patch.workspaceTrainingState.selectedCardStatus, 'returned');
  assert.match(practiceReturnStep.patch.workspaceTrainingState.latestLearningVerifiedResult, /Local preview verification passed/i);

  const returned = module.runBrowserPreviewAction(
    execute('trainer.training.return', {
      cardId: selectedCardId,
      handoffId,
    }),
    trainingBase,
    'en-US',
  );
  assert.equal(returned.tone, 'success');
  assert.match(returned.message, /return completed locally/i);
  assert.equal(returned.patch.workspaceTrainingState.selectedCardStatus, 'returned');
  assert.equal(returned.patch.workspaceTrainingState.latestTrainingHandoff.handoffStatus, 'returned');
  assert.equal(returned.patch.workspaceTrainingState.latestTrainingHandoff.returnMode, 'result');
  assert.equal(returned.patch.workspaceTrainingState.latestTrainingNextHop.status, 'continued_in_chat');
  assert.match(returned.patch.workspaceTrainingState.latestLearningFollowup, /Return result to Coach/i);
});

test('browser preview can move through workspace admission states without touching a real folder', async () => {
  const module = await loadBrowserSidecarModule();
  const bootstrap = {
    memory: {
      workspace: {
        trainerWorkspace: {
          status: 'root-missing',
          projectName: 'Preview project',
          projectPath: 'D:\\Preview\\project',
        },
      },
      workspaceUnderstanding: {
        firstLookSummary: {
          recommendedNextStep: 'Choose a folder first.',
        },
      },
    },
  };
  const command = (commandId) => ({
    type: 'command/execute',
    payload: { commandId },
  });
  const withPatch = (current, patch) => ({
    ...current,
    ...patch,
    memory: patch?.memory ?? current.memory,
  });

  const directAdopt = module.runBrowserPreviewAction(
    command('trainer.workspace.adoptProject'),
    bootstrap,
    'en-US',
  );
  assert.equal(directAdopt.patch, undefined);
  assert.match(directAdopt.message, /Choose where Trainer keeps learning records/i);

  for (const commandId of [
    'trainer.plan.generate',
    'trainer.plan.update',
    'trainer.task.next',
    'trainer.resource.index',
    'trainer.training.generateCard',
  ]) {
    const blocked = module.runBrowserPreviewAction(command(commandId), bootstrap, 'en-US');
    assert.equal(blocked.patch, undefined, commandId);
    assert.match(blocked.message, /Choose where Trainer keeps learning records/i, commandId);
  }

  const selectedRoot = module.runBrowserPreviewAction(
    command('trainer.workspace.chooseRoot'),
    bootstrap,
    'en-US',
  );
  assert.equal(selectedRoot.tone, 'success');
  assert.equal(selectedRoot.patch.memory.workspace.trainerWorkspace.status, 'project-found');
  assert.match(
    selectedRoot.patch.memory.workspaceUnderstanding.firstLookSummary.recommendedNextStep,
    /Choose one: add it to Trainer/i,
  );
  const projectFound = withPatch(bootstrap, selectedRoot.patch);

  const blockedProjectPlan = module.runBrowserPreviewAction(
    command('trainer.plan.generate'),
    projectFound,
    'en-US',
  );
  assert.equal(blockedProjectPlan.patch, undefined);
  assert.match(blockedProjectPlan.message, /Choose one: add it to Trainer/i);

  const adopted = module.runBrowserPreviewAction(
    command('trainer.workspace.adoptProject'),
    projectFound,
    'en-US',
  );
  assert.equal(adopted.tone, 'success');
  assert.equal(adopted.patch.memory.workspace.trainerWorkspace.status, 'managed');
  const managed = withPatch(projectFound, adopted.patch);

  const managedBrowse = module.runBrowserPreviewAction(
    command('trainer.workspace.browseProject'),
    managed,
    'en-US',
  );
  const managedIgnore = module.runBrowserPreviewAction(
    command('trainer.workspace.ignoreProject'),
    managed,
    'en-US',
  );
  assert.equal(managedBrowse.patch, undefined);
  assert.equal(managedIgnore.patch, undefined);
  assert.match(managedBrowse.message, /kept separately/i);
  assert.match(managedIgnore.message, /kept separately/i);

  const browsed = module.runBrowserPreviewAction(
    command('trainer.workspace.browseProject'),
    projectFound,
    'en-US',
  );
  assert.equal(browsed.tone, 'success');
  assert.equal(browsed.patch.memory.workspace.trainerWorkspace.status, 'browse');
  const browse = withPatch(projectFound, browsed.patch);

  const browseTraining = module.runBrowserPreviewAction(
    command('trainer.training.generateCard'),
    browse,
    'en-US',
  );
  assert.equal(browseTraining.patch, undefined);
  assert.match(browseTraining.message, /saved learning records stay off/i);

  const ignored = module.runBrowserPreviewAction(
    command('trainer.workspace.ignoreProject'),
    browse,
    'en-US',
  );
  assert.equal(ignored.tone, 'success');
  assert.equal(ignored.patch.memory.workspace.trainerWorkspace.status, 'ignored');

  const managedPlan = module.runBrowserPreviewAction(
    command('trainer.plan.generate'),
    managed,
    'en-US',
  );
  assert.equal(managedPlan.tone, 'success');
  assert.ok(managedPlan.patch?.plan);
});

test('streamBrowserPreviewMessage hides raw HTTP and SSE failure details', async () => {
  const originalFetch = global.fetch;
  const callbackSet = (errors) => ({
    onStart() {},
    onChunk() {},
    onComplete() {},
    onError(message) {
      errors.push(message);
    },
  });

  try {
    const module = await loadBrowserSidecarModule();
    const httpErrors = [];
    global.fetch = async () => new Response(
      '<html><body>Traceback: secret=hidden</body></html>',
      { status: 502 },
    );

    await module.streamBrowserPreviewMessage(
      { text: 'Help me begin.', responseLanguage: 'en-US' },
      'preview-stream-http-error',
      callbackSet(httpErrors),
    );

    assert.equal(httpErrors.length, 1);
    assert.equal(httpErrors[0].payload.category, 'provider_error');
    assert.equal(httpErrors[0].payload.statusCode, 502);
    assert.doesNotMatch(JSON.stringify(httpErrors[0].payload), /html|traceback|secret/i);

    const sseErrors = [];
    global.fetch = async () => new Response(
      'event: error\ndata: Traceback (most recent call last): {"token":"hidden"}\n\n',
      {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      },
    );

    await module.streamBrowserPreviewMessage(
      { text: 'Help me begin.', responseLanguage: 'en-US' },
      'preview-stream-sse-error',
      callbackSet(sseErrors),
    );

    assert.equal(sseErrors.length, 1);
    assert.equal(sseErrors[0].payload.category, 'provider_error');
    assert.doesNotMatch(JSON.stringify(sseErrors[0].payload), /traceback|token|hidden/i);

    const malformedEvents = [];
    global.fetch = async () => new Response(
      'event: message\ndata: {"chunk":"secret=hidden"\n\n',
      {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      },
    );

    await module.streamBrowserPreviewMessage(
      { text: 'Help me begin.', responseLanguage: 'en-US' },
      'preview-stream-malformed-event',
      callbackSet(malformedEvents),
    );

    assert.equal(malformedEvents.length, 1);
    assert.equal(malformedEvents[0].payload.category, 'malformed_response');
    assert.doesNotMatch(JSON.stringify(malformedEvents[0].payload), /secret|hidden|unexpected token/i);
  } finally {
    global.fetch = originalFetch;
  }
});

test('browser preview keeps raw non-stream transport failures out of public errors', async () => {
  const originalFetch = global.fetch;
  const module = await loadBrowserSidecarModule();

  try {
    global.fetch = async () => new Response(
      '<html><body>502 gateway failure Traceback: api_key=hidden</body></html>',
      { status: 502 },
    );
    await assert.rejects(
      () => module.sendBrowserPreviewMessage({ text: 'Help me start.' }, 'preview-safe-send'),
      (error) => {
        assert.doesNotMatch(error.message, /html|502|gateway|traceback|api_key|hidden/i);
        assert.match(error.message, /connection|model|settings/i);
        return true;
      },
    );

    global.fetch = async () => new Response(
      JSON.stringify({ detail: 'Traceback: token=hidden' }),
      { status: 500, headers: { 'content-type': 'application/json' } },
    );
    await assert.rejects(
      () => module.saveBrowserPreviewCoachSettings({}, 'preview-safe-settings'),
      (error) => {
        assert.doesNotMatch(error.message, /traceback|token|hidden|json/i);
        assert.match(error.message, /connection|model|settings/i);
        return true;
      },
    );

    global.fetch = async () => new Response('<html>not json</html>', { status: 200 });
    await assert.rejects(
      () => module.sendBrowserPreviewMessage({ text: 'Try the next step.' }, 'preview-safe-json'),
      (error) => {
        assert.doesNotMatch(error.message, /html|json|unexpected token/i);
        assert.match(error.message, /reply|model|connection|settings/i);
        return true;
      },
    );
  } finally {
    global.fetch = originalFetch;
  }
});

test('browser preview replaces provider failure details and diagnostics with safe recovery copy', async () => {
  const originalFetch = global.fetch;
  const module = await seedPreviewProviderState(
    {
      configured: true,
      name: 'Safe test provider',
      baseUrl: 'http://127.0.0.1:1234/v1',
      model: 'safe-model',
      protocol: 'openai_chat_completions_compatible',
      availableModels: ['safe-model'],
      modelListStatus: 'ready',
    },
    'sk-safe-test',
  );

  try {
    global.fetch = async (url) => {
      const href = String(url);
      if (href.endsWith('/provider/test')) {
        return new Response(
          JSON.stringify({
            ok: false,
            status: 'Traceback: provider internal state',
            detail: '<html>secret_token=hidden</html>',
            diagnostics: ['HTTP 502', 'Traceback: api_key=hidden'],
            error_category: 'invalid_key_or_permission',
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      }
      if (href.endsWith('/provider/models')) {
        return new Response(
          JSON.stringify({
            ok: false,
            detail: 'Traceback: upstream gateway details',
            error_category: 'model_unsupported',
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      }
      throw new Error(`Unexpected fetch request: ${href}`);
    };

    const testResult = await module.testBrowserPreviewProvider('preview-safe-provider-test');
    const providerPatch = testResult.messages[0].payload.providerConfig;
    assert.equal(testResult.messages[1].payload.tone, 'error');
    assert.match(testResult.messages[1].payload.message, /key|access|settings/i);
    assert.doesNotMatch(JSON.stringify(testResult), /traceback|secret_token|api_key|hidden|502/i);
    assert.equal(providerPatch.lastTestResult.status, 'failed');
    assert.equal(providerPatch.lastTestResult.errorCategory, 'invalid_key_or_permission');

    const modelResult = await module.refreshBrowserPreviewProviderModels(
      {
        name: 'Safe test provider',
        baseUrl: 'http://127.0.0.1:1234/v1',
        model: 'safe-model',
        protocol: 'openai_chat_completions_compatible',
        apiKey: 'sk-safe-test',
      },
      'preview-safe-provider-models',
    );
    const modelPatch = modelResult.messages[0].payload.providerConfig;
    assert.equal(modelResult.messages[1].payload.tone, 'error');
    assert.match(modelResult.messages[1].payload.message, /model|settings/i);
    assert.doesNotMatch(JSON.stringify(modelResult), /traceback|gateway|details/i);
    assert.equal(modelPatch.modelErrorCategory, 'model_unsupported');
  } finally {
    global.fetch = originalFetch;
  }
});

test('browser preview turns upload HTML failures into safe recovery copy', async () => {
  const originalFetch = global.fetch;
  const module = await loadBrowserSidecarModule();

  try {
    global.fetch = async () => new Response(
      '<html><body>upload failed: Traceback token=hidden</body></html>',
      { status: 502 },
    );
    await assert.rejects(
      () =>
        module.uploadBrowserPreviewResources(
          [{ name: 'notes.md', kind: 'markdown', content: '# Notes' }],
          'preview-safe-upload',
        ),
      (error) => {
        assert.doesNotMatch(error.message, /html|upload failed|traceback|token|hidden|502/i);
        assert.match(error.message, /connection|model|settings/i);
        return true;
      },
    );
  } finally {
    global.fetch = originalFetch;
  }
});

test('browser preview returns completed uploads when another file fails', async () => {
  const originalFetch = global.fetch;
  const module = await loadBrowserSidecarModule();
  const uploadedNames = [];

  global.fetch = async (url, init) => {
    const href = String(url);
    if (href.endsWith('/resource/upload')) {
      const body = JSON.parse(init.body);
      uploadedNames.push(body.name);
      if (body.name === 'second.md') {
        return new Response('<html><body>second upload failed: token=hidden</body></html>', {
          status: 502,
        });
      }
      const id = body.name === 'first.md' ? 'resource-first' : 'resource-third';
      return new Response(
        JSON.stringify({
          id,
          title: body.name,
          kind: 'markdown',
          status: 'ready',
          summary: `${body.name} uploaded`,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    if (href.endsWith('/resource/index')) {
      const body = JSON.parse(init.body);
      return new Response(
        JSON.stringify({
          id: body.resource_id,
          title: body.resource_id === 'resource-first' ? 'first.md' : 'third.md',
          kind: 'markdown',
          status: 'ready',
          parse_status: 'parsed',
          index_status: 'indexed',
          summary: 'Indexed resource',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    if (href.includes('/memory/summary')) {
      return new Response(
        JSON.stringify({
          memory: {
            resources: [
              {
                id: 'resource-first',
                name: 'first.md',
                kind: 'markdown',
                parse_status: 'parsed',
                index_status: 'indexed',
                summary: 'First resource',
              },
              {
                id: 'resource-third',
                name: 'third.md',
                kind: 'markdown',
                parse_status: 'parsed',
                index_status: 'indexed',
                summary: 'Third resource',
              },
            ],
          },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const result = await module.uploadBrowserPreviewResources(
      [
        { name: 'first.md', kind: 'markdown', content: '# First' },
        { name: 'second.md', kind: 'markdown', content: '# Second' },
        { name: 'third.md', kind: 'markdown', content: '# Third' },
      ],
      'preview-partial-upload',
    );

    assert.deepEqual(uploadedNames, ['first.md', 'second.md', 'third.md']);
    assert.equal(result.uploadedCount, 2);
    assert.equal(result.indexedCount, 2);
    assert.equal(result.failedIndexCount, 0);
    assert.equal(result.failedUploadCount, 1);
    assert.equal(result.failedUploads[0].fileName, 'second.md');
    assert.match(result.failedUploads[0].message, /connection|model|settings/i);
    assert.doesNotMatch(result.failedUploads[0].message, /html|token|hidden|502/i);
    assert.deepEqual(
      result.patch.resources.map((resource) => resource.id),
      ['resource-first', 'resource-third'],
    );
  } finally {
    global.fetch = originalFetch;
  }
});

function createPreviewTrainingSummary() {
  return {
    memory: {
      workspace: {
        workspace_id: 'F:\\trainer-preview',
        latest_training_handoff: {
          candidate_id: 'candidate-practice-1',
          continue_in: 'training',
          card_type: 'practice',
          card_title: 'Practice the dependency boundary',
          scenario_pack: 'remote_workspace',
          learner_deliverables: ['Implement one route with one clean dependency seam.'],
          verification_steps: ['Run the route test once.'],
          return_with: 'Bring back the diff and the test output.',
        },
        latest_training_next_hop: {
          candidate_id: 'candidate-practice-2',
          candidate_type: 'practice_candidate',
          continue_in: 'training',
          target_kind: 'training_card',
          target_id: 'card-practice-2',
          status: 'surfaced',
          scenario_pack: 'remote_workspace',
          next_after_completion: 'Review the blocker, then continue the practice card.',
        },
        latest_training_submode: 'practice',
        latest_learning_focus_area: 'dependency injection',
        latest_learning_followup: 'Return with the route diff and the test output.',
        latest_learning_verified_result: 'One route now respects the dependency boundary.',
        latest_learning_partial_progress: 'The dependency function already exists.',
        selected_card_id: 'card-practice-1',
        selected_card_type: 'practice',
        selected_card_title: 'Practice the dependency boundary',
        selected_card_status: 'active',
      },
      training_card_candidates: [
        {
          card_id: 'card-practice-1',
          card_type: 'practice',
          title: 'Practice the dependency boundary',
          why_now: 'Highest leverage next card.',
          status: 'active',
        },
      ],
      active_training_card_routing: {
        selected_card_id: 'card-practice-1',
        why_this_card: 'Highest leverage next card.',
        candidate_count: 3,
        eligible_count: 1,
      },
      review_artifact: {
        id: 'review-1',
        title: 'Governed review',
        status: 'resolved',
        focus_area: 'dependency injection',
      },
      scenario_lab: {
        id: 'scenario-1',
        title: 'Sandbox the dependency boundary',
        status: 'ready',
        learner_deliverables: ['Build one route plus one dependency.'],
        verification_steps: ['Call the route once.'],
      },
      theory_drill: {
        id: 'theory-1',
        title: 'Why this boundary?',
        status: 'in_progress',
        questions: [
          {
            question_id: 'q1',
            prompt: 'Why does this dependency belong in the route instead of the service layer?',
          },
        ],
      },
      due_reviews: [
        {
          concept: 'fastapi Depends',
          reason: 'Review the boundary choice.',
          source: 'plan',
          severity: 'medium',
        },
      ],
    },
  };
}

test('fetchBrowserPreviewBootstrap preserves structured sandbox preview data', async () => {
  const originalFetch = global.fetch;
  global.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/memory/settings')) {
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (href.includes('/memory/summary')) {
      return new Response(
        JSON.stringify({
          memory: {
            sandbox_preview: {
              path: 'F:\\trainer\\sandbox\\preview.xlsx',
              relative_path: 'preview.xlsx',
              title: 'Preview',
              file_kind: 'table',
              preview_tier: 'converted',
              preview_kind: 'table',
              content: '### Sheet1',
              excerpt: '### Sheet1',
              is_binary: false,
              is_editable: true,
              can_native_open: true,
              structured_data: {
                kind: 'table',
                columns: ['Name', 'Score'],
                rows: [['Ada', '98']],
                rowCount: 1,
                columnCount: 2,
                truncated: false,
              },
              metadata: {},
            },
          },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule();
    const result = await module.fetchBrowserPreviewBootstrap('session-structured');

    assert.equal(result.sessionId, 'session-structured');
    assert.equal(result.message.type, 'bootstrap');
    assert.equal(result.message.payload.memory.sandboxPreview.previewKind, 'table');
    assert.deepEqual(result.message.payload.memory.sandboxPreview.structuredData, {
      kind: 'table',
      columns: ['Name', 'Score'],
      rows: [['Ada', '98']],
      rowCount: 1,
      columnCount: 2,
      truncated: false,
    });
  } finally {
    global.fetch = originalFetch;
  }
});

test('fetchBrowserPreviewBootstrap strips internal coach meta from visible surfaces', async () => {
  const originalFetch = global.fetch;
  global.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/memory/settings')) {
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (href.includes('/memory/summary')) {
      return new Response(
        JSON.stringify({
          memory: {
            current_focus:
              'Current coaching focus: Keep the remote boundary attached to one verified workspace path.',
            review_rhythm: 'Review rhythm: One review checkpoint is still due.',
          },
          review_queue_summary: 'Review rhythm: One review checkpoint is still due.',
          coach_turn: {
            summary: 'Project implementation',
            next_step: 'Review rhythm: Re-open one workspace path.',
            review_queue_summary: 'Review rhythm: One review checkpoint is still due.',
            resume_thread:
              'Resume the live thread around the verified remote boundary. Next: re-open one workspace path.',
          },
          plan_runtime_status: {
            current_main_thread: {
              summary: 'Current coaching focus: Teach the first remote boundary step.',
              current_step:
                'Current coaching focus: Verify which machine owns the workspace files.',
              why_now: 'Current focus to continue: The workspace owner is still ambiguous.',
              verified_result:
                'Build on the verified result: One workspace path is already confirmed.',
            },
            coach_judgment: {
              summary: 'Project implementation',
              teaching_goal: 'Current focus: Keep the boundary narrow.',
              resume_thread:
                'Resume the live thread around the verified remote boundary. Next: re-open one workspace path.',
            },
          },
          messages: [],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule();
    const result = await module.fetchBrowserPreviewBootstrap('session-meta-clean');
    const payload = result.message.payload;

    assert.equal(
      payload.memory.currentFocus,
      'Keep the remote boundary attached to one verified workspace path.',
    );
    assert.equal(payload.reviewQueueSummary, 'One review checkpoint is still due.');
    assert.equal(
      payload.coachTurn.reviewQueueSummary,
      'One review checkpoint is still due.',
    );
    assert.equal(
      payload.planRuntimeStatus.currentMainThread.summary,
      'Teach the first remote boundary step.',
    );
    assert.equal(
      payload.planRuntimeStatus.currentMainThread.currentStep,
      'Verify which machine owns the workspace files.',
    );
    assert.equal(
      payload.planRuntimeStatus.currentMainThread.whyNow,
      'The workspace owner is still ambiguous.',
    );
    assert.equal(
      payload.planRuntimeStatus.currentMainThread.verifiedResult,
      'One workspace path is already confirmed.',
    );
    assert.equal(payload.planRuntimeStatus.coachJudgment.summary, undefined);
    assert.equal(
      payload.planRuntimeStatus.coachJudgment.teachingGoal,
      'Keep the boundary narrow.',
    );
    assert.equal(
      payload.planRuntimeStatus.coachJudgment.resumeThread,
      'the verified remote boundary. Next: re-open one workspace path.',
    );
  } finally {
    global.fetch = originalFetch;
  }
});

test('fetchBrowserPreviewBootstrap maps authoritative workspace training state into preview bootstrap', async () => {
  const originalFetch = global.fetch;
  global.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/memory/settings')) {
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (href.includes('/memory/summary')) {
      return new Response(JSON.stringify(createPreviewTrainingSummary()), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule();
    const result = await module.fetchBrowserPreviewBootstrap('session-training');

    assert.equal(result.sessionId, 'session-training');
    assert.equal(result.message.type, 'bootstrap');
    assert.equal(result.message.payload.workspaceTrainingState.selectedCardId, 'card-practice-1');
    assert.equal(
      result.message.payload.workspaceTrainingState.latestTrainingHandoff.cardTitle,
      'Practice the dependency boundary',
    );
    assert.equal(
      result.message.payload.workspaceTrainingState.latestTrainingHandoff.scenarioPack,
      'remote_workspace',
    );
    assert.equal(
      result.message.payload.workspaceTrainingState.latestTrainingNextHop.targetId,
      'card-practice-2',
    );
    assert.equal(
      result.message.payload.workspaceTrainingState.latestTrainingNextHop.scenarioPack,
      'remote_workspace',
    );
    assert.equal(
      result.message.payload.workspaceTrainingState.scenarioLab.title,
      'Sandbox the dependency boundary',
    );
    assert.equal(
      result.message.payload.workspaceTrainingState.theoryDrill.questions[0].prompt,
      'Why does this dependency belong in the route instead of the service layer?',
    );
  } finally {
    global.fetch = originalFetch;
  }
});

test('fetchBrowserPreviewBootstrap maps workspace understanding first-look summaries', async () => {
  const originalFetch = global.fetch;
  global.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/memory/settings')) {
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (href.includes('/memory/summary')) {
      return new Response(
        JSON.stringify({
          memory: {
            workspace_understanding: {
              repo_summary: 'Preview workspace overview',
              entry_points: ['server/app/api/routers.py'],
              feature_lanes: ['Coach-first flow'],
              risk_zones: ['Avoid a dashboard-style first screen.'],
              training_opportunities: ['Keep first look in the Coach view.'],
              resource_brief: 'Preview context',
              first_look_summary: {
                folder_role: 'existing_engineering',
                project_type_guess: 'api_service',
                confidence: 0.84,
                why_this_guess: 'Detected a FastAPI sidecar.',
                entry_points: ['server/app/api/routers.py'],
                directory_anchors: ['server', 'extension'],
                core_modules_or_materials: ['routers.py'],
                risk_zones: ['Avoid widening the first-screen surface.'],
                training_opportunities: ['Use the router boundary as the first slice.'],
                unknowns: ['Unknown provider state'],
                recommended_next_step: 'Start from the router boundary.',
                classification_method: 'heuristic',
                classified_at: '2026-04-30T09:15:00Z',
              },
            },
          },
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      );
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule();
    const result = await module.fetchBrowserPreviewBootstrap('session-first-look');

    assert.equal(result.sessionId, 'session-first-look');
    assert.equal(result.message.type, 'bootstrap');
    assert.equal(result.message.payload.memory.workspaceUnderstanding.firstLookSummary.folderRole, 'existing_engineering');
    assert.equal(
      result.message.payload.memory.workspaceUnderstanding.firstLookSummary.projectTypeGuess,
      'api_service',
    );
    assert.equal(
      result.message.payload.memory.workspaceUnderstanding.firstLookSummary.recommendedNextStep,
      'Start from the router boundary.',
    );
  } finally {
    global.fetch = originalFetch;
  }
});

test('fetchBrowserPreviewBootstrap prefers browser preview bootstrap when present', async () => {
  const originalFetch = global.fetch;
  const originalWindow = global.window;
  const bootstrap = {
    activeView: 'coach',
    connection: { state: 'connected', provider: { name: 'Preview', model: 'mock', capabilities: {} } },
  };
  const previewWindow = global.window;
  previewWindow.__TRAINER_BOOTSTRAP__ = bootstrap;
  global.fetch = async (url) => {
    const href = String(url);
    if (href.endsWith('/session/start')) {
      return new Response(JSON.stringify({ session_id: 'session-window' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule();
    const result = await module.fetchBrowserPreviewBootstrap();

    assert.equal(result.sessionId, 'session-window');
    assert.equal(result.message.type, 'bootstrap');
    assert.equal(result.message.payload.activeView, 'coach');
  } finally {
    global.fetch = originalFetch;
    delete previewWindow.__TRAINER_BOOTSTRAP__;
    global.window = originalWindow;
  }
});

test('live browser Preview discovers the extension-managed sidecar port', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousSearch = global.window.location.search;
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  delete global.window.__TRAINER_BOOTSTRAP__;
  global.window.location.search = '?live=1';
  const probes = [];
  global.fetch = async (url) => {
    const href = String(url);
    probes.push(href);
    if (href.endsWith(':34891/health')) {
      throw new Error('connection refused');
    }
    if (href.endsWith(':34892/health')) {
      return new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule();
    const baseUrl = await module.ensureBrowserPreviewSidecar();

    assert.equal(baseUrl, 'http://127.0.0.1:34892');
    assert.deepEqual(probes, [
      'http://127.0.0.1:34891/health',
      'http://127.0.0.1:34892/health',
    ]);
  } finally {
    global.fetch = originalFetch;
    global.window.location.search = previousSearch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
  }
});

test('fetchBrowserPreviewBootstrap can force live bootstrap refresh even when browser preview bootstrap is present', async () => {
  const originalFetch = global.fetch;
  const originalWindow = global.window;
  const bootstrap = {
    activeView: 'coach',
    connection: { state: 'connected', provider: { name: 'Injected bootstrap', model: 'mock', capabilities: {} } },
  };
  const previewWindow = global.window;
  previewWindow.__TRAINER_BOOTSTRAP__ = bootstrap;
  const requests = [];
  global.fetch = async (url, init = {}) => {
    const href = String(url);
    requests.push({
      href,
      method: init.method ?? 'GET',
    });
    if (href.includes('/memory/settings')) {
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (href.includes('/memory/summary')) {
      return new Response(
        JSON.stringify({
          provider: {
            name: 'Live sidecar',
            model: 'live-model',
          },
          memory: {},
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      );
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule();
    const result = await module.fetchBrowserPreviewBootstrap('session-force-live', true);

    const normalizedRequests = requests.map((entry) => ({
      href: entry.href.replace(/^https?:\/\/127\.0\.0\.1:\d+/, ''),
      method: entry.method,
    }));
    assert.deepEqual(normalizedRequests[0], { href: '/memory/settings', method: 'POST' });
    assert.equal(normalizedRequests[1].method, 'GET');
    assert.match(
      normalizedRequests[1].href,
      /^\/memory\/summary\?session_id=session-force-live&workspace_id=trainer-web-preview-/,
    );
    assert.equal(result.message.payload.connection.provider.name, 'Live sidecar');
    assert.equal(result.message.payload.connection.provider.model, 'live-model');
  } finally {
    global.fetch = originalFetch;
    delete previewWindow.__TRAINER_BOOTSTRAP__;
    global.window = originalWindow;
  }
});

test('live browser Preview searches the real Sidecar and normalizes ranked hits', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousSearch = global.window.location.search;
  const requests = [];
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  global.window.location.search = '?sidecarPort=34892';
  delete global.window.__TRAINER_BOOTSTRAP__;
  global.fetch = async (url, init = {}) => {
    const href = String(url);
    requests.push({ href, init });
    if (href.endsWith(':34892/health')) {
      return new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (href.endsWith('/resource/search')) {
      return new Response(
        JSON.stringify({
          workspace_id: 'workspace-search',
          query: 'provider',
          total: 1,
          ranking_strategy: 'lexical_first',
          filters: { index_state: 'indexed' },
          hits: [
            {
              resource_id: 'resource-provider',
              title: 'Provider boundaries',
              kind: 'markdown',
              summary: 'Provider setup and failure boundaries.',
              source: 'docs/provider.md',
              index_state: 'indexed',
              trust_state: 'trusted',
              rank_score: 0.91,
              rank_reasons: ['title_match'],
            },
          ],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule();
    const result = await module.searchBrowserPreviewResources(
      { query: 'provider', requestId: 'resource-search-provider-1', mode: 'trusted' },
      'session-search',
    );
    const request = requests.find((entry) => entry.href.endsWith('/resource/search'));
    assert.ok(request);
    const body = JSON.parse(request.init.body);
    assert.equal(body.session_id, 'session-search');
    assert.match(body.workspace_id, /^trainer-web-preview-/);
    assert.deepEqual(
      {
        query: body.query,
        top_k: body.top_k,
        trust_state: body.trust_state,
        index_state: body.index_state,
      },
      {
        query: 'provider',
        top_k: 10,
        trust_state: 'trusted',
        index_state: 'indexed',
      },
    );
    assert.equal(result.sessionId, 'session-search');
    assert.equal(result.message.type, 'state/patch');
    assert.equal(result.message.payload.resourceSearch.query, 'provider');
    assert.equal(result.message.payload.resourceSearch.hits[0].status, 'ready');
    assert.equal(result.message.payload.resourceSearch.hits[0].trustState, 'trusted');
    assert.equal(result.message.payload.resourceSearch.hits[0].rankScore, 0.91);
  } finally {
    global.fetch = originalFetch;
    global.window.location.search = previousSearch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
  }
});

test('fetchBrowserPreviewBootstrap aligns preview memory to the current response language before reading summary', async () => {
  const originalFetch = global.fetch;
  resetPreviewStorage();
  global.window.localStorage.setItem(
    PREVIEW_LAYOUT_STORAGE_KEY,
    JSON.stringify({
      composerLanguage: 'zh-CN',
    }),
  );
  const requests = [];
  global.fetch = async (url, init = {}) => {
    const href = String(url);
    requests.push({
      href,
      method: init.method ?? 'GET',
      body: typeof init.body === 'string' ? JSON.parse(init.body) : undefined,
    });
    if (href.includes('/memory/settings')) {
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (href.includes('/memory/summary')) {
      return new Response(JSON.stringify({ memory: {} }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule();
    await module.fetchBrowserPreviewBootstrap('session-language');
    const previewWorkspaceId = requests[0].body?.workspace_id;

    assert.deepEqual(
      requests.map((entry) => ({ href: entry.href.replace(/^https?:\/\/127\.0\.0\.1:\d+/, ''), method: entry.method })),
      [
        { href: '/memory/settings', method: 'POST' },
        {
          href: `/memory/summary?session_id=session-language&workspace_id=${previewWorkspaceId}`,
          method: 'GET',
        },
      ],
    );
    assert.match(previewWorkspaceId, /^trainer-web-preview-/);
    assert.deepEqual(requests[0].body, {
      session_id: 'session-language',
      workspace_id: previewWorkspaceId,
      response_language: 'zh-CN',
    });
  } finally {
    global.fetch = originalFetch;
  }
});

test('sendBrowserPreviewMessage preserves workspace training state in preview patches', async () => {
  const originalFetch = global.fetch;
  let capturedBody;
  global.fetch = async (url, init) => {
    const href = String(url);
    if (href.endsWith('/session/message')) {
      capturedBody = JSON.parse(init.body);
      return new Response(
        JSON.stringify({
          session_id: 'session-training',
          reply: {
            id: 'assistant-1',
            role: 'assistant',
            content: 'Keep the route boundary narrow and verifiable.',
            metadata: {
              parts: [
                {
                  type: 'tool_call',
                  id: 'call-1',
                  name: 'recall_memory',
                  status: 'completed',
                  args: { focus: 'dependency boundary' },
                },
              ],
            },
          },
          snapshot: createPreviewTrainingSummary(),
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      );
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule();
    const result = await module.sendBrowserPreviewMessage(
      {
        text: 'What should I implement next?',
      },
      'session-training',
    );

    assert.equal(result.sessionId, 'session-training');
    assert.equal(result.message.type, 'state/patch');
    assert.equal(capturedBody.intent, 'coach');
    assert.equal(capturedBody.use_agent_loop, undefined);
    assert.equal(
      result.message.payload.workspaceTrainingState.latestTrainingHandoff.cardTitle,
      'Practice the dependency boundary',
    );
    assert.equal(
      result.message.payload.workspaceTrainingState.latestTrainingHandoff.scenarioPack,
      'remote_workspace',
    );
    assert.equal(
      result.message.payload.workspaceTrainingState.latestTrainingNextHop.candidateType,
      'practice_candidate',
    );
    assert.equal(
      result.message.payload.workspaceTrainingState.latestTrainingNextHop.scenarioPack,
      'remote_workspace',
    );
    assert.equal(
      result.message.payload.workspaceTrainingState.activeTrainingCardRouting.selectedCardId,
      'card-practice-1',
    );
    assert.equal(
      result.message.payload.workspaceTrainingState.reviewArtifact.status,
      'resolved',
    );
    assert.equal(result.message.payload.conversation[0].parts[0].type, 'tool_call');
    assert.equal(result.message.payload.conversation[0].parts[0].name, 'recall_memory');
  } finally {
    global.fetch = originalFetch;
  }
});

test('sendBrowserPreviewMessage keeps non-coach intents on /turn and forwards use_agent_loop', async () => {
  const originalFetch = global.fetch;
  let capturedHref = '';
  let capturedBody;
  global.fetch = async (url, init) => {
    capturedHref = String(url);
    capturedBody = JSON.parse(init.body);
    return new Response(
      JSON.stringify({
        session_id: 'session-review',
        reply: {
          id: 'assistant-review',
          role: 'assistant',
          content: 'Tighten one verification check first.',
        },
        snapshot: { messages: [] },
      }),
      {
        status: 200,
        headers: { 'content-type': 'application/json' },
      },
    );
  };

  try {
    const module = await loadBrowserSidecarModule();
    await module.sendBrowserPreviewMessage(
      {
        text: 'Please review this route.',
        intent: 'review',
        useAgentLoop: true,
      },
      'session-review',
    );

    assert.match(capturedHref, /\/turn$/);
    assert.equal(capturedBody.intent, 'review');
    assert.equal(capturedBody.use_agent_loop, true);
  } finally {
    global.fetch = originalFetch;
  }
});

test('sendBrowserPreviewMessage routes coach turns from plan view through /turn and forwards active_view', async () => {
  const originalFetch = global.fetch;
  let capturedHref = '';
  let capturedBody;
  global.fetch = async (url, init) => {
    capturedHref = String(url);
    capturedBody = JSON.parse(init.body);
    return new Response(
      JSON.stringify({
        session_id: 'session-plan-view',
        reply: {
          id: 'assistant-plan-view',
          role: 'assistant',
          content: 'Current stage, why now, next step, and verify method.',
        },
        snapshot: { messages: [] },
      }),
      {
        status: 200,
        headers: { 'content-type': 'application/json' },
      },
    );
  };

  try {
    const module = await loadBrowserSidecarModule();
    await module.sendBrowserPreviewMessage(
      {
        text: 'Shrink the current stage into one smaller next step.',
        intent: 'coach',
        activeView: 'plan',
        useAgentLoop: true,
      },
      'session-plan-view',
    );

    assert.match(capturedHref, /\/turn$/);
    assert.equal(capturedBody.intent, 'coach');
    assert.equal(capturedBody.active_view, 'plan');
    assert.equal(capturedBody.use_agent_loop, true);
  } finally {
    global.fetch = originalFetch;
  }
});

test('sendBrowserPreviewMessage forwards the typed Resources composer intent without rewriting the message', async () => {
  const originalFetch = global.fetch;
  let capturedHref = '';
  let capturedBody;
  global.fetch = async (url, init) => {
    capturedHref = String(url);
    capturedBody = JSON.parse(init.body);
    return new Response(
      JSON.stringify({
        session_id: 'session-resources-intent',
        reply: {
          id: 'assistant-resources-intent',
          role: 'assistant',
          content: 'Keep the organization proposal reversible.',
        },
        snapshot: { messages: [] },
      }),
      {
        status: 200,
        headers: { 'content-type': 'application/json' },
      },
    );
  };

  try {
    const module = await loadBrowserSidecarModule();
    const text = 'Turn this source into a small study-card candidate set.';
    await module.sendBrowserPreviewMessage(
      {
        text,
        intent: 'coach',
        activeView: 'resources',
        resourceComposerIntent: {
          mode: 'cards',
          resourceIds: ['resource-note-1'],
        },
      },
      'session-resources-intent',
    );

    assert.match(capturedHref, /\/turn$/);
    assert.equal(capturedBody.message, text);
    assert.equal(capturedBody.intent, 'coach');
    assert.equal(capturedBody.formal_plan_mutation, false);
    assert.deepEqual(capturedBody.resource_composer_intent, {
      mode: 'cards',
      resource_ids: ['resource-note-1'],
    });
  } finally {
    global.fetch = originalFetch;
  }
});

test('streamBrowserPreviewMessage uses the session stream route for coach turns', async () => {
  const originalFetch = global.fetch;
  let capturedHref = '';
  let capturedBody;
  global.fetch = async (url, init) => {
    capturedHref = String(url);
    capturedBody = JSON.parse(init.body);
    return new Response(
      `${[
        'event: status',
        'data: {"phase":"preparing_context"}',
        '',
        'event: tool_call',
        'data: {"id":"call-1","name":"recall_memory","arguments":{"focus":"loop"},"step":1}',
        '',
        'event: complete',
        'data: {"tokens":2,"response":{"session_id":"session-stream","reply":{"id":"assistant-stream","role":"assistant","content":"Keep the next slice tiny.","metadata":{"parts":[{"type":"tool_result","callId":"call-1","result":{"ok":true}}]}},"snapshot":{"messages":[]}}}',
        '',
      ].join('\n')}\n`,
      {
        status: 200,
        headers: {
          'content-type': 'text/event-stream',
        },
      },
    );
  };

  try {
    const module = await loadBrowserSidecarModule();
    const completions = [];
    const streamEvents = [];
    await module.streamBrowserPreviewMessage(
      {
        text: 'Coach me through the next slice.',
        useAgentLoop: true,
        resourceComposerIntent: {
          mode: 'locate',
          resourceIds: ['resource-stream-1'],
        },
      },
      'session-stream',
      {
        onStart() {},
        onChunk(message) {
          streamEvents.push(message);
        },
        onComplete(message, nextSessionId) {
          completions.push([message.type, nextSessionId]);
        },
        onError(error) {
          throw new Error(`Unexpected stream error: ${JSON.stringify(error)}`);
        },
      },
    );

    assert.match(capturedHref, /\/session\/message\/stream$/);
    assert.equal(capturedBody.intent, 'coach');
    assert.equal(capturedBody.use_agent_loop, true);
    assert.deepEqual(capturedBody.resource_composer_intent, {
      mode: 'locate',
      resource_ids: ['resource-stream-1'],
    });
    assert.deepEqual(completions, [
      ['stream/complete', 'session-stream'],
      ['state/patch', 'session-stream'],
    ]);
    assert.deepEqual(streamEvents[0], {
      type: 'operation/status',
      payload: {
        tone: 'info',
        message: 'Preparing the current workspace and learning context.',
      },
    });
    assert.equal(
      streamEvents.some(
        (message) =>
          message.type === 'stream/chunk' && String(message.payload?.chunk).includes('preparing_context'),
      ),
      false,
    );
  } finally {
    global.fetch = originalFetch;
  }
});

test('streamBrowserPreviewMessage preserves the four-view sidecar request contract', async () => {
  const originalFetch = global.fetch;
  const capturedRequests = [];
  global.fetch = async (url, init) => {
    capturedRequests.push({
      href: String(url),
      body: JSON.parse(init.body),
    });
    return new Response(
      [
        'event: complete',
        'data: {"tokens":1,"response":{"session_id":"four-view-session","reply":{"id":"assistant-four-view","role":"assistant","content":"A verified reply."},"snapshot":{"messages":[]}}}',
        '',
      ].join('\n'),
      {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      },
    );
  };

  const turns = [
    {
      activeView: 'coach',
      text: 'Coach me through one small verification step.',
      intent: 'coach',
      resourceIds: ['coach-context'],
      path: /\/session\/message\/stream$/,
    },
    {
      activeView: 'plan',
      text: 'Turn this plan stage into one measurable next task.',
      intent: 'plan',
      resourceIds: ['plan-context'],
      path: /\/turn\/stream$/,
    },
    {
      activeView: 'resources',
      text: 'Find the important evidence in the selected source.',
      resourceIds: ['resource-context'],
      resourceComposerIntent: {
        mode: 'locate',
        resourceIds: ['resource-context'],
      },
      path: /\/turn\/stream$/,
    },
    {
      activeView: 'training',
      text: 'Give me one short practice prompt from this context.',
      intent: 'coach',
      resourceIds: ['training-context'],
      path: /\/turn\/stream$/,
    },
  ];

  try {
    const module = await loadBrowserSidecarModule();
    for (const turn of turns) {
      await module.streamBrowserPreviewMessage(
        turn,
        `session-${turn.activeView}`,
        {
          onStart() {},
          onChunk() {},
          onComplete() {},
          onError(error) {
            throw new Error(`Unexpected stream error: ${JSON.stringify(error)}`);
          },
        },
      );
    }

    assert.equal(capturedRequests.length, turns.length);
    for (const [index, turn] of turns.entries()) {
      const request = capturedRequests[index];
      assert.match(request.href, turn.path);
      assert.equal(request.body.message, turn.text);
      assert.equal(request.body.active_view, turn.activeView);
      assert.deepEqual(request.body.resource_ids, turn.resourceIds);
      assert.equal(request.body.stream, true);
      assert.match(request.body.stream_id, /^stream-/);
    }
    assert.equal(capturedRequests[0].body.intent, 'coach');
    assert.equal(capturedRequests[1].body.intent, 'plan');
    assert.equal(capturedRequests[2].body.intent, 'resources');
    assert.deepEqual(capturedRequests[2].body.resource_composer_intent, {
      mode: 'locate',
      resource_ids: ['resource-context'],
    });
    assert.equal(capturedRequests[3].body.intent, 'coach');
  } finally {
    global.fetch = originalFetch;
  }
});

test('streamBrowserPreviewMessage parses CRLF-separated SSE chunks split across reads before completion', async () => {
  const originalFetch = global.fetch;
  let capturedHref = '';
  const events = [];
  global.fetch = async (url, init) => {
    capturedHref = String(url);
    const sse = [
      'event: status',
      'data: {"phase":"preparing_context"}',
      '',
      'event: message',
      'data: {"chunk":"The first visible line arrives now."}',
      '',
      'event: complete',
      'data: {"tokens":4,"response":{"session_id":"session-crlf-stream","reply":{"id":"assistant-crlf-stream","role":"assistant","content":"The first visible line arrives now."},"snapshot":{"messages":[]}}}',
      '',
    ].join('\r\n');
    const splitAt = sse.indexOf('\r\n') + 1;
    const encoder = new TextEncoder();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(sse.slice(0, splitAt)));
        controller.enqueue(encoder.encode(sse.slice(splitAt)));
        controller.close();
      },
    });
    return new Response(body, {
      status: 200,
      headers: {
        'content-type': 'text/event-stream',
      },
    });
  };

  try {
    const module = await loadBrowserSidecarModule();
    await module.streamBrowserPreviewMessage(
      {
        text: 'Show me one short streamed reply.',
        responseLanguage: 'en-US',
      },
      'session-crlf-stream',
      {
        onStart(message) {
          events.push(message);
        },
        onChunk(message) {
          events.push(message);
        },
        onComplete(message) {
          events.push(message);
        },
        onError(message) {
          events.push(message);
        },
      },
    );

    assert.match(capturedHref, /\/session\/message\/stream$/);
    assert.deepEqual(
      events.map((event) => event.type),
      ['stream/start', 'operation/status', 'stream/chunk', 'stream/complete', 'state/patch'],
    );
    assert.match(events[2].payload.chunk, /first visible line arrives now/i);
    assert.equal(events.some((event) => event.type === 'stream/error'), false);
  } finally {
    global.fetch = originalFetch;
  }
});

test('streamBrowserPreviewMessage keeps one messageId across stream callbacks', async () => {
  const originalFetch = global.fetch;
  const events = [];
  global.fetch = async () => new Response(
    [
      'event: tool_call',
      'data: {"id":"call-1","name":"recall_memory","arguments":{},"step":1}',
      '',
      'event: tool_result',
      'data: {"id":"call-1","name":"recall_memory","ok":true,"result":{},"step":1}',
      '',
      'event: step',
      'data: {"index":1,"stop_reason":null}',
      '',
      'event: message',
      'data: {"chunk":"A short reply."}',
      '',
      'event: complete',
      'data: {"tokens":2,"response":{"session_id":"session-message-id","reply":{"id":"assistant-message-id","role":"assistant","content":"A short reply."},"snapshot":{"messages":[]}}}',
      '',
    ].join('\n'),
    {
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
    },
  );

  try {
    const module = await loadBrowserSidecarModule();
    await module.streamBrowserPreviewMessage(
      { text: 'Keep the reply short.', useAgentLoop: true },
      'session-message-id',
      {
        onStart(message) {
          events.push(message);
        },
        onChunk(message) {
          events.push(message);
        },
        onComplete(message) {
          events.push(message);
        },
        onError(message) {
          events.push(message);
        },
      },
    );

    const streamMessageIds = events
      .filter((event) => event.type.startsWith('stream/'))
      .map((event) => event.payload.messageId);
    assert.ok(streamMessageIds.length >= 5);
    assert.equal(new Set(streamMessageIds).size, 1);
    assert.equal(typeof streamMessageIds[0], 'string');
    assert.equal(events.some((event) => event.type === 'stream/error'), false);
  } finally {
    global.fetch = originalFetch;
  }
});

test('streamBrowserPreviewMessage reports reader failures with the active messageId', async () => {
  const originalFetch = global.fetch;
  const events = [];
  global.fetch = async () => {
    const encoder = new TextEncoder();
    let sentChunk = false;
    const body = new ReadableStream({
      pull(controller) {
        if (!sentChunk) {
          sentChunk = true;
          controller.enqueue(encoder.encode('event: message\ndata: {"chunk":"Partial reply."}\n\n'));
          return;
        }
        controller.error(new Error('network connection reset'));
      },
    });
    return new Response(body, {
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
    });
  };

  try {
    const module = await loadBrowserSidecarModule();
    await module.streamBrowserPreviewMessage(
      { text: 'Start a reply.' },
      'session-reader-error',
      {
        onStart(message) {
          events.push(message);
        },
        onChunk(message) {
          events.push(message);
        },
        onComplete(message) {
          events.push(message);
        },
        onError(message) {
          events.push(message);
        },
      },
    );

    assert.deepEqual(
      events.map((event) => event.type),
      ['stream/start', 'stream/chunk', 'stream/error'],
    );
    assert.equal(events.at(-1).payload.category, 'network');
    assert.equal(events.at(-1).payload.messageId, events[0].payload.messageId);
  } finally {
    global.fetch = originalFetch;
  }
});

test('streamBrowserPreviewMessage rejects EOF without completion and ignores events after an SSE error', async () => {
  const originalFetch = global.fetch;
  const makeCallbacks = (events) => ({
    onStart(message) {
      events.push(message);
    },
    onChunk(message) {
      events.push(message);
    },
    onComplete(message) {
      events.push(message);
    },
    onError(message) {
      events.push(message);
    },
  });

  try {
    const module = await loadBrowserSidecarModule();
    const eofEvents = [];
    global.fetch = async () => new Response(
      'event: message\ndata: {"chunk":"Partial reply."}\n\n',
      {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      },
    );
    await module.streamBrowserPreviewMessage(
      { text: 'End the stream early.' },
      'session-eof-error',
      makeCallbacks(eofEvents),
    );
    assert.deepEqual(
      eofEvents.map((event) => event.type),
      ['stream/start', 'stream/chunk', 'stream/error'],
    );
    assert.equal(eofEvents.at(-1).payload.category, 'malformed_response');
    assert.equal(eofEvents.at(-1).payload.messageId, eofEvents[0].payload.messageId);

    const terminalEvents = [];
    global.fetch = async () => new Response(
      [
        'event: error',
        'data: upstream failed',
        '',
        'event: complete',
        'data: {"tokens":1,"response":{"reply":{"content":"should not complete"}}}',
        '',
      ].join('\n'),
      {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      },
    );
    await module.streamBrowserPreviewMessage(
      { text: 'Stop on the provider error.' },
      'session-terminal-error',
      makeCallbacks(terminalEvents),
    );
    assert.deepEqual(
      terminalEvents.map((event) => event.type),
      ['stream/start', 'stream/error'],
    );
    assert.equal(terminalEvents[1].payload.messageId, terminalEvents[0].payload.messageId);
  } finally {
    global.fetch = originalFetch;
  }
});

test('streamBrowserPreviewMessage routes coach turns from training view through /turn/stream and forwards active_view', async () => {
  const originalFetch = global.fetch;
  let capturedHref = '';
  let capturedBody;
  global.fetch = async (url, init) => {
    capturedHref = String(url);
    capturedBody = JSON.parse(init.body);
    return new Response(
      `${[
        'event: complete',
        'data: {"tokens":2,"response":{"session_id":"session-training-stream","reply":{"id":"assistant-training-stream","role":"assistant","content":"Start with one primer, then try one tiny verification step."},"snapshot":{"messages":[]}}}',
        '',
      ].join('\n')}\n`,
      {
        status: 200,
        headers: {
          'content-type': 'text/event-stream',
        },
      },
    );
  };

  try {
    const module = await loadBrowserSidecarModule();
    const completions = [];
    await module.streamBrowserPreviewMessage(
      {
        text: 'Give me one learn-first training card.',
        intent: 'coach',
        activeView: 'training',
        useAgentLoop: true,
      },
      'session-training-stream',
      {
        onStart() {},
        onChunk() {},
        onComplete(message, nextSessionId) {
          completions.push([message.type, nextSessionId]);
        },
        onError(error) {
          throw new Error(`Unexpected stream error: ${JSON.stringify(error)}`);
        },
      },
    );

    assert.match(capturedHref, /\/turn\/stream$/);
    assert.equal(capturedBody.intent, 'coach');
    assert.equal(capturedBody.active_view, 'training');
    assert.equal(capturedBody.use_agent_loop, true);
    assert.deepEqual(completions, [
      ['stream/complete', 'session-training-stream'],
      ['state/patch', 'session-training-stream'],
    ]);
  } finally {
    global.fetch = originalFetch;
  }
});

test('uploadBrowserPreviewResources keeps workspace training state during preview refresh', async () => {
  const originalFetch = global.fetch;
  global.fetch = async (url) => {
    const href = String(url);
    if (href.endsWith('/resource/upload')) {
      return new Response(
        JSON.stringify({
          id: 'resource-1',
          title: 'Route notes',
          kind: 'markdown',
          status: 'ready',
          summary: 'Dependency notes',
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      );
    }
    if (href.endsWith('/resource/index')) {
      return new Response(
        JSON.stringify({
          id: 'resource-1',
          title: 'Route notes',
          kind: 'markdown',
          status: 'ready',
          parse_status: 'parsed',
          index_status: 'indexed',
          summary: 'Dependency notes',
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      );
    }
    if (href.includes('/memory/summary')) {
      return new Response(JSON.stringify(createPreviewTrainingSummary()), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule();
    const result = await module.uploadBrowserPreviewResources(
      [
        {
          name: 'route-notes.md',
          kind: 'markdown',
          content: '# Route notes',
        },
      ],
      'session-training',
    );

    assert.equal(result.sessionId, 'session-training');
    assert.equal(result.uploadedCount, 1);
    assert.equal(result.indexedCount, 1);
    assert.equal(result.failedIndexCount, 0);
    assert.equal(result.patch.workspaceTrainingState.selectedCardId, 'card-practice-1');
    assert.equal(
      result.patch.workspaceTrainingState.latestTrainingHandoff.learnerDeliverables[0],
      'Implement one route with one clean dependency seam.',
    );
    assert.equal(
      result.patch.workspaceTrainingState.latestTrainingHandoff.scenarioPack,
      'remote_workspace',
    );
  } finally {
    global.fetch = originalFetch;
  }
});

test('uploadBrowserPreviewResources sends live URL imports as network-enabled URL sources', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousBootstrap = global.window.__TRAINER_BOOTSTRAP__;
  const uploadBodies = [];
  const indexBodies = [];
  global.window.__TRAINER_BROWSER_PREVIEW__ = false;
  delete global.window.__TRAINER_BOOTSTRAP__;
  global.fetch = async (url, init = {}) => {
    const href = String(url);
    if (href.endsWith('/resource/upload')) {
      uploadBodies.push(JSON.parse(init.body));
      return new Response(
        JSON.stringify({
          id: 'resource-url-1',
          title: 'Example',
          kind: 'url',
          status: 'indexing',
          source: 'https://example.com/docs',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    if (href.endsWith('/resource/index')) {
      indexBodies.push(JSON.parse(init.body));
      return new Response(
        JSON.stringify({
          id: 'resource-url-1',
          title: 'Example',
          kind: 'url',
          status: 'ready',
          parse_status: 'parsed',
          index_status: 'indexed',
          source: 'https://example.com/docs',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    if (href.includes('/memory/summary')) {
      return new Response(JSON.stringify({ resources: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule();
    const result = await module.uploadBrowserPreviewResources(
      [
        {
          name: 'Example',
          kind: 'url',
          content: '',
          source: 'https://example.com/docs',
        },
      ],
      'session-url-import',
    );

    assert.equal(result.uploadedCount, 1);
    assert.equal(result.indexedCount, 1);
    assert.equal(uploadBodies[0].kind, 'url');
    assert.equal(uploadBodies[0].source_type, 'url');
    assert.equal(uploadBodies[0].source, 'https://example.com/docs');
    assert.equal(uploadBodies[0].content, undefined);
    assert.equal(indexBodies[0].enable_network, true);
  } finally {
    global.fetch = originalFetch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    if (previousBootstrap === undefined) {
      delete global.window.__TRAINER_BOOTSTRAP__;
    } else {
      global.window.__TRAINER_BOOTSTRAP__ = previousBootstrap;
    }
  }
});

test('uploadBrowserPreviewResources does not report a 200 response with failed indexing as indexed', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousBootstrap = global.window.__TRAINER_BOOTSTRAP__;
  global.window.__TRAINER_BROWSER_PREVIEW__ = false;
  delete global.window.__TRAINER_BOOTSTRAP__;
  global.fetch = async (url) => {
    const href = String(url);
    if (href.endsWith('/resource/upload')) {
      return new Response(
        JSON.stringify({
          id: 'resource-index-failed',
          title: 'Unavailable URL',
          kind: 'url',
          source: 'https://example.com/unavailable',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    if (href.endsWith('/resource/index')) {
      return new Response(
        JSON.stringify({
          id: 'resource-index-failed',
          title: 'Unavailable URL',
          kind: 'url',
          parse_status: 'failed',
          index_status: 'failed',
          source: 'https://example.com/unavailable',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    if (href.includes('/memory/summary')) {
      return new Response(JSON.stringify({ resources: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const module = await loadBrowserSidecarModule();
    const result = await module.uploadBrowserPreviewResources(
      [
        {
          name: 'Unavailable URL',
          kind: 'url',
          content: '',
          source: 'https://example.com/unavailable',
        },
      ],
      'session-index-failed',
    );

    assert.equal(result.uploadedCount, 1);
    assert.equal(result.indexedCount, 0);
    assert.equal(result.failedIndexCount, 1);
  } finally {
    global.fetch = originalFetch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    if (previousBootstrap === undefined) {
      delete global.window.__TRAINER_BOOTSTRAP__;
    } else {
      global.window.__TRAINER_BOOTSTRAP__ = previousBootstrap;
    }
  }
});

test('fetchBrowserPreviewBootstrap uses the process-local preview provider key', async () => {
  const originalFetch = global.fetch;
  const module = await seedPreviewProviderState(
    {
      configured: true,
      name: 'MiniMax',
      baseUrl: 'http://47.107.101.18:3000/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      contextWindowTokens: 64000,
      maxOutputTokens: 8000,
      modelTokenLimits: {
        'MiniMax-M3': {
          contextWindowTokens: 64000,
          maxOutputTokens: 8000,
        },
      },
      profileId: 'minimax-core',
      profileLabel: 'MiniMax Core',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: true,
        structuredOutput: true,
        streaming: true,
      },
      availableModels: ['MiniMax-M3'],
      resolvedModel: 'MiniMax-M3',
      modelListStatus: 'idle',
    },
    'sk-test',
  );

  global.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/memory/settings')) {
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (href.includes('/memory/summary')) {
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const result = await module.fetchBrowserPreviewBootstrap('session-provider-overlay');

    assert.equal(result.message.payload.providerConfig.name, 'MiniMax');
    assert.equal(result.message.payload.providerConfig.apiKeyConfigured, true);
    assert.equal(
      result.message.payload.providerConfig.requestDefaults.extra_body.thinking.type,
      'disabled',
    );
    assert.deepEqual(result.message.payload.providerConfig.availableModels, ['MiniMax-M3']);
    assert.equal(result.message.payload.providerConfig.modelListStatus, 'ready');
    assert.equal(result.message.payload.providerConfig.lastTestResult, undefined);
    assert.equal(global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY), null);
    assert.equal(result.message.payload.connection.provider.name, 'MiniMax');
    assert.equal(result.message.payload.connection.provider.model, 'MiniMax-M3');
  } finally {
    global.fetch = originalFetch;
  }
});

test('fetchBrowserPreviewBootstrap drops preview last-test state when protocol identity changed', async () => {
  const originalFetch = global.fetch;
  const module = await seedPreviewProviderState(
    {
      configured: true,
      name: 'MiniMax',
      baseUrl: 'http://47.107.101.18:3000/v1',
      model: 'MiniMax-M3',
      protocol: 'anthropic_messages',
      profileId: 'minimax-core',
      profileLabel: 'MiniMax Core',
      capabilities: {
        chat: true,
        responses: false,
        vision: true,
        embeddings: false,
        tools: true,
        jsonSchema: false,
        structuredOutput: false,
        streaming: true,
      },
      availableModels: ['MiniMax-M3'],
      resolvedModel: 'MiniMax-M3',
      modelListStatus: 'idle',
    },
    'sk-test',
  );

  global.fetch = async (url) => {
    const href = String(url);
    if (href.includes('/memory/settings')) {
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (href.includes('/memory/summary')) {
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const result = await module.fetchBrowserPreviewBootstrap('session-provider-protocol-mismatch');

    assert.equal(result.message.payload.providerConfig.protocol, 'anthropic_messages');
    assert.equal(result.message.payload.providerConfig.lastTestResult, undefined);
  } finally {
    global.fetch = originalFetch;
  }
});

test('fetchBrowserPreviewBootstrap preserves remote, debug, and function coaching scenarios', async () => {
  const originalFetch = global.fetch;
  const scenarios = ['remote_workspace', 'debug_loop', 'function_guidance'];

  try {
    const module = await loadBrowserSidecarModule();
    for (const scenario of scenarios) {
      global.fetch = async (url) => {
        const href = String(url);
        if (href.includes('/memory/settings')) {
          return new Response(JSON.stringify({ ok: true }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          });
        }
        if (href.includes('/memory/summary')) {
          return new Response(
            JSON.stringify({
              coaching_state: {
                scenario,
                answer_mode: 'balanced',
                learner_signal: 'blocked',
                summary: `${scenario} summary`,
                next_step: `${scenario} next`,
              },
            }),
            {
              status: 200,
              headers: { 'content-type': 'application/json' },
            },
          );
        }
        throw new Error(`Unexpected fetch request: ${href}`);
      };

      const result = await module.fetchBrowserPreviewBootstrap(`session-${scenario}`);
      assert.equal(result.message.payload.coachingState.scenario, scenario);
      assert.equal(result.message.payload.coachingState.answerMode, 'balanced');
      assert.equal(result.message.payload.coachingState.learnerSignal, 'blocked');
    }
  } finally {
    global.fetch = originalFetch;
  }
});

test('sendBrowserPreviewMessage forwards the saved preview provider override and api key', async () => {
  const originalFetch = global.fetch;
  const module = await seedPreviewProviderState(
    {
      configured: true,
      name: 'MiniMax',
      baseUrl: 'http://47.107.101.18:3000/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      contextWindowTokens: 64000,
      maxOutputTokens: 8000,
      modelTokenLimits: {
        'MiniMax-M3': {
          contextWindowTokens: 64000,
          maxOutputTokens: 8000,
        },
      },
      profileId: 'minimax-core',
      profileLabel: 'MiniMax Core',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: true,
        structuredOutput: true,
        streaming: true,
      },
      availableModels: ['MiniMax-M3'],
      resolvedModel: 'MiniMax-M3',
      modelListStatus: 'ready',
    },
    'sk-preview',
  );

  let capturedBody;
  global.fetch = async (url, init) => {
    const href = String(url);
    if (href.endsWith('/session/message')) {
      capturedBody = JSON.parse(init.body);
      return new Response(
        JSON.stringify({
          session_id: 'session-preview-provider',
          snapshot: createPreviewTrainingSummary(),
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      );
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    await module.sendBrowserPreviewMessage(
      {
        text: 'Help me continue the remote setup.',
      },
      'session-preview-provider',
    );

    assert.equal(capturedBody.provider.name, 'MiniMax');
    assert.equal(capturedBody.provider.baseUrl, 'http://47.107.101.18:3000/v1');
    assert.equal(capturedBody.provider.model, 'MiniMax-M3');
    assert.equal(capturedBody.provider.requestDefaults.extra_body.thinking.type, 'disabled');
    assert.equal(capturedBody.api_key, 'sk-preview');
    assert.equal(global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY), null);
    assert.ok(
      !global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY)?.includes('sk-preview'),
    );
  } finally {
    global.fetch = originalFetch;
  }
});

test('saveBrowserPreviewProvider keeps the api key in process memory and clears legacy storage', async () => {
  const module = await loadBrowserSidecarModule();
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  global.window.__TRAINER_PREVIEW_STORAGE_KEY__ = PREVIEW_LAYOUT_STORAGE_KEY;
  global.window.localStorage.setItem(
    PREVIEW_LAYOUT_STORAGE_KEY,
    JSON.stringify({ composerLanguage: 'zh-CN' }),
  );
  global.window.localStorage.setItem(
    PREVIEW_PROVIDER_SECRETS_STORAGE_KEY,
    JSON.stringify({
      apiKeysByProvider: {
        'profile:minimax': 'sk-legacy-preview-key',
      },
    }),
  );

  const result = await module.saveBrowserPreviewProvider(
    {
      name: 'MiniMax',
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'http://47.107.101.18:3000/v1',
      model: 'MiniMax-M3',
      contextWindowTokens: 64000,
      maxOutputTokens: 8000,
      apiKey: 'sk-preview-save',
    },
    'session-save-provider',
  );

  const providerPatch = result.messages[0].payload.providerConfig;
  assert.equal(result.sessionId, 'session-save-provider');
  assert.equal(providerPatch.configured, true);
  assert.equal(providerPatch.apiKeyConfigured, true);
  assert.equal(providerPatch.profileId, 'minimax');
  assert.equal(providerPatch.providerProfiles.length, 1);
  assert.equal(providerPatch.contextWindowTokens, 64000);
  assert.equal(providerPatch.maxOutputTokens, 8000);
  assert.equal(providerPatch.modelTokenLimits['MiniMax-M3'].contextWindowTokens, 64000);
  assert.equal(providerPatch.requestDefaults.extra_body.thinking.type, 'disabled');
  assert.ok(result.messages[1].payload.message.trim().length > 0);

  assert.equal(global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY), null);
  assert.ok(
    !global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY)?.includes('sk-preview-save'),
  );
  assert.ok(
    !global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY)?.includes(
      'sk-legacy-preview-key',
    ),
  );
  const layoutPersisted = global.window.localStorage.getItem(PREVIEW_LAYOUT_STORAGE_KEY) ?? '';
  assert.equal(layoutPersisted.includes('sk-preview-save'), false);
  assert.equal(layoutPersisted.includes('sk-legacy-preview-key'), false);
  assert.equal(JSON.stringify(providerPatch).includes('sk-preview-save'), false);
  assert.match(layoutPersisted, /previewProviderConfig/);
});

test('saveBrowserPreviewProvider supplies the production default name when a complete draft leaves it blank', async () => {
  const module = await loadBrowserSidecarModule();

  const result = await module.saveBrowserPreviewProvider(
    {
      name: '',
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'preview-chat',
      apiKey: 'sk-preview-default-name',
    },
    'session-save-default-name',
  );

  const providerPatch = result.messages[0].payload.providerConfig;
  assert.equal(result.sessionId, 'session-save-default-name');
  assert.equal(providerPatch.configured, true);
  assert.equal(providerPatch.name, 'custom-openai-compatible');
  assert.equal(providerPatch.baseUrl, 'http://localhost:1234/v1');
  assert.equal(providerPatch.model, 'preview-chat');
  assert.equal(providerPatch.apiKeyConfigured, true);
});

test('useBrowserPreviewProviderTemplate uses the MiniMax starter and keeps the Chinese next step visible', async () => {
  global.window.localStorage.setItem(
    PREVIEW_LAYOUT_STORAGE_KEY,
    JSON.stringify({ composerLanguage: 'zh-CN' }),
  );
  const module = await loadBrowserSidecarModule();

  const result = await module.useBrowserPreviewProviderTemplate('session-minimax-template');
  const providerPatch = result.messages[0].payload.providerConfig;
  const status = result.messages[1].payload;

  assert.equal(result.sessionId, 'session-minimax-template');
  assert.equal(providerPatch.name, 'MiniMax');
  assert.equal(providerPatch.baseUrl, 'https://api.minimaxi.com/v1');
  assert.equal(providerPatch.model, 'MiniMax-M3');
  assert.equal(providerPatch.apiKeyConfigured, false);
  assert.equal(status.tone, 'success');
  assert.equal(status.message, '已填好 MiniMax 模板。填好 API key 后再测试。');
});

test('saveBrowserPreviewProvider updates an active profile label to the entered connection name', async () => {
  const module = await seedPreviewProviderState(
    {
      configured: true,
      name: 'MiniMax',
      baseUrl: 'https://api.minimaxi.com/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      profileId: 'minimax-core',
      profileLabel: 'MiniMax Core',
      providerProfiles: [
        {
          id: 'minimax-core',
          label: 'MiniMax Core',
          name: 'MiniMax',
          protocol: 'openai_chat_completions_compatible',
          baseUrl: 'https://api.minimaxi.com/v1',
          model: 'MiniMax-M3',
        },
      ],
    },
  );

  const result = await module.saveBrowserPreviewProvider(
    {
      name: 'custom-openai-compatible',
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'preview-chat',
      apiKey: 'sk-preview-profile-label',
    },
    'session-save-profile-label',
  );
  const providerPatch = result.messages[0].payload.providerConfig;

  assert.equal(providerPatch.profileId, 'minimax-core');
  assert.equal(providerPatch.name, 'custom-openai-compatible');
  assert.equal(providerPatch.profileLabel, 'custom-openai-compatible');
  assert.equal(providerPatch.providerProfiles[0].label, 'custom-openai-compatible');
  assert.equal(providerPatch.providerDashboard.currentProfile.label, 'custom-openai-compatible');
});

test('browser preview can find models, choose one, and save without a connection name', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousBootstrap = global.window.__TRAINER_BOOTSTRAP__;
  const module = await loadBrowserSidecarModule();
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  global.window.__TRAINER_BOOTSTRAP__ = {};
  let fetchCalls = 0;
  global.fetch = async () => {
    fetchCalls += 1;
    throw new Error('Fixture Preview must not contact a sidecar for model discovery.');
  };

  try {
    const discovery = await module.refreshBrowserPreviewProviderModels(
      {
        name: '',
        baseUrl: 'http://localhost:1234/v1',
        apiKey: 'sk-preview-model-flow',
        protocol: 'openai_chat_completions_compatible',
        model: '',
      },
      'session-find-models',
    );
    const availableModels = discovery.messages[0].payload.providerConfig.availableModels;
    const selectedModel = availableModels[1];

    const saved = await module.saveBrowserPreviewProvider(
      {
        name: '',
        baseUrl: 'http://localhost:1234/v1',
        apiKey: 'sk-preview-model-flow',
        protocol: 'openai_chat_completions_compatible',
        model: selectedModel,
        catalogModels: availableModels,
      },
      'session-save-selected-model',
    );
    const providerPatch = saved.messages[0].payload.providerConfig;

    assert.equal(fetchCalls, 0);
    assert.ok(selectedModel);
    assert.equal(providerPatch.configured, true);
    assert.equal(providerPatch.name, 'custom-openai-compatible');
    assert.equal(providerPatch.model, selectedModel);
    assert.equal(providerPatch.apiKeyConfigured, true);
    assert.ok(providerPatch.availableModels.includes(selectedModel));
  } finally {
    global.fetch = originalFetch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    if (previousBootstrap === undefined) {
      delete global.window.__TRAINER_BOOTSTRAP__;
    } else {
      global.window.__TRAINER_BOOTSTRAP__ = previousBootstrap;
    }
  }
});

test('browser preview keeps draft model discovery scoped away from the saved connection', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const module = await seedPreviewProviderState(
    {
      configured: true,
      name: 'Saved provider',
      baseUrl: 'http://saved.example/v1',
      model: 'saved-model',
      protocol: 'openai_chat_completions_compatible',
      availableModels: ['saved-model', 'saved-model-fast'],
      modelListStatus: 'ready',
    },
    'sk-saved-provider',
  );
  delete global.window.__TRAINER_BROWSER_PREVIEW__;
  let capturedBody;
  global.fetch = async (url, init) => {
    const href = String(url);
    if (!href.endsWith('/provider/models')) {
      throw new Error(`Unexpected fetch request: ${href}`);
    }
    capturedBody = JSON.parse(init.body);
    return new Response(
      JSON.stringify({
        ok: true,
        available_models: ['draft-model-a', 'draft-model-b'],
        resolved_model: 'draft-model-a',
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const result = await module.refreshBrowserPreviewProviderModels(
      {
        name: 'Draft provider',
        baseUrl: 'http://draft.example/v1',
        apiKey: 'sk-draft-provider',
        protocol: 'openai_chat_completions_compatible',
        model: '',
      },
      'session-draft-model-scope',
    );
    const providerPatch = result.messages[0].payload.providerConfig;

    assert.equal(capturedBody.provider.baseUrl, 'http://draft.example/v1');
    assert.equal(capturedBody.provider.model, '');
    assert.deepEqual(providerPatch.availableModels, ['saved-model', 'saved-model-fast']);
    assert.equal(providerPatch.modelListStatus, 'ready');
    assert.deepEqual(providerPatch.modelListing, {
      source: 'draft',
      name: 'Draft provider',
      baseUrl: 'http://draft.example/v1',
      protocol: 'openai_chat_completions_compatible',
      protocolFamily: 'openai',
      model: 'draft-model-a',
      availableModels: ['draft-model-a', 'draft-model-b'],
      resolvedModel: 'draft-model-a',
      modelTokenLimits: undefined,
      fetchedAt: providerPatch.modelListing.fetchedAt,
      errorCategory: undefined,
      retryable: undefined,
      statusCode: undefined,
      status: 'ready',
    });
    assert.equal(JSON.stringify(providerPatch).includes('sk-draft-provider'), false);
  } finally {
    global.fetch = originalFetch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
  }
});

test('browser preview rejects policy-blocked provider saves before writing provider state', async () => {
  const module = await loadBrowserSidecarModule();
  const persistedBefore = global.window.localStorage.getItem(PREVIEW_LAYOUT_STORAGE_KEY);

  await assert.rejects(
    () =>
      module.saveBrowserPreviewProvider(
        {
          name: 'Restricted connection',
          protocol: 'openai_chat_completions_compatible',
          baseUrl: 'https://example.test/v1',
          model: 'not-listed-model',
          allowedModels: ['safe-model'],
          apiKey: 'sk-do-not-save',
        },
        'session-save-not-allowed',
      ),
    /not available for this connection/,
  );
  assert.equal(global.window.localStorage.getItem(PREVIEW_LAYOUT_STORAGE_KEY), persistedBefore);
  assert.equal(global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY), null);

  await assert.rejects(
    () =>
      module.saveBrowserPreviewProvider(
        {
          name: 'Restricted connection',
          protocol: 'openai_chat_completions_compatible',
          baseUrl: 'https://example.test/v1',
          model: 'blocked-model',
          allowedModels: ['blocked-model'],
          deniedModels: ['blocked-model'],
          apiKey: 'sk-do-not-save',
        },
        'session-save-denied',
      ),
    /blocked for this connection/,
  );
  assert.equal(global.window.localStorage.getItem(PREVIEW_LAYOUT_STORAGE_KEY), persistedBefore);
  assert.equal(global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY), null);
});

test('browser preview rejects profile switches that violate the target profile policy', async () => {
  const module = await seedPreviewProviderState({
    configured: true,
    name: 'Allowed connection',
    baseUrl: 'https://example.test/v1',
    model: 'safe-model',
    protocol: 'openai_chat_completions_compatible',
    profileId: 'allowed',
    allowedModels: ['safe-model'],
    providerProfiles: [
      {
        id: 'allowed',
        label: 'Allowed connection',
        name: 'Allowed connection',
        baseUrl: 'https://example.test/v1',
        model: 'safe-model',
        protocol: 'openai_chat_completions_compatible',
        allowedModels: ['safe-model'],
      },
      {
        id: 'not-allowed',
        label: 'Needs correction',
        name: 'Needs correction',
        baseUrl: 'https://example.test/v1',
        model: 'not-listed-model',
        protocol: 'openai_chat_completions_compatible',
        allowedModels: ['safe-model'],
      },
      {
        id: 'denied',
        label: 'Blocked model',
        name: 'Blocked model',
        baseUrl: 'https://example.test/v1',
        model: 'blocked-model',
        protocol: 'openai_chat_completions_compatible',
        allowedModels: ['blocked-model'],
        deniedModels: ['blocked-model'],
      },
      {
        id: 'target-policy',
        label: 'Target policy',
        name: 'Target policy',
        baseUrl: 'https://example.test/v1',
        model: 'target-model',
        protocol: 'openai_chat_completions_compatible',
        allowedModels: ['target-model'],
        deniedModels: ['legacy-model'],
      },
    ],
  });
  const persistedBefore = global.window.localStorage.getItem(PREVIEW_LAYOUT_STORAGE_KEY);

  await assert.rejects(
    () => module.switchBrowserPreviewProviderProfile('not-allowed', 'session-profile-not-allowed'),
    /not available for this connection/,
  );
  assert.equal(global.window.localStorage.getItem(PREVIEW_LAYOUT_STORAGE_KEY), persistedBefore);

  await assert.rejects(
    () => module.switchBrowserPreviewProviderProfile('denied', 'session-profile-denied'),
    /blocked for this connection/,
  );
  assert.equal(global.window.localStorage.getItem(PREVIEW_LAYOUT_STORAGE_KEY), persistedBefore);

  const switched = await module.switchBrowserPreviewProviderProfile(
    'target-policy',
    'session-profile-target-policy',
  );
  const providerPatch = switched.messages[0].payload.providerConfig;
  assert.equal(providerPatch.profileId, 'target-policy');
  assert.deepEqual(providerPatch.allowedModels, ['target-model']);
  assert.deepEqual(providerPatch.deniedModels, ['legacy-model']);
});

test('fixture Preview switches a complete saved profile locally without contacting its endpoint', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousBootstrap = global.window.__TRAINER_BOOTSTRAP__;
  const savedProvider = {
    configured: true,
    name: 'Preview primary',
    baseUrl: 'http://localhost:1234/v1',
    model: 'preview-chat',
    protocol: 'openai_chat_completions_compatible',
    apiKeyConfigured: true,
    profileId: 'preview-primary',
    profileLabel: 'Preview primary',
    profileMode: 'direct',
    providerProfiles: [
      {
        id: 'preview-primary',
        label: 'Preview primary',
        name: 'Preview primary',
        baseUrl: 'http://localhost:1234/v1',
        model: 'preview-chat',
        protocol: 'openai_chat_completions_compatible',
      },
      {
        id: 'preview-backup',
        label: 'Preview backup',
        name: 'Preview backup',
        baseUrl: 'http://localhost:1235/v1',
        model: 'preview-reasoning',
        protocol: 'openai_chat_completions_compatible',
      },
    ],
  };
  const module = await seedPreviewProviderState(savedProvider);
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  global.window.__TRAINER_BOOTSTRAP__ = { providerConfig: savedProvider };
  global.fetch = async () => {
    throw new Error('fixture profile switches must stay local');
  };

  try {
    const result = await module.switchBrowserPreviewProviderProfile(
      'preview-backup',
      'session-fixture-profile-switch',
    );
    const providerPatch = result.messages[0].payload.providerConfig;

    assert.equal(result.sessionId, 'session-fixture-profile-switch');
    assert.equal(providerPatch.profileId, 'preview-backup');
    assert.equal(providerPatch.name, 'Preview backup');
    assert.equal(providerPatch.model, 'preview-reasoning');
    assert.equal(result.messages[1].payload.tone, 'success');
    assert.match(result.messages[1].payload.message, /Switched to 'Preview backup'/);
  } finally {
    global.fetch = originalFetch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    if (previousBootstrap === undefined) {
      delete global.window.__TRAINER_BOOTSTRAP__;
    } else {
      global.window.__TRAINER_BOOTSTRAP__ = previousBootstrap;
    }
  }
});

test('browser preview rejects restricted model switches before writing provider state', async () => {
  const module = await seedPreviewProviderState({
    configured: true,
    name: 'Restricted connection',
    baseUrl: 'https://example.test/v1',
    model: 'safe-model',
    protocol: 'openai_chat_completions_compatible',
    profileId: 'restricted',
    allowedModels: ['safe-model', 'blocked-model'],
    deniedModels: ['blocked-model'],
    providerProfiles: [
      {
        id: 'restricted',
        label: 'Restricted connection',
        name: 'Restricted connection',
        baseUrl: 'https://example.test/v1',
        model: 'safe-model',
        protocol: 'openai_chat_completions_compatible',
        allowedModels: ['safe-model', 'blocked-model'],
        deniedModels: ['blocked-model'],
      },
    ],
  });
  const persistedBefore = global.window.localStorage.getItem(PREVIEW_LAYOUT_STORAGE_KEY);

  await assert.rejects(
    () => module.switchBrowserPreviewProviderModel('not-listed-model', 'session-model-not-allowed'),
    /not available for this connection/,
  );
  assert.equal(global.window.localStorage.getItem(PREVIEW_LAYOUT_STORAGE_KEY), persistedBefore);

  await assert.rejects(
    () => module.switchBrowserPreviewProviderModel('blocked-model', 'session-model-denied'),
    /blocked for this connection/,
  );
  assert.equal(global.window.localStorage.getItem(PREVIEW_LAYOUT_STORAGE_KEY), persistedBefore);
});

test('switchBrowserPreviewProviderModel restores saved per-model limits in preview state', async () => {
  const module = await seedPreviewProviderState(
    {
      configured: true,
      name: 'MiniMax',
      baseUrl: 'http://47.107.101.18:3000/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      contextWindowTokens: 64000,
      maxOutputTokens: 8000,
      modelTokenLimits: {
        'MiniMax-M3': {
          contextWindowTokens: 64000,
          maxOutputTokens: 8000,
        },
        'MiniMax-M2.7-highspeed': {
          contextWindowTokens: 128000,
          maxOutputTokens: 12000,
        },
      },
      profileId: 'minimax-core',
      profileLabel: 'MiniMax Core',
      profileMode: 'direct',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: true,
        structuredOutput: true,
        streaming: true,
      },
      availableModels: ['MiniMax-M3', 'MiniMax-M2.7-highspeed'],
      resolvedModel: 'MiniMax-M3',
      modelListStatus: 'ready',
      providerProfiles: [
        {
          id: 'minimax-core',
          label: 'MiniMax Core',
          name: 'MiniMax',
          protocol: 'openai_chat_completions_compatible',
          baseUrl: 'http://47.107.101.18:3000/v1',
          model: 'MiniMax-M3',
          availableModels: ['MiniMax-M3', 'MiniMax-M2.7-highspeed'],
          contextWindowTokens: 64000,
          maxOutputTokens: 8000,
          modelTokenLimits: {
            'MiniMax-M3': {
              contextWindowTokens: 64000,
              maxOutputTokens: 8000,
            },
            'MiniMax-M2.7-highspeed': {
              contextWindowTokens: 128000,
              maxOutputTokens: 12000,
            },
          },
          mode: 'direct',
          credentialMode: 'ui_proxy',
        },
      ],
    },
    'sk-test',
  );

  const result = await module.switchBrowserPreviewProviderModel(
    'MiniMax-M2.7-highspeed',
    'session-switch-model',
  );
  const providerPatch = result.messages[0].payload.providerConfig;

  assert.equal(providerPatch.model, 'MiniMax-M2.7-highspeed');
  assert.equal(providerPatch.contextWindowTokens, 128000);
  assert.equal(providerPatch.maxOutputTokens, 12000);
  assert.equal(
    providerPatch.modelTokenLimits['MiniMax-M2.7-highspeed'].contextWindowTokens,
    128000,
  );
  assert.equal(providerPatch.providerProfiles[0].model, 'MiniMax-M2.7-highspeed');
});

test('switchBrowserPreviewProviderProfile auto-refreshes models and restores resolved-model limits when a preview key exists', async () => {
  const originalFetch = global.fetch;
  const module = await seedPreviewProviderState(
    {
      configured: true,
      name: 'MiniMax',
      baseUrl: 'http://47.107.101.18:3000/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      contextWindowTokens: 64000,
      maxOutputTokens: 8000,
      modelTokenLimits: {
        'MiniMax-M3': {
          contextWindowTokens: 64000,
          maxOutputTokens: 8000,
        },
        'MiniMax-M2.7-highspeed': {
          contextWindowTokens: 128000,
          maxOutputTokens: 12000,
        },
      },
      profileId: 'minimax-fast',
      profileLabel: 'MiniMax Fast',
      profileMode: 'direct',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: true,
        structuredOutput: true,
        streaming: true,
      },
      availableModels: ['MiniMax-M3'],
      resolvedModel: 'MiniMax-M3',
      modelListStatus: 'ready',
      providerProfiles: [
        {
          id: 'minimax-core',
          label: 'MiniMax Core',
          name: 'MiniMax',
          protocol: 'openai_chat_completions_compatible',
          baseUrl: 'http://47.107.101.18:3000/v1',
          model: 'MiniMax-M3',
          availableModels: ['MiniMax-M3'],
          contextWindowTokens: 64000,
          maxOutputTokens: 8000,
          modelTokenLimits: {
            'MiniMax-M3': {
              contextWindowTokens: 64000,
              maxOutputTokens: 8000,
            },
            'MiniMax-M2.7-highspeed': {
              contextWindowTokens: 128000,
              maxOutputTokens: 12000,
            },
          },
          mode: 'direct',
          credentialMode: 'ui_proxy',
        },
        {
          id: 'minimax-fast',
          label: 'MiniMax Fast',
          name: 'MiniMax',
          protocol: 'openai_chat_completions_compatible',
          baseUrl: 'http://47.107.101.18:3000/v1',
          model: 'MiniMax-M3',
          availableModels: ['MiniMax-M3'],
          contextWindowTokens: 64000,
          maxOutputTokens: 8000,
          modelTokenLimits: {
            'MiniMax-M3': {
              contextWindowTokens: 64000,
              maxOutputTokens: 8000,
            },
            'MiniMax-M2.7-highspeed': {
              contextWindowTokens: 128000,
              maxOutputTokens: 12000,
            },
          },
          mode: 'direct',
          credentialMode: 'ui_proxy',
        },
      ],
    },
    'sk-fast',
  );

  let capturedBody;
  global.fetch = async (url, init) => {
    const href = String(url);
    if (href.endsWith('/provider/models')) {
      capturedBody = JSON.parse(init.body);
      return new Response(
        JSON.stringify({
          ok: true,
          detail: 'Fetched 2 models. Resolved configured model to MiniMax-M2.7-highspeed.',
          available_models: ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
          resolved_model: 'MiniMax-M2.7-highspeed',
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      );
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const result = await module.switchBrowserPreviewProviderProfile(
      'minimax-fast',
      'session-switch-profile',
    );
    const providerPatch = result.messages[0].payload.providerConfig;

    assert.equal(capturedBody.provider.model, 'MiniMax-M3');
    assert.equal(capturedBody.api_key, 'sk-fast');
    assert.equal(providerPatch.profileId, 'minimax-fast');
    assert.equal(providerPatch.model, 'MiniMax-M2.7-highspeed');
    assert.equal(providerPatch.contextWindowTokens, 128000);
    assert.equal(providerPatch.maxOutputTokens, 12000);
    assert.equal(
      providerPatch.modelTokenLimits['MiniMax-M2.7-highspeed'].contextWindowTokens,
      128000,
    );
    assert.equal(
      providerPatch.providerProfiles.find((profile) => profile.id === 'minimax-fast').model,
      'MiniMax-M2.7-highspeed',
    );

    assert.equal(global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY), null);
  } finally {
    global.fetch = originalFetch;
  }
});

test('testBrowserPreviewProvider stores the last live result in preview state', async () => {
  const originalFetch = global.fetch;
  const module = await seedPreviewProviderState(
    {
      configured: true,
      name: 'MiniMax',
      baseUrl: 'http://47.107.101.18:3000/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      profileId: 'minimax-core',
      profileLabel: 'MiniMax Core',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: true,
        structuredOutput: true,
        streaming: true,
      },
      availableModels: ['MiniMax-M3'],
      resolvedModel: 'MiniMax-M3',
      modelListStatus: 'ready',
    },
    'sk-live',
  );

  let capturedBody;
  global.fetch = async (url, init) => {
    const href = String(url);
    if (href.endsWith('/provider/test')) {
      capturedBody = JSON.parse(init.body);
      return new Response(
        JSON.stringify({
          ok: true,
          status: 'connected',
          detail: 'MiniMax is connected.',
          diagnostics: ['live connectivity check succeeded'],
          capability_evidence: [
            { name: 'tools', declared: true, observed: true, state: 'verified' },
            { name: 'streaming', declared: true, observed: true, state: 'verified' },
          ],
          tools_ready: true,
          tool_probe_status: 'verified',
          streaming_ready: true,
          stream_probe_status: 'verified',
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      );
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const result = await module.testBrowserPreviewProvider('session-test-provider');
    const providerPatch = result.messages[0].payload.providerConfig;

    assert.equal(capturedBody.provider.name, 'MiniMax');
    assert.equal(capturedBody.api_key, 'sk-live');
    assert.equal(providerPatch.lastTestResult.detail, 'Model connected');
    assert.equal(providerPatch.lastTestResult.status, 'connected');
    assert.equal(providerPatch.lastTestResult.protocol, 'openai_chat_completions_compatible');
    assert.equal(providerPatch.lastTestResult.toolsReady, true);
    assert.equal(providerPatch.lastTestResult.toolProbeStatus, 'verified');
    assert.equal(providerPatch.lastTestResult.streamingReady, true);
    assert.equal(providerPatch.lastTestResult.streamProbeStatus, 'verified');
    assert.deepEqual(providerPatch.lastTestResult.capabilityEvidence, [
      { name: 'tools', declared: true, observed: true, state: 'verified' },
      { name: 'streaming', declared: true, observed: true, state: 'verified' },
    ]);
    assert.equal(providerPatch.capabilities.tools, true);
    assert.equal(providerPatch.capabilities.streaming, true);
    assert.equal(global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY), null);
  } finally {
    global.fetch = originalFetch;
  }
});

test('testBrowserPreviewProvider patches transient draft test state after a live success', async () => {
  const originalFetch = global.fetch;
  const module = await seedPreviewProviderState(
    {
      configured: true,
      name: 'Saved provider',
      baseUrl: 'https://saved.example/v1',
      model: 'saved-model',
      protocol: 'openai_chat_completions_compatible',
      profileId: 'saved-provider',
      profileLabel: 'Saved provider',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: true,
        structuredOutput: true,
        streaming: true,
      },
      availableModels: ['saved-model'],
      resolvedModel: 'saved-model',
      modelListStatus: 'ready',
    },
    'sk-saved-key',
  );

  global.fetch = async (url, init) => {
    const href = String(url);
    if (!href.endsWith('/provider/test')) {
      throw new Error(`Unexpected fetch request: ${href}`);
    }
    const body = JSON.parse(init.body);
    assert.equal(body.provider.baseUrl, 'https://draft.example/v1');
    assert.equal(body.provider.model, 'draft-model');
    return new Response(
      JSON.stringify({
        ok: true,
        status: 'connected',
        capability_evidence: [
          { name: 'tools', declared: true, observed: true, state: 'verified' },
        ],
        tools_ready: true,
        tool_probe_status: 'verified',
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const result = await module.testBrowserPreviewProvider(
      {
        name: 'Draft provider',
        baseUrl: 'https://draft.example/v1',
        model: 'draft-model',
        protocol: 'openai_chat_completions_compatible',
        apiKey: 'sk-draft-key',
      },
      'session-draft-test',
    );

    assert.equal(result.messages.length, 2);
    assert.equal(result.messages[0].type, 'state/patch');
    assert.equal(result.messages[1].type, 'operation/status');
    assert.equal(result.messages[1].payload.tone, 'success');
    const providerPatch = result.messages[0].payload.providerConfig;
    assert.equal(providerPatch.lastTestResult.ok, true);
    assert.equal(providerPatch.lastTestResult.providerName, 'Draft provider');
    assert.equal(providerPatch.lastTestResult.baseUrl, 'https://draft.example/v1');
    assert.equal(providerPatch.lastTestResult.model, 'draft-model');
    assert.equal(providerPatch.capabilities.tools, true);
    assert.match(result.messages[1].payload.message, /connected/i);
  } finally {
    global.fetch = originalFetch;
  }
});

test('refreshBrowserPreviewProviderModels updates preview model cache and available models', async () => {
  const originalFetch = global.fetch;
  const module = await seedPreviewProviderState(
    {
      configured: true,
      name: 'MiniMax',
      baseUrl: 'http://47.107.101.18:3000/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      profileId: 'minimax-core',
      profileLabel: 'MiniMax Core',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: true,
        structuredOutput: true,
        streaming: true,
      },
      availableModels: ['MiniMax-M3'],
      resolvedModel: 'MiniMax-M3',
      modelListStatus: 'idle',
    },
    'sk-live',
  );

  let capturedBody;
  global.fetch = async (url, init) => {
    const href = String(url);
    if (href.endsWith('/provider/models')) {
      capturedBody = JSON.parse(init.body);
      return new Response(
        JSON.stringify({
          ok: true,
          detail: 'Fetched 2 models.',
          available_models: ['MiniMax-M3', 'MiniMax-M2.7-highspeed'],
          resolved_model: 'MiniMax-M3',
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json' },
        },
      );
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    const result = await module.refreshBrowserPreviewProviderModels('session-refresh-models');
    const providerPatch = result.messages[0].payload.providerConfig;

    assert.equal(capturedBody.provider.name, 'MiniMax');
    assert.equal(capturedBody.api_key, 'sk-live');
    assert.equal(providerPatch.modelListStatus, 'ready');
    assert.deepEqual(providerPatch.availableModels, [
      'MiniMax-M3',
      'MiniMax-M2.7-highspeed',
    ]);

    assert.equal(global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY), null);
  } finally {
    global.fetch = originalFetch;
  }
});

test('fixture Preview keeps provider testing and model refresh local', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousBootstrap = global.window.__TRAINER_BOOTSTRAP__;
  const module = await seedPreviewProviderState(
    {
      configured: true,
      name: 'Preview provider',
      baseUrl: 'http://localhost:1234/v1',
      model: 'preview-model',
      protocol: 'openai_chat_completions_compatible',
      profileId: 'preview-provider',
      profileLabel: 'Preview provider',
      apiKeyConfigured: true,
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: true,
        structuredOutput: true,
        streaming: true,
      },
      availableModels: ['preview-model'],
      resolvedModel: 'preview-model',
      modelListStatus: 'ready',
    },
    undefined,
  );
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  global.window.__TRAINER_BOOTSTRAP__ = {};
  let fetchCalls = 0;
  global.fetch = async () => {
    fetchCalls += 1;
    throw new Error('Fixture Preview must not contact a sidecar for provider controls.');
  };

  try {
    const testResult = await module.testBrowserPreviewProvider('fixture-provider-test');
    const refreshResult = await module.refreshBrowserPreviewProviderModels('fixture-provider-models');

    assert.equal(fetchCalls, 0);
    assert.equal(testResult.messages.length, 1);
    assert.equal(testResult.messages[0].type, 'operation/status');
    assert.equal(testResult.messages[0].payload.tone, 'info');
    assert.match(testResult.messages[0].payload.message, /cannot verify a real connection/i);
    assert.match(testResult.messages[0].payload.message, /VS Code/i);
    assert.equal(testResult.messages.some((message) => message.type === 'state/patch'), false);
    assert.equal(global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY), null);
    assert.equal(refreshResult.messages[0].payload.providerConfig.modelListStatus, 'ready');
    assert.equal(refreshResult.messages[0].payload.providerConfig.apiKeyConfigured, true);
    assert.equal(refreshResult.messages[0].payload.providerConfig.cacheSource, 'cache');
    assert.match(refreshResult.messages[1].payload.message, /local model list/i);
  } finally {
    global.fetch = originalFetch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    if (previousBootstrap === undefined) {
      delete global.window.__TRAINER_BOOTSTRAP__;
    } else {
      global.window.__TRAINER_BOOTSTRAP__ = previousBootstrap;
    }
  }
});

test('fixture Preview discovers models for an incomplete draft without saving or replacing it', async () => {
  const originalFetch = global.fetch;
  const previousPreviewFlag = global.window.__TRAINER_BROWSER_PREVIEW__;
  const previousBootstrap = global.window.__TRAINER_BOOTSTRAP__;
  const module = await seedPreviewProviderState(
    {
      configured: false,
      name: '',
      baseUrl: '',
      model: '',
      protocol: 'openai_chat_completions_compatible',
      capabilities: {
        chat: true,
        responses: false,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: false,
        structuredOutput: false,
        streaming: true,
      },
      availableModels: [],
      modelListStatus: 'idle',
    },
    undefined,
  );
  global.window.__TRAINER_BROWSER_PREVIEW__ = true;
  global.window.__TRAINER_BOOTSTRAP__ = {};
  let fetchCalls = 0;
  global.fetch = async () => {
    fetchCalls += 1;
    throw new Error('Fixture Preview must not contact a sidecar for draft model discovery.');
  };

  try {
    const result = await module.refreshBrowserPreviewProviderModels(
      {
        baseUrl: 'http://localhost:1234/v1',
        apiKey: 'sk-preview-draft',
        protocol: 'openai_chat_completions_compatible',
        model: '',
      },
      'fixture-draft-models',
    );
    const providerPatch = result.messages[0].payload.providerConfig;

    assert.equal(fetchCalls, 0);
    assert.equal(providerPatch.configured, false);
    assert.equal(providerPatch.baseUrl, '');
    assert.equal(providerPatch.model, '');
    assert.equal(providerPatch.apiKeyConfigured, false);
    assert.equal(providerPatch.modelListStatus, 'ready');
    assert.deepEqual(providerPatch.availableModels, [
      'preview-chat',
      'preview-reasoning',
      'preview-vision',
    ]);
    assert.equal(JSON.stringify(providerPatch).includes('sk-preview-draft'), false);
    assert.equal(global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY), null);

    const draftTest = await module.testBrowserPreviewProvider(
      {
        baseUrl: 'http://localhost:1234/v1',
        apiKey: 'sk-preview-draft',
        protocol: 'openai_chat_completions_compatible',
        model: 'preview-chat',
      },
      'fixture-draft-test',
    );

    assert.equal(draftTest.messages.length, 1);
    assert.equal(draftTest.messages[0].type, 'operation/status');
    assert.equal(draftTest.messages[0].payload.tone, 'info');
    assert.match(draftTest.messages[0].payload.message, /cannot verify this draft connection/i);
    assert.equal(draftTest.messages.some((message) => message.type === 'state/patch'), false);
    assert.equal(global.window.localStorage.getItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY), null);
  } finally {
    global.fetch = originalFetch;
    if (previousPreviewFlag === undefined) {
      delete global.window.__TRAINER_BROWSER_PREVIEW__;
    } else {
      global.window.__TRAINER_BROWSER_PREVIEW__ = previousPreviewFlag;
    }
    if (previousBootstrap === undefined) {
      delete global.window.__TRAINER_BOOTSTRAP__;
    } else {
      global.window.__TRAINER_BOOTSTRAP__ = previousBootstrap;
    }
  }
});

test('browser preview only reuses a saved key for the same draft transport', async () => {
  const originalFetch = global.fetch;
  const module = await seedPreviewProviderState(
    {
      configured: true,
      name: 'Saved provider',
      baseUrl: 'https://saved.example/v1',
      model: 'saved-model',
      protocol: 'openai_chat_completions_compatible',
      profileId: 'saved-provider',
      profileLabel: 'Saved provider',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: true,
        structuredOutput: true,
        streaming: true,
      },
      availableModels: ['saved-model'],
      resolvedModel: 'saved-model',
      modelListStatus: 'ready',
    },
    'sk-saved-key',
  );
  const requests = [];
  global.fetch = async (url, init) => {
    const href = String(url);
    requests.push({ href, body: JSON.parse(init.body) });
    if (href.endsWith('/provider/models')) {
      return new Response(
        JSON.stringify({
          ok: true,
          available_models: ['saved-model', 'saved-model-next'],
          resolved_model: 'saved-model',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    if (href.endsWith('/provider/test')) {
      return new Response(
        JSON.stringify({ ok: true, status: 'connected' }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }
    throw new Error(`Unexpected fetch request: ${href}`);
  };

  try {
    await module.refreshBrowserPreviewProviderModels(
      {
        name: 'Saved provider',
        baseUrl: 'https://saved.example/v1',
        model: '',
        protocol: 'openai_chat_completions_compatible',
      },
      'preview-same-transport-models',
    );
    await module.testBrowserPreviewProvider(
      {
        name: 'Saved provider',
        baseUrl: 'https://saved.example/v1',
        model: 'saved-model',
        protocol: 'openai_chat_completions_compatible',
      },
      'preview-same-transport-test',
    );

    assert.equal(requests.length, 2);
    assert.deepEqual(
      requests.map((request) => request.body.api_key),
      ['sk-saved-key', 'sk-saved-key'],
    );

    const changedAddressModels = {
      name: 'New provider',
      baseUrl: 'https://other.example/v1',
      model: '',
      protocol: 'openai_chat_completions_compatible',
    };
    const changedProtocolTest = {
      name: 'Saved provider',
      baseUrl: 'https://saved.example/v1',
      model: 'saved-model',
      protocol: 'anthropic_messages',
    };
    await assert.rejects(
      () => module.refreshBrowserPreviewProviderModels(changedAddressModels, 'preview-new-address-models'),
      (error) => {
        assert.match(error.message, /api key/i);
        assert.doesNotMatch(error.message, /sk-saved-key/i);
        return true;
      },
    );
    await assert.rejects(
      () => module.testBrowserPreviewProvider(changedProtocolTest, 'preview-new-protocol-test'),
      (error) => {
        assert.match(error.message, /api key/i);
        assert.doesNotMatch(error.message, /sk-saved-key/i);
        return true;
      },
    );
    assert.equal(requests.length, 2);

    await module.refreshBrowserPreviewProviderModels(
      { ...changedAddressModels, apiKey: 'sk-new-key' },
      'preview-new-address-explicit-key',
    );
    assert.equal(requests.length, 3);
    assert.equal(requests.at(-1).body.api_key, 'sk-new-key');
    assert.notEqual(requests.at(-1).body.api_key, 'sk-saved-key');
  } finally {
    global.fetch = originalFetch;
  }
});
