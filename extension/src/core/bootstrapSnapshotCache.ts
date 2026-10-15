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

export class BootstrapSnapshotCache {
  private timer?: ReturnType<typeof setTimeout>;
  private pendingKey?: string;

  constructor(private readonly extensionContext: vscode.ExtensionContext) {}

  /** Debounced: message merges arrive in bursts (snapshot + summary + trash). */
  schedulePersist(workspaceId: string, bootstrap: BootstrapData): void {
    if (!workspaceId || bootstrap.conversation.length === 0) {
      return;
    }
    this.pendingKey = workspaceId;
    if (this.timer) {
      clearTimeout(this.timer);
    }
    this.timer = setTimeout(() => {
      this.timer = undefined;
      if (this.pendingKey !== workspaceId) {
        return;
      }
      void this.persistNow(workspaceId, bootstrap);
    }, PERSIST_DEBOUNCE_MS);
    this.timer.unref?.();
  }

  private async persistNow(workspaceId: string, bootstrap: BootstrapData): Promise<void> {
    try {
      const payload: CachedBootstrapEnvelope = {
        savedAt: new Date().toISOString(),
        bootstrap: sanitizeForCache(bootstrap),
      };
      const serialized = JSON.stringify(payload);
      if (serialized.length > MAX_CACHE_BYTES) {
        // Oversized thread: keep the cache useful by dropping to a smaller tail.
        const trimmed: CachedBootstrapEnvelope = {
          ...payload,
          bootstrap: {
            ...payload.bootstrap,
            conversation: payload.bootstrap.conversation.slice(-60),
          },
        };
        await this.extensionContext.workspaceState.update(
          cacheKey(workspaceId),
          JSON.stringify(trimmed),
        );
        return;
      }
      await this.extensionContext.workspaceState.update(cacheKey(workspaceId), serialized);
    } catch {
      // A failed cache write only costs restore speed, never correctness.
    }
  }

  load(workspaceId: string): BootstrapData | undefined {
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
      return bootstrap;
    } catch {
      return undefined;
    }
  }

  async clear(workspaceId: string): Promise<void> {
    if (this.timer && this.pendingKey === workspaceId) {
      clearTimeout(this.timer);
      this.timer = undefined;
      this.pendingKey = undefined;
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
  }
}
