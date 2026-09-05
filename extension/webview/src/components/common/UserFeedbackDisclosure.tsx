import type { ComposerLanguage } from "../../lib/types";
import { resolveCopy, type CopyKey } from "../../lib/i18n/copy";

export type UserFeedbackKind =
  | "too_hard"
  | "too_simple"
  | "misunderstood"
  | "resource_incorrect"
  | "plan_mismatch"
  | "card_unrealistic";

export type UserFeedbackDisclosureProps = {
  language: ComposerLanguage;
  busy?: boolean;
  submittedKind?: UserFeedbackKind;
  error?: string;
  onSubmit: (kind: UserFeedbackKind) => void;
};

const ACTIONS: Array<{ kind: UserFeedbackKind; key: CopyKey }> = [
  { kind: "too_hard", key: "feedbackTooHard" },
  { kind: "too_simple", key: "feedbackTooSimple" },
  { kind: "misunderstood", key: "feedbackMisunderstood" },
  { kind: "resource_incorrect", key: "feedbackResourceIncorrect" },
  { kind: "plan_mismatch", key: "feedbackPlanMismatch" },
  { kind: "card_unrealistic", key: "feedbackCardUnrealistic" },
];

export function UserFeedbackDisclosure({
  language,
  busy = false,
  submittedKind,
  error,
  onSubmit,
}: UserFeedbackDisclosureProps) {
  const copy = resolveCopy(language);
  return (
    <details className="user-feedback-disclosure">
      <summary>{copy.feedbackDisclosureSummary}</summary>
      <div className="user-feedback-disclosure__body">
        <p>{copy.feedbackDisclosureDetail}</p>
        <div className="user-feedback-disclosure__actions" role="group" aria-label={copy.feedbackLearningLabel}>
          {ACTIONS.map((action) => (
            <button
              key={action.kind}
              className={`button button--ghost user-feedback-disclosure__action${submittedKind === action.kind ? " is-selected" : ""}`}
              type="button"
              disabled={busy || Boolean(submittedKind)}
              onClick={() => onSubmit(action.kind)}
            >
              {copy[action.key]}
            </button>
          ))}
        </div>
        {busy ? <span className="user-feedback-disclosure__status" role="status">{copy.feedbackRecording}</span> : null}
        {submittedKind ? (
          <span className="user-feedback-disclosure__status user-feedback-disclosure__status--success" role="status">
            {copy.feedbackRecorded}
          </span>
        ) : null}
        {error ? <span className="user-feedback-disclosure__status user-feedback-disclosure__status--error" role="alert">{error}</span> : null}
      </div>
    </details>
  );
}
