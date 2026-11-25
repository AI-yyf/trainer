import { memo, Suspense, createContext, lazy, useContext, useEffect, useId, useMemo, useState } from "react";
import type { Element } from "hast";

import type { ComposerLanguage } from "../../lib/types";
import { messageRichContentCopy } from "../../lib/i18n/segments/messageRichContentCopy";
import { classifyImageUrl, describeRemoteImageHost, remoteImageLabels } from "../../lib/remoteImages";
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

const SAFE_IMAGE_DATA_URL_RE =
  /^data:image\/(?:png|jpeg|jpg|webp|gif|svg\+xml);base64,[A-Za-z0-9+/=]+$/;

/**
 * Sanitize markdown href/src URLs so generated SVG/PNG data URIs and localhost
 * image routes render safely while scriptable/HTML data URLs stay blocked.
 */
export function markdownUrlTransform(url: string, key?: string): string {
  const raw = String(url ?? "").trim();
  if (!raw) {
    return "";
  }
  const lower = raw.toLowerCase();
  if (
    lower.startsWith("javascript:") ||
    lower.startsWith("vbscript:") ||
    lower.startsWith("trainer-image://")
  ) {
    return "";
  }
  if (lower.startsWith("data:")) {
    if (key && key !== "src") {
      return "";
    }
    return SAFE_IMAGE_DATA_URL_RE.test(raw) ? raw : "";
  }
  if (
    lower.startsWith("https://") ||
    lower.startsWith("http://") ||
    lower.startsWith("vscode-resource:") ||
    lower.startsWith("vscode-webview-resource:") ||
    lower.startsWith("blob:")
  ) {
    return raw;
  }
  if (key !== "src") {
    if (
      lower.startsWith("mailto:") ||
      raw.startsWith("#") ||
      raw.startsWith("/")
    ) {
      return raw;
    }
  }
  return "";
}

function ImageLightbox({
  src,
  alt,
  language,
  onClose,
}: {
  src: string;
  alt?: string;
  language: ComposerLanguage;
  onClose: () => void;
}) {
  const closeLabel = messageRichContentCopy(language, "关闭预览");
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="message-image-lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={alt || messageRichContentCopy(language, "配图")}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="message-image-lightbox__dialog">
        <button
          type="button"
          className="message-image-lightbox__close"
          onClick={onClose}
        >
          {closeLabel}
        </button>
        <img className="message-image-lightbox__img" src={src} alt={alt || ""} />
        {alt ? <p className="message-image-lightbox__caption">{alt}</p> : null}
      </div>
    </div>
  );
}

export function RichMarkdownImage({
  src,
  alt,
  language,
}: {
  src?: string;
  alt?: string;
  language: ComposerLanguage;
}) {
  const [failed, setFailed] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  // A remote image loads only after the learner asks for it (see
  // lib/remoteImages.ts); this resets with the address, never persists.
  const [loadRemote, setLoadRemote] = useState(false);
  const cleanSrc = markdownUrlTransform(src ?? "", "src");
  const cleanAlt = String(alt ?? "").trim();
  const sourceKind = classifyImageUrl(cleanSrc);

  if (!cleanSrc || sourceKind === null || failed) {
    return (
      <figure className="message-rich-image" data-rich-image="error">
        <p className="message-rich-image__error">
          {messageRichContentCopy(language, "图片加载失败")}
          {cleanAlt ? ` (${cleanAlt})` : ""}
        </p>
      </figure>
    );
  }

  if (sourceKind === "remote" && !loadRemote) {
    const labels = remoteImageLabels();
    const host = describeRemoteImageHost(cleanSrc);
    return (
      <figure className="message-rich-image" data-rich-image="remote">
        <button
          type="button"
          className="trainer-remote-image"
          title={labels.hint}
          aria-label={`${labels.load} · ${host}`}
          onClick={() => setLoadRemote(true)}
        >
          <span className="trainer-remote-image__icon" aria-hidden="true">
            ▣
          </span>
          <span className="trainer-remote-image__text">
            <span className="trainer-remote-image__label">{labels.load}</span>
            {host ? <span className="trainer-remote-image__host">{host}</span> : null}
            {cleanAlt ? <span className="trainer-remote-image__alt">{cleanAlt}</span> : null}
          </span>
        </button>
      </figure>
    );
  }

  const zoomHint = messageRichContentCopy(language, "点击放大查看");
  const figureLabel = cleanAlt || messageRichContentCopy(language, "配图");

  return (
    <>
      <figure className="message-rich-image" data-rich-image="true">
        <button
          type="button"
          className="message-rich-image__trigger"
          aria-label={`${figureLabel} · ${zoomHint}`}
          onClick={() => setZoomed(true)}
        >
          <img
            className="message-rich-image__img"
            src={cleanSrc}
            alt={cleanAlt}
            loading="lazy"
            onError={() => setFailed(true)}
          />
        </button>
        {cleanAlt ? (
          <figcaption className="message-rich-image__caption">{cleanAlt}</figcaption>
        ) : null}
      </figure>
      {zoomed ? (
        <ImageLightbox
          src={cleanSrc}
          alt={cleanAlt}
          language={language}
          onClose={() => setZoomed(false)}
        />
      ) : null}
    </>
  );
}

