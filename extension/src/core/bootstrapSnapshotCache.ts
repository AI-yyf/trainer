import * as vscode from 'vscode';

import { createEmptyTrainerStreamingState } from '../../../shared/src/protocol';
import type { BootstrapData } from './types';

/**
 * Stale-while-revalidate bootstrap cache.
 *
 * The sidecar is a PyInstaller process: its cold start takes seconds, and
 * until it is healthy the host has no snapshot to show — the webview used to
 * sit on the "getting ready" empty state for that entire window. This cache
 * persists the last known-good BootstrapData per workspace (conversation
 * included) and lets activation seed host state with it immediately, so the
 * webview renders the restored thread in well under a second. The next
 * successful rehydration replaces it with the authoritative snapshot.
 */

const CACHE_PREFIX = 'trainer.bootstrapSnapshot.v1.';
const PERSIST_DEBOUNCE_MS = 1_500;
/** Keep the payload bounded: the last stretch of the thread is what restores. */
const MAX_CACHED_MESSAGES = 160;
const MAX_CACHE_BYTES = 2_000_000;

interface CachedBootstrapEnvelope {
  savedAt: string;
  /** Session the snapshot belonged to; seeds must match or be unknown. */
  sessionId?: string;
  bootstrap: BootstrapData;
}

function cacheKey(workspaceId: string): string {
  return `${CACHE_PREFIX}${workspaceId}`;
}

function sanitizeForCache(bootstrap: BootstrapData): BootstrapData {
  const conversation = bootstrap.conversation.length > MAX_CACHED_MESSAGES
    ? bootstrap.conversation.slice(-MAX_CACHED_MESSAGES)
    : bootstrap.conversation;
  return {
    ...bootstrap,
    conversation,
    // A half-finished stream must never resurrect as an in-flight stream.
    streamingState: createEmptyTrainerStreamingState(),
  };
}

interface PendingPersist {
  workspaceId: string;
  bootstrap: BootstrapData;
  sessionId?: string;
}

export interface CachedBootstrapEntry {
  bootstrap: BootstrapData;
  sessionId?: string;
  savedAt: string;
}

export class BootstrapSnapshotCache {
  private timer?: ReturnType<typeof setTimeout>;
  private pending?: PendingPersist;

  constructor(private readonly extensionContext: vscode.ExtensionContext) {}

  /**
   * Debounced: message merges arrive in bursts (snapshot + summary + trash).
   *
   * The timer is deliberately NOT reset on every call. Streaming and patch
   * traffic can arrive faster than the debounce window for minutes at a time;
   * resetting would starve the write forever (the original bug that left the
   * cache empty). Instead the first call arms the timer and every later call
   * only replaces the pending payload, so a write lands at most 1.5s after the
   * first change in a burst and always contains the newest conversation.
   */
  schedulePersist(workspaceId: string, bootstrap: BootstrapData, sessionId?: string): void {
    // A session-less snapshot cannot be bound, so it must never evict a bound
    // one. An EMPTY conversation bound to a session is a real state (the user
    // started a new thread) and must overwrite the stale cached thread.
    if (!workspaceId || !sessionId) {
      return;
    }
    this.pending = { workspaceId, bootstrap, sessionId };
    if (this.timer) {
      return;
    }
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.flushPending();
    }, PERSIST_DEBOUNCE_MS);
    this.timer.unref?.();
  }

  /** Persist the newest pending payload immediately (deactivate, tests). */
  async flush(): Promise<void> {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    await this.flushPending();
  }

  private async flushPending(): Promise<void> {
    const pending = this.pending;
    this.pending = undefined;
    if (!pending) {
      return;
    }
    await this.persistNow(pending.workspaceId, pending.bootstrap, pending.sessionId);
  }

  private async persistNow(
    workspaceId: string,
    bootstrap: BootstrapData,
    sessionId?: string,
  ): Promise<void> {
    try {
      const payload: CachedBootstrapEnvelope = {
        savedAt: new Date().toISOString(),
        sessionId,
        bootstrap: sanitizeForCache(bootstrap),
      };
      let serialized = JSON.stringify(payload);
      // Oversized thread: keep the cache useful by halving the tail until it
      // fits. A single giant message can still exceed the budget; in that case
      // skip the write rather than risk an unbounded memento.
      while (serialized.length > MAX_CACHE_BYTES && payload.bootstrap.conversation.length > 1) {
        const keep = Math.max(1, Math.floor(payload.bootstrap.conversation.length / 2));
        payload.bootstrap = {
          ...payload.bootstrap,
          conversation: payload.bootstrap.conversation.slice(-keep),
        };
        serialized = JSON.stringify(payload);
      }
      if (serialized.length > MAX_CACHE_BYTES) {
        return;
      }
      await this.extensionContext.workspaceState.update(cacheKey(workspaceId), serialized);
    } catch {
      // A failed cache write only costs restore speed, never correctness.
    }
  }

  load(workspaceId: string): CachedBootstrapEntry | undefined {
    try {
      const raw = this.extensionContext.workspaceState.get<string>(cacheKey(workspaceId));
      if (!raw) {
        return undefined;
      }
      const parsed = JSON.parse(raw) as CachedBootstrapEnvelope;
      const bootstrap = parsed?.bootstrap;
      if (!bootstrap || !Array.isArray(bootstrap.conversation) || typeof bootstrap.workspaceName !== 'string') {
        return undefined;
      }
      return { bootstrap, sessionId: parsed.sessionId, savedAt: parsed.savedAt };
    } catch {
      return undefined;
    }
  }

  async clear(workspaceId: string): Promise<void> {
    if (this.pending?.workspaceId === workspaceId) {
      this.pending = undefined;
      if (this.timer) {
        clearTimeout(this.timer);
        this.timer = undefined;
      }
    }
    try {
      await this.extensionContext.workspaceState.update(cacheKey(workspaceId), undefined);
    } catch {
      // Nothing depends on the delete succeeding.
    }
  }

  dispose(): void {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    this.pending = undefined;
  }
}
