import * as vscode from 'vscode';

import { primeProviderModelsState } from '../commands/providerWebviewCommands';
import { getRuntimeWorkspaceContext } from '../commands/workspaceContext';
import type { CommandContext } from './commandContext';
import type { SidecarStatus } from './types';
import { flushPendingTransferPromotionScope } from './transferPromotionScope';
import { mapResourceTrash, mergeMemorySummarySnapshot, mergeSessionStartSnapshot } from './workbenchData';
import { describeProviderSendState } from '../../../shared/src/providerStatus';
import { isComposerLanguage, type ComposerLanguage } from '../../../shared/src/types';
import { buildWorkspaceFileSnapshot } from './workspaceFileSnapshot';

export interface RuntimeStatusMessage {
  tone: 'info' | 'success' | 'error';
  message: string;
}

export interface RehydrateWorkbenchRuntimeOptions {
  ensureSidecar?: boolean;
  syncWorkbench?: boolean;
}

const inflightSessionInitializers = new WeakMap<
  CommandContext,
  Promise<string | undefined>
>();
const inflightRuntimeRehydrations = new WeakMap<
  CommandContext,
  {
    workspaceId: string;
    promise: Promise<SidecarStatus>;
  }
>();

type RuntimeCopy = {
  rootMissing: string;
  projectFound: string;
  ignored: string;
  browse: string;
  starting: string;
  stopped: string;
  unavailable: string;
  providerSetup: string;
  ready: string;
};

