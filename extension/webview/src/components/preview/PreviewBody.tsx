import type { ReactNode } from "react";

import { sanitizePreviewHtml } from "../../lib/htmlSanitizer";

export interface PreviewBodyProps {
  html?: string;
  structuredPreview?: ReactNode;
  textBody?: ReactNode;
  emptyMessage: string;
  htmlClassName: string;
  structuredClassName: string;
  emptyClassName: string;
}

export function renderPreviewBody({
  html,
  structuredPreview,
  textBody,
  emptyMessage,
  htmlClassName,
  structuredClassName,
  emptyClassName,
}: PreviewBodyProps): ReactNode {
  if (html) {
    const sanitizedHtml = sanitizePreviewHtml(html);
    return (
      <div
        className={htmlClassName}
        dangerouslySetInnerHTML={{ __html: sanitizedHtml }}
      />
    );
  }

  if (structuredPreview) {
    return <div className={structuredClassName}>{structuredPreview}</div>;
  }

  if (textBody) {
    return textBody;
  }

  return <div className={emptyClassName}>{emptyMessage}</div>;
}
