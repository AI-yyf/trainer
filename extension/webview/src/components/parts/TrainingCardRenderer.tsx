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
 * Multi-language support for TrainingCardRenderer
 * Maps ComposerLanguage to locale-specific text
 */
const TRAINING_LABELS: Record<ComposerLanguage, Record<string, string>> = {
  "zh-CN": {
    cardTypeFlash: "闪卡",
    cardTypePractice: "练习卡",
    difficultyEasy: "简单",
    difficultyMedium: "中等",
    difficultyHard: "困难",
    focus: "专注",
    skill: "技能",
    whyNow: "为什么现在练",
    problem: "问题",
    deliverable: "交付物",
    success: "成功信号",
    validation: "验证方式",
    hintLadder: "提示阶梯",
    hintsAvailable: "{n} 个提示可用",
    showHint: "显示下一个提示",
    usedHints: "已使用 {revealed}/{total} 个提示",
    submitEvidence: "提交证据",
    evidencePlaceholder: "描述你的尝试、结果或理解...",
    cancel: "取消",
    submitAndRate: "提交并评分",
    yourPerformance: "你的表现",
    selectPerformanceHint: "选择最符合你当前状态的选项",
    mastery: "掌握",
    state: "状态",
    due: "到期",
    intervalDays: "{n} 天",
    source: "来源",
    verification: "验收步骤",
    nextAfterCompletion: "完成后下一步",
    ifStuck: "如果卡住",
    sourceChain: "来源链",
    startPractice: "开始练习",
    skip: "跳过",
    viewDetails: "查看详情",
    ratingAgain: "重试",
    ratingHard: "困难",
    ratingGood: "良好",
    ratingEasy: "简单",
  },
  "en-US": {
    cardTypeFlash: "Flash Card",
    cardTypePractice: "Practice Card",
    difficultyEasy: "Easy",
    difficultyMedium: "Medium",
    difficultyHard: "Hard",
    focus: "Focus",
    skill: "Skill",
    whyNow: "Why now",
    problem: "Problem",
    deliverable: "Deliver",
    success: "Success",
    validation: "Validate by",
    hintLadder: "Hint Ladder",
    hintsAvailable: "{n} hint{plural} available",
    showHint: "Show hint {n}",
    usedHints: "Used {revealed}/{total} hints",
    submitEvidence: "Submit Evidence",
    evidencePlaceholder: "Describe your attempt, results, or understanding...",
    cancel: "Cancel",
    submitAndRate: "Submit & Rate",
    yourPerformance: "Your Performance",
    selectPerformanceHint: "Choose the option that best matches your current state",
    mastery: "Mastery",
    state: "State",
    due: "Due",
    intervalDays: "{n} days",
    source: "Source",
    verification: "Verification",
    nextAfterCompletion: "Next after completion",
    ifStuck: "If stuck",
    sourceChain: "Source chain",
    startPractice: "Start Practice",
    skip: "Skip",
    viewDetails: "View Details",
    ratingAgain: "Again",
    ratingHard: "Hard",
    ratingGood: "Good",
    ratingEasy: "Easy",
  },
  "es-ES": {
    cardTypeFlash: "Tarjeta rápida",
    cardTypePractice: "Tarjeta de práctica",
    difficultyEasy: "Fácil",
    difficultyMedium: "Medio",
    difficultyHard: "Difícil",
    focus: "Enfoque",
    skill: "Habilidad",
    whyNow: "Por qué ahora",
    problem: "Problema",
    deliverable: "Entregable",
    success: "Éxito",
    validation: "Validar por",
    hintLadder: "Escalera de pistas",
    hintsAvailable: "{n} pistas disponibles",
    showHint: "Mostrar pista {n}",
    usedHints: "Usadas {revealed}/{total} pistas",
    submitEvidence: "Enviar evidencia",
    evidencePlaceholder: "Describe tu intento, resultados o comprensión...",
    cancel: "Cancelar",
    submitAndRate: "Enviar y calificar",
    yourPerformance: "Tu rendimiento",
    selectPerformanceHint: "Elige la opción que mejor describe tu estado",
    mastery: "Dominio",
    state: "Estado",
    due: "Vence",
    intervalDays: "{n} días",
    source: "Fuente",
    verification: "Verificación",
    nextAfterCompletion: "Siguiente después de completar",
    ifStuck: "Si te atascas",
    sourceChain: "Cadena de origen",
    startPractice: "Iniciar práctica",
    skip: "Saltar",
    viewDetails: "Ver detalles",
    ratingAgain: "Otra vez",
    ratingHard: "Difícil",
    ratingGood: "Bien",
    ratingEasy: "Fácil",
  },
  "fr-FR": {
    cardTypeFlash: "Carte flash",
    cardTypePractice: "Carte d'exercice",
    difficultyEasy: "Facile",
    difficultyMedium: "Moyen",
    difficultyHard: "Difficile",
    focus: "Focus",
    skill: "Compétence",
    whyNow: "Pourquoi maintenant",
    problem: "Problème",
    deliverable: "Livrable",
    success: "Succès",
    validation: "Valider par",
    hintLadder: "Échelle de conseils",
    hintsAvailable: "{n} conseils disponibles",
    showHint: "Afficher conseil {n}",
    usedHints: "{revealed}/{total} conseils utilisés",
    submitEvidence: "Soumettre une preuve",
    evidencePlaceholder: "Décrivez votre tentative, vos résultats ou votre compréhension...",
    cancel: "Annuler",
    submitAndRate: "Soumettre et noter",
    yourPerformance: "Votre performance",
    selectPerformanceHint: "Choisissez l'option qui correspond le mieux à votre état",
    mastery: "Maîtrise",
    state: "État",
    due: "Échéance",
    intervalDays: "{n} jours",
    source: "Source",
    verification: "Vérification",
    nextAfterCompletion: "Suite après completion",
    ifStuck: "Si bloqué",
    sourceChain: "Chaîne source",
    startPractice: "Commencer l'exercice",
    skip: "Passer",
    viewDetails: "Voir détails",
    ratingAgain: "À revoir",
    ratingHard: "Difficile",
    ratingGood: "Bien",
    ratingEasy: "Facile",
  },
  "de-DE": {
    cardTypeFlash: "Lernkarte",
    cardTypePractice: "Übungskarte",
    difficultyEasy: "Einfach",
    difficultyMedium: "Mittel",
    difficultyHard: "Schwer",
    focus: "Fokus",
    skill: "Fähigkeit",
    whyNow: "Warum jetzt",
    problem: "Problem",
    deliverable: "Liefergegenstand",
    success: "Erfolg",
    validation: "Validieren durch",
    hintLadder: "Hinweis-Leiter",
    hintsAvailable: "{n} Hinweise verfügbar",
    showHint: "Hinweis {n} anzeigen",
    usedHints: "{revealed}/{total} Hinweise verwendet",
    submitEvidence: "Beweis einreichen",
    evidencePlaceholder: "Beschreibe deinen Versuch, Ergebnisse oder Verständnis...",
    cancel: "Abbrechen",
    submitAndRate: "Einreichen & Bewerten",
    yourPerformance: "Deine Leistung",
    selectPerformanceHint: "Wähle die Option, die deinem Zustand am besten entspricht",
    mastery: "Beherrschung",
    state: "Zustand",
    due: "Fällig",
    intervalDays: "{n} Tage",
    source: "Quelle",
    verification: "Verifizierung",
    nextAfterCompletion: "Nächster Schritt",
    ifStuck: "Wenn festgefahren",
    sourceChain: "Quellkette",
    startPractice: "Übung starten",
    skip: "Überspringen",
    viewDetails: "Details anzeigen",
    ratingAgain: "Nochmal",
    ratingHard: "Schwer",
    ratingGood: "Gut",
    ratingEasy: "Leicht",
  },
  "ja-JP": {
    cardTypeFlash: "フラッシュカード",
    cardTypePractice: "練習カード",
    difficultyEasy: "簡単",
    difficultyMedium: "普通",
    difficultyHard: "難しい",
    focus: "フォーカス",
    skill: "スキル",
    whyNow: "なぜ今",
    problem: "問題",
    deliverable: "成果物",
    success: "成功信号",
    validation: "検証方法",
    hintLadder: "ヒントはしご",
    hintsAvailable: "{n}個の利用可能ヒント",
    showHint: "ヒント{n}を表示",
    usedHints: "{revealed}/{total}個ヒント使用済み",
    submitEvidence: "証拠を提出",
    evidencePlaceholder: "あなたの試み、結果、理解を説明してください...",
    cancel: "キャンセル",
    submitAndRate: "提出して評価",
    yourPerformance: "あなたのパフォーマンス",
    selectPerformanceHint: "現在の状態に最も 맞는オプションを選択してください",
    mastery: "習熟度",
    state: "状態",
    due: "期限",
    intervalDays: "{n}日",
    source: "ソース",
    verification: "検証",
    nextAfterCompletion: "完了後の次のステップ",
    ifStuck: "行き詰まった場合",
    sourceChain: "ソースチェーン",
    startPractice: "練習を開始",
    skip: "スキップ",
    viewDetails: "詳細を見る",
    ratingAgain: "もう一度",
    ratingHard: "難しい",
    ratingGood: "良い",
    ratingEasy: "簡単",
  },
  "ko-KR": {
    cardTypeFlash: "플래시카드",
    cardTypePractice: "연습카드",
    difficultyEasy: "쉬움",
    difficultyMedium: "보통",
    difficultyHard: "어려움",
    focus: "집중",
    skill: "스킬",
    whyNow: "왜 지금",
    problem: "문제",
    deliverable: "산출물",
    success: "성공 신호",
    validation: "검증 방식",
    hintLadder: "힌트 사다리",
    hintsAvailable: "{n}개의 힌트 사용 가능",
    showHint: "힌트 {n} 표시",
    usedHints: "{revealed}/{total}개 힌트 사용됨",
    submitEvidence: "증거 제출",
    evidencePlaceholder: "시도, 결과 또는 이해를 설명하세요...",
    cancel: "취소",
    submitAndRate: "제출 및 평가",
    yourPerformance: "나의 성과",
    selectPerformanceHint: "현재 상태와 가장 일치하는 옵션을 선택하세요",
    mastery: "마스터리",
    state: "상태",
    due: "기한",
    intervalDays: "{n}일",
    source: "출처",
    verification: "검증",
    nextAfterCompletion: "완료 후 다음 단계",
    ifStuck: "막힌 경우",
    sourceChain: "출처 체인",
    startPractice: "연습 시작",
    skip: "건너뛰기",
    viewDetails: "상세 보기",
    ratingAgain: "다시",
    ratingHard: "어려움",
    ratingGood: "좋음",
    ratingEasy: "쉬움",
  },
  "pt-BR": {
    cardTypeFlash: "Cartão rápido",
    cardTypePractice: "Cartão de prática",
    difficultyEasy: "Fácil",
    difficultyMedium: "Médio",
    difficultyHard: "Difícil",
    focus: "Foco",
    skill: "Habilidade",
    whyNow: "Por que agora",
    problem: "Problema",
    deliverable: "Entregável",
    success: "Sucesso",
    validation: "Validar por",
    hintLadder: "Escada de dicas",
    hintsAvailable: "{n} dicas disponíveis",
    showHint: "Mostrar dica {n}",
    usedHints: "{revealed}/{total} dicas usadas",
    submitEvidence: "Enviar evidência",
    evidencePlaceholder: "Descreva sua tentativa, resultados ou compreensão...",
    cancel: "Cancelar",
    submitAndRate: "Enviar e classificar",
    yourPerformance: "Seu desempenho",
    selectPerformanceHint: "Escolha a opção que melhor corresponde ao seu estado",
    mastery: "Domínio",
    state: "Estado",
    due: "Vencimento",
    intervalDays: "{n} dias",
    source: "Fonte",
    verification: "Verificação",
    nextAfterCompletion: "Próximo após completar",
    ifStuck: "Se travado",
    sourceChain: "Cadeia de origem",
    startPractice: "Iniciar prática",
    skip: "Pular",
    viewDetails: "Ver detalhes",
    ratingAgain: "De novo",
    ratingHard: "Difícil",
    ratingGood: "Bom",
    ratingEasy: "Fácil",
  },
};

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
 * Simple translation helper for binary zh/en decisions
 */
function t(language: ComposerLanguage, zh: string, en: string): string {
  return language === "zh-CN" ? zh : en;
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
      language === "zh-CN" ? "学员跳过" : "Learner skipped",
    );
  }, [cardId, language, onCardStatusTransition]);

  const handleRate = useCallback((rating: TrainingRating) => {
    if (!cardId || !onCardStatusTransition) {
      return;
    }
    const reason =
      rating === "again"
        ? language === "zh-CN"
          ? "自评：再来一次"
          : "Self-grade: again"
        : rating === "hard"
          ? language === "zh-CN"
            ? "自评：有点难"
            : "Self-grade: hard"
          : rating === "good"
            ? language === "zh-CN"
              ? "自评：不错"
              : "Self-grade: good"
            : language === "zh-CN"
              ? "自评：太简单了"
              : "Self-grade: easy";
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
