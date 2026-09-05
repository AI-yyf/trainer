import { Suspense, createContext, lazy, useCallback, useContext, useEffect, useId, useMemo, useState } from "react";
import type { Element } from "hast";

import type { ComposerLanguage } from "../../lib/types";
import { MermaidBlock } from "./MermaidBlock";
import { RichCodeBlock } from "./RichCodeBlock";
import { resolveCodeBlockCopy } from "./codeBlockCopy";

const ReactMarkdown = lazy(async () => {
  const module = await import("react-markdown");
  return { default: module.default };
});

type RehypeKatexPlugin = typeof import("rehype-katex").default;
type RemarkGfmPlugin = typeof import("remark-gfm").default;
type RemarkMathPlugin = typeof import("remark-math").default;

let markdownPluginsPromise:
  | Promise<{
      rehypeKatex: RehypeKatexPlugin;
      remarkGfm: RemarkGfmPlugin;
      remarkMath: RemarkMathPlugin;
    }>
  | undefined;

async function loadMarkdownPlugins() {
  markdownPluginsPromise ??= Promise.all([
    import("rehype-katex"),
    import("remark-gfm"),
    import("remark-math"),
  ]).then(([rehypeKatex, remarkGfm, remarkMath]) => ({
    rehypeKatex: rehypeKatex.default,
    remarkGfm: remarkGfm.default,
    remarkMath: remarkMath.default,
  }));
  return markdownPluginsPromise;
}

if (typeof window !== "undefined") {
  void loadMarkdownPlugins();
}

type RichTableColumn = {
  id: string;
  index: number;
  label: string;
};

type RichTableContextValue = {
  cellByOffset: ReadonlyMap<number, RichTableColumn>;
  headerByOffset: ReadonlyMap<number, RichTableColumn>;
};

const RichTableContext = createContext<RichTableContextValue | undefined>(undefined);

function childElements(node: Element | undefined): Element[] {
  return node?.children.filter((child): child is Element => child.type === "element") ?? [];
}

function elementText(node: Element): string {
  return node.children
    .map((child) => {
      if (child.type === "text") {
        return child.value;
      }
      return child.type === "element" ? elementText(child) : "";
    })
    .join("")
    .replace(/\s+/g, " ")
    .trim();
}

function elementOffset(node: Element | undefined): number | undefined {
  return node?.position?.start.offset;
}

function richTableContext(
  node: Element,
  tableId: string,
  tableLabel: string,
  columnLabel: string,
): RichTableContextValue {
  const headerByOffset = new Map<number, RichTableColumn>();
  const cellByOffset = new Map<number, RichTableColumn>();
  const headerGroup = childElements(node).find((child) => child.tagName === "thead");
  const headerRow = childElements(headerGroup).find((child) => child.tagName === "tr");
  const headers = childElements(headerRow).filter((child) => child.tagName === "th");
  const columns = headers.map((header, index) => ({
    id: `${tableId}-column-${index + 1}`,
    index,
    label: elementText(header) || `${tableLabel} ${columnLabel} ${index + 1}`,
  }));

  for (const [index, header] of headers.entries()) {
    const offset = elementOffset(header);
    if (offset !== undefined) {
      headerByOffset.set(offset, columns[index]);
    }
  }

  const body = childElements(node).find((child) => child.tagName === "tbody");
  for (const row of childElements(body).filter((child) => child.tagName === "tr")) {
    for (const [index, cell] of childElements(row).filter((child) => child.tagName === "td").entries()) {
      const offset = elementOffset(cell);
      const column = columns[index];
      if (offset !== undefined && column) {
        cellByOffset.set(offset, column);
      }
    }
  }

  return { cellByOffset, headerByOffset };
}

