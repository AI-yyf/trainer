import { useEffect, useRef, useState, type ReactNode } from "react";

export interface TemplateAction {
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

/** A next step always has one title, one completion/reason, and one action. */
export function NextAction({ label, title, detail, action }: NextActionProps) {
  const preview = useRef<HTMLDivElement>(null);
  const [overflow, setOverflow] = useState(false);
  useEffect(() => {
    const node = preview.current;
    if (!node) return;
    const measure = () => setOverflow(node.scrollHeight > node.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [detail]);
  return (
    <section className="template-next-action" data-template="NextAction" aria-label={label}>
      <p className="template-metadata">{label}</p>
      <h3>{title}</h3>
      {detail ? <>
        <div ref={preview} className="template-next-action__detail">{detail}</div>
        {overflow ? <details className="template-disclosure template-next-action__full"><summary aria-label={label}>···</summary><div>{detail}</div></details> : null}
      </> : null}
      <button type="button" className="button button--accent" data-primary-action="true" disabled={action.disabled || action.busy} aria-busy={action.busy || undefined} onClick={action.onClick}>{action.label}</button>
    </section>
  );
}
