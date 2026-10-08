import type { ReactNode } from "react";

export interface TemplateAction {
  id?: string;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
}

export interface NextActionProps {
  label: string;
  title: string;
  detail?: ReactNode;
  action: TemplateAction;
}

/**
 * A next step always has one title, one completion/reason, and one action.
 * r1-g1-1/r1-g1-4: the detail renders in full (no height clamp) so the
 * completion criteria never collapse into a titleless "···" fold.
 */
export function NextAction({ label, title, detail, action }: NextActionProps) {
  return (
    <section className="template-next-action" data-template="NextAction" aria-label={label}>
      <p className="template-metadata">{label}</p>
      <h3>{title}</h3>
      {detail ? <div className="template-next-action__detail">{detail}</div> : null}
      <button type="button" className="button button--accent" data-primary-action="true" data-action-intent={action.id} disabled={action.disabled || action.busy} aria-busy={action.busy || undefined} onClick={action.onClick}>{action.label}</button>
    </section>
  );
}
