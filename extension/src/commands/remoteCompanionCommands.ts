import * as path from 'node:path';
import * as vscode from 'vscode';

import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';

export async function installRemoteCompanionCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const workspace = context.getHostState().workspace;
  if (!workspace.isRemoteWorkspace && !workspace.remoteName) {
    return { ok: false, message: 'Open a Remote-SSH, WSL, Tunnel, or Dev Container workspace first.' };
  }
  if (!vscode.workspace.isTrusted) {
    return { ok: false, message: 'Trust the current workspace before installing remote support.' };
  }

  const companionUri = vscode.Uri.joinPath(
    context.extensionContext.extensionUri,
    'bundled',
    'remote',
    'trainer-workspace-companion.vsix',
  );
  try {
    await vscode.commands.executeCommand('workbench.extensions.command.installFromVSIX', [companionUri]);
  } catch (error) {
    context.outputChannel.appendLine(
      `[remote] companion installation failed: ${error instanceof Error ? error.message : String(error)}`,
    );
    return { ok: false, message: 'VS Code could not install the Remote Workspace Companion.' };
  }

  return {
    ok: true,
    message: 'Remote Workspace Companion installation requested. Reload the remote window when VS Code asks.',
  };
}
