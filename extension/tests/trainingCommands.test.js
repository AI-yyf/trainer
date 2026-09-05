'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const trainingCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'trainingCommands.js',
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

const { createDefaultBootstrapData } = require(workbenchDataModulePath);

function createContext(overrides = {}) {
  const synced = [];
  const postCalls = [];
  const patched = [];
  const streamMessages = [];
  let streamingState = {
    isStreaming: false,
    streamedContent: '',
    streamMessageId: undefined,
    streamError: undefined,
  };
  const hostState = {
    workspace: {
      trusted: true,
      workspaceName: 'trainer-training',
      activeFile: 'F:\\trainer-training\\server\\app\\main.py',
      recentFiles: [],
      recentEditedFiles: [],
      workspaceFolder: overrides.workspaceFolder ?? 'F:\\trainer-training',
    },
    sidecar: {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
    bootstrap:
      overrides.bootstrap ??
      createDefaultBootstrapData(
        {
          trusted: true,
          workspaceFolder: overrides.workspaceFolder ?? 'F:\\trainer-training',
          activeFile: 'F:\\trainer-training\\server\\app\\main.py',
          recentFiles: [],
          recentEditedFiles: [],
        },
        undefined,
        {
          lifecycle: 'ready',
          host: '127.0.0.1',
          port: 34891,
          canStart: true,
        },
      ),
  };

  if (overrides.responseLanguage && hostState.bootstrap.memory?.workspace) {
    hostState.bootstrap.memory.workspace.responseLanguage = overrides.responseLanguage;
  }

  return {
    providerStore: {
      getConfig() {
        return undefined;
      },
      async getApiKey() {
        return undefined;
      },
    },
    sidecarManager: {
      getStatus() {
        return {
          lifecycle: 'ready',
          port: 34891,
        };
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        postCalls.push([port, requestPath, body]);
        if (requestPath === '/training/card-status') {
          return { card: { id: body.card_id } };
        }
        if (requestPath === '/training/generate-card') {
          return {
            card: { id: 'generated-card', card_type: body.card_type },
            score: 0.88,
          };
        }
        if (requestPath === '/training/flashcard/answer') {
          return { correct: true, detail: 'Flashcard answer recorded.' };
        }
        if (requestPath === '/training/theory-drill/answer') {
          return { ok: true, correct: true, detail: 'Theory drill answer recorded.' };
        }
        if (requestPath === '/training/reflect' || requestPath === '/training/return') {
          return { ok: true, workspace: {} };
        }
        if (requestPath === '/training/review-queue/action') {
          return { ok: true, detail: 'Review queue action recorded.' };
        }
        if (requestPath === '/training/review-artifact/action') {
          return { ok: true, detail: 'Review result saved.' };
        }
        if (requestPath === '/training/scenario-lab/action') {
          return { ok: true, detail: 'Scenario lab action recorded.' };
        }
        if (requestPath === '/training/dependency-skill-map/action') {
          return { maps: [], history: [], scenario_lab: null };
        }
        if (requestPath === '/evidence/enqueue') {
          return {};
        }
        throw new Error(`Unexpected POST ${requestPath}`);
      },
      async *fetchSSE(port, requestPath, body) {
        postCalls.push([port, requestPath, body]);
        yield { event: 'chunk', data: JSON.stringify({ chunk: 'Generated ' }) };
        yield {
          event: 'complete',
          data: JSON.stringify({
            response: {
              card: { card_id: 'generated-card', card_type: body.card_type },
              score: 0.88,
              success: true,
            },
          }),
        };
      },
      async getJson(port, requestPath) {
        postCalls.push([port, requestPath]);
        return {
          memory: {
            workspace: {
              workspace_id: hostState.workspace.workspaceFolder,
              selected_card_id: 'card-rehydrated',
              selected_card_type: 'practice',
              selected_card_status: 'active',
            },
            training_card_candidates: [],
            training_event_ledger: [],
          },
        };
      },
    },
    async patchWorkbenchData(patch) {
      patched.push(patch);
    },
    outputChannel: {
      appendLine() {
        return undefined;
      },
    },
    workbench: {
      async syncState() {
        synced.push(true);
      },
      async postMessage(message) {
        streamMessages.push(message);
      },
    },
    getStreamingState() {
      return streamingState;
    },
    async setStreamingState(nextState) {
      streamingState = { ...nextState };
    },
    getHostState() {
      return hostState;
    },
    getSessionId() {
      return undefined;
    },
    ...overrides,
    __postCalls: postCalls,
    __synced: synced,
    __patched: patched,
    __streamMessages: streamMessages,
  };
}

function prepareResourceTrainingContext(context, options = {}) {
  const state = context.getHostState();
  const resource = {
    id: 'resource-42',
    title: 'HTTPX timeout guide',
    kind: 'text',
    status: 'ready',
    summary: 'A verified HTTPX timeout reference.',
    indexState: 'indexed',
    trustState: 'trusted',
    trustScore: 0.95,
    freshness: 'fresh',
    qualityFlags: [],
    ...(options.resource ?? {}),
  };
  state.bootstrap.resources = options.missing ? [] : [resource];
  if (options.managed !== false) {
    state.bootstrap.memory.workspace = {
      ...(state.bootstrap.memory.workspace ?? {}),
      trainerWorkspace: {
        status: 'managed',
        contextId: 'context-resource-training',
        canonicalProjectPath: 'f:\\trainer-training',
        rootId: 'root-resource-training',
        projectId: 'project-resource-training',
      },
    };
  }
  return resource;
}

test('trainingCardStatusTransitionCommand sends workspace_id to sidecar', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingCardStatusTransitionCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });

  const result = await trainingCardStatusTransitionCommand(context, {
    cardId: 'card-123',
    newStatus: 'completed',
    reason: 'learner finished independently',
  });

  assert.equal(result.ok, true);
  const [port, requestPath, requestBody] = context.__postCalls[0];
  assert.equal(port, 34891);
  assert.equal(requestPath, '/training/card-status');
  assert.deepEqual(requestBody, {
    workspace_id: 'F:\\trainer-training',
    card_id: 'card-123',
    new_status: 'completed',
    reason: 'learner finished independently',
    // Host always forwards TrainingReliabilityRequestFields (server defaults when unset).
    request_id: '',
    idempotency_key: '',
    revision: 0,
    timeout_ms: 30000,
    cancel: false,
  });
  assert.equal(String(context.__postCalls[1][1]).startsWith('/memory/summary?'), true);
  assert.equal(context.__patched.length, 1);
  assert.equal(context.__synced.length, 1);
});

test('trainingGenerateCardCommand sends workspace_id to sidecar', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingGenerateCardCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({
    workspaceFolder: 'F:\\trainer-training',
    responseLanguage: 'zh-CN',
  });

  const result = await trainingGenerateCardCommand(context, {
    source: 'conversation',
    cardType: 'practice',
    focusArea: 'state machine',
    targetSkill: 'status transition',
  });

  assert.equal(result.ok, true);
  const [port, requestPath, requestBody] = context.__postCalls[0];
  assert.equal(port, 34891);
  assert.equal(requestPath, '/training/generate-card/stream');
  assert.equal(requestBody.workspace_id, 'F:\\trainer-training');
  assert.equal(requestBody.source, 'conversation');
  assert.equal(requestBody.card_type, 'practice');
  assert.equal(requestBody.focus_area, 'state machine');
  assert.equal(requestBody.target_skill, 'status transition');
  assert.equal(requestBody.response_language, 'zh-CN');
  assert.equal(String(context.__postCalls[1][1]).startsWith('/memory/summary?'), true);
  assert.equal(context.__patched.length, 1);
  assert.equal(context.__synced.length, 1);
});

