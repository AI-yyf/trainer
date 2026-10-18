import { BROWSER_CAPTURE } from '../core/constants';

/**
 * Forwards browser-captured coach drafts into the workbench.
 *
 * Background poller for `GET /browser/pending-drafts`: it only runs while a
 * workbench surface is visible and only touches the sidecar when there is
 * something to fetch — an empty queue produces no `postMessage` and no ack.
 *
 * Delivery is receipt-confirmed: a draft is acknowledged with `POST
 * /browser/pending-drafts/ack` only after the workbench has applied the
 * prefill and answered with the matching receipt (`DraftReceiptChannel`). A
 * draft whose receipt never arrives stays queued server-side and the next
 * tick retries it; the webview applies each draft id at most once, so a retry
 * can confirm but never re-stamp an already-applied prefill.
 *
 * The queue is workspace-scoped end to end: every read states the runtime
 * workspace id and drafts whose workspace does not match are dropped rather
 * than shown — a capture from project A must never reach project B's coach.
 */

export interface PendingBrowserDraft {
  id: string;
  text: string;
  workspaceId: string;
}

export const COACH_DRAFT_PREFILL_MESSAGE = 'ui/coachDraftPrefill';

export interface BrowserDraftPollerOptions {
  /** Resolves the sidecar port, or undefined when the sidecar is not running. */
  getSidecarPort: () => number | undefined;
  /** True while the sidebar or editor workbench surface is visible. */
  isWorkbenchVisible: () => boolean;
  /** Runtime workspace id this poller may read drafts for (isolation scope). */
  getWorkspaceId: () => string;
  /**
   * Delivers one draft to the workbench; resolves only once the webview has
   * confirmed it applied the prefill (the delivery receipt).
   */
  forwardDraft: (draft: PendingBrowserDraft) => Promise<void>;
  /** GET /browser/pending-drafts?workspace_id=... */
  fetchPendingDrafts: (port: number, workspaceId: string) => Promise<unknown>;
  /** POST /browser/pending-drafts/ack {workspace_id, ids} */
  acknowledgeDrafts: (port: number, workspaceId: string, ids: string[]) => Promise<void>;
  intervalMs?: number;
  onError?: (message: string) => void;
  setIntervalFn?: (handler: () => void, intervalMs: number) => ReturnType<typeof setInterval>;
  clearIntervalFn?: (timer: ReturnType<typeof setInterval>) => void;
}

export interface BrowserDraftPollResult {
  state: 'idle' | 'forwarded' | 'empty' | 'hidden' | 'no-sidecar' | 'unscoped';
  forwarded: number;
  acknowledged: number;
  error?: string;
}

export function parsePendingDrafts(payload: unknown): PendingBrowserDraft[] {
  const drafts = (payload as { drafts?: unknown } | undefined)?.drafts;
  if (!Array.isArray(drafts)) {
    return [];
  }
  const parsed: PendingBrowserDraft[] = [];
  for (const entry of drafts) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
      continue;
    }
    const record = entry as Record<string, unknown>;
    const id = typeof record.id === 'string' ? record.id.trim() : '';
    const text = typeof record.text === 'string' ? record.text : '';
    const workspaceId = typeof record.workspace_id === 'string' ? record.workspace_id.trim() : '';
    if (id && text.trim()) {
      parsed.push({ id, text, workspaceId });
    }
  }
  return parsed;
}

/**
 * Delivery receipts for forwarded prefills.
 *
 * `waitForReceipt` resolves `true` on the matching `notify` and `false` on
 * timeout, so the caller can turn a timeout into an ordinary failed delivery
 * without an unhandled rejection. A receipt that arrives after its wait
 * already timed out is simply dropped; the next delivery attempt re-waits.
 */
export class DraftReceiptChannel {
  private readonly waiters = new Map<string, () => void>();

  waitForReceipt(draftId: string, timeoutMs: number): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      const settle = (): void => {
        if (timer !== undefined) {
          clearTimeout(timer);
        }
        resolve(true);
      };
      timer = setTimeout(() => {
        if (this.waiters.get(draftId) === settle) {
          this.waiters.delete(draftId);
        }
        resolve(false);
      }, timeoutMs);
      this.waiters.set(draftId, settle);
    });
  }

  notify(draftId: string): void {
    const settle = this.waiters.get(draftId);
    if (!settle) {
      return;
    }
    this.waiters.delete(draftId);
    settle();
  }
}

