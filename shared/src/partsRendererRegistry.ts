/**
 * Typed Parts Registry - Pure TypeScript utility
 *
 * Provides a registry-based rendering system for Trainer message parts.
 * This is the shared/utility version without React dependencies.
 * React components are in extension/webview/src/components/parts/
 *
 * Reference: docs/open-source-fit-and-provider-strategy.md §10
 */

import type { ComposerLanguage } from "./types";
import type {
  TrainerMessagePart,
  TrainerMessagePartType,
  MarkdownPart,
  CodePart,
  DiffPart,
  TablePart,
  CitationPart,
  ToolCallPart,
  ToolResultPart,
  ReasoningPart,
  TrainingCardPart,
  FilePreviewPart,
  ChecklistPart,
  AlertPart,
  PlanUpdatePart,
  TestResultPart,
  MathPart,
  MermaidPart,
} from "./protocol";

/**
 * Render context for part rendering
 */
export interface RenderContext {
  language?: ComposerLanguage;
  onCitationClick?: (resourceId: string, chunkId?: string) => void;
  onFilePreviewClick?: (resourceId: string, path: string) => void;
  onTrainingCardClick?: (cardId: string) => void;
  onToolCallClick?: (callId: string) => void;
}

/**
 * Part renderer function type
 */
export type PartRendererFn<P extends TrainerMessagePart = TrainerMessagePart> = (part: P) => string;

/**
 * Registry entry for a part type
 */
export interface RendererRegistryEntry {
  renderer: PartRendererFn;
  priority: number;
}

/**
 * Parts renderer registry with type-safe registration
 */
export class PartsRendererRegistry {
  private _entries: Map<TrainerMessagePartType, RendererRegistryEntry> = new Map();

  register<P extends TrainerMessagePart>(
    type: P["type"],
    renderer: PartRendererFn<P>,
    options?: { priority?: number },
  ): void {
    this._entries.set(type, {
      renderer: renderer as PartRendererFn,
      priority: options?.priority ?? 100,
    });
  }

  getRenderer(type: TrainerMessagePartType): PartRendererFn | null {
    const entry = this._entries.get(type);
    return entry?.renderer ?? null;
  }

  getAllRendererTypes(): TrainerMessagePartType[] {
    return Array.from(this._entries.keys());
  }
}

// Singleton registry instance
let _registry: PartsRendererRegistry | null = null;

export function getPartsRendererRegistry(): PartsRendererRegistry {
  if (!_registry) {
    _registry = new PartsRendererRegistry();
    _registerDefaultRenderers(_registry);
  }
  return _registry;
}

export function resetPartsRendererRegistry(): void {
  _registry = null;
}

/**
 * Register default HTML-based renderers
 */
