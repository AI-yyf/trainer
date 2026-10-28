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

export type ComposerModelActionDensity = "default" | "compact";
export type ResourcesComposerMode = "locate" | "download" | "organize" | "cards";
export const COMPOSER_MODEL_PICKER_INITIAL_OPTION_LIMIT = 6;
export const COACH_SETTINGS_AUTOSAVE_DELAY_MS = 250;
export const RESOURCE_UPLOAD_LIMIT = 100;
export const RESOURCE_COMPOSER_MAX_IDS = 12;
export type WorkbenchDataSnapshot = ReturnType<typeof useWorkbenchState.getState>["data"];
export type WorkspaceSettingsSnapshot = NonNullable<
  ReturnType<typeof useWorkbenchState.getState>["data"]["memory"]["workspace"]
>;
export type DockedView = "plan" | "resources" | "training" | "progress" | "settings";
export type OperationMessage = TrainerOperationMessage;
export type ResourceOperationKind =
  | "delete"
  | "restore"
  | "search"
  | "index"
  | "upload"
  | "capture"
  | "organize"
  | "export";
export type ResourceMutationOperationKind = "delete" | "restore";
export type PendingResourceOperation = {
  kind: ResourceOperationKind;
  resolve: () => void;
  reject: (reason?: unknown) => void;
  timeoutId: number;
  /** The (marker-stripped) status text that settled this operation. */
  statusMessage?: string;
};
export type PendingResourceTrainingHandoff = {
  resourceId: string;
  resolve: (result: ResourceTrainingHandoffResult) => void;
  timeoutId: number;
};
export type ResourceOperationStatus = {
  kind: ResourceOperationKind;
  requestId: string;
  message: string;
};
export type SettingsFeedbackSlot = "provider" | "coachDefaults" | "workspaceControl";
export type SettingsActionKind =
  | "save-provider"
  | "refresh-provider-models"
  | "test-provider"
  | "clear-provider"
  | "open-config"
  | "save-coach"
  | "reset-defaults"
  | "start-provider-trial";

export type CoachCheckpointRecoveryAction = "resume" | "replay";

export function isCoachCheckpointRecoveryState(
  streaming: { isStreaming: boolean; streamError?: string; completionStopReason?: string },
): boolean {
  if (streaming.isStreaming) {
    return false;
  }
  if (streaming.streamError?.trim()) {
    return true;
  }
  const stopReason = streaming.completionStopReason?.trim().toLowerCase() ?? "";
  return /interrupted|aborted|failed|timeout|network|error/.test(stopReason);
}

export const coachFirstComposerPlaceholder: Record<ComposerLanguage, string> = {
  "zh-CN": "问教练",
  "en-US": "Ask the coach",
  "es-ES": "Empieza por contarme tu nivel, objetivo, proyecto o dónde te has atascado.",
  "fr-FR": "Commencez par me dire votre niveau, votre objectif, votre projet ou ce qui vous bloque.",
  "de-DE": "Sag mir zuerst dein Niveau, dein Ziel, dein Projekt oder wo du festhängst.",
  "ja-JP": "今のレベル、目標、プロジェクト、または困っていることを教えてください。",
  "ko-KR": "현재 수준, 목표, 프로젝트 또는 막힌 부분을 먼저 알려 주세요.",
  "pt-BR": "Comece me contando seu nível, objetivo, projeto ou onde está travado.",
};

export const RESOURCE_OPERATION_STATUS_PATTERN =
  /^\[\[trainer-resource-operation:(delete|restore|search|index|upload|capture|organize|export):([a-z0-9-]{1,96})\]\]\s*/i;
// Learning-feedback completion is a protocol acknowledgement, not a text
// match: the host echoes the request id the UI generated inside a marker.
export const LEARNING_FEEDBACK_STATUS_PATTERN =
  /^\[\[trainer-learning-feedback:([a-z0-9-]{1,96})\]\]\s*/i;
export const RESOURCE_OPERATION_TIMEOUT_MS = 45_000;
export const RESOURCE_TRAINING_HANDOFF_TIMEOUT_MS = 45_000;

export function parseResourceOperationStatus(
  message: HostMessage,
  fallbackMessage: string,
): ResourceOperationStatus | undefined {
  if (message.type !== "operation/status") {
    return undefined;
  }
  const marker = RESOURCE_OPERATION_STATUS_PATTERN.exec(message.payload.message);
  if (!marker) {
    return undefined;
  }
  const kind = marker[1]?.toLowerCase();
  const requestId = marker[2];
  if (
    (
      kind !== "delete" &&
      kind !== "restore" &&
      kind !== "search" &&
      kind !== "index" &&
      kind !== "upload" &&
      kind !== "capture" &&
      kind !== "organize" &&
      kind !== "export"
    ) ||
    !requestId
  ) {
    return undefined;
  }
  return {
    kind,
    requestId,
    message: message.payload.message.slice(marker[0].length).trim() || fallbackMessage,
  };
}

export function parseLearningFeedbackStatus(
  message: HostMessage,
): { requestId: string } | undefined {
  if (message.type !== "operation/status") {
    return undefined;
  }
  const requestId = LEARNING_FEEDBACK_STATUS_PATTERN.exec(message.payload.message)?.[1];
  return requestId ? { requestId } : undefined;
}

export function livePlanTaskMintPendingMessage(language: ComposerLanguage): string {
  const copy: Record<ComposerLanguage, string> = {
    "zh-CN": "正在按当前正式计划准备任务…",
    "en-US": "Preparing a task from the live plan…",
    "es-ES": "Preparando una tarea desde el plan en vivo…",
    "fr-FR": "Préparation d'une tâche à partir du plan actif…",
    "de-DE": "Aufgabe wird aus dem live-Plan vorbereitet…",
    "ja-JP": "正式な計画からタスクを準備しています…",
    "ko-KR": "현재 계획으로 과제를 준비하는 중…",
    "pt-BR": "Preparando uma tarefa a partir do plano ao vivo…",
  };
  return copy[language] ?? copy["en-US"];
}

export function livePlanUpdatePendingMessage(language: ComposerLanguage): string {
  const copy: Record<ComposerLanguage, string> = {
    "zh-CN": "正在按当前正式计划更新…",
    "en-US": "Updating the live plan…",
    "es-ES": "Actualizando el plan en vivo…",
    "fr-FR": "Mise à jour du plan actif…",
    "de-DE": "Live-Plan wird aktualisiert…",
    "ja-JP": "正式な計画を更新しています…",
    "ko-KR": "현재 계획을 업데이트하는 중…",
    "pt-BR": "Atualizando o plano ao vivo…",
  };
  return copy[language] ?? copy["en-US"];
}

export function trainingGenerateCardPendingMessage(language: ComposerLanguage): string {
  const copy: Record<ComposerLanguage, string> = {
    "zh-CN": "正在生成训练卡…",
    "en-US": "Preparing a training card…",
    "es-ES": "Preparando una tarjeta de entrenamiento…",
    "fr-FR": "Préparation d'une carte d'entraînement…",
    "de-DE": "Trainingskarte wird vorbereitet…",
    "ja-JP": "トレーニングカードを準備しています…",
    "ko-KR": "훈련 카드를 준비하는 중…",
    "pt-BR": "Preparando um cartão de treino…",
  };
  return copy[language] ?? copy["en-US"];
}

export function trainingPersistenceFailureMessage(language: ComposerLanguage): string {
  return appUiCopy(language, "训练记录没有保存，因此没有开始教练流式回复。输入已保留，可以重试。");
}

export type PartialResourceDeletionFailure = {
  deletedCount: number;
  failedCount: number;
  summaryRefreshFailed: boolean;
};

export function parsePartialResourceDeletionFailure(
  message: string,
): PartialResourceDeletionFailure | undefined {
  const trimmedMessage = message.trim();
  const summaryRefreshSuffix = " The workspace summary could not be refreshed.";
  const summaryRefreshFailed = trimmedMessage.endsWith(summaryRefreshSuffix);
  const aggregateMessage = summaryRefreshFailed
    ? trimmedMessage.slice(0, -summaryRefreshSuffix.length)
    : trimmedMessage;
  const match = /^Deleted\s+(\d+)\s+resources?\.\s+(\d+)\s+resources?\s+could not be deleted\.$/i.exec(
    aggregateMessage,
  );
  if (!match) {
    return undefined;
  }

  const deletedCount = Number.parseInt(match[1] ?? "", 10);
  const failedCount = Number.parseInt(match[2] ?? "", 10);
  if (
    !Number.isSafeInteger(deletedCount) ||
    !Number.isSafeInteger(failedCount) ||
    deletedCount < 1 ||
    failedCount < 1
  ) {
    return undefined;
  }

  return { deletedCount, failedCount, summaryRefreshFailed };
}

export function partialResourceDeletionFailureMessage(
  { deletedCount, failedCount, summaryRefreshFailed }: PartialResourceDeletionFailure,
  language: ComposerLanguage,
): string {
  if (language === "zh-CN") {
    return `已删除 ${deletedCount} 项资料；${failedCount} 项未能删除。${
      summaryRefreshFailed ? "资料库摘要尚未刷新，请重新打开资料库确认当前状态。" : ""
    }`;
  }

  return `Deleted ${deletedCount} resource${deletedCount === 1 ? "" : "s"}. ${failedCount} could not be deleted.${
    summaryRefreshFailed ? " The resource summary did not refresh. Reopen Resources to verify the current state." : ""
  }`;
}

