import * as path from 'node:path';
import * as vscode from 'vscode';

import type { RemoteProcessSpec } from '../../../shared/src/remoteProtocol';
import { deriveCompanionInstallState } from '../../../shared/src/companionInstallState';
import type { ComposerLanguage } from '../../../shared/src/types';
import { resolveProviderHostLanguage } from './providerHostCopy';
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
  const requestedCard = typeof record.cardId === 'string' && record.cardId.trim() ? record.cardId.trim() : undefined;
  const scope = captureVerificationScope(context, requestedCard);
  if (!workspace.isRemoteWorkspace && !workspace.remoteName) {
    return {
      ok: false,
      message: 'Remote verification is only available in a Remote-SSH, WSL, Tunnel, or Dev Container window.',
    };
  }
  if (!(await context.trustGuard.ensureTrusted('run remote verification'))) {
    return { ok: false, message: 'Workspace trust is required to run remote verification.' };
  }
  const spec = parseSpec(record);
  if (!spec) {
    return { ok: false, message: 'A verification executable is required.' };
  }

  const capabilities = await context.workspaceGateway.capabilities();
  if (!capabilities.companionAvailable || !capabilities.verify) {
    return {
      ok: false,
      message:
        'Remote Workspace Companion is not available in this window. Run "Trainer: Install Remote Workspace Support", reload the remote window, then verify again.',
    };
  }

  if (!verificationScopeIsCurrent(context, scope)) return { ok: false, message: 'Workspace, session or card changed before remote verification started.' };
  const described = describeSpec(spec);
  let stdout = '';
  let stderr = '';
  let exitCode: number | null = null;
  let passed = false;
  // Companion-side session id: the stable run identity behind the attestation
  // idempotency key, so a delivery retry can never double-record evidence.
  let companionRunId = '';
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
          ? 'the run timed out'
          : verification.state === 'cancelled'
            ? 'the run was cancelled'
            : 'the companion connection was lost';
      context.outputChannel.appendLine(`[remote] verification interrupted: ${reason}`);
      return {
        ok: false,
        message: `Remote verification was interrupted (${reason}), so no evidence was recorded.`,
        data: { spec, state: verification.state, stdout, stderr },
      };
    }
    exitCode = verification.exit_code ?? null;
    passed = verification.result === 'passed' && exitCode === 0;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    context.outputChannel.appendLine(`[remote] verification did not complete: ${detail}`);
    return {
      ok: false,
      message: `Remote verification did not complete, so no evidence was recorded: ${detail}`,
    };
  }
  if (exitCode === null) {
    return {
      ok: false,
      message: 'Remote verification was interrupted before producing an exit code; no evidence was recorded.',
    };
  }

  const cardId = scope.cardId;
  let attestation: 'delivered' | 'undelivered' | 'not_requested' | 'stale_scope' = 'not_requested';
  if (!verificationScopeIsCurrent(context, scope)) attestation = 'stale_scope';
  else if (cardId) {
    const body = buildTestRunAttestationBody({
      card: { cardId }, passed,
      summary: `Remote verify ${passed ? 'passed' : 'failed'}: ${described} (exit ${exitCode})`,
      testsOutput: truncateTestsOutput(`${stdout}\n${stderr}`.trim()),
      sessionId: scope.sessionId, workspaceId: scope.workspaceId,
      idempotencyKey: attestationIdempotencyKey({ cardId, runId: companionRunId }),
    });
    attestation = await dispatchTestRunAttestation(attestationRuntimeWithUndeliveredNotice(context, scope), body);
  }
  return {
    ok: passed,
    message: attestation === 'delivered'
      ? `Remote verification ${passed ? 'passed' : 'failed'} (exit ${exitCode}); the result was attested to the trainer.`
      : attestation === 'undelivered' ? ATTESTATION_UNDELIVERED_MARKER
      : attestation === 'stale_scope' ? 'Remote verification completed in an earlier workspace, session or card; no evidence was recorded.'
      : `Remote verification ${passed ? 'passed' : 'failed'} (exit ${exitCode}); no live practice card, so nothing was attested.`,
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
type RemoteVerificationSummaryKind = 'passed' | 'failed' | 'timed_out' | 'cancelled' | 'interrupted';

const REMOTE_VERIFICATION_SUMMARY_COPY: Record<
  ComposerLanguage,
  Record<RemoteVerificationSummaryKind, string>
> = {
  'zh-CN': {
    passed: '已验证通过 (exit {exit})',
    failed: '已验证未通过 (exit {exit})',
    timed_out: '远程验证超时,执行结果未知。',
    cancelled: '远程验证已停止,执行结果未知。',
    interrupted: '远程验证已中断,执行结果未知。',
  },
  'en-US': {
    passed: 'Verification passed (exit {exit})',
    failed: 'Verification failed (exit {exit})',
    timed_out: 'The remote verification timed out; its outcome is unknown.',
    cancelled: 'The remote verification was stopped; its outcome is unknown.',
    interrupted: 'The remote verification was interrupted; its outcome is unknown.',
  },
  'es-ES': {
    passed: 'Verificado como superado (exit {exit})',
    failed: 'Verificado como fallido (exit {exit})',
    timed_out: 'La verificación remota agotó el tiempo; su resultado es desconocido.',
    cancelled: 'La verificación remota se detuvo; su resultado es desconocido.',
    interrupted: 'La verificación remota se interrumpió; su resultado es desconocido.',
  },
  'fr-FR': {
    passed: 'Vérifié : réussi (exit {exit})',
    failed: 'Vérifié : échoué (exit {exit})',
    timed_out: 'La vérification distante a expiré ; son résultat est inconnu.',
    cancelled: 'La vérification distante a été arrêtée ; son résultat est inconnu.',
    interrupted: 'La vérification distante a été interrompue ; son résultat est inconnu.',
  },
  'de-DE': {
    passed: 'Verifiziert: bestanden (exit {exit})',
    failed: 'Verifiziert: fehlgeschlagen (exit {exit})',
    timed_out: 'Die Remote-Verifizierung hat Zeitüberschreitung; das Ergebnis ist unbekannt.',
    cancelled: 'Die Remote-Verifizierung wurde gestoppt; das Ergebnis ist unbekannt.',
    interrupted: 'Die Remote-Verifizierung wurde unterbrochen; das Ergebnis ist unbekannt.',
  },
  'ja-JP': {
    passed: '検証をパスしました (exit {exit})',
    failed: '検証はパスしませんでした (exit {exit})',
    timed_out: 'リモート検証がタイムアウトし、結果は不明です。',
    cancelled: 'リモート検証は停止され、結果は不明です。',
    interrupted: 'リモート検証は中断され、結果は不明です。',
  },
  'ko-KR': {
    passed: '검증 통과 (exit {exit})',
    failed: '검증 실패 (exit {exit})',
    timed_out: '원격 검증이 시간 초과되어 결과를 알 수 없습니다.',
    cancelled: '원격 검증이 중지되어 결과를 알 수 없습니다.',
    interrupted: '원격 검증이 중단되어 결과를 알 수 없습니다.',
  },
  'pt-BR': {
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

/** Workspace response language for host-posted summaries (provider copy rule). */
function remoteVerificationLanguage(context: CommandContext): ComposerLanguage | undefined {
  return resolveProviderHostLanguage(
    undefined,
    context.getHostState().bootstrap.memory?.workspace?.responseLanguage,
  );
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

export async function remoteVerifyActiveFileCommand(context: CommandContext): Promise<CommandExecutionResult> {
  const workspace = context.getHostState().workspace;
  const scope = captureVerificationScope(context);
  const editor = vscode.window.activeTextEditor;
  if (!workspace.isRemoteWorkspace && !workspace.remoteName) return { ok: false,
    message: 'Remote verification is only available in a Remote-SSH, WSL, Tunnel, or Dev Container window.' };
  if (!(await context.trustGuard.ensureTrusted('run remote verification'))) return { ok: false,
    message: 'Workspace trust is required to run remote verification.' };
  if (activeRemoteVerification) return { ok: false,
    message: 'A remote verification is already running. Stop it before starting another.' };
  if (!editor) return { ok: false, message: 'Open the practice file before verifying it.' };
  const spec = buildActiveFileVerificationSpec({ fsPath: editor.document.uri.fsPath });
  if (!spec) return { ok: false, message: 'Remote file verification currently supports Python practice files (pytest).' };

  // Reserve before any further await; onStart can arrive much later than the user's second click.
  const run: ActiveRemoteVerification = { signal: { aborted: false } };
  activeRemoteVerification = run;
  const language = remoteVerificationLanguage(context);
  let capabilities;
  try { capabilities = await context.workspaceGateway.capabilities(); }
  catch (error) {
    if (activeRemoteVerification === run) activeRemoteVerification = undefined;
    context.outputChannel.appendLine(`[remote] capabilities unavailable: ${error instanceof Error ? error.name : 'Request failed'}`);
    return { ok: false, message: 'Remote Workspace Companion is unavailable. Reconnect before verifying.' };
  }
  if (!capabilities.companionAvailable || !capabilities.verify || !verificationScopeIsCurrent(context, scope)) {
    if (activeRemoteVerification === run) activeRemoteVerification = undefined;
    return { ok: false, message: 'Remote Workspace Companion is not available in this workspace. Reconnect before verifying.' };
  }
  const post = (message: unknown) => {
    if (verificationScopeIsCurrent(context, scope)) void context.workbench.postMessage(message);
  };
  void context.workspaceGateway.runVerification(spec, {
    signal: run.signal,
    onStart: session => {
      run.sessionId = session.session_id;
      post({ type: 'remoteVerification/started', payload: { sessionId: session.session_id,
        spec: { executable: spec.executable, args: spec.args } } });
    },
    onChunk: chunk => {
      if (run.sessionId) post({ type: 'remoteVerification/stream', payload: {
        sessionId: run.sessionId, stream: chunk.stream, text: chunk.text } });
    },
  }).then(async verification => {
    const completed = verification.state === 'completed' && typeof verification.exit_code === 'number';
    const exitCode = completed ? verification.exit_code : null;
    const passed = completed && verification.result === 'passed' && exitCode === 0;
    let delivery: 'delivered' | 'undelivered' | 'not_requested' = 'not_requested';
    if (scope.cardId && completed && verificationScopeIsCurrent(context, scope)) {
      const body = buildTestRunAttestationBody({ card: { cardId: scope.cardId }, passed,
        summary: `Remote verify ${passed ? 'passed' : 'failed'} on ${workspace.remoteName ?? 'remote'}: ${path.basename(spec.args[spec.args.length - 1] ?? '')} (exit ${exitCode})`,
        testsOutput: truncateTestsOutput(`${verification.stdout}\n${verification.stderr}`.trim()),
        sessionId: scope.sessionId, workspaceId: scope.workspaceId,
        idempotencyKey: attestationIdempotencyKey({ cardId: scope.cardId, runId: run.sessionId ?? '' }),
      });
      delivery = await dispatchTestRunAttestation(attestationRuntimeWithUndeliveredNotice(context, scope), body);
    }
    const state = verification.state === 'completed' && !completed ? 'connection_lost' : verification.state;
    const summary = completed ? remoteVerificationSummary(passed ? 'passed' : 'failed', language, exitCode)
      : remoteVerificationSummary(state === 'timed_out' ? 'timed_out' : state === 'cancelled' ? 'cancelled' : 'interrupted', language);
    post({ type: 'remoteVerification/finished', payload: { sessionId: run.sessionId ?? '', state,
      exitCode, ...(completed ? { passed } : {}), summary, attestation: delivery } });
  }).catch(error => {
    context.outputChannel.appendLine(`[remote] verification interrupted: ${error instanceof Error ? error.name : 'Request failed'}`);
    post({ type: 'remoteVerification/finished', payload: { sessionId: run.sessionId ?? '',
      state: 'connection_lost', exitCode: null, summary: remoteVerificationSummary('interrupted', language) } });
  }).finally(() => { if (activeRemoteVerification === run) activeRemoteVerification = undefined; });
  return { ok: true, message: `Remote verification starting on ${workspace.remoteName ?? 'remote'}.` };
}

export async function remoteVerifyCancelCommand(_context: CommandContext): Promise<CommandExecutionResult> {
  if (activeRemoteVerification) activeRemoteVerification.signal.aborted = true;
  return { ok: true, message: 'Stop requested for the running remote verification.' };
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
    message: `Remote support state: ${state}.`,
    data: { state, remoteName },
  };
}
