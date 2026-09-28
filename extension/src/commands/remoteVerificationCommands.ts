import * as path from 'node:path';
import * as vscode from 'vscode';

import type { RemoteProcessSpec } from '../../../shared/src/remoteProtocol';
import { deriveCompanionInstallState } from '../../../shared/src/companionInstallState';
import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';
import {
  buildTestRunAttestationBody,
  dispatchTestRunAttestation,
  resolveAttestationWorkspaceId,
  resolveLivePracticeCardId,
  truncateTestsOutput,
} from '../testing/trainingAttestation';

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
  if (!workspace.isRemoteWorkspace && !workspace.remoteName) {
    return {
      ok: false,
      message: 'Remote verification is only available in a Remote-SSH, WSL, Tunnel, or Dev Container window.',
    };
  }
  if (!(await context.trustGuard.ensureTrusted('run remote verification'))) {
    return { ok: false, message: 'Workspace trust is required to run remote verification.' };
  }
  const record = (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown>;
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

  const described = describeSpec(spec);
  let stdout = '';
  let stderr = '';
  let exitCode: number | null = null;
  let passed = false;
  try {
    const verification = await context.workspaceGateway.runVerification(spec, {
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

  const hostState = context.getHostState();
  const cardId = typeof record.cardId === 'string' && record.cardId.trim() ? record.cardId.trim() : resolveLivePracticeCardId(hostState);
  if (cardId) {
    const body = buildTestRunAttestationBody({
      card: { cardId },
      passed,
      summary: `Remote verify ${passed ? 'passed' : 'failed'}: ${described} (exit ${exitCode})`,
      testsOutput: truncateTestsOutput(`${stdout}\n${stderr}`.trim()),
      sessionId: context.getSessionId(),
      workspaceId: resolveAttestationWorkspaceId(hostState),
    });
    void dispatchTestRunAttestation(context, body);
  }

  return {
    ok: passed,
    message: cardId
      ? `Remote verification ${passed ? 'passed' : 'failed'} (exit ${exitCode}); the result was attested to the trainer.`
      : `Remote verification ${passed ? 'passed' : 'failed'} (exit ${exitCode}); no live practice card, so nothing was attested.`,
    data: { spec, exit_code: exitCode, passed, stdout, stderr },
  };
}


/**
 * Streaming + cancel registry for the webview-facing remote verification.
 * One active session at a time per window: starting a new run while one is
 * active is rejected instead of silently racing two processes.
 */
const activeRemoteVerification: {
  sessionId?: string;
  signal: { aborted: boolean };
} = { signal: { aborted: false } };

const PYTESTABLE_EXTENSIONS = new Set(['.py']);

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

export async function remoteVerifyActiveFileCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const workspace = context.getHostState().workspace;
  if (!workspace.isRemoteWorkspace && !workspace.remoteName) {
    return {
      ok: false,
      message:
        'Remote verification is only available in a Remote-SSH, WSL, Tunnel, or Dev Container window.',
    };
  }
  if (!(await context.trustGuard.ensureTrusted('run remote verification'))) {
    return { ok: false, message: 'Workspace trust is required to run remote verification.' };
  }
  if (activeRemoteVerification.sessionId) {
    return {
      ok: false,
      message: 'A remote verification is already running. Stop it before starting another.',
    };
  }
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    return { ok: false, message: 'Open the practice file before verifying it.' };
  }
  const spec = buildActiveFileVerificationSpec({ fsPath: editor.document.uri.fsPath });
  if (!spec) {
    return {
      ok: false,
      message: 'Remote file verification currently supports Python practice files (pytest).',
    };
  }

  const capabilities = await context.workspaceGateway.capabilities();
  if (!capabilities.companionAvailable || !capabilities.verify) {
    return {
      ok: false,
      message:
        'Remote Workspace Companion is not available in this window. Run "Trainer: Install Remote Workspace Support", reload the remote window, then verify again.',
    };
  }

  activeRemoteVerification.signal = { aborted: false };
  const signal = activeRemoteVerification.signal;
  void context.workspaceGateway
    .runVerification(spec, {
      signal,
      onStart: (session) => {
        activeRemoteVerification.sessionId = session.session_id;
        void context.workbench.postMessage({
          type: 'remoteVerification/started',
          payload: {
            sessionId: session.session_id,
            spec: { executable: spec.executable, args: spec.args },
          },
        });
      },
      onChunk: (chunk) => {
        if (!activeRemoteVerification.sessionId) {
          return;
        }
        void context.workbench.postMessage({
          type: 'remoteVerification/stream',
          payload: {
            sessionId: activeRemoteVerification.sessionId,
            stream: chunk.stream,
            text: chunk.text,
          },
        });
      },
    })
    .then(async (verification) => {
      const sessionId = activeRemoteVerification.sessionId;
      activeRemoteVerification.sessionId = undefined;
      if (!sessionId) {
        return;
      }
      const completed = verification.state === 'completed';
      const exitCode = verification.exit_code ?? null;
      const passed = completed && verification.result === 'passed' && exitCode === 0;

      const hostState = context.getHostState();
      const cardId = resolveLivePracticeCardId(hostState);
      if (cardId && completed) {
        const body = buildTestRunAttestationBody({
          card: { cardId },
          passed,
          summary: `Remote verify ${passed ? 'passed' : 'failed'} on ${workspace.remoteName ?? 'remote'}: ${path.basename(spec.args[spec.args.length - 1] ?? '')} (exit ${exitCode})`,
          testsOutput: truncateTestsOutput(`${verification.stdout}\n${verification.stderr}`.trim()),
          sessionId: context.getSessionId(),
          workspaceId: resolveAttestationWorkspaceId(hostState),
        });
        void dispatchTestRunAttestation(context, body);
      }

      const summary = completed
        ? `已验证${passed ? '通过' : '未通过'} (exit ${exitCode})`
        : verification.state === 'timed_out'
          ? '远程验证超时,执行结果未知。'
          : verification.state === 'cancelled'
            ? '远程验证已停止,执行结果未知。'
            : '远程验证已中断,执行结果未知。';
      void context.workbench.postMessage({
        type: 'remoteVerification/finished',
        payload: {
          sessionId,
          state: verification.state,
          exitCode,
          ...(completed ? { passed } : {}),
          summary,
        },
      });
    })
    .catch((error) => {
      activeRemoteVerification.sessionId = undefined;
      void context.workbench.postMessage({
        type: 'remoteVerification/finished',
        payload: {
          sessionId: '',
          state: 'connection_lost',
          exitCode: null,
          summary: `远程验证已中断,执行结果未知。${error instanceof Error ? error.message : String(error)}`,
        },
      });
    });

  return {
    ok: true,
    message: `Remote verification starting on ${workspace.remoteName ?? 'remote'}.`,
  };
}

export async function remoteVerifyCancelCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  activeRemoteVerification.signal.aborted = true;
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
