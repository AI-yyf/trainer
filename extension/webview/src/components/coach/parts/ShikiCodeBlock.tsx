import { useEffect, useMemo, useState } from "react";


/**
 * Shiki is imported lazily, and it has to be.
 *
 * A top-level `import { codeToHtml } from "shiki"` pulls *every* bundled
 * grammar into the eager graph — the production build was emitting cpp at
 * 785 kB, emacs-lisp at 790 kB, wasm at 622 kB, and dozens more, none of which
 * a coach reply ever highlights. VS Code loads this webview on every sidebar
 * activation, so all of that was being parsed and held in memory before the
 * first message rendered.
 *
 * `codeToHtml` is only ever called from an async function, so a dynamic import
 * costs nothing in code shape and keeps the grammars out of the initial load.
 */
type ShikiModule = typeof import("shiki");
type ShikiHighlighter = Awaited<ReturnType<ShikiModule["createHighlighter"]>>;

let shikiModulePromise: Promise<ShikiModule> | undefined;
let javaScriptEngine: ReturnType<ShikiModule["createJavaScriptRegexEngine"]> | undefined;
const highlighterCache = new Map<ThemeName, Promise<ShikiHighlighter>>();

async function loadShikiModule(): Promise<ShikiModule> {
  shikiModulePromise ??= import("shiki");
  return shikiModulePromise;
}

/**
 * The Oniguruma engine needs WebAssembly, which the VS Code webview CSP
 * blocks; the failure was silent, so every block fell back to plain text.
 * Shiki's JavaScript engine is slower but wasm-free and safe here.
 *
 * `codeToHtml`'s shorthand uses the wasm engine; an explicit highlighter is
 * required to inject the JavaScript engine. Cache one per language/theme.
 */
async function getHighlighter(themeName: ThemeName): Promise<ShikiHighlighter> {
  let pending = highlighterCache.get(themeName);
  if (!pending) {
    pending = (async () => {
      const shiki = await loadShikiModule();
      javaScriptEngine ??= shiki.createJavaScriptRegexEngine();
      return shiki.createHighlighter({
        themes: [themeName],
        langs: [],
        engine: javaScriptEngine,
      });
    })().catch((error) => {
      // A transient grammar/chunk failure must not stick for the session.
      highlighterCache.delete(themeName);
      throw error;
    });
    highlighterCache.set(themeName, pending);
  }
  return pending;
}

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

  const highlighter = await getHighlighter(themeName);
  await highlighter.loadLanguage(languageId as never);
  const html = highlighter.codeToHtml(code, {
    lang: languageId as never,
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
  /** Live tail of a streaming reply: skip re-highlighting long growing code. */
  streaming?: boolean;
}

// Async Shiki highlighting of a code block that grows every frame is quadratic
// over the stream; long live code renders plain and highlights once it closes.
const STREAMING_HIGHLIGHT_LIMIT = 1200;

export function ShikiCodeBlock({ code, languageId = "text", streaming = false }: ShikiCodeBlockProps) {
  const [html, setHtml] = useState<string>();
  const [themeName, setThemeName] = useState<ThemeName>(() => getWorkbenchThemeName());

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setThemeName(getWorkbenchThemeName());
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "class", "data-vscode-theme-kind"],
    });
    return () => observer.disconnect();
  }, []);
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
      <pre className="message-markdown__code-block">
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
        ...classList.split(/\s+/),
      ]
        .filter(Boolean)
        .join(" ");
      return `<pre class="${nextClassList}"`;
    },
  );

  // Trusted local output: Shiki escapes the code and owns the markup. Running
  // the model-HTML sanitizer here strips every inline token color, which is
  // why the thread previously showed plain code blocks.
  return <div dangerouslySetInnerHTML={{ __html: renderedHtml }} />;
}
