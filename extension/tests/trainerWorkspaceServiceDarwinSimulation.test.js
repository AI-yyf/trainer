'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const hostPath = require('node:path');

// ---------------------------------------------------------------------------
// Darwin-semantics simulation for the workspace recovery runtime-data checks.
//
// On macOS, os.tmpdir() returns /var/folders/... and /var is a system-level
// symlink to /private/var, so fs.realpath() returns a path that differs from
// the lexical input even for a perfectly valid directory. The external
// runtime-data safety assertion must not treat that canonicalization as a
// redirect, otherwise backupWorkspace/migrateWorkspaceRoot reject the same
// valid external sidecar data folder that the POSIX rebase test fixtures
// create under the OS temp directory (they pass on Windows and failed on
// macOS).
//
// This file reproduces those semantics on every host:
//   * `node:path` is swapped for `node:path/posix` for the module under test,
//   * `fs.realpath` reports the macOS-style canonical form for paths inside
//     the simulation root (a '/private' prefix, like /var/... -> /private/var),
//   * `process.platform` reads as 'darwin' inside the service under test.
//
// Before the fix, the external-data-root assertion threw
// "must not resolve through a symbolic link or junction" for the valid
// fixture below; after the fix the rebase flow completes.
// ---------------------------------------------------------------------------

const SIM_ROOT = `/tmp/trainer-darwin-sim-${process.pid}-${Date.now().toString(36)}`;
const WINDOWS_DRIVE_ABSOLUTE = /^[a-zA-Z]:[\\/]/;
const realPlatform = process.platform;
const realRealpath = fs.realpath.bind(fs);

function toDarwinCanonicalForm(resultPath) {
  if (WINDOWS_DRIVE_ABSOLUTE.test(resultPath)) {
    // On a Windows host the physical realpath is drive-absolute; render it as
    // a '/private'-prefixed posix path to mimic macOS /var -> /private/var.
    return `/private/${resultPath.replace(WINDOWS_DRIVE_ABSOLUTE, '').split('\\').join('/')}`;
  }
  // On a real POSIX host the operating system already supplies the truth:
  // macOS returns /private/tmp/... for /tmp/... and Linux returns /tmp/....
  return resultPath;
}

fs.realpath = async function darwinSimulatedRealpath(candidatePath) {
  const resolved = await realRealpath(candidatePath);
  if (typeof candidatePath === 'string' && candidatePath.startsWith(`${SIM_ROOT}/`)) {
    return toDarwinCanonicalForm(resolved);
  }
  return resolved;
};

const POSIX_PATH = require('node:path/posix');

Object.defineProperty(process, 'platform', { value: 'darwin' });

const trainerWorkspaceServiceModulePath = hostPath.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'trainerWorkspaceService.js',
);

// The compiled service is a plain CommonJS module that only depends on
// node:crypto, node:fs/promises, and node:path. It is loaded here through a
// scoped require so the simulation can hand it the posix path implementation
// without touching the shared node:path module (the CommonJS loader itself
// depends on it).
function loadTrainerWorkspaceService(modulePath) {
  const source = require('node:fs').readFileSync(modulePath, 'utf8');
  const moduleExports = {};
  const scopedRequire = (request) => {
    if (request === 'node:path') {
      return POSIX_PATH;
    }
    if (request === 'node:fs/promises') {
      return fs;
    }
    return require(request);
  };
  const moduleFunction = require('node:vm').compileFunction(source, [
    'exports',
    'require',
    'module',
    '__filename',
    '__dirname',
  ]);
  moduleFunction.call(
    moduleExports,
    moduleExports,
    scopedRequire,
    { exports: moduleExports },
    modulePath,
    hostPath.dirname(modulePath),
  );
  return moduleExports;
}

const { TrainerWorkspaceService } = loadTrainerWorkspaceService(trainerWorkspaceServiceModulePath);

// The service must have loaded with posix path semantics for this simulation
// to be meaningful.
assert.equal(typeof TrainerWorkspaceService, 'function');

