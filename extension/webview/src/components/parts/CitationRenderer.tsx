/**
 * Citation Renderer
 *
 * Clickable resource reference with trust score and provenance.
 * Reference: docs/open-source-fit-and-provider-strategy.md §8.6
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
  const {
    resourceId,
    chunkId,
    label,
    title,
    source,
    sourceType,
    trustScore,
    freshness,
    referenceOrigin,
  } = part;

  const handleClick = () => {
    onClick?.(resourceId, chunkId);
  };

  // Trust score visualization
  const trustPercent = trustScore != null ? Math.round(trustScore * 100) : null;
  const trustClass =
    trustPercent === null
      ? "trust-unknown"
      : trustPercent >= 70
        ? "trust-high"
        : trustPercent >= 35
          ? "trust-moderate"
          : "trust-low";

  const freshnessLabel =
    freshness === "fresh" ? "fresh" : freshness === "stale" ? "stale" : "unknown";

  return (
    <div
      className="trainer-citation"
      data-resource-id={resourceId}
      data-chunk-id={chunkId}
      onClick={handleClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className="citation-icon">REF</div>
      <div className="citation-content">
        <div className="citation-header">
          <span className="citation-label">{label}</span>
          {title && <span className="citation-title">{title}</span>}
        </div>
        <div className="citation-meta">
          {source && <span className="citation-source">{source}</span>}
          {sourceType && (
            <span className="citation-source-type">{sourceType}</span>
          )}
          {referenceOrigin && (
            <span className="citation-origin">{referenceOrigin}</span>
          )}
        </div>
        <div className="citation-footer">
          {trustPercent !== null && (
            <div className="citation-trust">
              <span className={`trust-indicator ${trustClass}`}>
                {trustPercent >= 70 ? "✓" : trustPercent >= 35 ? "◐" : "✗"}
              </span>
              <span className="trust-label">Trust: {trustPercent}%</span>
              <div className="trust-bar">
                <div
                  className={`trust-fill ${trustClass}`}
                  style={{ width: `${trustPercent}%` }}
                />
              </div>
            </div>
          )}
          {freshness && (
            <div className="citation-freshness">
            <span className={`freshness-icon freshness-icon--${freshnessLabel}`}>
              {freshnessLabel}
            </span>
              <span className="freshness-label">{freshness}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CitationRenderer;
