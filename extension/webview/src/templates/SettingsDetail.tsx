import type { ReactNode } from "react";
import { ActivityHeader } from "./ActivityHeader";

export function SettingsDetail({
  parent,
  title,
  section,
  onBack,
  nav,
  children,
}: {
  parent: string;
  title: string;
  section?: string;
  onBack: () => void;
  nav?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      data-template="SettingsDetail"
      data-settings-detail={section}
      className={`template-settings-detail${nav ? " template-settings-detail--split" : ""}`}
    >
      {nav ? (
        <aside className="template-settings-detail__nav" aria-label={parent}>
          {nav}
        </aside>
      ) : null}
      <div className="template-settings-detail__content">
        <ActivityHeader parent={parent} title={title} onBack={onBack} />
        {children}
      </div>
    </section>
  );
}