export function resourceOperationFailureMessage(
  kind: ResourceOperationKind | undefined,
  language: ComposerLanguage,
): string | undefined {
  if (kind !== "upload" && kind !== "index") {
    return undefined;
  }

  const copy: Record<ComposerLanguage, Record<"upload" | "index", string>> = {
    "zh-CN": {
      upload: "\u8d44\u6599\u6ca1\u6709\u5b8c\u5168\u5bfc\u5165\u3002\u5df2\u5bfc\u5165\u7684\u8d44\u6599\u4ecd\u53ef\u4f7f\u7528\uff1b\u5230\u201c\u8d44\u6599\u201d\u9875\u5237\u65b0\u540e\u91cd\u8bd5\u672a\u5b8c\u6210\u7684\u9879\u76ee\u3002",
      index: "\u6709\u4e9b\u8d44\u6599\u8fd8\u6ca1\u6709\u5b8c\u6210\u6574\u7406\u3002\u5df2\u5b8c\u6210\u7684\u8d44\u6599\u53ef\u4ee5\u7ee7\u7eed\u4f7f\u7528\uff1b\u5237\u65b0\u7d22\u5f15\u4f1a\u91cd\u8bd5\u5176\u4f59\u9879\u76ee\u3002",
    },
    "en-US": {
      upload: "The import did not finish for every resource. The imported items are still available; refresh Resources to retry the rest.",
      index: "Some resources did not finish processing. The completed items are still available; refresh the index to retry the rest.",
    },
    "es-ES": {
      upload: "No se importaron todos los recursos. Los elementos importados siguen disponibles; actualiza Recursos para reintentar los demas.",
      index: "Algunos recursos no terminaron de procesarse. Los elementos listos siguen disponibles; actualiza el indice para reintentar los demas.",
    },
    "fr-FR": {
      upload: "Tous les elements n'ont pas ete importes. Les elements importes restent disponibles ; actualisez Ressources pour reessayer les autres.",
      index: "Certaines ressources n'ont pas termine leur traitement. Les elements prets restent disponibles ; actualisez l'index pour reessayer les autres.",
    },
    "de-DE": {
      upload: "Nicht alle Materialien wurden importiert. Die importierten Elemente bleiben verfugbar; aktualisiere Ressourcen, um die anderen erneut zu versuchen.",
      index: "Einige Materialien wurden nicht fertig verarbeitet. Die fertigen Elemente bleiben verfugbar; aktualisiere den Index, um die anderen erneut zu versuchen.",
    },
    "ja-JP": {
      upload: "\u4e00\u90e8\u306e\u8cc7\u6599\u306e\u53d6\u308a\u8fbc\u307f\u304c\u5b8c\u4e86\u3057\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u53d6\u308a\u8fbc\u307f\u6e08\u307f\u306e\u8cc7\u6599\u306f\u305d\u306e\u307e\u307e\u4f7f\u3048\u307e\u3059\u3002\u30ea\u30bd\u30fc\u30b9\u3092\u66f4\u65b0\u3057\u3066\u6b8b\u308a\u3092\u3082\u3046\u4e00\u5ea6\u8a66\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
      index: "\u4e00\u90e8\u306e\u8cc7\u6599\u306e\u51e6\u7406\u304c\u5b8c\u4e86\u3057\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u51e6\u7406\u6e08\u307f\u306e\u8cc7\u6599\u306f\u305d\u306e\u307e\u307e\u4f7f\u3048\u307e\u3059\u3002\u30a4\u30f3\u30c7\u30c3\u30af\u30b9\u3092\u66f4\u65b0\u3057\u3066\u6b8b\u308a\u3092\u3082\u3046\u4e00\u5ea6\u8a66\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    },
    "ko-KR": {
      upload: "\ubaa8\ub4e0 \uc790\ub8cc\ub97c \uac00\uc838\uc624\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4. \uac00\uc838\uc628 \uc790\ub8cc\ub294 \uacc4\uc18d \uc0ac\uc6a9\ud560 \uc218 \uc788\uc73c\uba70, \ub098\uba38\uc9c0\ub294 \uc790\ub8cc\ub97c \uc0c8\ub85c \uace0\uce68\ud574 \ub2e4\uc2dc \uc2dc\ub3c4\ud558\uc138\uc694.",
      index: "\uc77c\ubd80 \uc790\ub8cc\uc758 \ucc98\ub9ac\uac00 \uc644\ub8cc\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4. \uc644\ub8cc\ub41c \uc790\ub8cc\ub294 \uacc4\uc18d \uc0ac\uc6a9\ud560 \uc218 \uc788\uc73c\uba70, \uc0c8\ub85c \uace0\uce68\ud558\uba74 \ub098\uba38\uc9c0\ub97c \ub2e4\uc2dc \uc2dc\ub3c4\ud569\ub2c8\ub2e4.",
    },
    "pt-BR": {
      upload: "Nem todos os recursos foram importados. Os itens importados continuam disponiveis; atualize Recursos para tentar os demais novamente.",
      index: "Alguns recursos nao terminaram de ser processados. Os itens prontos continuam disponiveis; atualize o indice para tentar os demais novamente.",
    },
  };
  return copy[language]?.[kind] ?? copy["en-US"][kind];
}

// Provider failures carry a structured category from the host. Rendering a
// localized hint from that category keeps the message actionable (wrong key vs.
// unreachable service vs. unknown model) without ever trusting host error prose.
export function providerCategoryFailureMessage(
  summary: HostProviderTestSummary | undefined,
  language: ComposerLanguage,
): string | undefined {
  const category = summary?.errorCategory?.trim();
  if (!category) {
    return undefined;
  }
  return providerErrorHint(
    { modelErrorCategory: category, modelListDetail: undefined },
    language,
  );
}

export function sanitizeHostFailureMessage(
  message: HostMessage,
  language: ComposerLanguage,
  isProviderAction = false,
  resourceOperationKind?: ResourceOperationKind,
): HostMessage {
  if (message.type !== "operation/status" || message.payload.tone !== "error") {
    return message;
  }
  // The host marks curated, localized, path-free library failure copy with
  // the resource-failure marker (libraryCopy in resourceCommands.ts). Only
  // that marked copy may pass through: the specific reason is the whole
  // point, and a generic "try again" dead-ends. Everything unmarked keeps
  // the local recovery copy below — arbitrary host prose never passes.
  if (detectTrainerResourceFailure(message.payload.message)) {
    return {
      ...message,
      payload: {
        ...message.payload,
        message: trainerResourceFailureMessage(message.payload.message),
      },
    };
  }
  const partialDeletion = parsePartialResourceDeletionFailure(message.payload.message);
  const resourceRecovery = resourceOperationFailureMessage(resourceOperationKind, language);
  const revisionConflict = detectPlanRevisionConflict(message.payload.message);
  const livePlanGate = parseLivePlanTaskGateMarker(message.payload.message);
  return {
    ...message,
    payload: {
      ...message.payload,
      message: detectOperationScopeChanged(message.payload.message)
        ? operationScopeChangedMessage(language)
        : detectTrainingVerificationTargetMismatch(message.payload.message)
        ? trainingVerificationTargetMismatchMessage(language)
        : detectAttestationUndelivered(message.payload.message)
        ? attestationUndeliveredMessage(language)
        : revisionConflict
        ? planRevisionConflictMessage(revisionConflict.revision, language)
        : partialDeletion
          ? partialResourceDeletionFailureMessage(partialDeletion, language)
          : resourceRecovery
            ? resourceRecovery
          : livePlanGate
          ? livePlanTaskGateFailureMessage(livePlanGate, language)
        : isProviderAction
          ? providerCategoryFailureMessage(message.payload.providerTest, language) ??
            providerRecoveryMessage(language)
          : recoverableFailureMessage("operation", language),
    },
  };
}

export interface SettingsActionState {
  kind: SettingsActionKind;
  targets: SettingsFeedbackSlot[];
  baselineMessageKey?: string;
}

export interface UtilityComposerPrompt {
  id: string;
  label: string;
  prompt: string;
}

export interface UtilityComposerModeOption<TMode extends string> {
  id: TMode;
  label: string;
  header: string;
  summary: string;
  hint: string;
  placeholder: string;
  accessibilityLabel: string;
  prompts: UtilityComposerPrompt[];
}

export type SettingsFeedbackState = Partial<Record<SettingsFeedbackSlot, SettingsActionFeedback>>;
export const DEFAULT_ANSWER_MODE: CoachAnswerMode = "auto";
export const DEFAULT_TEACHING_STYLE: TeachingStyle = "auto";
export type BrowserPreviewModule = typeof import("../lib/browserSidecar");
export const CoachPlanView = lazy(async () => {
  const module = await import("../components/plan/CoachPlanView");
  return { default: module.CoachPlanView };
});
export const CoachSettingsView = lazy(async () => {
  const module = await import("../components/settings/CoachSettingsView");
  return { default: module.CoachSettingsView };
});
export const ResourcesWorkbenchView = lazy(async () => {
  const module = await import("../components/resources/ResourcesWorkbenchView");
  return { default: module.ResourcesWorkbenchView };
});
export const TrainingWorkbenchView = lazy(async () => {
  const module = await import("../components/training/TrainingWorkbenchView");
  return { default: module.TrainingWorkbenchView };
});
export const ProgressView = lazy(async () => {
  const module = await import("../components/progress/ProgressView");
  return { default: module.ProgressView };
});

export let browserPreviewModulePromise: Promise<BrowserPreviewModule> | undefined;
let bootstrapRequestSent = false;

export function resetBootstrapRequestSent(): void {
  bootstrapRequestSent = false;
}
export let lastBootstrapRequestAt = 0;

export function inBrowserPreviewEnvironment(): boolean {
  return (
    typeof window !== "undefined" &&
    (window.__TRAINER_BROWSER_PREVIEW__ === true || !window.acquireVsCodeApi)
  );
}

export function readBrowserPreviewLocationOverrides(): {
  activeView?: ActiveWorkbenchView;
  composerLanguage?: ComposerLanguage;
  direction?: TextDirection;
} {
  if (!inBrowserPreviewEnvironment() || typeof window === "undefined") {
    return {};
  }

  const search = new URLSearchParams(window.location.search);
  const requestedLanguage = search.get("lang");
  const requestedView = search.get("view");
  const requestedDirection = search.get("dir");

  return {
    composerLanguage: isComposerLanguage(requestedLanguage) ? requestedLanguage : undefined,
    direction:
      requestedDirection === "rtl" || requestedDirection === "ltr"
        ? requestedDirection
        : undefined,
    activeView:
      requestedView === "coach" ||
      requestedView === "plan" ||
      requestedView === "resources" ||
      requestedView === "training" ||
      requestedView === "progress" ||
      requestedView === "settings"
        ? requestedView
        : requestedView === "practice"
          ? "training"
          : undefined,
  };
}

export async function loadBrowserPreviewModule(): Promise<BrowserPreviewModule> {
  browserPreviewModulePromise ??= import("../lib/browserSidecar");
  return browserPreviewModulePromise;
}

export function requestBootstrapOnce(force = false): void {
  if (force) {
    bootstrapRequestSent = false;
  }
  if (bootstrapRequestSent) {
    return;
  }
  bootstrapRequestSent = true;
  lastBootstrapRequestAt = Date.now();
  announceReady();
  postMessage({ type: "request/bootstrap" });
}

export function syncBootstrapLifecycleOnVisible(hasReceivedHostState: boolean): void {
  bootstrapRequestSent = false;
  if (!hasReceivedHostState) {
    requestBootstrapOnce(true);
  } else {
    announceReady();
  }
}

export function normalizeOperationMessageKey(message: OperationMessage | undefined): string | undefined {
  const normalized = message?.message.trim().toLowerCase();
  return normalized && normalized.length > 0 ? normalized : undefined;
}

export function ViewFallback({
  label,
  language,
}: {
  label: string;
  language: ComposerLanguage;
}) {
  return (
    <SystemState kind="loading" title={appUiCopy(language, "正在加载{v}…").replace("{v}", label)} />
  );
}

export const COACH_REPLY_BODY_MAX_CHARS = 4000;

export const trainingFilePracticeCopy: Record<
  ComposerLanguage,
  {
    resultPlaceholder: string;
    blockerPlaceholder: string;
    verifyCurrentFile: string;
    submitTry: string;
    submitBlocker: string;
  }
> = {
  "zh-CN": {
    resultPlaceholder: "写我改了什么",
    blockerPlaceholder: "卡住了的话，写下哪一步过不去。",
    verifyCurrentFile: "验证当前文件",
    submitTry: "提交当前训练动手记录",
    submitBlocker: "提交当前训练 blocker",
  },
  "en-US": {
    resultPlaceholder: "What I changed",
    blockerPlaceholder: "Name the blocker, the failed check, and the smaller slice you need next.",
    verifyCurrentFile: "Verify current file",
    submitTry: "Submit the current training try note",
    submitBlocker: "Submit the current training blocker",
  },
  "es-ES": {
    resultPlaceholder: "Primero logra el resultado más pequeño y registra qué verificaste.",
    blockerPlaceholder: "Indica el blocker, la comprobación que falló y el siguiente paso más pequeño.",
    verifyCurrentFile: "Verificar archivo actual",
    submitTry: "Enviar la nota de práctica actual",
    submitBlocker: "Enviar el blocker actual",
  },
  "fr-FR": {
    resultPlaceholder: "Notez le résultat ou la preuve.",
    blockerPlaceholder: "Indiquez le blocker, la vérification échouée et la plus petite étape suivante.",
    verifyCurrentFile: "Vérifier le fichier actuel",
    submitTry: "Envoyer la note de pratique actuelle",
    submitBlocker: "Envoyer le blocker actuel",
  },
  "de-DE": {
    resultPlaceholder: "Ergebnis oder Nachweis notieren.",
    blockerPlaceholder: "Nenne den Blocker, die fehlgeschlagene Prüfung und den kleineren nächsten Schritt.",
    verifyCurrentFile: "Aktuelle Datei prüfen",
    submitTry: "Aktuelle Übungsnotiz senden",
    submitBlocker: "Aktuellen Blocker senden",
  },
  "ja-JP": {
    resultPlaceholder: "結果または根拠を記録する。",
    blockerPlaceholder: "blocker、失敗した確認、次に戻る小さな手順を書いてください。",
    verifyCurrentFile: "現在のファイルを検証",
    submitTry: "現在の練習メモを送信",
    submitBlocker: "現在の blocker を送信",
  },
  "ko-KR": {
    resultPlaceholder: "결과나 근거를 기록하세요.",
    blockerPlaceholder: "blocker, 실패한 확인, 다음에 시도할 더 작은 단계를 적으세요.",
    verifyCurrentFile: "현재 파일 검증",
    submitTry: "현재 연습 메모 보내기",
    submitBlocker: "현재 blocker 보내기",
  },
  "pt-BR": {
    resultPlaceholder: "Registre o resultado ou a evidência.",
    blockerPlaceholder: "Informe o blocker, a verificação que falhou e o próximo passo menor.",
    verifyCurrentFile: "Verificar arquivo atual",
    submitTry: "Enviar a nota de prática atual",
    submitBlocker: "Enviar o blocker atual",
  },
};

export function trainingFilePracticeText(language: ComposerLanguage) {
  return trainingFilePracticeCopy[language] ?? trainingFilePracticeCopy["en-US"];
}

export type TrainingComposerModeCopy = {
  talkPlaceholder: string;
  talkAccessibilityLabel: string;
  choicePlaceholder: string;
  fillPlaceholder: string;
  shortAnswerPlaceholder: string;
  answerAccessibilityLabel: string;
  studyPlaceholder: string;
  studyAccessibilityLabel: string;
  manualResultPlaceholder: string;
  manualBlockerPlaceholder: string;
  verificationPlaceholder: string;
  genericPlaceholder: string;
  genericAccessibilityLabel: string;
};

export const trainingComposerModeCopy: Record<ComposerLanguage, TrainingComposerModeCopy> = {
  "zh-CN": {
    talkPlaceholder: "围绕当前训练卡片直接问教练。",
    talkAccessibilityLabel: "就当前训练卡片向教练提问",
    choicePlaceholder: "可以直接选择上面的答案，也可以在这里改成你自己的表达。",
    fillPlaceholder: "写出关键词、概念，或最短的准确表达。",
    shortAnswerPlaceholder: "用一到两句话给出答案。",
    answerAccessibilityLabel: "提交当前训练答案",
    studyPlaceholder: "先读完卡片，再在这里记下一条理解到的规则、例子或卡点。",
    studyAccessibilityLabel: "提交当前训练学习笔记",
    manualResultPlaceholder: "写出你已经拿到的结果、例子或关键步。",
    manualBlockerPlaceholder: "写出卡点、最弱的证据，以及下一步要缩回的更小切片。",
    verificationPlaceholder: "围绕 {item} 记录结果、卡点或一条验证结论。",
    genericPlaceholder: "写我改了什么",
    genericAccessibilityLabel: "提交当前训练记录",
  },
  "en-US": {
    talkPlaceholder: "Ask Coach directly about the current training card.",
    talkAccessibilityLabel: "Ask Coach about the current training card",
    choicePlaceholder: "Choose an option above or rewrite it in your own words.",
    fillPlaceholder: "Write the keyword, concept, or shortest accurate phrase.",
    shortAnswerPlaceholder: "Answer in one or two sentences.",
    answerAccessibilityLabel: "Submit the current training answer",
    studyPlaceholder: "Study the card first, then record one rule, example, or obstacle here.",
    studyAccessibilityLabel: "Submit the current training study note",
    manualResultPlaceholder: "Write the result, example, or key step you now have.",
    manualBlockerPlaceholder: "Name the obstacle, weakest proof, and the smaller step you need next.",
    verificationPlaceholder: "Record the result, obstacle, or verification note for {item}.",
    genericPlaceholder: "What I changed",
    genericAccessibilityLabel: "Submit the current training note",
  },
  "es-ES": {
    talkPlaceholder: "Pregunta directamente al coach sobre la tarjeta de entrenamiento actual.",
    talkAccessibilityLabel: "Preguntar al coach sobre la tarjeta actual",
    choicePlaceholder: "Elige una opción arriba o reescríbela con tus propias palabras.",
    fillPlaceholder: "Escribe la palabra clave, el concepto o la formulación correcta más corta.",
    shortAnswerPlaceholder: "Responde en una o dos frases.",
    answerAccessibilityLabel: "Enviar la respuesta de entrenamiento actual",
    studyPlaceholder: "Primero estudia la tarjeta; luego anota aquí una regla, ejemplo u obstáculo.",
    studyAccessibilityLabel: "Enviar la nota de estudio actual",
    manualResultPlaceholder: "Escribe el resultado, ejemplo o paso clave que ya tienes.",
    manualBlockerPlaceholder: "Indica el obstáculo, la evidencia más débil y el paso más pequeño que necesitas después.",
    verificationPlaceholder: "Registra el resultado, el obstáculo o una nota de verificación para {item}.",
    genericPlaceholder: "Registra el resultado de esta ronda, el obstáculo o una nota de verificación.",
    genericAccessibilityLabel: "Enviar la nota de entrenamiento actual",
  },
  "fr-FR": {
    talkPlaceholder: "Posez directement une question au coach sur la carte d'entraînement actuelle.",
    talkAccessibilityLabel: "Poser une question au coach sur la carte actuelle",
    choicePlaceholder: "Choisissez une option ci-dessus ou reformulez-la avec vos propres mots.",
    fillPlaceholder: "Écrivez le mot-clé, le concept ou la formulation correcte la plus courte.",
    shortAnswerPlaceholder: "Répondez en une ou deux phrases.",
    answerAccessibilityLabel: "Envoyer la réponse d'entraînement actuelle",
    studyPlaceholder: "Étudiez d'abord la carte, puis notez ici une règle, un exemple ou un obstacle.",
    studyAccessibilityLabel: "Envoyer la note d'étude actuelle",
    manualResultPlaceholder: "Écrivez le résultat, l'exemple ou l'étape clé que vous avez maintenant.",
    manualBlockerPlaceholder: "Indiquez l'obstacle, la preuve la plus faible et la plus petite étape à faire ensuite.",
    verificationPlaceholder: "Notez le résultat, l'obstacle ou une note de vérification pour {item}.",
    genericPlaceholder: "Notez le résultat de cette session, l'obstacle ou une note de vérification.",
    genericAccessibilityLabel: "Envoyer la note d'entraînement actuelle",
  },
  "de-DE": {
    talkPlaceholder: "Frage den Coach direkt zur aktuellen Trainingskarte.",
    talkAccessibilityLabel: "Den Coach zur aktuellen Trainingskarte fragen",
    choicePlaceholder: "Wähle oben eine Option oder formuliere sie mit eigenen Worten neu.",
    fillPlaceholder: "Schreibe das Schlüsselwort, Konzept oder die kürzeste korrekte Formulierung.",
    shortAnswerPlaceholder: "Antworte in ein oder zwei Sätzen.",
    answerAccessibilityLabel: "Aktuelle Trainingsantwort senden",
    studyPlaceholder: "Lies zuerst die Karte und notiere hier dann eine Regel, ein Beispiel oder ein Hindernis.",
    studyAccessibilityLabel: "Aktuelle Lernnotiz senden",
    manualResultPlaceholder: "Schreibe das Ergebnis, Beispiel oder den Schlüsselschritt auf, den du jetzt hast.",
    manualBlockerPlaceholder: "Nenne das Hindernis, den schwächsten Beleg und den kleineren nächsten Schritt.",
    verificationPlaceholder: "Halte Ergebnis, Hindernis oder einen Prüfhinweis zu {item} fest.",
    genericPlaceholder: "Halte Ergebnis, Hindernis oder einen Prüfhinweis dieser Runde fest.",
    genericAccessibilityLabel: "Aktuelle Trainingsnotiz senden",
  },
  "ja-JP": {
    talkPlaceholder: "現在のトレーニングカードについて、コーチに直接質問してください。",
    talkAccessibilityLabel: "現在のトレーニングカードについてコーチに質問",
    choicePlaceholder: "上の選択肢を選ぶか、自分の言葉で書き直してください。",
    fillPlaceholder: "キーワード、概念、または最も短い正確な表現を書いてください。",
    shortAnswerPlaceholder: "一文か二文で答えてください。",
    answerAccessibilityLabel: "現在のトレーニングの回答を送信",
    studyPlaceholder: "まずカードを読み、ルール、例、または詰まった点をここに一つ記録してください。",
    studyAccessibilityLabel: "現在のトレーニング学習メモを送信",
    manualResultPlaceholder: "得られた結果、例、または重要な手順を書いてください。",
    manualBlockerPlaceholder: "詰まった点、最も弱い根拠、次に試すより小さな手順を書いてください。",
    verificationPlaceholder: "{item} について、結果、詰まった点、または検証メモを記録してください。",
    genericPlaceholder: "この回の結果、詰まった点、または検証メモを記録してください。",
    genericAccessibilityLabel: "現在のトレーニングメモを送信",
  },
  "ko-KR": {
    talkPlaceholder: "현재 훈련 카드에 대해 코치에게 바로 질문하세요.",
    talkAccessibilityLabel: "현재 훈련 카드에 대해 코치에게 질문",
    choicePlaceholder: "위의 선택지를 고르거나 자신의 말로 다시 작성하세요.",
    fillPlaceholder: "핵심어, 개념 또는 가장 짧고 정확한 표현을 작성하세요.",
    shortAnswerPlaceholder: "한두 문장으로 답하세요.",
    answerAccessibilityLabel: "현재 훈련 답변 보내기",
    studyPlaceholder: "먼저 카드를 읽고 규칙, 예시 또는 막힌 점 하나를 여기에 기록하세요.",
    studyAccessibilityLabel: "현재 훈련 학습 메모 보내기",
    manualResultPlaceholder: "지금 얻은 결과, 예시 또는 핵심 단계를 작성하세요.",
    manualBlockerPlaceholder: "막힌 점, 가장 약한 근거, 다음에 시도할 더 작은 단계를 적으세요.",
    verificationPlaceholder: "{item}에 대한 결과, 막힌 점 또는 검증 메모를 기록하세요.",
    genericPlaceholder: "이번 학습의 결과, 막힌 점 또는 검증 메모를 기록하세요.",
    genericAccessibilityLabel: "현재 훈련 메모 보내기",
  },
  "pt-BR": {
    talkPlaceholder: "Pergunte diretamente ao coach sobre o cartão de treinamento atual.",
    talkAccessibilityLabel: "Perguntar ao coach sobre o cartão atual",
    choicePlaceholder: "Escolha uma opção acima ou reescreva-a com suas próprias palavras.",
    fillPlaceholder: "Escreva a palavra-chave, o conceito ou a formulação correta mais curta.",
    shortAnswerPlaceholder: "Responda em uma ou duas frases.",
    answerAccessibilityLabel: "Enviar a resposta do treinamento atual",
    studyPlaceholder: "Primeiro estude o cartão; depois registre aqui uma regra, exemplo ou obstáculo.",
    studyAccessibilityLabel: "Enviar a nota de estudo atual",
    manualResultPlaceholder: "Escreva o resultado, exemplo ou passo-chave que você já tem.",
    manualBlockerPlaceholder: "Informe o obstáculo, a evidência mais fraca e o menor próximo passo.",
    verificationPlaceholder: "Registre o resultado, o obstáculo ou uma nota de verificação para {item}.",
    genericPlaceholder: "Registre o resultado desta rodada, o obstáculo ou uma nota de verificação.",
    genericAccessibilityLabel: "Enviar a nota de treinamento atual",
  },
};

export function trainingComposerModeText(language: ComposerLanguage): TrainingComposerModeCopy {
  return trainingComposerModeCopy[language] ?? trainingComposerModeCopy["en-US"];
}

export type TrainingHandoffComposerCopy = {
  reflectAccessibilityLabel: string;
  reflectPlaceholder: string;
  reflectSubmitAriaLabel: string;
  reflectEmptySubmitAriaLabel: string;
  returnAccessibilityLabel: string;
  returnPlaceholder: string;
  returnSubmitAriaLabel: string;
  returnSummary: string;
  routeLabel: string;
  cardRouteDescription: string;
  coachRouteDescription: string;
};

export const trainingHandoffComposerCopy: Record<ComposerLanguage, TrainingHandoffComposerCopy> = {
  "zh-CN": {
    reflectAccessibilityLabel: "记录当前训练复盘",
    reflectPlaceholder: "写下你刚确认的规则，以及下次如何复用它。",
    reflectSubmitAriaLabel: "记录训练复盘",
    reflectEmptySubmitAriaLabel: "写完训练复盘后记录",
    returnAccessibilityLabel: "完成当前训练回流",
    returnPlaceholder: "无需填写内容。核对可信验证结果后，点击完成回流。",
    returnSubmitAriaLabel: "完成训练回流",
    returnSummary: "不会保存输入内容；此操作只完成已验证的回流。",
    routeLabel: "输入去向",
    cardRouteDescription: "继续当前训练卡片",
    coachRouteDescription: "转为对话并保留训练上下文",
  },
  "en-US": {
    reflectAccessibilityLabel: "Record the current training reflection",
    reflectPlaceholder: "State the rule you just confirmed and how you will reuse it.",
    reflectSubmitAriaLabel: "Record training reflection",
    reflectEmptySubmitAriaLabel: "Write a training reflection before recording it",
    returnAccessibilityLabel: "Complete the current training return",
    returnPlaceholder: "No note is needed. Check the trusted verification, then select Complete return.",
    returnSubmitAriaLabel: "Complete training return",
    returnSummary: "No text is saved. This action only completes the verified return.",
    routeLabel: "Input route",
    cardRouteDescription: "Continue the current training card",
    coachRouteDescription: "Switch to conversation while keeping training context",
  },
  "es-ES": {
    reflectAccessibilityLabel: "Registrar la reflexión del entrenamiento actual",
    reflectPlaceholder: "Indica la regla que acabas de confirmar y cómo la reutilizarás.",
    reflectSubmitAriaLabel: "Registrar reflexión de entrenamiento",
    reflectEmptySubmitAriaLabel: "Escribe una reflexión antes de registrarla",
    returnAccessibilityLabel: "Completar el retorno del entrenamiento actual",
    returnPlaceholder: "No hace falta escribir nada. Revisa la verificación confiable y completa el retorno.",
    returnSubmitAriaLabel: "Completar retorno de entrenamiento",
    returnSummary: "No se guarda texto. Esta acción solo completa el retorno verificado.",
    routeLabel: "Destino de entrada",
    cardRouteDescription: "Continuar con la tarjeta de entrenamiento actual",
    coachRouteDescription: "Cambiar a la conversación manteniendo el contexto de entrenamiento",
  },
  "fr-FR": {
    reflectAccessibilityLabel: "Consigner la réflexion de formation actuelle",
    reflectPlaceholder: "Indiquez la règle que vous venez de confirmer et comment vous la réutiliserez.",
    reflectSubmitAriaLabel: "Consigner la réflexion de formation",
    reflectEmptySubmitAriaLabel: "Rédigez une réflexion avant de la consigner",
    returnAccessibilityLabel: "Terminer le retour de formation actuel",
    returnPlaceholder: "Aucune note n'est requise. Vérifiez le résultat fiable, puis terminez le retour.",
    returnSubmitAriaLabel: "Terminer le retour de formation",
    returnSummary: "Aucun texte n'est enregistré. Cette action termine seulement le retour vérifié.",
    routeLabel: "Destination de saisie",
    cardRouteDescription: "Continuer la carte de formation actuelle",
    coachRouteDescription: "Passer à la conversation en gardant le contexte de formation",
  },
  "de-DE": {
    reflectAccessibilityLabel: "Reflexion zum aktuellen Training festhalten",
    reflectPlaceholder: "Nenne die eben bestätigte Regel und wie du sie wiederverwendest.",
    reflectSubmitAriaLabel: "Trainingsreflexion festhalten",
    reflectEmptySubmitAriaLabel: "Schreibe eine Trainingsreflexion, bevor du sie festhältst",
    returnAccessibilityLabel: "Aktuelle Trainingsrückgabe abschließen",
    returnPlaceholder: "Keine Notiz erforderlich. Prüfe das vertrauenswürdige Ergebnis und schließe dann die Rückgabe ab.",
    returnSubmitAriaLabel: "Trainingsrückgabe abschließen",
    returnSummary: "Kein Text wird gespeichert. Diese Aktion schließt nur die verifizierte Rückgabe ab.",
    routeLabel: "Eingabeziel",
    cardRouteDescription: "Mit der aktuellen Trainingskarte fortfahren",
    coachRouteDescription: "Zur Unterhaltung wechseln und den Trainingskontext behalten",
  },
  "ja-JP": {
    reflectAccessibilityLabel: "現在のトレーニングの振り返りを記録",
    reflectPlaceholder: "今確認したルールと、次にどう再利用するかを書いてください。",
    reflectSubmitAriaLabel: "トレーニングの振り返りを記録",
    reflectEmptySubmitAriaLabel: "振り返りを書いてから記録してください",
    returnAccessibilityLabel: "現在のトレーニングの回帰を完了",
    returnPlaceholder: "入力は不要です。信頼できる検証結果を確認してから、回帰を完了してください。",
    returnSubmitAriaLabel: "トレーニングの回帰を完了",
    returnSummary: "入力内容は保存されません。この操作は検証済みの回帰のみを完了します。",
    routeLabel: "入力先",
    cardRouteDescription: "現在のトレーニングカードを続ける",
    coachRouteDescription: "トレーニングの文脈を保って会話に切り替える",
  },
  "ko-KR": {
    reflectAccessibilityLabel: "현재 훈련 회고 기록",
    reflectPlaceholder: "방금 확인한 규칙과 다음에 어떻게 재사용할지 적어 주세요.",
    reflectSubmitAriaLabel: "훈련 회고 기록",
    reflectEmptySubmitAriaLabel: "회고를 작성한 뒤 기록하세요",
    returnAccessibilityLabel: "현재 훈련 회귀 완료",
    returnPlaceholder: "입력할 내용이 없습니다. 신뢰할 수 있는 검증 결과를 확인한 뒤 회귀를 완료하세요.",
    returnSubmitAriaLabel: "훈련 회귀 완료",
    returnSummary: "입력 내용은 저장되지 않습니다. 이 작업은 검증된 회귀만 완료합니다.",
    routeLabel: "입력 경로",
    cardRouteDescription: "현재 훈련 카드를 계속 진행",
    coachRouteDescription: "훈련 맥락을 유지한 채 대화로 전환",
  },
  "pt-BR": {
    reflectAccessibilityLabel: "Registrar a reflexão do treinamento atual",
    reflectPlaceholder: "Registre a regra que você acabou de confirmar e como vai reutilizá-la.",
    reflectSubmitAriaLabel: "Registrar reflexão de treinamento",
    reflectEmptySubmitAriaLabel: "Escreva uma reflexão antes de registrá-la",
    returnAccessibilityLabel: "Concluir o retorno do treinamento atual",
    returnPlaceholder: "Não é necessário escrever nada. Confira a verificação confiável e conclua o retorno.",
    returnSubmitAriaLabel: "Concluir retorno do treinamento",
    returnSummary: "Nenhum texto é salvo. Esta ação apenas conclui o retorno verificado.",
    routeLabel: "Destino da entrada",
    cardRouteDescription: "Continuar o cartão de treinamento atual",
    coachRouteDescription: "Mudar para a conversa mantendo o contexto de treinamento",
  },
};

export function trainingHandoffComposerText(language: ComposerLanguage): TrainingHandoffComposerCopy {
  return trainingHandoffComposerCopy[language] ?? trainingHandoffComposerCopy["en-US"];
}

export function localizeUiViewReferences(
  value: string | undefined,
  language: ComposerLanguage,
): string | undefined {
  if (!value) {
    return value;
  }

  const localized = value
    .replace(/\bCoach\b/g, coachViewLabel(language))
    .replace(/\bPlan\b/g, planViewLabel(language))
    .replace(/\bResources\b/g, resourcesViewLabel(language))
    .replace(/\bTraining\b/g, trainingViewLabel(language))
    .replace(/\bSettings\b/g, settingsViewLabel(language));

  return language === "zh-CN"
    ? localized
        .replace(/(?<=[\u4e00-\u9fff])\s+(对话|计划|资料|训练|设置)/gu, "$1")
        .replace(/(对话|计划|资料|训练|设置)\s+(?=[\u4e00-\u9fff])/gu, "$1")
    : localized;
}




export function containsChineseText(value: string | undefined): boolean {
  return /[\u4e00-\u9fff]/u.test(value ?? "");
}

export function containsJapaneseText(value: string | undefined): boolean {
  return /[\u3040-\u30ff]/u.test(value ?? "");
}

export function containsKoreanText(value: string | undefined): boolean {
  return /[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]/u.test(value ?? "");
}

export function looksLikeChineseMojibake(value: string | undefined): boolean {
  return /(?:[ãäåçèéïð][\u0080-\u00BF]{1,3}){2,}/u.test(value ?? "");
}

export const SHORT_ZH_TECHNICAL_ENGLISH_TOKENS = new Set([
  "api",
  "apis",
  "protocol",
  "protocols",
  "provider",
  "providers",
  "model",
  "models",
  "remote",
  "debug",
  "function",
  "functions",
  "signature",
  "hover",
  "definition",
  "call",
  "site",
  "callsite",
  "workspace",
  "workspaces",
  "file",
  "files",
  "path",
  "paths",
  "coach",
  "plan",
  "training",
  "resources",
  "settings",
  "flash",
  "practice",
  "scenario",
  "pack",
  "verify",
  "return",
  "learn",
  "try",
  "reflect",
  "ide",
  "vscode",
  "ssh",
  "tunnel",
  "tunnels",
  "wsl",
  "json",
  "http",
  "https",
  "python",
  "typescript",
  "javascript",
  "node",
  "terminal",
  "breakpoint",
  "trace",
  "prompt",
  "truth",
  "thread",
  "mini",
  "minimax",
  "openai",
  "anthropic",
  "gemini",
  "kimi",
]);

export function tokenizeAsciiWords(value: string): string[] {
  return value.toLowerCase().match(/[a-z]+(?:[/-][a-z0-9]+)*/g) ?? [];
}

export function isShortTechnicalEnglishText(value: string): boolean {
  const normalized = value.trim();
  if (!normalized || normalized.length > 48) {
    return false;
  }
  if (containsChineseText(normalized) || looksLikeChineseMojibake(normalized)) {
    return false;
  }
  if (/^[A-Za-z0-9_.:/\\#@()[\]-]+$/.test(normalized)) {
    return true;
  }
  if (/[.!?][)"'\]]*$/.test(normalized)) {
    return false;
  }
  const words = tokenizeAsciiWords(normalized);
  if (words.length === 0 || words.length > 6) {
    return false;
  }
  return words.every((word) => SHORT_ZH_TECHNICAL_ENGLISH_TOKENS.has(word) || /\d/.test(word));
}

export function hasExcessiveEnglishProseForChinese(value: string): boolean {
  // Code identifiers are part of the exercise, not foreign-language prose.
  // Rejecting any unknown English token hid real Chinese questions containing
  // names such as `pair[0].append(4)`.
  const prose = value.replace(/```[\s\S]*?```|`[^`]*`/g, "");
  const words = tokenizeAsciiWords(prose);
  if (words.length === 0) {
    return false;
  }
  const unfamiliar = words.filter(
    (word) => !SHORT_ZH_TECHNICAL_ENGLISH_TOKENS.has(word) && !/\d/.test(word),
  );
  const chineseLength = (prose.match(/[\u4e00-\u9fff]/g) ?? []).length;
  return unfamiliar.length >= 8 && unfamiliar.join("").length > chineseLength * 2;
}

export function isLanguageAlignedUiText(language: ComposerLanguage, value: string | undefined): boolean {
  const normalized = value?.trim();
  if (!normalized) {
    return false;
  }
  if (looksLikeChineseMojibake(normalized)) {
    return false;
  }
  if (language === "zh-CN") {
    return (
      (!containsJapaneseText(normalized) &&
        !containsKoreanText(normalized) &&
        containsChineseText(normalized) &&
        !hasExcessiveEnglishProseForChinese(normalized)) ||
      isShortTechnicalEnglishText(normalized)
    );
  }
  if (language === "ja-JP") {
    return containsJapaneseText(normalized) || isShortTechnicalEnglishText(normalized);
  }
  if (language === "ko-KR") {
    return containsKoreanText(normalized) || isShortTechnicalEnglishText(normalized);
  }
  return (
    !containsChineseText(normalized) &&
    !containsJapaneseText(normalized) &&
    !containsKoreanText(normalized)
  );
}

export function skillSectionTargetView(section: TrainerSkillSection): ActiveWorkbenchView {
  switch (section) {
    case "Coach":
      return "coach";
    case "Plan":
      return "plan";
    case "Training":
      return "training";
    case "Resources":
      return "resources";
    case "Workspace":
      return "coach";
    case "Provider":
      return "settings";
  }
}

export type LocalCommandSuggestion = {
  id: SidebarControlCommandId;
  command: string;
  title: string;
  description: string;
  run: () => void;
};

export type ComposerDeckKind = "command" | "skill";

export type LocalSkillSuggestion = TrainerSkillCatalogItem;

export function resolveTheme(themePreference: ThemePreference): "light" | "dark" {
  if (themePreference === "light" || themePreference === "dark") {
    return themePreference;
  }

  if (document.body.classList.contains("vscode-light")) {
    return "light";
  }

  return "dark";
}

export function basename(value: string): string {
  const parts = value.split(/[\\/]/);
  return parts[parts.length - 1] || value;
}

export function effectiveConnectionState(
  connectionState: "starting" | "connected" | "offline",
): "starting" | "connected" | "offline" {
  return connectionState;
}

/** §六: the single blocking surface allowed to own the coach pane. */
export type CoachBlockingSurface =
  | "workspace-admission"
  | "provider-setup"
  | "provider-notice"
  | "recovering";

/**
 * §六 coach status arbitration. Explicit precedence so at most one blocking
 * surface is visible at a time:
 * workspace admission > neutral setup takeover > provider send-blocked notice
 * > stream recovery > none.
 */
export function resolveCoachBlockingSurface(input: {
  coachViewActive: boolean;
  workspaceSessionBlocked: boolean;
  neutralSetupTakeover: boolean;
  providerSendBlocked: boolean;
  streamRecovering: boolean;
}): CoachBlockingSurface | null {
  if (!input.coachViewActive) {
    return null;
  }
  if (input.workspaceSessionBlocked) {
    return "workspace-admission";
  }
  if (input.neutralSetupTakeover) {
    return "provider-setup";
  }
  if (input.providerSendBlocked) {
    return "provider-notice";
  }
  if (input.streamRecovering) {
    return "recovering";
  }
  return null;
}

export function planStageStatusLabel(status: PlanStage["status"], t: Copy): string {
  if (status === "done") {
    return t.stageDone;
  }
  if (status === "active") {
    return t.stageActive;
  }
  return t.stageQueued;
}

export function contextDetailLabel(value: "focused" | "balanced" | "full", t: Copy): string {
  if (value === "focused") {
    return t.detailFocused;
  }
  if (value === "full") {
    return t.detailFull;
  }
  return t.detailBalanced;
}

export function answerModeLabel(value: CoachAnswerMode, t: Copy): string {
  if (value === "auto") {
    return t.auto;
  }
  if (value === "coach-first") {
    return t.coachFirst;
  }
  if (value === "direct") {
    return t.direct;
  }
  return t.balanced;
}

export function teachingStyleLabel(value: TeachingStyle, t: Copy): string {
  if (value === "auto") {
    return t.auto;
  }
  if (value === "concept-first") {
    return t.teachingConceptFirst;
  }
  if (value === "hands-on") {
    return t.teachingHandsOn;
  }
  if (value === "challenging") {
    return t.teachingChallenging;
  }
  return t.teachingGuided;
}

export function coachDefaultsNoteIntro(
  language: ComposerLanguage,
  saveState: "saved" | "unsaved" | "empty",
): string {
  switch (language) {
    case "zh-CN":
      return saveState === "saved"
        ? "\u8FD9\u4E9B\u9ED8\u8BA4\u503C\u4F1A\u7528\u4E8E\u4E0B\u4E00\u8F6E\u6559\u7EC3\u3002"
        : saveState === "unsaved"
          ? "\u8349\u7A3F\u8FD8\u4E0D\u4F1A\u751F\u6548\u3002"
          : "\u8FD8\u6CA1\u6709\u5199\u5165\u5F53\u524D\u5DE5\u4F5C\u533A\u3002";
    case "es-ES":
      return saveState === "saved"
        ? "Estos valores se aplican al siguiente turno del coach."
        : saveState === "unsaved"
          ? "Los cambios del borrador no se aplican hasta guardar."
          : "Todav\u00EDa no se ha escrito nada en este workspace.";
    case "fr-FR":
      return saveState === "saved"
        ? "Ces valeurs s'appliquent au prochain tour du coach."
        : saveState === "unsaved"
          ? "Le brouillon ne s'applique pas avant l'enregistrement."
          : "Rien n'est encore enregistr\u00E9 dans cet espace de travail.";
    case "de-DE":
      return saveState === "saved"
        ? "Diese Vorgaben gelten ab der n\u00E4chsten Coach-Nachricht."
        : saveState === "unsaved"
          ? "Entwurfs\u00E4nderungen gelten erst nach dem Speichern."
          : "In diesen Workspace wurde noch nichts geschrieben.";
    case "ja-JP":
      return saveState === "saved"
        ? "\u3053\u306E\u65E2\u5B9A\u5024\u306F\u6B21\u306E coach turn \u304B\u3089\u4F7F\u308F\u308C\u307E\u3059\u3002"
        : saveState === "unsaved"
          ? "Draft \u306E\u5909\u66F4\u306F\u4FDD\u5B58\u3059\u308B\u307E\u3067\u53CD\u6620\u3055\u308C\u307E\u305B\u3093\u3002"
          : "\u3053\u306E workspace \u306B\u306F\u307E\u3060\u4FDD\u5B58\u3055\u308C\u3066\u3044\u307E\u305B\u3093\u3002";
    case "ko-KR":
      return saveState === "saved"
        ? "\uC774 \uAE30\uBCF8\uAC12\uC740 \uB2E4\uC74C coach turn\uBD80\uD130 \uC801\uC6A9\uB429\uB2C8\uB2E4."
        : saveState === "unsaved"
          ? "Draft \uBCC0\uACBD\uC740 \uC800\uC7A5 \uC804\uAE4C\uC9C0 \uC801\uC6A9\uB418\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4."
          : "\uC774 workspace\uC5D0\uB294 \uC544\uC9C1 \uC800\uC7A5\uB41C \uB0B4\uC6A9\uC774 \uC5C6\uC2B5\uB2C8\uB2E4.";
    case "pt-BR":
      return saveState === "saved"
        ? "Esses padr\u00F5es valem no pr\u00F3ximo turno do coach."
        : saveState === "unsaved"
          ? "As mudan\u00E7as do rascunho s\u00F3 valem depois de salvar."
          : "Ainda nada foi salvo neste workspace.";
    default:
      return saveState === "saved"
        ? "These defaults apply to the next coach turn."
        : saveState === "unsaved"
          ? "Draft changes stay local until save."
          : "Nothing has been written to this workspace yet.";
  }
}

export function autoAnswerModeNote(language: ComposerLanguage, t: Copy): string {
  const balanced = answerModeLabel("balanced", t);
  const direct = answerModeLabel("direct", t);
  switch (language) {
    case "zh-CN":
      return `反馈 Auto 会按场景和学科调整：remote / debug / function guidance 更偏 ${balanced}，数学、语言和书本材料会先稳住结构，明显卡住时更偏 ${direct}。`;
    case "es-ES":
      return `El modo Auto de respuesta se ajusta por escena y materia: remote, debug y function guidance se inclinan por ${balanced}; matem\u00E1ticas, idiomas y libros se mantienen m\u00E1s estructurados; si te bloqueas de verdad, se acerca a ${direct}.`;
    case "fr-FR":
      return `Le mode de r\u00E9ponse Auto s'ajuste selon la sc\u00E8ne et la mati\u00E8re : remote, debug et function guidance penchent vers ${balanced} ; maths, langues et livres restent plus structur\u00E9s ; en blocage clair, il penche vers ${direct}.`;
    case "de-DE":
      return `Der Auto-Antwortmodus passt sich nach Szene und Fach an: remote, debug und function guidance gehen eher zu ${balanced}; Mathe, Sprache und B\u00FCcher bleiben strukturierter; bei klarer Blockade eher zu ${direct}.`;
    case "ja-JP":
      return `Auto の response style は scene と subject ごとに調整されます。remote / debug / function guidance では ${balanced} 寄りになり、数学・言語・書籍では構造を先に保ち、明確に詰まったときは ${direct} 寄りになります。`;
    case "ko-KR":
      return `Auto response style\uB294 scene\uACFC subject\uC5D0 \uB530\uB77C \uC870\uC815\uB429\uB2C8\uB2E4. remote / debug / function guidance\uC5D0\uC11C\uB294 ${balanced} \uCABD, \uC218\uD559\u30FB\uC5B8\uC5B4\u30FB\uCC45 \uC8FC\uC81C\uB294 \uAD6C\uC870\uB97C \uBA3C\uC800 \uC7A1\uACE0, \uBA85\uD655\uD788 \uB9C9\uD790 \uB54C\uB294 ${direct} \uCABD\uC73C\uB85C \uAE30\uC6B8\uC5B4\uC9D1\uB2C8\uB2E4.`;
    case "pt-BR":
      return `O modo Auto de resposta se ajusta por cena e assunto: remote, debug e function guidance tendem a ${balanced}; matem\u00E1tica, idiomas e livros ficam mais estruturados; quando voc\u00EA trava de verdade, ele pende para ${direct}.`;
    default:
      return `Auto answer mode adapts by scene and subject: remote, debug, and function guidance lean ${balanced}; math, language, and book-based turns stay more structured; clearly blocked turns lean ${direct}.`;
  }
}

export function autoTeachingStyleNote(language: ComposerLanguage, t: Copy): string {
  const handsOn = teachingStyleLabel("hands-on", t);
  const conceptFirst = teachingStyleLabel("concept-first", t);
  const challenging = teachingStyleLabel("challenging", t);
  switch (language) {
    case "zh-CN":
      return `教学 Auto 也会按场景和学科调整：remote / debug 更偏 ${handsOn}，function guidance 更偏 ${conceptFirst}，数学、语言和书本材料会先讲结构再练，卡住时回到 ${handsOn}；你想先自己试时也会切到 ${challenging}。`;
    case "es-ES":
      return `El estilo Auto de ense\u00F1anza tambi\u00E9n se ajusta por escena y materia: remote y debug se inclinan por ${handsOn}, function guidance por ${conceptFirst}, y matem\u00E1ticas, idiomas y libros explican primero la estructura antes de practicar. Si te bloqueas vuelve a ${handsOn}; si quieres probar primero, cambia a ${challenging}.`;
    case "fr-FR":
      return `Le style Auto d'enseignement s'ajuste aussi selon la sc\u00E8ne et la mati\u00E8re : remote et debug penchent vers ${handsOn}, function guidance vers ${conceptFirst}, et maths, langues et livres posent d'abord la structure avant la pratique. En blocage, retour \u00E0 ${handsOn} ; si tu veux essayer d'abord, passage possible vers ${challenging}.`;
    case "de-DE":
      return `Der Auto-Lehrstil passt sich ebenfalls nach Szene und Fach an: remote und debug gehen eher zu ${handsOn}, function guidance eher zu ${conceptFirst}, und Mathe, Sprache sowie B\u00FCcher kl\u00E4ren erst die Struktur vor der \u00Dcbung. Bei Blockade zur\u00FCck zu ${handsOn}; wenn du erst selbst probieren willst, auch ${challenging}.`;
    case "ja-JP":
      return `Auto の teaching style も scene と subject ごとに調整されます。remote / debug では ${handsOn} 寄り、function guidance では ${conceptFirst} 寄り、数学・言語・書籍では構造を先に整えてから練習に入ります。詰まった turn では ${handsOn} に戻り、先に自分で試したいときは ${challenging} にも切り替わります。`;
    case "ko-KR":
      return `Auto teaching style\uB3C4 scene\uACFC subject\uC5D0 \uB530\uB77C \uC870\uC815\uB429\uB2C8\uB2E4. remote / debug\uB294 ${handsOn}, function guidance\uB294 ${conceptFirst} \uCABD\uC73C\uB85C \uAE30\uC6B8\uACE0, \uC218\uD559\u30FB\uC5B8\uC5B4\u30FB\uCC45 \uC8FC\uC81C\uB294 \uAD6C\uC870\uB97C \uBA3C\uC800 \uC7A1\uACE0 \uC5F0\uC2B5\uD569\uB2C8\uB2E4. \uB9C9\uD788\uBA74 ${handsOn}\uC73C\uB85C \uB3CC\uC544\uAC00\uACE0, \uBA3C\uC800 \uD574\uBCF4\uACE0 \uC2F6\uC73C\uBA74 ${challenging}\uB85C \uBC14\uB014 \uC218\uB3C4 \uC788\uC2B5\uB2C8\uB2E4.`;
    case "pt-BR":
      return `O estilo Auto de ensino tamb\u00E9m se ajusta por cena e assunto: remote e debug tendem a ${handsOn}, function guidance a ${conceptFirst}, e matem\u00E1tica, idiomas e livros explicam primeiro a estrutura antes da pr\u00E1tica. Se travar, volta para ${handsOn}; se quiser tentar primeiro, pode mudar para ${challenging}.`;
    default:
      return `Auto teaching style also adapts by scene and subject: remote and debug lean ${handsOn}, function guidance leans ${conceptFirst}, and math, language, and book-based study explain structure before practice. Blocked turns return to ${handsOn}; try-first turns can switch to ${challenging}.`;
  }
}

export function coachDefaultsStatusNote(input: {
  language: ComposerLanguage;
  saveState: "saved" | "unsaved" | "empty";
  answerMode: CoachAnswerMode;
  teachingStyle: TeachingStyle;
  t: Copy;
}): string {
  const details: string[] = [];
  if (input.answerMode === "auto") {
    details.push(autoAnswerModeNote(input.language, input.t));
  }
  if (input.teachingStyle === "auto") {
    details.push(autoTeachingStyleNote(input.language, input.t));
  }
  const intro = coachDefaultsNoteIntro(input.language, input.saveState);
  return details.length > 0 ? [intro, ...details].join(" ") : intro;
}

export function formatToggleValue(enabled: boolean, t: Copy): string {
  return enabled ? t.on : t.off;
}

export function formatContextBundleValue(
  config: {
    followCurrentFile: boolean;
    contextDetail: "focused" | "balanced" | "full";
    includeCurrentFile: boolean;
    includeSelection: boolean;
    includeDiagnostics: boolean;
    includeRelatedFiles: boolean;
  },
  t: Copy,
): string {
  const enabledAttachments = [
    config.includeCurrentFile ? t.file : null,
    config.includeSelection ? t.selection : null,
    config.includeDiagnostics ? t.diagnostics : null,
    config.includeRelatedFiles ? t.relatedFiles : null,
  ].filter(Boolean) as string[];
  const attachmentLabel = enabledAttachments.length > 0 ? enabledAttachments.join(" / ") : t.off;
  return [
    `${t.follow} ${formatToggleValue(config.followCurrentFile, t)}`,
    `${t.contextDetail} ${contextDetailLabel(config.contextDetail, t)}`,
    attachmentLabel,
  ].join(" · ");
}

export function formatCoachDefaultsValue(
  config: {
    language: ComposerLanguage;
    answerMode: CoachAnswerMode;
    teachingStyle: TeachingStyle;
    memoryScope: "project" | "personal" | "session";
    workingSetMode: "focused" | "balanced" | "broad";
    reviewCadence: "light" | "steady" | "active";
    reviewReminderMode: "due" | "ahead" | "digest";
  },
  t: Copy,
): string {
  // Endonym display: a language's own name stays native in every UI language.
  const languageLabel = config.language === "zh-CN" ? "中文" : "English";
  const summaryLanguage = config.language;
  const memoryScopeMap = {
    project: appUiCopy(summaryLanguage, "当前项目"),
    personal: appUiCopy(summaryLanguage, "个人通用"),
    session: appUiCopy(summaryLanguage, "仅本次会话"),
  } as const;
  const workingSetMap = {
    focused: appUiCopy(summaryLanguage, "只跟当前任务"),
    balanced: appUiCopy(summaryLanguage, "兼顾邻近文件"),
    broad: appUiCopy(summaryLanguage, "允许更宽引用"),
  } as const;
  const reviewCadenceMap = {
    light: appUiCopy(summaryLanguage, "轻量"),
    steady: appUiCopy(summaryLanguage, "标准"),
    active: appUiCopy(summaryLanguage, "紧凑"),
  } as const;
  const reviewReminderMap = {
    due: appUiCopy(summaryLanguage, "到期"),
    ahead: appUiCopy(summaryLanguage, "提前"),
    digest: appUiCopy(summaryLanguage, "合并"),
  } as const;

  return [
    languageLabel,
    answerModeLabel(config.answerMode, t),
    teachingStyleLabel(config.teachingStyle, t),
    memoryScopeMap[config.memoryScope],
    workingSetMap[config.workingSetMode],
    reviewCadenceMap[config.reviewCadence],
    reviewReminderMap[config.reviewReminderMode],
  ].join(" · ");
}

export function compactDefinedValues(values: Array<string | null | undefined>, fallback: string): string {
  const resolved = values.filter(Boolean) as string[];
  return resolved.length > 0 ? resolved.join(" · ") : fallback;
}

export function truncateInlineText(value: string | undefined, limit = 56): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return undefined;
  }
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}

