'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const resourceCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'resourceCommands.js',
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
const { createDefaultBootstrapData } = require(workbenchDataModulePath);

function createContext() {
  const patches = [];
  const requests = [];
  const gets = [];
  let ensureRunningCalls = 0;
  let trustCalls = 0;
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    {
      name: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      apiKeyRef: 'trainer.default',
      model: 'demo-model',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: true,
        tools: false,
        jsonSchema: false,
        streaming: true,
      },
    },
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
  );
  bootstrap.resources = [
    {
      id: 'resource-1',
      title: 'Notes',
      kind: 'markdown',
      status: 'ready',
      summary: 'Coach notes',
      source: 'F:\\trainer\\notes.md',
      sandboxPath: 'F:\\trainer\\sandboxes\\workspace-a\\notes.md',
    },
    {
      id: 'resource-2',
      title: 'Other',
      kind: 'text',
      status: 'ready',
      summary: 'Other note',
      source: 'F:\\trainer\\other.txt',
    },
  ];
  bootstrap.resourceSearch = {
    workspaceId: 'F:\\trainer\\workspace-a',
    query: 'notes',
    total: 1,
    rankingStrategy: 'lexical_first',
    filters: {},
    hits: [
      {
        id: 'resource-1',
        title: 'Notes',
        kind: 'markdown',
        status: 'ready',
        summary: 'Coach notes',
        source: 'F:\\trainer\\notes.md',
        sandboxPath: 'F:\\trainer\\sandboxes\\workspace-a\\notes.md',
        trustScore: 0.9,
        freshness: 'fresh',
        trustState: 'trusted',
        fileType: 'markdown',
        projectScope: 'workspace-a',
        indexState: 'indexed',
        citationId: 'citation:resource-1',
        canInjectTrainingCard: true,
        updatedAt: '2026-06-10T08:00:00Z',
        rankScore: 1,
        rankReasons: ['title match'],
      },
    ],
  };
  bootstrap.memory.selectedResourceDetail = {
    id: 'resource-1',
    title: 'Notes',
    kind: 'markdown',
    status: 'ready',
    summary: 'Coach notes',
    source: 'F:\\trainer\\notes.md',
    sandboxPath: 'F:\\trainer\\sandboxes\\workspace-a\\notes.md',
  };
  return {
    workbench: {
      resolveWebviewUriForPath() {
        return undefined;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        ensureRunningCalls += 1;
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        requests.push({ port, requestPath, body });
        if (requestPath === '/sandbox/restore') {
          return {
            rootPath: 'F:\\trainer\\workspace-a',
            sandboxRootPath: 'F:\\trainer\\workspace-a\\.trainer\\resources\\workspace-a',
            workspaceRootPath: 'F:\\trainer\\workspace-a',
            activeWorkspaceRoot: 'F:\\trainer\\workspace-a',
            trashRootPath: 'F:\\trainer\\workspace-a\\.trainer\\trash',
            nodes: [],
            totalSize: 0,
            lastModified: '2026-06-10T08:00:00Z',
            ready: true,
            linkedResourceCount: 0,
            totalFiles: 0,
            totalDirectories: 0,
            latestCommand: undefined,
            capabilitySummary: undefined,
            notes: [],
            authority: {
              activeWorkspaceRoot: 'F:\\trainer\\workspace-a',
              rootUri: 'F:\\trainer\\workspace-a',
              authoritySource: 'workspace_authority_service',
              remoteName: undefined,
              authorityMode: 'level_destructive',
              permissionLevel: 'DESTRUCTIVE',
              permissionLabel: 'delete/overwrite/batch move (via trash)',
              allowedOperations: ['read', 'restore'],
              ledgerEntryCount: 2,
              checkpointCount: 2,
              trashRoot: 'F:\\trainer\\workspace-a\\.trainer\\trash',
            },
          };
        }
        return {
          removed: true,
          detail: 'Resource removed from workspace and sandbox trash updated.',
          checkpoint_id: 'checkpoint-42',
          ledger_entry_id: 'ledger-99',
          patch: ['trash F:\\trainer\\notes.md -> F:\\trainer\\workspace-a\\.trainer\\trash\\notes.md'],
          diff_summary: 'Moved resource into sandbox trash',
        };
      },
      async getJson(port, requestPath) {
        gets.push({ port, requestPath });
        if (requestPath.startsWith('/resource/trash?')) {
          return {
            workspace_id: 'F:\\trainer\\workspace-a',
            items: [
              {
                resource_id: 'resource-1',
                title: 'Notes',
                collection_path: 'knowledge/Docs/notes.md',
                collection_root: 'F:\\trainer\\knowledge',
                deleted_at: '2026-06-10T08:00:00Z',
                recoverable: true,
              },
            ],
          };
        }
        return {
          memory: {
            recent_summary: 'Workspace authority refreshed after delete.',
          },
        };
      },
    },
    getHostState() {
      return {
        bootstrap,
        workspace: {
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    trustGuard: {
      async ensureTrusted() {
        trustCalls += 1;
        return true;
      },
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    __patches: patches,
    __requests: requests,
    __gets: gets,
    get __ensureRunningCalls() {
      return ensureRunningCalls;
    },
    get __trustCalls() {
      return trustCalls;
    },
  };
}

test('indexResourcesCommand reindexes stale records even when their coarse status is ready', async () => {
  const { indexResourcesCommand } = loadWithVscodeMock(resourceCommandsModulePath, {});
  const context = createContext();
  const staleResource = {
    ...context.getHostState().bootstrap.resources[0],
    id: 'resource-stale',
    title: 'Stale notes',
    freshness: 'stale',
    status: 'ready',
  };
  context.getHostState().bootstrap.resources = [
    context.getHostState().bootstrap.resources[1],
    staleResource,
  ];
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    assert.equal(requestPath, '/resource/index');
    return {
      id: body.resource_id,
      title: staleResource.title,
      kind: staleResource.kind,
      parse_status: 'parsed',
      index_status: 'indexed',
      freshness: 'fresh',
    };
  };
  context.sidecarClient.getJson = async (port, requestPath) => {
    context.__gets.push({ port, requestPath });
    return { memory: { recent_summary: 'Stale resource indexed again.' } };
  };

  const result = await indexResourcesCommand(context);

  assert.equal(result.ok, true);
  assert.deepEqual(context.__requests, [
    {
      port: 34891,
      requestPath: '/resource/index',
      body: {
        session_id: 'session-1',
        workspace_id: 'F:\\trainer\\workspace-a',
        resource_id: 'resource-stale',
        enable_network: false,
      },
    },
  ]);
  assert.equal(context.__patches.length, 2);
});

test('indexResourcesCommand keeps indexing later resources after an earlier failure', async () => {
  const { indexResourcesCommand } = loadWithVscodeMock(resourceCommandsModulePath, {});
  const context = createContext();
  context.getHostState().bootstrap.resources = [
    {
      id: 'resource-failed-first',
      title: 'Unavailable webpage',
      kind: 'url',
      status: 'attention',
      freshness: 'stale',
    },
    {
      id: 'resource-indexed-second',
      title: 'Recoverable notes',
      kind: 'markdown',
      status: 'attention',
      freshness: 'stale',
    },
  ];
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    if (body.resource_id === 'resource-failed-first') {
      throw new Error('network request failed');
    }
    return {
      id: body.resource_id,
      title: 'Recoverable notes',
      kind: 'markdown',
      parse_status: 'parsed',
      index_status: 'indexed',
      freshness: 'fresh',
    };
  };
  context.sidecarClient.getJson = async (port, requestPath) => {
    context.__gets.push({ port, requestPath });
    return { memory: { recent_summary: 'Second resource indexed.' } };
  };

  const result = await indexResourcesCommand(context);

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /indexed 1 resource/i);
  assert.match(result.message ?? '', /refresh resources to retry the rest/i);
  assert.deepEqual(
    context.__requests.map((request) => request.body.resource_id),
    ['resource-failed-first', 'resource-indexed-second'],
  );
  assert.equal(context.__patches.length, 2);
});

