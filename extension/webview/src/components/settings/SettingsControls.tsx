import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDownIcon } from "../icons";

/**
 * Settings 表单基础控件 (P2 模块化，自 CoachSettingsView 迁出)。
 * 纯展示切片：ChoiceList（带键盘导航的下拉）、SummaryCard、SimpleInfoRow、
 * ContextList——与设置状态零耦合，行为与迁出前逐行一致。
 */

export function ChoiceList<T extends string>({
  items,
  active,
  onChange,
}: {
  items: Array<{ label: string; value: T }>;
  active?: T;
  onChange?: (value: T) => void;
}) {
  // One themed pull-down per row: trigger shows the current choice, the
  // listbox opens below, closes on outside click or on pick.
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const focusChoiceOnOpenRef = useRef(false);
  useEffect(() => {
    if (!open) {
      return;
    }
    if (focusChoiceOnOpenRef.current) {
      rootRef.current?.querySelector<HTMLButtonElement>('[role="option"][aria-selected="true"]')?.focus();
      focusChoiceOnOpenRef.current = false;
    }
    const onDocMouseDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);
  const effective = active ?? items[0]?.value;
  const current = items.find((item) => item.value === effective) ?? items[0];
  return (
    <div className="settings-sheet__group settings-choice" ref={rootRef} onKeyDown={(event) => {
      if (event.key === "Escape" && open) {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      if (!open) {
        focusChoiceOnOpenRef.current = true;
        setOpen(true);
        return;
      }
      const options = Array.from(rootRef.current?.querySelectorAll<HTMLButtonElement>('[role="option"]') ?? []);
      if (!options.length) return;
      const focusedIndex = options.findIndex((option) => option === document.activeElement);
      const index = focusedIndex >= 0 ? focusedIndex
        : options.findIndex((option) => option.getAttribute("aria-selected") === "true");
      const next = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1
        : (index + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
      options[next]?.focus();
    }}>
      <button
        ref={triggerRef}
        type="button"
        className="settings-choice__trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="settings-choice__trigger-label">{current?.label}</span>
        <ChevronDownIcon size={12} aria-hidden="true" />
      </button>
      {open ? (
        <div className="settings-choice__list" role="listbox">
          {items.map((item) => (
            <button
              key={item.value}
              type="button"
              role="option"
              aria-selected={item.value === effective}
              className={`settings-choice__option ${item.value === effective ? "is-active" : ""}`}
              onClick={() => {
                onChange?.(item.value);
                setOpen(false);
                triggerRef.current?.focus();
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function SummaryCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <div className="settings-sheet__summary-card">
      <span className="settings-sheet__summary-card-label">{label}</span>
      <strong className="settings-sheet__summary-card-value">{value}</strong>
      {detail ? <p className="settings-sheet__note settings-sheet__note--compact">{detail}</p> : null}
    </div>
  );
}

export function SimpleInfoRow({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="settings-sheet__simple-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function ContextList({
  rows,
  onLabel,
  offLabel,
}: {
  rows: Array<{ label: string; enabled: boolean; detail: string; onToggle: () => void }>;
  onLabel: string;
  offLabel: string;
}) {
  return (
    <div className="settings-sheet__workspace-list">
      {rows.map((row) => (
        <button
          key={row.label}
          className={`settings-sheet__workspace-list-item ${row.enabled ? "is-enabled" : ""}`}
          type="button"
          aria-pressed={row.enabled}
          title={row.detail}
          onClick={row.onToggle}
        >
          <strong>{row.label}</strong>
          <em>{row.enabled ? onLabel : offLabel}</em>
        </button>
      ))}
    </div>
  );
}