test('workspace invalidation prevents an old training stream from publishing into the next workspace', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingGenerateCardCommand, invalidateActiveTrainingCardStream } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training-old' });
  let releaseStream;
  let streamStarted;
  const started = new Promise((resolve) => {
    streamStarted = resolve;
  });
  const release = new Promise((resolve) => {
    releaseStream = resolve;
  });
  const defaultPostJson = context.sidecarClient.postJson;
  context.sidecarClient = {
    ...context.sidecarClient,
    async postJson(port, requestPath, body, options) {
      if (requestPath === '/stream/cancel') {
        context.__postCalls.push([port, requestPath, body, options]);
        return {};
      }
      return defaultPostJson(port, requestPath, body, options);
    },
    async *fetchSSE(port, requestPath, body) {
      context.__postCalls.push([port, requestPath, body]);
      streamStarted();
      await release;
      yield {
        event: 'complete',
        data: JSON.stringify({
          response: {
            card: { card_id: 'old-workspace-card', card_type: body.card_type },
            success: true,
          },
        }),
      };
    },
  };

  const pending = trainingGenerateCardCommand(context, {
    source: 'conversation',
    cardType: 'practice',
  });
  await started;
  assert.equal(invalidateActiveTrainingCardStream(context), true);
  releaseStream();
  const result = await pending;

  assert.equal(result.ok, true);
  assert.equal(context.__patched.length, 0);
  assert.equal(context.__synced.length, 0);
  assert.equal(
    context.__streamMessages.some((message) => message.type === 'stream/complete'),
    false,
  );
  assert.equal(
    context.__postCalls.some(([, requestPath]) => requestPath === '/stream/cancel'),
    true,
  );
});

test('trainingGenerateCardCommand defaults to conversation_gap and forwards nested IDE facts', async () => {
  const documentText = [
    'export async function fetchLesson(lessonId) {',
    '  return request(`/api/lessons/${lessonId}`);',
    '}',
  ].join('\n');
  const selection = {
    isEmpty: false,
    start: { line: 0, character: 0 },
    end: { line: 2, character: 1 },
  };
  const document = {
    uri: { fsPath: 'F:\\trainer-training\\src\\demo.ts' },
    languageId: 'typescript',
    lineCount: 3,
    getText(range) {
      return range ? documentText : documentText;
    },
    lineAt(index) {
      return { text: documentText.split('\n')[index] };
    },
  };
  const vscodeMock = {
    commands: { async executeCommand() { return undefined; } },
    DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2, Hint: 3 },
    window: { activeTextEditor: { document, selection } },
    languages: {
      getDiagnostics() {
        return [{
          severity: 0,
          range: { start: { line: 1, character: 2 } },
          message: 'Object is possibly undefined.',
        }];
      },
    },
  };
  const { trainingGenerateCardCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });

  const result = await trainingGenerateCardCommand(context, {
    cardType: 'practice',
    focusArea: 'function guidance',
    targetSkill: 'function contract',
  });

  assert.equal(result.ok, true);
  const [, requestPath, requestBody] = context.__postCalls[0];
  assert.equal(requestPath, '/training/generate-card/stream');
  assert.equal(requestBody.source, 'conversation_gap');
  assert.deepEqual(requestBody.current_file, {
    path: 'F:\\trainer-training\\src\\demo.ts',
    language_id: 'typescript',
    content: documentText,
    content_excerpt: documentText,
    content_line_span: '1-3',
    content_strategy: 'selection-window',
    selection_text: documentText,
    selection_range: '1:1-3:2',
    diagnostics: ['[error] line 2: Object is possibly undefined.'],
    recent_files: [],
    recent_edited_files: [],
    related_files: [],
  });
  assert.equal(requestBody.context_hint.includes('F:\\trainer-training'), false);
});

test('trainingGenerateCardCommand preserves every supported non-English response language', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingGenerateCardCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );

  for (const responseLanguage of ['es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    const context = createContext({
      workspaceFolder: 'F:\\trainer-training',
      responseLanguage,
    });
    const result = await trainingGenerateCardCommand(context, {
      source: 'conversation',
      cardType: 'practice',
      focusArea: 'remote workspace boundary',
      targetSkill: 'credential placement',
    });

    assert.equal(result.ok, true, responseLanguage);
    assert.equal(context.__postCalls[0][2].response_language, responseLanguage);
  }
});

test('trainingGenerateCardCommand forwards resource_id for resource_knowledge cards', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingGenerateCardCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });
  prepareResourceTrainingContext(context);

  const result = await trainingGenerateCardCommand(context, {
    source: 'resource_knowledge',
    cardType: 'practice',
    resourceId: 'resource-42',
  });

  assert.equal(result.ok, true);
  const [port, requestPath, requestBody] = context.__postCalls[0];
  assert.equal(port, 34891);
  assert.equal(requestPath, '/training/generate-card/stream');
  assert.equal(requestBody.resource_id, 'resource-42');
  assert.equal(requestBody.source, 'resource_knowledge');
});

test('trainingGenerateCardCommand accepts a trusted legacy resource without trustState', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingGenerateCardCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });
  prepareResourceTrainingContext(context, {
    resource: { trustState: undefined, trustScore: 0.95, freshness: 'fresh', qualityFlags: [] },
  });

  const result = await trainingGenerateCardCommand(context, {
    source: 'resource_knowledge',
    cardType: 'practice',
    resourceId: 'resource-42',
  });

  assert.equal(result.ok, true);
  assert.equal(context.__postCalls[0][1], '/training/generate-card/stream');
});

test('trainingGenerateCardCommand blocks resource cards that are not ready', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingGenerateCardCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const cases = [
    { name: 'unmanaged project', options: { managed: false } },
    { name: 'missing resource', options: { missing: true } },
    {
      name: 'unfinished indexing',
      options: { resource: { status: 'indexing', indexState: 'pending' } },
    },
    { name: 'stale resource', options: { resource: { freshness: 'stale' } } },
    {
      name: 'untrusted resource',
      options: { resource: { trustState: 'untrusted', trustScore: 0.2 } },
    },
    {
      name: 'quality-blocked resource',
      options: { resource: { qualityFlags: ['source_conflict'] } },
    },
  ];

  for (const { name, options } of cases) {
    const context = createContext({
      workspaceFolder: 'F:\\trainer-training',
      responseLanguage: 'zh-CN',
    });
    prepareResourceTrainingContext(context, options);

    const result = await trainingGenerateCardCommand(context, {
      source: 'resource_knowledge',
      cardType: 'practice',
      resourceId: 'resource-42',
    });

    assert.equal(result.ok, false, name);
    assert.equal(context.__postCalls.length, 0, name);
  }
});

