import { findSidebarControlCommand, type SidebarControlCommandId } from "./sidebarCommands";

export type SendTarget = "idle" | "local_command" | "trainer";
export type SendIntent =
  | "coach"
  | "task"
  | "review"
  | "plan"
  | "next_task"
  | "local_command";
export type ContextDetailLevel = "focused" | "balanced" | "full";
export type SidebarViewName =
  | "coach"
  | "plan"
  | "resources"
  | "training"
  | "settings";
export type LegacyIntentHint = "task" | "review" | "memory" | "next_task";

export interface SendIntelligenceInput {
  draft: string;
  activeView: SidebarViewName;
  hasResearchProject: boolean;
  activeFile?: string;
  selectionRange?: string;
  relatedFilesCount: number;
  includeCurrentFile: boolean;
  includeSelection: boolean;
  includeDiagnostics: boolean;
  includeRelatedFiles: boolean;
  contextDetail: ContextDetailLevel;
  diagnosticErrors?: number;
  diagnosticWarnings?: number;
  intentHint?: LegacyIntentHint;
}

export interface SendWarning {
  id:
    | "review-needs-file"
    | "review-file-disabled"
    | "selection-enabled-without-selection"
    | "selection-available-but-disabled"
    | "related-enabled-without-files"
    | "related-available-but-disabled"
    | "diagnostics-enabled-without-signals"
    | "review-not-full-context";
  severity: "warning" | "info";
}

export interface SendIntelligence {
  target: SendTarget;
  intent: SendIntent;
  isEmpty: boolean;
  localCommandId?: SidebarControlCommandId;
  draftBody?: string;
  requiresCurrentFile: boolean;
  hasActiveFile: boolean;
  hasSelection: boolean;
  hasRelatedFiles: boolean;
  hasDiagnostics: boolean;
  warnings: SendWarning[];
}

export function analyzeSendIntent(input: SendIntelligenceInput): SendIntelligence {
  const normalizedDraft = input.draft.trim();
  const localCommand = findSidebarControlCommand(normalizedDraft);
  const hasActiveFile = Boolean(input.activeFile);
  const hasSelection = Boolean(input.selectionRange);
  const hasRelatedFiles = input.relatedFilesCount > 0;
  const hasDiagnostics = (input.diagnosticErrors ?? 0) + (input.diagnosticWarnings ?? 0) > 0;

  if (!normalizedDraft) {
    return {
      target: "idle",
      intent: resolveIdleIntent(input),
      isEmpty: true,
      requiresCurrentFile: false,
      hasActiveFile,
      hasSelection,
      hasRelatedFiles,
      hasDiagnostics,
      warnings: [],
    };
  }

  if (localCommand) {
    return {
      target: "local_command",
      intent: "local_command",
      isEmpty: false,
      localCommandId: localCommand.id,
      requiresCurrentFile: false,
      hasActiveFile,
      hasSelection,
      hasRelatedFiles,
      hasDiagnostics,
      warnings: [],
    };
  }

  const resolvedIntent = resolveTrainerIntent(normalizedDraft, input);
  const draftBody = draftBodyForIntent(normalizedDraft, resolvedIntent);
  const requiresCurrentFile = resolvedIntent === "review";

  const warnings: SendWarning[] = [];
  if (requiresCurrentFile && !hasActiveFile) {
    warnings.push({ id: "review-needs-file", severity: "warning" });
  }
  if (requiresCurrentFile && !input.includeCurrentFile) {
    warnings.push({ id: "review-file-disabled", severity: "warning" });
  }
  if (input.includeSelection && !hasSelection) {
    warnings.push({ id: "selection-enabled-without-selection", severity: "info" });
  }
  if (!input.includeSelection && hasSelection) {
    warnings.push({ id: "selection-available-but-disabled", severity: "info" });
  }
  if (input.includeRelatedFiles && !hasRelatedFiles) {
    warnings.push({ id: "related-enabled-without-files", severity: "info" });
  }
  if (!input.includeRelatedFiles && hasRelatedFiles) {
    warnings.push({ id: "related-available-but-disabled", severity: "info" });
  }
  if (input.includeDiagnostics && !hasDiagnostics) {
    warnings.push({ id: "diagnostics-enabled-without-signals", severity: "info" });
  }
  if (resolvedIntent === "review" && input.contextDetail !== "full") {
    warnings.push({ id: "review-not-full-context", severity: "info" });
  }

  return {
    target: "trainer",
    intent: resolvedIntent,
    isEmpty: false,
    draftBody,
    requiresCurrentFile,
    hasActiveFile,
    hasSelection,
    hasRelatedFiles,
    hasDiagnostics,
    warnings,
  };
}

