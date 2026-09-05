import * as vscode from 'vscode';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import {
  formatSearchHitTeachingSummary,
  normalizeResourceSearchMode,
  resourceSearchModeRequest,
} from '../../../shared/src/resourceSearch';
import { resolveResourceOpenTarget } from '../../../shared/src/resourceOpen';
import type { CommandContext } from '../core/commandContext';
import { attachPreviewAssetUris } from '../core/previewAssetUris';
import type {
  BootstrapData,
  CommandExecutionResult,
  ResourceDetailRecordView,
  ResourceRecordView,
} from '../core/types';
import type { ManagedDataFolderChangeResult } from '../core/sidecarProcessManager';
import { mergeMemorySummarySnapshot, mergeResourceRecords } from '../core/workbenchData';
import { rehydrateWorkbenchRuntime, trainerSessionBlockReason } from '../core/runtimeRehydration';
import { getRuntimeWorkspaceId, withWorkspaceQuery } from './workspaceContext';

const MAX_RESOURCE_UPLOADS = 100;
type ResourceSourceMode = 'files' | 'folder' | 'url';
const RESOURCE_FILTER_EXTENSIONS = [
  'pdf',
  'doc',
  'docx',
  'ppt',
  'pptx',
  'xls',
  'xlsx',
  'csv',
  'tsv',
  'epub',
  'eml',
  'zip',
  'png',
  'svg',
  'jpg',
  'jpeg',
  'webp',
  'gif',
  'bmp',
  'mp3',
  'wav',
  'm4a',
  'mp4',
  'mov',
  'webm',
  'md',
  'markdown',
  'txt',
  'rst',
  'py',
  'ts',
  'tsx',
  'js',
  'jsx',
  'mjs',
  'cjs',
  'json',
  'yaml',
  'yml',
  'toml',
  'ipynb',
  'html',
  'css',
  'scss',
  'less',
  'vue',
  'svelte',
  'astro',
  'go',
  'rs',
  'java',
  'kt',
  'swift',
  'c',
  'cc',
  'cpp',
  'h',
  'hpp',
  'cs',
  'php',
  'rb',
  'sh',
  'zsh',
  'bash',
  'ps1',
  'sql',
];
const SUPPORTED_RESOURCE_EXTENSIONS = new Set(RESOURCE_FILTER_EXTENSIONS.map((extension) => `.${extension}`));
const RESOURCE_UPLOAD_KINDS = new Set(['pdf', 'image', 'text', 'markdown', 'code', 'url'] as const);

type ResourceUploadKind = 'pdf' | 'image' | 'text' | 'markdown' | 'code' | 'url';
type ResourceDeletionFailureReason = 'request_failed' | 'not_confirmed';
type ResourceRestorationFailureReason = 'request_failed' | 'not_confirmed';

interface ResourceDeletionRequest {
  resourceIds: string[];
  isBatch: boolean;
}

interface ResourceDeletionFailure {
  resourceId: string;
  reason: ResourceDeletionFailureReason;
}

interface ResourceDeletionBatchResult {
  requestedResourceIds: string[];
  deletedResourceIds: string[];
  failedResourceIds: string[];
  failures: ResourceDeletionFailure[];
  summaryRefreshed: boolean;
}

interface ResourceRestorationFailure {
  resourceId: string;
  reason: ResourceRestorationFailureReason;
}

interface ResourceRestorationBatchResult {
  requestedResourceIds: string[];
  restoredResourceIds: string[];
  failedResourceIds: string[];
  failures: ResourceRestorationFailure[];
  summaryRefreshed: boolean;
}

interface ResourceUploadBatchResult {
  uploads: unknown[];
  failedCount: number;
}

interface ResourceIndexBatchResult {
  indexed: unknown[];
  failedCount: number;
}

type ResourceRecordObserver = (record: unknown) => Promise<void>;

// A webview can post more than one destructive command before its next state sync.
// Keep deletion plus the resulting snapshot reconciliation ordered per extension host.
const resourceDeletionQueues = new WeakMap<CommandContext, Promise<void>>();
const resourceSearchRequestOwners = new WeakMap<CommandContext, symbol>();
const RESOURCE_SEARCH_REQUEST_ID_PATTERN = /^[a-z0-9-]{1,96}$/i;

interface InlineResourceUpload {
  kind: ResourceUploadKind;
  name: string;
  source: string;
  content?: string;
  contentEncoding?: 'utf-8' | 'base64';
  tags: string[];
  sourceType: 'file' | 'folder' | 'url';
  sourceItems: string[];
}

function resourceMutationAdmissionBlock(context: CommandContext): CommandExecutionResult | undefined {
  const status = context.getHostState().bootstrap.memory?.workspace?.trainerWorkspace?.status;
  if (!status || status === 'managed') {
    return undefined;
  }

  const language = resourceResponseLanguage(context);
  if (status === 'browse') {
    return {
      ok: false,
      message:
        language === 'zh-CN'
          ? '这个项目目前只能浏览。你可以搜索和打开已有资料，但不能添加、索引或修改资料。'
          : 'This project is browse-only. You can search and open existing resources, but cannot add, index, or change them.',
    };
  }
  if (status === 'ignored') {
    return {
      ok: false,
      message:
        language === 'zh-CN'
          ? '这个项目已被忽略。Trainer 不会在这里添加或修改资料；需要时请先在教练页把它加入 Trainer。'
          : 'This project is ignored. Trainer will not add or change resources here. Add it to Trainer from Coach when you are ready.',
    };
  }

  return {
    ok: false,
    message:
      trainerSessionBlockReason(context) ??
      'Choose how Trainer should work with this project before changing its resources.',
  };
}

function resourceResponseLanguage(context: CommandContext): string | undefined {
  return context.getHostState().bootstrap.memory?.workspace?.responseLanguage;
}

function preservedTrashListMessage(context: CommandContext): string {
  return resourceResponseLanguage(context) === 'zh-CN'
    ? '当前回收站内容保持不变。'
    : 'The current Trash list is still shown.';
}

export async function uploadResourceCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  if (!(await context.trustGuard.ensureTrusted('upload training resources'))) {
    return { ok: false, message: 'Workspace trust is required to upload resources.' };
  }

  const requestedMode =
    payload && typeof payload === 'object' && 'mode' in payload
      ? (payload as { mode?: unknown }).mode
      : undefined;

  const directMode: ResourceSourceMode | undefined =
    requestedMode === 'files' || requestedMode === 'folder' || requestedMode === 'url'
      ? requestedMode
      : undefined;
  const inlineUploadResult = parseInlineResourceUploads(payload);
  if (inlineUploadResult.error) {
    return { ok: false, message: inlineUploadResult.error };
  }
  const inlineUploads = inlineUploadResult.uploads;

  const sourceMode:
    | { label: string; value: ResourceSourceMode }
    | undefined = inlineUploads.length > 0
    ? {
        label: 'Inline resources',
        value: resolveInlineUploadMode(inlineUploads, directMode),
      }
    : directMode
    ? {
        label: directMode === 'files' ? 'Local files' : directMode === 'folder' ? 'Folder' : 'URL',
        value: directMode,
      }
    : await vscode.window.showQuickPick(
    [
      {
        label: 'Local files',
        description: 'Select up to 100 files from this machine',
        value: 'files' as const,
      },
      {
        label: 'Folder',
        description: 'Recursively import files from one folder (up to 100 files)',
        value: 'folder' as const,
      },
      {
        label: 'URL',
        description: 'Attach a remote page or document link',
        value: 'url' as const,
      },
    ],
    {
      title: 'Add Trainer resource',
      ignoreFocusOut: true,
    },
  );

  if (!sourceMode) {
    return { ok: false, cancelled: true };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const uploads: unknown[] = [];
  const workspaceId = getRuntimeWorkspaceId(context);
  let truncated = false;
  let skippedUnsupported = 0;
  let failedUploads = 0;

  const patchResourceRecords = async (records: unknown[]) => {
    if (records.length === 0) {
      return;
    }
    await context.patchWorkbenchData(
      mergeResourceRecords(context.getHostState().bootstrap, records),
    );
  };
  const recordUploaded = async (upload: unknown) => {
    uploads.push(upload);
    await patchResourceRecords([upload]);
  };
  const recordIndexed = async (indexed: unknown) => {
    await patchResourceRecords([indexed]);
  };

  if (inlineUploads.length > 0) {
    truncated = inlineUploads.length > MAX_RESOURCE_UPLOADS;
    const limitedUploads = inlineUploads.slice(0, MAX_RESOURCE_UPLOADS);
    const uploadResult = await uploadInlineResources(
      context,
      status.port,
      workspaceId,
      limitedUploads,
      recordUploaded,
    );
    failedUploads += uploadResult.failedCount;
  } else if (sourceMode.value === 'files') {
    const picks = await vscode.window.showOpenDialog({
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: true,
      openLabel: 'Upload to Trainer',
      filters: {
        Resources: RESOURCE_FILTER_EXTENSIONS,
        All: ['*'],
      },
    });

    if (!picks?.length) {
      return { ok: false, cancelled: true };
    }
    const allFiles = picks.map((uri) => uri.fsPath);
    const supportedFiles = allFiles.filter((filePath) => isSupportedResourceFile(filePath));
    skippedUnsupported = allFiles.length - supportedFiles.length;
    if (supportedFiles.length === 0) {
      return {
        ok: false,
        message:
          skippedUnsupported > 0
            ? `Skipped ${skippedUnsupported} unsupported file(s). No supported resources were selected.`
            : 'No resources selected.',
      };
    }
    truncated = supportedFiles.length > MAX_RESOURCE_UPLOADS;
    const limitedFiles = supportedFiles.slice(0, MAX_RESOURCE_UPLOADS);

    const uploadResult = await uploadLocalFiles(
      context,
      status.port,
      workspaceId,
      limitedFiles,
      undefined,
      recordUploaded,
    );
    failedUploads += uploadResult.failedCount;
  } else if (sourceMode.value === 'folder') {
    const picks = await vscode.window.showOpenDialog({
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      openLabel: 'Import folder into Trainer',
    });

    const folderPath = picks?.[0]?.fsPath;
    if (!folderPath) {
      return { ok: false, cancelled: true };
    }

    const folderImport = await collectImportableFiles(
      folderPath,
      MAX_RESOURCE_UPLOADS,
    );
    const discoveredFiles = folderImport.files;
    truncated = folderImport.truncated;
    skippedUnsupported = folderImport.skippedUnsupported;
    if (discoveredFiles.length === 0) {
      return {
        ok: false,
        message:
          skippedUnsupported > 0
            ? `Skipped ${skippedUnsupported} unsupported file(s). No supported files were found in that folder.`
            : 'No supported files were found in that folder.',
      };
    }

    const uploadResult = await uploadLocalFiles(
      context,
      status.port,
      workspaceId,
      discoveredFiles,
      folderPath,
      recordUploaded,
    );
    failedUploads += uploadResult.failedCount;
  } else {
    const source = await vscode.window.showInputBox({
      title: 'Trainer resource URL',
      prompt: 'Paste the URL to attach to this workspace.',
      ignoreFocusOut: true,
      validateInput: (value) => validateResourceUrl(value),
    });
    if (!source) {
      return { ok: false, cancelled: true };
    }

    try {
      const upload = await context.sidecarClient.postJson<unknown>(status.port, '/resource/upload', {
        session_id: context.getSessionId(),
        workspace_id: workspaceId,
        kind: 'url',
        name: inferUrlTitle(source),
        source,
        tags: [],
      });
      await recordUploaded(upload);
    } catch {
      failedUploads += 1;
    }
  }

  if (uploads.length === 0) {
    return {
      ok: false,
      message: buildResourceImportMessage({
        uploadsCount: 0,
        indexedCount: 0,
        failedUploads,
        failedIndexes: 0,
        summaryRefreshed: true,
        truncated,
        skippedUnsupported,
        sourceMode: sourceMode.value,
        language: resourceResponseLanguage(context),
      }),
      data: [],
    };
  }

  const indexResult = await indexUploadedResources(
    context,
    status.port,
    workspaceId,
    uploads,
    recordIndexed,
  );
  const indexed = indexResult.indexed;
  let summaryRefreshed = true;
  try {
    const summary = await context.sidecarClient.getJson<unknown>(
      status.port,
      withWorkspaceQuery('/memory/summary', context),
    );
    await context.patchWorkbenchData(
      mergeMemorySummarySnapshot(
        context.getHostState().bootstrap,
        summary,
        getRuntimeWorkspaceId(context),
      ),
    );
  } catch {
    summaryRefreshed = false;
  }

  const completed = failedUploads === 0 && indexResult.failedCount === 0 && summaryRefreshed;
  return {
    ok: completed,
    message: buildResourceImportMessage({
      uploadsCount: uploads.length,
      indexedCount: indexed.length,
      failedUploads,
      failedIndexes: indexResult.failedCount,
      summaryRefreshed,
      truncated,
      skippedUnsupported,
      sourceMode: sourceMode.value,
      language: resourceResponseLanguage(context),
    }),
    data: indexed.length > 0 ? indexed : uploads,
  };
}

