'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const workspaceTrustModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'workspaceTrust.js',
);

test('WorkspaceTrustGuard infers activeWorkspaceRoot from recent files when no editor is active', () => {
  const vscodeMock = {
    workspace: {
      isTrusted: true,
      workspaceFolders: [
        { uri: { fsPath: 'F:\\trainer-alpha' } },
        { uri: { fsPath: 'F:\\trainer-beta' } },
      ],
      getDiagnostics() {
        return [];
      },
    },
    window: {
      activeTextEditor: undefined,
    },
    env: {
      remoteName: undefined,
    },
    languages: {
      getDiagnostics() {
        return [];
      },
    },
  };

  const { WorkspaceTrustGuard } = loadWithVscodeMock(workspaceTrustModulePath, vscodeMock);
  const guard = new WorkspaceTrustGuard();
  guard.rememberDocumentEdit({
    uri: { fsPath: 'F:\\trainer-beta\\src\\main.py' },
  });

  const snapshot = guard.getSnapshot();

  assert.equal(snapshot.activeWorkspaceRoot, 'F:\\trainer-beta');
  assert.equal(snapshot.workspaceFolder, 'F:\\trainer-beta');
});

test('WorkspaceTrustGuard reports the VS Code remote host in its snapshot', () => {
  const vscodeMock = {
    workspace: {
      isTrusted: true,
      workspaceFolders: [{ uri: { fsPath: 'F:\\trainer-remote' } }],
    },
    window: {
      activeTextEditor: undefined,
    },
    env: {
      remoteName: 'ssh-remote',
    },
    languages: {
      getDiagnostics() {
        return [];
      },
    },
  };

  const { WorkspaceTrustGuard } = loadWithVscodeMock(workspaceTrustModulePath, vscodeMock);
  const snapshot = new WorkspaceTrustGuard().getSnapshot();

  assert.equal(snapshot.remoteName, 'ssh-remote');
  assert.equal(snapshot.isRemoteWorkspace, true);
});

test('WorkspaceTrustGuard gives a short localized trust prompt without leaking command internals', async () => {
  const warningCalls = [];
  const commandCalls = [];
  const vscodeMock = {
    workspace: {
      isTrusted: false,
      workspaceFolders: [],
    },
    window: {
      activeTextEditor: undefined,
      async showWarningMessage(message, action) {
        warningCalls.push({ message, action });
        return action;
      },
    },
    env: {
      language: 'zh-cn',
    },
    commands: {
      async executeCommand(command) {
        commandCalls.push(command);
      },
    },
    languages: {
      getDiagnostics() {
        return [];
      },
    },
  };

  const { WorkspaceTrustGuard } = loadWithVscodeMock(workspaceTrustModulePath, vscodeMock);
  const trusted = await new WorkspaceTrustGuard().ensureTrusted('start the Trainer sidecar');

  assert.equal(trusted, false);
  assert.deepEqual(warningCalls, [
    {
      message: '要继续使用 Trainer，请先信任当前工作区。',
      action: '管理工作区信任',
    },
  ]);
  assert.deepEqual(commandCalls, ['workbench.trust.manage']);
});
