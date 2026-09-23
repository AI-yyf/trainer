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
  command?: string;
  cwd?: string;
  cardId?: string;
}

/**
 * Run one explicit verification command in the REMOTE workspace via the
 * Companion and attest the outcome to the sidecar as host-trusted evidence.
 *
 * Honesty contract: only a completed run (numeric exit code) is attested. A
 * companion/transport failure or an interrupted process records NO evidence —
 * an interrupted run must never become "failed", and nothing here can create
 * "passed" without a real remote execution.
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
  const command = typeof record.command === 'string' ? record.command.trim() : '';
  const cwd = typeof record.cwd === 'string' && record.cwd.trim() ? record.cwd.trim() : undefined;
  if (!command) {
    return { ok: false, message: 'A verification command is required.' };
  }

  const capabilities = await context.workspaceGateway.capabilities();
  if (!capabilities.companionAvailable || !capabilities.verify) {
    return {
      ok: false,
      message:
        'Remote Workspace Companion is not available in this window. Run "Trainer: Install Remote Workspace Support", reload the remote window, then verify again.',
    };
  }

  let stdout = '';
  let stderr = '';
  let exitCode: number | null;
  let passed: boolean;
  try {
    const verification = await context.workspaceGateway.verify({ command, ...(cwd ? { cwd } : {}) });
    stdout = verification.stdout ?? '';
    stderr = verification.stderr ?? '';
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
      summary: `Remote verify ${passed ? 'passed' : 'failed'}: ${command} (exit ${exitCode})`,
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
    data: { command, exit_code: exitCode, passed, stdout, stderr },
  };
}
