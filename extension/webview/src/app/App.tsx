import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { researchBriefResourceIds,upsertResearchBrief } from "../../../../shared/src/researchBrief";
import { LearningDrawer } from "../components/learning/LearningDrawer";
import { useLearningDrawerSections } from "../components/learning/useLearningDrawerSections";
import { goalTitleFromConversation } from "../lib/coachGoalTitle";
import { SystemState } from "../templates/SystemState";
import { SettingsRoute } from "./SettingsRoute";

import { useShallow } from "zustand/react/shallow";
import { trainerCommands } from "../../../../shared/src/commands";
import {
  sanitizeErrorSurfaceText
} from "../../../../shared/src/errorSurfaceSanitizer";
import type { TrainingPlanBinding } from "../../../../shared/src/models";
import { isOperationReliabilityInFlight } from "../../../../shared/src/operationReliabilityGovernance";
import {
  type RecoveredPlanResumeTurn
} from "../../../../shared/src/planOrientationGovernance";
import { analyzeSendIntent } from "../../../../shared/src/sendIntelligence";
import {
  filterSidebarControlCommands
} from "../../../../shared/src/sidebarCommands";
import {
  filterTrainerSkills,
  resolveTrainerSkillText,
  trainerSkillTriggerToken,
} from "../../../../shared/src/skillCatalog";
import {
  type CoachMessageAction
} from "../components/coach";
import { CoachHistoryDrawer } from "../components/coach/CoachHistoryDrawer";
import { type UserFeedbackKind } from "../components/common/UserFeedbackDisclosure";
import { WorkbenchSurfaceButton } from "../components/common/WorkbenchSurfaceButton";
import {
  CoachComposer
} from "../components/composer";
import {
  CheckMarkIcon,
  ChevronRightIcon,
  ResourcesIcon,
  SkillCubeIcon,
  TargetIcon,
  WarningIcon
} from "../components/icons";
import { isBrowserPreviewFixtureMode } from "../lib/browserPreviewMode";
import { formatTokenCount } from "../lib/formatUtils";
import {
  appUiCopy
} from "../lib/i18n/appUiCopy";
import { I18nProvider } from "../lib/i18n/context";
import { resolveCopy as resolveWorkbenchCopy } from "../lib/i18n/copy";
import { resolvePlanViewCopy } from "../lib/i18n/planViewCopy";
import { GOAL_MODE_COPY,composerAddCopy } from "../lib/i18n/segments/coachInlineText";
import {
  operationStatusMessageText
} from "../lib/operationMessageGovernance";
import { coachReplyMarkdown } from "../lib/shareUtils";
import type {
  ActiveWorkbenchView,
  ComposerLanguage,
  ConversationMessage,
  HostMessage,
  MessageAttachment,
  ResourceComposerIntent
} from "../lib/types";
import {
  normalizeSidebarView,
} from "../lib/types";
import { viewLabels } from "../lib/viewLabels";
import {
  getInjectedBootstrapState,
  getWorkbenchSurface,
  inVsCodeWebview,
  isBrowserSidePanelSurface,
  postMessage,
  requestCollapseToSidebar
} from "../lib/vscode";
import { AppShell } from "../templates/AppShell";
import { UtilityOverlay } from "../templates/UtilityOverlay";
import { templateCopy } from "../templates/templateCopy";
import { WorkbenchSurfaces } from "./WorkbenchSurfaces";
import { ProviderConnectionContext } from "./providerConnectionContext";
import { useCoachConversationController } from "./useCoachConversationController";
import {
  useCoachSettingsController,
  useCoachSettingsState,
  useProviderReadinessState,
} from "./useCoachSettingsController";
import { useComposerProviderController } from "./useComposerProviderController";
import {
  useLearningPlanController
} from "./useLearningPlanController";
import { useLibraryResourceController } from "./useLibraryResourceController";
import { useMenuState } from "./useMenuState";
import { useOperationStatusController } from "./useOperationStatusController";
import { useProviderConnectionController } from "./useProviderConnectionController";
import { useTrainingCardController } from "./useTrainingCardController";
import { composerSessionKeyFor,useWorkbenchState } from "./useWorkbenchState";
import {
  useWorkspaceAdmissionFlow,
  useWorkspaceAdmissionState,
} from "./useWorkspaceAdmissionController";

// ContextMenu type imported from useMenuState
import {
  COACH_REPLY_BODY_MAX_CHARS,
  ComposerDeckKind,
  DirectoryInput,
  LocalSkillSuggestion,
  composerShortcutHint,
  focusComposerInput,
  inBrowserPreviewEnvironment,
  requireBrowserPreviewAdapter,
  resolveCoachBlockingSurface,
  resolveTheme
} from "./appHelpers";
import { useTrainingAttemptAndComposerModes } from "./useTrainingAttemptAndComposerModes";
import { useTrainingWorkbenchDerivedState } from "./useTrainingWorkbenchDerivedState";
import { useWorkbenchHostMessageHandler } from "./useWorkbenchHostMessageHandler";
import { useWorkbenchLifecycleEffects } from "./useWorkbenchLifecycleEffects";
import { useWorkbenchRuntimeDerivedState } from "./useWorkbenchRuntimeDerivedState";
import { useWorkbenchSurfaceRenderers } from "./useWorkbenchSurfaceRenderers";
import {
  createWorkbenchSubmitHandler,
  useWorkbenchTurnSenderAndHistory,
} from "./useWorkbenchTurnSubmissionController";

export const injectedBootstrapAvailable = Boolean(getInjectedBootstrapState());
export const RESOURCE_VERSION_CHECK_TIMEOUT_MS = 125_000;

export const QUEUED_BANNER_COPY: Record<
  ComposerLanguage,
  {
    regionLabel: string;
    summary: (count: number) => string;
    imagePlaceholder: string;
    sendNow: string;
    edit: string;
    remove: string;
  }
> = {
  "zh-CN": {
    regionLabel: "待发送消息队列",
    summary: (count) => `已排队（${count} 条 · 回复完成后自动发送）`,
    imagePlaceholder: "[图片消息]",
    sendNow: "立即切换",
    edit: "编辑",
    remove: "取消排队",
  },
  "en-US": {
    regionLabel: "Queued messages",
    summary: (count) => `Queued (${count} · sends when current reply finishes)`,
    imagePlaceholder: "[Image message]",
    sendNow: "Send now",
    edit: "Edit",
    remove: "Remove queued message",
  },
  "es-ES": {
    regionLabel: "Mensajes en cola",
    summary: (count) => `En cola (${count} · se envía al terminar la respuesta)`,
    imagePlaceholder: "[Mensaje de imagen]",
    sendNow: "Enviar ahora",
    edit: "Editar",
    remove: "Quitar de la cola",
  },
  "fr-FR": {
    regionLabel: "Messages en file d'attente",
    summary: (count) => `En file (${count} · envoi automatique après la réponse)`,
    imagePlaceholder: "[Message image]",
    sendNow: "Envoyer maintenant",
    edit: "Modifier",
    remove: "Retirer de la file",
  },
  "de-DE": {
    regionLabel: "Nachrichten-Warteschlange",
    summary: (count) => `In Warteschlange (${count} · sendet nach Antwortende)`,
    imagePlaceholder: "[Bildnachricht]",
    sendNow: "Jetzt senden",
    edit: "Bearbeiten",
    remove: "Aus Warteschlange entfernen",
  },
  "ja-JP": {
    regionLabel: "送信待ちキュー",
    summary: (count) => `キュー済み（${count} 件 · 返信完了後に自動送信）`,
    imagePlaceholder: "[画像メッセージ]",
    sendNow: "今すぐ切替",
    edit: "編集",
    remove: "キューから削除",
  },
  "ko-KR": {
    regionLabel: "전송 대기열",
    summary: (count) => `대기열 (${count}건 · 답변 완료 후 자동 전송)`,
    imagePlaceholder: "[이미지 메시지]",
    sendNow: "지금 전환",
    edit: "편집",
    remove: "대기열에서 제거",
  },
  "pt-BR": {
    regionLabel: "Mensagens na fila",
    summary: (count) => `Na fila (${count} · envia ao concluir a resposta)`,
    imagePlaceholder: "[Mensagem com imagem]",
    sendNow: "Enviar agora",
    edit: "Editar",
    remove: "Remover da fila",
  },
};

export interface WorkbenchSendTurnInput {
  text: string;
  intent: "coach" | "next_task" | "review" | "plan" | "task";
  intentSource?: "explicit" | "inferred" | "none";
  goals?: string[];
  stream?: boolean;
  activeView?: ActiveWorkbenchView;
  includeCurrentFile?: boolean;
  includeDiagnostics?: boolean;
  contextDetail?: "focused" | "balanced" | "full";
  formalPlanMutation?: boolean;
  planComposerMode?: "explain" | "generate" | "evidence" | "blocker";
  planRuntimeRecovery?: RecoveredPlanResumeTurn;
  resourceComposerIntent?: ResourceComposerIntent;
  resourceIds?: string[];
  attachments?: MessageAttachment[];
  goalMode?: boolean;
  goalText?: string;
}

