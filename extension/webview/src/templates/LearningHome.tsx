import type { ReactNode } from "react";
import { NextAction, type NextActionProps } from "./NextAction";

export interface LearningHomeProps {
  currentLabel: string;
  title: string;
  stage?: string;
  next: NextActionProps;
  nextTools?: ReactNode;
  state?: ReactNode;
  review?: { label: string; content: ReactNode };
  route?: { label: string; content: ReactNode };
  growth?: { label: string; content: ReactNode };
  evidence?: { label: string; content: ReactNode };
  children?: ReactNode;
}

/** Current learning precedes review, route, growth and evidence disclosures. */
export function LearningHome({ currentLabel, title, stage, next, nextTools, state, review, route, growth, evidence, children }: LearningHomeProps) {
  return (
    <section className="template-learning-home" data-template="LearningHome" data-plan-primary="true">
      <header><p className="template-metadata">{currentLabel}</p><h2>{title}</h2>{stage ? <p className="template-metadata">{stage}</p> : null}</header>
      {state}
      <NextAction {...next} />
      {nextTools}
      {([ ["reviews", review], ["route", route], ["growth", growth], ["evidence", evidence] ] as const).map(([id, slot]) => slot ? (
        <details key={id} className="template-disclosure" data-learning-section={id}><summary>{slot.label}</summary><div>{slot.content}</div></details>
      ) : null)}
      {children}
    </section>
  );
}
