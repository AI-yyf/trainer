import { useEffect, useRef } from "react";

export interface OverflowAction {
  id: string;
  label: string;
  disabled?: boolean;
  onClick: () => void;
}

/** Native disclosure semantics keep secondary tools keyboard-accessible. */
export function OverflowActions({ label, actions }: { label: string; actions: OverflowAction[] }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (event.target instanceof Node && !ref.current?.contains(event.target) && ref.current) ref.current.open = false;
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, []);
  return (
    <details ref={ref} className="template-overflow" onKeyDown={(event) => {
      if (event.key === "Escape" && ref.current?.open) { ref.current.open = false; ref.current.querySelector("summary")?.focus(); event.stopPropagation(); }
    }}>
      <summary aria-label={label} title={label}>···</summary>
      <div className="template-overflow__actions" role="group" aria-label={label}>
        {actions.map((action) => <button key={action.id} type="button" disabled={action.disabled} onClick={() => { if (ref.current) ref.current.open = false; action.onClick(); }}>{action.label}</button>)}
      </div>
    </details>
  );
}
