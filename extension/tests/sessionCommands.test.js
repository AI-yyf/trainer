'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const sessionCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'sessionCommands.js',
);
const memoryCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'memoryCommands.js',
);
const providerWebviewCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'providerWebviewCommands.js',
);

function createStreamingState(overrides = {}) {
  return {
    isStreaming: false,
    streamedContent: '',
    streamError: undefined,
    streamMessageId: undefined,
    agentActivity: [],
    agentStep: undefined,
    completionSummary: undefined,
    completionNextStep: undefined,
    completionStopReason: undefined,
    toolCount: undefined,
    agentic: undefined,
    reliabilityPhase: undefined,
    reliabilityOutcome: undefined,
    ...overrides,
  };
}

const VERIFIED_STREAMING_PROBE = {
  capabilityEvidence: [
    { name: 'streaming', declared: true, observed: true, state: 'verified' },
  ],
  streamingReady: true,
  streamProbeStatus: 'verified',
};

const VERIFIED_STREAMING_TEST_RESULT = {
  ok: true,
  status: 'ready',
  detail: 'Provider streaming probe observed an incremental chunk.',
  checkedAt: new Date().toISOString(),
  providerName: 'Local Compatible',
  baseUrl: 'http://localhost:1234/v1',
  model: 'demo-model',
  ...VERIFIED_STREAMING_PROBE,
};

function createContext(overrides = {}) {
  const patches = [];
  const synced = [];
  const shown = [];
  const sessionIds = [];
  const postCalls = [];
  const streamingStates = [];
  const trainerWorkspaceRoot = Object.prototype.hasOwnProperty.call(overrides, 'trainerWorkspaceRoot')
    ? overrides.trainerWorkspaceRoot
    : 'F:\\trainer-workspace';
  const hostState = {
    sessionId: overrides.initialSessionId,
    workspace: {
      workspaceFolder: overrides.workspaceFolder ?? 'F:\\trainer-a',
    },
    sidecar: {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
      ...(overrides.hostStateSidecar ?? {}),
    },
    bootstrap: {
      plan: { id: 'plan-1', frozen: false, stages: [], title: 'Plan', cadence: '', summary: '' },
      conversation: [],
      sessionHistory: [],
      memory: {
        weakSpots: [],
        recentWins: [],
        reviewSummary: '',
        ...(overrides.trainerWorkspaceAdmission
          ? {
              workspace: {
                trainerWorkspace: overrides.trainerWorkspaceAdmission,
              },
            }
          : {}),
      },
      profile: { focusAreas: [] },
      providerConfig: {},
      evaluation: { checks: [] },
    },
    streamingState: overrides.initialStreamingState ?? createStreamingState(),
  };
  return {
    outputChannel: {
      appendLine() {},
    },
    extensionContext: {
      globalState: {
        _value: undefined,
        async update(key, value) {
          this._value = { key, value };
        },
      },
      workspaceState: {
        async update() {
          return undefined;
        },
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    trainerWorkspace: {
      getRoot() {
        return trainerWorkspaceRoot;
      },
    },
    sidecarClient: {
      async getJson(port, requestPath) {
        if (requestPath.startsWith('/memory/summary')) {
          return {
            session_id: 'session-target',
            messages: [],
            memory: {
              workspace: {
                latest_training_submode: 'review',
              },
            },
            plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          };
        }
        if (requestPath.startsWith('/session/history')) {
          return [{ session_id: 'session-target', summary: 'Resume me' }];
        }
        throw new Error(`Unexpected GET ${requestPath}`);
      },
      async postJson(port, requestPath) {
        postCalls.push([port, requestPath, arguments[2]]);
        if (requestPath === '/session/start') {
          return {
            session_id: 'session-started',
            messages: [],
            memory: {},
            plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          };
        }
        return {
          plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          plan_runtime_status: {},
        };
      },
    },
    providerStore: {
      getConfig() {
        return {
          name: 'Local Compatible',
          baseUrl: 'http://localhost:1234/v1',
          model: 'demo-model',
        };
      },
      async getApiKey() {
        return 'sk-test';
      },
      getLastTestResult() {
        return {
          ok: true,
          status: 'ready',
          detail: 'Provider previously validated.',
          checkedAt: new Date().toISOString(),
          providerName: 'Local Compatible',
          baseUrl: 'http://localhost:1234/v1',
          model: 'demo-model',
        };
      },
      getModelCache() {
        return undefined;
      },
      isModelCacheFresh() {
        return false;
      },
      isModelCacheCompatible() {
        return false;
      },
      async saveModelCache() {
        return undefined;
      },
      async saveLastTestResult() {
        return undefined;
      },
      async clearLastTestResult() {
        return undefined;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
      async refreshSnapshot() {
        return undefined;
      },
    },
    workbench: {
      async show() {
        shown.push(true);
      },
      async postMessage(message) {
        postCalls.push(['workbench', 'postMessage', message]);
      },
      async syncState() {
        synced.push(true);
      },
    },
    getHostState() {
      return hostState;
    },
    getSessionId() {
      return hostState.sessionId;
    },
    async setSessionId(sessionId) {
      hostState.sessionId = sessionId;
      sessionIds.push(sessionId);
    },
    getStreamingState() {
      return hostState.streamingState;
    },
    async setStreamingState(streamingState) {
      hostState.streamingState = streamingState;
      streamingStates.push(streamingState);
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    ...overrides,
    __patches: patches,
    __synced: synced,
    __shown: shown,
    __sessionIds: sessionIds,
    __hostState: hostState,
    __postCalls: postCalls,
    __streamingStates: streamingStates,
  };
}

test('generatePlanCommand keeps a frozen plan intact without contacting the sidecar', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { generatePlanCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();
  context.__hostState.bootstrap.plan.frozen = true;
  context.__hostState.bootstrap.memory.workspace = { responseLanguage: 'zh-CN' };
  context.sidecarManager = {
    async ensureRunning() {
      throw new Error('Frozen plans must not start the sidecar.');
    },
  };
  context.sidecarClient = {
    async postJson() {
      throw new Error('Frozen plans must not call the plan generation route.');
    },
  };

  const result = await generatePlanCommand(context);

  assert.equal(result.ok, false);
  assert.match(result.message, /冻结/);
  assert.equal(context.__postCalls.length, 0);
});

test('resumeProjectLaneCommand restores a lane inside the current workspace', async () => {
  const executedCommands = [];
  const vscodeMock = {
    commands: {
      async executeCommand(commandId, ...args) {
        executedCommands.push([commandId, ...args]);
      },
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { resumeProjectLaneCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await resumeProjectLaneCommand(context, {
    workspaceId: 'F:\\trainer-a',
    workspacePath: 'F:\\trainer-a',
    workspaceLabel: 'trainer-a',
    resumeSessionId: 'session-target',
    targetView: 'practice',
    targetTrainingSubmode: 'review',
  });

  assert.equal(result.ok, true);
  assert.equal(context.__sessionIds.at(-1), 'session-target');
  assert.equal(context.__synced.length, 1);
  assert.equal(executedCommands.length, 0);
  assert.ok(context.__patches.length >= 1);
  assert.deepEqual(context.__postCalls.at(-1), [
    'workbench',
    'postMessage',
    {
      type: 'ui/restoreView',
      payload: {
        sessionId: 'session-target',
        activeView: 'training',
        trainingSubmode: 'review',
        workspaceLabel: 'trainer-a',
        resumeReason: undefined,
        focusArea: undefined,
        currentStageTitle: undefined,
        latestSummary: undefined,
        latestTrainingNextHop: undefined,
        resourceSurface: undefined,
        resourceId: undefined,
        sandboxPath: undefined,
        resourceDetailId: undefined,
        previewPath: undefined,
      },
    },
  ]);
});

test('resumeProjectLaneCommand blocks incomplete admission before reading the current workspace memory', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        throw new Error('The current workspace must not be reopened.');
      },
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { resumeProjectLaneCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);

  for (const status of ['root-missing', 'project-found', 'ignored']) {
    let memoryReads = 0;
    let sidecarStarts = 0;
    const context = createContext({
      trainerWorkspaceAdmission: { status },
      sidecarManager: {
        async ensureRunning() {
          sidecarStarts += 1;
          return { lifecycle: 'ready', port: 34891 };
        },
      },
      sidecarClient: {
        async getJson() {
          memoryReads += 1;
          throw new Error('Memory must not be read before project admission.');
        },
      },
    });

    const result = await resumeProjectLaneCommand(context, {
      workspaceId: 'F:\\trainer-a',
      workspacePath: 'F:\\trainer-a',
      resumeSessionId: 'session-target',
    });

    assert.equal(result.ok, false, status);
    assert.equal(memoryReads, 0, status);
    assert.equal(sidecarStarts, 0, status);
    assert.equal(context.__synced.length, 0, status);
  }
});

test('resumeProjectLaneCommand restores theory drill authority before posting ui restore', async () => {
  const vscodeMock = {
    env: {
      remoteName: 'ssh-remote',
    },
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { resumeProjectLaneCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-resume-theory' });
  let summaryCallCount = 0;
  context.sidecarClient = {
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath, null]);
      if (!requestPath.startsWith('/memory/summary?')) {
        throw new Error(`Unexpected GET ${requestPath}`);
      }
      summaryCallCount += 1;
      if (summaryCallCount === 1) {
        return {
          session_id: 'session-resume-theory',
          memory: {
            theory_drill_history: [
              {
                entry_id: 'theory-history-resume-1',
                theory_drill_id: 'theory-resume-1',
                version: 3,
              },
            ],
            theory_drill: {
              id: 'theory-resume-1',
              title: 'Dependency recall',
            },
            workspace: {
              latest_training_submode: 'flash',
              latest_learning_focus_area: 'dependency mastery',
            },
          },
        };
      }
      return {
        session_id: 'session-resume-theory',
        memory: {
          theory_drill_history: [
            {
              entry_id: 'theory-history-resume-1',
              theory_drill_id: 'theory-resume-1',
              version: 3,
            },
          ],
          theory_drill: {
            id: 'theory-resume-1',
            title: 'Dependency recall',
            status: 'ready',
          },
          workspace: {
            latest_training_submode: 'flash',
            latest_learning_focus_area: 'dependency mastery',
          },
        },
      };
    },
    async postJson(port, requestPath, body) {
      context.__postCalls.push([port, requestPath, body]);
      if (requestPath === '/training/theory-drill/restore') {
        return { ok: true };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
  };

  const result = await resumeProjectLaneCommand(context, {
    workspaceId: 'F:\\trainer-a',
    workspacePath: 'F:\\trainer-a',
    workspaceLabel: 'trainer-a',
    resumeSessionId: 'session-resume-theory',
    targetView: 'practice',
    targetTrainingSubmode: 'review',
    resumeReason: 'Resume the theory lane first.',
  });

  assert.equal(result.ok, true);
  assert.equal(
    context.__postCalls[0][1],
    '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-resume-theory',
  );
  assert.equal(context.__postCalls[1][1], '/training/theory-drill/restore');
  assert.deepEqual(context.__postCalls[1][2], {
    workspace_id: 'F:\\trainer-a',
    theory_drill_id: 'theory-resume-1',
    history_entry_id: 'theory-history-resume-1',
    history_version: 3,
    note: 'Resume the theory lane first.',
  });
  assert.equal(
    context.__postCalls[2][1],
    '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-resume-theory',
  );
  assert.deepEqual(context.__postCalls.at(-1), [
    'workbench',
    'postMessage',
    {
      type: 'ui/restoreView',
      payload: {
        sessionId: 'session-resume-theory',
        activeView: 'training',
        trainingSubmode: 'flash',
        trainingRestoreTarget: 'theory_drill',
        theoryDrillId: 'theory-resume-1',
        workspaceLabel: 'trainer-a',
        resumeReason: 'Resume the theory lane first.',
        focusArea: 'dependency mastery',
        currentStageTitle: undefined,
        latestSummary: undefined,
        latestTrainingNextHop: undefined,
        resourceSurface: undefined,
        resourceId: undefined,
        sandboxPath: undefined,
        resourceDetailId: undefined,
        previewPath: undefined,
      },
    },
  ]);
});

test('resumeProjectLaneCommand honestly fails when explicit governed resume history is missing', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { resumeProjectLaneCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-resume-missing-history' });
  context.sidecarClient = {
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath, null]);
      if (!requestPath.startsWith('/memory/summary?')) {
        throw new Error(`Unexpected GET ${requestPath}`);
      }
      return {
        session_id: 'session-resume-missing-history',
        memory: {
          theory_drill_history: [],
          workspace: {
            latest_training_submode: 'flash',
          },
        },
      };
    },
    async postJson() {
      throw new Error('Unexpected POST');
    },
  };

  const result = await resumeProjectLaneCommand(context, {
    workspaceId: 'F:\\trainer-a',
    workspacePath: 'F:\\trainer-a',
    workspaceLabel: 'trainer-a',
    resumeSessionId: 'session-resume-missing-history',
    targetView: 'practice',
    targetTrainingSubmode: 'flash',
    trainingRestoreTarget: 'theory_drill',
    theoryDrillId: 'theory-missing',
    resumeReason: 'Resume missing theory drill history.',
  });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /no governed restore history/i);
  assert.equal(context.__synced.length, 0);
  assert.equal(
    context.__postCalls.some((call) => call[0] === 'workbench' && call[1] === 'postMessage'),
    false,
  );
});

test('restartSessionCommand forwards the workspace path to the sidecar', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    workspace: {
      name: 'trainer-a',
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { restartSessionCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ workspaceFolder: 'F:\\trainer-a' });
  context.__hostState.workspace.remoteName = 'ssh-remote';

  const result = await restartSessionCommand(context);

  assert.equal(result.ok, true);
  const [, requestPath, requestBody] = context.__postCalls[0];
  assert.equal(requestPath, '/session/start');
  assert.deepEqual(requestBody, {
    workspace_id: 'F:\\trainer-a',
    workspace_name: 'trainer-a',
    workspace_path: 'F:\\trainer-a',
    remote_name: 'ssh-remote',
    workspace_trusted: false,
    force_new: true,
  });
  assert.equal(context.__sessionIds.at(-1), 'session-started');
  assert.deepEqual(context.__postCalls.at(-1), [
    'workbench',
    'postMessage',
    {
      type: 'ui/restoreView',
      payload: {
        sessionId: 'session-started',
        activeView: 'coach',
      },
    },
  ]);
});

test('restartSessionCommand blocks incomplete workspace admission before starting the sidecar', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    workspace: { name: 'trainer-a' },
  };
  const { restartSessionCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const cases = [
    ['root-missing', /选择 Trainer 工作区/],
    ['project-found', /加入 Trainer.*仅浏览.*忽略/],
    ['ignored', /已被忽略/],
  ];

  for (const [status, expectedMessage] of cases) {
    const context = createContext({
      trainerWorkspaceAdmission: { status },
    });
    let sidecarStarts = 0;
    context.sidecarManager = {
      async ensureRunning() {
        sidecarStarts += 1;
        return { lifecycle: 'ready', port: 34891 };
      },
    };

    const result = await restartSessionCommand(context);

    assert.equal(result.ok, false);
    assert.match(result.message ?? '', expectedMessage);
    assert.equal(sidecarStarts, 0);
    assert.deepEqual(context.__postCalls, []);
  }
});

test('sendMessageCommand blocks root-missing admission before any provider or sidecar work', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({
    trainerWorkspaceAdmission: { status: 'root-missing' },
  });
  let sidecarStarts = 0;
  context.sidecarManager = {
    async ensureRunning() {
      sidecarStarts += 1;
      return { lifecycle: 'ready', port: 34891 };
    },
  };

  const result = await sendMessageCommand(context, { text: 'Start a coaching session.' });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /选择 Trainer 工作区/);
  assert.equal(sidecarStarts, 0);
  assert.deepEqual(context.__postCalls, []);
});

test('restartSessionCommand prefers activeWorkspaceRoot when it differs from workspaceFolder', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    workspace: {
      name: 'trainer-root',
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { restartSessionCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ workspaceFolder: 'F:\\trainer-fallback' });
  context.__hostState.workspace.activeWorkspaceRoot = 'F:\\trainer-root';
  context.__hostState.workspace.remoteName = 'ssh-remote';

  await restartSessionCommand(context);

  const [, requestPath, requestBody] = context.__postCalls[0];
  assert.equal(requestPath, '/session/start');
  assert.equal(requestBody.workspace_id, 'F:\\trainer-root');
  assert.equal(requestBody.workspace_path, 'F:\\trainer-root');
  assert.equal(requestBody.workspace_name, 'trainer-root');
  assert.equal(requestBody.remote_name, 'ssh-remote');
  assert.equal(requestBody.workspace_trusted, false);
});

