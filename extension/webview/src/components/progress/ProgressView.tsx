import { useState } from "react";

import { EvidenceIcon } from "../icons/brand/trainerBrand";
import type { ComposerLanguage } from "../../lib/types";
import type {
  TrainingSkillDimensionState,
  TrainingSkillEvidenceRow,
  TrainingSkillProjection,
} from "../../lib/types";

type DimensionKey = "comprehension" | "implementation" | "debugging" | "transfer";

const DIMENSION_KEYS: DimensionKey[] = ["comprehension", "implementation", "debugging", "transfer"];

const DIMENSION_LABELS: Record<ComposerLanguage, Record<DimensionKey, string>> = {
  "zh-CN": { comprehension: "理解", implementation: "实现", debugging: "调试", transfer: "迁移" },
  "en-US": {
    comprehension: "Comprehension",
    implementation: "Implementation",
    debugging: "Debugging",
    transfer: "Transfer",
  },
  "es-ES": {
    comprehension: "Comprensión",
    implementation: "Implementación",
    debugging: "Depuración",
    transfer: "Transferencia",
  },
  "fr-FR": {
    comprehension: "Compréhension",
    implementation: "Implémentation",
    debugging: "Débogage",
    transfer: "Transfert",
  },
  "de-DE": {
    comprehension: "Verständnis",
    implementation: "Implementierung",
    debugging: "Fehlersuche",
    transfer: "Transfer",
  },
  "ja-JP": {
    comprehension: "理解",
    implementation: "実装",
    debugging: "デバッグ",
    transfer: "転用",
  },
  "ko-KR": {
    comprehension: "이해",
    implementation: "구현",
    debugging: "디버깅",
    transfer: "전이",
  },
  "pt-BR": {
    comprehension: "Compreensão",
    implementation: "Implementação",
    debugging: "Depuração",
    transfer: "Transferência",
  },
};

const STATE_LABELS: Record<ComposerLanguage, Record<TrainingSkillDimensionState["state"], string>> = {
  "zh-CN": {
    not_verified: "还未验证",
    assisted: "有辅助完成",
    independent: "独立完成",
    repeat_verified: "反复验证",
    needs_review: "需要回顾",
  },
  "en-US": {
    not_verified: "Not verified yet",
    assisted: "Completed with hints",
    independent: "Independent",
    repeat_verified: "Repeatedly verified",
    needs_review: "Needs review",
  },
  "es-ES": {
    not_verified: "Aún sin verificar",
    assisted: "Completado con ayudas",
    independent: "Independiente",
    repeat_verified: "Verificado repetidamente",
    needs_review: "Necesita repaso",
  },
  "fr-FR": {
    not_verified: "Pas encore vérifié",
    assisted: "Terminé avec aides",
    independent: "Indépendant",
    repeat_verified: "Vérifié à plusieurs reprises",
    needs_review: "À revoir",
  },
  "de-DE": {
    not_verified: "Noch nicht überprüft",
    assisted: "Mit Hinweisen abgeschlossen",
    independent: "Selbstständig",
    repeat_verified: "Mehrfach überprüft",
    needs_review: "Braucht Wiederholung",
  },
  "ja-JP": {
    not_verified: "まだ検証なし",
    assisted: "ヒント付きで完了",
    independent: "自力で完了",
    repeat_verified: "繰り返し検証済み",
    needs_review: "要復習",
  },
  "ko-KR": {
    not_verified: "아직 검증 안 됨",
    assisted: "힌트로 완료",
    independent: "독립 완료",
    repeat_verified: "반복 검증됨",
    needs_review: "복습 필요",
  },
  "pt-BR": {
    not_verified: "Ainda não verificado",
    assisted: "Concluído com dicas",
    independent: "Independente",
    repeat_verified: "Verificado repetidamente",
    needs_review: "Precisa de revisão",
  },
};

const COPY: Record<
  ComposerLanguage,
  {
    ariaLabel: string;
    title: string;
    updated: (label: string) => string;
    evidenceCount: (count: number) => string;
    noEvidence: string;
    notVerified: string;
    transferNudge: string;
    empty: string;
    startPracticing: string;
    localeTag: string;
    drilldownWhy: string;
    drilldownEmpty: string;
    drilldownNoScenario: string;
    drilldownAssisted: string;
    drilldownIndependent: string;
  }
