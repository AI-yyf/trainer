import type { ReactNode } from "react";
import { ActivityHeader } from "./ActivityHeader";

/** Evidence-derived states first; drilldown stays with each dimension. No scores. */
export function GrowthEvidence({ parent, title, updated, onBack, children }: {
  parent: string; title: string; updated?: string; onBack: () => void; children: ReactNode;
}) {
  return <section className="template-growth-evidence" aria-label={title} data-template="GrowthEvidence">
    <ActivityHeader parent={parent} title={title} onBack={onBack} />
    {updated ? <p className="template-metadata">{updated}</p> : null}
    {children}
  </section>;
}