test('restartSessionCommand refetches authoritative memory summary before restoring the view', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    workspace: {
      name: 'trainer-a',
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { restartSessionCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ workspaceFolder: 'F:\\trainer-a' });
  context.__hostState.workspace.remoteName = 'ssh-remote';

  context.sidecarClient = {
    async postJson(port, requestPath, body) {
      context.__postCalls.push([port, requestPath, body]);
      if (requestPath === '/session/start') {
        return {
          session_id: 'session-started',
          messages: [],
          memory: {
            workspace: {
              latest_learning_focus_area: 'stale-start-response',
            },
          },
          plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath, null]);
      if (requestPath === '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-started') {
        return {
          session_id: 'session-started',
          messages: [],
          memory: {
            workspace: {
              latest_learning_focus_area: 'authoritative-summary',
            },
          },
          plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
        };
      }
      throw new Error(`Unexpected GET ${requestPath}`);
    },
  };

  const result = await restartSessionCommand(context);

  assert.equal(result.ok, true);
  assert.equal(context.__postCalls[0][1], '/session/start');
  assert.equal(
    context.__postCalls[1][1],
    '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-started',
  );
  assert.ok(
    context.__patches.some(
      (patch) => patch?.memory?.workspace?.latestLearningFocusArea === 'authoritative-summary',
    ),
  );
});

test('restartSessionCommand clears stale streaming state before restoring the fresh coach session', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    workspace: {
      name: 'trainer-a',
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { restartSessionCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const staleStreamingState = createStreamingState({
    isStreaming: true,
    streamMessageId: 'msg-stale-session',
    streamedContent: 'Old workspace answer still streaming.',
    completionSummary: 'Old session summary',
    completionNextStep: 'Old session next step',
    toolCount: 2,
    agentic: true,
    agentActivity: [
      {
        id: 'inspect-plan',
        name: 'inspect_plan',
        status: 'succeeded',
        result: { summary: 'Old plan anchor' },
        step: 0,
      },
    ],
  });
  const context = createContext({
    workspaceFolder: 'F:\\trainer-a',
    initialStreamingState: staleStreamingState,
  });

  const result = await restartSessionCommand(context);

  assert.equal(result.ok, true);
  assert.deepEqual(context.__streamingStates, [createStreamingState()]);
  assert.deepEqual(context.__hostState.streamingState, createStreamingState());
  assert.equal(context.__hostState.streamingState.streamMessageId, undefined);
  assert.equal(context.__hostState.streamingState.agentActivity.length, 0);
});

test('saveProviderFromWebviewCommand syncs runtime preferences into sidecar memory settings', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { saveProviderFromWebviewCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    vscodeMock,
  );
  const savedConfigs = [];
  const context = createContext({
    providerStore: {
      getConfig() {
        return undefined;
      },
      async saveConfig(config) {
        savedConfigs.push(config);
      },
      async getApiKey() {
        return 'sk-test';
      },
      getModelCache() {
        return undefined;
      },
      isModelCacheFresh() {
        return false;
      },
      isModelCacheCompatible() {
        return false;
      },
      getLastTestResult() {
        return undefined;
      },
      async clearModelCache() {
        return undefined;
      },
      async saveModelCache(config, payload) {
        return {
          ...payload,
          fetchedAt: payload.fetchedAt ?? '2026-05-24T00:00:00.000Z',
          expiresAt: '2026-05-24T00:30:00.000Z',
        };
      },
      async clearLastTestResult() {
        return undefined;
      },
    },
    sidecarManager: {
      getStatus() {
        return { lifecycle: 'ready', port: 34891 };
      },
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        context.__postCalls.push([port, requestPath, body]);
        if (requestPath === '/provider/workspace-secret/clear') {
          return { ok: true, cleared: true };
        }
        if (requestPath === '/provider/workspace-secret/save') {
          return { ok: true, configured: true };
        }
        if (requestPath === '/provider/models') {
          return {
            ok: true,
            detail: 'Loaded 1 live model.',
            available_models: ['mimo-v2.5'],
            resolved_model: 'mimo-v2.5',
          };
        }
        if (requestPath === '/provider/test') {
          return {
            ok: true,
            status: 'connected',
            provider_name: 'trainer-e2e-openai-compatible',
            detail: 'Provider reachable. Chat probe succeeded with model mimo-v2.5.',
            error_category: undefined,
            retryable: false,
            status_code: 200,
          };
        }
        if (requestPath === '/memory/settings') {
          return { ok: true };
        }
        throw new Error(`Unexpected POST ${requestPath}`);
      },
    },
  });
  context.__hostState.bootstrap.connection = {
    provider: {
      name: '',
      model: '',
      capabilities: {},
      runtimePreferences: {},
    },
  };
  context.__hostState.bootstrap.connection = {
    provider: {
      name: '',
      model: '',
      capabilities: {},
      runtimePreferences: {},
    },
  };

  const result = await saveProviderFromWebviewCommand(context, {
    name: 'trainer-e2e-openai-compatible',
    baseUrl: 'https://token-plan-cn.xiaomimimo.com/v1',
    model: 'mimo-v2.5',
    protocol: 'openai_chat_completions_compatible',
    apiKey: 'sk-test',
    replaceApiKey: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    requestDefaults: {
      extra_body: {
        thinking: {
          type: 'disabled',
        },
      },
    },
    runtimePreferences: {
      family: 'generic-openai',
      reasoningEffort: 'auto',
      enableDeepThinking: true,
      toolUseMode: 'trainer-only',
      webSearchMode: 'off',
      downloadMode: 'workspace-only',
      allowBackgroundResearch: false,
    },
  });

  assert.equal(result.ok, true);
  // Provider save command fetches models and patches workbench; runtimePreferences
  // sync to the sidecar is not part of this command.
  const modelCall = context.__postCalls.find(([, requestPath]) => requestPath === '/provider/models');
  assert.ok(modelCall, 'expected a /provider/models POST after saving provider');
  assert.deepEqual(savedConfigs[0].requestDefaults, {
    extra_body: {
      thinking: {
        type: 'disabled',
      },
    },
  });
  assert.equal(savedConfigs[0].profileId, undefined);
  assert.equal(savedConfigs[0].providerProfiles, undefined);
});

test('saveProviderFromWebviewCommand defaults remote workspaces to workspace_secret', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { saveProviderFromWebviewCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    vscodeMock,
  );
  const savedConfigs = [];
  let storedConfig;
  let storedApiKey;
  const context = createContext({
    providerStore: {
      getConfig() {
        return storedConfig;
      },
      async saveConfig(config, apiKey) {
        savedConfigs.push(config);
        storedConfig = config;
        if (apiKey !== undefined) {
          storedApiKey = apiKey;
        }
      },
      async getApiKey() {
        return storedApiKey;
      },
      getModelCache() {
        return undefined;
      },
      isModelCacheFresh() {
        return false;
      },
      isModelCacheCompatible() {
        return false;
      },
      getLastTestResult() {
        return undefined;
      },
      async clearModelCache() {
        return undefined;
      },
      async saveModelCache(config, payload) {
        return payload;
      },
      async clearLastTestResult() {
        return undefined;
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        context.__postCalls.push([port, requestPath, body]);
        if (requestPath === '/provider/models') {
          return {
            ok: true,
            detail: 'Loaded 1 live model.',
            available_models: ['remote-model'],
            resolved_model: 'remote-model',
          };
        }
        if (requestPath === '/provider/test') {
          return {
            ok: true,
            status: 'connected',
            provider_name: 'remote-compatible',
            detail: 'Provider reachable. Chat probe succeeded with model remote-model.',
            error_category: undefined,
            retryable: false,
            status_code: 200,
          };
        }
        throw new Error(`Unexpected POST ${requestPath}`);
      },
    },
  });
  context.__hostState.workspace.remoteName = 'ssh-remote';
  context.__hostState.workspace.isRemoteWorkspace = true;
  context.__hostState.bootstrap.connection = {
    provider: {
      name: '',
      model: '',
      capabilities: {},
      runtimePreferences: {},
    },
  };

  const result = await saveProviderFromWebviewCommand(context, {
    name: 'remote-compatible',
    baseUrl: 'https://example.com/v1',
    model: 'remote-model',
    protocol: 'openai_chat_completions_compatible',
    apiKey: 'sk-remote',
    replaceApiKey: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
  });

  assert.equal(result.ok, true);
  assert.equal(savedConfigs[0].credentialMode, 'workspace_secret');
  const apiKeyRef = savedConfigs[0].apiKeyRef;
  assert.match(apiKeyRef, /^trainer\.provider\.[0-9a-f-]{36}$/i);
  assert.equal(savedConfigs[0].apiKey, undefined);
  const modelCall = context.__postCalls.find(([, requestPath]) => requestPath === '/provider/models');
  const testCall = context.__postCalls.find(([, requestPath]) => requestPath === '/provider/test');
  assert.ok(modelCall);
  assert.ok(testCall);
  for (const [, , body] of [modelCall, testCall]) {
    assert.equal(body.workspace_id, 'F:\\trainer-a');
    assert.equal(body.api_key_ref, apiKeyRef);
    assert.equal(body.apiKey, 'sk-remote');
  }
  assert.equal(JSON.stringify(context.__patches).includes('sk-remote'), false);
  assert.equal(JSON.stringify(result.data).includes('sk-remote'), false);
});

test('saveProviderFromWebviewCommand keeps workspace_secret keys in SecretStorage and forwards them only to the sidecar', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { saveProviderFromWebviewCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    vscodeMock,
  );
  const savedConfigs = [];
  let storedConfig = {
    name: 'old-provider',
    baseUrl: 'https://old.example/v1',
    model: 'old-model',
    protocol: 'openai_chat_completions_compatible',
    apiKeyRef: 'trainer.old',
    credentialMode: 'workspace_secret',
  };
  let storedApiKey = 'sk-old-workspace-secret';
  const context = createContext({
    providerStore: {
      getConfig() {
        return storedConfig;
      },
      async saveConfig(config, apiKey) {
        savedConfigs.push(config);
        storedConfig = config;
        if (apiKey !== undefined) {
          storedApiKey = apiKey;
        }
      },
      async getApiKey() {
        return storedApiKey;
      },
      getModelCache() {
        return undefined;
      },
      isModelCacheFresh() {
        return false;
      },
      isModelCacheCompatible() {
        return false;
      },
      getLastTestResult() {
        return undefined;
      },
      async clearModelCache() {
        return undefined;
      },
      async saveModelCache(config, payload) {
        return {
          ...payload,
          fetchedAt: payload.fetchedAt ?? '2026-05-24T00:00:00.000Z',
          expiresAt: '2026-05-24T00:30:00.000Z',
        };
      },
      async clearLastTestResult() {
        return undefined;
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        context.__postCalls.push([port, requestPath, body]);
        if (requestPath === '/provider/models') {
          return {
            ok: true,
            detail: 'Loaded 1 live model.',
            available_models: ['remote-model'],
            resolved_model: 'remote-model',
          };
        }
        if (requestPath === '/provider/test') {
          assert.equal(body.workspace_id, 'F:\\trainer-a');
          assert.match(body.api_key_ref, /^trainer\.provider\.[0-9a-f-]{36}$/i);
          assert.equal(body.apiKey, 'sk-workspace-secret');
          return {
            ok: true,
            status: 'connected',
            provider_name: 'remote-compatible',
            detail: 'Provider reachable. Chat probe succeeded with model remote-model.',
            error_category: undefined,
            retryable: false,
            status_code: 200,
          };
        }
        throw new Error(`Unexpected POST ${requestPath}`);
      },
    },
  });
  context.__hostState.bootstrap.connection = {
    provider: {
      name: '',
      model: '',
      capabilities: {},
      runtimePreferences: {},
    },
  };

  const result = await saveProviderFromWebviewCommand(context, {
    name: 'remote-compatible',
    baseUrl: 'https://example.com/v1',
    model: 'remote-model',
    protocol: 'openai_chat_completions_compatible',
    credentialMode: 'workspace_secret',
    apiKey: 'sk-workspace-secret',
    replaceApiKey: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
  });

  assert.equal(result.ok, true);
  assert.equal(savedConfigs[0].credentialMode, 'workspace_secret');
  const modelCall = context.__postCalls.find(([, requestPath]) => requestPath === '/provider/models');
  const testCall = context.__postCalls.find(([, requestPath]) => requestPath === '/provider/test');
  assert.ok(modelCall);
  assert.ok(testCall);
  const apiKeyRef = savedConfigs[0].apiKeyRef;
  assert.match(apiKeyRef, /^trainer\.provider\.[0-9a-f-]{36}$/i);
  assert.equal(modelCall[2].workspace_id, 'F:\\trainer-a');
  assert.equal(modelCall[2].api_key_ref, apiKeyRef);
  assert.equal(modelCall[2].apiKey, 'sk-workspace-secret');
  assert.equal(testCall[2].api_key_ref, apiKeyRef);
  assert.equal(savedConfigs[0].apiKey, undefined);
  assert.equal(JSON.stringify(context.__patches).includes('sk-workspace-secret'), false);
  assert.equal(JSON.stringify(result.data).includes('sk-workspace-secret'), false);
});

