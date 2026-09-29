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
import type { ComposerLanguage } from "../../lib/types";

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
  language: ComposerLanguage;
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

type TrainingCardPanelCopyKey =
  | "recallLabel"
  | "recallDescription"
  | "explainLabel"
  | "explainDescription"
  | "predictLabel"
  | "predictDescription"
  | "drillLabel"
  | "drillDescription"
  | "debugLabel"
  | "debugDescription"
  | "transferLabel"
  | "transferDescription"
  | "reviewLabel"
  | "reviewDescription"
  | "difficultyEasy"
  | "difficultyMedium"
  | "difficultyHard"
  | "hintTypeMinimal"
  | "hintTypeStructural"
  | "hintTypeExample"
  | "hintTypeAnswer"
  | "whyNow"
  | "yourTask"
  | "hint"
  | "needHint"
  | "submitAnswer"
  | "rateYourself"
  | "ratingAgain"
  | "ratingHard"
  | "ratingGood"
  | "ratingEasy"
  | "nextCard"
  | "skip"
  | "passCriteria"
  | "concepts"
  | "skipReason"
  | "gradeAgainReason"
  | "gradeHardReason"
  | "gradeGoodReason"
  | "gradeEasyReason"
  | "greetingAttempt"
  | "greetingSubmit"
  | "greetingRate"
  | "greetingDone"
  | "greetingStartNamed"
  | "greetingStart"
  | "currentHintMarker"
  | "moreHints"
  | "evidencePlaceholder"
  | "ratingAgainDescription"
  | "ratingHardDescription"
  | "ratingGoodDescription"
  | "ratingEasyDescription"
  | "doneMessage"
  | "readyButton";

/**
 * Card-panel copy keyed by zh-CN string keys (§十五 i18n copy-record pattern).
 */
const trainingCardPanelTextCopy: Record<
  ComposerLanguage,
  Record<TrainingCardPanelCopyKey, string>
