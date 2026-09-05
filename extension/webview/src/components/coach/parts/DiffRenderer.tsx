import { useMemo } from "react";

import type { DiffPart } from "../../../lib/types";
import { sanitizePreviewHtml } from "../../../lib/htmlSanitizer";
import Prism from "prismjs";
import "prismjs/components/prism-diff";

export interface DiffRendererProps {
  part: DiffPart;
  className?: string;
}

interface DiffLine {
  prefix: string;
  content: string;
  type: "add" | "remove" | "context";
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function parseDiff(patch: string): DiffLine[] {
  const lines: DiffLine[] = [];
  const rawLines = patch.split("\n");

  for (const line of rawLines) {
    if (line.startsWith("+++") || line.startsWith("@@") || line.startsWith("Index:") || line.startsWith("===")) {
      continue;
    }
    if (line.startsWith("+")) {
      lines.push({ prefix: "+", content: line.slice(1), type: "add" });
    } else if (line.startsWith("-")) {
      lines.push({ prefix: "-", content: line.slice(1), type: "remove" });
    } else if (line.startsWith(" ")) {
      lines.push({ prefix: " ", content: line.slice(1), type: "context" });
    } else if (line.trim()) {
      lines.push({ prefix: " ", content: line, type: "context" });
    }
  }

  return lines;
}

export function DiffRenderer({ part, className }: DiffRendererProps) {
  const diffLines = useMemo(() => parseDiff(part.patch), [part.patch]);

  const highlightedLines = useMemo(() => {
    const language = part.language || "diff";
    return diffLines.map((line) => {
      if (line.type === "context" && line.content.trim()) {
        try {
          if (Prism.languages[language]) {
            return sanitizePreviewHtml(
              Prism.highlight(line.content, Prism.languages[language], language),
            );
          }
        } catch {
          // fallback to escaped content
        }
      }
      return escapeHtml(line.content);
    });
  }, [diffLines, part.language]);

  return (
    <div className={`diff-renderer ${className ?? ""}`}>
      <div className="diff-renderer__header">
        <span className="diff-renderer__lang">{part.language || "diff"}</span>
      </div>
      <div className="diff-renderer__content">
        {diffLines.map((line, index) => (
          <div
            key={index}
            className={`diff-renderer__line diff-renderer__line--${line.type}`}
          >
            <span className="diff-renderer__prefix">{line.prefix}</span>
            <span
              className="diff-renderer__code"
              dangerouslySetInnerHTML={{
                __html: highlightedLines[index] || escapeHtml(line.content),
              }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
