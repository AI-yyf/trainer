import type { CoachActionType } from "./protocol";

export type SuggestedActionGovernanceView = "coach" | "plan" | "practice";
export type SuggestedActionGovernanceTrainingSubmode = "practice" | "review";

export interface SuggestedActionGovernanceInput {
  action: CoachActionType;
  prompt?: string;
}

export interface SuggestedActionGovernanceResult {
  activeView: SuggestedActionGovernanceView;
  trainingSubmode?: SuggestedActionGovernanceTrainingSubmode;
  composerDraft?: string;
}

function normalizePrompt(prompt: string | undefined): string | undefined {
  const normalized = prompt?.trim();
  return normalized ? normalized : undefined;
}

export function resolveSuggestedActionGovernance(
  action: SuggestedActionGovernanceInput,
): SuggestedActionGovernanceResult {
  const composerDraft = normalizePrompt(action.prompt);

  if (action.action === "plan") {
    return {
      activeView: "plan",
    };
  }

  if (action.action === "review" || action.action === "retry_review") {
    return {
      activeView: "practice",
      trainingSubmode: "review",
      composerDraft,
    };
  }

  if (action.action === "next_task" || action.action === "task") {
    return {
      activeView: "practice",
      trainingSubmode: "practice",
      composerDraft,
    };
  }

  return {
    activeView: "coach",
    composerDraft,
  };
}