export async function indexResourcesCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  if (!(await context.trustGuard.ensureTrusted('index training resources'))) {
    return { ok: false, message: 'Workspace trust is required to index resources.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const resources = context.getHostState().bootstrap.resources;
  const indexed: unknown[] = [];
  let failedCount = 0;
  for (const resource of resources) {
    if (resource.status === 'ready' && resource.freshness !== 'stale') {
      continue;
    }
    try {
      const response = await context.sidecarClient.postJson<unknown>(status.port, '/resource/index', {
        session_id: context.getSessionId(),
        workspace_id: getRuntimeWorkspaceId(context),
        resource_id: resource.id,
        enable_network: resource.kind === 'url',
      });
      indexed.push(response);
    } catch {
      failedCount += 1;
    }
  }

  if (indexed.length > 0) {
    await context.patchWorkbenchData(
      mergeResourceRecords(context.getHostState().bootstrap, indexed),
    );
  }

  let summaryRefreshed = true;
  try {
    const summary = await context.sidecarClient.getJson<unknown>(
      status.port,
      withWorkspaceQuery('/memory/summary', context),
    );
    await context.patchWorkbenchData(
      mergeMemorySummarySnapshot(
        context.getHostState().bootstrap,
        summary,
        getRuntimeWorkspaceId(context),
      ),
    );
  } catch {
    summaryRefreshed = false;
  }

  return {
    ok: failedCount === 0 && summaryRefreshed,
    message: buildResourceIndexMessage({
      indexedCount: indexed.length,
      failedCount,
      summaryRefreshed,
      language: resourceResponseLanguage(context),
    }),
    data: indexed,
  };
}

export async function openResourceCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const resourceId =
    payload && typeof payload === 'object' && 'resourceId' in payload
      ? (payload as { resourceId?: unknown }).resourceId
      : undefined;

  if (typeof resourceId !== 'string') {
    return { ok: false, message: 'No resource selected.' };
  }

  const resource = context.getHostState().bootstrap.resources.find((item) => item.id === resourceId);
  if (!resource) {
    return { ok: false, message: 'The selected resource could not be found.' };
  }

  const target = resolveResourceOpenTarget(resource);
  if (target.kind === 'unavailable') {
    return {
      ok: false,
      message:
        target.reason === 'missing_source'
          ? 'This resource has no source to open.'
          : 'This resource has an invalid source to open.',
    };
  }

  if (target.kind === 'vscode') {
    await openLocalPathInVscode(target.source);
  } else {
    await vscode.env.openExternal(vscode.Uri.parse(target.source));
  }
  return {
    ok: true,
    message: `Opened ${resource.title}.`,
  };
}

async function openLocalPathInVscode(targetPath: string): Promise<void> {
  const targetUri = vscode.Uri.file(targetPath);
  await vscode.commands.executeCommand('vscode.open', targetUri, {
    preview: false,
    preserveFocus: false,
  });
}

export function deleteResourceCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const previousDeletion = resourceDeletionQueues.get(context) ?? Promise.resolve();
  const operation = previousDeletion
    .catch(() => undefined)
    .then(() => executeDeleteResourceCommand(context, payload));

  resourceDeletionQueues.set(
    context,
    operation.then(
      () => undefined,
      () => undefined,
    ),
  );
  return operation;
}

async function executeDeleteResourceCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  if (!(await context.trustGuard.ensureTrusted('delete training resources'))) {
    return { ok: false, message: 'Workspace trust is required to delete resources.' };
  }

  const deletionRequest = extractResourceDeletionRequest(payload);
  if (deletionRequest.resourceIds.length === 0) {
    return { ok: false, message: 'No resources selected.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const deletionSnapshot = context.getHostState().bootstrap;
  const resourcesById = new Map(deletionSnapshot.resources.map((resource) => [resource.id, resource]));
  const deletedResourceIds: string[] = [];
  const failedDeletions: ResourceDeletionFailure[] = [];
  const deletionResponses: unknown[] = [];

  // Keep trash/checkpoint operations ordered so the server can preserve its workspace ledger.
  for (const resourceId of deletionRequest.resourceIds) {
    try {
      const response = await context.sidecarClient.postJson<unknown>(status.port, '/resource/delete', {
        session_id: context.getSessionId(),
        workspace_id: getRuntimeWorkspaceId(context),
        resource_id: resourceId,
      });
      if (!wasResourceDeletionConfirmed(response)) {
        failedDeletions.push({ resourceId, reason: 'not_confirmed' });
        continue;
      }
      deletedResourceIds.push(resourceId);
      deletionResponses.push(response);
    } catch {
      // The user-facing result deliberately avoids raw sidecar errors, which can include local paths.
      failedDeletions.push({ resourceId, reason: 'request_failed' });
    }
  }

  let summaryRefreshed = true;
  let trashSnapshotConfirmed = false;
  if (deletedResourceIds.length > 0) {
    let summaryPatch: Partial<BootstrapData> = {};
    let latestSnapshot = context.getHostState().bootstrap;
    try {
      const summary = await context.sidecarClient.getJson<unknown>(
        status.port,
        withWorkspaceQuery('/memory/summary', context),
      );
      latestSnapshot = context.getHostState().bootstrap;
      summaryPatch = mergeMemorySummarySnapshot(
        latestSnapshot,
        summary,
        getRuntimeWorkspaceId(context),
      );
    } catch {
      // The local deletion snapshot remains authoritative for confirmed deletions.
      summaryRefreshed = false;
      latestSnapshot = context.getHostState().bootstrap;
    }

    let refreshedDeletedResources: BootstrapData['deletedResources'];
    try {
      refreshedDeletedResources = await loadDeletedResources(context, status.port);
      trashSnapshotConfirmed = true;
    } catch {
      // Keep the last known Trash state when a successful delete cannot refresh its recovery list.
    }

    const deletedResourceIdSet = new Set(deletedResourceIds);
    const deletedResources = deletedResourceIds
      .map((resourceId) => resourcesById.get(resourceId))
      .filter((resource): resource is ResourceRecordView => resource !== undefined);
    try {
      await context.patchWorkbenchData({
        ...summaryPatch,
        resources: (summaryPatch.resources ?? latestSnapshot.resources).filter(
          (resource) => !deletedResourceIdSet.has(resource.id),
        ),
        ...(refreshedDeletedResources ? { deletedResources: refreshedDeletedResources } : {}),
        // A paged search result cannot truthfully adjust its total from only the loaded hits.
        resourceSearch: undefined,
        memory: {
          ...(summaryPatch.memory ?? latestSnapshot.memory),
          selectedResourceDetail: shouldClearSelectedResources(latestSnapshot, deletedResourceIdSet)
            ? undefined
            : latestSnapshot.memory.selectedResourceDetail,
          sandboxPreview: clearDeletedResourcePreviews(latestSnapshot, deletedResources),
        },
      } as Partial<BootstrapData>);
    } catch {
      return {
        ok: false,
        message:
          'Resources were deleted, but the workbench could not refresh. Reopen Resources to verify the current state.',
        data: buildResourceDeletionBatchResult(
          deletionRequest.resourceIds,
          deletedResourceIds,
          failedDeletions,
          summaryRefreshed,
        ),
      };
    }
  }

  const batchResult = buildResourceDeletionBatchResult(
    deletionRequest.resourceIds,
    deletedResourceIds,
    failedDeletions,
    summaryRefreshed,
  );
  const fullySucceeded =
    deletedResourceIds.length > 0 && failedDeletions.length === 0 && trashSnapshotConfirmed;

  return {
    ok: fullySucceeded,
    message: buildResourceDeletionResultMessage(
      deletionRequest,
      deletionResponses,
      batchResult,
      trashSnapshotConfirmed,
    ),
    data:
      !deletionRequest.isBatch && fullySucceeded && summaryRefreshed
        ? deletionResponses[0]
        : batchResult,
  };
}

export function restoreResourceCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const previousMutation = resourceDeletionQueues.get(context) ?? Promise.resolve();
  const operation = previousMutation
    .catch(() => undefined)
    .then(() => executeRestoreResourceCommand(context, payload));

  resourceDeletionQueues.set(
    context,
    operation.then(
      () => undefined,
      () => undefined,
    ),
  );
  return operation;
}

export function refreshResourceTrashCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const previousMutation = resourceDeletionQueues.get(context) ?? Promise.resolve();
  const operation = previousMutation
    .catch(() => undefined)
    .then(() => executeRefreshResourceTrashCommand(context));

  resourceDeletionQueues.set(
    context,
    operation.then(
      () => undefined,
      () => undefined,
    ),
  );
  return operation;
}

async function executeRefreshResourceTrashCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return {
      ...admissionBlock,
      message: `${admissionBlock.message ?? 'Trainer cannot refresh the Trash for this project yet.'} ${preservedTrashListMessage(context)}`,
    };
  }

  if (!(await context.trustGuard.ensureTrusted('refresh the resource Trash'))) {
    return {
      ok: false,
      message:
        resourceResponseLanguage(context) === 'zh-CN'
          ? '请先信任当前工作区，再刷新回收站。当前回收站内容保持不变。'
          : 'Trust this workspace before refreshing the Trash. The current Trash list is still shown.',
    };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  try {
    const deletedResources = await loadDeletedResources(context, status.port);
    await context.patchWorkbenchData({ deletedResources });
    return {
      ok: true,
      message:
        deletedResources.length > 0
          ? `Trash refreshed. ${formatResourceCount(deletedResources.length)} can be restored.`
          : 'Trash refreshed. No deleted resources are available.',
      data: deletedResources,
    };
  } catch {
    return {
      ok: false,
      message: 'Could not refresh the resource Trash. The last known recovery state is still shown.',
    };
  }
}

