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

const STALE_ROOT_ID = 'root-stale-identity';
const FRESH_ROOT_PATH = 'F:\\trainer-admission-root';
const PROJECT_PATH = 'G:\\trainer';

function rootPathUnavailableError() {
  const error = new Error('Sidecar request failed (409).');
  error.statusCode = 409;
  error.metadata = {
    code: 'root_path_unavailable',
    category: 'workspace_root',
    pathState: 'unavailable',
  };
  return error;
}

function classificationResponse(rootId, rootPath) {
  return {
    folder_role: 'existing_engineering',
    project_type_guess: 'unknown',
    confidence: 0,
    why_this_guess: '',
    entry_points: [],
    directory_anchors: [],
    core_modules_or_materials: [],
    risk_zones: [],
    training_opportunities: [],
    unknowns: [],
    recommended_next_step: '',
    classification_method: 'heuristic',
    classified_at: '2026-09-06T00:00:00.000Z',
    root_identity: {
      rootId,
      rootPath,
    },
    project_discovery: { discovery_id: 'discovery-retry' },
  };
}

function createVscodeMock(workspaceFolders) {
  return {
    Uri: {
      file(value) {
        return { fsPath: value };
      },
    },
    window: {
      async showOpenDialog() {
        return undefined;
      },
      async showWarningMessage(_message, _options, ...actions) {
        return actions[0];
      },
    },
    workspace: {
      workspaceFolders: workspaceFolders ?? [],
    },
  };
}

