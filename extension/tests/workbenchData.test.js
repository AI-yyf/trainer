'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const compiledRoot = process.env.TRAINER_EXTENSION_DIST_ROOT ?? path.resolve(__dirname, '..', 'dist');

const workbenchDataModulePath = path.resolve(
  compiledRoot,
  'extension',
  'src',
  'core',
  'workbenchData.js',
);
const sharedProtocolModulePath = path.resolve(
  compiledRoot,
  'shared',
  'src',
  'protocol.js',
);

const {
  applyDerivedHostState,
  createDefaultBootstrapData,
  mergeEvaluationResult,
  mergeMemorySummary,
  mapResourceTrash,
  mergePlanResult,
  mergeResourceRecords,
  mergeSessionMessage,
  failClosedWorkbenchAfterWorkspaceTransfer,
  mergeSessionStartSnapshot,
  mergeMemorySummarySnapshot,
  mergeSessionMessageSnapshot,
  mergePlanResultSnapshot,
  mergeTaskResultSnapshot,
  mergeEvaluationResultSnapshot,
  patchHostState,
  toHostBootstrapMessage,
} = require(workbenchDataModulePath);
const {
  createEmptyTrainerStreamingState,
  upsertTrainerToolActivity,
} = require(sharedProtocolModulePath);

function createWorkspaceSnapshot() {
  return {
    trusted: true,
    workspaceFolder: 'F:\\trainer',
    activeFile: 'F:\\trainer\\server\\app\\main.py',
    recentFiles: [
      'F:\\trainer\\server\\app\\main.py',
      'F:\\trainer\\server\\app\\api\\routers.py',
    ],
    recentEditedFiles: [
      'F:\\trainer\\extension\\src\\commands\\sessionCommands.ts',
    ],
  };
}

function createProvider() {
  return {
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    apiKeyRef: 'trainer.default',
    model: 'demo-model',
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: true,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
  };
}

function createSidecarStatus() {
  return {
    lifecycle: 'ready',
    host: '127.0.0.1',
    port: 34891,
    canStart: true,
  };
}

function createBootstrap() {
  return createDefaultBootstrapData(
    createWorkspaceSnapshot(),
    createProvider(),
    createSidecarStatus(),
  );
}

test('memory summary keeps a camel-case response language so the restored UI stays in the chosen language', () => {
  const patch = mergeMemorySummary(createBootstrap(), {
    memory: {
      workspace: {
        responseLanguage: 'ja-JP',
      },
    },
  });

  assert.equal(patch.memory.workspace.responseLanguage, 'ja-JP');
});

function createHostState() {
  const bootstrap = createBootstrap();
  return {
    provider: createProvider(),
    providerApiKeyConfigured: true,
    sidecar: createSidecarStatus(),
    workspace: createWorkspaceSnapshot(),
    sessionId: 'session-42',
    streamingState: createEmptyTrainerStreamingState(),
    bootstrap,
  };
}

test('createDefaultBootstrapData seeds workbench defaults from workspace and provider state', () => {
  const bootstrap = createBootstrap();

  assert.equal(bootstrap.workspaceName, 'trainer');
  assert.equal(bootstrap.connection.state, 'connected');
  assert.equal(bootstrap.connection.provider.name, 'Local Compatible');
  assert.ok(Array.isArray(bootstrap.commands));
  assert.ok(bootstrap.commands.length > 5);
  assert.deepEqual(bootstrap.conversation, []);
  assert.equal(bootstrap.liveContext.recentFiles[0], 'F:\\trainer\\server\\app\\main.py');
  assert.equal(
    bootstrap.liveContext.recentEditedFiles[0],
    'F:\\trainer\\extension\\src\\commands\\sessionCommands.ts',
  );
  assert.equal(bootstrap.profile.preferredStyle, 'auto');
  assert.equal(bootstrap.profile.answerPolicy, 'auto');
});

test('mapResourceTrash requires the requested workspace and complete unique Trash items', () => {
  const workspaceId = 'F:\\trainer\\workspace-a';
  const deletedResources = mapResourceTrash({
    workspace_id: workspaceId,
    items: [
      {
        resource_id: 'resource-1',
        title: 'Notes',
        collection_path: 'knowledge/Docs/notes.md',
        deleted_at: '2026-06-10T08:00:00Z',
        recoverable: true,
      },
    ],
  }, workspaceId);

  assert.deepEqual(deletedResources, [
    {
      resourceId: 'resource-1',
      title: 'Notes',
      collectionPath: 'knowledge/Docs/notes.md',
      deletedAt: '2026-06-10T08:00:00Z',
      recoverable: true,
    },
  ]);
  assert.deepEqual(
    mapResourceTrash(
      {
        workspaceId,
        items: [{ resourceId: 'resource-2', title: 'Camel case workspace', recoverable: false }],
      },
      workspaceId,
    ),
    [
      {
        resourceId: 'resource-2',
        title: 'Camel case workspace',
        deletedAt: undefined,
        collectionPath: undefined,
        recoverable: false,
      },
    ],
  );
  assert.throws(
    () => mapResourceTrash({ workspace_id: 'F:\\trainer\\workspace-b', items: [] }, workspaceId),
    /workspace did not match/,
  );
  assert.throws(() => mapResourceTrash({ items: [] }, workspaceId), /workspace did not match/);
  assert.throws(() => mapResourceTrash([], workspaceId), /must be an object/);
  assert.throws(
    () => mapResourceTrash({ workspace_id: workspaceId }, workspaceId),
    /did not include items/,
  );
  assert.throws(
    () => mapResourceTrash({ workspace_id: workspaceId, items: [{ title: 'No ID' }] }, workspaceId),
    /invalid item/,
  );
  assert.throws(
    () => mapResourceTrash({ workspace_id: workspaceId, items: [{ resource_id: 'partial' }] }, workspaceId),
    /invalid item/,
  );
  assert.throws(
    () => mapResourceTrash({
      workspace_id: workspaceId,
      items: [
        { resource_id: 'duplicate', title: 'First' },
        { resourceId: 'duplicate', title: 'Second' },
      ],
    }, workspaceId),
    /duplicate resource IDs/,
  );
});

test('applyDerivedHostState updates connection metadata and session label', () => {
  const bootstrap = createBootstrap();
  bootstrap.providerConfig.availableModels = ['demo-model', 'demo-model-2'];
  bootstrap.providerConfig.resolvedModel = 'demo-model';
  bootstrap.providerConfig.modelListStatus = 'ready';
  bootstrap.providerConfig.modelListDetail = 'Cached models';
  bootstrap.providerConfig.cacheFetchedAt = '2026-05-02T00:00:00.000Z';
  bootstrap.providerConfig.cacheExpiresAt = '2026-05-02T12:00:00.000Z';
  bootstrap.providerConfig.cacheSource = 'cache';

  const updated = applyDerivedHostState(
    bootstrap,
    createProvider(),
    {
      lifecycle: 'starting',
      host: '127.0.0.1',
      canStart: true,
    },
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\nested-workspace',
      activeFile: 'F:\\trainer\\nested-workspace\\main.py',
    },
    'session-42',
  );

  assert.equal(updated.workspaceName, 'nested-workspace');
  assert.equal(updated.sessionLabel, 'session-42');
  assert.equal(updated.connection.state, 'starting');
  assert.deepEqual(updated.providerConfig.availableModels, ['demo-model', 'demo-model-2']);
  assert.equal(updated.providerConfig.resolvedModel, 'demo-model');
  assert.equal(updated.providerConfig.cacheSource, 'cache');
});

test('applyDerivedHostState carries advanced provider profile fields into the webview snapshot', () => {
  const provider = {
    ...createProvider(),
    credentialMode: 'workspace_secret',
    allowedModels: ['demo-model', 'demo-model-2'],
    deniedModels: ['demo-model-beta'],
    modelAliases: {
      'coach-fast': 'demo-model',
    },
    taskBindings: {
      coach_reply: {
        alias: 'coach-fast',
        fallbackAliases: [],
        requiredCapabilities: ['chat'],
      },
    },
    embeddingModel: 'text-embedding-3-small',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
  };
  const bootstrap = createDefaultBootstrapData(
    createWorkspaceSnapshot(),
    provider,
    createSidecarStatus(),
  );

  const updated = applyDerivedHostState(
    bootstrap,
    provider,
    createSidecarStatus(),
    createWorkspaceSnapshot(),
    'session-42',
  );

  assert.equal(updated.providerConfig.credentialMode, 'workspace_secret');
  assert.deepEqual(updated.providerConfig.allowedModels, ['demo-model', 'demo-model-2']);
  assert.deepEqual(updated.providerConfig.deniedModels, ['demo-model-beta']);
  assert.deepEqual(updated.providerConfig.modelAliases, {
    'coach-fast': 'demo-model',
  });
  assert.deepEqual(updated.providerConfig.taskBindings, {
    coach_reply: {
      alias: 'coach-fast',
      fallbackAliases: [],
      requiredCapabilities: ['chat'],
    },
  });
  assert.equal(updated.providerConfig.embeddingModel, 'text-embedding-3-small');
  assert.equal(updated.providerConfig.catalogSource, 'provider_live');
  assert.equal(updated.providerConfig.cacheTtlSeconds, 43200);
});

test('applyDerivedHostState drops last provider test results from a different protocol', () => {
  const provider = {
    ...createProvider(),
    protocol: 'openai_responses',
  };
  const bootstrap = createDefaultBootstrapData(
    createWorkspaceSnapshot(),
    provider,
    createSidecarStatus(),
  );
  bootstrap.providerConfig.lastTestResult = {
    ok: true,
    status: 'connected',
    detail: 'Provider reachable. Responses probe succeeded.',
    checkedAt: '2026-07-04T00:00:00.000Z',
    providerName: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    protocol: 'anthropic_messages',
  };

  const updated = applyDerivedHostState(
    bootstrap,
    provider,
    createSidecarStatus(),
    createWorkspaceSnapshot(),
    'session-42',
  );

  assert.equal(updated.providerConfig.protocol, 'openai_responses');
  assert.equal(updated.providerConfig.lastTestResult, undefined);
});

test('host bootstrap payload carries the current recoverable streaming snapshot', () => {
  const hostState = createHostState();
  const streamingState = {
    ...createEmptyTrainerStreamingState(),
    isStreaming: true,
    streamMessageId: 'msg-stream-1',
    streamedContent: 'Checking the current workspace context...',
    agentStep: 1,
    agentActivity: upsertTrainerToolActivity([], {
      id: 'call-1',
      name: 'inspect_plan',
      status: 'running',
      args: { focus: 'message flow' },
      step: 1,
    }),
  };

  const nextHostState = patchHostState(hostState, { streamingState });
  const bootstrapMessage = toHostBootstrapMessage(nextHostState);

  assert.equal(nextHostState.streamingState.isStreaming, true);
  assert.equal(nextHostState.bootstrap.streamingState.streamMessageId, 'msg-stream-1');
  assert.equal(bootstrapMessage.payload.streamingState.streamedContent, 'Checking the current workspace context...');
  assert.equal(bootstrapMessage.payload.streamingState.agentActivity[0].name, 'inspect_plan');
  assert.deepEqual(bootstrapMessage.payload.streamingState.agentActivity[0].args, {
    focus: 'message flow',
  });
});

test('mergeSessionMessage maps first-look summaries into workspace understanding', () => {
  const bootstrap = createBootstrap();

  const result = mergeSessionMessage(bootstrap, {
    session_id: 'session-first-look',
    reply: {
      id: 'assistant-first-look',
      role: 'assistant',
      content: 'First look captured.',
    },
    snapshot: {
      messages: [],
      memory: {
        workspace_understanding: {
          repo_summary: 'Trainer workspace overview',
          entry_points: ['extension/src/app/App.tsx'],
          feature_lanes: ['Coach-first message flow'],
          risk_zones: ['Do not add a sixth navigation surface.'],
          training_opportunities: ['Keep first look inside the Coach view.'],
          resource_brief: 'Preview workspace context',
          first_look_summary: {
            folder_role: 'existing_engineering',
            project_type_guess: 'api_service',
            confidence: 0.88,
            why_this_guess: 'Detected a sidecar and extension host.',
            entry_points: ['server/app/api/routers.py'],
            directory_anchors: ['server', 'extension'],
            core_modules_or_materials: ['routers.py'],
            risk_zones: ['Keep the coach view message-first.'],
            training_opportunities: ['Use the router boundary as the first verified slice.'],
            unknowns: ['Unknown runtime constraints'],
            recommended_next_step: 'Start from the router boundary.',
            classification_method: 'heuristic',
            classified_at: '2026-04-30T09:15:00Z',
          },
        },
      },
    },
  });

  assert.equal(result.patch.memory.workspaceUnderstanding.firstLookSummary.folderRole, 'existing_engineering');
  assert.equal(result.patch.memory.workspaceUnderstanding.firstLookSummary.projectTypeGuess, 'api_service');
  assert.equal(result.patch.memory.workspaceUnderstanding.firstLookSummary.recommendedNextStep, 'Start from the router boundary.');
});

test('mergeSessionMessage maps snapshot payload into workbench views', () => {
  const bootstrap = createBootstrap();

  const result = mergeSessionMessage(
    bootstrap,
    {
      session_id: 'session-99',
      reply: {
        id: 'assistant-2',
        role: 'assistant',
        content: 'Updated reply',
        metadata: {
          coach_focus: {
            current_focus: 'Tighten the coach-first message flow',
            next_step: 'Land the continuity bridge in App.tsx',
            review_rhythm: 'Immediate revisit after the first UI slice',
            relationship_stage: 'active',
            first_turn_priority: '',
            strategy_preference_summary:
              'message flow: 2/3 useful outcomes with steady/guided/transfer/widen',
            continuity_summary: 'message flow -> plan summary -> composer tightening',
            recent_teaching_signals: [
              'Keep the visible surface narrow.',
              'Let the backend hold the complexity.',
            ],
          },
          next_step_hint: {
            title: 'Patch the continuity bridge in App.tsx',
            summary: 'Keep this slice narrow and rerun the focused UI checks.',
            recommended_action: 'task',
            focus_area: 'message flow',
            resume_thread:
              'Resume the live thread around Keep this slice narrow and rerun the focused UI checks. Next: Patch the continuity bridge in App.tsx.',
            continue_in: 'plan',
            source: 'agent_loop',
            verification: ['Run the focused UI checks'],
          },
        },
      },
      suggested_actions: ['Generate plan', 'Review current file'],
      snapshot: {
        messages: [
          {
            id: 'user-2',
            role: 'user',
            content: 'Need a stricter evaluator.',
            timestamp: '2026-04-19T08:00:00Z',
          },
          {
            id: 'assistant-2',
            role: 'assistant',
            content: 'Start with a smaller spec.',
            timestamp: '2026-04-19T08:01:00Z',
            metadata: {
              parts: [
                {
                  type: 'tool_call',
                  id: 'call-1',
                  name: 'recall_memory',
                  status: 'completed',
                  args: { focus: 'message flow' },
                },
                {
                  type: 'reasoning',
                  summary: 'Keep the visible surface narrow.',
                  redacted: true,
                },
                {
                  type: 'coach_visible_status',
                  status: 'done',
                  summary: 'Checked context before answering.',
                  detail: 'Used recall_memory before narrowing the next move.',
                  nextStep: 'Land the continuity bridge in App.tsx',
                  source: 'agent_loop',
                  toolNames: ['recall_memory'],
                  stepCount: 1,
                },
              ],
            },
          },
        ],
        profile: {
          long_term_goals: ['Build a robust trainer'],
          weekly_hours: 8,
          teaching_style: 'guided',
          answer_policy: 'balanced',
          target_project: 'Turn Trainer into a long-term unified learning coach',
          preferred_libraries: ['fastapi', 'pytest'],
          workspace: {
            learner_name: 'Mimo',
            preferred_rhythm: 'Keep each turn narrow and verifiable',
            preferred_learning_mode: 'Discuss the approach first, then land code together',
            onboarding_request: 'Make the sidebar calmer and easier to understand',
            project_context: 'A VS Code trainer extension with a React webview and FastAPI sidecar',
          },
        },
        global_plan: {
          id: 'global-plan-1',
          ownerId: 'local-trainer',
          title: 'Long-term engineering mastery',
          summary: 'Build durable capability across current and future projects.',
          goals: ['Ship reliable work across projects'],
          stages: [
            {
              id: 'global-stage-1',
              title: 'Foundation',
              goal: 'Build a verified learning habit.',
              status: 'active',
            },
          ],
          frozen: false,
          currentProjectPlanId: 'plan-99',
          currentStep: 'Use the current project to prove one transferable skill.',
          whyNow: 'The active project gives the next grounded practice loop.',
          verifyMethod: ['Run the focused checks'],
        },
        project_plan_link: {
          global_plan_id: 'global-plan-1',
          workspace_id: 'workspace-trainer',
          project_plan_id: 'plan-99',
          linked_at: '2026-07-11T00:00:00+00:00',
          updated_at: '2026-07-11T01:00:00+00:00',
        },
        current_task: {
          id: 'task-7',
          title: 'Design an evaluator',
          natural_language_goal: 'Validate the current implementation against the spec.',
          constraints: ['Avoid direct answers'],
          outputs: ['A structured evaluation report'],
        },
        evaluation: {
          summary: '2 of 3 checks passed.',
          static_checks: [{ id: 'lint', label: 'Lint', status: 'passed', detail: 'ok' }],
          dynamic_checks: [{ id: 'tests', label: 'Tests', status: 'failed', detail: '1 failing test' }],
          semantic_checks: [{ id: 'spec', label: 'Spec fit', status: 'warning', detail: 'Edge case unclear' }],
          next_step: 'Fix the failing test first.',
        },
        memory: {
          recent_summary: 'Recent focus is spec discipline.',
          weaknesses: ['Edge cases'],
          reflections: ['Improved static validation coverage'],
          subplans: [
            {
              id: 'subplan-1',
              parent_plan_id: 'plan-99',
              title: 'Persisted frontend slice',
              description: 'Keep the durable work visible in Plan.',
              stages: [
                {
                  id: 'sub-stage-1',
                  title: 'Bridge the snapshot',
                  goal: 'Map persisted subplans into the webview.',
                  status: 'active',
                },
              ],
              status: 'active',
              progress_percent: 50,
              created_at: '2026-07-11T00:00:00+00:00',
              updated_at: '2026-07-11T01:00:00+00:00',
            },
          ],
        },
        plan_runtime_status: {
          current_step: 'Patch the continuity bridge in App.tsx',
          why_now: 'The plan is currently blocked on continuity.',
          verify_method: ['Run the focused UI checks'],
          next_step_hint: {
            title: 'Patch the continuity bridge in App.tsx',
            summary: 'Keep this slice narrow and rerun the focused UI checks.',
            recommended_action: 'task',
            focus_area: 'message flow',
            resume_thread:
              'Resume the live thread around Keep this slice narrow and rerun the focused UI checks. Next: Patch the continuity bridge in App.tsx.',
            continue_in: 'plan',
            source: 'plan',
            verification: ['Run the focused UI checks'],
          },
        },
      },
    },
    'Need a stricter evaluator.',
  );

  assert.equal(result.sessionId, 'session-99');
  assert.equal(result.patch.profile.answerPolicy, 'balanced');
  assert.equal(result.patch.profile.learnerName, 'Mimo');
  assert.equal(result.patch.profile.targetProject, 'Turn Trainer into a long-term unified learning coach');
  assert.equal(result.patch.profile.preferredRhythm, 'Keep each turn narrow and verifiable');
  assert.equal(
    result.patch.profile.preferredLearningMode,
    'Discuss the approach first, then land code together',
  );
  assert.equal(
    result.patch.profile.onboardingRequest,
    'Make the sidebar calmer and easier to understand',
  );
  assert.equal(
    result.patch.profile.projectContext,
    'A VS Code trainer extension with a React webview and FastAPI sidecar',
  );
  assert.equal(result.patch.coachFocus.relationshipStage, 'active');
  assert.equal(
    result.patch.coachFocus.strategyPreferenceSummary,
    'message flow: 2/3 useful outcomes with steady/guided/transfer/widen',
  );
  assert.equal(
    result.patch.coachFocus.continuitySummary,
    'message flow -> plan summary -> composer tightening',
  );
  assert.deepEqual(result.patch.coachFocus.recentTeachingSignals, [
    'Keep the visible surface narrow.',
    'Let the backend hold the complexity.',
  ]);
  assert.equal(result.patch.task.id, 'task-7');
  assert.equal(result.patch.task.acceptanceCriteria[0], 'A structured evaluation report');
  assert.equal(result.patch.evaluation.headline, '1 of 3 checks passed');
  assert.equal(result.patch.evaluation.checks[1].status, 'fail');
  assert.equal(result.patch.evaluation.checks[2].status, 'warn');
  assert.equal(result.patch.memory.currentFocus, 'Recent focus is spec discipline.');
  assert.equal(result.patch.globalPlan.title, 'Long-term engineering mastery');
  assert.equal(result.patch.globalPlan.currentProjectPlanId, 'plan-99');
  assert.equal(result.patch.globalPlan.stages[0].status, 'active');
  assert.deepEqual(result.patch.projectPlanLink, {
    globalPlanId: 'global-plan-1',
    workspaceId: 'workspace-trainer',
    projectPlanId: 'plan-99',
    linkedAt: '2026-07-11T00:00:00+00:00',
    updatedAt: '2026-07-11T01:00:00+00:00',
  });
  assert.deepEqual(result.patch.memory.subplans, [
    {
      id: 'subplan-1',
      parentPlanId: 'plan-99',
      title: 'Persisted frontend slice',
      description: 'Keep the durable work visible in Plan.',
      stages: [
        {
          id: 'sub-stage-1',
          title: 'Bridge the snapshot',
          objective: 'Map persisted subplans into the webview.',
          status: 'active',
        },
      ],
      status: 'active',
      progressPercent: 50,
      createdAt: '2026-07-11T00:00:00+00:00',
      updatedAt: '2026-07-11T01:00:00+00:00',
    },
  ]);
  assert.equal(result.patch.conversation.length, 2);
  assert.equal(result.patch.conversation[1].parts.length, 3);
  assert.equal(result.patch.conversation[1].parts[0].type, 'tool_call');
  assert.equal(result.patch.conversation[1].parts[0].name, 'recall_memory');
  assert.equal(result.patch.conversation[1].parts[1].type, 'reasoning');
  assert.equal(result.patch.conversation[1].parts[2].type, 'coach_visible_status');
  assert.equal(result.patch.conversation[1].parts[2].status, 'done');
  assert.equal(result.patch.conversation[1].parts[2].nextStep, 'Land the continuity bridge in App.tsx');
  assert.deepEqual(result.patch.conversation[1].parts[2].toolNames, ['recall_memory']);
  assert.equal(result.patch.nextStepHint.title, 'Patch the continuity bridge in App.tsx');
  assert.equal(
    result.patch.nextStepHint.summary,
    'Keep this slice narrow and rerun the focused UI checks.',
  );
  assert.equal(result.patch.nextStepHint.recommendedAction, 'task');
  assert.equal(
    result.patch.nextStepHint.resumeThread,
    'Resume the live thread around Keep this slice narrow and rerun the focused UI checks. Next: Patch the continuity bridge in App.tsx.',
  );
  assert.equal(result.patch.nextStepHint.continueIn, 'plan');
  assert.deepEqual(result.patch.nextStepHint.verification, ['Run the focused UI checks']);
  assert.equal(result.patch.planRuntimeStatus.nextStepHint.title, 'Patch the continuity bridge in App.tsx');
  assert.equal(
    result.patch.planRuntimeStatus.nextStepHint.resumeThread,
    'Resume the live thread around Keep this slice narrow and rerun the focused UI checks. Next: Patch the continuity bridge in App.tsx.',
  );
  assert.equal(result.patch.suggestedActions[0].action, 'plan');
  assert.equal(result.patch.suggestedActions[1].action, 'review');
});

test('mapPlanRuntimeStatus snake→camel preserves verify_plan_advance for Plan paint', () => {
  const bootstrap = createBootstrap();
  const workspaceId =
    bootstrap.workspaceTrainingState?.workspaceId ||
    bootstrap.memory.workspace?.workspaceId ||
    'F:\\trainer';
  const patch = mergeMemorySummarySnapshot(
    {
      ...bootstrap,
      workspaceTrainingState: {
        ...(bootstrap.workspaceTrainingState || {}),
        workspaceId,
      },
      memory: {
        ...bootstrap.memory,
        workspace: {
          ...(bootstrap.memory.workspace || {}),
          workspaceId,
        },
      },
    },
    {
      context_id: workspaceId,
      plan_runtime_status: {
        current_step: 'Land the expiry guard',
        why_now: 'Evaluator advanced the live plan',
        verify_plan_advance: {
          advanced: true,
          what: 'Land the expiry guard',
          why: 'Evaluator-acked verify moved the live plan forward.',
          next: 'Add one regression check',
          plan_id: 'plan-verify-advance-1',
        },
      },
      memory: {
        workspace: {
          workspace_id: workspaceId,
        },
      },
    },
  );

  assert.equal(patch.planRuntimeStatus?.verifyPlanAdvance?.advanced, true);
  assert.equal(patch.planRuntimeStatus?.verifyPlanAdvance?.what, 'Land the expiry guard');
  assert.equal(
    patch.planRuntimeStatus?.verifyPlanAdvance?.why,
    'Evaluator-acked verify moved the live plan forward.',
  );
  assert.equal(patch.planRuntimeStatus?.verifyPlanAdvance?.next, 'Add one regression check');
  assert.equal(patch.planRuntimeStatus?.verifyPlanAdvance?.planId, 'plan-verify-advance-1');
});

test('mergeMemorySummary clears an explicitly removed global plan relationship', () => {
  const bootstrap = {
    ...createBootstrap(),
    globalPlan: {
      id: 'global-plan-existing',
      title: 'Existing global plan',
      summary: 'Will be cleared by the sidecar snapshot.',
      goals: [],
      stages: [],
      frozen: false,
    },
    projectPlanLink: {
      globalPlanId: 'global-plan-existing',
      workspaceId: 'workspace-old',
      projectPlanId: 'project-plan-old',
      linkedAt: '2026-07-10T00:00:00+00:00',
      updatedAt: '2026-07-10T00:00:00+00:00',
    },
  };

  const patch = mergeMemorySummary(bootstrap, {
    memory: {},
    global_plan: null,
    project_plan_link: null,
  });

  assert.equal(patch.globalPlan, undefined);
  assert.equal(patch.projectPlanLink, undefined);
});

test('mergeMemorySummary normalizes scenario and theory state from a training summary', () => {
  const patch = mergeMemorySummary(createBootstrap(), {
    memory: {
      workspace: { workspace_id: 'context-training-123' },
      scenario_lab: {
        id: 'scenario-managed-1',
        title: 'FastAPI dependency boundary',
        focus_area: 'dependency injection',
        status: 'ready',
        dependency_keys: ['fastapi'],
        related_apis: ['Depends'],
      },
      theory_drill: {
        id: 'theory-managed-1',
        title: 'Dependency review',
        focus_area: 'dependency injection',
        status: 'ready',
        summary: 'Recall why the route owns the boundary.',
        questions: [{ id: 'question-managed-1', prompt: 'Where does Depends belong?' }],
      },
    },
  });

  assert.equal(patch.workspaceTrainingState?.workspaceId, 'context-training-123');
  assert.equal(patch.workspaceTrainingState?.scenarioLab?.id, 'scenario-managed-1');
  assert.equal(patch.workspaceTrainingState?.scenarioLab?.focusArea, 'dependency injection');
  assert.deepEqual(patch.workspaceTrainingState?.scenarioLab?.dependencyKeys, ['fastapi']);
  assert.equal(patch.workspaceTrainingState?.theoryDrill?.id, 'theory-managed-1');
  assert.equal(
    patch.workspaceTrainingState?.theoryDrill?.questions?.[0]?.prompt,
    'Where does Depends belong?',
  );
});

test('mergePlanResult keeps the project plan when a global-plan route returns it in a snapshot', () => {
  const bootstrap = createBootstrap();
  bootstrap.plan = {
    id: 'project-plan-1',
    title: 'Project plan',
    frozen: false,
    cadence: '3 hours/week',
    summary: 'Preserve this project plan while global context changes.',
    stages: [
      { id: 'stage-1', title: 'Current stage', objective: 'Keep the current lane.', status: 'active' },
    ],
  };

  const patch = mergePlanResult(bootstrap, {
    global_plan: {
      id: 'global-plan-1',
      title: 'Global plan',
      summary: 'Cross-project capability.',
      goals: ['Build reliable software'],
      stages: [],
      frozen: false,
    },
    project_plan_link: null,
    snapshot: {
      plan: {
        id: 'project-plan-1',
        title: 'Project plan',
        frozen: false,
        cadence: '3 hours/week',
        summary: 'Preserve this project plan while global context changes.',
        stages: [
          { id: 'stage-1', title: 'Current stage', objective: 'Keep the current lane.', status: 'active' },
        ],
      },
    },
  });

  assert.equal(patch.plan.id, 'project-plan-1');
  assert.equal(patch.plan.stages.length, 1);
  assert.equal(patch.globalPlan.id, 'global-plan-1');
  assert.equal(patch.projectPlanLink, undefined);
});

test('mergeSessionMessage preserves structured suggested action ids and actions', () => {
  const bootstrap = createBootstrap();

  const result = mergeSessionMessage(
    bootstrap,
    {
      session_id: 'session-structured-actions',
      reply: {
        id: 'assistant-structured',
        role: 'assistant',
        content: 'Pick the next move.',
      },
      suggested_actions: [
        {
          id: 'coach-next',
          label: '给我更小的下一步',
          action: 'hint',
          rationale: 'Keep the learner moving with a smaller nudge.',
          artifact_kind: 'idea_implementation',
          prompt: '结合当前代码，给我更小的下一步。',
          focus_area: 'message flow',
        },
        { id: 'coach-review-again', label: '改完后重新评审', action: 'retry_review' },
      ],
      snapshot: {
        messages: [],
      },
    },
    'What should I do next?',
  );

  assert.equal(result.patch.suggestedActions[0].id, 'coach-next');
  assert.equal(result.patch.suggestedActions[0].action, 'hint');
  assert.equal(result.patch.suggestedActions[0].artifactKind, 'idea_implementation');
  assert.equal(result.patch.suggestedActions[0].focusArea, 'message flow');
  assert.equal(result.patch.suggestedActions[0].prompt, '结合当前代码，给我更小的下一步。');
  assert.equal(result.patch.suggestedActions[1].id, 'coach-review-again');
  assert.equal(result.patch.suggestedActions[1].action, 'retry_review');
});

