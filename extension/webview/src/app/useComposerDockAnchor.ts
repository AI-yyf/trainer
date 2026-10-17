import { useEffect, useState } from "react";
import { resolveDockContextAnchor } from "../lib/composerDock";
import type { ActiveWorkbenchView } from "../lib/types";

/**
 * Dock composer context anchor state (§3.7 red line 4): a send from Learning
 * carries the current stage and a send from Resources carries the open
 * resource/selection. The chip is auto-attached per surface, removable per
 * anchor identity, and re-armed automatically when the underlying context
 * changes (a new stage or a different resource re-anchors the dock).
 */
export function useComposerDockAnchor(
  surface: ActiveWorkbenchView,
  stageTitle?: string | null,
  stageProgress?: string | null,
  resourceLabel?: string | null,
) {
  const [suppressedId, setSuppressedId] = useState<string | null>(null);
  const anchor = resolveDockContextAnchor(surface, { stageTitle, stageProgress, resourceLabel });
  const anchorId = anchor?.id ?? null;
  useEffect(() => {
    setSuppressedId(null);
  }, [anchorId]);
  const suppressed = anchorId !== null && suppressedId === anchorId;
  return {
    anchor: suppressed ? null : anchor,
    suppressed,
    suppress: () => setSuppressedId(anchorId),
  };
}