test('trainingGenerateCardCommand keeps the generated and active card IDs distinct', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingGenerateCardCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });
  prepareResourceTrainingContext(context);
  const defaultClient = context.sidecarClient;
  context.sidecarClient = {
    ...defaultClient,
    async *fetchSSE(port, requestPath, body) {
      context.__postCalls.push([port, requestPath, body]);
      yield {
        event: 'complete',
        data: JSON.stringify({
          response: {
            card: { card_id: 'generated-card', card_type: body.card_type },
            score: 0.88,
            success: true,
            active_routing: { selected_card_id: 'different-active-card' },
          },
        }),
      };
    },
  };

  const result = await trainingGenerateCardCommand(context, {
    source: 'resource_knowledge',
    cardType: 'flash',
    resourceId: 'resource-42',
  });

  assert.equal(result.ok, true);
  assert.equal(result.data.generatedCardId, 'generated-card');
  assert.equal(result.data.selectedCardId, 'different-active-card');
});

test('claimTrainingGenerateCardCompleteBind is fail-closed idempotent by request_id', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const {
    claimTrainingGenerateCardCompleteBind,
    hasTrainingGenerateCardCompleteBind,
  } = loadWithVscodeMock(trainingCommandsModulePath, vscodeMock);
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });

  assert.equal(
    claimTrainingGenerateCardCompleteBind(context, 'training-req-shared', 'card-bound'),
    true,
  );
  assert.equal(hasTrainingGenerateCardCompleteBind(context, 'training-req-shared'), true);
  assert.equal(
    claimTrainingGenerateCardCompleteBind(context, 'training-req-shared', 'card-other'),
    false,
  );
  assert.equal(
    claimTrainingGenerateCardCompleteBind(context, 'training-req-other', 'card-bound'),
    true,
  );
});

test('two generate-card completes with same request_id bind once and do not remint leftover', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingGenerateCardCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });
  const requestId = 'training-req-owner-waiter-shared';
  const leftoverPatch = {
    workspaceTrainingState: {
      selectedCardId: undefined,
      selectedCardTitle: 'leftover-title-not-live',
    },
  };
  context.patchWorkbenchData = async (patch) => {
    context.__patched.push(patch);
    // First bind keeps leftover title chrome; a second apply must not clobber it.
    if (!context.__leftoverTitle) {
      context.__leftoverTitle = leftoverPatch.workspaceTrainingState.selectedCardTitle;
    }
  };

  const owner = await trainingGenerateCardCommand(context, {
    source: 'conversation',
    cardType: 'practice',
    requestId,
  });
  assert.equal(owner.ok, true);
  assert.equal(context.__patched.length, 1);
  assert.equal(context.__synced.length, 1);
  assert.equal(
    context.__postCalls.filter((entry) => String(entry[1]).startsWith('/memory/summary')).length,
    1,
  );
  const ownerStreamBody = context.__postCalls.find(
    (entry) => entry[1] === '/training/generate-card/stream',
  )?.[2];
  assert.equal(ownerStreamBody.request_id, requestId);

  const waiter = await trainingGenerateCardCommand(context, {
    source: 'conversation',
    cardType: 'practice',
    requestId,
  });
  assert.equal(waiter.ok, true);
  assert.equal(context.__patched.length, 1, 'waiter complete must not re-bind host state');
  assert.equal(context.__synced.length, 1, 'waiter complete must not sync a second bind');
  assert.equal(
    context.__postCalls.filter((entry) => String(entry[1]).startsWith('/memory/summary')).length,
    1,
    'waiter complete must not rehydrate and clobber leftover',
  );
  assert.equal(context.__leftoverTitle, 'leftover-title-not-live');
  assert.equal(
    context.__streamMessages.filter((message) => message.type === 'stream/complete').length,
    2,
    'waiter still gets stream/complete for UI cleanup',
  );
  const streamBodies = context.__postCalls
    .filter((entry) => entry[1] === '/training/generate-card/stream')
    .map((entry) => entry[2]);
  assert.equal(streamBodies.length, 2);
  assert.equal(streamBodies[0].request_id, requestId);
  assert.equal(streamBodies[1].request_id, requestId);
  assert.notEqual(streamBodies[0].stream_id, streamBodies[1].stream_id);
});

test('concurrent waiter complete while owner isStreaming binds once and acks via owner messageId', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingGenerateCardCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });
  const requestId = 'training-req-concurrent-owner-waiter';
  let ownerRelease;
  const ownerHold = new Promise((resolve) => {
    ownerRelease = resolve;
  });
  let ownerStarted;
  const ownerStartedGate = new Promise((resolve) => {
    ownerStarted = resolve;
  });
  let waiterSawStreaming = false;
  let fetchCount = 0;
  context.sidecarClient = {
    ...context.sidecarClient,
    async *fetchSSE(port, requestPath, body) {
      fetchCount += 1;
      context.__postCalls.push([port, requestPath, body]);
      if (fetchCount === 1) {
        ownerStarted();
        await ownerHold;
        yield {
          event: 'complete',
          data: JSON.stringify({
            response: {
              card: { card_id: 'generated-card', card_type: body.card_type },
              score: 0.9,
              success: true,
              active_routing: { selected_card_id: 'card-bound-once' },
            },
          }),
        };
        return;
      }
      // Waiter joins while owner still holds isStreaming.
      waiterSawStreaming = context.getStreamingState().isStreaming === true;
      yield {
        event: 'complete',
        data: JSON.stringify({
          response: {
            card: { card_id: 'generated-card', card_type: body.card_type },
            score: 0.9,
            success: true,
            active_routing: { selected_card_id: 'card-bound-once' },
          },
        }),
      };
    },
  };

  const ownerPending = trainingGenerateCardCommand(context, {
    source: 'conversation',
    cardType: 'practice',
    requestId,
  });
  await ownerStartedGate;
  const ownerMessageId = context.getStreamingState().streamMessageId;
  assert.equal(context.getStreamingState().isStreaming, true);
  assert.ok(ownerMessageId);

  const waiter = await trainingGenerateCardCommand(context, {
    source: 'conversation',
    cardType: 'practice',
    requestId,
  });
  assert.equal(waiter.ok, true, 'same request_id waiter must not be blocked by isStreaming');
  assert.equal(waiterSawStreaming, true);
  assert.equal(context.__patched.length, 1, 'first complete claims bind once');
  assert.equal(context.__synced.length, 1);
  assert.equal(
    context.__streamMessages.filter((message) => message.type === 'stream/complete').length,
    1,
    'waiter posts first complete with owner messageId while owner still in flight',
  );
  assert.equal(
    context.__streamMessages.find((message) => message.type === 'stream/complete')?.payload
      ?.messageId,
    ownerMessageId,
  );
  assert.equal(context.getStreamingState().isStreaming, false);

  ownerRelease();
  const owner = await ownerPending;
  assert.equal(owner.ok, true);
  assert.equal(context.__patched.length, 1, 'owner complete must not remint bind');
  assert.equal(context.__synced.length, 1);
  assert.equal(
    context.__streamMessages.filter((message) => message.type === 'stream/complete').length,
    2,
    'owner still emits stream/complete for UI cleanup',
  );
  assert.equal(
    context.__streamMessages.every(
      (message) =>
        message.type !== 'stream/complete' || message.payload.messageId === ownerMessageId,
    ),
    true,
    'both completes reuse owner streamMessageId so webview can ack',
  );
});