export function isTerminallyTruncatedText(value: string | undefined): boolean {
  return /(?:…|\.{3})\s*$/u.test(value?.trim() ?? "");
}

export function normalizeInlineComparisonText(value: string | undefined): string {
  return value?.replace(/\s+/g, " ").trim().toLowerCase() ?? "";
}

export function pickFirstText(...values: Array<string | undefined | null>): string | undefined {
  return values.find((value) => Boolean(value?.trim()))?.trim();
}

// Training evidence text (evaluator summaries, handoff templates, card-router
// routing defaults) is localized by the sidecar per the workspace response
// language, so the view uses host text directly via pickFirstText — no
// language-alignment re-picking layer.

export function pickLanguageAlignedTrainingList(
  language: ComposerLanguage,
  values: Array<string | undefined | null>,
): string[] {
  const normalized = values
    .map((value) => value?.trim())
    .filter((value): value is string => Boolean(value));
  const aligned = normalized.filter((value) => isLanguageAlignedUiText(language, value));
  if (aligned.length > 0) {
    return Array.from(new Set(aligned));
  }
  if (language === "zh-CN") {
    return Array.from(new Set(normalized.filter((value) => !looksLikeChineseMojibake(value))));
  }
  return [];
}

export function joinInlineMeta(values: Array<string | undefined | null>): string | undefined {
  const resolved = values
    .map((value) => value?.trim())
    .filter((value): value is string => Boolean(value));
  return resolved.length > 0 ? resolved.join(" · ") : undefined;
}