async function executeRestoreResourceCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  if (!(await context.trustGuard.ensureTrusted('restore training resources'))) {
    return { ok: false, message: 'Workspace trust is required to restore resources.' };
  }

  const restorationRequest = extractResourceDeletionRequest(payload);
  if (restorationRequest.resourceIds.length === 0) {
    return { ok: false, message: 'No deleted resources selected.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const restoredResourceIds: string[] = [];
  const failedRestorations: ResourceRestorationFailure[] = [];
  const restorationResponses: unknown[] = [];

  for (const resourceId of restorationRequest.resourceIds) {
    try {
      const response = await context.sidecarClient.postJson<unknown>(status.port, '/resource/restore', {
        session_id: context.getSessionId(),
        workspace_id: getRuntimeWorkspaceId(context),
        resource_id: resourceId,
      });
      if (!wasResourceRestorationConfirmed(response)) {
        failedRestorations.push({ resourceId, reason: 'not_confirmed' });
        continue;
      }
      restoredResourceIds.push(resourceId);
      restorationResponses.push(response);
    } catch {
      // The workbench result stays path-safe even when a stale Trash item cannot be restored.
      failedRestorations.push({ resourceId, reason: 'request_failed' });
    }
  }

  let summaryRefreshed = true;
  let trashSnapshotConfirmed = false;
  if (restoredResourceIds.length > 0) {
    let summaryPatch: Partial<BootstrapData> = {};
    let latestSnapshot = context.getHostState().bootstrap;
    try {
      const summary = await context.sidecarClient.getJson<unknown>(
        status.port,
        withWorkspaceQuery('/memory/summary', context),
      );
      latestSnapshot = context.getHostState().bootstrap;
      summaryPatch = mergeMemorySummarySnapshot(
        latestSnapshot,
        summary,
        getRuntimeWorkspaceId(context),
      );
    } catch {
      summaryRefreshed = false;
      latestSnapshot = context.getHostState().bootstrap;
    }

    let refreshedDeletedResources: BootstrapData['deletedResources'];
    try {
      refreshedDeletedResources = await loadDeletedResources(context, status.port);
      trashSnapshotConfirmed = true;
    } catch {
      // Keep the last known Trash state when a successful restore cannot refresh its recovery list.
    }

    const restoredRecords = restorationResponses
      .map((response) => asRecord(response)?.resource)
      .filter((resource): resource is Record<string, unknown> => resource !== undefined);
    const resourcePatch = mergeResourceRecords(
      { ...latestSnapshot, ...summaryPatch } as BootstrapData,
      restoredRecords,
    );
    const latestSandboxState = restorationResponses
      .map((response) => asRecord(response)?.sandbox_state ?? asRecord(response)?.sandboxState)
      .find((value) => value !== undefined);

    try {
      await context.patchWorkbenchData({
        ...summaryPatch,
        ...resourcePatch,
        ...(refreshedDeletedResources ? { deletedResources: refreshedDeletedResources } : {}),
        resourceSearch: undefined,
        memory: {
          ...(summaryPatch.memory ?? latestSnapshot.memory),
          sandboxState: latestSandboxState
            ? normalizeSandboxState(latestSandboxState)
            : latestSnapshot.memory.sandboxState,
          selectedResourceDetail: undefined,
          sandboxPreview: undefined,
        },
      } as Partial<BootstrapData>);
    } catch {
      return {
        ok: false,
        message:
          'Resources were restored, but the workbench could not refresh. Reopen Resources to verify the current state.',
        data: buildResourceRestorationBatchResult(
          restorationRequest.resourceIds,
          restoredResourceIds,
          failedRestorations,
          summaryRefreshed,
        ),
      };
    }
  }

  const batchResult = buildResourceRestorationBatchResult(
    restorationRequest.resourceIds,
    restoredResourceIds,
    failedRestorations,
    summaryRefreshed,
  );
  const fullySucceeded =
    restoredResourceIds.length > 0 && failedRestorations.length === 0 && trashSnapshotConfirmed;
  return {
    ok: fullySucceeded,
    message: buildResourceRestorationResultMessage(batchResult, trashSnapshotConfirmed),
    data: batchResult,
  };
}

export async function restoreSandboxPathCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  if (!(await context.trustGuard.ensureTrusted('restore sandbox resources'))) {
    return { ok: false, message: 'Workspace trust is required to restore sandbox resources.' };
  }

  const sandboxPath =
    payload && typeof payload === 'object' && 'path' in payload
      ? (payload as { path?: unknown }).path
      : undefined;
  if (typeof sandboxPath !== 'string' || !sandboxPath.trim()) {
    return { ok: false, message: 'No sandbox path was provided.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const workspace = context.getHostState().workspace;
  const sandboxState = await context.sidecarClient.postJson<unknown>(status.port, '/sandbox/restore', {
    session_id: context.getSessionId(),
    workspace_id: getRuntimeWorkspaceId(context),
    path: sandboxPath,
    // Ordinary restore is not organize-confirm; never claim destructive bypass.
    explicit_destructive_policy: false,
    // Host-attested VS Code trust + remote identity (never JSON-omit undefined).
    remote_name: workspace.remoteName ?? '',
    workspace_trusted: Boolean(workspace.trusted),
  });

  await context.patchWorkbenchData({
    memory: {
      ...context.getHostState().bootstrap.memory,
      sandboxState: normalizeSandboxState(sandboxState),
    },
  } as Partial<BootstrapData>);

  return {
    ok: true,
    message: 'Sandbox path restored from trash.',
    data: sandboxState,
  };
}

export async function chooseManagedDataFolderCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  if (!(await context.trustGuard.ensureTrusted('change the Trainer managed data folder'))) {
    return { ok: false, message: 'Workspace trust is required to change the managed data folder.' };
  }

  const workspaceFolder = context.getHostState().workspace.workspaceFolder;
  const currentFolder = context.sidecarManager.getManagedDataFolderSnapshot(workspaceFolder);
  const picks = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    defaultUri: vscode.Uri.file(currentFolder.effectivePath),
    openLabel: 'Use this folder',
    title: 'Choose Trainer managed data folder',
  });
  const targetFolder = picks?.[0]?.fsPath;
  if (!targetFolder) {
    return { ok: false, message: 'Managed data folder selection cancelled.' };
  }

  const change = await context.sidecarManager.configureManagedDataFolder(targetFolder, workspaceFolder);
  return applyManagedDataFolderChange(context, change);
}

export async function resetManagedDataFolderCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  if (!(await context.trustGuard.ensureTrusted('reset the Trainer managed data folder'))) {
    return { ok: false, message: 'Workspace trust is required to reset the managed data folder.' };
  }

  const workspaceFolder = context.getHostState().workspace.workspaceFolder;
  const change = await context.sidecarManager.resetManagedDataFolder(workspaceFolder);
  return applyManagedDataFolderChange(context, change);
}

export async function chooseSandboxRootCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  if (!(await context.trustGuard.ensureTrusted('change the workspace sandbox root'))) {
    return { ok: false, message: 'Workspace trust is required to change the sandbox root.' };
  }

  const current = context.getHostState().bootstrap;
  const defaultPath =
    current.memory.sandboxState?.sandboxRootPath ??
    current.memory.sandboxState?.rootPath ??
    current.memory.sandboxState?.workspaceRootPath ??
    current.memory.sandboxState?.activeWorkspaceRoot;
  const picks = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    defaultUri: defaultPath ? vscode.Uri.file(defaultPath) : undefined,
    openLabel: 'Use as sandbox root',
    title: 'Choose workspace sandbox root',
  });
  const targetFolder = picks?.[0]?.fsPath;
  if (!targetFolder) {
    return { ok: false, message: 'Sandbox root selection cancelled.' };
  }

  return applySandboxRootChange(context, { rootPath: targetFolder });
}

export async function resetSandboxRootCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  if (!(await context.trustGuard.ensureTrusted('reset the workspace sandbox root'))) {
    return { ok: false, message: 'Workspace trust is required to reset the sandbox root.' };
  }

  return applySandboxRootChange(context, { clear: true });
}

export async function searchResourcesCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const request = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
  const query = typeof request.query === 'string' ? request.query.trim() : '';
  const requestId = normalizeResourceSearchRequestId(request);
  const requestOwner = Symbol('resource-search');
  resourceSearchRequestOwners.set(context, requestOwner);
  if (!query) {
    return { ok: false, message: 'Enter a resource search query.' };
  }

  if (!(await context.trustGuard.ensureTrusted('search training resources'))) {
    return { ok: false, message: 'Workspace trust is required to search resources.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const body: Record<string, unknown> = {
    session_id: context.getSessionId(),
    workspace_id: getRuntimeWorkspaceId(context),
    query,
  };
  const searchMode = normalizeResourceSearchMode(request.mode ?? request.resourceSearchMode);
  const modeRequest = resourceSearchModeRequest(searchMode);
  appendOptionalSearchField(body, 'top_k', request.topK);
  appendOptionalSearchField(body, 'project_scope', request.projectScope);
  appendOptionalSearchField(body, 'trust_state', modeRequest.trustState ?? request.trustState);
  appendOptionalSearchField(body, 'file_type', request.fileType);
  appendOptionalSearchField(body, 'source_type', request.sourceType);
  appendOptionalSearchField(body, 'kind', request.kind);
  appendOptionalSearchField(body, 'index_state', modeRequest.indexState ?? request.indexState);

  const response = await context.sidecarClient.postJson<unknown>(status.port, '/resource/search', body);
  const normalized = normalizeResourceSearchResult(response, query, requestId);

  if (resourceSearchRequestOwners.get(context) === requestOwner) {
    await context.patchWorkbenchData({
      resourceSearch: normalized,
    } as Partial<BootstrapData>);
  }

  return {
    ok: true,
    message: buildResourceSearchMessage(normalized),
    data: normalized,
  };
}

