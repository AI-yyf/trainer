import * as vscode from 'vscode';

import { buildCommandRegistrations } from './registry.config';
import { CommandRegistry } from '../core/commandRegistry';
import type { CommandContext } from '../core/commandContext';

export function registerCommands(
  extensionContext: vscode.ExtensionContext,
  context: CommandContext,
): CommandRegistry {
  const registry = new CommandRegistry(context.outputChannel);
  registry.setContext(context);

  for (const entry of buildCommandRegistrations(context)) {
    registry.register(extensionContext, entry.commandId, entry.register);
  }

  extensionContext.subscriptions.push(registry);
  return registry;
}
