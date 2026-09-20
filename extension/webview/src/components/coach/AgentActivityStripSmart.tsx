import { describeTrainerStopReason } from "../../../../../shared/src/protocol";
import type { AgentToolActivity } from "../../app/useWorkbenchState";
import type { ComposerLanguage } from "../../lib/types";
import {
  hasCoachToolResultFailure,
  resolveCoachToolResultCopy,
  summarizeSafeCoachToolResult,
} from "./coachToolResultCopy";
import { CollapsibleBlock } from "./CollapsibleBlock";

export interface AgentActivityStripProps {
  activities: AgentToolActivity[];
  step?: number;
  language?: ComposerLanguage;
  stopReason?: string;
  /** Keep live tool activity readable without pinning every result open. */
  collapsible?: boolean;
}

const TOOL_LABELS: Record<string, { zh: string; en: string }> = {
  search_resources: { zh: "搜索资料", en: "Search resources" },
  search: { zh: "搜索", en: "Search" },
  read_workspace_file: { zh: "读取文件", en: "Read file" },
  list_workspace_files: { zh: "浏览文件", en: "List files" },
  recall_memory: { zh: "回顾记忆", en: "Recall memory" },
  record_learning_note: { zh: "保存观察", en: "Save note" },
  inspect_plan: { zh: "查看计划", en: "Inspect plan" },
  verify_practice_current_file: { zh: "验证实战", en: "Verify practice" },
  generate_training_card: { zh: "生成训练卡", en: "Generate card" },
  generate_cards: { zh: "生成训练卡", en: "Generate cards" },
  run_diagnostics: { zh: "运行诊断", en: "Run diagnostics" },
  align_plan: { zh: "对齐计划", en: "Align plan" },
  plan_alignment: { zh: "对齐计划", en: "Align plan" },
  card_generation: { zh: "生成训练卡", en: "Card generation" },
  evaluation: { zh: "评估结果", en: "Evaluation" },
  coach_finalize: { zh: "收束回复", en: "Finalize" },
  search_learning_materials: { zh: "检索学习资料", en: "Search learning materials" },
  assess_research_evidence: { zh: "评估证据覆盖", en: "Assess evidence coverage" },
  save_formal_plan: { zh: "保存正式计划", en: "Save formal plan" },
  inspect_workspace: { zh: "理解工作区", en: "Inspect workspace" },
};

function toolLabel(name: string, language: ComposerLanguage): string {
  const entry = TOOL_LABELS[name];
  if (entry) {
    return language === "zh-CN" ? entry.zh : entry.en;
  }
  return resolveCoachToolResultCopy(language).currentStep;
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
      return language === "zh-CN"
        ? "正在核对上下文，同时有一步需要重试"
        : "Checking context while one step needs another try";
    }
    return copy.blocked;
  }

  if (running.length > 0) {
    if (running.length === 1) {
      const label = toolLabel(running[0].name, language);
      return language === "zh-CN" ? `正在${label}` : `Trainer is ${label.toLowerCase()}`;
    }

    return language === "zh-CN"
      ? `正在核对 ${running.length} 项上下文`
      : `Trainer is checking ${running.length} things`;
  }

  if (succeeded.length > 1) {
    return language === "zh-CN"
      ? `已完成 ${succeeded.length} 个步骤，正在整理回复`
      : `Trainer checked ${succeeded.length} items and is shaping the reply`;
  }

  if (succeeded.length === 1) {
    const label = toolLabel(succeeded[0].name, language);
    return language === "zh-CN" ? `已完成：${label}` : `Trainer has the key context from ${label}`;
  }

  return language === "zh-CN" ? "正在准备回复" : "Trainer is preparing a reply";
}

function activityDetailsLabel(language: ComposerLanguage, count: number): string {
  if (language === "zh-CN") {
    return `运行详情 · ${count} 个步骤`;
  }
  return `Run details · ${count} step${count === 1 ? "" : "s"}`;
}

