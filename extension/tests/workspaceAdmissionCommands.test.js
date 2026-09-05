'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const commandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'workspaceAdmissionCommands.js',
);
const workbenchDataModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'workbenchData.js',
);

function createVscodeMock(...selectedPaths) {
  const selectionQueue = [...selectedPaths];
  return {
    Uri: {
      file(value) {
        return { fsPath: value };
      },
    },
    window: {
      async showOpenDialog() {
        const selectedPath = selectionQueue.shift();
        return selectedPath ? [{ fsPath: selectedPath }] : undefined;
      },
      async showWarningMessage(_message, _options, ...actions) {
        return actions[0];
      },
    },
    workspace: {
      workspaceFolders: [],
    },
  };
}

function createContext(options = {}) {
  const { createDefaultBootstrapData } = require(workbenchDataModulePath);
  const workspaceFolder = path.resolve('C:\\trainer-workspace-tests\\current-project');
  let sidecarStatus = options.sidecarStatus ?? {
    lifecycle: 'ready',
    host: '127.0.0.1',
    port: 34891,
    canStart: true,
  };
  const projectsByPath = options.projectsByPath ?? {};
  const globalStateStore = new Map();
  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder },
    undefined,
    sidecarStatus,
  );
  const patches = [];
  const calls = [];
  const runtimeCalls = [];
  const managedDataCalls = [];
  const workbenchSyncs = [];
  const outputLines = [];
  const admissionModeCalls = [];
  let activeRoot;
  let activeManifest;
  const deletedProjectPaths = new Set();
  let sessionId;
  let serverManaged = false;
  let adoptionJobId;
  let adoptionJobCompleted = false;
  let trainerAdmissionMode;
  let managedDataPath = path.resolve('C:\\trainer-workspace-tests\\sidecar-data');
  const trainerWorkspace = {
    getRoot() {
      return activeRoot;
    },
    async selectRoot(rootPath) {
      calls.push({ kind: 'root', rootPath });
      activeRoot = rootPath;
      activeManifest = {
        rootPath,
        canonicalRootPath: rootPath,
        rootId: activeManifest?.rootId,
      };
      return activeManifest;
    },
    async setRootIdentity(rootId, canonicalRootPath) {
      activeManifest = {
        ...(activeManifest ?? {}),
        rootPath: activeRoot,
        canonicalRootPath,
        rootId,
      };
    },
    async migrateWorkspaceRoot(targetRoot, options) {
      calls.push({ kind: 'migrate', targetRoot, options });
      activeRoot = targetRoot;
      activeManifest = { rootPath: targetRoot, canonicalRootPath: targetRoot, rootId: activeManifest?.rootId };
      return {
        sourceRoot: 'C:\\trainer-workspace-tests\\root',
        targetRoot,
        projectCount: 1,
        completedAt: '2026-07-11T00:00:00.000Z',
        managedDataRoot: path.join(targetRoot, '.trainer', 'runtime'),
      };
    },
    async backupWorkspace(backupRoot, options) {
      calls.push({ kind: 'backup', backupRoot, options });
      return {
        backupRoot,
        sourceRoot: activeRoot,
        projectCount: 1,
        createdAt: '2026-07-11T00:00:00.000Z',
        managedDataRoot: path.join(backupRoot, '.trainer', 'runtime'),
      };
    },
    async restoreWorkspaceBackup(backupRoot, targetRoot) {
      calls.push({ kind: 'restore', backupRoot, targetRoot });
      activeRoot = targetRoot;
      activeManifest = { rootPath: targetRoot, canonicalRootPath: targetRoot, rootId: activeManifest?.rootId };
      return {
        sourceRoot: 'C:\\trainer-workspace-tests\\root',
        targetRoot,
        projectCount: 1,
        completedAt: '2026-07-11T00:00:00.000Z',
        managedDataRoot: path.join(targetRoot, '.trainer', 'runtime'),
      };
    },
    async rollbackWorkspaceRoot(rootPath) {
      calls.push({ kind: 'rollback', rootPath });
      if (rootPath) {
        activeRoot = rootPath;
        activeManifest = { rootPath, canonicalRootPath: rootPath, rootId: activeManifest?.rootId };
        return;
      }
      activeRoot = undefined;
      activeManifest = undefined;
    },
    async getProject(projectPath) {
      const resolved = path.resolve(projectPath);
      if (deletedProjectPaths.has(resolved)) {
        return undefined;
      }
      const configured = projectsByPath[resolved];
      return {
        fingerprint: 'project-1',
        projectPath: resolved,
        workspaceRoot: activeRoot,
        adoptionMode: 'managed',
        projectId:
          configured?.projectId ??
          bootstrap.memory.workspace?.trainerWorkspace?.projectId ??
          'project-leftover-a',
        contextId:
          configured?.contextId ??
          bootstrap.memory.workspace?.trainerWorkspace?.contextId ??
          bootstrap.memory.workspace?.workspaceId,
        canonicalProjectPath: configured?.canonicalProjectPath ?? resolved,
        updatedAt: '2026-07-11T00:00:00.000Z',
      };
    },
    async deleteManagedProject(projectPath) {
      const resolved = path.resolve(projectPath);
      calls.push({ kind: 'delete', projectPath: resolved });
      deletedProjectPaths.add(resolved);
      const configured = projectsByPath[resolved];
      return {
        fingerprint: 'project-1',
        projectPath: resolved,
        workspaceRoot: activeRoot,
        adoptionMode: 'managed',
        projectId:
          configured?.projectId ??
          bootstrap.memory.workspace?.trainerWorkspace?.projectId ??
          'project-leftover-a',
        contextId:
          configured?.contextId ??
          bootstrap.memory.workspace?.trainerWorkspace?.contextId ??
          bootstrap.memory.workspace?.workspaceId,
        canonicalProjectPath:
          configured?.canonicalProjectPath ??
          bootstrap.memory.workspace?.trainerWorkspace?.projectPath ??
          resolved,
        updatedAt: '2026-07-11T00:00:00.000Z',
      };
    },
    async setProjectAdmission(projectPath, adoptionMode, managedIdentity) {
      calls.push({ kind: 'project', projectPath, adoptionMode, managedIdentity });
      if (managedIdentity) {
        activeManifest = {
          ...(activeManifest ?? {}),
          rootPath: activeRoot,
          canonicalRootPath: activeRoot,
          rootId: managedIdentity.rootId,
        };
      }
      return {
        fingerprint: 'project-1',
        projectPath,
        workspaceRoot: 'C:\\trainer-workspace-tests\\root',
        adoptionMode,
        rootId: managedIdentity?.rootId,
        projectId: managedIdentity?.projectId,
        contextId: managedIdentity?.contextId,
        canonicalProjectPath: managedIdentity?.canonicalProjectPath ?? projectPath,
        legacyAliases: managedIdentity?.legacyAliases ?? [],
        manifestRevision: 1,
        pathRevision: 0,
        identityStatus: managedIdentity ? 'verified' : 'pending',
        updatedAt: '2026-07-11T00:00:00.000Z',
      };
    },
    async recordManagedProvisioningPending(projectPath, reason) {
      calls.push({ kind: 'pending', projectPath, reason });
    },
    getManagedProvisioningPending() {
      return undefined;
    },
    async readWorkspaceManifest() {
      return activeManifest;
    },
    async toSnapshot(projectPath) {
      const projectCall = [...calls].reverse().find((call) => call.kind === 'project');
      if (!activeRoot) {
        return { rootPath: undefined, workspaceReady: false };
      }
      if (projectPath && deletedProjectPaths.has(path.resolve(projectPath))) {
        return { rootPath: activeRoot, workspaceReady: true };
      }
      return {
        rootPath: activeRoot,
        workspaceReady: true,
        currentProject: projectCall
          ? {
              fingerprint: 'project-1',
              projectPath,
              workspaceRoot: activeRoot,
              adoptionMode: projectCall.adoptionMode,
              updatedAt: '2026-07-11T00:00:00.000Z',
            }
          : undefined,
      };
    },
  };
  const hostState = {
    workspace: { trusted: true, workspaceFolder },
    bootstrap,
  };
  return {
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      getStatus() {
        return sidecarStatus;
      },
      async ensureRunning() {
        runtimeCalls.push({ kind: 'ensure-sidecar' });
        return sidecarStatus;
      },
      getManagedDataFolderSnapshot() {
        return {
          configuredPath: managedDataPath,
          effectivePath: managedDataPath,
          defaultPath: path.resolve('C:\\trainer-workspace-tests\\default-sidecar-data'),
          source: 'custom',
          status: 'ready',
        };
      },
      async stop() {
        managedDataCalls.push({ kind: 'stop', path: managedDataPath });
      },
      async restart() {
        managedDataCalls.push({ kind: 'restart', path: managedDataPath });
        return { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true };
      },
      async configureManagedDataFolder(nextPath) {
        managedDataCalls.push({ kind: 'configure', sourcePath: managedDataPath, targetPath: nextPath });
        managedDataPath = nextPath;
        return {
          changed: true,
          previousPath: managedDataPath,
          next: {
            configuredPath: managedDataPath,
            effectivePath: managedDataPath,
            defaultPath: path.resolve('C:\\trainer-workspace-tests\\default-sidecar-data'),
            source: 'custom',
            status: 'ready',
          },
          migration: 'skipped_nonempty_target',
        };
      },
    },
    sidecarClient: {
      setTrainerAdmissionMode(mode) {
        trainerAdmissionMode = mode === 'browse' || mode === 'ignored' ? mode : undefined;
        admissionModeCalls.push(trainerAdmissionMode);
      },
      async postJson(port, requestPath, body) {
        runtimeCalls.push({ kind: 'post', port, requestPath, body, trainerAdmissionMode });
        if (requestPath === '/session/start') {
          return {
            session_id: 'session-admission',
            messages: [],
            memory: {},
            plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          };
        }
        if (requestPath === '/workspace/classify') {
          return {
            folder_role: 'existing_engineering',
            project_type_guess: 'api_service',
            confidence: 0.92,
            why_this_guess: 'The folder contains service and route modules.',
            entry_points: ['server/app/main.py'],
            directory_anchors: ['server/app'],
            core_modules_or_materials: ['server/app/api/routers.py'],
            risk_zones: ['server/app/api/routers.py'],
            training_opportunities: ['Trace a request from route to service.'],
            unknowns: ['Runtime deployment target.'],
            recommended_next_step: 'Start from the API router boundary.',
            classification_method: 'heuristic',
            classified_at: '2026-07-31T00:00:00.000Z',
            root_identity: {
              rootId: 'root-admission',
              rootPath: 'C:\\trainer-workspace-tests\\root',
            },
            project_discovery: { discovery_id: 'discovery-admission' },
          };
        }
        if (requestPath === '/workspace/discovery/decision') {
          adoptionJobId = 'job-admission';
          adoptionJobCompleted = false;
          return {
            project_discovery: { status: 'adoption_requested' },
            project_adoption_job: {
              job_id: adoptionJobId,
              status: 'queued',
              progress: 0.05,
              progress_message: 'Queued for background adoption indexing.',
            },
          };
        }
        if (requestPath === '/memory/transfer/exclude-workspace') {
          return { ok: true, workspace_ids: body?.workspaceIds ?? [] };
        }
        if (requestPath === '/memory/transfer/include-workspace') {
          return { ok: true, workspace_ids: body?.workspaceIds ?? [] };
        }
        throw new Error(`Unexpected POST ${requestPath}`);
      },
      async getJson(port, requestPath) {
        runtimeCalls.push({ kind: 'get', port, requestPath, trainerAdmissionMode });
        if (requestPath.startsWith('/workspace/adoption-job?')) {
          const requestUrl = new URL(requestPath, 'http://127.0.0.1');
          if (!adoptionJobId) {
            const error = new Error('Project adoption job was not found.');
            error.statusCode = 404;
            throw error;
          }
          if (!adoptionJobCompleted) {
            adoptionJobCompleted = true;
            serverManaged = true;
            return {
              project_discovery: { status: 'adopted' },
              project_provisioning: {
                agent_session_id: 'session-provisioned',
                root_id: 'root-admission',
                root_path: requestUrl.searchParams.get('root_path') ?? undefined,
              },
              project_identity: {
                rootId: 'root-admission',
                canonicalRootPath: requestUrl.searchParams.get('root_path') ?? undefined,
                projectId: 'project-admission',
                contextId: 'context-admission',
                canonicalProjectPath: requestUrl.searchParams.get('workspace_id') ?? '',
                legacyAliases: [requestUrl.searchParams.get('workspace_id') ?? ''],
                revisions: { root: 1, project: 1, context: 1 },
                pending: false,
              },
              project_adoption_job: {
                job_id: adoptionJobId,
                status: 'completed',
                progress: 1,
                progress_message: 'Project adoption completed.',
              },
            };
          }
          return {
            project_discovery: { status: 'adopted' },
            project_provisioning: {
              agent_session_id: 'session-provisioned',
              root_id: 'root-admission',
              root_path: requestUrl.searchParams.get('root_path') ?? undefined,
            },
            project_identity: {
              rootId: 'root-admission',
              canonicalRootPath: requestUrl.searchParams.get('root_path') ?? undefined,
              projectId: 'project-admission',
              contextId: 'context-admission',
              canonicalProjectPath: requestUrl.searchParams.get('workspace_id') ?? '',
              legacyAliases: [requestUrl.searchParams.get('workspace_id') ?? ''],
              revisions: { root: 1, project: 1, context: 1 },
              pending: false,
            },
            project_adoption_job: {
              job_id: adoptionJobId,
              status: 'completed',
              progress: 1,
              progress_message: 'Project adoption completed.',
            },
          };
        }
        if (requestPath.startsWith('/workspace/project-provisioning?')) {
          if (serverManaged) {
            return { project_provisioning: { agent_session_id: 'session-provisioned' } };
          }
          const error = new Error('No managed project was found.');
          error.statusCode = 404;
          throw error;
        }
        if (requestPath.startsWith('/memory/summary')) {
          return {
            messages: [],
            memory: {},
            plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          };
        }
        throw new Error(`Unexpected GET ${requestPath}`);
      },
    },
    providerStore: {
      getConfig() {
        return undefined;
      },
      async getApiKey() {
        return undefined;
      },
    },
    workbench: {
      async syncState() {
        workbenchSyncs.push(true);
      },
    },
    outputChannel: {
      appendLine(line) {
        outputLines.push(line);
      },
    },
    trainerWorkspace,
    extensionContext: {
      globalState: {
        get(key) {
          return globalStateStore.get(key);
        },
        async update(key, value) {
          if (value === undefined) {
            globalStateStore.delete(key);
            return;
          }
          globalStateStore.set(key, value);
        },
      },
    },
    getHostState() {
      return hostState;
    },
    getSessionId() {
      return sessionId;
    },
    async setSessionId(nextSessionId) {
      sessionId = nextSessionId;
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
      hostState.bootstrap = {
        ...hostState.bootstrap,
        ...patch,
      };
    },
    __calls: calls,
    __patches: patches,
    __runtimeCalls: runtimeCalls,
    __admissionModeCalls: admissionModeCalls,
    __getTrainerAdmissionMode() {
      return trainerAdmissionMode;
    },
    __managedDataCalls: managedDataCalls,
    __workbenchSyncs: workbenchSyncs,
    __outputLines: outputLines,
    __globalState: globalStateStore,
    __setSidecarStatus(nextStatus) {
      sidecarStatus = nextStatus;
    },
  };
}

