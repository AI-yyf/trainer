'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const trainerWorkspaceServiceModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'trainerWorkspaceService.js',
);

const {
  TRAINER_WORKSPACE_DIRECTORIES,
  TRAINER_MANAGED_PROJECT_DIRECTORIES,
  TRAINER_WORKSPACE_BACKUP_FILE,
  TRAINER_WORKSPACE_PENDING_RECONCILIATIONS_STORAGE_KEY,
  TRAINER_WORKSPACE_PROJECTS_STORAGE_KEY,
  TRAINER_WORKSPACE_ROOT_STORAGE_KEY,
  TRAINER_WORKSPACE_MANIFEST_FILE,
  TrainerWorkspaceService,
  fingerprintTrainerProjectPath,
} = require(trainerWorkspaceServiceModulePath);

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

function createService(globalState) {
  return new TrainerWorkspaceService({ globalState });
}

function managedIdentity(projectPath, label = 'one') {
  return {
    rootId: 'root-host-v2',
    projectId: `project-${label}`,
    contextId: `context-${label}`,
    canonicalProjectPath: path.resolve(projectPath),
    legacyAliases: [`legacy-${label}`],
    revisions: { root: 1, project: 1, context: 1 },
    pending: false,
    reconcile: { root: { state: 'current' }, project: { state: 'current' } },
  };
}

async function createTemporaryDirectory(t) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'trainer-workspace-service-'));
  t.after(async () => {
    await fs.rm(directory, { recursive: true, force: true });
  });
  return directory;
}

test('saveWorkspaceRoot creates the constitution workspace scaffold', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const rootPath = path.join(temporaryDirectory, 'TrainerWorkspace');
  const globalState = createGlobalState();
  const service = createService(globalState);

  const manifest = await service.selectRoot(rootPath);

  assert.equal(globalState.get(TRAINER_WORKSPACE_ROOT_STORAGE_KEY), path.resolve(rootPath));
  assert.equal(service.getRoot(), path.resolve(rootPath));
  assert.equal(manifest.rootPath, path.resolve(rootPath));
  for (const directory of TRAINER_WORKSPACE_DIRECTORIES) {
    const stat = await fs.stat(path.join(rootPath, directory));
    assert.equal(stat.isDirectory(), true, `${directory} should be a directory`);
  }
  assert.equal(await service.hasWorkspaceScaffold(), true);
});

test('workspace root persists through ExtensionContext globalState', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const rootPath = path.join(temporaryDirectory, 'saved-root');
  const globalState = createGlobalState();

  await createService(globalState).selectRoot(rootPath);
  const restoredService = createService(globalState);

  assert.equal(restoredService.getWorkspaceRoot(), path.resolve(rootPath));
  assert.equal((await restoredService.readWorkspaceManifest()).rootPath, path.resolve(rootPath));
});

test('workspace snapshot does not report a persisted but unavailable root as ready', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const unavailableRoot = path.join(temporaryDirectory, 'missing-root');
  const service = createService(
    createGlobalState({ [TRAINER_WORKSPACE_ROOT_STORAGE_KEY]: unavailableRoot }),
  );

  const snapshot = await service.toSnapshot(path.join(temporaryDirectory, 'missing-project'));

  assert.equal(snapshot.rootPath, path.resolve(unavailableRoot));
  assert.equal(snapshot.workspaceReady, false);
  assert.equal(snapshot.manifest, undefined);
  assert.equal(snapshot.currentProject, undefined);
});

test('project adoption records a stable fingerprint and explicit state changes', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const workspaceRoot = path.join(temporaryDirectory, 'workspace');
  const projectPath = path.join(temporaryDirectory, 'detected-project');
  await fs.mkdir(projectPath, { recursive: true });
  const globalState = createGlobalState();
  const service = createService(globalState);
  await service.selectRoot(workspaceRoot);

  const browseState = await service.setProjectAdmission(projectPath, 'browse');
  const ignoredState = await service.setProjectAdmission(projectPath, 'ignored');
  const managedState = await service.setProjectAdmission(
    projectPath,
    'managed',
    managedIdentity(projectPath),
  );

  const expectedFingerprint = fingerprintTrainerProjectPath(projectPath);
  assert.equal(browseState.fingerprint, expectedFingerprint);
  assert.equal(managedState.fingerprint, expectedFingerprint);
  assert.equal(ignoredState.adoptionMode, 'ignored');
  assert.equal(managedState.projectId, 'project-one');
  assert.equal((await service.getProject(projectPath)).adoptionMode, 'managed');
  assert.equal(
    globalState.get(TRAINER_WORKSPACE_PROJECTS_STORAGE_KEY)[expectedFingerprint].adoptionMode,
    'managed',
  );
});