const runtimeCopyByLanguage: Record<ComposerLanguage, RuntimeCopy> = {
  'zh-CN': {
    rootMissing: '先选择 Trainer 工作区，再开始对话。',
    projectFound: '发现了这个项目。先选择“加入 Trainer”“仅浏览”或“忽略”。',
    ignored: '这个项目已被忽略。需要时可回到教练页把它加入 Trainer。',
    browse: '这个项目现在只能浏览，不会启动项目对话或保存学习记录。',
    starting: 'Trainer 正在准备，稍等一下。',
    stopped: 'Trainer 已暂停。请在设置中重新启动后继续。',
    unavailable: 'Trainer 现在还不能使用。稍后再试，或在设置中重新启动。',
    providerSetup: '模型连接还没完成。请到“设置”中完成连接后再开始对话。',
    ready: 'Trainer 已准备好，可以继续当前对话和学习。',
  },
  'en-US': {
    rootMissing: 'Choose a Trainer workspace before starting a conversation.',
    projectFound: 'A project was found. Choose Add to Trainer, Browse only, or Ignore.',
    ignored: 'This project is ignored. Return to Coach to add it to Trainer when you are ready.',
    browse: 'This project is browse-only. Coaching and saved learning records stay off.',
    starting: 'Trainer is getting ready. Please wait a moment.',
    stopped: 'Trainer is paused. Restart it in Settings to continue.',
    unavailable: 'Trainer is not available yet. Try again shortly or restart it in Settings.',
    providerSetup: 'The model connection is not ready. Finish it in Settings before starting a conversation.',
    ready: 'Trainer is ready. You can continue this conversation and learning.',
  },
  'es-ES': {
    rootMissing: 'Elige un espacio de Trainer antes de iniciar una conversación.',
    projectFound: 'Se encontró un proyecto. Elige Agregar a Trainer, Solo explorar o Ignorar.',
    ignored: 'Este proyecto está ignorado. Vuelve a Coach para agregarlo a Trainer cuando quieras.',
    browse: 'Este proyecto es solo para explorar. El coaching y los registros guardados están desactivados.',
    starting: 'Trainer se está preparando. Espera un momento.',
    stopped: 'Trainer está en pausa. Reinícialo en Ajustes para continuar.',
    unavailable: 'Trainer aún no está disponible. Inténtalo pronto o reinícialo en Ajustes.',
    providerSetup: 'La conexión del modelo no está lista. Termínala en Ajustes antes de iniciar una conversación.',
    ready: 'Trainer está listo. Puedes continuar esta conversación y el aprendizaje.',
  },
  'fr-FR': {
    rootMissing: 'Choisissez un espace Trainer avant de démarrer une conversation.',
    projectFound: 'Un projet a été trouvé. Choisissez Ajouter à Trainer, Consultation seule ou Ignorer.',
    ignored: 'Ce projet est ignoré. Revenez à Coach pour l’ajouter à Trainer lorsque vous le souhaitez.',
    browse: 'Ce projet est en consultation seule. Le coaching et les enregistrements restent désactivés.',
    starting: 'Trainer se prépare. Patientez un instant.',
    stopped: 'Trainer est en pause. Redémarrez-le dans Réglages pour continuer.',
    unavailable: 'Trainer n’est pas encore disponible. Réessayez bientôt ou redémarrez-le dans Réglages.',
    providerSetup: 'La connexion du modèle n’est pas prête. Terminez-la dans Réglages avant de démarrer une conversation.',
    ready: 'Trainer est prêt. Vous pouvez continuer cette conversation et cet apprentissage.',
  },
  'de-DE': {
    rootMissing: 'Wählen Sie einen Trainer-Arbeitsbereich, bevor Sie eine Unterhaltung starten.',
    projectFound: 'Ein Projekt wurde gefunden. Wählen Sie Zu Trainer hinzufügen, Nur ansehen oder Ignorieren.',
    ignored: 'Dieses Projekt wird ignoriert. Öffnen Sie Coach, wenn Sie es zu Trainer hinzufügen möchten.',
    browse: 'Dieses Projekt ist nur zur Ansicht. Coaching und gespeicherte Lernaufzeichnungen bleiben aus.',
    starting: 'Trainer wird vorbereitet. Einen Moment bitte.',
    stopped: 'Trainer ist angehalten. Starten Sie ihn in Einstellungen neu, um fortzufahren.',
    unavailable: 'Trainer ist noch nicht verfügbar. Versuchen Sie es gleich erneut oder starten Sie ihn in Einstellungen neu.',
    providerSetup: 'Die Modellverbindung ist nicht bereit. Schließen Sie sie in Einstellungen ab, bevor Sie eine Unterhaltung starten.',
    ready: 'Trainer ist bereit. Sie können diese Unterhaltung und das Lernen fortsetzen.',
  },
  'ja-JP': {
    rootMissing: '会話を始める前に Trainer ワークスペースを選択してください。',
    projectFound: 'プロジェクトが見つかりました。Trainer に追加、閲覧のみ、または無視を選んでください。',
    ignored: 'このプロジェクトは無視されています。必要になったら Coach で Trainer に追加できます。',
    browse: 'このプロジェクトは閲覧のみです。コーチングと学習記録の保存は行われません。',
    starting: 'Trainer を準備しています。少しお待ちください。',
    stopped: 'Trainer は一時停止中です。続けるには設定で再起動してください。',
    unavailable: 'Trainer はまだ利用できません。少し待つか、設定で再起動してください。',
    providerSetup: 'モデル接続の準備ができていません。会話を始める前に設定で完了してください。',
    ready: 'Trainer の準備ができました。この会話と学習を続けられます。',
  },
  'ko-KR': {
    rootMissing: '대화를 시작하기 전에 Trainer 작업 공간을 선택하세요.',
    projectFound: '프로젝트를 찾았습니다. Trainer에 추가, 둘러보기만 또는 무시를 선택하세요.',
    ignored: '이 프로젝트는 무시되었습니다. 필요하면 Coach에서 Trainer에 추가할 수 있습니다.',
    browse: '이 프로젝트는 둘러보기 전용입니다. 코칭과 학습 기록 저장은 꺼져 있습니다.',
    starting: 'Trainer를 준비하고 있습니다. 잠시만 기다려 주세요.',
    stopped: 'Trainer가 일시 중지되었습니다. 계속하려면 설정에서 다시 시작하세요.',
    unavailable: 'Trainer를 아직 사용할 수 없습니다. 잠시 후 다시 시도하거나 설정에서 다시 시작하세요.',
    providerSetup: '모델 연결이 준비되지 않았습니다. 대화를 시작하기 전에 설정에서 완료하세요.',
    ready: 'Trainer가 준비되었습니다. 이 대화와 학습을 계속할 수 있습니다.',
  },
  'pt-BR': {
    rootMissing: 'Escolha um espaço do Trainer antes de iniciar uma conversa.',
    projectFound: 'Um projeto foi encontrado. Escolha Adicionar ao Trainer, Somente navegar ou Ignorar.',
    ignored: 'Este projeto está ignorado. Volte ao Coach para adicioná-lo ao Trainer quando quiser.',
    browse: 'Este projeto é apenas para navegação. O coaching e os registros salvos ficam desativados.',
    starting: 'O Trainer está se preparando. Aguarde um instante.',
    stopped: 'O Trainer está pausado. Reinicie-o em Configurações para continuar.',
    unavailable: 'O Trainer ainda não está disponível. Tente novamente em breve ou reinicie-o em Configurações.',
    providerSetup: 'A conexão do modelo não está pronta. Conclua-a em Configurações antes de iniciar uma conversa.',
    ready: 'O Trainer está pronto. Você pode continuar esta conversa e o aprendizado.',
  },
};

