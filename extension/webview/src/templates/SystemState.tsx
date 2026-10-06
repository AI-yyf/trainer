import type { ReactNode } from "react";
import type { TemplateAction } from "./NextAction";

export type SystemStateKind = "information" | "loading" | "empty" | "processing" | "success" | "error" | "recoverable-error" | "disconnected" | "provider-required" | "workspace-required" | "permission-required" | "read-only" | "remote-unavailable";

export interface SystemStateProps {
  kind: SystemStateKind;
  title: string;
  detail?: ReactNode;
  action?: TemplateAction;
  /** Visual weight of the action: solid accent (default) or quiet ghost —
      used when the state's action is not the surface's primary goal. */
  actionTone?: "accent" | "ghost";
  children?: ReactNode;
}

/** States share information order and a single recovery action. */
export function SystemState({ kind, title, detail, action, actionTone = "accent", children }: SystemStateProps) {
  const pending = kind === "loading" || kind === "processing";
  return (
    <section className={`template-system-state template-system-state--${kind}`} data-template="SystemState" data-system-state={kind} role={kind === "error" || kind === "recoverable-error" ? "alert" : "status"} aria-live={kind === "error" || kind === "recoverable-error" ? "assertive" : "polite"} aria-busy={pending || undefined}>
      {kind === "loading" ? <span className="skeleton template-system-state__skeleton" aria-hidden="true" /> : null}
      {kind === "processing" ? <span className="trainer-spinner" aria-hidden="true" /> : null}
      <h3>{title}</h3>
      {detail ? <div className="template-system-state__detail">{detail}</div> : null}
      {children}
      {action ? <button type="button" className={`button ${actionTone === "ghost" ? "button--ghost" : "button--accent"}`} data-primary-action={actionTone === "ghost" ? undefined : "true"} disabled={action.disabled || action.busy} aria-busy={action.busy || undefined} onClick={action.onClick}>{action.label}</button> : null}
    </section>
  );
}
