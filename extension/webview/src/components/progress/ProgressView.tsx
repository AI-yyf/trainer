import type { TrainingSkillDimensionState, TrainingSkillProjection } from "../../lib/types";

type DimensionKey = "comprehension" | "implementation" | "debugging" | "transfer";

const DIMENSION_KEYS: DimensionKey[] = ["comprehension", "implementation", "debugging", "transfer"];

const DIMENSION_LABELS: Record<ComposerLanguage, Record<DimensionKey, string>> = {
  "zh-CN": { comprehension: "理解", implementation: "实现", debugging: "调试", transfer: "迁移" },
  "en-US": {
    comprehension: "Comprehension",
    implementation: "Implementation",
    debugging: "Debugging",
    transfer: "Transfer",
  },
};

type ComposerLanguage = "zh-CN" | "en-US";

const STATE_LABELS: Record<ComposerLanguage, Record<TrainingSkillDimensionState["state"], string>> = {
  "zh-CN": {
    not_verified: "还未验证",
    assisted: "有辅助完成",
    independent: "独立完成",
    repeat_verified: "反复验证",
    needs_review: "需要回顾",
  },
  "en-US": {
    not_verified: "Not verified yet",
    assisted: "Completed with hints",
    independent: "Independent",
    repeat_verified: "Repeatedly verified",
    needs_review: "Needs review",
  },
};

function dimensionState(
  projection: TrainingSkillProjection | undefined,
  key: DimensionKey,
): TrainingSkillDimensionState | undefined {
  return projection?.dimensions?.[key];
}

export interface ProgressViewProps {
  zh: boolean;
  projection?: TrainingSkillProjection;
  onOpenTraining: () => void;
}

/**
 * §十二: capability presentation. Calm text rows with evidence counts —
 * no score bars, no gamification. Every claim comes from the server-side
 * skill projection; empty state explains what will populate it.
 */
export function ProgressView({ zh, projection, onOpenTraining }: ProgressViewProps) {
  const language: ComposerLanguage = zh ? "zh-CN" : "en-US";
  const hasAnyEvidence = DIMENSION_KEYS.some((key) => {
    const state = dimensionState(projection, key);
    return Boolean(state && (state.verifiedCount ?? 0) > 0);
  });
  const updatedAt = projection?.updatedAt ? new Date(projection.updatedAt) : undefined;
  const updatedLabel =
    updatedAt && !Number.isNaN(updatedAt.getTime())
      ? updatedAt.toLocaleString(zh ? "zh-CN" : undefined, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "";

  return (
    <section className="progress-view" aria-label={zh ? "你的成长" : "Your progress"}>
      <header className="progress-view__header">
        <p className="eyebrow">{zh ? "你的成长" : "Your progress"}</p>
        {updatedLabel ? (
          <p className="progress-view__updated">
            {zh ? `更新于 ${updatedLabel}` : `Updated ${updatedLabel}`}
          </p>
        ) : null}
      </header>
      {hasAnyEvidence ? (
        <ul className="progress-view__dimensions">
          {DIMENSION_KEYS.map((key) => {
            const state = dimensionState(projection, key);
            const count = state?.verifiedCount ?? 0;
            return (
              <li key={key} className="progress-view__row">
                <div className="progress-view__row-main">
                  <span className="progress-view__dimension">{DIMENSION_LABELS[language][key]}</span>
                  <span className="progress-view__state">
                    {state
                      ? STATE_LABELS[language][state.state]
                      : zh
                        ? "还未验证"
                        : "Not verified yet"}
                  </span>
                </div>
                <span className="progress-view__evidence">
                  {zh
                    ? `证据 ${count} 条`
                    : `${count} ${count === 1 ? "piece" : "pieces"} of evidence`}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="progress-view__empty">
          <p>
            {zh
              ? "完成一次练习的验证后，这里会显示你在理解、实现、调试和迁移上的真实成长。"
              : "Once you verify a practice card, your real growth in comprehension, implementation, debugging, and transfer shows up here."}
          </p>
          <button className="button button--accent" type="button" onClick={onOpenTraining}>
            {zh ? "去练习" : "Start practicing"}
          </button>
        </div>
      )}
    </section>
  );
}
