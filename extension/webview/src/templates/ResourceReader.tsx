import type { ReactNode } from "react";
import { ActivityHeader } from "./ActivityHeader";
import type { TemplateAction } from "./NextAction";

/** Source identity, reading content, then contextual tools in a stable order. */
export function ResourceReader({ parent, title, source, updatedAt, onBack, askCoach, generatePractice, joinLearning, children }: {
  parent: string;
  title: string;
  source?: string;
  updatedAt?: string;
  onBack: () => void;
  askCoach?: TemplateAction;
  generatePractice?: TemplateAction;
  joinLearning?: TemplateAction;
  children: ReactNode;
}) {
  return <section className="template-resource-reader" data-template="ResourceReader">
    <ActivityHeader parent={parent} title={title} onBack={onBack} />
    {source || updatedAt ? <p className="template-metadata">{[source, updatedAt].filter(Boolean).join(" · ")}</p> : null}
    {children}
    <div className="template-reader-actions">
      {askCoach ? <button type="button" className="button button--accent" data-primary-action="true" disabled={askCoach.disabled} onClick={askCoach.onClick}>{askCoach.label}</button> : null}
      {[generatePractice, joinLearning].map((action, index) => action ? <button key={index} type="button" className="button button--ghost" disabled={action.disabled || action.busy} aria-busy={action.busy || undefined} onClick={action.onClick}>{action.label}</button> : null)}
    </div>
  </section>;
}
