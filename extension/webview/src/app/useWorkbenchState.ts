import { create } from "zustand";

import { trainerCommands } from "../../../../shared/src/commands";
import { sanitizeErrorSurfaceText } from "../../../../shared/src/errorSurfaceSanitizer";
import { stripProviderSnapshotSecrets } from "../../../../shared/src/hostLastTestGovernance";
import { formalPlanIdentityIsLive } from "../../../../shared/src/workspaceRecoveryGovernance";
import {
  createEmptyTrainerStreamingState,
  deriveTrainerStreamingOperationMessage,
  normalizeTrainerStreamingState,
  upsertTrainerToolActivity,
  type TrainerOperationMessage,
  type TrainerToolActivity,
} from "../../../../shared/src/protocol";
import {
  mapStreamStatusToReliabilityPhase,
  normalizeOperationReliabilityOutcome,
  normalizeOperationReliabilityPhase,
} from "../../../../shared/src/operationReliabilityGovernance";
import { createNeutralBootstrapData } from "../lib/neutralBootstrap";
import {
  sanitizeVisibleData,
  sanitizeVisibleText,
  splitSafeVisibleStreamText,
} from "../lib/visibleText";
import {
  getInjectedBootstrapState,
  getPersistedState,
  inVsCodeWebview,
  postMessage,
  setPersistedState,
} from "../lib/vscode";
import { normalizeSidebarView } from "../lib/types";
import type {
  ActiveWorkbenchView,
  BootstrapData,
  ComposerLanguage,
  CoachDefaults,
  LearningSurfaceAlignment,
  HostMessage,
  PersistedWorkbenchState,
  StageMaterialItem,
  TeachingStyle,
  ThemePreference,
} from "../lib/types";
import { normalizeTeachingStyle } from "../lib/types";

type WorkbenchMemoryState = BootstrapData["memory"] & {
  memoryEvidence: string[];
};

type WorkbenchBootstrapState = Omit<BootstrapData, "memory"> & {
  memory: WorkbenchMemoryState;
  // Keep an empty fallback plan from being presented as a saved learning plan.
  hasFormalPlan: boolean;
};

type WorkbenchBootstrapInput = Omit<Partial<BootstrapData>, "plan"> & {
  hasFormalPlan?: boolean;
  plan?: BootstrapData["plan"] | null;
};

const persisted = getPersistedState();
const injectedBootstrap =
  getInjectedBootstrapState<WorkbenchBootstrapInput>() ??
  buildNeutralBootstrapData();
const initialData = normalizeBootstrapData(injectedBootstrap);

const defaultPersistedState: PersistedWorkbenchState = {
  themePreference: inVsCodeWebview() ? "system" : "dark",
  learningSurfaceAlignment: "left",
  activeView: "coach",
  composerLanguage:
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("zh")
      ? "zh-CN"
      : "en-US",
  composerAnswerMode: "auto",
  teachingStyle: "auto",
  resourceSearchMode: "lexical",
  includeCurrentFile: true,
  includeSelection: true,
  includeDiagnostics: true,
  includeRelatedFiles: true,
  contextDetail: "balanced",
  followCurrentFile: true,
  coachDefaults: {
    memoryScope: "project",
    workingSetMode: "balanced",
    reviewCadence: "steady",
    reviewReminderMode: "due",
    workspaceMemoryToggles: {
      decisions: true,
      patterns: true,
      resources: true,
    },
  },
  composerDraft: "",
};

const initialUi: PersistedWorkbenchState = {
  ...defaultPersistedState,
  ...persisted,
  composerDraft: sanitizeVisibleText(persisted?.composerDraft).trim(),
  learningSurfaceAlignment: persisted?.learningSurfaceAlignment === "right" ? "right" : "left",
  activeView: normalizeSidebarView(persisted?.activeView),
};

function buildNeutralBootstrapData(): WorkbenchBootstrapState {
  return {
    ...createNeutralBootstrapData(inVsCodeWebview() ? "starting" : "offline"),
    hasFormalPlan: false,
  };
}

