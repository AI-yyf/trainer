/**
 * TrainingCardPanel Component
 *
 * A single-card training interface that follows the teaching-first principles:
 * 1. Show why this card is relevant now
 * 2. Prompt learner to attempt first (retrieval practice)
 * 3. Provide progressive hints if stuck
 * 4. Collect evidence of understanding
 * 5. Update mastery and schedule next review
 *
 * This is the core of the Trainer training experience.
 *
 * Reference: docs/open-source-fit-and-provider-strategy.md §6.3-§6.8
 */

import React, { useState, useCallback } from "react";
import {
  LightBulbIcon,
  EyeIcon,
  CheckIcon,
  ArrowRightIcon,
  SparklesIcon,
  TrophyIcon,
} from "../icons";
import { CollapseSection } from "../common/CollapseSection";

export type CardType = "recall" | "explain" | "predict" | "drill" | "debug" | "transfer" | "review";
export type CardState = "idle" | "presenting" | "attempting" | "hinting" | "evidencing" | "feedback" | "rating" | "done";
export type CardRating = "again" | "hard" | "good" | "easy";

export interface TrainingCardData {
  id: string;
  type: CardType;
  title: string;
  /** Why this card is relevant now */
  whyNow: string;
  /** What learner should do */
  learnerAction: string;
  /** Hint levels (progressive disclosure) */
  hints: Array<{
    level: number;
    content: string;
    type: "minimal" | "structural" | "example" | "answer";
  }>;
  /** Expected evidence format */
  evidencePrompt: string;
  /** Pass criteria */
  passCriteria: string[];
  /** Concept tags */
  concepts: string[];
  /** Difficulty level */
  difficulty: "easy" | "medium" | "hard";
  /** Related project context */
  projectContext?: string;
}

export interface TrainingCardPanelProps {
  /** Current language */
  language: "zh-CN" | "en-US";
  /** The training card to display */
  card: TrainingCardData;
  /** Current card state */
  state: CardState;
  /** Current hint level shown (0 = none, 1 = minimal, 2 = structural, 3 = example) */
  currentHintLevel: number;
  /** Learner's evidence submission */
  evidenceDraft: string;
  /** Rating (if state is 'rating') */
  rating?: CardRating;
  /** User's name for personalization */
  learnerName?: string;
  /** Callback when learner wants next hint */
  onRequestHint?: (level: number) => void;
  /** Callback when evidence draft changes */
  onEvidenceChange?: (text: string) => void;
  /** Callback when learner submits evidence */
  onSubmitEvidence?: () => void;
  /** @deprecated Unused. Skip/grade is fail-closed via onCardStatusTransition only. */
  onRate?: (rating: CardRating) => void;
  /** Callback when learner requests next card */
  onNextCard?: () => void;
  /** @deprecated Unused. Skip/grade is fail-closed via onCardStatusTransition only. */
  onSkip?: () => void;
  /** Fail-closed: skip/grade only through hooked status transition (no bare onSkip/onRate). */
  onCardStatusTransition?: (cardId: string, newStatus: "skipped" | "reviewed", reason?: string) => void;
}

/**
 * Get card type metadata
 */
function getCardTypeInfo(
  type: CardType,
  language: "zh-CN" | "en-US"
): { label: string; icon: string; description: string } {
  const info: Record<CardType, { label: string; icon: string; description: string }> = {
    recall: {
      label: language === "zh-CN" ? "回忆" : "Recall",
      icon: "R",
      description: language === "zh-CN"
        ? "主动回忆，不要先看答案"
        : "Recall first, don't peek at the answer",
    },
    explain: {
      label: language === "zh-CN" ? "解释" : "Explain",
      icon: "E",
      description: language === "zh-CN"
        ? "解释原因和机制"
        : "Explain the why and how",
    },
    predict: {
      label: language === "zh-CN" ? "预测" : "Predict",
      icon: "P",
      description: language === "zh-CN"
        ? "预测输出/bug/测试结果"
        : "Predict output/bug/test result",
    },
    drill: {
      label: language === "zh-CN" ? "练习" : "Drill",
      icon: "D",
      description: language === "zh-CN"
        ? "做一个最小实现"
        : "Create a minimal implementation",
    },
    debug: {
      label: language === "zh-CN" ? "调试" : "Debug",
      icon: "B",
      description: language === "zh-CN"
        ? "提出假设并验证"
        : "Form hypotheses and verify",
    },
    transfer: {
      label: language === "zh-CN" ? "迁移" : "Transfer",
      icon: "T",
      description: language === "zh-CN"
        ? "把概念用到项目里"
        : "Apply concept to your project",
    },
    review: {
      label: language === "zh-CN" ? "复习" : "Review",
      icon: "V",
      description: language === "zh-CN"
        ? "间隔重复，自评难度"
        : "Spaced repetition, self-rate difficulty",
    },
  };
  return info[type];
}

