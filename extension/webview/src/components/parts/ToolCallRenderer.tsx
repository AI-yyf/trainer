/**
 * Tool Call Renderer
 *
 * Displays tool call requests and their status.
 * Reference: docs/open-source-fit-and-provider-strategy.md §10
 */

import React from "react";
import { sanitizeErrorSurfaceJson } from "../../../../../shared/src/errorSurfaceSanitizer";
import type { ToolCallPart } from "@trainer/shared";

export interface ToolCallRendererProps {
  part: ToolCallPart;
  onClick?: () => void;
}

export const ToolCallRenderer: React.FC<ToolCallRendererProps> = ({
  part,
  onClick,
}) => {
  const { id, name, status, args } = part;

  // Status icon mapping
  const statusIcons: Record<string, string> = {
    pending: "P",
    called: "RUN",
    completed: "OK",
    failed: "ERR",
    cancelled: "C",
  };
  const statusIcon = statusIcons[status] ?? "RUN";

  // Format arguments for display
  const argsJson = sanitizeErrorSurfaceJson(args);
  const isArgsComplex = Object.keys(args ?? {}).length > 3;

  return (
    <div
      className="trainer-tool-call"
      data-call-id={id}
      data-tool-name={name}
      data-status={status}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className="tool-call-header">
        <span className="tool-status-icon">{statusIcon}</span>
        <span className="tool-name">{name}</span>
        <span className={`tool-status status-${status}`}>{status}</span>
      </div>
      <div className="tool-args-container">
        <div className="tool-args-header">
          <span className="args-label">Arguments</span>
        </div>
        <pre className="tool-args">
          <code className="args-json">{argsJson}</code>
        </pre>
      </div>
    </div>
  );
};

export default ToolCallRenderer;
