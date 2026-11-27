import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import { deriveTrainerCapabilityVerdict } from "../../../../shared/src/capabilityVerdict";
import {
  matchesSavedCoachDefaults,
  sameCoachDefaults,
} from "../../../../shared/src/coachDefaults";
import { trainerCommands } from "../../../../shared/src/commands";
import type { CompanionInstallState } from "../../../../shared/src/companionInstallState";
import type { TrainerOperationMessage } from "../../../../shared/src/protocol";
import {
  PROVIDER_TEST_FRESHNESS_WINDOW_MS,
  describeProviderImageInputState,
  describeProviderSendState,
} from "../../../../shared/src/providerStatus";
import type { ResourceSearchMode } from "../../../../shared/src/resourceSearch";
import {
  scopedSettingsCapabilityTruth,
  selectScopedSettingsLastTest,
} from "../../../../shared/src/settingsCapabilityGovernance";
import {
  TRAINER_CUSTOM_SKILL_LIMIT,
  filterTrainerSkills,
  mergeSkillCatalog,
  normalizeTrainerCustomSkills,
  parseTrainerSkillShare,
  serializeTrainerSkillShare,
  trainerSkillCatalog,
  trainerSkillTriggerToken,
  type TrainerCustomSkill,
  type TrainerSkillContext,
} from "../../../../shared/src/skillCatalog";
import type { SettingsSectionStatus } from "../components/settings/CoachSettingsView";
import { resolveStarterSubjectFamily } from "../lib/courseTemplates";
import { appUiCopy } from "../lib/i18n/appUiCopy";
import type { Copy } from "../lib/i18n/copy";
import {
  recoverableFailureMessage,
  type OperationMessageSurface,
} from "../lib/operationMessageGovernance";
import {
  normalizeTeachingStyle,
  type ActiveWorkbenchView,
  type BootstrapData,
  type CoachAnswerMode,
  type CoachDefaults,
  type ComposerLanguage,
  type HostMessage,
  type TeachingStyle,
} from "../lib/types";
import { postMessage } from "../lib/vscode";
import {
  COACH_SETTINGS_AUTOSAVE_DELAY_MS,
  DEFAULT_ANSWER_MODE,
  DEFAULT_TEACHING_STYLE,
  buildLocalCommandSuggestions,
  buildSettingsFeedback,
  coachDefaultsStatusNote,
  compactDefinedValues,
  effectiveConnectionState,
  focusComposerInput,
  formatCoachDefaultsValue,
  formatContextBundleValue,
  formatSparseCoachDefaultsSavedValue,
  formatSparseWorkspaceControlValue,
  loadBrowserPreviewModule,
  localizeUiViewReferences,
  providerBlockingReason,
  providerHasVerifiedToolsProbe,
  providerModelRuntimeNote,
  providerSettingsLocale,
  type BrowserPreviewModule,
  type ComposerDeckKind,
  type LocalCommandSuggestion,
  type LocalSkillSuggestion,
  type OperationMessage,
  type SettingsActionState,
  type SettingsFeedbackState,
} from "./appHelpers";
import {
  blockedComposerSetupMessage,
  providerCoachBanner,
  providerSetupSummary,
} from "./providerRecoveryCopy";
import { buildProviderSettingsActions } from "./providerSettingsActions";
import type { ContextMenu } from "./useMenuState";
import type { ProviderDraft } from "../components/settings/CoachSettingsView";
import { useWorkbenchState } from "./useWorkbenchState";

type SyncCursorState = ReturnType<typeof useWorkbenchState.getState>["syncCursor"];
type WorkbenchLayoutState = ReturnType<typeof useWorkbenchState.getState>["layout"];

type ProviderSavePayload = Parameters<
  BrowserPreviewModule["saveBrowserPreviewProviderProfile"]
>[0];

