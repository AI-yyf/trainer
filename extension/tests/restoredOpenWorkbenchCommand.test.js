// Restored behavioral regression test. Original file: extension/tests/openWorkbenchCommand.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Opening the Trainer workbench with and without an admitted root (sidecar start gating).
//
// Restoration: whole - all 2 original test definitions, code and assertions unchanged.
// Target: extension host (extension/dist) with the vscode mock.

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const openWorkbenchModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'openWorkbench.js',
);

function createContext(status) {
  let shown = 0;
  let synced = 0;
  let sidecarStarts = 0;

  return {
    trainerWorkspace: {
      getRoot() {
        return 'H:\\trainer-workspace-root';
      },
    },
    getHostState() {
      return {
        workspace: { trusted: true },
        bootstrap: {
          memory: {
            workspace: {
              trainerWorkspace: { status },
            },
          },
        },
      };
    },
    workbench: {
      async show() {
        shown += 1;
      },
      async syncState() {
        synced += 1;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        sidecarStarts += 1;
      },
    },
    observed() {
      return { shown, synced, sidecarStarts };
    },
  };
}

test('opening Trainer with a missing root does not start the sidecar', async () => {
  const { openWorkbenchCommand } = loadWithVscodeMock(openWorkbenchModulePath, {});
  const context = createContext('root-missing');

  const result = await openWorkbenchCommand(context);

  assert.equal(result.ok, true);
  assert.deepEqual(context.observed(), { shown: 1, synced: 1, sidecarStarts: 0 });
});

test('opening an admitted Trainer workspace preserves sidecar startup', async () => {
  const { openWorkbenchCommand } = loadWithVscodeMock(openWorkbenchModulePath, {});
  const context = createContext('managed');

  await openWorkbenchCommand(context);

  assert.equal(context.observed().sidecarStarts, 1);
});
