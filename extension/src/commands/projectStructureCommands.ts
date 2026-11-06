import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';
import { COMMAND_IDS } from '../core/constants';
import { getRuntimeWorkspaceId } from './workspaceContext';

/**
 * Internal bridge command for the Resources project-details graph panel.
 *
 * The webview asks for one imported project's structure with a per-request
 * `requestId`; the host answers with a `resource/projectStructure` message
 * carrying the same id — the same correlation pattern as `library/folders`.
 * The sidecar's GET /project/summary does all analysis; this command never
 * computes structure itself.
 */

function readStringField(payload: unknown, key: string): string {
  if (!payload || typeof payload !== 'object') {
    return '';
  }
  const value = (payload as Record<string, unknown>)[key];
  return typeof value === 'string' ? value.trim() : '';
}

async function answerProjectStructure(
  context: CommandContext,
  requestId: string,
  ok: boolean,
  message: string,
  structure?: unknown,
): Promise<void> {
  if (!requestId) {
    return;
  }
  await context.workbench.postMessage({
    type: 'resource/projectStructure',
    payload: {
      requestId,
      ok,
      message,
      ...(structure === undefined ? {} : { structure }),
    },
  });
}

export async function projectStructureCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const requestId = readStringField(payload, 'requestId');
  const resourceId = readStringField(payload, 'resourceId');
  if (!resourceId) {
    const message = 'A resource id is required.';
    await answerProjectStructure(context, requestId, false, message);
    return { ok: false, message };
  }
  try {
    const status = await context.sidecarManager.ensureRunning();
    if (status.lifecycle !== 'ready' || !status.port) {
      throw new Error(status.detail ?? 'Sidecar is unavailable.');
    }
    const workspaceId = getRuntimeWorkspaceId(context);
    const query = new URLSearchParams({ workspace_id: workspaceId, resource_id: resourceId });
    const structure = await context.sidecarClient.getJson<unknown>(
      status.port,
      `/project/summary?${query.toString()}`,
    );
    await answerProjectStructure(context, requestId, true, '', structure);
    return { ok: true };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await answerProjectStructure(context, requestId, false, message);
    return { ok: false, message };
  }
}
