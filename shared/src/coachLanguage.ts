import type { ComposerLanguage } from "./types";
import {
  compactNarrowSidebarList,
  compactNarrowSidebarText,
  normalizeNarrowSidebarCopy,
  summarizeNarrowSidebarLead,
} from "./trainingCardCopy";

export interface CoachReturnCopy {
  title?: string;
  detail?: string;
  summaryLines: string[];
}

export interface WaitingCoachJudgmentCopy {
  title: string;
  summary?: string;
}

export interface PlanCandidateReasonCopy {
  summary?: string;
  line?: string;
}

export interface TrainingNextHopCopy {
  title?: string;
  summary?: string;
  detail?: string;
}

function pickFirst(...values: Array<string | undefined>): string | undefined {
  for (const value of values) {
    if (value) {
      return value;
    }
  }
  return undefined;
}

export function normalizeCoachReturnCopy(
  language: ComposerLanguage,
  input: {
    title?: string;
    detail?: string;
    summaryLines?: readonly string[];
  },
): CoachReturnCopy {
  const title =
    compactNarrowSidebarText(language, input.title, { maxLength: 54 }) ??
    normalizeNarrowSidebarCopy(language, input.title);
  const detail = summarizeNarrowSidebarLead(language, input.detail, { maxLength: 86 });
  const summaryLines = compactNarrowSidebarList(language, input.summaryLines, {
    maxItems: 3,
    maxLength: 72,
  });
  return { title, detail, summaryLines };
}

export function summarizeWaitingCoachJudgment(
  language: ComposerLanguage,
  input: {
    returnSummary?: string;
    handoffSummary?: string;
  },
): WaitingCoachJudgmentCopy {
  const title = language === "zh-CN" ? "已带回教练" : "Returned to coach";
  const raw = pickFirst(input.returnSummary, input.handoffSummary);
  const summary = summarizeNarrowSidebarLead(
    language,
    raw ??
      (language === "zh-CN"
        ? "等待教练判定下一跳。"
        : "Waiting for the coach to judge the next hop."),
    { maxLength: 96 },
  );
  return { title, summary };
}

export function summarizePlanCandidateReason(
  language: ComposerLanguage,
  reason?: string,
): PlanCandidateReasonCopy {
  const summary = summarizeNarrowSidebarLead(language, reason, { maxLength: 90 });
  return {
    summary,
    line: summary ? `${language === "zh-CN" ? "候选提示" : "Candidate note"}: ${summary}` : undefined,
  };
}

export function summarizeTrainingNextHopCopy(
  language: ComposerLanguage,
  input: {
    title?: string;
    summary?: string;
    nextAfterCompletion?: string;
    whyNow?: string;
    statusReason?: string;
    blockedBy?: string;
    handoffSummary?: string;
    fallbackAction?: string;
  },
): TrainingNextHopCopy {
  const title = compactNarrowSidebarText(
    language,
    pickFirst(input.title, input.summary, input.nextAfterCompletion),
    { maxLength: 54 },
  );
  const summary = compactNarrowSidebarText(
    language,
    pickFirst(input.summary, input.nextAfterCompletion, input.title),
    { maxLength: 54 },
  );
  const detail = summarizeNarrowSidebarLead(
    language,
    pickFirst(
      input.whyNow,
      input.statusReason,
      input.blockedBy,
      input.handoffSummary,
      input.fallbackAction,
    ),
    { maxLength: 88 },
  );
  return { title, summary, detail };
}
