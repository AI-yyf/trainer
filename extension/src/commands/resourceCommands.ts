import * as vscode from 'vscode';
import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';

import {
  formatSearchHitTeachingSummary,
  normalizeResourceSearchMode,
  resourceSearchModeRequest,
} from '../../../shared/src/resourceSearch';
import {
  resolveResourceOpenTarget,
  resolveResourceReadCandidates,
} from '../../../shared/src/resourceOpen';
import type { ResourceVersionCheckResult } from '../../../shared/src/models';
import { mapResearchBriefAsset, resolveResearchCitationLine, upsertResearchBrief } from '../../../shared/src/researchBrief';
import type { CommandContext } from '../core/commandContext';
import { attachPreviewAssetUris } from '../core/previewAssetUris';
import type {
  BootstrapData,
  CommandExecutionResult,
  ResourceDetailRecordView,
  ResourceRecordView,
} from '../core/types';
import type { ManagedDataFolderChangeResult } from '../core/sidecarProcessManager';
import { mergeMemorySummarySnapshot, mergeResourceRecords, resetWorkbenchAfterRuntimeDataChange } from '../core/workbenchData';
import { rehydrateWorkbenchRuntime, trainerSessionBlockReason } from '../core/runtimeRehydration';
import { getRuntimeWorkspaceId, isRemoteWorkspaceSnapshot, withWorkspaceQuery } from './workspaceContext';
import { basenameFs, looksLikeWindowsAbsolutePath, normalizeFsPath } from '../core/workspaceRoots';
import { isComposerLanguage, type ComposerLanguage } from '../../../shared/src/types';
import { hostCommandCopy, resolveHostCommandLanguage } from './hostCommandCopy';
import { runtimeDataRootUnder } from './workspaceAdmissionCommands';

const MAX_RESOURCE_UPLOADS = 100;
type ResourceSourceMode = 'files' | 'folder' | 'workspace' | 'url';
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
const RESOURCE_UPLOAD_KINDS = new Set([
  'pdf',
  'epub',
  'docx',
  'pptx',
  'html',
  'image',
  'text',
  'markdown',
  'code',
  'url',
  'video',
] as const);

type ResourceUploadKind =
  | 'pdf'
  | 'epub'
  | 'docx'
  | 'pptx'
  | 'html'
  | 'image'
  | 'text'
  | 'markdown'
  | 'code'
  | 'url'
  | 'video';
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

  // These reasons are curated, localized and path-free. They carry the resource-failure
  // marker so the webview shows the actual reason: unmarked host prose is replaced there
  // by a generic recovery message ("the import did not finish; refresh to retry"), which
  // hides that the learner only has to choose how Trainer manages this project.
  const blocked = (message: string): CommandExecutionResult => ({
    ok: false,
    message: `[[trainer-resource-failure]] ${message}`,
  });
  const language = resourceResponseLanguage(context);
  if (status === 'browse') {
    return blocked(hostCommandCopy(language, 'resourceBrowseOnly'));
  }
  if (status === 'ignored') {
    return blocked(hostCommandCopy(language, 'resourceProjectIgnored'));
  }

  return blocked(
    trainerSessionBlockReason(context) ??
      hostCommandCopy(language, 'resourceChooseAdmissionFallback'),
  );
}

function resourceResponseLanguage(context: CommandContext, explicit?: unknown): ComposerLanguage {
  return resolveHostCommandLanguage(context, explicit);
}

function preservedTrashListMessage(context: CommandContext): string {
  return hostCommandCopy(resourceResponseLanguage(context), 'trashCurrentListPreserved');
}

async function typedResourcePathFallback(
  kind: 'file' | 'folder',
  language: ComposerLanguage,
): Promise<string[] | undefined> {
  // Mirrors the workspace-admission typed-path fallback: when the native
  // dialog never appears, ask for a full path instead of failing silently.
  const typed = await vscode.window.showInputBox({
    title: hostCommandCopy(language, kind === 'file' ? 'resourcePickerTitleFile' : 'resourcePickerTitleFolder'),
    prompt: hostCommandCopy(language, kind === 'file' ? 'resourcePickerPromptFile' : 'resourcePickerPromptFolder'),
    placeHolder: kind === 'file' ? '/Users/<you>/notes/lecture.pdf' : '/Users/<you>/notes',
    ignoreFocusOut: true,
  });
  const trimmed = typed?.trim();
  // A typed path is passed through even when it does not exist yet: the
  // per-file upload then reports the concrete failure instead of silence.
  return trimmed ? [trimmed] : undefined;
}

const WORKSPACE_IMPORT_COPY: Record<
  ComposerLanguage,
  {
    selectFromWorkspace: string;
    noLocalWorkspaceFolder: string;
    pickTitle: string;
    pickPlaceholder: string;
    detailFormat: (detail: string) => string;
  }
> = {
  'zh-CN': {
    selectFromWorkspace: '从当前项目选择',
    noLocalWorkspaceFolder: '当前尚未打开本地项目文件夹。',
    pickTitle: '选择当前项目文件复制到资料库',
    pickPlaceholder: '勾选需要加入 Trainer 资料库的代码或文档（不会改动原项目）',
    detailFormat: (detail) => `（${detail}）`,
  },
  'en-US': {
    selectFromWorkspace: 'Select from workspace',
    noLocalWorkspaceFolder: 'No local workspace folder is currently open.',
    pickTitle: 'Select workspace files to copy into Library',
    pickPlaceholder: 'Check project files to copy into Trainer Library (read-only on project)',
    detailFormat: (detail) => ` (${detail})`,
  },
  'es-ES': {
    selectFromWorkspace: 'Seleccionar del proyecto',
    noLocalWorkspaceFolder: 'No hay ninguna carpeta de proyecto local abierta.',
    pickTitle: 'Seleccionar archivos del proyecto para copiar a la biblioteca',
    pickPlaceholder: 'Marca los archivos a copiar en la biblioteca de Trainer (solo lectura)',
    detailFormat: (detail) => ` (${detail})`,
  },
  'fr-FR': {
    selectFromWorkspace: 'Choisir depuis le projet',
    noLocalWorkspaceFolder: 'Aucun dossier de projet local n’est actuellement ouvert.',
    pickTitle: 'Choisir les fichiers du projet à copier dans la bibliothèque',
    pickPlaceholder: 'Cochez les fichiers à copier dans Trainer (lecture seule sur le projet)',
    detailFormat: (detail) => ` (${detail})`,
  },
  'de-DE': {
    selectFromWorkspace: 'Aus aktuellem Projekt wählen',
    noLocalWorkspaceFolder: 'Derzeit ist kein lokaler Projektordner geöffnet.',
    pickTitle: 'Projektdateien zum Kopieren in die Bibliothek auswählen',
    pickPlaceholder: 'Dateien für die Trainer-Bibliothek auswählen (Projekt bleibt schreibgeschützt)',
    detailFormat: (detail) => ` (${detail})`,
  },
  'ja-JP': {
    selectFromWorkspace: '現在のプロジェクトから選択',
    noLocalWorkspaceFolder: '現在開いているローカルプロジェクトフォルダがありません。',
    pickTitle: 'ライブラリにコピーするプロジェクトファイルを選択',
    pickPlaceholder: 'Trainer ライブラリへコピーするファイルを選択（元のプロジェクトは変更されません）',
    detailFormat: (detail) => `（${detail}）`,
  },
  'ko-KR': {
    selectFromWorkspace: '현재 프로젝트에서 선택',
    noLocalWorkspaceFolder: '현재 열려 있는 로컬 프로젝트 폴더가 없습니다.',
    pickTitle: '자료실로 복사할 프로젝트 파일 선택',
    pickPlaceholder: 'Trainer 자료실에 복사할 파일을 선택하세요 (원본 프로젝트는 수정되지 않음)',
    detailFormat: (detail) => ` (${detail})`,
  },
  'pt-BR': {
    selectFromWorkspace: 'Selecionar do projeto',
    noLocalWorkspaceFolder: 'Nenhuma pasta de projeto local está aberta no momento.',
    pickTitle: 'Selecionar arquivos do projeto para copiar à biblioteca',
    pickPlaceholder: 'Marque os arquivos para copiar à biblioteca do Trainer (somente leitura)',
    detailFormat: (detail) => ` (${detail})`,
  },
};

function workspaceImportCopy(language?: ComposerLanguage) {
  return WORKSPACE_IMPORT_COPY[language ?? 'en-US'] ?? WORKSPACE_IMPORT_COPY['en-US'];
}

function normalizeRequestedTargetFolder(payload: unknown): string | undefined {
  if (!payload || typeof payload !== 'object') {
    return undefined;
  }
  const record = payload as { targetFolder?: unknown; collectionPath?: unknown };
  const raw =
    typeof record.targetFolder === 'string'
      ? record.targetFolder
      : typeof record.collectionPath === 'string'
        ? record.collectionPath
        : '';
  const segments = raw
    .trim()
    .replace(/\\/g, '/')
    .replace(/^\/+|\/+$/g, '')
    .split('/')
    .map((segment) => segment.trim())
    .filter((segment) => segment && segment !== '.' && segment !== '..');
  return segments.length > 0 ? segments.slice(0, 3).join('/') : undefined;
}