test('choosing a Trainer Workspace Root classifies the current project before an admission decision', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { chooseTrainerWorkspaceRootCommand } = loadWithVscodeMock(commandsModulePath, vscodeMock);
  const context = createContext();

  const result = await chooseTrainerWorkspaceRootCommand(context);

  assert.equal(result.ok, true);
  assert.deepEqual(context.__calls, [{ kind: 'root', rootPath: 'C:\\trainer-workspace-tests\\root' }]);
  const admissionPatch = [...context.__patches]
    .reverse()
    .find((patch) => patch?.memory?.workspace?.trainerWorkspace);
  assert.equal(admissionPatch.memory.workspace.trainerWorkspace.status, 'project-found');
  const classifyCalls = context.__runtimeCalls.filter(
    (call) => call.kind === 'post' && call.requestPath === '/workspace/classify',
  );
  assert.equal(classifyCalls.length, 1);
  assert.equal(classifyCalls[0].body.folder_path, path.resolve('C:\\trainer-workspace-tests\\current-project'));
  assert.equal(classifyCalls[0].body.root_path, 'C:\\trainer-workspace-tests\\root');
  const firstLookPatch = [...context.__patches]
    .reverse()
    .find((patch) => patch?.memory?.workspaceUnderstanding?.firstLookSummary);
  assert.equal(firstLookPatch.memory.workspaceUnderstanding.firstLookSummary.folderRole, 'existing_engineering');
  assert.equal(firstLookPatch.memory.workspaceUnderstanding.firstLookSummary.projectTypeGuess, 'api_service');
  assert.equal(
    firstLookPatch.memory.workspaceUnderstanding.firstLookSummary.recommendedNextStep,
    'Start from the API router boundary.',
  );
  assert.equal(
    context.__runtimeCalls.filter((call) => call.kind === 'post' && call.requestPath === '/session/start').length,
    0,
  );
  assert.equal(
    context.__runtimeCalls.filter(
      (call) => call.kind === 'post' && call.requestPath === '/workspace/discovery/decision',
    ).length,
    0,
  );
  assert.deepEqual(context.__managedDataCalls.map((call) => call.kind), [
    'stop',
    'configure',
    'restart',
  ]);
});

