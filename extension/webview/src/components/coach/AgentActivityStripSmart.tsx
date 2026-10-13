import { describeTrainerStopReason } from "../../../../../shared/src/protocol";
import type { AgentToolActivity } from "../../app/useWorkbenchState";
import type { ComposerLanguage } from "../../lib/types";
import { agentActivityStripCopy, TOOL_LABELS } from "../../lib/i18n/segments/agentActivityStripCopy";
import {
  hasCoachToolResultFailure,
  resolveCoachToolResultCopy,
  summarizeSafeCoachToolResult,
} from "./coachToolResultCopy";

export interface AgentActivityStripProps {
  activities: AgentToolActivity[];
  step?: number;
  language?: ComposerLanguage;
  stopReason?: string;
}

function toolLabel(name: string, language: ComposerLanguage): string {
  const labels = TOOL_LABELS[name];
  const label = labels?.[language];
  if (label) {
    return label;
  }
  return resolveCoachToolResultCopy(language).currentStep;
}

/** The en sentence lowercases the label; other locales use it verbatim. */
function sentenceLabel(label: string, language: ComposerLanguage): string {
  return language === "en-US" ? label.toLowerCase() : label;
}

function summarizeResult(
  activity: AgentToolActivity,
  language: ComposerLanguage,
): string | undefined {
  if (activity.status === "running") {
    return undefined;
  }
  const copy = resolveCoachToolResultCopy(language);
  if (activity.status === "failed" || hasCoachToolResultFailure(undefined, activity.result)) {
    return copy.needsRetry;
  }
  return summarizeSafeCoachToolResult(activity.result, language) ?? copy.completed;
}

function summarizeActivitySet(
  activities: AgentToolActivity[],
  language: ComposerLanguage,
): string {
  const running = activities.filter((activity) => activity.status === "running");
  const failed = activities.filter(
    (activity) =>
      activity.status === "failed" || hasCoachToolResultFailure(undefined, activity.result),
  );
  const succeeded = activities.filter((activity) => activity.status === "succeeded");

  if (failed.length > 0) {
    const copy = resolveCoachToolResultCopy(language);
    if (running.length > 0) {
      return agentActivityStripCopy(language, "正在核对上下文，同时有一步需要重试");
    }
    return copy.blocked;
  }

  if (running.length > 0) {
    if (running.length === 1) {
      const label = toolLabel(running[0].name, language);
      return agentActivityStripCopy(language, "正在{label}").replace(
        "{label}",
        sentenceLabel(label, language),
      );
    }

    return agentActivityStripCopy(language, "正在核对 {n} 项上下文").replace(
      "{n}",
      String(running.length),
    );
  }

  if (succeeded.length > 1) {
    return agentActivityStripCopy(language, "已完成 {n} 个步骤，正在整理回复").replace(
      "{n}",
      String(succeeded.length),
    );
  }

  if (succeeded.length === 1) {
    const label = toolLabel(succeeded[0].name, language);
    return agentActivityStripCopy(language, "已完成：{label}").replace(
      "{label}",
      sentenceLabel(label, language),
    );
  }

  return agentActivityStripCopy(language, "正在准备回复");
}

function activityPills(activities: AgentToolActivity[], language: ComposerLanguage) {
  return (
    <div className="agent-activity-strip__pills">
      {activities.map((activity) => {
        const hint = summarizeResult(activity, language);
        const title = toolLabel(activity.name, language);
        return (
          <span
            key={activity.id}
            className={`agent-activity-pill agent-activity-pill--${activity.status}`}
            title={hint ? `${title} - ${hint}` : title}
          >
            <span
              className={`agent-activity-pill__dot agent-activity-pill__dot--${activity.status}`}
              aria-hidden="true"
            />
            <span className="agent-activity-pill__label">{title}</span>
            {hint ? <span className="agent-activity-pill__hint">{hint}</span> : null}
          </span>
        );
      })}
    </div>
  );
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

function activityDetails(activities: AgentToolActivity[], language: ComposerLanguage) {
  const hasRunningItems = activities.some((item) => item.status === "running");
  return (
    <>
      {hasRunningItems ? (
        <span className="agent-activity-strip__working">
          {agentActivityStripCopy(language, "正在核对上下文...")}
        </span>
      ) : null}
      {activityPills(activities, language)}
    </>
  );
}

export function AgentActivityStrip({
  activities,
  step,
  language = "en-US",
  stopReason,
}: AgentActivityStripProps) {
  if (activities.length === 0) {
    return null;
  }

  const summary = summarizeActivitySet(activities, language);
  const displayStep =
    typeof step === "number"
      ? Math.max(1, step >= activities.length ? step : step + 1)
      : undefined;

  return (
    <div className="agent-activity-strip" role="status">
      <div className="agent-activity-strip__summary">
        {typeof displayStep === "number" ? (
          <span className="agent-activity-strip__step">
            {agentActivityStripCopy(language, "第 {n} 步").replace("{n}", String(displayStep))}
          </span>
        ) : null}
        <span className="agent-activity-strip__lead">{summary}</span>
      </div>
      <div className="agent-activity-strip__details">
        {activityDetails(activities, language)}
        {stopReasonLine(stopReason, language)}
      </div>
    </div>
  );
}
