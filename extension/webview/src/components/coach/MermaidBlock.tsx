import { useEffect,useId,useState } from "react";

import {
  renderMermaidDiagram,
  resolveMermaidTheme,
  type MermaidThemeName,
} from "../../lib/mermaidDiagram";
import { MermaidDiagramView } from "../common/MermaidDiagramView";
import { TrainerSpinner } from "../common/TrainerSpinner";
import { ShikiCodeBlock } from "./parts/ShikiCodeBlock";

export interface MermaidBlockProps {
  chart: string;
  summaryLabel: string;
  errorLabel: string;
  loadingLabel: string;
}

/**
 * A Mermaid diagram in a coach reply. The chart is model output, so it is
 * rendered, scrubbed and shadow-isolated by `lib/mermaidDiagram.ts`; a chart
 * that cannot be rendered falls back to its source.
 */
export function MermaidBlock({ chart, summaryLabel, errorLabel, loadingLabel }: MermaidBlockProps) {
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [theme, setTheme] = useState<MermaidThemeName>(() => resolveMermaidTheme());
  const elementId = useId().replace(/:/g, "-");

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setTheme(resolveMermaidTheme());
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "class", "data-vscode-theme-kind"],
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;

    void renderMermaidDiagram(chart, { elementId, theme }).then(
      (markup) => {
        if (!cancelled) {
          setSvg(markup);
          setError("");
        }
      },
      () => {
        if (!cancelled) {
          setSvg("");
          setError(errorLabel);
        }
      },
    );

    return () => {
      cancelled = true;
    };
  }, [chart, elementId, errorLabel, theme]);

  if (error) {
    return (
      <div className="message-mermaid message-mermaid--error">
        <p>{error}</p>
        <ShikiCodeBlock code={chart} languageId="mermaid" />
      </div>
    );
  }

  return (
    <div className="message-mermaid">
      <span className="message-mermaid__label eyebrow">{summaryLabel}</span>
      {svg ? (
        <MermaidDiagramView svg={svg} className="message-mermaid__canvas" />
      ) : (
        <div className="message-mermaid__canvas">
          <TrainerSpinner size="sm" label={loadingLabel} />
        </div>
      )}
    </div>
  );
}
