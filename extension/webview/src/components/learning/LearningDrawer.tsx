import type { CSSProperties,ReactNode } from "react";
import { useEffect,useRef } from "react";

import { MAX_CAPABILITY_LEVEL,type LearningProgressAchievement } from "../../lib/learningSummary";
import type { ComposerLanguage,LearningSection } from "../../lib/types";

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
  composerHint: string;
}> = {
  "zh-CN": {
    title: "学习", goal: "当前目标", practice: "到期练习", progress: "掌握进度",
    emptyGoal: "尚未制定正式学习计划。", emptyPractice: "当前暂无到期练习。",
    emptyProgress: "完成并验证一次练习后，此处将记录各维度的掌握进度。", due: "{n} 项待复习",
    evidence: "{n} 次", totalChecks: "已验证 {n} 次", open: "打开",
    currentCard: "当前练习：",
    composerHint: "如需查看完整阶段、核查具体验证证据或调整计划，请直接在下方输入框询问教练。",
  },
  "en-US": {
    title: "Learning", goal: "Current goal", practice: "Due practice", progress: "Mastery",
    emptyGoal: "No formal learning plan yet.", emptyPractice: "No due practice items.",
    emptyProgress: "Complete a verified practice to record mastery across dimensions.", due: "{n} due",
    evidence: "{n}×", totalChecks: "{n} verified", open: "Open",
    currentCard: "Current exercise:",
    composerHint: "Ask the coach in the input box below to inspect all stages, review concrete evidence, or adjust your plan.",
  },
  "es-ES": {
    title: "Aprendizaje", goal: "Objetivo actual", practice: "Práctica pendiente", progress: "Dominio",
    emptyGoal: "Aún no hay un plan de aprendizaje formal.", emptyPractice: "No hay práctica pendiente.",
    emptyProgress: "Tras completar una práctica verificada, aquí se registrará el dominio.", due: "{n} pendientes",
    evidence: "{n}×", totalChecks: "{n} verificadas", open: "Abrir",
    currentCard: "Ejercicio actual:",
    composerHint: "Pregunta al entrenador en el cuadro inferior para ver todas las etapas, revisar evidencias o ajustar el plan.",
  },
  "fr-FR": {
    title: "Apprentissage", goal: "Objectif actuel", practice: "Pratique à faire", progress: "Maîtrise",
    emptyGoal: "Aucun plan d'apprentissage formel pour le moment.", emptyPractice: "Aucune pratique à réviser.",
    emptyProgress: "Après une pratique vérifiée, la maîtrise s'affichera ici.", due: "{n} à revoir",
    evidence: "{n}×", totalChecks: "{n} vérif.", open: "Ouvrir",
    currentCard: "Exercice actuel :",
    composerHint: "Utilisez la zone de saisie ci-dessous pour consulter toutes les étapes, vérifier les preuves ou ajuster le plan.",
  },
  "de-DE": {
    title: "Lernen", goal: "Aktuelles Ziel", practice: "Fällige Übung", progress: "Beherrschung",
    emptyGoal: "Noch kein formeller Lernplan vorhanden.", emptyPractice: "Derzeit keine fälligen Übungen.",
    emptyProgress: "Nach einer überprüften Übung wird hier der Fortschritt erfasst.", due: "{n} fällig",
    evidence: "{n}×", totalChecks: "{n} geprüft", open: "Öffnen",
    currentCard: "Aktuelle Übung:",
    composerHint: "Nutzen Sie das Eingabefeld unten, um alle Phasen, konkrete Nachweise oder Planänderungen abzufragen.",
  },
  "ja-JP": {
    title: "学習", goal: "現在の目標", practice: "期限の練習", progress: "習得状況",
    emptyGoal: "正式な学習計画はまだ作成されていません。", emptyPractice: "現在、期限の練習はありません。",
    emptyProgress: "検証済みの練習を完了すると、各領域の習得状況がここに記録されます。", due: "{n} 件",
    evidence: "{n} 回", totalChecks: "検証 {n} 回", open: "開く",
    currentCard: "現在の課題：",
    composerHint: "全段階の確認、具体的な検証根拠の参照、計画の調整は下の入力欄からコーチに質問できます。",
  },
  "ko-KR": {
    title: "학습", goal: "현재 목표", practice: "예정된 연습", progress: "숙달 현황",
    emptyGoal: "아직 공식 학습 계획이 수립되지 않았습니다.", emptyPractice: "현재 예정된 복습 과제가 없습니다.",
    emptyProgress: "검증된 연습을 완료하면 각 영역의 숙달 현황이 여기에 기록됩니다.", due: "{n}개",
    evidence: "{n}회", totalChecks: "검증 {n}회", open: "열기",
    currentCard: "현재 과제:",
    composerHint: "전체 단계, 구체적인 검증 근거 확인 및 계획 조정은 아래 입력창에서 코치에게 바로 질문하세요.",
  },
  "pt-BR": {
    title: "Aprendizado", goal: "Objetivo atual", practice: "Prática pendente", progress: "Domínio",
    emptyGoal: "Ainda não há um plano formal de aprendizado.", emptyPractice: "Nenhuma prática pendente no momento.",
    emptyProgress: "Após concluir uma prática verificada, o domínio será registrado aqui.", due: "{n} pendentes",
    evidence: "{n}×", totalChecks: "{n} verificadas", open: "Abrir",
    currentCard: "Exercício atual:",
    composerHint: "Use a caixa de entrada abaixo para consultar todas as etapas, verificar evidências ou ajustar seu plano.",
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
  /** The band position on the 0..3 capability scale (0 = unverified/needs review, 3 = repeatedly verified). */
  /** The server projection state the band was drawn from. */
  stateKey?: string;
  level: number;
  evidenceCount: number;
}

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
            {/* Single unified multi-segment capability bar mapped 1:1 to server projection bands without percentages. */}
            <div
              className="learning-drawer__mastery-bar"
              role="img"
              data-capability-bar="true"
              style={{ "--capability-count": progress.rows.length } as CSSProperties}
              aria-label={progress.rows
                .map(
                  (row) =>
                    `${row.label}: ${row.state}${
                      row.evidenceCount > 0 ? ` (${format(copy.evidence, row.evidenceCount)})` : ""
                    }`,
                )
                .join("；")}
            >
              {progress.rows.map((row) => {
                const clampedLevel = Math.min(Math.max(row.level, 0), MAX_CAPABILITY_LEVEL);
                return (
                  <span
                    key={row.label}
                    className={`learning-drawer__mastery-segment${clampedLevel > 0 ? " is-filled" : ""}`}
                    data-capability-state={row.stateKey}
                    data-capability-level={clampedLevel}
                    title={`${row.label}：${row.state}`}
                  />
                );
              })}
            </div>
            <ul className="learning-drawer__mastery-list">
              {progress.rows.map((row) => {
                const clampedLevel = Math.min(Math.max(row.level, 0), MAX_CAPABILITY_LEVEL);
                return (
                  <li
                    key={row.label}
                    className="learning-drawer__mastery-row"
                    data-capability-state={row.stateKey}
                    data-capability-level={clampedLevel}
                  >
                    <span className="learning-drawer__mastery-label">{row.label}</span>
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
      <p className="learning-drawer__meta" data-learning-drawer-composer-hint="true">
        {copy.composerHint}
      </p>
    </div>
  );
}
