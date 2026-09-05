import {
  isAuthoritativeAck,
  sanitizeErrorSurface,
  sanitizeErrorSurfaceJson,
  sanitizeErrorSurfaceText,
} from "../../../../../shared/src/errorSurfaceSanitizer";
import { isDocxPreviewPath } from "../../../../../shared/src/previewAssets";
import {
  describeTrainerStopReason,
  type TrainerMessagePart,
} from "../../../../../shared/src/protocol";
import type { ComposerLanguage } from "../../lib/types";

import { CollapsibleBlock } from "./CollapsibleBlock";
import { MermaidBlock } from "./MermaidBlock";
import { MessageRichContent } from "./MessageRichContent";
import { RichCodeBlock } from "./RichCodeBlock";
import {
  hasCoachToolResultFailure,
  resolveCoachToolResultCopy,
  safeCoachResultText,
  summarizeSafeCoachToolResult,
} from "./coachToolResultCopy";
import { StructuredTable } from "./parts/StructuredTable";
import { DocxPreview } from "../preview/DocxPreview";

export interface CoachMessagePartsProps {
  parts: TrainerMessagePart[];
  language?: ComposerLanguage;
}

function copy(
  language: ComposerLanguage,
  zh: string,
  en: string,
): string {
  return language === "zh-CN" ? zh : en;
}

function renderSafeJson(value: unknown, language: ComposerLanguage): string {
  return sanitizeErrorSurfaceJson(value, language);
}

function inferCodeLanguage(path: string | undefined, fallback?: string): string | undefined {
  const normalizedFallback = fallback?.trim();
  if (normalizedFallback) {
    return normalizedFallback;
  }

  const extension = path?.split(".").pop()?.trim().toLowerCase();
  if (!extension) {
    return undefined;
  }

  switch (extension) {
    case "ts":
    case "tsx":
    case "js":
    case "jsx":
    case "mjs":
    case "cjs":
    case "py":
    case "json":
    case "md":
    case "yaml":
    case "yml":
    case "html":
    case "css":
    case "scss":
    case "sh":
    case "sql":
    case "xml":
      return extension;
    default:
      return undefined;
  }
}

function mathMarkdown(tex: string, display: boolean): string {
  return display ? `$$\n${tex}\n$$` : `$${tex}$`;
}

function coachVisibleStatusLabel(
  status: "working" | "done" | "blocked" | "degraded",
  language: ComposerLanguage,
): string {
  switch (status) {
    case "working":
      return copy(language, "核对中", "Checking");
    case "blocked":
      return copy(language, "受阻", "Blocked");
    case "degraded":
      return copy(language, "已降级", "Degraded");
    default:
      return copy(language, "已核对", "Checked");
  }
}

function coachVisibleStatusHeading(
  status: "working" | "done" | "blocked" | "degraded",
  language: ComposerLanguage,
): string {
  switch (status) {
    case "working":
      return copy(language, "教练正在核对", "Coach is checking");
    case "blocked":
      return copy(language, "教练检查受阻", "Coach hit a blocker");
    case "degraded":
      return copy(language, "教练已安全降级", "Coach fell back safely");
    default:
      return copy(language, "教练已核对", "Coach checked");
  }
}

function humanizeToolName(name: string): string {
  const normalized = name.replace(/_/g, " ").trim();
  return normalized.length > 0 ? normalized : name;
}

function practiceVerificationStatusLabel(
  status: string | undefined,
  language: ComposerLanguage,
): string {
  if (status === "passed") {
    return copy(language, "\u5df2\u901a\u8fc7", "Passed");
  }
  if (status === "blocked") {
    return copy(language, "\u53d7\u963b", "Blocked");
  }
  if (status === "needs_review") {
    return copy(language, "\u9700\u590d\u6838", "Needs review");
  }
  return copy(language, "\u5df2\u9a8c\u8bc1", "Verified");
}

