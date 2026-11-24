/**
 * Mermaid Renderer
 *
 * A diagram carried as a typed message part. Rendering (strict mode,
 * allowlist scrubbing, shadow isolation) has one owner in
 * `lib/mermaidDiagram.ts`; this component only lays it out.
 */

import React, { useEffect, useId, useState } from "react";

import { MermaidDiagramView } from "../common/MermaidDiagramView";
import { renderMermaidDiagram, resolveMermaidTheme } from "../../lib/mermaidDiagram";

export interface MermaidRendererLabels {
  failed: string;
  detail: string;
  viewSource: string;
}

export interface MermaidRendererProps {
  source: string;
  labels?: MermaidRendererLabels;
}

const DEFAULT_LABELS: MermaidRendererLabels = {
  failed: "Diagram rendering failed",
  detail: "Rendering detail",
  viewSource: "View source",
};

type RenderState = { svg: string; error: string };

export const MermaidRenderer: React.FC<MermaidRendererProps> = ({
  source,
  labels,
}) => {
  const copy = labels ?? DEFAULT_LABELS;
  const [state, setState] = useState<RenderState>({ svg: "", error: "" });
  const elementId = useId().replace(/:/g, "-");

  useEffect(() => {
    let cancelled = false;

    void renderMermaidDiagram(source, { elementId, theme: resolveMermaidTheme() }).then(
      (svg) => {
        if (!cancelled) {
          setState({ svg, error: "" });
        }
      },
      (error: unknown) => {
        if (!cancelled) {
          setState({
            svg: "",
            // Shown as text by React; it never becomes markup.
            error: error instanceof Error ? error.message : String(error),
          });
        }
      },
    );

    return () => {
      cancelled = true;
    };
  }, [source, elementId]);

  return (
    <div className="trainer-mermaid">
      {state.error ? (
        <div className="mermaid-error" role="alert">
          <div className="mermaid-error-header">
            <span className="error-icon" aria-hidden="true">!</span>
            <span className="error-label">{copy.failed}</span>
          </div>
          <pre className="mermaid-source">{source}</pre>
          <div className="mermaid-error-detail">{copy.detail}: {state.error}</div>
        </div>
      ) : (
        <MermaidDiagramView svg={state.svg} className="mermaid-diagram" />
      )}
      <details className="mermaid-source-details">
        <summary>{copy.viewSource}</summary>
        <pre className="mermaid-source">{source}</pre>
      </details>
    </div>
  );
};

export default MermaidRenderer;
