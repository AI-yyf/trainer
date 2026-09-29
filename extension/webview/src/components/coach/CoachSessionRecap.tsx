import type { ReactNode } from "react";

import type { CoachTurnSummaryView, ComposerLanguage } from "../../lib/types";
import { coachSessionRecapCopy } from "./coachSessionRecapCopy";
import { StatusPill } from "../StatusPill";

export interface CoachSessionRecapProps {
  turn?: CoachTurnSummaryView | null;
  language?: ComposerLanguage;
  isStreaming?: boolean;
  action?: ReactNode;
  className?: string;
}

type TurnTone = "connected" | "pending" | "fail" | "starting";

function localize(language: ComposerLanguage, key: string): string {
  return coachSessionRecapCopy(language, key);
}

function normalize(value: string | undefined): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  return normalized?.length ? normalized : undefined;
}

function turnTone(turn: CoachTurnSummaryView | null | undefined, isStreaming: boolean): TurnTone {
  if (isStreaming) {
    return "pending";
  }
  if (turn?.blocker) {
    return "fail";
  }
  if (turn) {
    return "connected";
  }
  return "starting";
}

function toneLabel(tone: TurnTone, language: ComposerLanguage): string {
  switch (tone) {
    case "fail":
      return localize(language, "受阻");
    case "pending":
      return localize(language, "进行中");
    case "connected":
      return localize(language, "已收口");
    case "starting":
    default:
      return localize(language, "等待");
  }
}

function factLabel(language: ComposerLanguage, kind: "decision" | "blocker" | "nextStep" | "resumeThread"): string {
  switch (kind) {
    case "decision":
      return localize(language, "决策");
    case "blocker":
      return localize(language, "卡点");
    case "nextStep":
      return localize(language, "下一步");
    case "resumeThread":
      return localize(language, "续接");
  }
}

export function CoachSessionRecap({
  turn,
  language = "en-US",
  isStreaming = false,
  action,
  className,
}: CoachSessionRecapProps) {
  const summary = normalize(turn?.summary) ?? normalize(turn?.decision) ?? normalize(turn?.nextStep);
  const blocker = normalize(turn?.blocker);
  const decision = normalize(turn?.decision);
  const nextStep = normalize(turn?.nextStep);
  const resumeThread = normalize(turn?.resumeThread);
  const tone = turnTone(turn, isStreaming);

  const facts = [
    blocker ? { kind: "blocker" as const, value: blocker } : null,
    decision ? { kind: "decision" as const, value: decision } : null,
    nextStep ? { kind: "nextStep" as const, value: nextStep } : null,
    resumeThread ? { kind: "resumeThread" as const, value: resumeThread } : null,
  ].filter((item): item is { kind: "decision" | "blocker" | "nextStep" | "resumeThread"; value: string } => Boolean(item));

  if (!turn && !action) {
    return null;
  }

  return (
    <div className={["coach-turn-recap", className].filter(Boolean).join(" ")}>
      {turn ? (
        <>
          <div className="coach-turn-recap__header">
            <StatusPill tone={tone}>
              {toneLabel(tone, language)}
            </StatusPill>
            <span className="coach-turn-recap__title">
              {localize(language, "本次总结")}
            </span>
          </div>

          {summary ? (
            <p className="coach-turn-recap__summary" title={summary}>
              {summary}
            </p>
          ) : null}

          {facts.length > 0 ? (
            <div className="coach-turn-recap__facts">
              {facts.map((fact) => (
                <div key={`${fact.kind}:${fact.value}`} className={`coach-turn-recap__fact coach-turn-recap__fact--${fact.kind}`}>
                  <span className="coach-turn-recap__fact-label">{factLabel(language, fact.kind)}</span>
                  <strong className="coach-turn-recap__fact-value" title={fact.value}>
                    {fact.value}
                  </strong>
                </div>
              ))}
            </div>
          ) : null}

        </>
      ) : null}

      {action ? <div className="coach-turn-recap__actions">{action}</div> : null}
    </div>
  );
}
