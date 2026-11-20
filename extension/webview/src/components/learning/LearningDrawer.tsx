import type { ReactNode } from "react";
import { useEffect, useRef } from "react";

import type { LearningProgressAchievement } from "../../lib/learningSummary";
import type { ComposerLanguage, LearningSection } from "../../lib/types";

const COPY: Record<ComposerLanguage, {
  title: string;
  goal: string;
  practice: string;
  progress: string;
  emptyGoal: string;
  emptyPractice: string;
  emptyProgress: string;
  due: string;
  evidence: string;
  totalChecks: string;
  open: string;
  /** Labels the subject line of the practice panel, so a card title never
      appears as a stray line. */
  currentCard: string;
}> = {
  "zh-CN": {
    title: "学习", goal: "当前目标", practice: "到期练习", progress: "会了吗",
    emptyGoal: "还没有正式计划。", emptyPractice: "现在没有到期练习。",
    emptyProgress: "动手完成一次练习后，这里会记录你的掌握情况。", due: "{n} 张待复习",
    evidence: "{n} 次", totalChecks: "实测 {n} 次", open: "打开",
    currentCard: "当前练习：",
  },
  "en-US": {
    title: "Learning", goal: "Current goal", practice: "Due practice", progress: "Mastery",
    emptyGoal: "No formal plan yet.", emptyPractice: "Nothing is due right now.",
    emptyProgress: "Complete one practice to see what's solid.", due: "{n} due",
    evidence: "{n}×", totalChecks: "{n} checks", open: "Open",
    currentCard: "Current card:",
  },
  "es-ES": {
    title: "Aprendizaje", goal: "Objetivo actual", practice: "Práctica pendiente", progress: "Dominio",
    emptyGoal: "Aún no hay un plan formal.", emptyPractice: "No hay práctica pendiente.",
    emptyProgress: "El progreso aparece tras una práctica.", due: "{n} pendientes",
    evidence: "{n}×", totalChecks: "{n} pruebas", open: "Abrir",
    currentCard: "Ejercicio actual:",
  },
  "fr-FR": {
    title: "Apprentissage", goal: "Objectif actuel", practice: "Pratique à faire", progress: "Maîtrise",
    emptyGoal: "Pas encore de plan formel.", emptyPractice: "Rien à faire pour le moment.",
    emptyProgress: "La progression apparaît après une pratique.", due: "{n} à revoir",
    evidence: "{n}×", totalChecks: "{n} vérif.", open: "Ouvrir",
    currentCard: "Exercice actuel :",
  },
  "de-DE": {
    title: "Lernen", goal: "Aktuelles Ziel", practice: "Fällige Übung", progress: "Beherrschung",
    emptyGoal: "Noch kein formeller Plan.", emptyPractice: "Gerade nichts fällig.",
    emptyProgress: "Fortschritt erscheint nach einer Übung.", due: "{n} fällig",
    evidence: "{n}×", totalChecks: "{n} Prüf.", open: "Öffnen",
    currentCard: "Aktuelle Übung:",
  },
  "ja-JP": {
    title: "学習", goal: "現在の目標", practice: "期限の練習", progress: "定着度",
    emptyGoal: "正式な計画はまだありません。", emptyPractice: "今は期限の練習がありません。",
    emptyProgress: "練習を1回終えると進捗が表示されます。", due: "{n} 件",
    evidence: "{n} 回", totalChecks: "実測 {n} 回", open: "開く",
    currentCard: "現在の練習：",
  },
  "ko-KR": {
    title: "학습", goal: "현재 목표", practice: "예정된 연습", progress: "숙련도",
    emptyGoal: "아직 공식 계획이 없습니다.", emptyPractice: "지금은 예정된 연습이 없습니다.",
    emptyProgress: "연습을 한 번 마치면 진행 상황이 표시됩니다.", due: "{n}개",
    evidence: "{n}회", totalChecks: "검증 {n}회", open: "열기",
    currentCard: "현재 연습:",
  },
  "pt-BR": {
    title: "Aprendizado", goal: "Objetivo atual", practice: "Prática pendente", progress: "Domínio",
    emptyGoal: "Ainda não há um plano formal.", emptyPractice: "Nada pendente agora.",
    emptyProgress: "O progresso aparece após uma prática.", due: "{n} pendentes",
    evidence: "{n}×", totalChecks: "{n} testes", open: "Abrir",
    currentCard: "Exercício atual:",
  },
};

