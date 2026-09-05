import type { ReactNode } from "react";

import {
  isAuthoritativeAck,
  sanitizeErrorSurface,
  sanitizeErrorSurfaceJson,
  sanitizeErrorSurfaceText,
} from "../../../../../../shared/src/errorSurfaceSanitizer";
import type {
  AlertPart,
  CitationPart,
  ChecklistPart,
  CodePart,
  DiffPart,
  FilePreviewPart,
  MarkdownPart,
  MathPart,
  MermaidPart,
  PlanUpdatePart,
  ReasoningPart,
  TablePart,
  TestResultPart,
  ToolCallPart,
  ToolResultPart,
  TrainerMessagePart,
  TrainerMessagePartType,
  TrainingCardPart,
  ComposerLanguage,
} from "../../../lib/types";
import { StatusPill } from "../../StatusPill";
import { CollapsibleBlock } from "../CollapsibleBlock";
import {
  hasCoachToolResultFailure,
  resolveCoachToolResultCopy,
  summarizeSafeCoachToolResult,
} from "../coachToolResultCopy";
import { MermaidBlock } from "../MermaidBlock";
import { MessageRichContent } from "../MessageRichContent";
import { DiffRenderer } from "./DiffRenderer";
import { FilePreviewRenderer } from "./FilePreviewRenderer";
import { ShikiCodeBlock } from "./ShikiCodeBlock";
import { StructuredTable } from "./StructuredTable";
import { ToolCallRenderer } from "./ToolCallRenderer";

export { DiffRenderer } from "./DiffRenderer";
export type { DiffRendererProps } from "./DiffRenderer";

export { FilePreviewRenderer } from "./FilePreviewRenderer";
export type { FilePreviewRendererProps } from "./FilePreviewRenderer";

export { ToolCallRenderer } from "./ToolCallRenderer";
export type { ToolCallRendererProps } from "./ToolCallRenderer";

export interface PartRenderContext {
  language?: ComposerLanguage;
}

export type PartComponent<T extends TrainerMessagePart> = (props: {
  part: T;
  context?: PartRenderContext;
}) => ReactNode;

export interface PartRegistry {
  markdown: PartComponent<MarkdownPart>;
  code: PartComponent<CodePart>;
  diff: PartComponent<DiffPart>;
  math: PartComponent<MathPart>;
  mermaid: PartComponent<MermaidPart>;
  table: PartComponent<TablePart>;
  citation: PartComponent<CitationPart>;
  tool_call: PartComponent<ToolCallPart>;
  tool_result: PartComponent<ToolResultPart>;
  reasoning: PartComponent<ReasoningPart>;
  training_card: PartComponent<TrainingCardPart>;
  plan_update: PartComponent<PlanUpdatePart>;
  test_result: PartComponent<TestResultPart>;
  file_preview: PartComponent<FilePreviewPart>;
  checklist: PartComponent<ChecklistPart>;
  alert: PartComponent<AlertPart>;
}

function label(language: ComposerLanguage | undefined, zh: string, en: string): string {
  return language === "zh-CN" ? zh : en;
}

function asRecordValue(value: unknown): Record<string, unknown> | undefined {
  if (!value || Array.isArray(value) || typeof value !== "object") {
    return undefined;
  }
  return value as Record<string, unknown>;
}

function asStringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : undefined;
}

function asStringArrayValue(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    .map((item) => item.trim());
}

function asNumberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function formatDateTime(value: string | undefined): string | undefined {
  if (!value) {
    return undefined;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatPercent(value: number | undefined): string | undefined {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return undefined;
  }
  return `${Math.round(value * 100)}%`;
}

function MarkdownPartRenderer({ part, context }: { part: MarkdownPart; context?: PartRenderContext }) {
  return <MessageRichContent body={part.content} language={context?.language ?? "en-US"} />;
}

function CodePartRenderer({ part }: { part: CodePart }) {
  return (
    <div className="message-part message-part--code">
      <div className="code-block-wrapper">
        <div className="code-block-header">
          <span className="code-block-lang">{part.language || "text"}</span>
        </div>
        <ShikiCodeBlock code={part.code} languageId={part.language} />
      </div>
    </div>
  );
}

function DiffPartRenderer({ part }: { part: DiffPart }) {
  return <DiffRenderer part={part} />;
}

function MathPartRenderer({ part }: { part: MathPart }) {
  return (
    <div className="message-render-block message-part message-part--math">
      <span className="eyebrow">{part.display ? "Display math" : "Math"}</span>
      <pre className="message-markdown__code-block">
        <code>{part.tex}</code>
      </pre>
    </div>
  );
}

function MermaidPartRenderer({ part, context }: { part: MermaidPart; context?: PartRenderContext }) {
  return (
    <MermaidBlock
      chart={part.source}
      summaryLabel={label(context?.language, "Diagram", "Diagram")}
      errorLabel={label(context?.language, "Diagram render failed. Showing the raw content instead.", "Diagram render failed. Showing the raw content instead.")}
    />
  );
}

function TablePartRenderer({ part, context }: { part: TablePart; context?: PartRenderContext }) {
  return (
    <div className="message-render-block message-render-block--table message-part message-part--table">
      <StructuredTable
        columns={part.columns}
        rows={part.rows.map((row) =>
          row.map((cell) =>
            typeof cell === "string"
              ? sanitizeErrorSurfaceText(cell, context?.language)
              : sanitizeErrorSurfaceJson(cell, context?.language),
          ),
        )}
        rowCount={part.rows.length}
        columnCount={part.columns.length}
      />
    </div>
  );
}

function CitationPartRenderer({ part, context }: { part: CitationPart; context?: PartRenderContext }) {
  const trustText =
    typeof part.trustScore === "number"
      ? `${label(context?.language, "Trust", "Trust")} ${part.trustScore.toFixed(2)}`
      : "";
  const sourceMeta = [part.sourceType, part.freshness, trustText].filter(Boolean).join(" | ");
  return (
    <div className="message-part message-part--citation">
      <span className="eyebrow">{part.label}</span>
      {part.title && part.title !== part.label ? <p><strong>{part.title}</strong></p> : null}
      <p className="message-part__meta">
        <code>{part.resourceId}</code>
        {part.chunkId ? <span>{` | ${part.chunkId}`}</span> : null}
      </p>
      {part.source ? <p className="message-part__meta">{part.source}</p> : null}
      {sourceMeta ? <p className="message-part__meta">{sourceMeta}</p> : null}
      {part.summary ? <p>{part.summary}</p> : null}
      {part.snippet ? <p>{part.snippet}</p> : null}
      {part.whyItMatters ? (
        <p className="message-part__meta">
          {label(context?.language, "Why it matters: ", "Why it matters: ")}
          {part.whyItMatters}
        </p>
      ) : null}
    </div>
  );
}

function workspaceEventTitle(
  eventType: string | undefined,
  language: ComposerLanguage | undefined,
): string {
  if (eventType === "sandbox_resource_removed") {
    return label(language, "资料删除结果", "Resource delete result");
  }
  if (eventType === "sandbox_resource_synced") {
    return label(language, "资料导入结果", "Resource import result");
  }
  if (eventType === "sandbox_file_written") {
    return label(language, "工作区写入结果", "Workspace write result");
  }
  if (eventType === "sandbox_file_deleted") {
    return label(language, "工作区删除结果", "Workspace delete result");
  }
  if (eventType === "sandbox_file_renamed") {
    return label(language, "工作区重命名结果", "Workspace rename result");
  }
  if (eventType === "sandbox_command_executed") {
    return label(language, "工作区命令结果", "Workspace command result");
  }
  if (eventType === "sandbox_workspace_cleared") {
    return label(language, "工作区清理结果", "Workspace cleanup result");
  }
  return label(language, "Workspace result", "Workspace result");
}

function workspaceEventSummary(
  resultRecord: Record<string, unknown>,
  language: ComposerLanguage | undefined,
): string | undefined {
  const auditNote = asStringValue(resultRecord.auditNote);
  if (auditNote) {
    return auditNote;
  }
  const eventType = asStringValue(resultRecord.eventType);
  const payload = asRecordValue(resultRecord.payload) ?? {};
  const trashCount = Object.keys(asRecordValue(payload.trashed_paths) ?? {}).length;
  if (eventType === "sandbox_resource_removed") {
    if (trashCount > 1) {
      return label(
        language,
        `已把沙箱副本和 ${trashCount - 1} 个派生工件移入当前工作区回收区。`,
        `Moved the sandbox copy and ${trashCount - 1} derived artifact${trashCount - 1 === 1 ? "" : "s"} into the active workspace trash.`,
      );
    }
    return label(
      language,
      "已把受控资料副本移入当前工作区回收区。",
      "Moved the managed resource copy into the active workspace trash.",
    );
  }
  if (eventType === "sandbox_resource_synced") {
    return label(
      language,
      "已把资料同步到当前工作区边界内，后续索引与预览会围绕受控副本展开。",
      "Synced the resource into the active workspace boundary for governed indexing and preview.",
    );
  }
  return undefined;
}

function workspaceEventFacts(
  resultRecord: Record<string, unknown>,
  language: ComposerLanguage | undefined,
): string[] {
  const facts: string[] = [];
  const payload = asRecordValue(resultRecord.payload) ?? {};
  const authority = asRecordValue(resultRecord.authority) ?? {};
  const latestAuthorityOperation = asRecordValue(resultRecord.latestAuthorityOperation) ?? {};
  const checkpointId = asStringValue(payload.checkpoint_id);
  const patchCount = asStringArrayValue(payload.patch).length;
  const trashCount = Object.keys(asRecordValue(payload.trashed_paths) ?? {}).length;
  const permissionLabel = asStringValue(authority.permissionLabel);
  const permissionLevel = asStringValue(authority.permissionLevel);
  const ledgerCount = asNumberValue(authority.ledgerEntryCount);
  const checkpointCount = asNumberValue(authority.checkpointCount);
  const latestOperation = asStringValue(latestAuthorityOperation.operation);
  const latestResult = asStringValue(latestAuthorityOperation.result);

  if (checkpointId) {
    facts.push(label(language, `检查点 ${checkpointId}`, `Checkpoint ${checkpointId}`));
  }
  if (patchCount > 0) {
    facts.push(
      label(
        language,
        `${patchCount} 个 patch 步骤`,
        `${patchCount} patch step${patchCount === 1 ? "" : "s"}`,
      ),
    );
  }
  if (trashCount > 0) {
    facts.push(
      label(
        language,
        `${trashCount} 个回收区落点`,
        `${trashCount} trash target${trashCount === 1 ? "" : "s"}`,
      ),
    );
  }
  if (permissionLabel || permissionLevel) {
    facts.push(
      label(
        language,
        `权限 ${permissionLabel ?? permissionLevel}`,
        `Permission ${permissionLabel ?? permissionLevel}`,
      ),
    );
  }
  if (typeof ledgerCount === "number") {
    facts.push(label(language, `账本 ${ledgerCount}`, `Ledger ${ledgerCount}`));
  }
  if (typeof checkpointCount === "number") {
    facts.push(label(language, `检查点总数 ${checkpointCount}`, `Checkpoints ${checkpointCount}`));
  }
  if (latestOperation && latestResult) {
    facts.push(
      label(
        language,
        `最近操作 ${latestOperation} · ${latestResult}`,
        `Latest op ${latestOperation} · ${latestResult}`,
      ),
    );
  }
  return facts;
}

function workspaceEventDetailLines(resultRecord: Record<string, unknown>): string[] {
  const payload = asRecordValue(resultRecord.payload) ?? {};
  const patchLines = asStringArrayValue(payload.patch);
  if (patchLines.length > 0) {
    return patchLines.slice(0, 5);
  }

  const trashedPaths = asRecordValue(payload.trashed_paths);
  if (trashedPaths) {
    return Object.entries(trashedPaths)
      .filter(
        ([sourcePath, targetPath]) =>
          typeof sourcePath === "string" &&
          sourcePath.trim().length > 0 &&
          typeof targetPath === "string" &&
          targetPath.trim().length > 0,
      )
      .slice(0, 4)
      .map(([sourcePath, targetPath]) => `${sourcePath} -> ${targetPath}`);
  }

  const diffSummary = asStringValue(payload.diff_summary);
  return diffSummary ? [diffSummary] : [];
}

function WorkspaceToolResultRenderer({
  part,
  context,
  resultRecord,
}: {
  part: ToolResultPart;
  context?: PartRenderContext;
  resultRecord: Record<string, unknown>;
}) {
  const hasFailure = hasCoachToolResultFailure(part.error, part.result);
  const acknowledged = !hasFailure && isAuthoritativeAck(part.result);
  const tone = hasFailure ? "fail" : acknowledged ? "pass" : "pending";
  const statusLabel = hasFailure
    ? label(context?.language, "失败", "Failed")
    : acknowledged
      ? label(context?.language, "已确认", "Confirmed")
      : label(context?.language, "待确认", "Waiting");
  const eventType = asStringValue(resultRecord.eventType);
  const authority = asRecordValue(resultRecord.authority) ?? {};
  const workspaceRoot = asStringValue(authority.activeWorkspaceRoot);
  const trashRoot = asStringValue(authority.trashRoot);
  const detailLines = workspaceEventDetailLines(resultRecord);
  const facts = workspaceEventFacts(resultRecord, context?.language);
  const summary = workspaceEventSummary(resultRecord, context?.language);

  return (
    <div className="message-part message-part--tool-result">
      <div className="message-part__header">
        <strong>{workspaceEventTitle(eventType, context?.language)}</strong>
        <StatusPill tone={tone}>{statusLabel}</StatusPill>
      </div>
      <p className="message-part__meta">
        <code>{part.callId}</code>
        {eventType ? <span>{` | ${eventType}`}</span> : null}
      </p>
      {summary ? <p>{summary}</p> : null}
      {workspaceRoot ? (
        <p className="message-part__meta">
          {label(context?.language, "Workspace root: ", "Workspace root: ")}
          <code>{workspaceRoot}</code>
        </p>
      ) : null}
      {trashRoot ? (
        <p className="message-part__meta">
          {label(context?.language, "Trash root: ", "Trash root: ")}
          <code>{trashRoot}</code>
        </p>
      ) : null}
      {facts.length > 0 ? (
        <div className="message-part__facts">
          {facts.map((fact) => (
            <span key={fact} className="message-part__fact-pill">
              {fact}
            </span>
          ))}
        </div>
      ) : null}
      {detailLines.length > 0 ? (
        <details className="message-part__details">
          <summary>{label(context?.language, "详情", "Details")}</summary>
          <div className="message-part__details-body">
            {detailLines.map((line) => (
              <code key={line}>{sanitizeErrorSurfaceText(line, context?.language)}</code>
            ))}
          </div>
        </details>
      ) : null}
      {hasFailure ? (
        <p className="message-part__error">{sanitizeErrorSurfaceText(part.error, context?.language)}</p>
      ) : null}
    </div>
  );
}

function ToolResultPartRenderer({ part, context }: { part: ToolResultPart; context?: PartRenderContext }) {
  const resultRecord = asRecordValue(part.result);
  const looksLikeWorkspaceResult =
    Boolean(resultRecord) &&
    (Boolean(asStringValue(resultRecord?.eventType)) ||
      Boolean(asRecordValue(resultRecord?.authority)) ||
      Boolean(asRecordValue(resultRecord?.latestAuthorityOperation)));
  if (resultRecord && looksLikeWorkspaceResult) {
    return <WorkspaceToolResultRenderer part={part} context={context} resultRecord={resultRecord} />;
  }
  const hasFailure = hasCoachToolResultFailure(part.error, part.result);
  const acknowledged = !hasFailure && isAuthoritativeAck(part.result);
  const tone = hasFailure ? "fail" : acknowledged ? "pass" : "pending";
  const toolCopy = resolveCoachToolResultCopy(context?.language ?? "en-US");
  const safeSummary = summarizeSafeCoachToolResult(part.result, context?.language ?? "en-US");
  const errorSurface = hasFailure
    ? sanitizeErrorSurface(part.error, { language: context?.language })
    : undefined;
  const statusLabel = hasFailure
    ? label(context?.language, "失败", "Failed")
    : acknowledged
      ? label(context?.language, "已确认", "Confirmed")
      : label(context?.language, "待确认", "Waiting");
  return (
    <div className="message-part message-part--tool-result">
      <div className="message-part__header">
        <strong>{label(context?.language, "工具结果", "Tool result")}</strong>
        <StatusPill tone={tone}>{statusLabel}</StatusPill>
      </div>
      <p className="message-part__meta">
        <code>{part.callId}</code>
      </p>
      <p>
        {hasFailure
          ? errorSurface?.message ?? toolCopy.failed
          : acknowledged
            ? safeSummary ?? toolCopy.completed
            : sanitizeErrorSurface(undefined, {
                language: context?.language,
                acknowledged: false,
              }).message}
      </p>
      {hasFailure ? (
        <p className="message-part__error">
          {errorSurface ? `${errorSurface.why} ${errorSurface.next}` : toolCopy.retry}
        </p>
      ) : null}
    </div>
  );
}

function ReasoningPartRenderer({ part, context }: { part: ReasoningPart; context?: PartRenderContext }) {
  const summary = part.redacted
    ? label(context?.language, "Redacted reasoning summary", "Redacted reasoning summary")
    : label(context?.language, "Reasoning summary", "Reasoning summary");
  const sourceChain = part.sourceChain ?? [];
  const hintLadder = part.hintLadder ?? [];
  const verificationSteps = part.verificationSteps ?? [];
  return (
    <CollapsibleBlock
      className="message-part message-part--reasoning"
      summary={summary}
      defaultOpen={!part.redacted}
    >
      <p>{sanitizeErrorSurfaceText(part.summary, context?.language)}</p>
      {part.detail && !part.redacted ? (
        <p className="message-part__meta">{sanitizeErrorSurfaceText(part.detail, context?.language)}</p>
      ) : null}
      {sourceChain.length > 0 ? (
        <div className="message-part__facts" aria-label={label(context?.language, "Source chain", "Source chain")}>
          {sourceChain.map((item) => (
            <span key={item} className="message-part__fact-pill">
              {item}
            </span>
          ))}
        </div>
      ) : null}
      {hintLadder.length > 0 || verificationSteps.length > 0 ? (
        <details className="message-part__details">
          <summary>
            {label(
              context?.language,
              "Hint ladder & verification",
              "Hint ladder & verification",
            )}
          </summary>
          <div className="message-part__details-body">
            {hintLadder.length > 0 ? (
              <p className="message-part__meta">
                {label(context?.language, "Hint ladder", "Hint ladder")}
              </p>
            ) : null}
            {hintLadder.map((item) => (
              <code key={`hint-${item}`}>{item}</code>
            ))}
            {verificationSteps.length > 0 ? (
              <p className="message-part__meta">
                {label(context?.language, "Verification steps", "Verification steps")}
              </p>
            ) : null}
            {verificationSteps.map((item) => (
              <code key={`verify-${item}`}>{item}</code>
            ))}
          </div>
        </details>
      ) : null}
    </CollapsibleBlock>
  );
}

function TrainingCardPartRenderer({ part, context }: { part: TrainingCardPart; context?: PartRenderContext }) {
  const difficultyTone =
    part.difficulty === "hard" ? "fail" : part.difficulty === "medium" ? "warn" : "pass";
  const statusTone =
    part.status === "blocked"
      ? "fail"
      : part.status === "active" || part.status === "implemented"
        ? "warn"
        : part.status === "reviewed" || part.status === "fed_back" || part.status === "archived"
          ? "pass"
          : "pending";
  const primaryMeta = [part.focusArea, part.targetSkill].filter(Boolean).join(" | ");
  const actionItems = [
    part.deliverable,
    part.validationMethod,
    part.successSignal,
    part.fallbackAction,
    part.nextAfterCompletion,
  ].filter(Boolean) as string[];
  const reviewMeta = [
    part.reviewSurfaceMode ? `${label(context?.language, "Surface", "Surface")}: ${part.reviewSurfaceMode}` : undefined,
    part.reviewSource ? `${label(context?.language, "Source", "Source")}: ${part.reviewSource}` : undefined,
    part.dueAt ? `${label(context?.language, "Due", "Due")}: ${formatDateTime(part.dueAt)}` : undefined,
    typeof part.intervalDays === "number"
      ? `${label(context?.language, "Interval", "Interval")}: ${part.intervalDays}d`
      : undefined,
    typeof part.stability === "number"
      ? `${label(context?.language, "Stability", "Stability")}: ${part.stability.toFixed(2)}`
      : undefined,
    typeof part.fsrsDifficulty === "number"
      ? `${label(context?.language, "Difficulty", "Difficulty")}: ${part.fsrsDifficulty.toFixed(2)}`
      : undefined,
    typeof part.retrievability === "number"
      ? `${label(context?.language, "Recall", "Recall")}: ${formatPercent(part.retrievability)}`
      : undefined,
    part.fsrsState ? `${label(context?.language, "FSRS", "FSRS")}: ${part.fsrsState}` : undefined,
  ].filter(Boolean) as string[];

  return (
    <div className="message-part message-part--training-card">
      <div className="message-part__header">
        <strong>{part.title || label(context?.language, "Training card", "Training card")}</strong>
        {part.status ? <StatusPill tone={statusTone}>{part.status}</StatusPill> : null}
      </div>
      <p className="message-part__meta">
        <code>{part.cardId}</code>
        {part.cardType ? <span>{` | ${part.cardType}`}</span> : null}
        {part.difficulty ? (
          <>
            <span> | </span>
            <StatusPill tone={difficultyTone}>{part.difficulty}</StatusPill>
          </>
        ) : null}
      </p>
      {primaryMeta ? <p className="message-part__meta">{primaryMeta}</p> : null}
      {part.whyNow ? <p>{part.whyNow}</p> : null}
      {part.reviewReason ? <p className="message-part__meta">{part.reviewReason}</p> : null}
      {reviewMeta.length > 0 ? <p className="message-part__meta">{reviewMeta.join(" | ")}</p> : null}
      {part.problemStatement ? <p>{part.problemStatement}</p> : null}
      {actionItems.length > 0 ? (
        <ul className="message-part__list">
          {part.deliverable ? <li>{label(context?.language, "Deliverable: ", "Deliverable: ")}{part.deliverable}</li> : null}
          {part.validationMethod ? <li>{label(context?.language, "Verify via: ", "Verify via: ")}{part.validationMethod}</li> : null}
          {part.successSignal ? <li>{label(context?.language, "Success signal: ", "Success signal: ")}{part.successSignal}</li> : null}
          {part.fallbackAction ? <li>{label(context?.language, "Fallback: ", "Fallback: ")}{part.fallbackAction}</li> : null}
          {part.nextAfterCompletion ? <li>{label(context?.language, "Then: ", "Then: ")}{part.nextAfterCompletion}</li> : null}
        </ul>
      ) : null}
    </div>
  );
}

function PlanUpdatePartRenderer({ part, context }: { part: PlanUpdatePart; context?: PartRenderContext }) {
  return (
    <div className="message-part message-part--plan-update">
      <span className="eyebrow">{label(context?.language, "Plan update", "Plan update")}</span>
      <p className="message-part__meta">
        <code>{part.planId}</code>
      </p>
      {part.changes.length > 0 ? (
        <ul className="message-part__list">
          {part.changes.map((change, index) => (
            <li key={index}>
              {typeof change === "string"
                ? sanitizeErrorSurfaceText(change, context?.language)
                : sanitizeErrorSurfaceJson(change, context?.language)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function TestResultPartRenderer({ part, context }: { part: TestResultPart; context?: PartRenderContext }) {
  const tone = part.status === "pass" ? "pass" : part.status === "fail" ? "fail" : "warn";
  return (
    <div className="message-part message-part--test-result">
      <div className="message-part__header">
        <strong>{label(context?.language, "Test result", "Test result")}</strong>
        <StatusPill tone={tone}>{part.status}</StatusPill>
      </div>
      <p className="message-part__meta">
        <code>{part.command}</code>
      </p>
      {part.detail ? <p>{sanitizeErrorSurfaceText(part.detail, context?.language)}</p> : null}
      {part.outputRef ? <p className="message-part__meta">{part.outputRef}</p> : null}
    </div>
  );
}

function ChecklistPartRenderer({ part }: { part: ChecklistPart }) {
  return (
    <div className="message-part message-part--checklist">
      <ul className="message-part__checklist">
        {part.items.map((item, index) => (
          <li key={`${item.label}-${index}`} className={item.done ? "is-done" : ""}>
            <span aria-hidden="true">{item.done ? "done" : "todo"}</span>
            <span>{item.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AlertPartRenderer({ part, context }: { part: AlertPart; context?: PartRenderContext }) {
  return (
    <div className={`message-part message-part--alert message-part--alert-${part.level}`} role="alert">
      <strong>{sanitizeErrorSurfaceText(part.title, context?.language)}</strong>
      {part.detail ? <p>{sanitizeErrorSurfaceText(part.detail, context?.language)}</p> : null}
    </div>
  );
}

export const partRegistry: PartRegistry = {
  markdown: MarkdownPartRenderer,
  code: CodePartRenderer,
  diff: DiffPartRenderer,
  math: MathPartRenderer,
  mermaid: MermaidPartRenderer,
  table: TablePartRenderer,
  citation: CitationPartRenderer,
  tool_call: ({ part }) => <ToolCallRenderer part={part} />,
  tool_result: ToolResultPartRenderer,
  reasoning: ReasoningPartRenderer,
  training_card: TrainingCardPartRenderer,
  plan_update: PlanUpdatePartRenderer,
  test_result: TestResultPartRenderer,
  file_preview: ({ part }) => <FilePreviewRenderer part={part} />,
  checklist: ChecklistPartRenderer,
  alert: AlertPartRenderer,
};

export function isRegisteredPartType(type: string): type is TrainerMessagePartType {
  return type in partRegistry;
}

export function renderPart(part: TrainerMessagePart, context?: PartRenderContext): ReactNode | undefined {
  const renderer = partRegistry[part.type as keyof PartRegistry];
  if (!renderer) {
    return undefined;
  }
  return renderer({ part: part as never, context });
}
