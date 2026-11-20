import type { ComposerLanguage } from "../../lib/types";
import type { LearningProgressRow } from "../../lib/learningSummary";

const COPY: Record<ComposerLanguage, { title: string; evidence: string; open: string }> = {
  "zh-CN": { title: "进度已更新", evidence: "{n} 条证据", open: "查看成长" },
  "en-US": { title: "Progress updated", evidence: "{n} evidence", open: "View growth" },
  "es-ES": { title: "Progreso actualizado", evidence: "{n} evidencias", open: "Ver progreso" },
  "fr-FR": { title: "Progression mise à jour", evidence: "{n} preuves", open: "Voir la progression" },
  "de-DE": { title: "Fortschritt aktualisiert", evidence: "{n} Nachweise", open: "Fortschritt ansehen" },
  "ja-JP": { title: "進捗を更新しました", evidence: "{n} 件の証拠", open: "成長を見る" },
  "ko-KR": { title: "진행 상황 업데이트", evidence: "증거 {n}개", open: "성장 보기" },
  "pt-BR": { title: "Progresso atualizado", evidence: "{n} evidências", open: "Ver progresso" },
};

export interface InlineProgressCardProps {
  language: ComposerLanguage;
  rows: LearningProgressRow[];
  evidenceCount: number;
  onOpen: () => void;
}

/**
 * The conversation's compact receipt for a completed practice. It does not
 * repeat the full growth page; it names the dimensions that now have evidence
 * and hands management to the learning drawer.
 */
export function InlineProgressCard({ language, rows, evidenceCount, onOpen }: InlineProgressCardProps) {
  const copy = COPY[language];
  const proven = rows.filter((row) => row.evidenceCount > 0);
  if (proven.length === 0) {
    return null;
  }
  return (
    <section className="inline-progress-card" data-inline-progress="true" aria-label={copy.title}>
      <header className="inline-progress-card__header">
        <strong>{copy.title}</strong>
        <span>{copy.evidence.replace("{n}", String(evidenceCount))}</span>
      </header>
      <ul className="inline-progress-card__rows">
        {proven.map((row) => (
          <li key={row.label}>
            <span>{row.label}</span>
            <strong>{row.state}</strong>
          </li>
        ))}
      </ul>
      <button type="button" className="button button--ghost inline-progress-card__open" onClick={onOpen}>
        {copy.open}
      </button>
    </section>
  );
}
