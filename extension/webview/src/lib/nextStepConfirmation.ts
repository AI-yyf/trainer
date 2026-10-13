/**
 * Grounding downgrade consumption (DESIGN.md §2.5/§2.6, §3 边界规则⑤).
 *
 * The server stamps `next_step_requires_confirmation` (agent_meta) /
 * `requires_confirmation` (coach_turn) when a next step references symbols
 * that are not anchored in the reply, code, history, or verified workspace
 * facts. The UI must render that downgrade as a visible "confirm before
 * acting" marker — never silently delete the step and never present it as
 * ordinary verified guidance.
 *
 * One normalization point for every carrier the webview can observe:
 * - `data.coachTurn.requiresConfirmation` (host snapshot mapping)
 * - `data.nextStepHint.requiresConfirmation` (host snapshot mapping)
 * - `stream/complete` terminal frame (`nextStepRequiresConfirmation`)
 * - per-artifact `metadata` on the next_step card (server passthrough)
 */

/**
 * Reads the confirmation marker from a raw metadata record. Accepts the
 * snake_case server keys plus the camelCase mirrors so the flag survives
 * whichever mapping hop populates it first.
 */
export function nextStepRequiresConfirmationFromMetadata(
  metadata: Record<string, unknown> | undefined,
): boolean {
  if (!metadata) {
    return false;
  }
  return (
    metadata.next_step_requires_confirmation === true ||
    metadata.nextStepRequiresConfirmation === true ||
    metadata.requires_confirmation === true ||
    metadata.requiresConfirmation === true
  );
}

/** True when any artifact of the turn carries the confirmation marker. */
export function nextStepRequiresConfirmationFromArtifacts(
  artifacts: Array<{ metadata?: Record<string, unknown> }> | undefined,
): boolean {
  if (!artifacts || artifacts.length === 0) {
    return false;
  }
  return artifacts.some((artifact) =>
    nextStepRequiresConfirmationFromMetadata(artifact.metadata),
  );
}

/**
 * Turn-level union of all carriers. The flag is per-turn state: the latest
 * assistant turn shows the marker when any of its deliveries said so.
 */
export function resolveTurnNextStepRequiresConfirmation(input: {
  coachTurnRequiresConfirmation?: boolean;
  nextStepHintRequiresConfirmation?: boolean;
  streamingCompletionRequiresConfirmation?: boolean;
  artifactRequiresConfirmation?: boolean;
}): boolean {
  return (
    input.coachTurnRequiresConfirmation === true ||
    input.nextStepHintRequiresConfirmation === true ||
    input.streamingCompletionRequiresConfirmation === true ||
    input.artifactRequiresConfirmation === true
  );
}