test('sendMessageCommand forwards a workspace_secret key only to the local sidecar', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    window: {
      activeTextEditor: null,
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-workspace-secret-send' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Remote Compatible',
    credentialMode: 'workspace_secret',
    baseUrl: 'https://example.com/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    cacheSource: 'live',
    lastTestResult: {
      ok: true,
      status: 'connected',
      detail: 'Connected.',
      checkedAt: new Date().toISOString(),
      providerName: 'Remote Compatible',
      baseUrl: 'https://example.com/v1',
      model: 'demo-model',
      responseLanguage: 'en-US',
    },
  };
  context.providerStore = {
    getConfig() {
      return {
        name: 'Remote Compatible',
        baseUrl: 'https://example.com/v1',
        model: 'demo-model',
        apiKeyRef: 'trainer.remote',
        credentialMode: 'workspace_secret',
      };
    },
    async getApiKey() {
      return 'sk-local-fallback';
    },
    getModelCache() {
      return undefined;
    },
    isModelCacheFresh() {
      return false;
    },
    isModelCacheCompatible() {
      return false;
    },
    async saveModelCache() {
      return undefined;
    },
    async saveLastTestResult() {
      return undefined;
    },
    async clearLastTestResult() {
      return undefined;
    },
    getLastTestResult() {
      return {
        ok: true,
        status: 'connected',
        detail: 'Connected.',
        checkedAt: new Date().toISOString(),
        providerName: 'Remote Compatible',
        baseUrl: 'https://example.com/v1',
        model: 'demo-model',
        responseLanguage: 'en-US',
      };
    },
  };
  context.sidecarClient = {
    async postJson(port, requestPath, body) {
      context.__postCalls.push([port, requestPath, body]);
      if (requestPath === '/session/message') {
        assert.equal(body.workspace_id, 'F:\\trainer-a');
        assert.equal(body.api_key_ref, 'trainer.remote');
        assert.equal(body.api_key, 'sk-local-fallback');
        assert.equal(body.apiKey, 'sk-local-fallback');
        return {
          session_id: 'session-workspace-secret-send',
          reply: {
            role: 'assistant',
            content: 'Keep the patch small.',
            metadata: {},
          },
          snapshot: {
            messages: [],
            memory: {},
          },
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
  };

  const result = await sendMessageCommand(context, {
    text: 'Help me continue the next slice.',
  });

  assert.equal(result.ok, true);
  assert.equal(JSON.stringify(context.__patches).includes('sk-local-fallback'), false);
  assert.equal(JSON.stringify(result.data).includes('sk-local-fallback'), false);
});

test('saveCoachSettingsCommand normalizes legacy resource search modes before persistence', async () => {
  const vscodeMock = {};
  const { saveCoachSettingsCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({
    sidecarClient: {
      async getJson() {
        throw new Error('Unexpected GET');
      },
      async postJson(port, requestPath, body) {
        context.__postCalls.push([port, requestPath, body]);
        if (requestPath === '/memory/settings') {
          return {
            memory: {
              workspace: {
                resource_search_mode: 'coach',
              },
            },
          };
        }
        throw new Error(`Unexpected POST ${requestPath}`);
      },
    },
  });

  const result = await saveCoachSettingsCommand(context, {
    resourceSearchMode: 'coach',
  });

  assert.equal(result.ok, true);
  assert.deepEqual(context.__postCalls, [
    [
      34891,
      '/memory/settings',
      {
        session_id: undefined,
        workspace_id: 'F:\\trainer-a',
        response_language: undefined,
        answer_mode: undefined,
        teaching_style: undefined,
        coach_defaults: undefined,
        resource_search_mode: 'lexical',
        follow_current_file: undefined,
        context_detail: undefined,
        include_current_file: undefined,
        include_selection: undefined,
        include_diagnostics: undefined,
        include_related_files: undefined,
      },
    ],
  ]);
  assert.equal(context.__patches.length, 1);
  assert.equal(context.__patches[0].memory.workspace.resourceSearchMode, 'lexical');
  assert.equal(context.__synced.length, 1);
});

test('saveCoachSettingsCommand keeps settings local until the project is admitted', async () => {
  const vscodeMock = {};
  const { saveCoachSettingsCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);

  for (const status of ['root-missing', 'project-found', 'ignored']) {
    let sidecarStarts = 0;
    let writes = 0;
    const context = createContext({
      trainerWorkspaceAdmission: { status },
      sidecarManager: {
        async ensureRunning() {
          sidecarStarts += 1;
          return { lifecycle: 'ready', port: 34891 };
        },
      },
      sidecarClient: {
        async postJson() {
          writes += 1;
          throw new Error('Settings must not be written before project admission.');
        },
      },
    });
    context.__hostState.bootstrap.memory.workspace = {
      trainerWorkspace: { status },
      responseLanguage: 'en-US',
      answerMode: 'direct',
      resourceSearchMode: 'lexical',
      followCurrentFile: true,
      contextDetail: 'focused',
      includeCurrentFile: true,
      includeSelection: true,
      includeDiagnostics: true,
      includeRelatedFiles: true,
      coachDefaults: {
        memoryScope: 'personal',
        workingSetMode: 'focused',
        reviewCadence: 'light',
        reviewReminderMode: 'ahead',
        workspaceMemoryToggles: {
          decisions: false,
          patterns: true,
          resources: false,
        },
      },
    };
    context.__hostState.bootstrap.profile.preferredStyle = 'guided';

    const result = await saveCoachSettingsCommand(context, {
      responseLanguage: 'zh-CN',
      answerMode: 'balanced',
      resourceSearchMode: 'semantic',
      teachingStyle: 'hands-on',
      coachDefaults: {
        memoryScope: 'session',
        workingSetMode: 'broad',
        reviewCadence: 'active',
        reviewReminderMode: 'digest',
        workspaceMemoryToggles: { patterns: false },
      },
      followCurrentFile: false,
      contextDetail: 'full',
      includeCurrentFile: false,
      includeSelection: false,
      includeDiagnostics: false,
      includeRelatedFiles: false,
    });

    assert.equal(result.ok, true, status);
    assert.match(result.message, /stay local/i, status);
    assert.equal(sidecarStarts, 0, status);
    assert.equal(writes, 0, status);
    assert.equal(context.__patches.length, 1, status);
    const localWorkspace = context.__patches[0].memory.workspace;
    assert.equal(localWorkspace.trainerWorkspace.status, status, status);
    assert.equal(localWorkspace.responseLanguage, 'zh-CN', status);
    assert.equal(localWorkspace.answerMode, 'balanced', status);
    assert.equal(localWorkspace.resourceSearchMode, 'lexical', status);
    assert.equal(localWorkspace.followCurrentFile, false, status);
    assert.equal(localWorkspace.contextDetail, 'full', status);
    assert.equal(localWorkspace.includeCurrentFile, false, status);
    assert.equal(localWorkspace.includeSelection, false, status);
    assert.equal(localWorkspace.includeDiagnostics, false, status);
    assert.equal(localWorkspace.includeRelatedFiles, false, status);
    assert.deepEqual(localWorkspace.coachDefaults, {
      memoryScope: 'session',
      workingSetMode: 'broad',
      reviewCadence: 'active',
      reviewReminderMode: 'digest',
      workspaceMemoryToggles: {
        decisions: false,
        patterns: false,
        resources: false,
      },
    }, status);
    assert.equal(context.__patches[0].profile.preferredStyle, 'hands-on', status);
    assert.equal(context.__synced.length, 0, status);
  }
});

test('resumeProjectLaneCommand stores a handoff anchor and opens another workspace', async () => {
  const executedCommands = [];
  const vscodeMock = {
    commands: {
      async executeCommand(commandId, ...args) {
        executedCommands.push([commandId, ...args]);
      },
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { resumeProjectLaneCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ workspaceFolder: 'F:\\trainer-a' });

  const result = await resumeProjectLaneCommand(context, {
    workspaceId: 'F:\\trainer-b',
    workspacePath: 'F:\\trainer-b',
    workspaceLabel: 'trainer-b',
    resumeSessionId: 'session-b',
    targetView: 'practice',
    targetTrainingSubmode: 'flash',
    resumeReason: 'Resume the dependency lane first.',
    focusArea: 'dependency mastery',
    currentStageTitle: 'Stabilize recall',
    latestSummary: 'Flashcards are the next shortest path back in.',
  });

  assert.equal(result.ok, true);
  assert.deepEqual(context.extensionContext.globalState._value, {
    key: 'trainer.session.pendingResumeProjectLane',
    value: {
      workspaceId: 'F:\\trainer-b',
      workspacePath: 'F:\\trainer-b',
      workspaceLabel: 'trainer-b',
      resumeSessionId: 'session-b',
      targetView: 'practice',
      targetTrainingSubmode: 'flash',
      activeView: 'practice',
      trainingSubmode: 'flash',
      resourceSurface: undefined,
      trainingRestoreTarget: undefined,
      theoryDrillId: undefined,
      scenarioLabId: undefined,
      reviewArtifactId: undefined,
      resourceId: undefined,
      sandboxPath: undefined,
      resourceDetailId: undefined,
      previewPath: undefined,
      resumeReason: 'Resume the dependency lane first.',
      focusArea: 'dependency mastery',
      currentStageTitle: 'Stabilize recall',
      latestSummary: 'Flashcards are the next shortest path back in.',
    },
  });
  assert.equal(executedCommands.length, 1);
  assert.equal(executedCommands[0][0], 'vscode.openFolder');
  assert.equal(executedCommands[0][1].fsPath, 'F:\\trainer-b');
  assert.equal(executedCommands[0][2], false);
  assert.deepEqual(result.data, {
    workspaceId: 'F:\\trainer-b',
    workspacePath: 'F:\\trainer-b',
    workspaceLabel: 'trainer-b',
    resumeSessionId: 'session-b',
    targetView: 'practice',
    targetTrainingSubmode: 'flash',
    activeView: 'practice',
    trainingSubmode: 'flash',
    resourceSurface: undefined,
    trainingRestoreTarget: undefined,
    theoryDrillId: undefined,
    scenarioLabId: undefined,
    reviewArtifactId: undefined,
    resourceId: undefined,
    sandboxPath: undefined,
    resourceDetailId: undefined,
    previewPath: undefined,
    resumeReason: 'Resume the dependency lane first.',
    focusArea: 'dependency mastery',
    currentStageTitle: 'Stabilize recall',
    latestSummary: 'Flashcards are the next shortest path back in.',
  });
});

test('resumeProjectLaneCommand derives theory drill restore payload from the resumed snapshot', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { resumeProjectLaneCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({
    sidecarClient: {
      async getJson(port, requestPath) {
        context.__postCalls.push([port, requestPath, null]);
        if (requestPath.startsWith('/memory/summary')) {
          return {
            session_id: 'session-target',
            memory: {
              theory_drill_history: [
                {
                  entry_id: 'theory-history-restore-1',
                  theory_drill_id: 'theory-restore-1',
                  version: 5,
                },
              ],
              theory_drill: {
                id: 'theory-restore-1',
                title: 'Dependency recall',
              },
              workspace: {
                latest_training_submode: 'flash',
                latest_learning_focus_area: 'dependency mastery',
              },
            },
          };
        }
        if (requestPath.startsWith('/session/history')) {
          return [];
        }
        throw new Error(`Unexpected GET ${requestPath}`);
      },
      async postJson(port, requestPath, body) {
        context.__postCalls.push([port, requestPath, body]);
        if (requestPath === '/training/theory-drill/restore') {
          return { ok: true };
        }
        throw new Error(`Unexpected POST ${requestPath}`);
      },
    },
  });

  const result = await resumeProjectLaneCommand(context, {
    workspaceId: 'F:\\trainer-a',
    workspacePath: 'F:\\trainer-a',
    workspaceLabel: 'trainer-a',
    resumeSessionId: 'session-target',
    targetView: 'practice',
    targetTrainingSubmode: 'review',
    resumeReason: 'Resume the theory lane first.',
  });

  assert.equal(result.ok, true);
  assert.equal(context.__postCalls[1][1], '/training/theory-drill/restore');
  assert.deepEqual(context.__postCalls[1][2], {
    workspace_id: 'F:\\trainer-a',
    theory_drill_id: 'theory-restore-1',
    history_entry_id: 'theory-history-restore-1',
    history_version: 5,
    note: 'Resume the theory lane first.',
  });
  assert.equal(
    context.__postCalls[2][1],
    '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-target',
  );
  assert.deepEqual(context.__postCalls.at(-1), [
    'workbench',
    'postMessage',
    {
      type: 'ui/restoreView',
      payload: {
        sessionId: 'session-target',
        activeView: 'training',
        trainingSubmode: 'flash',
        trainingRestoreTarget: 'theory_drill',
        theoryDrillId: 'theory-restore-1',
        workspaceLabel: 'trainer-a',
        resumeReason: 'Resume the theory lane first.',
        focusArea: 'dependency mastery',
        currentStageTitle: undefined,
        latestSummary: undefined,
        latestTrainingNextHop: undefined,
        resourceSurface: undefined,
        resourceId: undefined,
        sandboxPath: undefined,
        resourceDetailId: undefined,
        previewPath: undefined,
      },
    },
  ]);
});

test('updatePlanCommand honestly rejects unsupported batch evidence governance routes', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { updatePlanCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Anthropic Gateway',
    baseUrl: 'http://minimax.redfast.top',
    model: 'MiniMax-M3',
    protocol: 'anthropic_messages',
    protocolFamily: 'anthropic',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: true,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    runtimePreferences: {
      family: 'auto',
      reasoningEffort: 'auto',
      enableDeepThinking: true,
      toolUseMode: 'auto',
      webSearchMode: 'auto',
      downloadMode: 'auto',
      allowBackgroundResearch: true,
    },
    availableModels: [],
    modelListStatus: 'ready',
  };

  const result = await updatePlanCommand(context, {
    evidenceAction: 'defer',
    evidenceActionScope: 'focus_area',
    evidenceFocusArea: 'routing',
    evidenceIds: ['e-1', 'e-2'],
    planId: 'plan-1',
    note: 'Batch defer routing evidence.',
  });

  assert.equal(result.ok, false);
  assert.match(result.message, /not supported/i);
  assert.equal(context.__postCalls.length, 0);
});

test('updatePlanCommand honestly rejects unsupported dry-run plan evidence preview routes', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { updatePlanCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Anthropic Gateway',
    baseUrl: 'http://minimax.redfast.top',
    model: 'MiniMax-M3',
    protocol: 'anthropic_messages',
    protocolFamily: 'anthropic',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: true,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    runtimePreferences: {
      family: 'auto',
      reasoningEffort: 'auto',
      enableDeepThinking: true,
      toolUseMode: 'auto',
      webSearchMode: 'auto',
      downloadMode: 'auto',
      allowBackgroundResearch: true,
    },
    availableModels: [],
    modelListStatus: 'ready',
  };

  const result = await updatePlanCommand(context, {
    evidenceAction: 'adopt',
    evidenceIds: ['e-1', 'e-2'],
    planId: 'plan-1',
    note: 'Preview the composed formal candidate first.',
    dryRun: true,
  });

  assert.equal(result.ok, false);
  assert.match(result.message, /not supported/i);
  assert.equal(context.__postCalls.length, 0);
});

test('updatePlanCommand restores formal plan history through the governed plan API', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { updatePlanCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient = {
    async getJson() {
      throw new Error('Unexpected GET');
    },
    async postJson(port, requestPath, body) {
      context.__postCalls.push([port, requestPath, body]);
      if (requestPath === '/provider/test') {
        return {
          ok: true,
          status: 'connected',
          provider_name: 'Local Compatible',
          detail: 'Provider reachable. Chat probe succeeded with model demo-model. Response: pong',
          resolved_model: 'demo-model',
        };
      }
      if (requestPath === '/plan/update') {
        return {
          plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          plan_runtime_status: {},
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
  };
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: true,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    runtimePreferences: {
      family: 'auto',
      reasoningEffort: 'auto',
      enableDeepThinking: true,
      toolUseMode: 'auto',
      webSearchMode: 'auto',
      downloadMode: 'auto',
      allowBackgroundResearch: true,
    },
    availableModels: [],
    modelListStatus: 'ready',
  };

  const result = await updatePlanCommand(context, {
    restorePlanHistoryEntryId: 'audit-project-1',
    instructions: 'Explicitly restore the current formal project plan from governed history.',
  });

  assert.equal(result.ok, true);
  assert.equal(context.__postCalls[0][1], '/provider/test');
  assert.equal(context.__postCalls[1][1], '/plan/update');
  assert.deepEqual(context.__postCalls[1][2], {
    plan_id: 'plan-1',
    workspace_id: 'F:\\trainer-a',
    instructions: 'Explicitly restore the current formal project plan from governed history.',
    restorePlanHistoryEntryId: 'audit-project-1',
    restorePlanHistoryVersion: undefined,
  });
  assert.ok(context.__patches.length >= 1);
});

test('updatePlanCommand forwards explicit formal plan history version restores through the governed plan API', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { updatePlanCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();
  context.__hostState.bootstrap.providerConfig = {
    name: 'demo',
    baseUrl: 'https://example.com/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: true,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    runtimePreferences: {
      family: 'auto',
      reasoningEffort: 'auto',
      enableDeepThinking: true,
      toolUseMode: 'auto',
      webSearchMode: 'auto',
      downloadMode: 'auto',
      allowBackgroundResearch: true,
    },
    availableModels: [],
    modelListStatus: 'ready',
  };

  await updatePlanCommand(context, {
    restorePlanHistoryEntryId: 'audit-project-1',
    restorePlanHistoryVersion: 3,
    instructions: 'Restore the authoritative formal project plan from governed version 3.',
  });

  const planUpdateCall = [...context.__postCalls].reverse().find((call) => call[1] === '/plan/update')
    ?? context.__postCalls.at(-1);
  assert.ok(planUpdateCall);
  assert.deepEqual(planUpdateCall[2], {
    plan_id: 'plan-1',
    workspace_id: 'F:\\trainer-a',
    instructions: 'Restore the authoritative formal project plan from governed version 3.',
    restorePlanHistoryEntryId: 'audit-project-1',
    restorePlanHistoryVersion: 3,
  });
});

test('updatePlanCommand restores formal plan history by version even without an explicit entry id', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { updatePlanCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();
  context.__hostState.bootstrap.providerConfig = {
    name: 'demo',
    baseUrl: 'https://example.com/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: true,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    runtimePreferences: {
      family: 'auto',
      reasoningEffort: 'auto',
      enableDeepThinking: true,
      toolUseMode: 'auto',
      webSearchMode: 'auto',
      downloadMode: 'auto',
      allowBackgroundResearch: true,
    },
    availableModels: [],
    modelListStatus: 'ready',
  };

  await updatePlanCommand(context, {
    restorePlanHistoryVersion: 3,
    instructions: 'Restore the authoritative formal project plan from governed version 3.',
  });

  const planUpdateCall = [...context.__postCalls].reverse().find((call) => call[1] === '/plan/update')
    ?? context.__postCalls.at(-1);
  assert.ok(planUpdateCall);
  assert.deepEqual(planUpdateCall[2], {
    plan_id: 'plan-1',
    workspace_id: 'F:\\trainer-a',
    instructions: 'Restore the authoritative formal project plan from governed version 3.',
    restorePlanHistoryEntryId: undefined,
    restorePlanHistoryVersion: 3,
  });
});

test('updatePlanCommand honestly rejects unsupported restore orchestration routes', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { updatePlanCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: true,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    runtimePreferences: {
      family: 'auto',
      reasoningEffort: 'auto',
      enableDeepThinking: true,
      toolUseMode: 'auto',
      webSearchMode: 'auto',
      downloadMode: 'auto',
      allowBackgroundResearch: true,
    },
    availableModels: [],
    modelListStatus: 'ready',
  };

  const result = await updatePlanCommand(context, {
    restoreOrchestrationRunId: 'restore-run-1',
    instructions: 'Run the governed restore sequence.',
    restoreOrchestrationSteps: [
      {
        itemId: 'formal-1',
        action: 'restore_formal_history',
        entryId: 'formal-1',
      },
      {
        itemId: 'subplan-2',
        action: 'restore_project_subplan',
        entryId: 'subplan-2',
        version: 2,
      },
    ],
  });

  assert.equal(result.ok, false);
  assert.match(result.message, /not supported/i);
  assert.equal(context.__postCalls.length, 0);
});

test('trainingRestoreOrchestrationCommand restores authoritative memory summary and posts ui restore', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
    },
  };
  const { trainingRestoreOrchestrationCommand } = loadWithVscodeMock(
    memoryCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ initialSessionId: 'session-training-1' });
  let summaryCallCount = 0;
  context.sidecarClient = {
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath, null]);
      summaryCallCount += 1;
      if (summaryCallCount === 1) {
        return {
          memory: {
            workspace: {
              latest_learning_focus_area: 'fastapi',
            },
            dependency_skill_map_history: [
              {
                entryId: 'dep-history-1',
                dependencyKey: 'fastapi',
                version: 1,
                beforeSnapshot: { version: 0 },
                afterSnapshot: { version: 1 },
                createdAt: '2026-06-05T00:00:00.000Z',
              },
            ],
            scenario_lab_history: [
              {
                entryId: 'scenario-history-1',
                scenarioLabId: 'scenario-lab-1',
                version: 2,
                beforeSnapshot: { version: 1 },
                afterSnapshot: { version: 2 },
                createdAt: '2026-06-05T00:00:01.000Z',
              },
            ],
            theory_drill_history: [],
            review_artifact_history: [],
            current_focus: 'Governed training restore',
            weak_spots: ['scenario lab restore'],
            recent_wins: [],
            review_summary: 'Stopped on invalid scenario lab input.',
            dependency_skill_maps: [],
          },
        };
      }
      return {
        memory: {
          current_focus: 'Governed training restore',
          weak_spots: ['scenario lab restore'],
          recent_wins: [],
          review_summary: 'Stopped on invalid scenario lab input.',
          dependency_skill_maps: [],
        },
      };
    },
    async postJson(port, requestPath, body) {
      context.__postCalls.push([port, requestPath, body]);
      return { ok: true };
    },
  };

  const result = await trainingRestoreOrchestrationCommand(context, {
    runId: 'training-restore-run-1',
    note: 'Restore governed training assets in order.',
  });

  assert.equal(result.ok, true);
  assert.equal(result.message, 'Training state restored from the authoritative memory summary.');
  assert.equal(
    context.__postCalls[0][1],
    '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-training-1',
  );
  assert.equal(context.__postCalls[1][1], '/training/dependency-skill-map/restore');
  assert.deepEqual(context.__postCalls[1][2], {
    workspace_id: 'F:\\trainer-a',
    dependency_key: 'fastapi',
    history_entry_id: 'dep-history-1',
    note: 'Restore governed training assets in order.',
  });
  assert.equal(context.__postCalls[2][1], '/training/scenario-lab/restore');
  assert.deepEqual(context.__postCalls[2][2], {
    workspace_id: 'F:\\trainer-a',
    scenario_lab_id: 'scenario-lab-1',
    history_entry_id: 'scenario-history-1',
    history_version: 2,
    note: 'Restore governed training assets in order.',
  });
  assert.equal(
    context.__postCalls[3][1],
    '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-training-1',
  );
  assert.equal(context.__postCalls.at(-1)[1], 'postMessage');
  assert.deepEqual(context.__postCalls.at(-1)[2], {
    type: 'ui/restoreView',
    payload: {
      activeView: 'training',
      trainingSubmode: undefined,
      trainingRestoreTarget: undefined,
      theoryDrillId: undefined,
      scenarioLabId: undefined,
      reviewArtifactId: undefined,
      resumeReason: 'Restore governed training assets in order.',
    },
  });
  assert.equal(context.__patches.at(-1).memory.currentFocus, 'Governed training restore');
});

