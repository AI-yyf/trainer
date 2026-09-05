/**
 * Reasoning Renderer
 *
 * Displays model reasoning summary with hint ladder and verification steps.
 * Reference: docs/open-source-fit-and-provider-strategy.md §10
 */

import React, { useState } from "react";
import { sanitizeErrorSurfaceText } from "../../../../../shared/src/errorSurfaceSanitizer";
import type { ReasoningPart } from "@trainer/shared";

export interface ReasoningRendererProps {
  part: ReasoningPart;
}

export const ReasoningRenderer: React.FC<ReasoningRendererProps> = ({
  part,
}) => {
  const { summary, redacted, detail, sourceChain, hintLadder, verificationSteps } = part;
  const [expanded, setExpanded] = useState(false);

  if (redacted) {
    return (
      <div className="trainer-reasoning reasoning-redacted">
        <div className="reasoning-header">
          <span className="reasoning-icon">R</span>
          <span className="reasoning-label">Reasoning</span>
          <span className="reasoning-redacted-badge">[Hidden]</span>
        </div>
      </div>
    );
  }

  return (
    <div className="trainer-reasoning">
      <div className="reasoning-header" onClick={() => setExpanded(!expanded)}>
        <span className="reasoning-icon">R</span>
        <span className="reasoning-label">Reasoning</span>
        <button className="reasoning-expand-btn" aria-expanded={expanded}>
          {expanded ? "▼" : "▶"}
        </button>
      </div>

      <div className="reasoning-summary">
        <span className="reasoning-text">{sanitizeErrorSurfaceText(summary)}</span>
      </div>

      {expanded && (
        <div className="reasoning-details">
          {detail && (
            <div className="reasoning-detail">
              <span className="detail-label">Detail:</span>
              <span className="detail-text">{sanitizeErrorSurfaceText(detail)}</span>
            </div>
          )}

          {sourceChain && sourceChain.length > 0 && (
            <div className="reasoning-source-chain">
              <span className="chain-label">Source chain:</span>
              <ol className="chain-list">
                {sourceChain.map((source, index) => (
                  <li key={index} className="chain-item">
                    {source}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {hintLadder && hintLadder.length > 0 && (
            <div className="reasoning-hints">
              <span className="hints-label">Hint ladder:</span>
              <ol className="hint-ladder">
                {hintLadder.map((hint, index) => (
                  <li key={index} className="hint-item">
                    <span className="hint-level">Level {index + 1}:</span>
                    <span className="hint-text">{hint}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {verificationSteps && verificationSteps.length > 0 && (
            <div className="reasoning-verification">
              <span className="verification-label">Verification steps:</span>
              <ol className="step-list">
                {verificationSteps.map((step, index) => (
                  <li key={index} className="step-item">
                    {step}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ReasoningRenderer;
