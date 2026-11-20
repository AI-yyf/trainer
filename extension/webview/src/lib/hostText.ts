/**
 * Host text normalization.
 *
 * The webview receives its state from the host, which received it from the
 * sidecar. Those payloads are declared with precise types, but at runtime a
 * field can carry something else — a record where the view expects text, a
 * number, a blank string. The learning path reads those fields at the moment
 * a practice settles, so an unguarded `.trim()` or `.replace()` there blanks
 * the whole conversation with the error boundary instead of degrading.
 *
 * These helpers normalize the host's text fields once, at the boundary, so a
 * malformed value is dropped instead of taking the workbench down.
 */

/**
 * Coerce one host value to the string the view declares.
 *
 * @returns the trimmed text, or `undefined` when the value is not usable text.
 */
export function normalizeHostText(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

/** The training-state fields that carry free text from the host. */
export interface HostTrainingTextFields {
  latestTrainingSubmode?: string;
  latestLearningFocusArea?: string;
  latestLearningFollowup?: string;
  latestLearningVerifiedResult?: string;
  latestLearningBlocker?: string;
  latestLearningAbandonReason?: string;
  latestLearningPartialProgress?: string;
  selectedCardTitle?: string;
}

/**
 * The training state's text fields, normalized once.
 *
 * Non-text fields are carried through untouched: only the values the view
 * treats as text are coerced.
 */
export function normalizeTrainingStateTextFields<T extends HostTrainingTextFields>(
  state: T | undefined,
): T | undefined {
  if (!state) {
    return state;
  }
  return {
    ...state,
    latestTrainingSubmode: normalizeHostText(state.latestTrainingSubmode),
    latestLearningFocusArea: normalizeHostText(state.latestLearningFocusArea),
    latestLearningFollowup: normalizeHostText(state.latestLearningFollowup),
    latestLearningVerifiedResult: normalizeHostText(state.latestLearningVerifiedResult),
    latestLearningBlocker: normalizeHostText(state.latestLearningBlocker),
    latestLearningAbandonReason: normalizeHostText(state.latestLearningAbandonReason),
    latestLearningPartialProgress: normalizeHostText(state.latestLearningPartialProgress),
    selectedCardTitle: normalizeHostText(state.selectedCardTitle),
  };
}