/**
 * Get difficulty label
 */
function getDifficultyInfo(
  difficulty: "easy" | "medium" | "hard",
  language: "zh-CN" | "en-US"
): { label: string } {
  const info: Record<"easy" | "medium" | "hard", { label: string }> = {
    easy: {
      label: language === "zh-CN" ? "简单" : "Easy",
    },
    medium: {
      label: language === "zh-CN" ? "中等" : "Medium",
    },
    hard: {
      label: language === "zh-CN" ? "困难" : "Hard",
    },
  };
  return info[difficulty];
}

/**
 * Get hint type label
 */
function getHintTypeInfo(
  type: TrainingCardData["hints"][0]["type"],
  language: "zh-CN" | "en-US"
): { label: string } {
  const info: Record<TrainingCardData["hints"][0]["type"], { label: string }> = {
    minimal: {
      label: language === "zh-CN" ? "最小提示" : "Minimal",
    },
    structural: {
      label: language === "zh-CN" ? "结构提示" : "Structural",
    },
    example: {
      label: language === "zh-CN" ? "示例" : "Example",
    },
    answer: {
      label: language === "zh-CN" ? "答案" : "Answer",
    },
  };
  return info[type];
}

export const TrainingCardPanel: React.FC<TrainingCardPanelProps> = ({
  language,
  card,
  state,
  currentHintLevel,
  evidenceDraft,
  rating,
  learnerName,
  onRequestHint,
  onEvidenceChange,
  onSubmitEvidence,
  onNextCard,
  onCardStatusTransition,
}) => {
  const typeInfo = getCardTypeInfo(card.type, language);
  const difficultyInfo = getDifficultyInfo(card.difficulty, language);
  const currentHint = card.hints[currentHintLevel - 1];
  const hintInfo = currentHint ? getHintTypeInfo(currentHint.type, language) : null;

  const [showHints, setShowHints] = useState(false);

  // State-based rendering
  const isAttempting = state === "attempting" || state === "hinting";
  const isEvidencing = state === "evidencing";
  const isRating = state === "rating";
  const isDone = state === "done";

  // Labels
  const whyNowLabel = language === "zh-CN" ? "为什么现在练" : "Why Now";
  const yourTaskLabel = language === "zh-CN" ? "你的任务" : "Your Task";
  const hintLabel = language === "zh-CN" ? "提示" : "Hint";
  const needHintLabel = language === "zh-CN" ? "需要提示" : "Need a hint?";
  const submitEvidenceLabel = language === "zh-CN" ? "提交答案" : "Submit Answer";
  const rateYourselfLabel = language === "zh-CN" ? "给自己评分" : "Rate Yourself";
  const againLabel = language === "zh-CN" ? "再来一次" : "Again";
  const hardLabel = language === "zh-CN" ? "有点难" : "Hard";
  const goodLabel = language === "zh-CN" ? "不错" : "Good";
  const easyLabel = language === "zh-CN" ? "太简单了" : "Easy";
  const nextCardLabel = language === "zh-CN" ? "下一张" : "Next Card";
  const skipLabel = language === "zh-CN" ? "跳过" : "Skip";
  const passCriteriaLabel = language === "zh-CN" ? "通过标准" : "Pass Criteria";
  const conceptsLabel = language === "zh-CN" ? "相关概念" : "Concepts";
  const canTransitionCardStatus = Boolean(card.id && onCardStatusTransition);

  const handleSkip = () => {
    if (!canTransitionCardStatus || !onCardStatusTransition) {
      return;
    }
    onCardStatusTransition(
      card.id,
      "skipped",
      language === "zh-CN" ? "学员跳过" : "Learner skipped",
    );
  };

  const handleRate = (nextRating: CardRating) => {
    if (!canTransitionCardStatus || !onCardStatusTransition) {
      return;
    }
    const reason =
      nextRating === "again"
        ? language === "zh-CN"
          ? "自评：再来一次"
          : "Self-grade: again"
        : nextRating === "hard"
          ? language === "zh-CN"
            ? "自评：有点难"
            : "Self-grade: hard"
          : nextRating === "good"
            ? language === "zh-CN"
              ? "自评：不错"
              : "Self-grade: good"
            : language === "zh-CN"
              ? "自评：太简单了"
              : "Self-grade: easy";
    onCardStatusTransition(card.id, "reviewed", reason);
  };

  // Greeting based on state
  const getGreeting = () => {
    if (isAttempting) {
      return language === "zh-CN" ? "先作答" : "Answer first";
    }
    if (isEvidencing) {
      return learnerName
        ? `${learnerName}, ${language === "zh-CN" ? "提交答案" : "Submit your answer"}`
        : language === "zh-CN"
          ? "提交答案"
          : "Submit your answer";
    }
    if (isRating) {
      return language === "zh-CN" ? "选择结果" : "Choose result";
    }
    if (isDone) {
      return language === "zh-CN" ? "已记录" : "Recorded";
    }
    return learnerName
      ? `${learnerName}, ${language === "zh-CN" ? "开始本卡" : "start this card"}`
      : language === "zh-CN"
        ? "开始本卡"
        : "Start this card";
  };

  return (
    <div className="training-card-panel training-card">
      {/* Card header */}
      <div className="card-header">
        <div className={`card-type card-type--${card.type}`}>
          <span className="type-icon">{typeInfo.icon}</span>
          <span className="type-label">{typeInfo.label}</span>
        </div>
        <div className={`card-difficulty card-difficulty--${card.difficulty}`}>
          {difficultyInfo.label}
        </div>
      </div>

      {/* Card title */}
      <div className="card-title">{card.title}</div>

      {/* Why now */}
      <div className="card-section card-why">
        <div className="section-label">
          <LightBulbIcon size={14} />
          <span>{whyNowLabel}</span>
        </div>
        <div className="section-content">{card.whyNow}</div>
      </div>

      {/* Your task (collapsible after attempting) */}
      {!isAttempting && !isEvidencing && !isRating && !isDone && (
        <div className="card-section card-task">
          <div className="section-label">
            <SparklesIcon size={14} />
            <span>{yourTaskLabel}</span>
          </div>
          <div className="section-content">{card.learnerAction}</div>
        </div>
      )}

      {/* Hints section */}
      {isAttempting && (
        <div className="card-section card-hints">
          {!showHints ? (
            <button
              className="hint-trigger"
              onClick={() => setShowHints(true)}
              type="button"
            >
              <EyeIcon size={14} />
              <span>{needHintLabel}</span>
            </button>
          ) : (
            <>
              {card.hints.slice(0, currentHintLevel).map((hint, index) => {
                const thisHintInfo = getHintTypeInfo(hint.type, language);
                return (
                  <div
                    key={index}
                    className={`hint-item hint-item--${hint.type}`}
                  >
                    <div className="hint-header">
                      <span
                        className={`hint-type hint-type--${hint.type}`}
                      >
                        {thisHintInfo.label}
                      </span>
                      {index === currentHintLevel - 1 && (
                        <span className="hint-current">({language === "zh-CN" ? "当前" : "current"})</span>
                      )}
                    </div>
                    <div className="hint-content">{hint.content}</div>
                  </div>
                );
              })}
              {currentHintLevel < card.hints.length && (
                <button
                  className="more-hint-button"
                  onClick={() => onRequestHint?.(currentHintLevel + 1)}
                  type="button"
                >
                  + {language === "zh-CN" ? "更多提示" : "More hints"}
                </button>
              )}
            </>
          )}
        </div>
      )}

      {/* Evidence submission */}
      {isEvidencing && (
        <div className="card-section card-evidence">
          <div className="section-label">
            <CheckIcon size={14} />
            <span>{card.evidencePrompt}</span>
          </div>
          <textarea
            className="evidence-input"
            value={evidenceDraft}
            onChange={(e) => onEvidenceChange?.(e.target.value)}
            placeholder={language === "zh-CN" ? "写下答案或代码..." : "Write your answer or code..."}
            rows={6}
          />
          <button
            className="submit-button"
            onClick={onSubmitEvidence}
            type="button"
            disabled={!evidenceDraft.trim()}
          >
            <CheckIcon size={14} />
            <span>{submitEvidenceLabel}</span>
          </button>
        </div>
      )}

      {/* Rating buttons */}
      {isRating && (
        <div className="card-section card-rating">
          <div className="section-label">
            <TrophyIcon size={14} />
            <span>{rateYourselfLabel}</span>
          </div>
          <div className="rating-buttons">
            <button
              className={`rating-button rating-button--again ${rating === "again" ? "is-selected" : ""}`}
              onClick={() => handleRate("again")}
              type="button"
              disabled={!canTransitionCardStatus}
            >
              <span className="rating-label">{againLabel}</span>
              <span className="rating-desc">
                {language === "zh-CN" ? "需要更多练习" : "Need more practice"}
              </span>
            </button>
            <button
              className={`rating-button rating-button--hard ${rating === "hard" ? "is-selected" : ""}`}
              onClick={() => handleRate("hard")}
              type="button"
              disabled={!canTransitionCardStatus}
            >
              <span className="rating-label">{hardLabel}</span>
              <span className="rating-desc">
                {language === "zh-CN" ? "有点困难" : "A bit difficult"}
              </span>
            </button>
            <button
              className={`rating-button rating-button--good ${rating === "good" ? "is-selected" : ""}`}
              onClick={() => handleRate("good")}
              type="button"
              disabled={!canTransitionCardStatus}
            >
              <span className="rating-label">{goodLabel}</span>
              <span className="rating-desc">
                {language === "zh-CN" ? "掌握良好" : "Good grasp"}
              </span>
            </button>
            <button
              className={`rating-button rating-button--easy ${rating === "easy" ? "is-selected" : ""}`}
              onClick={() => handleRate("easy")}
              type="button"
              disabled={!canTransitionCardStatus}
            >
              <span className="rating-label">{easyLabel}</span>
              <span className="rating-desc">
                {language === "zh-CN" ? "太简单了" : "Too easy"}
              </span>
            </button>
          </div>
        </div>
      )}

      {/* Done state */}
      {isDone && (
        <div className="card-section card-done">
          <div className="done-message">
            {language === "zh-CN" ? "这张卡片完成了！" : "Card completed!"}
          </div>
          <button
            className="next-card-button"
            onClick={onNextCard}
            type="button"
          >
            <ArrowRightIcon size={14} />
            <span>{nextCardLabel}</span>
          </button>
        </div>
      )}

      {/* Pass criteria (shown when rating, collapsed detail) */}
      {isRating && card.passCriteria.length > 0 && (
        <div className="card-section card-criteria">
          <CollapseSection
            level={2}
            title={passCriteriaLabel}
            persistenceKey={`card-${card.id}-pass-criteria`}
          >
            <ul className="criteria-list">
              {card.passCriteria.map((criteria, index) => (
                <li key={index} className="criteria-item">
                  {criteria}
                </li>
              ))}
            </ul>
          </CollapseSection>
        </div>
      )}

      {/* Concepts tags */}
      {card.concepts.length > 0 && (
        <div className="card-concepts">
          <span className="concepts-label">{conceptsLabel}:</span>
          <div className="concepts-tags">
            {card.concepts.map((concept, index) => (
              <span key={index} className="concept-tag">
                {concept}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Footer actions */}
      <div className="card-footer">
        <button
          className="skip-button"
          onClick={handleSkip}
          type="button"
          disabled={!canTransitionCardStatus}
        >
          {skipLabel}
        </button>
        {isAttempting && !showHints && (
          <button
            className="ready-button"
            onClick={() => {}}
            type="button"
          >
            {language === "zh-CN" ? "准备好了" : "I'm ready"}
          </button>
        )}
      </div>
    </div>
  );
};