export async function uploadResourceCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('upload training resources'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredUploadResources') };
  }

  const requestedMode =
    payload && typeof payload === 'object' && 'mode' in payload
      ? (payload as { mode?: unknown }).mode
      : undefined;

  const directMode: ResourceSourceMode | undefined =
    requestedMode === 'files' ||
    requestedMode === 'folder' ||
    requestedMode === 'workspace' ||
    requestedMode === 'url'
      ? requestedMode
      : undefined;
  const inlineUploadResult = parseInlineResourceUploads(payload, lang);
  if (inlineUploadResult.error) {
    return { ok: false, message: inlineUploadResult.error };
  }
  const inlineUploads = inlineUploadResult.uploads;
  const requestedTargetFolder = normalizeRequestedTargetFolder(payload);
  let targetGroupForUploads = requestedTargetFolder;

  const sourceMode:
    | { label: string; value: ResourceSourceMode }
    | undefined = inlineUploads.length > 0
    ? {
        label: hostCommandCopy(lang, 'resourceLabelInline'),
        value: resolveInlineUploadMode(inlineUploads, directMode),
      }
    : directMode
    ? {
        label:
          directMode === 'files'
            ? hostCommandCopy(lang, 'resourceLabelLocalFiles')
            : directMode === 'folder'
              ? hostCommandCopy(lang, 'resourceLabelFolder')
              : directMode === 'workspace'
                ? workspaceImportCopy(lang).selectFromWorkspace
                : hostCommandCopy(lang, 'resourceLabelUrl'),
        value: directMode,
      }
    : await vscode.window.showQuickPick(
    [
      {
        label: hostCommandCopy(lang, 'resourceLabelLocalFiles'),
        description: hostCommandCopy(lang, 'resourceDescLocalFiles'),
        value: 'files' as const,
      },
      {
        label: hostCommandCopy(lang, 'resourceLabelFolder'),
        description: hostCommandCopy(lang, 'resourceDescFolder'),
        value: 'folder' as const,
      },
      {
        label: hostCommandCopy(lang, 'resourceLabelUrl'),
        description: hostCommandCopy(lang, 'resourceDescUrl'),
        value: 'url' as const,
      },
    ],
    {
      title: hostCommandCopy(lang, 'resourceAddMethodTitle'),
      ignoreFocusOut: true,
    },
  );

  if (!sourceMode) {
    return { ok: false, cancelled: true };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
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
  // One visible stage line that advances with the real import work. Each
  // stage is only reported when that work actually starts; failures still
  // surface through the final per-resource result.
  let importStageHandle: { dispose?: () => void } | undefined;
  let lastImportStageAt = 0;
  const showImportStage = async (text: string) => {
    // Keep each real stage visible long enough to be read; the work itself is
    // already done (or about to start), this only paces the disclosure.
    const elapsed = Date.now() - lastImportStageAt;
    if (lastImportStageAt > 0 && elapsed < 450) {
      await new Promise((resolve) => setTimeout(resolve, 450 - elapsed));
    }
    lastImportStageAt = Date.now();
    importStageHandle?.dispose?.();
    if (typeof vscode.window.setStatusBarMessage !== "function") {
      return;
    }
    importStageHandle = vscode.window.setStatusBarMessage(text, 180_000);
  };
  await showImportStage(hostCommandCopy(lang, 'importStageIdentifying'));

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
      openLabel: hostCommandCopy(lang, 'uploadToTrainerLabel'),
      filters: {
        Resources: RESOURCE_FILTER_EXTENSIONS,
        All: ['*'],
      },
    });

    // The native file dialog can be unusable in some window setups (the same
    // environment limitation the workspace-admission lane documents). Offer a
    // typed-path fallback so importing never dead-ends silently.
    const allFiles = picks?.length
      ? picks.map((uri) => uri.fsPath)
      : await typedResourcePathFallback('file', lang);
    if (!allFiles?.length) {
      return { ok: false, cancelled: true };
    }
    const supportedFiles = allFiles.filter((filePath) => isSupportedResourceFile(filePath));
    skippedUnsupported = allFiles.length - supportedFiles.length;
    if (supportedFiles.length === 0) {
      return {
        ok: false,
        message:
          skippedUnsupported > 0
            ? hostCommandCopy(lang, 'skippedUnsupportedFiles', { count: skippedUnsupported })
            : hostCommandCopy(lang, 'noResourcesSelected'),
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
      openLabel: hostCommandCopy(lang, 'importFolderToTrainerLabel'),
    });

    const folderPath = picks?.[0]?.fsPath ?? (await typedResourcePathFallback('folder', lang))?.[0];
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
            ? hostCommandCopy(lang, 'folderSkippedUnsupportedFiles', { count: skippedUnsupported })
            : hostCommandCopy(lang, 'folderNoSupportedFiles'),
      };
    }

    const uploadResult = await uploadLocalFiles(
      context,
      status.port,
      workspaceId,
      discoveredFiles,
      folderPath,
      recordUploaded,
      Boolean(requestedTargetFolder),
    );
    if (requestedTargetFolder) {
      const folderName = basenameFs(folderPath).trim();
      targetGroupForUploads = [...requestedTargetFolder.split('/'), ...(folderName ? [folderName] : [])]
        .filter((segment) => segment && segment !== '.' && segment !== '..')
        .slice(0, 3)
        .join('/');
    }
    failedUploads += uploadResult.failedCount;
  } else if (sourceMode.value === 'workspace') {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    const workspaceRoot = workspaceFolder?.uri.fsPath ?? context.getHostState().workspace.activeWorkspaceRoot;
    if (!workspaceRoot) {
      return {
        ok: false,
        message: workspaceImportCopy(lang).noLocalWorkspaceFolder,
      };
    }
    let candidatePaths: string[] = [];
    if (typeof vscode.workspace.findFiles === 'function') {
      const found = await vscode.workspace.findFiles(
        '**/*',
        '{**/node_modules/**,**/.git/**,**/dist/**,**/build/**,**/.venv/**,**/venv/**,**/__pycache__/**,**/.next/**,**/.turbo/**}',
        400,
      );
      candidatePaths = found
        .map((uri) => uri.fsPath)
        .filter((fsPath) => fsPath && isSupportedResourceFile(fsPath));
    }
    if (candidatePaths.length === 0) {
      const scanned = await collectImportableFiles(workspaceRoot, 300);
      candidatePaths = scanned.files;
    }
    const items = candidatePaths
      .map((filePath) => {
        const rel = path.relative(workspaceRoot, filePath).split(path.sep).join('/') || path.basename(filePath);
        const dir = path.posix.dirname(rel);
        return {
          label: path.posix.basename(rel),
          description: dir === '.' ? path.basename(workspaceRoot) : `${path.basename(workspaceRoot)}/${dir}`,
          detail: rel,
          filePath,
        };
      })
      .sort((a, b) => a.detail.localeCompare(b.detail));
    if (items.length === 0) {
      return {
        ok: false,
        message: hostCommandCopy(lang, 'folderNoSupportedFiles'),
      };
    }
    const picked = await vscode.window.showQuickPick(items, {
      canPickMany: true,
      matchOnDescription: true,
      matchOnDetail: true,
      ignoreFocusOut: true,
      title: workspaceImportCopy(lang).pickTitle,
      placeHolder: workspaceImportCopy(lang).pickPlaceholder,
    });
    if (!picked || picked.length === 0) {
      return { ok: false, cancelled: true };
    }
    truncated = picked.length > MAX_RESOURCE_UPLOADS;
    const selectedFiles = picked.slice(0, MAX_RESOURCE_UPLOADS).map((item) => item.filePath);
    const uploadResult = await uploadLocalFiles(
      context,
      status.port,
      workspaceId,
      selectedFiles,
      requestedTargetFolder ? undefined : workspaceRoot,
      recordUploaded,
    );
    failedUploads += uploadResult.failedCount;
  } else {
    const source = await vscode.window.showInputBox({
      title: hostCommandCopy(lang, 'resourceUrlTitle'),
      prompt: hostCommandCopy(lang, 'resourceUrlPrompt'),
      ignoreFocusOut: true,
      validateInput: (value) => validateResourceUrl(value, lang),
    });
    if (!source) {
      return { ok: false, cancelled: true };
    }

    try {
      // A web resource is captured through the same controlled pipeline as the
      // Resources URL form: HTML is read and stored as an indexed Markdown
      // snapshot, never as the raw page. The later index pass is a cheap
      // re-index of that owned Markdown file.
      const capture = await captureResourceCommand(context, {
        url: source,
        title: inferUrlTitle(source),
        kind: captureKindForUrl(source),
      });
      if (!capture.ok) {
        failedUploads += 1;
      } else if (capture.data !== undefined) {
        uploads.push(capture.data);
      }
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
        language: lang,
      }),
      data: [],
    };
  }

  const sidecarPort = status.port;
  if (targetGroupForUploads && uploads.length > 0) {
    for (let index = 0; index < uploads.length; index += 1) {
      const uploadedId = asString(asRecord(uploads[index])?.id);
      if (!uploadedId) {
        continue;
      }
      try {
        const organized = await context.sidecarClient.postJson<unknown>(sidecarPort, '/resource/organize', {
          session_id: context.getSessionId(),
          workspace_id: workspaceId,
          resource_id: uploadedId,
          action: 'set_group',
          group: targetGroupForUploads,
        });
        uploads[index] = organized;
        await patchResourceRecords([organized]);
      } catch {
        // Keep the uploaded resource even if automatic folder placement fails.
      }
    }
  }
  const uploadedResourceIds = uploads
    .map((upload) => asString(asRecord(upload)?.id))
    .filter((value): value is string => Boolean(value));
  if (uploadedResourceIds.length > 0) {
    const stageRequest = {
      session_id: context.getSessionId(),
      workspace_id: workspaceId,
      resource_ids: uploadedResourceIds,
    };
    await showImportStage(hostCommandCopy(lang, 'importStageParsingStructure'));
    try {
      await context.sidecarClient.postJson<unknown>(
        sidecarPort,
        '/resource/canonicalize/analyze',
        stageRequest,
        { timeoutMs: RESOURCE_INDEX_TIMEOUT_MS },
      );
    } catch {
      // Older sidecars without the staged endpoints still index normally.
    }
    await showImportStage(hostCommandCopy(lang, 'importStageGeneratingMarkdown'));
    let materializedItems: Record<string, unknown>[] = [];
    try {
      const materialized = await context.sidecarClient.postJson<unknown>(
        sidecarPort,
        '/resource/canonicalize/materialize',
        stageRequest,
        { timeoutMs: RESOURCE_INDEX_TIMEOUT_MS },
      );
      materializedItems = Array.isArray(asRecord(materialized)?.items)
        ? (asRecord(materialized)?.items as unknown[])
            .map((item) => asRecord(item))
            .filter((item): item is Record<string, unknown> => Boolean(item))
        : [];
    } catch {
      // Fallback: indexing builds the canonical document itself.
    }
    const imageCount = materializedItems.reduce(
      (total, item) => total + (asNumber(item.asset_count) ?? 0),
      0,
    );
    const tableCount = materializedItems.reduce(
      (total, item) => total + (asNumber(item.table_count) ?? 0),
      0,
    );
    if (imageCount > 0 || tableCount > 0) {
      await showImportStage(
        hostCommandCopy(lang, 'importStageExtractedSummary', { images: imageCount, tables: tableCount }),
      );
    }
  }
  await showImportStage(hostCommandCopy(lang, 'importStageBuildingIndex'));
  // Parsing Word/PowerPoint/PDF sources into Markdown and indexing them can
  // take tens of seconds; keep one honest visible stage instead of a silent
  // wait. The final command message still reports the real per-resource result.
  const runIndex = () =>
    indexUploadedResources(
      context,
      sidecarPort,
      workspaceId,
      uploads,
      recordIndexed,
    );
  const indexResult =
    typeof vscode.window.withProgress === 'function' &&
    vscode.ProgressLocation?.Notification !== undefined
      ? await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: hostCommandCopy(lang, 'importStageProgressTitle'),
            cancellable: false,
          },
          runIndex,
        )
      : await runIndex();
  const indexed = indexResult.indexed;
  let summaryRefreshed = true;
  await showImportStage(hostCommandCopy(lang, 'importStageRefreshingLibrary'));
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

  importStageHandle?.dispose?.();
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
      language: lang,
    }),
    data: indexed.length > 0 ? indexed : uploads,
  };
}

