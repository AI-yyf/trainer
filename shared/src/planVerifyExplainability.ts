import type { ComposerLanguage } from "./types";

export interface PlanVerifyAdvanceFsrsSummary {
  reps?: number;
  state?: string;
  stability?: number;
  difficulty?: number;
  intervalDays?: number;
  masteryScore?: number;
}

export interface PlanVerifyAdvanceExplainInput {
  advanced?: boolean;
  what?: string;
  why?: string;
  next?: string;
  fsrs?: PlanVerifyAdvanceFsrsSummary;
}

function compact(value?: string): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  return normalized ? normalized : undefined;
}

function formatFsrsClause(
  language: ComposerLanguage,
  fsrs?: PlanVerifyAdvanceFsrsSummary,
): string | undefined {
  if (!fsrs) {
    return undefined;
  }
  const parts: string[] = [];
  if (typeof fsrs.reps === "number" && Number.isFinite(fsrs.reps)) {
    parts.push(`reps=${fsrs.reps}`);
  }
  const state = compact(fsrs.state);
  if (state) {
    parts.push(`state=${state}`);
  }
  if (typeof fsrs.intervalDays === "number" && Number.isFinite(fsrs.intervalDays)) {
    parts.push(`intervalDays=${fsrs.intervalDays}`);
  }
  if (typeof fsrs.masteryScore === "number" && Number.isFinite(fsrs.masteryScore)) {
    parts.push(`mastery=${fsrs.masteryScore}`);
  }
  if (!parts.length) {
    return undefined;
  }
  return language === "zh-CN" ? `FSRS 写回：${parts.join("，")}` : `FSRS write-back: ${parts.join(", ")}`;
}

/** Short Plan nextStep prefix: advanced vs not-advanced. */
export function planVerifyAdvanceStageLabel(
  language: ComposerLanguage,
  advanced?: boolean,
): string {
  if (advanced === true) {
    return language === "zh-CN" ? "已推进" : "Advanced";
  }
  if (advanced === false) {
    return language === "zh-CN" ? "未推进" : "Not advanced";
  }
  return "";
}

/**
 * Honest post-verify copy: whether the plan stage advanced, why/next, and optional FSRS write-back.
 * Same honesty bar as training-return send-state explainability.
 */
export function describePlanVerifyAdvanceState(
  language: ComposerLanguage,
  input: PlanVerifyAdvanceExplainInput,
): { tone: "info" | "success"; message: string } {
  const what = compact(input.what);
  const why = compact(input.why);
  const next = compact(input.next);
  const fsrsClause = formatFsrsClause(language, input.fsrs);
  const zh = language === "zh-CN";
  const sep = zh ? "" : " ";

  if (input.advanced === true) {
    const bits = [
      zh ? "计划阶段已推进。" : "Plan stage advanced.",
      what,
      why ? (zh ? `原因：${why}` : `Why: ${why}`) : undefined,
      next ? (zh ? `下一步：${next}` : `Next: ${next}`) : undefined,
      fsrsClause,
    ].filter(Boolean);
    return { tone: "success", message: bits.join(sep) };
  }

  if (input.advanced === false) {
    const reason = why ?? what;
    const bits = [
      zh ? "验证已完成，但计划阶段未推进。" : "Verify finished, but the plan stage did not advance.",
      reason ? (zh ? `原因：${reason}` : `Why: ${reason}`) : undefined,
      next ? (zh ? `下一步：${next}` : `Next: ${next}`) : undefined,
      fsrsClause,
    ].filter(Boolean);
    return { tone: "info", message: bits.join(sep) };
  }

  const bits = [
    zh ? "验证结果已更新。" : "Verify result updated.",
    what ?? why,
    next ? (zh ? `下一步：${next}` : `Next: ${next}`) : undefined,
    fsrsClause,
  ].filter(Boolean);
  return { tone: "info", message: bits.join(sep) };
}