export async function previewResourceCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('preview training resources'))) {
    return { ok: false, message: 'Workspace trust is required to preview resources.' };
  }

  const resourceId =
    payload && typeof payload === 'object' && 'resourceId' in payload
      ? (payload as { resourceId?: unknown }).resourceId
      : undefined;
  const explicitPath =
    payload && typeof payload === 'object' && 'path' in payload
      ? (payload as { path?: unknown }).path
      : undefined;
  const resource =
    typeof resourceId === 'string'
      ? context.getHostState().bootstrap.resources.find((item) => item.id === resourceId)
      : undefined;
  const requestedPath = typeof explicitPath === 'string' ? explicitPath.trim() : undefined;
  const source = resource?.source?.trim();
  const previewPath = resource?.sandboxPath?.trim() ??
    (requestedPath && !/^https?:\/\//i.test(requestedPath) ? requestedPath : undefined);

  if (!previewPath) {
    return {
      ok: false,
      message: 'This resource has no governed sandbox copy to preview. Use native open for the original source.',
      data: { capability: 'native-open-only', source },
    };
  }

  const sandboxRoot = resolveSandboxRootPath(context);
  if (!sandboxRoot || !isPathWithinRoot(previewPath, sandboxRoot)) {
    return { ok: false, message: 'The requested preview path is outside the governed Trainer sandbox.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  try {
    const response = await context.sidecarClient.postJson<unknown>(status.port, '/sandbox/preview', {
      session_id: context.getSessionId(),
      workspace_id: getRuntimeWorkspaceId(context),
      path: previewPath,
    });
    const preview = normalizeSandboxPreview(response);
    const current = context.getHostState().bootstrap;
    await context.patchWorkbenchData(
      attachPreviewAssetUris(
        {
          // Pass conversation so host can invent file_preview for document+.docx
          // (sidecar never emits Coach parts; omit conversation elsewhere = fail-closed).
          conversation: current.conversation,
          memory: {
            ...current.memory,
            sandboxPreview: preview,
            selectedResourceDetail: resource
              ? normalizeResourceDetailRecord(resource)
              : current.memory.selectedResourceDetail,
          },
        } as Partial<BootstrapData>,
        (filePath) => normalizeWorkbenchAssetUri(context.workbench.resolveWebviewUriForPath?.(filePath)),
      ),
    );
    return {
      ok: true,
      message: `Previewed ${resource?.title ?? path.basename(previewPath)}.`,
      data: preview,
    };
  } catch {
    return {
      ok: false,
      message: 'The governed preview is unavailable. Use native open if the source is still accessible.',
    };
  }
}

function resolveSandboxRootPath(context: CommandContext): string | undefined {
  const sandboxState = context.getHostState().bootstrap.memory.sandboxState;
  return asString(
    sandboxState?.sandboxRootPath ??
      sandboxState?.rootPath,
  );
}

function isPathWithinRoot(targetPath: string, rootPath: string): boolean {
  const relative = path.relative(path.resolve(rootPath), path.resolve(targetPath));
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

export async function createSandboxDirectoryCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  if (!(await context.trustGuard.ensureTrusted('create sandbox directories'))) {
    return { ok: false, message: 'Workspace trust is required to create sandbox directories.' };
  }

  const requestedPath =
    payload && typeof payload === 'object' && 'path' in payload
      ? (payload as { path?: unknown }).path
      : undefined;
  const directoryPath = typeof requestedPath === 'string' ? requestedPath.trim() : '';
  if (!directoryPath) {
    return { ok: false, message: 'Provide a sandbox directory path.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const current = context.getHostState().bootstrap;
  const workspace = context.getHostState().workspace;
  const response = await context.sidecarClient.postJson<unknown>(status.port, '/sandbox/mkdir', {
    workspace_id: getRuntimeWorkspaceId(context),
    path: directoryPath,
    // Ordinary mkdir is not organize-confirm; never claim destructive bypass.
    explicit_destructive_policy: false,
    // Host-attested VS Code trust + remote identity (never JSON-omit undefined).
    remote_name: workspace.remoteName ?? '',
    workspace_trusted: Boolean(workspace.trusted),
  });
  const sandboxState = normalizeSandboxState(response);
  const sandboxPreview = extractSandboxStatePreview(response);
  const selectedResourceDetail = resolveSandboxRefreshSelectedResourceDetail(
    current.resources,
    current.memory.selectedResourceDetail,
    sandboxPreview?.path,
    asString(asRecord(response)?.selected_path) ?? asString(asRecord(response)?.selectedPath),
    asString(asRecord(response)?.selected_path) ?? asString(asRecord(response)?.selectedPath),
  );
  const memoryPatch = attachPreviewAssetUris(
    {
      memory: {
        ...(current.memory ?? {}),
        sandboxState,
        sandboxPreview,
        selectedResourceDetail,
      },
    } as Partial<BootstrapData>,
    (filePath) => normalizeWorkbenchAssetUri(context.workbench.resolveWebviewUriForPath?.(filePath)),
  );
  await context.patchWorkbenchData(memoryPatch);

  return {
    ok: true,
    message: `Created sandbox folder ${directoryPath}.`,
    data: sandboxState,
  };
}

export async function createSandboxFileCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  if (!(await context.trustGuard.ensureTrusted('create sandbox files'))) {
    return { ok: false, message: 'Workspace trust is required to create sandbox files.' };
  }

  const request = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
  const requestedPath = typeof request.path === 'string' ? request.path.trim() : '';
  const content = typeof request.content === 'string' ? request.content : '';
  if (!requestedPath) {
    return { ok: false, message: 'Provide a sandbox file path.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const current = context.getHostState().bootstrap;
  const workspace = context.getHostState().workspace;
  const previewResponse = await context.sidecarClient.postJson<unknown>(status.port, '/sandbox/write', {
    workspace_id: getRuntimeWorkspaceId(context),
    path: requestedPath,
    content,
    create: true,
    // Ordinary write is not organize-confirm; never claim destructive bypass.
    explicit_destructive_policy: false,
    // Host-attested VS Code trust + remote identity (never JSON-omit undefined).
    remote_name: workspace.remoteName ?? '',
    workspace_trusted: Boolean(workspace.trusted),
  });
  const sandboxState = await refreshSandboxSelectionFromPreview(
    context,
    status.port,
    current,
    previewResponse,
    requestedPath,
  );

  return {
    ok: true,
    message: `Created sandbox file ${requestedPath}.`,
    data: sandboxState,
  };
}

export async function renameSandboxPathCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  if (!(await context.trustGuard.ensureTrusted('rename sandbox paths'))) {
    return { ok: false, message: 'Workspace trust is required to rename sandbox paths.' };
  }

  const request = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
  const sandboxPath = typeof request.path === 'string' ? request.path.trim() : '';
  const nextPath =
    typeof request.newPath === 'string'
      ? request.newPath.trim()
      : typeof request.nextPath === 'string'
        ? request.nextPath.trim()
        : '';
  if (!sandboxPath) {
    return { ok: false, message: 'No sandbox path was provided.' };
  }
  if (!nextPath) {
    return { ok: false, message: 'Provide the next sandbox path.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const current = context.getHostState().bootstrap;
  const workspace = context.getHostState().workspace;
  const previewResponse = await context.sidecarClient.postJson<unknown>(status.port, '/sandbox/rename', {
    workspace_id: getRuntimeWorkspaceId(context),
    path: sandboxPath,
    new_path: nextPath,
    // Ordinary rename is not organize-confirm; never claim destructive bypass.
    explicit_destructive_policy: false,
    // Host-attested VS Code trust + remote identity (never JSON-omit undefined).
    remote_name: workspace.remoteName ?? '',
    workspace_trusted: Boolean(workspace.trusted),
  });
  const sandboxState = await refreshSandboxSelectionFromPreview(
    context,
    status.port,
    current,
    previewResponse,
    sandboxPath,
  );

  return {
    ok: true,
    message: `Sandbox path renamed to ${nextPath}.`,
    data: sandboxState,
  };
}

export async function deleteSandboxPathCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  if (!(await context.trustGuard.ensureTrusted('delete sandbox paths'))) {
    return { ok: false, message: 'Workspace trust is required to delete sandbox paths.' };
  }

  const sandboxPath =
    payload && typeof payload === 'object' && 'path' in payload
      ? (payload as { path?: unknown }).path
      : undefined;
  if (typeof sandboxPath !== 'string' || !sandboxPath.trim()) {
    return { ok: false, message: 'No sandbox path was provided.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const current = context.getHostState().bootstrap;
  const workspace = context.getHostState().workspace;
  const response = await context.sidecarClient.postJson<unknown>(status.port, '/sandbox/delete', {
    workspace_id: getRuntimeWorkspaceId(context),
    path: sandboxPath,
    // Ordinary delete is not organize-confirm; never claim destructive bypass.
    explicit_destructive_policy: false,
    // Host-attested VS Code trust + remote identity (never JSON-omit undefined).
    remote_name: workspace.remoteName ?? '',
    workspace_trusted: Boolean(workspace.trusted),
  });
  const sandboxState = normalizeSandboxState(response);
  const sandboxPreview = extractSandboxStatePreview(response);
  const currentSelected = current.memory.selectedResourceDetail
    ? normalizeResourceDetailRecord(current.memory.selectedResourceDetail)
    : undefined;
  const selectedResourceDetail =
    currentSelected &&
    (currentSelected.sandboxPath === sandboxPath || currentSelected.source === sandboxPath)
      ? undefined
      : current.memory.selectedResourceDetail;
  const memoryPatch = attachPreviewAssetUris(
    {
      memory: {
        ...(current.memory ?? {}),
        sandboxState,
        sandboxPreview,
        selectedResourceDetail,
      },
    } as Partial<BootstrapData>,
    (filePath) => normalizeWorkbenchAssetUri(context.workbench.resolveWebviewUriForPath?.(filePath)),
  );
  await context.patchWorkbenchData(memoryPatch);

  return {
    ok: true,
    message: 'Sandbox path moved to Trash.',
    data: sandboxState,
  };
}

export async function deleteSandboxPathsCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const request = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
  const candidatePaths = Array.isArray(request.paths) ? request.paths : [];
  const paths = candidatePaths
    .map((value) => (typeof value === 'string' ? value.trim() : ''))
    .filter((value, index, items) => value.length > 0 && items.indexOf(value) === index);

  if (paths.length === 0) {
    return { ok: false, message: 'No sandbox paths were provided.' };
  }

  let lastResult: CommandExecutionResult | undefined;
  for (const sandboxPath of paths) {
    const result = await deleteSandboxPathCommand(context, { path: sandboxPath });
    if (!result.ok) {
      return {
        ok: false,
        message: result.message || `Failed while deleting ${sandboxPath}.`,
        data: result.data,
      };
    }
    lastResult = result;
  }

  return {
    ok: true,
    message:
      paths.length === 1
        ? 'Sandbox path moved to Trash.'
        : `${paths.length} sandbox paths moved to Trash.`,
    data: lastResult?.data,
  };
}

export async function refreshSandboxCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('refresh resource sandbox capability'))) {
    return { ok: false, message: 'Workspace trust is required to refresh sandbox capability.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }
  const port = status.port;

  const current = context.getHostState().bootstrap;
  const refreshSelection = resolveSandboxRefreshSelection(current);
  const response = await context.sidecarClient.getJson<unknown>(
    port,
    buildSandboxStateRequestPath(context, refreshSelection),
  );
  const sandboxState = normalizeSandboxState(response);
  const sandboxPreview = extractSandboxStatePreview(response);
  const selectedResourceDetail = resolveSandboxRefreshSelectedResourceDetail(
    current.resources,
    current.memory.selectedResourceDetail,
    sandboxPreview?.path,
    refreshSelection.selectedPath,
    asString(asRecord(response)?.selected_path) ?? asString(asRecord(response)?.selectedPath),
  );
  const memoryPatch = attachPreviewAssetUris(
    {
      memory: {
        ...(current.memory ?? {}),
        sandboxState,
        sandboxPreview,
        selectedResourceDetail,
      },
    } as Partial<BootstrapData>,
    (filePath) => normalizeWorkbenchAssetUri(context.workbench.resolveWebviewUriForPath?.(filePath)),
  );
  await context.patchWorkbenchData(memoryPatch);

  return {
    ok: true,
    message: 'Sandbox capability refreshed.',
    data: sandboxState,
  };
}

export async function revealSandboxPathCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('open sandbox paths in the system file manager'))) {
    return { ok: false, message: 'Workspace trust is required to open sandbox paths.' };
  }

  const request = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
  const requestedPath = typeof request.path === 'string' ? request.path.trim() : '';
  const current = context.getHostState().bootstrap;
  const fallbackRoot =
    current.memory.sandboxState?.sandboxRootPath ??
    current.memory.sandboxState?.rootPath ??
    current.memory.sandboxState?.workspaceRootPath ??
    current.memory.sandboxState?.activeWorkspaceRoot ??
    '';
  const targetPath = requestedPath || fallbackRoot;

  if (!targetPath) {
    return { ok: false, message: 'No sandbox path is available to open.' };
  }

  try {
    await fs.access(targetPath);
  } catch {
    return { ok: false, message: `Sandbox path is unavailable: ${targetPath}.` };
  }

  const targetUri = vscode.Uri.file(targetPath);
  try {
    await vscode.commands.executeCommand('revealFileInOS', targetUri);
  } catch {
    await vscode.env.openExternal(targetUri);
  }

  return {
    ok: true,
    message: `Opened sandbox path ${path.basename(targetPath) || targetPath}.`,
  };
}

function validateResourceUrl(value: string): string | undefined {
  if (!value.trim()) {
    return 'Enter a URL.';
  }
  try {
    const url = new URL(value.trim());
    if (!['http:', 'https:'].includes(url.protocol)) {
      return 'Use an http or https URL.';
    }
  } catch {
    return 'Enter a valid URL.';
  }
  return undefined;
}

function inferUrlTitle(source: string): string {
  try {
    const url = new URL(source);
    const lastPathSegment = url.pathname.split('/').filter(Boolean).pop();
    return lastPathSegment || url.hostname || source;
  } catch {
    return source;
  }
}

async function uploadLocalFiles(
  context: CommandContext,
  port: number,
  workspaceId: string,
  filePaths: string[],
  collectionRoot?: string,
  onUploaded?: ResourceRecordObserver,
): Promise<ResourceUploadBatchResult> {
  const uploads: unknown[] = [];
  let failedCount = 0;
  for (const filePath of filePaths) {
    const collectionPath = collectionRoot
      ? collectionPathForFile(filePath, collectionRoot)
      : undefined;
    let upload: unknown;
    try {
      upload = await context.sidecarClient.postJson<unknown>(port, '/resource/upload', {
        session_id: context.getSessionId(),
        workspace_id: workspaceId,
        kind: detectResourceKind(filePath),
        name: path.basename(filePath),
        source: filePath,
        tags: [],
        ...(collectionPath
          ? {
              collection_path: collectionPath,
              collection_root: collectionRoot,
            }
          : {}),
      });
    } catch {
      failedCount += 1;
      continue;
    }
    uploads.push(upload);
    await onUploaded?.(upload);
  }
  return { uploads, failedCount };
}

function collectionPathForFile(filePath: string, collectionRoot: string): string | undefined {
  const root = path.resolve(collectionRoot);
  const file = path.resolve(filePath);
  const relativePath = path.relative(root, file);
  if (
    !relativePath ||
    relativePath === '.' ||
    relativePath === '..' ||
    relativePath.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relativePath)
  ) {
    return undefined;
  }

  const rootName = path.basename(root).trim();
  const relativeSegments = relativePath
    .split(/[\\/]+/)
    .map((segment) => segment.trim())
    .filter((segment) => segment && segment !== '.' && segment !== '..');
  if (!rootName || relativeSegments.length === 0) {
    return undefined;
  }

  return [rootName, ...relativeSegments].join('/');
}

