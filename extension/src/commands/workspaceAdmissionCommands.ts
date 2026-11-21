import * as vscode from 'vscode';
import * as os from 'node:os';
import * as path from 'node:path';
import fs from 'node:fs';
import { isComposerLanguage, type ComposerLanguage } from '../../../shared/src/types';
import { SidecarHttpError, type SidecarErrorPathState } from '../core/httpClient';
import { hostCommandCopy, resolveHostCommandLanguage } from './hostCommandCopy';
import { provisionRemoteProject } from './remoteProjectAdmission';

import type { CommandContext } from '../core/commandContext';
import { getRuntimeWorkspaceContext } from './workspaceContext';
import { maybePromptCarryOverOnProjectSwitch } from './memoryCommands';
import { rehydrateWorkbenchRuntime, rememberServerIssuedSession } from '../core/runtimeRehydration';
import { resolveTrainerWorkspaceAdmission, resolveTrainerProjectsList } from '../core/trainerWorkspaceAdmission';
import { resolveCurrentTrainerProjectPath } from '../core/trainerWorkspaceAdmission';
import { failClosedWorkbenchAfterWorkspaceTransfer, resetWorkbenchAfterRuntimeDataChange } from '../core/workbenchData';
import {
  applyExcludedWorkspacesToBootstrap,
  flushPendingTransferPromotionScope,
  postOrQueueTransferPromotionScope,
} from '../core/transferPromotionScope';
import {
  basenameFs,
  looksLikeWindowsAbsolutePath,
  normalizeFsPath,
  resolveSovereignWorkspaceRootPath,
} from '../core/workspaceRoots';
import {
  buildWorkspaceFileSnapshot,
  type WorkspaceFileSnapshot,
} from '../core/workspaceFileSnapshot';
import type { BootstrapData, CommandExecutionResult, FirstLookSummary } from '../core/types';
import {
  TRAINER_WORKSPACE_RUNTIME_DATA_DIRECTORY,
  type TrainerManagedProjectIdentity,
  type TrainerProjectAdoptionMode,
  type TrainerWorkspaceManifest,
} from '../core/trainerWorkspaceService';

type ProjectDiscoveryPayload = {
  discovery_id?: string;
  status?: string;
  available_decisions?: string[];
  availableDecisions?: string[];
  is_browse_only?: boolean;
  isBrowseOnly?: boolean;
};

type ProjectProvisioningPayload = {
  agent_session_id?: string;
  root_id?: string;
  rootId?: string;
  root_path?: string;
  rootPath?: string;
};

type ProjectClassificationResponse = {
  root_identity?: { rootId?: string; rootPath?: string };
  project_discovery?: ProjectDiscoveryPayload;
  folder_role?: FirstLookSummary['folderRole'];
  project_type_guess?: FirstLookSummary['projectTypeGuess'];
  subject_family?: FirstLookSummary['subjectFamily'];
  confidence?: number;
  why_this_guess?: string;
  entry_points?: string[];
  directory_anchors?: string[];
  core_modules_or_materials?: string[];
  risk_zones?: string[];
  training_opportunities?: string[];
  unknowns?: string[];
  recommended_next_step?: string;
  classification_method?: FirstLookSummary['classificationMethod'];
  classified_at?: string;
};

type ProjectAdoptionJobPayload = {
  job_id?: string;
  status?: string;
  progress?: number;
  progress_message?: string;
  retry_reason?: string;
  root_path?: string;
  workspace_id?: string;
  context_id?: string;
};

type ProjectDecisionResponse = {
  project_discovery?: ProjectDiscoveryPayload;
  project_provisioning?: ProjectProvisioningPayload;
  project_adoption_job?: ProjectAdoptionJobPayload;
  project_identity?: TrainerManagedProjectIdentity;
};

type ProjectProvisioningResponse = {
  project_provisioning?: ProjectProvisioningPayload;
};

type SelectedTrainerRoot = {
  canonicalRootPath: string;
  rootId?: string;
};

function runtimeDataPointerKey(rootPath: string): string {
  return `trainer.workspace.runtimeDataByRoot.v1:${encodeURIComponent(normalizeFsPath(rootPath))}`;
}

type WorkspaceClassificationRequest = {
  workspace_id: string;
  folder_path: string;
  root_id?: string;
  root_path: string;
  remote_name: string;
  workspace_file_snapshot?: WorkspaceFileSnapshot;
  response_language?: string;
};

type ReadOnlyAdmissionMode = Extract<TrainerProjectAdoptionMode, 'browse' | 'ignored'>;
type WorkspaceAdmissionErrorCode =
  | 'root_missing'
  | 'root_id_mismatch'
  | 'root_path_unavailable'
  | 'backend_unavailable';

type WorkspaceAdmissionFailure = {
  errorCode: WorkspaceAdmissionErrorCode;
  category: 'workspace_root' | 'backend';
  pathState: SidecarErrorPathState;
};

type WorkspaceAdmissionCommandPayload = {
  responseLanguage?: unknown;
  projectPath?: unknown;
};

function firstLookSummaryFromClassification(
  response: ProjectClassificationResponse,
): FirstLookSummary | undefined {
  if (!response.classified_at) {
    return undefined;
  }
  return {
    folderRole: response.folder_role ?? 'mixed_uncertain',
    projectTypeGuess: response.project_type_guess ?? 'unknown',
    subjectFamily: response.subject_family ?? 'code',
    confidence: response.confidence ?? 0,
    whyThisGuess: response.why_this_guess ?? '',
    entryPoints: response.entry_points ?? [],
    directoryAnchors: response.directory_anchors ?? [],
    coreModulesOrMaterials: response.core_modules_or_materials ?? [],
    riskZones: response.risk_zones ?? [],
    trainingOpportunities: response.training_opportunities ?? [],
    unknowns: response.unknowns ?? [],
    recommendedNextStep: response.recommended_next_step ?? '',
    classificationMethod: response.classification_method ?? 'heuristic',
    classifiedAt: response.classified_at,
  };
}

function workspaceAdmissionFailure(error: unknown): WorkspaceAdmissionFailure | undefined {
  const metadata = error instanceof SidecarHttpError
    ? error.metadata
    : typeof error === 'object' && error !== null && 'metadata' in error
      ? (error as { metadata?: { code?: string; category?: string; pathState?: SidecarErrorPathState } }).metadata ?? {}
      : {};
  const rawCode = metadata.code?.toLowerCase();
  if (rawCode === 'root_id_mismatch' || rawCode === 'root_path_unavailable' || rawCode === 'root_missing') {
    return {
      errorCode: rawCode,
      category: 'workspace_root',
      pathState: metadata.pathState ?? (rawCode === 'root_missing' ? 'missing' : 'unavailable'),
    };
  }
  if (rawCode === 'backend_unavailable') {
    return { errorCode: rawCode, category: 'backend', pathState: metadata.pathState ?? 'unknown' };
  }
  return undefined;
}

type AdmissionHostCopy = {
  addFailedPrefix: string;
  nextRootMissing: string;
  nextRootIdMismatch: string;
  nextRootPathUnavailable: string;
  nextBackendUnavailable: string;
  noFolderOpen: string;
  unresolvedFolder: (resolvedPath: string) => string;
  reopenAndRetry: string;
  rootMustBeLocal: string;
  projectSameAsRoot: string;
  pickWorkspaceFolderTitle: string;
  pickWorkspaceFolderPlaceholder: string;
  browseAnotherFolder: string;
  browseAnotherFolderDetail: string;
  chooseProjectTitle: string;
  chooseProjectOpenLabel: string;
  projectSelectionCancelled: string;
  rootSelectionCancelled: string;
  rootReady: (rootPath: string) => string;
  projectAdded: string;
  projectBrowseOnly: string;
  projectIgnored: string;
};

