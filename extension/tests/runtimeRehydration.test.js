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

const vscodeMock = {
  workspace: {
    name: 'trainer',
  },
};

const {
  buildTrainerRuntimeStatus,
  rehydrateWorkbenchRuntime,
  refreshWorkbenchResourceTrash,
  shouldAutoStartSidecar,
  trainerSessionBlockReason,
} = loadWithVscodeMock(
  runtimeRehydrationModulePath,
  {
    ...vscodeMock,
    env: { language: 'en' },
  },
);

function createContext(providerConfig, sidecar) {
  return {
    getHostState() {
      return {
        bootstrap: {
          providerConfig,
          memory: {
            workspace: {
              trainerWorkspace: {
                status: 'managed',
              },
            },
          },
        },
      };
    },
    sidecarManager: {
      getStatus() {
        return sidecar;
      },
    },
    trainerWorkspace: {
      getRoot() {
        return 'C:\\trainer-workspace-tests\\root';
      },
    },
  };
}

test('runtime status reports provider setup work instead of claiming full readiness', () => {
  const context = createContext(
    {
      configured: true,
      apiKeyConfigured: false,
      name: 'openai',
      baseUrl: 'https://api.openai.com/v1',
      model: 'gpt-4.1-mini',
      availableModels: [],
      modelListStatus: 'idle',
    },
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 8765,
      canStart: true,
    },
  );

  const status = buildTrainerRuntimeStatus(context);

  assert.equal(status.tone, 'info');
  assert.match(status.message, /connection is not complete yet/i);
  assert.match(status.message, /add the key in settings/i);
  assert.doesNotMatch(status.message, /^Trainer is ready\./i);
});

test('runtime status reports full readiness only when sidecar and provider are both usable', () => {
  const context = createContext(
    {
      configured: true,
      apiKeyConfigured: true,
      name: 'openai',
      baseUrl: 'https://api.openai.com/v1',
      model: 'gpt-4.1-mini',
      availableModels: ['gpt-4.1-mini'],
      modelListStatus: 'ready',
      protocol: 'openai_chat_completions',
      lastTestResult: {
        ok: true,
        status: 'connected',
        checkedAt: new Date().toISOString(),
        providerName: 'openai',
        baseUrl: 'https://api.openai.com/v1',
        model: 'gpt-4.1-mini',
        protocol: 'openai_chat_completions',
      },
    },
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 8765,
      canStart: true,
    },
  );

  const status = buildTrainerRuntimeStatus(context);

  assert.equal(status.tone, 'success');
  assert.match(status.message, /^Trainer is ready\./i);
});

test('runtime recovery status follows the saved language and does not leak backend details', () => {
  const providerConfig = {
    configured: true,
    apiKeyConfigured: true,
    model: 'demo-model',
    availableModels: ['demo-model'],
    modelListStatus: 'ready',
  };
  const projectFoundContext = createContext(
    providerConfig,
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 8765,
      canStart: true,
    },
  );
  projectFoundContext.getHostState = () => ({
    bootstrap: {
      providerConfig,
      memory: {
        workspace: {
          responseLanguage: 'zh-CN',
          trainerWorkspace: { status: 'project-found' },
        },
      },
    },
  });

  const blocked = trainerSessionBlockReason(projectFoundContext);

  assert.equal(blocked, '发现了这个项目。先选择“加入 Trainer”“仅浏览”或“忽略”。');
  assert.doesNotMatch(blocked, /Choose whether|browse-only/i);

  const unavailable = buildTrainerRuntimeStatus(projectFoundContext, {
    lifecycle: 'error',
    host: '127.0.0.1',
    canStart: true,
    detail: 'internal launch trace with local path and command arguments',
  });

  assert.equal(unavailable.tone, 'error');
  assert.equal(unavailable.message, 'Trainer 现在还不能使用。稍后再试，或在设置中重新启动。');
  assert.doesNotMatch(unavailable.message, /internal launch trace/i);
});

test('auto-start guard respects explicitly stopped and unavailable sidecars', () => {
  assert.equal(
    shouldAutoStartSidecar({
      lifecycle: 'stopped',
      host: '127.0.0.1',
      canStart: true,
      detail: 'Sidecar stopped.',
    }),
    false,
  );
  assert.equal(
    shouldAutoStartSidecar({
      lifecycle: 'unavailable',
      host: '127.0.0.1',
      canStart: false,
    }),
    false,
  );
  assert.equal(
    shouldAutoStartSidecar({
      lifecycle: 'idle',
      host: '127.0.0.1',
      canStart: true,
    }),
    true,
  );
});