test('debugRestoreViewCommand restores theory drill authority from the authoritative summary before posting ui restore', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { debugRestoreViewCommand } = loadWithVscodeMock(memoryCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-training-1' });
  let summaryCallCount = 0;
  context.sidecarClient = {
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath, null]);
      if (!requestPath.startsWith('/memory/summary?')) {
        throw new Error(`Unexpected GET ${requestPath}`);
      }
      summaryCallCount += 1;
      if (summaryCallCount === 1) {
        return {
          memory: {
            weak_spots: [],
            recent_wins: [],
            review_summary: 'Ready',
            teaching_observations: [],
            lowest_mastery_concepts: [],
            due_reviews: [],
            learning_outcomes: [],
            dependency_mastery: [],
            dependency_skill_maps: [],
            dependency_skill_map_history: [],
            theory_drill_history: [
              {
                entry_id: 'theory-history-1',
                theory_drill_id: 'theory-restore-1',
                version: 4,
                before_snapshot: { status: 'pending' },
                after_snapshot: { status: 'ready' },
              },
            ],
            recent_flash_attempts: [],
            review_queue_actions: [],
            scenario_lab_history: [],
            review_artifact_history: [],
            training_event_ledger: [],
            workspace: {
              latest_training_submode: 'flash',
            },
          },
        };
      }
      return {
        memory: {
          weak_spots: [],
          recent_wins: [],
          review_summary: 'Ready',
          teaching_observations: [],
          lowest_mastery_concepts: [],
          due_reviews: [],
          learning_outcomes: [],
          dependency_mastery: [],
          dependency_skill_maps: [],
          dependency_skill_map_history: [],
          theory_drill_history: [
            {
              entry_id: 'theory-history-1',
              theory_drill_id: 'theory-restore-1',
              version: 4,
              before_snapshot: { status: 'pending' },
              after_snapshot: { status: 'ready' },
            },
          ],
          recent_flash_attempts: [],
          review_queue_actions: [],
          scenario_lab_history: [],
          review_artifact_history: [],
          training_event_ledger: [],
          theory_drill: {
            id: 'theory-restore-1',
            title: 'Dependency recall',
            status: 'ready',
          },
          workspace: {
            latest_training_submode: 'flash',
          },
        },
      };
    },
    async postJson(port, requestPath, body) {
      context.__postCalls.push([port, requestPath, body]);
      if (requestPath === '/training/theory-drill/restore') {
        return { ok: true };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
  };
  context.workbench = {
    async show() {
      context.__postCalls.push(['workbench', 'show', null]);
    },
    async postMessage(message) {
      context.__postCalls.push(['workbench', 'postMessage', message]);
    },
    async syncState() {
      context.__postCalls.push(['workbench', 'syncState', null]);
    },
    setRefreshHandler() {},
  };

  const result = await debugRestoreViewCommand(context, {
    activeView: 'practice',
    trainingSubmode: 'flash',
    trainingRestoreTarget: 'theory_drill',
    theoryDrillId: 'theory-restore-1',
    resumeReason: 'Resume theory drill first.',
  });

  assert.equal(result.ok, true);
  assert.equal(
    context.__postCalls[0][1],
    '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-training-1',
  );
  assert.equal(context.__postCalls[1][1], '/training/theory-drill/restore');
  assert.deepEqual(context.__postCalls[1][2], {
    workspace_id: 'F:\\trainer-a',
    theory_drill_id: 'theory-restore-1',
    history_entry_id: 'theory-history-1',
    history_version: 4,
    note: 'Resume theory drill first.',
  });
  assert.equal(
    context.__postCalls[2][1],
    '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-training-1',
  );
  assert.equal(context.__postCalls[3][1], 'show');
  assert.equal(context.__postCalls[4][1], 'syncState');
  const actualPayload = context.__postCalls[5][2].payload;
  assert.equal(actualPayload.sessionId, 'session-training-1');
  assert.equal(actualPayload.activeView, 'practice');
  assert.equal(actualPayload.trainingSubmode, 'flash');
  assert.equal(actualPayload.trainingRestoreTarget, 'theory_drill');
  assert.equal(actualPayload.theoryDrillId, 'theory-restore-1');
  assert.equal(actualPayload.resumeReason, 'Resume theory drill first.');
  assert.equal(context.__patches.length, 2);
});

test('debugRestoreViewCommand restores scenario lab authority from the authoritative summary before posting ui restore', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { debugRestoreViewCommand } = loadWithVscodeMock(memoryCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-training-scenario' });
  let summaryCallCount = 0;
  context.sidecarClient = {
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath, null]);
      if (!requestPath.startsWith('/memory/summary?')) {
        throw new Error(`Unexpected GET ${requestPath}`);
      }
      summaryCallCount += 1;
      if (summaryCallCount === 1) {
        return {
          memory: {
            weak_spots: [],
            recent_wins: [],
            review_summary: 'Ready',
            teaching_observations: [],
            lowest_mastery_concepts: [],
            due_reviews: [],
            learning_outcomes: [],
            dependency_mastery: [],
            dependency_skill_maps: [],
            dependency_skill_map_history: [],
            theory_drill_history: [],
            recent_flash_attempts: [],
            review_queue_actions: [],
            scenario_lab_history: [
              {
                entry_id: 'scenario-history-1',
                scenario_lab_id: 'scenario-lab-1',
                version: 2,
                before_snapshot: { status: 'ready' },
                after_snapshot: { status: 'in_progress' },
              },
            ],
            review_artifact_history: [],
            training_event_ledger: [],
            workspace: {
              latest_training_submode: 'practice',
            },
          },
        };
      }
      return {
        memory: {
          weak_spots: [],
          recent_wins: [],
          review_summary: 'Ready',
          teaching_observations: [],
          lowest_mastery_concepts: [],
          due_reviews: [],
          learning_outcomes: [],
          dependency_mastery: [],
          dependency_skill_maps: [],
          dependency_skill_map_history: [],
          theory_drill_history: [],
          recent_flash_attempts: [],
          review_queue_actions: [],
          scenario_lab_history: [
            {
              entry_id: 'scenario-history-1',
              scenario_lab_id: 'scenario-lab-1',
              version: 2,
              before_snapshot: { status: 'ready' },
              after_snapshot: { status: 'in_progress' },
            },
          ],
          review_artifact_history: [],
          training_event_ledger: [],
          scenario_lab: {
            id: 'scenario-lab-1',
            title: 'Minimum dependency lab',
            status: 'ready',
          },
          workspace: {
            latest_training_submode: 'practice',
          },
        },
      };
    },
    async postJson(port, requestPath, body) {
      context.__postCalls.push([port, requestPath, body]);
      if (requestPath === '/training/scenario-lab/restore') {
        return { ok: true };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
  };
  context.workbench = {
    async show() {
      context.__postCalls.push(['workbench', 'show', null]);
    },
    async postMessage(message) {
      context.__postCalls.push(['workbench', 'postMessage', message]);
    },
    async syncState() {
      context.__postCalls.push(['workbench', 'syncState', null]);
    },
    setRefreshHandler() {},
  };

  const result = await debugRestoreViewCommand(context, {
    activeView: 'practice',
    trainingSubmode: 'practice',
    trainingRestoreTarget: 'scenario_lab',
    scenarioLabId: 'scenario-lab-1',
    resumeReason: 'Resume scenario lab first.',
  });

  assert.equal(result.ok, true);
  assert.equal(
    context.__postCalls[0][1],
    '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-training-scenario',
  );
  assert.equal(context.__postCalls[1][1], '/training/scenario-lab/restore');
  assert.deepEqual(context.__postCalls[1][2], {
    workspace_id: 'F:\\trainer-a',
    scenario_lab_id: 'scenario-lab-1',
    history_entry_id: 'scenario-history-1',
    history_version: 2,
    note: 'Resume scenario lab first.',
  });
  assert.equal(
    context.__postCalls[2][1],
    '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-training-scenario',
  );
  const actualPayload = context.__postCalls[5][2].payload;
  assert.equal(actualPayload.trainingRestoreTarget, 'scenario_lab');
  assert.equal(actualPayload.scenarioLabId, 'scenario-lab-1');
  assert.equal(actualPayload.trainingSubmode, 'practice');
  assert.equal(actualPayload.resumeReason, 'Resume scenario lab first.');
});

test('debugRestoreViewCommand restores review artifact authority from the authoritative summary before posting ui restore', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { debugRestoreViewCommand } = loadWithVscodeMock(memoryCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-training-review' });
  let summaryCallCount = 0;
  context.sidecarClient = {
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath, null]);
      if (!requestPath.startsWith('/memory/summary?')) {
        throw new Error(`Unexpected GET ${requestPath}`);
      }
      summaryCallCount += 1;
      if (summaryCallCount === 1) {
        return {
          memory: {
            weak_spots: [],
            recent_wins: [],
            review_summary: 'Ready',
            teaching_observations: [],
            lowest_mastery_concepts: [],
            due_reviews: [],
            learning_outcomes: [],
            dependency_mastery: [],
            dependency_skill_maps: [],
            dependency_skill_map_history: [],
            theory_drill_history: [],
            recent_flash_attempts: [],
            review_queue_actions: [],
            scenario_lab_history: [],
            review_artifact_history: [
              {
                entry_id: 'review-history-1',
                review_artifact_id: 'review-artifact-1',
                version: 6,
                before_snapshot: { status: 'active' },
                after_snapshot: { status: 'resolved' },
              },
            ],
            training_event_ledger: [],
            workspace: {
              latest_training_submode: 'review',
            },
          },
        };
      }
      return {
        memory: {
          weak_spots: [],
          recent_wins: [],
          review_summary: 'Ready',
          teaching_observations: [],
          lowest_mastery_concepts: [],
          due_reviews: [],
          learning_outcomes: [],
          dependency_mastery: [],
          dependency_skill_maps: [],
          dependency_skill_map_history: [],
          theory_drill_history: [],
          recent_flash_attempts: [],
          review_queue_actions: [],
          scenario_lab_history: [],
          review_artifact_history: [
            {
              entry_id: 'review-history-1',
              review_artifact_id: 'review-artifact-1',
              version: 6,
              before_snapshot: { status: 'active' },
              after_snapshot: { status: 'resolved' },
            },
          ],
          training_event_ledger: [],
          review_artifact: {
            id: 'review-artifact-1',
            title: 'Governed review',
            status: 'active',
          },
          workspace: {
            latest_training_submode: 'review',
          },
        },
      };
    },
    async postJson(port, requestPath, body) {
      context.__postCalls.push([port, requestPath, body]);
      if (requestPath === '/training/review-artifact/restore') {
        return { ok: true };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
  };
  context.workbench = {
    async show() {
      context.__postCalls.push(['workbench', 'show', null]);
    },
    async postMessage(message) {
      context.__postCalls.push(['workbench', 'postMessage', message]);
    },
    async syncState() {
      context.__postCalls.push(['workbench', 'syncState', null]);
    },
    setRefreshHandler() {},
  };

  const result = await debugRestoreViewCommand(context, {
    activeView: 'practice',
    trainingSubmode: 'review',
    trainingRestoreTarget: 'review_artifact',
    reviewArtifactId: 'review-artifact-1',
    resumeReason: 'Resume governed review first.',
  });

  assert.equal(result.ok, true);
  assert.equal(
    context.__postCalls[0][1],
    '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-training-review',
  );
  assert.equal(context.__postCalls[1][1], '/training/review-artifact/restore');
  assert.deepEqual(context.__postCalls[1][2], {
    workspace_id: 'F:\\trainer-a',
    review_artifact_id: 'review-artifact-1',
    history_entry_id: 'review-history-1',
    history_version: 6,
    note: 'Resume governed review first.',
  });
  assert.equal(
    context.__postCalls[2][1],
    '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-training-review',
  );
  const actualPayload = context.__postCalls[5][2].payload;
  assert.equal(actualPayload.trainingRestoreTarget, 'review_artifact');
  assert.equal(actualPayload.reviewArtifactId, 'review-artifact-1');
  assert.equal(actualPayload.trainingSubmode, 'review');
  assert.equal(actualPayload.resumeReason, 'Resume governed review first.');
});

test('debugRestoreViewCommand honestly fails when explicit governed restore history is missing', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { debugRestoreViewCommand } = loadWithVscodeMock(memoryCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-training-missing-history' });
  context.sidecarClient = {
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath, null]);
      if (requestPath.startsWith('/memory/summary?')) {
        return {
          memory: {
            theory_drill_history: [],
            scenario_lab_history: [],
            review_artifact_history: [],
            training_event_ledger: [],
            workspace: {
              latest_training_submode: 'flash',
            },
          },
        };
      }
      throw new Error(`Unexpected GET ${requestPath}`);
    },
    async postJson() {
      throw new Error('Unexpected POST');
    },
  };

  const result = await debugRestoreViewCommand(context, {
    activeView: 'practice',
    trainingSubmode: 'flash',
    trainingRestoreTarget: 'theory_drill',
    theoryDrillId: 'theory-missing',
    resumeReason: 'Try restoring a missing theory drill history.',
  });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /no governed restore history/i);
  assert.equal(context.__patches.length, 0);
});

test('debugRestoreViewCommand refreshes memory summary before ui restore without explicit training target', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { debugRestoreViewCommand } = loadWithVscodeMock(memoryCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-training-2' });
  context.sidecarClient = {
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath, null]);
      if (requestPath.startsWith('/memory/summary?')) {
        return {
          memory: {
            weak_spots: [],
            recent_wins: [],
            review_summary: 'Ready',
            teaching_observations: [],
            lowest_mastery_concepts: [],
            due_reviews: [],
            learning_outcomes: [],
            dependency_mastery: [],
            dependency_skill_maps: [],
            dependency_skill_map_history: [],
            theory_drill_history: [],
            recent_flash_attempts: [],
            review_queue_actions: [],
            scenario_lab_history: [],
            review_artifact_history: [],
            training_event_ledger: [],
            workspace: {
              latest_training_submode: 'review_queue',
            },
          },
        };
      }
      throw new Error(`Unexpected GET ${requestPath}`);
    },
    async postJson() {
      throw new Error('Unexpected POST');
    },
  };
  context.workbench = {
    async show() {
      context.__postCalls.push(['workbench', 'show', null]);
    },
    async postMessage(message) {
      context.__postCalls.push(['workbench', 'postMessage', message]);
    },
    async syncState() {
      context.__postCalls.push(['workbench', 'syncState', null]);
    },
    setRefreshHandler() {},
  };

  const result = await debugRestoreViewCommand(context, {
    activeView: 'practice',
    trainingSubmode: 'review_queue',
    resumeReason: 'Show current training truth.',
  });

  assert.equal(result.ok, true);
  assert.equal(String(context.__postCalls[0][1]).startsWith('/memory/summary?'), true);
  assert.equal(context.__postCalls[1][1], 'show');
  assert.equal(context.__postCalls[2][1], 'syncState');
  assert.equal(context.__postCalls[3][1], 'postMessage');
  assert.equal(context.__patches.length, 2);
  // latestTrainingSubmode is not part of the mapped MemorySnapshotView.workspace;
  // the command patches workbench state via mergeMemorySummary which maps only
  // standard workspace fields (responseLanguage, answerMode, etc.).
});