export interface UseCoachSettingsStateParams {
  syncCursor: SyncCursorState;
  activeView: ActiveWorkbenchView;
  isBrowserPreview: boolean;
  setOperationMessage: (
    message?: TrainerOperationMessage,
    surface?: OperationMessageSurface,
  ) => void;
}

export function useCoachSettingsState({
  syncCursor,
  activeView,
  isBrowserPreview,
  setOperationMessage,
}: UseCoachSettingsStateParams) {
  const [settingsSectionRequest, setSettingsSectionRequest] = useState<{
    category: "teaching";
    requestId: number;
    skillTrigger?: string;
  }>();
  const [skillImportText, setSkillImportText] = useState("");
  const [settingsActionState, updateSettingsActionState] = useState<SettingsActionState>();
  const [settingsFeedbackState, setSettingsFeedbackState] = useState<SettingsFeedbackState>({});
  const settingsScopeKey = `${syncCursor.generation}\0${syncCursor.workspaceId}\0${syncCursor.sessionId}`;
  const settingsScopeRef = useRef(settingsScopeKey);
  const settingsActionScopeRef = useRef(settingsScopeKey);

  useEffect(() => {
    if (settingsScopeRef.current !== settingsScopeKey) {
      updateSettingsActionState(undefined);
      setSettingsFeedbackState({});
      settingsScopeRef.current = settingsScopeKey;
    }
  }, [settingsScopeKey]);

  const setSettingsActionState = useCallback(
    (next?: SettingsActionState) => {
      if (next) {
        settingsActionScopeRef.current = settingsScopeKey;
        setOperationMessage(undefined);
        updateSettingsActionState({ ...next, baselineMessageKey: undefined });
      } else {
        updateSettingsActionState(undefined);
      }
    },
    [setOperationMessage, settingsScopeKey],
  );

  const [companionInstallState, setCompanionInstallState] =
    useState<CompanionInstallState>("not_installed");
  const companionStateQueriedRef = useRef(false);

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

  return {
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
  };
}

export interface UseProviderReadinessStateParams {
  data: BootstrapData;
  composerLanguage: ComposerLanguage;
  activeView: ActiveWorkbenchView;
  workspaceAuthority: NonNullable<BootstrapData["memory"]["sandboxState"]>["authority"];
}

