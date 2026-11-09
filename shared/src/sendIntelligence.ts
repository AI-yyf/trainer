import { findSidebarControlCommand, type SidebarControlCommandId } from "./sidebarCommands";

export type SendTarget = "idle" | "local_command" | "trainer";
export type SendIntentSource = "explicit" | "inferred" | "none";
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
  | "progress"
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
  /**
   * Whether `intent` came from an explicit user action (slash command, skill
   * button, view control) or natural-language inference. The server treats
   * only explicit sources as permission to start formal practice/plan flows.
   */
  intentSource: SendIntentSource;
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
      intentSource: "none",
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
      intentSource: "explicit",
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
  const draftBody = draftBodyForIntent(normalizedDraft, resolvedIntent.intent);
  const requiresCurrentFile = resolvedIntent.intent === "review";

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
  if (resolvedIntent.intent === "review" && input.contextDetail !== "full") {
    warnings.push({ id: "review-not-full-context", severity: "info" });
  }

  return {
    target: "trainer",
    intent: resolvedIntent.intent,
    intentSource: resolvedIntent.source,
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

const WORKSPACE_FILE_REFERENCE_PATTERN =
  /(?:^|[\s`'"([{])((?:[\w.@-]+\/)*[\w.@-]+\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|go|rs|java|kt|kts|swift|c|cc|cpp|cxx|h|hpp|cs|rb|php|sh|bash|zsh|sql|md|mdx|json|jsonc|toml|ya?ml|txt|ini|cfg))(?=$|[\s`'",)\]}:;])/gi;

/**
 * True when the learner names a concrete workspace file (for example
 * ``queue_lock.py`` or ``src/app.ts``). Such a turn needs the real file, not a
 * guess: Coach enables its verified tool loop so it can read the workspace
 * snapshot before answering.
 */
export function messageReferencesWorkspaceFile(text: string): boolean {
  const normalized = text.trim();
  if (!normalized) {
    return false;
  }
  WORKSPACE_FILE_REFERENCE_PATTERN.lastIndex = 0;
  return WORKSPACE_FILE_REFERENCE_PATTERN.test(normalized);
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
): { intent: SendIntent; source: SendIntentSource } {
  if (/^\/next\b/i.test(draft)) {
    return { intent: "next_task", source: "explicit" };
  }
  if (/^\/plan\b/i.test(draft)) {
    return {
      intent: isExplicitFormalPlanSave(draft.replace(/^\/plan\b/i, "").trim()) ? "plan" : "coach",
      source: "explicit",
    };
  }
  if (/^\/review\b/i.test(draft)) {
    return { intent: "review", source: "explicit" };
  }
  if (/^\/task\b/i.test(draft)) {
    return { intent: "task", source: "explicit" };
  }
  if (input.intentHint === "next_task") {
    return { intent: "next_task", source: "explicit" };
  }
  if (input.intentHint === "task") {
    return { intent: "task", source: "explicit" };
  }
  if (input.intentHint === "review") {
    return { intent: "review", source: "explicit" };
  }
  if (input.activeView === "coach") {
    const inferredIntent = inferNaturalLanguageIntent(draft);
    if (inferredIntent) {
      return { intent: inferredIntent, source: "inferred" };
    }
  }
  return { intent: "coach", source: "none" };
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

  if (isExplicitFormalPlanSave(normalized)) {
    return "plan";
  }

  // Next-task language stays in Coach until the learner uses /next or the
  // explicit Next task action. Casual "next" / "continue" must not mint a TaskSpec.
  return undefined;
}

function isExplicitFormalPlanSave(draft: string): boolean {
  const instruction = draft.split(/[。！？!?\n]/, 1)[0];
  const asksToChangePlan = /^(?:(?:请(?:你)?|帮我|麻烦(?:你)?)\s*)*(?:明确|直接)?(?:重新)?(?:生成|创建|修改|修正|修复|补齐|更新|重写)[^。！？\n]{0,48}计划/u.test(instruction) ||
    /^(?:please\s+)?(?:create|generate|update|revise|fix|rewrite|repair|complete)\b.{0,90}\bplan\b/iu.test(instruction);
  return asksToChangePlan && /保存|落库|存下|\bsave\b/iu.test(instruction);
}

function normalizeDraftText(value: string): string {
  return value.trim().replace(/\s+/g, " ").toLowerCase();
}

function matchesAny(value: string, patterns: Array<RegExp>): boolean {
  return patterns.some((pattern) => pattern.test(value));
}

const EXPLICIT_CURRENT_FILE_PATTERNS = [
  /\b(?:current|active|this)\s+(?:file|code|implementation)\b/i,
  /\b(?:look|check|inspect|explain|walk\s+me\s+through)\s+(?:the\s+)?(?:(?:current|active|this)\s+)?(?:file|code)\b/i,
  /\b(?:file|code)\s+(?:in|from)\s+(?:the\s+)?editor\b/i,
  /\b(?:the\s+)?(?:file|code)\s+(?:above|below|here)\b/i,
  /\u5f53\u524d(?:\u6587\u4ef6|\u4ee3\u7801|\u51fd\u6570)/,
  /\u8fd9(?:\u4e2a|\u6bb5)?(?:\u6587\u4ef6|\u4ee3\u7801|\u51fd\u6570)/,
  /(?:\u67e5\u770b|\u770b\u770b|\u89e3\u91ca|\u5206\u6790|\u68c0\u67e5)(?:\u4e00\u4e0b)?(?:\u5f53\u524d|\u8fd9(?:\u4e2a|\u6bb5)?)?(?:\u6587\u4ef6|\u4ee3\u7801|\u51fd\u6570)/,
];
