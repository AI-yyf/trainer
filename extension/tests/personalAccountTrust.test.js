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

function createContext({ grants = [], globalStore = {} } = {}) {
  const patches = [];
  const posts = [];
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
    },
    { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
  );
  bootstrap.memory.memoryShareGrants = grants;
  bootstrap.memory.workspace = {
    ...bootstrap.memory.workspace,
    workspaceId: 'F:\\trainer\\workspace-a',
    trainerWorkspace: { status: 'managed' },
  };
  return {
    extensionContext: {
      globalState: {
        get(key) {
          return globalStore[key];
        },
        async update(key, value) {
          if (value === undefined) {
            delete globalStore[key];
          } else {
            globalStore[key] = value;
          }
        },
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        posts.push({ requestPath, body });
        return {
          memory: {
            memory_scope:
              requestPath === '/memory/scope' && body.scope === 'isolated' ? 'isolated' : 'global',
            memory_share_grants: grants,
          },
        };
      },
    },
    trainerWorkspace: {
      async toSnapshot() {
        return {
          manifest: {
            projects: {
              'F:\\trainer\\workspace-a': { adoptionMode: 'managed', projectPath: 'F:\\trainer\\workspace-a' },
              'F:\\trainer\\workspace-b': { adoptionMode: 'managed', projectPath: 'F:\\trainer\\workspace-b' },
              'F:\\trainer\\workspace-c': { adoptionMode: 'managed', projectPath: 'F:\\trainer\\workspace-c' },
              'F:\\trainer\\browse': { adoptionMode: 'browse', projectPath: 'F:\\trainer\\browse' },
            },
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
        return undefined;
      },
    },
    getHostState() {
      return {
        bootstrap,
        workspace: {
          workspaceFolder: 'F:\\trainer\\workspace-a',
          activeWorkspaceRoot: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    __posts: posts,
    __patches: patches,
    __globalStore: globalStore,
  };
}

test('setPersonalAccountTrustCommand enables the authoritative global memory policy', async () => {
  const { setPersonalAccountTrustCommand } = loadWithVscodeMock(memoryCommandsModulePath, {
    window: {},
  });
  const context = createContext();

  const result = await setPersonalAccountTrustCommand(context, { enabled: true });

  assert.equal(result.ok, true);
  assert.equal(context.__posts.length, 1);
  assert.equal(context.__posts[0].requestPath, '/memory/scope');
  assert.equal(context.__posts[0].body.scope, 'global');
  assert.equal(context.__globalStore['trainer.memory.personalAccountTrust'], true);
  const memoryPatch = context.__patches.find((patch) => patch.memory?.crossWorkspaceMemory === 'global');
  assert.ok(memoryPatch, 'server snapshot flips the webview toggle');
});

test('setPersonalAccountTrustCommand revokes incoming grants when disabled', async () => {
  const { setPersonalAccountTrustCommand } = loadWithVscodeMock(memoryCommandsModulePath, {
    window: {},
  });
  const context = createContext({
    grants: [
      { sourceWorkspaceId: 'F:\\trainer\\workspace-b', targetWorkspaceId: 'F:\\trainer\\workspace-a', categories: ['preferences'] },
      { sourceWorkspaceId: 'F:\\trainer\\workspace-c', targetWorkspaceId: 'F:\\trainer\\workspace-a', categories: ['mastery'] },
    ],
    globalStore: { 'trainer.memory.personalAccountTrust': true },
  });

  const result = await setPersonalAccountTrustCommand(context, { enabled: false });

  assert.equal(result.ok, true);
  assert.equal(context.__posts.length, 3);
  assert.equal(context.__posts[0].requestPath, '/memory/scope');
  assert.equal(context.__posts[0].body.scope, 'isolated');
  assert.ok(context.__posts.slice(1).every((post) => post.requestPath === '/memory/share-grants/revoke'));
  assert.equal(context.__globalStore['trainer.memory.personalAccountTrust'], undefined);
});

test('personalAccountTrusted prefers the authoritative server policy over the legacy cache', async () => {
  const { personalAccountTrusted } = loadWithVscodeMock(memoryCommandsModulePath, { window: {} });
  const off = createContext({ globalStore: { 'trainer.memory.personalAccountTrust': true } });
  off.getHostState().bootstrap.memory.crossWorkspaceMemory = 'isolated';
  assert.equal(personalAccountTrusted(off), false);
  const on = createContext();
  on.getHostState().bootstrap.memory.crossWorkspaceMemory = 'global';
  assert.equal(personalAccountTrusted(on), true);
});
