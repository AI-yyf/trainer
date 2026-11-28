'use strict';

// Behavioral contract for the Browser Side Panel transport
// (`extension/webview/src/lib/chromeSidePanelTransport.ts`): a request this
// surface cannot carry out answers with an explicit failure.
//
// The webview reads silence as "still pending" and a `training/persistenceAck`
// with `ok: true` as "the server saved it", so a dropped request or a
// defaulted acknowledgement reports progress that no server state backs
// (product-contract §6 "evidence must be real", §9 "no fake completion").
//
// The TypeScript sources are bundled in memory: no dist build is required and
// nothing is written to disk.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const esbuild = require(
  fs.existsSync(path.resolve(__dirname, '../webview/node_modules/esbuild'))
    ? path.resolve(__dirname, '../webview/node_modules/esbuild')
    : 'esbuild',
);

const repoRoot = path.resolve(__dirname, '../..');
const webviewRoot = path.join(repoRoot, 'extension', 'webview');

async function loadWebviewModule(entryRelativePath) {
  const entryPath = path.join(webviewRoot, entryRelativePath);
  const bundled = await esbuild.build({
    entryPoints: [entryPath],
    bundle: true,
    platform: 'node',
    format: 'cjs',
    write: false,
    logLevel: 'silent',
    tsconfig: path.join(webviewRoot, 'tsconfig.json'),
  });
  const mod = { exports: {} };
  const fn = new Function('require', 'module', 'exports', '__filename', '__dirname', bundled.outputFiles[0].text);
  fn(require, mod, mod.exports, entryPath, path.dirname(entryPath));
  return mod.exports;
}

const moduleCache = new Map();
function loadOnce(entryRelativePath) {
  if (!moduleCache.has(entryRelativePath)) {
    moduleCache.set(entryRelativePath, loadWebviewModule(entryRelativePath));
  }
  return moduleCache.get(entryRelativePath);
}

const WAIT_MS = 2000;

// Mirrors RESOURCE_OPERATION_STATUS_PATTERN in
// extension/webview/src/app/appHelpers.tsx: the marker the webview needs to
// settle a pending search.
const RESOURCE_SEARCH_STATUS_PATTERN =
  /^\[\[trainer-resource-operation:search:([a-z0-9-]{1,96})\]\]\s*/i;

// The only training commands with a real browser lane
// (`/browser/chat/training/...` on the sidecar).
const TRAINING_LANES = new Map([
  ['trainer.training.attempt.start', '/training/attempt/start'],
  ['trainer.training.flashcardAnswer', '/training/flashcard/answer'],
  ['trainer.training.practiceReturn', '/training/practice-return'],
  ['trainer.training.return', '/training/practice-return'],
]);

// Commands `handleCommandExecute` implements itself; everything else in the
// catalog must come back as an explicit failure.
const SUPPORTED_COMMAND_IDS = new Set([
  'trainer.session.listSessions',
  'trainer.session.list',
  'trainer.session.new',
  'trainer.session.activateSession',
  'trainer.session.select',
  'trainer.resource.search',
  'trainer.resource.capture',
  'trainer.browserCapture.captureActiveTab',
  'trainer.browserCapture.status',
  'trainer.config.openWorkspace',
]);
const SUPPORTED_COMMAND_PREFIXES = [
  'trainer.training.',
  'trainer.evidence.',
  'trainer.provider.',
  'trainer.workspace.',
];

const AUTH = {
  'trainerCapture.baseUrl': 'http://127.0.0.1:8765',
  'trainerCapture.credential': 'paired-credential',
  'trainerCapture.workspaceId': 'ws-sidepanel',
  'trainerCapture.workspaceName': 'Side Panel Workspace',
};

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

/**
 * A real transport on a fake platform. `events` is one ordered log of every
 * sidecar fetch and every host message, so a test can prove which came first.
 */