/** A web capture fetches, cleans and indexes a remote page: give it room. */
const RESOURCE_CAPTURE_TIMEOUT_MS = 120_000;
/** First-time parse + chunk + embed can exceed the generic 15s request budget
 *  (measured on Windows hosted runners: the server finished at ~15s but the
 *  client had already counted the index as failed). Keep a bounded but real
 *  long-operation budget; a genuinely hung sidecar still aborts. */
const RESOURCE_INDEX_TIMEOUT_MS = 120_000;

type LibraryCopyKey =
  | 'captureStartedBody'
  | 'captureInvalidUrl'
  | 'captureFetchFailed'
  | 'captureNotConfirmed'
  | 'organizeBlocked'
  | 'organizeNotFound'
  | 'organizeInvalid'
  | 'exportNotFound'
  | 'exportNoSnapshot'
  | 'exportSaveCancelled'
  | 'exportSaveFailed'
  | 'exportSucceeded'
  | 'serviceUnavailable'
  | 'migrationFailed'
  | 'migrationConfirmationRequired'
  | 'openMissingSource'
  | 'openMissingFile'
  | 'openCaptureRequired';

/**
 * Curated, path-free library copy in the workspace response language. Failure
 * copy carries the `[[trainer-resource-failure]]` marker so the webview's
 * failure sanitizer can trust and pass through the specific reason instead of
 * replacing it with the generic "try again" notice.
 */
function libraryCopy(key: LibraryCopyKey, language?: ComposerLanguage, detail?: string): string {
  const lang = language ?? 'en-US';
  const formatDetail = detail ? workspaceImportCopy(lang).detailFormat(detail) : '';
  const failure = (msg: string): string => `[[trainer-resource-failure]] ${msg}`;
  switch (key) {
    case 'captureStartedBody':
      return hostCommandCopy(lang, 'libCaptureStarted');
    case 'captureInvalidUrl':
      return failure(hostCommandCopy(lang, 'libCaptureInvalidUrl'));
    case 'captureFetchFailed':
      return failure(hostCommandCopy(lang, 'libCaptureFetchFailed', { detail: formatDetail }));
    case 'captureNotConfirmed':
      return failure(hostCommandCopy(lang, 'libCaptureNotConfirmed'));
    case 'organizeBlocked':
      return failure(hostCommandCopy(lang, 'libOrganizeBlocked'));
    case 'organizeNotFound':
      return failure(hostCommandCopy(lang, 'libOrganizeNotFound'));
    case 'organizeInvalid':
      return failure(hostCommandCopy(lang, 'libOrganizeInvalid'));
    case 'exportNotFound':
      return failure(hostCommandCopy(lang, 'libOrganizeNotFound'));
    case 'exportNoSnapshot':
      return failure(hostCommandCopy(lang, 'libExportNoSnapshot'));
    case 'exportSaveCancelled':
      return failure(hostCommandCopy(lang, 'libExportCancelled'));
    case 'exportSaveFailed':
      return failure(hostCommandCopy(lang, 'libExportFailed', { detail: formatDetail }));
    case 'exportSucceeded':
      return hostCommandCopy(lang, 'libExportSucceeded', { name: detail ?? '' });
    case 'serviceUnavailable':
      return failure(hostCommandCopy(lang, 'libServiceUnavailable'));
    case 'migrationFailed':
      return failure(hostCommandCopy(lang, 'libMigrationFailed', { detail: formatDetail }));
    case 'migrationConfirmationRequired':
      return failure(hostCommandCopy(lang, 'libMigrationConfirmationRequired'));
    case 'openMissingSource':
      return failure(hostCommandCopy(lang, 'libOpenMissingSource'));
    case 'openMissingFile':
      return failure(hostCommandCopy(lang, 'libOpenMissingFile'));
    case 'openCaptureRequired':
      return failure(hostCommandCopy(lang, 'libOpenCaptureRequired'));
  }
}

function isResourceCapturePayloadRecord(payload: unknown): Record<string, unknown> {
  return payload && typeof payload === 'object' && !Array.isArray(payload)
    ? (payload as Record<string, unknown>)
    : {};
}

/** Internal bridge: the webview's "add by URL" capture, answered synchronously. */
export async function captureResourceCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('capture a resource from a URL'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredCapture') };
  }

  const request = isResourceCapturePayloadRecord(payload);
  const workspaceId = getRuntimeWorkspaceId(context);
  const sessionId = context.getSessionId();
  const url = asString(request.url)?.trim() ?? '';
  if (!url || !/^https?:\/\//i.test(url)) {
    return { ok: false, message: libraryCopy('captureInvalidUrl', lang) };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: libraryCopy('captureFetchFailed', lang, status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable')) };
  }
  if ((request.workspace_id && request.workspace_id !== workspaceId) || workspaceId !== getRuntimeWorkspaceId(context)) {
    return { ok: false, message: hostCommandCopy(lang, 'projectChangedResubmitCapture') };
  }

  const title = asString(request.title)?.trim();
  const focusId = asString(request.bind_focus_id ?? request.bindFocusId)?.trim();
  const selection = asString(request.selection)?.trim();
  const captureMode = request.capture_mode === 'selection' || request.capture_mode === 'link'
    ? request.capture_mode : undefined;
  const planId = asString(request.bind_plan_id)?.trim();
  const planRevision = request.bind_plan_revision;
  const targetDir = asString(request.target_dir ?? request.targetDir)?.trim();
  const clientCaptureId = asString(request.client_capture_id ?? request.clientCaptureId)?.trim() ||
    `library-capture-${Date.now().toString(36)}`;
  try {
    const captured = await context.sidecarClient.postJson<unknown>(
      status.port,
      '/resources/capture',
      {
        session_id: sessionId,
        workspace_id: workspaceId || asString(request.workspace_id)?.trim() || undefined,
        url,
        kind: asString(request.kind)?.trim() || 'web',
        ...(title ? { title } : {}),
        ...(focusId ? { bind_focus_id: focusId } : {}),
        ...(planId ? { bind_plan_id: planId } : {}),
        ...(typeof planRevision === 'number' && Number.isInteger(planRevision) ? { bind_plan_revision: planRevision } : {}),
        ...(captureMode ? { capture_mode: captureMode } : {}),
        ...(selection ? { selection } : {}),
        ...(request.download === true ? { download: true } : {}),
        ...(targetDir ? { target_dir: targetDir } : {}),
        client_capture_id: clientCaptureId,
      },
      { timeoutMs: RESOURCE_CAPTURE_TIMEOUT_MS },
    );
    const record = asRecord(captured) ?? {};
    const deduped = asBoolean(record.deduped) === true;
    // The response doubles as the refreshed resource record (the sidecar
    // returns the full ResourceRecord shape plus capture extras), so one
    // patch puts it straight into the library snapshot the webview waits on.
    if (workspaceId === getRuntimeWorkspaceId(context) && sessionId === context.getSessionId()) {
      await context.patchWorkbenchData(
        mergeResourceRecords(context.getHostState().bootstrap, [captured]),
      );
    }
    if (captureMode && workspaceId === getRuntimeWorkspaceId(context) && sessionId === context.getSessionId()) {
      // Selection/link saves also update the learning ledger and can change a
      // formal plan. Keep the resource receipt valid if a follow-up read fails.
      try {
        await refreshResourceLearningState(context, status.port);
      } catch {
        context.outputChannel.appendLine('[resources] Could not refresh the learning snapshot after capture.');
      }
    }
    const capturedTitle = asString(record.name ?? record.title)?.trim() || url;
    return {
      ok: true,
      message: deduped
        ? hostCommandCopy(lang, 'captureAlreadyInLibrary', { title: capturedTitle })
        : capturedTitle,
      data: captured,
    };
  } catch (error) {
    const detail = errorSidecarDetail(error);
    return {
      ok: false,
      message: libraryCopy('captureFetchFailed', lang, detail),
    };
  }
}

async function refreshResourceLearningState(context: CommandContext, port: number): Promise<void> {
  const workspaceId = getRuntimeWorkspaceId(context);
  const summary = await context.sidecarClient.getJson<unknown>(
    port,
    withWorkspaceQuery('/memory/summary', context, workspaceId),
  );
  if (workspaceId === getRuntimeWorkspaceId(context)) {
    await context.patchWorkbenchData(
      mergeMemorySummarySnapshot(context.getHostState().bootstrap, summary, workspaceId),
    );
  }
}

export async function checkResourceVersionsCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const lang = resourceResponseLanguage(context);
  const request = isResourceCapturePayloadRecord(payload);
  const workspaceId = getRuntimeWorkspaceId(context);
  const sessionId = context.getSessionId();
  if (request.workspace_id !== workspaceId) {
    return { ok: false, message: hostCommandCopy(lang, 'projectChangedCheckSourcesAgain') };
  }
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
  }
  if (workspaceId !== getRuntimeWorkspaceId(context) || sessionId !== context.getSessionId()) {
    return { ok: false, message: hostCommandCopy(lang, 'projectChangedCheckSourcesAgain') };
  }
  const results = await context.sidecarClient.postJson<ResourceVersionCheckResult[]>(
    status.port, '/resources/check-versions',
    { workspace_id: workspaceId, session_id: sessionId, sources: request.sources },
    { timeoutMs: RESOURCE_CAPTURE_TIMEOUT_MS },
  );
  return { ok: true, data: results };
}