function savedRuntimeLanguage(
  context: Pick<CommandContext, 'getHostState'>,
): ComposerLanguage | undefined {
  const savedLanguage = context.getHostState().bootstrap.memory?.workspace?.responseLanguage;
  if (isComposerLanguage(savedLanguage)) {
    return savedLanguage;
  }

  return undefined;
}

function resolveRuntimeLanguage(context: Pick<CommandContext, 'getHostState'>): ComposerLanguage {
  const savedLanguage = savedRuntimeLanguage(context);
  if (savedLanguage) {
    return savedLanguage;
  }

  const vscodeLanguage = vscode.env?.language?.trim().toLowerCase();
  if (vscodeLanguage?.startsWith('en')) {
    return 'en-US';
  }
  if (vscodeLanguage?.startsWith('es')) {
    return 'es-ES';
  }
  if (vscodeLanguage?.startsWith('fr')) {
    return 'fr-FR';
  }
  if (vscodeLanguage?.startsWith('de')) {
    return 'de-DE';
  }
  if (vscodeLanguage?.startsWith('ja')) {
    return 'ja-JP';
  }
  if (vscodeLanguage?.startsWith('ko')) {
    return 'ko-KR';
  }
  if (vscodeLanguage?.startsWith('pt')) {
    return 'pt-BR';
  }
  return 'zh-CN';
}

function runtimeCopy(context: Pick<CommandContext, 'getHostState'>): RuntimeCopy {
  return runtimeCopyByLanguage[resolveRuntimeLanguage(context)];
}

export function hasTrainerWorkspaceRoot(context: Pick<CommandContext, 'trainerWorkspace'>): boolean {
  return Boolean(context.trainerWorkspace?.getRoot());
}

export function trainerSessionBlockReason(context: CommandContext): string | undefined {
  const copy = runtimeCopy(context);
  const admission = context.getHostState().bootstrap.memory?.workspace?.trainerWorkspace;
  if (admission?.status === 'root-missing' || !hasTrainerWorkspaceRoot(context)) {
    return copy.rootMissing;
  }
  if (admission?.status === 'project-found') {
    return copy.projectFound;
  }
  if (admission?.status === 'ignored') {
    return copy.ignored;
  }
  if (admission?.status === 'browse') {
    return copy.browse;
  }
  return undefined;
}

export function shouldAutoStartSidecar(status: SidecarStatus): boolean {
  if (!status.canStart || status.lifecycle === 'unavailable') {
    return false;
  }
  if (status.lifecycle === 'stopped' && status.detail === 'Sidecar stopped.') {
    return false;
  }
  return true;
}

export function buildTrainerRuntimeStatus(
  context: CommandContext,
  status = context.sidecarManager.getStatus(),
): RuntimeStatusMessage {
  const language = resolveRuntimeLanguage(context);
  const copy = runtimeCopyByLanguage[language];
  if (status.lifecycle !== 'ready') {
    if (status.lifecycle === 'starting') {
      return {
        tone: 'info',
        message: copy.starting,
      };
    }
    if (status.lifecycle === 'stopped') {
      return {
        tone: 'info',
        message: copy.stopped,
      };
    }
    return {
      tone: status.lifecycle === 'error' || status.lifecycle === 'unavailable' ? 'error' : 'info',
      message: copy.unavailable,
    };
  }

  const sessionBlockReason = trainerSessionBlockReason(context);
  if (sessionBlockReason) {
    return {
      tone: 'info',
      message: sessionBlockReason,
    };
  }

  const sendState = describeProviderSendState(
    context.getHostState().bootstrap.providerConfig,
    language,
  );
  if (sendState.blocked) {
    return {
      tone: 'info',
      message: sendState.reason ?? copy.providerSetup,
    };
  }

  return {
    tone: 'success',
    message: copy.ready,
  };
}

