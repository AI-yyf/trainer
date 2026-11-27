import { sanitizeErrorSurfaceText } from "../../../../../shared/src/errorSurfaceSanitizer";
import type { ProviderModelTokenLimit } from "../../../../../shared/src/models";
import {
  evaluateProviderModelPolicy
} from "../../../../../shared/src/providerModelPolicy";
import {
  readProviderModelTokenLimit,
  withProviderModelTokenLimit
} from "../../../../../shared/src/providerModelTokenLimits";
import {
  PROVIDER_TEMPLATE_GROUP_ORDER,
  PROVIDER_TEMPLATE_GROUPS,
  PROVIDER_TEMPLATE_LABELS
} from "../../../../../shared/src/providerTemplateCatalog";
import { type SettingsSectionId } from "../../templates/SettingsIndex";
import { SystemState } from "../../templates/SystemState";
import { templateCopy } from "../../templates/templateCopy";
import {
  ChoiceList,
  SimpleInfoRow
} from "./SettingsControls";

import { LANGUAGE_LABELS } from "../../../../../shared/src";
import { ActionButton } from "../common";
import { ChevronDownIcon,ComposeIcon,PlayIcon,PlusIcon,TrashIcon } from "../icons";
import { DataFolderIcon,DoneIcon,ReloadIcon } from "../icons/inline";
import { CoachNavIcon } from "../icons/navigation/primaryNav";
import { SettingsConnectionIcon,SettingsPreferencesIcon,SettingsTeachingIcon,SettingsWorkspaceIcon } from "../icons/navigation/settingsNav";
import { StatusPill } from "../StatusPill";
import {
  adaptiveBehaviorLabel,
  compactSummaryValue,
  formatRequestDefaultsDraft,
  formatTokenValue,
  mergeDraftStringList,
  modelPolicyHint,
  parseDraftStringList,
  parsePositiveIntegerInput,
  providerTemplateGroupLabel,
  settingsPhrase,
  settingsStatusPhrase,
  shortenSummary
} from "./coachSettingsHelpers";
import { settingsText } from "./settingsText";

import type { CoachSettingsCoreState } from "./useCoachSettingsSheetController";

