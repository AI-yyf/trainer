import { CollapsePanelIcon, ExpandPanelIcon } from "../icons";

export interface WorkbenchSurfaceButtonProps {
  /** `expand` opens a full-width editor tab; `collapse` returns to the sidebar. */
  mode: "expand" | "collapse";
  label: string;
  onClick: () => void;
}

/**
 * Compact surface control shared by the Learning header, the Resources toolbar
 * and the editor-panel shell header. Icon + label; the label collapses first
 * when the surface gets narrow (container query on `.trainer-shell`).
 */
export function WorkbenchSurfaceButton({ mode, label, onClick }: WorkbenchSurfaceButtonProps) {
  const Icon = mode === "expand" ? ExpandPanelIcon : CollapsePanelIcon;
  return (
    <button
      type="button"
      className="button button--ghost button--micro workbench-surface-button"
      data-workbench-surface-action={mode}
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      <span className="button__icon" aria-hidden="true">
        <Icon size={13} />
      </span>
      <span className="workbench-surface-button__label">{label}</span>
    </button>
  );
}
