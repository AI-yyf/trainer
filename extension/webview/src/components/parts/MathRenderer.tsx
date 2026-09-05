/**
 * Math Renderer
 *
 * LaTeX math display using KaTeX.
 * Reference: docs/open-source-fit-and-provider-strategy.md §10
 */

import React, { useEffect, useRef } from "react";

import { sanitizePreviewHtml } from "../../lib/htmlSanitizer";

export interface MathRendererProps {
  tex: string;
  display?: boolean;
}

export const MathRenderer: React.FC<MathRendererProps> = ({
  tex,
  display = false,
}) => {
  const containerRef = useRef<HTMLSpanElement>(null);

  // Render using KaTeX if available
  useEffect(() => {
    if (!containerRef.current) return;

    // Check if KaTeX is available
    const renderKaTeX = async () => {
      try {
        // Dynamic import KaTeX to reduce initial bundle size
        const katex = await import("katex");
        const html = katex.default.renderToString(tex, {
          displayMode: display,
          throwOnError: false,
          trust: false,
          errorColor: "var(--danger)",
        });
        if (containerRef.current) {
          containerRef.current.innerHTML = sanitizePreviewHtml(html);
        }
      } catch (error) {
        // Fallback: show raw LaTeX
        console.warn("KaTeX not available, showing raw LaTeX:", error);
      }
    };

    renderKaTeX();
  }, [tex, display]);

  const className = display ? "math-display" : "math-inline";

  // Fallback display while KaTeX loads or if unavailable
  return (
    <span
      ref={containerRef}
      className={`trainer-math ${className}`}
      data-tex={tex}
    >
      {tex}
    </span>
  );
};

export default MathRenderer;
