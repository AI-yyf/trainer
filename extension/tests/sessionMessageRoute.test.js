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

function createContext() {
  const postCalls = [];
  const patches = [];
  const streamCalls = [];
  const hostMessages = [];
  const hostState = {
    sessionId: 'session-route-test',
    workspace: {
      workspaceFolder: 'F:\\trainer-a',
    },
    bootstrap: {
      plan: { id: 'plan-1', frozen: false, stages: [], title: 'Plan', cadence: '', summary: '' },
      conversation: [],
      sessionHistory: [],
      memory: { weakSpots: [], recentWins: [], reviewSummary: '', reviewRhythm: '', dueReviews: [], teachingObservations: [], memoryEvidence: [] },
      profile: { focusAreas: [], goals: [], learnerName: 'Mimo', weeklyHours: 4, preferredStyle: 'guided', answerPolicy: 'coach-first' },
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
          responseLanguage: 'en-US',
          capabilityEvidence: [
            { name: 'streaming', declared: true, observed: true, state: 'verified' },
          ],
          streamingReady: true,
          streamProbeStatus: 'verified',
        },
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
      completionSummary: undefined,
      completionNextStep: undefined,
      completionStopReason: undefined,
      toolCount: undefined,
      agentic: undefined,
    },
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
    sidecarClient: {
      async postJson(port, requestPath, body, options) {
        postCalls.push([port, requestPath, body, options]);
        return {
          session_id: 'session-route-test',
          reply: {
            id: 'assistant-route',
            role: 'assistant',
            content: 'Keep the slice small.',
            metadata: {},
          },
          snapshot: {
            messages: [],
            memory: {},
            plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
          },
          suggested_actions: [],
        };
      },
      async *fetchSSE(port, requestPath, body, options) {
        streamCalls.push([port, requestPath, body, options]);
        yield {
          event: 'complete',
          data: JSON.stringify({
            tokens: 2,
            response: {
              session_id: 'session-route-test',
              reply: {
                id: 'assistant-stream-route',
                role: 'assistant',
                content: 'Keep the next step focused.',
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
    },
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
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    workbench: {
      async postMessage(message) {
        hostMessages.push(message);
        return undefined;
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
    __postCalls: postCalls,
    __patches: patches,
    __streamCalls: streamCalls,
    __hostMessages: hostMessages,
  };
}

function createEditorMock({ documentText, selectedText, selectionLine = 0 }) {
  const lines = documentText.split('\n');
  const selection = selectedText
    ? {
        isEmpty: false,
        start: { line: selectionLine, character: 0 },
        end: { line: selectionLine, character: selectedText.length },
      }
    : {
        isEmpty: true,
        start: { line: selectionLine, character: 0 },
        end: { line: selectionLine, character: 0 },
      };
  return {
    document: {
      uri: { fsPath: 'F:\\trainer-a\\src\\example.ts' },
      languageId: 'typescript',
      lineCount: lines.length,
      getText(range) {
        return range ? selectedText : documentText;
      },
      lineAt(index) {
        return { text: lines[index] ?? '' };
      },
    },
    selection,
  };
}

test('sendMessageCommand routes default coach turns through /session/message', async () => {
  const vscodeMock = {
    window: {
      activeTextEditor: undefined,
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await sendMessageCommand(context, {
    text: 'Help me continue this coach turn.',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(context.__postCalls[0][1], '/session/message');
  assert.equal(context.__postCalls[0][2].intent, 'coach');
  assert.deepEqual(context.__postCalls[0][3], { timeoutMs: 90_000 });
});

test('sendMessageCommand leaves the active file out of an ordinary Coach question', async () => {
  const vscodeMock = {
    window: {
      activeTextEditor: createEditorMock({ documentText: 'const unrelated = true;' }),
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await sendMessageCommand(context, {
    text: 'Explain the difference between a closure and a callback.',
    intent: 'coach',
  });

  assert.equal(result.ok, true);
  assert.equal(context.__postCalls[0][2].current_file, undefined);
});

test('sendMessageCommand keeps full file context for reviews', async () => {
  const documentText = 'const ready = true;';
  const vscodeMock = {
    window: {
      activeTextEditor: createEditorMock({ documentText }),
    },
    languages: {
      getDiagnostics() {
        return [];
      },
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await sendMessageCommand(context, {
    text: 'Review this change.',
    intent: 'review',
  });

  assert.equal(result.ok, true);
  assert.equal(context.__postCalls[0][2].current_file.content, documentText);
});

test('sendMessageCommand sends only the selection window when file context is off', async () => {
  const lines = Array.from({ length: 180 }, (_, index) => `const line${index + 1} = ${index + 1};`);
  const selectedLine = 90;
  const selectedText = 'const selected = useValue();';
  lines[selectedLine] = selectedText;
  const documentText = lines.join('\n');
  const vscodeMock = {
    window: {
      activeTextEditor: createEditorMock({
        documentText,
        selectedText,
        selectionLine: selectedLine,
      }),
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await sendMessageCommand(context, {
    text: 'What does this selected code do?',
    intent: 'coach',
    includeCurrentFile: false,
    includeSelection: true,
  });

  assert.equal(result.ok, true);
  const currentFile = context.__postCalls[0][2].current_file;
  assert.equal(currentFile.selection_text, selectedText);
  assert.equal(currentFile.content.includes('const line1 = 1;'), false);
  assert.ok(currentFile.content.length < documentText.length);
  assert.equal(currentFile.diagnostics, undefined);
  assert.equal(currentFile.related_files, undefined);
});

test('sendMessageCommand keeps non-coach intents on /turn', async () => {
  const vscodeMock = {
    window: {
      activeTextEditor: undefined,
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await sendMessageCommand(context, {
    text: 'Review this change.',
    intent: 'review',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(context.__postCalls[0][1], '/turn');
  assert.equal(context.__postCalls[0][2].intent, 'review');
  assert.deepEqual(context.__postCalls[0][3], { timeoutMs: 90_000 });
});

test('sendMessageCommand routes plan-view coach turns through /turn and carries active_view', async () => {
  const vscodeMock = {
    window: {
      activeTextEditor: undefined,
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await sendMessageCommand(context, {
    text: 'Shrink the current stage into one smaller next step.',
    intent: 'coach',
    activeView: 'plan',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(context.__postCalls[0][1], '/turn');
  assert.equal(context.__postCalls[0][2].intent, 'coach');
  assert.equal(context.__postCalls[0][2].active_view, 'plan');
  assert.deepEqual(context.__postCalls[0][3], { timeoutMs: 90_000 });
});

test('sendMessageCommand forwards Resources composer intent without changing chat or plan semantics', async () => {
  const vscodeMock = {
    window: {
      activeTextEditor: undefined,
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();
  const text = 'Group these notes by topic and keep the source trail clear.';

  const result = await sendMessageCommand(context, {
    text,
    intent: 'coach',
    activeView: 'resources',
    resourceComposerIntent: {
      mode: 'organize',
      resourceIds: ['resource-1', 'resource-2', 'resource-1', '../not-a-resource-id'],
    },
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  const [, requestPath, body] = context.__postCalls[0];
  assert.equal(requestPath, '/turn');
  assert.equal(body.intent, 'coach');
  assert.equal(body.active_view, 'resources');
  assert.equal(body.message, text);
  assert.equal(body.formal_plan_mutation, false);
  assert.deepEqual(body.resource_composer_intent, {
    mode: 'organize',
    resource_ids: ['resource-1', 'resource-2'],
  });
});

test('sendStreamMessageCommand routes default Coach turns through /session/message/stream', async () => {
  const vscodeMock = {
    window: {
      activeTextEditor: undefined,
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await sendStreamMessageCommand(context, {
    text: 'Help me choose the next focused step.',
    stream: true,
    resourceIds: ['resource-coach'],
    resourceComposerIntent: {
      mode: 'locate',
      resourceIds: ['resource-coach'],
    },
    responseLanguage: 'en-US',
    answerMode: 'coach-first',
    includeCurrentFile: false,
    useAgentLoop: true,
  });

  assert.equal(result.ok, true);
  assert.equal(context.__streamCalls.length, 1);
  const [, requestPath, body, options] = context.__streamCalls[0];
  assert.equal(requestPath, '/session/message/stream');
  assert.equal(body.session_id, 'session-route-test');
  assert.equal(body.intent, 'coach');
  assert.equal(body.active_view, undefined);
  assert.equal(body.message, 'Help me choose the next focused step.');
  assert.deepEqual(body.resource_ids, ['resource-coach']);
  assert.deepEqual(body.resource_composer_intent, {
    mode: 'locate',
    resource_ids: ['resource-coach'],
  });
  assert.equal(body.response_language, 'en-US');
  assert.equal(body.answer_mode, 'guided');
  assert.equal(body.use_agent_loop, true);
  assert.equal(body.stream, true);
  assert.match(body.stream_id, /^msg_/);
  assert.equal(options.timeoutMs, 90_000);
  assert.ok(options.signal instanceof AbortSignal);
  assert.equal(options.signal.aborted, false);
});

test('sendStreamMessageCommand locally fail-closes unverified streaming with a visible timeline', async () => {
  const vscodeMock = {
    window: {
      activeTextEditor: undefined,
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();
  context.getHostState().bootstrap.providerConfig.lastTestResult = {
    ...context.getHostState().bootstrap.providerConfig.lastTestResult,
    capabilityEvidence: [
      {
        name: 'streaming',
        declared: true,
        observed: null,
        state: 'unverified',
      },
    ],
    streamingReady: false,
    streamProbeStatus: 'unverified',
  };

  const result = await sendStreamMessageCommand(context, {
    text: 'Do not start until streaming is verified.',
    stream: true,
    includeCurrentFile: false,
  });

  assert.equal(result.ok, false);
  assert.match(result.message, /has not verified real incremental output/i);
  assert.equal(context.__streamCalls.length, 0);
  const types = context.__hostMessages.map((message) => message.type);
  assert.equal(types.includes('stream/start'), true);
  assert.equal(types.includes('stream/error'), true);
  assert.ok(types.indexOf('stream/start') < types.indexOf('stream/error'));
  const phases = context.__hostMessages
    .filter((message) => message.type === 'operation/status')
    .map((message) => message.payload?.phase);
  assert.deepEqual(
    ['pending', 'executing', 'failed', 'acked'].every((phase) => phases.includes(phase)),
    true,
  );
  assert.ok(phases.indexOf('pending') < phases.indexOf('executing'));
  assert.ok(phases.indexOf('executing') < phases.indexOf('failed'));
  assert.ok(phases.indexOf('failed') < phases.indexOf('acked'));
  assert.equal(context.getStreamingState().isStreaming, false);
  assert.equal(context.getStreamingState().reliabilityPhase, 'acked');
  assert.equal(context.getStreamingState().reliabilityOutcome, 'failure');
});

test('sendStreamMessageCommand sends never-tested providers to the sidecar instead of a silent local gate', async () => {
  const vscodeMock = {
    window: {
      activeTextEditor: undefined,
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();
  context.getHostState().bootstrap.providerConfig.lastTestResult = undefined;

  const result = await sendStreamMessageCommand(context, {
    text: 'Keep coaching this recovered step.',
    stream: true,
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(context.__streamCalls.length, 1);
  assert.equal(context.__hostMessages.some((message) => message.type === 'stream/start'), true);
  assert.equal(context.getStreamingState().isStreaming, false);
});

test('sendStreamMessageCommand routes structured Plan, Resources, and Training turns through /turn/stream', async () => {
  const vscodeMock = {
    window: {
      activeTextEditor: undefined,
    },
  };
  const { sendStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const structuredTurns = [
    { intent: 'plan', activeView: 'plan', text: 'Break the stage into a verifiable next task.' },
    { intent: 'review', activeView: 'resources', text: 'Find the resource evidence I should review.' },
    { intent: 'next_task', activeView: 'training', text: 'Give me the next practice card.' },
  ];

  for (const turn of structuredTurns) {
    const context = createContext();
    const result = await sendStreamMessageCommand(context, {
      ...turn,
      stream: true,
      includeCurrentFile: false,
    });

    assert.equal(result.ok, true, `${turn.activeView} stream should complete`);
    assert.equal(context.__streamCalls.length, 1);
    const [, requestPath, body, options] = context.__streamCalls[0];
    assert.equal(requestPath, '/turn/stream');
    assert.equal(body.intent, turn.intent);
    assert.equal(body.active_view, turn.activeView);
    assert.equal(body.message, turn.text);
    assert.equal(options.timeoutMs, 90_000);
    assert.ok(options.signal instanceof AbortSignal);
    assert.equal(options.signal.aborted, false);
  }
});

test('cancelStreamMessageCommand aborts the active stream without reporting a provider failure', async () => {
  const vscodeMock = {
    window: {
      activeTextEditor: undefined,
    },
  };
  const { sendStreamMessageCommand, cancelStreamMessageCommand } = loadWithVscodeMock(
    sessionCommandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  context.sidecarClient.fetchSSE = async function* (_port, _path, _body, options) {
    context.__streamCalls.push([_port, _path, _body, options]);
    await new Promise((resolve) => options.signal.addEventListener('abort', resolve, { once: true }));
    throw new Error('request aborted by test');
  };

  const running = sendStreamMessageCommand(context, {
    text: 'Stop this deliberately slow reply.',
    stream: true,
    responseLanguage: 'en-US',
  });
  while (context.__streamCalls.length === 0) {
    await new Promise((resolve) => setImmediate(resolve));
  }

  const [streamOptions] = [context.__streamCalls[0][3]];
  const cancelResult = await cancelStreamMessageCommand(context, {
    messageId: context.getStreamingState().streamMessageId,
  });
  const result = await running;

  assert.equal(cancelResult.ok, true);
  assert.equal(result.ok, true);
  assert.equal(streamOptions.signal.aborted, true);
  assert.equal(context.__postCalls.at(-1)[1], '/stream/cancel');
  assert.equal(context.__postCalls.at(-1)[2].stream_id, context.getStreamingState().streamMessageId);
  assert.equal(context.getStreamingState().isStreaming, false);
  assert.equal(context.getStreamingState().completionStopReason, 'cancelled');
  assert.equal(context.getStreamingState().streamError, undefined);
  assert.equal(context.getStreamingState().reliabilityPhase, 'acked');
  assert.equal(context.getStreamingState().reliabilityOutcome, 'failure');
  const phases = context.__hostMessages
    .filter((message) => message.type === 'operation/status')
    .map((message) => message.payload?.phase);
  assert.ok(phases.includes('failed'), 'abort timeline must surface failed');
  assert.ok(phases.includes('acked'), 'abort timeline must surface acked');
  assert.ok(phases.indexOf('failed') < phases.indexOf('acked'));
  assert.equal(context.__hostMessages.at(-1).type, 'stream/cancelled');
  assert.equal(
    context.__hostMessages.some((message) => message.type === 'stream/error'),
    false,
    'host abort must not report a provider stream/error',
  );
});

test('invalidateActiveTrainerStreams drops buffered Coach SSE events after a workspace switch', async () => {
  const vscodeMock = {
    window: {
      activeTextEditor: undefined,
    },
  };
  const {
    sendStreamMessageCommand,
    invalidateActiveTrainerStreams,
  } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();
  let release;
  let streamStarted;
  const streamStartedPromise = new Promise((resolve) => {
    streamStarted = resolve;
  });
  const streamGate = new Promise((resolve) => {
    release = resolve;
  });
  context.sidecarClient.fetchSSE = async function* (_port, _path, _body, options) {
    context.__streamCalls.push([_port, _path, _body, options]);
    streamStarted();
    await streamGate;
    yield {
      event: 'chunk',
      data: JSON.stringify({ chunk: 'old workspace chunk' }),
    };
    yield {
      event: 'complete',
      data: JSON.stringify({
        response: {
          session_id: 'old-session',
          reply: {
            role: 'assistant',
            content: 'old workspace completion',
          },
          snapshot: {
            messages: [],
            memory: {},
            plan: { id: 'plan-1', frozen: false, stages: [] },
          },
        },
      }),
    };
  };

  const running = sendStreamMessageCommand(context, {
    text: 'Keep this stream pending.',
    stream: true,
    includeCurrentFile: false,
  });
  await streamStartedPromise;
  await invalidateActiveTrainerStreams(context);
  release();
  const result = await running;

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /invalidated/i);
  assert.equal(
    context.__hostMessages.some((message) =>
      ['stream/chunk', 'stream/complete', 'stream/error'].includes(message.type),
    ),
    false,
  );
  assert.equal(context.__patches.length, 0);
  assert.equal(context.getStreamingState().isStreaming, true);
});

test('sendMessageCommand discards a response that resolves after the workspace changes', async () => {
  const vscodeMock = {
    window: {
      activeTextEditor: undefined,
    },
  };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();
  let release;
  const responseGate = new Promise((resolve) => {
    release = resolve;
  });
  const originalPostJson = context.sidecarClient.postJson;
  context.sidecarClient.postJson = async (...args) => {
    if (args[1] === '/session/message') {
      await responseGate;
    }
    return originalPostJson(...args);
  };

  const running = sendMessageCommand(context, {
    text: 'This response belongs to the old workspace.',
    includeCurrentFile: false,
  });
  await new Promise((resolve) => setImmediate(resolve));
  context.getHostState().workspace.workspaceFolder = 'F:\\trainer-b';
  release();
  const result = await running;

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /discarded after the workspace changed/i);
  assert.equal(context.__patches.length, 0);
  assert.equal(context.getHostState().sessionId, 'session-route-test');
});

test('sendMessageCommand forwards a caller-owned request id for idempotent replay', async () => {
  const vscodeMock = { window: { activeTextEditor: undefined } };
  const { sendMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await sendMessageCommand(context, {
    text: 'Retry this exact Coach turn safely.',
    requestId: 'coach-replay-123',
    includeCurrentFile: false,
  });

  assert.equal(result.ok, true);
  assert.equal(context.__postCalls[0][2].request_id, 'coach-replay-123');
});
