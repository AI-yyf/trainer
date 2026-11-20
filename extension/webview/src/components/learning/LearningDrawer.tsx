import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";

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
  open: string;
  /** Labels the subject line of the practice panel, so a card title never
      appears as a stray line. */
  currentCard: string;
  /** The heatmap legend: from "not verified yet" to "repeatedly verified". */
  less: string;
  more: string;
}> = {
  "zh-CN": {
    title: "学习", goal: "当前目标", practice: "到期练习", progress: "成长进度",
    emptyGoal: "还没有正式计划。", emptyPractice: "现在没有到期练习。",
    emptyProgress: "完成一次练习后，这里会出现进度。", due: "{n} 张待复习",
    evidence: "{n} 条证据", open: "打开",
    currentCard: "当前练习：",
    less: "少",
    more: "多",
  },
  "en-US": {
    title: "Learning", goal: "Current goal", practice: "Due practice", progress: "Growth",
    emptyGoal: "No formal plan yet.", emptyPractice: "Nothing is due right now.",
    emptyProgress: "Progress appears after one practice.", due: "{n} due",
    evidence: "{n} evidence", open: "Open",
    currentCard: "Current card:",
    less: "Less",
    more: "More",
  },
  "es-ES": {
    title: "Aprendizaje", goal: "Objetivo actual", practice: "Práctica pendiente", progress: "Progreso",
    emptyGoal: "Aún no hay un plan formal.", emptyPractice: "No hay práctica pendiente.",
    emptyProgress: "El progreso aparece tras una práctica.", due: "{n} pendientes",
    evidence: "{n} evidencias", open: "Abrir",
    currentCard: "Ejercicio actual:",
    less: "Menos",
    more: "Más",
  },
  "fr-FR": {
    title: "Apprentissage", goal: "Objectif actuel", practice: "Pratique à faire", progress: "Progression",
    emptyGoal: "Pas encore de plan formel.", emptyPractice: "Rien à faire pour le moment.",
    emptyProgress: "La progression apparaît après une pratique.", due: "{n} à revoir",
    evidence: "{n} preuves", open: "Ouvrir",
    currentCard: "Exercice actuel :",
    less: "Moins",
    more: "Plus",
  },
  "de-DE": {
    title: "Lernen", goal: "Aktuelles Ziel", practice: "Fällige Übung", progress: "Fortschritt",
    emptyGoal: "Noch kein formeller Plan.", emptyPractice: "Gerade nichts fällig.",
    emptyProgress: "Fortschritt erscheint nach einer Übung.", due: "{n} fällig",
    evidence: "{n} Nachweise", open: "Öffnen",
    currentCard: "Aktuelle Übung:",
    less: "Weniger",
    more: "Mehr",
  },
  "ja-JP": {
    title: "学習", goal: "現在の目標", practice: "期限の練習", progress: "成長",
    emptyGoal: "正式な計画はまだありません。", emptyPractice: "今は期限の練習がありません。",
    emptyProgress: "練習を1回終えると進捗が表示されます。", due: "{n} 件",
    evidence: "{n} 件の証拠", open: "開く",
    currentCard: "現在の練習：",
    less: "少",
    more: "多",
  },
  "ko-KR": {
    title: "학습", goal: "현재 목표", practice: "예정된 연습", progress: "성장",
    emptyGoal: "아직 공식 계획이 없습니다.", emptyPractice: "지금은 예정된 연습이 없습니다.",
    emptyProgress: "연습을 한 번 마치면 진행 상황이 표시됩니다.", due: "{n}개",
    evidence: "증거 {n}개", open: "열기",
    currentCard: "현재 연습:",
    less: "적음",
    more: "많음",
  },
  "pt-BR": {
    title: "Aprendizado", goal: "Objetivo atual", practice: "Prática pendente", progress: "Progresso",
    emptyGoal: "Ainda não há um plano formal.", emptyPractice: "Nada pendente agora.",
    emptyProgress: "O progresso aparece após uma prática.", due: "{n} pendentes",
    evidence: "{n} evidências", open: "Abrir",
    currentCard: "Exercício atual:",
    less: "Menos",
    more: "Mais",
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
            {/* One heatmap: a column per dimension, the filled cells show how far
                the capability has come (a band, never a fake percentage). */}
            <ul className="learning-drawer__heatmap">
              {progress.rows.map((row, columnIndex) => (
                <li key={row.label} className="learning-drawer__heatmap-column">
                  <div
                    className="learning-drawer__heatmap-cells"
                    role="img"
                    data-capability-state={row.stateKey}
                    data-capability-level={Math.min(Math.max(row.level, 0), HEATMAP_LEVELS.length)}
                    aria-label={`${row.label}: ${row.state}, ${format(copy.evidence, row.evidenceCount)}`}
                    title={`${row.label} · ${row.state}`}
                  >
                    {/* The cells fill from the bottom up, like a bar that grows. */}
                    {HEATMAP_LEVELS.map((level) => {
                      const filled = level >= HEATMAP_LEVELS.length - row.level;
                      return (
                        <span
                          key={level}
                          className={`learning-drawer__heatmap-cell${filled ? " is-filled" : ""}`}
                          data-heat-level={filled ? row.level : undefined}
                          style={{ "--heat-delay": `${columnIndex * 60 + (HEATMAP_LEVELS.length - level) * 40}ms` } as CSSProperties}
                        />
                      );
                    })}
                  </div>
                  <span className="learning-drawer__heatmap-label">{row.label}</span>
                  <span className="learning-drawer__heatmap-state">{row.state}</span>
                  <span className="learning-drawer__meta">{format(copy.evidence, row.evidenceCount)}</span>
                </li>
              ))}
            </ul>
            <p className="learning-drawer__heatmap-legend">
              <span>{copy.less}</span>
              <span className="learning-drawer__heatmap-ramp" aria-hidden="true">
                {[0, 1, 2, 3].map((level) => (
                  <span
                    key={level}
                    className={`learning-drawer__heatmap-cell${level > 0 ? " is-filled" : ""}`}
                    data-heat-level={level > 0 ? level : undefined}
                  />
                ))}
              </span>
              <span>{copy.more}</span>
            </p>
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