async function uploadInlineResources(
  context: CommandContext,
  port: number,
  workspaceId: string,
  resources: InlineResourceUpload[],
  onUploaded?: ResourceRecordObserver,
): Promise<ResourceUploadBatchResult> {
  const uploads: unknown[] = [];
  let failedCount = 0;
  for (const resource of resources) {
    let upload: unknown;
    try {
      upload = await context.sidecarClient.postJson<unknown>(port, '/resource/upload', {
        session_id: context.getSessionId(),
        workspace_id: workspaceId,
        kind: resource.kind,
        name: resource.name,
        source: resource.source,
        content: resource.content,
        content_encoding: resource.contentEncoding,
        tags: resource.tags,
        source_type: resource.sourceType,
        source_items: resource.sourceItems,
      });
    } catch {
      failedCount += 1;
      continue;
    }
    uploads.push(upload);
    await onUploaded?.(upload);
  }
  return { uploads, failedCount };
}

async function indexUploadedResources(
  context: CommandContext,
  port: number,
  workspaceId: string,
  uploads: unknown[],
  onIndexed?: ResourceRecordObserver,
): Promise<ResourceIndexBatchResult> {
  const indexed: unknown[] = [];
  let failedCount = 0;
  for (const upload of uploads) {
    const resourceId =
      upload && typeof upload === 'object' && 'id' in upload
        ? (upload as { id?: unknown }).id
        : undefined;
    if (typeof resourceId !== 'string' || !resourceId) {
      failedCount += 1;
      continue;
    }
    let response: unknown;
    try {
      response = await context.sidecarClient.postJson<unknown>(port, '/resource/index', {
        session_id: context.getSessionId(),
        workspace_id: workspaceId,
        resource_id: resourceId,
        enable_network: isUrlResourceUpload(upload),
      });
    } catch {
      failedCount += 1;
      continue;
    }
    indexed.push(response);
    await onIndexed?.(response);
  }
  return { indexed, failedCount };
}

function isUrlResourceUpload(upload: unknown): boolean {
  return (
    upload !== null &&
    typeof upload === 'object' &&
    'kind' in upload &&
    (upload as { kind?: unknown }).kind === 'url'
  );
}

async function collectImportableFiles(
  folderPath: string,
  limit: number,
): Promise<{ files: string[]; truncated: boolean; skippedUnsupported: number }> {
  const collected: string[] = [];
  const pending: string[] = [folderPath];
  let truncated = false;
  let skippedUnsupported = 0;

  while (pending.length > 0 && collected.length < limit) {
    const currentPath = pending.shift();
    if (!currentPath) {
      continue;
    }

    const entries = await fs.readdir(currentPath, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));

    for (const entry of entries) {
      if (entry.name.startsWith('.')) {
        continue;
      }

      const absolutePath = path.join(currentPath, entry.name);
      if (entry.isDirectory()) {
        if (shouldSkipDirectory(entry.name)) {
          continue;
        }
        pending.push(absolutePath);
        continue;
      }

      if (!entry.isFile()) {
        continue;
      }

      if (!isSupportedResourceFile(absolutePath)) {
        skippedUnsupported += 1;
        continue;
      }

      collected.push(absolutePath);
      if (collected.length >= limit) {
        truncated = true;
        break;
      }
    }
  }

  return { files: collected, truncated, skippedUnsupported };
}

function buildResourceImportMessage(input: {
  uploadsCount: number;
  indexedCount: number;
  failedUploads: number;
  failedIndexes: number;
  summaryRefreshed: boolean;
  truncated: boolean;
  skippedUnsupported: number;
  sourceMode: 'files' | 'folder' | 'url';
  language?: string;
}): string {
  const {
    uploadsCount,
    indexedCount,
    failedUploads,
    failedIndexes,
    summaryRefreshed,
    truncated,
    skippedUnsupported,
    sourceMode,
    language,
  } = input;
  const isChinese = language === 'zh-CN';
  if (uploadsCount === 0) {
    const failedSummary = isChinese
      ? failedUploads > 0
        ? `有 ${failedUploads} 个文件没能添加。请稍后再试。`
        : '没有添加任何资料。'
      : failedUploads > 0
        ? `${formatFileCount(failedUploads)} could not be added. Try again.`
        : 'No resources were added.';
    const skippedSummary =
      skippedUnsupported > 0
        ? isChinese
          ? ` 已跳过 ${skippedUnsupported} 个 Trainer 暂不支持的文件。`
          : ` Skipped ${formatFileCount(skippedUnsupported)} that Trainer cannot use.`
        : '';
    return `${failedSummary}${skippedSummary}`.trim();
  }
  const importedSummary = isChinese
    ? truncated
      ? sourceMode === 'folder'
        ? `已导入文件夹中的前 ${uploadsCount} 个可用文件`
        : `已导入前 ${uploadsCount} 个可用文件`
      : `已导入 ${uploadsCount} 项资料`
    : truncated
      ? sourceMode === 'folder'
        ? `Imported the first ${uploadsCount} supported file(s) from that folder`
        : `Imported the first ${uploadsCount} supported file(s)`
      : `Imported ${uploadsCount} resource(s)`;
  const indexedSummary = indexedCount > 0
    ? isChinese
      ? `，已完成 ${indexedCount} 项索引`
      : ` and indexed ${indexedCount}`
    : '';
  const skippedSummary =
    skippedUnsupported > 0
      ? isChinese
        ? ` 已跳过 ${skippedUnsupported} 个不支持的文件。`
        : ` Skipped ${skippedUnsupported} unsupported file(s).`
      : '';
  const failedUploadSummary =
    failedUploads > 0
      ? isChinese
        ? ` 另有 ${failedUploads} 个文件没能添加。你可以先使用已导入的资料，稍后再试。`
        : ` ${formatFileCount(failedUploads)} could not be added. You can use the imported resource${uploadsCount === 1 ? '' : 's'} now and try the other file${failedUploads === 1 ? '' : 's'} again.`
      : '';
  const failedIndexSummary =
    failedIndexes > 0
      ? isChinese
        ? ` 另有 ${failedIndexes} 项资料还没完成索引。可在“资料”页刷新后重试。`
        : ` ${formatResourceCount(failedIndexes)} still need${failedIndexes === 1 ? 's' : ''} indexing. Refresh Resources to try again.`
      : '';
  const summaryRefreshNotice = summaryRefreshed
    ? ''
    : isChinese
      ? ' 资料列表暂时没能刷新。重新打开“资料”页查看最新结果。'
      : ' The library summary could not be refreshed. Reopen Resources to check the latest state.';
  return `${importedSummary}${indexedSummary}${isChinese ? '。' : '.'}${skippedSummary}${failedUploadSummary}${failedIndexSummary}${summaryRefreshNotice}`.trim();
}

function buildResourceIndexMessage(input: {
  indexedCount: number;
  failedCount: number;
  summaryRefreshed: boolean;
  language?: string;
}): string {
  const { indexedCount, failedCount, summaryRefreshed, language } = input;
  const isChinese = language === 'zh-CN';
  if (indexedCount === 0 && failedCount === 0) {
    return isChinese ? '所有资料都已经是最新状态。' : 'All resources are already up to date.';
  }

  const indexedSummary = isChinese
    ? `已完成 ${indexedCount} 项资料的索引。`
    : `Indexed ${formatResourceCount(indexedCount)}.`;
  const failedSummary = failedCount > 0
    ? isChinese
      ? ` 另有 ${failedCount} 项暂时没有完成。已完成的资料可以继续使用；刷新资料会重试其余项目。`
      : ` ${formatResourceCount(failedCount)} did not finish. The indexed resources are still available; refresh Resources to retry the rest.`
    : '';
  const summaryRefreshNotice = summaryRefreshed
    ? ''
    : isChinese
      ? ' 资料库摘要暂时没有刷新；重新打开“资料”页即可确认最新状态。'
      : ' The library summary did not refresh. Reopen Resources to confirm the latest state.';
  return `${indexedSummary}${failedSummary}${summaryRefreshNotice}`.trim();
}

function formatFileCount(count: number): string {
  return `${count} file${count === 1 ? '' : 's'}`;
}

function shouldSkipDirectory(name: string): boolean {
  return [
    'node_modules',
    'dist',
    'build',
    '.git',
    '.next',
    '.nuxt',
    '.turbo',
    'coverage',
    '.venv',
    'venv',
    '__pycache__',
  ].includes(name);
}

function isSupportedResourceFile(filePath: string): boolean {
  return SUPPORTED_RESOURCE_EXTENSIONS.has(path.extname(filePath).toLowerCase());
}