function createManagedDataFolderContext(selectedFolder) {
  const patches = [];
  const requests = [];
  const gets = [];
  const sessionUpdates = [];
  let sessionId = 'session-keep';
  let sidecarStatus = {
    lifecycle: 'ready',
    host: '127.0.0.1',
    port: 34891,
    canStart: true,
    detail: 'Sidecar ready.',
  };
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    {
      name: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      apiKeyRef: 'trainer.default',
      model: 'demo-model',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: true,
        tools: false,
        jsonSchema: false,
        streaming: true,
      },
    },
    sidecarStatus,
  );

  return {
    extensionContext: {},
    outputChannel: { appendLine() {} },
    trainerWorkspace: {
      getRoot() {
        return 'F:\\trainer\\trainer-workspace';
      },
    },
    providerStore: {
      getConfig() {
        return undefined;
      },
      getApiKey() {
        return undefined;
      },
    },
    tests: {},
    workbench: {
      async syncState() {},
      async postMessage() {},
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      getManagedDataFolderSnapshot() {
        return {
          effectivePath: 'F:\\trainer\\managed-data-default',
          defaultPath: 'F:\\trainer\\managed-data-default',
          source: 'recommended',
          status: 'ready',
        };
      },
      async configureManagedDataFolder(targetFolder) {
        return {
          changed: true,
          previousPath: 'F:\\trainer\\managed-data-default',
          next: {
            configuredPath: targetFolder,
            effectivePath: targetFolder,
            defaultPath: 'F:\\trainer\\managed-data-default',
            source: 'custom',
            status: 'ready',
          },
          migration: 'copied',
        };
      },
      async resetManagedDataFolder() {
        return {
          changed: true,
          previousPath: selectedFolder,
          next: {
            effectivePath: 'F:\\trainer\\managed-data-default',
            defaultPath: 'F:\\trainer\\managed-data-default',
            source: 'recommended',
            status: 'ready',
          },
          migration: 'not_needed',
        };
      },
      async restart() {
        sidecarStatus = {
          lifecycle: 'ready',
          host: '127.0.0.1',
          port: 34891,
          canStart: true,
          detail: 'Sidecar ready.',
        };
        return sidecarStatus;
      },
      getStatus() {
        return sidecarStatus;
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        requests.push({ port, requestPath, body });
        if (requestPath === '/session/start') {
          return {
            session_id: 'session-restarted',
            memory: {
              recent_summary: 'Managed folder switched and recovered.',
            },
          };
        }
        throw new Error(`Unexpected request path: ${requestPath}`);
      },
      async getJson(port, requestPath) {
        gets.push({ port, requestPath });
        if (requestPath.startsWith('/resource/trash?')) {
          return {
            workspace_id: 'F:\\trainer\\workspace-a',
            items: [],
          };
        }
        return {
          memory: {
            recent_summary: 'Managed folder switched and recovered.',
          },
        };
      },
    },
    getHostState() {
      return {
        bootstrap,
        workspace: {
          trusted: true,
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
        sessionId,
      };
    },
    getSessionId() {
      return sessionId;
    },
    async setSessionId(nextSessionId) {
      sessionId = nextSessionId;
      sessionUpdates.push(nextSessionId);
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    __patches: patches,
    __requests: requests,
    __gets: gets,
    __sessionUpdates: sessionUpdates,
  };
}

test('deleteResourceCommand ignores the UI operation id when it removes the bootstrap record', async () => {
  const vscodeMock = {};
  const { deleteResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await deleteResourceCommand(context, {
    resourceId: 'resource-1',
    __trainerResourceOperationId: 'resource-operation-test-1',
  });

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /sandbox trash updated/i);
  assert.match(result.message ?? '', /checkpoint-42/i);
  assert.match(result.message ?? '', /ledger-99/i);
  assert.match(result.message ?? '', /patch step/i);
  assert.deepEqual(result.data, {
    removed: true,
    detail: 'Resource removed from workspace and sandbox trash updated.',
    checkpoint_id: 'checkpoint-42',
    ledger_entry_id: 'ledger-99',
    patch: ['trash F:\\trainer\\notes.md -> F:\\trainer\\workspace-a\\.trainer\\trash\\notes.md'],
    diff_summary: 'Moved resource into sandbox trash',
  });
  assert.equal(context.__requests.length, 1);
  assert.deepEqual(context.__requests[0], {
    port: 34891,
    requestPath: '/resource/delete',
    body: {
      session_id: 'session-1',
      workspace_id: 'F:\\trainer\\workspace-a',
      resource_id: 'resource-1',
    },
  });
  assert.deepEqual(context.__gets, [
    {
      port: 34891,
      requestPath: '/memory/summary?workspace_id=F%3A%5Ctrainer%5Cworkspace-a&session_id=session-1',
    },
    {
      port: 34891,
      requestPath: '/resource/trash?workspace_id=F%3A%5Ctrainer%5Cworkspace-a&session_id=session-1',
    },
  ]);
  assert.equal(context.__patches.length, 1);
  assert.deepEqual(
    context.__patches[0].resources.map((item) => item.id),
    ['resource-2'],
  );
  assert.equal(context.__patches[0].resourceSearch, undefined);
  assert.equal(context.__patches[0].memory.selectedResourceDetail, undefined);
  assert.equal(
    context.__patches[0].memory.currentFocus,
    'Workspace authority refreshed after delete.',
  );
  assert.deepEqual(context.__patches[0].deletedResources, [
    {
      resourceId: 'resource-1',
      title: 'Notes',
      collectionPath: 'knowledge/Docs/notes.md',
      deletedAt: '2026-06-10T08:00:00Z',
      recoverable: true,
    },
  ]);
});

test('refreshResourceTrashCommand preserves the last known Trash when a matching response is malformed', async () => {
  const vscodeMock = {};
  const { refreshResourceTrashCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  const lastKnownDeletedResources = [
    {
      resourceId: 'resource-last-known',
      title: 'Last known Trash item',
      recoverable: true,
    },
  ];
  context.getHostState().bootstrap.deletedResources = lastKnownDeletedResources;
  context.sidecarClient.getJson = async (port, requestPath) => {
    context.__gets.push({ port, requestPath });
    return {
      workspace_id: 'F:\\trainer\\workspace-a',
      items: [
        {
          resource_id: 'resource-1',
          title: 'Notes',
          collection_path: 'knowledge/Docs/notes.md',
          collection_root: null,
          deleted_at: '2026-06-10T08:00:00Z',
          recoverable: true,
        },
        {
          resourceId: 'resource-1',
          title: 'Duplicate Notes',
          deletedAt: '2026-06-10T08:01:00Z',
          recoverable: false,
        },
        {
          resource_id: 'missing-title',
          recoverable: true,
        },
      ],
    };
  };

  const result = await refreshResourceTrashCommand(context);

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /Could not refresh the resource Trash/i);
  assert.deepEqual(context.__gets, [
    {
      port: 34891,
      requestPath: '/resource/trash?workspace_id=F%3A%5Ctrainer%5Cworkspace-a&session_id=session-1',
    },
  ]);
  assert.deepEqual(context.__patches, []);
  assert.deepEqual(context.getHostState().bootstrap.deletedResources, lastKnownDeletedResources);
});

test('refreshResourceTrashCommand rejects bare and unscoped Trash responses', async () => {
  const vscodeMock = {};
  const { refreshResourceTrashCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  const responses = [[], { items: [] }];
  context.sidecarClient.getJson = async () => responses.shift();

  const bareArrayResult = await refreshResourceTrashCommand(context);
  const unscopedResult = await refreshResourceTrashCommand(context);

  assert.equal(bareArrayResult.ok, false);
  assert.equal(unscopedResult.ok, false);
  assert.deepEqual(context.__patches, []);
});

test('refreshResourceTrashCommand does not start the sidecar for an untrusted workspace', async () => {
  const { refreshResourceTrashCommand } = loadWithVscodeMock(resourceCommandsModulePath, {});
  const context = createContext();
  const lastKnownDeletedResources = [
    { resourceId: 'resource-last-known', title: 'Last known Trash item', recoverable: true },
  ];
  context.getHostState().bootstrap.deletedResources = lastKnownDeletedResources;
  context.trustGuard.ensureTrusted = async () => false;

  const result = await refreshResourceTrashCommand(context);

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /Trust this workspace before refreshing the Trash/i);
  assert.equal(context.__ensureRunningCalls, 0);
  assert.equal(context.__gets.length, 0);
  assert.deepEqual(context.__patches, []);
  assert.deepEqual(context.getHostState().bootstrap.deletedResources, lastKnownDeletedResources);
});

test('refreshResourceTrashCommand does not start the sidecar for a browse-only project', async () => {
  const { refreshResourceTrashCommand } = loadWithVscodeMock(resourceCommandsModulePath, {});
  const context = createContext();
  const lastKnownDeletedResources = [
    { resourceId: 'resource-last-known', title: 'Last known Trash item', recoverable: true },
  ];
  context.getHostState().bootstrap.deletedResources = lastKnownDeletedResources;
  context.getHostState().bootstrap.memory.workspace = {
    ...(context.getHostState().bootstrap.memory.workspace ?? {}),
    trainerWorkspace: {
      ...(context.getHostState().bootstrap.memory.workspace?.trainerWorkspace ?? {}),
      status: 'browse',
    },
  };
  context.trustGuard.ensureTrusted = async () => {
    throw new Error('Trust should not be checked when project admission is blocked.');
  };

  const result = await refreshResourceTrashCommand(context);

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /browse-only/i);
  assert.equal(context.__trustCalls, 0);
  assert.equal(context.__ensureRunningCalls, 0);
  assert.equal(context.__gets.length, 0);
  assert.deepEqual(context.__patches, []);
  assert.deepEqual(context.getHostState().bootstrap.deletedResources, lastKnownDeletedResources);
});

