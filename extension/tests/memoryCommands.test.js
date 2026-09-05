'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const memoryCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'memoryCommands.js',
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
  const gets = [];
  const posts = [];
  const syncs = [];
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
  bootstrap.memory.sandboxState = {
    rootPath: 'F:\\trainer\\workspace-stale',
    activeWorkspaceRoot: 'F:\\trainer\\workspace-stale',
    workspaceRootPath: 'F:\\trainer\\workspace-stale',
    trashRootPath: 'F:\\trainer\\workspace-stale\\.trainer\\trash',
    nodes: [],
    totalSize: 0,
    lastModified: '',
    authority: {
      activeWorkspaceRoot: 'F:\\trainer\\workspace-stale',
      rootUri: 'F:\\trainer\\workspace-stale',
      authoritySource: 'stale_source',
      permissionLevel: 'INSPECT',
      permissionLabel: 'inspect only',
      authorityMode: 'level_inspect',
      allowedOperations: ['read'],
      ledgerEntryCount: 0,
      checkpointCount: 0,
      trashRoot: 'F:\\trainer\\workspace-stale\\.trainer\\trash',
    },
  };

  return {
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async getJson(port, requestPath) {
        gets.push({ port, requestPath });
        return {
          active_workspace_root: 'F:\\trainer\\workspace-a',
          root_uri: 'F:\\trainer\\workspace-a',
          remote_name: 'ssh-remote',
          is_remote_workspace: true,
          permission_level: 'DESTRUCTIVE',
          permission_label: 'delete/overwrite/batch move (via trash)',
          authority_mode: 'level_destructive',
          allowed_operations: ['read', 'list', 'search', 'index', 'preview', 'summarize', 'delete'],
          ledger_entry_count: 7,
          checkpoint_count: 2,
          trash_root: 'F:\\trainer\\workspace-a\\.trainer\\trash',
        };
      },
      async postJson(port, requestPath, body) {
        posts.push({ port, requestPath, body });
        return {
          memory: {
            memory_share_grants: [],
          },
        };
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    workbench: {
      async syncState() {
        syncs.push(true);
      },
    },
    getHostState() {
      return {
        bootstrap,
        workspace: {
          workspaceFolder: 'F:\\trainer\\workspace-a',
          activeWorkspaceRoot: 'F:\\trainer\\workspace-a',
          trusted: true,
          remoteName: '',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    __patches: patches,
    __gets: gets,
    __posts: posts,
    __syncs: syncs,
  };
}

test('refreshWorkspaceAuthorityCommand refreshes only sandbox authority state', async () => {
  const vscodeMock = {};
  const { refreshWorkspaceAuthorityCommand } = loadWithVscodeMock(memoryCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await refreshWorkspaceAuthorityCommand(context);

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /authority refreshed/i);
  assert.deepEqual(context.__gets, [
    {
      port: 34891,
      requestPath:
        '/workspace/authority?workspace_id=F%3A%5Ctrainer%5Cworkspace-a&session_id=session-1&workspace_trusted=true&remote_name=',
    },
  ]);
  assert.equal(context.__patches.length, 1);
  assert.equal(context.__syncs.length, 1);
  assert.equal(context.__patches[0].conversation, undefined);
  assert.equal(context.__patches[0].memory.sandboxState.rootPath, 'F:\\trainer\\workspace-a');
  assert.equal(context.__patches[0].memory.sandboxState.activeWorkspaceRoot, 'F:\\trainer\\workspace-a');
  assert.equal(context.__patches[0].memory.sandboxState.authoritySource, 'workspace_authority_service');
  assert.equal(context.__patches[0].memory.sandboxState.authority.authoritySource, 'workspace_authority_service');
  assert.equal(context.__patches[0].memory.sandboxState.trashRootPath, 'F:\\trainer\\workspace-a\\.trainer\\trash');
  assert.equal(context.__patches[0].memory.sandboxState.authority.permissionLevel, 'DESTRUCTIVE');
  assert.equal(context.__patches[0].memory.sandboxState.authority.ledgerEntryCount, 7);
});

test('refreshMemoryCommand keeps a managed context for the next dependency action', async () => {
  const vscodeMock = {};
  const { refreshMemoryCommand } = loadWithVscodeMock(memoryCommandsModulePath, vscodeMock);
  const context = createContext();
  context.getHostState().bootstrap.memory.workspace = {
    ...(context.getHostState().bootstrap.memory.workspace ?? {}),
    trainerWorkspace: {
      status: 'managed',
      contextId: 'context-managed-123',
      canonicalProjectPath: 'f:\\trainer\\workspace-a',
      rootId: 'root-managed',
      projectId: 'project-managed',
    },
  };
  context.sidecarClient.getJson = async (port, requestPath) => {
    context.__gets.push({ port, requestPath });
    return {
      memory: {
        workspace: {
          workspace_id: 'context-managed-123',
        },
      },
    };
  };

  const result = await refreshMemoryCommand(context);

  assert.equal(result.ok, true);
  assert.deepEqual(context.__gets, [
    {
      port: 34891,
      requestPath: '/memory/summary?workspace_id=context-managed-123&session_id=session-1',
    },
  ]);
  assert.equal(context.__patches.length, 1);
  assert.equal(
    context.__patches[0].memory.workspace?.trainerWorkspace?.contextId,
    'context-managed-123',
  );
});

test('revokeMemoryShareCommand removes the source through the current workspace and refreshes the snapshot', async () => {
  const vscodeMock = {};
  const { revokeMemoryShareCommand } = loadWithVscodeMock(memoryCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await revokeMemoryShareCommand(context, {
    sourceWorkspaceId: 'F:\\trainer\\workspace-source',
  });

  assert.equal(result.ok, true);
  assert.deepEqual(context.__posts, [
    {
      port: 34891,
      requestPath: '/memory/share-grants/revoke',
      body: {
        session_id: 'session-1',
        workspace_id: 'F:\\trainer\\workspace-a',
        source_workspace_id: 'F:\\trainer\\workspace-source',
      },
    },
  ]);
  assert.equal(context.__patches.length, 1);
  assert.deepEqual(context.__patches[0].memory.memoryShareGrants, []);
  assert.equal(context.__syncs.length, 1);
});

test('revokeMemoryShareCommand uses the managed target without changing the source workspace identity', async () => {
  const vscodeMock = {};
  const { revokeMemoryShareCommand } = loadWithVscodeMock(memoryCommandsModulePath, vscodeMock);
  const context = createContext();
  const managedContextId = 'context-memory-123';
  const sourceWorkspaceId = 'F:\\trainer\\workspace-source';
  context.getHostState().bootstrap.memory.workspace = {
    ...(context.getHostState().bootstrap.memory.workspace ?? {}),
    trainerWorkspace: {
      status: 'managed',
      contextId: managedContextId,
      canonicalProjectPath: 'f:\\trainer\\workspace-a',
      rootId: 'root-memory',
      projectId: 'project-memory',
    },
  };

  const result = await revokeMemoryShareCommand(context, { sourceWorkspaceId });

  assert.equal(result.ok, true);
  assert.equal(context.__posts[0].body.workspace_id, managedContextId);
  assert.equal(context.__posts[0].body.source_workspace_id, sourceWorkspaceId);
});