> = {
  "zh-CN": {
    recallLabel: "回忆",
    recallDescription: "主动回忆，不要先看答案",
    explainLabel: "解释",
    explainDescription: "解释原因和机制",
    predictLabel: "预测",
    predictDescription: "预测输出/bug/测试结果",
    drillLabel: "练习",
    drillDescription: "做一个最小实现",
    debugLabel: "调试",
    debugDescription: "提出假设并验证",
    transferLabel: "迁移",
    transferDescription: "把概念用到项目里",
    reviewLabel: "复习",
    reviewDescription: "间隔重复，自评难度",
    difficultyEasy: "简单",
    difficultyMedium: "中等",
    difficultyHard: "困难",
    hintTypeMinimal: "最小提示",
    hintTypeStructural: "结构提示",
    hintTypeExample: "示例",
    hintTypeAnswer: "答案",
    whyNow: "为什么现在练",
    yourTask: "你的任务",
    hint: "提示",
    needHint: "需要提示",
    submitAnswer: "提交答案",
    rateYourself: "给自己评分",
    ratingAgain: "再来一次",
    ratingHard: "有点难",
    ratingGood: "不错",
    ratingEasy: "太简单了",
    nextCard: "下一张",
    skip: "跳过",
    passCriteria: "通过标准",
    concepts: "相关概念",
    skipReason: "学员跳过",
    gradeAgainReason: "自评：再来一次",
    gradeHardReason: "自评：有点难",
    gradeGoodReason: "自评：不错",
    gradeEasyReason: "自评：太简单了",
    greetingAttempt: "先作答",
    greetingSubmit: "提交答案",
    greetingRate: "选择结果",
    greetingDone: "已记录",
    greetingStartNamed: "开始本卡",
    greetingStart: "开始本卡",
    currentHintMarker: "当前",
    moreHints: "更多提示",
    evidencePlaceholder: "写下答案或代码...",
    ratingAgainDescription: "需要更多练习",
    ratingHardDescription: "有点困难",
    ratingGoodDescription: "掌握良好",
    ratingEasyDescription: "太简单了",
    doneMessage: "这张卡片完成了！",
    readyButton: "准备好了",
  },
  "en-US": {
    recallLabel: "Recall",
    recallDescription: "Recall first, don't peek at the answer",
    explainLabel: "Explain",
    explainDescription: "Explain the why and how",
    predictLabel: "Predict",
    predictDescription: "Predict output/bug/test result",
    drillLabel: "Drill",
    drillDescription: "Create a minimal implementation",
    debugLabel: "Debug",
    debugDescription: "Form hypotheses and verify",
    transferLabel: "Transfer",
    transferDescription: "Apply concept to your project",
    reviewLabel: "Review",
    reviewDescription: "Spaced repetition, self-rate difficulty",
    difficultyEasy: "Easy",
    difficultyMedium: "Medium",
    difficultyHard: "Hard",
    hintTypeMinimal: "Minimal",
    hintTypeStructural: "Structural",
    hintTypeExample: "Example",
    hintTypeAnswer: "Answer",
    whyNow: "Why Now",
    yourTask: "Your Task",
    hint: "Hint",
    needHint: "Need a hint?",
    submitAnswer: "Submit Answer",
    rateYourself: "Rate Yourself",
    ratingAgain: "Again",
    ratingHard: "Hard",
    ratingGood: "Good",
    ratingEasy: "Easy",
    nextCard: "Next Card",
    skip: "Skip",
    passCriteria: "Pass Criteria",
    concepts: "Concepts",
    skipReason: "Learner skipped",
    gradeAgainReason: "Self-grade: again",
    gradeHardReason: "Self-grade: hard",
    gradeGoodReason: "Self-grade: good",
    gradeEasyReason: "Self-grade: easy",
    greetingAttempt: "Answer first",
    greetingSubmit: "Submit your answer",
    greetingRate: "Choose result",
    greetingDone: "Recorded",
    greetingStartNamed: "start this card",
    greetingStart: "Start this card",
    currentHintMarker: "current",
    moreHints: "More hints",
    evidencePlaceholder: "Write your answer or code...",
    ratingAgainDescription: "Need more practice",
    ratingHardDescription: "A bit difficult",
    ratingGoodDescription: "Good grasp",
    ratingEasyDescription: "Too easy",
    doneMessage: "Card completed!",
    readyButton: "I'm ready",
  },
  "es-ES": {
    recallLabel: "Evocación",
    recallDescription: "Recuerda activamente, no mires la respuesta primero",
    explainLabel: "Explicar",
    explainDescription: "Explica el porqué y el cómo",
    predictLabel: "Predecir",
    predictDescription: "Predice la salida, el bug o el resultado del test",
    drillLabel: "Práctica",
    drillDescription: "Crea una implementación mínima",
    debugLabel: "Depurar",
    debugDescription: "Formula hipótesis y verifícalas",
    transferLabel: "Transferir",
    transferDescription: "Aplica el concepto a tu proyecto",
    reviewLabel: "Repasar",
    reviewDescription: "Repetición espaciada, autoevalúa la dificultad",
    difficultyEasy: "Fácil",
    difficultyMedium: "Medio",
    difficultyHard: "Difícil",
    hintTypeMinimal: "Mínima",
    hintTypeStructural: "Estructural",
    hintTypeExample: "Ejemplo",
    hintTypeAnswer: "Respuesta",
    whyNow: "Por qué ahora",
    yourTask: "Tu tarea",
    hint: "Pista",
    needHint: "¿Necesitas una pista?",
    submitAnswer: "Enviar respuesta",
    rateYourself: "Califícate",
    ratingAgain: "Otra vez",
    ratingHard: "Difícil",
    ratingGood: "Bien",
    ratingEasy: "Fácil",
    nextCard: "Siguiente tarjeta",
    skip: "Saltar",
    passCriteria: "Criterios de aprobación",
    concepts: "Conceptos",
    skipReason: "Saltado por el estudiante",
    gradeAgainReason: "Autoevaluación: otra vez",
    gradeHardReason: "Autoevaluación: difícil",
    gradeGoodReason: "Autoevaluación: bien",
    gradeEasyReason: "Autoevaluación: muy fácil",
    greetingAttempt: "Responde primero",
    greetingSubmit: "Envía tu respuesta",
    greetingRate: "Elige el resultado",
    greetingDone: "Registrado",
    greetingStartNamed: "empieza esta tarjeta",
    greetingStart: "Empieza esta tarjeta",
    currentHintMarker: "actual",
    moreHints: "Más pistas",
    evidencePlaceholder: "Escribe tu respuesta o código...",
    ratingAgainDescription: "Necesita más práctica",
    ratingHardDescription: "Algo difícil",
    ratingGoodDescription: "Buen dominio",
    ratingEasyDescription: "Demasiado fácil",
    doneMessage: "¡Tarjeta completada!",
    readyButton: "Estoy listo",
  },
  "fr-FR": {
    recallLabel: "Rappel",
    recallDescription: "Faites appel à votre mémoire, ne regardez pas la réponse",
    explainLabel: "Expliquer",
    explainDescription: "Expliquez le pourquoi et le comment",
    predictLabel: "Prédire",
    predictDescription: "Prédisez la sortie, le bug ou le résultat du test",
    drillLabel: "Exercice",
    drillDescription: "Créez une implémentation minimale",
    debugLabel: "Déboguer",
    debugDescription: "Formulez des hypothèses et vérifiez-les",
    transferLabel: "Transférer",
    transferDescription: "Appliquez le concept à votre projet",
    reviewLabel: "Réviser",
    reviewDescription: "Répétition espacée, auto-évaluez la difficulté",
    difficultyEasy: "Facile",
    difficultyMedium: "Moyen",
    difficultyHard: "Difficile",
    hintTypeMinimal: "Minimal",
    hintTypeStructural: "Structurel",
    hintTypeExample: "Exemple",
    hintTypeAnswer: "Réponse",
    whyNow: "Pourquoi maintenant",
    yourTask: "Votre tâche",
    hint: "Indice",
    needHint: "Besoin d'un indice ?",
    submitAnswer: "Soumettre la réponse",
    rateYourself: "Évaluez-vous",
    ratingAgain: "À revoir",
    ratingHard: "Difficile",
    ratingGood: "Bien",
    ratingEasy: "Facile",
    nextCard: "Carte suivante",
    skip: "Passer",
    passCriteria: "Critères de réussite",
    concepts: "Concepts",
    skipReason: "Passé par l'apprenant",
    gradeAgainReason: "Auto-évaluation : à revoir",
    gradeHardReason: "Auto-évaluation : difficile",
    gradeGoodReason: "Auto-évaluation : bien",
    gradeEasyReason: "Auto-évaluation : trop facile",
    greetingAttempt: "Répondez d'abord",
    greetingSubmit: "Soumettez votre réponse",
    greetingRate: "Choisissez le résultat",
    greetingDone: "Enregistré",
    greetingStartNamed: "commencez cette carte",
    greetingStart: "Commencez cette carte",
    currentHintMarker: "actuel",
    moreHints: "Plus d'indices",
    evidencePlaceholder: "Écrivez votre réponse ou votre code...",
    ratingAgainDescription: "Besoin de plus de pratique",
    ratingHardDescription: "Un peu difficile",
    ratingGoodDescription: "Bien maîtrisé",
    ratingEasyDescription: "Trop facile",
    doneMessage: "Carte terminée !",
    readyButton: "Je suis prêt",
  },
  "de-DE": {
    recallLabel: "Abruf",
    recallDescription: "Aktiv abrufen, nicht zuerst auf die Antwort schauen",
    explainLabel: "Erklären",
    explainDescription: "Erkläre das Warum und das Wie",
    predictLabel: "Vorhersagen",
    predictDescription: "Sage Ausgabe, Bug oder Testergebnis voraus",
    drillLabel: "Übung",
    drillDescription: "Erstelle eine minimale Implementierung",
    debugLabel: "Debuggen",
    debugDescription: "Stelle Hypothesen auf und prüfe sie",
    transferLabel: "Transferieren",
    transferDescription: "Wende das Konzept auf dein Projekt an",
    reviewLabel: "Wiederholen",
    reviewDescription: "Verteilt wiederholen, Schwierigkeit selbst einschätzen",
    difficultyEasy: "Einfach",
    difficultyMedium: "Mittel",
    difficultyHard: "Schwer",
    hintTypeMinimal: "Minimal",
    hintTypeStructural: "Strukturell",
    hintTypeExample: "Beispiel",
    hintTypeAnswer: "Antwort",
    whyNow: "Warum jetzt",
    yourTask: "Deine Aufgabe",
    hint: "Hinweis",
    needHint: "Brauchst du einen Hinweis?",
    submitAnswer: "Antwort abschicken",
    rateYourself: "Bewerte dich selbst",
    ratingAgain: "Nochmal",
    ratingHard: "Schwer",
    ratingGood: "Gut",
    ratingEasy: "Leicht",
    nextCard: "Nächste Karte",
    skip: "Überspringen",
    passCriteria: "Bestehenskriterien",
    concepts: "Konzepte",
    skipReason: "Von Lernenden übersprungen",
    gradeAgainReason: "Selbsteinschätzung: nochmal",
    gradeHardReason: "Selbsteinschätzung: schwer",
    gradeGoodReason: "Selbsteinschätzung: gut",
    gradeEasyReason: "Selbsteinschätzung: zu leicht",
    greetingAttempt: "Erst antworten",
    greetingSubmit: "Schicke deine Antwort ab",
    greetingRate: "Ergebnis wählen",
    greetingDone: "Erfasst",
    greetingStartNamed: "starte diese Karte",
    greetingStart: "Starte diese Karte",
    currentHintMarker: "aktuell",
    moreHints: "Mehr Hinweise",
    evidencePlaceholder: "Schreibe deine Antwort oder deinen Code...",
    ratingAgainDescription: "Braucht mehr Übung",
    ratingHardDescription: "Etwas schwierig",
    ratingGoodDescription: "Gut verstanden",
    ratingEasyDescription: "Zu leicht",
    doneMessage: "Karte abgeschlossen!",
    readyButton: "Ich bin bereit",
  },
  "ja-JP": {
    recallLabel: "想起",
    recallDescription: "まず能動的に思い出す。答えを先に見ない",
    explainLabel: "説明",
    explainDescription: "理由と仕組みを説明する",
    predictLabel: "予測",
    predictDescription: "出力・バグ・テスト結果を予測する",
    drillLabel: "ドリル",
    drillDescription: "最小の実装を作る",
    debugLabel: "デバッグ",
    debugDescription: "仮説を立てて検証する",
    transferLabel: "転移",
    transferDescription: "概念を自分のプロジェクトに応用する",
    reviewLabel: "復習",
    reviewDescription: "間隔反復で難易度を自己評価する",
    difficultyEasy: "簡単",
    difficultyMedium: "普通",
    difficultyHard: "難しい",
    hintTypeMinimal: "最小",
    hintTypeStructural: "構造",
    hintTypeExample: "例",
    hintTypeAnswer: "答え",
    whyNow: "なぜ今",
    yourTask: "あなたのタスク",
    hint: "ヒント",
    needHint: "ヒントが必要ですか？",
    submitAnswer: "回答を提出",
    rateYourself: "自分を採点",
    ratingAgain: "もう一度",
    ratingHard: "難しい",
    ratingGood: "良い",
    ratingEasy: "簡単",
    nextCard: "次のカード",
    skip: "スキップ",
    passCriteria: "合格基準",
    concepts: "関連概念",
    skipReason: "学習者がスキップ",
    gradeAgainReason: "自己評価：もう一度",
    gradeHardReason: "自己評価：難しい",
    gradeGoodReason: "自己評価：良い",
    gradeEasyReason: "自己評価：簡単すぎる",
    greetingAttempt: "まず回答",
    greetingSubmit: "回答を提出してください",
    greetingRate: "結果を選択",
    greetingDone: "記録済み",
    greetingStartNamed: "このカードを開始",
    greetingStart: "このカードを開始",
    currentHintMarker: "現在",
    moreHints: "ヒントをさらに表示",
    evidencePlaceholder: "回答かコードを書いてください...",
    ratingAgainDescription: "もっと練習が必要",
    ratingHardDescription: "少し難しい",
    ratingGoodDescription: "よく理解できた",
    ratingEasyDescription: "簡単すぎた",
    doneMessage: "このカードは完了しました！",
    readyButton: "準備できました",
  },
  "ko-KR": {
    recallLabel: "회상",
    recallDescription: "먼저 능동적으로 떠올리세요. 답을 먼저 보지 마세요",
    explainLabel: "설명",
    explainDescription: "이유와 원리를 설명하세요",
    predictLabel: "예측",
    predictDescription: "출력, 버그, 테스트 결과를 예측하세요",
    drillLabel: "연습",
    drillDescription: "최소 구현을 만들어 보세요",
    debugLabel: "디버깅",
    debugDescription: "가설을 세우고 검증하세요",
    transferLabel: "전이",
    transferDescription: "개념을 내 프로젝트에 적용하세요",
    reviewLabel: "복습",
    reviewDescription: "간격 반복, 난이도를 스스로 평가하세요",
    difficultyEasy: "쉬움",
    difficultyMedium: "보통",
    difficultyHard: "어려움",
    hintTypeMinimal: "최소",
    hintTypeStructural: "구조",
    hintTypeExample: "예시",
    hintTypeAnswer: "정답",
    whyNow: "왜 지금",
    yourTask: "내 과제",
    hint: "힌트",
    needHint: "힌트가 필요한가요?",
    submitAnswer: "답안 제출",
    rateYourself: "스스로 평가하기",
    ratingAgain: "다시",
    ratingHard: "어려움",
    ratingGood: "좋음",
    ratingEasy: "쉬움",
    nextCard: "다음 카드",
    skip: "건너뛰기",
    passCriteria: "통과 기준",
    concepts: "관련 개념",
    skipReason: "학습자가 건너뜀",
    gradeAgainReason: "자가 평가: 다시",
    gradeHardReason: "자가 평가: 어려움",
    gradeGoodReason: "자가 평가: 좋음",
    gradeEasyReason: "자가 평가: 너무 쉬움",
    greetingAttempt: "먼저 답하기",
    greetingSubmit: "답안을 제출하세요",
    greetingRate: "결과 선택",
    greetingDone: "기록됨",
    greetingStartNamed: "이 카드 시작",
    greetingStart: "이 카드 시작",
    currentHintMarker: "현재",
    moreHints: "힌트 더 보기",
    evidencePlaceholder: "답이나 코드를 적어주세요...",
    ratingAgainDescription: "더 연습이 필요",
    ratingHardDescription: "조금 어려움",
    ratingGoodDescription: "잘 이해함",
    ratingEasyDescription: "너무 쉬움",
    doneMessage: "이 카드를 완료했어요!",
    readyButton: "준비됐어요",
  },
  "pt-BR": {
    recallLabel: "Evocação",
    recallDescription: "Lembre ativamente, não olhe a resposta antes",
    explainLabel: "Explicar",
    explainDescription: "Explique o porquê e o como",
    predictLabel: "Prever",
    predictDescription: "Preveja a saída, o bug ou o resultado do teste",
    drillLabel: "Prática",
    drillDescription: "Crie uma implementação mínima",
    debugLabel: "Depurar",
    debugDescription: "Formule hipóteses e verifique",
    transferLabel: "Transferir",
    transferDescription: "Aplique o conceito ao seu projeto",
    reviewLabel: "Revisar",
    reviewDescription: "Repetição espaçada, avalie a dificuldade você mesmo",
    difficultyEasy: "Fácil",
    difficultyMedium: "Médio",
    difficultyHard: "Difícil",
    hintTypeMinimal: "Mínima",
    hintTypeStructural: "Estrutural",
    hintTypeExample: "Exemplo",
    hintTypeAnswer: "Resposta",
    whyNow: "Por que agora",
    yourTask: "Sua tarefa",
    hint: "Dica",
    needHint: "Precisa de uma dica?",
    submitAnswer: "Enviar resposta",
    rateYourself: "Avalie-se",
    ratingAgain: "De novo",
    ratingHard: "Difícil",
    ratingGood: "Bom",
    ratingEasy: "Fácil",
    nextCard: "Próximo cartão",
    skip: "Pular",
    passCriteria: "Critérios de aprovação",
    concepts: "Conceitos",
    skipReason: "Pulado pelo aprendiz",
    gradeAgainReason: "Autoavaliação: de novo",
    gradeHardReason: "Autoavaliação: difícil",
    gradeGoodReason: "Autoavaliação: bom",
    gradeEasyReason: "Autoavaliação: fácil demais",
    greetingAttempt: "Responda primeiro",
    greetingSubmit: "Envie sua resposta",
    greetingRate: "Escolha o resultado",
    greetingDone: "Registrado",
    greetingStartNamed: "comece este cartão",
    greetingStart: "Comece este cartão",
    currentHintMarker: "atual",
    moreHints: "Mais dicas",
    evidencePlaceholder: "Escreva sua resposta ou código...",
    ratingAgainDescription: "Precisa de mais prática",
    ratingHardDescription: "Um pouco difícil",
    ratingGoodDescription: "Bom domínio",
    ratingEasyDescription: "Fácil demais",
    doneMessage: "Cartão concluído!",
    readyButton: "Estou pronto",
  },
};