const ADMISSION_HOST_COPY: Record<ComposerLanguage, AdmissionHostCopy> = {
  'zh-CN': {
    addFailedPrefix: '无法添加项目',
    nextRootMissing: '请先选择唯一的 Trainer 学习文件夹（根目录）。',
    nextRootIdMismatch: '请重新选择与该路径匹配的 Trainer 学习文件夹后重试。',
    nextRootPathUnavailable: '请确认学习文件夹仍可访问，再重新选择并重试。',
    nextBackendUnavailable: '请确认工作区受信任且本地服务可用，然后重试。',
    noFolderOpen: '当前窗口没有打开任何项目文件夹。',
    unresolvedFolder: (p) => `未能解析当前项目目录（已检测到的工作区目录：${p}）。`,
    reopenAndRetry: '请选择或重新打开项目文件夹后点击“加入 Trainer”重试。',
    rootMustBeLocal: 'Trainer 学习文件夹（根目录）必须位于本机，不能选择远程路径；远程代码目录将自动关联到此本机根目录且保持零写入。',
    projectSameAsRoot: '当前打开的目录本身就是 Trainer 唯一的学习文件夹（根目录），不能同时作为子项目加入。请选择其他代码或学习项目文件夹。',
    pickWorkspaceFolderTitle: '选择要加入 Trainer 的工作区文件夹',
    pickWorkspaceFolderPlaceholder: '选择一个已打开的文件夹（所有数据仍保存在本机唯一的 Trainer 根目录）',
    browseAnotherFolder: '浏览其他文件夹…',
    browseAnotherFolderDetail: '从文件系统选择其他项目目录关联到当前 Trainer 根目录',
    chooseProjectTitle: '选择要加入 Trainer 的项目文件夹',
    chooseProjectOpenLabel: '加入此项目文件夹',
    projectSelectionCancelled: '已取消选择项目文件夹。',
    rootSelectionCancelled: '已取消选择 Trainer 学习文件夹。',
    rootReady: (p) => `Trainer 唯一学习文件夹已就绪：${p}。`,
    projectAdded: '当前项目已关联到本机唯一的 Trainer 根目录，项目目录本身零写入。',
    projectBrowseOnly: '当前项目将保持仅浏览模式，不会写入长期项目记忆。',
    projectIgnored: '已忽略当前项目；需要时可随时重新加入 Trainer。',
  },
  'en-US': {
    addFailedPrefix: 'Project could not be added',
    nextRootMissing: 'Choose the single Trainer learning folder (root) first.',
    nextRootIdMismatch: 'Re-select the Trainer learning folder that matches this path, then retry.',
    nextRootPathUnavailable: 'Verify that the learning folder is accessible, re-select it, and retry.',
    nextBackendUnavailable: 'Verify workspace trust and local backend availability, then retry.',
    noFolderOpen: 'Trainer could not resolve the current project folder (no workspace folder is open).',
    unresolvedFolder: (p) => `Trainer could not resolve the current project folder (resolved workspace folder: ${p}).`,
    reopenAndRetry: 'Reopen or choose a project folder, then click Add to Trainer again to retry.',
    rootMustBeLocal: 'The single Trainer learning folder (root) must be a local folder on this computer, not a remote URI.',
    projectSameAsRoot: 'This folder is already your single Trainer learning folder (root) and cannot be added as a project inside itself. Choose a separate project folder instead.',
    pickWorkspaceFolderTitle: 'Choose a workspace folder to add to Trainer',
    pickWorkspaceFolderPlaceholder: 'Pick an open folder (all Trainer data stays inside your single local root)',
    browseAnotherFolder: 'Browse another folder…',
    browseAnotherFolderDetail: 'Pick any other project folder to link into your single Trainer root',
    chooseProjectTitle: 'Choose Trainer Project Folder',
    chooseProjectOpenLabel: 'Use as Trainer Project',
    projectSelectionCancelled: 'Trainer project folder selection cancelled.',
    rootSelectionCancelled: 'Trainer Workspace Root selection cancelled.',
    rootReady: (p) => `Trainer Workspace is ready at ${p}.`,
    projectAdded: 'The current project was added to Trainer with an isolated project lane.',
    projectBrowseOnly: 'The current project will stay browse-only and will not receive long-lived project memory.',
    projectIgnored: 'The current project will be ignored by Trainer.',
  },
  'es-ES': {
    addFailedPrefix: 'No se pudo agregar el proyecto',
    nextRootMissing: 'Elige primero la carpeta única de aprendizaje de Trainer.',
    nextRootIdMismatch: 'Vuelve a elegir la carpeta de Trainer que coincide con esta ruta e inténtalo de nuevo.',
    nextRootPathUnavailable: 'Verifica que la carpeta de aprendizaje siga accesible, vuelve a elegirla e inténtalo de nuevo.',
    nextBackendUnavailable: 'Verifica la confianza del espacio de trabajo y el servicio local, luego reintenta.',
    noFolderOpen: 'No hay ninguna carpeta de proyecto abierta en esta ventana.',
    unresolvedFolder: (p) => `No se pudo resolver la carpeta actual del proyecto (carpeta detectada: ${p}).`,
    reopenAndRetry: 'Abre o elige una carpeta de proyecto y vuelve a pulsar Agregar a Trainer.',
    rootMustBeLocal: 'La carpeta raíz de Trainer debe estar en este equipo local, no en una ruta remota.',
    projectSameAsRoot: 'Esta carpeta ya es tu carpeta raíz única de Trainer. Elige una carpeta de proyecto distinta.',
    pickWorkspaceFolderTitle: 'Elige una carpeta del espacio de trabajo para agregar a Trainer',
    pickWorkspaceFolderPlaceholder: 'Todos los datos de Trainer se guardan únicamente en tu carpeta raíz local',
    browseAnotherFolder: 'Explorar otra carpeta…',
    browseAnotherFolderDetail: 'Elegir otra carpeta de proyecto para vincularla a tu raíz única de Trainer',
    chooseProjectTitle: 'Elegir carpeta de proyecto de Trainer',
    chooseProjectOpenLabel: 'Usar como proyecto de Trainer',
    projectSelectionCancelled: 'Se canceló la selección de la carpeta del proyecto.',
    rootSelectionCancelled: 'Se canceló la selección de la carpeta raíz de Trainer.',
    rootReady: (p) => `La carpeta raíz de Trainer está lista en ${p}.`,
    projectAdded: 'El proyecto se vinculó a la carpeta raíz única de Trainer sin escribir archivos en el proyecto.',
    projectBrowseOnly: 'El proyecto permanecerá en modo solo exploración sin memoria a largo plazo.',
    projectIgnored: 'Trainer ignorará este proyecto por ahora.',
  },
  'fr-FR': {
    addFailedPrefix: 'Impossible d’ajouter le projet',
    nextRootMissing: 'Choisissez d’abord l’unique dossier d’apprentissage Trainer.',
    nextRootIdMismatch: 'Sélectionnez à nouveau le dossier Trainer correspondant à ce chemin puis réessayez.',
    nextRootPathUnavailable: 'Vérifiez que le dossier racine est accessible, sélectionnez-le à nouveau puis réessayez.',
    nextBackendUnavailable: 'Vérifiez la confiance de l’espace de travail et la disponibilité du service local, puis réessayez.',
    noFolderOpen: 'Aucun dossier de projet n’est ouvert dans cette fenêtre.',
    unresolvedFolder: (p) => `Impossible de résoudre le dossier de projet actuel (dossier détecté : ${p}).`,
    reopenAndRetry: 'Ouvrez ou choisissez un dossier de projet puis cliquez à nouveau sur Ajouter à Trainer.',
    rootMustBeLocal: 'Le dossier racine unique de Trainer doit être un dossier local sur cet ordinateur, pas un chemin distant.',
    projectSameAsRoot: 'Ce dossier est déjà votre dossier racine unique de Trainer. Choisissez un autre dossier de projet.',
    pickWorkspaceFolderTitle: 'Choisir un dossier de l’espace de travail à ajouter à Trainer',
    pickWorkspaceFolderPlaceholder: 'Toutes les données Trainer restent dans votre unique dossier racine local',
    browseAnotherFolder: 'Parcourir un autre dossier…',
    browseAnotherFolderDetail: 'Sélectionner un autre dossier de projet à lier à votre racine Trainer',
    chooseProjectTitle: 'Choisir le dossier de projet Trainer',
    chooseProjectOpenLabel: 'Utiliser comme projet Trainer',
    projectSelectionCancelled: 'Sélection du dossier de projet annulée.',
    rootSelectionCancelled: 'Sélection du dossier racine Trainer annulée.',
    rootReady: (p) => `Le dossier racine Trainer est prêt : ${p}.`,
    projectAdded: 'Le projet a été lié à votre dossier racine unique Trainer sans rien écrire dans le projet.',
    projectBrowseOnly: 'Ce projet restera en consultation seule sans mémoire persistante.',
    projectIgnored: 'Ce projet sera ignoré par Trainer.',
  },
  'de-DE': {
    addFailedPrefix: 'Projekt konnte nicht hinzugefügt werden',
    nextRootMissing: 'Wählen Sie zuerst den einzigen Trainer-Lernordner (Stammordner).',
    nextRootIdMismatch: 'Wählen Sie den zu diesem Pfad passenden Trainer-Stammordner erneut aus und versuchen Sie es wieder.',
    nextRootPathUnavailable: 'Prüfen Sie, ob der Stammordner erreichbar ist, wählen Sie ihn erneut aus und versuchen Sie es wieder.',
    nextBackendUnavailable: 'Prüfen Sie die Arbeitsbereichs-Vertrauenswürdigkeit und den lokalen Dienst und versuchen Sie es erneut.',
    noFolderOpen: 'In diesem Fenster ist kein Projektordner geöffnet.',
    unresolvedFolder: (p) => `Der aktuelle Projektordner konnte nicht ermittelt werden (erkannter Ordner: ${p}).`,
    reopenAndRetry: 'Öffnen oder wählen Sie einen Projektordner und klicken Sie erneut auf Zu Trainer hinzufügen.',
    rootMustBeLocal: 'Der einzige Trainer-Stammordner muss ein lokaler Ordner auf diesem Computer sein, kein Remote-Pfad.',
    projectSameAsRoot: 'Dieser Ordner ist bereits Ihr einziger Trainer-Stammordner. Bitte wählen Sie einen separaten Projektordner.',
    pickWorkspaceFolderTitle: 'Arbeitsbereichsordner für Trainer auswählen',
    pickWorkspaceFolderPlaceholder: 'Alle Trainer-Daten bleiben ausschließlich in Ihrem lokalen Stammordner',
    browseAnotherFolder: 'Anderen Ordner durchsuchen…',
    browseAnotherFolderDetail: 'Einen anderen Projektordner mit dem lokalen Trainer-Stammordner verknüpfen',
    chooseProjectTitle: 'Trainer-Projektordner auswählen',
    chooseProjectOpenLabel: 'Als Trainer-Projekt verwenden',
    projectSelectionCancelled: 'Auswahl des Projektordners abgebrochen.',
    rootSelectionCancelled: 'Auswahl des Trainer-Stammordners abgebrochen.',
    rootReady: (p) => `Trainer-Stammordner ist bereit unter ${p}.`,
    projectAdded: 'Das Projekt wurde mit dem einzigen lokalen Trainer-Stammordner verknüpft (keine Schreibvorgänge im Projekt).',
    projectBrowseOnly: 'Dieses Projekt bleibt im Nur-Ansicht-Modus ohne dauerhafte Projekterinnerung.',
    projectIgnored: 'Dieses Projekt wird von Trainer ignoriert.',
  },
  'ja-JP': {
    addFailedPrefix: 'プロジェクトを追加できませんでした',
    nextRootMissing: 'まず唯一の Trainer 学習フォルダ（ルート）を選択してください。',
    nextRootIdMismatch: 'このパスに一致する Trainer 学習フォルダを選び直してから再試行してください。',
    nextRootPathUnavailable: '学習フォルダにアクセスできるか確認し、選び直して再試行してください。',
    nextBackendUnavailable: 'ワークスペースの信頼状態とローカルサービスを確認してから再試行してください。',
    noFolderOpen: 'このウィンドウではプロジェクトフォルダが開かれていません。',
    unresolvedFolder: (p) => `現在のプロジェクトフォルダを特定できませんでした（検出パス: ${p}）。`,
    reopenAndRetry: 'プロジェクトフォルダを開くか選択してから、もう一度「Trainer に追加」をクリックしてください。',
    rootMustBeLocal: 'Trainer の学習フォルダ（ルート）はこのローカル端末上のフォルダである必要があります。リモートパスは指定できません。',
    projectSameAsRoot: 'このフォルダ自体が Trainer の唯一の学習フォルダ（ルート）です。別のプロジェクトフォルダを選択してください。',
    pickWorkspaceFolderTitle: 'Trainer に追加するワークスペースフォルダを選択',
    pickWorkspaceFolderPlaceholder: 'すべての Trainer データは唯一のローカルルート内に保存されます',
    browseAnotherFolder: '別のフォルダを参照…',
    browseAnotherFolderDetail: '他のプロジェクトフォルダをローカルの Trainer ルートに紐付けます',
    chooseProjectTitle: 'Trainer プロジェクトフォルダを選択',
    chooseProjectOpenLabel: 'Trainer プロジェクトとして使用',
    projectSelectionCancelled: 'プロジェクトフォルダの選択がキャンセルされました。',
    rootSelectionCancelled: 'Trainer 学習フォルダの選択がキャンセルされました。',
    rootReady: (p) => `Trainer 学習フォルダの準備が完了しました: ${p}`,
    projectAdded: '現在のプロジェクトを唯一のローカル Trainer ルートに紐付けました（プロジェクト側への書き込みなし）。',
    projectBrowseOnly: '現在のプロジェクトは閲覧のみとなり、長期記憶は保存されません。',
    projectIgnored: '現在のプロジェクトは Trainer で無視されます。',
  },
  'ko-KR': {
    addFailedPrefix: '프로젝트를 추가할 수 없습니다',
    nextRootMissing: '먼저 유일한 Trainer 학습 폴더(루트)를 선택하세요.',
    nextRootIdMismatch: '이 경로와 일치하는 Trainer 학습 폴더를 다시 선택한 뒤 재시도하세요.',
    nextRootPathUnavailable: '학습 폴더에 접근 가능한지 확인하고 다시 선택한 뒤 재시도하세요.',
    nextBackendUnavailable: '작업 영역 신뢰 상태와 로컬 서비스를 확인한 뒤 재시도하세요.',
    noFolderOpen: '이 창에 열려 있는 프로젝트 폴더가 없습니다.',
    unresolvedFolder: (p) => `현재 프로젝트 폴더를 확인할 수 없습니다(감지된 경로: ${p}).`,
    reopenAndRetry: '프로젝트 폴더를 열거나 선택한 뒤 Trainer에 추가를 다시 클릭하세요.',
    rootMustBeLocal: 'Trainer 학습 폴더(루트)는 원격 경로가 아닌 이 로컬 컴퓨터의 폴더여야 합니다.',
    projectSameAsRoot: '이 폴더는 이미 유일한 Trainer 학습 폴더(루트)입니다. 별도의 프로젝트 폴더를 선택하세요.',
    pickWorkspaceFolderTitle: 'Trainer에 추가할 작업 영역 폴더 선택',
    pickWorkspaceFolderPlaceholder: '모든 Trainer 데이터는 유일한 로컬 루트 폴더에만 저장됩니다',
    browseAnotherFolder: '다른 폴더 찾아보기…',
    browseAnotherFolderDetail: '다른 프로젝트 폴더를 로컬 Trainer 루트에 연결합니다',
    chooseProjectTitle: 'Trainer 프로젝트 폴더 선택',
    chooseProjectOpenLabel: 'Trainer 프로젝트로 사용',
    projectSelectionCancelled: '프로젝트 폴더 선택이 취소되었습니다.',
    rootSelectionCancelled: 'Trainer 학습 폴더 선택이 취소되었습니다.',
    rootReady: (p) => `Trainer 학습 폴더가 준비되었습니다: ${p}`,
    projectAdded: '현재 프로젝트가 유일한 로컬 Trainer 루트에 연결되었습니다(프로젝트 폴더에 쓰기 없음).',
    projectBrowseOnly: '현재 프로젝트는 둘러보기 전용으로 유지되며 장기 기억이 저장되지 않습니다.',
    projectIgnored: '현재 프로젝트는 Trainer에서 무시됩니다.',
  },
  'pt-BR': {
    addFailedPrefix: 'Não foi possível adicionar o projeto',
    nextRootMissing: 'Escolha primeiro a pasta única de aprendizado do Trainer (raiz).',
    nextRootIdMismatch: 'Selecione novamente a pasta raiz do Trainer correspondente a este caminho e tente de novo.',
    nextRootPathUnavailable: 'Verifique se a pasta raiz continua acessível, selecione-a novamente e tente de novo.',
    nextBackendUnavailable: 'Verifique a confiança do espaço de trabalho e o serviço local e tente novamente.',
    noFolderOpen: 'Nenhuma pasta de projeto está aberta nesta janela.',
    unresolvedFolder: (p) => `Não foi possível resolver a pasta atual do projeto (pasta detectada: ${p}).`,
    reopenAndRetry: 'Abra ou escolha uma pasta de projeto e clique novamente em Adicionar ao Trainer.',
    rootMustBeLocal: 'A pasta raiz única do Trainer deve ser uma pasta local neste computador, não um caminho remoto.',
    projectSameAsRoot: 'Esta pasta já é sua pasta raiz única do Trainer. Escolha uma pasta de projeto separada.',
    pickWorkspaceFolderTitle: 'Escolha uma pasta do espaço de trabalho para adicionar ao Trainer',
    pickWorkspaceFolderPlaceholder: 'Todos os dados do Trainer ficam exclusivamente na sua pasta raiz local',
    browseAnotherFolder: 'Procurar outra pasta…',
    browseAnotherFolderDetail: 'Selecionar outra pasta de projeto para vincular à raiz única do Trainer',
    chooseProjectTitle: 'Escolher pasta do projeto Trainer',
    chooseProjectOpenLabel: 'Usar como projeto Trainer',
    projectSelectionCancelled: 'Seleção da pasta do projeto cancelada.',
    rootSelectionCancelled: 'Seleção da pasta raiz do Trainer cancelada.',
    rootReady: (p) => `Pasta raiz do Trainer pronta em ${p}.`,
    projectAdded: 'O projeto atual foi vinculado à pasta raiz única do Trainer sem gravar arquivos no projeto.',
    projectBrowseOnly: 'O projeto atual permanecerá apenas para visualização, sem memória de longo prazo.',
    projectIgnored: 'Este projeto será ignorado pelo Trainer.',
  },
};

