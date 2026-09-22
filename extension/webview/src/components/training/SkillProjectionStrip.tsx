import { useMemo } from "react";
import type { ComposerLanguage, TrainingSkillProjection } from "../../lib/types";

/**
 * Phase-D capability model made visible: the learner's evidence-derived skill
 * states per dimension (comprehension / implementation / debugging / transfer).
 * Rendered from workspace memory via the snapshot — no extra round-trips.
 */

const DIMENSION_ORDER = ["comprehension", "implementation", "debugging", "transfer"] as const;

type SkillDimension = (typeof DIMENSION_ORDER)[number];

const dimensionLabels: Record<ComposerLanguage, Record<SkillDimension, string>> = {
  "zh-CN": { comprehension: "理解", implementation: "实现", debugging: "调试", transfer: "迁移" },
  "en-US": { comprehension: "Comprehension", implementation: "Implementation", debugging: "Debugging", transfer: "Transfer" },
  "es-ES": { comprehension: "Comprensión", implementation: "Implementación", debugging: "Depuración", transfer: "Transferencia" },
  "fr-FR": { comprehension: "Compréhension", implementation: "Implémentation", debugging: "Débogage", transfer: "Transfert" },
  "de-DE": { comprehension: "Verständnis", implementation: "Implementierung", debugging: "Fehlersuche", transfer: "Transfer" },
  "ja-JP": { comprehension: "理解", implementation: "実装", debugging: "デバッグ", transfer: "転移" },
  "ko-KR": { comprehension: "이해", implementation: "구현", debugging: "디버깅", transfer: "전이" },
  "pt-BR": { comprehension: "Compreensão", implementation: "Implementação", debugging: "Depuração", transfer: "Transferência" },
};

const stateLabels: Record<ComposerLanguage, Record<string, string>> = {
  "zh-CN": { not_verified: "未验证", assisted: "需辅助", independent: "可独立", repeat_verified: "已重复验证", needs_review: "需复查" },
  "en-US": { not_verified: "Not verified", assisted: "Needs help", independent: "Independent", repeat_verified: "Repeat verified", needs_review: "Needs review" },
  "es-ES": { not_verified: "Sin verificar", assisted: "Necesita ayuda", independent: "Independiente", repeat_verified: "Verificado repetidamente", needs_review: "Necesita repaso" },
  "fr-FR": { not_verified: "Non vérifié", assisted: "Aide nécessaire", independent: "Indépendant", repeat_verified: "Vérifié à répétition", needs_review: "À revoir" },
  "de-DE": { not_verified: "Nicht verifiziert", assisted: "Hilfe nötig", independent: "Eigenständig", repeat_verified: "Wiederholt verifiziert", needs_review: "Überarbeitung nötig" },
  "ja-JP": { not_verified: "未検証", assisted: "支援が必要", independent: "自力で可能", repeat_verified: "反復検証済み", needs_review: "要復習" },
  "ko-KR": { not_verified: "미검증", assisted: "도움 필요", independent: "독립 수행", repeat_verified: "반복 검증됨", needs_review: "복습 필요" },
  "pt-BR": { not_verified: "Não verificado", assisted: "Precisa de ajuda", independent: "Independente", repeat_verified: "Verificado repetidamente", needs_review: "Precisa de revisão" },
};

const titleLabels: Record<ComposerLanguage, string> = {
  "zh-CN": "技能投影",
  "en-US": "Skill projection",
  "es-ES": "Proyección de habilidades",
  "fr-FR": "Projection des compétences",
  "de-DE": "Fähigkeitsprojektion",
  "ja-JP": "スキル投影",
  "ko-KR": "스킬 프로젝션",
  "pt-BR": "Projeção de habilidades",
};

function labelFor(language: ComposerLanguage, table: Record<ComposerLanguage, Record<string, string>>, key: string, fallbackKey: string): string {
  return table[language]?.[key] ?? table["en-US"]?.[key] ?? fallbackKey;
}

export function useSkillProjectionEntries(projection: TrainingSkillProjection | undefined) {
  return useMemo(() => {
    if (!projection?.dimensions) {
      return [];
    }
    return DIMENSION_ORDER.map((dimension) => ({
      dimension,
      state: projection.dimensions?.[dimension]?.state ?? "not_verified",
      verifiedCount: projection.dimensions?.[dimension]?.verifiedCount ?? 0,
    }));
  }, [projection]);
}

export interface SkillProjectionStripProps {
  language: ComposerLanguage;
  projection: TrainingSkillProjection | undefined;
  /** compact: inline chips for Plan/Coach; full: labelled rows for Training. */
  variant?: "compact" | "full";
}

export function SkillProjectionStrip({ language, projection, variant = "compact" }: SkillProjectionStripProps) {
  const entries = useSkillProjectionEntries(projection);
  if (entries.length === 0) {
    return null;
  }
  const title = titleLabels[language] ?? titleLabels["en-US"];
  return (
    <div
      className="skill-projection"
      data-variant={variant}
      role="status"
      aria-label={title}
    >
      {variant === "full" ? <div className="skill-projection-title">{title}</div> : null}
      <div className="skill-projection-row">
        {entries.map(({ dimension, state, verifiedCount }) => (
          <span
            key={dimension}
            className="skill-projection-chip"
            data-skill-dimension={dimension}
            data-skill-state={state}
            title={`${dimensionLabels[language]?.[dimension] ?? dimension} · ${labelFor(language, stateLabels, state, state)}`}
          >
            <span className="skill-projection-dimension">
              {dimensionLabels[language]?.[dimension] ?? dimension}
            </span>
            <span className="skill-projection-state">
              {labelFor(language, stateLabels, state, state)}
              {variant === "full" && verifiedCount > 0 ? ` · ${verifiedCount}` : ""}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