test('deleteResourceCommand reports an unconfirmed result when the Trash belongs to another workspace', async () => {
  const vscodeMock = {};
  const { deleteResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  const lastKnownDeletedResources = [
    { resourceId: 'resource-last-known', title: 'Last known Trash item', recoverable: true },
  ];
  context.getHostState().bootstrap.deletedResources = lastKnownDeletedResources;
  context.sidecarClient.getJson = async (port, requestPath) => {
    context.__gets.push({ port, requestPath });
    if (requestPath.startsWith('/resource/trash?')) {
      return { workspace_id: 'F:\\trainer\\workspace-stale', items: [] };
    }
    return { memory: { recent_summary: 'Summary refreshed.' } };
  };

  const result = await deleteResourceCommand(context, { resourceId: 'resource-1' });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /Trash state could not be confirmed/i);
  assert.equal(context.__patches.length, 1);
  assert.equal(
    Object.prototype.hasOwnProperty.call(context.__patches[0], 'deletedResources'),
    false,
  );
  assert.deepEqual(context.getHostState().bootstrap.deletedResources, lastKnownDeletedResources);
});

test('restoreResourceCommand reports an unconfirmed result when the Trash belongs to another workspace', async () => {
  const vscodeMock = {};
  const { restoreResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  const lastKnownDeletedResources = [
    { resourceId: 'resource-1', title: 'Notes', recoverable: true },
  ];
  context.getHostState().bootstrap.deletedResources = lastKnownDeletedResources;
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return {
      restored: true,
      resource: {
        id: body.resource_id,
        kind: 'markdown',
        name: 'Notes',
        source: 'F:\\trainer\\notes.md',
        parse_status: 'pending',
        index_status: 'pending',
      },
      sandbox_state: {
        root_path: 'F:\\trainer\\workspace-a',
        sandbox_root_path: 'F:\\trainer\\workspace-a\\.trainer\\resources\\workspace-a',
        ready: true,
        linked_resource_count: 1,
        total_files: 1,
        total_directories: 1,
        nodes: [],
      },
    };
  };
  context.sidecarClient.getJson = async (port, requestPath) => {
    context.__gets.push({ port, requestPath });
    if (requestPath.startsWith('/resource/trash?')) {
      return { workspaceId: 'F:\\trainer\\workspace-stale', items: [] };
    }
    return { memory: { resources: context.getHostState().bootstrap.resources } };
  };

  const result = await restoreResourceCommand(context, { resourceId: 'resource-1' });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /Trash state could not be confirmed/i);
  assert.equal(context.__patches.length, 1);
  assert.equal(
    Object.prototype.hasOwnProperty.call(context.__patches[0], 'deletedResources'),
    false,
  );
  assert.deepEqual(context.getHostState().bootstrap.deletedResources, lastKnownDeletedResources);
});