export function buildCoachSettingsConnectionNodes(core: CoachSettingsCoreState) {
  const {
    providerDraft,
    onProviderDraftChange,
    onResetProviderDraft,
    providerStatus,
    coachDefaultsStatus,
    onSaveProvider,
    onSaveProviderProfile,
    providerSaveBusy,
    onUseProviderTemplateLabel,
    onRefreshProviderProfiles,
    onSwitchProviderProfile,
    onTestProvider,
    onCancelProviderTest,
    onClearProvider,
    onOpenConfig,
    provider,
    trainerWorkspace,
    remoteWorkspaceName,
    language,
    answerMode,
    teachingStyle,
    followCurrentFile,
    learnerName,
    targetProject,
    preferredRhythm,
    preferredLearningMode,
    onboardingRequest,
    projectContext,
    onNavigateToView,
    onTrustWindow,
    onChooseTrainerWorkspaceRoot,
    copy,
    settingsGlobalCopy,
    providerDirectoryRef,
    providerTemplatesRef,
    connectionView,
    setConnectionView,
    setModelPickerOpen,
    settingsIndexOpen,
    activeSettingsCategory,
    providerTestPending,
    providerTestPassed,
    coachSendState,
    resolvedWorkspaceTrustState,
    providerSaved,
    providerCoachReady,
    providerNeedsApiKey,
    teachingStyleItems,
    backendStarting,
    backendUnavailable,
    backendRecovery,
    providerCredentialsRejected,
    lastTestLabel,
    providerHasDraftChanges,
    providerDraftHasApiKey,
    providerDraftCanReuseSavedApiKey,
    providerSummaryText,
    runtimeSummaryText,
    coachStateSummaryText,
    providerRequirementNote,
    canUseSavedModelMetadata,
    draftModelTokenLimits,
    liveModelTokenLimits,
    draftCatalogModels,
    draftRequestDefaults,
    currentDraftModel,
    currentLiveModel,
    applyModelAdaptation,
    draftModelPolicy,
    currentDraftModelPolicyMessage,
    modelSearchQuery,
    resetModelPickerSearch,
    exactMatchingModel,
    canUseTypedModel,
    modelLimitNames,
    manualModelDraft,
    setManualModelDraft,
    requestDefaultsText,
    setRequestDefaultsText,
    requestDefaultsError,
    requestDefaultsFocusedRef,
    manualModelPolicy,
    manualModelBlockedByPolicy,
    modelPickerCopy,
    discoveredModelSet,
    modelLimitKeySet,
    canAddManualModel,
    liveContextWindowTokens,
    liveMaxOutputTokens,
    draftContextWindowTokens,
    draftMaxOutputTokens,
    providerProfiles,
    canSaveProviderProfile,
    localizedProviderProfilesLabel,
    localizedProviderDirectoryLabel,
    localizedRefreshProfilesLabel,
    localizedSaveProfileLabel,
    localizedSaveProfileDetail,
    localizedPerModelLimitsLabel,
    localizedPerModelLimitsDetail,
    localizedUseModelLabel,
    localizedCurrentModelLabel,
    localizedModelLimitEmpty,
    localizedCatalogPanelLabel,
    localizedCatalogPanelDetail,
    localizedCatalogAllowedModelsLabel,
    localizedCatalogDeniedModelsLabel,
    localizedCatalogEmbeddingModelLabel,
    localizedCatalogRequestDefaultsLabel,
    localizedCatalogSourceLabel,
    localizedCatalogCacheTtlLabel,
    localizedAdvancedRoutingLabel,
    localizedAdvancedRoutingDetail,
    localizedCredentialModeLabel,
    localizedCredentialModeUiProxy,
    localizedCredentialModeWorkspaceSecret,
    localizedAllowedModelsInputDetail,
    localizedDeniedModelsInputDetail,
    localizedEmbeddingModelPlaceholder,
    localizedCacheTtlDetail,
    localizedManualModelLabel,
    localizedManualModelPlaceholder,
    localizedManualModelButton,
    localizedManualModelHint,
    localizedRequestDefaultsInputDetail,
    localizedRequestDefaultsInputHint,
    modelCardCopy,
    localizedModelOriginLive,
    localizedModelOriginManual,
    localizedClearModelLimitsLabel,
    providerCatalogRows,
    providerCatalogSummary,
    draftCredentialMode,
    draftCatalogSource,
    draftCacheTtlSeconds,
    draftEmbeddingModel,
    draftAllowedModelsSource,
    draftDeniedModelsSource,
    allowedModelsText,
    setAllowedModelsText,
    allowedModelsFocusedRef,
    deniedModelsText,
    setDeniedModelsText,
    deniedModelsFocusedRef,
    handleRequestDefaultsTextChange,
    canSaveProviderConnection,
    saveProviderConnectionLabel,
    saveProviderConnectionTitle,
    providerSetupChecks,
    canRetestProvider,
    availabilityMode,
    shouldRoutePrimaryToSavedProfiles,
    showProviderDetailActions,
    workspaceRootMissing,
    resolvedAvailabilityTone,
    localizedResolvedAvailabilityStatusLabel,
    localizedResolvedAvailabilityDetail,
    openProviderApiKey,
    showConnectionForm,
    providerIdentityListVisible,
    showConnectionSummary,
    showProviderTemplates,
    connectionHost,
    focusDraftModelPicker,
    displayAvailabilityHeadline,
    displayAvailabilityDetail,
    showAvailabilityPrimaryAction,
    effectiveAvailabilityPrimaryCta,
    effectiveAvailabilityPrimaryTone,
    connectionTestFailed,
    connectionReadyForUse,
    connectionModelFull,
    connectionModelLimitSummary,
    connectionModelSummary,
    connectionSummaryStatusLabel,
    connectionSummaryNote,
  } = core;

  const connectionSummaryCard = showConnectionSummary ? (
    <div className="settings-connection-summary">
      <div className="settings-connection-summary__main">
        <div className="settings-connection-summary__eyebrow">
          <span className="settings-connection-summary__provider">
            {provider.profileLabel?.trim() || provider.name?.trim() || copy.provider}
          </span>
          <StatusPill tone={resolvedAvailabilityTone}>{connectionSummaryStatusLabel}</StatusPill>
        </div>
        <div className="settings-connection-summary__identity">
          <span
            className="settings-connection-summary__dot"
            data-state={resolvedAvailabilityTone}
            aria-hidden="true"
          />
          <strong className="settings-connection-summary__model" title={provider.model || ""}>
            {connectionModelFull}
          </strong>
        </div>
        <div className="settings-connection-summary__meta">
          {connectionHost ? (
            <span className="settings-connection-summary__host" title={provider.baseUrl}>
              {connectionHost}
            </span>
          ) : null}
          {connectionHost && connectionSummaryNote ? <span aria-hidden="true">·</span> : null}
          {connectionSummaryNote ? (
            <span className="settings-connection-summary__note-inline">{connectionSummaryNote}</span>
          ) : null}
        </div>
      </div>
      <div className="settings-actions settings-actions--compact">
        {connectionReadyForUse && onNavigateToView ? (
          <ActionButton
            fullWidth={false}
            icon={<CoachNavIcon size={14} />}
            label={settingsText(language, "去对话", "Go to Chat")}
            detail={settingsText(
              language,
              "直接开始使用；第一次真实发送会确认连接。",
              "Start using it now; the first real send confirms the connection.",
            )}
            ariaLabel={settingsText(language, "去对话", "Go to Chat")}
            onClick={() => onNavigateToView("coach")}
          />
        ) : showAvailabilityPrimaryAction ? (
          <ActionButton
            fullWidth={false}
            icon={effectiveAvailabilityPrimaryCta.icon}
            label={effectiveAvailabilityPrimaryCta.label}
            detail={effectiveAvailabilityPrimaryCta.detail}
            ariaLabel={effectiveAvailabilityPrimaryCta.label}
            onClick={effectiveAvailabilityPrimaryCta.action}
            disabled={!effectiveAvailabilityPrimaryCta.action}
            title={effectiveAvailabilityPrimaryCta.detail}
          />
        ) : null}
        <ActionButton
          fullWidth={false}
          icon={<ComposeIcon size={14} />}
          label={settingsPhrase(language, "editConfiguration")}
          ariaLabel={settingsPhrase(language, "editConfiguration")}
          detail={settingsPhrase(language, "editConfigurationDetail")}
          onClick={() => setConnectionView("edit")}
        />
      </div>
      <div className="settings-connection-model">
        <div className="settings-connection-model__copy">
          <span className="settings-connection-model__label">
            {settingsText(language, "聊天模型", "Chat model")}
          </span>
          <strong className="settings-connection-model__value" title={connectionModelFull}>
            {connectionModelFull}
          </strong>
          {connectionModelLimitSummary ? (
            <span className="settings-connection-model__limits">{connectionModelLimitSummary}</span>
          ) : null}
        </div>
        <button
          type="button"
          className="settings-connection-model__change"
          onClick={focusDraftModelPicker}
        >
          {settingsText(language, "更换模型", "Change model")}
        </button>
      </div>
      {providerSaved &&
      (onTestProvider || onSaveProviderProfile || onUseProviderTemplateLabel) ? (
        <details className="settings-connection-summary__manage">
          <summary>
            <span>{settingsText(language, "管理连接", "Manage connection")}</span>
            <ChevronDownIcon size={12} />
          </summary>
          <div className="settings-connection-summary__manage-actions">
            {providerTestPending && onCancelProviderTest ? (
              <button
                type="button"
                className="settings-connection-summary__link"
                onClick={onCancelProviderTest}
              >
                {settingsText(language, "取消测试", "Cancel test")}
              </button>
            ) : null}
            {connectionReadyForUse && canRetestProvider && onTestProvider ? (
              <button
                type="button"
                className="settings-connection-summary__link"
                onClick={onTestProvider}
              >
                {providerTestPassed || connectionTestFailed ? <ReloadIcon size={12} /> : <PlayIcon size={12} />}
                {providerTestPassed || connectionTestFailed
                  ? settingsText(language, "重新测试连接", "Test connection again")
                  : settingsText(language, "测试连接（可选）", "Test connection (optional)")}
              </button>
            ) : null}
            {providerProfiles.length <= 1 && canSaveProviderProfile && onSaveProviderProfile ? (
              <button
                type="button"
                className="settings-connection-summary__link"
                onClick={onSaveProviderProfile}
              >
                <PlusIcon size={12} />
                {localizedSaveProfileLabel}
              </button>
            ) : null}
            {providerProfiles.length <= 1 && onUseProviderTemplateLabel ? (
              <button
                type="button"
                className="settings-connection-summary__link"
                onClick={() => setConnectionView("add")}
              >
                <PlusIcon size={12} />
                {settingsPhrase(language, "addProvider")}
              </button>
            ) : null}
          </div>
        </details>
      ) : null}
    </div>
  ) : null;
  const showAvailabilityChecklist =
    providerHasDraftChanges || (!providerCoachReady && !shouldRoutePrimaryToSavedProfiles);
  const renderProviderSetupChecks = (className: string) => (
    <div
      className={`settings-setup-checks ${className}`.trim()}
      aria-label={settingsPhrase(language, "connectionChecklist")}
    >
      {providerSetupChecks.map((item) => (
        <div key={item.id} className={`settings-setup-check is-${item.state}`}>
          <span className="settings-setup-check__dot" aria-hidden="true" />
          <span className="settings-setup-check__label">{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  );
  const coachSettingsSaving = coachDefaultsStatus?.feedback?.tone === "pending";
  const coachSettingsSavedRecently = coachDefaultsStatus?.feedback?.tone === "pass";
  const coachSettingsSaveFailure =
    coachDefaultsStatus?.feedback?.tone === "fail" ? coachDefaultsStatus.feedback : undefined;
  // Save-on-change has no Save button to hang feedback on, so the header
  // carries a live status: saving → saved, or the sanitized failure detail.
  const coachSettingsAutosaveNode = (
    <span
      className={`settings-autosave${
        coachSettingsSaving
          ? " is-saving"
          : coachSettingsSaveFailure
            ? " is-failed"
            : coachSettingsSavedRecently
              ? " is-saved"
              : ""
      }`}
      role="status"
      aria-live="polite"
      data-settings-autosave={
        coachSettingsSaving
          ? "saving"
          : coachSettingsSaveFailure
            ? "failed"
            : coachSettingsSavedRecently
              ? "saved"
              : "idle"
      }
    >
      {coachSettingsSaving
        ? settingsGlobalCopy.settingsAutosaving
        : coachSettingsSaveFailure
          ? `${coachSettingsSaveFailure.title}${
              coachSettingsSaveFailure.detail
                ? ` · ${sanitizeErrorSurfaceText(coachSettingsSaveFailure.detail)}`
                : ""
            }`
          : coachSettingsSavedRecently
            ? settingsGlobalCopy.settingsAutosaved
            : ""}
    </span>
  );
  // An unsaved *empty* draft differs from the empty config only in defaults;
  // only count it as dirty once the user has actually typed something.
  const connectionDirty =
    providerStatus?.saveState === "unsaved" &&
    (providerSaved ||
      Boolean(providerDraft.baseUrl.trim() || providerDraft.apiKey.trim() || providerDraft.model.trim()));
  const settingsNavItems = [
    {
      id: "connection",
      label: settingsGlobalCopy.settingsSectionConnection,
      dirty: connectionDirty,
      icon: <SettingsConnectionIcon size={18} active={activeSettingsCategory === "connection"} />,
    },
    {
      id: "workspace",
      label: settingsPhrase(language, "navWorkspace"),
      dirty: false,
      icon: <SettingsWorkspaceIcon size={18} active={activeSettingsCategory === "workspace"} />,
    },
    {
      id: "teaching",
      label: templateCopy[language].coach,
      dirty: false,
      icon: <SettingsTeachingIcon size={18} active={activeSettingsCategory === "teaching"} />,
    },
    {
      id: "preferences",
      label: settingsGlobalCopy.settingsPreferences,
      dirty: false,
      icon: <SettingsPreferencesIcon size={18} active={activeSettingsCategory === "preferences"} />,
    },
  ] as const;
  const settingsStatusConnectionReady = providerCoachReady && !providerHasDraftChanges;
  // Blocker banner — one row per real problem, each with the action that
  // clears it. Same truth sources as the availability strip; hidden when
  // nothing is wrong so healthy Settings opens straight on the content.
  const settingsStatusIssues: Array<{
    id: "key" | "test" | "trust" | "unsaved";
    label: string;
    target: SettingsSectionId;
    action?: () => void;
  }> = [];
  if (providerNeedsApiKey || coachSendState.reasonKind === "missing_api_key") {
    settingsStatusIssues.push({
      id: "key",
      label: settingsGlobalCopy.settingsStatusNoApiKey,
      target: "connection",
      action: openProviderApiKey,
    });
  } else if (providerSaved && !providerTestPassed && !showConnectionSummary) {
    settingsStatusIssues.push({
      id: "test",
      label: settingsGlobalCopy.settingsStatusNeedsTest,
      target: "connection",
    });
  }
  if (resolvedWorkspaceTrustState !== "trusted") {
    settingsStatusIssues.push({
      id: "trust",
      label: settingsGlobalCopy.settingsStatusTrust,
      target: "workspace",
      action: onTrustWindow,
    });
  }
  if (connectionDirty) {
    const keyIssue = settingsStatusIssues.find(issue => issue.id === "key");
    if (keyIssue) {
      keyIssue.label = `${keyIssue.label} · ${settingsGlobalCopy.settingsStatusUnsaved}`;
    } else {
      settingsStatusIssues.push({
        id: "unsaved",
        label: settingsGlobalCopy.settingsStatusUnsaved,
        target: "connection",
        action: () => setConnectionView("edit"),
      });
    }
  }
  // De-duplication: the blocker bar at the top of the detail body is the
  // single actionable issue list. When it is visible alongside the strip
  // (detail pane only — the index hides the bar), the strip drops its action
  // button so it repeats none of the per-issue actions; the form-level Test
  // button renders instead (showProviderDetailTestAction below). The strip
  // keeps the full connection explanation. Backend recovery keeps its full
  // strip: the blocker bar has no row for it.
  const availabilityStripReduced =
    !settingsIndexOpen &&
    !backendRecovery &&
    settingsStatusIssues.some((issue) => issue.target === "connection");
  // A section only shows the blockers that belong to it. Trust lives in
  // Workspace, so a healthy model connection no longer opens under a wall of
  // workspace-permission copy.
  const visibleSettingsStatusIssues = settingsStatusIssues.filter(
    (issue) =>
      issue.target === activeSettingsCategory &&
      !(issue.id === "unsaved" && connectionView === "edit"),
  );
  const coachBehaviorSummary = shortenSummary(
    compactSummaryValue(
      answerMode === "auto" && teachingStyle === "auto"
        ? [LANGUAGE_LABELS[language], copy.auto]
        : [
            LANGUAGE_LABELS[language],
            answerMode === "auto"
              ? adaptiveBehaviorLabel(language, "answer")
              : answerMode === "coach-first"
                ? copy.coachFirst
                : answerMode === "balanced"
                  ? copy.balanced
                  : copy.direct,
            teachingStyle === "auto"
              ? adaptiveBehaviorLabel(language, "teaching")
              : teachingStyleItems.find((item) => item.value === teachingStyle)?.label ?? copy.auto,
          ],
      copy.off,
    ),
    36,
  );
  const contextBehaviorSummary = followCurrentFile ? copy.followCurrentFile : copy.currentFile;
  const runtimeFlowSummary = `${runtimeSummaryText}${coachStateSummaryText ? ` · ${coachStateSummaryText}` : ""}`;
  const rememberedRows = [
    learnerName
      ? { label: settingsPhrase(language, "name"), value: learnerName }
      : null,
    targetProject
      ? { label: settingsPhrase(language, "project"), value: targetProject }
      : null,
    preferredLearningMode
      ? { label: settingsPhrase(language, "coachingMode"), value: preferredLearningMode }
      : null,
    preferredRhythm
      ? { label: settingsPhrase(language, "rhythm"), value: preferredRhythm }
      : null,
    onboardingRequest
      ? { label: settingsPhrase(language, "thisRound"), value: onboardingRequest }
      : null,
    projectContext && projectContext !== targetProject
      ? { label: settingsPhrase(language, "context"), value: projectContext }
      : null,
  ].filter(Boolean) as Array<{ label: string; value: string }>;
  const remembersSummary = rememberedRows.length
    ? shortenSummary(
        rememberedRows
          .slice(0, 2)
          .map((row) => `${row.label}: ${row.value}`)
          .join(" · "),
        72,
      )
    : undefined;
  const updateDraftModelTokenLimit = (
    modelName: string,
    patch: Partial<ProviderModelTokenLimit>,
  ) => {
    const normalizedModel = modelName.trim();
    if (!normalizedModel || !evaluateProviderModelPolicy(normalizedModel, draftModelPolicy).allowed) {
      return;
    }
    const currentLimit =
      normalizedModel === currentDraftModel
        ? {
            contextWindowTokens: draftContextWindowTokens,
            maxOutputTokens: draftMaxOutputTokens,
          }
        : readProviderModelTokenLimit(draftModelTokenLimits, normalizedModel);
    const nextModelTokenLimits = withProviderModelTokenLimit(draftModelTokenLimits, normalizedModel, {
      ...currentLimit,
      ...patch,
    });
    if (normalizedModel === currentDraftModel) {
      onProviderDraftChange({
        contextWindowTokens:
          "contextWindowTokens" in patch ? patch.contextWindowTokens : draftContextWindowTokens,
        maxOutputTokens: "maxOutputTokens" in patch ? patch.maxOutputTokens : draftMaxOutputTokens,
        modelTokenLimits: nextModelTokenLimits,
      });
      return;
    }
    onProviderDraftChange({ modelTokenLimits: nextModelTokenLimits });
  };
  const clearDraftModelTokenLimit = (modelName: string) => {
    const normalizedModel = modelName.trim();
    if (!normalizedModel || !evaluateProviderModelPolicy(normalizedModel, draftModelPolicy).allowed) {
      return;
    }
    const nextModelTokenLimits = withProviderModelTokenLimit(
      draftModelTokenLimits,
      normalizedModel,
      undefined,
    );
    if (normalizedModel === currentDraftModel) {
      onProviderDraftChange({
        contextWindowTokens: undefined,
        maxOutputTokens: undefined,
        modelTokenLimits: nextModelTokenLimits,
      });
      return;
    }
    onProviderDraftChange({
      modelTokenLimits: nextModelTokenLimits,
    });
  };
  const removeDraftCatalogModel = (modelName: string) => {
    const normalizedModel = modelName.trim().toLowerCase();
    if (!normalizedModel || !evaluateProviderModelPolicy(normalizedModel, draftModelPolicy).allowed) {
      return;
    }
    onProviderDraftChange({
      catalogModels: draftCatalogModels.filter((entry) => entry.trim().toLowerCase() !== normalizedModel),
    });
  };
  const handleAddManualModel = () => {
    const model = manualModelDraft.trim();
    const modelPolicy = evaluateProviderModelPolicy(model, draftModelPolicy);
    if (
      !model ||
      !modelPolicy.allowed ||
      modelLimitKeySet.has(model.toLowerCase())
    ) {
      return;
    }
    onProviderDraftChange({
      catalogModels: mergeDraftStringList(draftCatalogModels, model),
      model,
    });
    setManualModelDraft("");
  };
  const handleUseTypedModel = () => {
    const model = exactMatchingModel ?? modelSearchQuery.trim();
    if (!model || !canUseTypedModel) {
      return;
    }
    onProviderDraftChange({
      ...(exactMatchingModel
        ? {}
        : { catalogModels: mergeDraftStringList(draftCatalogModels, model) }),
    });
    applyModelAdaptation(model);
    resetModelPickerSearch();
    setModelPickerOpen(false);
  };
  const providerModelLimitsPanel = (
    <details className="settings-sheet__minor-panel settings-sheet__model-limits-panel">
      <summary>
        {localizedPerModelLimitsLabel} <span aria-hidden="true">·</span>{" "}
        <span className="settings-section-count">{modelLimitNames.length}</span>
      </summary>
      <div className="settings-sheet__minor-body settings-model-limits-panel">
        <p className="settings-sheet__note settings-sheet__note--compact">
          {localizedPerModelLimitsDetail}
        </p>
        <div className="settings-model-limit-toolbar">
          <label className="settings-field settings-field--dense settings-model-limit-toolbar__field">
            <span>{localizedManualModelLabel}</span>
            <input
              value={manualModelDraft}
              placeholder={localizedManualModelPlaceholder}
              onChange={(event) => setManualModelDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter") {
                  return;
                }
                event.preventDefault();
                handleAddManualModel();
              }}
            />
          </label>
          <button
            type="button"
            className="toolbar-button settings-model-limit-toolbar__button"
            disabled={!canAddManualModel}
            onClick={handleAddManualModel}
          >
            <span>{localizedManualModelButton}</span>
          </button>
        </div>
        <p className="settings-sheet__note settings-sheet__note--compact" role="status">
          {manualModelBlockedByPolicy
            ? modelPolicyHint(
                language,
                manualModelPolicy.reason === "denied" ? "denied" : "not_allowed",
              )
            : localizedManualModelHint}
        </p>
        {modelLimitNames.length > 0 ? (
          <div className="settings-model-limit-list" role="list" aria-label={localizedPerModelLimitsLabel}>
            {modelLimitNames.map((modelName) => {
              const isCurrentModel = modelName === currentDraftModel;
              const modelLimitPolicy = evaluateProviderModelPolicy(modelName, draftModelPolicy);
              const modelLimitBlockedByPolicy = !modelLimitPolicy.allowed;
              const isKnownLiveModel = discoveredModelSet.has(modelName.trim().toLowerCase());
              const isSavedCatalogModel = draftCatalogModels.some(
                (entry) => entry.trim().toLowerCase() === modelName.trim().toLowerCase(),
              );
              const draftLimit = readProviderModelTokenLimit(draftModelTokenLimits, modelName);
              const liveLimit = readProviderModelTokenLimit(liveModelTokenLimits, modelName);
              const draftRowContextWindowTokens = isCurrentModel
                ? draftContextWindowTokens
                : draftLimit?.contextWindowTokens;
              const draftRowMaxOutputTokens = isCurrentModel
                ? draftMaxOutputTokens
                : draftLimit?.maxOutputTokens;
              const liveRowContextWindowTokens =
                modelName === currentLiveModel ? liveContextWindowTokens : liveLimit?.contextWindowTokens;
              const liveRowMaxOutputTokens =
                modelName === currentLiveModel ? liveMaxOutputTokens : liveLimit?.maxOutputTokens;
              const hasDraftValues =
                typeof draftRowContextWindowTokens === "number" || typeof draftRowMaxOutputTokens === "number";
              const showCatalogRemoveAction = !hasDraftValues && isSavedCatalogModel;

              return (
                <div
                  key={modelName}
                  className={`settings-model-limit-row ${isCurrentModel ? "is-active" : ""} ${
                    modelLimitBlockedByPolicy ? "is-blocked" : ""
                  }`}
                  role="listitem"
                >
                  <div className="settings-model-limit-row__header">
                    <button
                      type="button"
                      className="settings-model-limit-row__model"
                      aria-pressed={isCurrentModel}
                      disabled={modelLimitBlockedByPolicy}
                      onClick={() => {
                        if (modelLimitBlockedByPolicy) {
                          return;
                        }
                        onProviderDraftChange({
                          model: modelName,
                          catalogModels: mergeDraftStringList(draftCatalogModels, modelName),
                        });
                      }}
                    >
                      <span className="settings-model-limit-row__model-name">{modelName}</span>
                      <span className="settings-model-limit-row__model-state">
                        {isCurrentModel ? localizedCurrentModelLabel : localizedUseModelLabel}
                      </span>
                    </button>
                    <div className="settings-model-limit-row__actions">
                      <span className="settings-model-limit-row__origin">
                        {isKnownLiveModel ? localizedModelOriginLive : localizedModelOriginManual}
                      </span>
                      {hasDraftValues || showCatalogRemoveAction ? (
                        <button
                          type="button"
                          className="toolbar-button settings-model-limit-row__clear"
                          disabled={modelLimitBlockedByPolicy}
                          onClick={() => {
                            if (modelLimitBlockedByPolicy) {
                              return;
                            }
                            if (hasDraftValues) {
                              clearDraftModelTokenLimit(modelName);
                              return;
                            }
                            removeDraftCatalogModel(modelName);
                          }}
                        >
                          <span>
                            {hasDraftValues ? localizedClearModelLimitsLabel : modelCardCopy.remove}
                          </span>
                        </button>
                      ) : null}
                    </div>
                  </div>
                  <div className="settings-model-limit-row__fields">
                    <label className="settings-field settings-field--dense">
                      <span>{settingsPhrase(language, "contextWindow")}</span>
                      <input
                        type="number"
                        min={1}
                        step={1}
                        disabled={modelLimitBlockedByPolicy}
                        value={draftRowContextWindowTokens ?? ""}
                        placeholder={
                          liveRowContextWindowTokens
                            ? formatTokenValue(liveRowContextWindowTokens)
                            : settingsPhrase(language, "notRecorded")
                        }
                        onChange={(event) =>
                          updateDraftModelTokenLimit(modelName, {
                            contextWindowTokens: parsePositiveIntegerInput(event.target.value),
                          })
                        }
                      />
                    </label>
                    <label className="settings-field settings-field--dense">
                      <span>{settingsPhrase(language, "maxOutput")}</span>
                      <input
                        type="number"
                        min={1}
                        step={1}
                        disabled={modelLimitBlockedByPolicy}
                        value={draftRowMaxOutputTokens ?? ""}
                        placeholder={
                          liveRowMaxOutputTokens
                            ? formatTokenValue(liveRowMaxOutputTokens)
                            : settingsPhrase(language, "notRecorded")
                        }
                        onChange={(event) =>
                          updateDraftModelTokenLimit(modelName, {
                            maxOutputTokens: parsePositiveIntegerInput(event.target.value),
                          })
                        }
                      />
                    </label>
                  </div>
                  {modelLimitBlockedByPolicy ? (
                    <p className="settings-sheet__note settings-sheet__note--compact" role="status">
                      {modelPolicyHint(
                        language,
                        modelLimitPolicy.reason === "denied" ? "denied" : "not_allowed",
                      )}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="settings-sheet__note settings-sheet__note--compact">
            {localizedModelLimitEmpty}
          </p>
        )}
      </div>
    </details>
  );
  const canNestModelLimitsInCatalog =
    canUseSavedModelMetadata && providerCatalogRows.length > 0;
  const advancedRoutingBody = (
      <div className="settings-sheet__minor-body settings-sheet__stack settings-sheet__stack--tight">
        <p className="settings-sheet__note settings-sheet__note--compact">
          {localizedAdvancedRoutingDetail}
        </p>
        <div className="settings-grid settings-grid--form">
          <div className="settings-field">
            <span>{localizedCredentialModeLabel}</span>
            <ChoiceList
              active={draftCredentialMode}
              items={[
                { label: localizedCredentialModeUiProxy, value: "ui_proxy" },
                {
                  label: localizedCredentialModeWorkspaceSecret,
                  value: "workspace_secret",
                },
              ]}
              onChange={(value) => onProviderDraftChange({ credentialMode: value })}
            />
          </div>

          <div className="settings-field">
            <span>{localizedCatalogSourceLabel}</span>
            <ChoiceList
              active={draftCatalogSource}
              items={[
                {
                  label: modelCardCopy.liveFetch,
                  value: "provider_live",
                },
                {
                  label: modelCardCopy.cached,
                  value: "cached",
                },
                {
                  label: modelCardCopy.manual,
                  value: "manual",
                },
              ]}
              onChange={(value) => onProviderDraftChange({ catalogSource: value })}
            />
          </div>

          <label className="settings-field">
            <span>{localizedCatalogCacheTtlLabel}</span>
            <input
              type="number"
              min={1}
              step={1}
              value={draftCacheTtlSeconds ?? ""}
              placeholder={provider.cacheTtlSeconds ? String(provider.cacheTtlSeconds) : ""}
              onChange={(event) =>
                onProviderDraftChange({
                  cacheTtlSeconds: parsePositiveIntegerInput(event.target.value),
                })
              }
            />
            <p className="settings-sheet__note settings-sheet__note--compact">
              {localizedCacheTtlDetail}
            </p>
          </label>

          <label className="settings-field">
            <span>{localizedCatalogEmbeddingModelLabel}</span>
            <input
              value={draftEmbeddingModel}
              placeholder={localizedEmbeddingModelPlaceholder}
              onChange={(event) =>
                onProviderDraftChange({
                  embeddingModel: event.target.value,
                })
              }
            />
          </label>

          <label className="settings-field">
            <span>{localizedCatalogAllowedModelsLabel}</span>
            <textarea
              rows={2}
              value={allowedModelsText}
              onFocus={() => {
                allowedModelsFocusedRef.current = true;
              }}
              onChange={(event) => {
                setAllowedModelsText(event.target.value);
                onProviderDraftChange({
                  allowedModels: parseDraftStringList(event.target.value),
                });
              }}
              onBlur={() => {
                allowedModelsFocusedRef.current = false;
                setAllowedModelsText(draftAllowedModelsSource);
              }}
            />
            <p className="settings-sheet__note settings-sheet__note--compact">
              {localizedAllowedModelsInputDetail}
            </p>
          </label>

          <label className="settings-field">
            <span>{localizedCatalogDeniedModelsLabel}</span>
            <textarea
              rows={2}
              value={deniedModelsText}
              onFocus={() => {
                deniedModelsFocusedRef.current = true;
              }}
              onChange={(event) => {
                setDeniedModelsText(event.target.value);
                onProviderDraftChange({
                  deniedModels: parseDraftStringList(event.target.value),
                });
              }}
              onBlur={() => {
                deniedModelsFocusedRef.current = false;
                setDeniedModelsText(draftDeniedModelsSource);
              }}
            />
            <p className="settings-sheet__note settings-sheet__note--compact">
              {localizedDeniedModelsInputDetail}
            </p>
          </label>

          <label className="settings-field">
            <span>{localizedCatalogRequestDefaultsLabel}</span>
            <textarea
              rows={6}
              spellCheck={false}
              value={requestDefaultsText}
              onFocus={() => {
                requestDefaultsFocusedRef.current = true;
              }}
              onChange={(event) => handleRequestDefaultsTextChange(event.target.value)}
              onBlur={() => {
                requestDefaultsFocusedRef.current = false;
                if (!requestDefaultsError) {
                  setRequestDefaultsText(formatRequestDefaultsDraft(draftRequestDefaults));
                }
              }}
            />
            <p className="settings-sheet__note settings-sheet__note--compact">
              {localizedRequestDefaultsInputDetail}
            </p>
            <p
              className={`settings-sheet__note settings-sheet__note--compact${
                requestDefaultsError ? " settings-sheet__note--warning" : ""
              }`}
            >
              {requestDefaultsError ?? localizedRequestDefaultsInputHint}
            </p>
          </label>
        </div>
      </div>
  );
  const providerCatalogPanel = canNestModelLimitsInCatalog ? (
    <details className="settings-sheet__minor-panel settings-sheet__provider-catalog">
      <summary>
        {localizedCatalogPanelLabel} <span aria-hidden="true">·</span> {providerCatalogSummary}
      </summary>
      <div className="settings-sheet__minor-body settings-sheet__stack settings-sheet__stack--tight">
        <p className="settings-sheet__note settings-sheet__note--compact">
          {localizedCatalogPanelDetail}
        </p>
        <div className="settings-sheet__simple-list" aria-label={localizedCatalogPanelLabel}>
          {providerCatalogRows.map((row) => (
            <SimpleInfoRow key={row.label} label={row.label} value={row.value} />
          ))}
        </div>
        {providerModelLimitsPanel}
        <details className="settings-sheet__minor-panel">
          <summary>{localizedAdvancedRoutingLabel}</summary>
          {advancedRoutingBody}
        </details>
      </div>
    </details>
  ) : (
    <details className="settings-sheet__minor-panel">
      <summary>{localizedAdvancedRoutingLabel}</summary>
      {advancedRoutingBody}
    </details>
  );
  const providerListBar =
    providerIdentityListVisible &&
    (providerProfiles.length > 0 ||
      canSaveProviderProfile ||
      (providerSaved && (onRefreshProviderProfiles || onUseProviderTemplateLabel))) ? (
      <div
        ref={providerDirectoryRef}
        className="settings-provider-bar"
        role="group"
        aria-label={localizedProviderProfilesLabel}
      >
        <div
          className="settings-sheet__provider-profiles settings-provider-bar__content"
          aria-label={providerSummaryText}
        >
          <div className="settings-provider-bar__list" role="list">
          {providerProfiles.map((profile) => (
            <button
              key={profile.id}
              className={`settings-provider-profile settings-provider-profile--bar ${
                profile.isActive ? "is-active" : ""
              }`}
              type="button"
              role="listitem"
              aria-pressed={profile.isActive}
              title={profile.detail ?? profile.label}
              disabled={!onSwitchProviderProfile || profile.isActive}
              onClick={() => {
                resetModelPickerSearch();
                setModelPickerOpen(false);
                setConnectionView("auto");
                onSwitchProviderProfile?.(profile.id);
              }}
            >
              <span className="settings-provider-profile__row">
                <span
                  className="settings-provider-profile__dot"
                  data-state={profile.isActive ? "active" : "idle"}
                  aria-hidden="true"
                />
                <span className="settings-provider-profile__label">{profile.label}</span>
                <span className="settings-provider-profile__meta">
                  <span className="settings-provider-profile__model">
                    {profile.model || provider.model}
                  </span>
                  {profile.isActive ? (
                    <span className="settings-provider-profile__state" aria-hidden="true">
                      <DoneIcon size={12} />
                    </span>
                  ) : null}
                </span>
              </span>
            </button>
          ))}
          </div>
          <div className="settings-provider-bar__actions">
            {providerSaved && !showConnectionSummary && !showConnectionForm ? (
              <button
                type="button"
                className="settings-provider-bar__add"
                title={settingsPhrase(language, "editConfiguration")}
                aria-label={settingsPhrase(language, "editConfiguration")}
                onClick={() => setConnectionView("edit")}
              >
                <ComposeIcon size={14} />
                <span>{settingsPhrase(language, "editConfiguration")}</span>
              </button>
            ) : null}
            {canSaveProviderProfile && !showConnectionSummary ? (
              <button
                type="button"
                className="settings-provider-bar__add"
                title={localizedSaveProfileDetail}
                aria-label={localizedSaveProfileLabel}
                onClick={onSaveProviderProfile}
              >
                <DoneIcon size={14} />
                <span>{localizedSaveProfileLabel}</span>
              </button>
            ) : null}
            {onRefreshProviderProfiles ? (
              <button
                type="button"
                className="settings-provider-bar__icon-button"
                title={localizedRefreshProfilesLabel}
                aria-label={localizedRefreshProfilesLabel}
                onClick={onRefreshProviderProfiles}
              >
                <ReloadIcon size={14} />
              </button>
            ) : null}
            {providerSaved && onUseProviderTemplateLabel && connectionView !== "add" ? (
              <button
                type="button"
                className="settings-provider-bar__add"
                onClick={() => setConnectionView("add")}
              >
                <PlusIcon size={14} />
                <span>{settingsPhrase(language, "addProvider")}</span>
              </button>
            ) : null}
          </div>
        </div>
      </div>
    ) : null;
  const providerDirectory =
    showProviderTemplates ? (
    <div className="settings-provider-directory-wrap">
      <div
        ref={providerTemplatesRef}
        className="settings-provider-directory"
        role="group"
        aria-label={localizedProviderDirectoryLabel}
      >
        {PROVIDER_TEMPLATE_GROUP_ORDER.map((group) => {
          const groupLabels = PROVIDER_TEMPLATE_LABELS.filter(
            (templateLabel) => PROVIDER_TEMPLATE_GROUPS[templateLabel] === group,
          );
          if (groupLabels.length === 0) {
            return null;
          }
          return (
            <div className="settings-provider-directory__group" key={group}>
              <div className="settings-provider-directory__heading">
                {providerTemplateGroupLabel(language, group)}
                <span className="settings-section-count" aria-hidden="true">
                  {groupLabels.length}
                </span>
              </div>
              <div role="list">
                {groupLabels.map((templateLabel) => (
                  <button
                    key={templateLabel}
                    type="button"
                    className="settings-provider-directory__item"
                    onClick={() => {
                      setConnectionView("edit");
                      onUseProviderTemplateLabel?.(templateLabel);
                    }}
                  >
                    {templateLabel}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <p className="settings-sheet__note settings-sheet__note--compact">
        {settingsPhrase(language, "providerDirectoryNote")}
      </p>
    </div>
  ) : null;
  const providerSecondaryActions = (
    <div className="settings-actions settings-actions--compact">
      <ActionButton
        fullWidth={false}
        icon={<SettingsPreferencesIcon size={14} />}
        label={copy.openConfig}
        detail={settingsPhrase(language, "workspaceFile")}
        onClick={onOpenConfig}
      />
      <ActionButton
        fullWidth={false}
        icon={<TrashIcon size={14} />}
        label={copy.clear}
        detail={settingsPhrase(language, "clearDraft")}
        onClick={onClearProvider}
      />
    </div>
  );
  const providerPrimaryActions = showProviderDetailActions ? (
    <div className="settings-actions settings-actions--compact settings-actions--primary settings-model-editor__footer">
      <button
        type="button"
        className="settings-model-editor__cancel"
        onClick={() => {
          onResetProviderDraft?.();
          setConnectionView("auto");
        }}
      >
        {settingsText(language, "取消", "Cancel")}
      </button>
      <ActionButton
        fullWidth={false}
        icon={
          providerSaveBusy ? (
            <span aria-hidden="true" className="trainer-spinner trainer-spinner--sm" />
          ) : (
            <DoneIcon size={14} />
          )
        }
        label={
          !canSaveProviderConnection && providerSaved && !providerHasDraftChanges
            ? settingsText(language, "已保存", "Saved")
            : settingsText(language, "保存", "Save")
        }
        ariaLabel={saveProviderConnectionLabel}
        // r1-g2-4: 保存并使用 is this screen's single solid primary; retest
        // and model-list refresh stay quiet secondary actions below it.
        tone="accent"
        detail={
          canSaveProviderConnection
            ? settingsPhrase(language, "saveToApply")
            : currentDraftModelPolicyMessage ??
              settingsPhrase(language, "saveConnectionDetail")
        }
        disabled={!canSaveProviderConnection}
        onClick={onSaveProvider}
        title={saveProviderConnectionTitle}
      />
    </div>
  ) : null;
  const providerDetailRequirementNote = providerHasDraftChanges
    ? currentDraftModelPolicyMessage ??
      (!providerDraft.baseUrl.trim()
        ? settingsStatusPhrase(language, "fillProviderFields")
        : !providerDraft.model.trim()
          ? providerDraftHasApiKey || providerDraftCanReuseSavedApiKey
            ? settingsText(language, "保存时将自动获取并选择可用模型。", "A model will be fetched and selected automatically when you save.")
            : modelPickerCopy.modelRequiredNote
          : !providerDraftHasApiKey && !providerDraftCanReuseSavedApiKey
            ? settingsStatusPhrase(language, "connectionSavedApiKeyMissing")
            : localizedResolvedAvailabilityDetail)
    : providerRequirementNote ?? localizedResolvedAvailabilityDetail;

  const availabilityState = <div data-settings-availability="true">
    <SystemState
      kind={backendStarting || providerTestPending ? "processing" : backendUnavailable ? "disconnected" : workspaceRootMissing ? "workspace-required" : providerCredentialsRejected ? "recoverable-error" : availabilityMode !== "ready" ? "provider-required" : "success"}
      title={displayAvailabilityHeadline}
      detail={showAvailabilityPrimaryAction ? displayAvailabilityDetail : localizedResolvedAvailabilityStatusLabel}
      action={availabilityStripReduced ? undefined : showAvailabilityPrimaryAction && !backendStarting && !providerTestPending ? {
        label: effectiveAvailabilityPrimaryCta.label,
        onClick: () => effectiveAvailabilityPrimaryCta.action?.(),
        disabled: !effectiveAvailabilityPrimaryCta.action,
      } : undefined}
      actionTone={effectiveAvailabilityPrimaryTone}
    />
  </div>;
  const settingsIndexItems = (["connection", "teaching", "workspace", "preferences"] as const).map((id) => {
    const item = settingsNavItems.find((entry) => entry.id === id)!;
    return {
      ...item,
      summary: (id === "connection"
        ? connectionModelSummary === copy.notConfigured
          ? connectionSummaryStatusLabel
          : connectionModelSummary
        : id === "workspace"
          ? remoteWorkspaceName ||
            (() => {
              const rootPath = trainerWorkspace?.rootPath?.replace(/[\\/]+$/, "");
              if (workspaceRootMissing || !rootPath) {
                return settingsPhrase(language, "workspaceNotSelected");
              }
              return rootPath;
            })()
          : id === "teaching"
            ? teachingStyleItems.find((entry) => entry.value === teachingStyle)?.label ?? copy.auto
            : LANGUAGE_LABELS[language]) ?? undefined,
      summaryTitle: (id === "workspace"
        ? remoteWorkspaceName || trainerWorkspace?.rootPath
        : id === "connection"
          ? [provider.model || providerDraft.model, lastTestLabel].filter(Boolean).join(" · ")
          : undefined) ?? undefined,
      action:
        id === "workspace" && workspaceRootMissing && onChooseTrainerWorkspaceRoot
          ? {
              label: settingsText(language, "选择学习文件夹", "Choose folder"),
              onClick: onChooseTrainerWorkspaceRoot,
              icon: <DataFolderIcon size={12} />,
            }
          : undefined,
    };
  });


  return {
    connectionSummaryCard,
    showAvailabilityChecklist,
    renderProviderSetupChecks,
    coachSettingsAutosaveNode,
    settingsNavItems,
    settingsStatusConnectionReady,
    visibleSettingsStatusIssues,
    coachBehaviorSummary,
    contextBehaviorSummary,
    runtimeFlowSummary,
    rememberedRows,
    remembersSummary,
    handleUseTypedModel,
    providerModelLimitsPanel,
    canNestModelLimitsInCatalog,
    providerCatalogPanel,
    providerListBar,
    providerDirectory,
    providerSecondaryActions,
    providerPrimaryActions,
    providerDetailRequirementNote,
    availabilityState,
    settingsIndexItems,
  };
}
