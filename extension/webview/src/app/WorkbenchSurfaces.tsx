import { useState, type ReactNode } from "react";
import type { ActiveWorkbenchView } from "../lib/types";

/** Retain visited surfaces so navigation does not discard readers or form state. */
export function WorkbenchSurfaces({ activeView, render }: {
  activeView: ActiveWorkbenchView;
  render: (view: ActiveWorkbenchView) => ReactNode;
}) {
  const [visited, setVisited] = useState<ActiveWorkbenchView[]>([activeView]);
  if (!visited.includes(activeView)) setVisited([...visited, activeView]);
  return <>{visited.map((view) => (
    <div key={view} className="template-surface" data-surface={view} hidden={view !== activeView}>
      {render(view)}
    </div>
  ))}</>;
}
