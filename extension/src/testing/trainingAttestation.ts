import type * as vscode from 'vscode';

import { sanitizeErrorSurfaceText } from '../../../shared/src/errorSurfaceSanitizer';

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
 * Marker the webview maps to a training-scoped "verified but evidence
 * undelivered, verify again" notice (same protocol as the plan-revision
 * conflict marker). The host never ships localized prose for it — the webview
 * owns the eight-language copy and the surface scoping.
 */
export const ATTESTATION_UNDELIVERED_MARKER = '[[trainer-attestation-undelivered]]';

/** Whether a verification result reached the training ledger. */
export type AttestationDeliveryOutcome = 'delivered' | 'undelivered';

/**
 * `not_arrived`: the request provably never reached the sidecar (pre-send
 * readiness guard, connect/DNS-class transport error) — a resend cannot
 * double-record and is attempted once. `ambiguous`: timeout, lost response,
 * HTTP-level failure — the outcome is unknown, so no automatic resend.
 */
export type AttestationDeliveryFailureKind = 'not_arrived' | 'ambiguous';

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
  /**
   * Invoked when evidence could not be delivered after failure classification
   * and the single connect-class retry. Implementations post the
   * training-scoped undelivered notice ({@link ATTESTATION_UNDELIVERED_MARKER});
   * the webview localizes and scopes it.
   */
  notifyAttestationUndelivered?: () => void;
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
  /**
   * Stable per-run key (see {@link attestationIdempotencyKey}). The sidecar's
   * training-reliability ledger replays a completed save with the same key, so
   * a transport-loss resend or a manual retry never double-records evidence.
   */
  idempotency_key?: string;
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
  /** Host-trusted outcome; defaults to true for successful test runs. */
  passed?: boolean;
  sessionId?: string;
  workspaceId?: string;
  /** Stable per-run key for replay-safe delivery retries. */
  idempotencyKey?: string;
}): TrainingVerificationAttestationBody {
  return {
    card_id: input.card.cardId,
    passed: input.passed ?? true,
    evidence_source: TEST_RUNNER_EVIDENCE_SOURCE,
    summary: input.summary,
    tests_output: truncateTestsOutput(input.testsOutput),
    ...(input.card.focusArea ? { focus_area: input.card.focusArea } : {}),
    ...(input.card.cardTitle ? { card_title: input.card.cardTitle } : {}),
    ...(input.sessionId ? { session_id: input.sessionId } : {}),
    ...(input.workspaceId ? { workspace_id: input.workspaceId } : {}),
    ...(input.idempotencyKey ? { idempotency_key: input.idempotencyKey } : {}),
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
    throw new AttestationNotArrivedError(
      status.detail ?? 'Sidecar is unavailable; training attestation not sent.',
    );
  }
  // ensureRunning can finish after the learner changes scope or selects another card.
  if ((body.workspace_id && body.workspace_id !== resolveAttestationWorkspaceId(runtime.getHostState())) ||
      (body.session_id && body.session_id !== runtime.getSessionId()) ||
      (resolveLivePracticeCardId(runtime.getHostState()) && body.card_id !== resolveLivePracticeCardId(runtime.getHostState()))) {
    throw new Error('Attestation scope changed before delivery; no evidence was sent.');
  }
  await runtime.sidecarClient.postJson(status.port, TRAINING_ATTESTATION_PATH, body);
}

/**
 * Stable idempotency key for one verification run against one card. Retrying
 * the delivery of the same run reuses the key, so the sidecar's reliability
 * ledger replays instead of double-recording host-trusted evidence; a genuinely
 * new run gets a fresh run id and records normally.
 */
export function attestationIdempotencyKey(input: { cardId: string; runId: string }): string {
  const cardId = input.cardId.trim();
  const runId = input.runId.trim();
  if (!cardId || !runId) {
    return '';
  }
  return `remote-verify:${runId}:${cardId}`;
}

/**
 * Thrown by the pre-send readiness guard before any bytes are written: the
 * attestation provably never reached the sidecar, so a resend cannot
 * double-record and classifies as {@link AttestationDeliveryFailureKind}'s
 * `not_arrived` regardless of the status detail text.
 */
export class AttestationNotArrivedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AttestationNotArrivedError';
  }
}

const CONNECT_ERROR_CODES: ReadonlySet<string> = new Set([
  'ECONNREFUSED',
  'EHOSTUNREACH',
  'ENETUNREACH',
  'ENOTFOUND',
  'EAI_AGAIN',
]);

function errorCodeOf(error: unknown): string | undefined {
  if (!error || typeof error !== 'object' || !('code' in error)) {
    return undefined;
  }
  const code = (error as { code?: unknown }).code;
  return typeof code === 'string' ? code : undefined;
}

/**
 * Classify a delivery failure. Only provably-not-arrived failures (the typed
 * pre-send readiness guard, connect/DNS-class transport errors) qualify for
 * the single automatic resend; everything else stays ambiguous and is
 * surfaced instead.
 */
export function classifyAttestationDeliveryFailure(error: unknown): AttestationDeliveryFailureKind {
  if (error instanceof AttestationNotArrivedError) {
    return 'not_arrived';
  }
  const code = errorCodeOf(error);
  if (code && CONNECT_ERROR_CODES.has(code)) {
    return 'not_arrived';
  }
  return 'ambiguous';
}

function logAttestationFailure(
  runtime: TrainingAttestationRuntime,
  body: TrainingVerificationAttestationBody,
  error: unknown,
  kind: AttestationDeliveryFailureKind,
  retryFailed: boolean,
): void {
  try {
    // Secret-shaped fragments are redacted by the shared error-surface
    // sanitizer; the classified rendition keeps the log diagnosable without
    // leaking raw provider prose into the output channel.
    runtime.outputChannel.appendLine(
      `[training-attestation] failed to attest card ${body.card_id} (${kind}${retryFailed ? ', after retry' : ''}): ${sanitizeErrorSurfaceText(error)}`,
    );
  } catch {
    // The output channel can be disposed during shutdown; dropping the log
    // line is still safer than surfacing the error into the test UX.
  }
}

/**
 * Fire-and-forget attestation dispatch. Attestation must never break or delay
 * the test UX, so this never throws. A `not_arrived` failure is retried once
 * after re-establishing the sidecar (the body's idempotency key makes the
 * resend replay-safe); an `ambiguous` failure is not resent — instead the
 * caller's {@link TrainingAttestationRuntime.notifyAttestationUndelivered}
 * surfaces the training-scoped "verify again to record it" notice.
 */
export async function dispatchTestRunAttestation(
  runtime: TrainingAttestationRuntime,
  body: TrainingVerificationAttestationBody,
): Promise<AttestationDeliveryOutcome> {
  try {
    await postTrainingVerificationAttestation(runtime, body);
    return 'delivered';
  } catch (error: unknown) {
    const kind = classifyAttestationDeliveryFailure(error);
    logAttestationFailure(runtime, body, error, kind, false);
    if (kind !== 'not_arrived') {
      runtime.notifyAttestationUndelivered?.();
      return 'undelivered';
    }
    try {
      await postTrainingVerificationAttestation(runtime, body);
      return 'delivered';
    } catch (retryError: unknown) {
      logAttestationFailure(
        runtime,
        body,
        retryError,
        classifyAttestationDeliveryFailure(retryError),
        true,
      );
      runtime.notifyAttestationUndelivered?.();
      return 'undelivered';
    }
  }
}
