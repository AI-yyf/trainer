import * as vscode from 'vscode';

import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';
import { mergeEvaluationResultSnapshot, mergeMemorySummarySnapshot } from '../core/workbenchData';
import { getRuntimeWorkspaceId, withWorkspaceQuery } from './workspaceContext';
import { describeProviderSendState } from '../../../shared/src/providerStatus';

function leftoverTrainingEvaluateHttpFailure(error: unknown): CommandExecutionResult | undefined {
  if (typeof error !== "object" || error === null) {
    return undefined;
  }
  const statusCode = "statusCode" in error ? error.statusCode : undefined;
  if (statusCode !== 409) {
    return undefined;
  }
  const metadata = "metadata" in error ? error.metadata : undefined;
  const metadataDetail =
    typeof metadata === "object" && metadata !== null && "detail" in metadata
      ? metadata.detail
      : undefined;
  const message = error instanceof Error ? error.message : String(error);
  const detail = `${typeof metadataDetail === "string" ? metadataDetail : ""} ${message}`.toLowerCase();
  if (!/leftover-not-live|does not match live selected_card_id/.test(detail)) {
    return undefined;
  }
  return {
    ok: false,
    message:
      "Recovered training card is leftover-not-live. Trainer will not skip, grade, reflect, return, verify, or resurrect leftover as live.",
  };
}

export async function evaluateCurrentFileCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('evaluate the current file'))) {
    return { ok: false, message: 'Workspace trust is required to evaluate files.' };
  }

  const evaluationPayload = extractEvaluationPayload(payload);
  const editor = vscode.window.activeTextEditor;
  const workspaceFolder =
    vscode.workspace?.workspaceFolders?.[0]?.uri.fsPath ??
    context.getHostState().workspace?.workspaceFolder;
  const targetDocument = await resolveTrainingVerifyDocument({
    filesToTouch: evaluationPayload.filesToTouch,
    editor,
    workspaceFolder,
  });
  if (!targetDocument) {
    const message =
      evaluationPayload.filesToTouch.length > 0
        ? 'No readable training target file. Open a filesToTouch path, then verify.'
        : 'No active editor.';
    vscode.window.showWarningMessage(
      evaluationPayload.filesToTouch.length > 0
        ? 'Open one of the training card files before running Trainer evaluation.'
        : 'Open a file before running Trainer evaluation.',
    );
    return { ok: false, message };
  }

  return evaluateDocument(
    context,
    targetDocument,
    targetDocument.getText(),
    '/evaluate/current-file',
    payload,
  );
}

export async function evaluateSelectionCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('evaluate the current selection'))) {
    return { ok: false, message: 'Workspace trust is required to evaluate code selections.' };
  }

  const evaluationPayload = extractEvaluationPayload(payload);
  if (evaluationPayload.source === 'training') {
    return {
      ok: false,
      message: 'Training practice verification must read the active IDE file and diagnostics. Use Verify current file.',
    };
  }

  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    return { ok: false, message: 'No active editor.' };
  }

  const selectedText = editor.document.getText(editor.selection);
  if (!selectedText.trim()) {
    return { ok: false, message: 'No selection to evaluate.' };
  }

  return evaluateDocument(context, editor.document, selectedText, '/evaluate/snippet', payload);
}

