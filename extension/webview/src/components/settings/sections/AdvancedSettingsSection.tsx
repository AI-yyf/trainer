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

export interface AdvancedSettingsSectionProps {
  controller: CoachSettingsSheetController;
}

export function AdvancedSettingsSection({ controller }: AdvancedSettingsSectionProps) {
  const {
    workspaceId,
    className,
    workspaceControlStatus,
    provider,
    language,
    followCurrentFile,
    contextDetail,
    onFollowCurrentFileChange,
    onContextDetailChange,
    copy,
    settingsGlobalCopy,
    advancedContextPinned,
    setAdvancedContextPinned,
    usageInsightsPinned,
    usageInsights,
    usageInsightsError,
    usageInsightsLoading,
    usageWindowDays,
    loadUsageInsights,
    handleUsageInsightsToggle,
    handleUsageWindowChange,
    answerStyle,
    tuneAdvancedContextKnob,
    contextRows,
    attachedContextSummaryText,
    contextBehaviorSummary,
  } = controller;
  return (
    <>
          <header className="settings-section-head">
            <span id="settings-section-advanced-title" className="eyebrow">
              {settingsGlobalCopy.settingsAdvancedContext}
            </span>
          </header>
          <div className="settings-sheet__minor-body settings-sheet__defaults-body">
            <div className="settings-subsection">
              <span className="eyebrow settings-subsection__title">
                {settingsText(language, "内部标识", "Internal identifiers")}
              </span>
              <div className="settings-sheet__simple-list" role="list">
                <SimpleInfoRow
                  label={settingsText(language, "工作区 ID", "Workspace ID")}
                  value={workspaceId || "—"}
                />
                {provider.profileId?.trim() ? (
                  <SimpleInfoRow
                    label={settingsText(language, "配置 ID", "Profile ID")}
                    value={provider.profileId.trim()}
                  />
                ) : null}
              </div>
              <p className="settings-sheet__note settings-sheet__note--compact">
                {settingsText(language, "这些标识用于问题排查；连接诊断在“连接”页。", "Use these identifiers when reporting issues; connection diagnostics live under Connection.")}
              </p>
            </div>

            <CollapseSection
              level={2}
              persistenceKey="settings-usage-insights"
              open={usageInsightsPinned ?? false}
              onToggle={handleUsageInsightsToggle}
              title={<span className="eyebrow">{settingsText(language, "使用洞察", "Usage insights")}</span>}
              subtitle={<span className="settings-sheet__defaults-preview">{settingsText(language, "只汇总本机使用记录，只读、不联网。", "Local usage history, read-only. Nothing leaves this machine.")}</span>}
            >
              <div className="settings-sheet__minor-body" data-settings-subsection="usage-insights">
                <div className="settings-grid settings-grid--compact settings-grid--tight">
                  <div className="settings-row" data-usage-insights-window="true">
                    <span className="eyebrow">{settingsText(language, "统计区间", "Window")}</span>
                    <ChoiceList
                      active={String(usageWindowDays)}
                      items={[
                        { label: settingsText(language, "近 7 天", "Last 7 days"), value: "7" },
                        { label: settingsText(language, "近 30 天", "Last 30 days"), value: "30" },
                      ]}
                      onChange={(value) => handleUsageWindowChange(value === "7" ? 7 : 30)}
                    />
                  </div>
                </div>
                {usageInsightsLoading ? (
                  <p className="settings-sheet__note settings-sheet__note--compact">{settingsText(language, "读取中…", "Loading…")}</p>
                ) : usageInsightsError ? (
                  <p className="settings-sheet__note settings-sheet__note--compact" data-usage-insights-error="true">{usageInsightsError}</p>
                ) : usageInsights && usageInsights.total_events === 0 ? (
                  <p className="settings-sheet__note settings-sheet__note--compact">{settingsText(language, "这个区间还没有任何记录。", "No activity recorded in this window yet.")}</p>
                ) : usageInsights ? (
                  <>
                    <div className="settings-sheet__simple-list" data-usage-insights-totals="true">
                      <SimpleInfoRow label={settingsText(language, "卡片", "Cards")} value={String(usageInsights.totals.cards ?? 0)} />
                      <SimpleInfoRow label={settingsText(language, "计划", "Plans")} value={String(usageInsights.totals.plans ?? 0)} />
                      <SimpleInfoRow label={settingsText(language, "证据", "Evidence")} value={String(usageInsights.totals.evidence ?? 0)} />
                      <SimpleInfoRow label={settingsText(language, "练习提交", "Practice submissions")} value={String(usageInsights.totals.practice_submissions ?? 0)} />
                      <SimpleInfoRow label={settingsText(language, "资源", "Resources")} value={String(usageInsights.totals.resources ?? 0)} />
                      <SimpleInfoRow label={settingsText(language, "反思", "Reflections")} value={String(usageInsights.totals.reflections ?? 0)} />
                      <SimpleInfoRow label={settingsText(language, "教学资产", "Teaching assets")} value={String(usageInsights.totals.teaching_assets ?? 0)} />
                      <SimpleInfoRow label={settingsText(language, "活跃天数", "Active days")} value={String(usageInsights.active_days)} />
                      <SimpleInfoRow label={settingsText(language, "连续活跃", "Day streak")} value={String(usageInsights.streak_days)} />
                    </div>
                    <span className="eyebrow">{settingsText(language, "每日活跃", "Daily activity")}</span>
                    <div data-usage-insights-daily="true" role="img" aria-label={settingsText(language, "每日活跃", "Daily activity")}>
                      {usageInsights.daily.map((day) => (
                        <span
                          key={day.date}
                          title={day.date}
                          style={{
                            display: "inline-block",
                            width: 8,
                            height: 8,
                            borderRadius: 2,
                            marginRight: 2,
                            background: day.any_activity
                              ? "var(--accent)"
                              : "var(--line, transparent)",
                          }}
                        />
                      ))}
                    </div>
                  </>
                ) : null}
                <button
                  type="button"
                  className="context-chip"
                  data-usage-insights-refresh="true"
                  onClick={() => loadUsageInsights(usageWindowDays)}
                  disabled={usageInsightsLoading}
                >
                  <span>{settingsText(language, "刷新", "Refresh")}</span>
                </button>
              </div>
            </CollapseSection>

            <CollapseSection
              level={2}
              persistenceKey="settings-advanced-context"
              open={advancedContextPinned ?? answerStyle === "custom"}
              onToggle={setAdvancedContextPinned}
              title={<span className="eyebrow">{settingsGlobalCopy.settingsAdvancedContext}</span>}
              subtitle={<span className="settings-sheet__defaults-preview">{contextBehaviorSummary}</span>}
              >
              <div className="settings-sheet__minor-body">
                <div className="settings-grid settings-grid--compact settings-grid--tight">
                <div className="settings-row">
                    <span className="eyebrow">{copy.followCurrentFile}</span>
                    <ChoiceList
                      active={followCurrentFile ? "on" : "off"}
                      items={[
                        { label: copy.on, value: "on" },
                        { label: copy.off, value: "off" },
                        ]}
                      onChange={(value) =>
                        tuneAdvancedContextKnob(() => onFollowCurrentFileChange?.(value === "on"))
                      }
                      />
                </div>
                <div className="settings-row">
                    <span className="eyebrow">{copy.contextMode}</span>
                    <ChoiceList
                      active={contextDetail}
                      items={[
                        { label: copy.focused, value: "focused" },
                        { label: copy.balancedContext, value: "balanced" },
                        { label: copy.fullContext, value: "full" },
                        ]}
                      onChange={(value) =>
                        tuneAdvancedContextKnob(() => onContextDetailChange?.(value))
                      }
                      />
                </div>
                </div>

                <ContextList rows={contextRows} onLabel={copy.on} offLabel={copy.off} />
                {workspaceControlStatus?.saveState === "unsaved" ? (
                  <p className="settings-sheet__note settings-sheet__note--compact">
                    {attachedContextSummaryText}
                  </p>
                  ) : null}
              </div>
            </CollapseSection>

          </div>
    </>
  );
}
