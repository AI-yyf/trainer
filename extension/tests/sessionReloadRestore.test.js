'use strict';

/**
 * Reload-restore behavior (root-cause guard): a persisted session id survives
 * a host reload and the stored conversation comes back with it.
 *
 * 保存会话 → 模拟重载 → 会话与消息恢复. The fake sidecar below is stateful
 * (sessions live in a map) the way the real repository is: /session/activate
 * resolves the stored session, /session/start resumes the workspace's latest
 * thread, /memory/summary serves the transcript.
 *
 * Regression this pins: the host used to trust the persisted session id
 * without ever asking the server. After a data-root switch or a replaced
 * database the id became dangling — the summary fell back to another thread
 * and the next turn's ensure_session() started a brand-new empty session, so
 * the reloaded history silently disappeared. The fix re-verifies the stored id
 * through /session/activate and falls back to /session/start (adopting the id
 * actually in use) when it cannot be restored.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const runtimeRehydrationModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'runtimeRehydration.js',
);
const workbenchDataModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'workbenchData.js',
);

const vscodeMock = { workspace: { name: 'trainer' }, env: { language: 'zh-cn' } };

const { createDefaultBootstrapData } = loadWithVscodeMock(workbenchDataModulePath, vscodeMock);
const { rehydrateWorkbenchRuntime } = loadWithVscodeMock(runtimeRehydrationModulePath, vscodeMock);

// The host derives the runtime workspace id from the sovereign project path
// and normalizes it with the host platform's path rules (on Windows the same
// root resolves to an absolute drive path like D:\trainer\project).
const WORKSPACE = path.resolve('/trainer/project');

/** Minimal stateful stand-in for the sidecar's session store. */
function createFakeSidecar(sessions, latestSessionId) {
  const requests = [];
  return {
    requests,
    // "保存会话": a session with its transcript already persisted.
    async postJson(_port, requestPath, body) {
      requests.push({ requestPath, body });
      if (requestPath === '/session/activate') {
        const session = sessions.get(body?.session_id);
        if (!session) {
          throw new Error('Sidecar request failed (404): session not found');
        }
        return {
          session_id: session.sessionId,
          workspace_id: WORKSPACE,
          snapshot: sessionSnapshot(session),
        };
      }
      if (requestPath === '/session/start') {
        // The server resumes the workspace's latest thread on plain starts.
        const session = sessions.get(latestSessionId) ?? undefined;
        if (!session) {
          throw new Error('Sidecar request failed (500): no session');
        }
        return {
          session_id: session.sessionId,
          context_id: WORKSPACE,
          sessionHistoryRestored: true,
          ...sessionSnapshot(session),
        };
      }
      throw new Error(`Unexpected postJson ${requestPath}`);
    },
    async getJson(_port, requestPath) {
      requests.push({ requestPath });
      if (String(requestPath).startsWith('/memory/summary')) {
        const params = new URL(`http://localhost${requestPath}`).searchParams;
        const session = sessions.get(params.get('session_id')) ?? sessions.get(latestSessionId);
        if (!session) {
          return { contextId: WORKSPACE, sessionHistoryRestored: false, messages: [] };
        }
        return sessionSnapshot(session);
      }
      if (String(requestPath).startsWith('/resource/trash')) {
        return { workspace_id: WORKSPACE, items: [] };
      }
      return {};
    },
  };
}

function sessionSnapshot(session) {
  return {
    contextId: WORKSPACE,
    sessionHistoryRestored: true,
    messages: session.messages.map((message) => ({ ...message })),
    plan: null,
    current_task: null,
    memory: { workspace: { workspace_id: WORKSPACE } },
  };
}

