import * as path from 'node:path';
import * as vscode from 'vscode';

import type { CommandContext } from '../core/commandContext';
import type { BootstrapData, CommandExecutionResult } from '../core/types';
import { mergeMemorySummarySnapshot } from '../core/workbenchData';
import { getRuntimeWorkspaceId, getWorkspaceId, withWorkspaceQuery } from './workspaceContext';
import {
  asNonEmptyString,
  asNumber,
  asRecord,
  buildMemorySummaryQueryPath,
  resolveExplicitTrainingRestoreStepFromSummary,
  resolveLatestTrainingNextHopFromSummary,
} from './trainingRestoreGovernance';

type DebugRestorePayload = {
  sessionId?: string;
  workspaceId?: string;
  activeView?: string;
  trainingSubmode?: string;
  trainingRestoreTarget?: string;
  theoryDrillId?: string;
  scenarioLabId?: string;
  reviewArtifactId?: string;
  resourceSurface?: string;
  resourceId?: string;
  resourceDetailId?: string;
  sandboxPath?: string;
  previewPath?: string;
  workspaceLabel?: string;
  resumeReason?: string;
  focusArea?: string;
  currentStageTitle?: string;
  latestSummary?: string;
};

type TrainingRestoreOrchestrationPayload = {
  runId?: string;
  note?: string;
  sessionId?: string;
  workspaceId?: string;
};

type RestoreRequestStep = {
  requestPath: string;
  body: Record<string, unknown>;
};

export async function refreshMemoryCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('refresh Trainer memory'))) {
    return { ok: false, message: 'Workspace trust is required to refresh memory.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const summary = await context.sidecarClient.getJson<unknown>(
    status.port,
    withWorkspaceQuery('/memory/summary', context),
  );
  await patchFromSummary(context, summary);
  return {
    ok: true,
    message: 'Trainer memory refreshed.',
    data: summary,
  };
}

type UserFeedbackPayload = {
  kind?: string;
  message?: string;
  focusArea?: string;
  scenario?: string;
  trainingCardId?: string;
  planId?: string;
};

const USER_FEEDBACK_KINDS = new Set([
  'too_hard',
  'too_simple',
  'misunderstood',
  'resource_incorrect',
  'plan_mismatch',
  'card_unrealistic',
]);

export async function recordUserFeedbackCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('record Trainer learning feedback'))) {
    return { ok: false, message: 'Workspace trust is required to record learning feedback.' };
  }
  const input = (payload && typeof payload === 'object' ? payload : {}) as UserFeedbackPayload;
  const kind = input.kind?.trim().toLowerCase() ?? '';
  const message = input.message?.trim() ?? '';
  if (!USER_FEEDBACK_KINDS.has(kind) || !message) {
    return { ok: false, message: 'A supported feedback kind and message are required.' };
  }
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }
  try {
    const snapshot = await context.sidecarClient.postJson<unknown>(status.port, '/memory/feedback', {
      session_id: context.getSessionId(),
      workspace_id: getRuntimeWorkspaceId(context),
      kind,
      message,
      focus_area: input.focusArea?.trim() || undefined,
      scenario: input.scenario?.trim() || 'coach',
      training_card_id: input.trainingCardId?.trim() || undefined,
      plan_id: input.planId?.trim() || undefined,
    });
    await patchFromSummary(context, snapshot);
    await context.workbench.syncState();
    return { ok: true, message: 'Learning feedback recorded.', data: snapshot };
  } catch (error) {
    context.outputChannel.appendLine(`[memory] user feedback error: ${error}`);
    return { ok: false, message: String(error) };
  }
}

export async function refreshWorkspaceAuthorityCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const trustGuard = context.trustGuard as
    | {
        ensureTrusted?: (reason: string) => Promise<boolean>;
      }
    | undefined;
  if (trustGuard?.ensureTrusted && !(await trustGuard.ensureTrusted('refresh workspace authority'))) {
    return { ok: false, message: 'Workspace trust is required to refresh workspace authority.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const authority = await context.sidecarClient.getJson<unknown>(
    status.port,
    buildWorkspaceAuthorityRequestPath(context),
  );
  const sandboxState = mergeSandboxStateFromAuthority(context, authority);

  await context.patchWorkbenchData({
    memory: {
      ...context.getHostState().bootstrap.memory,
      sandboxState,
    },
  });
  await context.workbench.syncState();

  return {
    ok: true,
    message: 'Workspace authority refreshed.',
    data: authority,
  };
}

