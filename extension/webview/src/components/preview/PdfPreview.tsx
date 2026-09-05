import { lazy, Suspense } from "react";

import { isPdfPreviewPath as isPdfPreviewPathShared } from "../../../../../shared/src/previewAssets";
import type { PdfPreviewContentProps } from "./PdfPreviewContent";

const LazyPdfPreviewContent = lazy(() => import("./PdfPreviewContent"));

export interface PdfPreviewProps extends PdfPreviewContentProps {
  fallbackLabel?: string;
}

export function isPdfPreviewPath(value: string | undefined): boolean {
  return isPdfPreviewPathShared(value);
}

export function PdfPreview({
  fallbackLabel = "Loading PDF preview...",
  ...props
}: PdfPreviewProps) {
  return (
    <Suspense fallback={<div className="pdf-preview__status">{fallbackLabel}</div>}>
      <LazyPdfPreviewContent {...props} />
    </Suspense>
  );
}
