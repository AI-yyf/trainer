import { memo, Suspense, createContext, lazy, useContext, useEffect, useId, useMemo, useState } from "react";
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

function labels(language: ComposerLanguage) {
  const codeBlockCopy = resolveCodeBlockCopy(language);
  if (language === "zh-CN") {
    return {
      code: codeBlockCopy.code,
      diagram: "图表",
      mindmap: "思维导图",
      table: "表格",
      renderError: "图表渲染失败，已回退为原始内容。",
      loading: "正在整理显示…",
      copy: codeBlockCopy.copy,
      copied: codeBlockCopy.copied,
    };
  }

  return {
    code: codeBlockCopy.code,
    diagram: "Diagram",
    mindmap: "Mind map",
    table: "Table",
    renderError: "Diagram render failed. Showing the raw content instead.",
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

// 行内代码组件
function InlineCode({ children }: { children: React.ReactNode }) {
  return <code className="message-markdown__inline-code">{children}</code>;
}

function RichMarkdownRenderer({
  body,
  language,
  streaming = false,
}: {
  body: string;
  language: ComposerLanguage;
  /** Live tail of a streaming reply: long growing code blocks stay unhighlighted. */
  streaming?: boolean;
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
    return renderPlainText(body);
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
              streaming={streaming}
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
}

/**
 * While streaming, only the tail after the last completed markdown block
 * (paragraph boundary, closed code fence, or closed math block) changes from
 * frame to frame. Splitting there lets completed blocks render through
 * memoized components — one parse per block for the whole stream instead of a
 * full-document re-parse per frame (O(n²) over long replies).
 */
function splitStreamingBody(body: string): { stableBlocks: string[]; tail: string } {
  const lines = body.split("\n");
  let inFence = false;
  let fence = "";
  let inMath = false;
  let lastStableLine = -1;
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (inFence) {
      if (trimmed.startsWith(fence)) {
        inFence = false;
        lastStableLine = i;
      }
      continue;
    }
    if (trimmed.startsWith("```") || trimmed.startsWith("~~~")) {
      inFence = true;
      fence = trimmed.slice(0, 3);
      continue;
    }
    if (trimmed === "$$") {
      if (inMath) {
        inMath = false;
        lastStableLine = i;
      } else {
        inMath = true;
      }
      continue;
    }
    if (trimmed === "") {
      let previous = i - 1;
      while (previous >= 0 && lines[previous].trim() === "") {
        previous--;
      }
      if (previous >= 0) {
        lastStableLine = previous;
      }
    }
  }
  if (lastStableLine < 0) {
    return { stableBlocks: [], tail: body };
  }
  const stable = lines.slice(0, lastStableLine + 1).join("\n");
  const tail = lines.slice(lastStableLine + 1).join("\n");
  const stableBlocks = stable
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);
  return { stableBlocks, tail };
}

const StreamedStableBlock = memo(function StreamedStableBlock({
  body,
  language,
}: {
  body: string;
  language: ComposerLanguage;
}) {
  return <RichMarkdownRenderer body={body} language={language} />;
});

function MessageRichContentImpl({
  body,
  language,
  streaming = false,
}: MessageRichContentProps) {
  // Split per frame: cheap line scan keeps completed blocks byte-stable so
  // their memoized renderers never re-parse.
  const split = useMemo(
    () => (streaming ? splitStreamingBody(body) : null),
    [body, streaming],
  );
  const content = (
    <div
      className={`message-markdown ${language === "zh-CN" ? "is-zh" : "is-en"} ${
        streaming ? "is-streaming" : ""
      }`}
    >
      {split ? (
        <>
          {split.stableBlocks.map((block, index) => (
            <StreamedStableBlock key={index} body={block} language={language} />
          ))}
          <Suspense fallback={renderPlainText(split.tail)}>
            <RichMarkdownRenderer body={split.tail} language={language} streaming />
          </Suspense>
        </>
      ) : (
        <Suspense fallback={renderPlainText(body)}>
          <RichMarkdownRenderer body={body} language={language} />
        </Suspense>
      )}
    </div>
  );
  return content;
}

export const MessageRichContent = memo(MessageRichContentImpl);