test('managed adoption creates an isolated project lane for memory, plans, training, and agent context', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const workspaceRoot = path.join(temporaryDirectory, 'workspace');
  const projectPath = path.join(temporaryDirectory, 'project');
  await fs.mkdir(projectPath, { recursive: true });
  const service = createService(createGlobalState());
  await service.selectRoot(workspaceRoot);

  const project = await service.setProjectAdmission(projectPath, 'managed', managedIdentity(projectPath));

  assert.ok(project.projectLanePath);
  for (const directory of TRAINER_MANAGED_PROJECT_DIRECTORIES) {
    const stat = await fs.stat(path.join(project.projectLanePath, directory));
    assert.equal(stat.isDirectory(), true, `${directory} should be a managed project lane directory`);
  }
  const projectManifest = JSON.parse(
    await fs.readFile(path.join(project.projectLanePath, 'project.json'), 'utf8'),
  );
  assert.equal(projectManifest.kind, 'trainer-project');
  assert.equal(projectManifest.sourcePath, path.resolve(projectPath));
});

test('managed adoption refuses a backend identity from a different Trainer workspace root', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const workspaceRoot = path.join(temporaryDirectory, 'workspace');
  const projectPath = path.join(temporaryDirectory, 'project');
  const otherRoot = path.join(temporaryDirectory, 'other-workspace');
  await fs.mkdir(projectPath, { recursive: true });
  const service = createService(createGlobalState());
  await service.selectRoot(workspaceRoot);

  await assert.rejects(
    () =>
      service.setProjectAdmission(projectPath, 'managed', {
        ...managedIdentity(projectPath),
        canonicalRootPath: otherRoot,
      }),
    /does not match the selected workspace root/,
  );
  assert.equal(await service.getProject(projectPath), undefined);
});

test('workspace manifest records only explicit project adoption state', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const workspaceRoot = path.join(temporaryDirectory, 'workspace');
  const projectPath = path.join(temporaryDirectory, 'project');
  await fs.mkdir(projectPath, { recursive: true });
  const service = createService(createGlobalState());
  await service.saveWorkspaceRoot(workspaceRoot);

  const projectState = await service.setProjectAdoption(projectPath, 'managed', managedIdentity(projectPath));
  const manifestPath = path.join(workspaceRoot, TRAINER_WORKSPACE_MANIFEST_FILE);
  const fileManifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
  const serviceManifest = await service.readWorkspaceManifest();

  assert.equal(fileManifest.schemaVersion, 2);
  assert.equal(fileManifest.kind, 'trainer-workspace');
  assert.equal(fileManifest.rootPath, path.resolve(workspaceRoot));
  assert.deepEqual(fileManifest.projects[projectState.fingerprint], projectState);
  assert.deepEqual(serviceManifest.projects[projectState.fingerprint], projectState);
  assert.deepEqual(fileManifest.directories, [...TRAINER_WORKSPACE_DIRECTORIES]);
});

