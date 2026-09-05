import { lazy, Suspense } from "react";

import type { AudioPreviewContentProps } from "./AudioPreviewContent";

const LazyAudioPreviewContent = lazy(() => import("./AudioPreviewContent"));

export interface AudioPreviewProps extends AudioPreviewContentProps {
  fallbackLabel?: string;
}

export function AudioPreview({
  fallbackLabel = "Loading audio preview...",
  ...props
}: AudioPreviewProps) {
  return (
    <Suspense fallback={<div className="audio-preview__status">{fallbackLabel}</div>}>
      <LazyAudioPreviewContent {...props} />
    </Suspense>
  );
}
