import type { ReactNode } from "react";
import { ChevronRightIcon } from "../components/icons";

export type SettingsSectionId = "connection" | "teaching" | "workspace" | "preferences";
export interface SettingsIndexItem {
  id: SettingsSectionId;
  label: string;
  summary?: string;
  summaryTitle?: string;
  icon?: ReactNode;
  dirty?: boolean;
  action?: { label: string; onClick: () => void; icon?: ReactNode };
}

/**
 * Settings are destinations with factual summaries, not horizontal tabs.
 *
 * ``variant="rail"`` is the same destination list as a persistent wide-screen
 * navigation column; it drops summaries and inline actions so the right-hand
 * detail pane stays the only place for configuration work.
 */
export function SettingsIndex({
  title,
  items,
  onSelect,
  variant = "page",
  activeId,
}: {
  title: string;
  items: SettingsIndexItem[];
  onSelect: (id: SettingsSectionId) => void;
  variant?: "page" | "rail";
  activeId?: SettingsSectionId;
}) {
  const rail = variant === "rail";
  return (
    <section
      className={`template-settings-index${rail ? " template-settings-index--rail" : ""}`}
      data-template="SettingsIndex"
      data-settings-variant={variant}
      aria-label={title}
    >
      {rail ? null : <h2>{title}</h2>}
      <ul>
        {items.map((item) => {
          const active = rail && item.id === activeId;
          return (
            <li key={item.id}>
              <div className="template-settings-index__row">
                <button
                  type="button"
                  data-settings-category={rail ? undefined : item.id}
                  data-settings-rail-category={rail ? item.id : undefined}
                  data-settings-active={active ? "true" : undefined}
                  aria-current={active ? "page" : undefined}
                  onClick={() => onSelect(item.id)}
                >
                  {item.icon ? <span className="template-settings-index__icon" aria-hidden="true">{item.icon}</span> : null}
                  <span><strong>{item.label}{item.dirty ? " ·" : ""}</strong>{!rail && item.summary ? <small title={item.summaryTitle ?? item.summary}>{item.summary}</small> : null}</span>
                  {rail ? null : (
                    <span className="template-settings-index__chevron" aria-hidden="true">
                      <ChevronRightIcon size={14} />
                    </span>
                  )}
                </button>
                {!rail && item.action ? (
                  <button type="button" className="template-settings-index__action" onClick={item.action.onClick}>
                    {item.action.icon ? <span className="template-settings-index__action-icon" aria-hidden="true">{item.action.icon}</span> : null}
                    {item.action.label}
                  </button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