test('mergeSessionMessage preserves context attachments from message metadata', () => {
  const bootstrap = createBootstrap();

  const result = mergeSessionMessage(
    bootstrap,
    {
      session_id: 'session-100',
      reply: {
        id: 'assistant-3',
        role: 'assistant',
        content: 'I turned your goal into a task.',
      },
      snapshot: {
        messages: [
          {
            id: 'user-3',
            role: 'user',
            content: 'Turn this into a task.',
            timestamp: '2026-04-19T08:02:00Z',
            metadata: {
              intent: 'task',
              current_file: 'F:\\trainer\\server\\app\\api\\routers.py',
              content_strategy: 'selection-window',
              content_line_span: '10-40',
              selection_range: '10:1-20:4',
              diagnostics_count: 2,
              related_files: [
                { path: 'F:\\trainer\\server\\app\\llm\\prompts.py', reason: 'import' },
              ],
              related_files_count: 1,
              recent_edited_files: [
                'F:\\trainer\\extension\\src\\commands\\sessionCommands.ts',
              ],
              context_note: 'Attached python file context',
            },
          },
          {
            id: 'assistant-3',
            role: 'assistant',
            content: 'I turned your goal into a task.',
            timestamp: '2026-04-19T08:03:00Z',
            metadata: {
              artifacts: [{ kind: 'task', title: 'Design an evaluator', bullets: ['Avoid direct answers'] }],
            },
          },
        ],
      },
    },
    'Turn this into a task.',
  );

  assert.equal(result.patch.conversation[0].attachments[0].label, 'Intent');
  assert.equal(result.patch.conversation[0].attachments[0].value, 'task');
  assert.equal(
    result.patch.conversation[0].attachments.find((attachment) => attachment.label === 'Selection').value,
    '10:1-20:4',
  );
  assert.equal(
    result.patch.conversation[0].attachments.find((attachment) => attachment.label === 'File').value,
    'routers.py',
  );
  assert.equal(
    result.patch.conversation[0].attachments.find((attachment) => attachment.label === 'Strategy').value,
    'selection-window',
  );
  assert.equal(result.patch.conversation[0].contextNote, 'Attached python file context');
  assert.equal(
    result.patch.conversation[0].attachments.find((attachment) => attachment.label === 'Related').value,
    'prompts.py',
  );
  assert.equal(
    result.patch.conversation[0].attachments.find((attachment) => attachment.label === 'Related count').value,
    '1',
  );
  assert.equal(result.patch.conversation[1].artifacts[0].title, 'Design an evaluator');
  assert.equal(result.patch.conversation[1].artifacts[0].bullets[0], 'Avoid direct answers');
});

test('mergeSessionMessage localizes context attachment labels for Chinese metadata', () => {
  const bootstrap = createBootstrap();

  const result = mergeSessionMessage(
    bootstrap,
    {
      session_id: 'session-zh',
      reply: {
        id: 'assistant-zh',
        role: 'assistant',
        content: '我已经整理好了。',
      },
      snapshot: {
        messages: [
          {
            id: 'user-zh',
            role: 'user',
            content: '帮我看下这个实现。',
            timestamp: '2026-04-19T09:10:00Z',
            metadata: {
              intent: 'review',
              response_language: 'zh-CN',
              answer_mode: 'coach-first',
              current_file: 'F:\\trainer\\extension\\src\\core\\workbenchData.ts',
              content_strategy: 'selection-window',
              diagnostics_count: 3,
              related_files: [{ path: 'F:\\trainer\\server\\app\\api\\routers.py' }],
            },
          },
        ],
      },
    },
    '帮我看下这个实现。',
  );

  const attachments = result.patch.conversation[0].attachments;
  assert.equal(attachments.find((attachment) => attachment.label === '意图').value, '评审');
  assert.equal(attachments.find((attachment) => attachment.label === '方式').value, '引导');
  assert.equal(attachments.find((attachment) => attachment.label === '文件').value, 'workbenchData.ts');
  assert.equal(attachments.find((attachment) => attachment.label === '策略').value, '围绕选区');
  assert.equal(attachments.find((attachment) => attachment.label === '诊断').value, '3');
  assert.equal(attachments.find((attachment) => attachment.label === '相关文件').value, 'routers.py');
});

test('mergeSessionMessage preserves image delivery truth in support without adding extra attachment clutter', () => {
  const bootstrap = createBootstrap();

  const result = mergeSessionMessage(
    bootstrap,
    {
      session_id: 'session-image-truth',
      reply: {
        id: 'assistant-image-truth',
        role: 'assistant',
        content: 'I can still coach from the screenshot context.',
      },
      snapshot: {
        messages: [
          {
            id: 'user-image-truth',
            role: 'user',
            content: 'Please inspect this screenshot.',
            timestamp: '2026-04-19T09:20:00Z',
            metadata: {
              response_language: 'en-US',
              attachments_present: true,
              image_attachment_count: 1,
              attachments_delivered_to_model: false,
              attachments_delivery_reason: 'vision_not_available',
              support: {
                preview: 'Attached image status',
                lines: [
                  '1 image attachment did not reach the model. The current provider turn is not vision-ready, so images were not forwarded to the model.',
                ],
              },
            },
          },
        ],
      },
    },
    'Please inspect this screenshot.',
  );

  const message = result.patch.conversation[0];
  assert.equal(message.attachments, undefined);
  assert.equal(message.support.preview, 'Attached image status');
  assert.deepEqual(message.support.lines, [
    '1 image attachment did not reach the model. The current provider turn is not vision-ready, so images were not forwarded to the model.',
  ]);
});

test('mergeSessionMessage preserves extended coach-first artifact kinds', () => {
  const bootstrap = createBootstrap();

  const result = mergeSessionMessage(
    bootstrap,
    {
      session_id: 'session-artifacts',
      reply: {
        id: 'assistant-extended',
        role: 'assistant',
        content: '我已经把实现路径整理好了。',
      },
      snapshot: {
        messages: [
          {
            id: 'assistant-extended',
            role: 'assistant',
            content: '我已经把实现路径整理好了。',
            timestamp: '2026-04-19T10:00:00Z',
            metadata: {
              artifacts: [
                {
                  kind: 'idea_implementation',
                  title: '实现路径',
                  summary: '先做最小切片。',
                  bullets: ['先落第一层', '马上验证'],
                  recommended_action: 'task',
                  rationale: '先把交互收紧成一条最薄路径。',
                  focus_area: 'composer',
                  verification: ['发送后还能直接理解下一步'],
                },
                {
                  kind: 'next_step',
                  title: '现在先做',
                  summary: '从当前边界开始。',
                  bullets: ['只改一层'],
                  recommended_action: 'review',
                },
              ],
            },
          },
        ],
      },
    },
    '请指导我实现这个 idea',
  );

  assert.equal(result.patch.conversation[0].artifacts[0].kind, 'idea_implementation');
  assert.equal(result.patch.conversation[0].artifacts[0].title, '实现路径');
  assert.equal(result.patch.conversation[0].artifacts[0].recommendedAction, 'task');
  assert.equal(result.patch.conversation[0].artifacts[0].focusArea, 'composer');
  assert.equal(result.patch.conversation[0].artifacts[0].verification[0], '发送后还能直接理解下一步');
  assert.equal(result.patch.conversation[0].artifacts[1].kind, 'next_step');
  assert.equal(result.patch.conversation[0].artifacts[1].recommendedAction, 'review');
});

test('mergeMemorySummary prefers memory resources and normalizes resource state', () => {
  const bootstrap = createBootstrap();

  const patch = mergeMemorySummary(bootstrap, {
    profile: {
      long_term_goal: 'Train against specifications',
      weekly_hours: 5,
      teaching_style: 'guided',
      answer_policy: 'direct',
      target_project: 'Specification-first trainer',
      preferred_libraries: ['fastapi'],
      workspace: {
        learner_name: 'Ava',
        preferred_rhythm: 'Ship one thin slice per round',
        preferred_learning_mode: 'Coach me by guiding before revealing the answer',
        onboarding_request: 'Stay close to the current codebase',
        project_context: 'Existing trainer sidecar and webview',
      },
    },
    plan: {
      id: 'plan-2',
      title: 'Spec-first practice',
      frozen: true,
      weekly_cadence: '5 hours / week',
      objective: 'Practice structured evaluation.',
      phases: [{ title: 'Phase 1', objective: 'Learn specs', completion_signal: 'First passing report' }],
    },
    memory: {
      recent_summary: 'Resource grounding improved.',
      weaknesses: ['Boundary conditions'],
      reflections: ['Indexed a PDF spec successfully', 'Generated a better task'],
      resources: [
        {
          id: 'resource-1',
          kind: 'url',
          name: 'Spec reference',
          source: 'https://example.com/spec',
          summary: 'Remote spec',
          parse_status: 'parsed',
          index_status: 'indexed',
        },
      ],
    },
  });

  assert.equal(patch.profile.answerPolicy, 'direct');
  assert.equal(patch.profile.learnerName, 'Ava');
  assert.equal(patch.profile.targetProject, 'Specification-first trainer');
  assert.equal(patch.profile.preferredRhythm, 'Ship one thin slice per round');
  assert.equal(
    patch.profile.preferredLearningMode,
    'Coach me by guiding before revealing the answer',
  );
  assert.equal(patch.profile.onboardingRequest, 'Stay close to the current codebase');
  assert.equal(patch.profile.projectContext, 'Existing trainer sidecar and webview');
  assert.equal(patch.plan.id, 'plan-2');
  assert.equal(patch.plan.cadence, '5 hours / week');
  assert.equal(patch.plan.stages[0].status, 'queued');
  assert.equal(patch.memory.weakSpots[0], 'Boundary conditions');
  assert.equal(patch.resources[0].kind, 'url');
  assert.equal(patch.resources[0].status, 'ready');
});

test('mergeMemorySummary preserves snake-case resource workspace metadata', () => {
  const patch = mergeMemorySummary(createBootstrap(), {
    memory: {
      resources: [
        {
          id: 'resource-nested',
          name: 'coach-patterns.md',
          kind: 'markdown',
          source: 'F:\\trainer\\docs\\coach-patterns.md',
          collection_path: 'knowledge/coach/patterns/coach-patterns.md',
          collection_root: 'F:\\trainer\\docs',
          canonical_source: 'workspace://knowledge/coach/patterns/coach-patterns.md',
          source_items: ['F:\\trainer\\docs\\coach-patterns.md'],
          tags: ['coach', 'patterns'],
          warnings: ['review before reuse'],
          source_type: 'workspace_file',
          file_type: 'markdown',
          project_scope: 'knowledge',
          trust_state: 'trusted',
          trust_score: 0.94,
          freshness: 'fresh',
          index_state: 'indexed',
          citation_id: 'citation:coach-patterns',
          preview_tier: 'rich',
          preview_kind: 'markdown',
          rank_score: 0.91,
          rank_reasons: ['title match'],
          match_summary: 'Coach pattern evidence',
          can_inject_training_card: true,
          quality_flags: ['curated'],
          sandbox_path: 'F:\\trainer\\.trainer\\sandbox\\knowledge\\coach\\patterns\\coach-patterns.md',
          sandbox_origin: 'managed',
          sandbox_synced_at: '2026-07-11T12:00:00Z',
          sandbox_dirty: false,
          extracted_artifact_path: 'F:\\trainer\\.trainer\\artifacts\\coach-patterns.md',
          updated_at: '2026-07-11T12:00:01Z',
          summary: 'Reusable coach prompts',
          parse_status: 'parsed',
          index_status: 'indexed',
        },
      ],
    },
  });

  assert.deepEqual(patch.resources[0], {
    id: 'resource-nested',
    title: 'coach-patterns.md',
    kind: 'markdown',
    status: 'ready',
    summary: 'Reusable coach prompts',
    source: 'F:\\trainer\\docs\\coach-patterns.md',
    collectionPath: 'knowledge/coach/patterns/coach-patterns.md',
    collectionRoot: 'F:\\trainer\\docs',
    canonicalSource: 'workspace://knowledge/coach/patterns/coach-patterns.md',
    sourceItems: ['F:\\trainer\\docs\\coach-patterns.md'],
    tags: ['coach', 'patterns'],
    warnings: ['review before reuse'],
    sourceType: 'workspace_file',
    fileType: 'markdown',
    projectScope: 'knowledge',
    trustState: 'trusted',
    trustScore: 0.94,
    freshness: 'fresh',
    indexState: 'indexed',
    citationId: 'citation:coach-patterns',
    previewTier: 'rich',
    previewKind: 'markdown',
    rankScore: 0.91,
    rankReasons: ['title match'],
    matchSummary: 'Coach pattern evidence',
    canInjectTrainingCard: true,
    qualityFlags: ['curated'],
    sandboxPath: 'F:\\trainer\\.trainer\\sandbox\\knowledge\\coach\\patterns\\coach-patterns.md',
    sandboxOrigin: 'managed',
    sandboxSyncedAt: '2026-07-11T12:00:00Z',
    sandboxDirty: false,
    extractedArtifactPath: 'F:\\trainer\\.trainer\\artifacts\\coach-patterns.md',
    updatedAt: '2026-07-11T12:00:01Z',
  });
});

test('mergeMemorySummary maps explicit memory share grants without accepting unknown categories', () => {
  const bootstrap = createBootstrap();

  const patch = mergeMemorySummary(bootstrap, {
    memory: {
      memory_share_grants: [
        {
          source_workspace_id: 'F:\\trainer\\project-a',
          target_workspace_id: 'F:\\trainer\\project-b',
          categories: ['preferences', 'mastery'],
          created_at: '2026-07-11T09:00:00Z',
          updated_at: '2026-07-11T09:00:00Z',
        },
        {
          source_workspace_id: 'F:\\trainer\\project-c',
          target_workspace_id: 'F:\\trainer\\project-b',
          categories: ['resources'],
        },
      ],
    },
  });

  assert.deepEqual(patch.memory.memoryShareGrants, [
    {
      sourceWorkspaceId: 'F:\\trainer\\project-a',
      targetWorkspaceId: 'F:\\trainer\\project-b',
      categories: ['preferences', 'mastery'],
      createdAt: '2026-07-11T09:00:00Z',
      updatedAt: '2026-07-11T09:00:00Z',
    },
  ]);
});

test('mergeMemorySummary preserves sandbox state across summary refreshes', () => {
  const bootstrap = createBootstrap();
  bootstrap.memory = {
    ...bootstrap.memory,
    selectedResourceDetail: {
      id: 'resource-sandbox',
      title: 'workbenchData.ts',
      kind: 'code',
      status: 'ready',
      summary: 'Sandbox boundary sample',
      source: 'F:\\trainer\\extension\\src\\core\\workbenchData.ts',
      sandboxPath: 'F:\\trainer\\extension\\src\\core\\workbenchData.ts',
      tags: ['sandbox', 'authority'],
    },
    sandboxPreview: {
      path: 'F:\\trainer\\extension\\src\\core\\workbenchData.ts',
      title: 'workbenchData.ts',
      previewTier: 'rich',
      previewKind: 'code',
      excerpt: 'Sandbox boundary sample',
      assetUri: 'file:///F:/trainer/extension/src/core/workbenchData.ts',
    },
    sandboxState: {
      rootPath: 'F:\\trainer',
      sandboxRootPath: 'F:\\trainer\\.trainer-sandbox',
      workspaceRootPath: 'F:\\trainer',
      activeWorkspaceRoot: 'F:\\trainer',
      trashRootPath: 'F:\\trainer\\.trainer-trash',
      ready: true,
      lastUpdatedAt: '2026-04-30T09:18:00Z',
      authority: {
        activeWorkspaceRoot: 'F:\\trainer',
        rootUri: 'file:///F:/trainer',
        authoritySource: 'workspace_authority_service',
        permissionLevel: 'read_write',
        permissionLabel: 'Read / write',
        mountedSources: ['workspace.json', 'AGENT_POLICY.md'],
        trashRoot: 'F:\\trainer\\.trainer-trash',
      },
    },
  };

  const patch = mergeMemorySummary(bootstrap, {
    memory: {
      recent_summary: 'Refreshed summary without sandbox fields.',
      weaknesses: ['Boundary conditions'],
      reflections: ['Updated profile summary'],
    },
  });

  assert.equal(patch.memory.selectedResourceDetail?.title, 'workbenchData.ts');
  assert.equal(patch.memory.sandboxPreview?.path, 'F:\\trainer\\extension\\src\\core\\workbenchData.ts');
  assert.equal(patch.memory.sandboxState?.rootPath, 'F:\\trainer');
  assert.equal(patch.memory.sandboxState?.authority?.permissionLabel, 'Read / write');
  assert.deepEqual(patch.memory.sandboxState?.authority?.mountedSources, ['workspace.json', 'AGENT_POLICY.md']);
  assert.equal(
    patch.memory.sandboxState?.authority?.nextSafeAction,
    'Start with the thinnest edit, then verify immediately that it actually holds.',
  );
});

test('mergeResourceRecords updates existing resources in place and preserves unrelated ones', () => {
  const bootstrap = createBootstrap();
  bootstrap.resources = [
    {
      id: 'resource-existing',
      title: 'Existing',
      kind: 'markdown',
      status: 'indexing',
      summary: 'Old summary',
      source: 'F:\\trainer\\notes.md',
    },
    {
      id: 'resource-other',
      title: 'Other',
      kind: 'text',
      status: 'ready',
      summary: 'Other summary',
      source: 'F:\\trainer\\todo.txt',
    },
  ];

  const patch = mergeResourceRecords(bootstrap, {
    id: 'resource-existing',
    kind: 'markdown',
    name: 'Existing',
    source: 'F:\\trainer\\notes.md',
    summary: 'New summary',
    parse_status: 'parsed',
    index_status: 'indexed',
  });

  assert.equal(patch.resources.length, 2);
  assert.equal(patch.resources[0].id, 'resource-existing');
  assert.equal(patch.resources[0].status, 'ready');
  assert.equal(patch.resources[0].summary, 'New summary');
  assert.equal(patch.resources[1].id, 'resource-other');
});

test('mergeResourceRecords preserves camelCase resource workspace metadata across partial uploads', () => {
  const bootstrap = createBootstrap();
  const firstPatch = mergeResourceRecords(bootstrap, {
    id: 'resource-upload',
    title: 'upload-patterns.md',
    kind: 'markdown',
    source: 'F:\\trainer\\imports\\upload-patterns.md',
    collectionPath: 'knowledge/uploads/upload-patterns.md',
    collectionRoot: 'F:\\trainer\\imports',
    canonicalSource: 'workspace://knowledge/uploads/upload-patterns.md',
    sourceItems: ['F:\\trainer\\imports\\upload-patterns.md'],
    tags: ['upload'],
    warnings: ['needs indexing review'],
    sourceType: 'uploaded_file',
    fileType: 'markdown',
    projectScope: 'knowledge',
    trustState: 'reviewed',
    trustScore: 0.82,
    freshness: 'fresh',
    indexState: 'indexed',
    citationId: 'citation:upload-patterns',
    previewTier: 'converted',
    previewKind: 'markdown',
    rankScore: 0.77,
    rankReasons: ['recent upload'],
    matchSummary: 'Imported resource',
    canInjectTrainingCard: false,
    qualityFlags: ['user_uploaded'],
    sandboxPath: 'F:\\trainer\\.trainer\\sandbox\\knowledge\\uploads\\upload-patterns.md',
    sandboxOrigin: 'upload',
    sandboxSyncedAt: '2026-07-11T12:01:00Z',
    sandboxDirty: false,
    extractedArtifactPath: 'F:\\trainer\\.trainer\\artifacts\\upload-patterns.md',
    updatedAt: '2026-07-11T12:01:01Z',
    summary: 'Imported reusable patterns',
    parseStatus: 'parsed',
    indexStatus: 'indexed',
  });

  const resource = firstPatch.resources[0];
  assert.equal(resource.collectionPath, 'knowledge/uploads/upload-patterns.md');
  assert.equal(resource.collectionRoot, 'F:\\trainer\\imports');
  assert.equal(resource.sourceType, 'uploaded_file');
  assert.equal(resource.sandboxPath, 'F:\\trainer\\.trainer\\sandbox\\knowledge\\uploads\\upload-patterns.md');
  assert.equal(resource.sandboxDirty, false);
  assert.deepEqual(resource.sourceItems, ['F:\\trainer\\imports\\upload-patterns.md']);
  assert.deepEqual(resource.tags, ['upload']);
  assert.deepEqual(resource.warnings, ['needs indexing review']);

  const secondPatch = mergeResourceRecords(
    { ...bootstrap, resources: firstPatch.resources },
    {
      id: 'resource-upload',
      title: 'upload-patterns.md',
      kind: 'markdown',
      source: 'F:\\trainer\\imports\\upload-patterns.md',
      summary: 'Imported reusable patterns, indexed',
      parseStatus: 'parsed',
      indexStatus: 'indexed',
    },
  );

  assert.equal(secondPatch.resources[0].summary, 'Imported reusable patterns, indexed');
  assert.equal(secondPatch.resources[0].collectionPath, 'knowledge/uploads/upload-patterns.md');
  assert.equal(secondPatch.resources[0].collectionRoot, 'F:\\trainer\\imports');
  assert.equal(secondPatch.resources[0].sandboxPath, resource.sandboxPath);
  assert.equal(secondPatch.resources[0].extractedArtifactPath, resource.extractedArtifactPath);
  assert.deepEqual(secondPatch.resources[0].sourceItems, resource.sourceItems);
  assert.deepEqual(secondPatch.resources[0].tags, resource.tags);
  assert.deepEqual(secondPatch.resources[0].warnings, resource.warnings);
});

test('mergeMemorySummary derives trust state for legacy resource snapshots', () => {
  const bootstrap = createBootstrap();
  const trusted = mergeMemorySummary(bootstrap, {
    memory: {
      resources: [
        {
          id: 'resource-legacy-trusted',
          kind: 'markdown',
          name: 'Legacy trusted notes',
          source: 'F:\\trainer\\notes.md',
          parse_status: 'parsed',
          index_status: 'indexed',
          trust_score: 0.84,
          freshness: 'fresh',
          quality_flags: [],
        },
      ],
    },
  });
  const flagged = mergeMemorySummary(bootstrap, {
    memory: {
      resources: [
        {
          id: 'resource-legacy-flagged',
          kind: 'markdown',
          name: 'Legacy flagged notes',
          source: 'F:\\trainer\\notes.md',
          parse_status: 'parsed',
          index_status: 'indexed',
          trust_score: 0.84,
          freshness: 'fresh',
          quality_flags: ['thin_content'],
        },
      ],
    },
  });

  assert.equal(trusted.resources[0].trustState, 'trusted');
  assert.equal(flagged.resources[0].trustState, 'unknown');
});

test('mergeEvaluationResult falls back to pending for unknown check states', () => {
  const bootstrap = createBootstrap();

  const patch = mergeEvaluationResult(bootstrap, {
    summary: 'Evaluation completed with mixed signal.',
    static_checks: [{ id: 'a', label: 'A', status: 'mystery', detail: 'unknown' }],
    dynamic_checks: [{ id: 'b', label: 'B', status: 'passed', detail: 'ok' }],
    semantic_checks: [],
    next_step: 'Review the odd status mapping.',
  });

  assert.equal(patch.evaluation.headline, '1 of 2 checks passed');
  assert.equal(patch.evaluation.checks[0].status, 'pending');
  assert.equal(patch.evaluation.checks[1].status, 'pass');
  assert.equal(patch.evaluation.nextStep, 'Review the odd status mapping.');
});