export function useProviderReadinessState({
  data,
  composerLanguage,
  activeView,
  workspaceAuthority,
}: UseProviderReadinessStateParams) {
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
        composerLanguage,
        providerTestClock,
      ),
    [data.providerConfig, scopedProviderLastTest, composerLanguage, providerTestClock],
  );

  const providerImageInputState = useMemo(
    () =>
      describeProviderImageInputState(
        { ...data.providerConfig, lastTestResult: scopedProviderLastTest },
        composerLanguage,
        providerTestClock,
      ),
    [data.providerConfig, scopedProviderLastTest, composerLanguage, providerTestClock],
  );

  const capabilityVerdict = useMemo(
    () =>
      deriveTrainerCapabilityVerdict({
        connectionState: data.connection.state,
        providerConfigured: data.providerConfig.configured,
        apiKeyConfigured: data.providerConfig.apiKeyConfigured,
        sendBlocked: providerSendState.blocked,
        lastTestOk: scopedProviderLastTest?.ok === true,
        capabilityTruth: scopedSettingsCapabilityTruth(data.providerConfig.lastTestResult, {
          workspaceId: settingsWorkspaceId,
          providerProfileId: data.providerConfig.profileId,
        }),
        imageProtocolSupported: providerImageInputState.supported,
        authority: workspaceAuthority,
        workspaceManaged: false,
        workspaceReadOnly: true,
      }),
    [
      data.connection.state,
      data.providerConfig,
      providerImageInputState.supported,
      providerSendState.blocked,
      scopedProviderLastTest,
      settingsWorkspaceId,
      workspaceAuthority,
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
      "en-US":
        "A formal plan needs a provider that supports tool calls. Choose and test a tools-capable provider in Settings.",
      "es-ES":
        "El plan formal necesita un proveedor con llamadas a herramientas. Elige y prueba uno compatible en Ajustes.",
      "fr-FR":
        "Le plan formel exige un fournisseur compatible avec les appels d'outils. Choisissez-en un et testez-le dans Réglages.",
      "de-DE":
        "Ein formeller Plan benötigt einen Provider mit Tool-Aufrufen. Wählen und testen Sie einen passenden Provider in Einstellungen.",
      "ja-JP":
        "正式な計画にはツール呼び出し対応の Provider が必要です。設定で対応 Provider を選び、テストしてください。",
      "ko-KR":
        "정식 계획에는 도구 호출을 지원하는 Provider가 필요합니다. 설정에서 지원 Provider를 선택하고 테스트하세요.",
      "pt-BR":
        "Um plano formal precisa de um provider com chamadas de ferramenta. Escolha e teste um provider compatível em Configurações.",
    };
    return messages[composerLanguage];
  }, [composerLanguage]);

  const chatToolsEvidence = scopedProviderLastTest?.capabilityEvidence?.find(
    (entry) => entry.name.trim().toLowerCase() === "tools",
  );
  const providerToolsExplicitlyUnsupported =
    (chatToolsEvidence?.state === "unsupported" ||
      chatToolsEvidence?.state === "disabled" ||
      scopedProviderLastTest?.toolsReady === false) &&
    data.providerConfig.capabilities?.tools !== true;

  const agentToolsCapabilityMessage = useMemo(() => {
    const messages: Record<ComposerLanguage, string> = {
      "zh-CN": "当前视图需要已经通过工具调用验证的 Provider。请在设置中选择并测试支持 tools 的连接。",
      "en-US":
        "This view needs a provider verified for tool calls. Choose and test a tools-capable connection in Settings.",
      "es-ES":
        "Esta vista necesita un provider verificado para llamadas de herramientas. Elige y prueba una conexión compatible con tools en Ajustes.",
      "fr-FR":
        "Cette vue nécessite un provider vérifié pour les appels d'outils. Choisissez et testez une connexion compatible dans Réglages.",
      "de-DE":
        "Diese Ansicht benötigt einen für Tool-Aufrufe verifizierten Provider. Wählen und testen Sie in Einstellungen eine passende Verbindung.",
      "ja-JP":
        "このビューには、ツール呼び出しを検証済みの Provider が必要です。設定で対応する接続を選び、テストしてください。",
      "ko-KR":
        "이 보기에는 도구 호출이 검증된 Provider가 필요합니다. 설정에서 tools를 지원하는 연결을 선택하고 테스트하세요.",
      "pt-BR":
        "Esta visualização precisa de um provider verificado para chamadas de ferramenta. Escolha e teste uma conexão compatível em Configurações.",
    };
    return messages[composerLanguage];
  }, [composerLanguage]);

  const providerBlockReason = useMemo(
    () => providerBlockingReason(data.providerConfig, composerLanguage, data.connection.state),
    [composerLanguage, data.connection.state, data.providerConfig],
  );

  const blockedComposerGuidance = useMemo(() => {
    const raw = blockedComposerSetupMessage(
      data.providerConfig,
      composerLanguage,
      activeView,
      data.connection.state,
    );
    return localizeUiViewReferences(raw, composerLanguage) ?? raw;
  }, [activeView, composerLanguage, data.connection.state, data.providerConfig]);

  const blockedCoachGuidance = useMemo(() => {
    const raw = blockedComposerSetupMessage(
      data.providerConfig,
      composerLanguage,
      "coach",
      data.connection.state,
    );
    return localizeUiViewReferences(raw, composerLanguage) ?? raw;
  }, [composerLanguage, data.connection.state, data.providerConfig]);

  const providerCoachNotice = useMemo(() => {
    const notice = providerCoachBanner(
      data.providerConfig,
      composerLanguage,
      data.connection.state,
      blockedCoachGuidance,
    );
    return notice
      ? {
          ...notice,
          message: localizeUiViewReferences(notice.message, composerLanguage) ?? notice.message,
        }
      : undefined;
  }, [blockedCoachGuidance, composerLanguage, data.connection.state, data.providerConfig]);

  const providerSetupState = useMemo(() => {
    const summary = providerSetupSummary(
      data.providerConfig,
      composerLanguage,
      data.connection.state,
    );
    return {
      title: localizeUiViewReferences(summary.title, composerLanguage) ?? summary.title,
      detail: localizeUiViewReferences(summary.detail, composerLanguage) ?? summary.detail,
      actionLabel:
        localizeUiViewReferences(summary.actionLabel, composerLanguage) ?? summary.actionLabel,
    };
  }, [composerLanguage, data.connection.state, data.providerConfig]);

  const displayConnectionState = effectiveConnectionState(data.connection.state);

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
  };
}