test('multi-root project picker chooses an explicit Windows folder without replacing the Trainer root', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\selected-project');
  const { chooseWorkspaceProjectCommand } = loadWithVscodeMock(commandsModulePath, vscodeMock);
  const context = createContext();
  await context.trainerWorkspace.selectRoot('C:\\trainer-workspace-tests\\trainer-root');

  const result = await chooseWorkspaceProjectCommand(context);

  assert.equal(result.ok, true);
  const classifyCall = context.__runtimeCalls.find(
    (call) => call.kind === 'post' && call.requestPath === '/workspace/classify',
  );
  assert.equal(classifyCall.body.folder_path, 'C:\\trainer-workspace-tests\\selected-project');
  assert.equal(classifyCall.body.workspace_id, 'C:\\trainer-workspace-tests\\selected-project');
  assert.equal(classifyCall.body.root_path, 'C:\\trainer-workspace-tests\\trainer-root');
  assert.notEqual(classifyCall.body.folder_path, classifyCall.body.root_path);
});

test('project admission keeps the current VS Code folder scoped to the chosen mode', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { browseWorkspaceProjectCommand, chooseTrainerWorkspaceRootCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  const runtimeCallsAfterSetup = context.__runtimeCalls.length;
  const workbenchSyncsAfterSetup = context.__workbenchSyncs.length;

  const result = await browseWorkspaceProjectCommand(context);

  assert.equal(result.ok, true);
  assert.equal(context.__calls.at(-1).kind, 'project');
  assert.equal(context.__calls.at(-1).adoptionMode, 'browse');
  const admissionPatch = [...context.__patches]
    .reverse()
    .find((patch) => patch?.memory?.workspace?.trainerWorkspace);
  assert.equal(admissionPatch.memory.workspace.trainerWorkspace.status, 'browse');
  assert.equal(context.__runtimeCalls.length, runtimeCallsAfterSetup + 2);
  assert.ok(
    context.__runtimeCalls.some(
      (call) => call.kind === 'get' && call.requestPath.startsWith('/workspace/project-provisioning?'),
    ),
  );
  assert.equal(context.__workbenchSyncs.length, workbenchSyncsAfterSetup);
});

test('managing the current project starts the recovered session after admission', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { adoptWorkspaceProjectCommand, chooseTrainerWorkspaceRootCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  const sessionStartsBeforeAdmission = context.__runtimeCalls.filter(
    (call) => call.kind === 'post' && call.requestPath === '/session/start',
  ).length;
  const workbenchSyncsBeforeAdmission = context.__workbenchSyncs.length;

  const result = await adoptWorkspaceProjectCommand(context);

  assert.equal(result.ok, true);
  assert.equal(context.__calls.at(-1).adoptionMode, 'managed');
  assert.equal(context.__calls.at(-1).managedIdentity.projectId, 'project-admission');
  assert.equal(context.__calls.at(-1).managedIdentity.contextId, 'context-admission');
  assert.equal(
    context.__runtimeCalls.filter((call) => call.kind === 'post' && call.requestPath === '/session/start').length,
    sessionStartsBeforeAdmission + 1,
  );
  assert.ok(
    context.__runtimeCalls.some((call) => call.kind === 'post' && call.requestPath === '/workspace/classify'),
  );
  assert.ok(
    context.__runtimeCalls.some(
      (call) => call.kind === 'post' && call.requestPath === '/workspace/discovery/decision',
    ),
  );
  const classifyCall = [...context.__runtimeCalls].reverse().find(
    (call) => call.kind === 'post' && call.requestPath === '/workspace/classify',
  );
  const decisionCall = context.__runtimeCalls.find(
    (call) => call.kind === 'post' && call.requestPath === '/workspace/discovery/decision',
  );
  assert.equal(classifyCall.body.root_path, 'C:\\trainer-workspace-tests\\root');
  assert.equal(decisionCall.body.root_path, 'C:\\trainer-workspace-tests\\root');
  assert.notEqual(classifyCall.body.folder_path, classifyCall.body.root_path);
  assert.equal(
    context.__runtimeCalls.filter((call) => call.kind === 'post' && call.requestPath === '/plan/generate')
      .length,
    0,
  );
  assert.equal(context.__workbenchSyncs.length, workbenchSyncsBeforeAdmission + 1);
});

