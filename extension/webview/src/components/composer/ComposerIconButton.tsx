import type { ReactNode } from "react";

export interface ComposerIconButtonProps {
  label: string;
  icon: ReactNode;
  active?: boolean;
  disabled?: boolean;
  className?: string;
  title?: string;
  ariaLabel?: string;
  onClick?: () => void;
}

export function ComposerIconButton({
  label,
  icon,
  active = false,
  disabled = false,
  className,
  title,
  ariaLabel,
  onClick,
}: ComposerIconButtonProps) {
  const classes = ["icon-button", active ? "is-active" : "", className].filter(Boolean).join(" ");

  return (
    <button
      aria-label={ariaLabel ?? label}
      aria-pressed={active}
      className={classes}
      disabled={disabled}
      // Custom CSS tooltip (data-tip) instead of the native title: it lets
      // us apply the first-hover delay + adjacent-instant pattern from the
      // design-engineering skill set. aria-label stays the a11y name.
      data-tip={title ?? label}
      type="button"
      onClick={onClick}
    >
      <span className="icon-button__glyph" aria-hidden="true">
        {icon}
      </span>
    </button>
  );
}
