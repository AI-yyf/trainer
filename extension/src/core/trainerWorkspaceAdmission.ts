import type {
  TrainerProjectListEntryView,
  TrainerProjectsListView,
  TrainerWorkspaceAdmissionView,
  TrainerWorkspaceReconciliationView,
  WorkspaceSnapshot,
} from './types';
import { basenameFs, resolveSovereignWorkspaceRootPath } from './workspaceRoots';
import { isRemoteWorkspaceSnapshot, resolveWorkspaceUri } from '../commands/workspaceContext';
import type {
  TrainerWorkspacePendingReconciliation,
  TrainerWorkspaceService,
} from './trainerWorkspaceService';

export function resolveCurrentTrainerProjectPath(
  workspace: WorkspaceSnapshot,
): string | undefined {
  return isRemoteWorkspaceSnapshot(workspace)
    ? resolveWorkspaceUri(workspace)
    : resolveSovereignWorkspaceRootPath(workspace);
}

function toReconciliationView(
  pending: TrainerWorkspacePendingReconciliation | undefined,
): TrainerWorkspaceReconciliationView | undefined {
  if (!pending) {
    return undefined;
  }
  return {
    reason: pending.reason,
    jobId: pending.jobId,
    updatedAt: pending.updatedAt,
    state: pending.state,
    availableActions: [...pending.availableActions],
  };
}

export async function resolveTrainerWorkspaceAdmission(
  trainerWorkspace: TrainerWorkspaceService,
  workspace: WorkspaceSnapshot,
): Promise<TrainerWorkspaceAdmissionView | undefined> {
  const projectPath = resolveCurrentTrainerProjectPath(workspace);
  const snapshot = await trainerWorkspace.toSnapshot(projectPath, {
    remote: isRemoteWorkspaceSnapshot(workspace),
  });

  if (!snapshot.workspaceReady) {
    return {
      status: 'root-missing',
      rootPath: snapshot.rootPath,
      projectName: projectPath ? basenameFs(projectPath) || projectPath : undefined,
      projectPath,
    };
  }

  if (!projectPath) {
    return {
      status: 'project-found',
      rootPath: snapshot.rootPath,
    };
  }

  const project = snapshot.currentProject;
  const pending = trainerWorkspace.getManagedProvisioningPending(projectPath);
  return {
    status: project?.adoptionMode ?? 'project-found',
    rootPath: snapshot.rootPath,
    rootId: project?.rootId ?? snapshot.manifest?.rootId,
    projectId: project?.projectId ?? project?.fingerprint,
    contextId: project?.contextId,
    projectName: basenameFs(projectPath) || projectPath,
    projectPath,
    canonicalProjectPath: project?.canonicalProjectPath,
    identityStatus: project?.identityStatus ?? snapshot.manifest?.identityStatus,
    manifestRevision: project?.manifestRevision ?? snapshot.manifest?.manifestRevision,
    pathRevision: project?.pathRevision ?? snapshot.manifest?.pathRevision,
    updatedAt: project?.updatedAt,
    reconciliation: toReconciliationView(pending),
  };
}

/**
 * Settings "added projects" list (Task: manage adopted projects). Sourced from
 * the same adoption state the admission flow writes — the workspace manifest's
 * project registry. Removal reuses the existing reference-only delete flow
 * (files are never touched); entries are sorted so the open project leads.
 */
export async function resolveTrainerProjectsList(
  trainerWorkspace: TrainerWorkspaceService,
  workspace: WorkspaceSnapshot,
): Promise<TrainerProjectsListView | undefined> {
  const currentProjectPath = resolveCurrentTrainerProjectPath(workspace);
  const snapshot = await trainerWorkspace.toSnapshot(currentProjectPath, {
    remote: isRemoteWorkspaceSnapshot(workspace),
  });
  const manifestProjects = Object.values(snapshot.manifest?.projects ?? {});
  const samePath = (left: string | undefined, right: string | undefined): boolean => {
    const a = left?.trim();
    const b = right?.trim();
    return Boolean(a && b) && a!.toLowerCase() === b!.toLowerCase();
  };
  const seen = new Set<string>();
  const projects: TrainerProjectListEntryView[] = [];
  for (const project of manifestProjects) {
    const projectPath = project.projectPath?.trim();
    if (!projectPath) {
      continue;
    }
    // 'ignored' rows are explicitly not "added" — they are the removal
    // outcome, so they never appear in the managed list.
    if (project.adoptionMode === 'ignored') {
      continue;
    }
    const dedupeKey = projectPath.toLowerCase();
    if (seen.has(dedupeKey)) {
      continue;
    }
    seen.add(dedupeKey);
    projects.push({
      projectPath,
      projectName: basenameFs(projectPath) || projectPath,
      adoptionMode: project.adoptionMode,
      identityStatus: project.identityStatus,
      isCurrent: samePath(projectPath, currentProjectPath),
      updatedAt: project.updatedAt,
    });
  }
  projects.sort((left, right) => {
    if (left.isCurrent !== right.isCurrent) {
      return left.isCurrent ? -1 : 1;
    }
    return left.projectName.localeCompare(right.projectName);
  });
  return {
    rootPath: snapshot.rootPath,
    projects,
  };
}