test('runtime rehydration restores durable Trash with the sovereign workspace before Resources opens', async () => {
  const workspaceRoot = 'F:\\trainer\\workspace-a';
  const workspaceFolder = 'F:\\projects\\source-a';
  const requests = [];
  const patches = [];
  const bootstrap = {
    providerConfig: {},
    memory: {
      workspace: {
        trainerWorkspace: {
          status: 'managed',
        },
      },
    },
    resources: [],
    deletedResources: [
      {
        resourceId: 'previous-trash',
        title: 'Previous Trash',
        recoverable: true,
      },
    ],
  };
  const hostState = {
    workspace: {
      trusted: true,
      activeWorkspaceRoot: workspaceRoot,
      workspaceFolder,
    },
    sessionId: 'stale-session',
    bootstrap,
  };
  const context = {
    trainerWorkspace: {
      getRoot() {
        return workspaceRoot;
      },
    },
    getSessionId() {
      return hostState.sessionId;
    },
    async setSessionId(sessionId) {
      hostState.sessionId = sessionId;
    },
    getHostState() {
      return hostState;
    },
    providerStore: {
      getConfig() {
        return undefined;
      },
      async getApiKey() {
        return undefined;
      },
    },
    sidecarManager: {
      getStatus() {
        return {
          lifecycle: 'ready',
          host: '127.0.0.1',
          port: 34891,
          canStart: true,
        };
      },
    },
    sidecarClient: {
      async getJson(port, requestPath) {
        requests.push({ port, requestPath });
        if (requestPath.startsWith('/resource/trash')) {
          return {
            workspace_id: workspaceRoot,
            items: [
              {
                resource_id: 'resource-1',
                title: 'Notes',
                recoverable: true,
              },
            ],
          };
        }
        return { memory: { resources: [] } };
      },
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
      Object.assign(hostState.bootstrap, patch);
    },
    outputChannel: {
      appendLine() {},
    },
    workbench: {
      async syncState() {},
    },
  };

  await rehydrateWorkbenchRuntime(context);

  assert.deepEqual(requests, [
    {
      port: 34891,
      requestPath: '/memory/summary?workspace_id=F%3A%5Ctrainer%5Cworkspace-a',
    },
    {
      port: 34891,
      requestPath: '/resource/trash?workspace_id=F%3A%5Ctrainer%5Cworkspace-a',
    },
  ]);
  assert.deepEqual(patches.find((patch) => patch.deletedResources)?.deletedResources, [
    {
      resourceId: 'resource-1',
      title: 'Notes',
      deletedAt: undefined,
      collectionPath: undefined,
      recoverable: true,
    },
  ]);
});

test('Trash rehydration retains the last known state for rejected Trash snapshots', async () => {
  const workspaceId = 'F:\\trainer\\workspace-a';
  const rejectedResponses = [
    {
      response: { workspace_id: 'F:\\trainer\\workspace-b', items: [] },
      error: /workspace did not match/,
    },
    {
      response: { workspace_id: workspaceId, items: [{ title: 'No ID' }] },
      error: /invalid item/,
    },
    {
      response: {
        workspace_id: workspaceId,
        items: [
          { resource_id: 'duplicate', title: 'First' },
          { resourceId: 'duplicate', title: 'Second' },
        ],
      },
      error: /duplicate resource IDs/,
    },
    {
      response: { workspace_id: workspaceId, items: [{ resource_id: 'partial' }] },
      error: /invalid item/,
    },
  ];

  for (const { response, error } of rejectedResponses) {
    const patches = [];
    const logs = [];
    const context = {
      trainerWorkspace: {
        getRoot() {
          return workspaceId;
        },
      },
      getHostState() {
        return {
          workspace: {
            trusted: true,
            activeWorkspaceRoot: workspaceId,
          },
          bootstrap: {
            memory: {
              workspace: {
                trainerWorkspace: {
                  status: 'managed',
                },
              },
            },
            deletedResources: [
              {
                resourceId: 'previous-trash',
                title: 'Previous Trash',
                recoverable: true,
              },
            ],
          },
        };
      },
      sidecarManager: {
        getStatus() {
          return { port: 34891 };
        },
      },
      sidecarClient: {
        async getJson() {
          return response;
        },
      },
      async patchWorkbenchData(patch) {
        patches.push(patch);
      },
      outputChannel: {
        appendLine(message) {
          logs.push(message);
        },
      },
    };

    await refreshWorkbenchResourceTrash(context, 34891);

    assert.deepEqual(patches, []);
    assert.match(logs[0], error);
  }
});