test('late owner generate-card complete does not clobber newer coach streamMessageId', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingGenerateCardCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });
  const requestId = 'training-req-owner-then-coach';
  let ownerRelease;
  const ownerHold = new Promise((resolve) => {
    ownerRelease = resolve;
  });
  let ownerStarted;
  const ownerStartedGate = new Promise((resolve) => {
    ownerStarted = resolve;
  });
  let streamCalls = 0;

  context.sidecarClient = {
    ...context.sidecarClient,
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath]);
      return {
        memory: {
          workspace: {
            workspace_id: context.getHostState().workspace.workspaceFolder,
            selected_card_id: 'card-bound-once',
            selected_card_type: 'practice',
            selected_card_status: 'active',
          },
          training_card_candidates: [],
          training_event_ledger: [],
        },
      };
    },
    async *fetchSSE(port, requestPath, body) {
      context.__postCalls.push([port, requestPath, body]);
      streamCalls += 1;
      if (streamCalls === 1) {
        ownerStarted();
        await ownerHold;
        yield {
          event: 'complete',
          data: JSON.stringify({
            response: {
              card: { card_id: 'generated-card', card_type: body.card_type },
              score: 0.9,
              success: true,
              active_routing: { selected_card_id: 'card-bound-once' },
            },
          }),
        };
        return;
      }
      yield {
        event: 'complete',
        data: JSON.stringify({
          response: {
            card: { card_id: 'generated-card', card_type: body.card_type },
            score: 0.9,
            success: true,
            active_routing: { selected_card_id: 'card-bound-once' },
          },
        }),
      };
    },
  };

  const ownerPending = trainingGenerateCardCommand(context, {
    source: 'conversation',
    cardType: 'practice',
    requestId,
  });
  await ownerStartedGate;
  const ownerMessageId = context.getStreamingState().streamMessageId;
  assert.ok(ownerMessageId);

  const waiter = await trainingGenerateCardCommand(context, {
    source: 'conversation',
    cardType: 'practice',
    requestId,
  });
  assert.equal(waiter.ok, true);
  assert.equal(context.getStreamingState().isStreaming, false);
  assert.equal(context.__patched.length, 1, 'waiter claimed bind once');

  const coachStreamMessageId = 'msg_coach_after_waiter';
  await context.setStreamingState({
    isStreaming: true,
    streamedContent: 'Coach reply in flight',
    streamMessageId: coachStreamMessageId,
    streamError: undefined,
    reliabilityPhase: 'pending',
  });
  assert.equal(context.getStreamingState().streamMessageId, coachStreamMessageId);
  assert.equal(context.getStreamingState().isStreaming, true);

  ownerRelease();
  const owner = await ownerPending;
  assert.equal(owner.ok, true);
  assert.equal(
    context.getStreamingState().streamMessageId,
    coachStreamMessageId,
    'late owner must not overwrite coach streamMessageId',
  );
  assert.equal(
    context.getStreamingState().isStreaming,
    true,
    'late owner must not clear coach isStreaming',
  );
  assert.equal(context.__patched.length, 1, 'late owner must not remint card bind');
  assert.equal(context.__synced.length, 1);
  assert.equal(
    context.__streamMessages.filter(
      (message) =>
        message.type === 'stream/complete' && message.payload.messageId === ownerMessageId,
    ).length,
    1,
    'only waiter acked owner streamMessageId; late owner skipped ack after coach took over',
  );
});

test('generate-card complete still binds once when coach owns streamMessageId', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingGenerateCardCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });
  const requestId = 'training-req-coach-owns-before-complete';
  let ownerRelease;
  const ownerHold = new Promise((resolve) => {
    ownerRelease = resolve;
  });
  let ownerStarted;
  const ownerStartedGate = new Promise((resolve) => {
    ownerStarted = resolve;
  });
  let streamCalls = 0;

  context.sidecarClient = {
    ...context.sidecarClient,
    async getJson(port, requestPath) {
      context.__postCalls.push([port, requestPath]);
      return {
        memory: {
          workspace: {
            workspace_id: context.getHostState().workspace.workspaceFolder,
            selected_card_id: 'card-bound-under-coach',
            selected_card_type: 'practice',
            selected_card_status: 'active',
          },
          training_card_candidates: [],
          training_event_ledger: [],
        },
      };
    },
    async *fetchSSE(port, requestPath, body) {
      context.__postCalls.push([port, requestPath, body]);
      streamCalls += 1;
      if (streamCalls === 1) {
        ownerStarted();
      }
      await ownerHold;
      yield {
        event: 'complete',
        data: JSON.stringify({
          response: {
            card: { card_id: 'generated-card', card_type: body.card_type },
            score: 0.91,
            success: true,
            active_routing: { selected_card_id: 'card-bound-under-coach' },
          },
        }),
      };
    },
  };

  const ownerPending = trainingGenerateCardCommand(context, {
    source: 'conversation',
    cardType: 'practice',
    requestId,
  });
  await ownerStartedGate;
  const ownerMessageId = context.getStreamingState().streamMessageId;
  assert.ok(ownerMessageId);
  assert.equal(context.__patched.length, 0, 'no bind before complete');

  const coachStreamMessageId = 'msg_coach_owns_before_complete';
  await context.setStreamingState({
    isStreaming: true,
    streamedContent: 'Coach reply owns stream',
    streamMessageId: coachStreamMessageId,
    streamError: undefined,
    reliabilityPhase: 'pending',
  });
  assert.equal(context.getStreamingState().streamMessageId, coachStreamMessageId);

  // Concurrent waiter while coach owns stream — both completes must share one claim-once bind.
  const waiterPending = trainingGenerateCardCommand(context, {
    source: 'conversation',
    cardType: 'practice',
    requestId,
  });

  ownerRelease();
  const [owner, waiter] = await Promise.all([ownerPending, waiterPending]);
  assert.equal(owner.ok, true);
  assert.equal(waiter.ok, true);
  assert.equal(
    context.getStreamingState().streamMessageId,
    coachStreamMessageId,
    'complete must not overwrite coach streamMessageId',
  );
  assert.equal(
    context.getStreamingState().isStreaming,
    true,
    'complete must not clear coach isStreaming',
  );
  assert.equal(context.__patched.length, 1, 'claim-once bind still applies under coach stream');
  assert.equal(context.__synced.length, 1, 'syncState still runs once for claim-once bind');
  assert.equal(
    context.__streamMessages.filter(
      (message) =>
        message.type === 'stream/complete' && message.payload.messageId === ownerMessageId,
    ).length,
    0,
    'fail-closed: no stream/complete ack onto coach-owned stream',
  );
  assert.equal(
    context.__postCalls.filter((entry) => String(entry[1]).startsWith('/memory/summary')).length,
    1,
    'duplicate completes under coach must not remint via second rehydrate',
  );
});

