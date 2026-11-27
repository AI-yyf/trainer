import { BROWSER_CAPTURE } from '../core/constants';

/**
 * Library freshness subscriber for browser captures.
 *
 * Primary transport is the real-time SSE workspace event stream (`eventStream.ts`
 * calling `pushLibraryPayload`); the interval timer remains only as an offline /
 * fallback safety net and skips every tick while SSE is actively connected.
 */

export interface BrowserLibraryRevision {
  workspaceId: string;
  requestedWorkspaceId: string;
  count: number;
  revision: string;
}

export interface BrowserLibraryPollerOptions {
  getSidecarPort: () => number | undefined;
  isWorkbenchVisible: () => boolean;
  getWorkspaceId: () => string;
  fetchLibraryRevision: (port: number, workspaceId: string) => Promise<unknown>;
  refreshLibrary: (revision: BrowserLibraryRevision) => Promise<void>;
  /** When true (e.g. live SSE stream is active), periodic timer ticks stay silent. */
  shouldSkipTimerPoll?: () => boolean;
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
  private queuedPush?: { hasPayload: true; payload: unknown };
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
      if (this.options.shouldSkipTimerPoll?.() === true) {
        return;
      }
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
    this.queuedPush = undefined;
    this.stop();
  }

  /**
   * Apply a library revision pushed directly from the sidecar's SSE stream,
   * refreshing `/memory/summary` only when the resource-id revision changed.
   */
  async pushLibraryPayload(payload: unknown): Promise<BrowserLibraryPollResult> {
    if (this.disposed) {
      return { state: 'idle' };
    }
    if (this.inFlight) {
      this.queuedPush = { hasPayload: true, payload };
      return { state: 'idle' };
    }
    return this.runPass({ pushedPayload: payload });
  }

  async pollOnce(): Promise<BrowserLibraryPollResult> {
    if (this.disposed || this.inFlight) {
      return { state: 'idle' };
    }
    return this.runPass();
  }

  private async runPass(input?: { pushedPayload?: unknown }): Promise<BrowserLibraryPollResult> {
    const isPush = input !== undefined && Object.prototype.hasOwnProperty.call(input, 'pushedPayload');
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
    if (!isPush && Date.now() < this.backoffUntil) {
      return { state: 'idle' };
    }

    this.inFlight = true;
    try {
      const rawPayload = isPush
        ? input.pushedPayload
        : await this.options.fetchLibraryRevision(port, workspaceId);
      const result = await this.applyRevisionPayload(workspaceId, rawPayload);
      while (!this.disposed && this.queuedPush?.hasPayload) {
        const next = this.queuedPush.payload;
        this.queuedPush = undefined;
        if (!this.options.isWorkbenchVisible()) {
          break;
        }
        const latestWorkspace = this.options.getWorkspaceId().trim();
        if (!latestWorkspace) {
          break;
        }
        await this.applyRevisionPayload(latestWorkspace, next);
      }
      return result;
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

  private async applyRevisionPayload(
    workspaceId: string,
    rawPayload: unknown,
  ): Promise<BrowserLibraryPollResult> {
    const revision = parseBrowserLibraryRevision(rawPayload);
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
