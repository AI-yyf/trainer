'use strict';

// Behavior tests for the remote verification session manager (protocol v2).
// The manager is TypeScript with only a type-only import, so the test compiles
// that single module to a temp dir and drives it with fake processes.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');

const repoRoot = path.resolve(__dirname, '..', '..');
const sourcePath = path.join(repoRoot, 'remote-extension', 'src', 'verificationSessions.ts');
const tscPath = path.join(repoRoot, 'extension', 'node_modules', 'typescript', 'bin', 'tsc');

let managerModulePromise;

function walkFor(rootPath, fileName) {
  for (const entry of fs.readdirSync(rootPath, { withFileTypes: true })) {
    const entryPath = path.join(rootPath, entry.name);
    if (entry.isDirectory()) {
      const found = walkFor(entryPath, fileName);
      if (found) return found;
    } else if (entry.name === fileName) {
      return entryPath;
    }
  }
  return undefined;
}

function loadManagerModule() {
  if (!managerModulePromise) {
    const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-vrf-sessions-'));
    execFileSync(process.execPath, [
      tscPath,
      sourcePath,
      '--outDir',
      outDir,
      '--module',
      'nodenext',
      '--moduleResolution',
      'nodenext',
      '--target',
      'es2022',
      '--skipLibCheck',
    ], { cwd: repoRoot });
    // tsc infers the repo root from the ../../shared type import, so the
    // emitted module nests; locate it.
    const emitted = walkFor(outDir, 'verificationSessions.js');
    managerModulePromise = import(pathToFileURL(emitted).href);
  }
  return managerModulePromise;
}

function fakeClock() {
  let current = 1_000_000;
  const timers = [];
  return {
    now: () => current,
    advance(ms) {
      current += ms;
      const due = timers.filter((timer) => !timer.done && timer.delayMs <= ms);
      for (const timer of due) {
        timer.done = true;
        timer.callback();
      }
    },
    setTimeoutFn(callback, delayMs) {
      const timer = { callback, delayMs, done: false };
      timers.push(timer);
      return timer;
    },
    clearTimeoutFn(timer) {
      timer.done = true;
    },
  };
}

function fakeSpawnFactory() {
  const spawns = [];
  return {
    spawns,
    spawnVerification(spec) {
      const spawn = {
        spec,
        killTreeCalls: 0,
        stdoutListeners: [],
        stderrListeners: [],
      };
      spawn.exited = new Promise((resolve, reject) => {
        spawn.exitResolve = resolve;
        spawn.exitReject = reject;
      });
      spawns.push(spawn);
      return {
        pid: 4000 + spawns.length,
        killTree: () => {
          spawn.killTreeCalls += 1;
        },
        exited: spawn.exited,
        onStdout: (listener) => spawn.stdoutListeners.push(listener),
        onStderr: (listener) => spawn.stderrListeners.push(listener),
      };
    },
  };
}

async function makeManager(overrides = {}) {
  const { createVerificationSessionManager } = await loadManagerModule();
  const clock = fakeClock();
  const fake = fakeSpawnFactory();
  const manager = createVerificationSessionManager({
    spawnVerification: fake.spawnVerification,
    environment: () => ({ os: 'linux', arch: 'x64', node_version: 'v22' }),
    now: clock.now,
    setTimeoutFn: clock.setTimeoutFn,
    clearTimeoutFn: clock.clearTimeoutFn,
    generateSessionId: () => `vrf-${fake.spawns.length + 1}`,
    ...overrides,
  });
  return { manager, clock, fake };
}

const PYTEST_SPEC = { executable: 'python', args: ['-m', 'pytest', '-q'], cwd: '/remote/ws' };

const flush = () => new Promise((resolve) => setImmediate(resolve));

test('a zero exit completes passed; a nonzero exit completes failed', async () => {
  const { manager, fake } = await makeManager();
  const started = await manager.startSession(PYTEST_SPEC);
  assert.equal(started.state, 'running');
  assert.equal(started.spec.executable, 'python');
  assert.equal(started.environment.os, 'linux');

  fake.spawns[0].exitResolve({ code: 0 });
  await flush();
  let status = await manager.status(started.session_id);
  assert.equal(status.state, 'completed');
  assert.equal(status.result, 'passed');
  assert.equal(status.exit_code, 0);
  assert.ok(status.finished_at);

  const failed = await manager.startSession({ executable: 'pytest', args: [] });
  fake.spawns[1].exitResolve({ code: 3 });
  await flush();
  status = await manager.status(failed.session_id);
  assert.equal(status.state, 'completed');
  assert.equal(status.result, 'failed');
  assert.equal(status.exit_code, 3);
});