test('v1 manifests are read as v2 and preserved as reconcile-required until a server identity arrives', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const workspaceRoot = path.join(temporaryDirectory, 'workspace');
  const projectPath = path.join(temporaryDirectory, 'legacy-project');
  await fs.mkdir(projectPath, { recursive: true });
  const globalState = createGlobalState();
  const service = createService(globalState);
  await service.selectRoot(workspaceRoot);
  const fingerprint = fingerprintTrainerProjectPath(projectPath);
  const legacyManifest = {
    schemaVersion: 1,
    kind: 'trainer-workspace',
    rootPath: path.resolve(workspaceRoot),
    createdAt: '2026-07-01T00:00:00.000Z',
    updatedAt: '2026-07-01T00:00:00.000Z',
    directories: [...TRAINER_WORKSPACE_DIRECTORIES],
    projects: {
      [fingerprint]: {
        fingerprint,
        projectPath: path.resolve(projectPath),
        workspaceRoot: path.resolve(workspaceRoot),
        adoptionMode: 'managed',
        updatedAt: '2026-07-01T00:00:00.000Z',
      },
    },
  };
  const manifestPath = path.join(workspaceRoot, TRAINER_WORKSPACE_MANIFEST_FILE);
  await fs.writeFile(manifestPath, `${JSON.stringify(legacyManifest)}\n`, 'utf8');

  const migrated = await service.readWorkspaceManifest();

  assert.equal(migrated.schemaVersion, 2);
  assert.equal(migrated.rootId, undefined);
  assert.equal(migrated.identityStatus, 'reconcile-required');
  assert.equal(migrated.projects[fingerprint].identityStatus, 'reconcile-required');
  assert.equal(migrated.projects[fingerprint].projectId, undefined);
  await service.saveWorkspaceRoot(workspaceRoot);
  assert.equal(JSON.parse(await fs.readFile(manifestPath, 'utf8')).schemaVersion, 2);
});

test('two managed projects keep server-issued IDs separate under one root', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const workspaceRoot = path.join(temporaryDirectory, 'workspace');
  const alphaPath = path.join(temporaryDirectory, 'alpha');
  const betaPath = path.join(temporaryDirectory, 'beta');
  await Promise.all([fs.mkdir(alphaPath, { recursive: true }), fs.mkdir(betaPath, { recursive: true })]);
  const service = createService(createGlobalState());
  await service.selectRoot(workspaceRoot);

  const alpha = await service.setProjectAdmission(alphaPath, 'managed', managedIdentity(alphaPath, 'alpha'));
  const beta = await service.setProjectAdmission(betaPath, 'managed', managedIdentity(betaPath, 'beta'));
  const manifest = await service.readWorkspaceManifest();

  assert.equal(manifest.rootId, 'root-host-v2');
  assert.equal(alpha.rootId, beta.rootId);
  assert.notEqual(alpha.projectId, beta.projectId);
  assert.notEqual(alpha.contextId, beta.contextId);
  assert.notEqual(alpha.projectLanePath, beta.projectLanePath);
  assert.equal(path.basename(alpha.projectLanePath), alpha.projectId);
  assert.equal(path.basename(beta.projectLanePath), beta.projectId);
  assert.equal(manifest.projects[alpha.fingerprint].contextId, alpha.contextId);
  assert.equal(manifest.projects[beta.fingerprint].contextId, beta.contextId);
});

test('server-confirmed project path reconciliation preserves project and context identity', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const workspaceRoot = path.join(temporaryDirectory, 'workspace');
  const originalPath = path.join(temporaryDirectory, 'project-original');
  const movedPath = path.join(temporaryDirectory, 'project-moved');
  await Promise.all([fs.mkdir(originalPath, { recursive: true }), fs.mkdir(movedPath, { recursive: true })]);
  const service = createService(createGlobalState());
  await service.selectRoot(workspaceRoot);
  const original = await service.setProjectAdmission(
    originalPath,
    'managed',
    managedIdentity(originalPath, 'moved'),
  );
  const reconciled = await service.setProjectAdmission(
    movedPath,
    'managed',
    managedIdentity(movedPath, 'moved'),
  );
  const manifest = await service.readWorkspaceManifest();

  assert.equal(reconciled.projectId, original.projectId);
  assert.equal(reconciled.contextId, original.contextId);
  assert.equal(reconciled.pathRevision, original.pathRevision + 1);
  assert.ok(reconciled.legacyAliases.includes(path.resolve(originalPath)));
  assert.equal(reconciled.projectLanePath, original.projectLanePath);
  assert.equal(manifest.projects[original.fingerprint], undefined);
  assert.equal(manifest.projects[reconciled.fingerprint].projectId, original.projectId);
});

