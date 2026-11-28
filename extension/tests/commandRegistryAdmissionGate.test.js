'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const distSrc = path.resolve(__dirname, '..', 'dist', 'extension', 'src');
const commandRegistryModulePath = path.join(distSrc, 'core', 'commandRegistry.js');
const { COMMAND_IDS } = require(path.join(distSrc, 'core', 'constants.js'));
const { trainerCommands } = require(
  path.resolve(__dirname, '..', 'dist', 'shared', 'src', 'commands.js'),
);

const MARKER = '[[trainer-resource-failure]] ';
const ROOT = 'F:\\trainer\\workspace-a';

// `trainerSessionBlockReason` reports a missing root first, so statuses other than
// "no root at all" are only reachable when a Trainer workspace root exists.
function createContext({ status, language = 'en-US', withRoot = true }) {
  return {
    getHostState: () => ({
      bootstrap: {
        memory: {
          workspace: {
            responseLanguage: language,
            trainerWorkspace: status ? { status } : undefined,
          },
        },
      },
    }),
    trainerWorkspace: withRoot ? { getRoot: () => ROOT } : undefined,
    // Only touched once the gate lets a command through.
    workbench: { syncState: async () => {} },
  };
}

function uploadedCommandId() {
  const upload = COMMAND_IDS.uploadResource;
  assert.equal(typeof upload, 'string');
  assert.equal(upload, trainerCommands.uploadResource);
  return upload;
}

async function gateResult(commandId, context) {
  const calls = [];
  const toasts = [];
  const registered = new Map();
  const vscodeMock = {
    commands: {
      registerCommand: (id, callback) => {
        registered.set(id, callback);
        return { dispose: () => {} };
      },
    },
    window: {
      showWarningMessage: (message) => {
        toasts.push(message);
      },
    },
  };
  const { CommandRegistry } = loadWithVscodeMock(commandRegistryModulePath, vscodeMock);
  const registry = new CommandRegistry({ appendLine: () => {} });
  registry.setContext(context);
  const handler = async () => {
    calls.push('handler');
    return { ok: true };
  };
  registry.register({ subscriptions: [] }, commandId, handler);
  const direct = await registry.execute(commandId, {});
  // A palette or shortcut invocation goes through the registered command, which also
  // shows the failure as a toast because no webview reads the return value.
  await registered.get(commandId)({ mode: 'files', __trainerResourceOperationId: 'op-1' });
  return { direct, toasts, calls };
}

test('a blocked resource change reports its reason in resource terms and marked for the webview', async () => {
  const upload = uploadedCommandId();
  const cases = [
    { name: 'no trainer workspace', options: { withRoot: false }, pattern: /choose how trainer should work with this project/i },
    { name: 'browse-only', options: { status: 'browse' }, pattern: /browse-only.*cannot add, index, or change/i },
    { name: 'ignored', options: { status: 'ignored' }, pattern: /ignored.*will not add or change resources/i },
    { name: 'project found, decision pending', options: { status: 'project-found' }, pattern: /project was found/i },
  ];
  for (const { name, options, pattern } of cases) {
    const { direct, toasts, calls } = await gateResult(upload, createContext(options));

    assert.equal(direct.ok, false, name);
    assert.ok(
      typeof direct.message === 'string' && direct.message.startsWith(MARKER),
      `${name}: expected marked host copy, got ${JSON.stringify(direct.message)}`,
    );
    assert.match(direct.message, pattern, `${name}: the reason should fit a resource change`);
    assert.deepEqual(calls, [], `${name}: the handler must not run`);
    assert.equal(toasts.length, 1, name);
    assert.ok(!toasts[0].includes('[['), `${name}: the toast must not show protocol markers: ${toasts[0]}`);
    assert.ok(
      toasts[0].endsWith(direct.message.slice(MARKER.length)),
      `${name}: the toast should carry the same reason as the webview copy`,
    );
  }
});

test('the marked resource reason follows the workspace language', async () => {
  const { direct } = await gateResult(uploadedCommandId(), createContext({ language: 'zh-CN', withRoot: false }));

  assert.ok(direct.message.startsWith(MARKER), direct.message);
  assert.match(direct.message.slice(MARKER.length), /再变更资料/);
});

test('every resource change the gate covers gets the resource reason, not the conversation one', async () => {
  const resourceCommands = [
    COMMAND_IDS.uploadResource,
    COMMAND_IDS.indexResources,
    COMMAND_IDS.deleteResource,
    COMMAND_IDS.restoreResource,
    COMMAND_IDS.restoreSandboxPath,
    COMMAND_IDS.createSandboxFile,
    COMMAND_IDS.createSandboxDirectory,
    COMMAND_IDS.renameSandboxPath,
    COMMAND_IDS.deleteSandboxPath,
    COMMAND_IDS.deleteSandboxPaths,
  ];
  for (const commandId of resourceCommands) {
    const { direct, calls } = await gateResult(commandId, createContext({ withRoot: false }));
    assert.equal(direct.ok, false, commandId);
    assert.ok(direct.message.startsWith(MARKER), `${commandId}: ${direct.message}`);
    assert.doesNotMatch(direct.message, /before starting a conversation/i, commandId);
    assert.deepEqual(calls, [], commandId);
  }
});

test('commands that are not resource changes keep the session-level reason unmarked', async () => {
  const { direct, calls } = await gateResult(COMMAND_IDS.generatePlan, createContext({ withRoot: false }));

  assert.equal(direct.ok, false);
  assert.equal(typeof direct.message, 'string');
  assert.ok(!direct.message.startsWith(MARKER), direct.message);
  assert.match(direct.message, /choose a trainer workspace before starting a conversation/i);
  assert.deepEqual(calls, []);
});

test('an admitted workspace is not gated', async () => {
  const { direct, calls, toasts } = await gateResult(uploadedCommandId(), createContext({ status: 'managed' }));

  assert.deepEqual(direct, { ok: true });
  // gateResult runs the command twice: directly and through the registered command.
  assert.deepEqual(calls, ['handler', 'handler']);
  assert.deepEqual(toasts, []);
});