export async function linkResourceToLearningCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) return admissionBlock;
  const lang = resourceResponseLanguage(context);
  if (!(await context.trustGuard.ensureTrusted('link library sources to learning'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredLinkSources') };
  }
  const request = isResourceCapturePayloadRecord(payload);
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
  }
  if (request.workspace_id && request.workspace_id !== getRuntimeWorkspaceId(context)) {
    return { ok: false, message: hostCommandCopy(lang, 'projectChangedConfirmLink') };
  }
  try {
    const linked = await context.sidecarClient.postJson(
      status.port,
      '/resources/link-learning',
      { ...request, session_id: context.getSessionId(), workspace_id: getRuntimeWorkspaceId(context) },
    );
    try {
      await refreshResourceLearningState(context, status.port);
    } catch {
      context.outputChannel.appendLine('[resources] Could not refresh the learning snapshot after linking.');
    }
    return { ok: true, data: linked };
  } catch (error) {
    return { ok: false, message: errorSidecarDetail(error) ?? hostCommandCopy(lang, 'resourceLinkSaveFailed') };
  }
}

/**
 * P2 (Trainer 2.0): turn one finished library/analysis reply into a Research
 * Brief library asset. The server drafts, validates and pins the citations —
 * the host only forwards the learner's goal, the reply text and the attached
 * resource ids, and never invents brief content itself.
 */
export async function saveResearchBriefCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const lang = resourceResponseLanguage(context);
  const request = isResourceCapturePayloadRecord(payload);
  const researchGoal = asString(request.researchGoal ?? request.research_goal)?.trim() ?? '';
  const reply = asString(request.reply)?.trim() ?? '';
  if (!researchGoal || !reply) {
    return {
      ok: false,
      message: hostCommandCopy(lang, 'briefMissingGoalOrReply'),
    };
  }
  const workspaceId = getRuntimeWorkspaceId(context);
  const sessionId = context.getSessionId();
  const generation = context.getHostState().bootstrap.runtimeDataGeneration;
  const currentScope = () => getRuntimeWorkspaceId(context) === workspaceId &&
    context.getSessionId() === sessionId && context.getHostState().bootstrap.runtimeDataGeneration === generation;
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
  }
  const resourceIds = Array.isArray(request.resourceIds)
    ? request.resourceIds
        .map((item) => asString(item)?.trim() ?? '')
        .filter(Boolean)
        .slice(0, 4)
    : [];
  try {
    const provider = context.providerStore.getConfig();
    const apiKey = await context.providerStore.getApiKey();
    if (!currentScope()) return { ok: false, message: hostCommandCopy(lang, 'workspaceChangedBeforeBrief') };
    const result = await context.sidecarClient.postJson(
      status.port,
      '/resource/research-brief/draft',
      {
        researchGoal: researchGoal.slice(0, 300),
        reply: reply.slice(0, 12000),
        resourceIds,
        responseLanguage: lang,
        contextId: workspaceId,
        provider,
        api_key: apiKey,
        save: true,
        __trainerResourceOperationId: request.__trainerResourceOperationId,
      },
    );
    const payload = asRecord(result);
    const brief = mapResearchBriefAsset(payload?.asset);
    if (payload?.saved !== true || !brief) return { ok: false, message: hostCommandCopy(lang, 'briefNotReturned') };
    if (currentScope()) {
      const memory = context.getHostState().bootstrap.memory;
      await context.patchWorkbenchData({ memory: { ...memory, researchBriefs: upsertResearchBrief(memory.researchBriefs, brief) } });
    }
    return { ok: true, data: result };
  } catch (error) {
    return {
      ok: false,
      message: errorSidecarDetail(error) ?? hostCommandCopy(lang, 'briefPrepareFailed'),
    };
  }
}

function errorSidecarDetail(error: unknown): string | undefined {
  const metadata = (error as { metadata?: { detail?: unknown; code?: unknown } }).metadata;
  const detail = typeof metadata?.detail === 'string' ? metadata.detail.trim() : '';
  const code = typeof metadata?.code === 'string' ? metadata.code.trim() : '';
  if (detail) {
    return detail;
  }
  if (code) {
    return code;
  }
  const message = error instanceof Error ? error.message : String(error);
  // Keep the surfaced detail short and path-free: a fetch/timeout class, not a raw stack.
  return /timed out/i.test(message)
    ? 'timed out'
    : /fetch|network|ECONN|ENOTFOUND|getaddrinfo/i.test(message)
      ? 'fetch_failed'
      : undefined;
}

/** Internal bridge: rename/retag/regroup one resource from the reader. */
export async function organizeResourceCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }

  const language = resourceResponseLanguage(context);
  if (!(await context.trustGuard.ensureTrusted('organize the resource library'))) {
    return { ok: false, message: hostCommandCopy(language, 'trustRequiredOrganize') };
  }

  const request = isResourceCapturePayloadRecord(payload);
  const resourceId = asString(request.resource_id ?? request.resourceId)?.trim();
  const action = asString(request.action)?.trim();
  if (!resourceId || !action || !['rename', 'set_tags', 'set_group'].includes(action)) {
    return { ok: false, message: libraryCopy('organizeInvalid', language) };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: libraryCopy('serviceUnavailable', language) };
  }

  const tags = asStringArray(request.tags)?.map((tag) => tag.trim()).filter(Boolean);
  try {
    const organized = await context.sidecarClient.postJson<unknown>(status.port, '/resource/organize', {
      session_id: context.getSessionId(),
      workspace_id: getRuntimeWorkspaceId(context) || asString(request.workspace_id)?.trim() || undefined,
      resource_id: resourceId,
      action,
      ...(action === 'rename' && asString(request.title)?.trim() ? { title: asString(request.title)?.trim() } : {}),
      ...(action === 'set_tags' && tags ? { tags } : {}),
      ...(action === 'set_group' ? { group: asString(request.group)?.trim() ?? '' } : {}),
    });
    await context.patchWorkbenchData(
      mergeResourceRecords(context.getHostState().bootstrap, [organized]),
    );
    return { ok: true, message: '', data: organized };
  } catch (error) {
    const statusCode = (error as { statusCode?: unknown }).statusCode;
    if (statusCode === 404) {
      return { ok: false, message: libraryCopy('organizeNotFound', language) };
    }
    if (statusCode === 409) {
      return { ok: false, message: libraryCopy('organizeBlocked', language) };
    }
    if (statusCode === 422) {
      return { ok: false, message: libraryCopy('organizeInvalid', language) };
    }
    return { ok: false, message: libraryCopy('serviceUnavailable', language) };
  }
}

/** Internal bridge: save one resource's owned snapshot through the OS save flow. */
export async function exportResourceCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const language = resourceResponseLanguage(context);
  if (!(await context.trustGuard.ensureTrusted('export a resource'))) {
    return { ok: false, message: hostCommandCopy(language, 'trustRequiredExport') };
  }

  const request = isResourceCapturePayloadRecord(payload);
  const resourceId = asString(request.resource_id ?? request.resourceId)?.trim();
  const requestedFormat =
    asString(request.format)?.trim().toLowerCase() === 'pdf' ? 'pdf' : 'markdown';
  const resource = resourceId
    ? context.getHostState().bootstrap.resources.find((item) => item.id === resourceId)
    : undefined;
  if (!resource) {
    return { ok: false, message: libraryCopy('exportNotFound', language) };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: libraryCopy('serviceUnavailable', language) };
  }

  const workspaceId = getRuntimeWorkspaceId(context);
  const sessionId = context.getSessionId();
  const query = new URLSearchParams({ resource_id: resource.id });
  if (requestedFormat === 'pdf') {
    query.set('format', 'pdf');
  }
  if (sessionId) {
    query.set('session_id', sessionId);
  }
  if (workspaceId) {
    query.set('workspace_id', workspaceId);
  }

  let bytes: Buffer;
  let filename: string | undefined;
  try {
    const exported = await context.sidecarClient.getBytes(
      status.port,
      `/resource/export?${query.toString()}`,
      { timeoutMs: RESOURCE_CAPTURE_TIMEOUT_MS },
    );
    bytes = exported.bytes;
    filename = exported.filename || resource.title.trim() || resource.id;
  } catch (error) {
    const statusCode = (error as { statusCode?: unknown }).statusCode;
    if (statusCode === 404) {
      return { ok: false, message: libraryCopy('exportNotFound', language) };
    }
    if (statusCode === 409) {
      return { ok: false, message: libraryCopy('exportNoSnapshot', language) };
    }
    return {
      ok: false,
      message: libraryCopy('exportSaveFailed', language, errorSidecarDetail(error)),
    };
  }

  const sanitize = (value: string) => value.replace(/[\\/:*?"<>|]/g, '_').trim() || 'resource';
  const normalizedFilename =
    requestedFormat === 'pdf' && !sanitize(filename).toLowerCase().endsWith('.pdf')
      ? `${sanitize(filename).replace(/\.md$/i, '')}.pdf`
      : sanitize(filename);
  const defaultUri = vscode.workspace.workspaceFile
    ? vscode.Uri.joinPath(vscode.Uri.file(path.dirname(vscode.workspace.workspaceFile.fsPath)), normalizedFilename)
    : undefined;
  const target = await vscode.window.showSaveDialog({
    defaultUri,
    saveLabel: hostCommandCopy(language, 'exportSaveLabel'),
    filters:
      requestedFormat === 'pdf'
        ? { PDF: ['pdf'] }
        : { Markdown: ['md'] },
  });
  if (!target) {
    // Report the cancellation as a normal outcome (not `cancelled`): a
    // cancelled status would suppress every message and leave the reader
    // waiting on a save flow the user explicitly dismissed.
    return { ok: false, message: libraryCopy('exportSaveCancelled', language) };
  }

  try {
    await vscode.workspace.fs.writeFile(target, bytes);
  } catch (error) {
    return {
      ok: false,
      message: libraryCopy('exportSaveFailed', language, error instanceof Error ? error.message : String(error)),
    };
  }
  return { ok: true, message: libraryCopy('exportSucceeded', language, sanitize(filename)), data: { path: target.fsPath } };
}

/** One Markdown-only library migration step: preview first, then one confirmation. */
export interface MarkdownOnlyMigrationSummary {
  status: 'preview' | 'confirmation_required' | 'complete' | 'partial';
  workspace_id?: string;
  dry_run?: boolean;
  resources?: number;
  originals_to_delete?: number;
  records_to_mark?: number;
  convertible?: number;
  /** Originals kept because no canonical Markdown stands behind them. */
  originals_kept?: number;
  kept_originals?: string[];
  manifest?: Array<Record<string, unknown>>;
  manifest_path?: string;
  failures?: Array<Record<string, unknown>>;
}

/**
 * Markdown-only library migration bridge.
 *
 * The webview posts one `command/execute` carrying a per-request
 * `operationId`; the host answers with a `library/migration` message that
 * carries the same id — the same correlation pattern as `library/folders`.
 * The dry-run is the default: the destructive pass only runs when the same
 * surface that showed the preview confirms it once.
 */
export async function markdownOnlyMigrationCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const request = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : undefined;
  const operationId = typeof request?.operationId === 'string' ? request.operationId.trim() : '';
  const dryRun = request?.dryRun !== false;
  const confirm = request?.confirm === true;
  const language = resourceResponseLanguage(context);

  const answer = async (ok: boolean, message: string, summary?: MarkdownOnlyMigrationSummary) => {
    if (!operationId) {
      return;
    }
    await context.workbench.postMessage({
      type: 'library/migration',
      payload: { operationId, ok, message, ...(summary ? { summary } : {}) },
    });
  };

  if (!dryRun && !confirm) {
    // The server refuses an unconfirmed destructive pass. Say so locally
    // instead of asking the sidecar for a pass it will reject.
    const message = libraryCopy('migrationConfirmationRequired', language);
    await answer(false, message);
    return { ok: false, message };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    const message = libraryCopy('serviceUnavailable', language);
    await answer(false, message);
    return { ok: false, message };
  }

  const workspaceId = getRuntimeWorkspaceId(context);
  const sessionId = context.getSessionId();
  try {
    const summary = await context.sidecarClient.postJson<MarkdownOnlyMigrationSummary>(
      status.port,
      '/resource/md-only/migrate',
      {
        workspace_id: workspaceId,
        session_id: sessionId,
        dry_run: dryRun,
        confirm,
      },
      { timeoutMs: RESOURCE_CAPTURE_TIMEOUT_MS },
    );
    await answer(true, '', summary);
    return { ok: true, data: summary };
  } catch (error) {
    const message = libraryCopy('migrationFailed', language, errorSidecarDetail(error));
    await answer(false, message);
    return { ok: false, message };
  }
}