const MAX_LENGTH = 1200;
const MAX_LINES = 20;
const HARD_COLLAPSE_LENGTH = 6800;
const HARD_COLLAPSE_LINES = 108;
const SOFT_COLLAPSE_LENGTH = 5600;
const SOFT_COLLAPSE_LINES = 88;
const STRUCTURED_COLLAPSE_LENGTH = 6200;
const STRUCTURED_COLLAPSE_LINES = 92;
const SUMMARY_MAX_LENGTH = 210;
const STRUCTURED_PREVIEW_MAX = 2;

function countLines(value: string): number {
  return value.split("\n").length;
}

function truncateText(value: string, maxLength: number): string {
  return value.length > maxLength ? `${value.slice(0, maxLength).trim()}…` : value;
}

function stripStructuredContent(value: string): string {
  return value
    .replace(/```[\s\S]*?```/g, "\n")
    .replace(/\$\$[\s\S]*?\$\$/g, "\n")
    .replace(/^\|.*\|$/gm, "")
    .trim();
}

function hasStructuredContent(value: string): boolean {
  return (
    /```[\s\S]*?```/.test(value) ||
    /\$\$[\s\S]*?\$\$/.test(value) ||
    /^\|.*\|$/m.test(value)
  );
}

function normalizeInlineText(line: string): string {
  return line
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
    .replace(/^#{1,6}\s+/, "")
    .replace(/^>\s+/, "")
    .replace(/^[-*+]\s+/, "")
    .replace(/^\d+[.)]\s+/, "")
    .replace(/[:：]$/, "")
    .replace(/\s+/g, " ")
    .trim();
}

function extractLeadParagraph(value: string): string | undefined {
  const normalized = stripStructuredContent(value);
  if (!normalized) {
    return undefined;
  }

  const [firstBlock] = normalized.split(/\n\s*\n/);
  const lead = firstBlock
    ?.split("\n")
    .map((line) => normalizeInlineText(line))
    .filter(Boolean)
    .join(" ")
    .trim();

  if (!lead) {
    return undefined;
  }

  return truncateText(lead, SUMMARY_MAX_LENGTH);
}

function extractStructuredPreview(value: string, language: ComposerLanguage): string[] {
  const copy = labels(language);
  const previews: string[] = [];
  const codeBlocks = value.match(/```([\w-]+)?\n[\s\S]*?```/g) ?? [];
  for (const block of codeBlocks.slice(0, STRUCTURED_PREVIEW_MAX)) {
    const match = /^```([\w-]+)?\n([\s\S]*?)```$/.exec(block.trim());
    const languageId = match?.[1]?.trim() || copy.code;
    const body = match?.[2]?.trim() || "";
    const firstLine = body.split("\n").map((line) => line.trim()).find(Boolean) || "";
    previews.push(`${languageId} · ${truncateText(firstLine || copy.code, 72)}`);
  }

  if (/^\|.*\|$/m.test(value)) {
    previews.push(language === "zh-CN" ? "包含表格内容" : "Includes table content");
  }

  if (/```mermaid[\s\S]*?```/.test(value)) {
    previews.push(language === "zh-CN" ? "包含图表或思维导图" : "Includes diagram or mind map");
  }

  return previews.slice(0, STRUCTURED_PREVIEW_MAX);
}

function labels(language: ComposerLanguage) {
  const codeBlockCopy = resolveCodeBlockCopy(language);
  if (language === "zh-CN") {
    return {
      expand: "继续看",
      collapse: "收起",
      code: codeBlockCopy.code,
      diagram: "图表",
      mindmap: "思维导图",
      table: "表格",
      renderError: "图表渲染失败，已回退为原始内容。",
      foldedLeadFallback: "先看前面这一段。",
      foldedMetaFallback: "展开剩下的内容",
      loading: "正在整理显示…",
      copy: codeBlockCopy.copy,
      copied: codeBlockCopy.copied,
    };
  }

  return {
    expand: "Continue",
    collapse: "Hide",
    code: codeBlockCopy.code,
    diagram: "Diagram",
    mindmap: "Mind map",
    table: "Table",
    renderError: "Diagram render failed. Showing the raw content instead.",
    foldedLeadFallback: "Start with the opening.",
    foldedMetaFallback: "Open the rest",
    loading: "Rendering…",
    copy: codeBlockCopy.copy,
    copied: codeBlockCopy.copied,
  };
}

