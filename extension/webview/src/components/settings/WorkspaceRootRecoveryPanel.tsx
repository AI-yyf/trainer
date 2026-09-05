import { ActionButton } from "../common";
import { FileIcon, FolderIcon, RefreshIcon, UploadIcon } from "../icons";
import { useTranslation } from "../../lib/i18n/useTranslation";
import type { TrainerWorkspaceAdmission } from "../../lib/types";

export interface WorkspaceRootRecoveryPanelProps {
  trainerWorkspace?: TrainerWorkspaceAdmission;
  onChooseRoot?: () => void;
  onMigrateRoot?: () => void;
  onBackup?: () => void;
  onRestore?: () => void;
}

export function WorkspaceRootRecoveryPanel({
  trainerWorkspace,
  onChooseRoot,
  onMigrateRoot,
  onBackup,
  onRestore,
}: WorkspaceRootRecoveryPanelProps) {
  const { t } = useTranslation();
  const rootPath = trainerWorkspace?.rootPath?.trim();
  const rootIsReady = Boolean(rootPath && trainerWorkspace?.status !== "root-missing");

  const statusBlock = (
      <div className="workspace-root-recovery__status">
        <span
          className={`workspace-root-recovery__status-dot workspace-root-recovery__status-dot--${
            rootIsReady ? "ready" : "missing"
          }`}
          aria-hidden="true"
        />
        <div className="workspace-root-recovery__status-copy">
          <h3 className="workspace-root-recovery__title">{t("workspaceRootControl")}</h3>
          <p className="workspace-root-recovery__detail">
            {rootIsReady ? t("workspaceRootReady") : t("workspaceAdmissionRootMissingDetail")}
          </p>
        </div>
      </div>
  );

  if (rootIsReady) {
    return (
      <details className="workspace-root-recovery workspace-root-recovery--ready" aria-label={t("workspaceRootControl")}>
        <summary>
          <span>{t("workspaceRootControl")}</span>
          <em>{t("workspaceRootReady")}</em>
        </summary>
        {statusBlock}
        {rootPath ? (
          <p className="workspace-root-recovery__path" title={rootPath}>
            <span>{t("workspaceRootPath")}</span>
            <code>{rootPath}</code>
          </p>
        ) : null}
        <ActionButton
          icon={<RefreshIcon size={14} />}
          label={t("workspaceRootMigrate")}
          detail={t("workspaceRootMigrateDetail")}
          tone="accent"
          onClick={onMigrateRoot}
        />
        <details className="workspace-root-recovery__more">
          <summary>{t("workspaceRootRecovery")}</summary>
          <div className="workspace-root-recovery__actions">
            <ActionButton
              icon={<FileIcon size={14} />}
              label={t("workspaceRootBackup")}
              detail={t("workspaceRootBackupDetail")}
              onClick={onBackup}
            />
            <ActionButton
              icon={<UploadIcon size={14} />}
              label={t("workspaceRootRestore")}
              detail={t("workspaceRootRestoreDetail")}
              onClick={onRestore}
            />
            <ActionButton
              icon={<FolderIcon size={14} />}
              label={t("workspaceRootChange")}
              detail={t("workspaceRootChangeDetail")}
              onClick={onChooseRoot}
            />
          </div>
        </details>
      </details>
    );
  }

  return (
    <section className="workspace-root-recovery" aria-label={t("workspaceRootControl")}>
      {statusBlock}
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
