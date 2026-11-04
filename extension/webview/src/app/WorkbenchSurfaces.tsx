import { memo, Profiler, useEffect, useState, type ReactNode } from "react";
import type { ActiveWorkbenchView } from "../lib/types";
import { recordSurfaceRender, surfaceProfiler } from './surfaceRuntimeMetrics';

const SurfaceContent = memo(function SurfaceContent({ view, hidden, render }: {
  view: ActiveWorkbenchView;
  hidden: boolean;
  render: (view: ActiveWorkbenchView) => ReactNode;
}) {
  recordSurfaceRender(view, hidden);
  const content = render(view);
  return window.__TRAINER_PROFILE_SURFACES__ === true
    ? <Profiler id={view} onRender={surfaceProfiler(view, hidden)}>{content}</Profiler> : content;
}, (previous, next) => {
  // Keep the actual subtree and its local draft/reader/scroll state. Hidden
  // surfaces defer parent-prop updates until the next visit; scoped store
  // subscriptions still receive their own business-critical transitions.
  if (previous.hidden && next.hidden) return true;
  return previous.hidden === next.hidden && previous.render === next.render;
});

/** Resources is the first surface a learner opens from Coach after a turn.
 *  Mount it during the first idle window so the click is a reveal, not a
 *  cold 4000-line component mount. */
const PRELOAD_VIEWS: ActiveWorkbenchView[] = ["resources"];

/** Retain visited surfaces so navigation does not discard readers or form state. */
export function WorkbenchSurfaces({ activeView, render }: {
  activeView: ActiveWorkbenchView;
  render: (view: ActiveWorkbenchView) => ReactNode;
}) {
  const [visited, setVisited] = useState<ActiveWorkbenchView[]>([activeView]);
  if (!visited.includes(activeView)) setVisited([...visited, activeView]);
  useEffect(() => {
    const addPreloaded = () => {
      setVisited((current) => {
        const next = [...current];
        for (const view of PRELOAD_VIEWS) {
          if (!next.includes(view)) next.push(view);
        }
        return next;
      });
    };
    const idle = window.requestIdleCallback;
    if (typeof idle === "function") {
      const handle = idle(addPreloaded, { timeout: 800 });
      return () => window.cancelIdleCallback?.(handle);
    }
    const timer = window.setTimeout(addPreloaded, 400);
    return () => window.clearTimeout(timer);
  }, []);
  return <>{visited.map((view) => (
    <div key={view} className="template-surface" data-surface={view} hidden={view !== activeView}>
      <SurfaceContent view={view} hidden={view !== activeView} render={render} />
    </div>
  ))}</>;
}
