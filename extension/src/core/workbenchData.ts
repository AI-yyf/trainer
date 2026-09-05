import * as path from 'node:path';
import { trainerCommandCatalog } from '../../../shared/src/commands';
import {
  createEmptyTrainerStreamingState,
  normalizeNextStepHint,
  normalizeTrainerMessageParts,
} from '../../../shared/src/protocol';
import { normalizeResourceSearchMode } from '../../../shared/src/resourceSearch';
import { deriveResourceTrustState } from '../../../shared/src/resourceTrust';
import {
  defaultCapabilitiesForProtocol,
  normalizeProviderProtocol,
  providerProtocolFamily,
} from '../../../shared/src/providerProtocols';
import { providerTransportIsConfigured } from '../../../shared/src/providerStatus';
import { describeWorkspaceAuthoritySummary } from '../../../shared/src/workspaceAuthority';
import { isComposerLanguage, type ComposerLanguage } from '../../../shared/src/types';
import { normalizeCoachOrientationRecord } from '../../../shared/src/coachOrientationGovernance';
import {
  preferRecoveredCoachTaskChrome,
  preferRecoveredCoachTurnChrome,
  preferRecoveredTrainingFocusChrome,
  leftoverTrainingHandoffChromeIsNotLive,
  leftoverResourceSelectedDetailIsNotLive,
  leftoverResourceSandboxPreviewIsNotLive,
  leftoverResourceSandboxStateIsNotLive,
  leftoverResourceLibraryListIsNotLive,
  leftoverSettingsProfileRhythmIsNotLive,
  leftoverSettingsLearnerProjectOnboardingIsNotLive,
  leftoverCoachConversationIsNotLive,
  leftoverSuggestedActionsIsNotLive,
  leftoverMintingSuggestedActionsAreNotLive,
  leftoverBoundPlanCompetingIdentityLabels,
  leftoverFirstLookHeadlineIsNotLive,
  leftoverEvaluationHeadlineIsNotLive,
  leftoverStreamingCheckpointIsNotLive,
  leftoverTransferSkillIsNotLive,
  preferRecoveredTransferSkill,
  preferRecoveredTrainingHandoffChrome,
} from '../../../shared/src/planOrientationGovernance';
import { sanitizeErrorSurfaceText } from '../../../shared/src/errorSurfaceSanitizer';
import { stripHostLastTestSecrets } from '../../../shared/src/hostLastTestGovernance';
import { normalizeTransferSkillStateRecord } from '../../../shared/src/transferSkillGovernance';
import {
  normalizePlanRuntimeRecovery,
  normalizePlanRuntimeResumeState,
  normalizeProviderCapabilityRecovery,
  recoverStreamingCheckpointAfterRestart,
  selectPlanRuntimeForScope,
  planRuntimeStatusFromRecovery,
  selectProviderCapabilityForScope,
  selectStreamingCheckpointForScope,
  preferAuthoritativeProviderLastTest,
  selectTrainingChromeForScope,
  selectResourcesForScope,
  selectNextStepHintForScope,
  selectCoachingAdaptationForScope,
  isCurrentForWorkspace,
  trainingRecordMatchesWorkspace,
  type RecoveryScope,
} from '../../../shared/src/workspaceRecoveryGovernance';

import type {
  AffectStateView,
  BootstrapData,
  CapabilityFlags,
  ConversationAttachmentView,
  ConversationArtifactView,
  ConversationMessageView,
  EvaluationReportView,
  GlobalPlanProjectLinkView,
  GlobalPlanView,
  ImplementationGuideView,
  LearnerStateView,
  HostMessage,
  LiveContextView,
  LearningPlanView,
  NextStepHintView,
  PlanRuntimeStatusView,
  PrincipleNoteView,
  ProviderConfig,
  ProviderSummary,
  ProviderConfigView,
  ProviderCapabilityVerificationState,
  ProjectAdaptationGuideView,
  ProjectIdeaView,
  ProjectSourceSuggestion,
  ResourceDetailRecordView,
  ResourceRecordView,
  SandboxPreviewView,
  SandboxStateView,
  SidecarStatus,
  SubPlanView,
  SuggestedActionView,
  TaskSpecView,
  TeachingDecisionView,
  TrainerHostState,
  ToneDecisionView,
  UserProfileView,
  WorkspaceAuthorityView,
  WorkspaceSnapshot,
  EvidenceQueueView,
  EvidenceItemView,
} from './types';

type UnknownRecord = Record<string, unknown>;
type WorkspaceTrainingStateView = NonNullable<BootstrapData['workspaceTrainingState']>;
type TrainingHandoffStateView = NonNullable<WorkspaceTrainingStateView['latestTrainingHandoff']>;
type TrainingNextHopStateView = NonNullable<WorkspaceTrainingStateView['latestTrainingNextHop']>;
type TrainingCardCandidateStateView = NonNullable<WorkspaceTrainingStateView['trainingCardCandidates']>[number];
type ActiveTrainingCardRoutingStateView = NonNullable<WorkspaceTrainingStateView['activeTrainingCardRouting']>;
type TrainingBlockedCardCandidateStateView = NonNullable<
  NonNullable<ActiveTrainingCardRoutingStateView['blockedCandidates']>
>[number];
type TrainingEventLedgerEntryStateView = NonNullable<
  WorkspaceTrainingStateView['trainingEventLedger']
>[number];
type ReviewArtifactStateView = NonNullable<WorkspaceTrainingStateView['reviewArtifact']>;
type ScenarioLabStateView = NonNullable<WorkspaceTrainingStateView['scenarioLab']>;
type TheoryDrillStateView = NonNullable<WorkspaceTrainingStateView['theoryDrill']>;
type TheoryDrillQuestionStateView = NonNullable<TheoryDrillStateView['questions']>[number];
type SandboxAuthorityView = NonNullable<BootstrapData['memory']['sandboxState']>['authority'];
type WorkspaceUnderstandingView = NonNullable<BootstrapData['memory']['workspaceUnderstanding']>;
type FirstLookSummaryView = NonNullable<WorkspaceUnderstandingView['firstLookSummary']>;
type TrainerWorkspaceAdmissionStateView = NonNullable<
  NonNullable<BootstrapData['memory']['workspace']>['trainerWorkspace']
>;

const COACH_SURFACE_NOISE_MARKERS = [
  '\uFFFD',
  '\u9227',
  '\u5053',
  '\u95B8',
  '\u9420',
  '\u5A11',
  '\u7F02',
  '\u6FDE',
  '\u745C',
  '\u7EF1',
  '\u9852',
  '\u9350',
] as const;

function looksLikeCoachSurfaceNoise(value: string): boolean {
  if (!value) {
    return false;
  }
  if (/[\uE000-\uF8FF]/u.test(value)) {
    return true;
  }
  let markerHits = 0;
  for (const marker of COACH_SURFACE_NOISE_MARKERS) {
    if (value.includes(marker)) {
      markerHits += 1;
      if (markerHits >= 2) {
        return true;
      }
    }
  }
  return false;
}

function coachSurfaceText(value: unknown): string | undefined {
  const text = asString(value);
  if (!text) {
    return undefined;
  }
  const normalized = text.trim().replace(/\s+/g, ' ');
  if (!normalized || looksLikeCoachSurfaceNoise(normalized)) {
    return undefined;
  }
  return normalized;
}

export function createDefaultBootstrapData(
  workspace: WorkspaceSnapshot,
  provider?: ProviderConfig,
  sidecar?: SidecarStatus,
): BootstrapData {
  const resolvedSidecar: SidecarStatus = sidecar ?? {
    lifecycle: 'idle',
    host: '127.0.0.1',
    canStart: true,
  };
  return applyDerivedHostState(
    {
      workspaceName: workspaceName(workspace),
      sessionLabel: '新的 Trainer 会话',
      connection: {
        state: 'offline',
        provider: toProviderSummary(provider),
      },
      providerConfig: toProviderConfigView(provider, false),
      liveContext: toLiveContext(workspace),
      profile: {
        learnerName: '你',
        goals: ['先完成模型连接，再开始第一轮训练。'],
        weeklyHours: 4,
        preferredStyle: 'auto',
        answerPolicy: 'auto',
        focusAreas: [],
        targetProject: undefined,
        preferredRhythm: undefined,
        preferredLearningMode: undefined,
        onboardingRequest: undefined,
        projectContext: undefined,
      },
      plan: {
        id: 'plan-pending',
        title: '计划尚未开始',
        frozen: false,
        cadence: '每周 4 小时',
        summary: '完成模型连接后，Trainer 会根据你的项目和对话生成第一条训练主线。',
        stages: [],
      },
      task: {
        id: 'task-pending',
        title: '还没有训练任务',
        description: '先配置模型连接，然后告诉教练你想实现什么。',
        constraints: [],
        acceptanceCriteria: [],
        nextActionLabel: '先完成连接',
      },
      evaluation: {
        headline: '还没有训练评估',
        summary: '等教练开始工作后，这里会出现当前实现的判断与下一步建议。',
        passRate: 0,
        updatedAt: '未运行',
        checks: [],
        nextStep: '先完成模型连接。',
      },
      memory: {
        currentFocus: '先完成连接。',
        weakSpots: [],
        recentWins: [],
        reviewSummary: '开始几轮训练后，这里才会出现稳定的复习节奏。',
        reviewRhythm: '当前还没有复习安排。',
        dueReviews: [],
        teachingObservations: [],
        memoryEvidence: [],
        memoryShareGrants: [],
        workspace: {},
      },
      workspaceTrainingState: undefined,
      coachingState: {
        scenario: 'general',
        answerMode: 'guided',
        learnerSignal: 'steady',
        summary: '先把模型连接起来，再开始你的第一轮教练对话。',
        nextStep: '去设置里保存 provider、base URL、model 和 API key。',
        encouragement: '连通之后，我们就能把你的想法压成真正的实现步骤。',
        updatedAt: new Date().toISOString(),
      },
      learnerState: undefined,
      affectState: undefined,
      teachingDecision: undefined,
      toneDecision: undefined,
      implementationGuide: undefined,
      projectIdeas: [],
      projectAdaptationGuide: undefined,
      projectSources: [],
      principleNotes: undefined,
      coachTurn: undefined,
      coachFocus: undefined,
      coachOrientation: undefined,
      planRuntimeStatus: undefined,
      nextStepHint: undefined,
      reviewQueueSummary: '当前还没有复习安排。',
      nextReviewDue: undefined,
      streamingState: createEmptyTrainerStreamingState(),
      resources: [],
      conversation: [],
      suggestedActions: [],
      commands: trainerCommandCatalog.map((command) => ({ ...command })),
    },
    provider,
    resolvedSidecar,
    workspace,
    undefined,
  );
}

export function applyDerivedHostState(
  data: BootstrapData,
  provider: ProviderConfig | undefined,
  sidecar: SidecarStatus,
  workspace: WorkspaceSnapshot,
  sessionId: string | undefined,
  providerHasApiKey = data.providerConfig.apiKeyConfigured,
): BootstrapData {
  const baseProviderConfig = toProviderConfigView(provider, providerHasApiKey);
  const preserveProviderSupplement =
    data.providerConfig.name === baseProviderConfig.name &&
    data.providerConfig.baseUrl === baseProviderConfig.baseUrl &&
    normalizeProviderProtocol(data.providerConfig.protocol) === normalizeProviderProtocol(baseProviderConfig.protocol);

  return {
    ...data,
    workspaceName: workspaceName(workspace),
    sessionLabel: sessionId ?? data.sessionLabel,
    connection: {
      state: toConnectionState(sidecar),
      provider: toProviderSummary(provider),
    },
    providerConfig: preserveProviderSupplement
      ? {
          ...baseProviderConfig,
          availableModels: data.providerConfig.availableModels,
          resolvedModel: data.providerConfig.resolvedModel,
          modelCapabilities: data.providerConfig.modelCapabilities ?? baseProviderConfig.modelCapabilities,
          modelListStatus: data.providerConfig.modelListStatus,
          modelListDetail: data.providerConfig.modelListDetail,
          cacheFetchedAt: data.providerConfig.cacheFetchedAt,
          cacheExpiresAt: data.providerConfig.cacheExpiresAt,
          cacheSource: data.providerConfig.cacheSource,
          modelErrorCategory: data.providerConfig.modelErrorCategory,
          modelStatusCode: data.providerConfig.modelStatusCode,
          modelRetryable: data.providerConfig.modelRetryable,
          protocolDiagnostic: data.providerConfig.protocolDiagnostic,
          taskBindingDiagnostics: data.providerConfig.taskBindingDiagnostics,
          modelDiagnostics: data.providerConfig.modelDiagnostics,
          modelTest: data.providerConfig.modelTest,
          modelListing: data.providerConfig.modelListing,
          diagnostics: data.providerConfig.diagnostics,
          warnings: data.providerConfig.warnings,
          lastTestResult: isCompatibleLastTestResult(baseProviderConfig, data.providerConfig.lastTestResult)
            ? (stripHostLastTestSecrets({
                ...(data.providerConfig.lastTestResult as unknown as Record<string, unknown>),
              }) as unknown as BootstrapData['providerConfig']['lastTestResult'])
            : undefined,
        }
      : baseProviderConfig,
    liveContext: toLiveContext(workspace),
  };
}

