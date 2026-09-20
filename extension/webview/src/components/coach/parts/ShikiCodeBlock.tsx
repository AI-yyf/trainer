import { useEffect, useMemo, useState } from "react";

import { codeToHtml } from "shiki";

import { sanitizePreviewHtml } from "../../../lib/htmlSanitizer";

type ThemeName = "github-dark-default" | "github-light-default";

const SHIKI_THEME_BY_THEME: Record<string, ThemeName> = {
  dark: "github-dark-default",
  light: "github-light-default",
  system: "github-dark-default",
};

const shikiHtmlCache = new Map<string, string>();
// Streaming re-highlights every intermediate prefix of a growing code block;
// without a cap the cache grows once per delta. Evict the oldest entries.
const SHIKI_HTML_CACHE_LIMIT = 240;

function getWorkbenchThemeName(): ThemeName {
  if (typeof document === "undefined") {
    return "github-dark-default";
  }
  const theme = document.documentElement.dataset.theme ?? "dark";
  return SHIKI_THEME_BY_THEME[theme] ?? "github-dark-default";
}

function normalizeLanguage(languageId: string): string {
  const normalized = languageId.trim().toLowerCase();
  if (!normalized) {
    return "text";
  }
  if (normalized === "js") {
    return "javascript";
  }
  if (normalized === "ts") {
    return "typescript";
  }
  if (normalized === "md") {
    return "markdown";
  }
  if (normalized === "yml") {
    return "yaml";
  }
  if (normalized === "sh" || normalized === "shell") {
    return "bash";
  }
  return normalized;
}

async function highlightCode(code: string, languageId: string, themeName: ThemeName): Promise<string> {
  const key = `${themeName}::${languageId}::${code}`;
  const cached = shikiHtmlCache.get(key);
  if (cached) {
    return cached;
  }

  const html = await codeToHtml(code, {
    lang: normalizeLanguage(languageId) as never,
    theme: themeName,
  });
  shikiHtmlCache.set(key, html);
  while (shikiHtmlCache.size > SHIKI_HTML_CACHE_LIMIT) {
    const oldest = shikiHtmlCache.keys().next();
    if (oldest.done) {
      break;
    }
    shikiHtmlCache.delete(oldest.value);
  }
  return html;
}

export interface ShikiCodeBlockProps {
  code: string;
  languageId?: string;
  className?: string;
  /** Live tail of a streaming reply: skip re-highlighting long growing code. */
  streaming?: boolean;
}

// Async Shiki highlighting of a code block that grows every frame is quadratic
// over the stream; long live code renders plain and highlights once it closes.
const STREAMING_HIGHLIGHT_LIMIT = 1200;

export function ShikiCodeBlock({ code, languageId = "text", className, streaming = false }: ShikiCodeBlockProps) {
  const [html, setHtml] = useState<string>();
  const themeName = getWorkbenchThemeName();
  const normalizedLanguageId = useMemo(() => normalizeLanguage(languageId), [languageId]);

  const codeKey = useMemo(
    () => `${themeName}::${normalizedLanguageId}::${code}`,
    [code, normalizedLanguageId, themeName],
  );

  useEffect(() => {
    if (streaming && code.length > STREAMING_HIGHLIGHT_LIMIT) {
      setHtml(undefined);
      return;
    }
    let cancelled = false;

    const cached = shikiHtmlCache.get(codeKey);
    if (cached) {
      setHtml(cached);
      return () => {
        cancelled = true;
      };
    }

    void highlightCode(code, normalizedLanguageId, themeName)
      .then((nextHtml) => {
        if (!cancelled) {
          setHtml(nextHtml);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setHtml(undefined);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [code, codeKey, normalizedLanguageId, streaming, themeName]);

  if (!html) {
    return (
      <pre className={`message-markdown__code-block ${className ?? ""}`.trim()}>
        <code>{code}</code>
      </pre>
    );
  }

  const renderedHtml = html.replace(
    /^<pre class="([^"]+)"/,
    (_match, classList: string) => {
      const nextClassList = [
        "message-markdown__code-block",
        "message-markdown__code-block--shiki",
        className,
        ...classList.split(/\s+/),
      ]
        .filter(Boolean)
        .join(" ");
      return `<pre class="${nextClassList}"`;
    },
  );

  return (
    <div dangerouslySetInnerHTML={{ __html: sanitizePreviewHtml(renderedHtml) }} />
  );
}
