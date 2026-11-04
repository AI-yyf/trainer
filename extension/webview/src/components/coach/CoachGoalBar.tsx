import { useEffect, useState } from "react";

import { GOAL_MODE_COPY } from "../../lib/i18n/segments/coachInlineText";
import type { ComposerLanguage } from "../../lib/types";
import { TargetIcon } from "../icons";
import { TrainerIconBase } from "../icons/TrainerIconBase";

function GoalGlyph({ kind }: { kind: "pause" | "play" | "trash" | "chevron" }) {
  return (
    <TrainerIconBase viewBox="0 0 24 24" size={14}>
      {kind === "pause" ? (
        <>
          <rect x="7" y="5" width="3.2" height="14" rx="1" />
          <rect x="13.8" y="5" width="3.2" height="14" rx="1" />
        </>
      ) : null}
      {kind === "play" ? <path d="M8 5.5v13l10-6.5z" /> : null}
      {kind === "trash" ? (
        <>
          <path d="M4 7h16" />
          <path d="M9 7V4.5h6V7" />
          <path d="m6.5 7 1 13h9l1-13" />
        </>
      ) : null}
      {kind === "chevron" ? <path d="m6 9 6 6 6-6" /> : null}
    </TrainerIconBase>
  );
}

function elapsedLabel(seconds: number, language: ComposerLanguage): string {
  switch (language) {
    case "zh-CN":
    case "ja-JP":
      return `${seconds} 秒`;
    case "ko-KR":
      return `${seconds}초`;
    default:
      return `${seconds}s`;
  }
}

export interface CoachGoalBarProps {
  language: ComposerLanguage;
  title: string;
  startedAt: number | null;
  paused: boolean;
  pausedAt: number | null;
  onPause: () => void;
  onResume: () => void;
  onClear: () => void;
}

/**
 * One in-progress goal, read as a single quiet strip above the composer.
 * Elapsed time is frozen while paused; the next turn runs as normal coaching.
 */
export function CoachGoalBar({
  language,
  title,
  startedAt,
  paused,
  pausedAt,
  onPause,
  onResume,
  onClear,
}: CoachGoalBarProps) {
  const copy = GOAL_MODE_COPY[language] ?? GOAL_MODE_COPY["en-US"];
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (paused || startedAt === null) {
      return;
    }
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [paused, startedAt]);

  const end = paused ? pausedAt ?? now : now;
  const elapsedSeconds =
    startedAt === null ? 0 : Math.max(0, Math.floor((end - startedAt) / 1000));

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
        {startedAt !== null ? (
          <span className="coach-goal-bar__elapsed" aria-hidden="true">
            {elapsedLabel(elapsedSeconds, language)}
          </span>
        ) : null}
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
            aria-label={copy.clear}
            title={copy.clear}
            onClick={onClear}
          >
            <GoalGlyph kind="trash" />
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
        </div>
      ) : null}
    </section>
  );
}