async function createHarness({ paired = true, respond = () => jsonResponse(200, {}) } = {}) {
  const { createChromeSidePanelTransport } = await loadOnce('src/lib/chromeSidePanelTransport.ts');
  const stored = paired ? { ...AUTH } : {};
  const events = [];
  const transport = createChromeSidePanelTransport({
    platform: {
      storageGet: async (defaults) => ({ ...defaults, ...stored }),
      storageSet: async (items) => {
        Object.assign(stored, items);
      },
      sendRuntimeMessage: async () => ({}),
      queryActiveTab: async () => undefined,
      fetchFn: async (url) => {
        events.push({ kind: 'fetch', url: String(url) });
        return respond(String(url));
      },
    },
  });
  transport.subscribe((message) => events.push({ kind: 'message', message }));
  return { transport, events };
}

/** Resolves with the first host message matching `predicate`. */
function nextMessage(transport, predicate, description) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      unsubscribe();
      reject(new Error(`No ${description} arrived within ${WAIT_MS}ms.`));
    }, WAIT_MS);
    const unsubscribe = transport.subscribe((message) => {
      if (!predicate(message)) {
        return;
      }
      clearTimeout(timer);
      unsubscribe();
      resolve(message);
    });
  });
}

/** Pairs with the bootstrap the side panel requests before anything else. */
async function connect(harness) {
  const bootstrap = nextMessage(harness.transport, (message) => message.type === 'bootstrap', 'bootstrap');
  harness.transport.postMessage({ type: 'request/bootstrap' });
  await bootstrap;
}

/** Posts `action` and resolves with the first host message it produces. */
async function replyTo(harness, action, description) {
  const reply = nextMessage(harness.transport, () => true, `reply to ${description}`);
  harness.transport.postMessage(action);
  return reply;
}

function executeCommand(transport, commandId, payload) {
  transport.postMessage({ type: 'command/execute', payload: { commandId, payload } });
}