test('a manifest persistence failure records reconciliation and allows a later verified retry', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const workspaceRoot = path.join(temporaryDirectory, 'workspace');
  const projectPath = path.join(temporaryDirectory, 'project');
  await fs.mkdir(projectPath, { recursive: true });
  const values = new Map();
  let rejectProjectRegistryWrite = false;
  const globalState = {
    get(key) {
      return values.get(key);
    },
    async update(key, value) {
      if (key === TRAINER_WORKSPACE_PROJECTS_STORAGE_KEY && rejectProjectRegistryWrite) {
        rejectProjectRegistryWrite = false;
        throw new Error('simulated manifest registry failure');
      }
      if (value === undefined) {
        values.delete(key);
        return;
      }
      values.set(key, value);
    },
  };
  const service = createService(globalState);
  await service.selectRoot(workspaceRoot);
  rejectProjectRegistryWrite = true;

  await assert.rejects(
    () => service.setProjectAdmission(projectPath, 'managed', managedIdentity(projectPath, 'retry')),
    /simulated manifest registry failure/,
  );
  assert.equal(await service.getProject(projectPath), undefined);
  assert.match(service.getManagedProvisioningPending(projectPath).reason, /simulated manifest registry failure/);

  const retried = await service.setProjectAdmission(projectPath, 'managed', managedIdentity(projectPath, 'retry'));
  assert.equal(retried.identityStatus, 'verified');
  assert.equal(service.getManagedProvisioningPending(projectPath), undefined);
});

test('pending managed provisioning preserves recovery metadata and can be abandoned', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const workspaceRoot = path.join(temporaryDirectory, 'workspace');
  const projectPath = path.join(temporaryDirectory, 'project');
  await fs.mkdir(projectPath, { recursive: true });
  const globalState = createGlobalState();
  const service = createService(globalState);
  await service.selectRoot(workspaceRoot);

  await service.recordManagedProvisioningPending(
    projectPath,
    'Trainer adoption indexing is still running.',
    { jobId: 'job-admission-42', state: 'waiting' },
  );

  const pending = service.getManagedProvisioningPending(projectPath);
  assert.equal(pending.reason, 'Trainer adoption indexing is still running.');
  assert.equal(pending.jobId, 'job-admission-42');
  assert.equal(pending.state, 'waiting');
  assert.deepEqual(pending.availableActions, ['continue-waiting', 'retry', 'abandon']);
  assert.match(pending.updatedAt, /^\d{4}-\d{2}-\d{2}T/);
  assert.equal(
    globalState.get(TRAINER_WORKSPACE_PENDING_RECONCILIATIONS_STORAGE_KEY)[
      fingerprintTrainerProjectPath(projectPath)
    ].jobId,
    'job-admission-42',
  );

  await service.abandonManagedProvisioning(projectPath);
  assert.equal(service.getManagedProvisioningPending(projectPath), undefined);
});

test('workspace migration copies Trainer data, rebases project lanes, and leaves the source untouched', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const sourceRoot = path.join(temporaryDirectory, 'source-workspace');
  const targetRoot = path.join(temporaryDirectory, 'migrated-workspace');
  const projectPath = path.join(temporaryDirectory, 'project');
  await fs.mkdir(projectPath, { recursive: true });
  const globalState = createGlobalState();
  const service = createService(globalState);
  await service.selectRoot(sourceRoot);
  const project = await service.setProjectAdmission(projectPath, 'managed', managedIdentity(projectPath));
  const sourceMemoryPath = path.join(sourceRoot, '.trainer', 'memory', 'profile.json');
  const sourceLaneArtifact = path.join(project.projectLanePath, 'memory', 'project-context.json');
  await fs.writeFile(sourceMemoryPath, '{"goal":"learn"}\n', 'utf8');
  await fs.writeFile(sourceLaneArtifact, '{"scope":"project"}\n', 'utf8');

  const result = await service.migrateWorkspaceRoot(targetRoot);
  const migratedProject = await service.getProject(projectPath);
  const migratedManifest = await service.readWorkspaceManifest();
  const migratedLanePath = path.join(targetRoot, 'Projects', project.projectId);

  assert.equal(result.sourceRoot, path.resolve(sourceRoot));
  assert.equal(result.targetRoot, path.resolve(targetRoot));
  assert.equal(globalState.get(TRAINER_WORKSPACE_ROOT_STORAGE_KEY), path.resolve(targetRoot));
  assert.equal(await fs.readFile(sourceMemoryPath, 'utf8'), '{"goal":"learn"}\n');
  assert.equal(await fs.readFile(path.join(targetRoot, '.trainer', 'memory', 'profile.json'), 'utf8'), '{"goal":"learn"}\n');
  assert.equal(await fs.readFile(path.join(migratedLanePath, 'memory', 'project-context.json'), 'utf8'), '{"scope":"project"}\n');
  assert.equal(migratedManifest.rootPath, path.resolve(targetRoot));
  assert.equal(migratedManifest.rootId, project.rootId);
  assert.equal(migratedManifest.identityStatus, 'reconcile-required');
  assert.equal(migratedManifest.projects[project.fingerprint].workspaceRoot, path.resolve(targetRoot));
  assert.equal(migratedManifest.projects[project.fingerprint].projectId, project.projectId);
  assert.equal(migratedManifest.projects[project.fingerprint].contextId, project.contextId);
  assert.equal(migratedManifest.projects[project.fingerprint].identityStatus, 'reconcile-required');
  assert.equal(migratedManifest.projects[project.fingerprint].projectLanePath, path.resolve(migratedLanePath));
  assert.equal(migratedProject.workspaceRoot, path.resolve(targetRoot));
  assert.equal(migratedProject.projectLanePath, path.resolve(migratedLanePath));
  const projectManifest = JSON.parse(await fs.readFile(path.join(migratedLanePath, 'project.json'), 'utf8'));
  assert.equal(projectManifest.workspaceRoot, path.resolve(targetRoot));
});