export function shouldAttachCurrentFile(text: string, intent?: SendIntent): boolean {
  if (intent === "review" || intent === "task") {
    return true;
  }

  const normalized = normalizeDraftText(text);
  if (/^\/(?:review|task)\b/i.test(normalized)) {
    return true;
  }

  return matchesAny(normalized, EXPLICIT_CURRENT_FILE_PATTERNS);
}

function resolveTrainerIntent(
  draft: string,
  input: SendIntelligenceInput,
): SendIntent {
  if (/^\/next\b/i.test(draft)) {
    return "next_task";
  }
  if (/^\/plan\b/i.test(draft)) {
    return "coach";
  }
  if (/^\/review\b/i.test(draft)) {
    return "review";
  }
  if (/^\/task\b/i.test(draft)) {
    return "task";
  }
  if (input.intentHint === "next_task") {
    return "next_task";
  }
  if (input.intentHint === "task") {
    return "task";
  }
  if (input.intentHint === "review") {
    return "review";
  }
  if (input.activeView === "coach") {
    const inferredIntent = inferNaturalLanguageIntent(draft);
    if (inferredIntent) {
      return inferredIntent;
    }
  }
  return "coach";
}

function resolveIdleIntent(_input: SendIntelligenceInput): SendIntent {
  return "coach";
}

function draftBodyForIntent(draft: string, intent: SendIntent): string {
  if (intent === "next_task") {
    return draft.replace(/^\/next\b/i, "").trim();
  }
  if (intent === "plan") {
    return draft.replace(/^\/plan\b/i, "").trim();
  }
  if (intent === "coach" && /^\/plan\b/i.test(draft)) {
    return draft.replace(/^\/plan\b/i, "").trim();
  }
  if (intent === "review") {
    return draft.replace(/^\/review\b/i, "").trim();
  }
  if (intent === "task") {
    return draft.replace(/^\/task\b/i, "").trim();
  }
  return draft;
}

function inferNaturalLanguageIntent(draft: string): SendIntent | undefined {
  const normalized = normalizeDraftText(draft);
  if (!normalized) {
    return undefined;
  }

  if (matchesAny(normalized, REVIEW_PATTERNS)) {
    return "review";
  }
  // Next-task language stays in Coach until the learner uses /next or the
  // explicit Next task action. Casual "next" / "continue" must not mint a TaskSpec.
  return undefined;
}

function normalizeDraftText(value: string): string {
  return value.trim().replace(/\s+/g, " ").toLowerCase();
}

function matchesAny(value: string, patterns: Array<RegExp>): boolean {
  return patterns.some((pattern) => pattern.test(value));
}

const REVIEW_PATTERNS = [
  /\b(review|inspect|check|audit|critique|analyze|analyse)\b/i,
  /\blook\s+at\b/i,
  /看看|检查|审查|评审|复盘|帮我看|帮我检查|帮我审查/,
];

const EXPLICIT_CURRENT_FILE_PATTERNS = [
  /\b(?:current|active|this)\s+(?:file|code|implementation)\b/i,
  /\b(?:look|check|inspect|explain|walk\s+me\s+through)\s+(?:the\s+)?(?:(?:current|active|this)\s+)?(?:file|code)\b/i,
  /\b(?:file|code)\s+(?:in|from)\s+(?:the\s+)?editor\b/i,
  /\b(?:the\s+)?(?:file|code)\s+(?:above|below|here)\b/i,
  /\u5f53\u524d(?:\u6587\u4ef6|\u4ee3\u7801|\u51fd\u6570)/,
  /\u8fd9(?:\u4e2a|\u6bb5)?(?:\u6587\u4ef6|\u4ee3\u7801|\u51fd\u6570)/,
  /(?:\u67e5\u770b|\u770b\u770b|\u89e3\u91ca|\u5206\u6790|\u68c0\u67e5)(?:\u4e00\u4e0b)?(?:\u5f53\u524d|\u8fd9(?:\u4e2a|\u6bb5)?)?(?:\u6587\u4ef6|\u4ee3\u7801|\u51fd\u6570)/,
];

