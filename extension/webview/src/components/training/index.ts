// Focus-mode training owns exactly one live surface: the single-card
// TrainingWorkbenchView. The former multi-panel chrome (CoachTrainingView,
// welcome/motivation/rhythm/memory/card panels, tip panel) and the practice /
// flash sub-views it mounted were unreachable dead code and were removed.
export {
  applyTrainingCardGrade,
  applyTrainingCardSkip,
  interpretTrainingComposerCardCommand,
  type TrainingCardGrade,
  type TrainingComposerCardCommand
} from "../../lib/i18n/segments/trainingCardActions";
export { TrainingWorkbenchView,resolveTrainingCardMismatchRecovery } from "./TrainingWorkbenchView";
export type {
  TrainingCardMismatchRecovery,TrainingReviewAction,
  TrainingReviewItem,TrainingWorkbenchViewProps
} from "./TrainingWorkbenchView";
