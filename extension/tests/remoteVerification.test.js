'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock: loadMock } = require('./helpers/loadWithVscodeMock');
function uri(value) {
  const url = new URL(value);
  return { scheme: url.protocol.slice(0, -1), authority: url.host, path: url.pathname, fsPath: url.pathname,
    toString: () => url.toString(), with: (change) => { const next = new URL(url); next.pathname = change.path; return uri(next.toString()); } };
}
function loadWithVscodeMock(modulePath, mock) {
  return loadMock(modulePath, { FileType: { File: 1, Directory: 2 }, Uri: { parse: uri }, window: { activeTextEditor: { document: {
    uri: uri('vscode-remote://ssh-remote+owned/workspace/practice.py') } } }, ...mock });
}

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
  const messages = [];
  const hostState = {
    sessionId: overrides.sessionId,
    workspace: {
      workspaceFolder: '/workspace', workspaceUri: 'vscode-remote://ssh-remote+owned/workspace',
      workspaceScheme: 'vscode-remote', workspaceAuthority: 'ssh-remote+owned',
      ...(overrides.workspace ?? {}),
    },
    bootstrap: {
      workspaceTrainingState: overrides.trainingState ?? null,
      memory: { workspace: { trainerWorkspace: { status: 'managed', contextId: 'context-owned',
        canonicalProjectPath: 'vscode-remote://ssh-remote+owned/workspace' } } },
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
    workspaceGateway: {
      async capabilities() {
        return { companionAvailable: true, verify: true };
      },
      async runVerification(_spec, options) {
        options.onStart({ session_id: 'actual-run' });
        return {
          result: 'passed',
          state: 'completed',
          spec: { executable: 'npm', args: ['test'] },
          execution_location: 'remote:ssh-remote',
          started_at: '2026-01-01T00:00:00Z',
          finished_at: '2026-01-01T00:00:01Z',
          exit_code: 0,
          stdout: 'all tests passed',
          stderr: '',
          environment: { os: 'linux', arch: 'x64', node_version: 'v22' },
        };
      },
      async environment() { return { os: 'linux', canonical_workspace_uri: 'file:///workspace' }; },
      async stat() { return { type: 1 }; },
      async hashArtifact() { return 'a'.repeat(64); },
      ...overrides.gateway,
    },
    getHostState: () => hostState,
    getSessionId: () => overrides.sessionId,
    workbench: { async postMessage(message) { messages.push(message); } },
  };
  return { context, posts, messages };
}