test('deleteResourceCommand normalizes IDs before its local fallback when summary refresh fails', async () => {
  const vscodeMock = {};
  const { deleteResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient.getJson = async (port, requestPath) => {
    if (requestPath.startsWith('/resource/trash?')) {
      return {
        workspace_id: 'F:\\trainer\\workspace-a',
        items: [
          {
            resource_id: 'resource-1',
            title: 'Notes',
            recoverable: true,
          },
        ],
      };
    }
    throw new Error('Summary unavailable');
  };

  const result = await deleteResourceCommand(context, { resourceId: ' resource-1 ' });

  assert.equal(result.ok, true);
  assert.equal(result.data.summaryRefreshed, false);
  assert.deepEqual(context.__requests[0].body.resource_id, 'resource-1');
  assert.deepEqual(
    context.__patches[0].resources.map((item) => item.id),
    ['resource-2'],
  );
  assert.equal(context.__patches[0].resourceSearch, undefined);
});

test('deleteResourceCommand deletes a batch sequentially and keeps failed resources in the snapshot', async () => {
  const vscodeMock = {};
  const { deleteResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  let activeRequests = 0;
  let maxActiveRequests = 0;
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    activeRequests += 1;
    maxActiveRequests = Math.max(maxActiveRequests, activeRequests);
    await new Promise((resolve) => setImmediate(resolve));
    activeRequests -= 1;

    if (body.resource_id === 'resource-2') {
      throw new Error('Sidecar request failed (500): C:\\private\\trainer-resource-error');
    }
    return {
      removed: true,
      detail: 'Resource removed from workspace.',
    };
  };

  const result = await deleteResourceCommand(context, {
    resourceIds: [' resource-1 ', 'resource-2', 'resource-1', '   '],
  });

  assert.equal(result.ok, false);
  assert.equal(maxActiveRequests, 1);
  assert.match(result.message ?? '', /Deleted 1 resource\./i);
  assert.match(result.message ?? '', /1 resource could not be deleted\./i);
  assert.doesNotMatch(result.message ?? '', /private|500/i);
  assert.deepEqual(result.data, {
    requestedResourceIds: ['resource-1', 'resource-2'],
    deletedResourceIds: ['resource-1'],
    failedResourceIds: ['resource-2'],
    failures: [{ resourceId: 'resource-2', reason: 'request_failed' }],
    summaryRefreshed: true,
  });
  assert.deepEqual(
    context.__requests.map((request) => request.body.resource_id),
    ['resource-1', 'resource-2'],
  );
  assert.equal(context.__patches.length, 1);
  assert.deepEqual(
    context.__patches[0].resources.map((item) => item.id),
    ['resource-2'],
  );
  assert.equal(context.__patches[0].resourceSearch, undefined);
  assert.equal(context.__patches[0].memory.selectedResourceDetail, undefined);
});

test('deleteResourceCommand serializes overlapping deletes and does not revive an earlier resource', async () => {
  const vscodeMock = {};
  const { deleteResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  let bootstrap = context.getHostState().bootstrap;
  const serverDeletedIds = new Set();
  let markFirstDeleteStarted;
  let releaseFirstDelete;
  const firstDeleteStarted = new Promise((resolve) => {
    markFirstDeleteStarted = resolve;
  });
  const firstDeleteGate = new Promise((resolve) => {
    releaseFirstDelete = resolve;
  });

  context.getHostState = () => ({
    bootstrap,
    workspace: {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
  });
  context.patchWorkbenchData = async (patch) => {
    context.__patches.push(patch);
    bootstrap = {
      ...bootstrap,
      ...patch,
    };
  };
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    assert.equal(requestPath, '/resource/delete');
    if (body.resource_id === 'resource-1') {
      markFirstDeleteStarted();
      await firstDeleteGate;
    }
    serverDeletedIds.add(body.resource_id);
    return { removed: true, detail: 'Resource removed from workspace.' };
  };
  context.sidecarClient.getJson = async (port, requestPath) => {
    context.__gets.push({ port, requestPath });
    if (requestPath.startsWith('/resource/trash?')) {
      return {
        workspace_id: 'F:\\trainer\\workspace-a',
        items: [...serverDeletedIds].map((resourceId) => ({
          resource_id: resourceId,
          title: resourceId,
          recoverable: true,
        })),
      };
    }
    return {
      memory: {
        resources: bootstrap.resources.filter((resource) => !serverDeletedIds.has(resource.id)),
      },
    };
  };

  const firstDelete = deleteResourceCommand(context, { resourceId: 'resource-1' });
  const secondDelete = deleteResourceCommand(context, { resourceId: 'resource-2' });

  await firstDeleteStarted;
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(
    context.__requests.map((request) => request.body.resource_id),
    ['resource-1'],
  );

  releaseFirstDelete();
  const [firstResult, secondResult] = await Promise.all([firstDelete, secondDelete]);

  assert.equal(firstResult.ok, true);
  assert.equal(secondResult.ok, true);
  assert.deepEqual(
    context.__requests.map((request) => request.body.resource_id),
    ['resource-1', 'resource-2'],
  );
  assert.deepEqual(bootstrap.resources.map((resource) => resource.id), []);
  assert.equal(context.__patches.length, 2);
});

test('restoreSandboxPathCommand uses the governed sandbox restore route and patches sandbox state', async () => {
  const vscodeMock = {};
  const { restoreSandboxPathCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await restoreSandboxPathCommand(context, {
    path: 'F:\\trainer\\workspace-a\\.trainer\\trash\\20260610T080000-12345678\\notes.md',
  });

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /restored from trash/i);
  assert.deepEqual(context.__requests[0], {
    port: 34891,
    requestPath: '/sandbox/restore',
    body: {
      session_id: 'session-1',
      workspace_id: 'F:\\trainer\\workspace-a',
      path: 'F:\\trainer\\workspace-a\\.trainer\\trash\\20260610T080000-12345678\\notes.md',
      explicit_destructive_policy: false,
      remote_name: '',
      workspace_trusted: false,
    },
  });
  assert.equal(context.__patches.length, 1);
  assert.equal(context.__patches[0].memory.sandboxState.authority.permissionLevel, 'DESTRUCTIVE');
  assert.equal(context.__patches[0].memory.sandboxState.authority.checkpointCount, 2);
});

test('restoreResourceCommand restores a deleted record and refreshes governed workbench state', async () => {
  const vscodeMock = {};
  const { restoreResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    assert.equal(requestPath, '/resource/restore');
    return {
      restored: true,
      reindex_required: true,
      resource: {
        id: body.resource_id,
        kind: 'markdown',
        name: 'Notes',
        source: 'F:\\trainer\\notes.md',
        parse_status: 'pending',
        index_status: 'pending',
        collection_path: 'knowledge/Docs/notes.md',
        collection_root: 'F:\\trainer\\knowledge',
        sandbox_path: 'F:\\trainer\\sandboxes\\workspace-a\\notes.md',
      },
      sandbox_state: {
        root_path: 'F:\\trainer\\workspace-a',
        sandbox_root_path: 'F:\\trainer\\workspace-a\\.trainer\\resources\\workspace-a',
        ready: true,
        linked_resource_count: 1,
        total_files: 1,
        total_directories: 1,
        nodes: [],
      },
    };
  };
  context.sidecarClient.getJson = async (port, requestPath) => {
    context.__gets.push({ port, requestPath });
    if (requestPath.startsWith('/resource/trash?')) {
      return { workspace_id: 'F:\\trainer\\workspace-a', items: [] };
    }
    return {
      memory: {
        resources: context.getHostState().bootstrap.resources,
      },
    };
  };

  const result = await restoreResourceCommand(context, { resourceIds: [' resource-1 ', 'resource-1'] });

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /Restored 1 resource\. Re-index before reuse\./);
  assert.deepEqual(context.__requests, [
    {
      port: 34891,
      requestPath: '/resource/restore',
      body: {
        session_id: 'session-1',
        workspace_id: 'F:\\trainer\\workspace-a',
        resource_id: 'resource-1',
      },
    },
  ]);
  assert.equal(context.__patches.length, 1);
  assert.equal(context.__patches[0].resourceSearch, undefined);
  assert.equal(context.__patches[0].memory.sandboxState.ready, true);
  const restored = context.__patches[0].resources.find((resource) => resource.id === 'resource-1');
  assert.equal(restored.status, 'indexing');
  assert.equal(restored.collectionPath, 'knowledge/Docs/notes.md');
  assert.equal(restored.collectionRoot, 'F:\\trainer\\knowledge');
  assert.deepEqual(context.__patches[0].deletedResources, []);
});

test('searchResourcesCommand uses the managed workspace context for sidecar state', async () => {
  const vscodeMock = {};
  const { searchResourcesCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  const managedContextId = 'context-resource-123';
  context.getHostState().bootstrap.memory.workspace = {
    ...(context.getHostState().bootstrap.memory.workspace ?? {}),
    trainerWorkspace: {
      status: 'managed',
      contextId: managedContextId,
      canonicalProjectPath: 'f:\\trainer\\workspace-a',
      rootId: 'root-resource',
      projectId: 'project-resource',
    },
  };
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return {
      workspace_id: managedContextId,
      query: body.query,
      total: 0,
      results: [],
    };
  };

  const result = await searchResourcesCommand(context, { query: 'notes' });

  assert.equal(result.ok, true);
  assert.equal(context.__requests.length, 1);
  assert.equal(context.__requests[0].requestPath, '/resource/search');
  assert.equal(context.__requests[0].body.workspace_id, managedContextId);
});

test('searchResourcesCommand includes top-hit evidence in the summary message', async () => {
  const vscodeMock = {};
  const { searchResourcesCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return {
      workspace_id: 'F:\\trainer\\workspace-a',
      query: 'notes',
      total: 2,
      ranking_strategy: 'lexical_first',
      filters: {},
      results: [
        {
          id: 'resource-1',
          title: 'Notes',
          source: 'F:\\trainer\\notes.md',
          project_scope: 'workspace-a',
          trust_state: 'trusted',
          trust_score: 0.9,
          freshness: 'fresh',
          preview_tier: 'converted',
          preview_kind: 'document',
          citation_id: 'citation:resource-1',
          rank_score: 1.23,
          match_summary: 'matched title and freshness signals',
          can_inject_training_card: true,
          rank_reasons: ['title match', 'freshness fresh'],
        },
        {
          id: 'resource-2',
          title: 'Other note',
          project_scope: 'workspace-a',
          trust_state: 'trusted',
          trust_score: 0.8,
          freshness: 'fresh',
          citation_id: 'citation:resource-2',
          rank_reasons: ['body match'],
        },
      ],
    };
  };

  const result = await searchResourcesCommand(context, {
    query: 'notes',
    topK: 5,
    requestId: 'resource-search-notes-1',
  });

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /Found 2 ranked resources/i);
  assert.match(result.message ?? '', /Top hit: Notes/i);
  assert.match(result.message ?? '', /source F:\\trainer\\notes.md/i);
  assert.match(result.message ?? '', /project workspace-a/i);
  assert.match(result.message ?? '', /trust trusted 90%/i);
  assert.match(result.message ?? '', /preview Tier B · Document/i);
  assert.match(result.message ?? '', /citation citation:resource-1/i);
  assert.match(result.message ?? '', /rank 1\.23/i);
  assert.match(result.message ?? '', /injectable training card/i);
  assert.match(result.message ?? '', /match summary: matched title and freshness signals/i);
  assert.match(result.message ?? '', /reasons: title match, freshness fresh/i);
  assert.equal(context.__patches.length, 1);
  assert.equal(context.__patches[0].resourceSearch.requestId, 'resource-search-notes-1');
  assert.equal(context.__patches[0].resourceSearch.total, 2);
  assert.equal(context.__patches[0].resourceSearch.hits[0].citationId, 'citation:resource-1');
  assert.equal(result.data.requestId, 'resource-search-notes-1');
});

test('searchResourcesCommand ignores legacy rerank flags and keeps real filters', async () => {
  const vscodeMock = {};
  const { searchResourcesCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return {
      workspace_id: 'F:\\trainer\\workspace-a',
      query: 'coach reply',
      total: 1,
      ranking_strategy: 'lexical_first+semantic_rerank+provider_rerank',
      filters: {
        project_scope: 'workspace-a',
        trust_state: 'trusted',
        file_type: 'markdown',
        source_type: 'local:markdown',
        kind: 'markdown',
        index_state: 'indexed',
      },
      hits: [
        {
          id: 'resource-1',
          title: 'Notes',
          source: 'F:\\trainer\\notes.md',
          project_scope: 'workspace-a',
          trust_state: 'trusted',
          trust_score: 0.9,
          freshness: 'fresh',
          citation_id: 'citation:resource-1',
          rank_reasons: ['title match', 'provider rerank applied'],
          match_summary: 'provider rerank kept this at the top',
          can_inject_training_card: true,
        },
      ],
    };
  };

  const result = await searchResourcesCommand(context, {
    query: 'coach reply',
    topK: 7,
    mode: 'coach',
    semanticRerank: true,
    providerRerank: true,
    projectScope: 'workspace-a',
    trustState: 'trusted',
    fileType: 'markdown',
    sourceType: 'local:markdown',
    kind: 'markdown',
    indexState: 'indexed',
  });

  assert.equal(result.ok, true);
  assert.deepEqual(context.__requests[0], {
    port: 34891,
    requestPath: '/resource/search',
    body: {
      session_id: 'session-1',
      workspace_id: 'F:\\trainer\\workspace-a',
      query: 'coach reply',
      top_k: 7,
      project_scope: 'workspace-a',
      trust_state: 'trusted',
      file_type: 'markdown',
      source_type: 'local:markdown',
      kind: 'markdown',
      index_state: 'indexed',
    },
  });
  assert.equal(context.__patches[0].resourceSearch.rankingStrategy, 'lexical_first');
  assert.equal(context.__patches[0].resourceSearch.filters.file_type, 'markdown');
  assert.equal(context.__patches[0].resourceSearch.filters.trust_state, 'trusted');
});

