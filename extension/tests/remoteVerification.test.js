'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const remoteVerificationModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'remoteVerificationCommands.js',
);

const ATTEST_PATH = '/training/verification/attest';

function createCommandContext(overrides = {}) {
  const posts = [];
  const hostState = {
    sessionId: overrides.sessionId,
    workspace: {
      workspaceFolder: '/workspace',
      ...(overrides.workspace ?? {}),
    },
    bootstrap: {
      workspaceTrainingState: overrides.trainingState ?? null,
    },
  };
  const context = {
    outputChannel: { appendLine() {} },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        posts.push([port, requestPath, body]);
        return { ok: true };
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return overrides.trusted ?? true;
      },
    },
    workspaceGateway: overrides.gateway ?? {
      async capabilities() {
        return { companionAvailable: true, verify: true };
      },
      async verify() {
        return {
          result: 'passed',
          command: overrides.command ?? 'npm test',
          exit_code: 0,
          stdout: 'all tests passed',
          stderr: '',
        };
      },
    },
    getHostState: () => hostState,
    getSessionId: () => overrides.sessionId,
  };
  return { context, posts };
}

test('remote verification requires a remote workspace window', async () => {
  const { remoteVerifyCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
  const { context, posts } = createCommandContext({ workspace: { isRemoteWorkspace: false } });
  const result = await remoteVerifyCommand(context, { command: 'npm test' });
  assert.equal(result.ok, false);
  assert.match(result.message, /Remote-SSH, WSL, Tunnel, or Dev Container/);
  assert.deepEqual(posts, []);
});

test('remote verification reports a missing companion instead of recording evidence', async () => {
  const { remoteVerifyCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
  let verifyCalls = 0;
  const { context, posts } = createCommandContext({
    workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
    gateway: {
      async capabilities() {
        return { companionAvailable: false, verify: false };
      },
      async verify() {
        verifyCalls += 1;
        return { result: 'passed', exit_code: 0 };
      },
    },
  });
  const result = await remoteVerifyCommand(context, { command: 'npm test' });
  assert.equal(result.ok, false);
  assert.match(result.message, /Install Remote Workspace Support/);
  assert.equal(verifyCalls, 0);
  assert.deepEqual(posts, []);
});

test('a passed remote run attests host-trusted evidence for the live practice card', async () => {
  const { remoteVerifyCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
  const { context, posts } = createCommandContext({
    workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
    sessionId: 'session-1',
    trainingState: {
      selectedCardId: 'card-9',
      selectedCardStatus: 'active',
      selectedCardType: 'practice',
    },
  });
  const result = await remoteVerifyCommand(context, { command: 'npm test' });
  assert.equal(result.ok, true);
  assert.match(result.message, /attested/);
  assert.equal(posts.length, 1);
  const [, requestPath, body] = posts[0];
  assert.equal(requestPath, ATTEST_PATH);
  assert.equal(body.card_id, 'card-9');
  assert.equal(body.passed, true);
  assert.equal(body.evidence_source, 'test_runner');
  assert.match(body.summary, /Remote verify passed: npm test \(exit 0\)/);
});

test('a failed remote run attests an honest failure', async () => {
  const { remoteVerifyCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
  const { context, posts } = createCommandContext({
    workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
    trainingState: {
      selectedCardId: 'card-9',
      selectedCardStatus: 'active',
      selectedCardType: 'practice',
    },
    gateway: {
      async capabilities() {
        return { companionAvailable: true, verify: true };
      },
      async verify() {
        return { result: 'failed', command: 'npm test', exit_code: 1, stdout: '', stderr: '1 test failed' };
      },
    },
  });
  const result = await remoteVerifyCommand(context, { command: 'npm test' });
  assert.equal(result.ok, false);
  assert.equal(posts.length, 1);
  const [, , body] = posts[0];
  assert.equal(body.passed, false);
  assert.match(body.summary, /exit 1/);
});

test('an interrupted remote run records no evidence at all', async () => {
  const { remoteVerifyCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
  const { context, posts } = createCommandContext({
    workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
    trainingState: {
      selectedCardId: 'card-9',
      selectedCardStatus: 'active',
      selectedCardType: 'practice',
    },
    gateway: {
      async capabilities() {
        return { companionAvailable: true, verify: true };
      },
      async verify() {
        throw new Error('companion connection lost');
      },
    },
  });
  const result = await remoteVerifyCommand(context, { command: 'npm test' });
  assert.equal(result.ok, false);
  assert.match(result.message, /no evidence was recorded/i);
  assert.deepEqual(posts, []);
});

test('an exit-code-less completion is treated as interrupted, not failed', async () => {
  const { remoteVerifyCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
  const { context, posts } = createCommandContext({
    workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
    trainingState: {
      selectedCardId: 'card-9',
      selectedCardStatus: 'active',
      selectedCardType: 'practice',
    },
    gateway: {
      async capabilities() {
        return { companionAvailable: true, verify: true };
      },
      async verify() {
        return { result: 'failed', command: 'npm test', exit_code: null, stdout: '', stderr: '' };
      },
    },
  });
  const result = await remoteVerifyCommand(context, { command: 'npm test' });
  assert.equal(result.ok, false);
  assert.match(result.message, /interrupted/i);
  assert.deepEqual(posts, []);
});
