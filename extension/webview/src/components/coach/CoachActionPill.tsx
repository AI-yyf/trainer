import type { CoachActivity, ComposerLanguage } from "../../lib/types";
import {
  SearchIcon,
  PlanIcon,
  TrainingIcon,
  ResourcesIcon,
  InsightIcon,
  ComposeIcon,
} from "../icons";

interface CoachActionPillProps {
  activity: CoachActivity;
  language?: ComposerLanguage;
}

function kindIcon(kind: CoachActivity["kind"], size = 12) {
  const iconProps = { size, strokeWidth: 1.8 };
  switch (kind) {
    case "checking_resources":
    case "search_resources":
    case "search":
      return <SearchIcon {...iconProps} />;
    case "aligning_plan":
    case "align_plan":
    case "plan_alignment":
      return <PlanIcon {...iconProps} />;
    case "scheduling_training":
    case "card_generation":
    case "generate_cards":
    case "generating_card":
      return <TrainingIcon {...iconProps} />;
    case "reviewing_evidence":
    case "resource_upload":
      return <ResourcesIcon {...iconProps} />;
    case "evaluating_result":
    case "evaluation":
    case "evaluate":
      return <InsightIcon {...iconProps} />;
    case "workspace_classification":
    default:
      return <ComposeIcon {...iconProps} />;
  }
}

export function CoachActionPill({ activity, language = "en-US" }: CoachActionPillProps) {
  const isZh = language === "zh-CN";
  const isActive = activity.status === "active";
  const isCompleted = activity.status === "completed";
  const isFailed = activity.status === "failed";

  const dotClass = isActive
    ? "coach-action-pill__dot coach-action-pill__dot--pulse"
    : isCompleted
      ? "coach-action-pill__dot coach-action-pill__dot--completed"
      : isFailed
        ? "coach-action-pill__dot coach-action-pill__dot--failed"
        : "coach-action-pill__dot";

  return (
    <span
      className={`coach-action-pill coach-action-pill--${activity.status}`}
      title={activity.detail || activity.label}
    >
      <span className="coach-action-pill__icon" aria-hidden="true">
        {kindIcon(activity.kind)}
      </span>
      <span className={dotClass} aria-hidden="true" />
      <span className="coach-action-pill__label">{activity.label}</span>
      {isCompleted && (
        <span className="coach-action-pill__check" aria-hidden="true">
          {isZh ? "完成" : "Done"}
        </span>
      )}
      {isFailed && (
        <span className="coach-action-pill__err" aria-hidden="true">
          {isZh ? "失败" : "Failed"}
        </span>
      )}
    </span>
  );
}
