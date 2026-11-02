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
                <span><strong>{item.label}{item.dirty ? " ·" : ""}</strong>{item.summary ? <small title={item.summaryTitle ?? item.summary}>{item.summary}</small> : null}</span>
                <span className="template-settings-index__chevron" aria-hidden="true">
                  <ChevronRightIcon size={14} />
                </span>
              </button>
              {item.action ? (
                <button type="button" className="template-settings-index__action" onClick={item.action.onClick}>
                  {item.action.icon ? <span className="template-settings-index__action-icon" aria-hidden="true">{item.action.icon}</span> : null}
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
