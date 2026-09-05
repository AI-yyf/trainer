/**
 * Parts Renderer - React component for rendering Trainer message parts
 *
 * Provides type-safe rendering of all TrainerMessagePart types using
 * the PartsRendererRegistry.
 *
 * Reference: docs/open-source-fit-and-provider-strategy.md §10
 */

import React, { useMemo, useCallback } from "react";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import {
  getPartsRendererRegistry,
  RenderContext,
  getPartCssClasses,
  getPartDefaultCollapsed,
  isInteractivePart,
} from "@trainer/shared";
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
} from "@trainer/shared";

// Import renderer components
import { CodeRenderer } from "./CodeRenderer";
import { DiffRenderer } from "./DiffRenderer";
import { TableRenderer } from "./TableRenderer";
import { CitationRenderer } from "./CitationRenderer";
import { ToolCallRenderer } from "./ToolCallRenderer";
import { ToolResultRenderer } from "./ToolResultRenderer";
import { ReasoningRenderer } from "./ReasoningRenderer";
import { TrainingCardRenderer } from "./TrainingCardRenderer";
import { FilePreviewRenderer } from "./FilePreviewRenderer";
import { ChecklistRenderer } from "./ChecklistRenderer";
import { AlertRenderer } from "./AlertRenderer";
import { PlanUpdateRenderer } from "./PlanUpdateRenderer";
import { TestResultRenderer } from "./TestResultRenderer";
import { MathRenderer } from "./MathRenderer";
import { MermaidRenderer } from "./MermaidRenderer";

// Lazy-load react-markdown to reduce initial bundle size
import ReactMarkdown from "react-markdown";

type PartsLanguage = "en" | "zh";

type PartsCopy = {
  expand: string;
  collapse: string;
  tool: string;
  toolResult: string;
  reasoning: string;
  file: string;
  card: string;
};

const partsCopy: Record<PartsLanguage, PartsCopy> = {
  en: {
    expand: "Expand details",
    collapse: "Collapse details",
    tool: "Tool",
    toolResult: "Tool result",
    reasoning: "Reasoning",
    file: "File",
    card: "Card",
  },
  zh: {
    expand: "展开详情",
    collapse: "收起详情",
    tool: "工具",
    toolResult: "工具结果",
    reasoning: "推理摘要",
    file: "文件",
    card: "卡片",
  },
};

function resolvePartsCopy(language: PartsLanguage | undefined): PartsCopy {
  return partsCopy[language ?? "en"];
}

export interface PartsRendererProps {
  parts: TrainerMessagePart[];
  language?: PartsLanguage;
  onCitationClick?: (resourceId: string, chunkId?: string) => void;
  onFilePreviewClick?: (resourceId: string, path: string) => void;
  onTrainingCardClick?: (cardId: string) => void;
  onToolCallClick?: (callId: string) => void;
  collapsedStates?: Record<string, boolean>;
  onCollapseChange?: (partId: string, collapsed: boolean) => void;
}

export interface SinglePartRendererProps {
  part: TrainerMessagePart;
  language?: PartsLanguage;
  onCitationClick?: (resourceId: string, chunkId?: string) => void;
  onFilePreviewClick?: (resourceId: string, path: string) => void;
  onTrainingCardClick?: (cardId: string) => void;
  onToolCallClick?: (callId: string) => void;
  /** Collapse state for collapsible parts */
  collapsed?: boolean;
  /** Callback when collapse state changes */
  onCollapseChange?: (collapsed: boolean) => void;
}

/**
 * Build render context for part rendering
 */
function buildRenderContext(props: SinglePartRendererProps): RenderContext {
  return {
    language: props.language === "zh" ? "zh-CN" : "en-US",
    onCitationClick: props.onCitationClick,
    onFilePreviewClick: props.onFilePreviewClick,
    onTrainingCardClick: props.onTrainingCardClick,
    onToolCallClick: props.onToolCallClick,
  };
}

/**
 * Single part renderer component
 */
