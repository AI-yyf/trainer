// Restored behavioral regression test. Original file: extension/tests/hostMessageSchema.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Host message schema: well-formed messages delivered with parsed payload, unknown fields stripped, resource version bounds.
//
// Restoration: whole - all 4 original test definitions, code and assertions unchanged.
// Target: webview TypeScript transpiled in memory with typescript.transpileModule.

'use strict';

/**
 * The webview trusts the extension host, but it still validates what arrives:
 * `subscribeToHostMessages` (webview/src/lib/vscode.ts) parses every message
 * with a schema and drops what does not fit. These tests drive that function
 * with real messages, so the schema is checked by what it does — not by the
 * text of its source.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');

const webviewNodeModules = path.resolve(__dirname, '..', 'webview', 'node_modules');
if (!process.env.NODE_PATH?.split(path.delimiter).includes(webviewNodeModules)) {
  process.env.NODE_PATH = process.env.NODE_PATH
    ? `${webviewNodeModules}${path.delimiter}${process.env.NODE_PATH}`
    : webviewNodeModules;
  Module._initPaths();
}

const typescript = require(path.join(webviewNodeModules, 'typescript'));
for (const extension of ['.ts', '.tsx']) {
  if (!require.extensions[extension]) {
    require.extensions[extension] = (module, filename) => {
      const { outputText } = typescript.transpileModule(fs.readFileSync(filename, 'utf8'), {
        compilerOptions: {
          module: typescript.ModuleKind.CommonJS,
          target: typescript.ScriptTarget.ES2020,
          jsx: typescript.JsxEmit.ReactJSX,
          esModuleInterop: true,
        },
        fileName: filename,
      });
      module._compile(outputText, filename);
    };
  }
}

const vscodeModulePath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'vscode.ts');

function withWindow(run) {
  const previous = Object.prototype.hasOwnProperty.call(globalThis, 'window') ? globalThis.window : undefined;
  const window = new EventTarget();
  globalThis.window = window;
  try {
    return run(window);
  } finally {
    if (previous === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = previous;
    }
  }
}

function postFromHost(window, data) {
  const event = new Event('message');
  Object.defineProperty(event, 'data', { value: data });
  window.dispatchEvent(event);
}

function freshModule() {
  delete require.cache[require.resolve(vscodeModulePath)];
  return require(vscodeModulePath);
}

test('a well-formed host message is delivered with its payload parsed', () => {
  withWindow((window) => {
    const { subscribeToHostMessages } = freshModule();
    const received = [];
    const unsubscribe = subscribeToHostMessages((message) => received.push(message));

    postFromHost(window, { type: 'remoteCompanion/state', payload: { state: 'ready', remoteName: 'ssh-remote' } });
    postFromHost(window, {
      type: 'operation/lifecycle',
      payload: { identity: { requestId: 'req-1', generation: 2, workspaceId: 'ws', sessionId: 's', revision: 3 }, phase: 'running' },
      scope: { generation: 2, revision: 5, messageId: 'm', workspaceId: 'ws', sessionId: 's' },
      operationPhase: 'running',
    });

    assert.equal(received.length, 2);
    assert.deepEqual(received[0], { type: 'remoteCompanion/state', payload: { state: 'ready', remoteName: 'ssh-remote' } });
    assert.equal(received[1].payload.phase, 'running');
    assert.equal(received[1].payload.identity.requestId, 'req-1');
    assert.equal(received[1].scope.revision, 5);
    assert.equal(received[1].operationPhase, 'running');
    unsubscribe();
  });
});

test('a message that does not fit the schema never reaches the workbench', () => {
  withWindow((window) => {
    const { subscribeToHostMessages } = freshModule();
    const received = [];
    const unsubscribe = subscribeToHostMessages((message) => received.push(message));

    const malformed = [
      null,
      undefined,
      'state/patch',
      42,
      {},
      { type: 'notAKnownType', payload: {} },
      // A known type whose payload is missing or wrong.
      { type: 'remoteCompanion/state' },
      { type: 'remoteCompanion/state', payload: { state: 'definitely-not-a-state' } },
      { type: 'remoteCompanion/state', payload: { state: 1 } },
      { type: 'remoteVerification/finished', payload: { sessionId: 's', state: 'completed', exitCode: 'zero', summary: 'ok' } },
      { type: 'remoteVerification/stream', payload: { sessionId: 's', stream: 'stdin', text: 'x' } },
      { type: 'state/syncStatus', payload: { status: 'current', generation: 0 } },
      { type: 'skills/draftResult', payload: { requestId: 'r', ok: true, draft: { trigger: 't', title: 'd', detail: 'x', prompt: 'p', source: 'elsewhere' } } },
      // An identity with a field of the wrong type.
      { type: 'operation/lifecycle', payload: { identity: { requestId: 'req-1', generation: 'two', workspaceId: 'ws', sessionId: 's', revision: 0 }, phase: 'running' } },
    ];
    for (const message of malformed) {
      postFromHost(window, message);
    }

    assert.deepEqual(received, [], 'nothing malformed is delivered');

    // A structurally valid message with a malformed optional envelope is
    // still delivered, without the envelope.
    postFromHost(window, {
      type: 'operation/lifecycle',
      payload: { identity: { requestId: 'req-2', generation: 1, workspaceId: 'ws', sessionId: 's', revision: 0 }, phase: 'failed' },
      scope: { generation: 1, revision: 5 },
      operationPhase: 'not-a-phase',
    });
    assert.equal(received.length, 1);
    assert.equal(received[0].payload.phase, 'failed');
    assert.equal('scope' in received[0], false);
    assert.equal('operationPhase' in received[0], false);

    // Unsubscribing stops delivery.
    unsubscribe();
    postFromHost(window, { type: 'remoteCompanion/state', payload: { state: 'ready' } });
    assert.equal(received.length, 1);
  });
});

test('unknown fields are stripped rather than passed into the workbench', () => {
  withWindow((window) => {
    const { subscribeToHostMessages } = freshModule();
    const received = [];
    const unsubscribe = subscribeToHostMessages((message) => received.push(message));

    postFromHost(window, {
      type: 'browserCapture/statusResult',
      payload: { prepared: true, paired: true, version: '0.3.0', injectedByHost: 'nope' },
      extraTopLevelField: 'nope',
    });

    assert.deepEqual(received, [
      { type: 'browserCapture/statusResult', payload: { prepared: true, paired: true, version: '0.3.0' } },
    ]);
    unsubscribe();
  });
});

test('the resource version schema keeps its bounds', () => {
  withWindow(() => {
    const { resourceVersionResultsSchema } = freshModule();
    const entry = { resource_id: 'r', version_id: 'v', content_hash: 'h', status: 'unchanged' };
    const first = resourceVersionResultsSchema.safeParse([entry]);
    assert.equal(first.success, true);
    assert.deepEqual(first.data, [entry]);

    // `basis` may be absent or null.
    assert.equal(resourceVersionResultsSchema.safeParse([{ ...entry, basis: null }]).success, true);
    assert.equal(resourceVersionResultsSchema.safeParse([{ ...entry, basis: 'page' }]).success, true);
    // At most four results travel at once.
    assert.equal(resourceVersionResultsSchema.safeParse(Array.from({ length: 4 }, () => entry)).success, true);
    assert.equal(resourceVersionResultsSchema.safeParse(Array.from({ length: 5 }, () => entry)).success, false);
    assert.equal(resourceVersionResultsSchema.safeParse([{ ...entry, status: 'somewhere-else' }]).success, false);
    assert.equal(resourceVersionResultsSchema.safeParse([{ ...entry, basis: 'content_hash' }]).success, false);
    assert.equal(resourceVersionResultsSchema.safeParse('not a list').success, false);
  });
});