test('debugRestoreViewCommand carries restored next hop authority into ui restore payload', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { debugRestoreViewCommand } = loadWithVscodeMock(memoryCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-training-next-hop' });
  context.sidecarClient = {
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath, null]);
      if (requestPath.startsWith('/memory/summary?')) {
        return {
          memory: {
            weak_spots: [],
            recent_wins: [],
            review_summary: 'Ready',
            teaching_observations: [],
            lowest_mastery_concepts: [],
            due_reviews: [],
            learning_outcomes: [],
            dependency_mastery: [],
            dependency_skill_maps: [],
            dependency_skill_map_history: [],
            theory_drill_history: [],
            recent_flash_attempts: [],
            review_queue_actions: [],
            scenario_lab_history: [],
            review_artifact_history: [],
            training_event_ledger: [],
            workspace: {
              latest_training_submode: 'practice',
              latest_training_next_hop: {
                candidate_id: 'candidate-next-hop-1',
                candidate_type: 'practice_candidate',
                continue_in: 'training',
                target_kind: 'training_card',
                target_id: 'card-next-hop-1',
                status: 'surfaced',
                review_artifact_id: 'review-artifact-1',
                next_after_completion: 'Review the blocker, then continue the practice card.',
              },
            },
          },
        };
      }
      throw new Error(`Unexpected GET ${requestPath}`);
    },
    async postJson() {
      throw new Error('Unexpected POST');
    },
  };
  context.workbench = {
    async show() {
      context.__postCalls.push(['workbench', 'show', null]);
    },
    async postMessage(message) {
      context.__postCalls.push(['workbench', 'postMessage', message]);
    },
    async syncState() {
      context.__postCalls.push(['workbench', 'syncState', null]);
    },
    setRefreshHandler() {},
  };

  const result = await debugRestoreViewCommand(context, {
    sessionId: 'session-next-hop-override',
    activeView: 'practice',
    trainingSubmode: 'practice',
    trainingRestoreTarget: 'next_hop',
    reviewArtifactId: 'review-artifact-1',
    resumeReason: 'Show the next hop authority.',
  });

  assert.equal(result.ok, true);
  assert.equal(String(context.__postCalls[0][1]).startsWith('/memory/summary?'), true);
  assert.match(String(context.__postCalls[0][1]), /session_id=session-next-hop-override/);
  assert.equal(
    (String(context.__postCalls[0][1]).match(/session_id=/g) ?? []).length,
    1,
  );
  assert.equal(context.__postCalls[1][1], 'show');
  assert.equal(context.__postCalls[2][1], 'syncState');
  assert.equal(context.__postCalls[3][0], 'workbench');
  assert.equal(context.__postCalls[3][1], 'postMessage');
  assert.equal(context.__postCalls[3][2].type, 'ui/restoreView');
  assert.equal(context.__postCalls[3][2].payload.sessionId, 'session-next-hop-override');
  assert.equal(context.__postCalls[3][2].payload.activeView, 'practice');
  assert.equal(context.__postCalls[3][2].payload.trainingSubmode, 'practice');
  assert.equal(context.__postCalls[3][2].payload.trainingRestoreTarget, 'next_hop');
  assert.equal(context.__postCalls[3][2].payload.reviewArtifactId, 'review-artifact-1');
  assert.equal(context.__postCalls[3][2].payload.resumeReason, 'Show the next hop authority.');
  assert.equal(
    context.__postCalls[3][2].payload.latestTrainingNextHop?.candidateId,
    'candidate-next-hop-1',
  );
  assert.equal(
    context.__postCalls[3][2].payload.latestTrainingNextHop?.candidateType,
    'practice_candidate',
  );
  assert.equal(
    context.__postCalls[3][2].payload.latestTrainingNextHop?.continueIn,
    'training',
  );
  assert.equal(
    context.__postCalls[3][2].payload.latestTrainingNextHop?.targetKind,
    'training_card',
  );
  assert.equal(
    context.__postCalls[3][2].payload.latestTrainingNextHop?.targetId,
    'card-next-hop-1',
  );
  assert.equal(
    context.__postCalls[3][2].payload.latestTrainingNextHop?.status,
    'surfaced',
  );
  assert.equal(
    context.__postCalls[3][2].payload.latestTrainingNextHop?.reviewArtifactId,
    'review-artifact-1',
  );
  assert.equal(
    context.__postCalls[3][2].payload.latestTrainingNextHop?.nextAfterCompletion,
    'Review the blocker, then continue the practice card.',
  );
  assert.equal(context.__patches.length, 2);
  // latestTrainingNextHop is not part of the mapped MemorySnapshotView.workspace;
  // it is carried through the ui/restoreView payload instead.
  assert.equal(context.__sessionIds.at(-1), 'session-next-hop-override');
});

test('debugRestoreViewCommand carries resource restore hints into the ui restore payload', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { debugRestoreViewCommand } = loadWithVscodeMock(memoryCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-resource-restore' });
  context.sidecarClient = {
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath, null]);
      if (requestPath.startsWith('/memory/summary?')) {
        return {
          memory: {
            weak_spots: [],
            recent_wins: [],
            review_summary: 'Ready',
            teaching_observations: [],
            lowest_mastery_concepts: [],
            due_reviews: [],
            learning_outcomes: [],
            dependency_mastery: [],
            dependency_skill_maps: [],
            dependency_skill_map_history: [],
            theory_drill_history: [],
            recent_flash_attempts: [],
            review_queue_actions: [],
            scenario_lab_history: [],
            review_artifact_history: [],
            training_event_ledger: [],
            workspace: {},
          },
        };
      }
      throw new Error(`Unexpected GET ${requestPath}`);
    },
    async postJson() {
      throw new Error('Unexpected POST');
    },
  };
  context.workbench = {
    async show() {
      context.__postCalls.push(['workbench', 'show', null]);
    },
    async postMessage(message) {
      context.__postCalls.push(['workbench', 'postMessage', message]);
    },
    async syncState() {
      context.__postCalls.push(['workbench', 'syncState', null]);
    },
    setRefreshHandler() {},
  };

  const result = await debugRestoreViewCommand(context, {
    activeView: 'resources',
    resourceSurface: 'sandbox',
    resourceId: 'resource-1',
    resourceDetailId: 'resource-1',
    sandboxPath: 'F:\\trainer\\sandbox\\resource-1.md',
    previewPath: 'F:\\trainer\\sandbox\\resource-1.md',
    workspaceLabel: 'trainer-vsix-e2e',
    resumeReason: 'Show the current resource surface.',
    focusArea: 'resource sandbox',
    currentStageTitle: 'Govern the library',
    latestSummary: 'Restore the current sandbox path first.',
  });

  assert.equal(result.ok, true);
  assert.equal(context.__postCalls[1][1], 'show');
  assert.equal(context.__postCalls[2][1], 'syncState');
  assert.equal(context.__postCalls[3][1], 'postMessage');
  assert.equal(context.__postCalls[3][2].type, 'ui/restoreView');
  assert.equal(context.__postCalls[3][2].payload.activeView, 'resources');
  assert.equal(context.__postCalls[3][2].payload.resourceSurface, 'sandbox');
  assert.equal(context.__postCalls[3][2].payload.resourceId, 'resource-1');
  assert.equal(context.__postCalls[3][2].payload.resourceDetailId, 'resource-1');
  assert.equal(
    context.__postCalls[3][2].payload.sandboxPath,
    'F:\\trainer\\sandbox\\resource-1.md',
  );
  assert.equal(
    context.__postCalls[3][2].payload.previewPath,
    'F:\\trainer\\sandbox\\resource-1.md',
  );
  assert.equal(context.__postCalls[3][2].payload.workspaceLabel, 'trainer-vsix-e2e');
  assert.equal(context.__postCalls[3][2].payload.resumeReason, 'Show the current resource surface.');
  assert.equal(context.__postCalls[3][2].payload.focusArea, 'resource sandbox');
  assert.equal(context.__postCalls[3][2].payload.currentStageTitle, 'Govern the library');
  assert.equal(
    context.__postCalls[3][2].payload.latestSummary,
    'Restore the current sandbox path first.',
  );
});

test('debugRestoreViewCommand uses payload workspaceId for next-hop memory summary restore', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { debugRestoreViewCommand } = loadWithVscodeMock(memoryCommandsModulePath, vscodeMock);
  const context = createContext({
    initialSessionId: 'session-next-hop-workspace-override',
    workspaceFolder: 'F:\\trainer-a',
  });

  const requestedPaths = [];
  context.sidecarClient = {
    async getJson(port, requestPath) {
      requestedPaths.push(requestPath);
      return {
        memory: {
          weak_spots: [],
          recent_wins: [],
          review_summary: 'Ready',
          teaching_observations: [],
          lowest_mastery_concepts: [],
          due_reviews: [],
          learning_outcomes: [],
          dependency_mastery: [],
          dependency_skill_maps: [],
          dependency_skill_map_history: [],
          theory_drill_history: [],
          recent_flash_attempts: [],
          review_queue_actions: [],
          scenario_lab_history: [],
          review_artifact_history: [],
          training_event_ledger: [],
          workspace: {
            workspace_id: 'F:\\trainer-b',
            latest_training_submode: 'practice',
            latest_training_next_hop: {
              candidate_id: 'candidate-next-hop-workspace-override',
              candidate_type: 'practice_candidate',
              continue_in: 'training',
              target_kind: 'training_card',
              target_id: 'card-next-hop-workspace-override',
              status: 'surfaced',
            },
          },
        },
      };
    },
    async postJson() {
      throw new Error('Unexpected POST');
    },
  };
  context.workbench = {
    async show() {
      context.__postCalls.push(['workbench', 'show', null]);
    },
    async postMessage(message) {
      context.__postCalls.push(['workbench', 'postMessage', message]);
    },
    async syncState() {
      context.__postCalls.push(['workbench', 'syncState', null]);
    },
    setRefreshHandler() {},
  };

  const result = await debugRestoreViewCommand(context, {
    sessionId: 'session-next-hop-workspace-override',
    workspaceId: 'F:\\trainer-b',
    activeView: 'practice',
    trainingSubmode: 'practice',
    trainingRestoreTarget: 'next_hop',
    resumeReason: 'Restore next hop with explicit workspace override.',
  });

  assert.equal(result.ok, true);
  assert.equal(requestedPaths.length, 1);
  assert.match(String(requestedPaths[0]), /workspace_id=F%3A%5Ctrainer-b/);
  assert.match(String(requestedPaths[0]), /session_id=session-next-hop-workspace-override/);
  assert.equal(context.__postCalls[2][2].type, 'ui/restoreView');
  assert.equal(
    context.__postCalls[2][2].payload.latestTrainingNextHop?.targetId,
    'card-next-hop-workspace-override',
  );
});

test('debugRestoreViewCommand backfills next hop from ledger when workspace next hop object is empty', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { debugRestoreViewCommand } = loadWithVscodeMock(memoryCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-ledger-next-hop' });
  context.sidecarClient = {
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath, null]);
      if (requestPath.startsWith('/memory/summary?')) {
        return {
          memory: {
            weak_spots: [],
            recent_wins: [],
            review_summary: 'Ready',
            teaching_observations: [],
            lowest_mastery_concepts: [],
            due_reviews: [],
            learning_outcomes: [],
            dependency_mastery: [],
            dependency_skill_maps: [],
            dependency_skill_map_history: [],
            theory_drill_history: [],
            recent_flash_attempts: [],
            review_queue_actions: [],
            scenario_lab_history: [],
            review_artifact_history: [],
            training_event_ledger: [
              {
                event_id: 'event-next-hop-ledger',
                event_type: 'training_next_hop_materialized',
                workspace_id: 'F:\\trainer-a',
                candidate_id: 'candidate-ledger-next-hop',
                candidate_type: 'practice_candidate',
                candidate_status: 'surfaced',
                candidate_status_reason: 'Derived from latest governed training judgment.',
                candidate_project_scope: 'current_project',
                candidate_continue_in: 'training',
                candidate_target_kind: 'training_card',
                candidate_target_id: 'card-ledger-next-hop',
                candidate_title: 'FastAPI Depends boundary next cut',
                candidate_why_now: 'Keep the same boundary and verify with one learner-owned check.',
                selected_card_type: 'practice',
                selected_card_title: 'FastAPI Depends boundary next cut',
                status_kind: 'surfaced',
                status_summary: 'Next hop is surfaced and ready in training.',
                return_mode: 'result',
                return_summary: 'One verified learner-owned card finished.',
                next_after_completion: 'Then run one tiny recovery question.',
                fallback_action: 'Go back to flash review if blocked.',
                source_chain: ['training_return', 'review_artifact'],
                created_at: '2026-05-24T00:00:05Z',
              },
            ],
            workspace: {
              latest_training_submode: 'practice',
              latest_training_next_hop: {},
            },
          },
        };
      }
      throw new Error(`Unexpected GET ${requestPath}`);
    },
    async postJson() {
      throw new Error('Unexpected POST');
    },
  };
  context.workbench = {
    async show() {
      context.__postCalls.push(['workbench', 'show', null]);
    },
    async postMessage(message) {
      context.__postCalls.push(['workbench', 'postMessage', message]);
    },
    async syncState() {
      context.__postCalls.push(['workbench', 'syncState', null]);
    },
    setRefreshHandler() {},
  };

  const result = await debugRestoreViewCommand(context, {
    sessionId: 'session-ledger-next-hop-override',
    activeView: 'practice',
    trainingSubmode: 'practice',
    trainingRestoreTarget: 'next_hop',
    resumeReason: 'Restore next hop from ledger when object is missing.',
  });

  assert.equal(result.ok, true);
  const payload = context.__postCalls[3][2].payload;
  assert.equal(payload.trainingRestoreTarget, 'next_hop');
  assert.equal(payload.latestTrainingNextHop?.candidateType, 'practice_candidate');
  assert.equal(payload.latestTrainingNextHop?.continueIn, 'training');
  assert.equal(payload.latestTrainingNextHop?.targetKind, 'training_card');
  assert.equal(payload.latestTrainingNextHop?.targetId, 'card-ledger-next-hop');
  assert.equal(payload.latestTrainingNextHop?.status, 'surfaced');
  assert.equal(payload.latestTrainingNextHop?.cardTitle, 'FastAPI Depends boundary next cut');
  assert.equal(payload.latestTrainingNextHop?.summary, 'Next hop is surfaced and ready in training.');
});

test('sendMessageCommand does not transparently retry session message after timeout', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-send-timeout-retry' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Anthropic Gateway',
    baseUrl: 'http://minimax.redfast.top',
    model: 'MiniMax-M3',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['MiniMax-M3'],
    resolvedModel: 'MiniMax-M3',
    modelListStatus: 'ready',
    cacheSource: 'live',
    lastTestResult: {
      ok: true,
      status: 'connected',
      detail: 'Provider reachable. Chat probe succeeded with model MiniMax-M3. Response: pong',
      checkedAt: new Date().toISOString(),
      providerName: 'Anthropic Gateway',
      baseUrl: 'http://minimax.redfast.top',
      model: 'MiniMax-M3',
      responseLanguage: 'zh-CN',
    },
  };

  context.providerStore = {
    getConfig() {
      return {
        name: 'Anthropic Gateway',
        baseUrl: 'http://minimax.redfast.top',
        model: 'MiniMax-M3',
        protocol: 'anthropic_messages',
        apiKeyRef: 'anthropic.default',
        capabilities: {
          chat: true,
          responses: false,
          vision: true,
          embeddings: false,
          tools: true,
          jsonSchema: false,
          structuredOutput: false,
          streaming: true,
        },
      };
    },
    async getApiKey() {
      return 'sk-test';
    },
    getModelCache() {
      return undefined;
    },
    isModelCacheFresh() {
      return false;
    },
    async saveModelCache() {
      return undefined;
    },
  };

  let turnAttempts = 0;
  context.sidecarClient = {
    async postJson(port, requestPath, body, options) {
      context.__postCalls.push([port, requestPath, body, options]);
      if (requestPath === '/session/message') {
        turnAttempts += 1;
        if (turnAttempts === 1) {
          throw new Error('Sidecar request timed out: POST /session/message');
        }
        return {
          session_id: 'session-send-timeout-retry',
          reply: {
            role: 'assistant',
            content: 'Use one tiny learner-owned verification slice first.',
            metadata: {
              coach_visible_status: {
                summary: 'Coach is back on track.',
              },
            },
          },
          snapshot: {
            messages: [],
            memory: {},
            plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          },
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath, null, null]);
      if (requestPath.startsWith('/session/history')) {
        return [{ session_id: 'session-send-timeout-retry', summary: 'Coach resumed.' }];
      }
      throw new Error(`Unexpected GET ${requestPath}`);
    },
  };

  const result = await sendMessageCommand(context, {
    text: '帮我先定义一个最小可验证训练切片',
    intent: 'coach',
    responseLanguage: 'zh-CN',
    answerMode: 'coach-first',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  const coachCalls = context.__postCalls.filter((call) => call[1] === '/session/message');
  assert.equal(coachCalls.length, 1);
  assert.match(result.message, /timed out|timeout/i);
});