test('managed admission forwards the current response language to both first-look requests', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { adoptWorkspaceProjectCommand, chooseTrainerWorkspaceRootCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  context.getHostState().bootstrap.memory.workspace = {
    ...(context.getHostState().bootstrap.memory.workspace ?? {}),
    responseLanguage: 'en-US',
  };
  await chooseTrainerWorkspaceRootCommand(context);

  const result = await adoptWorkspaceProjectCommand(context, { responseLanguage: 'ja-JP' });

  assert.equal(result.ok, true);
  const sessionStartCall = context.__runtimeCalls.find(
    (call) => call.kind === 'post' && call.requestPath === '/session/start',
  );
  const classifyCall = [...context.__runtimeCalls].reverse().find(
    (call) => call.kind === 'post' && call.requestPath === '/workspace/classify',
  );
  assert.equal(sessionStartCall.body.response_language, 'ja-JP');
  assert.equal(sessionStartCall.body.workspace_trusted, true);
  assert.equal(sessionStartCall.body.remote_name, '');
  assert.equal(classifyCall.body.response_language, 'ja-JP');
});

test('managed admission ignores an invalid requested language and uses the saved language', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { adoptWorkspaceProjectCommand, chooseTrainerWorkspaceRootCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  context.getHostState().bootstrap.memory.workspace = {
    ...(context.getHostState().bootstrap.memory.workspace ?? {}),
    responseLanguage: 'pt-BR',
  };
  await chooseTrainerWorkspaceRootCommand(context);

  const result = await adoptWorkspaceProjectCommand(context, { responseLanguage: 'unsupported-language' });

  assert.equal(result.ok, true);
  const sessionStartCall = context.__runtimeCalls.find(
    (call) => call.kind === 'post' && call.requestPath === '/session/start',
  );
  const classifyCall = context.__runtimeCalls.find(
    (call) => call.kind === 'post' && call.requestPath === '/workspace/classify',
  );
  assert.equal(sessionStartCall.body.response_language, 'pt-BR');
  assert.equal(classifyCall.body.response_language, 'pt-BR');
});

test('explicit adoption briefly unlocks only its required setup requests from browse or ignored mode', async () => {
  for (const readOnlyMode of ['browse', 'ignored']) {
    const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
    const {
      adoptWorkspaceProjectCommand,
      browseWorkspaceProjectCommand,
      chooseTrainerWorkspaceRootCommand,
      ignoreWorkspaceProjectCommand,
    } = loadWithVscodeMock(commandsModulePath, vscodeMock);
    const context = createContext();
    await chooseTrainerWorkspaceRootCommand(context);
    await (readOnlyMode === 'browse'
      ? browseWorkspaceProjectCommand(context)
      : ignoreWorkspaceProjectCommand(context));
    assert.equal(context.__getTrainerAdmissionMode(), readOnlyMode);

    const requestStart = context.__runtimeCalls.length;
    const modeTransitionStart = context.__admissionModeCalls.length;
    const result = await adoptWorkspaceProjectCommand(context);

    assert.equal(result.ok, true);
    const adoptionRequests = context.__runtimeCalls
      .slice(requestStart)
      .filter((call) => call.kind === 'post');
    assert.deepEqual(
      adoptionRequests.map((call) => call.trainerAdmissionMode),
      [undefined, undefined, undefined, undefined],
    );
    assert.equal(
      adoptionRequests.some((call) => call.requestPath === '/memory/transfer/include-workspace'),
      true,
    );
    assert.deepEqual(context.__admissionModeCalls.slice(modeTransitionStart, -1), [
      undefined,
      readOnlyMode,
      undefined,
      readOnlyMode,
      undefined,
      readOnlyMode,
      undefined,
      readOnlyMode,
      undefined,
      readOnlyMode,
    ]);
    assert.equal(context.__getTrainerAdmissionMode(), undefined);
    assert.equal(context.__calls.at(-1).adoptionMode, 'managed');
  }
});

test('a failed explicit adoption restores the original read-only admission', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { adoptWorkspaceProjectCommand, chooseTrainerWorkspaceRootCommand, ignoreWorkspaceProjectCommand } =
    loadWithVscodeMock(commandsModulePath, vscodeMock);
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  await ignoreWorkspaceProjectCommand(context);
  const originalPostJson = context.sidecarClient.postJson;
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    if (requestPath === '/workspace/classify') {
      context.__runtimeCalls.push({ kind: 'post', port, requestPath, body, trainerAdmissionMode: undefined });
      throw new Error('classification failed');
    }
    return originalPostJson(port, requestPath, body);
  };

  const transitionStart = context.__admissionModeCalls.length;
  const result = await adoptWorkspaceProjectCommand(context);

  assert.equal(result.ok, false);
  assert.equal(context.__getTrainerAdmissionMode(), 'ignored');
  assert.deepEqual(context.__admissionModeCalls.slice(transitionStart), [
    undefined,
    'ignored',
  ]);
});

test('managed admission returns a safe localized conflict classification', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { adoptWorkspaceProjectCommand, chooseTrainerWorkspaceRootCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  const originalPostJson = context.sidecarClient.postJson;
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    if (requestPath === '/workspace/classify') {
      context.__runtimeCalls.push({ kind: 'post', port, requestPath, body });
      const error = new Error('Sidecar request failed (409). C:\\Users\\secret\\sk-live-key');
      error.statusCode = 409;
      error.metadata = {
        code: 'root_id_mismatch',
        category: 'workspace_root',
        pathState: 'unknown',
      };
      throw error;
    }
    return originalPostJson(port, requestPath, body);
  };

  const result = await adoptWorkspaceProjectCommand(context, { responseLanguage: 'zh-CN' });

  assert.equal(result.ok, false);
  assert.deepEqual(result.data, {
    errorCode: 'root_id_mismatch',
    category: 'workspace_root',
    pathState: 'unknown',
  });
  assert.match(result.message, /root_id_mismatch/);
  assert.match(result.message, /重新选择|匹配/);
  assert.doesNotMatch(result.message, /secret|sk-live-key|C:\\\\Users/);
  assert.match(context.__outputLines.at(-1), /code=root_id_mismatch category=workspace_root path_state=unknown/);
  assert.doesNotMatch(context.__outputLines.at(-1), /secret|sk-live-key|C:\\\\Users/);
});

