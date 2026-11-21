import * as path from 'node:path';
import * as vscode from 'vscode';

import type { RemoteProcessSpec } from '../../../shared/src/remoteProtocol';
import type { RemoteVerificationArtifact } from '../../../shared/src/trainingVerification';
import { assertRemoteVerificationFileScope, captureRemoteVerificationArtifact, finishRemoteVerificationArtifact,
  type CapturedRemoteArtifact } from '../testing/remoteVerificationArtifact';
import { deriveCompanionInstallState } from '../../../shared/src/companionInstallState';
import type { ComposerLanguage } from '../../../shared/src/types';
import { hostCommandCopy, resolveHostCommandLanguage } from './hostCommandCopy';
import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';
import {
  ATTESTATION_UNDELIVERED_MARKER,
  attestationIdempotencyKey,
  buildTestRunAttestationBody,
  dispatchTestRunAttestation,
  resolveAttestationWorkspaceId,
  resolveLivePracticeCardId,
  truncateTestsOutput,
  type TrainingAttestationRuntime,
} from '../testing/trainingAttestation';

/**
 * Attestation runtime with the undelivered notice wired: a failed delivery
 * posts the marker message the webview scopes to Training (localized there).
 */
interface VerificationScope {
  workspaceId?: string;
  sessionId?: string;
  cardId?: string;
}
function captureVerificationScope(context: CommandContext, cardId?: string): VerificationScope {
  return { workspaceId: resolveAttestationWorkspaceId(context.getHostState()),
    sessionId: context.getSessionId(), cardId: cardId ?? resolveLivePracticeCardId(context.getHostState()) };
}
function verificationScopeIsCurrent(context: CommandContext, scope: VerificationScope): boolean {
  return scope.workspaceId === resolveAttestationWorkspaceId(context.getHostState()) &&
    scope.sessionId === context.getSessionId() && (!scope.cardId || scope.cardId === resolveLivePracticeCardId(context.getHostState()));
}

function attestationRuntimeWithUndeliveredNotice(context: CommandContext, scope: VerificationScope): TrainingAttestationRuntime {
  return {
    sidecarClient: context.sidecarClient,
    sidecarManager: context.sidecarManager,
    outputChannel: context.outputChannel,
    getHostState: () => context.getHostState(),
    getSessionId: () => context.getSessionId(),
    notifyAttestationUndelivered: () => {
      if (!verificationScopeIsCurrent(context, scope)) return;
      void context.workbench.postMessage({
        type: 'operation/status',
        payload: { tone: 'error', message: ATTESTATION_UNDELIVERED_MARKER },
      });
    },
  };
}

export interface RemoteVerificationCommandPayload {
  /** Structured process spec — protocol v2 has no shell-string path. */
  executable?: string;
  args?: string[];
  cwd?: string;
  timeoutMs?: number;
  cardId?: string;
  /** Explicit file whose stable bytes bind this verification to its project. */
  artifactUri?: string;
}

function parseSpec(record: Record<string, unknown>): RemoteProcessSpec | undefined {
  const executable = typeof record.executable === 'string' ? record.executable.trim() : '';
  if (!executable) {
    return undefined;
  }
  const args = Array.isArray(record.args)
    ? record.args.map((entry) => String(entry))
    : [];
  return {
    executable,
    args,
    ...(typeof record.cwd === 'string' && record.cwd.trim() ? { cwd: record.cwd.trim() } : {}),
    ...(typeof record.timeoutMs === 'number' && record.timeoutMs > 0
      ? { timeout_ms: Math.floor(record.timeoutMs) }
      : {}),
  };
}

function describeSpec(spec: RemoteProcessSpec): string {
  return [spec.executable, ...spec.args].join(' ');
}

/**
 * Run one explicit verification process in the REMOTE workspace via the
 * Companion (protocol v2: structured ProcessSpec, streaming lifecycle) and
 * attest the outcome to the sidecar as host-trusted evidence.
 *
 * Honesty contract: only a completed run (numeric exit code, state
 * "completed") is attested. A companion/transport failure, a timeout, a user
 * cancellation, or a disconnect records NO evidence — an interrupted run must
 * never become "failed", and nothing here can create "passed" without a real
 * remote execution.
 */
