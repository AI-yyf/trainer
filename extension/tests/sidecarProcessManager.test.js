'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const sidecarProcessManagerModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'sidecarProcessManager.js',
);

function createEventEmitter() {
  return class EventEmitter {
    constructor() {
      this.event = () => ({ dispose() {} });
    }

    fire() {}

    dispose() {}
  };
}

function createOutputChannel() {
  return {
    append() {},
    appendLine() {},
  };
}

function writeFile(targetPath, content = '') {
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.writeFileSync(targetPath, content, 'utf8');
}

function bundledExecutableName() {
  return process.platform === 'win32' ? 'trainer-sidecar.exe' : 'trainer-sidecar';
}

function writeBundledBinaryManifest(extensionRoot, { platform, entryName } = {}) {
  const targetPlatform = platform ?? `${process.platform}-${process.arch}`;
  writeFile(
    path.join(extensionRoot, 'bundled', 'bin', targetPlatform, 'trainer-sidecar-manifest.json'),
    `${JSON.stringify({
      manifestVersion: 1,
      platform: targetPlatform,
      entryName: entryName ?? bundledExecutableName(),
      sourceSnapshot: { fileCount: 1, sha256: 'a'.repeat(64) },
    })}\n`,
  );
}

function expectedSystemPythonLabels() {
  return process.platform === 'win32'
    ? ['system-python']
    : ['system-python3.12', 'system-python3', 'system-python'];
}

const extensionModes = {
  Production: 1,
  Development: 2,
};

function createManagerFixture({
  workspaceFolder,
  extensionPath,
  configuredSidecarPort,
  extensionMode = extensionModes.Production,
}) {
  const vscodeMock = {
    ExtensionMode: extensionModes,
    workspace: {
      workspaceFolders: workspaceFolder ? [{ uri: { fsPath: workspaceFolder } }] : undefined,
      getConfiguration(section) {
        if (section !== 'trainer') {
          return { get() { return undefined; } };
        }
        return {
          get(key) {
            return key === 'sidecar.port' ? configuredSidecarPort : undefined;
          },
        };
      },
    },
    EventEmitter: createEventEmitter(),
  };
  const { SidecarProcessManager } = loadWithVscodeMock(
    sidecarProcessManagerModulePath,
    vscodeMock,
  );
  const extensionContext = {
    extensionPath,
    extensionMode,
    globalStorageUri: {
      fsPath: path.join(extensionPath, '.tmp-test-storage'),
    },
  };
  return new SidecarProcessManager(extensionContext, createOutputChannel());
}

async function reserveFreePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  assert.equal(typeof address, 'object');
  assert.ok(address && 'port' in address);
  const { port } = address;
  await new Promise((resolve) => server.close(resolve));
  return port;
}