test('mergeMemorySummary drops workspace A recovery leftover when switching to workspace B', () => {
  const bootstrap = createBootstrap();
  bootstrap.workspaceTrainingState = {
    workspaceId: 'workspace-a',
    selectedCardTitle: 'Review the refresh path',
    selectedCardId: 'card-leftover-a',
    selectedCardType: 'practice',
    selectedCardStatus: 'in_progress',
    latestTrainingHandoff: {
      workspaceId: 'workspace-a',
      cardTitle: 'Review the refresh path',
    },
    latestTrainingNextHop: {
      workspaceId: 'workspace-a',
      title: 'Review the refresh path',
      cardTitle: 'Review the refresh path',
    },
    dueReviews: [
      {
        concept: 'Keep the leftover A due review',
        reason: 'A leftover review item',
        source: 'plan',
        severity: 'high',
      },
    ],
    latestTrainingSubmode: 'practice',
    latestLearningFocusArea: 'Keep the leftover A learning focus',
    latestLearningFollowup: 'Keep the leftover A learning followup',
    latestLearningVerifiedResult: 'Keep the leftover A verified result',
    latestLearningBlocker: 'Keep the leftover A learning blocker',
    latestLearningAbandonReason: 'Keep the leftover A abandon reason',
    latestLearningPartialProgress: 'Keep the leftover A partial progress',
    reviewArtifact: {
      title: 'Keep the leftover A review artifact',
      focusArea: 'Keep the leftover A review focus',
      summary: 'A leftover review artifact',
    },
    scenarioLab: {
      title: 'Keep the leftover A scenario lab',
      focusArea: 'Keep the leftover A scenario focus',
      successSignal: 'A leftover scenario signal',
    },
    theoryDrill: {
      title: 'Keep the leftover A theory drill',
      focusArea: 'Keep the leftover A drill focus',
      summary: 'A leftover theory drill',
    },
    trainingCardCandidates: [
      {
        cardId: 'card-leftover-a',
        type: 'practice',
        title: 'Keep the leftover A training card',
      },
    ],
    activeTrainingCardRouting: {
      selectedCardId: 'card-leftover-a',
      whyThisCard: 'Keep the leftover A routing why',
      nextAfterCompletion: 'Keep the leftover A routing next',
      selectedCard: {
        cardId: 'card-leftover-a',
        type: 'practice',
        title: 'Keep the leftover A routing card',
      },
    },
    trainingEventLedger: [
      {
        eventId: 'event-leftover-a',
        eventType: 'card_selected',
        selectedCardId: 'card-leftover-a',
        selectedCardTitle: 'Keep the leftover A ledger card',
        whyThisCard: 'Keep the leftover A ledger why',
      },
    ],
    latestTransferState: {
      concept: 'Keep the leftover A transfer skill',
      state: 'awaiting_second_scene',
      sceneCount: 1,
      workspaceIds: ['workspace-a'],
      sceneKeys: ['default'],
      why: 'Keep the leftover A transfer why',
      next: 'Keep the leftover A transfer next',
    },
    latestTrainingReliability: {
      requestId: 'request-leftover-a',
      commandId: 'trainer.training.save',
      cardId: 'card-leftover-a',
      phase: 'succeeded',
      outcome: 'success',
      revision: 1,
    },
  };
  bootstrap.memory.workspaceUnderstanding = {
    repoSummary: 'Keep the leftover A repo summary',
    entryPoints: ['Keep the leftover A entry'],
    featureLanes: [],
    riskZones: [],
    trainingOpportunities: [],
    resourceBrief: 'Keep the leftover A resource brief',
    firstLookSummary: {
      folderRole: 'existing_engineering',
      projectTypeGuess: 'api_service',
      confidence: 0.9,
      whyThisGuess: 'Keep the leftover A first-look why',
      entryPoints: ['Keep the leftover A first-look entry'],
      directoryAnchors: [],
      coreModulesOrMaterials: [],
      riskZones: [],
      trainingOpportunities: [],
      unknowns: [],
      recommendedNextStep: 'Keep the leftover A first-look next',
      classificationMethod: 'heuristic',
      classifiedAt: '2026-08-25T00:00:00.000Z',
    },
    updatedAt: '2026-08-25T00:00:00.000Z',
  };
  bootstrap.memory.evidenceQueue = {
    pending: [
      {
        id: 'evidence-leftover-a',
        workspaceId: 'workspace-a',
        summary: 'Keep the leftover A pending evidence',
        source: 'card_result',
        concepts: [],
        outcome: 'partial',
        confidence: 0.8,
        adopted: false,
      },
    ],
    deferred: [
      {
        id: 'evidence-deferred-a',
        workspaceId: 'workspace-a',
        summary: 'Keep the leftover A deferred evidence',
        source: 'card_result',
        concepts: [],
        outcome: 'partial',
        confidence: 0.5,
      },
    ],
    adopted: [
      {
        id: 'evidence-adopted-a',
        workspaceId: 'workspace-a',
        summary: 'Keep the leftover A adopted evidence',
        source: 'card_result',
        concepts: [],
        outcome: 'success',
        confidence: 1,
        adopted: true,
      },
    ],
    rejected: [],
    history: [],
    totalCount: 3,
  };
  bootstrap.memory.sandboxPreview = {
    path: 'F:\\workspace-a\\notes.md',
    title: 'Keep the leftover A sandbox preview',
    excerpt: 'A leftover sandbox preview',
  };
  bootstrap.memory.sandboxState = {
    rootPath: 'F:\\workspace-a',
    selectedPath: 'F:\\workspace-a\\notes.md',
    ready: true,
  };
  bootstrap.memory.dueReviews = [
    {
      concept: 'Keep the leftover A due review',
      reason: 'A leftover review item',
      source: 'plan',
      severity: 'high',
    },
  ];
  bootstrap.memory.dueReviewCount = 1;
  bootstrap.memory.workspace = {
    ...bootstrap.memory.workspace,
    workspaceId: 'workspace-a',
    latestLearningFocusArea: 'Keep the leftover A learning focus',
    latestTransferState: {
      concept: 'Keep the leftover A transfer skill',
      state: 'awaiting_second_scene',
      sceneCount: 1,
      workspaceIds: ['workspace-a'],
      sceneKeys: ['default'],
      why: 'Keep the leftover A transfer why',
      next: 'Keep the leftover A transfer next',
    },
    latestPlanRuntime: {
      revision: 1,
      workspaceId: 'workspace-a',
      planId: 'plan-a',
      currentStep: 'Stay on A',
      frozen: false,
      verifyMethod: [],
    },
    latestProviderCapability: {
      revision: 1,
      workspaceId: 'workspace-a',
      providerProfileId: 'profile-a',
      providerName: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
      ok: true,
      checkedAt: '2026-08-25T00:00:00.000Z',
      toolsReady: false,
      toolProbeStatus: 'unverified',
      streamingReady: false,
      streamProbeStatus: 'unverified',
      visionReady: false,
      visionProbeStatus: 'unverified',
      thinkingReady: false,
      thinkingProbeStatus: 'unverified',
      capabilityEvidence: [],
    },
    latestStreamingCheckpoint: {
      revision: 1,
      workspaceId: 'workspace-a',
      providerProfileId: 'profile-a',
      requestId: 'stream-a',
      phase: 'interrupted',
    },
    trainerWorkspace: {
      status: 'managed',
      rootPath: 'F:\\workspace-a',
      projectId: 'project-leftover-a',
      projectName: 'Keep the leftover A project',
      projectPath: 'F:\\workspace-a',
      identityStatus: 'verified',
    },
    resourceSandbox: {
      configuredPath: 'F:\\workspace-a\\.trainer-resources',
      effectivePath: 'F:\\workspace-a\\.trainer-resources',
      defaultPath: 'F:\\workspace-a\\.trainer-resources',
      source: 'custom',
      status: 'ready',
    },
    projectContext: 'Keep the leftover A project context',
    learnerName: 'Keep the leftover A learner',
    preferredRhythm: 'Keep the leftover A rhythm',
    preferredLearningMode: 'Keep the leftover A learning mode',
    onboardingRequest: 'Keep the leftover A onboarding',
    followCurrentFile: true,
    contextDetail: 'full',
    includeCurrentFile: true,
    includeSelection: true,
    includeDiagnostics: true,
    includeRelatedFiles: true,
    responseLanguage: 'ja-JP',
    answerMode: 'direct',
    coachDefaults: {
      memoryScope: 'personal',
      workingSetMode: 'broad',
      reviewCadence: 'active',
      reviewReminderMode: 'ahead',
      workspaceMemoryToggles: {
        decisions: false,
        patterns: false,
        resources: false,
      },
    },
  };
  bootstrap.profile = {
    ...bootstrap.profile,
    projectContext: 'Keep the leftover A project context',
    learnerName: 'Keep the leftover A learner',
    preferredRhythm: 'Keep the leftover A rhythm',
    preferredLearningMode: 'Keep the leftover A learning mode',
    onboardingRequest: 'Keep the leftover A onboarding',
    targetProject: 'Keep the leftover A project context',
  };
  bootstrap.providerConfig.lastTestResult = {
    ok: true,
    status: 'connected',
    detail: 'Workspace A last-test',
    checkedAt: '2026-08-25T00:00:00.000Z',
    workspaceId: 'workspace-a',
    profileId: 'profile-a',
    providerName: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
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
  bootstrap.resources = [
    {
      id: 'resource-a',
      title: 'Workspace A notes',
      kind: 'markdown',
      status: 'ready',
      summary: 'A leftover resource',
    },
  ];
  bootstrap.memory.selectedResourceDetail = {
    id: 'resource-a',
    title: 'Workspace A notes',
    kind: 'markdown',
    status: 'ready',
    summary: 'A leftover resource',
  };
  bootstrap.memory.workspace = {
    ...bootstrap.memory.workspace,
    resourceSearchMode: 'semantic',
  };
  bootstrap.coachFocus = {
    currentFocus: 'Keep the leftover A coach focus',
    activeTask: 'Keep the current stage',
    nextStep: 'Stay on leftover A',
    firstTurnPriority: 'Keep the leftover A recommended',
    strategyPreferenceSummary: 'Keep the leftover A coach focus recommended',
    continuitySummary: 'Keep the leftover A coach focus summary',
  };
  bootstrap.coachOrientation = {
    objectLabel: 'Keep the current stage',
    why: 'Leftover A plan is still current',
    nextStep: 'Stay on leftover A',
  };
  bootstrap.memory.currentFocus = 'Keep the leftover A coaching focus';
  bootstrap.memory.activeThread = {
    focusArea: 'Keep the leftover A coaching focus',
    summary: 'A leftover coaching thread',
    nextStep: 'Stay on leftover A',
  };
  bootstrap.coachingState = {
    scenario: 'task',
    answerMode: 'guided',
    learnerSignal: 'steady',
    summary: 'Keep the leftover A coaching summary',
    nextStep: 'Stay on leftover A',
    encouragement: 'Keep going on A',
    teachingGoal: 'Ship one auth check',
    updatedAt: '2026-08-25T00:00:00.000Z',
  };
  bootstrap.conversation = [
    {
      id: 'msg-a',
      role: 'assistant',
      author: 'Trainer',
      body: 'Keep the leftover A coaching summary',
      timestamp: 'now',
    },
  ];
  bootstrap.evaluation = {
    headline: 'Keep the leftover A evaluation headline',
    summary: 'Keep the leftover A evaluation summary',
    passRate: 0.5,
    updatedAt: '2026-08-25T00:00:00.000Z',
    checks: [{ id: 'check-a', label: 'A leftover eval check', status: 'fail', detail: 'Stay on leftover A eval' }],
    nextStep: 'Stay on leftover A eval',
  };
  bootstrap.learnerState = {
    currentConfidence: 0.2,
    frustrationLevel: 0.8,
    attemptCountRecent: 3,
    needsRescue: true,
    needsReview: true,
    preferredHintDepth: 'expanded',
    learnerSignal: 'blocked',
    activeFocus: 'Keep the leftover A learner focus',
    evidence: ['A leftover eval evidence'],
  };
  bootstrap.teachingDecision = {
    mode: 'review_reflection',
    reason: 'Keep the leftover A teaching reason',
    primaryGoal: 'Keep the leftover A teaching goal',
    lessonShape: 'A leftover lesson',
    exerciseShape: 'A leftover exercise',
    teachingStrategy: 'Stay on leftover A',
    closingMove: 'Keep one auth check',
    artifactPriority: ['A leftover artifact'],
    shouldEndWithQuestion: true,
    shouldGenerateExercise: true,
    shouldRevealCode: true,
    shouldProducePlanArtifact: true,
    shouldTriggerDeepAnalysis: true,
    shouldFocusOnImplementationSteps: true,
    toneProfile: 'review_loop',
    focusArea: 'Keep the leftover A teaching focus',
  };
  bootstrap.memory.recentWins = ['Keep the leftover A recent win'];
  bootstrap.memory.teachingObservations = ['Keep the leftover A teaching observation'];
  bootstrap.memory.coachingAdaptation = {
    summary: 'Keep the leftover A adaptation summary',
    evidence: ['Keep the leftover A adaptation evidence'],
    challengeLevel: 'raise',
    nextStepBias: 'widen',
  };
  bootstrap.affectState = {
    frustrationLevel: 0.9,
    confidenceLevel: 0.1,
    momentumLevel: 0.2,
    needsReassurance: true,
    urgencyLevel: 'high',
  };
  bootstrap.toneDecision = {
    tone: 'concise_rescue',
    verbosityBias: 'short',
    acknowledgeProgress: true,
    avoidOverwhelm: true,
  };
  bootstrap.implementationGuide = {
    ideaSummary: 'Keep the leftover A implementation idea',
    scopeBoundary: 'Stay on leftover A',
    mvpDefinition: 'Ship one leftover A slice',
    currentStep: 'Keep the leftover A implementation step',
    nextSteps: ['Stay on leftover A'],
    validationStrategy: [],
    openQuestions: [],
    teachingGoal: 'Keep the leftover A teaching goal',
  };
  bootstrap.projectIdeas = [
    {
      id: 'idea-a',
      title: 'Keep the leftover A project idea',
      summary: 'A leftover project idea',
      sourceArea: 'workspace-a',
      ideaKind: 'feature',
      learningValue: '',
      engineeringValue: '',
      difficulty: '',
      suggestedScope: '',
      firstStep: 'Stay on leftover A',
      acceptanceSignals: [],
      whyNow: 'Keep the leftover A teaching goal',
    },
  ];
  bootstrap.projectAdaptationGuide = {
    targetOutcome: 'Keep the leftover A adaptation outcome',
    currentConstraints: ['Stay on leftover A'],
    affectedAreas: ['A leftover adaptation area'],
    preserveAreas: [],
    firstMigrationStep: 'Keep the leftover A adaptation step',
    migrationSequence: ['Stay on leftover A'],
    validationCheckpoints: [],
    rollbackNotes: [],
  };
  bootstrap.projectSources = [
    {
      title: 'Keep the leftover A project source',
      sourceKind: 'reference_repo',
      repoHint: '',
      fitReason: 'A leftover project source',
      trainingValue: '',
      firstFilter: '',
      firstTask: 'Stay on leftover A',
      caution: '',
      tags: [],
      sourceUrl: '',
      retrievedAt: '',
      trustScore: 0,
      qualityFlags: [],
    },
  ];
  bootstrap.principleNotes = {
    currentPrinciple: 'Keep the leftover A principle',
    whyItMatters: 'Keep the leftover A principle why',
    commonMistake: '',
    applyNow: 'Keep the leftover A principle apply',
    transferTargets: ['Stay on leftover A'],
  };
  bootstrap.coachTurn = {
    scenario: 'project_adaptation',
    learnerSignal: 'blocked',
    summary: 'Keep the leftover A coach turn summary',
    nextStep: 'Keep the leftover A coach turn next',
    teachingGoal: 'Keep the leftover A coach turn goal',
  };
  bootstrap.task = {
    id: 'task-formal-old',
    title: 'Ship one auth check',
    description: 'Keep the leftover A task',
    constraints: [],
    acceptanceCriteria: [],
    nextActionLabel: 'Evaluate the leftover A file',
  };
  bootstrap.suggestedActions = [
    {
      id: 'suggested-a',
      label: 'Continue Ship one auth check',
      action: 'task',
    },
  ];
  bootstrap.nextStepHint = {
    title: 'Keep the leftover A next-step hint',
    summary: 'Keep the leftover A next-step summary',
    recommendedAction: 'task',
  };
  bootstrap.planRuntimeStatus = {
    nextTrainingAction: 'Keep the leftover A next training',
    currentMainThread: {
      summary: 'Keep the leftover A main thread',
      nextStep: 'Stay on leftover A',
    },
    coachJudgment: {
      summary: 'Keep the leftover A coach judgment',
      teachingGoal: 'Ship leftover A',
    },
    reviewPoints: [],
  };
  bootstrap.reviewQueueSummary = 'Keep the leftover A review queue';
  bootstrap.nextReviewDue = '2026-08-26T00:00:00.000Z';
  bootstrap.providerConfig.profileId = 'profile-a';
  bootstrap.streamingState = {
    ...createEmptyTrainerStreamingState(),
    isStreaming: true,
    streamMessageId: 'stream-a',
  };

  const patch = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-b',
    plan_runtime_status: {
      revision: 1,
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-b',
      },
    },
  });

  assert.equal(patch.memory.workspace.latestPlanRuntime, undefined);
  assert.equal(patch.memory.workspace.latestProviderCapability, undefined);
  assert.equal(patch.memory.workspace.latestStreamingCheckpoint, undefined);
  assert.equal(patch.workspaceTrainingState?.selectedCardTitle, undefined);
  assert.equal(patch.workspaceTrainingState?.latestTrainingHandoff, undefined);
  assert.equal(patch.workspaceTrainingState?.latestTrainingNextHop, undefined);
  assert.equal(patch.providerConfig.lastTestResult, undefined);
  assert.equal(patch.streamingState.isStreaming, false);
  assert.equal(patch.planRuntimeStatus, undefined);
  assert.notEqual(patch.planRuntimeStatus?.nextTrainingAction, 'Keep the leftover A next training');
  assert.notEqual(
    patch.planRuntimeStatus?.currentMainThread?.summary,
    'Keep the leftover A main thread',
  );
  assert.notEqual(
    patch.planRuntimeStatus?.coachJudgment?.summary,
    'Keep the leftover A coach judgment',
  );
  assert.equal(patch.reviewQueueSummary, '');
  assert.equal(patch.nextReviewDue, undefined);
  assert.notEqual(patch.reviewQueueSummary, 'Keep the leftover A review queue');
  assert.notEqual(patch.nextReviewDue, '2026-08-26T00:00:00.000Z');
  assert.notEqual(patch.reviewQueueSummary, '当前还没有复习安排。');
  assert.deepEqual(patch.memory.dueReviews, []);
  assert.deepEqual(patch.workspaceTrainingState?.dueReviews ?? [], []);
  assert.equal(patch.memory.dueReviewCount, 0);
  assert.notEqual(patch.memory.dueReviews[0]?.concept, 'Keep the leftover A due review');
  assert.notEqual(patch.workspaceTrainingState?.dueReviews?.[0]?.concept, 'Keep the leftover A due review');
  assert.equal(patch.workspaceTrainingState?.latestLearningFocusArea, undefined);
  assert.equal(patch.workspaceTrainingState?.latestLearningFollowup, undefined);
  assert.equal(patch.workspaceTrainingState?.latestLearningBlocker, undefined);
  assert.equal(patch.workspaceTrainingState?.latestTrainingSubmode, undefined);
  assert.equal(patch.memory.workspace.latestLearningFocusArea, undefined);
  assert.notEqual(
    patch.workspaceTrainingState?.latestLearningFocusArea,
    'Keep the leftover A learning focus',
  );
  assert.notEqual(patch.memory.workspace.latestLearningFocusArea, 'Keep the leftover A learning focus');
  assert.equal(patch.workspaceTrainingState?.selectedCardId, undefined);
  assert.equal(patch.workspaceTrainingState?.selectedCardType, undefined);
  assert.equal(patch.workspaceTrainingState?.selectedCardStatus, undefined);
  assert.notEqual(patch.workspaceTrainingState?.selectedCardId, 'card-leftover-a');
  assert.notEqual(patch.workspaceTrainingState?.selectedCardStatus, 'in_progress');
  assert.equal(patch.workspaceTrainingState?.reviewArtifact, undefined);
  assert.equal(patch.workspaceTrainingState?.scenarioLab, undefined);
  assert.equal(patch.workspaceTrainingState?.theoryDrill, undefined);
  assert.deepEqual(patch.workspaceTrainingState?.trainingCardCandidates ?? [], []);
  assert.notEqual(patch.workspaceTrainingState?.reviewArtifact?.title, 'Keep the leftover A review artifact');
  assert.notEqual(patch.workspaceTrainingState?.scenarioLab?.title, 'Keep the leftover A scenario lab');
  assert.notEqual(patch.workspaceTrainingState?.theoryDrill?.title, 'Keep the leftover A theory drill');
  assert.notEqual(
    patch.workspaceTrainingState?.trainingCardCandidates?.[0]?.title,
    'Keep the leftover A training card',
  );
  assert.equal(patch.workspaceTrainingState?.activeTrainingCardRouting, undefined);
  assert.notEqual(
    patch.workspaceTrainingState?.activeTrainingCardRouting?.whyThisCard,
    'Keep the leftover A routing why',
  );
  assert.notEqual(
    patch.workspaceTrainingState?.activeTrainingCardRouting?.selectedCard?.title,
    'Keep the leftover A routing card',
  );
  assert.notEqual(
    patch.workspaceTrainingState?.activeTrainingCardRouting?.nextAfterCompletion,
    'Keep the leftover A routing next',
  );
  assert.deepEqual(patch.workspaceTrainingState?.trainingEventLedger ?? [], []);
  assert.notEqual(
    patch.workspaceTrainingState?.trainingEventLedger?.[0]?.whyThisCard,
    'Keep the leftover A ledger why',
  );
  assert.notEqual(
    patch.workspaceTrainingState?.trainingEventLedger?.[0]?.selectedCardTitle,
    'Keep the leftover A ledger card',
  );
  assert.equal(patch.workspaceTrainingState?.latestTransferState, undefined);
  assert.equal(patch.memory.workspace.latestTransferState, undefined);
  assert.notEqual(
    patch.workspaceTrainingState?.latestTransferState?.concept,
    'Keep the leftover A transfer skill',
  );
  assert.notEqual(patch.memory.workspace.latestTransferState?.concept, 'Keep the leftover A transfer skill');
  assert.notEqual(patch.workspaceTrainingState?.latestTransferState?.state, 'awaiting_second_scene');
  assert.notEqual(patch.workspaceTrainingState?.latestTransferState?.state, 'transferable');
  assert.notEqual(patch.memory.workspace.latestTransferState?.state, 'transferable');
  assert.equal(patch.workspaceTrainingState?.latestTrainingReliability, undefined);
  assert.notEqual(patch.workspaceTrainingState?.latestTrainingReliability?.requestId, 'request-leftover-a');
  assert.notEqual(patch.workspaceTrainingState?.latestTrainingReliability?.phase, 'succeeded');
  assert.notEqual(patch.workspaceTrainingState?.latestTrainingReliability?.outcome, 'success');
  assert.equal(patch.memory.workspaceUnderstanding, undefined);
  assert.notEqual(patch.memory.workspaceUnderstanding?.repoSummary, 'Keep the leftover A repo summary');
  assert.notEqual(
    patch.memory.workspaceUnderstanding?.firstLookSummary?.recommendedNextStep,
    'Keep the leftover A first-look next',
  );
  assert.notEqual(patch.memory.workspaceUnderstanding?.firstLookSummary?.folderRole, 'existing_engineering');
  assert.deepEqual(patch.memory.evidenceQueue?.pending ?? [], []);
  assert.deepEqual(patch.memory.evidenceQueue?.deferred ?? [], []);
  assert.deepEqual(patch.memory.evidenceQueue?.adopted ?? [], []);
  assert.deepEqual(patch.memory.evidenceQueue?.rejected ?? [], []);
  assert.equal(patch.memory.evidenceQueue?.totalCount ?? 0, 0);
  assert.notEqual(patch.memory.evidenceQueue?.pending?.[0]?.id, 'evidence-leftover-a');
  assert.notEqual(patch.memory.evidenceQueue?.pending?.[0]?.summary, 'Keep the leftover A pending evidence');
  assert.notEqual(patch.memory.evidenceQueue?.adopted?.[0]?.id, 'evidence-adopted-a');
  assert.notEqual(patch.memory.evidenceQueue?.deferred?.[0]?.id, 'evidence-deferred-a');
  assert.equal(patch.memory.sandboxPreview, undefined);
  assert.equal(patch.memory.sandboxState, undefined);
  assert.notEqual(patch.memory.sandboxPreview?.path, 'F:\\workspace-a\\notes.md');
  assert.notEqual(patch.memory.sandboxPreview?.title, 'Keep the leftover A sandbox preview');
  assert.notEqual(patch.memory.sandboxState?.rootPath, 'F:\\workspace-a');
  assert.notEqual(patch.memory.sandboxState?.selectedPath, 'F:\\workspace-a\\notes.md');
  assert.equal(patch.memory.workspace.trainerWorkspace, undefined);
  assert.notEqual(patch.memory.workspace.trainerWorkspace?.status, 'managed');
  assert.notEqual(patch.memory.workspace.trainerWorkspace?.rootPath, 'F:\\workspace-a');
  assert.notEqual(patch.memory.workspace.trainerWorkspace?.projectId, 'project-leftover-a');
  assert.notEqual(patch.memory.workspace.trainerWorkspace?.identityStatus, 'verified');
  assert.equal(patch.memory.workspace.resourceSandbox, undefined);
  assert.notEqual(patch.memory.workspace.resourceSandbox?.effectivePath, 'F:\\workspace-a\\.trainer-resources');
  assert.notEqual(patch.memory.workspace.resourceSandbox?.status, 'ready');
  assert.equal(patch.memory.workspace.projectContext, undefined);
  assert.equal(patch.profile.projectContext, undefined);
  assert.notEqual(patch.memory.workspace.projectContext, 'Keep the leftover A project context');
  assert.notEqual(patch.profile.projectContext, 'Keep the leftover A project context');
  assert.notEqual(patch.profile.targetProject, 'Keep the leftover A project context');
  assert.notEqual(patch.profile.learnerName, 'Keep the leftover A learner');
  assert.notEqual(patch.memory.workspace.learnerName, 'Keep the leftover A learner');
  assert.notEqual(patch.profile.preferredRhythm, 'Keep the leftover A rhythm');
  assert.notEqual(patch.profile.preferredLearningMode, 'Keep the leftover A learning mode');
  assert.notEqual(patch.profile.onboardingRequest, 'Keep the leftover A onboarding');
  assert.equal(patch.memory.workspace.followCurrentFile, undefined);
  assert.equal(patch.memory.workspace.contextDetail, undefined);
  assert.equal(patch.memory.workspace.includeCurrentFile, undefined);
  assert.equal(patch.memory.workspace.includeSelection, undefined);
  assert.equal(patch.memory.workspace.includeDiagnostics, undefined);
  assert.equal(patch.memory.workspace.includeRelatedFiles, undefined);
  assert.notEqual(patch.memory.workspace.followCurrentFile, true);
  assert.notEqual(patch.memory.workspace.contextDetail, 'full');
  assert.notEqual(patch.memory.workspace.includeCurrentFile, true);
  assert.notEqual(patch.memory.workspace.includeSelection, true);
  assert.notEqual(patch.memory.workspace.includeDiagnostics, true);
  assert.notEqual(patch.memory.workspace.includeRelatedFiles, true);
  assert.equal(patch.memory.workspace.responseLanguage, undefined);
  assert.equal(patch.memory.workspace.answerMode, undefined);
  assert.equal(patch.memory.workspace.coachDefaults, undefined);
  assert.notEqual(patch.memory.workspace.responseLanguage, 'ja-JP');
  assert.notEqual(patch.memory.workspace.answerMode, 'direct');
  assert.notEqual(patch.memory.workspace.coachDefaults?.memoryScope, 'personal');
  assert.notEqual(patch.memory.workspace.coachDefaults?.workingSetMode, 'broad');
  assert.notEqual(patch.memory.workspace.coachDefaults?.reviewCadence, 'active');
  assert.notEqual(patch.memory.workspace.coachDefaults?.reviewReminderMode, 'ahead');
  assert.notEqual(patch.memory.workspace.coachDefaults?.workspaceMemoryToggles?.decisions, false);
  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.summary, '');
  assert.equal(patch.plan.currentStep, undefined);
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.deepEqual(patch.resources, []);
  assert.equal(patch.memory.selectedResourceDetail, undefined);
  assert.equal(patch.memory.workspace.resourceSearchMode, undefined);
  assert.equal(patch.coachFocus.currentFocus, '');
  assert.equal(patch.coachFocus.nextStep, '');
  assert.equal(patch.coachFocus.firstTurnPriority, '');
  assert.equal(patch.coachFocus.strategyPreferenceSummary, '');
  assert.equal(patch.coachFocus.continuitySummary, '');
  assert.notEqual(patch.coachFocus.currentFocus, 'Keep the leftover A coach focus');
  assert.notEqual(patch.coachFocus.continuitySummary, 'Keep the leftover A coach focus summary');
  assert.notEqual(patch.coachFocus.firstTurnPriority, 'Keep the leftover A recommended');
  assert.equal(patch.coachOrientation, undefined);
  assert.equal(patch.task.title, '');
  assert.equal(patch.task.description, '');
  assert.notEqual(patch.task.title, 'Ship one auth check');
  assert.deepEqual(patch.suggestedActions, []);
  assert.equal(patch.nextStepHint.title, '');
  assert.equal(patch.nextStepHint.summary, '');
  assert.equal(patch.nextStepHint.recommendedAction, undefined);
  assert.notEqual(patch.nextStepHint.title, 'Keep the leftover A next-step hint');
  assert.notEqual(patch.nextStepHint.summary, 'Keep the leftover A next-step summary');
  assert.equal(patch.memory.coachingAdaptation?.summary, '');
  assert.deepEqual(patch.memory.coachingAdaptation?.evidence, []);
  assert.equal(patch.memory.coachingAdaptation?.challengeLevel, undefined);
  assert.equal(patch.memory.coachingAdaptation?.nextStepBias, undefined);
  assert.notEqual(patch.memory.coachingAdaptation?.summary, 'Keep the leftover A adaptation summary');
  assert.notEqual(
    patch.memory.coachingAdaptation?.evidence?.[0],
    'Keep the leftover A adaptation evidence',
  );
  assert.equal(patch.memory.currentFocus, '');
  assert.notEqual(patch.memory.currentFocus, 'Keep the leftover A coaching focus');
  assert.equal(patch.memory.activeThread, undefined);
  assert.equal(patch.coachingState.summary, '');
  assert.equal(patch.coachingState.nextStep, '');
  assert.equal(patch.coachingState.teachingGoal, undefined);
  assert.notEqual(patch.coachingState.summary, 'Keep the leftover A coaching summary');
  assert.deepEqual(patch.conversation, []);
  assert.equal(patch.evaluation.headline, '');
  assert.equal(patch.evaluation.summary, '');
  assert.equal(patch.evaluation.nextStep, '');
  assert.deepEqual(patch.evaluation.checks, []);
  assert.notEqual(patch.evaluation.summary, 'Keep the leftover A evaluation summary');
  assert.notEqual(patch.evaluation.headline, '还没有训练评估');
  assert.equal(patch.learnerState.activeFocus, '');
  assert.deepEqual(patch.learnerState.evidence, []);
  assert.notEqual(patch.learnerState.activeFocus, 'Keep the leftover A learner focus');
  assert.equal(patch.teachingDecision.reason, '');
  assert.equal(patch.teachingDecision.primaryGoal, '');
  assert.equal(patch.teachingDecision.focusArea, '');
  assert.notEqual(patch.teachingDecision.primaryGoal, 'Keep the leftover A teaching goal');
  assert.notEqual(patch.teachingDecision.focusArea, 'Keep the leftover A teaching focus');
  assert.deepEqual(patch.memory.recentWins, []);
  assert.deepEqual(patch.memory.teachingObservations, []);
  assert.equal(patch.affectState.needsReassurance, false);
  assert.equal(patch.affectState.urgencyLevel, 'medium');
  assert.notEqual(patch.affectState.frustrationLevel, 0.9);
  assert.equal(patch.toneDecision.tone, 'steady');
  assert.equal(patch.toneDecision.acknowledgeProgress, false);
  assert.notEqual(patch.toneDecision.tone, 'concise_rescue');
  assert.equal(patch.implementationGuide.ideaSummary, '');
  assert.equal(patch.implementationGuide.currentStep, '');
  assert.notEqual(patch.implementationGuide.ideaSummary, 'Keep the leftover A implementation idea');
  assert.deepEqual(patch.projectIdeas, []);
  assert.equal(patch.projectAdaptationGuide.targetOutcome, '');
  assert.equal(patch.projectAdaptationGuide.firstMigrationStep, '');
  assert.notEqual(patch.projectAdaptationGuide.targetOutcome, 'Keep the leftover A adaptation outcome');
  assert.deepEqual(patch.projectSources, []);
  assert.notEqual(patch.projectSources[0]?.title, 'Keep the leftover A project source');
  assert.equal(patch.principleNotes.currentPrinciple, '');
  assert.equal(patch.principleNotes.whyItMatters, '');
  assert.equal(patch.principleNotes.applyNow, '');
  assert.notEqual(patch.principleNotes.currentPrinciple, 'Keep the leftover A principle');
  assert.equal(patch.coachTurn.summary, '');
  assert.equal(patch.coachTurn.nextStep, '');
  assert.equal(patch.coachTurn.teachingGoal, undefined);
  assert.notEqual(patch.coachTurn.summary, 'Keep the leftover A coach turn summary');
});

