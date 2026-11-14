import { memo, Suspense, createContext, lazy, useContext, useDeferredValue, useEffect, useId, useMemo, useState } from "react";
import type { Element } from "hast";
import type { Components } from "react-markdown";

import type { ComposerLanguage } from "../../lib/types";
import { messageRichContentCopy } from "../../lib/i18n/segments/messageRichContentCopy";
import { MermaidBlock } from "./MermaidBlock";
import { RichCodeBlock } from "./RichCodeBlock";
import { resolveCodeBlockCopy } from "./codeBlockCopy";
import { normalizeLatexDelimiters } from "../../../../../shared/src/latexDelimiters";
import { remarkChatBreaks } from "../../lib/remarkChatBreaks";
import { rehypeChatScripts } from "../../lib/rehypeChatScripts";

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
    import("katex/contrib/mhchem"),
    import("rehype-katex"),
    import("remark-gfm"),
    import("remark-math"),
  ]).then(([, rehypeKatex, remarkGfm, remarkMath]) => ({
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
const MarkdownStreamingContext = createContext(false);

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
  return {
    code: codeBlockCopy.code,
    diagram: messageRichContentCopy(language, "图表"),
    mindmap: messageRichContentCopy(language, "思维导图"),
    table: messageRichContentCopy(language, "表格"),
    renderError: messageRichContentCopy(language, "图表渲染失败，已回退为原始内容。"),
    loading: messageRichContentCopy(language, "正在整理显示…"),
    copy: codeBlockCopy.copy,
    copied: codeBlockCopy.copied,
  };
}

/** 插件就绪前的加载态：绝不渲染原始正文（原始 LaTeX 会闪现）。 */
function MarkdownLoading({ language }: { language: ComposerLanguage }) {
  return (
    <div className="message-markdown message-markdown--loading" data-markdown-loading="true">
      <p className="template-metadata">{messageRichContentCopy(language, "正在整理显示…")}</p>
    </div>
  );
}

// 行内代码组件
function InlineCode({ children }: { children: React.ReactNode }) {
  return <code className="message-markdown__inline-code">{children}</code>;
}

const RichMarkdownRenderer = memo(function RichMarkdownRenderer({
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
  const copy = useMemo(() => labels(language), [language]);

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

  const components = useMemo<Components>(() => ({
    // 处理代码元素 - 区分行内代码和代码块
    code({ className, children }) {
      const streaming = useContext(MarkdownStreamingContext);
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
            loadingLabel={copy.loading}
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
    a({ node, children, href, ...props }) {
      // External links leave the webview instead of replacing Trainer.
      return (
        <a
          {...props}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
        >
          {children}
        </a>
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
            messageRichContentCopy(language, "列"),
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
  }), [copy, language]);

  if (!plugins) {
    // 懒加载插件就绪前绝不渲染原始正文：模型回复常含 \( \) / \[ \] 公式，
    // 纯文本瞬态会把原始反斜杠直接闪给学习者（窄侧栏下尤其刺眼）。
    return (
      <div className="message-markdown message-markdown--loading" data-markdown-loading="true">
        <p className="template-metadata">{copy.loading}</p>
      </div>
    );
  }

  return (
    <ReactMarkdown
      rehypePlugins={[
        [
          plugins.rehypeKatex,
          {
            throwOnError: false,
            strict: "ignore",
            errorColor: "var(--fg-1)",
          },
        ],
        rehypeChatScripts,
      ]}
      remarkPlugins={[[plugins.remarkGfm, { singleTilde: false }], remarkChatBreaks, plugins.remarkMath]}
      components={components}
    >
      {body}
    </ReactMarkdown>
  );
});

export interface MessageRichContentProps {
  body: string;
  language: ComposerLanguage;
  streaming?: boolean;
}

function MessageRichContentImpl({
  body: rawBody,
  language,
  streaming = false,
}: MessageRichContentProps) {
  // Keep Markdown grammar context across chunks, including list continuations,
  // blank lines inside fences, and references defined later in the reply.
  const deferredBody = useDeferredValue(rawBody);
  const visibleBody = streaming ? deferredBody : rawBody;
  const body = useMemo(() => normalizeLatexDelimiters(visibleBody), [visibleBody]);

  return (
    <div
      className={`message-markdown ${language === "zh-CN" ? "is-zh" : "is-en"} ${
        streaming ? "is-streaming" : ""
      }`}
    >
      <MarkdownStreamingContext.Provider value={streaming}>
        <Suspense fallback={<MarkdownLoading language={language} />}>
          <RichMarkdownRenderer body={body} language={language} />
        </Suspense>
      </MarkdownStreamingContext.Provider>
    </div>
  );
}

export const MessageRichContent = memo(MessageRichContentImpl);
