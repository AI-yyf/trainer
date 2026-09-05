import { useMemo, useState } from "react";

import type { FilePreviewPart } from "../../../lib/types";
import { sanitizePreviewHtml } from "../../../lib/htmlSanitizer";
import {
  getStructuredPreviewFormat,
  isDocxPreviewPath,
  isArchivePreviewPath,
  isNotebookPreviewPath,
  isPresentationPreviewPath,
  isSpreadsheetPreviewPath,
  isTabularPreviewPath,
  getPreviewFormatBadge,
  getPreviewKindLabel,
  getPreviewModeSummary,
  getPreviewTierLabel,
} from "../../../../../../shared/src/previewAssets";
import { DocxPreview } from "../../preview/DocxPreview";
import { AudioPreview } from "../../preview/AudioPreview";
import { PdfPreview, isPdfPreviewPath } from "../../preview/PdfPreview";
import { renderPreviewBody } from "../../preview/PreviewBody";
import { renderStructuredPreview } from "./StructuredPreview";

export interface FilePreviewRendererProps {
  part: FilePreviewPart;
  className?: string;
}

const MAX_PREVIEW_LINES = 18;

function detectLanguage(filename: string, explicitLanguage?: string): string {
  if (explicitLanguage?.trim()) {
    return explicitLanguage.trim();
  }
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  const langMap: Record<string, string> = {
    ts: "typescript",
    tsx: "tsx",
    js: "javascript",
    jsx: "jsx",
    py: "python",
    rb: "ruby",
    go: "go",
    rs: "rust",
    java: "java",
    c: "c",
    cpp: "cpp",
    cs: "csharp",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    xml: "xml",
    html: "html",
    css: "css",
    md: "markdown",
    sql: "sql",
    sh: "bash",
    bash: "bash",
    zsh: "bash",
    ps1: "powershell",
    toml: "toml",
    ini: "ini",
  };
  return langMap[ext] || "text";
}

function getFilenameFromPath(path: string, fallbackTitle?: string): string {
  const parts = path.split(/[/\\]/);
  return parts[parts.length - 1] || fallbackTitle || path || "preview";
}

function previewTierLabel(part: FilePreviewPart): string | undefined {
  if (part.previewTier === "rich") {
    return "Tier A · Rich preview";
  }
  if (part.previewTier === "converted") {
    return "Tier B · Converted preview";
  }
  if (part.previewTier === "metadata") {
    return "Tier C · Metadata fallback";
  }
  return undefined;
}

function previewKindLabel(part: FilePreviewPart): string | undefined {
  const kind = part.previewKind;
  if (!kind) {
    return undefined;
  }
  if (kind === "document" && isPdfPreviewPath(part.path)) {
    return "PDF";
  }
  if (kind === "document" && isDocxPreviewPath(part.path)) {
    return "DOCX";
  }
  if (kind === "table" && isSpreadsheetPreviewPath(part.path)) {
    return "Spreadsheet";
  }
  if (kind === "table" && isTabularPreviewPath(part.path)) {
    return "Table";
  }
  if (kind === "notebook" || isNotebookPreviewPath(part.path)) {
    return "Notebook";
  }
  if (kind === "archive" || isArchivePreviewPath(part.path)) {
    return "Archive";
  }
  if (kind === "document" && isPresentationPreviewPath(part.path)) {
    return "Presentation";
  }
  const labels = new Map<string, string>([
    ["markdown", "Markdown"],
    ["code", "Code"],
    ["table", "Table"],
    ["document", "Document"],
    ["notebook", "Notebook"],
    ["image", "Image"],
    ["audio", "Audio"],
    ["video", "Video"],
    ["archive", "Archive"],
    ["structured-text", "Structured text"],
    ["markup", "Markup"],
    ["text", "Text"],
  ]);
  return labels.get(kind) ?? kind;
}

