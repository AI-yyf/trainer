import type { ReactNode } from "react";
import { ActivityHeader } from "./ActivityHeader";
import type { TemplateAction } from "./NextAction";

/** Source identity, reading content, then contextual tools in a stable order. */
export function ResourceReader({ parent, title, source, updatedAt, stage, onBack, askCoach, openInEditor, openExternally, generatePractice, joinLearning, children }: {
  parent: string;
  title: string;
  source?: string;
  updatedAt?: string;
  stage?: string;
  onBack: () => void;
  askCoach?: TemplateAction;
  /** Open the original in VS Code (the editor remains the file owner). */
  openInEditor?: TemplateAction;
  /** Open the original through the OS default application / browser. */
  openExternally?: TemplateAction;
  generatePractice?: TemplateAction;
  joinLearning?: TemplateAction;
  children: ReactNode;
}) {
  const actions = [joinLearning, generatePractice, askCoach];
  const primaryAction = actions.find((action) => action && !action.disabled);
  return <section className="template-resource-reader" data-template="ResourceReader">
    <ActivityHeader parent={parent} title={title} onBack={onBack} />
    {source || updatedAt ? <p className="template-metadata">{[source, updatedAt].filter(Boolean).join(" · ")}</p> : null}
    {stage ? <p className="template-metadata">{stage}</p> : null}
    <div className="template-reader-actions">
      {actions.map((action, index) => action ? <button
        key={action.id ?? index}
        type="button"
        className={`button ${action === primaryAction ? "button--accent" : "button--ghost"}`}
        data-primary-action={action === primaryAction ? "true" : undefined}
        disabled={action.disabled || action.busy}
        aria-busy={action.busy || undefined}
        onClick={action.onClick}
      >{action.label}</button> : null)}
    </div>
    {openInEditor || openExternally ? (
      <div className="template-reader-open-actions" role="group">
        {[
          ["editor", openInEditor],
          ["external", openExternally],
        ].map(([kind, action]) => {
          const item = action as TemplateAction | undefined;
          return item ? (
            <button
              key={kind as string}
              type="button"
              className="button button--ghost button--compact"
              data-reader-open={kind as string}
              disabled={item.disabled || item.busy}
              aria-busy={item.busy || undefined}
              onClick={item.onClick}
            >
              {item.label}
            </button>
          ) : null;
        })}
      </div>
    ) : null}
    {children}
  </section>;
}