export function trainingExpectedSymbols(...groups: Array<string[] | undefined>): string[] {
  return Array.from(
    new Set(
      groups
        .flatMap((group) => group ?? [])
        .map((symbol) => symbol.trim())
        .filter(Boolean),
    ),
  );
}

export type TrainingSubjectCard = {
  learningFamily?: TrainingLearningFamily;
  learningSubtype?: string;
  knowledgeType?: string;
  scenarioPack?: string;
  focusArea?: string;
  targetSkill?: string;
  problemStatement?: string;
  scenario?: string;
  filesToTouch?: string[];
  apiHints?: string[];
  expectedSymbols?: string[];
};

export function normalizeTrainingLearningFamily(value: string | undefined): TrainingLearningFamily | undefined {
  return value === "code" || value === "theory" ? value : undefined;
}

export function resolveTrainingLearningSubtype(...values: Array<string | undefined>): string | undefined {
  return values.find((value) => Boolean(value?.trim()))?.trim();
}

export function resolveTrainingLearningFamily(...cards: Array<TrainingSubjectCard | undefined>): TrainingLearningFamily {
  for (const card of cards) {
    const explicit = normalizeTrainingLearningFamily(card?.learningFamily);
    if (explicit) {
      return explicit;
    }
    const subtype = card?.learningSubtype?.trim().toLowerCase();
    if (subtype && ["remote", "debug", "function", "implementation"].includes(subtype)) {
      return "code";
    }
    if (subtype && ["derivation", "writing", "memorization", "reading", "concept"].includes(subtype)) {
      return "theory";
    }
  }

  const scenarioPack = cards
    .map((card) => card?.scenarioPack?.trim().toLowerCase())
    .find(Boolean);
  if (
    scenarioPack &&
    [
      "remote_workspace",
      "remote_boundary",
      "debug_loop",
      "minimal_debug_loop",
      "function_guidance",
      "function_contract_recovery",
    ].includes(scenarioPack)
  ) {
    return "code";
  }

  if (
    cards.some(
      (card) =>
        Boolean(card?.filesToTouch?.length) ||
        Boolean(card?.apiHints?.length) ||
        Boolean(card?.expectedSymbols?.length),
    )
  ) {
    return "code";
  }

  const blob = cards
    .flatMap((card) => [
      card?.knowledgeType,
      card?.scenarioPack,
      card?.learningSubtype,
      card?.focusArea,
      card?.targetSkill,
      card?.problemStatement,
      card?.scenario,
    ])
    .filter((value): value is string => Boolean(value?.trim()))
    .join(" ")
    .toLowerCase();

  if (
    /(remote|debug|breakpoint|launch\.json|signature help|call site|hover|definition|workspace|repo|repository|api|protocol|endpoint|patch|refactor|test|diagnostic|ssh|wsl|dev container|code|function)/u.test(
      blob,
    )
  ) {
    return "code";
  }

  if (
    /(math|deriv|proof|equation|calculus|reading|passage|essay|sentence|grammar|translation|memor|recall|flash|book|novel|medicine|politics|history|concept)/u.test(
      blob,
    )
  ) {
    return "theory";
  }

  return "theory";
}

