import { CollapsePanelIcon, ExpandPanelIcon } from "../icons";

export interface WorkbenchSurfaceButtonProps {
  /** `expand` opens a full-width editor tab; `collapse` returns to the sidebar. */
  mode: "expand" | "collapse";
  label: string;
  onClick: () => void;
}

/**
 * Compact surface control shared by the Learning header, the Resources toolbar
 * and the editor-panel shell header. Icon-only by design; aria-label/title
 * carry the action name so the narrow sidebar stays quiet.
 */
export function WorkbenchSurfaceButton({ mode, label, onClick }: WorkbenchSurfaceButtonProps) {
  const Icon = mode === "expand" ? ExpandPanelIcon : CollapsePanelIcon;
  return (
    <button
      type="button"
      className="button button--ghost button--micro workbench-surface-button workbench-surface-button--icon"
      data-workbench-surface-action={mode}
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      <span className="button__icon" aria-hidden="true">
        <Icon size={16} />
      </span>
    </button>
  );
}
