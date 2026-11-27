import { BROWSER_CAPTURE } from '../core/constants';

/**
 * Forwards browser-captured coach drafts into the workbench.
 *
 * Primary transport is the real-time SSE workspace event stream (`eventStream.ts`
 * calling `pushDraftsPayload`); the interval timer remains only as an offline /
 * fallback safety net and skips every tick while SSE is actively connected.
 *
 * Delivery is receipt-confirmed: a draft is acknowledged with `POST
 * /browser/pending-drafts/ack` only after the workbench has applied the
 * prefill and answered with the matching receipt (`DraftReceiptChannel`).
 */

export interface PendingBrowserDraft {
  id: string;
  text: string;
  workspaceId: string;
  source?: { url: string; title: string; selection: string };
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
  /** When true (e.g. live SSE stream is active), periodic timer ticks stay silent. */
  shouldSkipTimerPoll?: () => boolean;
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
      const url = asTrimmedText(record.url);
      const source = /^https?:\/\//i.test(url)
        ? { url, title: asTrimmedText(record.title), selection: asTrimmedText(record.selection) }
        : undefined;
      parsed.push({ id, text, workspaceId, ...(source ? { source } : {}) });
    }
  }
  return parsed;
}

function asTrimmedText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

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
  private queuedPush?: { hasPayload: true; payload: unknown };
  private consecutiveFailures = 0;
  private backoffUntil = 0;
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
   * Deliver a draft snapshot pushed directly from the sidecar's SSE stream,
   * bypassing any HTTP poll request. If a delivery is currently in flight, the
   * latest pushed snapshot is queued and drained right after it settles.
   */
  async pushDraftsPayload(payload: unknown): Promise<BrowserDraftPollResult> {
    if (this.disposed) {
      return { state: 'idle', forwarded: 0, acknowledged: 0 };
    }
    if (this.inFlight) {
      this.queuedPush = { hasPayload: true, payload };
      return { state: 'idle', forwarded: 0, acknowledged: 0 };
    }
    return this.runPass({ pushedPayload: payload });
  }

  async pollOnce(): Promise<BrowserDraftPollResult> {
    if (this.disposed || this.inFlight) {
      return { state: 'idle', forwarded: 0, acknowledged: 0 };
    }
    return this.runPass();
  }

  private async runPass(input?: { pushedPayload?: unknown }): Promise<BrowserDraftPollResult> {
    const isPush = input !== undefined && Object.prototype.hasOwnProperty.call(input, 'pushedPayload');
    if (!this.options.isWorkbenchVisible()) {
      return { state: 'hidden', forwarded: 0, acknowledged: 0 };
    }
    const workspaceId = this.options.getWorkspaceId().trim();
    if (!workspaceId) {
      return { state: 'unscoped', forwarded: 0, acknowledged: 0 };
    }
    const port = this.options.getSidecarPort();
    if (port === undefined) {
      return { state: 'no-sidecar', forwarded: 0, acknowledged: 0 };
    }
    if (!isPush && Date.now() < this.backoffUntil) {
      return { state: 'idle', forwarded: 0, acknowledged: 0 };
    }

    this.inFlight = true;
    try {
      const rawPayload = isPush
        ? input.pushedPayload
        : await this.options.fetchPendingDrafts(port, workspaceId);
      const result = await this.deliverPayload(port, workspaceId, rawPayload);
      while (!this.disposed && this.queuedPush?.hasPayload) {
        const next = this.queuedPush.payload;
        this.queuedPush = undefined;
        if (!this.options.isWorkbenchVisible()) {
          break;
        }
        const latestWorkspace = this.options.getWorkspaceId().trim();
        const latestPort = this.options.getSidecarPort();
        if (!latestWorkspace || latestPort === undefined) {
          break;
        }
        await this.deliverPayload(latestPort, latestWorkspace, next);
      }
      return result;
    } catch (error) {
      this.enterBackoff();
      const message = error instanceof Error ? error.message : String(error);
      this.reportError(error);
      return { state: 'idle', forwarded: 0, acknowledged: 0, error: message };
    } finally {
      this.inFlight = false;
    }
  }

  private async deliverPayload(
    port: number,
    workspaceId: string,
    rawPayload: unknown,
  ): Promise<BrowserDraftPollResult> {
    const fetched = parsePendingDrafts(rawPayload);
    const foreign = fetched.filter(
      (draft) => draft.workspaceId && draft.workspaceId !== workspaceId,
    );
    if (foreign.length > 0) {
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
    if (message === this.lastReportedError) {
      return;
    }
    this.lastReportedError = message;
    this.options.onError?.(message);
  }
}
