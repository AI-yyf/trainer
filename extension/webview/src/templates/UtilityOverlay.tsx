import { useEffect, useRef, type ReactNode } from "react";

/** AppShell utilities keep focus inside the dialog and return it to their entry. */
export function UtilityOverlay({ label, closeLabel, onClose, children }: {
  label: string;
  closeLabel: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const element = panel.current;
    if (!element) return;
    const controls = () => Array.from(element.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex='0']"))
      .filter((control) => control.getClientRects().length > 0);
    (element.querySelector<HTMLInputElement>("input") ?? controls()[0] ?? element).focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); close.current(); return; }
      if (event.key !== "Tab") return;
      const items = controls();
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) { event.preventDefault(); element.focus(); return; }
      if (event.shiftKey && (document.activeElement === first || !element.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !element.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => { document.removeEventListener("keydown", keydown); if (previous?.isConnected) previous.focus(); };
  }, []);
  return <div className="app-shell-overlay" data-overlay="history">
    <button type="button" tabIndex={-1} className="app-shell-overlay__backdrop" aria-label={closeLabel} onClick={onClose} />
    <div ref={panel} className="app-shell-overlay__panel" role="dialog" aria-modal="true" aria-label={label} tabIndex={-1}>
      <button type="button" className="template-back" aria-label={closeLabel} onClick={onClose}>×</button>
      {children}
    </div>
  </div>;
}