async function evaluateDocument(
  context: CommandContext,
  document: vscode.TextDocument,
  code: string,
  path: string,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const providerConfig = context.providerStore.getConfig();
  const apiKey = await context.providerStore.getApiKey();
  if (!providerConfig || !apiKey?.trim()) {
    return {
      ok: false,
      message: 'Trainer needs a saved provider and API key before evaluation can run.',
    };
  }

  const sendState = describeProviderSendState(context.getHostState().bootstrap.providerConfig, 'en-US');
  if (sendState.blocked) {
    return {
      ok: false,
      message: sendState.reason ?? 'Trainer evaluation is blocked until the provider state is ready.',
    };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const evaluationPayload = extractEvaluationPayload(payload);
  const diagnostics = vscode.languages.getDiagnostics(document.uri).map(
    (diagnostic) =>
      `[${diagnosticSeverityLabel(diagnostic.severity)}] line ${diagnostic.range.start.line + 1}: ${diagnostic.message}`,
  );

  try {
    const response = await context.sidecarClient.postJson<unknown>(status.port, path, {
      session_id: context.getSessionId(),
      workspace_id: getRuntimeWorkspaceId(context),
      task_spec_id: evaluationPayload.taskSpecId ?? context.getHostState().bootstrap.task.id,
      file_path: document.uri.fsPath,
      language_id: document.languageId,
      content: code,
      diagnostics,
      evaluation_source: evaluationPayload.source,
      training_card_id: evaluationPayload.cardId,
      training_card_title: evaluationPayload.cardTitle,
      ...(evaluationPayload.acceptanceCriteria.length > 0
        ? { acceptance_criteria: evaluationPayload.acceptanceCriteria }
        : {}),
      ...(evaluationPayload.learnerDeliverables.length > 0
        ? { learner_deliverables: evaluationPayload.learnerDeliverables }
        : {}),
      ...(evaluationPayload.expectedSymbols.length > 0
        ? { expected_symbols: evaluationPayload.expectedSymbols }
        : {}),
    });

    await context.patchWorkbenchData(
      mergeEvaluationResultSnapshot(
        context.getHostState().bootstrap,
        response,
        getRuntimeWorkspaceId(context),
      ),
    );
    context.tests.publishReport(response, document.uri);

    const memoryRefreshError = await refreshMemorySummaryAfterEvaluation(context, status.port);

    return {
      ok: true,
      message: memoryRefreshError
        ? `Trainer evaluation completed. Training state refresh will recover on the next sync: ${memoryRefreshError}`
        : 'Trainer evaluation completed.',
      data: response,
    };
  } catch (error) {
    const leftover = leftoverTrainingEvaluateHttpFailure(error);
    if (leftover) {
      return leftover;
    }
    throw error;
  }
}

async function refreshMemorySummaryAfterEvaluation(
  context: CommandContext,
  port: number,
): Promise<string | undefined> {
  try {
    const summary = await context.sidecarClient.getJson<unknown>(
      port,
      withWorkspaceQuery('/memory/summary', context),
    );
    await context.patchWorkbenchData(
      mergeMemorySummarySnapshot(
        context.getHostState().bootstrap,
        summary,
        getRuntimeWorkspaceId(context),
      ),
    );
    return undefined;
  } catch (error) {
    const message = formatErrorMessage(error);
    context.outputChannel?.appendLine?.(
      `[evaluation] Memory summary refresh failed after evaluation: ${message}`,
    );
    return message;
  }
}

function extractEvaluationPayload(payload: unknown): {
  source?: string;
  cardId?: string;
  cardTitle?: string;
  taskSpecId?: string;
  acceptanceCriteria: string[];
  learnerDeliverables: string[];
  expectedSymbols: string[];
  filesToTouch: string[];
} {
  if (!payload || typeof payload !== 'object') {
    return {
      acceptanceCriteria: [],
      learnerDeliverables: [],
      expectedSymbols: [],
      filesToTouch: [],
    };
  }
  const record = payload as Record<string, unknown>;
  return {
    source: typeof record.source === 'string' ? record.source : undefined,
    cardId: typeof record.cardId === 'string' ? record.cardId : undefined,
    cardTitle: typeof record.cardTitle === 'string' ? record.cardTitle : undefined,
    taskSpecId: typeof record.taskSpecId === 'string' ? record.taskSpecId : undefined,
    acceptanceCriteria: extractStringArray(record.acceptanceCriteria ?? record.acceptance_criteria),
    learnerDeliverables: extractStringArray(record.learnerDeliverables ?? record.learner_deliverables),
    expectedSymbols: extractStringArray(record.expectedSymbols ?? record.expected_symbols),
    filesToTouch: extractStringArray(record.filesToTouch ?? record.files_to_touch),
  };
}

function normalizeFsPath(value: string): string {
  return value.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
}

function isAbsoluteFsPath(value: string): boolean {
  return /^(?:[a-zA-Z]:[\\/]|\/|\\\\)/.test(value);
}

function joinWorkspacePath(workspaceFolder: string, relativePath: string): string {
  const root = workspaceFolder.replace(/[\\/]+$/, '');
  const leaf = relativePath.replace(/^[\\/]+/, '');
  return `${root}/${leaf}`.replace(/\\/g, '/');
}

function candidateUrisForTrainingFiles(
  filesToTouch: string[],
  workspaceFolder: string | undefined,
): vscode.Uri[] {
  const uris: vscode.Uri[] = [];
  for (const filePath of filesToTouch) {
    if (isAbsoluteFsPath(filePath)) {
      uris.push(vscode.Uri.file(filePath));
      continue;
    }
    if (workspaceFolder) {
      uris.push(vscode.Uri.file(joinWorkspacePath(workspaceFolder, filePath)));
    }
  }
  return uris;
}

async function resolveTrainingVerifyDocument(input: {
  filesToTouch: string[];
  editor: vscode.TextEditor | undefined;
  workspaceFolder: string | undefined;
}): Promise<vscode.TextDocument | undefined> {
  if (input.filesToTouch.length > 0) {
    const editorPath = input.editor?.document.uri.fsPath;
    if (
      editorPath &&
      input.filesToTouch.some((filePath) => {
        const absolute = isAbsoluteFsPath(filePath)
          ? filePath
          : input.workspaceFolder
            ? joinWorkspacePath(input.workspaceFolder, filePath)
            : filePath;
        return normalizeFsPath(editorPath) === normalizeFsPath(absolute) ||
          normalizeFsPath(editorPath).endsWith(`/${normalizeFsPath(filePath)}`);
      })
    ) {
      return input.editor?.document;
    }
    for (const uri of candidateUrisForTrainingFiles(input.filesToTouch, input.workspaceFolder)) {
      try {
        return await vscode.workspace.openTextDocument(uri);
      } catch {
        continue;
      }
    }
    return undefined;
  }
  return input.editor?.document;
}

function extractStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of value) {
    if (typeof item !== 'string') {
      continue;
    }
    const normalized = item.replace(/\s+/g, ' ').trim();
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function formatErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function diagnosticSeverityLabel(severity: vscode.DiagnosticSeverity): string {
  switch (severity) {
    case vscode.DiagnosticSeverity.Error:
      return 'Error';
    case vscode.DiagnosticSeverity.Warning:
      return 'Warning';
    case vscode.DiagnosticSeverity.Information:
      return 'Info';
    case vscode.DiagnosticSeverity.Hint:
      return 'Hint';
    default:
      return 'Unknown';
  }
}
