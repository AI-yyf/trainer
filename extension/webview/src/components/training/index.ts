// Focus-mode training owns exactly one live surface: the single-card
// TrainingWorkbenchView. The former multi-panel chrome (CoachTrainingView,
// welcome/motivation/rhythm/memory/card panels, tip panel) and the practice /
// flash sub-views it mounted were unreachable dead code and were removed.
export { TrainingWorkbenchView } from "./TrainingWorkbenchView";
export type { TrainingWorkbenchViewProps } from "./TrainingWorkbenchView";
export {
  applyTrainingCardGrade,
  applyTrainingCardSkip,
  interpretTrainingComposerCardCommand,
  type TrainingCardGrade,
  type TrainingComposerCardCommand,
} from "./trainingCardActions";
export type {
  TrainingReviewAction,
  TrainingReviewItem,
  TrainingCardMismatchRecovery,
} from "./TrainingWorkbenchView";
export { resolveTrainingCardMismatchRecovery } from "./TrainingWorkbenchView";
