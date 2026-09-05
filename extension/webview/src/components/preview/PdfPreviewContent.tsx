import { useEffect, useMemo, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import type { PDFDocumentProxy } from "pdfjs-dist";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

export interface PdfPreviewContentProps {
  src: string;
  title: string;
  className?: string;
  compact?: boolean;
}

function formatPageSummary(numPages: number | undefined): string {
  if (!numPages || !Number.isFinite(numPages)) {
    return "Loading PDF preview";
  }
  return numPages === 1 ? "1 page" : `${numPages} pages`;
}

export default function PdfPreviewContent({
  src,
  title,
  className,
  compact = false,
}: PdfPreviewContentProps) {
  const [numPages, setNumPages] = useState<number>();
  const [pageNumber, setPageNumber] = useState(1);

  const pageHeight = compact ? 320 : 420;
  const pageLabel = useMemo(() => formatPageSummary(numPages), [numPages]);

  useEffect(() => {
    setPageNumber(1);
    setNumPages(undefined);
  }, [src]);

  function onDocumentLoadSuccess(document: PDFDocumentProxy): void {
    setNumPages(document.numPages);
  }

  return (
    <div className={`pdf-preview ${className ?? ""}`}>
      <div className="pdf-preview__frame">
        <Document
          file={src}
          onLoadSuccess={onDocumentLoadSuccess}
          loading={<div className="pdf-preview__status">Loading PDF preview...</div>}
          error={<div className="pdf-preview__status">PDF preview could not be loaded.</div>}
          noData={<div className="pdf-preview__status">No PDF source is attached.</div>}
        >
          <Page
            pageNumber={pageNumber}
            height={pageHeight}
            renderAnnotationLayer={false}
            renderTextLayer={false}
            loading={<div className="pdf-preview__status">Rendering page...</div>}
          />
        </Document>
      </div>
      <div className="pdf-preview__footer">
        <span>{title}</span>
        <span>{pageLabel}</span>
      </div>
      {numPages && numPages > 1 ? (
        <div className="pdf-preview__pager" aria-label="PDF page controls">
          <button
            type="button"
            className="pdf-preview__pager-button"
            onClick={() => setPageNumber((current) => Math.max(1, current - 1))}
            disabled={pageNumber <= 1}
          >
            Prev
          </button>
          <span className="pdf-preview__pager-label">
            {pageNumber} / {numPages}
          </span>
          <button
            type="button"
            className="pdf-preview__pager-button"
            onClick={() => setPageNumber((current) => Math.min(numPages, current + 1))}
            disabled={pageNumber >= numPages}
          >
            Next
          </button>
        </div>
      ) : null}
    </div>
  );
}
