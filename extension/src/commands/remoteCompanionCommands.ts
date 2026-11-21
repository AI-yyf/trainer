import * as vscode from 'vscode';

import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';
import { hostCommandCopy, resolveHostCommandLanguage } from './hostCommandCopy';

export async function installRemoteCompanionCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const lang = resolveHostCommandLanguage(context);
  const workspace = context.getHostState().workspace;
  if (!workspace.isRemoteWorkspace && !workspace.remoteName) {
    return { ok: false, message: hostCommandCopy(lang, 'remoteOpenWorkspaceFirst') };
  }
  if (!vscode.workspace.isTrusted) {
    return { ok: false, message: hostCommandCopy(lang, 'remoteTrustBeforeInstall') };
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
    return { ok: false, message: hostCommandCopy(lang, 'remoteCompanionInstallFailed') };
  }

  return {
    ok: true,
    message: hostCommandCopy(lang, 'remoteCompanionInstallRequested'),
  };
}
