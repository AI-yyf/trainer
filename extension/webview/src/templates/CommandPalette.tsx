import { useEffect, useRef, useState, type ReactNode } from "react";

export interface PaletteEntry { id: string; trigger: string; title: string; detail?: string; onSelect: () => void }

/**
 * Search is owned by the invoking input; this template owns option order and focus.
 * r1-g0-4: the scroller snaps its height to whole entry rows and the palette
 * carries a visible "↓ N more" hint plus a bottom fade while rows sit below
 * the fold.
 */
export function CommandPalette({ label, hint, entries, selectedIndex, onHighlight, empty, footer, containerRef, moreLabel }: {
  label: string; hint?: string; entries: PaletteEntry[]; selectedIndex: number;
  onHighlight: (index: number) => void; empty: string; footer?: ReactNode; containerRef?: { current: HTMLDivElement | null };
  /** "{n}" slot replaced with the number of rows still below the fold. */
  moreLabel?: string;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [fold, setFold] = useState<{ scrollable: boolean; hidden: number }>({ scrollable: false, hidden: 0 });

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) {
      return;
    }
    // Row-align the height: clamp the CSS max-height down to a whole number of
    // entry rows plus the fixed chrome, so the last visible row is never
    // sliced mid-text. The inline value is reset first so the CSS cap
    // (min(260px, 36vh)) stays the source of truth across re-measures.
    const entry = scroller.querySelector<HTMLElement>(".template-command-palette__entry");
    scroller.style.maxHeight = "";
    const styles = window.getComputedStyle(scroller);
    const cssCap = Number.parseFloat(styles.maxHeight);
    if (entry && Number.isFinite(cssCap) && cssCap > 0) {
      const row = entry.offsetHeight;
      const rowGap = Number.parseFloat(styles.rowGap) || 0;
      const padY = Number.parseFloat(styles.paddingTop) + Number.parseFloat(styles.paddingBottom);
      const fixedChrome =
        scroller.querySelector<HTMLElement>(".template-command-palette__footer")?.offsetHeight ?? 0;
      if (row > 0) {
        const usable = Math.max(cssCap - padY - fixedChrome + rowGap, row);
        const rows = Math.max(Math.floor(usable / (row + rowGap)), 1);
        scroller.style.maxHeight = `${Math.min(rows * row + (rows - 1) * rowGap + padY + fixedChrome, cssCap)}px`;
      }
    }
    const measure = () => {
      const belowFold = Array.from(
        scroller.querySelectorAll<HTMLElement>(".template-command-palette__entry"),
      ).filter((row) => row.offsetTop + row.offsetHeight > scroller.scrollTop + scroller.clientHeight).length;
      setFold({
        scrollable: scroller.scrollHeight > scroller.clientHeight + 1,
        hidden: belowFold,
      });
    };
    measure();
    scroller.addEventListener("scroll", measure, { passive: true });
    const observer = new ResizeObserver(measure);
    observer.observe(scroller);
    return () => {
      scroller.removeEventListener("scroll", measure);
      observer.disconnect();
    };
  }, [entries.length]);

  return <div ref={containerRef} className={`template-command-palette${fold.scrollable ? " is-scrollable" : ""}`} data-template="CommandPalette" role="listbox" aria-label={label}>
    <div className="template-command-palette__scroll" ref={scrollRef}>
      {hint ? <p className="template-metadata">{hint}</p> : null}
      {entries.length ? entries.map((entry, index) => <button key={entry.id} type="button" role="option" aria-selected={selectedIndex === index}
        className={`template-command-palette__entry${selectedIndex === index ? " is-active" : ""}`} onMouseEnter={() => onHighlight(index)} onClick={entry.onSelect}>
        <span className="template-command-palette__trigger">{entry.trigger}</span><span><strong>{entry.title}</strong>{entry.detail ? <span>{entry.detail}</span> : null}</span>
      </button>) : <p>{empty}</p>}
      {footer ? <div className="template-command-palette__footer">{footer}</div> : null}
    </div>
    {fold.scrollable && fold.hidden > 0 && moreLabel ? (
      <p className="template-command-palette__more" aria-hidden="true">
        {moreLabel.replace("{n}", String(fold.hidden))}
      </p>
    ) : null}
  </div>;
}