test('a workspace change waits out an older rehydration and hydrates the new workspace afterward', async () => {
  const workspaceA = 'F:\\workspace-a';
  const workspaceB = 'F:\\workspace-b';
  const requests = [];
  const pendingResponses = [];
  const patches = [];
  const hostState = {
    workspace: {
      trusted: true,
      activeWorkspaceRoot: workspaceA,
    },
    sessionId: 'session-a',
    bootstrap: {
      providerConfig: {},
      memory: {
        workspace: {
          trainerWorkspace: {
            status: 'managed',
          },
        },
      },
      conversation: [
        {
          id: 'old-message',
          role: 'assistant',
          body: 'must not survive the switch',
        },
      ],
      profile: {
        learnerName: 'Learner',
        goals: [],
        focusAreas: [],
      },
      plan: { id: '', title: '', currentStep: '', stages: [] },
      task: { id: '', title: '', description: '', status: 'not_started' },
      resources: [],
      deletedResources: [],
    },
  };
  const context = {
    trainerWorkspace: {
      getRoot() {
        return 'F:\\trainer-root';
      },
    },
    getSessionId() {
      return hostState.sessionId;
    },
    async setSessionId(sessionId) {
      hostState.sessionId = sessionId;
    },
    getHostState() {
      return hostState;
    },
    providerStore: {
      getConfig() {
        return undefined;
      },
      async getApiKey() {
        return undefined;
      },
    },
    sidecarManager: {
      getStatus() {
        return {
          lifecycle: 'ready',
          host: '127.0.0.1',
          port: 34891,
          canStart: true,
        };
      },
      async setManagedDataRootScope() {},
    },
    sidecarClient: {
      async getJson(port, requestPath) {
        requests.push({ port, requestPath });
        if (requestPath.includes(encodeURIComponent(workspaceA))) {
          return new Promise((resolve) => {
            pendingResponses.push({ requestPath, resolve });
            });
        }
        if (requestPath.startsWith('/memory/summary')) {
          return {
            workspace_id: workspaceB,
            memory: { workspace: { workspace_id: workspaceB } },
            messages: [
              {
                id: 'new-message',
                role: 'assistant',
                content: 'new workspace memory',
              },
            ],
          };
        }
        return {
          workspace_id: workspaceB,
          items: [],
        };
      },
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    outputChannel: {
      appendLine() {},
    },
    workbench: {
      async syncState() {},
    },
  };

  const firstRehydration = rehydrateWorkbenchRuntime(context);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(pendingResponses.length, 2);

  hostState.workspace.activeWorkspaceRoot = workspaceB;
  hostState.sessionId = 'session-b';
  hostState.bootstrap.conversation = [];
  const secondRehydration = rehydrateWorkbenchRuntime(context, { syncWorkbench: true });
  await new Promise((resolve) => setImmediate(resolve));

  for (const pending of pendingResponses) {
    pending.resolve(
      pending.requestPath.startsWith('/memory/summary')
        ? {
            messages: [
              {
                id: 'stale-message',
                role: 'assistant',
                content: 'stale workspace memory',
              },
            ],
          }
        : {
            workspace_id: workspaceA,
            items: [],
          },
    );
  }

  await firstRehydration;
  await secondRehydration;

  assert.deepEqual(
    requests.map(({ requestPath }) => requestPath),
    [
      `/memory/summary?workspace_id=${encodeURIComponent(workspaceA)}`,
      `/resource/trash?workspace_id=${encodeURIComponent(workspaceA)}`,
      `/memory/summary?workspace_id=${encodeURIComponent(workspaceB)}`,
      `/resource/trash?workspace_id=${encodeURIComponent(workspaceB)}`,
    ],
  );
  assert.equal(
    patches.some((patch) =>
      JSON.stringify(patch).includes('stale workspace memory'),
    ),
    false,
  );
  assert.equal(
    patches.some((patch) =>
      JSON.stringify(patch).includes('new workspace memory'),
    ),
    true,
  );
});
