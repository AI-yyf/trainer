import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';
import { buildTrainerRuntimeStatus, rehydrateWorkbenchRuntime } from '../core/runtimeRehydration';

export async function restartSidecarCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('start the Trainer sidecar'))) {
    return { ok: false, message: 'Workspace trust is required to start the sidecar.' };
  }

  const status = await context.sidecarManager.restart();
  await rehydrateWorkbenchRuntime(context, {
    ensureSidecar: false,
    syncWorkbench: true,
  });
  const runtimeStatus = buildTrainerRuntimeStatus(context, status);
  await context.workbench.postMessage({
    type: 'operation/status',
    payload: runtimeStatus,
  });
  return {
    ok: status.lifecycle === 'ready',
    message: runtimeStatus.message,
    data: status,
  };
}

export async function stopSidecarCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  await context.sidecarManager.stop();
  await context.workbench.syncState();
  return {
    ok: true,
    message: 'Sidecar stopped.',
  };
}