function useAppFoundation() {
  useEffect(() => {
    performance.mark("trainer:app-mounted");
  }, []);
  // §三 R3: App subscribes to a shallow summary of the store. Per-chunk
  // streaming content is deliberately NOT selected — CoachConversationView
  // subscribes to it itself — so a streaming reply no longer re-renders the
  // whole workbench on every chunk.
  const {
    data,
    layout,
    resourceOrganizationPending,
    resourceRestoreContext,
    trainingRestoreContext,
    trainingReviewQueueRequested,
    beginTrainingReview,
    hasReceivedHostState,
    syncStatus,
    syncCursor,
    setActiveView,
    openLearningDrawer,
    closeLearningDrawer,
    setLearningSection,
    setResourceRestoreContext,
    setComposerDraft,
    clearDockReturnNotice,
    setComposerLanguage,
    setComposerAnswerMode,
    setContextDetail,
    setIncludeCurrentFile,
    setIncludeSelection,
    setIncludeDiagnostics,
    setIncludeRelatedFiles,
    setFollowCurrentFile,
    setCoachDefaults,
    applyHostMessage: applyRawHostMessage,
    streamingIsStreaming,
    streamingStreamMessageId,
    streamingStreamError,
    streamingCompletionStopReason,
    streamingReliabilityPhase,
    streamingReliabilityOutcome,
    streamingCompletionNextStepRequiresConfirmation,
    streamingContentBucket,
  } = useWorkbenchState(
    useShallow((state) => ({
      data: state.data,
      layout: state.layout,
      resourceOrganizationPending: state.resourceOrganizationPending,
      resourceRestoreContext: state.resourceRestoreContext,
      trainingRestoreContext: state.trainingRestoreContext,
      trainingReviewQueueRequested: state.trainingReviewQueueRequested,
      beginTrainingReview: state.beginTrainingReview,
      hasReceivedHostState: state.hasReceivedHostState,
      syncStatus: state.syncStatus,
      syncCursor: state.syncCursor,
      setActiveView: state.setActiveView,
      openLearningDrawer: state.openLearningDrawer,
      closeLearningDrawer: state.closeLearningDrawer,
      setLearningSection: state.setLearningSection,
      setResourceRestoreContext: state.setResourceRestoreContext,
      setComposerDraft: state.setComposerDraft,
      setComposerSendPreference: state.setComposerSendPreference,
      clearDockReturnNotice: state.clearDockReturnNotice,
      dockReturnNotice: state.dockReturnNotice,
      setComposerLanguage: state.setComposerLanguage,
      setComposerAnswerMode: state.setComposerAnswerMode,
      setTeachingStyle: state.setTeachingStyle,
      setContextDetail: state.setContextDetail,
      setIncludeCurrentFile: state.setIncludeCurrentFile,
      setIncludeSelection: state.setIncludeSelection,
      setIncludeDiagnostics: state.setIncludeDiagnostics,
      setIncludeRelatedFiles: state.setIncludeRelatedFiles,
      setFollowCurrentFile: state.setFollowCurrentFile,
      setCoachDefaults: state.setCoachDefaults,
      setThemePreference: state.setThemePreference,
      setLearningSurfaceAlignment: state.setLearningSurfaceAlignment,
      applyHostMessage: state.applyHostMessage,
      streamingIsStreaming: state.streaming.isStreaming,
      streamingStreamMessageId: state.streaming.streamMessageId,
      streamingStreamError: state.streaming.streamError,
      streamingCompletionStopReason: state.streaming.completionStopReason,
      streamingReliabilityPhase: state.streaming.reliabilityPhase,
      streamingReliabilityOutcome: state.streaming.reliabilityOutcome,
      streamingCompletionNextStepRequiresConfirmation:
        state.streaming.completionNextStepRequiresConfirmation === true,
      // Activity presence is a per-tool-event boolean, not per-chunk content.
      // Coarse progress for the preview surfaces (context ring, view rail,
      // per-view reply banner). The full text subscribes in the conversation.
      streamingContentBucket: Math.floor((state.streaming.streamedContent?.length ?? 0) / 256),
    })),
  );
  // App only needs the streaming fields it acts on; content stays out.
  const streaming = useMemo(
    () => ({
      isStreaming: streamingIsStreaming,
      streamMessageId: streamingStreamMessageId,
      streamError: streamingStreamError,
      completionStopReason: streamingCompletionStopReason,
      reliabilityPhase: streamingReliabilityPhase,
      reliabilityOutcome: streamingReliabilityOutcome,
      completionNextStepRequiresConfirmation: streamingCompletionNextStepRequiresConfirmation,
    }),
    [
      streamingCompletionNextStepRequiresConfirmation,
      streamingCompletionStopReason,
      streamingIsStreaming,
      streamingReliabilityOutcome,
      streamingReliabilityPhase,
      streamingStreamError,
      streamingStreamMessageId,
    ],
  );
  const syncIdentity = syncCursor.generation > 0 ? syncCursor : undefined;

  // §三/§四十四: the operation-status controller owns the single banner channel
  // (message + surface), its visibility and its dismiss lifecycle.
  const {
    operationMessage,
    operationMessageVisible,
    operationMessageSurface,
    setOperationMessage,
    dismissOperationMessage,
  } = useOperationStatusController();

  // Training-card controller pilot (DESIGN.md §3): the training domain owns its
  // interaction state and host interception; App only routes and assembles.
  const {
    trainingComposerFlashMode,
    setTrainingComposerFlashMode,
    trainingComposerVerifyIndex,
    setTrainingComposerVerifyIndex,
    trainingComposerPracticeReturnMode,
    setTrainingComposerPracticeReturnMode,
    setTrainingComposerRoute,
    trainingVerifyNotice,
    setTrainingVerifyNotice,
    remoteVerification,
    displayedTrainingCardIdRef,
    beginRemoteVerification,
    stopRemoteVerification,
    resetRemoteVerification,
    handleRemoteVerificationHostMessage,
    handleRemoteVerificationCommandFailure,
    trainingPersistencePending,
    requestTrainingPersistence,
    resolveTrainingPersistenceAck,
  } = useTrainingCardController();

  const { openMenu, setOpenMenu } = useMenuState();
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0);
  const [dismissedComposerDeck, setDismissedComposerDeck] = useState<ComposerDeckKind>();
  const isBrowserPreview = inBrowserPreviewEnvironment();
  const activeView = normalizeSidebarView(layout.activeView);
  const t = resolveWorkbenchCopy(layout.composerLanguage);
  const {
    settingsSectionRequest,
    setSettingsSectionRequest,
    skillImportText,
    setSkillImportText,
    settingsActionState,
    settingsFeedbackState,
    setSettingsFeedbackState,
    settingsScopeKey,
    settingsActionScopeRef,
    setSettingsActionState,
    companionInstallState,
    setCompanionInstallState,
  } = useCoachSettingsState({
    syncCursor,
    activeView,
    isBrowserPreview,
    setOperationMessage,
  });
  const {
    pendingPostAdmissionSendRef,
    trainerWorkspaceAdmission,
    canCaptureGoalBeforeWorkspaceSetup,
    canChatBeforeProjectAdmission,
    workspaceAuthority,
    resourceWriteAccess,
    workspaceSessionBlocked,
    workspaceSessionBlockTitle,
    workspaceSessionBlockMessage,
    openWorkspaceAdmission,
    runWorkspaceAdmissionCommand,
  } = useWorkspaceAdmissionState({
    data,
    composerLanguage: layout.composerLanguage,
    t,
    setActiveView,
  });
  const composerDeckRef = useRef<HTMLDivElement | null>(null);
  const streamResumeDraftRef = useRef("");
  const sendRecoveredPlanResumeRef = useRef<
    (action: "continue_step" | "clear_blocker") => void
  >(() => undefined);
  // Goal mode: one small goal; the learner attempts first, the coach corrects.
  // Store-backed so a pane remount never drops the mode mid-conversation.
  const goalMode = useWorkbenchState((state) => state.goalMode);
  const goalText = useWorkbenchState((state) => state.goalText);
  const goalPaused = useWorkbenchState((state) => state.goalPaused);
  const startGoal = useWorkbenchState((state) => state.startGoal);
  const pauseGoal = useWorkbenchState((state) => state.pauseGoal);
  const resumeGoal = useWorkbenchState((state) => state.resumeGoal);
  const clearGoal = useWorkbenchState((state) => state.clearGoal);
  const restoreGoalForSession = useWorkbenchState((state) => state.restoreGoalForSession);
  const applyServerGoal = useWorkbenchState((state) => state.applyServerGoal);
  const goalModeCopy = GOAL_MODE_COPY[layout.composerLanguage] ?? GOAL_MODE_COPY["en-US"];
  const [composerModelActionDensity, setComposerModelActionDensity] = useState<"compact" | "default">("default");
  // §三: the provider-connection controller owns the editable draft (derived
  // from the single ProviderFacts record), its save payload, the endpoint
  // speed test and the API-key focus request. The instance is published to the
  // tree through ProviderConnectionContext, so Settings reads the same draft
  // and focus/speed-test state without loose props (an unmounted Settings
  // still cannot lose an unsaved draft — the state lives here in App).
  const providerConnection = useProviderConnectionController({
    facts: data.providerConfig,
    settingsActionKind: settingsActionState?.kind,
    settingsScopeKey,
    settingsActionScopeRef,
  });
  const {
    providerDraft,
    setProviderDraft,
    providerDraftHasChanges,
    providerDraftHasUnsavedApiKey,
    providerSavePayload,
    markProviderDraftSaved,
    handleProviderSpeedTestMessage,
    requestProviderApiKeyFocus,
  } = providerConnection;
  const composerSessionKey = composerSessionKeyFor(data);
  const [pendingGoalScope, setPendingGoalScope] = useState<string>();
  const goalDraftPending = !goalMode && pendingGoalScope === composerSessionKey;
  useEffect(() => {
    setPendingGoalScope((scope) => goalMode || scope !== composerSessionKey ? undefined : scope);
  }, [composerSessionKey, goalMode]);
  const [resourceSelectionBySession, setResourceSelectionBySession] = useState<Record<string, string[]>>({});
  const [inlinePracticeCollapsed, setInlinePracticeCollapsed] = useState(false);
  const [researchBriefToOpen, setResearchBriefToOpen] = useState<{ id: string; workspaceId?: string }>();
  const selectedResourceContextIds = resourceSelectionBySession[composerSessionKey] ?? [];
  const setSelectedResourceContextIds = useCallback((ids: string[]) => {
    setResourceSelectionBySession((sessions) => ({ ...sessions, [composerSessionKey]: ids }));
  }, [composerSessionKey]);
  const resourceConversationContextIds = layout.composerResourceRefs?.[composerSessionKey] ?? [];
  const setResourceConversationContextIds = (ids: string[]) => {
    useWorkbenchState.getState().writeComposerResourceRefs(composerSessionKey, ids, "replace");
  };
  const hostMessageSequenceRef = useRef(0);
  const handleSubmitRef = useRef<
    ((confirmedActionKey?: string, overrideSubmission?: { text: string; attachments?: MessageAttachment[] }) => Promise<void>) | null
  >(null);
  const sendTurnRef = useRef<(input: WorkbenchSendTurnInput) => void>(() => undefined);
  const coachRuntimeContextSignatureRef = useRef<string | undefined>(undefined);
  const composerModelSearchRef = useRef<HTMLInputElement | null>(null);
  const viewContentRef = useRef<HTMLElement | null>(null);
  const uploadFilesInputRef = useRef<HTMLInputElement | null>(null);
  const uploadFolderInputRef = useRef<HTMLInputElement | null>(null);
  const applyHostMessageRef = useRef<(message: HostMessage, isProviderActionOverride?: boolean) => void>(
    () => undefined,
  );
  const coachAutoScrollPinnedRef = useRef(true);
  const pinCoachScrollToBottom = useCallback(() => {
    coachAutoScrollPinnedRef.current = true;
  }, []);
  // §三: the conversation domain owns its local interaction state (echoes,
  // pending reply action, preview session id, last-turn view, transition).
  const {
    optimisticTurns,
    clearOptimisticTurns,
    appendOptimisticTurn,
    pendingMessageAction,
    beginPendingMessageAction,
    finishPendingMessageAction,
    clearPendingMessageActionUnless,
    previewSessionId,
    setPreviewSessionId,
    lastTurnView,
    setLastTurnView,
    coachContextTransition,
    setCoachContextTransition,
  } = useCoachConversationController({
    conversation: data.conversation,
    onOptimisticTurnAppended: pinCoachScrollToBottom,
  });
  // A new chat / restored session replaces the conversation identity. The
  // server snapshot is authoritative; unsettled optimistic echoes from the
  // previous session must not survive as orphan user chips.
  const coachSessionIdentityRef = useRef<string | undefined>(syncCursor.sessionId);
  useEffect(() => {
    const nextSessionId = syncCursor.sessionId;
    const previous = coachSessionIdentityRef.current;
    if (previous !== undefined && previous !== nextSessionId) {
      clearOptimisticTurns();
    }
    coachSessionIdentityRef.current = nextSessionId;
    if (nextSessionId) {
      if (inVsCodeWebview()) {
        applyServerGoal(data.goal);
      } else {
        restoreGoalForSession(nextSessionId);
      }
    }
  }, [applyServerGoal, clearOptimisticTurns, data.goal, restoreGoalForSession, syncCursor.sessionId]);
  // The server snapshot owns goal truth in VS Code. Browser preview keeps its
  // local fixture goal because no sidecar snapshot exists there.
  useEffect(() => {
    if (inVsCodeWebview()) {
      applyServerGoal(data.goal);
    }
  }, [applyServerGoal, data.goal]);
  const requestGoalControl = useCallback(
    (action: "start" | "pause" | "resume" | "complete", title?: string) => {
      postMessage({
        type: "command/execute",
        payload: {
          commandId: trainerCommands.goalControl,
          payload: { action, ...(title ? { title } : {}) },
        },
      });
    },
    [],
  );
  // §三: the plan-composer domain owns its composer mode/context/draft state.
  const {
    planComposerMode,
    setPlanComposerMode,
    coachPlanContext,
    setCoachPlanContext,
    pendingPlanComposerDraftReplacement,
    setPendingPlanComposerDraftReplacement,
  } = useLearningPlanController();
  const [, setUserFeedbackState] = useState<{
    busy: boolean;
    submittedKind?: UserFeedbackKind;
    error?: string;
  }>({ busy: false });
  const userFeedbackPendingKindRef = useRef<UserFeedbackKind>();
  const userFeedbackTimeoutRef = useRef<number | undefined>(undefined);
  // Protocol marker scope: the ack for a feedback submission carries the
  // request id the UI generated, so completion no longer depends on the
  // host's English status text.
  const userFeedbackRequestIdRef = useRef<string | undefined>(undefined);
  const injectedPreviewBootstrapHydratedRef = useRef(false);
  const browserPreviewLocationOverridesAppliedRef = useRef(false);
  const pendingTrainingHandoffSubmissionRef = useRef<
    { phase: "reflect" | "return"; cardId: string } | undefined
  >();
  const pendingLivePlanTaskMintRef = useRef<{ commandId: string; scope?: string; draft?: string } | undefined>();
  // Composer focus follows explicit coach intent only (deep-link prompts,
  // artifact/handoff bridges, suggested-action prefill). Plain navigation to
  // the coach tab must not steal focus from whatever the learner was doing.
  const coachComposerFocusRequestRef = useRef(false);
  const requestCoachComposerFocus = useCallback(() => {
    coachComposerFocusRequestRef.current = true;
    // Same-view handoffs focus right away; if the view is still switching,
    // the composer-shell effect below completes the request after commit.
    window.requestAnimationFrame(() => {
      if (!coachComposerFocusRequestRef.current) {
        return;
      }
      coachComposerFocusRequestRef.current = false;
      focusComposerInput();
    });
  }, []);
  const resolvedTheme = useMemo(() => resolveTheme(layout.themePreference), [layout.themePreference]);
  const browserPreviewFixture = isBrowserPreviewFixtureMode();
  // The same bundle runs in the sidebar view and in the full-width editor
  // panel; only the sidebar offers "open in editor", and only the panel offers
  // "back to sidebar".
  const editorPanelSurface = getWorkbenchSurface() === "editor";
  const canOpenInEditor = !editorPanelSurface && !isBrowserPreview && !isBrowserSidePanelSurface();
  const openViewInEditor = useCallback((view: "plan" | "resources") => {
    postMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.openViewInEditor, payload: { view } },
    });
  }, []);
  const expandToEditorLabel = appUiCopy(layout.composerLanguage, "在编辑器中打开");
  const openProviderSetup = useCallback(() => {
    // Deep link: Settings retains its surfaces, so pin the connection category
    // instead of landing on whatever detail was visited last.
    useWorkbenchState.getState().requestSettingsCategory("connection");
    setActiveView("settings");
    if (!data.providerConfig.apiKeyConfigured) {
      requestProviderApiKeyFocus();
    }
  }, [data.providerConfig.apiKeyConfigured, requestProviderApiKeyFocus, setActiveView]);
  const localizedResourceOperationFallback = t.stageDone;
  const planText = resolvePlanViewCopy(layout.composerLanguage);
  const handleResourceSelectionChange = setSelectedResourceContextIds;
  const {
    resolveResourceOperationStatus,
    resolveResourceTrainingHandoffMessage,
    resolveLibraryFolderOperation,
    resolveLibraryMigrationOperation,
    requestResourceMutation,
    requestResourceIndex,
    requestCoachReplyUpload,
    requestCoachResearchBrief,
    requestResourceSearch,
    requestBrowserPreviewResourceSearch,
    requestResourceTrainingHandoff,
    handleBrowserUploads,
    handleBrowserUrlImport,
    resourceCaptureFocusOptions,
    refreshPreviewResources,
    beginResourceOperationStatusWait,
    captureResourceIntoLibrary,
    requestLibraryMigration,
    listLibraryFolders,
    createLibraryFolder,
    renameLibraryFolder,
    deleteLibraryFolder,
    revealLibraryPath,
    organizeLibraryResource,
    exportLibraryResource,
  } = useLibraryResourceController({
    resources: data.resources,
    planStages: data.plan?.stages,
    workspaceId: data.memory.workspace?.workspaceId,
    composerLanguage: layout.composerLanguage,
    resourceSearchMode: layout.resourceSearchMode,
    localizedResourceOperationFallback,
    isBrowserPreview,
    browserPreviewFixture,
    previewSessionId,
    setPreviewSessionId,
    setActiveView,
    setOperationMessage,
    applyRawHostMessage,
    applyHostMessageRef,
  });
  const handleCoachMessageAction = useCallback(
    async (action: CoachMessageAction, message: ConversationMessage) => {
      if (action === "open-research-brief") {
        if (message.researchPreparation?.status === "saved") {
          const workspaceId = useWorkbenchState.getState().data.memory.workspace?.workspaceId;
          setResearchBriefToOpen({ id: message.researchPreparation.assetId, workspaceId });
          setResourceRestoreContext(undefined);
          setActiveView("resources");
        }
        return;
      }
      if (action === "set-goal") {
        // The learner's preceding turn is the goal; the assistant reply is the
        // evidence/answer, not the thing to pursue. Fall back to the reply only
        // when the thread has no prior user turn.
        const conversation = useWorkbenchState.getState().data.conversation;
        const title = goalTitleFromConversation(conversation, message.id);
        startGoal(title);
        requestGoalControl("start", title);
        setActiveView("coach");
        requestCoachComposerFocus();
        return;
      }
      if (action === "retry") {
        if (streaming.isStreaming) {
          return;
        }
        // Regenerate: re-send the user prompt that produced this reply through
        // sendTurn so browser preview, provider guards, and user context
        // preferences (current file, selection, diagnostics, coach defaults)
        // all stay consistent with normal turns.
        const conversation = useWorkbenchState.getState().data.conversation;
        const index = conversation.findIndex((item) => item.id === message.id);
        let prompt: string | undefined;
        for (let i = index - 1; index > 0 && i >= 0; i--) {
          const candidate = conversation[i];
          if (candidate.role === "user" && candidate.body.trim()) {
            prompt = candidate.body;
            break;
          }
        }
        if (!prompt) {
          return;
        }
        sendTurnRef.current({
          text: prompt,
          intent: "coach",
          activeView: "coach",
          stream: true,
        });
        return;
      }
      const replyDoc = coachReplyMarkdown(message, layout.composerLanguage);
      if (action === "share" || action === "copy") {
        const text = action === "copy" ? message.body : replyDoc.markdown;
        let copied = false;
        try {
          await navigator.clipboard.writeText(text);
          copied = true;
        } catch {
          // webview iframe 可能没有 clipboard-write 权限——回落 execCommand
          try {
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.cssText = "position:fixed;opacity:0;pointer-events:none";
            document.body.appendChild(ta);
            ta.select();
            copied = document.execCommand("copy");
            document.body.removeChild(ta);
          } catch {
            copied = false;
          }
        }
        setOperationMessage({
          tone: copied ? "success" : "error",
          message: copied
            ? appUiCopy(layout.composerLanguage, "这条教练回复已复制到剪贴板。")
            : appUiCopy(layout.composerLanguage, "复制失败,请重试。"),
        });
        return;
      }
      if (!beginPendingMessageAction(`${message.id}:${action}`)) return;
      if (action === "save-resource") {
        try {
          if (isBrowserPreview) {
            const browserPreview = await requireBrowserPreviewAdapter();
            const result = await browserPreview.uploadBrowserPreviewResources(
              [
                {
                  kind: "markdown",
                  name: replyDoc.title,
                  source: "coach-reply",
                  content: replyDoc.markdown,
                  contentEncoding: "utf-8",
                  tags: ["coach-reply"],
                },
              ],
              previewSessionId,
            );
            setPreviewSessionId(result.sessionId);
            useWorkbenchState.getState().patchData(result.patch);
            setOperationMessage({
              tone: result.failedUploadCount > 0 ? "error" : "success",
              message:
                result.failedUploadCount > 0
                  ? appUiCopy(layout.composerLanguage, "这条回复没有存进资料库,请重试。")
                  : appUiCopy(layout.composerLanguage, "已把这条回复存入资料库。"),
            });
          } else {
            await requestCoachReplyUpload(message);
            setOperationMessage({
              tone: "success",
              message: appUiCopy(layout.composerLanguage, "已把这条回复存入资料库。"),
            });
          }
        } catch (error) {
          setOperationMessage({
            tone: "error",
            message: `${appUiCopy(layout.composerLanguage, "这条回复没有存进资料库,请重试。")} ${sanitizeErrorSurfaceText(error instanceof Error ? error.message : String(error), layout.composerLanguage)}`,
          });
        } finally {
          finishPendingMessageAction();
        }
        return;
      }
      if (action === "save-research-brief") {
        const scope = useWorkbenchState.getState();
        const currentScope = () => {
          const current = useWorkbenchState.getState();
          return current.syncCursor.workspaceId === scope.syncCursor.workspaceId &&
            current.syncCursor.sessionId === scope.syncCursor.sessionId &&
            current.data.runtimeDataGeneration === scope.data.runtimeDataGeneration;
        };
        try {
          if (isBrowserPreview) {
            const browserPreview = await requireBrowserPreviewAdapter();
            if (!currentScope()) return;
            const researchGoal = goalTitleFromConversation(scope.data.conversation, message.id);
            const brief = await browserPreview.saveBrowserPreviewResearchBrief({
              researchGoal: researchGoal.slice(0, 300),
              reply: message.body.slice(0, 12000),
              resourceIds: researchBriefResourceIds(message),
              contextId: scope.data.memory.workspace?.workspaceId,
            }, previewSessionId);
            if (!currentScope()) return;
            const current = useWorkbenchState.getState();
            const memory = current.data.memory;
            current.patchData({ memory: { ...memory, researchBriefs: upsertResearchBrief(memory.researchBriefs, brief) } });
          } else {
            await requestCoachResearchBrief(message);
          }
          if (currentScope()) setOperationMessage({
            tone: "success",
            message: appUiCopy(layout.composerLanguage, "备课简报已存入资料库。"),
          });
        } catch (error) {
          if (currentScope()) setOperationMessage({
            tone: "error",
            message: `${appUiCopy(layout.composerLanguage, "这份回复没有生成备课简报。")} ${sanitizeErrorSurfaceText(error instanceof Error ? error.message : String(error), layout.composerLanguage)}`,
          });
        } finally {
          finishPendingMessageAction();
        }
        return;
      }
      const excerpt =
        message.body.trim().length > COACH_REPLY_BODY_MAX_CHARS
          ? `${message.body.trim().slice(0, COACH_REPLY_BODY_MAX_CHARS)}…`
          : message.body.trim();
      const scope = useWorkbenchState.getState();
      // A flash card (闪记) is the same evidence pipeline in a recall shape:
      // the learner answers inside the card, exactly like a practice card.
      const flashCard = action === "flash-card";
      try {
        await requestTrainingPersistence(trainerCommands.trainingGenerateCard, {
          source: "conversation_gap",
          cardType: flashCard ? "flash" : "practice",
          submode: flashCard ? "flash" : "practice",
          prompt: excerpt,
          contextHint: excerpt,
          focusArea: replyDoc.title,
        });
        const current = useWorkbenchState.getState();
        if (scope.syncCursor.workspaceId === current.syncCursor.workspaceId &&
          scope.syncCursor.sessionId === current.syncCursor.sessionId &&
          scope.layout.activeView === current.layout.activeView) {
          // The minted card renders inline in the conversation. A legacy
          // training route would open the learning drawer on top of it, so the
          // learner stays on Chat where the card itself is actionable.
          setActiveView("coach");
        }
      } catch (error) {
        setOperationMessage({
          tone: "error",
          message: sanitizeErrorSurfaceText(error instanceof Error ? error.message : String(error), layout.composerLanguage),
        });
      } finally {
        finishPendingMessageAction();
      }
    },
    [
      finishPendingMessageAction,
      isBrowserPreview,
      layout.composerLanguage,
      previewSessionId,
      requestCoachResearchBrief,
      requestCoachReplyUpload,
      requestTrainingPersistence,
      setActiveView,
      setOperationMessage,
      setResourceRestoreContext,
      streaming.isStreaming,
    ],
  );

  return {
    data,
    layout,
    resourceOrganizationPending,
    resourceRestoreContext,
    trainingRestoreContext,
    trainingReviewQueueRequested,
    beginTrainingReview,
    hasReceivedHostState,
    syncStatus,
    syncCursor,
    setActiveView,
    openLearningDrawer,
    closeLearningDrawer,
    setLearningSection,
    setResourceRestoreContext,
    setComposerDraft,
    clearDockReturnNotice,
    setComposerLanguage,
    setComposerAnswerMode,
    setContextDetail,
    setIncludeCurrentFile,
    setIncludeSelection,
    setIncludeDiagnostics,
    setIncludeRelatedFiles,
    setFollowCurrentFile,
    setCoachDefaults,
    applyRawHostMessage,
    streamingContentBucket,
    operationMessage,
    operationMessageVisible,
    operationMessageSurface,
    setOperationMessage,
    dismissOperationMessage,
    trainingComposerFlashMode,
    setTrainingComposerFlashMode,
    trainingComposerVerifyIndex,
    setTrainingComposerVerifyIndex,
    trainingComposerPracticeReturnMode,
    setTrainingComposerPracticeReturnMode,
    setTrainingComposerRoute,
    trainingVerifyNotice,
    setTrainingVerifyNotice,
    remoteVerification,
    displayedTrainingCardIdRef,
    beginRemoteVerification,
    stopRemoteVerification,
    resetRemoteVerification,
    handleRemoteVerificationHostMessage,
    handleRemoteVerificationCommandFailure,
    trainingPersistencePending,
    requestTrainingPersistence,
    resolveTrainingPersistenceAck,
    settingsSectionRequest,
    setSettingsSectionRequest,
    skillImportText,
    setSkillImportText,
    settingsActionState,
    settingsFeedbackState,
    setSettingsFeedbackState,
    setSettingsActionState,
    companionInstallState,
    setCompanionInstallState,
    pendingPostAdmissionSendRef,
    trainerWorkspaceAdmission,
    canCaptureGoalBeforeWorkspaceSetup,
    canChatBeforeProjectAdmission,
    workspaceAuthority,
    resourceWriteAccess,
    workspaceSessionBlocked,
    workspaceSessionBlockTitle,
    workspaceSessionBlockMessage,
    openWorkspaceAdmission,
    runWorkspaceAdmissionCommand,
    providerDraft,
    setProviderDraft,
    providerDraftHasChanges,
    providerDraftHasUnsavedApiKey,
    providerSavePayload,
    markProviderDraftSaved,
    handleProviderSpeedTestMessage,
    requestProviderApiKeyFocus,
    optimisticTurns,
    clearOptimisticTurns,
    appendOptimisticTurn,
    pendingMessageAction,
    clearPendingMessageActionUnless,
    previewSessionId,
    setPreviewSessionId,
    lastTurnView,
    setLastTurnView,
    coachContextTransition,
    setCoachContextTransition,
    planComposerMode,
    setPlanComposerMode,
    coachPlanContext,
    setCoachPlanContext,
    pendingPlanComposerDraftReplacement,
    setPendingPlanComposerDraftReplacement,
    resolveResourceOperationStatus,
    resolveResourceTrainingHandoffMessage,
    resolveLibraryFolderOperation,
    resolveLibraryMigrationOperation,
    requestResourceMutation,
    requestResourceIndex,
    requestResourceSearch,
    requestBrowserPreviewResourceSearch,
    requestResourceTrainingHandoff,
    handleBrowserUploads,
    handleBrowserUrlImport,
    resourceCaptureFocusOptions,
    refreshPreviewResources,
    beginResourceOperationStatusWait,
    captureResourceIntoLibrary,
    requestLibraryMigration,
    listLibraryFolders,
    createLibraryFolder,
    renameLibraryFolder,
    deleteLibraryFolder,
    revealLibraryPath,
    organizeLibraryResource,
    exportLibraryResource,
    streaming,
    syncIdentity,
    openMenu,
    setOpenMenu,
    selectedCommandIndex,
    setSelectedCommandIndex,
    dismissedComposerDeck,
    setDismissedComposerDeck,
    isBrowserPreview,
    activeView,
    t,
    composerDeckRef,
    streamResumeDraftRef,
    sendRecoveredPlanResumeRef,
    goalMode,
    goalText,
    goalPaused,
    startGoal,
    pauseGoal,
    resumeGoal,
    clearGoal,
    goalModeCopy,
    composerModelActionDensity,
    setComposerModelActionDensity,
    providerConnection,
    composerSessionKey,
    setPendingGoalScope,
    goalDraftPending,
    inlinePracticeCollapsed,
    setInlinePracticeCollapsed,
    researchBriefToOpen,
    selectedResourceContextIds,
    setSelectedResourceContextIds,
    resourceConversationContextIds,
    setResourceConversationContextIds,
    hostMessageSequenceRef,
    handleSubmitRef,
    sendTurnRef,
    coachRuntimeContextSignatureRef,
    composerModelSearchRef,
    viewContentRef,
    uploadFilesInputRef,
    uploadFolderInputRef,
    applyHostMessageRef,
    coachAutoScrollPinnedRef,
    requestGoalControl,
    setUserFeedbackState,
    userFeedbackPendingKindRef,
    userFeedbackTimeoutRef,
    userFeedbackRequestIdRef,
    injectedPreviewBootstrapHydratedRef,
    browserPreviewLocationOverridesAppliedRef,
    pendingTrainingHandoffSubmissionRef,
    pendingLivePlanTaskMintRef,
    coachComposerFocusRequestRef,
    requestCoachComposerFocus,
    resolvedTheme,
    browserPreviewFixture,
    editorPanelSurface,
    canOpenInEditor,
    openViewInEditor,
    expandToEditorLabel,
    openProviderSetup,
    localizedResourceOperationFallback,
    planText,
    handleResourceSelectionChange,
    handleCoachMessageAction,
  };
}

