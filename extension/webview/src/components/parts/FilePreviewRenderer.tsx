/**
 * File Preview Renderer
 *
 * Three-tier preview: Rich (Tier A), Converted (Tier B), Metadata (Tier C).
 * - PDF: react-pdf + PDF.js (MIT)
 * - DOCX: docx-preview + Mammoth.js (Apache-2.0 / BSD-2)
 * - Audio: wavesurfer.js (BSD-3)
 * - CSV/TSV: TanStack Table (MIT)
 * - PPTX: slide outline extraction
 * - XLSX: structured data preview
 * - text/code: inline content
 * - other: metadata + native open fallback (Tier C)
 *
 * Reference: docs/open-source-fit-and-provider-strategy.md §7.7
 */

import React, { useMemo } from "react";
import type { FilePreviewPart } from "@trainer/shared";
import {
  isPdfPreviewPath,
  isDocxPreviewPath,
  isTabularPreviewPath,
  isSpreadsheetPreviewPath,
  isPresentationPreviewPath,
  isArchivePreviewPath,
  isNotebookPreviewPath,
} from "../../../../../shared/src/previewAssets";
import { sanitizePreviewHtml } from "../../lib/htmlSanitizer";
import { PdfPreview } from "../preview/PdfPreview";
import { DocxPreview } from "../preview/DocxPreview";
import { AudioPreview } from "../preview/AudioPreview";
import { CSVPreview } from "./CSVPreview";
import { PPTXPreview } from "../preview/PPTXPreview";
import { XLSXPreview } from "../preview/XLSXPreview";

export interface FilePreviewRendererProps {
  part: FilePreviewPart;
  onClick?: () => void;
  onNativeOpen?: () => void;
}

/** Tier labels for display */
const TIER_CONFIG = {
  rich: { icon: "A", label: "Tier A", description: "Rich preview" },
  converted: { icon: "B", label: "Tier B", description: "Converted preview" },
  metadata: { icon: "C", label: "Tier C", description: "Metadata only" },
} as const;

function getTierInfo(tier: "rich" | "converted" | "metadata") {
  return TIER_CONFIG[tier] ?? TIER_CONFIG.metadata;
}

function NativeOpenButton({ onNativeOpen }: { onNativeOpen?: () => void }) {
  if (!onNativeOpen) return null;
  return (
    <button className="native-open-btn" onClick={onNativeOpen}>
      Open in Editor
    </button>
  );
}

function PreviewHeader({
  tier,
  previewKind,
  onNativeOpen,
}: {
  tier: "rich" | "converted" | "metadata";
  previewKind?: string;
  onNativeOpen?: () => void;
}) {
  const info = getTierInfo(tier);
  return (
    <div className="preview-header">
      <span className="preview-tier">{info.icon} {info.label}</span>
      {previewKind && <span className="preview-kind">{previewKind}</span>}
      <NativeOpenButton onNativeOpen={onNativeOpen} />
    </div>
  );
}

