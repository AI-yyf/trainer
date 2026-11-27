'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');

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

const protocolModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'protocol.js',
);

const webviewSrcRoot = path.resolve(__dirname, '..', 'webview', 'src');
const webviewRequire = Module.createRequire(path.join(webviewSrcRoot, '..', 'package.json'));
const { buildSync } = webviewRequire('esbuild');

function loadWebviewModule(relativeFile) {
  const filename = path.join(webviewSrcRoot, relativeFile);
  const { outputFiles } = buildSync({
    entryPoints: [filename],
    bundle: true,
    platform: 'node',
    format: 'cjs',
    write: false,
    external: ['react', 'react-dom', 'react/jsx-runtime', '*?worker&inline'],
  });
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  mod._compile(outputFiles[0].text, filename);
  return mod.exports;
}

const VERIFIED_STREAMING_TEST_RESULT = {
  ok: true,
  status: 'ready',
  detail: 'Provider streaming probe observed an incremental chunk.',
  checkedAt: new Date().toISOString(),
  providerName: 'Local Compatible',
  baseUrl: 'http://localhost:1234/v1',
  model: 'demo-model',
  capabilityEvidence: [
    { name: 'streaming', declared: true, observed: true, state: 'verified' },
  ],
  streamingReady: true,
  streamProbeStatus: 'verified',
};