/** Lets the already-scheduled microtasks of one dispatch finish. */
const settle = async () => {
  for (let round = 0; round < 4; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};

/** A bounded window in which an unexpected reply would have arrived. */
const quiet = () => new Promise((resolve) => setTimeout(resolve, 20));

const trainingLaneFetchesBefore = (harness, message) => {
  const replyAt = harness.events.findIndex((event) => event.message === message);
  assert.ok(replyAt >= 0, 'the reply must be in the event log');
  return harness.events
    .slice(0, replyAt)
    .filter((event) => event.kind === 'fetch' && event.url.includes('/browser/chat/training/'));
};

const trainingFamilyCommandIds = (trainerCommands) =>
  Object.values(trainerCommands).filter(
    (id) => id.startsWith('trainer.training.') || id.startsWith('trainer.evidence.'),
  );

test('a training/evidence command with no browser lane is acknowledged ok:false and never reaches the server', async () => {
  const { trainerCommands } = await loadOnce('../../shared/src/commands.ts');
  const family = trainingFamilyCommandIds(trainerCommands);
  assert.ok(family.length >= 20, 'the training/evidence family is expected to be large');
  for (const lane of TRAINING_LANES.keys()) {
    assert.ok(family.includes(lane), `${lane} should belong to the training family`);
  }

  const messages = new Set();
  let unsupported = 0;
  for (const commandId of family) {
    if (TRAINING_LANES.has(commandId)) {
      continue;
    }
    unsupported += 1;
    const harness = await createHarness();
    await connect(harness);

    const requestId = `training-persistence-${unsupported}`;
    const ack = await replyTo(
      harness,
      { type: 'command/execute', payload: { commandId, payload: { cardId: 'card-1', __trainerTrainingPersistenceId: requestId } } },
      `an acknowledgement for ${commandId}`,
    );
    await settle();

    assert.equal(ack.type, 'training/persistenceAck', `${commandId} must answer on the persistence channel`);
    assert.equal(ack.payload.ok, false, `${commandId} has no browser lane and must not be acknowledged as saved`);
    assert.equal(ack.payload.commandId, commandId);
    assert.equal(ack.payload.requestId, requestId, 'the webview correlates the acknowledgement by this id');
    assert.equal(typeof ack.payload.message, 'string');
    assert.ok(ack.payload.message.trim().length > 0, `${commandId} must state why it failed`);
    assert.notEqual(ack.payload.message, 'Not connected', 'an unimplemented command is a different failure from being offline');
    messages.add(ack.payload.message);
    assert.equal(trainingLaneFetchesBefore(harness, ack).length, 0, `${commandId} must not be sent to the sidecar`);
    assert.equal(
      harness.events.filter((event) => event.kind === 'fetch').length,
      1,
      `${commandId} must cause no sidecar call beyond the initial bootstrap`,
    );
  }

  assert.ok(unsupported >= 10, 'most training/evidence commands have no browser lane');
  assert.equal(messages.size, 1, 'the failure message is stable across commands');
});

test('a durable training command is answered on the persistence channel whatever its prefix', async () => {
  const { trainerCommands } = await loadOnce('../../shared/src/commands.ts');
  // Sent by the webview through requestTrainingPersistence, so the caller is
  // holding a promise that only a training/persistenceAck settles.
  const durableCommands = [
    trainerCommands.trainingCardStatusTransition,
    trainerCommands.trainingCardLibrary,
    trainerCommands.evaluateCurrentFile,
  ];
  for (const commandId of durableCommands) {
    assert.ok(!TRAINING_LANES.has(commandId));
    const harness = await createHarness();
    await connect(harness);

    const ack = await replyTo(
      harness,
      { type: 'command/execute', payload: { commandId, payload: { cardId: 'card-1', __trainerTrainingPersistenceId: 'persist-1' } } },
      `an acknowledgement for ${commandId}`,
    );
    await settle();

    assert.equal(ack.type, 'training/persistenceAck', `${commandId} must not be left waiting`);
    assert.equal(ack.payload.ok, false);
    assert.equal(ack.payload.requestId, 'persist-1');
    assert.equal(trainingLaneFetchesBefore(harness, ack).length, 0);
  }
});

test('ok:true is emitted for a training/evidence command only after the sidecar accepted a real lane call', async () => {
  const { trainerCommands } = await loadOnce('../../shared/src/commands.ts');
  const family = trainingFamilyCommandIds(trainerCommands);
  const scenarios = [
    { name: 'sidecar accepts', paired: true, respond: () => jsonResponse(200, { saved: true }) },
    {
      name: 'sidecar rejects',
      paired: true,
      respond: (url) => (url.includes('/browser/chat/training/') ? jsonResponse(500, { detail: 'rejected' }) : jsonResponse(200, {})),
    },
    {
      name: 'request fails',
      paired: true,
      respond: (url) => {
        if (url.includes('/browser/chat/training/')) {
          throw new Error('socket hang up');
        }
        return jsonResponse(200, {});
      },
    },
    { name: 'not paired', paired: false, respond: () => jsonResponse(200, {}) },
  ];

  let acknowledgedSaved = 0;
  for (const scenario of scenarios) {
    for (const commandId of family) {
      const harness = await createHarness(scenario);
      await connect(harness);
      const before = harness.events.length;

      const ack = await replyTo(
        harness,
        { type: 'command/execute', payload: { commandId, payload: { cardId: 'card-1', __trainerTrainingPersistenceId: 'persist-1' } } },
        `an acknowledgement for ${commandId} (${scenario.name})`,
      );
      await settle();
      const fetches = harness.events.slice(before).filter((event) => event.kind === 'fetch');

      assert.equal(ack.type, 'training/persistenceAck');
      assert.equal(typeof ack.payload.ok, 'boolean', `${commandId}: ok must be an explicit boolean`);
      if (ack.payload.ok !== true) {
        assert.equal(ack.payload.ok, false, `${commandId} (${scenario.name}): a failure must be ok === false`);
        if (!TRAINING_LANES.has(commandId)) {
          assert.deepEqual(fetches, [], `${commandId} has no lane to call`);
        }
        continue;
      }

      acknowledgedSaved += 1;
      assert.equal(scenario.name, 'sidecar accepts', `${commandId}: ok:true requires an accepting sidecar`);
      assert.ok(TRAINING_LANES.has(commandId), `${commandId}: ok:true requires a browser lane`);
      assert.equal(ack.payload.data.saved, true, 'the acknowledgement carries the sidecar answer');
      const laneCalls = trainingLaneFetchesBefore(harness, ack);
      assert.equal(laneCalls.length, 1, `${commandId}: ok:true must follow exactly one lane call`);
      assert.ok(
        laneCalls[0].url.endsWith(`/browser/chat${TRAINING_LANES.get(commandId)}`),
        `${commandId}: the lane call must target its sidecar route`,
      );
    }
  }
  assert.equal(acknowledgedSaved, TRAINING_LANES.size, 'exactly the lane-backed commands can be acknowledged as saved');
});

test('every catalog command gets a reply, and an unsupported one is an explicit error status', async () => {
  const { trainerCommands } = await loadOnce('../../shared/src/commands.ts');
  const catalog = Object.values(trainerCommands);
  const isSupported = (commandId) =>
    SUPPORTED_COMMAND_IDS.has(commandId) ||
    SUPPORTED_COMMAND_PREFIXES.some((prefix) => commandId.startsWith(prefix));

  let unsupported = 0;
  for (const commandId of catalog) {
    const harness = await createHarness();
    await connect(harness);
    const reply = await replyTo(
      harness,
      { type: 'command/execute', payload: { commandId, payload: {} } },
      commandId,
    );
    if (isSupported(commandId)) {
      continue;
    }
    unsupported += 1;
    assert.equal(reply.type, 'operation/status', `${commandId} must answer with a status the UI handles`);
    assert.equal(reply.payload.tone, 'error', `${commandId} is not implemented here and must not look like it ran`);
    assert.ok(reply.payload.message.includes(commandId), `${commandId}: the status names the command`);
  }

  assert.ok(
    unsupported * 2 > catalog.length,
    `most of the catalog is unsupported in the side panel (${unsupported} of ${catalog.length}); ` +
      'the check above only means something if it exercised them',
  );
});

test('a command/execute without a usable command id is answered, not lost to a crash', async () => {
  const harness = await createHarness();
  const malformed = [
    { type: 'command/execute' },
    { type: 'command/execute', payload: {} },
    { type: 'command/execute', payload: { commandId: '' } },
    { type: 'command/execute', payload: { commandId: 42 } },
  ];
  for (const action of malformed) {
    const reply = await replyTo(harness, action, JSON.stringify(action));
    assert.equal(reply.type, 'operation/status');
    assert.equal(reply.payload.tone, 'error');
  }
});

test('an action with no side panel handler fails out loud while receipts and diagnostics stay unanswered', async () => {
  const harness = await createHarness();
  const requests = [
    'settings/saveCoach',
    'plan/generate',
    'plan/freeze',
    'task/specify',
    'task/next',
    'task/evaluateCurrentFile',
    'research/create',
    'research/addTheme',
    'research/activateTheme',
    'research/advance',
    'research/message',
    'research/streamMessage',
    'research/approve',
    'research/getStatus',
    'future/unknownAction',
  ];
  for (const type of requests) {
    const reply = await replyTo(harness, { type, payload: {} }, type);
    assert.equal(reply.type, 'operation/status', `${type} must answer with a status the UI handles`);
    assert.equal(reply.payload.tone, 'error', `${type} has no side panel handler`);
    assert.ok(reply.payload.message.includes(type), `${type}: the status names the action`);
  }

  // Posted without waiting for anything: a reply here would be noise, and for
  // state/ack (sent after every synced snapshot) an error after each sync.
  const unanswered = [
    { type: 'state/ack', payload: { revision: 1 } },
    { type: 'ui/coachDraftPrefillApplied', payload: { draftId: 'draft-1' } },
    { type: 'provider/cancelTest', payload: { requestId: 'test-1' } },
    { type: 'debug/error', payload: { source: 'test', message: 'boom' } },
    { type: 'debug/visibleFacts', payload: { activeView: 'coach' } },
    { type: 'ui/liveFollow', payload: { enabled: true } },
    { type: 'ui/focus', payload: { target: 'conversation' } },
    { type: 'ui/collapseToSidebar' },
    { type: 'settings/primeProviderModels' },
  ];
  for (const action of unanswered) {
    const before = harness.events.length;
    harness.transport.postMessage(action);
    await quiet();
    const replies = harness.events.slice(before).filter((event) => event.kind === 'message');
    assert.deepEqual(replies, [], `${action.type} is a receipt and expects no answer`);
  }
});

test('a resource search that does not run settles as a failed search for its own operation id', async () => {
  const { trainerCommands } = await loadOnce('../../shared/src/commands.ts');
  const cases = [
    {
      name: 'not paired',
      paired: false,
      payload: { query: 'idempotency', requestId: 'resource-search-offline' },
    },
    {
      name: 'empty query',
      paired: true,
      payload: { query: '   ', requestId: 'resource-search-empty' },
    },
    {
      name: 'request fails',
      paired: true,
      respond: (url) => {
        if (url.endsWith('/browser/chat/resource/search')) {
          throw new Error('socket hang up');
        }
        return jsonResponse(200, {});
      },
      payload: { query: 'idempotency', requestId: 'resource-search-network' },
    },
    {
      name: 'sidecar rejects',
      paired: true,
      respond: (url) => (url.endsWith('/browser/chat/resource/search') ? jsonResponse(503, { detail: 'unavailable' }) : jsonResponse(200, {})),
      payload: { query: 'idempotency', requestId: 'resource-search-rejected' },
    },
  ];

  for (const scenario of cases) {
    const harness = await createHarness({ paired: scenario.paired, respond: scenario.respond });
    await connect(harness);
    const before = harness.events.length;

    const reply = await replyTo(
      harness,
      { type: 'command/execute', payload: { commandId: trainerCommands.searchResources, payload: scenario.payload } },
      `a search status (${scenario.name})`,
    );
    await settle();

    assert.equal(reply.type, 'operation/status', `${scenario.name}: the search must be answered`);
    assert.equal(reply.payload.tone, 'error', `${scenario.name}: a search that did not run is a failed search`);
    const marker = RESOURCE_SEARCH_STATUS_PATTERN.exec(reply.payload.message);
    assert.ok(marker, `${scenario.name}: the status must carry the search marker the webview settles on`);
    assert.equal(marker[1].toLowerCase(), scenario.payload.requestId);
    assert.ok(reply.payload.message.slice(marker[0].length).trim().length > 0, `${scenario.name}: a reason is given`);
    assert.deepEqual(
      harness.events.slice(before).filter((event) => event.message && event.message.type === 'state/patch'),
      [],
      `${scenario.name}: a failed search must not publish results`,
    );
  }
});

test('a successful resource search still publishes its results and a success status', async () => {
  const { trainerCommands } = await loadOnce('../../shared/src/commands.ts');
  const hit = { id: 'res-1', title: 'Idempotent retries' };
  const harness = await createHarness({
    respond: (url) => (url.endsWith('/browser/chat/resource/search') ? jsonResponse(200, { hits: [hit], total: 1 }) : jsonResponse(200, {})),
  });
  await connect(harness);

  // The results are published before the status that settles the search.
  const status = nextMessage(harness.transport, (message) => message.type === 'operation/status', 'a search status');
  executeCommand(harness.transport, trainerCommands.searchResources, { query: 'idempotency', requestId: 'resource-search-ok' });
  const settled = await status;

  assert.equal(settled.payload.tone, 'success');
  assert.equal(RESOURCE_SEARCH_STATUS_PATTERN.exec(settled.payload.message)[1], 'resource-search-ok');
  const patch = harness.events.find((event) => event.message && event.message.type === 'state/patch');
  assert.ok(patch, 'the results are published as a state patch');
  assert.deepEqual(patch.message.payload.resourceSearch.hits, [hit]);
});
