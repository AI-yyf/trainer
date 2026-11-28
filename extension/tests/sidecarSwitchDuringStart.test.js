// Found in the installed VSIX on 2026-11-28, right after "choose a learning folder" was first offered
// on the Resources page: the binding succeeded, and the sidebar then showed a red "this step did not
// complete, try again". Choosing a folder switches the managed data folder, which stops the sidecar.
// When that stop lands on a sidecar that is still starting (the usual case on a cold start, where
// opening Resources has just started one), the launch reported "Sidecar failed to start and did not
// stop cleanly: Sidecar exited before readiness (signal=SIGTERM)" — a false failure for a process
// that was replaced on purpose. A request that needed that sidecar failed with it.
//
// Now a managed-data switch is the only sidecar operation in flight: requests wait for it, a
// launch it stopped is retried against the folder it installed, and the switch restarts the
// sidecar itself without waiting for its own gate (a plain restart() there deadlocked it).
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const modulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'sidecarProcessManager.js',
);

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function reserveFreePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const { port } = server.address();
  await new Promise((resolve) => server.close(resolve));
  return port;
}

function createManager(tempRoot) {
  const vscodeMock = {
    ExtensionMode: { Production: 1, Development: 2 },
    workspace: {
      workspaceFolders: [{ uri: { fsPath: path.join(tempRoot, 'workspace') } }],
      getConfiguration() {
        return { get() { return undefined; } };
      },
    },
    EventEmitter: class {
      event() { return { dispose() {} }; }
      fire() {}
      dispose() {}
    },
  };
  const { SidecarProcessManager } = loadWithVscodeMock(modulePath, vscodeMock);
  const extensionContext = {
    extensionPath: path.join(tempRoot, 'extension'),
    extensionMode: 1,
    globalStorageUri: { fsPath: path.join(tempRoot, 'storage') },
  };
  const manager = new SidecarProcessManager(extensionContext, {
    append() {},
    appendLine() {},
    replace() {},
  });
  return manager;
}

/** A child that never answers /health: it stands for a sidecar that is still starting. */
const SILENT = {
  label: 'silent',
  command: process.execPath,
  args: ['-e', 'process.stdin.resume()'],
  cwd: process.cwd(),
};
/** A child that answers every request with JSON on the port the manager hands it. */
const HEALTHY = {
  label: 'healthy',
  command: process.execPath,
  args: [
    '-e',
    "require('http').createServer((request, response) => { response.setHeader('content-type', 'application/json'); response.end('{\"status\":\"ok\"}'); }).listen(Number(process.env.TRAINER_PORT), '127.0.0.1', () => process.stdin.resume());",
  ],
  cwd: process.cwd(),
};

/** Each launch takes the next candidate in `launches` (the last one repeats). */
async function prepareLaunches(manager, launches) {
  const port = await reserveFreePort();
  manager.resolveLaunchPort = async () => port;
  let attempt = 0;
  manager.buildLaunchCandidates = () => [launches[Math.min(attempt++, launches.length - 1)]];
  return port;
}

const withTempRoot = async (run) => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-switch-'));
  const manager = createManager(tempRoot);
  try {
    return await run(manager);
  } finally {
    manager.dispose();
    await delay(200);
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
};

test('a stop that lands on a starting sidecar is not reported as a failed start', async () => {
  await withTempRoot(async (manager) => {
    await prepareLaunches(manager, [SILENT]);

    const pending = manager.ensureRunning();
    await delay(500);
    assert.equal(manager.getStatus().lifecycle, 'starting');

    await manager.stop();
    await assert.rejects(pending, (error) => error && error.name === 'SidecarStartInterruptedError');

    const status = manager.getStatus();
    assert.equal(status.lifecycle, 'stopped');
    assert.doesNotMatch(String(status.detail), /failed to start|did not stop cleanly/);
  });
});

test('a request that needs the sidecar waits for a managed-data switch and then runs against the new folder', async () => {
  await withTempRoot(async (manager) => {
    await prepareLaunches(manager, [SILENT, HEALTHY]);
    const order = [];

    const pending = manager.ensureRunning();
    await delay(500);
    assert.equal(manager.getStatus().lifecycle, 'starting');

    const switching = manager.withManagedDataSwitch(async () => {
      order.push('switch:stop');
      await manager.stop();
      await delay(600);
      order.push('switch:done');
    });
    // A second request arrives while the switch is open; it must not start a sidecar either.
    await delay(150);
    const late = manager.ensureRunning();

    const status = await pending;
    await switching;
    const lateStatus = await late;
    order.push('requests:resolved');

    assert.equal(status.lifecycle, 'ready');
    assert.equal(lateStatus.lifecycle, 'ready');
    assert.deepEqual(order, ['switch:stop', 'switch:done', 'requests:resolved']);
  });
});

test('without a switch a stopped launch is not retried behind the caller\'s back', async () => {
  await withTempRoot(async (manager) => {
    const { SidecarStartInterruptedError } = require(modulePath);
    let starts = 0;
    manager.resolveLaunchPort = async () => reserveFreePort();
    manager.buildLaunchCandidates = () => {
      starts += 1;
      return [SILENT];
    };

    const pending = manager.ensureRunning();
    await delay(500);
    await manager.stop();
    await assert.rejects(pending, (error) => error instanceof SidecarStartInterruptedError);
    await delay(400);

    assert.equal(starts, 1);
    assert.equal(manager.getStatus().lifecycle, 'stopped');
  });
});

test('the switch restarts the sidecar itself without waiting for its own gate, and waiting requests join the result', async () => {
  await withTempRoot(async (manager) => {
    await prepareLaunches(manager, [SILENT, HEALTHY]);

    const pending = manager.ensureRunning();
    await delay(500);
    assert.equal(manager.getStatus().lifecycle, 'starting');

    const switching = manager.withManagedDataSwitch(async () => {
      await manager.stop();
      const status = await manager.ensureRunningAfterManagedDataSwitch();
      assert.equal(status.lifecycle, 'ready');
    });
    const status = await pending;
    await switching;

    assert.equal(status.lifecycle, 'ready');
    assert.equal(manager.getStatus().lifecycle, 'ready');
  });
});
