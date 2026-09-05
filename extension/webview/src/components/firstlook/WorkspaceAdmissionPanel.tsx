import { useId } from "react";
import type { CopyKey } from "../../lib/i18n/copy";
import { useTranslation } from "../../lib/i18n/useTranslation";

export type WorkspaceAdmissionStatus =
  | "root-missing"
  | "project-found"
  | "managed"
  | "browse"
  | "ignored";

export interface WorkspaceAdmissionPanelProps {
  status: WorkspaceAdmissionStatus;
  projectName?: string;
  projectPath?: string;
  onSelectWorkspaceRoot?: () => void;
  onSelectProject?: () => void;
  onAddProject?: () => void;
  onBrowseProject?: () => void;
  onIgnoreProject?: () => void;
  onDeleteProject?: () => void;
  reconciliation?: {
    reason: string;
    state: "waiting" | "retry-required";
    updatedAt: string;
    jobId?: string;
    availableActions: readonly ("continue-waiting" | "retry" | "abandon")[];
  };
  onRetryAdmission?: () => void;
  onContinueAdmission?: () => void;
  onAbandonAdmission?: () => void;
  disabled?: boolean;
}

interface AdmissionAction {
  label: CopyKey;
  onClick: () => void;
}

const STATUS_COPY = {
  "root-missing": {
    label: "workspaceAdmissionRootMissing",
    detail: "workspaceAdmissionRootMissingDetail",
  },
  "project-found": {
    label: "workspaceAdmissionProjectFound",
    detail: "workspaceAdmissionProjectFoundDetail",
  },
  managed: {
    label: "workspaceAdmissionManaged",
    detail: "workspaceAdmissionManagedDetail",
  },
  browse: {
    label: "workspaceAdmissionBrowse",
    detail: "workspaceAdmissionBrowseDetail",
  },
  ignored: {
    label: "workspaceAdmissionIgnored",
    detail: "workspaceAdmissionIgnoredDetail",
  },
} satisfies Record<WorkspaceAdmissionStatus, { label: CopyKey; detail: CopyKey }>;

function asAction(label: CopyKey, onClick: (() => void) | undefined): AdmissionAction | undefined {
  return onClick ? { label, onClick } : undefined;
}

function withoutPrimary(
  primary: AdmissionAction | undefined,
  candidates: Array<AdmissionAction | undefined>,
): AdmissionAction[] {
  return candidates.filter((candidate): candidate is AdmissionAction => Boolean(candidate && candidate !== primary));
}

function resolveActions(props: WorkspaceAdmissionPanelProps): {
  primary?: AdmissionAction;
  secondary: AdmissionAction[];
} {
  const selectRoot = asAction("workspaceAdmissionSelectRoot", props.onSelectWorkspaceRoot);
  const selectProject = asAction("workspaceAdmissionSelectProject", props.onSelectProject);
  const add = asAction("workspaceAdmissionAdd", props.onAddProject);
  const browse = asAction("workspaceAdmissionBrowseAction", props.onBrowseProject);
  const ignore = asAction("workspaceAdmissionIgnore", props.onIgnoreProject);
  const remove = asAction("workspaceAdmissionDelete", props.onDeleteProject);
  const retry = asAction("workspaceAdmissionAdd", props.onRetryAdmission);
  const continueWaiting = asAction("workspaceAdmissionBrowseAction", props.onContinueAdmission);
  const abandon = asAction("workspaceAdmissionIgnore", props.onAbandonAdmission);

  if (props.reconciliation) {
    const primary = props.reconciliation.state === "waiting" ? continueWaiting ?? retry : retry;
    return { primary, secondary: withoutPrimary(primary, [retry, continueWaiting, abandon]) };
  }

  switch (props.status) {
    case "root-missing":
      return { primary: selectRoot, secondary: selectProject ? [selectProject] : [] };
    case "project-found": {
      const primary = add ?? selectProject ?? browse;
      return { primary, secondary: withoutPrimary(primary, [selectProject, add, browse, ignore]) };
    }
    case "managed":
      return { secondary: remove ? [remove] : [] };
    case "browse":
      return { primary: add, secondary: withoutPrimary(add, [ignore]) };
    case "ignored": {
      const primary = add ?? browse;
      return { primary, secondary: withoutPrimary(primary, [add, browse]) };
    }
  }
}

export function WorkspaceAdmissionPanel(props: WorkspaceAdmissionPanelProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const stateCopy = STATUS_COPY[props.status];
  const actions = resolveActions(props);
  const projectName = props.projectName?.trim();
  const projectPath = props.projectPath?.trim();

  return (
    <section className="workspace-admission" aria-labelledby={titleId} data-status={props.status}>
      <div className="workspace-admission__status" aria-live="polite">
        <span
          className={`workspace-admission__status-dot workspace-admission__status-dot--${props.status}`}
          aria-hidden="true"
        />
        <div className="workspace-admission__status-copy">
          <h3 id={titleId} className="workspace-admission__title">
            {t(stateCopy.label)}
          </h3>
          <p className="workspace-admission__detail">{t(stateCopy.detail)}</p>
        </div>
      </div>

      {props.reconciliation ? (
        <div className="workspace-admission__reconciliation" role="status">
          <p>{props.reconciliation.reason}</p>
          <p>{props.reconciliation.state} · {new Date(props.reconciliation.updatedAt).toLocaleString()}</p>
          <p>{props.reconciliation.state === "waiting" ? "Continue waiting or retry if the job does not progress." : "Retry the admission, or abandon the pending record without changing the project."}</p>
        </div>
      ) : null}

      {projectName || projectPath ? (
        <dl className="workspace-admission__project">
          {projectName ? (
            <div className="workspace-admission__project-row">
              <dt>{t("workspaceAdmissionProjectName")}</dt>
              <dd>{projectName}</dd>
            </div>
          ) : null}
          {projectPath ? (
            <div className="workspace-admission__project-row">
              <dt>{t("workspaceAdmissionProjectPath")}</dt>
              <dd className="workspace-admission__path" title={projectPath}>
                {projectPath}
              </dd>
            </div>
          ) : null}
        </dl>
      ) : null}

      {actions.primary || actions.secondary.length > 0 ? (
        <div className="workspace-admission__actions">
          {actions.primary ? (
            <button
              type="button"
              className="button button--accent workspace-admission__primary-action"
              onClick={actions.primary.onClick}
              disabled={props.disabled}
            >
              {t(actions.primary.label)}
            </button>
          ) : null}
          {actions.secondary.length > 0 ? (
            <div className="workspace-admission__secondary-actions">
              {actions.secondary.map((action) => (
                <button
                  key={action.label}
                  type="button"
                  className="button button--ghost workspace-admission__secondary-action"
                  onClick={action.onClick}
                  disabled={props.disabled}
                >
                  {t(action.label)}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
