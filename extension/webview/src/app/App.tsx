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

import { trainerCommands } from "../../../../shared/src/commands";
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
  PROVIDER_TEST_FRESHNESS_WINDOW_MS,
} from "../../../../shared/src/providerStatus";
import {
  filterTrainerSkills,
  resolveTrainerSkillText,
  trainerSkillCatalog,
  trainerSkillSectionLabel,
  type TrainerSkillCatalogItem,
  type TrainerSkillContext,
  type TrainerSkillSection,
} from "../../../../shared/src/skillCatalog";
import {
  providerModelTokenLimitsKey,
  resolveProviderModelTokenState,
} from "../../../../shared/src/providerModelTokenLimits";
import {
  evaluateProviderModelPolicy,
  filterProviderModelOptions,
  type ProviderModelPolicyReason,
} from "../../../../shared/src/providerModelPolicy";
import { normalizeProviderProtocol } from "../../../../shared/src/providerProtocols";
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
import { normalizeTransferSkillStateRecord } from "../../../../shared/src/transferSkillGovernance";
import {
  planRuntimeStatusFromRecovery,
  selectStreamingCheckpointForScope,
  streamingCheckpointToOrientation,
} from "../../../../shared/src/workspaceRecoveryGovernance";
import {
  type CoachArtifactBlockData,
  CoachConversationView,
  CoachMessageBubble,
} from "../components/coach";
import { CoachComposer, ComposerIconButton } from "../components/composer";
import { UserFeedbackDisclosure, type UserFeedbackKind } from "../components/common/UserFeedbackDisclosure";
import { WorkspaceAdmissionPanel } from "../components/firstlook";
import {
  type ResourceSearchRequest,
} from "../components/resources/ResourcesWorkbenchView";
import {
  applyTrainingCardGrade,
  applyTrainingCardSkip,
  interpretTrainingComposerCardCommand,
  type FlashVerificationMode,
  type TrainingReviewItem,
  type TrainingSummaryCard,
} from "../components/training/TrainingWorkbenchView";
import {
  CheckMarkIcon,
  ContextLayersIcon,
  FolderIcon,
  LinkIcon,
  RefreshIcon,
  ResourcesIcon,
  UploadIcon,
} from "../components/icons";
import { StatusPill } from "../components/StatusPill";
import { applyWorkbenchTheme } from "../lib/theme";
import { I18nProvider } from "../lib/i18n/context";
import { resolveCopy as resolveWorkbenchCopy, type Copy } from "../lib/i18n/copy";
import { resolvePlanComposerCopy } from "../lib/i18n/planComposerCopy";
import { resolveResourceComposerCopy } from "../lib/i18n/resourceComposerCopy";
import { resolvePlanViewCopy } from "../lib/i18n/planViewCopy";
import { resolveTextDirection, type TextDirection } from "../lib/i18n/direction";
import type {
  ActiveWorkbenchView,
  BootstrapData,
  BrowserUploadResourceInput as BrowserUploadResourceInputType,
  CoachAnswerMode,
  CoachDefaults,
  ComposerLanguage,
  ConversationMessage,
  DebugVisibleTrainingFacts,
  EvaluationCheck,
  HostMessage,
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
  COACH_FIRST_SIDEBAR_VIEWS,
  normalizeSidebarView,
  normalizeTeachingStyle,
} from "../lib/types";
import {
  announceReady,
  getInjectedBootstrapState,
  persistBrowserPreviewProviderConfig,
  postDebugVisibleFacts,
  postMessage,
  subscribeToHostMessages,
} from "../lib/vscode";
import {
  buildGenericImageReviewPrompt,
  buildScratchPaperVerificationPrompt,
  buildTrainingFeedbackPrompt,
  type TrainingFeedbackPromptInput,
} from "../lib/universalLearningPrompts";
import { isBrowserPreviewFixtureMode } from "../lib/browserSidecar";
import { useTrainingCommands } from "./useTrainingCommands";
import { type TrainingRestoreContext, useWorkbenchState } from "./useWorkbenchState";
import type { PlanReviewItem } from "../components/plan/CoachPlanView";
import type {
  ProviderDraft,
  SettingsActionFeedback,
  SettingsSectionStatus,
} from "../components/settings/CoachSettingsView";

type ContextMenu = "context" | "resources" | "model" | undefined;
type ComposerModelActionDensity = "default" | "compact";
type TrainingPracticeReturnMode = "result" | "blocked";
type TrainingComposerRoute = "card" | "coach";
type PlanComposerMode = "explain" | "generate" | "evidence" | "blocker";
type PlanComposerDraftReplacement = {
  source: "stage" | "project-subplan";
  targetTitle: string;
};
type ResourcesComposerMode = "locate" | "download" | "organize" | "cards";
type ComposerProviderMenuItem = {
  id: string;
  selectionKind: "profile" | "model";
  label: string;
  model: string;
  isActive: boolean;
  isSelectable?: boolean;
  policyReason?: ProviderModelPolicyReason;
};
type HeaderSwitcherDensity = "full" | "compact";
const COMPOSER_MODEL_PICKER_INITIAL_OPTION_LIMIT = 6;
const RESOURCE_UPLOAD_LIMIT = 100;
const RESOURCE_COMPOSER_MAX_IDS = 12;
type WorkbenchDataSnapshot = ReturnType<typeof useWorkbenchState.getState>["data"];
type WorkspaceSettingsSnapshot = NonNullable<
  ReturnType<typeof useWorkbenchState.getState>["data"]["memory"]["workspace"]
>;
type DockedView = "plan" | "resources" | "training" | "settings";
type OperationMessage = { tone: "info" | "success" | "error"; message: string };
type ResourceOperationKind = "delete" | "restore" | "search" | "index" | "upload";
type ResourceMutationOperationKind = "delete" | "restore";
type PendingResourceOperation = {
  kind: ResourceOperationKind;
  resolve: () => void;
  reject: (reason?: unknown) => void;
  timeoutId: number;
};
type PendingResourceTrainingHandoff = {
  resourceId: string;
  resolve: (result: ResourceTrainingHandoffResult) => void;
  timeoutId: number;
};
type PendingTrainingPersistence = {
  commandId: string;
  resolve: (data?: unknown) => void;
  reject: (reason?: unknown) => void;
  timeoutId: number;
};
type ResourceOperationStatus = {
  kind: ResourceOperationKind;
  requestId: string;
  message: string;
};
type SettingsFeedbackSlot = "provider" | "coachDefaults" | "workspaceControl";
type SettingsActionKind =
  | "save-provider"
  | "refresh-provider-models"
  | "test-provider"
  | "clear-provider"
  | "open-config"
  | "save-coach"
  | "reset-defaults";

type RecoverableFailureKind = "bootstrap" | "send" | "upload" | "provider" | "operation";

type CoachCheckpointRecoveryAction = "resume" | "replay";

