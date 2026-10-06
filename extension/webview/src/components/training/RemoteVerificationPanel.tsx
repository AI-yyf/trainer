import { SystemState } from "../../templates/SystemState";
import { VerificationResult } from "../../templates/VerificationResult";
import type { ComposerLanguage } from "../../lib/types";

export type RemoteVerificationViewState = {
  running: boolean;
  output: string;
  summary?: string;
  finishedState?:
    | "completed"
    | "cancelled"
    | "timed_out"
    | "spawn_failed"
    | "connection_lost";
  passed?: boolean;
};

const COPY: Record<
  ComposerLanguage,
  {
    running: (remote: string) => string;
    runningLabel: string;
    stop: string;
    passed: string;
    failed: string;
    interrupted: string;
    fallbackRemote: string;
  }
> = {
  "zh-CN": {
    running: (remote) => `正在 ${remote} 验证…`,
    runningLabel: "远程验证运行中",
    stop: "停止",
    passed: "远程验证通过",
    failed: "远程验证未通过",
    interrupted: "远程验证已中断,执行结果未知。",
    fallbackRemote: "远程",
  },
  "en-US": {
    running: (remote) => `Verifying on ${remote}…`,
    runningLabel: "Remote verification running",
    stop: "Stop",
    passed: "Remote verification passed",
    failed: "Remote verification failed",
    interrupted: "Remote verification was interrupted; the outcome is unknown.",
    fallbackRemote: "remote",
  },
  "es-ES": {
    running: (remote) => `Verificando en ${remote}…`,
    runningLabel: "Verificación remota en curso",
    stop: "Detener",
    passed: "Verificación remota superada",
    failed: "Verificación remota fallida",
    interrupted: "La verificación remota se interrumpió; el resultado es desconocido.",
    fallbackRemote: "remoto",
  },
  "fr-FR": {
    running: (remote) => `Vérification sur ${remote}…`,
    runningLabel: "Vérification distante en cours",
    stop: "Arrêter",
    passed: "Vérification distante réussie",
    failed: "Vérification distante échouée",
    interrupted: "La vérification distante a été interrompue ; le résultat est inconnu.",
    fallbackRemote: "distant",
  },
  "de-DE": {
    running: (remote) => `Verifiziere auf ${remote}…`,
    runningLabel: "Remote-Verifizierung läuft",
    stop: "Stoppen",
    passed: "Remote-Verifizierung bestanden",
    failed: "Remote-Verifizierung fehlgeschlagen",
    interrupted: "Remote-Verifizierung wurde unterbrochen; das Ergebnis ist unbekannt.",
    fallbackRemote: "Remote",
  },
  "ja-JP": {
    running: (remote) => `${remote} で検証中…`,
    runningLabel: "リモート検証を実行中",
    stop: "停止",
    passed: "リモート検証に合格",
    failed: "リモート検証は不合格",
    interrupted: "リモート検証が中断されたため、結果は不明です。",
    fallbackRemote: "リモート",
  },
  "ko-KR": {
    running: (remote) => `${remote}에서 검증 중…`,
    runningLabel: "원격 검증 실행 중",
    stop: "중지",
    passed: "원격 검증 통과",
    failed: "원격 검증 실패",
    interrupted: "원격 검증이 중단되어 결과를 알 수 없습니다.",
    fallbackRemote: "원격",
  },
  "pt-BR": {
    running: (remote) => `Verificando em ${remote}…`,
    runningLabel: "Verificação remota em andamento",
    stop: "Parar",
    passed: "Verificação remota aprovada",
    failed: "Verificação remota reprovada",
    interrupted: "A verificação remota foi interrompida; o resultado é desconhecido.",
    fallbackRemote: "remoto",
  },
};

/**
 * §八 streaming remote verification panel (§十五: eight languages, no
 * zh/en binaries). A completed run shows its honest verdict; any
 * interrupted/cancelled/timed-out/disconnected state shows "outcome
 * unknown" and never fabricates a failed result.
 */
export function RemoteVerificationPanel({
  verification,
  remoteName,
  language,
  onStop,
}: {
  verification: RemoteVerificationViewState;
  remoteName?: string;
  language: ComposerLanguage;
  onStop?: () => void;
}) {
  const copy = COPY[language];
  const remote = remoteName || copy.fallbackRemote;
  const output = verification.output ? <pre className="remote-verify-panel__output">{verification.output}</pre> : undefined;
  return verification.running ? <SystemState kind="processing" title={copy.running(remote)}>
    {onStop ? <button type="button" className="template-back" onClick={onStop}>{copy.stop}</button> : null}
    {output ? <details className="template-disclosure"><summary>{remote}</summary>{output}</details> : null}
  </SystemState> : <VerificationResult language={language}
    verdict={verification.finishedState === "completed" ? verification.passed ? "passed" : "failed" : "unknown"}
    summary={verification.summary ?? (verification.finishedState === "completed" ? verification.passed ? copy.passed : copy.failed : copy.interrupted)} details={output} />;
}