function trainingCardPanelText(language: ComposerLanguage, key: TrainingCardPanelCopyKey): string {
  return trainingCardPanelTextCopy[language]?.[key] ?? trainingCardPanelTextCopy["en-US"][key];
}

/**
 * Get card type metadata
 */
function getCardTypeInfo(
  type: CardType,
  language: ComposerLanguage
): { label: string; icon: string; description: string } {
  const info: Record<CardType, { label: string; icon: string; description: string }> = {
    recall: {
      label: trainingCardPanelText(language, "recallLabel"),
      icon: "R",
      description: trainingCardPanelText(language, "recallDescription"),
    },
    explain: {
      label: trainingCardPanelText(language, "explainLabel"),
      icon: "E",
      description: trainingCardPanelText(language, "explainDescription"),
    },
    predict: {
      label: trainingCardPanelText(language, "predictLabel"),
      icon: "P",
      description: trainingCardPanelText(language, "predictDescription"),
    },
    drill: {
      label: trainingCardPanelText(language, "drillLabel"),
      icon: "D",
      description: trainingCardPanelText(language, "drillDescription"),
    },
    debug: {
      label: trainingCardPanelText(language, "debugLabel"),
      icon: "B",
      description: trainingCardPanelText(language, "debugDescription"),
    },
    transfer: {
      label: trainingCardPanelText(language, "transferLabel"),
      icon: "T",
      description: trainingCardPanelText(language, "transferDescription"),
    },
    review: {
      label: trainingCardPanelText(language, "reviewLabel"),
      icon: "V",
      description: trainingCardPanelText(language, "reviewDescription"),
    },
  };
  return info[type];
}

