import { MemorySharingPanel } from "../MemorySharingPanel";
import {
  ChoiceList,
  SimpleInfoRow,
  SummaryCard
} from "../SettingsControls";
import { TelemetryOptInPanel } from "../TelemetryOptInPanel";

import { LANGUAGE_LABELS, SUPPORTED_LANGUAGES } from "../../../../../../shared/src/types";
import { ActionButton } from "../../common";
import { ReloadIcon } from "../../icons/inline";
import { SettingsSkillsIcon } from "../../icons/navigation/settingsNav";
import {
  memoryShareSourceLabel,
  settingsPhrase
} from "../coachSettingsHelpers";
import { settingsText } from "../settingsText";
import type { CoachSettingsSheetController } from "../useCoachSettingsSheetController";

export function TeachingSettingsSection({ controller }: { controller: CoachSettingsSheetController }) {
  const {
    answerMode,
    teachingStyle,
    onAnswerModeChange,
    onTeachingStyleChange,
    copy,
    settingsGlobalCopy,
    answerStyle,
    selectAnswerStyle,
    teachingStyleItems,
    coachSettingsAutosaveNode,
    coachBehaviorSummary,
  } = controller;
  return (
    <>
          <header className="settings-section-head">
            <span id="settings-section-teaching-title" className="eyebrow">
              {settingsGlobalCopy.settingsTeachingPrefs}
            </span>
            <span className="settings-section-head__summary">{coachBehaviorSummary}</span>
            {coachSettingsAutosaveNode}
          </header>
          <div className="settings-sheet__minor-body settings-sheet__defaults-body">
              <div
                className="settings-answer-style"
                role="radiogroup"
                aria-label={settingsGlobalCopy.settingsAnswerStyle}
                data-settings-answer-style={answerStyle}
              >
                <span className="eyebrow">{settingsGlobalCopy.settingsAnswerStyle}</span>
                <div className="settings-answer-style__options">
                  {([
                    { value: "simple", label: settingsGlobalCopy.answerStyleSimple },
                    { value: "balanced", label: settingsGlobalCopy.answerStyleBalanced },
                    { value: "deep", label: settingsGlobalCopy.answerStyleDeep },
                    { value: "custom", label: settingsGlobalCopy.answerStyleCustom },
                  ] as const).map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      role="radio"
                      aria-checked={answerStyle === option.value}
                      className={`toolbar-button settings-sheet__choice-pill settings-answer-style__option${
                        answerStyle === option.value ? " is-active" : ""
                      }`}
                      onClick={() => selectAnswerStyle(option.value)}
                    >
                      <span>{option.label}</span>
                    </button>
                  ))}
                </div>
                <p className="settings-sheet__note settings-sheet__note--compact">
                  {settingsGlobalCopy.settingsAnswerStyleHint}
                </p>
              </div>

              <div className="settings-grid settings-grid--compact settings-grid--tight">
                <div className="settings-row">
                  <span className="eyebrow">{copy.answerMode}</span>
                  <ChoiceList
                    active={answerMode}
                    items={[
                      { label: copy.auto, value: "auto" },
                      { label: copy.coachFirst, value: "coach-first" },
                      { label: copy.balanced, value: "balanced" },
                      { label: copy.direct, value: "direct" },
                    ]}
                    onChange={onAnswerModeChange}
                  />
                </div>
                <div className="settings-row">
                  <span className="eyebrow">{copy.teachingStyle}</span>
                  <ChoiceList
                    active={teachingStyle}
                    items={teachingStyleItems}
                    onChange={onTeachingStyleChange}
                  />
                </div>
              </div>



          </div>
    </>
  );
}

export interface PreferencesSettingsSectionProps {
  controller: CoachSettingsSheetController;
  onLaunchBrowserCapture: () => void;
  onInstallBrowserCapture: () => void;
  onOpenBrowserExtensionsPage: () => void;
}

