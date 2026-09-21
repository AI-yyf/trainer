/**
 * Phase-A runtime metrics (design package §14 / §03-1): request and duration
 * counters with in-memory state only. They answer the acceptance questions
 * "did normal UI activity touch the provider, the model catalog, or the
 * sidecar lifecycle" and give the hot-path latency spans a shared home.
 *
 * Deliberately not telemetry: nothing leaves the process. The snapshot is
 * readable in tests, in the output channel, and from diagnostics.
 */

export interface RuntimeMetricsSnapshot {
  /** Upstream provider verification/HTTP attempts (never chat content). */
  providerHttpRequests: number;
  providerHttpLastDurationMs: number;
  providerHttpTotalDurationMs: number;
  /** /provider/models catalog attempts — must stay 0 on pure UI activity. */
  modelCatalogRequests: number;
  modelCatalogLastDurationMs: number;
  /** Sidecar process starts — must stay 0 on pure UI activity. */
  sidecarStarts: number;
  /** Full runtime rehydrations (activation/workspace/engine-ready paths). */
  runtimeRehydrations: number;
  /** Webview sync activity: patches, full payloads, bytes, refresh calls. */
  webviewVisibilityShows: number;
  webviewSyncPatches: number;
  webviewSyncFullPatches: number;
  webviewSyncBytes: number;
}

const counters: RuntimeMetricsSnapshot = {
  providerHttpRequests: 0,
  providerHttpLastDurationMs: 0,
  providerHttpTotalDurationMs: 0,
  modelCatalogRequests: 0,
  modelCatalogLastDurationMs: 0,
  sidecarStarts: 0,
  runtimeRehydrations: 0,
  webviewVisibilityShows: 0,
  webviewSyncPatches: 0,
  webviewSyncFullPatches: 0,
  webviewSyncBytes: 0,
};

type MetricsListener = (snapshot: RuntimeMetricsSnapshot) => void;
const listeners = new Set<MetricsListener>();

function emit(): void {
  for (const listener of listeners) {
    try {
      listener(snapshotRuntimeMetrics());
    } catch {
      // Metrics must never break the caller.
    }
  }
}

export function recordProviderHttpRequest(durationMs: number): void {
  counters.providerHttpRequests += 1;
  counters.providerHttpLastDurationMs = Math.max(0, Math.round(durationMs));
  counters.providerHttpTotalDurationMs += Math.max(0, Math.round(durationMs));
  emit();
}

export function recordModelCatalogRequest(durationMs: number): void {
  counters.modelCatalogRequests += 1;
  counters.modelCatalogLastDurationMs = Math.max(0, Math.round(durationMs));
  emit();
}

export function recordSidecarStart(): void {
  counters.sidecarStarts += 1;
  emit();
}

export function recordRuntimeRehydration(): void {
  counters.runtimeRehydrations += 1;
  emit();
}

export function recordWebviewVisibilityShow(): void {
  counters.webviewVisibilityShows += 1;
  emit();
}

export function recordWebviewSync(options: { full: boolean; bytes: number }): void {
  if (options.full) {
    counters.webviewSyncFullPatches += 1;
  } else {
    counters.webviewSyncPatches += 1;
  }
  counters.webviewSyncBytes += Math.max(0, Math.round(options.bytes));
  emit();
}

export function snapshotRuntimeMetrics(): RuntimeMetricsSnapshot {
  return { ...counters };
}

/** Test/diagnostics helper: zero every counter. */
export function resetRuntimeMetrics(): void {
  for (const key of Object.keys(counters) as Array<keyof RuntimeMetricsSnapshot>) {
    counters[key] = 0;
  }
  emit();
}

export function onRuntimeMetrics(listener: MetricsListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function formatRuntimeMetrics(snapshot: RuntimeMetricsSnapshot): string {
  return (
    `[metrics] providerHttp=${snapshot.providerHttpRequests} ` +
    `models=${snapshot.modelCatalogRequests} sidecarStarts=${snapshot.sidecarStarts} ` +
    `rehydrations=${snapshot.runtimeRehydrations} shows=${snapshot.webviewVisibilityShows} ` +
    `patches=${snapshot.webviewSyncPatches} fullPatches=${snapshot.webviewSyncFullPatches} ` +
    `syncBytes=${snapshot.webviewSyncBytes}`
  );
}
