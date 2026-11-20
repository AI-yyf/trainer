'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
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

function createManager(tempRoot, workspaceFolder) {
  const vscodeMock = {
    ExtensionMode: { Production: 1, Development: 2 },
    workspace: {
      workspaceFolders: workspaceFolder ? [{ uri: { fsPath: workspaceFolder } }] : undefined,
      getConfiguration() {
        return { get() { return undefined; } };
      },
    },
    EventEmitter: class EventEmitter {
      constructor() {
        this.event = () => ({ dispose() {} });
      }
      fire() {}
      dispose() {}
    },
  };
  const { SidecarProcessManager } = loadWithVscodeMock(
    sidecarProcessManagerModulePath,
    vscodeMock,
  );
  const globalStoragePath = path.join(tempRoot, 'globalStorage');
  const extensionContext = {
    extensionPath: path.join(tempRoot, 'extension'),
    extensionMode: 1,
    globalStorageUri: { fsPath: globalStoragePath },
  };
  const outputChannel = { append() {}, appendLine() {}, replace() {} };
  return {
    manager: new SidecarProcessManager(extensionContext, outputChannel),
    globalStoragePath,
  };
}

test('SidecarProcessManager defaults data dir to <libraryRoot>/.trainer/runtime when rootPath is set', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-unified-root-'));
  try {
    const projectDir = path.join(tempRoot, 'code-repo');
    const libraryRoot = path.join(tempRoot, 'library-root');
    fs.mkdirSync(projectDir, { recursive: true });
    fs.mkdirSync(libraryRoot, { recursive: true });

    const { manager, globalStoragePath } = createManager(tempRoot, projectDir);
    await manager.setManagedDataRootScope({
      rootId: 'root-abc',
      rootPath: libraryRoot,
      legacyWorkspaceFolder: projectDir,
    });

    const expectedRuntimeDir = fs.realpathSync(libraryRoot);
    const snapshot = manager.getManagedDataFolderSnapshot(projectDir);
    assert.equal(
      fs.realpathSync(snapshot.effectivePath),
      path.join(expectedRuntimeDir, '.trainer', 'runtime'),
    );
    assert.equal(snapshot.effectivePath.startsWith(globalStoragePath), false);
    assert.equal(fs.existsSync(path.join(projectDir, '.trainer')), false);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('resetManagedDataFolder keeps data inside <libraryRoot>/.trainer/runtime', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-unified-reset-'));
  try {
    const projectDir = path.join(tempRoot, 'code-repo');
    const libraryRoot = path.join(tempRoot, 'library-root');
    const customDir = path.join(tempRoot, 'custom-dir');
    fs.mkdirSync(projectDir, { recursive: true });
    fs.mkdirSync(libraryRoot, { recursive: true });

    const { manager } = createManager(tempRoot, projectDir);
    await manager.setManagedDataRootScope({
      rootId: 'root-reset',
      rootPath: libraryRoot,
      legacyWorkspaceFolder: projectDir,
    });
    await manager.configureManagedDataFolder(customDir, projectDir, { copyExistingData: false });
    const resetResult = await manager.resetManagedDataFolder(projectDir, {
      allowExistingTarget: true,
      copyExistingData: false,
    });

    assert.equal(
      fs.realpathSync(resetResult.next.effectivePath),
      path.join(fs.realpathSync(libraryRoot), '.trainer', 'runtime'),
    );
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('legacy trainer.db in globalStorage migrates to <libraryRoot>/.trainer/runtime without overwriting existing data', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-unified-migrate-'));
  try {
    const projectDir = path.join(tempRoot, 'code-repo');
    const libraryRoot = path.join(tempRoot, 'library-root');
    fs.mkdirSync(projectDir, { recursive: true });
    fs.mkdirSync(libraryRoot, { recursive: true });

    const { manager, globalStoragePath } = createManager(tempRoot, projectDir);
    const legacySidecarDir = path.join(globalStoragePath, 'sidecar');
    fs.mkdirSync(path.join(legacySidecarDir, 'qdrant'), { recursive: true });
    fs.writeFileSync(path.join(legacySidecarDir, 'trainer.db'), 'legacy-sqlite-bytes', 'utf8');
    fs.writeFileSync(path.join(legacySidecarDir, 'qdrant', 'index.bin'), 'vec', 'utf8');

    await manager.setManagedDataRootScope({
      rootId: 'root-migrate',
      rootPath: libraryRoot,
      legacyWorkspaceFolder: projectDir,
    });

    const targetRuntime = path.join(libraryRoot, '.trainer', 'runtime');
    assert.equal(fs.readFileSync(path.join(targetRuntime, 'trainer.db'), 'utf8'), 'legacy-sqlite-bytes');
    assert.equal(fs.readFileSync(path.join(targetRuntime, 'qdrant', 'index.bin'), 'utf8'), 'vec');

    // Existing trainer.db under <libraryRoot> must never be overwritten by an older legacy copy.
    fs.writeFileSync(path.join(targetRuntime, 'trainer.db'), 'newer-library-db', 'utf8');
    fs.writeFileSync(path.join(legacySidecarDir, 'trainer.db'), 'stale-legacy-db', 'utf8');
    await manager.setManagedDataRootScope({
      rootId: 'root-migrate-2',
      rootPath: libraryRoot,
      legacyWorkspaceFolder: projectDir,
    });
    assert.equal(fs.readFileSync(path.join(targetRuntime, 'trainer.db'), 'utf8'), 'newer-library-db');
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});
