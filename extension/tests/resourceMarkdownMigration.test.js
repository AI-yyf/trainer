'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
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

function createContext() {
  const requests = [];
  const hostMessages = [];
  return {
    workbench: {
      resolveWebviewUriForPath() {
        return undefined;
      },
      async postMessage(message) {
        hostMessages.push(message);
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        requests.push({ port, requestPath, body });
        return {
          status: body.dry_run ? 'preview' : 'completed',
          resources: 3,
          originals_to_delete: body.dry_run ? 1 : 1,
          records_to_mark: body.dry_run ? 2 : 2,
          convertible: 0,
          manifest: [{ resource_id: 'resource-1', action: 'delete_originals' }],
          failures: [],
        };
      },
    },
    getHostState() {
      return {
        bootstrap: { resources: [], memory: { workspace: { responseLanguage: 'zh-CN' } } },
        workspace: { workspaceFolder: '/tmp/trainer-workspace' },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    __requests: requests,
    __hostMessages: hostMessages,
  };
}

test('the Markdown-only migration previews first and answers the request it was given', async () => {
  const { markdownOnlyMigrationCommand } = loadWithVscodeMock(resourceCommandsModulePath, {});
  const context = createContext();

  const result = await markdownOnlyMigrationCommand(context, {
    operationId: 'op-preview',
    dryRun: true,
  });

  assert.equal(result.ok, true);
  assert.equal(context.__requests.length, 1);
  assert.equal(context.__requests[0].requestPath, '/resource/md-only/migrate');
  assert.equal(context.__requests[0].body.dry_run, true);
  assert.equal(context.__requests[0].body.confirm, false);

  assert.equal(context.__hostMessages.length, 1);
  const answer = context.__hostMessages[0];
  assert.equal(answer.type, 'library/migration');
  assert.equal(answer.payload.operationId, 'op-preview');
  assert.equal(answer.payload.ok, true);
  assert.equal(answer.payload.summary.status, 'preview');
  assert.equal(answer.payload.summary.originals_to_delete, 1);
});

test('the destructive pass never runs without the one explicit confirmation', async () => {
  const { markdownOnlyMigrationCommand } = loadWithVscodeMock(resourceCommandsModulePath, {});
  const context = createContext();

  const unconfirmed = await markdownOnlyMigrationCommand(context, {
    operationId: 'op-unconfirmed',
    dryRun: false,
  });

  assert.equal(unconfirmed.ok, false);
  // Nothing reached the sidecar: the unconfirmed pass is refused locally.
  assert.equal(context.__requests.length, 0);
  assert.equal(context.__hostMessages[0].type, 'library/migration');
  assert.equal(context.__hostMessages[0].payload.ok, false);
  assert.match(context.__hostMessages[0].payload.message, /确认|confirmation/i);

  const confirmed = await markdownOnlyMigrationCommand(context, {
    operationId: 'op-confirmed',
    dryRun: false,
    confirm: true,
  });

  assert.equal(confirmed.ok, true);
  assert.equal(context.__requests.length, 1);
  assert.equal(context.__requests[0].body.dry_run, false);
  assert.equal(context.__requests[0].body.confirm, true);
  assert.equal(context.__hostMessages[1].payload.operationId, 'op-confirmed');
});

test('a failed migration reports the failure instead of claiming a clean library', async () => {
  const { markdownOnlyMigrationCommand } = loadWithVscodeMock(resourceCommandsModulePath, {});
  const context = createContext();
  context.sidecarClient.postJson = async () => {
    const error = new Error('sidecar unavailable');
    error.statusCode = 503;
    throw error;
  };

  const result = await markdownOnlyMigrationCommand(context, {
    operationId: 'op-failed',
    dryRun: true,
  });

  assert.equal(result.ok, false);
  assert.equal(context.__hostMessages[0].payload.ok, false);
  assert.ok(context.__hostMessages[0].payload.message.length > 0);
});
