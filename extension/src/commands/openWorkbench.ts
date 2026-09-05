import type { CommandContext } from '../core/commandContext';
import { trainerSessionBlockReason } from '../core/runtimeRehydration';
import type { CommandExecutionResult } from '../core/types';

export async function openWorkbenchCommand(context: CommandContext): Promise<CommandExecutionResult> {
  await context.workbench.show();

  if (context.getHostState().workspace.trusted && !trainerSessionBlockReason(context)) {
    await context.sidecarManager.ensureRunning();
  }

  await context.workbench.syncState();
  return {
    ok: true,
    message: 'Trainer coach sidebar opened.',
  };
}