function normalizeBootstrapData(
  value: WorkbenchBootstrapInput | undefined,
  fallbackState: WorkbenchBootstrapState = buildNeutralBootstrapData(),
): WorkbenchBootstrapState {
  const fallback = fallbackState;
  const source = sanitizeVisibleData(value ?? {}) as WorkbenchBootstrapInput;
  const workspaceSettings = source.memory?.workspace;
  const fallbackWorkspaceSettings = fallback.memory.workspace;
  const fallbackMemoryEvidence =
    "memoryEvidence" in fallback.memory && Array.isArray(fallback.memory.memoryEvidence)
      ? fallback.memory.memoryEvidence.filter((item): item is string => typeof item === "string")
      : [];
  const memoryEvidence = Array.isArray(source.memory?.memoryEvidence)
    ? source.memory.memoryEvidence.filter((item): item is string => typeof item === "string")
    : fallbackMemoryEvidence;
  const hasFormalPlan =
    source.plan === null
      ? false
      : source.plan !== undefined
        ? formalPlanIdentityIsLive(source.plan)
        : typeof source.hasFormalPlan === "boolean"
          ? source.hasFormalPlan
          : fallback.hasFormalPlan;

  return {
    ...fallback,
    ...source,
    workspaceTrainingState:
      source.workspaceTrainingState ?? fallback.workspaceTrainingState,
    connection: {
      ...fallback.connection,
      ...(source.connection ?? {}),
      state:
        source.connection?.state === "connected" ||
        source.connection?.state === "starting" ||
        source.connection?.state === "offline"
          ? source.connection.state
          : fallback.connection.state,
      provider: {
        ...fallback.connection.provider,
        ...(source.connection?.provider ?? {}),
        protocol:
          source.connection?.provider?.protocol ??
          source.providerConfig?.protocol ??
          fallback.connection.provider.protocol,
        protocolFamily:
          source.connection?.provider?.protocolFamily ??
          source.providerConfig?.protocolFamily ??
          fallback.connection.provider.protocolFamily,
        capabilities: {
          ...fallback.connection.provider.capabilities,
          ...(source.connection?.provider?.capabilities ?? {}),
        },
      },
    },
    providerConfig: {
      ...fallback.providerConfig,
      ...(source.providerConfig ?? {}),
      capabilities: {
        ...fallback.providerConfig.capabilities,
        ...(source.providerConfig?.capabilities ?? {}),
      },
    },
    liveContext: {
      ...fallback.liveContext,
      ...(source.liveContext ?? {}),
      recentFiles: source.liveContext?.recentFiles ?? fallback.liveContext.recentFiles,
      recentEditedFiles:
        source.liveContext?.recentEditedFiles ?? fallback.liveContext.recentEditedFiles,
      relatedFiles: source.liveContext?.relatedFiles ?? fallback.liveContext.relatedFiles,
    },
    profile: {
      ...fallback.profile,
      ...(source.profile ?? {}),
      goals: source.profile?.goals ?? fallback.profile.goals,
      focusAreas: source.profile?.focusAreas ?? fallback.profile.focusAreas,
    },
    plan: {
      ...fallback.plan,
      ...(source.plan ?? {}),
      stages: source.plan?.stages ?? fallback.plan.stages,
    },
    hasFormalPlan,
    task: {
      ...fallback.task,
      ...(source.task ?? {}),
      constraints: source.task?.constraints ?? fallback.task.constraints,
      acceptanceCriteria:
        source.task?.acceptanceCriteria ?? fallback.task.acceptanceCriteria,
    },
    evaluation: {
      ...fallback.evaluation,
      ...(source.evaluation ?? {}),
      checks: source.evaluation?.checks ?? fallback.evaluation.checks,
    },
    memory: {
      ...fallback.memory,
      ...(source.memory ?? {}),
      weakSpots: source.memory?.weakSpots ?? fallback.memory.weakSpots,
      recentWins: source.memory?.recentWins ?? fallback.memory.recentWins,
      dueReviews: source.memory?.dueReviews ?? fallback.memory.dueReviews,
      teachingObservations:
        source.memory?.teachingObservations ?? fallback.memory.teachingObservations,
      lowestMasteryConcepts:
        source.memory?.lowestMasteryConcepts ?? fallback.memory.lowestMasteryConcepts,
      activeThread: source.memory?.activeThread ?? fallback.memory.activeThread,
      memoryEvidence,
      memoryShareGrants:
        source.memory?.memoryShareGrants ?? fallback.memory.memoryShareGrants ?? [],
      workspace: workspaceSettings
        ? {
            ...(fallbackWorkspaceSettings ?? {}),
            ...workspaceSettings,
            coachDefaults: workspaceSettings.coachDefaults
              ? {
                  ...(fallbackWorkspaceSettings?.coachDefaults ?? {}),
                  ...workspaceSettings.coachDefaults,
                  workspaceMemoryToggles: workspaceSettings.coachDefaults
                    .workspaceMemoryToggles
                    ? {
                        ...(fallbackWorkspaceSettings?.coachDefaults
                          ?.workspaceMemoryToggles ?? {}),
                        ...workspaceSettings.coachDefaults.workspaceMemoryToggles,
                      }
                    : fallbackWorkspaceSettings?.coachDefaults?.workspaceMemoryToggles,
                }
              : fallbackWorkspaceSettings?.coachDefaults,
          }
        : source.memory?.workspace ?? fallback.memory.workspace,
    },
    conversation: Array.isArray(source.conversation)
      ? source.conversation
      : fallback.conversation,
    resources: Array.isArray(source.resources) ? source.resources : fallback.resources,
    suggestedActions: Array.isArray(source.suggestedActions)
      ? source.suggestedActions
      : fallback.suggestedActions,
    commands: Array.isArray(source.commands) ? source.commands : fallback.commands,
    projectIdeas: source.projectIdeas ?? fallback.projectIdeas,
    stageMaterials: source.stageMaterials ?? fallback.stageMaterials,
  };
}

export type AgentToolActivity = TrainerToolActivity;
export type StreamingState = ReturnType<typeof normalizeTrainerStreamingState> & {
  pendingVisibleContent?: string;
  hasRejectedVisibleContent?: boolean;
};
type OperationMessage = TrainerOperationMessage;

export interface ResourceRestoreContext {
  surface: "detail" | "sandbox";
  resourceId?: string;
  focusArea?: string;
  sandboxPath?: string;
  previewPath?: string;
  summary?: string;
}

export interface TrainingRestoreContext {
  target?: "theory_drill" | "scenario_lab" | "review_artifact" | "next_hop";
  theoryDrillId?: string;
  scenarioLabId?: string;
  reviewArtifactId?: string;
}