test('searchResourcesCommand applies the trusted mode as indexed and trusted FTS filters', async () => {
  const vscodeMock = {};
  const { searchResourcesCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return {
      workspace_id: 'F:\\trainer\\workspace-a',
      query: 'notes',
      total: 0,
      ranking_strategy: 'lexical_first',
      filters: { trust_state: 'trusted', index_state: 'indexed' },
      hits: [],
    };
  };

  const result = await searchResourcesCommand(context, {
    query: 'notes',
    mode: 'trusted',
  });

  assert.equal(result.ok, true);
  assert.deepEqual(context.__requests[0].body, {
    session_id: 'session-1',
    workspace_id: 'F:\\trainer\\workspace-a',
    query: 'notes',
    trust_state: 'trusted',
    index_state: 'indexed',
  });
  assert.deepEqual(context.__patches[0].resourceSearch.filters, {
    trust_state: 'trusted',
    index_state: 'indexed',
  });
});

test('searchResourcesCommand does not let an older response replace the newest search', async () => {
  const vscodeMock = {};
  const { searchResourcesCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  let resolveFirst;
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    const responseFor = (query, resourceId) => ({
      workspace_id: 'F:\\trainer\\workspace-a',
      query,
      total: 1,
      ranking_strategy: 'lexical_first',
      filters: {},
      hits: [{ id: resourceId, title: query }],
    });
    if (body.query === 'first') {
      return new Promise((resolve) => {
        resolveFirst = () => resolve(responseFor('first', 'resource-1'));
      });
    }
    return responseFor('second', 'resource-2');
  };

  const first = searchResourcesCommand(context, {
    query: 'first',
    requestId: 'resource-search-first-1',
  });
  await Promise.resolve();
  const second = await searchResourcesCommand(context, {
    query: 'second',
    requestId: 'resource-search-second-1',
  });
  resolveFirst();
  const firstResult = await first;

  assert.equal(second.ok, true);
  assert.equal(firstResult.ok, true);
  assert.equal(context.__patches.length, 1);
  assert.equal(context.__patches[0].resourceSearch.query, 'second');
  assert.equal(context.__patches[0].resourceSearch.requestId, 'resource-search-second-1');
});

test('uploadResourceCommand exposes epub and eml in the file picker filters', async () => {
  const vscodeMock = {
    window: {
      showOpenDialog: async (options) => {
        vscodeMock.__openDialogOptions = options;
        return undefined;
      },
    },
  };
  const { uploadResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await uploadResourceCommand(context, { mode: 'files' });

  assert.equal(result.ok, false);
  assert.equal(result.cancelled, true);
  assert.equal(result.message, undefined);
  assert.ok(vscodeMock.__openDialogOptions);
  assert.ok(vscodeMock.__openDialogOptions.filters);
  assert.ok(vscodeMock.__openDialogOptions.filters.Resources.includes('docx'));
  assert.ok(vscodeMock.__openDialogOptions.filters.Resources.includes('xlsx'));
  assert.ok(vscodeMock.__openDialogOptions.filters.Resources.includes('epub'));
  assert.ok(vscodeMock.__openDialogOptions.filters.Resources.includes('eml'));
  assert.ok(vscodeMock.__openDialogOptions.filters.Resources.includes('zip'));
  assert.ok(vscodeMock.__openDialogOptions.filters.Resources.includes('mp3'));
  assert.ok(vscodeMock.__openDialogOptions.filters.Resources.includes('mp4'));
});

test('uploadResourceCommand treats cancelling every picker as a quiet cancellation', async () => {
  const vscodeMock = {
    window: {
      showOpenDialog: async () => undefined,
      showInputBox: async () => undefined,
      showQuickPick: async () => undefined,
    },
  };
  const { uploadResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();

  for (const payload of [undefined, { mode: 'folder' }, { mode: 'url' }]) {
    const result = await uploadResourceCommand(context, payload);
    assert.equal(result.ok, false);
    assert.equal(result.cancelled, true);
    assert.equal(result.message, undefined);
  }
});

test('uploadResourceCommand accepts inline uploads without opening picker UI', async () => {
  const vscodeMock = {
    window: {
      showQuickPick: async () => {
        throw new Error('showQuickPick should not run for inline uploads');
      },
      showOpenDialog: async () => {
        throw new Error('showOpenDialog should not run for inline uploads');
      },
    },
  };
  const { uploadResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    if (requestPath === '/resource/upload') {
      return {
        id: 'resource-inline-1',
        title: 'inline-proof.md',
        kind: 'markdown',
        status: 'indexing',
        summary: 'Inline upload proof',
        source: 'C:\\temp\\inline-proof.md',
      };
    }
    if (requestPath === '/resource/index') {
      return {
        id: 'resource-inline-1',
        title: 'inline-proof.md',
        kind: 'markdown',
        status: 'ready',
        summary: 'Inline upload proof',
        source: 'C:\\temp\\inline-proof.md',
      };
    }
    throw new Error(`Unexpected request path: ${requestPath}`);
  };
  context.sidecarClient.getJson = async (port, requestPath) => {
    context.__gets.push({ port, requestPath });
    return {
      memory: {
        recent_summary: 'Inline upload indexed and available.',
      },
    };
  };

  const result = await uploadResourceCommand(context, {
    mode: 'files',
    uploads: [
      {
        name: 'inline-proof.md',
        kind: 'markdown',
        source: 'inline://trainer/inline-proof.md',
        content: '# Inline proof\nTrainer should ingest this without a picker.\n',
        contentEncoding: 'utf-8',
        tags: ['vsix-e2e', 'inline'],
      },
    ],
  });

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /Imported 1 resource\(s\) and indexed 1\./i);
  assert.deepEqual(context.__requests, [
    {
      port: 34891,
      requestPath: '/resource/upload',
      body: {
        session_id: 'session-1',
        workspace_id: 'F:\\trainer\\workspace-a',
        kind: 'markdown',
        name: 'inline-proof.md',
        source: 'inline://trainer/inline-proof.md',
        content: '# Inline proof\nTrainer should ingest this without a picker.\n',
        content_encoding: 'utf-8',
        tags: ['vsix-e2e', 'inline'],
        source_type: 'file',
        source_items: [],
      },
    },
    {
      port: 34891,
      requestPath: '/resource/index',
      body: {
        session_id: 'session-1',
        workspace_id: 'F:\\trainer\\workspace-a',
        resource_id: 'resource-inline-1',
        enable_network: false,
      },
    },
  ]);
  assert.equal(context.__gets.length, 1);
  assert.match(context.__gets[0].requestPath, /\/memory\/summary\?/);
  assert.equal(Array.isArray(result.data), true);
  assert.equal(result.data[0].status, 'ready');
});

test('uploadResourceCommand preserves earlier files when a later upload fails', async () => {
  const vscodeMock = {
    window: {
      showOpenDialog: async () => [
        { fsPath: 'C:\\trainer\\first.md' },
        { fsPath: 'C:\\private\\second.md' },
      ],
    },
  };
  const { uploadResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.getHostState().bootstrap.memory.workspace.responseLanguage = 'zh-CN';
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    if (requestPath === '/resource/upload' && body.name === 'first.md') {
      return {
        id: 'resource-first',
        title: 'first.md',
        kind: 'markdown',
        status: 'indexing',
        summary: 'First resource uploaded.',
        source: 'C:\\trainer\\first.md',
      };
    }
    if (requestPath === '/resource/upload' && body.name === 'second.md') {
      throw new Error('Sidecar request failed (500): C:\\private\\trainer-resource-error');
    }
    if (requestPath === '/resource/index' && body.resource_id === 'resource-first') {
      return {
        id: 'resource-first',
        title: 'first.md',
        kind: 'markdown',
        status: 'ready',
        summary: 'First resource indexed.',
        source: 'C:\\trainer\\first.md',
      };
    }
    throw new Error(`Unexpected request path: ${requestPath}`);
  };
  context.sidecarClient.getJson = async (port, requestPath) => {
    context.__gets.push({ port, requestPath });
    return { memory: { recent_summary: 'One resource is ready to use.' } };
  };

  const result = await uploadResourceCommand(context, { mode: 'files' });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /已导入 1 项资料，已完成 1 项索引/);
  assert.match(result.message ?? '', /另有 1 个文件没能添加。你可以先使用已导入的资料，稍后再试。/);
  assert.doesNotMatch(result.message ?? '', /private|500|trainer-resource-error/i);
  assert.deepEqual(
    context.__requests.map((request) => [request.requestPath, request.body.name ?? request.body.resource_id]),
    [
      ['/resource/upload', 'first.md'],
      ['/resource/upload', 'second.md'],
      ['/resource/index', 'resource-first'],
    ],
  );
  assert.ok(
    context.__patches.some((patch) =>
      patch.resources?.some((resource) => resource.id === 'resource-first' && resource.status === 'indexing'),
    ),
  );
  assert.ok(
    context.__patches.some((patch) =>
      patch.resources?.some((resource) => resource.id === 'resource-first' && resource.status === 'ready'),
    ),
  );
  assert.equal(context.__gets.length, 1);
  assert.equal(Array.isArray(result.data), true);
  assert.equal(result.data[0].id, 'resource-first');
  assert.equal(result.data[0].status, 'ready');
});