function admissionHostCopy(language: ComposerLanguage | undefined): AdmissionHostCopy {
  return ADMISSION_HOST_COPY[language ?? 'en-US'] ?? ADMISSION_HOST_COPY['en-US'];
}

function workspaceAdmissionFailureMessage(
  failure: WorkspaceAdmissionFailure,
  language: ComposerLanguage | undefined,
): string {
  const copy = admissionHostCopy(language);
  const next = failure.errorCode === 'root_missing'
    ? copy.nextRootMissing
    : failure.errorCode === 'root_id_mismatch'
      ? copy.nextRootIdMismatch
      : failure.errorCode === 'root_path_unavailable'
        ? copy.nextRootPathUnavailable
        : copy.nextBackendUnavailable;
  return `${copy.addFailedPrefix} (${failure.errorCode}). ${next}`;
}

function safeWorkspaceAdmissionLog(failure: WorkspaceAdmissionFailure, statusCode?: number): string {
  return `[workspace-admission] status=${statusCode ?? 'unknown'} code=${failure.errorCode} category=${failure.category} path_state=${failure.pathState}`;
}

function resolveWorkspaceAdmissionResponseLanguage(
  context: CommandContext,
  payload?: WorkspaceAdmissionCommandPayload,
): ComposerLanguage | undefined {
  if (isComposerLanguage(payload?.responseLanguage)) {
    return payload.responseLanguage;
  }
  const workspaceLanguage = context.getHostState().bootstrap.memory.workspace?.responseLanguage;
  return isComposerLanguage(workspaceLanguage) ? workspaceLanguage : undefined;
}

async function withUserInitiatedProjectAdmission<T>(
  context: CommandContext,
  operation: () => Promise<T>,
): Promise<T> {
  const restoreMode = currentReadOnlyAdmissionMode(context);
  if (!restoreMode) {
    return operation();
  }

  context.sidecarClient.setTrainerAdmissionMode(undefined);
  try {
    return await operation();
  } finally {
    context.sidecarClient.setTrainerAdmissionMode(restoreMode);
  }
}

function pathsEqual(left: string, right: string): boolean {
  const normalize = (value: string): string => {
    // Windows drive/UNC paths are opaque absolute identifiers on POSIX hosts:
    // resolving them against the POSIX cwd would corrupt the comparison.
    if (/^([a-zA-Z]:[\/]|\\)/.test(value)) {
      const winNormalized = path.win32.normalize(value);
      return process.platform === 'win32'
        ? winNormalized.toLocaleLowerCase('en-US')
        : winNormalized;
    }
    const normalized = path.normalize(path.resolve(value));
    return process.platform === 'win32' ? normalized.toLocaleLowerCase('en-US') : normalized;
  };
  return normalize(left) === normalize(right);
}

function selectedRootFromManifest(manifest: TrainerWorkspaceManifest): SelectedTrainerRoot {
  return {
    // Windows drive/UNC roots are opaque absolute identifiers on POSIX hosts:
    // normalize them with filesystem-aware rules instead of path.resolve,
    // which would wrongly join them onto the POSIX cwd.
    canonicalRootPath: normalizeFsPath(manifest.canonicalRootPath),
    rootId: manifest.rootId,
  };
}

export function runtimeDataRootUnder(rootPath: string): string {
  // The managed runtime data root is a real filesystem location, so it is
  // always joined with the host separator rules: a Windows-style root keeps
  // the win32 join on Windows, while a POSIX host joins it with posix rules
  // so the runtime-data path stays a well-formed host path. Rendering the
  // joined location with backslashes on POSIX would hand the sidecar and the
  // runtime-data safety assertions a path the POSIX filesystem never uses.
  if (looksLikeWindowsAbsolutePath(rootPath)) {
    return process.platform === 'win32'
      ? path.win32.join(rootPath, TRAINER_WORKSPACE_RUNTIME_DATA_DIRECTORY)
      : path.posix.join(rootPath, TRAINER_WORKSPACE_RUNTIME_DATA_DIRECTORY);
  }
  return path.join(rootPath, TRAINER_WORKSPACE_RUNTIME_DATA_DIRECTORY);
}

async function readSelectedTrainerRoot(context: CommandContext, responseLanguage?: ComposerLanguage): Promise<SelectedTrainerRoot> {
  const manifest = await context.trainerWorkspace.readWorkspaceManifest();
  if (!manifest) {
    const lang = resolveHostCommandLanguage(context, responseLanguage);
    const configuredRoot = context.trainerWorkspace.getRoot();
    throw new Error(
      configuredRoot
        ? hostCommandCopy(lang, 'rootUnavailablePathError', { path: configuredRoot })
        : hostCommandCopy(lang, 'rootUnavailableMissingError'),
    );
  }
  return selectedRootFromManifest(manifest);
}

function unresolvableProjectPathResult(
  context: CommandContext,
  responseLanguage?: ComposerLanguage,
): CommandExecutionResult {
  const language = resolveWorkspaceAdmissionResponseLanguage(context, { responseLanguage });
  const copy = admissionHostCopy(language);
  const failure: WorkspaceAdmissionFailure = {
    errorCode: 'root_missing',
    category: 'workspace_root',
    pathState: 'missing',
  };
  const workspace = context.getHostState().workspace;
  const resolvedPath = workspace.activeWorkspaceRoot ?? workspace.workspaceFolder;
  const resolutionDetail = resolvedPath
    ? copy.unresolvedFolder(resolvedPath)
    : copy.noFolderOpen;
  return {
    ok: false,
    message: `${workspaceAdmissionFailureMessage(failure, language)} ${resolutionDetail} ${copy.reopenAndRetry}`,
    data: failure,
  };
}

