'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const modulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'libraryFolderCommands.js',
);
const { createDefaultBootstrapData } = require(path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'workbenchData.js',
));

function createContext({ ready = true, trusted = true } = {}) {
  const calls = { get: [], post: [], del: [], messages: [], trust: 0, ensureRunning: 0 };
  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: '/ws/project' },
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
    { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
  );
  return {
    sidecarManager: {
      async ensureRunning() {
        calls.ensureRunning += 1;
        return ready
          ? { lifecycle: 'ready', port: 34891 }
          : { lifecycle: 'starting', detail: 'Sidecar is starting.' };
      },
    },
    sidecarClient: {
      async getJson(port, requestPath) {
        calls.get.push({ port, requestPath });
        return {
          managed_root: 'Trainer Library',
          exists: true,
          total_resource_count: 2,
          groups: [{ path: 'course', name: 'course', resource_count: 2 }],
        };
      },
      async postJson(port, requestPath, body) {
        calls.post.push({ port, requestPath, body });
        return { ok: true };
      },
      async deleteJson(port, requestPath, body) {
        calls.del.push({ port, requestPath, body });
        return { ok: true, recoverable: true };
      },
    },
    workbench: {
      async postMessage(message) {
        calls.messages.push(message);
      },
    },
    trustGuard: {
      async ensureTrusted() {
        calls.trust += 1;
        return trusted;
      },
    },
    getSessionId() {
      return 'session-1';
    },
    getHostState() {
      return { bootstrap, workspace: { workspaceFolder: '/ws/project' } };
    },
    __calls: calls,
  };
}

function lastAnswer(context) {
  return context.__calls.messages[context.__calls.messages.length - 1];
}

test('list forwards the folder tree in a correlated library/folders answer', async () => {
  const { libraryFoldersListCommand } = loadWithVscodeMock(modulePath, {});
  const context = createContext();
  const result = await libraryFoldersListCommand(context, { operationId: 'op-1' });
  assert.equal(result.ok, true);
  assert.equal(context.__calls.get.length, 1);
  assert.match(context.__calls.get[0].requestPath, /^\/library\/groups(\?workspace_id=.*)?$/);
  const answer = lastAnswer(context);
  assert.equal(answer.type, 'library/folders');
  assert.equal(answer.payload.operationId, 'op-1');
  assert.equal(answer.payload.ok, true);
  assert.equal(answer.payload.folders.groups[0].path, 'course');
});

test('create posts the folder path and answers ok', async () => {
  const { libraryFoldersCreateCommand } = loadWithVscodeMock(modulePath, {});
  const context = createContext();
  const result = await libraryFoldersCreateCommand(context, { operationId: 'op-2', path: 'course/basics' });
  assert.equal(result.ok, true);
  assert.equal(context.__calls.trust, 1);
  assert.equal(context.__calls.post.length, 1);
  assert.equal(context.__calls.post[0].requestPath, '/library/groups');
  assert.equal(context.__calls.post[0].body.path, 'course/basics');
  assert.equal(lastAnswer(context).payload.ok, true);
});

test('rename posts new_path and refuses without one', async () => {
  const { libraryFoldersRenameCommand } = loadWithVscodeMock(modulePath, {});
  const context = createContext();
  const ok = await libraryFoldersRenameCommand(context, {
    operationId: 'op-3',
    path: 'course',
    new_path: 'course-v2',
  });
  assert.equal(ok.ok, true);
  assert.equal(context.__calls.post[0].requestPath, '/library/groups/rename');
  assert.equal(context.__calls.post[0].body.new_path, 'course-v2');

  const missing = await libraryFoldersRenameCommand(context, { operationId: 'op-4', path: 'course' });
  assert.equal(missing.ok, false);
  assert.equal(lastAnswer(context).payload.operationId, 'op-4');
  assert.equal(lastAnswer(context).payload.ok, false);
  assert.match(lastAnswer(context).payload.message, /new folder path/i);
});

test('delete uses DELETE with the folder body', async () => {
  const { libraryFoldersDeleteCommand } = loadWithVscodeMock(modulePath, {});
  const context = createContext();
  const result = await libraryFoldersDeleteCommand(context, { operationId: 'op-5', path: 'course' });
  assert.equal(result.ok, true);
  assert.equal(context.__calls.del.length, 1);
  assert.equal(context.__calls.del[0].requestPath, '/library/groups');
  assert.equal(context.__calls.del[0].body.path, 'course');
  assert.equal(lastAnswer(context).payload.ok, true);
});

test('an unready sidecar answers honestly instead of failing silently', async () => {
  const { libraryFoldersListCommand } = loadWithVscodeMock(modulePath, {});
  const context = createContext({ ready: false });
  const result = await libraryFoldersListCommand(context, { operationId: 'op-6' });
  assert.equal(result.ok, false);
  const answer = lastAnswer(context);
  assert.equal(answer.payload.operationId, 'op-6');
  assert.equal(answer.payload.ok, false);
  assert.match(answer.payload.message, /starting/i);
  assert.equal(context.__calls.get.length, 0);
});

test('an untrusted workspace blocks mutations before any sidecar call', async () => {
  const { libraryFoldersCreateCommand } = loadWithVscodeMock(modulePath, {});
  const context = createContext({ trusted: false });
  const result = await libraryFoldersCreateCommand(context, { operationId: 'op-7', path: 'course' });
  assert.equal(result.ok, false);
  assert.equal(context.__calls.post.length, 0);
  assert.equal(context.__calls.ensureRunning, 0);
  assert.match(lastAnswer(context).payload.message, /trust/i);
});
