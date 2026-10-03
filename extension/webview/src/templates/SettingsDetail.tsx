import type { ReactNode } from "react";
import { ActivityHeader } from "./ActivityHeader";

export function SettingsDetail({ parent, title, section, onBack, children }: {
  parent: string;
  title: string;
  section?: string;
  onBack: () => void;
  children: ReactNode;
}) {
  return <section data-template="SettingsDetail" data-settings-detail={section}><ActivityHeader parent={parent} title={title} onBack={onBack} />{children}</section>;
}
