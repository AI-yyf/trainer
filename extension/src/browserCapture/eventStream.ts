import { BROWSER_CAPTURE } from '../core/constants';
import { SidecarRequestAbortedError, type SSEMessage } from '../core/httpClient';

/**
 * Real-time SSE subscriber for `/browser/events/stream`.
 *
 * Replaces continuous HTTP polling for queued coach drafts and browser library
 * captures while a workbench surface is visible. Once the initial `snapshot`
 * frame arrives on an open SSE connection, `connected` turns true so the
 * fallback timers in `BrowserDraftPoller` and `BrowserLibraryPoller` stay
 * completely idle (zero polling requests).
 */

export type OpenWorkspaceEventStreamFn = (
  port: number,
  path: string,
  options?: { signal?: AbortSignal; connectTimeoutMs?: number },
) => AsyncIterable<SSEMessage>;

export interface BrowserWorkspaceEventStreamOptions {
  openEventStream?: OpenWorkspaceEventStreamFn;
  getSidecarPort: () => number | undefined;
  isWorkbenchVisible: () => boolean;
  getWorkspaceId: () => string;
  onDraftsPayload: (payload: { drafts: unknown[] }) => Promise<void>;
  onLibraryPayload: (payload: unknown) => Promise<void>;
  onPairingChanged?: (pairedCredentials: number) => void;
  onError?: (message: string) => void;
  watchdogIntervalMs?: number;
  reconnectBaseMs?: number;
  reconnectMaxMs?: number;
  setIntervalFn?: (handler: () => void, intervalMs: number) => ReturnType<typeof setInterval>;
  clearIntervalFn?: (timer: ReturnType<typeof setInterval>) => void;
}

export class BrowserWorkspaceEventStream {
  private readonly options: BrowserWorkspaceEventStreamOptions;
  private readonly watchdogIntervalMs: number;
  private readonly reconnectBaseMs: number;
  private readonly reconnectMaxMs: number;
  private watchdogTimer?: ReturnType<typeof setInterval>;
  private activeAbort?: AbortController;
  private activeKey?: string;
  private streamConnected = false;
  private connecting = false;
  private started = false;
  private disposed = false;
  private consecutiveFailures = 0;
  private backoffUntil = 0;
  private lastReportedError?: string;

  constructor(options: BrowserWorkspaceEventStreamOptions) {
    this.options = options;
    this.watchdogIntervalMs = options.watchdogIntervalMs ?? 5_000;
    this.reconnectBaseMs = options.reconnectBaseMs ?? BROWSER_CAPTURE.eventsReconnectBaseMs;
    this.reconnectMaxMs = options.reconnectMaxMs ?? BROWSER_CAPTURE.eventsReconnectMaxMs;
  }

  /** True when `openEventStream` is wired AND the stream has delivered its live snapshot. */
  get connected(): boolean {
    return this.streamConnected;
  }

  get running(): boolean {
    return this.started && !this.disposed;
  }

  start(): void {
    if (this.disposed || this.started || !this.options.openEventStream) {
      return;
    }
    this.started = true;
    const schedule = this.options.setIntervalFn ?? setInterval;
    this.watchdogTimer = schedule(() => {
      this.reconcile();
    }, this.watchdogIntervalMs);
    this.watchdogTimer.unref?.();
    this.reconcile();
  }

  stop(): void {
    this.started = false;
    if (this.watchdogTimer !== undefined) {
      const cancel = this.options.clearIntervalFn ?? clearInterval;
      cancel(this.watchdogTimer);
      this.watchdogTimer = undefined;
    }
    this.abortActiveStream();
  }

  /** Prompt immediate connect/disconnect/re-scope without waiting for the watchdog. */
  wake(): void {
    if (!this.started || this.disposed) {
      return;
    }
    this.backoffUntil = 0;
    this.reconcile();
  }

  dispose(): void {
    this.disposed = true;
    this.stop();
  }

  private desiredConnection(): { port: number; workspaceId: string; key: string } | undefined {
    if (!this.started || this.disposed || !this.options.openEventStream) {
      return undefined;
    }
    if (!this.options.isWorkbenchVisible()) {
      return undefined;
    }
    const workspaceId = this.options.getWorkspaceId().trim();
    if (!workspaceId) {
      return undefined;
    }
    const port = this.options.getSidecarPort();
    if (port === undefined) {
      return undefined;
    }
    return { port, workspaceId, key: `${port}:${workspaceId}` };
  }

  private reconcile(): void {
    const desired = this.desiredConnection();
    if (!desired) {
      this.abortActiveStream();
      return;
    }
    if (this.activeKey && this.activeKey !== desired.key) {
      this.abortActiveStream();
    }
    if (this.connecting || this.activeAbort) {
      return;
    }
    if (Date.now() < this.backoffUntil) {
      return;
    }
    void this.consumeLoop(desired.port, desired.workspaceId, desired.key);
  }

  private abortActiveStream(): void {
    this.streamConnected = false;
    this.activeKey = undefined;
    if (this.activeAbort) {
      const controller = this.activeAbort;
      this.activeAbort = undefined;
      controller.abort();
    }
  }

  private async consumeLoop(port: number, workspaceId: string, key: string): Promise<void> {
    const openStream = this.options.openEventStream;
    if (!openStream) {
      return;
    }
    const controller = new AbortController();
    this.activeAbort = controller;
    this.activeKey = key;
    this.connecting = true;
    const path = `${BROWSER_CAPTURE.eventsStreamPath}?workspace_id=${encodeURIComponent(workspaceId)}`;

    try {
      for await (const frame of openStream(port, path, { signal: controller.signal })) {
        if (controller.signal.aborted || this.disposed || !this.started) {
          break;
        }
        if (!this.options.isWorkbenchVisible() || this.options.getWorkspaceId().trim() !== workspaceId) {
          controller.abort();
          break;
        }
        this.connecting = false;
        this.streamConnected = true;
        this.resetBackoff();
        await this.dispatchFrame(frame);
      }
    } catch (error) {
      if (
        !controller.signal.aborted &&
        !(error instanceof SidecarRequestAbortedError)
      ) {
        this.enterBackoff();
        this.reportError(error);
      }
    } finally {
      this.connecting = false;
      if (this.activeAbort === controller) {
        this.activeAbort = undefined;
        this.activeKey = undefined;
        this.streamConnected = false;
      }
    }
  }

  private async dispatchFrame(frame: SSEMessage): Promise<void> {
    if (frame.event !== 'snapshot' && frame.event !== 'workspace_event') {
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(frame.data);
    } catch {
      return;
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return;
    }
    const record = parsed as Record<string, unknown>;
    if (Array.isArray(record.drafts)) {
      await this.options.onDraftsPayload({ drafts: record.drafts });
    }
    if (record.library && typeof record.library === 'object' && !Array.isArray(record.library)) {
      await this.options.onLibraryPayload(record.library);
    }
    if (
      frame.event === 'workspace_event' &&
      record.kind === 'pairing_changed' &&
      typeof record.paired_credentials === 'number'
    ) {
      this.options.onPairingChanged?.(record.paired_credentials);
    }
  }

  private enterBackoff(): void {
    this.consecutiveFailures += 1;
    const delayMs = Math.min(
      this.reconnectBaseMs * 2 ** Math.max(0, this.consecutiveFailures - 1),
      this.reconnectMaxMs,
    );
    this.backoffUntil = Date.now() + delayMs;
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
