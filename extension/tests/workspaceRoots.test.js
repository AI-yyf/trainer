'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const workspaceRootsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'workspaceRoots.js',
);

test('resolveActiveWorkspaceFolder prefers the folder containing the active file', () => {
  const vscodeMock = {
    workspace: {
      workspaceFolders: [
        { uri: { fsPath: 'F:\\trainer-alpha' } },
        { uri: { fsPath: 'F:\\trainer-beta' } },
      ],
    },
    window: {
      activeTextEditor: {
        document: {
          uri: { fsPath: 'F:\\trainer-beta\\src\\main.py' },
        },
      },
    },
  };

  const { resolveActiveWorkspaceFolderPath } = loadWithVscodeMock(
    workspaceRootsModulePath,
    vscodeMock,
  );

  assert.equal(resolveActiveWorkspaceFolderPath(), 'F:\\trainer-beta');
});

test('resolveActiveWorkspaceFolder matches POSIX-native folder paths on any host', () => {
  const vscodeMock = {
    workspace: {
      workspaceFolders: [
        { uri: { fsPath: '/repo/trainer-alpha' } },
        { uri: { fsPath: '/repo/trainer-beta' } },
      ],
    },
    window: {
      activeTextEditor: {
        document: {
          uri: { fsPath: '/repo/trainer-beta/src/main.py' },
        },
      },
    },
  };

  const { resolveActiveWorkspaceFolderPath } = loadWithVscodeMock(
    workspaceRootsModulePath,
    vscodeMock,
  );

  assert.equal(resolveActiveWorkspaceFolderPath(), '/repo/trainer-beta');
});

test('resolveActiveWorkspaceFolder returns undefined when multiple folders have no active-file match', () => {
  const vscodeMock = {
    workspace: {
      workspaceFolders: [
        { uri: { fsPath: 'F:\\trainer-alpha' } },
        { uri: { fsPath: 'F:\\trainer-beta' } },
      ],
    },
    window: {
      activeTextEditor: {
        document: {
          uri: { fsPath: 'F:\\outside\\notes.md' },
        },
      },
    },
  };

  const { resolveActiveWorkspaceFolderPath } = loadWithVscodeMock(
    workspaceRootsModulePath,
    vscodeMock,
  );

  assert.equal(resolveActiveWorkspaceFolderPath(), undefined);
});

test('resolveActiveWorkspaceFolder keeps the only workspace folder as the sovereign root', () => {
  const vscodeMock = {
    workspace: {
      workspaceFolders: [{ uri: { fsPath: 'F:\\trainer-alpha' } }],
    },
    window: {
      activeTextEditor: undefined,
    },
  };

  const { resolveActiveWorkspaceFolderPath } = loadWithVscodeMock(
    workspaceRootsModulePath,
    vscodeMock,
  );

  assert.equal(resolveActiveWorkspaceFolderPath(), 'F:\\trainer-alpha');
});
