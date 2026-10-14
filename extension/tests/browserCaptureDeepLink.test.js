'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const deepLinkModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'browserCapture',
  'deepLink.js',
);

function loadDeepLink(vscodeMock = { window: {}, workspace: {}, commands: {} }) {
  return loadWithVscodeMock(deepLinkModulePath, vscodeMock);
}

function createDeps() {
  const events = [];
  const lines = [];
  const workbench = {
    async show() {
      events.push('show');
    },
    async postMessage(message) {
      events.push('postMessage');
      events.push(message);
    },
  };
  return {
    events,
    lines,
    deps: {
      workbench,
      outputChannel: {
        appendLine(line) {
          lines.push(line);
        },
      },
    },
  };
}

test('library deep links parse the resource id and reject everything else', () => {
  const { parseTrainerDeepLink } = loadDeepLink();

  assert.deepEqual(parseTrainerDeepLink({ path: '/library/res-123' }), {
    kind: 'library',
    resourceId: 'res-123',
  });
  assert.deepEqual(parseTrainerDeepLink({ path: '/library/res-123/' }), {
    kind: 'library',
    resourceId: 'res-123',
  });
  assert.deepEqual(parseTrainerDeepLink({ path: '/library/res%2E1' }), {
    kind: 'library',
    resourceId: 'res.1',
  });
  // Query form fallback for clients that cannot mint a path segment.
  assert.deepEqual(parseTrainerDeepLink({ path: '/', query: 'resourceId=res-9' }), {
    kind: 'library',
    resourceId: 'res-9',
  });

  for (const uri of [
    { path: '/library/' },
    { path: '/library' },
    { path: '/library/a/b' },
    { path: '/training/card-1' },
    { path: '' },
    { path: '/library/%2F' },
    { path: '/library/bad id' },
  ]) {
    assert.equal(parseTrainerDeepLink(uri), undefined, JSON.stringify(uri));
  }
});

test('handling a library deep link focuses the workbench and posts ui/openResource', async () => {
  const { handleTrainerDeepLink, OPEN_RESOURCE_MESSAGE } = loadDeepLink();
  const { deps, events } = createDeps();
  const uri = {
    path: '/library/resource-42',
    toString: () => 'vscode://local.trainer-extension/library/resource-42',
  };

  const result = await handleTrainerDeepLink(deps, uri);

  assert.deepEqual(result, { handled: true, resourceId: 'resource-42', deliveryAttempts: 1 });
  assert.equal(OPEN_RESOURCE_MESSAGE, 'ui/openResource');
  // show() must land first so the message cannot reach an unmounted view.
  assert.deepEqual(events, [
    'show',
    'postMessage',
    { type: 'ui/openResource', resourceId: 'resource-42' },
  ]);
});

test('the registered URI handler ignores unrecognized deep links without touching the workbench', async () => {
  const { createTrainerUriHandler } = loadDeepLink();
  const { deps, events, lines } = createDeps();
  const handler = createTrainerUriHandler(deps);

  await handler.handleUri({
    path: '/plan/stage-1',
    toString: () => 'vscode://local.trainer-extension/plan/stage-1',
  });

  assert.deepEqual(events, []);
  assert.equal(lines.length, 1);
  assert.match(lines[0], /ignored unrecognized deep link/);
});

test('delivery retries while the workbench has not become visible yet', async () => {
  const { handleTrainerDeepLink } = loadDeepLink();
  const { deps, events } = createDeps();
  let visible = false;
  const waits = [];
  deps.workbench.isVisible = () => visible;
  deps.delayFn = async (milliseconds) => {
    waits.push(milliseconds);
    if (waits.length === 2) {
      // The webview resolves while the deep link is waiting.
      visible = true;
    }
  };

  const result = await handleTrainerDeepLink(deps, {
    path: '/library/resource-7',
    toString: () => 'vscode://local.trainer-extension/library/resource-7',
  });

  assert.equal(result.handled, true);
  assert.equal(result.deliveryAttempts, 3);
  assert.deepEqual(waits, [300, 300]);
  assert.equal(events[0], 'show');
  assert.equal(
    events.filter((event) => event?.type === 'ui/openResource').length,
    3,
  );
});

test('delivery stops after the bounded attempt budget and says so in the log', async () => {
  const { handleTrainerDeepLink } = loadDeepLink();
  const { deps, events, lines } = createDeps();
  deps.workbench.isVisible = () => false;
  deps.delayFn = async () => undefined;

  const result = await handleTrainerDeepLink(deps, {
    path: '/library/resource-8',
    toString: () => 'vscode://local.trainer-extension/library/resource-8',
  });

  assert.equal(result.deliveryAttempts, 6);
  assert.equal(
    events.filter((event) => event?.type === 'ui/openResource').length,
    6,
  );
  assert.ok(lines.some((line) => /could not confirm a visible workbench/.test(line)));
});
