/**
 * Mermaid Renderer
 *
 * Diagram rendering using Mermaid.js.
 * Reference: docs/open-source-fit-and-provider-strategy.md §10
 */

import React, { useEffect, useRef, useState } from "react";

import { sanitizePreviewHtml } from "../../lib/htmlSanitizer";

export interface MermaidRendererProps {
  source: string;
}

export const MermaidRenderer: React.FC<MermaidRendererProps> = ({
  source,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const diagramId = useRef(`mermaid-${Math.random().toString(36).substr(2, 9)}`);

  useEffect(() => {
    if (!containerRef.current) return;

    const renderDiagram = async () => {
      try {
        // Dynamic import Mermaid to reduce initial bundle size
        const mermaid = await import("mermaid");

        // Initialize Mermaid with default config
        mermaid.default.initialize({
          startOnLoad: false,
          theme: "default",
          securityLevel: "strict",
        });

        // Clear previous content
        if (containerRef.current) {
          containerRef.current.innerHTML = "";
        }

        // Render the diagram
        const { svg } = await mermaid.default.render(diagramId.current, source);
        if (containerRef.current) {
          containerRef.current.innerHTML = sanitizePreviewHtml(svg);
        }
        setError(null);
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : "Failed to render diagram";
        setError(errorMessage);
        console.warn("Mermaid rendering error:", err);
      }
    };

    renderDiagram();
  }, [source]);

  if (error) {
    return (
      <div className="trainer-mermaid mermaid-error">
        <div className="mermaid-error-header">
          <span className="error-icon">!</span>
          <span className="error-label">Diagram rendering failed</span>
        </div>
        <pre className="mermaid-source">{source}</pre>
        <div className="mermaid-error-detail">{error}</div>
      </div>
    );
  }

  return (
    <div className="trainer-mermaid">
      <div ref={containerRef} className="mermaid-diagram" />
      <details className="mermaid-source-details">
        <summary>View source</summary>
        <pre className="mermaid-source">{source}</pre>
      </details>
    </div>
  );
};

export default MermaidRenderer;
