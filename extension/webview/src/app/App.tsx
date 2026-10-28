import { SystemState } from "../templates/SystemState";
import {
  executeLearningPrimaryAction,
  resolveLearningPrimaryAction,
  type LearningFacts,
} from "../lib/learningActionResolver";
import { readTrainingCardList, readTrainingCardText, resolveBoundTrainingCardFacts } from "../lib/boundTrainingCardFacts";
import { CommandPalette } from "../templates/CommandPalette";
import {
  Suspense,
  forwardRef,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { reviewConceptLabel } from "../lib/reviewLabel";
import { resolveStarterSubjectFamily } from "../lib/courseTemplates";

import { resourceRecordIsAcknowledgedUpload } from "../../../../shared/src/resourceWorkbenchGovernance";
import { trainerCommands } from "../../../../shared/src/commands";
import type { TrainerOperationMessage } from "../../../../shared/src/protocol";
import type { TrainingPlanBinding } from "../../../../shared/src/models";
import { isComposerLanguage } from "../../../../shared/src/types";
import type { ResourceSearchMode } from "../../../../shared/src/resourceSearch";
import { analyzeSendIntent, shouldAttachCurrentFile } from "../../../../shared/src/sendIntelligence";
import { deriveTrainerCapabilityVerdict } from "../../../../shared/src/capabilityVerdict";
import {
  selectScopedSettingsLastTest,
  scopedSettingsCapabilityTruth,
} from "../../../../shared/src/settingsCapabilityGovernance";
import {
  hasSavedProviderProfiles,
  describeProviderImageInputState,
  describeProviderSendState,
  providerErrorHint,
  PROVIDER_TEST_FRESHNESS_WINDOW_MS,
} from "../../../../shared/src/providerStatus";
import {
  filterTrainerSkills,
  mergeSkillCatalog,
  normalizeTrainerCustomSkill,
  normalizeTrainerCustomSkills,
  parseTrainerSkillShare,
  resolveTrainerSkillText,
  serializeTrainerSkillShare,
  trainerSkillCatalog,
  trainerSkillSectionLabel,
  trainerSkillTriggerToken,
  TRAINER_CUSTOM_SKILL_LIMIT,
  type TrainerCustomSkill,
  type TrainerSkillCatalogItem,
  type TrainerSkillContext,
  type TrainerSkillSection,
} from "../../../../shared/src/skillCatalog";
import {
  matchesSavedCoachDefaults,
  sameCoachDefaults,
} from "../../../../shared/src/coachDefaults";
import {
  evaluateProviderModelPolicy,
  filterProviderModelOptions,
  type ProviderModelPolicyReason,
} from "../../../../shared/src/providerModelPolicy";
import {
  buildTrainingCoachBridge,
  composeTrainingCoachBridgeDraft,
} from "../../../../shared/src/trainingCoachBridge";
import {
  deriveTrainingExecutionState,
  isTrainingPrimerLike as isSharedTrainingPrimerLike,
  normalizeTrainingStatus as normalizeSharedTrainingStatus,
  normalizeTrainingSubmode as normalizeSharedTrainingSubmode,
} from "../../../../shared/src/trainingExecutionGovernance";
import { localizeTrainingNextHopLabel } from "../../../../shared/src/trainingHandoffGovernance";
import {
  type SidebarControlCommandId,
  filterSidebarControlCommands,
  findSidebarControlCommand,
  sidebarControlCommandLabel,
} from "../../../../shared/src/sidebarCommands";
import {
  deriveCoachOrientation,
} from "../../../../shared/src/coachOrientationGovernance";
import { isOperationReliabilityInFlight } from "../../../../shared/src/operationReliabilityGovernance";
import {
  buildRecoveredPlanResumeTurn,
  derivePlanOrientation,
  formalPlanIsLiveRuntimeIdentity,
  liveEvidenceBinding,
  liveFormalPlanCadence,
  liveFormalPlanFrozen,
  liveFormalPlanStages,
  liveFormalPlanSummary,
  liveFormalPlanTitle,
  formalTaskIsLiveRuntimeIdentity,
  leftoverTaskGuideFocusIsNotLive,
  leftoverCoachTurnChromeIsNotLive,
  leftoverCoachConversationIsNotLive,
  leftoverSuggestedActionsIsNotLive,
  leftoverMintingSuggestedActionsAreNotLive,
  leftoverFirstLookHeadlineIsNotLive,
  leftoverEvaluationHeadlineIsNotLive,
  leftoverStreamingCheckpointIsNotLive,
  leftoverTransferSkillIsNotLive,
  leftoverTrainingFocusChromeIsNotLive,
  leftoverTrainingHandoffChromeIsNotLive,
  independentTrainingSelectionIsLive,
  leftoverResourceSelectedDetailIsNotLive,
  leftoverResourceSandboxPreviewIsNotLive,
  leftoverResourceSandboxStateIsNotLive,
  leftoverResourceLibraryListIsNotLive,
  leftoverSettingsProfileRhythmIsNotLive,
  leftoverSettingsLearnerProjectOnboardingIsNotLive,
  streakAdaptsWithoutInventingLiveObjects,
  pressureAdaptsWithoutInventingLiveObjects,
  preferRecoveredCoachTaskChrome,
  preferRecoveredCoachTurnChrome,
  preferRecoveredTransferSkill,
  preferRecoveredTrainingFocusChrome,
  preferRecoveredTrainingHandoffChrome,
  formalCardIsLiveRuntimeIdentity,
  liveTrainingFormalSummary,
  liveTrainingSourceFallback,
  liveTrainingFocusFallback,
  liveTrainingTargetSkill,
  liveTrainingTitleFallback,
  liveTrainingNextChallengeTitle,
  liveTrainingWhyNow,
  liveTrainingCoachSummary,
  lockRecoveredPlanVerifyItems,
  preferRecoveredPlanRuntimeFacts,
  scopeEvidenceQueueToRuntimeStep,
  recoveredPlanResumeMessage,
  resolveLivePlanStageChrome,
  type PlanOrientationAction,
  type RecoveredPlanResumeTurn,
} from "../../../../shared/src/planOrientationGovernance";
import {
  deriveResourcesOrientation,
  resolveResourcesBindingIds,
  type ResourcesOrientationAction,
} from "../../../../shared/src/resourcesOrientationGovernance";
import {
  sanitizeErrorSurfaceText,
  waitingComposerEnqueueFailureText,
} from "../../../../shared/src/errorSurfaceSanitizer";
import { readWorkspaceTrustStateFromCapabilitySummary } from "../../../../shared/src/workspaceTrustState";
import {
  deriveOnboardingSteps,
  resolveEffectiveTrustState,
} from "../../../../shared/src/onboarding";
import {
  blockedComposerPresenceMessage,
  blockedComposerSetupMessage,
  providerCoachBanner,
  providerRecoveryLocale,
  providerRecoverySummary,
  providerRecoveryStatusLabel,
  providerSetupSummary,
} from "./providerRecoveryCopy";
import { normalizeTransferSkillStateRecord } from "../../../../shared/src/transferSkillGovernance";
import { CoachHistoryDrawer } from "../components/coach/CoachHistoryDrawer";
import { UtilityOverlay } from "../templates/UtilityOverlay";
import { templateCopy } from "../templates/templateCopy";
import { buildComposerProviderMenuItems, composerModelPolicyHint, compactComposerModelLabel, type ComposerProviderMenuItem } from "../lib/composerModelHelpers";
import { viewLabels, resourcesViewLabel, coachViewLabel, planViewLabel, trainingViewLabel, settingsViewLabel } from "../lib/viewLabels";
import { WorkbenchSurfaces } from "./WorkbenchSurfaces";
import { getSurfaceScrollElement, useSurfaceScroll } from "./useSurfaceScroll";
import { useCoachHistory } from "./useCoachHistory";
import { useMenuState } from "./useMenuState";
import { useComposerModelQuery } from "./useComposerModelQuery";
import { useComposerHistoryNavigation } from "./useComposerHistoryNavigation";
import { useCoachConversationController } from "./useCoachConversationController";
import {
  useLearningPlanController,
  type PlanComposerDraftReplacement,
  type PlanComposerMode,
} from "./useLearningPlanController";
import { useOperationStatusController } from "./useOperationStatusController";
import { useProviderConnectionController } from "./useProviderConnectionController";
import { useTrainingCardController } from "./useTrainingCardController";
import { useShallow } from "zustand/react/shallow";
import { coachReplyTitle, coachReplyMarkdown } from "../lib/shareUtils";
import { formatTokenCount } from "../lib/formatUtils";
import {
  planRuntimeStatusFromRecovery,
  selectStreamingCheckpointForScope,
  streamingCheckpointToOrientation,
} from "../../../../shared/src/workspaceRecoveryGovernance";
import {
  type CoachArtifactBlockData,
  type CoachMessageAction,
  CoachConversationView,
  CoachMessageBubble,
} from "../components/coach";
import { AppShell } from "../templates/AppShell";
import { PracticeResponse } from "../templates/PracticeResponse";
import { ActivityHeader } from "../templates/ActivityHeader";
import { appendDockAnchor, composerDockDraftScope, dockSendNavigation, docksComposer, normalizeDockSendPreference, resolveDockContextAnchor } from "../lib/composerDock";
import { useComposerDockAnchor } from "./useComposerDockAnchor";
import { PLAN_COPY } from "../lib/i18n/segments/planInlineText";
import {
  attestationUndeliveredMessage,
  detectAttestationUndelivered,
  detectTrainerResourceFailure,
  trainerResourceFailureMessage,
  detectTrainingVerificationTargetMismatch,
  detectOperationScopeChanged,
  detectPlanRevisionConflict,
  livePlanTaskGateFailureMessage,
  parseLivePlanTaskGateMarker,
  planRevisionConflictMessage,
  operationScopeChangedMessage,
  trainingVerificationTargetMismatchMessage,
  operationStatusMessageText,
  providerRecoveryMessage,
  recoverableFailureMessage,
  resolveOperationMessageSurface,
  type OperationMessageSurface,
} from "../lib/operationMessageGovernance";
import { resolveTurnNextStepRequiresConfirmation } from "../lib/nextStepConfirmation";
import { CoachComposer, ComposerIconButton, DockReturnToSurfaceBar, DockSendPreferenceSwitch } from "../components/composer";
import { UserFeedbackDisclosure, type UserFeedbackKind } from "../components/common/UserFeedbackDisclosure";
import { WorkbenchSurfaceButton } from "../components/common/WorkbenchSurfaceButton";
import { WorkspaceAdmissionPanel, OnboardingWizard } from "../components/firstlook";
import type {
  ResourceCaptureInput,
  ResourceCaptureFocusOption,
  ResourceMutationOutcome,
  ResourceOrganizeInput,
  ResourceSearchRequest,
} from "../components/resources/ResourcesWorkbenchView";
import {
  parseLibraryFolderTree,
  type LibraryFolderHostAnswer,
  type LibraryFolderListResult,
} from "../lib/libraryFolders";
import {
  applyTrainingCardGrade,
  applyTrainingCardSkip,
  interpretTrainingComposerCardCommand,
} from "../lib/i18n/segments/trainingCardActions";
import type {
  TrainingReviewItem,
  TrainingSummaryCard,
} from "../components/training/TrainingWorkbenchView";
import {
  CheckMarkIcon,
  ChevronRightIcon,
  ContextLayersIcon,
  FolderIcon,
  LinkIcon,
  RefreshIcon,
  ResourcesIcon,
  UploadIcon,
  WarningIcon,
} from "../components/icons";
import { StatusPill } from "../components/StatusPill";
import { applyWorkbenchTheme } from "../lib/theme";
import { I18nProvider } from "../lib/i18n/context";
import { resolveCopy as resolveWorkbenchCopy, type Copy } from "../lib/i18n/copy";
import { resolvePlanComposerCopy } from "../lib/i18n/planComposerCopy";
import { resolveResourceComposerCopy } from "../lib/i18n/resourceComposerCopy";
import { resolvePlanViewCopy } from "../lib/i18n/planViewCopy";
import { resolveTextDirection, type TextDirection } from "../lib/i18n/direction";
import {
  classifyProviderThinkingSupport,
  describeProviderThinking,
  normalizeProviderThinkingConfig,
  synthesizeProviderThinkingDescriptor,
  thinkingProtocolSupportsWire,
} from "../../../../shared/src/providerThinking";
import type {
  ProviderThinkingConfig,
  ProviderThinkingDescriptor,
} from "../../../../shared/src/providerThinking";
import type {
  ActiveWorkbenchView,
  BootstrapData,
  BrowserUploadResourceInput as BrowserUploadResourceInputType,
  CoachAnswerMode,
  CoachDefaults,
  CoachSessionSummary,
  ComposerLanguage,
  ConversationMessage,
  DebugVisibleTrainingFacts,
  EvaluationCheck,
  HostMessage,
  HostProviderTestSummary,
  MessageAttachment,
  PlanStage,
  ProviderConfigView,
  ResourceComposerIntent,
  ResourceTrainingHandoffResult,
  SidebarView,
  SuggestedAction,
  TeachingStyle,
  ThemePreference,
  TrainingCardCandidate,
  TrainingLearningFamily,
  WorkspaceTrainingState,
} from "../lib/types";
import {
  normalizeSidebarView,
  normalizeTeachingStyle,
} from "../lib/types";
import {
  announceReady,
  getInjectedBootstrapState,
  getWorkbenchSurface,
  persistBrowserPreviewProviderConfig,
  postDebugVisibleFacts,
  postMessage,
  requestCollapseToSidebar,
  subscribeToHostMessages,
  requestNativeSkillDraft,
} from "../lib/vscode";
import {
  buildGenericImageReviewPrompt,
  buildScratchPaperVerificationPrompt,
  buildTrainingFeedbackPrompt,
  type TrainingFeedbackPromptInput,
} from "../lib/universalLearningPrompts";
import {
  appUiAltCopy,
  appUiCopy,
  COACH_CHECKPOINT_RECOVERY_COPY,
  COACH_STARTER_PROMPTS,
  PLAN_DRAFT_REPLACEMENT_COPY,
  SCENARIO_TEXT,
  TRAINING_CARD_STATUS_TEXT,
  TRAINING_HANDOFF_STATUS_TEXT,
} from "../lib/i18n/appUiCopy";
import { isBrowserPreviewFixtureMode } from "../lib/browserSidecar";
import { useTrainingCommands, useTrainingAttemptLifecycle } from "./useTrainingCommands";
import { type TrainingRestoreContext, useWorkbenchState } from "./useWorkbenchState";
import { formatReviewDueLabel, learnerSignalLabel } from "../components/settings/useCoachSettingsViewState";
import { ProviderConnectionContext } from "./providerConnectionContext";
import type { PlanReviewItem } from "../components/plan/CoachPlanView";
import type {
  SettingsActionFeedback,
  SettingsSectionStatus,
} from "../components/settings/CoachSettingsView";

// ContextMenu type imported from useMenuState
import {
  CAPTURE_CONFIRMATION_TIMEOUT_MS,
  COACH_REPLY_BODY_MAX_CHARS,
  COACH_SETTINGS_AUTOSAVE_DELAY_MS,
  COMPOSER_MODEL_PICKER_INITIAL_OPTION_LIMIT,
  CoachCheckpointRecoveryAction,
  CoachPlanView,
  CoachSettingsView,
  ComposerDeckKind,
  ComposerModelActionDensity,
  DEFAULT_ANSWER_MODE,
  DEFAULT_TEACHING_STYLE,
  DirectoryInput,
  DockedView,
  LIBRARY_FOLDER_OPERATION_TIMEOUT_MS,
  LocalCommandSuggestion,
  LocalSkillSuggestion,
  MenuList,
  MenuToggleRow,
  OPEN_RESOURCE_SYNC_TIMEOUT_MS,
  ORGANIZE_CONFIRMATION_TIMEOUT_MS,
  PendingResourceOperation,
  PendingResourceTrainingHandoff,
  ProgressView,
  RESOURCE_COMPOSER_MAX_IDS,
  RESOURCE_OPERATION_TIMEOUT_MS,
  RESOURCE_TRAINING_HANDOFF_TIMEOUT_MS,
  RESOURCE_UPLOAD_LIMIT,
  ResourceMutationOperationKind,
  ResourcesComposerMode,
  ResourcesWorkbenchView,
  SettingsActionState,
  SettingsFeedbackState,
  TrainingWorkbenchView,
  UtilityComposerModeOption,
  ViewFallback,
  WorkbenchDataSnapshot,
  activeStageObjectiveText,
  resetBootstrapRequestSent,
  browserFileSupported,
  browserUploadLooksLikeFolder,
  buildLocalCommandSuggestions,
  buildSettingsFeedback,
  captureTargetKind,
  coachDefaultsStatusNote,
  coachFirstComposerPlaceholder,
  coachLaneLabel,
  coachingScenarioLabel,
  compactCoachLine,
  compactDefinedValues,
  composerHintText,
  composerShortcutHint,
  defaultPromptText,
  describeSidecarFailure,
  effectiveConnectionState,
  exportDownloadName,
  focusComposerInput,
  formatCoachDefaultsValue,
  formatContextBundleValue,
  formatSparseCoachDefaultsSavedValue,
  formatSparseWorkspaceControlValue,
  inBrowserPreviewEnvironment,
  isCoachCheckpointRecoveryState,
  isEditingAnotherField,
  isLanguageAlignedUiText,
  isTerminallyTruncatedText,
  joinInlineMeta,
  livePlanTaskMintPendingMessage,
  livePlanUpdatePendingMessage,
  loadBrowserPreviewModule,
  localizeConversationMessage,
  localizeUiViewReferences,
  normalizeInlineComparisonText,
  normalizeOperationMessageKey,
  parseLearningFeedbackStatus,
  parseResourceOperationStatus,
  pickFirstText,
  pickLanguageAlignedTrainingList,
  planComposerDraftReplacementCopy,
  providerBlockingReason,
  providerHasVerifiedToolsProbe,
  providerModelMenuNote,
  providerModelRuntimeNote,
  providerSettingsLocale,
  readBrowserFiles,
  readBrowserPreviewLocationOverrides,
  requestBootstrapOnce,
  resolveCoachBlockingSurface,
  resolveTheme,
  resolveTrainingLearningFamily,
  resolveTrainingLearningSubtype,
  resolveTrainingPracticeVerificationMode,
  restoredTrainingCard,
  sanitizeHostFailureMessage,
  sendContextShortSummary,
  sendStatuslineText,
  skillSectionTargetView,
  syncBootstrapLifecycleOnVisible,
  toPlanReviewItem,
  trainingCardStatusLabel,
  trainingComposerModeText,
  trainingExpectedSymbols,
  trainingFilePracticeText,
  trainingGenerateCardPendingMessage,
  trainingHandoffComposerText,
  trainingHandoffStatusLabel,
  trainingPersistenceFailureMessage,
  triggerLocalDownload,
  triggerResourceUpload,
  truncateInlineText,
  waitForCapturedResource,
  waitForOrganizedResource,
  waitForResourceInSnapshot,
} from "./appHelpers";

export function App() {
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
    setResourceRestoreContext,
    setComposerDraft,
    setComposerSendPreference,
    markDockStaySend,
    clearDockReturnNotice,
    dockReturnNotice,
    setComposerLanguage,
    setComposerAnswerMode,
    setTeachingStyle,
    setContextDetail,
    setIncludeCurrentFile,
    setIncludeSelection,
    setIncludeDiagnostics,
    setIncludeRelatedFiles,
    setFollowCurrentFile,
    setCoachDefaults,
    setThemePreference,
    setLearningSurfaceAlignment,
    applyHostMessage: applyRawHostMessage,
    streamingIsStreaming,
    streamingStreamMessageId,
    streamingStreamError,
    streamingCompletionStopReason,
    streamingReliabilityPhase,
    streamingReliabilityOutcome,
    streamingCompletionNextStepRequiresConfirmation,
    streamingHasAgentActivity,
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
      setResourceRestoreContext: state.setResourceRestoreContext,
      setComposerDraft: state.setComposerDraft,
      setComposerSendPreference: state.setComposerSendPreference,
      markDockStaySend: state.markDockStaySend,
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
      streamingHasAgentActivity: state.streaming.agentActivity.length > 0,
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
  const [settingsSectionRequest, setSettingsSectionRequest] = useState<{ category: "teaching"; requestId: number; skillTrigger?: string }>();
  const [pendingDeleteSkillId, setPendingDeleteSkillId] = useState<string>();
  const [skillDraftFields, setSkillDraftFields] = useState({
    trigger: "",
    title: "",
    detail: "",
    prompt: "",
  });
  const [skillImportText, setSkillImportText] = useState("");
  const composerDeckRef = useRef<HTMLDivElement | null>(null);
  const streamResumeDraftRef = useRef("");
  const sendRecoveredPlanResumeRef = useRef<
    (action: "continue_step" | "clear_blocker") => void
  >(() => undefined);
  const [composerAttachments, setComposerAttachments] = useState<MessageAttachment[]>([]);
  const [composerModelActionDensity, setComposerModelActionDensity] =
    useState<ComposerModelActionDensity>("default");
  const [settingsActionState, updateSettingsActionState] = useState<SettingsActionState>();
  const [settingsFeedbackState, setSettingsFeedbackState] = useState<SettingsFeedbackState>({});
  const settingsScopeKey = `${syncCursor.generation}\0${syncCursor.workspaceId}\0${syncCursor.sessionId}`;
  const settingsScopeRef = useRef(settingsScopeKey);
  const settingsActionScopeRef = useRef(settingsScopeKey);
  useEffect(() => {
    if (settingsScopeRef.current !== settingsScopeKey) {
      // An old request cannot finish a new conversation's local busy state.
      // Keep the connection draft so the learner can retry after the handshake.
      updateSettingsActionState(undefined);
      setSettingsFeedbackState({});
      settingsScopeRef.current = settingsScopeKey;
    }
  }, [settingsScopeKey]);
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
  // §十一: companion install state for the Settings remote-support panel.
  const [companionInstallState, setCompanionInstallState] = useState<
    import("../../../../shared/src/companionInstallState").CompanionInstallState
  >("not_installed");
  const companionStateQueriedRef = useRef(false);
  const [resourcesComposerMode, setResourcesComposerMode] =
    useState<ResourcesComposerMode>("locate");
  const [selectedResourceContextIds, setSelectedResourceContextIds] = useState<string[]>([]);
  const [resourceConversationContextIds, setResourceConversationContextIds] = useState<string[]>([]);
  const [resourcesViewSearchQuery, setResourcesViewSearchQuery] = useState("");
  const composerShellRef = useRef<HTMLDivElement | null>(null);
  const hostMessageSequenceRef = useRef(0);
  const coachRuntimeContextSignatureRef = useRef<string | undefined>(undefined);
  const composerModelSearchRef = useRef<HTMLInputElement | null>(null);
  const viewContentRef = useRef<HTMLElement | null>(null);
  const uploadFilesInputRef = useRef<HTMLInputElement | null>(null);
  const uploadFolderInputRef = useRef<HTMLInputElement | null>(null);
  const resourceOperationResolversRef = useRef(new Map<string, PendingResourceOperation>());
  const resourceOperationSequenceRef = useRef(0);
  const resourceTrainingHandoffResolversRef = useRef(
    new Map<string, PendingResourceTrainingHandoff>(),
  );
  const resourceTrainingHandoffSequenceRef = useRef(0);
  const coachAutoScrollPinnedRef = useRef(true);
  const pinCoachScrollToBottom = useCallback(() => {
    coachAutoScrollPinnedRef.current = true;
  }, []);
  // §三: the conversation domain owns its local interaction state (echoes,
  // pending reply action, preview session id, last-turn view, transition).
  const {
    optimisticTurns,
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
  // §三: the plan-composer domain owns its composer mode/context/draft state.
  const {
    planComposerMode,
    setPlanComposerMode,
    coachPlanContext,
    setCoachPlanContext,
    pendingPlanComposerDraftReplacement,
    setPendingPlanComposerDraftReplacement,
  } = useLearningPlanController();
  const [userFeedbackState, setUserFeedbackState] = useState<{
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
  const pendingLivePlanTaskMintRef = useRef<{ commandId: string } | undefined>();
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
  const isBrowserPreview = inBrowserPreviewEnvironment();
  const activeView = normalizeSidebarView(layout.activeView);
  const browserPreviewFixture = isBrowserPreviewFixtureMode();
  // The same bundle runs in the sidebar view and in the full-width editor
  // panel; only the sidebar offers "open in editor", and only the panel offers
  // "back to sidebar".
  const editorPanelSurface = getWorkbenchSurface() === "editor";
  const canOpenInEditor = !editorPanelSurface && !isBrowserPreview;
  const openViewInEditor = useCallback((view: "plan" | "resources") => {
    postMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.openViewInEditor, payload: { view } },
    });
  }, []);
  const expandToEditorLabel = appUiCopy(layout.composerLanguage, "在编辑器中打开");
  const t = resolveWorkbenchCopy(layout.composerLanguage);
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
  const setSettingsActionState = useCallback((next?: SettingsActionState) => {
    // A repeated connection test can return the same text as the previous one.
    // Clear the previous outcome when starting, rather than treating identical
    // text as an outstanding operation forever.
    if (next) {
      settingsActionScopeRef.current = settingsScopeKey;
      setOperationMessage(undefined);
      updateSettingsActionState({ ...next, baselineMessageKey: undefined });
    } else {
      updateSettingsActionState(undefined);
    }
  }, [setOperationMessage, settingsScopeKey]);
  const handleResourceSelectionChange = useCallback(
    (resourceIds: string[], reason?: "selection" | "unmount") => {
      setSelectedResourceContextIds(resourceIds);
      if (reason !== "unmount") {
        setResourceConversationContextIds(resourceIds);
      }
    },
    [],
  );
  const resolveResourceOperationStatus = useCallback((message: HostMessage): HostMessage => {
    const status = parseResourceOperationStatus(message, localizedResourceOperationFallback);
    if (!status || message.type !== "operation/status") {
      return message;
    }
    const operation = resourceOperationResolversRef.current.get(status.requestId);
    if (operation?.kind === status.kind) {
      // The settling text travels with the operation: a caller that needs the
      // concrete outcome (an exported filename) reads it without a second wait.
      operation.statusMessage = status.message;
      resourceOperationResolversRef.current.delete(status.requestId);
      window.clearTimeout(operation.timeoutId);
      if (message.payload.tone === "error") {
        operation.reject(new Error(status.message));
      } else {
        operation.resolve();
      }
    }
    return {
      ...message,
      payload: { ...message.payload, message: status.message },
    };
  }, [localizedResourceOperationFallback]);
  const requestResourceMutation = useCallback(
    (kind: ResourceMutationOperationKind, resourceIds: string[]): Promise<void> => {
      const requestId = `resource-operation-${Date.now().toString(36)}-${++resourceOperationSequenceRef.current}`;
      return new Promise<void>((resolve, reject) => {
        const timeoutId = window.setTimeout(() => {
          const operation = resourceOperationResolversRef.current.get(requestId);
          if (!operation || operation.kind !== kind) {
            return;
          }
          resourceOperationResolversRef.current.delete(requestId);
          operation.reject(new Error("Resource operation timed out."));
        }, RESOURCE_OPERATION_TIMEOUT_MS);
        resourceOperationResolversRef.current.set(requestId, { kind, resolve, reject, timeoutId });
        try {
          postMessage({
            type: "command/execute",
            payload: {
              commandId:
                kind === "delete" ? trainerCommands.deleteResource : trainerCommands.restoreResource,
              payload: { resourceIds, __trainerResourceOperationId: requestId },
            },
          });
        } catch (error) {
          const operation = resourceOperationResolversRef.current.get(requestId);
          resourceOperationResolversRef.current.delete(requestId);
          if (operation) {
            window.clearTimeout(operation.timeoutId);
            operation.reject(error);
          } else {
            reject(error);
          }
        }
      });
    },
    [],
  );
  const requestResourceIndex = useCallback((): Promise<void> => {
    const requestId = `resource-operation-${Date.now().toString(36)}-${++resourceOperationSequenceRef.current}`;
    return new Promise<void>((resolve, reject) => {
      const timeoutId = window.setTimeout(() => {
        const operation = resourceOperationResolversRef.current.get(requestId);
        if (!operation || operation.kind !== "index") {
          return;
        }
        resourceOperationResolversRef.current.delete(requestId);
        operation.reject(new Error("Resource indexing timed out."));
      }, RESOURCE_OPERATION_TIMEOUT_MS);
      resourceOperationResolversRef.current.set(requestId, {
        kind: "index",
        resolve,
        reject,
        timeoutId,
      });
      try {
        postMessage({
          type: "command/execute",
          payload: {
            commandId: trainerCommands.indexResources,
            payload: { __trainerResourceOperationId: requestId },
          },
        });
      } catch (error) {
        const operation = resourceOperationResolversRef.current.get(requestId);
        resourceOperationResolversRef.current.delete(requestId);
        if (operation) {
          window.clearTimeout(operation.timeoutId);
          operation.reject(error);
        } else {
          reject(error);
        }
      }
    });
  }, []);
  const requestCoachReplyUpload = useCallback(
    (message: ConversationMessage): Promise<void> => {
      const requestId = `resource-operation-${Date.now().toString(36)}-${++resourceOperationSequenceRef.current}`;
      return new Promise<void>((resolve, reject) => {
        const timeoutId = window.setTimeout(() => {
          const operation = resourceOperationResolversRef.current.get(requestId);
          if (!operation || operation.kind !== "upload") {
            return;
          }
          resourceOperationResolversRef.current.delete(requestId);
          operation.reject(new Error("Resource upload timed out."));
        }, RESOURCE_OPERATION_TIMEOUT_MS);
        resourceOperationResolversRef.current.set(requestId, {
          kind: "upload",
          resolve,
          reject,
          timeoutId,
        });
        try {
          const replyDoc = coachReplyMarkdown(message, layout.composerLanguage);
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.uploadResource,
              payload: {
                uploads: [
                  {
                    kind: "markdown",
                    name: replyDoc.title,
                    source: "coach-reply",
                    content: replyDoc.markdown,
                    contentEncoding: "utf-8",
                    tags: ["coach-reply"],
                    sourceType: "file",
                  },
                ],
                __trainerResourceOperationId: requestId,
              },
            },
          });
        } catch (error) {
          const operation = resourceOperationResolversRef.current.get(requestId);
          resourceOperationResolversRef.current.delete(requestId);
          if (operation) {
            window.clearTimeout(operation.timeoutId);
            operation.reject(error);
          } else {
            reject(error);
          }
        }
      });
    },
    [layout.composerLanguage],
  );
  const handleCoachMessageAction = useCallback(
    async (action: CoachMessageAction, message: ConversationMessage) => {
      if (action === "retry") {
        // Regenerate: re-send the user prompt that produced this reply.
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
        appendOptimisticTurn(prompt);
        postMessage({
          type: "session/sendStreamMessage",
          payload: {
            text: prompt,
            intent: "coach",
            stream: true,
            resourceIds: [],
            includeCurrentFile: false,
            includeSelection: false,
            includeDiagnostics: false,
            includeRelatedFiles: false,
            contextDetail: "balanced",
            responseLanguage: layout.composerLanguage,
            activeView: "coach",
            requestId: `coach-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
          },
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
            const browserPreview = await loadBrowserPreviewModule();
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
      const excerpt =
        message.body.trim().length > COACH_REPLY_BODY_MAX_CHARS
          ? `${message.body.trim().slice(0, COACH_REPLY_BODY_MAX_CHARS)}…`
          : message.body.trim();
      postMessage({
        type: "command/execute",
        payload: {
          commandId: trainerCommands.trainingGenerateCard,
          payload: {
            source: "conversation_gap",
            cardType: "practice",
            prompt: excerpt,
            // Live browser preview reads contextHint directly; the host rebuilds
            // it from prompt. Send both so the reply reaches the card generator.
            contextHint: excerpt,
            focusArea: replyDoc.title,
          },
        },
      });
    },
    [
      isBrowserPreview,
      layout.composerLanguage,
      previewSessionId,
      requestCoachReplyUpload,
      setOperationMessage,
    ],
  );
  const requestResourceSearch = useCallback(
    ({ query, requestId }: ResourceSearchRequest): Promise<void> => {
      return new Promise<void>((resolve, reject) => {
        const timeoutId = window.setTimeout(() => {
          const operation = resourceOperationResolversRef.current.get(requestId);
          if (!operation || operation.kind !== "search") {
            return;
          }
          resourceOperationResolversRef.current.delete(requestId);
          operation.reject(new Error("Resource search timed out."));
        }, RESOURCE_OPERATION_TIMEOUT_MS);
        resourceOperationResolversRef.current.set(requestId, {
          kind: "search",
          resolve,
          reject,
          timeoutId,
        });
        try {
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.searchResources,
              payload: { query, requestId, mode: layout.resourceSearchMode },
            },
          });
        } catch (error) {
          const operation = resourceOperationResolversRef.current.get(requestId);
          resourceOperationResolversRef.current.delete(requestId);
          if (operation) {
            window.clearTimeout(operation.timeoutId);
            operation.reject(error);
          } else {
            reject(error);
          }
        }
      });
    },
    [layout.resourceSearchMode],
  );
  const requestBrowserPreviewResourceSearch = useCallback(
    async ({ query, requestId }: ResourceSearchRequest): Promise<void> => {
      if (!isBrowserPreview || browserPreviewFixture) {
        return;
      }
      const browserPreview = await loadBrowserPreviewModule();
      const result = await browserPreview.searchBrowserPreviewResources(
        { query, requestId, mode: layout.resourceSearchMode },
        previewSessionId,
      );
      setPreviewSessionId(result.sessionId);
      applyRawHostMessage(result.message);
    },
    [
      applyRawHostMessage,
      browserPreviewFixture,
      isBrowserPreview,
      layout.resourceSearchMode,
      previewSessionId,
    ],
  );
  const requestResourceTrainingHandoff = useCallback(
    (resourceId: string): Promise<ResourceTrainingHandoffResult> => {
      const requestId = `resource-training-${Date.now().toString(36)}-${++resourceTrainingHandoffSequenceRef.current}`;
      return new Promise<ResourceTrainingHandoffResult>((resolve) => {
        const timeoutId = window.setTimeout(() => {
          const handoff = resourceTrainingHandoffResolversRef.current.get(requestId);
          if (!handoff) {
            return;
          }
          resourceTrainingHandoffResolversRef.current.delete(requestId);
          handoff.resolve({ requestId, resourceId, outcome: "failed" });
        }, RESOURCE_TRAINING_HANDOFF_TIMEOUT_MS);
        resourceTrainingHandoffResolversRef.current.set(requestId, { resourceId, resolve, timeoutId });
        try {
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.trainingGenerateCard,
              payload: {
                source: "resource_knowledge",
                cardType: "flash",
                submode: "flash",
                resourceId,
                __trainerResourceTrainingHandoffId: requestId,
              },
            },
          });
        } catch {
          const handoff = resourceTrainingHandoffResolversRef.current.get(requestId);
          resourceTrainingHandoffResolversRef.current.delete(requestId);
          if (handoff) {
            window.clearTimeout(handoff.timeoutId);
          }
          resolve({ requestId, resourceId, outcome: "failed" });
        }
      }).then((result) => {
        if (result.outcome === "ready") {
          setActiveView("training");
        }
        return result;
      });
    },
    [setActiveView],
  );
  const submitUserFeedback = useCallback(
    (kind: UserFeedbackKind) => {
      if (userFeedbackState.busy || userFeedbackState.submittedKind || isBrowserPreview) return;
      userFeedbackPendingKindRef.current = kind;
      const requestId = `learning-feedback-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
      userFeedbackRequestIdRef.current = requestId;
      setUserFeedbackState({ busy: true });
      postMessage({
        type: "command/execute",
        payload: {
          commandId: trainerCommands.recordUserFeedback,
          payload: {
            kind,
            message: appUiCopy(layout.composerLanguage, "这一步不合适。"),
            scenario: activeView === "training" ? "training" : "coach",
            focusArea: data.memory.workspace?.latestLearningFocusArea,
            trainingCardId: undefined,
            planId: data.plan?.id,
            requestId,
          },
        },
      });
      window.clearTimeout(userFeedbackTimeoutRef.current);
      userFeedbackTimeoutRef.current = window.setTimeout(() => {
        setUserFeedbackState((current) => current.busy ? { busy: false, error: appUiCopy(layout.composerLanguage, "反馈未收到确认，可重试。") } : current);
      }, 12000);
    },
    [activeView, data.memory.workspace, data.plan?.id, isBrowserPreview, layout.composerLanguage, postMessage, userFeedbackState.busy, userFeedbackState.submittedKind],
  );

  useEffect(() => {
    return () => {
      window.clearTimeout(userFeedbackTimeoutRef.current);
      for (const operation of resourceOperationResolversRef.current.values()) {
        window.clearTimeout(operation.timeoutId);
        operation.reject(new Error("Resource operation was interrupted."));
      }
      resourceOperationResolversRef.current.clear();
      for (const handoff of resourceTrainingHandoffResolversRef.current.values()) {
        window.clearTimeout(handoff.timeoutId);
        handoff.resolve({
          requestId: "",
          resourceId: handoff.resourceId,
          outcome: "failed",
        });
      }
      resourceTrainingHandoffResolversRef.current.clear();
    };
  }, []);
  // ---------------------------------------------------------- library folders
  // The host answers a folder request (list / create / rename / delete) with a
  // `library/folders` message carrying the request's operationId — the same
  // correlation pattern as `training/resourceHandoff`. A request that never
  // gets an answer inside its bounded window resolves as unconfirmed, so the
  // view never invents a folder write.
  const libraryFolderResolversRef = useRef<
    Map<string, { timeoutId: number; resolve: (answer: LibraryFolderHostAnswer) => void }>
  >(new Map());
  const resolveLibraryFolderOperation = useCallback(
    (payload: { operationId?: string; ok: boolean; folders?: unknown; message?: string }) => {
      const operationId = String(payload.operationId ?? "").trim();
      if (!operationId) {
        return;
      }
      const pending = libraryFolderResolversRef.current.get(operationId);
      if (!pending) {
        return;
      }
      libraryFolderResolversRef.current.delete(operationId);
      window.clearTimeout(pending.timeoutId);
      pending.resolve({
        ok: payload.ok,
        message: typeof payload.message === "string" ? payload.message.trim() : "",
        folders: payload.folders,
      });
    },
    [],
  );
  useEffect(() => {
    return () => {
      for (const pending of libraryFolderResolversRef.current.values()) {
        window.clearTimeout(pending.timeoutId);
        pending.resolve({ ok: false, message: "", unconfirmed: true });
      }
      libraryFolderResolversRef.current.clear();
    };
  }, []);
  const applyHostMessage = useCallback(
    (message: HostMessage, isProviderActionOverride = false) => {
      hostMessageSequenceRef.current += 1;
      // Reply uploads settle through their request-id acknowledgement. An
      // unrelated status (for example Trash refresh) must not enable duplicates.
      if (message.type === "operation/status" || message.type === "stream/start") {
        clearPendingMessageActionUnless(":save-resource");
      }
      if (message.type === "remoteCompanion/state") {
        setCompanionInstallState(
          message.payload.state as import("../../../../shared/src/companionInstallState").CompanionInstallState,
        );
        return;
      }
      // §三: the training-card controller owns remote-verification state and
      // its request identity; it consumes every remoteVerification/* message.
      if (handleRemoteVerificationHostMessage(message)) {
        return;
      }
      if (message.type === "training/resourceHandoff") {
        const handoff = resourceTrainingHandoffResolversRef.current.get(message.payload.requestId);
        if (handoff?.resourceId === message.payload.resourceId) {
          resourceTrainingHandoffResolversRef.current.delete(message.payload.requestId);
          window.clearTimeout(handoff.timeoutId);
          handoff.resolve(message.payload);
        }
        return;
      }
      // Folder space answers (list/create/rename/delete) settle their request.
      if (message.type === "library/folders") {
        resolveLibraryFolderOperation(message.payload);
        return;
      }
      if (message.type === "training/persistenceAck") {
        resolveTrainingPersistenceAck(message);
        return;
      }
      if (handleProviderSpeedTestMessage(message)) {
        return;
      }
      if (message.type === "session/list") {
        applySessionList(message.payload);
        return;
      }
      const learningFeedbackStatus = parseLearningFeedbackStatus(message);
      if (
        learningFeedbackStatus &&
        userFeedbackRequestIdRef.current === learningFeedbackStatus.requestId
      ) {
        userFeedbackRequestIdRef.current = undefined;
        window.clearTimeout(userFeedbackTimeoutRef.current);
        setUserFeedbackState((current) => current.busy ? { busy: false, submittedKind: userFeedbackPendingKindRef.current } : current);
        return;
      }
      const resourceOperationStatus = parseResourceOperationStatus(
        message,
        localizedResourceOperationFallback,
      );
      const resolvedMessage = resolveResourceOperationStatus(message);
      if (
        resolvedMessage.type === "ui/restoreView" &&
        resolvedMessage.payload.focusProviderApiKey
      ) {
        requestProviderApiKeyFocus();
      }
      let hostOperationSurface: OperationMessageSurface | undefined;
      if (message.type === "operation/status") {
        // §三: the training-card controller settles a failed remote-verification
        // request; a failure that belongs to another card aborts the message.
        if (handleRemoteVerificationCommandFailure(message) === "abort") {
          return;
        }
        // §四十四: a store-written banner inherits its host domain. Resource
        // operation results (upload/index/delete/restore acks) render only in
        // Library — the Library view already reports its own mutation status —
        // and plan-state failures (revision conflict, live-plan gate) render
        // only in Learning. Stream-scoped non-errors clear the banner instead
        // of setting one, so they never claim a scope.
        //
        // The scope is derived from the RAW text (sanitization rewrites the
        // markers) and travels into the store write below, atomically with the
        // message — no separate surface state to go stale.
        const hostSurfaceScope = resolveOperationMessageSurface({ message: message.payload.message,
          planStateFailure: Boolean(detectPlanRevisionConflict(message.payload.message) || parseLivePlanTaskGateMarker(message.payload.message)),
          resourceOperation: Boolean(resourceOperationStatus && resourceOperationStatus.kind !== "search"),
        });
        if (!(message.payload.surface === "stream" && message.payload.tone !== "error")) {
          hostOperationSurface = hostSurfaceScope;
        }
      }
      // A library deep link may beat the refreshed snapshot into this webview:
      // ask for a fresh bootstrap, give the resource a bounded moment to
      // arrive, and only then let the landing report it as missing.
      if (resolvedMessage.type === "ui/openResource") {
        const deepLinkResourceId = String(resolvedMessage.resourceId ?? "").trim();
        const alreadySynced = deepLinkResourceId
          ? useWorkbenchState
              .getState()
              .data.resources.some((resource) => resource.id === deepLinkResourceId)
          : false;
        if (deepLinkResourceId && !alreadySynced) {
          postMessage({ type: "request/bootstrap" });
          void waitForResourceInSnapshot(
            deepLinkResourceId,
            OPEN_RESOURCE_SYNC_TIMEOUT_MS,
          ).then(() => {
            applyRawHostMessage(resolvedMessage);
          });
          return;
        }
      }
      if (resourceOperationStatus?.kind !== "search") {
        applyRawHostMessage(
          sanitizeHostFailureMessage(
            resolvedMessage,
            layout.composerLanguage,
            Boolean(isProviderActionOverride || settingsActionState?.targets.includes("provider")),
            resourceOperationStatus?.kind,
          ),
          { operationSurface: hostOperationSurface },
        );
      }
      if (resolvedMessage.type === "ui/coachPrompt" && typeof window !== "undefined") {
        requestCoachComposerFocus();
      }
      // Browser-captured drafts land in the same composer (prefilled, not sent).
      // Focus follows only when the user is not typing somewhere else.
      if (
        resolvedMessage.type === "ui/coachDraftPrefill" &&
        typeof window !== "undefined" &&
        !isEditingAnotherField()
      ) {
        requestCoachComposerFocus();
      }
    },
    [
      applyRawHostMessage,
      handleProviderSpeedTestMessage,
      handleRemoteVerificationCommandFailure,
      handleRemoteVerificationHostMessage,
      layout.composerLanguage,
      localizedResourceOperationFallback,
      requestCoachComposerFocus,
      requestProviderApiKeyFocus,
      resolveLibraryFolderOperation,
      resolveTrainingPersistenceAck,
      resolveResourceOperationStatus,
      settingsActionState,
    ],
  );
  const showComposerShell = docksComposer(activeView);
  const openTrainingCoachBridge = useCallback(
    (bridge: Parameters<typeof composeTrainingCoachBridgeDraft>[0]) => {
      setActiveView("coach");
      setComposerDraft(composeTrainingCoachBridgeDraft(bridge));
      requestCoachComposerFocus();
    },
    [requestCoachComposerFocus, setActiveView, setComposerDraft],
  );
  const {
    onRefreshTask: requestTrainingCardGeneration,
    onRefreshDeck: handleRefreshTrainingDeck,
    onSubmitFlashAnswer: handleSubmitFlashAnswer,
    onSubmitTheoryDrillAnswer: handleSubmitTheoryDrillAnswer,
    onTheoryDrillAction: handleTheoryDrillAction,
    onOpenCoachFromPractice: handleOpenCoachFromPractice,
    onOpenCoachFromFlash: handleOpenCoachFromFlash,
    onOpenCoachBridgeFromFlash: handleOpenCoachBridgeFromFlash,
    onOpenPracticeFromFlash: handleOpenPracticeFromFlash,
    onOpenResources: handleOpenResourcesFromTraining,
    onCreateFlashcard: handleCreateFlashcard,
    onOpenReviewCoach: handleOpenReviewCoach,
    onReviewQueueAction: handleReviewQueueAction,
    onReviewArtifactAction: handleReviewArtifactAction,
    onScenarioLabAction: handleScenarioLabAction,
    onDependencySkillMapAction: handleDependencySkillMapAction,
    onCardStatusTransition: handleTrainingCardStatusTransition,
  } = useTrainingCommands(setActiveView, {
    onOpenCoachWithBridge: openTrainingCoachBridge,
    requestTrainingPersistence,
  });
  const workspaceSettings = data.memory.workspace;
  const trainerWorkspaceAdmission = workspaceSettings?.trainerWorkspace;
  const canCaptureGoalBeforeWorkspaceSetup =
    trainerWorkspaceAdmission?.status === "root-missing";
  const workspaceAuthority = data.memory.sandboxState?.authority;
  const resourceWriteAccess = trainerWorkspaceAdmission
    ? {
        allowed: trainerWorkspaceAdmission.status === "managed",
        reason:
          trainerWorkspaceAdmission.status === "root-missing"
            ? t.workspaceAdmissionRootMissingDetail
            : undefined,
      }
    : workspaceAuthority?.resourceWriteAllowed === true
      ? {
          allowed: workspaceAuthority.authorityScope === "trainer_sandbox" &&
            workspaceAuthority.resourceWriteEvidence?.operation === "write" &&
            workspaceAuthority.resourceWriteEvidence.scope === "trainer_sandbox" &&
            workspaceAuthority.resourceWriteEvidence.allowed === true,
          reason: workspaceAuthority.resourceWriteEvidence?.reason,
        }
      : {
        allowed: false,
        reason:
          appUiCopy(layout.composerLanguage, "资料写入权限还没确认。先在设置里选工作区根目录。"),
      };
  const workspaceSessionBlocked =
    trainerWorkspaceAdmission?.status === "root-missing" ||
    trainerWorkspaceAdmission?.status === "project-found" ||
    trainerWorkspaceAdmission?.status === "browse" ||
    trainerWorkspaceAdmission?.status === "ignored";
  const workspaceSessionBlockTitle =
    trainerWorkspaceAdmission?.status === "root-missing"
      ? t.workspaceAdmissionRootMissing
      : trainerWorkspaceAdmission?.status === "project-found"
        ? t.workspaceAdmissionProjectFound
        : trainerWorkspaceAdmission?.status === "browse"
          ? t.workspaceAdmissionBrowse
        : trainerWorkspaceAdmission?.status === "ignored"
          ? t.workspaceAdmissionIgnored
          : undefined;
  const workspaceSessionBlockMessage =
    trainerWorkspaceAdmission?.status === "root-missing"
      ? t.workspaceAdmissionRootMissingDetail
      : trainerWorkspaceAdmission?.status === "project-found"
        ? t.workspaceAdmissionProjectFoundDetail
        : trainerWorkspaceAdmission?.status === "browse"
          ? t.workspaceAdmissionBrowseDetail
        : trainerWorkspaceAdmission?.status === "ignored"
          ? t.workspaceAdmissionIgnoredDetail
          : undefined;
  const openWorkspaceAdmission = useCallback(() => {
    if (trainerWorkspaceAdmission?.status === "root-missing") {
      useWorkbenchState.getState().requestSettingsCategory("workspace");
      setActiveView("settings");
      return;
    }
    setActiveView("coach");
  }, [setActiveView, trainerWorkspaceAdmission?.status]);
  const defaultCoachDefaults = useMemo(
    () => ({
      memoryScope: "project" as const,
      workingSetMode: "balanced" as const,
      reviewCadence: "steady" as const,
      reviewReminderMode: "due" as const,
      workspaceMemoryToggles: {
        decisions: true,
        patterns: true,
        resources: true,
      },
    }),
    [],
  );
  const draft = layout.composerDraft;
  const composerSessionKey = `${data.memory.workspace?.resourceSandbox?.effectivePath
    ?? data.memory.workspace?.workspaceId ?? data.workspaceName}\u0000${data.sessionLabel}`;
  const surfaceInstanceKey = `${composerSessionKey}\u0000${data.runtimeDataGeneration ?? ""}`;
  const attachmentScope = syncIdentity
    ? JSON.stringify([syncIdentity.generation, syncIdentity.workspaceId, syncIdentity.sessionId])
    : surfaceInstanceKey;
  useEffect(() => {
    if (hasReceivedHostState && data.sessionLabel) {
      useWorkbenchState.getState().selectComposerDraftScope(
        composerDockDraftScope(activeView, composerSessionKey),
      );
    }
  }, [activeView, composerSessionKey, data.sessionLabel, hasReceivedHostState]);
  const normalizedDraft = draft.trim();
  useEffect(() => {
    if (activeView === "plan" && normalizedDraft) {
      return;
    }

    setPendingPlanComposerDraftReplacement(undefined);
  }, [activeView, normalizedDraft]);

  const applyPlanComposerGuidance = (targetTitle: string) => {
    setActiveView("coach");
    setPendingPlanComposerDraftReplacement(undefined);
    setComposerDraft(planText.stageGuidancePrompt(targetTitle));
    requestCoachComposerFocus();
  };
  const requestPlanComposerGuidance = (
    targetTitle: string,
    source: PlanComposerDraftReplacement["source"],
  ) => {
    const normalizedTargetTitle = targetTitle.trim();
    if (!normalizedTargetTitle) {
      return;
    }

    if (normalizedDraft) {
      setPendingPlanComposerDraftReplacement({ source, targetTitle: normalizedTargetTitle });
      return;
    }

    applyPlanComposerGuidance(normalizedTargetTitle);
  };
  const confirmPlanComposerDraftReplacement = () => {
    if (!pendingPlanComposerDraftReplacement) {
      return;
    }

    applyPlanComposerGuidance(pendingPlanComposerDraftReplacement.targetTitle);
  };
  const cancelPlanComposerDraftReplacement = () => {
    setPendingPlanComposerDraftReplacement(undefined);
    window.requestAnimationFrame(() => {
      focusComposerInput();
    });
  };
  // §四十八: sent-message history navigation lives in useComposerHistoryNavigation.
  const { resetComposerHistoryNavigation, navigateComposerHistory } =
    useComposerHistoryNavigation({
      conversation: data.conversation,
      draft,
      setComposerDraft,
    });
  const handleComposerDraftChange = useCallback(
    (nextDraft: string) => {
      resetComposerHistoryNavigation();
      setDismissedComposerDeck(undefined);
      setComposerDraft(nextDraft);
    },
    [resetComposerHistoryNavigation, setComposerDraft],
  );
  const previewDirectionOverride = isBrowserPreview
    ? readBrowserPreviewLocationOverrides().direction
    : undefined;
  const uiDirection = previewDirectionOverride ?? resolveTextDirection(layout.composerLanguage);
  const applyBrowserPreviewLocationOverrides = useCallback(() => {
    if (!isBrowserPreview) {
      return;
    }

    // URL parameters establish the initial preview state only. Do not replay
    // them after an async bootstrap or a user setting change has landed.
    if (browserPreviewLocationOverridesAppliedRef.current) {
      return;
    }
    browserPreviewLocationOverridesAppliedRef.current = true;

    const overrides = readBrowserPreviewLocationOverrides();
    if (overrides.composerLanguage) {
      setComposerLanguage(overrides.composerLanguage);
    }
    if (overrides.activeView) {
      setActiveView(overrides.activeView);
    }
  }, [isBrowserPreview, setActiveView, setComposerLanguage]);
  const applyPreviewHostMessages = useCallback(
    (messages: HostMessage[], isProviderAction = false) => {
      for (const message of messages) {
        applyHostMessage(message, isProviderAction);
        if (
          isProviderAction &&
          message.type === "state/patch" &&
          message.payload &&
          typeof message.payload === "object" &&
          "providerConfig" in message.payload
        ) {
          const providerConfig = message.payload.providerConfig;
          useWorkbenchState.getState().patchData({ providerConfig });
          persistBrowserPreviewProviderConfig(providerConfig);
        }
      }
    },
    [applyHostMessage],
  );
  const providerTestCheckedAt = data.providerConfig.lastTestResult?.checkedAt;
  const [providerTestClock, setProviderTestClock] = useState(() => Date.now());
  useEffect(() => {
    const checkedAtMs = Date.parse(providerTestCheckedAt ?? "");
    if (!Number.isFinite(checkedAtMs)) {
      return;
    }

    const now = Date.now();
    setProviderTestClock(now);
    const expiresAt = checkedAtMs + PROVIDER_TEST_FRESHNESS_WINDOW_MS;
    if (expiresAt <= now) {
      return;
    }

    const timeoutId = window.setTimeout(() => setProviderTestClock(Date.now()), expiresAt - now + 1);
    return () => window.clearTimeout(timeoutId);
  }, [providerTestCheckedAt]);
  const settingsWorkspaceId =
    data.memory.workspace?.workspaceId ??
    data.workspaceTrainingState?.workspaceId ??
    data.providerConfig.lastTestResult?.workspaceId;
  const settingsLastTestScope = {
    workspaceId: settingsWorkspaceId,
    providerProfileId: data.providerConfig.profileId,
  };
  const scopedProviderLastTest = selectScopedSettingsLastTest(
    data.providerConfig.lastTestResult,
    settingsLastTestScope,
  );
  const providerSendState = useMemo(
    () =>
      describeProviderSendState(
        { ...data.providerConfig, lastTestResult: scopedProviderLastTest },
        layout.composerLanguage,
        providerTestClock,
      ),
    [data.providerConfig, scopedProviderLastTest, layout.composerLanguage, providerTestClock],
  );
  const providerImageInputState = useMemo(
    () =>
      describeProviderImageInputState(
        { ...data.providerConfig, lastTestResult: scopedProviderLastTest },
        layout.composerLanguage,
        providerTestClock,
      ),
    [data.providerConfig, scopedProviderLastTest, layout.composerLanguage, providerTestClock],
  );
  // Capability gating keys off provider readiness (configured + API key + a
  // live passing test). Sidecar connection state is informational only — the
  // host lazy-starts the sidecar per request, so an offline indicator must
  // never lock the workbench.
  const capabilityVerdict = useMemo(
    () => deriveTrainerCapabilityVerdict({
      connectionState: data.connection.state,
      providerConfigured: data.providerConfig.configured,
      apiKeyConfigured: data.providerConfig.apiKeyConfigured,
      sendBlocked: providerSendState.blocked,
      lastTestOk: scopedProviderLastTest?.ok === true,
      capabilityTruth: scopedSettingsCapabilityTruth(
        data.providerConfig.lastTestResult,
        {
          workspaceId: settingsWorkspaceId,
          providerProfileId: data.providerConfig.profileId,
        },
      ),
      imageProtocolSupported: providerImageInputState.supported,
      authority: workspaceAuthority,
      workspaceManaged: false,
      workspaceReadOnly: true,
    }),
    [
      data.connection.state,
      data.providerConfig,
      providerSendState.blocked,
      scopedProviderLastTest,
      settingsWorkspaceId,
      trainerWorkspaceAdmission?.status,
      workspaceAuthority,
      providerImageInputState.supported,
    ],
  );
  const providerCanCoachNow = !providerSendState.blocked;
  const providerSupportsFormalPlanTools = providerHasVerifiedToolsProbe({
    lastTestResult: scopedProviderLastTest,
  });
  const providerCanMutateFormalPlan = capabilityVerdict.formalPlan;
  const formalPlanCapabilityMessage = useMemo(() => {
    const messages: Record<ComposerLanguage, string> = {
      "zh-CN": "正式计划需要支持工具调用的模型。请在设置中选择并测试支持 tools 的 Provider。",
      "en-US": "A formal plan needs a provider that supports tool calls. Choose and test a tools-capable provider in Settings.",
      "es-ES": "El plan formal necesita un proveedor con llamadas a herramientas. Elige y prueba uno compatible en Ajustes.",
      "fr-FR": "Le plan formel exige un fournisseur compatible avec les appels d'outils. Choisissez-en un et testez-le dans Réglages.",
      "de-DE": "Ein formeller Plan benötigt einen Provider mit Tool-Aufrufen. Wählen und testen Sie einen passenden Provider in Einstellungen.",
      "ja-JP": "正式な計画にはツール呼び出し対応の Provider が必要です。設定で対応 Provider を選び、テストしてください。",
      "ko-KR": "정식 계획에는 도구 호출을 지원하는 Provider가 필요합니다. 설정에서 지원 Provider를 선택하고 테스트하세요.",
      "pt-BR": "Um plano formal precisa de um provider com chamadas de ferramenta. Escolha e teste um provider compatível em Configurações.",
    };
    return messages[layout.composerLanguage];
  }, [layout.composerLanguage]);
  const agentToolsCapabilityMessage = useMemo(() => {
    const messages: Record<ComposerLanguage, string> = {
      "zh-CN": "当前视图需要已经通过工具调用验证的 Provider。请在设置中选择并测试支持 tools 的连接。",
      "en-US": "This view needs a provider verified for tool calls. Choose and test a tools-capable connection in Settings.",
      "es-ES": "Esta vista necesita un provider verificado para llamadas de herramientas. Elige y prueba una conexión compatible con tools en Ajustes.",
      "fr-FR": "Cette vue nécessite un provider vérifié pour les appels d'outils. Choisissez et testez une connexion compatible dans Réglages.",
      "de-DE": "Diese Ansicht benötigt einen für Tool-Aufrufe verifizierten Provider. Wählen und testen Sie in Einstellungen eine passende Verbindung.",
      "ja-JP": "このビューには、ツール呼び出しを検証済みの Provider が必要です。設定で対応する接続を選び、テストしてください。",
      "ko-KR": "이 보기에는 도구 호출이 검증된 Provider가 필요합니다. 설정에서 tools를 지원하는 연결을 선택하고 테스트하세요.",
      "pt-BR": "Esta visualização precisa de um provider verificado para chamadas de ferramenta. Escolha e teste uma conexão compatível em Configurações.",
    };
    return messages[layout.composerLanguage];
  }, [layout.composerLanguage]);
  const providerBlockReason = useMemo(
    () => providerBlockingReason(data.providerConfig, layout.composerLanguage, data.connection.state),
    [data.connection.state, data.providerConfig, layout.composerLanguage],
  );
  const blockedComposerGuidance = useMemo(
    () =>
      localizeUiViewReferences(
        blockedComposerSetupMessage(
          data.providerConfig,
          layout.composerLanguage,
          activeView,
          data.connection.state,
        ),
        layout.composerLanguage,
      ) ??
      blockedComposerSetupMessage(
        data.providerConfig,
        layout.composerLanguage,
        activeView,
        data.connection.state,
      ),
    [activeView, data.connection.state, data.providerConfig, layout.composerLanguage],
  );
  const blockedCoachGuidance = useMemo(
    () =>
      localizeUiViewReferences(
        blockedComposerSetupMessage(
          data.providerConfig,
          layout.composerLanguage,
          "coach",
          data.connection.state,
        ),
        layout.composerLanguage,
      ) ??
      blockedComposerSetupMessage(
        data.providerConfig,
        layout.composerLanguage,
        "coach",
        data.connection.state,
      ),
    [data.connection.state, data.providerConfig, layout.composerLanguage],
  );
  const providerCoachNotice = useMemo(
    () =>
      (() => {
        const notice = providerCoachBanner(
          data.providerConfig,
          layout.composerLanguage,
          data.connection.state,
          blockedCoachGuidance,
        );
        return notice
          ? {
              ...notice,
              message: localizeUiViewReferences(notice.message, layout.composerLanguage) ?? notice.message,
            }
          : undefined;
      })(),
    [blockedCoachGuidance, data.connection.state, data.providerConfig, layout.composerLanguage],
  );
  const providerSetupState = useMemo(
    () => {
      const summary = providerSetupSummary(data.providerConfig, layout.composerLanguage, data.connection.state);
      return {
        title: localizeUiViewReferences(summary.title, layout.composerLanguage) ?? summary.title,
        detail: localizeUiViewReferences(summary.detail, layout.composerLanguage) ?? summary.detail,
        actionLabel:
          localizeUiViewReferences(summary.actionLabel, layout.composerLanguage) ?? summary.actionLabel,
      };
    },
    [data.connection.state, data.providerConfig, layout.composerLanguage],
  );
  const displayConnectionState = effectiveConnectionState(data.connection.state);
  // The neutral takeover is reserved for a provider that genuinely cannot run
  // (not configured / blocked) — never for a connecting or offline sidecar.
  const shouldShowNeutralEmptyState =
    data.conversation.length === 0 && (!providerCanCoachNow || Boolean(providerBlockReason));
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
  const baselineConnectedMessage = useMemo(
    () =>
      appUiCopy(layout.composerLanguage, "已连接到扩展宿主。"),
    [layout.composerLanguage],
  );
  const composerHasSavedProfiles = useMemo(
    () => hasSavedProviderProfiles(data.providerConfig),
    [data.providerConfig.profileCount, data.providerConfig.providerProfiles],
  );
  const composerProviderProfileLabel = useMemo(
    () =>
      data.providerConfig.configured ? data.providerConfig.profileLabel?.trim() || undefined : undefined,
    [data.providerConfig.configured, data.providerConfig.profileLabel],
  );

  const composerProviderCopy = providerSettingsLocale(layout.composerLanguage);
  const composerModelButtonLabel = useMemo(() => {
    if (!data.providerConfig.configured) {
      return composerHasSavedProfiles
        ? composerProviderCopy.menu.chooseModel
        : composerProviderCopy.menu.model;
    }

    const resolvedModel = data.providerConfig.resolvedModel?.trim();
    if (resolvedModel) {
      return resolvedModel;
    }

    const configuredModel = data.providerConfig.model.trim();
    if (configuredModel) {
      return configuredModel;
    }

    if (composerProviderProfileLabel) {
      return composerProviderProfileLabel;
    }

    return composerProviderCopy.menu.model;
  }, [
    composerHasSavedProfiles,
    composerProviderCopy,
    composerProviderProfileLabel,
    data.providerConfig.configured,
    data.providerConfig.model,
    data.providerConfig.resolvedModel,
  ]);
  const composerModelButtonDisplayLabel =
    composerModelActionDensity === "compact"
      ? compactComposerModelLabel(
          composerModelButtonLabel,
          composerProviderProfileLabel ?? data.providerConfig.name,
          layout.composerLanguage,
        )
      : composerModelButtonLabel;
  const composerActiveModelPolicy = useMemo(() => {
    const resolvedModel = data.providerConfig.resolvedModel?.trim() ?? "";
    const configuredModel = data.providerConfig.model.trim();
    return evaluateProviderModelPolicy(
      data.providerConfig.configured ? resolvedModel || configuredModel : "",
      {
        allowedModels: data.providerConfig.allowedModels,
        deniedModels: data.providerConfig.deniedModels,
      },
    );
  }, [
    data.providerConfig.allowedModels,
    data.providerConfig.configured,
    data.providerConfig.deniedModels,
    data.providerConfig.model,
    data.providerConfig.resolvedModel,
  ]);
  const composerActiveModelPolicyHint = composerModelPolicyHint(
    layout.composerLanguage,
    composerActiveModelPolicy.reason,
  );
  const composerModelButtonTitle = !data.providerConfig.configured
    ? composerProviderCopy.menu.manageModels
    : composerActiveModelPolicyHint ??
      (composerProviderProfileLabel && composerProviderProfileLabel !== composerModelButtonLabel
        ? composerProviderCopy.menu.switchModelWithConnection
            .replace("{model}", composerModelButtonLabel)
            .replace("{connection}", composerProviderProfileLabel)
        : composerProviderCopy.menu.switchModel.replace("{model}", composerModelButtonLabel));
  const composerPresenceProviderCaption = useMemo(() => {
    if (data.providerConfig.configured) {
      return (
        composerProviderProfileLabel ??
        data.providerConfig.name?.trim() ??
        composerProviderCopy.menu.currentConnection
      );
    }

    if (composerHasSavedProfiles) {
      return composerProviderCopy.menu.savedConnections;
    }

    return composerProviderCopy.menu.modelEntry;
  }, [
    composerHasSavedProfiles,
    composerProviderCopy,
    composerProviderProfileLabel,
    data.providerConfig.configured,
    data.providerConfig.name,
  ]);
  const composerPresenceProviderDetail = useMemo(() => {
    if (data.providerConfig.configured || composerHasSavedProfiles) {
      return providerModelMenuNote(data.providerConfig, layout.composerLanguage);
    }

    return composerProviderCopy.menu.saveConnectionFirst;
  }, [
    composerHasSavedProfiles,
    composerProviderCopy,
    data.providerConfig,
    layout.composerLanguage,
  ]);

  // §四十八: menu item construction lives in lib/composerModelHelpers.
  const composerProviderMenuItems = useMemo(
    () => buildComposerProviderMenuItems(data.providerConfig, layout.composerLanguage),
    [data.providerConfig, layout.composerLanguage],
  );

  // §四十八: model search state + filtering live in useComposerModelQuery.
  const {
    query: composerModelQuery,
    setQuery: setComposerModelQuery,
    filtered: filteredComposerProviderMenuItems,
  } = useComposerModelQuery(composerProviderMenuItems);

  const composerThinkingDescriptor = useMemo<ProviderThinkingDescriptor | undefined>(() => {
    const provider = data.providerConfig;
    if (!provider.configured) {
      return undefined;
    }
    const lastTest = provider.lastTestResult as
      | {
          capabilityEvidence?: Array<{
            name?: unknown;
            state?: unknown;
            observed?: unknown;
          }>;
        }
      | undefined;
    const model = provider.resolvedModel ?? provider.model;
    const context = {
      protocol: provider.protocol,
      model,
      providerName: provider.name,
      baseUrl: provider.baseUrl,
      capabilityEvidence: lastTest?.capabilityEvidence,
      modelCapabilities: model ? provider.modelCapabilities?.[model] : undefined,
      profileCapabilities: provider.capabilities,
    };
    if (!thinkingProtocolSupportsWire(provider.protocol)) {
      return undefined;
    }
    // Smart adaptation (P0 model experience): the protocol defaults mark
    // `thinking:false` for every model (providerProtocols.ts:254) — that is
    // absence of evidence, not a verdict. The control therefore renders
    // whenever the protocol can carry a thinking field: "自动" emits nothing
    // until the learner picks a mode, and a gateway that dislikes the choice
    // is absorbed by the sidecar's negotiated replay (provider/thinking.py).
    // Only an explicit probe verdict of "unsupported" hides it — a declared
    // or verified model always shows it and restores the last choice. The
    // control never gates sending.
    const support = classifyProviderThinkingSupport(context);
    if (support === "unsupported") {
      return undefined;
    }
    const storedThinking = normalizeProviderThinkingConfig(
      provider.thinkingConfig,
      provider.protocol,
    );
    const descriptor =
      describeProviderThinking(context, provider.requestDefaults) ??
      synthesizeProviderThinkingDescriptor(context, storedThinking ?? { mode: "auto" });
    if (!descriptor) {
      return undefined;
    }
    return storedThinking ? { ...descriptor, config: storedThinking } : descriptor;
  }, [
    data.providerConfig.baseUrl,
    data.providerConfig.capabilities,
    data.providerConfig.configured,
    data.providerConfig.lastTestResult,
    data.providerConfig.model,
    data.providerConfig.modelCapabilities,
    data.providerConfig.name,
    data.providerConfig.protocol,
    data.providerConfig.requestDefaults,
    data.providerConfig.resolvedModel,
    data.providerConfig.thinkingConfig,
  ]);

  // R3②: context usage used to re-tally the entire conversation plus the
  // full streamed content character-by-character on every stream chunk
  // (O(conversation + stream) per chunk, O(n²) per turn). Both tallies are
  // now cached: the conversation part recomputes only when the conversation
  // array identity changes (per turn, not per chunk), and the stream part
  // only tallies the newly appended slice (streamedContent grows
  // monotonically per streamMessageId; any shrink or id change resets it).
  // StrictMode double-invocation is safe: both caches are keyed by identity
  // and re-run with the same inputs returns the cached values untouched.
  const composerContextTallyRef = useRef<{
    conversation: typeof data.conversation | undefined;
    conversationCjk: number;
    conversationOther: number;
    streamMessageId: string | undefined;
    streamConsumedChars: number;
    streamCjk: number;
    streamOther: number;
  }>({
    conversation: undefined,
    conversationCjk: 0,
    conversationOther: 0,
    streamMessageId: undefined,
    streamConsumedChars: 0,
    streamCjk: 0,
    streamOther: 0,
  });

  const composerContextUsage = useMemo(() => {
    const provider = data.providerConfig;
    const model = provider.resolvedModel ?? provider.model;
    const limit =
      (model ? provider.modelTokenLimits?.[model]?.contextWindowTokens : undefined) ??
      provider.contextWindowTokens;
    const cjkPattern = /[\u1100-\u11ff\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]/;
    const tally = (text: string): { cjk: number; other: number } => {
      let cjk = 0;
      let other = 0;
      for (const ch of text) {
        if (cjkPattern.test(ch)) {
          cjk += 1;
        } else {
          other += 1;
        }
      }
      return { cjk, other };
    };
    const cache = composerContextTallyRef.current;
    if (cache.conversation !== data.conversation) {
      let cjk = 0;
      let other = 0;
      for (const message of data.conversation) {
        const bodyTally = tally(message.body ?? "");
        cjk += bodyTally.cjk;
        other += bodyTally.other;
        for (const attachment of message.attachments ?? []) {
          const attachmentTally = tally(attachment.value ?? "");
          cjk += attachmentTally.cjk;
          other += attachmentTally.other;
        }
        // Per-message framing overhead (role tags, separators).
        other += 16;
      }
      cache.conversation = data.conversation;
      cache.conversationCjk = cjk;
      cache.conversationOther = other;
    }
    let cjk = cache.conversationCjk;
    let other = cache.conversationOther;
    // The streaming text is read from the store when this memo re-runs (the
    // coarse bucket below schedules that; the final value lands on the
    // stream-end flip), so App itself never subscribes per chunk.
    const streamed = useWorkbenchState.getState().streaming.streamedContent ?? "";
    const streamReset =
      streaming.streamMessageId !== cache.streamMessageId ||
      streamed.length < cache.streamConsumedChars;
    if (streamReset) {
      const full = tally(streamed);
      cache.streamMessageId = streaming.streamMessageId;
      cache.streamConsumedChars = streamed.length;
      cache.streamCjk = full.cjk;
      cache.streamOther = full.other;
    } else if (streamed.length > cache.streamConsumedChars) {
      const delta = tally(streamed.slice(cache.streamConsumedChars));
      cache.streamConsumedChars = streamed.length;
      cache.streamCjk += delta.cjk;
      cache.streamOther += delta.other;
    }
    cjk += cache.streamCjk;
    other += cache.streamOther;
    // A system/pedagogy prompt is always prepended server-side.
    const systemOverhead = 1200;
    const used = Math.ceil(cjk + other / 4) + systemOverhead;
    const ratio = limit && limit > 0 ? Math.min(1, used / limit) : undefined;
    return { used, limit, ratio };
  }, [
    data.conversation,
    data.providerConfig,
    streaming.streamMessageId,
    streamingContentBucket,
    streaming.isStreaming,
  ]);

  const composerContextUsageTone = composerContextUsage.ratio === undefined
    ? "unknown"
    : composerContextUsage.ratio >= 0.85
      ? "critical"
      : composerContextUsage.ratio >= 0.6
        ? "warn"
        : "ok";

  const composerContextUsageLabel = composerContextUsage.limit
    ? appUiCopy(layout.composerLanguage, "上下文用量约 {u} / {l}")
        .replace("{u}", formatTokenCount(composerContextUsage.used))
        .replace("{l}", formatTokenCount(composerContextUsage.limit))
    : appUiCopy(layout.composerLanguage, "上下文用量约 {u}（未知上限）").replace(
        "{u}",
        formatTokenCount(composerContextUsage.used),
      );

  const composerContextUsageDetail = composerContextUsage.limit
    ? appUiCopy(
        layout.composerLanguage,
        "本会话已用约 {u} 个上下文，上限约 {l}（约 {p}%）。这是按消息长度估算的近似值。",
      )
        .replace("{u}", formatTokenCount(composerContextUsage.used))
        .replace("{l}", formatTokenCount(composerContextUsage.limit))
        .replace("{p}", String(Math.round((composerContextUsage.ratio ?? 0) * 100)))
    : appUiCopy(
        layout.composerLanguage,
        "本会话已用约 {u} 个上下文（按消息长度估算）。该连接没有可靠的上下文上限，所以只显示估算值。",
      ).replace("{u}", formatTokenCount(composerContextUsage.used));

  const composerContextRingNode = (
    <svg
      viewBox="0 0 18 18"
      width="18"
      height="18"
      aria-hidden="true"
      className={`composer-context-ring composer-context-ring--${composerContextUsageTone}`}
    >
      {/* r1-g0-3: the idle ring reads as "◎" only when the track is visible —
          the old 0.18-opacity track all but vanished at 18px. */}
      <circle
        cx="9"
        cy="9"
        r="7"
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.32"
        strokeWidth="2.2"
      />
      {composerContextUsage.ratio !== undefined ? (
        <circle
          cx="9"
          cy="9"
          r="7"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeDasharray={`${(composerContextUsage.ratio * 43.98).toFixed(2)} 43.98`}
          transform="rotate(-90 9 9)"
        />
      ) : (
        <circle cx="9" cy="9" r="1.9" fill="currentColor" />
      )}
    </svg>
  );

  // History has a single header entry point (trainer-history-toggle); the
  // composer secondary row stays minimal (context usage + model switch).

  useEffect(() => {
    const pending = pendingLivePlanTaskMintRef.current;
    if (!pending || !operationMessage) {
      return;
    }
    if (operationMessage.tone === "info") {
      return;
    }
    pendingLivePlanTaskMintRef.current = undefined;
    if (operationMessage.tone === "success") {
      setComposerDraft("");
      setComposerAttachments([]);
      setDismissedComposerDeck(undefined);
    }
  }, [operationMessage, setComposerDraft]);

  useEffect(() => {
    if (!settingsActionState) {
      return;
    }

    // Backend readiness/progress can arrive while a connection test is active.
    // Only its final success/error should settle the settings operation.
    if (!operationMessage || operationMessage.tone === "info") {
      return;
    }

    const normalized = operationMessage.message.trim().toLowerCase();
    if (settingsActionState.baselineMessageKey && normalized === settingsActionState.baselineMessageKey) {
      return;
    }

    setSettingsFeedbackState((current) => {
      const next: SettingsFeedbackState = { ...current };
      for (const slot of settingsActionState.targets) {
        const feedback = buildSettingsFeedback(
          settingsActionState,
          operationMessage,
          layout.composerLanguage,
          slot,
        );
        if (feedback) {
          next[slot] = feedback;
        }
      }
      return next;
    });
    if (
      settingsActionState.kind === "save-provider" &&
      settingsActionState.targets.includes("provider") &&
      operationMessage.tone === "success"
    ) {
      markProviderDraftSaved();
    }
    setSettingsActionState(undefined);
  }, [layout.composerLanguage, markProviderDraftSaved, operationMessage, settingsActionState]);

  useEffect(() => {
    applyWorkbenchTheme(resolvedTheme, layout.themePreference === "system");
  }, [resolvedTheme, layout.themePreference]);

  // The host-message dispatch changes identity whenever layout values or
  // settings action state change. Keep the subscription and the one-shot
  // bootstrap request out of that churn: re-running this effect used to call
  // `requestBootstrapOnce` again after the bootstrap guard re-armed, which
  // re-posted `request/bootstrap` and produced a continuous
  // POST /memory/settings + GET /memory/summary loop against the sidecar.
  const applyHostMessageRef = useRef(applyHostMessage);
  useEffect(() => {
    applyHostMessageRef.current = applyHostMessage;
  }, [applyHostMessage]);

  useEffect(() => {
    const unsubscribe = subscribeToHostMessages((message) => {
      applyHostMessageRef.current(message);
    });
    requestBootstrapOnce();
    return unsubscribe;
  }, []);

  useEffect(() => {
    if (isBrowserPreview || hasReceivedHostState) {
      return;
    }

    const timer = window.setTimeout(() => {
      requestBootstrapOnce(true);
    }, 1800);

    return () => {
      window.clearTimeout(timer);
    };
  }, [hasReceivedHostState, isBrowserPreview]);

  useEffect(() => {
    if (isBrowserPreview) {
      return;
    }

    const handleVisibility = () => {
      if (document.visibilityState !== "visible") {
        return;
      }
      // With host state already in the store, refocusing is free: the host
      // pushes incremental patches and the runtime is never re-initialized.
      if (!hasReceivedHostState) {
        syncBootstrapLifecycleOnVisible(hasReceivedHostState);
      }
    };

    window.addEventListener("focus", handleVisibility);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.removeEventListener("focus", handleVisibility);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [hasReceivedHostState, isBrowserPreview]);

  useEffect(() => {
    if (!isBrowserPreview) {
      return;
    }
    applyBrowserPreviewLocationOverrides();
  }, [applyBrowserPreviewLocationOverrides, isBrowserPreview]);

  // Bootstrap the live browser preview at most once per mount. The callbacks
  // below change identity on every layout/settings state change, so they are
  // read through a ref: keying this effect on them refetched the full
  // POST /memory/settings + GET /memory/summary bootstrap on every churn, and
  // `previewSessionId` resolving from undefined to a session id doubled it.
  const browserPreviewBootstrapDepsRef = useRef({
    applyHostMessage,
    applyBrowserPreviewLocationOverrides,
    setOperationMessage,
    composerLanguage: layout.composerLanguage,
    previewSessionId,
  });
  useEffect(() => {
    browserPreviewBootstrapDepsRef.current = {
      applyHostMessage,
      applyBrowserPreviewLocationOverrides,
      setOperationMessage,
      composerLanguage: layout.composerLanguage,
      previewSessionId,
    };
  });
  useEffect(() => {
    if (!isBrowserPreview) {
      return;
    }

    const {
      applyHostMessage: dispatchHostMessage,
      applyBrowserPreviewLocationOverrides: applyLocationOverrides,
      setOperationMessage: reportOperationMessage,
      composerLanguage,
      previewSessionId: bootstrapSessionId,
    } = browserPreviewBootstrapDepsRef.current;

    const injectedPreviewBootstrap = getInjectedBootstrapState<BootstrapData>();
    if (injectedPreviewBootstrap && typeof injectedPreviewBootstrap === "object") {
      if (injectedPreviewBootstrapHydratedRef.current) {
        return;
      }
      injectedPreviewBootstrapHydratedRef.current = true;
      dispatchHostMessage({
        type: "bootstrap",
        payload: structuredClone(injectedPreviewBootstrap),
      });
      applyLocationOverrides();
      return;
    }

    let cancelled = false;
    const requestSequence = hostMessageSequenceRef.current;
    void loadBrowserPreviewModule()
      .then((browserPreview) => browserPreview.fetchBrowserPreviewBootstrap(bootstrapSessionId))
      .then(({ sessionId, message }) => {
        if (cancelled) {
          return;
        }
        if (hostMessageSequenceRef.current !== requestSequence) {
          return;
        }
        setPreviewSessionId(sessionId);
        dispatchHostMessage(message);
        applyLocationOverrides();
      })
      .catch(() => {
        if (cancelled) {
          return;
        }
        reportOperationMessage({
          tone: "error",
          message: recoverableFailureMessage("bootstrap", composerLanguage),
        });
      });

    return () => {
      cancelled = true;
    };
  }, [isBrowserPreview]);

  useEffect(() => {
    if (isBrowserPreview) {
      return;
    }

    postMessage({
      type: "ui/liveFollow",
      payload: { enabled: layout.followCurrentFile },
    });
  }, [isBrowserPreview, layout.followCurrentFile]);

  useEffect(() => {
    setOpenMenu(undefined);
  }, [layout.activeView]);

  // Restart the view entrance animation on every view change without
  // remounting the container (remounting would drop child state).
  useEffect(() => {
    const node = viewContentRef.current;
    if (!node) {
      return;
    }
    node.classList.remove("view-content--enter");
    void node.offsetWidth;
    node.classList.add("view-content--enter");
  }, [activeView]);

  useEffect(() => {
    if (openMenu !== "model") {
      setComposerModelQuery("");
      return;
    }

    window.requestAnimationFrame(() => {
      composerModelSearchRef.current?.focus();
    });
  }, [openMenu]);

  useEffect(() => {
    if (activeView === "settings") {
      return;
    }

    const shell = composerShellRef.current;
    if (!shell) {
      return;
    }

    const updateDensity = () => {
      const width = shell.getBoundingClientRect().width;
      setComposerModelActionDensity(width < 430 ? "compact" : "default");
    };

    updateDensity();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateDensity);
      return () => {
        window.removeEventListener("resize", updateDensity);
      };
    }

    const observer = new ResizeObserver(() => {
      updateDensity();
    });
    observer.observe(shell);
    return () => observer.disconnect();
  }, [activeView]);

  useEffect(() => {
    setSelectedCommandIndex(0);
  }, [normalizedDraft]);

  useSurfaceScroll(viewContentRef, activeView, composerSessionKey);

  // The imperative streaming subscription below reads the active view without
  // re-subscribing; keep the latest value in a ref.
  const activeViewRef = useRef(activeView);
  activeViewRef.current = activeView;

  useEffect(() => {
    if (activeView !== "coach") {
      return;
    }

    const container = viewContentRef.current && getSurfaceScrollElement(viewContentRef.current, "coach");
    if (!container) {
      return;
    }

    // Stick-to-bottom only while the reader is already at (or near) the
    // bottom; scrolling up during a stream must stay respected.
    const isPinnedToBottom = () =>
      container.scrollHeight - container.scrollTop - container.clientHeight < 120;

    const handleScroll = () => {
      coachAutoScrollPinnedRef.current = isPinnedToBottom();
    };
    container.addEventListener("scroll", handleScroll, { passive: true });

    coachAutoScrollPinnedRef.current = isPinnedToBottom();
    const handle = window.requestAnimationFrame(() => {
      if (coachAutoScrollPinnedRef.current) {
        container.scrollTop = container.scrollHeight;
      }
    });

    return () => {
      window.cancelAnimationFrame(handle);
      container.removeEventListener("scroll", handleScroll);
    };
  }, [activeView, data.conversation.length, streaming.isStreaming]);

  // Per-chunk content is not part of App's subscription; the stick-to-bottom
  // pin follows the store directly so every chunk re-sticks without a render.
  useEffect(() => {
    return useWorkbenchState.subscribe((state, previous) => {
      if (state.streaming.streamedContent === previous.streaming.streamedContent) {
        return;
      }
      if (activeViewRef.current !== "coach" || !coachAutoScrollPinnedRef.current) {
        return;
      }
      const container =
        viewContentRef.current && getSurfaceScrollElement(viewContentRef.current, "coach");
      if (!container) {
        return;
      }
      container.scrollTop = container.scrollHeight;
    });
  }, []);

  const streamingPlaceholderBody = useMemo(() => {
    if (streamingHasAgentActivity) {
      return appUiCopy(layout.composerLanguage, "正在整理当前步骤，然后给出第一段可见回复。");
    }
    return appUiCopy(layout.composerLanguage, "正在梳理你的问题，然后给出第一段可见回复。");
  }, [layout.composerLanguage, streamingHasAgentActivity]);
  const hasFormalPlan = data.hasFormalPlan;
  const activePlanStage = hasFormalPlan
    ? (data.plan.currentStageId
        ? data.plan.stages.find((stage) => stage.id === data.plan.currentStageId)
        : undefined) ??
      data.plan.stages.find((stage) => stage.status === "active") ??
      data.plan.stages[0]
    : undefined;
  const planRuntimeStatus = data.planRuntimeStatus;
  const recoveredRuntime =
    planRuntimeStatus?.recovered === true ||
    Boolean(
      planRuntimeStatusFromRecovery(
        data.memory.workspace?.latestPlanRuntime,
        data.memory.workspace?.workspaceId ?? data.workspaceTrainingState?.workspaceId ?? "",
      ),
    );
  const runtimeCurrentStage = planRuntimeStatus?.currentStage;
  const runtimeCurrentThread = planRuntimeStatus?.currentMainThread;
  const leftoverChromeIdentity = {
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
    runtimePlanId: data.memory.workspace?.latestPlanRuntime?.planId,
    planId: data.plan.id,
    planCurrentStep: data.plan.currentStep,
  };
  const leftoverTaskChromeNotLive = leftoverTaskGuideFocusIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: leftoverChromeIdentity.runtimeCurrentStep,
  });
  const independentTrainingSelectionLive = independentTrainingSelectionIsLive({
    workspaceId: data.memory.workspace?.workspaceId,
    selectedCardId: data.workspaceTrainingState?.selectedCardId,
    selection: data.memory.workspace?.liveTrainingSelection,
  });
  const leftoverTrainingHandoffChromeNotLive = leftoverTrainingHandoffChromeIsNotLive(
    leftoverChromeIdentity,
  ) && !independentTrainingSelectionLive;
  const leftoverSandboxPreviewNotLive = leftoverResourceSandboxPreviewIsNotLive(
    leftoverChromeIdentity,
  );
  const leftoverResourceSelectedDetailNotLive = leftoverResourceSelectedDetailIsNotLive(
    leftoverChromeIdentity,
  );
  const leftoverResourceSandboxStateNotLive = leftoverResourceSandboxStateIsNotLive(
    leftoverChromeIdentity,
  );
  const leftoverResourceLibraryListNotLive =
    leftoverResourceLibraryListIsNotLive({
      recovered: recoveredRuntime,
      runtimeCurrentStep: leftoverChromeIdentity.runtimeCurrentStep,
    }) || leftoverTrainingHandoffChromeNotLive;
  const leftoverSettingsProfileRhythmNotLive = !data.sessionHistoryRestored && leftoverSettingsProfileRhythmIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverSettingsLearnerProjectOnboardingNotLive = !data.sessionHistoryRestored && leftoverSettingsLearnerProjectOnboardingIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverCoachConversationNotLive = !data.sessionHistoryRestored && leftoverCoachConversationIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverSuggestedActionsNotLive = leftoverSuggestedActionsIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverFirstLookHeadlineNotLive = leftoverFirstLookHeadlineIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverEvaluationHeadlineNotLive = leftoverEvaluationHeadlineIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverStreamingCheckpointNotLive = leftoverStreamingCheckpointIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverTransferSkillNotLive = leftoverTransferSkillIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const liveTransferState = preferRecoveredTransferSkill({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
    transfer:
      normalizeTransferSkillStateRecord(data.workspaceTrainingState?.latestTransferState) ??
      normalizeTransferSkillStateRecord(data.memory.workspace?.latestTransferState),
  });
  const liveConversation = leftoverCoachConversationNotLive ? [] : data.conversation;
  const liveFirstLookSummary = leftoverFirstLookHeadlineNotLive
    ? undefined
    : data.memory.workspaceUnderstanding?.firstLookSummary;
  const firstLookSummary = liveFirstLookSummary;
  const liveEvaluationHeadline = leftoverEvaluationHeadlineNotLive
    ? undefined
    : data.evaluation.headline;
  const liveLatestStreamingCheckpoint = leftoverStreamingCheckpointNotLive
    ? undefined
    : data.memory.workspace?.latestStreamingCheckpoint;
  const localizedConversation = useMemo(
    () => liveConversation.map((message) => localizeConversationMessage(message, t, layout.composerLanguage)),
    [layout.composerLanguage, liveConversation, t],
  );
  // Conversation length when the current stream started. The completion patch
  // merges the finished turn into the conversation while the streaming UI is
  // still up; entries past this base are represented by the optimistic echo
  // and the live streaming slot so nothing remounts at completion.
  const streamBaseLengthRef = useRef<number | null>(null);
  if (streaming.isStreaming) {
    if (streamBaseLengthRef.current === null) {
      streamBaseLengthRef.current = data.conversation.length;
    }
  } else {
    streamBaseLengthRef.current = null;
  }
  const coachRenderConversation = useMemo(() => {
    let list = localizedConversation;
    if (
      streaming.isStreaming &&
      streamBaseLengthRef.current !== null &&
      list.length > streamBaseLengthRef.current
    ) {
      list = list.slice(0, streamBaseLengthRef.current);
    }
    const now = Date.now();
    const pendingTurns = optimisticTurns.filter((entry) => now - entry.createdAt <= 120_000);
    const pendingMessages = pendingTurns
      .filter((entry) => {
        // Confirm against the raw server conversation; the localized list may
        // rewrite bodies but never reorders or drops entries.
        if (entry.baseLength >= liveConversation.length) {
          return true;
        }
        return !liveConversation
          .slice(entry.baseLength)
          .some((item) => item.role === "user" && item.body.trim() === entry.body.trim());
      })
      .map((entry) => ({
        id: entry.id,
        role: "user" as const,
        author: t.you,
        body: entry.body,
        timestamp: "",
      }));
    return pendingMessages.length > 0 ? [...list, ...pendingMessages] : list;
  }, [liveConversation, localizedConversation, optimisticTurns, streaming.isStreaming, t]);
  const liveCoachTaskChrome = preferRecoveredCoachTaskChrome({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
    taskTitle: data.task.title,
    ideaSummary: data.implementationGuide?.ideaSummary,
    scopeBoundary: data.implementationGuide?.scopeBoundary,
    guideCurrentStep: data.implementationGuide?.currentStep,
    teachingGoal: data.implementationGuide?.teachingGoal,
    successSignal: data.implementationGuide?.successSignal,
    fallbackStep: data.implementationGuide?.fallbackStep,
    currentFocus: data.coachFocus?.currentFocus,
    activeTask: data.coachFocus?.activeTask,
    nextStep: data.coachFocus?.nextStep,
    activeStage: data.coachFocus?.activeStage,
  });
  const leftoverCoachTurnChromeNotLive = leftoverCoachTurnChromeIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const latestCoachArtifact = useMemo(() => {
    const preferredArtifactKinds = new Set([
      "idea_implementation",
      "project_adaptation",
      "project_idea",
      "principle",
      "plan_update",
      "next_step",
      "review",
    ]);

    for (let index = data.conversation.length - 1; index >= 0; index -= 1) {
      const message = data.conversation[index];
      if (message.role !== "assistant" || !message.artifacts?.length) {
        continue;
      }

      const preferredArtifact = message.artifacts.find((artifact) =>
        preferredArtifactKinds.has(artifact.kind),
      );
      if (preferredArtifact) {
        return preferredArtifact;
      }

      return message.artifacts[0];
    }

    return undefined;
  }, [data.conversation]);
  // Grounding downgrade (DESIGN.md §2.5): union of the webview-visible
  // carriers for the latest turn — host-mapped coach turn / next-step hint and
  // the streaming terminal frame. Message-level artifact metadata is read by
  // the bubble itself.
  const coachTurnNextStepRequiresConfirmation = resolveTurnNextStepRequiresConfirmation({
    coachTurnRequiresConfirmation: data.coachTurn?.requiresConfirmation,
    nextStepHintRequiresConfirmation: data.nextStepHint?.requiresConfirmation,
    streamingCompletionRequiresConfirmation: streaming.completionNextStepRequiresConfirmation,
  });
  const liveCoachTurnChrome = preferRecoveredCoachTurnChrome({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
    coachTurnNextStep: data.coachTurn?.nextStep,
    coachTurnSummary: data.coachTurn?.summary,
    coachTurnTeachingGoal: data.coachTurn?.teachingGoal,
    coachTurnEncouragement: data.coachTurn?.encouragement,
    coachTurnActiveStage: data.coachTurn?.activeStage,
    coachingStateNextStep: data.coachingState?.nextStep,
    coachingStateSummary: data.coachingState?.summary,
    coachingStateTeachingGoal: data.coachingState?.teachingGoal,
    coachingStateEncouragement: data.coachingState?.encouragement,
    evaluationNextStep: data.evaluation.nextStep,
    nextStepHintTitle: data.nextStepHint?.title,
    nextStepHintSummary: data.nextStepHint?.summary,
    resumeThread: data.coachTurn?.resumeThread ?? data.coachingState?.resumeThread,
    supportStrategy: data.coachTurn?.supportStrategy ?? data.coachingState?.supportStrategy,
    reviewQueueSummary:
      data.coachTurn?.reviewQueueSummary ??
      data.reviewQueueSummary ??
      planRuntimeStatus?.reviewQueueSummary,
    artifactTeaser: latestCoachArtifact?.teaser,
    artifactRationale: latestCoachArtifact?.rationale,
    continuitySummary: data.coachFocus?.continuitySummary,
    coachJudgmentSummary: planRuntimeStatus?.coachJudgment?.summary,
    coachJudgmentTeachingGoal: planRuntimeStatus?.coachJudgment?.teachingGoal,
  });
  const formattedNextReviewDue = useMemo(
    () => formatReviewDueLabel(data.nextReviewDue, layout.composerLanguage),
    [data.nextReviewDue, layout.composerLanguage],
  );
  const resolvedCoachScenario = data.coachTurn?.scenario ?? data.coachingState?.scenario;
  const activeThreadFocus = data.memory.activeThread?.focusArea;
  const activeThreadSummary = data.memory.activeThread?.summary;
  const activeThreadNextStep = data.memory.activeThread?.nextStep;
  const memoryEvidence = (data as WorkbenchDataSnapshot).memory.memoryEvidence.slice(0, 2);
  const resolvedCoachSummary =
    liveCoachTurnChrome.coachJudgmentSummary ??
    liveCoachTurnChrome.coachTurnSummary ??
    (leftoverCoachTurnChromeNotLive ? undefined : activeThreadSummary) ??
    liveCoachTurnChrome.coachingStateSummary ??
    liveCoachTaskChrome.currentFocus;
  const resolvedCoachNextStep =
    planRuntimeStatus?.nextTrainingAction ??
    runtimeCurrentThread?.nextStep ??
    liveCoachTurnChrome.coachTurnNextStep ??
    (leftoverCoachTurnChromeNotLive ? undefined : activeThreadNextStep) ??
    liveCoachTurnChrome.coachingStateNextStep ??
    liveCoachTaskChrome.nextStep ??
    (leftoverTaskChromeNotLive ? undefined : data.task.nextActionLabel);
  const resolvedCoachEncouragement =
    liveCoachTurnChrome.coachTurnEncouragement ??
    liveCoachTurnChrome.coachingStateEncouragement ??
    (leftoverTaskChromeNotLive ? undefined : data.task.description);
  const resolvedCoachReview = leftoverCoachTurnChromeNotLive
    ? undefined
    : liveCoachTurnChrome.reviewQueueSummary ??
      data.coachFocus?.reviewRhythm ??
      data.memory.reviewRhythm;
  const resolvedCoachSignal = data.coachTurn?.learnerSignal ?? data.coachingState?.learnerSignal;
  const resolvedCoachFocus =
    runtimeCurrentThread?.focusArea ??
    (leftoverTaskChromeNotLive ? undefined : activeThreadFocus) ??
    liveCoachTaskChrome.currentFocus ??
    liveCoachTaskChrome.activeTask ??
    (leftoverTaskChromeNotLive ? undefined : data.memory.currentFocus);
  const resolvedCoachStage =
    runtimeCurrentStage?.title ??
    liveCoachTaskChrome.activeStage ??
    liveCoachTurnChrome.coachTurnActiveStage;
  const latestArtifactTeaser = liveCoachTurnChrome.artifactTeaser;
  const runtimeCurrentStepRaw = planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep;
  const runtimeWhyNowRaw = planRuntimeStatus?.whyNow ?? runtimeCurrentThread?.whyNow;
  const runtimeCurrentStep = isLanguageAlignedUiText(layout.composerLanguage, runtimeCurrentStepRaw)
    ? runtimeCurrentStepRaw
    : undefined;
  const runtimeWhyNow = isLanguageAlignedUiText(layout.composerLanguage, runtimeWhyNowRaw)
    ? runtimeWhyNowRaw
    : undefined;
  const runtimeVerifyItems = useMemo(
    () =>
      [
        ...(planRuntimeStatus?.verifyMethod ?? []),
        ...(runtimeCurrentThread?.verifyMethod ?? []),
      ].filter((item, index, array): item is string => Boolean(item) && array.indexOf(item) === index),
    [planRuntimeStatus?.verifyMethod, runtimeCurrentThread?.verifyMethod],
  );
  const runtimeBlockedReason =
    planRuntimeStatus?.blockedReason ??
    runtimeCurrentThread?.blockedReason ??
    runtimeCurrentThread?.blocker;
  const runtimeNextAfterCurrent =
    planRuntimeStatus?.nextAfterCurrent ?? runtimeCurrentThread?.nextAfterCurrent;
  const recoveredDisplayFacts = useMemo(
    () =>
      preferRecoveredPlanRuntimeFacts({
        recovered: recoveredRuntime,
        runtime: {
          currentStep: runtimeCurrentStep,
          whyNow: runtimeWhyNow,
          nextAfterCurrent: runtimeNextAfterCurrent,
          blockedReason: runtimeBlockedReason,
          verifyMethod: runtimeVerifyItems,
        },
        plan: {
          currentStep: data.plan.currentStep,
          whyNow: data.plan.whyNow,
          nextAfterCurrent: data.plan.nextAfterCurrent,
          blockedReason: data.plan.blockedReason,
          verifyMethod: data.plan.verifyMethod,
        },
      }),
    [
      data.plan.blockedReason,
      data.plan.currentStep,
      data.plan.nextAfterCurrent,
      data.plan.verifyMethod,
      data.plan.whyNow,
      recoveredRuntime,
      runtimeBlockedReason,
      runtimeCurrentStep,
      runtimeNextAfterCurrent,
      runtimeVerifyItems,
      runtimeWhyNow,
    ],
  );
  const formalPlanIdentity = useMemo(
    () => ({
      recovered: recoveredRuntime,
      runtimeCurrentStep: runtimeCurrentStepRaw,
      planCurrentStep: data.plan.currentStep,
      runtimePlanId: data.memory.workspace?.latestPlanRuntime?.planId,
      planId: data.plan.id,
    }),
    [
      data.memory.workspace?.latestPlanRuntime?.planId,
      data.plan.currentStep,
      data.plan.id,
      runtimeCurrentStepRaw,
      recoveredRuntime,
    ],
  );
  const formalPlanLive = formalPlanIsLiveRuntimeIdentity(formalPlanIdentity);
  const livePlanFrozen = liveFormalPlanFrozen({
    ...formalPlanIdentity,
    frozen: data.plan.frozen,
  });
  const livePlanTitle = liveFormalPlanTitle({
    ...formalPlanIdentity,
    planTitle: data.plan.title,
  });
  const livePlanSummary = liveFormalPlanSummary({
    ...formalPlanIdentity,
    planSummary: data.plan.summary,
  });
  const liveTrainingSummary = liveTrainingFormalSummary({
    ...formalPlanIdentity,
    planSummary: data.plan.summary,
  });
  const liveTrainingSource = liveTrainingSourceFallback({
    ...formalPlanIdentity,
    planSummary: data.plan.summary,
  });
  const liveTask = formalTaskIsLiveRuntimeIdentity({
    recovered: recoveredRuntime,
    runtimeCurrentStep: recoveredDisplayFacts.currentStep,
    taskTitle: data.task.title,
  });
  const leftoverSuggestedActionNotLive =
    (Boolean(recoveredRuntime) && !formalPlanLive && !liveTask) ||
    streakAdaptsWithoutInventingLiveObjects({
      failureStreak: data.memory.coachingAdaptation?.failureStreak,
      successStreak: data.memory.coachingAdaptation?.successStreak,
      streakBlocksLiveObjectMint:
        data.memory.coachingAdaptation?.streakBlocksLiveObjectMint === true ||
        data.coachFocus?.streakBlocksLiveObjectMint === true,
      livePlan: formalPlanLive,
      liveTask,
      liveCard: Boolean(data.workspaceTrainingState?.selectedCardId?.trim()),
    }) ||
    pressureAdaptsWithoutInventingLiveObjects({
      timeBudget: data.memory.coachingAdaptation?.timeBudget,
      taskUrgency: data.memory.coachingAdaptation?.taskUrgency,
      pressureBlocksLiveObjectMint:
        data.memory.coachingAdaptation?.pressureBlocksLiveObjectMint === true ||
        data.coachFocus?.pressureBlocksLiveObjectMint === true,
      livePlan: formalPlanLive,
      liveTask,
      liveCard: Boolean(data.workspaceTrainingState?.selectedCardId?.trim()),
    }) ||
    data.memory.coachingAdaptation?.closedLoopReturnBlocksTaskMint === true ||
    data.coachFocus?.closedLoopReturnBlocksTaskMint === true;
  const leftoverMintingSuggestedActionsNotLive = leftoverMintingSuggestedActionsAreNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: recoveredDisplayFacts.currentStep,
    runtimePlanId: data.memory.workspace?.latestPlanRuntime?.planId,
    planId: data.plan.id,
    planCurrentStep: data.plan.currentStep,
    taskTitle: data.task.title,
  });
  const liveSuggestedActions = leftoverSuggestedActionsNotLive
    ? []
    : leftoverMintingSuggestedActionsNotLive || leftoverSuggestedActionNotLive
      ? data.suggestedActions.filter(
          (item) => !["plan", "task", "next_task", "card"].includes(String(item.action ?? "")),
        )
      : data.suggestedActions;
  const liveTrainingTitle = liveTrainingTitleFallback({
    ...formalPlanIdentity,
    planTitle: data.plan.title,
    taskTitle: data.task.title,
  });
  const liveTrainingFocus = liveTrainingFocusFallback({
    ...formalPlanIdentity,
    taskTitle: data.task.title,
    coachFocus: resolvedCoachFocus,
    memoryFocus: data.memory.currentFocus,
  });
  const livePlanStages = liveFormalPlanStages({
    ...formalPlanIdentity,
    stages: data.plan.stages,
  });
  const livePlanCadence = liveFormalPlanCadence({
    ...formalPlanIdentity,
    cadence: data.plan.cadence,
  });
  const liveCoachStage =
    resolvedCoachStage ?? (formalPlanLive ? activePlanStage?.title : undefined);
  const liveStageChrome = useMemo(
    () =>
      resolveLivePlanStageChrome({
        recovered: recoveredRuntime,
        runtimeCurrentStep: recoveredDisplayFacts.currentStep,
        planCurrentStep: data.plan.currentStep,
        planStageTitle: activePlanStage?.title,
        planStageGoal: activePlanStage?.objective,
        runtimePlanId: formalPlanIdentity.runtimePlanId,
        planId: formalPlanIdentity.planId,
      }),
    [
      activePlanStage?.objective,
      activePlanStage?.title,
      data.plan.currentStep,
      formalPlanIdentity.planId,
      formalPlanIdentity.runtimePlanId,
      recoveredDisplayFacts.currentStep,
      recoveredRuntime,
    ],
  );
  const leftoverPlanNotLive = Boolean(recoveredRuntime) && !formalPlanLive;
  const visibleFormalPlan = useMemo(() => {
    if (!hasFormalPlan) {
      return null;
    }
    if (leftoverPlanNotLive && !recoveredDisplayFacts.currentStep) {
      return null;
    }
    if (!recoveredRuntime) {
      return data.plan;
    }
    return {
      ...data.plan,
      frozen: livePlanFrozen,
      title: livePlanTitle,
      summary: livePlanSummary,
      cadence: livePlanCadence,
      currentStep: recoveredDisplayFacts.currentStep,
      whyNow: recoveredDisplayFacts.whyNow ?? "",
      nextAfterCurrent: recoveredDisplayFacts.nextAfterCurrent ?? "",
      blockedReason: recoveredDisplayFacts.blockedReason ?? "",
      verifyMethod: recoveredDisplayFacts.verifyMethod ?? [],
      currentStageId:
        formalPlanLive && liveStageChrome.stageIsCurrent ? data.plan.currentStageId : undefined,
      stages: livePlanStages,
    };
  }, [
    data.plan,
    formalPlanLive,
    hasFormalPlan,
    livePlanCadence,
    livePlanFrozen,
    livePlanStages,
    livePlanSummary,
    livePlanTitle,
    leftoverPlanNotLive,
    liveStageChrome.stageIsCurrent,
    recoveredDisplayFacts,
    recoveredRuntime,
  ]);
  const liveEvidenceQueue = useMemo(
    () =>
      scopeEvidenceQueueToRuntimeStep({
        queue: data.memory.evidenceQueue,
        recovered: recoveredRuntime,
        currentStep: recoveredDisplayFacts.currentStep,
      }),
    [data.memory.evidenceQueue, recoveredDisplayFacts.currentStep, recoveredRuntime],
  );
  const planWhyNow = useMemo(() => {
    const verifyAdvance = planRuntimeStatus?.verifyPlanAdvance;
    const verifySentence = [verifyAdvance?.what, verifyAdvance?.why]
      .map((item) => item?.trim())
      .filter(Boolean)
      .join(" — ");
    if (verifyAdvance?.advanced && verifySentence) {
      return verifySentence;
    }
    if (recoveredRuntime && recoveredDisplayFacts.currentStep) {
      return recoveredDisplayFacts.whyNow;
    }
    return (
      recoveredDisplayFacts.whyNow ??
      runtimeWhyNow ??
      liveCoachTurnChrome.artifactRationale ??
      liveCoachTaskChrome.teachingGoal ??
      liveCoachTurnChrome.coachJudgmentTeachingGoal ??
      liveCoachTurnChrome.coachTurnTeachingGoal ??
      resolvedCoachSummary ??
      (leftoverTaskChromeNotLive ? undefined : data.plan.summary)
    );
  }, [
    liveCoachTurnChrome.coachTurnTeachingGoal,
    data.plan.summary,
    leftoverTaskChromeNotLive,
    liveCoachTaskChrome.teachingGoal,
    liveCoachTurnChrome.artifactRationale,
    planRuntimeStatus?.verifyPlanAdvance,
    recoveredDisplayFacts.currentStep,
    recoveredDisplayFacts.whyNow,
    recoveredRuntime,
    resolvedCoachSummary,
    liveCoachTurnChrome.coachJudgmentTeachingGoal,
    runtimeWhyNow,
  ]);
  const verifyPlanAdvanceNext = planRuntimeStatus?.verifyPlanAdvance?.advanced
    ? planRuntimeStatus.verifyPlanAdvance.next?.trim() || "" : "";
  const planVerifyItems = useMemo(() => {
    const items = lockRecoveredPlanVerifyItems({
      recovered: recoveredRuntime,
      currentStep: recoveredDisplayFacts.currentStep,
      verifyMethod: recoveredDisplayFacts.verifyMethod,
      fallbacks: [
        recoveredDisplayFacts.verifyMethod ?? [],
        data.plan.verifyMethod ?? [],
        leftoverCoachTurnChromeNotLive ? [] : latestCoachArtifact?.verification ?? [],
        liveCoachTaskChrome.successSignal ? [liveCoachTaskChrome.successSignal] : [],
        liveCoachTurnChrome.evaluationNextStep ? [liveCoachTurnChrome.evaluationNextStep] : [],
      ],
    });
    return items
      .filter((item) => !isTerminallyTruncatedText(item))
      .filter((item, index, values) => Boolean(item) && values.indexOf(item) === index)
      .slice(0, 3);
  }, [
    liveCoachTurnChrome.evaluationNextStep,
    data.plan.verifyMethod,
    liveCoachTaskChrome.successSignal,
    leftoverCoachTurnChromeNotLive,
    latestCoachArtifact?.verification,
    recoveredDisplayFacts.currentStep,
    recoveredDisplayFacts.verifyMethod,
    recoveredRuntime,
  ]);
  const planReviewReason = useMemo(
    () =>
      planRuntimeStatus?.reviewPoints?.[0]?.taskHint ??
      planRuntimeStatus?.reviewPoints?.[0]?.focusArea ??
      planRuntimeStatus?.reviewPoints?.[0]?.reason ??
      liveCoachTaskChrome.fallbackStep ??
      data.memory.dueReviews[0]?.taskHint ??
      data.memory.dueReviews[0]?.focusArea ??
      data.memory.dueReviews[0]?.reason ??
      data.memory.reviewSummary,
    [
      data.memory.dueReviews,
      data.memory.reviewSummary,
      liveCoachTaskChrome.fallbackStep,
      planRuntimeStatus?.reviewPoints,
    ],
  );
  const planReviewItems = useMemo<PlanReviewItem[]>(
    () =>
      (planRuntimeStatus?.reviewPoints?.length ? planRuntimeStatus.reviewPoints : data.memory.dueReviews)
        .slice(0, 4)
        .map((item, index) => toPlanReviewItem(item, index, layout.composerLanguage)),
    [data.memory.dueReviews, layout.composerLanguage, planRuntimeStatus?.reviewPoints],
  );
  const planReviewWindowLead = useMemo(() => {
    const primary = planReviewItems[0];
    if (!primary) {
      return (
        formattedNextReviewDue ??
        resolvedCoachReview ??
        (leftoverCoachTurnChromeNotLive ? undefined : data.reviewQueueSummary) ??
        (leftoverCoachTurnChromeNotLive ? undefined : data.memory.reviewRhythm)
      );
    }
    return [
      primary.meta,
      primary.taskHint,
      primary.focusArea,
    ].filter(Boolean)[0] ?? primary.title;
  }, [
    data.memory.reviewRhythm,
    data.reviewQueueSummary,
    leftoverCoachTurnChromeNotLive,
    formattedNextReviewDue,
    planReviewItems,
    resolvedCoachReview,
  ]);
  const planReturnPathLead = useMemo(() => {
    const returnTarget =
      recoveredRuntime && recoveredDisplayFacts.currentStep
        ? recoveredDisplayFacts.nextAfterCurrent
        : recoveredDisplayFacts.nextAfterCurrent ??
          runtimeNextAfterCurrent ??
          planReviewWindowLead ??
          resolvedCoachReview ??
          liveCoachTurnChrome.evaluationNextStep;
    if (!returnTarget) {
      return appUiCopy(layout.composerLanguage, "带验证结果回 Coach，再推进。");
    }
    return appUiCopy(layout.composerLanguage, "回到 Coach：{v}").replace("{v}", returnTarget);
  }, [
    liveCoachTurnChrome.evaluationNextStep,
    layout.composerLanguage,
    planReviewWindowLead,
    recoveredDisplayFacts.currentStep,
    recoveredDisplayFacts.nextAfterCurrent,
    recoveredRuntime,
    resolvedCoachReview,
    runtimeNextAfterCurrent,
  ]);
  const rememberedCoachSummary = useMemo(() => {
    const lines = [
      leftoverSettingsLearnerProjectOnboardingNotLive
        ? null
        : data.profile.targetProject
          ? appUiCopy(layout.composerLanguage, "你现在主要在推进：{v}").replace("{v}", data.profile.targetProject)
          : null,
      leftoverSettingsProfileRhythmNotLive
        ? null
        : data.profile.preferredLearningMode
          ? appUiCopy(layout.composerLanguage, "你更希望我这样带：{v}").replace("{v}", data.profile.preferredLearningMode)
          : null,
      leftoverSettingsProfileRhythmNotLive
        ? null
        : data.profile.preferredRhythm
          ? appUiCopy(layout.composerLanguage, "你想保持的节奏：{v}").replace("{v}", data.profile.preferredRhythm)
          : null,
      leftoverSettingsLearnerProjectOnboardingNotLive
        ? null
        : data.profile.onboardingRequest
          ? appUiCopy(layout.composerLanguage, "这轮最想推进的是：{v}").replace("{v}", data.profile.onboardingRequest)
          : null,
    ].filter((item): item is string => Boolean(item));
    if (!lines.length) {
      return undefined;
    }
    return (
      <div className="coach-plan-view__signal-feed">
        {lines.slice(0, 3).map((line) => (
          <div key={line} className="coach-plan-view__support-feed-item">
            <p>{line}</p>
          </div>
        ))}
      </div>
    );
  }, [
    data.profile.onboardingRequest,
    data.profile.preferredLearningMode,
    data.profile.preferredRhythm,
    data.profile.targetProject,
    layout.composerLanguage,
    leftoverSettingsLearnerProjectOnboardingNotLive,
    leftoverSettingsProfileRhythmNotLive,
  ]);
  const planSupportRows = useMemo(
    () =>
      [
        resolvedCoachFocus
          ? {
              id: "focus",
              label: appUiCopy(layout.composerLanguage, "当前聚焦"),
              value: resolvedCoachFocus,
            }
          : null,
        resolvedCoachScenario
          ? {
              id: "scenario",
              label: appUiCopy(layout.composerLanguage, "这轮主线"),
              value: coachingScenarioLabel(resolvedCoachScenario, layout.composerLanguage),
            }
          : null,
        liveCoachStage
          ? {
              id: "stage",
              label: appUiAltCopy(layout.composerLanguage, "当前阶段"),
              value: liveCoachStage,
            }
          : null,
        resolvedCoachSignal
          ? {
              id: "signal",
              label: appUiCopy(layout.composerLanguage, "学习信号"),
              value: learnerSignalLabel(resolvedCoachSignal, layout.composerLanguage),
            }
          : null,
        livePlanCadence
          ? {
              id: "cadence",
              label: t.planCadence,
              value: livePlanCadence,
            }
          : null,
        {
          id: "status",
          label: t.planFrozen,
          value: livePlanFrozen ? t.planFreeze : t.planLive,
        },
        resolvedCoachReview
          ? {
              id: "review",
              label: t.reviewRhythm,
              value: resolvedCoachReview,
            }
          : null,
      ].filter((item): item is { id: string; label: string; value: string } => Boolean(item?.value)),
    [
      liveCoachStage,
      livePlanCadence,
      livePlanFrozen,
      layout.composerLanguage,
      resolvedCoachFocus,
      resolvedCoachReview,
      resolvedCoachScenario,
      resolvedCoachSignal,
      t.planCadence,
      t.planFreeze,
      t.planFrozen,
      t.planLive,
      t.reviewRhythm,
    ],
  );
  const coachStrategyLines = useMemo(
    () =>
      [
        compactCoachLine(
          appUiCopy(layout.composerLanguage, "当前主线依据"),
          memoryEvidence.join(" · "),
          layout.composerLanguage,
        ),
        compactCoachLine(
          appUiCopy(layout.composerLanguage, "下一轮会怎么续上"),
          liveCoachTurnChrome.resumeThread,
          layout.composerLanguage,
        ),
        compactCoachLine(
          appUiCopy(layout.composerLanguage, "回应方式会偏向"),
          liveCoachTurnChrome.supportStrategy,
          layout.composerLanguage,
        ),
      ].filter((item): item is string => Boolean(item)),
    [
      memoryEvidence,
      liveCoachTurnChrome.resumeThread,
      liveCoachTurnChrome.supportStrategy,
      layout.composerLanguage,
    ],
  );
  const coachThreadSubtitle = useMemo(() => {
    return coachLaneLabel(resolvedCoachScenario, layout.composerLanguage);
  }, [layout.composerLanguage, resolvedCoachScenario]);
  const coachSummaryText = useMemo(() => {
    if (!resolvedCoachSummary) {
      return undefined;
    }
    const firstLine = resolvedCoachSummary.split("\n").find((line) => line.trim().length > 0)?.trim();
    return firstLine || resolvedCoachSummary;
  }, [resolvedCoachSummary]);
  const coachRelationshipStage = data.coachFocus?.relationshipStage;
  const coachContinuitySummary = liveCoachTurnChrome.continuitySummary;
  const resolvedCoachStateSummary = useMemo(() => {
    if (coachStrategyLines.length === 0) {
      return coachSummaryText;
    }
    return [coachSummaryText, ...coachStrategyLines].filter(Boolean).join("\n");
  }, [coachStrategyLines, coachSummaryText]);
  const headerCoachTitle = useMemo(() => {
    if (!providerCanCoachNow) {
      return undefined;
    }
    if (coachRelationshipStage === "intake" || isFirstCoachConversation) {
      return appUiCopy(layout.composerLanguage, "先认识一下");
    }
    return resolvedCoachFocus ?? coachThreadSubtitle;
  }, [
    coachRelationshipStage,
    coachThreadSubtitle,
    isFirstCoachConversation,
    layout.composerLanguage,
    providerCanCoachNow,
    resolvedCoachFocus,
  ]);
  const headerCoachDetail = useMemo(() => {
    if (!providerCanCoachNow) {
      return undefined;
    }

    const raw =
      coachRelationshipStage === "intake" || isFirstCoachConversation
        ? data.coachFocus?.firstTurnPriority
          ? appUiCopy(layout.composerLanguage, "先了解你的目标、项目和卡点，再决定最适合怎么带你。")
          : appUiCopy(layout.composerLanguage, "先说你的目标、项目或卡点，我会先判断怎么带你更合适。")
        : coachContinuitySummary ??
          runtimeCurrentStep ??
          resolvedCoachNextStep ??
          latestArtifactTeaser ??
          activePlanStage?.title ??
          coachSummaryText;
    return truncateInlineText(raw, 54);
  }, [
    activePlanStage?.title,
    coachContinuitySummary,
    coachRelationshipStage,
    coachSummaryText,
    data.coachFocus?.firstTurnPriority,
    isFirstCoachConversation,
    layout.composerLanguage,
    latestArtifactTeaser,
    providerCanCoachNow,
    resolvedCoachNextStep,
    runtimeCurrentStep,
  ]);
  const workspaceAuthoritySummary = workspaceAuthority?.nextSafeAction
    ? { nextSafeAction: workspaceAuthority.nextSafeAction }
    : undefined;
  const coachRuntimeContextSignature = [
    runtimeCurrentStage?.id,
    runtimeCurrentStage?.title,
    runtimeCurrentThread?.focusArea,
    runtimeCurrentStep,
    runtimeCurrentThread?.nextStep,
    runtimeNextAfterCurrent,
    planRuntimeStatus?.nextTrainingAction,
  ]
    .map((value) => normalizeInlineComparisonText(value))
    .filter(Boolean)
    .join("\u001f");
  useEffect(() => {
    const previousSignature = coachRuntimeContextSignatureRef.current;
    if (previousSignature === undefined) {
      coachRuntimeContextSignatureRef.current = coachRuntimeContextSignature;
      return;
    }
    if (previousSignature === coachRuntimeContextSignature) {
      return;
    }

    coachRuntimeContextSignatureRef.current = coachRuntimeContextSignature;
    setCoachContextTransition(
      coachRuntimeContextSignature && data.conversation.length > 0
        ? {
            signature: coachRuntimeContextSignature,
            conversationLength: data.conversation.length,
          }
        : undefined,
    );
  }, [coachRuntimeContextSignature, data.conversation.length]);
  const hasCoachContextTransition =
    coachContextTransition?.signature === coachRuntimeContextSignature &&
    coachContextTransition.conversationLength === data.conversation.length;
  const openPlanComposerMode = useCallback(
    (mode: PlanComposerMode) => {
      setActiveView("coach");
      setPlanComposerMode(mode);
      setCoachPlanContext(mode);
      const modeCopy = resolvePlanComposerCopy(layout.composerLanguage).modes[mode];
      const prompt =
        mode === "blocker" ? modeCopy.secondaryPrompt.prompt : modeCopy.primaryPrompt.prompt;
      setComposerDraft(prompt);
      requestCoachComposerFocus();
    },
    [layout.composerLanguage, requestCoachComposerFocus, setActiveView],
  );
  const handlePlanOrientationAction = useCallback(
    (action: PlanOrientationAction | string | null) => {
      if (!action) {
        return;
      }
      if (action === "generate_plan") {
        openPlanComposerMode("generate");
        return;
      }
      if (action === "continue_without_plan") {
        setActiveView("coach");
        requestCoachComposerFocus();
        return;
      }
      if (action === "clear_blocker" || action === "continue_step") {
        sendRecoveredPlanResumeRef.current(action);
        return;
      }
      if (action === "wait") {
        openPlanComposerMode("evidence");
        if (isBrowserPreview) {
          setOperationMessage({
            tone: "info",
            message:
              appUiCopy(layout.composerLanguage, "预览不能改真实数据，请回 VS Code。请在输入框里核对证据。"),
          }, "plan");
        }
        return;
      }
      if (action === "adopt_evidence") {
        const pendingEvidenceId = liveEvidenceQueue.pending[0]?.id?.trim();
        if (pendingEvidenceId) {
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.evidenceAdopt,
              payload: { evidenceId: pendingEvidenceId },
            },
          });
          return;
        }
        openPlanComposerMode("evidence");
        return;
      }
      if (action === "open_training") {
        setActiveView("training");
        return;
      }
      if (action === "unfreeze_plan" && livePlanFrozen) {
        pendingLivePlanTaskMintRef.current = {
          commandId: trainerCommands.updatePlan,
        };
        setOperationMessage({
          tone: "info",
          message: livePlanUpdatePendingMessage(layout.composerLanguage),
        }, "plan");
        postMessage({
          type: "plan/freeze",
          payload: { frozen: false },
        });
      }
    },
    [
      liveEvidenceQueue.pending,
      livePlanFrozen,
      layout.composerLanguage,
      isBrowserPreview,
      openPlanComposerMode,
      postMessage,
      requestCoachComposerFocus,
      setActiveView,
      setOperationMessage,
    ],
  );
  const handleResourcesOrientationAction = useCallback(
    (action: ResourcesOrientationAction | string) => {
      if (action === "open_coach") {
        setActiveView("coach");
        return;
      }
      if (action === "import_resource") {
        triggerResourceUpload({
          browserPreview: isBrowserPreview,
          payloadMode: "files",
          filesInputRef: uploadFilesInputRef,
          folderInputRef: uploadFolderInputRef,
        });
        return;
      }
      if (action === "retry_index") {
        void requestResourceIndex();
        return;
      }
      if (action === "preview_resource") {
        const resourceId = resourceConversationContextIds.find((id) =>
          data.resources.some((resource) => resource.id === id),
        );
        if (resourceId && !isBrowserPreview) {
          postMessage({
            type: "command/execute",
            payload: { commandId: trainerCommands.previewSandbox, payload: { resourceId } },
          });
        }
        return;
      }
      if (action === "open_plan") {
        setActiveView("plan");
        return;
      }
      if (action === "open_training") {
        setActiveView("training");
      }
    },
    [
      data.resources,
      isBrowserPreview,
      postMessage,
      requestResourceIndex,
      resourceConversationContextIds,
      setActiveView,
    ],
  );
  const coachOrientation = useMemo(() => {
    const training = data.workspaceTrainingState;
    const sidecarStatus =
      data.connection.state === "offline"
        ? "error"
        : data.connection.state === "starting"
          ? "starting"
          : data.connection.state === "connected"
            ? "ready"
            : "unknown";
    return deriveCoachOrientation({
      sidecarStatus,
      hasProviderModel: Boolean(data.providerConfig.model?.trim() && data.providerConfig.baseUrl?.trim()),
      providerSendBlocked: !providerCanCoachNow || Boolean(providerBlockReason),
      providerBlockReason: providerBlockReason ?? providerSendState.reason,
      workspaceBlocked: workspaceSessionBlocked,
      workspaceBlockReason: workspaceSessionBlockMessage,
      streaming: streaming.isStreaming,
      checkpointRecovery:
        leftoverStreamingCheckpointNotLive
          ? false
          : isCoachCheckpointRecoveryState(streaming) ||
            streamingCheckpointToOrientation(
              data.workspaceTrainingState?.workspaceId || data.memory.workspace?.workspaceId
                ? selectStreamingCheckpointForScope(liveLatestStreamingCheckpoint, {
                    workspaceId:
                      data.workspaceTrainingState?.workspaceId || data.memory.workspace?.workspaceId || "",
                    providerProfileId: data.providerConfig.profileId,
                    providerName: data.providerConfig.name,
                    baseUrl: data.providerConfig.baseUrl,
                    model: data.providerConfig.model,
                  })
                : liveLatestStreamingCheckpoint,
            ),
      conversationCount: liveConversation.length,
      planBlockedReason: runtimeBlockedReason ?? data.plan?.blockedReason,
      planCurrentStep: runtimeCurrentStep,
      planWhyNow: runtimeWhyNow,
      activeThreadFocus:
        runtimeCurrentThread?.focusArea ??
        (leftoverTaskChromeNotLive ? undefined : data.memory.activeThread?.focusArea) ??
        liveCoachTaskChrome.currentFocus,
      trainingReliabilityPhase: leftoverTrainingHandoffChromeNotLive
        ? undefined
        : training?.latestTrainingReliability?.phase,
      operationReliabilityPhase: streaming.reliabilityPhase,
      operationReliabilityOutcome: streaming.reliabilityOutcome,
      trainingLearningPhase: leftoverTrainingHandoffChromeNotLive
        ? undefined
        : training?.latestTrainingHandoff?.learningPhase,
      trainingHandoffStatus: leftoverTrainingHandoffChromeNotLive
        ? undefined
        : training?.latestTrainingHandoff?.handoffStatus,
      selectedCardTitle: leftoverTrainingHandoffChromeNotLive
        ? undefined
        : liveTrainingNextChallengeTitle({
        ...formalPlanIdentity,
        planTitle: data.plan.title,
        taskTitle: data.task.title,
        cardTitle: training?.selectedCardTitle ?? training?.latestTrainingHandoff?.cardTitle,
      }),
      language: layout.composerLanguage,
      firstLookRecommendedNext: liveFirstLookSummary?.recommendedNextStep,
      firstLookWhy: liveFirstLookSummary?.whyThisGuess,
      transferState: liveTransferState,
    });
  }, [
    data.connection.state,
    liveConversation.length,
    leftoverTaskChromeNotLive,
    liveCoachTaskChrome.currentFocus,
    data.memory.activeThread?.focusArea,
    data.plan?.blockedReason,
    data.providerConfig.baseUrl,
    data.providerConfig.model,
    data.providerConfig.name,
    data.providerConfig.profileId,
    data.memory.workspace?.workspaceId,
    data.workspaceTrainingState,
    data.memory.workspace?.latestTransferState,
    leftoverStreamingCheckpointNotLive,
    leftoverTrainingHandoffChromeNotLive,
    leftoverTransferSkillNotLive,
    liveLatestStreamingCheckpoint,
    liveTransferState,
    liveFirstLookSummary?.recommendedNextStep,
    liveFirstLookSummary?.whyThisGuess,
    liveEvaluationHeadline,
    layout.composerLanguage,
    providerBlockReason,
    providerCanCoachNow,
    providerSendState.reason,
    runtimeBlockedReason,
    runtimeCurrentStep,
    runtimeCurrentThread?.focusArea,
    runtimeWhyNow,
    formalPlanIdentity,
    data.plan.title,
    data.task.title,
    streaming,
    workspaceSessionBlockMessage,
    workspaceSessionBlocked,
  ]);
  const planOrientation = useMemo(
    () =>
      derivePlanOrientation({
        hasFormalPlan: hasFormalPlan && formalPlanLive,
        frozen: livePlanFrozen,
        planCurrentStep: data.plan.currentStep,
        planId: data.plan.id,
        runtimePlanId: data.memory.workspace?.latestPlanRuntime?.planId,
        blockedReason: recoveredDisplayFacts.blockedReason,
        currentStep: recoveredDisplayFacts.currentStep,
        whyNow: recoveredDisplayFacts.whyNow,
        nextAfterCurrent: recoveredDisplayFacts.nextAfterCurrent,
        evidenceBinding: liveEvidenceBinding({
          binding: data.memory.workspace?.latestPlanRuntime?.evidenceBinding,
          pendingIds: liveEvidenceQueue.pending.map((item) => item.id),
          recovered: recoveredRuntime,
          currentStep: recoveredDisplayFacts.currentStep,
        }),
        pendingEvidenceIds: liveEvidenceQueue.pending.map((item) => item.id),
        pendingEvidenceCount: liveEvidenceQueue.pending.length,
        verifyMethod: recoveredDisplayFacts.verifyMethod,
        recoveredRuntime,
        resumeState: planRuntimeStatus?.resumeState,
        transferState: liveTransferState,
        firstLookRecommendedNext: liveFirstLookSummary?.recommendedNextStep,
        firstLookWhy: liveFirstLookSummary?.whyThisGuess,
        language: layout.composerLanguage,
      }),
    [
      liveEvidenceQueue.pending.length,
      data.memory.workspace?.latestPlanRuntime,
      leftoverTransferSkillNotLive,
      liveTransferState,
      data.memory.workspace?.latestTransferState,
      livePlanFrozen,
      data.plan.currentStep,
      data.plan.id,
      recoveredDisplayFacts,
      data.workspaceTrainingState?.latestTransferState,
      hasFormalPlan,
      layout.composerLanguage,
      leftoverFirstLookHeadlineNotLive,
      liveFirstLookSummary?.recommendedNextStep,
      liveFirstLookSummary?.whyThisGuess,
      recoveredRuntime,
      planRuntimeStatus?.resumeState,
    ],
  );
  const liveResources = leftoverResourceLibraryListNotLive
    ? data.resources.filter(resourceRecordIsAcknowledgedUpload)
    : data.resources;
  const liveSandboxState = leftoverResourceSandboxStateNotLive
    ? undefined
    : data.memory.sandboxState;
  const resourcesOrientation = useMemo(() => {
    const selectedResourceId = resourceConversationContextIds.find((id) =>
      liveResources.some((resource) => resource.id === id),
    );
    const selectedResource = liveResources.find((resource) => resource.id === selectedResourceId);
    const searchWorkspaceId = data.resourceSearch?.workspaceId;
    const currentWorkspaceId =
      data.memory.workspace?.workspaceId ?? data.workspaceTrainingState?.workspaceId;
    const liveSelectedResourceDetail = leftoverResourceSelectedDetailNotLive
      ? undefined
      : data.memory.selectedResourceDetail;
    const liveSandboxPreview = leftoverSandboxPreviewNotLive
      ? undefined
      : data.memory.sandboxPreview;
    const previewMatchesSelected = Boolean(
      selectedResource &&
        (liveSelectedResourceDetail?.id === selectedResource.id ||
          (selectedResource.sandboxPath &&
            liveSandboxPreview?.path === selectedResource.sandboxPath)),
    );
    const bindings = resolveResourcesBindingIds({
      selectedResourceId: selectedResource?.id,
      selectedCitationId: selectedResource?.citationId,
      planEvidenceBinding: data.memory.workspace?.latestPlanRuntime?.evidenceBinding,
      livePendingEvidenceIds: liveEvidenceQueue.pending.map((item) => item.id),
      recoveredRuntime,
      currentStep: recoveredDisplayFacts.currentStep,
      trainingTargetId: data.workspaceTrainingState?.latestTrainingHandoff?.targetId,
      trainingTargetKind: data.workspaceTrainingState?.latestTrainingHandoff?.targetKind,
      trainingSourceChain: data.workspaceTrainingState?.latestTrainingHandoff?.sourceChain,
    });
    return deriveResourcesOrientation({
      // r2-g2-0: the library header total counts distinct resources — the same
      // distinct-leaf source the tree group badges use, so the header number
      // always equals the sum of the group badges.
      resourceCount: new Set(liveResources.map((resource) => resource.id)).size,
      selectedResourceId: selectedResource?.id,
      selectedResourceTitle: selectedResource?.title,
      indexState: selectedResource?.indexState,
      resourceStatus: selectedResource?.status,
      trustState: selectedResource?.trustState,
      freshness: selectedResource?.freshness,
      qualityFlags: selectedResource?.qualityFlags,
      searchQuery: data.resourceSearch?.query.trim() === resourcesViewSearchQuery.trim()
        ? resourcesViewSearchQuery : undefined,
      searchHitCount: data.resourceSearch?.hits.length ?? data.resourceSearch?.total,
      searchWorkspaceId,
      currentWorkspaceId,
      hasPreview: previewMatchesSelected,
      boundPlanId: bindings.boundPlanId,
      boundTrainingCardId: bindings.boundTrainingCardId,
      language: layout.composerLanguage,
      materialRecommendation: data.memory.coachingAdaptation?.materialRecommendation,
      transferSceneCount: data.memory.coachingAdaptation?.transferSceneCount,
      transferState: liveTransferState?.state,
    });
  }, [
    data.memory.coachingAdaptation?.materialRecommendation,
    data.memory.coachingAdaptation?.transferSceneCount,
    leftoverResourceSelectedDetailNotLive,
    leftoverResourceLibraryListNotLive,
    leftoverResourceSandboxStateNotLive,
    leftoverSandboxPreviewNotLive,
    liveResources,
    data.memory.sandboxPreview?.path,
    data.memory.selectedResourceDetail?.id,
    data.memory.workspace?.latestPlanRuntime?.evidenceBinding,
    leftoverTransferSkillNotLive,
    liveTransferState?.state,
    data.memory.workspace?.latestTransferState?.state,
    liveEvidenceQueue.pending,
    recoveredDisplayFacts.currentStep,
    recoveredRuntime,
    data.memory.workspace?.workspaceId,
    data.resourceSearch,
    resourcesViewSearchQuery,
    data.workspaceTrainingState?.latestTrainingHandoff,
    data.workspaceTrainingState?.workspaceId,
    layout.composerLanguage,
    resourceConversationContextIds,
  ]);
  const trainingState = data.workspaceTrainingState;
  const selectedTrainingRouteCard = trainingState?.activeTrainingCardRouting?.selectedCard;
  const normalizedTrainingSubmode = normalizeSharedTrainingSubmode(
    trainingState?.latestTrainingSubmode,
  );
  const shouldPrioritizeReviewArtifact = Boolean(
    trainingState?.reviewArtifact?.id &&
      trainingState.reviewArtifact.status !== "archived" &&
      (normalizedTrainingSubmode === "review-queue" || normalizedTrainingSubmode === "review"),
  );
  const restoredTrainingCardCandidate = useMemo(
    () => restoredTrainingCard(trainingState, trainingRestoreContext),
    [trainingRestoreContext, trainingState],
  );
  const selectedTrainingCardCandidate = useMemo(() => {
    const restoredCard = restoredTrainingCardCandidate;
    if (trainingRestoreContext?.target && restoredCard) {
      return restoredCard;
    }
    if (shouldPrioritizeReviewArtifact && trainingState?.reviewArtifact?.id) {
      return restoredTrainingCard(trainingState, {
        target: "review_artifact",
        reviewArtifactId: trainingState.reviewArtifact.id,
      });
    }
    const candidates = trainingState?.trainingCardCandidates;
    if (!candidates?.length) {
      return restoredCard;
    }

    const selectedCardId = trainingState?.selectedCardId?.trim();
    const routeSelectedCardId = selectedTrainingRouteCard?.cardId?.trim();

    // Leftover stored cards / title / current_step must not count as live selectedCardId.
    // Live only when runtime still carries a matching card id — never candidates[0] fallback.
    if (selectedCardId) {
      const selectedById = candidates.find((card) =>
        formalCardIsLiveRuntimeIdentity({
          cardId: card.cardId,
          selectedCardId,
          cardTitle: card.title,
        }),
      );
      if (selectedById) {
        return selectedById;
      }
    }

    if (routeSelectedCardId && routeSelectedCardId === selectedCardId) {
      const selectedByRouteId = candidates.find((card) =>
        formalCardIsLiveRuntimeIdentity({
          cardId: card.cardId,
          selectedCardId: routeSelectedCardId,
          cardTitle: card.title,
        }),
      );
      if (selectedByRouteId) {
        return selectedByRouteId;
      }
    }

    return restoredCard;
  }, [restoredTrainingCardCandidate, shouldPrioritizeReviewArtifact, trainingState]);
  const trainingRestoreForeground = Boolean(
    trainingRestoreContext?.target &&
      restoredTrainingCardCandidate?.cardId &&
      selectedTrainingCardCandidate?.cardId === restoredTrainingCardCandidate.cardId,
  );
  const reviewArtifactForeground = Boolean(
    trainingState?.reviewArtifact?.id &&
      selectedTrainingCardCandidate?.cardId === trainingState.reviewArtifact.id &&
      (shouldPrioritizeReviewArtifact ||
        (trainingRestoreForeground && trainingRestoreContext?.target === "review_artifact")),
  );
  // A retained review is history unless that exact review is the foreground card.
  const activeTrainingReviewArtifact = reviewArtifactForeground
    ? trainingState?.reviewArtifact
    : undefined;
  const trainingLedgerEntry =
    trainingState?.trainingEventLedger?.find((entry) => entry.selectedCardId === trainingState?.selectedCardId) ??
    trainingState?.trainingEventLedger?.find((entry) => entry.cardCandidateId === trainingState?.selectedCardId) ??
    trainingState?.trainingEventLedger?.[0];
  const trainingCardType = reviewArtifactForeground || trainingRestoreForeground
    ? (selectedTrainingCardCandidate?.type ?? "practice")
    : (trainingState?.selectedCardType ??
      selectedTrainingRouteCard?.type ??
      selectedTrainingCardCandidate?.type ??
      "practice");
  const activeTrainingCardId = reviewArtifactForeground || trainingRestoreForeground
    ? selectedTrainingCardCandidate?.cardId
    : (trainingState?.selectedCardId ??
      (selectedTrainingRouteCard?.cardId &&
      selectedTrainingRouteCard.cardId === trainingState?.selectedCardId
        ? selectedTrainingRouteCard.cardId
        : undefined));
  displayedTrainingCardIdRef.current = activeTrainingCardId;
  // §三: a card or scope change invalidates the in-flight remote verification
  // panel; the controller owns that state and clears it here.
  useEffect(() => {
    resetRemoteVerification();
  }, [activeTrainingCardId, syncCursor.generation, syncCursor.workspaceId, syncCursor.sessionId, resetRemoteVerification]);
  const activityDraftKey = `${composerSessionKey}\u0000${activeTrainingCardId ?? "unselected"}`;
  const activityDraft = layout.activityDrafts?.[activityDraftKey] ?? "";
  const [activityAttachmentBank, setActivityAttachmentBank] = useState<Record<string, MessageAttachment[]>>({});
  const activityAttachments = activityAttachmentBank[activityDraftKey] ?? [];
  const setActivityAttachments = (attachments: MessageAttachment[]) => {
    setActivityAttachmentBank((bank) => ({ ...bank, [activityDraftKey]: attachments }));
  };
  const setActivityDraft = useCallback((value: string) => {
    useWorkbenchState.getState().setActivityDraft(activityDraftKey, value);
  }, [activityDraftKey]);
  const trainingRestoreReplacesSelectedCard = Boolean(
    trainingRestoreForeground &&
      activeTrainingCardId &&
      activeTrainingCardId !== trainingState?.selectedCardId,
  );
  const restoredTrainingCardStatus = trainingRestoreForeground
    ? trainingRestoreContext?.target === "scenario_lab"
      ? trainingState?.scenarioLab?.status
      : trainingRestoreContext?.target === "theory_drill"
        ? trainingState?.theoryDrill?.status
        : trainingRestoreContext?.target === "review_artifact"
          ? trainingState?.reviewArtifact?.status
          : trainingState?.latestTrainingNextHop?.status
    : undefined;
  const effectiveTrainingSubmode = reviewArtifactForeground
    ? "review"
    : trainingRestoreForeground
      ? trainingRestoreContext?.target === "theory_drill"
        ? "flash"
        : trainingRestoreContext?.target === "scenario_lab"
          ? "scenario"
          : trainingRestoreContext?.target === "review_artifact"
            ? "review"
            : (trainingState?.latestTrainingSubmode ??
              (trainingCardType === "flash" ? "flash" : "practice"))
      : trainingState?.latestTrainingSubmode;
  const effectiveSelectedTrainingCardStatus = reviewArtifactForeground
    ? (trainingState?.reviewArtifact?.status === "resolved" ? "reviewed" : "active")
    : (trainingRestoreForeground
      ? (restoredTrainingCardStatus ?? "active")
      : trainingState?.selectedCardStatus);
  const visibleTrainingCardTitle = reviewArtifactForeground
    ? selectedTrainingCardCandidate?.title
    : liveTrainingNextChallengeTitle({
    ...formalPlanIdentity,
    recovered: formalPlanIdentity.recovered && !independentTrainingSelectionLive,
    planTitle: data.plan.title,
    taskTitle: data.task.title,
    cardTitle: pickFirstText(
      trainingRestoreForeground ? selectedTrainingCardCandidate?.title : undefined,
      leftoverTrainingHandoffChromeNotLive ? undefined : trainingState?.selectedCardTitle,
      leftoverTrainingHandoffChromeNotLive ? undefined : selectedTrainingRouteCard?.title,
      leftoverTrainingHandoffChromeNotLive && !trainingRestoreForeground
        ? undefined
        : selectedTrainingCardCandidate?.title,
    ),
  });
  const trainingLearningSubtype = resolveTrainingLearningSubtype(
    selectedTrainingCardCandidate?.learningSubtype,
    selectedTrainingRouteCard?.learningSubtype,
    trainingState?.activeTrainingCardRouting?.selectedCard?.learningSubtype,
  );
  const trainingLearningFamily = resolveTrainingLearningFamily(
    selectedTrainingCardCandidate,
    selectedTrainingRouteCard,
    trainingState?.activeTrainingCardRouting?.selectedCard,
  );
  const trainingPracticeVerificationMode = resolveTrainingPracticeVerificationMode({
    cardType: trainingCardType,
    learningFamily: trainingLearningFamily,
  });
  const trainingScenarioPackLabel = pickFirstText(
    selectedTrainingCardCandidate?.scenarioPack,
    selectedTrainingRouteCard?.scenarioPack,
    trainingState?.latestTrainingHandoff?.scenarioPack,
    trainingState?.latestTrainingNextHop?.scenarioPack,
  );
  const trainingSuggestedWorkspaceAction = pickFirstText(
    selectedTrainingCardCandidate?.suggestedWorkspaceAction,
    selectedTrainingRouteCard?.suggestedWorkspaceAction,
  );
  const trainingScenario = pickFirstText(
    selectedTrainingCardCandidate?.scenario,
    selectedTrainingRouteCard?.scenario,
    leftoverTrainingHandoffChromeNotLive
      ? undefined
      : trainingState?.latestTrainingNextHop?.summary,
  );
  const coachTrainingInlineAction = useMemo(() => {
    if (leftoverTrainingHandoffChromeNotLive) {
      return null;
    }
    const selectedCardId = activeTrainingCardId;
    if (!selectedCardId) {
      return null;
    }
    const selectedCardTitle = visibleTrainingCardTitle;
    if (!selectedCardTitle) {
      return null;
    }
    const rationale = pickFirstText(
      trainingRestoreForeground ? selectedTrainingCardCandidate?.whyNow : undefined,
      leftoverTrainingHandoffChromeNotLive
        ? undefined
        : trainingState?.activeTrainingCardRouting?.whyThisCard,
      trainingRestoreForeground ? undefined : trainingLedgerEntry?.candidateWhyNow,
      leftoverTrainingHandoffChromeNotLive ? undefined : selectedTrainingCardCandidate?.whyNow,
      leftoverTrainingHandoffChromeNotLive ? undefined : selectedTrainingRouteCard?.deliverable,
    );
    return {
      label: t.trainingOpenCurrentCard,
      title: rationale ?? selectedCardTitle,
    };
  }, [
    activeTrainingCardId,
    leftoverTrainingHandoffChromeNotLive,
    selectedTrainingRouteCard?.cardId,
    selectedTrainingCardCandidate?.title,
    selectedTrainingCardCandidate?.whyNow,
    trainingState?.activeTrainingCardRouting?.selectedCardId,
    trainingLedgerEntry?.candidateWhyNow,
    selectedTrainingRouteCard?.deliverable,
    selectedTrainingRouteCard?.title,
    trainingState?.activeTrainingCardRouting?.whyThisCard,
    trainingState?.selectedCardId,
    trainingState?.selectedCardTitle,
    trainingRestoreForeground,
    t.trainingOpenCurrentCard,
    visibleTrainingCardTitle,
  ]);
  const trainingApiHints = pickLanguageAlignedTrainingList(layout.composerLanguage, [
    ...(selectedTrainingCardCandidate?.apiHints ?? []),
    ...(selectedTrainingRouteCard?.apiHints ?? []),
  ]);
  const trainingSelfCheck = pickLanguageAlignedTrainingList(layout.composerLanguage, [
    ...(selectedTrainingCardCandidate?.selfCheck ?? []),
    ...(selectedTrainingRouteCard?.selfCheck ?? []),
  ]);
  const trainingFilesToTouch =
    selectedTrainingCardCandidate?.filesToTouch ?? selectedTrainingRouteCard?.filesToTouch ?? [];
  const trainingHintLadder = pickLanguageAlignedTrainingList(layout.composerLanguage, [
    ...(selectedTrainingCardCandidate?.hintLadder ?? []),
    ...(selectedTrainingRouteCard?.hintLadder ?? []),
  ]);
  const trainingCommonMistakes = pickLanguageAlignedTrainingList(layout.composerLanguage, [
    ...(selectedTrainingCardCandidate?.commonMistakes ?? []),
    ...(selectedTrainingRouteCard?.commonMistakes ?? []),
  ]);
  const trainingStuckRecovery = pickFirstText(
    selectedTrainingCardCandidate?.stuckRecovery,
    selectedTrainingRouteCard?.stuckRecovery,
  );
  const trainingReflectionPrompt = pickFirstText(
    selectedTrainingCardCandidate?.reflectionPrompt,
    selectedTrainingRouteCard?.reflectionPrompt,
  );
  const trainingWhyThisCard = leftoverTrainingHandoffChromeNotLive
    ? undefined
    : pickFirstText(
        trainingState?.activeTrainingCardRouting?.whyThisCard,
        trainingLedgerEntry?.whyThisCard,
      );
  const trainingDeliverable = pickFirstText(
    selectedTrainingCardCandidate?.deliverable,
    selectedTrainingRouteCard?.deliverable,
  );
  const trainingValidationMethod = pickFirstText(
    selectedTrainingCardCandidate?.validationMethod,
    selectedTrainingRouteCard?.validationMethod,
  );
  const trainingVerificationMethod = pickFirstText(
    selectedTrainingCardCandidate?.verificationMethod,
    selectedTrainingRouteCard?.verificationMethod,
  );
  const trainingDeliverables = pickLanguageAlignedTrainingList(layout.composerLanguage, [
    trainingDeliverable,
    ...(selectedTrainingCardCandidate?.learnerDeliverables ?? []),
    ...(selectedTrainingRouteCard?.learnerDeliverables ?? []),
    ...(trainingLedgerEntry?.learnerDeliverables ?? []),
  ]);
  const cardScopedVerifyItems = pickLanguageAlignedTrainingList(layout.composerLanguage, [
    trainingValidationMethod,
    trainingVerificationMethod,
    ...(selectedTrainingCardCandidate?.verificationSteps ?? []),
    ...(selectedTrainingRouteCard?.verificationSteps ?? []),
    ...(trainingLedgerEntry?.verificationSteps ?? []),
  ]);
  const contextualTrainingVerifyItems =
    trainingCardType === "flash"
      ? []
      : pickLanguageAlignedTrainingList(layout.composerLanguage, [
          ...runtimeVerifyItems,
          ...planVerifyItems,
        ]);
  const authoritativeVerifyItems =
    cardScopedVerifyItems.length > 0 ? cardScopedVerifyItems : contextualTrainingVerifyItems;
  const trainingCardWhy = leftoverTrainingHandoffChromeNotLive
    ? pickFirstText(
        runtimeWhyNow,
        recoveredRuntime ? recoveredDisplayFacts.whyNow : undefined,
      )
    : pickFirstText(
        trainingWhyThisCard,
        selectedTrainingCardCandidate?.whyNow,
        trainingState?.latestTrainingNextHop?.whyNow,
        runtimeWhyNow,
        recoveredRuntime ? recoveredDisplayFacts.whyNow : undefined,
      );
  const liveTrainingWhy = liveTrainingWhyNow({
    ...formalPlanIdentity,
    taskTitle: data.task.title,
    cardWhy: trainingCardWhy,
    liveWhy: liveTrainingSummary || resolvedCoachSummary,
  });
  const liveTrainingCoachChrome = liveTrainingCoachSummary({
    ...formalPlanIdentity,
    taskTitle: data.task.title,
    coachSummary: resolvedCoachSummary,
  });
  const liveTrainingHandoffChrome = preferRecoveredTrainingHandoffChrome({
    ...leftoverChromeIdentity,
    recovered: !independentTrainingSelectionLive && leftoverChromeIdentity.recovered,
    successSignal: pickFirstText(
      trainingState?.latestTrainingHandoff?.successSignal,
      selectedTrainingCardCandidate?.successSignal,
      selectedTrainingRouteCard?.successSignal,
      trainingLedgerEntry?.successSignal,
    ),
    returnWith: pickFirstText(
      selectedTrainingCardCandidate?.returnWith,
      selectedTrainingRouteCard?.returnWith,
      trainingState?.latestTrainingHandoff?.returnWith,
    ),
    cardTitle: pickFirstText(
      trainingState?.latestTrainingHandoff?.cardTitle,
      trainingState?.latestTrainingNextHop?.cardTitle,
      trainingState?.latestTrainingNextHop?.title,
    ),
    selectedCardTitle: trainingState?.selectedCardTitle,
    followup: trainingState?.latestLearningFollowup,
    blocker: pickFirstText(
      trainingState?.latestLearningBlocker,
      trainingState?.latestTrainingHandoff?.blockedBy,
    ),
    handoffSummary: trainingState?.latestTrainingHandoff?.handoffSummary,
    nextAfterCompletion: pickFirstText(
      selectedTrainingCardCandidate?.nextAfterCompletion,
      selectedTrainingRouteCard?.nextAfterCompletion,
      trainingState?.activeTrainingCardRouting?.nextAfterCompletion,
      trainingState?.latestTrainingHandoff?.nextAfterCompletion,
    ),
    fallbackAction: pickFirstText(
      trainingState?.activeTrainingCardRouting?.fallbackAction,
      trainingState?.latestTrainingHandoff?.fallbackAction,
    ),
    nextHopTitle: trainingState?.latestTrainingNextHop?.title,
    nextHopCardTitle: trainingState?.latestTrainingNextHop?.cardTitle,
    nextHopHandoffSummary: trainingState?.latestTrainingNextHop?.handoffSummary,
    nextHopNextAfterCompletion: trainingState?.latestTrainingNextHop?.nextAfterCompletion,
    nextHopFallbackAction: trainingState?.latestTrainingNextHop?.fallbackAction,
    routingNextAfterCompletion: trainingState?.activeTrainingCardRouting?.nextAfterCompletion,
    routingFallbackAction: trainingState?.activeTrainingCardRouting?.fallbackAction,
    whyThisCard: trainingState?.activeTrainingCardRouting?.whyThisCard,
    ledgerWhyThisCard: trainingLedgerEntry?.whyThisCard,
    returnSummary: trainingState?.latestTrainingHandoff?.returnSummary,
    nextHopReturnSummary: trainingState?.latestTrainingNextHop?.returnSummary,
    nextHopSummary: trainingState?.latestTrainingNextHop?.summary,
    nextHopWhyNow: trainingState?.latestTrainingNextHop?.whyNow,
  });
  const trainingReturnWithText = leftoverTrainingHandoffChromeNotLive
    ? undefined
    : pickFirstText(
        liveTrainingHandoffChrome.returnWith,
        selectedTrainingCardCandidate?.returnWith,
        selectedTrainingRouteCard?.returnWith,
        trainingState?.latestTrainingHandoff?.returnWith,
      );
  const trainingNextAfterCompletionText = leftoverTrainingHandoffChromeNotLive
    ? undefined
    : pickFirstText(
        liveTrainingHandoffChrome.nextAfterCompletion,
        liveTrainingHandoffChrome.nextHopNextAfterCompletion,
        liveTrainingHandoffChrome.routingNextAfterCompletion,
        selectedTrainingCardCandidate?.nextAfterCompletion,
        selectedTrainingRouteCard?.nextAfterCompletion,
        trainingState?.activeTrainingCardRouting?.nextAfterCompletion,
        trainingState?.latestTrainingHandoff?.nextAfterCompletion,
        trainingState?.latestTrainingNextHop?.nextAfterCompletion,
      );
  const trainingFallbackActionText = leftoverTrainingHandoffChromeNotLive
    ? undefined
    : pickFirstText(
        liveTrainingHandoffChrome.fallbackAction,
        liveTrainingHandoffChrome.nextHopFallbackAction,
        liveTrainingHandoffChrome.routingFallbackAction,
        trainingState?.activeTrainingCardRouting?.fallbackAction,
        trainingState?.latestTrainingHandoff?.fallbackAction,
        trainingState?.latestTrainingNextHop?.fallbackAction,
        selectedTrainingCardCandidate?.stuckRecovery,
        selectedTrainingRouteCard?.stuckRecovery,
      );
  const trainingSuccessSignal = leftoverTrainingHandoffChromeNotLive
    ? undefined
    : pickFirstText(
        liveTrainingHandoffChrome.successSignal,
        trainingState?.latestTrainingHandoff?.successSignal,
        selectedTrainingCardCandidate?.successSignal,
        selectedTrainingRouteCard?.successSignal,
        trainingLedgerEntry?.successSignal,
      );
  const authoritativeDueReviews =
    trainingState?.dueReviews?.length ? trainingState.dueReviews : data.memory.dueReviews;
  const primaryDueReview = authoritativeDueReviews[0];
  const primaryDueReviewTitle = primaryDueReview
    ? reviewConceptLabel(primaryDueReview.concept) ?? t.reviewQueue
    : undefined;
  const trainingReviewItems = useMemo<TrainingReviewItem[]>(
    () =>
      authoritativeDueReviews.slice(0, 4).map((item, index) => ({
        id: `training-review-${index}-${item.concept}`,
        title: reviewConceptLabel(item.concept) ?? t.reviewQueue,
        concept: item.concept,
        focusArea: item.focusArea ?? item.concept,
        taskHint: pickFirstText(item.taskHint, item.reason) ?? item.reason,
        due: item.dueAt,
        fsrs: { intervalDays: item.intervalDays, masteryScore: item.masteryScore },
        detail: pickFirstText(item.taskHint, item.reason),
        meta: joinInlineMeta(
          pickLanguageAlignedTrainingList(layout.composerLanguage, [item.focusArea, item.severity, item.dueAt]),
        ),
      })),
    [authoritativeDueReviews, layout.composerLanguage, t.reviewQueue],
  );
  const trainingStatusMeta = joinInlineMeta([
    trainingCardStatusLabel(effectiveSelectedTrainingCardStatus, layout.composerLanguage),
    trainingHandoffStatusLabel(
      trainingRestoreReplacesSelectedCard
        ? undefined
        : trainingState?.latestTrainingHandoff?.handoffStatus,
      layout.composerLanguage,
    ),
    localizeTrainingNextHopLabel(
      layout.composerLanguage,
      "status",
      trainingRestoreReplacesSelectedCard
        ? undefined
        : trainingState?.latestTrainingNextHop?.status,
    ),
  ]);
  const trainingExecutionState = useMemo(
    () =>
      deriveTrainingExecutionState({
        cardType: trainingCardType,
        trainingSubmode: effectiveTrainingSubmode,
        selectedCardStatus: effectiveSelectedTrainingCardStatus,
        latestTrainingHandoffStatus: reviewArtifactForeground || trainingRestoreReplacesSelectedCard
          ? undefined
          : trainingState?.latestTrainingHandoff?.handoffStatus,
        latestTrainingNextHopStatus: reviewArtifactForeground || trainingRestoreReplacesSelectedCard
          ? undefined
          : trainingState?.latestTrainingNextHop?.status,
        latestTrainingBlockedBy:
          reviewArtifactForeground || trainingRestoreReplacesSelectedCard
            ? undefined
            : (trainingState?.latestTrainingHandoff?.blockedBy ??
              trainingState?.latestTrainingNextHop?.blockedBy),
        latestVerifiedResult: reviewArtifactForeground
          ? undefined
          : (trainingRestoreReplacesSelectedCard
            ? undefined
            : trainingState?.latestLearningVerifiedResult),
        latestLearningBlocker: reviewArtifactForeground
          ? trainingState?.reviewArtifact?.blockedReason
          : (trainingRestoreReplacesSelectedCard
            ? undefined
            : trainingState?.latestLearningBlocker),
        learningPhase: reviewArtifactForeground || trainingRestoreReplacesSelectedCard
          ? selectedTrainingCardCandidate?.learningPhase
          : (trainingState?.latestTrainingHandoff?.learningPhase ??
            selectedTrainingCardCandidate?.learningPhase),
      }),
    [
      trainingCardType,
      effectiveSelectedTrainingCardStatus,
      effectiveTrainingSubmode,
      reviewArtifactForeground,
      trainingRestoreReplacesSelectedCard,
      trainingState?.latestLearningBlocker,
      trainingState?.latestLearningVerifiedResult,
      trainingState?.latestTrainingHandoff?.handoffStatus,
      trainingState?.latestTrainingHandoff?.learningPhase,
      trainingState?.latestTrainingHandoff?.blockedBy,
      selectedTrainingCardCandidate?.learningPhase,
      trainingState?.latestTrainingNextHop?.status,
      trainingState?.latestTrainingNextHop?.blockedBy,
      trainingState?.latestTrainingSubmode,
      trainingState?.reviewArtifact?.blockedReason,
      trainingState?.reviewArtifact?.verifiedResult,
      trainingState?.selectedCardStatus,
    ],
  );
  const normalizedTrainingCardStatus = trainingExecutionState.selectedStatus;
  const normalizedTrainingHandoffStatus = trainingExecutionState.handoffStatus;
  const normalizedTrainingNextHopStatus = trainingExecutionState.nextHopStatus;
  const trainingHandoffReflectionRequired =
    !leftoverTrainingHandoffChromeNotLive &&
    (normalizedTrainingHandoffStatus === "needs_reflection" ||
      normalizedTrainingNextHopStatus === "reflection_required");
  const trainingHandoffReturnRequired =
    !leftoverTrainingHandoffChromeNotLive &&
    (normalizedTrainingHandoffStatus === "ready_to_return" ||
      normalizedTrainingNextHopStatus === "return_required");
  const trainingHandoffId = trainingState?.latestTrainingHandoff?.handoffId?.trim();
  const trainingOutcomeCard: TrainingSummaryCard | undefined = trainingRestoreReplacesSelectedCard
    ? undefined
    : (() => {
    const verifiedResult = pickFirstText(
      trainingState?.latestLearningVerifiedResult,
      activeTrainingReviewArtifact?.verifiedResult,
      activeTrainingCardId && trainingState?.scenarioLab?.id === activeTrainingCardId
        ? trainingState?.scenarioLab?.reviewOutcome : undefined,
    );
    if (verifiedResult) {
      return {
        title: trainingExecutionState.pendingPlanConfirmation
          ? appUiCopy(layout.composerLanguage, "已验证，待计划确认")
          : appUiCopy(layout.composerLanguage, "已验证结果"),
        detail: verifiedResult,
        meta: trainingStatusMeta,
      };
    }

    const blocker = pickFirstText(
      trainingState?.latestLearningBlocker,
      trainingState?.latestTrainingHandoff?.blockedBy,
      trainingState?.latestTrainingNextHop?.statusReason,
      trainingState?.latestTrainingNextHop?.blockedBy,
      activeTrainingReviewArtifact?.blockedReason,
    );
    if (blocker) {
      return {
        title: appUiCopy(layout.composerLanguage, "当前阻塞"),
        detail: blocker,
        meta: trainingStatusMeta,
      };
    }

    const partialProgress = pickFirstText(
      trainingState?.latestLearningPartialProgress,
      activeTrainingReviewArtifact?.partialProgress,
    );
    if (partialProgress) {
      return {
        title: appUiCopy(layout.composerLanguage, "当前进展"),
        detail: partialProgress,
        meta: trainingStatusMeta,
      };
    }

    return undefined;
    })();
  const trainingNextHopCard: TrainingSummaryCard | undefined =
    leftoverTrainingHandoffChromeNotLive ||
    trainingRestoreReplacesSelectedCard ||
    !trainingState?.latestTrainingNextHop
      ? undefined
      : {
          title:
            pickFirstText(
              liveTrainingHandoffChrome.nextHopTitle,
              liveTrainingHandoffChrome.nextHopCardTitle,
              trainingState.latestTrainingNextHop.title,
              trainingState.latestTrainingNextHop.cardTitle,
            ) ??
            localizeTrainingNextHopLabel(layout.composerLanguage, "target_kind", "next_hop") ??
            localizeTrainingNextHopLabel(layout.composerLanguage, "fallback_title"),
          detail: pickFirstText(
            liveTrainingHandoffChrome.nextHopSummary,
            liveTrainingHandoffChrome.nextHopWhyNow,
            liveTrainingHandoffChrome.nextHopReturnSummary,
            liveTrainingHandoffChrome.nextHopNextAfterCompletion,
            liveTrainingHandoffChrome.nextHopHandoffSummary,
            leftoverTrainingHandoffChromeNotLive
              ? undefined
              : trainingState.latestTrainingNextHop.summary,
            leftoverTrainingHandoffChromeNotLive
              ? undefined
              : trainingState.latestTrainingNextHop.whyNow,
            leftoverTrainingHandoffChromeNotLive
              ? undefined
              : trainingState.latestTrainingNextHop.returnSummary,
            leftoverTrainingHandoffChromeNotLive
              ? undefined
              : trainingState.latestTrainingNextHop.nextAfterCompletion,
          ),
          meta: joinInlineMeta([
            localizeTrainingNextHopLabel(
              layout.composerLanguage,
              "status",
              trainingState.latestTrainingNextHop.status,
            ),
            localizeTrainingNextHopLabel(
              layout.composerLanguage,
              "continue_in",
              trainingState.latestTrainingNextHop.continueIn,
            ),
            localizeTrainingNextHopLabel(
              layout.composerLanguage,
              "project_scope",
              trainingState.latestTrainingNextHop.projectScope,
            ),
            trainingState.latestLearningFocusArea,
          ]),
        };
  const practiceExpectedSymbols = trainingExpectedSymbols(
    selectedTrainingCardCandidate?.expectedSymbols,
    selectedTrainingRouteCard?.expectedSymbols,
    trainingLedgerEntry?.expectedSymbols,
  );
  const trainingCardVerified = trainingExecutionState.verified;
  const trainingCardBlocked = trainingExecutionState.blocked;
  const trainingCardSkipped = trainingExecutionState.skipped;
  const trainingNeedsPrimer = trainingExecutionState.needsPrimer;
  const trainingComposerReflectReason = trainingExecutionState.reflectReason;
  const trainingComposerPhase = trainingExecutionState.composerPhase;
  const trainingComposerStudyMode =
    trainingCardType === "practice" && trainingComposerPhase === "learn";
  const leftoverTrainingFocusChromeNotLive = leftoverTrainingFocusChromeIsNotLive(
    leftoverChromeIdentity,
  );
  const liveTrainingFocusChrome = preferRecoveredTrainingFocusChrome({
    ...leftoverChromeIdentity,
    teachingDecisionFocusArea: data.teachingDecision?.focusArea,
    learnerStateActiveFocus: data.learnerState?.activeFocus,
    latestLearningFocusArea: trainingState?.latestLearningFocusArea,
    cardFocusArea: pickFirstText(
      selectedTrainingCardCandidate?.focusArea,
      selectedTrainingRouteCard?.focusArea,
    ),
  });
  const liveTrainingCurrentFocus = leftoverTrainingFocusChromeNotLive
    ? liveTrainingFocus
    : pickFirstText(
        liveTrainingFocusChrome.latestLearningFocusArea,
        liveTrainingFocusChrome.cardFocusArea,
        liveTrainingFocusChrome.teachingDecisionFocusArea,
        liveTrainingFocusChrome.learnerStateActiveFocus,
        liveTrainingFocus,
      );
  const trainingCoachBridge = useMemo(
    () =>
      buildTrainingCoachBridge({
        language: layout.composerLanguage,
        cardId: activeTrainingCardId,
        cardType: trainingCardType === "flash" ? "flash" : "practice",
        taskTitle: visibleTrainingCardTitle ?? liveTrainingTitle,
        focusArea: liveTrainingCurrentFocus,
        cardTitle: visibleTrainingCardTitle,
        learnerDeliverables: trainingDeliverables,
        verificationSteps: authoritativeVerifyItems,
        successSignal: leftoverTrainingHandoffChromeNotLive
          ? undefined
          : ((trainingRestoreReplacesSelectedCard
              ? undefined
              : liveTrainingHandoffChrome.successSignal) ??
            selectedTrainingCardCandidate?.successSignal ??
            selectedTrainingRouteCard?.successSignal),
        returnWith: leftoverTrainingHandoffChromeNotLive
          ? undefined
          : ((trainingRestoreReplacesSelectedCard
              ? undefined
              : liveTrainingHandoffChrome.returnWith) ??
            selectedTrainingCardCandidate?.returnWith ??
            selectedTrainingRouteCard?.returnWith),
        latestVerifiedResult:
          trainingRestoreReplacesSelectedCard
            ? undefined
            : (trainingState?.latestLearningVerifiedResult ?? activeTrainingReviewArtifact?.verifiedResult),
        latestSubmittedResult:
          selectedTrainingCardCandidate?.learnerAnswer ?? selectedTrainingRouteCard?.learnerAnswer,
        reflection:
          !trainingRestoreReplacesSelectedCard &&
          activeTrainingCardId === (
            trainingState?.latestTrainingHandoff?.cardId ??
            trainingState?.latestTrainingHandoff?.candidateId
          )
            ? trainingState?.latestTrainingHandoff?.reflection
            : undefined,
        latestFollowup:
          leftoverTrainingHandoffChromeNotLive || trainingRestoreReplacesSelectedCard
            ? undefined
            : (liveTrainingHandoffChrome.followup ??
              trainingState?.latestLearningFollowup ??
              trainingState?.latestTrainingNextHop?.nextAfterCompletion),
        reviewSummary: trainingRestoreReplacesSelectedCard
          ? undefined
          : activeTrainingReviewArtifact?.summary,
        reviewBlocker:
          leftoverTrainingHandoffChromeNotLive || trainingRestoreReplacesSelectedCard
            ? undefined
            : (liveTrainingHandoffChrome.blocker ??
              trainingState?.latestLearningBlocker ??
              activeTrainingReviewArtifact?.blockedReason),
        reviewPartialProgress:
          trainingRestoreReplacesSelectedCard
            ? undefined
            : (trainingState?.latestLearningPartialProgress ??
              activeTrainingReviewArtifact?.partialProgress),
        reviewRootCause: trainingRestoreReplacesSelectedCard
          ? undefined
          : activeTrainingReviewArtifact?.rootCause,
        reviewNextRule: trainingRestoreReplacesSelectedCard
          ? undefined
          : activeTrainingReviewArtifact?.nextSelfImplementationRule,
        reviewRecommendedActions: trainingRestoreReplacesSelectedCard
          ? undefined
          : activeTrainingReviewArtifact?.recommendedActions,
        reviewStatus:
          trainingCardVerified
            ? "resolved"
            : trainingCardBlocked || activeTrainingReviewArtifact?.status === "active"
              ? "active"
              : activeTrainingReviewArtifact?.status === "archived"
                ? "archived"
                : undefined,
      }),
    [
      activeTrainingCardId,
      activeTrainingReviewArtifact,
      authoritativeVerifyItems,
      leftoverTrainingHandoffChromeNotLive,
      liveTrainingCurrentFocus,
      liveTrainingFocus,
      liveTrainingHandoffChrome.blocker,
      liveTrainingHandoffChrome.followup,
      liveTrainingHandoffChrome.returnWith,
      liveTrainingHandoffChrome.successSignal,
      liveTrainingTitle,
      layout.composerLanguage,
      selectedTrainingCardCandidate?.focusArea,
      selectedTrainingCardCandidate?.learnerAnswer,
      selectedTrainingCardCandidate?.returnWith,
      selectedTrainingCardCandidate?.successSignal,
      selectedTrainingCardCandidate?.title,
      selectedTrainingRouteCard?.focusArea,
      selectedTrainingRouteCard?.learnerAnswer,
      selectedTrainingRouteCard?.returnWith,
      selectedTrainingRouteCard?.successSignal,
      selectedTrainingRouteCard?.title,
      trainingCardBlocked,
      trainingCardType,
      trainingCardVerified,
      trainingDeliverables,
      trainingRestoreReplacesSelectedCard,
      trainingState?.latestLearningBlocker,
      trainingState?.latestLearningFocusArea,
      trainingState?.latestLearningFollowup,
      trainingState?.latestLearningPartialProgress,
      trainingState?.latestLearningVerifiedResult,
      trainingState?.latestTrainingHandoff?.returnWith,
      trainingState?.latestTrainingHandoff?.cardId,
      trainingState?.latestTrainingHandoff?.candidateId,
      trainingState?.latestTrainingHandoff?.reflection,
      trainingState?.latestTrainingHandoff?.successSignal,
      trainingState?.latestTrainingNextHop?.nextAfterCompletion,
      activeTrainingReviewArtifact?.blockedReason,
      activeTrainingReviewArtifact?.nextSelfImplementationRule,
      activeTrainingReviewArtifact?.partialProgress,
      activeTrainingReviewArtifact?.recommendedActions,
      activeTrainingReviewArtifact?.rootCause,
      activeTrainingReviewArtifact?.status,
      activeTrainingReviewArtifact?.summary,
      activeTrainingReviewArtifact?.verifiedResult,
      trainingState?.selectedCardId,
      trainingState?.selectedCardTitle,
      visibleTrainingCardTitle,
    ],
  );
  const selectedTrainingFlashCard =
    trainingCardType === "flash"
      ? (selectedTrainingCardCandidate?.type === "flash"
          ? selectedTrainingCardCandidate
          : selectedTrainingRouteCard?.type === "flash"
            ? selectedTrainingRouteCard
            : undefined)
      : undefined;
  const activeTheoryDrill =
    trainingState?.theoryDrill?.id && trainingState.theoryDrill.id === activeTrainingCardId
      ? trainingState.theoryDrill
      : undefined;
  const flashQuestion = activeTheoryDrill?.questions?.[0];
  const trainingFlashPrompt = pickFirstText(
    selectedTrainingFlashCard?.question,
    flashQuestion?.prompt,
    selectedTrainingFlashCard?.problemStatement,
    selectedTrainingFlashCard?.scenario,
  );
  const trainingTargetSkill = pickFirstText(
    selectedTrainingCardCandidate?.targetSkill,
    selectedTrainingRouteCard?.targetSkill,
    trainingState?.activeTrainingCardRouting?.selectedCard?.targetSkill,
    leftoverTrainingFocusChromeNotLive ? undefined : liveTrainingFocusChrome.cardFocusArea,
  );
  const liveTrainingSkill = liveTrainingTargetSkill({
    ...formalPlanIdentity,
    taskTitle: data.task.title,
    cardSkill: trainingTargetSkill,
    liveFocus: liveTrainingFocus,
  });
  const trainingProblemStatement = pickFirstText(
    trainingCardType === "flash" ? trainingFlashPrompt : undefined,
    selectedTrainingCardCandidate?.problemStatement,
    selectedTrainingRouteCard?.problemStatement,
    trainingState?.activeTrainingCardRouting?.selectedCard?.problemStatement,
    trainingFlashPrompt,
    selectedTrainingCardCandidate?.question,
    selectedTrainingRouteCard?.question,
  );
  const trainingFlashChoices =
    selectedTrainingFlashCard?.choices?.length ? selectedTrainingFlashCard.choices : flashQuestion?.choices;
  const normalizedTrainingFlashChoices = useMemo(
    () =>
      (trainingFlashChoices ?? [])
        .map((choice) => choice.trim())
        .filter((choice): choice is string => Boolean(choice)),
    [trainingFlashChoices],
  );
  const normalizedTrainingFlashChoicesKey = normalizedTrainingFlashChoices.join("\u0000");
  const trainingComposerVerifyItems = authoritativeVerifyItems.slice(0, 4);
  const trainingComposerSelectedVerifyItem =
    trainingComposerVerifyItems[trainingComposerVerifyIndex] ?? trainingComposerVerifyItems[0];
  const hasTrainingCard = leftoverTrainingHandoffChromeNotLive
    ? false
    : Boolean(
        trainingState?.selectedCardId?.trim() &&
          (selectedTrainingCardCandidate || selectedTrainingRouteCard),
      );
  const hasRenderableTrainingCard = leftoverTrainingHandoffChromeNotLive
    ? false
    : hasTrainingCard || Boolean(trainingState?.latestTrainingNextHop);
  const boundTrainingCardFacts = useMemo(() => resolveBoundTrainingCardFacts({
    eligible: hasTrainingCard && syncStatus === "current" &&
      !reviewArtifactForeground && trainingCardType !== "flash",
    activeCardId: activeTrainingCardId,
    candidate: selectedTrainingCardCandidate,
    routeCard: selectedTrainingRouteCard,
  }), [hasTrainingCard, syncStatus, reviewArtifactForeground, trainingCardType,
    activeTrainingCardId, selectedTrainingCardCandidate, selectedTrainingRouteCard]);
  useEffect(() => {
    if (activeView !== "training") {
      return;
    }
    const scenarioLabVisible = Boolean(
      trainingState?.scenarioLab?.id &&
        selectedTrainingCardCandidate?.cardId === trainingState.scenarioLab.id,
    );
    const theoryDrillVisible = Boolean(
      trainingState?.theoryDrill?.id &&
        selectedTrainingCardCandidate?.cardId === trainingState.theoryDrill.id,
    );
    const reviewArtifactVisible = Boolean(
      trainingState?.reviewArtifact?.id &&
        selectedTrainingCardCandidate?.cardId === trainingState.reviewArtifact.id,
    );
    const nextHopVisible = Boolean(
      trainingState?.latestTrainingNextHop &&
        selectedTrainingCardCandidate?.cardId ===
          (trainingState.latestTrainingNextHop.targetId ??
            trainingState.latestTrainingNextHop.candidateId ??
            "next-hop"),
    );
    const restoreKind =
      trainingRestoreContext?.target ??
      (nextHopVisible
        ? "next_hop"
        : scenarioLabVisible
          ? "scenario_lab"
          : theoryDrillVisible
            ? "theory_drill"
            : reviewArtifactVisible
              ? "review_artifact"
              : undefined);
    const activeSubmode =
      effectiveTrainingSubmode ?? (trainingCardType === "flash" ? "flash" : "practice");
    const facts: DebugVisibleTrainingFacts = {
      surface: "training",
      activeView: "training",
      restoreKind,
      surfaceMode: "project",
      activeSubmode,
      visibleTitle: visibleTrainingCardTitle,
      visibleSummary: trainingProblemStatement,
      scenarioLabVisible,
      scenarioLabId: scenarioLabVisible ? trainingState?.scenarioLab?.id : undefined,
      scenarioLabTitle: scenarioLabVisible ? trainingState?.scenarioLab?.title : undefined,
      scenarioLabStatus: scenarioLabVisible ? trainingState?.scenarioLab?.status : undefined,
      scenarioLabScenario: scenarioLabVisible
        ? trainingState?.scenarioLab?.summary
        : undefined,
      theoryDrillVisible,
      theoryDrillId: theoryDrillVisible ? trainingState?.theoryDrill?.id : undefined,
      theoryDrillTitle: theoryDrillVisible ? trainingState?.theoryDrill?.title : undefined,
      theoryDrillStatus: theoryDrillVisible ? trainingState?.theoryDrill?.status : undefined,
      theoryQuestionPrompt: theoryDrillVisible ? trainingState?.theoryDrill?.questions?.[0]?.prompt : undefined,
      reviewArtifactVisible,
      reviewArtifactId: reviewArtifactVisible ? trainingState?.reviewArtifact?.id : undefined,
      reviewArtifactStatus: reviewArtifactVisible ? trainingState?.reviewArtifact?.status : undefined,
      nextHopVisible,
      nextHopTitle: nextHopVisible ? visibleTrainingCardTitle : undefined,
      nextHopStatus: nextHopVisible ? trainingState?.latestTrainingNextHop?.status : undefined,
      nextHopContinueIn: nextHopVisible
        ? trainingState?.latestTrainingNextHop?.continueIn
        : undefined,
      nextHopCandidateType: nextHopVisible
        ? trainingState?.latestTrainingNextHop?.candidateType
        : undefined,
      nextHopTargetKind: nextHopVisible ? trainingState?.latestTrainingNextHop?.targetKind : undefined,
      nextHopTargetId: nextHopVisible ? trainingState?.latestTrainingNextHop?.targetId : undefined,
      nextHopReviewArtifactId: nextHopVisible
        ? trainingState?.latestTrainingNextHop?.reviewArtifactId
        : undefined,
      nextHopPlanEvidenceId: nextHopVisible
        ? trainingState?.latestTrainingNextHop?.planEvidenceId
        : undefined,
      singleCardImmersive: true,
      routeStripCollapsedByDefault: true,
      cardOnlyMode: true,
      secondaryPanelsCollapsedByDefault: true,
    };
    postDebugVisibleFacts({ activeView: "training", training: facts });
  }, [
    activeView,
    selectedTrainingCardCandidate?.cardId,
    selectedTrainingCardCandidate?.title,
    trainingCardType,
    effectiveTrainingSubmode,
    trainingProblemStatement,
    trainingRestoreContext?.target,
    trainingState?.latestTrainingNextHop,
    trainingState?.latestTrainingSubmode,
    trainingState?.reviewArtifact,
    trainingState?.scenarioLab,
    trainingState?.selectedCardTitle,
    trainingState?.theoryDrill,
    visibleTrainingCardTitle,
  ]);
  const trainingComposerEnabled = activeView === "training" && hasTrainingCard;
  const resolvedReviewArtifact = reviewArtifactForeground && trainingState?.reviewArtifact?.status === "resolved";
  const trainingComposerTalkMode = false; // Chat is owned exclusively by Coach.
  const trainingComposerUsesAnswerMode = trainingComposerPhase === "answer";
  const trainingComposerPracticeInputMode =
    trainingCardType === "practice" && trainingComposerPhase === "try";
  const trainingComposerManualPracticeMode =
    trainingComposerPracticeInputMode && trainingPracticeVerificationMode === "manual";
  const trainingComposerFilePracticeMode =
    trainingComposerPracticeInputMode && trainingPracticeVerificationMode === "file";
  const trainingComposerReflectMode = trainingComposerPhase === "reflect";
  const trainingComposerReturnMode = trainingComposerPhase === "return";
  useEffect(() => {
    const pending = pendingTrainingHandoffSubmissionRef.current;
    if (!pending || pending.cardId !== trainingState?.selectedCardId) {
      return;
    }

    const completed =
      pending.phase === "reflect"
        ? trainingHandoffReturnRequired
        : normalizedTrainingNextHopStatus === "continued_in_chat";
    if (!completed) {
      return;
    }

    pendingTrainingHandoffSubmissionRef.current = undefined;
    if (pending.phase === "return") {
      // Draft handoff only: the bridge draft waits in the coach composer
      // (stored per scope). Navigation and focus stay with the learner — the
      // training card shows its own explicit "回到对话" exit.
      setComposerDraft(composeTrainingCoachBridgeDraft(trainingCoachBridge));
      return;
    }

    setActivityDraft("");
  }, [
    normalizedTrainingNextHopStatus,
    setComposerDraft,
    setActivityDraft,
    trainingCoachBridge,
    trainingHandoffReturnRequired,
    trainingState?.selectedCardId,
  ]);
  useEffect(() => {
    setTrainingComposerVerifyIndex(0);
    setTrainingComposerRoute("card");
    setTrainingComposerFlashMode(
      trainingCardType === "flash" && normalizedTrainingFlashChoices.length > 0 ? "choice" : "short",
    );
    setTrainingComposerPracticeReturnMode(
      trainingCardBlocked && !trainingCardVerified ? "blocked" : "result",
    );
  }, [
    normalizedTrainingFlashChoicesKey,
    trainingCardBlocked,
    trainingCardType,
    trainingCardVerified,
    trainingState?.selectedCardId,
  ]);
  const providerConnectionSummary = useMemo(
    () =>
      data.providerConfig.configured
        ? compactDefinedValues(
            [
              data.providerConfig.name || null,
              data.providerConfig.baseUrl || null,
              data.providerConfig.model || null,
              data.providerConfig.apiKeyConfigured ? t.apiKeySaved : t.apiKeyMissing,
            ],
            t.notConfigured,
          )
        : t.notConfigured,
    [
      data.providerConfig.apiKeyConfigured,
      data.providerConfig.baseUrl,
      data.providerConfig.model,
      data.providerConfig.name,
      data.providerConfig.configured,
      t.apiKeySaved,
      t.apiKeyMissing,
      t.notConfigured,
    ],
  );
  const providerStatus = useMemo<SettingsSectionStatus>(() => {
    const copy = providerSettingsLocale(layout.composerLanguage);
    const draftSummary = compactDefinedValues(
      [
        providerDraft.name || null,
        providerDraft.baseUrl || null,
        providerDraft.model || null,
        providerDraftHasUnsavedApiKey ? copy.draftKey : null,
      ],
      data.providerConfig.configured ? providerConnectionSummary : t.notConfigured,
    );
    const feedback =
      buildSettingsFeedback(settingsActionState, operationMessage, layout.composerLanguage, "provider") ??
      (settingsActionState?.kind === "save-provider" && settingsActionState.targets.includes("provider")
        ? {
            tone: "pending" as const,
            ...copy.pending.save,
          }
        : settingsActionState?.kind === "refresh-provider-models" &&
            settingsActionState.targets.includes("provider")
          ? {
              tone: "pending" as const,
              ...copy.pending.refresh,
            }
        : settingsActionState?.kind === "test-provider" && settingsActionState.targets.includes("provider")
          ? {
              actionKind: "test-provider",
              tone: "pending" as const,
              ...copy.pending.test,
            }
          : settingsActionState?.kind === "clear-provider" && settingsActionState.targets.includes("provider")
            ? {
                tone: "pending" as const,
                ...copy.pending.clear,
              }
            : settingsActionState?.kind === "open-config" && settingsActionState.targets.includes("provider")
              ? {
                  tone: "pending" as const,
                  ...copy.pending.open,
                }
              : undefined) ??
      settingsFeedbackState.provider;

    return {
      saveState:
        data.providerConfig.configured || providerDraftHasChanges
          ? providerDraftHasChanges
            ? "unsaved"
            : "saved"
          : "empty",
      effectiveValue: providerConnectionSummary,
      savedValue: data.providerConfig.configured ? providerConnectionSummary : undefined,
      editingValue: providerDraftHasChanges ? draftSummary : undefined,
      note:
        data.providerConfig.configured && providerDraftHasChanges
          ? copy.draftNotApplied
          : providerModelRuntimeNote(data.providerConfig, layout.composerLanguage),
      feedback,
    };
  }, [
    data.providerConfig,
    layout.composerLanguage,
    operationMessage,
    providerConnectionSummary,
    providerDraft,
    providerDraftHasChanges,
    providerDraftHasUnsavedApiKey,
    settingsActionState,
    settingsFeedbackState.provider,
    t.apiKeySaved,
    t.apiKeyMissing,
    t.notConfigured,
  ]);
  const coachDefaultsStatus = useMemo<SettingsSectionStatus>(() => {
    const liveWorkspaceCoachDefaults = leftoverSettingsProfileRhythmNotLive
      ? undefined
      : workspaceSettings?.coachDefaults;
    const formCoachDefaults = leftoverSettingsProfileRhythmNotLive
      ? defaultCoachDefaults
      : layout.coachDefaults;
    const savedCoachDefaults: CoachDefaults = {
      memoryScope: liveWorkspaceCoachDefaults?.memoryScope ?? defaultCoachDefaults.memoryScope,
      workingSetMode: liveWorkspaceCoachDefaults?.workingSetMode ?? defaultCoachDefaults.workingSetMode,
      reviewCadence: liveWorkspaceCoachDefaults?.reviewCadence ?? defaultCoachDefaults.reviewCadence,
      reviewReminderMode:
        liveWorkspaceCoachDefaults?.reviewReminderMode ?? defaultCoachDefaults.reviewReminderMode,
      // Pass the snapshot's skills through — omitting the key would pin the
      // saved side to [] and report "unsaved" forever once a skill exists.
      customSkills: liveWorkspaceCoachDefaults?.customSkills,
      workspaceMemoryToggles: {
        decisions:
          liveWorkspaceCoachDefaults?.workspaceMemoryToggles?.decisions ??
          defaultCoachDefaults.workspaceMemoryToggles.decisions,
        patterns:
          liveWorkspaceCoachDefaults?.workspaceMemoryToggles?.patterns ??
          defaultCoachDefaults.workspaceMemoryToggles.patterns,
        resources:
          liveWorkspaceCoachDefaults?.workspaceMemoryToggles?.resources ??
          defaultCoachDefaults.workspaceMemoryToggles.resources,
        },
    };
    const savedLanguage = workspaceSettings?.responseLanguage ?? layout.composerLanguage;
    const savedAnswerMode = workspaceSettings?.answerMode ?? DEFAULT_ANSWER_MODE;
    const savedTeachingStyle = data.profile.preferredStyle.trim()
      ? normalizeTeachingStyle(data.profile.preferredStyle)
      : layout.teachingStyle;
    const savedValue = leftoverSettingsProfileRhythmNotLive
      ? undefined
      : workspaceSettings
        ? formatSparseCoachDefaultsSavedValue(workspaceSettings, t, savedTeachingStyle)
        : undefined;
    const editingValue = formatCoachDefaultsValue(
      {
        language: layout.composerLanguage,
        answerMode: layout.composerAnswerMode,
        teachingStyle: layout.teachingStyle,
        memoryScope: formCoachDefaults.memoryScope,
        workingSetMode: formCoachDefaults.workingSetMode,
        reviewCadence: formCoachDefaults.reviewCadence,
        reviewReminderMode: formCoachDefaults.reviewReminderMode,
      },
      t,
    );
    const effectiveValue = leftoverSettingsProfileRhythmNotLive
      ? editingValue
      : workspaceSettings
        ? formatCoachDefaultsValue(
            {
              language: workspaceSettings.responseLanguage ?? layout.composerLanguage,
              answerMode: workspaceSettings.answerMode ?? DEFAULT_ANSWER_MODE,
              teachingStyle: savedTeachingStyle,
              memoryScope: savedCoachDefaults.memoryScope,
              workingSetMode: savedCoachDefaults.workingSetMode,
              reviewCadence: savedCoachDefaults.reviewCadence,
              reviewReminderMode: savedCoachDefaults.reviewReminderMode,
            },
            t,
          )
        : editingValue;
    const isSaved =
      !leftoverSettingsProfileRhythmNotLive &&
      (workspaceSettings?.responseLanguage ?? layout.composerLanguage) === layout.composerLanguage &&
      (workspaceSettings?.answerMode ?? DEFAULT_ANSWER_MODE) === layout.composerAnswerMode &&
      savedTeachingStyle === layout.teachingStyle &&
      sameCoachDefaults(savedCoachDefaults, layout.coachDefaults);
    const feedback =
      buildSettingsFeedback(settingsActionState, operationMessage, layout.composerLanguage, "coachDefaults") ??
      (settingsActionState &&
      (settingsActionState.kind === "save-coach" || settingsActionState.kind === "reset-defaults") &&
      settingsActionState.targets.includes("coachDefaults")
        ? {
            tone: "pending" as const,
            title: appUiCopy(
              layout.composerLanguage,
              settingsActionState.kind === "reset-defaults" ? "恢复中" : "保存中",
            ),
            detail:
              appUiCopy(layout.composerLanguage, "正在同步语言、回复方式、教学风格和教练默认策略。"),
          }
        : undefined) ??
      settingsFeedbackState.coachDefaults;

    const coachDefaultsSaveState = leftoverSettingsProfileRhythmNotLive
      ? "empty"
      : workspaceSettings
        ? isSaved
          ? "saved"
          : "unsaved"
        : "empty";
    const noteAnswerMode = coachDefaultsSaveState === "saved" ? savedAnswerMode : layout.composerAnswerMode;
    const noteTeachingStyle = coachDefaultsSaveState === "saved" ? savedTeachingStyle : layout.teachingStyle;

    return {
      saveState: coachDefaultsSaveState,
      effectiveValue,
      savedValue: leftoverSettingsProfileRhythmNotLive
        ? undefined
        : savedValue ??
          formatCoachDefaultsValue(
            {
              language: savedLanguage,
              answerMode: savedAnswerMode,
              teachingStyle: savedTeachingStyle,
              memoryScope: savedCoachDefaults.memoryScope,
              workingSetMode: savedCoachDefaults.workingSetMode,
              reviewCadence: savedCoachDefaults.reviewCadence,
              reviewReminderMode: savedCoachDefaults.reviewReminderMode,
            },
            t,
          ),
      editingValue: isSaved ? undefined : editingValue,
      note: coachDefaultsStatusNote({
        language: layout.composerLanguage,
        saveState: coachDefaultsSaveState,
        answerMode: noteAnswerMode,
        teachingStyle: noteTeachingStyle,
        t,
      }),
      /*
      note:
        appUiCopy(layout.composerLanguage, "这里会一起保存语言、反馈方式、教学风格和教练默认策略。"),
      */
      feedback,
    };
  }, [
    data.profile.preferredStyle,
    defaultCoachDefaults,
    leftoverSettingsProfileRhythmNotLive,
    layout.coachDefaults,
    layout.composerAnswerMode,
    layout.composerLanguage,
    layout.teachingStyle,
    operationMessage,
    settingsActionState,
    settingsFeedbackState.coachDefaults,
    t,
    workspaceSettings,
  ]);
  const workspaceControlStatus = useMemo<SettingsSectionStatus>(() => {
    const savedValue = workspaceSettings ? formatSparseWorkspaceControlValue(workspaceSettings, t) : undefined;
    const effectiveValue = workspaceSettings
      ? formatContextBundleValue(
          {
            followCurrentFile: workspaceSettings.followCurrentFile ?? layout.followCurrentFile,
            contextDetail: workspaceSettings.contextDetail ?? layout.contextDetail,
            includeCurrentFile: workspaceSettings.includeCurrentFile ?? layout.includeCurrentFile,
            includeSelection: workspaceSettings.includeSelection ?? layout.includeSelection,
            includeDiagnostics: workspaceSettings.includeDiagnostics ?? layout.includeDiagnostics,
            includeRelatedFiles: workspaceSettings.includeRelatedFiles ?? layout.includeRelatedFiles,
          },
          t,
        )
      : formatContextBundleValue(
          {
            followCurrentFile: layout.followCurrentFile,
            contextDetail: layout.contextDetail,
            includeCurrentFile: layout.includeCurrentFile,
            includeSelection: layout.includeSelection,
            includeDiagnostics: layout.includeDiagnostics,
            includeRelatedFiles: layout.includeRelatedFiles,
          },
          t,
        );
    const isSaved =
      (workspaceSettings?.followCurrentFile ?? true) === layout.followCurrentFile &&
      (workspaceSettings?.contextDetail ?? "balanced") === layout.contextDetail &&
      (workspaceSettings?.includeCurrentFile ?? true) === layout.includeCurrentFile &&
      (workspaceSettings?.includeSelection ?? true) === layout.includeSelection &&
      (workspaceSettings?.includeDiagnostics ?? true) === layout.includeDiagnostics &&
      (workspaceSettings?.includeRelatedFiles ?? true) === layout.includeRelatedFiles;
    const feedback =
      buildSettingsFeedback(settingsActionState, operationMessage, layout.composerLanguage, "workspaceControl") ??
      (settingsActionState &&
      (settingsActionState.kind === "save-coach" || settingsActionState.kind === "reset-defaults") &&
      settingsActionState.targets.includes("workspaceControl")
        ? {
            tone: "pending" as const,
            title: appUiCopy(
              layout.composerLanguage,
              settingsActionState.kind === "reset-defaults" ? "恢复中" : "保存中",
            ),
            detail:
              appUiCopy(layout.composerLanguage, "正在写入这组工作区上下文控制。"),
          }
        : undefined) ??
      settingsFeedbackState.workspaceControl;

    return {
      saveState: workspaceSettings ? (isSaved ? "saved" : "unsaved") : "empty",
      effectiveValue,
      savedValue: savedValue ?? (appUiCopy(layout.composerLanguage, "工作区未单独覆盖")),
      editingValue: isSaved ? undefined : effectiveValue,
      note:
        appUiCopy(layout.composerLanguage, "这些开关现在就会影响发送，但保存后工作区重开仍会保持。"),
      feedback,
    };
  }, [
    layout.composerLanguage,
    layout.contextDetail,
    layout.followCurrentFile,
    layout.includeCurrentFile,
    layout.includeDiagnostics,
    layout.includeRelatedFiles,
    layout.includeSelection,
    operationMessage,
    settingsActionState,
    settingsFeedbackState.workspaceControl,
    t,
    workspaceSettings,
  ]);

  const sendAnalysis = useMemo(
    () =>
      analyzeSendIntent({
        draft,
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
      draft,
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

  const reportLocalCommand = (message: string) => {
    setOperationMessage({ tone: "success", message });
  };

  const localCommands = useMemo<LocalCommandSuggestion[]>(
    () =>
      buildLocalCommandSuggestions({
        t,
        language: layout.composerLanguage,
        applyView: (view, message) => {
          setActiveView(view);
          reportLocalCommand(message);
        },
        applyLanguage: (language, message) => {
          setComposerLanguage(language);
          reportLocalCommand(message);
        },
        applyAnswerMode: (mode, message) => {
          setComposerAnswerMode(mode);
          reportLocalCommand(message);
        },
        applyContextDetail: (detail, message) => {
          setContextDetail(detail);
          reportLocalCommand(message);
        },
        applyAttachmentPreset: (enabled, message) => {
          setIncludeCurrentFile(enabled);
          setIncludeSelection(enabled);
          setIncludeDiagnostics(enabled);
          setIncludeRelatedFiles(enabled);
          reportLocalCommand(message);
        },
        applySingleAttachment: (key, enabled, message) => {
          if (key === "current_file") {
            setIncludeCurrentFile(enabled);
          } else if (key === "selection") {
            setIncludeSelection(enabled);
          } else if (key === "diagnostics") {
            setIncludeDiagnostics(enabled);
          } else {
            setIncludeRelatedFiles(enabled);
          }
          reportLocalCommand(message);
        },
        applyLiveFollow: (enabled, message) => {
          setFollowCurrentFile(enabled);
          reportLocalCommand(message);
        },
      }),
    [
      layout.composerLanguage,
      setActiveView,
      setComposerLanguage,
      setComposerAnswerMode,
      setContextDetail,
      setIncludeCurrentFile,
      setIncludeSelection,
      setIncludeDiagnostics,
      setIncludeRelatedFiles,
      setFollowCurrentFile,
      t,
    ],
  );

  const localCommandMap = useMemo(
    () => new Map(localCommands.map((command) => [command.id, command])),
    [localCommands],
  );
  const trainerSkillContext = useMemo<TrainerSkillContext>(
    () => ({
      activeView,
      hasActiveFile: Boolean(data.liveContext.activeFile),
      hasSelection: Boolean(data.liveContext.selectionRange),
      relatedFilesCount: data.liveContext.relatedFiles.length,
      resourceCount: data.resources.length,
      subjectFamily: resolveStarterSubjectFamily(data.workspaceTrainingState?.skillProjection),
    }),
    [
      activeView,
      data.liveContext.activeFile,
      data.liveContext.selectionRange,
      data.liveContext.relatedFiles.length,
      data.resources.length,
      data.workspaceTrainingState?.skillProjection,
    ],
  );
  const customSkills = useMemo(
    () => layout.coachDefaults.customSkills ?? [],
    [layout.coachDefaults.customSkills],
  );
  const availableSkillCatalog = useMemo(
    () => mergeSkillCatalog(customSkills),
    [customSkills],
  );
  const matchingLocalSkills = useMemo<LocalSkillSuggestion[]>(() => {
    // Only the first `$token` selects a skill — text after it is arguments
    // handed to the skill on submit. Filtering on the full draft would drop
    // the resolved skill (and falsely offer to re-create it) once the user
    // starts typing arguments.
    const triggerToken = trainerSkillTriggerToken(normalizedDraft);
    if (triggerToken === undefined) {
      return [];
    }

    return filterTrainerSkills(triggerToken, trainerSkillContext, triggerToken === "$" ? 6 : 10, availableSkillCatalog);
  }, [
    normalizedDraft,
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
  const composerUsesTrainingFlow = trainingComposerEnabled && !trainingComposerTalkMode;
  // A missing provider must not destroy a useful draft. Let submission surface the
  // in-place recovery state and keep the learner in the view where they were working.
  const composerSendBlocked = workspaceSessionBlocked;
  const imageAttachmentSendBlocked =
    composerAttachments.length > 0 && !providerImageInputState.supported;
  const imageAttachmentBlockedReason = imageAttachmentSendBlocked
    ? providerImageInputState.detail ??
      providerImageInputState.reason ??
      (appUiCopy(layout.composerLanguage, "当前连接还不能验证图片。"))
    : undefined;
  const showComposerProviderPill = false;
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
    (showComposerBlockingNotice || showComposerProviderPill || showComposerProviderNote);

  const sendTurn = ({
    text,
    intent,
    goals,
    stream = true,
    activeView: activeViewOverride,
    includeCurrentFile,
    includeDiagnostics,
    contextDetail,
    formalPlanMutation,
    planComposerMode,
    planRuntimeRecovery,
    resourceComposerIntent,
    attachments,
  }: {
    text: string;
    intent: "coach" | "next_task" | "review" | "plan" | "task";
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
    attachments?: MessageAttachment[];
  }) => {
    if (workspaceSessionBlocked) {
      openWorkspaceAdmission();
      setOperationMessage({
        tone: "info",
        message: workspaceSessionBlockMessage ?? blockedComposerGuidance,
      });
      return;
    }

    if (!providerCanCoachNow || providerBlockReason || capabilitySendBlocked) {
      useWorkbenchState.getState().requestSettingsCategory("connection");
      setActiveView("settings");
      setOperationMessage({
        tone: "info",
        message: blockedComposerGuidance,
      });
      return;
    }

    const turnActiveView = activeViewOverride ?? activeView;
    const recoveredResume =
      planRuntimeRecovery?.recovered === true && planRuntimeRecovery.formalPlanMutation === false
        ? planRuntimeRecovery
        : undefined;
    const resolvedFormalPlanMutation = recoveredResume ? false : formalPlanMutation;
    // The four workbench views share one real streaming conversation surface.
    // View context and selected resources ground ordinary discussion, while
    // explicit formal-plan mutations need executable tools.
    const requiresVerifiedAgentTools = Boolean(resolvedFormalPlanMutation);
    const laneNeedsVerifiedTools =
      turnActiveView === "resources" ||
      turnActiveView === "plan" ||
      intent === "plan";
    if (requiresVerifiedAgentTools && !providerSupportsFormalPlanTools) {
      setOperationMessage({
        tone: "info",
        message: agentToolsCapabilityMessage,
      });
      return;
    }
    const resourceIds: string[] = resourceComposerIntent
      ? resourceComposerIntent.resourceIds ?? []
      : turnActiveView === "plan"
        ? data.resources.map((resource) => resource.id).filter(Boolean)
        : selectedResourceContextIds.length > 0
          ? selectedResourceContextIds
          : resourceConversationContextIds;
    const resolvedResourceComposerIntent = resourceComposerIntent
      ? {
          ...resourceComposerIntent,
          resourceIds: resourceIds.slice(0, RESOURCE_COMPOSER_MAX_IDS),
        }
      : undefined;
    if (
      resourceComposerIntent &&
      resourceIds.length > RESOURCE_COMPOSER_MAX_IDS
    ) {
      setOperationMessage({
        tone: "info",
        message:
          appUiCopy(layout.composerLanguage, "资源上下文最多带入 12 份，已使用前 12 份。"),
      });
    }
    const resolvedIncludeCurrentFile =
      includeCurrentFile ??
      (layout.includeCurrentFile && shouldAttachCurrentFile(text, intent));
    const effectiveStream = stream;
    const payload = {
      text,
      intent,
      goals,
      resourceIds,
      resourceComposerIntent: resolvedResourceComposerIntent,
      includeCurrentFile: resolvedIncludeCurrentFile,
      includeSelection: layout.includeSelection,
      includeDiagnostics: includeDiagnostics ?? layout.includeDiagnostics,
      includeRelatedFiles: layout.includeRelatedFiles,
      contextDetail: contextDetail ?? layout.contextDetail,
      responseLanguage: layout.composerLanguage,
      answerMode: layout.composerAnswerMode,
      teachingStyle: layout.teachingStyle,
      coachDefaults: layout.coachDefaults,
      activeView: turnActiveView,
      formalPlanMutation: resolvedFormalPlanMutation,
      planComposerMode:
        turnActiveView === "plan" ? planComposerMode ?? resolvedPlanComposerMode : undefined,
      planRuntimeRecovery: recoveredResume,
      attachments: attachments?.length ? attachments : undefined,
      useAgentLoop: requiresVerifiedAgentTools
        ? true
        : laneNeedsVerifiedTools && providerSupportsFormalPlanTools
          ? true
          : undefined,
      requestId: `coach-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    };
    setLastTurnView(turnActiveView);
    streamResumeDraftRef.current = text;
    // Local echo: the user's turn shows up instantly; the server-confirmed
    // copy lands at the same list position when the snapshot merges.
    appendOptimisticTurn(text);

    if (isBrowserPreview) {
      if (stream) {
        void loadBrowserPreviewModule().then((browserPreview) =>
          browserPreview.streamBrowserPreviewMessage(payload, previewSessionId ?? "", {
          onStart: (message) => applyHostMessage(message),
          onChunk: (message) => applyHostMessage(message),
          onComplete: (message, nextSessionId) => {
            setPreviewSessionId(nextSessionId);
            applyHostMessage(message);
          },
          onError: (message) => applyHostMessage(message),
          onCancelled: (message) => applyHostMessage(message),
          }),
        ).catch(() => {
          setOperationMessage({
            tone: "error",
            message: recoverableFailureMessage("send", layout.composerLanguage),
          });
        });
        return;
      }

      void loadBrowserPreviewModule()
        .then((browserPreview) => browserPreview.sendBrowserPreviewMessage(payload, previewSessionId))
        .then(({ sessionId, message }) => {
          setPreviewSessionId(sessionId);
          applyHostMessage(message);
        })
        .catch(() => {
          setOperationMessage({
            tone: "error",
            message: recoverableFailureMessage("send", layout.composerLanguage),
          });
        });
      return;
    }

    postMessage(
      effectiveStream
        ? {
            type: "session/sendStreamMessage",
            payload: {
              ...payload,
              stream: true,
            },
          }
        : {
            type: "session/sendMessage",
            payload,
          },
    );
  };

  sendRecoveredPlanResumeRef.current = (action) => {
    const resume = buildRecoveredPlanResumeTurn(action, {
      recovered: planRuntimeStatus?.recovered === true,
      currentStep: planRuntimeStatus?.currentStep,
      currentStepId: planRuntimeStatus?.currentStageId,
      blockedReason: planRuntimeStatus?.blockedReason,
      whyNow: planRuntimeStatus?.whyNow,
    });
    if (!resume) {
      openPlanComposerMode(action === "clear_blocker" ? "blocker" : "explain");
      return;
    }
    setActiveView("coach");
    requestCoachComposerFocus();
    sendTurn({
      text: recoveredPlanResumeMessage(resume, layout.composerLanguage),
      intent: "plan",
      activeView: "plan",
      stream: true,
      formalPlanMutation: false,
      planComposerMode: action === "clear_blocker" ? "blocker" : "explain",
      planRuntimeRecovery: resume,
    });
  };

  const sendTrainingFeedback = (input: TrainingFeedbackPromptInput) => {
    sendTurn({
      text: buildTrainingFeedbackPrompt(layout.composerLanguage, input),
      intent: "coach",
      activeView: "training",
      stream: true,
      includeCurrentFile: false,
      includeDiagnostics: false,
      contextDetail: "focused",
    });
  };

  const handleBrowserUploads = async (files: File[]) => {
    const importingFolder = browserUploadLooksLikeFolder(files);
    const supportedFiles = files.filter(browserFileSupported);
    const unsupportedCount = files.length - supportedFiles.length;
    try {
      const browserPreview = await loadBrowserPreviewModule();
      const uploadLimit = browserPreview.browserUploadLimit();
      const truncated = supportedFiles.length > uploadLimit;
      const limitedFiles = supportedFiles.slice(0, uploadLimit);
      if (limitedFiles.length === 0) {
        setOperationMessage({
          tone: "error",
          message:
            appUiCopy(layout.composerLanguage, "没有找到可导入的支持文件。"),
        }, "resources");
        return;
      }

      const uploads = await readBrowserFiles(limitedFiles);
      const {
        sessionId,
        patch,
        uploadedCount,
        indexedCount,
        failedIndexCount,
        failedUploadCount,
        truncated: uploadTruncated,
      } = await browserPreview.uploadBrowserPreviewResources(uploads, previewSessionId);
      setPreviewSessionId(sessionId);
      useWorkbenchState.getState().patchData(patch);
      const limitedCount = uploads.length;
      const finalTruncated = truncated || uploadTruncated;
      const skippedText =
        unsupportedCount > 0
          ? appUiCopy(layout.composerLanguage, "跳过 {n} 个不支持的文件。")
              .replace("{n}", String(unsupportedCount))
              .replace("{s}", unsupportedCount === 1 ? "" : "s")
          : "";
      const truncationText = finalTruncated
        ? appUiCopy(layout.composerLanguage, "仅导入前 {n} 个支持文件。")
            .replace("{n}", String(limitedCount))
            .replace("{s}", limitedCount === 1 ? "" : "s")
        : "";
      const indexingText =
        failedIndexCount > 0
          ? appUiCopy(layout.composerLanguage, "其中 {i} 个已完成索引，{f} 个上传成功但索引未完成。")
              .replace("{i}", String(indexedCount))
              .replace("{f}", String(failedIndexCount))
              .replace("{s}", failedIndexCount === 1 ? "" : "s")
          : appUiCopy(layout.composerLanguage, "已完成 {i} 个文件的索引并刷新资料状态。")
              .replace("{i}", String(indexedCount))
              .replace("{s}", indexedCount === 1 ? "" : "s");
      const uploadFailureText =
        failedUploadCount > 0
          ? appUiCopy(layout.composerLanguage, "其中 {n} 个没有导入成功，其他资料已经可以使用。")
              .replace("{n}", String(failedUploadCount))
              .replace("{s}", failedUploadCount === 1 ? "" : "s")
          : "";
      const importedLead = appUiCopy(
        layout.composerLanguage,
        importingFolder ? "已导入文件夹中的资料。" : "已导入资料。",
      );
      const uploadedText = appUiCopy(layout.composerLanguage, "共上传 {n} 个支持文件。")
        .replace("{n}", String(uploadedCount))
        .replace("{s}", uploadedCount === 1 ? "" : "s");
      setOperationMessage({
        tone: failedUploadCount > 0 || failedIndexCount > 0 ? "info" : "success",
        message: [
          importedLead,
          uploadedCount > 0 ? uploadedText : "",
          truncationText,
          skippedText,
          uploadFailureText,
          indexingText,
        ]
          .filter(Boolean)
          .map((fragment) => ` ${fragment}`)
          .join("")
          .trim(),
      }, "resources");
    } catch {
      setOperationMessage({
        tone: "error",
        message: recoverableFailureMessage("upload", layout.composerLanguage),
      }, "resources");
    }
  };

  const handleBrowserUrlImport = async () => {
    if (!isBrowserPreview || browserPreviewFixture) {
      return;
    }

    const rawSource = window.prompt(
      appUiCopy(layout.composerLanguage, "\u7c98\u8d34\u8981\u5bfc\u5165\u7684\u7f51\u9875 URL"),
    )?.trim();
    if (!rawSource) {
      return;
    }

    let parsedUrl: URL;
    try {
      parsedUrl = new URL(rawSource);
      if (parsedUrl.protocol !== "http:" && parsedUrl.protocol !== "https:") {
        throw new Error("unsupported protocol");
      }
    } catch {
      setOperationMessage({
        tone: "error",
        message:
          appUiCopy(layout.composerLanguage, "\u8bf7\u8f93\u5165\u6709\u6548\u7684 http \u6216 https URL\u3002"),
      }, "resources");
      return;
    }

    const pathTitle = parsedUrl.pathname.split("/").filter(Boolean).pop();
    const title = pathTitle || parsedUrl.hostname || rawSource;
    try {
      const browserPreview = await loadBrowserPreviewModule();
      const result = await browserPreview.uploadBrowserPreviewResources(
        [
          {
            name: title,
            kind: "url",
            content: "",
            source: rawSource,
            tags: [],
          },
        ],
        previewSessionId,
      );
      setPreviewSessionId(result.sessionId);
      useWorkbenchState.getState().patchData(result.patch);
      setOperationMessage({
        tone: result.failedIndexCount > 0 || result.failedUploadCount > 0 ? "info" : "success",
        message:
          result.failedIndexCount > 0 || result.failedUploadCount > 0
            ? appUiCopy(layout.composerLanguage, "网页已导入，但索引未完全完成。已上传 {n} 项。").replace(
                "{n}",
                String(result.uploadedCount),
              )
            : appUiCopy(layout.composerLanguage, "网页已导入并完成索引。"),
      }, "resources");
    } catch {
      setOperationMessage({
        tone: "error",
        message: recoverableFailureMessage("upload", layout.composerLanguage),
      }, "resources");
    }
  };

  // ------------------------------------------------------------------ capture
  // In-library "add by URL" rides the same capture pipeline as the browser
  // extension: in a live browser preview the webview can call the sidecar
  // directly; inside VS Code it posts the capture command on the existing
  // webview → host → sidecar message chain.
  const resourceCaptureFocusOptions = useMemo<ResourceCaptureFocusOption[]>(
    () =>
      (data.plan?.stages ?? [])
        .filter((stage) => stage.id.trim() && stage.title.trim())
        .map((stage) => ({ id: stage.id, label: stage.title })),
    [data.plan?.stages],
  );

  const refreshPreviewResources = useCallback(async () => {
    const browserPreview = await loadBrowserPreviewModule();
    const { sessionId, message } = await browserPreview.fetchBrowserPreviewBootstrap(
      previewSessionId,
      true,
    );
    setPreviewSessionId(sessionId);
    applyHostMessage(message);
  }, [applyHostMessage, previewSessionId]);

  /**
   * One correlated wait for a host resource command's `operation/status`.
   * The host answers with `[[trainer-resource-operation:<kind>:<id>]] …`;
   * success resolves, failure rejects with the (already localized) reason,
   * and a quiet window resolves so the caller's own confirmation loop keeps
   * owning honest "unconfirmed" reporting.
   */
  const beginResourceOperationStatusWait = useCallback(
    (kind: "capture" | "organize" | "export", timeoutMs: number) => {
      const requestId = `resource-${kind}-${Date.now().toString(36)}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      const operation = {
        statusMessage: "",
      };
      let timedOut = false;
      const done = new Promise<void>((resolve, reject) => {
        const timeoutId = window.setTimeout(() => {
          timedOut = true;
          resourceOperationResolversRef.current.delete(requestId);
          resolve();
        }, timeoutMs);
        const settle = (settledMessage?: string) => {
          // resolveResourceOperationStatus may have already recorded the status
          // text it settled with; never clobber it with an empty fallback.
          if (settledMessage) {
            operation.statusMessage = settledMessage;
          }
          resourceOperationResolversRef.current.delete(requestId);
          window.clearTimeout(timeoutId);
        };
        resourceOperationResolversRef.current.set(requestId, {
          kind,
          resolve: () => {
            settle();
            resolve();
          },
          reject: (reason) => {
            settle(reason instanceof Error ? reason.message : String(reason ?? ""));
            reject(reason);
          },
          timeoutId,
        });
      });
      const settle = () => {
        const pending = resourceOperationResolversRef.current.get(requestId);
        if (pending?.kind === kind) {
          resourceOperationResolversRef.current.delete(requestId);
          window.clearTimeout(pending.timeoutId);
        }
      };
      // The status text the host settled with (empty when none arrived).
      const statusMessage = (): string => operation.statusMessage;
      // True only when the window expired without a host verdict — callers
      // must not treat that as success evidence for an older record.
      const hasTimedOut = (): boolean => timedOut;
      return { requestId, done, settle, statusMessage, hasTimedOut };
    },
    [],
  );

  const captureResourceIntoLibrary = useCallback(
    async (input: ResourceCaptureInput): Promise<ResourceMutationOutcome> => {
      const url = input.url.trim();
      const title = input.title?.trim() || undefined;
      const download = input.download === true;
      const targetDir = download ? input.targetDir?.trim() || undefined : undefined;
      const clientCaptureId = `library-capture-${Date.now().toString(36)}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      if (isBrowserPreview && !browserPreviewFixture) {
        try {
          const browserPreview = await loadBrowserPreviewModule();
          const baseUrl = await browserPreview.ensureBrowserPreviewSidecar();
          const response = await fetch(`${baseUrl}/resources/capture`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              url,
              kind: captureTargetKind(url),
              ...(title ? { title } : {}),
              ...(input.focusId ? { bind_focus_id: input.focusId } : {}),
              ...(download ? { download: true } : {}),
              ...(targetDir ? { target_dir: targetDir } : {}),
              client_capture_id: clientCaptureId,
              session_id: previewSessionId,
            }),
          });
          if (!response.ok) {
            const detail = await response
              .json()
              .then((body: unknown) => describeSidecarFailure(body))
              .catch(() => "");
            return { ok: false, message: detail || sanitizeErrorSurfaceText(`HTTP ${response.status}`, layout.composerLanguage) };
          }
          const payload = (await response.json()) as {
            name?: unknown;
            resource_id?: unknown;
            deduped?: unknown;
            saved_path?: unknown;
          };
          const name = typeof payload.name === "string" && payload.name.trim()
            ? payload.name.trim()
            : url;
          await refreshPreviewResources().catch(() => undefined);
          return {
            ok: true,
            message: name,
            deduped: payload.deduped === true,
            resourceId: typeof payload.resource_id === "string" ? payload.resource_id : undefined,
            // The capture contract's `saved_path` is only reported when the
            // pipeline actually downloaded the original bytes.
            savedPath:
              typeof payload.saved_path === "string" && payload.saved_path.trim()
                ? payload.saved_path.trim()
                : undefined,
          };
        } catch (error) {
          return {
            ok: false,
            message: error instanceof Error ? error.message : String(error),
          };
        }
      }

      // Inside VS Code the host owns sidecar access: post the capture command
      // and settle through EITHER the correlated operation status (fast,
      // specific failure or success) OR the refreshed library snapshot. A
      // status that names a failure surfaces its reason; a capture that never
      // lands is reported as unconfirmed — never as a silent "added".
      const beforeIds = new Set(
        useWorkbenchState.getState().data.resources.map((resource) => resource.id),
      );
      const captureWait = beginResourceOperationStatusWait(
        "capture",
        CAPTURE_CONFIRMATION_TIMEOUT_MS,
      );
      postMessage({
        type: "command/execute",
        payload: {
          commandId: "trainer.resource.capture",
          payload: {
            url,
            kind: captureTargetKind(url),
            ...(title ? { title } : {}),
            ...(input.focusId ? { bind_focus_id: input.focusId } : {}),
            ...(download ? { download: true } : {}),
            ...(targetDir ? { target_dir: targetDir } : {}),
            client_capture_id: clientCaptureId,
            workspace_id: data.memory.workspace?.workspaceId || undefined,
            __trainerResourceOperationId: captureWait.requestId,
          },
        },
      });
      let landed: Awaited<ReturnType<typeof waitForCapturedResource>>;
      let operationRejected: unknown;
      try {
        landed = await Promise.race([
          waitForCapturedResource(url, beforeIds),
          captureWait.done.then(() => undefined),
        ]);
        captureWait.settle();
        // The host applies the snapshot patch before its success status, but
        // give the record one short extra window to arrive.
        landed ??= await waitForCapturedResource(url, new Set(beforeIds), 10_000);
      } catch (error) {
        captureWait.settle();
        const reason = error instanceof Error ? error.message : String(error);
        return {
          ok: false,
          message: reason.replace("[[trainer-resource-failure]]", "").trim(),
        };
      }
      if (!landed) {
        return { ok: false, unconfirmed: true, message: "" };
      }
      if (landed.deduped) {
        // A pre-existing record for this URL is not evidence that THIS
        // operation finished (T-0010): before treating it as a deduped
        // success, wait for the correlated host verdict. A failure rejects
        // here; a verdict timeout keeps the result unconfirmed instead of
        // dressing an old path up as this download.
        if (!captureWait.hasTimedOut()) {
          try {
            await captureWait.done;
          } catch (error) {
            operationRejected = error;
          }
          if (operationRejected) {
            const reason =
              operationRejected instanceof Error
                ? operationRejected.message
                : String(operationRejected ?? "");
            return {
              ok: false,
              message: reason.replace("[[trainer-resource-failure]]", "").trim(),
            };
          }
          // The remembered download path may have landed with the status
          // patch; re-read the record once for the freshest savedPath.
          const refreshed = await waitForCapturedResource(url, new Set(), 2_000);
          if (refreshed && refreshed.resourceId === landed.resourceId) {
            landed = refreshed;
          }
        }
      }
      return {
        ok: true,
        message: landed.title,
        deduped: landed.deduped,
        resourceId: landed.resourceId,
        savedPath: landed.savedPath,
      };
    },
    [
      beginResourceOperationStatusWait,
      browserPreviewFixture,
      isBrowserPreview,
      postMessage,
      previewSessionId,
      refreshPreviewResources,
    ],
  );

  // ------------------------------------------------------------ library folders
  // One gateway for the folder space: the live preview lane calls the sidecar
  // directly, the VS Code lane posts the command on the existing
  // webview → host → sidecar chain and waits for the correlated
  // `library/folders` answer.
  const requestLibraryFolderOperation = useCallback(
    (commandId: string, payload: Record<string, unknown>): Promise<LibraryFolderHostAnswer> => {
      const operationId = `library-folders-${Date.now().toString(36)}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      return new Promise((resolve) => {
        const timeoutId = window.setTimeout(() => {
          const pending = libraryFolderResolversRef.current.get(operationId);
          if (!pending) {
            return;
          }
          libraryFolderResolversRef.current.delete(operationId);
          resolve({ ok: false, message: "", unconfirmed: true });
        }, LIBRARY_FOLDER_OPERATION_TIMEOUT_MS);
        libraryFolderResolversRef.current.set(operationId, { timeoutId, resolve });
        try {
          postMessage({
            type: "command/execute",
            payload: { commandId, payload: { ...payload, operationId } },
          });
        } catch {
          libraryFolderResolversRef.current.delete(operationId);
          window.clearTimeout(timeoutId);
          resolve({ ok: false, message: "", unconfirmed: true });
        }
      });
    },
    [postMessage],
  );

  const mutatePreviewLibraryFolder = useCallback(
    async (
      method: "POST" | "DELETE",
      endpoint: string,
      body: Record<string, unknown>,
    ): Promise<ResourceMutationOutcome> => {
      try {
        const browserPreview = await loadBrowserPreviewModule();
        const baseUrl = await browserPreview.ensureBrowserPreviewSidecar();
        const response = await fetch(`${baseUrl}${endpoint}`, {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...body, session_id: previewSessionId }),
        });
        if (!response.ok) {
          const detail = await response
            .json()
            .then((payload: unknown) => describeSidecarFailure(payload))
            .catch(() => "");
          return { ok: false, message: detail || sanitizeErrorSurfaceText(`HTTP ${response.status}`, layout.composerLanguage) };
        }
        return { ok: true, message: "" };
      } catch (error) {
        return {
          ok: false,
          message: error instanceof Error ? error.message : String(error),
        };
      }
    },
    [previewSessionId],
  );

  const listLibraryFolders = useCallback(async (): Promise<LibraryFolderListResult> => {
    if (isBrowserPreview && !browserPreviewFixture) {
      try {
        const browserPreview = await loadBrowserPreviewModule();
        const baseUrl = await browserPreview.ensureBrowserPreviewSidecar();
        const response = await fetch(
          `${baseUrl}/library/groups?session_id=${encodeURIComponent(previewSessionId ?? "")}`,
        );
        if (!response.ok) {
          const detail = await response
            .json()
            .then((payload: unknown) => describeSidecarFailure(payload))
            .catch(() => "");
          return { ok: false, folders: [], message: detail || sanitizeErrorSurfaceText(`HTTP ${response.status}`, layout.composerLanguage) };
        }
        const payload = await response.json().catch(() => undefined);
        return { ok: true, folders: parseLibraryFolderTree(payload), message: "" };
      } catch (error) {
        return {
          ok: false,
          folders: [],
          message: error instanceof Error ? error.message : String(error),
        };
      }
    }
    const answer = await requestLibraryFolderOperation("trainer.library.folders.list", {
      workspace_id: data.memory.workspace?.workspaceId || undefined,
    });
    if (answer.unconfirmed) {
      return { ok: false, folders: [], message: "" };
    }
    return {
      ok: answer.ok,
      folders: parseLibraryFolderTree(answer.folders),
      message: answer.message,
    };
  }, [
    browserPreviewFixture,
    data.memory.workspace?.workspaceId,
    isBrowserPreview,
    previewSessionId,
    requestLibraryFolderOperation,
  ]);

  const createLibraryFolder = useCallback(
    async (path: string): Promise<ResourceMutationOutcome> => {
      const folderPath = path.trim();
      if (isBrowserPreview && !browserPreviewFixture) {
        return mutatePreviewLibraryFolder("POST", "/library/groups", { path: folderPath });
      }
      const answer = await requestLibraryFolderOperation("trainer.library.folders.create", {
        path: folderPath,
        workspace_id: data.memory.workspace?.workspaceId || undefined,
      });
      return {
        ok: answer.ok,
        message: answer.message,
        ...(answer.unconfirmed ? { unconfirmed: true } : {}),
      };
    },
    [
      browserPreviewFixture,
      data.memory.workspace?.workspaceId,
      isBrowserPreview,
      mutatePreviewLibraryFolder,
      requestLibraryFolderOperation,
    ],
  );

  const renameLibraryFolder = useCallback(
    async (path: string, nextPath: string): Promise<ResourceMutationOutcome> => {
      const folderPath = path.trim();
      const nextFolderPath = nextPath.trim();
      if (isBrowserPreview && !browserPreviewFixture) {
        return mutatePreviewLibraryFolder("POST", "/library/groups/rename", {
          path: folderPath,
          new_path: nextFolderPath,
        });
      }
      const answer = await requestLibraryFolderOperation("trainer.library.folders.rename", {
        path: folderPath,
        new_path: nextFolderPath,
        workspace_id: data.memory.workspace?.workspaceId || undefined,
      });
      return {
        ok: answer.ok,
        message: answer.message,
        ...(answer.unconfirmed ? { unconfirmed: true } : {}),
      };
    },
    [
      browserPreviewFixture,
      data.memory.workspace?.workspaceId,
      isBrowserPreview,
      mutatePreviewLibraryFolder,
      requestLibraryFolderOperation,
    ],
  );

  const deleteLibraryFolder = useCallback(
    async (path: string): Promise<ResourceMutationOutcome> => {
      const folderPath = path.trim();
      if (isBrowserPreview && !browserPreviewFixture) {
        return mutatePreviewLibraryFolder("DELETE", "/library/groups", { path: folderPath });
      }
      const answer = await requestLibraryFolderOperation("trainer.library.folders.delete", {
        path: folderPath,
        workspace_id: data.memory.workspace?.workspaceId || undefined,
      });
      return {
        ok: answer.ok,
        message: answer.message,
        ...(answer.unconfirmed ? { unconfirmed: true } : {}),
      };
    },
    [
      browserPreviewFixture,
      data.memory.workspace?.workspaceId,
      isBrowserPreview,
      mutatePreviewLibraryFolder,
      requestLibraryFolderOperation,
    ],
  );

  const revealLibraryPath = useCallback(
    (path: string) => {
      // The host's existing reveal action opens any path in the system file
      // manager; no second reveal channel is introduced for downloads.
      postMessage({
        type: "command/execute",
        payload: { commandId: trainerCommands.revealSandboxPath, payload: { path } },
      });
    },
    [postMessage],
  );

  const organizeLibraryResource = useCallback(
    async (
      resourceId: string,
      request: ResourceOrganizeInput,
    ): Promise<ResourceMutationOutcome> => {
      if (isBrowserPreview && !browserPreviewFixture) {
        try {
          const browserPreview = await loadBrowserPreviewModule();
          const baseUrl = await browserPreview.ensureBrowserPreviewSidecar();
          const response = await fetch(`${baseUrl}/resource/organize`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: previewSessionId,
              resource_id: resourceId,
              action: request.action,
              ...(request.title !== undefined ? { title: request.title } : {}),
              ...(request.tags !== undefined ? { tags: request.tags } : {}),
              ...(request.group !== undefined ? { group: request.group } : {}),
            }),
          });
          if (!response.ok) {
            const detail = await response
              .json()
              .then((body: unknown) => describeSidecarFailure(body))
              .catch(() => "");
            return { ok: false, message: detail || sanitizeErrorSurfaceText(`HTTP ${response.status}`, layout.composerLanguage) };
          }
          await refreshPreviewResources().catch(() => undefined);
          return {
            ok: true,
            // The view owns the localized "updated" copy; this lane only
            // reports that the write really happened.
            message: "",
            resourceId,
          };
        } catch (error) {
          return {
            ok: false,
            message: error instanceof Error ? error.message : String(error),
          };
        }
      }

      const before = useWorkbenchState
        .getState()
        .data.resources.find((item) => item.id === resourceId);
      const beforeCollectionPath = (before?.collectionPath ?? "").trim();
      const organizeWait = beginResourceOperationStatusWait(
        "organize",
        ORGANIZE_CONFIRMATION_TIMEOUT_MS,
      );
      postMessage({
        type: "command/execute",
        payload: {
          commandId: "trainer.resource.organize",
          payload: {
            resource_id: resourceId,
            action: request.action,
            ...(request.title !== undefined ? { title: request.title } : {}),
            ...(request.tags !== undefined ? { tags: request.tags } : {}),
            ...(request.group !== undefined ? { group: request.group } : {}),
            workspace_id: data.memory.workspace?.workspaceId || undefined,
            __trainerResourceOperationId: organizeWait.requestId,
          },
        },
      });
      let confirmed: boolean;
      try {
        confirmed = await Promise.race([
          waitForOrganizedResource(resourceId, request, beforeCollectionPath),
          organizeWait.done.then(() => true),
        ]);
        organizeWait.settle();
      } catch (error) {
        organizeWait.settle();
        const reason = error instanceof Error ? error.message : String(error);
        return {
          ok: false,
          message: reason.replace("[[trainer-resource-failure]]", "").trim(),
        };
      }
      if (!confirmed) {
        return { ok: false, unconfirmed: true, message: "" };
      }
      return { ok: true, message: "", resourceId };
    },
    [
      beginResourceOperationStatusWait,
      browserPreviewFixture,
      isBrowserPreview,
      postMessage,
      previewSessionId,
      refreshPreviewResources,
    ],
  );

  const exportLibraryResource = useCallback(
    async (resourceId: string): Promise<ResourceMutationOutcome> => {
      const resource = data.resources.find((item) => item.id === resourceId);
      const name = resource?.title?.trim() || resourceId;
      if (isBrowserPreview && !browserPreviewFixture) {
        try {
          const browserPreview = await loadBrowserPreviewModule();
          const baseUrl = await browserPreview.ensureBrowserPreviewSidecar();
          const response = await fetch(
            `${baseUrl}/resource/export?session_id=${encodeURIComponent(
              previewSessionId ?? "",
            )}&resource_id=${encodeURIComponent(resourceId)}`,
          );
          if (!response.ok) {
            const detail = await response
              .json()
              .then((body: unknown) => describeSidecarFailure(body))
              .catch(() => "");
            return { ok: false, message: detail || sanitizeErrorSurfaceText(`HTTP ${response.status}`, layout.composerLanguage) };
          }
          const blob = await response.blob();
          const downloadName = exportDownloadName(response.headers) ?? name;
          triggerLocalDownload(blob, downloadName);
          return { ok: true, message: downloadName, resourceId };
        } catch (error) {
          return {
            ok: false,
            message: error instanceof Error ? error.message : String(error),
          };
        }
      }

      // Inside VS Code the host owns the OS save flow. The correlated
      // operation status reports the real outcome — the chosen filename on
      // success, the concrete reason on failure; a quiet window keeps the
      // honest "requested" statement.
      const exportWait = beginResourceOperationStatusWait("export", 120_000);
      postMessage({
        type: "command/execute",
        payload: {
          commandId: "trainer.resource.export",
          payload: {
            resource_id: resourceId,
            workspace_id: data.memory.workspace?.workspaceId || undefined,
            __trainerResourceOperationId: exportWait.requestId,
          },
        },
      });
      try {
        await exportWait.done;
        const landedMessage = exportWait.statusMessage()
          .replace("[[trainer-resource-failure]]", "")
          .trim();
        exportWait.settle();
        // The host's status text is the finished sentence (it names the saved
        // file); the reader shows it verbatim instead of re-wrapping it.
        return { ok: true, requested: true, message: landedMessage, resourceId };
      } catch (error) {
        exportWait.settle();
        const reason = error instanceof Error ? error.message : String(error);
        return {
          ok: false,
          message: reason.replace("[[trainer-resource-failure]]", "").trim(),
        };
      }
    },
    [
      beginResourceOperationStatusWait,
      browserPreviewFixture,
      data.resources,
      isBrowserPreview,
      postMessage,
      previewSessionId,
    ],
  );

  const persistCoachSettings = useCallback(
    (overrides?: Partial<{
      responseLanguage: ComposerLanguage;
      answerMode: CoachAnswerMode;
      resourceSearchMode: ResourceSearchMode;
      teachingStyle: TeachingStyle;
      coachDefaults: typeof layout.coachDefaults;
      followCurrentFile: boolean;
      contextDetail: "focused" | "balanced" | "full";
      includeCurrentFile: boolean;
      includeSelection: boolean;
      includeDiagnostics: boolean;
      includeRelatedFiles: boolean;
    }>) => {
      const payload = {
        responseLanguage: overrides?.responseLanguage ?? layout.composerLanguage,
        answerMode: overrides?.answerMode ?? layout.composerAnswerMode,
        resourceSearchMode: overrides?.resourceSearchMode ?? layout.resourceSearchMode,
        teachingStyle: overrides?.teachingStyle ?? layout.teachingStyle,
        coachDefaults: overrides?.coachDefaults ?? layout.coachDefaults,
        followCurrentFile: overrides?.followCurrentFile ?? layout.followCurrentFile,
        contextDetail: overrides?.contextDetail ?? layout.contextDetail,
        includeCurrentFile: overrides?.includeCurrentFile ?? layout.includeCurrentFile,
        includeSelection: overrides?.includeSelection ?? layout.includeSelection,
        includeDiagnostics: overrides?.includeDiagnostics ?? layout.includeDiagnostics,
        includeRelatedFiles: overrides?.includeRelatedFiles ?? layout.includeRelatedFiles,
      };

      // Persisting identical values would only round-trip the sidecar and
      // re-apply a snapshot. Compare against the last server-applied settings
      // snapshot (not the optimistic layout state, which already reflects the
      // pending change) so explicit user changes still save while redundant
      // identical writes are dropped.
      const savedWorkspaceSettings = data.memory.workspace;
      const savedTeachingStyle = data.profile.preferredStyle.trim()
        ? normalizeTeachingStyle(data.profile.preferredStyle)
        : undefined;
      const matchesSavedSettings = Boolean(
        savedWorkspaceSettings &&
          payload.responseLanguage === savedWorkspaceSettings.responseLanguage &&
          payload.answerMode === savedWorkspaceSettings.answerMode &&
          payload.resourceSearchMode === savedWorkspaceSettings.resourceSearchMode &&
          (savedTeachingStyle === undefined || payload.teachingStyle === savedTeachingStyle) &&
          payload.followCurrentFile === savedWorkspaceSettings.followCurrentFile &&
          payload.contextDetail === savedWorkspaceSettings.contextDetail &&
          payload.includeCurrentFile === savedWorkspaceSettings.includeCurrentFile &&
          payload.includeSelection === savedWorkspaceSettings.includeSelection &&
          payload.includeDiagnostics === savedWorkspaceSettings.includeDiagnostics &&
          payload.includeRelatedFiles === savedWorkspaceSettings.includeRelatedFiles &&
          matchesSavedCoachDefaults(payload.coachDefaults, savedWorkspaceSettings.coachDefaults),
      );
      if (matchesSavedSettings) {
        return;
      }

      if (isBrowserPreview) {
        setSettingsActionState({
          kind: "save-coach",
          targets: ["coachDefaults", "workspaceControl"],
          baselineMessageKey: normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
        });
        void loadBrowserPreviewModule()
          .then((browserPreview) =>
            browserPreview.saveBrowserPreviewCoachSettings(payload, previewSessionId),
          )
          .then(({ sessionId, message }) => {
            setPreviewSessionId(sessionId);
            applyHostMessage(message);
            setOperationMessage({
              tone: "success",
              message:
                appUiCopy(payload.responseLanguage, "已保存教练默认设置。"),
            });
          })
          .catch(() => {
            setOperationMessage({
              tone: "error",
              message: recoverableFailureMessage("operation", layout.composerLanguage),
            });
          });
        return;
      }

      setSettingsActionState({
        kind: "save-coach",
        targets: ["coachDefaults", "workspaceControl"],
        baselineMessageKey: normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
      });
      postMessage({
        type: "settings/saveCoach",
        payload,
      });
    },
    [
      applyHostMessage,
      baselineConnectedMessage,
      data.memory.workspace,
      data.profile.preferredStyle,
      isBrowserPreview,
      layout.coachDefaults,
      layout.composerAnswerMode,
      layout.composerLanguage,
      layout.contextDetail,
      layout.followCurrentFile,
      layout.resourceSearchMode,
      layout.teachingStyle,
      layout.includeCurrentFile,
      layout.includeDiagnostics,
      layout.includeRelatedFiles,
      layout.includeSelection,
      operationMessage,
      previewSessionId,
      setSettingsActionState,
      setOperationMessage,
    ],
  );

  // Settings save on change. Preset clicks fan out to several setters in one
  // tick, so the flush is debounced and reads the *latest* persist closure —
  // by then the layout store already holds every pending change.
  const persistCoachSettingsRef = useRef(persistCoachSettings);
  persistCoachSettingsRef.current = persistCoachSettings;
  const coachSettingsAutosaveTimerRef = useRef<number | null>(null);
  const queueCoachSettingsSave = useCallback(() => {
    if (coachSettingsAutosaveTimerRef.current !== null) {
      window.clearTimeout(coachSettingsAutosaveTimerRef.current);
    }
    coachSettingsAutosaveTimerRef.current = window.setTimeout(() => {
      coachSettingsAutosaveTimerRef.current = null;
      persistCoachSettingsRef.current();
    }, COACH_SETTINGS_AUTOSAVE_DELAY_MS);
  }, []);

  useEffect(
    () => () => {
      if (coachSettingsAutosaveTimerRef.current !== null) {
        window.clearTimeout(coachSettingsAutosaveTimerRef.current);
      }
    },
    [],
  );

  const handleSuggestedAction = (
    action: SuggestedAction["action"],
    options?: Pick<SuggestedAction, "prompt" | "focusArea">,
  ) => {
    const prompt = options?.prompt;
    const focusArea = options?.focusArea;
    const reviewOnlyDraft =
      prompt ??
      (appUiCopy(layout.composerLanguage, "先继续当前复习项，不要新开正式任务。"));
    // Suggested actions prefill the composer draft; pressing send stays with
    // the learner. Pure navigation actions keep their navigate-only behavior.
    if (action === "hint") {
      setActiveView("coach");
      setComposerDraft(
        prompt ??
          (appUiCopy(layout.composerLanguage, "请继续给我一个更小、更具体的下一步。")),
      );
      requestCoachComposerFocus();
      return;
    }

    if (action === "plan") {
      setActiveView("plan");
      setComposerDraft(
        prompt ??
          (appUiCopy(layout.composerLanguage, "请先和我讨论这条计划的阶段、证据和验证方式；在我明确生成前不要改正式计划。")),
      );
      return;
    }

    if (action === "next_task") {
      setActiveView("coach");
      if (leftoverSuggestedActionNotLive) {
        setComposerDraft(reviewOnlyDraft);
        requestCoachComposerFocus();
        return;
      }
      setComposerDraft(prompt ?? defaultPromptText("next_task", layout.composerLanguage, focusArea));
      requestCoachComposerFocus();
      return;
    }

    if (action === "review" || action === "retry_review") {
      setActiveView("coach");
      setComposerDraft(prompt ?? defaultPromptText("review", layout.composerLanguage, focusArea));
      requestCoachComposerFocus();
      return;
    }

    setActiveView("coach");
    if (leftoverSuggestedActionNotLive) {
      setComposerDraft(reviewOnlyDraft);
      requestCoachComposerFocus();
      return;
    }
    setComposerDraft(prompt ?? defaultPromptText("task", layout.composerLanguage, focusArea));
    requestCoachComposerFocus();
  };

  const handleSubmit = async (activityResponse?: string) => {
    const normalizedDraft = activityResponse === undefined ? draft.trim() : activityResponse.trim();
    const submissionAttachments = activityResponse === undefined ? composerAttachments : activityAttachments;
    const hasImageAttachments = submissionAttachments.length > 0;
    const allowEmptyTrainingReturnSubmission =
      composerUsesTrainingFlow &&
      trainingComposerReturnMode &&
      trainingHandoffReturnRequired &&
      Boolean(trainingState?.selectedCardId);
    if (!normalizedDraft && !hasImageAttachments && !allowEmptyTrainingReturnSubmission) {
      return;
    }

    if (canCaptureGoalBeforeWorkspaceSetup && normalizedDraft) {
      openWorkspaceAdmission();
      setOperationMessage({
        tone: "info",
        message: t.workspaceAdmissionGoalSaved,
      });
      return;
    }

    if (workspaceSessionBlocked) {
      openWorkspaceAdmission();
      setOperationMessage({
        tone: "info",
        message: workspaceSessionBlockMessage ?? blockedComposerGuidance,
      });
      return;
    }

    if (allowEmptyTrainingReturnSubmission) {
      try {
        await handleSubmitTrainingEvidence("");
      } catch {
        setOperationMessage({
          tone: "error",
          message: trainingPersistenceFailureMessage(layout.composerLanguage),
        });
      }
      return;
    }

    const localCommandDefinition = activityResponse !== undefined || hasImageAttachments
      ? undefined
      : findSidebarControlCommand(normalizedDraft);
    const localCommand = localCommandDefinition
      ? localCommandMap.get(localCommandDefinition.id)
      : undefined;

    if (localCommand) {
      localCommand.run();
      setComposerDraft("");
      return;
    }

    const submittedSkillTrigger = normalizedDraft.split(/\s+/, 1)[0] ?? "";
    const submittedSkill =
      activityResponse === undefined && submittedSkillTrigger.startsWith("$")
        ? availableSkillCatalog.find((skill) =>
            skill.trigger.toLowerCase() === submittedSkillTrigger.toLowerCase() &&
            (!skill.when || skill.when(trainerSkillContext)),
          )
        : undefined;

    if (submittedSkill) {
      const targetView = skillSectionTargetView(submittedSkill.section);
      const followupText = normalizedDraft.slice(submittedSkillTrigger.length).trim();
      const skillPrompt =
        resolveTrainerSkillText(submittedSkill.prompt, layout.composerLanguage) ||
        resolveTrainerSkillText(submittedSkill.detail, layout.composerLanguage) ||
        resolveTrainerSkillText(submittedSkill.title, layout.composerLanguage);
      const formalPlanSkill = submittedSkill.commandId === trainerCommands.generatePlan;

      if (formalPlanSkill && !providerCanMutateFormalPlan) {
        setOperationMessage({
          tone: "info",
          message: formalPlanCapabilityMessage,
        });
        return;
      }

      if (submittedSkill.commandId === trainerCommands.sendStreamMessage) {
        if (!providerCanCoachNow || providerBlockReason) {
          setOperationMessage({
            tone: "info",
            message: blockedComposerGuidance,
          });
          return;
        }

        const skillMessageText = [skillPrompt, followupText].filter(Boolean).join("\n\n");

        setActiveView(targetView);
        sendTurn({
          text: skillMessageText,
          intent: "coach",
          activeView: targetView,
          stream: true,
          attachments: composerAttachments,
        });
      } else if (followupText || hasImageAttachments) {
        if (!providerCanCoachNow || providerBlockReason) {
          setOperationMessage({
            tone: "info",
            message: blockedComposerGuidance,
          });
          return;
        }

        const intent =
          submittedSkill.commandId === trainerCommands.evaluateCurrentFile ||
          submittedSkill.commandId === trainerCommands.evaluateSelection
            ? "review"
            : submittedSkill.commandId === trainerCommands.generatePlan
              ? "plan"
              : submittedSkill.commandId === trainerCommands.nextTask
                ? "next_task"
                : submittedSkill.commandId === trainerCommands.taskSpecify ||
                    submittedSkill.commandId === trainerCommands.trainingGenerateCard ||
                    submittedSkill.section === "Training"
                  ? "task"
                  : submittedSkill.section === "Plan"
                    ? "plan"
                    : "coach";
        const skillMessageText = [skillPrompt, followupText].filter(Boolean).join("\n\n");

        setActiveView(targetView);
        sendTurn({
          text: skillMessageText,
          intent,
          activeView: targetView,
          stream: true,
          formalPlanMutation: formalPlanSkill,
          attachments: composerAttachments,
        });
      } else {
        const isLivePlanTaskMint =
          submittedSkill.commandId === trainerCommands.nextTask ||
          submittedSkill.commandId === trainerCommands.taskSpecify;
        const isGenerateCard = submittedSkill.commandId === trainerCommands.trainingGenerateCard;
        const isPlanUpdate = submittedSkill.commandId === trainerCommands.updatePlan;
        setActiveView(targetView);
        if (isLivePlanTaskMint || isGenerateCard || isPlanUpdate) {
          pendingLivePlanTaskMintRef.current = { commandId: submittedSkill.commandId };
          setOperationMessage({
            tone: "info",
            message: isGenerateCard
              ? trainingGenerateCardPendingMessage(layout.composerLanguage)
              : isPlanUpdate
                ? livePlanUpdatePendingMessage(layout.composerLanguage)
                : livePlanTaskMintPendingMessage(layout.composerLanguage),
          });
        }
        postMessage({
          type: "command/execute",
          payload: {
            commandId: submittedSkill.commandId,
            payload: submittedSkill.payload,
          },
        });
        if (isLivePlanTaskMint || isGenerateCard || isPlanUpdate) {
          // Keep draft until authoritative success/failure ack (intent→pending→ack).
          return;
        }
      }

      setComposerDraft("");
      setComposerAttachments([]);
      setDismissedComposerDeck(undefined);
      return;
    }

    if (composerUsesTrainingFlow) {
      if (trainingPersistencePending) {
        return;
      }

      const trainingCardCommand = interpretTrainingComposerCardCommand(normalizedDraft);
      const trainingCardTransition = leftoverTrainingHandoffChromeNotLive
        ? undefined
        : handleTrainingCardStatusTransition;
      const appliedTrainingCardCommand =
        trainingCardCommand?.kind === "skip"
          ? applyTrainingCardSkip(
              trainingCardTransition,
              activeTrainingCardId,
              layout.composerLanguage,
            )
          : trainingCardCommand?.kind === "grade" && !trainingComposerUsesAnswerMode
            ? applyTrainingCardGrade(
                trainingCardTransition,
                activeTrainingCardId,
                layout.composerLanguage,
                trainingCardCommand.grade,
              )
            : false;
      if (appliedTrainingCardCommand) {
        setActivityDraft("");
        setActivityAttachments([]);
        return;
      }

      if (hasImageAttachments) {
        if (!providerCanCoachNow || providerBlockReason) {
          setOperationMessage({
            tone: "info",
            message: blockedComposerGuidance,
          });
          return;
        }

        if (!providerImageInputState.supported) {
          setOperationMessage({
            tone: "info",
            message:
              providerImageInputState.detail ??
              providerImageInputState.reason ??
              (appUiCopy(layout.composerLanguage, "当前连接还不能验证图片。")),
          });
          return;
        }

        sendTurn({
          text: buildScratchPaperVerificationPrompt(layout.composerLanguage, {
            cardTitle: visibleTrainingCardTitle ?? liveTrainingTitle,
            learnerNote: normalizedDraft,
            verificationItems: authoritativeVerifyItems,
          }),
          intent: "review",
          activeView: "training",
          stream: true,
          includeCurrentFile: false,
          includeDiagnostics: false,
          contextDetail: "focused",
          attachments: submissionAttachments,
        });
        setActivityDraft("");
        setActivityAttachments([]);
        return;
      }

      if (
        (!trainingComposerReflectMode && !trainingComposerReturnMode) &&
        (!providerCanCoachNow || providerBlockReason)
      ) {
        setOperationMessage({
          tone: "info",
          message: blockedComposerGuidance,
        });
        return;
      }

      if (trainingComposerUsesAnswerMode) {
        const normalizedAnswer = normalizedDraft;
        const selectedOptionIndex =
          trainingComposerFlashMode === "choice"
            ? normalizedTrainingFlashChoices.findIndex(
                (choice) =>
                  normalizeInlineComparisonText(choice) === normalizeInlineComparisonText(normalizedAnswer),
              )
            : -1;
        try {
          await requestTrainingPersistence(
            activeTheoryDrill?.id
              ? trainerCommands.trainingTheoryDrillAnswer
              : trainerCommands.trainingFlashcardAnswer,
            activeTheoryDrill?.id
              ? {
                  theoryDrillId: activeTheoryDrill.id,
                  questionId: flashQuestion?.id,
                  learnerAnswer: normalizedAnswer,
                  selectedOptionIndex: selectedOptionIndex >= 0 ? selectedOptionIndex : undefined,
                }
              : {
                  cardId: activeTrainingCardId,
                  learnerAnswer: normalizedAnswer,
                  selectedOptionIndex: selectedOptionIndex >= 0 ? selectedOptionIndex : undefined,
                },
          );
        } catch {
          setOperationMessage({
            tone: "error",
            message: trainingPersistenceFailureMessage(layout.composerLanguage),
          });
          return;
        }
        sendTrainingFeedback({
          phase: "answer",
          cardTitle: visibleTrainingCardTitle ?? liveTrainingTitle,
          question: flashQuestion?.prompt ?? trainingFlashPrompt ?? trainingProblemStatement,
          learnerAnswer: normalizedAnswer,
          evidenceItems: authoritativeVerifyItems,
        });
        setActivityDraft("");
      } else {
        let shouldStartFeedback = false;
        try {
          shouldStartFeedback = await handleSubmitTrainingEvidence(normalizedDraft);
        } catch {
          setOperationMessage({
            tone: "error",
            message: trainingPersistenceFailureMessage(layout.composerLanguage),
          });
          return;
        }
        if (!shouldStartFeedback) {
          return;
        }
        sendTrainingFeedback({
          phase: trainingComposerReflectMode ? "reflection" : "evidence",
          cardTitle: visibleTrainingCardTitle ?? liveTrainingTitle,
          question: reviewArtifactForeground
            ? trainingState?.reviewArtifact?.summary
            : trainingComposerSelectedVerifyItem ?? trainingProblemStatement,
          learnerAnswer: normalizedDraft,
          evidenceItems: reviewArtifactForeground
            ? selectedTrainingCardCandidate?.verificationSteps ?? []
            : authoritativeVerifyItems,
        });
        setActivityDraft("");
      }
      return;
    }

    const waitingComposerEvidence =
      (activeView === "plan" || coachPlanContext !== undefined) &&
      (coachPlanContext ?? resolvedPlanComposerMode) === "evidence" &&
      recoveredRuntime &&
      planRuntimeStatus?.resumeState === "waiting" &&
      Boolean(planRuntimeStatus?.currentStep?.trim()) &&
      liveEvidenceQueue.pending.length === 0;
    if (waitingComposerEvidence) {
      const submitted = normalizedDraft.trim();
      if (!submitted || trainingPersistencePending) {
        return;
      }
      try {
        await requestTrainingPersistence(trainerCommands.evidenceEnqueue, {
          waitingComposer: true,
          summary: submitted,
        });
      } catch (error) {
        setOperationMessage({
          tone: "error",
          message: waitingComposerEnqueueFailureText(error, layout.composerLanguage),
        });
        return;
      }
      setComposerDraft("");
      setComposerAttachments([]);
      return;
    }

    if (!providerCanCoachNow || providerBlockReason) {
      setOperationMessage({
        tone: "info",
        message: blockedComposerGuidance,
      });
      return;
    }

    const dockSendPreference = normalizeDockSendPreference(layout.composerSendPreference);
    const dockAnchor = activeView === "coach" ? null : resolveDockContextAnchor(
      activeView,
      {
        stageTitle: activePlanStage?.title,
        stageProgress: dockStageProgressLabel,
        resourceLabel: selectedResourceNavigationLabel,
      },
      dockAnchorControl.suppressed,
    );
    const analyzedIntent =
      sendAnalysis.intent === "coach" ||
      sendAnalysis.intent === "next_task" ||
      sendAnalysis.intent === "review" ||
      sendAnalysis.intent === "plan" ||
      sendAnalysis.intent === "task"
        ? sendAnalysis.intent
        : "coach";
    const planComposerSubmission = activeView === "plan" || coachPlanContext !== undefined;
    const submittedPlanMode = coachPlanContext ?? resolvedPlanComposerMode;
    const formalPlanGeneration =
      (planComposerSubmission && submittedPlanMode === "generate") ||
      (activeView === "coach" && sendAnalysis.intent === "plan");
    const previewPlanCandidateGeneration =
      formalPlanGeneration && isBrowserPreview && Boolean(window.__TRAINER_BOOTSTRAP__);
    if (formalPlanGeneration && !previewPlanCandidateGeneration && !providerCanMutateFormalPlan) {
      setOperationMessage({
        tone: "info",
        message: formalPlanCapabilityMessage,
      });
      return;
    }
    if (formalPlanGeneration && !previewPlanCandidateGeneration && !capabilityVerdict.formalPlan) {
      setOperationMessage({
        tone: "info",
        message: formalPlanCapabilityMessage,
      });
      return;
    }
    const intent = formalPlanGeneration ? "plan" : analyzedIntent;
    const rawMessageText =
      sendAnalysis.draftBody ||
      (hasImageAttachments
        ? buildGenericImageReviewPrompt(layout.composerLanguage, normalizedDraft)
        : defaultPromptText(intent, layout.composerLanguage));
    const messageText = appendDockAnchor(rawMessageText, dockAnchor);

    sendTurn({
      text: messageText,
      intent,
      goals: formalPlanGeneration ? data.profile.goals : undefined,
      activeView: planComposerSubmission ? "plan" : activeView,
      stream: true,
      formalPlanMutation: formalPlanGeneration && !previewPlanCandidateGeneration,
      planComposerMode: planComposerSubmission ? submittedPlanMode : undefined,
      resourceComposerIntent:
        activeView === "resources"
          ? {
              mode: resourcesComposerMode,
              resourceIds: selectedResourceContextIds,
            }
          : undefined,
      includeDiagnostics: intent === "review" ? true : undefined,
      contextDetail: intent === "review" ? "full" : undefined,
      attachments: composerAttachments,
    });
    if (activeView === "plan" || activeView === "resources") {
      if (dockSendNavigation(dockSendPreference, activeView) === "jump_to_coach") {
        setActiveView("coach");
      } else {
        // §3.7 red line 5: the store raises the returnToSurface notice when
        // this send's stream completes — even when every stream message lands
        // in one synchronous batch (fixture streams, fast real streams).
        markDockStaySend(activeView);
      }
    }
    setComposerDraft("");
    setComposerAttachments([]);
    setCoachPlanContext(undefined);
  };

  // Re-arm the bootstrap request guard only on the false -> true transition of
  // host-state reception. In browser preview `hasReceivedHostState` starts
  // true, so an unconditional reset here disarmed the guard on mount and every
  // subsequent `requestBootstrapOnce` call re-posted `request/bootstrap`,
  // driving a continuous POST /memory/settings + GET /memory/summary loop.
  const hostStateReceivedOnceRef = useRef(hasReceivedHostState);
  useEffect(() => {
    if (!hasReceivedHostState) {
      return;
    }
    if (hostStateReceivedOnceRef.current) {
      return;
    }
    hostStateReceivedOnceRef.current = true;
    resetBootstrapRequestSent();
  }, [hasReceivedHostState]);

  useEffect(() => {
    if (!showComposerShell || !coachComposerFocusRequestRef.current) {
      return;
    }
    coachComposerFocusRequestRef.current = false;
    const handle = window.requestAnimationFrame(() => {
      focusComposerInput();
    });

    return () => window.cancelAnimationFrame(handle);
  }, [activeView, hasReceivedHostState, showComposerShell]);

  const runComposerCommand = (command: LocalCommandSuggestion) => {
    command.run();
    setComposerDraft("");
    setOpenMenu(undefined);
    window.requestAnimationFrame(() => {
      focusComposerInput();
    });
  };

  const openComposerModelSettings = useCallback(() => {
    setOpenMenu(undefined);
    setComposerModelQuery("");
    useWorkbenchState.getState().requestSettingsCategory("connection");
    setActiveView("settings");
  }, [setActiveView]);

  const toggleComposerModelMenu = useCallback(() => {
    if (!data.providerConfig.configured && !composerHasSavedProfiles) {
      openComposerModelSettings();
      return;
    }

    setOpenMenu((current) => (current === "model" ? undefined : "model"));
  }, [composerHasSavedProfiles, data.providerConfig.configured, openComposerModelSettings]);

  const refreshComposerProviderModels = useCallback(() => {
    if (!data.providerConfig.configured) {
      setOperationMessage({
        tone: "info",
        message:
          appUiCopy(layout.composerLanguage, "先保存连接，再更新模型列表。"),
      });
      return;
    }

    if (!data.providerConfig.apiKeyConfigured) {
      setOperationMessage({
        tone: "info",
        message:
          appUiCopy(layout.composerLanguage, "先填写访问密钥，再更新模型列表。"),
      });
      return;
    }

    if (isBrowserPreview) {
      void loadBrowserPreviewModule()
        .then((browserPreview) =>
          browserPreview.refreshBrowserPreviewProviderModels(previewSessionId),
        )
        .then(({ sessionId, messages }) => {
          setPreviewSessionId(sessionId);
          applyPreviewHostMessages(messages, true);
        })
        .catch(() => {
          setOperationMessage({
            tone: "error",
            message: recoverableFailureMessage("provider", layout.composerLanguage),
          });
        });
      return;
    }

    postMessage({
      type: "command/execute",
      payload: {
        commandId: trainerCommands.refreshProviderModels,
      },
    });
  }, [
    applyPreviewHostMessages,
    data.providerConfig.apiKeyConfigured,
    data.providerConfig.configured,
    isBrowserPreview,
    layout.composerLanguage,
    previewSessionId,
    setOperationMessage,
  ]);

  const {
    coachSessions,
    coachSessionsStatus,
    coachSessionsMessage,
    applySessionList,
    requestCoachSessions,
    toggleComposerHistoryMenu,
    activateCoachSession,
    startNewCoachChat,
  } = useCoachHistory({
    isBrowserPreview,
    composerLanguage: layout.composerLanguage,
    previewSessionId,
    conversationCount: data.conversation.length,
    cacheScope: data.workspaceName,
    setOpenMenu,
    setOperationMessage,
  });

  const setComposerThinking = useCallback(
    (thinking: ProviderThinkingConfig) => {
      if (isBrowserPreview) {
        setOperationMessage({
          tone: "info",
          message:
            appUiCopy(layout.composerLanguage, "预览模式不会保存思考强度。"),
        });
        return;
      }
      postMessage({
        type: "command/execute",
        payload: {
          commandId: trainerCommands.setProviderThinking,
          payload: { thinking },
        },
      });
    },
    [isBrowserPreview, layout.composerLanguage, setOperationMessage],
  );

  const switchComposerProviderProfile = useCallback((profileId: string) => {
    setOpenMenu(undefined);
    setComposerModelQuery("");

    if (isBrowserPreview) {
      void loadBrowserPreviewModule()
        .then((browserPreview) =>
          browserPreview.switchBrowserPreviewProviderProfile(profileId, previewSessionId),
        )
        .then(({ sessionId, messages }) => {
          setPreviewSessionId(sessionId);
          applyPreviewHostMessages(messages, true);
        })
        .catch(() => {
          setOperationMessage({
            tone: "error",
            message: recoverableFailureMessage("provider", layout.composerLanguage),
          });
        });
      return;
    }

    postMessage({
      type: "command/execute",
      payload: {
        commandId: trainerCommands.switchProviderProfile,
        payload: {
          profileId,
          reason: "composer_switch",
        },
      },
    });
  }, [applyPreviewHostMessages, isBrowserPreview, layout.composerLanguage, previewSessionId, setOperationMessage]);

  const switchComposerProviderModel = useCallback((model: string) => {
    const modelPolicy = evaluateProviderModelPolicy(model, {
      allowedModels: data.providerConfig.allowedModels,
      deniedModels: data.providerConfig.deniedModels,
    });
    if (!modelPolicy.allowed) {
      setOperationMessage({
        tone: "info",
        message:
          composerModelPolicyHint(layout.composerLanguage, modelPolicy.reason) ??
          (appUiCopy(layout.composerLanguage, "\u8bf7\u5148\u9009\u62e9\u4e00\u4e2a\u53ef\u4ee5\u4f7f\u7528\u7684\u6a21\u578b\u3002")),
      });
      return;
    }

    setOpenMenu(undefined);
    setComposerModelQuery("");

    if (isBrowserPreview) {
      void loadBrowserPreviewModule()
        .then((browserPreview) =>
          browserPreview.switchBrowserPreviewProviderModel(modelPolicy.model, previewSessionId),
        )
        .then(({ sessionId, messages }) => {
          setPreviewSessionId(sessionId);
          applyPreviewHostMessages(messages, true);
        })
        .catch(() => {
          setOperationMessage({
            tone: "error",
            message: recoverableFailureMessage("provider", layout.composerLanguage),
          });
        });
      return;
    }

    postMessage({
      type: "command/execute",
      payload: {
        commandId: trainerCommands.switchProviderModel,
        payload: {
          model: modelPolicy.model,
          reason: "composer_model_switch",
        },
      },
    });
  }, [
    applyPreviewHostMessages,
    data.providerConfig.allowedModels,
    data.providerConfig.deniedModels,
    isBrowserPreview,
    layout.composerLanguage,
    previewSessionId,
    setOperationMessage,
  ]);

  // Phase-D training attempt lifecycle: entering a formal card starts/resumes
  // an attempt; the Try draft is throttled into attempt updates; hints bump
  // the assistance level; return closes the lifecycle. Identity fields are
  // derived server-side from the persisted attempt.
  // Rules of Hooks: call the hook at top level. It returns a stable identity
  // (internal useMemo), so the dependent effects below do not re-fire per render.
  const attemptLifecycle = useTrainingAttemptLifecycle();
  // The start/recover effect reads the active file as a snapshot only; keeping
  // it in a ref avoids making a file switch restart the attempt.
  const attemptStartFilePathRef = useRef<string | undefined>(data.liveContext?.activeFile);
  attemptStartFilePathRef.current = data.liveContext?.activeFile;

  // When a formal training card becomes active, start or resume its attempt.
  useEffect(() => {
    if (activeView !== "training" || !activeTrainingCardId || isBrowserPreview || trainingComposerReturnMode || reviewArtifactForeground) {
      return;
    }
    attemptLifecycle.startOrRecover(activeTrainingCardId, {
      filePath: attemptStartFilePathRef.current ?? undefined,
    });
  }, [activeView, activeTrainingCardId, attemptLifecycle, isBrowserPreview, trainingComposerReturnMode, reviewArtifactForeground]);

  const handleHintReveal = useCallback(
    (hintLevel: number) => {
      if (!activeTrainingCardId || isBrowserPreview) {
        return;
      }
      const clamped = Math.min(3, Math.max(1, hintLevel));
      attemptLifecycle.updateAssistance(activeTrainingCardId, `hint_level_${clamped}`);
    },
    [activeTrainingCardId, attemptLifecycle, isBrowserPreview],
  );

  const checkRemoteRunnerBoundary = useCallback((): string | null => {
    // TR-100: remote workspace without a runner must not silently verify.
    const wsRoot = data.memory.workspace?.workspaceId ?? "";
    if (!wsRoot) return null;
    // VS Code remote workspaces use vscode-remote:// or ssh:// URI schemes.
    const isRemote = wsRoot.startsWith("vscode-remote://") || wsRoot.startsWith("ssh://");
    if (!isRemote) return null;
    return "Remote workspace detected but no remote verification runner is available. Trainer will not run local checks against a remote project.";
  }, [data.memory.workspace?.workspaceId]);

  const handleVerifyTrainingFromIde = useCallback(() => {
    const boundaryNotice = checkRemoteRunnerBoundary();
    if (boundaryNotice) {
      // The card owns this notice; the surface is no longer pre-set — the
      // following verify failure carries the training marker and scopes itself.
      setTrainingVerifyNotice(boundaryNotice);
      return;
    }
    if (isBrowserPreview || leftoverTrainingHandoffChromeNotLive || !activeTrainingCardId) {
      const notice = leftoverTrainingHandoffChromeNotLive
        ? appUiCopy(layout.composerLanguage, "验证未通过：当前训练卡片不是实时状态。")
        : !activeTrainingCardId
          ? appUiCopy(layout.composerLanguage, "没有可验证的当前文件。")
          : appUiCopy(layout.composerLanguage, "预览不能验真实工作区文件。请回 VS Code 打开文件后再验证。");
      setTrainingVerifyNotice(notice);
      return;
    }
    postMessage({
      type: "command/execute",
      payload: {
        commandId: trainerCommands.evaluateCurrentFile,
        payload: {
          source: "training",
          cardId: activeTrainingCardId,
          cardTitle: readTrainingCardText(boundTrainingCardFacts, "title", () => visibleTrainingCardTitle),
          acceptanceCriteria: boundTrainingCardFacts
            ? boundTrainingCardFacts.lists.acceptanceCriteria ?? boundTrainingCardFacts.lists.verificationSteps ?? []
            : selectedTrainingCardCandidate?.acceptanceCriteria?.length
              ? selectedTrainingCardCandidate.acceptanceCriteria
              : selectedTrainingRouteCard?.acceptanceCriteria?.length
                ? selectedTrainingRouteCard.acceptanceCriteria
                : authoritativeVerifyItems,
          learnerDeliverables: readTrainingCardList(boundTrainingCardFacts, "learnerDeliverables", () => trainingDeliverables),
          expectedSymbols: trainingCardType === "practice" ? readTrainingCardList(boundTrainingCardFacts, "expectedSymbols", () => practiceExpectedSymbols) : [],
          filesToTouch: readTrainingCardList(boundTrainingCardFacts, "filesToTouch", () => trainingFilesToTouch),
        },
      },
    });
  }, [
    leftoverTrainingHandoffChromeNotLive,
    activeTrainingCardId,
    boundTrainingCardFacts,
    authoritativeVerifyItems,
    selectedTrainingCardCandidate?.acceptanceCriteria,
    selectedTrainingRouteCard?.acceptanceCriteria,
    isBrowserPreview,
    layout.composerLanguage,
    trainingFilesToTouch,
    practiceExpectedSymbols,
    setOperationMessage,
    trainingCardType,
    trainingDeliverables,
    visibleTrainingCardTitle,
  ]);

  const handleSubmitTrainingEvidence = useCallback(async (evidence: string): Promise<boolean> => {
    if (leftoverTrainingHandoffChromeNotLive) {
      return false;
    }
    const normalizedEvidence = evidence.trim();
    if (reviewArtifactForeground && trainingState?.reviewArtifact?.id) {
      if (!normalizedEvidence) {
        return false;
      }
      await requestTrainingPersistence(trainerCommands.trainingReviewArtifactAction, {
        reviewArtifactId: trainingState.reviewArtifact.id,
        action: "resolved",
        note: normalizedEvidence,
      });
      return true;
    }
    const shouldSubmitTrainingHandoffReturn =
      trainingComposerReturnMode &&
      trainingHandoffReturnRequired &&
      Boolean(activeTrainingCardId);
    if (shouldSubmitTrainingHandoffReturn && activeTrainingCardId) {
      pendingTrainingHandoffSubmissionRef.current = {
        phase: "return",
        cardId: activeTrainingCardId,
      };
      try {
        await requestTrainingPersistence(trainerCommands.trainingReturn, {
          cardId: activeTrainingCardId,
          handoffId: trainingHandoffId ?? "",
        });
      } catch (error) {
        pendingTrainingHandoffSubmissionRef.current = undefined;
        throw error;
      }
      return false;
    }

    if (!normalizedEvidence) {
      return false;
    }

    const practiceResultMode = trainingComposerPracticeReturnMode === "result";
    const practiceBlockedMode = trainingComposerPracticeReturnMode === "blocked";

    const shouldSubmitTrainingHandoffReflection =
      trainingComposerReflectMode &&
      trainingHandoffReflectionRequired &&
      Boolean(activeTrainingCardId);
    if (shouldSubmitTrainingHandoffReflection && activeTrainingCardId) {
      pendingTrainingHandoffSubmissionRef.current = {
        phase: "reflect",
        cardId: activeTrainingCardId,
      };
      try {
        await requestTrainingPersistence(trainerCommands.trainingReflect, {
          cardId: activeTrainingCardId,
          handoffId: trainingHandoffId ?? "",
          reflection: normalizedEvidence,
        });
      } catch (error) {
        pendingTrainingHandoffSubmissionRef.current = undefined;
        throw error;
      }
      return false;
    }

    if (trainingComposerStudyMode && activeTrainingCardId) {
      await requestTrainingPersistence(trainerCommands.trainingCardStatusTransition, {
        cardId: activeTrainingCardId,
        newStatus: "active",
        reason: "study_note_submitted",
      });
    }

    const shouldReviewAnsweredFlash =
      trainingComposerReflectMode &&
      trainingComposerReflectReason === "flash_answered" &&
      activeTrainingCardId;

    if (shouldReviewAnsweredFlash && activeTrainingCardId) {
      await requestTrainingPersistence(trainerCommands.trainingCardStatusTransition, {
        cardId: activeTrainingCardId,
        newStatus: "reviewed",
        reason: "flash_reflection_submitted",
      });
    }

    const shouldSubmitManualPracticeReturn =
      trainingComposerManualPracticeMode && activeTrainingCardId;
    const shouldSubmitBlockedFilePracticeReturn =
      trainingComposerFilePracticeMode && practiceBlockedMode && activeTrainingCardId;

    let authoritativePracticeStatus: string | undefined;
    if ((shouldSubmitManualPracticeReturn || shouldSubmitBlockedFilePracticeReturn) && activeTrainingCardId) {
      const passed = Boolean(shouldSubmitManualPracticeReturn && practiceResultMode);
      // commandId: trainerCommands.trainingPracticeReturn — persist the single-card practice return.
      const response = await requestTrainingPersistence(trainerCommands.trainingPracticeReturn, {
        cardId: activeTrainingCardId,
        passed,
        summary: normalizedEvidence,
        nextStep: passed
          ? (trainingNextAfterCompletionText ?? trainingState?.latestLearningFollowup ?? "")
          : (trainingFallbackActionText ?? trainingState?.latestLearningFollowup ?? ""),
        focusArea:
          trainingState?.latestLearningFocusArea ??
          selectedTrainingCardCandidate?.focusArea ??
          selectedTrainingRouteCard?.focusArea ??
          resolvedCoachFocus ??
          "",
        failedChecks:
          passed || !trainingComposerSelectedVerifyItem
            ? []
            : [trainingComposerSelectedVerifyItem],
        evidenceSource: "learner_return",
      });
      const workspace =
        response && typeof response === "object" && !Array.isArray(response)
          ? (response as { workspace?: unknown }).workspace
          : undefined;
      const selectedCardStatus =
        workspace && typeof workspace === "object" && !Array.isArray(workspace)
          ? (workspace as { selected_card_status?: unknown }).selected_card_status
          : undefined;
      authoritativePracticeStatus =
        typeof selectedCardStatus === "string" ? selectedCardStatus : undefined;
    }

    const manualPracticePassed =
      trainingComposerManualPracticeMode && practiceResultMode;
    const manualPracticeBlocked =
      trainingComposerManualPracticeMode && practiceBlockedMode;
    const filePracticeBlocked = trainingComposerFilePracticeMode && practiceBlockedMode;
    const trainingFailureOutcome =
      manualPracticeBlocked ||
      filePracticeBlocked ||
      trainingCardBlocked ||
      authoritativePracticeStatus === "blocked";
    const trainingPassOutcome =
      authoritativePracticeStatus === "active" ||
      (!authoritativePracticeStatus && trainingCardVerified);

    await requestTrainingPersistence(trainerCommands.evidenceEnqueue, {
      source: "learning_signal",
      summary: normalizedEvidence,
      concepts: [
        trainingState?.latestLearningFocusArea,
        selectedTrainingCardCandidate?.focusArea,
        resolvedCoachFocus,
      ].filter((value): value is string => Boolean(value?.trim())),
      outcome: trainingFailureOutcome ? "fail" : trainingPassOutcome ? "pass" : "note",
      sourceCardId: activeTrainingCardId,
      targetPlanStageId: activePlanStage?.id,
      confidence: trainingPassOutcome ? 0.86 : trainingFailureOutcome ? 0.52 : 0.68,
    });
    return true;
  }, [
    activePlanStage?.id,
    activeTrainingCardId,
    leftoverTrainingHandoffChromeNotLive,
    requestTrainingPersistence,
    reviewArtifactForeground,
    resolvedCoachFocus,
    selectedTrainingCardCandidate?.focusArea,
    selectedTrainingRouteCard?.focusArea,
    trainingComposerFilePracticeMode,
    trainingComposerReflectMode,
    trainingComposerReflectReason,
    trainingComposerReturnMode,
    trainingCardBlocked,
    trainingComposerManualPracticeMode,
    trainingComposerPracticeReturnMode,
    trainingComposerSelectedVerifyItem,
    trainingComposerStudyMode,
    trainingCardVerified,
    trainingFallbackActionText,
    trainingHandoffReflectionRequired,
    trainingHandoffReturnRequired,
    trainingHandoffId,
    trainingNextAfterCompletionText,
    trainingState?.latestLearningFocusArea,
    trainingState?.latestLearningFollowup,
    trainingState?.reviewArtifact?.id,
  ]);

  const handleResumeTrainingInCoach = useCallback(() => {
    if (leftoverTrainingHandoffChromeNotLive) {
      setActiveView("coach");
      requestCoachComposerFocus();
      return;
    }
    if (reviewArtifactForeground && trainingState?.reviewArtifact?.status === "resolved") {
      const title = trainingState.reviewArtifact.title ?? trainingState.reviewArtifact.focusArea ?? "review";
      const result = trainingState.reviewArtifact.verifiedResult ?? trainingState.reviewArtifact.summary ?? "";
      setActiveView("coach");
      setComposerDraft(
        appUiCopy(layout.composerLanguage, "我完成了“{t}”的回顾。结论：{r}\n\n请帮我安排下一步。")
          .replace("{t}", () => title)
          .replace("{r}", () => result),
      );
      requestCoachComposerFocus();
      return;
    }

    if (trainingHandoffReflectionRequired) {
      setTrainingComposerRoute("card");
      setActivityDraft("");
      window.requestAnimationFrame(() => {
        document.getElementById("training-response")?.focus();
      });
      return;
    }

    if (trainingHandoffReturnRequired && trainingState?.selectedCardId) {
      void handleSubmitTrainingEvidence("").catch(() => {
        setOperationMessage({
          tone: "error",
          message: trainingPersistenceFailureMessage(layout.composerLanguage),
        });
      });
      return;
    }

    setActiveView("coach");
    setComposerDraft(composeTrainingCoachBridgeDraft(trainingCoachBridge));
    requestCoachComposerFocus();
  }, [
    handleSubmitTrainingEvidence,
    layout.composerLanguage,
    leftoverTrainingHandoffChromeNotLive,
    requestCoachComposerFocus,
    reviewArtifactForeground,
    setActiveView,
    setComposerDraft,
    setOperationMessage,
    trainingCoachBridge,
    trainingHandoffReflectionRequired,
    trainingHandoffReturnRequired,
    trainingState?.reviewArtifact?.focusArea,
    trainingState?.reviewArtifact?.status,
    trainingState?.reviewArtifact?.summary,
    trainingState?.reviewArtifact?.title,
    trainingState?.reviewArtifact?.verifiedResult,
    trainingState?.selectedCardId,
  ]);

  const queueComposerPrompt = useCallback(
    (prompt: string) => {
      setOpenMenu(undefined);
      setComposerDraft(prompt);
      window.requestAnimationFrame(() => {
        focusComposerInput();
      });
    },
    [setComposerDraft],
  );

  const liveSandboxPreview = leftoverSandboxPreviewNotLive
    ? undefined
    : data.memory.sandboxPreview;
  const selectedResourceNavigationLabel = leftoverResourceSelectedDetailNotLive
    ? undefined
    : truncateInlineText(
        liveSandboxPreview?.relativePath ??
          data.memory.selectedResourceDetail?.title ??
          data.memory.selectedResourceDetail?.sandboxPath ??
          liveSandboxState?.selectedPath,
        layout.composerLanguage === "zh-CN" ? 22 : 46,
      ) ??
      truncateInlineText(
        data.memory.selectedResourceDetail?.source ?? liveSandboxPreview?.path,
        layout.composerLanguage === "zh-CN" ? 22 : 46,
      );
  const dockStageProgressLabel = hasFormalPlan && activePlanStage
    ? PLAN_COPY[layout.composerLanguage].stageProgress
        .replace(
          "{index}",
          String(
            data.plan.stages.findIndex((stage) => stage.id === activePlanStage.id) + 1,
          ),
        )
        .replace("{total}", String(data.plan.stages.length))
    : null;
  const dockAnchorControl = useComposerDockAnchor(
    activeView,
    activePlanStage?.title,
    dockStageProgressLabel,
    selectedResourceNavigationLabel,
  );
  const resourceConversationContextLabel = useMemo(() => {
    if (resourceConversationContextIds.length === 0) {
      return undefined;
    }
    const selectedNames = resourceConversationContextIds
      .map((resourceId) => liveResources.find((resource) => resource.id === resourceId)?.title?.trim())
      .filter((title): title is string => Boolean(title));
    const total = resourceConversationContextIds.length;
    const visibleNames = selectedNames.slice(0, 2);
    const overflowCount = Math.max(total - visibleNames.length, 0);
    if (layout.composerLanguage === "zh-CN") {
      const names = visibleNames.join("、");
      return names
        ? `已带入资料：${names}${overflowCount > 0 ? ` 等 ${total} 份` : ""}`
        : `已带入 ${total} 份资料`;
    }
    const names = visibleNames.join(", ");
    return names
      ? `Resource context: ${names}${overflowCount > 0 ? ` +${overflowCount}` : ""}`
      : `${total} resource${total === 1 ? "" : "s"} attached`;
  }, [layout.composerLanguage, liveResources, resourceConversationContextIds]);
  const planHasFormalThread =
    hasFormalPlan &&
    Boolean(activePlanStage?.title?.trim() || data.plan.summary.trim() || data.plan.stages.length > 0);
  const planIsFrozen = hasFormalPlan && livePlanFrozen;
  const resolvedPlanComposerMode: PlanComposerMode = !planHasFormalThread && planComposerMode !== "generate"
    ? recoveredRuntime && (planComposerMode === "blocker" || planComposerMode === "evidence")
      ? planComposerMode
      : "explain"
    : planIsFrozen && planComposerMode === "generate"
      ? "explain"
      : planComposerMode;
  const planComposerModes = useMemo<UtilityComposerModeOption<PlanComposerMode>[]>(() => {
    const planComposerText = resolvePlanComposerCopy(layout.composerLanguage);
    const isZh = layout.composerLanguage === "zh-CN";
    const stageLabel =
      truncateInlineText(
        formalPlanLive
          ? activePlanStage?.title ?? resolvedCoachStage ?? resolvedCoachFocus ?? livePlanSummary
          : recoveredDisplayFacts.currentStep || livePlanTitle,
        isZh ? 22 : 48,
      ) ?? planComposerText.currentThread;
    const explainMode = planComposerText.modes.explain;
    const generateMode = planComposerText.modes.generate;
    const evidenceMode = planComposerText.modes.evidence;
    const blockerMode = planComposerText.modes.blocker;
    const modes: UtilityComposerModeOption<PlanComposerMode>[] = [
      {
        id: "explain",
        label: explainMode.label,
        header: stageLabel,
        summary: `${planComposerText.planLabel} · ${explainMode.label}`,
        hint: explainMode.hint,
        placeholder: explainMode.placeholder,
        accessibilityLabel: explainMode.accessibilityLabel,
        prompts: [
          {
            id: "plan-explain-stage",
            label: explainMode.primaryPrompt.label,
            prompt: explainMode.primaryPrompt.prompt,
          },
          {
            id: "plan-why-now",
            label: explainMode.secondaryPrompt.label,
            prompt: explainMode.secondaryPrompt.prompt,
          },
        ],
      },
      {
        id: "generate",
        label: generateMode.label,
        header: generateMode.header,
        summary: `${planComposerText.planLabel} · ${generateMode.label}`,
        hint: generateMode.hint,
        placeholder: generateMode.placeholder,
        accessibilityLabel: generateMode.accessibilityLabel,
        prompts: [
          {
            id: "plan-generate",
            label: generateMode.primaryPrompt.label,
            prompt: generateMode.primaryPrompt.prompt,
          },
          {
            id: "plan-restructure",
            label: generateMode.secondaryPrompt.label,
            prompt: generateMode.secondaryPrompt.prompt,
          },
        ],
      },
      {
        id: "evidence",
        label: evidenceMode.label,
        header: evidenceMode.header,
        summary: `${planComposerText.planLabel} · ${evidenceMode.label}`,
        hint: evidenceMode.hint,
        placeholder: evidenceMode.placeholder,
        accessibilityLabel: evidenceMode.accessibilityLabel,
        prompts: [
          {
            id: "plan-evidence-note",
            label: evidenceMode.primaryPrompt.label,
            prompt: evidenceMode.primaryPrompt.prompt,
          },
          {
            id: "plan-adoption-gap",
            label: evidenceMode.secondaryPrompt.label,
            prompt: evidenceMode.secondaryPrompt.prompt,
          },
        ],
      },
      {
        id: "blocker",
        label: blockerMode.label,
        header: blockerMode.header,
        summary: `${planComposerText.planLabel} · ${blockerMode.label}`,
        hint: blockerMode.hint,
        placeholder: blockerMode.placeholder,
        accessibilityLabel: blockerMode.accessibilityLabel,
        prompts: [
          {
            id: "plan-shrink-next",
            label: blockerMode.primaryPrompt.label,
            prompt: blockerMode.primaryPrompt.prompt,
          },
          {
            id: "plan-blocker",
            label: blockerMode.secondaryPrompt.label,
            prompt: blockerMode.secondaryPrompt.prompt,
          },
        ],
      },
    ];
    return planIsFrozen ? modes.filter((mode) => mode.id !== "generate") : modes;
  }, [
    activePlanStage?.title,
    data.plan.stages.length,
    formalPlanLive,
    livePlanSummary,
    livePlanTitle,
    layout.composerLanguage,
    planIsFrozen,
    recoveredDisplayFacts.currentStep,
    resolvedCoachFocus,
    resolvedCoachStage,
  ]);
  const activePlanComposerMode =
    planComposerModes.find((mode) => mode.id === resolvedPlanComposerMode) ??
    planComposerModes[0];
  const resourceComposerModes = useMemo<UtilityComposerModeOption<ResourcesComposerMode>[]>(() => {
    const resourceComposerText = resolveResourceComposerCopy(layout.composerLanguage);
    const selectionLabel =
      selectedResourceNavigationLabel ?? resourceComposerText.nextResource;
    const locateMode = resourceComposerText.modes.locate;
    const downloadMode = resourceComposerText.modes.download;
    const organizeMode = resourceComposerText.modes.organize;
    const cardsMode = resourceComposerText.modes.cards;
    return [
      {
        id: "locate",
        label: locateMode.label,
        header: selectionLabel,
        summary: locateMode.summary,
        hint: locateMode.hint,
        placeholder: locateMode.placeholder,
        accessibilityLabel: locateMode.accessibilityLabel,
        prompts: [
          {
            id: "resources-find-file-modern",
            ...locateMode.primaryPrompt,
          },
          {
            id: "resources-open-next-modern",
            ...locateMode.secondaryPrompt,
          },
        ],
      },
      {
        id: "download",
        label: downloadMode.label,
        header: downloadMode.header,
        summary: downloadMode.summary,
        hint: downloadMode.hint,
        placeholder: downloadMode.placeholder,
        accessibilityLabel: downloadMode.accessibilityLabel,
        prompts: [
          {
            id: "resources-download-modern",
            ...downloadMode.primaryPrompt,
          },
          {
            id: "resources-source-gap",
            ...downloadMode.secondaryPrompt,
          },
        ],
      },
      {
        id: "organize",
        label: organizeMode.label,
        header: organizeMode.header,
        summary: organizeMode.summary,
        hint: organizeMode.hint,
        placeholder: organizeMode.placeholder,
        accessibilityLabel: organizeMode.accessibilityLabel,
        prompts: [
          {
            id: "resources-organize-modern",
            ...organizeMode.primaryPrompt,
          },
          {
            id: "resources-project-grouping",
            ...organizeMode.secondaryPrompt,
          },
        ],
      },
      {
        id: "cards",
        label: cardsMode.label,
        header: cardsMode.header,
        summary: cardsMode.summary,
        hint: cardsMode.hint,
        placeholder: cardsMode.placeholder,
        accessibilityLabel: cardsMode.accessibilityLabel,
        prompts: [
          {
            id: "resources-turn-into-cards-modern",
            ...cardsMode.primaryPrompt,
          },
          {
            id: "resources-knowledge-atom",
            ...cardsMode.secondaryPrompt,
          },
        ],
      },
    ];
  }, [layout.composerLanguage, selectedResourceNavigationLabel]);
  const activeResourcesComposerMode =
    resourceComposerModes.find((mode) => mode.id === resourcesComposerMode) ??
    resourceComposerModes[0];

  const renderTrainingComposerAccessory = () => {
    if (!composerUsesTrainingFlow) {
      return null;
    }

    if (
      trainingComposerUsesAnswerMode &&
      trainingComposerFlashMode === "choice" &&
      normalizedTrainingFlashChoices.length > 0
    ) {
      return (
        <section
          className="composer-training-panel composer-training-panel--choices-only"
          aria-label={appUiCopy(layout.composerLanguage, "训练选项")}
        >
          <div className="composer-context-strip__chips composer-context-strip__chips--training-choice">
            {normalizedTrainingFlashChoices.slice(0, 4).map((choice, index) => {
              const isActive = normalizeInlineComparisonText(choice) === normalizeInlineComparisonText(activityDraft);
              return (
                <button
                  key={`${choice}:${index}`}
                  className={`composer-context-chip ${isActive ? "is-active" : "is-enabled"}`.trim()}
                  type="button"
                  aria-pressed={isActive}
                  onClick={() => {
                    setActivityDraft(choice);
                    window.requestAnimationFrame(() => {
                      document.getElementById("training-response")?.focus();
                    });
                  }}
                >
                  <span>{String.fromCharCode(65 + index)}</span>
                  <span className="composer-context-chip__label">{choice}</span>
                </button>
              );
            })}
          </div>
        </section>
      );
    }

    if (!trainingComposerManualPracticeMode) {
      return null;
    }

    const resultMode = trainingComposerPracticeReturnMode === "result";
    const resultLabel = appUiCopy(layout.composerLanguage, "\u8bb0\u5f55\u7ed3\u679c");
    const blockerLabel = appUiCopy(layout.composerLanguage, "\u8bb0\u5f55\u53d7\u963b");

    return (
      <section
        className="composer-training-panel"
        aria-label={appUiCopy(layout.composerLanguage, "\u8bad\u7ec3\u4f5c\u7b54\u65b9\u5f0f")}
      >
        <div className="composer-context-strip__chips composer-context-strip__chips--training">
          <button
            className={`composer-context-chip ${resultMode ? "is-active" : "is-enabled"}`}
            type="button"
            aria-pressed={resultMode}
            title={resultLabel}
            onClick={() => {
              setTrainingComposerPracticeReturnMode("result");
              window.requestAnimationFrame(() => {
                document.getElementById("training-response")?.focus();
              });
            }}
          >
            <span className="composer-context-chip__label">{resultLabel}</span>
          </button>
          <button
            className={`composer-context-chip ${resultMode ? "is-enabled" : "is-active"}`}
            type="button"
            aria-pressed={!resultMode}
            title={blockerLabel}
            onClick={() => {
              setTrainingComposerPracticeReturnMode("blocked");
              window.requestAnimationFrame(() => {
                document.getElementById("training-response")?.focus();
              });
            }}
          >
            <span className="composer-context-chip__label">{blockerLabel}</span>
          </button>
        </div>
      </section>
    );
  };

  const handleCancelStream = useCallback(() => {
    if (!streaming.isStreaming) {
      return;
    }
    const resumeDraft = streamResumeDraftRef.current;
    if (resumeDraft.trim()) {
      setComposerDraft(resumeDraft);
    }
    postMessage({
      type: "session/cancelStreamMessage",
      payload: streaming.streamMessageId ? { messageId: streaming.streamMessageId } : undefined,
    });
  }, [setComposerDraft, streaming.isStreaming, streaming.streamMessageId]);

  const streamWasActiveRef = useRef(streaming.isStreaming);
  // §3.7 red line 5 (stay mode): the store owns the stay-send marker and the
  // returnToSurface notice (raised inside the stream/complete reducer, so a
  // batched fixture completion still closes the loop); the App only navigates
  // or dismisses.
  const handleDockReturnViewReply = useCallback(() => {
    clearDockReturnNotice();
    setActiveView("coach");
  }, [clearDockReturnNotice, setActiveView]);
  const handleDockReturnDismiss = useCallback(() => clearDockReturnNotice(), [clearDockReturnNotice]);
  useEffect(() => {
    const wasActive = streamWasActiveRef.current;
    streamWasActiveRef.current = streaming.isStreaming;
    if (wasActive && !streaming.isStreaming && streaming.completionStopReason !== "cancelled") {
      streamResumeDraftRef.current = "";
    }
  }, [streaming.completionStopReason, streaming.isStreaming]);

  const renderComposerAccessory = () => {
    if (!openMenu) {
      return null;
    }

    if (openMenu === "resources") {
      return (
        <section className="composer-menu-panel composer-menu-panel--resources">
          <div className="composer-menu-panel__header">
            <span className="eyebrow">{t.resourcesMenu}</span>
            <strong>
              {data.resources.length > 0
                ? appUiCopy(layout.composerLanguage, "这次会附带 {n} 份资料")
                    .replace("{n}", String(data.resources.length))
                    .replace("{s}", data.resources.length === 1 ? "" : "s")
                : t.resourcesEmpty}
            </strong>
          </div>
          <div className="composer-menu-panel__section">
            <div className="menu-list is-compact">
              <button
                className="menu-list__item"
                type="button"
                onClick={() =>
                  triggerResourceUpload({
                    browserPreview: isBrowserPreview,
                    payloadMode: "files",
                    filesInputRef: uploadFilesInputRef,
                    folderInputRef: uploadFolderInputRef,
                  })
                }
              >
                <span className="menu-list__icon" aria-hidden="true">
                  <UploadIcon size={14} />
                </span>
                <span className="menu-list__body">
                  <strong>{t.addFiles}</strong>
                </span>
              </button>
              <button
                className="menu-list__item"
                type="button"
                onClick={() =>
                  triggerResourceUpload({
                    browserPreview: isBrowserPreview,
                    payloadMode: "folder",
                    folder: true,
                    filesInputRef: uploadFilesInputRef,
                    folderInputRef: uploadFolderInputRef,
                  })
                }
              >
                <span className="menu-list__icon" aria-hidden="true">
                  <FolderIcon size={14} />
                </span>
                <span className="menu-list__body">
                  <strong>{t.addFolder}</strong>
                </span>
              </button>
              {!isBrowserPreview ? (
                <button
                  className="menu-list__item"
                  type="button"
                  onClick={() =>
                    triggerResourceUpload({
                      browserPreview: isBrowserPreview,
                      payloadMode: "url",
                      filesInputRef: uploadFilesInputRef,
                      folderInputRef: uploadFolderInputRef,
                    })
                  }
                >
                  <span className="menu-list__icon" aria-hidden="true">
                    <LinkIcon size={14} />
                  </span>
                  <span className="menu-list__body">
                    <strong>{t.addUrl}</strong>
                  </span>
                </button>
              ) : null}
            </div>
            {data.resources.length >= RESOURCE_UPLOAD_LIMIT ? (
              <p className="composer-menu-panel__hint">{t.maxFilesHint}</p>
            ) : null}
          </div>
          {data.resources.length > 0 ? (
            <div className="composer-menu-panel__section">
              <p className="composer-menu-panel__hint">
                {appUiCopy(layout.composerLanguage, "这些资料会和当前消息一起发给教练参考。")}
              </p>
              <div className="composer-resource-list">
                {data.resources.slice(0, 6).map((resource) => (
                  <div
                    key={resource.id}
                    className="composer-resource-chip"
                    title={[resource.title, resource.status].filter(Boolean).join(" · ")}
                  >
                    <strong>{resource.title}</strong>
                    <span>{resource.status}</span>
                  </div>
                ))}
              </div>
              {data.resources.length > 6 ? (
                <p className="composer-menu-panel__hint">
                  {appUiCopy(layout.composerLanguage, "另外还有 {n} 份资料会一起带上。").replace(
                    "{n}",
                    String(data.resources.length - 6),
                  )}
                </p>
              ) : null}
            </div>
          ) : null}
        </section>
      );
    }

    if (openMenu === "model") {
      const providerApplied = data.providerConfig.configured;
      const visibleSelections = filteredComposerProviderMenuItems;
      const visibleModels = visibleSelections.filter(
        (profile) => profile.selectionKind === "model",
      );
      const visibleProfiles = visibleSelections.filter(
        (profile) => profile.selectionKind === "profile" && !profile.isActive,
      );
      const savedProfiles = composerProviderMenuItems.filter(
        (profile) => profile.selectionKind === "profile" && !profile.isActive,
      );
      const hasModelQuery = composerModelQuery.trim().length > 0;
      const activeModelItem = composerProviderMenuItems.find(
        (item) => item.selectionKind === "model" && item.isActive,
      );
      const activeModelPolicyHint = composerModelPolicyHint(
        layout.composerLanguage,
        activeModelItem?.policyReason,
      );
      const retainedBlockedActiveModel =
        activeModelItem && activeModelPolicyHint ? activeModelItem : undefined;
      const defaultVisibleModels = composerProviderMenuItems
        .filter((profile) => profile.selectionKind === "model" && !profile.isActive)
        .slice(0, COMPOSER_MODEL_PICKER_INITIAL_OPTION_LIMIT);
      const displayedModels = hasModelQuery
        ? [
            ...(retainedBlockedActiveModel ? [retainedBlockedActiveModel] : []),
            ...visibleModels.filter((item) => item.id !== retainedBlockedActiveModel?.id),
          ]
        : [
            ...(retainedBlockedActiveModel ? [retainedBlockedActiveModel] : []),
            ...defaultVisibleModels,
          ];
      const nonActiveModelCount = composerProviderMenuItems.filter(
        (item) => item.selectionKind === "model" && !item.isActive,
      ).length;
      const hasOnlyCurrentModel =
        Boolean(activeModelItem) && nonActiveModelCount === 0 && savedProfiles.length === 0;
      const showModelSection =
        hasModelQuery || defaultVisibleModels.length > 0 || hasOnlyCurrentModel;
      const searchLabel =
        appUiCopy(layout.composerLanguage, "搜索模型或已保存连接");
      const emptyStateLabel = hasModelQuery
        ? appUiCopy(layout.composerLanguage, "没有匹配的模型或已保存连接。")
        : hasOnlyCurrentModel
          ? composerProviderCopy.modelPicker.onlyCurrentModel
          : composerHasSavedProfiles
            ? appUiCopy(layout.composerLanguage, "可从下方展开已保存连接。")
            : appUiCopy(layout.composerLanguage, "还没有可切换的模型。请到“设置”保存连接。");

      const visibleSelectionCount = displayedModels.length + (hasModelQuery ? visibleProfiles.length : 0);
      const showSearch = nonActiveModelCount > COMPOSER_MODEL_PICKER_INITIAL_OPTION_LIMIT;
      const modelSectionLabel =
        hasModelQuery
          ? appUiCopy(layout.composerLanguage, "匹配的模型")
          : appUiCopy(layout.composerLanguage, "可切换模型");
      const profileSectionLabel =
        appUiCopy(layout.composerLanguage, "已保存连接");
      const refreshModelsDisabled =
        !providerApplied ||
        !data.providerConfig.apiKeyConfigured ||
        data.providerConfig.modelListStatus === "loading";
      const refreshModelsLabel =
        appUiCopy(layout.composerLanguage, "刷新模型");
      const refreshModelsTitle = !providerApplied
        ? appUiCopy(layout.composerLanguage, "先保存连接，再更新模型列表")
        : !data.providerConfig.apiKeyConfigured
          ? appUiCopy(layout.composerLanguage, "先在“设置”填写访问密钥，再更新模型列表")
          : data.providerConfig.modelListStatus === "loading"
            ? appUiCopy(layout.composerLanguage, "正在更新模型列表")
            : appUiCopy(layout.composerLanguage, "更新模型列表");

      return (
        <section className="composer-menu-panel composer-menu-panel--provider">
          <div className="composer-menu-panel__header">
            <span className="eyebrow">{t.chatModel}</span>
            <div className="composer-menu-panel__header-actions">
              <ComposerIconButton
                icon={<RefreshIcon size={14} />}
                label={refreshModelsLabel}
                ariaLabel={refreshModelsLabel}
                title={refreshModelsTitle}
                active={data.providerConfig.modelListStatus === "loading"}
                disabled={refreshModelsDisabled}
                onClick={refreshComposerProviderModels}
              />
            </div>
          </div>

          {showSearch || hasModelQuery ? (
            <label className="resources-search resources-search--hero composer-menu-panel__search">
              <span className="sr-only">{searchLabel}</span>
              <input
                ref={composerModelSearchRef}
                type="search"
                value={composerModelQuery}
                onChange={(event) => setComposerModelQuery(event.target.value)}
                placeholder={searchLabel}
              />
            </label>
          ) : null}

          {composerThinkingDescriptor ? (
            <div className="composer-menu-panel__section composer-thinking">
              <div className="composer-thinking__header">
                <span className="eyebrow">
                  {appUiCopy(layout.composerLanguage, "思考强度")}
                </span>
                {composerThinkingDescriptor.disabled ? (
                  <span className="composer-thinking__state">
                    {appUiCopy(layout.composerLanguage, "已关闭")}
                  </span>
                ) : null}
              </div>
              <div className="composer-thinking__modes" role="group" aria-label={appUiAltCopy(layout.composerLanguage, "思考强度")}>
                {(
                  [
                    { value: "auto", label: appUiCopy(layout.composerLanguage, "自动") },
                    { value: "disabled", label: appUiCopy(layout.composerLanguage, "关闭") },
                    { value: "enabled", label: appUiCopy(layout.composerLanguage, "开启") },
                  ] as const
                ).map((option) => {
                  const active = composerThinkingDescriptor.config.mode === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      className={`composer-thinking__mode ${active ? "is-active" : ""}`}
                      aria-pressed={active}
                      onClick={() =>
                        setComposerThinking({
                          ...composerThinkingDescriptor.config,
                          mode: option.value,
                          // "On" must carry a concrete effort or nothing is
                          // emitted and the toggle falls back to "auto".
                          ...(option.value === "enabled" &&
                          composerThinkingDescriptor.kind === "reasoning_effort" &&
                          !composerThinkingDescriptor.config.reasoningEffort
                            ? { reasoningEffort: "medium" as const }
                            : {}),
                        })
                      }
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
              {composerThinkingDescriptor.config.mode === "enabled" &&
              composerThinkingDescriptor.kind === "reasoning_effort" &&
              composerThinkingDescriptor.effortOptions ? (
                <div className="composer-thinking__modes composer-thinking__modes--effort" role="group" aria-label={appUiCopy(layout.composerLanguage, "推理力度")}>
                  {composerThinkingDescriptor.effortOptions.map((option) => {
                    const active =
                      (composerThinkingDescriptor.config.reasoningEffort ?? "medium") === option;
                    return (
                      <button
                        key={option}
                        type="button"
                        className={`composer-thinking__mode ${active ? "is-active" : ""}`}
                        aria-pressed={active}
                        onClick={() =>
                          setComposerThinking({
                            ...composerThinkingDescriptor.config,
                            mode: "enabled",
                            reasoningEffort: option,
                          })
                        }
                      >
                        {option === "low"
                          ? appUiCopy(layout.composerLanguage, "低")
                          : option === "high"
                            ? appUiCopy(layout.composerLanguage, "高")
                            : appUiCopy(layout.composerLanguage, "中")}
                      </button>
                    );
                  })}
                </div>
              ) : null}
              {composerThinkingDescriptor.config.mode === "enabled" &&
              (composerThinkingDescriptor.kind === "thinking_budget" ||
                composerThinkingDescriptor.kind === "gemini_thinking") ? (
                <p className="composer-menu-panel__hint">
                  {appUiCopy(
                    layout.composerLanguage,
                    typeof composerThinkingDescriptor.config.budgetTokens === "number"
                      ? "思考预算 {n}，可在“设置”里调整。"
                      : "思考预算 自动，可在“设置”里调整。",
                  ).replace(
                    "{n}",
                    typeof composerThinkingDescriptor.config.budgetTokens === "number"
                      ? String(composerThinkingDescriptor.config.budgetTokens)
                      : "",
                  )}
                </p>
              ) : null}
            </div>
          ) : null}

          {showModelSection ? (
            <div className="composer-menu-panel__section">
              {visibleSelectionCount > 0 ? (
                <div className="composer-provider-groups">
                  {displayedModels.length > 0 ? (
                    <div
                      className="composer-provider-list"
                      role="list"
                      aria-label={modelSectionLabel}
                    >
                        {displayedModels.map((profile) => {
                          const policyHint = composerModelPolicyHint(
                            layout.composerLanguage,
                            profile.policyReason,
                          );
                          const modelDisabled = profile.isActive || profile.isSelectable === false;
                          const modelContextTokens =
                            data.providerConfig.modelTokenLimits?.[profile.model]
                              ?.contextWindowTokens ?? data.providerConfig.contextWindowTokens;
                          const modelContextHint = modelContextTokens
                            ? appUiCopy(layout.composerLanguage, "上下文 {n}").replace(
                                "{n}",
                                formatTokenCount(modelContextTokens),
                              )
                            : undefined;
                          return (
                            <button
                              key={profile.id}
                              className={`composer-provider-list__item ${profile.isActive ? "is-active" : ""}`}
                              type="button"
                              disabled={modelDisabled}
                              aria-current={profile.isActive ? "true" : undefined}
                              title={
                                [policyHint, modelContextHint].filter(Boolean).join(" · ") ||
                                profile.model
                              }
                              onClick={() => switchComposerProviderModel(profile.model)}
                            >
                              <div className="composer-provider-list__row">
                                <span className="composer-provider-list__stack">
                                  <span className="composer-provider-list__model">{profile.model}</span>
                                  {modelContextHint || policyHint ? (
                                    <span className="composer-provider-list__label">
                                      {[modelContextHint, policyHint].filter(Boolean).join(" · ")}
                                    </span>
                                  ) : null}
                                </span>
                                {profile.isActive ? (
                                  <span className="composer-provider-list__state">
                                    <CheckMarkIcon size={12} />
                                    <span className="sr-only">{composerProviderCopy.modelPicker.currentModel}</span>
                                  </span>
                                ) : null}
                              </div>
                            </button>
                          );
                        })}
                    </div>
                  ) : null}

                  {hasModelQuery && visibleProfiles.length > 0 ? (
                    <section className="composer-provider-group">
                      <div className="composer-provider-group__header">
                        <span className="eyebrow">{profileSectionLabel}</span>
                      </div>
                      <div
                        className="composer-provider-list"
                        role="list"
                        aria-label={appUiCopy(layout.composerLanguage, "已保存连接")}
                      >
                        {visibleProfiles.map((profile) => (
                          <button
                            key={profile.id}
                            className="composer-provider-list__item"
                            type="button"
                            title={profile.model}
                            onClick={() => switchComposerProviderProfile(profile.id)}
                          >
                            <div className="composer-provider-list__row">
                              <span className="composer-provider-list__stack">
                                <span className="composer-provider-list__model">{profile.label}</span>
                                <span className="composer-provider-list__label">{profile.model}</span>
                              </span>
                            </div>
                          </button>
                        ))}
                      </div>
                    </section>
                  ) : null}

                </div>
              ) : (
                <p className="composer-menu-panel__hint">{emptyStateLabel}</p>
              )}
            </div>
          ) : null}

          {!hasModelQuery && savedProfiles.length > 0 ? (
            <details className="composer-provider-group">
              <summary className="composer-provider-group__header">
                <span className="eyebrow">{profileSectionLabel}</span>
              </summary>
              <div
                className="composer-provider-list"
                role="list"
                aria-label={appUiCopy(layout.composerLanguage, "已保存连接")}
              >
                {savedProfiles.map((profile) => (
                  <button
                    key={profile.id}
                    className="composer-provider-list__item"
                    type="button"
                    title={profile.model}
                    onClick={() => switchComposerProviderProfile(profile.id)}
                  >
                    <div className="composer-provider-list__row">
                      <span className="composer-provider-list__stack">
                        <span className="composer-provider-list__model">{profile.label}</span>
                        <span className="composer-provider-list__label">{profile.model}</span>
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </details>
          ) : null}

          {!hasModelQuery && !showSearch && !providerApplied && savedProfiles.length === 0 ? (
            <p className="composer-menu-panel__hint">{emptyStateLabel}</p>
          ) : null}

        </section>
      );
    }

    return (
      <section className="composer-menu-panel">
        <div className="composer-menu-panel__header">
          <span className="eyebrow">{t.currentContext}</span>
          {sendContextShortSummary(data, layout, t) ? (
            <strong>{sendContextShortSummary(data, layout, t)}</strong>
          ) : null}
        </div>
        <div className="composer-menu-panel__section">
          <MenuToggleRow
            label={t.relatedFiles}
            value={
              layout.includeRelatedFiles
                ? data.liveContext.relatedFiles.length > 0
                  ? String(data.liveContext.relatedFiles.length)
                  : t.on
                : t.off
            }
            active={layout.includeRelatedFiles}
            onClick={() => setIncludeRelatedFiles(!layout.includeRelatedFiles)}
          />
          <MenuToggleRow
            label={t.follow}
            value={layout.followCurrentFile ? t.on : t.off}
            active={layout.followCurrentFile}
            onClick={() => setFollowCurrentFile(!layout.followCurrentFile)}
          />
        </div>
        <div className="composer-menu-panel__section">
          <span className="eyebrow">{t.contextDetail}</span>
          <MenuList
            items={[
              {
                label: t.detailFocused,
                active: layout.contextDetail === "focused",
                onClick: () => setContextDetail("focused"),
              },
              {
                label: t.detailBalanced,
                active: layout.contextDetail === "balanced",
                onClick: () => setContextDetail("balanced"),
              },
              {
                label: t.detailFull,
                active: layout.contextDetail === "full",
                onClick: () => setContextDetail("full"),
              },
            ]}
          />
        </div>
        <p className="composer-menu-panel__hint">{t.contextAutoNote}</p>
      </section>
    );
  };

  const renderCommandDeck = () => {
    if (
      dismissedComposerDeck === "command" ||
      !normalizedDraft.startsWith("/") ||
      matchingLocalCommands.length === 0
    ) {
      return null;
    }

    return (
      <div ref={composerDeckRef} className="command-deck" role="list" aria-label={t.slashCommands}>
        <div className="command-deck__header">
          <strong>{t.slashCommands}</strong>
          <span className="command-deck__hint">
            {appUiCopy(layout.composerLanguage, "Enter 执行，Tab 补全。")}
          </span>
        </div>
        <div className="command-deck__list">
          {matchingLocalCommands.map((command) => (
            <button
              key={command.command}
              className={`command-deck__item ${
                matchingLocalCommands[selectedCommandIndex]?.command === command.command ? "is-active" : ""
              }`}
              type="button"
              aria-label={`${command.command}: ${command.title}`}
              title={[command.command, command.title, command.description].filter(Boolean).join(" · ")}
              onMouseEnter={() => {
                const index = matchingLocalCommands.findIndex((item) => item.command === command.command);
                if (index >= 0) {
                  setSelectedCommandIndex(index);
                }
              }}
              onClick={() => {
                runComposerCommand(command);
              }}
            >
              <span className="command-deck__command">{command.command}</span>
              <span className="command-deck__body">
                <strong>{command.title}</strong>
                <span>{command.description}</span>
              </span>
            </button>
          ))}
        </div>
      </div>
    );
  };

  const selectSkillSuggestion = (skill: LocalSkillSuggestion) => {
    // Replace only the typed `$token` — text after it is skill arguments and
    // must survive autocomplete ("$exp notes" → "$explain notes").
    const triggerToken = trainerSkillTriggerToken(normalizedDraft);
    const remainder =
      triggerToken !== undefined ? normalizedDraft.slice(triggerToken.length).trim() : "";
    setComposerDraft(remainder ? `${skill.trigger} ${remainder}` : `${skill.trigger} `);
    setDismissedComposerDeck("skill");
    setOpenMenu(undefined);
    setSelectedCommandIndex(0);
    window.requestAnimationFrame(() => {
      focusComposerInput();
    });
  };

  const persistCustomSkills = (next: TrainerCustomSkill[]) => {
    // Keep local state identical to what the server stores — the payload is
    // normalized (deduped, capped) on the way out, so an un-normalized list
    // would leave the save-dedup comparison permanently mismatched.
    setCoachDefaults({ customSkills: normalizeTrainerCustomSkills(next) });
    queueCoachSettingsSave();
  };

  const saveCustomSkillDraft = () => {
    const skill = normalizeTrainerCustomSkill({
      ...skillDraftFields,
      id: undefined,
      createdAt: new Date().toISOString(),
    });
    if (!skill) {
      setOperationMessage({
        tone: "error",
        message:
          appUiCopy(layout.composerLanguage, "技能需要 $触发词 和提示词。"),
      });
      return;
    }
    const builtinCollision = trainerSkillCatalog.some(
      (entry) => entry.trigger.toLowerCase() === skill.trigger.toLowerCase(),
    );
    if (builtinCollision) {
      setOperationMessage({
        tone: "error",
        message:
          appUiCopy(layout.composerLanguage, "{v} 已经是内置技能，换个触发词。").replace("{v}", skill.trigger),
      });
      return;
    }
    const remaining = customSkills.filter(
      (entry) => entry.trigger.toLowerCase() !== skill.trigger.toLowerCase(),
    );
    if (remaining.length >= TRAINER_CUSTOM_SKILL_LIMIT) {
      setOperationMessage({
        tone: "error",
        message:
          appUiCopy(layout.composerLanguage, "最多只能有 {v} 个自定义技能，先删除一个。").replace("{v}", String(TRAINER_CUSTOM_SKILL_LIMIT)),
      });
      return;
    }
    persistCustomSkills([...remaining, skill]);
    setSkillDraftFields({ trigger: "", title: "", detail: "", prompt: "" });
    setOperationMessage({
      tone: "success",
      message:
        appUiCopy(layout.composerLanguage, "已保存 {v}。").replace("{v}", skill.trigger),
    });
  };

  const installCustomSkillFromPaste = () => {
    const skill = parseTrainerSkillShare(skillImportText);
    if (!skill) {
      setOperationMessage({
        tone: "error",
        message:
          appUiCopy(layout.composerLanguage, "粘贴的内容不是有效的技能分享包。"),
      });
      return;
    }
    const builtinCollision = trainerSkillCatalog.some(
      (entry) => entry.trigger.toLowerCase() === skill.trigger.toLowerCase(),
    );
    if (builtinCollision) {
      setOperationMessage({
        tone: "error",
        message:
          appUiCopy(layout.composerLanguage, "{v} 与内置技能冲突，未安装。").replace("{v}", skill.trigger),
      });
      return;
    }
    const remaining = customSkills.filter(
      (entry) => entry.trigger.toLowerCase() !== skill.trigger.toLowerCase(),
    );
    if (remaining.length >= TRAINER_CUSTOM_SKILL_LIMIT) {
      setOperationMessage({
        tone: "error",
        message:
          appUiCopy(layout.composerLanguage, "最多只能有 {v} 个自定义技能，先删除一个。").replace("{v}", String(TRAINER_CUSTOM_SKILL_LIMIT)),
      });
      return;
    }
    persistCustomSkills([...remaining, skill]);
    setSkillImportText("");
    setOperationMessage({
      tone: "success",
      message:
        appUiCopy(layout.composerLanguage, "已安装 {v}。").replace("{v}", skill.trigger),
    });
  };

  const removeCustomSkill = (skillId: string) => {
    if (pendingDeleteSkillId !== skillId) {
      setPendingDeleteSkillId(skillId);
      return;
    }
    setPendingDeleteSkillId(undefined);
    const skill = customSkills.find((entry) => entry.id === skillId);
    persistCustomSkills(customSkills.filter((entry) => entry.id !== skillId));
    setOperationMessage({
      tone: "info",
      message: appUiCopy(layout.composerLanguage, "已删除 {v}。").replace(
        "{v}",
        () => skill?.trigger ?? "skill",
      ),
    });
  };

  const copyCustomSkillShare = async (skill: TrainerCustomSkill) => {
    try {
      await navigator.clipboard.writeText(serializeTrainerSkillShare(skill));
      setOperationMessage({
        tone: "success",
        message:
          appUiCopy(layout.composerLanguage, "{v} 分享包已复制，可粘贴给其他工作区。").replace("{v}", skill.trigger),
      });
    } catch {
      setOperationMessage({
        tone: "error",
        message: appUiCopy(layout.composerLanguage, "复制失败，请重试。"),
      });
    }
  };

  const openSkillSettings = (skillTrigger?: string) => {
    setSettingsSectionRequest({ category: "teaching", requestId: Date.now(), skillTrigger });
    setActiveView("settings");
  };
  const renderSkillSharing = () => <details className="template-disclosure"><summary>{appUiCopy(layout.composerLanguage, "分享")}</summary><div>
    {customSkills.map((skill) => <div className="template-context" key={skill.id}><span>{skill.trigger} · {skill.title}</span><button type="button" className="template-back" onClick={() => void copyCustomSkillShare(skill)}>{appUiCopy(layout.composerLanguage, "复制分享包")}</button></div>)}
    <textarea className="settings-skill-import" value={skillImportText} placeholder={appUiCopy(layout.composerLanguage, "粘贴技能分享包 JSON 进行安装")} aria-label={appUiCopy(layout.composerLanguage, "安装技能")} rows={2} onChange={(event) => setSkillImportText(event.target.value)} />
    <button type="button" className="button button--ghost" disabled={!skillImportText.trim()} onClick={installCustomSkillFromPaste}>{appUiCopy(layout.composerLanguage, "安装技能")}</button>
  </div></details>;
  const renderSkillDeck = () => {
    if (dismissedComposerDeck === "skill" || !normalizedDraft.startsWith("$")) return null;
    const draftTriggerToken = trainerSkillTriggerToken(normalizedDraft) ?? "$";
    const creatableTrigger = draftTriggerToken.length > 1 && !availableSkillCatalog.some((skill) => skill.trigger.toLowerCase() === draftTriggerToken.toLowerCase()) ? draftTriggerToken : undefined;
    return <CommandPalette containerRef={composerDeckRef} label={appUiCopy(layout.composerLanguage, "技能")}
      hint={appUiCopy(layout.composerLanguage, "继续输入可收窄范围，删除 $ 就会按普通消息发送。")}
      empty={appUiCopy(layout.composerLanguage, "没有匹配到 skill。继续输入，或者直接当作普通消息发送。")}
      moreLabel={appUiCopy(layout.composerLanguage, "↓ 还有 {n} 条")}
      selectedIndex={selectedCommandIndex} onHighlight={setSelectedCommandIndex}
      entries={matchingLocalSkills.map((skill) => ({ id: skill.id, trigger: skill.trigger,
        title: resolveTrainerSkillText(skill.title, layout.composerLanguage), detail: resolveTrainerSkillText(skill.detail, layout.composerLanguage), onSelect: () => selectSkillSuggestion(skill) }))}
      footer={<><button type="button" className="template-back" onClick={() => openSkillSettings(creatableTrigger)}>{creatableTrigger ? appUiCopy(layout.composerLanguage, "创建技能 {v}").replace("{v}", creatableTrigger) : appUiCopy(layout.composerLanguage, "管理技能")}</button></>} />;
  };

  const renderSuggestedActions = () => {
    if (latestCoachArtifact && !coachTrainingInlineAction) {
      return null;
    }

    if (!coachTrainingInlineAction && liveSuggestedActions.length === 0) {
      return null;
    }

    const visibleActions = liveSuggestedActions;

    if (!coachTrainingInlineAction && visibleActions.length === 0) {
      return null;
    }

    return (
      <div className="suggested-inline">
        {leftoverSuggestedActionNotLive ? (
          <p
            className="coach-leftover-note"
            data-coach-leftover-note="true"
            role="status"
            aria-live="polite"
          >
            {t.leftoverNotLiveHint}
          </p>
        ) : null}
        <div className="suggested-actions">
          {coachTrainingInlineAction ? (
            <button
              className="button button--ghost"
              type="button"
              title={coachTrainingInlineAction.title}
              onClick={() => setActiveView("training")}
            >
              {coachTrainingInlineAction.label}
            </button>
          ) : (
            visibleActions.slice(0, 1).map((item) => (
              <button
                key={item.id}
                className="button button--ghost"
                type="button"
                title={item.rationale ?? item.focusArea ?? item.prompt ?? item.label}
                onClick={() =>
                  handleSuggestedAction(item.action, {
                    prompt: item.prompt,
                    focusArea: item.focusArea,
                  })
                }
              >
                {appUiCopy(layout.composerLanguage, "接着做：{v}").replace("{v}", item.label)}
              </button>
            ))
          )}
        </div>
      </div>
    );
  };

  const providerSetupAction = {
    primary: {
      label: providerSetupState.actionLabel,
    },
  };
  const useProviderTemplateByLabel = (templateLabel: string) => {
    setSettingsActionState({
      kind: "save-provider",
      targets: ["provider"],
      baselineMessageKey:
        normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
    });
    if (isBrowserPreview) {
      void loadBrowserPreviewModule()
        .then((browserPreview) =>
          browserPreview.useBrowserPreviewProviderTemplate(
            templateLabel,
            previewSessionId,
          ),
        )
        .then(({ sessionId, messages }) => {
          setPreviewSessionId(sessionId);
          applyPreviewHostMessages(messages, true);
        })
        .catch(() => {
          setOperationMessage({
            tone: "error",
            message: recoverableFailureMessage("provider", layout.composerLanguage),
          });
        });
      return;
    }
    postMessage({
      type: "command/execute",
      payload: {
        commandId: trainerCommands.useProviderTemplate,
        payload: {
          templateLabel,
          skipPicker: true,
        },
      },
    });
  };
  const runWorkspaceAdmissionCommand = (commandId: string, payload?: unknown) => {
    postMessage({
      type: "command/execute",
      payload: payload === undefined ? { commandId } : { commandId, payload },
    });
  };
  // First runs have no capability summary yet; the host window trust verdict
  // fills the gap so a trusted window is never asked to trust itself again.
  const effectiveWorkspaceTrustState = resolveEffectiveTrustState(
    readWorkspaceTrustStateFromCapabilitySummary(
      liveSandboxState?.capabilitySummary as Record<string, unknown> | undefined,
    ),
    data.memory.workspace?.windowTrusted === true,
  );
  const onboarding = deriveOnboardingSteps({
    workspaceAdmissionStatus: trainerWorkspaceAdmission?.status,
    workspaceTrustState: effectiveWorkspaceTrustState,
    providerConfigured: data.providerConfig.configured,
    providerApiKeyConfigured: data.providerConfig.apiKeyConfigured,
    providerSendBlocked: providerSendState.blocked,
  });
  // Only true cold starts get the wizard: a saved connection that merely lost
  // its key keeps the existing scenario-aware recovery surface.
  const onboardingActive = !onboarding.complete && !data.providerConfig.configured;
  // The onboarding paste only fills address + key, but a saveable provider
  // needs a model id. The browser preview can list models for an unsaved
  // draft directly; the VS Code host keeps the field free-form so the learner
  // can type it (the full settings picker stays available either way).
  // Smart skill authoring: the settings panel describes a skill in one line;
  // the preview generates the trigger/title/prompt with the configured model.
  const onGenerateSkillDraft = useMemo(() => {
    if (!isBrowserPreview) {
      return requestNativeSkillDraft;
    }
    return async (description: string) => {
      const browserPreview = await loadBrowserPreviewModule();
      return browserPreview.generateBrowserPreviewSkillDraft(description);
    };
  }, [isBrowserPreview]);

  const onboardingListModels = useMemo(() => {
    if (!isBrowserPreview) {
      return undefined;
    }
    return async (baseUrl: string, apiKey: string): Promise<string[]> => {
      const browserPreview = await loadBrowserPreviewModule();
      return browserPreview.listBrowserPreviewDraftModels({ baseUrl }, apiKey);
    };
  }, [isBrowserPreview]);
  const startOnboardingTrial = () => {
    setSettingsActionState({
      kind: "start-provider-trial",
      targets: ["provider"],
      baselineMessageKey:
        normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
    });
    if (isBrowserPreview) {
      setOperationMessage({
        tone: "info",
        message:
          appUiCopy(layout.composerLanguage, "练习模式需要在 VS Code 扩展中启动。"),
      });
      return;
    }
    postMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.startProviderTrial },
    });
  };
  const saveProviderDraft = () => {
    setSettingsActionState({
      kind: "save-provider",
      targets: ["provider"],
      baselineMessageKey:
        normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
    });
    if (isBrowserPreview) {
      void loadBrowserPreviewModule()
        .then((browserPreview) =>
          browserPreview.saveBrowserPreviewProvider(providerSavePayload, previewSessionId),
        )
        .then(({ sessionId, messages }) => {
          setPreviewSessionId(sessionId);
          applyPreviewHostMessages(messages, true);
        })
        .catch(() => {
          setOperationMessage({
            tone: "error",
            message: recoverableFailureMessage("provider", layout.composerLanguage),
          });
        });
      return;
    }
    postMessage({
      type: "command/execute",
      payload: {
        commandId: "trainer.provider.save",
        payload: { ...providerSavePayload, responseLanguage: layout.composerLanguage },
      },
    });
  };
  const onboardingWizard = onboardingActive ? (
    <OnboardingWizard
      steps={onboarding.steps}
      activeStepId={onboarding.activeStepId}
      complete={onboarding.complete}
      busy={settingsActionState?.kind === "save-provider"}
      trialBusy={settingsActionState?.kind === "start-provider-trial"}
      draftBaseUrl={providerDraft.baseUrl}
      draftApiKey={providerDraft.apiKey}
      draftModel={providerDraft.model}
      hasStoredApiKey={data.providerConfig.apiKeyConfigured}
      onDraftChange={(patch) => setProviderDraft((draft) => ({ ...draft, ...patch }))}
      onListModels={onboardingListModels}
      onChooseWorkspaceRoot={() =>
        runWorkspaceAdmissionCommand(trainerCommands.chooseTrainerWorkspaceRoot)
      }
      onTrustWindow={() =>
        postMessage({
          type: "command/execute",
          payload: { commandId: trainerCommands.trustWorkspaceWindow },
        })
      }
      onSaveConnection={saveProviderDraft}
      onStartTrial={startOnboardingTrial}
      onOpenSettings={() => openProviderSetup()}
    />
  ) : null;
  const workspaceAdmissionContent = trainerWorkspaceAdmission ? (
    <>
      <WorkspaceAdmissionPanel
        status={trainerWorkspaceAdmission.status}
        projectName={trainerWorkspaceAdmission.projectName}
        projectPath={trainerWorkspaceAdmission.projectPath}
        subjectFamily={firstLookSummary?.subjectFamily}
        reconciliation={trainerWorkspaceAdmission.reconciliation}
        onRetryAdmission={() => runWorkspaceAdmissionCommand(trainerCommands.retryWorkspaceAdmission, { responseLanguage: layout.composerLanguage })}
        onContinueAdmission={() => runWorkspaceAdmissionCommand(trainerCommands.continueWorkspaceAdmission, { responseLanguage: layout.composerLanguage })}
        onAbandonAdmission={() => runWorkspaceAdmissionCommand(trainerCommands.abandonWorkspaceAdmission)}
        onSelectWorkspaceRoot={() =>
          runWorkspaceAdmissionCommand(trainerCommands.chooseTrainerWorkspaceRoot)
        }
        onSelectProject={() =>
          runWorkspaceAdmissionCommand(trainerCommands.chooseWorkspaceProject)
        }
        onAddProject={() =>
          runWorkspaceAdmissionCommand(trainerCommands.adoptWorkspaceProject, {
            responseLanguage: layout.composerLanguage,
          })
        }
        onBrowseProject={() => runWorkspaceAdmissionCommand(trainerCommands.browseWorkspaceProject)}
        onIgnoreProject={() => runWorkspaceAdmissionCommand(trainerCommands.ignoreWorkspaceProject)}
        onDeleteProject={() => runWorkspaceAdmissionCommand(trainerCommands.deleteWorkspaceProject)}
      />
    </>
  ) : null;
  const coachSuperEntryContent = (embedded = false) => {
    if (embedded || workspaceSessionBlocked) {
      return null;
    }
    if (shouldShowNeutralEmptyState) {
      if (onboardingWizard) {
        // Unified cold-start wizard covers the fresh-user ladder; the
        // scenario-aware recovery block below stays for saved connections.
        return (
          <div
            className={`coach-empty-state ${
              displayConnectionState === "starting"
                ? "coach-empty-state--welcome"
                : "coach-empty-state--blocked"
            }`}
          >
            {onboardingWizard}
          </div>
        );
      }
      // Scenario-aware, localized setup copy (first-run "连接模型", missing key,
      // backend starting, …) instead of a single error-flavoured sentence.
      const setupTitle = providerSetupState.title;
      // A categorized provider failure names its class (invalid key, rate
      // limit, …) instead of the generic check-connection line.
      const setupDetail =
        (data.connection.state === "connected" && providerSendState.blocked ? providerSendState.reason?.trim() : undefined) ||
        providerSetupState.detail;
      const setupActionLabel =
        providerSetupState.actionLabel ||
        (layout.composerLanguage === "zh-CN" ? "检查连接" : providerSetupAction.primary.label);
      return (
        <div
          className={`coach-empty-state ${
            displayConnectionState === "starting"
              ? "coach-empty-state--welcome"
              : "coach-empty-state--blocked"
          }`}
        >
          <p>{setupTitle}</p>
          {setupDetail && setupDetail !== setupTitle ? (
            <p className="coach-empty-state__detail">{setupDetail}</p>
          ) : null}
          <button className="button button--accent" type="button" onClick={() => openProviderSetup()}>
            {setupActionLabel}
          </button>
        </div>
      );
    }
    if (isFirstCoachConversation && providerCanCoachNow) {
      // §六十一: three starter prompts — not a dashboard. Filling the draft
      // keeps the learner in control of what gets sent.
      const starters =
        COACH_STARTER_PROMPTS[layout.composerLanguage] ?? COACH_STARTER_PROMPTS["en-US"];
      return (
        <div className="coach-empty-state coach-empty-state--welcome">
          <p>
            {appUiCopy(layout.composerLanguage, "你在做什么？")}
          </p>
          <div className="coach-empty-state__starters" role="group"
            aria-label={appUiCopy(layout.composerLanguage, "开始方式")}>
            {starters.map((starter) => (
              <button
                key={starter.label}
                type="button"
                className="toolbar-button"
                onClick={() => {
                  setComposerDraft(starter.prompt);
                }}
              >
                {starter.label}
              </button>
            ))}
          </div>
        </div>
      );
    }
    return null;
  };

  const handleCoachArtifactOpen = (artifact: CoachArtifactBlockData) => {
    // “Set as practice” explicitly creates a card for the live plan step.
    // A normal task turn is intentionally blocked after Return; it must not
    // mint a parallel TaskSpec or leave this button stuck in review-only mode.
    if (
      (artifact.kind === "task" || artifact.kind === "next_step") &&
      (!artifact.recommendedAction || artifact.recommendedAction === "task") &&
      formalPlanLive && !livePlanFrozen &&
      activePlanStage?.id && data.plan.id &&
      recoveredDisplayFacts.currentStep?.trim()
    ) {
      handleGenerateTrainingCard(
        activePlanStage?.title ?? artifact.focusArea,
        recoveredDisplayFacts.currentStep,
        {
          planId: data.plan.id,
          stageId: activePlanStage.id,
          step: recoveredDisplayFacts.currentStep,
          revision: data.plan.revision,
        },
      );
      return;
    }
    if (artifact.recommendedAction) {
      handleSuggestedAction(artifact.recommendedAction, {
        focusArea: artifact.focusArea,
      });
      return;
    }
    if (artifact.kind === "plan" || artifact.kind === "plan_update") {
      setActiveView("plan");
      return;
    }
    if (artifact.kind === "evaluation" || artifact.kind === "review") {
      handleSuggestedAction("review", {
        focusArea: artifact.focusArea,
      });
      return;
    }
    if (artifact.kind === "task" || artifact.kind === "next_step") {
      handleSuggestedAction("task", {
        focusArea: artifact.focusArea,
      });
    }
  };
  // Stable identity for memoized conversation children; behavior stays fresh
  // through the ref so memo never serves a stale closure.
  const handleCoachArtifactOpenRef = useRef(handleCoachArtifactOpen);
  handleCoachArtifactOpenRef.current = handleCoachArtifactOpen;
  const stableHandleCoachArtifactOpen = useCallback(
    (artifact: CoachArtifactBlockData) => handleCoachArtifactOpenRef.current(artifact),
    [],
  );

  const coachCheckpointRecovery =
    leftoverStreamingCheckpointNotLive ? false : isCoachCheckpointRecoveryState(streaming);
  const coachCheckpointRecoveryCopy =
    COACH_CHECKPOINT_RECOVERY_COPY[layout.composerLanguage] ??
    COACH_CHECKPOINT_RECOVERY_COPY["en-US"];
  const runCoachCheckpointRecoveryAction = (action: CoachCheckpointRecoveryAction) => {
    if (isBrowserPreview) {
      return;
    }
    postMessage({
      type: "command/execute",
      payload: {
        commandId:
          action === "resume"
            ? trainerCommands.resumeLatestCoachCheckpoint
            : trainerCommands.replayLatestCoachCheckpoint,
      },
    });
  };
  const coachCheckpointRecoveryActions = coachCheckpointRecovery ? (
    <section className="coach-checkpoint-recovery" aria-label={coachCheckpointRecoveryCopy.title}>
      <strong>{coachCheckpointRecoveryCopy.title}</strong>
      <p>{coachCheckpointRecoveryCopy.hint}</p>
      <div className="coach-checkpoint-recovery__actions">
        <button className="button button--accent" type="button" onClick={() => runCoachCheckpointRecoveryAction("resume")}>
          {coachCheckpointRecoveryCopy.resume}
        </button>
        <button className="button button--ghost" type="button" onClick={() => runCoachCheckpointRecoveryAction("replay")}>
          {coachCheckpointRecoveryCopy.replay}
        </button>
      </div>
    </section>
  ) : null;

  const renderCoachConversationPane = (className: string, embedded = false) => (
    <CoachConversationView
      messages={coachRenderConversation}
      className={className}
      surfaceTone="quiet"
      eyebrow={undefined}
      title={undefined}
      subtitle={undefined}
      openArtifactLabel={appUiCopy(layout.composerLanguage, "\u5c55\u5f00")}
      userLabel={t.you}
      assistantLabel={t.trainer}
      systemLabel={appUiCopy(layout.composerLanguage, "\u7cfb\u7edf")}
      language={layout.composerLanguage}
      emptyState={embedded || workspaceSessionBlocked ? null : coachSuperEntryContent(false)}
      listHead={embedded ? undefined : coachTrainingResumeLine}
      footer={embedded ? undefined : coachCheckpointRecoveryActions}
      streamingMessage={
        streaming.isStreaming
          ? {
              // R3: the in-flight body comes from the view's own store
              // subscription; App never selects per-chunk content.
              body: "",
              author: t.trainer,
              timestamp: t.streaming,
              role: "assistant",
              roleLabel: t.trainer,
            }
          : null
      }
      liveContentFromStore
      streamingPlaceholder={streamingPlaceholderBody}
      onArtifactOpen={stableHandleCoachArtifactOpen}
      onMessageAction={handleCoachMessageAction}
      pendingMessageAction={pendingMessageAction}
      turnNextStepRequiresConfirmation={coachTurnNextStepRequiresConfirmation}
    />
  );

  // r1-g0-2: first-run task suggestions — at most two task-relevant chips above
  // the one coach input while the thread is still nearly empty. A click fills
  // the draft and sends through the same submit path; the chips are plain
  // secondary buttons, no banner and no second input.
  const coachThreadNearEmpty =
    coachRenderConversation.length === 0 && !streaming.isStreaming;
  const coachSuggestionChipTexts = (
    activeView === "coach" &&
    !composerUsesTrainingFlow &&
    coachThreadNearEmpty &&
    providerCanCoachNow &&
    !shouldShowNeutralEmptyState &&
    !workspaceSessionBlocked
  )
    ? [
        recoveredDisplayFacts.currentStep?.trim() || activePlanStage?.title?.trim() || "",
        liveSuggestedActions[0]?.prompt?.trim() || liveSuggestedActions[0]?.label?.trim() || "",
      ]
        .filter((text, index, all) => text.length > 0 && all.indexOf(text) === index)
        .slice(0, 2)
    : [];
  const coachSuggestionChips = coachSuggestionChipTexts.length > 0 ? (
    <div
      className="composer-suggestion-chips"
      role="group"
      aria-label={appUiCopy(layout.composerLanguage, "从当前任务开始")}
    >
      {coachSuggestionChipTexts.map((text) => (
        <button
          key={text}
          type="button"
          className="toolbar-button composer-suggestion-chip"
          title={text}
          onClick={() => {
            setComposerDraft(text);
            void handleSubmit(text);
          }}
        >
          {truncateInlineText(text, 18) ?? text}
        </button>
      ))}
    </div>
  ) : null;

  const renderContextualResultRail = (view: "plan" | "resources" | "training" | "settings") => {
    const isTraining = view === "training";
    const isResources = view === "resources";
    const isSettings = view === "settings";
    const isZh = layout.composerLanguage === "zh-CN";
    const textLimit = isZh ? 28 : 56;
    // Leftover-not-live (recovered without live selected_card_id / leftover stored note)
    // must not paint leftover dump as a live skip/grade/reflect/return object.
    // Quiet leftover sentence stays on the Training pane. Do not invent a card.
    const leftoverTrainingActivityNotLive =
      leftoverTrainingHandoffChromeNotLive ||
      (Boolean(recoveredRuntime) && !String(trainingState?.selectedCardId ?? "").trim());
    const blockerValue = isTraining
      ? leftoverTrainingActivityNotLive
        ? undefined
        : pickFirstText(
          trainingState?.latestLearningBlocker,
          trainingState?.latestTrainingHandoff?.blockedBy,
          activeTrainingReviewArtifact?.blockedReason,
          runtimeBlockedReason,
        )
      : isSettings
        ? undefined
      : runtimeBlockedReason ??
        (leftoverCoachTurnChromeNotLive
          ? undefined
          : data.coachTurn?.blocker ?? data.coachingState?.blocker);
    const resultValue = isTraining
      ? leftoverTrainingActivityNotLive
        ? undefined
        : pickFirstText(
          trainingState?.latestLearningVerifiedResult,
          activeTrainingReviewArtifact?.verifiedResult,
          trainingState?.latestLearningPartialProgress,
          activeTrainingReviewArtifact?.partialProgress,
        )
      : isSettings
        ? undefined
      : latestArtifactTeaser ??
        (leftoverCoachTurnChromeNotLive ? undefined : latestCoachArtifact?.title) ??
        resolvedCoachSummary;
    // A stream belongs to the active session, not to the view where it was
    // started. Keep the live reply visible when the learner switches views
    // while the agent is still working; the completed-result guard below still
    // prevents stale Coach results from cluttering the Resources surface.
    // The preview truncates from the start, so reading the latest content here
    // (scheduled by the coarse bucket) is exact for what this line shows.
    const liveValue = streaming.isStreaming
      ? truncateInlineText(streaming.streamMessageId?.startsWith("training_")
          ? streamingPlaceholderBody
          : useWorkbenchState.getState().streaming.streamedContent || streamingPlaceholderBody, textLimit)
      : undefined;
    const activitySource = liveValue ?? blockerValue ?? resultValue;
    const activityValue =
      isTraining && !liveValue
        ? activitySource?.trim()
        : truncateInlineText(activitySource, textLimit);
    const isPlanContextWorthSurfacing = view !== "plan" || Boolean(liveValue || blockerValue);
    const isResourcesContextWorthSurfacing =
      !isResources || streaming.isStreaming || lastTurnView === "resources";
    const isSettingsContextWorthSurfacing = !isSettings || Boolean(liveValue);
    if (
      !activityValue ||
      !isPlanContextWorthSurfacing ||
      !isResourcesContextWorthSurfacing ||
      !isSettingsContextWorthSurfacing ||
      (isTraining && !liveValue)
    ) {
      return null;
    }
    const activityLabel = liveValue
      ? t.viewContextWorking
      : blockerValue
        ? t.viewContextBlocker
        : t.viewContextLatest;
    const activityTone = liveValue ? "activity" : blockerValue ? "blocker" : "result";

    return (
      <section
        className={`view-context-rail view-context-rail--${view}`}
        data-view-context-rail={view}
        aria-label={`${
          view === "plan"
            ? planViewLabel(layout.composerLanguage)
            : isResources
              ? resourcesViewLabel(layout.composerLanguage)
              : isSettings
                ? settingsViewLabel(layout.composerLanguage)
                : trainingViewLabel(layout.composerLanguage)
        } ${t.viewContextCoach}`}
        aria-live={streaming.isStreaming ? "polite" : undefined}
      >
        <div className="view-context-rail__facts">
          <div className={`view-context-rail__fact view-context-rail__fact--${activityTone}`} title={activityValue}>
            <span>{activityLabel}</span>
            <strong>{activityValue}</strong>
          </div>
        </div>
        {isTraining ? null : (
        <button
          className="view-context-rail__open-coach"
          data-view-context-rail-open-coach
          type="button"
          onClick={() => {
            setActiveView(
              view === "settings" && lastTurnView && lastTurnView !== "settings"
                ? lastTurnView
                : "coach",
            );
            requestCoachComposerFocus();
          }}
        >
          {t.openCoach}
        </button>
        )}
      </section>
    );
  };

  const renderViewAgentReply = (view: "plan" | "resources" | "training") => {
    let latestReply: ConversationMessage | undefined;
    let latestUnscopedReply: ConversationMessage | undefined;
    for (let index = localizedConversation.length - 1; index >= 0; index -= 1) {
      const message = localizedConversation[index];
      if (message.role !== "assistant") {
        continue;
      }
      if (message.sourceView === view) {
        latestReply = message;
        break;
      }
      if (!message.sourceView && !latestUnscopedReply) {
        latestUnscopedReply = message;
      }
    }

    if (!latestReply && lastTurnView === view) {
      latestReply = latestUnscopedReply;
    }

    const isStreamingForView = streaming.isStreaming && lastTurnView === view;
    const visibleReply = isStreamingForView
      ? {
          id: `streaming-${view}`,
          role: "assistant" as const,
          author: t.trainer,
          // Same coarse-bucket read as the view rail: the banner summary
          // truncates from the start, so the latest content is exact here.
          body: streaming.streamMessageId?.startsWith("training_")
            ? streamingPlaceholderBody
            : useWorkbenchState.getState().streaming.streamedContent || streamingPlaceholderBody,
          timestamp: t.streaming,
        }
      : latestReply;
    if (!visibleReply) {
      return null;
    }

    const isZh = layout.composerLanguage === "zh-CN";
    const viewLabel =
      view === "plan"
        ? planViewLabel(layout.composerLanguage)
        : view === "resources"
          ? resourcesViewLabel(layout.composerLanguage)
          : trainingViewLabel(layout.composerLanguage);
    const summary = isStreamingForView
      ? appUiCopy(layout.composerLanguage, "正在回复")
      : truncateInlineText(visibleReply.body, isZh ? 26 : 52) ??
        (appUiCopy(layout.composerLanguage, "查看回复"));

    return (
      <details
        className={`view-agent-reply view-agent-reply--${view}`}
        data-view-agent-reply={view}
        open={isStreamingForView}
      >
        <summary>
          <span>{appUiCopy(layout.composerLanguage, "{v} · 本次教练回复").replace("{v}", viewLabel)}</span>
          <strong>{summary}</strong>
        </summary>
        <div className="view-agent-reply__body" aria-live={isStreamingForView ? "polite" : undefined}>
          <CoachMessageBubble
            assistantLabel={t.trainer}
            className={isStreamingForView ? "message-bubble--streaming" : undefined}
            language={layout.composerLanguage}
            message={visibleReply}
            openArtifactLabel={appUiCopy(layout.composerLanguage, "展开")}
            systemLabel={appUiCopy(layout.composerLanguage, "系统")}
            userLabel={t.you}
            streaming={isStreamingForView}
            onArtifactOpen={stableHandleCoachArtifactOpen}
            onMessageAction={handleCoachMessageAction}
            pendingMessageAction={pendingMessageAction}
          />
          {!isStreamingForView ? (
            <UserFeedbackDisclosure
              language={layout.composerLanguage}
              busy={userFeedbackState.busy}
              submittedKind={userFeedbackState.submittedKind}
              error={userFeedbackState.error}
              onSubmit={submitUserFeedback}
            />
          ) : null}
        </div>
      </details>
    );
  };

  const renderDockedView = (view: DockedView, content: ReactNode) => {
    return (
      <section
        className={`view-stack view-stack--${view} view-stack--content-${layout.learningSurfaceAlignment} view-stack--single`}
      >
        <div className="view-stack__primary">
          {content}
        </div>
      </section>
    );
  };

  // §十一: one quiet context line, not a module — the card itself stays the
  // primary surface for the in-progress training card. r3: it renders as the
  // list's first entry (listHead) instead of a floating banner above the pane,
  // so on a short thread it anchors with the conversation instead of opening a
  // dead zone. The data attribute stays for the UI-geometry gate.
  const coachTrainingResumeLine = (() => {
    const ts = data.workspaceTrainingState;
    const cardId = ts?.selectedCardId?.trim();
    const cardTitle = ts?.selectedCardTitle?.trim();
    if (!cardId || !cardTitle) return null;
    return (
      <p className="muted" data-coach-training-resume="true">
        {appUiCopy(layout.composerLanguage, "正在进行：{v}").replace("{v}", () => cardTitle)}
        {/* r2 first-screen affordance: a bordered quiet button (existing
            .button--ghost) reads as the next step; the bare .template-back
            text link rendered as part of the sentence. */}
        <button
          type="button"
          className="button button--ghost"
          onClick={() => setActiveView("training")}
        >
          {appUiCopy(layout.composerLanguage, "继续")}
        </button>
      </p>
    );
  })();

  const renderCoachRootView = () => (
    <section className="coach-view">
      {coachBlockingSurface === "workspace-admission" && onboardingWizard ? (
        // R1①: on a true cold start the wizard's workspace step owns the
        // root-selection ask; the admission panel must not stack under it
        // (its reconciliation details stay available once the wizard clears).
        <div className="coach-onboarding">{onboardingWizard}</div>
      ) : coachBlockingSurface === "workspace-admission" && workspaceAdmissionContent ? (
        <>
          <div className="coach-workspace-admission">{workspaceAdmissionContent}</div>
          {!providerCanCoachNow && providerCoachNotice ? (
            <button
              className="button button--ghost coach-workspace-admission__provider-action"
              type="button"
              onClick={openProviderSetup}
            >
              <span>{providerSetupState.actionLabel}</span>
              <strong>{providerCoachNotice.message}</strong>
            </button>
          ) : null}
        </>
      ) : null}
      {renderCoachConversationPane("coach-pane", false)}
    </section>
  );

  const contextualComposerSummary = () => {
    if (!latestCoachArtifact || leftoverCoachTurnChromeNotLive) {
      return sendStatuslineText(sendAnalysis, data, layout, t);
    }
    const action = latestCoachArtifact.recommendedAction
      ? appUiCopy(layout.composerLanguage, "现在顺着这条结果继续：{v}").replace(
          "{v}",
          () => latestCoachArtifact.title,
        )
      : appUiCopy(layout.composerLanguage, "当前主线：{v}").replace(
          "{v}",
          () => latestCoachArtifact.title,
        );
    return latestArtifactTeaser ? `${action} · ${latestArtifactTeaser}` : action;
  };

  const composerSurfaceHint = () => {
    if (providerSendState.warning && !providerSendState.blocked) {
      return providerSendState.warning;
    }
    if (draft.trim().length === 0) {
      return undefined;
    }
    if (latestCoachArtifact) {
      return contextualComposerSummary();
    }
    if (sendAnalysis.target === "local_command" || sendAnalysis.intent !== "coach") {
      return sendStatuslineText(sendAnalysis, data, layout, t);
    }
    if (data.resources.length > 0) {
      return composerHintText(sendAnalysis, data, layout, t);
    }
    return undefined;
  };

  const providerRecoveryReason =
    providerBlockReason ??
    (providerSendState.blocked
      ? providerRecoverySummary(
          data.providerConfig,
          layout.composerLanguage,
          data.connection.state,
        ).detail
      : providerSendState.reason?.trim());
  void providerRecoveryReason;
  const trainingComposerModeTextCopy = trainingComposerModeText(layout.composerLanguage);
  const blockedComposerFallback =
    sendBlocked && !workspaceSessionBlocked
      ? providerRecoveryLocale(layout.composerLanguage).draftWhilePaused
      : providerCanCoachNow && !providerBlockReason
      ? isFirstCoachConversation
        ? coachFirstComposerPlaceholder[layout.composerLanguage]
        : activeView === "plan"
          ? t.composerPlaceholderPlan
          : t.composerPlaceholder
      : activeView === "plan"
        ? appUiCopy(layout.composerLanguage, "先记下下一条计划备注。")
        : activeView === "training"
          ? trainingComposerModeTextCopy.genericPlaceholder
          : providerRecoveryLocale(layout.composerLanguage).draftWhilePaused;
  const blockedComposerPresenceDetail =
    activeView === "coach"
      ? localizeUiViewReferences(
          blockedComposerPresenceMessage(
            data.providerConfig,
            layout.composerLanguage,
            data.connection.state,
          ),
          layout.composerLanguage,
        ) ??
        blockedComposerPresenceMessage(
          data.providerConfig,
          layout.composerLanguage,
          data.connection.state,
        )
      : blockedComposerGuidance;
  const blockedComposerPresenceCopy = workspaceSessionBlocked
    ? workspaceSessionBlockMessage ?? blockedComposerPresenceDetail
    : blockedComposerPresenceDetail;
  const compactUtilityComposerPlaceholder =
    sendBlocked
      ? blockedComposerFallback
      : activeView === "resources"
        ? appUiCopy(layout.composerLanguage, "找资料")
        : activeView === "training"
          ? trainingComposerModeTextCopy.genericPlaceholder
          : activeView === "plan"
            ? appUiCopy(layout.composerLanguage, "写下这一步")
            : blockedComposerFallback;
  const refinedUtilityComposerPlaceholder =
    activeView === "resources"
      ? appUiCopy(layout.composerLanguage, "找资料")
      : activeView === "plan"
        ? appUiCopy(layout.composerLanguage, "写下这一步")
        : compactUtilityComposerPlaceholder;
  const trainingFilePracticeTextCopy = trainingFilePracticeText(layout.composerLanguage);
  const trainingHandoffComposerTextCopy = trainingHandoffComposerText(layout.composerLanguage);
  const resolvedTrainingComposerPlaceholder = trainingComposerUsesAnswerMode
    ? trainingComposerFlashMode === "choice"
      ? trainingComposerModeTextCopy.choicePlaceholder
      : trainingComposerFlashMode === "fill"
        ? trainingComposerModeTextCopy.fillPlaceholder
        : trainingComposerModeTextCopy.shortAnswerPlaceholder
    : trainingComposerStudyMode
      ? trainingComposerModeTextCopy.studyPlaceholder
    : trainingComposerPracticeInputMode
      ? trainingComposerFilePracticeMode
        ? trainingComposerPracticeReturnMode === "result"
          ? trainingFilePracticeTextCopy.resultPlaceholder
          : trainingFilePracticeTextCopy.blockerPlaceholder
        : trainingComposerPracticeReturnMode === "result"
          ? trainingComposerModeTextCopy.manualResultPlaceholder
          : trainingComposerModeTextCopy.manualBlockerPlaceholder
    : trainingComposerReturnMode
      ? trainingHandoffComposerTextCopy.returnPlaceholder
    : trainingComposerReflectMode
      ? trainingHandoffComposerTextCopy.reflectPlaceholder
    : trainingComposerSelectedVerifyItem
      ? trainingComposerModeTextCopy.verificationPlaceholder.replace(
          "{item}",
          truncateInlineText(
            trainingComposerSelectedVerifyItem,
            layout.composerLanguage === "zh-CN" ? 20 : 40,
          ) ?? trainingComposerSelectedVerifyItem,
        )
      : trainingComposerModeTextCopy.genericPlaceholder;
  const resolvedCompactUtilityComposerPlaceholder =
    trainingComposerTalkMode
      ? trainingComposerModeTextCopy.talkPlaceholder
      : composerUsesTrainingFlow && !composerSendBlocked
      ? resolvedTrainingComposerPlaceholder
      : activeView === "resources"
        ? activeResourcesComposerMode.placeholder
        : activeView === "plan"
          ? activePlanComposerMode.placeholder
          : refinedUtilityComposerPlaceholder;
  const planSummarySource =
    formalPlanLive
      ? activePlanStage?.title ?? resolvedCoachStage ?? resolvedCoachFocus ?? livePlanSummary
      : recoveredDisplayFacts.currentStep || livePlanTitle;
  const planSummaryTruncated = truncateInlineText(
    planSummarySource,
    layout.composerLanguage === "zh-CN" ? 24 : 48,
  );
  const resolvedUtilityComposerSummary =
    activeView === "resources"
      ? selectedResourceNavigationLabel
        ? appUiCopy(layout.composerLanguage, "资料：{v}").replace(
            "{v}",
            () => selectedResourceNavigationLabel,
          )
        : appUiCopy(layout.composerLanguage, "资料：先让教练定位文件")
      : activeView === "plan"
        ? planSummaryTruncated
          ? appUiCopy(layout.composerLanguage, "计划：{v}").replace("{v}", () => planSummaryTruncated)
          : appUiCopy(layout.composerLanguage, "计划：解释当前阶段")
        : activeView === "coach"
          ? contextualComposerSummary()
          : undefined;
  const resolvedUtilityComposerHint =
    activeView === "resources"
      ? appUiCopy(layout.composerLanguage, "可以让教练先找文件、判断最该打开哪一个，或建议如何整理当前资料区。")
      : activeView === "plan"
        ? appUiCopy(layout.composerLanguage, "这里适合解释当前阶段、整理练习记录，或把遇到的问题变成更小的一步。")
        : providerCanCoachNow && !providerBlockReason
          ? composerSurfaceHint()
          : undefined;
  const refinedUtilityComposerHint =
    activeView === "coach" && providerCanCoachNow && !providerBlockReason
      ? composerSurfaceHint()
      : undefined;
  const laneAwareUtilityComposerHint =
    activeView === "resources"
      ? activeResourcesComposerMode.hint
      : activeView === "plan"
        ? activePlanComposerMode.hint
        : refinedUtilityComposerHint;
  const studyFocusSource =
    trainingTargetSkill ?? trainingScenarioPackLabel ?? trainingProblemStatement;
  const studyFocusText =
    truncateInlineText(studyFocusSource, layout.composerLanguage === "zh-CN" ? 22 : 44) ??
    studyFocusSource;
  const returnModeText = truncateInlineText(
    trainingReturnWithText ?? trainingSuccessSignal ?? trainingCoachBridge.ctaLabel,
    layout.composerLanguage === "zh-CN" ? 26 : 52,
  );
  const reflectFallbackText = truncateInlineText(
    trainingFallbackActionText ??
      trainingComposerSelectedVerifyItem ??
      trainingState?.latestLearningBlocker,
    layout.composerLanguage === "zh-CN" ? 26 : 52,
  );
  const currentCheckText =
    truncateInlineText(
      trainingComposerSelectedVerifyItem,
      layout.composerLanguage === "zh-CN" ? 26 : 52,
    ) ?? trainingComposerSelectedVerifyItem;
  const resolvedComposerSummary = trainingComposerTalkMode
    ? appUiCopy(layout.composerLanguage, "\u8bad\u7ec3 \u00b7 \u4e0e\u6559\u7ec3\u5bf9\u8bdd")
    : composerUsesTrainingFlow
    ? trainingComposerUsesAnswerMode
      ? appUiCopy(
          layout.composerLanguage,
          trainingComposerFlashMode === "choice"
            ? "作答方式：选择"
            : trainingComposerFlashMode === "fill"
              ? "作答方式：填空"
              : "作答方式：简答",
        )
      : trainingComposerPracticeInputMode
        ? trainingComposerFilePracticeMode
          ? appUiCopy(
              layout.composerLanguage,
              trainingComposerPracticeReturnMode === "result" ? "动手：结果记录" : "动手：遇到的问题",
            )
          : appUiCopy(
              layout.composerLanguage,
              trainingComposerPracticeReturnMode === "result" ? "动手：结果" : "动手：遇到的问题",
            )
      : trainingComposerStudyMode
        ? studyFocusText
          ? appUiCopy(layout.composerLanguage, "学习聚焦：{v}").replace("{v}", () => studyFocusText)
          : appUiCopy(layout.composerLanguage, "学习聚焦：当前卡片")
      : trainingComposerReturnMode
        ? returnModeText
          ? appUiCopy(layout.composerLanguage, "回流：{v}").replace("{v}", () => returnModeText)
          : appUiCopy(layout.composerLanguage, "回流：带回结果")
      : trainingComposerReflectMode
        ? trainingComposerReflectReason === "flash_answered"
          ? appUiCopy(layout.composerLanguage, "\u590d\u76d8\uff1a\u538b\u6210\u4e00\u6761\u89c4\u5219")
          : trainingComposerReflectReason === "skipped"
            ? appUiCopy(layout.composerLanguage, "\u590d\u76d8\uff1a\u6536\u7d27\u5165\u53e3")
            : trainingComposerReflectReason === "verification_passed"
              ? appUiCopy(layout.composerLanguage, "\u590d\u76d8\uff1a\u5df2\u9a8c\u8bc1\u7684\u89c4\u5219")
            : reflectFallbackText
              ? appUiCopy(layout.composerLanguage, "复盘：{v}").replace("{v}", () => reflectFallbackText)
              : appUiCopy(layout.composerLanguage, "复盘：收紧遇到的问题")
      : trainingComposerSelectedVerifyItem
        ? appUiCopy(layout.composerLanguage, "当前检查：{v}").replace("{v}", () => currentCheckText)
        : appUiCopy(layout.composerLanguage, "\u8bb0\u4e0b\u8fd9\u4e00\u8f6e\u7684\u7ed3\u679c\u3002")
    : resolvedUtilityComposerSummary;
  const laneAwareComposerSummary =
    trainingComposerTalkMode || composerUsesTrainingFlow
      ? resolvedComposerSummary
      : activeView === "resources"
        ? activeResourcesComposerMode.summary
        : activeView === "plan"
          ? activePlanComposerMode.summary
          : resolvedComposerSummary;
  const resolvedComposerAccessibilityLabel = trainingComposerTalkMode
    ? trainingComposerModeTextCopy.talkAccessibilityLabel
    : composerUsesTrainingFlow
    ? trainingComposerUsesAnswerMode
      ? trainingComposerModeTextCopy.answerAccessibilityLabel
      : trainingComposerPracticeInputMode
        ? trainingComposerPracticeReturnMode === "blocked"
          ? trainingFilePracticeTextCopy.submitBlocker
          : trainingFilePracticeTextCopy.submitTry
      : trainingComposerStudyMode
        ? trainingComposerModeTextCopy.studyAccessibilityLabel
      : trainingComposerReturnMode
        ? trainingHandoffComposerTextCopy.returnAccessibilityLabel
      : trainingComposerReflectMode
        ? trainingHandoffComposerTextCopy.reflectAccessibilityLabel
      : trainingComposerModeTextCopy.genericAccessibilityLabel
    : t.composerAccessibility;
  const refinedComposerAccessibilityLabel = composerUsesTrainingFlow
    ? resolvedComposerAccessibilityLabel
    : activeView === "plan"
      ? appUiCopy(layout.composerLanguage, "提交计划讨论、生成或证据整理请求")
      : activeView === "resources"
        ? appUiCopy(layout.composerLanguage, "提交资料定位、整理、下载或转卡请求")
        : activeView === "coach"
          ? t.composerAccessibility
          : activeView === "training"
            ? trainingComposerModeTextCopy.genericAccessibilityLabel
          : appUiCopy(layout.composerLanguage, "提交当前视图请求");
  const laneAwareComposerAccessibilityLabel =
    trainingComposerTalkMode || composerUsesTrainingFlow
      ? resolvedComposerAccessibilityLabel
      : activeView === "plan"
        ? activePlanComposerMode.accessibilityLabel
        : activeView === "resources"
          ? activeResourcesComposerMode.accessibilityLabel
          : refinedComposerAccessibilityLabel;
  const localizedTrainingComposerAccessibilityLabel =
    !trainingComposerTalkMode && composerUsesTrainingFlow && trainingComposerReturnMode
      ? trainingHandoffComposerTextCopy.returnAccessibilityLabel
      : !trainingComposerTalkMode && composerUsesTrainingFlow && trainingComposerReflectMode
        ? trainingHandoffComposerTextCopy.reflectAccessibilityLabel
        : laneAwareComposerAccessibilityLabel;
  const localizedTrainingComposerSubmitAriaLabel =
    !trainingComposerTalkMode && composerUsesTrainingFlow && trainingComposerReturnMode
      ? trainingHandoffComposerTextCopy.returnSubmitAriaLabel
      : !trainingComposerTalkMode && composerUsesTrainingFlow && trainingComposerReflectMode
        ? trainingHandoffComposerTextCopy.reflectSubmitAriaLabel
        : trainingComposerTalkMode || composerUsesTrainingFlow
          ? localizedTrainingComposerAccessibilityLabel
          : activeView === "training"
            ? trainingComposerModeTextCopy.genericAccessibilityLabel
          : activeView === "resources"
            ? activeResourcesComposerMode.accessibilityLabel
          : appUiCopy(layout.composerLanguage, activeView === "coach" ? "发送消息" : "发送请求");
  const localizedTrainingComposerSummary =
    !trainingComposerTalkMode && composerUsesTrainingFlow && trainingComposerReturnMode
      ? trainingHandoffComposerTextCopy.returnSummary
      : laneAwareComposerSummary;
  const allowEmptyTrainingReturnSubmission =
    composerUsesTrainingFlow &&
    trainingComposerReturnMode &&
    trainingHandoffReturnRequired &&
    Boolean(activeTrainingCardId);
  // Compact single-card action surface (Phase-C training slice): the Start/
  // Verify buttons are rendered inside TrainingWorkbenchView from the
  // eight-language surface labels; the card reports status transitions and
  // verification requests through the handler below.
  const handleVerifyCurrentFileFromCard = () => {
    if (data.workspace?.isRemoteWorkspace && !isBrowserPreview) {
      // The controller owns the running guard, panel state and request identity.
      beginRemoteVerification(activeTrainingCardId ?? "");
      return;
    }
    if (isBrowserPreview) {
      setTrainingVerifyNotice(
        appUiCopy(layout.composerLanguage, "预览不能验证当前文件；真实工作区中将运行验证。"),
      );
      return;
    }
    handleVerifyTrainingFromIde();
  };
  useEffect(() => {
    if (activeView !== "settings" || isBrowserPreview || companionStateQueriedRef.current) {
      return;
    }
    companionStateQueriedRef.current = true;
    postMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.remoteCompanionState },
    });
  }, [activeView, isBrowserPreview]);
  const handleStopRemoteVerification = () => {
    stopRemoteVerification();
  };
  const trainingVerifyFileVisible =
    hasTrainingCard && trainingCardType === "practice" && effectiveTrainingSubmode !== "learn-primer";
  // §26: Learning 下一步 → [开始练习] navigates to Training Focus.
  const trainingPrimaryAction = !hasTrainingCard ? undefined : (
    <button
      className="button button--accent"
      type="button"
      onClick={() => {
        setActiveView("training");
        const cardId = data.workspaceTrainingState?.selectedCardId?.trim();
        if (cardId && !isBrowserPreview && !trainingComposerReturnMode) {
          attemptLifecycle.startOrRecover(cardId, {
            filePath: data.liveContext?.activeFile ?? undefined,
          });
        }
      }}
    >
      {appUiCopy(layout.composerLanguage, "开始练习")}
    </button>
  );

  const showComposerTrainingVerify =
    activeView === "training" &&
    Boolean(hasTrainingCard) &&
    !leftoverTrainingHandoffChromeNotLive &&
    trainingCardType === "practice" &&
    trainingPracticeVerificationMode === "file" &&
    (trainingComposerPhase === "try" || trainingComposerPhase === "verify");
  const trainingCoachActionLabel = trainingHandoffReflectionRequired
    ? t.trainingRecordStep
    : trainingHandoffReturnRequired
      ? t.trainingReturnToCoach
      : trainingComposerPhase === "return"
      ? t.trainingReturnToCoach
      : trainingCoachBridge.ctaLabel;
  const trainingCoachAction = (
    <>
      <button
        className={`button ${trainingCardVerified || trainingCardBlocked ? "button--accent" : "button--ghost"}`}
        type="button"
        onClick={handleResumeTrainingInCoach}
      >
        {trainingCoachActionLabel}
      </button>
    </>
  );

  const renderResourcesView = () => {
    return (
      <section className="resources-view">
        {dockReturnNotice === "resources" ? (
          <DockReturnToSurfaceBar
            language={layout.composerLanguage}
            surface="resources"
            onViewReply={handleDockReturnViewReply}
            onDismiss={handleDockReturnDismiss}
          />
        ) : null}
        <Suspense
          fallback={<ViewFallback label={resourcesViewLabel(layout.composerLanguage)} language={layout.composerLanguage} />}
        >
          <ResourcesWorkbenchView
          language={layout.composerLanguage}
          resources={liveResources}
          resourceSearch={data.resourceSearch}
          onSearchQueryChange={setResourcesViewSearchQuery}
          orientation={
            leftoverResourceLibraryListNotLive && resourcesOrientation
              ? {
                  ...resourcesOrientation,
                  why: t.leftoverNotLive,
                  primaryAction: "open_coach",
                  primaryActionLabel: t.openCoach,
                }
              : resourcesOrientation
          }
          leftoverNote={leftoverResourceLibraryListNotLive ? t.leftoverNotLive : undefined}
          onOrientationAction={handleResourcesOrientationAction}
          deletedResources={data.deletedResources}
          sandboxState={liveSandboxState}
          sandboxPreview={leftoverSandboxPreviewNotLive ? undefined : data.memory.sandboxPreview}
          resourceWriteAccess={resourceWriteAccess}
          onChooseWorkspaceRoot={
            trainerWorkspaceAdmission?.status === "root-missing"
              ? () => runWorkspaceAdmissionCommand(trainerCommands.chooseTrainerWorkspaceRoot)
              : undefined
          }
          restoreContext={resourceRestoreContext}
          onDebugVisibleFacts={(facts) =>
            activeView === "resources" ? postDebugVisibleFacts({ activeView: "resources", resources: facts }) : undefined
          }
          organizationConfirm={
            resourceOrganizationPending?.pending && !leftoverResourceLibraryListNotLive
              ? {
                  operationCount: resourceOrganizationPending.operationCount,
                  onConfirm: () =>
                    postMessage({
                      type: "command/execute",
                      payload: {
                        commandId: trainerCommands.confirmResourceOrganization,
                        payload: { responseLanguage: layout.composerLanguage },
                      },
                    }),
                  onCancel: () =>
                    postMessage({
                      type: "command/execute",
                      payload: {
                        commandId: trainerCommands.cancelResourceOrganization,
                      },
                    }),
                }
              : undefined
          }
          isBrowserPreview={browserPreviewFixture}
          onStartTrainingFromResource={
            browserPreviewFixture ? undefined : requestResourceTrainingHandoff
          }
          onOpenTraining={() => setActiveView("training")}
          onAskCoach={(resourceIds) => {
            setSelectedResourceContextIds(resourceIds);
            setResourceConversationContextIds(resourceIds);
            setActiveView("coach");
            requestCoachComposerFocus();
          }}
          onJoinLearning={(resourceIds) => {
            setSelectedResourceContextIds(resourceIds);
            setResourceConversationContextIds(resourceIds);
            setCoachPlanContext("explain");
            setActiveView("coach");
            requestCoachComposerFocus();
          }}
          initialResourceContextIds={resourceConversationContextIds}
          onResourceSelectionChange={handleResourceSelectionChange}
          onRestoreContextChange={setResourceRestoreContext}
          onSearchResources={
            isBrowserPreview
              ? browserPreviewFixture
                ? undefined
                : requestBrowserPreviewResourceSearch
              : requestResourceSearch
          }
          onImportFiles={() =>
            triggerResourceUpload({
              browserPreview: isBrowserPreview,
              payloadMode: "files",
              filesInputRef: uploadFilesInputRef,
              folderInputRef: uploadFolderInputRef,
            })
          }
          onImportFolder={() =>
            triggerResourceUpload({
              browserPreview: isBrowserPreview,
              payloadMode: "folder",
              folder: true,
              filesInputRef: uploadFilesInputRef,
              folderInputRef: uploadFolderInputRef,
            })
          }
          onImportUrl={() =>
            isBrowserPreview ? void handleBrowserUrlImport() : triggerResourceUpload({
              browserPreview: false,
              payloadMode: "url",
              filesInputRef: uploadFilesInputRef,
              folderInputRef: uploadFolderInputRef,
            })
          }
          onCaptureResource={
            isBrowserPreview && browserPreviewFixture ? undefined : captureResourceIntoLibrary
          }
          captureFocusOptions={resourceCaptureFocusOptions}
          onOrganizeResource={
            isBrowserPreview && browserPreviewFixture ? undefined : organizeLibraryResource
          }
          onExportResource={
            isBrowserPreview && browserPreviewFixture ? undefined : exportLibraryResource
          }
          onListLibraryFolders={
            isBrowserPreview && browserPreviewFixture ? undefined : listLibraryFolders
          }
          onCreateLibraryFolder={
            isBrowserPreview && browserPreviewFixture ? undefined : createLibraryFolder
          }
          onRenameLibraryFolder={
            isBrowserPreview && browserPreviewFixture ? undefined : renameLibraryFolder
          }
          onDeleteLibraryFolder={
            isBrowserPreview && browserPreviewFixture ? undefined : deleteLibraryFolder
          }
          onRevealSavedPath={isBrowserPreview && browserPreviewFixture ? undefined : revealLibraryPath}
          isLiveBrowserPreview={isBrowserPreview && !browserPreviewFixture}
          onExpandToEditor={canOpenInEditor ? () => openViewInEditor("resources") : undefined}
          expandToEditorLabel={expandToEditorLabel}
          onOpenResource={(resourceId) =>
            postMessage({
              type: "resource/open",
              payload: { resourceId },
            })
          }
          onPreviewResource={
            isBrowserPreview && browserPreviewFixture
              ? undefined
              : (resourceId) =>
                  postMessage({
                    type: "command/execute",
                    payload: { commandId: trainerCommands.previewSandbox, payload: { resourceId } },
                  })
          }
          onRefreshResources={
            isBrowserPreview
              ? () => {
                  postMessage({
                    type: "command/execute",
                    payload: {
                      commandId: trainerCommands.indexResources,
                    },
                  });
                }
              : requestResourceIndex
          }
          onRefreshDeletedResources={
            isBrowserPreview
              ? undefined
              : () => {
                  postMessage({
                    type: "command/execute",
                    payload: {
                      commandId: trainerCommands.refreshResourceTrash,
                    },
                  });
                }
          }
          onDeleteResources={
            isBrowserPreview
              ? undefined
              : (resourceIds) => requestResourceMutation("delete", resourceIds)
          }
          onRestoreResources={
            isBrowserPreview
              ? undefined
              : (resourceIds) => requestResourceMutation("restore", resourceIds)
          }
          deleteUnavailableReason={
            isBrowserPreview
              ? appUiCopy(layout.composerLanguage, "\u6d4f\u89c8\u5668\u9884\u89c8\u4e0d\u4f1a\u5220\u9664\u771f\u5b9e\u8d44\u6599\u3002\u8bf7\u5728 VS Code \u4fa7\u680f\u4e2d\u6267\u884c\u3002")
              : undefined
          }
          restoreUnavailableReason={
            isBrowserPreview
              ? appUiCopy(layout.composerLanguage, "\u6d4f\u89c8\u5668\u9884\u89c8\u4e0d\u4f1a\u6062\u590d\u771f\u5b9e\u8d44\u6599\u3002\u8bf7\u5728 VS Code \u4fa7\u680f\u4e2d\u6267\u884c\u3002")
              : undefined
          }
          />
        </Suspense>

      </section>
    );
  };

  const renderTrainingView = () => {
    const title = hasRenderableTrainingCard
      ? readTrainingCardText(boundTrainingCardFacts, "title", () => pickFirstText(
          visibleTrainingCardTitle,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : liveTrainingHandoffChrome.cardTitle,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : trainingState?.latestTrainingHandoff?.cardTitle,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : trainingState?.latestTrainingNextHop?.cardTitle,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : trainingState?.latestTrainingNextHop?.title,
          liveTrainingTitle,
          formalPlanLive || liveTask ? resolvedCoachFocus : undefined,
        )) ?? trainingViewLabel(layout.composerLanguage)
      : trainingViewLabel(layout.composerLanguage);
    const currentStep = hasRenderableTrainingCard
      ? boundTrainingCardFacts
        ? boundTrainingCardFacts.text.problemStatement ??
          boundTrainingCardFacts.text.suggestedWorkspaceAction ??
          boundTrainingCardFacts.text.deliverable ?? ""
        : pickFirstText(
          trainingProblemStatement,
          trainingSuggestedWorkspaceAction,
          trainingDeliverables[0],
          selectedTrainingCardCandidate?.deliverable,
          selectedTrainingRouteCard?.deliverable,
        ) ?? ""
      : "";
    const localizedSuggestedWorkspaceAction = hasRenderableTrainingCard
      ? readTrainingCardText(boundTrainingCardFacts, "suggestedWorkspaceAction", () => trainingSuggestedWorkspaceAction)
      : undefined;
    const localizedScenario = hasRenderableTrainingCard
      ? boundTrainingCardFacts
        ? boundTrainingCardFacts.text.scenario ?? boundTrainingCardFacts.text.scenarioPack
        : pickFirstText(
          trainingScenario,
          trainingScenarioPackLabel,
        )
      : undefined;
    const localizedWhyNow = hasRenderableTrainingCard
      ? readTrainingCardText(boundTrainingCardFacts, "whyNow", () => liveTrainingWhy)
      : undefined;
    const localizedSourceSummary = hasRenderableTrainingCard
      ? pickFirstText(leftoverTrainingHandoffChromeNotLive
            ? undefined
            : liveTrainingHandoffChrome.handoffSummary,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : trainingState?.latestTrainingHandoff?.handoffSummary,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : liveTrainingHandoffChrome.nextHopHandoffSummary,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : trainingState?.latestTrainingNextHop?.handoffSummary,
          liveTrainingCoachChrome,
          liveTrainingSource,
        )
      : undefined;
    const localizedCurrentFocus = hasTrainingCard
      // A matching card's technical focus remains authoritative across locale
      // changes, including a settings refresh that clears the recovered flag.
      ? readTrainingCardText(boundTrainingCardFacts, "focusArea", () => pickFirstText(
          selectedTrainingCardCandidate && selectedTrainingCardCandidate.cardId === activeTrainingCardId
            ? selectedTrainingCardCandidate.focusArea : undefined,
          selectedTrainingRouteCard && selectedTrainingRouteCard.cardId === activeTrainingCardId
            ? selectedTrainingRouteCard.focusArea : undefined,
        ) ?? pickFirstText(
          leftoverTrainingFocusChromeNotLive ? undefined : liveTrainingFocusChrome.latestLearningFocusArea,
          leftoverTrainingFocusChromeNotLive ? undefined : liveTrainingFocusChrome.cardFocusArea,
          leftoverTrainingFocusChromeNotLive
            ? undefined
            : liveTrainingFocusChrome.teachingDecisionFocusArea,
          leftoverTrainingFocusChromeNotLive
            ? undefined
            : liveTrainingFocusChrome.learnerStateActiveFocus,
          liveTrainingCurrentFocus,
          liveTrainingFocus,
        ) ?? pickFirstText(
          liveTrainingCurrentFocus,
          liveTrainingFocus,
        ))
      : undefined;

    return (
      <section className="training-view">
        <Suspense fallback={<ViewFallback label={t.training} language={layout.composerLanguage} />}>
          <TrainingWorkbenchView
          language={layout.composerLanguage}
          cardType={trainingCardType}
          trainingSubmode={effectiveTrainingSubmode}
          cardOnly={true}
          response={resolvedReviewArtifact ? (
            <SystemState kind="success" title={templateCopy[layout.composerLanguage].reviewRecorded}
              detail={trainingState?.reviewArtifact?.verifiedResult ?? trainingState?.reviewArtifact?.summary}
              action={{ label: templateCopy[layout.composerLanguage].askCoach, onClick: handleResumeTrainingInCoach }} />
          ) : hasTrainingCard && !leftoverTrainingHandoffChromeNotLive && !trainingComposerReturnMode ? (
            <PracticeResponse
              attachmentScope={`${attachmentScope}\u0000${activeTrainingCardId ?? ""}\u0000${trainingComposerPhase}`}
              label={localizedTrainingComposerAccessibilityLabel}
              prompt={reviewArtifactForeground ? trainingState?.reviewArtifact?.summary : trainingComposerReflectMode ? readTrainingCardText(boundTrainingCardFacts, "reflectionPrompt", () => trainingReflectionPrompt) : undefined}
              value={activityDraft}
              language={layout.composerLanguage}
              attachments={activityAttachments}
              onAttachmentsChange={setActivityAttachments}
              attachmentsAvailable={providerImageInputState.supported && !trainingComposerReflectMode}
              attachmentError={providerImageInputState.detail ?? providerImageInputState.reason}
              submitLabel={trainingComposerReflectMode ? templateCopy[layout.composerLanguage].recordReflection : templateCopy[layout.composerLanguage].submitAnswer}
              busy={trainingPersistencePending || streaming.isStreaming}
              disabled={workspaceSessionBlocked}
              onChange={setActivityDraft}
              onSubmit={(value) => { void handleSubmit(value); }}
            >
              {renderTrainingComposerAccessory()}
            </PracticeResponse>
          ) : null}
          cardId={activeTrainingCardId}
          selectedCardStatus={effectiveSelectedTrainingCardStatus}
          onCardStatusTransition={leftoverTrainingHandoffChromeNotLive ? undefined : handleTrainingCardStatusTransition}
          onVerifyCurrentFile={reviewArtifactForeground ? undefined : handleVerifyCurrentFileFromCard}
          remoteVerification={remoteVerification}
          onStopRemoteVerification={handleStopRemoteVerification}
          onHintReveal={handleHintReveal}
          card={{
            title,
            currentStep,
            learningFamily: trainingLearningFamily,
            learningSubtype: trainingLearningSubtype,
            whyThisCard: reviewArtifactForeground ? trainingState?.reviewArtifact?.guardrail : localizedWhyNow,
            targetSkill: readTrainingCardText(boundTrainingCardFacts, "targetSkill", () => liveTrainingSkill),
            problemStatement: readTrainingCardText(boundTrainingCardFacts, "problemStatement", () => trainingProblemStatement),
            suggestedWorkspaceAction: localizedSuggestedWorkspaceAction,
            scenario: localizedScenario,
            whyNow: reviewArtifactForeground ? trainingState?.reviewArtifact?.guardrail : localizedWhyNow,
            sourceSummary: localizedSourceSummary,
            sourceDetail:
              hasRenderableTrainingCard
                ? pickFirstText(leftoverTrainingHandoffChromeNotLive
                      ? undefined
                      : liveTrainingHandoffChrome.handoffSummary,
                    leftoverTrainingHandoffChromeNotLive
                      ? undefined
                      : trainingState?.latestTrainingHandoff?.handoffSummary,
                    leftoverTrainingHandoffChromeNotLive
                      ? undefined
                      : liveTrainingHandoffChrome.nextHopHandoffSummary,
                  )
                : undefined,
            apiHints: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardList(boundTrainingCardFacts, "apiHints", () => trainingApiHints) : [],
            selfCheck: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardList(boundTrainingCardFacts, "selfCheck", () => trainingSelfCheck) : [],
            deliverable: reviewArtifactForeground ? trainingState?.reviewArtifact?.summary : hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "deliverable", () => trainingDeliverable) : undefined,
            deliverables: reviewArtifactForeground ? selectedTrainingCardCandidate?.learnerDeliverables ?? [] : hasTrainingCard ? readTrainingCardList(boundTrainingCardFacts, "learnerDeliverables", () => trainingDeliverables) : [],
            validationMethod: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "validationMethod", () => trainingValidationMethod) : undefined,
            verificationMethod: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "verificationMethod", () => trainingVerificationMethod) : undefined,
            verifyItems: reviewArtifactForeground ? selectedTrainingCardCandidate?.verificationSteps ?? [] : hasTrainingCard ? boundTrainingCardFacts ? boundTrainingCardFacts.lists.verificationSteps ?? boundTrainingCardFacts.lists.acceptanceCriteria ?? [] : authoritativeVerifyItems : [],
            successSignal: reviewArtifactForeground ? trainingState?.reviewArtifact?.verifiedResult : hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "successSignal", () => trainingSuccessSignal) : undefined,
            returnWith: reviewArtifactForeground ? trainingState?.reviewArtifact?.nextSelfImplementationRule : hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "returnWith", () => trainingReturnWithText) : undefined,
            nextAfterCompletion: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "nextAfterCompletion", () => trainingNextAfterCompletionText) : undefined,
            fallbackAction: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "fallbackAction", () => trainingFallbackActionText) : undefined,
            filesToTouch: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardList(boundTrainingCardFacts, "filesToTouch", () => trainingFilesToTouch) : [],
            hintLadder: !reviewArtifactForeground && hasTrainingCard && !trainingComposerReturnMode ? readTrainingCardList(boundTrainingCardFacts, "hintLadder", () => trainingHintLadder) : [],
            commonMistakes: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardList(boundTrainingCardFacts, "commonMistakes", () => trainingCommonMistakes) : [],
            stuckRecovery: reviewArtifactForeground ? trainingState?.reviewArtifact?.guardrail : hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "stuckRecovery", () => trainingStuckRecovery) : undefined,
            outcome: !reviewArtifactForeground && hasTrainingCard ? trainingOutcomeCard : undefined,
            nextHop:
              hasRenderableTrainingCard && !trainingRestoreForeground && !reviewArtifactForeground
                ? trainingNextHopCard
                : undefined,
            flashPrompt: trainingFlashPrompt,
            expectedSymbols: trainingCardType === "practice" ? readTrainingCardList(boundTrainingCardFacts, "expectedSymbols", () => practiceExpectedSymbols) : [],
            scenarioPackLabel: hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "scenarioPack", () => trainingScenarioPackLabel) : undefined,
            currentFocus: localizedCurrentFocus,
          }}
          handoff={{
            latestTrainingHandoffStatus:
              reviewArtifactForeground || trainingRestoreReplacesSelectedCard
                ? undefined
                : trainingState?.latestTrainingHandoff?.handoffStatus,
            latestTrainingLearningPhase:
              reviewArtifactForeground || trainingRestoreReplacesSelectedCard
                ? selectedTrainingCardCandidate?.learningPhase
                : (trainingState?.latestTrainingHandoff?.learningPhase ??
                  selectedTrainingCardCandidate?.learningPhase),
            latestTrainingReliability:
              activeTrainingCardId && trainingState?.latestTrainingReliability?.cardId === activeTrainingCardId
                ? trainingState.latestTrainingReliability
                : undefined,
            reliabilityInFlight: trainingPersistencePending,
            latestTrainingNextHopStatus:
              reviewArtifactForeground || trainingRestoreReplacesSelectedCard
                ? undefined
                : trainingState?.latestTrainingNextHop?.status,
            latestTrainingNextHopReason:
              !reviewArtifactForeground &&
              !trainingRestoreReplacesSelectedCard &&
              trainingState?.latestTrainingNextHop?.status === "blocked"
                ? trainingState.latestTrainingNextHop.statusReason
                : undefined,
            latestTrainingBlockedBy:
              leftoverTrainingHandoffChromeNotLive ||
              reviewArtifactForeground ||
              trainingRestoreReplacesSelectedCard
                ? undefined
                : liveTrainingHandoffChrome.blocker ??
                  trainingState?.latestTrainingHandoff?.blockedBy,
            latestVerifiedResult:
              reviewArtifactForeground
                ? undefined
                : trainingRestoreReplacesSelectedCard
                ? undefined
                : trainingState?.latestLearningVerifiedResult,
            latestLearningBlocker:
              (reviewArtifactForeground ? trainingState?.reviewArtifact?.blockedReason : undefined) ??
              (leftoverTrainingHandoffChromeNotLive || reviewArtifactForeground || trainingRestoreReplacesSelectedCard
                ? undefined
                : pickFirstText(
                    liveTrainingHandoffChrome.blocker,
                    trainingState?.latestLearningBlocker,
                  ) || liveTrainingHandoffChrome.blocker || trainingState?.latestLearningBlocker || (
                    activeTrainingCardId && trainingState?.latestTrainingNextHop?.candidateId === activeTrainingCardId &&
                    trainingState?.latestTrainingNextHop?.status === "verification_required"
                      ? trainingState?.latestTrainingNextHop?.statusReason || trainingState?.latestTrainingNextHop?.summary
                      : undefined
                  )),
            verificationNotice: trainingVerifyNotice,
            latestLearningFollowup:
              leftoverTrainingHandoffChromeNotLive || reviewArtifactForeground || trainingRestoreReplacesSelectedCard
                ? undefined
                : pickFirstText(
                    liveTrainingHandoffChrome.followup,
                    trainingState?.latestLearningFollowup,
                  ),
          }}
          reviewItems={trainingReviewItems}
          onReviewQueueAction={(payload) => {
            if (payload.action === "accept") beginTrainingReview();
            handleReviewQueueAction(payload);
          }}
          reviewSummary={pickFirstText(
            formattedNextReviewDue,
            data.memory.reviewSummary,
          )}
          primaryAction={
            leftoverTrainingHandoffChromeNotLive ? (
              <button
                className="button button--accent"
                type="button"
                aria-label={t.openCoach}
                onClick={() => {
                  setActiveView("coach");
                  requestCoachComposerFocus();
                }}
              >
                {t.openCoach}
              </button>
            ) : trainingPrimaryAction
          }
          leftoverNote={leftoverTrainingHandoffChromeNotLive ? t.leftoverNotLive : undefined}
          actions={hasTrainingCard ? trainingCoachAction : undefined}
          emptyState={
            leftoverTrainingHandoffChromeNotLive ? undefined : (
            <SystemState kind={workspaceSessionBlocked ? "workspace-required" : "empty"} title={t.trainingEmptyTitle} detail={workspaceSessionBlockMessage || t.trainingEmptyDescription}
              action={{ label: workspaceSessionBlocked ? t.settings : t.startTraining, onClick: () => workspaceSessionBlocked ? openWorkspaceAdmission() : handleGenerateTrainingCard() }} />
            )
          }
          onNextCard={handleGenerateTrainingCard}
          />

        </Suspense>

      </section>
    );
  };

  // Domain controller owns priority; views receive one complete descriptor.
  const learningFacts: LearningFacts = {
    scope: {
      workspaceId: syncIdentity?.workspaceId ?? data.memory.workspace?.workspaceId ?? data.workspaceTrainingState?.workspaceId ?? composerSessionKey,
      sessionId: syncIdentity?.sessionId ?? data.sessionLabel,
      generation: String(syncIdentity?.generation ?? data.runtimeDataGeneration ?? "unversioned"),
    },
    language: layout.composerLanguage,
    workspace: { ready: !workspaceSessionBlocked, detail: workspaceSessionBlockMessage },
    provider: {
      ready: providerCanCoachNow,
      canGeneratePlan: providerCanMutateFormalPlan,
      detail: providerCanCoachNow ? formalPlanCapabilityMessage : providerBlockReason ?? providerSetupState.detail,
    },
    freshness: syncStatus,
    // An idle sidecar starts on demand; a verified provider still permits work.
    connection: data.connection.state === "connected" ||
      (data.connection.state === "offline" && providerCanCoachNow)
        ? "ready" : data.connection.state === "starting" ? "recovering" : "offline",
    connectionRecovery: {
      title: providerSetupState.title,
      label: t.openSettings,
      detail: providerSetupState.detail,
    },
    plan: {
      state: hasFormalPlan ? livePlanFrozen ? "frozen" : "active" : "absent",
      id: formalPlanLive ? data.plan.id : undefined,
      revision: formalPlanLive ? data.plan.revision : undefined,
      currentStep: verifyPlanAdvanceNext || recoveredDisplayFacts.currentStep ||
        (!recoveredRuntime ? liveCoachTaskChrome.currentStep || resolvedCoachNextStep : undefined),
      blocker: recoveredDisplayFacts.blockedReason,
      completion: planVerifyItems,
    },
    evidence: {
      pending: liveEvidenceQueue.pending.map(item => ({
        id: item.id, summary: item.summary, source: item.source,
        sourceCardId: item.sourceCardId, verified: item.verified,
        verificationSource: item.verificationSource, outcome: item.outcome,
      })),
      blockingId: planRuntimeStatus?.resumeState === "waiting"
        ? liveEvidenceBinding({ binding: data.memory.workspace?.latestPlanRuntime?.evidenceBinding,
            pendingIds: liveEvidenceQueue.pending.map(item => item.id), recovered: recoveredRuntime,
            currentStep: recoveredDisplayFacts.currentStep }) || undefined
        : undefined,
    },
    training: hasTrainingCard && activeTrainingCardId
      ? {
          workspaceId: trainingState?.workspaceId ?? data.memory.workspace?.workspaceId ?? "",
          cardId: activeTrainingCardId,
          title: readTrainingCardText(boundTrainingCardFacts, "title", () => visibleTrainingCardTitle ?? selectedTrainingCardCandidate?.title) ?? trainingViewLabel(layout.composerLanguage),
          status: normalizedTrainingNextHopStatus === "continued_in_chat" || resolvedReviewArtifact
            ? "completed" : trainingHandoffReturnRequired || trainingComposerReturnMode
              ? "return_pending" : "active",
        }
      : undefined,
    dueReview: planReviewItems.find(item => item.surfaceMode === "due"),
    firstLookStep: !recoveredRuntime ? liveFirstLookSummary?.recommendedNextStep : undefined,
    operationPending: streaming.isStreaming || trainingPersistencePending || Boolean(pendingLivePlanTaskMintRef.current),
  };
  const learningFactsRef = useRef(learningFacts);
  learningFactsRef.current = learningFacts;
  const learningPrimaryAction = resolveLearningPrimaryAction(learningFacts);
  const runLearningPrimaryAction = () => executeLearningPrimaryAction(
    learningPrimaryAction, learningFactsRef.current, {
      chooseWorkspace: openWorkspaceAdmission,
      configureProvider: openProviderSetup,
      restoreState: () => postMessage({ type: "request/bootstrap" }),
      openTraining: () => setActiveView("training"),
      resumePlan: () => handlePlanOrientationAction("unfreeze_plan"),
      resolveBlocker: () => handlePlanOrientationAction("clear_blocker"),
      adoptEvidence: (evidenceId) => postMessage({ type: "command/execute", payload: {
        commandId: trainerCommands.evidenceAdopt, payload: { evidenceId },
      } }),
      continueStep: (step) => {
        if (planRuntimeStatus?.recovered && planRuntimeStatus.currentStep?.trim() === step) {
          handlePlanOrientationAction("continue_step");
        } else {
          requestPlanComposerGuidance(step, "stage");
        }
      },
      continueWithoutPlan: () => handlePlanOrientationAction("continue_without_plan"),
      startReview: () => useWorkbenchState.getState().openTrainingReviewQueue(),
      returnToCoach: handleResumeTrainingInCoach,
      generatePlan: () => handlePlanOrientationAction("generate_plan"),
      confirmStep: () => openPlanComposerMode("explain"),
    },
  );
  const learningPracticeReadyToContinue = Boolean(
    boundTrainingCardFacts && trainingCardType === "practice" && recoveredRuntime &&
    syncStatus === "current" && learningPrimaryAction.intent === "resume_training" &&
    learningPrimaryAction.target.cardId === boundTrainingCardFacts.cardId &&
    !learningPrimaryAction.disabled && !learningPrimaryAction.busy,
  );
  const renderPlanView = () => (
    <section className="plan-view">
      <Suspense fallback={<ViewFallback label={t.plan} language={layout.composerLanguage} />}>
        <CoachPlanView
        plan={workspaceSessionBlocked ? null : visibleFormalPlan}
        dockReturnNotice={dockReturnNotice === "plan" ? (
          <DockReturnToSurfaceBar
            language={layout.composerLanguage}
            surface="plan"
            onViewReply={handleDockReturnViewReply}
            onDismiss={handleDockReturnDismiss}
          />
        ) : undefined}
        primaryAction={{
          label: templateCopy[layout.composerLanguage].nextAction,
          title: learningPrimaryAction.title,
          detail: <div data-plan-fact="next">{learningPrimaryAction.detail}</div>,
          action: { id: learningPrimaryAction.intent, label: learningPrimaryAction.label,
            disabled: learningPrimaryAction.disabled, busy: learningPrimaryAction.busy,
            onClick: runLearningPrimaryAction },
        }}
        primaryEvidenceId={learningPrimaryAction.target.evidenceId}
        projection={data.workspaceTrainingState?.skillProjection}
        onNavigateToView={setActiveView}
        className="plan-pane"
        compactPrimary
        onExpandToEditor={canOpenInEditor ? () => openViewInEditor("plan") : undefined}
        expandToEditorLabel={expandToEditorLabel}
        leftoverNote={leftoverPlanNotLive
          ? learningPracticeReadyToContinue
            ? templateCopy[layout.composerLanguage].practiceReadyToContinue
            : t.leftoverNotLive
          : undefined}
        eyebrow=""
        title={
          workspaceSessionBlocked || !hasFormalPlan
            ? t.plan
            : formalPlanLive
              ? data.plan.title
              : livePlanTitle
        }
        titleNote={undefined}
        composerDraftReplacement={
          pendingPlanComposerDraftReplacement
            ? {
                source: pendingPlanComposerDraftReplacement.source,
                ...planComposerDraftReplacementCopy(
                  layout.composerLanguage,
                  pendingPlanComposerDraftReplacement.targetTitle,
                ),
                onConfirm: confirmPlanComposerDraftReplacement,
                onCancel: cancelPlanComposerDraftReplacement,
              }
            : undefined
        }
        goalLabel={t.currentFocus}
        goalSummary={
          // Stage/plan-level objective only. The concrete next-step sentence is
          // owned by the nextStep prop below — never duplicated here.
          <p>{resolvedCoachFocus || activeStageObjectiveText(activePlanStage, livePlanSummary)}</p>
        }
        liveStageIsCurrent={liveStageChrome.stageIsCurrent}
        goalHint={planText.goalHint}
        emptyState={
          <p className="muted">
            {planText.emptyState(coachViewLabel(layout.composerLanguage))}
          </p>
        }
        overviewLabel={planText.overviewLabel}
        currentStageLabel={planText.currentStageLabel}
        currentStageHint={planText.currentStageHint}
        nextStepLabel={t.currentTask}
        nextStepHint={planText.nextStepHint}
        stagesLabel={planText.stagesLabel}
        coachingStateLabel={t.coachState}
        pathLabel={planText.pathLabel}
        pathHint={planText.pathHint}
        whyNowLabel={planText.whyNowLabel}
        verifyLabel={t.acceptance}
        reviewWindowLabel={planText.reviewWindowLabel}
        planAtGlanceLabel={t.currentFocus}
        planAtGlanceHint={planText.planAtGlanceHint}
        stageProgressLabel={planText.stageProgressLabel}
        reviewQueueCountLabel={planText.reviewQueueCountLabel}
        currentFocusLabel={t.currentFocus}
        reviewFocusLabel={planText.reviewFocusLabel}
        pathSummaryLabel={planText.pathSummaryLabel}
        pathSummaryHint={planText.pathSummaryHint}
        returnLabel={planText.returnLabel}
        nowLabel={t.nextMove}
        revisitSummaryLabel={planText.revisitSummaryLabel}
        reviewLabel={planText.reviewLabel}
        weakSpotsLabel={t.weakSpots}
        winsLabel={t.recentWins}
        teachingObservationsLabel={t.teachingObservations}
        supportSummaryLabel={planText.supportSummaryLabel}
        supportHint={planText.supportHint}
        rememberedSummaryLabel={planText.rememberedSummaryLabel}
        notesLabel={planText.notesLabel}
        stageStatusLabels={{
          done: t.stageDone,
          active: t.stageActive,
          queued: t.stageQueued,
        }}
        actions={[
          {
            id: "plan-ask-coach",
            label: templateCopy[layout.composerLanguage].askCoach,
            tone: "ghost" as const,
            onClick: () => openPlanComposerMode("explain"),
          },
          {
            id: "plan-adjust",
            label: templateCopy[layout.composerLanguage].adjustPlan,
            tone: "ghost" as const,
            disabled: !providerCanMutateFormalPlan,
            detail: providerCanMutateFormalPlan ? undefined : formalPlanCapabilityMessage,
            onClick: () => openPlanComposerMode("generate"),
          },
          ...(liveEvidenceQueue.pending.length > 0 && formalPlanLive && !livePlanFrozen && !workspaceSessionBlocked
            ? [{ id: "plan-ask-evidence", tone: "ghost" as const,
                label: resolvePlanComposerCopy(layout.composerLanguage).modes.evidence.primaryPrompt.label,
                disabled: !providerCanCoachNow || syncStatus !== "current",
                onClick: () => openPlanComposerMode("evidence") }]
            : []),
          ...(!hasFormalPlan || !livePlanFrozen
            ? [{ id: "refresh-plan", label: t.generatePlan, tone: "ghost" as const,
                disabled: !providerCanMutateFormalPlan || workspaceSessionBlocked || syncStatus !== "current",
                detail: providerCanMutateFormalPlan ? undefined : formalPlanCapabilityMessage,
                onClick: () => handlePlanOrientationAction("generate_plan") }]
            : []),
          ...(hasFormalPlan && formalPlanLive && !livePlanFrozen
            ? [{ id: "plan-next-task", label: planText.nextTaskLabel, tone: "ghost" as const,
                disabled: !providerCanCoachNow || workspaceSessionBlocked || syncStatus !== "current",
                onClick: () => {
                  setActiveView("coach");
                  setComposerDraft(
                    defaultPromptText("next_task", layout.composerLanguage, activePlanStage?.title),
                  );
                  requestCoachComposerFocus();
                }, }]
            : []),
          ...(hasFormalPlan && formalPlanLive && !livePlanFrozen && !workspaceSessionBlocked
            ? [
                {
                  id: livePlanFrozen ? "resume-plan" : "freeze-plan",
                  label: livePlanFrozen ? appUiCopy(layout.composerLanguage, "解冻计划") : t.planFreeze,
                  tone: "ghost" as const,
                  onClick: () => {
                    pendingLivePlanTaskMintRef.current = {
                      commandId: trainerCommands.updatePlan,
                    };
                    setOperationMessage({
                      tone: "info",
                      message: livePlanUpdatePendingMessage(layout.composerLanguage),
                    }, "plan");
                    postMessage({
                      type: "plan/freeze",
                      payload: { frozen: !livePlanFrozen },
                    });
                  },
                },
              ]
            : []),
        ]}
        onStageSelect={(stage) => {
          requestPlanComposerGuidance(stage.title, "stage");
        }}
        nextStep={
          <>
            <p>
              {verifyPlanAdvanceNext ||
                (learningFacts.plan.currentStep || learningFacts.firstLookStep || latestArtifactTeaser)}
            </p>
            {runtimeBlockedReason ? (
              <p className="inline-note">{runtimeBlockedReason}</p>
            ) : null}
          </>
        }
        whyNow={
          <>
            <p>{planWhyNow || (recoveredRuntime ? planOrientation.why : undefined)}</p>
            {recoveredRuntime ? null : liveCoachTaskChrome.scopeBoundary ? (
              <p className="inline-note">{liveCoachTaskChrome.scopeBoundary}</p>
            ) : latestCoachArtifact?.focusArea ? (
              <p className="inline-note">{latestCoachArtifact.focusArea}</p>
            ) : runtimeCurrentStage?.goal ? (
              <p className="inline-note">{runtimeCurrentStage.goal}</p>
            ) : liveCoachStage ? (
              <p className="inline-note">{liveCoachStage}</p>
            ) : null}
          </>
        }
        verifyNow={
          planVerifyItems.length ? (
            <ul className="coach-plan-inline-list">
              {planVerifyItems.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : liveCoachTurnChrome.evaluationNextStep ? (
            <p>{liveCoachTurnChrome.evaluationNextStep}</p>
          ) : undefined
        }
        returnPath={<p>{planReturnPathLead}</p>}
        reviewWindow={
          <>
            <p>{runtimeNextAfterCurrent || planReviewWindowLead}</p>
            {runtimeNextAfterCurrent && planReviewReason ? (
              <p className="inline-note">{planReviewReason}</p>
            ) : !runtimeNextAfterCurrent && planReviewReason ? (
              <p className="inline-note">{planReviewReason}</p>
            ) : null}
          </>
        }
        coachingStateSummary={
          resolvedCoachStateSummary ? (
            <div className="coach-plan-view__signal-feed">
              {resolvedCoachStateSummary ? (
                <div className="coach-plan-view__support-feed-item">
                  <p>{resolvedCoachSummary ?? resolvedCoachStateSummary.split("\n").filter(Boolean)[0]}</p>
                </div>
              ) : null}
            </div>
          ) : undefined
        }
        rememberedSummary={rememberedCoachSummary}
        memorySummary={undefined}
        reviewRhythm={undefined}
        detailsSummaryLabel={planText.detailsSummaryLabel}
        dueReviewItems={planReviewItems}
        dueReviewSummaryLabel={planText.dueReviewItems(planReviewItems.length)}
        teachingObservations={data.memory.teachingObservations.slice(0, 3)}
        weakSpots={data.memory.weakSpots.slice(0, 3)}
        recentWins={data.memory.recentWins.slice(0, 3)}
        trajectoryLabel={planText.trajectoryLabel}
        trajectoryItems={(data.projectSources ?? []).slice(0, 3).map((source) => ({
          id: source.sourceUrl || source.title,
          label: source.title,
          value: source.repoHint || source.sourceUrl,
          detail: source.fitReason || source.trainingValue,
        }))}
        globalPlan={data.globalPlan}
        projectPlanLink={data.projectPlanLink}
        onCreateGlobalPlan={
          isBrowserPreview
            ? undefined
            : () =>
                postMessage({
                  type: "command/execute",
                  payload: { commandId: trainerCommands.createGlobalPlan },
                })
        }
        onLinkCurrentProjectPlan={
          isBrowserPreview
            ? undefined
            : () =>
                postMessage({
                  type: "command/execute",
                  payload: { commandId: trainerCommands.linkCurrentProjectPlan },
                })
        }
        projectSubplans={(data.memory.subplans ?? []).map((subplan) => {
          const activeStage =
            subplan.stages.find((stage) => stage.status === "active") ?? subplan.stages[0];
          return {
            id: subplan.id,
            title: subplan.title,
            status:
              subplan.status === "active"
                ? ("active" as const)
                : subplan.status === "draft"
                  ? ("pending" as const)
                  : ("frozen" as const),
            nextStep: activeStage?.objective,
            frozenReason:
              subplan.status === "completed"
                ? planText.subplanComplete
                : subplan.status === "archived"
                  ? planText.subplanArchived
                  : undefined,
          };
        })}
        projectSubplansLabel={planText.projectSubplansLabel}
        onProjectSubplanSelect={(subplan) => {
          requestPlanComposerGuidance(subplan.title, "project-subplan");
        }}
        evidenceQueue={liveEvidenceQueue}
        planChangeCandidates={data.memory.planChangeCandidates}
        evidenceActions={{
          onRefreshQueue: () =>
            postMessage({
              type: "command/execute",
              payload: { commandId: trainerCommands.evidenceRefreshQueue },
            }),
          onAdoptEvidence: (evidenceId) =>
            postMessage({
              type: "command/execute",
              payload: {
                commandId: trainerCommands.evidenceAdopt,
                payload: { evidenceId },
              },
            }),
          onDeferEvidence: (evidenceId, reason) =>
            postMessage({
              type: "command/execute",
              payload: {
                commandId: trainerCommands.evidenceDefer,
                payload: { evidenceId, reason },
              },
            }),
          onRejectEvidence: (evidenceId, reason) =>
            postMessage({
              type: "command/execute",
              payload: {
                commandId: trainerCommands.evidenceReject,
                payload: { evidenceId, reason },
              },
            }),
        }}
        />
        </Suspense>
    </section>
  );

  const renderSettingsView = () => (
    <section className="settings-view">
      <Suspense fallback={<ViewFallback label={t.settings} language={layout.composerLanguage} />}>
        <CoachSettingsView
          sectionRequest={settingsSectionRequest}
          skillSharing={renderSkillSharing()}
        companionInstallState={companionInstallState}

        capabilityVerdict={capabilityVerdict}
        providerImageInputState={providerImageInputState}
        providerStatus={providerStatus}
        coachDefaultsStatus={coachDefaultsStatus}
        workspaceControlStatus={workspaceControlStatus}
        coachStateSummary={resolvedCoachStateSummary}
        reviewRhythmSummary={resolvedCoachReview}
        onCoachSettingsMutated={queueCoachSettingsSave}
        onSaveCoachSettings={() => persistCoachSettings()}
        onSaveProvider={saveProviderDraft}
        onSaveProviderProfile={() => {
          setSettingsActionState({
            kind: "save-provider",
            targets: ["provider"],
            baselineMessageKey:
              normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
          });
          if (isBrowserPreview) {
            void loadBrowserPreviewModule()
              .then((browserPreview) =>
                browserPreview.saveBrowserPreviewProviderProfile(providerSavePayload, previewSessionId),
              )
              .then(({ sessionId, messages }) => {
                setPreviewSessionId(sessionId);
                applyPreviewHostMessages(messages, true);
              })
              .catch(() => {
                setOperationMessage({
                  tone: "error",
                  message: recoverableFailureMessage("provider", layout.composerLanguage),
                });
              });
            return;
          }
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.saveProviderProfile,
              payload: providerSavePayload,
            },
          });
        }}
        onUseProviderTemplateLabel={useProviderTemplateByLabel}
        onRefreshProviderProfiles={() => {
          setSettingsActionState({
            kind: "refresh-provider-models",
            targets: ["provider"],
            baselineMessageKey:
              normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
          });
          if (isBrowserPreview) {
            void loadBrowserPreviewModule()
              .then((browserPreview) =>
                browserPreview.refreshBrowserPreviewProviderProfiles(previewSessionId),
              )
              .then(({ sessionId, messages }) => {
                setPreviewSessionId(sessionId);
                applyPreviewHostMessages(messages, true);
              })
              .catch(() => {
                setOperationMessage({
                  tone: "error",
                  message: recoverableFailureMessage("provider", layout.composerLanguage),
                });
              });
            return;
          }
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.refreshProviderProfiles,
            },
          });
        }}
        onSwitchProviderProfile={(profileId) => {
          setSettingsActionState({
            kind: "save-provider",
            targets: ["provider"],
            baselineMessageKey:
              normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
          });
          if (isBrowserPreview) {
            void loadBrowserPreviewModule()
              .then((browserPreview) =>
                browserPreview.switchBrowserPreviewProviderProfile(profileId, previewSessionId),
              )
              .then(({ sessionId, messages }) => {
                setPreviewSessionId(sessionId);
                applyPreviewHostMessages(messages, true);
              })
              .catch(() => {
                setOperationMessage({
                  tone: "error",
                  message: recoverableFailureMessage("provider", layout.composerLanguage),
                });
              });
            return;
          }
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.switchProviderProfile,
              payload: {
                profileId,
                reason: "settings_switch",
              },
            },
          });
        }}
        providerSaveBusy={settingsActionState?.kind === "save-provider"}
        onRefreshProviderModels={() => {
          const shouldUseDraft = providerDraftHasChanges || !data.providerConfig.configured;
          setSettingsActionState({
            kind: "refresh-provider-models",
            targets: ["provider"],
            baselineMessageKey:
              normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
          });
          if (isBrowserPreview) {
            void loadBrowserPreviewModule()
              .then((browserPreview) =>
                browserPreview.refreshBrowserPreviewProviderModels(
                  shouldUseDraft ? providerSavePayload : undefined,
                  previewSessionId,
                ),
              )
              .then(({ sessionId, messages }) => {
                setPreviewSessionId(sessionId);
                applyPreviewHostMessages(messages, true);
              })
              .catch(() => {
                setOperationMessage({
                  tone: "error",
                  message: recoverableFailureMessage("provider", layout.composerLanguage),
                });
              });
            return;
          }
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.refreshProviderModels,
              ...(shouldUseDraft ? { payload: { draft: providerSavePayload } } : {}),
            },
          });
        }}
        onTestProvider={() => {
          setSettingsActionState({
            kind: "test-provider",
            targets: ["provider"],
            baselineMessageKey:
              normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
          });
          if (isBrowserPreview) {
            void loadBrowserPreviewModule()
              .then((browserPreview) =>
                browserPreview.testBrowserPreviewProvider(
                  providerDraftHasChanges ? providerSavePayload : undefined,
                  previewSessionId,
                ),
              )
              .then(({ sessionId, messages }) => {
                setPreviewSessionId(sessionId);
                applyPreviewHostMessages(messages, true);
              })
              .catch(() => {
                setOperationMessage({
                  tone: "error",
                  message: recoverableFailureMessage("provider", layout.composerLanguage),
                });
              });
            return;
          }
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.testProvider,
              payload: {
                responseLanguage: layout.composerLanguage,
                ...(providerDraftHasChanges ? { draft: providerSavePayload } : {}),
              },
            },
          });
        }}
        onRestartSidecar={
          isBrowserPreview
            ? undefined
            : () =>
                postMessage({
                  type: "command/execute",
                  payload: { commandId: trainerCommands.restartSidecar },
                })
        }
        onClearProvider={() => {
          setSettingsActionState({
            kind: "clear-provider",
            targets: ["provider"],
            baselineMessageKey:
              normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
          });
          if (isBrowserPreview) {
            void loadBrowserPreviewModule()
              .then((browserPreview) =>
                browserPreview.clearBrowserPreviewProvider(previewSessionId),
              )
              .then(({ sessionId, messages }) => {
                setPreviewSessionId(sessionId);
                applyPreviewHostMessages(messages, true);
              })
              .catch(() => {
                setOperationMessage({
                  tone: "error",
                  message: recoverableFailureMessage("provider", layout.composerLanguage),
                });
              });
            return;
          }
          postMessage({
            type: "command/execute",
            payload: { commandId: "trainer.provider.clear" },
          });
        }}
        onOpenConfig={() => {
          setSettingsActionState({
            kind: "open-config",
            targets: ["provider"],
            baselineMessageKey:
              normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
          });
          if (isBrowserPreview) {
            setOperationMessage({
              tone: "info",
              message:
                appUiCopy(layout.composerLanguage, "浏览器预览没有工作区配置文件入口。这个按钮只在 VS Code 侧栏里可用。"),
            });
            return;
          }
          postMessage({
            type: "command/execute",
            payload: { commandId: "trainer.config.openWorkspace" },
          });
        }}
        onResetDefaults={() => {
          const defaultLanguage =
            typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("zh")
              ? "zh-CN"
              : "en-US";
          setSettingsActionState({
            kind: "reset-defaults",
            targets: ["coachDefaults", "workspaceControl"],
            baselineMessageKey:
              normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
          });
          setThemePreference("system");
          setComposerLanguage(defaultLanguage);
          setComposerAnswerMode(DEFAULT_ANSWER_MODE);
          setTeachingStyle(DEFAULT_TEACHING_STYLE);
          setFollowCurrentFile(true);
          setContextDetail("balanced");
          setIncludeCurrentFile(true);
          setIncludeSelection(true);
          setIncludeDiagnostics(true);
          setIncludeRelatedFiles(true);
          setCoachDefaults(defaultCoachDefaults);
          persistCoachSettings({
            responseLanguage: defaultLanguage,
            answerMode: DEFAULT_ANSWER_MODE,
            teachingStyle: DEFAULT_TEACHING_STYLE,
            followCurrentFile: true,
            contextDetail: "balanced",
            includeCurrentFile: true,
            includeSelection: true,
            includeDiagnostics: true,
            includeRelatedFiles: true,
            coachDefaults: defaultCoachDefaults,
          });
          setOperationMessage({
            tone: "success",
            message:
              appUiCopy(defaultLanguage, "已恢复教练默认设置。"),
          });
        }}
        />
      </Suspense>
      {renderContextualResultRail("settings")}
    </section>
  );

  const renderProgressView = () => (
    <section className="progress-view-section">
      <Suspense fallback={<ViewFallback label={t.progress} language={layout.composerLanguage} />}>
        <ProgressView
          language={layout.composerLanguage}
          projection={data.workspaceTrainingState?.skillProjection}
          onOpenTraining={() => setActiveView("training")}
          onBack={() => setActiveView("plan")}
        />
      </Suspense>
    </section>
  );

  const renderWorkbenchSurface = (view: ActiveWorkbenchView) => {
    switch (view) {
      case "plan": return renderDockedView("plan", renderPlanView());
      case "resources": return renderDockedView("resources", renderResourcesView());
      case "training": return renderDockedView("training", renderTrainingView());
      case "progress": return renderDockedView("progress", renderProgressView());
      case "settings": return renderDockedView("settings", renderSettingsView());
      default: return renderCoachRootView();
    }
  };

  const workbenchShell = (
      <AppShell
        language={layout.composerLanguage}
        direction={uiDirection}
        activeView={activeView}
        context={data.workspaceName}
        historyOpen={openMenu === "history"}
        onHistory={toggleComposerHistoryMenu}
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
              onNewChat={startNewCoachChat}
              onClose={() => setOpenMenu(undefined)}
            />
        </UtilityOverlay>
      ) : null}

      {operationMessage && operationMessageVisible ? (
        <div className="template-global-state">
          <SystemState kind={operationMessage.tone === "error" ? "recoverable-error" : operationMessage.tone === "success" ? "success" : "information"}
            title={sanitizeErrorSurfaceText(operationStatusMessageText(operationMessage, layout.composerLanguage), layout.composerLanguage)}>
            {operationMessage.tone === "error" ? <button type="button" className="template-back" aria-label={appUiCopy(layout.composerLanguage, "关闭提示")} onClick={dismissOperationMessage}>×</button> : null}
          </SystemState>
        </div>
      ) : null}

      <main
        className={`view-content${activeView === "coach" ? "" : " view-content--docked"}`}
        ref={viewContentRef}
      >
        {hasReceivedHostState || isBrowserPreview ? (
          <WorkbenchSurfaces key={surfaceInstanceKey} activeView={activeView} render={renderWorkbenchSurface} />
        ) : (
          <SystemState kind="loading" title={appUiCopy(layout.composerLanguage, "正在加载{v}…").replace("{v}", "Trainer")} />
        )}
      </main>

      {showComposerShell ? (
      <footer className="composer-shell composer-shell--quiet">
          <div ref={composerShellRef}>
            {showComposerPresenceBar ? (
              <div className="composer-presencebar">
                {showComposerProviderPill ? (
                  <button
                    className={`composer-presencebar__provider ${
                      openMenu === "model" ? "is-active" : ""
                    }`.trim()}
                    type="button"
                    title={[composerModelButtonTitle, composerPresenceProviderDetail]
                      .filter(Boolean)
                      .join(" · ")}
                    aria-label={composerModelButtonTitle}
                    aria-expanded={openMenu === "model"}
                    onClick={toggleComposerModelMenu}
                  >
                    <span>{composerPresenceProviderCaption}</span>
                    <strong>{composerModelButtonDisplayLabel}</strong>
                  </button>
                ) : null}
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

            {!composerUsesTrainingFlow && activeView === "coach" && resourceConversationContextLabel ? (
              <div
                className="composer-presencebar"
                aria-label={resourceConversationContextLabel}
                role="group"
              >
                <div className="composer-presencebar__context">
                  <div className="composer-presencebar__copy">
                    <strong>{appUiCopy(layout.composerLanguage, "资料上下文")}</strong>
                    <span>{resourceConversationContextLabel}</span>
                  </div>
                </div>
                <div className="composer__buttons">
                  <button
                    className="button button--ghost composer-secondary-button"
                    type="button"
                    onClick={() => {
                      setSelectedResourceContextIds([]);
                      setResourceConversationContextIds([]);
                    }}
                  >
                    <span className="composer-secondary-button__label">
                      {appUiCopy(layout.composerLanguage, "清除")}
                    </span>
                  </button>
                </div>
              </div>
            ) : null}

            {coachPlanContext ? <div className="template-context" role="group">
              <span>{resolvePlanComposerCopy(layout.composerLanguage).modes[coachPlanContext].label}</span>
              <button type="button" className="template-back" onClick={() => setCoachPlanContext(undefined)}>{appUiCopy(layout.composerLanguage, "清除")}</button>
            </div> : null}
            {dockAnchorControl.anchor && activeView !== "coach" ? <div className="template-context" role="group" data-dock-anchor="true">
              <span>{dockAnchorControl.anchor.label}</span>
              <button type="button" className="template-back" onClick={dockAnchorControl.suppress}>{appUiCopy(layout.composerLanguage, "清除")}</button>
            </div> : null}
            {activeView === "plan" || activeView === "resources" ? (
              <DockSendPreferenceSwitch
                language={layout.composerLanguage}
                value={normalizeDockSendPreference(layout.composerSendPreference)}
                onChange={setComposerSendPreference}
              />
            ) : null}
            {coachSuggestionChips}
            <CoachComposer
              attachmentScope={attachmentScope}
              value={allowEmptyTrainingReturnSubmission ? "" : draft}
              onChange={handleComposerDraftChange}
              onSubmit={handleSubmit}
              onCancel={handleCancelStream}
              onNavigateHistory={navigateComposerHistory}
              density={composerModelActionDensity}
              placeholder={
                workspaceSessionBlocked && !canCaptureGoalBeforeWorkspaceSetup
                  ? workspaceSessionBlockMessage ?? ""
                  : activeView !== "coach" && !normalizedDraft
                    ? resolvedCompactUtilityComposerPlaceholder
                    : blockedComposerFallback
              }
              disabled={workspaceSessionBlocked && !canCaptureGoalBeforeWorkspaceSetup}
              submitDisabled={
                canCaptureGoalBeforeWorkspaceSetup
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
              submitAriaLabel={localizedTrainingComposerSubmitAriaLabel}
              emptySubmitAriaLabel={
                !trainingComposerTalkMode && composerUsesTrainingFlow && trainingComposerReflectMode
                  ? trainingHandoffComposerTextCopy.reflectEmptySubmitAriaLabel
                  : undefined
              }
              allowEmptySubmit={allowEmptyTrainingReturnSubmission}
              inputReadOnly={allowEmptyTrainingReturnSubmission}
              language={layout.composerLanguage}
              minRows={2}
              summary={
                activeView === "coach" || allowEmptyTrainingReturnSubmission
                  ? localizedTrainingComposerSummary
                  : undefined
              }
              hintText={activeView === "coach" && !composerUsesTrainingFlow && Boolean(laneAwareUtilityComposerHint) ? laneAwareUtilityComposerHint : undefined}
              shortcutHint={
                activeView === "coach"
                  ? composerShortcutHint({
                      language: layout.composerLanguage,
                      hasCommandDeck: normalizedDraft.startsWith("/") && matchingLocalCommands.length > 0,
                      hasContextMenu: openMenu === "context",
                    })
                  : undefined
              }
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
              attachments={composerAttachments}
              onAttachmentsChange={setComposerAttachments}
              attachmentsAvailable={providerImageInputState.supported}
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
                  dismissedComposerDeck !== "command" &&
                  normalizedDraft.startsWith("/") &&
                  matchingLocalCommands.length > 0;
                const hasSkillDeck =
                  dismissedComposerDeck !== "skill" &&
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

                if (event.key === "Escape" && (hasCommandDeck || hasSkillDeck)) {
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
                        pinned: true,
                        active: openMenu === "resources",
                        onClick: () => {
                          setOpenMenu(openMenu === "resources" ? undefined : "resources");
                        },
                      },
                    ]),
                ...(showComposerTrainingVerify && !trainingVerifyFileVisible
                  ? [
                      {
                        id: "composer-verify-file",
                        label: trainingFilePracticeTextCopy.verifyCurrentFile,
                        icon: <CheckMarkIcon size={16} />,
                        pinned: true,
                        onClick: handleVerifyTrainingFromIde,
                      },
                    ]
                  : []),
              ]}
            />
          </div>
        </footer>
      ) : null}
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