type MemoryShareSourcePick = vscode.QuickPickItem & {
  workspaceId: string;
};

export async function grantMemoryShareCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('allow cross-project Trainer memory sharing'))) {
    return { ok: false, message: 'Workspace trust is required to change memory sharing.' };
  }

  const admission = context.getHostState().bootstrap.memory.workspace?.trainerWorkspace;
  if (admission?.status !== 'managed') {
    return {
      ok: false,
      message: 'Add the current project to Trainer before sharing memory between projects.',
    };
  }

  const physicalWorkspaceId = getWorkspaceId(context);
  const workspaceId = getRuntimeWorkspaceId(context);
  const snapshot = await context.trainerWorkspace.toSnapshot();
  const candidates = Object.values(snapshot.manifest?.projects ?? {})
    .filter(
      (project) =>
        project.adoptionMode === 'managed' &&
        canonicalWorkspaceId(project.projectPath) !== canonicalWorkspaceId(physicalWorkspaceId),
    )
    .map<MemoryShareSourcePick>((project) => ({
      label: path.basename(project.projectPath) || project.projectPath,
      description: 'Reusable preferences and mastery signals',
      detail: 'Trainer will keep plans, sessions, resources, and active threads isolated.',
      workspaceId: project.projectPath,
    }));

  if (candidates.length === 0) {
    return {
      ok: false,
      message: 'Add another managed Trainer project before authorizing cross-project memory.',
    };
  }

  const selected = await vscode.window.showQuickPick(candidates, {
    title: 'Allow Project Memory Sharing',
    placeHolder: 'Choose a project to share reusable memory from',
  });
  if (!selected) {
    return { ok: false, message: 'Project memory sharing selection cancelled.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const summary = await context.sidecarClient.postJson<unknown>(status.port, '/memory/share-grants', {
    session_id: context.getSessionId(),
    workspace_id: workspaceId,
    source_workspace_id: selected.workspaceId,
    categories: ['preferences', 'mastery'],
  });
  await patchFromSummary(context, summary);
  await context.workbench.syncState();
  return {
    ok: true,
    message: 'Trainer can now read reusable memory from ' + selected.label + '.',
    data: summary,
  };
}

export async function revokeMemoryShareCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('revoke cross-project Trainer memory sharing'))) {
    return { ok: false, message: 'Workspace trust is required to change memory sharing.' };
  }

  const sourceWorkspaceId = memoryShareSourceWorkspaceId(payload);
  if (!sourceWorkspaceId) {
    return { ok: false, message: 'A memory sharing source is required.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const summary = await context.sidecarClient.postJson<unknown>(
    status.port,
    '/memory/share-grants/revoke',
    {
      session_id: context.getSessionId(),
      workspace_id: getRuntimeWorkspaceId(context),
      source_workspace_id: sourceWorkspaceId,
    },
  );
  await patchFromSummary(context, summary);
  await context.workbench.syncState();
  return {
    ok: true,
    message: 'Project memory sharing was revoked.',
    data: summary,
  };
}

export async function trainingRestoreOrchestrationCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('restore governed Trainer state'))) {
    return { ok: false, message: 'Workspace trust is required to restore governed Trainer state.' };
  }

  const request = normalizeTrainingRestoreOrchestrationPayload(payload);
  const workspaceId = request.workspaceId ?? getRuntimeWorkspaceId(context);
  const sessionId = request.sessionId ?? context.getSessionId();
  const note = request.note;

  let summary = await fetchMemorySummary(context, workspaceId, sessionId);
  await patchFromSummary(context, summary);

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  for (const step of resolveTrainingRestoreOrchestrationSteps(summary, workspaceId, note)) {
    await context.sidecarClient.postJson(status.port, step.requestPath, step.body);
  }

  summary = await fetchMemorySummary(context, workspaceId, sessionId);
  await patchFromSummary(context, summary);
  await context.workbench.syncState();
  await context.workbench.postMessage({
    type: 'ui/restoreView',
    payload: {
      activeView: 'training',
      trainingSubmode: resolveTrainingSubmode(summary, undefined),
      trainingRestoreTarget: undefined,
      theoryDrillId: undefined,
      scenarioLabId: undefined,
      reviewArtifactId: undefined,
      resumeReason: note,
    },
  });

  return {
    ok: true,
    message: 'Training state restored from the authoritative memory summary.',
    data: summary,
  };
}

