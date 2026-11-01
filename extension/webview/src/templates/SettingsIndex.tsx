import type { ReactNode } from "react";

export type SettingsSectionId = "connection" | "teaching" | "workspace" | "preferences";
export interface SettingsIndexItem {
  id: SettingsSectionId;
  label: string;
  summary?: string;
  icon?: ReactNode;
  dirty?: boolean;
  action?: { label: string; onClick: () => void };
}

/** Settings are destinations with factual summaries, not horizontal tabs. */
export function SettingsIndex({ title, items, onSelect }: {
  title: string;
  items: SettingsIndexItem[];
  onSelect: (id: SettingsSectionId) => void;
}) {
  return (
    <section className="template-settings-index" data-template="SettingsIndex" aria-label={title}>
      <h2>{title}</h2>
      <ul>
        {items.map((item) => (
          <li key={item.id}>
            <div className="template-settings-index__row">
              <button type="button" data-settings-category={item.id} onClick={() => onSelect(item.id)}>
                {item.icon ? <span className="template-settings-index__icon" aria-hidden="true">{item.icon}</span> : null}
                <span><strong>{item.label}{item.dirty ? " ·" : ""}</strong>{item.summary ? <small>{item.summary}</small> : null}</span>
                <span aria-hidden="true">›</span>
              </button>
              {item.action ? (
                <button type="button" className="template-settings-index__action" onClick={item.action.onClick}>
                  {item.action.label}
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