export async function indexResourcesCommand(  context: CommandContext,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('index training resources'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredIndex') };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
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
      }, { timeoutMs: RESOURCE_INDEX_TIMEOUT_MS });
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
  const payloadRecord = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : undefined;
  const resourceId = payloadRecord?.resourceId;
  const researchCitation = asRecord(payloadRecord?.researchCitation);
  const openSource = payloadRecord?.openSource === true;
  const requestedLine =
    typeof payloadRecord?.line === 'number' && Number.isFinite(payloadRecord.line)
      ? Math.max(1, Math.floor(payloadRecord.line))
      : undefined;
  const language = resourceResponseLanguage(context);

  if (typeof resourceId !== 'string') {
    return { ok: false, message: hostCommandCopy(language, 'noSingleResourceSelected') };
  }

  const resource = context.getHostState().bootstrap.resources.find((item) => item.id === resourceId);
  if (!resource) {
    return { ok: false, message: hostCommandCopy(language, 'selectedResourceMissing') };
  }
  const unavailablePin = () => ({ ok: false, message: hostCommandCopy(language, 'unavailablePinLocation') });
  if (researchCitation && (!requestedLine || !resource.versionId || !resource.contentHash ||
    resource.versionId !== researchCitation.versionId || resource.contentHash !== researchCitation.contentHash)) {
    return unavailablePin();
  }

  // The library is Markdown-only: a row opens the canonical Markdown
  // document. There is no original binary to open.
  const target = resolveResourceOpenTarget(resource);
  if (target.kind === 'unavailable') {
    if (researchCitation) return unavailablePin();
    return {
      ok: false,
      message:
        target.reason === 'missing_source'
          ? libraryCopy('openMissingSource', language)
          : libraryCopy('openCaptureRequired', language),
    };
  }

  const targetUri = await resolveExistingResourceUri(
    context,
    resolveResourceReadCandidates(resource),
  );
  if (!targetUri) {
    if (researchCitation) return unavailablePin();
    return { ok: false, message: libraryCopy('openMissingFile', language) };
  }

  let line = requestedLine;
  if (researchCitation && requestedLine) {
    if (typeof researchCitation.excerpt !== 'string' || typeof researchCitation.lineEnd !== 'number') {
      return unavailablePin();
    }
    try {
      const document = await vscode.workspace.openTextDocument(targetUri);
      const canonical = resource.canonicalMarkdownPath?.replace(/\\/g, '/');
      const isCanonicalFile = Boolean(canonical && targetUri.path.toLowerCase().endsWith(`/${canonical.replace(/^\/+/, '').toLowerCase()}`));
      line = resolveResearchCitationLine(document.getText(), requestedLine, {
        excerpt: researchCitation.excerpt, lineEnd: researchCitation.lineEnd,
      }, isCanonicalFile);
      if (line === undefined) return unavailablePin();
    } catch {
      return unavailablePin();
    }
  }
  const startLine = line ? line - 1 : 0;
  const isMarkdownDocument = /\.(?:md|markdown)$/i.test(targetUri.path);
  if (isMarkdownDocument && !openSource && line === undefined) {
    try {
      await vscode.commands.executeCommand('markdown.showPreview', targetUri);
      return {
        ok: true,
        message: hostCommandCopy(language, 'openedPreview', { title: resource.title }),
      };
    } catch {
      // Fall back to opening the source document if Markdown preview is unavailable.
    }
  }
  await vscode.commands.executeCommand('vscode.open', targetUri, {
    preview: false,
    preserveFocus: false,
    selection: new vscode.Range(startLine, 0, startLine, 0),
  });
  return {
    ok: true,
    message: hostCommandCopy(language, 'openedResource', { title: resource.title }),
  };
}

function expandResourceHomePath(value: string): string {
  if (value === '~') {
    return os.homedir();
  }
  if (value.startsWith('~/') || value.startsWith('~\\')) {
    return path.join(os.homedir(), value.slice(2));
  }
  return value;
}

/**
 * Roots a relative resource source may be relative to. The workspace folder
 * is the common case; the admission roots cover resources imported before the
 * project was adopted, and the sandbox roots cover managed library copies.
 */
function resourceOpenRoots(context: CommandContext): string[] {
  const state = context.getHostState();
  const admission = state.bootstrap.memory?.workspace?.trainerWorkspace;
  const sandbox = state.bootstrap.memory?.sandboxState;
  const roots = new Set<string>();
  const add = (value: string | undefined) => {
    const trimmed = value?.trim();
    if (!trimmed) return;
    if (!looksLikeWindowsAbsolutePath(trimmed) && !path.isAbsolute(trimmed)) return;
    roots.add(normalizeFsPath(trimmed));
  };
  add(context.trainerWorkspace?.getRoot());
  add(admission?.rootPath);
  add(state.workspace.activeWorkspaceRoot);
  add(state.workspace.workspaceFolder);
  add(admission?.projectPath);
  add(admission?.canonicalProjectPath);
  add(sandbox?.rootPath);
  add(sandbox?.sandboxRootPath);
  add(sandbox?.workspaceRootPath);
  add(sandbox?.activeWorkspaceRoot);
  for (const folder of vscode.workspace?.workspaceFolders ?? []) {
    if (folder.uri.scheme === 'file') {
      add(folder.uri.fsPath);
    }
  }
  return [...roots];
}

async function localResourceFileExists(targetPath: string): Promise<boolean> {
  try {
    const stat = await fs.stat(targetPath);
    return stat.isFile();
  } catch {
    return false;
  }
}

async function resolveLocalResourceUri(
  context: CommandContext,
  candidates: string[],
): Promise<vscode.Uri | undefined> {
  const roots = resourceOpenRoots(context);
  for (const candidate of candidates) {
    const expanded = expandResourceHomePath(candidate);
    if (/^file:\/\//i.test(expanded)) {
      try {
        const uri = vscode.Uri.parse(expanded);
        if (uri.scheme === 'file' && (await localResourceFileExists(uri.fsPath))) {
          return uri;
        }
      } catch {
        // A malformed file URI is not a reason to stop trying the next source
        // candidate; the final failure stays honest either way.
      }
      continue;
    }
    if (looksLikeWindowsAbsolutePath(expanded)) {
      if (process.platform !== 'win32') {
        // A Windows identifier cannot name a readable file on a POSIX host;
        // opening it would only produce the same broken tab we are fixing.
        continue;
      }
      const normalized = normalizeFsPath(expanded);
      if (await localResourceFileExists(normalized)) {
        return vscode.Uri.file(normalized);
      }
      continue;
    }
    if (path.isAbsolute(expanded)) {
      const normalized = normalizeFsPath(expanded);
      if (await localResourceFileExists(normalized)) {
        return vscode.Uri.file(normalized);
      }
      continue;
    }
    for (const root of roots) {
      const resolved = path.resolve(root, expanded);
      if (await localResourceFileExists(resolved)) {
        return vscode.Uri.file(resolved);
      }
    }
  }
  return undefined;
}

async function resolveRemoteResourceUri(
  context: CommandContext,
  candidates: string[],
): Promise<vscode.Uri | undefined> {
  const folders = (vscode.workspace?.workspaceFolders ?? []).filter(
    (folder) => folder.uri.scheme !== 'file',
  );
  if (folders.length === 0) {
    return undefined;
  }
  for (const candidate of candidates) {
    const expanded = expandResourceHomePath(candidate);
    if (/^file:\/\//i.test(expanded)) {
      continue;
    }
    for (const folder of folders) {
      let uri: vscode.Uri | undefined;
      if (!looksLikeWindowsAbsolutePath(expanded) && path.isAbsolute(expanded)) {
        uri = folder.uri.with({ path: expanded });
      } else if (!looksLikeWindowsAbsolutePath(expanded)) {
        uri = vscode.Uri.joinPath(folder.uri, expanded);
      }
      if (!uri) {
        continue;
      }
      try {
        const stat = await context.workspaceGateway.stat(uri);
        if ((stat.type & 1) === 1) {
          return uri;
        }
      } catch {
        // Keep looking: a missing remote path is not an error until every
        // candidate and root has been tried.
      }
    }
  }
  return undefined;
}