export function PreferencesSettingsSection({
  controller,
  onLaunchBrowserCapture,
  onInstallBrowserCapture,
  onOpenBrowserExtensionsPage,
}: PreferencesSettingsSectionProps) {
  const {
    nextReviewDue,
    onResetDefaults,
    backendConnectionState,
    memoryShareGrants,
    personalAccountTrusted,
    telemetryOptIn,
    themePreference,
    learningSurfaceAlignment,
    language,
    onThemePreferenceChange,
    onLearningSurfaceAlignmentChange,
    onLanguageChange,
    onCoachDefaultsChange,
    onGrantMemoryShare,
    onRevokeMemoryShare,
    onSetPersonalAccountTrust,
    onTelemetryOptInChange,
    onTelemetryStatusRefresh,
    onRefreshMemory,
    copy,
    settingsGlobalCopy,
    browserCaptureCopy,
    surfaceAlignmentCopy,
    memoryScope,
    workingSetMode,
    reviewCadence,
    reviewReminderMode,
    workspaceMemoryToggles,
    canManageMemoryShares,
    memorySharingSummary,
    localizedCoachStateText,
    memoryScopeRuntimeSummary,
    reviewCadenceItems,
    reviewReminderItems,
    updateWorkspaceMemoryToggles,
    advancedSummaryText,
    runtimeSummaryText,
    coachStateSummaryText,
    coachSettingsAutosaveNode,
    runtimeFlowSummary,
    rememberedRows,
    remembersSummary,
  } = controller;
  return (
    <>
          <header className="settings-section-head">
            <span id="settings-section-preferences-title" className="eyebrow">
              {settingsGlobalCopy.settingsPreferences}
            </span>
            <span className="settings-section-head__summary">{advancedSummaryText}</span>
            {coachSettingsAutosaveNode}
          </header>
          <div className="settings-sheet__minor-body settings-sheet__defaults-body">
              <div className="settings-grid settings-grid--compact settings-grid--tight">
                <div className="settings-row" data-settings-language="true">
                  <span className="eyebrow">{copy.language}</span>
                  <ChoiceList
                    active={language}
                    items={SUPPORTED_LANGUAGES.map((value) => ({
                      label: LANGUAGE_LABELS[value],
                      value,
                    }))}
                    onChange={onLanguageChange}
                  />
                </div>
              </div>
            <div className="settings-subsection" data-settings-subsection="appearance">
              <span className="eyebrow settings-subsection__title">{settingsGlobalCopy.settingsAppearance}</span>
              <div className="settings-grid settings-grid--compact settings-grid--tight">
                <div className="settings-row">
                  <span className="eyebrow">{copy.theme}</span>
                  <ChoiceList
                    active={themePreference}
                    items={[
                      { label: copy.system, value: "system" },
                      { label: copy.light, value: "light" },
                      { label: copy.dark, value: "dark" },
                    ]}
                    onChange={onThemePreferenceChange}
                  />
                </div>
                <div className="settings-row">
                  <span className="eyebrow">{surfaceAlignmentCopy.label}</span>
                  <ChoiceList
                    active={learningSurfaceAlignment}
                    items={[
                      { label: surfaceAlignmentCopy.left, value: "left" },
                      { label: surfaceAlignmentCopy.right, value: "right" },
                    ]}
                    onChange={onLearningSurfaceAlignmentChange}
                  />
                </div>
              </div>
            </div>

            <div className="settings-subsection" data-settings-subsection="browser-capture">
              <span className="eyebrow settings-subsection__title">{browserCaptureCopy.title}</span>
              <p className="settings-sheet__note settings-sheet__note--compact">{browserCaptureCopy.body}</p>
              <div className="settings-actions settings-actions--compact">
                <button
                  type="button"
                  className="button"
                  data-browser-capture-action="launch"
                  onClick={onLaunchBrowserCapture}
                >
                  {browserCaptureCopy.launch}
                </button>
                <button
                  type="button"
                  className="toolbar-button"
                  data-browser-capture-action="install"
                  onClick={onInstallBrowserCapture}
                >
                  {browserCaptureCopy.install}
                </button>
                <button
                  type="button"
                  className="toolbar-button"
                  data-browser-capture-action="open-extensions"
                  onClick={onOpenBrowserExtensionsPage}
                >
                  {browserCaptureCopy.open}
                </button>
              </div>
              <p className="settings-sheet__note settings-sheet__note--compact">{browserCaptureCopy.hint}</p>
            </div>

            <div className="settings-subsection" data-settings-subsection="memory">
              <span className="eyebrow settings-subsection__title">{settingsGlobalCopy.settingsMemoryPrivacy}</span>
              <div className="settings-grid settings-grid--compact settings-grid--tight">
                <div className="settings-row">
                  <span className="eyebrow">{copy.memoryScope}</span>
                  <ChoiceList
                    active={memoryScope}
                    items={[
                      { label: copy.memoryScopeProject, value: "project" },
                      { label: copy.memoryScopePersonal, value: "personal" },
                      { label: copy.memoryScopeSession, value: "session" },
                    ]}
                    onChange={(value) => onCoachDefaultsChange?.({ memoryScope: value })}
                  />
                </div>
                <div className="settings-row">
                  <span className="eyebrow">{copy.workingSet}</span>
                  <ChoiceList
                    active={workingSetMode}
                    items={[
                      { label: copy.workingSetFocused, value: "focused" },
                      { label: copy.workingSetBalanced, value: "balanced" },
                      { label: copy.workingSetBroad, value: "broad" },
                    ]}
                    onChange={(value) => onCoachDefaultsChange?.({ workingSetMode: value })}
                  />
                </div>
              </div>
          {rememberedRows.length ? (
            <div className="settings-sheet__remembered-panel">
              <div className="settings-sheet__remembered-summary">
                <span className="eyebrow">
                  {settingsPhrase(language, "trainerRemembers")}
                </span>
                {remembersSummary ? (
                  <span className="settings-sheet__remembered-preview">{remembersSummary}</span>
                ) : null}
              </div>
              <div className="settings-sheet__simple-list" aria-label={settingsPhrase(language, "trainerRemembers")}>
                {rememberedRows.map((row) => (
                  <SimpleInfoRow key={row.label} label={row.label} value={row.value} />
                ))}
              </div>
            </div>
          ) : null}

          <div className="settings-sheet__utility-grid">
            <section className="settings-sheet__workspace-card">
              <span className="eyebrow">{copy.memoryStrategy}</span>
              <div className="settings-sheet__status settings-sheet__status--dense">
                <button
                  className={`context-chip ${workspaceMemoryToggles.decisions ? "is-enabled" : ""}`}
                  type="button"
                  onClick={() =>
                    updateWorkspaceMemoryToggles({ decisions: !workspaceMemoryToggles.decisions })
                  }
                >
                  <span>{copy.rememberDecisions}</span>
                  <strong>{workspaceMemoryToggles.decisions ? copy.on : copy.off}</strong>
                </button>
                <button
                  className={`context-chip ${workspaceMemoryToggles.patterns ? "is-enabled" : ""}`}
                  type="button"
                  onClick={() =>
                    updateWorkspaceMemoryToggles({ patterns: !workspaceMemoryToggles.patterns })
                  }
                >
                  <span>{copy.rememberPatterns}</span>
                  <strong>{workspaceMemoryToggles.patterns ? copy.on : copy.off}</strong>
                </button>
                <button
                  className={`context-chip ${workspaceMemoryToggles.resources ? "is-enabled" : ""}`}
                  type="button"
                  onClick={() =>
                    updateWorkspaceMemoryToggles({ resources: !workspaceMemoryToggles.resources })
                  }
                >
                  <span>{copy.rememberResources}</span>
                  <strong>{workspaceMemoryToggles.resources ? copy.on : copy.off}</strong>
                </button>
              </div>
            </section>
          </div>

          <MemorySharingPanel
            copy={copy}
            canManageMemoryShares={canManageMemoryShares}
            memorySharingSummary={memorySharingSummary}
            memoryShareGrants={memoryShareGrants}
            memoryShareSourceLabel={memoryShareSourceLabel}
            personalAccountTrusted={personalAccountTrusted === true}
            onSetPersonalAccountTrust={onSetPersonalAccountTrust}
            onGrantMemoryShare={onGrantMemoryShare}
            onRevokeMemoryShare={onRevokeMemoryShare}
          />

          <TelemetryOptInPanel
            language={language}
            connectionState={backendConnectionState}
            telemetryOptIn={telemetryOptIn}
            onTelemetryOptInChange={onTelemetryOptInChange}
            onTelemetryStatusRefresh={onTelemetryStatusRefresh}
          />
            </div>

            <div className="settings-subsection" data-settings-subsection="review">
              <div className="settings-sheet__utility-grid">
                <section className="settings-sheet__workspace-card">
                  <span className="eyebrow settings-subsection__title">{copy.reviewStrategy}</span>
                  <div className="settings-sheet__stack">
                    <div className="settings-sheet__compact-row">
                      <span>{copy.reviewRhythmPace}</span>
                      <ChoiceList
                        active={reviewCadence}
                        items={reviewCadenceItems}
                        onChange={(value) => onCoachDefaultsChange?.({ reviewCadence: value })}
                      />
                    </div>
                    <div className="settings-sheet__compact-row">
                      <span>{copy.reviewRhythmReminder}</span>
                      <ChoiceList
                        active={reviewReminderMode}
                        items={reviewReminderItems}
                        onChange={(value) => onCoachDefaultsChange?.({ reviewReminderMode: value })}
                      />
                    </div>
                  </div>
                </section>
              </div>
            </div>

            <div className="settings-subsection" data-settings-subsection="maintenance">
              <div className="settings-sheet__utility-grid">
                <section className="settings-sheet__workspace-card">
                  <span className="eyebrow">{copy.systemActions}</span>
                  <div className="settings-actions settings-actions--compact">
                    <ActionButton
                      fullWidth={false}
                      icon={<ReloadIcon size={14} />}
                      label={copy.refreshMemory}
                      detail={settingsText(language, "重建摘要", "Rebuild summary")}
                      onClick={onRefreshMemory}
                    />
                    <ActionButton
                      fullWidth={false}
                      icon={<SettingsSkillsIcon size={14} />}
                      label={copy.resetDefaults}
                      detail={settingsText(language, "推荐值", "Recommended")}
                      onClick={onResetDefaults}
                    />
                  </div>
                </section>
              </div>
          <div className="settings-sheet__minor-body settings-sheet__minor-body--flat">
              <div className="settings-sheet__summary-grid">
                <SummaryCard
                  label={copy.runtimeSection}
                  value={runtimeSummaryText}
                  detail={memoryScopeRuntimeSummary}
                />
                {localizedCoachStateText ? (
                  <SummaryCard
                    label={copy.coachState}
                    value={<span title={localizedCoachStateText}>{coachStateSummaryText}</span>}
                  />
                ) : null}
                {nextReviewDue ? <SummaryCard label={copy.nextReview} value={nextReviewDue} /> : null}
              </div>
              <p className="settings-sheet__note settings-sheet__note--compact">{runtimeFlowSummary}</p>
            </div>
            </div>
          </div>
    </>
  );
}