export function MessageImageGallery({
  previews,
  language,
}: {
  previews?: Array<{ id: string; name?: string; mimeType: string; dataUrl: string }>;
  language: ComposerLanguage;
}) {
  const [active, setActive] = useState<{ src: string; alt?: string } | null>(null);
  // Attachments are the learner's own files: only a local image address
  // belongs here, and nothing in the gallery ever fetches from another site.
  const safePreviews = (previews ?? []).filter(
    (item) => classifyImageUrl(markdownUrlTransform(item.dataUrl, "src")) === "local",
  );
  if (safePreviews.length === 0) {
    return null;
  }
  const zoomHint = messageRichContentCopy(language, "点击放大查看");
  return (
    <>
      <div className="message-attachment-gallery" data-image-attachment-gallery="true">
        {safePreviews.map((item) => {
          const label = item.name?.trim() || messageRichContentCopy(language, "配图");
          return (
            <button
              key={item.id}
              type="button"
              className="message-attachment-gallery__thumb"
              aria-label={`${label} · ${zoomHint}`}
              onClick={() => setActive({ src: item.dataUrl, alt: label })}
            >
              <img
                className="message-attachment-gallery__img"
                src={item.dataUrl}
                alt={label}
                loading="lazy"
              />
            </button>
          );
        })}
      </div>
      {active ? (
        <ImageLightbox
          src={active.src}
          alt={active.alt}
          language={language}
          onClose={() => setActive(null)}
        />
      ) : null}
    </>
  );
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
      urlTransform={markdownUrlTransform}
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
      components={{
        img({ src, alt }) {
          return <RichMarkdownImage src={src} alt={alt} language={language} />;
        },
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
  let blockStart = 0;
  let lastStableLine = -1;
  const stableBlocks: string[] = [];

  const pushBlock = (from: number, toInclusive: number) => {
    const chunk = lines.slice(from, toInclusive + 1).join("\n").trim();
    if (chunk) {
      stableBlocks.push(chunk);
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (inFence) {
      if (trimmed.startsWith(fence)) {
        inFence = false;
        pushBlock(blockStart, i);
        lastStableLine = i;
        blockStart = i + 1;
      }
      continue;
    }
    if (trimmed.startsWith("```") || trimmed.startsWith("~~~")) {
      // Flush any prose preceding the code fence before starting the fence block.
      if (i > blockStart) {
        pushBlock(blockStart, i - 1);
        lastStableLine = i - 1;
      }
      blockStart = i;
      inFence = true;
      fence = trimmed.slice(0, 3);
      continue;
    }
    if (trimmed === "$$") {
      if (inMath) {
        inMath = false;
        pushBlock(blockStart, i);
        lastStableLine = i;
        blockStart = i + 1;
      } else {
        if (i > blockStart) {
          pushBlock(blockStart, i - 1);
          lastStableLine = i - 1;
        }
        blockStart = i;
        inMath = true;
      }
      continue;
    }
    if (inMath) {
      continue;
    }
    if (trimmed === "") {
      if (i > blockStart) {
        pushBlock(blockStart, i - 1);
        lastStableLine = i - 1;
      }
      blockStart = i + 1;
    }
  }
  if (lastStableLine < 0) {
    return { stableBlocks: [], tail: body };
  }
  const tail = lines.slice(lastStableLine + 1).join("\n");
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
  body: rawBody,
  language,
  streaming = false,
}: MessageRichContentProps) {
  // Coach replies may carry LaTeX in \[ \] / \( \) delimiters that
  // remark-math cannot parse; normalize outside code fences/spans.
  const body = useMemo(() => normalizeLatexDelimiters(rawBody), [rawBody]);
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
          <Suspense fallback={<MarkdownLoading language={language} />}>
            <RichMarkdownRenderer body={split.tail} language={language} streaming />
          </Suspense>
        </>
      ) : (
        <Suspense fallback={<MarkdownLoading language={language} />}>
          <RichMarkdownRenderer body={body} language={language} />
        </Suspense>
      )}
    </div>
  );
  return content;
}

export const MessageRichContent = memo(MessageRichContentImpl);