export async function remoteVerifyCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const workspace = context.getHostState().workspace;
  const record = (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown>;
  const lang = resolveHostCommandLanguage(context, record.responseLanguage);
  const requestedCard = typeof record.cardId === 'string' && record.cardId.trim() ? record.cardId.trim() : undefined;
  const scope = captureVerificationScope(context, requestedCard);
  if (!workspace.isRemoteWorkspace && !workspace.remoteName) {
    return {
      ok: false,
      message: hostCommandCopy(lang, 'remoteVerifyWindowRequired'),
    };
  }
  if (!(await context.trustGuard.ensureTrusted('run remote verification'))) {
    return { ok: false, message: hostCommandCopy(lang, 'remoteVerifyTrustRequired') };
  }
  const spec = parseSpec(record);
  if (!spec) {
    return { ok: false, message: hostCommandCopy(lang, 'remoteVerifyExecutableRequired') };
  }

  const capabilities = await context.workspaceGateway.capabilities();
  if (!capabilities.companionAvailable || !capabilities.verify) {
    return {
      ok: false,
      message: hostCommandCopy(lang, 'remoteVerifyCompanionUnavailableRunInstall'),
    };
  }

  if (!verificationScopeIsCurrent(context, scope)) return { ok: false, message: hostCommandCopy(lang, 'remoteVerifyScopeChangedBeforeStart') };
  const described = describeSpec(spec);
  let stdout = '';
  let stderr = '';
  let exitCode: number | null = null;
  let passed = false;
  // Companion-side session id: the stable run identity behind the attestation
  // idempotency key, so a delivery retry can never double-record evidence.
  let companionRunId = '';
  let captured: CapturedRemoteArtifact | undefined;
  let artifact: RemoteVerificationArtifact | undefined;
  if (scope.cardId) {
    try { captured = await captureRemoteVerificationArtifact(context,
      typeof record.artifactUri === 'string' ? record.artifactUri : vscode.window?.activeTextEditor?.document.uri); }
    catch { context.outputChannel.appendLine('[remote] verification artifact could not be bound; evidence will not be recorded.'); }
  }
  if (!verificationScopeIsCurrent(context, scope)) return { ok: false, message: hostCommandCopy(lang, 'remoteVerifyScopeChangedBeforeStart') };
  try {
    const verification = await context.workspaceGateway.runVerification(spec, {
      onStart: (session) => {
        companionRunId = session.session_id;
      },
      onChunk: (chunk) => {
        if (chunk.stream === 'stdout') {
          stdout = (stdout + chunk.text).slice(-100_000);
        } else {
          stderr = (stderr + chunk.text).slice(-100_000);
        }
        context.outputChannel.appendLine(`[remote:${chunk.stream}] ${chunk.text.trimEnd()}`);
      },
    });
    if (verification.state !== 'completed') {
      const reason =
        verification.state === 'timed_out'
          ? hostCommandCopy(lang, 'remoteVerifyReasonTimedOut')
          : verification.state === 'cancelled'
            ? hostCommandCopy(lang, 'remoteVerifyReasonCancelled')
            : hostCommandCopy(lang, 'remoteVerifyReasonConnectionLost');
      context.outputChannel.appendLine(`[remote] verification interrupted: ${verification.state}`);
      return {
        ok: false,
        message: hostCommandCopy(lang, 'remoteVerifyInterruptedReason', { reason }),
        data: { spec, state: verification.state, stdout, stderr },
      };
    }
    exitCode = verification.exit_code ?? null;
    passed = verification.result === 'passed' && exitCode === 0;
    if (verificationScopeIsCurrent(context, scope)) {
      try { artifact = await finishRemoteVerificationArtifact(context, captured, companionRunId, verification); }
      catch { context.outputChannel.appendLine('[remote] verification artifact changed or became unavailable; no evidence was recorded.'); }
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    context.outputChannel.appendLine(`[remote] verification did not complete: ${detail}`);
    return {
      ok: false,
      message: hostCommandCopy(lang, 'remoteVerifyFailedDetail', { detail }),
    };
  }
  if (exitCode === null) {
    return {
      ok: false,
      message: hostCommandCopy(lang, 'remoteVerifyNoExitCode'),
    };
  }

  const cardId = scope.cardId;
  let attestation: 'delivered' | 'undelivered' | 'not_requested' | 'stale_scope' | 'artifact_unavailable' = 'not_requested';
  if (!verificationScopeIsCurrent(context, scope)) attestation = 'stale_scope';
  else if (cardId && !artifact) attestation = 'artifact_unavailable';
  else if (cardId && artifact) {
    const body = buildTestRunAttestationBody({
      card: { cardId }, passed,
      summary: `Remote verify ${passed ? 'passed' : 'failed'}: ${described} (exit ${exitCode})`,
      testsOutput: truncateTestsOutput(`${stdout}\n${stderr}`.trim()),
      sessionId: scope.sessionId, workspaceId: scope.workspaceId,
      idempotencyKey: attestationIdempotencyKey({ cardId, runId: companionRunId }),
      verificationArtifact: artifact,
    });
    attestation = await dispatchTestRunAttestation(attestationRuntimeWithUndeliveredNotice(context, scope), body);
  }
  const statusWord = hostCommandCopy(lang, passed ? 'statusWordPassed' : 'statusWordFailed');
  return {
    ok: passed,
    message: attestation === 'delivered'
      ? hostCommandCopy(lang, 'remoteVerifyOutcomeDelivered', { status: statusWord, code: exitCode })
      : attestation === 'undelivered' ? ATTESTATION_UNDELIVERED_MARKER
      : attestation === 'stale_scope' ? hostCommandCopy(lang, 'remoteVerifyOutcomeStale')
      : attestation === 'artifact_unavailable' ? hostCommandCopy(lang, 'remoteVerifyOutcomeArtifactUnavailable')
      : hostCommandCopy(lang, 'remoteVerifyOutcomeNoCard', { status: statusWord, code: exitCode }),
    data: { spec, exit_code: exitCode, passed, stdout, stderr, attestation },
  };
}


/**
 * Streaming + cancel registry for the webview-facing remote verification.
 * One active session at a time per window: starting a new run while one is
 * active is rejected instead of silently racing two processes.
 */
interface ActiveRemoteVerification {
  sessionId?: string;
  signal: { aborted: boolean };
}
let activeRemoteVerification: ActiveRemoteVerification | undefined;

const PYTESTABLE_EXTENSIONS = new Set(['.py']);

/**
 * Localized one-line outcome summaries for the streaming remote verification.
 * The host posts them before the webview can localize, so they ship in the
 * workspace response language (same resolution rule as provider host copy).
 */
type RemoteVerificationSummaryKind = 'passed' | 'failed' | 'timed_out' | 'cancelled' | 'interrupted' | 'artifact_unavailable';

const REMOTE_VERIFICATION_SUMMARY_COPY: Record<
  ComposerLanguage,
  Record<RemoteVerificationSummaryKind, string>
> = {
  'zh-CN': {
    artifact_unavailable: '运行已完成，但文件或哈希未确认；没有记录验证证据。',
    passed: '已验证通过 (exit {exit})',
    failed: '已验证未通过 (exit {exit})',
    timed_out: '远程验证超时,执行结果未知。',
    cancelled: '远程验证已停止,执行结果未知。',
    interrupted: '远程验证已中断,执行结果未知。',
  },
  'en-US': {
    artifact_unavailable: 'The run completed, but the artifact or hash could not be confirmed; no verification evidence was recorded.',
    passed: 'Verification passed (exit {exit})',
    failed: 'Verification failed (exit {exit})',
    timed_out: 'The remote verification timed out; its outcome is unknown.',
    cancelled: 'The remote verification was stopped; its outcome is unknown.',
    interrupted: 'The remote verification was interrupted; its outcome is unknown.',
  },
  'es-ES': {
    artifact_unavailable: 'La ejecución terminó, pero no se pudo confirmar el archivo o su hash; no se registró evidencia de verificación.',
    passed: 'Verificado como superado (exit {exit})',
    failed: 'Verificado como fallido (exit {exit})',
    timed_out: 'La verificación remota agotó el tiempo; su resultado es desconocido.',
    cancelled: 'La verificación remota se detuvo; su resultado es desconocido.',
    interrupted: 'La verificación remota se interrumpió; su resultado es desconocido.',
  },
  'fr-FR': {
    artifact_unavailable: 'L’exécution est terminée, mais le fichier ou son empreinte n’a pas pu être confirmé ; aucune preuve de vérification n’a été enregistrée.',
    passed: 'Vérifié : réussi (exit {exit})',
    failed: 'Vérifié : échoué (exit {exit})',
    timed_out: 'La vérification distante a expiré ; son résultat est inconnu.',
    cancelled: 'La vérification distante a été arrêtée ; son résultat est inconnu.',
    interrupted: 'La vérification distante a été interrompue ; son résultat est inconnu.',
  },
  'de-DE': {
    artifact_unavailable: 'Der Lauf ist beendet, aber Datei oder Hash konnten nicht bestätigt werden; es wurde kein Verifizierungsnachweis gespeichert.',
    passed: 'Verifiziert: bestanden (exit {exit})',
    failed: 'Verifiziert: fehlgeschlagen (exit {exit})',
    timed_out: 'Die Remote-Verifizierung hat Zeitüberschreitung; das Ergebnis ist unbekannt.',
    cancelled: 'Die Remote-Verifizierung wurde gestoppt; das Ergebnis ist unbekannt.',
    interrupted: 'Die Remote-Verifizierung wurde unterbrochen; das Ergebnis ist unbekannt.',
  },
  'ja-JP': {
    artifact_unavailable: '実行は完了しましたが、ファイルまたはハッシュを確認できず、検証証拠は記録されませんでした。',
    passed: '検証をパスしました (exit {exit})',
    failed: '検証はパスしませんでした (exit {exit})',
    timed_out: 'リモート検証がタイムアウトし、結果は不明です。',
    cancelled: 'リモート検証は停止され、結果は不明です。',
    interrupted: 'リモート検証は中断され、結果は不明です。',
  },
  'ko-KR': {
    artifact_unavailable: '실행은 완료되었지만 파일 또는 해시를 확인하지 못해 검증 증거가 기록되지 않았습니다.',
    passed: '검증 통과 (exit {exit})',
    failed: '검증 실패 (exit {exit})',
    timed_out: '원격 검증이 시간 초과되어 결과를 알 수 없습니다.',
    cancelled: '원격 검증이 중지되어 결과를 알 수 없습니다.',
    interrupted: '원격 검증이 중단되어 결과를 알 수 없습니다.',
  },
  'pt-BR': {
    artifact_unavailable: 'A execução terminou, mas o arquivo ou hash não pôde ser confirmado; nenhuma evidência de verificação foi registrada.',
    passed: 'Verificado como aprovado (exit {exit})',
    failed: 'Verificado como reprovado (exit {exit})',
    timed_out: 'A verificação remota excedeu o tempo; o resultado é desconhecido.',
    cancelled: 'A verificação remota foi cancelada; o resultado é desconhecido.',
    interrupted: 'A verificação remota foi interrompida; o resultado é desconhecido.',
  },
};

function remoteVerificationSummary(
  kind: RemoteVerificationSummaryKind,
  language: ComposerLanguage | undefined,
  exitCode?: number | null,
): string {
  const table = REMOTE_VERIFICATION_SUMMARY_COPY[language ?? 'en-US'] ?? REMOTE_VERIFICATION_SUMMARY_COPY['en-US'];
  return table[kind].split('{exit}').join(String(exitCode ?? '?'));
}

/** Workspace response language for host-posted summaries. */
function remoteVerificationLanguage(context: CommandContext, payload?: unknown): ComposerLanguage {
  const explicit =
    payload && typeof payload === 'object' ? (payload as Record<string, unknown>).responseLanguage : undefined;
  return resolveHostCommandLanguage(context, explicit);
}

function buildActiveFileVerificationSpec(
  activeFile: { fsPath: string; languageId?: string },
): RemoteProcessSpec | undefined {
  const extension = path.extname(activeFile.fsPath).toLowerCase();
  if (!PYTESTABLE_EXTENSIONS.has(extension)) {
    return undefined;
  }
  return {
    executable: 'python',
    args: ['-m', 'pytest', activeFile.fsPath, '-q', '--no-header'],
    timeout_ms: 10 * 60_000,
  };
}

export const TRAINING_VERIFICATION_TARGET_MISMATCH_MARKER = '[[trainer-training-verification-target-mismatch]]';

/** A UI assertion never selects a card; the host remains the authority. */
export interface RemoteActiveFileVerificationPayload {
  expectedCardId?: string;
}

export async function remoteVerifyActiveFileCommand(context: CommandContext, payload?: unknown): Promise<CommandExecutionResult> {
  const workspace = context.getHostState().workspace;
  const scope = captureVerificationScope(context);
  const language = remoteVerificationLanguage(context, payload);
  if (payload && typeof payload === 'object' && Object.prototype.hasOwnProperty.call(payload, 'expectedCardId')) {
    const expectedCardId = (payload as Record<string, unknown>).expectedCardId;
    if (typeof expectedCardId !== 'string' || !expectedCardId.trim() || expectedCardId.trim() !== scope.cardId) {
      return { ok: false, message: TRAINING_VERIFICATION_TARGET_MISMATCH_MARKER };
    }
  }
  const editor = vscode.window.activeTextEditor;
  if (!workspace.isRemoteWorkspace && !workspace.remoteName) return { ok: false,
    message: hostCommandCopy(language, 'remoteVerifyWindowRequired') };
  if (!(await context.trustGuard.ensureTrusted('run remote verification'))) return { ok: false,
    message: hostCommandCopy(language, 'remoteVerifyTrustRequired') };
  if (activeRemoteVerification) return { ok: false,
    message: hostCommandCopy(language, 'remoteVerifyAlreadyRunning') };
  if (!editor) return { ok: false, message: hostCommandCopy(language, 'remoteVerifyOpenFileFirst') };
  const spec = buildActiveFileVerificationSpec({ fsPath: editor.document.uri.fsPath });
  if (!spec) return { ok: false, message: hostCommandCopy(language, 'remoteVerifyPythonOnly') };
  const verificationFileName = path.basename(editor.document.uri.fsPath);

  // Reserve before any further await; onStart can arrive much later than the user's second click.
  const run: ActiveRemoteVerification = { signal: { aborted: false } };
  activeRemoteVerification = run;
  let capabilities;
  try { capabilities = await context.workspaceGateway.capabilities(); }
  catch (error) {
    if (activeRemoteVerification === run) activeRemoteVerification = undefined;
    context.outputChannel.appendLine(`[remote] capabilities unavailable: ${error instanceof Error ? error.name : 'Request failed'}`);
    return { ok: false, message: hostCommandCopy(language, 'remoteVerifyCompanionReconnect') };
  }
  if (!capabilities.companionAvailable || !capabilities.verify || !verificationScopeIsCurrent(context, scope)) {
    if (activeRemoteVerification === run) activeRemoteVerification = undefined;
    return { ok: false, message: hostCommandCopy(language, 'remoteVerifyCompanionNotInWorkspace') };
  }
  try { await assertRemoteVerificationFileScope(context, editor.document.uri); }
  catch {
    if (activeRemoteVerification === run) activeRemoteVerification = undefined;
    return { ok: false, message: hostCommandCopy(language, 'remoteVerifyFileOutsideProject') };
  }
  let captured: CapturedRemoteArtifact | undefined;
  try {
    const environment = await context.workspaceGateway.environment();
    spec.executable = environment.os === 'win32' ? 'python' : 'python3';
    if (scope.cardId) captured = await captureRemoteVerificationArtifact(context, editor.document.uri);
  } catch {
    context.outputChannel.appendLine('[remote] remote environment or artifact unavailable; trusted evidence requires a stable hash.');
  }
  if (!verificationScopeIsCurrent(context, scope) || run.signal.aborted) {
    if (activeRemoteVerification === run) activeRemoteVerification = undefined;
    return { ok: false, message: hostCommandCopy(language, 'remoteVerifyCancelledBeforeStart') };
  }
  const post = (message: unknown) => {
    if (verificationScopeIsCurrent(context, scope)) void context.workbench.postMessage(message);
  };
  void context.workspaceGateway.runVerification(spec, {
    signal: run.signal,
    onStart: session => {
      run.sessionId = session.session_id;
      post({ type: 'remoteVerification/started', payload: { sessionId: session.session_id,
        ...(scope.cardId ? { cardId: scope.cardId } : {}),
        spec: { executable: spec.executable, args: spec.args } } });
    },
    onChunk: chunk => {
      if (run.sessionId) post({ type: 'remoteVerification/stream', payload: {
        sessionId: run.sessionId, ...(scope.cardId ? { cardId: scope.cardId } : {}), stream: chunk.stream, text: chunk.text } });
    },
  }).then(async verification => {
    const completed = verification.state === 'completed' && typeof verification.exit_code === 'number';
    const exitCode = completed ? verification.exit_code : null;
    const passed = completed && verification.result === 'passed' && exitCode === 0;
    let delivery: 'delivered' | 'undelivered' | 'not_requested' = 'not_requested';
    if (scope.cardId && completed && verificationScopeIsCurrent(context, scope)) {
      let artifact: RemoteVerificationArtifact | undefined;
      try { artifact = await finishRemoteVerificationArtifact(context, captured, run.sessionId ?? '', verification); }
      catch { context.outputChannel.appendLine('[remote] remote artifact hash unavailable after verification; no evidence was recorded.'); }
      if (artifact && verificationScopeIsCurrent(context, scope)) {
      const body = buildTestRunAttestationBody({ card: { cardId: scope.cardId }, passed,
        summary: `Remote verify ${passed ? 'passed' : 'failed'} on ${workspace.remoteName ?? 'remote'}: ${verificationFileName} (exit ${exitCode})`,
        testsOutput: truncateTestsOutput(`${verification.stdout}\n${verification.stderr}`.trim()),
        sessionId: scope.sessionId, workspaceId: scope.workspaceId,
        idempotencyKey: attestationIdempotencyKey({ cardId: scope.cardId, runId: run.sessionId ?? '' }),
        verificationArtifact: artifact,
      });
      delivery = await dispatchTestRunAttestation(attestationRuntimeWithUndeliveredNotice(context, scope), body);
      }
    }
    const state = verification.state === 'completed' && !completed ? 'connection_lost' : verification.state;
    const summary = completed ? remoteVerificationSummary(scope.cardId && delivery === 'not_requested' ? 'artifact_unavailable' : passed ? 'passed' : 'failed', language, exitCode)
      : remoteVerificationSummary(state === 'timed_out' ? 'timed_out' : state === 'cancelled' ? 'cancelled' : 'interrupted', language);
    post({ type: 'remoteVerification/finished', payload: { sessionId: run.sessionId ?? '', state,
      ...(scope.cardId ? { cardId: scope.cardId } : {}),
      exitCode, ...(completed ? { passed } : {}), summary, attestation: delivery } });
  }).catch(error => {
    context.outputChannel.appendLine(`[remote] verification interrupted: ${error instanceof Error ? error.name : 'Request failed'}`);
    post({ type: 'remoteVerification/finished', payload: { sessionId: run.sessionId ?? '',
      ...(scope.cardId ? { cardId: scope.cardId } : {}),
      state: 'connection_lost', exitCode: null, summary: remoteVerificationSummary('interrupted', language) } });
  }).finally(() => { if (activeRemoteVerification === run) activeRemoteVerification = undefined; });
  return { ok: true, message: hostCommandCopy(language, 'remoteVerifyStarting', { remote: workspace.remoteName ?? 'remote' }) };
}

export async function remoteVerifyCancelCommand(context: CommandContext): Promise<CommandExecutionResult> {
  if (activeRemoteVerification) activeRemoteVerification.signal.aborted = true;
  return { ok: true, message: hostCommandCopy(resolveHostCommandLanguage(context), 'remoteVerifyStopRequested') };
}


/**
 * One-shot companion install-state query for the Settings panel. User
 * initiated (the panel asks when it becomes visible); no background polling.
 */
export async function remoteCompanionStateCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const workspace = context.getHostState().workspace;
  const remoteName = workspace.remoteName;
  let capabilities;
  try {
    capabilities = await context.workspaceGateway.capabilities();
  } catch {
    capabilities = undefined;
  }
  const state = deriveCompanionInstallState({
    capabilities: capabilities
      ? {
          protocol_version: (capabilities.protocolVersion ?? 0) as 2,
          available: Boolean(capabilities.companionAvailable),
          capabilities: {
            stat: false,
            read_file: false,
            list_directory: false,
            find_files: false,
            search_text: false,
            hash_artifact: false,
            diagnostics: false,
            environment: false,
            verify: false,
          },
        }
      : undefined,
    connectionLost: false,
  });
  return {
    ok: true,
    message: hostCommandCopy(resolveHostCommandLanguage(context), 'remoteCompanionStateReport', { state }),
    data: { state, remoteName },
  };
}
