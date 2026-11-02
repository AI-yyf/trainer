'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const pollerModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'browserCapture',
  'libraryPoller.js',
);

const { BrowserLibraryPoller, parseBrowserLibraryRevision } = require(pollerModulePath);

function harness({
  visible = true,
  port = 34891,
  workspaceId = 'workspace-a',
  revisions = ['r1'],
  refreshError,
  workspaceStamp,
} = {}) {
  let cursor = 0;
  const refreshes = [];
  const errors = [];
  const fetches = [];
  const poller = new BrowserLibraryPoller({
    getSidecarPort: () => (port === null ? undefined : port),
    isWorkbenchVisible: () => visible,
    getWorkspaceId: () => workspaceId,
    fetchLibraryRevision: async (requestedPort, requestedWorkspace) => {
      fetches.push({ port: requestedPort, workspaceId: requestedWorkspace });
      const revision = revisions[Math.min(cursor, revisions.length - 1)];
      cursor += 1;
      return {
        workspace_id: workspaceStamp ?? requestedWorkspace,
        count: cursor,
        revision,
      };
    },
    refreshLibrary: async (revision) => {
      if (refreshError) {
        throw new Error(refreshError);
      }
      refreshes.push(revision.revision);
    },
    intervalMs: 1_000,
    onError: (message) => errors.push(message),
  });
  return { poller, refreshes, errors, fetches };
}

test('first read only establishes the baseline; changes refresh once', async () => {
  const { poller, refreshes } = harness({ revisions: ['r1', 'r2', 'r2', 'r3'] });
  assert.deepEqual(await poller.pollOnce(), {
    state: 'baseline',
    workspaceId: 'workspace-a',
    count: 1,
    revision: 'r1',
  });
  assert.equal(refreshes.length, 0);

  assert.equal((await poller.pollOnce()).state, 'changed');
  assert.deepEqual(refreshes, ['r2']);

  assert.equal((await poller.pollOnce()).state, 'unchanged');
  assert.deepEqual(refreshes, ['r2']);

  assert.equal((await poller.pollOnce()).state, 'changed');
  assert.deepEqual(refreshes, ['r2', 'r3']);
});

test('hidden, unscoped and stopped-sidecar states do not fetch or refresh', async () => {
  const hidden = harness({ visible: false });
  assert.equal((await hidden.poller.pollOnce()).state, 'hidden');
  assert.equal(hidden.fetches.length, 0);

  const unscoped = harness({ workspaceId: '  ' });
  assert.equal((await unscoped.poller.pollOnce()).state, 'unscoped');
  assert.equal(unscoped.fetches.length, 0);

  const stopped = harness({ port: null });
  assert.equal((await stopped.poller.pollOnce()).state, 'no-sidecar');
  assert.equal(stopped.fetches.length, 0);
  assert.equal(stopped.refreshes.length, 0);
});

test('a foreign workspace stamp never refreshes this workbench', async () => {
  const { poller, refreshes, errors } = harness({ workspaceStamp: 'workspace-b' });
  const result = await poller.pollOnce();
  assert.equal(result.state, 'unscoped');
  assert.equal(result.workspaceId, 'workspace-b');
  assert.equal(refreshes.length, 0);
  assert.match(errors[0], /belongs to workspace-b/);
});

test('a failed refresh is reported and the next tick retries', async () => {
  const errors = [];
  let fail = true;
  let cursor = 0;
  const refreshes = [];
  const poller = new BrowserLibraryPoller({
    getSidecarPort: () => 34891,
    isWorkbenchVisible: () => true,
    getWorkspaceId: () => 'workspace-a',
    fetchLibraryRevision: async () => {
      cursor += 1;
      return { workspace_id: 'workspace-a', count: cursor, revision: `r${cursor}` };
    },
    refreshLibrary: async (revision) => {
      if (fail) {
        throw new Error('summary unavailable');
      }
      refreshes.push(revision.revision);
    },
    intervalMs: 0,
    onError: (message) => errors.push(message),
  });
  assert.equal((await poller.pollOnce()).state, 'baseline');
  assert.equal((await poller.pollOnce()).state, 'error');
  assert.match(errors[0], /summary unavailable/);
  fail = false;
  assert.equal((await poller.pollOnce()).state, 'changed');
  assert.deepEqual(refreshes, ['r3']);
});

test('parses the host-facing revision payload and ignores malformed values', () => {
  assert.deepEqual(
    parseBrowserLibraryRevision({ workspace_id: 'w', count: 2, revision: 'abc' }),
    { workspaceId: 'w', count: 2, revision: 'abc' },
  );
  assert.deepEqual(parseBrowserLibraryRevision(null), {
    workspaceId: '',
    count: 0,
    revision: '',
  });
});