export type WorkbenchCtxAfterK0 = ReturnType<typeof useAppFoundation>;
export type WorkbenchCtxAfterE1 = WorkbenchCtxAfterK0 & ReturnType<typeof useWorkbenchHostMessageHandler>;

function useAppProviderComposerSetup(ctx: WorkbenchCtxAfterE1) {
  const {
    data,
    layout,
    setActiveView,
    setOperationMessage,
    workspaceAuthority,
    previewSessionId,
    setPreviewSessionId,
    setOpenMenu,
    isBrowserPreview,
    activeView,
    composerModelActionDensity,
    applyPreviewHostMessages,
  } = ctx;
  const {
    providerSendState,
    providerImageInputState,
    capabilityVerdict,
    providerCanCoachNow,
    providerSupportsFormalPlanTools,
    providerCanMutateFormalPlan,
    formalPlanCapabilityMessage,
    providerToolsExplicitlyUnsupported,
    agentToolsCapabilityMessage,
    providerBlockReason,
    blockedComposerGuidance,
    providerCoachNotice,
    providerSetupState,
    displayConnectionState,
  } = useProviderReadinessState({
    data,
    composerLanguage: layout.composerLanguage,
    activeView,
    workspaceAuthority,
  });
  // The neutral takeover is reserved for a provider that genuinely cannot run
  // (not configured / blocked) — never for a connecting or offline sidecar.
  const shouldShowNeutralEmptyState =
    data.conversation.length === 0 && (!providerCanCoachNow || Boolean(providerBlockReason));
  const coachWelcomeVisible =
    data.conversation.length === 0 && providerCanCoachNow && !shouldShowNeutralEmptyState;
  const hasDurableCoachContext = Boolean(
    data.memory.activeThread ||
      data.memory.memoryEvidence.length > 0 ||
      data.memory.workspaceUnderstanding ||
      data.plan?.id ||
      data.profile.goals.length > 0 ||
      data.profile.targetProject?.trim() ||
      data.profile.projectContext?.trim() ||
      data.memory.workspace?.projectContext?.trim(),
  );
  // r2-g0-1: the first-run gate is "the learner has not spoken yet", not
  // "the thread is empty" — the capture-ready seed ships one coach greeting,
  // which must not hide the starters.
  const isFirstCoachConversation =
    !data.conversation.some((message) => message.role === "user") &&
    !hasDurableCoachContext;
  const {
    composerHasSavedProfiles,
    composerProviderCopy,
    composerModelButtonDisplayLabel,
    composerModelButtonTitle,
    composerProviderMenuItems,
    composerModelQuery,
    setComposerModelQuery,
    filteredComposerProviderMenuItems,
    composerThinkingDescriptor,
    toggleComposerModelMenu,
    refreshComposerProviderModels,
    setComposerThinking,
    switchComposerProviderModel,
    switchComposerProviderModelForProfile,
  } = useComposerProviderController({
    providerConfig: data.providerConfig,
    composerLanguage: layout.composerLanguage,
    composerModelActionDensity,
    isBrowserPreview,
    previewSessionId,
    setPreviewSessionId,
    applyPreviewHostMessages,
    setActiveView,
    setOpenMenu,
    setOperationMessage,
  });

  return {
    providerSendState,
    providerImageInputState,
    capabilityVerdict,
    providerCanCoachNow,
    providerSupportsFormalPlanTools,
    providerCanMutateFormalPlan,
    formalPlanCapabilityMessage,
    providerToolsExplicitlyUnsupported,
    agentToolsCapabilityMessage,
    providerBlockReason,
    blockedComposerGuidance,
    providerCoachNotice,
    providerSetupState,
    displayConnectionState,
    composerHasSavedProfiles,
    composerProviderCopy,
    composerModelButtonDisplayLabel,
    composerModelButtonTitle,
    composerProviderMenuItems,
    composerModelQuery,
    setComposerModelQuery,
    filteredComposerProviderMenuItems,
    composerThinkingDescriptor,
    toggleComposerModelMenu,
    refreshComposerProviderModels,
    setComposerThinking,
    switchComposerProviderModel,
    switchComposerProviderModelForProfile,
    shouldShowNeutralEmptyState,
    coachWelcomeVisible,
    isFirstCoachConversation,
  };
}

