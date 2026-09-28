/**
 * Remote verification session management (protocol v2).
 *
 * Pure state machinery, platform process control injected. Sessions are
 * forward-only (running → completed | cancelled | timed_out | spawn_failed;
 * connection_lost can only replace running), duplicate starts of an identical
 * running spec return the same session, completion is idempotent, and output
 * is buffered with a cap so pollers read incremental chunks by offset.
 */
import type {
  RemoteEnvironment,
  RemoteProcessSpec,
  RemoteProcessState,
  RemoteVerificationStatus,
} from '../../shared/src/remoteProtocol';

export const VERIFICATION_OUTPUT_CAP = 200_000;

export type SpawnedVerificationProcess = {
  pid: number | undefined;
  /** Kill the whole process tree (POSIX group / Windows taskkill /t). */
  killTree: () => void;
  /** Resolves once the process is gone: exit code, or the spawn failure detail. */
  exited: Promise<{ code: number | null; error?: string }>;
  onStdout: (listener: (chunk: string) => void) => void;
  onStderr: (listener: (chunk: string) => void) => void;
};

export type VerificationSpawnFn = (
  spec: RemoteProcessSpec,
  cwd: string | undefined,
) => SpawnedVerificationProcess;

export type VerificationSessionManagerOptions = {
  spawnVerification: VerificationSpawnFn;
  environment: () => Promise<RemoteEnvironment> | RemoteEnvironment;
  now?: () => number;
  /** Kill the tree after this long when the spec carries no timeout. */
  defaultTimeoutMs?: number;
  maxSessions?: number;
  generateSessionId?: () => string;
  /** Injectable for tests; defaults to the global timers. */
  setTimeoutFn?: (callback: () => void, ms: number) => unknown;
  clearTimeoutFn?: (timer: unknown) => void;
};

type SessionRecord = {
  sessionId: string;
  spec: RemoteProcessSpec;
  state: RemoteProcessState;
  result?: 'passed' | 'failed';
  exitCode?: number | null;
  startedAt: string;
  finishedAt?: string;
  stdout: string;
  stderr: string;
  environment?: RemoteEnvironment;
  error?: string;
  killTree?: () => void;
  runningKey?: string;
  timer?: unknown;
};

const TERMINAL_STATES: ReadonlySet<RemoteProcessState> = new Set([
  'completed',
  'cancelled',
  'timed_out',
  'spawn_failed',
  'connection_lost',
]);

export function isTerminalVerificationState(state: RemoteProcessState): boolean {
  return TERMINAL_STATES.has(state);
}

function runningKeyOf(spec: RemoteProcessSpec): string {
  return JSON.stringify({
    executable: spec.executable,
    args: [...spec.args],
    cwd: spec.cwd ?? '',
  });
}

function appendCapped(buffer: string, chunk: string): string {
  const merged = buffer + chunk;
  if (merged.length <= VERIFICATION_OUTPUT_CAP) {
    return merged;
  }
  // Keep the tail: later output matters more when diagnosing a failed run.
  return merged.slice(merged.length - VERIFICATION_OUTPUT_CAP);
}