function createGlobalState(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    get(key) {
      return values.get(key);
    },
    async update(key, value) {
      if (value === undefined) {
        values.delete(key);
        return;
      }
      values.set(key, value);
    },
  };
}

function simulationDirectory(label) {
  return POSIX_PATH.join(SIM_ROOT, label);
}

async function removeSimulationTree() {
  await fs.rm(hostPath.resolve(SIM_ROOT), { recursive: true, force: true });
}

async function createExternalDataRoot(label, fileName) {
  const externalDataRoot = simulationDirectory(label);
  await fs.mkdir(externalDataRoot, { recursive: true });
  await fs.writeFile(POSIX_PATH.join(externalDataRoot, fileName), `${label}-state\n`, 'utf8');
  return externalDataRoot;
}

test('darwin simulation: workspace migration rebases an external sidecar data folder whose canonical path differs from the lexical path', async (t) => {
  t.after(removeSimulationTree);
  const sourceRoot = simulationDirectory('source-workspace');
  const targetRoot = simulationDirectory('migrated-workspace');
  const externalDataRoot = await createExternalDataRoot('sidecar-data', 'research.db');
  const service = new TrainerWorkspaceService({ globalState: createGlobalState() });

  await service.selectRoot(sourceRoot);

  // Before the per-host fix this call rejected the valid external data root
  // with "must not resolve through a symbolic link or junction" because the
  // simulated macOS realpath (/private/...) differs from the lexical path.
  const migration = await service.migrateWorkspaceRoot(targetRoot, {
    managedDataRoot: externalDataRoot,
  });

  assert.equal(migration.targetRoot, POSIX_PATH.resolve(targetRoot));
  assert.equal(migration.managedDataRoot, POSIX_PATH.join(targetRoot, '.trainer', 'runtime'));
  assert.equal(
    await fs.readFile(POSIX_PATH.join(migration.managedDataRoot, 'research.db'), 'utf8'),
    'sidecar-data-state\n',
  );
  assert.equal(
    await fs.readFile(POSIX_PATH.join(externalDataRoot, 'research.db'), 'utf8'),
    'sidecar-data-state\n',
  );
});

test('darwin simulation: workspace backup captures the same canonicalized external data folder', async (t) => {
  t.after(removeSimulationTree);
  const sourceRoot = simulationDirectory('backup-source-workspace');
  const backupRoot = simulationDirectory('workspace-backup');
  const externalDataRoot = await createExternalDataRoot('backup-sidecar-data', 'trainer.db');
  const service = new TrainerWorkspaceService({ globalState: createGlobalState() });

  await service.selectRoot(sourceRoot);

  const backup = await service.backupWorkspace(backupRoot, { managedDataRoot: externalDataRoot });

  assert.equal(backup.managedDataRoot, POSIX_PATH.join(backupRoot, '.trainer', 'runtime'));
  assert.equal(
    await fs.readFile(POSIX_PATH.join(backup.managedDataRoot, 'trainer.db'), 'utf8'),
    'backup-sidecar-data-state\n',
  );
});

test('darwin simulation: a symlinked external data directory is still rejected', async (t) => {
  t.after(removeSimulationTree);
  const sourceRoot = simulationDirectory('reject-source-workspace');
  const backupRoot = simulationDirectory('reject-workspace-backup');
  const externalDataRoot = await createExternalDataRoot('reject-sidecar-data', 'trainer.db');
  const linkedDataRoot = simulationDirectory('reject-linked-runtime');
  const service = new TrainerWorkspaceService({ globalState: createGlobalState() });

  await service.selectRoot(sourceRoot);
  await fs.symlink(
    hostPath.resolve(externalDataRoot),
    linkedDataRoot,
    realPlatform === 'win32' ? 'junction' : 'dir',
  );

  await assert.rejects(
    () => service.backupWorkspace(backupRoot, { managedDataRoot: linkedDataRoot }),
    /symbolic link|junction/,
  );
});