function detectResourceKind(filePath: string): ResourceUploadKind {
  const extension = path.extname(filePath).toLowerCase();
  if (extension === '.pdf') {
    return 'pdf';
  }
  if (['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'].includes(extension)) {
    return 'image';
  }
  if (['.md', '.markdown'].includes(extension)) {
    return 'markdown';
  }
  if (
    ['.py', '.ts', '.tsx', '.js', '.jsx', '.json', '.yaml', '.yml', '.toml', '.ipynb'].includes(
      extension,
    )
  ) {
    return 'code';
  }
  if (['.txt', '.rst'].includes(extension)) {
    return 'text';
  }
  return 'text';
}

function parseInlineResourceUploads(payload: unknown): {
  uploads: InlineResourceUpload[];
  error?: string;
} {
  if (!payload || typeof payload !== 'object' || !('uploads' in payload)) {
    return { uploads: [] };
  }

  const rawUploads = (payload as { uploads?: unknown }).uploads;
  if (!Array.isArray(rawUploads) || rawUploads.length === 0) {
    return { uploads: [], error: 'No inline resources were provided.' };
  }

  const uploads: InlineResourceUpload[] = [];
  for (let index = 0; index < rawUploads.length; index += 1) {
    const parsed = parseInlineResourceUpload(rawUploads[index], index);
    if (typeof parsed === 'string') {
      return { uploads: [], error: parsed };
    }
    uploads.push(parsed);
  }

  return { uploads };
}

function parseInlineResourceUpload(
  value: unknown,
  index: number,
): InlineResourceUpload | string {
  if (!value || typeof value !== 'object') {
    return `Inline resource ${index + 1} must be an object.`;
  }

  const record = value as {
    kind?: unknown;
    name?: unknown;
    source?: unknown;
    content?: unknown;
    contentEncoding?: unknown;
    tags?: unknown;
    sourceType?: unknown;
    sourceItems?: unknown;
  };
  const name = typeof record.name === 'string' ? record.name.trim() : '';
  if (!name) {
    return `Inline resource ${index + 1} is missing a name.`;
  }
  const source = typeof record.source === 'string' ? record.source.trim() : '';
  if (!source) {
    return `Inline resource ${index + 1} is missing a source.`;
  }

  const sourceType =
    record.sourceType === 'file' || record.sourceType === 'folder' || record.sourceType === 'url'
      ? record.sourceType
      : /^https?:\/\//i.test(source)
      ? 'url'
      : 'file';
  const inferredKind = sourceType === 'url' ? 'url' : detectResourceKind(name || source);
  const kind =
    typeof record.kind === 'string' && RESOURCE_UPLOAD_KINDS.has(record.kind as ResourceUploadKind)
      ? (record.kind as ResourceUploadKind)
      : inferredKind;

  if (kind === 'url') {
    const validationError = validateResourceUrl(source);
    if (validationError) {
      return `Inline resource ${index + 1} has an invalid URL source: ${validationError}`;
    }
  }

  const tags = Array.isArray(record.tags)
    ? record.tags.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    : [];
  const sourceItems = Array.isArray(record.sourceItems)
    ? record.sourceItems.filter(
        (item): item is string => typeof item === 'string' && item.trim().length > 0,
      )
    : [];

  return {
    kind,
    name,
    source,
    content: typeof record.content === 'string' ? record.content : undefined,
    contentEncoding:
      record.contentEncoding === 'utf-8' || record.contentEncoding === 'base64'
        ? record.contentEncoding
        : undefined,
    tags,
    sourceType,
    sourceItems,
  };
}

function resolveInlineUploadMode(
  uploads: InlineResourceUpload[],
  directMode: ResourceSourceMode | undefined,
): ResourceSourceMode {
  if (directMode) {
    return directMode;
  }
  if (uploads.every((upload) => upload.sourceType === 'url' || upload.kind === 'url')) {
    return 'url';
  }
  if (uploads.some((upload) => upload.sourceType === 'folder')) {
    return 'folder';
  }
  return 'files';
}

function appendOptionalSearchField(
  target: Record<string, unknown>,
  key: string,
  value: unknown,
): void {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (trimmed) {
      target[key] = trimmed;
    }
    return;
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    target[key] = value;
    return;
  }
  if (typeof value === 'boolean') {
    target[key] = value;
  }
}

function normalizeResourceSearchRequestId(request: Record<string, unknown>): string | undefined {
  const candidates = [request.requestId, request.__trainerResourceOperationId];
  for (const candidate of candidates) {
    const requestId = typeof candidate === 'string' ? candidate.trim() : '';
    if (RESOURCE_SEARCH_REQUEST_ID_PATTERN.test(requestId)) {
      return requestId;
    }
  }
  return undefined;
}

function normalizeResourceSearchResult(
  value: unknown,
  fallbackQuery: string,
  requestId?: string,
): BootstrapData['resourceSearch'] {
  const record = asRecord(value);
  const rawHits = Array.isArray(record?.hits)
    ? record.hits
    : Array.isArray(record?.results)
      ? record.results
      : [];
  const hits = rawHits
    .map((item) => normalizeResourceDetailRecord(item))
    .filter((item): item is ResourceDetailRecordView => item !== undefined);
  return {
    ...(requestId ? { requestId } : {}),
    workspaceId:
      asString(record?.workspace_id) ??
      asString(record?.workspaceId) ??
      undefined,
    query: asString(record?.query) ?? fallbackQuery,
    total: asNumber(record?.total) ?? hits.length,
    rankingStrategy: 'lexical_first',
    filters: normalizeStringRecord(record?.filters),
    hits,
  };
}

function normalizeResourceDetailRecord(value: unknown): ResourceDetailRecordView | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }

  const id = asString(record.id) ?? asString(record.resource_id) ?? asString(record.resourceId);
  const title =
    asString(record.title) ??
    asString(record.name) ??
    asString(record.resource_title) ??
    asString(record.resourceTitle);
  if (!id || !title) {
    return undefined;
  }

  return {
    id,
    title,
    kind: normalizeResourceKind(
      asString(record.kind) ?? asString(record.preview_kind) ?? asString(record.previewKind),
    ),
    status: normalizeResourceStatus(
      asString(record.status) ??
        asString(record.parse_status) ??
        asString(record.parseStatus) ??
        asString(record.index_status) ??
        asString(record.indexStatus),
    ),
    summary:
      asString(record.summary) ??
      asString(record.match_summary) ??
      asString(record.matchSummary) ??
      '',
    source: asString(record.source) ?? asString(record.path),
    collectionPath: asString(record.collection_path) ?? asString(record.collectionPath),
    collectionRoot: asString(record.collection_root) ?? asString(record.collectionRoot),
    canonicalSource: asString(record.canonical_source) ?? asString(record.canonicalSource),
    sourceType: asString(record.source_type) ?? asString(record.sourceType),
    fileType: asString(record.file_type) ?? asString(record.fileType),
    projectScope: asString(record.project_scope) ?? asString(record.projectScope),
    trustState: asString(record.trust_state) ?? asString(record.trustState),
    trustScore: asNumber(record.trust_score) ?? asNumber(record.trustScore),
    freshness: normalizeFreshness(asString(record.freshness)),
    indexState: asString(record.index_state) ?? asString(record.indexState),
    citationId: asString(record.citation_id) ?? asString(record.citationId),
    previewTier:
      normalizePreviewTier(asString(record.preview_tier) ?? asString(record.previewTier)) ?? undefined,
    previewKind: asString(record.preview_kind) ?? asString(record.previewKind),
    rankScore: asNumber(record.rank_score) ?? asNumber(record.rankScore),
    rankReasons: asStringArray(record.rank_reasons ?? record.rankReasons),
    matchSummary: asString(record.match_summary) ?? asString(record.matchSummary),
    canInjectTrainingCard:
      asBoolean(record.can_inject_training_card) ?? asBoolean(record.canInjectTrainingCard),
    qualityFlags: asStringArray(record.quality_flags ?? record.qualityFlags),
    sandboxPath: asString(record.sandbox_path) ?? asString(record.sandboxPath),
    sandboxOrigin: asString(record.sandbox_origin) ?? asString(record.sandboxOrigin),
    sandboxSyncedAt: asString(record.sandbox_synced_at) ?? asString(record.sandboxSyncedAt),
    sandboxDirty: asBoolean(record.sandbox_dirty) ?? asBoolean(record.sandboxDirty),
    extractedArtifactPath:
      asString(record.extracted_artifact_path) ?? asString(record.extractedArtifactPath),
    updatedAt: asString(record.updated_at) ?? asString(record.updatedAt),
    sourceItems: asStringArray(record.source_items ?? record.sourceItems),
    tags: asStringArray(record.tags),
    warnings: asStringArray(record.warnings),
  };
}

function normalizeSandboxPreview(value: unknown): Record<string, unknown> & { path: string } {
  const record = asRecord(value) ?? {};
  const structuredData = asRecord(record.structured_data) ?? asRecord(record.structuredData);
  const metadata = asRecord(record.metadata);
  const pathValue = asString(record.path) ?? '';
  const previewTier = asString(record.preview_tier) ?? asString(record.previewTier);
  const previewKind = asString(record.preview_kind) ?? asString(record.previewKind);
  const renderedFrom = asString(record.rendered_from) ?? asString(record.renderedFrom);
  const assetUri = asString(record.asset_uri) ?? asString(record.assetUri);

  return {
    path: pathValue,
    relativePath: asString(record.relative_path) ?? asString(record.relativePath),
    relative_path: asString(record.relative_path) ?? asString(record.relativePath),
    title: asString(record.title),
    fileKind: asString(record.file_kind) ?? asString(record.fileKind),
    file_kind: asString(record.file_kind) ?? asString(record.fileKind),
    previewTier,
    preview_tier: previewTier,
    previewKind,
    preview_kind: previewKind,
    languageHint: asString(record.language_hint) ?? asString(record.languageHint),
    language_hint: asString(record.language_hint) ?? asString(record.languageHint),
    renderedFrom,
    rendered_from: renderedFrom,
    content: asString(record.content),
    excerpt: asString(record.excerpt),
    html: asString(record.html),
    isBinary: asBoolean(record.is_binary) ?? asBoolean(record.isBinary),
    is_binary: asBoolean(record.is_binary) ?? asBoolean(record.isBinary),
    isEditable: asBoolean(record.is_editable) ?? asBoolean(record.isEditable),
    is_editable: asBoolean(record.is_editable) ?? asBoolean(record.isEditable),
    canNativeOpen: asBoolean(record.can_native_open) ?? asBoolean(record.canNativeOpen),
    can_native_open: asBoolean(record.can_native_open) ?? asBoolean(record.canNativeOpen),
    structuredData,
    structured_data: structuredData,
    metadata,
    assetUri,
    asset_uri: assetUri,
  };
}

function normalizeSandboxState(value: unknown): Record<string, unknown> {
  const record = asRecord(value) ?? {};
  const selectedPath = asString(record.selectedPath) ?? asString(record.selected_path) ?? undefined;
  const preview = extractSandboxStatePreview(value);
  return {
    ...record,
    rootPath: asString(record.rootPath) ?? asString(record.root_path) ?? asString(record.rootPath),
    sandboxRootPath:
      asString(record.sandboxRootPath) ?? asString(record.sandbox_root_path) ?? undefined,
    workspaceRootPath:
      asString(record.workspaceRootPath) ?? asString(record.workspace_root_path) ?? undefined,
    activeWorkspaceRoot:
      asString(record.activeWorkspaceRoot) ?? asString(record.active_workspace_root) ?? undefined,
    trashRootPath: asString(record.trashRootPath) ?? asString(record.trash_root_path) ?? undefined,
    managedRoots:
      asStringArray(record.managedRoots ?? record.managed_roots) ?? undefined,
    selectedPath,
    selected_path: selectedPath,
    preview,
    authority: asRecord(record.authority) ?? undefined,
    capabilitySummary:
      asRecord(record.capabilitySummary) ?? asRecord(record.capability_summary) ?? undefined,
  };
}

