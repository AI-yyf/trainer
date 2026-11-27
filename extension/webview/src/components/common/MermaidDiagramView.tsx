import { useEffect,useRef } from "react";

import { MERMAID_SHADOW_CSS } from "../../lib/mermaidDiagram";

export interface MermaidDiagramViewProps {
  /** Already-scrubbed SVG markup (see `renderMermaidDiagram`). */
  svg: string;
  className?: string;
}

/**
 * Mounts a rendered Mermaid diagram inside a closed shadow root.
 *
 * The diagram carries its own `<style>` (the theme Mermaid generated for it).
 * In the light DOM those rules would apply to the whole workbench — and a
 * hostile diagram could style it. In a shadow tree of its own they can only
 * ever reach the diagram, and the closed mode keeps page scripts from
 * reaching in. This is the single place diagram markup enters the DOM.
 */
export function MermaidDiagramView({ svg, className }: MermaidDiagramViewProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<ShadowRoot | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) {
      return;
    }
    const root = rootRef.current ?? host.attachShadow({ mode: "closed" });
    rootRef.current = root;

    const sheet = document.createElement("style");
    sheet.textContent = MERMAID_SHADOW_CSS;
    const holder = document.createElement("div");
    holder.innerHTML = svg;
    root.replaceChildren(sheet, holder);
    host.dataset.rendered = "true";
  }, [svg]);

  return <div ref={hostRef} className={className ?? "mermaid-diagram"} data-mermaid-host="true" />;
}
