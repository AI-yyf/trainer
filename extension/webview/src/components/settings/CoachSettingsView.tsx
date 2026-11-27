import { SettingsIndex } from "../../templates/SettingsIndex";
import { SettingsDetail } from "../../templates/SettingsDetail";
import { SystemState } from "../../templates/SystemState";
import { normalizeProviderProtocol } from "../../../../../shared/src/providerProtocols";
import {
  providerModelTokenLimitsKey,
  readProviderModelTokenLimit,
  resolveProviderModelTokenState,
  withProviderModelTokenLimit,
} from "../../../../../shared/src/providerModelTokenLimits";
import { trainerCommands } from "../../../../../shared/src/commands";
import { postMessage as postWebviewMessage } from "../../lib/vscode";
import { settingsText } from "./settingsText";
import { useCoachSettingsHostFacts } from "./useCoachSettingsViewState";
import { useProviderConnection } from "../../app/providerConnectionContext";
import {
  settingsPhrase,
  type CoachSettingsLabels,
  type CoachSettingsViewProps,
  type CoachSettingsViewSheetProps,
  type ProviderDraft,
  type SettingsActionFeedback,
  type SettingsSectionStatus,
} from "./coachSettingsHelpers";
import { useCoachSettingsSheetController } from "./useCoachSettingsSheetController";
import {
  ConnectionSettingsLead,
  ConnectionSettingsSectionBody,
} from "./sections/ConnectionSettingsSection";
import { WorkspaceSettingsSection } from "./sections/WorkspaceSettingsSection";
import {
  PreferencesSettingsSection,
  TeachingSettingsSection,
} from "./sections/TeachingAndPreferencesSection";
import { SkillsSettingsSection } from "./sections/SkillsSettingsSection";
import { AdvancedSettingsSection } from "./sections/AdvancedSettingsSection";

export type {
  CoachSettingsLabels,
  CoachSettingsViewProps,
  ProviderDraft,
  SettingsActionFeedback,
  SettingsSectionStatus,
};

/**
 * Settings shell (the exported, lazily loaded view). Derives the sunk values
 * from the store and App's published connection instance, then renders the
 * sheet with the exact same fields it always received.
 */