> = {
  "zh-CN": {
    ariaLabel: "你的成长",
    title: "你的成长",
    updated: (label) => `更新于 ${label}`,
    evidenceCount: (count) => `${count} 次验证通过`,
    noEvidence: "还没有验证记录",
    notVerified: "还未验证",
    transferNudge: "迁移能力还未验证。做一个陌生的练习来检验你真正掌握了吗。",
    empty: "完成一次练习的验证后，这里会显示你在理解、实现、调试和迁移上的真实成长。",
    startPracticing: "去练习",
    localeTag: "zh-CN",
    drilldownWhy: "为什么 Trainer 这样判断：",
    drilldownEmpty: "还没有可展示的证据明细。",
    drilldownNoScenario: "无场景标记",
    drilldownAssisted: "有辅助",
    drilldownIndependent: "独立完成",
  },
  "en-US": {
    ariaLabel: "Your progress",
    title: "Your progress",
    updated: (label) => `Updated ${label}`,
    evidenceCount: (count) => `${count} verification${count === 1 ? "" : "s"} passed`,
    noEvidence: "No verifications yet",
    notVerified: "Not verified yet",
    transferNudge:
      "Transfer hasn't been verified yet. Try an unfamiliar exercise to test your real understanding.",
    empty:
      "Once you verify a practice card, your real growth in comprehension, implementation, debugging, and transfer shows up here.",
    startPracticing: "Start practicing",
    localeTag: "en-US",
    drilldownWhy: "Why Trainer judges it this way:",
    drilldownEmpty: "No evidence detail to show yet.",
    drilldownNoScenario: "No scenario tag",
    drilldownAssisted: "With help",
    drilldownIndependent: "Independent",
  },
  "es-ES": {
    ariaLabel: "Tu progreso",
    title: "Tu progreso",
    updated: (label) => `Actualizado ${label}`,
    evidenceCount: (count) => `${count} verificación${count === 1 ? "" : "es"} superada${count === 1 ? "" : "s"}`,
    noEvidence: "Aún no hay verificaciones",
    notVerified: "Aún sin verificar",
    transferNudge:
      "La transferencia aún no está verificada. Prueba un ejercicio poco familiar para comprobar tu comprensión real.",
    empty:
      "Cuando verifiques una tarjeta de práctica, tu crecimiento real en comprensión, implementación, depuración y transferencia aparecerá aquí.",
    startPracticing: "Empezar a practicar",
    localeTag: "es-ES",
    drilldownWhy: "Por qué Trainer lo evalúa así:",
    drilldownEmpty: "Aún no hay detalle de evidencia.",
    drilldownNoScenario: "Sin escenario",
    drilldownAssisted: "Con ayuda",
    drilldownIndependent: "Independiente",
  },
  "fr-FR": {
    ariaLabel: "Votre progression",
    title: "Votre progression",
    updated: (label) => `Mis à jour ${label}`,
    evidenceCount: (count) => `${count} vérification${count === 1 ? "" : "s"} réussie${count === 1 ? "" : "s"}`,
    noEvidence: "Pas encore de vérifications",
    notVerified: "Pas encore vérifié",
    transferNudge:
      "Le transfert n'est pas encore vérifié. Essayez un exercice inhabituel pour tester votre vraie compréhension.",
    empty:
      "Après la vérification d'une carte d'exercice, votre progression réelle en compréhension, implémentation, débogage et transfert apparaît ici.",
    startPracticing: "Commencer à pratiquer",
    localeTag: "fr-FR",
    drilldownWhy: "Pourquoi Trainer juge ainsi :",
    drilldownEmpty: "Pas encore de détail de preuve.",
    drilldownNoScenario: "Sans scénario",
    drilldownAssisted: "Avec aide",
    drilldownIndependent: "Indépendant",
  },
  "de-DE": {
    ariaLabel: "Dein Fortschritt",
    title: "Dein Fortschritt",
    updated: (label) => `Aktualisiert ${label}`,
    evidenceCount: (count) => `${count} bestandene Überprüfung${count === 1 ? "" : "en"}`,
    noEvidence: "Noch keine Überprüfungen",
    notVerified: "Noch nicht überprüft",
    transferNudge:
      "Transfer ist noch nicht überprüft. Probiere eine ungewohnte Aufgabe, um dein echtes Verständnis zu testen.",
    empty:
      "Sobald du eine Übungskarte überprüfst, erscheint hier dein echtes Wachstum in Verständnis, Implementierung, Fehlersuche und Transfer.",
    startPracticing: "Jetzt üben",
    localeTag: "de-DE",
    drilldownWhy: "Warum Trainer so urteilt:",
    drilldownEmpty: "Noch keine Belegdetails.",
    drilldownNoScenario: "Ohne Szenario",
    drilldownAssisted: "Mit Hilfe",
    drilldownIndependent: "Selbstständig",
  },
  "ja-JP": {
    ariaLabel: "あなたの成長",
    title: "あなたの成長",
    updated: (label) => `${label} 更新`,
    evidenceCount: (count) => `${count} 回の検証に合格`,
    noEvidence: "検証記録はまだありません",
    notVerified: "まだ検証なし",
    transferNudge:
      "転用はまだ検証されていません。見慣れない練習で本当の理解を確かめてみましょう。",
    empty:
      "練習カードを検証すると、理解・実装・デバッグ・転用の本当の成長がここに表示されます。",
    startPracticing: "練習を始める",
    localeTag: "ja-JP",
    drilldownWhy: "Trainer がこう判断した理由:",
    drilldownEmpty: "表示できるエビデンスはまだありません。",
    drilldownNoScenario: "シナリオ記録なし",
    drilldownAssisted: "ヒント付き",
    drilldownIndependent: "自力で完了",
  },
  "ko-KR": {
    ariaLabel: "당신의 성장",
    title: "당신의 성장",
    updated: (label) => `${label} 업데이트`,
    evidenceCount: (count) => `${count}회 검증 통과`,
    noEvidence: "아직 검증 기록이 없습니다",
    notVerified: "아직 검증 안 됨",
    transferNudge:
      "전이는 아직 검증되지 않았습니다. 익숙하지 않은 연습으로 진짜 이해를 확인해 보세요.",
    empty:
      "연습 카드를 검증하면 이해·구현·디버깅·전이에 대한 실제 성장이 여기에 표시됩니다.",
    startPracticing: "연습 시작",
    localeTag: "ko-KR",
    drilldownWhy: "Trainer가 이렇게 판단한 이유:",
    drilldownEmpty: "아직 표시할 증거가 없습니다.",
    drilldownNoScenario: "시나리오 기록 없음",
    drilldownAssisted: "도움 받음",
    drilldownIndependent: "독립 완료",
  },
  "pt-BR": {
    ariaLabel: "Seu progresso",
    title: "Seu progresso",
    updated: (label) => `Atualizado ${label}`,
    evidenceCount: (count) => `${count} verificação${count === 1 ? "" : "es"} aprovada${count === 1 ? "" : "s"}`,
    noEvidence: "Nenhuma verificação ainda",
    notVerified: "Ainda não verificado",
    transferNudge:
      "A transferência ainda não foi verificada. Tente um exercício pouco familiar para testar sua compreensão real.",
    empty:
      "Depois de verificar um cartão de prática, seu crescimento real em compreensão, implementação, depuração e transferência aparece aqui.",
    startPracticing: "Começar a praticar",
    localeTag: "pt-BR",
    drilldownWhy: "Por que o Trainer julga assim:",
    drilldownEmpty: "Ainda sem detalhes de evidência.",
    drilldownNoScenario: "Sem cenário",
    drilldownAssisted: "Com ajuda",
    drilldownIndependent: "Independente",
  },
};

