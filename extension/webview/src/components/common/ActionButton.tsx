import type { ReactNode, ButtonHTMLAttributes } from "react";

import { ArrowRightIcon } from "../icons";

export interface ActionButtonProps
  extends Pick<ButtonHTMLAttributes<HTMLButtonElement>, "disabled" | "type" | "onClick" | "title"> {
  icon?: ReactNode;
  label: string;
  detail?: ReactNode;
  tone?: "accent" | "ghost";
  fullWidth?: boolean;
  className?: string;
  /** Override the composed label when a concise accessible name is required. */
  ariaLabel?: string;
  "data-view-primary"?: string;
}

export function ActionButton({
  icon,
  label,
  detail,
  tone = "ghost",
  fullWidth = true,
  className,
  disabled,
  type = "button",
  onClick,
  title,
  ariaLabel,
  "data-view-primary": viewPrimary,
}: ActionButtonProps) {
  const classes = [
    "action-button",
    `action-button--${tone}`,
    fullWidth ? "action-button--full" : "action-button--inline",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  const accessibleName = [label, typeof detail === "string" ? detail : undefined]
    .filter(Boolean)
    .join(". ");

  return (
    <button
      className={classes}
      type={type}
      disabled={disabled}
      onClick={onClick}
      title={title}
      aria-label={ariaLabel ?? accessibleName}
      data-view-primary={viewPrimary}
    >
      {icon ? (
        <span className="action-button__icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <span className="action-button__copy">
        <strong className="action-button__label">{label}</strong>
        {detail ? <span className="action-button__detail">{detail}</span> : null}
      </span>
      <span className="action-button__chev" aria-hidden="true">
        <ArrowRightIcon size={13} />
      </span>
    </button>
  );
}