export function createVerificationSessionManager(options: VerificationSessionManagerOptions) {
  const {
    spawnVerification,
    environment,
    now = () => Date.now(),
    defaultTimeoutMs = 10 * 60_000,
    maxSessions = 32,
    generateSessionId = () =>
      `vrf-${now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`,
    setTimeoutFn = (callback: () => void, ms: number) => setTimeout(callback, ms),
    clearTimeoutFn = (timer: unknown) => clearTimeout(timer as ReturnType<typeof setTimeout>),
  } = options;

  const sessions = new Map<string, SessionRecord>();

  function settle(
    session: SessionRecord,
    next: Exclude<RemoteProcessState, 'running'>,
    detail: { code?: number | null; error?: string } = {},
  ): void {
    if (isTerminalVerificationState(session.state)) {
      return; // forward-only
    }
    if (session.timer) {
      clearTimeoutFn(session.timer);
      session.timer = undefined;
    }
    session.state = next;
    if (detail.code !== undefined) {
      session.exitCode = detail.code;
    }
    if (detail.error !== undefined) {
      session.error = detail.error;
    }
    session.finishedAt = new Date(now()).toISOString();
    if (next === 'completed') {
      session.result = (session.exitCode ?? 1) === 0 ? 'passed' : 'failed';
    }
    session.killTree = undefined;
    session.runningKey = undefined;
  }

  function evictOverflow(): void {
    let terminal: SessionRecord[] = [];
    for (const record of sessions.values()) {
      if (isTerminalVerificationState(record.state)) {
        terminal = terminal.concat(record);
      }
    }
    terminal.sort((a, b) => (a.finishedAt ?? '').localeCompare(b.finishedAt ?? ''));
    let overflow = sessions.size - maxSessions;
    for (const record of terminal) {
      if (overflow <= 0) {
        break;
      }
      sessions.delete(record.sessionId);
      overflow -= 1;
    }
  }

  return {
    /** Idempotent for an identical running spec: returns the same session. */
    async startSession(spec: RemoteProcessSpec): Promise<RemoteVerificationStatus> {
      const key = runningKeyOf(spec);
      for (const record of sessions.values()) {
        if (record.runningKey === key && record.state === 'running') {
          return this.status(record.sessionId, 0, 0);
        }
      }

      const environmentSnapshot = await environment();
      const sessionId = generateSessionId();
      const session: SessionRecord = {
        sessionId,
        spec,
        state: 'running',
        startedAt: new Date(now()).toISOString(),
        stdout: '',
        stderr: '',
        environment: environmentSnapshot,
        runningKey: key,
      };
      sessions.set(sessionId, session);

      let spawned: SpawnedVerificationProcess;
      try {
        spawned = spawnVerification(spec, spec.cwd || undefined);
      } catch (error) {
        settle(session, 'spawn_failed', {
          error: error instanceof Error ? error.message : String(error),
        });
        return this.status(sessionId, 0, 0);
      }

      session.killTree = spawned.killTree;
      spawned.onStdout((chunk) => {
        session.stdout = appendCapped(session.stdout, chunk);
      });
      spawned.onStderr((chunk) => {
        session.stderr = appendCapped(session.stderr, chunk);
      });
      void spawned.exited.then(
        ({ code, error }) => {
          if (code !== null && code !== undefined) {
            settle(session, 'completed', { code });
          } else {
            settle(session, 'spawn_failed', { error: error ?? 'process failed to start' });
          }
        },
        (error) => {
          settle(session, 'spawn_failed', {
            error: error instanceof Error ? error.message : String(error),
          });
        },
      );

      const timeoutMs =
        typeof spec.timeout_ms === 'number' && spec.timeout_ms > 0
          ? spec.timeout_ms
          : defaultTimeoutMs;
      session.timer = setTimeoutFn(() => {
        if (session.state === 'running') {
          session.killTree?.();
          settle(session, 'timed_out', { error: `timed out after ${timeoutMs}ms` });
        }
      }, timeoutMs);

      evictOverflow();
      return this.status(sessionId, 0, 0);
    },

    status(sessionId: string, stdoutOffset = 0, stderrOffset = 0): RemoteVerificationStatus {
      const session = sessions.get(sessionId);
      if (!session) {
        throw new Error(`Unknown verification session: ${sessionId}`);
      }
      const stdoutChunk = session.stdout.slice(Math.max(0, stdoutOffset));
      const stderrChunk = session.stderr.slice(Math.max(0, stderrOffset));
      const status: RemoteVerificationStatus = {
        session_id: session.sessionId,
        state: session.state,
        started_at: session.startedAt,
        finished_at: session.finishedAt,
        stdout_chunk: stdoutChunk,
        stderr_chunk: stderrChunk,
        stdout_total: session.stdout.length,
        stderr_total: session.stderr.length,
        environment: session.environment as RemoteEnvironment,
        spec: session.spec,
      };
      if (isTerminalVerificationState(session.state)) {
        status.exit_code = session.exitCode ?? null;
        if (session.result) {
          status.result = session.result;
        }
        if (session.error) {
          status.error = session.error;
        }
      }
      return status;
    },

    cancel(sessionId: string): RemoteVerificationStatus {
      const session = sessions.get(sessionId);
      if (!session) {
        throw new Error(`Unknown verification session: ${sessionId}`);
      }
      if (session.state === 'running') {
        session.killTree?.();
        settle(session, 'cancelled', { code: null });
      }
      return this.status(sessionId, session.stdout.length, session.stderr.length);
    },

    /** Companion shutdown / bridge loss: running work becomes connection_lost. */
    disposeAll(): void {
      for (const session of sessions.values()) {
        if (session.state === 'running') {
          session.killTree?.();
          settle(session, 'connection_lost', { error: 'companion connection lost' });
        }
      }
      sessions.clear();
    },

    activeCount(): number {
      let count = 0;
      for (const session of sessions.values()) {
        if (session.state === 'running') {
          count += 1;
        }
      }
      return count;
    },
  };
}