test('openResourceCommand opens the managed local copy in VS Code', async () => {
  const executedCommands = [];
  const vscodeMock = {
    Uri: {
      file(value) {
        return { fsPath: value, path: value, scheme: 'file' };
      },
    },
    commands: {
      async executeCommand(...args) {
        executedCommands.push(args);
      },
    },
  };
  const { openResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await openResourceCommand(context, { resourceId: 'resource-1' });

  assert.equal(result.ok, true);
  assert.deepEqual(executedCommands, [
    [
      'vscode.open',
      {
        fsPath: 'F:\\trainer\\sandboxes\\workspace-a\\notes.md',
        path: 'F:\\trainer\\sandboxes\\workspace-a\\notes.md',
        scheme: 'file',
      },
      { preview: false, preserveFocus: false },
    ],
  ]);
});

test('previewResourceCommand requests governed content and patches the workbench preview', async () => {
  const executedCommands = [];
  const vscodeMock = {
    Uri: {
      file(value) {
        return { fsPath: value, path: value, scheme: 'file' };
      },
    },
    commands: {
      async executeCommand(...args) {
        executedCommands.push(args);
      },
    },
  };
  const { previewResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.getHostState().bootstrap.memory.sandboxState = {
    sandboxRootPath: 'F:\\trainer\\sandboxes\\workspace-a',
  };
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return {
      path: body.path,
      title: 'Notes',
      preview_kind: 'markdown',
      preview_tier: 'rich',
      content: '# Preview content',
      can_native_open: true,
    };
  };
  const result = await previewResourceCommand(context, { resourceId: 'resource-1' });

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /Previewed Notes/i);
  assert.equal(result.data.content, '# Preview content');
  assert.deepEqual(context.__requests[0], {
    port: 34891,
    requestPath: '/sandbox/preview',
    body: {
      session_id: 'session-1',
      workspace_id: 'F:\\trainer\\workspace-a',
      path: 'F:\\trainer\\sandboxes\\workspace-a\\notes.md',
    },
  });
  assert.equal(context.__patches[0].memory.sandboxPreview.content, '# Preview content');
  assert.deepEqual(executedCommands, []);
});

test('previewResourceCommand attaches conversation file_preview for live docx document preview', async () => {
  const { previewResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, {
    Uri: {
      file(value) {
        return { fsPath: value, path: value, scheme: 'file' };
      },
    },
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  });
  const context = createContext();
  const sandboxPath = 'F:\\trainer\\sandboxes\\workspace-a\\coach-notes.docx';
  context.getHostState().bootstrap.resources = [
    {
      id: 'resource-docx',
      title: 'Coach notes',
      kind: 'document',
      status: 'ready',
      summary: 'Docx notes',
      source: 'F:\\trainer\\coach-notes.docx',
      sandboxPath,
    },
  ];
  context.getHostState().bootstrap.memory.sandboxState = {
    sandboxRootPath: 'F:\\trainer\\sandboxes\\workspace-a',
  };
  context.getHostState().bootstrap.conversation = [
    {
      id: 'user-preview',
      role: 'user',
      author: 'you',
      body: 'preview the docx',
      timestamp: '2026-08-27T09:00:00Z',
    },
  ];
  context.workbench.resolveWebviewUriForPath = (filePath) =>
    filePath === sandboxPath ? `vscode-webview-resource://trainer/${sandboxPath}` : undefined;
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return {
      path: body.path,
      title: 'Coach notes',
      preview_kind: 'document',
      preview_tier: 'converted',
      can_native_open: true,
    };
  };

  const result = await previewResourceCommand(context, { resourceId: 'resource-docx' });

  assert.equal(result.ok, true);
  const patch = context.__patches[0];
  assert.equal(patch.memory.sandboxPreview.previewKind, 'document');
  assert.equal(
    patch.memory.sandboxPreview.assetUri,
    `vscode-webview-resource://trainer/${sandboxPath}`,
  );
  const hostPreview = patch.conversation.find((message) => message.id === 'host-file-preview-docx');
  assert.ok(hostPreview);
  assert.equal(hostPreview.parts[0].type, 'file_preview');
  assert.equal(hostPreview.parts[0].previewKind, 'document');
  assert.equal(hostPreview.parts[0].path, sandboxPath);
  assert.equal(
    hostPreview.parts[0].assetUri,
    `vscode-webview-resource://trainer/${sandboxPath}`,
  );
  assert.equal(hostPreview.parts[0].resourceId, 'resource-docx');
});

test('previewResourceCommand previews an explicit sandbox path without native opening', async () => {
  const executedCommands = [];
  const vscodeMock = {
    Uri: {
      file(value) {
        return { fsPath: value, path: value, scheme: 'file' };
      },
    },
    commands: {
      async executeCommand(...args) {
        executedCommands.push(args);
      },
    },
  };
  const { previewResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  const sandboxPath = 'F:\\trainer\\sandboxes\\workspace-a\\scratch.md';
  context.getHostState().bootstrap.memory.sandboxState = {
    sandboxRootPath: 'F:\\trainer\\sandboxes\\workspace-a',
  };

  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return { path: body.path, preview_kind: 'text', content: 'scratch preview' };
  };
  const result = await previewResourceCommand(context, { path: sandboxPath });

  assert.equal(result.ok, true);
  assert.equal(result.data.path, sandboxPath);
  assert.equal(result.data.content, 'scratch preview');
  assert.equal(context.__requests[0].requestPath, '/sandbox/preview');
  assert.equal(context.__patches[0].memory.sandboxPreview.content, 'scratch preview');
  assert.deepEqual(executedCommands, []);
});

test('previewResourceCommand rejects an explicit path outside the governed sandbox', async () => {
  const vscodeMock = {
    Uri: {
      file(value) {
        return { fsPath: value, path: value, scheme: 'file' };
      },
    },
    commands: {
      async executeCommand() {
        throw new Error('vscode.open should not run outside the sandbox');
      },
    },
  };
  const { previewResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.getHostState().bootstrap.memory.sandboxState = {
    sandboxRootPath: 'F:\\trainer\\sandboxes\\workspace-a',
  };

  const result = await previewResourceCommand(context, {
    path: 'F:\\trainer\\workspace-a\\outside.md',
  });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /outside the governed Trainer sandbox/i);
  assert.deepEqual(context.__requests, []);
  assert.deepEqual(context.__patches, []);
});

test('previewResourceCommand does not open an explicit path without workspace trust', async () => {
  const vscodeMock = {
    Uri: {
      file(value) {
        return { fsPath: value, path: value, scheme: 'file' };
      },
    },
    commands: {
      async executeCommand() {
        throw new Error('vscode.open should not run without trust');
      },
    },
  };
  const { previewResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.trustGuard.ensureTrusted = async () => false;

  const result = await previewResourceCommand(context, {
    path: 'F:\\trainer\\sandboxes\\workspace-a\\scratch.md',
  });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /Workspace trust/i);
  assert.deepEqual(context.__requests, []);
  assert.deepEqual(context.__patches, []);
});

test('createSandboxDirectoryCommand creates nested folders and patches sandbox state', async () => {
  const vscodeMock = {};
  const { createSandboxDirectoryCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return {
      workspace_id: 'F:\\trainer\\workspace-a',
      root_path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a',
      sandbox_root_path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a',
      workspace_root_path: 'F:\\trainer\\workspace-a',
      active_workspace_root: 'F:\\trainer\\workspace-a',
      trash_root_path: 'F:\\trainer\\workspace-a\\.trainer\\trash',
      ready: true,
      total_files: 1,
      total_directories: 3,
      selected_path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\packs\\remote\\ssh',
      preview: {
        path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\packs\\remote\\ssh',
        relative_path: 'packs/remote/ssh',
        title: 'ssh',
        node_kind: 'directory',
        file_kind: 'directory',
        rendered_from: 'directory',
        content: '',
        excerpt: '',
        metadata: {
          child_count: 0,
        },
      },
      nodes: [],
    };
  };

  const result = await createSandboxDirectoryCommand(context, { path: 'packs/remote/ssh' });

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /Created sandbox folder/i);
  assert.deepEqual(context.__requests, [
    {
      port: 34891,
      requestPath: '/sandbox/mkdir',
      body: {
        workspace_id: 'F:\\trainer\\workspace-a',
        path: 'packs/remote/ssh',
        explicit_destructive_policy: false,
        remote_name: '',
        workspace_trusted: false,
      },
    },
  ]);
  assert.equal(
    context.__patches[0].memory.sandboxState.selectedPath,
    'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\packs\\remote\\ssh',
  );
  assert.equal(
    context.__patches[0].memory.sandboxPreview.path,
    'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\packs\\remote\\ssh',
  );
  assert.equal(context.__patches[0].memory.selectedResourceDetail, undefined);
});

