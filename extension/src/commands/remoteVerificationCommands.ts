import type { RemoteProcessSpec } from '../../../shared/src/remoteProtocol';
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
