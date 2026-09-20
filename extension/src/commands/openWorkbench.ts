import type { CommandContext } from '../core/commandContext';
import { trainerSessionBlockReason } from '../core/runtimeRehydration';
import type { CommandExecutionResult } from '../core/types';

export async function openWorkbenchCommand(context: CommandContext): Promise<CommandExecutionResult> {
  await context.workbench.show();

  if (context.getHostState().workspace.trusted && !trainerSessionBlockReason(context)) {
    // Kick the sidecar off but never block the panel on it: cold starts can
    // take tens of seconds and the UI is fully usable while it warms up.
    void context.sidecarManager.ensureRunning().catch(() => undefined);
  }

  await context.workbench.syncState();
  return {
    ok: true,
    message: 'Trainer coach sidebar opened.',
  };
}