test('mergeMemorySummary re-scopes workspace A leftover plan and resources after switching back', () => {
  const bootstrap = createBootstrap();
  bootstrap.workspaceTrainingState = { workspaceId: 'workspace-b' };
  bootstrap.memory.workspace = {
    ...bootstrap.memory.workspace,
    workspaceId: 'workspace-b',
  };
  bootstrap.plan = {
    id: '',
    title: '',
    frozen: false,
    cadence: '',
    summary: '',
    stages: [],
  };
  bootstrap.resources = [];
  bootstrap.task = {
    id: '',
    title: '',
    description: '',
    constraints: [],
    acceptanceCriteria: [],
    nextActionLabel: '',
  };

  const patch = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    current_task: {
      id: 'task-formal-old',
      title: 'Ship one auth check',
      natural_language_goal: 'Keep the leftover A task',
      workspace_id: 'workspace-a',
    },
    plan: {
      id: 'plan-formal-old',
      title: 'Keep the current stage',
      summary: 'Leftover formal summary of the old stage path',
      current_step: 'Keep one auth check',
      stages: [],
    },
    memory: {
      resources: [
        {
          id: 'resource-a',
          title: 'Workspace A notes',
          kind: 'markdown',
          status: 'ready',
          summary: 'A leftover resource',
        },
      ],
      selected_resource_detail: {
        id: 'resource-a',
        title: 'Workspace A notes',
        kind: 'markdown',
        status: 'ready',
        summary: 'A leftover resource',
      },
      current_focus: 'Keep the leftover A coaching focus',
      recent_wins: ['Keep the leftover A recent win'],
      teaching_observations: ['Keep the leftover A teaching observation'],
      due_reviews: [
        {
          workspace_id: 'workspace-a',
          concept: 'Keep the leftover A due review',
          reason: 'A leftover review item',
          source: 'plan',
          severity: 'high',
        },
      ],
      due_review_count: 1,
      coaching_adaptation: {
        workspace_id: 'workspace-a',
        summary: 'Keep the leftover A adaptation summary',
        evidence: ['Keep the leftover A adaptation evidence'],
        challenge_level: 'raise',
        next_step_bias: 'widen',
      },
      active_thread: {
        workspace_id: 'workspace-a',
        focus_area: 'Keep the leftover A coaching focus',
        summary: 'A leftover coaching thread',
        next_step: 'Stay on leftover A',
      },
      workspace: {
        workspace_id: 'workspace-a',
        resource_search_mode: 'trusted',
        latest_coaching_focus: {
          workspace_id: 'workspace-a',
          summary: 'Keep the leftover A coaching summary',
          next_step: 'Stay on leftover A',
          focus_area: 'Keep the leftover A coaching focus',
          teaching_goal: 'Ship one auth check',
        },
      },
    },
    coaching_state: {
      scenario: 'task',
      summary: 'Keep the leftover A coaching summary',
      next_step: 'Stay on leftover A',
      teaching_goal: 'Ship one auth check',
      workspace_id: 'workspace-a',
    },
    evaluation: {
      workspace_id: 'workspace-a',
      summary: 'Keep the leftover A evaluation summary',
      next_step: 'Stay on leftover A eval',
      headline: 'Keep the leftover A evaluation headline',
    },
    learner_state: {
      workspace_id: 'workspace-a',
      active_focus: 'Keep the leftover A learner focus',
      evidence: ['A leftover eval evidence'],
    },
    teaching_decision: {
      workspace_id: 'workspace-a',
      reason: 'Keep the leftover A teaching reason',
      primary_goal: 'Keep the leftover A teaching goal',
      teaching_strategy: 'Stay on leftover A',
      closing_move: 'Keep one auth check',
      focus_area: 'Keep the leftover A teaching focus',
    },
    affect_state: {
      workspace_id: 'workspace-a',
      frustration_level: 0.9,
      confidence_level: 0.1,
      momentum_level: 0.2,
      needs_reassurance: true,
      urgency_level: 'high',
    },
    tone_decision: {
      workspace_id: 'workspace-a',
      tone: 'concise_rescue',
      verbosity_bias: 'short',
      acknowledge_progress: true,
      avoid_overwhelm: true,
    },
    implementation_guide: {
      workspace_id: 'workspace-a',
      idea_summary: 'Keep the leftover A implementation idea',
      current_step: 'Keep the leftover A implementation step',
      teaching_goal: 'Keep the leftover A teaching goal',
    },
    project_ideas: [
      {
        workspace_id: 'workspace-a',
        id: 'idea-a',
        title: 'Keep the leftover A project idea',
        summary: 'A leftover project idea',
        first_step: 'Stay on leftover A',
      },
    ],
    project_adaptation_guide: {
      workspace_id: 'workspace-a',
      target_outcome: 'Keep the leftover A adaptation outcome',
      first_migration_step: 'Keep the leftover A adaptation step',
    },
    project_sources: {
      workspace_id: 'workspace-a',
      sources: [
        {
          title: 'Keep the leftover A project source',
          fit_reason: 'A leftover project source',
        },
      ],
    },
    principle_notes: {
      workspace_id: 'workspace-a',
      current_principle: 'Keep the leftover A principle',
      why_it_matters: 'Keep the leftover A principle why',
      apply_now: 'Keep the leftover A principle apply',
    },
    coach_turn: {
      workspace_id: 'workspace-a',
      scenario: 'project_adaptation',
      learner_signal: 'blocked',
      summary: 'Keep the leftover A coach turn summary',
      next_step: 'Keep the leftover A coach turn next',
      teaching_goal: 'Keep the leftover A coach turn goal',
    },
    coach_focus: {
      workspace_id: 'workspace-a',
      current_focus: 'Keep the leftover A coach focus',
      next_step: 'Stay on leftover A',
      first_turn_priority: 'Keep the leftover A recommended',
      strategy_preference_summary: 'Keep the leftover A coach focus recommended',
      continuity_summary: 'Keep the leftover A coach focus summary',
    },
    next_step_hint: {
      workspace_id: 'workspace-a',
      title: 'Keep the leftover A next-step hint',
      summary: 'Keep the leftover A next-step summary',
      recommended_action: 'task',
    },
    plan_runtime_status: {
      workspace_id: 'workspace-a',
      next_training_action: 'Keep the leftover A next training',
      current_main_thread: {
        summary: 'Keep the leftover A main thread',
        next_step: 'Stay on leftover A',
      },
      coach_judgment: {
        summary: 'Keep the leftover A coach judgment',
        teaching_goal: 'Ship leftover A',
      },
    },
    review_queue_summary: 'Keep the leftover A review queue',
    next_review_due: '2026-08-26T00:00:00.000Z',
    messages: [
      {
        id: 'msg-a',
        role: 'assistant',
        content: 'Keep the leftover A coaching summary',
      },
    ],
  });

  assert.equal(patch.plan.title, 'Keep the current stage');
  assert.equal(patch.plan.summary, 'Leftover formal summary of the old stage path');
  assert.equal(patch.plan.currentStep, 'Keep one auth check');
  assert.equal(patch.resources[0]?.title, 'Workspace A notes');
  assert.equal(patch.memory.selectedResourceDetail?.title, 'Workspace A notes');
  assert.equal(patch.memory.workspace.resourceSearchMode, 'trusted');
  assert.equal(patch.task.title, 'Ship one auth check');
  assert.equal(patch.task.description, 'Keep the leftover A task');
  assert.equal(patch.memory.currentFocus, 'Keep the leftover A coaching focus');
  assert.equal(patch.memory.activeThread?.focusArea, 'Keep the leftover A coaching focus');
  assert.equal(patch.coachingState.summary, 'Keep the leftover A coaching summary');
  assert.equal(patch.coachingState.nextStep, 'Stay on leftover A');
  assert.equal(patch.coachingState.teachingGoal, 'Ship one auth check');
  assert.equal(patch.conversation[0]?.body, 'Keep the leftover A coaching summary');
  assert.equal(patch.evaluation.summary, 'Keep the leftover A evaluation summary');
  assert.equal(patch.evaluation.nextStep, 'Stay on leftover A eval');
  assert.equal(patch.learnerState.activeFocus, 'Keep the leftover A learner focus');
  assert.equal(patch.teachingDecision.primaryGoal, 'Keep the leftover A teaching goal');
  assert.equal(patch.teachingDecision.focusArea, 'Keep the leftover A teaching focus');
  assert.deepEqual(patch.memory.recentWins, ['Keep the leftover A recent win']);
  assert.deepEqual(patch.memory.teachingObservations, ['Keep the leftover A teaching observation']);
  assert.equal(patch.affectState.needsReassurance, true);
  assert.equal(patch.affectState.urgencyLevel, 'high');
  assert.equal(patch.toneDecision.tone, 'concise_rescue');
  assert.equal(patch.toneDecision.acknowledgeProgress, true);
  assert.equal(patch.implementationGuide.ideaSummary, 'Keep the leftover A implementation idea');
  assert.equal(patch.projectIdeas[0]?.title, 'Keep the leftover A project idea');
  assert.equal(patch.projectAdaptationGuide.targetOutcome, 'Keep the leftover A adaptation outcome');
  assert.equal(patch.projectAdaptationGuide.firstMigrationStep, 'Keep the leftover A adaptation step');
  assert.equal(patch.projectSources[0]?.title, 'Keep the leftover A project source');
  assert.equal(patch.principleNotes.currentPrinciple, 'Keep the leftover A principle');
  assert.equal(patch.principleNotes.applyNow, 'Keep the leftover A principle apply');
  assert.equal(patch.coachTurn.summary, 'Keep the leftover A coach turn summary');
  assert.equal(patch.coachTurn.nextStep, 'Keep the leftover A coach turn next');
  assert.equal(patch.coachTurn.teachingGoal, 'Keep the leftover A coach turn goal');
  assert.equal(patch.coachFocus.currentFocus, 'Keep the leftover A coach focus');
  assert.equal(patch.coachFocus.firstTurnPriority, 'Keep the leftover A recommended');
  assert.equal(patch.coachFocus.continuitySummary, 'Keep the leftover A coach focus summary');
  assert.equal(patch.nextStepHint.title, 'Keep the leftover A next-step hint');
  assert.equal(patch.nextStepHint.summary, 'Keep the leftover A next-step summary');
  assert.equal(patch.nextStepHint.recommendedAction, 'task');
  assert.equal(patch.memory.coachingAdaptation?.summary, 'Keep the leftover A adaptation summary');
  assert.deepEqual(patch.memory.coachingAdaptation?.evidence, [
    'Keep the leftover A adaptation evidence',
  ]);
  assert.equal(patch.memory.coachingAdaptation?.challengeLevel, 'raise');
  assert.equal(patch.memory.coachingAdaptation?.nextStepBias, 'widen');
  assert.equal(patch.planRuntimeStatus?.nextTrainingAction, 'Keep the leftover A next training');
  assert.equal(patch.planRuntimeStatus?.currentMainThread?.summary, 'Keep the leftover A main thread');
  assert.equal(patch.planRuntimeStatus?.coachJudgment?.summary, 'Keep the leftover A coach judgment');
  assert.equal(patch.reviewQueueSummary, 'Keep the leftover A review queue');
  assert.equal(patch.nextReviewDue, '2026-08-26T00:00:00.000Z');
  assert.equal(patch.memory.dueReviews[0]?.concept, 'Keep the leftover A due review');
  assert.equal(patch.memory.dueReviews[0]?.reason, 'A leftover review item');
  assert.equal(patch.memory.dueReviewCount, 1);
});

test('mergeMemorySummary re-scopes workspace A training chrome after switching back', () => {
  const bootstrap = createBootstrap();
  bootstrap.workspaceTrainingState = { workspaceId: 'workspace-b' };
  bootstrap.memory.workspace = {
    ...bootstrap.memory.workspace,
    workspaceId: 'workspace-b',
  };

  const patch = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        selected_card_title: 'Review the refresh path',
        selected_card_id: 'card-leftover-a',
        selected_card_type: 'practice',
        selected_card_status: 'in_progress',
        latest_training_chrome: {
          workspace_id: 'workspace-a',
          selected_card_title: 'Review the refresh path',
        },
        latest_training_handoff: {
          workspace_id: 'workspace-a',
          card_title: 'Review the refresh path',
        },
        latest_training_next_hop: {
          workspace_id: 'workspace-a',
          title: 'Review the refresh path',
          card_title: 'Review the refresh path',
        },
        latest_training_submode: 'practice',
        latest_learning_focus_area: 'Keep the leftover A learning focus',
        latest_learning_followup: 'Keep the leftover A learning followup',
        latest_learning_blocker: 'Keep the leftover A learning blocker',
        latest_learning_verified_result: 'Keep the leftover A verified result',
        latest_learning_abandon_reason: 'Keep the leftover A abandon reason',
        latest_learning_partial_progress: 'Keep the leftover A partial progress',
        latest_transfer_state: {
          concept: 'Keep the leftover A transfer skill',
          state: 'awaiting_second_scene',
          scene_count: 1,
          workspace_ids: ['workspace-a'],
          scene_keys: ['default'],
          why: 'Keep the leftover A transfer why',
          next: 'Keep the leftover A transfer next',
        },
        latest_training_reliability: {
          workspace_id: 'workspace-a',
          request_id: 'request-leftover-a',
          command_id: 'trainer.training.save',
          card_id: 'card-leftover-a',
          phase: 'succeeded',
          outcome: 'success',
          revision: 1,
        },
        trainer_workspace: {
          workspace_id: 'workspace-a',
          status: 'managed',
          root_path: 'F:\\workspace-a',
          project_id: 'project-leftover-a',
          project_name: 'Keep the leftover A project',
          project_path: 'F:\\workspace-a',
        },
        resource_sandbox: {
          workspace_id: 'workspace-a',
          configured_path: 'F:\\workspace-a\\.trainer-resources',
          effective_path: 'F:\\workspace-a\\.trainer-resources',
          default_path: 'F:\\workspace-a\\.trainer-resources',
          source: 'custom',
        },
        project_context: 'Keep the leftover A project context',
        learner_name: 'Keep the leftover A learner',
        preferred_rhythm: 'Keep the leftover A rhythm',
        preferred_learning_mode: 'Keep the leftover A learning mode',
        onboarding_request: 'Keep the leftover A onboarding',
        follow_current_file: true,
        context_detail: 'full',
        include_current_file: true,
        include_selection: true,
        include_diagnostics: true,
        include_related_files: true,
        response_language: 'ja-JP',
        answer_mode: 'direct',
        coach_defaults: {
          memory_scope: 'personal',
          working_set_mode: 'broad',
          review_cadence: 'active',
          review_reminder_mode: 'ahead',
          workspace_memory_toggles: {
            decisions: false,
            patterns: false,
            resources: false,
          },
        },
      },
      review_artifact: {
        workspace_id: 'workspace-a',
        title: 'Keep the leftover A review artifact',
        focus_area: 'Keep the leftover A review focus',
        summary: 'A leftover review artifact',
      },
      scenario_lab: {
        workspace_id: 'workspace-a',
        title: 'Keep the leftover A scenario lab',
        focus_area: 'Keep the leftover A scenario focus',
        success_signal: 'A leftover scenario signal',
      },
      theory_drill: {
        workspace_id: 'workspace-a',
        title: 'Keep the leftover A theory drill',
        focus_area: 'Keep the leftover A drill focus',
        summary: 'A leftover theory drill',
      },
      training_card_candidates: [
        {
          workspace_id: 'workspace-a',
          card_id: 'card-leftover-a',
          type: 'practice',
          title: 'Keep the leftover A training card',
        },
      ],
      active_training_card_routing: {
        workspace_id: 'workspace-a',
        selected_card_id: 'card-leftover-a',
        why_this_card: 'Keep the leftover A routing why',
        next_after_completion: 'Keep the leftover A routing next',
        selected_card: {
          card_id: 'card-leftover-a',
          type: 'practice',
          title: 'Keep the leftover A routing card',
        },
      },
      training_event_ledger: [
        {
          workspace_id: 'workspace-a',
          event_id: 'event-leftover-a',
          event_type: 'card_selected',
          selected_card_id: 'card-leftover-a',
          selected_card_title: 'Keep the leftover A ledger card',
          why_this_card: 'Keep the leftover A ledger why',
        },
      ],
      workspace_understanding: {
        workspace_id: 'workspace-a',
        repo_summary: 'Keep the leftover A repo summary',
        resource_brief: 'Keep the leftover A resource brief',
        first_look_summary: {
          folder_role: 'existing_engineering',
          project_type_guess: 'api_service',
          recommended_next_step: 'Keep the leftover A first-look next',
          why_this_guess: 'Keep the leftover A first-look why',
        },
      },
      evidence_queue: {
        pending: [
          {
            workspace_id: 'workspace-a',
            id: 'evidence-leftover-a',
            summary: 'Keep the leftover A pending evidence',
            source: 'card_result',
            outcome: 'partial',
            confidence: 0.8,
          },
        ],
        deferred: [
          {
            workspace_id: 'workspace-a',
            id: 'evidence-deferred-a',
            summary: 'Keep the leftover A deferred evidence',
            source: 'card_result',
            outcome: 'partial',
            confidence: 0.5,
          },
        ],
        adopted: [
          {
            workspace_id: 'workspace-a',
            id: 'evidence-adopted-a',
            summary: 'Keep the leftover A adopted evidence',
            source: 'card_result',
            outcome: 'success',
            confidence: 1,
            adopted: true,
          },
        ],
        rejected: [],
        history: [],
        total_count: 3,
      },
      sandbox_preview: {
        workspace_id: 'workspace-a',
        path: 'F:\\workspace-a\\notes.md',
        title: 'Keep the leftover A sandbox preview',
        excerpt: 'A leftover sandbox preview',
      },
      sandbox_state: {
        workspace_id: 'workspace-a',
        root_path: 'F:\\workspace-a',
        selected_path: 'F:\\workspace-a\\notes.md',
        ready: true,
      },
    },
  });

  assert.equal(patch.workspaceTrainingState?.workspaceId, 'workspace-a');
  assert.equal(patch.workspaceTrainingState?.selectedCardTitle, 'Review the refresh path');
  assert.equal(patch.workspaceTrainingState?.selectedCardId, 'card-leftover-a');
  assert.equal(patch.workspaceTrainingState?.selectedCardType, 'practice');
  assert.equal(patch.workspaceTrainingState?.selectedCardStatus, 'in_progress');
  assert.equal(patch.workspaceTrainingState?.latestTrainingHandoff?.cardTitle, 'Review the refresh path');
  assert.equal(patch.workspaceTrainingState?.latestTrainingNextHop?.title, 'Review the refresh path');
  assert.equal(patch.workspaceTrainingState?.latestLearningFocusArea, 'Keep the leftover A learning focus');
  assert.equal(patch.workspaceTrainingState?.latestLearningFollowup, 'Keep the leftover A learning followup');
  assert.equal(patch.workspaceTrainingState?.latestLearningBlocker, 'Keep the leftover A learning blocker');
  assert.equal(patch.workspaceTrainingState?.latestTrainingSubmode, 'practice');
  assert.equal(patch.memory.workspace.latestLearningFocusArea, 'Keep the leftover A learning focus');
  assert.equal(patch.workspaceTrainingState?.reviewArtifact?.title, 'Keep the leftover A review artifact');
  assert.equal(patch.workspaceTrainingState?.scenarioLab?.title, 'Keep the leftover A scenario lab');
  assert.equal(patch.workspaceTrainingState?.theoryDrill?.title, 'Keep the leftover A theory drill');
  assert.equal(patch.workspaceTrainingState?.trainingCardCandidates?.[0]?.title, 'Keep the leftover A training card');
  assert.equal(patch.workspaceTrainingState?.activeTrainingCardRouting?.whyThisCard, 'Keep the leftover A routing why');
  assert.equal(
    patch.workspaceTrainingState?.activeTrainingCardRouting?.selectedCard?.title,
    'Keep the leftover A routing card',
  );
  assert.equal(
    patch.workspaceTrainingState?.activeTrainingCardRouting?.nextAfterCompletion,
    'Keep the leftover A routing next',
  );
  assert.equal(patch.workspaceTrainingState?.trainingEventLedger?.[0]?.whyThisCard, 'Keep the leftover A ledger why');
  assert.equal(
    patch.workspaceTrainingState?.trainingEventLedger?.[0]?.selectedCardTitle,
    'Keep the leftover A ledger card',
  );
  assert.equal(patch.workspaceTrainingState?.latestTransferState?.concept, 'Keep the leftover A transfer skill');
  assert.equal(patch.workspaceTrainingState?.latestTransferState?.state, 'awaiting_second_scene');
  assert.notEqual(patch.workspaceTrainingState?.latestTransferState?.state, 'transferable');
  assert.equal(patch.memory.workspace.latestTransferState?.concept, 'Keep the leftover A transfer skill');
  assert.equal(patch.memory.workspace.latestTransferState?.state, 'awaiting_second_scene');
  assert.equal(patch.workspaceTrainingState?.latestTrainingReliability?.requestId, 'request-leftover-a');
  assert.equal(patch.workspaceTrainingState?.latestTrainingReliability?.phase, 'succeeded');
  assert.equal(patch.workspaceTrainingState?.latestTrainingReliability?.cardId, 'card-leftover-a');
  assert.equal(patch.memory.workspaceUnderstanding?.repoSummary, 'Keep the leftover A repo summary');
  assert.equal(
    patch.memory.workspaceUnderstanding?.firstLookSummary?.recommendedNextStep,
    'Keep the leftover A first-look next',
  );
  assert.equal(patch.memory.workspaceUnderstanding?.firstLookSummary?.folderRole, 'existing_engineering');
  assert.equal(patch.memory.evidenceQueue?.pending?.[0]?.id, 'evidence-leftover-a');
  assert.equal(patch.memory.evidenceQueue?.pending?.[0]?.summary, 'Keep the leftover A pending evidence');
  assert.equal(patch.memory.evidenceQueue?.deferred?.[0]?.id, 'evidence-deferred-a');
  assert.equal(patch.memory.evidenceQueue?.adopted?.[0]?.id, 'evidence-adopted-a');
  assert.equal(patch.memory.evidenceQueue?.totalCount, 3);
  assert.equal(patch.memory.sandboxPreview?.path, 'F:\\workspace-a\\notes.md');
  assert.equal(patch.memory.sandboxPreview?.title, 'Keep the leftover A sandbox preview');
  assert.equal(patch.memory.sandboxState?.rootPath, 'F:\\workspace-a');
  assert.equal(patch.memory.sandboxState?.selectedPath, 'F:\\workspace-a\\notes.md');
  assert.equal(patch.memory.workspace.trainerWorkspace?.status, 'managed');
  assert.equal(patch.memory.workspace.trainerWorkspace?.rootPath, 'F:\\workspace-a');
  assert.equal(patch.memory.workspace.trainerWorkspace?.projectId, 'project-leftover-a');
  assert.equal(patch.memory.workspace.trainerWorkspace?.projectName, 'Keep the leftover A project');
  assert.equal(patch.memory.workspace.resourceSandbox?.effectivePath, 'F:\\workspace-a\\.trainer-resources');
  assert.equal(patch.memory.workspace.resourceSandbox?.source, 'custom');
  assert.equal(patch.memory.workspace.projectContext, 'Keep the leftover A project context');
  assert.equal(patch.profile.projectContext, 'Keep the leftover A project context');
  assert.equal(patch.profile.learnerName, 'Keep the leftover A learner');
  assert.equal(patch.profile.preferredRhythm, 'Keep the leftover A rhythm');
  assert.equal(patch.profile.preferredLearningMode, 'Keep the leftover A learning mode');
  assert.equal(patch.profile.onboardingRequest, 'Keep the leftover A onboarding');
  assert.equal(patch.memory.workspace.followCurrentFile, true);
  assert.equal(patch.memory.workspace.contextDetail, 'full');
  assert.equal(patch.memory.workspace.includeCurrentFile, true);
  assert.equal(patch.memory.workspace.includeSelection, true);
  assert.equal(patch.memory.workspace.includeDiagnostics, true);
  assert.equal(patch.memory.workspace.includeRelatedFiles, true);
  assert.equal(patch.memory.workspace.responseLanguage, 'ja-JP');
  assert.equal(patch.memory.workspace.answerMode, 'direct');
  assert.equal(patch.memory.workspace.coachDefaults?.memoryScope, 'personal');
  assert.equal(patch.memory.workspace.coachDefaults?.workingSetMode, 'broad');
  assert.equal(patch.memory.workspace.coachDefaults?.reviewCadence, 'active');
  assert.equal(patch.memory.workspace.coachDefaults?.reviewReminderMode, 'ahead');
  assert.equal(patch.memory.workspace.coachDefaults?.workspaceMemoryToggles?.decisions, false);
});

test('mergeMemorySummary drops provider A last-test and stream when switching to provider B', () => {
  const bootstrap = createBootstrap();
  bootstrap.workspaceTrainingState = { workspaceId: 'workspace-shared' };
  bootstrap.memory.workspace = {
    ...bootstrap.memory.workspace,
    workspaceId: 'workspace-shared',
    latestProviderCapability: {
      revision: 1,
      workspaceId: 'workspace-shared',
      providerProfileId: 'profile-a',
      providerName: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
      ok: true,
      checkedAt: '2026-08-25T00:00:00.000Z',
      toolsReady: false,
      toolProbeStatus: 'unverified',
      streamingReady: false,
      streamProbeStatus: 'unverified',
      visionReady: false,
      visionProbeStatus: 'unverified',
      thinkingReady: false,
      thinkingProbeStatus: 'unverified',
      capabilityEvidence: [],
    },
    latestStreamingCheckpoint: {
      revision: 1,
      workspaceId: 'workspace-shared',
      providerProfileId: 'profile-a',
      requestId: 'stream-a',
      phase: 'interrupted',
    },
  };
  bootstrap.providerConfig.profileId = 'profile-b';
  bootstrap.providerConfig.lastTestResult = {
    ok: true,
    status: 'connected',
    detail: 'Provider A last-test',
    checkedAt: '2026-08-25T00:00:00.000Z',
    workspaceId: 'workspace-shared',
    profileId: 'profile-a',
    providerName: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
  };
  bootstrap.streamingState = {
    ...createEmptyTrainerStreamingState(),
    streamError: 'interrupted',
    completionStopReason: 'interrupted',
  };

  const patch = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-shared',
    memory: {
      workspace: {
        workspace_id: 'workspace-shared',
        latest_provider_capability: bootstrap.memory.workspace.latestProviderCapability,
        latest_streaming_checkpoint: bootstrap.memory.workspace.latestStreamingCheckpoint,
      },
    },
  });

  assert.equal(patch.memory.workspace.latestProviderCapability, undefined);
  assert.equal(patch.memory.workspace.latestStreamingCheckpoint, undefined);
  assert.equal(patch.providerConfig.lastTestResult, undefined);
});

test('mergeMemorySummary drops unscoped leftover last-test when the current workspace is known', () => {
  const bootstrap = createBootstrap();
  bootstrap.workspaceTrainingState = { workspaceId: 'workspace-b' };
  bootstrap.memory.workspace = {
    ...bootstrap.memory.workspace,
    workspaceId: 'workspace-b',
  };
  bootstrap.providerConfig.profileId = 'profile-b';
  bootstrap.providerConfig.lastTestResult = {
    ok: true,
    status: 'connected',
    detail: 'Unscoped leftover last-test',
    checkedAt: '2026-08-25T00:00:00.000Z',
    providerName: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    toolsReady: true,
    toolProbeStatus: 'verified',
  };

  const patch = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-b',
    memory: {
      workspace: {
        workspace_id: 'workspace-b',
      },
    },
  });

  assert.equal(patch.providerConfig.lastTestResult, undefined);
});

test('mergeMemorySummary prefers newer failed leftover last-test over recovered success', () => {
  const bootstrap = createBootstrap();
  bootstrap.workspaceTrainingState = { workspaceId: 'workspace-a' };
  bootstrap.memory.workspace = {
    ...bootstrap.memory.workspace,
    workspaceId: 'workspace-a',
  };
  bootstrap.providerConfig.profileId = 'profile-a';
  bootstrap.providerConfig.lastTestResult = {
    ok: false,
    status: 'failed',
    detail: 'Live test failed',
    checkedAt: '2026-08-26T12:00:00.000Z',
    workspaceId: 'workspace-a',
    profileId: 'profile-a',
    providerName: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    toolsReady: false,
    toolProbeStatus: 'unverified',
    streamingReady: false,
    streamProbeStatus: 'unverified',
    visionReady: false,
    visionProbeStatus: 'unverified',
    thinkingReady: false,
    thinkingProbeStatus: 'unverified',
    capabilityEvidence: [],
  };

  const patch = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_provider_capability: {
          revision: 1,
          workspaceId: 'workspace-a',
          providerProfileId: 'profile-a',
          providerName: 'Local Compatible',
          baseUrl: 'http://localhost:1234/v1',
          model: 'demo-model',
          ok: true,
          checkedAt: '2026-08-25T00:00:00.000Z',
          toolsReady: true,
          toolProbeStatus: 'verified',
          streamingReady: false,
          streamProbeStatus: 'unverified',
          visionReady: false,
          visionProbeStatus: 'unverified',
          thinkingReady: false,
          thinkingProbeStatus: 'unverified',
          capabilityEvidence: [
            { name: 'tools', declared: true, observed: true, state: 'verified' },
          ],
        },
      },
    },
  });

  assert.equal(patch.providerConfig.lastTestResult?.ok, false);
  assert.equal(patch.providerConfig.lastTestResult?.toolsReady, false);
  assert.equal(patch.providerConfig.lastTestResult?.checkedAt, '2026-08-26T12:00:00.000Z');
});

function leftoverAIdentityBootstrap() {
  const bootstrap = createBootstrap();
  bootstrap.memory.workspace = {
    ...bootstrap.memory.workspace,
    workspaceId: 'workspace-a',
    projectContext: 'Keep the leftover A project context',
    learnerName: 'Keep the leftover A learner',
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
    selectedCardType: 'practice',
    selectedCardStatus: 'in_progress',
    latestTransferState: {
      concept: 'Keep the leftover A transfer skill',
      state: 'awaiting_second_scene',
      sceneCount: 1,
      workspaceIds: ['workspace-a'],
      sceneKeys: ['default'],
      why: 'Keep the leftover A transfer why',
      next: 'Keep the leftover A transfer next',
    },
  };
  bootstrap.memory.workspace.latestTransferState = bootstrap.workspaceTrainingState.latestTransferState;
  bootstrap.memory.workspace.preferredRhythm = 'Keep the leftover A rhythm';
  bootstrap.memory.workspace.preferredLearningMode = 'Keep the leftover A learning mode';
  bootstrap.memory.workspace.coachDefaults = {
    memoryScope: 'personal',
    workingSetMode: 'broad',
    reviewCadence: 'active',
    reviewReminderMode: 'ahead',
    workspaceMemoryToggles: {
      decisions: false,
      patterns: false,
      resources: false,
    },
  };
  bootstrap.profile = {
    ...bootstrap.profile,
    learnerName: 'Keep the leftover A learner',
    targetProject: 'Keep the leftover A project context',
    projectContext: 'Keep the leftover A project context',
    onboardingRequest: 'Keep the leftover A onboarding',
    preferredRhythm: 'Keep the leftover A rhythm',
    preferredLearningMode: 'Keep the leftover A learning mode',
  };
  bootstrap.memory.workspace.onboardingRequest = 'Keep the leftover A onboarding';
  bootstrap.memory.sandboxPreview = {
    path: 'F:\\workspace-a\\notes.md',
    title: 'Keep the leftover A sandbox preview',
    excerpt: 'A leftover sandbox preview',
  };
  bootstrap.memory.sandboxState = {
    rootPath: 'F:\\workspace-a',
    selectedPath: 'F:\\workspace-a\\notes.md',
    ready: true,
    linkedResourceCount: 3,
    totalFiles: 4,
    nodes: [{ path: 'F:\\workspace-a\\notes.md', name: 'Keep the leftover A library notes' }],
  };
  bootstrap.resources = [
    {
      id: 'resource-leftover-a',
      title: 'Keep the leftover A library notes',
      kind: 'markdown',
      status: 'ready',
      summary: 'A leftover library item',
    },
  ];
  bootstrap.conversation = [
    {
      id: 'msg-leftover-a',
      role: 'assistant',
      author: 'Trainer',
      body: 'Keep the leftover A conversation',
      timestamp: 'now',
    },
  ];
  bootstrap.memory.activeThread = {
    focusArea: 'Keep the leftover A conversation focus',
    summary: 'Keep the leftover A conversation thread',
    nextStep: 'Keep the leftover A conversation next',
  };
  bootstrap.suggestedActions = [
    {
      id: 'suggested-leftover-a',
      label: 'Keep the leftover A suggested action',
      action: 'task',
    },
  ];
  bootstrap.memory.workspaceUnderstanding = {
    repoSummary: 'Keep the leftover A repo summary',
    entryPoints: ['Keep the leftover A entry'],
    featureLanes: [],
    riskZones: [],
    trainingOpportunities: [],
    resourceBrief: 'Keep the leftover A resource brief',
    firstLookSummary: {
      folderRole: 'existing_engineering',
      projectTypeGuess: 'api_service',
      confidence: 0.9,
      whyThisGuess: 'Keep the leftover A first-look why',
      entryPoints: ['Keep the leftover A first-look entry'],
      directoryAnchors: [],
      coreModulesOrMaterials: [],
      riskZones: [],
      trainingOpportunities: [],
      unknowns: [],
      recommendedNextStep: 'Keep the leftover A first-look next',
      classificationMethod: 'heuristic',
      classifiedAt: '2026-08-25T00:00:00.000Z',
    },
    updatedAt: '2026-08-25T00:00:00.000Z',
  };
  bootstrap.evaluation = {
    headline: 'Keep the leftover A evaluation headline',
    summary: 'Keep the leftover A evaluation summary',
    passRate: 0.5,
    updatedAt: '2026-08-25T00:00:00.000Z',
    checks: [],
    nextStep: 'Stay on leftover A eval',
  };
  bootstrap.memory.workspace.latestStreamingCheckpoint = {
    revision: 1,
    workspaceId: 'workspace-a',
    providerName: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    requestId: 'stream-leftover-a',
    streamMessageId: 'Keep the leftover A stream',
    phase: 'interrupted',
    stopReason: 'Keep the leftover A stream interrupt',
    error: 'Keep the leftover A stream interrupt',
  };
  bootstrap.streamingState = {
    ...createEmptyTrainerStreamingState(),
    isStreaming: false,
    streamMessageId: 'Keep the leftover A stream',
    streamError: 'Keep the leftover A stream interrupt',
    completionStopReason: 'interrupted',
  };
  bootstrap.memory.evidenceQueue = {
    pending: [
      {
        id: 'evidence-leftover-a',
        workspaceId: 'workspace-a',
        summary: 'Keep the leftover A pending evidence',
        source: 'card_result',
        concepts: [],
        outcome: 'partial',
        confidence: 0.8,
      },
    ],
    deferred: [],
    adopted: [],
    rejected: [],
    history: [],
    totalCount: 1,
  };
  return bootstrap;
}