test('workspace backup restores a complete snapshot into a new active root', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const sourceRoot = path.join(temporaryDirectory, 'source-workspace');
  const backupRoot = path.join(temporaryDirectory, 'workspace-backup');
  const restoredRoot = path.join(temporaryDirectory, 'restored-workspace');
  const projectPath = path.join(temporaryDirectory, 'project');
  await fs.mkdir(projectPath, { recursive: true });
  const globalState = createGlobalState();
  const service = createService(globalState);
  await service.selectRoot(sourceRoot);
  const project = await service.setProjectAdmission(projectPath, 'managed', managedIdentity(projectPath));
  await fs.writeFile(
    path.join(sourceRoot, '.trainer', 'plans', 'global-plan.json'),
    '{"stage":"foundation"}\n',
    'utf8',
  );

  const backup = await service.backupWorkspace(backupRoot);
  const backupManifest = JSON.parse(
    await fs.readFile(path.join(backupRoot, TRAINER_WORKSPACE_BACKUP_FILE), 'utf8'),
  );
  const restored = await service.restoreWorkspaceBackup(backupRoot, restoredRoot);
  const restoredProject = await service.getProject(projectPath);

  assert.equal(backup.sourceRoot, path.resolve(sourceRoot));
  assert.equal(backupManifest.kind, 'trainer-workspace-backup');
  assert.equal(backupManifest.sourceRoot, path.resolve(sourceRoot));
  assert.equal(restored.sourceRoot, path.resolve(sourceRoot));
  assert.equal(restored.targetRoot, path.resolve(restoredRoot));
  assert.equal(globalState.get(TRAINER_WORKSPACE_ROOT_STORAGE_KEY), path.resolve(restoredRoot));
  assert.equal(
    await fs.readFile(path.join(restoredRoot, '.trainer', 'plans', 'global-plan.json'), 'utf8'),
    '{"stage":"foundation"}\n',
  );
  assert.equal(await fs.stat(path.join(backupRoot, TRAINER_WORKSPACE_BACKUP_FILE)).then(() => true), true);
  assert.equal(await fs.stat(path.join(restoredRoot, TRAINER_WORKSPACE_BACKUP_FILE)).then(() => true).catch(() => false), false);
  assert.equal(restoredProject.workspaceRoot, path.resolve(restoredRoot));
  assert.equal(restoredProject.projectLanePath, path.resolve(restoredRoot, 'Projects', project.projectId));
  assert.equal(restoredProject.projectId, project.projectId);
  assert.equal(restoredProject.contextId, project.contextId);
  assert.equal(restoredProject.identityStatus, 'reconcile-required');
});

