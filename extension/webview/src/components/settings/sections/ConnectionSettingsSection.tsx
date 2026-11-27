import { templateCopy } from "../../../templates/templateCopy";
import { SettingsIndex, type SettingsSectionId } from "../../../templates/SettingsIndex";
import { SettingsDetail } from "../../../templates/SettingsDetail";
import {
  ChoiceList,
  ContextList,
  SimpleInfoRow,
  SummaryCard,
} from "../SettingsControls";
import { SystemState } from "../../../templates/SystemState";
import { useWorkbenchState } from "../../../app/useWorkbenchState";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  countSavedProviderProfiles,
  describeProviderCapabilityMatrixGroups,
  describeProviderDiagnosticVerdict,
  describeProviderProfileSummary,
  describeProviderProtocolSummary,
  describeProviderImageInputState,
  describeProviderSendState,
  describeProviderTestReadiness,
  hasSavedProviderProfiles,
  PROVIDER_TEST_FRESHNESS_WINDOW_MS,
  providerBaseUrlIsLocalService,
  providerErrorHint,
  type ProviderImageInputState,
  type ProviderSendState,
  type ProviderSendStateStatus,
} from "../../../../../../shared/src/providerStatus";
import {
  normalizeProviderBaseUrl,
  normalizeProviderProtocol,
  providerProtocolCompletionLabel,
  providerProtocolEndpointHint,
  looksLikeSchemelessProviderUrl,
  SUPPORTED_PROVIDER_PROTOCOLS,
} from "../../../../../../shared/src/providerProtocols";
import {
  providerModelTokenLimitsKey,
  readProviderModelTokenLimit,
  resolveProviderModelTokenState,
  withProviderModelTokenLimit,
} from "../../../../../../shared/src/providerModelTokenLimits";
import {
  SMART_CONTEXT_WINDOW_PRESETS,
  SMART_MAX_OUTPUT_PRESETS,
  formatCompactTokenLimit,
  inferModelDefaultTokenLimits,
  resolveEffectiveTokenBudgetProfile,
} from "../../../../../../shared/src/smartTokenBudget";
import {
  evaluateProviderModelPolicy,
  filterProviderModelOptions,
} from "../../../../../../shared/src/providerModelPolicy";
import type { ProviderModelTokenLimit, ProviderProtocol } from "../../../../../../shared/src/models";
import {
  providerConnectionNameLabel,
  providerFailureCopy,
  providerModelCardCopy,
  sidecarRestartCopy,
} from "../../../lib/i18n/segments/providerSettingsCopy";
import { MemorySharingPanel } from "../MemorySharingPanel";
import { TelemetryOptInPanel } from "../TelemetryOptInPanel";
import { providerRecoveryLocale } from "../../../app/providerRecoveryCopy";
import {
  deriveProviderSetupState,
  type ProviderSetupReason,
} from "../../../../../../shared/src/providerSetupState";
import type { LocalUsageInsights, ProviderEndpointSpeedTestResult } from "../../../lib/types";
import {
  isNewApiConnectionType,
  parseProviderConnectionPaste,
} from "../../../../../../shared/src/providerGateway";
import {
  PROVIDER_TEMPLATE_GROUPS,
  type ProviderTemplateGroup,
  PROVIDER_TEMPLATE_GROUP_ORDER,
  PROVIDER_TEMPLATE_LABELS,
} from "../../../../../../shared/src/providerTemplateCatalog";
import { classifyProviderThinkingSupport, describeProviderThinking, normalizeProviderThinkingConfig, synthesizeProviderThinkingDescriptor, thinkingProtocolSupportsWire, updateProviderThinking } from "../../../../../../shared/src/providerThinking";
import type { ProviderThinkingConfig } from "../../../../../../shared/src/providerThinking";
import type { TrainerCapabilityVerdict } from "../../../../../../shared/src/capabilityVerdict";
import {
  describeWorkspaceTrustState,
  normalizeWorkspaceTrustState,
  type WorkspaceTrustState,
} from "../../../../../../shared/src/workspaceTrustState";
import {
  selectScopedSettingsLastTest,
  settingsCapabilityChipsVisible,
  settingsCapabilitySurfaceStatus,
  settingsProtocolIsKnown,
} from "../../../../../../shared/src/settingsCapabilityGovernance";
import {
  inferProviderModelAdaptation,
  recommendProviderModel,
  type ProviderModelAdaptation,
} from "../../../../../../shared/src/providerModelAdaptation";
import { sanitizeErrorSurfaceText } from "../../../../../../shared/src/errorSurfaceSanitizer";