/** A fresh host context — what a window reload rebuilds, plus the persisted id. */
function createReloadedHost(sidecar, persistedSessionId, sessionIds) {
  const workspace = { trusted: true, activeWorkspaceRoot: '/trainer/project' };
  const bootstrap = createDefaultBootstrapData(workspace);
  bootstrap.memory.workspace = {
    ...(bootstrap.memory.workspace ?? {}),
    workspaceId: WORKSPACE,
    trainerWorkspace: { status: 'managed' },
  };
  bootstrap.workspaceTrainingState = { workspaceId: WORKSPACE };
  const hostState = {
    sessionId: persistedSessionId,
    workspace,
    bootstrap,
  };
  const context = {
    trainerWorkspace: { getRoot: () => '/trainer' },
    getSessionId: () => hostState.sessionId,
    getHostState: () => hostState,
    sidecarManager: {
      getStatus: () => ({ lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true }),
      async setManagedDataRootScope() {},
      async ensureRunning() {
        return { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true };
      },
    },
    sidecarClient: sidecar,
    async setSessionId(sessionId) {
      hostState.sessionId = sessionId;
      sessionIds.push(sessionId);
    },
    async patchWorkbenchData(patch) {
      Object.assign(hostState.bootstrap, patch);
    },
    outputChannel: { appendLine() {} },
    workbench: { async syncState() {} },
  };
  return { context, hostState };
}

const SAVED_MESSAGES = [
  { id: 'm1', role: 'user', content: '保存下来的用户消息', timestamp: '2026-10-14T10:00:00Z' },
  { id: 'm2', role: 'assistant', content: '保存下来的教练回复', timestamp: '2026-10-14T10:00:05Z' },
];

test('reload restores the stored session and its messages', async () => {
  const sessions = new Map([
    ['session-saved', { sessionId: 'session-saved', messages: SAVED_MESSAGES }],
  ]);
  const sidecar = createFakeSidecar(sessions, 'session-saved');
  const sessionIds = [];
  const { context, hostState } = createReloadedHost(sidecar, 'session-saved', sessionIds);

  await rehydrateWorkbenchRuntime(context, { ensureSidecar: true, syncWorkbench: true });

  // Session identity survives the reload.
  assert.equal(hostState.sessionId, 'session-saved');
  assert.deepEqual(sessionIds, [], 'the stored id is kept, not replaced');
  // Messages come back with it.
  const conversation = hostState.bootstrap.conversation;
  assert.equal(conversation.length, 2);
  assert.equal(conversation[0].body, '保存下来的用户消息');
  assert.equal(conversation[1].body, '保存下来的教练回复');
  assert.equal(hostState.bootstrap.sessionHistoryRestored, true);
  // The stored id is verified with the server before the refresh runs.
  assert.equal(sidecar.requests[0].requestPath, '/session/activate');
  assert.deepEqual(sidecar.requests[0].body, {
    session_id: 'session-saved',
    workspace_id: WORKSPACE,
  });
});

test('a stale stored session id self-heals to the workspace latest thread', async () => {
  // The persisted id is gone (database replaced / data root moved), but the
  // workspace still has a latest thread with real history.
  const sessions = new Map([
    ['session-latest', { sessionId: 'session-latest', messages: SAVED_MESSAGES }],
  ]);
  const sidecar = createFakeSidecar(sessions, 'session-latest');
  const sessionIds = [];
  const { context, hostState } = createReloadedHost(sidecar, 'session-gone', sessionIds);

  await rehydrateWorkbenchRuntime(context, { ensureSidecar: true, syncWorkbench: true });

  // The dangling id is replaced by the session actually in use, so the next
  // turn continues the restored thread instead of starting an empty session.
  assert.equal(hostState.sessionId, 'session-latest');
  assert.deepEqual(sessionIds, ['session-latest']);
  assert.equal(hostState.bootstrap.conversation[0].body, '保存下来的用户消息');
  assert.equal(hostState.bootstrap.sessionHistoryRestored, true);
  assert.deepEqual(
    sidecar.requests.slice(0, 4).map((request) => request.requestPath),
    [
      '/session/activate',
      '/session/start',
      `/memory/summary?workspace_id=${encodeURIComponent(WORKSPACE)}&session_id=session-latest`,
      `/resource/trash?workspace_id=${encodeURIComponent(WORKSPACE)}`,
    ],
  );
});
