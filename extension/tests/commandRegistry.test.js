'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const commandRegistryModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'commandRegistry.js',
);

const vscodeMock = {
  commands: {
    registerCommand() {
      return { dispose() {} };
    },
  },
  workspace: {},
};

function createContext(status) {
  let syncCount = 0;
  return {
    trainerWorkspace: {
      getRoot() {
        return 'C:\\trainer-workspace-tests\\root';
      },
    },
    getHostState() {
      return {
        bootstrap: {
          memory: {
            workspace: {
              trainerWorkspace: { status },
            },
          },
        },
      };
    },
    outputChannel: {
      appendLine() {},
    },
    workbench: {
      async syncState() {
        syncCount += 1;
      },
    },
    get syncCount() {
      return syncCount;
    },
  };
}

const WORKSPACE_WORKFLOW_COMMANDS = [
  'trainer.plan.generate',
  'trainer.evaluate.currentFile',
  'trainer.resource.upload',
  'trainer.resource.restore',
  'trainer.sandbox.write',
  'trainer.memory.refresh',
  'trainer.evidence.enqueue',
  'trainer.training.generateCard',
  'trainer.research.create',
];

const RESOURCE_MUTATION_COMMANDS = [
  'trainer.resource.upload',
  'trainer.resource.index',
  'trainer.resource.delete',
  'trainer.resource.restore',
  'trainer.sandbox.restore',
  'trainer.sandbox.write',
  'trainer.sandbox.mkdir',
  'trainer.sandbox.rename',
  'trainer.sandbox.delete',
  'trainer.sandbox.deleteMany',
  'trainer.sandbox.chooseRoot',
  'trainer.sandbox.resetRoot',
  'trainer.resource.chooseManagedDataFolder',
  'trainer.resource.resetManagedDataFolder',
];

const READ_ONLY_RESOURCE_COMMANDS = [
  'trainer.resource.search',
  'trainer.resource.open',
  'trainer.resource.refreshTrash',
  'trainer.sandbox.preview',
  'trainer.sandbox.refresh',
  'trainer.sandbox.reveal',
];

test('workspace workflow commands stop before their handler for every incomplete admission state', async () => {
  const { CommandRegistry } = loadWithVscodeMock(commandRegistryModulePath, vscodeMock);

  for (const status of ['root-missing', 'project-found', 'browse', 'ignored']) {
    const context = createContext(status);
    const registry = new CommandRegistry(context.outputChannel);
    const extensionContext = { subscriptions: [] };
    let calls = 0;
    registry.setContext(context);
    for (const commandId of WORKSPACE_WORKFLOW_COMMANDS) {
      registry.register(extensionContext, commandId, async () => {
        calls += 1;
        return { ok: true };
      });
    }

    for (const commandId of WORKSPACE_WORKFLOW_COMMANDS) {
      const result = await registry.execute(commandId);
      assert.equal(result.ok, false, `${status}: ${commandId}`);
    }
    assert.equal(calls, 0, status);
    assert.equal(context.syncCount, 0, status);
  }
});

test('provider setup commands remain available while workspace admission is incomplete', async () => {
  const { CommandRegistry } = loadWithVscodeMock(commandRegistryModulePath, vscodeMock);
  const context = createContext('root-missing');
  const registry = new CommandRegistry(context.outputChannel);
  const extensionContext = { subscriptions: [] };
  let calls = 0;
  registry.setContext(context);
  registry.register(extensionContext, 'trainer.provider.test', async () => {
    calls += 1;
    return { ok: true, message: 'Provider is reachable.' };
  });

  const result = await registry.execute('trainer.provider.test');

  assert.equal(result.ok, true);
  assert.equal(calls, 1);
  assert.equal(context.syncCount, 1);
});

test('a closed output channel does not mask the command failure', async () => {
  const { CommandRegistry } = loadWithVscodeMock(commandRegistryModulePath, vscodeMock);
  const context = createContext('managed');
  const registry = new CommandRegistry({
    appendLine() {
      throw new Error('Channel has been closed');
    },
  });
  const extensionContext = { subscriptions: [] };
  registry.setContext(context);
  registry.register(extensionContext, 'trainer.provider.test', async () => {
    throw new Error('The provider request timed out.');
  });

  const result = await registry.execute('trainer.provider.test');

  assert.deepEqual(result, {
    ok: false,
    message: 'The provider request timed out.',
  });
  assert.equal(context.syncCount, 0);
});

test('resource restore follows the current project admission mode', async () => {
  const { CommandRegistry } = loadWithVscodeMock(commandRegistryModulePath, vscodeMock);

  for (const [status, allowed] of [
    ['project-found', false],
    ['browse', false],
    ['managed', true],
  ]) {
    const context = createContext(status);
    const registry = new CommandRegistry(context.outputChannel);
    const extensionContext = { subscriptions: [] };
    let calls = 0;
    registry.setContext(context);
    registry.register(extensionContext, 'trainer.resource.restore', async () => {
      calls += 1;
      return { ok: true, message: 'Resource restored.' };
    });

    const result = await registry.execute('trainer.resource.restore');

    assert.equal(result.ok, allowed, status);
    assert.equal(calls, allowed ? 1 : 0, status);
    assert.equal(context.syncCount, allowed ? 1 : 0, status);
  }
});

test('browse and ignored projects stop every registered resource mutation before its handler runs', async () => {
  const { CommandRegistry } = loadWithVscodeMock(commandRegistryModulePath, vscodeMock);

  for (const status of ['browse', 'ignored']) {
    const context = createContext(status);
    const registry = new CommandRegistry(context.outputChannel);
    const extensionContext = { subscriptions: [] };
    let calls = 0;
    registry.setContext(context);
    for (const commandId of RESOURCE_MUTATION_COMMANDS) {
      registry.register(extensionContext, commandId, async () => {
        calls += 1;
        return { ok: true };
      });
    }

    for (const commandId of RESOURCE_MUTATION_COMMANDS) {
      const result = await registry.execute(commandId);
      assert.equal(result.ok, false, `${status}: ${commandId}`);
    }
    assert.equal(calls, 0, status);
    assert.equal(context.syncCount, 0, status);
  }
});

test('browse and ignored projects retain registered read-only resource actions', async () => {
  const { CommandRegistry } = loadWithVscodeMock(commandRegistryModulePath, vscodeMock);

  for (const status of ['browse', 'ignored']) {
    const context = createContext(status);
    const registry = new CommandRegistry(context.outputChannel);
    const extensionContext = { subscriptions: [] };
    let calls = 0;
    registry.setContext(context);
    for (const commandId of READ_ONLY_RESOURCE_COMMANDS) {
      registry.register(extensionContext, commandId, async () => {
        calls += 1;
        return { ok: true, message: 'Read-only resource action completed.' };
      });
    }

    for (const commandId of READ_ONLY_RESOURCE_COMMANDS) {
      const result = await registry.execute(commandId);
      assert.equal(result.ok, true, `${status}: ${commandId}`);
    }
    assert.equal(calls, READ_ONLY_RESOURCE_COMMANDS.length, status);
    assert.equal(context.syncCount, READ_ONLY_RESOURCE_COMMANDS.length, status);
  }
});