test('failClosedWorkbenchAfterWorkspaceTransfer drops leftover A identity on empty restore', () => {
  const patch = failClosedWorkbenchAfterWorkspaceTransfer(leftoverAIdentityBootstrap(), undefined);

  assert.equal(patch.memory.workspace.workspaceId, undefined);
  assert.notEqual(patch.memory.workspace.workspaceId, 'workspace-a');
  assert.notEqual(patch.memory.workspace.workspaceId, '__trainer_empty_workspace__');
  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.id, '');
  assert.equal(patch.plan.currentStep, undefined);
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.equal(patch.task.id, '');
  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Ship one auth check');
  assert.equal(patch.workspaceTrainingState?.selectedCardId, undefined);
  assert.equal(patch.workspaceTrainingState?.selectedCardTitle, undefined);
  assert.notEqual(patch.workspaceTrainingState?.selectedCardId, 'card-leftover-a');
  assert.deepEqual(patch.memory.evidenceQueue?.pending ?? [], []);
  assert.notEqual(patch.memory.evidenceQueue?.pending?.[0]?.id, 'evidence-leftover-a');
  assert.equal(patch.memory.workspace.trainerWorkspace, undefined);
  assert.notEqual(patch.memory.workspace.trainerWorkspace?.projectId, 'project-leftover-a');
  assert.notEqual(patch.memory.workspace.projectContext, 'Keep the leftover A project context');
  assert.equal(patch.workspaceTrainingState?.latestTransferState, undefined);
  assert.equal(patch.memory.workspace.latestTransferState, undefined);
  assert.notEqual(patch.workspaceTrainingState?.latestTransferState?.state, 'transferable');
  assert.notEqual(patch.memory.workspace.latestTransferState?.concept, 'Keep the leftover A transfer skill');
});

test('failClosedWorkbenchAfterWorkspaceTransfer drops leftover A identity when restoring onto B', () => {
  const patch = failClosedWorkbenchAfterWorkspaceTransfer(leftoverAIdentityBootstrap(), 'workspace-b');

  assert.equal(patch.memory.workspace.workspaceId, 'workspace-b');
  assert.notEqual(patch.memory.workspace.workspaceId, 'workspace-a');
  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.id, '');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Ship one auth check');
  assert.equal(patch.workspaceTrainingState?.selectedCardId, undefined);
  assert.notEqual(patch.workspaceTrainingState?.selectedCardId, 'card-leftover-a');
  assert.deepEqual(patch.memory.evidenceQueue?.pending ?? [], []);
  assert.equal(patch.memory.workspace.trainerWorkspace, undefined);
  assert.equal(patch.workspaceTrainingState?.latestTransferState, undefined);
  assert.equal(patch.memory.workspace.latestTransferState, undefined);
  assert.notEqual(patch.workspaceTrainingState?.latestTransferState?.state, 'transferable');
});

test('failClosedWorkbenchAfterWorkspaceTransfer does not let restored A inherit B transferable', () => {
  const leftoverWhy = 'Keep the leftover B transfer why';
  const leftoverNext = 'Keep the leftover B transfer next';
  const leftoverPlan = 'Keep the leftover B plan';
  const current = leftoverAIdentityBootstrap();
  current.memory.workspace.workspaceId = 'workspace-b';
  current.workspaceTrainingState = {
    ...current.workspaceTrainingState,
    workspaceId: 'workspace-b',
    latestTransferState: {
      concept: 'Keep the leftover B transfer skill',
      state: 'transferable',
      sceneCount: 2,
      workspaceIds: ['workspace-a', 'workspace-b'],
      sceneKeys: ['default'],
      why: leftoverWhy,
      next: leftoverNext,
    },
  };
  current.memory.workspace.latestTransferState = current.workspaceTrainingState.latestTransferState;
  current.plan = {
    ...current.plan,
    id: 'plan-leftover-b',
    title: leftoverPlan,
  };

  const ontoA = failClosedWorkbenchAfterWorkspaceTransfer(current, 'workspace-a');
  assert.equal(ontoA.memory.workspace.workspaceId, 'workspace-a');
  assert.notEqual(ontoA.memory.workspace.latestTransferState?.state, 'transferable');
  assert.notEqual(ontoA.workspaceTrainingState?.latestTransferState?.state, 'transferable');
  assert.notEqual(ontoA.memory.workspace.latestTransferState?.next, leftoverNext);
  assert.notEqual(ontoA.memory.workspace.latestTransferState?.why, leftoverWhy);
  assert.notEqual(ontoA.plan?.title, leftoverPlan);
  assert.notEqual(ontoA.plan?.id, 'plan-leftover-b');
});

test('failClosedWorkbenchAfterWorkspaceTransfer re-scopes leftover A when restoring onto A', () => {
  const patch = failClosedWorkbenchAfterWorkspaceTransfer(leftoverAIdentityBootstrap(), 'workspace-a');

  assert.equal(patch.memory.workspace.workspaceId, 'workspace-a');
  assert.equal(patch.plan.title, 'Keep the current stage');
  assert.equal(patch.plan.currentStep, 'Keep one auth check');
  assert.equal(patch.task.title, 'Ship one auth check');
  assert.equal(patch.workspaceTrainingState?.selectedCardId, 'card-leftover-a');
  assert.equal(patch.workspaceTrainingState?.selectedCardTitle, 'Review the refresh path');
  assert.equal(patch.memory.evidenceQueue?.pending?.[0]?.id, 'evidence-leftover-a');
  assert.equal(patch.memory.workspace.projectContext, 'Keep the leftover A project context');
});

test('failClosedWorkbenchAfterWorkspaceTransfer drops leftover A identity on leave or rollback to empty', () => {
  const patch = failClosedWorkbenchAfterWorkspaceTransfer(leftoverAIdentityBootstrap(), undefined);

  assert.equal(patch.plan.title, '');
  assert.equal(patch.task.title, '');
  assert.equal(patch.workspaceTrainingState?.selectedCardId, undefined);
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.notEqual(patch.task.title, 'Ship one auth check');
  assert.notEqual(patch.workspaceTrainingState?.selectedCardId, 'card-leftover-a');
});

test('mergeSessionStartSnapshot does not paint an unscoped sidecar plan as workspace B identity', () => {
  const current = failClosedWorkbenchAfterWorkspaceTransfer(leftoverAIdentityBootstrap(), 'workspace-b');
  const bootstrap = createBootstrap();
  Object.assign(bootstrap, current);
  bootstrap.memory = current.memory;
  bootstrap.plan = current.plan;
  bootstrap.task = current.task;
  bootstrap.workspaceTrainingState = current.workspaceTrainingState;

  const patch = mergeSessionStartSnapshot(
    bootstrap,
    {
      session_id: 'session-b',
      memory: {},
      plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
      current_task: { id: 'task-1', title: 'Generated task' },
    },
    'workspace-b',
  );

  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.id, '');
  assert.notEqual(patch.plan.title, 'Plan');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Generated task');
  assert.notEqual(patch.task.title, 'Ship one auth check');
});

function failClosedBIdentityBootstrap() {
  const current = failClosedWorkbenchAfterWorkspaceTransfer(leftoverAIdentityBootstrap(), 'workspace-b');
  const bootstrap = createBootstrap();
  Object.assign(bootstrap, current);
  bootstrap.memory = current.memory;
  bootstrap.plan = current.plan;
  bootstrap.task = current.task;
  bootstrap.workspaceTrainingState = current.workspaceTrainingState;
  return bootstrap;
}

test('mergeMemorySummarySnapshot does not paint an unscoped sidecar plan as workspace B identity', () => {
  const patch = mergeMemorySummarySnapshot(
    failClosedBIdentityBootstrap(),
    {
      session_id: 'session-b',
      memory: {},
      plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
      current_task: { id: 'task-1', title: 'Generated task' },
    },
    'workspace-b',
  );

  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.id, '');
  assert.notEqual(patch.plan.title, 'Plan');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Generated task');
  assert.notEqual(patch.task.title, 'Ship one auth check');
});

test('mergeMemorySummarySnapshot does not paint a plan stamped for A as workspace B identity', () => {
  const patch = mergeMemorySummarySnapshot(
    failClosedBIdentityBootstrap(),
    {
      session_id: 'session-b',
      memory: {},
      plan: {
        id: 'plan-1',
        title: 'Plan',
        frozen: false,
        stages: [],
        workspace_id: 'workspace-a',
      },
      current_task: {
        id: 'task-1',
        title: 'Generated task',
        workspace_id: 'workspace-a',
      },
    },
    'workspace-b',
  );

  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.id, '');
  assert.notEqual(patch.plan.title, 'Plan');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Generated task');
  assert.notEqual(patch.task.title, 'Ship one auth check');
});

test('mergeMemorySummarySnapshot paints a plan stamped for B as workspace B identity', () => {
  const patch = mergeMemorySummarySnapshot(
    failClosedBIdentityBootstrap(),
    {
      session_id: 'session-b',
      memory: {},
      plan: {
        id: 'plan-1',
        title: 'Plan',
        frozen: false,
        stages: [],
        workspace_id: 'workspace-b',
      },
      current_task: {
        id: 'task-1',
        title: 'Generated task',
        workspace_id: 'workspace-b',
      },
    },
    'workspace-b',
  );

  assert.equal(patch.plan.title, 'Plan');
  assert.equal(patch.plan.id, 'plan-1');
  assert.equal(patch.task.title, 'Generated task');
  assert.equal(patch.task.id, 'task-1');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.notEqual(patch.task.title, 'Ship one auth check');
});

test('mergeMemorySummarySnapshot empty omit is not leftover fill and does not invent a plan', () => {
  const patch = mergeMemorySummarySnapshot(
    failClosedBIdentityBootstrap(),
    {
      session_id: 'session-b',
      memory: {},
    },
    'workspace-b',
  );

  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.id, '');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.notEqual(patch.plan.id, 'plan-formal-old');
  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Ship one auth check');
  assert.notEqual(patch.workspaceTrainingState?.selectedCardId, 'card-leftover-a');
});

test('mergeSessionMessageSnapshot does not paint an unscoped /turn plan as workspace B identity', () => {
  const patch = mergeSessionMessageSnapshot(
    failClosedBIdentityBootstrap(),
    {
      session_id: 'session-b',
      reply: { content: 'Continue on B.' },
      snapshot: {
        memory: {},
        plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
        current_task: { id: 'task-1', title: 'Generated task' },
      },
    },
    'What is next?',
    'workspace-b',
  ).patch;

  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.id, '');
  assert.notEqual(patch.plan.title, 'Plan');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Generated task');
  assert.notEqual(patch.task.title, 'Ship one auth check');
});

test('mergeSessionMessageSnapshot does not paint a /turn plan stamped for A as workspace B identity', () => {
  const patch = mergeSessionMessageSnapshot(
    failClosedBIdentityBootstrap(),
    {
      session_id: 'session-b',
      reply: { content: 'Continue on B.' },
      snapshot: {
        memory: {},
        plan: {
          id: 'plan-1',
          title: 'Plan',
          frozen: false,
          stages: [],
          workspace_id: 'workspace-a',
        },
        current_task: {
          id: 'task-1',
          title: 'Generated task',
          workspace_id: 'workspace-a',
        },
      },
    },
    'What is next?',
    'workspace-b',
  ).patch;

  assert.equal(patch.plan.title, '');
  assert.notEqual(patch.plan.title, 'Plan');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Generated task');
});

test('mergeSessionMessageSnapshot paints a /turn plan stamped for B as workspace B identity', () => {
  const patch = mergeSessionMessageSnapshot(
    failClosedBIdentityBootstrap(),
    {
      session_id: 'session-b',
      reply: { content: 'Continue on B.' },
      snapshot: {
        memory: {},
        plan: {
          id: 'plan-1',
          title: 'Plan',
          frozen: false,
          stages: [],
          workspace_id: 'workspace-b',
        },
        current_task: {
          id: 'task-1',
          title: 'Generated task',
          workspace_id: 'workspace-b',
        },
      },
    },
    'What is next?',
    'workspace-b',
  ).patch;

  assert.equal(patch.plan.title, 'Plan');
  assert.equal(patch.plan.id, 'plan-1');
  assert.equal(patch.task.title, 'Generated task');
  assert.equal(patch.task.id, 'task-1');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
});

test('mergeSessionMessageSnapshot empty omit is not leftover fill and does not invent a plan', () => {
  const patch = mergeSessionMessageSnapshot(
    failClosedBIdentityBootstrap(),
    {
      session_id: 'session-b',
      reply: { content: 'Continue on B.' },
      snapshot: {
        memory: {},
      },
    },
    'What is next?',
    'workspace-b',
  ).patch;

  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.id, '');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Ship one auth check');
});

test('mergeMemorySummarySnapshot does not leftover-fill empty workspace from an unscoped sidecar plan', () => {
  const current = failClosedWorkbenchAfterWorkspaceTransfer(leftoverAIdentityBootstrap(), undefined);
  const bootstrap = createBootstrap();
  Object.assign(bootstrap, current);
  bootstrap.memory = current.memory;
  bootstrap.plan = current.plan;
  bootstrap.task = current.task;
  bootstrap.workspaceTrainingState = current.workspaceTrainingState;

  const patch = mergeMemorySummarySnapshot(
    bootstrap,
    {
      session_id: 'session-empty',
      memory: {},
      plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
      current_task: { id: 'task-1', title: 'Generated task' },
    },
    undefined,
  );

  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.id, '');
  assert.notEqual(patch.plan.title, 'Plan');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Generated task');
  assert.notEqual(patch.task.title, 'Ship one auth check');
});

test('mergePlanResultSnapshot does not paint an unscoped generate-plan as workspace B identity', () => {
  const patch = mergePlanResultSnapshot(
    failClosedBIdentityBootstrap(),
    {
      plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] },
    },
    'workspace-b',
  );

  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.id, '');
  assert.notEqual(patch.plan.title, 'Plan');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
});

test('mergePlanResultSnapshot does not paint a generate-plan stamped for A as workspace B identity', () => {
  const patch = mergePlanResultSnapshot(
    failClosedBIdentityBootstrap(),
    {
      snapshot: {
        plan: {
          id: 'plan-1',
          title: 'Plan',
          frozen: false,
          stages: [],
          workspace_id: 'workspace-a',
        },
      },
    },
    'workspace-b',
  );

  assert.equal(patch.plan.title, '');
  assert.notEqual(patch.plan.title, 'Plan');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
});

test('mergePlanResultSnapshot consumes a sidecar generate-plan stamped for B as workspace B identity', () => {
  const patch = mergePlanResultSnapshot(
    failClosedBIdentityBootstrap(),
    {
      id: 'plan-1',
      title: 'Plan',
      frozen: false,
      stages: [],
      workspace_id: 'workspace-b',
      plan: {
        id: 'plan-1',
        title: 'Plan',
        frozen: false,
        stages: [],
        workspace_id: 'workspace-b',
      },
    },
    'workspace-b',
  );

  assert.equal(patch.plan.title, 'Plan');
  assert.equal(patch.plan.id, 'plan-1');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
});

test('mergePlanResultSnapshot paints a generate-plan stamped for B as workspace B identity', () => {
  const patch = mergePlanResultSnapshot(
    failClosedBIdentityBootstrap(),
    {
      plan: {
        id: 'plan-1',
        title: 'Plan',
        frozen: false,
        stages: [],
        workspace_id: 'workspace-b',
      },
    },
    'workspace-b',
  );

  assert.equal(patch.plan.title, 'Plan');
  assert.equal(patch.plan.id, 'plan-1');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
});

test('mergePlanResultSnapshot after leftover generate paints the NEW live plan on five views', () => {
  const leftoverStep = 'Keep one auth check';
  const leftoverTitle = 'Keep the current stage';
  const generatedId = 'plan-generated-new';
  const generatedStep = 'Inspect one refresh boundary';
  const generatedTitle = 'Token-refresh learning path';
  const bootstrap = leftoverAIdentityBootstrap();
  bootstrap.workspaceTrainingState = {
    ...bootstrap.workspaceTrainingState,
    selectedCardTitle: leftoverStep,
    latestTrainingHandoff: {
      cardTitle: leftoverStep,
      learningPhase: 'return',
      handoffStatus: 'ready_to_return',
    },
  };
  const patch = mergePlanResultSnapshot(
    bootstrap,
    {
      plan: {
        id: generatedId,
        title: generatedTitle,
        current_step: generatedStep,
        frozen: false,
        stages: [],
        workspace_id: 'workspace-a',
      },
      plan_runtime_status: {
        recovered: true,
        current_step: generatedStep,
        plan_id: generatedId,
        workspace_id: 'workspace-a',
      },
      coach_orientation: {
        objectKind: 'plan',
        objectLabel: generatedStep,
        state: 'ready',
        why: 'The current object is this plan step.',
        primaryAction: 'open_plan',
        primaryActionLabel: 'Open Plan',
        nextStep: 'Continue this step, or check Plan.',
        advancedWhere: 'Plan · current step',
        source: 'snapshot',
        revision: 1,
      },
      suggested_actions: [],
      current_task: null,
      memory: {
        workspace: {
          workspace_id: 'workspace-a',
          latest_plan_runtime: {
            plan_id: generatedId,
            current_step: generatedStep,
            resume_state: 'in_progress',
            workspace_id: 'workspace-a',
          },
          onboarding_request: '',
          project_context: '',
          selected_card_title: '',
        },
        resources: [],
      },
    },
    'workspace-a',
  );

  assert.equal(patch.plan.id, generatedId);
  assert.equal(patch.plan.currentStep, generatedStep);
  assert.notEqual(patch.plan.id, 'plan-formal-old');
  assert.notEqual(patch.plan.title, leftoverTitle);
  assert.notEqual(patch.plan.currentStep, leftoverStep);
  assert.equal(patch.planRuntimeStatus?.currentStep, generatedStep);
  assert.notEqual(patch.planRuntimeStatus?.currentStep, leftoverStep);
  assert.equal(patch.task?.title, '');
  assert.equal(patch.coachOrientation?.objectKind, 'plan');
  assert.equal(patch.coachOrientation?.objectLabel, generatedStep);
  assert.notEqual(patch.coachOrientation?.objectLabel, leftoverStep);
  assert.notEqual(patch.memory.sandboxPreview?.title, 'Keep the leftover A sandbox preview');
  assert.equal(
    (patch.resources ?? []).some((item) => item.title === 'Keep the leftover A library notes'),
    false,
  );
  assert.notEqual(patch.memory.workspace?.onboardingRequest, 'Keep the leftover A onboarding');
  assert.notEqual(patch.memory.workspace?.projectContext, 'Keep the leftover A project context');
  assert.notEqual(patch.workspaceTrainingState?.selectedCardTitle, leftoverStep);
  assert.notEqual(patch.workspaceTrainingState?.latestTrainingHandoff?.cardTitle, leftoverStep);
  assert.equal(patch.memory.workspace?.latestPlanRuntime?.planId, generatedId);
});

test('mergeMemorySummary after leftover generate omits leftover fallback when live plan is already current', () => {
  const leftoverStep = 'Keep one auth check';
  const leftoverTitle = 'Keep the current stage';
  const generatedId = 'plan-generated-new';
  const generatedStep = 'Inspect one refresh boundary';
  const generatedTitle = 'Token-refresh learning path';
  const bootstrap = leftoverAIdentityBootstrap();
  bootstrap.plan = {
    ...bootstrap.plan,
    id: generatedId,
    title: generatedTitle,
    currentStep: generatedStep,
  };
  bootstrap.planRuntimeStatus = {
    ...bootstrap.planRuntimeStatus,
    recovered: true,
    currentStep: generatedStep,
    planId: generatedId,
  };
  bootstrap.workspaceTrainingState = {
    ...bootstrap.workspaceTrainingState,
    selectedCardTitle: leftoverStep,
    latestTrainingHandoff: {
      cardTitle: leftoverStep,
      learningPhase: 'return',
      handoffStatus: 'ready_to_return',
    },
  };
  const patch = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    plan: {
      id: generatedId,
      title: generatedTitle,
      current_step: generatedStep,
      frozen: false,
      stages: [],
      workspace_id: 'workspace-a',
    },
    plan_runtime_status: {
      recovered: true,
      current_step: generatedStep,
      plan_id: generatedId,
      workspace_id: 'workspace-a',
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_plan_runtime: {
          plan_id: generatedId,
          current_step: generatedStep,
          resume_state: 'in_progress',
          workspace_id: 'workspace-a',
        },
      },
    },
  });

  assert.equal(patch.plan.id, generatedId);
  assert.notEqual(patch.plan.title, leftoverTitle);
  assert.notEqual(patch.memory.sandboxPreview?.title, 'Keep the leftover A sandbox preview');
  assert.equal(
    (patch.resources ?? []).some((item) => item.title === 'Keep the leftover A library notes'),
    false,
  );
  assert.notEqual(patch.workspaceTrainingState?.selectedCardTitle, leftoverStep);
  assert.notEqual(patch.workspaceTrainingState?.latestTrainingHandoff?.cardTitle, leftoverStep);
});

test('mergePlanResultSnapshot empty omit is not leftover fill and does not invent a plan', () => {
  const patch = mergePlanResultSnapshot(
    failClosedBIdentityBootstrap(),
    {},
    'workspace-b',
  );

  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.id, '');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
  assert.notEqual(patch.plan.id, 'plan-formal-old');
});

test('mergePlanResultSnapshot does not leftover-fill empty workspace from an unscoped generate-plan', () => {
  const current = failClosedWorkbenchAfterWorkspaceTransfer(leftoverAIdentityBootstrap(), undefined);
  const bootstrap = createBootstrap();
  Object.assign(bootstrap, current);
  bootstrap.memory = current.memory;
  bootstrap.plan = current.plan;
  bootstrap.task = current.task;
  bootstrap.workspaceTrainingState = current.workspaceTrainingState;

  const patch = mergePlanResultSnapshot(
    bootstrap,
    { plan: { id: 'plan-1', title: 'Plan', frozen: false, stages: [] } },
    undefined,
  );

  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.id, '');
  assert.notEqual(patch.plan.title, 'Plan');
  assert.notEqual(patch.plan.title, 'Keep the current stage');
});

test('mergeTaskResultSnapshot does not paint an unscoped next-task as workspace B identity', () => {
  const patch = mergeTaskResultSnapshot(
    failClosedBIdentityBootstrap(),
    { id: 'task-1', title: 'Generated task', natural_language_goal: 'Invent a live task' },
    'workspace-b',
  );

  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Generated task');
  assert.notEqual(patch.task.title, 'Ship one auth check');
});

test('mergeTaskResultSnapshot does not paint a next-task stamped for A as workspace B identity', () => {
  const patch = mergeTaskResultSnapshot(
    failClosedBIdentityBootstrap(),
    {
      id: 'task-1',
      title: 'Generated task',
      natural_language_goal: 'Invent a live task',
      workspace_id: 'workspace-a',
    },
    'workspace-b',
  );

  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Generated task');
  assert.notEqual(patch.task.title, 'Ship one auth check');
});

test('mergeTaskResultSnapshot paints a next-task stamped for B as workspace B identity', () => {
  const patch = mergeTaskResultSnapshot(
    failClosedBIdentityBootstrap(),
    {
      id: 'task-1',
      title: 'Generated task',
      natural_language_goal: 'Ship the B task',
      workspace_id: 'workspace-b',
    },
    'workspace-b',
  );

  assert.equal(patch.task.title, 'Generated task');
  assert.equal(patch.task.id, 'task-1');
  assert.notEqual(patch.task.title, 'Ship one auth check');
});

test('mergeTaskResultSnapshot empty omit is not leftover fill and does not invent a task', () => {
  const patch = mergeTaskResultSnapshot(
    failClosedBIdentityBootstrap(),
    {},
    'workspace-b',
  );

  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Ship one auth check');
  assert.notEqual(patch.task.id, 'task-formal-old');
});

test('mergeTaskResultSnapshot does not leftover-fill empty workspace from an unscoped next-task', () => {
  const current = failClosedWorkbenchAfterWorkspaceTransfer(leftoverAIdentityBootstrap(), undefined);
  const bootstrap = createBootstrap();
  Object.assign(bootstrap, current);
  bootstrap.memory = current.memory;
  bootstrap.plan = current.plan;
  bootstrap.task = current.task;
  bootstrap.workspaceTrainingState = current.workspaceTrainingState;

  const patch = mergeTaskResultSnapshot(
    bootstrap,
    { id: 'task-1', title: 'Generated task', natural_language_goal: 'Invent a live task' },
    undefined,
  );

  assert.equal(patch.task.title, '');
  assert.notEqual(patch.task.title, 'Generated task');
  assert.notEqual(patch.task.title, 'Ship one auth check');
});

test('mergeEvaluationResultSnapshot does not paint an unscoped evaluation as workspace B identity', () => {
  const patch = mergeEvaluationResultSnapshot(
    failClosedBIdentityBootstrap(),
    { summary: 'Leftover evaluation', next_step: 'Keep going', passed: true },
    'workspace-b',
  );

  assert.equal(patch.evaluation.summary, '');
  assert.notEqual(patch.evaluation.summary, 'Leftover evaluation');
});

test('mergeEvaluationResultSnapshot does not paint an evaluation stamped for A as workspace B identity', () => {
  const patch = mergeEvaluationResultSnapshot(
    failClosedBIdentityBootstrap(),
    {
      summary: 'A evaluation',
      next_step: 'Keep going',
      passed: true,
      workspace_id: 'workspace-a',
    },
    'workspace-b',
  );

  assert.equal(patch.evaluation.summary, '');
  assert.notEqual(patch.evaluation.summary, 'A evaluation');
});

test('mergeEvaluationResultSnapshot paints an evaluation stamped for B as workspace B identity', () => {
  const patch = mergeEvaluationResultSnapshot(
    failClosedBIdentityBootstrap(),
    {
      summary: '2 of 3 checks passed.',
      next_step: 'Fix the failing test first.',
      passed: false,
      workspace_id: 'workspace-b',
      static_checks: [{ id: 'lint', label: 'Lint', status: 'passed', detail: 'ok' }],
    },
    'workspace-b',
  );

  assert.equal(patch.evaluation.summary, '2 of 3 checks passed.');
  assert.notEqual(patch.evaluation.summary, '');
});

test('mergeEvaluationResultSnapshot empty omit is not leftover fill', () => {
  const patch = mergeEvaluationResultSnapshot(
    failClosedBIdentityBootstrap(),
    {},
    'workspace-b',
  );

  assert.equal(patch.evaluation.summary, '');
  assert.equal(patch.evaluation.headline, '');
});

test('mergeMemorySummary does not leftover-fill B with unscoped transfer mastery', () => {
  const bootstrap = leftoverAIdentityBootstrap();
  const patch = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-b',
    memory: {
      workspace: {
        workspace_id: 'workspace-b',
        latest_transfer_state: {
          concept: 'Keep the leftover A transfer skill',
          state: 'transferable',
          scene_count: 1,
          workspace_ids: [],
          why: 'Bare transfer ids without evidence',
          next: 'Treat one scene as global mastery',
        },
      },
    },
  });

  assert.equal(patch.workspaceTrainingState?.latestTransferState, undefined);
  assert.equal(patch.memory.workspace.latestTransferState, undefined);
  assert.notEqual(patch.workspaceTrainingState?.latestTransferState?.state, 'transferable');
  assert.notEqual(patch.memory.workspace.latestTransferState?.concept, 'Keep the leftover A transfer skill');
});

test('mergeMemorySummary does not treat one-scene A transfer as B mastery', () => {
  const bootstrap = leftoverAIdentityBootstrap();
  const patch = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-b',
    memory: {
      workspace: {
        workspace_id: 'workspace-b',
        latest_transfer_state: {
          concept: 'Keep the leftover A transfer skill',
          state: 'awaiting_second_scene',
          scene_count: 1,
          workspace_ids: ['workspace-a'],
          scene_keys: ['default'],
          why: 'Only one project scene so far',
          next: 'Prove it in a second scene',
        },
      },
    },
  });

  assert.equal(patch.workspaceTrainingState?.latestTransferState, undefined);
  assert.equal(patch.memory.workspace.latestTransferState, undefined);
  assert.notEqual(patch.workspaceTrainingState?.latestTransferState?.state, 'transferable');
  assert.notEqual(patch.memory.workspace.latestTransferState?.concept, 'Keep the leftover A transfer skill');
});

