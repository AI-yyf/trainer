import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult, StageMaterialItem } from '../core/types';
import { COMMAND_IDS } from '../core/constants';
import { getRuntimeWorkspaceId } from './workspaceContext';

interface StageMaterialGeneratePayload {
  planId?: unknown;
  stageId?: unknown;
  workspaceId?: unknown;
}

function readNonEmptyString(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : '';
}

/**
 * Generate learning materials for a plan stage via the sidecar, then push the
 * resulting materials into the workbench as a state/patch keyed by stage id.
 */
export async function generateStageMaterialCommand(
  context: CommandContext,
  payload: unknown,
): Promise<CommandExecutionResult> {
  const input = (payload ?? {}) as StageMaterialGeneratePayload;
  const planId = readNonEmptyString(input.planId);
  const stageId = readNonEmptyString(input.stageId);
  if (!planId || !stageId) {
    return { ok: false, message: 'planId and stageId are required to generate stage materials.' };
  }
  if (!(await context.trustGuard.ensureTrusted('generate stage learning materials'))) {
    return { ok: false, message: 'Workspace trust is required to generate stage materials.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const body: Record<string, unknown> = {
    workspace_id: readNonEmptyString(input.workspaceId) || getRuntimeWorkspaceId(context),
  };
  const sessionId = context.getSessionId();
  if (sessionId) {
    body.session_id = sessionId;
  }

  let response: { materials?: StageMaterialItem[] } | undefined;
  try {
    response = await context.sidecarClient.postJson<{ materials?: StageMaterialItem[] }>(
      status.port,
      `/plan/${encodeURIComponent(planId)}/stages/${encodeURIComponent(stageId)}/material/generate`,
      body,
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return { ok: false, message: `Stage material generation failed: ${detail}` };
  }

  const materials = Array.isArray(response?.materials) ? response?.materials : [];
  await context.patchWorkbenchData({
    stageMaterials: { [stageId]: materials },
  });
  return {
    ok: true,
    message:
      materials.length > 0
        ? `已生成 ${materials.length} 份学习资料。`
        : 'Stage material generation returned no materials.',
    data: { stageId, materials },
  };
}

export const stageMaterialCommandIds = [COMMAND_IDS.stageMaterialGenerate];
