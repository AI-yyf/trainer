import type * as vscode from 'vscode';

import type { SidecarHttpClient } from '../core/httpClient';
import type { SidecarProcessManager } from '../core/sidecarProcessManager';
import type { TrainerHostState } from '../core/types';
import { getRuntimeWorkspaceContext } from '../commands/workspaceContext';

/** Sidecar endpoint that records a trusted host-side training verification. */
export const TRAINING_ATTESTATION_PATH = '/training/verification/attest';

/** Evidence source the sidecar treats as host-trusted for test-runner attestations. */
export const TEST_RUNNER_EVIDENCE_SOURCE = 'test_runner';

/** Hard cap for the tests_output echo so training ledgers stay small. */
export const TEST_RUNNER_ATTESTATION_OUTPUT_LIMIT = 500;

/**
 * Narrow slice of {@link CommandContext} the attestation flow needs. The
 * TrainerTestController receives this lazily (after activation finishes wiring
 * the command context) so the controller itself stays dependency-free.
 */
export interface TrainingAttestationRuntime {
  sidecarClient: Pick<SidecarHttpClient, 'postJson'>;
  sidecarManager: Pick<SidecarProcessManager, 'ensureRunning'>;
  outputChannel: Pick<vscode.OutputChannel, 'appendLine'>;
  getHostState(): TrainerHostState;
  getSessionId(): string | undefined;
}

/** A practice card that is currently live (selected and not yet closed out). */
export interface LivePracticeCard {
  cardId: string;
  cardTitle?: string;
  focusArea?: string;
}

/** Snake_case body the sidecar `POST /training/verification/attest` expects. */
export interface TrainingVerificationAttestationBody {
  card_id: string;
  passed: boolean;
  evidence_source: typeof TEST_RUNNER_EVIDENCE_SOURCE;
  summary: string;
  tests_output: string;
  focus_area?: string;
  card_title?: string;
  session_id?: string;
  workspace_id?: string;
}

/**
 * Card statuses that mean the selected card is closed out and can no longer
 * accept verification evidence. Everything else (candidate, active,
 * implemented, completed, needs_primer, answered, blocked, ...) is still live.
 */
const CLOSED_CARD_STATUSES = new Set(['fed_back', 'archived', 'reviewed', 'skipped']);

function normalizeStatus(value: unknown): string {
  return typeof value === 'string' ? value.trim().toLowerCase().replace(/-/g, '_') : '';
}

function asOptionalText(value: unknown): string | undefined {
  if (typeof value !== 'string') {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

/**
 * Resolve the live practice card from the host bootstrap state. The host state
 * tracks the currently selected training card in
 * `bootstrap.workspaceTrainingState` (`selected_card_id` server-side); the
 * active routing view repeats it with richer card details.
 *
 * Returns undefined when no card is selected, when the selected card is
 * closed out (fed back / archived / reviewed / skipped), or when the selected
 * card is a flash card — attestation only applies to practice cards.
 */
export function resolveLivePracticeCard(hostState: TrainerHostState | undefined): LivePracticeCard | undefined {
  const trainingState = hostState?.bootstrap?.workspaceTrainingState;
  if (!trainingState) {
    return undefined;
  }

  const routing = trainingState.activeTrainingCardRouting;
  const cardId =
    asOptionalText(trainingState.selectedCardId) ??
    asOptionalText(routing?.selectedCardId) ??
    asOptionalText(routing?.selectedCard?.cardId);
  if (!cardId) {
    return undefined;
  }

  const status = normalizeStatus(trainingState.selectedCardStatus);
  if (CLOSED_CARD_STATUSES.has(status)) {
    return undefined;
  }

  if (trainingState.selectedCardType === 'flash') {
    return undefined;
  }

  return {
    cardId,
    cardTitle:
      asOptionalText(trainingState.selectedCardTitle) ?? asOptionalText(routing?.selectedCard?.title),
    focusArea:
      asOptionalText(routing?.selectedCard?.focusArea) ??
      asOptionalText(trainingState.latestLearningFocusArea),
  };
}

/** Convenience wrapper returning just the live practice card id, if any. */
export function resolveLivePracticeCardId(hostState: TrainerHostState | undefined): string | undefined {
  return resolveLivePracticeCard(hostState)?.cardId;
}

/**
 * Resolve the same workspace id the rest of the host uses for sidecar calls
 * (managed context id when admitted, else the sovereign/legacy folder scope).
 */
export function resolveAttestationWorkspaceId(hostState: TrainerHostState | undefined): string | undefined {
  if (!hostState) {
    return undefined;
  }
  return getRuntimeWorkspaceContext({ getHostState: () => hostState }).workspaceId;
}

/** Truncate the tests output echo to the attestation-friendly size. */
export function truncateTestsOutput(value: string): string {
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (normalized.length <= TEST_RUNNER_ATTESTATION_OUTPUT_LIMIT) {
    return normalized;
  }
  return `${normalized.slice(0, TEST_RUNNER_ATTESTATION_OUTPUT_LIMIT)}…`;
}

export function buildTestRunAttestationBody(input: {
  card: LivePracticeCard;
  summary: string;
  testsOutput: string;
  sessionId?: string;
  workspaceId?: string;
}): TrainingVerificationAttestationBody {
  return {
    card_id: input.card.cardId,
    passed: true,
    evidence_source: TEST_RUNNER_EVIDENCE_SOURCE,
    summary: input.summary,
    tests_output: truncateTestsOutput(input.testsOutput),
    ...(input.card.focusArea ? { focus_area: input.card.focusArea } : {}),
    ...(input.card.cardTitle ? { card_title: input.card.cardTitle } : {}),
    ...(input.sessionId ? { session_id: input.sessionId } : {}),
    ...(input.workspaceId ? { workspace_id: input.workspaceId } : {}),
  };
}

/**
 * POST the attestation to the sidecar. Throws on transport/sidecar failure —
 * callers that fire-and-forget must attach a catch (see
 * {@link dispatchTestRunAttestation}).
 */
export async function postTrainingVerificationAttestation(
  runtime: TrainingAttestationRuntime,
  body: TrainingVerificationAttestationBody,
): Promise<void> {
  const status = await runtime.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    throw new Error(status.detail ?? 'Sidecar is unavailable; training attestation not sent.');
  }
  await runtime.sidecarClient.postJson(status.port, TRAINING_ATTESTATION_PATH, body);
}

/**
 * Fire-and-forget attestation dispatch. Attestation must never break or delay
 * the test UX, so this never throws: failures are logged to the output
 * channel and swallowed.
 */
export function dispatchTestRunAttestation(
  runtime: TrainingAttestationRuntime,
  body: TrainingVerificationAttestationBody,
): Promise<void> {
  return postTrainingVerificationAttestation(runtime, body).catch((error: unknown) => {
    try {
      runtime.outputChannel.appendLine(
        `[training-attestation] failed to attest card ${body.card_id}: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    } catch {
      // The output channel can be disposed during shutdown; dropping the log
      // line is still safer than surfacing the error into the test UX.
    }
  });
}