test('trainingFlashcardAnswerCommand sends workspace_id to sidecar', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingFlashcardAnswerCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });

  const result = await trainingFlashcardAnswerCommand(context, {
    cardId: 'flash-123',
    learnerAnswer: 'ready',
    selectedOptionIndex: 2,
  });

  assert.equal(result.ok, true);
  const [port, requestPath, requestBody] = context.__postCalls[0];
  assert.equal(port, 34891);
  assert.equal(requestPath, '/training/flashcard/answer');
  assert.deepEqual(requestBody, {
    workspace_id: 'F:\\trainer-training',
    card_id: 'flash-123',
    learner_answer: 'ready',
    selected_option_index: 2,
  });
});

test('trainingFlashcardAnswerCommand accepts legacy answer and prefers learnerAnswer', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingFlashcardAnswerCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });

  await trainingFlashcardAnswerCommand(context, {
    cardId: 'flash-legacy',
    answer: 'legacy answer',
  });
  await trainingFlashcardAnswerCommand(context, {
    cardId: 'flash-preferred',
    answer: 'legacy answer',
    learnerAnswer: 'preferred answer',
  });

  const flashAnswerCalls = context.__postCalls.filter(
    ([, requestPath]) => requestPath === '/training/flashcard/answer',
  );

  assert.equal(flashAnswerCalls[0][2].learner_answer, 'legacy answer');
  assert.equal(flashAnswerCalls[1][2].learner_answer, 'preferred answer');
});

test('trainingFlashcardAnswerCommand forwards structured answer modes', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingFlashcardAnswerCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });

  await trainingFlashcardAnswerCommand(context, {
    cardId: 'flash-multiple',
    selectedOptionIndices: [2, 0],
  });
  await trainingFlashcardAnswerCommand(context, {
    cardId: 'flash-fill',
    fillBlankAnswers: { 0: 'router', 1: 'middleware' },
  });
  await trainingFlashcardAnswerCommand(context, {
    cardId: 'flash-sort',
    sortOrder: [1, 0, 2],
  });

  const flashAnswerCalls = context.__postCalls.filter(
    ([, requestPath]) => requestPath === '/training/flashcard/answer',
  );
  assert.deepEqual(flashAnswerCalls.map(([, , body]) => body), [
    {
      workspace_id: 'F:\\trainer-training',
      card_id: 'flash-multiple',
      learner_answer: '',
      selected_option_index: null,
      selected_option_indices: [2, 0],
    },
    {
      workspace_id: 'F:\\trainer-training',
      card_id: 'flash-fill',
      learner_answer: '',
      selected_option_index: null,
      fill_blank_answers: { 0: 'router', 1: 'middleware' },
    },
    {
      workspace_id: 'F:\\trainer-training',
      card_id: 'flash-sort',
      learner_answer: '',
      selected_option_index: null,
      sort_order: [1, 0, 2],
    },
  ]);
});

test('trainingTheoryDrillAnswerCommand sends the current learner answer to sidecar', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingTheoryDrillAnswerCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });

  const result = await trainingTheoryDrillAnswerCommand(context, {
    theoryDrillId: 'theory-123',
    questionId: 'question-123',
    learnerAnswer: 'The route owns the boundary.',
    selectedOptionIndex: 1,
  });

  assert.equal(result.ok, true);
  assert.deepEqual(context.__postCalls[0], [34891, '/training/theory-drill/answer', {
    workspace_id: 'F:\\trainer-training',
    theory_drill_id: 'theory-123',
    question_id: 'question-123',
    learner_answer: 'The route owns the boundary.',
    selected_option_index: 1,
  }]);
});

test('training reflect and return commands use the formal handoff endpoints', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingReflectCommand, trainingReturnCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const reflectionContext = createContext({ workspaceFolder: 'F:\\trainer-training' });

  const reflection = await trainingReflectCommand(reflectionContext, {
    cardId: 'practice-123',
    handoffId: 'handoff-123',
    reflection: 'The focused check proved the state transition is durable.',
  });

  assert.equal(reflection.ok, true);
  assert.deepEqual(reflectionContext.__postCalls[0], [34891, '/training/reflect', {
    workspace_id: 'F:\\trainer-training',
    card_id: 'practice-123',
    handoff_id: 'handoff-123',
    reflection: 'The focused check proved the state transition is durable.',
    request_id: '',
    idempotency_key: '',
    revision: 0,
    timeout_ms: 30000,
    cancel: false,
  }]);
  assert.equal(String(reflectionContext.__postCalls[1][1]).startsWith('/memory/summary?'), true);
  assert.equal(reflectionContext.__patched.length, 1);
  assert.equal(reflectionContext.__synced.length, 1);

  const returnContext = createContext({ workspaceFolder: 'F:\\trainer-training' });
  const returned = await trainingReturnCommand(returnContext, {
    cardId: 'practice-123',
    handoffId: 'handoff-123',
  });

  assert.equal(returned.ok, true);
  assert.deepEqual(returnContext.__postCalls[0], [34891, '/training/return', {
    workspace_id: 'F:\\trainer-training',
    card_id: 'practice-123',
    handoff_id: 'handoff-123',
    request_id: '',
    idempotency_key: '',
    revision: 0,
    timeout_ms: 30000,
    cancel: false,
  }]);
  assert.equal(String(returnContext.__postCalls[1][1]).startsWith('/memory/summary?'), true);
  assert.equal(returnContext.__patched.length, 1);
  assert.equal(returnContext.__synced.length, 1);
});

test('training reflect does not report success when the sidecar rejects the transition', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingReflectCommand } = loadWithVscodeMock(trainingCommandsModulePath, vscodeMock);
  const context = createContext({
    sidecarClient: {
      async postJson() {
        return { ok: false, workspace: {} };
      },
      async getJson() {
        throw new Error('A rejected reflection must not rehydrate state.');
      },
    },
  });

  const result = await trainingReflectCommand(context, {
    cardId: 'practice-123',
    reflection: 'I should not be accepted before trusted verification.',
  });

  assert.equal(result.ok, false);
  assert.equal(context.__patched.length, 0);
  assert.equal(context.__synced.length, 0);
});

test('flashcardCreateCommand sends coach-generated flashcard payloads to sidecar', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { flashcardCreateCommand } = loadWithVscodeMock(trainingCommandsModulePath, vscodeMock);
  const context = createContext({
    workspaceFolder: 'F:\\trainer-training',
    responseLanguage: 'zh-CN',
  });

  const result = await flashcardCreateCommand(context, {
    question: 'What is the smallest useful slice?',
    answerMode: 'text',
    expectedAnswer: 'The smallest verifiable slice.',
    context: 'practice prompt',
  });

  assert.equal(result.ok, true);
  const [port, requestPath, requestBody] = context.__postCalls[0];
  assert.equal(port, 34891);
  assert.equal(requestPath, '/training/generate-card');
  assert.equal(requestBody.workspace_id, 'F:\\trainer-training');
  assert.equal(requestBody.source, 'coach_action_flashcard_create');
  assert.equal(requestBody.card_type, 'flash');
  assert.equal(requestBody.focus_area, 'What is the smallest useful slice?');
  assert.equal(requestBody.target_skill, 'The smallest verifiable slice.');
  assert.equal(requestBody.response_language, 'zh-CN');
});

