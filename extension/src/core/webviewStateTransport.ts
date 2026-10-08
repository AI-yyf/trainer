import type { WebviewSyncAck, WebviewSyncEnvelope, WebviewSyncStatus } from '../../../shared/src/webviewSync';

interface Snapshot {
  payload: Record<string, unknown>;
  workspaceId: string;
  sessionId: string;
  runtimeGeneration?: unknown;
  hostState: unknown;
}

export interface StateDelivery {
  type: 'bootstrap' | 'state/patch';
  payload: Record<string, unknown>;
  sync: WebviewSyncEnvelope;
}

type PublishedSnapshot = Snapshot & { sequence: number };

interface PendingDelivery {
  message: StateDelivery;
  snapshot: PublishedSnapshot;
  attempts: number;
  recovery: boolean;
  firstSentAt: number;
}

/** One in-flight state message. New host states coalesce, never fork a delta chain. */
export class WebviewStateTransport {
  private generation = 0;
  private revision = 0;
  private appliedRevision = 0;
  private receivedRevision = 0;
  private applied?: PublishedSnapshot;
  private desired?: PublishedSnapshot;
  private sequence = 0;
  private pending?: PendingDelivery;
  private timer?: ReturnType<typeof setTimeout>;
  private fullRequested = true;
  private exhausted = false;
  private disposed = false;
  private readonly waiters = new Set<(applied: boolean) => void>();

  constructor(private readonly options: {
    send(message: StateDelivery): Promise<boolean>;
    status(status: WebviewSyncStatus, generation: number): void;
    acknowledged(hostState: unknown, elapsedMs: number): void;
    received?(): void;
    attempt?(attempt: number, recovery: boolean): void;
    retryMs?: number;
    maxAttempts?: number;
  }) {}

  get scope(): WebviewSyncEnvelope {
    const snapshot = this.desired ?? this.applied;
    return { generation: this.generation, revision: this.appliedRevision, baseRevision: 0,
      messageId: '', workspaceId: snapshot?.workspaceId ?? '', sessionId: snapshot?.sessionId ?? '' };
  }

  get debug() {
    return { generation: this.generation, revision: this.revision, receivedRevision: this.receivedRevision, appliedRevision: this.appliedRevision,
      pendingMessageId: this.pending?.message.sync.messageId, attempts: this.pending?.attempts ?? 0,
      status: this.exhausted ? 'stale' : this.pending ? 'recovering' : 'current' };
  }

  reset(): void {
    this.clearTimer();
    this.generation += 1;
    this.pending = undefined;
    this.applied = undefined;
    this.appliedRevision = 0;
    this.receivedRevision = 0;
    this.fullRequested = true;
    this.exhausted = false;
    this.resolveWaiters(false);
  }

  async publish(input: Snapshot, forceFull = false): Promise<void> {
    if (this.disposed) return;
    const snapshot: PublishedSnapshot = { ...input, sequence: this.desired && this.desired.hostState === input.hostState
      ? this.desired.sequence : ++this.sequence };
    const previous = this.desired;
    if (previous && (previous.workspaceId !== snapshot.workspaceId || previous.sessionId !== snapshot.sessionId ||
        previous.runtimeGeneration !== snapshot.runtimeGeneration)) this.reset();
    if (this.generation === 0) this.reset();
    this.desired = snapshot;
    this.fullRequested ||= forceFull;
    if (this.exhausted) {
      // A fresh explicit request or authoritative host change can start a new bounded cycle.
      if (!forceFull && previous?.hostState === snapshot.hostState) return;
      this.exhausted = false;
      this.fullRequested = true;
    }
    if (!this.pending) await this.pump();
  }

  acknowledge(ack: WebviewSyncAck): void {
    const pending = this.pending;
    if (!pending || ack.messageId !== pending.message.sync.messageId ||
        ack.generation !== pending.message.sync.generation || ack.revision !== pending.message.sync.revision ||
        ack.workspaceId !== pending.snapshot.workspaceId || ack.sessionId !== pending.snapshot.sessionId) return;
    if (ack.status === 'received') {
      this.receivedRevision = ack.revision;
      this.options.received?.();
      return;
    }
    if (ack.status === 'rejected') {
      this.clearTimer();
      this.pending = undefined;
      if (pending.recovery) { this.finishExhausted(); return; }
      this.fullRequested = true;
      void this.pump(true);
      return;
    }
    if ((ack.status !== 'applied' && ack.status !== 'duplicate') ||
        ack.appliedRevision !== pending.message.sync.revision) return;
    this.clearTimer();
    this.applied = pending.snapshot;
    this.appliedRevision = ack.revision;
    this.pending = undefined;
    this.options.acknowledged(pending.snapshot.hostState, Date.now() - pending.firstSentAt);
    this.options.status('current', this.generation);
    this.resolveWaiters(true);
    void this.pump();
  }