function previewGuidance(part: FilePreviewPart): string {
  if (part.previewKind === "document" && part.assetUri && isPdfPreviewPath(part.path)) {
    return "Trainer is rendering this PDF with a rich in-thread viewer so you can inspect it without leaving the coaching flow.";
  }
  if (part.previewKind === "document" && part.assetUri && isDocxPreviewPath(part.path)) {
    return "Trainer is rendering this DOCX with an in-thread viewer so the sidebar can keep a rich document preview.";
  }
  if (part.previewTier === "metadata" && ["image", "audio", "video"].includes(part.previewKind ?? "")) {
    return "This quick preview stays lightweight inside the coach thread. Open the source file if you need the full native experience.";
  }
  if (part.previewTier === "metadata" && part.previewKind === "archive") {
    return "Archives stay at metadata level here so the thread remains readable and workspace-bounded.";
  }
  if (part.previewKind === "archive" && part.previewTier === "converted") {
    return "Trainer is using a governed entry index here so the thread can teach from entry names and snippets without unpacking the archive live.";
  }
  if (part.previewKind === "table" && part.previewTier === "rich") {
    return isSpreadsheetPreviewPath(part.path)
      ? "Trainer is rendering this spreadsheet as rows and columns so the thread can teach from the cells directly."
      : "Trainer is rendering this tabular resource as rows and columns so the thread can teach from the data structure directly.";
  }
  if (part.previewKind === "notebook") {
    return "Trainer is rendering this notebook as a compact cell outline so the thread can teach from the notebook structure directly.";
  }
  if (part.previewKind === "archive") {
    return "Trainer is rendering this archive as a governed entry index so the thread can teach from entries without unpacking everything inline.";
  }
  if (part.previewKind === "document" && isPresentationPreviewPath(part.path)) {
    return "Trainer is rendering this presentation as a structured outline so the thread can teach from titles and slide notes first.";
  }
  if (part.previewTier === "converted") {
    const structuredFormat = getStructuredPreviewFormat(part.structuredData);
    if (part.previewKind === "table" && structuredFormat === "xlsx") {
      return "Trainer is using converted spreadsheet rows so the thread can teach from sample cells without pretending to be a full spreadsheet app.";
    }
    if (part.previewKind === "document" && structuredFormat === "pptx") {
      return "Trainer is using converted presentation structure so the thread can teach from the slide outline without pretending to be a full deck editor.";
    }
    return "Trainer is using converted text here so the agent can cite and teach from it without pretending to be a full document viewer.";
  }
  return "Trainer keeps this preview lightweight inside the message thread so you can inspect it without leaving the coaching flow.";
}