export interface LearningDrawerGoal {
  title?: string;
  step?: string;
  status?: string;
  actionLabel?: string;
  onAction?: () => void;
  /**
   * The governed plan card. It renders inside this section so the goal is
   * never a separate destination — the drawer is the only learning surface.
   */
  detail?: ReactNode;
  /** A notice scoped to the plan surface (revision conflict, plan gate). */
  notice?: ReactNode;
  /**
   * Secondary goal controls (pause / resume / end an active goal). Goal state
   * belongs to learning, so its controls live here instead of a bar above the
   * composer.
   */
  controls?: ReactNode;
}

export interface LearningDrawerPractice {
  dueCount: number;
  /**
   * The current card's title, when it says something the goal card does not
   * already say. A title that repeats the plan's current step is dropped.
   */
  cardTitle?: string;
  actionLabel?: string;
  onAction?: () => void;
  /**
   * The current card's own reading surface (task details). The drawer is the
   * learning surface while it is open, so the card's facts must be readable
   * here instead of only behind the modal backdrop.
   */
  detail?: ReactNode;
  /**
   * A notice scoped to the practice surface (verification mismatch,
   * undelivered attestation). It belongs to this section, never to a global
   * error banner.
   */
  notice?: ReactNode;
}

export interface LearningDrawerProgressRow {
  label: string;
  state: string;
  /** The band position on the heatmap scale (0 = nothing yet, 3 = repeatedly verified). */
  /** The server projection state the band was drawn from. */
  stateKey?: string;
  level: number;
  evidenceCount: number;
}

/** The heatmap's scale: three cells, from "nothing yet" to "repeatedly verified". */
const HEATMAP_LEVELS = [0, 1, 2];

export interface LearningDrawerProgress {
  rows: LearningDrawerProgressRow[];
  evidenceCount: number;
  achievement?: LearningProgressAchievement;
  actionLabel?: string;
  onAction?: () => void;
}

export interface LearningDrawerProps {
  language: ComposerLanguage;
  section: LearningSection;
  onSectionChange?: (section: LearningSection) => void;
  goal?: LearningDrawerGoal;
  practice?: LearningDrawerPractice;
  progress?: LearningDrawerProgress;
}

function format(template: string, value: number): string {
  return template.replace("{n}", String(value));
}

/**
 * The single learning surface. It is deliberately not a tab set: three
 * compact sections share one scroll, and each section owns at most one action.
 * The requested section only decides where the drawer starts.
 */