export type WorkbenchCtxAfterK1 = WorkbenchCtxAfterE1 & ReturnType<typeof useAppProviderComposerSetup>;
export type WorkbenchCtxAfterE2 = WorkbenchCtxAfterK1 & ReturnType<typeof useWorkbenchLifecycleEffects>;
export type WorkbenchCtxAfterE3 = WorkbenchCtxAfterE2 & ReturnType<typeof useWorkbenchRuntimeDerivedState>;
export type WorkbenchCtxAfterE4 = WorkbenchCtxAfterE3 & ReturnType<typeof useTrainingWorkbenchDerivedState>;

function useAppSettingsAndArbitration(ctx: WorkbenchCtxAfterE4) {
  const {
    activityDraftKey,
    data,
    layout,
    setActiveView,
    setComposerDraft,
    setComposerLanguage,
    setComposerAnswerMode,
    setContextDetail,
    setIncludeCurrentFile,
    setIncludeSelection,
    setIncludeDiagnostics,
    setIncludeRelatedFiles,
    setFollowCurrentFile,
    setCoachDefaults,
    operationMessage,
    setOperationMessage,
    setSettingsSectionRequest,
    skillImportText,
    setSkillImportText,
    settingsActionState,
    settingsFeedbackState,
    setSettingsFeedbackState,
    setSettingsActionState,
    workspaceSessionBlocked,
    workspaceSessionBlockMessage,
    openWorkspaceAdmission,
    providerDraft,
    providerDraftHasChanges,
    providerDraftHasUnsavedApiKey,
    providerSavePayload,
    markProviderDraftSaved,
    previewSessionId,
    setPreviewSessionId,
    streaming,
    setOpenMenu,
    selectedCommandIndex,
    setSelectedCommandIndex,
    dismissedComposerDeck,
    setDismissedComposerDeck,
    isBrowserPreview,
    activeView,
    t,
    composerDeckRef,
    requestTrainingCardGeneration,
    applyHostMessage,
    draft,
    composerAttachments,
    normalizedDraft,
    applyPreviewHostMessages,
    providerSendState,
    providerImageInputState,
    capabilityVerdict,
    providerCanCoachNow,
    providerBlockReason,
    blockedComposerGuidance,
    shouldShowNeutralEmptyState,
    activePlanStage,
    leftoverSettingsProfileRhythmNotLive,
    recoveredDisplayFacts,
    formalPlanLive,
    livePlanFrozen,
    activityAttachments,
    setActivityDraft,
    trainingComposerEnabled,
    trainingComposerTalkMode,
  } = ctx;
  const activityDraft = layout.activityDrafts?.[activityDraftKey] ?? "";
  const composerUsesTrainingFlow = trainingComposerEnabled && !trainingComposerTalkMode;
  const activeSkillDraft = (composerUsesTrainingFlow ? activityDraft : draft).trim();
  const {
    providerStatus,
    coachDefaultsStatus,
    workspaceControlStatus,
    localCommandMap,
    trainerSkillContext,
    customSkills,
    availableSkillCatalog,
    composerMenuSkills,
    persistCoachSettings,
    queueCoachSettingsSave,
    selectSkillSuggestion,
    installCustomSkillFromPaste,
    copyCustomSkillShare,
    openSkillSettings,
    useProviderTemplateByLabel,
    saveProviderDraft,
    providerSettingsActions,
    cancelProviderTest,
  } = useCoachSettingsController({
    data,
    layout,
    activeView,
    t,
    isBrowserPreview,
    previewSessionId,
    setPreviewSessionId,
    leftoverSettingsProfileRhythmNotLive,
    operationMessage,
    setOperationMessage,
    settingsActionState,
    setSettingsActionState,
    settingsFeedbackState,
    setSettingsFeedbackState,
    setSettingsSectionRequest,
    skillImportText,
    setSkillImportText,
    providerDraft,
    providerDraftHasChanges,
    providerDraftHasUnsavedApiKey,
    providerSavePayload,
    markProviderDraftSaved,
    applyHostMessage,
    applyPreviewHostMessages,
    setActiveView,
    setComposerLanguage,
    setComposerAnswerMode,
    setContextDetail,
    setIncludeCurrentFile,
    setIncludeSelection,
    setIncludeDiagnostics,
    setIncludeRelatedFiles,
    setFollowCurrentFile,
    setCoachDefaults,
    activeSkillDraft,
    composerUsesTrainingFlow,
    setActivityDraft,
    setComposerDraft,
    setDismissedComposerDeck,
    setOpenMenu,
    setSelectedCommandIndex,
  });

  const analyzeComposerDraft = useCallback(
    (text: string) =>
      analyzeSendIntent({
        draft: text,
        activeView,
        hasResearchProject: false,
        activeFile: data.liveContext.activeFile,
        selectionRange: data.liveContext.selectionRange,
        relatedFilesCount: data.liveContext.relatedFiles.length,
        includeCurrentFile: layout.includeCurrentFile,
        includeSelection: layout.includeSelection,
        includeDiagnostics: layout.includeDiagnostics,
        includeRelatedFiles: layout.includeRelatedFiles,
        contextDetail: layout.contextDetail,
        diagnosticErrors: data.liveContext.diagnosticErrors,
        diagnosticWarnings: data.liveContext.diagnosticWarnings,
      }),
    [
      activeView,
      data.liveContext.activeFile,
      data.liveContext.selectionRange,
      data.liveContext.relatedFiles.length,
      layout.includeCurrentFile,
      layout.includeSelection,
      layout.includeDiagnostics,
      layout.includeRelatedFiles,
      layout.contextDetail,
      data.liveContext.diagnosticErrors,
      data.liveContext.diagnosticWarnings,
    ],
  );

  const sendAnalysis = useMemo(() => analyzeComposerDraft(draft), [analyzeComposerDraft, draft]);

  const matchingLocalSkills = useMemo<LocalSkillSuggestion[]>(() => {
    // Only the first `$token` selects a skill — text after it is arguments
    // handed to the skill on submit. Filtering on the full draft would drop
    // the resolved skill (and falsely offer to re-create it) once the user
    // starts typing arguments.
    const triggerToken = trainerSkillTriggerToken(activeSkillDraft);
    if (triggerToken === undefined) {
      return [];
    }

    return filterTrainerSkills(triggerToken, trainerSkillContext, triggerToken === "$" ? 6 : 10, availableSkillCatalog);
  }, [
    activeSkillDraft,
    trainerSkillContext,
    availableSkillCatalog,
  ]);
  const matchingLocalCommands = useMemo(
    () =>
      filterSidebarControlCommands(normalizedDraft)
        .flatMap((commandDefinition) => {
          const suggestion = localCommandMap.get(commandDefinition.id);
          return suggestion ? [suggestion] : [];
        })
        .slice(0, 6),
    [localCommandMap, normalizedDraft],
  );
  useEffect(() => {
    const activeDeckItems = normalizedDraft.startsWith("$") ? matchingLocalSkills : matchingLocalCommands;
    if (activeDeckItems.length === 0) {
      setSelectedCommandIndex(0);
      return;
    }

    setSelectedCommandIndex((current) =>
      current >= activeDeckItems.length ? activeDeckItems.length - 1 : current,
    );
  }, [matchingLocalCommands, matchingLocalSkills, normalizedDraft]);

  useEffect(() => {
    const activeItem = composerDeckRef.current?.querySelector<HTMLElement>(
      ".command-deck__item.is-active, .template-command-palette__entry[aria-selected=true]",
    );
    activeItem?.scrollIntoView({ block: "nearest" });
  }, [dismissedComposerDeck, normalizedDraft, selectedCommandIndex]);

  const sendBlocked =
    workspaceSessionBlocked || !providerCanCoachNow || Boolean(providerBlockReason);
  const capabilitySendBlocked = !capabilityVerdict.chat;
  const handleGenerateTrainingCard = useCallback(
    (focusArea?: string, prompt?: string, planBinding?: TrainingPlanBinding) => {
      if (workspaceSessionBlocked) {
        openWorkspaceAdmission();
        setOperationMessage({
          tone: "info",
          message: workspaceSessionBlockMessage ?? blockedComposerGuidance,
        });
        return;
      }

      if (!providerCanCoachNow || providerBlockReason) {
        setOperationMessage({
          tone: "info",
          message: blockedComposerGuidance,
        });
        return;
      }

      requestTrainingCardGeneration(focusArea, prompt, planBinding);
    },
    [
      blockedComposerGuidance,
      openWorkspaceAdmission,
      providerBlockReason,
      providerCanCoachNow,
      requestTrainingCardGeneration,
      setOperationMessage,
      workspaceSessionBlockMessage,
      workspaceSessionBlocked,
    ],
  );
  // "Next card" is a plan action when a live formal step exists: minting a
  // context-free conversation card here used to replace the learner's plan
  // step with a generic fallback. Bind the live stage only when the plan can
  // still advance (not frozen); otherwise keep the explicit manual request.
  const handleNextTrainingCard = useCallback(() => {
    const step = recoveredDisplayFacts.currentStep?.trim();
    if (
      formalPlanLive &&
      !livePlanFrozen &&
      activePlanStage?.id &&
      data.plan.id &&
      step
    ) {
      handleGenerateTrainingCard(activePlanStage.title, step, {
        planId: data.plan.id,
        stageId: activePlanStage.id,
        step,
        revision: data.plan.revision,
      });
      return;
    }
    handleGenerateTrainingCard();
  }, [
    activePlanStage,
    data.plan.id,
    data.plan.revision,
    formalPlanLive,
    handleGenerateTrainingCard,
    livePlanFrozen,
    recoveredDisplayFacts.currentStep,
  ]);
  // Secondary Learning action: mint a card for the live plan step with the
  // plan binding the server requires. The primary "continue" action stays a
  // deliberate discussion; this is the practice path.
  const handleGeneratePlanStepCard = useCallback(() => {
    const step = recoveredDisplayFacts.currentStep?.trim();
    if (!formalPlanLive || livePlanFrozen || !activePlanStage?.id || !data.plan.id || !step) {
      return;
    }
    if (workspaceSessionBlocked) {
      openWorkspaceAdmission();
      return;
    }
    if (!providerCanCoachNow || providerBlockReason) {
      setOperationMessage({ tone: "info", message: blockedComposerGuidance });
      return;
    }
    // The minted card is inline in the conversation: land on Chat instead of
    // opening the learning drawer over the card the learner is about to use.
    setActiveView("coach");
    handleGenerateTrainingCard(activePlanStage.title, step, {
      planId: data.plan.id,
      stageId: activePlanStage.id,
      step,
      revision: data.plan.revision,
    });
  }, [
    activePlanStage,
    blockedComposerGuidance,
    data.plan.id,
    data.plan.revision,
    formalPlanLive,
    handleGenerateTrainingCard,
    livePlanFrozen,
    openWorkspaceAdmission,
    providerBlockReason,
    providerCanCoachNow,
    recoveredDisplayFacts.currentStep,
    setOperationMessage,
    workspaceSessionBlocked,
  ]);
  // A missing provider must not destroy a useful draft. Let submission surface the
  // in-place recovery state and keep the learner in the view where they were working.
  const composerSendBlocked = workspaceSessionBlocked;
  const imageAttachmentSendBlocked =
    (composerUsesTrainingFlow ? activityAttachments : composerAttachments).length > 0 && !providerImageInputState.supported;
  const imageAttachmentBlockedReason = imageAttachmentSendBlocked
    ? providerImageInputState.detail ??
      providerImageInputState.reason ??
      (appUiCopy(layout.composerLanguage, "当前连接还不能验证图片。"))
    : undefined;
  const showComposerProviderNote =
    !composerUsesTrainingFlow &&
    !sendBlocked &&
    Boolean(
      providerSendState.warning
    );
  // §六: one arbitration result drives both the coach pane takeover and the
  // composer presence bar, so at most one blocking surface is ever visible.
  const coachBlockingSurface = resolveCoachBlockingSurface({
    coachViewActive: activeView === "coach",
    workspaceSessionBlocked,
    neutralSetupTakeover: shouldShowNeutralEmptyState,
    providerSendBlocked: sendBlocked,
    streamRecovering:
      !streaming.isStreaming &&
      (Boolean(streaming.streamError?.trim()) ||
        /interrupted|aborted|failed|timeout|network|error/.test(
          streaming.completionStopReason?.trim().toLowerCase() ?? "",
        )),
  });
  const showComposerBlockingNotice = coachBlockingSurface === "provider-notice";
  const showComposerPresenceBar =
    (coachBlockingSurface === null || coachBlockingSurface === "provider-notice") &&
    (showComposerBlockingNotice || showComposerProviderNote);

  return {
    providerStatus,
    coachDefaultsStatus,
    workspaceControlStatus,
    localCommandMap,
    trainerSkillContext,
    customSkills,
    availableSkillCatalog,
    composerMenuSkills,
    persistCoachSettings,
    queueCoachSettingsSave,
    selectSkillSuggestion,
    installCustomSkillFromPaste,
    copyCustomSkillShare,
    openSkillSettings,
    useProviderTemplateByLabel,
    saveProviderDraft,
    providerSettingsActions,
    cancelProviderTest,
    composerUsesTrainingFlow,
    activeSkillDraft,
    analyzeComposerDraft,
    sendAnalysis,
    matchingLocalSkills,
    matchingLocalCommands,
    sendBlocked,
    capabilitySendBlocked,
    handleGenerateTrainingCard,
    handleNextTrainingCard,
    handleGeneratePlanStepCard,
    composerSendBlocked,
    imageAttachmentSendBlocked,
    imageAttachmentBlockedReason,
    showComposerProviderNote,
    coachBlockingSurface,
    showComposerBlockingNotice,
    showComposerPresenceBar,
  };
}