export async function ensureInitialSession(
  context: CommandContext,
  port = context.sidecarManager.getStatus().port,
): Promise<string | undefined> {
  if (trainerSessionBlockReason(context)) {
    return undefined;
  }

  const existingSessionId = context.getSessionId();
  if (existingSessionId) {
    return existingSessionId;
  }

  const activeInitialization = inflightSessionInitializers.get(context);
  if (activeInitialization) {
    return activeInitialization;
  }

  const initialization = (async (): Promise<string | undefined> => {
    if (!port) {
      return context.getSessionId();
    }

    const runtimeWorkspace = getRuntimeWorkspaceContext(context);
    const workspaceIdAtStart = runtimeWorkspace.workspaceId;
    const workspacePath = runtimeWorkspace.canonicalProjectPath;
    const workspaceName = workspacePath
      ? vscode.workspace.name || workspacePath.split(/[\\/]/).pop() || 'Trainer'
      : 'Trainer';
    const responseLanguage = savedRuntimeLanguage(context);
    const workspaceFileSnapshot = await buildWorkspaceFileSnapshot(context);
    const payload = await context.sidecarClient.postJson<{ session_id?: string }>(
      port,
      '/session/start',
      {
        workspace_id: runtimeWorkspace.workspaceId,
        workspace_name: workspaceName,
        workspace_path: workspacePath,
        remote_name: context.getHostState().workspace.remoteName ?? '',
        workspace_trusted: Boolean(context.getHostState().workspace.trusted),
        ...(workspaceFileSnapshot ? { workspace_file_snapshot: workspaceFileSnapshot } : {}),
        ...(responseLanguage ? { response_language: responseLanguage } : {}),
      },
    );

    if (getRuntimeWorkspaceContext(context).workspaceId !== workspaceIdAtStart) {
      context.outputChannel.appendLine(
        `[session] discarded initialization from stale workspace ${workspaceIdAtStart}`,
      );
      return context.getSessionId();
    }

    if (!payload.session_id) {
      return context.getSessionId();
    }

    await context.setSessionId(payload.session_id);
    await context.patchWorkbenchData(
      mergeSessionStartSnapshot(
        context.getHostState().bootstrap,
        payload,
        runtimeWorkspace.workspaceId,
      ),
    );
    context.outputChannel.appendLine(`[session] initialized ${payload.session_id}`);
    return payload.session_id;
  })();

  inflightSessionInitializers.set(context, initialization);
  try {
    return await initialization;
  } finally {
    inflightSessionInitializers.delete(context);
  }
}

