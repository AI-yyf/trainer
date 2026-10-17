import type { ReactNode } from "react";
import { NextAction, type NextActionProps } from "./NextAction";

export interface LearningHomeProps {
  currentLabel: string;
  title: string;
  stage?: string;
  next: NextActionProps;
  nextTools?: ReactNode;
  state?: ReactNode;
  /** Merged proof debt: due reviews + evidence to adopt (§3.4). DOM id stays "reviews". */
  proof?: { label: string; content: ReactNode };
  route?: { label: string; content: ReactNode };
  growth?: { label: string; content: ReactNode };
  /** Optional surface control rendered in the header (e.g. open full width). */
  headerActions?: ReactNode;
  children?: ReactNode;
}

/** Current learning precedes review, route, growth and evidence disclosures. */
export function LearningHome({ currentLabel, title, stage, next, nextTools, state, proof, route, growth, headerActions, children }: LearningHomeProps) {
  return (
    <section className="template-learning-home" data-template="LearningHome" data-plan-primary="true">
      <header><p className="template-metadata">{currentLabel}</p><h2>{title}</h2>{stage ? <p className="template-metadata">{stage}</p> : null}{headerActions ? <div className="template-learning-home__header-actions">{headerActions}</div> : null}</header>
      {state ? state : <NextAction {...next} />}
      {nextTools}
      {([ ["reviews", proof], ["route", route], ["growth", growth] ] as const).map(([id, slot]) => slot ? (
        <details key={id} className="template-disclosure" data-learning-section={id}><summary>{slot.label}</summary><div>{slot.content}</div></details>
      ) : null)}
      {children}
    </section>
  );
}