function _registerDefaultRenderers(registry: PartsRendererRegistry): void {
  registry.register<MarkdownPart>("markdown", (part) =>
    `<div class="trainer-markdown">${escapeHtml(part.content)}</div>`
  );

  registry.register<CodePart>("code", (part) => {
    const langClass = part.language ? `language-${part.language}` : "";
    return `<pre class="trainer-code-block ${langClass}"><code>${escapeHtml(part.code)}</code></pre>`;
  });

  registry.register<DiffPart>("diff", (part) => {
    const lines = escapeHtml(part.patch).split("\n");
    const highlighted = lines.map((line) => {
      if (line.startsWith("+")) return `<span class="diff-line diff-added">${line}</span>`;
      if (line.startsWith("-")) return `<span class="diff-line diff-removed">${line}</span>`;
      if (line.startsWith("@@")) return `<span class="diff-line diff-hunk-header">${line}</span>`;
      return `<span class="diff-line">${line}</span>`;
    }).join("\n");
    return `<pre class="trainer-diff-block"><code>${highlighted}</code></pre>`;
  });

  registry.register<TablePart>("table", (part) => {
    const headerRow = part.columns.map((col) => `<th>${escapeHtml(col)}</th>`).join("");
    const dataRows = part.rows.map((row) => {
      const cells = row.map((cell) => `<td>${escapeHtml(String(cell ?? ""))}</td>`).join("");
      return `<tr>${cells}</tr>`;
    }).join("");
    return `<div class="trainer-table-wrapper"><table class="trainer-table"><thead><tr>${headerRow}</tr></thead><tbody>${dataRows}</tbody></table></div>`;
  });

  registry.register<CitationPart>("citation", (part) => {
    const scoreText = part.trustScore != null ? `${Math.round(part.trustScore * 100)}%` : "";
    return `<div class="trainer-citation" data-resource-id="${escapeHtml(part.resourceId)}">
      <span class="citation-icon">📄</span>
      <div class="citation-content">
        <span class="citation-label">${escapeHtml(part.label)}</span>
        ${part.title ? `<span class="citation-title">${escapeHtml(part.title)}</span>` : ""}
        ${part.source ? `<span class="citation-source">${escapeHtml(part.source)}</span>` : ""}
        ${scoreText ? `<span class="citation-trust">${scoreText}</span>` : ""}
      </div>
    </div>`;
  });

  registry.register<ToolCallPart>("tool_call", (part) => {
    const statusIcon = part.status === "pending" ? "⏳" : part.status === "called" ? "🔧" : "⚠️";
    return `<div class="trainer-tool-call" data-call-id="${escapeHtml(part.id)}">
      <div class="tool-call-header">
        <span class="tool-status-icon">${statusIcon}</span>
        <span class="tool-name">${escapeHtml(part.name)}</span>
        <span class="tool-status">${escapeHtml(part.status)}</span>
      </div>
      <pre class="tool-args"><code>${escapeHtml(JSON.stringify(part.args, null, 2))}</code></pre>
    </div>`;
  });

  registry.register<ToolResultPart>("tool_result", (part) => {
    if (part.error) {
      return `<div class="trainer-tool-result trainer-tool-result-error" data-call-id="${escapeHtml(part.callId)}">
        <span class="tool-error-icon">❌</span>
        <span class="tool-error-message">${escapeHtml(part.error)}</span>
      </div>`;
    }
    const resultJson = typeof part.result === "string" ? part.result : JSON.stringify(part.result, null, 2);
    return `<div class="trainer-tool-result" data-call-id="${escapeHtml(part.callId)}">
      <pre class="tool-result"><code>${escapeHtml(resultJson)}</code></pre>
    </div>`;
  });

  registry.register<ReasoningPart>("reasoning", (part) => {
    let hintsHtml = "";
    if (part.hintLadder && part.hintLadder.length > 0) {
      hintsHtml = `<div class="reasoning-hints">
        <span class="hints-label">Hints:</span>
        <ol class="hint-ladder">${part.hintLadder.map((h, i) => `<li class="hint-item">${escapeHtml(h)}</li>`).join("")}</ol>
      </div>`;
    }
    const redactedLabel = part.redacted ? '<span class="reasoning-redacted">[Reasoning hidden]</span>' : "";
    return `<div class="trainer-reasoning">
      <div class="reasoning-summary">${redactedLabel}<span class="reasoning-text">${escapeHtml(part.summary)}</span></div>
      ${hintsHtml}
    </div>`;
  });

  registry.register<TrainingCardPart>("training_card", (part) => {
    const difficultyIcon = part.difficulty === "easy" ? "🟢" : part.difficulty === "medium" ? "🟡" : "🔴";
    const masteryText = part.masteryScore != null ? `${Math.round(part.masteryScore * 100)}%` : "";
    return `<div class="trainer-training-card" data-card-id="${escapeHtml(part.cardId)}">
      <div class="card-header">
        <span class="card-type">${part.cardType === "flash" ? "⚡ Flash" : "🎯 Practice"}</span>
        <span class="card-difficulty">${difficultyIcon} ${part.difficulty || ""}</span>
      </div>
      ${part.title ? `<div class="card-title">${escapeHtml(part.title)}</div>` : ""}
      ${part.focusArea ? `<div class="card-focus">${escapeHtml(part.focusArea)}</div>` : ""}
      ${masteryText ? `<div class="card-metrics"><span class="metric mastery">${masteryText}</span></div>` : ""}
    </div>`;
  });

  registry.register<FilePreviewPart>("file_preview", (part) => {
    const tierIcon = part.previewTier === "rich" ? "✨" : part.previewTier === "converted" ? "📝" : "📋";
    const tierLabel = part.previewTier === "rich" ? "Tier A" : part.previewTier === "converted" ? "Tier B" : "Tier C";
    return `<div class="trainer-file-preview" data-resource-id="${escapeHtml(part.resourceId)}">
      <div class="preview-header">
        <span class="preview-tier">${tierIcon} ${tierLabel}</span>
        ${part.previewKind ? `<span class="preview-kind">${escapeHtml(part.previewKind)}</span>` : ""}
      </div>
      <div class="preview-path">${escapeHtml(part.path)}</div>
    </div>`;
  });

  registry.register<ChecklistPart>("checklist", (part) => {
    const itemHtml = part.items.map((item) =>
      `<li class="checklist-item ${item.done ? "checklist-item-done" : ""}">${item.done ? "☑️" : "☐"} ${escapeHtml(item.label)}</li>`
    ).join("");
    return `<div class="trainer-checklist"><ul class="checklist-items">${itemHtml}</ul></div>`;
  });

  registry.register<AlertPart>("alert", (part) => {
    const levelIcon = part.level === "error" ? "❌" : part.level === "warn" ? "⚠️" : "ℹ️";
    return `<div class="trainer-alert alert-${part.level}">
      <div class="alert-header">
        <span class="alert-icon">${levelIcon}</span>
        <span class="alert-title">${escapeHtml(part.title)}</span>
      </div>
      ${part.detail ? `<div class="alert-detail">${escapeHtml(part.detail)}</div>` : ""}
    </div>`;
  });

  registry.register<PlanUpdatePart>("plan_update", (part) => {
    const changesHtml = part.changes.map((c) => `<div class="plan-change-item">${escapeHtml(JSON.stringify(c))}</div>`).join("");
    return `<div class="trainer-plan-update" data-plan-id="${escapeHtml(part.planId)}">
      <div class="plan-update-header"><span class="plan-icon">📋</span><span class="plan-label">Plan Update</span></div>
      <div class="plan-changes">${changesHtml}</div>
    </div>`;
  });

  registry.register<TestResultPart>("test_result", (part) => {
    const statusIcon = part.status === "pass" ? "✅" : part.status === "fail" ? "❌" : "❓";
    return `<div class="trainer-test-result test-result-${part.status}">
      <div class="test-result-header">
        <span class="test-status-icon">${statusIcon}</span>
        <span class="test-command">${escapeHtml(part.command)}</span>
        <span class="test-status">${escapeHtml(part.status)}</span>
      </div>
      ${part.detail ? `<div class="test-result-detail">${escapeHtml(part.detail)}</div>` : ""}
    </div>`;
  });

  registry.register<MathPart>("math", (part) => {
    const displayClass = part.display ?? false ? "math-display" : "math-inline";
    return `<span class="${displayClass} trainer-math" data-tex="${escapeHtml(part.tex)}">${escapeHtml(part.tex)}</span>`;
  });

  registry.register<MermaidPart>("mermaid", (part) => {
    const diagramId = `mermaid-${Math.random().toString(36).substr(2, 9)}`;
    return `<div class="trainer-mermaid" data-diagram-id="${diagramId}"><pre class="mermaid-source">${escapeHtml(part.source)}</pre></div>`;
  });
}