/**
 * Get difficulty label
 */
function getDifficultyInfo(
  difficulty: "easy" | "medium" | "hard",
  language: ComposerLanguage
): { label: string } {
  const info: Record<"easy" | "medium" | "hard", { label: string }> = {
    easy: {
      label: trainingCardPanelText(language, "difficultyEasy"),
    },
    medium: {
      label: trainingCardPanelText(language, "difficultyMedium"),
    },
    hard: {
      label: trainingCardPanelText(language, "difficultyHard"),
    },
  };
  return info[difficulty];
}

/**
 * Get hint type label
 */
function getHintTypeInfo(
  type: TrainingCardData["hints"][0]["type"],
  language: ComposerLanguage
): { label: string } {
  const info: Record<TrainingCardData["hints"][0]["type"], { label: string }> = {
    minimal: {
      label: trainingCardPanelText(language, "hintTypeMinimal"),
    },
    structural: {
      label: trainingCardPanelText(language, "hintTypeStructural"),
    },
    example: {
      label: trainingCardPanelText(language, "hintTypeExample"),
    },
    answer: {
      label: trainingCardPanelText(language, "hintTypeAnswer"),
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
  const whyNowLabel = trainingCardPanelText(language, "whyNow");
  const yourTaskLabel = trainingCardPanelText(language, "yourTask");
  const hintLabel = trainingCardPanelText(language, "hint");
  const needHintLabel = trainingCardPanelText(language, "needHint");
  const submitEvidenceLabel = trainingCardPanelText(language, "submitAnswer");
  const rateYourselfLabel = trainingCardPanelText(language, "rateYourself");
  const againLabel = trainingCardPanelText(language, "ratingAgain");
  const hardLabel = trainingCardPanelText(language, "ratingHard");
  const goodLabel = trainingCardPanelText(language, "ratingGood");
  const easyLabel = trainingCardPanelText(language, "ratingEasy");
  const nextCardLabel = trainingCardPanelText(language, "nextCard");
  const skipLabel = trainingCardPanelText(language, "skip");
  const passCriteriaLabel = trainingCardPanelText(language, "passCriteria");
  const conceptsLabel = trainingCardPanelText(language, "concepts");
  const canTransitionCardStatus = Boolean(card.id && onCardStatusTransition);

  const handleSkip = () => {
    if (!canTransitionCardStatus || !onCardStatusTransition) {
      return;
    }
    onCardStatusTransition(
      card.id,
      "skipped",
      trainingCardPanelText(language, "skipReason"),
    );
  };

  const handleRate = (nextRating: CardRating) => {
    if (!canTransitionCardStatus || !onCardStatusTransition) {
      return;
    }
    const reason =
      nextRating === "again"
        ? trainingCardPanelText(language, "gradeAgainReason")
        : nextRating === "hard"
          ? trainingCardPanelText(language, "gradeHardReason")
          : nextRating === "good"
            ? trainingCardPanelText(language, "gradeGoodReason")
            : trainingCardPanelText(language, "gradeEasyReason");
    onCardStatusTransition(card.id, "reviewed", reason);
  };

  // Greeting based on state
  const getGreeting = () => {
    if (isAttempting) {
      return trainingCardPanelText(language, "greetingAttempt");
    }
    if (isEvidencing) {
      return learnerName
        ? `${learnerName}, ${trainingCardPanelText(language, "greetingSubmit")}`
        : trainingCardPanelText(language, "greetingSubmit");
    }
    if (isRating) {
      return trainingCardPanelText(language, "greetingRate");
    }
    if (isDone) {
      return trainingCardPanelText(language, "greetingDone");
    }
    return learnerName
      ? `${learnerName}, ${trainingCardPanelText(language, "greetingStartNamed")}`
      : trainingCardPanelText(language, "greetingStart");
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
                        <span className="hint-current">({trainingCardPanelText(language, "currentHintMarker")})</span>
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
                  + {trainingCardPanelText(language, "moreHints")}
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
            placeholder={trainingCardPanelText(language, "evidencePlaceholder")}
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
                {trainingCardPanelText(language, "ratingAgainDescription")}
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
                {trainingCardPanelText(language, "ratingHardDescription")}
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
                {trainingCardPanelText(language, "ratingGoodDescription")}
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
                {trainingCardPanelText(language, "ratingEasyDescription")}
              </span>
            </button>
          </div>
        </div>
      )}

      {/* Done state */}
      {isDone && (
        <div className="card-section card-done">
          <div className="done-message">
            {trainingCardPanelText(language, "doneMessage")}
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
            {trainingCardPanelText(language, "readyButton")}
          </button>
        )}
      </div>
    </div>
  );
};