export async function debugRestoreViewCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('restore the Trainer workbench view'))) {
    return { ok: false, message: 'Workspace trust is required to restore the Trainer workbench view.' };
  }

  const request = normalizeDebugRestorePayload(payload);
  const workspaceId = request.workspaceId ?? resolveWorkspaceId(context);
  const requestedSessionId = request.sessionId ?? context.getSessionId();

  let summary = await fetchMemorySummary(context, workspaceId, requestedSessionId);
  const restoreStep = resolveExplicitTrainingRestoreStepFromSummary(summary, request, workspaceId);
  const requestedTarget = request.trainingRestoreTarget;
  if (
    (requestedTarget === 'theory_drill' ||
      requestedTarget === 'scenario_lab' ||
      requestedTarget === 'review_artifact') &&
    !restoreStep
  ) {
    return {
      ok: false,
      message: 'No governed restore history is available for the requested training asset.',
    };
  }

  await patchFromSummary(context, summary);

  if (restoreStep) {
    const status = await context.sidecarManager.ensureRunning();
    if (status.lifecycle !== 'ready' || !status.port) {
      return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
    }
    await context.sidecarClient.postJson(status.port, restoreStep.requestPath, restoreStep.body);
    summary = await fetchMemorySummary(context, workspaceId, requestedSessionId);
  }

  await patchFromSummary(context, summary);

  const resolvedSessionId = requestedSessionId ?? context.getSessionId();
  await context.setSessionId(resolvedSessionId);

  const memory = asRecord(asRecord(summary)?.memory);
  const theoryDrill = asRecord(memory?.theory_drill);
  const scenarioLab = asRecord(memory?.scenario_lab);
  const reviewArtifact = asRecord(memory?.review_artifact);

  const restorePayload: Record<string, unknown> = {
    sessionId: resolvedSessionId,
    activeView: request.activeView ?? 'training',
    trainingSubmode: resolveTrainingSubmode(summary, request.trainingSubmode),
    trainingRestoreTarget: request.trainingRestoreTarget,
    theoryDrillId:
      request.trainingRestoreTarget === 'theory_drill'
        ? asNonEmptyString(theoryDrill?.id) ?? request.theoryDrillId
        : request.theoryDrillId,
    scenarioLabId:
      request.trainingRestoreTarget === 'scenario_lab'
        ? asNonEmptyString(scenarioLab?.id) ?? request.scenarioLabId
        : request.scenarioLabId,
    reviewArtifactId:
      request.trainingRestoreTarget === 'review_artifact'
        ? asNonEmptyString(reviewArtifact?.id) ?? request.reviewArtifactId
        : request.reviewArtifactId,
    resourceSurface: request.resourceSurface,
    resourceId: request.resourceId,
    resourceDetailId: request.resourceDetailId,
    sandboxPath: request.sandboxPath,
    previewPath: request.previewPath,
    workspaceLabel: request.workspaceLabel,
    resumeReason: request.resumeReason,
    focusArea: request.focusArea,
    currentStageTitle: request.currentStageTitle,
    latestSummary: request.latestSummary,
  };

  if (request.trainingRestoreTarget === 'next_hop') {
    restorePayload.latestTrainingNextHop = resolveLatestTrainingNextHopFromSummary(summary);
  }

  await (context.workbench as { show?: () => Promise<void> }).show?.();
  await context.workbench.syncState();
  await context.workbench.postMessage({
    type: 'ui/restoreView',
    payload: restorePayload,
  });

  return {
    ok: true,
    message: 'Trainer restored the requested workbench view from authoritative state.',
    data: summary,
  };
}

