import type { ReactNode } from "react";

import {
  coachOrientationTone,
  type CoachOrientationRecord,
  type CoachOrientationState,
} from "../../../../../shared/src/coachOrientationGovernance";
import { resolveCopy, type Copy } from "../../lib/i18n/copy";
import type { ComposerLanguage } from "../../lib/types";

export type OrientationRailRecord = Pick<
  CoachOrientationRecord,
  "objectLabel" | "why" | "primaryActionLabel" | "nextStep" | "advancedWhere"
> & {
  state: CoachOrientationState;
  primaryAction: string;
};

export interface CoachOrientationRailProps {
  orientation: OrientationRailRecord;
  language: ComposerLanguage;
  showAction?: boolean;
  onAction?: (action: string) => void;
  moreContent?: ReactNode;
}

function orientationStateLabel(state: CoachOrientationState, t: Copy): string {
  switch (state) {
    case "needs_setup":
      return t.orientationStateNeedsSetup;
    case "waiting":
      return t.orientationStateWaiting;
    case "working":
      return t.orientationStateWorking;
    case "blocked":
      return t.orientationStateBlocked;
    case "ready":
      return t.orientationStateReady;
    case "interrupted":
      return t.orientationStateInterrupted;
  }
}

export function CoachOrientationRail({
  orientation,
  language,
  showAction = true,
  onAction,
  moreContent,
}: CoachOrientationRailProps) {
  const t = resolveCopy(language);
  const tone = coachOrientationTone(orientation.state);
  const stateLabel = orientationStateLabel(orientation.state, t);
  const canAct =
    showAction &&
    orientation.primaryAction !== "wait" &&
    Boolean(onAction) &&
    Boolean(orientation.primaryActionLabel);
  const stateDetail = [stateLabel, orientation.why].filter(Boolean).join(" · ");
  const primaryAriaLabel = [orientation.primaryActionLabel, stateLabel, orientation.nextStep]
    .filter(Boolean)
    .join(". ");
  return (
    <div
      className={`coach-thread-strip coach-thread-strip--${tone} coach-thread-strip--orientation`}
      role="status"
      data-view-identity="true"
      aria-label={`${orientation.objectLabel}. ${stateLabel}`}
      aria-live={orientation.state === "working" || orientation.state === "waiting" ? "polite" : undefined}
    >
      <p className="coach-thread-strip__sentence">
        <strong className="coach-thread-strip__value" data-view-object="">
          {orientation.objectLabel}
        </strong>
        <span className="coach-thread-strip__state" data-view-state="">
          {stateLabel}
        </span>
        {orientation.why ? (
          <span className="coach-thread-strip__why" data-view-why="">
            {orientation.why}
          </span>
        ) : null}
        {orientation.nextStep ? (
          <span className="coach-thread-strip__next" data-view-next="">
            <span className="sr-only">{t.orientationNext}</span>
            {orientation.nextStep}
          </span>
        ) : null}
      </p>
      <div className="coach-thread-strip__action-row">
        {canAct ? (
          <button
            className="coach-thread-strip__action"
            type="button"
            data-view-primary=""
            aria-label={primaryAriaLabel}
            onClick={() => onAction?.(orientation.primaryAction)}
          >
            {orientation.primaryActionLabel}
          </button>
        ) : null}
        <details className="coach-thread-strip__advanced">
          <summary>{t.orientationMore}</summary>
          <dl className="coach-thread-strip__advanced-list">
            <div>
              <dt>{t.orientationNow}</dt>
              <dd>{orientation.objectLabel}</dd>
            </div>
            <div>
              <dt>{t.orientationState}</dt>
              <dd>{stateDetail}</dd>
            </div>
            {orientation.advancedWhere ? (
              <div>
                <dt>{t.orientationMore}</dt>
                <dd>{orientation.advancedWhere}</dd>
              </div>
            ) : null}
          </dl>
          {moreContent}
        </details>
      </div>
    </div>
  );
}