test('workspace recovery captures external sidecar data and resumes from the restored copy', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const sourceRoot = path.join(temporaryDirectory, 'source-workspace');
  const externalDataRoot = path.join(temporaryDirectory, 'sidecar-data');
  const backupRoot = path.join(temporaryDirectory, 'workspace-backup');
  const restoredRoot = path.join(temporaryDirectory, 'restored-workspace');
  const service = createService(createGlobalState());
  await service.selectRoot(sourceRoot);
  await fs.mkdir(path.join(externalDataRoot, 'qdrant'), { recursive: true });
  await fs.writeFile(path.join(externalDataRoot, 'trainer.db'), 'sqlite-state\n', 'utf8');
  await fs.writeFile(path.join(externalDataRoot, 'qdrant', 'collections.json'), '{"resources":1}\n', 'utf8');

  const backup = await service.backupWorkspace(backupRoot, { managedDataRoot: externalDataRoot });
  const backupManifest = JSON.parse(
    await fs.readFile(path.join(backupRoot, TRAINER_WORKSPACE_BACKUP_FILE), 'utf8'),
  );
  const restored = await service.restoreWorkspaceBackup(backupRoot, restoredRoot);

  assert.equal(backup.managedDataRoot, path.resolve(backupRoot, '.trainer', 'runtime'));
  assert.deepEqual(backupManifest.runtimeData, { relativePath: path.join('.trainer', 'runtime') });
  assert.equal(
    await fs.readFile(path.join(backupRoot, '.trainer', 'runtime', 'trainer.db'), 'utf8'),
    'sqlite-state\n',
  );
  assert.equal(restored.managedDataRoot, path.resolve(restoredRoot, '.trainer', 'runtime'));
  assert.equal(
    await fs.readFile(path.join(restored.managedDataRoot, 'qdrant', 'collections.json'), 'utf8'),
    '{"resources":1}\n',
  );
});

test('workspace migration rebases an external sidecar data folder into the new root', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const sourceRoot = path.join(temporaryDirectory, 'source-workspace');
  const externalDataRoot = path.join(temporaryDirectory, 'sidecar-data');
  const targetRoot = path.join(temporaryDirectory, 'migrated-workspace');
  const service = createService(createGlobalState());
  await service.selectRoot(sourceRoot);
  await fs.mkdir(externalDataRoot, { recursive: true });
  await fs.writeFile(path.join(externalDataRoot, 'research.db'), 'research-state\n', 'utf8');

  const migration = await service.migrateWorkspaceRoot(targetRoot, {
    managedDataRoot: externalDataRoot,
  });

  assert.equal(migration.managedDataRoot, path.resolve(targetRoot, '.trainer', 'runtime'));
  assert.equal(
    await fs.readFile(path.join(migration.managedDataRoot, 'research.db'), 'utf8'),
    'research-state\n',
  );
  assert.equal(await fs.readFile(path.join(externalDataRoot, 'research.db'), 'utf8'), 'research-state\n');
});

test('workspace migration restores the previous registry and root when activation persistence fails', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const sourceRoot = path.join(temporaryDirectory, 'source-workspace');
  const targetRoot = path.join(temporaryDirectory, 'migrated-workspace');
  const projectPath = path.join(temporaryDirectory, 'project');
  await fs.mkdir(projectPath, { recursive: true });
  const values = new Map();
  let rejectNextRootActivation = false;
  const globalState = {
    get(key) {
      return values.get(key);
    },
    async update(key, value) {
      if (key === TRAINER_WORKSPACE_ROOT_STORAGE_KEY && rejectNextRootActivation) {
        rejectNextRootActivation = false;
        throw new Error('simulated root persistence failure');
      }
      if (value === undefined) {
        values.delete(key);
        return;
      }
      values.set(key, value);
    },
  };
  const service = createService(globalState);
  await service.selectRoot(sourceRoot);
  const project = await service.setProjectAdmission(projectPath, 'managed', managedIdentity(projectPath));
  rejectNextRootActivation = true;

  await assert.rejects(
    () => service.migrateWorkspaceRoot(targetRoot),
    /simulated root persistence failure/,
  );

  assert.equal(service.getWorkspaceRoot(), path.resolve(sourceRoot));
  assert.equal(
    globalState.get(TRAINER_WORKSPACE_PROJECTS_STORAGE_KEY)[project.fingerprint].workspaceRoot,
    path.resolve(sourceRoot),
  );
  assert.equal(await fs.stat(targetRoot).then(() => true).catch(() => false), true);
});