function dimensionState(
  projection: TrainingSkillProjection | undefined,
  key: DimensionKey,
): TrainingSkillDimensionState | undefined {
  return projection?.dimensions?.[key];
}

export interface ProgressViewProps {
  language: ComposerLanguage;
  projection?: TrainingSkillProjection;
  onOpenTraining: () => void;
}

/**
 * §十二: capability presentation. Calm text rows with evidence counts —
 * no score bars, no gamification. Every claim comes from the server-side
 * skill projection; empty state explains what will populate it.
 * §十五: all eight supported languages flow through the label maps —
 * no zh/en binaries in this surface.
 */
export function ProgressView({ language, projection, onOpenTraining }: ProgressViewProps) {
  const copy = COPY[language];
  const [expandedDimension, setExpandedDimension] = useState<DimensionKey | undefined>();
  const hasAnyEvidence = DIMENSION_KEYS.some((key) => {
    const state = dimensionState(projection, key);
    return Boolean(state && (state.verifiedCount ?? 0) > 0);
  });
  const updatedAt = projection?.updatedAt ? new Date(projection.updatedAt) : undefined;
  const updatedLabel =
    updatedAt && !Number.isNaN(updatedAt.getTime())
      ? updatedAt.toLocaleString(copy.localeTag, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "";

  return (
    <section className="progress-view" aria-label={copy.ariaLabel}>
      <header className="progress-view__header">
        <p className="eyebrow">{copy.title}</p>
        {updatedLabel ? (
          <p className="progress-view__updated">{copy.updated(updatedLabel)}</p>
        ) : null}
      </header>
      {hasAnyEvidence ? (
        <ul className="progress-view__dimensions">
          {DIMENSION_KEYS.map((key) => {
            const state = dimensionState(projection, key);
            const count = state?.verifiedCount ?? 0;
            const rows: TrainingSkillEvidenceRow[] = state?.evidence ?? [];
            const expanded = expandedDimension === key && rows.length > 0;
            return (
              <li key={key} className="progress-view__row">
                <button
                  type="button"
                  className="progress-view__row-toggle"
                  aria-expanded={expanded}
                  disabled={rows.length === 0}
                  onClick={() => setExpandedDimension((current) => (current === key ? undefined : key))}
                >
                  <div className="progress-view__row-main">
                    <span className="progress-view__dimension">{DIMENSION_LABELS[language][key]}</span>
                    <span className="progress-view__state">
                      {state ? STATE_LABELS[language][state.state] : copy.notVerified}
                    </span>
                  </div>
                  <span className="progress-view__evidence">
                    {count > 0 ? copy.evidenceCount(count) : copy.noEvidence}
                  </span>
                </button>
                {expanded ? (
                  <div className="progress-view__drilldown">
                    <p className="progress-view__drilldown-why">
                      <EvidenceIcon size={12} />
                      {copy.drilldownWhy}
                    </p>
                    <ul className="progress-view__drilldown-list">
                      {rows.map((row) => {
                        const recordedAt = row.timestamp ? new Date(row.timestamp) : undefined;
                        const day = recordedAt && !Number.isNaN(recordedAt.getTime())
                          ? recordedAt.toLocaleDateString(copy.localeTag)
                          : undefined;
                        const assistance =
                          row.assistanceLevel === "independent"
                            ? copy.drilldownIndependent
                            : copy.drilldownAssisted;
                        return (
                          <li key={row.evidenceId ?? `${day}-${row.scenario ?? ""}`}>
                            <span className="progress-view__drilldown-day">{day ?? ""}</span>
                            <span className="progress-view__drilldown-assistance">{assistance}</span>
                            <span className="progress-view__drilldown-scenario">
                              {row.scenario || copy.drilldownNoScenario}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ) : null}
              </li>
            );
          })}
          {(() => {
            const transfer = dimensionState(projection, "transfer");
            if (transfer && transfer.verifiedCount && transfer.verifiedCount > 0) return null;
            const strongest = DIMENSION_KEYS
              .map((k) => dimensionState(projection, k))
              .filter((s) => s && (s.verifiedCount ?? 0) > 0);
            if (strongest.length < 2) return null;
            return (
              <li className="progress-view__row progress-view__nudge">
                <span className="progress-view__state">{copy.transferNudge}</span>
              </li>
            );
          })()}
        </ul>
      ) : (
        <div className="progress-view__empty">
          <p>{copy.empty}</p>
          <button className="button button--accent" type="button" onClick={onOpenTraining}>
            {copy.startPracticing}
          </button>
        </div>
      )}
    </section>
  );
}