function practiceVerificationTone(
  status: string | undefined,
  passed: boolean | undefined,
): "done" | "blocked" | "degraded" {
  if (passed || status === "passed") {
    return "done";
  }
  if (status === "blocked") {
    return "blocked";
  }
  return "degraded";
}

function visibleTrainingCardText(
  value: string | undefined,
  language: ComposerLanguage,
): string | undefined {
  const normalized = value?.trim();
  if (!normalized || language !== "zh-CN") {
    return normalized;
  }
  if (/[\u3400-\u9fff]/u.test(normalized)) {
    return normalized;
  }
  if (
    normalized.length <= 64 &&
    /^[A-Za-z0-9_./:\\#@()[\]{}<>=+*,'"`| -]+$/.test(normalized) &&
    !/[.!?]/.test(normalized)
  ) {
    return normalized;
  }
  return undefined;
}

function renderPart(
  part: TrainerMessagePart,
  language: ComposerLanguage,
  index: number,
) {
  switch (part.type) {
    case "markdown":
      return (
        <div key={`part-${index}`} className="message-part message-part--markdown">
          <MessageRichContent body={part.content} language={language} preferCollapse={false} />
        </div>
      );
    case "code":
      return (
        <div key={`part-${index}`} className="message-part message-part--code">
          <p className="message-part__meta">
            {part.language ? <span>{part.language}</span> : null}
            {part.path ? <code>{part.path}</code> : null}
          </p>
          <RichCodeBlock
            code={part.code}
            language={language}
            languageId={inferCodeLanguage(part.path, part.language)}
          />
        </div>
      );
    case "diff":
      return (
        <div key={`part-${index}`} className="message-part message-part--diff">
          {part.language ? <p className="message-part__meta">{part.language}</p> : null}
          <RichCodeBlock
            code={part.patch}
            language={language}
            languageId={part.language?.trim() || "diff"}
          />
        </div>
      );
    case "math":
      return (
        <div key={`part-${index}`} className="message-part message-part--math">
          <p className="message-part__meta">
            {copy(language, part.display ? "展示公式" : "行内公式", part.display ? "Display math" : "Inline math")}
          </p>
          <MessageRichContent
            body={mathMarkdown(part.tex, Boolean(part.display))}
            language={language}
            preferCollapse={false}
          />
        </div>
      );
    case "mermaid":
      return (
        <div key={`part-${index}`} className="message-part message-part--mermaid">
          <MermaidBlock
            chart={part.source}
            summaryLabel={copy(language, "流程图", "Diagram")}
            errorLabel={copy(
              language,
              "图表渲染失败，先显示原始内容。",
              "Diagram render failed. Showing the raw content instead.",
            )}
          />
        </div>
      );
    case "table":
      return (
        <div key={`part-${index}`} className="message-part message-part--table">
          <StructuredTable
            columns={part.columns}
            rows={part.rows.map((row) => row.map((cell) => String(cell ?? "")))}
            rowCount={part.rows.length}
            columnCount={part.columns.length}
            rowLabel={copy(language, "行", "rows")}
            columnLabel={copy(language, "列", "columns")}
            truncatedLabel={copy(language, "仅预览关键信息", "Quick preview only")}
            emptyLabel={copy(language, "没有可显示的行。", "No rows available.")}
          />
        </div>
      );
    case "citation":
      return (
        <div key={`part-${index}`} className="message-part message-part--citation">
          <strong>{part.title || part.label}</strong>
          <p className="message-part__meta">
            <code>{part.resourceId}</code>
            {part.chunkId ? <span>{` | ${part.chunkId}`}</span> : null}
          </p>
          {part.source ? <p className="message-part__meta">{part.source}</p> : null}
          {typeof part.trustScore === "number" ? (
            <p className="message-part__meta">
              {copy(language, "可信度", "Trust")} {Math.round(part.trustScore * 100)}%
            </p>
          ) : null}
        </div>
      );
    case "tool_call":
      return (
        <CollapsibleBlock
          key={`part-${index}`}
          className="message-part message-part--tool-call"
          summary={copy(language, `调用工具：${part.name}`, `Tool call: ${part.name}`)}
          defaultOpen={false}
        >
          <p className="message-part__meta">
            <code>{part.id}</code>
            <span>{` | ${part.status}`}</span>
            {typeof part.step === "number" ? <span>{` | step ${part.step}`}</span> : null}
          </p>
          <RichCodeBlock
            code={renderSafeJson(part.args, language)}
            language={language}
            languageId="json"
          />
        </CollapsibleBlock>
      );
    case "tool_result": {
      const toolCopy = resolveCoachToolResultCopy(language);
      const hasFailure = hasCoachToolResultFailure(part.error, part.result);
      if (part.displayKind === "practice_verification") {
        const tone = practiceVerificationTone(part.status, part.passed);
        const safeSummary = safeCoachResultText(part.summary);
        const safeNextStep = safeCoachResultText(part.nextStep);
        return (
          <CollapsibleBlock
            key={`part-${index}`}
            className={`message-part message-part--tool-result message-part--practice-verification message-part--coach-visible-status-${tone}`}
            summary={
              hasFailure
                ? `${toolCopy.failed}. ${toolCopy.retry}`
                : `${copy(language, "\u5b9e\u6218\u9a8c\u8bc1", "Practice verification")}: ${practiceVerificationStatusLabel(part.status, language)}`
            }
            defaultOpen={false}
          >
            <div className="message-part__header">
              <strong>{copy(language, "\u5f53\u524d IDE \u6587\u4ef6", "Current IDE file")}</strong>
              <span className={`message-part__status-chip message-part__status-chip--${tone}`}>
                {practiceVerificationStatusLabel(part.status, language)}
              </span>
            </div>
            {hasFailure ? <p>{toolCopy.failed}</p> : safeSummary ? <p>{safeSummary}</p> : null}
            {hasFailure || safeNextStep ? (
              <p className="message-part__meta">
                {toolCopy.next}
                {hasFailure ? toolCopy.retry : safeNextStep}
              </p>
            ) : null}
          </CollapsibleBlock>
        );
      }
      const safeSummary = summarizeSafeCoachToolResult(part.result, language);
      const acknowledged = !hasFailure && isAuthoritativeAck(part.result);
      const errorSurface = hasFailure
        ? sanitizeErrorSurface(part.error, { language })
        : undefined;
      return (
        <CollapsibleBlock
          key={`part-${index}`}
          className="message-part message-part--tool-result"
          summary={hasFailure ? `${toolCopy.failed}. ${toolCopy.retry}` : toolCopy.update}
          defaultOpen={false}
        >
          <p>
            {hasFailure
              ? errorSurface?.message ?? toolCopy.failed
              : acknowledged
                ? safeSummary ?? toolCopy.completed
                : sanitizeErrorSurface(undefined, { language, acknowledged: false }).message}
          </p>
          {hasFailure ? (
            <p className="message-part__meta">
              {toolCopy.next}
              {toolCopy.retry}
            </p>
          ) : null}
        </CollapsibleBlock>
      );
    }
    case "reasoning":
      return (
        <CollapsibleBlock
          key={`part-${index}`}
          className="message-part message-part--reasoning"
          summary={copy(language, "推理摘要", "Reasoning summary")}
          defaultOpen={!part.redacted}
        >
          <p>{sanitizeErrorSurfaceText(part.summary, language)}</p>
          {part.detail && !part.redacted ? (
            <p className="message-part__meta">{sanitizeErrorSurfaceText(part.detail, language)}</p>
          ) : null}
          {part.sourceChain?.length ? (
            <div className="message-part__facts">
              {part.sourceChain.map((item) => (
                <span key={item} className="message-part__fact-pill">
                  {item}
                </span>
              ))}
            </div>
          ) : null}
          {part.hintLadder?.length ? (
            <ul className="message-part__list">
              {part.hintLadder.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
          {part.verificationSteps?.length ? (
            <ul className="message-part__list">
              {part.verificationSteps.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
        </CollapsibleBlock>
      );
    case "coach_visible_status": {
      const stopReasonLabel = describeTrainerStopReason(part.stopReason, language);
      const decision = part.decision?.trim();
      const blocker = part.blocker?.trim();
      const teachingNote = part.teachingNote?.trim();
      const confidence = part.confidence?.trim();
      const evidence = part.evidence?.map((item) => item.trim()).filter(Boolean) ?? [];
      return (
        <div
          key={`part-${index}`}
          className={`message-part message-part--coach-visible-status message-part--coach-visible-status-${part.status}`}
          role="status"
          aria-live="polite"
        >
          <div className="message-part__header">
            <strong>{coachVisibleStatusHeading(part.status, language)}</strong>
            <span className={`message-part__status-chip message-part__status-chip--${part.status}`}>
              {coachVisibleStatusLabel(part.status, language)}
            </span>
          </div>
          <p>{sanitizeErrorSurfaceText(part.summary, language)}</p>
          {part.detail ? (
            <p className="message-part__meta">{sanitizeErrorSurfaceText(part.detail, language)}</p>
          ) : null}
          {part.nextStep ? (
            <p className="message-part__meta">
              {copy(language, "下一步：", "Next: ")}
              {part.nextStep}
            </p>
          ) : null}
          {part.resumeThread ? (
            <p className="message-part__meta">{part.resumeThread}</p>
          ) : null}
          {decision ? (
            <p className="message-part__meta">
              {copy(language, "决定：", "Decision: ")}
              {decision}
            </p>
          ) : null}
          {blocker ? (
            <p className="message-part__meta">
              {copy(language, "卡点：", "Blocker: ")}
              {blocker}
            </p>
          ) : null}
          {teachingNote ? (
            <p className="message-part__meta">
              {copy(language, "教学提示：", "Teaching note: ")}
              {teachingNote}
            </p>
          ) : null}
          {confidence ? (
            <p className="message-part__meta">
              {copy(language, "置信度：", "Confidence: ")}
              {confidence}
            </p>
          ) : null}
          {evidence.length ? (
            <div className="message-part__facts">
              {evidence.map((item) => (
                <span key={item} className="message-part__fact-pill">
                  {item}
                </span>
              ))}
            </div>
          ) : null}
          {stopReasonLabel ? (
            <div className="message-part__facts">
              <span className="message-part__fact-pill">{stopReasonLabel}</span>
            </div>
          ) : null}
          {part.toolNames?.length ? (
            <div className="message-part__facts">
              {part.toolNames.map((toolName) => (
                <span key={toolName} className="message-part__fact-pill">
                  {humanizeToolName(toolName)}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      );
    }
    case "training_card": {
      const title = visibleTrainingCardText(part.title, language);
      const whyNow = visibleTrainingCardText(part.whyNow, language);
      const deliverable = visibleTrainingCardText(part.deliverable, language);
      const validationMethod = visibleTrainingCardText(part.validationMethod, language);
      return (
        <div key={`part-${index}`} className="message-part message-part--training-card">
          <strong>{title || copy(language, "训练卡片", "Training card")}</strong>
          <p className="message-part__meta">
            <code>{part.cardId}</code>
            {part.cardType ? <span>{` | ${part.cardType}`}</span> : null}
            {part.difficulty ? <span>{` | ${part.difficulty}`}</span> : null}
          </p>
          {whyNow ? <p>{whyNow}</p> : null}
          {deliverable ? <p>{deliverable}</p> : null}
          {validationMethod ? <p className="message-part__meta">{validationMethod}</p> : null}
        </div>
      );
    }
    case "plan_update":
      return (
        <div key={`part-${index}`} className="message-part message-part--plan-update">
          <strong>{copy(language, "计划更新", "Plan update")}</strong>
          <p className="message-part__meta">
            <code>{part.planId}</code>
          </p>
          <ul className="message-part__list">
            {part.changes.map((change, changeIndex) => (
              <li key={`change-${changeIndex}`}>{renderSafeJson(change, language)}</li>
            ))}
          </ul>
        </div>
      );
    case "test_result":
      return (
        <div key={`part-${index}`} className="message-part message-part--test-result">
          <strong>{copy(language, "测试结果", "Test result")}</strong>
          <p className="message-part__meta">
            <code>{part.command}</code>
            <span>{` | ${part.status}`}</span>
          </p>
          {part.detail ? <p>{sanitizeErrorSurfaceText(part.detail, language)}</p> : null}
          {part.outputRef ? <p className="message-part__meta">{part.outputRef}</p> : null}
        </div>
      );
    case "file_preview": {
      const raw = part as TrainerMessagePart & Record<string, unknown>;
      const previewKind =
        typeof part.previewKind === "string"
          ? part.previewKind
          : typeof raw.preview_kind === "string"
            ? raw.preview_kind
            : undefined;
      const assetUri =
        typeof part.assetUri === "string"
          ? part.assetUri
          : typeof raw.asset_uri === "string"
            ? raw.asset_uri
            : undefined;
      const canRenderDocxPreview =
        previewKind === "document" &&
        Boolean(assetUri) &&
        isDocxPreviewPath(part.path);

      return (
        <CollapsibleBlock
          key={`part-${index}`}
          className="message-part message-part--file-preview"
          summary={copy(language, `文件预览：${part.title || part.path}`, `File preview: ${part.title || part.path}`)}
          defaultOpen={false}
        >
          <p className="message-part__meta">
            <code>{part.path}</code>
            {part.previewTier ? <span>{` | ${part.previewTier}`}</span> : null}
            {previewKind ? <span>{` | ${previewKind}`}</span> : null}
          </p>
          {canRenderDocxPreview && assetUri ? (
            <DocxPreview
              src={assetUri}
              title={part.title || part.path}
              compact
            />
          ) : part.content ? (
            <RichCodeBlock
              code={part.content}
              language={language}
              languageId={inferCodeLanguage(part.path)}
            />
          ) : null}
        </CollapsibleBlock>
      );
    }
    case "checklist":
      return (
        <div key={`part-${index}`} className="message-part message-part--checklist">
          <ul className="message-part__checklist">
            {part.items.map((item, itemIndex) => (
              <li key={`check-${itemIndex}`} className={item.done ? "is-done" : ""}>
                <span aria-hidden="true">{item.done ? "done" : "todo"}</span>
                <span>{item.label}</span>
              </li>
            ))}
          </ul>
        </div>
      );
    case "alert":
      return (
        <div
          key={`part-${index}`}
          className={`message-part message-part--alert message-part--alert-${part.level}`}
          role="alert"
        >
          <strong>{part.title}</strong>
          {part.detail ? <p>{sanitizeErrorSurfaceText(part.detail, language)}</p> : null}
        </div>
      );
    default: {
      const unknownPart = part as { type: string };
      return (
        <CollapsibleBlock
          key={`part-${index}`}
          className="message-part message-part--unknown"
          summary={copy(
            language,
            `消息片段：${unknownPart.type}`,
            `Message part: ${unknownPart.type}`,
          )}
          defaultOpen={false}
        >
          <RichCodeBlock
            code={sanitizeErrorSurfaceText(part, language)}
            language={language}
            languageId="json"
          />
        </CollapsibleBlock>
      );
    }
  }
}

export function CoachMessageParts({
  parts,
  language = "en-US",
}: CoachMessagePartsProps) {
  return (
    <div className="message-bubble__parts">
      {parts.map((part, index) => renderPart(part, language, index))}
    </div>
  );
}