test('trainingDependencySkillMapActionCommand sends workspace_id to sidecar', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingDependencySkillMapActionCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });

  const result = await trainingDependencySkillMapActionCommand(context, {
    dependencyKey: 'api-client',
    action: 'send_to_flashcards',
    note: 'revisit edge cases',
    focusItemKey: 'request retry',
    relatedApi: 'fetch',
    scenario: 'retry failure',
  });

  assert.equal(result.ok, true);
  const [port, requestPath, requestBody] = context.__postCalls[0];
  assert.equal(port, 34891);
  assert.equal(requestPath, '/training/dependency-skill-map/action');
  assert.deepEqual(requestBody, {
    workspace_id: 'F:\\trainer-training',
    dependency_key: 'api-client',
    action: 'send_to_flashcards',
    note: 'revisit edge cases',
    focus_item_key: 'request retry',
    related_api: 'fetch',
    scenario: 'retry failure',
  });
});

test('trainingDependencySkillMapActionCommand uses the managed workspace context ID', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingDependencySkillMapActionCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });
  context.getHostState().bootstrap.memory.workspace = {
    ...(context.getHostState().bootstrap.memory.workspace ?? {}),
    trainerWorkspace: {
      status: 'managed',
      contextId: 'context-training-123',
      canonicalProjectPath: 'f:\\trainer-training',
      rootId: 'root-training',
      projectId: 'project-training',
    },
  };

  const result = await trainingDependencySkillMapActionCommand(context, {
    dependencyKey: 'api-client',
    action: 'send_to_flashcards',
  });

  assert.equal(result.ok, true);
  const [, requestPath, requestBody] = context.__postCalls[0];
  assert.equal(requestPath, '/training/dependency-skill-map/action');
  assert.equal(requestBody.workspace_id, 'context-training-123');
  assert.notEqual(requestBody.workspace_id, 'F:\\trainer-training');
});

test('trainingDependencySkillMapActionCommand rehydrates managed scenario and theory state from its runtime context', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingDependencySkillMapActionCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const calls = [];
  const scenarioLab = {
    id: 'scenario-managed-1',
    title: 'FastAPI dependency boundary',
    focus_area: 'dependency injection',
    status: 'ready',
    success_signal: 'Explain the boundary before coding.',
    dependency_keys: ['fastapi'],
    related_apis: ['Depends'],
  };
  const theoryDrill = {
    id: 'theory-managed-1',
    title: 'Dependency review',
    focus_area: 'dependency injection',
    status: 'ready',
    summary: 'Recall why the route owns the boundary.',
    questions: [{ id: 'question-managed-1', prompt: 'Where does Depends belong?' }],
  };
  const context = createContext({
    workspaceFolder: 'F:\\trainer-training',
    sidecarClient: {
      async postJson(port, requestPath, body) {
        calls.push([port, requestPath, body]);
        return {
          ok: true,
          maps: [{ dependency_key: 'fastapi' }],
          history: [],
          scenario_lab: scenarioLab,
        };
      },
      async getJson(port, requestPath) {
        calls.push([port, requestPath]);
        return {
          memory: {
            workspace: { workspace_id: 'context-training-123' },
            scenario_lab: scenarioLab,
            theory_drill: theoryDrill,
          },
        };
      },
    },
  });
  context.getHostState().bootstrap.memory.workspace = {
    ...(context.getHostState().bootstrap.memory.workspace ?? {}),
    trainerWorkspace: {
      status: 'managed',
      contextId: 'context-training-123',
      canonicalProjectPath: 'f:\\trainer-training',
      rootId: 'root-training',
      projectId: 'project-training',
    },
  };

  const result = await trainingDependencySkillMapActionCommand(context, {
    dependencyKey: 'fastapi',
    action: 'request_verification',
    relatedApi: 'Depends',
  });

  assert.equal(result.ok, true);
  assert.equal(calls[0][2].workspace_id, 'context-training-123');
  assert.equal(calls[1][1], '/memory/summary?workspace_id=context-training-123');
  assert.equal(context.__patched.length, 1);
  assert.equal(context.__patched[0].workspaceTrainingState?.workspaceId, 'context-training-123');
  assert.equal(context.__patched[0].workspaceTrainingState?.scenarioLab?.id, scenarioLab.id);
  assert.equal(context.__patched[0].workspaceTrainingState?.scenarioLab?.focusArea, 'dependency injection');
  assert.equal(context.__patched[0].workspaceTrainingState?.theoryDrill?.id, theoryDrill.id);
  assert.equal(
    context.__patched[0].workspaceTrainingState?.theoryDrill?.questions?.[0]?.prompt,
    'Where does Depends belong?',
  );
});

test('trainingDependencySkillMapActionCommand blocks direct mastery upgrades before any HTTP request', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingDependencySkillMapActionCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ responseLanguage: 'zh-CN' });

  for (const action of ['mark_practiced', 'mark_applied', 'mark_transferable']) {
    const result = await trainingDependencySkillMapActionCommand(context, {
      dependencyKey: 'fastapi',
      action,
    });

    assert.equal(result.ok, false);
    assert.equal(result.message, '先验证当前文件；填写说明不会直接改变掌握记录。');
  }

  assert.equal(context.__postCalls.length, 0);
  assert.equal(context.__patched.length, 0);
  assert.equal(context.__synced.length, 0);
});

test('trainingReviewQueueActionCommand and trainingScenarioLabActionCommand send workspace_id to sidecar', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const {
    trainingReviewArtifactActionCommand,
    trainingReviewQueueActionCommand,
    trainingScenarioLabActionCommand,
  } = loadWithVscodeMock(trainingCommandsModulePath, vscodeMock);

  const reviewContext = createContext({ workspaceFolder: 'F:\\trainer-training' });
  const reviewResult = await trainingReviewQueueActionCommand(reviewContext, {
    concept: 'retry policy',
    action: 'accept',
    scope: 'focus_area',
    batchLimit: 2,
    focusArea: 'resilience',
    taskHint: 'Retry one failed request with a bounded policy.',
    note: 'pull into training',
  });

  assert.equal(reviewResult.ok, true);
  assert.equal(reviewContext.__postCalls[0][1], '/training/review-queue/action');
  assert.deepEqual(reviewContext.__postCalls[0][2], {
    workspace_id: 'F:\\trainer-training',
    concept: 'retry policy',
    action: 'accept',
    scope: 'focus_area',
    batch_limit: 2,
    focus_area: 'resilience',
    task_hint: 'Retry one failed request with a bounded policy.',
    note: 'pull into training',
  });

  const artifactContext = createContext({ workspaceFolder: 'F:\\trainer-training' });
  const artifactResult = await trainingReviewArtifactActionCommand(artifactContext, {
    reviewArtifactId: 'review-123',
    action: 'resolved',
    note: 'The retry stops after the configured limit.',
  });

  assert.equal(artifactResult.ok, true);
  assert.deepEqual(artifactContext.__postCalls[0], [34891, '/training/review-artifact/action', {
    workspace_id: 'F:\\trainer-training',
    review_artifact_id: 'review-123',
    action: 'resolved',
    note: 'The retry stops after the configured limit.',
    edit_patch: {},
  }]);

  const scenarioContext = createContext({ workspaceFolder: 'F:\\trainer-training' });
  const scenarioResult = await trainingScenarioLabActionCommand(scenarioContext, {
    scenarioLabId: 'scenario-1',
    action: 'start',
    note: 'begin with the smallest slice',
  });

  assert.equal(scenarioResult.ok, true);
  assert.equal(scenarioContext.__postCalls[0][1], '/training/scenario-lab/action');
  assert.deepEqual(scenarioContext.__postCalls[0][2], {
    workspace_id: 'F:\\trainer-training',
    scenario_lab_id: 'scenario-1',
    action: 'start',
    note: 'begin with the smallest slice',
  });
});

