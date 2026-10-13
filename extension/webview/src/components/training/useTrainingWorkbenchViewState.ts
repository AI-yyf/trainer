import { useWorkbenchState } from "../../app/useWorkbenchState";

/**
 * Selector module for TrainingWorkbenchView (props-debt round: store-driven
 * data).
 *
 * Every field this view reads that already lives in the workbench store is
 * selected here instead of being threaded through `TrainingWorkbenchViewProps`
 * — the back-to-learning relay (a pure `setActiveView` store action), the
 * remote workspace display name, and the persisted review-queue open request.
 *
 * What deliberately stays a prop: the card/handoff facts App derives under
 * source guards (grouped into `TrainingCardFacts` / `TrainingHandoffFacts`
 * descriptors), values only App can produce (the practice-response JSX,
 * primary/actions/empty-state chrome, the remote-verification controller
 * state), and callbacks closing over App-local state (status transitions,
 * file verification, hint accounting, review-queue actions).
 *
 * This module is imported only by TrainingWorkbenchView, so the selectors stay
 * in the view's lazy chunk — nothing here may be pulled into App's first
 * bundle.
 */
export interface TrainingWorkbenchViewState {
  /** Return from the focused card to the Learning home (store relay). */
  onBackToLearning: () => void;
  /** Remote companion display name for the "verify on <name>" affordance. */
  remoteName: string | undefined;
  /** Persisted request to open the follow-up review queue disclosure. */
  reviewQueueOpenRequest: boolean;
}

export function useTrainingWorkbenchViewState(): TrainingWorkbenchViewState {
  const setActiveView = useWorkbenchState((state) => state.setActiveView);
  const remoteName = useWorkbenchState((state) => state.data.workspace?.remoteName);
  const reviewQueueOpenRequest = useWorkbenchState(
    (state) => state.trainingReviewQueueRequested,
  );

  return {
    onBackToLearning: () => setActiveView("plan"),
    remoteName,
    reviewQueueOpenRequest,
  };
}