export type WorkbenchCtxAfterK2 = WorkbenchCtxAfterE4 & ReturnType<typeof useAppSettingsAndArbitration>;
export type WorkbenchCtxAfterE5a = WorkbenchCtxAfterK2 & ReturnType<typeof useWorkbenchTurnSenderAndHistory>;
export type WorkbenchCtxAfterE6 = WorkbenchCtxAfterE5a & ReturnType<typeof useTrainingAttemptAndComposerModes>;

function useAppAdmissionAndSkillSharing(ctx: WorkbenchCtxAfterE6) {
  const {
    data,
    layout,
    setComposerDraft,
    setOperationMessage,
    skillImportText,
    setSkillImportText,
    settingsActionState,
    setSettingsActionState,
    pendingPostAdmissionSendRef,
    trainerWorkspaceAdmission,
    workspaceSessionBlocked,
    runWorkspaceAdmissionCommand,
    providerDraft,
    setProviderDraft,
    streaming,
    isBrowserPreview,
    handleSubmitRef,
    sendTurnRef,
    openProviderSetup,
    setComposerAttachments,
    providerSendState,
    providerCanCoachNow,
    providerBlockReason,
    providerSetupState,
    firstLookSummary,
    liveSandboxState,
    customSkills,
    installCustomSkillFromPaste,
    copyCustomSkillShare,
    saveProviderDraft,
    capabilitySendBlocked,
  } = ctx;
  const renderSkillSharing = () => <details className="template-disclosure"><summary>{appUiCopy(layout.composerLanguage, "分享")}</summary><div>
    {customSkills.map((skill) => <div className="template-context" key={skill.id}><span>{skill.trigger} · {skill.title}</span><button type="button" className="template-back" onClick={() => void copyCustomSkillShare(skill)}>{appUiCopy(layout.composerLanguage, "复制分享包")}</button></div>)}
    <textarea className="settings-skill-import" value={skillImportText} placeholder={appUiCopy(layout.composerLanguage, "粘贴技能分享包 JSON 进行安装")} aria-label={appUiCopy(layout.composerLanguage, "安装技能")} rows={2} onChange={(event) => setSkillImportText(event.target.value)} />
    <button type="button" className="button button--ghost" disabled={!skillImportText.trim()} onClick={installCustomSkillFromPaste}>{appUiCopy(layout.composerLanguage, "安装技能")}</button>
  </div></details>;
  const providerSetupAction = {
    primary: {
      label: providerSetupState.actionLabel,
    },
  };
  const {
    onboarding,
    onboardingWizard,
    workspaceAdmissionContent,
  } = useWorkspaceAdmissionFlow({
    trainerWorkspaceAdmission,
    workspaceSessionBlocked,
    windowTrusted: data.memory.workspace?.windowTrusted === true,
    liveSandboxCapabilitySummary:
      liveSandboxState?.capabilitySummary as Record<string, unknown> | undefined,
    firstLookSubjectFamily: firstLookSummary?.subjectFamily,
    providerConfig: data.providerConfig,
    providerSendBlocked: providerSendState.blocked,
    providerCanCoachNow,
    providerBlockReason,
    capabilitySendBlocked,
    isStreaming: streaming.isStreaming,
    isBrowserPreview,
    composerLanguage: layout.composerLanguage,
    providerDraft,
    setProviderDraft,
    settingsActionState,
    setSettingsActionState,
    setOperationMessage,
    setComposerDraft,
    setComposerAttachments,
    pendingPostAdmissionSendRef,
    handleSubmitRef,
    sendTurnRef,
    runWorkspaceAdmissionCommand,
    saveProviderDraft,
    openProviderSetup,
  });
  return {
    onboarding,
    onboardingWizard,
    workspaceAdmissionContent,
    renderSkillSharing,
    providerSetupAction,
  };
}