export interface WorkbenchStore {
  data: WorkbenchBootstrapState;
  layout: PersistedWorkbenchState;
  /** Local language intent remains visible until the host echoes the same value. */
  pendingComposerLanguage?: ComposerLanguage;
  operationMessage?: OperationMessage;
  streaming: StreamingState;
  resourceOrganizationPending?: { pending: true; operationCount?: number };
  resourceRestoreContext?: ResourceRestoreContext;
  trainingRestoreContext?: TrainingRestoreContext;
  hasReceivedHostState: boolean;
  /** Generated stage learning materials keyed by plan stage id. */
  stageMaterials: Record<string, StageMaterialItem[]>;
  /** Per-stage generation in-flight flags (optimistic, cleared on host response). */
  stageMaterialGenerating: Record<string, boolean>;
  setThemePreference: (theme: ThemePreference) => void;
  setLearningSurfaceAlignment: (alignment: LearningSurfaceAlignment) => void;
  setActiveView: (view: ActiveWorkbenchView) => void;
  setResourceRestoreContext: (context?: ResourceRestoreContext) => void;
  setComposerLanguage: (language: ComposerLanguage) => void;
  setComposerAnswerMode: (mode: "auto" | "coach-first" | "balanced" | "direct") => void;
  setTeachingStyle: (style: TeachingStyle) => void;
  setIncludeCurrentFile: (enabled: boolean) => void;
  setIncludeSelection: (enabled: boolean) => void;
  setIncludeDiagnostics: (enabled: boolean) => void;
  setIncludeRelatedFiles: (enabled: boolean) => void;
  setContextDetail: (detail: "focused" | "balanced" | "full") => void;
  setFollowCurrentFile: (enabled: boolean) => void;
  setCoachDefaults: (defaults: Partial<CoachDefaults>) => void;
  setComposerDraft: (draft: string) => void;
  setOperationMessage: (message?: OperationMessage) => void;
  patchData: (patch: WorkbenchBootstrapInput) => void;
  applyHostMessage: (message: HostMessage) => void;
  requestStageMaterialGeneration: (planId: string, stageId: string) => void;
  applyStageMaterials: (stageId: string, materials: StageMaterialItem[]) => void;
  setStageMaterialGenerating: (stageId: string, busy: boolean) => void;
  startStream: (messageId: string) => void;
  appendChunk: (chunk: string) => void;
  endStream: () => void;
  resetStream: () => void;
}

function persistLayout(next: PersistedWorkbenchState): PersistedWorkbenchState {
  setPersistedState(next);
  return next;
}

function freshStreamingState(): StreamingState {
  return createEmptyTrainerStreamingState();
}

function isCurrentStreamEvent(streaming: StreamingState, messageId: string | undefined): boolean {
  return messageId === undefined || messageId === streaming.streamMessageId;
}

function sameOperationMessage(left?: OperationMessage, right?: OperationMessage): boolean {
  if (!left || !right) {
    return left === right;
  }
  return left.tone === right.tone && left.message === right.message;
}

function deriveRecoveredStreamingOperationMessage(
  language: ComposerLanguage,
  nextStreaming: StreamingState,
): OperationMessage | undefined {
  return deriveTrainerStreamingOperationMessage(language, nextStreaming);
}

function adoptRecoveredStreamingOperationMessage(
  language: ComposerLanguage,
  nextStreaming: StreamingState,
  currentOperationMessage?: OperationMessage,
  currentStreaming?: StreamingState,
): OperationMessage | undefined {
  const nextRecovered = deriveRecoveredStreamingOperationMessage(language, nextStreaming);
  if (!currentOperationMessage) {
    return nextRecovered;
  }
  const currentRecovered = deriveRecoveredStreamingOperationMessage(
    language,
    currentStreaming ?? freshStreamingState(),
  );
  return sameOperationMessage(currentOperationMessage, currentRecovered)
    ? nextRecovered
    : currentOperationMessage;
}

function prefersChinese(language: ComposerLanguage): boolean {
  return language === "zh-CN";
}

function localizeUi(language: ComposerLanguage, english: string, chinese: string): string {
  return prefersChinese(language) ? chinese : english;
}

function unreadableVisibleText(language: ComposerLanguage): string {
  return localizeUi(
    language,
    "This content could not be shown clearly.",
    "\u8fd9\u6bb5\u5185\u5bb9\u6ca1\u6709\u663e\u793a\u6e05\u695a\u3002",
  );
}

function streamEncodingRecoveryText(language: ComposerLanguage): string {
  return localizeUi(
    language,
    "Part of this reply could not be shown clearly. Please retry this message.",
    "这次回复有一部分显示异常，请重新发送这条消息。",
  );
}

function appendSafeStreamContent(
  streaming: StreamingState,
  chunk: string,
): Pick<
  StreamingState,
  "streamedContent" | "pendingVisibleContent" | "hasRejectedVisibleContent"
> {
  if (streaming.hasRejectedVisibleContent) {
    return {
      streamedContent: streaming.streamedContent,
      pendingVisibleContent: undefined,
      hasRejectedVisibleContent: true,
    };
  }
  const split = splitSafeVisibleStreamText(streaming.pendingVisibleContent ?? "", chunk);
  return {
    streamedContent: streaming.streamedContent + split.visible,
    pendingVisibleContent: split.pending || undefined,
    hasRejectedVisibleContent: split.rejected || undefined,
  };
}

function mergeBootstrapPatch(
  current: WorkbenchBootstrapState,
  patch: WorkbenchBootstrapInput,
): WorkbenchBootstrapInput {
  const hasPlanPatch = Object.prototype.hasOwnProperty.call(patch, "plan");
  return {
    ...current,
    ...patch,
    hasFormalPlan: hasPlanPatch
      ? formalPlanIdentityIsLive(patch.plan)
      : patch.hasFormalPlan ?? current.hasFormalPlan,
  };
}

function mergeStageMaterials(
  current: Record<string, StageMaterialItem[]>,
  incoming: Record<string, StageMaterialItem[]> | undefined,
): Record<string, StageMaterialItem[]> {
  if (!incoming) {
    return current;
  }
  const merged: Record<string, StageMaterialItem[]> = { ...current };
  for (const [stageId, materials] of Object.entries(incoming)) {
    if (Array.isArray(materials)) {
      merged[stageId] = materials;
    }
  }
  return merged;
}

function clearStageMaterialGenerating(
  current: Record<string, boolean>,
  settledStageIds: ReadonlySet<string>,
): Record<string, boolean> {
  const next: Record<string, boolean> = {};
  let changed = false;
  for (const [stageId, busy] of Object.entries(current)) {
    if (settledStageIds.has(stageId)) {
      changed = true;
      continue;
    }
    next[stageId] = busy;
  }
  return changed ? next : current;
}

