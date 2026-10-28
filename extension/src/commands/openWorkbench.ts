import * as vscode from 'vscode';

import type { CommandContext } from '../core/commandContext';
import { COMMAND_IDS } from '../core/constants';
import { trainerSessionBlockReason } from '../core/runtimeRehydration';
import type { CommandExecutionResult } from '../core/types';

export async function openWorkbenchCommand(context: CommandContext): Promise<CommandExecutionResult> {
  await context.workbench.show();

  if (context.getHostState().workspace.trusted && !trainerSessionBlockReason(context)) {
    // Kick the sidecar off but never block the panel on it: cold starts can
    // take tens of seconds and the UI is fully usable while it warms up.
    void context.sidecarManager.ensureRunning().catch((error: unknown) => {
      // A failed warm-up used to be swallowed here, so the panel opened into a
      // dead state with no explanation. Say it once, with a way to recover.
      const detail = error instanceof Error ? error.message : String(error);
      context.outputChannel.appendLine(`[sidecar] startup failed: ${detail}`);
      void vscode.window
        ?.showWarningMessage?.(
          'Trainer could not start its local engine, so coaching replies will not arrive yet.',
          'Retry',
          'Show Log',
        )
        .then((choice) => {
          if (choice === 'Retry') {
            void vscode.commands.executeCommand(COMMAND_IDS.restartSidecar);
          } else if (choice === 'Show Log') {
            context.outputChannel.show(true);
          }
        });
    });
  }

  await context.workbench.syncState();
  return {
    ok: true,
    message: 'Trainer coach sidebar opened.',
  };
}