test('stateful training commands keep a managed workspace context across generation and follow-up actions', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const {
    trainingGenerateCardCommand,
    trainingReviewQueueActionCommand,
    trainingScenarioLabActionCommand,
  } = loadWithVscodeMock(trainingCommandsModulePath, vscodeMock);
  const managedContextId = 'context-training-456';
  const makeManagedContext = () => {
    const context = createContext({ workspaceFolder: 'F:\\trainer-training' });
    context.getHostState().bootstrap.memory.workspace = {
      ...(context.getHostState().bootstrap.memory.workspace ?? {}),
      trainerWorkspace: {
        status: 'managed',
        contextId: managedContextId,
        canonicalProjectPath: 'f:\\trainer-training',
        rootId: 'root-training',
        projectId: 'project-training',
      },
    };
    return context;
  };

  const generationContext = makeManagedContext();
  const generationResult = await trainingGenerateCardCommand(generationContext, {
    cardType: 'practice',
  });
  assert.equal(generationResult.ok, true);
  assert.equal(generationContext.__postCalls[0][2].workspace_id, managedContextId);
  assert.equal(
    generationContext.__postCalls[1][1],
    `/memory/summary?workspace_id=${managedContextId}`,
  );

  const reviewContext = makeManagedContext();
  const reviewResult = await trainingReviewQueueActionCommand(reviewContext, {
    concept: 'retry policy',
    action: 'accept',
  });
  assert.equal(reviewResult.ok, true);
  assert.equal(reviewContext.__postCalls[0][2].workspace_id, managedContextId);

  const scenarioContext = makeManagedContext();
  const scenarioResult = await trainingScenarioLabActionCommand(scenarioContext, {
    scenarioLabId: 'scenario-1',
    action: 'start',
  });
  assert.equal(scenarioResult.ok, true);
  assert.equal(scenarioContext.__postCalls[0][2].workspace_id, managedContextId);
});

test('trainingGenerateCardCommand posts a sanitized stream/error when the sidecar leaks', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingGenerateCardCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const fakeKey = 'sk-test-not-a-real-key-aaaaaaaa';
  const leak = [
    'Traceback (most recent call last):',
    '  File "app.py", line 12, in run',
    'KeyError: boom',
    '{"choices":[{"message":{"content":"hidden","token":"fake-token-zzzz"}}]}',
    `api_key=${fakeKey}`,
  ].join('\n');
  const context = createContext({
    workspaceFolder: 'F:\\trainer-training',
    responseLanguage: 'en-US',
  });
  const defaultPostJson = context.sidecarClient.postJson;
  context.sidecarClient = {
    ...context.sidecarClient,
    async postJson(port, requestPath, body, options) {
      return defaultPostJson(port, requestPath, body, options);
    },
    async *fetchSSE() {
      yield {
        event: 'error',
        data: JSON.stringify({ error: leak }),
      };
    },
  };

  const result = await trainingGenerateCardCommand(context, {
    source: 'conversation',
    cardType: 'practice',
    focusArea: 'state machine',
    targetSkill: 'status transition',
  });

  assert.equal(result.ok, false);
  const streamError = context.__streamMessages.find((message) => message.type === 'stream/error');
  assert.ok(streamError);
  const rendered = JSON.stringify({ result, streamError });
  assert.doesNotMatch(rendered, /sk-test-not-a-real-key-aaaaaaaa/);
  assert.doesNotMatch(rendered, /Traceback \(most recent call last\)/i);
  assert.doesNotMatch(rendered, /File "app\.py"/);
  assert.doesNotMatch(rendered, /"choices"/);
  assert.doesNotMatch(rendered, /fake-token-zzzz/);
  assert.match(String(streamError.payload.error), /failed|hidden|Settings|Try again|connection/i);
  assert.ok(String(streamError.payload.error).trim().length > 0);
});

test('trainingGenerateCardCommand treats HTTP 502 as pending→failure, not silent success', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingGenerateCardCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({
    workspaceFolder: 'F:\\trainer-training',
    responseLanguage: 'en-US',
  });
  context.sidecarClient = {
    ...context.sidecarClient,
    async *fetchSSE() {
      throw new Error('SSE request failed (502): {"detail":"provider down"}');
    },
  };

  const result = await trainingGenerateCardCommand(context, {
    source: 'conversation',
    cardType: 'practice',
    focusArea: 'auth expiry',
    targetSkill: 'token refresh',
  });

  assert.equal(result.ok, false);
  const streamStart = context.__streamMessages.find((message) => message.type === 'stream/start');
  const streamError = context.__streamMessages.find((message) => message.type === 'stream/error');
  const streamComplete = context.__streamMessages.find((message) => message.type === 'stream/complete');
  assert.ok(streamStart, 'expected stream/start pending');
  assert.ok(streamError, 'expected stream/error failure');
  assert.equal(streamComplete, undefined);
  assert.equal(streamError.payload.reliabilityOutcome, 'failure');
  assert.equal(streamError.payload.reliabilityPhase, 'acked');
  assert.ok(String(result.message || '').trim().length > 0);
  assert.doesNotMatch(JSON.stringify({ result, streamError }), /api_key|sk-|traceback/i);
});