export class BrowserDraftPoller {
  private readonly options: BrowserDraftPollerOptions;
  private readonly intervalMs: number;
  private timer?: ReturnType<typeof setInterval>;
  private inFlight = false;
  private disposed = false;
  /** Consecutive failed passes; drives the error backoff. */
  private consecutiveFailures = 0;
  /** Wall clock until which polls are skipped after repeated failures. */
  private backoffUntil = 0;
  /** The last error text reported; identical repeats stay silent. */
  private lastReportedError?: string;

  constructor(options: BrowserDraftPollerOptions) {
    this.options = options;
    this.intervalMs = options.intervalMs ?? BROWSER_CAPTURE.draftPollIntervalMs;
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
   * dropped rather than queued so a slow sidecar cannot pile up requests.
   *
   * Repeated failures back off geometrically (interval → 2× → 4× … capped at
   * one minute) so a stale pairing or a dead port cannot flood the log with a
   * 401 per second; a different error message is always reported immediately,
   * and one clean pass resets the backoff.
   */
  async pollOnce(): Promise<BrowserDraftPollResult> {
    if (this.disposed || this.inFlight) {
      return { state: 'idle', forwarded: 0, acknowledged: 0 };
    }
    if (!this.options.isWorkbenchVisible()) {
      return { state: 'hidden', forwarded: 0, acknowledged: 0 };
    }
    const workspaceId = this.options.getWorkspaceId().trim();
    if (!workspaceId) {
      // Without a workspace there is no honest read to make: fetching
      // unscoped could pull another project's captures into this coach.
      return { state: 'unscoped', forwarded: 0, acknowledged: 0 };
    }
    const port = this.options.getSidecarPort();
    if (port === undefined) {
      return { state: 'no-sidecar', forwarded: 0, acknowledged: 0 };
    }
    if (Date.now() < this.backoffUntil) {
      return { state: 'idle', forwarded: 0, acknowledged: 0 };
    }

    this.inFlight = true;
    try {
      const fetched = parsePendingDrafts(
        await this.options.fetchPendingDrafts(port, workspaceId),
      );
      const foreign = fetched.filter(
        (draft) => draft.workspaceId && draft.workspaceId !== workspaceId,
      );
      if (foreign.length > 0) {
        // The sidecar filters by workspace; a foreign draft here would be an
        // isolation breach. Never show it, never ack it — report it.
        this.reportError(
          `${foreign.length} queued draft(s) belong to another workspace and stay queued`,
        );
      }
      const drafts = fetched.filter(
        (draft) => !draft.workspaceId || draft.workspaceId === workspaceId,
      );
      if (drafts.length === 0) {
        this.resetBackoff();
        return { state: 'empty', forwarded: 0, acknowledged: 0 };
      }

      const forwardedIds: string[] = [];
      for (const draft of drafts) {
        try {
          await this.options.forwardDraft(draft);
          forwardedIds.push(draft.id);
        } catch (error) {
          // Leave the failed draft unacknowledged: the sidecar keeps it and the
          // next tick retries it.
          this.enterBackoff();
          this.reportError(error);
        }
      }

      let acknowledged = 0;
      if (forwardedIds.length > 0) {
        try {
          await this.options.acknowledgeDrafts(port, workspaceId, forwardedIds);
          acknowledged = forwardedIds.length;
        } catch (error) {
          this.enterBackoff();
          this.reportError(error);
        }
      }

      if (forwardedIds.length > 0 && acknowledged === forwardedIds.length) {
        this.resetBackoff();
      }

      return {
        state: forwardedIds.length > 0 ? 'forwarded' : 'empty',
        forwarded: forwardedIds.length,
        acknowledged,
      };
    } catch (error) {
      this.enterBackoff();
      const message = error instanceof Error ? error.message : String(error);
      this.reportError(error);
      return { state: 'idle', forwarded: 0, acknowledged: 0, error: message };
    } finally {
      this.inFlight = false;
    }
  }

  private resetBackoff(): void {
    this.consecutiveFailures = 0;
    this.backoffUntil = 0;
    this.lastReportedError = undefined;
  }

  private enterBackoff(): void {
    this.consecutiveFailures += 1;
    const delayMs = Math.min(
      this.intervalMs * 2 ** (this.consecutiveFailures - 1),
      60_000,
    );
    this.backoffUntil = Date.now() + delayMs;
  }

  private reportError(error: unknown): void {
    const message = error instanceof Error ? error.message : String(error);
    // A failing poll loop runs every few seconds; repeating the identical
    // failure text each tick is log noise, not new information.
    if (message === this.lastReportedError) {
      return;
    }
    this.lastReportedError = message;
    this.options.onError?.(message);
  }
}