test('managed admission rejects a backend root that no longer matches the selected workspace', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { adoptWorkspaceProjectCommand, chooseTrainerWorkspaceRootCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  const originalGetJson = context.sidecarClient.getJson;
  context.sidecarClient.getJson = async (port, requestPath) => {
    const response = await originalGetJson(port, requestPath);
    if (!requestPath.startsWith('/workspace/adoption-job?')) {
      return response;
    }
    return {
      ...response,
      project_provisioning: {
        ...response.project_provisioning,
        root_path: 'C:\\trainer-workspace-tests\\other-root',
      },
      project_identity: {
        ...response.project_identity,
        canonicalRootPath: 'C:\\trainer-workspace-tests\\other-root',
      },
    };
  };

  const result = await adoptWorkspaceProjectCommand(context);

  assert.equal(result.ok, false);
  assert.equal(context.__calls.some((call) => call.kind === 'project'), false);
  assert.equal(context.__calls.some((call) => call.kind === 'pending'), true);
});

test('managing a project reports retry_required without writing a managed admission', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { adoptWorkspaceProjectCommand, chooseTrainerWorkspaceRootCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  const originalPostJson = context.sidecarClient.postJson;
  const originalGetJson = context.sidecarClient.getJson;
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    if (requestPath === '/workspace/discovery/decision') {
      context.__runtimeCalls.push({ kind: 'post', port, requestPath, body });
      return {
        project_discovery: { status: 'adoption_requested' },
        project_adoption_job: {
          job_id: 'job-admission',
          status: 'queued',
          progress: 0.05,
          progress_message: 'Queued for background adoption indexing.',
        },
      };
    }
    return originalPostJson(port, requestPath, body);
  };
  context.sidecarClient.getJson = async (port, requestPath) => {
    if (requestPath.startsWith('/workspace/adoption-job?')) {
      context.__runtimeCalls.push({ kind: 'get', port, requestPath });
      return {
        project_adoption_job: {
          job_id: 'job-admission',
          status: 'retry_required',
          progress: 1,
          progress_message: 'Trainer adoption indexing needs retry.',
          retry_reason: 'inventory budget exhausted',
        },
      };
    }
    return originalGetJson(port, requestPath);
  };

  const result = await adoptWorkspaceProjectCommand(context);

  assert.equal(result.ok, false);
  assert.equal(context.__calls.some((call) => call.kind === 'project'), false);
  assert.equal(context.__calls.some((call) => call.kind === 'pending'), true);
  assert.match(result.message, /retry/i);
});

test('managing a project rejects completed adoption when discovery is not adopted', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { adoptWorkspaceProjectCommand, chooseTrainerWorkspaceRootCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  const originalPostJson = context.sidecarClient.postJson;
  const originalGetJson = context.sidecarClient.getJson;
  const completedNonAdoptedResponse = {
    project_discovery: { status: 'adoption_requested' },
    project_adoption_job: {
      job_id: 'job-admission',
      status: 'completed',
      progress: 1,
      progress_message: 'Project adoption completed.',
    },
    project_provisioning: {
      agent_session_id: 'session-provisioned',
      root_id: 'root-admission',
      root_path: 'C:\\trainer-workspace-tests\\root',
    },
    project_identity: {
      rootId: 'root-admission',
      canonicalRootPath: 'C:\\trainer-workspace-tests\\root',
      projectId: 'project-admission',
      contextId: 'context-admission',
      canonicalProjectPath: path.resolve('C:\\trainer-workspace-tests\\current-project'),
      legacyAliases: [path.resolve('C:\\trainer-workspace-tests\\current-project')],
      revisions: { root: 1, project: 1, context: 1 },
      pending: false,
    },
  };
  context.sidecarClient.postJson = async (port, requestPath, body) => {
    if (requestPath === '/workspace/discovery/decision') {
      context.__runtimeCalls.push({ kind: 'post', port, requestPath, body });
      return completedNonAdoptedResponse;
    }
    return originalPostJson(port, requestPath, body);
  };
  context.sidecarClient.getJson = async (port, requestPath) => {
    if (requestPath.startsWith('/workspace/adoption-job?')) {
      context.__runtimeCalls.push({ kind: 'get', port, requestPath });
      return completedNonAdoptedResponse;
    }
    return originalGetJson(port, requestPath);
  };

  const result = await adoptWorkspaceProjectCommand(context);

  assert.equal(result.ok, false);
  assert.equal(context.__calls.some((call) => call.kind === 'project'), false);
  assert.equal(context.__calls.some((call) => call.kind === 'pending'), true);
  assert.match(result.message, /required project state|did not start/i);
});

test('managed admission polls until the adoption job completes', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { adoptWorkspaceProjectCommand, chooseTrainerWorkspaceRootCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  const originalGetJson = context.sidecarClient.getJson;
  let pollCount = 0;
  context.sidecarClient.getJson = async (port, requestPath) => {
    if (requestPath.startsWith('/workspace/adoption-job?')) {
      pollCount += 1;
      context.__runtimeCalls.push({ kind: 'get', port, requestPath });
      if (pollCount === 1) {
        return {
          project_adoption_job: {
            job_id: 'job-admission',
            status: 'running',
            progress: 0.5,
            progress_message: 'Still scanning.',
          },
        };
      }
      return {
        project_discovery: { status: 'adopted' },
        project_provisioning: {
          agent_session_id: 'session-provisioned',
          root_id: 'root-admission',
          root_path: 'C:\\trainer-workspace-tests\\root',
        },
        project_identity: {
          rootId: 'root-admission',
          canonicalRootPath: 'C:\\trainer-workspace-tests\\root',
          projectId: 'project-admission',
          contextId: 'context-admission',
          canonicalProjectPath: path.resolve('C:\\trainer-workspace-tests\\current-project'),
          legacyAliases: [path.resolve('C:\\trainer-workspace-tests\\current-project')],
          revisions: { root: 1, project: 1, context: 1 },
          pending: false,
        },
        project_adoption_job: {
          job_id: 'job-admission',
          status: 'completed',
          progress: 1,
          progress_message: 'Project adoption completed.',
        },
      };
    }
    return originalGetJson(port, requestPath);
  };

  const result = await adoptWorkspaceProjectCommand(context);

  assert.equal(result.ok, true);
  assert.equal(pollCount, 2);
  assert.equal(
    context.__runtimeCalls.filter((call) => call.kind === 'get' && call.requestPath.startsWith('/workspace/adoption-job?')).length,
    2,
  );
  assert.equal(context.__calls.at(-1).adoptionMode, 'managed');
});

