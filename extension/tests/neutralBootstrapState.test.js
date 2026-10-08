'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');
const typescript = require('typescript');

const stateSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'app',
  'useWorkbenchState.ts',
);
const neutralBootstrapSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'neutralBootstrap.ts',
);

function compileTypeScript(sourcePath) {
  return typescript.transpileModule(fs.readFileSync(sourcePath, 'utf8'), {
    compilerOptions: {
      module: typescript.ModuleKind.CommonJS,
      target: typescript.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
    fileName: sourcePath,
  }).outputText;
}

function createFixtureBootstrap() {
  const sentinel = 'fixture-only-data-must-never-render';
  return {
    activeView: 'training',
    workspaceTrainingState: { id: sentinel },
    connection: {
      state: 'connected',
      provider: {
        name: sentinel,
        model: sentinel,
        protocol: 'openai_chat_completions_compatible',
        protocolFamily: 'openai',
        capabilities: { fixtureCapability: sentinel },
      },
    },
    providerConfig: {
      configured: true,
      name: sentinel,
      baseUrl: sentinel,
      model: sentinel,
      apiKeyConfigured: true,
      availableModels: [sentinel],
      modelListStatus: 'ready',
      capabilities: { fixtureCapability: sentinel },
    },
    liveContext: {
      activeFile: sentinel,
      activeLanguageId: sentinel,
      selectionRange: undefined,
      selectionPreview: sentinel,
      diagnosticsSummary: sentinel,
      diagnosticErrors: 1,
      diagnosticWarnings: 1,
      documentVersion: 1,
      recentFiles: [sentinel],
      recentEditedFiles: [sentinel],
      relatedFiles: [sentinel],
    },
    profile: {
      goals: [sentinel],
      focusAreas: [sentinel],
    },
    plan: {
      id: sentinel,
      title: sentinel,
      summary: sentinel,
      stages: [{ id: sentinel }],
      currentStageId: sentinel,
    },
    task: {
      id: sentinel,
      title: sentinel,
      description: sentinel,
      constraints: [sentinel],
      acceptanceCriteria: [sentinel],
      nextActionLabel: sentinel,
    },
    evaluation: {
      headline: sentinel,
      summary: sentinel,
      passRate: 1,
      updatedAt: sentinel,
      checks: [{ id: sentinel }],
      nextStep: sentinel,
    },
    memory: {
      currentFocus: sentinel,
      weakSpots: [sentinel],
      recentWins: [sentinel],
      reviewSummary: sentinel,
      reviewRhythm: sentinel,
      dueReviews: [sentinel],
      teachingObservations: [sentinel],
      lowestMasteryConcepts: [sentinel],
      activeThread: sentinel,
      memoryEvidence: [sentinel],
      workspace: {
        id: sentinel,
        coachDefaults: {
          workspaceMemoryToggles: { decisions: true },
        },
      },
    },
    coachingState: {
      scenario: sentinel,
      answerMode: 'guided',
      learnerSignal: 'steady',
      summary: sentinel,
      nextStep: sentinel,
      encouragement: sentinel,
      updatedAt: sentinel,
    },
    coachTurn: { id: sentinel },
    coachFocus: sentinel,
    planRuntimeStatus: { id: sentinel },
    reviewQueueSummary: sentinel,
    nextReviewDue: sentinel,
    conversation: [{ id: sentinel, content: sentinel }],
    resources: [{ id: sentinel, name: sentinel }],
    suggestedActions: [{ id: sentinel, label: sentinel }],
    commands: [{ id: sentinel, label: sentinel }],
    projectIdeas: [{ id: sentinel, title: sentinel }],
  };
}

function createZustandShim() {
  return {
    create(initializer) {
      let state;
      const store = () => state;
      store.getState = () => state;
      const set = (nextState) => {
        const patch = typeof nextState === 'function' ? nextState(state) : nextState;
        state = { ...state, ...patch };
      };
      state = initializer(set, () => state, {
        getState: () => state,
        setState: set,
      });
      return store;
    },
  };
}

function createProtocolShim() {
  const emptyStreamingState = () => ({
    isStreaming: false,
    streamedContent: '',
    streamMessageId: undefined,
    streamError: undefined,
    agentActivity: [],
  });
  return {
    createEmptyTrainerStreamingState: emptyStreamingState,
    normalizeTrainerStreamingState(value) {
      return {
        ...emptyStreamingState(),
        ...(value ?? {}),
      };
    },
    deriveTrainerStreamingOperationMessage() {
      return undefined;
    },
    upsertTrainerToolActivity(items, update) {
      const activities = [...(items ?? [])];
      const index = activities.findIndex((activity) => activity.id === update.id);
      const current = index >= 0 ? activities[index] : undefined;
      const next = {
        id: update.id,
        name: update.name ?? current?.name ?? update.id,
        status: update.status,
        args: update.args ?? current?.args,
        result: update.result ?? current?.result,
        step: update.step ?? current?.step,
      };
      if (index >= 0) {
        activities[index] = next;
      } else {
        activities.push(next);
      }
      return activities;
    },
  };
}

function loadWorkbenchState({ injectedBootstrap, persisted } = {}) {
  const fixture = createFixtureBootstrap();
  const postedMessages = [];
  const persistedWrites = [];
  const originalLoad = Module._load;
  const previousTsLoader = Module._extensions['.ts'];
  const target = new Module(stateSourcePath, module);
  target.filename = stateSourcePath;
  target.paths = Module._nodeModulePaths(path.dirname(stateSourcePath));

  delete require.cache[neutralBootstrapSourcePath];
  Module._extensions['.ts'] = (loadedModule, filename) => {
    loadedModule._compile(compileTypeScript(filename), filename);
  };

  Module._load = function loadWithStateMocks(request, parent, isMain) {
    if (parent?.filename === stateSourcePath) {
      if (request === 'zustand') {
        return createZustandShim();
      }
      if (request === '../../../../shared/src/protocol') {
        return createProtocolShim();
      }
      if (request === '../lib/mockData') {
        return { mockBootstrapData: fixture };
      }
      if (request === '../lib/vscode') {
        return {
          getInjectedBootstrapState: () => injectedBootstrap,
          getPersistedState: () => persisted,
          inVsCodeWebview: () => true,
          setPersistedState(state) { persistedWrites.push(state); },
          adoptHostSyncScope() {},
          postMessage(message) { postedMessages.push(message); },
        };
      }
      if (request === '../lib/types') {
        return {
          normalizeSidebarView: (view) =>
            view === 'training' || view === 'resources' ? view : 'coach',
          normalizeTeachingStyle: (style) => style ?? 'auto',
        };
      }
    }
    return originalLoad.call(this, request, parent, isMain);
  };

  try {
    target._compile(compileTypeScript(stateSourcePath), stateSourcePath);
    const store = target.exports.useWorkbenchState;
    return {
      ...store.getState(),
      getState: store.getState,
      postedMessages,
      persistedWrites,
    };
  } finally {
    Module._load = originalLoad;
    if (previousTsLoader === undefined) {
      delete Module._extensions['.ts'];
    } else {
      Module._extensions['.ts'] = previousTsLoader;
    }
    delete require.cache[neutralBootstrapSourcePath];
  }
}

test('page exit immediately persists the latest scoped draft before the debounce expires', () => {
  const previousWindow = global.window;
  const events = new EventTarget();
  const timers = new Map();
  let sequence = 0;
  global.window = {
    setTimeout(callback) { const id = ++sequence; timers.set(id, callback); return id; },
    clearTimeout(id) { timers.delete(id); },
    addEventListener: (...args) => events.addEventListener(...args),
    removeEventListener: (...args) => events.removeEventListener(...args),
  };
  try {
    const state = loadWorkbenchState();
    state.getState().selectComposerDraftScope('workspace-one\0session-one');
    state.persistedWrites.length = 0;
    state.getState().setComposerDraft('first keystrokes');
    state.getState().setComposerDraft('last keystrokes before reload');
    assert.equal(state.persistedWrites.length, 0, 'typing stays batched');
    events.dispatchEvent(new Event('pagehide'));
    assert.equal(state.persistedWrites.length, 1);
    assert.equal(state.persistedWrites[0].composerDraft, 'last keystrokes before reload');
    assert.equal(state.persistedWrites[0].composerDrafts['workspace-one\0session-one'], 'last keystrokes before reload');
    assert.equal(timers.size, 0, 'exit cannot leave a delayed stale write');
    events.dispatchEvent(new Event('pagehide'));
    assert.equal(state.persistedWrites.length, 1, 'a clean exit does not serialize again');
  } finally { global.window = previousWindow; }
});

function assertNoFixtureData(data) {
  assert.doesNotMatch(
    JSON.stringify(data),
    /fixture-only-data-must-never-render/,
    'a neutral or sparse real bootstrap must not fall back to fixture fields',
  );
}

test('the initial VS Code empty state contains no browser fixture data', () => {
  const state = loadWorkbenchState();

  assertNoFixtureData(state.data);
  assert.deepEqual(state.data.conversation, []);
  assert.deepEqual(state.data.resources, []);
  assert.equal(state.data.providerConfig.configured, false);
  assert.equal(state.data.providerConfig.apiKeyConfigured, false);
});

test('a sparse authoritative bootstrap never fills missing state from browser fixture data', () => {
  const state = loadWorkbenchState({
    injectedBootstrap: {
      connection: { state: 'offline' },
      conversation: [],
      resources: [],
    },
  });

  assertNoFixtureData(state.data);
  assert.equal(state.data.connection.state, 'offline');
  assert.deepEqual(state.data.conversation, []);
  assert.deepEqual(state.data.resources, []);
});

test('an authoritative null plan stays absent instead of becoming a formal fallback plan', () => {
  const state = loadWorkbenchState({
    injectedBootstrap: {
      connection: { state: 'connected' },
      plan: null,
    },
  });

  assert.equal(state.data.hasFormalPlan, false);
  assert.equal(state.data.plan.id, '');

  state.applyHostMessage({
    type: 'state/patch',
    payload: {
      plan: {
        id: 'generated-plan',
        title: 'Generated plan',
        summary: 'A real plan now exists.',
        stages: [],
      },
    },
  });
  assert.equal(state.getState().data.hasFormalPlan, true);

  state.applyHostMessage({ type: 'state/patch', payload: { plan: null } });
  assert.equal(state.getState().data.hasFormalPlan, false);
});

test('a pending composer language survives stale host snapshots until the host acknowledges it', () => {
  const state = loadWorkbenchState({
    injectedBootstrap: {
      connection: { state: 'connected' },
      memory: {
        workspace: {
          workspaceId: 'workspace-language',
          responseLanguage: 'en-US',
        },
      },
    },
  });

  state.getState().setComposerLanguage('zh-CN');
  assert.equal(state.getState().pendingComposerLanguage, 'zh-CN');

  state.getState().applyHostMessage({
    type: 'bootstrap',
    payload: {
      connection: { state: 'connected' },
      memory: {
        workspace: {
          workspaceId: 'workspace-language',
          responseLanguage: 'en-US',
        },
      },
    },
  });
  assert.equal(state.getState().layout.composerLanguage, 'zh-CN');
  assert.equal(state.getState().pendingComposerLanguage, 'zh-CN');

  state.getState().applyHostMessage({
    type: 'state/patch',
    payload: {
      memory: { workspace: {} },
    },
  });
  assert.equal(state.getState().layout.composerLanguage, 'zh-CN');
  assert.equal(state.getState().pendingComposerLanguage, 'zh-CN');

  state.getState().applyHostMessage({
    type: 'state/patch',
    payload: {
      memory: {
        workspace: {
          responseLanguage: 'en-US',
        },
      },
    },
  });
  assert.equal(state.getState().layout.composerLanguage, 'zh-CN');
  assert.equal(state.getState().pendingComposerLanguage, 'zh-CN');

  state.getState().applyHostMessage({
    type: 'state/patch',
    payload: {
      memory: {
        workspace: {
          responseLanguage: 'zh-CN',
        },
      },
    },
  });
  assert.equal(state.getState().layout.composerLanguage, 'zh-CN');
  assert.equal(state.getState().pendingComposerLanguage, undefined);

  state.getState().applyHostMessage({
    type: 'state/patch',
    payload: {
      memory: {
        workspace: {
          responseLanguage: 'en-US',
        },
      },
    },
  });
  assert.equal(state.getState().layout.composerLanguage, 'en-US');
});

test('a pending composer language does not cross an explicit workspace switch', () => {
  const bootstrapFor = (workspaceId, responseLanguage) => ({
    connection: { state: 'connected' },
    memory: {
      workspace: {
        workspaceId,
        responseLanguage,
      },
    },
  });

  const bootstrapState = loadWorkbenchState({
    injectedBootstrap: bootstrapFor('workspace-a', 'en-US'),
  });
  bootstrapState.getState().setComposerLanguage('zh-CN');
  bootstrapState.getState().applyHostMessage({
    type: 'bootstrap',
    payload: bootstrapFor('workspace-b', 'en-US'),
  });
  assert.equal(bootstrapState.getState().layout.composerLanguage, 'en-US');
  assert.equal(bootstrapState.getState().pendingComposerLanguage, undefined);

  const patchState = loadWorkbenchState({
    injectedBootstrap: bootstrapFor('workspace-a', 'en-US'),
  });
  patchState.getState().setComposerLanguage('zh-CN');
  patchState.getState().applyHostMessage({
    type: 'state/patch',
    payload: bootstrapFor('workspace-b', 'en-US'),
  });
  assert.equal(patchState.getState().layout.composerLanguage, 'en-US');
  assert.equal(patchState.getState().pendingComposerLanguage, undefined);
});

test('empty leftover plan after a workspace switch is not live Plan identity', () => {
  const state = loadWorkbenchState({
    injectedBootstrap: {
      connection: { state: 'connected' },
      hasFormalPlan: true,
      plan: {
        id: 'plan-formal-old',
        title: 'Keep the current stage',
        summary: 'Leftover formal summary of the old stage path',
        currentStep: 'Keep one auth check',
        stages: [],
      },
    },
  });
  assert.equal(state.data.hasFormalPlan, true);

  state.applyHostMessage({
    type: 'state/patch',
    payload: {
      plan: {
        id: '',
        title: '',
        frozen: false,
        cadence: '',
        summary: '',
        stages: [],
      },
    },
  });
  assert.equal(state.getState().data.hasFormalPlan, false);
  assert.equal(state.getState().data.plan.title, '');
  assert.notEqual(state.getState().data.plan.title, 'Keep the current stage');
});

test('visible bootstrap, state patches, and streaming never retain GBK mojibake', () => {
  const corrupted = '\u6d93\u5b29\u7af4\u9352\u20ac';
  const state = loadWorkbenchState({
    injectedBootstrap: {
      conversation: [{ id: 'corrupted-history', content: corrupted }],
      memory: {
        activeThread: { summary: corrupted, nextStep: corrupted },
      },
    },
  });

  assert.doesNotMatch(JSON.stringify(state.data), new RegExp(corrupted));

  state.applyHostMessage({
    type: 'state/patch',
    payload: {
      coachingState: { summary: corrupted, nextStep: corrupted },
    },
  });
  assert.doesNotMatch(JSON.stringify(state.getState().data), new RegExp(corrupted));

  state.applyHostMessage({ type: 'stream/start', payload: { messageId: 'corrupted-stream' } });
  for (const character of corrupted) {
    state.applyHostMessage({ type: 'stream/chunk', payload: { chunk: character } });
  }
  assert.equal(state.getState().streaming.streamedContent, '');

  state.applyHostMessage({
    type: 'stream/complete',
    payload: {
      tokens: 1,
      summary: corrupted,
      nextStep: corrupted,
      stopReason: corrupted,
    },
  });
  const streaming = state.getState().streaming;
  assert.equal(streaming.completionSummary, undefined);
  assert.equal(streaming.completionNextStep, undefined);
  assert.equal(streaming.completionStopReason, undefined);
  assert.ok(streaming.streamError, 'a rejected stream should tell the learner what to do next');
  assert.equal(state.getState().operationMessage?.tone, 'error');
  assert.doesNotMatch(JSON.stringify(streaming), new RegExp(corrupted));

  state.applyHostMessage({
    type: 'stream/tool_call',
    payload: {
      id: corrupted,
      name: corrupted,
      arguments: { detail: corrupted },
    },
  });
  state.applyHostMessage({
    type: 'stream/tool_result',
    payload: {
      id: corrupted,
      name: corrupted,
      ok: false,
      result: { error: corrupted },
    },
  });
  state.applyHostMessage({ type: 'ui/coachPrompt', payload: { draft: corrupted } });
  state.applyHostMessage({
    type: 'ui/restoreView',
    payload: {
      activeView: 'resources',
      resourceSurface: 'detail',
      focusArea: corrupted,
      latestSummary: corrupted,
    },
  });

  assert.equal(state.getState().layout.composerDraft, '');
  const activities = state.getState().streaming.agentActivity;
  const expectedToolName =
    state.getState().layout.composerLanguage === 'zh-CN' ? '工具操作' : 'Tool action';
  assert.equal(activities[0]?.name, expectedToolName);
  assert.doesNotMatch(
    JSON.stringify({ name: activities[0]?.name, args: activities[0]?.args, result: activities[0]?.result }),
    new RegExp(corrupted),
  );
  assert.doesNotMatch(JSON.stringify(state.getState().resourceRestoreContext), new RegExp(corrupted));

  const restoredState = loadWorkbenchState({
    persisted: { composerDraft: corrupted },
  });
  assert.equal(restoredState.layout.composerDraft, '');
});

test('late stream events cannot replace the active Coach stream', () => {
  const state = loadWorkbenchState();
  state.applyHostMessage({ type: 'stream/start', payload: { messageId: 'stream-current' } });

  state.applyHostMessage({
    type: 'stream/chunk',
    payload: { messageId: 'stream-stale', chunk: 'This must not appear.' },
  });
  state.applyHostMessage({
    type: 'stream/error',
    payload: { messageId: 'stream-stale', error: 'This must not interrupt the current reply.' },
  });
  state.applyHostMessage({
    type: 'stream/complete',
    payload: { messageId: 'stream-stale', tokens: 1 },
  });

  assert.equal(state.getState().streaming.isStreaming, true);
  assert.equal(state.getState().streaming.streamedContent, '');
  assert.equal(state.getState().streaming.streamError, undefined);

  state.applyHostMessage({
    type: 'stream/chunk',
    payload: { messageId: 'stream-current', chunk: 'Current reply.' },
  });
  state.applyHostMessage({
    type: 'stream/complete',
    payload: { messageId: 'stream-current', tokens: 1 },
  });

  assert.equal(state.getState().streaming.isStreaming, false);
  assert.equal(state.getState().streaming.streamedContent, 'Current reply.');
});

test('stream/complete while isStreaming still acks once for matching streamMessageId', () => {
  const state = loadWorkbenchState();
  state.applyHostMessage({ type: 'stream/start', payload: { messageId: 'stream-owner' } });
  assert.equal(state.getState().streaming.isStreaming, true);
  assert.equal(state.getState().streaming.reliabilityPhase, 'pending');

  // Stale other stream must not swallow the in-flight owner/waiter complete path.
  state.applyHostMessage({ type: 'stream/start', payload: { messageId: 'stream-other' } });
  assert.equal(state.getState().streaming.streamMessageId, 'stream-owner');
  assert.equal(state.getState().streaming.isStreaming, true);

  state.applyHostMessage({
    type: 'stream/complete',
    payload: {
      messageId: 'stream-owner',
      tokens: 2,
      reliabilityPhase: 'acked',
      reliabilityOutcome: 'success',
    },
  });
  assert.equal(state.getState().streaming.isStreaming, false);
  assert.equal(state.getState().streaming.reliabilityPhase, 'acked');
  assert.equal(state.getState().streaming.reliabilityOutcome, 'success');

  state.applyHostMessage({
    type: 'stream/complete',
    payload: {
      messageId: 'stream-owner',
      tokens: 99,
      reliabilityPhase: 'acked',
      reliabilityOutcome: 'success',
    },
  });
  assert.equal(state.getState().streaming.isStreaming, false);
  assert.equal(state.getState().streaming.reliabilityPhase, 'acked');
  assert.equal(state.getState().streaming.toolCount, undefined);
});

test('late generate-card stream/complete does not clobber newer coach stream', () => {
  const state = loadWorkbenchState();
  state.applyHostMessage({ type: 'stream/start', payload: { messageId: 'training-owner' } });
  state.applyHostMessage({
    type: 'stream/complete',
    payload: {
      messageId: 'training-owner',
      tokens: 1,
      reliabilityPhase: 'acked',
      reliabilityOutcome: 'success',
    },
  });
  assert.equal(state.getState().streaming.isStreaming, false);
  assert.equal(state.getState().streaming.streamMessageId, 'training-owner');

  state.applyHostMessage({ type: 'stream/start', payload: { messageId: 'msg-coach-newer' } });
  assert.equal(state.getState().streaming.streamMessageId, 'msg-coach-newer');
  assert.equal(state.getState().streaming.isStreaming, true);
  assert.equal(state.getState().streaming.reliabilityPhase, 'pending');

  state.applyHostMessage({
    type: 'stream/complete',
    payload: {
      messageId: 'training-owner',
      tokens: 99,
      reliabilityPhase: 'acked',
      reliabilityOutcome: 'success',
    },
  });
  assert.equal(state.getState().streaming.streamMessageId, 'msg-coach-newer');
  assert.equal(state.getState().streaming.isStreaming, true);
  assert.equal(state.getState().streaming.reliabilityPhase, 'pending');
});

test('bootstrap hydration keeps an operation notice produced by the preceding action', () => {
  const state = loadWorkbenchState();
  const savedNotice = {
    tone: 'success',
    message: "Saved 'Debug provider' as a provider profile.",
  };

  state.applyHostMessage({ type: 'operation/status', payload: savedNotice });
  state.applyHostMessage({
    type: 'bootstrap',
    payload: {
      connection: { state: 'connected' },
      providerConfig: { configured: true, apiKeyConfigured: true },
    },
  });

  assert.deepEqual(state.getState().operationMessage, savedNotice);
});

test('a sparse Training bootstrap keeps a restored next hop visible', () => {
  const state = loadWorkbenchState({
    injectedBootstrap: {
      activeView: 'training',
      workspaceTrainingState: {},
    },
  });
  const nextHop = {
    targetId: 'card-next-hop',
    candidateId: 'candidate-next-hop',
    cardType: 'practice',
    cardTitle: 'FastAPI dependency boundary',
    title: 'FastAPI dependency boundary',
    summary: 'Verify the current dependency selection.',
    status: 'verification_required',
    continueIn: 'training',
  };

  state.applyHostMessage({
    type: 'ui/restoreView',
    payload: {
      activeView: 'training',
      trainingRestoreTarget: 'next_hop',
      latestTrainingNextHop: nextHop,
    },
  });
  state.applyHostMessage({
    type: 'bootstrap',
    payload: {
      activeView: 'training',
      workspaceTrainingState: {
        selectedCardId: nextHop.targetId,
        selectedCardTitle: 'No training task yet',
        selectedCardType: 'flash',
      },
    },
  });

  const resolved = state.getState();
  assert.equal(resolved.layout.activeView, 'training');
  assert.equal(resolved.trainingRestoreContext?.target, 'next_hop');
  assert.equal(resolved.data.workspaceTrainingState?.latestTrainingNextHop?.targetId, nextHop.targetId);
  assert.equal(resolved.data.workspaceTrainingState?.selectedCardTitle, nextHop.cardTitle);
  assert.equal(resolved.data.workspaceTrainingState?.selectedCardType, nextHop.cardType);
});

test('ordinary view switches keep resource detail and training return targets available', () => {
  const state = loadWorkbenchState({
    injectedBootstrap: {
      activeView: 'resources',
      resources: [{ id: 'resource-keep', title: 'Keep this resource' }],
      workspaceTrainingState: {},
    },
  });
  const resourceContext = { surface: 'detail', resourceId: 'resource-keep' };
  const nextHop = {
    targetId: 'card-keep',
    cardType: 'practice',
    cardTitle: 'Keep this training return',
    title: 'Keep this training return',
    status: 'verification_required',
    continueIn: 'training',
  };

  state.getState().setResourceRestoreContext(resourceContext);
  state.getState().setActiveView('coach');
  state.getState().setActiveView('resources');

  assert.deepEqual(state.getState().resourceRestoreContext, resourceContext);

  state.getState().applyHostMessage({
    type: 'ui/restoreView',
    payload: {
      activeView: 'training',
      trainingRestoreTarget: 'next_hop',
      latestTrainingNextHop: nextHop,
    },
  });
  state.getState().setActiveView('coach');
  state.getState().setActiveView('training');

  assert.equal(state.getState().trainingRestoreContext?.target, 'next_hop');
  assert.equal(
    state.getState().data.workspaceTrainingState?.latestTrainingNextHop?.targetId,
    nextHop.targetId,
  );
});

test('a new runtime database drops restore targets even when its context ID is unchanged', () => {
  const state = loadWorkbenchState({ injectedBootstrap: {
    runtimeDataGeneration: 'newer-database',
    memory: { workspace: { workspaceId: 'context-one' }, sandboxPreview: { path: '/old.md' } },
    workspaceTrainingState: { workspaceId: 'context-one', skillProjection: {
      workspaceId: 'context-one', dimensions: { implementation: { state: 'assisted', verifiedCount: 1 } },
    } },
  } });
  state.getState().setResourceRestoreContext({ surface: 'detail', resourceId: 'old-resource' });
  state.getState().openTrainingReviewQueue();
  state.getState().applyHostMessage({ type: 'ui/restoreView', payload: {
    activeView: 'training', trainingRestoreTarget: 'next_hop',
    latestTrainingNextHop: { targetId: 'old-card', cardType: 'practice', title: 'Old card' },
  } });
  // Match the actual JSON bridge: undefined properties do not survive transport.
  state.getState().applyHostMessage(JSON.parse(JSON.stringify({ type: 'bootstrap', payload: {
    runtimeDataGeneration: 'older-backup',
    memory: { workspace: { workspaceId: 'context-one' } },
    workspaceTrainingState: { workspaceId: 'context-one' },
  } })));
  const restored = state.getState();
  assert.equal(restored.data.workspaceTrainingState.skillProjection, undefined);
  assert.equal(restored.data.workspaceTrainingState.latestTrainingNextHop, undefined);
  assert.equal(restored.data.memory.sandboxPreview, undefined);
  assert.equal(restored.resourceRestoreContext, undefined);
  assert.equal(restored.trainingRestoreContext, undefined);
  assert.equal(restored.trainingReviewQueueRequested, false);
  assert.deepEqual(restored.stageMaterials, {});
});

test('review navigation opens Training and clears the request when leaving it', () => {
  const state = loadWorkbenchState();
  state.getState().openTrainingReviewQueue();
  assert.equal(state.getState().layout.activeView, 'training');
  assert.equal(state.getState().trainingReviewQueueRequested, true);
  state.getState().setActiveView('coach');
  assert.equal(state.getState().trainingReviewQueueRequested, false);
});

test('accepting a review clears the previous restored training target', () => {
  const state = loadWorkbenchState();
  state.getState().applyHostMessage({ type: 'ui/restoreView', payload: {
    activeView: 'training', trainingRestoreTarget: 'next_hop',
    latestTrainingNextHop: { targetId: 'old-card', cardType: 'practice', title: 'Old card' },
  } });
  state.getState().openTrainingReviewQueue();
  state.getState().beginTrainingReview();
  assert.equal(state.getState().trainingRestoreContext, undefined);
  assert.equal(state.getState().trainingReviewQueueRequested, false);
  assert.equal(state.getState().layout.activeView, 'training');
});

test('stream/cancelled keeps composer draft and acks failure without clearing it', () => {
  const state = loadWorkbenchState({
    injectedBootstrap: {
      connection: { state: 'connected' },
      conversation: [],
    },
  });
  const draft = 'keep this coach draft after abort';
  state.getState().setComposerDraft(draft);
  state.applyHostMessage({
    type: 'stream/start',
    payload: { messageId: 'msg-abort-keep-draft' },
  });
  state.applyHostMessage({
    type: 'operation/status',
    payload: { phase: 'pending', message: 'Sending…' },
  });
  state.applyHostMessage({
    type: 'operation/status',
    payload: { phase: 'failed', message: 'Cancelled' },
  });
  state.applyHostMessage({
    type: 'stream/cancelled',
    payload: { messageId: 'msg-abort-keep-draft' },
  });

  assert.equal(state.getState().layout.composerDraft, draft);
  assert.equal(state.getState().streaming.isStreaming, false);
  assert.equal(state.getState().streaming.reliabilityPhase, 'acked');
  assert.equal(state.getState().streaming.reliabilityOutcome, 'failure');
  assert.equal(state.getState().streaming.completionStopReason, 'cancelled');
  assert.equal(state.getState().streaming.streamError, undefined);
});

test('stream-scoped progress stays in the assistant bubble while failures remain global', () => {
  const state = loadWorkbenchState({
    injectedBootstrap: {
      connection: { state: 'connected' },
      conversation: [],
    },
  });

  state.applyHostMessage({
    type: 'stream/start',
    payload: { messageId: 'msg-inline-progress' },
  });
  state.applyHostMessage({
    type: 'operation/status',
    payload: {
      tone: 'info',
      phase: 'preparing_context',
      surface: 'stream',
      message: 'Preparing context',
    },
  });

  assert.equal(state.getState().operationMessage, undefined);
  assert.equal(state.getState().streaming.reliabilityPhase, 'executing');

  state.applyHostMessage({
    type: 'operation/status',
    payload: {
      tone: 'error',
      phase: 'failed',
      surface: 'stream',
      message: 'The stream failed',
    },
  });

  assert.equal(state.getState().operationMessage?.tone, 'error');
  assert.equal(state.getState().streaming.reliabilityPhase, 'failed');
});

function versionedMessage(revision, baseRevision, title, generation = 1, workspaceId = 'workspace-1', sessionId = 'session-1') {
  return { type: baseRevision === 0 ? 'bootstrap' : 'state/patch',
    sync: { generation, revision, baseRevision, messageId: `${generation}:${revision}`, workspaceId, sessionId },
    payload: { task: { title }, memory: { workspace: { workspaceId } } } };
}

test('actual store application ACK follows receipt and rejects gaps, duplicate events and older scope snapshots', () => {
  const state = loadWorkbenchState();
  state.applyHostMessage(versionedMessage(1, 0, 'current'));
  assert.equal(state.getState().data.task.title, 'current');
  assert.deepEqual(state.postedMessages.map(message => message.payload.status), ['received', 'applied']);
  state.applyHostMessage(versionedMessage(3, 2, 'lost-base'));
  assert.equal(state.getState().data.task.title, 'current');
  assert.equal(state.getState().syncStatus, 'recovering');
  assert.equal(state.postedMessages.at(-1).payload.status, 'rejected');
  state.applyHostMessage(versionedMessage(1, 0, 'must-not-reapply'));
  assert.equal(state.getState().data.task.title, 'current');
  assert.equal(state.postedMessages.at(-1).payload.status, 'duplicate');
  state.applyHostMessage(versionedMessage(4, 0, 'new-scope', 2, 'workspace-2', 'session-2'));
  state.applyHostMessage(versionedMessage(5, 0, 'late-old-scope'));
  assert.equal(state.getState().data.task.title, 'new-scope');
  state.applyHostMessage({ type: 'state/patch', payload: { task: { title: 'legacy-bypass' } } });
  assert.equal(state.getState().data.task.title, 'new-scope');
});

test('operation messages remain scoped and an older result cannot replace a newer request for the same target', () => {
  const state = loadWorkbenchState();
  state.applyHostMessage(versionedMessage(1, 0, 'task'));
  const identity = { generation: 1, workspaceId: 'workspace-1', sessionId: 'session-1', revision: 1,
    requestId: 'first', commandId: 'trainer.resource.index', targetId: 'resource-1' };
  state.applyHostMessage({ type: 'operation/lifecycle', payload: { identity, phase: 'pending' } });
  const second = { ...identity, requestId: 'second' };
  state.applyHostMessage({ type: 'operation/lifecycle', payload: { identity: second, phase: 'pending' } });
  state.applyHostMessage({ type: 'operation/status', operation: identity, payload: { tone: 'success', message: 'old result' } });
  assert.equal(state.getState().operationMessage, undefined);
  state.applyHostMessage({ type: 'operation/status', operation: second, payload: { tone: 'success', message: 'new result' } });
  assert.equal(state.getState().operationMessage.message, 'new result');
  const shown = state.getState().operationMessage;
  state.getState().setOperationMessage({ tone: 'info', message: 'new notice during old dismissal' });
  state.getState().clearOperationMessage(shown);
  assert.equal(state.getState().operationMessage.message, 'new notice during old dismissal');
  state.applyHostMessage(versionedMessage(2, 0, 'new-scope', 2, 'workspace-2', 'session-2'));
  state.applyHostMessage({ type: 'operation/status', operation: second, payload: { tone: 'error', message: 'old-scope error' } });
  assert.notEqual(state.getState().operationMessage?.message, 'old-scope error');
});