// =============================================================================
// Utility Functions
// =============================================================================

function escapeHtml(text: string): string {
  const htmlEscapeMap: Record<string, string> = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };
  return text.replace(/[&<>"']/g, (char) => htmlEscapeMap[char] ?? char);
}

/**
 * Get CSS classes for part rendering
 */
export function getPartCssClasses(type: TrainerMessagePartType): string {
  const classMap: Record<TrainerMessagePartType, string> = {
    markdown: "trainer-markdown",
    code: "trainer-code",
    diff: "trainer-diff",
    math: "trainer-math",
    mermaid: "trainer-mermaid",
    table: "trainer-table",
    citation: "trainer-citation",
    tool_call: "trainer-tool-call",
    tool_result: "trainer-tool-result",
    reasoning: "trainer-reasoning",
    coach_visible_status: "trainer-coach-visible-status",
    training_card: "trainer-training-card",
    plan_update: "trainer-plan-update",
    test_result: "trainer-test-result",
    file_preview: "trainer-file-preview",
    checklist: "trainer-checklist",
    alert: "trainer-alert",
  };
  return classMap[type] ?? "trainer-unknown-part";
}

/**
 * Check if a part type supports interactive features
 */
export function isInteractivePart(type: TrainerMessagePartType): boolean {
  const interactiveTypes: TrainerMessagePartType[] = [
    "citation",
    "tool_call",
    "training_card",
    "file_preview",
  ];
  return interactiveTypes.includes(type);
}

/**
 * Get the default collapse behavior for a part type
 */
export function getPartDefaultCollapsed(type: TrainerMessagePartType): boolean {
  const collapsibleTypes: TrainerMessagePartType[] = [
    "tool_call",
    "tool_result",
    "reasoning",
    "file_preview",
  ];
  return collapsibleTypes.includes(type);
}

/**
 * Render a single part to HTML string
 */
export function renderPartToHtml(part: TrainerMessagePart): string {
  const registry = getPartsRendererRegistry();
  const renderer = registry.getRenderer(part.type);
  if (renderer) {
    return renderer(part);
  }
  // Fallback: JSON preview for unknown types
  return `<div class="trainer-unknown-part">
    <div class="unknown-part-header">
      <span class="unknown-icon">❓</span>
      <span class="unknown-type">Unknown part type: ${escapeHtml(part.type)}</span>
    </div>
    <pre class="unknown-part-json"><code>${escapeHtml(JSON.stringify(part, null, 2))}</code></pre>
  </div>`;
}

/**
 * Render multiple parts to HTML string
 */
export function renderPartsToHtml(parts: TrainerMessagePart[]): string {
  return parts.map(renderPartToHtml).join("\n");
}
