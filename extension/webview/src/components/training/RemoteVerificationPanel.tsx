import { SystemState } from "../../templates/SystemState";
import { VerificationResult } from "../../templates/VerificationResult";
import { COPY } from "../../lib/i18n/segments/trainingInlineText";
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