test('SidecarProcessManager uses the configured sidecar port when it is available', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-configured-port-'));
  try {
    const preferredPort = await reserveFreePort();
    const manager = createManagerFixture({
      workspaceFolder: path.join(tempRoot, 'workspace'),
      extensionPath: path.join(tempRoot, 'extension'),
      configuredSidecarPort: preferredPort,
    });
    let launchedPort;
    manager.buildLaunchCandidates = () => [{ label: 'test', command: 'test', args: [], cwd: tempRoot }];
    manager.launchCandidate = async (_candidate, port) => {
      launchedPort = port;
      return { lifecycle: 'ready', host: '127.0.0.1', port, canStart: true };
    };

    const status = await manager.start();

    assert.equal(launchedPort, preferredPort);
    assert.equal(status.port, preferredPort);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager falls back when the configured sidecar port is occupied', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-port-fallback-'));
  const occupiedServer = net.createServer();
  try {
    await new Promise((resolve, reject) => {
      occupiedServer.once('error', reject);
      occupiedServer.listen(0, '127.0.0.1', resolve);
    });
    const address = occupiedServer.address();
    assert.equal(typeof address, 'object');
    assert.ok(address && 'port' in address);
    const occupiedPort = address.port;
    const manager = createManagerFixture({
      workspaceFolder: path.join(tempRoot, 'workspace'),
      extensionPath: path.join(tempRoot, 'extension'),
      configuredSidecarPort: occupiedPort,
    });
    let launchedPort;
    manager.buildLaunchCandidates = () => [{ label: 'test', command: 'test', args: [], cwd: tempRoot }];
    manager.launchCandidate = async (_candidate, port) => {
      launchedPort = port;
      return { lifecycle: 'ready', host: '127.0.0.1', port, canStart: true };
    };

    const status = await manager.start();

    assert.notEqual(launchedPort, occupiedPort);
    assert.ok(launchedPort >= 34891 && launchedPort <= 34911);
    assert.equal(status.port, launchedPort);
  } finally {
    await new Promise((resolve) => occupiedServer.close(resolve));
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager uses workspace source candidates ahead of bundled binary only in development', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-order-'));
  try {
    const workspaceRoot = path.join(tempRoot, 'workspace');
    const extensionRoot = path.join(workspaceRoot, 'extension');
    const workspaceServer = path.join(workspaceRoot, 'server');
    const bundledBinary = path.join(
      extensionRoot,
      'bundled',
      'bin',
      `${process.platform}-${process.arch}`,
      bundledExecutableName(),
    );

    writeFile(path.join(workspaceServer, 'run_sidecar.py'), 'print("workspace sidecar")\n');
    writeFile(bundledBinary, '');
    writeBundledBinaryManifest(extensionRoot);

    const manager = createManagerFixture({
      workspaceFolder: workspaceRoot,
      extensionPath: extensionRoot,
      extensionMode: extensionModes.Development,
    });

    const candidates = manager.buildLaunchCandidates(34891);
    assert.equal(candidates.length, expectedSystemPythonLabels().length + 2);
    assert.equal(candidates[0].label, 'uv-run');
    assert.deepEqual(
      candidates.slice(1, -1).map((candidate) => candidate.label),
      expectedSystemPythonLabels(),
    );
    assert.equal(candidates[candidates.length - 1].label, 'bundled-binary');
    assert.equal(candidates[0].cwd, workspaceServer);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager excludes workspace source candidates in production', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-production-order-'));
  try {
    const workspaceRoot = path.join(tempRoot, 'workspace');
    const extensionRoot = path.join(workspaceRoot, 'extension');
    const workspaceServer = path.join(workspaceRoot, 'server');
    const bundledServer = path.join(extensionRoot, 'bundled', 'server');
    const bundledBinary = path.join(
      extensionRoot,
      'bundled',
      'bin',
      `${process.platform}-${process.arch}`,
      bundledExecutableName(),
    );

    writeFile(path.join(workspaceServer, 'run_sidecar.py'), 'print("workspace sidecar")\n');
    writeFile(path.join(bundledServer, 'run_sidecar.py'), 'print("bundled sidecar")\n');
    writeFile(bundledBinary, '');
    writeBundledBinaryManifest(extensionRoot);

    const manager = createManagerFixture({
      workspaceFolder: workspaceRoot,
      extensionPath: extensionRoot,
    });
    const candidates = manager.buildLaunchCandidates(34891);

    assert.deepEqual(candidates.map((candidate) => candidate.label), ['bundled-binary']);
    assert.ok(candidates.every((candidate) => candidate.cwd !== workspaceServer));
    assert.doesNotMatch(JSON.stringify(candidates), /workspace[\\/]server/);

    manager.extensionContext.extensionMode = undefined;
    const candidatesWithoutMode = manager.buildLaunchCandidates(34891);
    assert.deepEqual(candidatesWithoutMode.map((candidate) => candidate.label), ['bundled-binary']);
    assert.doesNotMatch(JSON.stringify(candidatesWithoutMode), /workspace[\\/]server/);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager keeps bundled binary first when only bundled server assets are available in development', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-bundled-'));
  try {
    const extensionRoot = path.join(tempRoot, 'extension');
    const bundledServer = path.join(extensionRoot, 'bundled', 'server');
    const bundledBinary = path.join(
      extensionRoot,
      'bundled',
      'bin',
      `${process.platform}-${process.arch}`,
      bundledExecutableName(),
    );

    writeFile(path.join(bundledServer, 'run_sidecar.py'), 'print("bundled sidecar")\n');
    writeFile(bundledBinary, '');
    writeBundledBinaryManifest(extensionRoot);

    const manager = createManagerFixture({
      workspaceFolder: undefined,
      extensionPath: extensionRoot,
      extensionMode: extensionModes.Development,
    });

    const candidates = manager.buildLaunchCandidates(34891);
    assert.equal(candidates.length, expectedSystemPythonLabels().length + 2);
    assert.equal(candidates[0].label, 'bundled-binary');
    assert.equal(candidates[1].label, 'uv-run');
    assert.deepEqual(
      candidates.slice(2).map((candidate) => candidate.label),
      expectedSystemPythonLabels(),
    );
    assert.equal(candidates[1].cwd, bundledServer);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager does not fall back to source runtimes in production when the bundled binary is missing', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-missing-binary-'));
  try {
    const extensionRoot = path.join(tempRoot, 'extension');
    const bundledServer = path.join(extensionRoot, 'bundled', 'server');

    writeFile(path.join(bundledServer, 'run_sidecar.py'), 'print("bundled sidecar")\n');
    writeBundledBinaryManifest(extensionRoot);

    const manager = createManagerFixture({
      workspaceFolder: undefined,
      extensionPath: extensionRoot,
    });

    assert.deepEqual(manager.buildLaunchCandidates(34891), []);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager does not fall back to an unpackaged Python runtime for an installed VSIX', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-untrusted-binary-'));
  try {
    const extensionRoot = path.join(tempRoot, 'extension');
    const bundledServer = path.join(extensionRoot, 'bundled', 'server');
    const bundledBinary = path.join(
      extensionRoot,
      'bundled',
      'bin',
      `${process.platform}-${process.arch}`,
      bundledExecutableName(),
    );

    writeFile(path.join(bundledServer, 'run_sidecar.py'), 'print("bundled sidecar")\n');
    writeFile(bundledBinary, '');

    const manager = createManagerFixture({
      workspaceFolder: undefined,
      extensionPath: extensionRoot,
    });
    const candidates = manager.buildLaunchCandidates(34891);

    assert.deepEqual(candidates, []);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager does not use a mismatched bundled runtime', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-mismatched-binary-'));
  try {
    const extensionRoot = path.join(tempRoot, 'extension');
    const bundledServer = path.join(extensionRoot, 'bundled', 'server');
    const bundledBinary = path.join(
      extensionRoot,
      'bundled',
      'bin',
      `${process.platform}-${process.arch}`,
      bundledExecutableName(),
    );

    writeFile(path.join(bundledServer, 'run_sidecar.py'), 'print("bundled sidecar")\n');
    writeFile(bundledBinary, '');
    writeBundledBinaryManifest(extensionRoot, { platform: 'different-platform' });

    const manager = createManagerFixture({
      workspaceFolder: undefined,
      extensionPath: extensionRoot,
    });
    const candidates = manager.buildLaunchCandidates(34891);

    assert.deepEqual(candidates, []);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager gives installed VSIX users a package recovery action', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-missing-runtime-'));
  try {
    const extensionRoot = path.join(tempRoot, 'extension');
    writeFile(
      path.join(extensionRoot, 'bundled', 'server', 'run_sidecar.py'),
      'print("bundled sidecar")\n',
    );
    const manager = createManagerFixture({
      workspaceFolder: undefined,
      extensionPath: extensionRoot,
    });

    const status = await manager.ensureRunning();

    assert.equal(status.lifecycle, 'unavailable');
    assert.equal(status.canStart, false);
    assert.match(status.detail, /does not include a verified runtime/i);
    assert.match(status.detail, /Install the Trainer VSIX built for/i);
    assert.doesNotMatch(status.detail, /uv|python3|pip/i);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager keeps an unresponsive live child instead of starting a second writer', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-health-restart-'));
  try {
    const manager = createManagerFixture({
      workspaceFolder: path.join(tempRoot, 'workspace'),
      extensionPath: path.join(tempRoot, 'extension'),
    });
    manager.status = {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      pid: 101,
      canStart: true,
    };
    manager.process = { exitCode: null };
    manager.client = {
      async probeHealth() {
        return false;
      },
    };

    let startCalls = 0;
    manager.stop = async () => {
      throw new Error('ensureRunning must not stop a live sidecar after one failed health probe');
    };
    manager.start = async () => {
      startCalls += 1;
      return {
        lifecycle: 'ready',
        host: '127.0.0.1',
        port: 34892,
        canStart: true,
      };
    };

    const status = await manager.ensureRunning();

    assert.equal(startCalls, 0);
    assert.equal(status.lifecycle, 'ready');
    assert.equal(manager.process.exitCode, null);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager serializes concurrent health failures without replacing the live child', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-health-concurrent-'));
  try {
    const manager = createManagerFixture({
      workspaceFolder: path.join(tempRoot, 'workspace'),
      extensionPath: path.join(tempRoot, 'extension'),
    });
    manager.status = {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      pid: 101,
      canStart: true,
    };
    manager.process = { exitCode: null };
    manager.client = {
      async probeHealth() {
        return false;
      },
    };

    let startCalls = 0;
    manager.stop = async () => {
      throw new Error('ensureRunning must not stop a live sidecar after one failed health probe');
    };
    manager.start = async () => {
      startCalls += 1;
      return {
        lifecycle: 'ready',
        host: '127.0.0.1',
        port: 34892,
        canStart: true,
      };
    };

    const [first, second] = await Promise.all([manager.ensureRunning(), manager.ensureRunning()]);

    assert.equal(startCalls, 0);
    assert.equal(first.lifecycle, 'ready');
    assert.equal(second.lifecycle, 'ready');
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager does not launch a replacement when an explicit restart cannot stop the child', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-health-stop-failure-'));
  try {
    const manager = createManagerFixture({
      workspaceFolder: path.join(tempRoot, 'workspace'),
      extensionPath: path.join(tempRoot, 'extension'),
    });
    manager.status = {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      pid: 101,
      canStart: true,
    };
    manager.process = { exitCode: null };
    let startCalls = 0;
    manager.stop = async () => {
      throw new Error('Sidecar did not stop before the workspace data operation timed out.');
    };
    manager.start = async () => {
      startCalls += 1;
      return {
        lifecycle: 'ready',
        host: '127.0.0.1',
        port: 34892,
        canStart: true,
      };
    };

    await assert.rejects(() => manager.restart(), /did not stop/);
    assert.equal(startCalls, 0);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager starts a replacement only after the tracked child has exited', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-health-exited-'));
  try {
    const manager = createManagerFixture({
      workspaceFolder: path.join(tempRoot, 'workspace'),
      extensionPath: path.join(tempRoot, 'extension'),
    });
    manager.status = {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      pid: 101,
      canStart: true,
    };
    manager.process = { exitCode: 1 };
    manager.client = {
      async probeHealth() {
        return false;
      },
    };

    let startCalls = 0;
    manager.start = async () => {
      startCalls += 1;
      return {
        lifecycle: 'ready',
        host: '127.0.0.1',
        port: 34892,
        canStart: true,
      };
    };

    const status = await manager.ensureRunning();

    assert.equal(startCalls, 1);
    assert.equal(status.port, 34892);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager does not try another launch candidate while a failed candidate remains live', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-sidecar-candidate-linger-'));
  try {
    const manager = createManagerFixture({
      workspaceFolder: path.join(tempRoot, 'workspace'),
      extensionPath: path.join(tempRoot, 'extension'),
    });
    manager.buildLaunchCandidates = () => [
      { label: 'first', command: 'first', args: [], cwd: tempRoot },
      { label: 'second', command: 'second', args: [], cwd: tempRoot },
    ];

    const attempts = [];
    manager.launchCandidate = async (candidate) => {
      attempts.push(candidate.label);
      manager.process = { exitCode: null };
      throw new Error('The candidate process could not be terminated.');
    };

    const status = await manager.start();

    assert.deepEqual(attempts, ['first']);
    assert.equal(status.lifecycle, 'error');
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager can switch to a custom managed data folder and copy existing data into an empty target', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-managed-data-copy-'));
  try {
    const workspaceRoot = path.join(tempRoot, 'workspace');
    const extensionRoot = path.join(workspaceRoot, 'extension');
    const manager = createManagerFixture({
      workspaceFolder: workspaceRoot,
      extensionPath: extensionRoot,
    });

    const defaultFolder = manager.getManagedDataFolderSnapshot(workspaceRoot).effectivePath;
    writeFile(path.join(defaultFolder, 'state', 'memory.json'), '{"ok":true}\n');
    const customFolder = path.join(tempRoot, 'trainer-data-custom');

    const result = await manager.configureManagedDataFolder(customFolder, workspaceRoot);

    assert.equal(result.changed, true);
    assert.equal(result.migration, 'copied');
    assert.equal(result.next.source, 'custom');
    assert.equal(result.next.effectivePath, path.resolve(customFolder));
    assert.equal(
      fs.readFileSync(path.join(customFolder, 'state', 'memory.json'), 'utf8'),
      '{"ok":true}\n',
    );
    assert.equal(
      fs.readFileSync(path.join(defaultFolder, 'state', 'memory.json'), 'utf8'),
      '{"ok":true}\n',
    );
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager rejects an ordinary managed data switch to a non-empty target', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-managed-data-skip-'));
  try {
    const workspaceRoot = path.join(tempRoot, 'workspace');
    const extensionRoot = path.join(workspaceRoot, 'extension');
    const manager = createManagerFixture({
      workspaceFolder: workspaceRoot,
      extensionPath: extensionRoot,
    });

    const defaultFolder = manager.getManagedDataFolderSnapshot(workspaceRoot).effectivePath;
    writeFile(path.join(defaultFolder, 'state', 'memory.json'), '{"from":"default"}\n');
    const customFolder = path.join(tempRoot, 'trainer-data-existing');
    writeFile(path.join(customFolder, 'existing.txt'), 'keep me\n');

    await assert.rejects(
      () => manager.configureManagedDataFolder(customFolder, workspaceRoot),
      /must be empty/,
    );
    assert.equal(manager.getManagedDataFolderSnapshot(workspaceRoot).effectivePath, defaultFolder);
    assert.equal(fs.existsSync(path.join(customFolder, 'state', 'memory.json')), false);
    assert.equal(
      fs.readFileSync(path.join(customFolder, 'existing.txt'), 'utf8'),
      'keep me\n',
    );
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager allows a verified recovery target to take over without recopying it', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-managed-data-recovery-'));
  try {
    const workspaceRoot = path.join(tempRoot, 'workspace');
    const extensionRoot = path.join(workspaceRoot, 'extension');
    const manager = createManagerFixture({
      workspaceFolder: workspaceRoot,
      extensionPath: extensionRoot,
    });
    const defaultFolder = manager.getManagedDataFolderSnapshot(workspaceRoot).effectivePath;
    writeFile(path.join(defaultFolder, 'state', 'memory.json'), '{"from":"default"}\n');
    const recoveredFolder = path.join(tempRoot, 'recovered-runtime');
    writeFile(path.join(recoveredFolder, 'state', 'memory.json'), '{"from":"backup"}\n');

    const result = await manager.configureManagedDataFolder(recoveredFolder, workspaceRoot, {
      allowExistingTarget: true,
    });

    assert.equal(result.changed, true);
    assert.equal(result.migration, 'skipped_nonempty_target');
    assert.equal(result.next.effectivePath, path.resolve(recoveredFolder));
    assert.equal(
      fs.readFileSync(path.join(recoveredFolder, 'state', 'memory.json'), 'utf8'),
      '{"from":"backup"}\n',
    );
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('SidecarProcessManager rejects a managed data target nested inside the current data directory', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-managed-data-nested-'));
  try {
    const workspaceRoot = path.join(tempRoot, 'workspace');
    const extensionRoot = path.join(workspaceRoot, 'extension');
    const manager = createManagerFixture({
      workspaceFolder: workspaceRoot,
      extensionPath: extensionRoot,
    });
    const currentFolder = manager.getManagedDataFolderSnapshot(workspaceRoot).effectivePath;
    const nestedTarget = path.join(currentFolder, 'nested-target');

    await assert.rejects(
      () => manager.configureManagedDataFolder(nestedTarget, workspaceRoot),
      /cannot be nested/,
    );
    assert.equal(manager.getManagedDataFolderSnapshot(workspaceRoot).effectivePath, currentFolder);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});