test('sendMessageCommand does not retry non-timeout errors and patches provider failure state', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-send-non-timeout' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    cacheSource: 'live',
    lastTestResult: {
      ok: true,
      status: 'connected',
      detail: 'Provider reachable. Chat probe succeeded with model demo-model. Response: pong',
      checkedAt: new Date().toISOString(),
      providerName: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
      protocol: 'anthropic_messages',
      responseLanguage: 'zh-CN',
    },
  };

  context.providerStore = {
    getConfig() {
      return {
        name: 'Local Compatible',
        baseUrl: 'http://localhost:1234/v1',
        model: 'demo-model',
        protocol: 'anthropic_messages',
      };
    },
    async getApiKey() {
      return 'sk-test';
    },
    getModelCache() {
      return {
        availableModels: ['MiniMax-M3'],
        resolvedModel: 'MiniMax-M3',
        fetchedAt: '2026-05-24T00:00:00.000Z',
        expiresAt: '2026-05-24T00:30:00.000Z',
      };
    },
    isModelCacheFresh() {
      return true;
    },
    isModelCacheCompatible() {
      return true;
    },
    async saveModelCache(_config, payload) {
      return payload;
    },
  };

  let turnAttempts = 0;
  context.sidecarClient = {
    async postJson(port, requestPath, body, options) {
      context.__postCalls.push([port, requestPath, body, options]);
      if (requestPath === '/session/message') {
        turnAttempts += 1;
        assert.equal(body.provider.protocol, 'anthropic_messages');
        throw new Error('Sidecar request failed (403): invalid api key');
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async getJson() {
      throw new Error('Unexpected GET');
    },
  };

  await assert.rejects(
    sendMessageCommand(context, {
      text: '帮我做一个最小训练计划',
      intent: 'coach',
      responseLanguage: 'zh-CN',
      answerMode: 'coach-first',
      includeCurrentFile: false,
    }),
    /invalid api key/i,
  );
  assert.equal(turnAttempts, 1);
  const coachCalls = context.__postCalls.filter((call) => call[1] === '/session/message');
  assert.equal(coachCalls.length, 1);
  const errorPatch = context.__patches.find(
    (patch) => patch?.providerConfig?.modelListStatus === 'error',
  );
  assert.ok(errorPatch);
  assert.equal(errorPatch.providerConfig.modelErrorCategory, 'invalid_key_or_permission');
  assert.equal(errorPatch.providerConfig.modelStatusCode, 403);
  assert.equal(errorPatch.providerConfig.modelRetryable, false);
  assert.equal(errorPatch.providerConfig.protocol, 'anthropic_messages');
  assert.equal(errorPatch.providerConfig.protocolFamily, 'anthropic');
});

test('sendMessageCommand stops a newly denied profile model before any sidecar work', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  let activeConfig = {
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    allowedModels: ['demo-model'],
    deniedModels: [],
  };
  let configReads = 0;
  let sidecarCalls = 0;
  const context = createContext({
    providerStore: {
      getConfig() {
        configReads += 1;
        return activeConfig;
      },
      async getApiKey() {
        activeConfig = {
          ...activeConfig,
          model: 'blocked-model',
          allowedModels: ['blocked-model'],
          deniedModels: ['BLOCKED-MODEL'],
        };
        return 'sk-test';
      },
    },
  });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Old connection still shown in the webview',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: {
      ok: true,
      status: 'connected',
      detail: 'The old connection was previously validated.',
      checkedAt: new Date().toISOString(),
      providerName: 'Old connection still shown in the webview',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
    },
  };
  context.sidecarManager = {
    async ensureRunning() {
      sidecarCalls += 1;
      throw new Error('A blocked model must not start the sidecar.');
    },
  };
  context.sidecarClient = {
    async postJson() {
      sidecarCalls += 1;
      throw new Error('A blocked model must not contact the sidecar.');
    },
  };

  const result = await sendMessageCommand(context, {
    text: 'Help me continue this lesson.',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /blocked for this connection/i);
  assert.match(result.message ?? '', /Settings/i);
  assert.ok(configReads >= 2, 'the guard should re-read the active provider after async key lookup');
  assert.equal(sidecarCalls, 0);
});

test('sendStreamMessageCommand stops models outside the allowed list before opening a stream', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  let sidecarCalls = 0;
  const context = createContext({
    providerStore: {
      getConfig() {
        return {
          name: 'Local Compatible',
          baseUrl: 'http://localhost:1234/v1',
          model: 'legacy-model',
          allowedModels: ['supported-model'],
          deniedModels: [],
        };
      },
      async getApiKey() {
        return 'sk-test';
      },
    },
  });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'legacy-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['legacy-model'],
    resolvedModel: 'legacy-model',
    modelListStatus: 'ready',
    lastTestResult: {
      ok: true,
      status: 'connected',
      detail: 'Provider previously validated.',
      checkedAt: new Date().toISOString(),
      providerName: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'legacy-model',
      ...VERIFIED_STREAMING_PROBE,
    },
  };
  context.sidecarManager = {
    async ensureRunning() {
      sidecarCalls += 1;
      throw new Error('A model outside the allowed list must not start the sidecar.');
    },
  };
  context.sidecarClient = {
    async *fetchSSE() {
      sidecarCalls += 1;
      throw new Error('A model outside the allowed list must not open a stream.');
    },
  };

  const result = await sendStreamMessageCommand(context, {
    text: 'Help me choose the next focused step.',
    stream: true,
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /not enabled for this connection/i);
  assert.match(result.message ?? '', /allowed list/i);
  assert.equal(sidecarCalls, 0);
});

test('sendMessageCommand blocks immediately when the last provider test already proved the reply is unusable', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-send-blocked-by-last-test' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: {
      ok: false,
      status: 'language_corruption',
      detail:
        'Provider reachable, but it corrupted Chinese input into question marks before the model saw it.',
      checkedAt: '2026-05-24T00:00:00.000Z',
      providerName: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
      errorCategory: 'language_corruption',
      retryable: false,
      statusCode: 200,
    },
  };

  let turnAttempts = 0;
  context.sidecarClient = {
    async postJson(port, requestPath) {
      if (requestPath === '/session/message') {
        turnAttempts += 1;
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async getJson() {
      throw new Error('Unexpected GET');
    },
  };

  const result = await sendMessageCommand(context, {
    text: '继续这轮训练',
    intent: 'coach',
    responseLanguage: 'zh-CN',
    answerMode: 'coach-first',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /\u4e2d\u6587\u6d88\u606f\u6ca1\u6709\u6b63\u5e38\u9001\u8fbe/);
  assert.match(result.message ?? '', /\u8bbe\u7f6e/);
  assert.equal(turnAttempts, 0);
});

test('sendMessageCommand does not reuse an English provider test for a zh-CN turn', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-send-language-guard' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    availableModels: ['demo-model'],
    modelListStatus: 'ready',
    lastTestResult: {
      ok: true,
      status: 'connected',
      detail: 'Provider reachable. Chat probe succeeded.',
      checkedAt: new Date().toISOString(),
      providerName: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
      responseLanguage: 'en-US',
    },
  };

  let requestCount = 0;
  context.sidecarClient = {
    async postJson() {
      requestCount += 1;
      throw new Error('The host guard should stop this turn before any sidecar request.');
    },
    async getJson() {
      throw new Error('The host guard should stop this turn before any sidecar request.');
    },
  };

  const result = await sendMessageCommand(context, {
    text: '请先帮我检查中文输入是否可用。',
    intent: 'coach',
    responseLanguage: 'zh-CN',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /\u8fde\u63a5\u8fd8\u6ca1\u6709\u786e\u8ba4\u53ef\u7528/);
  assert.match(result.message ?? '', /\u5148\u6d4b\u8bd5\u8fde\u63a5/);
  assert.equal(requestCount, 0);
});

test('sendMessageCommand runs a strict provider preflight before first coach send when no successful reply proof exists', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
      },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-send-needs-validation' });
  context.providerStore.saveLastTestResult = async () => undefined;
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
  };

  let testCalls = 0;
  let turnCalls = 0;
  context.sidecarClient = {
    async postJson(port, requestPath, body, options) {
      if (requestPath === '/provider/test') {
        testCalls += 1;
        assert.equal(body.response_language, 'zh-CN');
        assert.deepEqual(options, { timeoutMs: 90_000 });
        return {
          ok: true,
          status: 'connected',
          provider_name: 'Local Compatible',
          detail: 'Provider reachable. Chat probe succeeded with model demo-model. Response: pong',
        };
      }
      if (requestPath === '/session/message') {
        turnCalls += 1;
        return {
          session_id: 'session-send-needs-validation',
          reply: { content: '好的，我们先把这轮目标缩成一个最小实现动作。', metadata: {} },
          snapshot: {
            messages: [],
            memory: {},
            plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          },
          suggested_actions: [],
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async getJson() {
      throw new Error('Unexpected GET');
    },
  };

  const result = await sendMessageCommand(context, {
    text: '继续这轮训练',
    intent: 'coach',
    responseLanguage: 'zh-CN',
    answerMode: 'coach-first',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(testCalls, 1);
  assert.equal(turnCalls, 1);
  const providerTestPatch = context.__patches.find(
    (patch) => patch?.providerConfig?.lastTestResult?.ok === true,
  );
  assert.equal(providerTestPatch.providerConfig.lastTestResult.responseLanguage, 'zh-CN');
});

test('sendMessageCommand stops before /session/message when the automatic provider preflight still proves the coach unusable', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-send-needs-validation-fail' });
  context.providerStore.saveLastTestResult = async () => undefined;
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
  };

  let testCalls = 0;
  let turnCalls = 0;
  context.sidecarClient = {
    async postJson(port, requestPath) {
      if (requestPath === '/provider/test') {
        testCalls += 1;
        return {
          ok: false,
          status: 'language_corruption',
          provider_name: 'Local Compatible',
          detail:
            'Provider reachable, but it corrupted Chinese input into question marks before the model saw it.',
          error_category: 'language_corruption',
          retryable: false,
          status_code: 200,
        };
      }
      if (requestPath === '/session/message') {
        turnCalls += 1;
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async getJson() {
      throw new Error('Unexpected GET');
    },
  };

  const result = await sendMessageCommand(context, {
    text: '继续这轮训练',
    intent: 'coach',
    responseLanguage: 'zh-CN',
    answerMode: 'coach-first',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  assert.equal(testCalls, 1);
  assert.equal(turnCalls, 0);
  assert.equal(result.message, '这次没有收到可靠的中文回复。请检查模型连接后再试。');
});

test('sendMessageCommand safely records a rate-limited automatic provider preflight', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-send-preflight-rate-limit' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
  };

  let testCalls = 0;
  let turnCalls = 0;
  let savedResult;
  context.providerStore.saveLastTestResult = async (_providerConfig, result) => {
    savedResult = result;
  };
  context.sidecarClient = {
    async postJson(port, requestPath) {
      if (requestPath === '/provider/test') {
        testCalls += 1;
        throw new Error(
          'Sidecar request failed (429): {"detail":"LOCAL_SECRET_SENTINEL rate limit"}',
        );
      }
      if (requestPath === '/session/message') {
        turnCalls += 1;
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async getJson() {
      throw new Error('Unexpected GET');
    },
  };

  const result = await sendMessageCommand(context, {
    text: 'Continue this training turn.',
    intent: 'coach',
    responseLanguage: 'en-US',
    answerMode: 'coach-first',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  assert.equal(result.message, 'The model service is busy right now. Try again in a moment.');
  assert.doesNotMatch(result.message ?? '', /LOCAL_SECRET_SENTINEL|429/);
  assert.equal(testCalls, 1);
  assert.equal(turnCalls, 0);
  const failurePatch = context.__patches.find(
    (patch) => patch?.providerConfig?.modelErrorCategory === 'rate_limit',
  );
  assert.ok(failurePatch);
  assert.equal(failurePatch.providerConfig.modelStatusCode, 429);
  assert.equal(failurePatch.providerConfig.modelRetryable, true);
  assert.doesNotMatch(failurePatch.providerConfig.modelListDetail, /LOCAL_SECRET_SENTINEL|429/);
  assert.equal(savedResult?.errorCategory, 'rate_limit');
  assert.equal(savedResult?.retryable, true);
  assert.doesNotMatch(savedResult?.detail ?? '', /LOCAL_SECRET_SENTINEL|429/);
});

test('sendMessageCommand patches provider failure when turn returns empty_response', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-send-empty-response' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: {
      ok: true,
      status: 'connected',
      detail: 'Provider reachable. Chat probe succeeded with model demo-model. Response: pong',
      checkedAt: new Date().toISOString(),
      providerName: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
      responseLanguage: 'zh-CN',
    },
  };

  context.sidecarClient = {
    async postJson(port, requestPath) {
      if (requestPath === '/session/message') {
        throw new Error(
          'Sidecar request failed (502): {"detail":"Coach reply unusable: empty_response: Provider replied with reasoning-only content and no final coaching reply content."}',
        );
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async getJson() {
      throw new Error('Unexpected GET');
    },
  };

  await assert.rejects(
    sendMessageCommand(context, {
      text: '继续这轮训练',
      intent: 'coach',
      responseLanguage: 'zh-CN',
      answerMode: 'coach-first',
      includeCurrentFile: false,
    }),
    /empty_response/i,
  );

  const errorPatch = context.__patches.find(
    (patch) => patch?.providerConfig?.modelErrorCategory === 'empty_response',
  );
  assert.ok(errorPatch);
  assert.equal(errorPatch.providerConfig.modelListStatus, 'error');
  assert.equal(errorPatch.providerConfig.modelStatusCode, 502);
  assert.equal(errorPatch.providerConfig.modelRetryable, false);
});

test('sendMessageCommand keeps non-coach intents on /turn', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-review-turn-route' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: {
      ok: true,
      status: 'connected',
      detail: 'Provider reachable. Chat probe succeeded with model demo-model. Response: pong',
      checkedAt: new Date().toISOString(),
      providerName: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
      responseLanguage: 'en-US',
    },
  };

  context.sidecarClient = {
    async postJson(port, requestPath, body) {
      context.__postCalls.push([port, requestPath, body]);
      if (requestPath === '/turn') {
        return {
          session_id: 'session-review-turn-route',
          reply: {
            role: 'assistant',
            content: 'Review the smallest failing check first.',
            metadata: {},
          },
          snapshot: {
            messages: [],
            memory: {},
            plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          },
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async getJson() {
      throw new Error('Unexpected GET');
    },
  };

  const result = await sendMessageCommand(context, {
    text: 'Review this change.',
    intent: 'review',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(context.__postCalls[0][1], '/turn');
  assert.equal(context.__postCalls[0][2].intent, 'review');
  assert.equal(context.__postCalls[0][2].remote_name, '');
  assert.equal(context.__postCalls[0][2].workspace_trusted, false);
});

test('sendMessageCommand blocks image attachments when the provider lacks real image input support', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-send-image-blocked' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: true,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: {
      ok: true,
      status: 'connected',
      detail: 'Provider reachable. Chat probe succeeded with model demo-model. Response: pong',
      checkedAt: new Date().toISOString(),
      providerName: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
      responseLanguage: 'en-US',
    },
  };

  const result = await sendMessageCommand(context, {
    text: 'Please inspect this screenshot.',
    intent: 'coach',
    includeCurrentFile: false,
    attachments: [
      {
        id: 'att-1',
        kind: 'image',
        mimeType: 'image/png',
        dataBase64: 'AAAA',
        name: 'diagram.png',
      },
    ],
  });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /pictures cannot be sent right now/i);
  assert.match(result.message ?? '', /text coaching still works/i);
  const coachCalls = context.__postCalls.filter((call) => call[1] === '/session/message');
  assert.equal(coachCalls.length, 0);
});

test('sendStreamMessageCommand blocks image attachments when the provider lacks real image input support', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-stream-image-blocked' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: true,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: {
      ok: true,
      status: 'connected',
      detail: 'Provider reachable. Chat probe succeeded with model demo-model. Response: pong',
      checkedAt: new Date().toISOString(),
      providerName: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
      responseLanguage: 'en-US',
    },
  };

  const result = await sendStreamMessageCommand(context, {
    text: 'Stream this screenshot review.',
    intent: 'coach',
    stream: true,
    includeCurrentFile: false,
    attachments: [
      {
        id: 'att-1',
        kind: 'image',
        mimeType: 'image/png',
        dataBase64: 'AAAA',
        name: 'diagram.png',
      },
    ],
  });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /pictures cannot be sent right now/i);
  assert.match(result.message ?? '', /text coaching still works/i);
  const streamCalls = context.__postCalls.filter((call) => call[1] === '/session/message/stream');
  assert.equal(streamCalls.length, 0);
});