function isCoachCheckpointRecoveryState(
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

const recoverableFailureCopy: Record<
  ComposerLanguage,
  Record<RecoverableFailureKind, string>
> = {
  "zh-CN": {
    bootstrap: "暂时没能打开预览。等一会儿再试。",
    send: "这条消息没有发出去。检查一下连接，再试一次。",
    upload: "这个文件暂时没导入成功。确认文件没问题后再试。",
    provider: "还没连上模型。检查一下设置，再试一次。",
    operation: "这一步暂时没完成。再试一次。",
  },
  "en-US": {
    bootstrap: "Preview data could not load. Try again shortly.",
    send: "The message was not sent. Check the connection and try again.",
    upload: "The resource could not be imported. Check the file and try again.",
    provider: "The provider action did not finish. Check the settings and try again.",
    operation: "That action did not finish. Try again.",
  },
  "es-ES": {
    bootstrap: "La vista previa no se pudo abrir por ahora. Vuelve a intentarlo en un momento.",
    send: "El mensaje no se envió. Revisa la conexión e inténtalo de nuevo.",
    upload: "El archivo no se pudo importar. Revisa el archivo e inténtalo de nuevo.",
    provider: "No se pudo completar la conexión del modelo. Revisa los ajustes e inténtalo de nuevo.",
    operation: "Esta acción no se pudo completar. Inténtalo de nuevo.",
  },
  "fr-FR": {
    bootstrap: "La prévisualisation ne s'est pas ouverte. Réessayez dans un instant.",
    send: "Le message n'a pas été envoyé. Vérifiez la connexion puis réessayez.",
    upload: "Le fichier n'a pas pu être importé. Vérifiez-le puis réessayez.",
    provider: "La connexion au modèle n'a pas abouti. Vérifiez les réglages puis réessayez.",
    operation: "Cette action n'a pas pu être terminée. Réessayez.",
  },
  "de-DE": {
    bootstrap: "Die Vorschau konnte nicht geöffnet werden. Versuche es gleich noch einmal.",
    send: "Die Nachricht wurde nicht gesendet. Prüfe die Verbindung und versuche es erneut.",
    upload: "Die Datei konnte nicht importiert werden. Prüfe die Datei und versuche es erneut.",
    provider: "Die Modellverbindung konnte nicht abgeschlossen werden. Prüfe die Einstellungen und versuche es erneut.",
    operation: "Dieser Schritt konnte nicht abgeschlossen werden. Versuche es erneut.",
  },
  "ja-JP": {
    bootstrap: "プレビューを開けませんでした。少し待ってからもう一度試してください。",
    send: "メッセージを送信できませんでした。接続を確認して、もう一度試してください。",
    upload: "ファイルを取り込めませんでした。ファイルを確認して、もう一度試してください。",
    provider: "モデルへの接続を完了できませんでした。設定を確認して、もう一度試してください。",
    operation: "この操作を完了できませんでした。もう一度試してください。",
  },
  "ko-KR": {
    bootstrap: "미리 보기를 열 수 없었습니다. 잠시 후 다시 시도하세요.",
    send: "메시지를 보내지 못했습니다. 연결을 확인한 뒤 다시 시도하세요.",
    upload: "파일을 가져오지 못했습니다. 파일을 확인한 뒤 다시 시도하세요.",
    provider: "모델 연결을 완료하지 못했습니다. 설정을 확인한 뒤 다시 시도하세요.",
    operation: "이 작업을 완료하지 못했습니다. 다시 시도하세요.",
  },
  "pt-BR": {
    bootstrap: "Não foi possível abrir a visualização agora. Tente novamente em instantes.",
    send: "Não foi possível enviar a mensagem. Verifique a conexão e tente novamente.",
    upload: "Não foi possível importar o arquivo. Verifique o arquivo e tente novamente.",
    provider: "Não foi possível concluir a conexão com o modelo. Verifique as configurações e tente novamente.",
    operation: "Não foi possível concluir esta ação. Tente novamente.",
  },
};

const coachFirstComposerPlaceholder: Record<ComposerLanguage, string> = {
  "zh-CN": "问教练",
  "en-US": "Ask the coach",
  "es-ES": "Empieza por contarme tu nivel, objetivo, proyecto o dónde te has atascado.",
  "fr-FR": "Commencez par me dire votre niveau, votre objectif, votre projet ou ce qui vous bloque.",
  "de-DE": "Sag mir zuerst dein Niveau, dein Ziel, dein Projekt oder wo du festhängst.",
  "ja-JP": "今のレベル、目標、プロジェクト、または困っていることを教えてください。",
  "ko-KR": "현재 수준, 목표, 프로젝트 또는 막힌 부분을 먼저 알려 주세요.",
  "pt-BR": "Comece me contando seu nível, objetivo, projeto ou onde está travado.",
};

const RESOURCE_OPERATION_STATUS_PATTERN =
  /^\[\[trainer-resource-operation:(delete|restore|search|index|upload):([a-z0-9-]{1,96})\]\]\s*/i;
const RESOURCE_OPERATION_TIMEOUT_MS = 45_000;
const RESOURCE_TRAINING_HANDOFF_TIMEOUT_MS = 45_000;
const TRAINING_PERSISTENCE_TIMEOUT_MS = 45_000;

function parseResourceOperationStatus(
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
      kind !== "upload"
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

function recoverableFailureMessage(
  kind: RecoverableFailureKind,
  language: ComposerLanguage,
): string {
  if (kind === "provider") {
    return providerRecoveryMessage(language);
  }
  return recoverableFailureCopy[language]?.[kind] ?? recoverableFailureCopy["en-US"][kind];
}

type LivePlanTaskGateKind = "no_live" | "leftover";

const LIVE_PLAN_TASK_GATE_MARKER =
  /^\[\[trainer-live-plan-task-gate:(no_live|leftover)\]\](?:\s|$)/i;

function livePlanTaskGateFailureMessage(
  kind: LivePlanTaskGateKind,
  language: ComposerLanguage,
): string {
  const copy: Record<ComposerLanguage, Record<LivePlanTaskGateKind, string>> = {
    "zh-CN": {
      no_live: "当前没有正式计划，所以还不能改计划或生成任务。先生成计划，再试一次。",
      leftover: "这里只有旧计划痕迹，不是当前正式计划。先生成计划，再试一次。",
    },
    "en-US": {
      no_live:
        "No live plan is bound, so Trainer will not invent a task or mutate leftover as live. Generate a plan first.",
      leftover:
        "Only leftover plan traces remain, not a live plan. Generate a plan first; Trainer will not resurrect leftover as live.",
    },
    "es-ES": {
      no_live:
        "No hay un plan en vivo, así que Trainer no inventará una tarea ni mutará un resto como vivo. Genera un plan primero.",
      leftover:
        "Solo quedan rastros de un plan anterior, no un plan en vivo. Genera un plan primero; Trainer no resucitará el resto como vivo.",
    },
    "fr-FR": {
      no_live:
        "Aucun plan actif n'est lié, donc Trainer n'inventera pas de tâche et ne mutera pas un reste comme actif. Générez d'abord un plan.",
      leftover:
        "Il ne reste que des traces d'ancien plan, pas un plan actif. Générez d'abord un plan ; Trainer ne ressuscitera pas le reste comme actif.",
    },
    "de-DE": {
      no_live:
        "Es ist kein live-Plan gebunden, daher erfindet Trainer keine Aufgabe und mutiert keinen Rest als live. Erzeuge zuerst einen Plan.",
      leftover:
        "Nur Restspuren eines Plans sind da, kein live-Plan. Erzeuge zuerst einen Plan; Trainer belebt keinen Rest als live wieder.",
    },
    "ja-JP": {
      no_live:
        "正式な計画がないため、タスク作成や古い計画の更新はできません。先に計画を生成してください。",
      leftover:
        "残っているのは古い計画の痕跡だけで、正式な計画ではありません。先に計画を生成してください。",
    },
    "ko-KR": {
      no_live:
        "살아있는 계획이 없어 과제를 만들거나 남은 계획을 바꾸지 않습니다. 먼저 계획을 생성하세요.",
      leftover:
        "남은 건 예전 계획 흔적일 뿐, 현재 계획이 아닙니다. 먼저 계획을 생성하세요. 남은 계획을 되살리지 않습니다.",
    },
    "pt-BR": {
      no_live:
        "Não há plano ao vivo vinculado, então o Trainer não inventará uma tarefa nem mutará resto como ao vivo. Gere um plano primeiro.",
      leftover:
        "Só restam rastros de plano antigo, não um plano ao vivo. Gere um plano primeiro; o Trainer não ressuscitará o resto como ao vivo.",
    },
  };
  return copy[language]?.[kind] ?? copy["en-US"][kind];
}

function livePlanTaskMintPendingMessage(language: ComposerLanguage): string {
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

function livePlanUpdatePendingMessage(language: ComposerLanguage): string {
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

function trainingGenerateCardPendingMessage(language: ComposerLanguage): string {
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

function parseLivePlanTaskGateMarker(message: string): LivePlanTaskGateKind | undefined {
  const match = LIVE_PLAN_TASK_GATE_MARKER.exec(message.trim());
  const kind = match?.[1]?.toLowerCase();
  return kind === "no_live" || kind === "leftover" ? kind : undefined;
}

function trainingPersistenceFailureMessage(language: ComposerLanguage): string {
  return language === "zh-CN"
    ? "训练记录没有保存，因此没有开始教练流式回复。输入已保留，可以重试。"
    : "The training record was not saved, so the coach stream did not start. Your input is still here to retry.";
}

function providerRecoveryMessage(language: ComposerLanguage): string {
  const copy: Record<ComposerLanguage, string> = {
    "zh-CN": "连接还没有通过。请检查服务地址、API key 和模型名称，然后再试一次。",
    "en-US": "The connection did not pass yet. Check the service address, API key, and model name, then try again.",
    "es-ES": "La conexión aún no pasó la comprobación. Revisa la dirección del servicio, la clave API y el modelo, e inténtalo de nuevo.",
    "fr-FR": "La connexion n'a pas encore passé la vérification. Vérifiez l'adresse du service, la clé API et le modèle, puis réessayez.",
    "de-DE": "Die Verbindung hat die Prüfung noch nicht bestanden. Prüfen Sie Serviceadresse, API-Schlüssel und Modellnamen und versuchen Sie es erneut.",
    "ja-JP": "接続はまだ確認できていません。サービスのアドレス、API キー、モデル名を確認して、もう一度試してください。",
    "ko-KR": "연결 확인이 아직 끝나지 않았습니다. 서비스 주소, API 키, 모델 이름을 확인한 뒤 다시 시도하세요.",
    "pt-BR": "A conexão ainda não passou na verificação. Confira o endereço do serviço, a chave de API e o modelo, depois tente novamente.",
  };
  return copy[language] ?? copy["en-US"];
}

type PartialResourceDeletionFailure = {
  deletedCount: number;
  failedCount: number;
  summaryRefreshFailed: boolean;
};

function parsePartialResourceDeletionFailure(
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

function partialResourceDeletionFailureMessage(
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

function resourceOperationFailureMessage(
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

function sanitizeHostFailureMessage(
  message: HostMessage,
  language: ComposerLanguage,
  isProviderAction = false,
  resourceOperationKind?: ResourceOperationKind,
): HostMessage {
  if (message.type !== "operation/status" || message.payload.tone !== "error") {
    return message;
  }

  const partialDeletion = parsePartialResourceDeletionFailure(message.payload.message);
  const resourceRecovery = resourceOperationFailureMessage(resourceOperationKind, language);
  const livePlanGate = parseLivePlanTaskGateMarker(message.payload.message);
  return {
    ...message,
    payload: {
      ...message.payload,
      message: partialDeletion
        ? partialResourceDeletionFailureMessage(partialDeletion, language)
        : resourceRecovery
          ? resourceRecovery
        : livePlanGate
          ? livePlanTaskGateFailureMessage(livePlanGate, language)
        : isProviderAction
          ? providerRecoveryMessage(language)
          : recoverableFailureMessage("operation", language),
    },
  };
}

function sanitizeOperationFailureMessage(
  message: OperationMessage,
  language: ComposerLanguage,
): OperationMessage {
  if (message.tone !== "error") {
    return message;
  }

  const localRecoveryMessages = Object.values(
    recoverableFailureCopy[language] ?? recoverableFailureCopy["en-US"],
  );
  localRecoveryMessages.push(providerRecoveryMessage(language));
  localRecoveryMessages.push(livePlanTaskGateFailureMessage("no_live", language));
  localRecoveryMessages.push(livePlanTaskGateFailureMessage("leftover", language));
  localRecoveryMessages.push(
    "验证未通过：当前训练卡片不是实时状态。",
    "没有可验证的当前文件。",
    "预览不能验真实工作区文件。请回 VS Code 打开文件后再验证。",
    "Verification failed: this training card is not live.",
    "There is no current file to verify.",
    "Preview cannot verify a real workspace file. Open the file in VS Code, then verify there.",
  );
  const livePlanGate = parseLivePlanTaskGateMarker(message.message);
  return {
    tone: "error",
    message: livePlanGate
      ? livePlanTaskGateFailureMessage(livePlanGate, language)
      : localRecoveryMessages.includes(message.message)
        ? message.message
        : recoverableFailureMessage("operation", language),
  };
}

interface SettingsActionState {
  kind: SettingsActionKind;
  targets: SettingsFeedbackSlot[];
  baselineMessageKey?: string;
}

interface UtilityComposerPrompt {
  id: string;
  label: string;
  prompt: string;
}

interface UtilityComposerModeOption<TMode extends string> {
  id: TMode;
  label: string;
  header: string;
  summary: string;
  hint: string;
  placeholder: string;
  accessibilityLabel: string;
  prompts: UtilityComposerPrompt[];
}

type SettingsFeedbackState = Partial<Record<SettingsFeedbackSlot, SettingsActionFeedback>>;
const DEFAULT_ANSWER_MODE: CoachAnswerMode = "auto";
const DEFAULT_TEACHING_STYLE: TeachingStyle = "auto";
type BrowserPreviewModule = typeof import("../lib/browserSidecar");
const CoachPlanView = lazy(async () => {
  const module = await import("../components/plan/CoachPlanView");
  return { default: module.CoachPlanView };
});
const CoachSettingsView = lazy(async () => {
  const module = await import("../components/settings/CoachSettingsView");
  return { default: module.CoachSettingsView };
});
const ResourcesWorkbenchView = lazy(async () => {
  const module = await import("../components/resources/ResourcesWorkbenchView");
  return { default: module.ResourcesWorkbenchView };
});
const TrainingWorkbenchView = lazy(async () => {
  const module = await import("../components/training/TrainingWorkbenchView");
  return { default: module.TrainingWorkbenchView };
});

let browserPreviewModulePromise: Promise<BrowserPreviewModule> | undefined;
let bootstrapRequestSent = false;
let lastBootstrapRequestAt = 0;

function inBrowserPreviewEnvironment(): boolean {
  return (
    typeof window !== "undefined" &&
    (window.__TRAINER_BROWSER_PREVIEW__ === true || !window.acquireVsCodeApi)
  );
}

function readBrowserPreviewLocationOverrides(): {
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
      requestedView === "settings"
        ? requestedView
        : requestedView === "practice"
          ? "training"
          : undefined,
  };
}

async function loadBrowserPreviewModule(): Promise<BrowserPreviewModule> {
  browserPreviewModulePromise ??= import("../lib/browserSidecar");
  return browserPreviewModulePromise;
}

function requestBootstrapOnce(force = false): void {
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

function syncBootstrapLifecycleOnVisible(hasReceivedHostState: boolean): void {
  bootstrapRequestSent = false;
  if (!hasReceivedHostState) {
    requestBootstrapOnce(true);
  } else {
    announceReady();
  }
}

function normalizeOperationMessageKey(message: OperationMessage | undefined): string | undefined {
  const normalized = message?.message.trim().toLowerCase();
  return normalized && normalized.length > 0 ? normalized : undefined;
}

function ViewFallback({
  label,
  language,
}: {
  label: string;
  language: ComposerLanguage;
}) {
  return (
    <section className="section-block section-block--placeholder">
      <p className="muted">
        {language === "zh-CN" ? `正在加载${label}…` : `Loading ${label}…`}
      </p>
    </section>
  );
}

const viewLabels: Record<
  ComposerLanguage,
  Record<"coach" | "plan" | "resources" | "training" | "settings", string>
> = {
  "zh-CN": { coach: "\u5bf9\u8bdd", plan: "\u8ba1\u5212", resources: "\u8d44\u6599", training: "\u8bad\u7ec3", settings: "\u8bbe\u7f6e" },
  "en-US": { coach: "Chat", plan: "Plan", resources: "Resources", training: "Training", settings: "Settings" },
  "es-ES": { coach: "Chat", plan: "Plan", resources: "Recursos", training: "Entrenamiento", settings: "Ajustes" },
  "fr-FR": { coach: "Chat", plan: "Plan", resources: "Ressources", training: "Entra\u00eenement", settings: "Param\u00e8tres" },
  "de-DE": { coach: "Chat", plan: "Plan", resources: "Materialien", training: "Training", settings: "Einstellungen" },
  "ja-JP": { coach: "\u5bfe\u8a71", plan: "\u8a08\u753b", resources: "\u8cc7\u6599", training: "\u8a13\u7df4", settings: "\u8a2d\u5b9a" },
  "ko-KR": { coach: "\ub300\ud654", plan: "\uacc4\ud68d", resources: "\uc790\ub8cc", training: "\ud6c8\ub828", settings: "\uc124\uc815" },
  "pt-BR": { coach: "Chat", plan: "Plano", resources: "Recursos", training: "Treinamento", settings: "Configura\u00e7\u00f5es" },
};

function resourcesViewLabel(language: ComposerLanguage): string {
  return viewLabels[language].resources;
}

function coachViewLabel(language: ComposerLanguage): string {
  return viewLabels[language].coach;
}

function planViewLabel(language: ComposerLanguage): string {
  return viewLabels[language].plan;
}

function trainingViewLabel(language: ComposerLanguage): string {
  return viewLabels[language].training;
}

function settingsViewLabel(language: ComposerLanguage): string {
  return viewLabels[language].settings;
}

const trainingFilePracticeCopy: Record<
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
    resultPlaceholder: "Registra el resultado o la evidencia.",
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

function trainingFilePracticeText(language: ComposerLanguage) {
  return trainingFilePracticeCopy[language] ?? trainingFilePracticeCopy["en-US"];
}

type TrainingComposerModeCopy = {
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

const trainingComposerModeCopy: Record<ComposerLanguage, TrainingComposerModeCopy> = {
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

function trainingComposerModeText(language: ComposerLanguage): TrainingComposerModeCopy {
  return trainingComposerModeCopy[language] ?? trainingComposerModeCopy["en-US"];
}

type TrainingHandoffComposerCopy = {
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

const trainingHandoffComposerCopy: Record<ComposerLanguage, TrainingHandoffComposerCopy> = {
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

function trainingHandoffComposerText(language: ComposerLanguage): TrainingHandoffComposerCopy {
  return trainingHandoffComposerCopy[language] ?? trainingHandoffComposerCopy["en-US"];
}

function localizeUiViewReferences(
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

function compactSidebarViewLabel(
  view: ActiveWorkbenchView,
  language: ComposerLanguage,
  fullLabel: string,
): string {
  return fullLabel;
}

function compactComposerModelLabel(
  modelLabel: string,
  _providerLabel: string | undefined,
  language: ComposerLanguage,
): string {
  const normalized = modelLabel.trim();
  if (!normalized) {
    return language === "zh-CN" ? "模型" : "Model";
  }
  const tail = normalized.split("/").filter(Boolean).pop() ?? normalized;
  return (
    tail
      .replace(/[-_ ]compatible$/i, "")
      .replace(/[:/](latest|default)$/i, "")
      .trim() || normalized
  );
}

function composerModelPolicyHint(
  language: ComposerLanguage,
  reason: ProviderModelPolicyReason | undefined,
): string | undefined {
  if (reason !== "denied" && reason !== "not_allowed") {
    return undefined;
  }

  const denied = reason === "denied";
  switch (language) {
    case "zh-CN":
      return denied
        ? "\u8fd9\u4e2a\u8fde\u63a5\u5df2\u505c\u7528\u5f53\u524d\u6a21\u578b\uff0c\u8bf7\u4ece\u5217\u8868\u91cc\u91cd\u65b0\u9009\u4e00\u4e2a\u3002"
        : "\u5f53\u524d\u6a21\u578b\u4e0d\u5728\u8fd9\u4e2a\u8fde\u63a5\u7684\u53ef\u7528\u8303\u56f4\u5185\uff0c\u8bf7\u4ece\u5217\u8868\u91cc\u91cd\u65b0\u9009\u4e00\u4e2a\u3002";
    case "es-ES":
      return denied
        ? "Este modelo esta desactivado para esta conexion. Elige uno de la lista."
        : "El modelo actual no esta en la lista permitida de esta conexion. Elige uno de la lista.";
    case "fr-FR":
      return denied
        ? "Ce modele est desactive pour cette connexion. Choisissez-en un dans la liste."
        : "Le modele actuel ne fait pas partie de la liste autorisee pour cette connexion. Choisissez-en un dans la liste.";
    case "de-DE":
      return denied
        ? "Dieses Modell ist fuer diese Verbindung deaktiviert. Waehle eines aus der Liste."
        : "Das aktuelle Modell ist fuer diese Verbindung nicht freigegeben. Waehle eines aus der Liste.";
    case "ja-JP":
      return denied
        ? "\u3053\u306e\u63a5\u7d9a\u3067\u306f\u73fe\u5728\u306e\u30e2\u30c7\u30eb\u306f\u4f7f\u3048\u307e\u305b\u3093\u3002\u4e00\u89a7\u304b\u3089\u9078\u3073\u76f4\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
        : "\u73fe\u5728\u306e\u30e2\u30c7\u30eb\u306f\u3053\u306e\u63a5\u7d9a\u306e\u4f7f\u7528\u7bc4\u56f2\u306b\u542b\u307e\u308c\u3066\u3044\u307e\u305b\u3093\u3002\u4e00\u89a7\u304b\u3089\u9078\u3073\u76f4\u3057\u3066\u304f\u3060\u3055\u3044\u3002";
    case "ko-KR":
      return denied
        ? "\uc774 \uc5f0\uacb0\uc5d0\uc11c\ub294 \ud604\uc7ac \ubaa8\ub378\uc744 \uc0ac\uc6a9\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4. \ubaa9\ub85d\uc5d0\uc11c \ub2e4\uc2dc \uc120\ud0dd\ud558\uc138\uc694."
        : "\ud604\uc7ac \ubaa8\ub378\uc740 \uc774 \uc5f0\uacb0\uc758 \uc0ac\uc6a9 \ubc94\uc704\uc5d0 \ud3ec\ud568\ub418\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4. \ubaa9\ub85d\uc5d0\uc11c \ub2e4\uc2dc \uc120\ud0dd\ud558\uc138\uc694.";
    case "pt-BR":
      return denied
        ? "Este modelo esta desativado para esta conexao. Escolha um da lista."
        : "O modelo atual nao esta na lista permitida desta conexao. Escolha um da lista.";
    default:
      return denied
        ? "This connection has turned off the current model. Choose one from the list."
        : "The current model is outside this connection's allowed list. Choose one from the list.";
  }
}

function providerDraftStringArrayKey(values: string[] | undefined): string {
  return JSON.stringify(
    Array.from(
      new Set(
        (values ?? [])
          .map((value) => value.trim())
          .filter(Boolean)
          .map((value) => value.toLowerCase()),
      ),
    ).sort(),
  );
}

function providerRequestDefaultsKey(value: Record<string, unknown> | undefined): string {
  try {
    return JSON.stringify(value ?? {});
  } catch {
    return "{}";
  }
}

function containsChineseText(value: string | undefined): boolean {
  return /[\u4e00-\u9fff]/u.test(value ?? "");
}

function containsJapaneseText(value: string | undefined): boolean {
  return /[\u3040-\u30ff]/u.test(value ?? "");
}

function containsKoreanText(value: string | undefined): boolean {
  return /[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]/u.test(value ?? "");
}

function looksLikeChineseMojibake(value: string | undefined): boolean {
  return /(?:[ãäåçèéïð][\u0080-\u00BF]{1,3}){2,}/u.test(value ?? "");
}

const SHORT_ZH_TECHNICAL_ENGLISH_TOKENS = new Set([
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

const KNOWN_COACH_UI_ZH_REPLACEMENTS: Array<[string, string]> = [
  ["function contract and call-site reading", "函数契约与 call site 判断"],
  ["the smallest trustworthy debug loop", "最小可信的 debug loop"],
  ["remote workspace boundary", "远程工作区边界"],
  ["VS Code remote workflow", "VS Code 远程工作流"],
  ["Code remote workflow", "远程工作流"],
  ["VS Code remote workspace", "VS Code 远程工作区"],
  ["VS Code function guidance", "VS Code 函数提示"],
  ["function contract recovery", "恢复函数契约"],
  ["function contract reading", "函数契约判断"],
  ["VS Code debug loop", "VS Code 调试闭环"],
];

function tokenizeAsciiWords(value: string): string[] {
  return value.toLowerCase().match(/[a-z]+(?:[/-][a-z0-9]+)*/g) ?? [];
}

function isShortTechnicalEnglishText(value: string): boolean {
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

function hasExcessiveEnglishProseForChinese(value: string): boolean {
  const words = tokenizeAsciiWords(value);
  if (words.length === 0) {
    return false;
  }
  return words.some(
    (word) => !SHORT_ZH_TECHNICAL_ENGLISH_TOKENS.has(word) && !/\d/.test(word),
  );
}

function isLanguageAlignedUiText(language: ComposerLanguage, value: string | undefined): boolean {
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

function localizeKnownCoachUiText(
  value: string | undefined,
  language: ComposerLanguage,
): string | undefined {
  if (!value) {
    return value;
  }
  if (language !== "zh-CN") {
    return value;
  }

  let cleaned = value;
  const laneMatch = cleaned.match(
    /^Continue\s+['"](?<focus>.+?)['"]\s+and do not open a new lane before this next move lands:\s*(?<rest>.+)$/i,
  );
  if (laneMatch?.groups) {
    const localizedFocus =
      localizeKnownCoachUiText(laneMatch.groups.focus, language)?.trim() || laneMatch.groups.focus;
    const localizedRest =
      localizeKnownCoachUiText(laneMatch.groups.rest, language)?.trim() || laneMatch.groups.rest;
    cleaned = `继续沿着「${localizedFocus}」这条主线，先别开新线。${localizedRest}`;
  }

  for (const [source, target] of KNOWN_COACH_UI_ZH_REPLACEMENTS) {
    cleaned = cleaned.replace(new RegExp(source.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), target);
  }

  const exactFocusMap: Record<string, string> = {
    "debug loop": "调试闭环",
    "function contract": "函数契约判断",
    "call-site reading": "call site 判断",
  };
  return localizeUiViewReferences(exactFocusMap[cleaned.trim().toLowerCase()] ?? cleaned, language);
}

function estimateHeaderSwitcherLabelWidth(label: string): number {
  return Array.from(label).reduce((width, char) => {
    if (/[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/u.test(char)) {
      return width + 14;
    }
    if (/[A-Z]/.test(char)) {
      return width + 8;
    }
    return width + 7;
  }, 0);
}

function resolveHeaderSwitcherDensity(widthPerTab: number): HeaderSwitcherDensity {
  if (widthPerTab < 100) {
    return "compact";
  }
  return "full";
}

function resolveHeaderSwitcherDensityForTabs(
  containerWidth: number,
  labels: string[],
): HeaderSwitcherDensity {
  const tabCount = Math.max(labels.length, 1);
  const widthPerTab = containerWidth / tabCount;
  const labelAllowance = Math.max(...labels.map(estimateHeaderSwitcherLabelWidth), 0) + 18;
  if (widthPerTab < labelAllowance) {
    return "compact";
  }
  return resolveHeaderSwitcherDensity(widthPerTab);
}

function skillSectionTargetView(section: TrainerSkillSection): ActiveWorkbenchView {
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

type LocalCommandSuggestion = {
  id: SidebarControlCommandId;
  command: string;
  title: string;
  description: string;
  run: () => void;
};

type ComposerDeckKind = "command" | "skill";

type LocalSkillSuggestion = TrainerSkillCatalogItem;

function resolveTheme(themePreference: ThemePreference): "light" | "dark" {
  if (themePreference === "light" || themePreference === "dark") {
    return themePreference;
  }

  if (document.body.classList.contains("vscode-light")) {
    return "light";
  }

  return "dark";
}

function basename(value: string): string {
  const parts = value.split(/[\\/]/);
  return parts[parts.length - 1] || value;
}

function connectionStateLabel(state: "starting" | "connected" | "offline", t: Copy): string {
  if (state === "connected") {
    return t.connected;
  }
  if (state === "starting") {
    return t.starting;
  }
  return t.offline;
}

function effectiveConnectionState(
  connectionState: "starting" | "connected" | "offline",
): "starting" | "connected" | "offline" {
  return connectionState;
}

function planStageStatusLabel(status: PlanStage["status"], t: Copy): string {
  if (status === "done") {
    return t.stageDone;
  }
  if (status === "active") {
    return t.stageActive;
  }
  return t.stageQueued;
}

function contextDetailLabel(value: "focused" | "balanced" | "full", t: Copy): string {
  if (value === "focused") {
    return t.detailFocused;
  }
  if (value === "full") {
    return t.detailFull;
  }
  return t.detailBalanced;
}

function answerModeLabel(value: CoachAnswerMode, t: Copy): string {
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

function teachingStyleLabel(value: TeachingStyle, t: Copy): string {
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

function coachDefaultsNoteIntro(
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

function autoAnswerModeNote(language: ComposerLanguage, t: Copy): string {
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

function autoTeachingStyleNote(language: ComposerLanguage, t: Copy): string {
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

function coachDefaultsStatusNote(input: {
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

function formatToggleValue(enabled: boolean, t: Copy): string {
  return enabled ? t.on : t.off;
}

function formatContextBundleValue(
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

function formatCoachDefaultsValue(
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
  const isChinese = config.language === "zh-CN";
  const languageLabel = config.language === "zh-CN" ? "中文" : "English";
  const memoryScopeMap = {
    project: isChinese ? "当前项目" : "Project",
    personal: isChinese ? "个人通用" : "Personal",
    session: isChinese ? "仅本次会话" : "Session only",
  } as const;
  const workingSetMap = {
    focused: isChinese ? "只跟当前任务" : "Current task only",
    balanced: isChinese ? "兼顾邻近文件" : "Balanced",
    broad: isChinese ? "允许更宽引用" : "Broader",
  } as const;
  const reviewCadenceMap = {
    light: isChinese ? "轻量" : "Light",
    steady: isChinese ? "标准" : "Standard",
    active: isChinese ? "紧凑" : "Active",
  } as const;
  const reviewReminderMap = {
    due: isChinese ? "到期" : "Due",
    ahead: isChinese ? "提前" : "Ahead",
    digest: isChinese ? "合并" : "Digest",
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

function compactDefinedValues(values: Array<string | null | undefined>, fallback: string): string {
  const resolved = values.filter(Boolean) as string[];
  return resolved.length > 0 ? resolved.join(" · ") : fallback;
}

function truncateInlineText(value: string | undefined, limit = 56): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return undefined;
  }
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}

function isTerminallyTruncatedText(value: string | undefined): boolean {
  return /(?:…|\.{3})\s*$/u.test(value?.trim() ?? "");
}

function normalizeInlineComparisonText(value: string | undefined): string {
  return value?.replace(/\s+/g, " ").trim().toLowerCase() ?? "";
}

function pickFirstText(...values: Array<string | undefined | null>): string | undefined {
  return values.find((value) => Boolean(value?.trim()))?.trim();
}

function pickLanguageAlignedUiText(
  language: ComposerLanguage,
  fallback: string | undefined,
  ...values: Array<string | undefined | null>
): string | undefined {
  for (const value of values) {
    const normalized = localizeKnownCoachUiText(value?.trim() ?? undefined, language)?.trim();
    if (normalized && isLanguageAlignedUiText(language, normalized)) {
      return normalized;
    }
  }
  return localizeKnownCoachUiText(fallback ?? pickFirstText(...values) ?? undefined, language);
}

function pickLanguageAlignedUiList(
  language: ComposerLanguage,
  values: Array<string | undefined | null>,
): string[] {
  const localized = values
    .map((value) => localizeKnownCoachUiText(value?.trim() ?? undefined, language)?.trim())
    .filter((value): value is string => Boolean(value));

  const aligned = localized.filter((value) => isLanguageAlignedUiText(language, value));
  if (aligned.length > 0) {
    return Array.from(new Set(aligned));
  }

  if (language === "zh-CN") {
    return Array.from(new Set(localized.filter((value) => !looksLikeChineseMojibake(value))));
  }

  return [];
}

/**
 * Training cards are learner-facing assessment material, not ambient UI. When
 * the current language is Chinese, an unlocalized sentence must not leak into
 * the card just because it is the only available upstream value. The card has
 * its own localized fallback copy for omitted optional fields.
 */
function pickLanguageAlignedTrainingText(
  language: ComposerLanguage,
  ...values: Array<string | undefined | null>
): string | undefined {
  const resolved = pickLanguageAlignedUiText(language, undefined, ...values);
  return resolved && isLanguageAlignedUiText(language, resolved) ? resolved : undefined;
}

function pickLanguageAlignedTrainingList(
  language: ComposerLanguage,
  values: Array<string | undefined | null>,
): string[] {
  const resolved = values
    .map((value) => localizeKnownCoachUiText(value?.trim() ?? undefined, language)?.trim())
    .filter((value): value is string => Boolean(value))
    .filter((value) => isLanguageAlignedUiText(language, value));
  return Array.from(new Set(resolved));
}

function joinInlineMeta(values: Array<string | undefined | null>): string | undefined {
  const resolved = values
    .map((value) => value?.trim())
    .filter((value): value is string => Boolean(value));
  return resolved.length > 0 ? resolved.join(" · ") : undefined;
}

function trainingExpectedSymbols(...groups: Array<string[] | undefined>): string[] {
  return Array.from(
    new Set(
      groups
        .flatMap((group) => group ?? [])
        .map((symbol) => symbol.trim())
        .filter(Boolean),
    ),
  );
}

type TrainingSubjectCard = {
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

function normalizeTrainingLearningFamily(value: string | undefined): TrainingLearningFamily | undefined {
  return value === "code" || value === "theory" ? value : undefined;
}

function resolveTrainingLearningSubtype(...values: Array<string | undefined>): string | undefined {
  return values.find((value) => Boolean(value?.trim()))?.trim();
}

function resolveTrainingLearningFamily(...cards: Array<TrainingSubjectCard | undefined>): TrainingLearningFamily {
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

function resolveTrainingPracticeVerificationMode(input: {
  cardType: "practice" | "flash";
  learningFamily: TrainingLearningFamily;
}): "file" | "manual" {
  if (input.cardType !== "practice") {
    return "manual";
  }
  return input.learningFamily === "code" ? "file" : "manual";
}

function firstTrainingCardOfType<T extends { type?: string }>(
  cards: readonly T[] | undefined,
  type: "practice" | "flash",
): T | undefined {
  return cards?.find((card) => card.type === type);
}

function restoredTrainingCard(
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
          scenario: scenarioLab.lastAction ?? scenarioLab.reviewOutcome,
          problemStatement: scenarioLab.lastAction ?? scenarioLab.reviewOutcome,
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
          title: reviewArtifact.title ?? "Review recovery",
          focusArea: reviewArtifact.focusArea,
          targetSkill: reviewArtifact.focusArea,
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

function sameCoachDefaults(left: CoachDefaults, right: CoachDefaults): boolean {
  return (
    left.memoryScope === right.memoryScope &&
    left.workingSetMode === right.workingSetMode &&
    left.reviewCadence === right.reviewCadence &&
    left.reviewReminderMode === right.reviewReminderMode &&
    left.workspaceMemoryToggles.decisions === right.workspaceMemoryToggles.decisions &&
    left.workspaceMemoryToggles.patterns === right.workspaceMemoryToggles.patterns &&
    left.workspaceMemoryToggles.resources === right.workspaceMemoryToggles.resources
  );
}

/**
 * True when the saved server snapshot pins every defined field to the same
 * value as the pending payload. Fields missing from the partial snapshot are
 * treated as matching so a sparse snapshot never blocks an explicit save.
 */
function matchesSavedCoachDefaults(
  next: CoachDefaults,
  saved:
    | (Partial<CoachDefaults> & { workspaceMemoryToggles?: Partial<CoachDefaults["workspaceMemoryToggles"]> })
    | undefined,
): boolean {
  if (!saved) {
    return false;
  }
  return (
    (saved.memoryScope === undefined || saved.memoryScope === next.memoryScope) &&
    (saved.workingSetMode === undefined || saved.workingSetMode === next.workingSetMode) &&
    (saved.reviewCadence === undefined || saved.reviewCadence === next.reviewCadence) &&
    (saved.reviewReminderMode === undefined ||
      saved.reviewReminderMode === next.reviewReminderMode) &&
    (saved.workspaceMemoryToggles?.decisions === undefined ||
      saved.workspaceMemoryToggles.decisions === next.workspaceMemoryToggles.decisions) &&
    (saved.workspaceMemoryToggles?.patterns === undefined ||
      saved.workspaceMemoryToggles.patterns === next.workspaceMemoryToggles.patterns) &&
    (saved.workspaceMemoryToggles?.resources === undefined ||
      saved.workspaceMemoryToggles.resources === next.workspaceMemoryToggles.resources)
  );
}

function formatSparseWorkspaceControlValue(workspace: WorkspaceSettingsSnapshot, t: Copy): string | undefined {
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

function formatSparseCoachDefaultsSavedValue(
  workspace: WorkspaceSettingsSnapshot,
  t: Copy,
  teachingStyle: TeachingStyle,
): string | undefined {
  const defaults = workspace.coachDefaults;
  const isChinese = (workspace.responseLanguage ?? "en-US") === "zh-CN";
  const memoryScopeMap = {
    project: isChinese ? "当前项目" : "Project",
    personal: isChinese ? "个人通用" : "Personal",
    session: isChinese ? "仅本次会话" : "Session only",
  } as const;
  const workingSetMap = {
    focused: isChinese ? "只跟当前任务" : "Current task only",
    balanced: isChinese ? "兼顾邻近文件" : "Balanced",
    broad: isChinese ? "允许更宽引用" : "Broader",
  } as const;
  const reviewCadenceMap = {
    light: isChinese ? "轻量" : "Light",
    steady: isChinese ? "标准" : "Standard",
    active: isChinese ? "紧凑" : "Active",
  } as const;
  const reviewReminderMap = {
    due: isChinese ? "到期" : "Due",
    ahead: isChinese ? "提前" : "Ahead",
    digest: isChinese ? "合并" : "Digest",
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
      ? `${isChinese ? "架构决策" : "Architecture decisions"} ${formatToggleValue(defaults.workspaceMemoryToggles.decisions, t)}`
      : null,
    defaults?.workspaceMemoryToggles?.patterns !== undefined
      ? `${isChinese ? "常用模式" : "Patterns"} ${formatToggleValue(defaults.workspaceMemoryToggles.patterns, t)}`
      : null,
    defaults?.workspaceMemoryToggles?.resources !== undefined
      ? `${isChinese ? "参考资料" : "Resources"} ${formatToggleValue(defaults.workspaceMemoryToggles.resources, t)}`
      : null,
  ];
  const result = values.filter(Boolean) as string[];
  return result.length > 0 ? result.join(" · ") : undefined;
}

function providerModelRuntimeNote(provider: ProviderConfigView, language: ComposerLanguage): string {
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
    return language === "zh-CN"
      ? `当前连接已可用，可选 ${modelCount} 个模型。`
      : `This connection is ready with ${modelCount} available models.`;
  }

  if (provider.modelListStatus === "loading") {
    return language === "zh-CN"
      ? "正在更新可选模型。"
      : "Updating available models.";
  }

  return language === "zh-CN"
    ? "当前连接已保存。可以测试连接或更新模型列表。"
    : "This connection is saved. You can test it or update the model list.";
}

function providerModelMenuNote(provider: ProviderConfigView, language: ComposerLanguage): string {
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
    return language === "zh-CN"
      ? `${provider.availableModels.length} 个可选模型`
      : `${provider.availableModels.length} available models`;
  }

  return language === "zh-CN" ? "连接已保存" : "Connection saved";
}

function providerHasVerifiedToolsProbe(
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

type ProviderSettingsLocale = {
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

const providerSettingsCopy: Record<ComposerLanguage, ProviderSettingsLocale> = {
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

function providerSettingsLocale(language: ComposerLanguage): ProviderSettingsLocale {
  return providerSettingsCopy[language] ?? providerSettingsCopy["en-US"];
}

function buildSettingsFeedback(
  action: SettingsActionState | undefined,
  message: OperationMessage | undefined,
  language: ComposerLanguage,
  slot: SettingsFeedbackSlot,
): SettingsActionFeedback | undefined {
  if (!action || !message || !action.targets.includes(slot)) {
    return undefined;
  }

  const normalized = message.message.toLowerCase();
  const isError = message.tone === "error";
  const copy = providerSettingsLocale(language);

  if (action.baselineMessageKey && normalized === action.baselineMessageKey) {
    return undefined;
  }

  if (action.kind === "save-provider") {
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
    const connectedSignal =
      normalized.includes("is connected") ||
      normalized.includes("connected and ready") ||
      normalized.includes("provider reachable") ||
      normalized.includes("已连通") ||
      normalized.includes("连通成功") ||
      normalized.includes("服务已就绪");
    const pendingLike =
      !isError &&
      !connectedSignal &&
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
function providerBlockingReason(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
): string | undefined {
  const sendState = describeProviderSendState(provider, language);
  if (connectionState === "offline" || connectionState === "starting" || sendState.blocked) {
    return providerRecoverySummary(provider, language, connectionState).detail;
  }
  if (provider.configured && provider.apiKeyConfigured && !providerHasVerifiedStreamingProbe(provider)) {
    return streamingCapabilityBlockReason(language);
  }
  return undefined;
}

function providerHasVerifiedStreamingProbe(
  provider: Pick<ProviderConfigView, "lastTestResult">,
): boolean {
  const lastTest = provider.lastTestResult;
  const streamingEvidence = lastTest?.capabilityEvidence?.find((entry) => {
    const name = entry.name.trim().toLowerCase();
    return name === "streaming" || name === "stream";
  });

  return (
    lastTest?.ok === true &&
    lastTest.streamingReady === true &&
    lastTest.streamProbeStatus === "verified" &&
    streamingEvidence?.state === "verified" &&
    streamingEvidence.observed === true
  );
}

function streamingCapabilityBlockReason(language: ComposerLanguage): string {
  return language === "zh-CN"
    ? "\u5f53\u524d\u8fde\u63a5\u8fd8\u6ca1\u6709\u9a8c\u8bc1\u771f\u5b9e\u6d41\u5f0f\u8f93\u51fa\u3002\u8bf7\u5728\u8bbe\u7f6e\u4e2d\u91cd\u65b0\u6d4b\u8bd5 Provider\uff0c\u786e\u8ba4\u80fd\u89c2\u5bdf\u5230\u589e\u91cf\u7247\u6bb5\u540e\u518d\u5bf9\u8bdd\u3002"
    : "This connection has not verified real incremental output yet. Retest the provider in Settings and continue after a visible stream chunk is observed.";
}

function providerCoachBanner(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
  blockedMessage?: string,
): { tone: "info" | "error"; message: string } | undefined {
  const recovery = providerRecoverySummary(provider, language, connectionState);
  if (connectionState === "offline") {
    return {
      tone: "error",
      message: blockedMessage ?? recovery.detail,
    };
  }

  if (connectionState === "starting") {
    return {
      tone: "info",
      message: blockedMessage ?? recovery.detail,
    };
  }

  const sendState = describeProviderSendState(provider, language);
  const lastCategory = provider.lastTestResult?.errorCategory ?? provider.modelErrorCategory;

  if (
    (sendState.status === "blocked_error" || sendState.status === "degraded_error") &&
    lastCategory === "language_corruption"
  ) {
    return {
      tone: sendState.blocked ? "error" : "info",
      message: blockedMessage ?? providerRecoveryLocale(language).languageIntegrityDetail,
    };
  }

  if (
    (sendState.status === "blocked_error" || sendState.status === "degraded_error") &&
    lastCategory === "language_probe_inconclusive"
  ) {
    return {
      tone: "info",
      message: blockedMessage ?? recovery.detail,
    };
  }

  if (sendState.blocked) {
    return {
      tone: "error",
      message: blockedMessage ?? recovery.detail,
    };
  }

  if ((sendState.status === "degraded_error" || sendState.status === "refreshing") && sendState.warning) {
    return {
      tone: "info",
      message: sendState.warning,
    };
  }

  return undefined;
}

function reviewSurfaceModeLabel(
  value: "due" | "ahead" | "digest" | undefined,
  language: ComposerLanguage,
): string | undefined {
  if (value === "ahead") {
    return language === "zh-CN" ? "提前提醒" : "Ahead";
  }
  if (value === "digest") {
    return language === "zh-CN" ? "合并回看" : "Digest";
  }
  if (value === "due") {
    return language === "zh-CN" ? "到期回看" : "Due";
  }
  return undefined;
}

function formatIntervalDays(days: number | undefined, language: ComposerLanguage): string | undefined {
  if (typeof days !== "number" || Number.isNaN(days)) {
    return undefined;
  }
  return language === "zh-CN" ? `${days} 天间隔` : `${days}-day interval`;
}

function formatMasteryScore(score: number | undefined, language: ComposerLanguage): string | undefined {
  if (typeof score !== "number" || Number.isNaN(score)) {
    return undefined;
  }
  const percent = `${Math.round(score * 100)}%`;
  return language === "zh-CN" ? `掌握度 ${percent}` : `Mastery ${percent}`;
}

function toPlanReviewItem(
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
    item.dueAt ? `${language === "zh-CN" ? "下次回看" : "Next review"}: ${formatReviewDueLabel(item.dueAt, language)}` : null,
    reviewSurfaceModeLabel(item.surfaceMode, language),
    formatIntervalDays(item.intervalDays, language),
    formatMasteryScore(item.masteryScore, language),
  ].filter(Boolean) as string[];
  return {
    id: `${item.source ?? "review"}-${item.concept}-${index}`,
    title: item.concept,
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

function warningText(
  id: ReturnType<typeof analyzeSendIntent>["warnings"][number]["id"],
  t: Copy,
): string {
  if (id === "review-needs-file") {
    return t.reviewNeedsFile;
  }
  if (id === "review-file-disabled") {
    return t.reviewFileDisabled;
  }
  if (id === "selection-enabled-without-selection") {
    return t.selectionMissing;
  }
  if (id === "selection-available-but-disabled") {
    return t.selectionDisabled;
  }
  if (id === "related-enabled-without-files") {
    return t.relatedMissing;
  }
  if (id === "related-available-but-disabled") {
    return t.relatedDisabled;
  }
  if (id === "diagnostics-enabled-without-signals") {
    return t.diagnosticsMissing;
  }
  return t.reviewNotFull;
}

function localizeAttachmentLabel(label: string, t: Copy): string {
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

function localizeAttachmentValue(value: string, t: Copy): string {
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

function localizeContextNote(value: string | undefined, language: ComposerLanguage): string | undefined {
  if (!value) {
    return value;
  }

  if (language === "zh-CN" && value === "Attached active code context") {
    return "参考了当前代码上下文";
  }

  if (language === "zh-CN" && value === "Attached Python file context") {
    return "参考了 Python 文件上下文";
  }

  return localizeKnownCoachUiText(value, language);
}

function localizeConversationMessage(
  message: ConversationMessage,
  t: Copy,
  language: ComposerLanguage,
): ConversationMessage {
  return {
    ...message,
    body: localizeKnownCoachUiText(message.body, language) ?? message.body,
    author:
      message.role === "user" && message.author.trim().toLowerCase() === "you"
        ? t.you
        : message.role === "assistant" &&
            (message.author.trim().toLowerCase() === "trainer" ||
              message.author.trim().toLowerCase() === "coach")
          ? t.trainer
          : message.role === "system" && message.author.trim().toLowerCase() === "system"
            ? language === "zh-CN"
              ? "系统"
              : "System"
            : message.author,
    attachments: message.attachments?.map((attachment) => ({
      label: localizeAttachmentLabel(attachment.label, t),
      value: localizeAttachmentValue(attachment.value, t),
    })),
    contextNote: localizeContextNote(message.contextNote, language),
  };
}

function learnerSignalLabel(
  value: NonNullable<ReturnType<typeof useWorkbenchState.getState>["data"]["coachingState"]>["learnerSignal"] | undefined,
  language: ComposerLanguage,
): string {
  if (value === "blocked") {
    return language === "zh-CN" ? "卡住" : "Blocked";
  }
  if (value === "uncertain") {
    return language === "zh-CN" ? "不确定" : "Uncertain";
  }
  if (value === "curious") {
    return language === "zh-CN" ? "好奇" : "Curious";
  }
  return language === "zh-CN" ? "稳定" : "Steady";
}

function coachingScenarioLabel(
  value: NonNullable<ReturnType<typeof useWorkbenchState.getState>["data"]["coachingState"]>["scenario"] | undefined,
  language: ComposerLanguage,
): string {
  const zh = {
    general: "常规引导",
    onboarding: "教练建联",
    idea_implementation: "想法落地",
    project_idea: "项目提炼",
    project_adaptation: "项目适配",
    project_sourcing: "项目来源",
    principle: "原理讲解",
    remote_workspace: "远程工作区",
    debug_loop: "调试闭环",
    function_guidance: "函数提示",
    review: "实现评审",
    plan: "计划推进",
    task: "训练任务",
    next_task: "下一步",
  } as const;
  const en = {
    general: "General coaching",
    onboarding: "Coach intake",
    idea_implementation: "Idea implementation",
    project_idea: "Project idea mining",
    project_adaptation: "Project adaptation",
    project_sourcing: "Project sourcing",
    principle: "Principle explanation",
    remote_workspace: "Remote workspace",
    debug_loop: "Debug loop",
    function_guidance: "Function guidance",
    review: "Review",
    plan: "Plan",
    task: "Task",
    next_task: "Next task",
  } as const;
  return (language === "zh-CN" ? zh : en)[value ?? "general"];
}

function normalizeTrainingStatus(value: string | undefined): string {
  return normalizeSharedTrainingStatus(value);
}

function normalizeTrainingSubmode(value: string | undefined): string {
  return normalizeSharedTrainingSubmode(value);
}

function isTrainingPrimerLike(input: {
  trainingSubmode?: string;
  selectedCardStatus?: string;
  latestTrainingHandoffStatus?: string;
}): boolean {
  return isSharedTrainingPrimerLike(input);
}

function trainingCardStatusLabel(value: string | undefined, language: ComposerLanguage): string | undefined {
  const normalized = normalizeTrainingStatus(value);
  if (!normalized) {
    return undefined;
  }
  const zh: Record<string, string> = {
    candidate: "候选",
    active: "进行中",
    needs_primer: "先学",
    answered: "已作答",
    implemented: "已完成",
    completed: "已完成",
    reviewed: "已复核",
    fed_back: "已回流",
    skipped: "已跳过",
    archived: "已归档",
    blocked: "已阻塞",
  };
  const en: Record<string, string> = {
    candidate: "Candidate",
    active: "Active",
    needs_primer: "Study first",
    answered: "Answered",
    implemented: "Completed",
    completed: "Completed",
    reviewed: "Reviewed",
    fed_back: "Returned",
    skipped: "Skipped",
    archived: "Archived",
    blocked: "Blocked",
  };
  return (language === "zh-CN" ? zh : en)[normalized] ?? value;
}

function trainingHandoffStatusLabel(value: string | undefined, language: ComposerLanguage): string | undefined {
  const normalized = normalizeTrainingStatus(value);
  if (!normalized) {
    return undefined;
  }
  const zh: Record<string, string> = {
    verified: "已验证",
    resolved: "已回流",
    needs_revision: "需返修",
    needs_primer: "先学",
    executed: "已接受",
    fed_back: "已回流",
    skipped: "已跳过",
    blocked: "已阻塞",
  };
  const en: Record<string, string> = {
    verified: "Verified",
    resolved: "Returned",
    needs_revision: "Needs revision",
    needs_primer: "Study first",
    executed: "Accepted",
    fed_back: "Returned",
    skipped: "Skipped",
    blocked: "Blocked",
  };
  return (language === "zh-CN" ? zh : en)[normalized] ?? value;
}

function compactCoachLine(
  label: string,
  value: string | undefined,
  language: ComposerLanguage,
): string | undefined {
  if (!value) {
    return undefined;
  }
  return language === "zh-CN" ? `${label}：${value}` : `${label}: ${value}`;
}

function coachLaneLabel(
  scenario:
    | NonNullable<ReturnType<typeof useWorkbenchState.getState>["data"]["coachingState"]>["scenario"]
    | undefined,
  language: ComposerLanguage,
): string {
  if (scenario === "project_adaptation") {
    return language === "zh-CN" ? "主线：项目适配" : "Lane: project adaptation";
  }
  if (scenario === "onboarding") {
    return language === "zh-CN" ? "主线：建立训练关系" : "Lane: coach intake";
  }
  if (scenario === "project_sourcing") {
    return language === "zh-CN" ? "主线：项目来源" : "Lane: project sourcing";
  }
  if (scenario === "remote_workspace") {
    return language === "zh-CN" ? "主线：远程工作区" : "Lane: remote workspace";
  }
  if (scenario === "debug_loop") {
    return language === "zh-CN" ? "主线：调试闭环" : "Lane: debug loop";
  }
  if (scenario === "function_guidance") {
    return language === "zh-CN" ? "主线：函数提示" : "Lane: function guidance";
  }
  if (scenario === "idea_implementation") {
    return language === "zh-CN" ? "主线：想法落地" : "Lane: idea implementation";
  }
  if (scenario === "project_idea") {
    return language === "zh-CN" ? "主线：项目提炼" : "Lane: project idea mining";
  }
  if (scenario === "principle") {
    return language === "zh-CN" ? "主线：原理讲解" : "Lane: principle";
  }
  if (scenario === "review") {
    return language === "zh-CN" ? "主线：实现评审" : "Lane: review";
  }
  if (scenario === "plan") {
    return language === "zh-CN" ? "主线：计划推进" : "Lane: plan";
  }
  return language === "zh-CN" ? "主线：当前训练" : "Lane: active coaching";
}

function sendContextSummary(
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
      layout.composerLanguage === "zh-CN"
        ? `${data.resources.length} 份资料`
        : `${data.resources.length} resource${data.resources.length === 1 ? "" : "s"}`,
    );
  }

  return parts.length > 0 ? parts.join(" · ") : t.noContext;
}

function sendContextShortSummary(
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
      ? layout.composerLanguage === "zh-CN"
        ? `${data.resources.length} 份资料`
        : `${data.resources.length} resource${data.resources.length === 1 ? "" : "s"}`
      : undefined,
  ].filter((value): value is string => Boolean(value));

  if (activeLabels.length === 0) {
    return t.noContext;
  }
  if (activeLabels.length >= 3) {
    return layout.composerLanguage === "zh-CN" ? "当前代码线索" : "current code context";
  }
  return activeLabels.join(" · ");
}

function sendContextPillItems(
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
        ? layout.composerLanguage === "zh-CN"
          ? `${data.liveContext.diagnosticErrors ?? 0} 错误 · ${data.liveContext.diagnosticWarnings ?? 0} 警告`
          : `${data.liveContext.diagnosticErrors ?? 0} errors · ${data.liveContext.diagnosticWarnings ?? 0} warnings`
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
        ? layout.composerLanguage === "zh-CN"
          ? `${data.liveContext.relatedFiles.length} 个相关文件`
          : `${data.liveContext.relatedFiles.length} related files`
        : undefined,
    active: layout.includeRelatedFiles && data.liveContext.relatedFiles.length > 0,
  });

  if (data.resources.length > 0) {
    items.push({
      id: "resources",
      label: t.attachments,
      value:
        layout.composerLanguage === "zh-CN"
          ? `${data.resources.length} 份资料`
          : `${data.resources.length} resources`,
      active: true,
    });
  }

  return items.filter((item) => item.active);
}

type ProviderRecoveryScenario =
  | "offline"
  | "starting"
  | "saved_connection"
  | "connection_setup"
  | "missing_key"
  | "checking"
  | "needs_attention";

type ProviderRecoverySummary = {
  title: string;
  detail: string;
  actionLabel: string;
};

type ProviderRecoveryLocale = {
  summary: Record<ProviderRecoveryScenario, ProviderRecoverySummary>;
  status: Record<ProviderRecoveryScenario, string>;
  stillAvailableDetail: string;
  languageIntegrityDetail: string;
  draftWhilePaused: string;
  connectionStillWorks: string;
};

const providerRecoveryCopy: Record<ComposerLanguage, ProviderRecoveryLocale> = {
  "zh-CN": {
    summary: {
      offline: {
        title: "Trainer 暂时还不能继续",
        detail: "打开“设置”检查连接。当前对话会保留在这里。",
        actionLabel: "打开设置",
      },
      starting: {
        title: "Trainer 正在准备中",
        detail: "稍等片刻，当前对话会自动恢复。",
        actionLabel: "查看连接",
      },
      saved_connection: {
        title: "选择一组已保存连接",
        detail: "“设置”里已有可用连接。选中它后继续。",
        actionLabel: "选择连接",
      },
      connection_setup: {
        title: "先连接模型",
        detail: "在“设置”完成连接后，Trainer 会从当前目标继续。",
        actionLabel: "连接模型",
      },
      missing_key: {
        title: "补上 API 密钥",
        detail: "这组连接已保存，但还缺少密钥。",
        actionLabel: "补上密钥",
      },
      checking: {
        title: "正在检查模型连接",
        detail: "Trainer 正在确认连接，请稍等。",
        actionLabel: "查看连接",
      },
      needs_attention: {
        title: "连接需要检查",
        detail: "到“设置”检查连接后再试。",
        actionLabel: "检查连接",
      },
    },
    status: {
      offline: "暂时不可用",
      starting: "准备中",
      saved_connection: "待选择",
      connection_setup: "待连接",
      missing_key: "缺少密钥",
      checking: "检查中",
      needs_attention: "需处理",
    },
    stillAvailableDetail: "仍可查看设置、资料和当前计划；新的教练回合会暂停。",
    languageIntegrityDetail: "消息没有正常送达。请在“设置”更换连接后重新测试。",
    draftWhilePaused: "连接恢复前，先把想法记在这里。",
    connectionStillWorks: "当前连接仍可继续",
  },
  "en-US": {
    summary: {
      offline: {
        title: "Trainer cannot continue yet",
        detail: "Open Settings to check the connection. This conversation will stay here.",
        actionLabel: "Open Settings",
      },
      starting: {
        title: "Trainer is getting ready",
        detail: "Give it a moment. This conversation will resume automatically.",
        actionLabel: "View connection",
      },
      saved_connection: {
        title: "Choose a saved connection",
        detail: "A saved connection is available in Settings. Select it to continue.",
        actionLabel: "Choose connection",
      },
      connection_setup: {
        title: "Connect a model to begin",
        detail: "Finish the connection in Settings. Trainer will continue from your current goal.",
        actionLabel: "Connect model",
      },
      missing_key: {
        title: "Add the API key",
        detail: "This connection is saved but still needs its key.",
        actionLabel: "Add key",
      },
      checking: {
        title: "Checking the model connection",
        detail: "Wait a moment while Trainer confirms the connection.",
        actionLabel: "View connection",
      },
      needs_attention: {
        title: "Connection needs attention",
        detail: "Check the connection in Settings, then try again.",
        actionLabel: "Check connection",
      },
    },
    status: {
      offline: "Unavailable",
      starting: "Starting",
      saved_connection: "Choose connection",
      connection_setup: "Setup needed",
      missing_key: "Key needed",
      checking: "Checking",
      needs_attention: "Needs attention",
    },
    stillAvailableDetail: "You can still review Settings, resources, and the current plan. New coach turns stay paused.",
    languageIntegrityDetail: "Messages did not arrive intact. In Settings, switch connections and test again.",
    draftWhilePaused: "Keep drafting while setup finishes.",
    connectionStillWorks: "Current connection still works",
  },
  "es-ES": {
    summary: {
      offline: {
        title: "Trainer aún no puede continuar",
        detail: "Abre Ajustes para revisar la conexión. Esta conversación se conservará aquí.",
        actionLabel: "Abrir Ajustes",
      },
      starting: {
        title: "Trainer se está preparando",
        detail: "Espera un momento. Esta conversación se reanudará automáticamente.",
        actionLabel: "Ver conexión",
      },
      saved_connection: {
        title: "Elige una conexión guardada",
        detail: "Hay una conexión guardada en Ajustes. Elígela para continuar.",
        actionLabel: "Elegir conexión",
      },
      connection_setup: {
        title: "Conecta un modelo para empezar",
        detail: "Completa la conexión en Ajustes. Trainer continuará desde tu objetivo actual.",
        actionLabel: "Conectar modelo",
      },
      missing_key: {
        title: "Añade la clave API",
        detail: "La conexión está guardada, pero aún necesita la clave.",
        actionLabel: "Añadir clave",
      },
      checking: {
        title: "Comprobando la conexión del modelo",
        detail: "Espera un momento mientras Trainer confirma la conexión.",
        actionLabel: "Ver conexión",
      },
      needs_attention: {
        title: "La conexión necesita atención",
        detail: "Revisa la conexión en Ajustes y vuelve a intentarlo.",
        actionLabel: "Revisar conexión",
      },
    },
    status: {
      offline: "No disponible",
      starting: "Iniciando",
      saved_connection: "Elegir conexión",
      connection_setup: "Falta configurar",
      missing_key: "Falta clave",
      checking: "Comprobando",
      needs_attention: "Revisar conexión",
    },
    stillAvailableDetail: "Aún puedes revisar Ajustes, recursos y el plan actual. Los nuevos turnos del coach quedan en pausa.",
    languageIntegrityDetail: "Los mensajes no llegaron correctamente. Cambia de conexión en Ajustes y vuelve a probar.",
    draftWhilePaused: "Puedes seguir escribiendo mientras termina la configuración.",
    connectionStillWorks: "La conexión actual sigue funcionando",
  },
  "fr-FR": {
    summary: {
      offline: {
        title: "Trainer ne peut pas encore continuer",
        detail: "Ouvrez Paramètres pour vérifier la connexion. Cette conversation restera ici.",
        actionLabel: "Ouvrir Paramètres",
      },
      starting: {
        title: "Trainer se prépare",
        detail: "Patientez un instant. Cette conversation reprendra automatiquement.",
        actionLabel: "Voir la connexion",
      },
      saved_connection: {
        title: "Choisissez une connexion enregistrée",
        detail: "Une connexion enregistrée est disponible dans Paramètres. Sélectionnez-la pour continuer.",
        actionLabel: "Choisir la connexion",
      },
      connection_setup: {
        title: "Connectez un modèle pour commencer",
        detail: "Terminez la connexion dans Paramètres. Trainer reprendra votre objectif actuel.",
        actionLabel: "Connecter un modèle",
      },
      missing_key: {
        title: "Ajoutez la clé API",
        detail: "Cette connexion est enregistrée, mais sa clé manque encore.",
        actionLabel: "Ajouter la clé",
      },
      checking: {
        title: "Vérification de la connexion du modèle",
        detail: "Patientez pendant que Trainer confirme la connexion.",
        actionLabel: "Voir la connexion",
      },
      needs_attention: {
        title: "La connexion demande une vérification",
        detail: "Vérifiez la connexion dans Paramètres, puis réessayez.",
        actionLabel: "Vérifier la connexion",
      },
    },
    status: {
      offline: "Indisponible",
      starting: "Démarrage",
      saved_connection: "Choisir la connexion",
      connection_setup: "Configuration requise",
      missing_key: "Clé requise",
      checking: "Vérification",
      needs_attention: "À vérifier",
    },
    stillAvailableDetail: "Vous pouvez encore consulter Paramètres, les ressources et le plan actuel. Les nouveaux tours du coach restent en pause.",
    languageIntegrityDetail: "Les messages ne sont pas arrivés correctement. Changez de connexion dans Paramètres et testez à nouveau.",
    draftWhilePaused: "Vous pouvez continuer à écrire pendant la préparation.",
    connectionStillWorks: "La connexion actuelle fonctionne encore",
  },
  "de-DE": {
    summary: {
      offline: {
        title: "Trainer kann noch nicht fortfahren",
        detail: "Öffne Einstellungen und prüfe die Verbindung. Diese Unterhaltung bleibt erhalten.",
        actionLabel: "Einstellungen öffnen",
      },
      starting: {
        title: "Trainer wird vorbereitet",
        detail: "Warte kurz. Diese Unterhaltung wird automatisch fortgesetzt.",
        actionLabel: "Verbindung ansehen",
      },
      saved_connection: {
        title: "Wähle eine gespeicherte Verbindung",
        detail: "In Einstellungen ist eine gespeicherte Verbindung verfügbar. Wähle sie zum Fortfahren.",
        actionLabel: "Verbindung wählen",
      },
      connection_setup: {
        title: "Verbinde ein Modell zum Start",
        detail: "Schließe die Verbindung in Einstellungen ab. Trainer macht bei deinem aktuellen Ziel weiter.",
        actionLabel: "Modell verbinden",
      },
      missing_key: {
        title: "API-Schlüssel hinzufügen",
        detail: "Diese Verbindung ist gespeichert, benötigt aber noch ihren Schlüssel.",
        actionLabel: "Schlüssel hinzufügen",
      },
      checking: {
        title: "Modellverbindung wird geprüft",
        detail: "Warte kurz, während Trainer die Verbindung bestätigt.",
        actionLabel: "Verbindung ansehen",
      },
      needs_attention: {
        title: "Verbindung muss geprüft werden",
        detail: "Prüfe die Verbindung in Einstellungen und versuche es erneut.",
        actionLabel: "Verbindung prüfen",
      },
    },
    status: {
      offline: "Nicht verfügbar",
      starting: "Startet",
      saved_connection: "Verbindung wählen",
      connection_setup: "Einrichtung nötig",
      missing_key: "Schlüssel fehlt",
      checking: "Wird geprüft",
      needs_attention: "Prüfung nötig",
    },
    stillAvailableDetail: "Du kannst weiterhin Einstellungen, Materialien und den aktuellen Plan ansehen. Neue Coach-Runden bleiben pausiert.",
    languageIntegrityDetail: "Nachrichten kamen nicht vollständig an. Wechsle die Verbindung in Einstellungen und teste erneut.",
    draftWhilePaused: "Du kannst weiter schreiben, während die Einrichtung fertig wird.",
    connectionStillWorks: "Die aktuelle Verbindung funktioniert weiter",
  },
  "ja-JP": {
    summary: {
      offline: {
        title: "Trainer はまだ続行できません",
        detail: "設定で接続を確認してください。会話はここに残ります。",
        actionLabel: "設定を開く",
      },
      starting: {
        title: "Trainer は準備中です",
        detail: "少し待ってください。この会話は自動で再開します。",
        actionLabel: "接続を確認",
      },
      saved_connection: {
        title: "保存済みの接続を選択",
        detail: "設定に利用できる接続があります。選択して続行してください。",
        actionLabel: "接続を選択",
      },
      connection_setup: {
        title: "モデルを接続して開始",
        detail: "設定で接続を完了してください。Trainer は現在の目標から続けます。",
        actionLabel: "モデルを接続",
      },
      missing_key: {
        title: "API キーを追加",
        detail: "この接続は保存済みですが、キーがまだ必要です。",
        actionLabel: "キーを追加",
      },
      checking: {
        title: "モデル接続を確認中",
        detail: "Trainer が接続を確認しています。少し待ってください。",
        actionLabel: "接続を確認",
      },
      needs_attention: {
        title: "接続の確認が必要です",
        detail: "設定で接続を確認してから、もう一度試してください。",
        actionLabel: "接続を確認",
      },
    },
    status: {
      offline: "利用不可",
      starting: "準備中",
      saved_connection: "接続を選択",
      connection_setup: "設定が必要",
      missing_key: "キーが必要",
      checking: "確認中",
      needs_attention: "要確認",
    },
    stillAvailableDetail: "設定、資料、現在の計画は引き続き確認できます。新しいコーチ対話は一時停止します。",
    languageIntegrityDetail: "メッセージが正しく届きませんでした。設定で接続を切り替えて、もう一度テストしてください。",
    draftWhilePaused: "設定が終わるまで、ここに考えを書き続けられます。",
    connectionStillWorks: "現在の接続は引き続き使えます",
  },
  "ko-KR": {
    summary: {
      offline: {
        title: "Trainer를 아직 계속 사용할 수 없습니다",
        detail: "설정에서 연결을 확인하세요. 이 대화는 그대로 유지됩니다.",
        actionLabel: "설정 열기",
      },
      starting: {
        title: "Trainer를 준비하는 중입니다",
        detail: "잠시 기다려 주세요. 이 대화는 자동으로 다시 시작됩니다.",
        actionLabel: "연결 보기",
      },
      saved_connection: {
        title: "저장된 연결을 선택하세요",
        detail: "설정에 사용할 수 있는 저장된 연결이 있습니다. 선택한 뒤 계속하세요.",
        actionLabel: "연결 선택",
      },
      connection_setup: {
        title: "모델을 연결해 시작하세요",
        detail: "설정에서 연결을 완료하세요. Trainer가 현재 목표부터 이어갑니다.",
        actionLabel: "모델 연결",
      },
      missing_key: {
        title: "API 키를 추가하세요",
        detail: "이 연결은 저장되었지만 아직 키가 필요합니다.",
        actionLabel: "키 추가",
      },
      checking: {
        title: "모델 연결을 확인하는 중입니다",
        detail: "Trainer가 연결을 확인하는 동안 잠시 기다려 주세요.",
        actionLabel: "연결 보기",
      },
      needs_attention: {
        title: "연결을 확인해야 합니다",
        detail: "설정에서 연결을 확인한 뒤 다시 시도하세요.",
        actionLabel: "연결 확인",
      },
    },
    status: {
      offline: "사용 불가",
      starting: "준비 중",
      saved_connection: "연결 선택",
      connection_setup: "설정 필요",
      missing_key: "키 필요",
      checking: "확인 중",
      needs_attention: "확인 필요",
    },
    stillAvailableDetail: "설정, 자료, 현재 계획은 계속 볼 수 있습니다. 새 코치 대화는 잠시 멈춥니다.",
    languageIntegrityDetail: "메시지가 정상적으로 도착하지 않았습니다. 설정에서 연결을 바꾼 뒤 다시 테스트하세요.",
    draftWhilePaused: "설정이 끝날 때까지 여기에서 계속 작성할 수 있습니다.",
    connectionStillWorks: "현재 연결은 계속 사용할 수 있습니다",
  },
  "pt-BR": {
    summary: {
      offline: {
        title: "O Trainer ainda não pode continuar",
        detail: "Abra Configurações para verificar a conexão. Esta conversa ficará aqui.",
        actionLabel: "Abrir configurações",
      },
      starting: {
        title: "O Trainer está se preparando",
        detail: "Aguarde um momento. Esta conversa será retomada automaticamente.",
        actionLabel: "Ver conexão",
      },
      saved_connection: {
        title: "Escolha uma conexão salva",
        detail: "Há uma conexão salva em Configurações. Selecione-a para continuar.",
        actionLabel: "Escolher conexão",
      },
      connection_setup: {
        title: "Conecte um modelo para começar",
        detail: "Conclua a conexão em Configurações. O Trainer continuará do seu objetivo atual.",
        actionLabel: "Conectar modelo",
      },
      missing_key: {
        title: "Adicione a chave de API",
        detail: "Esta conexão está salva, mas ainda precisa da chave.",
        actionLabel: "Adicionar chave",
      },
      checking: {
        title: "Verificando a conexão do modelo",
        detail: "Aguarde enquanto o Trainer confirma a conexão.",
        actionLabel: "Ver conexão",
      },
      needs_attention: {
        title: "A conexão precisa de atenção",
        detail: "Verifique a conexão em Configurações e tente novamente.",
        actionLabel: "Verificar conexão",
      },
    },
    status: {
      offline: "Indisponível",
      starting: "Iniciando",
      saved_connection: "Escolher conexão",
      connection_setup: "Configuração necessária",
      missing_key: "Chave necessária",
      checking: "Verificando",
      needs_attention: "Verificar conexão",
    },
    stillAvailableDetail: "Você ainda pode revisar Configurações, recursos e o plano atual. Novos turnos do coach ficam pausados.",
    languageIntegrityDetail: "As mensagens não chegaram corretamente. Troque a conexão em Configurações e teste novamente.",
    draftWhilePaused: "Você pode continuar escrevendo enquanto a configuração termina.",
    connectionStillWorks: "A conexão atual continua funcionando",
  },
};

function providerRecoveryLocale(language: ComposerLanguage): ProviderRecoveryLocale {
  return providerRecoveryCopy[language] ?? providerRecoveryCopy["en-US"];
}

function providerRecoveryScenario(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
): ProviderRecoveryScenario {
  if (connectionState === "offline") {
    return "offline";
  }
  if (connectionState === "starting") {
    return "starting";
  }

  const sendState = describeProviderSendState(provider, language);
  if (sendState.status === "missing_provider") {
    return hasSavedProviderProfiles(provider) ? "saved_connection" : "connection_setup";
  }
  if (sendState.status === "missing_api_key") {
    return "missing_key";
  }
  if (sendState.status === "warming" || sendState.status === "refreshing") {
    return "checking";
  }
  return "needs_attention";
}

function providerRecoverySummary(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
): ProviderRecoverySummary {
  const scenario = providerRecoveryScenario(provider, language, connectionState);
  return providerRecoveryLocale(language).summary[scenario];
}

function providerRecoveryStatusLabel(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
): string {
  const scenario = providerRecoveryScenario(provider, language, connectionState);
  return providerRecoveryLocale(language).status[scenario];
}

function providerSetupSummary(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
): ProviderRecoverySummary {
  return providerRecoverySummary(provider, language, connectionState);
}

function blockedComposerSetupMessage(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  _activeView: ActiveWorkbenchView,
  connectionState?: "starting" | "connected" | "offline",
): string {
  if (
    connectionState !== "offline" &&
    connectionState !== "starting" &&
    provider.configured &&
    provider.apiKeyConfigured &&
    !providerHasVerifiedStreamingProbe(provider)
  ) {
    return streamingCapabilityBlockReason(language);
  }
  return providerRecoverySummary(provider, language, connectionState).detail;
}

function blockedComposerPresenceMessage(
  provider: ProviderConfigView,
  language: ComposerLanguage,
  connectionState?: "starting" | "connected" | "offline",
): string {
  if (connectionState === "offline" || connectionState === "starting") {
    return providerRecoverySummary(provider, language, connectionState).title;
  }

  const sendState = describeProviderSendState(provider, language);
  const lastCategory = provider.lastTestResult?.errorCategory ?? provider.modelErrorCategory;

  if (
    (sendState.status === "blocked_error" || sendState.status === "degraded_error") &&
    lastCategory === "language_corruption"
  ) {
    return providerRecoveryLocale(language).languageIntegrityDetail;
  }

  return providerRecoverySummary(provider, language, connectionState).title;
}

function formatReviewDueLabel(value: string | undefined, language: ComposerLanguage): string | undefined {
  if (!value) {
    return undefined;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return language === "zh-CN"
    ? date.toLocaleString("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : date.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

function activeStageObjectiveText(stage: PlanStage | undefined, fallback: string): string {
  return stage?.objective?.trim() || stage?.title?.trim() || fallback;
}

function sendStatuslineText(
  analysis: ReturnType<typeof analyzeSendIntent>,
  data: ReturnType<typeof useWorkbenchState.getState>["data"],
  layout: ReturnType<typeof useWorkbenchState.getState>["layout"],
  t: Copy,
): string {
  if (analysis.isEmpty) {
    return "";
  }

  if (analysis.target === "local_command") {
    return `${t.runLocalCommand} · ${
      analysis.localCommandId
        ? sidebarControlCommandLabel(analysis.localCommandId, layout.composerLanguage)
        : t.noContext
    }`;
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
      ? layout.composerLanguage === "zh-CN"
        ? `附带 ${data.resources.length} 份资料`
        : `${data.resources.length} resource${data.resources.length === 1 ? "" : "s"} attached`
      : "";

  if (layout.composerLanguage === "zh-CN") {
    return [intentLabel, contextSummary, answerMode, resourceSummary].filter(Boolean).join(" · ");
  }

  return [intentLabel, contextSummary, answerMode, resourceSummary].filter(Boolean).join(" · ");
}

function composerHintText(
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
      ? layout.composerLanguage === "zh-CN"
        ? `${data.resources.length} 份资料`
        : `${data.resources.length} imported resource${data.resources.length === 1 ? "" : "s"}`
      : "";
  return [contextSummary, resourceSummary].filter(Boolean).join(" · ");
}

function composerShortcutHint({
  language,
  hasCommandDeck,
  hasContextMenu,
}: {
  language: ComposerLanguage;
  hasCommandDeck: boolean;
  hasContextMenu: boolean;
}): string {
  if (hasCommandDeck) {
    return language === "zh-CN"
      ? "↑↓ 选择 · Enter 执行 · Tab 补全 · Esc 关闭"
      : "Up/Down choose · Enter run · Tab complete · Esc close";
  }

  if (hasContextMenu) {
    return language === "zh-CN"
      ? "Enter 发送 · Shift+Enter 换行 · Esc 收起"
      : "Enter send · Shift+Enter newline · Esc close";
  }

  return "";
}

function focusComposerInput() {
  const element = document.getElementById("coach-composer");
  if (!(element instanceof HTMLTextAreaElement)) {
    return;
  }

  const caret = element.value.length;
  element.focus();
  element.setSelectionRange(caret, caret);
}

function defaultPromptText(
  intent: "coach" | "next_task" | "review" | "plan" | "task",
  language: ComposerLanguage,
  focusArea?: string,
): string {
  const zhFocus = focusArea ? `，重点围绕「${focusArea}」。` : "";
  const enFocus = focusArea ? ` Focus on "${focusArea}".` : "";
  if (intent === "next_task") {
    return language === "zh-CN"
      ? `请给我下一道训练题${zhFocus}`
      : `Give me the next training task.${enFocus}`;
  }
  if (intent === "review") {
    return language === "zh-CN"
      ? `请评审我当前文件的实现${zhFocus}`
      : `Review my current file.${enFocus}`;
  }
  if (intent === "plan") {
    return language === "zh-CN"
      ? `请刷新并重排我的当前训练计划${zhFocus}`
      : `Refresh and restructure my current training plan.${enFocus}`;
  }
  if (intent === "task") {
    return language === "zh-CN"
      ? `请把我当前目标转成一个可执行的小任务${zhFocus}`
      : `Turn my current goal into a concrete, executable task.${enFocus}`;
  }
  return language === "zh-CN"
    ? `请继续引导我实现这个想法${zhFocus}`
    : `Keep guiding me through this idea.${enFocus}`;
}

function planComposerDraftReplacementCopy(language: ComposerLanguage, stageTitle: string) {
  const targetTitle = stageTitle.trim() || (language === "zh-CN" ? "\u5f53\u524d\u9636\u6bb5" : "this stage");

  return language === "zh-CN"
    ? {
        title: "\u4f60\u5df2\u7ecf\u5199\u4e86\u5185\u5bb9\uff0c\u8fd8\u6ca1\u6709\u53d1\u9001\u3002",
        detail: `\u8981\u628a\u5b83\u6362\u6210\u56f4\u7ed5\u300c${targetTitle}\u300d\u7684\u5f15\u5bfc\u95ee\u9898\u5417\uff1f`,
        confirmLabel: "\u66ff\u6362\u5185\u5bb9",
        cancelLabel: "\u4fdd\u7559\u539f\u5185\u5bb9",
      }
    : {
        title: "You have an unsent draft.",
        detail: `Replace it with a prompt for "${targetTitle}"?`,
        confirmLabel: "Replace draft",
        cancelLabel: "Keep draft",
      };
}

function buildLocalCommandSuggestions({
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

function MenuList({
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

function MenuToggleRow({
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

type DirectoryInputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  webkitdirectory?: string;
};

const DirectoryInput = forwardRef<HTMLInputElement, DirectoryInputProps>(function DirectoryInput(
  props,
  ref,
) {
  return <input ref={ref} {...props} />;
});

function triggerResourceUpload({
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

const BROWSER_SUPPORTED_UPLOAD_EXTENSIONS = new Set([
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

function browserResourceKind(name: string): BrowserUploadResourceInputType["kind"] {
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

function browserFileSupported(file: File): boolean {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return BROWSER_SUPPORTED_UPLOAD_EXTENSIONS.has(extension);
}

function isBinaryBrowserFile(file: File): boolean {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return ["pdf", "png", "jpg", "jpeg", "webp", "gif", "bmp"].includes(extension);
}

async function readFileAsDataUrl(file: File): Promise<string> {
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

async function readBrowserFiles(
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

function browserUploadLooksLikeFolder(files: File[]): boolean {
  return files.some((file) => Boolean(file.webkitRelativePath));
}

export function App() {
  const {
    data,
    layout,
    operationMessage,
    streaming,
    resourceOrganizationPending,
    resourceRestoreContext,
    trainingRestoreContext,
    hasReceivedHostState,
    setActiveView,
    setResourceRestoreContext,
    setComposerDraft,
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
    setOperationMessage: setRawOperationMessage,
    setThemePreference,
    setLearningSurfaceAlignment,
    applyHostMessage: applyRawHostMessage,
  } = useWorkbenchState();

  const [openMenu, setOpenMenu] = useState<ContextMenu>();
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0);
  const [dismissedComposerDeck, setDismissedComposerDeck] = useState<ComposerDeckKind>();
  const composerDeckRef = useRef<HTMLDivElement | null>(null);
  const composerHistoryCursorRef = useRef<number | undefined>(undefined);
  const composerHistoryScratchDraftRef = useRef("");
  const streamResumeDraftRef = useRef("");
  const sendRecoveredPlanResumeRef = useRef<
    (action: "continue_step" | "clear_blocker") => void
  >(() => undefined);
  const sentMessageHistoryLengthRef = useRef(0);
  const [previewSessionId, setPreviewSessionId] = useState<string>();
  const [composerAttachments, setComposerAttachments] = useState<MessageAttachment[]>([]);
  const [providerDraft, setProviderDraft] = useState<ProviderDraft>({
    name: "",
    protocol: "openai_chat_completions_compatible",
    baseUrl: "",
    model: "",
    contextWindowTokens: undefined,
    maxOutputTokens: undefined,
    modelTokenLimits: undefined,
    credentialMode: "ui_proxy",
    catalogModels: [],
    allowedModels: [],
    deniedModels: [],
    embeddingModel: "",
    catalogSource: "provider_live",
    cacheTtlSeconds: undefined,
    requestDefaults: {},
    apiKey: "",
  });
  const providerDraftIsDirtyRef = useRef(false);
  const providerDraftSourceKeyRef = useRef<string>();
  const [composerModelQuery, setComposerModelQuery] = useState("");
  const [composerModelActionDensity, setComposerModelActionDensity] =
    useState<ComposerModelActionDensity>("default");
  const [headerSwitcherDensity, setHeaderSwitcherDensity] = useState<HeaderSwitcherDensity>("full");
  const [settingsActionState, setSettingsActionState] = useState<SettingsActionState>();
  const [settingsFeedbackState, setSettingsFeedbackState] = useState<SettingsFeedbackState>({});
  const [providerApiKeyFocusRequest, setProviderApiKeyFocusRequest] = useState(0);
  const [trainingComposerFlashMode, setTrainingComposerFlashMode] =
    useState<FlashVerificationMode>("short");
  const [trainingComposerVerifyIndex, setTrainingComposerVerifyIndex] = useState(0);
  const [trainingComposerPracticeReturnMode, setTrainingComposerPracticeReturnMode] =
    useState<TrainingPracticeReturnMode>("result");
  const [trainingComposerRoute, setTrainingComposerRoute] =
    useState<TrainingComposerRoute>("card");
  const trainingRouteDraftsRef = useRef<Record<TrainingComposerRoute, string>>({
    card: "",
    coach: "",
  });
  const [planComposerMode, setPlanComposerMode] = useState<PlanComposerMode>("explain");
  const [trainingVerifyNotice, setTrainingVerifyNotice] = useState<string | undefined>();
  const [operationMessageSurface, setOperationMessageSurface] = useState<"global" | "training" | "plan">("global");
  const [pendingPlanComposerDraftReplacement, setPendingPlanComposerDraftReplacement] =
    useState<PlanComposerDraftReplacement>();
  const [resourcesComposerMode, setResourcesComposerMode] =
    useState<ResourcesComposerMode>("locate");
  const [selectedResourceContextIds, setSelectedResourceContextIds] = useState<string[]>([]);
  const [resourceConversationContextIds, setResourceConversationContextIds] = useState<string[]>([]);
  const [lastTurnView, setLastTurnView] = useState<ActiveWorkbenchView>();
  const [coachContextTransition, setCoachContextTransition] = useState<
    { signature: string; conversationLength: number } | undefined
  >();
  const headerSwitcherRef = useRef<HTMLDivElement | null>(null);
  const composerShellRef = useRef<HTMLDivElement | null>(null);
  const composerModelAutoRefreshKeyRef = useRef("");
  const settingsModelAutoPrimeKeyRef = useRef("");
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
  const trainingPersistenceResolversRef = useRef(new Map<string, PendingTrainingPersistence>());
  const trainingPersistenceSequenceRef = useRef(0);
  const [trainingPersistencePending, setTrainingPersistencePending] = useState(false);
  const [userFeedbackState, setUserFeedbackState] = useState<{
    busy: boolean;
    submittedKind?: UserFeedbackKind;
    error?: string;
  }>({ busy: false });
  const userFeedbackPendingKindRef = useRef<UserFeedbackKind>();
  const injectedPreviewBootstrapHydratedRef = useRef(false);
  const browserPreviewLocationOverridesAppliedRef = useRef(false);
  const pendingTrainingHandoffSubmissionRef = useRef<
    { phase: "reflect" | "return"; cardId: string } | undefined
  >();
  const pendingLivePlanTaskMintRef = useRef<{ commandId: string } | undefined>();
  const resolvedTheme = useMemo(() => resolveTheme(layout.themePreference), [layout.themePreference]);
  const isBrowserPreview = inBrowserPreviewEnvironment();
  const activeView = normalizeSidebarView(layout.activeView);
  const browserPreviewFixture = isBrowserPreviewFixtureMode();
  const t = resolveWorkbenchCopy(layout.composerLanguage);
  const openProviderSetup = useCallback(() => {
    setActiveView("settings");
    if (!data.providerConfig.apiKeyConfigured) {
      setProviderApiKeyFocusRequest((request) => request + 1);
    }
  }, [data.providerConfig.apiKeyConfigured, setActiveView]);
  const localizedResourceOperationFallback = t.stageDone;
  const planText = resolvePlanViewCopy(layout.composerLanguage);
  const setOperationMessage = useCallback(
    (message?: OperationMessage) => {
      setRawOperationMessage(
        message ? sanitizeOperationFailureMessage(message, layout.composerLanguage) : undefined,
      );
    },
    [layout.composerLanguage, setRawOperationMessage],
  );
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
      const isZh = layout.composerLanguage === "zh-CN";
      userFeedbackPendingKindRef.current = kind;
      setUserFeedbackState({ busy: true });
      postMessage({
        type: "command/execute",
        payload: {
          commandId: trainerCommands.recordUserFeedback,
          payload: {
            kind,
            message: isZh ? "这一步不合适。" : "This step does not fit.",
            scenario: activeView === "training" ? "training" : "coach",
            focusArea: data.memory.workspace?.latestLearningFocusArea,
            trainingCardId: undefined,
            planId: data.plan?.id,
          },
        },
      });
      window.setTimeout(() => {
        setUserFeedbackState((current) => current.busy ? { busy: false, error: isZh ? "反馈未收到确认，可重试。" : "No acknowledgement received; try again." } : current);
      }, 12000);
    },
    [activeView, data.memory.workspace, data.plan?.id, isBrowserPreview, layout.composerLanguage, postMessage, userFeedbackState.busy, userFeedbackState.submittedKind],
  );

  const resolveTrainingPersistenceAck = useCallback((message: HostMessage) => {
    if (message.type !== "training/persistenceAck") {
      return;
    }
    const pending = trainingPersistenceResolversRef.current.get(message.payload.requestId);
    if (!pending || pending.commandId !== message.payload.commandId) {
      return;
    }
    trainingPersistenceResolversRef.current.delete(message.payload.requestId);
    window.clearTimeout(pending.timeoutId);
    if (trainingPersistenceResolversRef.current.size === 0) {
      setTrainingPersistencePending(false);
    }
    if (message.payload.ok) {
      pending.resolve(message.payload.data);
    } else {
      const failureMessage =
        typeof message.payload.message === "string" && message.payload.message.trim()
          ? message.payload.message
          : "Training persistence was not acknowledged.";
      pending.reject(new Error(failureMessage));
    }
  }, []);
  const requestTrainingPersistence = useCallback(
    (commandId: string, payload: Record<string, unknown>): Promise<unknown> => {
      const requestId = `training-persistence-${Date.now().toString(36)}-${++trainingPersistenceSequenceRef.current}`;
      return new Promise<unknown>((resolve, reject) => {
        const timeoutId = window.setTimeout(() => {
          const pending = trainingPersistenceResolversRef.current.get(requestId);
          if (!pending) {
            return;
          }
          trainingPersistenceResolversRef.current.delete(requestId);
          if (trainingPersistenceResolversRef.current.size === 0) {
            setTrainingPersistencePending(false);
          }
          pending.reject(new Error("Training persistence timed out."));
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.trainingReliabilityControl,
              payload: {
                requestId,
                action: "cancel",
              },
            },
          });
        }, TRAINING_PERSISTENCE_TIMEOUT_MS);
        trainingPersistenceResolversRef.current.set(requestId, {
          commandId,
          resolve,
          reject,
          timeoutId,
        });
        setTrainingPersistencePending(true);
        try {
          postMessage({
            type: "command/execute",
            payload: {
              commandId,
              payload: {
                ...payload,
                __trainerTrainingPersistenceId: requestId,
              },
            },
          });
        } catch (error) {
          const pending = trainingPersistenceResolversRef.current.get(requestId);
          trainingPersistenceResolversRef.current.delete(requestId);
          if (trainingPersistenceResolversRef.current.size === 0) {
            setTrainingPersistencePending(false);
          }
          if (pending) {
            window.clearTimeout(pending.timeoutId);
            pending.reject(error);
          } else {
            reject(error);
          }
        }
      });
    },
    [],
  );
  useEffect(() => {
    return () => {
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
      for (const pending of trainingPersistenceResolversRef.current.values()) {
        window.clearTimeout(pending.timeoutId);
        pending.reject(new Error("Training persistence was interrupted."));
      }
      trainingPersistenceResolversRef.current.clear();
    };
  }, []);
  const applyHostMessage = useCallback(
    (message: HostMessage, isProviderActionOverride = false) => {
      hostMessageSequenceRef.current += 1;
      if (message.type === "training/resourceHandoff") {
        const handoff = resourceTrainingHandoffResolversRef.current.get(message.payload.requestId);
        if (handoff?.resourceId === message.payload.resourceId) {
          resourceTrainingHandoffResolversRef.current.delete(message.payload.requestId);
          window.clearTimeout(handoff.timeoutId);
          handoff.resolve(message.payload);
        }
        return;
      }
      if (message.type === "training/persistenceAck") {
        resolveTrainingPersistenceAck(message);
        return;
      }
      if (message.type === "operation/status" && message.payload.message.includes("Learning feedback recorded")) {
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
        setProviderApiKeyFocusRequest((request) => request + 1);
      }
      if (resourceOperationStatus?.kind !== "search") {
        applyRawHostMessage(
          sanitizeHostFailureMessage(
            resolvedMessage,
            layout.composerLanguage,
            Boolean(isProviderActionOverride || settingsActionState?.targets.includes("provider")),
            resourceOperationStatus?.kind,
          ),
        );
      }
      if (resolvedMessage.type === "ui/coachPrompt" && typeof window !== "undefined") {
        window.requestAnimationFrame(() => {
          document.getElementById("coach-composer")?.focus();
        });
      }
    },
    [
      applyRawHostMessage,
      layout.composerLanguage,
      localizedResourceOperationFallback,
      resolveTrainingPersistenceAck,
      resolveResourceOperationStatus,
      settingsActionState,
    ],
  );
  const showComposerShell = activeView !== "settings";
  const openTrainingCoachBridge = useCallback(
    (bridge: Parameters<typeof composeTrainingCoachBridgeDraft>[0]) => {
      setActiveView("coach");
      setComposerDraft(composeTrainingCoachBridgeDraft(bridge));
      window.requestAnimationFrame(() => {
        focusComposerInput();
      });
    },
    [setActiveView, setComposerDraft],
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
          layout.composerLanguage === "zh-CN"
            ? "资料写入权限还没确认。先在设置里选工作区根目录。"
            : "Resource write access has not been confirmed. Choose a workspace root in Settings first.",
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
    setActiveView(trainerWorkspaceAdmission?.status === "root-missing" ? "settings" : "coach");
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
  const normalizedDraft = draft.trim();
  useEffect(() => {
    if (activeView === "plan" && normalizedDraft) {
      return;
    }

    setPendingPlanComposerDraftReplacement(undefined);
  }, [activeView, normalizedDraft]);

  const applyPlanComposerGuidance = (targetTitle: string) => {
    setPendingPlanComposerDraftReplacement(undefined);
    setComposerDraft(planText.stageGuidancePrompt(targetTitle));
    window.requestAnimationFrame(() => {
      focusComposerInput();
    });
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
  const sessionSentMessageHistory = useMemo(
    () =>
      data.conversation
        .filter((message) => message.role === "user")
        .map((message) => message.body.trim())
        .filter(Boolean),
    [data.conversation],
  );
  const resetComposerHistoryNavigation = useCallback(() => {
    composerHistoryCursorRef.current = undefined;
    composerHistoryScratchDraftRef.current = "";
  }, []);
  useEffect(() => {
    if (sentMessageHistoryLengthRef.current === sessionSentMessageHistory.length) {
      return;
    }
    sentMessageHistoryLengthRef.current = sessionSentMessageHistory.length;
    resetComposerHistoryNavigation();
  }, [resetComposerHistoryNavigation, sessionSentMessageHistory.length]);
  const navigateComposerHistory = useCallback(
    (direction: "previous" | "next") => {
      if (sessionSentMessageHistory.length === 0) {
        return false;
      }

      const currentIndex = composerHistoryCursorRef.current;
      if (direction === "previous") {
        const nextIndex =
          currentIndex === undefined
            ? sessionSentMessageHistory.length - 1
            : currentIndex > 0
              ? currentIndex - 1
              : undefined;
        if (nextIndex === undefined) {
          return false;
        }
        if (currentIndex === undefined) {
          composerHistoryScratchDraftRef.current = draft;
        }
        composerHistoryCursorRef.current = nextIndex;
        setComposerDraft(sessionSentMessageHistory[nextIndex] ?? "");
        return true;
      }

      if (currentIndex === undefined) {
        return false;
      }
      const nextIndex = currentIndex + 1;
      if (nextIndex >= sessionSentMessageHistory.length) {
        composerHistoryCursorRef.current = undefined;
        setComposerDraft(composerHistoryScratchDraftRef.current);
        composerHistoryScratchDraftRef.current = "";
        return true;
      }

      composerHistoryCursorRef.current = nextIndex;
      setComposerDraft(sessionSentMessageHistory[nextIndex] ?? "");
      return true;
    },
    [draft, sessionSentMessageHistory, setComposerDraft],
  );
  const handleComposerDraftChange = useCallback(
    (nextDraft: string) => {
      resetComposerHistoryNavigation();
      setDismissedComposerDeck(undefined);
      if (activeView === "training") {
        trainingRouteDraftsRef.current[trainingComposerRoute] = nextDraft;
      }
      setComposerDraft(nextDraft);
    },
    [activeView, resetComposerHistoryNavigation, setComposerDraft, trainingComposerRoute],
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
    data.memory.workspace?.workspaceId ?? data.workspaceTrainingState?.workspaceId;
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
  const providerTransportConnected = data.connection.state === "connected";
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
  const providerCanCoachNow = providerTransportConnected && !providerSendState.blocked;
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
  const shouldShowNeutralEmptyState =
    data.conversation.length === 0 && (!providerCanCoachNow || displayConnectionState !== "connected");
  const isFirstCoachConversation = data.conversation.length === 0;
  const baselineConnectedMessage = useMemo(
    () =>
      layout.composerLanguage === "zh-CN" ? "已连接到扩展宿主。" : "Connected to extension host.",
    [layout.composerLanguage],
  );
  const providerSavePayload = useMemo(() => {
    const trimmedApiKey = providerDraft.apiKey.trim();
    return {
      name: providerDraft.name,
      protocol: providerDraft.protocol,
      baseUrl: providerDraft.baseUrl,
      model: providerDraft.model,
      contextWindowTokens: providerDraft.contextWindowTokens ?? null,
      maxOutputTokens: providerDraft.maxOutputTokens ?? null,
      modelTokenLimits: providerDraft.modelTokenLimits,
      credentialMode: providerDraft.credentialMode,
      catalogModels: providerDraft.catalogModels ?? [],
      allowedModels: providerDraft.allowedModels ?? [],
      deniedModels: providerDraft.deniedModels ?? [],
      embeddingModel: providerDraft.embeddingModel?.trim() || "",
      catalogSource: providerDraft.catalogSource,
      cacheTtlSeconds: providerDraft.cacheTtlSeconds ?? null,
      requestDefaults: providerDraft.requestDefaults ?? {},
      ...(trimmedApiKey ? { apiKey: trimmedApiKey, replaceApiKey: true } : {}),
      capabilities: data.providerConfig.capabilities,
    };
  }, [data.providerConfig.capabilities, providerDraft]);

  const providerDraftSource = useMemo(
    () => ({
      configured: data.providerConfig.configured,
      profileId: data.providerConfig.profileId ?? "",
      name: data.providerConfig.name,
      protocol: data.providerConfig.protocol ?? "openai_chat_completions_compatible",
      baseUrl: data.providerConfig.baseUrl,
      model: data.providerConfig.model,
      contextWindowTokens: data.providerConfig.contextWindowTokens,
      maxOutputTokens: data.providerConfig.maxOutputTokens,
      modelTokenLimits: data.providerConfig.modelTokenLimits,
      credentialMode: data.providerConfig.credentialMode ?? "ui_proxy",
      catalogModels: data.providerConfig.catalogModels ?? [],
      allowedModels: data.providerConfig.allowedModels ?? [],
      deniedModels: data.providerConfig.deniedModels ?? [],
      embeddingModel: data.providerConfig.embeddingModel ?? "",
      catalogSource: data.providerConfig.catalogSource ?? "provider_live",
      cacheTtlSeconds: data.providerConfig.cacheTtlSeconds,
      requestDefaults: data.providerConfig.requestDefaults ?? {},
    }),
    [
      data.providerConfig.configured,
      data.providerConfig.profileId,
      data.providerConfig.name,
      data.providerConfig.protocol,
      data.providerConfig.baseUrl,
      data.providerConfig.model,
      data.providerConfig.contextWindowTokens,
      data.providerConfig.maxOutputTokens,
      data.providerConfig.modelTokenLimits,
      data.providerConfig.credentialMode,
      data.providerConfig.catalogModels,
      data.providerConfig.allowedModels,
      data.providerConfig.deniedModels,
      data.providerConfig.embeddingModel,
      data.providerConfig.catalogSource,
      data.providerConfig.cacheTtlSeconds,
      data.providerConfig.requestDefaults,
    ],
  );
  const providerDraftSourceKey = JSON.stringify(providerDraftSource);

  useEffect(() => {
    if (providerDraftSourceKeyRef.current === providerDraftSourceKey) {
      return;
    }
    providerDraftSourceKeyRef.current = providerDraftSourceKey;

    const shouldKeepUnsavedProviderDraft =
      providerDraftIsDirtyRef.current &&
      settingsActionState?.kind !== "save-provider" &&
      settingsActionState?.kind !== "clear-provider";
    if (shouldKeepUnsavedProviderDraft) {
      return;
    }

    setProviderDraft({
      name: providerDraftSource.name,
      protocol: providerDraftSource.protocol,
      baseUrl: providerDraftSource.baseUrl,
      model: providerDraftSource.model,
      contextWindowTokens: providerDraftSource.contextWindowTokens,
      maxOutputTokens: providerDraftSource.maxOutputTokens,
      modelTokenLimits: providerDraftSource.modelTokenLimits,
      credentialMode: providerDraftSource.credentialMode,
      catalogModels: providerDraftSource.catalogModels,
      allowedModels: providerDraftSource.allowedModels,
      deniedModels: providerDraftSource.deniedModels,
      embeddingModel: providerDraftSource.embeddingModel,
      catalogSource: providerDraftSource.catalogSource,
      cacheTtlSeconds: providerDraftSource.cacheTtlSeconds,
      requestDefaults: providerDraftSource.requestDefaults,
      apiKey: "",
    });
    providerDraftIsDirtyRef.current = false;
  }, [providerDraftSource, providerDraftSourceKey, settingsActionState?.kind]);

  const providerDraftHasUnsavedApiKey = providerDraft.apiKey.trim().length > 0;
  const providerDraftHasChanges = useMemo(
    () =>
      providerDraft.name !== data.providerConfig.name ||
      normalizeProviderProtocol(providerDraft.protocol) !==
        normalizeProviderProtocol(data.providerConfig.protocol) ||
      providerDraft.baseUrl !== data.providerConfig.baseUrl ||
      providerDraft.model !== data.providerConfig.model ||
      providerDraft.contextWindowTokens !== data.providerConfig.contextWindowTokens ||
      providerDraft.maxOutputTokens !== data.providerConfig.maxOutputTokens ||
      providerModelTokenLimitsKey(providerDraft.modelTokenLimits) !==
        providerModelTokenLimitsKey(data.providerConfig.modelTokenLimits) ||
      providerDraft.credentialMode !== data.providerConfig.credentialMode ||
      providerDraftStringArrayKey(providerDraft.catalogModels) !==
        providerDraftStringArrayKey(data.providerConfig.catalogModels) ||
      providerDraftStringArrayKey(providerDraft.allowedModels) !==
        providerDraftStringArrayKey(data.providerConfig.allowedModels) ||
      providerDraftStringArrayKey(providerDraft.deniedModels) !==
        providerDraftStringArrayKey(data.providerConfig.deniedModels) ||
      (providerDraft.embeddingModel ?? "") !== (data.providerConfig.embeddingModel ?? "") ||
      providerDraft.catalogSource !== data.providerConfig.catalogSource ||
      providerDraft.cacheTtlSeconds !== data.providerConfig.cacheTtlSeconds ||
      providerRequestDefaultsKey(providerDraft.requestDefaults) !==
        providerRequestDefaultsKey(data.providerConfig.requestDefaults) ||
      providerDraftHasUnsavedApiKey,
    [
      data.providerConfig.baseUrl,
      data.providerConfig.cacheTtlSeconds,
      data.providerConfig.catalogSource,
      data.providerConfig.credentialMode,
      data.providerConfig.catalogModels,
      data.providerConfig.deniedModels,
      data.providerConfig.embeddingModel,
      data.providerConfig.model,
      data.providerConfig.modelTokenLimits,
      data.providerConfig.name,
      data.providerConfig.protocol,
      data.providerConfig.allowedModels,
      data.providerConfig.requestDefaults,
      providerDraft.baseUrl,
      providerDraft.cacheTtlSeconds,
      providerDraft.catalogSource,
      providerDraft.contextWindowTokens,
      providerDraft.credentialMode,
      providerDraft.deniedModels,
      providerDraft.embeddingModel,
      providerDraft.model,
      providerDraft.modelTokenLimits,
      providerDraft.maxOutputTokens,
      providerDraft.name,
      providerDraft.protocol,
      providerDraft.catalogModels,
      providerDraft.allowedModels,
      providerDraft.requestDefaults,
      data.providerConfig.contextWindowTokens,
      data.providerConfig.maxOutputTokens,
      providerDraftHasUnsavedApiKey,
    ],
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

  const composerProviderMenuItems = useMemo<ComposerProviderMenuItem[]>(() => {
    const providerApplied = data.providerConfig.configured;
    const activeProfileId = providerApplied ? data.providerConfig.profileId?.trim() : undefined;
    const resolvedModel = data.providerConfig.resolvedModel?.trim() ?? "";
    const configuredModel = data.providerConfig.model.trim();
    const activeModel = providerApplied ? resolvedModel || configuredModel : "";
    const activeModelKey = activeModel.toLowerCase();
    const resolvedModelKey = resolvedModel.toLowerCase();
    const configuredModelKey = configuredModel.toLowerCase();
    const configuredModelIsAlias = Boolean(
      resolvedModelKey && configuredModelKey && resolvedModelKey !== configuredModelKey,
    );
    const liveModels = Array.isArray(data.providerConfig.availableModels)
      ? data.providerConfig.availableModels
      : [];
    const fallbackModels = [
      ...(Array.isArray(data.providerConfig.catalogModels) ? data.providerConfig.catalogModels : []),
      ...Object.keys(data.providerConfig.modelTokenLimits ?? {}),
    ];
    const modelCandidates = providerApplied
      ? [
          ...(liveModels.length > 0 ? liveModels : fallbackModels),
          resolvedModel,
          ...(resolvedModel ? [] : [configuredModel]),
        ]
      : [];
    const currentProviderModelPolicy = {
      allowedModels: data.providerConfig.allowedModels,
      deniedModels: data.providerConfig.deniedModels,
    };
    const filteredModelCandidates = filterProviderModelOptions(
      modelCandidates,
      currentProviderModelPolicy,
      { retainModels: activeModel ? [activeModel] : [] },
    );
    const knownModelMap = new Map<string, string>();
    for (const candidate of filteredModelCandidates) {
      const modelName = typeof candidate === "string" ? candidate.trim() : "";
      const modelKey = modelName.toLowerCase();
      if (
        !modelName ||
        (configuredModelIsAlias && modelKey === configuredModelKey) ||
        knownModelMap.has(modelKey)
      ) {
        continue;
      }
      knownModelMap.set(modelKey, modelName);
    }
    const knownModels = Array.from(knownModelMap.values());
    const activeProviderLabel =
      data.providerConfig.profileLabel?.trim() ??
      data.providerConfig.name?.trim() ??
      (layout.composerLanguage === "zh-CN" ? "当前连接" : "Current connection");
    const activeProviderModelItems =
      knownModels.length > 0
        ? knownModels.map((modelName) => {
            const modelPolicy = evaluateProviderModelPolicy(modelName, currentProviderModelPolicy);
            const isActive = modelName.toLowerCase() === activeModelKey;
            return {
              id: `model:${modelName}`,
              selectionKind: "model" as const,
              label: modelName,
              model: modelName,
              isActive,
              isSelectable: modelPolicy.allowed && !isActive,
              policyReason: modelPolicy.reason,
            };
          })
        : [];
    const profileRecords = Array.isArray(data.providerConfig.providerProfiles)
      ? data.providerConfig.providerProfiles
      : [];
    const items = profileRecords
      .map((profile) => {
        if (!profile || typeof profile !== "object" || Array.isArray(profile)) {
          return undefined;
        }

        const record = profile as Record<string, unknown>;
        const id = typeof record.id === "string" ? record.id.trim() : "";
        if (!id) {
          return undefined;
        }

        const label =
          typeof record.label === "string" && record.label.trim()
            ? record.label.trim()
            : typeof record.name === "string" && record.name.trim()
              ? record.name.trim()
              : id;
        const model =
          typeof record.model === "string" && record.model.trim()
            ? record.model.trim()
            : data.providerConfig.model;
        return {
          id,
          selectionKind: "profile",
          label,
          model,
          isActive: activeProfileId ? activeProfileId === id : false,
        };
      })
      .filter(Boolean) as ComposerProviderMenuItem[];

    if (items.length > 0) {
      const activeIndex = items.findIndex((item) => item.isActive);
      if (activeIndex > 0) {
        const [activeItem] = items.splice(activeIndex, 1);
        if (activeItem) {
          items.unshift(activeItem);
        }
      }
      if (activeProviderModelItems.length > 0) {
        return [
          ...activeProviderModelItems,
          ...items.filter((item) => !item.isActive),
        ];
      }
      return items;
    }

    if (!providerApplied) {
      return [];
    }

    if (activeProviderModelItems.length > 0) {
      return activeProviderModelItems;
    }

    return [
      {
        id: activeProfileId ?? data.providerConfig.name ?? "provider",
        selectionKind: "profile",
        label: activeProviderLabel,
        model: activeModel,
        isActive: true,
      },
    ];
  }, [
    data.providerConfig.configured,
    data.providerConfig.availableModels,
    data.providerConfig.allowedModels,
    data.providerConfig.catalogModels,
    data.providerConfig.deniedModels,
    data.providerConfig.model,
    data.providerConfig.name,
    data.providerConfig.profileId,
    data.providerConfig.profileLabel,
    data.providerConfig.providerProfiles,
    data.providerConfig.resolvedModel,
    data.providerConfig.modelTokenLimits,
    layout.composerLanguage,
  ]);

  const filteredComposerProviderMenuItems = useMemo(() => {
    const query = composerModelQuery.trim().toLowerCase();
    if (!query) {
      return composerProviderMenuItems;
    }

    return composerProviderMenuItems.filter((item) =>
      [item.label, item.model].some((value) => value.toLowerCase().includes(query)),
    );
  }, [composerModelQuery, composerProviderMenuItems]);

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

    if (!operationMessage) {
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
      providerDraftIsDirtyRef.current = false;
      setProviderDraft((current) => (current.apiKey ? { ...current, apiKey: "" } : current));
    }
    setSettingsActionState(undefined);
  }, [layout.composerLanguage, operationMessage, settingsActionState]);

  useEffect(() => {
    applyWorkbenchTheme(resolvedTheme);
  }, [resolvedTheme]);

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
      const elapsed = Date.now() - lastBootstrapRequestAt;
      if (!hasReceivedHostState || elapsed > 1500) {
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
    if (!hasReceivedHostState || isBrowserPreview || activeView !== "resources") {
      return;
    }

    postMessage({
      type: "command/execute",
      payload: {
        commandId: trainerCommands.refreshResourceTrash,
      },
    });
  }, [activeView, hasReceivedHostState, isBrowserPreview]);

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

  const sidebarViewTabs = COACH_FIRST_SIDEBAR_VIEWS.map((view) => {
    if (view === "coach") {
      const label = coachViewLabel(layout.composerLanguage);
      return {
        view,
        label,
        compactLabel: compactSidebarViewLabel(view, layout.composerLanguage, label),
      };
    }
    if (view === "plan") {
      const label = planViewLabel(layout.composerLanguage);
      return {
        view,
        label,
        compactLabel: compactSidebarViewLabel(view, layout.composerLanguage, label),
      };
    }
    if (view === "resources") {
      const label = resourcesViewLabel(layout.composerLanguage);
      return {
        view,
        label,
        compactLabel: compactSidebarViewLabel(view, layout.composerLanguage, label),
      };
    }
    if (view === "training") {
      const label = trainingViewLabel(layout.composerLanguage);
      return {
        view,
        label,
        compactLabel: compactSidebarViewLabel(view, layout.composerLanguage, label),
      };
    }
    const label = settingsViewLabel(layout.composerLanguage);
    return {
      view,
      label,
      compactLabel: compactSidebarViewLabel(view, layout.composerLanguage, label),
    };
  });
  const sidebarViewTabLabels = sidebarViewTabs.map(({ label }) => label).join("\u0000");

  useEffect(() => {
    const element = headerSwitcherRef.current;
    if (!element) {
      return;
    }

    const updateDensity = () => {
      const containerWidth = element.getBoundingClientRect().width;
      setHeaderSwitcherDensity(
        resolveHeaderSwitcherDensityForTabs(
          containerWidth,
          sidebarViewTabs.map(({ label }) => label),
        ),
      );
    };

    updateDensity();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateDensity);
      return () => window.removeEventListener("resize", updateDensity);
    }

    const observer = new ResizeObserver(() => updateDensity());
    observer.observe(element);
    return () => observer.disconnect();
  }, [sidebarViewTabLabels, sidebarViewTabs]);

  useEffect(() => {
    setSelectedCommandIndex(0);
  }, [normalizedDraft]);

  useEffect(() => {
    const container = viewContentRef.current;
    if (!container) {
      return;
    }
    container.scrollTop = 0;
  }, [activeView]);

  useEffect(() => {
    if (activeView !== "coach") {
      return;
    }

    const hasCoachThreadContent =
      data.conversation.length > 0 ||
      streaming.isStreaming ||
      Boolean(streaming.streamedContent.trim());
    if (!hasCoachThreadContent) {
      return;
    }

    const container = viewContentRef.current;
    if (!container) {
      return;
    }

    const handle = window.requestAnimationFrame(() => {
      container.scrollTop = container.scrollHeight;
    });

    return () => window.cancelAnimationFrame(handle);
  }, [activeView, data.conversation.length, streaming.isStreaming, streaming.streamedContent]);

  const streamingPlaceholderBody = useMemo(() => {
    if (streaming.agentActivity.length > 0) {
      return layout.composerLanguage === "zh-CN"
        ? "正在整理当前步骤，然后给出第一段可见回复。"
        : "Working through the current step, then writing the first visible reply.";
    }
    return layout.composerLanguage === "zh-CN"
      ? "正在梳理你的问题，然后给出第一段可见回复。"
      : "Thinking through your prompt, then writing the first visible reply.";
  }, [layout.composerLanguage, streaming.agentActivity.length]);
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
  const leftoverTrainingHandoffChromeNotLive = leftoverTrainingHandoffChromeIsNotLive(
    leftoverChromeIdentity,
  );
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
  const leftoverSettingsProfileRhythmNotLive = leftoverSettingsProfileRhythmIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverSettingsLearnerProjectOnboardingNotLive = leftoverSettingsLearnerProjectOnboardingIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverCoachConversationNotLive = leftoverCoachConversationIsNotLive({
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
      runtimeCurrentStep: recoveredDisplayFacts.currentStep,
      planCurrentStep: data.plan.currentStep,
      runtimePlanId: data.memory.workspace?.latestPlanRuntime?.planId,
      planId: data.plan.id,
    }),
    [
      data.memory.workspace?.latestPlanRuntime?.planId,
      data.plan.currentStep,
      data.plan.id,
      recoveredDisplayFacts.currentStep,
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
    if (verifySentence) {
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
  const verifyPlanAdvanceNext = planRuntimeStatus?.verifyPlanAdvance?.next?.trim() || "";
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
      return layout.composerLanguage === "zh-CN"
        ? "带验证结果回 Coach，再推进。"
        : "Return to Coach with the verified result.";
    }
    return layout.composerLanguage === "zh-CN"
      ? `回到 Coach：${returnTarget}`
      : `Return to Coach: ${returnTarget}`;
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
          ? layout.composerLanguage === "zh-CN"
            ? `你现在主要在推进：${data.profile.targetProject}`
            : `You are mainly pushing: ${data.profile.targetProject}`
          : null,
      leftoverSettingsProfileRhythmNotLive
        ? null
        : data.profile.preferredLearningMode
          ? layout.composerLanguage === "zh-CN"
            ? `你更希望我这样带：${data.profile.preferredLearningMode}`
            : `You prefer coaching like this: ${data.profile.preferredLearningMode}`
          : null,
      leftoverSettingsProfileRhythmNotLive
        ? null
        : data.profile.preferredRhythm
          ? layout.composerLanguage === "zh-CN"
            ? `你想保持的节奏：${data.profile.preferredRhythm}`
            : `You want to keep this rhythm: ${data.profile.preferredRhythm}`
          : null,
      leftoverSettingsLearnerProjectOnboardingNotLive
        ? null
        : data.profile.onboardingRequest
          ? layout.composerLanguage === "zh-CN"
            ? `这轮最想推进的是：${data.profile.onboardingRequest}`
            : `This round mainly wants to move: ${data.profile.onboardingRequest}`
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
              label: layout.composerLanguage === "zh-CN" ? "当前聚焦" : "Current focus",
              value: resolvedCoachFocus,
            }
          : null,
        resolvedCoachScenario
          ? {
              id: "scenario",
              label: layout.composerLanguage === "zh-CN" ? "这轮主线" : "Current lane",
              value: coachingScenarioLabel(resolvedCoachScenario, layout.composerLanguage),
            }
          : null,
        liveCoachStage
          ? {
              id: "stage",
              label: layout.composerLanguage === "zh-CN" ? "当前阶段" : "Current stage",
              value: liveCoachStage,
            }
          : null,
        resolvedCoachSignal
          ? {
              id: "signal",
              label: layout.composerLanguage === "zh-CN" ? "学习信号" : "Learner signal",
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
          layout.composerLanguage === "zh-CN" ? "当前主线依据" : "Continuity evidence",
          memoryEvidence.join(" · "),
          layout.composerLanguage,
        ),
        compactCoachLine(
          layout.composerLanguage === "zh-CN" ? "下一轮会怎么续上" : "How the next turn will resume",
          liveCoachTurnChrome.resumeThread,
          layout.composerLanguage,
        ),
        compactCoachLine(
          layout.composerLanguage === "zh-CN" ? "回应方式会偏向" : "Support style",
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
      return layout.composerLanguage === "zh-CN" ? "先认识一下" : "Start by getting oriented";
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
          ? layout.composerLanguage === "zh-CN"
            ? "先了解你的目标、项目和卡点，再决定最适合怎么带你。"
            : "First understand your goal, project, and blocker, then choose the best coaching lane."
          : layout.composerLanguage === "zh-CN"
            ? "先说你的目标、项目或卡点，我会先判断怎么带你更合适。"
            : "Start with your goal, project, or blocker. I’ll decide the best coaching lane first."
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
      setActiveView("plan");
      setPlanComposerMode(mode);
      const modeCopy = resolvePlanComposerCopy(layout.composerLanguage).modes[mode];
      const prompt =
        mode === "blocker" ? modeCopy.secondaryPrompt.prompt : modeCopy.primaryPrompt.prompt;
      setComposerDraft(prompt);
      window.requestAnimationFrame(() => {
        focusComposerInput();
      });
    },
    [layout.composerLanguage, setActiveView],
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
        focusComposerInput();
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
              layout.composerLanguage === "zh-CN"
                ? "预览不能改真实数据，请回 VS Code。请在输入框里核对证据。"
                : "Preview cannot change real data. Use VS Code. Check evidence in the composer.",
          });
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
        });
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
  const recoveredPlanPrimary =
    recoveredRuntime &&
    (planOrientation.primaryAction === "clear_blocker" ||
      planOrientation.primaryAction === "continue_step" ||
      planOrientation.primaryAction === "adopt_evidence" ||
      planOrientation.primaryAction === "wait")
      ? planOrientation.primaryAction
      : null;
  const recoveredAdoptPrimary = recoveredPlanPrimary === "adopt_evidence";
  const autoPlanComposerModeRef = useRef(false);
  useEffect(() => {
    if (activeView !== "plan") {
      autoPlanComposerModeRef.current = false;
      return;
    }
    if (autoPlanComposerModeRef.current) {
      return;
    }
    if (
      planOrientation.primaryAction === "wait" ||
      planOrientation.primaryAction === "adopt_evidence"
    ) {
      setPlanComposerMode("evidence");
      autoPlanComposerModeRef.current = true;
    }
  }, [activeView, planOrientation.primaryAction]);
  const firstLookContinuePrimary = planOrientation.primaryAction === "continue_without_plan";
  const liveResources = leftoverResourceLibraryListNotLive ? [] : data.resources;
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
      resourceCount: liveResources.length,
      selectedResourceId: selectedResource?.id,
      selectedResourceTitle: selectedResource?.title,
      indexState: selectedResource?.indexState,
      resourceStatus: selectedResource?.status,
      trustState: selectedResource?.trustState,
      freshness: selectedResource?.freshness,
      qualityFlags: selectedResource?.qualityFlags,
      searchQuery: data.resourceSearch?.query,
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
    data.workspaceTrainingState?.latestTrainingHandoff,
    data.workspaceTrainingState?.workspaceId,
    layout.composerLanguage,
    resourceConversationContextIds,
  ]);
  const coachConversationSummaryBar = undefined;
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
    ? (trainingState?.reviewArtifact?.status === "resolved" ? "fed_back" : "active")
    : (trainingRestoreForeground
      ? (restoredTrainingCardStatus ?? "active")
      : trainingState?.selectedCardStatus);
  const visibleTrainingCardTitle = liveTrainingNextChallengeTitle({
    ...formalPlanIdentity,
    planTitle: data.plan.title,
    taskTitle: data.task.title,
    cardTitle: pickLanguageAlignedTrainingText(
      layout.composerLanguage,
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
  const trainingScenarioPackLabel = pickLanguageAlignedTrainingText(
    layout.composerLanguage,
    selectedTrainingCardCandidate?.scenarioPack,
    selectedTrainingRouteCard?.scenarioPack,
    trainingState?.latestTrainingHandoff?.scenarioPack,
    trainingState?.latestTrainingNextHop?.scenarioPack,
  );
  const trainingSuggestedWorkspaceAction = pickLanguageAlignedTrainingText(
    layout.composerLanguage,
    selectedTrainingCardCandidate?.suggestedWorkspaceAction,
    selectedTrainingRouteCard?.suggestedWorkspaceAction,
  );
  const trainingScenario = pickLanguageAlignedTrainingText(
    layout.composerLanguage,
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
  const trainingConstraints = pickLanguageAlignedTrainingList(layout.composerLanguage, [
    ...(selectedTrainingCardCandidate?.constraints ?? []),
    ...(selectedTrainingRouteCard?.constraints ?? []),
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
  const trainingStuckRecovery = pickLanguageAlignedTrainingText(
    layout.composerLanguage,
    selectedTrainingCardCandidate?.stuckRecovery,
    selectedTrainingRouteCard?.stuckRecovery,
  );
  const trainingReflectionPrompt = pickLanguageAlignedTrainingText(
    layout.composerLanguage,
    selectedTrainingCardCandidate?.reflectionPrompt,
    selectedTrainingRouteCard?.reflectionPrompt,
  );
  const trainingWhyThisCard = leftoverTrainingHandoffChromeNotLive
    ? undefined
    : pickLanguageAlignedTrainingText(
        layout.composerLanguage,
        trainingState?.activeTrainingCardRouting?.whyThisCard,
        trainingLedgerEntry?.whyThisCard,
      );
  const trainingDeliverable = pickLanguageAlignedTrainingText(
    layout.composerLanguage,
    selectedTrainingCardCandidate?.deliverable,
    selectedTrainingRouteCard?.deliverable,
  );
  const trainingValidationMethod = pickLanguageAlignedTrainingText(
    layout.composerLanguage,
    selectedTrainingCardCandidate?.validationMethod,
    selectedTrainingRouteCard?.validationMethod,
  );
  const trainingVerificationMethod = pickLanguageAlignedTrainingText(
    layout.composerLanguage,
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
    ? pickLanguageAlignedTrainingText(
        layout.composerLanguage,
        runtimeWhyNow,
        recoveredRuntime ? recoveredDisplayFacts.whyNow : undefined,
      )
    : pickLanguageAlignedTrainingText(
        layout.composerLanguage,
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
    : pickLanguageAlignedTrainingText(
        layout.composerLanguage,
        liveTrainingHandoffChrome.returnWith,
        selectedTrainingCardCandidate?.returnWith,
        selectedTrainingRouteCard?.returnWith,
        trainingState?.latestTrainingHandoff?.returnWith,
      );
  const trainingNextAfterCompletionText = leftoverTrainingHandoffChromeNotLive
    ? undefined
    : pickLanguageAlignedTrainingText(
        layout.composerLanguage,
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
    : pickLanguageAlignedTrainingText(
        layout.composerLanguage,
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
    : pickLanguageAlignedTrainingText(
        layout.composerLanguage,
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
    ? pickLanguageAlignedTrainingText(layout.composerLanguage, primaryDueReview.concept) ??
      t.reviewQueue
    : undefined;
  const trainingReviewItems = useMemo<TrainingReviewItem[]>(
    () =>
      authoritativeDueReviews.slice(0, 4).map((item, index) => ({
        id: `training-review-${index}-${item.concept}`,
        title:
          pickLanguageAlignedTrainingText(layout.composerLanguage, item.concept) ??
          t.reviewQueue,
        concept: item.concept,
        focusArea: pickLanguageAlignedTrainingText(layout.composerLanguage, item.focusArea) ?? item.focusArea ?? item.concept,
        taskHint: pickLanguageAlignedTrainingText(layout.composerLanguage, item.taskHint, item.reason) ?? item.reason,
        due: item.dueAt,
        fsrs: { intervalDays: item.intervalDays, masteryScore: item.masteryScore },
        detail: pickLanguageAlignedTrainingText(layout.composerLanguage, item.taskHint, item.reason),
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
          ? trainingState?.reviewArtifact?.verifiedResult
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
    const verifiedResult = pickLanguageAlignedTrainingText(
      layout.composerLanguage,
      trainingState?.latestLearningVerifiedResult,
      trainingState?.reviewArtifact?.verifiedResult,
      trainingState?.scenarioLab?.reviewOutcome,
    );
    if (verifiedResult) {
      return {
        title: trainingExecutionState.pendingPlanConfirmation
          ? layout.composerLanguage === "zh-CN"
            ? "已验证，待计划确认"
            : "Verified, plan confirmation pending"
          : layout.composerLanguage === "zh-CN"
            ? "已验证结果"
            : "Latest verified result",
        detail: verifiedResult,
        meta: trainingStatusMeta,
      };
    }

    const blocker = pickLanguageAlignedTrainingText(
      layout.composerLanguage,
      trainingState?.latestLearningBlocker,
      trainingState?.latestTrainingHandoff?.blockedBy,
      trainingState?.latestTrainingNextHop?.statusReason,
      trainingState?.latestTrainingNextHop?.blockedBy,
      trainingState?.reviewArtifact?.blockedReason,
    );
    if (blocker) {
      return {
        title: layout.composerLanguage === "zh-CN" ? "当前阻塞" : "Current blocker",
        detail: blocker,
        meta: trainingStatusMeta,
      };
    }

    const partialProgress = pickLanguageAlignedTrainingText(
      layout.composerLanguage,
      trainingState?.latestLearningPartialProgress,
      trainingState?.reviewArtifact?.partialProgress,
    );
    if (partialProgress) {
      return {
        title: layout.composerLanguage === "zh-CN" ? "当前进展" : "Partial progress",
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
            pickLanguageAlignedTrainingText(
              layout.composerLanguage,
              liveTrainingHandoffChrome.nextHopTitle,
              liveTrainingHandoffChrome.nextHopCardTitle,
              trainingState.latestTrainingNextHop.title,
              trainingState.latestTrainingNextHop.cardTitle,
            ) ??
            localizeTrainingNextHopLabel(layout.composerLanguage, "target_kind", "next_hop") ??
            localizeTrainingNextHopLabel(layout.composerLanguage, "fallback_title"),
          detail: pickLanguageAlignedTrainingText(
            layout.composerLanguage,
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
            : (trainingState?.latestLearningVerifiedResult ?? trainingState?.reviewArtifact?.verifiedResult),
        latestFollowup:
          leftoverTrainingHandoffChromeNotLive || trainingRestoreReplacesSelectedCard
            ? undefined
            : (liveTrainingHandoffChrome.followup ??
              trainingState?.latestLearningFollowup ??
              trainingState?.latestTrainingNextHop?.nextAfterCompletion),
        reviewSummary: trainingRestoreReplacesSelectedCard
          ? undefined
          : trainingState?.reviewArtifact?.summary,
        reviewBlocker:
          leftoverTrainingHandoffChromeNotLive || trainingRestoreReplacesSelectedCard
            ? undefined
            : (liveTrainingHandoffChrome.blocker ??
              trainingState?.latestLearningBlocker ??
              trainingState?.reviewArtifact?.blockedReason),
        reviewPartialProgress:
          trainingRestoreReplacesSelectedCard
            ? undefined
            : (trainingState?.latestLearningPartialProgress ??
              trainingState?.reviewArtifact?.partialProgress),
        reviewRootCause: trainingRestoreReplacesSelectedCard
          ? undefined
          : trainingState?.reviewArtifact?.rootCause,
        reviewNextRule: trainingRestoreReplacesSelectedCard
          ? undefined
          : trainingState?.reviewArtifact?.nextSelfImplementationRule,
        reviewRecommendedActions: trainingRestoreReplacesSelectedCard
          ? undefined
          : trainingState?.reviewArtifact?.recommendedActions,
        reviewStatus:
          trainingCardVerified
            ? "resolved"
            : trainingCardBlocked || trainingState?.reviewArtifact?.status === "active"
              ? "active"
              : trainingState?.reviewArtifact?.status === "archived"
                ? "archived"
                : undefined,
      }),
    [
      activeTrainingCardId,
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
      selectedTrainingCardCandidate?.returnWith,
      selectedTrainingCardCandidate?.successSignal,
      selectedTrainingCardCandidate?.title,
      selectedTrainingRouteCard?.focusArea,
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
      trainingState?.latestTrainingHandoff?.successSignal,
      trainingState?.latestTrainingNextHop?.nextAfterCompletion,
      trainingState?.reviewArtifact?.blockedReason,
      trainingState?.reviewArtifact?.nextSelfImplementationRule,
      trainingState?.reviewArtifact?.partialProgress,
      trainingState?.reviewArtifact?.recommendedActions,
      trainingState?.reviewArtifact?.rootCause,
      trainingState?.reviewArtifact?.status,
      trainingState?.reviewArtifact?.summary,
      trainingState?.reviewArtifact?.verifiedResult,
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
  const trainingFlashPrompt = pickLanguageAlignedTrainingText(
    layout.composerLanguage,
    selectedTrainingFlashCard?.question,
    flashQuestion?.prompt,
    selectedTrainingFlashCard?.problemStatement,
    selectedTrainingFlashCard?.scenario,
  );
  const trainingTargetSkill = pickLanguageAlignedTrainingText(
    layout.composerLanguage,
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
  const trainingProblemStatement = pickLanguageAlignedTrainingText(
    layout.composerLanguage,
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
        ? trainingState?.scenarioLab?.lastAction ?? trainingState?.scenarioLab?.reviewOutcome
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
      nextHopTitle: nextHopVisible ? trainingState?.latestTrainingNextHop?.title : undefined,
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
  const trainingComposerTalkMode = trainingComposerEnabled && trainingComposerRoute === "coach";
  const trainingComposerUsesAnswerMode = trainingComposerPhase === "answer";
  const handleTrainingComposerRouteChange = useCallback(
    (nextRoute: TrainingComposerRoute) => {
      if (nextRoute === trainingComposerRoute) {
        return;
      }
      trainingRouteDraftsRef.current[trainingComposerRoute] = draft;
      const nextDraft = trainingRouteDraftsRef.current[nextRoute] ?? "";
      setTrainingComposerRoute(nextRoute);
      resetComposerHistoryNavigation();
      setDismissedComposerDeck(undefined);
      setComposerDraft(nextDraft);
    },
    [
      draft,
      resetComposerHistoryNavigation,
      setComposerDraft,
      setDismissedComposerDeck,
      setTrainingComposerRoute,
      trainingComposerRoute,
    ],
  );
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
      setActiveView("coach");
      setComposerDraft(composeTrainingCoachBridgeDraft(trainingCoachBridge));
      window.requestAnimationFrame(() => {
        focusComposerInput();
      });
      return;
    }

    setComposerDraft("");
  }, [
    normalizedTrainingNextHopStatus,
    setActiveView,
    setComposerDraft,
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
            title:
              layout.composerLanguage === "zh-CN"
                ? settingsActionState.kind === "reset-defaults"
                  ? "恢复中"
                  : "保存中"
                : settingsActionState.kind === "reset-defaults"
                  ? "Restoring"
                  : "Saving",
            detail:
              layout.composerLanguage === "zh-CN"
                ? "正在同步语言、回复方式、教学风格和教练默认策略。"
                : "Syncing language, answer style, teaching style, and the coach default strategy.",
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
        layout.composerLanguage === "zh-CN"
          ? "这里会一起保存语言、反馈方式、教学风格和教练默认策略。"
          : "This save writes language, answer mode, teaching style, and the coach default strategy together.",
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
            title:
              layout.composerLanguage === "zh-CN"
                ? settingsActionState.kind === "reset-defaults"
                  ? "恢复中"
                  : "保存中"
                : settingsActionState.kind === "reset-defaults"
                  ? "Restoring"
                  : "Saving",
            detail:
              layout.composerLanguage === "zh-CN"
                ? "正在写入这组工作区上下文控制。"
                : "Writing these workspace context controls.",
          }
        : undefined) ??
      settingsFeedbackState.workspaceControl;

    return {
      saveState: workspaceSettings ? (isSaved ? "saved" : "unsaved") : "empty",
      effectiveValue,
      savedValue: savedValue ?? (layout.composerLanguage === "zh-CN" ? "工作区未单独覆盖" : "No workspace override"),
      editingValue: isSaved ? undefined : effectiveValue,
      note:
        layout.composerLanguage === "zh-CN"
          ? "这些开关现在就会影响发送，但保存后工作区重开仍会保持。"
          : "These switches affect sends immediately, but only persist across reopen after save.",
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
    }),
    [
      activeView,
      data.liveContext.activeFile,
      data.liveContext.selectionRange,
      data.liveContext.relatedFiles.length,
      data.resources.length,
    ],
  );
  const matchingLocalSkills = useMemo<LocalSkillSuggestion[]>(() => {
    if (!normalizedDraft.startsWith("$")) {
      return [];
    }

    return filterTrainerSkills(normalizedDraft, trainerSkillContext, 10);
  }, [
    normalizedDraft,
    trainerSkillContext,
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
      ".command-deck__item.is-active, .skill-deck__item.is-active",
    );
    activeItem?.scrollIntoView({ block: "nearest" });
  }, [dismissedComposerDeck, normalizedDraft, selectedCommandIndex]);

  const visibleWarnings = useMemo(
    () => sendAnalysis.warnings.filter((warning) => warning.id !== "diagnostics-enabled-without-signals"),
    [sendAnalysis.warnings],
  );
  const sendBlocked =
    workspaceSessionBlocked || !providerCanCoachNow || Boolean(providerBlockReason);
  const capabilitySendBlocked = !capabilityVerdict.chat;
  const handleGenerateTrainingCard = useCallback(
    (focusArea?: string) => {
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

      requestTrainingCardGeneration(focusArea);
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
      (layout.composerLanguage === "zh-CN"
        ? "当前连接还不能验证图片。"
        : "This connection cannot verify images yet.")
    : undefined;
  const showComposerProviderPill = false;
  const showComposerProviderNote =
    !composerUsesTrainingFlow &&
    !sendBlocked &&
    Boolean(
      providerSendState.status === "degraded_error" || providerSendState.status === "refreshing"
        ? providerSendState.warning
        : undefined,
    );
  const hasFullCoachRecoverySurface = activeView === "coach" && shouldShowNeutralEmptyState;
  const hasCoachWorkspaceAdmissionSurface = activeView === "coach" && workspaceSessionBlocked;
  const suppressComposerRecoverySurface =
    activeView === "coach" &&
    !streaming.isStreaming &&
    (Boolean(streaming.streamError?.trim()) ||
      /interrupted|aborted|failed|timeout|network|error/.test(
        streaming.completionStopReason?.trim().toLowerCase() ?? "",
      ));
  const showComposerBlockingNotice =
    sendBlocked &&
    !suppressComposerRecoverySurface &&
    !hasFullCoachRecoverySurface &&
    !hasCoachWorkspaceAdmissionSurface;
  const showComposerPresenceBar =
    !suppressComposerRecoverySurface &&
    (
      (!hasCoachWorkspaceAdmissionSurface && workspaceSessionBlocked) ||
      showComposerBlockingNotice ||
      showComposerProviderPill ||
      showComposerProviderNote
    );

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
          layout.composerLanguage === "zh-CN"
            ? "资源上下文最多带入 12 份，已使用前 12 份。"
            : "A Resources turn can use up to 12 items; the first 12 are attached.",
      });
    }
    const resolvedIncludeCurrentFile =
      includeCurrentFile ??
      (layout.includeCurrentFile && shouldAttachCurrentFile(text, intent));
    const effectiveStream = resolvedFormalPlanMutation ? false : stream;
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
            layout.composerLanguage === "zh-CN"
              ? "没有找到可导入的支持文件。"
              : "No supported files were found to import.",
        });
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
      const skippedTextZh =
        unsupportedCount > 0 ? `跳过 ${unsupportedCount} 个不支持的文件。` : "";
      const skippedTextEn =
        unsupportedCount > 0
          ? ` Skipped ${unsupportedCount} unsupported file${unsupportedCount === 1 ? "" : "s"}.`
          : "";
      const truncationTextZh = finalTruncated ? `仅导入前 ${limitedCount} 个支持文件。` : "";
      const truncationTextEn = finalTruncated
        ? ` Imported only the first ${limitedCount} supported file${limitedCount === 1 ? "" : "s"}.`
        : "";
      const indexingTextZh =
        failedIndexCount > 0
          ? `其中 ${indexedCount} 个已完成索引，${failedIndexCount} 个上传成功但索引未完成。`
          : `已完成 ${indexedCount} 个文件的索引并刷新资料状态。`;
      const indexingTextEn =
        failedIndexCount > 0
          ? ` Indexed ${indexedCount}, while ${failedIndexCount} uploaded resource${failedIndexCount === 1 ? "" : "s"} did not finish indexing.`
          : ` Indexed ${indexedCount} resource${indexedCount === 1 ? "" : "s"} and refreshed resource status.`;
      const uploadFailureTextZh =
        failedUploadCount > 0
          ? `其中 ${failedUploadCount} 个没有导入成功，其他资料已经可以使用。`
          : "";
      const uploadFailureTextEn =
        failedUploadCount > 0
          ? ` ${failedUploadCount} file${failedUploadCount === 1 ? "" : "s"} could not be imported; the others are ready to use.`
          : "";
      const importedLeadZh = importingFolder ? "已导入文件夹中的资料。" : "已导入资料。";
      const importedLeadEn = importingFolder ? "Imported resources from the folder." : "Imported resources.";
      setOperationMessage({
        tone: failedUploadCount > 0 || failedIndexCount > 0 ? "info" : "success",
        message:
          layout.composerLanguage === "zh-CN"
            ? `${importedLeadZh}${uploadedCount > 0 ? ` 共上传 ${uploadedCount} 个支持文件。` : ""}${truncationTextZh ? ` ${truncationTextZh}` : ""}${skippedTextZh ? ` ${skippedTextZh}` : ""}${uploadFailureTextZh ? ` ${uploadFailureTextZh}` : ""} ${indexingTextZh}`.trim()
            : `${importedLeadEn}${uploadedCount > 0 ? ` Uploaded ${uploadedCount} supported file${uploadedCount === 1 ? "" : "s"}.` : ""}${truncationTextEn}${skippedTextEn}${uploadFailureTextEn}${indexingTextEn}`.trim(),
      });
    } catch {
      setOperationMessage({
        tone: "error",
        message: recoverableFailureMessage("upload", layout.composerLanguage),
      });
    }
  };

  const handleBrowserUrlImport = async () => {
    if (!isBrowserPreview || browserPreviewFixture) {
      return;
    }

    const rawSource = window.prompt(
      layout.composerLanguage === "zh-CN"
        ? "\u7c98\u8d34\u8981\u5bfc\u5165\u7684\u7f51\u9875 URL"
        : "Paste the webpage URL to import",
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
          layout.composerLanguage === "zh-CN"
            ? "\u8bf7\u8f93\u5165\u6709\u6548\u7684 http \u6216 https URL\u3002"
            : "Enter a valid http or https URL.",
      });
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
          layout.composerLanguage === "zh-CN"
            ? result.failedIndexCount > 0 || result.failedUploadCount > 0
              ? `\u7f51\u9875\u5df2\u5bfc\u5165\uff0c\u4f46\u7d22\u5f15\u672a\u5b8c\u5168\u5b8c\u6210\u3002\u5df2\u4e0a\u4f20 ${result.uploadedCount} \u9879\u3002`
              : "\u7f51\u9875\u5df2\u5bfc\u5165\u5e76\u5b8c\u6210\u7d22\u5f15\u3002"
            : result.failedIndexCount > 0 || result.failedUploadCount > 0
              ? `Webpage imported, but indexing did not finish for every resource. Uploaded ${result.uploadedCount}.`
              : "Webpage imported and indexed.",
      });
    } catch {
      setOperationMessage({
        tone: "error",
        message: recoverableFailureMessage("upload", layout.composerLanguage),
      });
    }
  };

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
                payload.responseLanguage === "zh-CN"
                  ? "已保存教练默认设置。"
                  : "Coach defaults saved.",
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

  const handleSuggestedAction = (
    action: SuggestedAction["action"],
    options?: Pick<SuggestedAction, "prompt" | "focusArea">,
  ) => {
    const prompt = options?.prompt;
    const focusArea = options?.focusArea;
    const reviewOnlyDraft =
      prompt ??
      (layout.composerLanguage === "zh-CN"
        ? "先继续当前复习项，不要新开正式任务。"
        : "Stay with the current review item. Do not start a new live task.");
    if (action === "hint") {
      setActiveView("coach");
      setComposerDraft(
        prompt ??
          (layout.composerLanguage === "zh-CN"
            ? "请继续给我一个更小、更具体的下一步。"
            : "Give me a smaller, more specific next step."),
      );
      return;
    }

    if (action === "plan") {
      setActiveView("plan");
      setComposerDraft(
        prompt ??
          (layout.composerLanguage === "zh-CN"
            ? "请先和我讨论这条计划的阶段、证据和验证方式；在我明确生成前不要改正式计划。"
            : "Discuss this plan's stages, evidence, and verification with me first. Do not change the formal plan until I explicitly generate it."),
      );
      return;
    }

    if (action === "next_task") {
      setActiveView("coach");
      if (leftoverSuggestedActionNotLive) {
        setComposerDraft(reviewOnlyDraft);
        return;
      }
      sendTurn({
        text: prompt ?? defaultPromptText("next_task", layout.composerLanguage, focusArea),
        intent: "next_task",
        activeView: "coach",
      });
      return;
    }

    if (action === "review" || action === "retry_review") {
      setActiveView("coach");
      sendTurn({
        text: prompt ?? defaultPromptText("review", layout.composerLanguage, focusArea),
        intent: "review",
        activeView: "coach",
        includeCurrentFile: true,
        includeDiagnostics: true,
        contextDetail: "full",
      });
      return;
    }

    setActiveView("coach");
    if (leftoverSuggestedActionNotLive) {
      setComposerDraft(reviewOnlyDraft);
      return;
    }
    sendTurn({
      text: prompt ?? defaultPromptText("task", layout.composerLanguage, focusArea),
      intent: "task",
      activeView: "coach",
    });
  };

  const handleSubmit = async () => {
    const hasImageAttachments = composerAttachments.length > 0;
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

    const localCommandDefinition = hasImageAttachments
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
      submittedSkillTrigger.startsWith("$")
        ? trainerSkillCatalog.find((skill) =>
            skill.trigger.toLowerCase() === submittedSkillTrigger.toLowerCase() &&
            (!skill.when || skill.when(trainerSkillContext)),
          )
        : undefined;

    if (submittedSkill) {
      const targetView = skillSectionTargetView(submittedSkill.section);
      const followupText = normalizedDraft.slice(submittedSkillTrigger.length).trim();
      const skillPrompt =
        localizeKnownCoachUiText(
          resolveTrainerSkillText(submittedSkill.prompt, layout.composerLanguage) ||
            resolveTrainerSkillText(submittedSkill.detail, layout.composerLanguage) ||
            resolveTrainerSkillText(submittedSkill.title, layout.composerLanguage),
          layout.composerLanguage,
        ) ??
        resolveTrainerSkillText(submittedSkill.detail, layout.composerLanguage) ??
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
        setComposerDraft("");
        setComposerAttachments([]);
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
              (layout.composerLanguage === "zh-CN"
                ? "当前连接还不能验证图片。"
                : "This connection cannot verify images yet."),
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
          attachments: composerAttachments,
        });
        setComposerDraft("");
        setComposerAttachments([]);
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
        setComposerDraft("");
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
          question: trainingComposerSelectedVerifyItem ?? trainingProblemStatement,
          learnerAnswer: normalizedDraft,
          evidenceItems: authoritativeVerifyItems,
        });
        setComposerDraft("");
      }
      return;
    }

    const waitingComposerEvidence =
      activeView === "plan" &&
      resolvedPlanComposerMode === "evidence" &&
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

    const analyzedIntent =
      sendAnalysis.intent === "coach" ||
      sendAnalysis.intent === "next_task" ||
      sendAnalysis.intent === "review" ||
      sendAnalysis.intent === "plan" ||
      sendAnalysis.intent === "task"
        ? sendAnalysis.intent
        : "coach";
    const planComposerSubmission = activeView === "plan";
    const formalPlanGeneration =
      planComposerSubmission && resolvedPlanComposerMode === "generate";
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
    const messageText =
      sendAnalysis.draftBody ||
      (hasImageAttachments
        ? buildGenericImageReviewPrompt(layout.composerLanguage, normalizedDraft)
        : defaultPromptText(intent, layout.composerLanguage));

    sendTurn({
      text: messageText,
      intent,
      goals: formalPlanGeneration ? data.profile.goals : undefined,
      activeView,
      stream: true,
      formalPlanMutation: formalPlanGeneration && !previewPlanCandidateGeneration,
      planComposerMode: planComposerSubmission ? resolvedPlanComposerMode : undefined,
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
    setComposerDraft("");
    setComposerAttachments([]);
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
    bootstrapRequestSent = false;
  }, [hasReceivedHostState]);

  useEffect(() => {
    if (!showComposerShell) {
      return;
    }
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
          layout.composerLanguage === "zh-CN"
            ? "先保存连接，再更新模型列表。"
            : "Save the connection before updating the model list.",
      });
      return;
    }

    if (!data.providerConfig.apiKeyConfigured) {
      setOperationMessage({
        tone: "info",
        message:
          layout.composerLanguage === "zh-CN"
            ? "先填写访问密钥，再更新模型列表。"
            : "Add an API key before updating the model list.",
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

  const primeSettingsProviderModels = useCallback(() => {
    if (!data.providerConfig.configured || !data.providerConfig.apiKeyConfigured) {
      return;
    }

    if (isBrowserPreview) {
      void loadBrowserPreviewModule()
        .then((browserPreview) =>
          browserPreview.refreshBrowserPreviewProviderModels(previewSessionId),
        )
        .then(({ sessionId, messages }) => {
          setPreviewSessionId(sessionId);
          applyPreviewHostMessages(
            messages.filter((message) => message.type !== "operation/status"),
            true,
          );
        })
        .catch(() => undefined);
      return;
    }

    postMessage({
      type: "settings/primeProviderModels",
    });
  }, [
    applyPreviewHostMessages,
    data.providerConfig.apiKeyConfigured,
    data.providerConfig.configured,
    isBrowserPreview,
    previewSessionId,
  ]);

  useEffect(() => {
    if (openMenu !== "model") {
      composerModelAutoRefreshKeyRef.current = "";
      return;
    }

    if (
      !data.providerConfig.configured ||
      !data.providerConfig.apiKeyConfigured ||
      data.providerConfig.modelListStatus === "loading"
    ) {
      return;
    }

    const availableModelCount = Array.isArray(data.providerConfig.availableModels)
      ? data.providerConfig.availableModels.filter((entry) => entry.trim().length > 0).length
      : 0;
    const cacheExpiryMs = data.providerConfig.cacheExpiresAt
      ? Date.parse(data.providerConfig.cacheExpiresAt)
      : Number.NaN;
    const cacheExpired = Number.isFinite(cacheExpiryMs) && cacheExpiryMs <= Date.now();
    const needsRefresh =
      availableModelCount === 0 ||
      data.providerConfig.modelListStatus === "idle" ||
      cacheExpired;
    if (!needsRefresh) {
      return;
    }

    const refreshKey = [
      data.providerConfig.name.trim().toLowerCase(),
      data.providerConfig.baseUrl.trim().toLowerCase(),
      normalizeProviderProtocol(data.providerConfig.protocol),
      data.providerConfig.model.trim().toLowerCase(),
      data.providerConfig.cacheFetchedAt ?? "",
      data.providerConfig.cacheExpiresAt ?? "",
      data.providerConfig.modelListStatus,
      availableModelCount,
      cacheExpired ? "expired" : "fresh",
    ].join("::");
    if (composerModelAutoRefreshKeyRef.current === refreshKey) {
      return;
    }

    composerModelAutoRefreshKeyRef.current = refreshKey;
    refreshComposerProviderModels();
  }, [
    data.providerConfig.apiKeyConfigured,
    data.providerConfig.availableModels,
    data.providerConfig.baseUrl,
    data.providerConfig.cacheExpiresAt,
    data.providerConfig.cacheFetchedAt,
    data.providerConfig.configured,
    data.providerConfig.model,
    data.providerConfig.modelListStatus,
    data.providerConfig.name,
    data.providerConfig.protocol,
    openMenu,
    refreshComposerProviderModels,
  ]);

  useEffect(() => {
    if (activeView !== "settings") {
      settingsModelAutoPrimeKeyRef.current = "";
      return;
    }

    if (
      !data.providerConfig.configured ||
      !data.providerConfig.apiKeyConfigured ||
      providerDraftHasChanges ||
      data.providerConfig.modelListStatus === "loading"
    ) {
      return;
    }

    const availableModelCount = Array.isArray(data.providerConfig.availableModels)
      ? data.providerConfig.availableModels.filter((entry) => entry.trim().length > 0).length
      : 0;
    const cacheExpiryMs = data.providerConfig.cacheExpiresAt
      ? Date.parse(data.providerConfig.cacheExpiresAt)
      : Number.NaN;
    const cacheExpired = Number.isFinite(cacheExpiryMs) && cacheExpiryMs <= Date.now();
    const shouldRetryAfterError =
      data.providerConfig.modelListStatus === "error" &&
      data.providerConfig.modelRetryable !== false;
    const needsPrime =
      availableModelCount === 0 ||
      data.providerConfig.modelListStatus === "idle" ||
      cacheExpired ||
      shouldRetryAfterError;
    if (!needsPrime) {
      return;
    }

    const primeKey = [
      data.providerConfig.name.trim().toLowerCase(),
      data.providerConfig.baseUrl.trim().toLowerCase(),
      normalizeProviderProtocol(data.providerConfig.protocol),
      data.providerConfig.model.trim().toLowerCase(),
      data.providerConfig.modelListStatus,
      data.providerConfig.cacheFetchedAt ?? "",
      data.providerConfig.cacheExpiresAt ?? "",
      availableModelCount,
      cacheExpired ? "expired" : "fresh",
      shouldRetryAfterError ? "retryable-error" : "steady",
    ].join("::");
    if (settingsModelAutoPrimeKeyRef.current === primeKey) {
      return;
    }

    settingsModelAutoPrimeKeyRef.current = primeKey;
    primeSettingsProviderModels();
  }, [
    activeView,
    data.providerConfig.apiKeyConfigured,
    data.providerConfig.availableModels,
    data.providerConfig.baseUrl,
    data.providerConfig.cacheExpiresAt,
    data.providerConfig.cacheFetchedAt,
    data.providerConfig.configured,
    data.providerConfig.model,
    data.providerConfig.modelListStatus,
    data.providerConfig.modelRetryable,
    data.providerConfig.name,
    data.providerConfig.protocol,
    primeSettingsProviderModels,
    providerDraftHasChanges,
  ]);

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
          (layout.composerLanguage === "zh-CN"
            ? "\u8bf7\u5148\u9009\u62e9\u4e00\u4e2a\u53ef\u4ee5\u4f7f\u7528\u7684\u6a21\u578b\u3002"
            : "Choose a model that this connection can use."),
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

  const handleVerifyTrainingFromIde = useCallback(() => {
    if (isBrowserPreview || leftoverTrainingHandoffChromeNotLive || !activeTrainingCardId) {
      const notice =
        layout.composerLanguage === "zh-CN"
          ? leftoverTrainingHandoffChromeNotLive
            ? "验证未通过：当前训练卡片不是实时状态。"
            : !activeTrainingCardId
              ? "没有可验证的当前文件。"
              : "预览不能验真实工作区文件。请回 VS Code 打开文件后再验证。"
          : leftoverTrainingHandoffChromeNotLive
            ? "Verification failed: this training card is not live."
            : !activeTrainingCardId
              ? "There is no current file to verify."
              : "Preview cannot verify a real workspace file. Open the file in VS Code, then verify there.";
      setTrainingVerifyNotice(notice);
      setOperationMessageSurface("training");
      return;
    }
    postMessage({
      type: "command/execute",
      payload: {
        commandId: trainerCommands.evaluateCurrentFile,
        payload: {
          source: "training",
          cardId: activeTrainingCardId,
          cardTitle: visibleTrainingCardTitle,
          taskSpecId: data.task.id,
          acceptanceCriteria: authoritativeVerifyItems,
          learnerDeliverables: trainingDeliverables,
          expectedSymbols: trainingCardType === "practice" ? practiceExpectedSymbols : [],
          filesToTouch: trainingFilesToTouch,
        },
      },
    });
  }, [
    leftoverTrainingHandoffChromeNotLive,
    activeTrainingCardId,
    authoritativeVerifyItems,
    data.task.id,
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
      window.requestAnimationFrame(() => {
        focusComposerInput();
      });
      return;
    }
    if (reviewArtifactForeground && trainingState?.reviewArtifact?.status === "resolved") {
      const title = trainingState.reviewArtifact.title ?? trainingState.reviewArtifact.focusArea ?? "review";
      const result = trainingState.reviewArtifact.verifiedResult ?? trainingState.reviewArtifact.summary ?? "";
      setActiveView("coach");
      setComposerDraft(
        layout.composerLanguage === "zh-CN"
          ? `\u6211\u5b8c\u6210\u4e86\u201c${title}\u201d\u7684\u56de\u987e\u3002\u7ed3\u8bba\uff1a${result}\n\n\u8bf7\u5e2e\u6211\u5b89\u6392\u4e0b\u4e00\u6b65\u3002`
          : `I finished reviewing "${title}". Result: ${result}\n\nPlease help me choose the next step.`,
      );
      window.requestAnimationFrame(() => {
        focusComposerInput();
      });
      return;
    }

    if (trainingHandoffReflectionRequired) {
      setTrainingComposerRoute("card");
      setComposerDraft("");
      window.requestAnimationFrame(() => {
        focusComposerInput();
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
    window.requestAnimationFrame(() => {
      focusComposerInput();
    });
  }, [
    handleSubmitTrainingEvidence,
    layout.composerLanguage,
    leftoverTrainingHandoffChromeNotLive,
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
  const resolvedPlanComposerMode: PlanComposerMode = !planHasFormalThread
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
          aria-label={layout.composerLanguage === "zh-CN" ? "训练选项" : "Training choices"}
        >
          <div className="composer-context-strip__chips composer-context-strip__chips--training-choice">
            {normalizedTrainingFlashChoices.slice(0, 4).map((choice, index) => {
              const isActive = normalizeInlineComparisonText(choice) === normalizeInlineComparisonText(draft);
              return (
                <button
                  key={`${choice}:${index}`}
                  className={`composer-context-chip ${isActive ? "is-active" : "is-enabled"}`.trim()}
                  type="button"
                  aria-pressed={isActive}
                  onClick={() => {
                    setComposerDraft(choice);
                    window.requestAnimationFrame(() => {
                      focusComposerInput();
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
    const resultLabel = layout.composerLanguage === "zh-CN" ? "\u8bb0\u5f55\u7ed3\u679c" : "Record result";
    const blockerLabel = layout.composerLanguage === "zh-CN" ? "\u8bb0\u5f55\u53d7\u963b" : "Record blocker";

    return (
      <section
        className="composer-training-panel"
        aria-label={layout.composerLanguage === "zh-CN" ? "\u8bad\u7ec3\u4f5c\u7b54\u65b9\u5f0f" : "Training response mode"}
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
                focusComposerInput();
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
                focusComposerInput();
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

  useEffect(() => {
    if (!streaming.isStreaming && streaming.completionStopReason !== "cancelled") {
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
                ? layout.composerLanguage === "zh-CN"
                  ? `这次会附带 ${data.resources.length} 份资料`
                  : `${data.resources.length} attached resource${data.resources.length === 1 ? "" : "s"}`
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
                  <UploadIcon size={13} />
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
                  <FolderIcon size={13} />
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
                    <LinkIcon size={13} />
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
                {layout.composerLanguage === "zh-CN"
                  ? "这些资料会和当前消息一起发给教练参考。"
                  : "These resources will be sent with the current turn for grounding."}
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
                  {layout.composerLanguage === "zh-CN"
                    ? `另外还有 ${data.resources.length - 6} 份资料会一起带上。`
                    : `${data.resources.length - 6} more resources will also be included.`}
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
        layout.composerLanguage === "zh-CN" ? "搜索模型或已保存连接" : "Search models or saved connections";
      const emptyStateLabel = hasModelQuery
        ? layout.composerLanguage === "zh-CN"
          ? "没有匹配的模型或已保存连接。"
          : "No matching models or saved connections."
        : hasOnlyCurrentModel
          ? composerProviderCopy.modelPicker.onlyCurrentModel
          : composerHasSavedProfiles
            ? layout.composerLanguage === "zh-CN"
              ? "可从下方展开已保存连接。"
              : "Saved connections are available below."
            : layout.composerLanguage === "zh-CN"
              ? "还没有可切换的模型。请到“设置”保存连接。"
              : "There are no models to switch yet. Save a connection in Settings first.";

      const visibleSelectionCount = displayedModels.length + (hasModelQuery ? visibleProfiles.length : 0);
      const showSearch = nonActiveModelCount > COMPOSER_MODEL_PICKER_INITIAL_OPTION_LIMIT;
      const modelSectionLabel =
        hasModelQuery
          ? layout.composerLanguage === "zh-CN"
            ? "匹配的模型"
            : "Matching models"
          : layout.composerLanguage === "zh-CN"
            ? "可切换模型"
            : "Available models";
      const profileSectionLabel =
        layout.composerLanguage === "zh-CN" ? "已保存连接" : "Saved connections";
      const refreshModelsDisabled =
        !providerApplied ||
        !data.providerConfig.apiKeyConfigured ||
        data.providerConfig.modelListStatus === "loading";
      const refreshModelsLabel =
        layout.composerLanguage === "zh-CN" ? "刷新模型" : "Refresh models";
      const refreshModelsTitle = !providerApplied
        ? layout.composerLanguage === "zh-CN"
          ? "先保存连接，再更新模型列表"
          : "Save the connection before updating the model list"
        : !data.providerConfig.apiKeyConfigured
          ? layout.composerLanguage === "zh-CN"
            ? "先在“设置”填写访问密钥，再更新模型列表"
            : "Add an API key in Settings before updating the model list"
          : data.providerConfig.modelListStatus === "loading"
            ? layout.composerLanguage === "zh-CN"
              ? "正在更新模型列表"
              : "Updating the model list"
            : layout.composerLanguage === "zh-CN"
              ? "更新模型列表"
              : "Update the model list";

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
                          return (
                            <button
                              key={profile.id}
                              className={`composer-provider-list__item ${profile.isActive ? "is-active" : ""}`}
                              type="button"
                              disabled={modelDisabled}
                              aria-current={profile.isActive ? "true" : undefined}
                              title={policyHint ?? profile.model}
                              onClick={() => switchComposerProviderModel(profile.model)}
                            >
                              <div className="composer-provider-list__row">
                                <span className="composer-provider-list__stack">
                                  <span className="composer-provider-list__model">{profile.model}</span>
                                  {policyHint ? (
                                    <span className="composer-provider-list__label">{policyHint}</span>
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
                        aria-label={layout.composerLanguage === "zh-CN" ? "已保存连接" : "Saved connections"}
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
                aria-label={layout.composerLanguage === "zh-CN" ? "已保存连接" : "Saved connections"}
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
          <strong>{sendContextShortSummary(data, layout, t)}</strong>
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
            {layout.composerLanguage === "zh-CN"
              ? "Enter 执行，Tab 补全。"
              : "Enter runs it. Tab completes it."}
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
    setComposerDraft(`${skill.trigger} `);
    setDismissedComposerDeck("skill");
    setOpenMenu(undefined);
    setSelectedCommandIndex(0);
    window.requestAnimationFrame(() => {
      focusComposerInput();
    });
  };

  const renderSkillDeck = () => {
    if (
      dismissedComposerDeck === "skill" ||
      !normalizedDraft.startsWith("$") ||
      matchingLocalSkills.length === 0
    ) {
      return null;
    }

    return (
      <div ref={composerDeckRef} className="skill-deck" role="list" aria-label={layout.composerLanguage === "zh-CN" ? "技能" : "Skills"}>
        <div className="skill-deck__header">
          <strong>{layout.composerLanguage === "zh-CN" ? "技能" : "Skills"}</strong>
          <span className="skill-deck__hint">
            {layout.composerLanguage === "zh-CN"
              ? "继续输入可收窄范围，删除 $ 就会按普通消息发送。"
              : "Keep typing to narrow it down, or remove $ to send a normal message."}
          </span>
        </div>
        {matchingLocalSkills.length === 0 ? (
          <p className="skill-deck__empty">
            {layout.composerLanguage === "zh-CN"
              ? "没有匹配到 skill。继续输入，或者直接当作普通消息发送。"
              : "No matching skill was found. Keep typing, or send this as a normal message."}
          </p>
        ) : (
          <div className="skill-deck__list">
            {matchingLocalSkills.map((skill) => (
              <button
              key={skill.id}
              className={`skill-deck__item ${
                matchingLocalSkills[selectedCommandIndex]?.id === skill.id ? "is-active" : ""
              }`}
              type="button"
              aria-label={`${skill.trigger}: ${resolveTrainerSkillText(skill.title, layout.composerLanguage)}`}
              title={[
                skill.trigger,
                resolveTrainerSkillText(skill.title, layout.composerLanguage),
                resolveTrainerSkillText(skill.detail, layout.composerLanguage),
                trainerSkillSectionLabel(skill.section, layout.composerLanguage),
              ]
                .filter(Boolean)
                .join(" · ")}
                onMouseEnter={() => {
                  const index = matchingLocalSkills.findIndex((item) => item.id === skill.id);
                  if (index >= 0) {
                    setSelectedCommandIndex(index);
                  }
                }}
                onClick={() => selectSkillSuggestion(skill)}
              >
                <span className="skill-deck__trigger">{skill.trigger}</span>
                <span className="skill-deck__body">
                  <strong>{resolveTrainerSkillText(skill.title, layout.composerLanguage)}</strong>
                  <span>{resolveTrainerSkillText(skill.detail, layout.composerLanguage)}</span>
                </span>
                <span className="skill-deck__section">
                  {trainerSkillSectionLabel(skill.section, layout.composerLanguage)}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    );
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
                {layout.composerLanguage === "zh-CN" ? `接着做：${item.label}` : `Continue: ${item.label}`}
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
  const runWorkspaceAdmissionCommand = (commandId: string, payload?: unknown) => {
    postMessage({
      type: "command/execute",
      payload: payload === undefined ? { commandId } : { commandId, payload },
    });
  };
  const workspaceAdmissionContent = trainerWorkspaceAdmission ? (
    <>
      <WorkspaceAdmissionPanel
        status={trainerWorkspaceAdmission.status}
        projectName={trainerWorkspaceAdmission.projectName}
        projectPath={trainerWorkspaceAdmission.projectPath}
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
      return (
        <div className="coach-empty-state coach-empty-state--blocked">
          <p>
            {layout.composerLanguage === "zh-CN"
              ? "这组连接暂时不能用。"
              : "This connection cannot be used right now."}
          </p>
          <button className="button button--accent" type="button" onClick={() => openProviderSetup()}>
            {layout.composerLanguage === "zh-CN" ? "检查连接" : providerSetupAction.primary.label}
          </button>
        </div>
      );
    }
    if (isFirstCoachConversation && providerCanCoachNow && displayConnectionState === "connected") {
      return (
        <div className="coach-empty-state coach-empty-state--welcome">
          <p>
            {layout.composerLanguage === "zh-CN"
              ? "先在下面说你现在卡在哪。"
              : "Say where you are stuck below."}
          </p>
        </div>
      );
    }
    return null;
  };

  const handleCoachArtifactOpen = (artifact: CoachArtifactBlockData) => {
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

  const coachCheckpointRecovery =
    leftoverStreamingCheckpointNotLive ? false : isCoachCheckpointRecoveryState(streaming);
  const coachCheckpointRecoveryCopy = layout.composerLanguage === "zh-CN"
    ? {
        title: "本轮已中断，可从已保存进度继续",
        resume: "恢复最近进度",
        replay: "查看本轮记录",
        hint: "恢复 checkpoint 不会重新发送当前草稿；查看记录不会改变当前对话。",
      }
    : {
        title: "This turn was interrupted. Continue from saved progress.",
        resume: "Resume latest progress",
        replay: "View this turn's record",
        hint: "Resuming the checkpoint does not resend your draft; viewing the record does not change this conversation.",
      };
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
      messages={localizedConversation}
      className={className}
      surfaceTone="quiet"
      eyebrow={undefined}
      title={undefined}
      subtitle={undefined}
      summaryBar={coachConversationSummaryBar}
      openArtifactLabel={layout.composerLanguage === "zh-CN" ? "\u5c55\u5f00" : "Open"}
      userLabel={t.you}
      assistantLabel={t.trainer}
      systemLabel={layout.composerLanguage === "zh-CN" ? "\u7cfb\u7edf" : "System"}
      language={layout.composerLanguage}
      emptyState={embedded || workspaceSessionBlocked ? null : coachSuperEntryContent(false)}
      footer={embedded ? undefined : coachCheckpointRecoveryActions}
      streamingMessage={
        streaming.isStreaming
          ? {
              body: streaming.streamedContent || streamingPlaceholderBody,
              author: t.trainer,
              timestamp: t.streaming,
              role: "assistant",
              roleLabel: t.trainer,
            }
          : null
      }
      agentActivity={streaming.agentActivity}
      agentStep={streaming.agentStep}
      onArtifactOpen={handleCoachArtifactOpen}
    />
  );

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
        : pickLanguageAlignedTrainingText(
          layout.composerLanguage,
          trainingState?.latestLearningBlocker,
          trainingState?.latestTrainingHandoff?.blockedBy,
          trainingState?.reviewArtifact?.blockedReason,
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
        : pickLanguageAlignedTrainingText(
          layout.composerLanguage,
          trainingState?.latestLearningVerifiedResult,
          trainingState?.reviewArtifact?.verifiedResult,
          trainingState?.latestLearningPartialProgress,
          trainingState?.reviewArtifact?.partialProgress,
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
    const liveValue = streaming.isStreaming
      ? truncateInlineText(streaming.streamedContent || streamingPlaceholderBody, textLimit)
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
            window.requestAnimationFrame(() => {
              focusComposerInput();
            });
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
          body: streaming.streamedContent || streamingPlaceholderBody,
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
      ? isZh
        ? "正在回复"
        : "Replying"
      : truncateInlineText(visibleReply.body, isZh ? 26 : 52) ??
        (isZh ? "查看回复" : "View reply");

    return (
      <details
        className={`view-agent-reply view-agent-reply--${view}`}
        data-view-agent-reply={view}
        open={isStreamingForView}
      >
        <summary>
          <span>{isZh ? `${viewLabel} · 本次教练回复` : `${viewLabel} · Latest Coach reply`}</span>
          <strong>{summary}</strong>
        </summary>
        <div className="view-agent-reply__body" aria-live={isStreamingForView ? "polite" : undefined}>
          <CoachMessageBubble
            assistantLabel={t.trainer}
            className={isStreamingForView ? "message-bubble--streaming" : undefined}
            language={layout.composerLanguage}
            message={visibleReply}
            openArtifactLabel={layout.composerLanguage === "zh-CN" ? "展开" : "Open"}
            systemLabel={layout.composerLanguage === "zh-CN" ? "系统" : "System"}
            userLabel={t.you}
            streaming={isStreamingForView}
            onArtifactOpen={handleCoachArtifactOpen}
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

  const renderCoachRootView = () => (
    <section className="coach-view">
      {workspaceSessionBlocked && workspaceAdmissionContent ? (
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
      ) : providerCoachNotice && sendBlocked && !shouldShowNeutralEmptyState && !workspaceSessionBlocked ? (
        <div
          className={`coach-inline-notice coach-inline-notice--${providerCoachNotice.tone}`}
          role="status"
        >
          {providerCoachNotice.message}
        </div>
      ) : null}
      {renderCoachConversationPane("coach-pane", false)}
    </section>
  );

  const contextualComposerSummary = () => {
    if (!latestCoachArtifact || leftoverCoachTurnChromeNotLive) {
      return sendStatuslineText(sendAnalysis, data, layout, t);
    }
    if (layout.composerLanguage === "zh-CN") {
      const action = latestCoachArtifact.recommendedAction
        ? `现在顺着这条结果继续：${latestCoachArtifact.title}`
        : `当前主线：${latestCoachArtifact.title}`;
      return latestArtifactTeaser ? `${action} · ${latestArtifactTeaser}` : action;
    }
    const action = latestCoachArtifact.recommendedAction
      ? `Continuing this result: ${latestCoachArtifact.title}`
      : `Current lane: ${latestCoachArtifact.title}`;
    return latestArtifactTeaser ? `${action} · ${latestArtifactTeaser}` : action;
  };

  const composerSurfaceHint = () => {
    if (providerSendState.status === "degraded_error" || providerSendState.status === "refreshing") {
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
        ? layout.composerLanguage === "zh-CN"
          ? "先记下下一条计划备注。"
          : "Queue the next plan note here."
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
        ? layout.composerLanguage === "zh-CN"
          ? "找资料"
          : "Find a file"
        : activeView === "training"
          ? trainingComposerModeTextCopy.genericPlaceholder
          : activeView === "plan"
            ? layout.composerLanguage === "zh-CN"
              ? "写下这一步"
              : "Write the next step"
            : blockedComposerFallback;
  const refinedUtilityComposerPlaceholder =
    activeView === "resources"
      ? layout.composerLanguage === "zh-CN"
        ? "找资料"
        : "Find a file"
      : activeView === "plan"
        ? layout.composerLanguage === "zh-CN"
          ? "写下这一步"
          : "Write the next step"
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
  const resolvedUtilityComposerSummary =
    activeView === "resources"
      ? layout.composerLanguage === "zh-CN"
        ? `资料：${selectedResourceNavigationLabel ?? "先让教练定位文件"}`
        : `Resources: ${selectedResourceNavigationLabel ?? "Let Coach locate the next file"}`
      : activeView === "plan"
        ? layout.composerLanguage === "zh-CN"
          ? `计划：${truncateInlineText(formalPlanLive ? activePlanStage?.title ?? resolvedCoachStage ?? resolvedCoachFocus ?? livePlanSummary : recoveredDisplayFacts.currentStep || livePlanTitle, 24) ?? "解释当前阶段"}`
          : `Plan: ${truncateInlineText(formalPlanLive ? activePlanStage?.title ?? resolvedCoachStage ?? resolvedCoachFocus ?? livePlanSummary : recoveredDisplayFacts.currentStep || livePlanTitle, 48) ?? "Explain the current stage"}`
        : activeView === "coach"
          ? contextualComposerSummary()
          : undefined;
  const resolvedUtilityComposerHint =
    activeView === "resources"
      ? layout.composerLanguage === "zh-CN"
        ? "可以让教练先找文件、判断最该打开哪一个，或建议如何整理当前资料区。"
        : "Ask Coach to find the right file, decide what to open next, or suggest how to organize this resource area."
      : activeView === "plan"
        ? layout.composerLanguage === "zh-CN"
          ? "这里适合解释当前阶段、梳理 evidence，或把 blocker 压成更小的下一步。"
          : "Use this to explain the current stage, structure evidence, or compress a blocker into a smaller next step."
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
  const resolvedComposerSummary = trainingComposerTalkMode
    ? layout.composerLanguage === "zh-CN"
      ? "\u8bad\u7ec3 \u00b7 \u4e0e\u6559\u7ec3\u5bf9\u8bdd"
      : "Training · Coach conversation"
    : composerUsesTrainingFlow
    ? trainingComposerUsesAnswerMode
      ? layout.composerLanguage === "zh-CN"
        ? `\u4f5c\u7b54\u65b9\u5f0f\uff1a${
            trainingComposerFlashMode === "choice"
              ? "\u9009\u62e9"
              : trainingComposerFlashMode === "fill"
                ? "\u586b\u7a7a"
                : "\u7b80\u7b54"
          }`
        : `Answer mode: ${
            trainingComposerFlashMode === "choice"
              ? "Choice"
              : trainingComposerFlashMode === "fill"
                ? "Fill"
                : "Short"
          }`
      : trainingComposerPracticeInputMode
        ? trainingComposerFilePracticeMode
          ? layout.composerLanguage === "zh-CN"
            ? `\u52a8\u624b\uff1a${trainingComposerPracticeReturnMode === "result" ? "\u7ed3\u679c\u8bb0\u5f55" : "Blocker"}`
            : `Try: ${trainingComposerPracticeReturnMode === "result" ? "Result note" : "Blocker"}`
          : layout.composerLanguage === "zh-CN"
            ? `\u52a8\u624b\uff1a${trainingComposerPracticeReturnMode === "result" ? "\u7ed3\u679c" : "Blocker"}`
            : `Try: ${trainingComposerPracticeReturnMode === "result" ? "Result" : "Blocker"}`
      : trainingComposerStudyMode
        ? layout.composerLanguage === "zh-CN"
          ? `\u5b66\u4e60\u805a\u7126\uff1a${truncateInlineText(trainingTargetSkill ?? trainingScenarioPackLabel ?? trainingProblemStatement, 22) ?? (trainingTargetSkill ?? trainingScenarioPackLabel ?? trainingProblemStatement ?? "\u5f53\u524d\u5361\u7247")}`
          : `Study focus: ${truncateInlineText(trainingTargetSkill ?? trainingScenarioPackLabel ?? trainingProblemStatement, 44) ?? (trainingTargetSkill ?? trainingScenarioPackLabel ?? trainingProblemStatement ?? "Current card")}`
      : trainingComposerReturnMode
        ? layout.composerLanguage === "zh-CN"
          ? `\u56de\u6d41\uff1a${truncateInlineText(trainingReturnWithText ?? trainingSuccessSignal ?? trainingCoachBridge.ctaLabel, 26) ?? "\u5e26\u56de\u7ed3\u679c"}`
          : `Return: ${truncateInlineText(trainingReturnWithText ?? trainingSuccessSignal ?? trainingCoachBridge.ctaLabel, 52) ?? "Bring back the result"}`
      : trainingComposerReflectMode
        ? trainingComposerReflectReason === "flash_answered"
          ? layout.composerLanguage === "zh-CN"
            ? "\u590d\u76d8\uff1a\u538b\u6210\u4e00\u6761\u89c4\u5219"
            : "Reflect: One rule"
          : trainingComposerReflectReason === "skipped"
            ? layout.composerLanguage === "zh-CN"
              ? "\u590d\u76d8\uff1a\u6536\u7d27\u5165\u53e3"
              : "Reflect: Smaller slice"
            : trainingComposerReflectReason === "verification_passed"
              ? layout.composerLanguage === "zh-CN"
                ? "\u590d\u76d8\uff1a\u5df2\u9a8c\u8bc1\u7684\u89c4\u5219"
                : "Reflect: Verified rule"
            : layout.composerLanguage === "zh-CN"
              ? `\u590d\u76d8\uff1a${truncateInlineText(trainingFallbackActionText ?? trainingComposerSelectedVerifyItem ?? trainingState?.latestLearningBlocker, 26) ?? "收紧 blocker"}`
              : `Reflect: ${truncateInlineText(trainingFallbackActionText ?? trainingComposerSelectedVerifyItem ?? trainingState?.latestLearningBlocker, 52) ?? "Tighten the blocker"}`
      : trainingComposerSelectedVerifyItem
        ? layout.composerLanguage === "zh-CN"
          ? `\u5f53\u524d\u68c0\u67e5\uff1a${truncateInlineText(trainingComposerSelectedVerifyItem, 26) ?? trainingComposerSelectedVerifyItem}`
          : `Current check: ${truncateInlineText(trainingComposerSelectedVerifyItem, 52) ?? trainingComposerSelectedVerifyItem}`
        : layout.composerLanguage === "zh-CN"
          ? "\u8bb0\u4e0b\u8fd9\u4e00\u8f6e\u7684\u7ed3\u679c\u3002"
          : "Record this round's result."
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
      ? layout.composerLanguage === "zh-CN"
        ? "提交计划讨论、生成或证据整理请求"
        : "Submit a plan discussion, generation, or evidence request"
      : activeView === "resources"
        ? layout.composerLanguage === "zh-CN"
          ? "提交资料定位、整理、下载或转卡请求"
          : "Submit a resource locate, organize, download, or card request"
        : activeView === "coach"
          ? t.composerAccessibility
          : activeView === "training"
            ? trainingComposerModeTextCopy.genericAccessibilityLabel
          : layout.composerLanguage === "zh-CN"
            ? "提交当前视图请求"
            : "Submit the current view request";
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
          : layout.composerLanguage === "zh-CN"
            ? activeView === "coach"
              ? "发送消息"
              : "发送请求"
            : activeView === "coach"
              ? "Send message"
              : "Send request";
  const localizedTrainingComposerSummary =
    !trainingComposerTalkMode && composerUsesTrainingFlow && trainingComposerReturnMode
      ? trainingHandoffComposerTextCopy.returnSummary
      : laneAwareComposerSummary;
  const allowEmptyTrainingReturnSubmission =
    composerUsesTrainingFlow &&
    trainingComposerReturnMode &&
    trainingHandoffReturnRequired &&
    Boolean(activeTrainingCardId);
  const shouldUseCompactUtilityComposer = activeView !== "coach" && draft.trim().length === 0;
  const trainingPrimaryAction = !hasTrainingCard ? undefined : undefined;
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
        <Suspense
          fallback={<ViewFallback label={resourcesViewLabel(layout.composerLanguage)} language={layout.composerLanguage} />}
        >
          <ResourcesWorkbenchView
          language={layout.composerLanguage}
          resources={liveResources}
          resourceSearch={data.resourceSearch}
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
            postDebugVisibleFacts({ activeView: "resources", resources: facts })
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
          isLiveBrowserPreview={isBrowserPreview && !browserPreviewFixture}
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
              ? () =>
                  postMessage({
                    type: "command/execute",
                    payload: {
                      commandId: trainerCommands.indexResources,
                    },
                  })
              : requestResourceIndex
          }
          onRefreshDeletedResources={
            isBrowserPreview
              ? undefined
              : () =>
                  postMessage({
                    type: "command/execute",
                    payload: {
                      commandId: trainerCommands.refreshResourceTrash,
                    },
                  })
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
              ? layout.composerLanguage === "zh-CN"
                ? "\u6d4f\u89c8\u5668\u9884\u89c8\u4e0d\u4f1a\u5220\u9664\u771f\u5b9e\u8d44\u6599\u3002\u8bf7\u5728 VS Code \u4fa7\u680f\u4e2d\u6267\u884c\u3002"
                : "Browser preview cannot delete real resources. Use the VS Code sidebar."
              : undefined
          }
          restoreUnavailableReason={
            isBrowserPreview
              ? layout.composerLanguage === "zh-CN"
                ? "\u6d4f\u89c8\u5668\u9884\u89c8\u4e0d\u4f1a\u6062\u590d\u771f\u5b9e\u8d44\u6599\u3002\u8bf7\u5728 VS Code \u4fa7\u680f\u4e2d\u6267\u884c\u3002"
                : "Browser preview cannot restore real resources. Use the VS Code sidebar."
              : undefined
          }
          />
        </Suspense>
        {renderViewAgentReply("resources")}
        {renderContextualResultRail("resources")}
      </section>
    );
  };

  const renderTrainingView = () => {
    const title = hasRenderableTrainingCard
      ? pickLanguageAlignedTrainingText(
          layout.composerLanguage,
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
        ) ?? trainingViewLabel(layout.composerLanguage)
      : trainingViewLabel(layout.composerLanguage);
    const currentStep = hasRenderableTrainingCard
      ? pickLanguageAlignedTrainingText(
          layout.composerLanguage,
          trainingProblemStatement,
          trainingSuggestedWorkspaceAction,
          trainingDeliverables[0],
          selectedTrainingCardCandidate?.deliverable,
          selectedTrainingRouteCard?.deliverable,
        ) ?? ""
      : "";
    const localizedSuggestedWorkspaceAction = hasRenderableTrainingCard
      ? pickLanguageAlignedTrainingText(
          layout.composerLanguage,
          trainingSuggestedWorkspaceAction,
          selectedTrainingCardCandidate?.deliverable,
          selectedTrainingRouteCard?.deliverable,
          runtimeCurrentStep,
        )
      : undefined;
    const localizedScenario = hasRenderableTrainingCard
      ? pickLanguageAlignedTrainingText(
          layout.composerLanguage,
          trainingScenario,
          trainingScenarioPackLabel,
        )
      : undefined;
    const localizedWhyNow = hasRenderableTrainingCard
      ? pickLanguageAlignedTrainingText(layout.composerLanguage, liveTrainingWhy)
      : undefined;
    const localizedSourceSummary = hasRenderableTrainingCard
      ? pickLanguageAlignedTrainingText(
          layout.composerLanguage,
          leftoverTrainingHandoffChromeNotLive
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
    const localizedCurrentFocus = hasRenderableTrainingCard
      ? pickLanguageAlignedTrainingText(
          layout.composerLanguage,
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
        )
      : undefined;

    return (
      <section className="training-view">
        <Suspense fallback={<ViewFallback label={t.training} language={layout.composerLanguage} />}>
          <TrainingWorkbenchView
          language={layout.composerLanguage}
          cardType={trainingCardType}
          trainingSubmode={effectiveTrainingSubmode}
          cardOnly={true}
          cardId={activeTrainingCardId}
          selectedCardStatus={effectiveSelectedTrainingCardStatus}
          onCardStatusTransition={leftoverTrainingHandoffChromeNotLive ? undefined : handleTrainingCardStatusTransition}
          title={title}
          currentStep={currentStep}
          learningFamily={trainingLearningFamily}
          learningSubtype={trainingLearningSubtype}
          whyThisCard={localizedWhyNow}
          targetSkill={liveTrainingSkill}
          problemStatement={trainingProblemStatement}
          suggestedWorkspaceAction={localizedSuggestedWorkspaceAction}
          scenario={localizedScenario}
          whyNow={localizedWhyNow}
          sourceSummary={localizedSourceSummary}
          sourceDetail={
            hasRenderableTrainingCard
              ? pickLanguageAlignedTrainingText(
                  layout.composerLanguage,
                  leftoverTrainingHandoffChromeNotLive
                    ? undefined
                    : liveTrainingHandoffChrome.handoffSummary,
                  leftoverTrainingHandoffChromeNotLive
                    ? undefined
                    : trainingState?.latestTrainingHandoff?.handoffSummary,
                  leftoverTrainingHandoffChromeNotLive
                    ? undefined
                    : liveTrainingHandoffChrome.nextHopHandoffSummary,
                )
              : undefined
          }
          apiHints={hasTrainingCard ? trainingApiHints : []}
          constraints={hasTrainingCard ? trainingConstraints : []}
          selfCheck={hasTrainingCard ? trainingSelfCheck : []}
          deliverable={hasTrainingCard ? trainingDeliverable : undefined}
          deliverables={hasTrainingCard ? trainingDeliverables : []}
          validationMethod={hasTrainingCard ? trainingValidationMethod : undefined}
          verificationMethod={hasTrainingCard ? trainingVerificationMethod : undefined}
          verifyItems={hasTrainingCard ? authoritativeVerifyItems : []}
          successSignal={hasTrainingCard ? trainingSuccessSignal : undefined}
          returnWith={hasTrainingCard ? trainingReturnWithText : undefined}
          nextAfterCompletion={hasTrainingCard ? trainingNextAfterCompletionText : undefined}
          fallbackAction={hasTrainingCard ? trainingFallbackActionText : undefined}
          filesToTouch={hasTrainingCard ? trainingFilesToTouch : []}
          hintLadder={hasTrainingCard ? trainingHintLadder : []}
          commonMistakes={hasTrainingCard ? trainingCommonMistakes : []}
          stuckRecovery={hasTrainingCard ? trainingStuckRecovery : undefined}
          reflectionPrompt={hasTrainingCard ? trainingReflectionPrompt : undefined}
          outcome={hasTrainingCard ? trainingOutcomeCard : undefined}
          nextHop={
            hasRenderableTrainingCard && !trainingRestoreForeground
              ? trainingNextHopCard
              : undefined
          }
          coachSummary={
            hasTrainingCard
              ? trainingStatusMeta ??
                pickLanguageAlignedTrainingText(layout.composerLanguage, liveTrainingCoachChrome)
              : undefined
          }
          scenarioPackLabel={hasTrainingCard ? trainingScenarioPackLabel : undefined}
          currentFocus={localizedCurrentFocus}
          latestTrainingHandoffStatus={
            reviewArtifactForeground || trainingRestoreReplacesSelectedCard
              ? undefined
              : trainingState?.latestTrainingHandoff?.handoffStatus
          }
          latestTrainingLearningPhase={
            reviewArtifactForeground || trainingRestoreReplacesSelectedCard
              ? selectedTrainingCardCandidate?.learningPhase
              : (trainingState?.latestTrainingHandoff?.learningPhase ??
                selectedTrainingCardCandidate?.learningPhase)
          }
          latestTrainingReliability={trainingState?.latestTrainingReliability}
          reliabilityInFlight={trainingPersistencePending}
          latestTrainingNextHopStatus={
            reviewArtifactForeground || trainingRestoreReplacesSelectedCard
              ? undefined
              : trainingState?.latestTrainingNextHop?.status
          }
          latestTrainingNextHopReason={
            !reviewArtifactForeground &&
            !trainingRestoreReplacesSelectedCard &&
            trainingState?.latestTrainingNextHop?.status === "blocked"
              ? trainingState.latestTrainingNextHop.statusReason
              : undefined
          }
          latestTrainingBlockedBy={
            leftoverTrainingHandoffChromeNotLive ||
            reviewArtifactForeground ||
            trainingRestoreReplacesSelectedCard
              ? undefined
              : liveTrainingHandoffChrome.blocker ??
                trainingState?.latestTrainingHandoff?.blockedBy
          }
          latestVerifiedResult={
            trainingRestoreReplacesSelectedCard
              ? undefined
              : pickLanguageAlignedTrainingText(
                  layout.composerLanguage,
                  trainingState?.latestLearningVerifiedResult,
                )
          }
          latestLearningBlocker={
            trainingVerifyNotice ??
            (leftoverTrainingHandoffChromeNotLive || trainingRestoreReplacesSelectedCard
              ? undefined
              : pickLanguageAlignedTrainingText(
                  layout.composerLanguage,
                  liveTrainingHandoffChrome.blocker,
                  trainingState?.latestLearningBlocker,
                ))
          }
          latestLearningFollowup={
            leftoverTrainingHandoffChromeNotLive || trainingRestoreReplacesSelectedCard
              ? undefined
              : pickLanguageAlignedTrainingText(
                  layout.composerLanguage,
                  liveTrainingHandoffChrome.followup,
                  trainingState?.latestLearningFollowup,
                )
          }
          reviewItems={trainingReviewItems}
          onReviewQueueAction={handleReviewQueueAction}
          reviewSummary={pickLanguageAlignedTrainingText(
            layout.composerLanguage,
            formattedNextReviewDue,
            data.memory.reviewSummary,
          )}
          recentWins={pickLanguageAlignedTrainingList(layout.composerLanguage, data.memory.recentWins)}
          weakSpots={pickLanguageAlignedTrainingList(layout.composerLanguage, data.memory.weakSpots)}
          primaryAction={
            leftoverTrainingHandoffChromeNotLive ? (
              <button
                className="button button--accent"
                type="button"
                aria-label={t.openCoach}
                onClick={() => setActiveView("coach")}
              >
                {t.openCoach}
              </button>
            ) : trainingPrimaryAction
          }
          leftoverNote={leftoverTrainingHandoffChromeNotLive ? t.leftoverNotLive : undefined}
          actions={hasTrainingCard ? trainingCoachAction : undefined}
          emptyState={
            leftoverTrainingHandoffChromeNotLive ? undefined : (
            <div className="workbench-empty">
              <h3>{t.trainingEmptyTitle}</h3>
              <p>{t.trainingEmptyDescription}</p>
              <button
                className="button button--accent"
                type="button"
                onClick={() => handleGenerateTrainingCard()}
              >
                {t.startTraining}
              </button>
            </div>
            )
          }
          onNextCard={handleGenerateTrainingCard}
          onRefreshDeck={handleRefreshTrainingDeck}
          flashPrompt={trainingFlashPrompt}
          expectedSymbols={trainingCardType === "practice" ? practiceExpectedSymbols : []}
          />
        </Suspense>
        {renderViewAgentReply("training")}
        {renderContextualResultRail("training")}
      </section>
    );
  };

  const renderPlanView = () => (
    <section className="plan-view">
      <Suspense fallback={<ViewFallback label={t.plan} language={layout.composerLanguage} />}>
        <CoachPlanView
        plan={shouldShowNeutralEmptyState ? null : visibleFormalPlan}
        className="plan-pane"
        compactPrimary
        leftoverNote={leftoverPlanNotLive ? t.leftoverNotLive : undefined}
        hideDecisionStrip
        eyebrow=""
        title={
          shouldShowNeutralEmptyState || !hasFormalPlan
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
          <>
            <p>
              {!formalPlanLive && recoveredDisplayFacts.currentStep
                ? recoveredDisplayFacts.currentStep
                : !liveStageChrome.stageIsCurrent && recoveredDisplayFacts.currentStep
                  ? recoveredDisplayFacts.currentStep
                  : resolvedCoachFocus ||
                    activeStageObjectiveText(activePlanStage, livePlanSummary)}
            </p>
          </>
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
          ...(liveEvidenceQueue.pending.length > 0
            ? [
                {
                  id: "plan-needs-evidence",
                  label: planOrientation.primaryActionLabel,
                  tone: "accent" as const,
                  onClick: () => handlePlanOrientationAction("wait"),
                },
              ]
            : []),
          ...(sendBlocked
            ? [
                {
                  id: "open-settings",
                  label: workspaceSessionBlocked
                    ? trainerWorkspaceAdmission?.status === "root-missing"
                      ? t.workspaceAdmissionSelectRoot
                      : t.openCoach
                    : t.openSettings,
                  tone: "accent" as const,
                  onClick: () => {
                    if (workspaceSessionBlocked) {
                      openWorkspaceAdmission();
                      return;
                    }
                    setActiveView("settings");
                  },
                },
              ]
            : [
                ...(recoveredPlanPrimary && !recoveredAdoptPrimary
                  ? [
                      {
                        id:
                          recoveredPlanPrimary === "clear_blocker"
                            ? "plan-clear-blocker"
                            : recoveredPlanPrimary === "wait"
                              ? "plan-needs-evidence"
                              : "plan-continue-step",
                        label: planOrientation.primaryActionLabel,
                        tone: "accent" as const,
                        onClick: () => handlePlanOrientationAction(recoveredPlanPrimary),
                      },
                    ]
                  : []),
                ...(firstLookContinuePrimary
                  ? [
                      {
                        id: "plan-continue-without-plan",
                        label: planOrientation.primaryActionLabel,
                        tone: "accent" as const,
                        onClick: () => handlePlanOrientationAction("continue_without_plan"),
                      },
                    ]
                  : []),
                ...(!recoveredAdoptPrimary && (!hasFormalPlan || !livePlanFrozen)
                  ? [
                      {
                        id: "refresh-plan",
                        label: t.generatePlan,
                        tone:
                          recoveredPlanPrimary || firstLookContinuePrimary
                            ? ("ghost" as const)
                            : ("accent" as const),
                        disabled: !providerCanMutateFormalPlan,
                        detail: providerCanMutateFormalPlan ? undefined : formalPlanCapabilityMessage,
                        onClick: () => handlePlanOrientationAction("generate_plan"),
                      },
                    ]
                  : []),
                ...(!recoveredAdoptPrimary && hasFormalPlan && formalPlanLive
                  ? [
                {
                  id: "plan-next-task",
                  label: planText.nextTaskLabel,
                  tone: "ghost" as const,
                  onClick: () => {
                    setActiveView("coach");
                    sendTurn({
                      text: defaultPromptText("next_task", layout.composerLanguage, activePlanStage?.title),
                      intent: "next_task",
                      activeView: "coach",
                    });
                  },
                },
                  ]
                  : []),
              ]),
          ...(hasFormalPlan && formalPlanLive && !recoveredAdoptPrimary && !shouldShowNeutralEmptyState
            ? [
                {
                  id: livePlanFrozen ? "resume-plan" : "freeze-plan",
                  label: livePlanFrozen ? t.planLive : t.planFreeze,
                  tone: "ghost" as const,
                  onClick: () => {
                    pendingLivePlanTaskMintRef.current = {
                      commandId: trainerCommands.updatePlan,
                    };
                    setOperationMessage({
                      tone: "info",
                      message: livePlanUpdatePendingMessage(layout.composerLanguage),
                    });
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
                (firstLookContinuePrimary
                  ? planOrientation.nextStep
                  : recoveredDisplayFacts.currentStep ||
                    liveCoachTaskChrome.currentStep ||
                    resolvedCoachNextStep ||
                    latestArtifactTeaser)}
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
      {renderViewAgentReply("plan")}
      {renderContextualResultRail("plan")}
    </section>
  );

  const renderSettingsView = () => (
    <section className="settings-view">
      <Suspense fallback={<ViewFallback label={t.settings} language={layout.composerLanguage} />}>
        <CoachSettingsView
        className="settings-pane"
        provider={data.providerConfig}
        workspaceId={settingsWorkspaceId}
        capabilityVerdict={capabilityVerdict}
        providerImageInputState={providerImageInputState}
        providerDraft={providerDraft}
        providerStatus={providerStatus}
        coachDefaultsStatus={coachDefaultsStatus}
        workspaceControlStatus={workspaceControlStatus}
        providerApiKeyFocusRequest={providerApiKeyFocusRequest}
        coachStateSummary={resolvedCoachStateSummary}
        coachSignal={
          resolvedCoachSignal ? learnerSignalLabel(resolvedCoachSignal, layout.composerLanguage) : undefined
        }
        workspaceAuthority={liveSandboxState?.authority}
        workspaceTrustState={readWorkspaceTrustStateFromCapabilitySummary(
          liveSandboxState?.capabilitySummary as Record<string, unknown> | undefined,
        )}
        resourceSandbox={data.memory.workspace?.resourceSandbox ?? null}
        trainerWorkspace={trainerWorkspaceAdmission}
        learnerName={
          leftoverSettingsLearnerProjectOnboardingNotLive ? undefined : data.profile.learnerName
        }
        targetProject={
          leftoverSettingsLearnerProjectOnboardingNotLive ? undefined : data.profile.targetProject
        }
        preferredRhythm={
          leftoverSettingsProfileRhythmNotLive ? undefined : data.profile.preferredRhythm
        }
        preferredLearningMode={
          leftoverSettingsProfileRhythmNotLive ? undefined : data.profile.preferredLearningMode
        }
        onboardingRequest={
          leftoverSettingsLearnerProjectOnboardingNotLive ? undefined : data.profile.onboardingRequest
        }
        projectContext={
          leftoverSettingsLearnerProjectOnboardingNotLive ? undefined : data.profile.projectContext
        }
        reviewRhythmSummary={resolvedCoachReview}
        nextReviewDue={formattedNextReviewDue}
        longTermMemoryStateLabel={layout.composerLanguage === "zh-CN" ? "已启用" : "Enabled"}
        themePreference={layout.themePreference}
        memoryShareGrants={data.memory.memoryShareGrants ?? []}
        learningSurfaceAlignment={layout.learningSurfaceAlignment}
        language={layout.composerLanguage}
        answerMode={layout.composerAnswerMode}
        teachingStyle={layout.teachingStyle}
        coachDefaults={
          leftoverSettingsProfileRhythmNotLive ? defaultCoachDefaults : layout.coachDefaults
        }
        followCurrentFile={layout.followCurrentFile}
        onProviderDraftChange={(patch) => {
          providerDraftIsDirtyRef.current = true;
          setProviderDraft((current) => {
            const hasProtocol = Object.prototype.hasOwnProperty.call(patch, "protocol");
            const hasBaseUrl = Object.prototype.hasOwnProperty.call(patch, "baseUrl");
            const hasModel = Object.prototype.hasOwnProperty.call(patch, "model");
            const hasModelTokenLimits = Object.prototype.hasOwnProperty.call(patch, "modelTokenLimits");
            const hasContextWindowTokens = Object.prototype.hasOwnProperty.call(
              patch,
              "contextWindowTokens",
            );
            const hasMaxOutputTokens = Object.prototype.hasOwnProperty.call(patch, "maxOutputTokens");
            const nextProtocol = hasProtocol
              ? normalizeProviderProtocol(patch.protocol) ?? current.protocol
              : current.protocol;
            const nextBaseUrl =
              hasBaseUrl && typeof patch.baseUrl === "string" ? patch.baseUrl : current.baseUrl;
            const normalizedCurrentBaseUrl = current.baseUrl.trim().replace(/\/+$/, "");
            const normalizedNextBaseUrl = nextBaseUrl.trim().replace(/\/+$/, "");
            const transportChanged =
              (hasProtocol && normalizeProviderProtocol(current.protocol) !== nextProtocol) ||
              (hasBaseUrl && normalizedCurrentBaseUrl !== normalizedNextBaseUrl);

            if (transportChanged) {
              return {
                ...current,
                ...patch,
                protocol: nextProtocol,
                model: "",
                contextWindowTokens: undefined,
                maxOutputTokens: undefined,
                modelTokenLimits: undefined,
                catalogModels: [],
              };
            }

            if (!hasModel && !hasModelTokenLimits && !hasContextWindowTokens && !hasMaxOutputTokens) {
              return {
                ...current,
                ...patch,
              };
            }

            const nextModel =
              hasModel && typeof patch.model === "string" ? patch.model : current.model;
            const tokenState = resolveProviderModelTokenState(current, nextModel, {
              modelTokenLimits: hasModelTokenLimits ? patch.modelTokenLimits : current.modelTokenLimits,
              hasModelTokenLimits,
              contextWindowTokens: patch.contextWindowTokens,
              maxOutputTokens: patch.maxOutputTokens,
              hasContextWindowTokens,
              hasMaxOutputTokens,
            });

            return {
              ...current,
              ...patch,
              model: nextModel,
              contextWindowTokens: tokenState.contextWindowTokens,
              maxOutputTokens: tokenState.maxOutputTokens,
              modelTokenLimits: tokenState.modelTokenLimits,
            };
          });
        }}
        onThemePreferenceChange={setThemePreference}
        onLearningSurfaceAlignmentChange={setLearningSurfaceAlignment}
        onLanguageChange={setComposerLanguage}
        onAnswerModeChange={setComposerAnswerMode}
        onTeachingStyleChange={setTeachingStyle}
        onFollowCurrentFileChange={setFollowCurrentFile}
        onCoachDefaultsChange={setCoachDefaults}
        onContextDetailChange={setContextDetail}
        onIncludeCurrentFileChange={setIncludeCurrentFile}
        onIncludeSelectionChange={setIncludeSelection}
        onIncludeDiagnosticsChange={setIncludeDiagnostics}
        onIncludeRelatedFilesChange={setIncludeRelatedFiles}
        onSaveCoachSettings={() => persistCoachSettings()}
        onGrantMemoryShare={
          isBrowserPreview
            ? undefined
            : () =>
                postMessage({
                  type: "command/execute",
                  payload: { commandId: trainerCommands.grantMemoryShare },
                })
        }
        onRevokeMemoryShare={
          isBrowserPreview
            ? undefined
            : (sourceWorkspaceId) =>
                postMessage({
                  type: "command/execute",
                  payload: {
                    commandId: trainerCommands.revokeMemoryShare,
                    payload: { sourceWorkspaceId },
                  },
                })
        }
        onSaveProvider={() => {
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
        }}
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
        onUseProviderTemplate={() => {
          setSettingsActionState({
            kind: "save-provider",
            targets: ["provider"],
            baselineMessageKey:
              normalizeOperationMessageKey(operationMessage) ?? baselineConnectedMessage.toLowerCase(),
          });
          if (isBrowserPreview) {
            void loadBrowserPreviewModule()
              .then((browserPreview) =>
                browserPreview.useBrowserPreviewProviderTemplate(previewSessionId),
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
                templateLabel: "MiniMax",
                skipPicker: true,
              },
            },
          });
        }}
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
                layout.composerLanguage === "zh-CN"
                  ? "浏览器预览没有工作区配置文件入口。这个按钮只在 VS Code 侧栏里可用。"
                  : "Browser preview does not expose a workspace config file. This action is only available inside the VS Code sidebar.",
            });
            return;
          }
          postMessage({
            type: "command/execute",
            payload: { commandId: "trainer.config.openWorkspace" },
          });
        }}
        onRefreshWorkspaceAuthority={() => {
          if (isBrowserPreview) {
            setOperationMessage({
              tone: "info",
              message:
                layout.composerLanguage === "zh-CN"
                  ? "浏览器预览只显示预置的工作区边界状态。重新读取真实边界请回到 VS Code 侧栏。"
                  : "Browser preview only shows seeded workspace boundary state. Re-read the real boundary in the VS Code sidebar.",
            });
            return;
          }
          postMessage({
            type: "command/execute",
            payload: { commandId: trainerCommands.refreshWorkspaceAuthority },
          });
        }}
        onChooseTrainerWorkspaceRoot={() =>
          runWorkspaceAdmissionCommand(trainerCommands.chooseTrainerWorkspaceRoot)
        }
        onMigrateTrainerWorkspaceRoot={() =>
          runWorkspaceAdmissionCommand(trainerCommands.migrateTrainerWorkspaceRoot)
        }
        onBackupTrainerWorkspace={() =>
          runWorkspaceAdmissionCommand(trainerCommands.backupTrainerWorkspace)
        }
        onRestoreTrainerWorkspaceBackup={() =>
          runWorkspaceAdmissionCommand(trainerCommands.restoreTrainerWorkspaceBackup)
        }
        onChooseManagedDataFolder={() => {
          if (isBrowserPreview) {
            setOperationMessage({
              tone: "info",
              message:
                layout.composerLanguage === "zh-CN"
                  ? "浏览器预览不能修改 managed data folder。请在 VS Code 侧栏里选择真实路径。"
                  : "Browser preview cannot change the managed data folder. Choose the real path in the VS Code sidebar.",
            });
            return;
          }
          postMessage({
            type: "command/execute",
            payload: { commandId: trainerCommands.chooseManagedDataFolder },
          });
        }}
        onResetManagedDataFolder={() => {
          if (isBrowserPreview) {
            setOperationMessage({
              tone: "info",
              message:
                layout.composerLanguage === "zh-CN"
                  ? "浏览器预览不能重置 managed data folder。请在 VS Code 侧栏里使用推荐路径。"
                  : "Browser preview cannot reset the managed data folder. Use the recommended path in the VS Code sidebar.",
            });
            return;
          }
          postMessage({
            type: "command/execute",
            payload: { commandId: trainerCommands.resetManagedDataFolder },
          });
        }}
        onRefreshMemory={() =>
          postMessage({
            type: "command/execute",
            payload: { commandId: "trainer.memory.refresh" },
          })
        }
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
              defaultLanguage === "zh-CN"
                ? "已恢复教练默认设置。"
                : "Coach defaults restored.",
          });
        }}
        />
      </Suspense>
      {renderContextualResultRail("settings")}
    </section>
  );

  let activeViewContent = renderCoachRootView();
  switch (activeView) {
    case "plan":
      activeViewContent = renderDockedView("plan", renderPlanView());
      break;
    case "resources":
      activeViewContent = renderDockedView("resources", renderResourcesView());
      break;
    case "training":
      activeViewContent = renderDockedView("training", renderTrainingView());
      break;
    case "settings":
      activeViewContent = renderDockedView("settings", renderSettingsView());
      break;
    case "coach":
    default:
      activeViewContent = renderCoachRootView();
      break;
  }

  const workbenchShell = (
      <div
        className="trainer-shell"
        lang={layout.composerLanguage}
        dir={uiDirection}
        data-text-direction={uiDirection}
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
      <header className="trainer-header">
        <div className="trainer-header__status">
          <div
            ref={headerSwitcherRef}
            className={`header-switcher header-switcher--${headerSwitcherDensity}`}
            aria-label={t.viewNavigation}
          >
            {sidebarViewTabs.map(({ view, label, compactLabel }) => {
              const displayLabel = headerSwitcherDensity === "compact" ? compactLabel : label;
              return (
                <button
                  key={view}
                  className={`header-switcher__item ${activeView === view ? "is-active" : ""}`}
                  data-testid={`trainer-view-nav-${view}`}
                  onClick={() => setActiveView(view)}
                  type="button"
                  aria-label={label}
                  title={label}
                  aria-pressed={activeView === view}
                  aria-current={activeView === view ? "page" : undefined}
                >
                  <span className="header-switcher__label">{displayLabel}</span>
                </button>
              );
            })}
          </div>
          <div className="header-actions">
            {activeView === "coach" && displayConnectionState !== "connected" ? (
              <StatusPill tone={displayConnectionState}>
                {connectionStateLabel(displayConnectionState, t)}
              </StatusPill>
            ) : null}
          </div>
        </div>
      </header>

      {operationMessage &&
      !(operationMessageSurface === "training" && activeView !== "training") &&
      !(operationMessageSurface === "plan" && activeView !== "plan") ? (
        <div className={`notice notice--${operationMessage.tone}`} role="status">
          {sanitizeErrorSurfaceText(operationMessage.message, layout.composerLanguage)}
        </div>
      ) : null}

      <main
        className={`view-content${activeView === "coach" ? "" : " view-content--docked"}`}
        ref={viewContentRef}
      >
        {activeViewContent}
      </main>

      {showComposerShell ? (
      <footer className={`composer-shell composer-shell--quiet${shouldUseCompactUtilityComposer ? " composer-shell--compact" : ""}`}>
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
                      setActiveView("settings");
                    }}
                  >
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
                  </button>
                ) : null}
              </div>
            ) : null}

            {!sendBlocked && !sendAnalysis.isEmpty && visibleWarnings.length > 0 ? (
              <div className="composer-meta composer-meta--compact">
                <div className="composer-inline-warnings">
                  {visibleWarnings.slice(0, 1).map((warning) => (
                    <button
                      key={warning.id}
                      className="inline-warning"
                      type="button"
                      onClick={() => {
                        if (warning.id === "review-file-disabled" || warning.id === "review-needs-file") {
                          setIncludeCurrentFile(true);
                        } else if (warning.id === "selection-available-but-disabled") {
                          setIncludeSelection(true);
                        } else if (warning.id === "related-available-but-disabled") {
                          setIncludeRelatedFiles(true);
                        } else if (warning.id === "review-not-full-context") {
                          setContextDetail("full");
                        }
                      }}
                    >
                      {warningText(warning.id, t)}
                    </button>
                  ))}
                </div>
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
                    <strong>{layout.composerLanguage === "zh-CN" ? "资料上下文" : "Resource context"}</strong>
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
                      {layout.composerLanguage === "zh-CN" ? "清除" : "Clear"}
                    </span>
                  </button>
                </div>
              </div>
            ) : null}

            <CoachComposer
              value={allowEmptyTrainingReturnSubmission ? "" : draft}
              onChange={handleComposerDraftChange}
              onSubmit={handleSubmit}
              onCancel={handleCancelStream}
              onNavigateHistory={navigateComposerHistory}
              density={shouldUseCompactUtilityComposer ? "compact" : "default"}
              placeholder={
                workspaceSessionBlocked && !canCaptureGoalBeforeWorkspaceSetup
                  ? workspaceSessionBlockMessage ?? ""
                  : shouldUseCompactUtilityComposer
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
                  ? layout.composerLanguage === "zh-CN"
                    ? "保存中"
                    : "Saving"
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
              minRows={1}
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
              modeControl={
                !composerUsesTrainingFlow && activeView === "plan"
                  ? {
                      id: "plan-composer-mode",
                      label: t.plan,
                      value: resolvedPlanComposerMode,
                      options: planComposerModes.map((mode) => ({
                        value: mode.id,
                        label: mode.label,
                        description: mode.header,
                      })),
                      onChange: (value) => {
                        const nextMode = planComposerModes.find((mode) => mode.id === value);
                        if (nextMode) {
                          setPlanComposerMode(nextMode.id);
                        }
                      },
                    }
                  : undefined
              }
              accessory={
                <>
                  {renderTrainingComposerAccessory()}
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
                ...(activeView === "coach"
                  ? [
                      {
                        id: "model-switch",
                        label: composerModelButtonDisplayLabel,
                        tone: "ghost" as const,
                        title: composerModelButtonTitle,
                        ariaLabel: composerModelButtonTitle,
                        onClick: toggleComposerModelMenu,
                      },
                    ]
                  : []),
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
                  event.preventDefault();
                  const selectedSkill = matchingLocalSkills[selectedCommandIndex];
                  if (selectedSkill) {
                    selectSkillSuggestion(selectedSkill);
                  }
                  return;
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
                {
                  id: "context",
                  label: t.currentContext,
                  icon: <ContextLayersIcon size={16} />,
                  active: openMenu === "context",
                  onClick: () => setOpenMenu(openMenu === "context" ? undefined : "context"),
                },
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
                ...(showComposerTrainingVerify
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
      </div>
  );

  return (
    <I18nProvider language={layout.composerLanguage} direction={uiDirection}>
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
    </I18nProvider>
  );
}