function finishSafeStreamContent(
  streaming: StreamingState,
): Pick<
  StreamingState,
  "streamedContent" | "pendingVisibleContent" | "hasRejectedVisibleContent"
> {
  return {
    streamedContent:
      streaming.streamedContent + sanitizeVisibleText(streaming.pendingVisibleContent ?? ""),
    pendingVisibleContent: undefined,
    hasRejectedVisibleContent: undefined,
  };
}

function visibleCompletionText(value: unknown): string | undefined {
  const normalized = sanitizeVisibleText(value).trim();
  return normalized || undefined;
}

function buildStreamCompletionMessage(
  language: ComposerLanguage,
  payload: {
    tokens: number;
    agentic?: boolean;
    summary?: string;
    nextStep?: string;
    toolCount?: number;
  },
): string {
  const summary = payload.summary?.trim();
  const nextStep = payload.nextStep?.trim();
  if (summary && nextStep) {
    return localizeUi(
      language,
      `${summary} Next: ${nextStep}`,
      `本轮收口：${summary} 下一步：${nextStep}`,
    );
  }
  if (summary) {
    return localizeUi(language, `Coach loop closed: ${summary}`, `本轮教练收口：${summary}`);
  }
  if (nextStep) {
    return localizeUi(language, `Next step: ${nextStep}`, `下一步：${nextStep}`);
  }
  if (payload.agentic) {
    const toolCount = typeof payload.toolCount === "number" ? payload.toolCount : 0;
    return toolCount > 0
      ? localizeUi(
          language,
          `Coach loop completed after ${toolCount} tool step${toolCount === 1 ? "" : "s"}.`,
          `教练回合已完成，共执行 ${toolCount} 个工具步骤。`,
        )
      : localizeUi(language, "Coach loop completed.", "教练回合已完成。");
  }
  return localizeUi(
    language,
    `Stream completed (${payload.tokens} tokens)`,
    `流式回复已完成（${payload.tokens} tokens）。`,
  );
}

function workspaceChromeAllowsLeftoverFill(
  incomingWorkspaceId: string | undefined,
  previousWorkspaceId: string | undefined,
): boolean {
  if (!incomingWorkspaceId) {
    return true;
  }
  return Boolean(previousWorkspaceId) && incomingWorkspaceId === previousWorkspaceId;
}

function resolveComposerLanguage(
  incomingLanguage: ComposerLanguage | undefined,
  fallbackLanguage: ComposerLanguage,
  pendingLanguage?: ComposerLanguage,
): ComposerLanguage {
  if (pendingLanguage !== undefined && incomingLanguage !== pendingLanguage) {
    return pendingLanguage;
  }
  return incomingLanguage ?? fallbackLanguage;
}

function reconcilePendingComposerLanguage(
  pendingLanguage: ComposerLanguage | undefined,
  incomingLanguage: ComposerLanguage | undefined,
): ComposerLanguage | undefined {
  if (pendingLanguage === undefined || incomingLanguage === pendingLanguage) {
    return undefined;
  }
  return pendingLanguage;
}

function workspaceIdentityChanged(
  incomingWorkspaceId: string | undefined,
  previousWorkspaceId: string | undefined,
): boolean {
  const incomingId = incomingWorkspaceId?.trim() ?? "";
  const previousId = previousWorkspaceId?.trim() ?? "";
  return Boolean(incomingId && previousId && incomingId !== previousId);
}

function syncLayoutFromBootstrap(
  layout: PersistedWorkbenchState,
  data: BootstrapData,
  previousWorkspaceId?: string,
  pendingComposerLanguage?: ComposerLanguage,
): PersistedWorkbenchState {
  const workspace = data.memory.workspace;
  const leftoverFill = workspaceChromeAllowsLeftoverFill(
    workspace?.workspaceId,
    previousWorkspaceId,
  );
  const layoutChrome = leftoverFill ? layout : defaultPersistedState;
  const nextLanguage = resolveComposerLanguage(
    workspace?.responseLanguage,
    layoutChrome.composerLanguage,
    pendingComposerLanguage,
  );
  const nextAnswerMode = workspace?.answerMode ?? layoutChrome.composerAnswerMode;
  const nextResourceSearchMode = workspace?.resourceSearchMode ?? layoutChrome.resourceSearchMode;
  const nextTeachingStyle = data.profile?.preferredStyle?.trim()
    ? normalizeTeachingStyle(data.profile.preferredStyle)
    : layout.teachingStyle;
  const nextFollowCurrentFile = workspace?.followCurrentFile ?? layoutChrome.followCurrentFile;
  const nextContextDetail = workspace?.contextDetail ?? layoutChrome.contextDetail;
  const nextIncludeCurrentFile = workspace?.includeCurrentFile ?? layoutChrome.includeCurrentFile;
  const nextIncludeSelection = workspace?.includeSelection ?? layoutChrome.includeSelection;
  const nextIncludeDiagnostics = workspace?.includeDiagnostics ?? layoutChrome.includeDiagnostics;
  const nextIncludeRelatedFiles = workspace?.includeRelatedFiles ?? layoutChrome.includeRelatedFiles;
  const nextCoachDefaults = workspace?.coachDefaults
    ? {
        ...layoutChrome.coachDefaults,
        ...workspace.coachDefaults,
        workspaceMemoryToggles: workspace.coachDefaults.workspaceMemoryToggles
          ? {
              ...layoutChrome.coachDefaults.workspaceMemoryToggles,
              ...workspace.coachDefaults.workspaceMemoryToggles,
            }
          : layoutChrome.coachDefaults.workspaceMemoryToggles,
      }
    : layoutChrome.coachDefaults;

  const nextLayout: PersistedWorkbenchState = {
    ...layout,
    composerLanguage: nextLanguage,
    composerAnswerMode: nextAnswerMode,
    resourceSearchMode: nextResourceSearchMode,
    teachingStyle: nextTeachingStyle,
    followCurrentFile: nextFollowCurrentFile,
    contextDetail: nextContextDetail,
    includeCurrentFile: nextIncludeCurrentFile,
    includeSelection: nextIncludeSelection,
    includeDiagnostics: nextIncludeDiagnostics,
    includeRelatedFiles: nextIncludeRelatedFiles,
    coachDefaults: nextCoachDefaults,
    previewProviderConfig: stripProviderSnapshotSecrets(data.providerConfig),
  };
  return persistLayout(nextLayout);
}

