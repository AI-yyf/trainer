/**
 * Citation Renderer (Trainer 2.0 minimalist expandable pill).
 */

import React from "react";
import type { CitationPart } from "@trainer/shared";

export interface CitationRendererProps {
  part: CitationPart;
  onClick?: (resourceId: string, chunkId?: string) => void;
}

export const CitationRenderer: React.FC<CitationRendererProps> = ({
  part,
  onClick,
}) => {
  const { resourceId, chunkId, label, title, source, summary, snippet } = part;
  const pillTitle = title || label || resourceId;
  const hasDetails = Boolean(source || summary || snippet);

  const handleOpen = (event: React.MouseEvent) => {
    if (onClick) {
      event.preventDefault();
      onClick(resourceId, chunkId);
    }
  };

  if (!hasDetails) {
    return (
      <span
        className="trainer-citation message-part--citation-pill"
        data-citation-pill="true"
        data-resource-id={resourceId}
        data-chunk-id={chunkId}
        onClick={onClick ? handleOpen : undefined}
        role={onClick ? "button" : undefined}
        tabIndex={onClick ? 0 : undefined}
      >
        <span className="citation-title">{pillTitle}</span>
        {chunkId ? <span className="citation-meta">{` · ${chunkId}`}</span> : null}
      </span>
    );
  }

  return (
    <details
      className="trainer-citation message-part--citation-pill"
      data-citation-pill="true"
      data-resource-id={resourceId}
      data-chunk-id={chunkId}
    >
      <summary className="message-part__citation-summary">
        <span className="citation-title">{pillTitle}</span>
        {chunkId ? <span className="citation-meta">{` · ${chunkId}`}</span> : null}
      </summary>
      <div className="message-part__citation-body">
        {source ? <p className="citation-source">{source}</p> : null}
        {summary ? <p>{summary}</p> : null}
        {snippet ? <p>{snippet}</p> : null}
        {onClick ? (
          <button
            type="button"
            className="message-part__meta"
            onClick={handleOpen}
          >
            ↗
          </button>
        ) : null}
      </div>
    </details>
  );
};

export default CitationRenderer;
