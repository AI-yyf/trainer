/**
 * Tool Result Renderer
 *
 * Displays tool execution results.
 * Reference: docs/open-source-fit-and-provider-strategy.md §10
 */

import React from "react";
import {
  isAuthoritativeAck,
  sanitizeErrorSurface,
  sanitizeErrorSurfaceText,
} from "../../../../../shared/src/errorSurfaceSanitizer";
import type { ToolResultPart } from "@trainer/shared";

export interface ToolResultRendererProps {
  part: ToolResultPart;
}

export const ToolResultRenderer: React.FC<ToolResultRendererProps> = ({
  part,
}) => {
  const { callId, result, error } = part;
  const hasError = typeof error === "string" && error.trim().length > 0;
  const acknowledged = !hasError && isAuthoritativeAck(result);

  if (hasError) {
    const surface = sanitizeErrorSurface(error);
    return (
      <div
        className="trainer-tool-result tool-result-error"
        data-call-id={callId}
      >
        <div className="tool-result-header error">
          <span className="tool-error-icon">ERR</span>
          <span className="tool-error-label">Failed</span>
        </div>
        <div className="tool-error-message">{surface.message}</div>
        <p className="tool-error-message">{surface.next}</p>
      </div>
    );
  }

  return (
    <div className="trainer-tool-result" data-call-id={callId}>
      <div className={`tool-result-header ${acknowledged ? "success" : "pending"}`}>
        <span className="tool-success-icon">{acknowledged ? "ACK" : "WAIT"}</span>
        <span className="tool-result-type">
          {acknowledged ? "confirmed result" : "waiting for acknowledgement"}
        </span>
      </div>
      <p className="tool-result">
        {acknowledged
          ? sanitizeErrorSurfaceText(typeof result === "string" ? result : "Confirmed")
          : sanitizeErrorSurface(undefined, { acknowledged: false }).message}
      </p>
    </div>
  );
};

export default ToolResultRenderer;