export function resolveTrainingPracticeVerificationMode(input: {
  cardType: "practice" | "flash";
  learningFamily: TrainingLearningFamily;
}): "file" | "manual" {
  if (input.cardType !== "practice") {
    return "manual";
  }
  return input.learningFamily === "code" ? "file" : "manual";
}

export function firstTrainingCardOfType<T extends { type?: string }>(
  cards: readonly T[] | undefined,
  type: "practice" | "flash",
): T | undefined {
  return cards?.find((card) => card.type === type);
}

export function restoredTrainingCard(
  trainingState: WorkspaceTrainingState | undefined,
  restoreContext: TrainingRestoreContext | undefined,
): TrainingCardCandidate | undefined {
  const target = restoreContext?.target;
  const scenarioLab = trainingState?.scenarioLab;
  const theoryDrill = trainingState?.theoryDrill;
  const reviewArtifact = trainingState?.reviewArtifact;
  const nextHop = trainingState?.latestTrainingNextHop;

  const scenarioLabCard =
    scenarioLab?.id &&
    (!restoreContext?.scenarioLabId || restoreContext.scenarioLabId === scenarioLab.id)
      ? {
          cardId: scenarioLab.id,
          type: "practice" as const,
          title: scenarioLab.title ?? "Scenario practice",
          focusArea: scenarioLab.focusArea,
          targetSkill: scenarioLab.focusArea,
          scenario: scenarioLab.summary,
          problemStatement: scenarioLab.summary,
          learnerDeliverables: scenarioLab.learnerDeliverables,
          verificationSteps: scenarioLab.verificationSteps,
          successSignal: scenarioLab.successSignal,
          returnWith: scenarioLab.migrateBackGuidance?.[0],
          nextAfterCompletion: scenarioLab.migrateBackGuidance?.[0],
        }
      : undefined;
  const theoryQuestion = theoryDrill?.questions?.[0];
  const theoryDrillCard =
    theoryDrill?.id &&
    (!restoreContext?.theoryDrillId || restoreContext.theoryDrillId === theoryDrill.id)
      ? {
          cardId: theoryDrill.id,
          type: "flash" as const,
          title: theoryDrill.title ?? "Theory drill",
          focusArea: theoryDrill.focusArea,
          targetSkill: theoryDrill.focusArea,
          question: theoryQuestion?.prompt,
          choices: theoryQuestion?.choices,
          expectedAnswer: theoryQuestion?.answer,
          problemStatement: theoryDrill.summary,
          successSignal: theoryDrill.successSignal,
          returnWith: theoryDrill.returnWith,
        }
      : undefined;
  const reviewArtifactCard =
    reviewArtifact?.id &&
    (!restoreContext?.reviewArtifactId || restoreContext.reviewArtifactId === reviewArtifact.id)
      ? {
          cardId: reviewArtifact.id,
          type: "practice" as const,
          learningFamily: "theory" as const,
          learningPhase: "reflect" as const,
          title: reviewArtifact.focusArea
            ? (reviewArtifact.title ?? "Review recovery").replace(
                reviewArtifact.focusArea, reviewConceptLabel(reviewArtifact.focusArea),
              )
            : reviewArtifact.title ?? "Review recovery",
          focusArea: reviewArtifact.focusArea,
          targetSkill: reviewArtifact.focusArea,
          deliverable: reviewArtifact.summary,
          reflectionPrompt: reviewArtifact.guardrail,
          problemStatement: reviewArtifact.summary ?? reviewArtifact.rootCause,
          learnerDeliverables: reviewArtifact.recommendedActions,
          verificationSteps: [reviewArtifact.nextSelfImplementationRule].filter(
            (value): value is string => Boolean(value?.trim()),
          ),
          successSignal: reviewArtifact.verifiedResult,
          returnWith: reviewArtifact.nextSelfImplementationRule,
        }
      : undefined;
  const nextHopCard =
    nextHop && (nextHop.targetId || nextHop.candidateId || nextHop.title || nextHop.cardTitle)
      ? {
          cardId: nextHop.targetId ?? nextHop.candidateId ?? "next-hop",
          type: nextHop.cardType ?? "practice",
          title: nextHop.cardTitle ?? nextHop.title ?? "Next training step",
          focusArea: trainingState?.latestLearningFocusArea,
          targetSkill: trainingState?.latestLearningFocusArea,
          scenario: nextHop.summary,
          problemStatement: nextHop.summary,
          whyNow: nextHop.whyNow,
          nextAfterCompletion: nextHop.nextAfterCompletion,
          stuckRecovery: nextHop.fallbackAction,
        }
      : undefined;

  if (target === "scenario_lab") {
    return scenarioLabCard;
  }
  if (target === "theory_drill") {
    return theoryDrillCard;
  }
  if (target === "review_artifact") {
    return reviewArtifactCard;
  }
  if (target === "next_hop") {
    return nextHopCard;
  }

  return nextHopCard ?? scenarioLabCard ?? theoryDrillCard ?? reviewArtifactCard;
}

export function formatSparseWorkspaceControlValue(workspace: WorkspaceSettingsSnapshot, t: Copy): string | undefined {
  const values = [
    workspace.followCurrentFile !== undefined
      ? `${t.follow} ${formatToggleValue(workspace.followCurrentFile, t)}`
      : null,
    workspace.contextDetail ? `${t.contextDetail} ${contextDetailLabel(workspace.contextDetail, t)}` : null,
    workspace.includeCurrentFile !== undefined
      ? `${t.file} ${formatToggleValue(workspace.includeCurrentFile, t)}`
      : null,
    workspace.includeSelection !== undefined
      ? `${t.selection} ${formatToggleValue(workspace.includeSelection, t)}`
      : null,
    workspace.includeDiagnostics !== undefined
      ? `${t.diagnostics} ${formatToggleValue(workspace.includeDiagnostics, t)}`
      : null,
    workspace.includeRelatedFiles !== undefined
      ? `${t.relatedFiles} ${formatToggleValue(workspace.includeRelatedFiles, t)}`
      : null,
  ];
  return compactDefinedValues(values, t.noContext);
}

export function formatSparseCoachDefaultsSavedValue(
  workspace: WorkspaceSettingsSnapshot,
  t: Copy,
  teachingStyle: TeachingStyle,
): string | undefined {
  const defaults = workspace.coachDefaults;
  const summaryLanguage = workspace.responseLanguage ?? "en-US";
  const memoryScopeMap = {
    project: appUiCopy(summaryLanguage, "当前项目"),
    personal: appUiCopy(summaryLanguage, "个人通用"),
    session: appUiCopy(summaryLanguage, "仅本次会话"),
  } as const;
  const workingSetMap = {
    focused: appUiCopy(summaryLanguage, "只跟当前任务"),
    balanced: appUiCopy(summaryLanguage, "兼顾邻近文件"),
    broad: appUiCopy(summaryLanguage, "允许更宽引用"),
  } as const;
  const reviewCadenceMap = {
    light: appUiCopy(summaryLanguage, "轻量"),
    steady: appUiCopy(summaryLanguage, "标准"),
    active: appUiCopy(summaryLanguage, "紧凑"),
  } as const;
  const reviewReminderMap = {
    due: appUiCopy(summaryLanguage, "到期"),
    ahead: appUiCopy(summaryLanguage, "提前"),
    digest: appUiCopy(summaryLanguage, "合并"),
  } as const;
  const values = [
    workspace.responseLanguage ? (workspace.responseLanguage === "zh-CN" ? "中文" : "English") : null,
    workspace.answerMode ? answerModeLabel(workspace.answerMode, t) : null,
    teachingStyleLabel(teachingStyle, t),
    defaults?.memoryScope ? memoryScopeMap[defaults.memoryScope] : null,
    defaults?.workingSetMode ? workingSetMap[defaults.workingSetMode] : null,
    defaults?.reviewCadence ? reviewCadenceMap[defaults.reviewCadence] : null,
    defaults?.reviewReminderMode ? reviewReminderMap[defaults.reviewReminderMode] : null,
    defaults?.workspaceMemoryToggles?.decisions !== undefined
      ? `${appUiCopy(summaryLanguage, "架构决策")} ${formatToggleValue(defaults.workspaceMemoryToggles.decisions, t)}`
      : null,
    defaults?.workspaceMemoryToggles?.patterns !== undefined
      ? `${appUiCopy(summaryLanguage, "常用模式")} ${formatToggleValue(defaults.workspaceMemoryToggles.patterns, t)}`
      : null,
    defaults?.workspaceMemoryToggles?.resources !== undefined
      ? `${appUiCopy(summaryLanguage, "参考资料")} ${formatToggleValue(defaults.workspaceMemoryToggles.resources, t)}`
      : null,
  ];
  const result = values.filter(Boolean) as string[];
  return result.length > 0 ? result.join(" · ") : undefined;
}

export function providerModelRuntimeNote(provider: ProviderConfigView, language: ComposerLanguage): string {
  if (!provider.configured) {
    return providerRecoverySummary(provider, language).detail;
  }

  if (!provider.apiKeyConfigured) {
    return providerRecoverySummary(provider, language).detail;
  }

  const modelCount = provider.availableModels.length;

  if (provider.modelListStatus === "error") {
    return providerRecoverySummary(provider, language).detail;
  }

  if (modelCount > 0) {
    return appUiCopy(language, "当前连接已可用，可选 {v} 个模型。").replace("{v}", String(modelCount));
  }

  if (provider.modelListStatus === "loading") {
    return appUiCopy(language, "正在更新可选模型。");
  }

  return appUiCopy(language, "当前连接已保存。可以测试连接或更新模型列表。");
}

export function providerModelMenuNote(provider: ProviderConfigView, language: ComposerLanguage): string {
  if (!provider.configured) {
    return providerRecoverySummary(provider, language).title;
  }

  if (!provider.apiKeyConfigured) {
    return providerRecoverySummary(provider, language).title;
  }

  if (provider.modelListStatus === "error") {
    return providerRecoverySummary(provider, language).title;
  }

  if (provider.modelListStatus === "loading") {
    return providerRecoverySummary(provider, language).title;
  }

  if (provider.availableModels.length > 0) {
    return appUiCopy(language, "{v} 个可选模型").replace("{v}", String(provider.availableModels.length));
  }

  return appUiCopy(language, "连接已保存");
}

export function providerHasVerifiedToolsProbe(
  provider: Pick<ProviderConfigView, "lastTestResult">,
): boolean {
  const lastTest = provider.lastTestResult;
  const toolsEvidence = lastTest?.capabilityEvidence?.find(
    (entry) => entry.name.trim().toLowerCase() === "tools",
  );

  return (
    lastTest?.ok === true &&
    lastTest.toolsReady === true &&
    lastTest.toolProbeStatus === "verified" &&
    toolsEvidence?.state === "verified" &&
    toolsEvidence.observed === true
  );
}

export type ProviderSettingsLocale = {
  modelPicker: {
    currentModel: string;
    onlyCurrentModel: string;
  };
  draftKey: string;
  draftNotApplied: string;
  feedback: {
    save: { failure: string; success: string };
    refresh: { failure: string; success: string };
    test: { failure: string; needsSetup: string; success: string };
    clear: { failure: string; success: string };
    open: { failure: string; success: string };
    coach: { failure: string; restored: string; success: string };
  };
  pending: {
    save: { detail: string; title: string };
    refresh: { detail: string; title: string };
    test: { detail: string; title: string };
    clear: { detail: string; title: string };
    open: { detail: string; title: string };
  };
  menu: {
    chooseModel: string;
    currentConnection: string;
    manageModels: string;
    model: string;
    modelEntry: string;
    savedConnections: string;
    saveConnectionFirst: string;
    switchModel: string;
    switchModelWithConnection: string;
  };
};

