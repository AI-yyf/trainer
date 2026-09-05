import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ArrowRightIcon,
  BooksIcon,
  CheckMarkIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  LightBulbIcon,
  RadioButtonEmptyIcon,
  RadioButtonIcon,
  SquareIcon,
  TrophyIcon,
  WarningIcon,
  XMarkIcon,
} from "../icons";
import { MessageRichContent } from "../coach/MessageRichContent";
import { CollapseSection } from "../common/CollapseSection";
import { resolveCopy } from "../../lib/i18n/copy";
import type { TrainingCardStatus } from "../../../../../shared/src/trainingCardRouting";
import type {
  ComposerLanguage,
  DependencyMastery,
  FlashcardAttempt,
  FlashcardDeck,
} from "../../lib/types";

type FlashcardAnswerMode = "text" | "single_choice" | "multiple_choice" | "fill_blank" | "sorting" | "true_false";
type FlashStudyPhase = "learn" | "check" | "review";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface FlashPracticeBridge {
  cardId: string;
  cardTitle: string;
  focusArea: string;
  prompt: string;
}

export interface CoachFlashViewProps {
  language: ComposerLanguage;
  deck?: FlashcardDeck;
  deckError?: boolean;
  dependencyMastery: DependencyMastery[];
  recentAttempts: FlashcardAttempt[];
  busy?: boolean;
  practiceBridge?: FlashPracticeBridge;
  cardStatus?: TrainingCardStatus;
  cardStatusBusy?: boolean;
  onCardStatusTransition?: (cardId: string, newStatus: TrainingCardStatus, reason?: string) => void;
  onRefreshDeck: () => void;
  onSubmitAnswer: (payload: {
    cardId: string;
    learnerAnswer?: string;
    selectedOptionIndex?: number;
    selectedOptionIndices?: number[];
    fillBlankAnswers?: Record<number, string>;
    sortOrder?: number[];
  }) => void;
  onOpenCoach: () => void;
  onOpenPractice?: (bridge: FlashPracticeBridge) => void;
  onCreateFlashcard?: (payload: {
    question: string;
    answerMode: FlashcardAnswerMode;
    options?: string[];
    expectedAnswer?: string;
    correctOptionIndex?: number;
    correctOptionIndices?: number[];
    correctSortOrder?: number[];
    fillBlankAnswers?: Record<number, string>;
    hintLadder?: string[];
    context?: string;
  }) => void;
  compact?: boolean;
  cardOnly?: boolean;
  sourceChain?: string[];
  whyNow?: string;
  targetSkill?: string;
  scenarioPackLabel?: string;
  feedbackTargets?: string[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isZh(lang: ComposerLanguage): boolean {
  return lang === "zh-CN";
}

function t(lang: ComposerLanguage, zh: string, en: string): string {
  return isZh(lang) ? zh : en;
}

function normalizeAnswerMode(
  value: string | undefined,
  hasOptions: boolean,
): FlashcardAnswerMode {
  if (
    value === "text" ||
    value === "single_choice" ||
    value === "multiple_choice" ||
    value === "fill_blank" ||
    value === "sorting" ||
    value === "true_false"
  ) {
    return value;
  }
  if (value === "short") {
    return "text";
  }
  if (value === "choice") {
    return "single_choice";
  }
  if (value === "fill") {
    return "fill_blank";
  }
  return hasOptions ? "single_choice" : "text";
}

function answerModeSummary(language: ComposerLanguage, mode: FlashcardAnswerMode): string {
  if (mode === "single_choice") {
    return t(language, "从几个选项里选出最稳的一项。", "Pick the most solid option from the set.");
  }
  if (mode === "multiple_choice") {
    return t(language, "把所有成立的选项一起找出来。", "Find every option that still holds.");
  }
  if (mode === "fill_blank") {
    return t(language, "补上缺失的 keyword 或 concept。", "Fill in the missing keyword or concept.");
  }
  if (mode === "sorting") {
    return t(language, "按正确顺序排好这些步骤。", "Put the steps back into the right order.");
  }
  if (mode === "true_false") {
    return t(language, "先判断对错，再确认理由。", "Decide whether it is true, then confirm why.");
  }
  return t(language, "先用你自己的话给出简短答案。", "Answer in your own words first.");
}

// ---------------------------------------------------------------------------
// Feedback helpers
// ---------------------------------------------------------------------------

function getAnswerFeedback(language: ComposerLanguage, status: FlashcardAttempt["status"], streakCount: number): string {
  if (language === "zh-CN") {
    if (status === "correct") {
      if (streakCount >= 3) return `连续答对 ${streakCount} 张！`;
      return "答对了！";
    }
    if (status === "needsWork") return "需要加强，继续努力";
    return "已回看";
  } else {
    if (status === "correct") {
      if (streakCount >= 3) return `${streakCount} in a row!`;
      return "Correct!";
    }
    if (status === "needsWork") return "Needs work, keep trying";
    return "Reviewed";
  }
}

function calculateStreak(attempts: FlashcardAttempt[]): number {
  let streak = 0;
  const sorted = [...attempts].sort((a, b) =>
    new Date(b.attemptedAt ?? 0).getTime() - new Date(a.attemptedAt ?? 0).getTime()
  );
  for (const attempt of sorted) {
    if (attempt.status === "correct") {
      streak++;
    } else if (attempt.status === "needsWork") {
      break;
    }
  }
  return streak;
}

function pickCard(deck: FlashcardDeck | undefined): FlashcardAttempt | undefined {
  if (!deck || !deck.cards || deck.cards.length === 0) {
    return undefined;
  }
  const unanswered = deck.cards.find((c) => c.status === "unanswered" || !c.status);
  return unanswered ?? deck.cards[0];
}

function feedbackKey(
  status?: FlashcardAttempt["status"],
): "correct" | "incorrect" | "partial" | null {
  if (status === "correct") return "correct";
  if (status === "needsWork") return "incorrect";
  if (status === "reviewed") return "partial";
  return null;
}

function StatusIcon({ status }: { status: FlashcardAttempt["status"] }): React.ReactNode {
  if (status === "correct") return <CheckMarkIcon size={14} />;
  if (status === "needsWork") return <XMarkIcon size={14} />;
  if (status === "reviewed") return <WarningIcon size={14} />;
  return null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CoachFlashView({
  language,
  deck,
  deckError = false,
  dependencyMastery,
  recentAttempts,
  busy = false,
  practiceBridge,
  cardStatus,
  cardStatusBusy = false,
  onCardStatusTransition,
  onRefreshDeck,
  onSubmitAnswer,
  onOpenCoach,
  onOpenPractice,
  onCreateFlashcard,
  compact = false,
  cardOnly = false,
  sourceChain,
  whyNow,
  targetSkill,
  scenarioPackLabel,
  feedbackTargets,
}: CoachFlashViewProps) {
  const card = useMemo(() => pickCard(deck), [deck]);
  const hasOptions = Boolean(card?.options && card.options.length > 0);
  const answerMode = normalizeAnswerMode(card?.answerMode, hasOptions);
  const isAnswered = Boolean(card?.status && card.status !== "unanswered");
  const fbKey = feedbackKey(card?.status);
  const copy = resolveCopy(language);

  // Local state
  const [textInput, setTextInput] = useState("");
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set());
  const [fillBlankAnswers, setFillBlankAnswers] = useState<Record<number, string>>({});
  const [sortOrder, setSortOrder] = useState<number[]>([]);
  const [hintsRevealed, setHintsRevealed] = useState(0);
  const [contextOpen, setContextOpen] = useState(false);
  const [focusedOptionIdx, setFocusedOptionIdx] = useState(0);
  const [masteryMark, setMasteryMark] = useState<"know" | "fuzzy" | "unknown" | null>(null);
  const [studyPhase, setStudyPhase] = useState<FlashStudyPhase>("learn");

  // Creation form state
  const [isCreating, setIsCreating] = useState(false);
  const [createQuestion, setCreateQuestion] = useState("");
  const [createAnswerMode, setCreateAnswerMode] = useState<FlashcardAnswerMode>("text");
  const [createOptions, setCreateOptions] = useState<string[]>([""]);
  const [createExpectedAnswer, setCreateExpectedAnswer] = useState("");
  const [createCorrectIndex, setCreateCorrectIndex] = useState<number | null>(null);
  const [createCorrectIndices, setCreateCorrectIndices] = useState<Set<number>>(new Set());
  const [createCorrectSortOrder, setCreateCorrectSortOrder] = useState<number[]>([]);
  const [createFillBlankAnswers, setCreateFillBlankAnswers] = useState<Record<number, string>>({});
  const [createHints, setCreateHints] = useState<string[]>([""]);
  const [createContext, setCreateContext] = useState("");

  const answerRef = useRef<HTMLTextAreaElement>(null);
  const optionRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);

  // Calculate current streak from recent attempts
  const streak = useMemo(() => calculateStreak(recentAttempts), [recentAttempts]);

  // Feedback message after answer
  const feedbackTitle = useMemo(() => {
    if (isAnswered && card?.status) {
      return getAnswerFeedback(language, card.status, streak);
    }
    return "";
  }, [language, isAnswered, card?.status, streak]);

  // Reset on card change
  useEffect(() => {
    setTextInput("");
    setSelectedIdx(null);
    setSelectedIndices(new Set());
    setFillBlankAnswers({});
    setSortOrder(card?.options ? Array.from({ length: card.options.length }, (_, i) => i) : []);
    setHintsRevealed(0);
    setContextOpen(false);
    setFocusedOptionIdx(0);
    setMasteryMark(null);
    setStudyPhase(isAnswered ? "review" : "learn");
  }, [card?.cardId, card?.options, isAnswered]);

  // Focus answer area on new card
  useEffect(() => {
    if (!isAnswered && studyPhase === "check") {
      setTimeout(() => {
        if (answerMode === "single_choice" || answerMode === "multiple_choice" || answerMode === "true_false") {
          (optionRefs.current[focusedOptionIdx] ?? optionRefs.current[0])?.focus();
          return;
        }
        answerRef.current?.focus();
      }, 80);
    }
  }, [answerMode, card?.cardId, focusedOptionIdx, isAnswered, studyPhase]);

  useEffect(() => {
    if (isAnswered && studyPhase !== "review") {
      setStudyPhase("review");
    }
  }, [isAnswered, studyPhase]);

  // Submit handler
  const handleSubmit = useCallback(() => {
    if (!card || busy || isAnswered) return;
    if (answerMode === "single_choice" || answerMode === "true_false") {
      if (selectedIdx === null) return;
      onSubmitAnswer({ cardId: card.cardId, selectedOptionIndex: selectedIdx });
    } else if (answerMode === "multiple_choice") {
      if (selectedIndices.size === 0) return;
      onSubmitAnswer({ cardId: card.cardId, selectedOptionIndices: Array.from(selectedIndices) });
    } else if (answerMode === "fill_blank") {
      const blanks = Object.keys(fillBlankAnswers).length;
      if (blanks === 0) return;
      onSubmitAnswer({ cardId: card.cardId, fillBlankAnswers });
    } else if (answerMode === "sorting") {
      onSubmitAnswer({ cardId: card.cardId, sortOrder });
    } else {
      if (!textInput.trim()) return;
      onSubmitAnswer({ cardId: card.cardId, learnerAnswer: textInput.trim() });
    }
  }, [answerMode, card, busy, isAnswered, selectedIdx, selectedIndices, fillBlankAnswers, sortOrder, textInput, onSubmitAnswer]);

  // Keyboard: Enter to submit, arrows for options
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!isAnswered && studyPhase === "learn" && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        setStudyPhase("check");
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        if (studyPhase === "check" && (answerMode === "text" || answerMode === "single_choice")) {
          e.preventDefault();
          handleSubmit();
        }
      }
      if (
        (answerMode === "single_choice" || answerMode === "true_false") &&
        hasOptions &&
        !isAnswered &&
        studyPhase === "check"
      ) {
        const optionsCount = card?.options?.length ?? 0;
        if (e.key === "ArrowDown" || e.key === "ArrowRight") {
          e.preventDefault();
          const next = (focusedOptionIdx + 1) % optionsCount;
          setFocusedOptionIdx(next);
          optionRefs.current[next]?.focus();
        }
        if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
          e.preventDefault();
          const prev = (focusedOptionIdx - 1 + optionsCount) % optionsCount;
          setFocusedOptionIdx(prev);
          optionRefs.current[prev]?.focus();
        }
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setSelectedIdx(focusedOptionIdx);
        }
        if (e.key === "1" || e.key === "2" || e.key === "3" || e.key === "4") {
          const idx = parseInt(e.key, 10) - 1;
          if (idx < optionsCount) {
            e.preventDefault();
            setSelectedIdx(idx);
            setFocusedOptionIdx(idx);
            optionRefs.current[idx]?.focus();
          }
        }
      }
    },
    [answerMode, card?.options?.length, focusedOptionIdx, handleSubmit, hasOptions, isAnswered, studyPhase],
  );

  // Mastery mark handler — fail-closed: no local-only grade without status transition.
  const canTransitionCardStatus = Boolean(card?.cardId && onCardStatusTransition);
  const handleMastery = useCallback(
    (level: "know" | "fuzzy" | "unknown") => {
      if (!card?.cardId || !onCardStatusTransition) {
        return;
      }
      setMasteryMark(level);
      const reason =
        level === "know"
          ? t(language, "掌握", "Know well")
          : level === "fuzzy"
            ? t(language, "模糊", "Fuzzy")
            : t(language, "不会", "Don't know");
      onCardStatusTransition(card.cardId, "reviewed", reason);
    },
    [card, language, onCardStatusTransition],
  );

  // Global keyboard shortcuts for immersion
  useEffect(() => {
    function handleGlobalKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA' || target?.isContentEditable) {
        return;
      }

      if (isAnswered) {
        switch (event.key) {
          case 'n':
          case 'N': {
            event.preventDefault();
            onRefreshDeck();
            break;
          }
          case '1': {
            event.preventDefault();
            handleMastery('know');
            break;
          }
          case '2': {
            event.preventDefault();
            handleMastery('fuzzy');
            break;
          }
          case '3': {
            event.preventDefault();
            handleMastery('unknown');
            break;
          }
        }
      }
    }

    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown);
  }, [isAnswered, onRefreshDeck, handleMastery]);

  // Creation form handlers
  const resetCreationForm = useCallback(() => {
    setCreateQuestion("");
    setCreateAnswerMode("text");
    setCreateOptions([""]);
    setCreateExpectedAnswer("");
    setCreateCorrectIndex(null);
    setCreateCorrectIndices(new Set());
    setCreateCorrectSortOrder([]);
    setCreateFillBlankAnswers({});
    setCreateHints([""]);
    setCreateContext("");
    setIsCreating(false);
  }, []);

  const handleCreateSubmit = useCallback(() => {
    if (!onCreateFlashcard || !createQuestion.trim()) return;
    const payload: Parameters<typeof onCreateFlashcard>[0] = {
      question: createQuestion.trim(),
      answerMode: createAnswerMode,
      hintLadder: createHints.filter(Boolean),
      context: createContext.trim() || undefined,
    };
    if (createAnswerMode === "text") {
      payload.expectedAnswer = createExpectedAnswer.trim() || undefined;
    } else if (createAnswerMode === "single_choice") {
      payload.options = createOptions.filter(Boolean);
      payload.correctOptionIndex = createCorrectIndex ?? undefined;
    } else if (createAnswerMode === "multiple_choice") {
      payload.options = createOptions.filter(Boolean);
      payload.correctOptionIndices = Array.from(createCorrectIndices);
    } else if (createAnswerMode === "sorting") {
      payload.options = createOptions.filter(Boolean);
      payload.correctSortOrder = createCorrectSortOrder.length > 0 ? createCorrectSortOrder : undefined;
    } else if (createAnswerMode === "fill_blank") {
      const answers: Record<number, string> = {};
      const matches = createQuestion.match(/\{\{(\d+)\}\}/g);
      if (matches) {
        matches.forEach((m) => {
          const num = parseInt(m.replace(/[{}]/g, ""), 10);
          if (createFillBlankAnswers[num]) {
            answers[num] = createFillBlankAnswers[num];
          }
        });
      }
      payload.fillBlankAnswers = Object.keys(answers).length > 0 ? answers : undefined;
    }
    onCreateFlashcard(payload);
    resetCreationForm();
  }, [onCreateFlashcard, createQuestion, createAnswerMode, createOptions, createExpectedAnswer, createCorrectIndex, createCorrectIndices, createCorrectSortOrder, createFillBlankAnswers, createHints, createContext, resetCreationForm]);

  const addOption = useCallback(() => setCreateOptions((prev) => [...prev, ""]), []);
  const removeOption = useCallback((idx: number) => setCreateOptions((prev) => prev.filter((_, i) => i !== idx)), []);
  const updateOption = useCallback((idx: number, val: string) => {
    setCreateOptions((prev) => {
      const next = [...prev];
      next[idx] = val;
      return next;
    });
  }, []);

  const addHint = useCallback(() => setCreateHints((prev) => [...prev, ""]), []);
  const removeHint = useCallback((idx: number) => setCreateHints((prev) => prev.filter((_, i) => i !== idx)), []);
  const updateHint = useCallback((idx: number, val: string) => {
    setCreateHints((prev) => {
      const next = [...prev];
      next[idx] = val;
      return next;
    });
  }, []);

  // --- Error state ---
  if (deckError) {
    return (
      <section className="section-block flash-state flash-state--error">
        <span className="flash-state__icon" aria-hidden="true"><WarningIcon size={20} /></span>
        <strong className="flash-state__title">
          {language === "zh-CN" ? "加载闪记卡失败" : "Failed to load flashcards"}
        </strong>
        <p className="flash-state__text">
          {language === "zh-CN" ? "请检查连接后重试。" : "Please check your connection and try again."}
        </p>
      </section>
    );
  }

  // --- Empty state ---
  if (!deck || !card) {
    if (isCreating) {
      return (
        <section className="flash-view flash-view--creating" aria-label={t(language, "创建闪记卡", "Create flashcard")}>
          <div className="flash-create-form">
            <h3 className="flash-create-form__title">{t(language, "创建闪记卡", "Create flashcard")}</h3>

            <label className="flash-create-form__label">{t(language, "问题", "Question")}</label>
            <textarea
              className="flash-create-form__textarea"
              rows={3}
              value={createQuestion}
              onChange={(e) => setCreateQuestion(e.target.value)}
              placeholder={t(language, "输入问题... 填空用 {{1}} 占位", "Enter question... Use {{1}} for blanks")}
            />

            <label className="flash-create-form__label">{t(language, "答题模式", "Answer mode")}</label>
            <select
              className="flash-create-form__select"
              value={createAnswerMode}
              onChange={(e) => setCreateAnswerMode(e.target.value as FlashcardAnswerMode)}
            >
              <option value="text">{t(language, "文本回答", "Text answer")}</option>
              <option value="single_choice">{t(language, "单选题", "Single choice")}</option>
              <option value="multiple_choice">{t(language, "多选题", "Multiple choice")}</option>
              <option value="sorting">{t(language, "排序题", "Sorting")}</option>
              <option value="fill_blank">{t(language, "填空题", "Fill in blank")}</option>
            </select>

            {(createAnswerMode === "single_choice" || createAnswerMode === "multiple_choice" || createAnswerMode === "sorting") && (
              <div className="flash-create-form__options">
                <label className="flash-create-form__label">{t(language, "选项", "Options")}</label>
                {createOptions.map((opt, idx) => (
                  <div key={idx} className="flash-create-form__option-row">
                    <input
                      className="flash-create-form__input"
                      value={opt}
                      onChange={(e) => updateOption(idx, e.target.value)}
                      placeholder={t(language, `选项 ${idx + 1}`, `Option ${idx + 1}`)}
                    />
                    {createOptions.length > 1 && (
                      <button type="button" className="button button--ghost button--micro" onClick={() => removeOption(idx)}>
                        <XMarkIcon size={12} />
                      </button>
                    )}
                  </div>
                ))}
                <button type="button" className="button button--ghost button--micro" onClick={addOption}>
                  {t(language, "+ 添加选项", "+ Add option")}
                </button>

                {createAnswerMode === "single_choice" && (
                  <div className="flash-create-form__correct">
                    <label className="flash-create-form__label">{t(language, "正确答案", "Correct answer")}</label>
                    <select
                      className="flash-create-form__select"
                      value={createCorrectIndex ?? ""}
                      onChange={(e) => setCreateCorrectIndex(e.target.value === "" ? null : parseInt(e.target.value, 10))}
                    >
                      <option value="">{t(language, "选择正确答案", "Select correct answer")}</option>
                      {createOptions.filter(Boolean).map((opt, idx) => (
                        <option key={idx} value={idx}>{opt}</option>
                      ))}
                    </select>
                  </div>
                )}

                {createAnswerMode === "multiple_choice" && (
                  <div className="flash-create-form__correct">
                    <label className="flash-create-form__label">{t(language, "正确答案", "Correct answers")}</label>
                    <div className="flash-create-form__checkboxes">
                      {createOptions.filter(Boolean).map((opt, idx) => (
                        <label key={idx} className="flash-create-form__checkbox-label">
                          <input
                            type="checkbox"
                            checked={createCorrectIndices.has(idx)}
                            onChange={(e) => {
                              setCreateCorrectIndices((prev) => {
                                const next = new Set(prev);
                                if (e.target.checked) next.add(idx);
                                else next.delete(idx);
                                return next;
                              });
                            }}
                          />
                          {opt}
                        </label>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {createAnswerMode === "text" && (
              <div className="flash-create-form__expected">
                <label className="flash-create-form__label">{t(language, "参考答案", "Expected answer")}</label>
                <textarea
                  className="flash-create-form__textarea"
                  rows={2}
                  value={createExpectedAnswer}
                  onChange={(e) => setCreateExpectedAnswer(e.target.value)}
                  placeholder={t(language, "输入参考答案...", "Enter expected answer...")}
                />
              </div>
            )}

            {createAnswerMode === "fill_blank" && (
              <div className="flash-create-form__fill-blank-hint">
                <p className="flash-create-form__hint-text">
                  {t(language, "在问题中使用 {{1}}、{{2}} 等标记填空位置，然后在下方输入每个空的正确答案。", "Use {{1}}, {{2}} etc. in question to mark blanks, then enter correct answers below.")}
                </p>
                {(() => {
                  const matches = createQuestion.match(/\{\{(\d+)\}\}/g);
                  if (!matches) return <p className="flash-create-form__warning">{t(language, "尚未在问题中检测到填空标记", "No blank markers detected in question")}</p>;
                  const seen = new Set<number>();
                  return matches.map((m) => {
                    const num = parseInt(m.replace(/[{}]/g, ""), 10);
                    if (seen.has(num)) return null;
                    seen.add(num);
                    return (
                      <div key={num} className="flash-create-form__blank-row">
                        <label>{t(language, `空 ${num}`, `Blank ${num}`)}</label>
                        <input
                          className="flash-create-form__input"
                          value={createFillBlankAnswers[num] ?? ""}
                          onChange={(e) => setCreateFillBlankAnswers((prev) => ({ ...prev, [num]: e.target.value }))}
                        />
                      </div>
                    );
                  });
                })()}
              </div>
            )}

            <div className="flash-create-form__hints">
              <label className="flash-create-form__label">{t(language, "提示（可选）", "Hints (optional)")}</label>
              {createHints.map((hint, idx) => (
                <div key={idx} className="flash-create-form__hint-row">
                  <input
                    className="flash-create-form__input"
                    value={hint}
                    onChange={(e) => updateHint(idx, e.target.value)}
                    placeholder={t(language, `提示 ${idx + 1}`, `Hint ${idx + 1}`)}
                  />
                  {createHints.length > 1 && (
                    <button type="button" className="button button--ghost button--micro" onClick={() => removeHint(idx)}>
                      <XMarkIcon size={12} />
                    </button>
                  )}
                </div>
              ))}
              <button type="button" className="button button--ghost button--micro" onClick={addHint}>
                {t(language, "+ 添加提示", "+ Add hint")}
              </button>
            </div>

            <label className="flash-create-form__label">{t(language, "背景上下文（可选）", "Context (optional)")}</label>
            <textarea
              className="flash-create-form__textarea"
              rows={2}
              value={createContext}
              onChange={(e) => setCreateContext(e.target.value)}
              placeholder={t(language, "输入背景上下文...", "Enter context...")}
            />

            <div className="flash-create-form__actions">
              <button
                className="button button--accent"
                type="button"
                onClick={handleCreateSubmit}
                disabled={!createQuestion.trim() || busy}
              >
                {t(language, "创建闪记卡", "Create flashcard")}
              </button>
              <button className="button button--ghost" type="button" onClick={resetCreationForm}>
                {t(language, "取消", "Cancel")}
              </button>
            </div>
          </div>
        </section>
      );
    }
    return (
      <section
        className="flash-view coach-empty-state coach-empty-state--welcome"
        aria-label={t(language, "闪卡复习", "Flash review")}
        ref={containerRef}
      >
        <div className="flash-empty__icon" aria-hidden="true">
          <BooksIcon size={32} />
        </div>
        <p className="coach-empty-state__copy">
          {t(language, "你的闪记卡库还是空的", "Your flashcard deck is empty")}
        </p>
        <p className="coach-empty-state__hint">
          {t(
            language,
            "暂无闪卡。完成实战卡，或从对话生成闪记。",
            "No flashcards yet. Finish a practice card or generate flashcards from chat.",
          )}
        </p>
        <div className="coach-empty-state__starters">
          <button className="button button--accent" type="button" onClick={onOpenCoach}>
            {t(language, "去找教练聊聊", "Chat with coach")}
          </button>
          {onCreateFlashcard ? (
            <button className="button button--accent" type="button" onClick={() => setIsCreating(true)}>
              {t(language, "手动创建闪记卡", "Create flashcard manually")}
            </button>
          ) : null}
          <button className="button button--ghost" type="button" onClick={onRefreshDeck} disabled={busy}>
            {t(language, "刷新卡组", "Refresh deck")}
          </button>
        </div>
      </section>
    );
  }

  // --- Loading state ---
  if (busy && !isAnswered) {
    return (
      <section className="flash-view" aria-busy="true" aria-label={t(language, "加载中", "Loading")}>
        <div className="flash-loading">
          <div className="training-skeleton-lines" aria-hidden="true">
            <span className="skeleton training-skeleton-line" />
            <span className="skeleton training-skeleton-line" />
            <span className="skeleton training-skeleton-line training-skeleton-line--short" />
          </div>
          <p className="flash-loading__text">
            {t(language, "提交中\u2026", "Submitting\u2026")}
          </p>
        </div>
      </section>
    );
  }

  const knowledgeTypeBadge = card.knowledgeType
    ? card.knowledgeType
    : null;

  const hintLadder = card.hintLadder ?? [];
  const canShowMoreHints = hintsRevealed < hintLadder.length;
  const rubricItems = Array.isArray(card.rubric) ? card.rubric : (card.rubric ? [card.rubric] : []);
  const commonMistakes = card.commonMistakes ?? [];
  const cardRecord = card as unknown as Record<string, unknown>;
  const lastFeedback = (
    (cardRecord.lastFeedback ?? cardRecord.last_feedback) as Record<string, unknown> | undefined
  );
  const gradedStatus: FlashcardAttempt["status"] =
    typeof lastFeedback?.correct === "boolean"
      ? lastFeedback.correct
        ? "correct"
        : "needsWork"
      : card.status;
  const gradedScore = typeof lastFeedback?.score === "number" ? lastFeedback.score : undefined;
  const gradedDetail = typeof lastFeedback?.detail === "string" ? lastFeedback.detail : undefined;
  const feedbackText =
    gradedDetail
    ?? (fbKey && card.feedback && typeof card.feedback === 'object' ? card.feedback[fbKey] : null);
  const visibleStudyPhase: FlashStudyPhase = isAnswered ? "review" : studyPhase;
  const sourceChainTrail = (sourceChain ?? []).filter(Boolean);
  const visibleFeedbackTargets = (feedbackTargets ?? []).filter(Boolean);
  const firstHint = hintLadder.find((hint) => hint?.trim())?.trim();
  const firstCommonMistake = commonMistakes.find((mistake) => mistake?.trim())?.trim();
  const cardContext = card.context?.trim() ?? "";
  const learnHeadline = targetSkill?.trim()
    ? t(language, `先把 ${targetSkill.trim()} 对齐，再开始检查。`, `Review ${targetSkill.trim()} first, then start the check.`)
    : scenarioPackLabel?.trim()
      ? t(
          language,
          `先把 ${scenarioPackLabel.trim()} 这组场景读顺，再开始检查。`,
          `Read through the ${scenarioPackLabel.trim()} scenario family first, then start the check.`,
        )
      : t(
          language,
          "先把这张卡想让你锁住的判断点对齐，再开始检查。",
          "Get the judgment this card is trying to lock in clear before you start the check.",
        );
  const learnWhyNow = whyNow?.trim()
    ? whyNow.trim()
    : t(
        language,
        "先把下一步想清楚，再进入检查。这样更像真实工作流，不像突然考试。",
        "Get the next step clear before you enter the check. It should feel like real work, not a surprise exam.",
      );
  const studyCue = firstHint
    ?? (cardContext
      ? cardContext
      : t(
          language,
          "先用自己的话回忆：这张卡在帮你避免什么错误，或者在帮你确认哪个关键动作。",
          "First say to yourself which mistake this card is helping you avoid, or which move it is helping you confirm.",
        ));
  const returnCue = visibleFeedbackTargets[0]
    ?? t(
        language,
        "做完后带着你的答案和一个还不确定的点回到 Coach。",
        "After the check, bring back your answer and one thing you are still unsure about.",
      );
  const showLearnContextDetails = Boolean(cardContext) && cardContext !== studyCue;
  const showCheckSurface = visibleStudyPhase !== "learn";
  const startCheck = () => setStudyPhase("check");

  const hasCard = Boolean(deck && card);
  const isDeckComplete = deck && (
    (deck.dueCount === 0 && deck.remainingCount === 0) ||
    (deck.dueCount != null && deck.dueCount === 0 && deck.remainingCount != null && deck.remainingCount === 0)
  );
  const deckTotal = deck?.cards?.length ?? 0;
  const correctCount = deck?.cards?.filter(c => c.status === "correct" || c.status === "reviewed").length ?? 0;
  const accuracyPercent = deckTotal > 0 ? Math.round((correctCount / deckTotal) * 100) : 0;
  const isNoDeck = !deck || deckTotal === 0;

  return (
    <section
      key={card?.cardId ?? "empty"}
      className={`flash-view ${compact ? "flash-view--compact" : ""} ${cardOnly ? "flash-view--card-only" : ""} ${hasCard ? "card-enter" : ""}`}
      aria-label={t(language, "当前闪卡", "Current flashcard")}
      onKeyDown={handleKeyDown}
      ref={containerRef}
    >
      {/* ---- No deck state - first time user ---- */}
      {isNoDeck && !isCreating ? (
        <div className="flash-empty">
          <div className="flash-empty__icon" aria-hidden="true">
            <BooksIcon size={48} />
          </div>
          <h3 className="flash-empty__title">
            {language === "zh-CN" ? "开始你的闪记训练" : "Start your flash training"}
          </h3>
          <p className="flash-empty__description">
            {language === "zh-CN"
              ? "从对话中学习新知识，或创建自定义闪记卡来强化记忆。"
              : "Learn from conversations or create custom flashcards to strengthen your memory."}
          </p>
          <div className="flash-empty__actions">
            <button
              className="button button--accent"
              type="button"
              onClick={onOpenCoach}
            >
              {language === "zh-CN" ? "开始学习" : "Start learning"}
            </button>
            {onCreateFlashcard && (
              <button
                className="button button--ghost"
                type="button"
                onClick={() => setIsCreating(true)}
              >
                {language === "zh-CN" ? "创建闪记卡" : "Create flashcard"}
              </button>
            )}
          </div>
          <div className="flash-empty__hints">
            <p className="flash-empty__hint-title">
              {language === "zh-CN" ? "来源" : "Sources"}
            </p>
            <ul className="flash-empty__hint-list">
              <li>{language === "zh-CN" ? "→ 对话生成" : "→ From coach chat"}</li>
              <li>{language === "zh-CN" ? "→ 训练后生成" : "→ From training"}</li>
              <li>{language === "zh-CN" ? "→ 资料抽取" : "→ From resources"}</li>
            </ul>
          </div>
        </div>
      ) : isDeckComplete && !isCreating ? (
        <div className="flash-complete">
          <div className="flash-complete__icon" aria-hidden="true">
            <TrophyIcon size={48} />
          </div>
          <h3 className="flash-complete__title">
            {language === "zh-CN"
              ? deckTotal === 0
                ? "卡组已清空"
                : "本轮完成"
              : deckTotal === 0
                ? "Deck cleared"
                : "Round complete"}
          </h3>
          {deckTotal > 0 && (
            <p className="flash-complete__stats">
              {language === "zh-CN"
                ? `本次复习 ${deckTotal} 张 · 正确率 ${accuracyPercent}%`
                : `${deckTotal} cards reviewed · ${accuracyPercent}% accuracy`}
            </p>
          )}
          {streak > 0 && (
            <p className="flash-complete__streak">
              {language === "zh-CN" ? `连续 ${streak} 天` : `${streak} day streak`}
            </p>
          )}
          <div className="flash-complete__actions">
            <button
              className="button button--accent"
              type="button"
              onClick={onRefreshDeck}
            >
              {language === "zh-CN" ? "再来一轮" : "Practice again"}
            </button>
            <button
              className="button button--ghost"
              type="button"
              onClick={onOpenCoach}
            >
              {language === "zh-CN" ? "去找教练" : "Chat with coach"}
            </button>
          </div>
        </div>
      ) : (
        <div className="flash-card-root training-card">
          {/* ---- Flash card type badge (prominent) ---- */}
          <div className="flash-card__type-strip">
        <span className="flash-card__type-badge-main">
          <LightBulbIcon size={14} />
          {t(language, "闪记卡", "Flash")}
        </span>
        <span className="flash-card__type-desc">
          {t(language, "快速回忆 · 即时反馈", "Recall · Instant feedback")}
        </span>
      </div>

      {/* ---- Source chain header ---- */}
      <div className="flash-card__header">
        <div className="flash-card__badges">
          {knowledgeTypeBadge ? (
            <span className="flash-card__badge flash-card__badge--type">
              {knowledgeTypeBadge}
            </span>
          ) : null}
          {scenarioPackLabel ? (
            <span className="message-part__status-chip">
              {t(language, `场景包 · ${scenarioPackLabel}`, `Scenario pack · ${scenarioPackLabel}`)}
            </span>
          ) : null}
          <span className="flash-card__badge flash-card__badge--source">
            {t(language, "来自训练主线和薄弱点", "From training & weak spots")}
          </span>
        </div>
        <div className="flash-card__header-actions">
          {onCreateFlashcard ? (
            <button
              type="button"
              className="button button--ghost button--micro"
              onClick={() => setIsCreating(true)}
              aria-label={t(language, "创建新闪记卡", "Create new flashcard")}
            >
              {t(language, "+ 新建", "+ New")}
            </button>
          ) : null}
          {deck.dueCount != null ? (
            <span className="flash-card__counter">
              {t(language, `待复习 ${deck.dueCount}`, `Due: ${deck.dueCount}`)}
              {deck.remainingCount != null
                ? ` / ${t(language, `剩余 ${deck.remainingCount}`, `${deck.remainingCount} left`)}`
                : ""}
            </span>
          ) : null}
        </div>
      </div>

      {/* ---- Source/why-now/target/feedback metadata is governance-only — moved to debug folding. ---- */}
      {visibleStudyPhase === "learn" ? (
        <div className="training-next-move flash-card__learn-first">
          <span className="training-next-move__label">{t(language, "先学习", "Learn first")}</span>
          <strong>{learnHeadline}</strong>
          <p>{learnWhyNow}</p>
          <ul className="training-inline-list flash-card__learn-first-list">
            <li>{t(language, `先看线索：${studyCue}`, `Study cue: ${studyCue}`)}</li>
            <li>{t(language, `开始检查后：${answerModeSummary(language, answerMode)}`, `Once you start the check: ${answerModeSummary(language, answerMode)}`)}</li>
            {firstCommonMistake ? (
              <li>{t(language, `常见误区：${firstCommonMistake}`, `Common miss: ${firstCommonMistake}`)}</li>
            ) : null}
            <li>{t(language, `带回 Coach：${returnCue}`, `Bring back to Coach: ${returnCue}`)}</li>
          </ul>
          {showLearnContextDetails ? (
            <details className="training-details flash-card__learn-first-details">
              <summary>{t(language, "更多上下文", "More context")}</summary>
              <div className="training-details__summary">{cardContext}</div>
            </details>
          ) : null}
          <div className="training-verification-return__actions flash-card__learn-first-actions">
            <button className="button button--accent" type="button" onClick={startCheck} disabled={busy}>
              {t(language, "开始检查", "Start check")}
            </button>
            <button className="button button--ghost" type="button" onClick={onOpenCoach}>
              {t(language, "问 Coach", "Ask coach")}
            </button>
          </div>
        </div>
      ) : null}

      {hasCard && (sourceChainTrail.length || whyNow || targetSkill || feedbackTargets?.length) ? (
        <details className="flash-card__debug-meta">
          <summary>{t(language, "更多细节", "Details")}</summary>
          <div className="card-metadata">
            <div className="card-metadata__row">
              {sourceChainTrail.length ? (
                <span className="card-metadata__source">
                  {t(language, `来源: ${sourceChain.join(" → ")}`, `Source: ${sourceChain.join(" → ")}`)}
                </span>
              ) : null}
              {targetSkill ? (
                <span className="card-metadata__skill">{targetSkill}</span>
              ) : null}
            </div>
            {whyNow ? <p className="card-metadata__why">{whyNow}</p> : null}
            {feedbackTargets?.length ? (
              <div className="card-metadata__feedback">
                {feedbackTargets.map((target) => (
                  <span key={target} className="card-metadata__feedback-item">
                    <CheckMarkIcon size={12} />
                    {target}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </details>
      ) : null}

      {showCheckSurface ? (
        <>
          <div className="training-flash-prompt flash-card__check-intro">
            <span>{t(language, visibleStudyPhase === "review" ? "已完成检查" : "现在检查", visibleStudyPhase === "review" ? "Check complete" : "Check now")}</span>
            <p>{answerModeSummary(language, answerMode)}</p>
          </div>

      {/* ---- Question ---- */}
      <div className="flash-card__question" role="heading" aria-level={2}>
        <div className="flash-card__question-content">
          <MessageRichContent
            body={card.question ?? t(language, "（无问题）", "(No question)")}
            language={language}
          />
        </div>
      </div>

      {/* ---- Hint ladder (inline, next to question) ---- */}
      {hintLadder.length > 0 ? (
        <div className="flash-card__hints flash-card__hints--inline">
          {hintsRevealed === 0 && !isAnswered ? (
            <button
              className="flash-card__hints-count"
              type="button"
              onClick={() => setHintsRevealed(1)}
              aria-label={t(
                language,
                `${hintLadder.length} 个提示可用`,
                `${hintLadder.length} hint${hintLadder.length > 1 ? "s" : ""} available`,
              )}
            >
              <span className="flash-card__hints-count-icon" aria-hidden="true">
                <LightBulbIcon size={14} />
              </span>
              <span className="flash-card__hints-count-text">
                {t(
                  language,
                  `${hintLadder.length} 个提示可用`,
                  `${hintLadder.length} hint${hintLadder.length > 1 ? "s" : ""} available`,
                )}
              </span>
            </button>
          ) : null}
          <div className="flash-card__hints-revealed">
            {hintLadder.slice(0, hintsRevealed).map((hint, idx) => (
              <div key={idx} className="flash-card__hint" role="status">
                <span className="flash-card__hint-label">
                  {t(language, `提示 ${idx + 1}`, `Hint ${idx + 1}`)}
                </span>
                <span className="flash-card__hint-text">{hint}</span>
              </div>
            ))}
          </div>
          {canShowMoreHints && hintsRevealed > 0 && !isAnswered ? (
            <button
              className="button button--ghost button--micro"
              type="button"
              onClick={() => setHintsRevealed((n) => n + 1)}
            >
              {t(language, "显示下一条提示", "Show next hint")}
            </button>
          ) : null}
        </div>
      ) : null}

      {/* ---- Context (collapsible, default collapsed) ---- */}
      {card.context ? (
        <details className="flash-card__context" open={contextOpen} onToggle={(e) => setContextOpen((e.currentTarget as HTMLDetailsElement).open)}>
          <summary className="flash-card__context-toggle">
            <span className="flash-card__context-label">
              {t(language, "背景上下文", "Context")}
            </span>
            <span className="flash-card__context-arrow" aria-hidden="true">
              {contextOpen ? <ChevronUpIcon size={12} /> : <ChevronDownIcon size={12} />}
            </span>
          </summary>
          <div className="flash-card__context-body">
            {card.context}
          </div>
        </details>
      ) : null}

        </>
      ) : null}

      {/* ---- Answer area ---- */}
      {!isAnswered && showCheckSurface ? (
        <div className="flash-card__answer-area">
          {(() => {
            if (answerMode === "single_choice" || answerMode === "true_false") {
              return (
                <fieldset className="flash-card__options" role="radiogroup" aria-label={t(language, "选择答案", "Choose an answer")}>
                  <legend className="sr-only">{t(language, "选项", "Options")}</legend>
                  {card.options!.map((opt, idx) => (
                    <button
                      key={idx}
                      ref={(el) => { optionRefs.current[idx] = el; }}
                      type="button"
                      role="radio"
                      aria-checked={selectedIdx === idx}
                      className={`flash-card__option ${selectedIdx === idx ? "flash-card__option--selected" : ""}`}
                      onClick={() => setSelectedIdx(idx)}
                      tabIndex={idx === focusedOptionIdx ? 0 : -1}
                    >
                      <span className="flash-card__option-marker">
                        {selectedIdx === idx ? <RadioButtonIcon size={16} /> : <RadioButtonEmptyIcon size={16} />}
                      </span>
                      <span className="flash-card__option-text">{opt}</span>
                    </button>
                  ))}
                </fieldset>
              );
            }
            if (answerMode === "multiple_choice") {
              return (
                <fieldset className="flash-card__options" role="group" aria-label={t(language, "选择所有符合的选项", "Select all that apply")}>
                  <legend className="sr-only">{t(language, "多选项", "Multiple options")}</legend>
                  {card.options!.map((opt, idx) => (
                    <button
                      key={idx}
                      type="button"
                      role="checkbox"
                      aria-checked={selectedIndices.has(idx)}
                      className={`flash-card__option ${selectedIndices.has(idx) ? "flash-card__option--selected" : ""}`}
                      onClick={() => {
                        setSelectedIndices((prev) => {
                          const next = new Set(prev);
                          if (next.has(idx)) next.delete(idx);
                          else next.add(idx);
                          return next;
                        });
                      }}
                    >
                      <span className="flash-card__option-marker">
                        {selectedIndices.has(idx) ? <CheckMarkIcon size={16} /> : <SquareIcon size={16} />}
                      </span>
                      <span className="flash-card__option-text">{opt}</span>
                    </button>
                  ))}
                </fieldset>
              );
            }
            if (answerMode === "sorting") {
              return (
                <div className="flash-card__sorting" role="list" aria-label={t(language, "排序选项", "Sort options")}>
                  {sortOrder.map((optIdx, position) => (
                    <div key={optIdx} className="flash-card__sort-item" role="listitem">
                      <span className="flash-card__sort-position">{position + 1}</span>
                      <span className="flash-card__sort-text">{card.options![optIdx]}</span>
                      <div className="flash-card__sort-controls">
                        <button
                          type="button"
                          className="button button--ghost button--micro"
                          disabled={position === 0}
                          onClick={() => {
                            setSortOrder((prev) => {
                              const next = [...prev];
                              [next[position], next[position - 1]] = [next[position - 1], next[position]];
                              return next;
                            });
                          }}
                          aria-label={t(language, "上移", "Move up")}
                        >
                          <ChevronUpIcon size={12} />
                        </button>
                        <button
                          type="button"
                          className="button button--ghost button--micro"
                          disabled={position === sortOrder.length - 1}
                          onClick={() => {
                            setSortOrder((prev) => {
                              const next = [...prev];
                              [next[position], next[position + 1]] = [next[position + 1], next[position]];
                              return next;
                            });
                          }}
                          aria-label={t(language, "下移", "Move down")}
                        >
                          <ChevronDownIcon size={12} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              );
            }
            if (answerMode === "fill_blank") {
              const parts = (card.question ?? "").split(/\{\{(\d+)\}\}/g);
              let blankIndex = 0;
              return (
                <div className="flash-card__fill-blank">
                  <p className="flash-card__fill-blank-prompt">
                    {parts.map((part, i) => {
                      if (i % 2 === 1) {
                        const idx = blankIndex++;
                        return (
                          <input
                            key={i}
                            type="text"
                            className="flash-card__fill-blank-input"
                            value={fillBlankAnswers[idx] ?? ""}
                            onChange={(e) => {
                              setFillBlankAnswers((prev) => ({ ...prev, [idx]: e.target.value }));
                            }}
                            placeholder={t(language, `空 ${idx + 1}`, `Blank ${idx + 1}`)}
                            aria-label={t(language, `填空 ${idx + 1}`, `Blank ${idx + 1}`)}
                          />
                        );
                      }
                      return <span key={i}>{part}</span>;
                    })}
                  </p>
                </div>
              );
            }
            return (
              <div className="flash-card__text-input">
                <label htmlFor="flash-answer" className="sr-only">
                  {t(language, "输入你的答案", "Type your answer")}
                </label>
                <textarea
                  id="flash-answer"
                  ref={answerRef}
                  className="flash-card__textarea"
                  rows={3}
                  placeholder={t(language, "输入你的答案\u2026", "Type your answer\u2026")}
                  value={textInput}
                  onChange={(e) => setTextInput(e.target.value)}
                  disabled={busy}
                  aria-label={t(language, "你的回答", "Your answer")}
                />
              </div>
            );
          })()}

          {/* Submit */}
          <div className="flash-card__submit-row">
            <button
              className="button button--accent"
              type="button"
              onClick={handleSubmit}
              disabled={(() => {
                if (answerMode === "single_choice" || answerMode === "true_false") return selectedIdx === null;
                if (answerMode === "multiple_choice") return selectedIndices.size === 0;
                if (answerMode === "sorting") return false;
                if (answerMode === "fill_blank") return Object.keys(fillBlankAnswers).length === 0;
                return !textInput.trim();
              })() || busy}
            >
              {busy
                ? t(language, "提交中\u2026", "Submitting\u2026")
                : t(language, "提交答案", "Submit answer")}
            </button>
          </div>
        </div>
      ) : null}

      {/* ---- Feedback after answer (rotateX reveal) ---- */}
      {isAnswered ? (
        <div className="training-flash-reveal-viewport">
          <div className="training-flash-reveal" key={card.cardId}>
            <div className="flash-card__feedback" aria-live="polite">
              <div className={`flash-card__feedback-banner flash-card__feedback-banner--${gradedStatus ?? "neutral"} score-pulse`}>
                <span className="flash-card__feedback-icon" aria-hidden="true">
                  <StatusIcon status={gradedStatus} />
                </span>
                <span className="flash-card__feedback-label">
                  {gradedStatus === "correct"
                    ? t(language, "答对了", "Correct")
                    : gradedStatus === "needsWork"
                      ? t(language, "待加强", "Needs work")
                      : t(language, "已回看", "Reviewed")}
                </span>
              </div>
              {/* Concise feedback line + (optional) deck-provided hint */}
              {feedbackTitle ? (
                <p className="flash-card__feedback-title">{feedbackTitle}</p>
              ) : null}
              {feedbackText ? (
                <p className="flash-card__feedback-text">{feedbackText}</p>
              ) : null}
              {gradedScore !== undefined ? (
                <p className="flash-card__feedback-score">
                  {t(language, `本题得分：${Math.round(gradedScore * 100)}%`, `Score: ${Math.round(gradedScore * 100)}%`)}
                </p>
              ) : null}

              {/* Expected answer */}
              {card.expectedAnswer ? (
                <div className="flash-card__reference">
                  <span className="flash-card__reference-label">
                    {t(language, "参考答案：", "Reference answer: ")}
                  </span>
                  <span className="flash-card__reference-value">{card.expectedAnswer}</span>
                </div>
              ) : null}

              {/* Learner answer */}
              {card.learnerAnswer ? (
                <div className="flash-card__learner-answer">
                  <span className="flash-card__learner-label">
                    {t(language, "你的回答：", "Your answer: ")}
                  </span>
                  <span className="flash-card__learner-value">{card.learnerAnswer}</span>
                </div>
              ) : null}

              {/* Transferable scenario */}
              {card.transferableScenario ? (
                <div className="flash-card__transferable">
                  <span className="flash-card__transferable-label">
                    {t(language, "迁移场景", "Transferable scenario")}
                  </span>
                  <p className="flash-card__transferable-text">{card.transferableScenario}</p>
                </div>
              ) : null}

              {/* Common mistakes */}
              {commonMistakes.length > 0 ? (
                <div className="flash-card__mistakes">
                  <span className="flash-card__mistakes-label">
                    {t(language, "常见错误", "Common mistakes")}
                  </span>
                  <ul className="flash-card__mistakes-list">
                    {commonMistakes.map((m, idx) => (
                      <li key={idx} className="flash-card__mistakes-item">{m}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {/* Rubric checklist (grading rubric, collapsed detail) */}
              {rubricItems.length > 0 ? (
                <div className="flash-card__rubric">
                  <CollapseSection
                    level={2}
                    title={copy.trainingCardDetailsRubric}
                    persistenceKey={`card-${card.cardId}-rubric`}
                  >
                    <ul className="flash-card__rubric-list">
                      {rubricItems.map((item, idx) => (
                        <li key={idx} className="flash-card__rubric-item">
                          <span className="flash-card__rubric-marker" aria-hidden="true">
                            <SquareIcon size={12} />
                          </span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </CollapseSection>
                </div>
              ) : null}

              {/* Mastery marking */}
              <div className="flash-card__mastery" role="radiogroup" aria-label={t(language, "你觉得掌握了吗？", "How well do you know this?")}>
                <span className="flash-card__mastery-label">
                  {t(language, "你觉得掌握了吗？", "How well do you know this?")}
                </span>
                <div className="flash-card__mastery-buttons">
                  <button
                    className={`button flash-card__mastery-btn ${masteryMark === "know" ? "flash-card__mastery-btn--active flash-card__mastery-btn--know" : ""}`}
                    type="button"
                    role="radio"
                    aria-checked={masteryMark === "know"}
                    onClick={() => handleMastery("know")}
                    disabled={cardStatusBusy || !canTransitionCardStatus}
                  >
                    → {t(language, "掌握", "Know well")}
                    {masteryMark === "know" ? (
                      <span className="flash-card__mastery-check" aria-hidden="true">
                        <CheckMarkIcon size={12} />
                      </span>
                    ) : null}
                  </button>
                  <button
                    className={`button flash-card__mastery-btn ${masteryMark === "fuzzy" ? "flash-card__mastery-btn--active flash-card__mastery-btn--fuzzy" : ""}`}
                    type="button"
                    role="radio"
                    aria-checked={masteryMark === "fuzzy"}
                    onClick={() => handleMastery("fuzzy")}
                    disabled={cardStatusBusy || !canTransitionCardStatus}
                  >
                    → {t(language, "模糊", "Fuzzy")}
                    {masteryMark === "fuzzy" ? (
                      <span className="flash-card__mastery-check" aria-hidden="true">
                        <CheckMarkIcon size={12} />
                      </span>
                    ) : null}
                  </button>
                  <button
                    className={`button flash-card__mastery-btn ${masteryMark === "unknown" ? "flash-card__mastery-btn--active flash-card__mastery-btn--unknown" : ""}`}
                    type="button"
                    role="radio"
                    aria-checked={masteryMark === "unknown"}
                    onClick={() => handleMastery("unknown")}
                    disabled={cardStatusBusy || !canTransitionCardStatus}
                  >
                    → {t(language, "不会", "Don\u2019t know")}
                    {masteryMark === "unknown" ? (
                      <span className="flash-card__mastery-check" aria-hidden="true">
                        <CheckMarkIcon size={12} />
                      </span>
                    ) : null}
                  </button>
                </div>
              </div>

              {/* Actions after answer */}
              <div className="flash-card__kbd-hint" aria-hidden="true">
                <span className="flash-card__kbd">N</span>
                <span>{t(language, "下一张", "Next")}</span>
                <span className="flash-card__kbd">1/2/3</span>
                <span>{t(language, "自评", "Rate")}</span>
                <span className="flash-card__kbd">C</span>
                <span>{t(language, "问教练", "Coach")}</span>
              </div>
              <div className="card-status-nav">
                <button
                  className="card-status-nav__btn card-status-nav__btn--primary"
                  type="button"
                  onClick={onRefreshDeck}
                  disabled={busy}
                >
                  {t(language, "下一张", "Next card")} <ArrowRightIcon size={14} />
                </button>
                <button
                  className="card-status-nav__btn"
                  type="button"
                  onClick={onOpenCoach}
                >
                  {t(language, "问教练", "Ask coach")}
                </button>
                {onOpenPractice && practiceBridge ? (
                  <button
                    className="card-status-nav__btn"
                    type="button"
                    onClick={() => onOpenPractice(practiceBridge)}
                  >
                    {t(language, "在教练中实战", "Practice in coach")}
                  </button>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* ---- Dependency mastery summary (compact) ---- */}
      {!cardOnly && dependencyMastery.length > 0 ? (
        <details className="flash-card__deps" aria-label={t(language, "依赖掌握", "Dependency mastery")}>
          <summary className="flash-card__deps-toggle">
            <span className="eyebrow">{t(language, "依赖掌握", "Dependency mastery")}</span>
            <span className="flash-card__deps-count">{dependencyMastery.length}</span>
          </summary>
          <div className="flash-card__deps-list">
            {dependencyMastery.slice(0, 5).map((dep) => (
              <div key={dep.dependencyKey} className="flash-card__dep-item">
                <span className="flash-card__dep-name">{dep.dependencyName}</span>
                <span className="flash-card__dep-score">
                  {dep.masteryStage ?? t(language, "待建立", "Not established")}
                  {" "}
                  ({Math.round(dep.masteryScore * 100)}%)
                </span>
              </div>
            ))}
          </div>
        </details>
      ) : null}

      {/* ---- Recent attempts strip ---- */}
      {!cardOnly && recentAttempts.length > 0 ? (
        <div className="flash-card__recent" aria-label={t(language, "最近反馈", "Recent feedback")}>
          <span className="flash-card__recent-label eyebrow">
            {t(language, "最近反馈", "Recent feedback")}
          </span>
          <div className="flash-card__recent-strip">
            {recentAttempts.slice(0, 4).map((attempt) => (
              <span
                key={attempt.id}
                className={`flash-card__recent-pip flash-card__recent-pip--${attempt.status ?? "neutral"}`}
                title={attempt.question ?? ""}
                aria-label={`${attempt.question ?? ""}: ${attempt.status ?? "unanswered"}`}
              >
                <StatusIcon status={attempt.status} />
              </span>
            ))}
          </div>
        </div>
      ) : null}
      </div>
    )}
    </section>
  );
}

