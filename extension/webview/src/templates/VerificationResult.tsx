import type { ReactNode } from "react";
import type { ComposerLanguage, EvaluationCheck } from "../lib/types";
import { DoneIcon } from "../components/icons/inline";
import { templateCopy } from "./templateCopy";

export type VerificationVerdict = "passed" | "failed" | "unknown";
const LABELS: Record<ComposerLanguage, Record<VerificationVerdict, string>> = {
  "zh-CN": { passed: "验证通过", failed: "需要再改一处", unknown: "验证结果待确认" },
  "en-US": { passed: "Verification passed", failed: "One more change needed", unknown: "Verification outcome unknown" },
  "es-ES": { passed: "Verificación superada", failed: "Hace falta otro cambio", unknown: "Resultado de verificación desconocido" },
  "fr-FR": { passed: "Vérification réussie", failed: "Encore une correction", unknown: "Résultat de vérification inconnu" },
  "de-DE": { passed: "Prüfung bestanden", failed: "Eine weitere Änderung nötig", unknown: "Prüfergebnis unbekannt" },
  "ja-JP": { passed: "検証に合格", failed: "もう一か所修正が必要", unknown: "検証結果は未確定" },
  "ko-KR": { passed: "검증 통과", failed: "한 곳 더 수정 필요", unknown: "검증 결과 미확인" },
  "pt-BR": { passed: "Verificação aprovada", failed: "Mais uma correção necessária", unknown: "Resultado da verificação desconhecido" },
};
const STALE_SOURCE: Record<ComposerLanguage, string> = {
  "zh-CN": "资料版本已更新。请从资料库打开最新版并创建新的练习。",
  "en-US": "The source has changed. Open the latest version in the library and create a new practice.",
  "es-ES": "La fuente ha cambiado. Abre la última versión en la biblioteca y crea una práctica nueva.",
  "fr-FR": "La source a changé. Ouvrez la dernière version dans la bibliothèque et créez un nouvel exercice.",
  "de-DE": "Die Quelle hat sich geändert. Öffne die neueste Version in der Bibliothek und erstelle eine neue Übung.",
  "ja-JP": "資料が更新されました。資料庫で最新版を開き、新しい練習を作成してください。",
  "ko-KR": "자료가 변경되었습니다. 자료실에서 최신 버전을 열고 새 연습을 만드세요.",
  "pt-BR": "A fonte mudou. Abra a versão mais recente na biblioteca e crie uma nova prática.",
};

/** Counts are derived only from actual supplied checks; absent facts stay absent. */
export function VerificationResult({ language, verdict, summary, checks, details, staleResource }: {
  language: ComposerLanguage;
  verdict: VerificationVerdict;
  summary?: string;
  checks?: EvaluationCheck[];
  details?: ReactNode;
  staleResource?: boolean;
}) {
  const passed = checks?.filter((check) => check.status === "pass").length;
  const visibleSummary = staleResource ? STALE_SOURCE[language] : summary;
  return <section className="template-verification" data-template="VerificationResult" data-verdict={verdict} role="status">
    <h3>{verdict === "passed" ? <DoneIcon size={14} /> : null}{LABELS[language][verdict]}</h3>
    {checks?.length ? <p className="template-metadata">{passed} / {checks.length}</p> : null}
    {visibleSummary ? <p>{visibleSummary}</p> : null}
    {checks?.length ? <ul>{checks.map((check) => <li key={check.id} data-check-status={check.status}>{check.label}{check.status === "fail" && check.detail ? <p>{check.detail}</p> : null}</li>)}</ul> : null}
    {details ? <details className="template-disclosure"><summary>{templateCopy[language].evidence}</summary><div>{details}</div></details> : null}
  </section>;
}
