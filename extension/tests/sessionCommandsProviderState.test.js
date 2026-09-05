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
    ...overrides,
  };
}

function createContext(overrides = {}) {
  const patches = [];
  const savedResults = [];
  const postCalls = [];
  const sessionIds = [];
  const hostState = {
    sessionId: overrides.initialSessionId ?? 'session-provider-state',
    workspace: {
      workspaceFolder: 'F:\\trainer-a',
    },
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
        configured: true,
        name: 'Local Compatible',
        baseUrl: 'http://localhost:1234/v1',
        model: 'demo-model',
        protocol: 'openai_chat_completions_compatible',
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
          protocol: 'openai_chat_completions_compatible',
          responseLanguage: 'zh-CN',
          capabilityEvidence: [
            { name: 'streaming', declared: true, observed: true, state: 'verified' },
          ],
          streamingReady: true,
          streamProbeStatus: 'verified',
        },
      },
      evaluation: { checks: [] },
    },
    streamingState: createStreamingState(),
  };

  return {
    trainerWorkspace: {
      getRoot() {
        return 'F:\\trainer\\trainer-workspace';
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: overrides.sidecarClient,
    providerStore: {
      getConfig() {
        return {
          name: 'Local Compatible',
          baseUrl: 'http://localhost:1234/v1',
          model: 'demo-model',
          protocol: 'openai_chat_completions_compatible',
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
      isModelCacheCompatible() {
        return false;
      },
      async saveModelCache() {
        return undefined;
      },
      async saveLastTestResult(_providerConfig, result) {
        savedResults.push(result);
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    workbench: {
      async postMessage(message) {
        postCalls.push(message);
      },
      async syncState() {
        return undefined;
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
    async setStreamingState(state) {
      hostState.streamingState = state;
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    __patches: patches,
    __savedResults: savedResults,
    __postCalls: postCalls,
    __sessionIds: sessionIds,
  };
}

test('sendMessageCommand degrades provider state when a successful response reports language_corruption', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({
    sidecarClient: {
      async postJson(port, requestPath) {
        assert.equal(port, 34891);
        assert.equal(requestPath, '/session/message');
        return {
          session_id: 'session-provider-state-direct',
          reply: {
            role: 'assistant',
            content: 'Trainer blocked this turn because the provider corrupted the input.',
            metadata: {},
          },
          agent_meta: {
            stop_reason: 'language_corruption',
            summary:
              'Provider reachable, but it corrupted Chinese input into question marks before the model saw it.',
            next_step: 'Switch provider or gateway before resuming the coach thread.',
          },
          snapshot: {
            messages: [],
            memory: {},
            plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          },
        };
      },
    },
  });
  const result = await sendMessageCommand(context, {
    text: '继续这一轮训练',
    intent: 'coach',
    responseLanguage: 'zh-CN',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(context.__sessionIds.at(-1), 'session-provider-state-direct');
  assert.equal(context.__savedResults.at(-1)?.status, 'language_corruption');
  assert.equal(context.__savedResults.at(-1)?.errorCategory, 'language_corruption');
  const errorPatch = context.__patches.find(
    (patch) => patch?.providerConfig?.modelErrorCategory === 'language_corruption',
  );
  assert.ok(errorPatch);
  assert.equal(errorPatch.providerConfig.modelListStatus, 'error');
});

test('sendMessageCommand keeps going when zh-CN integrity is not fully verified yet', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({
    sidecarClient: {
      async postJson(port, requestPath) {
        assert.equal(port, 34891);
        if (requestPath === '/provider/test') {
          return {
            ok: false,
            configured: true,
            api_key_supplied: true,
            reachable: true,
            success: false,
            status: 'language_probe_inconclusive',
            provider_name: 'Local Compatible',
            detail:
              'Language integrity probe was inconclusive. The provider replied, but it did not preserve the mixed CJK/ASCII probe text exactly enough for Trainer to trust it.',
            diagnostics: ['Language integrity probe was inconclusive.'],
            error_category: 'language_probe_inconclusive',
            retryable: false,
            status_code: 200,
          };
        }
        assert.equal(requestPath, '/session/message');
        return {
          session_id: 'session-provider-state-inconclusive',
          reply: {
            role: 'assistant',
            content: '先确认远程工作区边界，再做一个最小验证动作。',
            metadata: {},
          },
          snapshot: {
            messages: [],
            memory: {},
            plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          },
        };
      },
    },
  });
  context.getHostState().bootstrap.providerConfig.lastTestResult = undefined;

  const result = await sendMessageCommand(context, {
    text: '先教我 VS Code remote workspace boundary，再给我一个很小的验证动作。',
    intent: 'coach',
    responseLanguage: 'zh-CN',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(context.__sessionIds.at(-1), 'session-provider-state-inconclusive');
  assert.equal(context.__savedResults.at(-1)?.status, 'language_probe_inconclusive');
  assert.equal(context.__savedResults.at(-1)?.errorCategory, 'language_probe_inconclusive');
});

test('sendMessageCommand blocks a fresh connectivity failure before it reaches the sidecar', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  let sidecarCalls = 0;
  let sidecarStarts = 0;
  const context = createContext({
    sidecarClient: {
      async postJson() {
        sidecarCalls += 1;
        throw new Error('The blocked send must not reach the sidecar.');
      },
    },
  });
  context.sidecarManager = {
    async ensureRunning() {
      sidecarStarts += 1;
      throw new Error('The blocked send must not start the sidecar.');
    },
  };
  context.getHostState().bootstrap.providerConfig.lastTestResult = {
    ok: false,
    status: 'network_error',
    errorCategory: 'network_error',
    detail: 'Connection reset by peer.',
    retryable: true,
    checkedAt: new Date().toISOString(),
    providerName: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    protocol: 'openai_chat_completions_compatible',
  };

  const result = await sendMessageCommand(context, {
    text: 'Finish the smallest trusted check first.',
    intent: 'coach',
    responseLanguage: 'en-US',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /cannot reach the model/i);
  assert.equal(sidecarCalls, 0);
  assert.equal(sidecarStarts, 0);
  assert.equal(context.__sessionIds.length, 0);
});

test('sendStreamMessageCommand degrades provider state when stream completion reports empty_response', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext({
    initialSessionId: 'session-provider-state-stream-before',
    sidecarClient: {
      async *fetchSSE(port, requestPath) {
        assert.equal(port, 34891);
        assert.equal(requestPath, '/session/message/stream');
        yield {
          event: 'complete',
          data: JSON.stringify({
            tokens: 1,
            response: {
              session_id: 'session-provider-state-stream-after',
              reply: {
                role: 'assistant',
                content: 'No final coaching reply was produced.',
                metadata: {},
              },
              agent: {
                agentic: true,
                summary:
                  'Provider replied with reasoning-only content and no final coaching reply content.',
                next_step: 'Retry only after the provider can produce visible final content.',
                stop_reason: 'empty_response',
                tool_events: [],
              },
              snapshot: {
                messages: [],
                memory: {},
                plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
              },
            },
          }),
        };
      },
    },
  });

  const result = await sendStreamMessageCommand(context, {
    text: '继续这一轮训练',
    intent: 'coach',
    stream: true,
    responseLanguage: 'zh-CN',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(context.__sessionIds.at(-1), 'session-provider-state-stream-after');
  assert.equal(context.__savedResults.at(-1)?.status, 'empty_response');
  assert.equal(context.__savedResults.at(-1)?.errorCategory, 'empty_response');
  const errorPatch = context.__patches.find(
    (patch) => patch?.providerConfig?.modelErrorCategory === 'empty_response',
  );
  assert.ok(errorPatch);
  assert.equal(errorPatch.providerConfig.modelListStatus, 'error');
});

test('sendStreamMessageCommand blocks a fresh connectivity failure before starting a stream', async () => {
  const vscodeMock = {
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  let sidecarCalls = 0;
  let streamCalls = 0;
  let sidecarStarts = 0;
  const context = createContext({
    initialSessionId: 'session-provider-state-stream-blocked',
    sidecarClient: {
      async postJson() {
        sidecarCalls += 1;
        throw new Error('The blocked stream must not probe the sidecar.');
      },
      async *fetchSSE() {
        streamCalls += 1;
        throw new Error('The blocked stream must not begin SSE.');
      },
    },
  });
  context.sidecarManager = {
    async ensureRunning() {
      sidecarStarts += 1;
      throw new Error('The blocked stream must not start the sidecar.');
    },
  };
  context.getHostState().bootstrap.providerConfig.lastTestResult = {
    ok: false,
    status: 'timeout',
    errorCategory: 'timeout',
    detail: 'The service took too long to reply.',
    retryable: true,
    checkedAt: new Date().toISOString(),
    providerName: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    protocol: 'openai_chat_completions_compatible',
  };

  const result = await sendStreamMessageCommand(context, {
    text: 'Keep the reply short and trustworthy.',
    intent: 'coach',
    stream: true,
    responseLanguage: 'en-US',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /took too long to reply/i);
  assert.equal(sidecarCalls, 0);
  assert.equal(streamCalls, 0);
  assert.equal(sidecarStarts, 0);
  assert.equal(context.getStreamingState().isStreaming, false);
  assert.equal(context.getStreamingState().streamMessageId, undefined);
  assert.equal(
    context.__postCalls.some((call) => call[0] === 'workbench' && call[1] === 'postMessage' && call[2]?.type === 'stream/start'),
    false,
  );
});
