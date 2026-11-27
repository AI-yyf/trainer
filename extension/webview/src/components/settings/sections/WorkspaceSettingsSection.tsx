import {
  SummaryCard
} from "../SettingsControls";

import { trainerCommands } from "../../../../../../shared/src/commands";
import { resolveCopy as resolveWorkbenchCopy } from "../../../lib/i18n/copy";
import { REMOTE_SUPPORT_COPY,remoteSupportStateView } from "../../../lib/i18n/segments/remoteSupportCopy";
import { postMessage as postWebviewMessage } from "../../../lib/vscode";
import { WorkspaceAuthoritySummary } from "../../coach/parts/WorkspaceAuthoritySummary";
import { ActionButton } from "../../common";
import { FileIcon,RefreshIcon,UploadIcon } from "../../icons";
import { RemoteIcon } from "../../icons/brand/trainerBrand";
import { DataFolderIcon,ReloadIcon } from "../../icons/inline";
import { SettingsPreferencesIcon } from "../../icons/navigation/settingsNav";
import {
  settingsStatusPhrase
} from "../coachSettingsHelpers";
import { settingsText } from "../settingsText";
import type { CoachSettingsSheetController } from "../useCoachSettingsSheetController";
import { WorkspaceRootRecoveryPanel } from "../WorkspaceRootRecoveryPanel";

export interface WorkspaceSettingsSectionProps {
  controller: CoachSettingsSheetController;
}

export function WorkspaceSettingsSection({ controller }: WorkspaceSettingsSectionProps) {
  const {
    workspaceAuthority,
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
