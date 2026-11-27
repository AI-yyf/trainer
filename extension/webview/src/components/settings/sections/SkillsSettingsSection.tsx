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

export interface SkillsSettingsSectionProps {
  controller: CoachSettingsSheetController;
}

export function SkillsSettingsSection({ controller }: SkillsSettingsSectionProps) {
  const {
    className,
    skillSharing,
    language,
    onCoachDefaultsChange,
    onGenerateSkillDraft,
    settingsGlobalCopy,
    customSkillDraft,
    setCustomSkillDraft,
    customSkillDescription,
    setCustomSkillDescription,
    customSkillGenerating,
    setCustomSkillGenerating,
    customSkillFormOpen,
    setCustomSkillFormOpen,
    customSkillSource,
    setCustomSkillSource,
    customSkillError,
    setCustomSkillError,
    customSkills,
  } = controller;
  return (
    <>
          <header className="settings-section-head">
            <span id="settings-section-skills-title" className="eyebrow">
              {settingsGlobalCopy.settingsSectionSkills}
            </span>
            <span className="settings-section-head__summary">
              {settingsText(language, "Trainer 按你的问题自动选用；输入 $ 可手动触发。", "Trainer picks these automatically; type $ to trigger one manually.")}
            </span>
          </header>
          <div className="settings-sheet__minor-body settings-sheet__defaults-body">
            <details className="template-disclosure" data-skill-catalog="true"><summary>{templateCopy[language].builtinSkills}</summary><div className="settings-skill-groups">
              {(
                ["Coach", "Plan", "Training", "Resources", "Workspace", "Provider"] as TrainerSkillSection[]
              ).map((section) => {
                const items = trainerSkillCatalog.filter((skill) => skill.section === section);
                if (items.length === 0) {
                  return null;
                }
                return (
                  <div key={section} className="settings-subsection" data-settings-subsection={`skills-${section.toLowerCase()}`}>
                    <span className="eyebrow settings-subsection__title">
                      {trainerSkillSectionLabel(section, language)}
                    </span>
                    <div className="settings-sheet__simple-list" role="list">
                      {items.map((skill) => {
                        const title = resolveTrainerSkillText(skill.title, language);
                        const detail = resolveTrainerSkillText(skill.detail, language);
                        return (
                          <div key={skill.id} className="settings-skill-row" role="listitem">
                            <span className="settings-skill-row__trigger">{skill.trigger}</span>
                            <span className="settings-skill-row__body">
                              <span className="settings-skill-row__title">{title}</span>
                              {detail ? (
                                <span className="settings-skill-row__detail">{detail}</span>
                              ) : null}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div></details>

            {skillSharing}
            <div className="settings-subsection" data-settings-subsection="skills-custom">
              <span className="eyebrow settings-subsection__title">
                {settingsText(language, "我的技能", "My skills")}
              </span>
              {customSkills.length > 0 ? (
                <div className="settings-sheet__simple-list" role="list">
                  {customSkills.map((skill) => (
                    <div key={skill.id} className="settings-skill-row" role="listitem">
                      <span className="settings-skill-row__trigger">{skill.trigger}</span>
                      <span className="settings-skill-row__body">
                        <span className="settings-skill-row__title">{skill.title}</span>
                        {skill.detail ? (
                          <span className="settings-skill-row__detail">{skill.detail}</span>
                        ) : null}
                      </span>
                      <button
                        type="button"
                        className="settings-skill-row__remove"
                        aria-label={settingsText(language, "删除技能", "Remove skill")}
                        title={settingsText(language, "删除技能", "Remove skill")}
                        onClick={() =>
                          onCoachDefaultsChange?.({
                            customSkills: customSkills.filter((item) => item.id !== skill.id),
                          })
                        }
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="settings-sheet__note settings-sheet__note--compact">
                  {settingsText(
                    language,
                    "还没有自定义技能。添加一个，用 $触发器 在输入框里调用。",
                    "No custom skills yet. Add one and call it with its $trigger in the composer.",
                  )}
                </p>
              )}

              <div className="settings-skill-form-wrap">
              {customSkillFormOpen ? (
              <div className="settings-skill-form">
                <div className="settings-skill-form__field">
                  <span className="eyebrow">
                    {settingsText(language, "用一句话描述这个技能", "Describe the skill in one line")}
                  </span>
                  <textarea
                    value={customSkillDescription}
                    rows={2}
                    placeholder={settingsText(
                      language,
                      "例如:每周五把学习记录整理成周报,按完成/卡住/下一步输出",
                      "e.g. every Friday, tidy my learning log into done/stuck/next",
                    )}
                    onChange={(event) => {
                      setCustomSkillDescription(event.target.value);
                      setCustomSkillError(null);
                    }}
                  />
                </div>
                <button
                  type="button"
                  className="button button--accent settings-skill-form__generate"
                  disabled={
                    customSkillGenerating ||
                    customSkillDescription.trim().length < 2 ||
                    !onGenerateSkillDraft
                  }
                  onClick={async () => {
                    if (customSkillGenerating) return;
                    setCustomSkillGenerating(true);
                    setCustomSkillError(null);
                    try {
                      const draft = await onGenerateSkillDraft?.(customSkillDescription);
                      if (!draft) {
                        setCustomSkillError(
                          settingsText(
                            language,
                            "先描述一下这个技能要做什么。",
                            "Describe what the skill should do first.",
                          ),
                        );
                        return;
                      }
                      setCustomSkillDraft({
                        trigger: draft.trigger,
                        title: draft.title,
                        prompt: draft.prompt,
                        detail: draft.detail,
                      });
                      setCustomSkillSource(draft.source);
                      setCustomSkillError(null);
                    } catch {
                      setCustomSkillError(settingsText(language,
                        "技能生成失败。请检查连接后重试，也可以直接填写下方内容。",
                        "Skill generation failed. Check your connection and retry, or enter the skill below."));
                    } finally {
                      setCustomSkillGenerating(false);
                    }
                  }}
                >
                  {customSkillGenerating
                    ? settingsText(language, "生成中…", "Drafting…")
                    : settingsText(language, "✨ 智能生成", "✨ Draft with AI")}
                </button>
                {customSkillSource ? (
                  <p className="settings-sheet__note settings-sheet__note--compact">
                    {customSkillSource === "model"
                      ? settingsText(language, "已用当前模型生成,可直接修改后保存。", "Drafted with your model — tweak anything before saving.")
                      : settingsText(language, "已生成草稿(未连接模型),可修改后保存。", "Drafted without a model — tweak anything before saving.")}
                  </p>
                ) : null}

                <div className="settings-skill-form__field">
                  <span className="eyebrow">{settingsText(language, "触发器", "Trigger")}</span>
                  <input
                    type="text"
                    value={customSkillDraft.trigger}
                    placeholder="$my-skill"
                    onChange={(event) => {
                      setCustomSkillDraft((draft) => ({ ...draft, trigger: event.target.value }));
                      setCustomSkillError(null);
                    }}
                  />
                </div>
                <div className="settings-skill-form__field">
                  <span className="eyebrow">{settingsText(language, "名称", "Name")}</span>
                  <input
                    type="text"
                    value={customSkillDraft.title}
                    placeholder={settingsText(language, "例如:整理周报", "e.g. Tidy my weekly report")}
                    onChange={(event) => {
                      setCustomSkillDraft((draft) => ({ ...draft, title: event.target.value }));
                      setCustomSkillError(null);
                    }}
                  />
                </div>
                <div className="settings-skill-form__field">
                  <span className="eyebrow">{settingsText(language, "提示词", "Prompt")}</span>
                  <textarea
                    value={customSkillDraft.prompt}
                    rows={3}
                    onChange={(event) => {
                      setCustomSkillDraft((draft) => ({ ...draft, prompt: event.target.value }));
                      setCustomSkillError(null);
                    }}
                  />
                </div>
                {customSkillError ? (
                  <p className="settings-sheet__note settings-sheet__note--compact" role="alert">
                    {customSkillError}
                  </p>
                ) : null}
                <button
                  type="button"
                  className="button button--accent settings-skill-form__add"
                  disabled={
                    !customSkillDraft.trigger.trim() ||
                    !customSkillDraft.title.trim() ||
                    !customSkillDraft.prompt.trim() ||
                    customSkills.length >= 24
                  }
                  onClick={() => {
                    const normalized = normalizeCustomSkillTrigger(customSkillDraft.trigger);
                    if (!normalized) {
                      setCustomSkillError(
                        settingsText(
                          language,
                          "触发器需要是 $ 开头、无空格的短词(例如 $weekly-report)。",
                          "The trigger must be a short $word without spaces (e.g. $weekly-report).",
                        ),
                      );
                      return;
                    }
                    if (
                      customSkills.some(
                        (item) => item.trigger.toLowerCase() === normalized.toLowerCase(),
                      )
                    ) {
                      setCustomSkillError(
                        settingsText(language, "这个触发器已经被使用了。", "That trigger is already in use."),
                      );
                      return;
                    }
                    const prompt = customSkillDraft.prompt.trim();
                    const title = customSkillDraft.title.trim();
                    const detail =
                      customSkillDraft.detail.trim() ||
                      (prompt.length > 140 ? `${prompt.slice(0, 137)}...` : prompt);
                    onCoachDefaultsChange?.({
                      customSkills: [
                        ...customSkills,
                        {
                          id: `custom-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
                          trigger: normalized,
                          title,
                          detail,
                          prompt,
                          keywords: [],
                          createdAt: new Date().toISOString(),
                        } satisfies TrainerCustomSkill,
                      ],
                    });
                    setCustomSkillDraft({ trigger: "", title: "", prompt: "", detail: "" });
                    setCustomSkillDescription("");
                    setCustomSkillSource(null);
                    setCustomSkillError(null);
                    setCustomSkillFormOpen(false);
                  }}
                >
                  {settingsText(language, "添加技能", "Add skill")}
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="button button--accent settings-skill-form__toggle"
                onClick={() => setCustomSkillFormOpen(true)}
              >
                {settingsText(language, "添加技能", "Add skill")}
              </button>
            )}
              </div>
            </div>
          </div>
    </>
  );
}