export type WorkbenchCtxAfterK3 = WorkbenchCtxAfterE6 & ReturnType<typeof useAppAdmissionAndSkillSharing>;
export type WorkbenchCtxAfterE7 = WorkbenchCtxAfterK3 & ReturnType<typeof useWorkbenchSurfaceRenderers>;

export function App() {
  const ctxK0 = useAppFoundation();
  const ctxE1 = { ...ctxK0, ...useWorkbenchHostMessageHandler(ctxK0) };
  const ctxK1 = { ...ctxE1, ...useAppProviderComposerSetup(ctxE1) };
  const ctxE2 = { ...ctxK1, ...useWorkbenchLifecycleEffects(ctxK1) };
  const ctxE3 = { ...ctxE2, ...useWorkbenchRuntimeDerivedState(ctxE2) };
  const ctxE4 = { ...ctxE3, ...useTrainingWorkbenchDerivedState(ctxE3) };
  const ctxK2 = { ...ctxE4, ...useAppSettingsAndArbitration(ctxE4) };
  const ctxE5a = { ...ctxK2, ...useWorkbenchTurnSenderAndHistory(ctxK2) };
  const ctxE6 = { ...ctxE5a, ...useTrainingAttemptAndComposerModes(ctxE5a) };
  const ctxK3 = { ...ctxE6, ...useAppAdmissionAndSkillSharing(ctxE6) };
  const ctxE7 = { ...ctxK3, ...useWorkbenchSurfaceRenderers(ctxK3) };
  const ctxAfterE5b = { ...ctxE7, ...createWorkbenchSubmitHandler(ctxE7) };
  const {
    composerActionPreview,
    setComposerActionPreview,
    confirmComposerActionPreview,
    data,
    layout,
    hasReceivedHostState,
    setActiveView,
    openLearningDrawer,
    closeLearningDrawer,
    setLearningSection,
    setComposerDraft,
    operationMessage,
    operationMessageVisible,
    operationMessageSurface,
    dismissOperationMessage,
    trainingPersistencePending,
    settingsSectionRequest,
    settingsActionState,
    companionInstallState,
    canCaptureGoalBeforeWorkspaceSetup,
    canChatBeforeProjectAdmission,
    workspaceSessionBlocked,
    workspaceSessionBlockTitle,
    workspaceSessionBlockMessage,
    openWorkspaceAdmission,
    handleBrowserUploads,
    streaming,
    openMenu,
    setOpenMenu,
    selectedCommandIndex,
    setSelectedCommandIndex,
    dismissedComposerDeck,
    setDismissedComposerDeck,
    isBrowserPreview,
    activeView,
    t,
    goalMode,
    goalText,
    goalPaused,
    pauseGoal,
    resumeGoal,
    clearGoal,
    goalModeCopy,
    composerModelActionDensity,
    providerConnection,
    composerSessionKey,
    setPendingGoalScope,
    goalDraftPending,
    viewContentRef,
    uploadFilesInputRef,
    uploadFolderInputRef,
    requestGoalControl,
    requestCoachComposerFocus,
    editorPanelSurface,
    handleReviewQueueAction,
    showComposerShell,
    composerShellRef,
    draft,
    surfaceInstanceKey,
    composerDraftScope,
    attachmentScope,
    composerAttachments,
    setComposerAttachments,
    normalizedDraft,
    navigateComposerHistory,
    handleComposerDraftChange,
    uiDirection,
    providerSendState,
    providerImageInputState,
    capabilityVerdict,
    providerCanCoachNow,
    providerBlockReason,
    providerSetupState,
    composerModelButtonDisplayLabel,
    composerModelButtonTitle,
    toggleComposerModelMenu,
    composerContextUsage,
    composerContextUsageDetail,
    composerContextRingNode,
    resolvedCoachReview,
    planReviewItems,
    resolvedCoachStateSummary,
    activityDraftKey,
    activityDraft,
    activityAttachments,
    setActivityAttachments,
    setActivityDraft,
    composerMentionItems,
    handleComposerMentionSelect,
    trainingComposerPhase,
    trainingComposerTalkMode,
    trainingComposerReflectMode,
    inlinePracticeAwaitingComposerSubmission,
    providerStatus,
    coachDefaultsStatus,
    workspaceControlStatus,
    composerMenuSkills,
    persistCoachSettings,
    queueCoachSettingsSave,
    selectSkillSuggestion,
    openSkillSettings,
    useProviderTemplateByLabel,
    saveProviderDraft,
    providerSettingsActions,
    cancelProviderTest,
    composerUsesTrainingFlow,
    matchingLocalSkills,
    matchingLocalCommands,
    composerSendBlocked,
    imageAttachmentSendBlocked,
    imageAttachmentBlockedReason,
    showComposerProviderNote,
    showComposerBlockingNotice,
    showComposerPresenceBar,
    coachSessions,
    coachSessionsStatus,
    coachSessionsMessage,
    requestCoachSessions,
    toggleComposerHistoryMenu,
    activateCoachSession,
    startNewCoachChat,
    queuedFollowUps,
    setQueuedFollowUps,
    queueCurrentComposerDraft,
    runComposerCommand,
    handleVerifyTrainingFromIde,
    handleCancelStream,
    renderComposerAccessory,
    unifiedCommandSuggestions,
    selectUnifiedCommand,
    renderCommandDeck,
    renderSkillDeck,
    renderSkillSharing,
    renderContextualResultRail,
    renderDockedView,
    renderCoachRootView,
    composerSurfaceHint,
    blockedComposerFallback,
    blockedComposerPresenceDetail,
    blockedComposerPresenceCopy,
    unifiedCopy,
    trainingFilePracticeTextCopy,
    trainingHandoffComposerTextCopy,
    resolvedTrainingComposerPlaceholder,
    resolvedCompactUtilityComposerPlaceholder,
    localizedTrainingComposerAccessibilityLabel,
    localizedTrainingComposerSubmitAriaLabel,
    localizedTrainingComposerSummary,
    allowEmptyTrainingReturnSubmission,
    trainingVerifyFileVisible,
    showComposerTrainingVerify,
    renderResourcesView,
    learningPrimaryAction,
    renderPlanView,
    learningSummary,
    handleSubmit,
  } = ctxAfterE5b;

  const renderSettingsView = () => (
    <SettingsRoute
      language={layout.composerLanguage}
      fallbackLabel={t.settings}
      settingsProps={{
        sectionRequest: settingsSectionRequest,
        skillSharing: renderSkillSharing(),
        companionInstallState,
        capabilityVerdict,
        providerImageInputState,
        providerStatus,
        coachDefaultsStatus,
        workspaceControlStatus,
        coachStateSummary: resolvedCoachStateSummary,
        reviewRhythmSummary: resolvedCoachReview,
        onCoachSettingsMutated: queueCoachSettingsSave,
        onSaveCoachSettings: () => persistCoachSettings(),
        onSaveProvider: saveProviderDraft,
        onUseProviderTemplateLabel: useProviderTemplateByLabel,
        providerSaveBusy: settingsActionState?.kind === "save-provider",
        ...providerSettingsActions,
        onCancelProviderTest: cancelProviderTest,
      }}
      contextualRail={renderContextualResultRail("settings")}
    />
  );

  const renderWorkbenchSurface = (view: ActiveWorkbenchView) => {
    switch (view) {
      case "resources": return renderDockedView("resources", renderResourcesView());
      case "settings": return renderDockedView("settings", renderSettingsView());
      default: return renderCoachRootView();
    }
  };

  // The learning drawer's content is assembled outside App: the shell file
  // wires the workbench, the drawer owns its own cards.
  const learningDrawerSections = useLearningDrawerSections({
    language: layout.composerLanguage,
    summary: learningSummary,
    goalActionTitle: learningPrimaryAction.title,
    planDetail: renderPlanView(),
    operationMessage,
    operationMessageSurface,
    goal: {
      active: Boolean(goalMode || goalText.trim()),
      paused: goalPaused,
      onPause: () => {
        pauseGoal();
        requestGoalControl("pause");
      },
      onResume: () => {
        resumeGoal();
        requestGoalControl("resume");
      },
      onClear: () => {
        clearGoal();
      },
    },
    reviewItems: planReviewItems,
    onReviewQueueStart: handleReviewQueueAction,
    onOpenReviewQueue: () => {
      useWorkbenchState.getState().openTrainingReviewQueue();
      closeLearningDrawer();
    },
  });

  const workbenchShell = (
      <AppShell
        language={layout.composerLanguage}
        direction={uiDirection}
        activeView={activeView}
        context={data.workspaceName}
        historyOpen={openMenu === "history"}
        onHistory={() => {
          // One utility surface at a time: the history drawer and the learning
          // drawer are both overlays, and two open overlays cover each other.
          closeLearningDrawer();
          toggleComposerHistoryMenu();
        }}
        learningOpen={layout.learningDrawerOpen === true}
        onLearning={() => {
          setOpenMenu(undefined);
          if (layout.learningDrawerOpen) {
            closeLearningDrawer();
          } else {
            openLearningDrawer(layout.learningSection ?? "goal");
          }
        }}
        onNavigate={setActiveView}
        surfaceControl={
          editorPanelSurface ? (
            <WorkbenchSurfaceButton
              mode="collapse"
              label={appUiCopy(layout.composerLanguage, "收起回侧边栏")}
              onClick={requestCollapseToSidebar}
            />
          ) : undefined
        }
      >
      <input
        ref={uploadFilesInputRef}
        aria-hidden="true"
        className="sr-only"
        hidden
        multiple
        tabIndex={-1}
        type="file"
        onChange={(event) => {
          const nextFiles = Array.from(event.currentTarget.files ?? []);
          void handleBrowserUploads(nextFiles);
          event.currentTarget.value = "";
        }}
      />
      <DirectoryInput
        ref={uploadFolderInputRef}
        aria-hidden="true"
        className="sr-only"
        hidden
        multiple
        tabIndex={-1}
        type="file"
        webkitdirectory=""
        onChange={(event) => {
          const nextFiles = Array.from(event.currentTarget.files ?? []);
          void handleBrowserUploads(nextFiles);
          event.currentTarget.value = "";
        }}
      />
      {openMenu === "history" ? (
        <UtilityOverlay label={appUiCopy(layout.composerLanguage, "历史会话")} closeLabel={appUiCopy(layout.composerLanguage, "关闭")} onClose={() => setOpenMenu(undefined)}>
            <CoachHistoryDrawer
              zh={layout.composerLanguage === "zh-CN"}
              language={layout.composerLanguage}
              sessions={coachSessions}
              status={coachSessionsStatus}
              statusMessage={coachSessionsMessage}
              onActivate={activateCoachSession}
              onRefresh={requestCoachSessions}
              onNewChat={() => {
                clearGoal();
                // A new conversation belongs to the Chat destination even when
                // the drawer was opened from Resources; the host snapshot may
                // still carry the previous active view.
                setActiveView("coach");
                startNewCoachChat();
              }}
              onClose={() => setOpenMenu(undefined)}
            />
        </UtilityOverlay>
      ) : null}

      {operationMessage && operationMessageVisible
        && operationMessageSurface !== "training"
        && operationMessageSurface !== "plan"
        && !(operationMessageSurface === "global" && operationMessage.tone === "success" && activeView !== "coach" && activeView !== "settings") ? (
        <div className="template-global-state">
          <SystemState kind={operationMessage.tone === "error" ? "recoverable-error" : operationMessage.tone === "success" ? "success" : "information"}
            title={sanitizeErrorSurfaceText(operationStatusMessageText(operationMessage, layout.composerLanguage), layout.composerLanguage)}>
            {operationMessage.tone === "error" ? <button type="button" className="template-back" aria-label={appUiCopy(layout.composerLanguage, "关闭提示")} onClick={dismissOperationMessage}>×</button> : null}
          </SystemState>
        </div>
      ) : null}

      {/* One positioned body under the header: the conversation and the
          composer share it, so the learning modal can cover both. */}
      <div className="trainer-body">
      <main
        className={`view-content${activeView === "coach" ? "" : " view-content--docked"}`}
        ref={viewContentRef}
      >
      {hasReceivedHostState || isBrowserPreview || injectedBootstrapAvailable ? (
        <WorkbenchSurfaces key={surfaceInstanceKey} activeView={activeView} render={renderWorkbenchSurface} />
      ) : (
        <SystemState kind="loading" title={appUiCopy(layout.composerLanguage, "正在加载{v}…").replace("{v}", "Trainer")} />
      )}
        {composerActionPreview?.scope === attachmentScope && !streaming.isStreaming ? (
          <div className="unified-composer-preview" data-unified-action-preview={composerActionPreview.kind} role="group" aria-label={unifiedCopy.actionPreview}>
            <strong>{unifiedCopy.actionPreview}</strong>
            {composerActionPreview.detail ? <span className="template-metadata">{composerActionPreview.detail}</span> : null}
            <p>{composerActionPreview.text}</p>
            <div className="unified-composer-preview__actions">
              <button className="button button--accent" type="button" onClick={() => confirmComposerActionPreview(handleSubmit)}>{unifiedCopy.confirm}</button>
              <button className="button button--ghost" type="button" onClick={() => setComposerActionPreview(undefined)}>{unifiedCopy.cancel}</button>
            </div>
          </div>
        ) : null}
      </main>

      {/* The composer stays mounted under the learning modal: the sheet covers
          it while the drawer is open, so the draft and the focus survive. */}
      {showComposerShell ? (
      <footer
        className="composer-shell composer-shell--quiet"
      >
          <div ref={composerShellRef}>
            {showComposerPresenceBar ? (
              <div className="composer-presencebar">
                {showComposerProviderNote ? (
                  <div className="composer-presencebar__context">
                    <div className="composer-presencebar__copy">
                      <span>{providerSendState.warning}</span>
                    </div>
                  </div>
                ) : null}
                {showComposerBlockingNotice ? (
                  <button
                    className="composer-presencebar__blocked"
                    type="button"
                    aria-label={
                      workspaceSessionBlocked
                        ? workspaceSessionBlockTitle
                        : `${t.openSettings}: ${blockedComposerPresenceDetail}`
                    }
                    onClick={() => {
                      if (workspaceSessionBlocked) {
                        openWorkspaceAdmission();
                        return;
                      }
                      useWorkbenchState.getState().requestSettingsCategory("connection");
                      setActiveView("settings");
                    }}
                  >
                    <span className="composer-presencebar__blocked-icon" aria-hidden="true">
                      <WarningIcon size={14} />
                    </span>
                    <span className="composer-presencebar__blocked-copy">
                      {workspaceSessionBlocked ? (
                        <strong>{workspaceSessionBlockTitle}</strong>
                      ) : (
                        <strong>{providerSetupState.actionLabel}</strong>
                      )}
                      <span>
                        {workspaceSessionBlocked
                          ? workspaceSessionBlockMessage
                          : blockedComposerPresenceCopy}
                      </span>
                    </span>
                    <ChevronRightIcon
                      size={12}
                      className="composer-presencebar__blocked-chevron"
                      aria-hidden="true"
                    />
                  </button>
                ) : null}
              </div>
            ) : null}

            <CoachComposer
              attachmentScope={composerUsesTrainingFlow ? `${attachmentScope}\u0000${activityDraftKey}\u0000${trainingComposerPhase}` : attachmentScope}
              density={composerModelActionDensity}
              value={composerUsesTrainingFlow ? activityDraft : draft}
              onChange={(value) => {
                setComposerActionPreview(undefined);
                if (composerUsesTrainingFlow) {
                  setDismissedComposerDeck(undefined);
                  setActivityDraft(value);
                } else {
                  handleComposerDraftChange(value);
                }
              }}
              onSubmit={() => { void handleSubmit(); }}
              onQueueSubmit={composerUsesTrainingFlow ? undefined : queueCurrentComposerDraft}
              queueBanner={
                queuedFollowUps.length > 0 ? (() => {
                  const queueCopy = QUEUED_BANNER_COPY[layout.composerLanguage] ?? QUEUED_BANNER_COPY["en-US"];
                  return (
                  <div className="composer__queue-banner" role="region" aria-label={queueCopy.regionLabel}>
                    <div className="composer__queue-banner__header">
                      <span>{queueCopy.summary(queuedFollowUps.length)}</span>
                    </div>
                    {queuedFollowUps.map((item, idx) => (
                      <div key={item.id} className="composer__queue-banner__row">
                        <span className="composer__queue-banner__text" title={item.text}>
                          {item.text || queueCopy.imagePlaceholder}
                        </span>
                        <span className="composer__queue-banner__actions">
                          {idx === 0 ? (
                            <button
                              type="button"
                              className="button button--ghost button--compact"
                              onClick={() => handleCancelStream({ restoreDraft: false })}
                            >
                              {queueCopy.sendNow}
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="button button--ghost button--compact"
                            onClick={() => {
                              setQueuedFollowUps((current) => current.filter((entry) => entry.id !== item.id));
                              if (!composerUsesTrainingFlow) {
                                if (item.text) {
                                  setComposerDraft(draft.trim() ? `${draft.trim()}\n${item.text}` : item.text, composerDraftScope);
                                }
                                if (item.attachments?.length) {
                                  setComposerAttachments([...composerAttachments, ...item.attachments]);
                                }
                                requestCoachComposerFocus();
                              }
                            }}
                          >
                            {queueCopy.edit}
                          </button>
                          <button
                            type="button"
                            className="button button--ghost button--compact"
                            aria-label={queueCopy.remove}
                            onClick={() =>
                              setQueuedFollowUps((current) => current.filter((entry) => entry.id !== item.id))
                            }
                          >
                            ×
                          </button>
                        </span>
                      </div>
                    ))}
                  </div>
                  );
                })() : undefined
              }
              onCancel={handleCancelStream}
              mentionItems={composerMentionItems}
              onMentionSelect={handleComposerMentionSelect}
              onNavigateHistory={composerUsesTrainingFlow ? undefined : navigateComposerHistory}
              placeholder={
                (composerUsesTrainingFlow || inlinePracticeAwaitingComposerSubmission) && !workspaceSessionBlocked
                  ? resolvedTrainingComposerPlaceholder
                  : workspaceSessionBlocked && !canCaptureGoalBeforeWorkspaceSetup && !canChatBeforeProjectAdmission
                  ? workspaceSessionBlockMessage ?? ""
                  : activeView !== "coach" && !normalizedDraft
                    ? resolvedCompactUtilityComposerPlaceholder
                    : goalDraftPending
                      ? goalModeCopy.placeholder
                      : blockedComposerFallback
              }
              disabled={
                workspaceSessionBlocked &&
                !canCaptureGoalBeforeWorkspaceSetup &&
                !canChatBeforeProjectAdmission
              }
              submitDisabled={
                canCaptureGoalBeforeWorkspaceSetup || canChatBeforeProjectAdmission
                  ? !normalizedDraft || imageAttachmentSendBlocked
                  : composerSendBlocked || imageAttachmentSendBlocked
              }
              submitBlockedReason={imageAttachmentBlockedReason}
              busy={
                streaming.isStreaming ||
                isOperationReliabilityInFlight(streaming.reliabilityPhase) ||
                trainingPersistencePending
              }
              busyLabel={
                trainingPersistencePending
                  ? appUiCopy(layout.composerLanguage, "保存中")
                  : t.streaming
              }
              submitLabel=""
              accessibilityLabel={localizedTrainingComposerAccessibilityLabel}
              submitAriaLabel={
                (composerUsesTrainingFlow || inlinePracticeAwaitingComposerSubmission) && trainingComposerReflectMode
                  ? templateCopy[layout.composerLanguage].recordReflection
                  : localizedTrainingComposerSubmitAriaLabel
              }
              emptySubmitAriaLabel={
                !trainingComposerTalkMode && (composerUsesTrainingFlow || inlinePracticeAwaitingComposerSubmission) && trainingComposerReflectMode
                  ? trainingHandoffComposerTextCopy.reflectEmptySubmitAriaLabel
                  : undefined
              }
              allowEmptySubmit={allowEmptyTrainingReturnSubmission}
              language={layout.composerLanguage}
              minRows={2}
              summary={activeView === "coach" || allowEmptyTrainingReturnSubmission ? localizedTrainingComposerSummary : undefined}
              hintText={activeView === "coach" && providerCanCoachNow && !providerBlockReason ? composerSurfaceHint() : undefined}
              shortcutHint={activeView === "coach" ? composerShortcutHint({
                language: layout.composerLanguage,
                hasCommandDeck: normalizedDraft.startsWith("/") && matchingLocalCommands.length > 0,
                hasContextMenu: openMenu === "context",
              }) : undefined}
              accessory={
                <>
                  {openMenu ? (
                    // Click-anywhere-outside to close: a transparent layer
                    // under the panel that swallows the first outside click.
                    <div
                      className="composer-menu-backdrop"
                      onClick={() => setOpenMenu(undefined)}
                      aria-hidden="true"
                    />
                  ) : null}
                  {renderComposerAccessory()}
                  {renderSkillDeck()}
                  {renderCommandDeck()}
                </>
              }
              attachments={composerUsesTrainingFlow ? activityAttachments : composerAttachments}
              onAttachmentsChange={composerUsesTrainingFlow ? setActivityAttachments : setComposerAttachments}
              attachmentsAvailable={providerImageInputState.supported && !(composerUsesTrainingFlow && trainingComposerReflectMode)}
              attachmentsUnavailableReason={
                providerImageInputState.detail ?? providerImageInputState.reason
              }
              secondaryActions={[
                {
                  // Model + context combined: the ring carries the usage tone,
                  // the label carries model + token estimate, the menu lists
                  // each model's context window.
                  id: "model-switch",
                  compact: composerModelActionDensity === "compact",
                  icon: composerContextRingNode,
                  label: composerContextUsage.used
                    ? `${composerModelButtonDisplayLabel} · ${
                        composerContextUsage.limit
                          ? `${formatTokenCount(composerContextUsage.used)}/${formatTokenCount(
                              composerContextUsage.limit,
                            )}`
                          : `~${formatTokenCount(composerContextUsage.used)}`
                      }`
                    : composerModelButtonDisplayLabel,
                  tone: "ghost" as const,
                  title: [composerModelButtonTitle, composerContextUsageDetail]
                    .filter(Boolean)
                    .join(" · "),
                  ariaLabel: composerModelButtonTitle,
                  onClick: toggleComposerModelMenu,
                },
              ]}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) {
                  return;
                }

                const hasCommandDeck =
                  unifiedCommandSuggestions.length === 0 && !composerUsesTrainingFlow && dismissedComposerDeck !== "command" &&
                  normalizedDraft.startsWith("/") &&
                  matchingLocalCommands.length > 0;
                const hasSkillDeck =
                  !composerUsesTrainingFlow && dismissedComposerDeck !== "skill" &&
                  normalizedDraft.startsWith("$") &&
                  matchingLocalSkills.length > 0;

                if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
                  event.preventDefault();
                  focusComposerInput();
                  return;
                }

                if ((event.metaKey || event.ctrlKey) && event.key === "/") {
                  event.preventDefault();
                  setOpenMenu(openMenu === "context" ? undefined : "context");
                  return;
                }

                if (hasSkillDeck && event.key === "ArrowDown") {
                  event.preventDefault();
                  setSelectedCommandIndex((current) =>
                    current + 1 >= matchingLocalSkills.length ? 0 : current + 1,
                  );
                  return;
                }

                if (hasSkillDeck && event.key === "ArrowUp") {
                  event.preventDefault();
                  setSelectedCommandIndex((current) =>
                    current - 1 < 0 ? matchingLocalSkills.length - 1 : current - 1,
                  );
                  return;
                }

                if (hasSkillDeck && event.key === "Tab" && !event.shiftKey) {
                  event.preventDefault();
                  const selectedSkill = matchingLocalSkills[selectedCommandIndex];
                  if (selectedSkill) {
                    selectSkillSuggestion(selectedSkill);
                  }
                  return;
                }

                if (
                  hasSkillDeck &&
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.metaKey &&
                  !event.ctrlKey
                ) {
                  const selectedSkill = matchingLocalSkills[selectedCommandIndex];
                  const typedTrigger = trainerSkillTriggerToken(normalizedDraft);
                  const alreadyResolvedWithArgs =
                    typedTrigger !== undefined &&
                    normalizedDraft.length > typedTrigger.length &&
                    selectedSkill?.trigger.toLowerCase() === typedTrigger.toLowerCase();
                  if (!alreadyResolvedWithArgs) {
                    event.preventDefault();
                    if (selectedSkill) {
                      selectSkillSuggestion(selectedSkill);
                    }
                    return;
                  }
                  // "$skill args" already resolves to the highlighted skill —
                  // fall through so Enter submits the turn instead of
                  // pointlessly refilling the composer with the same text.
                }

                if (hasCommandDeck && event.key === "ArrowDown") {
                  event.preventDefault();
                  setSelectedCommandIndex((current) =>
                    current + 1 >= matchingLocalCommands.length ? 0 : current + 1,
                  );
                  return;
                }

                if (hasCommandDeck && event.key === "ArrowUp") {
                  event.preventDefault();
                  setSelectedCommandIndex((current) =>
                    current - 1 < 0 ? matchingLocalCommands.length - 1 : current - 1,
                  );
                  return;
                }

                if (hasCommandDeck && event.key === "Tab" && !event.shiftKey) {
                  event.preventDefault();
                  const selectedCommand = matchingLocalCommands[selectedCommandIndex];
                  if (selectedCommand) {
                    setComposerDraft(`${selectedCommand.command} `);
                    setDismissedComposerDeck("command");
                  }
                  return;
                }

                if (
                  hasCommandDeck &&
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.metaKey &&
                  !event.ctrlKey
                ) {
                  event.preventDefault();
                  const selectedCommand = matchingLocalCommands[selectedCommandIndex];
                  if (selectedCommand) {
                    runComposerCommand(selectedCommand);
                  }
                  return;
                }

                if (event.key === "Tab" && !event.shiftKey && !hasCommandDeck && dismissedComposerDeck !== "command" && unifiedCommandSuggestions.length > 0) {
                  event.preventDefault();
                  selectUnifiedCommand(unifiedCommandSuggestions[0]);
                  return;
                }

                if (event.key === "Escape" && (hasCommandDeck || hasSkillDeck || unifiedCommandSuggestions.length > 0)) {
                  event.preventDefault();
                  setDismissedComposerDeck(hasSkillDeck ? "skill" : "command");
                  setSelectedCommandIndex(0);
                  return;
                }

                if (event.key === "Escape" && openMenu) {
                  event.preventDefault();
                  setOpenMenu(undefined);
                  return;
                }

                if (event.key === "Enter" && !event.shiftKey && !event.metaKey && !event.ctrlKey) {
                  event.preventDefault();
                  handleSubmit();
                  return;
                }

                if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                  event.preventDefault();
                  handleSubmit();
                }
              }}
              leadingActions={[
                // The current-file context toggle lives in Settings (advanced
                // context); the composer keeps only the resources entry here.
                ...(activeView === "resources"
                  ? []
                  : [
                      {
                        id: "resources",
                        label: t.resourcesMenu,
                        icon: <ResourcesIcon size={16} />,
                        active: openMenu === "resources",
                        onClick: () => {
                          setOpenMenu(openMenu === "resources" ? undefined : "resources");
                        },
                      },
                    ]),
                {
                  id: "composer-goal-mode",
                  label: goalPaused ? goalModeCopy.resume : goalModeCopy.enter,
                  icon: <TargetIcon size={16} />,
                  active: !goalMode ? goalDraftPending : undefined,
                  focusComposer: true,
                  onClick: () => {
                    setActiveView("coach");
                    if (goalPaused) {
                      resumeGoal();
                      requestGoalControl("resume");
                    } else if (!goalMode) {
                      setPendingGoalScope(goalDraftPending ? undefined : composerSessionKey);
                    }
                    requestCoachComposerFocus();
                  },
                },
                {
                  id: "create-skill",
                  label: appUiCopy(layout.composerLanguage, "创建技能"),
                  icon: <SkillCubeIcon size={16} />,
                  group: composerAddCopy[layout.composerLanguage].skills,
                  onClick: () => {
                    setOpenMenu(undefined);
                    openSkillSettings();
                  },
                },
                ...composerMenuSkills.map((skill) => ({
                  id: `composer-skill-${skill.id}`,
                  label: resolveTrainerSkillText(skill.title, layout.composerLanguage) || skill.trigger,
                  description: resolveTrainerSkillText(skill.detail, layout.composerLanguage),
                  group: composerAddCopy[layout.composerLanguage].skills,
                  icon: <SkillCubeIcon size={16} />,
                  focusComposer: true,
                  onClick: () => selectSkillSuggestion(skill, true),
                })),
                ...(showComposerTrainingVerify && !trainingVerifyFileVisible
                  ? [
                      {
                        id: "composer-verify-file",
                        label: trainingFilePracticeTextCopy.verifyCurrentFile,
                        icon: <CheckMarkIcon size={16} />,
                        onClick: handleVerifyTrainingFromIde,
                      },
                    ]
                  : []),
              ]}
              onAddMenuOpen={() => setOpenMenu(undefined)}
            />
          </div>
        </footer>
      ) : null}

      {/* The learning drawer is a modal sheet at the shell level: it covers
          the conversation and the composer together, while the header (with
          the navigation row and the utilities) stays above it and clickable. */}
      {layout.learningDrawerOpen === true ? (
        <UtilityOverlay
          label={viewLabels[layout.composerLanguage].plan}
          closeLabel={appUiCopy(layout.composerLanguage, "关闭")}
          overlay="learning"
          panelClassName="learning-drawer-panel"
          onClose={closeLearningDrawer}
        >
          <LearningDrawer
            language={layout.composerLanguage}
            section={layout.learningSection ?? "goal"}
            onSectionChange={setLearningSection}
            goal={learningDrawerSections.goal}
            practice={learningDrawerSections.practice}
            progress={learningDrawerSections.progress}
          />
        </UtilityOverlay>
      ) : null}
      </div>
      </AppShell>
  );

  return (
    <I18nProvider language={layout.composerLanguage} direction={uiDirection}>
      <ProviderConnectionContext.Provider value={providerConnection}>
        {isBrowserPreview ? (
          <div className="trainer-preview-workbench" data-preview-frame="sidebar">
            <div className="trainer-preview-sidebar">{workbenchShell}</div>
            <div className="trainer-preview-editor" aria-hidden="true">
              <div className="trainer-preview-editor__chrome" />
              <div className="trainer-preview-editor__canvas" />
            </div>
          </div>
        ) : (
          workbenchShell
        )}
      </ProviderConnectionContext.Provider>
    </I18nProvider>
  );
}