export const providerSettingsCopy: Record<ComposerLanguage, ProviderSettingsLocale> = {
  "zh-CN": {
    modelPicker: {
      currentModel: "\u5f53\u524d\u6a21\u578b",
      onlyCurrentModel: "\u6b63\u5728\u4f7f\u7528\u8fd9\u4e2a\u6a21\u578b\u3002",
    },
    draftKey: "新密钥",
    draftNotApplied: "当前仍在使用已保存的连接。保存后才会切换到这组草稿。",
    feedback: {
      save: { failure: "未能保存", success: "已保存" },
      refresh: { failure: "未能更新", success: "模型已更新" },
      test: { failure: "未能检查", needsSetup: "还差一步", success: "已检查" },
      clear: { failure: "未能清除", success: "已清除" },
      open: { failure: "未能打开", success: "已打开" },
      coach: { failure: "未能保存", restored: "已恢复默认", success: "已同步" },
    },
    pending: {
      save: { title: "正在保存", detail: "正在保存这组连接。" },
      refresh: { title: "正在查找模型", detail: "正在查看这组连接可用的模型。" },
      test: { title: "正在检查", detail: "正在检查这组连接能否使用。" },
      clear: { title: "正在清除", detail: "正在移除这组已保存的连接。" },
      open: { title: "正在打开", detail: "正在打开此项目的 Trainer 设置。" },
    },
    menu: {
      chooseModel: "选择模型",
      currentConnection: "当前连接",
      manageModels: "管理模型和连接",
      model: "模型",
      modelEntry: "模型入口",
      savedConnections: "已保存的连接",
      saveConnectionFirst: "先在设置中保存一组连接",
      switchModel: "切换模型：{model}",
      switchModelWithConnection: "切换模型：{model} · {connection}",
    },
  },
  "en-US": {
    modelPicker: {
      currentModel: "Current model",
      onlyCurrentModel: "You're using this model.",
    },
    draftKey: "New key",
    draftNotApplied: "The saved connection is still in use. Save this draft to switch.",
    feedback: {
      save: { failure: "Could not save", success: "Saved" },
      refresh: { failure: "Could not update", success: "Models updated" },
      test: { failure: "Could not check", needsSetup: "Setup needed", success: "Checked" },
      clear: { failure: "Could not clear", success: "Cleared" },
      open: { failure: "Could not open", success: "Opened" },
      coach: { failure: "Could not save", restored: "Defaults restored", success: "Synced" },
    },
    pending: {
      save: { title: "Saving", detail: "Saving this connection." },
      refresh: { title: "Finding models", detail: "Looking for models available to this connection." },
      test: { title: "Checking", detail: "Checking whether this connection can be used." },
      clear: { title: "Clearing", detail: "Removing this saved connection." },
      open: { title: "Opening", detail: "Opening Trainer settings for this project." },
    },
    menu: {
      chooseModel: "Choose model",
      currentConnection: "Current connection",
      manageModels: "Manage models and connections",
      model: "Model",
      modelEntry: "Model picker",
      savedConnections: "Saved connections",
      saveConnectionFirst: "Save a connection in Settings first",
      switchModel: "Switch model: {model}",
      switchModelWithConnection: "Switch model: {model} · {connection}",
    },
  },
  "es-ES": {
    modelPicker: {
      currentModel: "Modelo actual",
      onlyCurrentModel: "Est\u00e1s usando este modelo.",
    },
    draftKey: "Nueva clave",
    draftNotApplied: "La conexión guardada sigue en uso. Guarda este borrador para cambiarla.",
    feedback: {
      save: { failure: "No se pudo guardar", success: "Guardado" },
      refresh: { failure: "No se pudo actualizar", success: "Modelos actualizados" },
      test: { failure: "No se pudo comprobar", needsSetup: "Falta configurar", success: "Comprobado" },
      clear: { failure: "No se pudo borrar", success: "Borrado" },
      open: { failure: "No se pudo abrir", success: "Abierto" },
      coach: { failure: "No se pudo guardar", restored: "Valores restaurados", success: "Sincronizado" },
    },
    pending: {
      save: { title: "Guardando", detail: "Guardando esta conexión." },
      refresh: { title: "Buscando modelos", detail: "Buscando modelos para esta conexión." },
      test: { title: "Comprobando", detail: "Comprobando si esta conexión se puede usar." },
      clear: { title: "Borrando", detail: "Eliminando esta conexión guardada." },
      open: { title: "Abriendo", detail: "Abriendo los ajustes de Trainer para este proyecto." },
    },
    menu: {
      chooseModel: "Elegir modelo",
      currentConnection: "Conexión actual",
      manageModels: "Gestionar modelos y conexiones",
      model: "Modelo",
      modelEntry: "Selector de modelo",
      savedConnections: "Conexiones guardadas",
      saveConnectionFirst: "Guarda primero una conexión en Ajustes",
      switchModel: "Cambiar modelo: {model}",
      switchModelWithConnection: "Cambiar modelo: {model} · {connection}",
    },
  },
  "fr-FR": {
    modelPicker: {
      currentModel: "Mod\u00e8le actuel",
      onlyCurrentModel: "Vous utilisez ce mod\u00e8le.",
    },
    draftKey: "Nouvelle clé",
    draftNotApplied: "La connexion enregistrée reste utilisée. Enregistrez ce brouillon pour changer.",
    feedback: {
      save: { failure: "Enregistrement impossible", success: "Enregistré" },
      refresh: { failure: "Mise à jour impossible", success: "Modèles mis à jour" },
      test: { failure: "Vérification impossible", needsSetup: "Configuration requise", success: "Vérifié" },
      clear: { failure: "Suppression impossible", success: "Supprimé" },
      open: { failure: "Ouverture impossible", success: "Ouvert" },
      coach: { failure: "Enregistrement impossible", restored: "Réglages rétablis", success: "Synchronisé" },
    },
    pending: {
      save: { title: "Enregistrement", detail: "Enregistrement de cette connexion." },
      refresh: { title: "Recherche de modèles", detail: "Recherche des modèles pour cette connexion." },
      test: { title: "Vérification", detail: "Vérification de l'utilisation de cette connexion." },
      clear: { title: "Suppression", detail: "Suppression de cette connexion enregistrée." },
      open: { title: "Ouverture", detail: "Ouverture des réglages Trainer pour ce projet." },
    },
    menu: {
      chooseModel: "Choisir un modèle",
      currentConnection: "Connexion actuelle",
      manageModels: "Gérer les modèles et connexions",
      model: "Modèle",
      modelEntry: "Sélecteur de modèle",
      savedConnections: "Connexions enregistrées",
      saveConnectionFirst: "Enregistrez d'abord une connexion dans Réglages",
      switchModel: "Changer de modèle : {model}",
      switchModelWithConnection: "Changer de modèle : {model} · {connection}",
    },
  },
  "de-DE": {
    modelPicker: {
      currentModel: "Aktuelles Modell",
      onlyCurrentModel: "Dieses Modell wird gerade verwendet.",
    },
    draftKey: "Neuer Schlüssel",
    draftNotApplied: "Die gespeicherte Verbindung wird weiter verwendet. Speichere diesen Entwurf zum Wechseln.",
    feedback: {
      save: { failure: "Speichern nicht möglich", success: "Gespeichert" },
      refresh: { failure: "Aktualisierung nicht möglich", success: "Modelle aktualisiert" },
      test: { failure: "Prüfung nicht möglich", needsSetup: "Einrichtung nötig", success: "Geprüft" },
      clear: { failure: "Löschen nicht möglich", success: "Gelöscht" },
      open: { failure: "Öffnen nicht möglich", success: "Geöffnet" },
      coach: { failure: "Speichern nicht möglich", restored: "Standards wiederhergestellt", success: "Synchronisiert" },
    },
    pending: {
      save: { title: "Speichern", detail: "Diese Verbindung wird gespeichert." },
      refresh: { title: "Modelle suchen", detail: "Modelle für diese Verbindung werden gesucht." },
      test: { title: "Prüfen", detail: "Es wird geprüft, ob diese Verbindung funktioniert." },
      clear: { title: "Löschen", detail: "Diese gespeicherte Verbindung wird entfernt." },
      open: { title: "Öffnen", detail: "Trainer-Einstellungen für dieses Projekt werden geöffnet." },
    },
    menu: {
      chooseModel: "Modell wählen",
      currentConnection: "Aktuelle Verbindung",
      manageModels: "Modelle und Verbindungen verwalten",
      model: "Modell",
      modelEntry: "Modellauswahl",
      savedConnections: "Gespeicherte Verbindungen",
      saveConnectionFirst: "Speichere zuerst eine Verbindung in Einstellungen",
      switchModel: "Modell wechseln: {model}",
      switchModelWithConnection: "Modell wechseln: {model} · {connection}",
    },
  },
  "ja-JP": {
    modelPicker: {
      currentModel: "\u73fe\u5728\u306e\u30e2\u30c7\u30eb",
      onlyCurrentModel: "\u3053\u306e\u30e2\u30c7\u30eb\u3092\u4f7f\u7528\u4e2d\u3067\u3059\u3002",
    },
    draftKey: "新しいキー",
    draftNotApplied: "保存済みの接続を使用中です。この下書きを保存すると切り替わります。",
    feedback: {
      save: { failure: "保存できませんでした", success: "保存しました" },
      refresh: { failure: "更新できませんでした", success: "モデルを更新しました" },
      test: { failure: "確認できませんでした", needsSetup: "設定が必要です", success: "確認しました" },
      clear: { failure: "削除できませんでした", success: "削除しました" },
      open: { failure: "開けませんでした", success: "開きました" },
      coach: { failure: "保存できませんでした", restored: "初期設定に戻しました", success: "同期しました" },
    },
    pending: {
      save: { title: "保存中", detail: "この接続を保存しています。" },
      refresh: { title: "モデルを探しています", detail: "この接続で使えるモデルを確認しています。" },
      test: { title: "確認中", detail: "この接続を使えるか確認しています。" },
      clear: { title: "削除中", detail: "この保存済み接続を削除しています。" },
      open: { title: "開いています", detail: "このプロジェクトの Trainer 設定を開いています。" },
    },
    menu: {
      chooseModel: "モデルを選ぶ",
      currentConnection: "現在の接続",
      manageModels: "モデルと接続を管理",
      model: "モデル",
      modelEntry: "モデルの選択",
      savedConnections: "保存済みの接続",
      saveConnectionFirst: "先に設定で接続を保存してください",
      switchModel: "モデルを切り替え: {model}",
      switchModelWithConnection: "モデルを切り替え: {model} · {connection}",
    },
  },
  "ko-KR": {
    modelPicker: {
      currentModel: "\ud604\uc7ac \ubaa8\ub378",
      onlyCurrentModel: "\ud604\uc7ac \uc774 \ubaa8\ub378\uc744 \uc0ac\uc6a9 \uc911\uc785\ub2c8\ub2e4.",
    },
    draftKey: "새 키",
    draftNotApplied: "저장된 연결을 계속 사용 중입니다. 이 초안을 저장하면 전환됩니다.",
    feedback: {
      save: { failure: "저장할 수 없어요", success: "저장했어요" },
      refresh: { failure: "업데이트할 수 없어요", success: "모델을 업데이트했어요" },
      test: { failure: "확인할 수 없어요", needsSetup: "설정이 더 필요해요", success: "확인했어요" },
      clear: { failure: "지울 수 없어요", success: "지웠어요" },
      open: { failure: "열 수 없어요", success: "열었어요" },
      coach: { failure: "저장할 수 없어요", restored: "기본값으로 되돌렸어요", success: "동기화했어요" },
    },
    pending: {
      save: { title: "저장 중", detail: "이 연결을 저장하고 있어요." },
      refresh: { title: "모델을 찾는 중", detail: "이 연결에서 쓸 수 있는 모델을 찾고 있어요." },
      test: { title: "확인 중", detail: "이 연결을 사용할 수 있는지 확인하고 있어요." },
      clear: { title: "지우는 중", detail: "저장된 이 연결을 지우고 있어요." },
      open: { title: "여는 중", detail: "이 프로젝트의 Trainer 설정을 열고 있어요." },
    },
    menu: {
      chooseModel: "모델 선택",
      currentConnection: "현재 연결",
      manageModels: "모델과 연결 관리",
      model: "모델",
      modelEntry: "모델 선택기",
      savedConnections: "저장된 연결",
      saveConnectionFirst: "먼저 설정에서 연결을 저장하세요",
      switchModel: "모델 전환: {model}",
      switchModelWithConnection: "모델 전환: {model} · {connection}",
    },
  },
  "pt-BR": {
    modelPicker: {
      currentModel: "Modelo atual",
      onlyCurrentModel: "Este modelo est\u00e1 em uso.",
    },
    draftKey: "Nova chave",
    draftNotApplied: "A conexão salva continua em uso. Salve este rascunho para trocar.",
    feedback: {
      save: { failure: "Não foi possível salvar", success: "Salvo" },
      refresh: { failure: "Não foi possível atualizar", success: "Modelos atualizados" },
      test: { failure: "Não foi possível verificar", needsSetup: "Falta configurar", success: "Verificado" },
      clear: { failure: "Não foi possível limpar", success: "Limpo" },
      open: { failure: "Não foi possível abrir", success: "Aberto" },
      coach: { failure: "Não foi possível salvar", restored: "Padrões restaurados", success: "Sincronizado" },
    },
    pending: {
      save: { title: "Salvando", detail: "Salvando esta conexão." },
      refresh: { title: "Buscando modelos", detail: "Buscando modelos para esta conexão." },
      test: { title: "Verificando", detail: "Verificando se esta conexão pode ser usada." },
      clear: { title: "Limpando", detail: "Removendo esta conexão salva." },
      open: { title: "Abrindo", detail: "Abrindo as configurações do Trainer deste projeto." },
    },
    menu: {
      chooseModel: "Escolher modelo",
      currentConnection: "Conexão atual",
      manageModels: "Gerenciar modelos e conexões",
      model: "Modelo",
      modelEntry: "Seletor de modelo",
      savedConnections: "Conexões salvas",
      saveConnectionFirst: "Salve primeiro uma conexão em Configurações",
      switchModel: "Trocar modelo: {model}",
      switchModelWithConnection: "Trocar modelo: {model} · {connection}",
    },
  },
};

export function providerSettingsLocale(language: ComposerLanguage): ProviderSettingsLocale {
  return providerSettingsCopy[language] ?? providerSettingsCopy["en-US"];
}

export function buildSettingsFeedback(
  action: SettingsActionState | undefined,
  message: OperationMessage | undefined,
  language: ComposerLanguage,
  slot: SettingsFeedbackSlot,
): SettingsActionFeedback | undefined {
  if (!action || !message || message.tone === "info" || !action.targets.includes(slot)) {
    return undefined;
  }

  const normalized = message.message.toLowerCase();
  const isError = message.tone === "error";
  const copy = providerSettingsLocale(language);

  if (action.baselineMessageKey && normalized === action.baselineMessageKey) {
    return undefined;
  }

  if (action.kind === "save-provider") {
    // The host saves the connection even when the follow-up verification
    // fails. The structured outcome — not the message text — decides between
    // a clean pass and an honest "saved, but not verified yet" state.
    if (!isError && message.providerTest?.ok === false) {
      return {
        actionKind: action.kind,
        tone: "pending",
        title: copy.feedback.test.needsSetup,
        detail: sanitizeErrorSurfaceText(message.message, language),
      };
    }
    return {
      tone: isError ? "fail" : "pass",
      title: isError ? copy.feedback.save.failure : copy.feedback.save.success,
      detail: sanitizeErrorSurfaceText(message.message, language),
    };
  }

  if (action.kind === "refresh-provider-models") {
    return {
      tone: isError ? "fail" : "pass",
      title: isError ? copy.feedback.refresh.failure : copy.feedback.refresh.success,
      detail: sanitizeErrorSurfaceText(message.message, language),
    };
  }

  if (action.kind === "test-provider") {
    // A verifiably connected result must never read as "still pending", even when the
    // provider display name itself happens to contain setup-like words (e.g. the
    // "未配置模型服务" fallback name appears inside every success message).
    // The structured host outcome is authoritative; legacy string signals
    // remain as a fallback for older payloads.
    const connectedSignal =
      message.providerTest?.ok === true ||
      normalized.includes("is connected") ||
      normalized.includes("connected and ready") ||
      normalized.includes("provider reachable") ||
      normalized.includes("已连通") ||
      normalized.includes("连通成功") ||
      normalized.includes("服务已就绪");
    const pendingLike =
      !isError &&
      !connectedSignal &&
      message.providerTest?.ok === undefined &&
      (normalized.includes("skip") ||
        normalized.includes("skipped") ||
        normalized.includes("scaffold") ||
        normalized.includes("not configured") ||
        normalized.includes("未配置") ||
        normalized.includes("sidecar"));
    return {
      actionKind: action.kind,
      tone: isError ? "fail" : pendingLike ? "pending" : "pass",
      title: isError
        ? copy.feedback.test.failure
        : pendingLike
          ? copy.feedback.test.needsSetup
          : copy.feedback.test.success,
      detail: sanitizeErrorSurfaceText(message.message, language),
    };
  }

  if (action.kind === "clear-provider") {
    return {
      tone: isError ? "fail" : "pass",
      title: isError ? copy.feedback.clear.failure : copy.feedback.clear.success,
      detail: sanitizeErrorSurfaceText(message.message, language),
    };
  }

  if (action.kind === "open-config") {
    return {
      tone: isError ? "fail" : "pass",
      title: isError ? copy.feedback.open.failure : copy.feedback.open.success,
      detail: sanitizeErrorSurfaceText(message.message, language),
    };
  }

  if (action.kind === "save-coach" || action.kind === "reset-defaults") {
    return {
      tone: isError ? "fail" : "pass",
      title: isError
        ? copy.feedback.coach.failure
        : action.kind === "reset-defaults"
          ? copy.feedback.coach.restored
          : copy.feedback.coach.success,
      detail: sanitizeErrorSurfaceText(message.message, language),
    };
  }

  return undefined;
}
export function providerBlockingReason(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
): string | undefined {
  const sendState = describeProviderSendState(provider, language);
  // Sidecar connection state is informational only: the host lazy-starts and
  // retries per request, so it must never block composing or sending. A
  // missing streaming probe is likewise not a gate — the stream path already
  // degrades gracefully at runtime.
  if (sendState.blocked) {
    return providerRecoverySummary(provider, language, connectionState).detail;
  }
  return undefined;
}

export function reviewSurfaceModeLabel(
  value: "due" | "ahead" | "digest" | undefined,
  language: ComposerLanguage,
): string | undefined {
  if (value === "ahead") {
    return appUiCopy(language, "提前提醒");
  }
  if (value === "digest") {
    return appUiCopy(language, "合并回看");
  }
  if (value === "due") {
    return appUiCopy(language, "到期回看");
  }
  return undefined;
}

export function formatIntervalDays(days: number | undefined, language: ComposerLanguage): string | undefined {
  if (typeof days !== "number" || Number.isNaN(days)) {
    return undefined;
  }
  return appUiCopy(language, "{v} 天间隔").replace("{v}", String(days));
}

// Honest banded capability language — a single score must never surface as a
// fake numeric percent. Bands: independent / assisted / emerging / unverified.
export function formatMasteryScore(score: number | undefined, language: ComposerLanguage): string | undefined {
  if (typeof score !== "number" || Number.isNaN(score)) {
    return undefined;
  }
  if (score >= 0.8) {
    return appUiCopy(language, "掌握度：独立完成");
  }
  if (score >= 0.5) {
    return appUiCopy(language, "掌握度：有辅助完成");
  }
  if (score > 0) {
    return appUiCopy(language, "掌握度：初步接触");
  }
  return appUiCopy(language, "掌握度：待验证");
}

export function toPlanReviewItem(
  item: {
    concept: string;
    reason: string;
    dueAt?: string;
    source?: string;
    surfaceMode?: "due" | "ahead" | "digest";
    taskHint?: string;
    focusArea?: string;
    linkedContext?: string[];
    intervalDays?: number;
    masteryScore?: number;
  },
  index: number,
  language: ComposerLanguage,
): PlanReviewItem {
  const meta = [
    item.dueAt ? `${appUiCopy(language, "下次回看")}: ${formatReviewDueLabel(item.dueAt, language)}` : null,
    reviewSurfaceModeLabel(item.surfaceMode, language),
    formatIntervalDays(item.intervalDays, language),
    formatMasteryScore(item.masteryScore, language),
  ].filter(Boolean) as string[];
  return {
    id: `${item.source ?? "review"}-${item.concept}-${index}`,
    title: reviewConceptLabel(item.concept),
    detail: item.reason,
    meta: meta.length > 0 ? meta.join(" · ") : undefined,
    surfaceMode: item.surfaceMode,
    taskHint: item.taskHint,
    focusArea: item.focusArea,
    linkedContext: item.linkedContext,
    intervalDays: item.intervalDays,
    masteryScore: item.masteryScore,
  };
}

export function localizeAttachmentLabel(label: string, t: Copy): string {
  const normalized = label.trim().toLowerCase();
  if (normalized === "intent") {
    return t.analysisAction;
  }
  if (normalized === "file") {
    return t.file;
  }
  if (normalized === "selection") {
    return t.selection;
  }
  if (normalized === "related") {
    return t.relatedFiles;
  }
  if (normalized === "diagnostics") {
    return t.diagnostics;
  }
  return label;
}

export function localizeAttachmentValue(value: string, t: Copy): string {
  const normalized = value.trim().toLowerCase();
  if (normalized === "coach") {
    return t.coach;
  }
  if (normalized === "review") {
    return t.runReview;
  }
  if (normalized === "task") {
    return t.currentTask;
  }
  if (normalized === "plan") {
    return t.plan;
  }
  return value;
}

