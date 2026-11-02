import type { ReactNode } from "react";
import { NextAction, type NextActionProps } from "./NextAction";

export interface LearningHomeSlot {
  label: string;
  content: ReactNode;
  /** Optional card count shown in the group label. */
  count?: number;
}

export interface LearningHomeProps {
  currentLabel: string;
  title: string;
  stage?: string;
  next: NextActionProps;
  nextTools?: ReactNode;
  state?: ReactNode;
  /** Merged proof debt: due reviews + evidence to adopt (§3.4). DOM id stays "reviews". */
  proof?: LearningHomeSlot;
  route?: LearningHomeSlot;
  growth?: LearningHomeSlot;
  /** Optional surface control rendered in the header (e.g. open full width). */
  headerActions?: ReactNode;
  children?: ReactNode;
}

function LearningCardGroup({
  id,
  label,
  count,
  children,
}: {
  id: string;
  label: string;
  count?: number;
  children: ReactNode;
}) {
  return (
    <section
      className="learning-card-group"
      data-learning-section={id}
      data-learning-card-group={id}
    >
      <header className="learning-card-group__header">
        <h3>{label}</h3>
        {typeof count === "number" ? (
          <span className="learning-card-group__count">{count}</span>
        ) : null}
      </header>
      <div className="learning-card-group__cards">{children}</div>
    </section>
  );
}

/**
 * Learning is a stack of cards: one current-action card, then compact groups
 * of path, proof and growth cards. There is no board frame around the groups:
 * each item stands on its own, so the sidebar stays quiet and scannable.
 */
export function LearningHome({
  currentLabel,
  title,
  stage,
  next,
  nextTools,
  state,
  proof,
  route,
  growth,
  headerActions,
  children,
}: LearningHomeProps) {
  return (
    <section
      className="template-learning-home learning-cards"
      data-template="LearningHome"
      data-plan-primary="true"
    >
      <header className="learning-cards__header">
        <p className="eyebrow">{currentLabel}</p>
        <h2>{title}</h2>
        {stage ? <p className="template-metadata">{stage}</p> : null}
        {headerActions ? (
          <div className="template-learning-home__header-actions">{headerActions}</div>
        ) : null}
      </header>
      <div className="learning-card-stack">
        <section
          className="learning-card learning-card--now"
          data-learning-section="current"
          data-learning-card-group="current"
        >
          {state ? state : <NextAction {...next} />}
          {nextTools}
        </section>
        {route ? (
          <LearningCardGroup id="route" label={route.label} count={route.count}>
            {route.content}
          </LearningCardGroup>
        ) : null}
        {proof ? (
          <LearningCardGroup id="reviews" label={proof.label} count={proof.count}>
            {proof.content}
          </LearningCardGroup>
        ) : null}
        {growth ? (
          <LearningCardGroup id="growth" label={growth.label} count={growth.count}>
            {growth.content}
          </LearningCardGroup>
        ) : null}
      </div>
      {children ? (
        <div className="learning-card-stack learning-card-stack--more">{children}</div>
      ) : null}
    </section>
  );
}