function renderPlainText(body: string) {
  return (
    <div className="message-markdown message-markdown--plain">
      {body.split(/\n{2,}/).map((paragraph, index) => (
        <p key={`${index}-${paragraph.slice(0, 24)}`}>{paragraph.trim()}</p>
      ))}
    </div>
  );
}

// 代码块组件，带复制功能
function CodeBlock({
  code,
  languageId,
  language
}: {
  code: string;
  languageId: string;
  language: ComposerLanguage;
}) {
  const [copied, setCopied] = useState(false);
  const copy = labels(language);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // 复制失败静默处理
    }
  }, [code]);

  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <span className="code-block-lang">{languageId || copy.code}</span>
        <button
          className="code-block-copy-btn"
          onClick={handleCopy}
          title={copied ? copy.copied : copy.copy}
        >
          {copied ? "OK" : "C"}
        </button>
      </div>
      <pre className="message-markdown__code-block">
        <code>{code}</code>
      </pre>
    </div>
  );
}

// 行内代码组件
function InlineCode({ children }: { children: React.ReactNode }) {
  return <code className="message-markdown__inline-code">{children}</code>;
}

function RichMarkdownRenderer({
  body,
  language,
}: {
  body: string;
  language: ComposerLanguage;
}) {
  const [plugins, setPlugins] = useState<{
    rehypeKatex: RehypeKatexPlugin;
    remarkGfm: RemarkGfmPlugin;
    remarkMath: RemarkMathPlugin;
  }>();
  const copy = labels(language);

  useEffect(() => {
    let cancelled = false;
    void loadMarkdownPlugins().then((nextPlugins) => {
      if (!cancelled) {
        setPlugins(nextPlugins);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!plugins) {
    return (
      <>
        {renderPlainText(body)}
        <p className="message-rich-content__loading">{copy.loading}</p>
      </>
    );
  }

  return (
    <ReactMarkdown
      rehypePlugins={[plugins.rehypeKatex]}
      remarkPlugins={[plugins.remarkGfm, plugins.remarkMath]}
      components={{
        // 处理代码元素 - 区分行内代码和代码块
        code({ node, className, children, ...props }) {
          const value = String(children ?? "").replace(/\n$/, "");
          const match = /language-(\w+)/.exec(className || "");
          const languageId = match ? match[1] : "";
          
          // 如果没有语言标识且没有换行，认为是行内代码
          const isInline = !languageId && !value.includes("\n");
          
          if (isInline) {
            return <InlineCode>{value}</InlineCode>;
          }

          // Mermaid 图表
          if (languageId === "mermaid") {
            const summaryLabel = value.includes("mindmap") ? copy.mindmap : copy.diagram;
            return (
              <MermaidBlock
                chart={value}
                errorLabel={copy.renderError}
                summaryLabel={summaryLabel}
              />
            );
          }

          // 代码块
          return (
            <RichCodeBlock
              code={value}
              languageId={languageId}
              language={language}
            />
          );
        },
        // 处理 pre 元素 - 防止嵌套问题
        pre({ children }) {
          // pre 元素的内容应该由 code 组件处理
          // 这里直接返回 children，避免额外的 pre 嵌套
          return <>{children}</>;
        },
        table({ node, children, ...props }) {
          const tableId = useId();
          const context = node
            ? richTableContext(
                node,
                tableId,
                copy.table,
                language === "zh-CN" ? "列" : "column",
              )
            : undefined;
          return (
            <div className="message-render-block message-render-block--table">
              <div className="message-table-wrap">
                <RichTableContext.Provider value={context}>
                  <table
                    {...props}
                    aria-label={copy.table}
                    data-rich-table="true"
                    data-column-count={context?.headerByOffset.size ?? 0}
                  >
                    <caption className="sr-only">{copy.table}</caption>
                    {children}
                  </table>
                </RichTableContext.Provider>
              </div>
            </div>
          );
        },
        th({ node, children, ...props }) {
          const context = useContext(RichTableContext);
          const column = context?.headerByOffset.get(elementOffset(node) ?? -1);
          return (
            <th
              {...props}
              id={column?.id}
              scope="col"
              data-column-index={column ? column.index + 1 : undefined}
              data-column-label={column?.label}
            >
              {children}
            </th>
          );
        },
        td({ node, children, ...props }) {
          const context = useContext(RichTableContext);
          const column = context?.cellByOffset.get(elementOffset(node) ?? -1);
          return (
            <td
              {...props}
              headers={column?.id}
              data-column-index={column ? column.index + 1 : undefined}
              data-column-label={column?.label}
            >
              {children}
            </td>
          );
        },
      }}
    >
      {body}
    </ReactMarkdown>
  );
}

export interface MessageRichContentProps {
  body: string;
  language: ComposerLanguage;
  streaming?: boolean;
  preferCollapse?: boolean;
  forceCollapse?: boolean;
  summaryOverride?: string;
  suppressPreviewItems?: boolean;
  onCopy?: () => void;
}

export function MessageRichContent({
  body,
  language,
  streaming = false,
  preferCollapse = false,
  forceCollapse = false,
  summaryOverride,
  suppressPreviewItems = false,
  onCopy,
}: MessageRichContentProps) {
  const copy = labels(language);
  const plainTextBody = stripStructuredContent(body);
  const containsStructuredContent = hasStructuredContent(body);
  const leadParagraph = useMemo(() => extractLeadParagraph(body), [body]);
  const structuredPreview = useMemo(() => extractStructuredPreview(body, language), [body, language]);
  const [expanded, setExpanded] = useState(false);
  const plainTextLines = countLines(plainTextBody);
  const totalLines = countLines(body);
  const shouldCollapse =
    !streaming &&
    (forceCollapse ||
      (preferCollapse &&
        (body.length > HARD_COLLAPSE_LENGTH ||
          totalLines > HARD_COLLAPSE_LINES ||
          (containsStructuredContent &&
            (body.length > STRUCTURED_COLLAPSE_LENGTH ||
              totalLines > STRUCTURED_COLLAPSE_LINES)) ||
          (!containsStructuredContent &&
            (plainTextBody.length > SOFT_COLLAPSE_LENGTH ||
              plainTextLines > SOFT_COLLAPSE_LINES)) ||
          (!containsStructuredContent &&
            (body.length > MAX_LENGTH * 1.65 || totalLines > MAX_LINES + 8)))));

  useEffect(() => {
    setExpanded(false);
  }, [body, shouldCollapse]);

  const content = (
    <div
      className={`message-markdown ${language === "zh-CN" ? "is-zh" : "is-en"} ${
        streaming ? "is-streaming" : ""
      }`}
    >
      <Suspense fallback={renderPlainText(body)}>
        <RichMarkdownRenderer body={body} language={language} />
      </Suspense>
    </div>
  );

  if (!shouldCollapse) {
    return content;
  }

  const previewLead = summaryOverride ?? leadParagraph ?? copy.foldedLeadFallback;
  const helperText = suppressPreviewItems ? copy.foldedMetaFallback : copy.expand;

  return (
    <details
      className="message-rich-content__fold"
      open={expanded}
      onToggle={(event) => {
        setExpanded(event.currentTarget.open);
      }}
    >
      <summary>
        <span className="message-rich-content__summary-shell">
          <span className="message-rich-content__summary-lead">{previewLead}</span>
          {!expanded && structuredPreview.length > 0 ? (
            <span className="message-rich-content__summary-detail">
              {structuredPreview.join(" · ")}
            </span>
          ) : null}
          <span className="message-rich-content__summary-meta">
            {expanded ? copy.collapse : helperText}
          </span>
        </span>
      </summary>
      <div className="message-rich-content__fold-body">{content}</div>
    </details>
  );
}