function resolveWorkspaceId(context: CommandContext): string {
  return getRuntimeWorkspaceId(context);
}

function memoryShareSourceWorkspaceId(payload: unknown): string | undefined {
  if (!payload || typeof payload !== 'object') {
    return undefined;
  }
  const record = payload as Record<string, unknown>;
  const candidate = record.sourceWorkspaceId ?? record.source_workspace_id;
  return typeof candidate === 'string' && candidate.trim() ? candidate.trim() : undefined;
}

function canonicalWorkspaceId(value: string): string {
  const normalized = path.resolve(value);
  return process.platform === 'win32' ? normalized.toLocaleLowerCase('en-US') : normalized;
}

async function fetchMemorySummary(
  context: CommandContext,
  workspaceId: string,
  sessionId: string | undefined,
): Promise<unknown> {
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    throw new Error(status.detail ?? 'Sidecar is unavailable.');
  }

  return context.sidecarClient.getJson<unknown>(
    status.port,
    buildMemorySummaryQueryPath(workspaceId, sessionId),
  );
}

async function patchFromSummary(context: CommandContext, summary: unknown): Promise<void> {
  await context.patchWorkbenchData(
    mergeMemorySummarySnapshot(
      context.getHostState().bootstrap,
      summary,
      getRuntimeWorkspaceId(context),
    ),
  );
}

function buildWorkspaceAuthorityRequestPath(context: CommandContext): string {
  const params = new URLSearchParams();
  params.set('workspace_id', getRuntimeWorkspaceId(context));
  const sessionId = context.getSessionId();
  if (sessionId) {
    params.set('session_id', sessionId);
  }
  // Host-attested VS Code trust + remote identity (never omit — fail-closed defaults otherwise).
  const workspace = context.getHostState().workspace;
  params.set('workspace_trusted', workspace.trusted ? 'true' : 'false');
  params.set('remote_name', workspace.remoteName ?? '');
  return `/workspace/authority?${params.toString()}`;
}

function mergeSandboxStateFromAuthority(
  context: CommandContext,
  value: unknown,
): BootstrapData['memory']['sandboxState'] {
  const record = asRecord(value);
  const authorityRecord = asRecord(record?.authority) ?? record ?? {};
  const currentSandboxState = asRecord(context.getHostState().bootstrap.memory.sandboxState) ?? {};
  const rootPath =
    asNonEmptyString(authorityRecord.activeWorkspaceRoot) ??
    asNonEmptyString(authorityRecord.active_workspace_root) ??
    asNonEmptyString(authorityRecord.rootUri) ??
    asNonEmptyString(authorityRecord.root_uri) ??
    asNonEmptyString(authorityRecord.rootPath) ??
    asNonEmptyString(authorityRecord.root_path) ??
    asNonEmptyString(currentSandboxState.rootPath) ??
    asNonEmptyString(currentSandboxState.workspaceRootPath);
  const authoritySource =
    asNonEmptyString(authorityRecord.authoritySource) ??
    asNonEmptyString(authorityRecord.authority_source) ??
    (rootPath ? 'workspace_authority_service' : undefined);
  const activeWorkspaceRoot =
    asNonEmptyString(authorityRecord.activeWorkspaceRoot) ??
    asNonEmptyString(authorityRecord.active_workspace_root) ??
    rootPath;
  const workspaceRootPath =
    asNonEmptyString(authorityRecord.workspaceRootPath) ??
    asNonEmptyString(authorityRecord.workspace_root_path) ??
    rootPath ??
    asNonEmptyString(currentSandboxState.workspaceRootPath);
  const trashRootPath =
    asNonEmptyString(authorityRecord.trashRoot) ??
    asNonEmptyString(authorityRecord.trash_root) ??
    asNonEmptyString(authorityRecord.trashRootPath) ??
    asNonEmptyString(authorityRecord.trash_root_path) ??
    asNonEmptyString(currentSandboxState.trashRootPath);
  const authority = {
    activeWorkspaceRoot,
    rootUri:
      asNonEmptyString(authorityRecord.rootUri) ??
      asNonEmptyString(authorityRecord.root_uri) ??
      activeWorkspaceRoot,
    authoritySource,
    remoteName:
      asNonEmptyString(authorityRecord.remoteName) ??
      asNonEmptyString(authorityRecord.remote_name),
    authorityMode:
      asNonEmptyString(authorityRecord.authorityMode) ??
      asNonEmptyString(authorityRecord.authority_mode),
    permissionLevel:
      asNonEmptyString(authorityRecord.permissionLevel) ??
      asNonEmptyString(authorityRecord.permission_level),
    permissionLabel:
      asNonEmptyString(authorityRecord.permissionLabel) ??
      asNonEmptyString(authorityRecord.permission_label),
    allowedOperations: toStringArray(
      authorityRecord.allowedOperations ?? authorityRecord.allowed_operations,
    ),
    ledgerEntryCount:
      asNumber(authorityRecord.ledgerEntryCount) ?? asNumber(authorityRecord.ledger_entry_count),
    checkpointCount:
      asNumber(authorityRecord.checkpointCount) ?? asNumber(authorityRecord.checkpoint_count),
    trashRoot: trashRootPath,
  };

  return {
    ...currentSandboxState,
    rootPath,
    workspaceRootPath,
    activeWorkspaceRoot,
    trashRootPath,
    authoritySource,
    authority,
  } as BootstrapData['memory']['sandboxState'];
}

function toStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }

  const items = value
    .map((item) => asNonEmptyString(item))
    .filter((item): item is string => Boolean(item));
  return items.length > 0 ? items : undefined;
}

function normalizeDebugRestorePayload(payload: unknown): DebugRestorePayload {
  const record = asRecord(payload);
  return {
    sessionId: asNonEmptyString(record?.sessionId),
    workspaceId: asNonEmptyString(record?.workspaceId),
    activeView: asNonEmptyString(record?.activeView),
    trainingSubmode: asNonEmptyString(record?.trainingSubmode),
    trainingRestoreTarget: asNonEmptyString(record?.trainingRestoreTarget),
    theoryDrillId: asNonEmptyString(record?.theoryDrillId),
    scenarioLabId: asNonEmptyString(record?.scenarioLabId),
    reviewArtifactId: asNonEmptyString(record?.reviewArtifactId),
    resourceSurface: asNonEmptyString(record?.resourceSurface),
    resourceId: asNonEmptyString(record?.resourceId),
    resourceDetailId: asNonEmptyString(record?.resourceDetailId),
    sandboxPath: asNonEmptyString(record?.sandboxPath),
    previewPath: asNonEmptyString(record?.previewPath),
    workspaceLabel: asNonEmptyString(record?.workspaceLabel),
    resumeReason: asNonEmptyString(record?.resumeReason),
    focusArea: asNonEmptyString(record?.focusArea),
    currentStageTitle: asNonEmptyString(record?.currentStageTitle),
    latestSummary: asNonEmptyString(record?.latestSummary),
  };
}

function normalizeTrainingRestoreOrchestrationPayload(
  payload: unknown,
): TrainingRestoreOrchestrationPayload {
  const record = asRecord(payload);
  return {
    runId: asNonEmptyString(record?.runId),
    note: asNonEmptyString(record?.note),
    sessionId: asNonEmptyString(record?.sessionId),
    workspaceId: asNonEmptyString(record?.workspaceId),
  };
}

function resolveTrainingSubmode(
  summary: unknown,
  fallback: string | undefined,
): string | undefined {
  return (
    asNonEmptyString(asRecord(asRecord(asRecord(summary)?.memory)?.workspace)?.latest_training_submode) ??
    fallback
  );
}