export async function refreshWorkbenchMemory(
  context: CommandContext,
  port = context.sidecarManager.getStatus().port,
  options: {
    preferWorkspaceRecovery?: boolean;
  } = {},
): Promise<void> {
  if (!port || trainerSessionBlockReason(context)) {
    return;
  }

  try {
    const sessionId = context.getSessionId();
    const workspaceId = getRehydrationWorkspaceId(context);
    const params = new URLSearchParams({ workspace_id: workspaceId });
    if (sessionId && !options.preferWorkspaceRecovery) {
      params.set('session_id', sessionId);
    }
    const summaryPath = `/memory/summary?${params.toString()}`;
    const summary = await context.sidecarClient.getJson<unknown>(port, summaryPath);
    if (getRehydrationWorkspaceId(context) !== workspaceId) {
      context.outputChannel.appendLine(
        `[memory] discarded summary from stale workspace ${workspaceId}`,
      );
      return;
    }
    await context.patchWorkbenchData(
      mergeMemorySummarySnapshot(context.getHostState().bootstrap, summary, workspaceId),
    );
  } catch (error) {
    context.outputChannel.appendLine(
      `[memory] unable to refresh workbench summary: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }
}

export async function refreshWorkbenchResourceTrash(
  context: CommandContext,
  port = context.sidecarManager.getStatus().port,
): Promise<void> {
  if (!port || trainerSessionBlockReason(context)) {
    return;
  }

  try {
    const workspaceId = getRehydrationWorkspaceId(context);
    const params = new URLSearchParams({ workspace_id: workspaceId });
    const trash = await context.sidecarClient.getJson<unknown>(
      port,
      `/resource/trash?${params.toString()}`,
    );
    if (getRehydrationWorkspaceId(context) !== workspaceId) {
      context.outputChannel.appendLine(
        `[resources] discarded Trash snapshot from stale workspace ${workspaceId}`,
      );
      return;
    }
    await context.patchWorkbenchData({ deletedResources: mapResourceTrash(trash, workspaceId) });
  } catch (error) {
    context.outputChannel.appendLine(
      `[resources] unable to refresh recoverable Trash state: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }
}

function getRehydrationWorkspaceId(context: CommandContext): string {
  return getRuntimeWorkspaceContext(context).workspaceId;
}

export async function rehydrateWorkbenchRuntime(
  context: CommandContext,
  options: RehydrateWorkbenchRuntimeOptions = {},
): Promise<SidecarStatus> {
  const ensureSidecar = options.ensureSidecar ?? false;
  const syncWorkbench = options.syncWorkbench ?? false;
  let requestedWorkspaceId = getRehydrationWorkspaceId(context);
  while (true) {
    const inflight = inflightRuntimeRehydrations.get(context);
    if (!inflight) {
      break;
    }
    await inflight.promise;
    requestedWorkspaceId = getRehydrationWorkspaceId(context);
    if (inflightRuntimeRehydrations.get(context)?.promise === inflight.promise) {
      inflightRuntimeRehydrations.delete(context);
    }
    if (inflight.workspaceId === requestedWorkspaceId) {
      if (syncWorkbench) {
        await context.workbench.syncState();
      }
      return context.sidecarManager.getStatus();
    }
  }

  requestedWorkspaceId = getRehydrationWorkspaceId(context);
  const trusted = context.getHostState().workspace.trusted;
  const workspaceIdAtStart = requestedWorkspaceId;

  const rehydration = (async (): Promise<SidecarStatus> => {
    let status = context.sidecarManager.getStatus();
    const runtimeWorkspace = getRuntimeWorkspaceContext(context);
    await context.sidecarManager.setManagedDataRootScope?.({
      rootId: runtimeWorkspace.rootId,
      legacyWorkspaceFolder: runtimeWorkspace.legacyWorkspaceId,
    });
    const workspaceAdmissionBlocked = Boolean(trainerSessionBlockReason(context));

    if (!workspaceAdmissionBlocked && context.sidecarManager.hasPendingManagedDataScopeRestart?.()) {
      status = await context.sidecarManager.ensureRunning();
    } else if (!workspaceAdmissionBlocked && ensureSidecar && trusted && shouldAutoStartSidecar(status)) {
      status = await context.sidecarManager.ensureRunning();
    }

    if (status.lifecycle === 'ready' && status.port && !trainerSessionBlockReason(context)) {
      await flushPendingTransferPromotionScope(context);
      await primeProviderModelsState(context);
      if (getRuntimeWorkspaceContext(context).workspaceId !== workspaceIdAtStart) {
        return context.sidecarManager.getStatus();
      }
      await ensureInitialSession(context, status.port);
      if (getRuntimeWorkspaceContext(context).workspaceId !== workspaceIdAtStart) {
        return context.sidecarManager.getStatus();
      }
      await Promise.all([
        refreshWorkbenchMemory(context, status.port, {
          preferWorkspaceRecovery: true,
        }),
        refreshWorkbenchResourceTrash(context, status.port),
      ]);
    }

    if (getRuntimeWorkspaceContext(context).workspaceId !== workspaceIdAtStart) {
      return context.sidecarManager.getStatus();
    }
    await context.patchWorkbenchData({});
    return context.sidecarManager.getStatus();
  })();

  inflightRuntimeRehydrations.set(context, {
    workspaceId: workspaceIdAtStart,
    promise: rehydration,
  });
  try {
    const status = await rehydration;
    if (syncWorkbench) {
      await context.workbench.syncState();
    }
    return status;
  } finally {
    if (inflightRuntimeRehydrations.get(context)?.promise === rehydration) {
      inflightRuntimeRehydrations.delete(context);
    }
  }
}