async function resolveExistingResourceUri(
  context: CommandContext,
  candidates: string[],
): Promise<vscode.Uri | undefined> {
  if (candidates.length === 0) {
    return undefined;
  }
  return isRemoteWorkspaceSnapshot(context.getHostState().workspace)
    ? resolveRemoteResourceUri(context, candidates)
    : resolveLocalResourceUri(context, candidates);
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
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('delete training resources'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredDeleteResources') };
  }

  const deletionRequest = extractResourceDeletionRequest(payload);
  if (deletionRequest.resourceIds.length === 0) {
    return { ok: false, message: hostCommandCopy(lang, 'noResourcesSelected') };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
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
        message: hostCommandCopy(lang, 'resourcesDeletedRefreshFailed'),
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
      resourceResponseLanguage(context),
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
  const lang = resourceResponseLanguage(context);
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return {
      ...admissionBlock,
      message: `${admissionBlock.message ?? hostCommandCopy(lang, 'trashRefreshBlockDefault')} ${preservedTrashListMessage(context)}`,
    };
  }

  if (!(await context.trustGuard.ensureTrusted('refresh the resource Trash'))) {
    return {
      ok: false,
      message: hostCommandCopy(lang, 'trustRequiredRefreshTrash'),
    };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
  }

  try {
    const deletedResources = await loadDeletedResources(context, status.port);
    await context.patchWorkbenchData({ deletedResources });
    return {
      ok: true,
      message:
        deletedResources.length > 0
          ? hostCommandCopy(lang, 'trashRefreshedCount', { count: deletedResources.length })
          : hostCommandCopy(lang, 'trashRefreshedEmpty'),
      data: deletedResources,
    };
  } catch {
    return {
      ok: false,
      message: hostCommandCopy(lang, 'trashRefreshFailed'),
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
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('restore training resources'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredRestoreResources') };
  }

  const restorationRequest = extractResourceDeletionRequest(payload);
  if (restorationRequest.resourceIds.length === 0) {
    return { ok: false, message: hostCommandCopy(lang, 'noDeletedResourcesSelected') };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
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
        message: hostCommandCopy(lang, 'resourcesRestoredRefreshFailed'),
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
    message: buildResourceRestorationResultMessage(
      batchResult,
      trashSnapshotConfirmed,
      resourceResponseLanguage(context),
    ),
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
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('restore sandbox resources'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredSandboxRestore') };
  }

  const sandboxPath =
    payload && typeof payload === 'object' && 'path' in payload
      ? (payload as { path?: unknown }).path
      : undefined;
  if (typeof sandboxPath !== 'string' || !sandboxPath.trim()) {
    return { ok: false, message: hostCommandCopy(lang, 'sandboxNoPathProvided') };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
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
    message: hostCommandCopy(lang, 'sandboxRestoredFromTrash'),
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
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('change the Trainer managed data folder'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredChangeDataFolder') };
  }

  const workspaceFolder = context.getHostState().workspace.workspaceFolder;
  const currentFolder = context.sidecarManager.getManagedDataFolderSnapshot(workspaceFolder);
  const picks = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    defaultUri: vscode.Uri.file(currentFolder.effectivePath),
    openLabel: hostCommandCopy(lang, 'useThisFolderOpenLabel'),
    title: hostCommandCopy(lang, 'chooseDataFolderTitle'),
  });
  let targetFolder = picks?.[0]?.fsPath;
  if (!targetFolder) {
    // 原生目录对话框被取消/不可用时,允许直接输入路径(不存在则创建),
    // 首次设置永远不会在这里卡死。
    const typed = await vscode.window.showInputBox({
      prompt: hostCommandCopy(lang, 'chooseDataFolderPromptFallback'),
      placeHolder: currentFolder.effectivePath,
      ignoreFocusOut: true,
    });
    targetFolder = typed?.trim();
    if (!targetFolder) {
      return { ok: false, message: hostCommandCopy(lang, 'dataFolderCancelled') };
    }
  }

  let change;
  try {
    change = await context.sidecarManager.configureManagedDataFolder(targetFolder, workspaceFolder);
  } catch (error) {
    // 非空目录是最常见的误选:自动改用它下面一个空的 Trainer 专用子目录。
    const fallbackFolder = path.join(targetFolder, 'Trainer');
    try {
      await fs.mkdir(fallbackFolder, { recursive: true });
      change = await context.sidecarManager.configureManagedDataFolder(
        fallbackFolder,
        workspaceFolder,
      );
    } catch (fallbackError) {
      return {
        ok: false,
        message: hostCommandCopy(lang, 'dataFolderPickFailed', {
          error: error instanceof Error ? error.message : String(error),
          fallbackError: fallbackError instanceof Error ? fallbackError.message : String(fallbackError),
        }),
      };
    }
  }
  return applyManagedDataFolderChange(context, change);
}

export async function resetManagedDataFolderCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('reset the Trainer managed data folder'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredResetDataFolder') };
  }

  const workspaceFolder = context.getHostState().workspace.workspaceFolder;
  const change = await context.sidecarManager.resetManagedDataFolder(workspaceFolder, {
    allowExistingTarget: true,
    copyExistingData: false,
  });
  return applyManagedDataFolderChange(context, change);
}

export async function moveManagedDataUnderRootCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('move Trainer data under the workspace root'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredAdoptDataFolder') };
  }

  // Unified-root model (P0): the recommended data home is the workspace
  // root's `.trainer/runtime` data area. This reuses the exact migration
  // machinery the root-selection flow uses (configureManagedDataFolder), so
  // the move is the same vetted copy/restart path — only the destination is
  // derived from the root instead of asked from the user.
  const rootPath =
    context.getHostState().bootstrap.memory.workspace?.trainerWorkspace?.rootPath?.trim() ||
    context.trainerWorkspace.getRoot();
  if (!rootPath) {
    return {
      ok: false,
      message: hostCommandCopy(lang, 'chooseWorkspaceRootBeforeMove'),
    };
  }

  const workspaceFolder = context.getHostState().workspace.workspaceFolder;
  const targetFolder = runtimeDataRootUnder(rootPath);
  const current = context.sidecarManager.getManagedDataFolderSnapshot(workspaceFolder);
  const samePath = (left: string, right: string): boolean =>
    normalizeFsPath(left).toLowerCase() === normalizeFsPath(right).toLowerCase() ||
    left === right;
  if (samePath(current.effectivePath, targetFolder)) {
    return { ok: true, message: hostCommandCopy(lang, 'dataAlreadyUnderWorkspaceRoot') };
  }

  const change = await context.sidecarManager.configureManagedDataFolder(targetFolder, workspaceFolder, {
    allowExistingTarget: true,
  });
  return applyManagedDataFolderChange(context, change);
}

export async function chooseSandboxRootCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('change the workspace sandbox root'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredChangeSandboxRoot') };
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
    openLabel: hostCommandCopy(lang, 'useAsSandboxRootLabel'),
    title: hostCommandCopy(lang, 'chooseSandboxRootTitle'),
  });
  const targetFolder = picks?.[0]?.fsPath;
  if (!targetFolder) {
    return { ok: false, message: hostCommandCopy(lang, 'sandboxRootCancelled') };
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
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('reset the workspace sandbox root'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredResetSandboxRoot') };
  }

  return applySandboxRootChange(context, { clear: true });
}