export function FilePreviewRenderer({ part, className }: FilePreviewRendererProps) {
  const [expanded, setExpanded] = useState(false);

  const filename = getFilenameFromPath(part.path, part.title);
  const language = detectLanguage(filename, part.language);
  const tierLabel = getPreviewTierLabel(part.previewTier, "en");
  const kindLabel = getPreviewKindLabel(part.previewKind, part.path, "en");
  const formatBadge = getPreviewFormatBadge(part.structuredData, part.path);
  const contentLines = useMemo(() => {
    const content = part.content?.replace(/\r\n/g, "\n") ?? "";
    return content ? content.split("\n") : [];
  }, [part.content]);

  const visibleLines = expanded ? contentLines : contentLines.slice(0, MAX_PREVIEW_LINES);
  const hasCollapsedContent = contentLines.length > MAX_PREVIEW_LINES;
  const displayPath = part.path || part.artifactPath || filename;
  const canRenderImagePreview = part.previewKind === "image" && Boolean(part.assetUri);
  const canRenderAudioPreview = part.previewKind === "audio" && Boolean(part.assetUri);
  const canRenderVideoPreview = part.previewKind === "video" && Boolean(part.assetUri);
  const canRenderDocxPreview =
    part.previewKind === "document" &&
    Boolean(part.assetUri) &&
    isDocxPreviewPath(part.path);
  const canRenderPdfPreview =
    part.previewKind === "document" &&
    Boolean(part.assetUri) &&
    isPdfPreviewPath(part.path);
  const documentPreviewSrc = canRenderPdfPreview || canRenderDocxPreview ? part.assetUri : undefined;
  const audioPreviewSrc = canRenderAudioPreview ? part.assetUri : undefined;
  const sanitizedHtml = useMemo(() => sanitizePreviewHtml(part.html), [part.html]);
  const previewHtml = canRenderDocxPreview ? undefined : sanitizedHtml;
  const structuredPreview = renderStructuredPreview(part.structuredData, part.previewKind, part.content);
  const previewSummary = getPreviewModeSummary(part, "en");
  const emptyCopy = part.canNativeOpen
    ? "No inline content is attached yet. Open the source file or artifact for the fuller view."
    : "No inline preview content is attached yet.";
  const textBody =
    !canRenderImagePreview &&
    !canRenderAudioPreview &&
    !canRenderVideoPreview &&
    !canRenderDocxPreview &&
    !canRenderPdfPreview &&
    part.content ? (
      <div className="file-preview-renderer__body">
        <pre className="file-preview-renderer__content">{visibleLines.join("\n")}</pre>
        {hasCollapsedContent ? (
          <button
            className="file-preview-renderer__toggle"
            type="button"
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? "Show less" : `Show ${contentLines.length - MAX_PREVIEW_LINES} more lines`}
          </button>
        ) : null}
      </div>
    ) : undefined;

  return (
    <div className={`file-preview-renderer ${className ?? ""}`}>
      <div className="file-preview-renderer__header">
        <span className="file-preview-renderer__icon" aria-hidden="true">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </svg>
        </span>
        <span className="file-preview-renderer__filename">{part.title || filename}</span>
        <span className="file-preview-renderer__lang">{language}</span>
      </div>

      <div className="file-preview-renderer__path">
        <code>{displayPath}</code>
      </div>

      <div className="file-preview-renderer__facts">
        {tierLabel ? <span>{tierLabel}</span> : null}
        {kindLabel ? <span>{kindLabel}</span> : null}
        {formatBadge ? <span>{formatBadge}</span> : null}
        {part.renderedFrom ? <span>Rendered from {part.renderedFrom}</span> : null}
        {part.truncated ? <span>Truncated</span> : null}
      </div>

      <div className="file-preview-renderer__summary">{previewSummary}</div>

      {canRenderImagePreview ? (
        <div className="file-preview-renderer__media">
          <img src={part.assetUri} alt={part.title || filename} />
        </div>
      ) : null}

      {audioPreviewSrc ? (
        <AudioPreview
          src={audioPreviewSrc}
          title={part.title ?? filename}
          className="file-preview-renderer__audio"
          compact
        />
      ) : null}

      {canRenderVideoPreview ? (
        <div className="file-preview-renderer__media">
          <video controls preload="metadata" src={part.assetUri} />
        </div>
      ) : null}

      {canRenderDocxPreview && documentPreviewSrc ? (
        <DocxPreview
          src={documentPreviewSrc}
          title={part.title || filename}
          className="file-preview-renderer__docx"
          compact
        />
      ) : null}

      {canRenderPdfPreview && documentPreviewSrc ? (
        <PdfPreview
          src={documentPreviewSrc}
          title={part.title || filename}
          className="file-preview-renderer__pdf"
          compact
        />
      ) : null}

      {!canRenderImagePreview && !canRenderAudioPreview && !canRenderVideoPreview && !canRenderDocxPreview && !canRenderPdfPreview ? (
        renderPreviewBody({
          html: previewHtml,
          structuredPreview,
          textBody,
          emptyMessage: emptyCopy,
          htmlClassName: "file-preview-renderer__html",
          structuredClassName: "file-preview-renderer__body",
          emptyClassName: "file-preview-renderer__empty",
        })
      ) : null}

      <div className="file-preview-renderer__meta">
        {part.artifactPath ? <span>Artifact: {part.artifactPath}</span> : null}
        {part.resourceId ? <span>Resource: {part.resourceId}</span> : null}
        {part.assetUri ? <span>Quick preview ready</span> : null}
        {part.canNativeOpen ? <span>Native open available</span> : null}
      </div>
    </div>
  );
}