test('createSandboxFileCommand creates a sandbox file and refreshes governed state', async () => {
  const vscodeMock = {};
  const { createSandboxFileCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return {
      path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\packs\\remote\\ssh\\notes.md',
      relative_path: 'packs/remote/ssh/notes.md',
      title: 'notes.md',
      node_kind: 'file',
      file_kind: 'markdown',
      preview_tier: 'rich',
      preview_kind: 'markdown',
      rendered_from: 'raw',
      content: '# Sandbox write proof',
      excerpt: '# Sandbox write proof',
      is_binary: false,
      is_editable: true,
      can_native_open: true,
      metadata: {},
    };
  };
  context.sidecarClient.getJson = async (port, requestPath) => {
    context.__gets.push({ port, requestPath });
    return {
      workspace_id: 'F:\\trainer\\workspace-a',
      root_path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a',
      sandbox_root_path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a',
      workspace_root_path: 'F:\\trainer\\workspace-a',
      active_workspace_root: 'F:\\trainer\\workspace-a',
      trash_root_path: 'F:\\trainer\\workspace-a\\.trainer\\trash',
      ready: true,
      total_files: 1,
      total_directories: 3,
      selected_path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\packs\\remote\\ssh\\notes.md',
      preview: {
        path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\packs\\remote\\ssh\\notes.md',
        relative_path: 'packs/remote/ssh/notes.md',
        title: 'notes.md',
        node_kind: 'file',
        file_kind: 'markdown',
        preview_tier: 'rich',
        preview_kind: 'markdown',
        rendered_from: 'raw',
        content: '# Sandbox write proof',
        excerpt: '# Sandbox write proof',
        metadata: {},
      },
      nodes: [],
    };
  };

  const result = await createSandboxFileCommand(context, { path: 'packs/remote/ssh/notes.md', content: '' });

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /Created sandbox file/i);
  assert.deepEqual(context.__requests, [
    {
      port: 34891,
      requestPath: '/sandbox/write',
      body: {
        workspace_id: 'F:\\trainer\\workspace-a',
        path: 'packs/remote/ssh/notes.md',
        content: '',
        create: true,
        explicit_destructive_policy: false,
        remote_name: '',
        workspace_trusted: false,
      },
    },
  ]);
  assert.deepEqual(context.__gets, [
    {
      port: 34891,
      requestPath:
        '/sandbox/state?workspace_id=F%3A%5Ctrainer%5Cworkspace-a&session_id=session-1&selected_path=F%3A%5Ctrainer%5Cworkspace-a%5C.trainer%5Csandboxes%5Cworkspace-a%5Cpacks%5Cremote%5Cssh%5Cnotes.md&preview_path=F%3A%5Ctrainer%5Cworkspace-a%5C.trainer%5Csandboxes%5Cworkspace-a%5Cpacks%5Cremote%5Cssh%5Cnotes.md&workspace_trusted=false&remote_name=',
    },
  ]);
  assert.equal(
    context.__patches[0].memory.sandboxState.selectedPath,
    'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\packs\\remote\\ssh\\notes.md',
  );
  assert.equal(context.__patches[0].memory.sandboxPreview.title, 'notes.md');
});

test('renameSandboxPathCommand renames a sandbox path and refreshes governed state', async () => {
  const vscodeMock = {};
  const { renameSandboxPathCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return {
      path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\packs\\debug\\minimal-loop.md',
      relative_path: 'packs/debug/minimal-loop.md',
      title: 'minimal-loop.md',
      node_kind: 'file',
      file_kind: 'markdown',
      preview_tier: 'rich',
      preview_kind: 'markdown',
      rendered_from: 'raw',
      content: 'renamed',
      excerpt: 'renamed',
      metadata: {},
    };
  };
  context.sidecarClient.getJson = async (port, requestPath) => {
    context.__gets.push({ port, requestPath });
    return {
      workspace_id: 'F:\\trainer\\workspace-a',
      root_path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a',
      sandbox_root_path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a',
      workspace_root_path: 'F:\\trainer\\workspace-a',
      active_workspace_root: 'F:\\trainer\\workspace-a',
      trash_root_path: 'F:\\trainer\\workspace-a\\.trainer\\trash',
      ready: true,
      total_files: 1,
      total_directories: 2,
      selected_path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\packs\\debug\\minimal-loop.md',
      preview: {
        path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\packs\\debug\\minimal-loop.md',
        relative_path: 'packs/debug/minimal-loop.md',
        title: 'minimal-loop.md',
        node_kind: 'file',
        file_kind: 'markdown',
        preview_tier: 'rich',
        preview_kind: 'markdown',
        rendered_from: 'raw',
        content: 'renamed',
        excerpt: 'renamed',
        metadata: {},
      },
      nodes: [],
    };
  };

  const result = await renameSandboxPathCommand(context, {
    path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\notes.md',
    newPath: 'packs/debug/minimal-loop.md',
  });

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /renamed/i);
  assert.deepEqual(context.__requests, [
    {
      port: 34891,
      requestPath: '/sandbox/rename',
      body: {
        workspace_id: 'F:\\trainer\\workspace-a',
        path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\notes.md',
        new_path: 'packs/debug/minimal-loop.md',
        explicit_destructive_policy: false,
        remote_name: '',
        workspace_trusted: false,
      },
    },
  ]);
  assert.match(context.__gets[0].requestPath, /\/sandbox\/state\?/);
  assert.equal(context.__patches[0].memory.sandboxPreview.title, 'minimal-loop.md');
});

test('deleteSandboxPathCommand moves a sandbox path to Trash and clears selected resource detail when needed', async () => {
  const vscodeMock = {};
  const { deleteSandboxPathCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return {
      workspace_id: 'F:\\trainer\\workspace-a',
      root_path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a',
      sandbox_root_path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a',
      workspace_root_path: 'F:\\trainer\\workspace-a',
      active_workspace_root: 'F:\\trainer\\workspace-a',
      trash_root_path: 'F:\\trainer\\workspace-a\\.trainer\\trash',
      ready: true,
      total_files: 0,
      total_directories: 1,
      selected_path: null,
      preview: null,
      nodes: [],
    };
  };

  const result = await deleteSandboxPathCommand(context, {
    path: 'F:\\trainer\\sandboxes\\workspace-a\\notes.md',
  });

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /Trash/i);
  assert.deepEqual(context.__requests, [
    {
      port: 34891,
      requestPath: '/sandbox/delete',
      body: {
        workspace_id: 'F:\\trainer\\workspace-a',
        path: 'F:\\trainer\\sandboxes\\workspace-a\\notes.md',
        explicit_destructive_policy: false,
        remote_name: '',
        workspace_trusted: false,
      },
    },
  ]);
  assert.equal(context.__patches[0].memory.selectedResourceDetail, undefined);
  assert.equal(
    context.__patches[0].memory.sandboxState.totalFiles ??
      context.__patches[0].memory.sandboxState.total_files,
    0,
  );
});