test('mergeMemorySummary keeps a second evidenced scene as transferable on that workspace', () => {
  const bootstrap = leftoverAIdentityBootstrap();
  bootstrap.memory.workspace.workspaceId = 'workspace-b';
  bootstrap.workspaceTrainingState.workspaceId = 'workspace-b';
  const patch = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-b',
    memory: {
      workspace: {
        workspace_id: 'workspace-b',
        latest_transfer_state: {
          concept: 'Shared rhythm',
          state: 'transferable',
          scene_count: 2,
          workspace_ids: ['workspace-b'],
          scene_keys: ['default', 'transfer:docs-sandbox'],
          why: 'Verified in more than one scene',
          next: 'Review the transferable skill',
        },
      },
    },
  });

  assert.equal(patch.workspaceTrainingState?.latestTransferState?.state, 'transferable');
  assert.equal(patch.memory.workspace.latestTransferState?.state, 'transferable');
  assert.equal(patch.workspaceTrainingState?.latestTransferState?.concept, 'Shared rhythm');
  assert.deepEqual(patch.memory.workspace.latestTransferState?.workspaceIds, ['workspace-b']);
});

test('mergeMemorySummary hydrates A Return bind without inventing a plan or painting B', () => {
  const bootstrapA = createBootstrap();
  bootstrapA.memory.workspace = {
    ...bootstrapA.memory.workspace,
    workspaceId: 'workspace-a',
  };
  const patchA = mergeMemorySummary(bootstrapA, {
    context_id: 'workspace-a',
    memory: {
      evidence_queue: {
        pending: [
          {
            id: 'ev-return-a',
            workspace_id: 'workspace-a',
            summary: 'Focused auth check passed.',
            source: 'training_handoff_return',
            source_card_id: 'card-growth-a',
            concepts: ['Keep one auth check'],
            outcome: 'pass',
            verified: true,
          },
        ],
        deferred: [],
        adopted: [],
        rejected: [],
        history: [],
        totalCount: 1,
      },
      workspace: {
        workspace_id: 'workspace-a',
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: 'Keep one auth check',
          next_after_current: 'Add a token expiry test',
          resume_state: 'waiting',
          evidence_binding: 'ev-return-a',
        },
        latest_training_next_hop: {
          workspace_id: 'workspace-a',
          title: 'Keep one auth check',
          card_title: 'Keep one auth check',
        },
      },
    },
  });

  assert.equal(patchA.memory.workspace.latestPlanRuntime?.resumeState, 'waiting');
  assert.equal(patchA.memory.workspace.latestPlanRuntime?.currentStep, 'Keep one auth check');
  assert.equal(patchA.memory.workspace.latestPlanRuntime?.nextAfterCurrent, 'Add a token expiry test');
  assert.equal(patchA.memory.workspace.latestPlanRuntime?.evidenceBinding, 'ev-return-a');
  assert.equal(patchA.memory.evidenceQueue?.pending?.[0]?.id, 'ev-return-a');
  assert.notEqual(patchA.plan?.id, 'plan-formal-old');
  assert.notEqual(patchA.memory.workspace.latestTransferState?.state, 'transferable');

  const bootstrapB = leftoverAIdentityBootstrap();
  bootstrapB.memory.workspace.latestPlanRuntime = patchA.memory.workspace.latestPlanRuntime;
  bootstrapB.memory.evidenceQueue = patchA.memory.evidenceQueue;
  const patchB = mergeMemorySummary(bootstrapB, {
    context_id: 'workspace-b',
    memory: {
      workspace: {
        workspace_id: 'workspace-b',
      },
    },
  });
  assert.deepEqual(patchB.memory.evidenceQueue?.pending ?? [], []);
  assert.notEqual(patchB.memory.workspace.latestPlanRuntime?.currentStep, 'Keep one auth check');
  assert.notEqual(patchB.memory.workspace.latestPlanRuntime?.evidenceBinding, 'ev-return-a');
  assert.notEqual(patchB.workspaceTrainingState?.latestTrainingNextHop?.title, 'Keep one auth check');
});

test('mergeMemorySummary does not leftover-fill B with A return evidence or training next', () => {
  const bootstrap = leftoverAIdentityBootstrap();
  bootstrap.memory.evidenceQueue = {
    pending: [
      {
        id: 'ev-return-a',
        workspaceId: 'workspace-a',
        summary: 'Focused auth check passed.',
        source: 'training_handoff_return',
        sourceCardId: 'card-leftover-a',
        concepts: ['Keep one auth check'],
        outcome: 'pass',
        confidence: 0.9,
        verified: true,
      },
    ],
    deferred: [],
    adopted: [],
    rejected: [],
    history: [],
    totalCount: 1,
  };
  bootstrap.memory.workspace.latestPlanRuntime = {
    revision: 1,
    workspaceId: 'workspace-a',
    currentStep: 'Keep one auth check',
    nextAfterCurrent: 'Add a token expiry test',
    resumeState: 'waiting',
    evidenceBinding: 'ev-return-a',
  };
  bootstrap.workspaceTrainingState.latestTrainingNextHop = {
    workspaceId: 'workspace-a',
    title: 'Keep one auth check',
    cardTitle: 'Keep one auth check',
  };

  const patch = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-b',
    memory: {
      workspace: {
        workspace_id: 'workspace-b',
      },
    },
  });

  assert.deepEqual(patch.memory.evidenceQueue?.pending ?? [], []);
  assert.notEqual(patch.memory.evidenceQueue?.pending?.[0]?.id, 'ev-return-a');
  assert.notEqual(patch.memory.workspace.latestPlanRuntime?.currentStep, 'Keep one auth check');
  assert.notEqual(patch.workspaceTrainingState?.latestTrainingNextHop?.title, 'Keep one auth check');
  assert.notEqual(patch.workspaceTrainingState?.selectedCardId, 'card-leftover-a');
  assert.notEqual(patch.memory.workspace.latestTransferState?.state, 'transferable');
});

test('mergeMemorySummary does not paint leftover formal plan as live when recovered current_step is empty', () => {
  const leftoverTitle = 'Keep the current stage';
  const leftoverStep = 'Keep one auth check';
  const leftoverBlocked = 'Keep the leftover blocker';
  const leftoverWhy = 'Keep the leftover why';
  const bootstrap = leftoverAIdentityBootstrap();
  bootstrap.plan = {
    ...bootstrap.plan,
    id: 'plan-formal-old',
    title: leftoverTitle,
    currentStep: leftoverStep,
    whyNow: leftoverWhy,
    blockedReason: leftoverBlocked,
    stages: [{ id: 'stage-1', title: 'Auth', objective: 'Keep one check', status: 'active' }],
  };
  bootstrap.planRuntimeStatus = {
    recovered: false,
    currentStep: leftoverStep,
    whyNow: leftoverWhy,
    blockedReason: leftoverBlocked,
    currentStage: { id: 'stage-1', title: 'Auth', goal: 'Keep one check', status: 'active' },
    currentMainThread: {
      currentStep: leftoverStep,
      whyNow: leftoverWhy,
      blockedReason: leftoverBlocked,
      summary: leftoverTitle,
    },
  };

  const patchA = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    plan: {
      id: 'plan-formal-old',
      title: leftoverTitle,
      current_step: leftoverStep,
      why_now: leftoverWhy,
      blocked_reason: leftoverBlocked,
      stages: [{ id: 'stage-1', title: 'Auth', goal: 'Keep one check', status: 'active' }],
    },
    plan_runtime_status: {
      recovered: false,
      current_step: leftoverStep,
      why_now: leftoverWhy,
      blocked_reason: leftoverBlocked,
      current_stage: { id: 'stage-1', title: 'Auth', goal: 'Keep one check', status: 'active' },
      current_main_thread: {
        current_step: leftoverStep,
        why_now: leftoverWhy,
        blocked_reason: leftoverBlocked,
        summary: leftoverTitle,
      },
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: '',
          resume_state: 'in_progress',
          why_now: leftoverWhy,
          blocked_reason: leftoverBlocked,
        },
      },
    },
  });

  assert.equal(patchA.plan.id, 'plan-formal-old');
  assert.equal(patchA.plan.title, leftoverTitle);
  assert.equal(patchA.plan.currentStep, leftoverStep);
  assert.equal(patchA.planRuntimeStatus?.recovered, true);
  assert.equal(patchA.planRuntimeStatus?.currentStep, undefined);
  assert.notEqual(patchA.planRuntimeStatus?.currentStep, leftoverStep);
  assert.notEqual(patchA.planRuntimeStatus?.whyNow, leftoverWhy);
  assert.notEqual(patchA.planRuntimeStatus?.blockedReason, leftoverBlocked);
  assert.notEqual(patchA.planRuntimeStatus?.currentStage?.title, 'Auth');
  assert.notEqual(patchA.planRuntimeStatus?.currentMainThread?.currentStep, leftoverStep);
  assert.notEqual(patchA.planRuntimeStatus?.currentMainThread?.blockedReason, leftoverBlocked);

  const live = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    plan: {
      id: 'plan-formal-old',
      title: leftoverTitle,
      current_step: leftoverStep,
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: 'Add a token expiry test',
          why_now: 'Expired tokens still leak.',
          resume_state: 'in_progress',
        },
      },
    },
  });
  assert.equal(live.planRuntimeStatus?.recovered, true);
  assert.equal(live.planRuntimeStatus?.currentStep, 'Add a token expiry test');
  assert.equal(live.plan.title, leftoverTitle);

  const patchB = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-b',
    memory: {
      workspace: {
        workspace_id: 'workspace-b',
      },
    },
  });
  assert.notEqual(patchB.plan?.id, 'plan-formal-old');
  assert.notEqual(patchB.plan?.title, leftoverTitle);
  assert.notEqual(patchB.planRuntimeStatus?.currentStep, leftoverStep);
  assert.notEqual(patchB.memory.workspace.latestPlanRuntime?.currentStep, leftoverStep);
});

test('mergeMemorySummary does not paint leftover current_task or Coach chrome as live when recovered current_step is empty', () => {
  const leftoverTask = 'Ship one auth check';
  const leftoverGuide = 'Keep the leftover A implementation step';
  const leftoverFocus = 'Keep the leftover A coach focus';
  const leftoverActiveTask = leftoverTask;
  const liveStep = 'Add a token expiry test';
  const bootstrap = leftoverAIdentityBootstrap();
  bootstrap.task = {
    ...bootstrap.task,
    title: leftoverTask,
    description: 'Keep the leftover A task',
    nextActionLabel: leftoverGuide,
  };
  bootstrap.implementationGuide = {
    ideaSummary: 'Keep the leftover A implementation idea',
    scopeBoundary: leftoverGuide,
    mvpDefinition: '',
    currentStep: leftoverGuide,
    nextSteps: [],
    validationStrategy: [],
    openQuestions: [],
    teachingGoal: leftoverTask,
    successSignal: leftoverGuide,
    fallbackStep: leftoverGuide,
  };
  bootstrap.coachFocus = {
    currentFocus: leftoverFocus,
    nextStep: leftoverGuide,
    activeTask: leftoverActiveTask,
    activeStage: leftoverFocus,
  };

  const patchA = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    current_task: {
      id: 'task-formal-old',
      title: leftoverTask,
      natural_language_goal: 'Keep the leftover A task',
      workspace_id: 'workspace-a',
    },
    implementation_guide: {
      workspace_id: 'workspace-a',
      idea_summary: 'Keep the leftover A implementation idea',
      current_step: leftoverGuide,
      scope_boundary: leftoverGuide,
      teaching_goal: leftoverTask,
      success_signal: leftoverGuide,
      fallback_step: leftoverGuide,
    },
    coach_focus: {
      workspace_id: 'workspace-a',
      current_focus: leftoverFocus,
      next_step: leftoverGuide,
      active_task: leftoverActiveTask,
      active_stage: leftoverFocus,
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: '',
          resume_state: 'in_progress',
        },
      },
    },
  });

  assert.equal(patchA.task.title, leftoverTask);
  assert.equal(patchA.planRuntimeStatus?.recovered, true);
  assert.equal(patchA.planRuntimeStatus?.currentStep, undefined);
  assert.equal(patchA.implementationGuide.currentStep, '');
  assert.equal(patchA.implementationGuide.scopeBoundary, '');
  assert.equal(patchA.implementationGuide.teachingGoal, undefined);
  assert.notEqual(patchA.implementationGuide.currentStep, leftoverGuide);
  assert.notEqual(patchA.coachFocus.currentFocus, leftoverFocus);
  assert.notEqual(patchA.coachFocus.activeTask, leftoverActiveTask);
  assert.notEqual(patchA.coachFocus.nextStep, leftoverGuide);

  const live = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    current_task: {
      id: 'task-formal-old',
      title: leftoverTask,
      natural_language_goal: 'Keep the leftover A task',
      workspace_id: 'workspace-a',
    },
    implementation_guide: {
      workspace_id: 'workspace-a',
      current_step: leftoverGuide,
      scope_boundary: leftoverGuide,
    },
    coach_focus: {
      workspace_id: 'workspace-a',
      current_focus: leftoverFocus,
      active_task: leftoverActiveTask,
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: liveStep,
          why_now: 'Expired tokens still leak.',
          resume_state: 'in_progress',
        },
      },
    },
  });
  assert.equal(live.planRuntimeStatus?.recovered, true);
  assert.equal(live.planRuntimeStatus?.currentStep, liveStep);
  assert.equal(live.task.title, leftoverTask);
  assert.notEqual(live.implementationGuide.currentStep, leftoverGuide);
  assert.notEqual(live.coachFocus.activeTask, leftoverActiveTask);

  const patchB = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-b',
    memory: {
      workspace: {
        workspace_id: 'workspace-b',
      },
    },
  });
  assert.notEqual(patchB.task?.title, leftoverTask);
  assert.notEqual(patchB.implementationGuide?.currentStep, leftoverGuide);
  assert.notEqual(patchB.coachFocus?.activeTask, leftoverActiveTask);
  assert.notEqual(patchB.coachFocus?.currentFocus, leftoverFocus);
});

test('mergeMemorySummary does not paint leftover coachTurn coachingState or evaluation nextStep as live when recovered current_step is empty', () => {
  const leftoverTurn = 'Keep the leftover A coach turn next';
  const leftoverState = 'Stay on leftover A';
  const leftoverEval = 'Stay on leftover A eval';
  const leftoverSummary = 'Keep the leftover A coach turn summary';
  const leftoverHint = 'Keep the leftover A next-step hint';
  const leftoverResume = 'Keep the leftover A resume thread';
  const leftoverSupport = 'Keep the leftover A support strategy';
  const leftoverReview = 'Keep the leftover A review queue';
  const leftoverTeaser = 'Keep the leftover A artifact teaser';
  const leftoverRationale = 'Keep the leftover A artifact rationale';
  const leftoverContinuity = 'Keep the leftover A coach focus summary';
  const leftoverJudgment = 'Keep the leftover A coach judgment';
  const leftoverJudgmentGoal = 'Ship leftover A';
  const liveStep = 'Add a token expiry test';
  const bootstrap = leftoverAIdentityBootstrap();
  bootstrap.coachTurn = {
    scenario: 'task',
    learnerSignal: 'steady',
    summary: leftoverSummary,
    nextStep: leftoverTurn,
    teachingGoal: leftoverTurn,
    resumeThread: leftoverResume,
    supportStrategy: leftoverSupport,
    reviewQueueSummary: leftoverReview,
  };
  bootstrap.coachingState = {
    scenario: 'task',
    answerMode: 'guided',
    learnerSignal: 'steady',
    summary: leftoverSummary,
    nextStep: leftoverState,
    encouragement: leftoverState,
    teachingGoal: leftoverTurn,
    resumeThread: leftoverResume,
    supportStrategy: leftoverSupport,
    updatedAt: '2026-08-26T00:00:00.000Z',
  };
  bootstrap.reviewQueueSummary = leftoverReview;
  bootstrap.conversation = [
    {
      id: 'assistant-leftover-a',
      role: 'assistant',
      author: 'Trainer',
      body: leftoverSummary,
      timestamp: '2026-08-26T00:00:00.000Z',
      artifacts: [
        {
          kind: 'next_step',
          title: leftoverTurn,
          teaser: leftoverTeaser,
          rationale: leftoverRationale,
        },
      ],
    },
  ];
  bootstrap.evaluation = {
    headline: leftoverEval,
    summary: leftoverEval,
    passRate: 0,
    updatedAt: '2026-08-26T00:00:00.000Z',
    checks: [],
    nextStep: leftoverEval,
  };
  bootstrap.nextStepHint = {
    title: leftoverHint,
    summary: leftoverState,
  };
  bootstrap.coachFocus = {
    currentFocus: leftoverContinuity,
    continuitySummary: leftoverContinuity,
  };
  bootstrap.planRuntimeStatus = {
    recovered: true,
    coachJudgment: {
      summary: leftoverJudgment,
      teachingGoal: leftoverJudgmentGoal,
    },
    reviewPoints: [],
  };

  const patchA = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    coaching_state: {
      workspace_id: 'workspace-a',
      scenario: 'task',
      summary: leftoverSummary,
      next_step: leftoverState,
      teaching_goal: leftoverTurn,
      resume_thread: leftoverResume,
      support_strategy: leftoverSupport,
    },
    coach_turn: {
      workspace_id: 'workspace-a',
      scenario: 'task',
      summary: leftoverSummary,
      next_step: leftoverTurn,
      teaching_goal: leftoverTurn,
      resume_thread: leftoverResume,
      support_strategy: leftoverSupport,
      review_queue_summary: leftoverReview,
    },
    review_queue_summary: leftoverReview,
    coach_focus: {
      workspace_id: 'workspace-a',
      continuity_summary: leftoverContinuity,
      current_focus: leftoverContinuity,
    },
    plan_runtime_status: {
      workspace_id: 'workspace-a',
      recovered: true,
      current_step: '',
      coach_judgment: {
        summary: leftoverJudgment,
        teaching_goal: leftoverJudgmentGoal,
      },
    },
    evaluation: {
      workspace_id: 'workspace-a',
      summary: leftoverEval,
      next_step: leftoverEval,
    },
    next_step_hint: {
      workspace_id: 'workspace-a',
      title: leftoverHint,
      summary: leftoverState,
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: '',
          resume_state: 'in_progress',
        },
      },
    },
  });

  assert.equal(patchA.planRuntimeStatus?.recovered, true);
  assert.equal(patchA.planRuntimeStatus?.currentStep, undefined);
  assert.notEqual(patchA.coachTurn?.nextStep, leftoverTurn);
  assert.notEqual(patchA.coachTurn?.summary, leftoverSummary);
  assert.notEqual(patchA.coachTurn?.resumeThread, leftoverResume);
  assert.notEqual(patchA.coachTurn?.supportStrategy, leftoverSupport);
  assert.notEqual(patchA.coachTurn?.reviewQueueSummary, leftoverReview);
  assert.notEqual(patchA.coachingState?.nextStep, leftoverState);
  assert.notEqual(patchA.coachingState?.summary, leftoverSummary);
  assert.notEqual(patchA.coachingState?.resumeThread, leftoverResume);
  assert.notEqual(patchA.coachingState?.supportStrategy, leftoverSupport);
  assert.notEqual(patchA.evaluation?.nextStep, leftoverEval);
  assert.notEqual(patchA.nextStepHint?.title, leftoverHint);
  assert.notEqual(patchA.reviewQueueSummary, leftoverReview);
  assert.notEqual(patchA.planRuntimeStatus?.reviewQueueSummary, leftoverReview);
  assert.notEqual(patchA.planRuntimeStatus?.coachJudgment?.resumeThread, leftoverResume);
  assert.notEqual(patchA.planRuntimeStatus?.coachJudgment?.supportStrategy, leftoverSupport);
  assert.notEqual(patchA.coachFocus?.continuitySummary, leftoverContinuity);
  assert.notEqual(patchA.planRuntimeStatus?.coachJudgment?.summary, leftoverJudgment);
  assert.notEqual(patchA.planRuntimeStatus?.coachJudgment?.teachingGoal, leftoverJudgmentGoal);
  assert.deepEqual(patchA.conversation ?? [], []);
  assert.notEqual(patchA.conversation?.[0]?.artifacts?.[0]?.teaser, leftoverTeaser);
  assert.notEqual(patchA.conversation?.[0]?.artifacts?.[0]?.rationale, leftoverRationale);

  const live = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    coaching_state: {
      workspace_id: 'workspace-a',
      next_step: leftoverState,
      summary: leftoverSummary,
    },
    coach_turn: {
      workspace_id: 'workspace-a',
      next_step: leftoverTurn,
      summary: leftoverSummary,
    },
    evaluation: {
      workspace_id: 'workspace-a',
      next_step: leftoverEval,
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: liveStep,
          why_now: 'Expired tokens still leak.',
          resume_state: 'in_progress',
        },
      },
    },
  });
  assert.equal(live.planRuntimeStatus?.recovered, true);
  assert.equal(live.planRuntimeStatus?.currentStep, liveStep);
  assert.equal(live.conversation?.[0]?.artifacts?.[0]?.teaser, leftoverTeaser);
  assert.equal(live.conversation?.[0]?.artifacts?.[0]?.rationale, leftoverRationale);
  assert.notEqual(live.coachTurn?.nextStep, leftoverTurn);
  assert.notEqual(live.coachingState?.nextStep, leftoverState);
  assert.notEqual(live.evaluation?.nextStep, leftoverEval);
  assert.notEqual(live.coachTurn?.resumeThread, leftoverResume);
  assert.notEqual(live.coachTurn?.supportStrategy, leftoverSupport);
  assert.notEqual(live.reviewQueueSummary, leftoverReview);
  assert.notEqual(live.coachFocus?.continuitySummary, leftoverContinuity);
  assert.notEqual(live.planRuntimeStatus?.coachJudgment?.summary, leftoverJudgment);
  assert.notEqual(live.planRuntimeStatus?.coachJudgment?.teachingGoal, leftoverJudgmentGoal);

  const patchB = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-b',
    memory: {
      workspace: {
        workspace_id: 'workspace-b',
      },
    },
  });
  assert.notEqual(patchB.coachTurn?.nextStep, leftoverTurn);
  assert.notEqual(patchB.coachingState?.nextStep, leftoverState);
  assert.notEqual(patchB.evaluation?.nextStep, leftoverEval);
  assert.notEqual(patchB.nextStepHint?.title, leftoverHint);
  assert.notEqual(patchB.coachTurn?.resumeThread, leftoverResume);
  assert.notEqual(patchB.coachTurn?.supportStrategy, leftoverSupport);
  assert.notEqual(patchB.reviewQueueSummary, leftoverReview);
  assert.notEqual(patchB.conversation?.[0]?.artifacts?.[0]?.teaser, leftoverTeaser);
  assert.notEqual(patchB.conversation?.[0]?.artifacts?.[0]?.rationale, leftoverRationale);
  assert.notEqual(patchB.coachFocus?.continuitySummary, leftoverContinuity);
  assert.notEqual(patchB.planRuntimeStatus?.coachJudgment?.summary, leftoverJudgment);
  assert.notEqual(patchB.planRuntimeStatus?.coachJudgment?.teachingGoal, leftoverJudgmentGoal);
});

test('mergeMemorySummary does not paint leftover teachingDecision.focusArea or learnerState.activeFocus as live Training identity when recovered current_step is empty', () => {
  const leftoverFocus = 'Keep the leftover A teaching focus';
  const leftoverLearner = 'Keep the leftover A learner focus';
  const leftoverLearning = 'Keep the leftover A learning focus';
  const liveStep = 'Add a token expiry test';
  const bootstrap = leftoverAIdentityBootstrap();
  bootstrap.learnerState = {
    currentConfidence: 0.2,
    frustrationLevel: 0.8,
    attemptCountRecent: 3,
    needsRescue: true,
    needsReview: true,
    preferredHintDepth: 'expanded',
    learnerSignal: 'blocked',
    activeFocus: leftoverLearner,
    evidence: ['A leftover eval evidence'],
  };
  bootstrap.teachingDecision = {
    mode: 'review_reflection',
    reason: 'Keep the leftover A teaching reason',
    primaryGoal: 'Keep the leftover A teaching goal',
    lessonShape: 'A leftover lesson',
    exerciseShape: 'A leftover exercise',
    teachingStrategy: 'Stay on leftover A',
    closingMove: 'Keep one auth check',
    artifactPriority: ['A leftover artifact'],
    shouldEndWithQuestion: true,
    shouldGenerateExercise: true,
    shouldRevealCode: true,
    shouldProducePlanArtifact: true,
    shouldTriggerDeepAnalysis: true,
    shouldFocusOnImplementationSteps: true,
    toneProfile: 'review_loop',
    focusArea: leftoverFocus,
  };
  bootstrap.workspaceTrainingState = {
    ...bootstrap.workspaceTrainingState,
    latestLearningFocusArea: leftoverLearning,
  };
  bootstrap.memory.workspace = {
    ...bootstrap.memory.workspace,
    latestLearningFocusArea: leftoverLearning,
  };

  const patchA = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    learner_state: {
      workspace_id: 'workspace-a',
      active_focus: leftoverLearner,
      evidence: ['A leftover eval evidence'],
    },
    teaching_decision: {
      workspace_id: 'workspace-a',
      reason: 'Keep the leftover A teaching reason',
      primary_goal: 'Keep the leftover A teaching goal',
      focus_area: leftoverFocus,
    },
    plan_runtime_status: {
      workspace_id: 'workspace-a',
      recovered: true,
      current_step: '',
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_learning_focus_area: leftoverLearning,
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: '',
          resume_state: 'in_progress',
        },
      },
    },
  });

  assert.equal(patchA.planRuntimeStatus?.recovered, true);
  assert.equal(patchA.planRuntimeStatus?.currentStep, undefined);
  assert.notEqual(patchA.teachingDecision?.focusArea, leftoverFocus);
  assert.notEqual(patchA.learnerState?.activeFocus, leftoverLearner);
  assert.notEqual(patchA.workspaceTrainingState?.latestLearningFocusArea, leftoverLearning);
  assert.notEqual(patchA.memory?.workspace?.latestLearningFocusArea, leftoverLearning);

  const live = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    learner_state: {
      workspace_id: 'workspace-a',
      active_focus: leftoverLearner,
    },
    teaching_decision: {
      workspace_id: 'workspace-a',
      focus_area: leftoverFocus,
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_learning_focus_area: leftoverLearning,
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          plan_id: 'plan-formal-old',
          current_step: liveStep,
          why_now: 'Expired tokens still leak.',
          resume_state: 'in_progress',
        },
      },
    },
  });
  assert.equal(live.planRuntimeStatus?.recovered, true);
  assert.equal(live.planRuntimeStatus?.currentStep, liveStep);
  assert.notEqual(live.teachingDecision?.focusArea, leftoverFocus);
  assert.notEqual(live.learnerState?.activeFocus, leftoverLearner);
  assert.notEqual(live.workspaceTrainingState?.latestLearningFocusArea, leftoverLearning);

  const matchingIncoming = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    plan: {
      id: 'plan-formal-old',
      workspace_id: 'workspace-a',
      title: 'Keep the current stage',
      current_step: liveStep,
      stages: [],
    },
    learner_state: {
      workspace_id: 'workspace-a',
      active_focus: liveStep,
    },
    teaching_decision: {
      workspace_id: 'workspace-a',
      focus_area: liveStep,
    },
    plan_runtime_status: {
      workspace_id: 'workspace-a',
      recovered: true,
      current_step: liveStep,
      plan_id: 'plan-formal-old',
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_learning_focus_area: liveStep,
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          plan_id: 'plan-formal-old',
          current_step: liveStep,
          resume_state: 'in_progress',
        },
      },
    },
  });
  assert.equal(matchingIncoming.teachingDecision?.focusArea, liveStep);
  assert.equal(matchingIncoming.learnerState?.activeFocus, liveStep);
  assert.equal(matchingIncoming.workspaceTrainingState?.latestLearningFocusArea, liveStep);

  const patchB = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-b',
    memory: {
      workspace: {
        workspace_id: 'workspace-b',
      },
    },
  });
  assert.notEqual(patchB.teachingDecision?.focusArea, leftoverFocus);
  assert.notEqual(patchB.learnerState?.activeFocus, leftoverLearner);
  assert.notEqual(patchB.workspaceTrainingState?.latestLearningFocusArea, leftoverLearning);
});