export function mergeSessionMessage(
  current: BootstrapData,
  payload: unknown,
  userMessage: string,
): { sessionId?: string; patch: Partial<BootstrapData> } {
  const record = asRecord(payload);
  const snapshot = asRecord(record?.snapshot);
  const reply = asRecord(record?.reply);
  const replyMetadata = asRecord(reply?.metadata);
  const coachContext = asRecord(record?.coach_context ?? replyMetadata?.coach_context);
  const agentMeta = asRecord(record?.agent_meta ?? record?.agentMeta ?? record?.agent);
  const pressureBlocksLiveObjectMint =
    coachContext?.pressure_blocks_live_object_mint === true ||
    coachContext?.pressureBlocksLiveObjectMint === true ||
    agentMeta?.pressure_blocks_live_object_mint === true ||
    agentMeta?.pressureBlocksLiveObjectMint === true;
  const streakBlocksLiveObjectMint =
    coachContext?.streak_blocks_live_object_mint === true ||
    coachContext?.streakBlocksLiveObjectMint === true ||
    agentMeta?.streak_blocks_live_object_mint === true ||
    agentMeta?.streakBlocksLiveObjectMint === true;
  const closedLoopReturnBlocksTaskMint =
    coachContext?.closed_loop_return_blocks_task_mint === true ||
    coachContext?.closedLoopReturnBlocksTaskMint === true ||
    agentMeta?.closed_loop_return_blocks_task_mint === true ||
    agentMeta?.closedLoopReturnBlocksTaskMint === true;
  const snapshotPlanRuntimeStatus = asRecord(snapshot?.plan_runtime_status);
  const nextStepHintValue =
    record?.next_step_hint ??
    replyMetadata?.next_step_hint ??
    coachContext?.next_step_hint ??
    asRecord(record?.plan_runtime_status)?.next_step_hint ??
    snapshotPlanRuntimeStatus?.next_step_hint;
  const sessionId = asString(record?.session_id) ?? asString(record?.sessionId);
  const fallbackConversation = [
    ...current.conversation,
    createConversationMessage('user', '你', userMessage),
    createConversationMessage('assistant', 'Trainer', asString(reply?.content) ?? 'Trainer 已返回回复。'),
  ];
  const incomingWorkspaceId =
    asString(snapshot?.context_id) ??
    asString(snapshot?.contextId) ??
    asString(asRecord(asRecord(snapshot?.memory)?.workspace)?.workspace_id) ??
    asString(asRecord(asRecord(snapshot?.memory)?.workspace)?.workspaceId);
  const currentWorkspaceId =
    current.workspaceTrainingState?.workspaceId ?? current.memory.workspace?.workspaceId;
  const mappedMemory = snapshot
    ? mapMemory(snapshot.memory, current.memory, incomingWorkspaceId, currentWorkspaceId)
    : current.memory;
  const memoryWithPressureStamp =
    pressureBlocksLiveObjectMint === true ||
    streakBlocksLiveObjectMint === true ||
    closedLoopReturnBlocksTaskMint === true
      ? {
          ...mappedMemory,
          coachingAdaptation: {
            ...(mappedMemory.coachingAdaptation ?? emptyLiveCoachingAdaptation()),
            ...(pressureBlocksLiveObjectMint === true
              ? { pressureBlocksLiveObjectMint: true }
              : {}),
            ...(streakBlocksLiveObjectMint === true
              ? { streakBlocksLiveObjectMint: true }
              : {}),
            ...(closedLoopReturnBlocksTaskMint === true
              ? { closedLoopReturnBlocksTaskMint: true }
              : {}),
          },
        }
      : mappedMemory;
  const mappedProfile = snapshot
    ? applyWorkspaceProfileHints(
        mapProfile(snapshot.profile, current.profile),
        memoryWithPressureStamp.workspace,
      )
    : current.profile;
  const memoryEvidence =
    asStringArray(record?.memory_evidence) ??
    asStringArray(coachContext?.memory_evidence) ??
    memoryWithPressureStamp.memoryEvidence;
  const activeThread =
    mapActiveThread(record?.active_thread, undefined, incomingWorkspaceId, currentWorkspaceId) ??
    mapActiveThread(coachContext?.active_thread, undefined, incomingWorkspaceId, currentWorkspaceId) ??
    (workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId)
      ? undefined
      : memoryWithPressureStamp.activeThread);

  const patch: Partial<BootstrapData> = {
    conversation: snapshot
      ? mapConversation(
          snapshot.messages,
          workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId) ? [] : fallbackConversation,
          incomingWorkspaceId,
          currentWorkspaceId,
        )
      : workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId)
        ? []
        : fallbackConversation,
    memory: {
      ...memoryWithPressureStamp,
      activeThread,
      memoryEvidence,
    },
    workspaceTrainingState: snapshot
      ? mapWorkspaceTrainingState(snapshot.memory, current.workspaceTrainingState)
      : current.workspaceTrainingState,
    profile: mappedProfile,
    plan: snapshot
      ? mapPlan(snapshot.plan, current.plan, incomingWorkspaceId, currentWorkspaceId)
      : current.plan,
    globalPlan: snapshot
      ? mapGlobalPlan(
          firstPresentRecordValue(snapshot, ['global_plan', 'globalPlan']),
          current.globalPlan,
        )
      : current.globalPlan,
    projectPlanLink: snapshot
      ? mapGlobalPlanProjectLink(
          firstPresentRecordValue(snapshot, ['project_plan_link', 'projectPlanLink']),
          current.projectPlanLink,
        )
      : current.projectPlanLink,
    task: snapshot
      ? mapTask(
          resolveCurrentTaskPayload(snapshot, asRecord(snapshot.memory)),
          current.task,
          incomingWorkspaceId,
          currentWorkspaceId,
        )
      : current.task,
    resources: snapshot
      ? mapResources(
          asRecord(snapshot.memory)?.resources ?? snapshot.resources,
          leftoverLibraryFallbackIsNotLiveForBoundPlan(
            current.resources,
            asRecord(asRecord(snapshot.memory)?.workspace),
          )
            ? []
            : current.resources,
          incomingWorkspaceId,
          currentWorkspaceId,
        )
      : current.resources,
    evaluation: snapshot
      ? mapEvaluation(snapshot.evaluation, current.evaluation, incomingWorkspaceId, currentWorkspaceId)
      : current.evaluation,
    coachingState: snapshot
      ? mapCoachingState(
          snapshot.coaching_state,
          current.coachingState,
          incomingWorkspaceId,
          currentWorkspaceId,
        )
      : current.coachingState,
    learnerState: mapLearnerState(
      record?.learner_state ?? snapshot?.learner_state,
      current.learnerState,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    affectState: mapAffectState(
      record?.affect_state ?? snapshot?.affect_state,
      current.affectState,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    teachingDecision: mapTeachingDecision(
      record?.teaching_decision ?? snapshot?.teaching_decision,
      current.teachingDecision,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    toneDecision: mapToneDecision(
      record?.tone_decision ?? snapshot?.tone_decision,
      current.toneDecision,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    implementationGuide: mapImplementationGuide(
      record?.implementation_guide ??
        snapshot?.implementation_guide ??
        asRecord(record?.pedagogy)?.implementation_guide,
      current.implementationGuide,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    projectIdeas: mapProjectIdeas(
      record?.project_ideas ??
        snapshot?.project_ideas ??
        asRecord(record?.pedagogy)?.project_ideas,
      current.projectIdeas,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    projectAdaptationGuide: mapProjectAdaptationGuide(
      record?.project_adaptation_guide ??
        record?.adaptation_guide ??
        snapshot?.project_adaptation_guide ??
        snapshot?.adaptation_guide ??
        asRecord(record?.pedagogy)?.project_adaptation_guide ??
        asRecord(record?.pedagogy)?.adaptation_guide,
      current.projectAdaptationGuide,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    projectSources: mapProjectSources(
      record?.project_sources ??
        snapshot?.project_sources ??
        asRecord(record?.pedagogy)?.project_sources,
      current.projectSources,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    principleNotes: mapPrincipleNote(
      record?.principle_notes ??
        record?.principle_note ??
        snapshot?.principle_notes ??
        snapshot?.principle_note ??
        asRecord(record?.pedagogy)?.principle_notes ??
        asRecord(record?.pedagogy)?.principle_note,
      current.principleNotes,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    coachTurn: mapCoachTurn(
      record?.coach_turn,
      reply,
      current.coachTurn,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    coachFocus: mapCoachFocus(
      record?.coach_focus ?? snapshot?.coach_focus,
      reply,
      current.coachFocus,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    coachOrientation: mapCoachOrientation(
      record?.coach_orientation ??
        snapshot?.coach_orientation ??
        snapshot?.coachOrientation ??
        asRecord(snapshot?.memory)?.workspace,
      workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId) ? undefined : current.coachOrientation,
    ),
    planRuntimeStatus: mapPlanRuntimeStatus(
      record?.plan_runtime_status ?? snapshotPlanRuntimeStatus,
      snapshot,
      current.planRuntimeStatus,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    nextStepHint: mapNextStepHint(
      nextStepHintValue,
      current.nextStepHint,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    ...mapReviewQueueChrome(
      snapshot?.review_queue_summary ?? snapshot?.reviewQueueSummary,
      snapshot?.next_review_due ?? snapshot?.nextReviewDue,
      workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId) ? undefined : current.reviewQueueSummary,
      workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId) ? undefined : current.nextReviewDue,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    suggestedActions: mapSuggestedActions(
      firstPresentRecordValue(record, ['suggested_actions', 'suggestedActions']) ??
        firstPresentRecordValue(snapshot, ['suggested_actions', 'suggestedActions']),
      workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId) ? [] : current.suggestedActions,
    ),
  };

  return { sessionId, patch: applyLeftoverBoundPlanFiveViewOmit(current, applyLeftoverNotLiveTaskGuideFocus(patch)) };
}

export function mergePlanResult(
  current: BootstrapData,
  payload: unknown,
): Partial<BootstrapData> {
  const record = asRecord(payload);
  const snapshot = asRecord(record?.snapshot);
  const incomingWorkspaceId =
    asString(snapshot?.context_id) ??
    asString(snapshot?.contextId) ??
    asString(record?.context_id) ??
    asString(record?.contextId) ??
    asString(asRecord(asRecord(snapshot?.memory)?.workspace)?.workspace_id) ??
    asString(asRecord(asRecord(snapshot?.memory)?.workspace)?.workspaceId);
  const currentWorkspaceId =
    current.workspaceTrainingState?.workspaceId ?? current.memory.workspace?.workspaceId;
  const planPayload = record?.plan ?? snapshot?.plan ?? payload;
  const globalPlanValue = firstPresentRecordValue(record, ['global_plan', 'globalPlan']);
  const projectPlanLinkValue = firstPresentRecordValue(record, [
    'project_plan_link',
    'projectPlanLink',
  ]);
  return {
    plan: mapPlan(planPayload, current.plan),
    globalPlan: mapGlobalPlan(
      globalPlanValue === undefined
        ? firstPresentRecordValue(snapshot, ['global_plan', 'globalPlan'])
        : globalPlanValue,
      current.globalPlan,
    ),
    projectPlanLink: mapGlobalPlanProjectLink(
      projectPlanLinkValue === undefined
        ? firstPresentRecordValue(snapshot, ['project_plan_link', 'projectPlanLink'])
        : projectPlanLinkValue,
      current.projectPlanLink,
    ),
    planRuntimeStatus: mapPlanRuntimeStatus(
      record?.plan_runtime_status,
      undefined,
      current.planRuntimeStatus,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    coachOrientation: mapCoachOrientation(
      record?.coach_orientation ?? snapshot?.coach_orientation ?? snapshot?.coachOrientation,
      current.coachOrientation,
    ),
    coachTurn: mapCoachTurn(
      record?.coach_turn,
      undefined,
      current.coachTurn,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    nextStepHint: mapNextStepHint(
      record?.next_step_hint ?? asRecord(record?.plan_runtime_status)?.next_step_hint,
      current.nextStepHint,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    suggestedActions: mapSuggestedActions(
      firstPresentRecordValue(record, ['suggested_actions', 'suggestedActions']) ??
        firstPresentRecordValue(snapshot, ['suggested_actions', 'suggestedActions']),
      current.suggestedActions,
    ),
  };
}

export function mergeTaskResult(
  current: BootstrapData,
  payload: unknown,
): Partial<BootstrapData> {
  return {
    task: mapTask(payload, current.task),
  };
}

function planCandidateFromPayload(payload: unknown): unknown {
  const record = asRecord(payload);
  if (!record) {
    return undefined;
  }
  const snapshot = asRecord(record.snapshot);
  if (record.plan !== undefined) {
    return record.plan;
  }
  if (snapshot?.plan !== undefined) {
    return snapshot.plan;
  }
  if (
    asString(record.id) !== undefined ||
    asString(record.plan_id) !== undefined ||
    asString(record.planId) !== undefined ||
    asString(record.title) !== undefined ||
    Array.isArray(record.stages) ||
    Array.isArray(record.phases)
  ) {
    return payload;
  }
  return undefined;
}

function taskCandidateFromPayload(payload: unknown): unknown {
  const record = asRecord(payload);
  if (!record) {
    return undefined;
  }
  const snapshot = asRecord(record.snapshot);
  const nested =
    record.current_task ??
    record.currentTask ??
    record.task ??
    snapshot?.current_task ??
    snapshot?.currentTask ??
    snapshot?.task;
  if (nested !== undefined) {
    return nested;
  }
  if (
    asString(record.natural_language_goal) !== undefined ||
    asString(record.naturalLanguageGoal) !== undefined ||
    ((asString(record.id) !== undefined || asString(record.title) !== undefined) &&
      record.plan === undefined &&
      snapshot?.plan === undefined &&
      !Array.isArray(record.stages) &&
      !Array.isArray(record.phases))
  ) {
    return payload;
  }
  return undefined;
}

export function mergePlanResultSnapshot(
  current: BootstrapData,
  payload: unknown,
  incomingWorkspaceId?: string,
): Partial<BootstrapData> {
  const patch = mergePlanResult(current, payload);
  const planCandidate = planCandidateFromPayload(payload);
  const taskCandidate = taskCandidateFromPayload(payload);
  const stamped = mergeWorkspaceStampedSnapshot(
    current,
    {
      context_id: incomingWorkspaceId,
      plan: planCandidate,
      current_task: taskCandidate,
    },
    incomingWorkspaceId,
  );
  const record = asRecord(payload);
  const livePlan = stamped.plan ?? current.plan;
  const generatedId = livePlan.id;
  const boundNewLivePlan = Boolean(generatedId) && generatedId !== current.plan.id;
  const next: Partial<BootstrapData> = {
    ...patch,
    plan: livePlan,
    ...(taskCandidate !== undefined ? { task: stamped.task } : {}),
  };
  if (record?.memory !== undefined || record?.coach_orientation !== undefined || record?.coachOrientation !== undefined) {
    const summaryPatch = mergeMemorySummary(current, {
      context_id: incomingWorkspaceId,
      plan: planCandidate,
      current_task: taskCandidate,
      plan_runtime_status: record.plan_runtime_status ?? record.planRuntimeStatus,
      coach_orientation: record.coach_orientation ?? record.coachOrientation,
      suggested_actions: record.suggested_actions ?? record.suggestedActions,
      memory: record.memory,
    });
    return applyLeftoverBoundPlanFiveViewOmit(current, {
      ...summaryPatch,
      ...next,
      plan: livePlan,
      ...(taskCandidate !== undefined ? { task: stamped.task } : {}),
    });
  }
  if (!boundNewLivePlan) {
    return next;
  }
  const liveStep = next.planRuntimeStatus?.currentStep ?? livePlan.currentStep;
  return applyLeftoverBoundPlanFiveViewOmit(
    current,
    applyLeftoverNotLiveTaskGuideFocus({
      ...current,
      ...next,
      plan: livePlan,
      planRuntimeStatus: {
        ...current.planRuntimeStatus,
        ...next.planRuntimeStatus,
        recovered: true,
        currentStep: liveStep,
        reviewPoints:
          next.planRuntimeStatus?.reviewPoints ?? current.planRuntimeStatus?.reviewPoints ?? [],
      },
      memory: {
        ...current.memory,
        workspace: {
          ...current.memory.workspace,
          latestPlanRuntime: {
            revision: 1,
            frozen: false,
            verifyMethod: [],
            ...current.memory.workspace?.latestPlanRuntime,
            planId: generatedId,
            currentStep: liveStep,
            workspaceId: incomingWorkspaceId ?? current.memory.workspace?.workspaceId,
            resumeState: 'in_progress',
          },
        },
      },
    }),
  );
}

export function mergeTaskResultSnapshot(
  current: BootstrapData,
  payload: unknown,
  incomingWorkspaceId?: string,
): Partial<BootstrapData> {
  const stamped = mergeWorkspaceStampedSnapshot(
    current,
    {
      context_id: incomingWorkspaceId,
      current_task: taskCandidateFromPayload(payload),
    },
    incomingWorkspaceId,
  );
  return {
    task: stamped.task,
  };
}

export function mergeEvaluationResult(
  current: BootstrapData,
  payload: unknown,
): Partial<BootstrapData> {
  return {
    evaluation: mapEvaluation(payload, current.evaluation),
  };
}

export function mergeEvaluationResultSnapshot(
  current: BootstrapData,
  payload: unknown,
  incomingWorkspaceId?: string,
): Partial<BootstrapData> {
  const record = asRecord(payload) ?? {};
  const stamp = asString(record.workspace_id) ?? asString(record.workspaceId);
  const incomingId = incomingWorkspaceId?.trim() || undefined;
  const scopedPayload = incomingId && stamp === incomingId ? payload : undefined;
  const currentWorkspaceId =
    current.workspaceTrainingState?.workspaceId ?? current.memory.workspace?.workspaceId;
  return {
    evaluation: mapEvaluation(
      scopedPayload,
      current.evaluation,
      incomingId,
      currentWorkspaceId,
    ),
  };
}

export function mergeMemorySummary(
  current: BootstrapData,
  payload: unknown,
): Partial<BootstrapData> {
  const snapshot = asRecord(payload);
  const memoryRecord = asRecord(snapshot?.memory);
  const incomingWorkspaceId =
    asString(snapshot?.context_id) ??
    asString(snapshot?.contextId) ??
    asString(asRecord(memoryRecord?.workspace)?.workspace_id) ??
    asString(asRecord(memoryRecord?.workspace)?.workspaceId);
  const currentWorkspaceId =
    current.workspaceTrainingState?.workspaceId ?? current.memory.workspace?.workspaceId;
  const mappedMemory = mapMemory(memoryRecord, current.memory, incomingWorkspaceId, currentWorkspaceId);
  const scopedWorkspaceFacts = applyRecoveryScopeToWorkspace(
    mappedMemory.workspace,
    recoveryScopeFromProvider(incomingWorkspaceId, current.providerConfig),
  );
  mappedMemory.workspace = scopedWorkspaceFacts;
  const planRuntimeStatus = asRecord(
    snapshot?.plan_runtime_status ??
      snapshot?.planRuntimeStatus ??
      asRecord(payload)?.plan_runtime_status ??
      asRecord(payload)?.planRuntimeStatus,
  );
  const mappedProfile = applyWorkspaceProfileHints(
    mapProfile(snapshot?.profile, current.profile),
    mappedMemory.workspace,
  );
  const planExplicitlyNull =
    Boolean(snapshot) &&
    Object.prototype.hasOwnProperty.call(snapshot, 'plan') &&
    snapshot!.plan == null;
  const hadStoredLeftoverPlan = Boolean(
    current.plan.id?.trim() ||
      current.plan.title?.trim() ||
      current.plan.currentStep?.trim() ||
      (current.plan.stages?.length ?? 0) > 0,
  );
  const mappedPlan = mapPlan(snapshot?.plan, current.plan, incomingWorkspaceId, currentWorkspaceId);
  let mappedPlanRuntimeStatus = mapPlanRuntimeStatus(
    planRuntimeStatus,
    snapshot,
    current.planRuntimeStatus,
    incomingWorkspaceId,
    currentWorkspaceId,
  );
  // Same-workspace start with plan:null clears live plan; if host still held stored leftover
  // and recovery did not already mark recovered, surface leftover-not-live for five-view overlay.
  if (
    planExplicitlyNull &&
    hadStoredLeftoverPlan &&
    !workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId) &&
    mappedPlanRuntimeStatus?.recovered !== true
  ) {
    mappedPlanRuntimeStatus = {
      reviewPoints: [],
      ...(mappedPlanRuntimeStatus ?? {}),
      recovered: true,
    };
  }
  const mapped = {
    conversation: mapConversation(
      snapshot?.messages,
      current.conversation,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    profile: mappedProfile,
    plan: mappedPlan,
    globalPlan: mapGlobalPlan(
      firstPresentRecordValue(snapshot, ['global_plan', 'globalPlan']),
      current.globalPlan,
    ),
    projectPlanLink: mapGlobalPlanProjectLink(
      firstPresentRecordValue(snapshot, ['project_plan_link', 'projectPlanLink']),
      current.projectPlanLink,
    ),
    task: mapTask(
      resolveCurrentTaskPayload(snapshot, memoryRecord),
      current.task,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    evaluation: mapEvaluation(
      snapshot?.evaluation,
      current.evaluation,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    memory: {
      ...mappedMemory,
      activeThread:
        mapActiveThread(
          memoryRecord?.active_thread,
          workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId)
            ? undefined
            : mappedMemory.activeThread,
          incomingWorkspaceId,
          currentWorkspaceId,
        ) ??
        (workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId)
          ? undefined
          : mappedMemory.activeThread),
      memoryEvidence:
        asStringArray(memoryRecord?.memory_evidence) ?? mappedMemory.memoryEvidence,
    },
    workspaceTrainingState: mapWorkspaceTrainingState(memoryRecord, current.workspaceTrainingState),
    coachingState: mapCoachingState(
      snapshot?.coaching_state,
      current.coachingState,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    learnerState: mapLearnerState(
      snapshot?.learner_state ?? asRecord(payload)?.learner_state,
      current.learnerState,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    affectState: mapAffectState(
      snapshot?.affect_state ?? asRecord(payload)?.affect_state,
      current.affectState,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    teachingDecision: mapTeachingDecision(
      snapshot?.teaching_decision ?? asRecord(payload)?.teaching_decision,
      current.teachingDecision,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    toneDecision: mapToneDecision(
      snapshot?.tone_decision ?? asRecord(payload)?.tone_decision,
      current.toneDecision,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    implementationGuide: mapImplementationGuide(
      snapshot?.implementation_guide ?? asRecord(payload)?.implementation_guide,
      current.implementationGuide,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    projectIdeas: mapProjectIdeas(
      snapshot?.project_ideas ?? asRecord(payload)?.project_ideas,
      current.projectIdeas,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    projectAdaptationGuide: mapProjectAdaptationGuide(
      snapshot?.project_adaptation_guide ??
        snapshot?.adaptation_guide ??
        asRecord(payload)?.project_adaptation_guide ??
        asRecord(payload)?.adaptation_guide,
      current.projectAdaptationGuide,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    projectSources: mapProjectSources(
      snapshot?.project_sources ?? asRecord(payload)?.project_sources,
      current.projectSources,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    principleNotes: mapPrincipleNote(
      snapshot?.principle_notes ??
        snapshot?.principle_note ??
        asRecord(payload)?.principle_notes ??
        asRecord(payload)?.principle_note,
      current.principleNotes,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    coachTurn: mapCoachTurn(
      asRecord(payload)?.coach_turn,
      undefined,
      current.coachTurn,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    coachFocus: mapCoachFocus(
      snapshot?.coach_focus ?? asRecord(payload)?.coach_focus,
      undefined,
      current.coachFocus,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    coachOrientation: mapCoachOrientation(
      snapshot?.coach_orientation ?? snapshot?.coachOrientation ?? asRecord(snapshot?.memory)?.workspace,
      workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId) ? undefined : current.coachOrientation,
    ),
    planRuntimeStatus: mappedPlanRuntimeStatus,
    nextStepHint: mapNextStepHint(
      asRecord(payload)?.next_step_hint ?? planRuntimeStatus?.next_step_hint,
      current.nextStepHint,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    ...mapReviewQueueChrome(
      snapshot?.review_queue_summary ?? snapshot?.reviewQueueSummary,
      snapshot?.next_review_due ?? snapshot?.nextReviewDue,
      workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId) ? undefined : current.reviewQueueSummary,
      workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId) ? undefined : current.nextReviewDue,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    resources: mapResources(
      snapshot?.memory ? asRecord(snapshot.memory)?.resources : snapshot?.resources,
      leftoverLibraryFallbackIsNotLiveForBoundPlan(current.resources, asRecord(memoryRecord?.workspace))
        ? []
        : current.resources,
      incomingWorkspaceId,
      currentWorkspaceId,
    ),
    suggestedActions: mapSuggestedActions(
      firstPresentRecordValue(snapshot, ['suggested_actions', 'suggestedActions']) ??
        firstPresentRecordValue(asRecord(payload), ['suggested_actions', 'suggestedActions']),
      workspaceIdsChanged(incomingWorkspaceId, currentWorkspaceId) ? [] : current.suggestedActions,
    ),
    providerConfig: {
      ...current.providerConfig,
      lastTestResult: lastTestForRecoveryScope(
        current.providerConfig.lastTestResult,
        mappedMemory.workspace,
        recoveryScopeFromProvider(incomingWorkspaceId, current.providerConfig),
        currentWorkspaceId,
      ),
    },
    streamingState: mapRecoveredStreamingState(
      mappedMemory.workspace,
      current.streamingState,
      recoveryScopeFromProvider(incomingWorkspaceId, current.providerConfig),
      currentWorkspaceId,
    ),
  };
  return applyLeftoverBoundPlanFiveViewOmit(current, applyLeftoverNotLiveTaskGuideFocus(mapped));
}

const EMPTY_WORKSPACE_TRANSFER_ID = '__trainer_empty_workspace__';

export function failClosedWorkbenchAfterWorkspaceTransfer(
  current: BootstrapData,
  incomingWorkspaceId?: string,
): Partial<BootstrapData> {
  const previousWorkspaceId =
    current.workspaceTrainingState?.workspaceId ?? current.memory.workspace?.workspaceId;
  const incomingId = incomingWorkspaceId?.trim() || undefined;
  const previousId = previousWorkspaceId?.trim() || undefined;
  const sameWorkspace = Boolean(incomingId) && Boolean(previousId) && incomingId === previousId;
  const unscopedCurrent = Boolean(incomingId) && !previousId;
  if (sameWorkspace || unscopedCurrent) {
    const scopedCurrent = unscopedCurrent
      ? {
          ...current,
          memory: {
            ...current.memory,
            workspace: {
              ...current.memory.workspace,
              workspaceId: incomingId,
            },
          },
        }
      : current;
    return mergeMemorySummary(scopedCurrent, {
      context_id: incomingId,
      plan_runtime_status: {
        revision: 1,
      },
      memory: {
        workspace: {
          workspace_id: incomingId,
        },
      },
    });
  }

  const stampedCurrent: BootstrapData = {
    ...current,
    memory: {
      ...current.memory,
      workspace: {
        ...current.memory.workspace,
        workspaceId: previousId || `${EMPTY_WORKSPACE_TRANSFER_ID}-previous`,
      },
    },
    workspaceTrainingState: {
      ...(current.workspaceTrainingState ?? {}),
      workspaceId: previousId || `${EMPTY_WORKSPACE_TRANSFER_ID}-previous`,
    },
  };
  const scopedIncomingId = incomingId ?? EMPTY_WORKSPACE_TRANSFER_ID;
  const patch = mergeMemorySummary(stampedCurrent, {
    context_id: scopedIncomingId,
    plan_runtime_status: {
      revision: 1,
    },
    memory: {
      workspace: {
        workspace_id: scopedIncomingId,
      },
    },
  });
  if (incomingId) {
    return patch;
  }
  const mappedMemory = patch.memory ?? current.memory;
  return {
    ...patch,
    memory: {
      ...mappedMemory,
      workspace: {
        ...mappedMemory.workspace,
        workspaceId: undefined,
      },
    },
    workspaceTrainingState: patch.workspaceTrainingState
      ? {
          ...patch.workspaceTrainingState,
          workspaceId: undefined,
        }
        : {
          workspaceId: undefined,
        },
  };
}

function mergeWorkspaceStampedSnapshot(
  current: BootstrapData,
  payload: unknown,
  incomingWorkspaceId?: string,
): Partial<BootstrapData> {
  const record = asRecord(payload) ?? {};
  const incomingId =
    incomingWorkspaceId?.trim() ||
    asString(record.context_id) ||
    asString(record.contextId) ||
    undefined;
  // Explicit null from /session/start (leftover stored, not live) must clear — not fall back.
  const planExplicitlyNull =
    Object.prototype.hasOwnProperty.call(record, 'plan') && record.plan == null;
  const taskKey = Object.prototype.hasOwnProperty.call(record, 'current_task')
    ? 'current_task'
    : Object.prototype.hasOwnProperty.call(record, 'currentTask')
      ? 'currentTask'
      : Object.prototype.hasOwnProperty.call(record, 'task')
        ? 'task'
        : undefined;
  const taskExplicitlyNull = Boolean(taskKey && record[taskKey] == null);
  const plan = asRecord(record.plan);
  const task = asRecord(record.current_task ?? record.currentTask ?? record.task);
  const planStamp = asString(plan?.workspace_id) ?? asString(plan?.workspaceId);
  const taskStamp = asString(task?.workspace_id) ?? asString(task?.workspaceId);
  const scopedPlan = incomingId && plan && planStamp === incomingId ? record.plan : undefined;
  const scopedTask =
    incomingId && task && taskStamp === incomingId
      ? (record.current_task ?? record.currentTask ?? record.task)
      : undefined;
  const memoryRecord = asRecord(record.memory);
  // Never inject plan/current_task:undefined — hasOwn+==null is treated as explicit
  // leftover clear and strips live training chrome on /memory/summary refresh.
  const stamped: UnknownRecord = {
    ...record,
    context_id: incomingId,
    ...(memoryRecord
      ? {
          memory: {
            ...memoryRecord,
            workspace: {
              ...(asRecord(memoryRecord.workspace) ?? {}),
              workspace_id: incomingId,
            },
          },
        }
      : {}),
  };
  if (planExplicitlyNull) {
    stamped.plan = null;
  } else if (scopedPlan !== undefined) {
    stamped.plan = scopedPlan;
  } else {
    delete stamped.plan;
  }
  if (taskExplicitlyNull) {
    stamped.current_task = null;
    delete stamped.currentTask;
    delete stamped.task;
  } else if (scopedTask !== undefined) {
    stamped.current_task = scopedTask;
    delete stamped.currentTask;
    delete stamped.task;
  } else {
    delete stamped.current_task;
    delete stamped.currentTask;
    delete stamped.task;
  }
  return mergeMemorySummary(current, stamped);
}

export function mergeSessionStartSnapshot(
  current: BootstrapData,
  payload: unknown,
  incomingWorkspaceId?: string,
): Partial<BootstrapData> {
  return mergeWorkspaceStampedSnapshot(current, payload, incomingWorkspaceId);
}

export function mergeMemorySummarySnapshot(
  current: BootstrapData,
  payload: unknown,
  incomingWorkspaceId?: string,
): Partial<BootstrapData> {
  return mergeWorkspaceStampedSnapshot(current, payload, incomingWorkspaceId);
}

export function mergeSessionMessageSnapshot(
  current: BootstrapData,
  payload: unknown,
  userMessage: string,
  incomingWorkspaceId?: string,
): { sessionId?: string; patch: Partial<BootstrapData> } {
  const { sessionId, patch } = mergeSessionMessage(current, payload, userMessage);
  const record = asRecord(payload) ?? {};
  const snapshot = asRecord(record.snapshot) ?? record;
  const stamped = mergeWorkspaceStampedSnapshot(current, snapshot, incomingWorkspaceId);
  return {
    sessionId,
    patch: {
      ...patch,
      plan: stamped.plan,
      task: stamped.task,
    },
  };
}

export function mergeResourceRecords(
  current: BootstrapData,
  payload: unknown,
): Partial<BootstrapData> {
  const list = Array.isArray(payload) ? payload : [payload];
  return {
    resources: list
      .map((item) => mapResource(item))
      .filter((item): item is ResourceRecordView => item !== undefined)
      .reduce<ResourceRecordView[]>((accumulator, resource) => {
        const existingIndex = accumulator.findIndex((item) => item.id === resource.id);
        if (existingIndex >= 0) {
          accumulator[existingIndex] = mergeDefinedResourceFields(accumulator[existingIndex], resource);
        } else {
          accumulator.push(resource);
        }
        return accumulator;
      }, [...current.resources]),
  };
}

export function mergeProfileWeaknessReviews(
  current: BootstrapData,
  payload: unknown,
): Partial<BootstrapData> {
  const record = asRecord(payload);
  const mappedMemory = record?.memory ? mapMemory(record.memory, current.memory) : current.memory;
  return {
    profile: applyWorkspaceProfileHints(
      mapProfile(record?.profile, current.profile),
      mappedMemory.workspace,
    ),
    memory: {
      ...current.memory,
      weakSpots: asStringArray(record?.weaknesses) ?? current.memory.weakSpots,
      reviewSummary: asStringArray(record?.reviews)?.join(' ') || current.memory.reviewSummary,
    },
  };
}

export function patchHostState(
  state: TrainerHostState,
  patch: Partial<BootstrapData>,
): TrainerHostState {
  const streamingState =
    patch.streamingState ?? state.streamingState ?? state.bootstrap.streamingState;
  return {
    ...state,
    streamingState,
    bootstrap: {
      ...state.bootstrap,
      ...patch,
      streamingState,
    },
  };
}

export function toBootstrapPayload(state: TrainerHostState): BootstrapData {
  return {
    ...state.bootstrap,
    streamingState:
      state.streamingState ?? state.bootstrap.streamingState ?? createEmptyTrainerStreamingState(),
  };
}

export function toHostBootstrapMessage(state: TrainerHostState): HostMessage {
  return {
    type: 'bootstrap',
    payload: toBootstrapPayload(state),
  };
}

export function toHostPatchMessage(state: TrainerHostState): HostMessage {
  return {
    type: 'state/patch',
    payload: toBootstrapPayload(state),
  };
}

export function toOperationStatus(
  ok: boolean,
  message: string,
): HostMessage {
  return {
    type: 'operation/status',
    payload: {
      tone: ok ? 'success' : 'error',
      message,
    },
  };
}

// A configured provider should never read as "unconfigured" just because its
// name field is empty — fall back to the model name so the connected service
// is identified meaningfully.
const UNCONFIGURED_PROVIDER_NAME = '未配置模型服务';
function providerDisplayName(provider: ProviderConfig | undefined): string {
  if (!provider) return UNCONFIGURED_PROVIDER_NAME;
  const name = provider.name?.trim();
  if (name && name !== UNCONFIGURED_PROVIDER_NAME) return name;
  const model = provider.model?.trim();
  if (model) return model;
  return UNCONFIGURED_PROVIDER_NAME;
}

function toProviderSummary(provider: ProviderConfig | undefined): ProviderSummary {
  const protocol = normalizeProviderProtocol(provider?.protocol);
  const capabilities: CapabilityFlags =
    provider?.capabilities ?? defaultCapabilitiesForProtocol(protocol);

  return {
    name: providerDisplayName(provider),
    model: provider?.model ?? '未选择模型',
    capabilities,
    protocol,
    protocolFamily: provider ? providerProtocolFamily(protocol) : undefined,
  };
}

export function mapResourceTrash(
  payload: unknown,
  expectedWorkspaceId: string,
): NonNullable<BootstrapData['deletedResources']> {
  const record = asRecord(payload);
  if (!record || Array.isArray(payload)) {
    throw new Error('Resource Trash response must be an object.');
  }
  const workspaceId = asString(record.workspace_id) ?? asString(record.workspaceId);
  if (!workspaceId || workspaceId !== expectedWorkspaceId) {
    throw new Error('Resource Trash response workspace did not match the active workspace.');
  }
  const items = Array.isArray(record.items) ? record.items : undefined;
  if (!items) {
    throw new Error('Resource Trash response did not include items.');
  }

  const seenResourceIds = new Set<string>();
  const deletedResources: NonNullable<BootstrapData['deletedResources']> = [];
  for (const item of items) {
    const deletedResource = mapDeletedResource(item);
    if (!deletedResource) {
      throw new Error('Resource Trash response included an invalid item.');
    }
    if (seenResourceIds.has(deletedResource.resourceId)) {
      throw new Error('Resource Trash response included duplicate resource IDs.');
    }
    seenResourceIds.add(deletedResource.resourceId);
    deletedResources.push(deletedResource);
  }
  return deletedResources;
}

function toProviderConfigView(
  provider: ProviderConfig | undefined,
  apiKeyConfigured: boolean,
): ProviderConfigView {
  const capabilities: CapabilityFlags =
    provider?.capabilities ?? defaultCapabilitiesForProtocol(normalizeProviderProtocol(provider?.protocol));
  const protocol = normalizeProviderProtocol(provider?.protocol);

  return {
    configured: providerTransportIsConfigured(provider),
    name: providerDisplayName(provider),
    baseUrl: provider?.baseUrl ?? '',
    model: provider?.model ?? '',
    contextWindowTokens: provider?.contextWindowTokens,
    maxOutputTokens: provider?.maxOutputTokens,
    apiKeyConfigured,
    capabilities,
    protocol,
    protocolFamily: provider ? providerProtocolFamily(protocol) : undefined,
    connectionType: provider?.connectionType,
    requestDefaults: provider?.requestDefaults ?? {},
    profileId: provider?.profileId,
    profileLabel: provider?.profileLabel,
    profileMode: provider?.profileMode,
    credentialMode: provider?.credentialMode,
    availableModels: provider?.availableModels ?? [],
    catalogModels: provider?.catalogModels ?? [],
    allowedModels: provider?.allowedModels ?? [],
    deniedModels: provider?.deniedModels ?? [],
    modelAliases: provider?.modelAliases ?? {},
    resolvedModel: provider?.model,
    modelCapabilities: provider?.modelCapabilities ?? {},
    modelTokenLimits: provider?.modelTokenLimits,
    taskBindings: provider?.taskBindings ?? {},
    embeddingModel: provider?.embeddingModel,
    catalogSource: provider?.catalogSource,
    cacheTtlSeconds: provider?.cacheTtlSeconds,
    modelListStatus: apiKeyConfigured ? 'idle' : 'idle',
    modelListDetail: undefined,
    cacheFetchedAt: undefined,
    cacheExpiresAt: undefined,
    cacheSource: undefined,
    modelErrorCategory: undefined,
    modelStatusCode: undefined,
    modelRetryable: undefined,
    workspaceSecretConfigured:
      provider?.credentialMode === 'workspace_secret' ? apiKeyConfigured : undefined,
    lastTestResult: undefined,
  };
}

function isCompatibleLastTestResult(
  provider: ProviderConfigView,
  result: ProviderConfigView['lastTestResult'],
): boolean {
  if (!result) {
    return false;
  }
  const resultProtocol = result.protocol ? normalizeProviderProtocol(result.protocol) : undefined;
  if (provider.profileId?.trim()) {
    if (!result.profileId?.trim() || result.profileId.trim() !== provider.profileId.trim()) {
      return false;
    }
  } else if (result.profileId?.trim()) {
    return false;
  }
  return (
    result.providerName.trim().toLowerCase() === provider.name.trim().toLowerCase() &&
    result.baseUrl.trim().toLowerCase() === provider.baseUrl.trim().toLowerCase() &&
    result.model.trim().toLowerCase() === provider.model.trim().toLowerCase() &&
    (!resultProtocol || resultProtocol === normalizeProviderProtocol(provider.protocol))
  );
}

function recoveryScopeFromProvider(
  workspaceId: string | undefined,
  provider: Pick<ProviderConfigView, 'profileId' | 'name' | 'baseUrl' | 'model'>,
): RecoveryScope | undefined {
  const scopedWorkspaceId = workspaceId?.trim();
  if (!scopedWorkspaceId) {
    return undefined;
  }
  return {
    workspaceId: scopedWorkspaceId,
    providerProfileId: provider.profileId?.trim() || undefined,
    providerName: provider.name,
    baseUrl: provider.baseUrl,
    model: provider.model,
  };
}

function toLiveContext(workspace: WorkspaceSnapshot): LiveContextView {
  const diagnosticsSummary =
    workspace.diagnosticErrors || workspace.diagnosticWarnings
      ? `${workspace.diagnosticErrors ?? 0} 个错误，${workspace.diagnosticWarnings ?? 0} 个警告`
      : '当前没有诊断问题';

  return {
    activeFile: workspace.activeFile,
    activeLanguageId: workspace.activeLanguageId,
    selectionRange: workspace.selectionRange,
    selectionPreview: truncateText(workspace.selectionText),
    diagnosticsSummary,
    documentVersion: workspace.documentVersion,
    recentFiles: workspace.recentFiles ?? [],
    recentEditedFiles: workspace.recentEditedFiles ?? [],
    relatedFiles: workspace.relatedFiles ?? [],
    diagnosticErrors: workspace.diagnosticErrors,
    diagnosticWarnings: workspace.diagnosticWarnings,
  };
}

function toConnectionState(sidecar: SidecarStatus): BootstrapData['connection']['state'] {
  if (sidecar.lifecycle === 'ready') {
    return 'connected';
  }
  if (sidecar.lifecycle === 'starting') {
    return 'starting';
  }
  return 'offline';
}

function workspaceName(workspace: WorkspaceSnapshot): string {
  if (!workspace.workspaceFolder) {
    return 'Trainer 工作区';
  }
  const normalized = workspace.workspaceFolder.replace(/\\/g, '/');
  return path.posix.basename(normalized) || workspace.workspaceFolder;
}

function mapProfile(value: unknown, fallback: UserProfileView): UserProfileView {
  const record = asRecord(value);
  const workspaceRecord = asRecord(record?.workspace);
  if (!record) {
    return fallback;
  }
  const goals =
    asStringArray(record.long_term_goals) ??
    (asString(record.long_term_goal) ? [asString(record.long_term_goal)!] : fallback.goals);
  const preferredStyle = asString(record.teaching_style) ?? fallback.preferredStyle;
  const answerPolicy = toAnswerPolicy(asString(record.answer_policy));
  const learnerName =
    asString(workspaceRecord?.learner_name) ??
    asString(workspaceRecord?.learnerName) ??
    fallback.learnerName;
  const projectContext =
    asString(workspaceRecord?.project_context) ??
    asString(workspaceRecord?.projectContext) ??
    fallback.projectContext;
  return {
    learnerName,
    goals,
    weeklyHours: asNumber(record.weekly_hours) ?? fallback.weeklyHours,
    preferredStyle,
    answerPolicy,
    focusAreas: asStringArray(record.preferred_libraries) ?? fallback.focusAreas,
    targetProject: asString(record.target_project) ?? projectContext ?? fallback.targetProject,
    preferredRhythm:
      asString(workspaceRecord?.preferred_rhythm) ??
      asString(workspaceRecord?.preferredRhythm) ??
      fallback.preferredRhythm,
    preferredLearningMode:
      asString(workspaceRecord?.preferred_learning_mode) ??
      asString(workspaceRecord?.preferredLearningMode) ??
      fallback.preferredLearningMode,
    onboardingRequest:
      asString(workspaceRecord?.onboarding_request) ??
      asString(workspaceRecord?.onboardingRequest) ??
      fallback.onboardingRequest,
    projectContext,
  };
}

function applyWorkspaceProfileHints(
  profile: UserProfileView,
  workspace: BootstrapData['memory']['workspace'],
): UserProfileView {
  if (!workspace) {
    return profile;
  }
  const scopedWorkspace = Boolean(workspace.workspaceId);
  return {
    ...profile,
    learnerName: scopedWorkspace
      ? workspace.learnerName ?? ''
      : workspace.learnerName ?? profile.learnerName,
    targetProject: scopedWorkspace
      ? workspace.projectContext
      : profile.targetProject ?? workspace.projectContext ?? profile.targetProject,
    preferredRhythm: scopedWorkspace
      ? workspace.preferredRhythm
      : workspace.preferredRhythm ?? profile.preferredRhythm,
    preferredLearningMode: scopedWorkspace
      ? workspace.preferredLearningMode
      : workspace.preferredLearningMode ?? profile.preferredLearningMode,
    onboardingRequest: scopedWorkspace
      ? workspace.onboardingRequest
      : workspace.onboardingRequest ?? profile.onboardingRequest,
    projectContext: scopedWorkspace
      ? workspace.projectContext
      : workspace.projectContext ?? profile.projectContext,
  };
}

function mapPlan(
  value: unknown,
  fallback: LearningPlanView,
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): LearningPlanView {
  // Fail-closed: explicit null means no live plan (leftover may stay stored server-side).
  if (value === null) {
    return emptyLivePlan();
  }
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const record = asRecord(value);
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? emptyLivePlan() : fallback;
  }
  const useFallback = !workspaceChanged;
  const stages = Array.isArray(record.stages)
    ? record.stages
    : Array.isArray(record.phases)
      ? record.phases
      : [];
  return {
    id: asString(record.id) ?? asString(record.plan_id) ?? (useFallback ? fallback.id : ''),
    title: asString(record.title) ?? (useFallback ? fallback.title : ''),
    frozen: asBoolean(record.frozen) ?? (useFallback ? fallback.frozen : false),
    cadence: asString(record.cadence) ?? asString(record.weekly_cadence) ?? (useFallback ? fallback.cadence : ''),
    summary: asString(record.summary) ?? asString(record.objective) ?? (useFallback ? fallback.summary : ''),
    currentStageId: asString(record.current_stage_id) ?? (useFallback ? fallback.currentStageId : undefined),
    currentStep: asString(record.current_step) ?? (useFallback ? fallback.currentStep : undefined),
    whyNow: asString(record.why_now) ?? (useFallback ? fallback.whyNow : undefined),
    verifyMethod: asStringArray(record.verify_method) ?? (useFallback ? fallback.verifyMethod : undefined),
    blockedReason: asString(record.blocked_reason) ?? (useFallback ? fallback.blockedReason : undefined),
    nextAfterCurrent: asString(record.next_after_current) ?? (useFallback ? fallback.nextAfterCurrent : undefined),
    stages: stages.map((stage, index) => mapPlanStage(stage, index)),
  };
}

function asCapabilityVerificationState(
  value: string | undefined,
): ProviderCapabilityVerificationState | undefined {
  return value === 'verified' || value === 'unsupported' || value === 'unverified' || value === 'disabled'
    ? value
    : undefined;
}

function mapRecoveredProviderLastTest(
  workspace: BootstrapData['memory']['workspace'],
  scope?: RecoveryScope,
): BootstrapData['providerConfig']['lastTestResult'] {
  const record = scope
    ? selectProviderCapabilityForScope(workspace?.latestProviderCapability, scope)
    : normalizeProviderCapabilityRecovery(workspace?.latestProviderCapability);
  if (!record) {
    return undefined;
  }
  return {
    ok: record.ok,
    status: record.ok ? 'connected' : 'failed',
    detail: '',
    checkedAt: record.checkedAt,
    workspaceId: record.workspaceId,
    profileId: record.providerProfileId,
    providerName: record.providerName,
    baseUrl: record.baseUrl,
    model: record.model,
    protocol: record.protocol ? normalizeProviderProtocol(record.protocol) : undefined,
    capabilityEvidence: record.capabilityEvidence.flatMap((entry) => {
      const state = asCapabilityVerificationState(entry.state);
      return state
        ? [{ name: entry.name, declared: entry.declared, observed: entry.observed, state }]
        : [];
    }),
    toolsReady: record.toolsReady,
    toolProbeStatus: asCapabilityVerificationState(record.toolProbeStatus),
    streamingReady: record.streamingReady,
    streamProbeStatus: asCapabilityVerificationState(record.streamProbeStatus),
    visionReady: record.visionReady,
    visionProbeStatus: asCapabilityVerificationState(record.visionProbeStatus),
    thinkingReady: record.thinkingReady,
    thinkingProbeStatus: asCapabilityVerificationState(record.thinkingProbeStatus),
  };
}

function mapRecoveredStreamingState(
  workspace: BootstrapData['memory']['workspace'],
  fallback: BootstrapData['streamingState'],
  scope?: RecoveryScope,
  previousWorkspaceId?: string,
): BootstrapData['streamingState'] {
  const incomingCheckpoint = recoverStreamingCheckpointAfterRestart(workspace?.latestStreamingCheckpoint);
  const recovered = scope
    ? selectStreamingCheckpointForScope(incomingCheckpoint, scope)
    : incomingCheckpoint;
  const leftoverInScope = leftoverStreamingIsCurrent(
    fallback,
    scope,
    previousWorkspaceId,
    Boolean(incomingCheckpoint) && !recovered,
  );
  if (fallback?.isStreaming && leftoverInScope) {
    return fallback;
  }
  if (!recovered || (recovered.phase !== 'interrupted' && recovered.phase !== 'cancelled')) {
    return leftoverInScope ? fallback : createEmptyTrainerStreamingState();
  }
  return {
    ...createEmptyTrainerStreamingState(),
    ...(leftoverInScope ? fallback : {}),
    isStreaming: false,
    streamError: sanitizeErrorSurfaceText(recovered.error || recovered.stopReason || recovered.phase),
    completionStopReason: recovered.phase,
    streamMessageId: recovered.streamMessageId,
  };
}

function leftoverStreamingIsCurrent(
  fallback: BootstrapData['streamingState'] | undefined,
  scope: RecoveryScope | undefined,
  previousWorkspaceId: string | undefined,
  incomingBelongsToAnotherProvider: boolean,
): boolean {
  if (!fallback) {
    return false;
  }
  if (scope?.workspaceId && previousWorkspaceId && previousWorkspaceId !== scope.workspaceId) {
    return false;
  }
  if (incomingBelongsToAnotherProvider) {
    return false;
  }
  return true;
}

function lastTestForRecoveryScope(
  leftover: BootstrapData['providerConfig']['lastTestResult'],
  workspace: BootstrapData['memory']['workspace'],
  scope: RecoveryScope | undefined,
  previousWorkspaceId?: string,
): BootstrapData['providerConfig']['lastTestResult'] {
  const recovered = mapRecoveredProviderLastTest(workspace, scope);
  let scopedLeftover = leftover;
  if (!leftover) {
    scopedLeftover = undefined;
  } else if (scope?.workspaceId && previousWorkspaceId && previousWorkspaceId !== scope.workspaceId) {
    scopedLeftover = undefined;
  } else if (!scope?.workspaceId) {
    scopedLeftover = leftover.workspaceId ? undefined : leftover;
  } else if (!leftover.workspaceId || leftover.workspaceId !== scope.workspaceId) {
    scopedLeftover = undefined;
  } else if (scope.providerProfileId) {
    if (!leftover.profileId || leftover.profileId !== scope.providerProfileId) {
      scopedLeftover = undefined;
    }
  } else if (leftover.profileId) {
    scopedLeftover = undefined;
  }
  return preferAuthoritativeProviderLastTest(scopedLeftover, recovered);
}

function reviewQueueTextForScope(
  value: unknown,
  incomingWorkspaceId: string | undefined,
  workspaceChanged: boolean,
): string | undefined {
  const record = asRecord(value);
  if (record) {
    const stamp = asString(record.workspace_id) ?? asString(record.workspaceId);
    if (incomingWorkspaceId) {
      if (workspaceChanged) {
        if (!isCurrentForWorkspace({ workspaceId: stamp || undefined }, incomingWorkspaceId)) {
          return undefined;
        }
      } else if (!trainingRecordMatchesWorkspace(record, incomingWorkspaceId)) {
        return undefined;
      }
    }
    return (
      asString(record.summary) ??
      asString(record.review_queue_summary) ??
      asString(record.reviewQueueSummary) ??
      asString(record.due) ??
      asString(record.next_review_due) ??
      asString(record.nextReviewDue) ??
      asString(record.due_at) ??
      asString(record.dueAt)
    );
  }
  return asString(value);
}

function mapReviewQueueChrome(
  summaryValue: unknown,
  dueValue: unknown,
  fallbackSummary: string | undefined,
  fallbackDue: string | undefined,
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): { reviewQueueSummary: string; nextReviewDue: string | undefined } {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const incomingSummary = reviewQueueTextForScope(summaryValue, incomingWorkspaceId, workspaceChanged);
  const incomingDue = reviewQueueTextForScope(dueValue, incomingWorkspaceId, workspaceChanged);
  if (workspaceChanged) {
    return {
      reviewQueueSummary: incomingSummary ?? '',
      nextReviewDue: incomingDue,
    };
  }
  return {
    reviewQueueSummary: incomingSummary ?? fallbackSummary ?? '',
    nextReviewDue: incomingDue ?? fallbackDue,
  };
}

function workspaceIdsChanged(incomingWorkspaceId?: string, previousWorkspaceId?: string): boolean {
  const incomingId = incomingWorkspaceId?.trim() ?? '';
  const previousId = previousWorkspaceId?.trim() ?? '';
  return Boolean(incomingId) && Boolean(previousId) && incomingId !== previousId;
}

function emptyLivePlan(): LearningPlanView {
  return {
    id: '',
    title: '',
    frozen: false,
    cadence: '',
    summary: '',
    stages: [],
  };
}

function emptyLiveCoachingState(): NonNullable<BootstrapData['coachingState']> {
  return {
    scenario: 'general',
    answerMode: 'guided',
    learnerSignal: 'steady',
    summary: '',
    nextStep: '',
    encouragement: '',
    updatedAt: '',
  };
}

function emptyLiveEvidenceQueue(): NonNullable<BootstrapData['memory']['evidenceQueue']> {
  return {
    pending: [],
    deferred: [],
    adopted: [],
    rejected: [],
    history: [],
    totalCount: 0,
  };
}

function emptyLiveEvaluation(): EvaluationReportView {
  return {
    headline: '',
    summary: '',
    passRate: 0,
    updatedAt: '',
    checks: [],
    nextStep: '',
  };
}

function emptyLiveLearnerState(): LearnerStateView {
  return {
    currentConfidence: 0,
    frustrationLevel: 0,
    attemptCountRecent: 0,
    needsRescue: false,
    needsReview: false,
    preferredHintDepth: 'guided',
    learnerSignal: 'steady',
    activeFocus: '',
    evidence: [],
  };
}

function emptyLiveTeachingDecision(): TeachingDecisionView {
  return {
    mode: 'guided',
    reason: '',
    primaryGoal: '',
    lessonShape: '',
    exerciseShape: '',
    teachingStrategy: '',
    closingMove: '',
    artifactPriority: [],
    shouldEndWithQuestion: false,
    shouldGenerateExercise: false,
    shouldRevealCode: false,
    shouldProducePlanArtifact: false,
    shouldTriggerDeepAnalysis: false,
    shouldFocusOnImplementationSteps: false,
    toneProfile: 'steady',
    focusArea: '',
  };
}

function emptyLiveAffectState(): AffectStateView {
  return {
    frustrationLevel: 0,
    confidenceLevel: 0.5,
    momentumLevel: 0.5,
    needsReassurance: false,
    urgencyLevel: 'medium',
  };
}

function emptyLiveToneDecision(): ToneDecisionView {
  return {
    tone: 'steady',
    verbosityBias: 'medium',
    acknowledgeProgress: false,
    avoidOverwhelm: false,
  };
}

function emptyLiveImplementationGuide(): ImplementationGuideView {
  return {
    ideaSummary: '',
    scopeBoundary: '',
    mvpDefinition: '',
    currentStep: '',
    nextSteps: [],
    validationStrategy: [],
    openQuestions: [],
  };
}

function emptyLiveAdaptationGuide(): ProjectAdaptationGuideView {
  return {
    targetOutcome: '',
    currentConstraints: [],
    affectedAreas: [],
    preserveAreas: [],
    firstMigrationStep: '',
    migrationSequence: [],
    validationCheckpoints: [],
    rollbackNotes: [],
  };
}

function emptyLivePrincipleNotes(): PrincipleNoteView {
  return {
    currentPrinciple: '',
    whyItMatters: '',
    commonMistake: '',
    applyNow: '',
    transferTargets: [],
  };
}

function emptyLiveCoachTurn(): NonNullable<BootstrapData['coachTurn']> {
  return {
    scenario: 'general',
    learnerSignal: 'steady',
    summary: '',
    nextStep: '',
  };
}

function emptyLiveCoachFocus(): NonNullable<BootstrapData['coachFocus']> {
  return {
    currentFocus: '',
    nextStep: '',
    firstTurnPriority: '',
    strategyPreferenceSummary: '',
    continuitySummary: '',
  };
}

function mapCurrentFocus(
  value: unknown,
  fallback: string,
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
  memoryRecord?: UnknownRecord,
): string {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const incomingFocus = asString(value);
  if (incomingFocus) {
    return incomingFocus;
  }
  const workspace = asRecord(memoryRecord?.workspace);
  const stored = workspace?.latest_coaching_focus ?? workspace?.latestCoachingFocus;
  if (incomingWorkspaceId && stored && trainingRecordMatchesWorkspace(stored, incomingWorkspaceId)) {
    return (
      asString(asRecord(stored)?.focus_area) ??
      asString(asRecord(stored)?.focusArea) ??
      asString(asRecord(stored)?.current_focus) ??
      ''
    );
  }
  return workspaceChanged ? '' : fallback;
}

function emptyLiveTask(): TaskSpecView {
  return {
    id: '',
    title: '',
    description: '',
    constraints: [],
    acceptanceCriteria: [],
    nextActionLabel: '',
  };
}

function resolveCurrentTaskPayload(
  snapshot: UnknownRecord | undefined,
  memoryRecord?: UnknownRecord,
): unknown {
  if (!snapshot) {
    return undefined;
  }
  // Explicit null from start/hydrate: do not fall back to leftover workspace task chrome.
  if (Object.prototype.hasOwnProperty.call(snapshot, 'current_task') && snapshot.current_task == null) {
    return null;
  }
  if (Object.prototype.hasOwnProperty.call(snapshot, 'currentTask') && snapshot.currentTask == null) {
    return null;
  }
  if (Object.prototype.hasOwnProperty.call(snapshot, 'task') && snapshot.task == null) {
    return null;
  }
  const workspace =
    asRecord(memoryRecord?.workspace) ?? asRecord(asRecord(snapshot?.memory)?.workspace);
  const candidates = [
    snapshot?.current_task,
    snapshot?.currentTask,
    workspace?.latest_current_task,
    workspace?.latestCurrentTask,
    workspace?.current_task,
    workspace?.currentTask,
  ];
  for (const candidate of candidates) {
    if (asRecord(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

function applyRecoveryScopeToWorkspace(
  workspace: BootstrapData['memory']['workspace'],
  scope: RecoveryScope | undefined,
): BootstrapData['memory']['workspace'] {
  if (!workspace || !scope) {
    return workspace;
  }
  return {
    ...workspace,
    workspaceId: scope.workspaceId,
    latestPlanRuntime: selectPlanRuntimeForScope(workspace.latestPlanRuntime, scope),
    latestProviderCapability: selectProviderCapabilityForScope(workspace.latestProviderCapability, scope),
    latestStreamingCheckpoint: selectStreamingCheckpointForScope(workspace.latestStreamingCheckpoint, scope),
  };
}

function recoveredPlanRuntimeFromSnapshot(snapshot: UnknownRecord | undefined): UnknownRecord | undefined {
  const workspace = asRecord(asRecord(snapshot?.memory)?.workspace);
  return asRecord(workspace?.latest_plan_runtime ?? workspace?.latestPlanRuntime);
}

function applyLeftoverBoundPlanFiveViewOmit<
  T extends {
    plan?: BootstrapData['plan'];
    planRuntimeStatus?: BootstrapData['planRuntimeStatus'];
    task?: BootstrapData['task'];
    resources?: BootstrapData['resources'];
    memory?: BootstrapData['memory'];
    profile?: BootstrapData['profile'];
    workspaceTrainingState?: BootstrapData['workspaceTrainingState'];
    coachOrientation?: BootstrapData['coachOrientation'];
    suggestedActions?: BootstrapData['suggestedActions'];
  },
>(current: BootstrapData, patch: T): T {
  const liveId = patch.plan?.id ?? '';
  const liveStep = patch.planRuntimeStatus?.currentStep ?? patch.plan?.currentStep ?? '';
  const liveTitle = patch.plan?.title ?? '';
  const labels = leftoverBoundPlanCompetingIdentityLabels({
    livePlanId: liveId,
    liveCurrentStep: liveStep,
    livePlanTitle: liveTitle,
    leftoverPlanId: current.plan.id,
    leftoverPlanTitle: current.plan.title,
    leftoverPlanStep: current.plan.currentStep,
    leftoverCardTitles: [
      current.workspaceTrainingState?.selectedCardTitle,
      current.workspaceTrainingState?.latestTrainingHandoff?.cardTitle,
      current.memory.sandboxPreview?.title,
      current.profile?.onboardingRequest,
      current.profile?.projectContext,
      current.memory.workspace?.onboardingRequest,
      current.memory.workspace?.projectContext,
      current.task?.title,
      ...(current.resources ?? []).map((item) => item.title),
    ],
  });
  if (labels.length === 0) {
    return patch;
  }
  const competing = new Set(labels);
  const omitText = (value: string | undefined): string | undefined => {
    const item = value?.trim() ?? '';
    return item && competing.has(item) ? '' : value;
  };
  const sandboxTitle = patch.memory?.sandboxPreview?.title?.trim() ?? '';
  const selectedDetailTitle = patch.memory?.selectedResourceDetail?.title?.trim() ?? '';
  const handoffTitle = patch.workspaceTrainingState?.latestTrainingHandoff?.cardTitle?.trim() ?? '';
  const orientationLabel = patch.coachOrientation?.objectLabel?.trim() ?? '';
  return {
    ...patch,
    task: patch.task
      ? {
          ...patch.task,
          title: omitText(patch.task.title) ?? '',
        }
      : patch.task,
    resources: patch.resources
      ? patch.resources.filter((item) => !competing.has((item.title ?? '').trim()))
      : patch.resources,
    memory: patch.memory
      ? {
          ...patch.memory,
          sandboxPreview:
            sandboxTitle && competing.has(sandboxTitle) ? undefined : patch.memory.sandboxPreview,
          selectedResourceDetail:
            selectedDetailTitle && competing.has(selectedDetailTitle)
              ? undefined
              : patch.memory.selectedResourceDetail,
          workspace: patch.memory.workspace
            ? {
                ...patch.memory.workspace,
                onboardingRequest: omitText(patch.memory.workspace.onboardingRequest),
                projectContext: omitText(patch.memory.workspace.projectContext),
              }
            : patch.memory.workspace,
        }
      : patch.memory,
    profile: patch.profile
      ? {
          ...patch.profile,
          onboardingRequest: omitText(patch.profile.onboardingRequest),
          projectContext: omitText(patch.profile.projectContext),
        }
      : patch.profile,
    workspaceTrainingState: patch.workspaceTrainingState
      ? {
          ...patch.workspaceTrainingState,
          selectedCardTitle: omitText(patch.workspaceTrainingState.selectedCardTitle),
          latestTrainingHandoff: patch.workspaceTrainingState.latestTrainingHandoff
            ? {
                ...patch.workspaceTrainingState.latestTrainingHandoff,
                cardTitle: omitText(patch.workspaceTrainingState.latestTrainingHandoff.cardTitle),
                learningPhase: competing.has(handoffTitle)
                  ? ''
                  : patch.workspaceTrainingState.latestTrainingHandoff.learningPhase,
              }
            : patch.workspaceTrainingState.latestTrainingHandoff,
          latestTrainingNextHop: patch.workspaceTrainingState.latestTrainingNextHop
            ? {
                ...patch.workspaceTrainingState.latestTrainingNextHop,
                title: omitText(patch.workspaceTrainingState.latestTrainingNextHop.title),
                cardTitle: omitText(patch.workspaceTrainingState.latestTrainingNextHop.cardTitle),
              }
            : patch.workspaceTrainingState.latestTrainingNextHop,
          activeTrainingCardRouting: patch.workspaceTrainingState.activeTrainingCardRouting
            ? {
                ...patch.workspaceTrainingState.activeTrainingCardRouting,
                whyThisCard: omitText(patch.workspaceTrainingState.activeTrainingCardRouting.whyThisCard),
              }
            : patch.workspaceTrainingState.activeTrainingCardRouting,
        }
      : patch.workspaceTrainingState,
    coachOrientation:
      patch.coachOrientation && orientationLabel && competing.has(orientationLabel)
        ? {
            ...patch.coachOrientation,
            objectKind: patch.coachOrientation.objectKind === 'training' ? 'plan' : patch.coachOrientation.objectKind,
            objectLabel: liveStep || liveTitle || patch.coachOrientation.objectLabel,
          }
        : patch.coachOrientation,
    suggestedActions: patch.suggestedActions
      ? patch.suggestedActions.filter((item) => {
          const blob = `${item.action} ${item.label} ${item.rationale ?? ''} ${item.prompt ?? ''} ${item.focusArea ?? ''}`;
          return ![...competing].some((label) => blob.includes(label));
        })
      : patch.suggestedActions,
  };
}

function applyLeftoverNotLiveTaskGuideFocus<
  T extends {
    implementationGuide?: BootstrapData['implementationGuide'];
    coachFocus?: BootstrapData['coachFocus'];
    coachTurn?: BootstrapData['coachTurn'];
    coachingState?: BootstrapData['coachingState'];
    evaluation?: BootstrapData['evaluation'];
    nextStepHint?: BootstrapData['nextStepHint'];
    planRuntimeStatus?: BootstrapData['planRuntimeStatus'];
    reviewQueueSummary?: BootstrapData['reviewQueueSummary'];
    learnerState?: BootstrapData['learnerState'];
    teachingDecision?: BootstrapData['teachingDecision'];
    workspaceTrainingState?: BootstrapData['workspaceTrainingState'];
    memory?: BootstrapData['memory'];
    profile?: BootstrapData['profile'];
    resources?: BootstrapData['resources'];
    conversation?: BootstrapData['conversation'];
    suggestedActions?: BootstrapData['suggestedActions'];
    plan?: BootstrapData['plan'];
    task?: BootstrapData['task'];
    coachOrientation?: BootstrapData['coachOrientation'];
    streamingState?: BootstrapData['streamingState'];
  },
>(patch: T): T {
  if (patch.planRuntimeStatus?.recovered !== true) {
    return patch;
  }
  const chrome = preferRecoveredCoachTaskChrome({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
    ideaSummary: patch.implementationGuide?.ideaSummary,
    scopeBoundary: patch.implementationGuide?.scopeBoundary,
    guideCurrentStep: patch.implementationGuide?.currentStep,
    teachingGoal: patch.implementationGuide?.teachingGoal,
    successSignal: patch.implementationGuide?.successSignal,
    fallbackStep: patch.implementationGuide?.fallbackStep,
    currentFocus: patch.coachFocus?.currentFocus,
    activeTask: patch.coachFocus?.activeTask,
    nextStep: patch.coachFocus?.nextStep,
    activeStage: patch.coachFocus?.activeStage,
  });
  const turnChrome = preferRecoveredCoachTurnChrome({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
    coachTurnNextStep: patch.coachTurn?.nextStep,
    coachTurnSummary: patch.coachTurn?.summary,
    coachTurnTeachingGoal: patch.coachTurn?.teachingGoal,
    coachTurnEncouragement: patch.coachTurn?.encouragement,
    coachTurnActiveStage: patch.coachTurn?.activeStage,
    coachingStateNextStep: patch.coachingState?.nextStep,
    coachingStateSummary: patch.coachingState?.summary,
    coachingStateTeachingGoal: patch.coachingState?.teachingGoal,
    coachingStateEncouragement: patch.coachingState?.encouragement,
    evaluationNextStep: patch.evaluation?.nextStep,
    nextStepHintTitle: patch.nextStepHint?.title,
    nextStepHintSummary: patch.nextStepHint?.summary,
    resumeThread: patch.coachTurn?.resumeThread ?? patch.coachingState?.resumeThread,
    supportStrategy: patch.coachTurn?.supportStrategy ?? patch.coachingState?.supportStrategy,
    reviewQueueSummary:
      patch.coachTurn?.reviewQueueSummary ??
      patch.reviewQueueSummary ??
      patch.planRuntimeStatus?.reviewQueueSummary,
    continuitySummary: patch.coachFocus?.continuitySummary,
    coachJudgmentSummary: patch.planRuntimeStatus?.coachJudgment?.summary,
    coachJudgmentTeachingGoal: patch.planRuntimeStatus?.coachJudgment?.teachingGoal,
  });
  const leftoverChromeIdentity = {
    recovered: true as const,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
    runtimePlanId: patch.memory?.workspace?.latestPlanRuntime?.planId,
    planId: patch.plan?.id,
    planCurrentStep: patch.plan?.currentStep,
  };
  const leftoverTrainingHandoffNotLive = leftoverTrainingHandoffChromeIsNotLive(leftoverChromeIdentity);
  const trainingFocusChrome = preferRecoveredTrainingFocusChrome({
    ...leftoverChromeIdentity,
    teachingDecisionFocusArea: patch.teachingDecision?.focusArea,
    learnerStateActiveFocus: patch.learnerState?.activeFocus,
    latestLearningFocusArea:
      patch.workspaceTrainingState?.latestLearningFocusArea ??
      patch.memory?.workspace?.latestLearningFocusArea,
  });
  const trainingHandoffChrome = preferRecoveredTrainingHandoffChrome({
    ...leftoverChromeIdentity,
    successSignal: patch.workspaceTrainingState?.latestTrainingHandoff?.successSignal,
    returnWith: patch.workspaceTrainingState?.latestTrainingHandoff?.returnWith,
    cardTitle: patch.workspaceTrainingState?.latestTrainingHandoff?.cardTitle,
    selectedCardTitle: patch.workspaceTrainingState?.selectedCardTitle,
    followup: patch.workspaceTrainingState?.latestLearningFollowup,
    blocker:
      patch.workspaceTrainingState?.latestLearningBlocker ??
      patch.workspaceTrainingState?.latestTrainingHandoff?.blockedBy,
    handoffSummary: patch.workspaceTrainingState?.latestTrainingHandoff?.handoffSummary,
    nextAfterCompletion: patch.workspaceTrainingState?.latestTrainingHandoff?.nextAfterCompletion,
    fallbackAction: patch.workspaceTrainingState?.latestTrainingHandoff?.fallbackAction,
    nextHopTitle: patch.workspaceTrainingState?.latestTrainingNextHop?.title,
    nextHopCardTitle: patch.workspaceTrainingState?.latestTrainingNextHop?.cardTitle,
    nextHopHandoffSummary: patch.workspaceTrainingState?.latestTrainingNextHop?.handoffSummary,
    nextHopNextAfterCompletion: patch.workspaceTrainingState?.latestTrainingNextHop?.nextAfterCompletion,
    nextHopFallbackAction: patch.workspaceTrainingState?.latestTrainingNextHop?.fallbackAction,
    routingNextAfterCompletion:
      patch.workspaceTrainingState?.activeTrainingCardRouting?.nextAfterCompletion,
    routingFallbackAction: patch.workspaceTrainingState?.activeTrainingCardRouting?.fallbackAction,
    whyThisCard: patch.workspaceTrainingState?.activeTrainingCardRouting?.whyThisCard,
    ledgerWhyThisCard: patch.workspaceTrainingState?.trainingEventLedger?.[0]?.whyThisCard,
    returnSummary: patch.workspaceTrainingState?.latestTrainingHandoff?.returnSummary,
    nextHopReturnSummary: patch.workspaceTrainingState?.latestTrainingNextHop?.returnSummary,
    nextHopSummary: patch.workspaceTrainingState?.latestTrainingNextHop?.summary,
    nextHopWhyNow: patch.workspaceTrainingState?.latestTrainingNextHop?.whyNow,
  });
  const resourceSelectedDetailNotLive = leftoverResourceSelectedDetailIsNotLive({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
  });
  const resourceSandboxPreviewNotLive = leftoverResourceSandboxPreviewIsNotLive({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
  });
  const resourceSandboxStateNotLive = leftoverResourceSandboxStateIsNotLive({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
  });
  const resourceLibraryListNotLive = leftoverResourceLibraryListIsNotLive({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
  });
  const coachConversationNotLive = leftoverCoachConversationIsNotLive({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
  });
  const suggestedActionsNotLive = leftoverSuggestedActionsIsNotLive({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
  });
  const firstLookHeadlineNotLive = leftoverFirstLookHeadlineIsNotLive({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
  });
  const evaluationHeadlineNotLive = leftoverEvaluationHeadlineIsNotLive({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
  });
  const streamingCheckpointNotLive = leftoverStreamingCheckpointIsNotLive({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
  });
  const transferSkillNotLive = leftoverTransferSkillIsNotLive({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
  });
  const liveWorkspaceTransferState = preferRecoveredTransferSkill({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
    transfer: patch.memory?.workspace?.latestTransferState,
  });
  const liveTrainingTransferState = preferRecoveredTransferSkill({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
    transfer: patch.workspaceTrainingState?.latestTransferState,
  });
  const settingsProfileRhythmNotLive = leftoverSettingsProfileRhythmIsNotLive({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
  });
  const settingsLearnerProjectOnboardingNotLive = leftoverSettingsLearnerProjectOnboardingIsNotLive({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
  });
  const mintingSuggestedActionsNotLive = leftoverMintingSuggestedActionsAreNotLive({
    recovered: true,
    runtimeCurrentStep: patch.planRuntimeStatus.currentStep,
    runtimePlanId: patch.memory?.workspace?.latestPlanRuntime?.planId,
    planId: patch.plan?.id,
    planCurrentStep: patch.plan?.currentStep,
    taskTitle: patch.task?.title,
  });
  const leftoverHonestSuggestedActions = suggestedActionsNotLive
    ? []
    : mintingSuggestedActionsNotLive
      ? (patch.suggestedActions ?? []).filter(
          (item) => !['plan', 'task', 'next_task', 'card'].includes(String(item.action ?? '')),
        )
      : patch.suggestedActions;
  return {
    ...patch,
    implementationGuide: patch.implementationGuide
      ? {
          ...patch.implementationGuide,
          ideaSummary: chrome.ideaSummary ?? '',
          scopeBoundary: chrome.scopeBoundary ?? '',
          currentStep: chrome.currentStep ?? '',
          teachingGoal: chrome.teachingGoal,
          successSignal: chrome.successSignal,
          fallbackStep: chrome.fallbackStep,
        }
      : patch.implementationGuide,
    coachFocus: patch.coachFocus
      ? {
          ...patch.coachFocus,
          currentFocus: chrome.currentFocus,
          activeTask: chrome.activeTask,
          nextStep: chrome.nextStep,
          activeStage: chrome.activeStage,
          continuitySummary: turnChrome.continuitySummary,
        }
      : patch.coachFocus,
    coachTurn: patch.coachTurn
      ? {
          ...patch.coachTurn,
          nextStep: turnChrome.coachTurnNextStep ?? '',
          summary: turnChrome.coachTurnSummary ?? '',
          teachingGoal: turnChrome.coachTurnTeachingGoal,
          encouragement: turnChrome.coachTurnEncouragement,
          activeStage: turnChrome.coachTurnActiveStage,
          resumeThread: turnChrome.resumeThread,
          supportStrategy: turnChrome.supportStrategy,
          reviewQueueSummary: turnChrome.reviewQueueSummary,
        }
      : patch.coachTurn,
    coachingState: patch.coachingState
      ? {
          ...patch.coachingState,
          nextStep: turnChrome.coachingStateNextStep ?? '',
          summary: turnChrome.coachingStateSummary ?? '',
          teachingGoal: turnChrome.coachingStateTeachingGoal,
          encouragement: turnChrome.coachingStateEncouragement,
          resumeThread: turnChrome.resumeThread,
          supportStrategy: turnChrome.supportStrategy,
        }
      : patch.coachingState,
    evaluation: patch.evaluation
      ? {
          ...patch.evaluation,
          nextStep: turnChrome.evaluationNextStep ?? '',
          headline: evaluationHeadlineNotLive ? '' : patch.evaluation.headline,
        }
      : patch.evaluation,
    nextStepHint: patch.nextStepHint
      ? {
          ...patch.nextStepHint,
          title: turnChrome.nextStepHintTitle ?? '',
          summary: turnChrome.nextStepHintSummary,
        }
      : patch.nextStepHint,
    reviewQueueSummary: turnChrome.reviewQueueSummary ?? '',
    planRuntimeStatus: patch.planRuntimeStatus
      ? {
          ...patch.planRuntimeStatus,
          reviewQueueSummary: turnChrome.reviewQueueSummary,
          coachJudgment: patch.planRuntimeStatus.coachJudgment
            ? {
                ...patch.planRuntimeStatus.coachJudgment,
                resumeThread: turnChrome.resumeThread,
                supportStrategy: turnChrome.supportStrategy,
                summary: turnChrome.coachJudgmentSummary,
                teachingGoal: turnChrome.coachJudgmentTeachingGoal,
              }
            : patch.planRuntimeStatus.coachJudgment,
        }
      : patch.planRuntimeStatus,
    learnerState: patch.learnerState
      ? {
          ...patch.learnerState,
          activeFocus: trainingFocusChrome.learnerStateActiveFocus ?? '',
        }
      : patch.learnerState,
    teachingDecision: patch.teachingDecision
      ? {
          ...patch.teachingDecision,
          focusArea: trainingFocusChrome.teachingDecisionFocusArea ?? '',
        }
      : patch.teachingDecision,
    workspaceTrainingState: patch.workspaceTrainingState
      ? {
          ...patch.workspaceTrainingState,
          latestTransferState: transferSkillNotLive
            ? liveTrainingTransferState
            : patch.workspaceTrainingState.latestTransferState,
          latestLearningFocusArea: trainingFocusChrome.latestLearningFocusArea,
          selectedCardId: leftoverTrainingHandoffNotLive
            ? undefined
            : patch.workspaceTrainingState.selectedCardId,
          selectedCardTitle: trainingHandoffChrome.selectedCardTitle,
          latestLearningFollowup: trainingHandoffChrome.followup,
          latestLearningBlocker: trainingHandoffChrome.blocker,
          latestLearningVerifiedResult: leftoverTrainingHandoffNotLive
            ? undefined
            : patch.workspaceTrainingState.latestLearningVerifiedResult,
          latestLearningPartialProgress: leftoverTrainingHandoffNotLive
            ? undefined
            : patch.workspaceTrainingState.latestLearningPartialProgress,
          reviewArtifact: leftoverTrainingHandoffNotLive
            ? undefined
            : patch.workspaceTrainingState.reviewArtifact,
          latestTrainingHandoff: patch.workspaceTrainingState.latestTrainingHandoff
            ? {
                ...patch.workspaceTrainingState.latestTrainingHandoff,
                successSignal: trainingHandoffChrome.successSignal,
                returnWith: trainingHandoffChrome.returnWith,
                cardTitle: trainingHandoffChrome.cardTitle,
                blockedBy: trainingHandoffChrome.blocker,
                handoffSummary: trainingHandoffChrome.handoffSummary,
                nextAfterCompletion: trainingHandoffChrome.nextAfterCompletion,
                fallbackAction: trainingHandoffChrome.fallbackAction,
                returnSummary: trainingHandoffChrome.returnSummary,
              }
            : patch.workspaceTrainingState.latestTrainingHandoff,
          latestTrainingNextHop: patch.workspaceTrainingState.latestTrainingNextHop
            ? {
                ...patch.workspaceTrainingState.latestTrainingNextHop,
                title: trainingHandoffChrome.nextHopTitle,
                cardTitle: trainingHandoffChrome.nextHopCardTitle,
                handoffSummary: trainingHandoffChrome.nextHopHandoffSummary,
                nextAfterCompletion: trainingHandoffChrome.nextHopNextAfterCompletion,
                fallbackAction: trainingHandoffChrome.nextHopFallbackAction,
                returnSummary: trainingHandoffChrome.nextHopReturnSummary,
                summary: trainingHandoffChrome.nextHopSummary,
                whyNow: trainingHandoffChrome.nextHopWhyNow,
              }
            : patch.workspaceTrainingState.latestTrainingNextHop,
          activeTrainingCardRouting: patch.workspaceTrainingState.activeTrainingCardRouting
            ? {
                ...patch.workspaceTrainingState.activeTrainingCardRouting,
                nextAfterCompletion: trainingHandoffChrome.routingNextAfterCompletion,
                fallbackAction: trainingHandoffChrome.routingFallbackAction,
                whyThisCard: trainingHandoffChrome.whyThisCard,
              }
            : patch.workspaceTrainingState.activeTrainingCardRouting,
          trainingEventLedger: patch.workspaceTrainingState.trainingEventLedger?.length
            ? [
                {
                  ...patch.workspaceTrainingState.trainingEventLedger[0],
                  whyThisCard: trainingHandoffChrome.ledgerWhyThisCard,
                },
                ...patch.workspaceTrainingState.trainingEventLedger.slice(1),
              ]
            : patch.workspaceTrainingState.trainingEventLedger,
        }
      : patch.workspaceTrainingState,
    profile: (settingsProfileRhythmNotLive || settingsLearnerProjectOnboardingNotLive) && patch.profile
      ? {
          ...patch.profile,
          preferredRhythm: settingsProfileRhythmNotLive ? undefined : patch.profile.preferredRhythm,
          preferredLearningMode: settingsProfileRhythmNotLive
            ? undefined
            : patch.profile.preferredLearningMode,
          learnerName: settingsLearnerProjectOnboardingNotLive ? undefined : patch.profile.learnerName,
          targetProject: settingsLearnerProjectOnboardingNotLive ? undefined : patch.profile.targetProject,
          onboardingRequest: settingsLearnerProjectOnboardingNotLive
            ? undefined
            : patch.profile.onboardingRequest,
          projectContext: settingsLearnerProjectOnboardingNotLive ? undefined : patch.profile.projectContext,
        }
      : patch.profile,
    memory: patch.memory
      ? {
          ...patch.memory,
          activeThread: coachConversationNotLive ? undefined : patch.memory.activeThread,
          selectedResourceDetail: resourceSelectedDetailNotLive
            ? undefined
            : patch.memory.selectedResourceDetail,
          sandboxPreview: resourceSandboxPreviewNotLive
            ? undefined
            : patch.memory.sandboxPreview,
          sandboxState: resourceSandboxStateNotLive
            ? undefined
            : patch.memory.sandboxState,
          workspace: patch.memory.workspace
            ? {
                ...patch.memory.workspace,
                latestLearningFocusArea: trainingFocusChrome.latestLearningFocusArea,
                preferredRhythm: settingsProfileRhythmNotLive
                  ? undefined
                  : patch.memory.workspace.preferredRhythm,
                preferredLearningMode: settingsProfileRhythmNotLive
                  ? undefined
                  : patch.memory.workspace.preferredLearningMode,
                coachDefaults: settingsProfileRhythmNotLive
                  ? undefined
                  : patch.memory.workspace.coachDefaults,
                learnerName: settingsLearnerProjectOnboardingNotLive
                  ? undefined
                  : patch.memory.workspace.learnerName,
                projectContext: settingsLearnerProjectOnboardingNotLive
                  ? undefined
                  : patch.memory.workspace.projectContext,
                onboardingRequest: settingsLearnerProjectOnboardingNotLive
                  ? undefined
                  : patch.memory.workspace.onboardingRequest,
                latestStreamingCheckpoint:
                  streamingCheckpointNotLive && !patch.streamingState?.isStreaming
                    ? undefined
                    : patch.memory.workspace.latestStreamingCheckpoint,
                latestTransferState: transferSkillNotLive
                  ? liveWorkspaceTransferState
                  : patch.memory.workspace.latestTransferState,
              }
            : patch.memory.workspace,
          workspaceUnderstanding: firstLookHeadlineNotLive
            ? patch.memory.workspaceUnderstanding
              ? {
                  ...patch.memory.workspaceUnderstanding,
                  firstLookSummary: undefined,
                }
              : patch.memory.workspaceUnderstanding
            : patch.memory.workspaceUnderstanding,
        }
      : patch.memory,
    resources: resourceLibraryListNotLive ? [] : patch.resources,
    conversation: coachConversationNotLive ? [] : patch.conversation,
    suggestedActions: suggestedActionsNotLive ? [] : leftoverHonestSuggestedActions,
    coachOrientation:
      streamingCheckpointNotLive &&
      !patch.streamingState?.isStreaming &&
      patch.coachOrientation?.primaryAction === 'resume_checkpoint'
        ? undefined
        : patch.coachOrientation,
    streamingState:
      streamingCheckpointNotLive && !patch.streamingState?.isStreaming
        ? createEmptyTrainerStreamingState()
        : patch.streamingState,
  };
}

function mapPlanRuntimeStatus(
  value: unknown,
  snapshot: UnknownRecord | undefined,
  fallback: BootstrapData['planRuntimeStatus'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['planRuntimeStatus'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const scopedFallback = workspaceChanged ? undefined : fallback;
  let incomingRecord = asRecord(value);
  if (incomingWorkspaceId && incomingRecord) {
    const incomingWorkspaceStamp =
      asString(incomingRecord.workspace_id) ?? asString(incomingRecord.workspaceId);
    if (workspaceChanged) {
      if (
        !isCurrentForWorkspace(
          { workspaceId: incomingWorkspaceStamp || undefined },
          incomingWorkspaceId,
        )
      ) {
        incomingRecord = undefined;
      }
    } else if (!trainingRecordMatchesWorkspace(incomingRecord, incomingWorkspaceId)) {
      incomingRecord = undefined;
    }
  }
  const latestRuntime = recoveredPlanRuntimeFromSnapshot(snapshot);
  const latestOverlay = incomingWorkspaceId
    ? planRuntimeStatusFromRecovery(latestRuntime, incomingWorkspaceId)
    : undefined;
  const incomingOverlay =
    incomingWorkspaceId && incomingRecord
      ? planRuntimeStatusFromRecovery(incomingRecord, incomingWorkspaceId)
      : incomingRecord?.recovered === true
        ? planRuntimeStatusFromRecovery(
            incomingRecord,
            asString(incomingRecord.workspace_id) ?? asString(incomingRecord.workspaceId) ?? '',
          )
        : undefined;
  const overlay = latestOverlay ?? incomingOverlay;
  const recovered = incomingWorkspaceId
    ? selectPlanRuntimeForScope(latestRuntime, { workspaceId: incomingWorkspaceId })
    : latestRuntime;
  const record = incomingRecord ?? asRecord(recovered);
  if (!record) {
    if (!snapshot) {
      return scopedFallback;
    }
    const derivedCurrentStage = deriveCurrentStageFromSnapshot(snapshot);
    const reviewQueueSummary =
      asString(snapshot.review_queue_summary) ?? scopedFallback?.reviewQueueSummary;
    const nextReviewDue =
      asString(snapshot.next_review_due) ?? scopedFallback?.nextReviewDue;
    if (!derivedCurrentStage && !reviewQueueSummary && !nextReviewDue) {
      return scopedFallback;
    }
    return {
      currentStage: derivedCurrentStage ?? scopedFallback?.currentStage,
      currentMainThread: scopedFallback?.currentMainThread,
      reviewPoints: scopedFallback?.reviewPoints ?? [],
      coachJudgment: scopedFallback?.coachJudgment,
      nextTrainingAction: scopedFallback?.nextTrainingAction,
      reviewQueueSummary,
      nextReviewDue,
    };
  }

  const currentStage = asRecord(record.current_stage);
  const currentMainThread = asRecord(record.current_main_thread);
  const coachJudgment = asRecord(record.coach_judgment);
  const reviewPoints: PlanRuntimeStatusView['reviewPoints'] = Array.isArray(record.review_points)
    ? record.review_points.reduce<PlanRuntimeStatusView['reviewPoints']>((items, point) => {
        const pointRecord = asRecord(point);
        if (!pointRecord) {
          return items;
        }
        items.push({
          concept: asString(pointRecord.concept) ?? '',
          reason: asString(pointRecord.reason) ?? '',
          severity: toReviewSeverity(asString(pointRecord.severity)),
          dueAt: asString(pointRecord.due_at) ?? undefined,
          source: asString(pointRecord.source) ?? undefined,
          surfaceMode: toReviewSurfaceMode(asString(pointRecord.surface_mode)),
          taskHint: asString(pointRecord.task_hint) ?? undefined,
          focusArea: asString(pointRecord.focus_area) ?? undefined,
          linkedContext: toLinkedContext(pointRecord.linked_context),
          intervalDays: asNumber(pointRecord.interval_days) ?? undefined,
          masteryScore: asNumber(pointRecord.mastery_score) ?? undefined,
        });
        return items;
      }, [])
    : (scopedFallback?.reviewPoints ?? []);

  return {
    currentStage: overlay
      ? overlay.currentStep && currentStage
        ? {
            id: asString(currentStage.id) ?? undefined,
            title: asString(currentStage.title) ?? undefined,
            goal: asString(currentStage.goal) ?? undefined,
            status: asString(currentStage.status) ?? undefined,
          }
        : undefined
      : currentStage
      ? {
          id: asString(currentStage.id) ?? undefined,
          title: asString(currentStage.title) ?? undefined,
          goal: asString(currentStage.goal) ?? undefined,
          status: asString(currentStage.status) ?? undefined,
        }
      : deriveCurrentStageFromSnapshot(snapshot) ?? scopedFallback?.currentStage,
    currentMainThread: currentMainThread
      ? {
          scenario: asString(currentMainThread.scenario) ?? undefined,
          focusArea:
            overlay && !overlay.currentStep
              ? undefined
              : asString(currentMainThread.focus_area) ?? undefined,
          summary: asString(currentMainThread.summary) ?? undefined,
          nextStep: asString(currentMainThread.next_step) ?? undefined,
          blocker: overlay
            ? overlay.blockedReason
            : asString(currentMainThread.blocker) ?? undefined,
          currentStep: overlay
            ? overlay.currentStep
            : asString(currentMainThread.current_step) ??
              asString(record.current_step) ??
              undefined,
          whyNow: overlay
            ? overlay.whyNow
            : asString(currentMainThread.why_now) ?? asString(record.why_now) ?? undefined,
          verifyMethod: overlay
            ? overlay.verifyMethod
            : asStringArray(currentMainThread.verify_method) ??
              asStringArray(record.verify_method) ??
              undefined,
          blockedReason: overlay
            ? overlay.blockedReason
            : asString(currentMainThread.blocked_reason) ??
              asString(record.blocked_reason) ??
              asString(currentMainThread.blocker) ??
              undefined,
          nextAfterCurrent: overlay
            ? overlay.nextAfterCurrent
            : asString(currentMainThread.next_after_current) ??
              asString(record.next_after_current) ??
              undefined,
          verifiedResult: asString(currentMainThread.verified_result) ?? undefined,
        }
      : overlay
        ? undefined
        : scopedFallback?.currentMainThread,
    reviewPoints,
    coachJudgment: coachJudgment
      ? {
          summary: asString(coachJudgment.summary) ?? undefined,
          teachingGoal: coachSurfaceText(coachJudgment.teaching_goal) ?? undefined,
          interventionStrategy: coachSurfaceText(coachJudgment.intervention_strategy) ?? undefined,
          supportStrategy: coachSurfaceText(coachJudgment.support_strategy) ?? undefined,
          resumeThread: coachSurfaceText(coachJudgment.resume_thread) ?? undefined,
        }
      : scopedFallback?.coachJudgment,
    nextTrainingAction:
      overlay && !overlay.currentStep
        ? undefined
        : asString(record.next_training_action) ??
          (overlay ? undefined : scopedFallback?.nextTrainingAction),
    reviewQueueSummary:
      coachSurfaceText(record.review_queue_summary) ??
      coachSurfaceText(snapshot?.review_queue_summary) ??
      scopedFallback?.reviewQueueSummary,
    nextReviewDue:
      asString(record.next_review_due) ??
      asString(snapshot?.next_review_due) ??
      scopedFallback?.nextReviewDue,
    currentStep: overlay
      ? overlay.currentStep
      : asString(record.current_step) ??
        asString(currentMainThread?.current_step) ??
        (record.recovered === true ? undefined : scopedFallback?.currentStep),
    whyNow: overlay
      ? overlay.whyNow
      : asString(record.why_now) ??
        asString(currentMainThread?.why_now) ??
        (record.recovered === true ? undefined : scopedFallback?.whyNow),
    verifyMethod: overlay
      ? overlay.verifyMethod
      : asStringArray(record.verify_method) ??
        asStringArray(currentMainThread?.verify_method) ??
        (record.recovered === true ? undefined : scopedFallback?.verifyMethod),
    blockedReason: overlay
      ? overlay.blockedReason
      : asString(record.blocked_reason) ??
        asString(currentMainThread?.blocked_reason) ??
        asString(currentMainThread?.blocker) ??
        (record.recovered === true ? undefined : scopedFallback?.blockedReason),
    nextAfterCurrent: overlay
      ? overlay.nextAfterCurrent
      : asString(record.next_after_current) ??
        asString(currentMainThread?.next_after_current) ??
        (record.recovered === true ? undefined : scopedFallback?.nextAfterCurrent),
    nextStepHint: mapNextStepHint(
      record.next_step_hint,
      scopedFallback?.nextStepHint,
      incomingWorkspaceId,
      previousWorkspaceId,
    ),
    recovered: overlay ? true : record.recovered === true,
    currentStageId: overlay
      ? overlay.currentStep
        ? overlay.currentStageId
        : undefined
      : asString(record.current_stage_id) ??
        asString(record.currentStageId) ??
        undefined,
    resumeState:
      overlay?.resumeState ??
      normalizePlanRuntimeResumeState(record.resume_state ?? record.resumeState) ??
      (record.recovered === true || overlay ? 'interrupted' : undefined),
    requestId:
      overlay?.requestId ??
      asString(record.request_id) ??
      asString(record.requestId) ??
      undefined,
    revision: overlay?.revision ?? asNumber(record.revision) ?? undefined,
    verifyPlanAdvance: mapVerifyPlanAdvance(
      record.verify_plan_advance ?? record.verifyPlanAdvance,
      scopedFallback?.verifyPlanAdvance,
    ),
  } satisfies PlanRuntimeStatusView;
}

function mapVerifyPlanAdvance(
  value: unknown,
  fallback: PlanRuntimeStatusView['verifyPlanAdvance'],
): PlanRuntimeStatusView['verifyPlanAdvance'] {
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }
  const what = asString(record.what) ?? '';
  const why = asString(record.why) ?? '';
  const next = asString(record.next) ?? '';
  if (!what && !why && !next && record.advanced !== true && record.advanced !== false) {
    return fallback;
  }
  return {
    advanced: record.advanced === true,
    what: what || undefined,
    why: why || undefined,
    next: next || undefined,
    planId: asString(record.plan_id) ?? asString(record.planId) ?? null,
  };
}

function emptyLiveNextStepHint(): NextStepHintView {
  return {
    title: '',
    summary: '',
  };
}

function mapNextStepHint(
  value: unknown,
  fallback: BootstrapData['nextStepHint'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['nextStepHint'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  if (workspaceChanged) {
    const scoped = incomingWorkspaceId
      ? selectNextStepHintForScope(value, { workspaceId: incomingWorkspaceId })
      : undefined;
    if (!scoped) {
      return emptyLiveNextStepHint();
    }
  }
  const record = asRecord(value);
  if (
    incomingWorkspaceId &&
    record &&
    !trainingRecordMatchesWorkspace(record, incomingWorkspaceId)
  ) {
    return workspaceChanged ? emptyLiveNextStepHint() : fallback;
  }
  const normalized = normalizeNextStepHint(value);
  if (!normalized) {
    return workspaceChanged ? emptyLiveNextStepHint() : fallback;
  }
  const useFallback = !workspaceChanged;
  return {
    title: normalized.title,
    summary: normalized.summary ?? (useFallback ? fallback?.summary : undefined),
    recommendedAction: normalized.recommendedAction ?? (useFallback ? fallback?.recommendedAction : undefined),
    focusArea: normalized.focusArea ?? (useFallback ? fallback?.focusArea : undefined),
    prompt: normalized.prompt ?? (useFallback ? fallback?.prompt : undefined),
    resumeThread: normalized.resumeThread ?? (useFallback ? fallback?.resumeThread : undefined),
    source: normalized.source ?? (useFallback ? fallback?.source : undefined),
    continueIn: normalized.continueIn ?? (useFallback ? fallback?.continueIn : undefined),
    verification: normalized.verification ?? (useFallback ? fallback?.verification : undefined),
  } satisfies NextStepHintView;
}

function deriveCurrentStageFromSnapshot(snapshot: UnknownRecord | undefined) {
  const plan = asRecord(snapshot?.plan);
  const stages = Array.isArray(plan?.stages) ? plan.stages : [];
  const currentStageId = asString(plan?.current_stage_id);
  const activeStage = stages.find((stage) => {
    const record = asRecord(stage);
    const stageId = asString(record?.id);
    const status = asString(record?.status);
    return stageId === currentStageId || status === 'active';
  });
  const record = asRecord(activeStage);
  if (!record) {
    return undefined;
  }
  return {
    id: asString(record.id) ?? undefined,
    title: asString(record.title) ?? undefined,
    goal: asString(record.goal) ?? undefined,
    status: asString(record.status) ?? undefined,
  };
}

function mapPlanStage(value: unknown, index: number) {
  const record = asRecord(value);
  const rawStatus = asString(record?.status);
  return {
    id: asString(record?.id) ?? `stage-${index + 1}`,
    title: asString(record?.title) ?? `阶段 ${index + 1}`,
    objective:
      asString(record?.goal) ??
      asString(record?.objective) ??
      asString(record?.completion_signal) ??
      '继续推进当前训练计划。',
    status:
      rawStatus === 'completed'
        ? 'done'
        : rawStatus === 'active'
          ? 'active'
          : 'queued',
  } as const;
}

function mapTask(
  value: unknown,
  fallback: TaskSpecView,
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): TaskSpecView {
  if (value === null) {
    return emptyLiveTask();
  }
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const record = asRecord(value);
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? emptyLiveTask() : fallback;
  }
  const useFallback = !workspaceChanged;
  return {
    id: asString(record.id) ?? (useFallback ? fallback.id : ''),
    title: asString(record.title) ?? (useFallback ? fallback.title : ''),
    description:
      asString(record.natural_language_goal) ??
      asString(record.naturalLanguageGoal) ??
      asString(record.description) ??
      (useFallback ? fallback.description : ''),
    constraints: asStringArray(record.constraints) ?? (useFallback ? fallback.constraints : []),
    acceptanceCriteria:
      asStringArray(record.outputs) ??
      asStringArray(record.verification_strategy) ??
      (useFallback ? fallback.acceptanceCriteria : []),
    nextActionLabel: useFallback ? fallback.nextActionLabel || '评估当前文件' : '',
  };
}

function mapEvaluation(
  value: unknown,
  fallback: EvaluationReportView,
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): EvaluationReportView {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const record = asRecord(value);
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? emptyLiveEvaluation() : fallback;
  }
  const useFallback = !workspaceChanged;
  const checks = [
    ...mapEvaluationChecks(record.static_checks),
    ...mapEvaluationChecks(record.dynamic_checks),
    ...mapEvaluationChecks(record.semantic_checks),
  ];
  const passCount = checks.filter((check) => check.status === 'pass').length;
  const passRate = checks.length === 0 ? 0 : passCount / checks.length;

  return {
    headline: checks.length
      ? `${passCount} of ${checks.length} checks passed`
      : (useFallback ? fallback.headline : ''),
    summary: asString(record.summary) ?? (useFallback ? fallback.summary : ''),
    passRate,
    updatedAt: formatTimestamp(new Date().toISOString()),
    checks,
    nextStep: asString(record.next_step) ?? (useFallback ? fallback.nextStep : ''),
  };
}

function mapEvaluationChecks(value: unknown): EvaluationReportView['checks'] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item, index) => {
    const record = asRecord(item);
    const rawStatus = asString(record?.status);
    return {
      id: asString(record?.id) ?? `check-${index + 1}`,
      label: asString(record?.label) ?? `检查项 ${index + 1}`,
      status:
        rawStatus === 'passed'
          ? 'pass'
          : rawStatus === 'failed'
            ? 'fail'
            : rawStatus === 'warning'
              ? 'warn'
              : 'pending',
      detail: asString(record?.detail) ?? '',
    } as const;
  });
}

function emptyLiveCoachingAdaptation(): NonNullable<BootstrapData['memory']['coachingAdaptation']> {
  return {
    summary: '',
    evidence: [],
  };
}

function mapCoachingAdaptation(
  value: unknown,
  fallback: BootstrapData['memory']['coachingAdaptation'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['memory']['coachingAdaptation'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  if (workspaceChanged) {
    const scoped = incomingWorkspaceId
      ? selectCoachingAdaptationForScope(value, { workspaceId: incomingWorkspaceId })
      : undefined;
    if (!scoped) {
      return emptyLiveCoachingAdaptation();
    }
  }
  const record = asRecord(value);
  if (
    incomingWorkspaceId &&
    record &&
    !trainingRecordMatchesWorkspace(record, incomingWorkspaceId)
  ) {
    return workspaceChanged ? emptyLiveCoachingAdaptation() : fallback;
  }
  if (!record) {
    return workspaceChanged ? emptyLiveCoachingAdaptation() : fallback;
  }
  const useFallback = !workspaceChanged;
  const challenge = asText(record.challenge_level) ?? asText(record.challengeLevel);
  const hintDepth = asText(record.hint_depth) ?? asText(record.hintDepth);
  const reviewUrgency = asText(record.review_urgency) ?? asText(record.reviewUrgency);
  const explanationMode = asText(record.explanation_mode) ?? asText(record.explanationMode);
  const nextStepBias = asText(record.next_step_bias) ?? asText(record.nextStepBias);
  const difficulty = asText(record.difficulty);
  const explanationDepth = asText(record.explanation_depth) ?? asText(record.explanationDepth);
  const codeReveal = asText(record.code_reveal) ?? asText(record.codeReveal);
  const practiceType = asText(record.practice_type) ?? asText(record.practiceType);
  const reviewFrequency = asText(record.review_frequency) ?? asText(record.reviewFrequency);
  const materialRecommendation =
    asText(record.material_recommendation) ?? asText(record.materialRecommendation);
  const nextPlanStep = asText(record.next_plan_step) ?? asText(record.nextPlanStep);
  const pedagogyMode = asText(record.pedagogy_mode) ?? asText(record.pedagogyMode);
  const timeBudget = asText(record.time_budget) ?? asText(record.timeBudget);
  const projectComplexity = asText(record.project_complexity) ?? asText(record.projectComplexity);
  const taskUrgency = asText(record.task_urgency) ?? asText(record.taskUrgency);
  const pressureBlocksLiveObjectMint =
    asBoolean(record.pressure_blocks_live_object_mint) ??
    asBoolean(record.pressureBlocksLiveObjectMint);
  const streakBlocksLiveObjectMint =
    asBoolean(record.streak_blocks_live_object_mint) ??
    asBoolean(record.streakBlocksLiveObjectMint);
  const closedLoopReturnBlocksTaskMint =
    asBoolean(record.closed_loop_return_blocks_task_mint) ??
    asBoolean(record.closedLoopReturnBlocksTaskMint);
  return {
    challengeLevel:
      challenge === 'lower' || challenge === 'raise' || challenge === 'steady'
        ? challenge
        : useFallback
          ? fallback?.challengeLevel
          : undefined,
    hintDepth:
      hintDepth === 'direct' || hintDepth === 'guided' || hintDepth === 'lighter'
        ? hintDepth
        : useFallback
          ? fallback?.hintDepth
          : undefined,
    reviewUrgency:
      reviewUrgency === 'high' || reviewUrgency === 'normal' || reviewUrgency === 'low'
        ? reviewUrgency
        : useFallback
          ? fallback?.reviewUrgency
          : undefined,
    explanationMode:
      explanationMode === 'rebuild' || explanationMode === 'grounded' || explanationMode === 'transfer'
        ? explanationMode
        : useFallback
          ? fallback?.explanationMode
          : undefined,
    nextStepBias:
      nextStepBias === 'shrink' || nextStepBias === 'steady' || nextStepBias === 'widen'
        ? nextStepBias
        : useFallback
          ? fallback?.nextStepBias
          : undefined,
    summary: asString(record.summary) ?? (useFallback ? fallback?.summary : ''),
    evidence: asStringArray(record.evidence) ?? (useFallback ? fallback?.evidence : []),
    difficulty:
      difficulty === 'easy' || difficulty === 'medium' || difficulty === 'hard'
        ? difficulty
        : useFallback
          ? fallback?.difficulty
          : undefined,
    hintCount:
      asNumber(record.hint_count) ??
      asNumber(record.hintCount) ??
      (useFallback ? fallback?.hintCount : undefined),
    explanationDepth:
      explanationDepth === 'rebuild' || explanationDepth === 'grounded' || explanationDepth === 'transfer'
        ? explanationDepth
        : useFallback
          ? fallback?.explanationDepth
          : undefined,
    codeReveal:
      codeReveal === 'full' || codeReveal === 'scaffold' || codeReveal === 'withhold'
        ? codeReveal
        : useFallback
          ? fallback?.codeReveal
          : undefined,
    practiceType:
      practiceType === 'recover' || practiceType === 'focused' || practiceType === 'stretch'
        ? practiceType
        : useFallback
          ? fallback?.practiceType
          : undefined,
    reviewFrequency:
      reviewFrequency === 'sooner' || reviewFrequency === 'normal' || reviewFrequency === 'later'
        ? reviewFrequency
        : useFallback
          ? fallback?.reviewFrequency
          : undefined,
    materialRecommendation:
      materialRecommendation === 'simpler' ||
      materialRecommendation === 'current' ||
      materialRecommendation === 'transfer'
        ? materialRecommendation
        : useFallback
          ? fallback?.materialRecommendation
          : undefined,
    nextPlanStep:
      nextPlanStep === 'shrink' || nextPlanStep === 'hold' || nextPlanStep === 'widen'
        ? nextPlanStep
        : useFallback
          ? fallback?.nextPlanStep
          : undefined,
    shouldRevealCode:
      asBoolean(record.should_reveal_code) ??
      asBoolean(record.shouldRevealCode) ??
      (useFallback ? fallback?.shouldRevealCode : undefined),
    successStreak:
      asNumber(record.success_streak) ??
      asNumber(record.successStreak) ??
      (useFallback ? fallback?.successStreak : undefined),
    failureStreak:
      asNumber(record.failure_streak) ??
      asNumber(record.failureStreak) ??
      (useFallback ? fallback?.failureStreak : undefined),
    pedagogyMode:
      pedagogyMode === 'socratic' || pedagogyMode === 'direct' || pedagogyMode === 'debug_guide'
        ? pedagogyMode
        : useFallback
          ? fallback?.pedagogyMode
          : undefined,
    transferSceneCount:
      asNumber(record.transfer_scene_count) ??
      asNumber(record.transferSceneCount) ??
      (useFallback ? fallback?.transferSceneCount : undefined),
    timeBudget:
      timeBudget === 'tight' || timeBudget === 'normal' || timeBudget === 'ample'
        ? timeBudget
        : useFallback
          ? fallback?.timeBudget
          : undefined,
    projectComplexity:
      projectComplexity === 'simple' ||
      projectComplexity === 'moderate' ||
      projectComplexity === 'complex'
        ? projectComplexity
        : useFallback
          ? fallback?.projectComplexity
          : undefined,
    taskUrgency:
      taskUrgency === 'low' || taskUrgency === 'medium' || taskUrgency === 'high'
        ? taskUrgency
        : useFallback
          ? fallback?.taskUrgency
          : undefined,
    pressureBlocksLiveObjectMint:
      pressureBlocksLiveObjectMint === true
        ? true
        : useFallback
          ? fallback?.pressureBlocksLiveObjectMint
          : undefined,
    streakBlocksLiveObjectMint:
      streakBlocksLiveObjectMint === true
        ? true
        : useFallback
          ? fallback?.streakBlocksLiveObjectMint
          : undefined,
    closedLoopReturnBlocksTaskMint:
      closedLoopReturnBlocksTaskMint === true
        ? true
        : useFallback
          ? fallback?.closedLoopReturnBlocksTaskMint
          : undefined,
  };
}

function mapMemory(
  value: unknown,
  fallback: BootstrapData['memory'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['memory'] {
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const reflections = asStringArray(record.reflections);
  const recentWins =
    asStringArray(record.recent_wins) ??
    (reflections
      ? reflections.slice(0, 3)
      : workspaceChanged
        ? []
        : fallback.recentWins);
  return {
    currentFocus: mapCurrentFocus(
      record.current_focus ?? record.currentFocus ?? record.recent_summary,
      fallback.currentFocus,
      incomingWorkspaceId,
      previousWorkspaceId,
      record,
    ),
    weakSpots: asStringArray(record.weaknesses) ?? fallback.weakSpots,
    recentWins: (recentWins ?? []).slice(0, 3),
    reviewSummary:
      asString(record.review_rhythm) ??
      reflections?.[0] ??
      (workspaceChanged ? '' : fallback.reviewSummary),
    reviewRhythm: asString(record.review_rhythm) ?? (workspaceChanged ? '' : fallback.reviewRhythm),
    dueReviews: mapDueReviews(
      record.due_reviews ?? record.dueReviews,
      incomingWorkspaceId,
      workspaceChanged,
    ),
    teachingObservations:
      asStringArray(record.teaching_observations) ?? (workspaceChanged ? [] : fallback.teachingObservations),
    coachingAdaptation: mapCoachingAdaptation(
      record.coaching_adaptation ?? record.coachingAdaptation,
      fallback.coachingAdaptation,
      incomingWorkspaceId,
      previousWorkspaceId,
    ),
    coachAnchor: asString(record.coach_anchor) ?? fallback.coachAnchor,
    topWeakness: asString(record.top_weakness) ?? fallback.topWeakness,
    lowestMasteryConcepts: asStringArray(record.lowest_mastery_concepts) ?? fallback.lowestMasteryConcepts,
    dueReviewCount:
      asNumber(record.due_review_count) ??
      asNumber(record.dueReviewCount) ??
      (workspaceChanged ? 0 : fallback.dueReviewCount),
    paceSignal: asString(record.pace_signal) ?? fallback.paceSignal,
    activeThread: mapActiveThread(
      record.active_thread,
      fallback.activeThread,
      incomingWorkspaceId,
      previousWorkspaceId,
    ),
    memoryEvidence: asStringArray(record.memory_evidence) ?? fallback.memoryEvidence,
    memoryShareGrants: mapMemoryShareGrants(
      record.memory_share_grants ?? record.memoryShareGrants,
      fallback.memoryShareGrants,
    ),
    evidenceQueue: mapEvidenceQueue(
      record.evidence_queue ?? record.evidenceQueue,
      fallback.evidenceQueue,
      incomingWorkspaceId,
      workspaceChanged,
    ),
    subplans: mapSubplans(record.subplans, fallback.subplans),
    providerDiagnostics:
      asRecordArray(record.provider_diagnostics) ?? asRecordArray(record.providerDiagnostics) ?? fallback.providerDiagnostics,
    selectedResourceDetail: mapResourceDetail(
      record.selected_resource_detail ?? record.selectedResourceDetail,
      workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId)
        ? undefined
        : fallback.selectedResourceDetail,
    ),
    sandboxPreview: mapSandboxPreview(
      scopedTrainingSubmodeValue(
        record.sandbox_preview ?? record.sandboxPreview,
        incomingWorkspaceId,
        !workspaceChanged,
      ),
      workspaceChanged ||
        leftoverFallbackTitleIsNotLiveForBoundPlan(
          fallback.sandboxPreview?.title,
          asRecord(record.workspace),
        )
        ? undefined
        : fallback.sandboxPreview,
    ),
    sandboxState: mapSandboxState(
      scopedTrainingSubmodeValue(
        record.sandbox_state ?? record.sandboxState,
        incomingWorkspaceId,
        !workspaceChanged,
      ),
      workspaceChanged ? undefined : fallback.sandboxState,
    ),
    workspaceUnderstanding: mapWorkspaceUnderstanding(
      scopedTrainingSubmodeValue(
        record.workspace_understanding ?? record.workspaceUnderstanding,
        incomingWorkspaceId,
        !workspaceChanged,
      ),
      workspaceChanged ? undefined : fallback.workspaceUnderstanding,
    ),
    workspace: mapMemoryWorkspace(record.workspace, fallback.workspace),
  };
}

function firstPresentRecordValue(
  record: UnknownRecord | undefined,
  keys: readonly string[],
): unknown {
  if (!record) {
    return undefined;
  }
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(record, key)) {
      return record[key];
    }
  }
  return undefined;
}

function mapGlobalPlan(
  value: unknown,
  fallback: BootstrapData['globalPlan'],
): GlobalPlanView | undefined {
  if (value === null) {
    return undefined;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }
  const stages = Array.isArray(record.stages) ? record.stages : [];
  return {
    id: asString(record.id) ?? fallback?.id ?? '',
    title: asString(record.title) ?? fallback?.title ?? '',
    summary: asString(record.summary) ?? fallback?.summary ?? '',
    goals: asStringArray(record.goals) ?? fallback?.goals ?? [],
    stages: stages.map((stage, index) => mapPlanStage(stage, index)),
    frozen: asBoolean(record.frozen) ?? fallback?.frozen ?? false,
    currentProjectPlanId:
      asString(record.current_project_plan_id) ??
      asString(record.currentProjectPlanId) ??
      fallback?.currentProjectPlanId,
    currentStageId:
      asString(record.current_stage_id) ?? asString(record.currentStageId) ?? fallback?.currentStageId,
    currentStep:
      asString(record.current_step) ?? asString(record.currentStep) ?? fallback?.currentStep,
    whyNow: asString(record.why_now) ?? asString(record.whyNow) ?? fallback?.whyNow,
    verifyMethod:
      asStringArray(record.verify_method) ??
      asStringArray(record.verifyMethod) ??
      fallback?.verifyMethod,
  };
}

function mapGlobalPlanProjectLink(
  value: unknown,
  fallback: BootstrapData['projectPlanLink'],
): GlobalPlanProjectLinkView | undefined {
  if (value === null) {
    return undefined;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }
  return {
    globalPlanId: asString(record.global_plan_id) ?? asString(record.globalPlanId) ?? '',
    workspaceId: asString(record.workspace_id) ?? asString(record.workspaceId) ?? '',
    projectPlanId: asString(record.project_plan_id) ?? asString(record.projectPlanId) ?? '',
    linkedAt: asString(record.linked_at) ?? asString(record.linkedAt) ?? '',
    updatedAt: asString(record.updated_at) ?? asString(record.updatedAt) ?? '',
  };
}

function mapSubplans(
  value: unknown,
  fallback: BootstrapData['memory']['subplans'],
): SubPlanView[] | undefined {
  const records = asRecordArray(value);
  if (!records) {
    return fallback;
  }
  return records.map((record, index) => {
    const rawStatus = asString(record.status);
    const progressPercent = asNumber(record.progress_percent ?? record.progressPercent) ?? 0;
    return {
      id: asString(record.id) ?? `subplan-${index + 1}`,
      parentPlanId:
        asString(record.parent_plan_id) ?? asString(record.parentPlanId) ?? '',
      title: asString(record.title) ?? `Sub-plan ${index + 1}`,
      description: asString(record.description) ?? '',
      stages: Array.isArray(record.stages)
        ? record.stages.map((stage, stageIndex) => mapPlanStage(stage, stageIndex))
        : [],
      status:
        rawStatus === 'active' || rawStatus === 'completed' || rawStatus === 'archived'
          ? rawStatus
          : 'draft',
      progressPercent: Math.max(0, Math.min(100, progressPercent)),
      createdAt: asString(record.created_at) ?? asString(record.createdAt) ?? '',
      updatedAt: asString(record.updated_at) ?? asString(record.updatedAt) ?? '',
    };
  });
}

function mapResourceDetail(
  value: unknown,
  fallback: BootstrapData['memory']['selectedResourceDetail'],
): BootstrapData['memory']['selectedResourceDetail'] {
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const base = mapResource(record);
  const id =
    asText(record.id) ??
    asText(record.resource_id) ??
    asText(record.resourceId) ??
    base?.id ??
    fallback?.id;
  const title =
    asText(record.title) ??
    asText(record.name) ??
    asText(record.resource_title) ??
    asText(record.resourceTitle) ??
    base?.title ??
    fallback?.title;
  if (!id || !title) {
    return fallback;
  }

  return {
    ...(base ?? fallback ?? {}),
    id,
    title,
    kind:
      asResourceKind(asText(record.kind)) ??
      asResourceKind(asText(record.preview_kind)) ??
      asResourceKind(asText(record.previewKind)) ??
      base?.kind ??
      fallback?.kind ??
      'text',
    status:
      asResourceStatus(asText(record.status)) ??
      base?.status ??
      fallback?.status ??
      'ready',
    summary:
      asText(record.summary) ??
      asText(record.match_summary) ??
      asText(record.matchSummary) ??
      base?.summary ??
      fallback?.summary ??
      '',
    source: asText(record.source) ?? asText(record.path) ?? base?.source ?? fallback?.source,
    canonicalSource:
      asText(record.canonical_source) ?? asText(record.canonicalSource) ?? base?.canonicalSource ?? fallback?.canonicalSource,
    sourceType: asText(record.source_type) ?? asText(record.sourceType) ?? base?.sourceType ?? fallback?.sourceType,
    fileType: asText(record.file_type) ?? asText(record.fileType) ?? base?.fileType ?? fallback?.fileType,
    projectScope:
      asText(record.project_scope) ?? asText(record.projectScope) ?? base?.projectScope ?? fallback?.projectScope,
    trustState:
      asText(record.trust_state) ?? asText(record.trustState) ?? base?.trustState ?? fallback?.trustState,
    trustScore: asNumber(record.trust_score) ?? asNumber(record.trustScore) ?? base?.trustScore ?? fallback?.trustScore,
    freshness:
      asText(record.freshness) === 'fresh' || asText(record.freshness) === 'stale' || asText(record.freshness) === 'unknown'
        ? (asText(record.freshness) as ResourceDetailRecordView['freshness'])
        : base?.freshness ?? fallback?.freshness,
    indexState: asText(record.index_state) ?? asText(record.indexState) ?? base?.indexState ?? fallback?.indexState,
    citationId: asText(record.citation_id) ?? asText(record.citationId) ?? base?.citationId ?? fallback?.citationId,
    previewTier: asPreviewTier(asText(record.preview_tier) ?? asText(record.previewTier)) ?? base?.previewTier ?? fallback?.previewTier,
    previewKind: asText(record.preview_kind) ?? asText(record.previewKind) ?? base?.previewKind ?? fallback?.previewKind,
    rankScore: asNumber(record.rank_score) ?? asNumber(record.rankScore) ?? base?.rankScore ?? fallback?.rankScore,
    rankReasons: asStringArray(record.rank_reasons ?? record.rankReasons) ?? base?.rankReasons ?? fallback?.rankReasons,
    matchSummary: asText(record.match_summary) ?? asText(record.matchSummary) ?? base?.matchSummary ?? fallback?.matchSummary,
    canInjectTrainingCard:
      asBoolean(record.can_inject_training_card) ??
      asBoolean(record.canInjectTrainingCard) ??
      base?.canInjectTrainingCard ??
      fallback?.canInjectTrainingCard,
    qualityFlags: asStringArray(record.quality_flags ?? record.qualityFlags) ?? base?.qualityFlags ?? fallback?.qualityFlags,
    sandboxPath: asText(record.sandbox_path) ?? asText(record.sandboxPath) ?? base?.sandboxPath ?? fallback?.sandboxPath,
    sandboxOrigin: asText(record.sandbox_origin) ?? asText(record.sandboxOrigin) ?? base?.sandboxOrigin ?? fallback?.sandboxOrigin,
    sandboxSyncedAt:
      asText(record.sandbox_synced_at) ?? asText(record.sandboxSyncedAt) ?? base?.sandboxSyncedAt ?? fallback?.sandboxSyncedAt,
    sandboxDirty:
      asBoolean(record.sandbox_dirty) ?? asBoolean(record.sandboxDirty) ?? base?.sandboxDirty ?? fallback?.sandboxDirty,
    extractedArtifactPath:
      asText(record.extracted_artifact_path) ??
      asText(record.extractedArtifactPath) ??
      base?.extractedArtifactPath ??
      fallback?.extractedArtifactPath,
    updatedAt: asText(record.updated_at) ?? asText(record.updatedAt) ?? base?.updatedAt ?? fallback?.updatedAt,
    sourceItems: asStringArray(record.source_items ?? record.sourceItems) ?? fallback?.sourceItems,
    tags: asStringArray(record.tags) ?? fallback?.tags,
    warnings: asStringArray(record.warnings) ?? fallback?.warnings,
  };
}

function leftoverFallbackTitleIsNotLiveForBoundPlan(
  leftoverTitle: string | undefined,
  workspace: UnknownRecord | undefined,
): boolean {
  const runtime = asRecord(workspace?.latest_plan_runtime ?? workspace?.latestPlanRuntime);
  const leftover = leftoverTitle?.trim() ?? '';
  if (!runtime || !leftover) {
    return false;
  }
  const liveStep = asText(runtime.current_step) ?? asText(runtime.currentStep) ?? '';
  return leftover !== liveStep;
}

function leftoverLibraryFallbackIsNotLiveForBoundPlan(
  fallback: ResourceRecordView[] | undefined,
  workspace: UnknownRecord | undefined,
): boolean {
  return (fallback ?? []).some((item) => leftoverFallbackTitleIsNotLiveForBoundPlan(item.title, workspace));
}

function mapSandboxPreview(
  value: unknown,
  fallback: BootstrapData['memory']['sandboxPreview'],
): BootstrapData['memory']['sandboxPreview'] {
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const path = asText(record.path) ?? fallback?.path;
  if (!path) {
    return fallback;
  }

  const structuredData = asRecord(record.structured_data) ?? asRecord(record.structuredData);
  const metadata = asRecord(record.metadata) ?? fallback?.metadata;

  return {
    path,
    relativePath: asText(record.relative_path) ?? asText(record.relativePath) ?? fallback?.relativePath,
    title: asText(record.title) ?? fallback?.title,
    fileKind: asText(record.file_kind) ?? asText(record.fileKind) ?? fallback?.fileKind,
    previewTier: asText(record.preview_tier) ?? asText(record.previewTier) ?? fallback?.previewTier,
    previewKind: asText(record.preview_kind) ?? asText(record.previewKind) ?? fallback?.previewKind,
    languageHint: asText(record.language_hint) ?? asText(record.languageHint) ?? fallback?.languageHint,
    renderedFrom: asText(record.rendered_from) ?? asText(record.renderedFrom) ?? fallback?.renderedFrom,
    content: asText(record.content) ?? fallback?.content,
    excerpt: asText(record.excerpt) ?? fallback?.excerpt,
    html: asText(record.html) ?? fallback?.html,
    isBinary: asBoolean(record.is_binary) ?? asBoolean(record.isBinary) ?? fallback?.isBinary,
    isEditable: asBoolean(record.is_editable) ?? asBoolean(record.isEditable) ?? fallback?.isEditable,
    canNativeOpen: asBoolean(record.can_native_open) ?? asBoolean(record.canNativeOpen) ?? fallback?.canNativeOpen,
    structuredData: structuredData ?? fallback?.structuredData,
    metadata,
    assetUri: asText(record.asset_uri) ?? asText(record.assetUri) ?? fallback?.assetUri,
  };
}

function mapWorkspaceAuthority(
  value: unknown,
  fallback: SandboxAuthorityView,
): SandboxAuthorityView {
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const activeWorkspaceRoot =
    asText(record.activeWorkspaceRoot) ?? asText(record.active_workspace_root) ?? fallback?.activeWorkspaceRoot;
  const rootUri = asText(record.rootUri) ?? asText(record.root_uri) ?? fallback?.rootUri;
  const authoritySource =
    asText(record.authoritySource) ?? asText(record.authority_source) ?? fallback?.authoritySource;
  const remoteName = asText(record.remoteName) ?? asText(record.remote_name) ?? fallback?.remoteName;
  const authorityMode = asText(record.authorityMode) ?? asText(record.authority_mode) ?? fallback?.authorityMode;
  const permissionLevel =
    asText(record.permissionLevel) ?? asText(record.permission_level) ?? fallback?.permissionLevel;
  const permissionLabel =
    asText(record.permissionLabel) ?? asText(record.permission_label) ?? fallback?.permissionLabel;
  const allowedOperations =
    asStringArray(record.allowedOperations ?? record.allowed_operations) ?? fallback?.allowedOperations;
  const mountedSources =
    asStringArray(record.mountedSources ?? record.mounted_sources) ?? fallback?.mountedSources;
  const ledgerEntryCount =
    asNumber(record.ledgerEntryCount) ?? asNumber(record.ledger_entry_count) ?? fallback?.ledgerEntryCount;
  const checkpointCount =
    asNumber(record.checkpointCount) ?? asNumber(record.checkpoint_count) ?? fallback?.checkpointCount;
  const trashRoot = asText(record.trashRoot) ?? asText(record.trash_root) ?? fallback?.trashRoot;
  const nextSafeAction =
    asText(record.nextSafeAction) ??
    asText(record.next_safe_action) ??
    fallback?.nextSafeAction ??
    describeWorkspaceAuthoritySummary(
      {
        activeWorkspaceRoot,
        rootUri,
        authoritySource,
        remoteName,
        authorityMode,
        permissionLevel,
        permissionLabel,
        allowedOperations,
        mountedSources,
        ledgerEntryCount,
        checkpointCount,
        trashRoot,
      },
      'en-US',
    ).nextSafeAction;

  return {
    activeWorkspaceRoot,
    rootUri,
    authoritySource,
    remoteName,
    authorityMode,
    permissionLevel,
    permissionLabel,
    allowedOperations,
    mountedSources,
    ledgerEntryCount,
    checkpointCount,
    trashRoot,
    nextSafeAction,
  };
}

function mapMemoryShareGrants(
  value: unknown,
  fallback: NonNullable<BootstrapData['memory']['memoryShareGrants']> | undefined,
): NonNullable<BootstrapData['memory']['memoryShareGrants']> {
  const records = asRecordArray(value);
  if (!records) {
    return fallback ?? [];
  }

  return records.flatMap((record) => {
    const sourceWorkspaceId = asString(record.source_workspace_id ?? record.sourceWorkspaceId);
    const targetWorkspaceId = asString(record.target_workspace_id ?? record.targetWorkspaceId);
    const categories = (asStringArray(record.categories ?? record.capabilities) ?? []).filter(
      (category): category is 'preferences' | 'mastery' =>
        category === 'preferences' || category === 'mastery',
    );
    if (!sourceWorkspaceId || !targetWorkspaceId || categories.length === 0) {
      return [];
    }
    return [{
      sourceWorkspaceId,
      targetWorkspaceId,
      categories,
      createdAt: asString(record.created_at ?? record.createdAt),
      updatedAt: asString(record.updated_at ?? record.updatedAt),
    }];
  });
}

function mapEvidenceQueue(
  value: unknown,
  fallback: BootstrapData['memory']['evidenceQueue'],
  incomingWorkspaceId?: string,
  workspaceChanged?: boolean,
): BootstrapData['memory']['evidenceQueue'] {
  const chromeFallback = workspaceChanged ? undefined : fallback;
  const record = asRecord(value);
  if (!record) {
    return chromeFallback ?? emptyLiveEvidenceQueue();
  }
  const pending = mapEvidenceItems(
    record.pending,
    chromeFallback?.pending,
    incomingWorkspaceId,
    workspaceChanged,
  );
  const deferred = mapEvidenceItems(
    record.deferred,
    chromeFallback?.deferred,
    incomingWorkspaceId,
    workspaceChanged,
  );
  const adopted = mapEvidenceItems(
    record.adopted,
    chromeFallback?.adopted,
    incomingWorkspaceId,
    workspaceChanged,
  );
  const rejected = mapEvidenceItems(
    record.rejected,
    chromeFallback?.rejected,
    incomingWorkspaceId,
    workspaceChanged,
  );
  const history = mapEvidenceItems(
    record.history,
    chromeFallback?.history,
    incomingWorkspaceId,
    workspaceChanged,
  );
  return {
    pending,
    deferred,
    adopted,
    rejected,
    history,
    totalCount:
      asNumber(record.total_count) ??
      asNumber(record.totalCount) ??
      pending.length + deferred.length + adopted.length + rejected.length + history.length,
  };
}

function mapEvidenceItems(
  value: unknown,
  fallback: EvidenceItemView[] | undefined,
  incomingWorkspaceId?: string,
  workspaceChanged?: boolean,
): EvidenceItemView[] {
  if (!Array.isArray(value)) {
    return fallback ?? [];
  }
  return value.reduce<EvidenceItemView[]>((items, entry) => {
    const record = asRecord(entry);
    const id = asString(record?.id);
    const summary = asString(record?.summary);
    if (!id || !summary) {
      return items;
    }
    if (incomingWorkspaceId) {
      const stamp = asString(record?.workspace_id) ?? asString(record?.workspaceId);
      if (workspaceChanged) {
        if (stamp && !isCurrentForWorkspace({ workspaceId: stamp }, incomingWorkspaceId)) {
          return items;
        }
      } else if (!trainingRecordMatchesWorkspace(record, incomingWorkspaceId)) {
        return items;
      }
    }
    items.push({
      id,
      workspaceId: asString(record?.workspace_id) ?? asString(record?.workspaceId) ?? undefined,
      summary,
      source: asString(record?.source) ?? "card_result",
      sourceCardId: asString(record?.source_card_id) ?? asString(record?.sourceCardId) ?? undefined,
      concepts: asStringArray(record?.concepts) ?? [],
      outcome: asString(record?.outcome) ?? "partial",
      confidence: asNumber(record?.confidence) ?? 0,
      verified: asBoolean(record?.verified) ?? undefined,
      verificationSource:
        asString(record?.verification_source) ?? asString(record?.verificationSource) ?? undefined,
      timestamp: asString(record?.timestamp) ?? undefined,
      targetPlanStageId:
        asString(record?.target_plan_stage_id) ?? asString(record?.targetPlanStageId) ?? undefined,
      adopted: asBoolean(record?.adopted) ?? undefined,
      adoptedAt: asString(record?.adopted_at) ?? asString(record?.adoptedAt) ?? null,
      deferredAt: asString(record?.deferred_at) ?? asString(record?.deferredAt) ?? null,
      deferralReason:
        asString(record?.deferral_reason) ?? asString(record?.deferralReason) ?? undefined,
      rejectedAt: asString(record?.rejected_at) ?? asString(record?.rejectedAt) ?? null,
      rejectionReason:
        asString(record?.rejection_reason) ?? asString(record?.rejectionReason) ?? undefined,
    });
    return items;
  }, []);
}

function mapSandboxState(
  value: unknown,
  fallback: BootstrapData['memory']['sandboxState'],
): BootstrapData['memory']['sandboxState'] {
  const record = asRecord(value);
  if (!record) {
    return fallback
      ? {
          ...fallback,
          authority: fallback.authority ? mapWorkspaceAuthority(fallback.authority, fallback.authority) : fallback.authority,
        }
      : fallback;
  }

  return {
    rootPath: asText(record.rootPath) ?? asText(record.root_path) ?? fallback?.rootPath,
    sandboxRootPath:
      asText(record.sandboxRootPath) ?? asText(record.sandbox_root_path) ?? fallback?.sandboxRootPath,
    workspaceRootPath:
      asText(record.workspaceRootPath) ?? asText(record.workspace_root_path) ?? fallback?.workspaceRootPath,
    activeWorkspaceRoot:
      asText(record.activeWorkspaceRoot) ?? asText(record.active_workspace_root) ?? fallback?.activeWorkspaceRoot,
    trashRootPath: asText(record.trashRootPath) ?? asText(record.trash_root_path) ?? fallback?.trashRootPath,
    managedRoots:
      asStringArray(record.managedRoots ?? record.managed_roots) ?? fallback?.managedRoots,
    ready: asBoolean(record.ready) ?? fallback?.ready,
    linkedResourceCount:
      asNumber(record.linkedResourceCount) ?? asNumber(record.linked_resource_count) ?? fallback?.linkedResourceCount,
    totalFiles: asNumber(record.totalFiles) ?? asNumber(record.total_files) ?? fallback?.totalFiles,
    totalDirectories:
      asNumber(record.totalDirectories) ?? asNumber(record.total_directories) ?? fallback?.totalDirectories,
    totalSizeBytes:
      asNumber(record.totalSizeBytes) ?? asNumber(record.total_size_bytes) ?? fallback?.totalSizeBytes,
    lastUpdatedAt:
      asText(record.lastUpdatedAt) ?? asText(record.last_updated_at) ?? fallback?.lastUpdatedAt,
    selectedPath: asText(record.selectedPath) ?? asText(record.selected_path) ?? fallback?.selectedPath,
    nodes: Array.isArray(record.nodes)
      ? record.nodes.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
      : fallback?.nodes,
    notes: asStringArray(record.notes) ?? fallback?.notes,
    preview: mapSandboxPreview(record.preview ?? record.previewData, fallback?.preview),
    recentCommands: asRecordArray(record.recentCommands ?? record.recent_commands) ?? fallback?.recentCommands,
    latestCommand: asRecord(record.latestCommand ?? record.latest_command) ?? fallback?.latestCommand ?? null,
    authority: mapWorkspaceAuthority(record.authority, fallback?.authority),
    capabilitySummary:
      asRecord(record.capabilitySummary) ?? asRecord(record.capability_summary) ?? fallback?.capabilitySummary,
    threatSummary:
      asRecord(record.threatSummary) ?? asRecord(record.threat_summary) ?? fallback?.threatSummary,
  };
}

function mapActiveThread(
  value: unknown,
  fallback: BootstrapData['memory']['activeThread'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['memory']['activeThread'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const record = asRecord(value);
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? undefined : fallback;
  }
  const useFallback = !workspaceChanged;
  return {
    scenario: asString(record.scenario) ?? (useFallback ? fallback?.scenario : undefined),
    focusArea: asString(record.focus_area) ?? (useFallback ? fallback?.focusArea : undefined),
    summary: asString(record.summary) ?? (useFallback ? fallback?.summary : undefined),
    nextStep: asString(record.next_step) ?? (useFallback ? fallback?.nextStep : undefined),
    blocker: asString(record.blocker) ?? (useFallback ? fallback?.blocker : undefined),
    verifiedResult: asString(record.verified_result) ?? (useFallback ? fallback?.verifiedResult : undefined),
    decision: asString(record.decision) ?? (useFallback ? fallback?.decision : undefined),
    teachingNote: asString(record.teaching_note) ?? (useFallback ? fallback?.teachingNote : undefined),
    confidence: asString(record.confidence) ?? (useFallback ? fallback?.confidence : undefined),
    evidence: asStringArray(record.evidence) ?? (useFallback ? fallback?.evidence : undefined),
    updatedAt: asString(record.updated_at) ?? (useFallback ? fallback?.updatedAt : undefined),
  };
}

function mapFirstLookSummary(
  value: unknown,
  fallback: FirstLookSummaryView | undefined,
): FirstLookSummaryView | undefined {
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const folderRole = toFirstLookFolderRole(asString(record.folder_role));
  const projectTypeGuess = toProjectTypeGuess(asString(record.project_type_guess));
  const confidence = asNumber(record.confidence);
  const whyThisGuess = asString(record.why_this_guess) ?? asString(record.whyThisGuess) ?? "";
  const entryPoints = asStringArray(record.entry_points) ?? asStringArray(record.entryPoints) ?? [];
  const directoryAnchors =
    asStringArray(record.directory_anchors) ?? asStringArray(record.directoryAnchors) ?? [];
  const coreModulesOrMaterials =
    asStringArray(record.core_modules_or_materials) ?? asStringArray(record.coreModulesOrMaterials) ?? [];
  const riskZones = asStringArray(record.risk_zones) ?? asStringArray(record.riskZones) ?? [];
  const trainingOpportunities =
    asStringArray(record.training_opportunities) ?? asStringArray(record.trainingOpportunities) ?? [];
  const unknowns = asStringArray(record.unknowns) ?? [];
  const recommendedNextStep =
    asString(record.recommended_next_step) ?? asString(record.recommendedNextStep) ?? "";
  const classificationMethod = asString(record.classification_method) ?? asString(record.classificationMethod);
  const classifiedAt = asString(record.classified_at) ?? asString(record.classifiedAt) ?? "";

  if (
    !folderRole &&
    !projectTypeGuess &&
    confidence === undefined &&
    !whyThisGuess &&
    entryPoints.length === 0 &&
    directoryAnchors.length === 0 &&
    coreModulesOrMaterials.length === 0 &&
    riskZones.length === 0 &&
    trainingOpportunities.length === 0 &&
    unknowns.length === 0 &&
    !recommendedNextStep &&
    !classificationMethod &&
    !classifiedAt
  ) {
    return fallback;
  }

  return {
    folderRole: folderRole ?? fallback?.folderRole ?? 'mixed_uncertain',
    projectTypeGuess: projectTypeGuess ?? fallback?.projectTypeGuess ?? 'unknown',
    confidence: confidence ?? fallback?.confidence ?? 0,
    whyThisGuess: whyThisGuess || fallback?.whyThisGuess || '',
    entryPoints: entryPoints.length > 0 ? entryPoints : fallback?.entryPoints ?? [],
    directoryAnchors: directoryAnchors.length > 0 ? directoryAnchors : fallback?.directoryAnchors ?? [],
    coreModulesOrMaterials:
      coreModulesOrMaterials.length > 0 ? coreModulesOrMaterials : fallback?.coreModulesOrMaterials ?? [],
    riskZones: riskZones.length > 0 ? riskZones : fallback?.riskZones ?? [],
    trainingOpportunities:
      trainingOpportunities.length > 0 ? trainingOpportunities : fallback?.trainingOpportunities ?? [],
    unknowns: unknowns.length > 0 ? unknowns : fallback?.unknowns ?? [],
    recommendedNextStep: recommendedNextStep || fallback?.recommendedNextStep || '',
    classificationMethod:
      classificationMethod === 'llm_enhanced' ? 'llm_enhanced' : 'heuristic',
    classifiedAt: classifiedAt || fallback?.classifiedAt || new Date().toISOString(),
  };
}

function mapWorkspaceUnderstanding(
  value: unknown,
  fallback: BootstrapData['memory']['workspaceUnderstanding'],
): BootstrapData['memory']['workspaceUnderstanding'] {
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const firstLookSummary = mapFirstLookSummary(
    record.first_look_summary ?? record.firstLookSummary,
    fallback?.firstLookSummary,
  );
  const repoSummary = asString(record.repo_summary) ?? asString(record.repoSummary) ?? '';
  const entryPoints = asStringArray(record.entry_points) ?? asStringArray(record.entryPoints) ?? [];
  const featureLanes = asStringArray(record.feature_lanes) ?? asStringArray(record.featureLanes) ?? [];
  const riskZones = asStringArray(record.risk_zones) ?? asStringArray(record.riskZones) ?? [];
  const trainingOpportunities =
    asStringArray(record.training_opportunities) ?? asStringArray(record.trainingOpportunities) ?? [];
  const resourceBrief = asString(record.resource_brief) ?? asString(record.resourceBrief) ?? '';

  if (
    !repoSummary &&
    entryPoints.length === 0 &&
    featureLanes.length === 0 &&
    riskZones.length === 0 &&
    trainingOpportunities.length === 0 &&
    !resourceBrief &&
    !firstLookSummary
  ) {
    return fallback;
  }

  return {
    repoSummary: repoSummary || fallback?.repoSummary || '',
    entryPoints: entryPoints.length > 0 ? entryPoints : fallback?.entryPoints ?? [],
    featureLanes: featureLanes.length > 0 ? featureLanes : fallback?.featureLanes ?? [],
    riskZones: riskZones.length > 0 ? riskZones : fallback?.riskZones ?? [],
    trainingOpportunities:
      trainingOpportunities.length > 0 ? trainingOpportunities : fallback?.trainingOpportunities ?? [],
    resourceBrief: resourceBrief || fallback?.resourceBrief || '',
    firstLookSummary,
    updatedAt: asString(record.updated_at) ?? asString(record.updatedAt) ?? fallback?.updatedAt ?? new Date().toISOString(),
  };
}

function mapMemoryWorkspace(
  value: unknown,
  fallback: BootstrapData['memory']['workspace'],
): BootstrapData['memory']['workspace'] {
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }
  const coachDefaults = asRecord(record.coach_defaults ?? record.coachDefaults);
  const toggles = asRecord(
    coachDefaults?.workspace_memory_toggles ??
      coachDefaults?.workspaceMemoryToggles ??
      record.workspace_memory_toggles ??
      record.workspaceMemoryToggles,
  );
  const incomingAnswerMode = asString(record.answer_mode) ?? asString(record.answerMode);
  const answerMode = incomingAnswerMode ? toAnswerPolicy(incomingAnswerMode) : undefined;
  const responseLanguage = toComposerLanguage(
    asString(record.response_language) ?? asString(record.responseLanguage),
  );
  const incomingWorkspaceId = asString(record.workspace_id) ?? asString(record.workspaceId);
  // A managed admission contextId is this host's runtime workspace identity (see
  // getRuntimeWorkspaceContext); honour it when workspaceId was never stamped yet.
  const fallbackWorkspaceId =
    fallback?.workspaceId ??
    (fallback?.trainerWorkspace?.status === 'managed'
      ? fallback.trainerWorkspace.contextId
      : undefined);
  const sameWorkspace =
    Boolean(incomingWorkspaceId) &&
    Boolean(fallbackWorkspaceId) &&
    incomingWorkspaceId === fallbackWorkspaceId;
  const latestPlanRuntime = incomingWorkspaceId
    ? selectPlanRuntimeForScope(record.latest_plan_runtime ?? record.latestPlanRuntime, {
        workspaceId: incomingWorkspaceId,
      })
    : normalizePlanRuntimeRecovery(record.latest_plan_runtime ?? record.latestPlanRuntime);
  const latestProviderCapability = normalizeProviderCapabilityRecovery(
    record.latest_provider_capability ?? record.latestProviderCapability,
  );
  const latestStreamingCheckpoint = recoverStreamingCheckpointAfterRestart(
    record.latest_streaming_checkpoint ?? record.latestStreamingCheckpoint,
  );

  return {
    workspaceId: incomingWorkspaceId ?? (sameWorkspace ? fallbackWorkspaceId : undefined),
    responseLanguage: responseLanguage ?? (sameWorkspace ? fallback?.responseLanguage : undefined),
    answerMode: answerMode ?? (sameWorkspace ? fallback?.answerMode : undefined),
    resourceSearchMode:
      record.resource_search_mode || record.resourceSearchMode
        ? normalizeResourceSearchMode(
            record.resource_search_mode ?? record.resourceSearchMode,
            sameWorkspace ? fallback?.resourceSearchMode ?? 'lexical' : 'lexical',
          )
        : sameWorkspace
          ? fallback?.resourceSearchMode
          : undefined,
    followCurrentFile:
      asBoolean(record.follow_current_file) ??
      asBoolean(record.followCurrentFile) ??
      (sameWorkspace ? fallback?.followCurrentFile : undefined),
    contextDetail:
      toContextDetail(asString(record.context_detail) ?? asString(record.contextDetail)) ??
      (sameWorkspace ? fallback?.contextDetail : undefined),
    includeCurrentFile:
      asBoolean(record.include_current_file) ??
      asBoolean(record.includeCurrentFile) ??
      (sameWorkspace ? fallback?.includeCurrentFile : undefined),
    includeSelection:
      asBoolean(record.include_selection) ??
      asBoolean(record.includeSelection) ??
      (sameWorkspace ? fallback?.includeSelection : undefined),
    includeDiagnostics:
      asBoolean(record.include_diagnostics) ??
      asBoolean(record.includeDiagnostics) ??
      (sameWorkspace ? fallback?.includeDiagnostics : undefined),
    includeRelatedFiles:
      asBoolean(record.include_related_files) ??
      asBoolean(record.includeRelatedFiles) ??
      (sameWorkspace ? fallback?.includeRelatedFiles : undefined),
    learnerName:
      asString(record.learner_name) ??
      asString(record.learnerName) ??
      (sameWorkspace ? fallback?.learnerName : undefined),
    projectContext:
      asString(record.project_context) ??
      asString(record.projectContext) ??
      (sameWorkspace ? fallback?.projectContext : undefined),
    preferredRhythm:
      asString(record.preferred_rhythm) ??
      asString(record.preferredRhythm) ??
      (sameWorkspace ? fallback?.preferredRhythm : undefined),
    preferredLearningMode:
      asString(record.preferred_learning_mode) ??
      asString(record.preferredLearningMode) ??
      (sameWorkspace ? fallback?.preferredLearningMode : undefined),
    onboardingRequest:
      asString(record.onboarding_request) ??
      asString(record.onboardingRequest) ??
      (sameWorkspace ? fallback?.onboardingRequest : undefined),
    latestLearningFocusArea:
      asString(record.latest_learning_focus_area) ??
      asString(record.latestLearningFocusArea) ??
      (sameWorkspace ? fallback?.latestLearningFocusArea : undefined),
    latestTransferState:
      scopedLatestTransferState(
        record.latest_transfer_state ?? record.latestTransferState,
        incomingWorkspaceId,
        sameWorkspace,
      ) ?? (sameWorkspace ? fallback?.latestTransferState : undefined),
    latestPlanRuntime: latestPlanRuntime ?? (sameWorkspace ? fallback?.latestPlanRuntime : undefined),
    latestProviderCapability:
      latestProviderCapability ?? (sameWorkspace ? fallback?.latestProviderCapability : undefined),
    latestStreamingCheckpoint:
      latestStreamingCheckpoint ?? (sameWorkspace ? fallback?.latestStreamingCheckpoint : undefined),
    trainerWorkspace: mapTrainerWorkspaceAdmission(
      scopedTrainingSubmodeValue(
        record.trainer_workspace ?? record.trainerWorkspace,
        incomingWorkspaceId,
        sameWorkspace,
      ),
      sameWorkspace ? fallback?.trainerWorkspace : undefined,
    ),
    resourceSandbox: (() => {
      const scopedSandbox = asRecord(
        scopedTrainingSubmodeValue(
          record.resource_sandbox ?? record.resourceSandbox,
          incomingWorkspaceId,
          sameWorkspace,
        ),
      );
      const chromeSandbox = sameWorkspace ? fallback?.resourceSandbox : undefined;
      if (
        scopedSandbox &&
        asText(scopedSandbox.effective_path ?? scopedSandbox.effectivePath) &&
        asText(scopedSandbox.default_path ?? scopedSandbox.defaultPath)
      ) {
        return {
          configuredPath:
            asText(scopedSandbox.configured_path ?? scopedSandbox.configuredPath) ??
            chromeSandbox?.configuredPath,
          effectivePath:
            asText(scopedSandbox.effective_path ?? scopedSandbox.effectivePath) ??
            chromeSandbox?.effectivePath ??
            '',
          defaultPath:
            asText(scopedSandbox.default_path ?? scopedSandbox.defaultPath) ??
            chromeSandbox?.defaultPath ??
            '',
          source: asText(scopedSandbox.source) === 'custom' ? 'custom' : 'recommended',
          status: 'ready',
        };
      }
      return chromeSandbox;
    })(),
    coachDefaults: (() => {
      const chromeDefaults = sameWorkspace ? fallback?.coachDefaults : undefined;
      const incomingMemoryScope =
        asString(coachDefaults?.memory_scope ?? coachDefaults?.memoryScope ?? record.memory_scope ?? record.memoryScope);
      const incomingWorkingSetMode =
        asString(
          coachDefaults?.working_set_mode ??
            coachDefaults?.workingSetMode ??
            record.working_set_mode ??
            record.workingSetMode,
        );
      const incomingReviewCadence =
        asString(
          coachDefaults?.review_cadence ??
            coachDefaults?.reviewCadence ??
            record.review_cadence ??
            record.reviewCadence,
        );
      const incomingReviewReminderMode =
        asString(
          coachDefaults?.review_reminder_mode ??
            coachDefaults?.reviewReminderMode ??
            record.review_reminder_mode ??
            record.reviewReminderMode,
        );
      if (
        !coachDefaults &&
        !incomingMemoryScope &&
        !incomingWorkingSetMode &&
        !incomingReviewCadence &&
        !incomingReviewReminderMode
      ) {
        return chromeDefaults;
      }
      return {
        memoryScope: toMemoryScope(incomingMemoryScope) ?? chromeDefaults?.memoryScope,
        workingSetMode: toWorkingSetMode(incomingWorkingSetMode) ?? chromeDefaults?.workingSetMode,
        reviewCadence: toReviewCadence(incomingReviewCadence) ?? chromeDefaults?.reviewCadence,
        reviewReminderMode:
          toReviewReminderMode(incomingReviewReminderMode) ?? chromeDefaults?.reviewReminderMode,
        workspaceMemoryToggles: toggles
          ? {
              decisions:
                asBoolean(toggles.decisions) ?? chromeDefaults?.workspaceMemoryToggles?.decisions,
              patterns:
                asBoolean(toggles.patterns) ?? chromeDefaults?.workspaceMemoryToggles?.patterns,
              resources:
                asBoolean(toggles.resources) ?? chromeDefaults?.workspaceMemoryToggles?.resources,
            }
          : chromeDefaults?.workspaceMemoryToggles,
      };
    })(),
  };
}

function scopedTrainingSubmodeValue(
  value: unknown,
  incomingWorkspaceId: string | undefined,
  sameWorkspace: boolean,
): unknown {
  if (value === undefined || value === null) {
    return value;
  }
  if (Array.isArray(value)) {
    if (!incomingWorkspaceId) {
      return value;
    }
    return value.filter((item) => {
      const record = asRecord(item);
      if (!record) {
        return false;
      }
      if (!sameWorkspace) {
        const stamp = asString(record.workspace_id) ?? asString(record.workspaceId);
        if (!stamp) {
          return Boolean(
            asString(record.title) ||
              asString(record.card_id) ||
              asString(record.cardId) ||
              asString(record.event_id) ||
              asString(record.eventId) ||
              asString(record.selected_card_id) ||
              asString(record.selectedCardId) ||
              asString(record.selected_card_title) ||
              asString(record.selectedCardTitle) ||
              asString(record.why_this_card) ||
              asString(record.whyThisCard) ||
              asString(record.card_candidate_id) ||
              asString(record.cardCandidateId),
          );
        }
        return isCurrentForWorkspace({ workspaceId: stamp }, incomingWorkspaceId);
      }
      return trainingRecordMatchesWorkspace(record, incomingWorkspaceId);
    });
  }
  const record = asRecord(value);
  if (!record || !incomingWorkspaceId) {
    return value;
  }
  if (!sameWorkspace) {
    const stamp = asString(record.workspace_id) ?? asString(record.workspaceId);
    if (!stamp) {
      return value;
    }
    return isCurrentForWorkspace({ workspaceId: stamp }, incomingWorkspaceId) ? value : undefined;
  }
  return trainingRecordMatchesWorkspace(record, incomingWorkspaceId) ? value : undefined;
}

function scopedLatestTransferState(
  value: unknown,
  incomingWorkspaceId: string | undefined,
  sameWorkspace: boolean,
): ReturnType<typeof normalizeTransferSkillStateRecord> {
  const incoming = normalizeTransferSkillStateRecord(value);
  if (!incoming) {
    return undefined;
  }
  if (incoming.workspaceIds.length === 0 && incoming.state === 'transferable') {
    return undefined;
  }
  if (!incomingWorkspaceId) {
    return sameWorkspace ? incoming : undefined;
  }
  if (sameWorkspace) {
    return incoming;
  }
  if (incoming.workspaceIds.length === 0) {
    return undefined;
  }
  return incoming.workspaceIds.includes(incomingWorkspaceId) ? incoming : undefined;
}

function mapWorkspaceTrainingState(
  value: unknown,
  fallback: BootstrapData['workspaceTrainingState'],
): BootstrapData['workspaceTrainingState'] {
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const workspaceRecord = asRecord(record.workspace);
  const incomingWorkspaceId =
    asString(workspaceRecord?.workspace_id) ?? asString(workspaceRecord?.workspaceId);
  const fallbackWorkspaceId = fallback?.workspaceId;
  const sameWorkspace =
    Boolean(incomingWorkspaceId) &&
    Boolean(fallbackWorkspaceId) &&
    incomingWorkspaceId === fallbackWorkspaceId;
  const chromeFallback = sameWorkspace ? fallback : undefined;
  const rawHandoff = workspaceRecord?.latest_training_handoff ?? workspaceRecord?.latestTrainingHandoff;
  const rawNextHop = workspaceRecord?.latest_training_next_hop ?? workspaceRecord?.latestTrainingNextHop;
  const scopedHandoff =
    !incomingWorkspaceId || trainingRecordMatchesWorkspace(rawHandoff, incomingWorkspaceId ?? "")
      ? rawHandoff
      : undefined;
  const scopedNextHop =
    !incomingWorkspaceId || trainingRecordMatchesWorkspace(rawNextHop, incomingWorkspaceId ?? "")
      ? rawNextHop
      : undefined;
  const incomingTitle =
    asString(workspaceRecord?.selected_card_title) ?? asString(workspaceRecord?.selectedCardTitle);
  const chromeSource =
    workspaceRecord?.latest_training_chrome ??
    workspaceRecord?.latestTrainingChrome ?? {
      workspaceId:
        asString(asRecord(scopedHandoff)?.workspace_id) ??
        asString(asRecord(scopedHandoff)?.workspaceId) ??
        asString(asRecord(scopedNextHop)?.workspace_id) ??
        asString(asRecord(scopedNextHop)?.workspaceId),
      selectedCardTitle: incomingTitle,
    };
  const scopedChrome = incomingWorkspaceId
    ? selectTrainingChromeForScope(chromeSource, { workspaceId: incomingWorkspaceId })
    : undefined;
  const titleMismatched =
    Boolean(incomingWorkspaceId) &&
    !trainingRecordMatchesWorkspace(chromeSource, incomingWorkspaceId ?? "");
  const mapped: WorkspaceTrainingStateView = {
    workspaceId: incomingWorkspaceId ?? (sameWorkspace ? fallbackWorkspaceId : undefined),
    latestConversationHandoff: mapTrainingHandoff(
      workspaceRecord?.latest_conversation_handoff ?? workspaceRecord?.latestConversationHandoff,
      chromeFallback?.latestConversationHandoff,
    ),
    latestTrainingHandoff: mapTrainingHandoff(
      scopedHandoff,
      chromeFallback?.latestTrainingHandoff,
    ),
    latestTrainingReliability: mapTrainingReliability(
      scopedTrainingSubmodeValue(
        workspaceRecord?.latest_training_reliability ?? workspaceRecord?.latestTrainingReliability,
        incomingWorkspaceId,
        sameWorkspace,
      ),
      chromeFallback?.latestTrainingReliability,
    ),
    latestTransferState:
      scopedLatestTransferState(
        workspaceRecord?.latest_transfer_state ?? workspaceRecord?.latestTransferState,
        incomingWorkspaceId,
        sameWorkspace,
      ) ?? chromeFallback?.latestTransferState,
    latestTrainingNextHop: mapTrainingNextHop(
      scopedNextHop,
      chromeFallback?.latestTrainingNextHop,
    ),
    latestTrainingSubmode:
      asString(workspaceRecord?.latest_training_submode) ??
      asString(workspaceRecord?.latestTrainingSubmode) ??
      chromeFallback?.latestTrainingSubmode,
    latestLearningFocusArea:
      asString(workspaceRecord?.latest_learning_focus_area) ??
      asString(workspaceRecord?.latestLearningFocusArea) ??
      chromeFallback?.latestLearningFocusArea,
    latestLearningFollowup:
      asString(workspaceRecord?.latest_learning_followup) ??
      asString(workspaceRecord?.latestLearningFollowup) ??
      chromeFallback?.latestLearningFollowup,
    latestLearningVerifiedResult:
      asString(workspaceRecord?.latest_learning_verified_result) ??
      asString(workspaceRecord?.latestLearningVerifiedResult) ??
      chromeFallback?.latestLearningVerifiedResult,
    latestLearningBlocker:
      asString(workspaceRecord?.latest_learning_blocker) ??
      asString(workspaceRecord?.latestLearningBlocker) ??
      chromeFallback?.latestLearningBlocker,
    latestLearningAbandonReason:
      asString(workspaceRecord?.latest_learning_abandon_reason) ??
      asString(workspaceRecord?.latestLearningAbandonReason) ??
      chromeFallback?.latestLearningAbandonReason,
    latestLearningPartialProgress:
      asString(workspaceRecord?.latest_learning_partial_progress) ??
      asString(workspaceRecord?.latestLearningPartialProgress) ??
      chromeFallback?.latestLearningPartialProgress,
    selectedCardId:
      asString(workspaceRecord?.selected_card_id) ??
      asString(workspaceRecord?.selectedCardId) ??
      chromeFallback?.selectedCardId,
    selectedCardType:
      toTrainingCardType(asString(workspaceRecord?.selected_card_type) ?? asString(workspaceRecord?.selectedCardType)) ??
      chromeFallback?.selectedCardType,
    selectedCardTitle: titleMismatched
      ? undefined
      : (scopedChrome?.selectedCardTitle ??
        incomingTitle ??
        (sameWorkspace ? fallback?.selectedCardTitle : undefined)),
    selectedCardStatus:
      asString(workspaceRecord?.selected_card_status) ??
      asString(workspaceRecord?.selectedCardStatus) ??
      chromeFallback?.selectedCardStatus,
    trainingCardCandidates: mapTrainingCardCandidates(
      scopedTrainingSubmodeValue(
        record.training_card_candidates ?? record.trainingCardCandidates,
        incomingWorkspaceId,
        sameWorkspace,
      ),
      chromeFallback?.trainingCardCandidates,
    ),
    activeTrainingCardRouting: mapActiveTrainingCardRouting(
      scopedTrainingSubmodeValue(
        record.active_training_card_routing ?? record.activeTrainingCardRouting,
        incomingWorkspaceId,
        sameWorkspace,
      ),
      chromeFallback?.activeTrainingCardRouting,
    ),
    trainingEventLedger: mapTrainingEventLedger(
      scopedTrainingSubmodeValue(
        record.training_event_ledger ?? record.trainingEventLedger,
        incomingWorkspaceId,
        sameWorkspace,
      ),
      chromeFallback?.trainingEventLedger,
    ),
    reviewArtifact: mapReviewArtifact(
      scopedTrainingSubmodeValue(
        record.review_artifact ?? record.reviewArtifact,
        incomingWorkspaceId,
        sameWorkspace,
      ),
      chromeFallback?.reviewArtifact,
    ),
    scenarioLab: mapScenarioLab(
      scopedTrainingSubmodeValue(
        record.scenario_lab ?? record.scenarioLab,
        incomingWorkspaceId,
        sameWorkspace,
      ),
      chromeFallback?.scenarioLab,
    ),
    theoryDrill: mapTheoryDrill(
      scopedTrainingSubmodeValue(
        record.theory_drill ?? record.theoryDrill,
        incomingWorkspaceId,
        sameWorkspace,
      ),
      chromeFallback?.theoryDrill,
    ),
    dueReviews:
      record.due_reviews === undefined && record.dueReviews === undefined
        ? chromeFallback?.dueReviews ?? []
        : mapDueReviews(
            record.due_reviews ?? record.dueReviews,
            incomingWorkspaceId,
            !sameWorkspace,
          ),
  };

  if (!hasWorkspaceTrainingStateContent(mapped)) {
    return fallback;
  }

  return mapped;
}

function toTrainingReliabilityPhase(
  value: string | undefined,
): NonNullable<WorkspaceTrainingStateView['latestTrainingReliability']>['phase'] {
  if (
    value === "intent" ||
    value === "pending" ||
    value === "executing" ||
    value === "succeeded" ||
    value === "failed" ||
    value === "acked" ||
    value === "cancelled"
  ) {
    return value;
  }
  return undefined;
}

function toTrainingReliabilityOutcome(
  value: string | undefined,
): NonNullable<WorkspaceTrainingStateView['latestTrainingReliability']>['outcome'] {
  if (
    value === "success" ||
    value === "failure" ||
    value === "cancelled" ||
    value === "timeout" ||
    value === ""
  ) {
    return value;
  }
  return undefined;
}

function mapTrainingReliability(
  value: unknown,
  fallback: WorkspaceTrainingStateView['latestTrainingReliability'],
): WorkspaceTrainingStateView['latestTrainingReliability'] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }
  const requestId =
    asString(record.request_id) ?? asString(record.requestId) ?? fallback?.requestId;
  if (!requestId) {
    return fallback;
  }
  return {
    requestId,
    idempotencyKey:
      asString(record.idempotency_key) ?? asString(record.idempotencyKey) ?? fallback?.idempotencyKey,
    commandId: asString(record.command_id) ?? asString(record.commandId) ?? fallback?.commandId,
    cardId: asString(record.card_id) ?? asString(record.cardId) ?? fallback?.cardId,
    handoffId: asString(record.handoff_id) ?? asString(record.handoffId) ?? fallback?.handoffId,
    phase:
      toTrainingReliabilityPhase(asString(record.phase)) ?? fallback?.phase,
    revision: asNumber(record.revision) ?? fallback?.revision,
    snapshotRevision:
      asNumber(record.snapshot_revision) ?? asNumber(record.snapshotRevision) ?? fallback?.snapshotRevision,
    createdAt: asString(record.created_at) ?? asString(record.createdAt) ?? fallback?.createdAt,
    updatedAt: asString(record.updated_at) ?? asString(record.updatedAt) ?? fallback?.updatedAt,
    ackedAt: asString(record.acked_at) ?? asString(record.ackedAt) ?? fallback?.ackedAt,
    timeoutAt: asString(record.timeout_at) ?? asString(record.timeoutAt) ?? fallback?.timeoutAt,
    cancelRequested:
      asBoolean(record.cancel_requested) ?? asBoolean(record.cancelRequested) ?? fallback?.cancelRequested,
    outcome:
      toTrainingReliabilityOutcome(asString(record.outcome)) ?? fallback?.outcome,
    error: (() => {
      const rawError = asString(record.error) ?? fallback?.error;
      return rawError ? sanitizeErrorSurfaceText(rawError) : undefined;
    })(),
    recoverable: asBoolean(record.recoverable) ?? fallback?.recoverable,
    recoveryAction:
      asString(record.recovery_action) ?? asString(record.recoveryAction) ?? fallback?.recoveryAction,
    learningPhase:
      asString(record.learning_phase) ?? asString(record.learningPhase) ?? fallback?.learningPhase,
  };
}

function mapTrainingHandoff(
  value: unknown,
  fallback: WorkspaceTrainingStateView['latestTrainingHandoff'],
): WorkspaceTrainingStateView['latestTrainingHandoff'] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const mapped: TrainingHandoffStateView = {
    handoffId:
      asString(record.handoff_id) ??
      asString(record.handoffId) ??
      fallback?.handoffId,
    learningPhase:
      toTrainingLearningPhase(asString(record.learning_phase) ?? asString(record.learningPhase)) ??
      fallback?.learningPhase,
    candidateId: asString(record.candidate_id) ?? asString(record.candidateId) ?? fallback?.candidateId,
    candidateType:
      toTrainingConversationCandidateType(
        asString(record.candidate_type) ?? asString(record.candidateType),
      ) ?? fallback?.candidateType,
    targetKind: asString(record.target_kind) ?? asString(record.targetKind) ?? fallback?.targetKind,
    targetId: asString(record.target_id) ?? asString(record.targetId) ?? fallback?.targetId,
    continueIn:
      toTrainingContinueIn(asString(record.continue_in) ?? asString(record.continueIn)) ??
      fallback?.continueIn,
    acceptedInto:
      asString(record.accepted_into) ?? asString(record.acceptedInto) ?? fallback?.acceptedInto,
    handoffStatus:
      asString(record.handoff_status) ?? asString(record.handoffStatus) ?? fallback?.handoffStatus,
    handoffSummary:
      asString(record.handoff_summary) ?? asString(record.handoffSummary) ?? fallback?.handoffSummary,
    blockedBy: asString(record.blocked_by) ?? asString(record.blockedBy) ?? fallback?.blockedBy,
    coachOnly: asBoolean(record.coach_only) ?? asBoolean(record.coachOnly) ?? fallback?.coachOnly,
    cardType:
      toTrainingCardType(asString(record.card_type) ?? asString(record.cardType)) ??
      fallback?.cardType,
    cardTitle: asString(record.card_title) ?? asString(record.cardTitle) ?? fallback?.cardTitle,
    scenarioPack:
      asString(record.scenario_pack) ?? asString(record.scenarioPack) ?? fallback?.scenarioPack,
    learnerDeliverables:
      asStringArray(record.learner_deliverables ?? record.learnerDeliverables) ??
      fallback?.learnerDeliverables,
    verificationSteps:
      asStringArray(record.verification_steps ?? record.verificationSteps) ??
      fallback?.verificationSteps,
    successSignal:
      asString(record.success_signal) ?? asString(record.successSignal) ?? fallback?.successSignal,
    returnWith: asString(record.return_with) ?? asString(record.returnWith) ?? fallback?.returnWith,
    nextAfterCompletion:
      asString(record.next_after_completion) ??
      asString(record.nextAfterCompletion) ??
      fallback?.nextAfterCompletion,
    fallbackAction:
      asString(record.fallback_action) ?? asString(record.fallbackAction) ?? fallback?.fallbackAction,
    returnMode:
      toTrainingReturnMode(asString(record.return_mode) ?? asString(record.returnMode)) ??
      fallback?.returnMode,
    returnSummary:
      asString(record.return_summary) ?? asString(record.returnSummary) ?? fallback?.returnSummary,
    judgedAt:
      asString(record.judged_at) ??
      asString(record.judgedAt) ??
      asString(record.fed_back_at) ??
      asString(record.fedBackAt) ??
      fallback?.judgedAt,
    sourceChain:
      asStringArray(record.source_chain ?? record.sourceChain) ?? fallback?.sourceChain,
  };

  return hasTrainingHandoffContent(mapped) ? mapped : undefined;
}

function mapTrainingNextHop(
  value: unknown,
  fallback: WorkspaceTrainingStateView['latestTrainingNextHop'],
): WorkspaceTrainingStateView['latestTrainingNextHop'] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const mapped: TrainingNextHopStateView = {
    candidateId: asString(record.candidate_id) ?? asString(record.candidateId) ?? fallback?.candidateId,
    candidateType:
      toTrainingNextHopCandidateType(
        asString(record.candidate_type) ?? asString(record.candidateType),
      ) ?? fallback?.candidateType,
    title: asString(record.title) ?? fallback?.title,
    summary: asString(record.summary) ?? fallback?.summary,
    whyNow: asString(record.why_now) ?? asString(record.whyNow) ?? fallback?.whyNow,
    projectScope:
      toTrainingProjectScope(asString(record.project_scope) ?? asString(record.projectScope)) ??
      fallback?.projectScope,
    continueIn:
      toTrainingNextHopContinueIn(asString(record.continue_in) ?? asString(record.continueIn)) ??
      fallback?.continueIn,
    targetKind: asString(record.target_kind) ?? asString(record.targetKind) ?? fallback?.targetKind,
    targetId: asString(record.target_id) ?? asString(record.targetId) ?? fallback?.targetId,
    acceptedInto:
      asString(record.accepted_into) ?? asString(record.acceptedInto) ?? fallback?.acceptedInto,
    status:
      toTrainingNextHopStatus(asString(record.status)) ??
      fallback?.status,
    statusReason:
      asString(record.status_reason) ?? asString(record.statusReason) ?? fallback?.statusReason,
    blockedBy: asString(record.blocked_by) ?? asString(record.blockedBy) ?? fallback?.blockedBy,
    handoffStatus:
      asString(record.handoff_status) ?? asString(record.handoffStatus) ?? fallback?.handoffStatus,
    handoffSummary:
      asString(record.handoff_summary) ?? asString(record.handoffSummary) ?? fallback?.handoffSummary,
    coachOnly: asBoolean(record.coach_only) ?? asBoolean(record.coachOnly) ?? fallback?.coachOnly,
    cardType:
      toTrainingCardType(asString(record.card_type) ?? asString(record.cardType)) ??
      fallback?.cardType,
    cardTitle: asString(record.card_title) ?? asString(record.cardTitle) ?? fallback?.cardTitle,
    scenarioPack:
      asString(record.scenario_pack) ?? asString(record.scenarioPack) ?? fallback?.scenarioPack,
    returnMode:
      toTrainingReturnMode(asString(record.return_mode) ?? asString(record.returnMode)) ??
      fallback?.returnMode,
    returnSummary:
      asString(record.return_summary) ?? asString(record.returnSummary) ?? fallback?.returnSummary,
    judgedAt:
      asString(record.judged_at) ?? asString(record.judgedAt) ?? fallback?.judgedAt,
    reviewArtifactId:
      asString(record.review_artifact_id) ??
      asString(record.reviewArtifactId) ??
      fallback?.reviewArtifactId,
    reviewArtifactStatus:
      asString(record.review_artifact_status) ??
      asString(record.reviewArtifactStatus) ??
      fallback?.reviewArtifactStatus,
    reviewRecoveryMode:
      asString(record.review_recovery_mode) ??
      asString(record.reviewRecoveryMode) ??
      fallback?.reviewRecoveryMode,
    planEvidenceId:
      asString(record.plan_evidence_id) ?? asString(record.planEvidenceId) ?? fallback?.planEvidenceId,
    nextAfterCompletion:
      asString(record.next_after_completion) ??
      asString(record.nextAfterCompletion) ??
      fallback?.nextAfterCompletion,
    fallbackAction:
      asString(record.fallback_action) ?? asString(record.fallbackAction) ?? fallback?.fallbackAction,
    sourceChain:
      asStringArray(record.source_chain ?? record.sourceChain) ?? fallback?.sourceChain,
  };

  return hasTrainingNextHopContent(mapped) ? mapped : undefined;
}

function mapTrainingCardCandidates(
  value: unknown,
  fallback: WorkspaceTrainingStateView['trainingCardCandidates'],
): WorkspaceTrainingStateView['trainingCardCandidates'] {
  if (value === undefined || value === null) {
    return fallback;
  }
  if (!Array.isArray(value)) {
    return fallback;
  }

  return value.reduce<TrainingCardCandidateStateView[]>((items, entry) => {
    const record = asRecord(entry);
    const cardId = asString(record?.card_id) ?? asString(record?.cardId) ?? asString(record?.id);
    const title = asString(record?.title);
    const type = toTrainingCardType(asString(record?.card_type) ?? asString(record?.cardType) ?? asString(record?.type));
    if (!cardId || !title || !type) {
      return items;
    }
    items.push({
      cardId,
      type,
      title,
      whyNow: asString(record?.why_now) ?? asString(record?.whyNow) ?? undefined,
      status: asString(record?.status) ?? undefined,
      learningPhase:
        toTrainingLearningPhase(
          asString(record?.learning_phase) ?? asString(record?.learningPhase),
        ) ?? undefined,
      ...mapTrainingCardVerificationFields(record),
    });
    return items;
  }, []);
}

type TrainingCardVerificationFields = Pick<
  TrainingCardCandidateStateView,
  | 'learningPhase'
  | 'question'
  | 'choices'
  | 'answerMode'
  | 'expectedAnswer'
  | 'learningFamily'
  | 'learningSubtype'
  | 'knowledgeType'
  | 'focusArea'
  | 'targetSkill'
  | 'scenarioPack'
  | 'scenario'
  | 'problemStatement'
  | 'suggestedWorkspaceAction'
  | 'apiHints'
  | 'constraints'
  | 'deliverable'
  | 'selfCheck'
  | 'expectedAnswerShape'
  | 'validationMethod'
  | 'verificationMethod'
  | 'filesToTouch'
  | 'learnerDeliverables'
  | 'verificationSteps'
  | 'successSignal'
  | 'expectedSymbols'
  | 'returnWith'
  | 'nextAfterCompletion'
  | 'trainerReviewInput'
  | 'stuckRecovery'
  | 'reflectionPrompt'
  | 'hintLadder'
  | 'commonMistakes'
>;

function mapTrainingCardVerificationFields(
  record: Record<string, unknown> | undefined,
  fallback?: Partial<TrainingCardVerificationFields>,
): Partial<TrainingCardVerificationFields> {
  if (!record) {
    return fallback ?? {};
  }
  return {
    learningPhase:
      toTrainingLearningPhase(
        asString(record.learning_phase) ?? asString(record.learningPhase),
      ) ?? fallback?.learningPhase,
    question: asString(record.question) ?? fallback?.question,
    choices: asStringArray(record.choices ?? record.options) ?? fallback?.choices,
    answerMode:
      asString(record.answer_mode) ??
      asString(record.answerMode) ??
      fallback?.answerMode,
    expectedAnswer:
      asString(record.expected_answer) ??
      asString(record.expectedAnswer) ??
      fallback?.expectedAnswer,
    learningFamily:
      (asString(record.learning_family) ?? asString(record.learningFamily)) === 'code'
        ? 'code'
        : (asString(record.learning_family) ?? asString(record.learningFamily)) === 'theory'
          ? 'theory'
          : fallback?.learningFamily,
    learningSubtype:
      asString(record.learning_subtype) ?? asString(record.learningSubtype) ?? fallback?.learningSubtype,
    knowledgeType:
      asString(record.knowledge_type) ?? asString(record.knowledgeType) ?? fallback?.knowledgeType,
    focusArea: asString(record.focus_area) ?? asString(record.focusArea) ?? fallback?.focusArea,
    targetSkill: asString(record.target_skill) ?? asString(record.targetSkill) ?? fallback?.targetSkill,
    scenarioPack:
      asString(record.scenario_pack) ?? asString(record.scenarioPack) ?? fallback?.scenarioPack,
    scenario: asString(record.scenario) ?? fallback?.scenario,
    problemStatement:
      asString(record.problem_statement) ?? asString(record.problemStatement) ?? fallback?.problemStatement,
    suggestedWorkspaceAction:
      asString(record.suggested_workspace_action) ??
      asString(record.suggestedWorkspaceAction) ??
      fallback?.suggestedWorkspaceAction,
    apiHints: asStringArray(record.api_hints ?? record.apiHints) ?? fallback?.apiHints,
    constraints: asStringArray(record.constraints) ?? fallback?.constraints,
    deliverable: asString(record.deliverable) ?? fallback?.deliverable,
    selfCheck: asStringArray(record.self_check ?? record.selfCheck) ?? fallback?.selfCheck,
    expectedAnswerShape:
      asString(record.expected_answer_shape) ??
      asString(record.expectedAnswerShape) ??
      fallback?.expectedAnswerShape,
    validationMethod:
      asString(record.validation_method) ??
      asString(record.validationMethod) ??
      fallback?.validationMethod,
    verificationMethod:
      asString(record.verification_method) ??
      asString(record.verificationMethod) ??
      fallback?.verificationMethod,
    filesToTouch:
      asStringArray(record.files_to_touch ?? record.filesToTouch) ?? fallback?.filesToTouch,
    learnerDeliverables:
      asStringArray(record.learner_deliverables ?? record.learnerDeliverables) ??
      fallback?.learnerDeliverables,
    verificationSteps:
      asStringArray(record.verification_steps ?? record.verificationSteps) ??
      fallback?.verificationSteps,
    successSignal:
      asString(record.success_signal) ?? asString(record.successSignal) ?? fallback?.successSignal,
    expectedSymbols:
      asStringArray(record.expected_symbols ?? record.expectedSymbols) ?? fallback?.expectedSymbols,
    returnWith:
      asString(record.return_with) ?? asString(record.returnWith) ?? fallback?.returnWith,
    nextAfterCompletion:
      asString(record.next_after_completion) ??
      asString(record.nextAfterCompletion) ??
      fallback?.nextAfterCompletion,
    trainerReviewInput:
      asString(record.trainer_review_input) ??
      asString(record.trainerReviewInput) ??
      fallback?.trainerReviewInput,
    stuckRecovery:
      asString(record.stuck_recovery) ?? asString(record.stuckRecovery) ?? fallback?.stuckRecovery,
    reflectionPrompt:
      asString(record.reflection_prompt) ??
      asString(record.reflectionPrompt) ??
      fallback?.reflectionPrompt,
    hintLadder:
      asStringArray(record.hint_ladder ?? record.hintLadder) ?? fallback?.hintLadder,
    commonMistakes:
      asStringArray(record.common_mistakes ?? record.commonMistakes) ?? fallback?.commonMistakes,
  };
}

function mapTrainerWorkspaceAdmission(
  value: unknown,
  fallback: TrainerWorkspaceAdmissionStateView | undefined,
): TrainerWorkspaceAdmissionStateView | undefined {
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const status = asString(record.status);
  if (
    status !== 'root-missing' &&
    status !== 'project-found' &&
    status !== 'managed' &&
    status !== 'browse' &&
    status !== 'ignored'
  ) {
    return fallback;
  }

  return {
    status,
    rootPath: asString(record.root_path) ?? asString(record.rootPath) ?? fallback?.rootPath,
    projectId: asString(record.project_id) ?? asString(record.projectId) ?? fallback?.projectId,
    projectName: asString(record.project_name) ?? asString(record.projectName) ?? fallback?.projectName,
    projectPath: asString(record.project_path) ?? asString(record.projectPath) ?? fallback?.projectPath,
    updatedAt: asString(record.updated_at) ?? asString(record.updatedAt) ?? fallback?.updatedAt,
    reconciliation: (() => {
      const reconciliation = asRecord(record.reconciliation);
      const state = asString(reconciliation?.state);
      if (!reconciliation || (state !== 'waiting' && state !== 'retry-required')) return fallback?.reconciliation;
      return {
        reason: asString(reconciliation.reason) ?? 'Workspace admission needs reconciliation.',
        jobId: asString(reconciliation.job_id) ?? asString(reconciliation.jobId),
        updatedAt: asString(reconciliation.updated_at) ?? asString(reconciliation.updatedAt) ?? new Date(0).toISOString(),
        state,
        availableActions: Array.isArray(reconciliation.available_actions)
          ? reconciliation.available_actions.filter((action): action is 'continue-waiting' | 'retry' | 'abandon' => action === 'continue-waiting' || action === 'retry' || action === 'abandon')
          : [],
      };
    })(),
  };
}

function mapActiveTrainingCardRouting(
  value: unknown,
  fallback: WorkspaceTrainingStateView['activeTrainingCardRouting'],
): WorkspaceTrainingStateView['activeTrainingCardRouting'] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const selectedCard = asRecord(record.selected_card ?? record.selectedCard);
  const mapped: ActiveTrainingCardRoutingStateView = {
    selectedCardId:
      asString(record.selected_card_id) ?? asString(record.selectedCardId) ?? fallback?.selectedCardId,
    selectedCard: selectedCard
      ? {
          cardId:
            asString(selectedCard.card_id) ??
            asString(selectedCard.cardId) ??
            fallback?.selectedCard?.cardId,
          title: asString(selectedCard.title) ?? fallback?.selectedCard?.title,
          type:
            toTrainingCardType(asString(selectedCard.type) ?? asString(selectedCard.card_type)) ??
            fallback?.selectedCard?.type,
          ...mapTrainingCardVerificationFields(selectedCard, fallback?.selectedCard),
        }
      : fallback?.selectedCard,
    whyThisCard:
      asString(record.why_this_card) ?? asString(record.whyThisCard) ?? fallback?.whyThisCard,
    nextAfterCompletion:
      asString(record.next_after_completion) ??
      asString(record.nextAfterCompletion) ??
      fallback?.nextAfterCompletion,
    blockedCandidates: mapTrainingBlockedCandidates(
      record.blocked_candidates ?? record.blockedCandidates,
      fallback?.blockedCandidates,
    ),
    fallbackAction:
      asString(record.fallback_action) ?? asString(record.fallbackAction) ?? fallback?.fallbackAction,
    candidateCount:
      asNumber(record.candidate_count) ?? asNumber(record.candidateCount) ?? fallback?.candidateCount,
    eligibleCount:
      asNumber(record.eligible_count) ?? asNumber(record.eligibleCount) ?? fallback?.eligibleCount,
  };

  return hasActiveTrainingCardRoutingContent(mapped) ? mapped : undefined;
}

function mapTrainingBlockedCandidates(
  value: unknown,
  fallback: ActiveTrainingCardRoutingStateView['blockedCandidates'],
): ActiveTrainingCardRoutingStateView['blockedCandidates'] {
  if (value === undefined || value === null) {
    return fallback;
  }
  if (!Array.isArray(value)) {
    return fallback;
  }

  return value.reduce<TrainingBlockedCardCandidateStateView[]>((items, entry) => {
    const record = asRecord(entry);
    const cardId = asString(record?.card_id) ?? asString(record?.cardId);
    const title = asString(record?.title);
    const type = toTrainingCardType(asString(record?.type) ?? asString(record?.card_type));
    if (!cardId || !title || !type) {
      return items;
    }
    items.push({
      cardId,
      type,
      title,
      reasons: asStringArray(record?.reasons) ?? [],
    });
    return items;
  }, []);
}

function mapTrainingEventLedger(
  value: unknown,
  fallback: WorkspaceTrainingStateView['trainingEventLedger'],
): WorkspaceTrainingStateView['trainingEventLedger'] {
  if (value === undefined || value === null) {
    return fallback;
  }
  if (!Array.isArray(value)) {
    return fallback;
  }

  return value.reduce<TrainingEventLedgerEntryStateView[]>((items, entry) => {
    const record = asRecord(entry);
    if (!record) {
      return items;
    }
    const mapped: TrainingEventLedgerEntryStateView = {
      eventId: asString(record.event_id) ?? asString(record.eventId) ?? undefined,
      eventType: asString(record.event_type) ?? asString(record.eventType) ?? undefined,
      candidateId: asString(record.candidate_id) ?? asString(record.candidateId) ?? undefined,
      candidateStatus:
        asString(record.candidate_status) ?? asString(record.candidateStatus) ?? undefined,
      candidateStatusReason:
        asString(record.candidate_status_reason) ??
        asString(record.candidateStatusReason) ??
        undefined,
      candidateContinueIn:
        toTrainingContinueIn(
          asString(record.candidate_continue_in) ?? asString(record.candidateContinueIn),
        ) ?? undefined,
      candidateType:
        toTrainingConversationCandidateType(
          asString(record.candidate_type) ?? asString(record.candidateType),
        ) ?? undefined,
      selectedCardId:
        asString(record.selected_card_id) ?? asString(record.selectedCardId) ?? undefined,
      selectedCardType:
        toTrainingCardType(asString(record.selected_card_type) ?? asString(record.selectedCardType)) ??
        undefined,
      selectedCardTitle:
        asString(record.selected_card_title) ?? asString(record.selectedCardTitle) ?? undefined,
      cardCandidateId:
        asString(record.card_candidate_id) ?? asString(record.cardCandidateId) ?? undefined,
      cardCandidateType:
        toTrainingCardType(asString(record.card_candidate_type) ?? asString(record.cardCandidateType)) ??
        undefined,
      cardCandidateTitle:
        asString(record.card_candidate_title) ?? asString(record.cardCandidateTitle) ?? undefined,
      whyThisCard:
        asString(record.why_this_card) ?? asString(record.whyThisCard) ?? undefined,
      learnerDeliverables:
        asStringArray(record.learner_deliverables ?? record.learnerDeliverables) ?? undefined,
      verificationSteps:
        asStringArray(record.verification_steps ?? record.verificationSteps) ?? undefined,
      successSignal:
        asString(record.success_signal) ?? asString(record.successSignal) ?? undefined,
      expectedSymbols:
        asStringArray(record.expected_symbols ?? record.expectedSymbols) ?? undefined,
      filesToTouch:
        asStringArray(record.files_to_touch ?? record.filesToTouch) ?? undefined,
      returnWith:
        asString(record.return_with) ?? asString(record.returnWith) ?? undefined,
      nextAfterCompletion:
        asString(record.next_after_completion) ??
        asString(record.nextAfterCompletion) ??
        undefined,
      fallbackAction:
        asString(record.fallback_action) ?? asString(record.fallbackAction) ?? undefined,
      planEvidenceId:
        asString(record.plan_evidence_id) ?? asString(record.planEvidenceId) ?? undefined,
      reviewArtifactId:
        asString(record.review_artifact_id) ?? asString(record.reviewArtifactId) ?? undefined,
      reviewArtifactStatus:
        asString(record.review_artifact_status) ??
        asString(record.reviewArtifactStatus) ??
        undefined,
      reviewRecoveryMode:
        asString(record.review_recovery_mode) ??
        asString(record.reviewRecoveryMode) ??
        undefined,
      judgedAt: asString(record.judged_at) ?? asString(record.judgedAt) ?? undefined,
      sourceChain:
        asStringArray(record.source_chain ?? record.sourceChain) ?? undefined,
      returnMode:
        toTrainingReturnMode(asString(record.return_mode) ?? asString(record.returnMode)) ??
        undefined,
      returnSummary:
        asString(record.return_summary) ?? asString(record.returnSummary) ?? undefined,
      candidateTargetKind:
        asString(record.candidate_target_kind) ?? asString(record.candidateTargetKind) ?? undefined,
      candidateTargetId:
        asString(record.candidate_target_id) ?? asString(record.candidateTargetId) ?? undefined,
      candidateProjectScope:
        toTrainingProjectScope(
          asString(record.candidate_project_scope) ?? asString(record.candidateProjectScope),
        ) ?? undefined,
      candidateBlockedBy:
        asString(record.candidate_blocked_by) ?? asString(record.candidateBlockedBy) ?? undefined,
      candidateAcceptedInto:
        asString(record.candidate_accepted_into) ??
        asString(record.candidateAcceptedInto) ??
        undefined,
      candidateWhyNow:
        asString(record.candidate_why_now) ?? asString(record.candidateWhyNow) ?? undefined,
      candidateTitle:
        asString(record.candidate_title) ?? asString(record.candidateTitle) ?? undefined,
      statusSummary:
        asString(record.status_summary) ?? asString(record.statusSummary) ?? undefined,
      statusDetail:
        asString(record.status_detail) ?? asString(record.statusDetail) ?? undefined,
      statusKind:
        asString(record.status_kind) ?? asString(record.statusKind) ?? undefined,
      blockedCandidates: mapTrainingBlockedCandidates(
        record.blocked_candidates ?? record.blockedCandidates,
        undefined,
      ),
      createdAt: asString(record.created_at) ?? asString(record.createdAt) ?? undefined,
    };

    if (hasTrainingEventLedgerEntryContent(mapped)) {
      items.push(mapped);
    }
    return items;
  }, []);
}

function mapReviewArtifact(
  value: unknown,
  fallback: WorkspaceTrainingStateView['reviewArtifact'],
): WorkspaceTrainingStateView['reviewArtifact'] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const mapped: ReviewArtifactStateView = {
    id: asString(record.id) ?? fallback?.id,
    title: asString(record.title) ?? fallback?.title,
    focusArea: asString(record.focus_area) ?? asString(record.focusArea) ?? fallback?.focusArea,
    source: asString(record.source) ?? fallback?.source,
    status: asString(record.status) ?? fallback?.status,
    summary: asString(record.summary) ?? fallback?.summary,
    rootCause: asString(record.root_cause) ?? asString(record.rootCause) ?? fallback?.rootCause,
    guardrail: asString(record.guardrail) ?? fallback?.guardrail,
    nextSelfImplementationRule:
      asString(record.next_self_implementation_rule) ??
      asString(record.nextSelfImplementationRule) ??
      fallback?.nextSelfImplementationRule,
    recommendedRecoveryMode:
      asString(record.recommended_recovery_mode) ??
      asString(record.recommendedRecoveryMode) ??
      fallback?.recommendedRecoveryMode,
    recommendedActions:
      asStringArray(record.recommended_actions ?? record.recommendedActions) ??
      fallback?.recommendedActions,
    verifiedResult:
      asString(record.verified_result) ?? asString(record.verifiedResult) ?? fallback?.verifiedResult,
    blockedReason:
      asString(record.blocked_reason) ?? asString(record.blockedReason) ?? fallback?.blockedReason,
    partialProgress:
      asString(record.partial_progress) ??
      asString(record.partialProgress) ??
      fallback?.partialProgress,
    lastAction:
      asString(record.last_action) ?? asString(record.lastAction) ?? fallback?.lastAction,
    updatedAt:
      asString(record.updated_at) ?? asString(record.updatedAt) ?? fallback?.updatedAt,
  };

  return hasReviewArtifactContent(mapped) ? mapped : undefined;
}

function mapScenarioLab(
  value: unknown,
  fallback: WorkspaceTrainingStateView['scenarioLab'],
): WorkspaceTrainingStateView['scenarioLab'] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const mapped: ScenarioLabStateView = {
    id: asString(record.id) ?? fallback?.id,
    title: asString(record.title) ?? fallback?.title,
    focusArea: asString(record.focus_area) ?? asString(record.focusArea) ?? fallback?.focusArea,
    status: asString(record.status) ?? fallback?.status,
    successSignal:
      asString(record.success_signal) ?? asString(record.successSignal) ?? fallback?.successSignal,
    reviewOutcome:
      asString(record.review_outcome) ?? asString(record.reviewOutcome) ?? fallback?.reviewOutcome,
    learnerDeliverables:
      asStringArray(record.learner_deliverables ?? record.learnerDeliverables) ??
      fallback?.learnerDeliverables,
    verificationSteps:
      asStringArray(record.verification_steps ?? record.verificationSteps) ??
      fallback?.verificationSteps,
    migrateBackGuidance:
      asStringArray(record.migrate_back_guidance ?? record.migrateBackGuidance) ??
      fallback?.migrateBackGuidance,
    dependencyKeys:
      asStringArray(record.dependency_keys ?? record.dependencyKeys) ?? fallback?.dependencyKeys,
    relatedApis:
      asStringArray(record.related_apis ?? record.relatedApis) ?? fallback?.relatedApis,
    lastAction:
      asString(record.last_action) ?? asString(record.lastAction) ?? fallback?.lastAction,
    updatedAt:
      asString(record.updated_at) ?? asString(record.updatedAt) ?? fallback?.updatedAt,
  };

  return hasScenarioLabContent(mapped) ? mapped : undefined;
}

function mapTheoryDrill(
  value: unknown,
  fallback: WorkspaceTrainingStateView['theoryDrill'],
): WorkspaceTrainingStateView['theoryDrill'] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const mapped: TheoryDrillStateView = {
    id: asString(record.id) ?? fallback?.id,
    title: asString(record.title) ?? fallback?.title,
    focusArea: asString(record.focus_area) ?? asString(record.focusArea) ?? fallback?.focusArea,
    status: asString(record.status) ?? fallback?.status,
    summary: asString(record.summary) ?? fallback?.summary,
    successSignal:
      asString(record.success_signal) ?? asString(record.successSignal) ?? fallback?.successSignal,
    returnWith:
      asString(record.return_with) ?? asString(record.returnWith) ?? fallback?.returnWith,
    questions: mapTheoryDrillQuestions(record.questions, fallback?.questions),
    lastAction:
      asString(record.last_action) ?? asString(record.lastAction) ?? fallback?.lastAction,
    updatedAt:
      asString(record.updated_at) ?? asString(record.updatedAt) ?? fallback?.updatedAt,
  };

  return hasTheoryDrillContent(mapped) ? mapped : undefined;
}

function mapTheoryDrillQuestions(
  value: unknown,
  fallback: TheoryDrillStateView['questions'],
): TheoryDrillStateView['questions'] {
  if (value === undefined || value === null) {
    return fallback;
  }
  if (!Array.isArray(value)) {
    return fallback;
  }

  return value.reduce<TheoryDrillQuestionStateView[]>((items, entry) => {
    const record = asRecord(entry);
    const prompt = asString(record?.prompt);
    if (!prompt) {
      return items;
    }
    items.push({
      id: asString(record?.question_id) ?? asString(record?.questionId) ?? asString(record?.id),
      prompt,
      choices: asStringArray(record?.choices) ?? asStringArray(record?.options) ?? undefined,
      answer: asString(record?.answer) ?? undefined,
      explanation: asString(record?.explanation) ?? undefined,
    });
    return items;
  }, []);
}

function hasWorkspaceTrainingStateContent(value: WorkspaceTrainingStateView): boolean {
  return Boolean(
    value.workspaceId ||
      value.latestConversationHandoff ||
      value.latestTrainingHandoff ||
      value.latestTrainingReliability ||
      value.latestTrainingNextHop ||
      value.latestTrainingSubmode ||
      value.latestLearningFocusArea ||
      value.latestLearningFollowup ||
      value.latestLearningVerifiedResult ||
      value.latestLearningBlocker ||
      value.latestLearningAbandonReason ||
      value.latestLearningPartialProgress ||
      value.selectedCardId ||
      value.selectedCardTitle ||
      value.selectedCardStatus ||
      value.trainingCardCandidates?.length ||
      value.activeTrainingCardRouting ||
      value.trainingEventLedger?.length ||
      value.reviewArtifact ||
      value.scenarioLab ||
      value.theoryDrill ||
      value.dueReviews?.length,
  );
}

function hasTrainingHandoffContent(value: TrainingHandoffStateView): boolean {
  return Boolean(
    value.candidateId ||
      value.candidateType ||
      value.targetKind ||
      value.targetId ||
      value.continueIn ||
      value.acceptedInto ||
      value.handoffStatus ||
      value.handoffSummary ||
      value.blockedBy ||
      value.cardType ||
      value.cardTitle ||
      value.scenarioPack ||
      value.learnerDeliverables?.length ||
      value.verificationSteps?.length ||
      value.successSignal ||
      value.returnWith ||
      value.nextAfterCompletion ||
      value.fallbackAction ||
      value.returnMode ||
      value.returnSummary ||
      value.judgedAt ||
      value.sourceChain?.length ||
      value.coachOnly ||
      value.learningPhase ||
      value.handoffId,
  );
}

function hasTrainingNextHopContent(value: TrainingNextHopStateView): boolean {
  return Boolean(
    value.candidateId ||
      value.candidateType ||
      value.title ||
      value.summary ||
      value.whyNow ||
      value.projectScope ||
      value.continueIn ||
      value.targetKind ||
      value.targetId ||
      value.acceptedInto ||
      value.status ||
      value.statusReason ||
      value.blockedBy ||
      value.handoffStatus ||
      value.handoffSummary ||
      value.cardType ||
      value.cardTitle ||
      value.scenarioPack ||
      value.returnMode ||
      value.returnSummary ||
      value.judgedAt ||
      value.reviewArtifactId ||
      value.reviewArtifactStatus ||
      value.reviewRecoveryMode ||
      value.planEvidenceId ||
      value.nextAfterCompletion ||
      value.fallbackAction ||
      value.sourceChain?.length ||
      value.coachOnly,
  );
}

function hasActiveTrainingCardRoutingContent(value: ActiveTrainingCardRoutingStateView): boolean {
  return Boolean(
      value.selectedCardId ||
      value.selectedCard?.title ||
      value.selectedCard?.type ||
      value.selectedCard?.scenarioPack ||
      value.selectedCard?.nextAfterCompletion ||
      value.selectedCard?.expectedSymbols?.length ||
      value.selectedCard?.apiHints?.length ||
      value.selectedCard?.learnerDeliverables?.length ||
      value.selectedCard?.verificationSteps?.length ||
      value.selectedCard?.successSignal ||
      value.whyThisCard ||
      value.nextAfterCompletion ||
      value.blockedCandidates?.length ||
      value.fallbackAction ||
      value.candidateCount ||
      value.eligibleCount,
  );
}

function hasTrainingEventLedgerEntryContent(value: TrainingEventLedgerEntryStateView): boolean {
  return Boolean(
    value.eventId ||
      value.eventType ||
      value.candidateId ||
      value.candidateStatus ||
      value.selectedCardId ||
      value.cardCandidateId ||
      value.whyThisCard ||
      value.learnerDeliverables?.length ||
      value.verificationSteps?.length ||
      value.successSignal ||
      value.expectedSymbols?.length ||
      value.filesToTouch?.length ||
      value.returnWith ||
      value.nextAfterCompletion ||
      value.fallbackAction ||
      value.reviewArtifactId ||
      value.planEvidenceId ||
      value.statusSummary ||
      value.statusDetail ||
      value.createdAt,
  );
}

function hasReviewArtifactContent(value: ReviewArtifactStateView): boolean {
  return Boolean(
    value.id ||
      value.title ||
      value.focusArea ||
      value.source ||
      value.status ||
      value.summary ||
      value.rootCause ||
      value.guardrail ||
      value.nextSelfImplementationRule ||
      value.recommendedRecoveryMode ||
      value.recommendedActions?.length ||
      value.verifiedResult ||
      value.blockedReason ||
      value.partialProgress ||
      value.lastAction ||
      value.updatedAt,
  );
}

function hasScenarioLabContent(value: ScenarioLabStateView): boolean {
  return Boolean(
    value.id ||
      value.title ||
      value.focusArea ||
      value.status ||
      value.successSignal ||
      value.reviewOutcome ||
      value.learnerDeliverables?.length ||
      value.verificationSteps?.length ||
      value.migrateBackGuidance?.length ||
      value.dependencyKeys?.length ||
      value.relatedApis?.length ||
      value.lastAction ||
      value.updatedAt,
  );
}

function hasTheoryDrillContent(value: TheoryDrillStateView): boolean {
  return Boolean(
    value.id ||
      value.title ||
      value.focusArea ||
      value.status ||
      value.summary ||
      value.successSignal ||
      value.returnWith ||
      value.questions?.length ||
      value.lastAction ||
      value.updatedAt,
  );
}

function mapDueReviews(
  value: unknown,
  incomingWorkspaceId?: string,
  workspaceChanged = false,
): BootstrapData['memory']['dueReviews'] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => asRecord(item))
    .filter((item): item is UnknownRecord => Boolean(item))
    .filter((item) => {
      if (!incomingWorkspaceId) {
        return true;
      }
      if (workspaceChanged) {
        const stamp = asString(item.workspace_id) ?? asString(item.workspaceId);
        if (!stamp) {
          return Boolean(asString(item.concept) || asString(item.reason));
        }
        return isCurrentForWorkspace({ workspaceId: stamp }, incomingWorkspaceId);
      }
      return trainingRecordMatchesWorkspace(item, incomingWorkspaceId);
    })
    .map((item) => ({
      concept: asString(item.concept) ?? '复习项',
      reason: asString(item.reason) ?? '',
      dueAt: asString(item.due_at),
      source: toReviewSource(asString(item.source)),
      severity: toReviewSeverity(asString(item.severity)),
      surfaceMode: toReviewSurfaceMode(asString(item.surface_mode)),
      taskHint: asString(item.task_hint) ?? undefined,
      focusArea: asString(item.focus_area) ?? undefined,
      linkedContext: toLinkedContext(item.linked_context),
      intervalDays: asNumber(item.interval_days) ?? undefined,
      masteryScore: asNumber(item.mastery_score) ?? undefined,
    }));
}

function mapCoachingState(
  value: unknown,
  fallback: BootstrapData['coachingState'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['coachingState'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const record = asRecord(value);
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? emptyLiveCoachingState() : fallback;
  }
  const useFallback = !workspaceChanged;
  return {
    scenario: toCoachingScenario(asString(record.scenario)),
    answerMode: toCoachingMode(asString(record.answer_mode)),
    learnerSignal: toLearnerSignal(asString(record.learner_signal)),
    summary: coachSurfaceText(record.summary) ?? (useFallback ? fallback?.summary : undefined) ?? '',
    nextStep: coachSurfaceText(record.next_step) ?? (useFallback ? fallback?.nextStep : undefined) ?? '',
    encouragement:
      coachSurfaceText(record.encouragement) ?? (useFallback ? fallback?.encouragement : undefined) ?? '',
    interventionStrategy:
      coachSurfaceText(record.intervention_strategy) ??
      (useFallback ? fallback?.interventionStrategy : undefined),
    teachingGoal: coachSurfaceText(record.teaching_goal) ?? (useFallback ? fallback?.teachingGoal : undefined),
    resumeThread: coachSurfaceText(record.resume_thread) ?? (useFallback ? fallback?.resumeThread : undefined),
    decision: asString(record.decision) ?? (useFallback ? fallback?.decision : undefined),
    blocker: coachSurfaceText(record.blocker) ?? (useFallback ? fallback?.blocker : undefined),
    teachingNote: coachSurfaceText(record.teaching_note) ?? (useFallback ? fallback?.teachingNote : undefined),
    confidence: asString(record.confidence) ?? (useFallback ? fallback?.confidence : undefined),
    evidence: asStringArray(record.evidence) ?? (useFallback ? fallback?.evidence : undefined),
    supportStrategy:
      coachSurfaceText(record.support_strategy) ?? (useFallback ? fallback?.supportStrategy : undefined),
    updatedAt:
      asString(record.updated_at) ?? (useFallback ? fallback?.updatedAt : undefined) ?? new Date().toISOString(),
  };
}

function mapLearnerState(
  value: unknown,
  fallback: BootstrapData['learnerState'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['learnerState'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const record = asRecord(value);
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? emptyLiveLearnerState() : fallback;
  }
  const useFallback = !workspaceChanged;
  return {
    currentConfidence: asNumber(record.current_confidence) ?? (useFallback ? fallback?.currentConfidence : undefined) ?? 0,
    frustrationLevel: asNumber(record.frustration_level) ?? (useFallback ? fallback?.frustrationLevel : undefined) ?? 0,
    attemptCountRecent:
      asNumber(record.attempt_count_recent) ?? (useFallback ? fallback?.attemptCountRecent : undefined) ?? 0,
    needsRescue: asBoolean(record.needs_rescue) ?? (useFallback ? fallback?.needsRescue : undefined) ?? false,
    needsReview: asBoolean(record.needs_review) ?? (useFallback ? fallback?.needsReview : undefined) ?? false,
    preferredHintDepth:
      asString(record.preferred_hint_depth) ?? (useFallback ? fallback?.preferredHintDepth : undefined) ?? 'guided',
    learnerSignal: toLearnerSignal(asString(record.learner_signal)),
    activeFocus: asString(record.active_focus) ?? (useFallback ? fallback?.activeFocus : undefined) ?? '',
    evidence: asStringArray(record.evidence) ?? (useFallback ? fallback?.evidence : undefined) ?? [],
  } satisfies LearnerStateView;
}

function mapAffectState(
  value: unknown,
  fallback: BootstrapData['affectState'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['affectState'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const record = asRecord(value);
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? emptyLiveAffectState() : fallback;
  }
  const useFallback = !workspaceChanged;
  return {
    frustrationLevel: asNumber(record.frustration_level) ?? (useFallback ? fallback?.frustrationLevel : undefined) ?? 0,
    confidenceLevel: asNumber(record.confidence_level) ?? (useFallback ? fallback?.confidenceLevel : undefined) ?? 0.5,
    momentumLevel: asNumber(record.momentum_level) ?? (useFallback ? fallback?.momentumLevel : undefined) ?? 0.5,
    needsReassurance:
      asBoolean(record.needs_reassurance) ?? (useFallback ? fallback?.needsReassurance : undefined) ?? false,
    urgencyLevel: toUrgencyLevel(
      asString(record.urgency_level) ?? (useFallback ? fallback?.urgencyLevel : undefined),
    ),
  } satisfies AffectStateView;
}

function mapTeachingDecision(
  value: unknown,
  fallback: BootstrapData['teachingDecision'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['teachingDecision'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const record = asRecord(value);
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? emptyLiveTeachingDecision() : fallback;
  }
  const useFallback = !workspaceChanged;
  return {
    mode: toTeachingMode(asString(record.mode)),
    reason: asString(record.reason) ?? (useFallback ? fallback?.reason : undefined) ?? '',
    primaryGoal: asString(record.primary_goal) ?? (useFallback ? fallback?.primaryGoal : undefined) ?? '',
    lessonShape: asString(record.lesson_shape) ?? (useFallback ? fallback?.lessonShape : undefined) ?? '',
    exerciseShape: asString(record.exercise_shape) ?? (useFallback ? fallback?.exerciseShape : undefined) ?? '',
    teachingStrategy: asString(record.teaching_strategy) ?? (useFallback ? fallback?.teachingStrategy : undefined) ?? '',
    closingMove: asString(record.closing_move) ?? (useFallback ? fallback?.closingMove : undefined) ?? '',
    artifactPriority:
      asStringArray(record.artifact_priority) ?? (useFallback ? fallback?.artifactPriority : undefined) ?? [],
    shouldEndWithQuestion:
      asBoolean(record.should_end_with_question) ??
      (useFallback ? fallback?.shouldEndWithQuestion : undefined) ??
      false,
    shouldGenerateExercise:
      asBoolean(record.should_generate_exercise) ??
      (useFallback ? fallback?.shouldGenerateExercise : undefined) ??
      false,
    shouldRevealCode:
      asBoolean(record.should_reveal_code) ?? (useFallback ? fallback?.shouldRevealCode : undefined) ?? false,
    shouldProducePlanArtifact:
      asBoolean(record.should_produce_plan_artifact) ??
      (useFallback ? fallback?.shouldProducePlanArtifact : undefined) ??
      false,
    shouldTriggerDeepAnalysis:
      asBoolean(record.should_trigger_deep_analysis) ??
      (useFallback ? fallback?.shouldTriggerDeepAnalysis : undefined) ??
      false,
    shouldFocusOnImplementationSteps:
      asBoolean(record.should_focus_on_implementation_steps) ??
      (useFallback ? fallback?.shouldFocusOnImplementationSteps : undefined) ??
      false,
    toneProfile: toToneProfile(asString(record.tone_profile)),
    focusArea:
      asString(record.focus_area) ??
      asString(record.focusArea) ??
      (useFallback ? fallback?.focusArea : undefined) ??
      '',
  } satisfies TeachingDecisionView;
}

function mapToneDecision(
  value: unknown,
  fallback: BootstrapData['toneDecision'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['toneDecision'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const record = asRecord(value);
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? emptyLiveToneDecision() : fallback;
  }
  const useFallback = !workspaceChanged;
  return {
    tone: toTone(asString(record.tone)),
    verbosityBias: toVerbosityBias(asString(record.verbosity_bias)),
    acknowledgeProgress:
      asBoolean(record.acknowledge_progress) ??
      (useFallback ? fallback?.acknowledgeProgress : undefined) ??
      false,
    avoidOverwhelm:
      asBoolean(record.avoid_overwhelm) ?? (useFallback ? fallback?.avoidOverwhelm : undefined) ?? false,
  } satisfies ToneDecisionView;
}

function mapImplementationGuide(
  value: unknown,
  fallback: BootstrapData['implementationGuide'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['implementationGuide'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const record = asRecord(value);
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? emptyLiveImplementationGuide() : fallback;
  }
  const useFallback = !workspaceChanged;
  return {
    ideaSummary: asString(record.idea_summary) ?? (useFallback ? fallback?.ideaSummary : undefined) ?? '',
    scopeBoundary: asString(record.scope_boundary) ?? (useFallback ? fallback?.scopeBoundary : undefined) ?? '',
    mvpDefinition: asString(record.mvp_definition) ?? (useFallback ? fallback?.mvpDefinition : undefined) ?? '',
    currentStep: asString(record.current_step) ?? (useFallback ? fallback?.currentStep : undefined) ?? '',
    nextSteps: asStringArray(record.next_steps) ?? (useFallback ? fallback?.nextSteps : undefined) ?? [],
    validationStrategy:
      asStringArray(record.validation_strategy) ?? (useFallback ? fallback?.validationStrategy : undefined) ?? [],
    openQuestions: asStringArray(record.open_questions) ?? (useFallback ? fallback?.openQuestions : undefined) ?? [],
    codebaseEntryPoints:
      asStringArray(record.codebase_entry_points) ?? (useFallback ? fallback?.codebaseEntryPoints : undefined),
    riskNotes: asStringArray(record.risk_notes) ?? (useFallback ? fallback?.riskNotes : undefined),
    teachingGoal: asString(record.teaching_goal) ?? (useFallback ? fallback?.teachingGoal : undefined),
    successSignal: asString(record.success_signal) ?? (useFallback ? fallback?.successSignal : undefined),
    fallbackStep: asString(record.fallback_step) ?? (useFallback ? fallback?.fallbackStep : undefined),
  } satisfies ImplementationGuideView;
}

function mapProjectIdeas(
  value: unknown,
  fallback: BootstrapData['projectIdeas'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['projectIdeas'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  if (!Array.isArray(value)) {
    return workspaceChanged ? [] : fallback;
  }
  return value
    .map((item) => asRecord(item))
    .filter((item): item is UnknownRecord => Boolean(item))
    .map((item, index) => ({
      id: asString(item.id) ?? `project-idea-${index + 1}`,
      title: asString(item.title) ?? 'Project idea',
      summary: asString(item.summary) ?? '',
      sourceArea: asString(item.source_area) ?? '',
      ideaKind: toProjectIdeaKind(asString(item.idea_kind)),
      learningValue: asString(item.learning_value) ?? '',
      engineeringValue: asString(item.engineering_value) ?? '',
      difficulty: asString(item.difficulty) ?? '',
      suggestedScope: asString(item.suggested_scope) ?? '',
      firstStep: asString(item.first_step) ?? '',
      acceptanceSignals: asStringArray(item.acceptance_signals) ?? [],
      whyNow: asString(item.why_now) ?? '',
    }) satisfies ProjectIdeaView);
}

function mapProjectAdaptationGuide(
  value: unknown,
  fallback: BootstrapData['projectAdaptationGuide'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['projectAdaptationGuide'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const record = asRecord(value);
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? emptyLiveAdaptationGuide() : fallback;
  }
  const useFallback = !workspaceChanged;
  return {
    targetOutcome: asString(record.target_outcome) ?? (useFallback ? fallback?.targetOutcome : undefined) ?? '',
    currentConstraints:
      asStringArray(record.current_constraints) ?? (useFallback ? fallback?.currentConstraints : undefined) ?? [],
    affectedAreas: asStringArray(record.affected_areas) ?? (useFallback ? fallback?.affectedAreas : undefined) ?? [],
    preserveAreas: asStringArray(record.preserve_areas) ?? (useFallback ? fallback?.preserveAreas : undefined) ?? [],
    firstMigrationStep:
      asString(record.first_migration_step) ?? (useFallback ? fallback?.firstMigrationStep : undefined) ?? '',
    migrationSequence:
      asStringArray(record.migration_sequence) ?? (useFallback ? fallback?.migrationSequence : undefined) ?? [],
    validationCheckpoints:
      asStringArray(record.validation_checkpoints) ??
      (useFallback ? fallback?.validationCheckpoints : undefined) ??
      [],
    rollbackNotes: asStringArray(record.rollback_notes) ?? (useFallback ? fallback?.rollbackNotes : undefined) ?? [],
  } satisfies ProjectAdaptationGuideView;
}

function mapPrincipleNote(
  value: unknown,
  fallback: BootstrapData['principleNotes'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['principleNotes'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const record = asRecord(value);
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? emptyLivePrincipleNotes() : fallback;
  }
  const useFallback = !workspaceChanged;
  return {
    currentPrinciple: asString(record.current_principle) ?? (useFallback ? fallback?.currentPrinciple : undefined) ?? '',
    whyItMatters:
      asString(record.why_it_matters) ??
      asString(record.why_this_approach) ??
      (useFallback ? fallback?.whyItMatters : undefined) ??
      '',
    commonMistake:
      asString(record.common_mistake) ??
      asString(record.common_wrong_intuition) ??
      (useFallback ? fallback?.commonMistake : undefined) ??
      '',
    applyNow:
      asString(record.apply_now) ??
      asString(record.follow_up_exercise) ??
      (useFallback ? fallback?.applyNow : undefined) ??
      '',
    transferTargets:
      asStringArray(record.transfer_targets) ??
      asStringArray(record.related_checks) ??
      (useFallback ? fallback?.transferTargets : undefined) ??
      [],
    concreteAnchor: asString(record.concrete_anchor) ?? (useFallback ? fallback?.concreteAnchor : undefined) ?? '',
    transferableLesson:
      asString(record.transferable_lesson) ??
      asString(record.transfer_lesson) ??
      (useFallback ? fallback?.transferableLesson : undefined),
    relatedChecks: asStringArray(record.related_checks) ?? (useFallback ? fallback?.relatedChecks : undefined),
    sourceAssetTitle: asString(record.source_asset_title) ?? (useFallback ? fallback?.sourceAssetTitle : undefined),
  } satisfies PrincipleNoteView;
}

function mapCoachTurn(
  value: unknown,
  reply: UnknownRecord | undefined,
  fallback: BootstrapData['coachTurn'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['coachTurn'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const direct = asRecord(value);
  const metadata = asRecord(reply?.metadata);
  const nested = asRecord(metadata?.coach_turn);
  const record = direct ?? nested;
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? emptyLiveCoachTurn() : fallback;
  }
  const useFallback = !workspaceChanged;

  return {
    scenario: toCoachingScenario(asString(record.scenario)),
    learnerSignal: toLearnerSignal(asString(record.learner_signal)),
    summary: coachSurfaceText(record.summary) ?? (useFallback ? fallback?.summary : undefined) ?? '',
    nextStep: coachSurfaceText(record.next_step) ?? (useFallback ? fallback?.nextStep : undefined) ?? '',
    encouragement: coachSurfaceText(record.encouragement) ?? (useFallback ? fallback?.encouragement : undefined),
    interventionStrategy:
      coachSurfaceText(record.intervention_strategy) ??
      (useFallback ? fallback?.interventionStrategy : undefined),
    teachingGoal: coachSurfaceText(record.teaching_goal) ?? (useFallback ? fallback?.teachingGoal : undefined),
    resumeThread: coachSurfaceText(record.resume_thread) ?? (useFallback ? fallback?.resumeThread : undefined),
    decision: asString(record.decision) ?? (useFallback ? fallback?.decision : undefined),
    blocker: coachSurfaceText(record.blocker) ?? (useFallback ? fallback?.blocker : undefined),
    teachingNote: coachSurfaceText(record.teaching_note) ?? (useFallback ? fallback?.teachingNote : undefined),
    confidence: asString(record.confidence) ?? (useFallback ? fallback?.confidence : undefined),
    evidence: asStringArray(record.evidence) ?? (useFallback ? fallback?.evidence : undefined),
    supportStrategy:
      coachSurfaceText(record.support_strategy) ?? (useFallback ? fallback?.supportStrategy : undefined),
    decisionReason: asString(record.decision_reason) ?? (useFallback ? fallback?.decisionReason : undefined),
    tone: toTone(asString(record.tone)),
    verbosityBias: toVerbosityBias(asString(record.verbosity_bias)),
    activeStage: asString(record.active_stage) ?? (useFallback ? fallback?.activeStage : undefined),
    activeTask: asString(record.active_task) ?? (useFallback ? fallback?.activeTask : undefined),
    dueReviewCount: asNumber(record.due_review_count) ?? (useFallback ? fallback?.dueReviewCount : undefined),
    reviewQueueSummary:
      coachSurfaceText(record.review_queue_summary) ?? (useFallback ? fallback?.reviewQueueSummary : undefined),
    failingChecks: asStringArray(record.failing_checks) ?? (useFallback ? fallback?.failingChecks : undefined),
    artifactKinds: mapArtifactKinds(record.artifact_kinds) ?? (useFallback ? fallback?.artifactKinds : undefined),
    suggestedActionTypes:
      mapSuggestedActionTypes(record.suggested_action_types) ??
      (useFallback ? fallback?.suggestedActionTypes : undefined),
    backgroundMode:
      asString(record.background_mode) === 'embedded'
        ? 'embedded'
        : useFallback
          ? fallback?.backgroundMode
          : undefined,
  };
}

function mapProjectSources(
  value: unknown,
  fallback: BootstrapData['projectSources'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['projectSources'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const envelope = asRecord(value);
  if (
    envelope &&
    !Array.isArray(value) &&
    incomingWorkspaceId &&
    !trainingRecordMatchesWorkspace(envelope, incomingWorkspaceId)
  ) {
    return workspaceChanged ? [] : fallback;
  }
  const items = Array.isArray(value) ? value : envelope?.sources;
  if (!Array.isArray(items)) {
    return workspaceChanged ? [] : fallback;
  }
  return items
    .map((item) => {
      const record = asRecord(item);
      if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
        return undefined;
      }
      const title = asString(record.title);
      if (!title) {
        return undefined;
      }
      return {
        title,
        sourceKind:
          asString(record.source_kind) === 'reference_impl' ||
          asString(record.source_kind) === 'training_repo'
            ? (asString(record.source_kind) as ProjectSourceSuggestion['sourceKind'])
            : 'reference_repo',
        repoHint: asString(record.repo_hint) ?? '',
        fitReason: asString(record.fit_reason) ?? '',
        trainingValue: asString(record.training_value) ?? '',
        firstFilter: asString(record.first_filter) ?? '',
        firstTask: asString(record.first_task) ?? '',
        caution: asString(record.caution) ?? '',
        tags: asStringArray(record.tags) ?? [],
        sourceUrl: asString(record.source_url) ?? '',
        retrievedAt: asString(record.retrieved_at) ?? '',
        trustScore: asNumber(record.trust_score) ?? 0,
        qualityFlags: asStringArray(record.quality_flags) ?? [],
      } satisfies ProjectSourceSuggestion;
    })
    .filter((item): item is ProjectSourceSuggestion => item !== undefined);
}

function mapCoachOrientation(
  value: unknown,
  fallback: BootstrapData['coachOrientation'],
): BootstrapData['coachOrientation'] {
  const record = asRecord(value);
  return (
    normalizeCoachOrientationRecord(value) ??
    normalizeCoachOrientationRecord(record?.coach_orientation) ??
    normalizeCoachOrientationRecord(record?.coachOrientation) ??
    normalizeCoachOrientationRecord(record?.latest_coach_orientation) ??
    normalizeCoachOrientationRecord(record?.latestCoachOrientation) ??
    fallback
  );
}

function mapCoachFocus(
  value: unknown,
  reply: UnknownRecord | undefined,
  fallback: BootstrapData['coachFocus'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['coachFocus'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  const metadata = asRecord(reply?.metadata);
  const record = asRecord(value) ?? asRecord(metadata?.coach_focus);
  if (!record || (incomingWorkspaceId && !trainingRecordMatchesWorkspace(record, incomingWorkspaceId))) {
    return workspaceChanged ? emptyLiveCoachFocus() : fallback;
  }
  const useFallback = !workspaceChanged;

  return {
    currentFocus: asString(record.current_focus) ?? (useFallback ? fallback?.currentFocus : undefined),
    reviewRhythm: asString(record.review_rhythm) ?? (useFallback ? fallback?.reviewRhythm : undefined),
    nextStep: asString(record.next_step) ?? (useFallback ? fallback?.nextStep : undefined),
    activeStage: asString(record.active_stage) ?? (useFallback ? fallback?.activeStage : undefined),
    activeTask: asString(record.active_task) ?? (useFallback ? fallback?.activeTask : undefined),
    scenario: toCoachingScenario(asString(record.scenario)),
    relationshipStage:
      asString(record.relationship_stage) === 'active'
        ? 'active'
        : asString(record.relationship_stage) === 'intake'
          ? 'intake'
          : useFallback
            ? fallback?.relationshipStage
            : undefined,
    firstTurnPriority:
      asString(record.first_turn_priority) ?? (useFallback ? fallback?.firstTurnPriority : undefined),
    strategyPreferenceSummary:
      asString(record.strategy_preference_summary) ??
      (useFallback ? fallback?.strategyPreferenceSummary : undefined),
    continuitySummary:
      asString(record.continuity_summary) ?? (useFallback ? fallback?.continuitySummary : undefined),
    recentTeachingSignals:
      asStringArray(record.recent_teaching_signals) ??
      (useFallback ? fallback?.recentTeachingSignals : undefined),
    teachingObservations:
      asStringArray(record.teaching_observations) ??
      (useFallback ? fallback?.teachingObservations : undefined),
    recentWins: asStringArray(record.recent_wins) ?? (useFallback ? fallback?.recentWins : undefined),
    dueReviewCount: asNumber(record.due_review_count) ?? (useFallback ? fallback?.dueReviewCount : undefined),
    language: asString(record.language) ?? (useFallback ? fallback?.language : undefined),
    pressureBlocksLiveObjectMint:
      asBoolean(record.pressure_blocks_live_object_mint) === true ||
      asBoolean(record.pressureBlocksLiveObjectMint) === true
        ? true
        : useFallback
          ? fallback?.pressureBlocksLiveObjectMint
          : undefined,
    streakBlocksLiveObjectMint:
      asBoolean(record.streak_blocks_live_object_mint) === true ||
      asBoolean(record.streakBlocksLiveObjectMint) === true
        ? true
        : useFallback
          ? fallback?.streakBlocksLiveObjectMint
          : undefined,
    closedLoopReturnBlocksTaskMint:
      asBoolean(record.closed_loop_return_blocks_task_mint) === true ||
      asBoolean(record.closedLoopReturnBlocksTaskMint) === true
        ? true
        : useFallback
          ? fallback?.closedLoopReturnBlocksTaskMint
          : undefined,
  };
}

function mapResources(
  value: unknown,
  fallback: ResourceRecordView[],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): ResourceRecordView[] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  if (!Array.isArray(value)) {
    return workspaceChanged ? [] : fallback;
  }
  const incoming = incomingWorkspaceId
    ? selectResourcesForScope(value, { workspaceId: incomingWorkspaceId })
    : value;
  return incoming
    .map((item) => mapResource(item))
    .filter((item): item is ResourceRecordView => item !== undefined);
}

function mapResource(value: unknown): ResourceRecordView | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const parseStatus = asText(record.parse_status) ?? asText(record.parseStatus);
  const indexStatus = asText(record.index_status) ?? asText(record.indexStatus);
  let status = asResourceStatus(asText(record.status)) ?? 'ready';
  if (parseStatus === 'failed' || indexStatus === 'failed') {
    status = 'attention';
  } else if (parseStatus || indexStatus) {
    status = parseStatus === 'parsed' && indexStatus === 'indexed' ? 'ready' : 'indexing';
  }
  const freshness = asText(record.freshness);
  const trustScore = asNumber(record.trust_score) ?? asNumber(record.trustScore);
  const qualityFlags = asStringArray(record.quality_flags ?? record.qualityFlags);
  const trustState =
    asText(record.trust_state) ??
    asText(record.trustState) ??
    (trustScore !== undefined || freshness !== undefined || qualityFlags !== undefined
      ? deriveResourceTrustState({ trustScore, freshness, qualityFlags })
      : undefined);
  return {
    id: asText(record.id) ?? asText(record.resource_id) ?? asText(record.resourceId) ?? 'resource',
    title:
      asText(record.name) ??
      asText(record.title) ??
      asText(record.resource_title) ??
      asText(record.resourceTitle) ??
      '资源',
    kind:
      asResourceKind(asText(record.kind)) ??
      asResourceKind(asText(record.file_kind)) ??
      asResourceKind(asText(record.fileKind)) ??
      'text',
    status,
    summary: asText(record.summary) ?? asText(record.match_summary) ?? asText(record.matchSummary) ?? '',
    source: asText(record.source) ?? asText(record.path),
    collectionPath: asText(record.collection_path) ?? asText(record.collectionPath),
    collectionRoot: asText(record.collection_root) ?? asText(record.collectionRoot),
    canonicalSource: asText(record.canonical_source) ?? asText(record.canonicalSource),
    sourceItems: asStringArray(record.source_items ?? record.sourceItems),
    tags: asStringArray(record.tags),
    warnings: asStringArray(record.warnings),
    sourceType: asText(record.source_type) ?? asText(record.sourceType),
    fileType: asText(record.file_type) ?? asText(record.fileType),
    projectScope: asText(record.project_scope) ?? asText(record.projectScope),
    trustState,
    trustScore,
    freshness:
      freshness === 'fresh' || freshness === 'stale' || freshness === 'unknown' ? freshness : undefined,
    indexState: asText(record.index_state) ?? asText(record.indexState) ?? indexStatus,
    citationId: asText(record.citation_id) ?? asText(record.citationId),
    previewTier: asPreviewTier(asText(record.preview_tier) ?? asText(record.previewTier)),
    previewKind: asText(record.preview_kind) ?? asText(record.previewKind),
    rankScore: asNumber(record.rank_score) ?? asNumber(record.rankScore),
    rankReasons: asStringArray(record.rank_reasons ?? record.rankReasons),
    matchSummary: asText(record.match_summary) ?? asText(record.matchSummary),
    canInjectTrainingCard:
      asBoolean(record.can_inject_training_card) ?? asBoolean(record.canInjectTrainingCard),
    qualityFlags,
    sandboxPath: asText(record.sandbox_path) ?? asText(record.sandboxPath),
    sandboxOrigin: asText(record.sandbox_origin) ?? asText(record.sandboxOrigin),
    sandboxSyncedAt: asText(record.sandbox_synced_at) ?? asText(record.sandboxSyncedAt),
    sandboxDirty: asBoolean(record.sandbox_dirty) ?? asBoolean(record.sandboxDirty),
    extractedArtifactPath:
      asText(record.extracted_artifact_path) ?? asText(record.extractedArtifactPath),
    updatedAt: asText(record.updated_at) ?? asText(record.updatedAt),
  };
}

function mapDeletedResource(
  value: unknown,
): NonNullable<BootstrapData['deletedResources']>[number] | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const resourceId = asText(record.resource_id) ?? asText(record.resourceId);
  const title =
    asText(record.title) ??
    asText(record.resource_title) ??
    asText(record.resourceTitle) ??
    asText(record.name);
  if (!resourceId || !title) {
    return undefined;
  }
  return {
    resourceId,
    title,
    deletedAt: asText(record.deleted_at) ?? asText(record.deletedAt),
    collectionPath: asText(record.collection_path) ?? asText(record.collectionPath),
    recoverable: asBoolean(record.recoverable) ?? false,
  };
}

function mergeDefinedResourceFields(
  existing: ResourceRecordView,
  incoming: ResourceRecordView,
): ResourceRecordView {
  return {
    ...existing,
    ...Object.fromEntries(Object.entries(incoming).filter(([, value]) => value !== undefined)),
  } as ResourceRecordView;
}

function mapConversation(
  value: unknown,
  fallback: BootstrapData['conversation'],
  incomingWorkspaceId?: string,
  previousWorkspaceId?: string,
): BootstrapData['conversation'] {
  const workspaceChanged = workspaceIdsChanged(incomingWorkspaceId, previousWorkspaceId);
  if (!Array.isArray(value) || value.length === 0) {
    return workspaceChanged ? [] : fallback;
  }
  return value.map((item, index) => {
    const record = asRecord(item);
    const role = asString(record?.role) === 'user' ? 'user' : 'assistant';
    const metadata = asRecord(record?.metadata);
    return {
      id: asString(record?.id) ?? `message-${index + 1}`,
      role,
      author: role === 'user' ? '你' : 'Trainer',
      body: asString(record?.content) ?? '',
      timestamp: formatTimestamp(asString(record?.timestamp)),
      sourceView: normalizeConversationSourceView(metadata?.active_view),
      parts: mapConversationParts(metadata),
      attachments: mapConversationAttachments(metadata),
      artifacts: mapConversationArtifacts(metadata),
      contextNote: asString(metadata?.context_note),
      support: mapConversationSupport(metadata),
    };
  });
}

function normalizeConversationSourceView(
  value: unknown,
): ConversationMessageView['sourceView'] | undefined {
  const normalized = asString(value);
  return normalized === 'coach' ||
    normalized === 'plan' ||
    normalized === 'resources' ||
    normalized === 'training' ||
    normalized === 'settings'
    ? normalized
    : undefined;
}

function mapSuggestedActions(
  value: unknown,
  fallback: SuggestedActionView[],
): SuggestedActionView[] {
  if (!Array.isArray(value) || value.length === 0) {
    return fallback;
  }

  return value
    .map<SuggestedActionView | undefined>((item, index) => {
      const record = asRecord(item);
      const label = typeof item === 'string' ? item : asString(record?.label);
      if (!label) {
        return undefined;
      }
      const rawAction = asString(record?.action);
      const action =
        rawAction === 'plan' ||
        rawAction === 'next_task' ||
        rawAction === 'review' ||
        rawAction === 'hint' ||
        rawAction === 'retry_review' ||
        rawAction === 'task'
          ? rawAction
          : inferSuggestedAction(label);
      const artifactKind = asString(record?.artifact_kind);
      return {
        id: asString(record?.id) ?? `suggested-${index + 1}`,
        label,
        action,
        rationale: asString(record?.rationale),
        artifactKind: artifactKind ? toArtifactKind(artifactKind) : undefined,
        prompt: asString(record?.prompt),
        focusArea: asString(record?.focus_area),
      } satisfies SuggestedActionView;
    })
    .filter((item): item is SuggestedActionView => item !== undefined);
}

function createConversationMessage(
  role: 'user' | 'assistant',
  author: string,
  body: string,
) {
  return {
    id: `${role}-${Date.now()}`,
    role,
    author,
    body,
    timestamp: formatTimestamp(new Date().toISOString()),
  };
}

function mapConversationAttachments(
  metadata: UnknownRecord | undefined,
): ConversationAttachmentView[] | undefined {
  if (!metadata) {
    return undefined;
  }

  const language = asString(metadata.response_language);
  const attachments: ConversationAttachmentView[] = [];
  const intent = asString(metadata.intent);
  const answerMode = asString(metadata.answer_mode);
  const strategy = asString(metadata.content_strategy);

  pushAttachment(attachments, attachmentLabel('intent', language), attachmentValue('intent', intent, language));
  pushAttachment(attachments, attachmentLabel('mode', language), attachmentValue('mode', answerMode, language));
  pushAttachment(attachments, attachmentLabel('strategy', language), attachmentValue('strategy', strategy, language));
  pushAttachment(attachments, attachmentLabel('selection', language), asString(metadata.selection_range));

  const currentFile = asString(metadata.current_file);
  if (currentFile) {
    pushAttachment(
      attachments,
      attachmentLabel('file', language),
      path.posix.basename(currentFile.replace(/\\/g, '/')),
    );
  }

  const diagnosticsCount = asNumber(metadata.diagnostics_count);
  if (typeof diagnosticsCount === 'number' && diagnosticsCount > 0) {
    pushAttachment(attachments, attachmentLabel('diagnostics', language), String(diagnosticsCount));
  }

  const relatedFiles = Array.isArray(metadata.related_files) ? metadata.related_files : [];
  const relatedTitles = relatedFiles
    .map((item) => asRecord(item))
    .map((item) => asString(item?.path))
    .filter((value): value is string => Boolean(value));
  if (relatedTitles.length > 0) {
    pushAttachment(
      attachments,
      attachmentLabel('related', language),
      relatedTitles.slice(0, 2).map(toBaseName).join(', '),
    );
    pushAttachment(attachments, attachmentLabel('relatedCount', language), String(relatedFiles.length));
  }

  return attachments.length > 0 ? attachments : undefined;
}

function mapConversationArtifacts(
  metadata: UnknownRecord | undefined,
): ConversationArtifactView[] | undefined {
  if (!metadata || !Array.isArray(metadata.artifacts)) {
    return undefined;
  }

  const artifacts = metadata.artifacts
    .map((item) => asRecord(item))
    .filter((item): item is UnknownRecord => Boolean(item))
    .map<ConversationArtifactView>((item) => ({
      kind: toArtifactKind(asString(item.kind)),
      title: asString(item.title) ?? 'Artifact',
      summary: asString(item.summary),
      content: asString(item.content),
      bullets: asStringArray(item.bullets)?.slice(0, 3),
      teaser: asString(item.teaser),
      recommendedAction: toSuggestedAction(asString(item.recommended_action)),
      rationale: asString(item.rationale),
      focusArea: asString(item.focus_area),
      verification: asStringArray(item.verification)?.slice(0, 3),
      metadata: asRecord(item.metadata) ?? undefined,
    }))
    .filter((artifact) => Boolean(artifact.kind && artifact.title));

  return artifacts.length > 0 ? artifacts : undefined;
}

function mapConversationParts(
  metadata: UnknownRecord | undefined,
): ConversationMessageView['parts'] | undefined {
  if (!metadata) {
    return undefined;
  }
  return normalizeTrainerMessageParts(metadata.parts);
}

function mapConversationSupport(
  metadata: UnknownRecord | undefined,
): ConversationMessageView['support'] | undefined {
  if (!metadata) {
    return undefined;
  }

  const support = asRecord(metadata.support);
  if (!support) {
    return undefined;
  }

  const preview = asString(support.preview);
  const lines = asStringArray(support.lines)?.slice(0, 6);
  if (!preview && (!lines || lines.length === 0)) {
    return undefined;
  }

  return {
    preview: preview ?? undefined,
    lines,
  };
}

function mapArtifactKinds(value: unknown): ConversationArtifactView['kind'][] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  return value.map((item) => toArtifactKind(asString(item))).filter(Boolean);
}

function mapSuggestedActionTypes(value: unknown): SuggestedActionView['action'][] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  return value.map((item) => toSuggestedAction(asString(item))).filter(Boolean) as SuggestedActionView['action'][];
}

function pushAttachment(
  attachments: ConversationAttachmentView[],
  label: string,
  value: string | undefined,
): void {
  const normalized = truncateText(value, 48);
  if (!normalized) {
    return;
  }
  attachments.push({ label, value: normalized });
}

function attachmentLabel(
  key:
    | 'intent'
    | 'mode'
    | 'language'
    | 'strategy'
    | 'window'
    | 'file'
    | 'selection'
    | 'diagnostics'
    | 'recentEdits'
    | 'recentFiles'
    | 'related'
    | 'relatedCount'
    | 'artifacts',
  responseLanguage: string | undefined,
): string {
  if (!prefersChinese(responseLanguage)) {
    return {
      intent: 'Intent',
      mode: 'Mode',
      language: 'Lang',
      strategy: 'Strategy',
      window: 'Window',
      file: 'File',
      selection: 'Selection',
      diagnostics: 'Diagnostics',
      recentEdits: 'Recent edits',
      recentFiles: 'Recent files',
      related: 'Related',
      relatedCount: 'Related count',
      artifacts: 'Artifacts',
    }[key];
  }

  return {
    intent: '意图',
    mode: '方式',
    language: '语言',
    strategy: '策略',
    window: '范围',
    file: '文件',
    selection: '选区',
    diagnostics: '诊断',
    recentEdits: '最近修改',
    recentFiles: '最近打开',
    related: '相关文件',
    relatedCount: '相关数量',
    artifacts: '产物',
  }[key];
}

function attachmentValue(
  key: 'intent' | 'mode' | 'strategy',
  value: string | undefined,
  responseLanguage: string | undefined,
): string | undefined {
  if (!value || !prefersChinese(responseLanguage)) {
    return value;
  }

  if (key === 'intent') {
    return {
      coach: '教练',
      plan: '计划',
      task: '任务',
      review: '评审',
      next_task: '下一题',
    }[value] ?? value;
  }

  if (key === 'mode') {
    return {
      auto: '自动',
      'coach-first': '引导',
      balanced: '平衡',
      direct: '直接',
      guided: '引导',
    }[value] ?? value;
  }

  return {
    'selection-window': '围绕选区',
    'head-window': '文件开头',
    'wide-window': '较大窗口',
    'full-file': '完整文件',
  }[value] ?? value;
}

function prefersChinese(responseLanguage: string | undefined): boolean {
  return Boolean(responseLanguage && responseLanguage.toLowerCase().startsWith('zh'));
}

function toBaseName(value: string): string {
  const normalized = value.replace(/\\/g, '/');
  return path.posix.basename(normalized) || value;
}

function toArtifactKind(value: string | undefined): ConversationArtifactView['kind'] {
  if (
    value === 'task' ||
    value === 'plan' ||
    value === 'evaluation' ||
    value === 'idea_implementation' ||
    value === 'project_idea' ||
    value === 'project_adaptation' ||
    value === 'principle' ||
    value === 'review' ||
    value === 'plan_update' ||
    value === 'next_step'
  ) {
    return value;
  }
  return 'note';
}

function toReviewSource(value: string | undefined): BootstrapData['memory']['dueReviews'][number]['source'] {
  if (value === 'mastery' || value === 'reflection' || value === 'plan') {
    return value;
  }
  return 'weakness';
}

function toReviewSeverity(value: string | undefined): BootstrapData['memory']['dueReviews'][number]['severity'] {
  if (value === 'high' || value === 'medium') {
    return value;
  }
  return 'low';
}

function toReviewSurfaceMode(
  value: string | undefined,
): BootstrapData['memory']['dueReviews'][number]['surfaceMode'] {
  if (value === 'due' || value === 'ahead' || value === 'digest') {
    return value;
  }
  return undefined;
}

function toLinkedContext(value: unknown): string[] | undefined {
  const items = Array.isArray(value)
    ? value.map((item) => asString(item)).filter((item): item is string => Boolean(item))
    : typeof value === 'string'
      ? [value]
      : [];
  return items.length > 0 ? items : undefined;
}

function toCoachingScenario(
  value: string | undefined,
): NonNullable<BootstrapData['coachingState']>['scenario'] {
  if (
    value === 'onboarding' ||
    value === 'idea_implementation' ||
    value === 'project_idea' ||
    value === 'project_adaptation' ||
    value === 'project_sourcing' ||
    value === 'principle' ||
    value === 'review' ||
    value === 'plan' ||
    value === 'task' ||
    value === 'next_task'
  ) {
    return value;
  }
  return 'general';
}

function toCoachingMode(
  value: string | undefined,
): NonNullable<BootstrapData['coachingState']>['answerMode'] {
  if (value === 'balanced' || value === 'direct') {
    return value;
  }
  return 'guided';
}

function toTeachingMode(
  value: string | undefined,
): NonNullable<BootstrapData['teachingDecision']>['mode'] {
  if (
    value === 'onboarding' ||
    value === 'idea_implementation' ||
    value === 'project_idea_mining' ||
    value === 'project_adaptation' ||
    value === 'planning' ||
    value === 'concept_teaching' ||
    value === 'engineering_challenge' ||
    value === 'review_reflection' ||
    value === 'project_sourcing' ||
    value === 'principle_explanation' ||
    value === 'scaffold' ||
    value === 'balanced' ||
    value === 'direct_rescue' ||
    value === 'challenge' ||
    value === 'reflection'
  ) {
    return value;
  }
  return 'guided';
}

function toLearnerSignal(
  value: string | undefined,
): NonNullable<BootstrapData['coachingState']>['learnerSignal'] {
  if (value === 'blocked' || value === 'uncertain' || value === 'curious') {
    return value;
  }
  return 'steady';
}

function toToneProfile(
  value: string | undefined,
): NonNullable<BootstrapData['teachingDecision']>['toneProfile'] {
  if (
    value === 'guided_build' ||
    value === 'proactive_coach' ||
    value === 'steady_migration' ||
    value === 'teaching_clarity' ||
    value === 'review_loop' ||
    value === 'concise_rescue'
  ) {
    return value;
  }
  return 'steady';
}

function toTone(
  value: string | undefined,
): NonNullable<BootstrapData['toneDecision']>['tone'] {
  if (
    value === 'encouraging' ||
    value === 'concise_rescue' ||
    value === 'reflective'
  ) {
    return value;
  }
  return 'steady';
}

function toVerbosityBias(
  value: string | undefined,
): NonNullable<BootstrapData['toneDecision']>['verbosityBias'] {
  if (value === 'short' || value === 'expanded') {
    return value;
  }
  return 'medium';
}

function toUrgencyLevel(
  value: string | undefined,
): NonNullable<BootstrapData['affectState']>['urgencyLevel'] {
  if (value === 'low' || value === 'high') {
    return value;
  }
  return 'medium';
}

function toProjectIdeaKind(
  value: string | undefined,
): ProjectIdeaView['ideaKind'] {
  if (
    value === 'refactor' ||
    value === 'test' ||
    value === 'architecture' ||
    value === 'developer_experience'
  ) {
    return value;
  }
  return 'feature';
}

function toFirstLookFolderRole(
  value: string | undefined,
): FirstLookSummaryView['folderRole'] {
  if (
    value === 'empty_new_project' ||
    value === 'existing_engineering' ||
    value === 'algorithm_model' ||
    value === 'idea_scratchpad' ||
    value === 'learning_materials' ||
    value === 'mixed_uncertain'
  ) {
    return value;
  }
  return 'mixed_uncertain';
}

function toProjectTypeGuess(
  value: string | undefined,
): FirstLookSummaryView['projectTypeGuess'] {
  if (
    value === 'web_app' ||
    value === 'api_service' ||
    value === 'cli_tool' ||
    value === 'library_package' ||
    value === 'ml_model' ||
    value === 'notebook_research' ||
    value === 'mobile_app' ||
    value === 'desktop_app' ||
    value === 'embedded_iot' ||
    value === 'data_pipeline' ||
    value === 'monorepo' ||
    value === 'documentation' ||
    value === 'game' ||
    value === 'config_dotfiles' ||
    value === 'unknown'
  ) {
    return value;
  }
  return 'unknown';
}

function inferSuggestedAction(label: string): SuggestedActionView['action'] {
  const normalized = label.toLowerCase();
  if (normalized.includes('plan') || normalized.includes('计划')) {
    return 'plan';
  }
  if (normalized.includes('next task') || normalized.includes('下一题')) {
    return 'next_task';
  }
  if (normalized.includes('review') || normalized.includes('评审')) {
    return normalized.includes('again') || normalized.includes('重新') ? 'retry_review' : 'review';
  }
  if (normalized.includes('hint') || normalized.includes('提示')) {
    return 'hint';
  }
  if (normalized.includes('修') || normalized.includes('fix')) {
    return 'review';
  }
  if (normalized.includes('task') || normalized.includes('任务')) {
    return 'task';
  }
  return 'task';
}

function toSuggestedAction(value: string | undefined): SuggestedActionView['action'] | undefined {
  if (
    value === 'plan' ||
    value === 'next_task' ||
    value === 'review' ||
    value === 'hint' ||
    value === 'retry_review' ||
    value === 'task'
  ) {
    return value;
  }
  return undefined;
}

function toAnswerPolicy(value: string | undefined): UserProfileView['answerPolicy'] {
  if (value === 'auto') {
    return 'auto';
  }
  if (value === 'direct') {
    return 'direct';
  }
  if (value === 'balanced') {
    return 'balanced';
  }
  if (value === 'coach-first') {
    return 'coach-first';
  }
  return 'auto';
}

function toComposerLanguage(value: string | undefined): ComposerLanguage | undefined {
  return isComposerLanguage(value) ? value : undefined;
}

function toContextDetail(
  value: string | undefined,
): 'focused' | 'balanced' | 'full' | undefined {
  if (value === 'focused' || value === 'balanced' || value === 'full') {
    return value;
  }
  return undefined;
}

function toMemoryScope(
  value: string | undefined,
): 'project' | 'personal' | 'session' | undefined {
  if (value === 'project' || value === 'personal' || value === 'session') {
    return value;
  }
  return undefined;
}

function toWorkingSetMode(
  value: string | undefined,
): 'focused' | 'balanced' | 'broad' | undefined {
  if (value === 'focused' || value === 'balanced' || value === 'broad') {
    return value;
  }
  return undefined;
}

function toReviewCadence(
  value: string | undefined,
): 'light' | 'steady' | 'active' | undefined {
  if (value === 'light' || value === 'steady' || value === 'active') {
    return value;
  }
  return undefined;
}

function toReviewReminderMode(
  value: string | undefined,
): 'due' | 'ahead' | 'digest' | undefined {
  if (value === 'due' || value === 'ahead' || value === 'digest') {
    return value;
  }
  return undefined;
}

function formatTimestamp(value: string | undefined): string {
  if (!value) {
    return '刚刚';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function truncateText(value: string | undefined, maxLength = 160): string | undefined {
  if (!value) {
    return undefined;
  }

  const normalized = value.replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1)}…`;
}

function asRecord(value: unknown): UnknownRecord | undefined {
  return value && typeof value === 'object' ? (value as UnknownRecord) : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function asText(value: unknown): string | undefined {
  const text = asString(value)?.trim();
  return text && text.length > 0 ? text : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' ? value : undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

function asStringArray(value: unknown): string[] | undefined {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : undefined;
}

function asRecordArray(value: unknown): UnknownRecord[] | undefined {
  return Array.isArray(value)
    ? value.filter((item): item is UnknownRecord => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    : undefined;
}

function asResourceKind(value: string | undefined): ResourceDetailRecordView['kind'] | undefined {
  if (
    value === 'pdf' ||
    value === 'image' ||
    value === 'markdown' ||
    value === 'text' ||
    value === 'code' ||
    value === 'url'
  ) {
    return value;
  }
  return undefined;
}

function asResourceStatus(value: string | undefined): ResourceDetailRecordView['status'] | undefined {
  if (value === 'ready' || value === 'indexing' || value === 'attention') {
    return value;
  }
  return undefined;
}

function asPreviewTier(
  value: string | undefined,
): ResourceDetailRecordView['previewTier'] | undefined {
  if (value === 'rich' || value === 'converted' || value === 'metadata') {
    return value;
  }
  return undefined;
}

function toTrainingConversationCandidateType(
  value: string | undefined,
): TrainingHandoffStateView['candidateType'] {
  if (
    value === 'project_context_candidate' ||
    value === 'resource_import_candidate' ||
    value === 'evidence_candidate' ||
    value === 'flash_candidate' ||
    value === 'practice_candidate' ||
    value === 'coach_visible_status' ||
    value === 'micro_drill_prompt' ||
    value === 'card_invocation'
  ) {
    return value;
  }
  return undefined;
}

function toTrainingCardType(
  value: string | undefined,
): TrainingCardCandidateStateView['type'] | undefined {
  if (value === 'practice' || value === 'flash') {
    return value;
  }
  return undefined;
}

function toTrainingLearningPhase(
  value: string | undefined,
): TrainingHandoffStateView['learningPhase'] {
  if (
    value === 'learn' ||
    value === 'try' ||
    value === 'verify' ||
    value === 'reflect' ||
    value === 'return'
  ) {
    return value;
  }
  return undefined;
}

function toTrainingContinueIn(
  value: string | undefined,
): TrainingHandoffStateView['continueIn'] {
  if (
    value === 'chat' ||
    value === 'training' ||
    value === 'plan' ||
    value === 'resources' ||
    value === 'none'
  ) {
    return value;
  }
  return undefined;
}

function toTrainingNextHopCandidateType(
  value: string | undefined,
): TrainingNextHopStateView['candidateType'] {
  if (
    value === 'evidence_candidate' ||
    value === 'flash_candidate' ||
    value === 'practice_candidate'
  ) {
    return value;
  }
  return undefined;
}

function toTrainingProjectScope(
  value: string | undefined,
): TrainingNextHopStateView['projectScope'] {
  if (
    value === 'global' ||
    value === 'current_project' ||
    value === 'project_subplan' ||
    value === 'sandbox' ||
    value === 'unknown'
  ) {
    return value;
  }
  return undefined;
}

function toTrainingNextHopContinueIn(
  value: string | undefined,
): TrainingNextHopStateView['continueIn'] {
  if (value === 'chat' || value === 'training' || value === 'plan') {
    return value;
  }
  return undefined;
}

function toTrainingNextHopStatus(
  value: string | undefined,
): TrainingNextHopStateView['status'] {
  if (
    value === 'created' ||
    value === 'surfaced' ||
    value === 'accepted' ||
    value === 'continued_in_chat' ||
    value === 'verification_required' ||
    value === 'reflection_required' ||
    value === 'return_required' ||
    value === 'dismissed' ||
    value === 'deferred' ||
    value === 'blocked' ||
    value === 'expired' ||
    value === 'archived'
  ) {
    return value;
  }
  return undefined;
}

function toTrainingReturnMode(
  value: string | undefined,
): TrainingHandoffStateView['returnMode'] {
  if (
    value === 'result' ||
    value === 'blocker' ||
    value === 'verification_required' ||
    value === 'reflection_required' ||
    value === 'return_required'
  ) {
    return value;
  }
  return undefined;
}
