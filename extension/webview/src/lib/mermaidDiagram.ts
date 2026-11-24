/**
 * One owner for Mermaid diagrams in the workbench.
 *
 * The chart text is model output or imported-document content, so it is
 * untrusted input that ends up as markup on the page. Three things keep it in
 * its box, in this order:
 *
 *  1. Mermaid itself runs in `strict` mode and stays on a patched release.
 *  2. Nothing relies on (1) alone: the rendered SVG is rebuilt from an
 *     allowlist of elements and attributes, so scripts, event handlers,
 *     links, embedded images and resource-loading CSS never reach the DOM.
 *  3. The result is mounted inside a closed shadow root, so a diagram's own
 *     `<style>` can only style the diagram — never the workbench around it.
 *
 * The chart is also size-capped: one message must not be able to pin the
 * main thread with a diagram the size of a book.
 */

export type MermaidThemeName = "dark" | "default";

/** A diagram larger than this is refused and shown as source instead. */
export const MERMAID_MAX_SOURCE_CHARS = 20_000;
export const MERMAID_MAX_SOURCE_LINES = 200;
/** Hard stop while scrubbing, so a pathological SVG cannot grow without bound. */
const MERMAID_MAX_ELEMENTS = 8_000;

const SVG_NS = "http://www.w3.org/2000/svg";
const XLINK_NS = "http://www.w3.org/1999/xlink";
const HTML_NS = "http://www.w3.org/1999/xhtml";

/** Labels are HTML when `htmlLabels` is on; only these survive scrubbing. */
const HTML_LABEL_ELEMENTS = new Set(["div", "span", "p", "br", "b", "i", "em", "strong", "code"]);

/** Names are compared lower-cased so camelCase SVG names match too. */
function lowercaseSet(names: string[]): Set<string> {
  return new Set(names.map((name) => name.toLowerCase()));
}

const SVG_ELEMENTS = lowercaseSet([
  "svg",
  "g",
  "path",
  "rect",
  "circle",
  "ellipse",
  "line",
  "polyline",
  "polygon",
  "text",
  "tspan",
  "textPath",
  "title",
  "desc",
  "defs",
  "marker",
  "pattern",
  "linearGradient",
  "radialGradient",
  "stop",
  "clipPath",
  "mask",
  "style",
  "foreignObject",
  "use",
  "symbol",
]);

/** Not rendered themselves; their children are kept in place. */
const UNWRAP_ELEMENTS = new Set(["a", "switch"]);

/** Attributes any kept SVG element may carry (besides local references and style). */
const SVG_ATTRIBUTES = lowercaseSet([
  "id",
  "class",
  "transform",
  "d",
  "x",
  "y",
  "x1",
  "y1",
  "x2",
  "y2",
  "cx",
  "cy",
  "r",
  "rx",
  "ry",
  "width",
  "height",
  "points",
  "fill",
  "stroke",
  "stroke-width",
  "stroke-dasharray",
  "stroke-linecap",
  "stroke-linejoin",
  "opacity",
  "fill-opacity",
  "stroke-opacity",
  "font-family",
  "font-size",
  "font-weight",
  "font-style",
  "text-anchor",
  "dominant-baseline",
  "alignment-baseline",
  "dx",
  "dy",
  "rotate",
  "textLength",
  "lengthAdjust",
  "viewBox",
  "preserveAspectRatio",
  "offset",
  "stop-color",
  "stop-opacity",
  "gradientUnits",
  "gradientTransform",
  "spreadMethod",
  "patternUnits",
  "patternContentUnits",
  "patternTransform",
  "markerWidth",
  "markerHeight",
  "markerUnits",
  "refX",
  "refY",
  "orient",
  "overflow",
  "vector-effect",
  "paint-order",
  "startOffset",
  "method",
  "spacing",
  "role",
  "aria-label",
  "aria-roledescription",
  "aria-hidden",
  "focusable",
  "version",
]);