export const useWorkbenchState = create<WorkbenchStore>((set, get) => ({
  data: initialData,
  layout: initialUi,
  pendingComposerLanguage: undefined,
  operationMessage: deriveRecoveredStreamingOperationMessage(
    initialUi.composerLanguage,
    normalizeTrainerStreamingState(initialData.streamingState),
  ),
  streaming: normalizeTrainerStreamingState(initialData.streamingState),
  resourceOrganizationPending: undefined,
  resourceRestoreContext: undefined,
  trainingRestoreContext: undefined,
  hasReceivedHostState: !inVsCodeWebview(),
  stageMaterials: initialData.stageMaterials ?? {},
  stageMaterialGenerating: {},
  setThemePreference: (themePreference) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        themePreference,
      }),
    })),
  setLearningSurfaceAlignment: (learningSurfaceAlignment) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        learningSurfaceAlignment,
      }),
    })),
  setActiveView: (activeView) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        activeView: normalizeSidebarView(activeView),
      }),
    })),
  setResourceRestoreContext: (resourceRestoreContext) => set({ resourceRestoreContext }),
  setComposerLanguage: (composerLanguage) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        composerLanguage,
      }),
      pendingComposerLanguage: composerLanguage,
    })),
  setComposerAnswerMode: (composerAnswerMode) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        composerAnswerMode,
      }),
    })),
  setTeachingStyle: (teachingStyle) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        teachingStyle,
      }),
    })),
  setIncludeCurrentFile: (includeCurrentFile) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        includeCurrentFile,
      }),
    })),
  setIncludeSelection: (includeSelection) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        includeSelection,
      }),
    })),
  setIncludeDiagnostics: (includeDiagnostics) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        includeDiagnostics,
      }),
    })),
  setIncludeRelatedFiles: (includeRelatedFiles) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        includeRelatedFiles,
      }),
    })),
  setContextDetail: (contextDetail) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        contextDetail,
      }),
    })),
  setFollowCurrentFile: (followCurrentFile) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        followCurrentFile,
      }),
    })),
  setCoachDefaults: (coachDefaults) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        coachDefaults: {
          ...state.layout.coachDefaults,
          ...coachDefaults,
          workspaceMemoryToggles: coachDefaults.workspaceMemoryToggles
            ? {
                ...state.layout.coachDefaults.workspaceMemoryToggles,
                ...coachDefaults.workspaceMemoryToggles,
              }
            : state.layout.coachDefaults.workspaceMemoryToggles,
        },
      }),
    })),
  setComposerDraft: (composerDraft) =>
    set((state) => ({
      layout: persistLayout({
        ...state.layout,
        composerDraft,
      }),
    })),
  setOperationMessage: (operationMessage) => set({ operationMessage }),
  patchData: (patch) =>
    set((state) => {
      const nextData = normalizeBootstrapData(mergeBootstrapPatch(state.data, patch));
      const nextStreaming =
        patch.streamingState !== undefined
          ? normalizeTrainerStreamingState(nextData.streamingState)
          : state.streaming;
      return {
        data: nextData,
        streaming: nextStreaming,
        operationMessage:
          patch.streamingState !== undefined
            ? adoptRecoveredStreamingOperationMessage(
                state.layout.composerLanguage,
                nextStreaming,
                state.operationMessage,
                state.streaming,
              )
            : state.operationMessage,
      };
    }),
  applyHostMessage: (message) =>
    set((state) => {
      if (message.type === "bootstrap") {
        const nextData = normalizeBootstrapData(message.payload as WorkbenchBootstrapInput);
        const previousWorkspaceId = state.data.memory.workspace?.workspaceId;
        const incomingWorkspaceId = nextData.memory.workspace?.workspaceId;
        const effectiveWorkspaceId = incomingWorkspaceId ?? previousWorkspaceId;
        const scopedPendingComposerLanguage = workspaceIdentityChanged(
          effectiveWorkspaceId,
          previousWorkspaceId,
        )
          ? undefined
          : state.pendingComposerLanguage;
        const nextLayout = syncLayoutFromBootstrap(
          state.layout,
          nextData,
          previousWorkspaceId,
          scopedPendingComposerLanguage,
        );
        const nextPendingComposerLanguage = reconcilePendingComposerLanguage(
          scopedPendingComposerLanguage,
          nextData.memory.workspace?.responseLanguage,
        );
        const restoredNextHop =
          state.trainingRestoreContext?.target === "next_hop"
            ? state.data.workspaceTrainingState?.latestTrainingNextHop
            : undefined;
        const restoredTargetId = restoredNextHop?.targetId ?? restoredNextHop?.candidateId;
        const incomingTrainingState = nextData.workspaceTrainingState;
        const shouldPreserveRestoredNextHop = Boolean(
          nextLayout.activeView === "training" &&
            restoredNextHop &&
            !incomingTrainingState?.latestTrainingNextHop &&
            (!incomingTrainingState?.selectedCardId ||
              !restoredTargetId ||
              incomingTrainingState.selectedCardId === restoredTargetId),
        );
        const resolvedData = shouldPreserveRestoredNextHop
          ? normalizeBootstrapData({
              ...nextData,
              workspaceTrainingState: {
                ...(incomingTrainingState ?? {}),
                latestTrainingNextHop: restoredNextHop,
                selectedCardId:
                  restoredTargetId ??
                  incomingTrainingState?.selectedCardId ??
                  state.data.workspaceTrainingState?.selectedCardId,
                selectedCardType:
                  restoredNextHop?.cardType ??
                  incomingTrainingState?.selectedCardType ??
                  state.data.workspaceTrainingState?.selectedCardType,
                selectedCardTitle:
                  restoredNextHop?.cardTitle ??
                  restoredNextHop?.title ??
                  incomingTrainingState?.selectedCardTitle ??
                  state.data.workspaceTrainingState?.selectedCardTitle,
                selectedCardStatus:
                  incomingTrainingState?.selectedCardStatus ??
                  state.data.workspaceTrainingState?.selectedCardStatus,
              },
            })
          : nextData;
        const nextStreaming = normalizeTrainerStreamingState(resolvedData.streamingState);
        return {
          data: resolvedData,
          layout: nextLayout,
          pendingComposerLanguage: nextPendingComposerLanguage,
          streaming: nextStreaming,
          // A full bootstrap replaces session state; stage materials follow the host truth.
          stageMaterials: resolvedData.stageMaterials ?? {},
          stageMaterialGenerating: {},
          resourceRestoreContext: state.resourceRestoreContext,
          trainingRestoreContext: state.trainingRestoreContext,
          operationMessage: adoptRecoveredStreamingOperationMessage(
            nextLayout.composerLanguage,
            nextStreaming,
            state.operationMessage,
            state.streaming,
          ),
          hasReceivedHostState: true,
        };
      }

      if (message.type === "state/patch") {
        const nextData = normalizeBootstrapData(
          mergeBootstrapPatch(state.data, message.payload as WorkbenchBootstrapInput),
        );
        const previousWorkspaceId = state.data.memory.workspace?.workspaceId;
        const incomingWorkspaceId = nextData.memory.workspace?.workspaceId;
        const effectiveWorkspaceId = incomingWorkspaceId ?? previousWorkspaceId;
        const scopedPendingComposerLanguage = workspaceIdentityChanged(
          effectiveWorkspaceId,
          previousWorkspaceId,
        )
          ? undefined
          : state.pendingComposerLanguage;
        const nextLayout = syncLayoutFromBootstrap(
          state.layout,
          nextData,
          previousWorkspaceId,
          scopedPendingComposerLanguage,
        );
        const nextPendingComposerLanguage = reconcilePendingComposerLanguage(
          scopedPendingComposerLanguage,
          nextData.memory.workspace?.responseLanguage,
        );
        const nextStreaming = normalizeTrainerStreamingState(nextData.streamingState);
        const patchedStageMaterials = message.payload.stageMaterials;
        const settledStageIds = new Set(
          patchedStageMaterials !== undefined ? Object.keys(patchedStageMaterials) : [],
        );
        return {
          data: nextData,
          layout: nextLayout,
          pendingComposerLanguage: nextPendingComposerLanguage,
          streaming: nextStreaming,
          stageMaterials: mergeStageMaterials(state.stageMaterials, patchedStageMaterials),
          stageMaterialGenerating: clearStageMaterialGenerating(
            state.stageMaterialGenerating,
            settledStageIds,
          ),
          operationMessage: adoptRecoveredStreamingOperationMessage(
            nextLayout.composerLanguage,
            nextStreaming,
            state.operationMessage,
            state.streaming,
          ),
          hasReceivedHostState: true,
        };
      }

      if (message.type === "stream/start") {
        if (
          state.streaming.isStreaming &&
          state.streaming.streamMessageId !== message.payload.messageId
        ) {
          return {};
        }
        return {
          streaming: {
            ...freshStreamingState(),
            isStreaming: true,
            streamMessageId: message.payload.messageId,
            reliabilityPhase: "pending",
          },
          operationMessage: undefined,
        };
      }

      if (message.type === "stream/chunk") {
        if (!isCurrentStreamEvent(state.streaming, message.payload.messageId)) {
          return {};
        }
        const safeContent = appendSafeStreamContent(state.streaming, message.payload.chunk);
        const hasNewEncodingIssue = Boolean(
          safeContent.hasRejectedVisibleContent && !state.streaming.hasRejectedVisibleContent,
        );
        const recoveryMessage = hasNewEncodingIssue
          ? streamEncodingRecoveryText(state.layout.composerLanguage)
          : undefined;
        return {
          streaming: {
            ...state.streaming,
            ...safeContent,
            streamError: recoveryMessage ?? state.streaming.streamError,
          },
          operationMessage: recoveryMessage
            ? {
                tone: "error",
                message: recoveryMessage,
              }
            : state.operationMessage,
        };
      }

      if (message.type === "stream/tool_call") {
        if (!isCurrentStreamEvent(state.streaming, message.payload.messageId)) {
          return {};
        }
        const safeToolName =
          sanitizeVisibleText(message.payload.name).trim() ||
          (state.layout.composerLanguage === "zh-CN" ? "工具操作" : "Tool action");
        const next = upsertTrainerToolActivity(state.streaming.agentActivity, {
          id: message.payload.id,
          name: safeToolName,
          status: "running",
          args:
            message.payload.arguments &&
            typeof message.payload.arguments === "object" &&
            !Array.isArray(message.payload.arguments)
              ? sanitizeVisibleData(message.payload.arguments as Record<string, unknown>)
              : undefined,
          step: message.payload.step,
        });
        return {
          streaming: {
            ...state.streaming,
            agentActivity: next,
          },
        };
      }

      if (message.type === "stream/tool_result") {
        if (!isCurrentStreamEvent(state.streaming, message.payload.messageId)) {
          return {};
        }
        const safeToolName =
          sanitizeVisibleText(message.payload.name).trim() ||
          (state.layout.composerLanguage === "zh-CN" ? "工具操作" : "Tool action");
        const next = upsertTrainerToolActivity(state.streaming.agentActivity, {
          id: message.payload.id,
          name: safeToolName,
          status: message.payload.ok ? "succeeded" : "failed",
          result: sanitizeVisibleData(message.payload.result),
          step: message.payload.step,
        });
        return {
          streaming: {
            ...state.streaming,
            agentActivity: next,
          },
        };
      }

      if (message.type === "stream/step") {
        if (!isCurrentStreamEvent(state.streaming, message.payload.messageId)) {
          return {};
        }
        return {
          streaming: {
            ...state.streaming,
            agentStep: message.payload.index,
          },
        };
      }

      if (message.type === "resourceOrganization/pending") {
        return {
          resourceOrganizationPending: message.payload.pending
            ? {
                pending: true as const,
                operationCount:
                  typeof message.payload.operationCount === "number"
                    ? message.payload.operationCount
                    : undefined,
              }
            : undefined,
        };
      }

      if (message.type === "stream/complete") {
        // Apply complete through isStreaming for the current streamMessageId —
        // owner/waiter first complete must reach pending→acked even while the
        // streaming flag is still true. Stale other messageIds stay ignored.
        if (!isCurrentStreamEvent(state.streaming, message.payload.messageId)) {
          return {};
        }
        // Owner already applied this streamMessageId — ignore waiter/replay duplicate complete.
        if (
          !state.streaming.isStreaming &&
          state.streaming.streamMessageId &&
          state.streaming.reliabilityPhase === "acked"
        ) {
          return {};
        }
        const language = state.layout.composerLanguage;
        const hadEncodingIssue = Boolean(state.streaming.hasRejectedVisibleContent);
        const completedContent = finishSafeStreamContent(state.streaming);
        const summary = visibleCompletionText(message.payload.summary);
        const nextStep = visibleCompletionText(message.payload.nextStep);
        const stopReason = visibleCompletionText(message.payload.stopReason);
        const toolCount =
          typeof message.payload.toolCount === "number"
            ? message.payload.toolCount
            : state.streaming.agentActivity.length > 0
              ? state.streaming.agentActivity.length
              : undefined;
        const nextStreaming = {
          ...state.streaming,
          ...completedContent,
          isStreaming: false,
          completionSummary: summary,
          completionNextStep: nextStep,
          completionStopReason: stopReason,
          toolCount,
          agentic: message.payload.agentic,
          streamError: hadEncodingIssue
            ? streamEncodingRecoveryText(language)
            : state.streaming.streamError,
          reliabilityPhase:
            normalizeOperationReliabilityPhase(message.payload.reliabilityPhase) ?? "acked",
          reliabilityOutcome:
            normalizeOperationReliabilityOutcome(message.payload.reliabilityOutcome) ??
            (hadEncodingIssue ? "failure" : "success"),
        };
        return {
          streaming: nextStreaming,
          operationMessage: hadEncodingIssue
            ? {
                tone: "error",
                message: streamEncodingRecoveryText(language),
              }
            : deriveTrainerStreamingOperationMessage(language, nextStreaming, {
                completionTokens: message.payload.tokens,
              }),
        };
      }

      if (message.type === "stream/error") {
        if (!isCurrentStreamEvent(state.streaming, message.payload.messageId)) {
          return {};
        }
        const language = state.layout.composerLanguage;
        const nextStreaming = {
          ...state.streaming,
          isStreaming: false,
          pendingVisibleContent: undefined,
          streamError: sanitizeErrorSurfaceText(
            sanitizeVisibleText(message.payload.error, unreadableVisibleText(language)),
            language,
          ),
          reliabilityPhase:
            normalizeOperationReliabilityPhase(message.payload.reliabilityPhase) ?? "acked",
          reliabilityOutcome:
            normalizeOperationReliabilityOutcome(message.payload.reliabilityOutcome) ?? "failure",
        };
        return {
          streaming: nextStreaming,
          operationMessage: deriveTrainerStreamingOperationMessage(language, nextStreaming, {
            errorCategory: message.payload.category,
          }),
        };
      }

      if (message.type === "stream/cancelled") {
        if (!isCurrentStreamEvent(state.streaming, message.payload.messageId)) {
          return {};
        }
        const cancelledMessage =
          state.layout.composerLanguage === "zh-CN"
            ? "已取消本轮回复，已保留已生成内容。"
            : "This reply was cancelled. The generated content is still here.";
        return {
          streaming: {
            ...state.streaming,
            isStreaming: false,
            pendingVisibleContent: undefined,
            streamError: undefined,
            completionStopReason: "cancelled",
            // Fail-closed: authoritative ack is failure, not silent success. Draft untouched.
            reliabilityPhase: "acked",
            reliabilityOutcome: "failure",
          },
          operationMessage: {
            tone: "info",
            message: cancelledMessage,
          },
        };
      }

      if (message.type === "operation/status") {
        const reliabilityPhase = mapStreamStatusToReliabilityPhase(message.payload.phase);
        return {
          streaming: reliabilityPhase
            ? {
                ...state.streaming,
                reliabilityPhase,
                reliabilityOutcome:
                  reliabilityPhase === "failed"
                    ? "failure"
                    : reliabilityPhase === "cancelled"
                      ? "cancelled"
                      : state.streaming.reliabilityOutcome,
              }
            : state.streaming,
          operationMessage: {
            ...message.payload,
            message: sanitizeErrorSurfaceText(
              sanitizeVisibleText(
                message.payload.message,
                unreadableVisibleText(state.layout.composerLanguage),
              ),
              state.layout.composerLanguage,
            ),
          },
          // Stage material generation failures arrive as error statuses; never leave
          // an optimistic in-flight spinner stuck after the host reports a failure.
          stageMaterialGenerating:
            message.payload.tone === "error" ? {} : state.stageMaterialGenerating,
        };
      }

      if (message.type === "ui/restoreView") {
        const payload = sanitizeVisibleData(message.payload);
        const requestedView =
          typeof payload.activeView === "string"
            ? normalizeSidebarView(payload.activeView)
            : state.layout.activeView;
        const restoredNextHop = payload.latestTrainingNextHop;
        const restoredTrainingState =
          requestedView === "training"
            ? {
                ...state.data.workspaceTrainingState,
                latestTrainingSubmode:
                  payload.trainingSubmode ??
                  state.data.workspaceTrainingState?.latestTrainingSubmode,
                latestLearningFocusArea:
                  payload.focusArea ??
                  state.data.workspaceTrainingState?.latestLearningFocusArea,
                latestTrainingNextHop:
                  restoredNextHop ?? state.data.workspaceTrainingState?.latestTrainingNextHop,
                selectedCardId:
                  restoredNextHop?.targetId ?? state.data.workspaceTrainingState?.selectedCardId,
                selectedCardType:
                  restoredNextHop?.cardType ??
                  state.data.workspaceTrainingState?.selectedCardType ??
                  "practice",
                selectedCardTitle:
                  restoredNextHop?.cardTitle ??
                  restoredNextHop?.title ??
                  state.data.workspaceTrainingState?.selectedCardTitle,
                selectedCardStatus:
                  state.data.workspaceTrainingState?.selectedCardStatus ?? "active",
              }
            : state.data.workspaceTrainingState;
        const trainingRestoreContext =
          requestedView === "training" &&
          (payload.trainingRestoreTarget || restoredNextHop)
            ? {
                target:
                  payload.trainingRestoreTarget ??
                  (restoredNextHop ? "next_hop" : undefined),
                theoryDrillId: payload.theoryDrillId,
                scenarioLabId: payload.scenarioLabId,
                reviewArtifactId: payload.reviewArtifactId,
              }
            : undefined;
        const resourceRestoreContext =
          requestedView === "resources" && payload.resourceSurface === "detail"
            ? {
                surface: "detail" as const,
                resourceId: payload.resourceDetailId ?? payload.resourceId,
                focusArea: payload.focusArea,
                summary: payload.latestSummary,
              }
            : requestedView === "resources" && payload.resourceSurface === "sandbox"
              ? {
                  surface: "sandbox" as const,
                  focusArea: payload.focusArea,
                  sandboxPath: payload.sandboxPath,
                  previewPath: payload.previewPath,
                  summary: payload.latestSummary,
                }
              : undefined;
        return {
          data:
            restoredTrainingState === state.data.workspaceTrainingState
              ? state.data
              : normalizeBootstrapData({
                  ...state.data,
                  workspaceTrainingState: restoredTrainingState,
                }),
          resourceRestoreContext:
            requestedView === "resources" ? resourceRestoreContext : state.resourceRestoreContext,
          trainingRestoreContext:
            requestedView === "training" ? trainingRestoreContext : state.trainingRestoreContext,
          layout: persistLayout({
            ...state.layout,
            activeView: requestedView,
          }),
        };
      }

      if (message.type === "ui/coachPrompt") {
        const draft = sanitizeVisibleText(message.payload.draft).trim();
        if (!draft) {
          return {};
        }
        return {
          layout: persistLayout({
            ...state.layout,
            activeView: "coach",
            composerDraft: draft,
          }),
        };
      }

      return {};
    }),
  requestStageMaterialGeneration: (planId, stageId) => {
    const normalizedStageId = stageId.trim();
    if (!normalizedStageId) {
      return;
    }
    set((state) => ({
      stageMaterialGenerating: {
        ...state.stageMaterialGenerating,
        [normalizedStageId]: true,
      },
    }));
    const workspaceId = get().data.memory.workspace?.workspaceId;
    postMessage({
      type: "command/execute",
      payload: {
        commandId: trainerCommands.stageMaterialGenerate,
        payload: {
          planId,
          stageId: normalizedStageId,
          ...(workspaceId ? { workspaceId } : {}),
        },
      },
    });
  },
  applyStageMaterials: (stageId, materials) =>
    set((state) => ({
      stageMaterials: mergeStageMaterials(state.stageMaterials, {
        [stageId]: materials,
      }),
      stageMaterialGenerating: clearStageMaterialGenerating(
        state.stageMaterialGenerating,
        new Set([stageId]),
      ),
    })),
  setStageMaterialGenerating: (stageId, busy) =>
    set((state) => ({
      stageMaterialGenerating: busy
        ? { ...state.stageMaterialGenerating, [stageId]: true }
        : clearStageMaterialGenerating(state.stageMaterialGenerating, new Set([stageId])),
    })),
  startStream: (messageId) =>
    set({
      streaming: {
        ...freshStreamingState(),
        isStreaming: true,
        streamMessageId: messageId,
        reliabilityPhase: "pending",
      },
      operationMessage: undefined,
    }),
  appendChunk: (chunk) =>
    set((state) => {
      const safeContent = appendSafeStreamContent(state.streaming, chunk);
      return {
        streaming: {
          ...state.streaming,
          ...safeContent,
        },
      };
    }),
  endStream: () =>
    set((state) => ({
      streaming: {
        ...state.streaming,
        ...finishSafeStreamContent(state.streaming),
        isStreaming: false,
      },
    })),
  resetStream: () => set({ streaming: freshStreamingState() }),
}));