test('managed admission times out when the adoption job never completes', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { adoptWorkspaceProjectCommand, chooseTrainerWorkspaceRootCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  const originalGetJson = context.sidecarClient.getJson;
  context.sidecarClient.getJson = async (port, requestPath) => {
    if (requestPath.startsWith('/workspace/adoption-job?')) {
      context.__runtimeCalls.push({ kind: 'get', port, requestPath });
      return {
        project_adoption_job: {
          job_id: 'job-admission',
          status: 'running',
          progress: 0.5,
          progress_message: 'Still scanning.',
        },
      };
    }
    return originalGetJson(port, requestPath);
  };

  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  const originalDateNow = Date.now;
  let fakeNow = originalDateNow();
  globalThis.setTimeout = (callback, ms, ...args) => {
    fakeNow += Number(ms);
    callback(...args);
    return 0;
  };
  globalThis.clearTimeout = () => undefined;
  Date.now = () => fakeNow;

  try {
    const result = await adoptWorkspaceProjectCommand(context);
    assert.equal(result.ok, false);
    assert.match(result.message, /timed out/i);
  } finally {
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
    Date.now = originalDateNow;
  }
});

test('managed admission retries after a server identity failure without a false local managed state', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { adoptWorkspaceProjectCommand, chooseTrainerWorkspaceRootCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  const originalGetJson = context.sidecarClient.getJson;
  let rejectFirstIdentity = true;
  context.sidecarClient.getJson = async (port, requestPath) => {
    if (requestPath.startsWith('/workspace/adoption-job?') && rejectFirstIdentity) {
      rejectFirstIdentity = false;
      context.__runtimeCalls.push({ kind: 'get', port, requestPath });
      return {
        project_discovery: { status: 'adopted' },
        project_provisioning: {
          agent_session_id: 'session-provisioned',
          root_id: 'root-admission',
          root_path: 'C:\\trainer-workspace-tests\\root',
        },
        project_adoption_job: {
          job_id: 'job-admission',
          status: 'completed',
          progress: 1,
          progress_message: 'Project adoption completed.',
        },
      };
    }
    return originalGetJson(port, requestPath);
  };

  const failed = await adoptWorkspaceProjectCommand(context);
  const recovered = await adoptWorkspaceProjectCommand(context);

  assert.equal(failed.ok, false);
  assert.equal(recovered.ok, true);
  assert.equal(context.__calls.filter((call) => call.kind === 'project').length, 1);
  assert.equal(context.__calls.filter((call) => call.kind === 'pending').length, 1);
  assert.equal(context.__calls.at(-1).managedIdentity.contextId, 'context-admission');
});

test('ignoring the current project keeps setup recoverable without starting a session', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { chooseTrainerWorkspaceRootCommand, ignoreWorkspaceProjectCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  const runtimeCallsAfterSetup = context.__runtimeCalls.length;

  const result = await ignoreWorkspaceProjectCommand(context);

  assert.equal(result.ok, true);
  const admissionPatch = [...context.__patches]
    .reverse()
    .find((patch) => patch?.memory?.workspace?.trainerWorkspace);
  assert.equal(admissionPatch.memory.workspace.trainerWorkspace.status, 'ignored');
  assert.equal(context.__runtimeCalls.length, runtimeCallsAfterSetup + 2);
});

test('managed projects cannot be downgraded to browse or ignored locally', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const {
    adoptWorkspaceProjectCommand,
    browseWorkspaceProjectCommand,
    chooseTrainerWorkspaceRootCommand,
    ignoreWorkspaceProjectCommand,
  } = loadWithVscodeMock(commandsModulePath, vscodeMock);
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  assert.equal((await adoptWorkspaceProjectCommand(context)).ok, true);
  const admissionsBeforeDowngrade = context.__calls.filter((call) => call.kind === 'project').length;

  const browse = await browseWorkspaceProjectCommand(context);
  const ignored = await ignoreWorkspaceProjectCommand(context);

  assert.equal(browse.ok, false);
  assert.equal(ignored.ok, false);
  assert.match(browse.message, /already managed/i);
  assert.match(ignored.message, /already managed/i);
  assert.equal(
    context.__calls.filter((call) => call.kind === 'project').length,
    admissionsBeforeDowngrade,
  );
  const admissionPatch = [...context.__patches]
    .reverse()
    .find((patch) => patch?.memory?.workspace?.trainerWorkspace);
  assert.equal(admissionPatch.memory.workspace.trainerWorkspace.status, 'managed');
});

test('a failed provisioning lookup does not downgrade a local project admission', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { browseWorkspaceProjectCommand, chooseTrainerWorkspaceRootCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  context.sidecarClient.getJson = async (port, requestPath) => {
    context.__runtimeCalls.push({ kind: 'get', port, requestPath });
    throw new Error('sidecar unavailable');
  };

  const result = await browseWorkspaceProjectCommand(context);

  assert.equal(result.ok, false);
  assert.match(result.message, /could not verify/i);
  assert.equal(context.__calls.some((call) => call.kind === 'project'), false);
});

test('workspace recovery commands keep backups non-disruptive and refresh after migration or restore', async () => {
  const vscodeMock = createVscodeMock(
    'C:\\trainer-workspace-tests\\migrated',
    'C:\\trainer-workspace-tests\\backup',
    'C:\\trainer-workspace-tests\\backup',
    'C:\\trainer-workspace-tests\\restored',
  );
  const {
    backupTrainerWorkspaceCommand,
    migrateTrainerWorkspaceRootCommand,
    restoreTrainerWorkspaceBackupCommand,
  } = loadWithVscodeMock(commandsModulePath, vscodeMock);
  const context = createContext();

  const migration = await migrateTrainerWorkspaceRootCommand(context);
  const backup = await backupTrainerWorkspaceCommand(context);
  const restoration = await restoreTrainerWorkspaceBackupCommand(context);

  assert.equal(migration.ok, true);
  assert.equal(backup.ok, true);
  assert.equal(restoration.ok, true);
  assert.deepEqual(context.__calls, [
    {
      kind: 'migrate',
      targetRoot: 'C:\\trainer-workspace-tests\\migrated',
      options: { managedDataRoot: path.resolve('C:\\trainer-workspace-tests\\sidecar-data') },
    },
    {
      kind: 'backup',
      backupRoot: 'C:\\trainer-workspace-tests\\backup',
      options: { managedDataRoot: path.resolve('C:\\trainer-workspace-tests\\migrated', '.trainer', 'runtime') },
    },
    {
      kind: 'restore',
      backupRoot: 'C:\\trainer-workspace-tests\\backup',
      targetRoot: 'C:\\trainer-workspace-tests\\restored',
    },
  ]);
  const admissionPatch = [...context.__patches]
    .reverse()
    .find((patch) => patch?.memory?.workspace?.trainerWorkspace);
  assert.equal(admissionPatch.memory.workspace.trainerWorkspace.status, 'project-found');
  assert.deepEqual(context.__managedDataCalls.map((call) => call.kind), [
    'stop',
    'configure',
    'restart',
    'stop',
    'restart',
    'stop',
    'configure',
    'restart',
  ]);
});