export const SinglePartRenderer: React.FC<SinglePartRendererProps> = (props) => {
  const { part, collapsed, onCollapseChange } = props;
  const copy = resolvePartsCopy(props.language);
  const context = useMemo(() => buildRenderContext(props), [props]);

  // Determine if this part should be collapsible
  const isCollapsible = getPartDefaultCollapsed(part.type);
  const shouldCollapse = isCollapsible && collapsed;

  const handleToggleCollapse = useCallback(() => {
    onCollapseChange?.(!collapsed);
  }, [collapsed, onCollapseChange]);

  // Render based on part type
  const renderContent = () => {
    switch (part.type) {
      case "markdown":
        return <MarkdownPartRenderer part={part as MarkdownPart} />;
      case "code":
        return <CodePartRenderer part={part as CodePart} />;
      case "diff":
        return <DiffPartRenderer part={part as DiffPart} />;
      case "math":
        return <MathPartRenderer part={part as MathPart} />;
      case "mermaid":
        return <MermaidPartRenderer part={part as MermaidPart} />;
      case "table":
        return <TablePartRenderer part={part as TablePart} />;
      case "citation":
        return <CitationPartRenderer part={part as CitationPart} context={context} />;
      case "tool_call":
        return <ToolCallPartRenderer part={part as ToolCallPart} context={context} />;
      case "tool_result":
        return <ToolResultPartRenderer part={part as ToolResultPart} />;
      case "reasoning":
        return <ReasoningPartRenderer part={part as ReasoningPart} />;
      case "training_card":
        return <TrainingCardPartRenderer part={part as TrainingCardPart} context={context} />;
      case "plan_update":
        return <PlanUpdatePartRenderer part={part as PlanUpdatePart} />;
      case "test_result":
        return <TestResultPartRenderer part={part as TestResultPart} />;
      case "file_preview":
        return <FilePreviewPartRenderer part={part as FilePreviewPart} context={context} />;
      case "checklist":
        return <ChecklistPartRenderer part={part as ChecklistPart} />;
      case "alert":
        return <AlertPartRenderer part={part as AlertPart} />;
      default:
        return <UnknownPartRenderer part={part} />;
    }
  };

  const cssClass = getPartCssClasses(part.type);
  const isInteractive = isInteractivePart(part.type);

  return (
    <div
      className={`trainer-part ${cssClass} ${isInteractive ? "trainer-part-interactive" : ""} ${shouldCollapse ? "trainer-part-collapsed" : ""}`}
      data-part-type={part.type}
    >
      {isCollapsible && (
        <button
          className="trainer-part-collapse-btn"
          onClick={handleToggleCollapse}
          aria-expanded={!shouldCollapse}
          aria-label={shouldCollapse ? copy.expand : copy.collapse}
          type="button"
        >
          {shouldCollapse ? "▶" : "▼"}
        </button>
      )}
      {shouldCollapse ? (
        <div className="trainer-part-collapsed-summary">
          {getPartSummary(part, copy)}
        </div>
      ) : (
        renderContent()
      )}
    </div>
  );
};

/**
 * Get a summary for collapsed parts
 */
function getPartSummary(part: TrainerMessagePart, copy: PartsCopy): string {
  switch (part.type) {
    case "tool_call":
      return `${copy.tool}: ${(part as ToolCallPart).name}`;
    case "tool_result":
      return copy.toolResult;
    case "reasoning":
      return `${copy.reasoning}: ${(part as ReasoningPart).summary.slice(0, 50)}...`;
    case "file_preview":
      return `${copy.file}: ${(part as FilePreviewPart).path}`;
    case "training_card":
      return `${copy.card}: ${(part as TrainingCardPart).title ?? (part as TrainingCardPart).cardId}`;
    default:
      return part.type;
  }
}

// =============================================================================
// Individual Part Renderers
// =============================================================================

const MarkdownPartRenderer: React.FC<{ part: MarkdownPart }> = ({ part }) => {
  return (
    <div className="trainer-markdown-content">
      <ReactMarkdown rehypePlugins={[rehypeKatex]} remarkPlugins={[remarkGfm, remarkMath]}>
        {part.content}
      </ReactMarkdown>
    </div>
  );
};

const CodePartRenderer: React.FC<{ part: CodePart }> = ({ part }) => {
  return <CodeRenderer code={part.code} language={part.language} />;
};

