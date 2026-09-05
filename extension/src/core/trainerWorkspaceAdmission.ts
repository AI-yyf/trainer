import * as path from 'node:path';

import type {
  TrainerWorkspaceAdmissionView,
  TrainerWorkspaceReconciliationView,
  WorkspaceSnapshot,
} from './types';
import { resolveSovereignWorkspaceRootPath } from './workspaceRoots';
import type {
  TrainerWorkspacePendingReconciliation,
  TrainerWorkspaceService,
} from './trainerWorkspaceService';

export function resolveCurrentTrainerProjectPath(
  workspace: WorkspaceSnapshot,
): string | undefined {
  return resolveSovereignWorkspaceRootPath(workspace);
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
  const snapshot = await trainerWorkspace.toSnapshot(projectPath);

  if (!snapshot.workspaceReady) {
    return {
      status: 'root-missing',
      rootPath: snapshot.rootPath,
      projectName: projectPath ? path.basename(projectPath) || projectPath : undefined,
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
    projectName: path.basename(projectPath) || projectPath,
    projectPath,
    canonicalProjectPath: project?.canonicalProjectPath,
    identityStatus: project?.identityStatus ?? snapshot.manifest?.identityStatus,
    manifestRevision: project?.manifestRevision ?? snapshot.manifest?.manifestRevision,
    pathRevision: project?.pathRevision ?? snapshot.manifest?.pathRevision,
    updatedAt: project?.updatedAt,
    reconciliation: toReconciliationView(pending),
  };
}