/** Attributes that may only point at something inside the same SVG. */
const LOCAL_REFERENCE_ATTRIBUTES = new Set([
  "marker-start",
  "marker-mid",
  "marker-end",
  "clip-path",
  "mask",
  "filter",
  "href",
  "xlink:href",
]);

/**
 * CSS properties a diagram may never set. Everything else is allowed as long
 * as the declaration is safe (see `isSafeDeclaration`), so the bundled theme
 * keeps rendering as designed.
 */
const FORBIDDEN_STYLE_PROPERTIES = new Set(["behavior", "-moz-binding", "-ms-behavior"]);

const LOCAL_ID_RE = /^#[-\w:.]+$/;
const LOCAL_URL_RE = /^url\(\s*['"]?#[-\w:.]+['"]?\s*\)$/i;
const CONTROL_CHARS_RE = /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/;

/**
 * Anything in a declaration that could load a resource, run script, or hide
 * what it really does. It is tested against the *whole* declaration, not the
 * value alone: splitting on the first colon is not how CSS reads a
 * declaration — `background\3a url(...)` is one `background` value whose
 * escaped colon (`\3a`) would otherwise smuggle a resource past a value-only
 * check. Escapes are rejected outright, which closes that door.
 */
const UNSAFE_DECLARATION_RE =
  /[\\@]|url\s*\(|image-set\s*\(|expression\s*\(|javascript:|behavior\s*:|-moz-binding|&/i;
const DECLARATION_RE = /^([-\w]+)\s*:\s*(.+)$/s;
const CSS_RULE_BLOCK_RE = /([^{}]*)\{([^{}]*)\}/g;

/**
 * Remove every at-rule together with its block, however deeply the block
 * nests (`@keyframes` holds a rule per frame). A diagram can keep plain rules
 * only: imports, font faces and animation timelines are not diagram content.
 */
function stripAtRules(cssText: string): string {
  let kept = "";
  let index = 0;
  while (index < cssText.length) {
    const at = cssText.indexOf("@", index);
    if (at < 0) {
      kept += cssText.slice(index);
      break;
    }
    kept += cssText.slice(index, at);
    const opener = cssText.indexOf("{", at);
    const terminator = cssText.indexOf(";", at);
    if (opener < 0 || (terminator >= 0 && terminator < opener)) {
      // A block-less at-rule (`@import url(...);`) ends at its semicolon,
      // or at the end of the sheet if it never closes.
      index = terminator >= 0 && (opener < 0 || terminator < opener) ? terminator + 1 : cssText.length;
      continue;
    }
    let depth = 0;
    let cursor = opener;
    for (; cursor < cssText.length; cursor += 1) {
      if (cssText[cursor] === "{") {
        depth += 1;
      } else if (cssText[cursor] === "}" && (depth -= 1) === 0) {
        cursor += 1;
        break;
      }
    }
    index = cursor;
  }
  return kept;
}

function isSafeDeclaration(declaration: string): false | { property: string; value: string } {
  const text = declaration.trim();
  if (!text || text.length > 300 || UNSAFE_DECLARATION_RE.test(text)) {
    return false;
  }
  const match = DECLARATION_RE.exec(text);
  if (!match) {
    return false;
  }
  const property = match[1].toLowerCase();
  const value = match[2].trim();
  // Script bindings and a viewport escape have no place in a diagram; the
  // diagram's own box (its shadow host) clips everything else it positions.
  if (FORBIDDEN_STYLE_PROPERTIES.has(property) || (property === "position" && /\bfixed\b/.test(value))) {
    return false;
  }
  return { property, value };
}

/** Keep the plain declarations of a `style` attribute; drop everything else. */
export function filterInlineStyle(styleText: string): string {
  const kept: string[] = [];
  for (const declaration of styleText.split(";")) {
    const safe = isSafeDeclaration(declaration);
    if (safe) {
      kept.push(`${safe.property}: ${safe.value}`);
    }
  }
  return kept.join("; ");
}

/**
 * Keep a diagram's stylesheet able to style the diagram and nothing more: no
 * at-rules (imports, font faces, keyframes) and no declaration that pulls in a
 * resource or escapes its own box. The sheet already lives in the diagram's
 * own shadow root, so its selectors can only ever match the diagram.
 */
export function filterDiagramStylesheet(cssText: string): string {
  const withoutAtRules = stripAtRules(cssText);
  const kept: string[] = [];
  for (const match of withoutAtRules.matchAll(CSS_RULE_BLOCK_RE)) {
    const selector = match[1].trim();
    const declarations = match[2]
      .split(";")
      .map((declaration) => isSafeDeclaration(declaration))
      .filter((safe): safe is { property: string; value: string } => Boolean(safe))
      .map((safe) => `${safe.property}: ${safe.value}`);
    if (selector && declarations.length > 0) {
      kept.push(`${selector} { ${declarations.join("; ")}; }`);
    }
  }
  return kept.join("\n");
}

function attributeIsSafe(name: string, value: string): boolean {
  const attribute = name.toLowerCase();
  if (attribute.startsWith("on") || !value || CONTROL_CHARS_RE.test(value)) {
    return false;
  }
  if (LOCAL_REFERENCE_ATTRIBUTES.has(attribute)) {
    const target = value.trim();
    return LOCAL_ID_RE.test(target) || LOCAL_URL_RE.test(target);
  }
  if (attribute === "style") {
    return filterInlineStyle(value).length > 0;
  }
  return SVG_ATTRIBUTES.has(attribute);
}

function copySafeAttributes(
  source: Element,
  target: Element,
  /** Names (lower-cased) the element may carry besides local references and style. */
  allowed: Set<string>,
): void {
  for (const attribute of Array.from(source.attributes)) {
    const lower = attribute.name.toLowerCase();
    const permitted =
      allowed.has(lower) || LOCAL_REFERENCE_ATTRIBUTES.has(lower) || lower === "style";
    if (!permitted || !attributeIsSafe(lower, attribute.value)) {
      continue;
    }
    // SVG attribute names are case-sensitive too (`viewBox`), so the name
    // keeps its case; only the lookup above is normalised.
    const value = lower === "style" ? filterInlineStyle(attribute.value) : attribute.value;
    if (lower === "xlink:href") {
      target.setAttributeNS(XLINK_NS, "xlink:href", value);
    } else {
      target.setAttribute(attribute.name, value);
    }
  }
}

const SVG_TEXT_ELEMENTS = new Set(["text", "tspan", "textpath", "title", "desc"]);
const HTML_LABEL_ATTRIBUTES = new Set(["class", "style"]);

function isSvgTextElement(name: string): boolean {
  return SVG_TEXT_ELEMENTS.has(name);
}

function scrubChildren(
  source: Element,
  target: Element,
  owner: Document,
  context: { elements: number },
  htmlLabels: boolean,
): void {
  for (const node of Array.from(source.childNodes)) {
    if (context.elements >= MERMAID_MAX_ELEMENTS) {
      return;
    }
    if (node.nodeType === 3) {
      // Text is content only where text means text (labels, titles, markup
      // labels); between shapes the SVG renderer ignores it anyway.
      if (htmlLabels || isSvgTextElement(target.localName.toLowerCase())) {
        target.appendChild(owner.createTextNode(node.nodeValue ?? ""));
      }
      continue;
    }
    if (node.nodeType !== 1) {
      // Comments, CDATA and processing instructions carry no diagram.
      continue;
    }
    const element = node as Element;
    // SVG is case-sensitive (`linearGradient` is not `lineargradient`), so the
    // element keeps its own name and only the comparisons are lower-cased.
    const localName = element.localName;
    const name = localName.toLowerCase();
    if (UNWRAP_ELEMENTS.has(name)) {
      scrubChildren(element, target, owner, context, htmlLabels);
      continue;
    }
    if (htmlLabels) {
      if (!HTML_LABEL_ELEMENTS.has(name)) {
        continue;
      }
      const label = owner.createElementNS(HTML_NS, name);
      copySafeAttributes(element, label, HTML_LABEL_ATTRIBUTES);
      context.elements += 1;
      target.appendChild(label);
      scrubChildren(element, label, owner, context, true);
      continue;
    }
    if (name === "style") {
      const stylesheet = filterDiagramStylesheet(element.textContent ?? "");
      if (!stylesheet.trim()) {
        continue;
      }
      const style = owner.createElementNS(SVG_NS, "style");
      style.textContent = stylesheet;
      context.elements += 1;
      target.appendChild(style);
      continue;
    }
    if (!SVG_ELEMENTS.has(name)) {
      // script, image, iframe, SMIL animation and unknown markup are dropped
      // together with everything inside them.
      continue;
    }
    const clean = owner.createElementNS(SVG_NS, localName);
    copySafeAttributes(element, clean, SVG_ATTRIBUTES);
    context.elements += 1;
    target.appendChild(clean);
    scrubChildren(element, clean, owner, context, name === "foreignobject");
  }
}

export interface MermaidDomAdapter {
  /** Parse markup as an SVG document and return its root element, or null. */
  parseSvgRoot(markup: string): Element | null;
  serialize(element: Element): string;
}

/**
 * Mermaid hands back markup for the HTML parser, not for an XML parser: its
 * labels hold HTML void elements (`<br>`, `<img>`) that are not self-closed,
 * and it round-trips its own output through `innerHTML`. Parsing as XML makes
 * every such diagram a parse error — which would quietly refuse any chart
 * with a line break in a label. The HTML parser reads it the way Mermaid
 * wrote it, and a `DOMParser` document is inert: it runs nothing and loads
 * nothing while it is only being read from.
 */
const browserAdapter: MermaidDomAdapter = {
  parseSvgRoot(markup) {
    return new DOMParser().parseFromString(markup, "text/html").querySelector("svg");
  },
  serialize(element) {
    return new XMLSerializer().serializeToString(element);
  },
};

/** Tests substitute a DOM implementation that runs outside a browser. */
export const mermaidDomAdapter: MermaidDomAdapter = { ...browserAdapter };

/**
 * Rebuild a rendered diagram from its allowlist. Returns ``""`` when the
 * markup is not an SVG document or nothing of it is allowed, so the caller
 * shows the source instead.
 */
export function scrubMermaidSvg(svgMarkup: string, owner: Document): string {
  if (!svgMarkup.trim()) {
    return "";
  }
  const source = mermaidDomAdapter.parseSvgRoot(svgMarkup);
  if (!source) {
    return "";
  }
  const clean = owner.createElementNS(SVG_NS, "svg");
  copySafeAttributes(source, clean, SVG_ATTRIBUTES);
  clean.setAttribute("xmlns", SVG_NS);
  clean.setAttribute("xmlns:xlink", XLINK_NS);
  scrubChildren(source, clean, owner, { elements: 0 }, false);
  if (clean.childElementCount === 0) {
    return "";
  }
  return mermaidDomAdapter.serialize(clean);
}

/** Styles that used to live in the page stylesheet; the shadow root needs its own. */
export const MERMAID_SHADOW_CSS = `
:host { display: block; min-width: 0; }
svg { display: block; width: max-content; height: auto; min-width: 100%; }
foreignObject { overflow: visible; }
`;

let mermaidModulePromise: Promise<typeof import("mermaid")> | undefined;
let configuredTheme: MermaidThemeName | undefined;

async function loadMermaid(): Promise<typeof import("mermaid")> {
  mermaidModulePromise ??= import("mermaid");
  return mermaidModulePromise;
}

/**
 * A diagram label may never carry these. Mermaid mounts its working SVG in
 * the page BEFORE the scrubber sees the returned markup, so anything a label's
 * HTML can do happens first. Mermaid sanitises label HTML with DOMPurify,
 * whose defaults still keep `<img>`, `<style>` and `src`: a label such as
 * `A["<img src=https://attacker.example/p.png>"]` started a remote request
 * during rendering. Forbid them at that earlier boundary as well.
 */
const LABEL_FORBIDDEN_TAGS = [
  "img", "script", "iframe", "link", "object", "embed", "video", "audio", "source",
  "style", "form", "input", "button", "textarea", "select", "option", "meta",
  "base", "frame", "frameset", "portal",
];
const LABEL_FORBIDDEN_ATTRIBUTES = [
  "src", "srcset", "xlink:href", "poster", "background", "action", "formaction",
  "ping", "srcdoc",
];

async function configureMermaid(theme: MermaidThemeName): Promise<typeof import("mermaid")["default"]> {
  const mermaid = (await loadMermaid()).default;
  if (configuredTheme === theme) {
    return mermaid;
  }
  // `strict` is the first line of defence, not the only one: the result is
  // scrubbed and shadow-isolated by the caller.
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme,
    dompurifyConfig: {
      FORBID_TAGS: LABEL_FORBIDDEN_TAGS,
      FORBID_ATTR: LABEL_FORBIDDEN_ATTRIBUTES,
    },
    // A parse error must throw to the caller, not leave Mermaid's own
    // "Syntax error" SVG behind in the page.
    suppressErrorRendering: true,
    flowchart: {
      useMaxWidth: true,
      htmlLabels: true,
      nodeSpacing: 18,
      rankSpacing: 20,
    },
  });
  configuredTheme = theme;
  return mermaid;
}

/** True when the diagram is too large to render and should be shown as source. */
export function isMermaidSourceTooLarge(chart: string): boolean {
  if (chart.length > MERMAID_MAX_SOURCE_CHARS) {
    return true;
  }
  let lines = 0;
  for (let index = 0; index < chart.length; index += 1) {
    if (chart.charCodeAt(index) === 10) {
      lines += 1;
      if (lines > MERMAID_MAX_SOURCE_LINES) {
        return true;
      }
    }
  }
  return false;
}

/**
 * Render one chart to scrubbed SVG markup. Throws when the chart is too
 * large, does not parse, or renders to nothing allowed, so the caller can
 * show the source with its error label.
 */
export async function renderMermaidDiagram(
  chart: string,
  options: { elementId: string; theme: MermaidThemeName; ownerDocument?: Document },
): Promise<string> {
  const ownerDocument = options.ownerDocument ?? document;
  if (isMermaidSourceTooLarge(chart)) {
    throw new Error("Mermaid diagram is too large to render.");
  }
  const mermaid = await configureMermaid(options.theme);
  // Mermaid measures label text, so its working SVG has to be connected to a
  // rendered document; a detached container would break the layout. Give it
  // our own invisible container instead of document.body, and take that
  // container out again whatever happens.
  const container = ownerDocument.createElement("div");
  container.setAttribute("aria-hidden", "true");
  container.style.position = "absolute";
  container.style.top = "0";
  container.style.left = "-99999px";
  container.style.visibility = "hidden";
  container.style.pointerEvents = "none";
  ownerDocument.body.appendChild(container);
  try {
    const result = await mermaid.render(`trainer-mermaid-${options.elementId}`, chart, container);
    const scrubbed = scrubMermaidSvg(result.svg, ownerDocument);
    if (!scrubbed) {
      throw new Error("Mermaid diagram did not render as SVG.");
    }
    return scrubbed;
  } finally {
    container.remove();
  }
}

/** The theme that matches the workbench: mermaid names light mode "default". */
export function resolveMermaidTheme(ownerDocument: Document = document): MermaidThemeName {
  return ownerDocument.documentElement.dataset.theme === "light" ? "default" : "dark";
}