test('sendStreamMessageCommand starts the first Chinese coach stream without a separate provider probe', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-stream-needs-validation' });
  context.providerStore.saveLastTestResult = async () => undefined;
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: VERIFIED_STREAMING_TEST_RESULT,
  };

  let testCalls = 0;
  let streamCalls = 0;
  context.sidecarClient = {
    async postJson(port, requestPath) {
      if (requestPath === '/provider/test') {
        testCalls += 1;
        return {
          ok: true,
          status: 'connected',
          provider_name: 'Local Compatible',
          detail: 'Provider reachable. Chat probe succeeded with model demo-model. Response: pong',
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async *fetchSSE(port, requestPath) {
      assert.equal(requestPath, '/session/message/stream');
      assert.ok(
        context.__postCalls.some(
          (call) => call[0] === 'workbench' && call[1] === 'postMessage' && call[2]?.type === 'stream/start',
        ),
        'the webview should enter its real stream state before the request begins',
      );
      streamCalls += 1;
      yield {
        event: 'complete',
        data: JSON.stringify({
          tokens: 1,
          response: {
            session_id: 'session-stream-needs-validation',
            reply: {
              role: 'assistant',
              content: '先把 remote workspace 的 boundary 说清楚。',
              metadata: {},
            },
            snapshot: {
              messages: [],
              memory: {},
              plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
            },
            suggested_actions: [],
          },
        }),
      };
    },
    async getJson() {
      throw new Error('Unexpected GET');
    },
  };

  const result = await sendStreamMessageCommand(context, {
    text: '请 explain VS Code remote workspace boundary。',
    intent: 'coach',
    stream: true,
    responseLanguage: 'zh-CN',
    answerMode: 'coach-first',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(testCalls, 0);
  assert.equal(streamCalls, 1);
  const workbenchMessages = context.__postCalls
    .filter((call) => call[0] === 'workbench' && call[1] === 'postMessage')
    .map((call) => call[2]);
  const streamStartIndex = workbenchMessages.findIndex((message) => message.type === 'stream/start');
  assert.ok(streamStartIndex >= 0, 'the stream should expose its actual start state');
  assert.equal(
    workbenchMessages.some((message) =>
      message.type === 'operation/status' &&
      /test the provider|testing the provider|connection check/i.test(String(message.payload?.message ?? '')),
    ),
    false,
    'the host must not claim it is testing the provider when it is sending the real request',
  );
  assert.ok(
    workbenchMessages.some((message) => message.type === 'operation/status' && message.payload?.phase === 'pending'),
    'the host should show the turn as pending before the sidecar request finishes',
  );
});

test('sendStreamMessageCommand blocks a known unusable Chinese connection without sending or probing again', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-stream-needs-validation-fail' });
  context.providerStore.saveLastTestResult = async () => undefined;
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: {
      ok: false,
      status: 'language_corruption',
      detail:
        'Provider reachable, but it corrupted Chinese input into question marks before the model saw it.',
      errorCategory: 'language_corruption',
      checkedAt: '2026-06-20T00:00:00.000Z',
      providerName: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
      responseLanguage: 'zh-CN',
    },
  };

  let testCalls = 0;
  let streamCalls = 0;
  context.sidecarClient = {
    async postJson(port, requestPath) {
      if (requestPath === '/provider/test') {
        testCalls += 1;
        return {
          ok: false,
          status: 'language_corruption',
          provider_name: 'Local Compatible',
          detail:
            'Provider reachable, but it corrupted Chinese input into question marks before the model saw it.',
          error_category: 'language_corruption',
          retryable: false,
          status_code: 200,
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async *fetchSSE() {
      streamCalls += 1;
      yield {
        event: 'complete',
        data: JSON.stringify({}),
      };
    },
    async getJson() {
      throw new Error('Unexpected GET');
    },
  };

  const result = await sendStreamMessageCommand(context, {
    text: '请 explain VS Code remote workspace boundary。',
    intent: 'coach',
    stream: true,
    responseLanguage: 'zh-CN',
    answerMode: 'coach-first',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  assert.equal(testCalls, 0);
  assert.equal(streamCalls, 0);
  assert.ok(result.message?.trim());
  assert.equal(
    context.__postCalls.some(
      (call) => call[0] === 'workbench' && call[1] === 'postMessage' && call[2]?.type === 'stream/start',
    ),
    false,
  );
});

test('sendStreamMessageCommand does not probe again for a stale successful connection record', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-stream-stale-proof' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: {
      ok: true,
      status: 'connected',
      detail: 'Provider was previously reachable.',
      checkedAt: '2000-01-01T00:00:00.000Z',
      providerName: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
      responseLanguage: 'en-US',
      ...VERIFIED_STREAMING_PROBE,
    },
  };

  let probeCalls = 0;
  let streamCalls = 0;
  context.sidecarClient = {
    async postJson(_port, requestPath) {
      if (requestPath === '/provider/test') {
        probeCalls += 1;
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async *fetchSSE(_port, requestPath) {
      assert.equal(requestPath, '/session/message/stream');
      streamCalls += 1;
      yield {
        event: 'complete',
        data: JSON.stringify({
          tokens: 1,
          response: {
            session_id: 'session-stream-stale-proof-complete',
            reply: { role: 'assistant', content: 'Continue with the next step.', metadata: {} },
          },
        }),
      };
    },
    async getJson() {
      throw new Error('Unexpected GET');
    },
  };

  const result = await sendStreamMessageCommand(context, {
    text: 'Explain the current workspace boundary.',
    intent: 'coach',
    stream: true,
    responseLanguage: 'zh-CN',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(probeCalls, 0);
  assert.equal(streamCalls, 1);
});

test('sendStreamMessageCommand closes its started stream with friendly copy when the model cannot be reached', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-stream-network-error' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: VERIFIED_STREAMING_TEST_RESULT,
  };
  context.sidecarClient = {
    async *fetchSSE() {
      throw new Error('connect ECONNREFUSED 127.0.0.1:1234');
    },
  };

  const result = await sendStreamMessageCommand(context, {
    text: 'Explain the current workspace boundary.',
    intent: 'coach',
    stream: true,
    responseLanguage: 'zh-CN',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  assert.doesNotMatch(result.message ?? '', /ECONNREFUSED/i);
  assert.equal(context.getStreamingState().isStreaming, false);
  const streamMessages = context.__postCalls
    .filter((call) => call[0] === 'workbench' && call[1] === 'postMessage')
    .map((call) => call[2]);
  const streamStartIndex = streamMessages.findIndex((message) => message.type === 'stream/start');
  const streamErrorIndex = streamMessages.findIndex((message) => message.type === 'stream/error');
  assert.ok(streamStartIndex >= 0);
  assert.ok(streamErrorIndex > streamStartIndex);
  assert.equal(streamMessages[streamErrorIndex].payload.category, 'network');
  assert.doesNotMatch(streamMessages[streamErrorIndex].payload.error, /ECONNREFUSED/i);
});

test('sendStreamMessageCommand treats an SSE EOF without completion as a failed reply', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-stream-clean-eof' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: VERIFIED_STREAMING_TEST_RESULT,
  };
  context.sidecarClient = {
    async *fetchSSE() {
      yield { event: 'message', data: JSON.stringify({ chunk: 'A partial reply.' }) };
    },
  };

  const result = await sendStreamMessageCommand(context, {
    text: 'Explain the current workspace boundary.',
    intent: 'coach',
    stream: true,
    responseLanguage: 'en-US',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  assert.doesNotMatch(result.message ?? '', /SSE|EOF|completion event/i);
  assert.equal(context.getStreamingState().isStreaming, false);
  assert.equal(context.getStreamingState().streamedContent, 'A partial reply.');
  assert.equal(context.__synced.length, 0);
  const streamMessages = context.__postCalls
    .filter((call) => call[0] === 'workbench' && call[1] === 'postMessage')
    .map((call) => call[2]);
  const start = streamMessages.find((message) => message.type === 'stream/start');
  const error = streamMessages.find((message) => message.type === 'stream/error');
  assert.ok(start);
  assert.ok(error);
  assert.equal(error.payload.messageId, start.payload.messageId);
  assert.equal(streamMessages.some((message) => message.type === 'stream/complete'), false);
});

test('sendStreamMessageCommand keeps recoverable SSE errors out of streamed text', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-stream-recoverable-error' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: VERIFIED_STREAMING_TEST_RESULT,
  };
  context.sidecarClient = {
    async *fetchSSE() {
      yield {
        event: 'error',
        data: JSON.stringify({
          error: 'The configured provider does not expose native streaming.',
          category: 'streaming_unavailable',
          recoverable: true,
          terminal: false,
          degraded: true,
        }),
      };
      yield {
        event: 'complete',
        data: JSON.stringify({
          tokens: 1,
          response: {
            session_id: 'session-stream-recoverable-error-complete',
            reply: {
              role: 'assistant',
              content: 'The buffered reply is complete.',
              metadata: {},
            },
          },
        }),
      };
    },
  };

  const result = await sendStreamMessageCommand(context, {
    text: 'Continue the current lesson.',
    intent: 'coach',
    stream: true,
    responseLanguage: 'en-US',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(context.getStreamingState().streamedContent, '');
  const messages = context.__postCalls
    .filter((call) => call[0] === 'workbench' && call[1] === 'postMessage')
    .map((call) => call[2]);
  assert.equal(messages.some((message) => message.type === 'stream/error'), false);
  assert.equal(messages.some((message) => message.type === 'stream/chunk'), false);
  assert.ok(
    messages.some(
      (message) =>
        message.type === 'operation/status' &&
        /degraded/i.test(String(message.payload?.message)),
    ),
  );
  assert.equal(messages.filter((message) => message.type === 'stream/complete').length, 1);
});

test('sendStreamMessageCommand treats terminal SSE errors as failures, not chunks', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-stream-terminal-error' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: VERIFIED_STREAMING_TEST_RESULT,
  };
  context.sidecarClient = {
    async *fetchSSE() {
      yield {
        event: 'error',
        data: JSON.stringify({
          error: 'The provider rejected this request.',
          terminal: true,
          recoverable: false,
        }),
      };
    },
  };

  const result = await sendStreamMessageCommand(context, {
    text: 'Continue the current lesson.',
    intent: 'coach',
    stream: true,
    responseLanguage: 'en-US',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  const messages = context.__postCalls
    .filter((call) => call[0] === 'workbench' && call[1] === 'postMessage')
    .map((call) => call[2]);
  assert.equal(messages.some((message) => message.type === 'stream/chunk'), false);
  assert.equal(messages.filter((message) => message.type === 'stream/error').length, 1);
});

test('sendStreamMessageCommand admits only one Coach stream for a context at a time', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-stream-single-flight' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: VERIFIED_STREAMING_TEST_RESULT,
  };
  let releaseFirstStream;
  const firstStreamGate = new Promise((resolve) => {
    releaseFirstStream = resolve;
  });
  let signalFirstFetch;
  const firstFetchStarted = new Promise((resolve) => {
    signalFirstFetch = resolve;
  });
  let streamCalls = 0;
  context.sidecarClient = {
    async *fetchSSE() {
      streamCalls += 1;
      signalFirstFetch();
      await firstStreamGate;
      yield {
        event: 'complete',
        data: JSON.stringify({
          tokens: 1,
          response: {
            session_id: 'session-stream-single-flight-complete',
            reply: { role: 'assistant', content: 'Finished the first stream.', metadata: {} },
          },
        }),
      };
    },
  };
  const payload = {
    text: 'Explain the current workspace boundary.',
    intent: 'coach',
    stream: true,
    responseLanguage: 'en-US',
    includeCurrentFile: false,
  };

  const first = sendStreamMessageCommand(context, payload);
  await firstFetchStarted;
  const second = await sendStreamMessageCommand(context, payload);

  assert.equal(second.ok, false);
  assert.match(second.message ?? '', /still working/i);
  assert.equal(streamCalls, 1);
  releaseFirstStream();
  assert.equal((await first).ok, true);
  const streamMessages = context.__postCalls
    .filter((call) => call[0] === 'workbench' && call[1] === 'postMessage')
    .map((call) => call[2]);
  assert.equal(streamMessages.filter((message) => message.type === 'stream/start').length, 1);
  assert.equal(streamMessages.filter((message) => message.type === 'stream/complete').length, 1);
});

test('sendStreamMessageCommand localizes network failures for every supported language', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const expectedMessages = {
    'zh-CN': '暂时连不上模型服务。请检查连接后再试。',
    'en-US': 'Trainer could not reach the model service. Check the connection and try again.',
    'es-ES': 'Trainer no puede conectarse al servicio del modelo. Revisa la conexión e intentalo de nuevo.',
    'fr-FR': 'Trainer ne peut pas joindre le service du modèle. Vérifiez la connexion, puis réessayez.',
    'de-DE': 'Trainer kann den Modelldienst nicht erreichen. Prüfen Sie die Verbindung und versuchen Sie es erneut.',
    'ja-JP': 'モデルサービスに接続できません。接続を確認して、もう一度試してください。',
    'ko-KR': '모델 서비스에 연결할 수 없습니다. 연결을 확인한 뒤 다시 시도해 주세요.',
    'pt-BR': 'Trainer não consegue se conectar ao serviço do modelo. Verifique a conexão e tente novamente.',
  };

  for (const [responseLanguage, expectedMessage] of Object.entries(expectedMessages)) {
    const context = createContext({ initialSessionId: 'session-stream-' + responseLanguage });
    context.__hostState.bootstrap.providerConfig = {
      configured: true,
      name: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
      apiKeyConfigured: true,
      availableModels: ['demo-model'],
      resolvedModel: 'demo-model',
      modelListStatus: 'ready',
      lastTestResult: VERIFIED_STREAMING_TEST_RESULT,
    };
    context.sidecarClient = {
      async *fetchSSE() {
        throw new Error('connect ECONNREFUSED 127.0.0.1:1234');
      },
    };

    const result = await sendStreamMessageCommand(context, {
      text: 'Explain the current workspace boundary.',
      intent: 'coach',
      stream: true,
      responseLanguage,
      includeCurrentFile: false,
    });

    assert.equal(result.ok, false);
    assert.equal(result.message, expectedMessage);
    const streamError = context.__postCalls
      .filter((call) => call[0] === 'workbench' && call[1] === 'postMessage')
      .map((call) => call[2])
      .find((message) => message.type === 'stream/error');
    assert.equal(streamError.payload.error, expectedMessage);
    assert.doesNotMatch(streamError.payload.error, /ECONNREFUSED/i);
  }
});

test('sendStreamMessageCommand forwards agent completion metadata to the webview', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({
    initialSessionId: 'session-stream-before',
    sidecarClient: {
      async *fetchSSE() {
        yield {
          event: 'status',
          data: JSON.stringify({ phase: 'preparing_context' }),
        };
        yield {
          event: 'tool_call',
          data: JSON.stringify({
            id: 'tool-1',
            name: 'recall_memory',
            arguments: { focus: 'async iteration' },
            step: 0,
          }),
        };
        yield {
          event: 'tool_result',
          data: JSON.stringify({
            id: 'tool-1',
            name: 'recall_memory',
            ok: true,
            result: { ok: true, summary: 'memory recalled' },
            step: 0,
          }),
        };
        yield {
          event: 'complete',
          data: JSON.stringify({
            tokens: 4,
            response: {
              session_id: 'session-stream-after',
              reply: {
                role: 'assistant',
                content: 'Patch the smallest async iterator call site next.',
                metadata: {},
              },
              agent: {
                agentic: true,
                summary: 'Closed the async investigation loop.',
                next_step: 'Patch the smallest async iterator call site.',
                stop_reason: 'coach_finalize',
                tool_events: [
                  { type: 'tool_call', id: 'tool-1', name: 'recall_memory' },
                  { type: 'tool_result', id: 'tool-1', name: 'recall_memory', ok: true },
                ],
              },
            },
          }),
        };
      },
    },
  });
  context.__hostState.bootstrap.providerConfig = {
    lastTestResult: VERIFIED_STREAMING_TEST_RESULT,
  };

  const result = await sendStreamMessageCommand(context, {
    text: 'Help me close the loop on async iteration.',
    intent: 'coach',
    stream: true,
    responseLanguage: 'en-US',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(context.__sessionIds.at(-1), 'session-stream-after');
  assert.ok(context.__patches.length >= 1);
  const statusEvent = context.__postCalls.find(
    (entry) =>
      entry[0] === 'workbench' &&
      entry[1] === 'postMessage' &&
      entry[2] &&
      entry[2].type === 'operation/status' &&
      entry[2].payload?.phase === 'preparing_context',
  );
  assert.deepEqual(statusEvent?.[2], {
    type: 'operation/status',
    payload: {
      tone: 'info',
      message: 'Preparing the current workspace and learning context.',
      phase: 'preparing_context',
    },
  });
  assert.equal(
    context.__postCalls.some(
      (entry) =>
        entry[0] === 'workbench' &&
        entry[1] === 'postMessage' &&
        entry[2]?.type === 'stream/chunk' &&
        String(entry[2]?.payload?.chunk).includes('preparing_context'),
    ),
    false,
  );
  const completeEvent = context.__postCalls.find(
    (entry) =>
      entry[0] === 'workbench' &&
      entry[1] === 'postMessage' &&
      entry[2] &&
      entry[2].type === 'stream/complete',
  );
  assert.equal(completeEvent?.[2]?.type, 'stream/complete');
  assert.equal(typeof completeEvent?.[2]?.payload.messageId, 'string');
  assert.deepEqual(
    { ...completeEvent?.[2]?.payload, messageId: undefined },
    {
      messageId: undefined,
      tokens: 4,
      agentic: true,
      summary: 'Closed the async investigation loop.',
      nextStep: 'Patch the smallest async iterator call site.',
      stopReason: 'coach_finalize',
      toolCount: 1,
      reliabilityPhase: 'acked',
      reliabilityOutcome: 'success',
    },
  );
});

test('global plan commands use explicit local routes without requiring a provider', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { createGlobalPlanCommand, linkCurrentProjectPlanCommand } = loadWithVscodeMock(
    sessionCommandsModulePath,
    vscodeMock,
  );
  const requests = [];
  const context = createContext({ initialSessionId: 'session-global' });
  context.providerStore = {
    getConfig() {
      throw new Error('Global plan commands must not read provider configuration.');
    },
    async getApiKey() {
      throw new Error('Global plan commands must not read provider credentials.');
    },
  };
  context.sidecarClient = {
    async postJson(port, requestPath, body) {
      requests.push(['POST', port, requestPath, body]);
      return {
        global_plan: {
          id: 'global-1',
          title: 'Long-term engineering mastery',
          summary: 'Build reliable software across projects.',
          goals: ['Build reliable software'],
          stages: [],
          frozen: false,
        },
        project_plan_link: null,
        snapshot: {
          plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          global_plan: {
            id: 'global-1',
            title: 'Long-term engineering mastery',
            summary: 'Build reliable software across projects.',
            goals: ['Build reliable software'],
            stages: [],
            frozen: false,
          },
          project_plan_link: null,
        },
      };
    },
    async putJson(port, requestPath, body) {
      requests.push(['PUT', port, requestPath, body]);
      return {
        global_plan: {
          id: 'global-1',
          title: 'Long-term engineering mastery',
          summary: 'Build reliable software across projects.',
          goals: ['Build reliable software'],
          stages: [],
          frozen: false,
        },
        project_plan_link: {
          global_plan_id: 'global-1',
          workspace_id: 'F:\\trainer-a',
          project_plan_id: 'plan-1',
          linked_at: '2026-07-11T00:00:00.000Z',
          updated_at: '2026-07-11T00:00:00.000Z',
        },
        snapshot: {
          plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          global_plan: {
            id: 'global-1',
            title: 'Long-term engineering mastery',
            summary: 'Build reliable software across projects.',
            goals: ['Build reliable software'],
            stages: [],
            frozen: false,
          },
          project_plan_link: {
            global_plan_id: 'global-1',
            workspace_id: 'F:\\trainer-a',
            project_plan_id: 'plan-1',
            linked_at: '2026-07-11T00:00:00.000Z',
            updated_at: '2026-07-11T00:00:00.000Z',
          },
        },
      };
    },
  };

  const created = await createGlobalPlanCommand(context, {
    title: 'Long-term engineering mastery',
    goals: ['Build reliable software'],
  });
  const linked = await linkCurrentProjectPlanCommand(context);

  assert.equal(created.ok, true);
  assert.equal(linked.ok, true);
  assert.deepEqual(requests, [
    [
      'POST',
      34891,
      '/plan/global',
      {
        session_id: 'session-global',
        workspace_id: 'F:\\trainer-a',
        title: 'Long-term engineering mastery',
        goals: ['Build reliable software'],
      },
    ],
    [
      'PUT',
      34891,
      '/plan/global/projects',
      {
        session_id: 'session-global',
        workspace_id: 'F:\\trainer-a',
        project_plan_id: 'plan-1',
      },
    ],
  ]);
  assert.equal(context.__patches[0].plan.id, 'plan-1');
  assert.equal(context.__patches[0].globalPlan.id, 'global-1');
  assert.equal(context.__patches[1].projectPlanLink.projectPlanId, 'plan-1');
  assert.equal(context.__synced.length, 2);
});

test('resumeLatestCoachCheckpointCommand restores the current Coach thread from its latest saved checkpoint', async () => {
  const vscodeMock = {
    window: {
      async showInformationMessage() {
        return undefined;
      },
    },
    workspace: {},
  };
  const { resumeLatestCoachCheckpointCommand } = loadWithVscodeMock(
    sessionCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({
    initialSessionId: 'session-current',
    initialStreamingState: createStreamingState({
      isStreaming: true,
      streamedContent: 'Stale partial response',
      streamMessageId: 'message-stale',
    }),
  });
  const requests = [];
  const checkpointId = 'agent-turn-0123456789abcdef0123456789abcdef';
  context.sidecarClient = {
    async getJson(port, requestPath) {
      requests.push(['GET', port, requestPath]);
      if (
        requestPath ===
        '/session/checkpoints?workspace_id=F%3A%5Ctrainer-a&session_id=session-current&limit=1'
      ) {
        return {
          checkpoints: [
            {
              checkpoint_id: checkpointId,
              session_id: 'session-current',
              created_at: '2026-07-15T01:02:03.000Z',
              next_step: 'Check the saved route before continuing.',
            },
          ],
        };
      }
      if (
        requestPath ===
        '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-current'
      ) {
        return {
          session_id: 'session-current',
          messages: [
            { id: 'saved-user', role: 'user', content: 'Help me trace this route.' },
            { id: 'saved-assistant', role: 'assistant', content: 'Start with the saved boundary.' },
          ],
          memory: {},
          plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
        };
      }
      throw new Error(`Unexpected GET ${requestPath}`);
    },
    async postJson(port, requestPath, body) {
      requests.push(['POST', port, requestPath, body]);
      if (requestPath === `/session/checkpoints/${checkpointId}/resume`) {
        return {
          checkpoint_id: checkpointId,
          session_id: 'session-current',
          workspace_id: 'F:\\trainer-a',
          executed: false,
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
  };

  const result = await resumeLatestCoachCheckpointCommand(context);

  assert.equal(result.ok, true);
  assert.deepEqual(requests, [
    [
      'GET',
      34891,
      '/session/checkpoints?workspace_id=F%3A%5Ctrainer-a&session_id=session-current&limit=1',
    ],
    [
      'POST',
      34891,
      `/session/checkpoints/${checkpointId}/resume`,
      { workspaceId: 'F:\\trainer-a', sessionId: 'session-current' },
    ],
    [
      'GET',
      34891,
      '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-current',
    ],
  ]);
  assert.deepEqual(context.__sessionIds, ['session-current']);
  assert.equal(context.__shown.length, 1);
  assert.equal(context.__hostState.streamingState.isStreaming, false);
  assert.equal(context.__hostState.streamingState.streamedContent, '');
  assert.deepEqual(
    context.__patches.at(-1).conversation.map((message) => message.body),
    ['Help me trace this route.', 'Start with the saved boundary.'],
  );
  assert.deepEqual(context.__postCalls.at(-1), [
    'workbench',
    'postMessage',
    {
      type: 'ui/restoreView',
      payload: {
        sessionId: 'session-current',
        activeView: 'coach',
        resumeReason: 'Check the saved route before continuing.',
      },
    },
  ]);
  assert.equal(requests.some(([, , requestPath]) => requestPath === '/session/message'), false);
  assert.equal(requests.some(([, , requestPath]) => requestPath === '/turn'), false);
});

test('replayLatestCoachCheckpointCommand only opens the stored trace and leaves the Coach thread untouched', async () => {
  const openedDocuments = [];
  const shownDocuments = [];
  const informationMessages = [];
  const vscodeMock = {
    window: {
      async showTextDocument(document, options) {
        shownDocuments.push([document, options]);
      },
      async showInformationMessage(message) {
        informationMessages.push(message);
      },
    },
    workspace: {
      async openTextDocument(options) {
        openedDocuments.push(options);
        return { uri: 'untitled:trainer-checkpoint.md' };
      },
    },
  };
  const { replayLatestCoachCheckpointCommand } = loadWithVscodeMock(
    sessionCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ initialSessionId: 'session-current' });
  const checkpointId = 'agent-turn-fedcba9876543210fedcba9876543210';
  const requests = [];
  context.sidecarClient = {
    async getJson(port, requestPath) {
      requests.push(['GET', port, requestPath]);
      return {
        checkpoints: [
          {
            checkpoint_id: checkpointId,
            session_id: 'session-current',
            created_at: '2026-07-15T02:03:04.000Z',
            next_step: 'Run the saved narrow check.',
          },
        ],
      };
    },
    async postJson(port, requestPath, body) {
      requests.push(['POST', port, requestPath, body]);
      if (requestPath !== `/session/checkpoints/${checkpointId}/replay`) {
        throw new Error(`Replay must not use ${requestPath}`);
      }
      return {
        mode: 'stored_trace',
        replayed: true,
        executed: false,
        checkpoint: {
          checkpoint_id: checkpointId,
          request: { message: 'Why did this route return early?' },
          final: { content: 'The saved condition returns before the fallback.' },
          recovery: { next_step: 'Run the saved narrow check.' },
          trace: {
            tool_events: [{ type: 'tool_call', name: 'read_file' }],
          },
        },
      };
    },
  };

  const result = await replayLatestCoachCheckpointCommand(context);

  assert.equal(result.ok, true);
  assert.deepEqual(requests, [
    [
      'GET',
      34891,
      '/session/checkpoints?workspace_id=F%3A%5Ctrainer-a&session_id=session-current&limit=1',
    ],
    [
      'POST',
      34891,
      `/session/checkpoints/${checkpointId}/replay`,
      { workspaceId: 'F:\\trainer-a', sessionId: 'session-current' },
    ],
  ]);
  assert.equal(openedDocuments.length, 1);
  assert.equal(openedDocuments[0].language, 'markdown');
  assert.match(openedDocuments[0].content, /saved replay/i);
  assert.match(openedDocuments[0].content, /Why did this route return early\?/);
  assert.match(openedDocuments[0].content, /The saved condition returns before the fallback\./);
  assert.equal(shownDocuments.length, 1);
  assert.deepEqual(informationMessages, [
    'Opened the saved Coach trace. Your current conversation is unchanged.',
  ]);
  assert.deepEqual(context.__sessionIds, []);
  assert.deepEqual(context.__patches, []);
  assert.deepEqual(context.__streamingStates, []);
  assert.deepEqual(context.__postCalls, []);
  assert.equal(requests.some(([, , requestPath]) => /\/session\/message|\/turn/.test(requestPath)), false);
});

test('checkpoint commands explain when the current Coach conversation has no saved checkpoint', async () => {
  const vscodeMock = {
    window: {},
    workspace: {},
  };
  const { resumeLatestCoachCheckpointCommand, replayLatestCoachCheckpointCommand } = loadWithVscodeMock(
    sessionCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ initialSessionId: 'session-current' });
  const requests = [];
  context.sidecarClient = {
    async getJson(port, requestPath) {
      requests.push(['GET', port, requestPath]);
      return { checkpoints: [] };
    },
    async postJson() {
      throw new Error('Checkpoint actions should not run without a saved checkpoint.');
    },
  };

  const resumed = await resumeLatestCoachCheckpointCommand(context);
  const replayed = await replayLatestCoachCheckpointCommand(context);

  assert.equal(resumed.ok, false);
  assert.equal(replayed.ok, false);
  assert.match(resumed.message ?? '', /no saved Coach checkpoint/i);
  assert.match(replayed.message ?? '', /no saved Coach checkpoint/i);
  assert.equal(requests.length, 2);
  assert.deepEqual(context.__sessionIds, []);
  assert.deepEqual(context.__patches, []);
});

const HOST_FAKE_KEY = 'sk-test-not-a-real-key-aaaaaaaa';
const HOST_LEAK_TEXT = [
  'Traceback (most recent call last):',
  '  File "app.py", line 12, in run',
  'KeyError: boom',
  '{"choices":[{"message":{"content":"hidden","token":"fake-token-zzzz"}}]}',
  `api_key=${HOST_FAKE_KEY}`,
].join('\n');

function assertHostPayloadSanitized(value) {
  const rendered = JSON.stringify(value);
  assert.doesNotMatch(rendered, /sk-test-not-a-real-key-aaaaaaaa/);
  assert.doesNotMatch(rendered, /Traceback \(most recent call last\)/i);
  assert.doesNotMatch(rendered, /File "app\.py"/);
  assert.doesNotMatch(rendered, /"choices"/);
  assert.doesNotMatch(rendered, /fake-token-zzzz/);
  assert.doesNotMatch(rendered, /api_key=sk-/i);
}

function workbenchMessages(context) {
  return context.__postCalls
    .filter((call) => call[0] === 'workbench' && call[1] === 'postMessage')
    .map((call) => call[2]);
}

test('sendStreamMessageCommand posts a sanitized stream/error when the sidecar SSE error leaks', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({ initialSessionId: 'session-host-stream-error-sanitize' });
  context.__hostState.bootstrap.providerConfig = {
    configured: true,
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    apiKeyConfigured: true,
    availableModels: ['demo-model'],
    resolvedModel: 'demo-model',
    modelListStatus: 'ready',
    lastTestResult: VERIFIED_STREAMING_TEST_RESULT,
  };
  context.sidecarClient = {
    async *fetchSSE() {
      yield {
        event: 'error',
        data: JSON.stringify({
          error: HOST_LEAK_TEXT,
          terminal: true,
          recoverable: false,
        }),
      };
    },
  };

  const result = await sendStreamMessageCommand(context, {
    text: 'Continue the current lesson.',
    intent: 'coach',
    stream: true,
    responseLanguage: 'en-US',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  const streamError = workbenchMessages(context).find((message) => message.type === 'stream/error');
  assert.ok(streamError);
  assertHostPayloadSanitized(streamError);
  assertHostPayloadSanitized(result.message);
  assert.match(String(streamError.payload.error), /failed|hidden|Settings|Try again|connection/i);
  assert.ok(String(streamError.payload.error).trim().length > 0);
});

test('sendStreamMessageCommand sanitizes leaking tool_result before postMessage', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({
    initialSessionId: 'session-host-tool-result-sanitize',
    sidecarClient: {
      async *fetchSSE() {
        yield {
          event: 'tool_call',
          data: JSON.stringify({
            id: 'tool-leak',
            name: 'search_memory',
            arguments: { query: 'async iteration', api_key: HOST_FAKE_KEY },
            step: 0,
          }),
        };
        yield {
          event: 'tool_result',
          data: JSON.stringify({
            id: 'tool-leak',
            name: 'search_memory',
            ok: false,
            result: {
              ok: false,
              hits: ['safe-hit'],
              error: HOST_LEAK_TEXT,
            },
            step: 0,
          }),
        };
        yield {
          event: 'complete',
          data: JSON.stringify({
            tokens: 2,
            response: {
              session_id: 'session-host-tool-result-sanitize',
              reply: {
                role: 'assistant',
                content: 'The search step failed. Check Settings, then retry the same question.',
                metadata: {},
              },
            },
          }),
        };
      },
    },
  });
  context.__hostState.bootstrap.providerConfig = {
    lastTestResult: VERIFIED_STREAMING_TEST_RESULT,
  };

  const result = await sendStreamMessageCommand(context, {
    text: 'Search memory for the last failed check.',
    intent: 'coach',
    stream: true,
    responseLanguage: 'en-US',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  const messages = workbenchMessages(context);
  const toolCall = messages.find((message) => message.type === 'stream/tool_call');
  const toolResult = messages.find((message) => message.type === 'stream/tool_result');
  assert.ok(toolCall);
  assert.ok(toolResult);
  assertHostPayloadSanitized(toolCall);
  assertHostPayloadSanitized(toolResult);
  assert.equal(toolResult.payload.ok, false);
  assert.deepEqual(toolResult.payload.result.hits, ['safe-hit']);
  assert.match(String(toolResult.payload.result.error), /failed|hidden|Settings|Try again|connection/i);
  const activity = context.getStreamingState().agentActivity ?? [];
  const stored = activity.find((entry) => entry.id === 'tool-leak');
  assert.ok(stored);
  assertHostPayloadSanitized(stored);
});