function buildSandboxStateRequestPath(
  context: CommandContext,
  selection: {
    selectedPath?: string;
    previewPath?: string;
  },
): string {
  const params = new URLSearchParams();
  params.set('workspace_id', getRuntimeWorkspaceId(context));
  const sessionId = context.getSessionId();
  if (sessionId) {
    params.set('session_id', sessionId);
  }
  if (selection.selectedPath) {
    params.set('selected_path', selection.selectedPath);
  }
  if (selection.previewPath) {
    params.set('preview_path', selection.previewPath);
  }
  // Host-attested VS Code trust + remote identity so capability summary is not stuck unknown.
  const workspace = context.getHostState().workspace;
  params.set('workspace_trusted', workspace.trusted ? 'true' : 'false');
  params.set('remote_name', workspace.remoteName ?? '');
  return `/sandbox/state?${params.toString()}`;
}

function resolveSandboxRefreshSelection(current: BootstrapData): {
  selectedPath?: string;
  previewPath?: string;
} {
  const currentSandboxState = asRecord(current.memory.sandboxState);
  const previewPath = current.memory.sandboxPreview?.path;
  const selectedPath =
    asString(currentSandboxState?.selectedPath) ??
    asString(currentSandboxState?.selected_path) ??
    previewPath ??
    current.memory.selectedResourceDetail?.sandboxPath ??
    current.memory.selectedResourceDetail?.source;
  return {
    selectedPath,
    previewPath,
  };
}

function extractSandboxStatePreview(
  value: unknown,
): BootstrapData['memory']['sandboxPreview'] {
  const previewRecord = asRecord(asRecord(value)?.preview);
  return previewRecord ? normalizeSandboxPreview(previewRecord) : undefined;
}

function extractSandboxSelectedPath(value: unknown): string | undefined {
  return asString(asRecord(value)?.selected_path) ?? asString(asRecord(value)?.selectedPath);
}

function resolveSandboxRefreshSelectedResourceDetail(
  resources: ResourceRecordView[],
  currentSelected: ResourceDetailRecordView | undefined,
  previewPath: string | undefined,
  requestedSelectedPath: string | undefined,
  responseSelectedPath: string | undefined,
): ResourceDetailRecordView | undefined {
  const candidatePaths = [previewPath, responseSelectedPath, requestedSelectedPath].filter(
    (value): value is string => Boolean(value),
  );
  if (candidatePaths.length === 0) {
    return currentSelected;
  }
  const normalizedCurrent = currentSelected ? normalizeResourceDetailRecord(currentSelected) : undefined;
  if (
    normalizedCurrent &&
    candidatePaths.some(
      (candidate) =>
        normalizedCurrent.sandboxPath === candidate || normalizedCurrent.source === candidate,
    )
  ) {
    return normalizedCurrent;
  }
  for (const candidatePath of candidatePaths) {
    const matched = findResourceDetailByPreviewPath(resources, candidatePath);
    if (matched) {
      return matched;
    }
  }
  return undefined;
}

async function refreshSandboxSelectionFromPreview(
  context: CommandContext,
  port: number,
  current: BootstrapData,
  previewResponse: unknown,
  requestedSelectedPath: string | undefined,
): Promise<Record<string, unknown>> {
  const preview = normalizeSandboxPreview(previewResponse);
  const stateResponse = await context.sidecarClient.getJson<unknown>(
    port,
    buildSandboxStateRequestPath(context, {
      selectedPath: preview.path,
      previewPath: preview.path,
    }),
  );
  const sandboxState = normalizeSandboxState(stateResponse);
  const sandboxPreview = extractSandboxStatePreview(stateResponse) ?? preview;
  const selectedResourceDetail = resolveSandboxRefreshSelectedResourceDetail(
    current.resources,
    current.memory.selectedResourceDetail,
    sandboxPreview?.path,
    requestedSelectedPath,
    extractSandboxSelectedPath(stateResponse),
  );
  const memoryPatch = attachPreviewAssetUris(
    {
      memory: {
        ...(current.memory ?? {}),
        sandboxState,
        sandboxPreview,
        selectedResourceDetail,
      },
    } as Partial<BootstrapData>,
    (filePath) => normalizeWorkbenchAssetUri(context.workbench.resolveWebviewUriForPath?.(filePath)),
  );
  await context.patchWorkbenchData(memoryPatch);
  return sandboxState;
}

async function loadDeletedResources(
  context: CommandContext,
  port: number,
): Promise<NonNullable<BootstrapData['deletedResources']>> {
  const response = await context.sidecarClient.getJson<unknown>(
    port,
    withWorkspaceQuery('/resource/trash', context),
  );
  return normalizeDeletedResources(response, getRuntimeWorkspaceId(context));
}

function normalizeDeletedResources(
  value: unknown,
  expectedWorkspaceId: string,
): NonNullable<BootstrapData['deletedResources']> {
  const record = asRecord(value);
  if (!record || Array.isArray(value)) {
    throw new Error('Resource Trash response must be an object.');
  }
  const workspaceId = asString(record.workspace_id) ?? asString(record.workspaceId);
  if (!workspaceId || workspaceId !== expectedWorkspaceId) {
    throw new Error('Resource Trash response workspace did not match the active workspace.');
  }
  const items = Array.isArray(record.items) ? record.items : undefined;
  if (!items) {
    throw new Error('Resource Trash response did not include items.');
  }

  const seenIds = new Set<string>();
  const deletedResources: NonNullable<BootstrapData['deletedResources']> = [];
  for (const item of items) {
    const deletedResource = normalizeDeletedResource(item);
    if (!deletedResource) {
      throw new Error('Resource Trash response included an invalid item.');
    }
    if (seenIds.has(deletedResource.resourceId)) {
      throw new Error('Resource Trash response included duplicate resource IDs.');
    }
    seenIds.add(deletedResource.resourceId);
    deletedResources.push(deletedResource);
  }
  return deletedResources;
}

function normalizeDeletedResource(
  value: unknown,
): NonNullable<BootstrapData['deletedResources']>[number] | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }

  const resourceId = (
    asString(record.resource_id) ??
    asString(record.resourceId)
  )?.trim();
  const title = (
    asString(record.title) ??
    asString(record.resource_title) ??
    asString(record.resourceTitle) ??
    asString(record.name)
  )?.trim();
  if (!resourceId || !title) {
    return undefined;
  }

  return {
    resourceId,
    title,
    deletedAt: asString(record.deleted_at) ?? asString(record.deletedAt),
    collectionPath: asString(record.collection_path) ?? asString(record.collectionPath),
    recoverable: asBoolean(record.recoverable) ?? false,
  };
}

function extractResourceDeletionRequest(payload: unknown): ResourceDeletionRequest {
  const record = asRecord(payload);
  const batchPayload = record?.resourceIds;
  const isBatch = Array.isArray(batchPayload);
  const batchResourceIds = isBatch ? uniqueResourceIds(batchPayload) : [];
  const singleResourceId = normalizeResourceId(record?.resourceId);

  return {
    resourceIds: batchResourceIds.length > 0 ? batchResourceIds : singleResourceId ? [singleResourceId] : [],
    isBatch,
  };
}

function uniqueResourceIds(values: unknown[]): string[] {
  const resourceIds: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const resourceId = normalizeResourceId(value);
    if (resourceId && !seen.has(resourceId)) {
      seen.add(resourceId);
      resourceIds.push(resourceId);
    }
  }
  return resourceIds;
}

function normalizeResourceId(value: unknown): string | undefined {
  const resourceId = asString(value)?.trim();
  return resourceId || undefined;
}

function wasResourceDeletionConfirmed(value: unknown): boolean {
  return asBoolean(asRecord(value)?.removed) === true;
}

function wasResourceRestorationConfirmed(value: unknown): boolean {
  return asBoolean(asRecord(value)?.restored) === true;
}

function buildResourceDeletionBatchResult(
  requestedResourceIds: string[],
  deletedResourceIds: string[],
  failures: ResourceDeletionFailure[],
  summaryRefreshed: boolean,
): ResourceDeletionBatchResult {
  return {
    requestedResourceIds,
    deletedResourceIds,
    failedResourceIds: failures.map((failure) => failure.resourceId),
    failures,
    summaryRefreshed,
  };
}

function buildResourceDeletionResultMessage(
  request: ResourceDeletionRequest,
  responses: unknown[],
  result: ResourceDeletionBatchResult,
  trashSnapshotConfirmed: boolean,
): string {
  if (
    !request.isBatch &&
    result.deletedResourceIds.length === 1 &&
    result.failures.length === 0 &&
    result.summaryRefreshed &&
    trashSnapshotConfirmed
  ) {
    return buildDeleteResourceMessage(responses[0]);
  }

  const parts: string[] = [];
  if (result.deletedResourceIds.length > 0) {
    parts.push(`Deleted ${formatResourceCount(result.deletedResourceIds.length)}.`);
  } else {
    parts.push('No resources were deleted.');
  }
  if (result.failures.length > 0) {
    parts.push(`${formatResourceCount(result.failures.length)} could not be deleted.`);
  }
  if (!result.summaryRefreshed && result.deletedResourceIds.length > 0) {
    parts.push('The workspace summary could not be refreshed.');
  }
  if (!trashSnapshotConfirmed && result.deletedResourceIds.length > 0) {
    parts.push('The Trash state could not be confirmed. Reopen Resources to verify the current state.');
  }
  return parts.join(' ');
}

function buildResourceRestorationBatchResult(
  requestedResourceIds: string[],
  restoredResourceIds: string[],
  failures: ResourceRestorationFailure[],
  summaryRefreshed: boolean,
): ResourceRestorationBatchResult {
  return {
    requestedResourceIds,
    restoredResourceIds,
    failedResourceIds: failures.map((failure) => failure.resourceId),
    failures,
    summaryRefreshed,
  };
}

function buildResourceRestorationResultMessage(
  result: ResourceRestorationBatchResult,
  trashSnapshotConfirmed: boolean,
): string {
  const parts: string[] = [];
  if (result.restoredResourceIds.length > 0) {
    parts.push(`Restored ${formatResourceCount(result.restoredResourceIds.length)}. Re-index before reuse.`);
  } else {
    parts.push('No resources were restored.');
  }
  if (result.failures.length > 0) {
    parts.push(`${formatResourceCount(result.failures.length)} could not be restored.`);
  }
  if (!result.summaryRefreshed && result.restoredResourceIds.length > 0) {
    parts.push('The workspace summary could not be refreshed.');
  }
  if (!trashSnapshotConfirmed && result.restoredResourceIds.length > 0) {
    parts.push('The Trash state could not be confirmed. Reopen Resources to verify the current state.');
  }
  return parts.join(' ');
}

function formatResourceCount(count: number): string {
  return `${count} resource${count === 1 ? '' : 's'}`;
}

