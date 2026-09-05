import { lazy, Suspense } from "react";

import { isDocxPreviewPath as isDocxPreviewPathShared } from "../../../../../shared/src/previewAssets";
import type { DocxPreviewContentProps } from "./DocxPreviewContent";

const LazyDocxPreviewContent = lazy(() => import("./DocxPreviewContent"));

export interface DocxPreviewProps extends DocxPreviewContentProps {
  fallbackLabel?: string;
}

export function isDocxPreviewPath(value: string | undefined): boolean {
  return isDocxPreviewPathShared(value);
}

export function DocxPreview({
  fallbackLabel = "Loading DOCX preview...",
  ...props
}: DocxPreviewProps) {
  return (
    <Suspense fallback={<div className="docx-preview__status">{fallbackLabel}</div>}>
      <LazyDocxPreviewContent {...props} />
    </Suspense>
  );
}