import { ActionButton } from "../../common";
import { ProviderEndpointSpeedTest } from "../ProviderEndpointSpeedTest";
import { ProviderQuickSetup } from "../ProviderQuickSetup";
import { WorkspaceRootRecoveryPanel } from "../WorkspaceRootRecoveryPanel";
import { WorkspaceAuthoritySummary } from "../../coach/parts/WorkspaceAuthoritySummary";
import { CollapseSection } from "../../common/CollapseSection";
import { StatusPill } from "../../StatusPill";
import { ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon, CloseIcon, ComposeIcon, EyeIcon, FileIcon, PlayIcon, PlusIcon, RefreshIcon, TrashIcon, UploadIcon } from "../../icons";
import { AlertTriangleIcon, DataFolderIcon, DoneIcon, ReloadIcon, SettingsShareIcon } from "../../icons/inline";
import { RemoteIcon } from "../../icons/brand/trainerBrand";
import { ResourcesNavIcon, TrainingNavIcon } from "../../icons/navigation/coreNav";
import { CoachNavIcon } from "../../icons/navigation/primaryNav";
import { SettingsAdvancedIcon, SettingsConnectionIcon, SettingsPreferencesIcon, SettingsSkillsIcon, SettingsTeachingIcon, SettingsWorkspaceIcon } from "../../icons/navigation/settingsNav";
import { LANGUAGE_LABELS, SUPPORTED_LANGUAGES } from "../../../../../../shared/src";
import { trainerCommands } from "../../../../../../shared/src/commands";
import { remoteSupportStateView, REMOTE_SUPPORT_COPY } from "../../../lib/i18n/segments/remoteSupportCopy";
import { settingsText } from "../settingsText";
import { languageIntegrityText } from "../languageIntegrityCopy";
import { useCoachSettingsViewState, useCoachSettingsHostFacts } from "../useCoachSettingsViewState";
import { useProviderConnection } from "../../../app/providerConnectionContext";
import { postMessage as postWebviewMessage, requestLocalUsageInsights } from "../../../lib/vscode";
import {
  trainerSkillCatalog,
  normalizeCustomSkillTrigger,
  resolveTrainerSkillText,
  trainerSkillSectionLabel,
  type TrainerCustomSkill,
  type TrainerSkillSection,
} from "../../../../../../shared/src/skillCatalog";
import { resolveCopy as resolveWorkbenchCopy } from "../../../lib/i18n/copy";
import {
  SETTINGS_FALLBACK_LABELS,
  englishLabels,
  extraLocalizedSettingsLabels,
  firstScreenRowLabels,
  localizedCatalogSavedModelsLabel,
  providerConnectionTruthCopyTable,
  providerDetailLabelTable,
  providerModelDiscoveryCopyTable,
  providerModelPickerCopyTable,
  providerTemplateGroupLabelTable,
  settingsPhraseTable,
  settingsStatusPhraseTable,
  settingsSupportPhraseTable,
  streamingVerificationCopyTable,
  toolsVerificationCopyTable,
  type ProviderConnectionTruthCopy,
  type ProviderDetailLabelKey,
  type SettingsPhraseKey,
  type SettingsStatusPhraseKey,
  type SettingsSupportPhraseKey,
  type ToolsVerificationCopy,
} from "../../../lib/i18n/segments/settingsInlineText";
import type {
  CapabilityFlags,
  CoachAnswerMode,
  ComposerLanguage,
  ProviderConfigView,
  ProviderProbeUsage,
  TeachingStyle,
  WorkspaceMemoryToggles,
  WorkspaceAuthority,
} from "../../../lib/types";
import {
  type AnswerMode,
  type SaveState,
  type CapabilityVerdictKey,
  CAPABILITY_VERDICT_LABELS,
  type AnswerStylePreset,
  DEFAULT_PROVIDER_CONNECTION_NAME,
  MODEL_PICKER_DEFENSIVE_OPTION_LIMIT,
  ANSWER_STYLE_STORAGE_KEY,
  SETTINGS_SECTION_FLASH_MS,
  type AnswerStyleValues,
  ANSWER_STYLE_PRESETS,
  deriveAnswerStylePreset,
  readStoredAnswerStyle,
  writeStoredAnswerStyle,
  prefersReducedMotion,
  learningSurfaceAlignmentCopy,
  browserCaptureSettingsCopy,
  type ProviderProfileView,
  asRecord,
  asString,
  asStringArray,
  asNumber,
  normalizeProviderBaseUrlDraft,
  looksLikeProviderServiceAddress,
  looksLikeProviderApiKeyToken,
  providerConnectionLabelFromPaste,
  providerConnectionTruthCopy,
  providerTemplateGroupLabel,
  providerDetailLabel,
  providerBaseUrlGuidance,
  providerModelDiscoveryCopy,
  providerModelPickerCopy,
  modelPolicyHint,
  normalizeComparablePath,
  memoryShareSourceLabel,
  normalizeProviderProfileView,
  normalizeProviderProfileViews,
  type ProviderDraft,
  type SettingsActionFeedback,
  type SettingsSectionStatus,
  type CoachSettingsLabels,
  type CoachSettingsViewProps,
  type CoachSettingsViewSheetProps,
  localizedSettingsLabels,
  settingsPhrase,
  settingsSupportPhrase,
  settingsStatusPhrase,
  providerVerdictTone,
  capabilityLabels,
  capabilitySummaryText,
  stringifyNode,
  compactSummaryValue,
  shortenSummary,
  adaptiveBehaviorLabel,
  formatTokenValue,
  formatProbeCostValue,
  describeProbeUsageDetail,
  formatDurationSeconds,
  summarizeProviderRequestDefaults,
  formatDraftStringList,
  parseDraftStringList,
  mergeDraftStringList,
  stringArrayKey,
  canonicalJsonValue,
  requestDefaultsKey,
  providerCapabilitiesKey,
  formatRequestDefaultsDraft,
  parsePositiveIntegerInput,
  formatTimestamp,
  toolsVerificationCopy,
  describeToolsVerificationFact,
  streamingVerificationCopy,
  describeStreamingVerificationFact,
  streamingProbeIsVerified,
  thinkingVerificationCopy,
  describeThinkingVerificationFact,
  visionVerificationCopy,
  describeVisionVerificationFact,
  gatewayFingerprintNote,
  protocolChoiceLabel,
  isMiniMaxLikeProvider,
  describeLanguageIntegrityFact,
} from "../coachSettingsHelpers";
import type { CoachSettingsSheetController } from "../useCoachSettingsSheetController";

export function ConnectionSettingsLead({ controller }: { controller: CoachSettingsSheetController }) {
  const {
    providerDraft,
    className,
    onProviderDraftChange,
    onSaveProvider,
    providerSaveBusy,
    onUseProviderTemplateLabel,
    provider,
    language,
    onTrustWindow,
    setConnectionView,
    providerTestPending,
    resolvedWorkspaceTrustState,
    providerCoachReady,
    providerDraftCanReuseSavedApiKey,
    showQuickSetup,
    showAvailabilityStrip,
    availabilityState,
  } = controller;
  return (
    <>
          {showQuickSetup ? (
          <ProviderQuickSetup
            language={language}
            draft={providerDraft}
            savedBaseUrl={provider.baseUrl}
            savedModel={provider.model}
            connected={providerCoachReady}
            hasStoredApiKey={providerDraftCanReuseSavedApiKey}
            trusted={resolvedWorkspaceTrustState === "trusted"}
            busy={providerSaveBusy || providerTestPending}
            onTrustWindow={onTrustWindow}
            onDraftChange={onProviderDraftChange}
            onSave={() => {
              if (onSaveProvider) {
                onSaveProvider();
              }
            }}
          />
          ) : null}
          {showQuickSetup && onUseProviderTemplateLabel ? (
            <button
              type="button"
              className="settings-template-entry"
              data-settings-template-entry="true"
              onClick={() => setConnectionView("add")}
            >
              <span className="settings-template-entry__copy">
                <strong>{settingsPhrase(language, "startFromTemplate")}</strong>
                <span>{settingsPhrase(language, "startFromTemplateDetail")}</span>
              </span>
              <ChevronRightIcon size={14} aria-hidden />
            </button>
          ) : null}
          {showAvailabilityStrip ? availabilityState : null}
    </>
  );
}

