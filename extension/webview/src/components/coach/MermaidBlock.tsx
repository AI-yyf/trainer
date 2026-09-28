import { useEffect, useId, useState } from "react";

import { TrainerSpinner } from "../common/TrainerSpinner";
import { sanitizePreviewHtml } from "../../lib/htmlSanitizer";
import { ShikiCodeBlock } from "./parts/ShikiCodeBlock";

export interface MermaidBlockProps {
  chart: string;
  summaryLabel: string;
  errorLabel: string;
  loadingLabel: string;
}

let mermaidReady = false;
let mermaidTheme: "dark" | "default" | undefined;
let mermaidModulePromise: Promise<typeof import("mermaid")> | undefined;

async function loadMermaid() {
  mermaidModulePromise ??= import("mermaid");
  return mermaidModulePromise;
}

function resolveMermaidTheme(): "dark" | "default" {
  const theme = document.documentElement.dataset.theme;
  return theme === "light" ? "default" : "dark";
}

async function ensureMermaid() {
  const nextTheme = resolveMermaidTheme();
  const mermaid = (await loadMermaid()).default;
  if (mermaidReady && mermaidTheme === nextTheme) {
    return mermaid;
  }

  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: nextTheme,
    flowchart: {
      useMaxWidth: true,
      htmlLabels: true,
      nodeSpacing: 18,
      rankSpacing: 20,
    },
  });
  mermaidReady = true;
  mermaidTheme = nextTheme;
  return mermaid;
}

export function MermaidBlock({ chart, summaryLabel, errorLabel, loadingLabel }: MermaidBlockProps) {
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");
  const elementId = useId().replace(/:/g, "-");

  useEffect(() => {
    let cancelled = false;

    async function renderChart() {
      try {
        const mermaid = await ensureMermaid();
        const result = await mermaid.render(`trainer-mermaid-${elementId}`, chart);
        if (!cancelled) {
          setSvg(sanitizePreviewHtml(result.svg));
          setError("");
        }
      } catch {
        if (!cancelled) {
          setSvg("");
          setError(errorLabel);
        }
      }
    }

    void renderChart();

    return () => {
      cancelled = true;
    };
  }, [chart, elementId, errorLabel]);

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
      <div className="message-mermaid__canvas">
        {svg ? (
          <div dangerouslySetInnerHTML={{ __html: sanitizePreviewHtml(svg) }} />
        ) : (
          <TrainerSpinner size="sm" label={loadingLabel} />
        )}
      </div>
    </div>
  );
}