function createContext(options = {}) {
  const { createDefaultBootstrapData } = require(workbenchDataModulePath);
  const workspaceSnapshot = options.workspace ?? { trusted: true, workspaceFolder: PROJECT_PATH };
  const sidecarStatus = options.sidecarStatus ?? {
    lifecycle: 'ready',
    host: '127.0.0.1',
    port: 34892,
    canStart: true,
  };
  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: PROJECT_PATH },
    undefined,
    sidecarStatus,
  );
  const patches = [];
  const calls = [];
  const runtimeCalls = [];
  const outputLines = [];
  let manifest = {
    rootPath: FRESH_ROOT_PATH,
    canonicalRootPath: FRESH_ROOT_PATH,
    rootId: STALE_ROOT_ID,
  };
  // Emulates the TrainerWorkspaceService pending-reconciliation contract:
  // a retry-required record from a previously failed admission.
  const pendingRecords = new Map(
    options.pendingRecords?.map((record) => [path.resolve(record.projectPath), { ...record }]) ?? [],
  );
  let sessionId;
  const trainerWorkspace = {
    getRoot() {
      return manifest.rootPath;
    },
    async readWorkspaceManifest() {
      return manifest;
    },
    async setRootIdentity(rootId, canonicalRootPath) {
      calls.push({ kind: 'root-identity', rootId, canonicalRootPath });
      manifest = { ...manifest, rootPath: canonicalRootPath, canonicalRootPath, rootId };
      return manifest;
    },
    async recordManagedProvisioningPending(projectPath, reason) {
      calls.push({ kind: 'pending', projectPath: path.resolve(projectPath), reason });
      pendingRecords.set(path.resolve(projectPath), {
        projectPath: path.resolve(projectPath),
        workspaceRoot: manifest.rootPath,
        reason,
        state: 'retry-required',
        availableActions: ['retry', 'abandon'],
        updatedAt: '2026-09-06T00:00:00.000Z',
      });
    },
    getManagedProvisioningPending(projectPath) {
      return pendingRecords.get(path.resolve(projectPath));
    },
    async setProjectAdmission(projectPath, adoptionMode, managedIdentity) {
      calls.push({
        kind: 'project',
        projectPath: path.resolve(projectPath),
        adoptionMode,
        managedIdentity,
      });
      // Service contract: a successful admission clears the pending record.
      pendingRecords.delete(path.resolve(projectPath));
      return {
        fingerprint: 'project-retry',
        projectPath: path.resolve(projectPath),
        workspaceRoot: manifest.rootPath,
        adoptionMode,
        canonicalProjectPath: managedIdentity?.canonicalProjectPath ?? path.resolve(projectPath),
        legacyAliases: [],
        manifestRevision: 1,
        pathRevision: 0,
        identityStatus: managedIdentity ? 'verified' : 'pending',
        updatedAt: '2026-09-06T00:00:00.000Z',
      };
    },
    async getProject(projectPath) {
      return undefined;
    },
    async toSnapshot(projectPath) {
      const projectCall = [...calls].reverse().find((call) => call.kind === 'project');
      return {
        rootPath: manifest.rootPath,
        workspaceReady: true,
        manifest,
        currentProject: projectCall
          ? {
              fingerprint: 'project-retry',
              projectPath,
              workspaceRoot: manifest.rootPath,
              adoptionMode: projectCall.adoptionMode,
              canonicalProjectPath: projectCall.managedIdentity?.canonicalProjectPath ?? projectPath,
              updatedAt: '2026-09-06T00:00:00.000Z',
            }
          : undefined,
      };
    },
  };
  const hostState = {
    workspace: workspaceSnapshot,
    bootstrap,
  };
  const classifyBehavior = options.classifyBehavior;
  let classifyCount = 0;
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
          configuredPath: 'C:\\trainer-retry-tests\\sidecar-data',
          effectivePath: 'C:\\trainer-retry-tests\\sidecar-data',
          defaultPath: 'C:\\trainer-retry-tests\\default-sidecar-data',
          source: 'custom',
          status: 'ready',
        };
      },
    },
    sidecarClient: {
      setTrainerAdmissionMode() {},
      async postJson(port, requestPath, body) {
        runtimeCalls.push({ kind: 'post', port, requestPath, body });
        if (requestPath === '/workspace/classify') {
          classifyCount += 1;
          return classifyBehavior({ attempt: classifyCount, body });
        }
        if (requestPath === '/session/start') {
          return {
            session_id: 'session-retry',
            messages: [],
            memory: {},
            plan: { id: 'plan-retry', title: 'Plan', frozen: false, stages: [] },
          };
        }
        if (requestPath === '/workspace/discovery/decision') {
          return {
            project_discovery: { status: 'adoption_requested' },
            project_adoption_job: {
              job_id: 'job-retry',
              status: 'queued',
              progress: 0.05,
              progress_message: 'Queued for background adoption indexing.',
            },
          };
        }
        if (requestPath === '/memory/transfer/include-workspace') {
          return { ok: true, workspace_ids: body?.workspaceIds ?? [] };
        }
        throw new Error(`Unexpected POST ${requestPath}`);
      },
      async getJson(port, requestPath) {
        runtimeCalls.push({ kind: 'get', port, requestPath });
        if (requestPath.startsWith('/workspace/adoption-job?')) {
          return {
            project_discovery: { status: 'adopted' },
            project_provisioning: {
              agent_session_id: 'session-provisioned-retry',
              root_id: manifest.rootId,
              root_path: manifest.canonicalRootPath,
            },
            project_identity: {
              rootId: manifest.rootId,
              canonicalRootPath: manifest.canonicalRootPath,
              projectId: 'project-retry',
              contextId: 'context-retry',
              canonicalProjectPath: PROJECT_PATH,
              legacyAliases: [PROJECT_PATH],
              revisions: { root: 1, project: 1, context: 1 },
              pending: false,
            },
            project_adoption_job: {
              job_id: 'job-retry',
              status: 'completed',
              progress: 1,
              progress_message: 'Project adoption completed.',
            },
          };
        }
        if (requestPath.startsWith('/resource/trash')) {
          return [];
        }
        if (requestPath.startsWith('/memory/summary')) {
          return {
            messages: [],
            memory: {},
            plan: { id: 'plan-retry', title: 'Plan', frozen: false, stages: [] },
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
      async syncState() {},
    },
    outputChannel: {
      appendLine(line) {
        outputLines.push(line);
      },
    },
    trainerWorkspace,
    extensionContext: {
      globalState: {
        get() {
          return undefined;
        },
        async update() {},
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
    __outputLines: outputLines,
    __pendingRecords: pendingRecords,
    __manifest() {
      return manifest;
    },
  };
}

function classifyCalls(context) {
  return context.__runtimeCalls.filter(
    (call) => call.kind === 'post' && call.requestPath === '/workspace/classify',
  );
}

test('clicking Add to Trainer after a root_path_unavailable record re-attempts admission and re-registers the stale root identity', async () => {
  const vscodeMock = createVscodeMock();
  const { adoptWorkspaceProjectCommand } = loadWithVscodeMock(commandsModulePath, vscodeMock);
  const context = createContext({
    pendingRecords: [
      {
        projectPath: PROJECT_PATH,
        workspaceRoot: FRESH_ROOT_PATH,
        reason: 'Project could not be added (root_path_unavailable). Verify that the root is accessible, re-select it, and retry.',
        state: 'retry-required',
        availableActions: ['retry', 'abandon'],
        updatedAt: '2026-09-03T00:00:00.000Z',
      },
    ],
    classifyBehavior({ attempt, body }) {
      if (attempt === 1) {
        assert.equal(body.root_id, STALE_ROOT_ID);
        throw rootPathUnavailableError();
      }
      return classificationResponse('root-fresh-identity', FRESH_ROOT_PATH);
    },
  });
  assert.ok(context.__pendingRecords.get(path.resolve(PROJECT_PATH)));

  const result = await adoptWorkspaceProjectCommand(context, { responseLanguage: 'en-US' });

  assert.equal(result.ok, true);
  // The stale retry record alone did not block the attempt: the click POSTed.
  const classify = classifyCalls(context);
  assert.equal(classify.length, 2);
  assert.equal(classify[0].body.root_id, STALE_ROOT_ID);
  assert.equal(classify[0].body.root_path, FRESH_ROOT_PATH);
  // The retry re-registers the root by path instead of replaying the stale ID.
  assert.equal(classify[1].body.root_id, undefined);
  assert.equal(classify[1].body.root_path, FRESH_ROOT_PATH);
  assert.equal(classify[1].body.workspace_id, PROJECT_PATH);
  // The refreshed identity was persisted and used by the follow-up requests.
  const identityCall = context.__calls.find((call) => call.kind === 'root-identity');
  assert.equal(identityCall.rootId, 'root-fresh-identity');
  const sessionCall = context.__runtimeCalls.find(
    (call) => call.kind === 'post' && call.requestPath === '/session/start',
  );
  assert.equal(sessionCall.body.root_id, 'root-fresh-identity');
  const decisionCall = context.__runtimeCalls.find(
    (call) => call.kind === 'post' && call.requestPath === '/workspace/discovery/decision',
  );
  assert.equal(decisionCall.body.root_id, 'root-fresh-identity');
  // A successful admission clears the pending retry record.
  const admitted = context.__calls.find((call) => call.kind === 'project');
  assert.equal(admitted.adoptionMode, 'managed');
  assert.equal(admitted.managedIdentity.rootId, 'root-fresh-identity');
  assert.equal(context.__pendingRecords.get(path.resolve(PROJECT_PATH)), undefined);
  assert.match(
    context.__outputLines.join('\n'),
    /re-registering the selected root by path/,
  );
});

test('a previously failed attempt never wedges the flow: every click re-attempts admission', async () => {
  const vscodeMock = createVscodeMock();
  const { adoptWorkspaceProjectCommand } = loadWithVscodeMock(commandsModulePath, vscodeMock);
  const context = createContext({
    classifyBehavior({ body }) {
      if (body.root_id) {
        throw rootPathUnavailableError();
      }
      // The backend cannot see the root path either: both attempts fail.
      throw rootPathUnavailableError();
    },
  });

  const first = await adoptWorkspaceProjectCommand(context);
  const classifyAfterFirstClick = classifyCalls(context).length;
  const second = await adoptWorkspaceProjectCommand(context);
  const classifyAfterSecondClick = classifyCalls(context).length;

  assert.equal(first.ok, false);
  assert.equal(second.ok, false);
  assert.equal(classifyAfterFirstClick, 2);
  assert.equal(classifyAfterSecondClick, 4);
  assert.match(first.message, /root_path_unavailable/);
  assert.match(first.message, /retry/i);
  // The pending record keeps being replaced with the fresh failure, and the
  // admission itself was never written.
  assert.equal(context.__calls.some((call) => call.kind === 'project'), false);
  const pendingCalls = context.__calls.filter((call) => call.kind === 'pending');
  assert.equal(pendingCalls.length, 2);
  assert.ok(context.__pendingRecords.get(path.resolve(PROJECT_PATH)));
});

test('host-side root resolution failure returns a retryable error with the resolved-or-empty path instead of a silent no-op', async () => {
  const vscodeMock = createVscodeMock([
    { uri: { fsPath: 'G:\\elsewhere' } },
    { uri: { fsPath: 'G:\\other' } },
  ]);
  const { adoptWorkspaceProjectCommand } = loadWithVscodeMock(commandsModulePath, vscodeMock);
  const context = createContext({
    // Multi-root window with no active editor: the sovereign root cannot be
    // resolved, but the host state still knows the workspace folder.
    workspace: { trusted: true, workspaceFolder: PROJECT_PATH },
  });

  const result = await adoptWorkspaceProjectCommand(context);

  assert.equal(result.ok, false);
  assert.equal(result.data?.errorCode, 'root_missing');
  assert.match(result.message, /root_missing/);
  assert.match(result.message, /resolved workspace folder: G:\\trainer/);
  assert.match(result.message, /retry/i);
  assert.equal(classifyCalls(context).length, 0);
});

test('host-side root resolution failure with no resolvable folder names the empty path and stays retryable', async () => {
  const vscodeMock = createVscodeMock([]);
  const { adoptWorkspaceProjectCommand } = loadWithVscodeMock(commandsModulePath, vscodeMock);
  const context = createContext({
    workspace: { trusted: true },
  });

  const result = await adoptWorkspaceProjectCommand(context);

  assert.equal(result.ok, false);
  assert.equal(result.data?.errorCode, 'root_missing');
  assert.match(result.message, /no workspace folder is open/);
  assert.match(result.message, /retry/i);
  assert.equal(classifyCalls(context).length, 0);
});
