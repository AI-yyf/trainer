import type { CSSProperties, ReactNode } from "react";
import { NextAction, type NextActionProps } from "./NextAction";

export interface LearningHomeSlot {
  label: string;
  content: ReactNode;
  /** Optional card count shown in the group label. */
  count?: number;
}

export interface LearningTodayView {
  eyebrow: string;
  title: string;
  detail?: string;
  progress: number;
  done: number;
  total: number;
  due: number;
  dueLabel: string;
  remaining: number;
  remainingLabel: string;
}

export interface LearningHomeProps {
  currentLabel: string;
  title: string;
  stage?: string;
  today?: LearningTodayView;
  next: NextActionProps;
  nextTools?: ReactNode;
  state?: ReactNode;
  /** Merged proof debt: due reviews + evidence to adopt (§3.4). DOM id stays "reviews". */
  proof?: LearningHomeSlot;
  route?: LearningHomeSlot;
  growth?: LearningHomeSlot;
  /** Optional surface control rendered in the header (e.g. open full width). */
  headerActions?: ReactNode;
  /** Label for the one disclosure that holds non-stage content. */
  moreLabel?: string;
  children?: ReactNode;
}

function LearningCardGroup({
  id,
  label,
  count,
  collapsible = false,
  children,
}: {
  id: string;
  label: string;
  count?: number;
  collapsible?: boolean;
  children: ReactNode;
}) {
  const header = (
    <header className="learning-card-group__header">
      <h3>{label}</h3>
      {typeof count === "number" ? (
        <span className="learning-card-group__count">{count}</span>
      ) : null}
    </header>
  );
  if (collapsible) {
    return (
      <details
        className="learning-card-group learning-card-group--collapsible"
        data-learning-section={id}
        data-learning-card-group={id}
        data-learning-collapsible="true"
      >
        <summary>{header}</summary>
        <div className="learning-card-group__cards">{children}</div>
      </details>
    );
  }
  return (
    <section
      className="learning-card-group"
      data-learning-section={id}
      data-learning-card-group={id}
    >
      {header}
      <div className="learning-card-group__cards">{children}</div>
    </section>
  );
}

/**
 * Learning is a stack of cards: one current-action card, then compact groups
 * of proof, path and growth cards. There is no board frame around the groups:
 * each item stands on its own, so the sidebar stays quiet and scannable.
 */
export function LearningHome({
  currentLabel,
  title,
  stage,
  today,
  next,
  nextTools,
  state,
  proof,
  route,
  growth,
  headerActions,
  moreLabel,
  children,
}: LearningHomeProps) {
  return (
    <section
      className="template-learning-home learning-cards"
      data-template="LearningHome"
      data-plan-primary="true"
    >
      {today ? (
        <section className="learning-today" data-learning-section="today" aria-label={today.eyebrow}>
          {headerActions ? (
            <div className="learning-today__actions">{headerActions}</div>
          ) : null}
          <div className="learning-today__copy">
            <p className="eyebrow">{today.eyebrow}</p>
            <h2>{today.title}</h2>
            {today.detail ? <p className="learning-today__detail">{today.detail}</p> : null}
            <div className="learning-today__stats">
              <span><strong>{today.due}</strong>{today.dueLabel}</span>
              <span><strong>{today.remaining}</strong>{today.remainingLabel}</span>
            </div>
          </div>
          <div
            className="learning-today__ring"
            style={{ "--learning-progress": `${today.progress}%` } as CSSProperties}
            aria-label={`${today.done}/${today.total}`}
          >
            <span>{today.done}/{today.total}</span>
          </div>
        </section>
      ) : (
        <header className="learning-cards__header">
          <p className="eyebrow">{currentLabel}</p>
          <h2>{title}</h2>
          {stage || headerActions ? (
            <div className="learning-cards__subhead">
              {stage ? <p className="template-metadata">{stage}</p> : <span />}
              {headerActions ? (
                <div className="template-learning-home__header-actions">{headerActions}</div>
              ) : null}
            </div>
          ) : null}
        </header>
      )}
      <div className="learning-card-stack">
        <section
          className="learning-card learning-card--now"
          data-learning-section="current"
          data-learning-card-group="current"
        >
          {state ? state : <NextAction {...next} />}
          {nextTools}
        </section>
        {proof || route || growth || children ? (
          <details className="learning-focus-more" data-learning-focus-more="true">
            <summary>
              <span>{moreLabel ?? "More"}</span>
              {proof ? <span className="learning-focus-more__hint">{proof.label}</span> : null}
            </summary>
            <div className="learning-card-stack">
              {proof ? (
                <LearningCardGroup id="reviews" label={proof.label} count={proof.count}>
                  {proof.content}
                </LearningCardGroup>
              ) : null}
              {route ? (
                <LearningCardGroup id="route" label={route.label} count={route.count} collapsible>
                  {route.content}
                </LearningCardGroup>
              ) : null}
              {growth ? (
                <LearningCardGroup id="growth" label={growth.label} count={growth.count}>
                  {growth.content}
                </LearningCardGroup>
              ) : null}
              {children ? (
                <div className="learning-card-stack learning-card-stack--more">{children}</div>
              ) : null}
            </div>
          </details>
        ) : null}
      </div>
    </section>
  );
}
