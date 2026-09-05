/**
 * Code Block Renderer
 *
 * Syntax-highlighted code display using Shiki.
 * Reference: docs/open-source-fit-and-provider-strategy.md §3, §7.7
 */

import React, { useMemo } from "react";
import { createHighlighter, type Highlighter } from "shiki";

import { sanitizePreviewHtml } from "../../lib/htmlSanitizer";

export interface CodeRendererProps {
  code: string;
  language?: string;
  /** Maximum lines to show before truncation */
  maxLines?: number;
  /** Whether to show line numbers */
  showLineNumbers?: boolean;
  /** Theme for syntax highlighting */
  theme?: "github-dark" | "github-light" | "vs-dark" | "vs-light";
}

/**
 * Map Trainer language identifiers to Shiki language identifiers
 */
const LANGUAGE_MAP: Record<string, string> = {
  // JavaScript/TypeScript
  javascript: "javascript",
  js: "javascript",
  typescript: "typescript",
  ts: "typescript",
  tsx: "tsx",
  jsx: "jsx",

  // Python
  python: "python",
  py: "python",

  // Web
  html: "html",
  css: "css",
  scss: "scss",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  xml: "xml",

  // Shell
  bash: "bash",
  sh: "bash",
  zsh: "bash",
  shell: "bash",
  powershell: "powershell",
  ps1: "powershell",

  // Systems
  c: "c",
  cpp: "cpp",
  "c++": "cpp",
  rust: "rust",
  go: "go",
  java: "java",

  // Languages
  ruby: "ruby",
  rb: "ruby",
  php: "php",
  swift: "swift",
  kotlin: "kotlin",
  scala: "scala",
  r: "r",
  lua: "lua",
  perl: "perl",
  sql: "sql",
  csharp: "csharp",
  cs: "csharp",
  fsharp: "fsharp",
  fs: "fsharp",

  // Data
  csv: "csv",
  tsv: "tsv",
  markdown: "markdown",
  md: "markdown",

  // Diff
  diff: "diff",
  patch: "diff",

  // Config
  ini: "ini",
  toml: "toml",
  env: "bash",

  // Markup
  svg: "svg",
  text: "text",
};

// Module-level Shiki highlighter singleton — initialized once, shared across all instances
let _highlighterPromise: Promise<Highlighter> | null = null;
let _highlighter: Highlighter | null = null;

function getHighlighter(): Highlighter | null {
  return _highlighter;
}

function initHighlighter(): Promise<Highlighter> {
  if (!_highlighterPromise) {
    _highlighterPromise = createHighlighter({
      themes: ["github-dark", "github-light"],
      langs: Object.values(LANGUAGE_MAP),
    }).then((h) => {
      _highlighter = h;
      return h;
    });
  }
  return _highlighterPromise;
}

export const CodeRenderer: React.FC<CodeRendererProps> = ({
  code,
  language,
  maxLines = 100,
  showLineNumbers = true,
  theme = "github-dark",
}) => {
  // Normalize language identifier
  const normalizedLang = useMemo(() => {
    if (!language) return null;
    const lower = language.toLowerCase().trim();
    return LANGUAGE_MAP[lower] ?? lower;
  }, [language]);

  // Truncate code if too long
  const { displayCode, isTruncated, lineCount } = useMemo(() => {
    const lines = code.split("\n");
    const totalLines = lines.length;
    const truncatedLines = lines.slice(0, maxLines);
    return {
      displayCode: truncatedLines.join("\n"),
      isTruncated: totalLines > maxLines,
      lineCount: totalLines,
    };
  }, [code, maxLines]);

  // Generate line numbers
  const lineNumbers = useMemo(() => {
    if (!showLineNumbers) return null;
    const lineCount = displayCode.split("\n").length;
    return Array.from({ length: lineCount }, (_, i) => i + 1);
  }, [displayCode, showLineNumbers]);

  const [highlighterReady, setHighlighterReady] = React.useState(_highlighter !== null);

  React.useEffect(() => {
    initHighlighter().then(() => setHighlighterReady(true));
  }, []);

  // Generate Shiki-highlighted HTML using real Shiki (MIT)
  const highlightedHtml = useMemo(() => {
    const hl = getHighlighter();
    if (!highlighterReady || !hl || !code) return null;
    const shikiLang = LANGUAGE_MAP[normalizedLang ?? ""] ?? normalizedLang;
    const selectedTheme = theme === "github-light" ? "github-light" : "github-dark";
    try {
      return hl.codeToHtml(code, { lang: shikiLang ?? "text", theme: selectedTheme });
    } catch {
      return null;
    }
  }, [highlighterReady, code, normalizedLang, theme]);

  // Fallback plain text lines when Shiki fails or no language
  const plainLines = useMemo(() => {
    if (highlightedHtml) return null;
    return displayCode.split("\n").map((line, i) => (
      <span key={i} className="code-line">
        {line || " "}
      </span>
    ));
  }, [highlightedHtml, displayCode]);

  return (
    <div className={`trainer-code-renderer theme-${theme}`} data-language={normalizedLang}>
      <div className="code-header">
        {normalizedLang && <span className="code-language">{normalizedLang}</span>}
        <span className="code-line-count">{lineCount} lines</span>
      </div>
      <div className="code-content">
        {showLineNumbers && lineNumbers && !highlightedHtml && (
          <div className="code-line-numbers" aria-hidden="true">
            {lineNumbers.map((num) => (
              <span key={num} className="line-number">
                {num}
              </span>
            ))}
          </div>
        )}
        {highlightedHtml ? (
          <div
            className="code-shiki"
            dangerouslySetInnerHTML={{ __html: sanitizePreviewHtml(highlightedHtml) }}
          />
        ) : (
          <pre className="code-block">
            <code className={`language-${normalizedLang ?? "text"}`}>{plainLines}</code>
          </pre>
        )}
      </div>
      {isTruncated && (
        <div className="code-truncation-notice">
          <span className="truncation-icon">!</span>
          <span className="truncation-text">
            Code truncated at {maxLines} lines. Full file available via native editor.
          </span>
        </div>
      )}
    </div>
  );
};

export default CodeRenderer;
