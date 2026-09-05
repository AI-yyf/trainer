/**
 * Common UI Components Index
 *
 * Reusable components that are shared across multiple views.
 */

export {
  HumanizedEmptyState,
  WelcomeEmptyState,
  SearchEmptyState,
  LearningEmptyState,
  SettingsEmptyState,
  ProgressiveHint,
} from "./HumanizedEmptyStates";
export { ActionButton } from "./ActionButton";

export type {
  EmptyStateProps,
  WelcomeEmptyStateProps,
  SearchEmptyStateProps,
  LearningEmptyStateProps,
  SettingsEmptyStateProps,
  ProgressiveHintProps,
} from "./HumanizedEmptyStates";
export type { ActionButtonProps } from "./ActionButton";

export {
  QuickActionsPanel,
  SearchQuickAction,
  FloatingActionButton,
  getCoachQuickActions,
} from "./QuickActions";

export type {
  QuickActionItem,
  QuickActionsPanelProps,
  SearchQuickActionProps,
  FloatingActionButtonProps,
} from "./QuickActions";

export {
  getContextualGuidance,
  getKeyboardShortcuts,
  getMotivationalMessage,
  getEncouragementMessage,
  formatRelativeTime,
} from "../coach/CoachGuidance";

export type {
  CoachGuidanceConfig,
  GuidanceItem,
  KeyboardShortcutItem,
} from "../coach/CoachGuidance";