test('status streams buffered output incrementally by offset', async () => {
  const { manager, fake } = await makeManager();
  const started = await manager.startSession(PYTEST_SPEC);
  const spawn = fake.spawns[0];
  spawn.stdoutListeners.forEach((listener) => listener('12 tests collected\n'));
  spawn.stdoutListeners.forEach((listener) => listener('......7..\n'));

  assert.equal(manager.status(started.session_id, 0, 0).stdout_chunk, '12 tests collected\n......7..\n');
  assert.equal(manager.status(started.session_id, 19, 0).stdout_chunk, '......7..\n');
  assert.equal(manager.status(started.session_id, 400, 0).stdout_chunk, '');

  spawn.exitResolve({ code: 0 });
  await flush();
  const final = await manager.status(started.session_id, 0, 0);
  assert.equal(final.state, 'completed');
  // Terminal status keeps answering with the full buffer (idempotent completion).
  assert.equal(final.stdout_total, '12 tests collected\n......7..\n'.length);
});

test('spawn rejection becomes spawn_failed with no exit code', async () => {
  const { manager, fake } = await makeManager();
  const started = await manager.startSession({ executable: 'definitely-missing', args: [] });
  fake.spawns[0].exitReject(new Error('spawn ENOENT'));
  await flush();
  const status = await manager.status(started.session_id);
  assert.equal(status.state, 'spawn_failed');
  assert.equal(status.exit_code, null);
  assert.match(status.error, /ENOENT/);
  assert.equal(status.result, undefined);
});

test('timeout fires the tree kill and reports timed_out', async () => {
  const { manager, clock, fake } = await makeManager({ defaultTimeoutMs: 5_000 });
  const started = await manager.startSession({ executable: 'pytest', args: [] });
  clock.advance(5_000);
  assert.equal(fake.spawns[0].killTreeCalls, 1);
  const status = await manager.status(started.session_id);
  assert.equal(status.state, 'timed_out');
  assert.match(status.error, /timed out after 5000ms/);
  assert.equal(status.exit_code, null);
});

test('spec timeout_ms overrides the default', async () => {
  const { manager, clock, fake } = await makeManager({ defaultTimeoutMs: 60_000 });
  await manager.startSession({ executable: 'pytest', args: [], timeout_ms: 1_500 });
  clock.advance(1_500);
  assert.equal(fake.spawns[0].killTreeCalls, 1);
});

test('cancel kills the tree once and stays cancelled even after a later exit', async () => {
  const { manager, fake } = await makeManager();
  const started = await manager.startSession(PYTEST_SPEC);
  const cancelled = await manager.cancel(started.session_id);
  assert.equal(cancelled.state, 'cancelled');
  assert.equal(fake.spawns[0].killTreeCalls, 1);

  // The real process may still report an exit afterwards; forward-only means
  // the cancelled state (and "no result") wins.
  fake.spawns[0].exitResolve({ code: 0 });
  const status = await manager.status(started.session_id);
  assert.equal(status.state, 'cancelled');
  assert.equal(status.result, undefined);

  const again = await manager.cancel(started.session_id);
  assert.equal(again.state, 'cancelled');
  assert.equal(fake.spawns[0].killTreeCalls, 1);
});

test('an identical running spec returns the same session (duplicate protection)', async () => {
  const { manager } = await makeManager();
  const first = await manager.startSession(PYTEST_SPEC);
  const second = await manager.startSession({ ...PYTEST_SPEC });
  assert.equal(second.session_id, first.session_id);

  const different = await manager.startSession({ executable: 'pytest', args: ['-k', 'other'] });
  assert.notEqual(different.session_id, first.session_id);
});

test('disposeAll marks running sessions connection_lost and kills their trees', async () => {
  const { manager, fake } = await makeManager();
  await manager.startSession(PYTEST_SPEC);
  manager.disposeAll();
  assert.equal(fake.spawns[0].killTreeCalls, 1);
  assert.throws(() => manager.status('vrf-1'), /Unknown verification session/);
});

test('output buffers keep the tail under the cap', async () => {
  const { manager, fake } = await makeManager();
  const started = await manager.startSession(PYTEST_SPEC);
  const spawn = fake.spawns[0];
  const bigChunk = 'x'.repeat(150_000);
  spawn.stdoutListeners.forEach((listener) => listener(bigChunk));
  spawn.stdoutListeners.forEach((listener) => listener(bigChunk));
  const status = manager.status(started.session_id, 0, 0);
  assert.equal(status.stdout_total <= 200_000, true);
  assert.equal(status.stdout_chunk.length, status.stdout_total);
  // The tail (not the head) is kept.
  assert.equal(status.stdout_chunk.endsWith('xxxx'), true);
});

test('terminal sessions are evicted oldest-first beyond maxSessions', async () => {
  const { manager, fake } = await makeManager({ maxSessions: 2 });
  const a = await manager.startSession({ executable: 'pytest', args: ['a'] });
  fake.spawns[0].exitResolve({ code: 0 });
  await flush();
  const b = await manager.startSession({ executable: 'pytest', args: ['b'] });
  fake.spawns[1].exitResolve({ code: 0 });
  await flush();
  const c = await manager.startSession({ executable: 'pytest', args: ['c'] });
  fake.spawns[2].exitResolve({ code: 0 });
  await flush();

  // The oldest terminal session (a) is gone; b and c remain.
  assert.throws(() => manager.status(a.session_id), /Unknown verification session/);
  assert.equal(manager.status(b.session_id).state, 'completed');
  assert.equal(manager.status(c.session_id).state, 'completed');
});
