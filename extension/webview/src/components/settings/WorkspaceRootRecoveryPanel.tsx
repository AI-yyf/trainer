import { ActionButton } from "../common";
import { FolderIcon } from "../icons";
import { useTranslation } from "../../lib/i18n/useTranslation";
import type { TrainerWorkspaceAdmission } from "../../lib/types";

export interface WorkspaceRootRecoveryPanelProps {
  trainerWorkspace?: TrainerWorkspaceAdmission;
  onChooseRoot?: () => void;
}

/**
 * Unified workspace-root card (P0 one-root model): the main view shows exactly
 * one root — its path plus the choose/change action. Migration, backup,
 * restore, authority refresh, and sandbox boundary live in the section's
 * collapsed "advanced" disclosure (owned by CoachSettingsView).
 */
export function WorkspaceRootRecoveryPanel({
  trainerWorkspace,
  onChooseRoot,
}: WorkspaceRootRecoveryPanelProps) {
  const { t } = useTranslation();
  const rootPath = trainerWorkspace?.rootPath?.trim();
  const rootIsReady = Boolean(rootPath && trainerWorkspace?.status !== "root-missing");

  if (rootIsReady) {
    return (
      <div className="workspace-root-recovery workspace-root-recovery--ready">
        {rootPath ? (
          <p className="workspace-root-recovery__path" title={rootPath}>
            <span>{t("workspaceRootPath")}</span>
            <code>{rootPath}</code>
          </p>
        ) : null}
        <ActionButton
          icon={<FolderIcon size={14} />}
          label={t("workspaceRootChange")}
          detail={t("workspaceRootChangeDetail")}
          onClick={onChooseRoot}
        />
      </div>
    );
  }

  return (
    <section className="workspace-root-recovery" aria-label={t("workspaceRootControl")}>
      <div className="workspace-root-recovery__status">
        <span
          className="workspace-root-recovery__status-dot workspace-root-recovery__status-dot--missing"
          aria-hidden="true"
        />
        <div className="workspace-root-recovery__status-copy">
          <p className="workspace-root-recovery__detail">
            {t("workspaceAdmissionRootMissingDetail")}
          </p>
        </div>
      </div>
      <ActionButton
        icon={<FolderIcon size={14} />}
        label={t("workspaceAdmissionSelectRoot")}
        detail={t("workspaceAdmissionRootMissing")}
        tone="accent"
        onClick={onChooseRoot}
      />
    </section>
  );
}
