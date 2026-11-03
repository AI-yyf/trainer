import { BROWSER_CAPTURE } from '../core/constants';

/**
 * Library freshness poller for browser captures.
 *
 * A capture writes to the sidecar without starting a coaching turn, so the
 * workbench snapshot the webview already holds does not know about it. While a
 * workbench surface is visible, poll a cheap library fingerprint and fetch a
 * fresh /memory/summary only when the resource-id set changes. The first
 * visible read refreshes too, so a capture made while the workbench was hidden
 * is never swallowed; subsequent unchanged reads are no-ops.
 *
 * The poller is workspace-scoped end to end: a response stamped with another
 * workspace is reported and ignored, never merged into this workbench.
 */

export interface BrowserLibraryRevision {
  /** Resolved workspace/context id returned by the sidecar. */
  workspaceId: string;
  /** Raw workspace id the host asked for (survives path -> context alias). */
  requestedWorkspaceId: string;
  count: number;
  revision: string;
}

export interface BrowserLibraryPollerOptions {
  /** Resolves the sidecar port, or undefined when the sidecar is not running. */
  getSidecarPort: () => number | undefined;
  /** True while the sidebar or editor workbench surface is visible. */
  isWorkbenchVisible: () => boolean;
  /** Runtime workspace id this poller may read the library for. */
  getWorkspaceId: () => string;
  /** GET /browser/library-revision?workspace_id=... */
  fetchLibraryRevision: (port: number, workspaceId: string) => Promise<unknown>;
  /** Fetch a fresh snapshot and push it to the workbench. */
  refreshLibrary: (revision: BrowserLibraryRevision) => Promise<void>;
  intervalMs?: number;
  onError?: (message: string) => void;
  setIntervalFn?: (handler: () => void, intervalMs: number) => ReturnType<typeof setInterval>;
  clearIntervalFn?: (timer: ReturnType<typeof setInterval>) => void;
}

export type BrowserLibraryPollState =
  | 'idle'
  | 'hidden'
  | 'no-sidecar'
  | 'unscoped'
  | 'unchanged'
  | 'changed'
  | 'error';

export interface BrowserLibraryPollResult {
  state: BrowserLibraryPollState;
  workspaceId?: string;
  count?: number;
  revision?: string;
  error?: string;
}

export function parseBrowserLibraryRevision(payload: unknown): BrowserLibraryRevision {
  const record =
    payload && typeof payload === 'object' && !Array.isArray(payload)
      ? (payload as Record<string, unknown>)
      : {};
  return {
    workspaceId: typeof record.workspace_id === 'string' ? record.workspace_id.trim() : '',
    requestedWorkspaceId:
      typeof record.requested_workspace_id === 'string'
        ? record.requested_workspace_id.trim()
        : '',
    count:
      typeof record.count === 'number' && Number.isFinite(record.count)
        ? record.count
        : 0,
    revision: typeof record.revision === 'string' ? record.revision.trim() : '',
  };
}

export class BrowserLibraryPoller {
  private readonly options: BrowserLibraryPollerOptions;
  private readonly intervalMs: number;
  private timer?: ReturnType<typeof setInterval>;
  private inFlight = false;
  private disposed = false;
  private hasBaseline = false;
  private lastRevision = '';
  private consecutiveFailures = 0;
  private backoffUntil = 0;
  private lastReportedError?: string;

  constructor(options: BrowserLibraryPollerOptions) {
    this.options = options;
    this.intervalMs = options.intervalMs ?? BROWSER_CAPTURE.libraryPollIntervalMs;
  }

  get running(): boolean {
    return this.timer !== undefined;
  }

  start(): void {
    if (this.disposed || this.timer) {
      return;
    }
    const schedule = this.options.setIntervalFn ?? setInterval;
    this.timer = schedule(() => {
      void this.pollOnce();
    }, this.intervalMs);
    this.timer.unref?.();
  }

  stop(): void {
    if (!this.timer) {
      return;
    }
    const cancel = this.options.clearIntervalFn ?? clearInterval;
    cancel(this.timer);
    this.timer = undefined;
  }

  dispose(): void {
    this.disposed = true;
    this.stop();
  }

  /**
   * One poll pass. Safe to call directly (tests do); overlapping ticks are
   * dropped rather than queued so a slow summary cannot pile up requests.
   */
  async pollOnce(): Promise<BrowserLibraryPollResult> {
    if (this.disposed || this.inFlight) {
      return { state: 'idle' };
    }
    if (!this.options.isWorkbenchVisible()) {
      return { state: 'hidden' };
    }
    const workspaceId = this.options.getWorkspaceId().trim();
    if (!workspaceId) {
      return { state: 'unscoped' };
    }
    const port = this.options.getSidecarPort();
    if (port === undefined) {
      return { state: 'no-sidecar' };
    }
    if (Date.now() < this.backoffUntil) {
      return { state: 'idle' };
    }

    this.inFlight = true;
    try {
      const revision = parseBrowserLibraryRevision(
        await this.options.fetchLibraryRevision(port, workspaceId),
      );
      if (!revision.workspaceId) {
        this.enterBackoff();
        this.reportError('library revision response has no workspace stamp');
        return { state: 'error', error: 'missing workspace stamp' };
      }
      const stampedWorkspace = revision.requestedWorkspaceId || revision.workspaceId;
      if (stampedWorkspace !== workspaceId) {
        this.reportError(
          `library revision belongs to ${stampedWorkspace}, not ${workspaceId}`,
        );
        return {
          state: 'unscoped',
          workspaceId: revision.workspaceId,
          count: revision.count,
          revision: revision.revision,
        };
      }

      // The first visible poll refreshes too: a capture may have landed while
      // the workbench was hidden, and baselining that revision would swallow
      // it. Only commit the revision after the refresh succeeds, so a failed
      // summary is retried on the next tick instead of being lost.
      const changed = !this.hasBaseline || revision.revision !== this.lastRevision;
      if (!changed) {
        this.resetBackoff();
        return {
          state: 'unchanged',
          workspaceId,
          count: revision.count,
          revision: revision.revision,
        };
      }

      await this.options.refreshLibrary(revision);
      this.hasBaseline = true;
      this.lastRevision = revision.revision;
      this.resetBackoff();
      return {
        state: 'changed',
        workspaceId,
        count: revision.count,
        revision: revision.revision,
      };
    } catch (error) {
      this.enterBackoff();
      this.reportError(error);
      return {
        state: 'error',
        error: error instanceof Error ? error.message : String(error),
      };
    } finally {
      this.inFlight = false;
    }
  }

  private enterBackoff(): void {
    this.consecutiveFailures += 1;
    const multiplier = Math.min(2 ** Math.max(0, this.consecutiveFailures - 1), 16);
    this.backoffUntil = Date.now() + this.intervalMs * multiplier;
  }

  private resetBackoff(): void {
    this.consecutiveFailures = 0;
    this.backoffUntil = 0;
    this.lastReportedError = undefined;
  }

  private reportError(error: unknown): void {
    const message = error instanceof Error ? error.message : String(error);
    if (message === this.lastReportedError) {
      return;
    }
    this.lastReportedError = message;
    this.options.onError?.(message);
  }
}