test('restore does not leftover-fill workspace A identity onto a different workspace', async () => {
  const vscodeMock = createVscodeMock(
    'C:\\trainer-workspace-tests\\backup',
    'C:\\trainer-workspace-tests\\restored',
  );
  const { restoreTrainerWorkspaceBackupCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  const bootstrap = context.getHostState().bootstrap;
  bootstrap.memory.workspace = {
    ...bootstrap.memory.workspace,
    workspaceId: 'workspace-a',
    projectContext: 'Keep the leftover A project context',
    trainerWorkspace: {
      status: 'managed',
      rootPath: 'F:\\workspace-a',
      projectId: 'project-leftover-a',
      projectName: 'Keep the leftover A project',
      projectPath: 'F:\\workspace-a',
      identityStatus: 'verified',
      contextId: 'workspace-a',
    },
  };
  bootstrap.plan = {
    id: 'plan-formal-old',
    title: 'Keep the current stage',
    frozen: false,
    cadence: 'weekly',
    summary: 'Leftover formal summary of the old stage path',
    currentStep: 'Keep one auth check',
    stages: [],
  };
  bootstrap.task = {
    id: 'task-formal-old',
    title: 'Ship one auth check',
    description: 'Keep the leftover A task',
    constraints: [],
    acceptanceCriteria: [],
    nextActionLabel: 'Evaluate the leftover A file',
  };
  bootstrap.workspaceTrainingState = {
    workspaceId: 'workspace-a',
    selectedCardId: 'card-leftover-a',
    selectedCardTitle: 'Review the refresh path',
  };

  const restoration = await restoreTrainerWorkspaceBackupCommand(context);
  const next = context.getHostState().bootstrap;

  assert.equal(restoration.ok, true);
  assert.notEqual(next.plan.title, 'Keep the current stage');
  assert.notEqual(next.plan.id, 'plan-formal-old');
  assert.notEqual(next.task.title, 'Ship one auth check');
  assert.notEqual(next.task.id, 'task-formal-old');
  assert.notEqual(next.workspaceTrainingState?.selectedCardId, 'card-leftover-a');
  assert.notEqual(next.memory.workspace.projectContext, 'Keep the leftover A project context');
  assert.notEqual(next.memory.workspace.trainerWorkspace?.projectId, 'project-leftover-a');
  assert.notEqual(next.memory.workspace.trainerWorkspace?.contextId, 'workspace-a');
});

function seedLeftoverAIdentity(bootstrap, workspaceId) {
  bootstrap.memory.workspace = {
    ...bootstrap.memory.workspace,
    workspaceId,
    projectContext: 'Keep the leftover A project context',
    trainerWorkspace: {
      status: 'managed',
      rootPath: 'F:\\workspace-a',
      projectId: 'project-leftover-a',
      projectName: 'Keep the leftover A project',
      projectPath: 'F:\\workspace-a',
      identityStatus: 'verified',
      contextId: workspaceId,
    },
  };
  bootstrap.plan = {
    id: 'plan-formal-old',
    title: 'Keep the current stage',
    frozen: false,
    cadence: 'weekly',
    summary: 'Leftover formal summary of the old stage path',
    currentStep: 'Keep one auth check',
    stages: [],
  };
  bootstrap.task = {
    id: 'task-formal-old',
    title: 'Ship one auth check',
    description: 'Keep the leftover A task',
    constraints: [],
    acceptanceCriteria: [],
    nextActionLabel: 'Evaluate the leftover A file',
  };
  bootstrap.workspaceTrainingState = {
    workspaceId,
    selectedCardId: 'card-leftover-a',
    selectedCardTitle: 'Review the refresh path',
    latestTransferState: {
      concept: 'Keep the leftover A transfer skill',
      state: 'awaiting_second_scene',
      sceneCount: 1,
      workspaceIds: [workspaceId],
      sceneKeys: ['default'],
      why: 'Keep the leftover A transfer why',
      next: 'Keep the leftover A transfer next',
    },
  };
  bootstrap.memory.workspace.latestTransferState = bootstrap.workspaceTrainingState.latestTransferState;
}

test('ignore leaves Trainer without leftover A identity or an invented plan', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { chooseTrainerWorkspaceRootCommand, ignoreWorkspaceProjectCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  const leftoverWorkspaceId = path.resolve('C:\\trainer-workspace-tests\\current-project');
  seedLeftoverAIdentity(context.getHostState().bootstrap, leftoverWorkspaceId);

  const result = await ignoreWorkspaceProjectCommand(context);
  const next = context.getHostState().bootstrap;

  assert.equal(result.ok, true);
  assert.equal(next.memory.workspace.trainerWorkspace?.status, 'ignored');
  assert.equal(next.plan.title, '');
  assert.equal(next.plan.id, '');
  assert.notEqual(next.plan.title, 'Keep the current stage');
  assert.equal(next.task.title, '');
  assert.notEqual(next.task.title, 'Ship one auth check');
  assert.equal(next.workspaceTrainingState?.selectedCardId, undefined);
  assert.notEqual(next.workspaceTrainingState?.selectedCardId, 'card-leftover-a');
  assert.notEqual(next.memory.workspace.projectContext, 'Keep the leftover A project context');
  assert.notEqual(next.memory.workspace.trainerWorkspace?.projectId, 'project-leftover-a');
});

test('failed restore rollback does not leftover-fill workspace A identity onto an empty workspace', async () => {
  const vscodeMock = createVscodeMock(
    'C:\\trainer-workspace-tests\\backup',
    'C:\\trainer-workspace-tests\\restored',
  );
  const { restoreTrainerWorkspaceBackupCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  seedLeftoverAIdentity(context.getHostState().bootstrap, 'workspace-a');
  context.trainerWorkspace.restoreWorkspaceBackup = async (backupRoot, targetRoot) => {
    context.__calls.push({ kind: 'restore', backupRoot, targetRoot });
    throw new Error('restore failed');
  };

  await assert.rejects(
    () => restoreTrainerWorkspaceBackupCommand(context),
    /restore failed/,
  );
  const next = context.getHostState().bootstrap;

  assert.equal(context.__calls.some((call) => call.kind === 'rollback'), true);
  assert.equal(next.plan.title, '');
  assert.equal(next.plan.id, '');
  assert.notEqual(next.plan.title, 'Keep the current stage');
  assert.equal(next.task.title, '');
  assert.notEqual(next.task.title, 'Ship one auth check');
  assert.equal(next.workspaceTrainingState?.selectedCardId, undefined);
  assert.notEqual(next.workspaceTrainingState?.selectedCardId, 'card-leftover-a');
  assert.notEqual(next.memory.workspace.projectContext, 'Keep the leftover A project context');
});

test('delete A leaves Trainer without leftover A identity or an invented plan', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { chooseTrainerWorkspaceRootCommand, deleteWorkspaceProjectCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  const leftoverWorkspaceId = path.resolve('C:\\trainer-workspace-tests\\current-project');
  seedLeftoverAIdentity(context.getHostState().bootstrap, leftoverWorkspaceId);

  const result = await deleteWorkspaceProjectCommand(context);
  const next = context.getHostState().bootstrap;

  assert.equal(result.ok, true);
  assert.equal(context.__calls.some((call) => call.kind === 'delete'), true);
  assert.notEqual(next.memory.workspace.trainerWorkspace?.status, 'ignored');
  assert.notEqual(next.memory.workspace.trainerWorkspace?.status, 'managed');
  assert.equal(next.plan.title, '');
  assert.equal(next.plan.id, '');
  assert.notEqual(next.plan.id, 'plan-pending');
  assert.notEqual(next.plan.title, '计划尚未开始');
  assert.notEqual(next.plan.title, 'Keep the current stage');
  assert.equal(next.task.title, '');
  assert.notEqual(next.task.title, 'Ship one auth check');
  assert.equal(next.workspaceTrainingState?.selectedCardId, undefined);
  assert.notEqual(next.workspaceTrainingState?.selectedCardId, 'card-leftover-a');
  assert.notEqual(next.memory.workspace.projectContext, 'Keep the leftover A project context');
  assert.notEqual(next.memory.workspace.trainerWorkspace?.projectId, 'project-leftover-a');
  assert.notEqual(next.memory.workspace.trainerWorkspace?.contextId, leftoverWorkspaceId);
  assert.equal(next.workspaceTrainingState?.latestTransferState, undefined);
  assert.equal(next.memory.workspace.latestTransferState, undefined);
  assert.notEqual(next.workspaceTrainingState?.latestTransferState?.state, 'transferable');
  assert.notEqual(next.workspaceTrainingState?.latestTransferState?.concept, 'Keep the leftover A transfer skill');
  assert.equal(
    context.__runtimeCalls.some(
      (call) => call.kind === 'post' && call.requestPath === '/memory/transfer/exclude-workspace',
    ),
    true,
  );
});

test('delete A does not leftover-fill workspace A identity onto workspace B', async () => {
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { chooseTrainerWorkspaceRootCommand, deleteWorkspaceProjectCommand } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const { failClosedWorkbenchAfterWorkspaceTransfer } = require(workbenchDataModulePath);
  const context = createContext();
  await chooseTrainerWorkspaceRootCommand(context);
  seedLeftoverAIdentity(context.getHostState().bootstrap, 'workspace-a');

  const result = await deleteWorkspaceProjectCommand(context);
  assert.equal(result.ok, true);

  const ontoB = failClosedWorkbenchAfterWorkspaceTransfer(
    context.getHostState().bootstrap,
    'workspace-b',
  );

  assert.notEqual(ontoB.plan?.title, 'Keep the current stage');
  assert.notEqual(ontoB.plan?.id, 'plan-formal-old');
  assert.notEqual(ontoB.task?.title, 'Ship one auth check');
  assert.notEqual(ontoB.task?.id, 'task-formal-old');
  assert.notEqual(ontoB.workspaceTrainingState?.selectedCardId, 'card-leftover-a');
  assert.notEqual(ontoB.memory?.workspace?.projectContext, 'Keep the leftover A project context');
  assert.notEqual(ontoB.memory?.workspace?.trainerWorkspace?.projectId, 'project-leftover-a');
  assert.notEqual(ontoB.plan?.id, 'plan-pending');
  assert.notEqual(ontoB.plan?.title, '计划尚未开始');
  assert.equal(ontoB.workspaceTrainingState?.latestTransferState, undefined);
  assert.equal(ontoB.memory?.workspace?.latestTransferState, undefined);
  assert.notEqual(ontoB.workspaceTrainingState?.latestTransferState?.state, 'transferable');
  assert.notEqual(ontoB.workspaceTrainingState?.latestTransferState?.concept, 'Keep the leftover A transfer skill');
  assert.equal(
    context.__runtimeCalls.some(
      (call) => call.kind === 'post' && call.requestPath === '/memory/transfer/exclude-workspace',
    ),
    true,
  );
});

test('delete A demotes B transferable and queues exclude when sidecar is not ready', async () => {
  const projectA = path.resolve('C:\\trainer-workspace-tests\\project-a');
  const vscodeMock = createVscodeMock('C:\\trainer-workspace-tests\\root');
  const { deleteWorkspaceProjectCommand, flushPendingTransferPromotionScope } = loadWithVscodeMock(
    commandsModulePath,
    vscodeMock,
  );
  const context = createContext({
    sidecarStatus: { lifecycle: 'starting', host: '127.0.0.1', canStart: true },
    projectsByPath: {
      [projectA]: {
        projectId: 'project-a',
        contextId: 'workspace-a',
        canonicalProjectPath: projectA,
      },
    },
  });
  const transferable = {
    concept: 'Keep one auth check',
    state: 'transferable',
    sceneCount: 2,
    workspaceIds: ['workspace-a', 'workspace-b'],
    sceneKeys: ['default', 'workspace:workspace-a'],
    why: '"Keep one auth check" has evidence in more than one scene.',
    next: 'Schedule a review, or apply it in a new challenge.',
  };
  context.getHostState().bootstrap.memory.workspace = {
    ...(context.getHostState().bootstrap.memory.workspace ?? {}),
    workspaceId: 'workspace-b',
    latestTransferState: transferable,
    trainerWorkspace: {
      status: 'managed',
      projectId: 'project-b',
      contextId: 'workspace-b',
      projectPath: path.resolve('C:\\trainer-workspace-tests\\current-project'),
      canonicalProjectPath: path.resolve('C:\\trainer-workspace-tests\\current-project'),
    },
  };
  context.getHostState().bootstrap.workspaceTrainingState = {
    workspaceId: 'workspace-b',
    latestTransferState: transferable,
  };

  const result = await deleteWorkspaceProjectCommand(context, { projectPath: projectA });
  const next = context.getHostState().bootstrap;

  assert.equal(result.ok, true);
  assert.equal(
    context.__runtimeCalls.some(
      (call) => call.kind === 'post' && call.requestPath === '/memory/transfer/exclude-workspace',
    ),
    false,
  );
  assert.equal(next.workspaceTrainingState?.latestTransferState?.state, 'awaiting_second_scene');
  assert.equal(next.memory.workspace.latestTransferState?.state, 'awaiting_second_scene');
  assert.notEqual(next.workspaceTrainingState?.latestTransferState?.state, 'transferable');
  assert.notEqual(next.memory.workspace.latestTransferState?.state, 'transferable');
  assert.deepEqual(next.workspaceTrainingState?.latestTransferState?.workspaceIds, ['workspace-b']);
  assert.equal(next.workspaceTrainingState?.latestTransferState?.sceneCount, 1);
  assert.notEqual(next.plan?.title, 'Trainer plan for Understand and advance the leftover project.');
  assert.notEqual(next.task?.title, 'Ship one invented task');
  const pending = context.__globalState.get('trainer.transfer.pendingPromotionScope');
  assert.ok(pending?.excludeWorkspaceIds?.includes('workspace-a'));
  assert.ok(!pending?.excludeWorkspaceIds?.includes('workspace-b'));

  context.__setSidecarStatus({ lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true });
  await flushPendingTransferPromotionScope(context);
  const excludeCall = context.__runtimeCalls.find(
    (call) => call.kind === 'post' && call.requestPath === '/memory/transfer/exclude-workspace',
  );
  assert.ok(excludeCall);
  assert.ok(excludeCall.body.workspaceIds.includes('workspace-a'));
  assert.ok(!excludeCall.body.workspaceIds.includes('workspace-b'));
  assert.equal(context.__globalState.get('trainer.transfer.pendingPromotionScope'), undefined);
});
