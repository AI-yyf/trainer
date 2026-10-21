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

  // A streaming burst: five patches inside one debounce window. The old
  // implementation cleared and re-armed the timer on every call, so a busy
  // conversation could defer the write indefinitely.
  for (let count = 1; count <= 3; count += 1) {
    cache.schedulePersist('workspace-a', bootstrapWithMessages(count));
    t.mock.timers.tick(400);
  }
  assert.equal(context.writes.length, 0, 'nothing is written before the window closes');

  // Patches keep arriving at the edge of the window; they must coalesce into
  // the single write that the first patch armed.
  cache.schedulePersist('workspace-a', bootstrapWithMessages(4));
  cache.schedulePersist('workspace-a', bootstrapWithMessages(5));
  t.mock.timers.tick(400);
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(context.writes.length, 1, 'the burst produces exactly one write');
  const envelope = JSON.parse(context.writes[0].value);
  assert.equal(envelope.bootstrap.conversation.length, 5);
  assert.equal(envelope.bootstrap.conversation[4].id, 'm-4');
  assert.equal(context.writes[0].key, 'trainer.bootstrapSnapshot.v1.workspace-a');
  cache.dispose();
});

test('flush persists the newest pending payload immediately', async () => {
  const context = createFakeContext();
  const cache = loadCache(context);

  cache.schedulePersist('workspace-a', bootstrapWithMessages(2));
  cache.schedulePersist('workspace-a', bootstrapWithMessages(3));
  assert.equal(context.writes.length, 0);

  await cache.flush();

  assert.equal(context.writes.length, 1);
  assert.equal(JSON.parse(context.writes[0].value).bootstrap.conversation.length, 3);
  assert.equal(cache.load('workspace-a').conversation.length, 3);
  cache.dispose();
});

test('load rejects a payload from a different workspace and empty threads are not cached', async () => {
  const context = createFakeContext();
  const cache = loadCache(context);

  cache.schedulePersist('workspace-a', bootstrapWithMessages(0));
  await cache.flush();
  assert.equal(context.writes.length, 0, 'empty conversations are not worth a write');
  assert.equal(cache.load('workspace-b'), undefined);

  cache.schedulePersist('workspace-a', bootstrapWithMessages(1));
  await cache.flush();
  assert.equal(cache.load('workspace-b'), undefined);
  assert.equal(cache.load('workspace-a').workspaceName, 'trainer-cache-test');
  cache.dispose();
});

test('a half-finished stream never resurrects from the cache', async () => {
  const context = createFakeContext();
  const cache = loadCache(context);
  const bootstrap = bootstrapWithMessages(1);
  bootstrap.streamingState = { isStreaming: true, streamMessageId: 'stale-stream' };

  cache.schedulePersist('workspace-a', bootstrap);
  await cache.flush();

  const restored = cache.load('workspace-a');
  assert.notEqual(restored.streamingState?.streamMessageId, 'stale-stream');
  assert.equal(restored.streamingState?.isStreaming, false);
  cache.dispose();
});

test('clear removes the cached envelope', async () => {
  const context = createFakeContext();
  const cache = loadCache(context);

  cache.schedulePersist('workspace-a', bootstrapWithMessages(2));
  await cache.flush();
  await cache.clear('workspace-a');

  assert.equal(cache.load('workspace-a'), undefined);
  cache.dispose();
});
