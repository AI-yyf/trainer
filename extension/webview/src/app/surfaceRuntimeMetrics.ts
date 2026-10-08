import type { ProfilerOnRenderCallback } from 'react';
import type { ActiveWorkbenchView } from '../lib/types';

export interface SurfaceRuntimeSample {
  renders: number;
  hiddenRenders: number;
  commits: number;
  hiddenCommits: number;
  actualDurationMs: number;
  baseDurationMs: number;
}

declare global {
  interface Window {
    __TRAINER_PROFILE_SURFACES__?: boolean;
    __TRAINER_SURFACE_METRICS__?: Partial<Record<ActiveWorkbenchView, SurfaceRuntimeSample>>;
  }
}

function sample(view: ActiveWorkbenchView): SurfaceRuntimeSample {
  const metrics = window.__TRAINER_SURFACE_METRICS__ ??= {};
  return metrics[view] ??= { renders: 0, hiddenRenders: 0, commits: 0, hiddenCommits: 0,
    actualDurationMs: 0, baseDurationMs: 0 };
}

export function recordSurfaceRender(view: ActiveWorkbenchView, hidden: boolean): void {
  if (window.__TRAINER_PROFILE_SURFACES__ !== true) return;
  const current = sample(view);
  current.renders += 1;
  if (hidden) current.hiddenRenders += 1;
}

export function surfaceProfiler(view: ActiveWorkbenchView, hidden: boolean): ProfilerOnRenderCallback {
  return (_id, _phase, actualDuration, baseDuration) => {
    const current = sample(view);
    current.commits += 1;
    if (hidden) current.hiddenCommits += 1;
    current.actualDurationMs += actualDuration;
    current.baseDurationMs = baseDuration;
  };
}
