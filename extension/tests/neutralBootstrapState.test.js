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
          setPersistedState() {},
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
