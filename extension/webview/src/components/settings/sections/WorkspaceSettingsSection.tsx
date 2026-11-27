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

export interface WorkspaceSettingsSectionProps {
  controller: CoachSettingsSheetController;
}

export function WorkspaceSettingsSection({ controller }: WorkspaceSettingsSectionProps) {
  const {
    workspaceAuthority,
    className,
    companionInstallState,
    resourceSandbox,
    trainerWorkspace,
    remoteWorkspaceName,
    language,
    onRefreshWorkspaceAuthority,
    onChooseTrainerWorkspaceRoot,
    onMigrateTrainerWorkspaceRoot,
    onBackupTrainerWorkspace,
    onRestoreTrainerWorkspaceBackup,
    onChooseManagedDataFolder,
    onResetManagedDataFolder,
    onRemoveTrainerProject,
    onMoveManagedDataUnderRoot,
    copy,
    settingsGlobalCopy,
    managedDataSourceLabel,
    showManagedDataRecommendedCard,
    showManagedDataCustomCard,
    showManagedDataFallbackNote,
    managedDataUnderRoot,
    addedProjectRows,
  } = controller;
  return (
    <>
          <header className="settings-section-head">
            <span id="settings-section-workspace-title" className="eyebrow">
              {resolveWorkbenchCopy(language).workspaceRootControl}
            </span>
          </header>
          <div className="settings-sheet__minor-body">
            <WorkspaceRootRecoveryPanel
              trainerWorkspace={trainerWorkspace}
              onChooseRoot={onChooseTrainerWorkspaceRoot}
            />
            {resourceSandbox ? (
              <section className="settings-sheet__workspace-card" data-settings-subsection="data-area">
                <div className="settings-sheet__authority-block-head">
                  <span className="eyebrow">{copy.workspaceDataArea}</span>
                </div>
                <p className="settings-sheet__note settings-sheet__note--compact">
                  {managedDataUnderRoot
                    ? copy.workspaceDataUnderRoot
                    : copy.workspaceDataInAppFolder}
                </p>
                {!managedDataUnderRoot ? (
                  <div className="settings-actions settings-actions--compact">
                    <ActionButton
                      fullWidth={false}
                      icon={<DataFolderIcon size={14} />}
                      label={copy.workspaceDataMoveUnderRoot}
                      detail={settingsText(language, "移动数据并重启后端", "Move data and restart")}
                      onClick={onMoveManagedDataUnderRoot}
                    />
                  </div>
                ) : null}
              </section>
            ) : null}

            <section className="settings-sheet__workspace-card" data-settings-subsection="added-projects">
              <div className="settings-sheet__authority-block-head">
                <span className="eyebrow">{copy.addedProjects}</span>
              </div>
              {addedProjectRows.length === 0 ? (
                <p className="settings-sheet__note settings-sheet__note--compact">
                  {copy.addedProjectsEmpty}
                </p>
              ) : (
                <ul className="settings-added-projects" role="list">
                  {addedProjectRows.map((project) => (
                    <li
                      key={project.projectPath}
                      className="settings-added-projects__row"
                      data-added-project-current={project.isCurrent ? "true" : undefined}
                    >
                      <div className="settings-added-projects__copy">
                        <span className="settings-added-projects__name" title={project.projectPath}>
                          {project.projectName}
                          {project.isCurrent ? (
                            <span className="settings-added-projects__badge">
                              {copy.addedProjectsCurrent}
                            </span>
                          ) : project.adoptionMode === "browse" ? (
                            <span className="settings-added-projects__badge settings-added-projects__badge--browse">
                              {copy.addedProjectsBrowse}
                            </span>
                          ) : null}
                        </span>
                        <span
                          className="settings-sheet__path-value settings-added-projects__path"
                          title={project.projectPath}
                        >
                          {project.projectPath}
                        </span>
                      </div>
                      {onRemoveTrainerProject ? (
                        <button
                          type="button"
                          className="toolbar-button settings-added-projects__remove"
                          onClick={() => onRemoveTrainerProject(project.projectPath)}
                        >
                          {copy.projectRemove}
                        </button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
              <p className="settings-sheet__note settings-sheet__note--compact">
                {copy.projectRemoveNote}
              </p>
            </section>
            {remoteWorkspaceName ? <section className="settings-sheet__workspace-card" data-settings-subsection="remote-support">
                {(() => {
                  const remoteSupportCopy = REMOTE_SUPPORT_COPY[language];
                  const view = remoteSupportStateView(language, companionInstallState);
                  return (
                    <>
                <div className="settings-sheet__authority-block-head">
                  <span className="eyebrow">
                    <RemoteIcon size={12} />
                    {remoteSupportCopy.sectionTitle}
                  </span>
                </div>
                <div className="settings-sheet__summary-grid">
                  <SummaryCard
                    label={remoteSupportCopy.remoteHost}
                    value={remoteWorkspaceName}
                  />
                </div>
                <p className="settings-sheet__note settings-sheet__note--compact">
                  {remoteSupportCopy.intro}
                </p>
                                      {view.note ? (
                        <p className="settings-sheet__note settings-sheet__note--compact">{view.note}</p>
                      ) : null}
                      <button
                        type="button"
                        className="toolbar-button"
                        disabled={view.disabled}
                        onClick={() =>
                          postWebviewMessage({
                            type: "command/execute",
                            payload: { commandId: trainerCommands.remoteInstallCompanion },
                          })
                        }
                      >
                        {view.button}
                      </button>
                    </>
                  );
                })()}
            </section> : null}

            <details className="settings-sheet__workspace-card settings-workspace-advanced" data-settings-subsection="workspace-advanced">
              <summary>{copy.workspaceAdvanced}</summary>
              <div className="settings-sheet__stack settings-sheet__stack--tight">
                {resourceSandbox ? (
                  <>
                    <div className="settings-actions settings-actions--compact">
                      <ActionButton
                        fullWidth={false}
                        icon={<DataFolderIcon size={14} />}
                        label={copy.managedDataFolderChoose}
                        detail={settingsText(language, "切换并重启后端", "Switch and restart")}
                        onClick={onChooseManagedDataFolder}
                      />
                      <ActionButton
                        fullWidth={false}
                        icon={<ReloadIcon size={14} />}
                        label={copy.managedDataFolderReset}
                        detail={settingsText(language, "回到推荐目录", "Return to recommended")}
                        onClick={onResetManagedDataFolder}
                      />
                    </div>
                    <div className="settings-sheet__summary-grid">
                      <SummaryCard
                        label={copy.effectiveNow}
                        value={
                          <span
                            className="settings-sheet__path-value"
                            title={resourceSandbox.effectivePath}
                          >
                            {resourceSandbox.effectivePath}
                          </span>
                        }
                        detail={managedDataSourceLabel}
                      />
                      {showManagedDataRecommendedCard ? (
                        <SummaryCard
                          label={copy.managedDataFolderRecommended}
                          value={
                            <span
                              className="settings-sheet__path-value"
                              title={resourceSandbox.defaultPath}
                            >
                              {resourceSandbox.defaultPath}
                            </span>
                          }
                        />
                      ) : null}
                      {showManagedDataCustomCard ? (
                        <SummaryCard
                          label={copy.managedDataFolderCustom}
                          value={
                            <span
                              className="settings-sheet__path-value"
                              title={resourceSandbox.configuredPath}
                            >
                              {resourceSandbox.configuredPath}
                            </span>
                          }
                        />
                      ) : null}
                    </div>
                    {showManagedDataFallbackNote ? (
                      <p className="settings-sheet__note settings-sheet__note--compact">
                        {copy.managedDataFolderFallbackNote}
                      </p>
                    ) : null}
                  </>
                ) : null}
                <div className="settings-actions settings-actions--compact">
                  <ActionButton
                    fullWidth={false}
                    icon={<RefreshIcon size={14} />}
                    label={settingsGlobalCopy.workspaceRootMigrate}
                    detail={settingsGlobalCopy.workspaceRootMigrateDetail}
                    onClick={onMigrateTrainerWorkspaceRoot}
                  />
                  <ActionButton
                    fullWidth={false}
                    icon={<FileIcon size={14} />}
                    label={settingsGlobalCopy.workspaceRootBackup}
                    detail={settingsGlobalCopy.workspaceRootBackupDetail}
                    onClick={onBackupTrainerWorkspace}
                  />
                  <ActionButton
                    fullWidth={false}
                    icon={<UploadIcon size={14} />}
                    label={settingsGlobalCopy.workspaceRootRestore}
                    detail={settingsGlobalCopy.workspaceRootRestoreDetail}
                    onClick={onRestoreTrainerWorkspaceBackup}
                  />
                </div>
                <div className="settings-sheet__authority-block">
                  <div className="settings-sheet__authority-block-head">
                    <span className="eyebrow">{copy.currentWorkspace}</span>
                    <ActionButton
                      fullWidth={false}
                      icon={<ReloadIcon size={14} />}
                      label={copy.refreshWorkspaceAuthority}
                      detail={settingsStatusPhrase(language, "rereadSandboxBoundary")}
                      onClick={onRefreshWorkspaceAuthority}
                    />
                  </div>
                  {workspaceAuthority ? (
                    <WorkspaceAuthoritySummary
                      language={language}
                      authority={workspaceAuthority}
                      className="workspace-authority-summary--compact"
                    />
                  ) : (
                    <div className="empty-state settings-sheet__authority-empty">
                      <span className="empty-state__icon" aria-hidden="true">
                        <SettingsPreferencesIcon size={16} />
                      </span>
                      <span className="empty-state__title">{copy.workspaceAuthorityEmpty}</span>
                    </div>
                  )}
                </div>
              </div>
            </details>
          </div>
    </>
  );
}
