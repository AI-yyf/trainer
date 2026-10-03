import type { ReactNode, RefObject } from "react";

export interface PaletteEntry { id: string; trigger: string; title: string; detail?: string; onSelect: () => void }

/** Search is owned by the invoking input; this template owns option order and focus. */
export function CommandPalette({ label, hint, entries, selectedIndex, onHighlight, empty, footer, containerRef }: {
  label: string; hint?: string; entries: PaletteEntry[]; selectedIndex: number;
  onHighlight: (index: number) => void; empty: string; footer?: ReactNode; containerRef?: RefObject<HTMLDivElement>;
}) {
  return <div ref={containerRef} className="template-command-palette" data-template="CommandPalette" role="listbox" aria-label={label}>
    {hint ? <p className="template-metadata">{hint}</p> : null}
    {entries.length ? entries.map((entry, index) => <button key={entry.id} type="button" role="option" aria-selected={selectedIndex === index}
      className={`template-command-palette__entry${selectedIndex === index ? " is-active" : ""}`} onMouseEnter={() => onHighlight(index)} onClick={entry.onSelect}>
      <span className="template-command-palette__trigger">{entry.trigger}</span><span><strong>{entry.title}</strong>{entry.detail ? <span>{entry.detail}</span> : null}</span>
    </button>) : <p>{empty}</p>}
    {footer ? <div className="template-command-palette__footer">{footer}</div> : null}
  </div>;
}
