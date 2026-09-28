import type { ReactNode } from "react";

/**
 * Design-system loading indicator (§四十八).
 *
 * A token-driven ring spinner; screen readers get `role="status"` with the
 * caller's localized label. Under `prefers-reduced-motion` the CSS swaps the
 * rotation for a calm ring-and-dot mark.
 */
export function TrainerSpinner({
  size = "md",
  label,
  children,
}: {
  size?: "sm" | "md" | "lg";
  /** Localized status text for assistive tech (and the visible label when children are absent). */
  label: string;
  /** Optional visible label; when omitted only the ring renders. */
  children?: ReactNode;
}) {
  return (
    <span className="trainer-spinner-status" role="status" aria-label={label}>
      <span aria-hidden="true" className={`trainer-spinner trainer-spinner--${size}`} />
      {children ? (
        <span className="trainer-spinner-status__label">{children}</span>
      ) : null}
    </span>
  );
}