function resolveTrainingRestoreOrchestrationSteps(
  summary: unknown,
  workspaceId: string,
  note: string | undefined,
): RestoreRequestStep[] {
  const memory = asRecord(asRecord(summary)?.memory);
  if (!memory) {
    return [];
  }

  const steps: RestoreRequestStep[] = [];
  const dependencyStep = resolveDependencySkillMapRestoreStep(memory, workspaceId, note);
  if (dependencyStep) {
    steps.push(dependencyStep);
  }

  const theoryDrillId =
    asNonEmptyString(asRecord(memory.theory_drill)?.id) ??
    asNonEmptyString(asRecord(latestHistoryEntry(memory.theory_drill_history))?.theory_drill_id) ??
    asNonEmptyString(asRecord(latestHistoryEntry(memory.theory_drill_history))?.theoryDrillId);
  const theoryStep =
    theoryDrillId
      ? resolveExplicitTrainingRestoreStepFromSummary(
          summary,
          {
            trainingRestoreTarget: 'theory_drill',
            theoryDrillId,
            resumeReason: note,
          },
          workspaceId,
        )
      : undefined;
  if (theoryStep) {
    steps.push(theoryStep);
  }

  const scenarioLabId =
    asNonEmptyString(asRecord(memory.scenario_lab)?.id) ??
    asNonEmptyString(asRecord(latestHistoryEntry(memory.scenario_lab_history))?.scenario_lab_id) ??
    asNonEmptyString(asRecord(latestHistoryEntry(memory.scenario_lab_history))?.scenarioLabId);
  const scenarioStep =
    scenarioLabId
      ? resolveExplicitTrainingRestoreStepFromSummary(
          summary,
          {
            trainingRestoreTarget: 'scenario_lab',
            scenarioLabId,
            resumeReason: note,
          },
          workspaceId,
        )
      : undefined;
  if (scenarioStep) {
    steps.push(scenarioStep);
  }

  const reviewArtifactId =
    asNonEmptyString(asRecord(memory.review_artifact)?.id) ??
    asNonEmptyString(asRecord(latestHistoryEntry(memory.review_artifact_history))?.review_artifact_id) ??
    asNonEmptyString(asRecord(latestHistoryEntry(memory.review_artifact_history))?.reviewArtifactId);
  const reviewStep =
    reviewArtifactId
      ? resolveExplicitTrainingRestoreStepFromSummary(
          summary,
          {
            trainingRestoreTarget: 'review_artifact',
            reviewArtifactId,
            resumeReason: note,
          },
          workspaceId,
        )
      : undefined;
  if (reviewStep) {
    steps.push(reviewStep);
  }

  return steps;
}

function resolveDependencySkillMapRestoreStep(
  memory: Record<string, unknown>,
  workspaceId: string,
  note: string | undefined,
): RestoreRequestStep | undefined {
  const latestEntry = latestHistoryEntry(memory.dependency_skill_map_history);
  const record = asRecord(latestEntry);
  const entryId = asNonEmptyString(record?.entry_id) ?? asNonEmptyString(record?.entryId);
  const dependencyKey =
    asNonEmptyString(record?.dependency_key) ??
    asNonEmptyString(record?.dependencyKey) ??
    asNonEmptyString(asRecord(memory.workspace)?.latest_learning_focus_area);
  if (!entryId || !dependencyKey) {
    return undefined;
  }

  return {
    requestPath: '/training/dependency-skill-map/restore',
    body: {
      workspace_id: workspaceId,
      dependency_key: dependencyKey,
      history_entry_id: entryId,
      note,
    },
  };
}

function latestHistoryEntry(history: unknown): Record<string, unknown> | undefined {
  if (!Array.isArray(history) || history.length === 0) {
    return undefined;
  }

  return history
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .sort(compareHistoryEntries)
    .at(-1);
}

function compareHistoryEntries(
  left: Record<string, unknown>,
  right: Record<string, unknown>,
): number {
  const leftVersion = asNumber(left.version) ?? -1;
  const rightVersion = asNumber(right.version) ?? -1;
  if (leftVersion !== rightVersion) {
    return leftVersion - rightVersion;
  }

  const leftCreatedAt = asNonEmptyString(left.created_at) ?? asNonEmptyString(left.createdAt) ?? '';
  const rightCreatedAt =
    asNonEmptyString(right.created_at) ?? asNonEmptyString(right.createdAt) ?? '';
  return leftCreatedAt.localeCompare(rightCreatedAt);
}