  /** Resolve only after the current desired host state has actually been applied. */
  whenApplied(timeoutMs = 10_000): Promise<boolean> {
    if (this.disposed || this.exhausted) return Promise.resolve(false);
    if (!this.pending && this.applied?.hostState === this.desired?.hostState) return Promise.resolve(true);
    const targetSequence = this.desired?.sequence ?? 0;
    return new Promise(resolve => {
      const timeout = setTimeout(() => { this.waiters.delete(waiter); resolve(false); }, timeoutMs);
      timeout.unref?.();
      const waiter = (ok: boolean) => {
        if (ok && (this.applied?.sequence ?? 0) < targetSequence) return;
        clearTimeout(timeout); this.waiters.delete(waiter); resolve(ok);
      };
      this.waiters.add(waiter);
    });
  }

  dispose(): void {
    this.disposed = true;
    this.clearTimer();
    this.resolveWaiters(false);
  }

  private async pump(recovery = false): Promise<void> {
    if (this.disposed || this.pending || this.exhausted || !this.desired) return;
    const snapshot = this.desired;
    const removedValue = this.applied && Object.keys(this.applied.payload).some(key =>
      this.applied?.payload[key] !== undefined && snapshot.payload[key] === undefined);
    const full = this.fullRequested || !this.applied || Boolean(removedValue);
    const payload: Record<string, unknown> = {};
    if (full) Object.assign(payload, snapshot.payload);
    else for (const key of new Set([...Object.keys(snapshot.payload), ...Object.keys(this.applied?.payload ?? {})])) {
      const next = snapshot.payload[key];
      const previous = this.applied?.payload[key];
      if (next !== previous && (next === undefined || previous === undefined ||
          JSON.stringify(next) !== JSON.stringify(previous))) payload[key] = next;
    }
    if (!full && Object.keys(payload).length === 0) {
      this.applied = snapshot;
      this.options.acknowledged(snapshot.hostState, -1);
      this.resolveWaiters(true);
      return;
    }
    this.fullRequested = false;
    this.revision += 1;
    const sync: WebviewSyncEnvelope = { generation: this.generation, revision: this.revision,
      baseRevision: full ? 0 : this.appliedRevision, messageId: `${this.generation}:${this.revision}`,
      workspaceId: snapshot.workspaceId, sessionId: snapshot.sessionId };
    const pending: PendingDelivery = { message: { type: full ? 'bootstrap' : 'state/patch', payload, sync },
      snapshot, attempts: 0, recovery, firstSentAt: Date.now() };
    this.pending = pending;
    await this.send(pending);
  }

  private async send(pending: PendingDelivery): Promise<void> {
    if (this.disposed || this.pending !== pending) return;
    pending.attempts += 1;
    this.options.attempt?.(pending.attempts, pending.recovery);
    this.options.status('recovering', this.generation);
    try { await this.options.send(pending.message); }
    catch { /* Delivery failure is recovered by the same bounded timer as a lost apply ACK. */ }
    if (this.pending !== pending || this.disposed) return;
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.timer = undefined;
      if (this.pending !== pending || this.disposed) return;
      if (pending.attempts < (this.options.maxAttempts ?? 3)) { void this.send(pending); return; }
      this.pending = undefined;
      if (pending.recovery) { this.finishExhausted(); return; }
      this.fullRequested = true;
      void this.pump(true);
    }, this.options.retryMs ?? 900);
    this.timer.unref?.();
  }

  private finishExhausted(): void {
    this.exhausted = true;
    this.options.status('stale', this.generation);
    this.resolveWaiters(false);
  }
  private clearTimer(): void { if (this.timer) clearTimeout(this.timer); this.timer = undefined; }
  private resolveWaiters(applied: boolean): void { for (const waiter of [...this.waiters]) waiter(applied); }
}