test('workspace restore rejects a legacy backup without the runtime data record', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const sourceRoot = path.join(temporaryDirectory, 'source-workspace');
  const backupRoot = path.join(temporaryDirectory, 'workspace-backup');
  const restoredRoot = path.join(temporaryDirectory, 'restored-workspace');
  const service = createService(createGlobalState());
  await service.selectRoot(sourceRoot);
  await service.backupWorkspace(backupRoot);

  const backupPath = path.join(backupRoot, TRAINER_WORKSPACE_BACKUP_FILE);
  const backupManifest = JSON.parse(await fs.readFile(backupPath, 'utf8'));
  delete backupManifest.runtimeData;
  await fs.writeFile(backupPath, `${JSON.stringify(backupManifest)}\n`, 'utf8');

  await assert.rejects(
    () => service.restoreWorkspaceBackup(backupRoot, restoredRoot),
    /does not include the runtime data/,
  );
  assert.equal(service.getWorkspaceRoot(), path.resolve(sourceRoot));
});

test('workspace recovery rejects runtime data that resolves through a symbolic link', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const sourceRoot = path.join(temporaryDirectory, 'source-workspace');
  const externalDataRoot = path.join(temporaryDirectory, 'external-runtime');
  const linkedDataRoot = path.join(temporaryDirectory, 'linked-runtime');
  const backupRoot = path.join(temporaryDirectory, 'workspace-backup');
  const restoredRoot = path.join(temporaryDirectory, 'restored-workspace');
  const service = createService(createGlobalState());
  await service.selectRoot(sourceRoot);
  await fs.mkdir(externalDataRoot, { recursive: true });
  await fs.writeFile(path.join(externalDataRoot, 'trainer.db'), 'state\n', 'utf8');
  try {
    await fs.symlink(
      externalDataRoot,
      linkedDataRoot,
      process.platform === 'win32' ? 'junction' : 'dir',
    );
  } catch (error) {
    t.skip(`Symbolic links are unavailable in this environment: ${String(error)}`);
    return;
  }

  await assert.rejects(
    () => service.backupWorkspace(backupRoot, { managedDataRoot: linkedDataRoot }),
    /symbolic link|junction/,
  );

  await service.backupWorkspace(backupRoot, { managedDataRoot: externalDataRoot });
  await fs.rm(path.join(backupRoot, '.trainer', 'runtime'), { recursive: true, force: true });
  await fs.symlink(
    externalDataRoot,
    path.join(backupRoot, '.trainer', 'runtime'),
    process.platform === 'win32' ? 'junction' : 'dir',
  );

  await assert.rejects(
    () => service.restoreWorkspaceBackup(backupRoot, restoredRoot),
    /symbolic link|junction|resolves outside/,
  );
  assert.equal(service.getWorkspaceRoot(), path.resolve(sourceRoot));
});

