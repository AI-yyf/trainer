import type { LearningProgressAchievement,LearningProgressRow } from "../../lib/learningSummary";
import type { ComposerLanguage } from "../../lib/types";

const COPY: Record<ComposerLanguage, { title: string; evidence: string; open: string }> = {
  "zh-CN": { title: "掌握进度", evidence: "已验证 {n} 次", open: "查看详情" },
  "en-US": { title: "Mastery", evidence: "{n} verified", open: "Details" },
  "es-ES": { title: "Dominio", evidence: "{n} verificadas", open: "Detalles" },
  "fr-FR": { title: "Maîtrise", evidence: "{n} vérif.", open: "Détails" },
  "de-DE": { title: "Beherrschung", evidence: "{n} geprüft", open: "Details" },
  "ja-JP": { title: "習得状況", evidence: "検証 {n} 回", open: "詳細" },
  "ko-KR": { title: "숙달 현황", evidence: "검증 {n}회", open: "자세히" },
  "pt-BR": { title: "Domínio", evidence: "{n} verificadas", open: "Detalhes" },
};

export interface InlineProgressCardProps {
  language: ComposerLanguage;
  rows: LearningProgressRow[];
  evidenceCount: number;
  achievement?: LearningProgressAchievement;
  onOpen: () => void;
}

/**
 * The conversation's compact receipt for a completed practice. It leads with a
 * single plain sentence traced to real evidence and hands heatmap drilldown to
 * the learning drawer.
 */
export function InlineProgressCard({
  language,
  rows,
  evidenceCount,
  achievement,
  onOpen,
}: InlineProgressCardProps) {
  const copy = COPY[language];
  const proven = rows.filter((row) => row.evidenceCount > 0);
  if (proven.length === 0 && !achievement) {
    return null;
  }
  return (
    <section className="inline-progress-card" data-inline-progress="true" aria-label={copy.title}>
      <header className="inline-progress-card__header">
        <strong>
          {copy.title}
          {evidenceCount > 0 ? <span className="inline-progress-card__count"> · {copy.evidence.replace("{n}", String(evidenceCount))}</span> : null}
        </strong>
        <button type="button" className="template-back inline-progress-card__open" onClick={onOpen}>
          {copy.open}
        </button>
      </header>
      {achievement ? (
        <p
          className="inline-progress-card__sentence"
          data-progress-sentence="true"
          data-evidence-id={achievement.evidenceId}
        >
          {achievement.sentence}
        </p>
      ) : null}
      {proven.length > 0 ? (
        <ul className="inline-progress-card__rows">
          {proven.map((row) => (
            <li key={row.label}>
              <span>{row.label}</span>
              <strong>{row.state}</strong>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
