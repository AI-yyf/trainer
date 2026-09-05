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
  return html;
}

export interface ShikiCodeBlockProps {
  code: string;
  languageId?: string;
  className?: string;
}

export function ShikiCodeBlock({ code, languageId = "text", className }: ShikiCodeBlockProps) {
  const [html, setHtml] = useState<string>();
  const themeName = getWorkbenchThemeName();
  const normalizedLanguageId = useMemo(() => normalizeLanguage(languageId), [languageId]);

  const codeKey = useMemo(
    () => `${themeName}::${normalizedLanguageId}::${code}`,
    [code, normalizedLanguageId, themeName],
  );

  useEffect(() => {
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
  }, [code, codeKey, normalizedLanguageId, themeName]);

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
