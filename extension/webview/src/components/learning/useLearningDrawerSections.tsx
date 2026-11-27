import type { ReactNode } from "react";

import { sanitizeErrorSurfaceText } from "../../../../../shared/src/errorSurfaceSanitizer";
import type { TrainerOperationMessage } from "../../../../../shared/src/protocol";
import { GOAL_MODE_COPY } from "../../lib/i18n/segments/coachInlineText";
import { isSameLearningFact,type LearningProgressAchievement,type LearningSummary } from "../../lib/learningSummary";
import { operationStatusMessageText,type OperationMessageSurface } from "../../lib/operationMessageGovernance";
import type { ComposerLanguage } from "../../lib/types";
import { SystemState } from "../../templates/SystemState";
import { templateCopy } from "../../templates/templateCopy";

/**
 * The learning drawer's three sections, assembled outside App.
 *
 * App only wires the workbench; the drawer content (which fact belongs to
 * which card, which notice belongs to which section, which action is allowed)
 * lives here so the shell file keeps shrinking instead of growing.
 */

export interface LearningDrawerGoalControls {
  /** True when an explicit goal (Goal mode) is active or being typed. */
  active: boolean;
  paused: boolean;
  onPause: () => void;
  onResume: () => void;
  onClear: () => void;
}

export interface LearningDrawerReviewItem {
  title?: string;
  focusArea?: string;
  taskHint?: string;
}

export interface LearningDrawerSectionsInput {
  language: ComposerLanguage;
  summary: LearningSummary;
  /** The primary action title already displayed inside Card 1 ("当前目标"). */
  goalActionTitle?: string;
  /** The governed plan card: the goal's own reading surface. */
  planDetail: ReactNode;
  operationMessage?: TrainerOperationMessage;
  operationMessageSurface: OperationMessageSurface;
  goal: LearningDrawerGoalControls;
  reviewItems: LearningDrawerReviewItem[];
  /** The governed review-queue start (recorded by the host). */
  onReviewQueueStart: (payload: {
    concept: string;
    action: "start";
    focusArea?: string;
    taskHint?: string;
  }) => void;
  /** Opens the drawer on the practice section (the queue's decisions live there). */
  onOpenReviewQueue: () => void;
}

export interface LearningDrawerSections {
  goal: {
    detail: ReactNode;
    notice?: ReactNode;
    controls?: ReactNode;
  };
  practice: {
    dueCount: number;
    cardTitle?: string;
    notice?: ReactNode;
    actionLabel?: string;
    onAction?: () => void;
  };
  progress: {
    rows: LearningSummary["progressRows"];
    evidenceCount: number;
    achievement?: LearningProgressAchievement;
  };
}

function sectionNotice(
  message: TrainerOperationMessage | undefined,
  surface: OperationMessageSurface,
  wanted: OperationMessageSurface,
  language: ComposerLanguage,
): ReactNode {
  if (!message || surface !== wanted) {
    return undefined;
  }
  return (
    <div className="learning-drawer__notice">
      <SystemState
        kind={message.tone === "error" ? "recoverable-error" : message.tone === "success" ? "success" : "information"}
        title={sanitizeErrorSurfaceText(operationStatusMessageText(message, language), language)}
      />
    </div>
  );
}

/** Assemble the drawer's three cards from the live facts. */
export function useLearningDrawerSections(input: LearningDrawerSectionsInput): LearningDrawerSections {
  const { language, summary } = input;
  const goalCopy = GOAL_MODE_COPY[language] ?? GOAL_MODE_COPY["en-US"];
  // The plan's current step and the current practice card are frequently the
  // same card. The drawer says it once: the goal card names the step, so the
  // practice card drops the title — and with it the action that would start
  // the very same card.
  const practiceAddsSomething = Boolean(summary.dueCardTitle) &&
    !isSameLearningFact(summary.dueCardTitle, summary.goalStep) &&
    !isSameLearningFact(summary.dueCardTitle, input.goalActionTitle);

  const goalControls = input.goal.active ? (
    <>
      <button
        type="button"
        className="button button--ghost button--compact"
        data-goal-control={input.goal.paused ? "resume" : "pause"}
        onClick={() => {
          if (input.goal.paused) {
            input.goal.onResume();
            return;
          }
          input.goal.onPause();
        }}
      >
        {input.goal.paused ? goalCopy.resume : goalCopy.pause}
      </button>
      <button
        type="button"
        className="button button--ghost button--compact"
        data-goal-control="clear"
        onClick={() => {
          input.goal.onClear();
        }}
      >
        {goalCopy.exit}
      </button>
    </>
  ) : undefined;

  return {
    goal: {
      detail: input.planDetail,
      notice: sectionNotice(input.operationMessage, input.operationMessageSurface, "plan", language),
      controls: goalControls,
    },
    practice: {
      dueCount: summary.dueCount,
      cardTitle: practiceAddsSomething ? summary.dueCardTitle : undefined,
      notice: sectionNotice(input.operationMessage, input.operationMessageSurface, "training", language),
      actionLabel: summary.dueCount || practiceAddsSomething
        ? templateCopy[language].startReview
        : undefined,
      onAction: () => {
        // The same governed start the plan card used to own: the host records
        // it, then the learner lands in the drawer's practice section where the
        // decisions live.
        const first = input.reviewItems[0];
        input.onReviewQueueStart({
          concept: first?.title ?? "",
          action: "start",
          focusArea: first?.focusArea,
          taskHint: first?.taskHint,
        });
        input.onOpenReviewQueue();
      },
    },
    progress: {
      rows: summary.progressRows,
      evidenceCount: summary.evidenceCount,
      achievement: summary.latestAchievement,
    },
  };
}