export interface UseCoachSettingsControllerParams {
  data: BootstrapData;
  layout: WorkbenchLayoutState;
  activeView: ActiveWorkbenchView;
  t: Copy;
  isBrowserPreview: boolean;
  previewSessionId: string | undefined;
  setPreviewSessionId: (sessionId?: string) => void;
  leftoverSettingsProfileRhythmNotLive: boolean;
  operationMessage: OperationMessage | undefined;
  setOperationMessage: (
    message?: TrainerOperationMessage,
    surface?: OperationMessageSurface,
  ) => void;
  settingsActionState: SettingsActionState | undefined;
  setSettingsActionState: (next?: SettingsActionState) => void;
  settingsFeedbackState: SettingsFeedbackState;
  setSettingsFeedbackState: Dispatch<SetStateAction<SettingsFeedbackState>>;
  setSettingsSectionRequest: Dispatch<
    SetStateAction<{ category: "teaching"; requestId: number; skillTrigger?: string } | undefined>
  >;
  skillImportText: string;
  setSkillImportText: Dispatch<SetStateAction<string>>;
  providerDraft: ProviderDraft;
  providerDraftHasChanges: boolean;
  providerDraftHasUnsavedApiKey: boolean;
  providerSavePayload: ProviderSavePayload;
  markProviderDraftSaved: () => void;
  applyHostMessage: (message: HostMessage, isProviderActionOverride?: boolean) => void;
  applyPreviewHostMessages: (messages: HostMessage[], isProviderAction?: boolean) => void;
  setActiveView: (view: ActiveWorkbenchView) => void;
  setComposerLanguage: (language: ComposerLanguage) => void;
  setComposerAnswerMode: (mode: CoachAnswerMode) => void;
  setContextDetail: (detail: "focused" | "balanced" | "full") => void;
  setIncludeCurrentFile: (enabled: boolean) => void;
  setIncludeSelection: (enabled: boolean) => void;
  setIncludeDiagnostics: (enabled: boolean) => void;
  setIncludeRelatedFiles: (enabled: boolean) => void;
  setFollowCurrentFile: (enabled: boolean) => void;
  setCoachDefaults: (patch: Partial<CoachDefaults>) => void;
  activeSkillDraft: string;
  composerUsesTrainingFlow: boolean;
  setActivityDraft: (value: string) => void;
  setComposerDraft: (value: string) => void;
  setDismissedComposerDeck: Dispatch<SetStateAction<ComposerDeckKind | undefined>>;
  setOpenMenu: Dispatch<SetStateAction<ContextMenu>>;
  setSelectedCommandIndex: Dispatch<SetStateAction<number>>;
}

