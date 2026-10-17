import { dockReturnBannerCopy, type ComposerDockSurface } from "../../lib/composerDock";

export interface DockReturnToSurfaceBarProps {
  language: string;
  surface: Exclude<ComposerDockSurface, "coach">;
  onViewReply: () => void;
  onDismiss: () => void;
}

/**
 * returnToSurface bar (§3.7 red line 5, stay mode): after a stay-mode send
 * finishes, the surface the learner remained on shows this actionable bar
 * instead of a transient toast. "View reply" follows the answer into Coach;
 * the back action dismisses the bar and keeps the surface (per-surface
 * scroll restore stays with useSurfaceScroll).
 */
export function DockReturnToSurfaceBar({
  language,
  surface,
  onViewReply,
  onDismiss,
}: DockReturnToSurfaceBarProps) {
  const copy = dockReturnBannerCopy(language, surface);
  return (
    <div className="template-context" role="group" data-dock-return="true">
      <span>{copy.title}</span>
      <button
        type="button"
        className="template-back"
        data-dock-return-action="view"
        onClick={onViewReply}
      >
        {copy.action}
      </button>
      <button
        type="button"
        className="template-back"
        data-dock-return-action="stay"
        onClick={onDismiss}
      >
        {copy.back}
      </button>
    </div>
  );
}