function serverRootPath(response: ProjectDecisionResponse, lang: ComposerLanguage): string | undefined {
  const identityPath = response.project_identity?.canonicalRootPath;
  const provisioningPath =
    response.project_provisioning?.root_path ?? response.project_provisioning?.rootPath;
  if (identityPath && provisioningPath && !pathsEqual(identityPath, provisioningPath)) {
    throw new Error(hostCommandCopy(lang, 'backendConflictingRootPaths'));
  }
  return identityPath ?? provisioningPath;
}

function serverRootId(response: ProjectDecisionResponse, lang: ComposerLanguage): string | undefined {
  const identityId = response.project_identity?.rootId;
  const provisioningId = response.project_provisioning?.root_id ?? response.project_provisioning?.rootId;
  if (identityId && provisioningId && identityId !== provisioningId) {
    throw new Error(hostCommandCopy(lang, 'backendConflictingRootIds'));
  }
  return identityId ?? provisioningId;
}

function assertProvisioningMatchesSelectedRoot(
  response: ProjectDecisionResponse,
  selectedRoot: SelectedTrainerRoot,
  lang: ComposerLanguage,
): void {
  const returnedRootPath = serverRootPath(response, lang);
  const returnedRootId = serverRootId(response, lang);
  if (!returnedRootPath || !pathsEqual(returnedRootPath, selectedRoot.canonicalRootPath)) {
    throw new Error(hostCommandCopy(lang, 'backendWrongRootPath'));
  }
  if (!returnedRootId) {
    throw new Error(hostCommandCopy(lang, 'backendMissingRootIdentity'));
  }
  if (selectedRoot.rootId && selectedRoot.rootId !== returnedRootId) {
    throw new Error(hostCommandCopy(lang, 'workspaceChangedDuringAdd'));
  }
}

export async function chooseTrainerWorkspaceRootCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const lang = resolveHostCommandLanguage(context);
  if (!(await context.trustGuard.ensureTrusted('set up the Trainer workspace root'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredSetRoot') };
  }

  const language = resolveWorkspaceAdmissionResponseLanguage(context);
  const copy = admissionHostCopy(language);
  const currentRoot = context.trainerWorkspace.getRoot();
  const defaultLocalPath = currentRoot || os.homedir();
  const defaultUri =
    defaultLocalPath && typeof vscode.Uri?.file === 'function'
      ? vscode.Uri.file(defaultLocalPath)
      : undefined;
  const picks = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    defaultUri,
    openLabel: hostCommandCopy(lang, 'pickRootOpenLabel'),
    title: hostCommandCopy(lang, 'pickRootTitle'),
  });
  const pickedUri = picks?.[0];
  if (pickedUri && pickedUri.scheme && pickedUri.scheme !== 'file') {
    return {
      ok: false,
      message: copy.rootMustBeLocal,
    };
  }
  let rootPath = pickedUri?.fsPath;
  if (!rootPath) {
    // The native folder dialog can be unusable in some window setups (remote
    // windows, restricted mode). Offer a typed-path fallback so first-time
    // setup never dead-ends: a missing folder is created for the learner.
    const typed = await vscode.window.showInputBox({
      prompt: hostCommandCopy(lang, 'pickRootPromptFallback'),
      placeHolder: '/Users/<you>/trainer-learning',
      ignoreFocusOut: true,
    });
    rootPath = typed?.trim();
    if (rootPath) {
      try {
        fs.mkdirSync(rootPath, { recursive: true });
      } catch (error) {
        return {
          ok: false,
          message: hostCommandCopy(lang, 'pickRootCreateFailed', {
            path: rootPath,
            error: error instanceof Error ? error.message : String(error),
          }),
        };
      }
    }
  }
  if (!rootPath) {
    return { ok: false, message: hostCommandCopy(lang, 'pickRootCancelled') };
  }

  let manifest: TrainerWorkspaceManifest;
  let restartedSidecar: boolean;
  const workspaceFolder = context.getHostState().workspace.workspaceFolder;
  const previousDataFolder = context.sidecarManager
    ?.getManagedDataFolderSnapshot?.(workspaceFolder)
    ?.effectivePath;
  const targetDefaultRuntime = runtimeDataRootUnder(rootPath);
  const globalStorageFsPath = context.extensionContext?.globalStorageUri?.fsPath;
  const globalStorageSidecarRoot = globalStorageFsPath
    ? path.join(globalStorageFsPath, 'sidecar')
    : undefined;
  const normalizedPrev = previousDataFolder ? normalizeFsPath(previousDataFolder) : undefined;
  const normalizedGlobalSidecar = globalStorageSidecarRoot
    ? normalizeFsPath(globalStorageSidecarRoot)
    : undefined;
  const prevInsideGlobalStorage = Boolean(
    normalizedPrev &&
      normalizedGlobalSidecar &&
      (normalizedPrev === normalizedGlobalSidecar ||
        normalizedPrev.startsWith(`${normalizedGlobalSidecar}${path.sep}`) ||
        normalizedPrev.startsWith(`${normalizedGlobalSidecar}/`)),
  );
  const hasTrainerDb = (dir: string): boolean =>
    fs.existsSync(path.join(dir, 'trainer.sqlite3')) || fs.existsSync(path.join(dir, 'trainer.db'));
  const shouldMigrateFromGlobalStorage = Boolean(
    previousDataFolder &&
      prevInsideGlobalStorage &&
      hasTrainerDb(previousDataFolder) &&
      !hasTrainerDb(targetDefaultRuntime),
  );
  try {
    const selection = await runWithQuiescentManagedData(
      context,
      async () => context.trainerWorkspace.selectRoot(rootPath as string),
      (selectedManifest) => context.extensionContext.globalState.get<string>(
        runtimeDataPointerKey(selectedManifest.rootPath),
      ) ?? runtimeDataRootUnder(selectedManifest.rootPath),
      { copyExistingData: shouldMigrateFromGlobalStorage },
    );
    manifest = selection.result;
    restartedSidecar = selection.restartedSidecar;
  } catch (error) {
    return {
      ok: false,
      message: hostCommandCopy(lang, 'pickRootFailed', {
        error: error instanceof Error ? error.message : String(error),
      }),
    };
  }
  await patchTrainerWorkspaceAdmission(context);
  await rehydrateAfterWorkspaceDataTransfer(context, restartedSidecar);
  return {
    ok: true,
    message: hostCommandCopy(lang, 'pickRootReady', { path: manifest.rootPath }),
    data: manifest,
  };
}

export async function migrateTrainerWorkspaceRootCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const lang = resolveHostCommandLanguage(context);
  if (!(await context.trustGuard.ensureTrusted('migrate the Trainer workspace root'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredMigrateRoot') };
  }

  const targetRoot = await pickTrainerWorkspaceDirectory({
    currentRoot: context.trainerWorkspace.getRoot(),
    openLabel: hostCommandCopy(lang, 'migrateRootOpenLabel'),
    title: hostCommandCopy(lang, 'migrateRootTitle'),
  });
  if (!targetRoot) {
    return { ok: false, message: hostCommandCopy(lang, 'migrateRootCancelled') };
  }

  const { result: migration, restartedSidecar } = await runWithQuiescentManagedData(
    context,
    async (managedDataRoot) =>
      context.trainerWorkspace.migrateWorkspaceRoot(targetRoot, { managedDataRoot }),
    (result) => result.managedDataRoot,
  );
  await patchTrainerWorkspaceAdmission(context);
  await rehydrateAfterWorkspaceDataTransfer(context, restartedSidecar);
  return {
    ok: true,
    message: hostCommandCopy(lang, 'migrateRootDone', { target: migration.targetRoot }),
    data: migration,
  };
}

export async function backupTrainerWorkspaceCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const lang = resolveHostCommandLanguage(context);
  if (!(await context.trustGuard.ensureTrusted('back up the Trainer workspace root'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredBackupRoot') };
  }

  const backupRoot = await pickTrainerWorkspaceDirectory({
    currentRoot: context.trainerWorkspace.getRoot(),
    openLabel: hostCommandCopy(lang, 'backupRootOpenLabel'),
    title: hostCommandCopy(lang, 'backupRootTitle'),
  });
  if (!backupRoot) {
    return { ok: false, message: hostCommandCopy(lang, 'backupRootCancelled') };
  }

  const { result: backup, restartedSidecar } = await runWithQuiescentManagedData(
    context,
    async (managedDataRoot) => context.trainerWorkspace.backupWorkspace(backupRoot, { managedDataRoot }),
  );
  await rehydrateAfterWorkspaceDataTransfer(context, restartedSidecar, false);
  return {
    ok: true,
    message: hostCommandCopy(lang, 'backupRootCreated', { target: backup.backupRoot }),
    data: backup,
  };
}

export async function restoreTrainerWorkspaceBackupCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const lang = resolveHostCommandLanguage(context);
  if (!(await context.trustGuard.ensureTrusted('restore a Trainer workspace backup'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredRestoreRoot') };
  }

  const backupRoot = await pickTrainerWorkspaceDirectory({
    openLabel: hostCommandCopy(lang, 'restorePickBackupOpenLabel'),
    title: hostCommandCopy(lang, 'restorePickBackupTitle'),
  });
  if (!backupRoot) {
    return { ok: false, message: hostCommandCopy(lang, 'restoreCancelled') };
  }

  const targetRoot = await pickTrainerWorkspaceDirectory({
    currentRoot: context.trainerWorkspace.getRoot(),
    openLabel: hostCommandCopy(lang, 'restoreTargetOpenLabel'),
    title: hostCommandCopy(lang, 'restoreTargetTitle'),
  });
  if (!targetRoot) {
    return { ok: false, message: hostCommandCopy(lang, 'restoreCancelled') };
  }

  const { result: restoration, restartedSidecar } = await runWithQuiescentManagedData(
    context,
    async () => context.trainerWorkspace.restoreWorkspaceBackup(backupRoot, targetRoot),
    (result) => result.managedDataRoot,
  );
  await patchTrainerWorkspaceAdmission(context);
  await rehydrateAfterWorkspaceDataTransfer(context, restartedSidecar);
  return {
    ok: true,
    message: hostCommandCopy(lang, 'restoreDone', { target: restoration.targetRoot }),
    data: restoration,
  };
}

async function runWithQuiescentManagedData<T>(
  context: CommandContext,
  operation: (managedDataRoot: string) => Promise<T>,
  resolveNextManagedDataRoot?: (result: T) => string | undefined,
  options: { copyExistingData?: boolean } = {},
): Promise<{ result: T; restartedSidecar: boolean }> {
  const workspaceFolder = context.getHostState().workspace.workspaceFolder;
  const currentData = context.sidecarManager.getManagedDataFolderSnapshot(workspaceFolder);
  const priorLifecycle = context.sidecarManager.getStatus().lifecycle;
  const wasReady = priorLifecycle === 'ready' || priorLifecycle === 'starting';
  const previousWorkspaceRoot = context.trainerWorkspace.getRoot();
  if (previousWorkspaceRoot) {
    await context.extensionContext.globalState.update(
      runtimeDataPointerKey(previousWorkspaceRoot), currentData.effectivePath,
    );
  }
  let operationFailure: unknown;

  const lang = resolveHostCommandLanguage(context);
  if (wasReady) {
    await context.setSessionId(undefined);
    await context.sidecarManager.stop();
  }

  try {
    const result = await operation(currentData.effectivePath);
    if (resolveNextManagedDataRoot) {
      const nextManagedDataRoot = resolveNextManagedDataRoot(result);
      if (!nextManagedDataRoot) {
        throw new Error(hostCommandCopy(lang, 'rootTransferMissingRuntimeData'));
      }
      const nextManifest = await context.trainerWorkspace.readWorkspaceManifest();
      await context.sidecarManager.setManagedDataRootScope?.({
        rootId: nextManifest?.rootId,
        rootPath: nextManifest?.rootPath ?? context.trainerWorkspace.getRoot(),
        legacyWorkspaceFolder: workspaceFolder,
      });
      await context.sidecarManager.configureManagedDataFolder(nextManagedDataRoot, workspaceFolder, {
        allowExistingTarget: true,
        ...options,
      });
      const nextRoot = context.trainerWorkspace.getRoot();
      if (nextRoot) {
        await context.extensionContext.globalState.update(
          runtimeDataPointerKey(nextRoot), nextManagedDataRoot,
        );
      }
    }
    return { result, restartedSidecar: wasReady };
  } catch (error) {
    operationFailure = error;
    if (resolveNextManagedDataRoot) {
      try {
        await context.trainerWorkspace.rollbackWorkspaceRoot(previousWorkspaceRoot);
        const previousManifest = await context.trainerWorkspace.readWorkspaceManifest();
        await context.sidecarManager.setManagedDataRootScope?.({
          rootId: previousManifest?.rootId,
          rootPath: previousManifest?.rootPath ?? previousWorkspaceRoot,
          legacyWorkspaceFolder: workspaceFolder,
        });
        await context.sidecarManager.configureManagedDataFolder(currentData.effectivePath, workspaceFolder, {
          allowExistingTarget: true,
          copyExistingData: false,
        });
        await patchTrainerWorkspaceAdmission(context);
      } catch (rollbackError) {
        context.outputChannel.appendLine(
          `[workspace] Transfer rollback failed: ${rollbackError instanceof Error ? rollbackError.message : String(rollbackError)}`,
        );
      }
    }
    throw error;
  } finally {
    if (wasReady) {
      try {
        const status = await context.sidecarManager.restart();
        if (!operationFailure && status.lifecycle !== 'ready') {
          throw new Error(status.detail ?? hostCommandCopy(lang, 'backendRestartFailedAfterTransfer'));
        }
      } catch (error) {
        if (!operationFailure) {
          throw error;
        }
      }
    }
  }
}

async function rehydrateAfterWorkspaceDataTransfer(
  context: CommandContext,
  restartedSidecar: boolean,
  dataChanged = true,
): Promise<void> {
  const incomingWorkspaceId = incomingWorkspaceIdAfterAdmission(
    context,
    context.getHostState().bootstrap.memory.workspace?.trainerWorkspace,
  );
  await context.patchWorkbenchData(
    dataChanged
      ? resetWorkbenchAfterRuntimeDataChange(context.getHostState(), incomingWorkspaceId)
      : failClosedWorkbenchAfterWorkspaceTransfer(context.getHostState().bootstrap, incomingWorkspaceId),
  );
  if (!restartedSidecar) {
    return;
  }
  await context.setSessionId(undefined);
  await rehydrateWorkbenchRuntime(context, {
    ensureSidecar: false,
    syncWorkbench: true,
  });
  await context.patchWorkbenchData(
    failClosedWorkbenchAfterWorkspaceTransfer(context.getHostState().bootstrap, incomingWorkspaceId),
  );
}

export async function adoptWorkspaceProjectCommand(
  context: CommandContext,
  payload?: WorkspaceAdmissionCommandPayload,
): Promise<CommandExecutionResult> {
  return setCurrentWorkspaceProjectAdmission(
    context,
    'managed',
    resolveWorkspaceAdmissionResponseLanguage(context, payload),
    typeof payload?.projectPath === 'string' ? payload.projectPath : undefined,
  );
}

function uriToProjectPath(uri: vscode.Uri | undefined): string | undefined {
  if (!uri) {
    return undefined;
  }
  if (uri.scheme && uri.scheme !== 'file') {
    return uri.toString();
  }
  return uri.fsPath;
}

export async function chooseWorkspaceProjectCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const lang = resolveHostCommandLanguage(context);
  if (!(await context.trustGuard.ensureTrusted('choose the Trainer project folder'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredChooseProject') };
  }
  const language = resolveWorkspaceAdmissionResponseLanguage(context);
  const copy = admissionHostCopy(language);

  let projectPath: string | undefined;
  const openFolders = vscode.workspace?.workspaceFolders ?? [];
  if (openFolders.length > 1 && typeof vscode.window?.showQuickPick === 'function') {
    const BROWSE_SENTINEL = '__trainer_browse_another_folder__';
    const items = [
      ...openFolders
        .map((folder) => {
          const folderPath = uriToProjectPath(folder.uri);
          return folderPath
            ? {
                label: folder.name || basenameFs(folderPath) || folderPath,
                description: folderPath,
                projectPath: folderPath,
              }
            : undefined;
        })
        .filter((item): item is { label: string; description: string; projectPath: string } => Boolean(item)),
      {
        label: copy.browseAnotherFolder,
        description: '',
        detail: copy.browseAnotherFolderDetail,
        projectPath: BROWSE_SENTINEL,
      },
    ];
    const selected = await vscode.window.showQuickPick(items, {
      title: copy.pickWorkspaceFolderTitle,
      placeHolder: copy.pickWorkspaceFolderPlaceholder,
      ignoreFocusOut: true,
    });
    if (!selected) {
      return { ok: false, cancelled: true, message: copy.projectSelectionCancelled };
    }
    if (selected.projectPath !== BROWSE_SENTINEL) {
      projectPath = selected.projectPath;
    }
  }

  if (!projectPath) {
    const picks = await vscode.window.showOpenDialog({
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      openLabel: copy.chooseProjectOpenLabel,
      title: copy.chooseProjectTitle,
    });
    projectPath = uriToProjectPath(picks?.[0]);
  }
  if (!projectPath) {
    return { ok: false, cancelled: true, message: copy.projectSelectionCancelled };
  }
  return setCurrentWorkspaceProjectAdmission(context, 'managed', language, projectPath);
}

export async function browseWorkspaceProjectCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  return setCurrentWorkspaceProjectAdmission(context, 'browse');
}

export async function ignoreWorkspaceProjectCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  return setCurrentWorkspaceProjectAdmission(context, 'ignored');
}

export async function deleteWorkspaceProjectCommand(
  context: CommandContext,
  payload?: WorkspaceAdmissionCommandPayload,
): Promise<CommandExecutionResult> {
  const lang = resolveHostCommandLanguage(context, payload?.responseLanguage);
  if (!(await context.trustGuard.ensureTrusted('delete the Trainer project'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredDeleteProject') };
  }

  const projectPath =
    (typeof payload?.projectPath === 'string' ? payload.projectPath.trim() : '') ||
    resolveCurrentTrainerProjectPath(context.getHostState().workspace);
  if (!projectPath) {
    return {
      ok: false,
      message: hostCommandCopy(lang, 'deleteProjectOpenTarget'),
    };
  }

  const existing = await context.trainerWorkspace.getProject(projectPath);
  if (!existing || existing.adoptionMode !== 'managed') {
    return {
      ok: false,
      message: hostCommandCopy(lang, 'deleteProjectNotManaged'),
    };
  }

  const deleteButton = hostCommandCopy(lang, 'deleteProjectConfirmButton');
  const confirmed = await vscode.window.showWarningMessage(
    hostCommandCopy(lang, 'deleteProjectConfirmPrompt'),
    { modal: true },
    deleteButton,
  );
  if (confirmed !== deleteButton) {
    return { ok: false, cancelled: true, message: hostCommandCopy(lang, 'deleteProjectCancelled') };
  }

  const deleted = await context.trainerWorkspace.deleteManagedProject(projectPath);
  if (context.trustGuard.getPreferredWorkspaceProject?.() === projectPath) {
    context.trustGuard.setPreferredWorkspaceProject?.(undefined);
  }
  const liveDeleted = deletedProjectIsLiveOnWorkbench(context.getHostState().bootstrap, deleted);
  const excludedWorkspaceIds = await excludeDeletedProjectFromTransferPromotion(context, deleted);
  const demotedBeforeAdmission = applyExcludedWorkspacesToBootstrap(
    context.getHostState().bootstrap,
    excludedWorkspaceIds,
  );
  if (liveDeleted) {
    await patchWorkbenchAfterDeletedLiveProject(context);
  } else {
    await patchTrainerWorkspaceAdmission(context);
  }
  if (!liveDeleted && demotedBeforeAdmission) {
    const current = context.getHostState().bootstrap;
    await context.patchWorkbenchData({
      memory: {
        ...current.memory,
        ...(demotedBeforeAdmission.memory ?? {}),
        workspace: {
          ...current.memory.workspace,
          ...(demotedBeforeAdmission.memory?.workspace ?? {}),
          latestTransferState: demotedBeforeAdmission.memory?.workspace?.latestTransferState,
        },
      },
      workspaceTrainingState: {
        ...(current.workspaceTrainingState ?? {}),
        ...(demotedBeforeAdmission.workspaceTrainingState ?? {}),
        latestTransferState: demotedBeforeAdmission.workspaceTrainingState?.latestTransferState,
      },
    });
  }
  return {
    ok: true,
    message: hostCommandCopy(lang, 'deleteProjectDone'),
    data: deleted,
  };
}

export async function retryWorkspaceAdmissionCommand(
  context: CommandContext,
  payload?: WorkspaceAdmissionCommandPayload,
): Promise<CommandExecutionResult> {
  return adoptWorkspaceProjectCommand(context, payload);
}

export async function continueWorkspaceAdmissionCommand(
  context: CommandContext,
  payload?: WorkspaceAdmissionCommandPayload,
): Promise<CommandExecutionResult> {
  return adoptWorkspaceProjectCommand(context, payload);
}

export async function abandonWorkspaceAdmissionCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const lang = resolveHostCommandLanguage(context);
  const projectPath = resolveCurrentTrainerProjectPath(context.getHostState().workspace);
  if (!projectPath) return { ok: false, message: hostCommandCopy(lang, 'abandonReconcileNeedProject') };
  await context.trainerWorkspace.abandonManagedProvisioning(projectPath);
  await patchTrainerWorkspaceAdmission(context);
  return { ok: true, message: hostCommandCopy(lang, 'abandonReconcileDone') };
}

function incomingWorkspaceIdAfterAdmission(
  context: CommandContext,
  trainerWorkspace: NonNullable<BootstrapData['memory']['workspace']>['trainerWorkspace'],
): string | undefined {
  if (trainerWorkspace?.status === 'managed') {
    const contextId = trainerWorkspace.contextId?.trim();
    if (contextId) {
      return contextId;
    }
  }
  if (
    trainerWorkspace?.status === 'ignored' ||
    trainerWorkspace?.status === 'browse' ||
    (trainerWorkspace?.status === 'root-missing' && !trainerWorkspace.projectPath)
  ) {
    return undefined;
  }
  return (
    resolveSovereignWorkspaceRootPath(context.getHostState().workspace) ??
    trainerWorkspace?.canonicalProjectPath ??
    trainerWorkspace?.projectPath ??
    trainerWorkspace?.rootPath
  );
}

function uniqueWorkspaceScopeIds(...values: Array<string | undefined>): string[] {
  const ids: string[] = [];
  for (const value of values) {
    const cleaned = value?.trim();
    if (!cleaned || ids.includes(cleaned)) {
      continue;
    }
    ids.push(cleaned);
  }
  return ids;
}

async function excludeDeletedProjectFromTransferPromotion(
  context: CommandContext,
  deleted: {
    projectId?: string;
    contextId?: string;
    projectPath?: string;
    canonicalProjectPath?: string;
  },
): Promise<string[]> {
  const current = context.getHostState().bootstrap;
  const workspaceIds = uniqueWorkspaceScopeIds(
    deleted.contextId,
    deleted.projectId,
    deleted.projectPath,
    deleted.canonicalProjectPath,
    deletedProjectIsLiveOnWorkbench(current, deleted) ? current.memory.workspace?.workspaceId : undefined,
  );
  await postOrQueueTransferPromotionScope(
    context,
    'exclude',
    workspaceIds,
    'Trainer kept the project deleted, but could not exclude leftover transfer scenes',
  );
  return workspaceIds;
}

async function includeAdoptedProjectInTransferPromotion(
  context: CommandContext,
  identity: TrainerManagedProjectIdentity | undefined,
  projectPath: string,
): Promise<void> {
  await postOrQueueTransferPromotionScope(
    context,
    'include',
    uniqueWorkspaceScopeIds(
      identity?.contextId,
      identity?.projectId,
      identity?.canonicalProjectPath,
      projectPath,
    ),
    'Trainer added the project, but could not restore leftover transfer scenes to the promotion set',
  );
}

export { flushPendingTransferPromotionScope };

function deletedProjectIsLiveOnWorkbench(
  current: BootstrapData,
  deleted: { projectId?: string; contextId?: string; projectPath?: string; canonicalProjectPath?: string },
): boolean {
  const admission = current.memory.workspace?.trainerWorkspace;
  const liveIds = [
    admission?.projectId,
    admission?.contextId,
    admission?.projectPath,
    admission?.canonicalProjectPath,
    current.memory.workspace?.workspaceId,
    current.workspaceTrainingState?.workspaceId,
  ]
    .map((value) => value?.trim())
    .filter((value): value is string => Boolean(value));
  const deletedIds = [
    deleted.projectId,
    deleted.contextId,
    deleted.projectPath,
    deleted.canonicalProjectPath,
  ]
    .map((value) => value?.trim())
    .filter((value): value is string => Boolean(value));
  return deletedIds.some((deletedId) =>
    liveIds.some((liveId) => liveId === deletedId || path.resolve(liveId) === path.resolve(deletedId)),
  );
}

async function patchWorkbenchAfterDeletedLiveProject(context: CommandContext): Promise<void> {
  const current = context.getHostState().bootstrap;
  const failClosed = failClosedWorkbenchAfterWorkspaceTransfer(current, undefined);
  const trainerWorkspace = await resolveTrainerWorkspaceAdmission(
    context.trainerWorkspace,
    context.getHostState().workspace,
  );
  const trainerProjects = await resolveTrainerProjectsList(
    context.trainerWorkspace,
    context.getHostState().workspace,
  );
  const resourceSandbox = context.sidecarManager.getManagedDataFolderSnapshot(
    context.getHostState().workspace.workspaceFolder,
  );
  context.sidecarClient.setTrainerAdmissionMode?.(trainerWorkspace?.status);
  await context.patchWorkbenchData({
    ...failClosed,
    memory: {
      ...failClosed.memory,
      workspace: {
        ...(failClosed.memory?.workspace ?? {}),
        trainerWorkspace,
        trainerProjects,
        resourceSandbox,
      },
    },
  } as Partial<BootstrapData>);
  await context.setSessionId(undefined);
}

export async function patchTrainerWorkspaceAdmission(
  context: CommandContext,
  preferredProjectPath?: string,
): Promise<void> {
  const current = context.getHostState().bootstrap;
  const trainerWorkspace = await resolveTrainerWorkspaceAdmission(
    context.trainerWorkspace,
    context.getHostState().workspace,
    preferredProjectPath,
  );
  const trainerProjects = await resolveTrainerProjectsList(
    context.trainerWorkspace,
    context.getHostState().workspace,
  );
  const incomingWorkspaceId = incomingWorkspaceIdAfterAdmission(context, trainerWorkspace);
  const failClosed = failClosedWorkbenchAfterWorkspaceTransfer(current, incomingWorkspaceId);
  const resourceSandbox = context.sidecarManager.getManagedDataFolderSnapshot(
    context.getHostState().workspace.workspaceFolder,
  );
  context.sidecarClient.setTrainerAdmissionMode?.(trainerWorkspace?.status);
  await context.patchWorkbenchData({
    ...failClosed,
    memory: {
      ...failClosed.memory,
      workspace: {
        ...(failClosed.memory?.workspace ?? {}),
        trainerWorkspace,
        trainerProjects,
        resourceSandbox,
      },
    },
  } as Partial<BootstrapData>);
  await patchProjectFoundFirstLookSummary(context, trainerWorkspace);
}

async function patchProjectFoundFirstLookSummary(
  context: CommandContext,
  trainerWorkspace: NonNullable<BootstrapData['memory']['workspace']>['trainerWorkspace'],
): Promise<void> {
  const projectPath = trainerWorkspace?.projectPath;
  if (trainerWorkspace?.status !== 'project-found' || !projectPath || !trainerWorkspace.rootPath) {
    return;
  }

  let selectedRoot: SelectedTrainerRoot;
  try {
    selectedRoot = await readSelectedTrainerRoot(context);
  } catch (error) {
    context.outputChannel.appendLine(
      `Trainer First Look skipped because the selected workspace root is unavailable: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
    return;
  }
  if (
    !pathsEqual(selectedRoot.canonicalRootPath, trainerWorkspace.rootPath) ||
    (trainerWorkspace.rootId && selectedRoot.rootId && trainerWorkspace.rootId !== selectedRoot.rootId)
  ) {
    return;
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    context.outputChannel.appendLine(
      `Trainer First Look skipped because the backend is unavailable: ${
        status.detail ?? 'sidecar did not report a ready port'
      }`,
    );
    return;
  }

  try {
    const responseLanguage = resolveWorkspaceAdmissionResponseLanguage(context);
    const workspaceFileSnapshot = await buildWorkspaceFileSnapshot(context);
    const classification = await classifyProjectForAdmission(context, status.port, {
      workspace_id: projectPath,
      folder_path: projectPath,
      root_id: selectedRoot.rootId,
      root_path: selectedRoot.canonicalRootPath,
      remote_name: context.getHostState().workspace.remoteName ?? '',
      ...(workspaceFileSnapshot ? { workspace_file_snapshot: workspaceFileSnapshot } : {}),
      ...(responseLanguage ? { response_language: responseLanguage } : {}),
    });
    const firstLookSummary = firstLookSummaryFromClassification(classification);
    if (!firstLookSummary) {
      context.outputChannel.appendLine('Trainer First Look skipped because the backend returned no summary.');
      return;
    }

    const current = context.getHostState().bootstrap;
    await context.patchWorkbenchData({
      memory: {
        ...current.memory,
        workspaceUnderstanding: {
          ...current.memory.workspaceUnderstanding,
          firstLookSummary,
        },
      },
    } as Partial<BootstrapData>);
  } catch (error) {
    const failure = workspaceAdmissionFailure(error);
    context.outputChannel.appendLine(
      failure
        ? `Trainer First Look classification failed: ${safeWorkspaceAdmissionLog(
            failure,
            error instanceof SidecarHttpError ? error.statusCode : undefined,
          )}`
        : 'Trainer First Look classification failed: backend error details were omitted.',
    );
  }
}

/**
 * A project admitted from the pre-admission folder keeps the same physical
 * project but changes its runtime workspace id to the managed project context.
 * A connection test that just passed for that folder must follow the project,
 * otherwise the learner is forced to re-test the same connection immediately
 * after choosing "加入 Trainer". Only a passed test for the same provider
 * fingerprint and profile is carried; cross-workspace results still never leak.
 */
async function carryProviderTestAcrossProjectAdmission(context: CommandContext): Promise<void> {
  const config = context.providerStore.getConfig();
  if (!config) {
    return;
  }
  const { workspaceId: targetWorkspaceId, legacyWorkspaceId } = getRuntimeWorkspaceContext(context);
  const sourceWorkspaceId = legacyWorkspaceId?.trim();
  if (!sourceWorkspaceId || !targetWorkspaceId || sourceWorkspaceId === targetWorkspaceId) {
    return;
  }
  const previous = context.providerStore.getLastTestResult(config, {
    workspaceId: sourceWorkspaceId,
    providerProfileId: config.profileId,
  });
  if (!previous?.ok) {
    return;
  }
  const carried = await context.providerStore.saveLastTestResult(config, previous, {
    workspaceId: targetWorkspaceId,
    providerProfileId: config.profileId,
  });
  // The next bootstrap snapshot reads the default store scope; point it at the
  // managed project context so providerConfig.lastTestResult carries the new
  // workspaceId the webview scopes against.
  context.providerStore.setActiveWorkspaceId(targetWorkspaceId);
  await context.patchWorkbenchData({
    providerConfig: {
      ...context.getHostState().bootstrap.providerConfig,
      lastTestResult: carried,
    },
  });
}

// Admission actions can be triggered in quick succession (or by a stale
// secondary click while the panel re-renders). Serialize them so a late
// ignore response cannot overwrite a newer adopt, and make the final message
// reflect the persisted project mode.
let admissionMutationQueue: Promise<unknown> = Promise.resolve();

function serializeAdmissionMutation<T>(task: () => Promise<T>): Promise<T> {
  const next = admissionMutationQueue.then(task, task);
  admissionMutationQueue = next.then(
    () => undefined,
    () => undefined,
  );
  return next;
}

function setCurrentWorkspaceProjectAdmission(
  context: CommandContext,
  adoptionMode: TrainerProjectAdoptionMode,
  responseLanguage?: ComposerLanguage,
  selectedProjectPath?: string,
): Promise<CommandExecutionResult> {
  return serializeAdmissionMutation(() =>
    runSetCurrentWorkspaceProjectAdmission(context, adoptionMode, responseLanguage, selectedProjectPath),
  );
}

async function runSetCurrentWorkspaceProjectAdmission(
  context: CommandContext,
  adoptionMode: TrainerProjectAdoptionMode,
  responseLanguage?: ComposerLanguage,
  selectedProjectPath?: string,
): Promise<CommandExecutionResult> {
  const lang = resolveHostCommandLanguage(context, responseLanguage);
  if (!(await context.trustGuard.ensureTrusted('set the current Trainer project admission mode'))) {
    return { ok: false, message: hostCommandCopy(lang, 'trustRequiredAdmission') };
  }

  const projectPath = selectedProjectPath?.trim() || resolveCurrentTrainerProjectPath(context.getHostState().workspace);
  if (!projectPath) {
    return unresolvableProjectPathResult(context, responseLanguage);
  }

  const language = resolveWorkspaceAdmissionResponseLanguage(context, { responseLanguage });
  const copy = admissionHostCopy(language);

  if (adoptionMode === 'managed') {
    const existingManifest = await context.trainerWorkspace.readWorkspaceManifest();
    if (!existingManifest && typeof vscode.window?.showOpenDialog === 'function') {
      const rootSetup = await chooseTrainerWorkspaceRootCommand(context);
      if (!rootSetup.ok) {
        return rootSetup;
      }
    }
  }

  let managedIdentity: TrainerManagedProjectIdentity | undefined;
  if (adoptionMode === 'managed') {
    try {
      const provisioned = await provisionManagedProject(context, projectPath, responseLanguage);
      if (provisioned.kind === 'browse') {
        const project = await context.trainerWorkspace.setProjectAdmission(projectPath, 'browse');
        await patchTrainerWorkspaceAdmission(context);
        return {
          ok: true,
          message: hostCommandCopy(lang, 'browseOnlyNotice'),
          data: project,
        };
      }
      managedIdentity = provisioned.identity;
    } catch (error) {
      const failure = workspaceAdmissionFailure(error);
      if (!failure) {
        const fallback = error instanceof Error ? error.message : String(error);
        await context.trainerWorkspace.recordManagedProvisioningPending(projectPath, fallback).catch(() => undefined);
        return { ok: false, message: fallback };
      }
      const message = workspaceAdmissionFailureMessage(failure, language);
      context.outputChannel.appendLine(
        safeWorkspaceAdmissionLog(failure, error instanceof SidecarHttpError ? error.statusCode : undefined),
      );
      await context.trainerWorkspace.recordManagedProvisioningPending(projectPath, message).catch(() => undefined);
      return { ok: false, message, data: failure };
    }
  } else {
    try {
      await assertProjectCanUseNonManagedAdmission(context, projectPath, responseLanguage);
    } catch (error) {
      return {
        ok: false,
        message: error instanceof Error ? error.message : String(error),
      };
    }
  }

  const project = await context.trainerWorkspace.setProjectAdmission(
    projectPath,
    adoptionMode,
    managedIdentity,
    projectPath.includes('://') ? managedIdentity?.canonicalProjectPath : undefined,
  );
  if (adoptionMode === 'managed') {
    if (selectedProjectPath?.trim()) {
      context.trustGuard.setPreferredWorkspaceProject?.(projectPath);
    }
    await includeAdoptedProjectInTransferPromotion(context, managedIdentity, projectPath);
  }
  await patchTrainerWorkspaceAdmission(
    context,
    adoptionMode === 'managed' && selectedProjectPath?.trim() ? projectPath : undefined,
  );
  if (adoptionMode === 'managed') {
    await rehydrateWorkbenchRuntime(context, {
      ensureSidecar: true,
      syncWorkbench: true,
    });
    // Rehydrate replaces the workbench bootstrap, so the carried connection
    // evidence must land after it, not before.
    await carryProviderTestAcrossProjectAdmission(context);
    // Trusted personal account: offer once to carry mastery into the
    // freshly adopted project instead of silently sharing.
    await maybePromptCarryOverOnProjectSwitch(context);
  }
  const persistedAdoptionMode =
    (project as { adoptionMode?: TrainerProjectAdoptionMode } | undefined)?.adoptionMode ??
    adoptionMode;
  const resultMessage =
    persistedAdoptionMode === 'managed'
      ? copy.projectAdded
      : persistedAdoptionMode === 'browse'
        ? copy.projectBrowseOnly
        : copy.projectIgnored;
  return {
    ok: true,
    message: resultMessage,
    data: project,
  };
}

function discoveryDecisionFromClassification(
  classification: ProjectClassificationResponse,
  remoteName: string,
): 'adopt' | 'browse' {
  const discovery = classification.project_discovery;
  const available = discovery?.available_decisions ?? discovery?.availableDecisions;
  if (Array.isArray(available) && available.length > 0) {
    if (available.includes('adopt')) {
      return 'adopt';
    }
    if (available.includes('browse')) {
      return 'browse';
    }
  }
  if (discovery?.is_browse_only === true || discovery?.isBrowseOnly === true) {
    return 'browse';
  }
  if (remoteName.trim()) {
    return 'browse';
  }
  return 'adopt';
}

async function classifyProjectForAdmission(
  context: CommandContext,
  port: number,
  body: WorkspaceClassificationRequest,
): Promise<ProjectClassificationResponse> {
  try {
    return await postUserInitiatedProjectAdmission<ProjectClassificationResponse>(
      context,
      port,
      '/workspace/classify',
      body,
    );
  } catch (error) {
    const failure = workspaceAdmissionFailure(error);
    if (failure?.errorCode !== 'root_path_unavailable' || !body.root_id || !body.root_path) {
      throw error;
    }
    // The backend rejected this root identity as unknown or unavailable (for
    // example after the sidecar data directory was reset). A retry must stay a
    // fresh attempt instead of replaying the same stale identity forever:
    // re-register the selected root by path so the backend returns a fresh
    // root_identity, which the caller persists before the admission decision.
    context.outputChannel.appendLine(
      `[workspace-admission] backend rejected root identity ${body.root_id} (root_path_unavailable); re-registering the selected root by path`,
    );
    const reRegistrationBody: WorkspaceClassificationRequest = {
      workspace_id: body.workspace_id,
      folder_path: body.folder_path,
      root_path: body.root_path,
      remote_name: body.remote_name,
      ...(body.workspace_file_snapshot ? { workspace_file_snapshot: body.workspace_file_snapshot } : {}),
      ...(body.response_language ? { response_language: body.response_language } : {}),
    };
    return postUserInitiatedProjectAdmission<ProjectClassificationResponse>(
      context,
      port,
      '/workspace/classify',
      reRegistrationBody,
    );
  }
}

async function provisionManagedProject(
  context: CommandContext,
  projectPath: string,
  responseLanguage?: ComposerLanguage,
): Promise<{ kind: 'managed'; identity: TrainerManagedProjectIdentity } | { kind: 'browse' }> {
  const lang = resolveHostCommandLanguage(context, responseLanguage);
  let selectedRoot = await readSelectedTrainerRoot(context, responseLanguage);
  if (!projectPath.includes('://') && pathsEqual(selectedRoot.canonicalRootPath, projectPath)) {
    const copy = admissionHostCopy(resolveWorkspaceAdmissionResponseLanguage(context, { responseLanguage }));
    throw new Error(copy.projectSameAsRoot);
  }

  let status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    throw new Error(status.detail ?? hostCommandCopy(lang, 'backendUnavailable'));
  }

  const workspaceName = basenameFs(projectPath) || 'Trainer';
  const workspaceFileSnapshot = await buildWorkspaceFileSnapshot(context);
  let classification = await classifyProjectForAdmission(context, status.port, {
    workspace_id: projectPath,
    folder_path: projectPath,
    root_id: selectedRoot.rootId,
    root_path: selectedRoot.canonicalRootPath,
    remote_name: context.getHostState().workspace.remoteName ?? '',
    ...(workspaceFileSnapshot ? { workspace_file_snapshot: workspaceFileSnapshot } : {}),
    ...(responseLanguage ? { response_language: responseLanguage } : {}),
  });
  const registeredRootId = classification.root_identity?.rootId;
  const registeredRootPath = classification.root_identity?.rootPath;
  if (!registeredRootId || !registeredRootPath) {
    throw new Error(hostCommandCopy(lang, 'backendDidNotRegisterRoot'));
  }
  const rootScopeChanged = selectedRoot.rootId !== registeredRootId;
  await context.trainerWorkspace.setRootIdentity(registeredRootId, registeredRootPath);
  selectedRoot = await readSelectedTrainerRoot(context, responseLanguage);
  if (rootScopeChanged) {
    // Root registration may have happened during the initial unscoped launch.
    // Switch storage before creating the project/session, then obtain a fresh
    // discovery owned by the backend that will keep that project's data.
    await patchTrainerWorkspaceAdmission(context);
    status = await context.sidecarManager.ensureRunning();
    if (status.lifecycle !== 'ready' || !status.port) {
      throw new Error(status.detail ?? hostCommandCopy(lang, 'backendUnavailable'));
    }
    classification = await classifyProjectForAdmission(context, status.port, {
      workspace_id: projectPath, folder_path: projectPath,
      root_id: selectedRoot.rootId, root_path: selectedRoot.canonicalRootPath,
      remote_name: context.getHostState().workspace.remoteName ?? '',
      ...(workspaceFileSnapshot ? { workspace_file_snapshot: workspaceFileSnapshot } : {}),
      ...(responseLanguage ? { response_language: responseLanguage } : {}),
    });
    if (classification.root_identity?.rootId !== selectedRoot.rootId ||
        !classification.root_identity?.rootPath ||
        !pathsEqual(classification.root_identity.rootPath, selectedRoot.canonicalRootPath)) {
      throw new Error(hostCommandCopy(lang, 'workspaceChangedDuringAdd'));
    }
  }
  if (projectPath.startsWith('vscode-remote://')) {
    const admissionPort = status.port;
    const identity = await provisionRemoteProject(context, projectPath, selectedRoot,
      (requestPath, body) => postUserInitiatedProjectAdmission(context, admissionPort, requestPath, body));
    await context.setSessionId(identity.agentSessionId);
    rememberServerIssuedSession(context, identity.agentSessionId);
    return { kind: 'managed', identity };
  }
  const started = await postUserInitiatedProjectAdmission<{ session_id?: string }>(
    context,
    status.port,
    '/session/start',
    {
      workspace_id: projectPath,
      workspace_name: workspaceName,
      workspace_path: projectPath,
      root_id: selectedRoot.rootId,
      root_path: selectedRoot.canonicalRootPath,
      remote_name: context.getHostState().workspace.remoteName ?? '',
      workspace_trusted: Boolean(context.getHostState().workspace.trusted),
      ...(workspaceFileSnapshot ? { workspace_file_snapshot: workspaceFileSnapshot } : {}),
      ...(responseLanguage ? { response_language: responseLanguage } : {}),
    },
  );
  const discoveryId = classification.project_discovery?.discovery_id;
  if (!discoveryId) {
    throw new Error(hostCommandCopy(lang, 'backendNoDiscoveryRecord'));
  }
  const decisionKind = discoveryDecisionFromClassification(
    classification,
    context.getHostState().workspace.remoteName ?? '',
  );
  const decision = await postUserInitiatedProjectAdmission<ProjectDecisionResponse>(
    context,
    status.port,
    '/workspace/discovery/decision',
    {
      workspace_id: projectPath,
      discovery_id: discoveryId,
      decision: decisionKind,
      root_id: selectedRoot.rootId,
      root_path: selectedRoot.canonicalRootPath,
    },
  );
  if (decisionKind === 'browse') {
    const sessionId = started.session_id?.trim();
    if (sessionId) {
      await context.setSessionId(sessionId);
    }
    return { kind: 'browse' };
  }
  const completed = await waitForManagedProjectAdoption(
    context,
    status.port,
    selectedRoot,
    projectPath,
    decision,
    lang,
  );
  const agentSessionId = completed.project_provisioning!.agent_session_id!;
  await context.setSessionId(agentSessionId);
  // The admission server just issued this session id: the rehydration that
  // follows is a continuation, not a reload, so it must not re-verify the id
  // through /session/activate inside the explicit-admission window.
  rememberServerIssuedSession(context, agentSessionId);
  return { kind: 'managed', identity: completed.project_identity! };
}

function currentReadOnlyAdmissionMode(context: CommandContext): ReadOnlyAdmissionMode | undefined {
  const status = context.getHostState().bootstrap.memory.workspace?.trainerWorkspace?.status;
  return status === 'browse' || status === 'ignored' ? status : undefined;
}

async function postUserInitiatedProjectAdmission<T>(
  context: CommandContext,
  port: number,
  requestPath: string,
  body: unknown,
): Promise<T> {
  return withUserInitiatedProjectAdmission(context, () =>
    context.sidecarClient.postJson<T>(port, requestPath, body),
  );
}

async function getUserInitiatedProjectAdmission<T>(
  context: CommandContext,
  port: number,
  requestPath: string,
): Promise<T> {
  return withUserInitiatedProjectAdmission(context, () => context.sidecarClient.getJson<T>(port, requestPath));
}

function projectAdoptionPollingPath(jobId: string, rootPath: string, workspaceId: string): string {
  const params = new URLSearchParams({
    job_id: jobId,
    root_path: rootPath,
    workspace_id: workspaceId,
  });
  return `/workspace/adoption-job?${params.toString()}`;
}

function managedAdoptionFailureMessage(
  lang: ComposerLanguage,
  status: string | undefined,
  reason: string | undefined,
): string {
  const normalizedStatus = status?.trim().toLowerCase();
  if (normalizedStatus === 'interrupted') {
    return reason
      ? hostCommandCopy(lang, 'adoptionInterruptedReason', { reason })
      : hostCommandCopy(lang, 'adoptionInterrupted');
  }
  if (normalizedStatus === 'retry_required') {
    return reason
      ? hostCommandCopy(lang, 'adoptionRetryRequiredReason', { reason })
      : hostCommandCopy(lang, 'adoptionRetryRequired');
  }
  return reason
    ? hostCommandCopy(lang, 'adoptionTimedOutReason', { reason })
    : hostCommandCopy(lang, 'adoptionTimedOut');
}

async function waitForManagedProjectAdoption(
  context: CommandContext,
  port: number,
  selectedRoot: SelectedTrainerRoot,
  projectPath: string,
  initialDecision: ProjectDecisionResponse,
  lang: ComposerLanguage,
): Promise<ProjectDecisionResponse> {
  const completedStatus = initialDecision.project_adoption_job?.status?.trim().toLowerCase();
  if (
    completedStatus === 'completed' &&
    initialDecision.project_discovery?.status === 'adopted' &&
    initialDecision.project_provisioning?.agent_session_id &&
    initialDecision.project_identity
  ) {
    const currentSelectedRoot = await readSelectedTrainerRoot(context, lang);
    if (
      !pathsEqual(currentSelectedRoot.canonicalRootPath, selectedRoot.canonicalRootPath) ||
      currentSelectedRoot.rootId !== selectedRoot.rootId
    ) {
      throw new Error(hostCommandCopy(lang, 'workspaceChangedDuringAdd'));
    }
    assertProvisioningMatchesSelectedRoot(initialDecision, currentSelectedRoot, lang);
    return initialDecision;
  }

  const jobId = initialDecision.project_adoption_job?.job_id?.trim();
  if (!jobId) {
    if (
      initialDecision.project_discovery?.status === 'adopted' &&
      initialDecision.project_provisioning?.agent_session_id &&
      initialDecision.project_identity
    ) {
      const currentSelectedRoot = await readSelectedTrainerRoot(context, lang);
      if (
        !pathsEqual(currentSelectedRoot.canonicalRootPath, selectedRoot.canonicalRootPath) ||
        currentSelectedRoot.rootId !== selectedRoot.rootId
      ) {
        throw new Error(hostCommandCopy(lang, 'workspaceChangedDuringAdd'));
      }
      assertProvisioningMatchesSelectedRoot(initialDecision, currentSelectedRoot, lang);
      return initialDecision;
    }
    throw new Error(hostCommandCopy(lang, 'adoptionNoJobStarted'));
  }

  const timeoutMs = 15_000;
  const pollIntervalMs = 250;
  const deadlineMs = Date.now() + timeoutMs;
  let lastStatus = initialDecision.project_adoption_job;

  while (Date.now() <= deadlineMs) {
    const currentSelectedRoot = await readSelectedTrainerRoot(context, lang);
    if (
      !pathsEqual(currentSelectedRoot.canonicalRootPath, selectedRoot.canonicalRootPath) ||
      currentSelectedRoot.rootId !== selectedRoot.rootId
    ) {
      throw new Error(hostCommandCopy(lang, 'workspaceChangedDuringAdd'));
    }

    const response = await getUserInitiatedProjectAdmission<ProjectDecisionResponse>(
      context,
      port,
      projectAdoptionPollingPath(jobId, selectedRoot.canonicalRootPath, projectPath),
    );
    lastStatus = response.project_adoption_job ?? lastStatus;
    const status = response.project_adoption_job?.status?.trim().toLowerCase();
    if (status === 'completed') {
      const agentSessionId = response.project_provisioning?.agent_session_id;
      if (!agentSessionId || !response.project_identity || response.project_discovery?.status !== 'adopted') {
        throw new Error(hostCommandCopy(lang, 'adoptionIncompleteState'));
      }
      const finalSelectedRoot = await readSelectedTrainerRoot(context, lang);
      if (
        !pathsEqual(finalSelectedRoot.canonicalRootPath, selectedRoot.canonicalRootPath) ||
        finalSelectedRoot.rootId !== selectedRoot.rootId
      ) {
        throw new Error(hostCommandCopy(lang, 'workspaceChangedDuringAdd'));
      }
      assertProvisioningMatchesSelectedRoot(response, finalSelectedRoot, lang);
      return response;
    }
    if (status === 'interrupted' || status === 'retry_required') {
      throw new Error(managedAdoptionFailureMessage(lang, status, response.project_adoption_job?.retry_reason));
    }

    const remainingMs = deadlineMs - Date.now();
    if (remainingMs <= 0) {
      break;
    }
    await new Promise<void>((resolve) => setTimeout(resolve, Math.min(pollIntervalMs, remainingMs)));
  }

  throw new Error(managedAdoptionFailureMessage(lang, lastStatus?.status, lastStatus?.retry_reason));
}

async function assertProjectCanUseNonManagedAdmission(
  context: CommandContext,
  projectPath: string,
  responseLanguage?: ComposerLanguage,
): Promise<void> {
  const lang = resolveHostCommandLanguage(context, responseLanguage);
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    throw new Error(hostCommandCopy(lang, 'nonManagedVerifyFailed'));
  }

  let response: ProjectProvisioningResponse;
  try {
    response = await context.sidecarClient.getJson<ProjectProvisioningResponse>(
      status.port,
      `/workspace/project-provisioning?workspace_id=${encodeURIComponent(projectPath)}`,
    );
  } catch (error) {
    if (isSidecarNotFound(error)) {
      return;
    }
    throw new Error(hostCommandCopy(lang, 'nonManagedVerifyFailed'));
  }

  if (!response?.project_provisioning?.agent_session_id) {
    throw new Error(hostCommandCopy(lang, 'nonManagedIncompleteVerify'));
  }
  throw new Error(hostCommandCopy(lang, 'alreadyManagedMustRetireFirst'));
}

function isSidecarNotFound(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'statusCode' in error &&
    (error as { statusCode?: unknown }).statusCode === 404
  );
}

async function pickTrainerWorkspaceDirectory(input: {
  currentRoot?: string;
  openLabel: string;
  title: string;
}): Promise<string | undefined> {
  const picks = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    defaultUri: input.currentRoot ? vscode.Uri.file(input.currentRoot) : undefined,
    openLabel: input.openLabel,
    title: input.title,
  });
  return picks?.[0]?.fsPath;
}


export async function trustWorkspaceWindowCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const lang = resolveHostCommandLanguage(context);
  // 受限模式下扩展写操作全部被 VS Code 拦截;这里给用户一个明确的一键入口,
  // 打开原生的工作区信任管理,信任后 Trainer 的所有功能立即可用。
  await vscode.commands.executeCommand('workbench.trust.manage');
  const trusted = vscode.workspace.isTrusted;
  return {
    ok: true,
    message: hostCommandCopy(lang, trusted ? 'trustWorkspaceReady' : 'trustWorkspaceManageOpened'),
    data: { trusted },
  };
}