test('mergeMemorySummary does not paint leftover training handoff card chrome as live Training identity when recovered current_step is empty', () => {
  const leftoverSignal = 'Keep the leftover A success signal';
  const leftoverReturn = 'Keep the leftover A return with';
  const leftoverCard = 'Keep the leftover A handoff card';
  const leftoverSelected = 'Review the leftover A selected card';
  const leftoverFollowup = 'Keep the leftover A learning followup';
  const leftoverBlocker = 'Keep the leftover A learning blocker';
  const leftoverSummary = 'Keep the leftover A handoff summary';
  const leftoverNextAfter = 'Keep the leftover A next after completion';
  const leftoverFallback = 'Keep the leftover A fallback action';
  const leftoverNextHopTitle = 'Keep the leftover A next hop title';
  const leftoverNextHopCard = 'Keep the leftover A next hop card';
  const leftoverWhy = 'Keep the leftover A why this card';
  const leftoverReturnSummary = 'Keep the leftover A return summary';
  const leftoverNextHopSummary = 'Keep the leftover A next hop summary';
  const leftoverNextHopWhy = 'Keep the leftover A next hop why';
  const leftoverResourceTitle = 'Workspace A notes';
  const leftoverRhythm = 'Keep the leftover A rhythm';
  const leftoverLearningMode = 'Keep the leftover A learning mode';
  const leftoverLearner = 'Keep the leftover A learner';
  const leftoverOnboarding = 'Keep the leftover A onboarding';
  const leftoverProject = 'Keep the leftover A project context';
  const leftoverSandboxTitle = 'Keep the leftover A sandbox preview';
  const leftoverLibraryTitle = 'Keep the leftover A library notes';
  const leftoverSandboxRoot = 'F:\\workspace-a';
  const leftoverSandboxPath = 'F:\\workspace-a\\notes.md';
  const leftoverConversation = 'Keep the leftover A conversation';
  const leftoverConversationFocus = 'Keep the leftover A conversation focus';
  const leftoverConversationThread = 'Keep the leftover A conversation thread';
  const leftoverConversationNext = 'Keep the leftover A conversation next';
  const leftoverSuggestedAction = 'Keep the leftover A suggested action';
  const leftoverFirstLookNext = 'Keep the leftover A first-look next';
  const leftoverFirstLookWhy = 'Keep the leftover A first-look why';
  const leftoverEvaluationHeadline = 'Keep the leftover A evaluation headline';
  const leftoverStream = 'Keep the leftover A stream';
  const leftoverStreamInterrupt = 'Keep the leftover A stream interrupt';
  const liveStep = 'Add a token expiry test';
  const bootstrap = leftoverAIdentityBootstrap();
  bootstrap.coachOrientation = {
    objectKind: 'conversation',
    objectLabel: leftoverStream,
    state: 'interrupted',
    why: leftoverStreamInterrupt,
    primaryAction: 'resume_checkpoint',
    primaryActionLabel: leftoverStream,
    nextStep: leftoverStreamInterrupt,
    advancedWhere: leftoverStream,
    source: 'snapshot',
    revision: 1,
  };
  bootstrap.workspaceTrainingState = {
    ...bootstrap.workspaceTrainingState,
    selectedCardTitle: leftoverSelected,
    latestLearningFollowup: leftoverFollowup,
    latestLearningBlocker: leftoverBlocker,
    latestTrainingHandoff: {
      workspaceId: 'workspace-a',
      cardTitle: leftoverCard,
      successSignal: leftoverSignal,
      returnWith: leftoverReturn,
      blockedBy: leftoverBlocker,
      handoffSummary: leftoverSummary,
      nextAfterCompletion: leftoverNextAfter,
      fallbackAction: leftoverFallback,
      returnSummary: leftoverReturnSummary,
      handoffStatus: 'ready_to_return',
      learningPhase: 'return',
    },
    latestTrainingNextHop: {
      workspaceId: 'workspace-a',
      title: leftoverNextHopTitle,
      cardTitle: leftoverNextHopCard,
      handoffSummary: leftoverSummary,
      nextAfterCompletion: leftoverNextAfter,
      fallbackAction: leftoverFallback,
      returnSummary: leftoverReturnSummary,
      summary: leftoverNextHopSummary,
      whyNow: leftoverNextHopWhy,
      status: 'surfaced',
    },
    activeTrainingCardRouting: {
      nextAfterCompletion: leftoverNextAfter,
      fallbackAction: leftoverFallback,
      whyThisCard: leftoverWhy,
    },
    trainingEventLedger: [
      {
        whyThisCard: leftoverWhy,
      },
    ],
  };

  const patchA = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    plan_runtime_status: {
      workspace_id: 'workspace-a',
      recovered: true,
      current_step: '',
    },
    suggested_actions: [
      {
        id: 'suggested-leftover-a',
        label: leftoverSuggestedAction,
        action: 'task',
      },
    ],
    evaluation: {
      workspace_id: 'workspace-a',
      headline: leftoverEvaluationHeadline,
      summary: leftoverEvaluationHeadline,
    },
    messages: [
      {
        id: 'msg-leftover-a',
        role: 'assistant',
        content: leftoverConversation,
        workspace_id: 'workspace-a',
      },
    ],
    memory: {
      workspace_understanding: {
        first_look_summary: {
          recommended_next_step: leftoverFirstLookNext,
          why_this_guess: leftoverFirstLookWhy,
          folder_role: 'existing_engineering',
          project_type_guess: 'api_service',
          classification_method: 'heuristic',
        },
      },
      active_thread: {
        workspace_id: 'workspace-a',
        focus_area: leftoverConversationFocus,
        summary: leftoverConversationThread,
        next_step: leftoverConversationNext,
      },
      sandbox_state: {
        root_path: leftoverSandboxRoot,
        selected_path: leftoverSandboxPath,
        ready: true,
        linked_resource_count: 3,
        total_files: 4,
      },
      resources: [
        {
          id: 'resource-leftover-a',
          title: leftoverLibraryTitle,
          kind: 'markdown',
          status: 'ready',
          summary: 'A leftover library item',
        },
      ],
      active_training_card_routing: {
        workspace_id: 'workspace-a',
        next_after_completion: leftoverNextAfter,
        fallback_action: leftoverFallback,
        why_this_card: leftoverWhy,
      },
      workspace: {
        workspace_id: 'workspace-a',
        selected_card_title: leftoverSelected,
        latest_learning_followup: leftoverFollowup,
        latest_learning_blocker: leftoverBlocker,
        latest_training_handoff: {
          workspace_id: 'workspace-a',
          card_title: leftoverCard,
          success_signal: leftoverSignal,
          return_with: leftoverReturn,
          blocked_by: leftoverBlocker,
          handoff_summary: leftoverSummary,
          next_after_completion: leftoverNextAfter,
          fallback_action: leftoverFallback,
          return_summary: leftoverReturnSummary,
          handoff_status: 'ready_to_return',
          learning_phase: 'return',
        },
        latest_training_next_hop: {
          workspace_id: 'workspace-a',
          title: leftoverNextHopTitle,
          card_title: leftoverNextHopCard,
          handoff_summary: leftoverSummary,
          next_after_completion: leftoverNextAfter,
          fallback_action: leftoverFallback,
          return_summary: leftoverReturnSummary,
          summary: leftoverNextHopSummary,
          why_now: leftoverNextHopWhy,
          status: 'surfaced',
        },
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: '',
          resume_state: 'in_progress',
        },
        preferred_rhythm: leftoverRhythm,
        preferred_learning_mode: leftoverLearningMode,
        learner_name: leftoverLearner,
        project_context: leftoverProject,
        onboarding_request: leftoverOnboarding,
        coach_defaults: {
          memory_scope: 'personal',
          working_set_mode: 'broad',
          review_cadence: 'active',
          review_reminder_mode: 'ahead',
        },
        sandbox_preview: {
          path: 'F:\\workspace-a\\notes.md',
          title: leftoverSandboxTitle,
          excerpt: 'A leftover sandbox preview',
        },
        latest_streaming_checkpoint: {
          workspace_id: 'workspace-a',
          provider_name: 'Local Compatible',
          base_url: 'http://localhost:1234/v1',
          model: 'demo-model',
          request_id: 'stream-leftover-a',
          stream_message_id: leftoverStream,
          phase: 'interrupted',
          stop_reason: leftoverStreamInterrupt,
          error: leftoverStreamInterrupt,
        },
      },
    },
  });

  assert.equal(patchA.planRuntimeStatus?.recovered, true);
  assert.equal(patchA.planRuntimeStatus?.currentStep, undefined);
  assert.notEqual(patchA.workspaceTrainingState?.selectedCardTitle, leftoverSelected);
  assert.notEqual(patchA.workspaceTrainingState?.latestTrainingHandoff?.cardTitle, leftoverCard);
  assert.notEqual(patchA.workspaceTrainingState?.latestTrainingHandoff?.successSignal, leftoverSignal);
  assert.notEqual(patchA.workspaceTrainingState?.latestTrainingHandoff?.returnWith, leftoverReturn);
  assert.notEqual(patchA.workspaceTrainingState?.latestLearningFollowup, leftoverFollowup);
  assert.notEqual(patchA.workspaceTrainingState?.latestLearningBlocker, leftoverBlocker);
  assert.notEqual(patchA.workspaceTrainingState?.latestTrainingHandoff?.handoffSummary, leftoverSummary);
  assert.notEqual(patchA.workspaceTrainingState?.latestTrainingHandoff?.nextAfterCompletion, leftoverNextAfter);
  assert.notEqual(patchA.workspaceTrainingState?.latestTrainingHandoff?.fallbackAction, leftoverFallback);
  assert.notEqual(patchA.workspaceTrainingState?.latestTrainingNextHop?.title, leftoverNextHopTitle);
  assert.notEqual(patchA.workspaceTrainingState?.latestTrainingNextHop?.cardTitle, leftoverNextHopCard);
  assert.notEqual(patchA.workspaceTrainingState?.latestTrainingNextHop?.nextAfterCompletion, leftoverNextAfter);
  assert.notEqual(patchA.workspaceTrainingState?.latestTrainingNextHop?.fallbackAction, leftoverFallback);
  assert.notEqual(
    patchA.workspaceTrainingState?.activeTrainingCardRouting?.nextAfterCompletion,
    leftoverNextAfter,
  );
  assert.notEqual(patchA.workspaceTrainingState?.activeTrainingCardRouting?.fallbackAction, leftoverFallback);
  assert.notEqual(patchA.workspaceTrainingState?.activeTrainingCardRouting?.whyThisCard, leftoverWhy);
  assert.notEqual(patchA.workspaceTrainingState?.latestTrainingHandoff?.returnSummary, leftoverReturnSummary);
  assert.notEqual(patchA.workspaceTrainingState?.latestTrainingNextHop?.summary, leftoverNextHopSummary);
  assert.notEqual(patchA.workspaceTrainingState?.latestTrainingNextHop?.whyNow, leftoverNextHopWhy);
  assert.notEqual(patchA.workspaceTrainingState?.trainingEventLedger?.[0]?.whyThisCard, leftoverWhy);
  assert.equal(patchA.memory.selectedResourceDetail, undefined);
  assert.notEqual(patchA.memory.selectedResourceDetail?.title, leftoverResourceTitle);
  assert.notEqual(patchA.profile.preferredRhythm, leftoverRhythm);
  assert.notEqual(patchA.profile.preferredLearningMode, leftoverLearningMode);
  assert.notEqual(patchA.profile.learnerName, leftoverLearner);
  assert.notEqual(patchA.profile.targetProject, leftoverProject);
  assert.notEqual(patchA.profile.projectContext, leftoverProject);
  assert.notEqual(patchA.profile.onboardingRequest, leftoverOnboarding);
  assert.notEqual(patchA.memory.workspace.preferredRhythm, leftoverRhythm);
  assert.notEqual(patchA.memory.workspace.preferredLearningMode, leftoverLearningMode);
  assert.notEqual(patchA.memory.workspace.learnerName, leftoverLearner);
  assert.notEqual(patchA.memory.workspace.projectContext, leftoverProject);
  assert.notEqual(patchA.memory.workspace.onboardingRequest, leftoverOnboarding);
  assert.equal(patchA.memory.workspace.coachDefaults, undefined);
  assert.notEqual(patchA.memory.workspace.coachDefaults?.memoryScope, 'personal');
  assert.notEqual(patchA.memory.workspace.coachDefaults?.reviewCadence, 'active');
  assert.equal(patchA.memory.sandboxPreview, undefined);
  assert.notEqual(patchA.memory.sandboxPreview?.title, leftoverSandboxTitle);
  assert.equal(patchA.memory.sandboxState, undefined);
  assert.notEqual(patchA.memory.sandboxState?.selectedPath, leftoverSandboxPath);
  assert.notEqual(patchA.memory.sandboxState?.rootPath, leftoverSandboxRoot);
  assert.deepEqual(patchA.resources ?? [], []);
  assert.notEqual(patchA.resources?.[0]?.title, leftoverLibraryTitle);
  assert.deepEqual(patchA.conversation ?? [], []);
  assert.notEqual(patchA.conversation?.[0]?.body, leftoverConversation);
  assert.equal(patchA.memory.activeThread, undefined);
  assert.notEqual(patchA.memory.activeThread?.focusArea, leftoverConversationFocus);
  assert.notEqual(patchA.memory.activeThread?.summary, leftoverConversationThread);
  assert.deepEqual(patchA.suggestedActions ?? [], []);
  assert.notEqual(patchA.suggestedActions?.[0]?.label, leftoverSuggestedAction);
  assert.notEqual(
    patchA.memory.workspaceUnderstanding?.firstLookSummary?.recommendedNextStep,
    leftoverFirstLookNext,
  );
  assert.notEqual(
    patchA.memory.workspaceUnderstanding?.firstLookSummary?.whyThisGuess,
    leftoverFirstLookWhy,
  );
  assert.notEqual(patchA.evaluation?.headline, leftoverEvaluationHeadline);
  assert.equal(patchA.memory.workspace.latestStreamingCheckpoint, undefined);
  assert.notEqual(patchA.memory.workspace.latestStreamingCheckpoint?.streamMessageId, leftoverStream);
  assert.notEqual(patchA.memory.workspace.latestStreamingCheckpoint?.error, leftoverStreamInterrupt);
  assert.notEqual(patchA.streamingState?.streamError, leftoverStreamInterrupt);
  assert.notEqual(patchA.streamingState?.streamMessageId, leftoverStream);
  assert.equal(patchA.streamingState?.isStreaming, false);
  assert.notEqual(patchA.coachOrientation?.primaryAction, 'resume_checkpoint');
  assert.notEqual(patchA.coachOrientation?.objectLabel, leftoverStream);
  assert.notEqual(patchA.coachOrientation?.why, leftoverStreamInterrupt);

  const inFlight = mergeMemorySummary(
    {
      ...bootstrap,
      streamingState: {
        ...createEmptyTrainerStreamingState(),
        isStreaming: true,
        streamMessageId: leftoverStream,
        streamError: leftoverStreamInterrupt,
      },
    },
    {
      context_id: 'workspace-a',
      plan_runtime_status: {
        workspace_id: 'workspace-a',
        recovered: true,
        current_step: '',
      },
      memory: {
        workspace: {
          workspace_id: 'workspace-a',
          latest_plan_runtime: {
            workspace_id: 'workspace-a',
            current_step: '',
            resume_state: 'in_progress',
          },
          latest_streaming_checkpoint: {
            workspace_id: 'workspace-a',
            provider_name: 'Local Compatible',
            base_url: 'http://localhost:1234/v1',
            model: 'demo-model',
            request_id: 'stream-leftover-a',
            stream_message_id: leftoverStream,
            phase: 'interrupted',
            stop_reason: leftoverStreamInterrupt,
            error: leftoverStreamInterrupt,
          },
        },
      },
    },
  );
  assert.equal(inFlight.planRuntimeStatus?.recovered, true);
  assert.equal(inFlight.planRuntimeStatus?.currentStep, undefined);
  assert.equal(inFlight.streamingState?.isStreaming, true);
  assert.equal(inFlight.memory.workspace.latestStreamingCheckpoint?.streamMessageId, leftoverStream);
  assert.equal(inFlight.streamingState?.streamMessageId, leftoverStream);
  assert.equal(patchA.workspaceTrainingState?.latestTrainingHandoff?.handoffStatus, 'ready_to_return');
  assert.equal(patchA.workspaceTrainingState?.latestTrainingHandoff?.learningPhase, 'return');
  assert.equal(patchA.workspaceTrainingState?.latestTrainingNextHop?.status, 'surfaced');

  const live = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    suggested_actions: [
      {
        id: 'suggested-leftover-a',
        label: leftoverSuggestedAction,
        action: 'task',
      },
    ],
    evaluation: {
      workspace_id: 'workspace-a',
      headline: leftoverEvaluationHeadline,
      summary: leftoverEvaluationHeadline,
    },
    messages: [
      {
        id: 'msg-leftover-a',
        role: 'assistant',
        content: leftoverConversation,
        workspace_id: 'workspace-a',
      },
    ],
    memory: {
      workspace_understanding: {
        first_look_summary: {
          recommended_next_step: leftoverFirstLookNext,
          why_this_guess: leftoverFirstLookWhy,
          folder_role: 'existing_engineering',
          project_type_guess: 'api_service',
          classification_method: 'heuristic',
        },
      },
      active_thread: {
        workspace_id: 'workspace-a',
        focus_area: leftoverConversationFocus,
        summary: leftoverConversationThread,
        next_step: leftoverConversationNext,
      },
      sandbox_state: {
        root_path: leftoverSandboxRoot,
        selected_path: leftoverSandboxPath,
        ready: true,
        linked_resource_count: 3,
        total_files: 4,
      },
      resources: [
        {
          id: 'resource-leftover-a',
          title: leftoverLibraryTitle,
          kind: 'markdown',
          status: 'ready',
          summary: 'A leftover library item',
        },
      ],
      workspace: {
        workspace_id: 'workspace-a',
        selected_card_title: leftoverSelected,
        latest_learning_followup: leftoverFollowup,
        latest_learning_blocker: leftoverBlocker,
        latest_training_handoff: {
          workspace_id: 'workspace-a',
          card_title: leftoverCard,
          success_signal: leftoverSignal,
          return_with: leftoverReturn,
          blocked_by: leftoverBlocker,
          handoff_summary: leftoverSummary,
          next_after_completion: leftoverNextAfter,
          fallback_action: leftoverFallback,
          handoff_status: 'ready_to_return',
        },
        latest_training_next_hop: {
          workspace_id: 'workspace-a',
          title: leftoverNextHopTitle,
          card_title: leftoverNextHopCard,
          next_after_completion: leftoverNextAfter,
          fallback_action: leftoverFallback,
          status: 'surfaced',
        },
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: liveStep,
          why_now: 'Expired tokens still leak.',
          resume_state: 'waiting',
          evidence_binding: 'ev-return-a',
        },
        preferred_rhythm: leftoverRhythm,
        preferred_learning_mode: leftoverLearningMode,
        learner_name: leftoverLearner,
        project_context: leftoverProject,
        onboarding_request: leftoverOnboarding,
        coach_defaults: {
          memory_scope: 'personal',
          working_set_mode: 'broad',
          review_cadence: 'active',
          review_reminder_mode: 'ahead',
        },
        sandbox_preview: {
          path: 'F:\\workspace-a\\notes.md',
          title: leftoverSandboxTitle,
          excerpt: 'A leftover sandbox preview',
        },
        latest_streaming_checkpoint: {
          workspace_id: 'workspace-a',
          provider_name: 'Local Compatible',
          base_url: 'http://localhost:1234/v1',
          model: 'demo-model',
          request_id: 'stream-leftover-a',
          stream_message_id: leftoverStream,
          phase: 'interrupted',
          stop_reason: leftoverStreamInterrupt,
          error: leftoverStreamInterrupt,
        },
      },
      evidence_queue: {
        pending: [
          {
            id: 'ev-return-a',
            workspace_id: 'workspace-a',
            summary: 'Focused auth check passed.',
            source: 'training_handoff_return',
            source_card_id: 'card-growth-a',
            concepts: [liveStep],
            outcome: 'pass',
            verified: true,
          },
        ],
        deferred: [],
        adopted: [],
        rejected: [],
        history: [],
        totalCount: 1,
      },
    },
  });
  assert.equal(live.planRuntimeStatus?.recovered, true);
  assert.equal(live.planRuntimeStatus?.currentStep, liveStep);
  assert.equal(live.memory.evidenceQueue?.pending?.[0]?.id, 'ev-return-a');
  assert.equal(live.memory.workspace.latestPlanRuntime?.evidenceBinding, 'ev-return-a');
  assert.equal(live.memory.workspace.latestPlanRuntime?.resumeState, 'waiting');
  assert.notEqual(live.workspaceTrainingState?.selectedCardTitle, leftoverSelected);
  assert.notEqual(live.workspaceTrainingState?.latestTrainingHandoff?.successSignal, leftoverSignal);
  assert.notEqual(live.workspaceTrainingState?.latestTrainingHandoff?.cardTitle, leftoverCard);
  assert.notEqual(live.workspaceTrainingState?.latestTrainingHandoff?.handoffSummary, leftoverSummary);
  assert.notEqual(live.workspaceTrainingState?.latestTrainingHandoff?.nextAfterCompletion, leftoverNextAfter);
  assert.notEqual(live.workspaceTrainingState?.latestTrainingNextHop?.title, leftoverNextHopTitle);
  assert.equal(live.workspaceTrainingState?.latestTrainingNextHop?.status, 'surfaced');
  assert.notEqual(live.profile.preferredRhythm, leftoverRhythm);
  assert.notEqual(live.profile.preferredLearningMode, leftoverLearningMode);
  assert.notEqual(live.profile.learnerName, leftoverLearner);
  assert.notEqual(live.profile.targetProject, leftoverProject);
  assert.notEqual(live.profile.projectContext, leftoverProject);
  assert.notEqual(live.profile.onboardingRequest, leftoverOnboarding);
  assert.notEqual(live.memory.workspace.preferredRhythm, leftoverRhythm);
  assert.notEqual(live.memory.workspace.learnerName, leftoverLearner);
  assert.notEqual(live.memory.workspace.projectContext, leftoverProject);
  assert.notEqual(live.memory.workspace.onboardingRequest, leftoverOnboarding);
  assert.notEqual(live.memory.workspace.coachDefaults?.memoryScope, 'personal');
  assert.notEqual(live.memory.workspace.coachDefaults?.reviewCadence, 'active');
  assert.notEqual(live.memory.sandboxPreview?.title, leftoverSandboxTitle);
  assert.notEqual(live.memory.sandboxState?.selectedPath, leftoverSandboxPath);
  assert.notEqual(live.memory.sandboxState?.rootPath, leftoverSandboxRoot);
  assert.notEqual(live.resources?.[0]?.title, leftoverLibraryTitle);
  assert.deepEqual(live.resources ?? [], []);
  assert.equal(live.conversation?.[0]?.body, leftoverConversation);
  assert.equal(live.memory.activeThread?.focusArea, leftoverConversationFocus);
  assert.equal(live.memory.activeThread?.summary, leftoverConversationThread);
  assert.equal((live.suggestedActions ?? []).some((item) => item.action === 'task'), false);
  assert.equal((live.suggestedActions ?? []).some((item) => item.action === 'plan'), false);
  assert.equal((live.suggestedActions ?? []).some((item) => item.action === 'next_task'), false);
  assert.notEqual(live.suggestedActions?.[0]?.label, leftoverSuggestedAction);
  assert.equal(
    live.memory.workspaceUnderstanding?.firstLookSummary?.recommendedNextStep,
    leftoverFirstLookNext,
  );
  assert.equal(live.memory.workspaceUnderstanding?.firstLookSummary?.whyThisGuess, leftoverFirstLookWhy);
  assert.equal(live.evaluation?.headline, leftoverEvaluationHeadline);
  assert.equal(live.memory.workspace.latestStreamingCheckpoint?.streamMessageId, leftoverStream);
  assert.equal(live.memory.workspace.latestStreamingCheckpoint?.error, leftoverStreamInterrupt);
  assert.equal(live.streamingState?.streamError, leftoverStreamInterrupt);
  assert.equal(live.streamingState?.streamMessageId, leftoverStream);
  assert.equal(live.coachOrientation?.primaryAction, 'resume_checkpoint');
  assert.equal(live.coachOrientation?.objectLabel, leftoverStream);

  const matchingIncoming = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    plan_runtime_status: {
      workspace_id: 'workspace-a',
      recovered: true,
      current_step: liveStep,
    },
    suggested_actions: [
      {
        id: 'suggested-leftover-a',
        label: leftoverSuggestedAction,
        action: 'task',
      },
    ],
    evaluation: {
      workspace_id: 'workspace-a',
      headline: leftoverEvaluationHeadline,
      summary: leftoverEvaluationHeadline,
    },
    messages: [
      {
        id: 'msg-leftover-a',
        role: 'assistant',
        content: leftoverConversation,
        workspace_id: 'workspace-a',
      },
    ],
    memory: {
      workspace_understanding: {
        first_look_summary: {
          recommended_next_step: leftoverFirstLookNext,
          why_this_guess: leftoverFirstLookWhy,
          folder_role: 'existing_engineering',
          project_type_guess: 'api_service',
          classification_method: 'heuristic',
        },
      },
      active_thread: {
        workspace_id: 'workspace-a',
        focus_area: leftoverConversationFocus,
        summary: leftoverConversationThread,
        next_step: leftoverConversationNext,
      },
      sandbox_state: {
        root_path: leftoverSandboxRoot,
        selected_path: leftoverSandboxPath,
        ready: true,
        linked_resource_count: 3,
        total_files: 4,
      },
      resources: [
        {
          id: 'resource-leftover-a',
          title: leftoverLibraryTitle,
          kind: 'markdown',
          status: 'ready',
          summary: 'A leftover library item',
        },
      ],
      selected_resource_detail: {
        id: 'resource-a',
        title: leftoverResourceTitle,
        kind: 'markdown',
        status: 'ready',
        summary: 'A leftover resource',
      },
      active_training_card_routing: {
        workspace_id: 'workspace-a',
        next_after_completion: liveStep,
        fallback_action: liveStep,
        why_this_card: liveStep,
      },
      workspace: {
        workspace_id: 'workspace-a',
        selected_card_title: liveStep,
        latest_learning_followup: liveStep,
        latest_learning_blocker: liveStep,
        latest_training_handoff: {
          workspace_id: 'workspace-a',
          card_title: liveStep,
          success_signal: liveStep,
          return_with: liveStep,
          blocked_by: liveStep,
          handoff_summary: liveStep,
          next_after_completion: liveStep,
          fallback_action: liveStep,
          return_summary: liveStep,
          handoff_status: 'ready_to_return',
        },
        latest_training_next_hop: {
          workspace_id: 'workspace-a',
          title: liveStep,
          card_title: liveStep,
          next_after_completion: liveStep,
          fallback_action: liveStep,
          return_summary: liveStep,
          summary: liveStep,
          why_now: liveStep,
          status: 'surfaced',
        },
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: liveStep,
          resume_state: 'waiting',
          evidence_binding: 'ev-return-a',
        },
        preferred_rhythm: leftoverRhythm,
        preferred_learning_mode: leftoverLearningMode,
        learner_name: leftoverLearner,
        project_context: leftoverProject,
        onboarding_request: leftoverOnboarding,
        coach_defaults: {
          memory_scope: 'personal',
          working_set_mode: 'broad',
          review_cadence: 'active',
          review_reminder_mode: 'ahead',
        },
        sandbox_preview: {
          path: 'F:\\workspace-a\\notes.md',
          title: leftoverSandboxTitle,
          excerpt: 'A leftover sandbox preview',
        },
        latest_streaming_checkpoint: {
          workspace_id: 'workspace-a',
          provider_name: 'Local Compatible',
          base_url: 'http://localhost:1234/v1',
          model: 'demo-model',
          request_id: 'stream-leftover-a',
          stream_message_id: leftoverStream,
          phase: 'interrupted',
          stop_reason: leftoverStreamInterrupt,
          error: leftoverStreamInterrupt,
        },
      },
    },
  });
  assert.notEqual(matchingIncoming.workspaceTrainingState?.selectedCardTitle, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestTrainingHandoff?.cardTitle, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestTrainingHandoff?.successSignal, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestTrainingHandoff?.returnWith, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestLearningFollowup, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestLearningBlocker, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestTrainingHandoff?.handoffSummary, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestTrainingHandoff?.nextAfterCompletion, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestTrainingHandoff?.fallbackAction, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestTrainingNextHop?.title, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestTrainingNextHop?.cardTitle, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestTrainingNextHop?.nextAfterCompletion, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestTrainingHandoff?.returnSummary, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestTrainingNextHop?.summary, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.latestTrainingNextHop?.whyNow, liveStep);
  assert.notEqual(matchingIncoming.workspaceTrainingState?.activeTrainingCardRouting?.whyThisCard, liveStep);
  assert.notEqual(matchingIncoming.memory.selectedResourceDetail?.title, leftoverResourceTitle);
  assert.notEqual(matchingIncoming.profile.preferredRhythm, leftoverRhythm);
  assert.notEqual(matchingIncoming.profile.learnerName, leftoverLearner);
  assert.notEqual(matchingIncoming.profile.onboardingRequest, leftoverOnboarding);
  assert.notEqual(matchingIncoming.memory.workspace.coachDefaults?.memoryScope, 'personal');
  assert.notEqual(matchingIncoming.memory.sandboxPreview?.title, leftoverSandboxTitle);
  assert.notEqual(matchingIncoming.memory.sandboxState?.selectedPath, leftoverSandboxPath);
  assert.notEqual(matchingIncoming.resources?.[0]?.title, leftoverLibraryTitle);
  assert.deepEqual(matchingIncoming.resources ?? [], []);
  assert.equal(matchingIncoming.conversation?.[0]?.body, leftoverConversation);
  assert.equal(matchingIncoming.memory.activeThread?.focusArea, leftoverConversationFocus);
  assert.equal((matchingIncoming.suggestedActions ?? []).some((item) => item.action === 'task'), false);
  assert.equal((matchingIncoming.suggestedActions ?? []).some((item) => item.action === 'plan'), false);
  assert.equal((matchingIncoming.suggestedActions ?? []).some((item) => item.action === 'next_task'), false);
  assert.notEqual(matchingIncoming.suggestedActions?.[0]?.label, leftoverSuggestedAction);
  assert.equal(
    matchingIncoming.memory.workspaceUnderstanding?.firstLookSummary?.recommendedNextStep,
    leftoverFirstLookNext,
  );
  assert.equal(matchingIncoming.evaluation?.headline, leftoverEvaluationHeadline);
  assert.equal(matchingIncoming.memory.workspace.latestStreamingCheckpoint?.streamMessageId, leftoverStream);
  assert.equal(matchingIncoming.streamingState?.streamError, leftoverStreamInterrupt);
  assert.equal(matchingIncoming.coachOrientation?.primaryAction, 'resume_checkpoint');
  assert.notEqual(
    matchingIncoming.workspaceTrainingState?.activeTrainingCardRouting?.nextAfterCompletion,
    liveStep,
  );
  assert.equal(matchingIncoming.workspaceTrainingState?.latestTrainingHandoff?.handoffStatus, 'ready_to_return');
  assert.equal(matchingIncoming.workspaceTrainingState?.latestTrainingNextHop?.status, 'surfaced');
  assert.equal(matchingIncoming.workspaceTrainingState?.selectedCardId, undefined);

  const patchB = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-b',
    memory: {
      workspace: {
        workspace_id: 'workspace-b',
      },
    },
  });
  assert.notEqual(patchB.workspaceTrainingState?.selectedCardTitle, leftoverSelected);
  assert.notEqual(patchB.workspaceTrainingState?.latestTrainingHandoff?.cardTitle, leftoverCard);
  assert.notEqual(patchB.workspaceTrainingState?.latestTrainingHandoff?.successSignal, leftoverSignal);
  assert.notEqual(patchB.workspaceTrainingState?.latestLearningFollowup, leftoverFollowup);
  assert.notEqual(patchB.workspaceTrainingState?.latestLearningBlocker, leftoverBlocker);
  assert.notEqual(patchB.workspaceTrainingState?.latestTrainingHandoff?.handoffSummary, leftoverSummary);
  assert.notEqual(patchB.workspaceTrainingState?.latestTrainingHandoff?.nextAfterCompletion, leftoverNextAfter);
  assert.notEqual(patchB.workspaceTrainingState?.latestTrainingNextHop?.title, leftoverNextHopTitle);
  assert.notEqual(patchB.workspaceTrainingState?.activeTrainingCardRouting?.fallbackAction, leftoverFallback);
  assert.notEqual(patchB.profile?.preferredRhythm, leftoverRhythm);
  assert.notEqual(patchB.profile?.learnerName, leftoverLearner);
  assert.notEqual(patchB.profile?.onboardingRequest, leftoverOnboarding);
  assert.notEqual(patchB.profile?.projectContext, leftoverProject);
  assert.notEqual(patchB.memory?.workspace?.coachDefaults?.memoryScope, 'personal');
  assert.notEqual(patchB.memory?.sandboxPreview?.title, leftoverSandboxTitle);
  assert.notEqual(patchB.memory?.sandboxState?.selectedPath, leftoverSandboxPath);
  assert.notEqual(patchB.resources?.[0]?.title, leftoverLibraryTitle);
  assert.notEqual(patchB.conversation?.[0]?.body, leftoverConversation);
  assert.notEqual(patchB.memory?.activeThread?.focusArea, leftoverConversationFocus);
  assert.notEqual(patchB.suggestedActions?.[0]?.label, leftoverSuggestedAction);
  assert.notEqual(
    patchB.memory?.workspaceUnderstanding?.firstLookSummary?.recommendedNextStep,
    leftoverFirstLookNext,
  );
  assert.notEqual(patchB.evaluation?.headline, leftoverEvaluationHeadline);
  assert.notEqual(patchB.memory?.workspace?.latestStreamingCheckpoint?.streamMessageId, leftoverStream);
  assert.notEqual(patchB.streamingState?.streamError, leftoverStreamInterrupt);
  assert.notEqual(patchB.coachOrientation?.objectLabel, leftoverStream);
  assert.notEqual(patchB.coachOrientation?.primaryAction, 'resume_checkpoint');
});

