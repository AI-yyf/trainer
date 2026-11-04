import { describeTrainerStopReason } from "../../../../../shared/src/protocol";
import type { AgentToolActivity } from "../../app/useWorkbenchState";
import type { ComposerLanguage } from "../../lib/types";
import { agentActivityStripCopy } from "../../lib/i18n/segments/agentActivityStripCopy";
import { currentTrainerStage, trainerStageLabel } from "../../lib/trainerStage";
import {
  hasCoachToolResultFailure,
  resolveCoachToolResultCopy,
  summarizeSafeCoachToolResult,
} from "./coachToolResultCopy";

export interface AgentActivityStripProps {
  activities: AgentToolActivity[];
  /** Kept for host compatibility; the restrained strip no longer prints step numbers. */
  step?: number;
  language?: ComposerLanguage;
  stopReason?: string;
}

function stopReasonLine(stopReason: string | undefined, language: ComposerLanguage) {
  const stopReasonLabel = describeTrainerStopReason(stopReason, language);
  if (!stopReasonLabel) {
    return null;
  }
  return (
    <span className="agent-activity-strip__stop-reason">
      {agentActivityStripCopy(language, "结束原因：{reason}").replace("{reason}", stopReasonLabel)}
    </span>
  );
}

function activityNeedsRetry(activity: AgentToolActivity): boolean {
  // Tool payloads are untrusted; only the result envelope decides failure.
  // Raw transport diagnostics never reach this rail.
  return activity.status === "failed" || hasCoachToolResultFailure(undefined, activity.result);
}

function failedActivityHint(
  activity: AgentToolActivity,
  language: ComposerLanguage,
): string | undefined {
  if (!activityNeedsRetry(activity)) {
    return undefined;
  }
  const copy = resolveCoachToolResultCopy(language);
  return copy.needsRetry;
}

/** Hover-only safe detail. The visible rail stays one line. */
function stripHint(activities: AgentToolActivity[], language: ComposerLanguage): string | undefined {
  const failed = activities.find(activityNeedsRetry);
  if (failed) {
    return failedActivityHint(failed, language);
  }
  for (const activity of [...activities].reverse()) {
    if (activity.status !== "succeeded") {
      continue;
    }
    const hint = summarizeSafeCoachToolResult(activity.result, language);
    if (hint) {
      return hint;
    }
  }
  return undefined;
}

function summarizeActivitySet(
  activities: AgentToolActivity[],
  language: ComposerLanguage,
): string {
  const running = activities.filter((activity) => activity.status === "running");
  const failed = activities.filter(activityNeedsRetry);
  if (failed.length > 0 && running.length === 0) {
    return resolveCoachToolResultCopy(language).blocked;
  }
  if (failed.length > 0 && running.length > 0) {
    return agentActivityStripCopy(language, "正在核对上下文，同时有一步需要重试");
  }
  if (running.length > 0) {
    return currentTrainerStage(activities, language).label;
  }
  // Once tools have settled, the only remaining stage is shaping the answer.
  return trainerStageLabel("finalize", language);
}

/**
 * One quiet stage line above the streaming bubble.
 *
 * Progressive disclosure: live turns show only the current stage; completed
 * tool details stay in the message's work-trail disclosure after the turn.
 * Failures keep the honest retry copy without exposing transport diagnostics.
 */
export function AgentActivityStrip({
  activities,
  language = "en-US",
  stopReason,
}: AgentActivityStripProps) {
  if (activities.length === 0) {
    return null;
  }

  const summary = summarizeActivitySet(activities, language);
  const stage = currentTrainerStage(activities, language);
  const hasRunning = activities.some((activity) => activity.status === "running");
  const hasFailure = activities.some(activityNeedsRetry);
  const hint = stripHint(activities, language);

  return (
    <div
      className={`agent-activity-strip${hasFailure ? " agent-activity-strip--failed" : ""}`}
      role="status"
      data-stage={stage.kind}
      data-retry={hasFailure ? "true" : undefined}
      title={hint}
    >
      <div className="agent-activity-strip__summary">
        <span className="agent-activity-strip__lead">{summary}</span>
        {stopReasonLine(stopReason, language)}
      </div>
      {hasRunning ? <span className="agent-activity-strip__progress" aria-hidden="true" /> : null}
    </div>
  );
}
