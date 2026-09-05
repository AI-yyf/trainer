/**
 * Diff Renderer
 *
 * Dual-mode diff display: unified and side-by-side.
 * Supports syntax highlighting for additions/removals.
 * Reference: docs/open-source-fit-and-provider-strategy.md §10
 */

import React, { useMemo, useState } from "react";

export interface DiffRendererProps {
  patch: string;
  language?: string;
  /** Whether to show line numbers */
  showLineNumbers?: boolean;
  /** Default view mode: "unified" or "side-by-side" */
  defaultMode?: "unified" | "side-by-side";
}

type ViewMode = "unified" | "side-by-side";

interface DiffLine {
  type: "context" | "addition" | "removal" | "hunk-header";
  content: string;
  oldLineNumber?: number;
  newLineNumber?: number;
}

interface SideBySideLine {
  left: DiffLine | null;
  right: DiffLine | null;
}

export const DiffRenderer: React.FC<DiffRendererProps> = ({
  patch,
  showLineNumbers = true,
  defaultMode = "unified",
}) => {
  const [viewMode, setViewMode] = useState<ViewMode>(defaultMode);

  const { lines, stats } = useMemo(() => {
    const parsedLines: DiffLine[] = [];
    let oldLineNum = 0;
    let newLineNum = 0;
    let additions = 0;
    let deletions = 0;

    const rawLines = patch.split("\n");

    for (const rawLine of rawLines) {
      if (rawLine.startsWith("@@")) {
        // Parse hunk header: @@ -start,count +start,count @@
        const match = rawLine.match(/@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
        if (match) {
          oldLineNum = parseInt(match[1], 10);
          newLineNum = parseInt(match[3], 10);
        }
        parsedLines.push({
          type: "hunk-header",
          content: rawLine,
        });
      } else if (rawLine.startsWith("+")) {
        parsedLines.push({
          type: "addition",
          content: rawLine.slice(1),
          newLineNumber: newLineNum++,
        });
        additions++;
      } else if (rawLine.startsWith("-")) {
        parsedLines.push({
          type: "removal",
          content: rawLine.slice(1),
          oldLineNumber: oldLineNum++,
        });
        deletions++;
      } else if (rawLine.startsWith(" ") || rawLine === "") {
        parsedLines.push({
          type: "context",
          content: rawLine.slice(1) || "",
          oldLineNumber: oldLineNum++,
          newLineNumber: newLineNum++,
        });
      }
    }

    return {
      lines: parsedLines,
      stats: { additions, deletions, total: additions + deletions },
    };
  }, [patch]);

  // Build side-by-side view by pairing lines
  const sideBySideLines = useMemo((): SideBySideLine[] => {
    const paired: SideBySideLine[] = [];
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];

      if (line.type === "hunk-header") {
        paired.push({ left: line, right: line });
        i++;
        continue;
      }

      if (line.type === "removal") {
        // Look ahead for a matching addition
        let j = i + 1;
        while (j < lines.length && lines[j].type === "removal") {
          j++;
        }
        const removals = lines.slice(i, j);

        // Find matching additions
        let k = j;
        while (k < lines.length && lines[k].type === "addition") {
          k++;
        }
        const additions = lines.slice(j, k);

        const maxLen = Math.max(removals.length, additions.length);
        for (let n = 0; n < maxLen; n++) {
          paired.push({
            left: removals[n] || null,
            right: additions[n] || null,
          });
        }

        i = k;
      } else if (line.type === "addition") {
        // Orphaned addition (no preceding removal)
        paired.push({ left: null, right: line });
        i++;
      } else {
        // Context line
        paired.push({ left: line, right: line });
        i++;
      }
    }

    return paired;
  }, [lines]);

  return (
    <div className="trainer-diff-renderer">
      <div className="diff-header">
        <span className="diff-stats">
          <span className="diff-additions">+{stats.additions}</span>
          <span className="diff-deletions">-{stats.deletions}</span>
        </span>
        <div className="diff-mode-toggle">
          <button
            className={`diff-mode-btn ${viewMode === "unified" ? "active" : ""}`}
            onClick={() => setViewMode("unified")}
            title="Unified view"
          >
            Unified
          </button>
          <button
            className={`diff-mode-btn ${viewMode === "side-by-side" ? "active" : ""}`}
            onClick={() => setViewMode("side-by-side")}
            title="Side-by-side view"
          >
            Split
          </button>
        </div>
      </div>
      <div className="diff-content">
        {viewMode === "unified" ? (
          <UnifiedDiffView lines={lines} showLineNumbers={showLineNumbers} />
        ) : (
          <SideBySideDiffView lines={sideBySideLines} showLineNumbers={showLineNumbers} />
        )}
      </div>
    </div>
  );
};

