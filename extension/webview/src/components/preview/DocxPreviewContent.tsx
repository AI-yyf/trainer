import { useEffect, useMemo, useRef, useState } from "react";

import mammoth from "mammoth";
import { renderAsync } from "docx-preview";

import { sanitizePreviewHtml } from "../../lib/htmlSanitizer";

export interface DocxPreviewContentProps {
  src: string;
  title: string;
  className?: string;
  compact?: boolean;
}

type DocxPreviewStatus = "idle" | "loading" | "ready" | "fallback" | "error";

function formatStatus(status: DocxPreviewStatus, error: string | null): string {
  if (status === "loading") {
    return "Rendering DOCX preview...";
  }
  if (status === "ready") {
    return "DOCX preview ready";
  }
  if (status === "fallback") {
    return "DOCX preview converted to HTML";
  }
  if (status === "error") {
    return error ? `DOCX preview failed: ${error}` : "DOCX preview failed";
  }
  return "Preparing DOCX preview...";
}

export default function DocxPreviewContent({
  src,
  title,
  className,
  compact = false,
}: DocxPreviewContentProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = useState<DocxPreviewStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [fallbackHtml, setFallbackHtml] = useState<string | null>(null);

  const statusText = useMemo(() => formatStatus(status, error), [status, error]);

  useEffect(() => {
    let cancelled = false;
    const previewContainer = containerRef.current;
    setStatus("loading");
    setError(null);
    setFallbackHtml(null);

    if (!previewContainer) {
      return undefined;
    }
    const docxContainer = previewContainer as HTMLDivElement;

    async function renderDocx(): Promise<void> {
      let arrayBuffer: ArrayBuffer | undefined;
      try {
        const response = await fetch(src);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        arrayBuffer = await response.arrayBuffer();
        if (cancelled) {
          return;
        }

        // Render into a detached staging node so unsanitized HTML never hits
        // the visible preview container, then fail-closed through the sanitizer.
        const staging = document.createElement("div");
        await renderAsync(arrayBuffer, staging, staging, {
          className: "docx-preview__docx",
          inWrapper: true,
          breakPages: true,
          ignoreWidth: compact,
          ignoreHeight: false,
          ignoreFonts: false,
          renderHeaders: true,
          renderFooters: true,
          renderFootnotes: true,
          renderEndnotes: true,
          renderAltChunks: true,
          useBase64URL: true,
        });
        if (cancelled) {
          return;
        }
        const sanitized = sanitizePreviewHtml(staging.innerHTML);
        docxContainer.innerHTML = sanitized;
        if (!sanitized.trim()) {
          setStatus("error");
          setError("Safe DOCX preview unavailable (unsanitized HTML was not shown)");
          return;
        }
        setStatus("ready");
      } catch (renderError) {
        if (cancelled) {
          return;
        }
        const renderErrorMessage =
          renderError instanceof Error ? renderError.message : String(renderError);
        try {
          if (!arrayBuffer) {
            throw new Error(renderErrorMessage);
          }
          const result = await mammoth.convertToHtml({ arrayBuffer });
          if (cancelled) {
            return;
          }
          const sanitizedFallback = sanitizePreviewHtml(result.value ?? "");
          if (!sanitizedFallback.trim()) {
            docxContainer.innerHTML = "";
            setFallbackHtml(null);
            setStatus("error");
            setError("Safe DOCX preview unavailable (empty or unsanitized HTML was not shown)");
            return;
          }
          docxContainer.innerHTML = "";
          setFallbackHtml(sanitizedFallback);
          setStatus("fallback");
          setError(null);
        } catch (fallbackError) {
          if (cancelled) {
            return;
          }
          const fallbackErrorMessage =
            fallbackError instanceof Error ? fallbackError.message : String(fallbackError);
          setStatus("error");
          setError(fallbackErrorMessage || renderErrorMessage);
        }
      }
    }

    void renderDocx();

    return () => {
      cancelled = true;
      docxContainer.innerHTML = "";
    };
  }, [compact, src]);

  return (
    <div className={`docx-preview ${compact ? "docx-preview--compact" : ""} ${className ?? ""}`.trim()}>
      <div className="docx-preview__frame">
        {fallbackHtml ? (
          <div
            className="docx-preview__fallback-html"
            dangerouslySetInnerHTML={{ __html: fallbackHtml }}
          />
        ) : (
          <div className="docx-preview__document" ref={containerRef} />
        )}
      </div>
      <div className="docx-preview__footer">
        <span>{title}</span>
        <span>{statusText}</span>
      </div>
      {status === "error" ? (
        <div className="docx-preview__status docx-preview__status--error">
          Open the source file for the native Word editor.
        </div>
      ) : null}
    </div>
  );
}