export function localizeContextNote(value: string | undefined, language: ComposerLanguage): string | undefined {
  if (!value) {
    return value;
  }

  if (language === "zh-CN" && value === "Attached active code context") {
    return "参考了当前代码上下文";
  }

  if (language === "zh-CN" && value === "Attached Python file context") {
    return "参考了 Python 文件上下文";
  }

  return value;
}

export function localizeConversationMessage(
  message: ConversationMessage,
  t: Copy,
  language: ComposerLanguage,
): ConversationMessage {
  return {
    ...message,
    body: message.body,
    author:
      message.role === "user" && message.author.trim().toLowerCase() === "you"
        ? t.you
        : message.role === "assistant" &&
            (message.author.trim().toLowerCase() === "trainer" ||
              message.author.trim().toLowerCase() === "coach")
          ? t.trainer
          : message.role === "system" && message.author.trim().toLowerCase() === "system"
            ? appUiCopy(language, "系统")
            : message.author,
    attachments: message.attachments?.map((attachment) => ({
      label: localizeAttachmentLabel(attachment.label, t),
      value: localizeAttachmentValue(attachment.value, t),
    })),
    contextNote: localizeContextNote(message.contextNote, language),
  };
}

export function coachingScenarioLabel(
  value: NonNullable<ReturnType<typeof useWorkbenchState.getState>["data"]["coachingState"]>["scenario"] | undefined,
  language: ComposerLanguage,
): string {
  return SCENARIO_TEXT[value ?? "general"]?.[language] ?? SCENARIO_TEXT.general[language];
}

export function normalizeTrainingStatus(value: string | undefined): string {
  return normalizeSharedTrainingStatus(value);
}

export function normalizeTrainingSubmode(value: string | undefined): string {
  return normalizeSharedTrainingSubmode(value);
}

export function isTrainingPrimerLike(input: {
  trainingSubmode?: string;
  selectedCardStatus?: string;
  latestTrainingHandoffStatus?: string;
}): boolean {
  return isSharedTrainingPrimerLike(input);
}

export function trainingCardStatusLabel(value: string | undefined, language: ComposerLanguage): string | undefined {
  const normalized = normalizeTrainingStatus(value);
  if (!normalized) {
    return undefined;
  }
  return TRAINING_CARD_STATUS_TEXT[normalized]?.[language] ?? value;
}

export function trainingHandoffStatusLabel(value: string | undefined, language: ComposerLanguage): string | undefined {
  const normalized = normalizeTrainingStatus(value);
  if (!normalized) {
    return undefined;
  }
  return TRAINING_HANDOFF_STATUS_TEXT[normalized]?.[language] ?? value;
}

export function compactCoachLine(
  label: string,
  value: string | undefined,
  language: ComposerLanguage,
): string | undefined {
  if (!value) {
    return undefined;
  }
  return appUiCopy(language, "{label}：{value}")
    .replace("{label}", () => label)
    .replace("{value}", () => value);
}

export function coachLaneLabel(
  scenario:
    | NonNullable<ReturnType<typeof useWorkbenchState.getState>["data"]["coachingState"]>["scenario"]
    | undefined,
  language: ComposerLanguage,
): string {
  if (scenario === "project_adaptation") {
    return appUiCopy(language, "主线：项目适配");
  }
  if (scenario === "onboarding") {
    return appUiCopy(language, "主线：建立训练关系");
  }
  if (scenario === "project_sourcing") {
    return appUiCopy(language, "主线：项目来源");
  }
  if (scenario === "remote_workspace") {
    return appUiCopy(language, "主线：远程工作区");
  }
  if (scenario === "debug_loop") {
    return appUiCopy(language, "主线：调试闭环");
  }
  if (scenario === "function_guidance") {
    return appUiCopy(language, "主线：函数提示");
  }
  if (scenario === "idea_implementation") {
    return appUiCopy(language, "主线：想法落地");
  }
  if (scenario === "project_idea") {
    return appUiCopy(language, "主线：项目提炼");
  }
  if (scenario === "principle") {
    return appUiCopy(language, "主线：原理讲解");
  }
  if (scenario === "review") {
    return appUiCopy(language, "主线：实现评审");
  }
  if (scenario === "plan") {
    return appUiCopy(language, "主线：计划推进");
  }
  return appUiCopy(language, "主线：当前训练");
}

export function sendContextSummary(
  data: ReturnType<typeof useWorkbenchState.getState>["data"],
  layout: ReturnType<typeof useWorkbenchState.getState>["layout"],
  t: Copy,
  includeCurrentFile = layout.includeCurrentFile,
): string {
  const parts: string[] = [];

  if (includeCurrentFile && data.liveContext.activeFile) {
    parts.push(basename(data.liveContext.activeFile));
  }
  if (layout.includeSelection && data.liveContext.selectionRange) {
    parts.push(t.selection);
  }
  if (layout.includeRelatedFiles && data.liveContext.relatedFiles.length > 0) {
    parts.push(`${data.liveContext.relatedFiles.length} ${t.relatedFiles}`);
  }
  if (data.resources.length > 0) {
    parts.push(
      appUiCopy(layout.composerLanguage, "{n} 份资料")
        .replace("{n}", String(data.resources.length))
        .replace("{s}", data.resources.length === 1 ? "" : "s"),
    );
  }

  // No announcement when nothing is attached: whether context is needed is
  // the coach's call at turn time, not a composer warning.
  return parts.length > 0 ? parts.join(" · ") : "";
}

export function sendContextShortSummary(
  data: ReturnType<typeof useWorkbenchState.getState>["data"],
  layout: ReturnType<typeof useWorkbenchState.getState>["layout"],
  t: Copy,
  includeCurrentFile = layout.includeCurrentFile,
): string {
  const activeLabels = [
    includeCurrentFile && data.liveContext.activeFile ? t.file : undefined,
    layout.includeSelection && data.liveContext.selectionRange ? t.selection : undefined,
    layout.includeRelatedFiles && data.liveContext.relatedFiles.length > 0
      ? t.relatedFiles
      : undefined,
    data.resources.length > 0
      ? appUiCopy(layout.composerLanguage, "{n} 份资料")
          .replace("{n}", String(data.resources.length))
          .replace("{s}", data.resources.length === 1 ? "" : "s")
      : undefined,
  ].filter((value): value is string => Boolean(value));

  if (activeLabels.length === 0) {
    return "";
  }
  if (activeLabels.length >= 3) {
    return appUiCopy(layout.composerLanguage, "当前代码线索");
  }
  return activeLabels.join(" · ");
}

export function sendContextPillItems(
  data: ReturnType<typeof useWorkbenchState.getState>["data"],
  layout: ReturnType<typeof useWorkbenchState.getState>["layout"],
  t: Copy,
): Array<{ id: string; label: string; value?: string; active: boolean }> {
  const items: Array<{ id: string; label: string; value?: string; active: boolean }> = [];

  items.push({
    id: "file",
    label: t.file,
    value:
      layout.includeCurrentFile && data.liveContext.activeFile
        ? basename(data.liveContext.activeFile)
        : undefined,
    active: layout.includeCurrentFile && Boolean(data.liveContext.activeFile),
  });

  items.push({
    id: "selection",
    label: t.selection,
    value: layout.includeSelection && data.liveContext.selectionRange ? data.liveContext.selectionRange : undefined,
    active: layout.includeSelection && Boolean(data.liveContext.selectionRange),
  });

  items.push({
    id: "diagnostics",
    label: t.diagnostics,
    value:
      layout.includeDiagnostics &&
      ((data.liveContext.diagnosticErrors ?? 0) > 0 || (data.liveContext.diagnosticWarnings ?? 0) > 0)
        ? appUiCopy(layout.composerLanguage, "{e} 错误 · {w} 警告")
            .replace("{e}", String(data.liveContext.diagnosticErrors ?? 0))
            .replace("{w}", String(data.liveContext.diagnosticWarnings ?? 0))
        : undefined,
    active:
      layout.includeDiagnostics &&
      ((data.liveContext.diagnosticErrors ?? 0) > 0 || (data.liveContext.diagnosticWarnings ?? 0) > 0),
  });

  items.push({
    id: "related",
    label: t.relatedFiles,
    value:
      layout.includeRelatedFiles && data.liveContext.relatedFiles.length > 0
        ? appUiCopy(layout.composerLanguage, "{v} 个相关文件").replace("{v}", String(data.liveContext.relatedFiles.length))
        : undefined,
    active: layout.includeRelatedFiles && data.liveContext.relatedFiles.length > 0,
  });

  if (data.resources.length > 0) {
    items.push({
      id: "resources",
      label: t.attachments,
      value:
        appUiCopy(layout.composerLanguage, "{v} 份资料").replace("{v}", String(data.resources.length)),
      active: true,
    });
  }

  return items.filter((item) => item.active);
}


export function activeStageObjectiveText(stage: PlanStage | undefined, fallback: string): string {
  return stage?.objective?.trim() || stage?.title?.trim() || fallback;
}

export function sendStatuslineText(
  analysis: ReturnType<typeof analyzeSendIntent>,
  data: ReturnType<typeof useWorkbenchState.getState>["data"],
  layout: ReturnType<typeof useWorkbenchState.getState>["layout"],
  t: Copy,
): string {
  if (analysis.isEmpty) {
    return "";
  }

  if (analysis.target === "local_command") {
    const commandLabel = analysis.localCommandId
      ? sidebarControlCommandLabel(analysis.localCommandId, layout.composerLanguage)
      : "";
    return commandLabel ? `${t.runLocalCommand} · ${commandLabel}` : t.runLocalCommand;
  }

  const intentLabel =
    analysis.intent === "next_task"
      ? t.nextTask
      : analysis.intent === "review"
        ? t.runReview
        : analysis.intent === "plan"
          ? t.plan
          : analysis.intent === "task"
            ? t.currentTask
            : t.coach;
  const includeCurrentFile =
    layout.includeCurrentFile && shouldAttachCurrentFile(analysis.draftBody ?? "", analysis.intent);
  const contextSummary = sendContextSummary(data, layout, t, includeCurrentFile);
  const answerMode = answerModeLabel(layout.composerAnswerMode, t);
  const resourceSummary =
    data.resources.length > 0
      ? appUiCopy(layout.composerLanguage, "附带 {n} 份资料")
          .replace("{n}", String(data.resources.length))
          .replace("{s}", data.resources.length === 1 ? "" : "s")
      : "";

  if (layout.composerLanguage === "zh-CN") {
    return [intentLabel, contextSummary, answerMode, resourceSummary].filter(Boolean).join(" · ");
  }

  return [intentLabel, contextSummary, answerMode, resourceSummary].filter(Boolean).join(" · ");
}

export function composerHintText(
  analysis: ReturnType<typeof analyzeSendIntent>,
  data: ReturnType<typeof useWorkbenchState.getState>["data"],
  layout: ReturnType<typeof useWorkbenchState.getState>["layout"],
  t: Copy,
): string {
  if (analysis.target === "local_command") {
    return sendStatuslineText(analysis, data, layout, t);
  }
  if (analysis.isEmpty) {
    return "";
  }
  const includeCurrentFile =
    layout.includeCurrentFile && shouldAttachCurrentFile(analysis.draftBody ?? "", analysis.intent);
  const contextSummary = sendContextShortSummary(data, layout, t, includeCurrentFile);
  const resourceSummary =
    data.resources.length > 0
      ? appUiCopy(layout.composerLanguage, "{count} 份资料")
          .replace("{count}", String(data.resources.length))
          .replace("{s}", data.resources.length === 1 ? "" : "s")
      : "";
  return [contextSummary, resourceSummary].filter(Boolean).join(" · ");
}

export function composerShortcutHint({
  language,
  hasCommandDeck,
  hasContextMenu,
}: {
  language: ComposerLanguage;
  hasCommandDeck: boolean;
  hasContextMenu: boolean;
}): string {
  if (hasCommandDeck) {
    return appUiCopy(language, "↑↓ 选择 · Enter 执行 · Tab 补全 · Esc 关闭");
  }

  if (hasContextMenu) {
    return appUiCopy(language, "Enter 发送 · Shift+Enter 换行 · Esc 收起");
  }

  return "";
}

export function focusComposerInput() {
  const element = document.getElementById("coach-composer");
  if (!(element instanceof HTMLTextAreaElement)) {
    return;
  }

  const caret = element.value.length;
  element.focus();
  element.setSelectionRange(caret, caret);
}

/**
 * True while the user is typing into a field other than the coach composer.
 * A host-prefilled draft still lands in the composer (it is visible the moment
 * the user returns to Coach), but it does not pull focus out of the field the
 * user is working in.
 */
export function isEditingAnotherField(): boolean {
  const active = document.activeElement;
  if (!(active instanceof HTMLElement) || active.id === "coach-composer") {
    return false;
  }
  return (
    active.isContentEditable ||
    active instanceof HTMLInputElement ||
    active instanceof HTMLTextAreaElement ||
    active instanceof HTMLSelectElement
  );
}

export function defaultPromptText(
  intent: "coach" | "next_task" | "review" | "plan" | "task",
  language: ComposerLanguage,
  focusArea?: string,
): string {
  const focus = focusArea
    ? appUiCopy(language, "，重点围绕「{a}」。").replace("{a}", () => focusArea)
    : "";
  if (intent === "next_task") {
    return appUiCopy(language, "请给我下一道训练题{focus}").replace("{focus}", () => focus);
  }
  if (intent === "review") {
    return appUiCopy(language, "请评审我当前文件的实现{focus}").replace("{focus}", () => focus);
  }
  if (intent === "plan") {
    return appUiCopy(language, "请刷新并重排我的当前训练计划{focus}").replace("{focus}", () => focus);
  }
  if (intent === "task") {
    return appUiCopy(language, "请把我当前目标转成一个可执行的小任务{focus}").replace("{focus}", () => focus);
  }
  return appUiCopy(language, "请继续引导我实现这个想法{focus}").replace("{focus}", () => focus);
}

export function planComposerDraftReplacementCopy(language: ComposerLanguage, stageTitle: string) {
  const targetTitle = stageTitle.trim() || (appUiCopy(language, "\u5f53\u524d\u9636\u6bb5"));

  const draftCopy = PLAN_DRAFT_REPLACEMENT_COPY[language] ?? PLAN_DRAFT_REPLACEMENT_COPY["en-US"];
  return {
    title: draftCopy.title,
    detail: draftCopy.detail.replace("{t}", () => targetTitle),
    confirmLabel: draftCopy.confirmLabel,
    cancelLabel: draftCopy.cancelLabel,
  };
}