test('mergeMemorySummary does not paint leftover one-scene transfer as transferable when recovered current_step is empty', () => {
  const leftoverConcept = 'Keep the leftover A transfer skill';
  const leftoverWhy = 'Keep the leftover A transfer why';
  const leftoverNext = 'Keep the leftover A transfer next';
  const liveStep = 'Add a token expiry test';
  const bootstrap = leftoverAIdentityBootstrap();
  const leftoverTransfer = {
    concept: leftoverConcept,
    state: 'transferable',
    sceneCount: 1,
    workspaceIds: ['workspace-a'],
    sceneKeys: ['default'],
    why: leftoverWhy,
    next: leftoverNext,
  };
  bootstrap.workspaceTrainingState = {
    ...bootstrap.workspaceTrainingState,
    latestTransferState: leftoverTransfer,
  };
  bootstrap.memory.workspace.latestTransferState = leftoverTransfer;

  const patchA = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    plan_runtime_status: {
      workspace_id: 'workspace-a',
      recovered: true,
      current_step: '',
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: '',
          resume_state: 'in_progress',
        },
        latest_transfer_state: {
          concept: leftoverConcept,
          state: 'transferable',
          scene_count: 1,
          workspace_ids: ['workspace-a'],
          scene_keys: ['default'],
          why: leftoverWhy,
          next: leftoverNext,
        },
      },
    },
  });

  assert.equal(patchA.planRuntimeStatus?.recovered, true);
  assert.equal(patchA.planRuntimeStatus?.currentStep, undefined);
  assert.notEqual(patchA.memory.workspace.latestTransferState?.state, 'transferable');
  assert.notEqual(patchA.workspaceTrainingState?.latestTransferState?.state, 'transferable');
  assert.equal(patchA.memory.workspace.latestTransferState?.state, 'awaiting_second_scene');
  assert.equal(patchA.workspaceTrainingState?.latestTransferState?.state, 'awaiting_second_scene');
  assert.notEqual(patchA.memory.workspace.latestTransferState?.next, leftoverNext);
  assert.notEqual(patchA.memory.workspace.latestTransferState?.why, leftoverWhy);
  assert.notEqual(patchA.workspaceTrainingState?.latestTransferState?.next, leftoverNext);
  assert.deepEqual(patchA.memory.workspace.latestTransferState?.workspaceIds, ['workspace-a']);

  const realMulti = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    plan_runtime_status: {
      workspace_id: 'workspace-a',
      recovered: true,
      current_step: '',
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: '',
          resume_state: 'in_progress',
        },
        latest_transfer_state: {
          concept: leftoverConcept,
          state: 'transferable',
          scene_count: 2,
          workspace_ids: ['workspace-a', 'workspace-c'],
          scene_keys: ['default', 'workspace:workspace-c'],
          why: leftoverWhy,
          next: leftoverNext,
        },
      },
    },
  });
  assert.equal(realMulti.planRuntimeStatus?.recovered, true);
  assert.equal(realMulti.planRuntimeStatus?.currentStep, undefined);
  assert.equal(realMulti.memory.workspace.latestTransferState?.state, 'transferable');
  assert.deepEqual(realMulti.memory.workspace.latestTransferState?.workspaceIds, [
    'workspace-a',
    'workspace-c',
  ]);

  const live = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-a',
    plan_runtime_status: {
      workspace_id: 'workspace-a',
      recovered: true,
      current_step: liveStep,
    },
    memory: {
      workspace: {
        workspace_id: 'workspace-a',
        latest_plan_runtime: {
          workspace_id: 'workspace-a',
          current_step: liveStep,
          why_now: 'Expired tokens still leak.',
          resume_state: 'waiting',
        },
        latest_transfer_state: {
          concept: leftoverConcept,
          state: 'transferable',
          scene_count: 2,
          workspace_ids: ['workspace-a', 'workspace-c'],
          scene_keys: ['default', 'workspace:workspace-c'],
          why: leftoverWhy,
          next: leftoverNext,
        },
      },
    },
  });
  assert.equal(live.planRuntimeStatus?.recovered, true);
  assert.equal(live.planRuntimeStatus?.currentStep, liveStep);
  assert.equal(live.memory.workspace.latestTransferState?.state, 'transferable');
  assert.equal(live.workspaceTrainingState?.latestTransferState?.state, 'transferable');

  const patchB = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-b',
    memory: {
      workspace: {
        workspace_id: 'workspace-b',
      },
    },
  });
  assert.notEqual(patchB.memory?.workspace?.latestTransferState?.concept, leftoverConcept);
  assert.notEqual(patchB.memory?.workspace?.latestTransferState?.state, 'transferable');
  assert.notEqual(patchB.workspaceTrainingState?.latestTransferState?.next, leftoverNext);
});

test('mergeSessionStartSnapshot after adopt does not mint a formal plan when first-look is present', () => {
  const leftover = createBootstrap();
  leftover.plan = {
    id: 'plan-minted-adopt',
    title: 'Trainer plan for Understand and advance the leftover project.',
    frozen: false,
    cadence: '',
    summary: 'Understand and advance the leftover project.',
    stages: [{ id: 'stage-1', title: 'Understand', status: 'active' }],
  };
  leftover.memory.workspace = {
    ...(leftover.memory.workspace ?? {}),
    workspaceId: 'workspace-leftover',
  };
  leftover.workspaceTrainingState = {
    ...(leftover.workspaceTrainingState ?? {}),
    workspaceId: 'workspace-leftover',
  };
  const firstLookNext = 'Add a token expiry test';
  const patch = mergeSessionStartSnapshot(
    leftover,
    {
      session_id: 'session-adopted',
      context_id: 'context-adopted',
      plan: null,
      current_task: null,
      memory: {
        workspace: { workspace_id: 'context-adopted' },
        workspace_understanding: {
          first_look_summary: {
            recommended_next_step: firstLookNext,
            why_this_guess: 'auth.py already checks expired tokens.',
          },
        },
      },
    },
    'context-adopted',
  );

  assert.equal(patch.plan.id, '');
  assert.equal(patch.plan.title, '');
  assert.notEqual(patch.plan.title, leftover.plan.title);
  assert.notEqual(patch.plan.id, 'plan-minted-adopt');
  assert.equal(patch.task.title, '');
  assert.equal(
    patch.memory.workspaceUnderstanding?.firstLookSummary?.recommendedNextStep,
    firstLookNext,
  );
});

test('mergeSessionMessageSnapshot after understand does not invent a training card', () => {
  const leftover = createBootstrap();
  leftover.plan = {
    id: '',
    title: '',
    frozen: false,
    cadence: '',
    summary: '',
    stages: [],
  };
  leftover.task = { id: '', title: '' };
  leftover.memory.workspace = {
    ...(leftover.memory.workspace ?? {}),
    workspaceId: 'workspace-understand',
  };
  leftover.workspaceTrainingState = {
    ...(leftover.workspaceTrainingState ?? {}),
    workspaceId: 'workspace-understand',
    selectedCardId: undefined,
    selectedCardTitle: undefined,
    trainingCardCandidates: [],
  };
  const firstLookNext = 'Add a token expiry test';
  const patch = mergeSessionMessageSnapshot(
    leftover,
    {
      session_id: 'session-understand',
      reply: { content: 'Stay with the first-look next step. Do not invent a card.' },
      snapshot: {
        plan: null,
        current_task: null,
        memory: {
          workspace: { workspace_id: 'workspace-understand' },
          workspace_understanding: {
            first_look_summary: {
              recommended_next_step: firstLookNext,
              why_this_guess: 'auth.py already checks expired tokens.',
            },
          },
          active_training_card_routing: null,
          training_card_candidates: [],
        },
      },
    },
    'Help me understand this VS Code remote workspace first, then verify one tiny step.',
    'workspace-understand',
  ).patch;

  assert.equal(patch.workspaceTrainingState?.selectedCardId, undefined);
  assert.equal(patch.workspaceTrainingState?.selectedCardTitle, undefined);
  assert.notEqual(patch.workspaceTrainingState?.selectedCardTitle, 'Ship one invented card');
  assert.deepEqual(patch.workspaceTrainingState?.trainingCardCandidates ?? [], []);
  assert.equal(patch.plan.id, '');
  assert.equal(patch.plan.title, '');
  assert.equal(patch.task.title, '');
  assert.equal(
    patch.memory.workspaceUnderstanding?.firstLookSummary?.recommendedNextStep,
    firstLookNext,
  );
});

test('mergeSessionMessageSnapshot after understand does not invent a learning note or resource', () => {
  const leftover = createBootstrap();
  leftover.plan = {
    id: '',
    title: '',
    frozen: false,
    cadence: '',
    summary: '',
    stages: [],
  };
  leftover.task = { id: '', title: '' };
  leftover.resources = [];
  leftover.memory.workspace = {
    ...(leftover.memory.workspace ?? {}),
    workspaceId: 'workspace-understand-note',
  };
  leftover.memory.teachingObservations = [];
  const firstLookNext = 'Add a token expiry test';
  const patch = mergeSessionMessageSnapshot(
    leftover,
    {
      session_id: 'session-understand-note',
      reply: { content: 'Stay with the first-look next step. Do not invent a note or resource.' },
      snapshot: {
        plan: null,
        current_task: null,
        resources: [],
        memory: {
          workspace: { workspace_id: 'workspace-understand-note' },
          teaching_observations: [],
          workspace_understanding: {
            first_look_summary: {
              recommended_next_step: firstLookNext,
              why_this_guess: 'auth.py already checks expired tokens.',
            },
          },
        },
      },
    },
    'Help me understand this VS Code remote workspace first, then verify one tiny step.',
    'workspace-understand-note',
  ).patch;

  assert.deepEqual(patch.memory.teachingObservations ?? [], []);
  assert.notEqual(patch.memory.teachingObservations?.[0], 'Ship one invented note');
  assert.deepEqual(patch.resources ?? [], []);
  assert.equal(patch.plan.id, '');
  assert.equal(patch.task.title, '');
  assert.equal(
    patch.memory.workspaceUnderstanding?.firstLookSummary?.recommendedNextStep,
    firstLookNext,
  );
});

test('mergeSessionMessageSnapshot after understand does not invent a plan', () => {
  const leftover = createBootstrap();
  leftover.plan = {
    id: '',
    title: '',
    frozen: false,
    cadence: '',
    summary: '',
    stages: [],
  };
  leftover.task = { id: '', title: '' };
  leftover.memory.workspace = {
    ...(leftover.memory.workspace ?? {}),
    workspaceId: 'workspace-understand-plan',
  };
  const firstLookNext = 'Add a token expiry test';
  const patch = mergeSessionMessageSnapshot(
    leftover,
    {
      session_id: 'session-understand-plan',
      reply: { content: 'Stay with the first-look next step. Do not invent a plan.' },
      snapshot: {
        plan: null,
        current_task: null,
        memory: {
          workspace: { workspace_id: 'workspace-understand-plan' },
          workspace_understanding: {
            first_look_summary: {
              recommended_next_step: firstLookNext,
              why_this_guess: 'auth.py already checks expired tokens.',
            },
          },
        },
      },
    },
    'Help me understand this VS Code remote workspace first, then verify one tiny step.',
    'workspace-understand-plan',
  ).patch;

  assert.equal(patch.plan.id, '');
  assert.equal(patch.plan.title, '');
  assert.notEqual(patch.plan.title, 'Ship one invented plan');
  assert.deepEqual(patch.plan.stages ?? [], []);
  assert.equal(patch.task.title, '');
  assert.equal(
    patch.memory.workspaceUnderstanding?.firstLookSummary?.recommendedNextStep,
    firstLookNext,
  );
});

test('mergeSessionMessageSnapshot after understand does not invent a task', () => {
  const leftover = createBootstrap();
  leftover.plan = {
    id: '',
    title: '',
    frozen: false,
    cadence: '',
    summary: '',
    stages: [],
  };
  leftover.task = { id: '', title: '' };
  leftover.memory.workspace = {
    ...(leftover.memory.workspace ?? {}),
    workspaceId: 'workspace-understand-task',
  };
  const firstLookNext = 'Add a token expiry test';
  const patch = mergeSessionMessageSnapshot(
    leftover,
    {
      session_id: 'session-understand-task',
      reply: { content: 'Stay with the first-look next step. Do not invent a task.' },
      snapshot: {
        plan: null,
        current_task: null,
        memory: {
          workspace: { workspace_id: 'workspace-understand-task' },
          workspace_understanding: {
            first_look_summary: {
              recommended_next_step: firstLookNext,
              why_this_guess: 'auth.py already checks expired tokens.',
            },
          },
        },
      },
    },
    'What should I do next after this slice?',
    'workspace-understand-task',
  ).patch;

  assert.equal(patch.task.title, '');
  assert.equal(patch.task.id, '');
  assert.notEqual(patch.task.title, 'Ship one invented task');
  assert.equal(patch.plan.id, '');
  assert.equal(patch.plan.title, '');
  assert.equal(
    patch.memory.workspaceUnderstanding?.firstLookSummary?.recommendedNextStep,
    firstLookNext,
  );
});

test('mergeSessionMessage surfaces pressure_blocks_live_object_mint as camelCase', () => {
  const bootstrap = createBootstrap();
  const { patch } = mergeSessionMessage(
    bootstrap,
    {
      session_id: 'session-pressure-stamp',
      reply: {
        content: 'Stay with one thin repair slice.',
        metadata: {
          coach_focus: {
            pressure_blocks_live_object_mint: true,
          },
        },
      },
      agent_meta: {
        pressure_blocks_live_object_mint: true,
      },
      snapshot: {
        messages: [],
        memory: {
          coaching_adaptation: {
            time_budget: 'normal',
            task_urgency: 'medium',
          },
        },
      },
    },
    'Create a practice card under pressure.',
  );

  assert.equal(patch.memory.coachingAdaptation?.pressureBlocksLiveObjectMint, true);
  assert.equal(patch.coachFocus?.pressureBlocksLiveObjectMint, true);
  assert.equal(patch.memory.coachingAdaptation?.timeBudget, 'normal');
  assert.equal(patch.memory.coachingAdaptation?.taskUrgency, 'medium');
});

test('mergeSessionMessage surfaces streak_blocks_live_object_mint as camelCase', () => {
  const bootstrap = createBootstrap();
  const { patch } = mergeSessionMessage(
    bootstrap,
    {
      session_id: 'session-streak-stamp',
      reply: {
        content: 'Adapt hints only. Do not mint a live object.',
        metadata: {
          coach_focus: {
            streak_blocks_live_object_mint: true,
          },
        },
      },
      agent_meta: {
        streak_blocks_live_object_mint: true,
      },
      snapshot: {
        messages: [],
        memory: {
          coaching_adaptation: {
            time_budget: 'normal',
            task_urgency: 'medium',
          },
        },
      },
    },
    'Give me the next challenge after a streak.',
  );

  assert.equal(patch.memory.coachingAdaptation?.streakBlocksLiveObjectMint, true);
  assert.equal(patch.coachFocus?.streakBlocksLiveObjectMint, true);
  assert.equal(patch.memory.coachingAdaptation?.timeBudget, 'normal');
  assert.equal(patch.memory.coachingAdaptation?.taskUrgency, 'medium');
});

test('fast-path memory summary rehydrate keeps pressure/streak stamps and leftover recovered', () => {
  // Performance/hydrate shortcuts must not drop honesty stamps already on the host.
  const bootstrap = createBootstrap();
  bootstrap.memory.workspace = {
    ...bootstrap.memory.workspace,
    workspaceId: 'workspace-fast-path-honesty',
  };
  bootstrap.workspaceTrainingState = { workspaceId: 'workspace-fast-path-honesty' };
  bootstrap.memory.coachingAdaptation = {
    ...(bootstrap.memory.coachingAdaptation ?? {}),
    timeBudget: 'tight',
    taskUrgency: 'high',
    pressureBlocksLiveObjectMint: true,
    streakBlocksLiveObjectMint: true,
  };
  bootstrap.coachFocus = {
    ...(bootstrap.coachFocus ?? {}),
    pressureBlocksLiveObjectMint: true,
    streakBlocksLiveObjectMint: true,
  };
  bootstrap.planRuntimeStatus = {
    ...(bootstrap.planRuntimeStatus ?? {}),
    recovered: true,
    planId: null,
    currentStep: '',
  };
  bootstrap.plan = {
    ...(bootstrap.plan ?? {}),
    id: '',
    title: '',
    currentStep: '',
    stages: [],
  };

  const patch = mergeMemorySummary(bootstrap, {
    context_id: 'workspace-fast-path-honesty',
    memory: {
      workspace: {
        workspace_id: 'workspace-fast-path-honesty',
      },
      coaching_adaptation: {
        time_budget: 'tight',
        task_urgency: 'high',
      },
    },
    plan_runtime_status: {
      recovered: true,
      current_step: '',
    },
  });

  assert.equal(patch.memory.coachingAdaptation?.pressureBlocksLiveObjectMint, true);
  assert.equal(patch.memory.coachingAdaptation?.streakBlocksLiveObjectMint, true);
  assert.equal(patch.planRuntimeStatus?.recovered, true);
});

test('mergeSessionMessage surfaces closed_loop_return_blocks_task_mint as camelCase', () => {
  const bootstrap = createBootstrap();
  const { patch } = mergeSessionMessage(
    bootstrap,
    {
      session_id: 'session-return-stamp',
      reply: {
        content: 'Stay with the live plan step. Do not mint a task.',
        metadata: {
          coach_focus: {
            closed_loop_return_blocks_task_mint: true,
          },
        },
      },
      agent_meta: {
        closed_loop_return_blocks_task_mint: true,
      },
      snapshot: {
        messages: [],
        memory: {
          coaching_adaptation: {
            time_budget: 'normal',
            task_urgency: 'medium',
          },
        },
      },
    },
    'Give me the next challenge after return.',
  );

  assert.equal(patch.memory.coachingAdaptation?.closedLoopReturnBlocksTaskMint, true);
  assert.equal(patch.coachFocus?.closedLoopReturnBlocksTaskMint, true);
  assert.equal(patch.memory.coachingAdaptation?.timeBudget, 'normal');
  assert.equal(patch.memory.coachingAdaptation?.taskUrgency, 'medium');
});

test('mergeSessionStartSnapshot same-workspace plan:null clears leftover live plan and marks leftover-not-live', () => {
  const leftover = createBootstrap();
  leftover.plan = {
    id: 'plan-leftover-same-ws',
    title: 'Keep the leftover stage',
    frozen: false,
    cadence: '',
    summary: 'Stored leftover formal plan',
    currentStep: 'Keep one auth check',
    stages: [{ id: 'stage-leftover', title: 'Leftover', status: 'active' }],
  };
  leftover.task = { id: 'task-leftover', title: 'Leftover task title' };
  leftover.memory.workspace = {
    ...(leftover.memory.workspace ?? {}),
    workspaceId: 'workspace-start-leftover',
  };
  leftover.workspaceTrainingState = {
    ...(leftover.workspaceTrainingState ?? {}),
    workspaceId: 'workspace-start-leftover',
  };
  const patch = mergeSessionStartSnapshot(
    leftover,
    {
      session_id: 'session-start-leftover',
      context_id: 'workspace-start-leftover',
      plan: null,
      current_task: null,
      plan_runtime_status: {
        recovered: false,
        current_step: '',
        plan_id: null,
      },
      suggested_actions: [
        { id: 'sa-plan', label: 'Generate plan', action: 'plan' },
        { id: 'sa-task', label: 'Next task', action: 'task' },
        { id: 'sa-next', label: 'Next task hop', action: 'next_task' },
        { id: 'sa-card', label: 'Mint card', action: 'card' },
        { id: 'sa-hint', label: 'Smaller hint', action: 'hint' },
      ],
      memory: {
        workspace: { workspace_id: 'workspace-start-leftover' },
      },
    },
    'workspace-start-leftover',
  );

  assert.equal(patch.plan.id, '');
  assert.equal(patch.plan.title, '');
  assert.equal(patch.plan.currentStep || '', '');
  assert.notEqual(patch.plan.id, 'plan-leftover-same-ws');
  assert.equal(patch.task.title, '');
  assert.equal(patch.planRuntimeStatus?.recovered, true);
  const actions = (patch.suggestedActions ?? []).map((item) => item.action);
  assert.ok(!actions.includes('plan'));
  assert.ok(!actions.includes('task'));
  assert.ok(!actions.includes('next_task'));
  assert.ok(!actions.includes('card'));
  // Empty recovered step: leftover-not-live clears suggested-action theater (Open Coach / generate is Plan primary).
  assert.deepEqual(actions, []);
});

test('mergeSessionStartSnapshot mismatch recovered + plan:null keeps recovered overlay without resurrecting leftover plan', () => {
  const leftover = createBootstrap();
  leftover.plan = {
    id: 'plan-leftover-mismatch',
    title: 'Keep the leftover stage',
    frozen: false,
    cadence: '',
    summary: 'Stored leftover',
    currentStep: 'Keep one auth check',
    stages: [{ id: 'stage-leftover', title: 'Leftover', status: 'active' }],
  };
  leftover.memory.workspace = {
    ...(leftover.memory.workspace ?? {}),
    workspaceId: 'workspace-start-mismatch',
  };
  leftover.workspaceTrainingState = {
    ...(leftover.workspaceTrainingState ?? {}),
    workspaceId: 'workspace-start-mismatch',
  };
  const recoveredStep = 'Add a token expiry test';
  const patch = mergeSessionStartSnapshot(
    leftover,
    {
      session_id: 'session-start-mismatch',
      context_id: 'workspace-start-mismatch',
      plan: null,
      current_task: null,
      plan_runtime_status: {
        recovered: true,
        current_step: recoveredStep,
        plan_id: 'plan-other-runtime',
        resume_state: 'in_progress',
      },
      memory: {
        workspace: {
          workspace_id: 'workspace-start-mismatch',
          latest_plan_runtime: {
            workspace_id: 'workspace-start-mismatch',
            plan_id: 'plan-other-runtime',
            current_step: recoveredStep,
            resume_state: 'in_progress',
          },
        },
      },
      suggested_actions: [
        { id: 'sa-plan', label: 'Generate plan', action: 'plan' },
        { id: 'sa-hint', label: 'Continue recovered step', action: 'hint' },
      ],
    },
    'workspace-start-mismatch',
  );

  assert.equal(patch.plan.id, '');
  assert.equal(patch.plan.title, '');
  assert.equal(patch.planRuntimeStatus?.recovered, true);
  assert.equal(patch.planRuntimeStatus?.currentStep, recoveredStep);
  assert.equal(patch.memory.workspace?.latestPlanRuntime?.planId, 'plan-other-runtime');
  const actions = (patch.suggestedActions ?? []).map((item) => item.action);
  assert.ok(!actions.includes('plan'));
  assert.ok(actions.includes('hint'));
});

test('mergeSessionStartSnapshot cold host empty plan consumes server recovered stamp without prior leftover', () => {
  const empty = createBootstrap();
  empty.plan = {
    id: '',
    title: '',
    frozen: false,
    cadence: '',
    summary: '',
    currentStep: '',
    stages: [],
  };
  empty.planRuntimeStatus = {
    reviewPoints: [],
    recovered: false,
    currentStep: '',
  };
  empty.memory.workspace = {
    ...(empty.memory.workspace ?? {}),
    workspaceId: 'workspace-cold-leftover-stamp',
  };
  empty.workspaceTrainingState = {
    ...(empty.workspaceTrainingState ?? {}),
    workspaceId: 'workspace-cold-leftover-stamp',
  };
  const patch = mergeSessionStartSnapshot(
    empty,
    {
      session_id: 'session-cold-leftover-stamp',
      context_id: 'workspace-cold-leftover-stamp',
      plan: null,
      current_task: null,
      plan_runtime_status: {
        recovered: true,
        current_step: '',
        plan_id: null,
      },
      suggested_actions: [
        { id: 'sa-plan', label: 'Generate plan', action: 'plan' },
        { id: 'sa-card', label: 'Mint card', action: 'card' },
        { id: 'sa-hint', label: 'Smaller hint', action: 'hint' },
      ],
      memory: {
        workspace: { workspace_id: 'workspace-cold-leftover-stamp' },
      },
    },
    'workspace-cold-leftover-stamp',
  );

  assert.equal(patch.plan.id, '');
  assert.equal(patch.plan.title, '');
  assert.equal(patch.planRuntimeStatus?.recovered, true);
  const actions = (patch.suggestedActions ?? []).map((item) => item.action);
  assert.ok(!actions.includes('plan'));
  assert.ok(!actions.includes('card'));
});

test('mergeSessionStartSnapshot camelCase planRuntimeStatus.recovered stamp also lights leftover overlay', () => {
  const empty = createBootstrap();
  empty.plan = {
    id: '',
    title: '',
    frozen: false,
    cadence: '',
    summary: '',
    currentStep: '',
    stages: [],
  };
  empty.planRuntimeStatus = { reviewPoints: [], recovered: false };
  empty.memory.workspace = {
    ...(empty.memory.workspace ?? {}),
    workspaceId: 'workspace-camel-recovered-stamp',
  };
  const patch = mergeSessionStartSnapshot(
    empty,
    {
      session_id: 'session-camel-recovered-stamp',
      context_id: 'workspace-camel-recovered-stamp',
      plan: null,
      planRuntimeStatus: {
        recovered: true,
        currentStep: '',
        planId: null,
      },
      memory: {
        workspace: { workspace_id: 'workspace-camel-recovered-stamp' },
      },
    },
    'workspace-camel-recovered-stamp',
  );

  assert.equal(patch.plan.id, '');
  assert.equal(patch.planRuntimeStatus?.recovered, true);
});

test('mergeMemorySummarySnapshot omit plan keeps live plan and selected_card_id chrome', () => {
  // Evaluate → /memory/summary often omits plan; must not treat missing key as plan:null.
  const ws = 'workspace-omit-vs-null';
  const live = createBootstrap();
  live.plan = {
    id: 'plan-live-omit',
    title: 'Live omit plan',
    frozen: false,
    cadence: '',
    summary: 'Live formal plan',
    currentStep: 'Keep the live training chrome',
    stages: [{ id: 'stage-live', title: 'Live', status: 'active' }],
  };
  live.planRuntimeStatus = {
    reviewPoints: [],
    recovered: false,
    currentStep: 'Keep the live training chrome',
    planId: 'plan-live-omit',
  };
  live.memory.workspace = {
    ...(live.memory.workspace ?? {}),
    workspaceId: ws,
  };
  live.workspaceTrainingState = {
    ...(live.workspaceTrainingState ?? {}),
    workspaceId: ws,
    selectedCardId: 'card-live-omit',
    selectedCardTitle: 'Keep the live card',
  };
  const patch = mergeMemorySummarySnapshot(
    live,
    {
      session_id: 'session-omit-plan',
      context_id: ws,
      // plan / current_task intentionally omitted
      memory: {
        workspace: { workspace_id: ws },
      },
    },
    ws,
  );

  assert.equal(patch.plan.id, 'plan-live-omit');
  assert.equal(patch.plan.title, 'Live omit plan');
  assert.equal(patch.plan.currentStep, 'Keep the live training chrome');
  assert.equal(patch.workspaceTrainingState?.selectedCardId, 'card-live-omit');
  assert.notEqual(patch.planRuntimeStatus?.recovered, true);
});

test('mergeMemorySummarySnapshot explicit plan:null clears live plan with recovered overlay', () => {
  const ws = 'workspace-null-vs-omit';
  const live = createBootstrap();
  live.plan = {
    id: 'plan-live-null',
    title: 'Stored leftover plan',
    frozen: false,
    cadence: '',
    summary: 'Stored leftover formal plan',
    currentStep: 'Keep one auth check',
    stages: [{ id: 'stage-leftover', title: 'Leftover', status: 'active' }],
  };
  live.planRuntimeStatus = {
    reviewPoints: [],
    recovered: false,
    currentStep: 'Keep one auth check',
    planId: 'plan-live-null',
  };
  live.memory.workspace = {
    ...(live.memory.workspace ?? {}),
    workspaceId: ws,
  };
  live.workspaceTrainingState = {
    ...(live.workspaceTrainingState ?? {}),
    workspaceId: ws,
    selectedCardId: 'card-leftover-null',
    selectedCardTitle: 'Leftover card chrome',
  };
  const patch = mergeMemorySummarySnapshot(
    live,
    {
      session_id: 'session-null-plan',
      context_id: ws,
      plan: null,
      current_task: null,
      plan_runtime_status: {
        recovered: false,
        current_step: '',
        plan_id: null,
      },
      memory: {
        workspace: { workspace_id: ws },
      },
    },
    ws,
  );

  assert.equal(patch.plan.id, '');
  assert.equal(patch.plan.title, '');
  assert.notEqual(patch.plan.id, 'plan-live-null');
  assert.equal(patch.planRuntimeStatus?.recovered, true);
  assert.equal(patch.workspaceTrainingState?.selectedCardId, undefined);
  assert.notEqual(patch.workspaceTrainingState?.selectedCardId, 'card-leftover-null');
});