test('chooseSandboxRootCommand fixes the workspace sandbox root and refreshes governed memory state', async () => {
  const vscodeMock = {
    window: {
      showOpenDialog: async (options) => {
        vscodeMock.__openDialogOptions = options;
        return [{ fsPath: 'D:\\trainer-projects\\remote-ssh' }];
      },
    },
    Uri: {
      file(fsPath) {
        return { fsPath };
      },
    },
  };
  const { chooseSandboxRootCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.getHostState().bootstrap.memory.sandboxState = {
    sandboxRootPath: 'F:\\trainer\\workspace-a\\.trainer\\resources\\workspace-a',
    workspaceRootPath: 'F:\\trainer\\workspace-a',
  };
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return {
      root_path: 'D:\\trainer-projects\\remote-ssh',
      sandbox_root_path: 'D:\\trainer-projects\\remote-ssh',
      workspace_root_path: 'F:\\trainer\\workspace-a',
      active_workspace_root: 'F:\\trainer\\workspace-a',
      trash_root_path: 'D:\\trainer-projects\\remote-ssh\\.trainer-trash',
      selected_path: 'D:\\trainer-projects\\remote-ssh\\plan\\current-plan.md',
      preview: {
        path: 'D:\\trainer-projects\\remote-ssh\\plan\\current-plan.md',
        relative_path: 'plan/current-plan.md',
        title: 'current-plan.md',
        file_kind: 'markdown',
        preview_tier: 'rich',
        preview_kind: 'markdown',
        rendered_from: 'raw',
        content: '# Current plan',
        excerpt: '# Current plan',
        metadata: {},
      },
    };
  };

  const result = await chooseSandboxRootCommand(context);

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /Sandbox root fixed at remote-ssh/i);
  assert.equal(vscodeMock.__openDialogOptions.defaultUri.fsPath, 'F:\\trainer\\workspace-a\\.trainer\\resources\\workspace-a');
  assert.deepEqual(context.__requests, [
    {
      port: 34891,
      requestPath: '/sandbox/root',
      body: {
        session_id: 'session-1',
        workspace_id: 'F:\\trainer\\workspace-a',
        root_path: 'D:\\trainer-projects\\remote-ssh',
        clear: false,
        remote_name: '',
        workspace_trusted: false,
      },
    },
  ]);
  assert.deepEqual(context.__gets, [
    {
      port: 34891,
      requestPath: '/memory/summary?workspace_id=F%3A%5Ctrainer%5Cworkspace-a&session_id=session-1',
    },
  ]);
  assert.equal(context.__patches.length, 1);
  assert.equal(
    context.__patches[0].memory.sandboxState.sandboxRootPath ??
      context.__patches[0].memory.sandboxState.sandbox_root_path,
    'D:\\trainer-projects\\remote-ssh',
  );
  assert.equal(context.__patches[0].memory.sandboxPreview.title, 'current-plan.md');
});

test('resetSandboxRootCommand returns the workspace to the default Trainer sandbox root', async () => {
  const vscodeMock = {};
  const { resetSandboxRootCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    context.__requests.push({ port, requestPath, body });
    return {
      root_path: 'F:\\trainer\\workspace-a\\.trainer\\resources\\workspace-a',
      sandbox_root_path: 'F:\\trainer\\workspace-a\\.trainer\\resources\\workspace-a',
      workspace_root_path: 'F:\\trainer\\workspace-a',
      active_workspace_root: 'F:\\trainer\\workspace-a',
      trash_root_path: 'F:\\trainer\\workspace-a\\.trainer\\trash',
      selected_path: 'F:\\trainer\\workspace-a\\.trainer\\resources\\workspace-a\\notes\\handoff.md',
      preview: {
        path: 'F:\\trainer\\workspace-a\\.trainer\\resources\\workspace-a\\notes\\handoff.md',
        relative_path: 'notes/handoff.md',
        title: 'handoff.md',
        file_kind: 'markdown',
        preview_tier: 'rich',
        preview_kind: 'markdown',
        rendered_from: 'raw',
        content: '# Handoff',
        excerpt: '# Handoff',
        metadata: {},
      },
    };
  };

  const result = await resetSandboxRootCommand(context);

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /reset to the default Trainer workspace/i);
  assert.deepEqual(context.__requests, [
    {
      port: 34891,
      requestPath: '/sandbox/root',
      body: {
        session_id: 'session-1',
        workspace_id: 'F:\\trainer\\workspace-a',
        root_path: undefined,
        clear: true,
        remote_name: '',
        workspace_trusted: false,
      },
    },
  ]);
  assert.equal(
    context.__patches[0].memory.sandboxState.sandboxRootPath ??
      context.__patches[0].memory.sandboxState.sandbox_root_path,
    'F:\\trainer\\workspace-a\\.trainer\\resources\\workspace-a',
  );
  assert.equal(context.__patches[0].memory.sandboxPreview.title, 'handoff.md');
});

test('chooseManagedDataFolderCommand restarts the backend and reinitializes the session on the new folder', async () => {
  const vscodeMock = {
    window: {
      showOpenDialog: async () => [{ fsPath: 'D:\\trainer\\managed-data' }],
    },
    Uri: {
      file(fsPath) {
        return { fsPath };
      },
    },
    workspace: {
      name: 'workspace-a',
    },
  };
  const { chooseManagedDataFolderCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createManagedDataFolderContext('D:\\trainer\\managed-data');

  const result = await chooseManagedDataFolderCommand(context);

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /Managed data folder updated\./i);
  assert.match(result.message ?? '', /previous folder was left untouched/i);
  assert.deepEqual(context.__sessionUpdates, [undefined, 'session-restarted']);
  assert.deepEqual(context.__requests, [
    {
      port: 34891,
      requestPath: '/session/start',
      body: {
        workspace_id: 'F:\\trainer\\workspace-a',
        workspace_name: 'workspace-a',
        workspace_path: 'F:\\trainer\\workspace-a',
        remote_name: '',
        workspace_trusted: true,
      },
    },
  ]);
  assert.deepEqual(context.__gets, [
    {
      port: 34891,
      requestPath: '/memory/summary?workspace_id=F%3A%5Ctrainer%5Cworkspace-a',
    },
    {
      port: 34891,
      requestPath: '/resource/trash?workspace_id=F%3A%5Ctrainer%5Cworkspace-a',
    },
  ]);
});

function setResourceAdmission(context, status) {
  const bootstrap = context.getHostState().bootstrap;
  bootstrap.memory.workspace = {
    ...(bootstrap.memory.workspace ?? {}),
    trainerWorkspace: { status },
  };
  context.trainerWorkspace = {
    getRoot() {
      return 'F:\\trainer\\workspace-a';
    },
  };
}

test('browse and ignored admissions stop every resource mutation before it reaches local or sidecar state', async () => {
  const vscodeMock = {};
  const commands = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);

  for (const status of ['browse', 'ignored']) {
    const context = createContext();
    setResourceAdmission(context, status);
    context.getHostState().bootstrap.memory.workspace.responseLanguage = 'en-US';
    let trustChecks = 0;
    let sidecarStarts = 0;
    context.trustGuard.ensureTrusted = async () => {
      trustChecks += 1;
      return true;
    };
    context.sidecarManager.ensureRunning = async () => {
      sidecarStarts += 1;
      return { lifecycle: 'ready', port: 34891 };
    };

    const mutations = [
      () => commands.uploadResourceCommand(context, { mode: 'url' }),
      () => commands.indexResourcesCommand(context),
      () => commands.deleteResourceCommand(context, { resourceId: 'resource-1' }),
      () => commands.restoreResourceCommand(context, { resourceId: 'resource-1' }),
      () => commands.restoreSandboxPathCommand(context, { path: 'notes.md' }),
      () => commands.createSandboxDirectoryCommand(context, { path: 'notes' }),
      () => commands.createSandboxFileCommand(context, { path: 'notes.md', content: 'draft' }),
      () => commands.renameSandboxPathCommand(context, { path: 'notes.md', newPath: 'next.md' }),
      () => commands.deleteSandboxPathCommand(context, { path: 'notes.md' }),
      () => commands.deleteSandboxPathsCommand(context, { paths: ['notes.md'] }),
      () => commands.chooseSandboxRootCommand(context),
      () => commands.resetSandboxRootCommand(context),
      () => commands.chooseManagedDataFolderCommand(context),
      () => commands.resetManagedDataFolderCommand(context),
    ];

    for (const mutate of mutations) {
      const result = await mutate();
      assert.equal(result.ok, false, status);
      assert.match(
        result.message ?? '',
        status === 'browse'
          ? /browse-only.*search and open.*cannot add, index, or change/i
          : /ignored.*will not add or change resources/i,
      );
    }

    assert.equal(trustChecks, 0, status);
    assert.equal(sidecarStarts, 0, status);
    assert.deepEqual(context.__requests, [], status);
    assert.deepEqual(context.__patches, [], status);
  }
});

test('browse and ignored admissions keep resource search available as a read-only operation', async () => {
  const vscodeMock = {};
  const { searchResourcesCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);

  for (const status of ['browse', 'ignored']) {
    const context = createContext();
    setResourceAdmission(context, status);
    context.sidecarClient.postJson = async (port, requestPath, body) => {
      context.__requests.push({ port, requestPath, body });
      return {
        workspace_id: 'F:\\trainer\\workspace-a',
        query: body.query,
        total: 0,
        ranking_strategy: 'lexical_first',
        filters: {},
        results: [],
      };
    };

    const result = await searchResourcesCommand(context, { query: 'notes' });

    assert.equal(result.ok, true, status);
    assert.match(result.message ?? '', /Found 0 ranked resources/i);
    assert.deepEqual(context.__requests, [
      {
        port: 34891,
        requestPath: '/resource/search',
        body: {
          session_id: 'session-1',
          workspace_id: 'F:\\trainer\\workspace-a',
          query: 'notes',
        },
      },
    ]);
  }
});