function createStreamTestContext({ fetchSSE, getJson }) {
  const patches = [];
  const synced = [];
  const postCalls = [];
  const sseRequests = [];
  const getRequests = [];
  const hostState = {
    sessionId: 'session-stream-1',
    workspace: { workspaceFolder: '/tmp/trainer-workspace-a' },
    sidecar: {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
    bootstrap: {
      plan: { id: 'plan-1', frozen: false, stages: [], title: 'Plan', cadence: '', summary: '' },
      conversation: [],
      sessionHistory: [],
      memory: { weakSpots: [], recentWins: [], reviewSummary: '' },
      profile: { focusAreas: [] },
      providerConfig: {
        lastTestResult: VERIFIED_STREAMING_TEST_RESULT,
      },
      evaluation: { checks: [] },
    },
    streamingState: {
      isStreaming: false,
      streamedContent: '',
      streamError: undefined,
      streamMessageId: undefined,
      agentActivity: [],
      agentStep: undefined,
      liveStageKind: undefined,
    },
  };

  return {
    outputChannel: { appendLine() {} },
    extensionContext: {
      globalState: { async update() {} },
      workspaceState: { async update() {} },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    trainerWorkspace: {
      getRoot() {
        return '/tmp/trainer-root';
      },
    },
    sidecarClient: {
      async getJson(port, requestPath) {
        getRequests.push(requestPath);
        if (getJson) {
          return getJson(port, requestPath);
        }
        throw new Error(`Unexpected GET ${requestPath}`);
      },
      async postJson(port, requestPath, body) {
        postCalls.push(['sidecar', requestPath, body]);
        return {
          plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          plan_runtime_status: {},
        };
      },
      async *fetchSSE(port, requestPath, body, options) {
        sseRequests.push({ port, requestPath, body, options });
        yield* fetchSSE(port, requestPath, body, options);
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
        return VERIFIED_STREAMING_TEST_RESULT;
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
      async saveModelCache() {},
      async saveLastTestResult() {},
      async clearLastTestResult() {},
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
      async refreshSnapshot() {},
      getLastActiveEditor() {
        return undefined;
      },
    },
    workbench: {
      async show() {},
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
    },
    getStreamingState() {
      return hostState.streamingState;
    },
    async setStreamingState(streamingState) {
      hostState.streamingState = streamingState;
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    __patches: patches,
    __synced: synced,
    __postCalls: postCalls,
    __sseRequests: sseRequests,
    __getRequests: getRequests,
  };
}

test('sendStreamMessageCommand settles authoritative snapshot directly from SSE complete without redundant GET /snapshot round-trip', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createStreamTestContext({
    async *fetchSSE() {
      yield {
        event: 'chunk',
        data: JSON.stringify({ delta: 'Direct authoritative reply.' }),
      };
      yield {
        event: 'complete',
        data: JSON.stringify({
          tokens: 5,
          response: {
            session_id: 'session-stream-1',
            snapshot_revision: 12,
            snapshot: {
              session_id: 'session-stream-1',
              snapshot_revision: 12,
              messages: [
                { role: 'user', content: 'Explain closures.', metadata: {} },
                { role: 'assistant', content: 'Direct authoritative reply.', metadata: {} },
              ],
              memory: { weak_spots: [], recent_wins: [], review_summary: '' },
              plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
              resources: [],
              session_history: [],
            },
            reply: {
              role: 'assistant',
              content: 'Direct authoritative reply.',
              metadata: {},
            },
            agent: {
              agentic: false,
              stop_reason: 'completed',
              tool_events: [],
            },
          },
        }),
      };
    },
  });

  const result = await sendStreamMessageCommand(context, {
    text: 'Explain closures.',
    intent: 'coach',
    stream: true,
    responseLanguage: 'en-US',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(context.__sseRequests.length, 1);
  assert.equal(context.__sseRequests[0].requestPath, '/session/message/stream');
  assert.equal(context.__sseRequests[0].body.fields, 'full');
  assert.deepEqual(
    context.__getRequests.filter((reqPath) => reqPath.startsWith('/snapshot')),
    [],
    'SSE complete carrying snapshot must not trigger a post-stream GET /snapshot round-trip',
  );
  assert.ok(context.__patches.length >= 1);
});

test('sendStreamMessageCommand retains GET /snapshot?fields=full fallback when SSE complete omits inline snapshot', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createStreamTestContext({
    async getJson(_port, requestPath) {
      if (requestPath.startsWith('/snapshot?')) {
        return {
          session_id: 'session-stream-1',
          snapshot_revision: 19,
          messages: [
            { role: 'user', content: 'Fallback check', metadata: {} },
            { role: 'assistant', content: 'Slim complete fallback reply.', metadata: {} },
          ],
          memory: { weak_spots: [], recent_wins: [], review_summary: '' },
          plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          resources: [],
          session_history: [],
        };
      }
      throw new Error(`Unexpected GET ${requestPath}`);
    },
    async *fetchSSE() {
      yield {
        event: 'complete',
        data: JSON.stringify({
          tokens: 4,
          response: {
            session_id: 'session-stream-1',
            snapshot_revision: 19,
            reply: {
              role: 'assistant',
              content: 'Slim complete fallback reply.',
              metadata: {},
            },
          },
        }),
      };
    },
  });

  const result = await sendStreamMessageCommand(context, {
    text: 'Fallback check',
    intent: 'coach',
    stream: true,
    responseLanguage: 'en-US',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(
    context.__getRequests.some((reqPath) => reqPath.includes('/snapshot?') && reqPath.includes('fields=full')),
    true,
  );
});

test('deriveTrainerStreamingOperationMessage stays silent on nominal completions and surfaces genuine anomalies', () => {
  const {
    isNominalTrainerStopReason,
    deriveTrainerStreamingOperationMessage,
  } = require(protocolModulePath);

  for (const nominal of [undefined, '', 'completed', 'stop', 'coach_finalize']) {
    assert.equal(isNominalTrainerStopReason(nominal), true);
    assert.equal(
      deriveTrainerStreamingOperationMessage(
        'zh-CN',
        {
          isStreaming: false,
          completionStopReason: nominal,
          completionSummary: 'Closed the reasoning loop.',
          completionNextStep: 'Write the unit test.',
          toolCount: 2,
          agentic: true,
        },
        { completionTokens: 512 },
      ),
      undefined,
      `Nominal stopReason=${String(nominal)} must not emit duplicate top banner noise`,
    );
  }

  const maxStepsZh = deriveTrainerStreamingOperationMessage('zh-CN', {
    isStreaming: false,
    completionStopReason: 'max_steps',
    completionSummary: '已完成前两步分析。',
    completionNextStep: '继续验证边界输入。',
  });
  assert.equal(maxStepsZh?.tone, 'info');
  assert.match(maxStepsZh?.message ?? '', /步数上限/);

  const emptyFailureEn = deriveTrainerStreamingOperationMessage('en-US', {
    isStreaming: false,
    completionStopReason: 'empty_response',
    reliabilityOutcome: 'failure',
    reliabilityPhase: 'failed',
  });
  assert.equal(emptyFailureEn?.tone, 'error');
  assert.match(emptyFailureEn?.message ?? '', /empty response/i);

  const cancelledZh = deriveTrainerStreamingOperationMessage('zh-CN', {
    isStreaming: false,
    completionStopReason: 'cancelled',
  });
  assert.deepEqual(cancelledZh, {
    tone: 'info',
    message: '已取消本轮回复，已保留已生成内容。',
  });
});

test('rememberSurfaceScroll persists scroll offsets without mutating Zustand layout or notifying subscribers', () => {
  const persistedStates = [];
  const previousWindow = globalThis.window;
  globalThis.window = {
    acquireVsCodeApi() {
      return {
        postMessage() {},
        getState() {
          return persistedStates.at(-1);
        },
        setState(next) {
          persistedStates.push(next);
        },
      };
    },
    location: { search: '', hash: '', origin: 'http://localhost' },
    localStorage: {
      getItem() {
        return null;
      },
      setItem() {},
    },
    matchMedia() {
      return {
        matches: false,
        addEventListener() {},
        removeEventListener() {},
      };
    },
    setTimeout,
    clearTimeout,
  };

  try {
    const {
      useWorkbenchState,
      getPersistedSurfaceScrollPositions,
    } = loadWebviewModule('app/useWorkbenchState.ts');

    const layoutBefore = useWorkbenchState.getState().layout;
    let subscriberNotifications = 0;
    const unsubscribe = useWorkbenchState.subscribe(() => {
      subscriberNotifications += 1;
    });

    useWorkbenchState.getState().rememberSurfaceScroll('coach:session-alpha', 384);
    assert.equal(subscriberNotifications, 0, 'rememberSurfaceScroll must not trigger React store subscribers');
    assert.equal(
      useWorkbenchState.getState().layout,
      layoutBefore,
      'rememberSurfaceScroll must preserve layout object identity',
    );
    assert.equal(getPersistedSurfaceScrollPositions()['coach:session-alpha'], 384);
    assert.equal(
      persistedStates.at(-1)?.surfaceScrollPositions?.['coach:session-alpha'],
      384,
    );

    unsubscribe();

    useWorkbenchState.getState().setActiveView('resources');
    assert.equal(
      persistedStates.at(-1)?.surfaceScrollPositions?.['coach:session-alpha'],
      384,
      'Subsequent layout persistence must retain persisted surface scroll positions',
    );
  } finally {
    if (previousWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = previousWindow;
    }
  }
});

test('App.tsx delegates composer provider and library resource domains to dedicated controllers', () => {
  const appSource = fs.readFileSync(
    path.join(webviewSrcRoot, 'app', 'App.tsx'),
    'utf8',
  );
  const lineCount = appSource.split('\n').length;
  assert.ok(appSource.includes('useComposerProviderController('));
  assert.ok(appSource.includes('useLibraryResourceController('));
  assert.equal(appSource.includes('resourceOperationResolversRef'), false);
  assert.equal(appSource.includes('resourceTrainingHandoffResolversRef'), false);
  assert.ok(
    lineCount < 11200,
    `Expected App.tsx line count to shrink below 11,200 after controller extraction, got ${lineCount}`,
  );
});