const DiffPartRenderer: React.FC<{ part: DiffPart }> = ({ part }) => {
  return <DiffRenderer patch={part.patch} language={part.language} />;
};

const MathPartRenderer: React.FC<{ part: MathPart }> = ({ part }) => {
  return <MathRenderer tex={part.tex} display={part.display ?? false} />;
};

const MermaidPartRenderer: React.FC<{ part: MermaidPart }> = ({ part }) => {
  return <MermaidRenderer source={part.source} />;
};

const TablePartRenderer: React.FC<{ part: TablePart }> = ({ part }) => {
  return <TableRenderer columns={part.columns} rows={part.rows} />;
};

const CitationPartRenderer: React.FC<{ part: CitationPart; context: RenderContext }> = ({ part, context }) => {
  return <CitationRenderer part={part} onClick={context.onCitationClick} />;
};

const ToolCallPartRenderer: React.FC<{ part: ToolCallPart; context: RenderContext }> = ({ part, context }) => {
  return <ToolCallRenderer part={part} onClick={() => context.onToolCallClick?.(part.id)} />;
};

const ToolResultPartRenderer: React.FC<{ part: ToolResultPart }> = ({ part }) => {
  return <ToolResultRenderer part={part} />;
};

const ReasoningPartRenderer: React.FC<{ part: ReasoningPart }> = ({ part }) => {
  return <ReasoningRenderer part={part} />;
};

const TrainingCardPartRenderer: React.FC<{ part: TrainingCardPart; context: RenderContext }> = ({ part, context }) => {
  return <TrainingCardRenderer part={part} onClick={() => context.onTrainingCardClick?.(part.cardId)} />;
};

const FilePreviewPartRenderer: React.FC<{ part: FilePreviewPart; context: RenderContext }> = ({ part, context }) => {
  return <FilePreviewRenderer part={part} onClick={() => context.onFilePreviewClick?.(part.resourceId, part.path)} />;
};

const ChecklistPartRenderer: React.FC<{ part: ChecklistPart }> = ({ part }) => {
  return <ChecklistRenderer items={part.items} />;
};

const AlertPartRenderer: React.FC<{ part: AlertPart }> = ({ part }) => {
  return <AlertRenderer level={part.level} title={part.title} detail={part.detail} />;
};

const PlanUpdatePartRenderer: React.FC<{ part: PlanUpdatePart }> = ({ part }) => {
  return <PlanUpdateRenderer planId={part.planId} changes={part.changes} />;
};

const TestResultPartRenderer: React.FC<{ part: TestResultPart }> = ({ part }) => {
  return <TestResultRenderer command={part.command} status={part.status} detail={part.detail} />;
};

const UnknownPartRenderer: React.FC<{ part: TrainerMessagePart }> = ({ part }) => {
  return (
    <div className="trainer-unknown-part" role="status">
      <div className="unknown-part-header">
        <span className="unknown-icon" aria-hidden="true">?</span>
        <span className="unknown-type">Unsupported message content: {part.type}</span>
      </div>
    </div>
  );
};

/**
 * Parts Renderer - renders multiple parts with collapse state management
 */
export const PartsRenderer: React.FC<PartsRendererProps> = (props) => {
  const { parts, collapsedStates = {}, onCollapseChange } = props;

  const handleCollapseChange = useCallback(
    (partId: string, collapsed: boolean) => {
      onCollapseChange?.(partId, collapsed);
    },
    [onCollapseChange],
  );

  return (
    <div className="trainer-parts-container">
      {parts.map((part, index) => {
        const partId = `${part.type}-${index}`;
        const defaultCollapsed = getPartDefaultCollapsed(part.type);
        const isCollapsed = collapsedStates[partId] ?? defaultCollapsed;

        return (
          <SinglePartRenderer
            key={partId}
            part={part}
            language={props.language}
            onCitationClick={props.onCitationClick}
            onFilePreviewClick={props.onFilePreviewClick}
            onTrainingCardClick={props.onTrainingCardClick}
            onToolCallClick={props.onToolCallClick}
            collapsed={isCollapsed}
            onCollapseChange={(collapsed) => handleCollapseChange(partId, collapsed)}
          />
        );
      })}
    </div>
  );
};

export default PartsRenderer;