export function ConnectionSettingsSectionBody({ controller }: { controller: CoachSettingsSheetController }) {
  const {
    capabilityVerdict,
    providerDraft,
    workspaceAuthority,
    className,
    onProviderDraftChange,
    onResetProviderDraft,
    onSaveProvider,
    providerSpeedTestResults,
    providerSpeedTestPending,
    onSpeedTestEndpoints,
    onRefreshProviderModels,
    onTestProvider,
    onCancelProviderTest,
    provider,
    language,
    copy,
    connectionView,
    setConnectionView,
    apiKeyInputRef,
    modelPickerRef,
    modelSearchInputRef,
    modelSelectRef,
    thinkingBudgetInputRef,
    modelPickerAutoOpenRef,
    modelPickerOpen,
    setModelPickerOpen,
    apiKeyVisible,
    setApiKeyVisible,
    providerPasteHint,
    setProviderPasteHint,
    lastTest,
    providerTestPending,
    providerSaved,
    providerCoachReady,
    lastTestLabel,
    draftProtocol,
    providerBaseUrlLabel,
    providerBaseUrlHint,
    protocolItems,
    providerHasDraftChanges,
    normalizedDraftBaseUrl,
    providerDraftCanReuseSavedApiKey,
    providerDraftReadyForModelDiscovery,
    availableModels,
    draftCapabilities,
    draftThinkingConfig,
    explicitDraftThinkingEnabled,
    inferredDraftLimits,
    smartTokenProfile,
    thinkingDescriptor,
    currentDraftModel,
    modelAdaptation,
    applyModelAdaptation,
    draftModelPolicy,
    currentDraftModelPolicy,
    modelSearchQuery,
    setModelSearchQuery,
    setManualModelEntryOpen,
    resetModelPickerSearch,
    normalizedModelSearchQuery,
    matchingModelOptions,
    visibleModelOptions,
    visibleModelSelection,
    showModelSearchInput,
    showManualModelEntryAction,
    canUseTypedModel,
    showTypedModelAction,
    hiddenMatchingModelCount,
    modelPickerCopy,
    modelCatalogIsEmpty,
    draftContextWindowTokens,
    draftMaxOutputTokens,
    localizedLastTestDetailText,
    cacheSourceLabel,
    modelCacheStatusLabel,
    modelCacheTone,
    providerTruthCopy,
    toolsCopy,
    capabilitySurfaceStatus,
    capabilityChipsAllowed,
    capabilityHonestyStatus,
    toolsVerificationFact,
    streamingCopy,
    streamingVerificationFact,
    thinkingCopy,
    thinkingVerificationFact,
    visionCopy,
    visionVerificationFact,
    updateThinkingConfig,
    thinkingControl,
    applyProviderSmartPaste,
    providerPasteHintCopy,
    modelDiscoveryGuidance,
    modelDiscoveryActionLabel,
    modelDiscoveryBlockedReason,
    canRefreshModels,
    canSaveProviderConnection,
    canRetestProvider,
    showConnectionForm,
    connectionSummaryCard,
    showAvailabilityChecklist,
    renderProviderSetupChecks,
    handleUseTypedModel,
    providerModelLimitsPanel,
    canNestModelLimitsInCatalog,
    providerCatalogPanel,
    providerListBar,
    providerDirectory,
    providerSecondaryActions,
    providerPrimaryActions,
    providerDetailRequirementNote,
  } = controller;
  return (
    <>
            {providerListBar}

            {connectionSummaryCard}

            {connectionView === "add" ? (
              <button
                type="button"
                className="template-back settings-connection-back"
                onClick={() => setConnectionView("auto")}
              >
                <ChevronLeftIcon size={14} />
                <span>{settingsPhrase(language, "backToConnection")}</span>
              </button>
            ) : null}

            {providerDirectory}

            {showConnectionForm ? (
            <>
            <form
              className="settings-sheet__minor-body settings-model-editor"
              onSubmit={(event) => {
                event.preventDefault();
                if (canSaveProviderConnection) {
                  onSaveProvider?.();
                }
              }}
            >
              <header className="settings-model-editor__header">
                <div className="settings-model-editor__title">
                  <span className="settings-model-editor__eyebrow">
                    {providerSaved
                      ? settingsText(language, "连接", "Connection")
                      : settingsText(language, "新连接", "New connection")}
                  </span>
                  <strong>
                    {providerSaved
                      ? settingsText(language, "编辑模型配置", "Edit model setup")
                      : settingsText(language, "添加模型", "Add model")}
                  </strong>
                </div>
                <button
                  type="button"
                  className="settings-model-editor__close"
                  aria-label={settingsText(language, "关闭", "Close")}
                  onClick={() => {
                    onResetProviderDraft?.();
                    setConnectionView("auto");
                  }}
                >
                  <CloseIcon size={16} />
                </button>
              </header>
              <label className="settings-field">
                <span>{providerConnectionNameLabel(language)}</span>
                <input
                  value={providerDraft.name}
                  placeholder={settingsText(language, "给这组连接起个名字(可不填)", "Name this connection (optional)")}
                  onChange={(event) => onProviderDraftChange({ name: event.target.value })}
                />
              </label>
              <div className="settings-grid settings-grid--form">
                <div className="settings-form-group-label">
                  <strong>{settingsText(language, "服务", "Service")}</strong>
                  <span>
                    {settingsText(
                      language,
                      "地址与密钥只保存在本机。",
                      "Address and key stay on this machine.",
                    )}
                  </span>
                </div>
                <div className="settings-form-row">
                <label className="settings-field">
                  <span>{providerBaseUrlLabel}</span>
                  <input
                    value={providerDraft.baseUrl}
                    placeholder={
                      settingsText(language, "例如 localhost:1234/v1 或 api.deepseek.com/v1", "e.g. localhost:1234/v1 or api.deepseek.com/v1")
                    }
                    onChange={(event) => {
                      const smartPaste = applyProviderSmartPaste(event.target.value, "baseUrl");
                      setProviderPasteHint(smartPaste ? providerPasteHintCopy(smartPaste) : null);
                      if (smartPaste) {
                        return;
                      }
                      onProviderDraftChange({
                        baseUrl: event.target.value,
                        ...(providerDraft.name.trim()
                          ? {}
                          : { name: DEFAULT_PROVIDER_CONNECTION_NAME }),
                      });
                    }}
                  />
                  <p className="settings-sheet__note settings-sheet__note--compact">
                    {providerBaseUrlHint}
                  </p>
                </label>

                <div className="settings-field">
                  <span>{copy.apiKey}</span>
                  <div className="settings-api-key-row">
                    <div className="settings-api-key-input">
                      <input
                        ref={apiKeyInputRef}
                        type={apiKeyVisible ? "text" : "password"}
                        aria-label={copy.apiKey}
                        value={providerDraft.apiKey}
                        placeholder={
                          providerDraftCanReuseSavedApiKey ? copy.apiKeySaved : settingsStatusPhrase(language, "connectionSavedApiKeyMissing")
                        }
                        onChange={(event) => {
                          const smartPaste = applyProviderSmartPaste(event.target.value, "apiKey");
                          setProviderPasteHint(smartPaste ? providerPasteHintCopy(smartPaste) : null);
                          if (smartPaste) {
                            return;
                          }
                          onProviderDraftChange({ apiKey: event.target.value });
                        }}
                      />
                      <button
                        type="button"
                        className="settings-api-key-visibility"
                        aria-label={
                          apiKeyVisible
                            ? settingsText(language, "隐藏密钥", "Hide key")
                            : settingsText(language, "显示密钥", "Show key")
                        }
                        title={
                          apiKeyVisible
                            ? settingsText(language, "隐藏密钥", "Hide key")
                            : settingsText(language, "显示密钥", "Show key")
                        }
                        onClick={() => setApiKeyVisible((visible) => !visible)}
                      >
                        <EyeIcon size={14} />
                      </button>
                    </div>
                    {onTestProvider ? (
                      <button
                        type="button"
                        className="settings-api-key-test"
                        disabled={!canRetestProvider}
                        onClick={onTestProvider}
                        title={
                          canRetestProvider
                            ? copy.test
                            : settingsText(
                                language,
                                "先补全接口地址、密钥和模型，再测试连接。",
                                "Complete the endpoint, key, and model before testing.",
                              )
                        }
                      >
                        {providerTestPending ? (
                          <span className="trainer-spinner trainer-spinner--sm" aria-hidden="true" />
                        ) : null}
                        {copy.test}
                      </button>
                    ) : null}
                    {providerTestPending && onCancelProviderTest ? (
                      <button
                        type="button"
                        className="settings-api-key-test settings-api-key-test--cancel"
                        onClick={onCancelProviderTest}
                      >
                        {settingsText(language, "取消", "Cancel")}
                      </button>
                    ) : null}
                  </div>
                </div>
                </div>

                <div className="settings-field" data-ignore-system-proxy-toggle="true">
                  <span>{settingsText(language, "网络代理", "Network proxy")}</span>
                  <ChoiceList
                    active={providerDraft.ignoreSystemProxy ? "direct" : "system"}
                    items={[
                      {
                        label: settingsText(language, "跟随系统代理", "Use system proxy"),
                        value: "system",
                      },
                      {
                        label: settingsText(language, "忽略系统代理（直连）", "Ignore system proxy (Direct)"),
                        value: "direct",
                      },
                    ]}
                    onChange={(value) => onProviderDraftChange({ ignoreSystemProxy: value === "direct" })}
                  />
                  <p className="settings-sheet__note settings-sheet__note--compact">
                    {settingsText(
                      language,
                      "若本机代理环境变量导致 502 或超时，请切换为直连。",
                      "Switch to direct connection if local proxy variables cause 502 or timeouts.",
                    )}
                  </p>
                </div>

                {providerPasteHint ? (
                  <p className="settings-sheet__note settings-sheet__note--compact settings-sheet__note--warning">
                    {providerPasteHint}
                  </p>
                ) : null}

                <div className="settings-form-group-label">
                  <strong>{settingsText(language, "模型", "Model")}</strong>
                  <span>
                    {settingsText(
                      language,
                      "这组连接默认使用的聊天模型。",
                      "The chat model this connection uses by default.",
                    )}
                  </span>
                </div>
                {modelCatalogIsEmpty ? (
                  <label className="settings-field">
                    <span>{copy.model}</span>
                    <input
                      value={currentDraftModel}
                      placeholder={modelPickerCopy.directModelPlaceholder}
                      onChange={(event) => onProviderDraftChange({ model: event.target.value })}
                    />
                    <p className="settings-sheet__note settings-sheet__note--compact">
                      {providerDraftReadyForModelDiscovery
                        ? modelPickerCopy.directModelHint
                        : settingsText(
                            language,
                            "直接输入服务商支持的完整模型名。",
                            "Enter the exact model name supported by the provider.",
                          )}
                    </p>
                  </label>
                ) : (
                <div className="settings-field">
                  <span>{copy.model}</span>
                  <details
                    ref={modelPickerRef}
                    className="settings-model-picker"
                    open={modelPickerOpen}
                    onToggle={() => {
                      const picker = modelPickerRef.current;
                      if (!picker) {
                        return;
                      }
                      modelPickerAutoOpenRef.current = false;
                      setModelPickerOpen(picker.open);
                      if (!picker.open) {
                        resetModelPickerSearch();
                        return;
                      }
                      if (!showModelSearchInput) {
                        return;
                      }
                      window.requestAnimationFrame(() => modelSearchInputRef.current?.focus());
                    }}
                  >
                    <summary
                      aria-label={`${copy.model}: ${currentDraftModel || copy.availableModels}`}
                      title={currentDraftModel || copy.availableModels}
                    >
                      <span>{currentDraftModel || copy.availableModels}</span>
                    </summary>
                    {showModelSearchInput ? (
                      <div className="settings-model-picker__filter">
                        <input
                          ref={modelSearchInputRef}
                          type="search"
                          aria-label={modelPickerCopy.filterLabel}
                          value={modelSearchQuery}
                          placeholder={modelPickerCopy.filterPlaceholder}
                          onChange={(event) => setModelSearchQuery(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key !== "Enter" || !canUseTypedModel) {
                              return;
                            }
                            event.preventDefault();
                            handleUseTypedModel();
                          }}
                        />
                        {normalizedModelSearchQuery && matchingModelOptions.length === 0 ? (
                          <p className="settings-model-picker__hint">{modelPickerCopy.noMatches}</p>
                        ) : null}
                        {normalizedModelSearchQuery && hiddenMatchingModelCount > 0 ? (
                          <p className="settings-model-picker__hint">
                            {modelPickerCopy.moreMatchesHint(hiddenMatchingModelCount)}
                          </p>
                        ) : null}
                        {showTypedModelAction ? (
                          <button
                            type="button"
                            className="toolbar-button"
                            onClick={handleUseTypedModel}
                          >
                            {modelPickerCopy.useTypedModel(modelSearchQuery.trim())}
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                    {showModelSearchInput || visibleModelOptions.length > 0 ? (
                      <select
                        ref={modelSelectRef}
                        aria-label={copy.model}
                        value={visibleModelSelection}
                        onChange={(event) => {
                          const selectedModel = event.target.value;
                          if (!evaluateProviderModelPolicy(selectedModel, draftModelPolicy).allowed) {
                            return;
                          }
                          applyModelAdaptation(selectedModel);
                          resetModelPickerSearch();
                          setModelPickerOpen(false);
                        }}
                      >
                        {!visibleModelSelection ? (
                          <option value="" disabled>
                            {normalizedModelSearchQuery && matchingModelOptions.length === 0
                              ? modelPickerCopy.noMatches
                              : copy.availableModels}
                          </option>
                        ) : null}
                        {visibleModelOptions.map((modelName) => (
                          <option key={modelName} value={modelName}>
                            {modelName}
                          </option>
                        ))}
                      </select>
                    ) : null}
                    {showManualModelEntryAction ? (
                      <div className="settings-model-picker__filter">
                        <button
                          type="button"
                          className="toolbar-button"
                          onClick={() => {
                            setManualModelEntryOpen(true);
                            window.requestAnimationFrame(() => modelSearchInputRef.current?.focus());
                          }}
                        >
                          {modelPickerCopy.enterModelName}
                        </button>
                      </div>
                    ) : null}
                  </details>
                  <div className="settings-sheet__stack settings-sheet__stack--tight">
                  {/*
                    model catalog present: keep the disclosure picker
                  */}
                    {currentDraftModel && !currentDraftModelPolicy.allowed ? (
                      <p className="settings-sheet__note settings-sheet__note--compact" role="status">
                        {modelPolicyHint(
                          language,
                          currentDraftModelPolicy.reason === "denied" ? "denied" : "not_allowed",
                        )}
                      </p>
                    ) : null}
                    {modelDiscoveryGuidance ? (
                      <p className="settings-sheet__note settings-sheet__note--compact">
                        {modelDiscoveryGuidance}
                      </p>
                    ) : null}
                  </div>
                </div>
                )}
                {(providerSaved || providerDraftReadyForModelDiscovery) && onRefreshProviderModels ? (
                  <button
                    type="button"
                    className="settings-model-refresh"
                    disabled={!canRefreshModels}
                    onClick={onRefreshProviderModels}
                    title={canRefreshModels ? modelDiscoveryActionLabel : modelDiscoveryBlockedReason}
                  >
                    <ReloadIcon size={12} aria-hidden="true" />
                    {modelDiscoveryActionLabel}
                  </button>
                ) : null}
              </div>

              <div className="settings-advanced-card coach-settings-view__provider-detail">
                <div className="settings-advanced-card__capabilities">
                  <div className="settings-advanced-card__section-heading">
                    <strong>{settingsText(language, "模型能力", "Model capabilities")}</strong>
                    <span>
                      {settingsText(
                        language,
                        "可手动开启或关闭，也可点击上方测试验证。",
                        "Toggle manually or run a live test to verify.",
                      )}
                    </span>
                  </div>
                  <label className="settings-advanced-toggle">
                    <input
                      type="checkbox"
                      checked={Boolean(draftCapabilities.tools)}
                      onChange={(event) =>
                        onProviderDraftChange({
                          capabilities: {
                            ...draftCapabilities,
                            tools: event.target.checked,
                          },
                        })
                      }
                    />
                    <span>{toolsCopy.label}</span>
                  </label>
                  <label className="settings-advanced-toggle">
                    <input
                      type="checkbox"
                      checked={Boolean(draftCapabilities.vision)}
                      onChange={(event) =>
                        onProviderDraftChange({
                          capabilities: {
                            ...draftCapabilities,
                            vision: event.target.checked,
                          },
                        })
                      }
                    />
                    <span>{visionCopy.label}</span>
                  </label>
                  <label className="settings-advanced-toggle">
                    <input
                      type="checkbox"
                      checked={explicitDraftThinkingEnabled}
                      onChange={(event) =>
                        updateThinkingConfig({
                          ...(draftThinkingConfig ?? { mode: "auto" }),
                          mode: event.target.checked ? "enabled" : "disabled",
                          ...(event.target.checked &&
                          thinkingDescriptor?.kind === "thinking_budget" &&
                          typeof draftThinkingConfig?.budgetTokens !== "number"
                            ? { budgetTokens: 4096 }
                            : {}),
                        })
                      }
                    />
                    <span>{settingsText(language, "思考模式", "Thinking")}</span>
                  </label>
                </div>
                {currentDraftModel &&
                (modelAdaptation.confidence === "unknown" ||
                  (modelAdaptation.supportsTools && !draftCapabilities.tools) ||
                  (modelAdaptation.supportsVision && !draftCapabilities.vision) ||
                  (modelAdaptation.supportsThinking && !explicitDraftThinkingEnabled)) ? (
                  <div
                    className={`settings-model-adaptation settings-model-adaptation--${modelAdaptation.confidence}`}
                    data-model-adaptation={modelAdaptation.confidence}
                  >
                    <div className="settings-model-adaptation__header">
                      <strong>{settingsText(language, "模型适配", "Model fit")}</strong>
                      <span>
                        {modelAdaptation.confidence === "unknown"
                          ? settingsText(
                              language,
                              "未识别模型 · 请测试确认",
                              "Unknown model · test to confirm",
                            )
                          : settingsText(
                              language,
                              "按模型族推断 · 测试后以实测为准",
                              "Inferred from the model family · a real test remains authoritative",
                            )}
                      </span>
                    </div>
                    <div className="settings-model-adaptation__footer">
                      <div className="settings-model-adaptation__chips">
                        {modelAdaptation.supportsTools ? <span>{toolsCopy.label}</span> : null}
                        {modelAdaptation.supportsVision ? <span>{visionCopy.label}</span> : null}
                        {modelAdaptation.supportsThinking ? (
                          <span>
                            {settingsText(language, "思考", "Thinking")}
                            {modelAdaptation.suggestedEffort
                              ? ` · ${
                                  modelAdaptation.suggestedEffort === "low"
                                    ? settingsText(language, "低", "Low")
                                    : modelAdaptation.suggestedEffort === "high"
                                      ? settingsText(language, "高", "High")
                                      : settingsText(language, "中", "Medium")
                                }`
                              : ""}
                          </span>
                        ) : null}
                        {!modelAdaptation.supportsTools &&
                        !modelAdaptation.supportsVision &&
                        !modelAdaptation.supportsThinking ? (
                          <span>{settingsText(language, "基础对话", "Chat only")}</span>
                        ) : null}
                      </div>
                      {modelAdaptation.confidence === "known" ? (
                        <button
                          type="button"
                          className="button button--ghost button--compact"
                          onClick={() => applyModelAdaptation(currentDraftModel)}
                        >
                          {settingsText(language, "应用推荐能力", "Apply suggested")}
                        </button>
                      ) : null}
                    </div>
                  </div>
                ) : null}
                {thinkingDescriptor &&
                !thinkingDescriptor.disabled &&
                draftThinkingConfig?.mode !== "disabled" &&
                (explicitDraftThinkingEnabled || thinkingDescriptor.kind === "reasoning_effort") ? (() => {
                  const isBudgetProtocol =
                    thinkingDescriptor.kind === "thinking_budget" ||
                    thinkingDescriptor.kind === "gemini_thinking";
                  const supportsCustomBudget = typeof thinkingDescriptor.budgetMax === "number";
                  const plan = smartTokenProfile.thinkingBudget;
                  const effectiveBudgetMax = Math.min(
                    thinkingDescriptor.budgetMax ?? plan.max,
                    plan.max,
                  );
                  const currentBudget =
                    typeof draftThinkingConfig?.budgetTokens === "number"
                      ? draftThinkingConfig.budgetTokens
                      : undefined;
                  const activePreset = isBudgetProtocol
                    ? currentBudget === undefined
                      ? "auto"
                      : currentBudget === plan.low
                        ? "low"
                        : currentBudget === plan.medium
                          ? "medium"
                          : currentBudget === plan.high
                            ? "high"
                            : "custom"
                    : currentBudget !== undefined
                      ? "custom"
                      : draftThinkingConfig?.mode === "auto"
                        ? "auto"
                        : draftThinkingConfig?.reasoningEffort ?? "auto";
                  const quickTokenPresets = plan.presets.filter(
                    (value) => value <= effectiveBudgetMax,
                  );
                  const selectThinkingPreset = (
                    preset: "auto" | "low" | "medium" | "high" | "custom",
                  ) => {
                    if (isBudgetProtocol) {
                      if (preset === "custom") {
                        updateThinkingConfig({
                          ...(draftThinkingConfig ?? { mode: "enabled" }),
                          mode: "enabled",
                          budgetTokens: currentBudget ?? plan.recommendedCustom,
                        });
                        window.requestAnimationFrame(() => thinkingBudgetInputRef.current?.focus());
                        return;
                      }
                      if (preset === "auto") {
                        updateThinkingConfig({
                          mode: "auto",
                          budgetTokens: undefined,
                        });
                        return;
                      }
                      const presetBudget =
                        preset === "low"
                          ? plan.low
                          : preset === "medium"
                            ? plan.medium
                            : plan.high;
                      updateThinkingConfig({
                        ...(draftThinkingConfig ?? { mode: "enabled" }),
                        mode: "enabled",
                        budgetTokens: presetBudget,
                      });
                      return;
                    }
                    if (preset === "custom") {
                      updateThinkingConfig({
                        ...(draftThinkingConfig ?? { mode: "enabled" }),
                        mode: "enabled",
                        reasoningEffort: undefined,
                        budgetTokens: currentBudget ?? plan.recommendedCustom,
                      });
                      window.requestAnimationFrame(() => thinkingBudgetInputRef.current?.focus());
                      return;
                    }
                    if (preset === "auto") {
                      updateThinkingConfig({
                        mode: "auto",
                        reasoningEffort: undefined,
                        budgetTokens: undefined,
                      });
                      return;
                    }
                    updateThinkingConfig({
                      ...(draftThinkingConfig ?? { mode: "enabled" }),
                      mode: "enabled",
                      reasoningEffort: preset,
                      budgetTokens: undefined,
                    });
                  };
                  return (
                    <div className="settings-thinking-intensity" data-thinking-intensity="true">
                      <div className="settings-thinking-intensity__row">
                        <span className="settings-thinking-intensity__label">
                          {settingsText(language, "思考强度", "Thinking intensity")}
                        </span>
                        <div
                          className="settings-thinking-intensity__pills"
                          role="group"
                          aria-label={settingsText(language, "思考强度", "Thinking intensity")}
                        >
                          {(
                            [
                              ["auto", settingsText(language, "自动", "Auto")],
                              ["low", settingsText(language, "低", "Low")],
                              ["medium", settingsText(language, "中", "Medium")],
                              ["high", settingsText(language, "高", "High")],
                              ...(supportsCustomBudget
                                ? ([["custom", settingsText(language, "自定义", "Custom")]] as const)
                                : []),
                            ] as const
                          ).map(([value, label]) => (
                            <button
                              key={value}
                              type="button"
                              className="settings-thinking-intensity__pill"
                              data-thinking-preset={value}
                              aria-pressed={activePreset === value}
                              onClick={() => selectThinkingPreset(value)}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </div>
                      {explicitDraftThinkingEnabled && supportsCustomBudget ? (
                        <div className="settings-thinking-intensity__budget">
                          <label className="settings-thinking-intensity__budget-field">
                            <span>{settingsText(language, "自定义预算 (Tokens)", "Custom budget (Tokens)")}</span>
                            <div className="settings-thinking-intensity__input-wrap">
                              <input
                                ref={thinkingBudgetInputRef}
                                type="number"
                                min={thinkingDescriptor.budgetMin ?? 1}
                                max={effectiveBudgetMax}
                                step={256}
                                value={currentBudget ?? ""}
                                placeholder={settingsText(
                                  language,
                                  "例如 {n}（安全上限 {max}，留空自动）",
                                  "e.g. {n} (cap {max}, blank = auto)",
                                )
                                  .replace("{n}", String(plan.recommendedCustom))
                                  .replace("{max}", formatCompactTokenLimit(effectiveBudgetMax))}
                                onChange={(event) => {
                                  const nextBudget = parsePositiveIntegerInput(event.target.value);
                                  updateThinkingConfig({
                                    ...(draftThinkingConfig ?? { mode: "enabled" }),
                                    mode: "enabled",
                                    ...(nextBudget !== undefined ? { reasoningEffort: undefined } : {}),
                                    budgetTokens: nextBudget,
                                  });
                                }}
                              />
                              {currentBudget !== undefined ? (
                                <button
                                  type="button"
                                  className="settings-thinking-intensity__clear"
                                  aria-label={settingsText(language, "清除自定义预算", "Clear custom budget")}
                                  title={settingsText(language, "清除自定义预算", "Clear custom budget")}
                                  onClick={() =>
                                    updateThinkingConfig({
                                      ...(draftThinkingConfig ?? { mode: "enabled" }),
                                      mode: "enabled",
                                      budgetTokens: undefined,
                                    })
                                  }
                                >
                                  ×
                                </button>
                              ) : null}
                            </div>
                          </label>
                          <div className="settings-thinking-intensity__chips">
                            {quickTokenPresets.map((tokens) => (
                              <button
                                key={tokens}
                                type="button"
                                className="settings-thinking-intensity__chip"
                                aria-pressed={currentBudget === tokens}
                                onClick={() =>
                                  updateThinkingConfig({
                                    ...(draftThinkingConfig ?? { mode: "enabled" }),
                                    mode: "enabled",
                                    reasoningEffort: undefined,
                                    budgetTokens: tokens,
                                  })
                                }
                              >
                                {formatCompactTokenLimit(tokens) || String(tokens)}
                              </button>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  );
                })() : null}
                <label className="settings-field">
                  <span>{settingsSupportPhrase(language, "protocol")}</span>
                  <select
                    value={draftProtocol}
                    onChange={(event) => {
                      const protocol = normalizeProviderProtocol(event.target.value);
                      if (protocol) {
                        onProviderDraftChange({ protocol });
                      }
                    }}
                  >
                    {protocolItems.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </label>
                <ProviderEndpointSpeedTest
                  language={language}
                  baseUrl={normalizedDraftBaseUrl || providerDraft.baseUrl}
                  results={providerSpeedTestResults}
                  pending={providerSpeedTestPending}
                  onRun={(urls) => onSpeedTestEndpoints?.(urls)}
                  onAdopt={(url) => onProviderDraftChange({ baseUrl: url })}
                />
                <details className="settings-sheet__minor-panel settings-token-presets-panel">
                  <summary>
                    <span>{settingsText(language, "上下文与输出上限", "Context & output limits")}</span>
                    <span className="settings-section-count">
                      {[
                        draftContextWindowTokens
                          ? formatCompactTokenLimit(draftContextWindowTokens) ||
                            formatTokenValue(draftContextWindowTokens)
                          : `${settingsText(language, "智能", "Smart")} ${formatCompactTokenLimit(smartTokenProfile.effectiveContextWindowTokens)}`,
                        draftMaxOutputTokens
                          ? formatCompactTokenLimit(draftMaxOutputTokens) ||
                            formatTokenValue(draftMaxOutputTokens)
                          : formatCompactTokenLimit(smartTokenProfile.effectiveMaxOutputTokens),
                      ].join(" / ")}
                    </span>
                  </summary>
                  <div className="settings-sheet__minor-body">
                    <div className="settings-advanced-limits">
                      <label className="settings-field">
                        <span>{settingsPhrase(language, "contextWindow")}</span>
                        <input
                          inputMode="numeric"
                          value={draftContextWindowTokens ?? ""}
                          placeholder={`${settingsText(language, "智能默认", "Smart default")} (${formatCompactTokenLimit(inferredDraftLimits.contextWindowTokens)})`}
                          onChange={(event) =>
                            onProviderDraftChange({
                              contextWindowTokens: parsePositiveIntegerInput(event.target.value),
                            })
                          }
                        />
                      </label>
                      <div className="settings-advanced-presets">
                        {([undefined, ...SMART_CONTEXT_WINDOW_PRESETS] as const).map((value) => {
                          const active = (draftContextWindowTokens ?? undefined) === value;
                          return (
                            <button
                              key={value ?? "auto"}
                              type="button"
                              className={active ? "is-active" : undefined}
                              aria-pressed={active}
                              onClick={() => onProviderDraftChange({ contextWindowTokens: value })}
                            >
                              {value
                                ? formatCompactTokenLimit(value)
                                : settingsText(language, "自动", "Auto")}
                            </button>
                          );
                        })}
                      </div>
                      <label className="settings-field">
                        <span>{settingsPhrase(language, "maxOutput")}</span>
                        <input
                          inputMode="numeric"
                          value={draftMaxOutputTokens ?? ""}
                          placeholder={`${settingsText(language, "智能默认", "Smart default")} (${formatCompactTokenLimit(inferredDraftLimits.maxOutputTokens)})`}
                          onChange={(event) =>
                            onProviderDraftChange({
                              maxOutputTokens: parsePositiveIntegerInput(event.target.value),
                            })
                          }
                        />
                      </label>
                      <div className="settings-advanced-presets">
                        {([undefined, ...SMART_MAX_OUTPUT_PRESETS] as const).map((value) => {
                          const active = (draftMaxOutputTokens ?? undefined) === value;
                          return (
                            <button
                              key={value ?? "auto"}
                              type="button"
                              className={active ? "is-active" : undefined}
                              aria-pressed={active}
                              onClick={() => onProviderDraftChange({ maxOutputTokens: value })}
                            >
                              {value
                                ? formatCompactTokenLimit(value)
                                : settingsText(language, "自动", "Auto")}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                </details>
                {thinkingDescriptor?.kind === "reasoning_effort" ||
                thinkingDescriptor?.kind === "minimax_thinking" ||
                thinkingDescriptor?.kind === "thinking_budget" ||
                thinkingDescriptor?.kind === "gemini_thinking"
                  ? null
                  : thinkingControl}
                {!canNestModelLimitsInCatalog ? providerModelLimitsPanel : null}
                {providerCatalogPanel}
                <details className="settings-sheet__minor-panel settings-connection-diagnostics">
                  <summary>{settingsText(language, "连接诊断", "Connection diagnostics")}</summary>
                  <div className="settings-sheet__minor-body settings-sheet__stack settings-sheet__stack--tight">
                    <div className="settings-sheet__summary-grid">
                      <SummaryCard
                        label={copy.modelCache}
                        value={<StatusPill tone={modelCacheTone}>{modelCacheStatusLabel}</StatusPill>}
                        detail={`${copy.modelCacheSource}: ${cacheSourceLabel}`}
                      />
                      <SummaryCard label={copy.lastTest} value={lastTestLabel} detail={localizedLastTestDetailText} />
                      <SummaryCard
                        label={providerTruthCopy.capabilities}
                        value={
                          capabilityChipsAllowed ? (
                            <span className="settings-sheet__summary-inline">
                              <span>{toolsCopy.label}</span>
                              <span data-settings-capability-chip="tools"><StatusPill tone={toolsVerificationFact.tone}>{toolsVerificationFact.value}</StatusPill></span>
                              <span>{streamingCopy.label}</span>
                              <span data-settings-capability-chip="streaming"><StatusPill tone={streamingVerificationFact.tone}>{streamingVerificationFact.value}</StatusPill></span>
                              <span>{thinkingCopy.label}</span>
                              <span data-settings-capability-chip="thinking"><StatusPill tone={thinkingVerificationFact.tone}>{thinkingVerificationFact.value}</StatusPill></span>
                              <span>{visionCopy.label}</span>
                              <span data-settings-capability-chip="vision"><StatusPill tone={visionVerificationFact.tone}>{visionVerificationFact.value}</StatusPill></span>
                            </span>
                          ) : (
                            <span
                              className="settings-capability-status"
                              data-settings-capability-status={providerHasDraftChanges ? "draft" : capabilitySurfaceStatus}
                            >
                              {capabilityHonestyStatus}
                            </span>
                          )
                        }
                      />
                      <SummaryCard
                        label={settingsText(language, "写入权限", "Writes")}
                        value={
                          workspaceAuthority?.authorityScope === "trainer_sandbox"
                            ? settingsText(language, "Trainer 沙箱 artifact 写入", "Trainer sandbox artifact writes")
                            : settingsText(language, "用户源码工作区只读", "User source workspace is read-only")
                        }
                        detail={
                          workspaceAuthority?.resourceWriteEvidence?.reason ??
                          settingsText(language, "等待真实写入证据", "Awaiting verified write evidence")
                        }
                      />
                      <SummaryCard
                        label={settingsPhrase(language, "finalCapabilities")}
                        detail={settingsPhrase(language, "capabilitiesFromLiveTest")}
                        value={
                          capabilityChipsAllowed ? (
                            <span className="settings-sheet__summary-inline">
                              {([
                                ["chat", capabilityVerdict.chat],
                                ["streaming", capabilityVerdict.streaming],
                                ["tools", capabilityVerdict.verifiedTools],
                                ["image-input", capabilityVerdict.imageInput],
                                ["formal-plan", capabilityVerdict.formalPlan],
                                ["resource-write", capabilityVerdict.resourceWrite],
                              ] as const).map(([name, enabled]) => (
                                <span key={name} data-capability-verdict={name}>
                                  <span>{CAPABILITY_VERDICT_LABELS[language][name]}</span>{" "}
                                  <StatusPill tone={enabled ? "connected" : "warn"}>
                                    {enabled
                                      ? settingsStatusPhrase(language, "ready")
                                      : settingsStatusPhrase(language, "unavailable")}
                                  </StatusPill>
                                </span>
                              ))}
                            </span>
                          ) : (
                            <span
                              className="settings-capability-status"
                              data-settings-capability-status={providerHasDraftChanges ? "draft" : capabilitySurfaceStatus}
                              data-capability-verdict-status={providerHasDraftChanges ? "draft" : capabilitySurfaceStatus}
                            >
                              {capabilityHonestyStatus}
                            </span>
                          )
                        }
                      />
                    </div>
                    {providerSecondaryActions}
                  </div>
                </details>
              </div>

              {providerPrimaryActions}
            </form>

            {!providerCoachReady ||
            (providerHasDraftChanges && !canSaveProviderConnection) ? (
              <p className="settings-sheet__note settings-sheet__note--warning">
                {providerDetailRequirementNote}
              </p>
            ) : null}
            {showAvailabilityChecklist ? renderProviderSetupChecks("settings-setup-checks--availability") : null}
            </>
            ) : null}
    </>
  );
}