export function buildLocalCommandSuggestions({
  t,
  language,
  applyView,
  applyLanguage,
  applyAnswerMode,
  applyContextDetail,
  applyAttachmentPreset,
  applySingleAttachment,
  applyLiveFollow,
}: {
  t: Copy;
  language: ComposerLanguage;
  applyView: (view: SidebarView, message: string) => void;
  applyLanguage: (value: ComposerLanguage, message: string) => void;
  applyAnswerMode: (value: CoachAnswerMode, message: string) => void;
  applyContextDetail: (value: "focused" | "balanced" | "full", message: string) => void;
  applyAttachmentPreset: (enabled: boolean, message: string) => void;
  applySingleAttachment: (
    key: "current_file" | "selection" | "diagnostics" | "related",
    enabled: boolean,
    message: string,
  ) => void;
  applyLiveFollow: (enabled: boolean, message: string) => void;
}): LocalCommandSuggestion[] {
  const commandLabel = (id: SidebarControlCommandId) => sidebarControlCommandLabel(id, language);

  return [
    {
      id: "open-coach",
      command: commandLabel("open-coach"),
      title: t.openCoach,
      description: `${t.switchView}: ${t.chat}`,
      run: () => applyView("coach", `${t.opened}: ${t.chat}`),
    },
    {
      id: "open-plan",
      command: commandLabel("open-plan"),
      title: t.openPlan,
      description: `${t.switchView}: ${t.plan}`,
      run: () => applyView("plan", `${t.opened}: ${t.plan}`),
    },
    {
      id: "open-settings",
      command: commandLabel("open-settings"),
      title: t.openSettings,
      description: `${t.switchView}: ${t.settings}`,
      run: () => applyView("settings", `${t.opened}: ${t.settings}`),
    },
    {
      id: "lang-zh",
      command: commandLabel("lang-zh"),
      title: "中文",
      description: `${t.setLanguage}: zh-CN`,
      run: () => applyLanguage("zh-CN", `${t.updated}: ${t.language} · zh-CN`),
    },
    {
      id: "lang-en",
      command: commandLabel("lang-en"),
      title: "English",
      description: `${t.setLanguage}: en-US`,
      run: () => applyLanguage("en-US", `${t.updated}: ${t.language} · en-US`),
    },
    {
      id: "mode-auto",
      command: commandLabel("mode-auto"),
      title: `${t.answerMode}: ${t.auto}`,
      description: `${t.setAnswerMode}: ${t.auto}`,
      run: () => applyAnswerMode("auto", `${t.updated}: ${t.answerMode} · ${t.auto}`),
    },
    {
      id: "mode-coach",
      command: commandLabel("mode-coach"),
      title: `${t.answerMode}: ${t.coachFirst}`,
      description: `${t.setAnswerMode}: ${t.coachFirst}`,
      run: () => applyAnswerMode("coach-first", `${t.updated}: ${t.answerMode} · ${t.coachFirst}`),
    },
    {
      id: "mode-balanced",
      command: commandLabel("mode-balanced"),
      title: `${t.answerMode}: ${t.balanced}`,
      description: `${t.setAnswerMode}: ${t.balanced}`,
      run: () => applyAnswerMode("balanced", `${t.updated}: ${t.answerMode} · ${t.balanced}`),
    },
    {
      id: "mode-direct",
      command: commandLabel("mode-direct"),
      title: `${t.answerMode}: ${t.direct}`,
      description: `${t.setAnswerMode}: ${t.direct}`,
      run: () => applyAnswerMode("direct", `${t.updated}: ${t.answerMode} · ${t.direct}`),
    },
    {
      id: "detail-focused",
      command: commandLabel("detail-focused"),
      title: `${t.contextDetail}: ${t.detailFocused}`,
      description: `${t.setContextDetail}: ${t.detailFocused}`,
      run: () => applyContextDetail("focused", `${t.updated}: ${t.contextDetail} · ${t.detailFocused}`),
    },
    {
      id: "detail-balanced",
      command: commandLabel("detail-balanced"),
      title: `${t.contextDetail}: ${t.detailBalanced}`,
      description: `${t.setContextDetail}: ${t.detailBalanced}`,
      run: () => applyContextDetail("balanced", `${t.updated}: ${t.contextDetail} · ${t.detailBalanced}`),
    },
    {
      id: "detail-full",
      command: commandLabel("detail-full"),
      title: `${t.contextDetail}: ${t.detailFull}`,
      description: `${t.setContextDetail}: ${t.detailFull}`,
      run: () => applyContextDetail("full", `${t.updated}: ${t.contextDetail} · ${t.detailFull}`),
    },
    {
      id: "attach-all",
      command: commandLabel("attach-all"),
      title: `${t.attachments}: ${t.allContext}`,
      description: `${t.setAttachments}: ${t.allContext}`,
      run: () => applyAttachmentPreset(true, `${t.updated}: ${t.attachments} · ${t.allContext}`),
    },
    {
      id: "attach-none",
      command: commandLabel("attach-none"),
      title: `${t.attachments}: ${t.noContext}`,
      description: `${t.setAttachments}: ${t.noContext}`,
      run: () => applyAttachmentPreset(false, `${t.updated}: ${t.attachments} · ${t.noContext}`),
    },
    {
      id: "file-on",
      command: commandLabel("file-on"),
      title: `${t.file}: ${t.on}`,
      description: `${t.setAttachments}: ${t.file} ${t.on}`,
      run: () => applySingleAttachment("current_file", true, `${t.updated}: ${t.file} · ${t.on}`),
    },
    {
      id: "file-off",
      command: commandLabel("file-off"),
      title: `${t.file}: ${t.off}`,
      description: `${t.setAttachments}: ${t.file} ${t.off}`,
      run: () => applySingleAttachment("current_file", false, `${t.updated}: ${t.file} · ${t.off}`),
    },
    {
      id: "selection-on",
      command: commandLabel("selection-on"),
      title: `${t.selection}: ${t.on}`,
      description: `${t.setAttachments}: ${t.selection} ${t.on}`,
      run: () => applySingleAttachment("selection", true, `${t.updated}: ${t.selection} · ${t.on}`),
    },
    {
      id: "selection-off",
      command: commandLabel("selection-off"),
      title: `${t.selection}: ${t.off}`,
      description: `${t.setAttachments}: ${t.selection} ${t.off}`,
      run: () => applySingleAttachment("selection", false, `${t.updated}: ${t.selection} · ${t.off}`),
    },
    {
      id: "diagnostics-on",
      command: commandLabel("diagnostics-on"),
      title: `${t.diagnostics}: ${t.on}`,
      description: `${t.setAttachments}: ${t.diagnostics} ${t.on}`,
      run: () => applySingleAttachment("diagnostics", true, `${t.updated}: ${t.diagnostics} · ${t.on}`),
    },
    {
      id: "diagnostics-off",
      command: commandLabel("diagnostics-off"),
      title: `${t.diagnostics}: ${t.off}`,
      description: `${t.setAttachments}: ${t.diagnostics} ${t.off}`,
      run: () => applySingleAttachment("diagnostics", false, `${t.updated}: ${t.diagnostics} · ${t.off}`),
    },
    {
      id: "related-on",
      command: commandLabel("related-on"),
      title: `${t.relatedFiles}: ${t.on}`,
      description: `${t.setAttachments}: ${t.relatedFiles} ${t.on}`,
      run: () => applySingleAttachment("related", true, `${t.updated}: ${t.relatedFiles} · ${t.on}`),
    },
    {
      id: "related-off",
      command: commandLabel("related-off"),
      title: `${t.relatedFiles}: ${t.off}`,
      description: `${t.setAttachments}: ${t.relatedFiles} ${t.off}`,
      run: () => applySingleAttachment("related", false, `${t.updated}: ${t.relatedFiles} · ${t.off}`),
    },
    {
      id: "follow-on",
      command: commandLabel("follow-on"),
      title: `${t.follow}: ${t.on}`,
      description: `${t.setLiveFollow}: ${t.on}`,
      run: () => applyLiveFollow(true, `${t.updated}: ${t.follow} · ${t.on}`),
    },
    {
      id: "follow-off",
      command: commandLabel("follow-off"),
      title: `${t.follow}: ${t.off}`,
      description: `${t.setLiveFollow}: ${t.off}`,
      run: () => applyLiveFollow(false, `${t.updated}: ${t.follow} · ${t.off}`),
    },
  ];
}

export function MenuList({
  items,
}: {
  items: Array<{ label: string; active: boolean; onClick: () => void }>;
}) {
  return (
    <div className="menu-list is-compact">
      {items.map((item) => (
        <button
          key={item.label}
          className={`menu-list__item ${item.active ? "is-active" : ""}`}
          type="button"
          aria-label={item.label}
          title={item.label}
          onClick={item.onClick}
        >
          <span className="menu-list__body">
            <strong>{item.label}</strong>
          </span>
          <span className="menu-list__state" aria-hidden="true">
            {item.active ? <CheckMarkIcon size={12} /> : null}
          </span>
        </button>
      ))}
    </div>
  );
}

export function MenuToggleRow({
  label,
  value,
  active,
  onClick,
}: {
  label: string;
  value: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className={`menu-row ${active ? "is-active" : ""}`}
      type="button"
      aria-label={`${label}: ${value}`}
      title={`${label}: ${value}`}
      onClick={onClick}
    >
      <span className="menu-row__body">
        <span>{label}</span>
      </span>
      <span className="menu-row__state">
        <strong>{value}</strong>
        {active ? <CheckMarkIcon size={12} aria-hidden="true" /> : null}
      </span>
    </button>
  );
}

export type DirectoryInputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  webkitdirectory?: string;
};

export const DirectoryInput = forwardRef<HTMLInputElement, DirectoryInputProps>(function DirectoryInput(
  props,
  ref,
) {
  return <input ref={ref} {...props} />;
});

/** Which capture kind the URL implies; the sidecar still validates for real. */
export function captureTargetKind(url: string): "pdf" | "github_repo" | "web" {
  const trimmed = url.trim();
  if (/^https?:\/\/(?:www\.)?github\.com\/[^/]+\/[^/]+/i.test(trimmed)) {
    return "github_repo";
  }
  try {
    const parsed = new URL(trimmed);
    if (/\.pdf$/i.test(parsed.pathname)) {
      return "pdf";
    }
  } catch {
    // Invalid URLs fall through to `web`; the sidecar performs the real check.
  }
  return "web";
}

/** Pull the display-safe message out of a sidecar error payload. */
export function describeSidecarFailure(body: unknown): string {
  if (!body || typeof body !== "object") {
    return "";
  }
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") {
    return detail.trim();
  }
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) {
      return message.trim();
    }
  }
  const message = (body as { message?: unknown }).message;
  return typeof message === "string" ? message.trim() : "";
}

/** Read the attachment filename a sidecar export response chose. */
export function exportDownloadName(headers: Headers): string | undefined {
  const disposition = headers.get("content-disposition") ?? "";
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim());
    } catch {
      return utf8Match[1].trim();
    }
  }
  const plainMatch = /filename="?([^";]+)"?/i.exec(disposition);
  return plainMatch?.[1]?.trim() || undefined;
}

/** Save an exported blob through the browser's own download path. */
export function triggerLocalDownload(blob: Blob, filename: string): void {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return;
  }
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename || "resource";
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

/** Poll cadence while waiting for a host-side library write to land. */
export const HOST_WRITE_POLL_MS = 500;
/** A deep link can land before the capture reaches this webview's snapshot. */
export const OPEN_RESOURCE_SYNC_TIMEOUT_MS = 4_000;
/** A capture fetches, cleans and indexes: keep its bounded window generous. */
export const CAPTURE_CONFIRMATION_TIMEOUT_MS = 30_000;
/** Rename/tag/group writes are a single sidecar call. */
export const ORGANIZE_CONFIRMATION_TIMEOUT_MS = 15_000;
/** Folder list/create/rename/delete answers ride one host round-trip. */
export const LIBRARY_FOLDER_OPERATION_TIMEOUT_MS = 8_000;

export function delayHostWritePoll(): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, HOST_WRITE_POLL_MS);
  });
}

/**
 * Bounded wait for a resource to appear in the synced workbench snapshot.
 * A `vscode://.../library/<id>` deep link can reach the webview before the
 * capture that minted the id has been synced; the landing point opens the
 * reader once it arrives, and reports honestly only after the wait expires.
 */
export async function waitForResourceInSnapshot(
  resourceId: string,
  timeoutMs: number,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (useWorkbenchState.getState().data.resources.some((resource) => resource.id === resourceId)) {
      return true;
    }
    if (Date.now() >= deadline) {
      return false;
    }
    await delayHostWritePoll();
  }
}

/**
 * Wait (bounded) for the host-driven capture to appear in the library snapshot.
 *
 * Inside VS Code the webview cannot reach the sidecar itself, so a posted
 * capture command is only confirmed by the refreshed snapshot. Matching rides
 * the same identity the sidecar records (`captured-from:<url>` tag), so a
 * capture that never lands is reported as unconfirmed instead of a false
 * "added to the library".
 */
export async function waitForCapturedResource(
  url: string,
  beforeIds: ReadonlySet<string>,
  timeoutMs: number = CAPTURE_CONFIRMATION_TIMEOUT_MS,
): Promise<
  | { deduped: boolean; title: string; resourceId: string; savedPath?: string }
  | undefined
> {
  const tag = `captured-from:${url}`;
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const resources = useWorkbenchState.getState().data.resources;
    const match = resources.find(
      (resource) =>
        (resource.tags ?? []).includes(tag) ||
        (!beforeIds.has(resource.id) &&
          (resource.source === url || resource.canonicalSource === url)),
    );
    if (match) {
      return {
        deduped: beforeIds.has(match.id),
        title: match.title?.trim() || match.id,
        resourceId: match.id,
        savedPath: resourceSavedPath(match),
      };
    }
    if (Date.now() >= deadline) {
      return undefined;
    }
    await delayHostWritePoll();
  }
}

/**
 * Read the download landing path a captured record may carry once the sidecar
 * has written the original bytes into the library's folder space. Tolerant by
 * design: the field is optional in the snapshot contract, so an absent path is
 * reported as "not confirmed" rather than guessed at.
 */
export function resourceSavedPath(resource: WorkbenchDataSnapshot["resources"][number]): string | undefined {
  const record = resource as unknown as Record<string, unknown>;
  for (const key of ["saved_path", "savedPath", "downloaded_path", "download_path"]) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return undefined;
}

/** True when the refreshed record already reflects the requested organize action. */
export function organizeOutcomeMatches(
  resource: WorkbenchDataSnapshot["resources"][number],
  request: ResourceOrganizeInput,
  beforeCollectionPath: string,
): boolean {
  if (request.action === "rename") {
    return resource.title.trim() === (request.title ?? "").trim();
  }
  if (request.action === "set_tags") {
    const normalize = (values: string[] | undefined) =>
      new Set(
        (values ?? [])
          .map((value) => value.trim().slice(0, 40).toLowerCase())
          .filter(Boolean),
      );
    const wanted = normalize(request.tags);
    const current = normalize(resource.tags);
    return (
      wanted.size === current.size && [...wanted].every((tag) => current.has(tag))
    );
  }
  const group = (request.group ?? "").trim();
  const currentPath = (resource.collectionPath ?? "").trim();
  if (!group) {
    return currentPath === "";
  }
  return currentPath !== "" && currentPath !== beforeCollectionPath;
}

/** Wait (bounded) for the host-driven organize write to show in the snapshot. */
export async function waitForOrganizedResource(
  resourceId: string,
  request: ResourceOrganizeInput,
  beforeCollectionPath: string,
): Promise<boolean> {
  const deadline = Date.now() + ORGANIZE_CONFIRMATION_TIMEOUT_MS;
  for (;;) {
    const resource = useWorkbenchState
      .getState()
      .data.resources.find((item) => item.id === resourceId);
    if (resource && organizeOutcomeMatches(resource, request, beforeCollectionPath)) {
      return true;
    }
    if (Date.now() >= deadline) {
      return false;
    }
    await delayHostWritePoll();
  }
}

export function triggerResourceUpload({
  browserPreview,
  payloadMode,
  folder,
  filesInputRef,
  folderInputRef,
}: {
  browserPreview: boolean;
  payloadMode?: "files" | "folder" | "url";
  folder?: boolean;
  filesInputRef: { current: HTMLInputElement | null };
  folderInputRef: { current: HTMLInputElement | null };
}) {
  if (browserPreview) {
    if (payloadMode === "url") {
      return;
    }
    if (folder) {
      folderInputRef.current?.click();
      return;
    }
    filesInputRef.current?.click();
    return;
  }

  const operationId = `resource-upload-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  postMessage({
    type: "resource/upload",
    payload: {
      ...(payloadMode ? { mode: payloadMode } : {}),
      __trainerResourceOperationId: operationId,
    },
  });
}

export const BROWSER_SUPPORTED_UPLOAD_EXTENSIONS = new Set([
  "pdf",
  "png",
  "jpg",
  "jpeg",
  "webp",
  "gif",
  "bmp",
  "md",
  "markdown",
  "txt",
  "rst",
  "py",
  "ts",
  "tsx",
  "js",
  "jsx",
  "mjs",
  "cjs",
  "json",
  "yaml",
  "yml",
  "toml",
  "ipynb",
  "html",
  "css",
  "scss",
  "less",
  "vue",
  "svelte",
  "astro",
  "go",
  "rs",
  "java",
  "kt",
  "swift",
  "c",
  "cc",
  "cpp",
  "h",
  "hpp",
  "cs",
  "php",
  "rb",
  "sh",
  "zsh",
  "bash",
  "ps1",
  "sql",
]);

export function browserResourceKind(name: string): BrowserUploadResourceInputType["kind"] {
  const extension = name.split(".").pop()?.toLowerCase() ?? "";
  if (extension === "pdf") {
    return "pdf";
  }
  if (["png", "jpg", "jpeg", "webp", "gif", "bmp"].includes(extension)) {
    return "image";
  }
  if (["md", "markdown"].includes(extension)) {
    return "markdown";
  }
  if (
    [
      "py",
      "ts",
      "tsx",
      "js",
      "jsx",
      "mjs",
      "cjs",
      "json",
      "yaml",
      "yml",
      "toml",
      "ipynb",
      "html",
      "css",
      "scss",
      "less",
      "vue",
      "svelte",
      "astro",
      "go",
      "rs",
      "java",
      "kt",
      "swift",
      "c",
      "cc",
      "cpp",
      "h",
      "hpp",
      "cs",
      "php",
      "rb",
      "sh",
      "zsh",
      "bash",
      "ps1",
      "sql",
    ].includes(extension)
  ) {
    return "code";
  }
  return "text";
}

export function browserFileSupported(file: File): boolean {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return BROWSER_SUPPORTED_UPLOAD_EXTENSIONS.has(extension);
}

export function isBinaryBrowserFile(file: File): boolean {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return ["pdf", "png", "jpg", "jpeg", "webp", "gif", "bmp"].includes(extension);
}

export async function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => {
      reject(reader.error ?? new Error(`Failed to read ${file.name}`));
    };
    reader.onload = () => {
      if (typeof reader.result !== "string") {
        reject(new Error(`Failed to read ${file.name}`));
        return;
      }
      resolve(reader.result);
    };
    reader.readAsDataURL(file);
  });
}

export async function readBrowserFiles(
  files: File[],
): Promise<BrowserUploadResourceInputType[]> {
  const uploads = await Promise.all(
    files.map(async (file) => {
      const source = file.webkitRelativePath || file.name;
      const kind = browserResourceKind(file.name);
      if (isBinaryBrowserFile(file)) {
        const dataUrl = await readFileAsDataUrl(file);
        const [, base64Payload = ""] = dataUrl.split(",", 2);
        return {
          name: source,
          kind,
          content: base64Payload,
          contentEncoding: "base64" as const,
          source,
          tags: [],
        };
      }

      return {
        name: source,
        kind,
        content: await file.text(),
        contentEncoding: "utf-8" as const,
        source,
        tags: [],
      };
    }),
  );
  return uploads;
}

export function browserUploadLooksLikeFolder(files: File[]): boolean {
  return files.some((file) => Boolean(file.webkitRelativePath));
}

