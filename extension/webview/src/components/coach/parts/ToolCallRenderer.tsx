import { useMemo, useState } from "react";

import { sanitizeErrorSurfaceJson } from "../../../../../../shared/src/errorSurfaceSanitizer";
import type { ToolCallPart } from "../../../lib/types";
import { ChevronDownIcon, TerminalIcon } from "../../icons";

export interface ToolCallRendererProps {
  part: ToolCallPart;
  className?: string;
}

type ToolCallStatus = "pending" | "running" | "completed" | "error";

function resolveStatus(status: string): ToolCallStatus {
  const normalized = status.toLowerCase();
  if (normalized === "running" || normalized === "in_progress" || normalized === "executing") {
    return "running";
  }
  if (normalized === "completed" || normalized === "done" || normalized === "success") {
    return "completed";
  }
  if (normalized === "error" || normalized === "failed" || normalized === "failure") {
    return "error";
  }
  return "pending";
}

function formatArgs(args: unknown): string {
  return sanitizeErrorSurfaceJson(args);
}

const STATUS_LABELS: Record<ToolCallStatus, { zh: string; en: string }> = {
  pending: { zh: "等待中", en: "Pending" },
  running: { zh: "运行中", en: "Running" },
  completed: { zh: "已完成", en: "Completed" },
  error: { zh: "失败", en: "Error" },
};

export function ToolCallRenderer({ part, className }: ToolCallRendererProps) {
  const [expanded, setExpanded] = useState(false);
  const resolvedStatus = useMemo(() => resolveStatus(part.status), [part.status]);
  const argsJson = useMemo(() => formatArgs(part.args), [part.args]);
  const hasArgs = argsJson.trim().length > 0;

  const statusLabel = STATUS_LABELS[resolvedStatus]?.en || part.status;

  return (
    <div className={`tool-call-renderer ${className ?? ""}`}>
      <div className="tool-call-renderer__header">
        <span className="tool-call-renderer__icon" aria-hidden="true">
          <TerminalIcon size={14} />
        </span>
        <span className="tool-call-renderer__name">{part.name}</span>
        <span className={`tool-call-renderer__status tool-call-renderer__status--${resolvedStatus}`}>
          {statusLabel}
        </span>
      </div>

      {hasArgs ? (
        <div className="tool-call-renderer__body">
          <button
            type="button"
            className="tool-call-renderer__toggle"
            onClick={() => setExpanded(!expanded)}
            aria-expanded={expanded}
          >
            <span>{expanded ? "Hide parameters" : "Show parameters"}</span>
            <ChevronDownIcon
              size={12}
              style={{ transform: expanded ? "rotate(180deg)" : "none", transition: "transform 0.2s" }}
            />
          </button>
          {expanded && (
            <pre className="tool-call-renderer__args">
              <code>{argsJson}</code>
            </pre>
          )}
        </div>
      ) : null}
    </div>
  );
}