export async function searchResourcesCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const lang = resourceResponseLanguage(context);
  const request = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
  const query = typeof request.query === 'string' ? request.query.trim() : '';
  const requestId = normalizeResourceSearchRequestId(request);
  const requestOwner = Symbol('resource-search');
  resourceSearchRequestOwners.set(context, requestOwner);
  if (!query) {
    return { ok: false, message: hostCommandCopy(lang, 'searchQueryRequired') };
  }

  if (!(await context.trustGuard.ensureTrusted('search training resources'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredSearch') };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
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
    message: buildResourceSearchMessage(normalized, lang),
    data: normalized,
  };
}

export async function createSandboxDirectoryCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const admissionBlock = resourceMutationAdmissionBlock(context);
  if (admissionBlock) {
    return admissionBlock;
  }
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('create sandbox directories'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredSandboxMkdir') };
  }

  const requestedPath =
    payload && typeof payload === 'object' && 'path' in payload
      ? (payload as { path?: unknown }).path
      : undefined;
  const directoryPath = typeof requestedPath === 'string' ? requestedPath.trim() : '';
  if (!directoryPath) {
    return { ok: false, message: hostCommandCopy(lang, 'sandboxMissingDirPath') };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
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
    message: hostCommandCopy(lang, 'sandboxCreatedFolder', { path: directoryPath }),
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
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('create sandbox files'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredSandboxWrite') };
  }

  const request = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
  const requestedPath = typeof request.path === 'string' ? request.path.trim() : '';
  const content = typeof request.content === 'string' ? request.content : '';
  if (!requestedPath) {
    return { ok: false, message: hostCommandCopy(lang, 'sandboxMissingFilePath') };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
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
    message: hostCommandCopy(lang, 'sandboxCreatedFile', { path: requestedPath }),
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
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('rename sandbox paths'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredSandboxRename') };
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
    return { ok: false, message: hostCommandCopy(lang, 'sandboxNoPathProvided') };
  }
  if (!nextPath) {
    return { ok: false, message: hostCommandCopy(lang, 'sandboxMissingNextPath') };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
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
    message: hostCommandCopy(lang, 'sandboxRenamedPath', { path: nextPath }),
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
  const lang = resourceResponseLanguage(context);

  if (!(await context.trustGuard.ensureTrusted('delete sandbox paths'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredSandboxDelete') };
  }

  const sandboxPath =
    payload && typeof payload === 'object' && 'path' in payload
      ? (payload as { path?: unknown }).path
      : undefined;
  if (typeof sandboxPath !== 'string' || !sandboxPath.trim()) {
    return { ok: false, message: hostCommandCopy(lang, 'sandboxNoPathProvided') };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
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
    message: hostCommandCopy(lang, 'sandboxMovedOneToTrash'),
    data: sandboxState,
  };
}

export async function deleteSandboxPathsCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const lang = resourceResponseLanguage(context);
  const request = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
  const candidatePaths = Array.isArray(request.paths) ? request.paths : [];
  const paths = candidatePaths
    .map((value) => (typeof value === 'string' ? value.trim() : ''))
    .filter((value, index, items) => value.length > 0 && items.indexOf(value) === index);

  if (paths.length === 0) {
    return { ok: false, message: hostCommandCopy(lang, 'sandboxNoPathsProvided') };
  }

  let lastResult: CommandExecutionResult | undefined;
  for (const sandboxPath of paths) {
    const result = await deleteSandboxPathCommand(context, { path: sandboxPath });
    if (!result.ok) {
      return {
        ok: false,
        message: result.message || hostCommandCopy(lang, 'sandboxDeletePathFailed', { path: sandboxPath }),
        data: result.data,
      };
    }
    lastResult = result;
  }

  return {
    ok: true,
    message:
      paths.length === 1
        ? hostCommandCopy(lang, 'sandboxMovedOneToTrash')
        : hostCommandCopy(lang, 'sandboxMovedManyToTrash', { count: paths.length }),
    data: lastResult?.data,
  };
}

export async function refreshSandboxCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const lang = resourceResponseLanguage(context);
  if (!(await context.trustGuard.ensureTrusted('refresh resource sandbox capability'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredSandboxRefresh') };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
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
    message: hostCommandCopy(lang, 'sandboxCapabilityRefreshed'),
    data: sandboxState,
  };
}

export async function revealSandboxPathCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const lang = resourceResponseLanguage(context);
  if (!(await context.trustGuard.ensureTrusted('open sandbox paths in the system file manager'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredSandboxOpen') };
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
    return { ok: false, message: hostCommandCopy(lang, 'sandboxNoPathAvailableToOpen') };
  }

  try {
    await fs.access(targetPath);
  } catch {
    return { ok: false, message: hostCommandCopy(lang, 'sandboxPathUnavailable', { path: targetPath }) };
  }

  const targetUri = vscode.Uri.file(targetPath);
  const targetLabel = basenameFs(targetPath) || targetPath;
  try {
    await vscode.commands.executeCommand('revealFileInOS', targetUri);
  } catch {
    return { ok: false, message: hostCommandCopy(lang, 'sandboxRevealFailed', { target: targetLabel }) };
  }

  return {
    ok: true,
    message: hostCommandCopy(lang, 'sandboxRevealDone', { target: targetLabel }),
  };
}

function validateResourceUrl(value: string, lang: ComposerLanguage = 'en-US'): string | undefined {
  if (!value.trim()) {
    return hostCommandCopy(lang, 'resourceUrlValidateEmpty');
  }
  try {
    const url = new URL(value.trim());
    if (!['http:', 'https:'].includes(url.protocol)) {
      return hostCommandCopy(lang, 'resourceUrlValidateHttp');
    }
  } catch {
    return hostCommandCopy(lang, 'resourceUrlValidateInvalid');
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

function captureKindForUrl(source: string): 'web' | 'pdf' | 'github_repo' {
  try {
    const url = new URL(source);
    if (
      /^(?:www\.)?github\.com$/i.test(url.hostname) &&
      /^\/[^/]+\/[^/]+/.test(url.pathname)
    ) {
      return 'github_repo';
    }
    if (/\.pdf$/i.test(url.pathname)) {
      return 'pdf';
    }
  } catch {
    // The sidecar performs the real validation; malformed URLs fall back to web.
  }
  return 'web';
}

async function uploadLocalFiles(
  context: CommandContext,
  port: number,
  workspaceId: string,
  filePaths: string[],
  collectionRoot?: string,
  onUploaded?: ResourceRecordObserver,
  skipCollectionMaterialization = false,
): Promise<ResourceUploadBatchResult> {
  const uploads: unknown[] = [];
  let failedCount = 0;
  for (const filePath of filePaths) {
    const collectionPath =
      collectionRoot && !skipCollectionMaterialization
        ? collectionPathForFile(filePath, collectionRoot)
        : undefined;
    let upload: unknown;
    try {
      // These paths come from the native file/folder picker. Import their
      // bytes through the local host so the sidecar never needs broader
      // filesystem access (including when the current project is remote).
      const content = await fs.readFile(filePath);
      upload = await context.sidecarClient.postJson<unknown>(port, '/resource/upload', {
        session_id: context.getSessionId(),
        workspace_id: workspaceId,
        kind: detectResourceKind(filePath),
        name: basenameFs(filePath),
        source: filePath,
        content: content.toString('base64'),
        content_encoding: 'base64',
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
  const windowsStyle =
    looksLikeWindowsAbsolutePath(filePath) || looksLikeWindowsAbsolutePath(collectionRoot);
  const root = windowsStyle ? path.win32.normalize(collectionRoot) : path.resolve(collectionRoot);
  const file = windowsStyle ? path.win32.normalize(filePath) : path.resolve(filePath);
  const relativePath = windowsStyle ? path.win32.relative(root, file) : path.relative(root, file);
  const separator = windowsStyle ? '\\' : path.sep;
  if (
    !relativePath ||
    relativePath === '.' ||
    relativePath === '..' ||
    relativePath.startsWith(`..${separator}`) ||
    (windowsStyle ? path.win32.isAbsolute(relativePath) : path.isAbsolute(relativePath))
  ) {
    return undefined;
  }

  const rootName = basenameFs(root).trim();
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
      }, { timeoutMs: RESOURCE_INDEX_TIMEOUT_MS });
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
  sourceMode: ResourceSourceMode;
  language?: ComposerLanguage;
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
  const lang = language ?? 'en-US';
  if (uploadsCount === 0) {
    const failedSummary =
      failedUploads > 0
        ? hostCommandCopy(lang, 'importFailedFilesRetry', {
            count: failedUploads,
            files: formatFileCount(failedUploads),
          })
        : hostCommandCopy(lang, 'importNoneAdded');
    const skippedSummary =
      skippedUnsupported > 0
        ? ` ${hostCommandCopy(lang, 'importSkippedHint', {
            count: skippedUnsupported,
            files: formatFileCount(skippedUnsupported),
          })}`
        : '';
    return `${failedSummary}${skippedSummary}`.trim();
  }
  const importedSummary = truncated
    ? sourceMode === 'folder' || sourceMode === 'workspace'
      ? hostCommandCopy(lang, 'importSummaryTruncatedFolder', { count: uploadsCount })
      : hostCommandCopy(lang, 'importSummaryTruncated', { count: uploadsCount })
    : hostCommandCopy(lang, 'importSummaryDone', { count: uploadsCount });
  const indexedSummary =
    indexedCount > 0
      ? hostCommandCopy(lang, 'importSummaryIndexed', { count: indexedCount })
      : lang === 'zh-CN'
        ? '。'
        : '.';
  const skippedSummary =
    skippedUnsupported > 0
      ? ` ${hostCommandCopy(lang, 'importSummarySkipped', { count: skippedUnsupported })}`
      : '';
  const failedUploadSummary =
    failedUploads > 0
      ? ` ${hostCommandCopy(lang, 'importPartialFailedUploads', {
          count: failedUploads,
          files: formatFileCount(failedUploads),
          importedWord: uploadsCount === 1 ? 'resource' : 'resources',
          otherWord: failedUploads === 1 ? 'file' : 'files',
        })}`
      : '';
  const failedIndexSummary =
    failedIndexes > 0
      ? ` ${hostCommandCopy(lang, 'importPartialFailedIndex', {
          count: failedIndexes,
          resources: formatResourceCount(failedIndexes),
          verb: failedIndexes === 1 ? 'needs' : 'need',
        })}`
      : '';
  const summaryRefreshNotice = summaryRefreshed
    ? ''
    : ` ${hostCommandCopy(lang, 'importSummaryNotRefreshed')}`;
  return `${importedSummary}${indexedSummary}${skippedSummary}${failedUploadSummary}${failedIndexSummary}${summaryRefreshNotice}`.trim();
}

function buildResourceIndexMessage(input: {
  indexedCount: number;
  failedCount: number;
  summaryRefreshed: boolean;
  language?: ComposerLanguage;
}): string {
  const { indexedCount, failedCount, summaryRefreshed, language } = input;
  const lang = language ?? 'en-US';
  if (indexedCount === 0 && failedCount === 0) {
    return hostCommandCopy(lang, 'indexAllUpToDate');
  }

  const indexedSummary = hostCommandCopy(lang, 'indexDoneCount', {
    count: indexedCount,
    resources: formatResourceCount(indexedCount),
  });
  const failedSummary =
    failedCount > 0
      ? ` ${hostCommandCopy(lang, 'indexFailedTail', {
          count: failedCount,
          resources: formatResourceCount(failedCount),
        })}`
      : '';
  const summaryRefreshNotice = summaryRefreshed
    ? ''
    : ` ${hostCommandCopy(lang, 'indexSummaryNotRefreshed')}`;
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
  if (extension === '.epub') {
    return 'epub';
  }
  if (['.docx', '.docm'].includes(extension)) {
    return 'docx';
  }
  if (['.pptx', '.pptm'].includes(extension)) {
    return 'pptx';
  }
  if (['.html', '.htm', '.xhtml'].includes(extension)) {
    return 'html';
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
  if (['.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'].includes(extension)) {
    return 'video';
  }
  return 'text';
}

function parseInlineResourceUploads(
  payload: unknown,
  lang: ComposerLanguage = 'en-US',
): {
  uploads: InlineResourceUpload[];
  error?: string;
} {
  if (!payload || typeof payload !== 'object' || !('uploads' in payload)) {
    return { uploads: [] };
  }

  const rawUploads = (payload as { uploads?: unknown }).uploads;
  if (!Array.isArray(rawUploads) || rawUploads.length === 0) {
    return { uploads: [], error: hostCommandCopy(lang, 'inlineResourcesEmpty') };
  }

  const uploads: InlineResourceUpload[] = [];
  for (let index = 0; index < rawUploads.length; index += 1) {
    const parsed = parseInlineResourceUpload(rawUploads[index], index, lang);
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
  lang: ComposerLanguage = 'en-US',
): InlineResourceUpload | string {
  if (!value || typeof value !== 'object') {
    return hostCommandCopy(lang, 'inlineResourceNotObject', { index: index + 1 });
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
    return hostCommandCopy(lang, 'inlineResourceMissingName', { index: index + 1 });
  }
  const source = typeof record.source === 'string' ? record.source.trim() : '';
  if (!source) {
    return hostCommandCopy(lang, 'inlineResourceMissingSource', { index: index + 1 });
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
    const validationError = validateResourceUrl(source, lang);
    if (validationError) {
      return hostCommandCopy(lang, 'inlineResourceInvalidUrl', {
        index: index + 1,
        error: validationError,
      });
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
    versionId: asString(record.version_id) ?? asString(record.versionId),
    contentHash: asString(record.content_hash) ?? asString(record.contentHash),
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
    canonicalMarkdownPath:
      asString(record.canonical_markdown_path) ?? asString(record.canonicalMarkdownPath),
    canonicalOriginalPath:
      asString(record.canonical_original_path) ?? asString(record.canonicalOriginalPath),
    parser: asString(record.parser),
    parserVersion: asString(record.parser_version) ?? asString(record.parserVersion),
    pageCount: asNumber(record.page_count) ?? asNumber(record.pageCount),
    slideCount: asNumber(record.slide_count) ?? asNumber(record.slideCount),
    location: asRecord(record.location),
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
  language?: ComposerLanguage,
): string {
  const lang = language ?? 'en-US';
  if (
    !request.isBatch &&
    result.deletedResourceIds.length === 1 &&
    result.failures.length === 0 &&
    result.summaryRefreshed &&
    trashSnapshotConfirmed
  ) {
    return buildDeleteResourceMessage(responses[0], lang);
  }

  const parts: string[] = [];
  if (result.deletedResourceIds.length > 0) {
    parts.push(
      hostCommandCopy(lang, 'deleteDeletedCount', {
        count: result.deletedResourceIds.length,
        resources: formatResourceCount(result.deletedResourceIds.length),
      }),
    );
  } else {
    parts.push(hostCommandCopy(lang, 'deleteNoneDeleted'));
  }
  if (result.failures.length > 0) {
    parts.push(
      hostCommandCopy(lang, 'deleteFailedCount', {
        count: result.failures.length,
        resources: formatResourceCount(result.failures.length),
      }),
    );
  }
  if (!result.summaryRefreshed && result.deletedResourceIds.length > 0) {
    parts.push(hostCommandCopy(lang, 'deleteSummaryRefreshFailed'));
  }
  if (!trashSnapshotConfirmed && result.deletedResourceIds.length > 0) {
    parts.push(hostCommandCopy(lang, 'deleteTrashUnconfirmed'));
  }
  const allGood =
    result.deletedResourceIds.length > 0 &&
    result.failures.length === 0 &&
    result.summaryRefreshed &&
    trashSnapshotConfirmed;
  const text = parts.join(lang === 'zh-CN' ? '' : ' ');
  // A not-fully-successful deletion reaches the webview's error sanitizer;
  // the marker marks this copy as curated + localized so it is shown verbatim.
  return allGood || (!request.isBatch && result.deletedResourceIds.length === 1 && result.failures.length === 0)
    ? text
    : `[[trainer-resource-failure]] ${text}`;
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
  language?: ComposerLanguage,
): string {
  const lang = language ?? 'en-US';
  const parts: string[] = [];
  if (result.restoredResourceIds.length > 0) {
    parts.push(
      hostCommandCopy(lang, 'restoreRestoredCount', {
        count: result.restoredResourceIds.length,
        resources: formatResourceCount(result.restoredResourceIds.length),
      }),
    );
  } else {
    parts.push(hostCommandCopy(lang, 'restoreNoneRestored'));
  }
  if (result.failures.length > 0) {
    parts.push(
      hostCommandCopy(lang, 'restoreFailedCount', {
        count: result.failures.length,
        resources: formatResourceCount(result.failures.length),
      }),
    );
  }
  if (!result.summaryRefreshed && result.restoredResourceIds.length > 0) {
    parts.push(hostCommandCopy(lang, 'deleteSummaryRefreshFailed'));
  }
  if (!trashSnapshotConfirmed && result.restoredResourceIds.length > 0) {
    parts.push(hostCommandCopy(lang, 'deleteTrashUnconfirmed'));
  }
  const allGood =
    result.restoredResourceIds.length > 0 &&
    result.failures.length === 0 &&
    result.summaryRefreshed &&
    trashSnapshotConfirmed;
  const text = parts.join(lang === 'zh-CN' ? '' : ' ');
  // Same trust marker as deletions: a partial restore reaches the error
  // sanitizer, and only marked copy is shown verbatim.
  return allGood ? text : `[[trainer-resource-failure]] ${text}`;
}

function formatResourceCount(count: number): string {
  return `${count} resource${count === 1 ? '' : 's'}`;
}

function buildDeleteResourceMessage(value: unknown, lang: ComposerLanguage = 'en-US'): string {
  const record = asRecord(value) ?? {};
  const detail = asString(record.detail) ?? hostCommandCopy(lang, 'deleteDefaultDetail');
  const checkpointId = asString(record.checkpoint_id) ?? asString(record.checkpointId);
  const ledgerEntryId = asString(record.ledger_entry_id) ?? asString(record.ledgerEntryId);
  const patchSteps = Array.isArray(record.patch) ? record.patch.length : 0;
  const parts = [detail];
  if (checkpointId) {
    parts.push(hostCommandCopy(lang, 'deleteCheckpointPart', { id: checkpointId }));
  }
  if (ledgerEntryId) {
    parts.push(hostCommandCopy(lang, 'deleteLedgerPart', { id: ledgerEntryId }));
  }
  if (patchSteps > 0) {
    parts.push(
      hostCommandCopy(lang, 'deletePatchStepCount', {
        count: patchSteps,
        steps: `${patchSteps} patch step${patchSteps === 1 ? '' : 's'}`,
      }),
    );
  }
  return parts.join(' ');
}

async function applyManagedDataFolderChange(
  context: CommandContext,
  change: ManagedDataFolderChangeResult,
): Promise<CommandExecutionResult> {
  const lang = resourceResponseLanguage(context);
  if (!change.changed) {
    return {
      ok: true,
      message: hostCommandCopy(
        lang,
        change.next.source === 'custom' ? 'dataFolderAlreadyCustom' : 'dataFolderAlreadyRecommended',
      ),
      data: change.next,
    };
  }

  await context.setSessionId(undefined);
  await context.patchWorkbenchData(
    resetWorkbenchAfterRuntimeDataChange(context.getHostState(), getRuntimeWorkspaceId(context)),
  );
  const status = await context.sidecarManager.restart();
  if (status.lifecycle === 'ready') {
    await rehydrateWorkbenchRuntime(context, {
      ensureSidecar: false,
      syncWorkbench: true,
    });
  }

  return {
    ok: status.lifecycle === 'ready',
    message: buildManagedDataFolderChangeMessage(change, status, lang),
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
  const lang = resourceResponseLanguage(context);
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? hostCommandCopy(lang, 'sidecarUnavailable') };
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
      ? hostCommandCopy(lang, 'sandboxRootResetDone')
      : hostCommandCopy(lang, 'sandboxRootFixedAt', {
          target: basenameFs(nextRoot ?? '') || nextRoot || hostCommandCopy(lang, 'selectedFolderLabel'),
        }),
    data: sandboxState,
  };
}

function buildManagedDataFolderChangeMessage(
  change: ManagedDataFolderChangeResult,
  status: { lifecycle: string; detail?: string },
  lang: ComposerLanguage = 'en-US',
): string {
  const changeSummary = hostCommandCopy(
    lang,
    change.next.source === 'custom' ? 'managedFolderUpdatedSummary' : 'managedFolderResetSummary',
  );
  const migrationSummary =
    change.migration === 'copied'
      ? ` ${hostCommandCopy(lang, 'managedMigrationCopied')}`
      : change.migration === 'skipped_nonempty_target'
        ? ` ${hostCommandCopy(lang, 'managedMigrationSkippedNonEmpty')}`
        : change.migration === 'skipped_nested_target'
          ? ` ${hostCommandCopy(lang, 'managedMigrationSkippedNested')}`
          : change.migration === 'source_missing'
            ? ` ${hostCommandCopy(lang, 'managedMigrationSourceMissing')}`
            : '';
  const previousFolderNote = ` ${hostCommandCopy(lang, 'managedFolderPrevUnchanged')}`;
  if (status.lifecycle !== 'ready') {
    const attention = hostCommandCopy(lang, 'managedFolderSidecarAttention', {
      detail: status.detail ?? hostCommandCopy(lang, 'backendUnavailable'),
    });
    return `${changeSummary}${migrationSummary}${previousFolderNote} ${attention}`;
  }
  return `${changeSummary}${migrationSummary}${previousFolderNote} ${hostCommandCopy(lang, 'managedFolderRestartReady')}`;
}

function buildResourceSearchMessage(
  search: BootstrapData['resourceSearch'],
  lang: ComposerLanguage = 'en-US',
): string {
  if (!search) {
    return hostCommandCopy(lang, 'resourceSearchZeroSummary');
  }
  const topHitSummary = search.hits[0]
    ? formatSearchHitTeachingSummary(search.hits[0], lang === 'zh-CN' ? 'zh' : 'en')
    : undefined;
  const summary = hostCommandCopy(lang, 'resourceSearchManySummary', { total: search.total });
  return topHitSummary ? `${summary} ${topHitSummary}` : summary;
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
    value === 'epub' ||
    value === 'docx' ||
    value === 'pptx' ||
    value === 'html' ||
    value === 'image' ||
    value === 'markdown' ||
    value === 'text' ||
    value === 'code' ||
    value === 'url' ||
    value === 'video'
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
  const record =
    payload && typeof payload === 'object' && !Array.isArray(payload)
      ? (payload as Record<string, unknown>)
      : {};
  const responseLanguage = isComposerLanguage(record.responseLanguage)
    ? record.responseLanguage
    : undefined;
  const lang = resourceResponseLanguage(context, responseLanguage);
  if (!armResourceOrganizationConfirm(context)) {
    return {
      ok: false,
      message: hostCommandCopy(lang, 'resourceOrganizeProposalMissing'),
    };
  }
  const confirmText = hostCommandCopy(lang, 'confirmOrganizePrompt');
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
