import { useEffect, useState } from "react";

import { COACH_WORKING_LABELS } from "../../lib/i18n/segments/coachInlineText";
import type { ComposerLanguage } from "../../lib/types";
import type { TrainerStage } from "../../lib/trainerStage";

/**
 * Elapsed label borrowed from ZCode's ChatLoading: the working line carries a
 * quiet, tabular duration so a long turn never looks frozen. The timer lives
 * inside this leaf component, so the rest of the thread does not re-render
 * every second.
 */
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

export interface CoachWorkingIndicatorProps {
  language: ComposerLanguage;
  className?: string;
  /** Stable stream id: remounting the pane must not restart the clock. */
  messageId?: string;
  /** The live tool stage, e.g. searching, downloading, organizing or creating cards. */
  stage?: TrainerStage;
}

// One live turn at a time; the newest stream id prunes the rest.
const WORKING_STARTED_AT = new Map<string, number>();

export function CoachWorkingIndicator({
  language,
  className,
  messageId,
  stage,
}: CoachWorkingIndicatorProps) {
  const key = messageId?.trim() || "default";
  const [elapsedMs, setElapsedMs] = useState(0);
  const [startedAt] = useState(() => {
    const existing = WORKING_STARTED_AT.get(key);
    if (existing !== undefined) {
      return existing;
    }
    const now = performance.now();
    WORKING_STARTED_AT.set(key, now);
    return now;
  });

  useEffect(() => {
    for (const candidate of WORKING_STARTED_AT.keys()) {
      if (candidate !== key) {
        WORKING_STARTED_AT.delete(candidate);
      }
    }
    const timer = window.setInterval(() => {
      setElapsedMs(performance.now() - startedAt);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [key, startedAt]);

  const label = stage?.label ?? COACH_WORKING_LABELS[language] ?? COACH_WORKING_LABELS["en-US"];
  const seconds = Math.floor(elapsedMs / 1000);
  const stageKind = stage?.kind ?? "think";
  const classes = [
    "coach-streaming-dots",
    "coach-working",
    `coach-working--${stageKind}`,
    className,
  ].filter(Boolean).join(" ");

  return (
    <div
      className={classes}
      role="status"
      aria-live="polite"
      aria-label={label}
      data-stage={stageKind}
    >
      <span className="coach-working__label" data-text={label}>
        {label}
      </span>
      {seconds >= 1 ? (
        <span className="coach-working__elapsed" aria-hidden="true">
          {elapsedLabel(seconds, language)}
        </span>
      ) : null}
    </div>
  );
}
