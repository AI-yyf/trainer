import * as vscode from 'vscode';

import type { CommandContext } from './commandContext';
import { COMMAND_IDS } from './constants';
import { trainerSessionBlockReason } from './runtimeRehydration';
import type { CommandExecutionResult } from './types';

type CommandHandler = (
  context: CommandContext,
  payload?: unknown,
) => Promise<CommandExecutionResult> | CommandExecutionResult;

const WORKSPACE_ADMISSION_REQUIRED_COMMAND_IDS = new Set<string>([
  COMMAND_IDS.generatePlan,
  COMMAND_IDS.updatePlan,
  COMMAND_IDS.createGlobalPlan,
  COMMAND_IDS.linkCurrentProjectPlan,
  COMMAND_IDS.taskSpecify,
  COMMAND_IDS.nextTask,
  COMMAND_IDS.evaluateCurrentFile,
  COMMAND_IDS.evaluateSelection,
  COMMAND_IDS.uploadResource,
  COMMAND_IDS.indexResources,
  COMMAND_IDS.deleteResource,
  COMMAND_IDS.restoreResource,
  COMMAND_IDS.restoreSandboxPath,
  COMMAND_IDS.createSandboxFile,
  COMMAND_IDS.createSandboxDirectory,
  COMMAND_IDS.renameSandboxPath,
  COMMAND_IDS.deleteSandboxPath,
  COMMAND_IDS.deleteSandboxPaths,
  COMMAND_IDS.chooseSandboxRoot,
  COMMAND_IDS.resetSandboxRoot,
  COMMAND_IDS.chooseManagedDataFolder,
  COMMAND_IDS.resetManagedDataFolder,
  COMMAND_IDS.refreshMemory,
  COMMAND_IDS.grantMemoryShare,
  COMMAND_IDS.revokeMemoryShare,
  COMMAND_IDS.evidenceEnqueue,
  COMMAND_IDS.evidenceAdopt,
  COMMAND_IDS.evidenceReject,
  COMMAND_IDS.evidenceDefer,
  COMMAND_IDS.evidenceRefreshQueue,
  COMMAND_IDS.trainingRestoreOrchestration,
  COMMAND_IDS.debugRestoreView,
  COMMAND_IDS.resumeLatestCoachCheckpoint,
  COMMAND_IDS.replayLatestCoachCheckpoint,
  COMMAND_IDS.trainingCardStatusTransition,
  COMMAND_IDS.trainingGenerateCard,
  COMMAND_IDS.trainingFlashcardCreate,
  COMMAND_IDS.trainingFlashcardAnswer,
  COMMAND_IDS.trainingTheoryDrillAnswer,
  COMMAND_IDS.trainingPracticeReturn,
  COMMAND_IDS.trainingDependencySkillMapAction,
  COMMAND_IDS.trainingReviewQueueAction,
  COMMAND_IDS.trainingScenarioLabAction,
  COMMAND_IDS.theoryDrillSubmitAnswer,
  COMMAND_IDS.reviewQueueAction,
  COMMAND_IDS.scenarioLabAction,
  COMMAND_IDS.createResearch,
  COMMAND_IDS.addResearchTheme,
  COMMAND_IDS.activateResearchTheme,
  COMMAND_IDS.advanceResearch,
  COMMAND_IDS.researchMessage,
  COMMAND_IDS.researchStreamMessage,
  COMMAND_IDS.approveResearchDecision,
]);

function workspaceAdmissionGate(
  commandId: string,
  context: CommandContext,
): CommandExecutionResult | undefined {
  if (!WORKSPACE_ADMISSION_REQUIRED_COMMAND_IDS.has(commandId)) {
    return undefined;
  }

  const blockReason = trainerSessionBlockReason(context);
  return blockReason ? { ok: false, message: blockReason } : undefined;
}

export class CommandRegistry implements vscode.Disposable {
  private readonly handlers = new Map<string, CommandHandler>();
  private readonly disposables: vscode.Disposable[] = [];
  private context?: CommandContext;

  constructor(private readonly outputChannel: vscode.OutputChannel) {}

  private appendLog(line: string): void {
    try {
      this.outputChannel.appendLine(line);
    } catch {
      // VS Code can dispose its output channel while a command is finishing.
    }
  }

  setContext(context: CommandContext): void {
    this.context = context;
  }

  register(extensionContext: vscode.ExtensionContext, commandId: string, handler: CommandHandler): void {
    this.handlers.set(commandId, handler);
    const disposable = vscode.commands.registerCommand(commandId, async (payload?: unknown) =>
      this.execute(commandId, payload),
    );
    this.disposables.push(disposable);
    extensionContext.subscriptions.push(disposable);
  }

  async execute(commandId: string, payload?: unknown): Promise<CommandExecutionResult> {
    if (!this.context) {
      return { ok: false, message: 'Trainer command context is not ready yet.' };
    }

    const handler = this.handlers.get(commandId);
    if (!handler) {
      return { ok: false, message: `Unknown Trainer command: ${commandId}` };
    }

    const workspaceGate = workspaceAdmissionGate(commandId, this.context);
    if (workspaceGate) {
      return workspaceGate;
    }

    try {
      this.appendLog(`[command] ${commandId}`);
      const result = await handler(this.context, payload);
      await this.context.workbench.syncState();
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.appendLog(`[command:error] ${commandId}: ${message}`);
      return { ok: false, message };
    }
  }

  dispose(): void {
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
    this.disposables.length = 0;
    this.handlers.clear();
  }
}
