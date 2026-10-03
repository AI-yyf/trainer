import type { ReactNode } from "react";

/** Append-only coach content; artifacts and contextual tools belong to each reply. */
export function Conversation({ className, label, header, footer, children }: {
  className?: string; label?: string; header?: ReactNode; footer?: ReactNode; children: ReactNode;
}) {
  return <section className={className} aria-label={label} data-template="Conversation">{header}{children}{footer}</section>;
}