test('remote evidence is bound to the starting card and changed identities cannot attest', async () => {
  const { remoteVerifyCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
  let finish;
  const { context, posts } = createCommandContext({ sessionId: 'start-session',
    workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
    trainingState: { selectedCardId: 'starting-card', selectedCardStatus: 'active', selectedCardType: 'practice' },
    gateway: { async capabilities() { return { companionAvailable: true, verify: true }; },
      async runVerification(_spec, options) {
        options.onStart({ session_id: 'actual-companion-run' });
        return new Promise(resolve => { finish = resolve; });
      } },
  });
  const running = remoteVerifyCommand(context, { executable: 'python', args: ['practice.py'] });
  while (!finish) await new Promise(resolve => setImmediate(resolve));
  context.getHostState().bootstrap.workspaceTrainingState.selectedCardId = 'later-card';
  finish({ state: 'completed', result: 'passed', exit_code: 0 });
  const result = await running;
  assert.equal(result.data.attestation, 'stale_scope');
  assert.deepEqual(posts, []);
  assert.doesNotMatch(result.message, /was attested/);
});

test('an ambiguous attestation response never claims recorded evidence or auto-resends', async () => {
  const { remoteVerifyCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
  const { context, messages } = createCommandContext({ sessionId: 's1',
    workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
    trainingState: { selectedCardId: 'card', selectedCardStatus: 'active', selectedCardType: 'practice' },
  });
  let requests = 0;
  context.sidecarClient.postJson = async () => { requests += 1; throw new Error('lost response'); };
  const result = await remoteVerifyCommand(context, { executable: 'python', args: ['practice.py'] });
  assert.equal(result.ok, true, 'the real process verdict remains a pass');
  assert.equal(result.data.attestation, 'undelivered');
  assert.equal(requests, 1);
  assert.match(result.message, /trainer-attestation-undelivered/);
  assert.equal(messages.filter(message => message.type === 'operation/status').length, 1);
});

test('active-file verification reserves the run before onStart and a second click cannot start another process', async () => {
  const { remoteVerifyActiveFileCommand, remoteVerifyCancelCommand } = loadWithVscodeMock(remoteVerificationModulePath, {
    window: { activeTextEditor: { document: { uri: uri('vscode-remote://ssh-remote+owned/workspace/practice.py') } } },
  });
  let start, finish, signal, calls = 0;
  const { context, posts, messages } = createCommandContext({ sessionId: 's1',
    workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
    trainingState: { selectedCardId: 'card', selectedCardStatus: 'active', selectedCardType: 'practice' },
    gateway: { async capabilities() { return { companionAvailable: true, verify: true }; },
      async runVerification(_spec, options) {
        calls += 1; signal = options.signal; start = options.onStart;
        return new Promise(resolve => { finish = resolve; });
      } },
  });
  assert.equal((await remoteVerifyActiveFileCommand(context)).ok, true);
  assert.equal((await remoteVerifyActiveFileCommand(context)).ok, false);
  assert.equal(calls, 1);
  start({ session_id: 'r1' });
  await remoteVerifyCancelCommand(context);
  assert.equal(signal.aborted, true);
  finish({ state: 'cancelled', exit_code: null, stdout: '', stderr: '' });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(posts, []);
  const finished = messages.find(message => message.type === 'remoteVerification/finished');
  assert.equal(finished.payload.state, 'cancelled');
  assert.equal('passed' in finished.payload, false);
});

test('remote verification requires a remote workspace window', async () => {
  const { remoteVerifyCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
  const { context, posts } = createCommandContext({ workspace: { isRemoteWorkspace: false } });
  const result = await remoteVerifyCommand(context, { executable: 'npm', args: ['test'] });
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
      async runVerification() {
        verifyCalls += 1;
        return { result: 'passed', state: 'completed', exit_code: 0 };
      },
    },
  });
  const result = await remoteVerifyCommand(context, { executable: 'npm', args: ['test'] });
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
  const result = await remoteVerifyCommand(context, { executable: 'npm', args: ['test'] });
  assert.equal(result.ok, true);
  assert.match(result.message, /attested/);
  assert.equal(posts.length, 1);
  const [, requestPath, body] = posts[0];
  assert.equal(requestPath, ATTEST_PATH);
  assert.equal(body.card_id, 'card-9');
  assert.equal(body.passed, true);
  assert.equal(body.evidence_source, 'test_runner');
  assert.deepEqual(body.verification_artifact, {
    workspace_uri: 'vscode-remote://ssh-remote+owned/workspace',
    artifact_uri: 'vscode-remote://ssh-remote+owned/workspace/practice.py',
    sha256: 'a'.repeat(64), companion_session_id: 'actual-run', execution_location: 'remote',
  });
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
      async runVerification(_spec, options) {
        options.onStart({ session_id: 'failed-run' });
        return {
          result: 'failed',
          state: 'completed',
          spec: { executable: 'npm', args: ['test'] },
          execution_location: 'remote:ssh-remote',
          started_at: '2026-01-01T00:00:00Z',
          finished_at: '2026-01-01T00:00:01Z',
          exit_code: 1,
          stdout: '',
          stderr: '1 test failed',
          environment: { os: 'linux', arch: 'x64', node_version: 'v22' },
        };
      },
    },
  });
  const result = await remoteVerifyCommand(context, { executable: 'npm', args: ['test'] });
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
      async runVerification() {
        throw new Error('companion connection lost');
      },
    },
  });
  const result = await remoteVerifyCommand(context, { executable: 'npm', args: ['test'] });
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
      async runVerification() {
        return {
          state: 'completed',
          spec: { executable: 'npm', args: ['test'] },
          execution_location: 'remote:ssh-remote',
          started_at: '2026-01-01T00:00:00Z',
          finished_at: '2026-01-01T00:00:01Z',
          exit_code: null,
          stdout: '',
          stderr: '',
          environment: { os: 'linux', arch: 'x64', node_version: 'v22' },
        };
      },
    },
  });
  const result = await remoteVerifyCommand(context, { executable: 'npm', args: ['test'] });
  assert.equal(result.ok, false);
  assert.match(result.message, /interrupted/i);
  assert.deepEqual(posts, []);
});