export function CoachSettingsView({
  sectionRequest,
  skillSharing,
  capabilityVerdict,
  providerImageInputState,
  coachStateSummary,
  reviewRhythmSummary,
  providerStatus,
  coachDefaultsStatus,
  workspaceControlStatus,
  providerSaveBusy,
  companionInstallState,
  onCoachSettingsMutated,
  onSaveCoachSettings,
  onSaveProvider,
  onSaveProviderProfile,
  onUseProviderTemplateLabel,
  onRefreshProviderProfiles,
  onSwitchProviderProfile,
  onRefreshProviderModels,
  onTestProvider,
  onCancelProviderTest,
  onRestartSidecar,
  onClearProvider,
  onOpenConfig,
  onResetDefaults,
}: CoachSettingsViewProps) {
  // App's single provider-connection controller instance (draft, speed test,
  // API-key focus): the same instance App's composer and deep links use.
  const {
    providerDraft,
    setProviderDraft,
    resetProviderDraft,
    providerApiKeyFocusRequest,
    providerSpeedTestResults,
    providerSpeedTestPending,
    runProviderSpeedTest,
  } = useProviderConnection();
  // Host-owned workspace/session facts, derived with App's exact expressions.
  const {
    settingsWorkspaceId,
    liveSandboxState,
    effectiveWorkspaceTrustState,
    coachSignal,
    nextReviewDue,
  } = useCoachSettingsHostFacts();
  return (
    <CoachSettingsViewSheet
      sectionRequest={sectionRequest}
      skillSharing={skillSharing}
      capabilityVerdict={capabilityVerdict}
      providerImageInputState={providerImageInputState}
      coachStateSummary={coachStateSummary}
      reviewRhythmSummary={reviewRhythmSummary}
      providerStatus={providerStatus}
      coachDefaultsStatus={coachDefaultsStatus}
      workspaceControlStatus={workspaceControlStatus}
      providerSaveBusy={providerSaveBusy}
      companionInstallState={companionInstallState}
      onCoachSettingsMutated={onCoachSettingsMutated}
      onSaveCoachSettings={onSaveCoachSettings}
      onSaveProvider={onSaveProvider}
      onSaveProviderProfile={onSaveProviderProfile}
      onUseProviderTemplateLabel={onUseProviderTemplateLabel}
      onRefreshProviderProfiles={onRefreshProviderProfiles}
      onSwitchProviderProfile={onSwitchProviderProfile}
      onRefreshProviderModels={onRefreshProviderModels}
      onTestProvider={onTestProvider}
      onCancelProviderTest={onCancelProviderTest}
      onRestartSidecar={onRestartSidecar}
      onClearProvider={onClearProvider}
      onOpenConfig={onOpenConfig}
      onResetDefaults={onResetDefaults}
      workspaceId={settingsWorkspaceId}
      workspaceAuthority={liveSandboxState?.authority}
      workspaceTrustState={effectiveWorkspaceTrustState}
      className="settings-pane"
      coachSignal={coachSignal}
      nextReviewDue={nextReviewDue}
      providerDraft={providerDraft}
      providerApiKeyFocusRequest={providerApiKeyFocusRequest}
      providerSpeedTestResults={providerSpeedTestResults}
      providerSpeedTestPending={providerSpeedTestPending}
      onSpeedTestEndpoints={runProviderSpeedTest}
      onResetProviderDraft={resetProviderDraft}
      onProviderDraftChange={(patch) => {
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
          const protocolChanged =
            hasProtocol && normalizeProviderProtocol(current.protocol) !== nextProtocol;

          if (protocolChanged) {
            return {
              ...current,
              ...patch,
              protocol: nextProtocol,
              model: "",
              ...(hasModel && typeof patch.model === "string" ? { model: patch.model } : {}),
              capabilities: patch.capabilities,
              requestDefaults: patch.requestDefaults ?? {},
              thinkingConfig: patch.thinkingConfig,
              allowedModels: patch.allowedModels ?? [],
              deniedModels: patch.deniedModels ?? [],
              contextWindowTokens: undefined,
              maxOutputTokens: undefined,
              modelTokenLimits: undefined,
              catalogModels: [],
            };
          }

          if (hasBaseUrl && normalizedCurrentBaseUrl !== normalizedNextBaseUrl) {
            return {
              ...current,
              ...patch,
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
    />
  );
}

function CoachSettingsViewSheet(props: CoachSettingsViewSheetProps) {
  const controller = useCoachSettingsSheetController(props);
  const {
    activeSettingsCategory,
    availabilityState,
    backendRecovery,
    classes,
    connectionAnchorRef,
    copy,
    language,
    openSettingsCategorySection,
    preferencesAnchorRef,
    resolvedWorkspaceTrustState,
    revealSettingsSection,
    sectionFlash,
    setSettingsIndexOpen,
    settingsGlobalCopy,
    settingsIndexItems,
    settingsIndexOpen,
    settingsNavItems,
    settingsStatusConnectionReady,
    teachingPrefsAnchorRef,
    visibleSettingsStatusIssues,
    workspaceAnchorRef,
    workspaceTrustSentence,
  } = controller;

  const handleLaunchBrowserCapture = () =>
    postWebviewMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.launchBrowserCapture },
    });

  const handleInstallBrowserCapture = () =>
    postWebviewMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.installBrowserCaptureForBrowser },
    });

  const handleOpenBrowserExtensionsPage = () =>
    postWebviewMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.openBrowserExtensionsPage },
    });

  return (
    <section className={classes} aria-labelledby="coach-settings-view-title">
      <h2 id="coach-settings-view-title" className="sr-only">
        {copy.title}
      </h2>

      {settingsIndexOpen && backendRecovery ? availabilityState : null}
      {settingsIndexOpen ? (
        <SettingsIndex
          title={copy.title}
          items={settingsIndexItems}
          onSelect={openSettingsCategorySection}
        />
      ) : null}
      <div hidden={settingsIndexOpen}>
      <SettingsDetail
        parent={copy.title}
        section={activeSettingsCategory}
        title={settingsNavItems.find((item) => item.id === activeSettingsCategory)?.label ?? copy.title}
        onBack={() => setSettingsIndexOpen(true)}
        nav={
          <SettingsIndex
            title={copy.title}
            items={settingsIndexItems}
            onSelect={openSettingsCategorySection}
            variant="rail"
            activeId={activeSettingsCategory}
          />
        }
      >
      <div className="settings-sheet__body settings-sheet__body--hierarchical">
        {visibleSettingsStatusIssues.length > 0 ? (
        <div
          className="settings-status-bar settings-status-bar--blockers"
          role="region"
          aria-label={settingsGlobalCopy.settingsStatusRegionLabel}
          data-settings-status-bar="true"
          data-settings-status-connection={settingsStatusConnectionReady ? "ready" : "setup"}
        >
          {visibleSettingsStatusIssues.map((issue) => (
            <div
              key={issue.id}
              className={`settings-status-bar__row is-${issue.id}`}
              data-settings-status-issue={issue.id}
            >
              <div
                data-workspace-trust-state={issue.id === "trust" ? resolvedWorkspaceTrustState : undefined}
                data-settings-workspace-trust={issue.id === "trust" ? "true" : undefined}
              >
                <SystemState
                  kind={issue.id === "trust" ? "permission-required" : issue.id === "unsaved" ? "information" : "provider-required"}
                  title={issue.id === "trust" ? workspaceTrustSentence : issue.label}
                >
              <button
                type="button"
                className={`button button--ghost button--compact settings-trust-action${
                  issue.id === "trust" && resolvedWorkspaceTrustState === "trusted"
                    ? " is-trusted"
                    : ""
                }`}
                data-settings-trust-action={issue.id === "trust" ? "true" : undefined}
                onClick={() => {
                  if (issue.action) {
                    issue.action();
                    if (issue.target !== activeSettingsCategory && issue.id !== "trust") {
                      revealSettingsSection(issue.target);
                    }
                    return;
                  }
                  revealSettingsSection(issue.target);
                }}
              >
                <span
                  className="settings-trust-action__state"
                  data-trust-state={issue.id === "trust" ? resolvedWorkspaceTrustState : undefined}
                  aria-hidden="true"
                />
                {issue.id === "trust"
                  ? settingsText(language, "信任此窗口", "Trust this window")
                  : issue.id === "key" || issue.id === "unsaved"
                    ? settingsPhrase(language, "editConfiguration")
                    : settingsGlobalCopy.settingsSectionConnection}
              </button>
                </SystemState>
              </div>
            </div>
          ))}
        </div>
        ) : null}

        <div className="settings-sheet__layout">
          <div className="settings-sheet__pane">
            {activeSettingsCategory === "connection" ? (
              <section className="settings-section settings-section--panel settings-section--setup settings-section--summary">
                <ConnectionSettingsLead controller={controller} />
                <div
                  ref={connectionAnchorRef}
                  className={`settings-anchor${sectionFlash === "connection" ? " settings-anchor--flash" : ""}`}
                  data-settings-section="connection"
                >
                  <ConnectionSettingsSectionBody controller={controller} />
                </div>
              </section>
            ) : null}

            {activeSettingsCategory === "workspace" ? (
              <section
                ref={workspaceAnchorRef}
                className={`settings-section settings-section--flat settings-anchor${sectionFlash === "workspace" ? " settings-anchor--flash" : ""}`}
                data-settings-section="workspace"
                aria-labelledby="settings-section-workspace-title"
              >
                <WorkspaceSettingsSection controller={controller} />
              </section>
            ) : null}

            {activeSettingsCategory === "teaching" ? (
              <section
                ref={teachingPrefsAnchorRef}
                className={`settings-section settings-section--flat settings-anchor${sectionFlash === "teaching" ? " settings-anchor--flash" : ""}`}
                data-settings-section="teaching"
                aria-labelledby="settings-section-teaching-title"
              >
                <TeachingSettingsSection controller={controller} />
              </section>
            ) : null}

            {activeSettingsCategory === "preferences" ? (
              <section
                ref={preferencesAnchorRef}
                className={`settings-section settings-section--flat settings-anchor${sectionFlash === "preferences" ? " settings-anchor--flash" : ""}`}
                data-settings-section="preferences"
                aria-labelledby="settings-section-preferences-title"
              >
                <PreferencesSettingsSection
                  controller={controller}
                  onLaunchBrowserCapture={handleLaunchBrowserCapture}
                  onInstallBrowserCapture={handleInstallBrowserCapture}
                  onOpenBrowserExtensionsPage={handleOpenBrowserExtensionsPage}
                />
              </section>
            ) : null}

            {activeSettingsCategory === "teaching" ? (
              <section
                className="settings-section settings-section--flat settings-anchor"
                data-settings-section="skills"
                aria-labelledby="settings-section-skills-title"
              >
                <SkillsSettingsSection controller={controller} />
              </section>
            ) : null}

            {activeSettingsCategory === "preferences" ? (
              <section
                className="settings-section settings-section--flat settings-anchor"
                data-settings-section="advanced"
                aria-labelledby="settings-section-advanced-title"
              >
                <AdvancedSettingsSection controller={controller} />
              </section>
            ) : null}
          </div>
        </div>
      </div>
      </SettingsDetail>
      </div>
    </section>
  );
}