function activityTimeline(activities: AgentToolActivity[], language: ComposerLanguage) {
  const isZh = language === "zh-CN";
  return (
    <ol className="agent-activity-strip__timeline">
      <li
        className={`agent-activity-stage ${activities.length > 0 ? "agent-activity-stage--succeeded" : "agent-activity-stage--running"}`}
      >
        <span className="agent-activity-stage__marker" aria-hidden="true" />
        <span className="agent-activity-stage__copy">
          <strong>{isZh ? "理解请求" : "Understand the request"}</strong>
          <span>
            {activities.length > 0
              ? isZh ? "已确定这一轮需要核对的内容" : "Identified what this turn needs to check"
              : isZh ? "正在梳理目标、约束与已有上下文" : "Mapping the goal, constraints, and available context"}
          </span>
        </span>
      </li>
      {activities.map((activity) => {
        const hint = summarizeResult(activity, language);
        const title = toolLabel(activity.name, language);
        return (
          <li
            key={activity.id}
            className={`agent-activity-stage agent-activity-stage--${activity.status}`}
            title={hint ? `${title} - ${hint}` : title}
          >
            <span className="agent-activity-stage__marker" aria-hidden="true" />
            <span className="agent-activity-stage__copy">
              <strong>{title}</strong>
              <span>{hint ?? (isZh ? "正在执行并等待结果" : "Running and waiting for a result")}</span>
            </span>
          </li>
        );
      })}
      {activities.length > 0 && activities.every((activity) => activity.status !== "running") ? (
        <li className="agent-activity-stage agent-activity-stage--running">
          <span className="agent-activity-stage__marker" aria-hidden="true" />
          <span className="agent-activity-stage__copy">
            <strong>{isZh ? "组织回答" : "Shape the answer"}</strong>
            <span>{isZh ? "正在把证据、结论和下一步串起来" : "Connecting evidence, conclusions, and next steps"}</span>
          </span>
        </li>
      ) : null}
    </ol>
  );
}

function stopReasonLine(stopReason: string | undefined, language: ComposerLanguage) {
  const stopReasonLabel = describeTrainerStopReason(stopReason, language);
  if (!stopReasonLabel) {
    return null;
  }
  return (
    <span className="agent-activity-strip__stop-reason">
      {language === "zh-CN" ? `结束原因：${stopReasonLabel}` : `Stopped: ${stopReasonLabel}`}
    </span>
  );
}

export function AgentActivityStrip({
  activities,
  step,
  language = "en-US",
  stopReason,
  collapsible = false,
}: AgentActivityStripProps) {
  const isZh = language === "zh-CN";
  const summary = summarizeActivitySet(activities, language);
  const hasRunningItems = activities.some((item) => item.status === "running");
  const displayStep =
    typeof step === "number"
      ? Math.max(1, step >= activities.length ? step : step + 1)
      : undefined;
  const details = (
    <>
      {hasRunningItems ? (
        <span className="agent-activity-strip__working" aria-live="polite">
          {isZh ? "正在核对上下文..." : "Checking context..."}
        </span>
      ) : null}
      {activityTimeline(activities, language)}
      {stopReasonLine(stopReason, language)}
    </>
  );

  return (
    <div className="agent-activity-strip" role="status" aria-live="polite" aria-atomic="false">
      <div className="agent-activity-strip__summary">
        <span className="agent-activity-strip__pulse" aria-hidden="true" />
        {typeof displayStep === "number" ? (
          <span className="agent-activity-strip__step">
            {isZh ? `第 ${displayStep} 步` : `Step ${displayStep}`}
          </span>
        ) : null}
        <span className="agent-activity-strip__lead">{summary}</span>
      </div>
      {collapsible ? (
        <CollapsibleBlock
          className="agent-activity-strip__details"
          summary={activityDetailsLabel(language, activities.length)}
          defaultOpen
        >
          {details}
        </CollapsibleBlock>
      ) : (
        details
      )}
    </div>
  );
}