export const FilePreviewRenderer: React.FC<FilePreviewRendererProps> = ({
  part,
  onNativeOpen,
}) => {
  const {
    resourceId,
    path,
    title,
    content,
    html,
    assetUri,
    previewTier = "metadata",
    previewKind,
    canNativeOpen,
    structuredData,
    truncated,
  } = part;

  const tier = previewTier;
  const tierInfo = getTierInfo(tier);
  const filename = title ?? path?.split(/[/\\]/).pop() ?? "file";
  const sanitizedHtml = useMemo(() => sanitizePreviewHtml(html), [html]);

  // ─── Tier A: PDF rich preview ───────────────────────────────────────────
  if (isPdfPreviewPath(path) && assetUri) {
    return (
      <div className="trainer-file-preview" data-resource-id={resourceId}>
        <PreviewHeader tier="rich" previewKind="PDF" onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
        <PdfPreview src={assetUri} title={filename} />
      </div>
    );
  }

  // ─── Tier A: DOCX rich preview ───────────────────────────────────────────
  if (isDocxPreviewPath(path) && assetUri) {
    return (
      <div className="trainer-file-preview" data-resource-id={resourceId}>
        <PreviewHeader tier="rich" previewKind="DOCX" onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
        <DocxPreview src={assetUri} title={filename} />
      </div>
    );
  }

  // ─── Tier A: Audio rich preview ─────────────────────────────────────────
  if (
    (previewKind === "audio" || /\.(mp3|wav|ogg|flac|aac|m4a|opus)$/i.test(path ?? "")) &&
    assetUri
  ) {
    return (
      <div className="trainer-file-preview" data-resource-id={resourceId}>
        <PreviewHeader tier="rich" previewKind="Audio" onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
        <AudioPreview src={assetUri} title={filename} />
      </div>
    );
  }

  // ─── Tier A: CSV/TSV rich preview (TanStack Table) ─────────────────────
  if (isTabularPreviewPath(path) && content) {
    const delimiter = content.includes("\t") ? "\t" : ",";
    return (
      <div className="trainer-file-preview" data-resource-id={resourceId}>
        <PreviewHeader tier="rich" previewKind="Table" onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
        <CSVPreview content={content} filename={filename} delimiter={delimiter} maxRows={500} />
      </div>
    );
  }

  // ─── Tier A: PPTX structured outline ─────────────────────────────────────
  if (isPresentationPreviewPath(path) && content) {
    return (
      <div className="trainer-file-preview" data-resource-id={resourceId}>
        <PreviewHeader tier="rich" previewKind="Presentation" onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
        <PPTXPreview markdown={content} filename={filename} />
      </div>
    );
  }

  // ─── Tier A: XLSX structured data preview ─────────────────────────────────
  if (isSpreadsheetPreviewPath(path)) {
    return (
      <div className="trainer-file-preview" data-resource-id={resourceId}>
        <PreviewHeader tier="rich" previewKind="Spreadsheet" onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
        <XLSXPreview
          structured={{
            sheetName: (structuredData?.sheetName as string) ?? "Sheet1",
            sheetCount: (structuredData?.sheetCount as number) ?? 1,
            columns: (structuredData?.columns as string[]) ?? [],
            rows: (structuredData?.rows as string[][]) ?? [],
            rowCount: (structuredData?.rowCount as number) ?? 0,
            columnCount: (structuredData?.columnCount as number) ?? 0,
          }}
          filename={filename}
        />
      </div>
    );
  }

  // ─── Tier B: Image ──────────────────────────────────────────────────────
  if (
    (previewKind === "image" || /\.(png|jpg|jpeg|gif|webp|svg|bmp|ico)$/i.test(path ?? "")) &&
    assetUri
  ) {
    return (
      <div className="trainer-file-preview" data-resource-id={resourceId}>
        <PreviewHeader tier="converted" previewKind="Image" onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
        <div className="preview-image">
          <img src={assetUri} alt={filename} style={{ maxWidth: "100%", borderRadius: "var(--radius-sm)" }} />
        </div>
      </div>
    );
  }

  // ─── Tier B: Video ───────────────────────────────────────────────────────
  if (
    (previewKind === "video" || /\.(mp4|webm|mov|avi|mkv)$/i.test(path ?? "")) &&
    assetUri
  ) {
    return (
      <div className="trainer-file-preview" data-resource-id={resourceId}>
        <PreviewHeader tier="converted" previewKind="Video" onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
        <div className="preview-video">
          <video src={assetUri} controls style={{ width: "100%", maxHeight: "320px" }} />
        </div>
      </div>
    );
  }

  // ─── Tier B: Notebook ─────────────────────────────────────────────────────
  if (isNotebookPreviewPath(path) && content) {
    return (
      <div className="trainer-file-preview" data-resource-id={resourceId}>
        <PreviewHeader tier="converted" previewKind="Notebook" onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
        <pre className="preview-content-text">{content}</pre>
      </div>
    );
  }

  // ─── Tier B: Archive listing ────────────────────────────────────────────
  if (isArchivePreviewPath(path) && structuredData) {
    const entries = (structuredData.entries as Array<{ name: string; size: number }> | undefined) ?? [];
    return (
      <div className="trainer-file-preview" data-resource-id={resourceId}>
        <PreviewHeader tier="converted" previewKind="Archive" onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
        <div className="preview-archive">
          <div className="archive-entries">
            {entries.slice(0, 50).map((entry, i) => (
              <div key={i} className="archive-entry">
                <span className="entry-name">{entry.name}</span>
                <span className="entry-size">{entry.size > 1024 ? `${(entry.size / 1024).toFixed(1)} KB` : `${entry.size} B`}</span>
              </div>
            ))}
            {entries.length > 50 && <div className="archive-more">+{entries.length - 50} more entries</div>}
          </div>
        </div>
      </div>
    );
  }

  // ─── Tier B: HTML content ────────────────────────────────────────────────
  if (sanitizedHtml) {
    return (
      <div className="trainer-file-preview" data-resource-id={resourceId}>
        <PreviewHeader tier="converted" previewKind={previewKind} onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
        <div className="preview-html" dangerouslySetInnerHTML={{ __html: sanitizedHtml }} />
      </div>
    );
  }

  // ─── Tier B: Text content ───────────────────────────────────────────────
  if (content) {
    return (
      <div className="trainer-file-preview" data-resource-id={resourceId}>
        <PreviewHeader tier="converted" previewKind={previewKind} onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
        {truncated && (
          <div className="preview-truncation-warning">
            <span className="warning-icon">!</span>
            <span className="warning-text">Preview truncated. Open in editor for full content.</span>
          </div>
        )}
        <pre className="preview-content-text">{content}</pre>
      </div>
    );
  }

  // ─── Tier C: Structured metadata ─────────────────────────────────────────
  if (structuredData && Object.keys(structuredData).length > 0) {
    return (
      <div className="trainer-file-preview" data-resource-id={resourceId}>
        <PreviewHeader tier="metadata" previewKind={previewKind} onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
        <div className="preview-structured">
          {Object.entries(structuredData).slice(0, 8).map(([key, value]) => (
            <div key={key} className="structured-entry">
              <span className="entry-key">{key}:</span>
              <span className="entry-value">
                {typeof value === "object" ? JSON.stringify(value).slice(0, 80) : String(value)}
              </span>
            </div>
          ))}
          {Object.keys(structuredData).length > 8 && (
            <div className="structured-more">+{Object.keys(structuredData).length - 8} more fields</div>
          )}
        </div>
      </div>
    );
  }

  // ─── Tier C: Path + metadata only ───────────────────────────────────────
  return (
    <div className="trainer-file-preview" data-resource-id={resourceId}>
      <div className="preview-header">
        <span className="preview-tier">{tierInfo.icon} {tierInfo.label}</span>
        {previewKind && <span className="preview-kind">{previewKind}</span>}
        <NativeOpenButton onNativeOpen={canNativeOpen ? onNativeOpen : undefined} />
      </div>
      <div className="preview-path-only">
        {title && <div className="preview-title">{title}</div>}
        <div className="preview-path">{path}</div>
      </div>
    </div>
  );
};

export default FilePreviewRenderer;