test('waiting composer enqueue fails closed when sidecar is down', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { evidenceEnqueueCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({
    workspaceFolder: 'F:\\trainer-training',
    responseLanguage: 'en-US',
  });
  context.sidecarManager.getStatus = () => ({ lifecycle: 'stopped' });

  const result = await evidenceEnqueueCommand(context, {
    waitingComposer: true,
    summary: 'I verified the retry stops after the configured limit.',
  });

  assert.equal(result.ok, false);
  assert.equal(result.data, undefined);
  assert.doesNotMatch(JSON.stringify(result), /"id"\s*:/);
  assert.doesNotMatch(String(result.message), /Traceback|api_key|sk-test|\{/);
  assert.match(String(result.message), /Sidecar is not running/);
  assert.match(String(result.message), /Retry in the evidence composer/);
  assert.equal(context.__postCalls.length, 0);
  assert.equal(context.__synced.length, 0);
});

test('waiting composer enqueue sanitizes sidecar 400 and does not invent a pending id', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { evidenceEnqueueCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const fakeKey = 'sk-test-not-a-real-key-aaaaaaaa';
  const leak = [
    'Sidecar request failed (400).',
    'Traceback (most recent call last):',
    '  File "app.py", line 12, in run',
    `{"detail":"boom","token":"${fakeKey}"}`,
  ].join('\n');
  const context = createContext({
    workspaceFolder: 'F:\\trainer-training',
    responseLanguage: 'en-US',
  });
  context.sidecarClient.postJson = async () => {
    throw new Error(leak);
  };

  const result = await evidenceEnqueueCommand(context, {
    waitingComposer: true,
    summary: 'Replacement verify note after reject.',
  });

  assert.equal(result.ok, false);
  assert.equal(result.data, undefined);
  assert.doesNotMatch(JSON.stringify(result), /"id"\s*:/);
  assert.doesNotMatch(String(result.message), /sk-test-not-a-real-key-aaaaaaaa/);
  assert.doesNotMatch(String(result.message), /Traceback \(most recent call last\)/);
  assert.doesNotMatch(String(result.message), /File "app\.py"/);
  assert.doesNotMatch(String(result.message), /\{"detail"/);
  assert.match(String(result.message), /hidden|failed|not queued/i);
  assert.match(String(result.message), /Retry in the evidence composer/);
  assert.equal(context.__synced.length, 0);
});

test('waiting composer enqueue still posts one item on success', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { evidenceEnqueueCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({
    workspaceFolder: 'F:\\trainer-training',
    responseLanguage: 'en-US',
  });

  const result = await evidenceEnqueueCommand(context, {
    waitingComposer: true,
    summary: 'I verified the retry stops after the configured limit.',
  });

  assert.equal(result.ok, true);
  assert.equal(result.data, undefined);
  const enqueueCalls = context.__postCalls.filter((call) => call[1] === '/evidence/enqueue');
  assert.equal(enqueueCalls.length, 1);
  assert.deepEqual(enqueueCalls[0][2], {
    workspace_id: 'F:\\trainer-training',
    waiting_composer: true,
    summary: 'I verified the retry stops after the configured limit.',
  });
  assert.equal(context.__synced.length, 1);
});

test('card-status / reflect / return forward __trainerTrainingPersistenceId as request_id', async () => {
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const {
    trainingCardStatusTransitionCommand,
    trainingReflectCommand,
    trainingReturnCommand,
  } = loadWithVscodeMock(trainingCommandsModulePath, vscodeMock);
  const persistenceId = 'training-persistence-abc123';

  const statusContext = createContext({ workspaceFolder: 'F:\\trainer-training' });
  const statusResult = await trainingCardStatusTransitionCommand(statusContext, {
    cardId: 'card-persist-1',
    newStatus: 'active',
    reason: 'study_note_submitted',
    __trainerTrainingPersistenceId: persistenceId,
  });
  assert.equal(statusResult.ok, true);
  assert.equal(statusContext.__postCalls[0][1], '/training/card-status');
  assert.equal(statusContext.__postCalls[0][2].request_id, persistenceId);
  assert.equal(statusContext.__postCalls[0][2].idempotency_key, persistenceId);

  const reflectContext = createContext({ workspaceFolder: 'F:\\trainer-training' });
  const reflectResult = await trainingReflectCommand(reflectContext, {
    cardId: 'practice-persist-1',
    handoffId: 'handoff-persist-1',
    reflection: 'Persistence id must become sidecar request_id.',
    __trainerTrainingPersistenceId: persistenceId,
  });
  assert.equal(reflectResult.ok, true);
  assert.equal(reflectContext.__postCalls[0][1], '/training/reflect');
  assert.equal(reflectContext.__postCalls[0][2].request_id, persistenceId);

  const returnContext = createContext({ workspaceFolder: 'F:\\trainer-training' });
  const returnResult = await trainingReturnCommand(returnContext, {
    cardId: 'practice-persist-1',
    handoffId: 'handoff-persist-1',
    __trainerTrainingPersistenceId: persistenceId,
  });
  assert.equal(returnResult.ok, true);
  assert.equal(returnContext.__postCalls[0][1], '/training/return');
  assert.equal(returnContext.__postCalls[0][2].request_id, persistenceId);
});

test('card-status leftover-not-live 409 does not rehydrate leftover as live', async () => {
  const httpClientPath = path.resolve(
    __dirname,
    '..',
    'dist',
    'extension',
    'src',
    'core',
    'httpClient.js',
  );
  const { SidecarHttpError } = require(httpClientPath);
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingCardStatusTransitionCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });
  context.sidecarClient.postJson = async () => {
    throw new SidecarHttpError(409, 'Sidecar request failed (409).', {
      detail:
        'Recovered training card is leftover-not-live. /training/card-status will not skip, grade, or resurrect leftover as live.',
    });
  };

  const result = await trainingCardStatusTransitionCommand(context, {
    cardId: 'card-leftover-stored-a',
    newStatus: 'skipped',
    reason: 'Learner skipped',
  });

  assert.equal(result.ok, false);
  assert.match(String(result.message), /leftover-not-live/);
  assert.doesNotMatch(String(result.message), /sk-[a-z0-9]/i);
  assert.equal(context.__patched.length, 0);
  assert.equal(context.__synced.length, 0);
});

test('reflect leftover-not-live 409 does not rehydrate leftover as live', async () => {
  const httpClientPath = path.resolve(
    __dirname,
    '..',
    'dist',
    'extension',
    'src',
    'core',
    'httpClient.js',
  );
  const { SidecarHttpError } = require(httpClientPath);
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingReflectCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });
  context.sidecarClient.postJson = async () => {
    throw new SidecarHttpError(409, 'Sidecar request failed (409).', {
      detail:
        'Recovered training card is leftover-not-live. Trainer will not skip, grade, reflect, return, or resurrect leftover as live.',
    });
  };

  const result = await trainingReflectCommand(context, {
    cardId: 'card-leftover-stored-a',
    handoffId: 'handoff-leftover-dump',
    reflection: 'Leftover dump must not reflect as live.',
  });

  assert.equal(result.ok, false);
  assert.match(String(result.message), /leftover-not-live/);
  assert.doesNotMatch(String(result.message), /sk-[a-z0-9]/i);
  assert.equal(context.__patched.length, 0);
  assert.equal(context.__synced.length, 0);
});

test('return leftover-not-live 409 does not rehydrate leftover as live', async () => {
  const httpClientPath = path.resolve(
    __dirname,
    '..',
    'dist',
    'extension',
    'src',
    'core',
    'httpClient.js',
  );
  const { SidecarHttpError } = require(httpClientPath);
  const vscodeMock = { commands: { async executeCommand() { return undefined; } } };
  const { trainingReturnCommand } = loadWithVscodeMock(
    trainingCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ workspaceFolder: 'F:\\trainer-training' });
  context.sidecarClient.postJson = async () => {
    throw new SidecarHttpError(409, 'Sidecar request failed (409).', {
      detail:
        'Recovered training card is leftover-not-live. Trainer will not skip, grade, reflect, return, or resurrect leftover as live.',
    });
  };

  const result = await trainingReturnCommand(context, {
    cardId: 'card-leftover-stored-a',
    handoffId: 'handoff-leftover-dump',
  });

  assert.equal(result.ok, false);
  assert.match(String(result.message), /leftover-not-live/);
  assert.doesNotMatch(String(result.message), /sk-[a-z0-9]/i);
  assert.equal(context.__patched.length, 0);
  assert.equal(context.__synced.length, 0);
});