interface UnifiedDiffViewProps {
  lines: DiffLine[];
  showLineNumbers: boolean;
}

const UnifiedDiffView: React.FC<UnifiedDiffViewProps> = ({ lines, showLineNumbers }) => (
  <pre className="diff-block">
    {lines.map((line, index) => (
      <DiffLineComponent key={index} line={line} showLineNumbers={showLineNumbers} />
    ))}
  </pre>
);

interface SideBySideDiffViewProps {
  lines: SideBySideLine[];
  showLineNumbers: boolean;
}

const SideBySideDiffView: React.FC<SideBySideDiffViewProps> = ({ lines, showLineNumbers }) => (
  <div className="diff-side-by-side">
    <div className="diff-side-by-side__left">
      <div className="diff-sbs-header">Original</div>
      {lines.map((line, index) => (
        <SideBySideLineComponent
          key={index}
          line={line.left}
          showLineNumbers={showLineNumbers}
          side="left"
        />
      ))}
    </div>
    <div className="diff-side-by-side__right">
      <div className="diff-sbs-header">Modified</div>
      {lines.map((line, index) => (
        <SideBySideLineComponent
          key={index}
          line={line.right}
          showLineNumbers={showLineNumbers}
          side="right"
        />
      ))}
    </div>
  </div>
);

interface DiffLineComponentProps {
  line: DiffLine;
  showLineNumbers: boolean;
}

const DiffLineComponent: React.FC<DiffLineComponentProps> = ({ line, showLineNumbers }) => {
  const lineClass = `diff-line diff-${line.type}`;
  const lineContent = line.content || " ";

  // Escape HTML
  const escapedContent = lineContent
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  if (line.type === "hunk-header") {
    return (
      <div className={lineClass}>
        <span className="diff-hunk-text">{escapeHtml(line.content)}</span>
      </div>
    );
  }

  return (
    <div className={lineClass}>
      {showLineNumbers && (
        <span className="diff-line-numbers">
          <span className="diff-old-line">{line.oldLineNumber ?? ""}</span>
          <span className="diff-new-line">{line.newLineNumber ?? ""}</span>
        </span>
      )}
      <span className="diff-line-content">{escapedContent}</span>
    </div>
  );
};

interface SideBySideLineComponentProps {
  line: DiffLine | null;
  showLineNumbers: boolean;
  side: "left" | "right";
}

const SideBySideLineComponent: React.FC<SideBySideLineComponentProps> = ({
  line,
  showLineNumbers,
  side,
}) => {
  if (!line) {
    return <div className="diff-sbs-line diff-sbs-line--empty" />;
  }

  const lineClass = `diff-sbs-line diff-sbs-line--${line.type}`;
  const lineContent = line.content || " ";

  const escapedContent = lineContent
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  if (line.type === "hunk-header") {
    return (
      <div className={lineClass}>
        <span className="diff-hunk-text">{escapeHtml(line.content)}</span>
      </div>
    );
  }

  const lineNum = side === "left" ? line.oldLineNumber : line.newLineNumber;

  return (
    <div className={lineClass}>
      {showLineNumbers && (
        <span className="diff-sbs-line-number">{lineNum ?? ""}</span>
      )}
      <span className="diff-sbs-prefix">
        {line.type === "addition" ? "+" : line.type === "removal" ? "-" : " "}
      </span>
      <span className="diff-sbs-content">{escapedContent}</span>
    </div>
  );
};

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export default DiffRenderer;