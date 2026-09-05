'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const workspaceContextModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'workspaceContext.js',
);

test('getWorkspaceId and getWorkspaceName prefer activeWorkspaceRoot over workspaceFolder', () => {
  const vscodeMock = {
    workspace: {
      workspaceFolders: [],
    },
    window: {},
  };

  const { getRuntimeWorkspaceContext, getWorkspaceId, getWorkspaceName } = loadWithVscodeMock(
    workspaceContextModulePath,
    vscodeMock,
  );

  const context = {
    getHostState() {
      return {
        workspace: {
          activeWorkspaceRoot: 'F:\\trainer-active',
          workspaceFolder: 'F:\\trainer-fallback',
        },
        bootstrap: { memory: {} },
      };
    },
    getSessionId() {
      return undefined;
    },
  };

  assert.equal(getWorkspaceId(context), 'F:\\trainer-active');
  assert.equal(getWorkspaceName(context), 'trainer-active');
  assert.equal(getRuntimeWorkspaceContext(context).legacyWorkspaceId, 'F:\\trainer-active');
});

test('getWorkspaceId falls back to the default workspace when multi-root has no active sovereign root', () => {
  const vscodeMock = {
    workspace: {
      workspaceFolders: [
        { uri: { fsPath: 'F:\\trainer-alpha' } },
        { uri: { fsPath: 'F:\\trainer-beta' } },
      ],
    },
    window: {
      activeTextEditor: undefined,
    },
  };

  const { getWorkspaceId, getWorkspaceName } = loadWithVscodeMock(
    workspaceContextModulePath,
    vscodeMock,
  );

  const context = {
    getHostState() {
      return {
        workspace: {
          workspaceFolder: 'F:\\trainer-stale',
        },
      };
    },
    getSessionId() {
      return undefined;
    },
  };

  assert.equal(getWorkspaceId(context), 'workspace-default');
  assert.equal(getWorkspaceName(context), 'Trainer');
});

test('withWorkspaceQuery uses the managed context ID and keeps unmanaged workspaces physical', () => {
  const vscodeMock = {
    workspace: { workspaceFolders: [] },
    window: {},
  };
  const { withWorkspaceQuery } = loadWithVscodeMock(workspaceContextModulePath, vscodeMock);
  const managedContext = {
    getHostState() {
      return {
        workspace: {
          activeWorkspaceRoot: 'F:\\trainer-managed',
          workspaceFolder: 'F:\\trainer-managed',
        },
        bootstrap: {
          memory: {
            workspace: {
              trainerWorkspace: {
                status: 'managed',
                contextId: 'context-managed-123',
              },
            },
          },
        },
      };
    },
    getSessionId() {
      return 'session-managed';
    },
  };
  const unmanagedContext = {
    getHostState() {
      return {
        workspace: {
          activeWorkspaceRoot: 'F:\\trainer-unmanaged',
          workspaceFolder: 'F:\\trainer-unmanaged',
        },
        bootstrap: { memory: {} },
      };
    },
    getSessionId() {
      return undefined;
    },
  };

  assert.equal(
    withWorkspaceQuery('/memory/summary', managedContext),
    '/memory/summary?workspace_id=context-managed-123&session_id=session-managed',
  );
  assert.equal(
    withWorkspaceQuery('/memory/summary', unmanagedContext),
    '/memory/summary?workspace_id=F%3A%5Ctrainer-unmanaged',
  );
  assert.equal(
    withWorkspaceQuery('/memory/summary', managedContext, 'F:\\explicit-legacy-path'),
    '/memory/summary?workspace_id=F%3A%5Cexplicit-legacy-path&session_id=session-managed',
  );
});
