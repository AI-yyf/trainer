/**
 * Training Card Renderer
 *
 * Displays training card with FSRS metrics, hint ladder, evidence submit,
 * and rating buttons following the strategy in docs/open-source-fit-and-provider-strategy.md §6.
 *
 * Key features:
 * - Single-card-first design (not a dashboard)
 * - Hint ladder with progressive reveal
 * - Evidence submit flow
 * - FSRS-based rating (Again/Hard/Good/Easy)
 * - Project handoff after completion
 */

import React, { useState, useCallback } from "react";
import type { TrainingCardPart } from "@trainer/shared";
import type { ComposerLanguage } from "../../lib/types";
import { TRAINING_LABELS } from "../../lib/i18n/segments/trainingInlineText";

export type TrainingRating = "again" | "hard" | "good" | "easy";

export interface TrainingCardRendererProps {
  part: TrainingCardPart;
  onClick?: () => void;
  onStartPractice?: () => void;
  /** @deprecated Unused. Skip/grade is fail-closed via onCardStatusTransition only. */
  onSkip?: () => void;
  onRevealHint?: (level: number) => void;
  onSubmitEvidence?: (evidence: string) => void;
  /** @deprecated Unused. Skip/grade is fail-closed via onCardStatusTransition only. */
  onRate?: (rating: TrainingRating) => void;
  /** Fail-closed: skip/grade only through hooked status transition (no bare onSkip/onRate). */
  onCardStatusTransition?: (cardId: string, newStatus: "skipped" | "reviewed", reason?: string) => void;
  language?: ComposerLanguage;
}

/**
 * Get localized label with template variable substitution
 */
function getLabel(language: ComposerLanguage, key: string, vars?: Record<string, string | number>): string {
  const langLabels = TRAINING_LABELS[language] ?? TRAINING_LABELS["en-US"];
  let label = langLabels[key] ?? TRAINING_LABELS["en-US"][key] ?? key;
  if (vars) {
    Object.entries(vars).forEach(([k, v]) => {
      label = label.replace(`{${k}}`, String(v));
    });
  }
  return label;
}

/**
 * Rating configuration with dynamic labels based on language
 */
function getRatingConfig(language: ComposerLanguage) {
  return {
    again: { icon: "A", labelKey: "ratingAgain" },
    hard: { icon: "H", labelKey: "ratingHard" },
    good: { icon: "G", labelKey: "ratingGood" },
    easy: { icon: "E", labelKey: "ratingEasy" },
  };
}