export function LearningDrawer({ language, section, onSectionChange, goal, practice, progress }: LearningDrawerProps) {
  const copy = COPY[language];
  const sectionRefs = useRef<Record<LearningSection, HTMLElement | null>>({
    goal: null,
    practice: null,
    progress: null,
  });

  useEffect(() => {
    const target = sectionRefs.current[section];
    target?.scrollIntoView?.({ block: "start" });
  }, [section]);

  const sectionProps = (key: LearningSection) => ({
    id: `learning-drawer-${key}`,
    ref: (node: HTMLElement | null) => { sectionRefs.current[key] = node; },
    "data-learning-section": key,
  });

  return (
    <div className="learning-drawer" data-template="LearningDrawer">
      <header className="learning-drawer__header">
        <h2>{copy.title}</h2>
      </header>

      <section className="learning-drawer__card learning-drawer__card--goal" {...sectionProps("goal")}>
        <header className="learning-drawer__card-header">
          <h3 className="learning-drawer__card-title">{copy.goal}</h3>
        </header>
        <div className="learning-drawer__card-body">
          {goal?.notice}
          {goal?.detail ? (
            // The governed plan card owns the title, the current step and the
            // single primary action for this section.
            <div className="learning-drawer__detail-surface">{goal.detail}</div>
          ) : goal?.title || goal?.step ? (
            <>
              {goal.title ? <strong className="learning-drawer__title">{goal.title}</strong> : null}
              {goal.step ? <p className="learning-drawer__detail">{goal.step}</p> : null}
              {goal.status ? <p className="learning-drawer__meta">{goal.status}</p> : null}
              {goal.actionLabel && goal.onAction ? (
                <button type="button" className="button button--accent" onClick={() => { onSectionChange?.("goal"); goal.onAction?.(); }}>
                  {goal.actionLabel}
                </button>
              ) : null}
            </>
          ) : <p className="learning-drawer__empty">{copy.emptyGoal}</p>}
          {goal?.controls ? <div className="learning-drawer__controls">{goal.controls}</div> : null}
        </div>
      </section>

      <section className="learning-drawer__card learning-drawer__card--practice" {...sectionProps("practice")}>
        <header className="learning-drawer__card-header">
          <h3 className="learning-drawer__card-title">{copy.practice}</h3>
          {practice?.dueCount ? (
            <span className="learning-drawer__card-metric">{format(copy.due, practice.dueCount)}</span>
          ) : null}
        </header>
        <div className="learning-drawer__card-body">
          {practice?.notice}
          {practice?.dueCount || practice?.cardTitle ? null : (
            <p className="learning-drawer__meta">{copy.emptyPractice}</p>
          )}
          {practice?.cardTitle ? (
            <p className="learning-drawer__detail">
              <span className="learning-drawer__detail-label">{copy.currentCard}</span>
              {practice.cardTitle}
            </p>
          ) : null}
          {practice?.detail ? <div className="learning-drawer__detail-surface">{practice.detail}</div> : null}
          {practice?.actionLabel && practice.onAction ? (
            // Secondary: the drawer's one accent action belongs to the goal
            // card, so the practice card only offers a way in.
            <button type="button" className="button button--ghost" onClick={() => { onSectionChange?.("practice"); practice.onAction?.(); }}>
              {practice.actionLabel}
            </button>
          ) : null}
        </div>
      </section>

      <section className="learning-drawer__card learning-drawer__card--progress" {...sectionProps("progress")}>
        <header className="learning-drawer__card-header">
          <h3 className="learning-drawer__card-title">{copy.progress}</h3>
          {progress?.evidenceCount ? (
            <span className="learning-drawer__card-metric">{format(copy.totalChecks, progress.evidenceCount)}</span>
          ) : null}
        </header>
        <div className="learning-drawer__card-body">
        {progress?.rows.length ? (
          <>
            {progress.achievement ? (
              <p
                className="learning-drawer__progress-sentence"
                data-progress-sentence="true"
                data-evidence-id={progress.achievement.evidenceId}
              >
                {progress.achievement.sentence}
              </p>
            ) : null}
            {/* Horizontal 3-step mastery ladder per capability — maps 1:1 to server projection bands without percentages. */}
            <ul className="learning-drawer__mastery-list">
              {progress.rows.map((row) => {
                const clampedLevel = Math.min(Math.max(row.level, 0), HEATMAP_LEVELS.length);
                return (
                  <li
                    key={row.label}
                    className="learning-drawer__mastery-row"
                    data-capability-state={row.stateKey}
                    data-capability-level={clampedLevel}
                  >
                    <span className="learning-drawer__mastery-label">{row.label}</span>
                    <span
                      className="learning-drawer__mastery-track"
                      role="img"
                      aria-label={`${row.label}: ${row.state}${row.evidenceCount > 0 ? `, ${format(copy.evidence, row.evidenceCount)}` : ""}`}
                    >
                      {HEATMAP_LEVELS.map((stepIndex) => {
                        const filled = stepIndex < clampedLevel;
                        return (
                          <span
                            key={stepIndex}
                            className={`learning-drawer__mastery-step${filled ? " is-filled" : ""}`}
                            data-step-level={filled ? clampedLevel : undefined}
                          />
                        );
                      })}
                    </span>
                    <span className="learning-drawer__mastery-status">
                      <span className="learning-drawer__mastery-state">{row.state}</span>
                      {row.evidenceCount > 0 ? (
                        <span className="learning-drawer__mastery-count">
                          {" · "}
                          <span>{format(copy.evidence, row.evidenceCount)}</span>
                        </span>
                      ) : null}
                    </span>
                  </li>
                );
              })}
            </ul>
            {progress.actionLabel && progress.onAction ? (
              <button type="button" className="button button--ghost" onClick={() => { onSectionChange?.("progress"); progress.onAction?.(); }}>
                {progress.actionLabel}
              </button>
            ) : null}
          </>
        ) : <p className="learning-drawer__empty">{copy.emptyProgress}</p>}
        </div>
      </section>
    </div>
  );
}
