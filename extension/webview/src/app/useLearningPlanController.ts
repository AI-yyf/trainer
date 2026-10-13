import { useState } from "react";

/**
 * Learning-plan composer controller (DESIGN.md §3, round 3).
 *
 * Owns the plan-composer interaction state: the composer mode, the coach-side
 * plan context (evidence / generate / blocker prompts routed from the plan
 * view into the composer) and a pending draft replacement awaiting the
 * learner's confirmation. Plan facts themselves stay in the store.
 */

export type PlanComposerMode = "explain" | "generate" | "evidence" | "blocker";

export interface PlanComposerDraftReplacement {
  source: "stage" | "project-subplan";
  targetTitle: string;
}

export function useLearningPlanController() {
  const [planComposerMode, setPlanComposerMode] = useState<PlanComposerMode>("explain");
  const [coachPlanContext, setCoachPlanContext] = useState<PlanComposerMode>();
  const [pendingPlanComposerDraftReplacement, setPendingPlanComposerDraftReplacement] =
    useState<PlanComposerDraftReplacement>();

  return {
    planComposerMode,
    setPlanComposerMode,
    coachPlanContext,
    setCoachPlanContext,
    pendingPlanComposerDraftReplacement,
    setPendingPlanComposerDraftReplacement,
  };
}
