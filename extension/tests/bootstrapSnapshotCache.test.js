'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const cacheModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'bootstrapSnapshotCache.js',
);

const VSCODE_MOCK = {};

function createFakeContext() {
  const stored = new Map();
  const writes = [];
  return {
    stored,
    writes,
    workspaceState: {
      get(key) {
        return stored.get(key);
      },
      update(key, value) {
        writes.push({ key, value });
        if (value === undefined) {
          stored.delete(key);
        } else {
          stored.set(key, value);
        }
        return Promise.resolve();
      },
    },
  };
}

function bootstrapWithMessages(count) {
  return {
    workspaceName: 'trainer-cache-test',
    conversation: Array.from({ length: count }, (_, index) => ({
      id: `m-${index}`,
      role: 'user',
      text: `message ${index}`,
    })),
  };
}

function loadCache(context) {
  const { BootstrapSnapshotCache } = loadWithVscodeMock(cacheModulePath, VSCODE_MOCK);
  return new BootstrapSnapshotCache(context);
}

test('repeated schedulePersist calls do not starve the debounced write', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const context = createFakeContext();
  const cache = loadCache(context);

  for (let count = 1; count <= 3; count += 1) {
    cache.schedulePersist('workspace-a', bootstrapWithMessages(count), 'session-a');
    t.mock.timers.tick(400);
  }
  assert.equal(context.writes.length, 0, 'nothing is written before the window closes');

  cache.schedulePersist('workspace-a', bootstrapWithMessages(4), 'session-a');
  cache.schedulePersist('workspace-a', bootstrapWithMessages(5), 'session-a');
  t.mock.timers.tick(400);
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(context.writes.length, 1, 'the burst produces exactly one write');
  const envelope = JSON.parse(context.writes[0].value);
  assert.equal(envelope.bootstrap.conversation.length, 5);
  assert.equal(envelope.sessionId, 'session-a');
  assert.equal(context.writes[0].key, 'trainer.bootstrapSnapshot.v1.workspace-a');
  cache.dispose();
});

test('flush persists the newest pending payload immediately', async () => {
  const context = createFakeContext();
  const cache = loadCache(context);

  cache.schedulePersist('workspace-a', bootstrapWithMessages(2), 'session-a');
  cache.schedulePersist('workspace-a', bootstrapWithMessages(3), 'session-a');
  assert.equal(context.writes.length, 0);

  await cache.flush();

  assert.equal(context.writes.length, 1);
  const entry = cache.load('workspace-a');
  assert.equal(entry.bootstrap.conversation.length, 3);
  assert.equal(entry.sessionId, 'session-a');
  cache.dispose();
});

test('a session-less snapshot never evicts a bound snapshot', async () => {
  const context = createFakeContext();
  const cache = loadCache(context);

  cache.schedulePersist('workspace-a', bootstrapWithMessages(2), 'session-a');
  await cache.flush();

  cache.schedulePersist('workspace-a', bootstrapWithMessages(1), undefined);
  await cache.flush();
  const entry = cache.load('workspace-a');
  assert.equal(entry.bootstrap.conversation.length, 2, 'unbound write must not land');
  assert.equal(entry.sessionId, 'session-a');
  cache.dispose();
});

test('an empty conversation bound to a session overwrites the cached thread', async () => {
  const context = createFakeContext();
  const cache = loadCache(context);

  cache.schedulePersist('workspace-a', bootstrapWithMessages(3), 'session-a');
  await cache.flush();

  // The user started a new thread: empty conversation, new session id.
  cache.schedulePersist('workspace-a', bootstrapWithMessages(0), 'session-b');
  await cache.flush();

  const entry = cache.load('workspace-a');
  assert.equal(entry.bootstrap.conversation.length, 0, 'stale thread is not restored');
  assert.equal(entry.sessionId, 'session-b');
  cache.dispose();
});

test('a half-finished stream never resurrects from the cache', async () => {
  const context = createFakeContext();
  const cache = loadCache(context);
  const bootstrap = bootstrapWithMessages(1);
  bootstrap.streamingState = { isStreaming: true, streamMessageId: 'stale-stream' };

  cache.schedulePersist('workspace-a', bootstrap, 'session-a');
  await cache.flush();

  const entry = cache.load('workspace-a');
  assert.notEqual(entry.bootstrap.streamingState?.streamMessageId, 'stale-stream');
  assert.equal(entry.bootstrap.streamingState?.isStreaming, false);
  cache.dispose();
});

test('clear removes the cached envelope', async () => {
  const context = createFakeContext();
  const cache = loadCache(context);

  cache.schedulePersist('workspace-a', bootstrapWithMessages(2), 'session-a');
  await cache.flush();
  await cache.clear('workspace-a');

  assert.equal(cache.load('workspace-a'), undefined);
  cache.dispose();
});