export function useCoachSettingsController({
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
}: UseCoachSettingsControllerParams) {
  const workspaceSettings = data.memory.workspace;

  const defaultCoachDefaults = useMemo<CoachDefaults>(
    () => ({
      memoryScope: "project",
      workingSetMode: "balanced",
      reviewCadence: "steady",
      reviewReminderMode: "due",
      workspaceMemoryToggles: {
        decisions: true,
        patterns: true,
        resources: true,
      },
    }),
    [],
  );

  useEffect(() => {
    if (!settingsActionState) {
      return;
    }
    if (!operationMessage || operationMessage.tone === "info") {
      return;
    }
    const normalized = operationMessage.message.trim().toLowerCase();
    if (
      settingsActionState.baselineMessageKey &&
      normalized === settingsActionState.baselineMessageKey
    ) {
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
  }, [
    layout.composerLanguage,
    markProviderDraftSaved,
    operationMessage,
    setSettingsActionState,
    setSettingsFeedbackState,
    settingsActionState,
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
      data.providerConfig.configured,
      data.providerConfig.model,
      data.providerConfig.name,
      t.apiKeyMissing,
      t.apiKeySaved,
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
      buildSettingsFeedback(
        settingsActionState,
        operationMessage,
        layout.composerLanguage,
        "provider",
      ) ??
      (settingsActionState?.kind === "save-provider" &&
      settingsActionState.targets.includes("provider")
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
          : settingsActionState?.kind === "test-provider" &&
              settingsActionState.targets.includes("provider")
            ? {
                actionKind: "test-provider",
                tone: "pending" as const,
                ...copy.pending.test,
              }
            : settingsActionState?.kind === "clear-provider" &&
                settingsActionState.targets.includes("provider")
              ? {
                  tone: "pending" as const,
                  ...copy.pending.clear,
                }
              : settingsActionState?.kind === "open-config" &&
                  settingsActionState.targets.includes("provider")
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
      workingSetMode:
        liveWorkspaceCoachDefaults?.workingSetMode ?? defaultCoachDefaults.workingSetMode,
      reviewCadence:
        liveWorkspaceCoachDefaults?.reviewCadence ?? defaultCoachDefaults.reviewCadence,
      reviewReminderMode:
        liveWorkspaceCoachDefaults?.reviewReminderMode ?? defaultCoachDefaults.reviewReminderMode,
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
      buildSettingsFeedback(
        settingsActionState,
        operationMessage,
        layout.composerLanguage,
        "coachDefaults",
      ) ??
      (settingsActionState &&
      (settingsActionState.kind === "save-coach" ||
        settingsActionState.kind === "reset-defaults") &&
      settingsActionState.targets.includes("coachDefaults")
        ? {
            tone: "pending" as const,
            title: appUiCopy(
              layout.composerLanguage,
              settingsActionState.kind === "reset-defaults" ? "恢复中" : "保存中",
            ),
            detail: appUiCopy(
              layout.composerLanguage,
              "正在同步语言、回复方式、教学风格和教练默认策略。",
            ),
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
    const noteAnswerMode =
      coachDefaultsSaveState === "saved" ? savedAnswerMode : layout.composerAnswerMode;
    const noteTeachingStyle =
      coachDefaultsSaveState === "saved" ? savedTeachingStyle : layout.teachingStyle;

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
      feedback,
    };
  }, [
    data.profile.preferredStyle,
    defaultCoachDefaults,
    layout.coachDefaults,
    layout.composerAnswerMode,
    layout.composerLanguage,
    layout.teachingStyle,
    leftoverSettingsProfileRhythmNotLive,
    operationMessage,
    settingsActionState,
    settingsFeedbackState.coachDefaults,
    t,
    workspaceSettings,
  ]);

  const workspaceControlStatus = useMemo<SettingsSectionStatus>(() => {
    const savedValue = workspaceSettings
      ? formatSparseWorkspaceControlValue(workspaceSettings, t)
      : undefined;
    const effectiveValue = workspaceSettings
      ? formatContextBundleValue(
          {
            followCurrentFile: workspaceSettings.followCurrentFile ?? layout.followCurrentFile,
            contextDetail: workspaceSettings.contextDetail ?? layout.contextDetail,
            includeCurrentFile: workspaceSettings.includeCurrentFile ?? layout.includeCurrentFile,
            includeSelection: workspaceSettings.includeSelection ?? layout.includeSelection,
            includeDiagnostics: workspaceSettings.includeDiagnostics ?? layout.includeDiagnostics,
            includeRelatedFiles:
              workspaceSettings.includeRelatedFiles ?? layout.includeRelatedFiles,
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
      buildSettingsFeedback(
        settingsActionState,
        operationMessage,
        layout.composerLanguage,
        "workspaceControl",
      ) ??
      (settingsActionState &&
      (settingsActionState.kind === "save-coach" ||
        settingsActionState.kind === "reset-defaults") &&
      settingsActionState.targets.includes("workspaceControl")
        ? {
            tone: "pending" as const,
            title: appUiCopy(
              layout.composerLanguage,
              settingsActionState.kind === "reset-defaults" ? "恢复中" : "保存中",
            ),
            detail: appUiCopy(layout.composerLanguage, "正在写入这组工作区上下文控制。"),
          }
        : undefined) ??
      settingsFeedbackState.workspaceControl;

    return {
      saveState: workspaceSettings ? (isSaved ? "saved" : "unsaved") : "empty",
      effectiveValue,
      savedValue: savedValue ?? appUiCopy(layout.composerLanguage, "工作区未单独覆盖"),
      editingValue: isSaved ? undefined : effectiveValue,
      note: appUiCopy(
        layout.composerLanguage,
        "这些开关现在就会影响发送，但保存后工作区重开仍会保持。",
      ),
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

  const localCommandMap = useMemo(() => {
    const reportLocalCommand = (message: string) => {
      setOperationMessage({ tone: "success", message });
    };
    const commands = buildLocalCommandSuggestions({
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
    });
    return new Map<string, LocalCommandSuggestion>(
      commands.map((command) => [command.id, command]),
    );
  }, [
    layout.composerLanguage,
    setActiveView,
    setComposerAnswerMode,
    setComposerLanguage,
    setContextDetail,
    setFollowCurrentFile,
    setIncludeCurrentFile,
    setIncludeDiagnostics,
    setIncludeRelatedFiles,
    setIncludeSelection,
    setOperationMessage,
    t,
  ]);

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
      data.liveContext.relatedFiles.length,
      data.liveContext.selectionRange,
      data.resources.length,
      data.workspaceTrainingState?.skillProjection,
    ],
  );

  const customSkills = useMemo(
    () => layout.coachDefaults.customSkills ?? [],
    [layout.coachDefaults.customSkills],
  );
  const availableSkillCatalog = useMemo(() => mergeSkillCatalog(customSkills), [customSkills]);
  const composerMenuSkills = useMemo(
    () =>
      filterTrainerSkills(
        "$",
        trainerSkillContext,
        availableSkillCatalog.length,
        availableSkillCatalog,
      ),
    [availableSkillCatalog, trainerSkillContext],
  );

  const persistCoachSettings = useCallback(
    (
      overrides?: Partial<{
        responseLanguage: ComposerLanguage;
        answerMode: CoachAnswerMode;
        resourceSearchMode: ResourceSearchMode;
        teachingStyle: TeachingStyle;
        coachDefaults: CoachDefaults;
        followCurrentFile: boolean;
        contextDetail: "focused" | "balanced" | "full";
        includeCurrentFile: boolean;
        includeSelection: boolean;
        includeDiagnostics: boolean;
        includeRelatedFiles: boolean;
      }>,
    ) => {
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

      const savedWorkspaceSettings = data.memory.workspace;
      const savedTeachingStyle = data.profile.preferredStyle.trim()
        ? normalizeTeachingStyle(data.profile.preferredStyle)
        : undefined;
      const matchesSavedSettings = Boolean(
        savedWorkspaceSettings &&
          payload.responseLanguage === savedWorkspaceSettings.responseLanguage &&
          payload.answerMode === savedWorkspaceSettings.answerMode &&
          payload.resourceSearchMode === savedWorkspaceSettings.resourceSearchMode &&
          (savedTeachingStyle === undefined
            ? payload.teachingStyle === DEFAULT_TEACHING_STYLE
            : payload.teachingStyle === savedTeachingStyle) &&
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

      setSettingsActionState({
        kind: "save-coach",
        targets: ["coachDefaults", "workspaceControl"],
      });

      if (isBrowserPreview) {
        void loadBrowserPreviewModule()
          .then((browserPreview) =>
            browserPreview.saveBrowserPreviewCoachSettings(payload, previewSessionId),
          )
          .then(({ sessionId, message }) => {
            setPreviewSessionId(sessionId);
            applyHostMessage(message);
            setOperationMessage({
              tone: "success",
              message: appUiCopy(payload.responseLanguage, "已保存教练默认设置。"),
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

      postMessage({
        type: "settings/saveCoach",
        payload,
      });
    },
    [
      applyHostMessage,
      data.memory.workspace,
      data.profile.preferredStyle,
      isBrowserPreview,
      layout.coachDefaults,
      layout.composerAnswerMode,
      layout.composerLanguage,
      layout.contextDetail,
      layout.followCurrentFile,
      layout.includeCurrentFile,
      layout.includeDiagnostics,
      layout.includeRelatedFiles,
      layout.includeSelection,
      layout.resourceSearchMode,
      layout.teachingStyle,
      previewSessionId,
      setOperationMessage,
      setPreviewSessionId,
      setSettingsActionState,
    ],
  );

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

  const selectSkillSuggestion = useCallback(
    (skill: LocalSkillSuggestion, preserveDraft = false) => {
      const triggerToken = trainerSkillTriggerToken(activeSkillDraft);
      const remainder =
        triggerToken !== undefined
          ? activeSkillDraft.slice(triggerToken.length).trim()
          : preserveDraft
            ? activeSkillDraft
            : "";
      const nextValue = remainder ? `${skill.trigger} ${remainder}` : `${skill.trigger} `;
      if (composerUsesTrainingFlow) {
        setActivityDraft(nextValue);
      } else {
        setComposerDraft(nextValue);
      }
      setDismissedComposerDeck("skill");
      setOpenMenu(undefined);
      setSelectedCommandIndex(0);
      window.requestAnimationFrame(() => {
        focusComposerInput();
      });
    },
    [
      activeSkillDraft,
      composerUsesTrainingFlow,
      setActivityDraft,
      setComposerDraft,
      setDismissedComposerDeck,
      setOpenMenu,
      setSelectedCommandIndex,
    ],
  );

  const persistCustomSkills = useCallback(
    (next: TrainerCustomSkill[]) => {
      setCoachDefaults({ customSkills: normalizeTrainerCustomSkills(next) });
      queueCoachSettingsSave();
    },
    [queueCoachSettingsSave, setCoachDefaults],
  );

  const installCustomSkillFromPaste = useCallback(() => {
    const skill = parseTrainerSkillShare(skillImportText);
    if (!skill) {
      setOperationMessage({
        tone: "error",
        message: appUiCopy(layout.composerLanguage, "粘贴的内容不是有效的技能分享包。"),
      });
      return;
    }
    const builtinCollision = trainerSkillCatalog.some(
      (entry) => entry.trigger.toLowerCase() === skill.trigger.toLowerCase(),
    );
    if (builtinCollision) {
      setOperationMessage({
        tone: "error",
        message: appUiCopy(layout.composerLanguage, "{v} 与内置技能冲突，未安装。").replace(
          "{v}",
          skill.trigger,
        ),
      });
      return;
    }
    const remaining = customSkills.filter(
      (entry: TrainerCustomSkill) => entry.trigger.toLowerCase() !== skill.trigger.toLowerCase(),
    );
    if (remaining.length >= TRAINER_CUSTOM_SKILL_LIMIT) {
      setOperationMessage({
        tone: "error",
        message: appUiCopy(
          layout.composerLanguage,
          "最多只能有 {v} 个自定义技能，先删除一个。",
        ).replace("{v}", String(TRAINER_CUSTOM_SKILL_LIMIT)),
      });
      return;
    }
    persistCustomSkills([...remaining, skill]);
    setSkillImportText("");
    setOperationMessage({
      tone: "success",
      message: appUiCopy(layout.composerLanguage, "已安装 {v}。").replace("{v}", skill.trigger),
    });
  }, [
    customSkills,
    layout.composerLanguage,
    persistCustomSkills,
    setOperationMessage,
    setSkillImportText,
    skillImportText,
  ]);

  const copyCustomSkillShare = useCallback(
    async (skill: TrainerCustomSkill) => {
      try {
        await navigator.clipboard.writeText(serializeTrainerSkillShare(skill));
        setOperationMessage({
          tone: "success",
          message: appUiCopy(
            layout.composerLanguage,
            "{v} 分享包已复制，可粘贴给其他工作区。",
          ).replace("{v}", skill.trigger),
        });
      } catch {
        setOperationMessage({
          tone: "error",
          message: appUiCopy(layout.composerLanguage, "复制失败，请重试。"),
        });
      }
    },
    [layout.composerLanguage, setOperationMessage],
  );

  const openSkillSettings = useCallback(
    (skillTrigger?: string) => {
      setSettingsSectionRequest({ category: "teaching", requestId: Date.now(), skillTrigger });
      setActiveView("settings");
    },
    [setActiveView, setSettingsSectionRequest],
  );

  const useProviderTemplateByLabel = useCallback(
    (templateLabel: string) => {
      setSettingsActionState({
        kind: "save-provider",
        targets: ["provider"],
      });
      if (isBrowserPreview) {
        void loadBrowserPreviewModule()
          .then((browserPreview) =>
            browserPreview.useBrowserPreviewProviderTemplate(templateLabel, previewSessionId),
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
    },
    [
      applyPreviewHostMessages,
      isBrowserPreview,
      layout.composerLanguage,
      previewSessionId,
      setOperationMessage,
      setPreviewSessionId,
      setSettingsActionState,
    ],
  );

  const saveProviderDraft = useCallback(() => {
    setSettingsActionState({
      kind: "save-provider",
      targets: ["provider"],
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
  }, [
    applyPreviewHostMessages,
    isBrowserPreview,
    layout.composerLanguage,
    previewSessionId,
    providerSavePayload,
    setOperationMessage,
    setPreviewSessionId,
    setSettingsActionState,
  ]);

  const providerSettingsActions = useMemo(
    () =>
      buildProviderSettingsActions({
        language: layout.composerLanguage,
        isBrowserPreview,
        previewSessionId,
        providerSavePayload,
        providerDraftHasChanges,
        providerConfigured: data.providerConfig.configured,
        setSettingsActionState,
        setPreviewSessionId,
        applyPreviewHostMessages,
        persistCoachSettings,
        defaultCoachDefaults,
      }),
    [
      applyPreviewHostMessages,
      data.providerConfig.configured,
      defaultCoachDefaults,
      isBrowserPreview,
      layout.composerLanguage,
      persistCoachSettings,
      previewSessionId,
      providerDraftHasChanges,
      providerSavePayload,
      setPreviewSessionId,
      setSettingsActionState,
    ],
  );

  const cancelProviderTest = useCallback(() => {
    const requestId = settingsActionState?.requestId;
    if (requestId && !isBrowserPreview) {
      postMessage({
        type: "provider/cancelTest",
        payload: { requestId },
      });
    }
    setSettingsActionState(undefined);
  }, [isBrowserPreview, setSettingsActionState, settingsActionState?.requestId]);

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
  };
}