function buildDeleteResourceMessage(value: unknown): string {
  const record = asRecord(value) ?? {};
  const detail = asString(record.detail) ?? 'Resource deleted.';
  const checkpointId = asString(record.checkpoint_id) ?? asString(record.checkpointId);
  const ledgerEntryId = asString(record.ledger_entry_id) ?? asString(record.ledgerEntryId);
  const patchSteps = Array.isArray(record.patch) ? record.patch.length : 0;
  const parts = [detail];
  if (checkpointId) {
    parts.push(`Checkpoint ${checkpointId}.`);
  }
  if (ledgerEntryId) {
    parts.push(`Ledger ${ledgerEntryId}.`);
  }
  if (patchSteps > 0) {
    parts.push(`${patchSteps} patch step${patchSteps === 1 ? '' : 's'}.`);
  }
  return parts.join(' ');
}

async function applyManagedDataFolderChange(
  context: CommandContext,
  change: ManagedDataFolderChangeResult,
): Promise<CommandExecutionResult> {
  if (!change.changed) {
    return {
      ok: true,
      message:
        change.next.source === 'custom'
          ? 'Trainer is already using this managed data folder.'
          : 'Trainer is already using the recommended managed data folder.',
      data: change.next,
    };
  }

  await context.setSessionId(undefined);
  const status = await context.sidecarManager.restart();
  if (status.lifecycle === 'ready') {
    await rehydrateWorkbenchRuntime(context, {
      ensureSidecar: false,
      syncWorkbench: true,
    });
  }

  return {
    ok: status.lifecycle === 'ready',
    message: buildManagedDataFolderChangeMessage(change, status),
    data: {
      sidecar: status,
      migration: change.migration,
      resourceSandbox: change.next,
    },
  };
}

async function applySandboxRootChange(
  context: CommandContext,
  options: {
    rootPath?: string;
    clear?: boolean;
  },
): Promise<CommandExecutionResult> {
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }
  const port = status.port;
  const current = context.getHostState().bootstrap;
  const workspace = context.getHostState().workspace;
  const response = await context.sidecarClient.postJson<unknown>(port, '/sandbox/root', {
    session_id: context.getSessionId(),
    workspace_id: getRuntimeWorkspaceId(context),
    root_path: options.rootPath,
    clear: Boolean(options.clear),
    // Host-attested VS Code trust + remote identity (never JSON-omit undefined).
    remote_name: workspace.remoteName ?? '',
    workspace_trusted: Boolean(workspace.trusted),
  });
  const sandboxState = normalizeSandboxState(response);
  const sandboxPreview = extractSandboxStatePreview(response);
  const summary = await context.sidecarClient.getJson<unknown>(
    port,
    withWorkspaceQuery('/memory/summary', context),
  );
  const summaryPatch = mergeMemorySummarySnapshot(
    current,
    summary,
    getRuntimeWorkspaceId(context),
  );
  const nextMemory = {
    ...(summaryPatch.memory ?? current.memory),
    sandboxState,
    sandboxPreview,
  };
  const memoryPatch = attachPreviewAssetUris(
    {
      ...summaryPatch,
      memory: nextMemory,
    } as Partial<BootstrapData>,
    (filePath) => normalizeWorkbenchAssetUri(context.workbench.resolveWebviewUriForPath?.(filePath)),
  );
  await context.patchWorkbenchData(memoryPatch);

  const nextRoot =
    asString(sandboxState['sandboxRootPath']) ??
    asString(sandboxState['rootPath']) ??
    options.rootPath;
  return {
    ok: true,
    message: options.clear
      ? 'Sandbox root reset to the default Trainer workspace.'
      : `Sandbox root fixed at ${path.basename(nextRoot ?? '') || nextRoot || 'the selected folder'}.`,
    data: sandboxState,
  };
}

function buildManagedDataFolderChangeMessage(
  change: ManagedDataFolderChangeResult,
  status: { lifecycle: string; detail?: string },
): string {
  const changeSummary =
    change.next.source === 'custom'
      ? 'Managed data folder updated.'
      : 'Trainer returned to the recommended managed data folder.';
  const migrationSummary =
    change.migration === 'copied'
      ? ' Existing sidecar data was copied because the target folder was empty.'
      : change.migration === 'skipped_nonempty_target'
        ? ' The target folder already had content, so Trainer left it untouched and did not copy old data.'
        : change.migration === 'skipped_nested_target'
          ? ' Trainer skipped auto-copy because the new folder overlaps the previous one.'
          : change.migration === 'source_missing'
            ? ' No previous sidecar data folder was available to copy.'
            : '';
  const previousFolderNote = ' The previous folder was left untouched.';
  if (status.lifecycle !== 'ready') {
    return `${changeSummary}${migrationSummary}${previousFolderNote} Sidecar restart needs attention: ${
      status.detail ?? 'Trainer backend is unavailable.'
    }`;
  }
  return `${changeSummary}${migrationSummary}${previousFolderNote} Trainer restarted the backend on the new folder.`;
}

function buildResourceSearchMessage(
  search: BootstrapData['resourceSearch'],
): string {
  if (!search) {
    return 'Found 0 ranked resources.';
  }
  const topHitSummary = search.hits[0]
    ? formatSearchHitTeachingSummary(search.hits[0], 'en')
    : undefined;
  return topHitSummary
    ? `Found ${search.total} ranked resources. ${topHitSummary}`
    : `Found ${search.total} ranked resources.`;
}

function clearDeletedResourcePreviews(
  current: BootstrapData,
  resources: ResourceRecordView[],
): BootstrapData['memory']['sandboxPreview'] {
  const preview = current.memory.sandboxPreview;
  if (!preview) {
    return undefined;
  }
  if (resources.some((resource) => preview.path === resource.sandboxPath || preview.path === resource.source)) {
    return undefined;
  }
  return preview;
}

function shouldClearSelectedResources(
  current: BootstrapData,
  resourceIds: ReadonlySet<string>,
): boolean {
  const selectedResourceId = current.memory.selectedResourceDetail?.id;
  return selectedResourceId ? resourceIds.has(selectedResourceId) : false;
}

function findResourceDetailByPreviewPath(
  resources: ResourceRecordView[],
  previewPath: string,
): ResourceDetailRecordView | undefined {
  return resources
    .map((item) => normalizeResourceDetailRecord(item))
    .find(
      (item) =>
        item !== undefined &&
        (item.sandboxPath === previewPath || item.source === previewPath),
    );
}

function normalizeStringRecord(value: unknown): Record<string, string> {
  const record = asRecord(value);
  if (!record) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(record)
      .map(([key, item]) => [key, asString(item)])
      .filter((entry): entry is [string, string] => typeof entry[1] === 'string'),
  );
}

function normalizeWorkbenchAssetUri(value: unknown): string | undefined {
  if (typeof value === 'string' && value.trim().length > 0) {
    return value;
  }
  if (value && typeof value === 'object' && 'toString' in value) {
    const rendered = value.toString();
    return typeof rendered === 'string' && rendered.trim().length > 0 ? rendered : undefined;
  }
  return undefined;
}

function normalizeResourceKind(value: string | undefined): ResourceDetailRecordView['kind'] {
  if (
    value === 'pdf' ||
    value === 'image' ||
    value === 'markdown' ||
    value === 'text' ||
    value === 'code' ||
    value === 'url'
  ) {
    return value;
  }
  if (value === 'document') {
    return 'pdf';
  }
  return 'text';
}

function normalizeResourceStatus(value: string | undefined): ResourceDetailRecordView['status'] {
  if (value === 'ready' || value === 'indexed' || value === 'parsed') {
    return 'ready';
  }
  if (value === 'indexing' || value === 'queued' || value === 'pending') {
    return 'indexing';
  }
  if (value === 'attention' || value === 'failed' || value === 'warning') {
    return 'attention';
  }
  return 'ready';
}

function normalizePreviewTier(
  value: string | undefined,
): ResourceDetailRecordView['previewTier'] | undefined {
  return value === 'rich' || value === 'converted' || value === 'metadata' ? value : undefined;
}

function normalizeFreshness(
  value: string | undefined,
): ResourceDetailRecordView['freshness'] | undefined {
  return value === 'fresh' || value === 'stale' || value === 'unknown' ? value : undefined;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim().length > 0 ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

function asStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const items = value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
  return items.length > 0 ? items : undefined;
}

/**
 * Host confirm for organize_resources: arms one-shot stamp then sends an organize turn.
 * Fail-closed when no pending proposal exists (webview cannot self-attest).
 */
export async function confirmResourceOrganizationCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const {
    armResourceOrganizationConfirm,
    markResourceOrganizationConfirmInFlight,
    sendStreamMessageCommand,
  } = await import('./sessionCommands');
  if (!armResourceOrganizationConfirm(context)) {
    return {
      ok: false,
      message: 'No resource organization proposal is waiting for confirmation.',
    };
  }
  const record =
    payload && typeof payload === 'object' && !Array.isArray(payload)
      ? (payload as Record<string, unknown>)
      : {};
  const responseLanguage =
    record.responseLanguage === 'zh-CN' ||
    record.responseLanguage === 'en-US' ||
    record.responseLanguage === 'es-ES' ||
    record.responseLanguage === 'fr-FR' ||
    record.responseLanguage === 'de-DE' ||
    record.responseLanguage === 'ja-JP' ||
    record.responseLanguage === 'ko-KR' ||
    record.responseLanguage === 'pt-BR'
      ? record.responseLanguage
      : undefined;
  const confirmText =
    responseLanguage === 'zh-CN'
      ? '请按刚才的整理方案提交变更。'
      : 'Commit the proposed resource organization.';
  markResourceOrganizationConfirmInFlight(context, true);
  try {
    return await sendStreamMessageCommand(context, {
      text: confirmText,
      stream: true,
      intent: 'coach',
      activeView: 'resources',
      resourceComposerIntent: { mode: 'organize' },
      responseLanguage,
      includeCurrentFile: false,
      includeDiagnostics: false,
      contextDetail: 'focused',
    });
  } finally {
    markResourceOrganizationConfirmInFlight(context, false);
  }
}

/** Cancel/absent confirmation — clear host + server pending; stamp must fail-closed. */
export async function cancelResourceOrganizationCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const {
    cancelResourceOrganizationConfirm,
    cancelStreamMessageCommand,
    isResourceOrganizationConfirmInFlight,
  } = await import('./sessionCommands');
  const abortConfirmTurn = isResourceOrganizationConfirmInFlight(context);
  cancelResourceOrganizationConfirm(context);
  await context.workbench.postMessage({
    type: 'resourceOrganization/pending',
    payload: { pending: false },
  });
  // Clear server pending before stream abort so an in-flight stamped organize
  // cannot consume pending after the learner cancelled.
  try {
    const status = await context.sidecarManager.ensureRunning();
    if (status.lifecycle === 'ready' && status.port) {
      await context.sidecarClient.postJson(
        status.port,
        '/resource/organization/cancel',
        {
          session_id: context.getSessionId(),
          workspace_id: getRuntimeWorkspaceId(context),
        },
        { timeoutMs: 5000 },
      );
    }
  } catch {
    // Host pending already cleared. Server clear is best-effort; stamp stays fail-closed
    // without host arm, and without server pending once cancel reaches the sidecar.
  }
  if (abortConfirmTurn) {
    try {
      await cancelStreamMessageCommand(context);
    } catch {
      // Local + server pending already cleared; stream abort is best-effort.
    }
  }
  return { ok: true };
}