test('changed or unavailable remote bytes keep the real process verdict but cannot attest evidence', async () => {
  const { remoteVerifyCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
  for (const failure of ['changed', 'unknown', 'missing', 'foreign']) {
    const { context, posts } = createCommandContext({
      workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
      trainingState: { selectedCardId: 'card-bytes', selectedCardType: 'practice', selectedCardStatus: 'active' },
    });
    let hashes = 0;
    context.workspaceGateway.hashArtifact = async () => {
      hashes += 1;
      if (failure === 'unknown') throw new Error('lost remote hash');
      return (hashes > 1 && failure === 'changed' ? 'b' : 'a').repeat(64);
    };
    const payload = { executable: 'npm', args: ['test'] };
    if (failure === 'missing') context.getHostState().bootstrap.memory.workspace.trainerWorkspace.status = 'browse';
    if (failure === 'foreign') payload.artifactUri = 'vscode-remote://ssh-remote+foreign/workspace/practice.py';
    const result = await remoteVerifyCommand(context, payload);
    assert.equal(result.ok, true);
    assert.equal(result.data.attestation, 'artifact_unavailable');
    assert.equal(posts.length, 0);
    assert.doesNotMatch(result.message, /was attested/);
  }
});

test('active-file execution rejects foreign, outside, or canonical escaping Python files before any session starts', async () => {
  for (const failure of ['foreign', 'outside', 'symlink', 'root_changed']) {
    const file = uri(failure === 'foreign' ? 'vscode-remote://ssh-remote+other/workspace/practice.py'
      : failure === 'outside' ? 'vscode-remote://ssh-remote+owned/outside/practice.py'
      : 'vscode-remote://ssh-remote+owned/workspace/link.py');
    const { remoteVerifyActiveFileCommand } = loadWithVscodeMock(remoteVerificationModulePath, {
      window: { activeTextEditor: { document: { uri: file } } },
    });
    const { context, posts, messages } = createCommandContext({ workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' } });
    let starts = 0;
    context.workspaceGateway.runVerification = async () => { starts++; throw new Error('Should not start'); };
    if (failure === 'symlink') context.workspaceGateway.stat = async () => { throw new Error('Canonical outside file'); };
    if (failure === 'root_changed') context.workspaceGateway.environment = async () => ({ os: 'linux', canonical_workspace_uri: 'file:///changed-project' });
    const result = await remoteVerifyActiveFileCommand(context);
    assert.equal(result.ok, false, failure);
    assert.equal(starts, 0, failure);
    assert.deepEqual(posts, []);
    assert.equal(messages.some(m => m.type === 'remoteVerification/started'), false);
  }
});

test('an internal alias can execute when its canonical scope is confirmed even if its hash is temporarily unavailable', async () => {
  const file = uri('vscode-remote://ssh-remote+owned/workspace/internal-alias.py');
  const { remoteVerifyActiveFileCommand } = loadWithVscodeMock(remoteVerificationModulePath, {
    window: { activeTextEditor: { document: { uri: file } } },
  });
  const { context, posts, messages } = createCommandContext({ workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
    trainingState: { selectedCardId: 'card', selectedCardType: 'practice', selectedCardStatus: 'active' } });
  let starts = 0;
  context.workspaceGateway.hashArtifact = async () => { throw new Error('Hash temporarily unavailable'); };
  context.workspaceGateway.runVerification = async (_spec, options) => {
    starts++; options.onStart({ session_id: 'internal-run' });
    return { state: 'completed', result: 'passed', exit_code: 0, execution_location: 'remote:ssh-remote', stdout: '', stderr: '' };
  };
  assert.equal((await remoteVerifyActiveFileCommand(context)).ok, true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(starts, 1);
  assert.deepEqual(posts, []);
  const finished = messages.find(m => m.type === 'remoteVerification/finished');
  assert.equal(finished.payload.state, 'completed');
  assert.equal(finished.payload.passed, true);
  assert.match(finished.payload.summary, /no verification evidence/);
});

test('a canonical root change during execution invalidates equal-hash remote evidence', async () => {
  const { remoteVerifyCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
  const { context, posts } = createCommandContext({ workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
    trainingState: { selectedCardId: 'card', selectedCardType: 'practice', selectedCardStatus: 'active' } });
  let observations = 0;
  context.workspaceGateway.environment = async () => ({ os: 'linux', canonical_workspace_uri:
    ++observations === 1 ? 'file:///workspace' : 'file:///different-project' });
  const result = await remoteVerifyCommand(context, { executable: 'npm', args: ['test'] });
  assert.equal(result.ok, true);
  assert.equal(result.data.attestation, 'artifact_unavailable');
  assert.equal(posts.length, 0);
  assert.equal(observations, 2);
});

test('active-file UI target assertions reject malformed or different IDs before trust, gateway or process', async () => {
  for (const expectedCardId of [undefined, null, '', '   ', 9, {}, 'restored-scenario']) {
    const { remoteVerifyActiveFileCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
    let trustCalls = 0, gatewayCalls = 0;
    const { context, posts } = createCommandContext({
      sessionId: 'session-owned', workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
      trainingState: { selectedCardId: 'old-live-formal-card', selectedCardType: 'practice', selectedCardStatus: 'active' },
    });
    context.trustGuard.ensureTrusted = async () => { trustCalls += 1; return true; };
    context.workspaceGateway.capabilities = async () => { gatewayCalls += 1; return { companionAvailable: true, verify: true }; };
    const result = await remoteVerifyActiveFileCommand(context, { expectedCardId });
    assert.equal(result.ok, false, String(expectedCardId));
    assert.equal(result.message, '[[trainer-training-verification-target-mismatch]]');
    assert.equal(trustCalls, 0);
    assert.equal(gatewayCalls, 0);
    assert.deepEqual(posts, []);
  }
});

test('a UI target assertion cannot turn a flash, closed or missing host card into a live practice', async () => {
  for (const trainingState of [null,
    { selectedCardId: 'scenario', selectedCardType: 'flash', selectedCardStatus: 'active' },
    { selectedCardId: 'scenario', selectedCardType: 'practice', selectedCardStatus: 'fed_back' },
  ]) {
    const { remoteVerifyActiveFileCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
    const { context, posts } = createCommandContext({ workspace: { isRemoteWorkspace: true }, trainingState });
    let trustCalls = 0;
    context.trustGuard.ensureTrusted = async () => { trustCalls += 1; return true; };
    assert.equal((await remoteVerifyActiveFileCommand(context, { expectedCardId: 'scenario' })).ok, false);
    assert.equal(trustCalls, 0);
    assert.deepEqual(posts, []);
  }
});

async function waitForRemoteTerminal(messages) {
  const deadline = Date.now() + 2000;
  while (!messages.some(message => message.type === 'remoteVerification/finished')) {
    if (Date.now() > deadline) throw new Error('Remote stub did not settle');
    await new Promise(resolve => setImmediate(resolve));
  }
  await new Promise(resolve => setImmediate(resolve));
}

test('matching UI assertion and no-argument palette both keep host-owned event and attestation identities', async () => {
  for (const payload of [{ expectedCardId: ' live-card ' }, undefined]) {
    const { remoteVerifyActiveFileCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
    const { context, posts, messages } = createCommandContext({
      sessionId: 'session-owned', workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
      trainingState: { selectedCardId: 'live-card', selectedCardType: 'practice', selectedCardStatus: 'active' },
      gateway: { async runVerification(spec, options) {
        options.onStart({ session_id: 'host-owned-run' });
        options.onChunk({ stream: 'stdout', text: 'test output' });
        return { state: 'completed', result: 'passed', exit_code: 0, execution_location: 'remote:ssh-remote', stdout: 'pass', stderr: '' };
      } },
    });
    assert.equal((await remoteVerifyActiveFileCommand(context, payload)).ok, true);
    await waitForRemoteTerminal(messages);
    const lifecycle = messages.filter(message => message.type.startsWith('remoteVerification/'));
    assert.equal(lifecycle.length, 3);
    for (const message of lifecycle) assert.equal(message.payload.cardId, 'live-card');
    assert.equal(posts.length, 1);
    assert.equal(posts[0][2].card_id, 'live-card');
    assert.equal(posts[0][2].idempotency_key, 'remote-verify:host-owned-run:live-card');
    assert.equal(posts[0][2].verification_artifact.companion_session_id, 'host-owned-run');
  }
});

test('registered active-file command forwards the UI assertion instead of silently becoming a palette command', async () => {
  const configPath = path.resolve(__dirname, '../dist/extension/src/commands/registry.config.js');
  const { buildCommandRegistrations } = loadWithVscodeMock(configPath, {});
  const { context, posts } = createCommandContext({
    workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
    trainingState: { selectedCardId: 'old-live-formal-card', selectedCardType: 'practice', selectedCardStatus: 'active' },
  });
  let trustCalls = 0;
  context.trustGuard.ensureTrusted = async () => { trustCalls += 1; return true; };
  const registration = buildCommandRegistrations(context).find(entry => entry.commandId === 'trainer.remote.verifyActiveFile');
  assert.ok(registration);
  assert.equal((await registration.register(context, { expectedCardId: 'restored-scenario' })).ok, false);
  assert.equal(trustCalls, 0);
  assert.deepEqual(posts, []);
});

test('matching assertion keeps cancelled, timed-out and disconnected runs unknown without attestation', async () => {
  for (const state of ['cancelled', 'timed_out', 'connection_lost']) {
    const { remoteVerifyActiveFileCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
    const { context, posts, messages } = createCommandContext({
      workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' }, sessionId: 'owned-session',
      trainingState: { selectedCardId: 'live-card', selectedCardType: 'practice', selectedCardStatus: 'active' },
      gateway: { async runVerification(spec, options) {
        options.onStart({ session_id: 'interrupted-run' });
        return { state, exit_code: null, execution_location: 'remote:ssh-remote', stdout: '', stderr: '' };
      } },
    });
    assert.equal((await remoteVerifyActiveFileCommand(context, { expectedCardId: 'live-card' })).ok, true);
    await waitForRemoteTerminal(messages);
    const finished = messages.find(message => message.type === 'remoteVerification/finished').payload;
    assert.equal(finished.state, state);
    assert.equal(finished.cardId, 'live-card');
    assert.equal('passed' in finished, false);
    assert.deepEqual(posts, []);
  }
});

test('a matched expected card still cannot start after the host card changes during preflight', async () => {
  const { remoteVerifyActiveFileCommand } = loadWithVscodeMock(remoteVerificationModulePath, {});
  let runs = 0;
  const { context, posts } = createCommandContext({
    workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' }, sessionId: 'session-owned',
    trainingState: { selectedCardId: 'live-card', selectedCardType: 'practice', selectedCardStatus: 'active' },
  });
  context.workspaceGateway.capabilities = async () => {
    context.getHostState().bootstrap.workspaceTrainingState.selectedCardId = 'later-card';
    return { companionAvailable: true, verify: true };
  };
  context.workspaceGateway.runVerification = async () => { runs += 1; throw new Error('must not run'); };
  assert.equal((await remoteVerifyActiveFileCommand(context, { expectedCardId: 'live-card' })).ok, false);
  assert.equal(runs, 0);
  assert.deepEqual(posts, []);
});