test('workspace recovery captures sidecar data reached through a junctioned temp ancestor', async (t) => {
  // GitHub Windows runners expose os.tmpdir() through a junction, so the
  // canonical path of an external sidecar data root differs from its lexical
  // path even though nothing malicious is happening. This fixture reproduces
  // that runner condition: the data root lives behind a junctioned ancestor
  // and must be captured and rebased, not rejected.
  const temporaryDirectory = await createTemporaryDirectory(t);
  const physicalDirectory = path.join(temporaryDirectory, 'physical-temp');
  const junctionedDirectory = path.join(temporaryDirectory, 'junctioned-temp');
  const externalDataRoot = path.join(junctionedDirectory, 'sidecar-data');
  try {
    await fs.mkdir(path.join(physicalDirectory, 'sidecar-data'), { recursive: true });
    await fs.symlink(
      physicalDirectory,
      junctionedDirectory,
      process.platform === 'win32' ? 'junction' : 'dir',
    );
  } catch (error) {
    t.skip(`Junctioned directories are unavailable in this environment: ${String(error)}`);
    return;
  }
  await fs.writeFile(path.join(externalDataRoot, 'trainer.db'), 'sqlite-state\n', 'utf8');

  const sourceRoot = path.join(temporaryDirectory, 'source-workspace');
  const backupRoot = path.join(temporaryDirectory, 'workspace-backup');
  const restoredRoot = path.join(temporaryDirectory, 'restored-workspace');
  const migratedRoot = path.join(temporaryDirectory, 'migrated-workspace');
  const service = createService(createGlobalState());
  await service.selectRoot(sourceRoot);

  const backup = await service.backupWorkspace(backupRoot, { managedDataRoot: externalDataRoot });
  assert.equal(backup.managedDataRoot, path.resolve(backupRoot, '.trainer', 'runtime'));
  assert.equal(
    await fs.readFile(path.join(backupRoot, '.trainer', 'runtime', 'trainer.db'), 'utf8'),
    'sqlite-state\n',
  );

  const migration = await service.migrateWorkspaceRoot(migratedRoot, {
    managedDataRoot: externalDataRoot,
  });
  assert.equal(migration.managedDataRoot, path.resolve(migratedRoot, '.trainer', 'runtime'));
  assert.equal(
    await fs.readFile(path.join(migration.managedDataRoot, 'trainer.db'), 'utf8'),
    'sqlite-state\n',
  );
  assert.equal(await fs.readFile(path.join(externalDataRoot, 'trainer.db'), 'utf8'), 'sqlite-state\n');

  const restored = await service.restoreWorkspaceBackup(backupRoot, restoredRoot);
  assert.equal(restored.managedDataRoot, path.resolve(restoredRoot, '.trainer', 'runtime'));
  assert.equal(
    await fs.readFile(path.join(restored.managedDataRoot, 'trainer.db'), 'utf8'),
    'sqlite-state\n',
  );
});

test('workspace recovery refuses non-empty or nested targets before changing the active root', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const sourceRoot = path.join(temporaryDirectory, 'source-workspace');
  const occupiedTarget = path.join(temporaryDirectory, 'occupied-target');
  const nestedTarget = path.join(sourceRoot, 'backup');
  const globalState = createGlobalState();
  const service = createService(globalState);
  await service.selectRoot(sourceRoot);
  await fs.mkdir(occupiedTarget, { recursive: true });
  await fs.writeFile(path.join(occupiedTarget, 'keep.txt'), 'keep\n', 'utf8');

  await assert.rejects(() => service.migrateWorkspaceRoot(occupiedTarget), /must be empty/);
  await assert.rejects(() => service.backupWorkspace(nestedTarget), /nested directory/);
  assert.equal(globalState.get(TRAINER_WORKSPACE_ROOT_STORAGE_KEY), path.resolve(sourceRoot));
  assert.equal(await fs.readFile(path.join(occupiedTarget, 'keep.txt'), 'utf8'), 'keep\n');
});

test('deleteManagedProject removes live registry but leaves the project lane stored', async (t) => {
  const temporaryDirectory = await createTemporaryDirectory(t);
  const workspaceRoot = path.join(temporaryDirectory, 'workspace');
  const alphaPath = path.join(temporaryDirectory, 'alpha');
  const betaPath = path.join(temporaryDirectory, 'beta');
  await Promise.all([fs.mkdir(alphaPath, { recursive: true }), fs.mkdir(betaPath, { recursive: true })]);
  const service = createService(createGlobalState());
  await service.selectRoot(workspaceRoot);

  const alpha = await service.setProjectAdmission(alphaPath, 'managed', managedIdentity(alphaPath, 'alpha'));
  const beta = await service.setProjectAdmission(betaPath, 'managed', managedIdentity(betaPath, 'beta'));
  const laneManifest = path.join(alpha.projectLanePath, 'project.json');
  assert.equal(await fs.readFile(laneManifest, 'utf8').then((value) => Boolean(value)), true);

  const deleted = await service.deleteManagedProject(alphaPath);
  const manifest = await service.readWorkspaceManifest();

  assert.equal(deleted.projectId, alpha.projectId);
  assert.equal(await service.getProject(alphaPath), undefined);
  assert.equal((await service.getProject(betaPath))?.projectId, beta.projectId);
  assert.equal(manifest.projects[alpha.fingerprint], undefined);
  assert.equal(manifest.projects[beta.fingerprint].projectId, beta.projectId);
  assert.equal(JSON.parse(await fs.readFile(laneManifest, 'utf8')).projectId, alpha.projectId);
});