export const TrainingCardRenderer: React.FC<TrainingCardRendererProps> = ({
  part,
  onClick,
  onStartPractice,
  onRevealHint,
  onSubmitEvidence,
  onCardStatusTransition,
  language = "en-US",
}) => {
  const {
    cardId,
    cardType,
    title,
    focusArea,
    targetSkill,
    difficulty,
    status,
    whyNow,
    problemStatement,
    deliverable,
    validationMethod,
    successSignal,
    fallbackAction,
    nextAfterCompletion,
    dueAt,
    intervalDays,
    masteryScore,
    stability,
    fsrsDifficulty,
    retrievability,
    fsrsState,
    reviewSource,
    hintLadder,
    verificationSteps,
    sourceChain,
  } = part;

  // Local state for interactive flows
  const [hintsRevealed, setHintsRevealed] = useState(0);
  const [evidenceText, setEvidenceText] = useState("");
  const [showEvidenceInput, setShowEvidenceInput] = useState(false);
  const [showRating, setShowRating] = useState(false);

  // Difficulty visualization with full i18n
  const difficultyConfig = {
    easy: { label: getLabel(language, "difficultyEasy") },
    medium: { label: getLabel(language, "difficultyMedium") },
    hard: { label: getLabel(language, "difficultyHard") },
  };
  const difficultyKey = difficulty ?? "medium";
  const diffConfig = difficultyConfig[difficultyKey];

  // FSRS metrics
  const masteryPercent = masteryScore != null ? Math.round(masteryScore * 100) : null;
  const retrievabilityPercent = retrievability != null ? Math.round(retrievability * 100) : null;

  // Hint ladder handlers
  const handleRevealNextHint = useCallback(() => {
    const nextLevel = hintsRevealed + 1;
    setHintsRevealed(nextLevel);
    onRevealHint?.(nextLevel);
  }, [hintsRevealed, onRevealHint]);

  const canTransitionCardStatus = Boolean(cardId && onCardStatusTransition);

  const handleSubmitEvidence = useCallback(() => {
    if (evidenceText.trim()) {
      onSubmitEvidence?.(evidenceText.trim());
      setShowEvidenceInput(false);
      setShowRating(Boolean(cardId && onCardStatusTransition));
    }
  }, [cardId, evidenceText, onCardStatusTransition, onSubmitEvidence]);

  const handleSkip = useCallback(() => {
    if (!cardId || !onCardStatusTransition) {
      return;
    }
    onCardStatusTransition(
      cardId,
      "skipped",
      getLabel(language, "skipReason"),
    );
  }, [cardId, language, onCardStatusTransition]);

  const handleRate = useCallback((rating: TrainingRating) => {
    if (!cardId || !onCardStatusTransition) {
      return;
    }
    const reason =
      rating === "again"
        ? getLabel(language, "gradeAgainReason")
        : rating === "hard"
          ? getLabel(language, "gradeHardReason")
          : rating === "good"
            ? getLabel(language, "gradeGoodReason")
            : getLabel(language, "gradeEasyReason");
    onCardStatusTransition(cardId, "reviewed", reason);
    setShowRating(false);
  }, [cardId, language, onCardStatusTransition]);

  // Card status determines display mode
  const isActive = status === "active";
  const isRated = status === "answered" || status === "reviewed";
  const hasHintLadder = hintLadder && hintLadder.length > 0;
  const visibleHints = hasHintLadder ? hintLadder.slice(0, hintsRevealed) : [];
  const remainingHints = hasHintLadder ? hintLadder.length - hintsRevealed : 0;
  const ratingConfig = getRatingConfig(language);

  return (
    <div
      className="trainer-training-card training-card"
      data-card-id={cardId}
      data-card-type={cardType}
      data-status={status}
      onClick={!isActive && !showEvidenceInput && !showRating ? onClick : undefined}
      role={onClick && !isActive ? "button" : undefined}
      tabIndex={onClick && !isActive ? 0 : undefined}
    >
      {/* Header */}
      <div className="card-header">
        <div className="card-type-badge">
          <span className="card-type-icon">
            {cardType === "flash" ? "F" : "P"}
          </span>
          <span className="card-type-label">
            {cardType === "flash" ? getLabel(language, "cardTypeFlash") : getLabel(language, "cardTypePractice")}
          </span>
        </div>
        <div className={`card-difficulty card-difficulty--${difficultyKey}`}>
          {diffConfig.label}
        </div>
      </div>

      {/* Title and Focus */}
      {title && <div className="card-title">{title}</div>}
      {focusArea && <div className="card-focus"><strong>{getLabel(language, "focus")}:</strong> {focusArea}</div>}
      {targetSkill && <div className="card-skill"><strong>{getLabel(language, "skill")}:</strong> {targetSkill}</div>}

      {/* Why Now */}
      {whyNow && (
        <div className="card-why-now">
          <span className="why-label"><strong>{getLabel(language, "whyNow")}:</strong></span>
          <span className="why-text">{whyNow}</span>
        </div>
      )}

      {/* Problem Statement */}
      {problemStatement && (
        <div className="card-problem">
          <span className="problem-label"><strong>{getLabel(language, "problem")}:</strong></span>
          <span className="problem-text">{problemStatement}</span>
        </div>
      )}

      {/* Deliverable */}
      {deliverable && (
        <div className="card-deliverable">
          <span className="deliverable-label"><strong>{getLabel(language, "deliverable")}:</strong></span>
          <span className="deliverable-text">{deliverable}</span>
        </div>
      )}

      {/* Success Signal */}
      {successSignal && (
        <div className="card-success">
          <span className="success-label"><strong>{getLabel(language, "success")}:</strong></span>
          <span className="success-text">{successSignal}</span>
        </div>
      )}

      {/* Validation Method */}
      {validationMethod && (
        <div className="card-validation">
          <span className="validation-label"><strong>{getLabel(language, "validation")}:</strong></span>
          <span className="validation-text">{validationMethod}</span>
        </div>
      )}

      {/* Hint Ladder Section */}
      {hasHintLadder && isActive && !isRated && (
        <div className="card-hint-ladder">
          <div className="hint-ladder-header">
            <span className="hint-icon">H</span>
            <span className="hint-title">{getLabel(language, "hintLadder")}</span>
            {remainingHints > 0 && (
              <span className="hint-count">
                {getLabel(language, "hintsAvailable", { n: remainingHints, plural: remainingHints > 1 ? "s" : "" })}
              </span>
            )}
          </div>

          {/* Revealed hints */}
          {visibleHints.map((hint, idx) => (
            <div key={idx} className="hint-item revealed">
              <span className="hint-level">{idx + 1}</span>
              <span className="hint-text">{hint}</span>
            </div>
          ))}

          {/* Reveal next hint button */}
          {remainingHints > 0 && (
            <button
              className="hint-reveal-btn"
              onClick={handleRevealNextHint}
            >
              {getLabel(language, "showHint", { n: hintsRevealed + 1 })}
            </button>
          )}

          {hintsRevealed > 0 && (
            <div className="hint-used-notice">
              {getLabel(language, "usedHints", { revealed: hintsRevealed, total: hintLadder!.length })}
            </div>
          )}
        </div>
      )}

      {/* Evidence Submit Section */}
      {isActive && !isRated && (
        <div className="card-evidence-section">
          {!showEvidenceInput ? (
            <button
              className="evidence-submit-btn"
              onClick={() => setShowEvidenceInput(true)}
            >
              {getLabel(language, "submitEvidence")}
            </button>
          ) : (
            <div className="evidence-input-container">
              <textarea
                className="evidence-textarea"
                value={evidenceText}
                onChange={(e) => setEvidenceText(e.target.value)}
                placeholder={getLabel(language, "evidencePlaceholder")}
                rows={3}
              />
              <div className="evidence-actions">
                <button
                  className="evidence-cancel-btn"
                  onClick={() => {
                    setShowEvidenceInput(false);
                    setEvidenceText("");
                  }}
                >
                  {getLabel(language, "cancel")}
                </button>
                <button
                  className="evidence-confirm-btn"
                  onClick={handleSubmitEvidence}
                  disabled={!evidenceText.trim()}
                >
                  {getLabel(language, "submitAndRate")}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Rating Section */}
      {(showRating || (isActive && isRated)) && (
        <div className="card-rating-section">
          <div className="rating-header">
            <span className="rating-title">{getLabel(language, "yourPerformance")}</span>
          </div>
          <div className="rating-buttons">
            {(Object.keys(ratingConfig) as TrainingRating[]).map((rating) => {
              const config = ratingConfig[rating];
              return (
                <button
                  key={rating}
                  type="button"
                  className={`rating-btn rating-btn--${rating}`}
                  onClick={() => handleRate(rating)}
                  disabled={!canTransitionCardStatus}
                >
                  <span className="rating-icon">{config.icon}</span>
                  <span className="rating-label">{getLabel(language, config.labelKey)}</span>
                </button>
              );
            })}
          </div>
          <div className="rating-hint">
            {getLabel(language, "selectPerformanceHint")}
          </div>
        </div>
      )}

      {/* FSRS Metrics */}
      <div className="card-metrics">
        {masteryPercent !== null && (
          <div className="metric mastery">
            <span className="metric-label"><strong>{getLabel(language, "mastery")}:</strong></span>
            <div className="metric-bar">
              <div className="metric-fill" style={{ width: `${masteryPercent}%` }} />
            </div>
            <span className="metric-value">{masteryPercent}%</span>
          </div>
        )}
        {retrievabilityPercent !== null && (
          <div className="metric retrievability">
            <span className="metric-label">R:</span>
            <div className="metric-bar">
              <div
                className="metric-fill"
                style={{
                  width: `${retrievabilityPercent}%`,
                  backgroundColor: retrievabilityPercent > 50 ? "var(--success-color)" : "var(--warning-color)",
                }}
              />
            </div>
            <span className="metric-value">{retrievabilityPercent}%</span>
          </div>
        )}
        {stability != null && (
          <div className="metric stability">
            <span className="metric-label">S:</span>
            <span className="metric-value">{stability.toFixed(2)}</span>
          </div>
        )}
        {fsrsDifficulty != null && (
          <div className="metric difficulty">
            <span className="metric-label">D:</span>
            <span className="metric-value">{fsrsDifficulty.toFixed(2)}</span>
          </div>
        )}
        {fsrsState && (
          <div className="metric state">
            <span className="metric-label"><strong>{getLabel(language, "state")}:</strong></span>
            <span className="metric-value">{fsrsState}</span>
          </div>
        )}
      </div>

      {/* Due/Interval Info */}
      <div className="card-timing">
        {dueAt && <span className="timing-due"><strong>{getLabel(language, "due")}:</strong> {dueAt}</span>}
        {intervalDays != null && (
          <span className="timing-interval"><strong>{getLabel(language, "intervalDays", { n: intervalDays })}</strong></span>
        )}
        {reviewSource && <span className="timing-source"><strong>{getLabel(language, "source")}:</strong> {reviewSource}</span>}
      </div>

      {/* Verification Steps */}
      {verificationSteps && verificationSteps.length > 0 && (
        <div className="card-verification">
          <span className="verification-label"><strong>{getLabel(language, "verification")}:</strong></span>
          <ol className="verification-list">
            {verificationSteps.map((step, idx) => (
              <li key={idx}>{step}</li>
            ))}
          </ol>
        </div>
      )}

      {/* Next After Completion */}
      {nextAfterCompletion && (
        <div className="card-next">
          <span className="next-label"><strong>{getLabel(language, "nextAfterCompletion")}:</strong></span>
          <span className="next-text">{nextAfterCompletion}</span>
        </div>
      )}

      {/* Fallback Action */}
      {fallbackAction && (
        <div className="card-fallback">
          <span className="fallback-label"><strong>{getLabel(language, "ifStuck")}:</strong></span>
          <span className="fallback-text">{fallbackAction}</span>
        </div>
      )}

      {/* Source Chain */}
      {sourceChain && sourceChain.length > 0 && (
        <div className="card-source-chain">
          <span className="source-label"><strong>{getLabel(language, "sourceChain")}:</strong></span>
          <span className="source-text">{sourceChain.join(" → ")}</span>
        </div>
      )}

      {/* Action Buttons */}
      <div className="card-actions">
        {isActive && !isRated && (
          <>
            {onStartPractice && (
              <button className="card-action-btn primary" onClick={onStartPractice}>
                {getLabel(language, "startPractice")}
              </button>
            )}
            {canTransitionCardStatus ? (
              <button
                type="button"
                className="card-action-btn secondary"
                onClick={handleSkip}
                disabled={!canTransitionCardStatus}
              >
                {getLabel(language, "skip")}
              </button>
            ) : null}
          </>
        )}
        {onClick && !isActive && (
          <button className="card-action-btn secondary" onClick={onClick}>
            {getLabel(language, "viewDetails")}
          </button>
        )}
      </div>
    </div>
  );
};

export default TrainingCardRenderer;
