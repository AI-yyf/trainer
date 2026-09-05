'use strict';

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

const {
  ensureInitialSession,
  rehydrateWorkbenchRuntime,
  trainerSessionBlockReason,
} = loadWithVscodeMock(runtimeRehydrationModulePath, {
  workspace: {
    name: 'trainer-workspace',
  },
});

test('automatic session initialization sends the authoritative workspace path to the sidecar', async () => {
  const workspacePath = 'H:\\projects\\trainer-workspace';
  const requests = [];
  const appliedSessionIds = [];

  const context = {
    trainerWorkspace: {
      getRoot() {
        return 'H:\\trainer-workspace-root';
      },
    },
    getSessionId() {
      return undefined;
    },
    getHostState() {
      return {
        workspace: {
          workspaceFolder: workspacePath,
        },
        bootstrap: {},
      };
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        requests.push({ port, requestPath, body });
        return {};
      },
    },
    async setSessionId(sessionId) {
      appliedSessionIds.push(sessionId);
    },
    async patchWorkbenchData() {},
    outputChannel: {
      appendLine() {},
    },
  };

  const sessionId = await ensureInitialSession(context, 34891);

  assert.equal(sessionId, undefined);
  assert.deepEqual(appliedSessionIds, []);
  assert.deepEqual(requests, [
    {
      port: 34891,
      requestPath: '/session/start',
      body: {
        workspace_id: workspacePath,
        workspace_name: 'trainer-workspace',
        workspace_path: workspacePath,
        remote_name: '',
        workspace_trusted: false,
      },
    },
  ]);
});

test('automatic session initialization carries a saved workspace language to the sidecar', async () => {
  const workspacePath = 'H:\\projects\\trainer-workspace';
  const requests = [];
  const context = {
    trainerWorkspace: {
      getRoot() {
        return 'H:\\trainer-workspace-root';
      },
    },
    getSessionId() {
      return undefined;
    },
    getHostState() {
      return {
        workspace: {
          workspaceFolder: workspacePath,
        },
        bootstrap: {
          memory: {
            workspace: {
              responseLanguage: 'ja-JP',
            },
          },
        },
      };
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        requests.push({ port, requestPath, body });
        return {};
      },
    },
    async setSessionId() {},
    async patchWorkbenchData() {},
    outputChannel: {
      appendLine() {},
    },
  };

  await ensureInitialSession(context, 34891);

  assert.deepEqual(requests, [
    {
      port: 34891,
      requestPath: '/session/start',
      body: {
        workspace_id: workspacePath,
        workspace_name: 'trainer-workspace',
        workspace_path: workspacePath,
        remote_name: '',
        workspace_trusted: false,
        response_language: 'ja-JP',
      },
    },
  ]);
});

test('automatic session initialization drops a response that belongs to a workspace left during the request', async () => {
  const workspaceA = 'H:\\projects\\workspace-a';
  const workspaceB = 'H:\\projects\\workspace-b';
  const hostState = {
    workspace: {
      workspaceFolder: workspaceA,
    },
    bootstrap: {},
    sessionId: undefined,
  };
  const appliedSessionIds = [];
  let resolveStart;
  const startResponse = new Promise((resolve) => {
    resolveStart = resolve;
  });

  const context = {
    trainerWorkspace: {
      getRoot() {
        return 'H:\\trainer-workspace-root';
      },
    },
    getSessionId() {
      return hostState.sessionId;
    },
    getHostState() {
      return hostState;
    },
    sidecarClient: {
      async postJson() {
        return startResponse;
      },
    },
    async setSessionId(sessionId) {
      appliedSessionIds.push(sessionId);
      hostState.sessionId = sessionId;
    },
    async patchWorkbenchData() {},
    outputChannel: {
      appendLine() {},
    },
  };

  const initialization = ensureInitialSession(context, 34891);
  hostState.workspace.workspaceFolder = workspaceB;
  resolveStart({ session_id: 'session-from-workspace-a' });

  assert.equal(await initialization, undefined);
  assert.deepEqual(appliedSessionIds, []);
  assert.equal(hostState.sessionId, undefined);
});

test('workspace admission blocks automatic sessions even when a stale root path remains configured', async () => {
  const workspacePath = 'H:\\projects\\trainer-workspace';
  const cases = [
    ['root-missing', /选择 Trainer 工作区/],
    ['project-found', /加入 Trainer.*仅浏览.*忽略/],
    ['browse', /只能浏览/],
    ['ignored', /已被忽略/],
  ];

  for (const [status, expectedMessage] of cases) {
    const requests = [];
    const context = {
      trainerWorkspace: {
        getRoot() {
          return 'H:\\trainer-workspace-root';
        },
      },
      getSessionId() {
        return undefined;
      },
      getHostState() {
        return {
          workspace: {
            workspaceFolder: workspacePath,
          },
          bootstrap: {
            memory: {
              workspace: {
                trainerWorkspace: { status },
              },
            },
          },
        };
      },
      sidecarClient: {
        async postJson(port, requestPath, body) {
          requests.push({ port, requestPath, body });
          return {};
        },
      },
      async setSessionId() {},
      async patchWorkbenchData() {},
      outputChannel: {
        appendLine() {},
      },
    };

    assert.match(trainerSessionBlockReason(context), expectedMessage);
    assert.equal(await ensureInitialSession(context, 34891), undefined);
    assert.deepEqual(requests, []);
  }
});

test('root-missing rehydration does not restart the sidecar or prefetch provider models', async () => {
  const workspacePath = 'H:\\projects\\trainer-workspace';
  let ensureRunningCalls = 0;
  let modelRequests = 0;
  let sessionRequests = 0;
  let scopeUpdates = 0;

  const context = {
    trainerWorkspace: {
      getRoot() {
        return 'H:\\trainer-workspace-root';
      },
    },
    getSessionId() {
      return undefined;
    },
    getHostState() {
      return {
        workspace: {
          trusted: true,
          workspaceFolder: workspacePath,
        },
        bootstrap: {
          memory: {
            workspace: {
              trainerWorkspace: { status: 'root-missing' },
            },
          },
          providerConfig: {
            configured: true,
            apiKeyConfigured: true,
            name: 'Example provider',
            baseUrl: 'https://example.invalid/v1',
            model: 'example-model',
            protocol: 'openai_chat_completions_compatible',
          },
        },
      };
    },
    sidecarManager: {
      getStatus() {
        return { lifecycle: 'ready', port: 34891, canStart: true };
      },
      async setManagedDataRootScope() {
        scopeUpdates += 1;
      },
      hasPendingManagedDataScopeRestart() {
        return true;
      },
      async ensureRunning() {
        ensureRunningCalls += 1;
        return { lifecycle: 'ready', port: 34891, canStart: true };
      },
    },
    providerStore: {
      getConfig() {
        return {
          name: 'Example provider',
          baseUrl: 'https://example.invalid/v1',
          model: 'example-model',
          protocol: 'openai_chat_completions_compatible',
        };
      },
      async getApiKey() {
        return 'test-key';
      },
    },
    sidecarClient: {
      async postJson(_port, requestPath) {
        if (requestPath === '/provider/models') {
          modelRequests += 1;
        }
        if (requestPath === '/session/start') {
          sessionRequests += 1;
        }
        return {};
      },
    },
    async patchWorkbenchData() {},
    outputChannel: {
      appendLine() {},
    },
  };

  await rehydrateWorkbenchRuntime(context, { ensureSidecar: true });

  assert.equal(scopeUpdates, 1);
  assert.equal(ensureRunningCalls, 0);
  assert.equal(modelRequests, 0);
  assert.equal(sessionRequests, 0);
});
