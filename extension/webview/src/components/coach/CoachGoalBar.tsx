import { useState } from "react";

import { GOAL_MODE_COPY } from "../../lib/i18n/segments/coachInlineText";
import type { ComposerLanguage } from "../../lib/types";
import { TargetIcon } from "../icons";
import { TrainerIconBase } from "../icons/TrainerIconBase";

function GoalGlyph({ kind }: { kind: "pause" | "play" | "archive" | "chevron" }) {
  return (
    <TrainerIconBase viewBox="0 0 24 24" size={14}>
      {kind === "pause" ? (
        <>
          <rect x="7" y="5" width="3.2" height="14" rx="1" />
          <rect x="13.8" y="5" width="3.2" height="14" rx="1" />
        </>
      ) : null}
      {kind === "play" ? <path d="M8 5.5v13l10-6.5z" /> : null}
      {kind === "archive" ? (
        <>
          <rect x="4" y="4.5" width="16" height="4.5" rx="1" />
          <path d="M5.5 9v10h13V9M10 13h4" />
        </>
      ) : null}
      {kind === "chevron" ? <path d="m6 9 6 6 6-6" /> : null}
    </TrainerIconBase>
  );
}

export interface CoachGoalBarProps {
  language: ComposerLanguage;
  title: string;
  paused: boolean;
  onPause: () => void;
  onResume: () => void;
  onArchive: () => void;
  onComplete: () => void;
}

/**
 * One in-progress goal, read as a single quiet strip above the composer.
 * The next turn runs as normal coaching; the strip keeps only title and state.
 */
export function CoachGoalBar({
  language,
  title,
  paused,
  onPause,
  onResume,
  onArchive,
  onComplete,
}: CoachGoalBarProps) {
  const copy = GOAL_MODE_COPY[language] ?? GOAL_MODE_COPY["en-US"];
  const [open, setOpen] = useState(false);

  return (
    <section
      className="coach-goal-bar"
      data-goal-bar="true"
      data-goal-paused={paused ? "true" : "false"}
    >
      <div className="coach-goal-bar__row">
        <span className="coach-goal-bar__icon" aria-hidden="true">
          <TargetIcon size={14} />
        </span>
        <span className="coach-goal-bar__eyebrow">{copy.inProgress}</span>
        <strong className="coach-goal-bar__title" title={title || copy.waiting}>
          {title || copy.waiting}
        </strong>
        {paused ? <span className="coach-goal-bar__paused">{copy.paused}</span> : null}
        <div className="coach-goal-bar__actions">
          <button
            type="button"
            className="coach-goal-bar__action"
            aria-label={paused ? copy.resume : copy.pause}
            title={paused ? copy.resume : copy.pause}
            onClick={paused ? onResume : onPause}
          >
            <GoalGlyph kind={paused ? "play" : "pause"} />
          </button>
          <button
            type="button"
            className="coach-goal-bar__action"
            aria-label={copy.archive}
            title={copy.archive}
            onClick={onArchive}
          >
            <GoalGlyph kind="archive" />
          </button>
          <button
            type="button"
            className="coach-goal-bar__action"
            aria-label={copy.expand}
            title={copy.expand}
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            <span className={open ? "coach-goal-bar__chevron is-open" : "coach-goal-bar__chevron"}>
              <GoalGlyph kind="chevron" />
            </span>
          </button>
        </div>
      </div>
      {open ? (
        <div className="coach-goal-bar__details">
          <p>{copy.hint}</p>
          <p>{copy.mastery}</p>
          <button className="button button--ghost" type="button" onClick={onComplete}>
            {copy.complete}
          </button>
        </div>
      ) : null}
    </section>
  );
}
