const SAFE_TAGS = new Set([
  "a",
  "article",
  "blockquote",
  "br",
  "code",
  "div",
  "details",
  "dl",
  "dt",
  "dd",
  "em",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "img",
  "li",
  "ol",
  "p",
  "pre",
  "section",
  "small",
  "span",
  "strong",
  "sub",
  "summary",
  "sup",
  "table",
  "tbody",
  "td",
  "th",
  "thead",
  "tr",
  "ul",
  // Mermaid / diagram SVG (no foreignObject — dropped as host below)
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
  "defs",
  "marker",
  "use",
  "clippath",
  "title",
  "desc",
  "lineargradient",
  "radialgradient",
  "stop",
  "pattern",
  "mask",
  "symbol",
]);

const DROP_HOST_TAGS = new Set([
  "script",
  "style",
  "iframe",
  "object",
  "embed",
  "link",
  "meta",
  "base",
  "foreignobject",
]);

const GLOBAL_ATTRS = new Set([
  "aria-hidden",
  "aria-label",
  "class",
  "dir",
  "id",
  "lang",
  "role",
  "title",
]);

const ATTRS_BY_TAG: Record<string, Set<string>> = {
  a: new Set(["href", "rel", "target", "title"]),
  img: new Set(["alt", "height", "loading", "src", "width"]),
  audio: new Set(["controls", "preload", "src"]),
  source: new Set(["src", "type"]),
  video: new Set(["controls", "preload", "src"]),
  td: new Set(["colspan", "rowspan"]),
  th: new Set(["colspan", "rowspan", "scope"]),
};

const SVG_TAGS = new Set([
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
  "defs",
  "marker",
  "use",
  "clippath",
  "title",
  "desc",
  "lineargradient",
  "radialgradient",
  "stop",
  "pattern",
  "mask",
  "symbol",
]);

const URL_ATTRS = new Set(["href", "src", "xlink:href"]);

const SAFE_URL_PROTOCOLS = new Set(["http:", "https:", "mailto:", "tel:", ""]);

function isSafeUrl(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) {
    return false;
  }
  if (trimmed.startsWith("#")) {
    return true;
  }
  try {
    const url = new URL(trimmed, "https://trainer.local");
    return SAFE_URL_PROTOCOLS.has(url.protocol);
  } catch {
    return !/^\s*(javascript|data|vbscript):/i.test(trimmed);
  }
}

function sanitizeElement(node: Element): void {
  const tagName = node.tagName.toLowerCase();
  if (!SAFE_TAGS.has(tagName)) {
    // Drop executable/embedding hosts entirely; unwrap other unknown tags only
    // after children are sanitized so nested payloads cannot escape the walk.
    if (DROP_HOST_TAGS.has(tagName)) {
      node.remove();
      return;
    }
    for (const child of Array.from(node.children)) {
      sanitizeElement(child);
    }
    const fragment = node.ownerDocument.createDocumentFragment();
    while (node.firstChild) {
      fragment.appendChild(node.firstChild);
    }
    node.replaceWith(fragment);
    return;
  }

  for (const attribute of Array.from(node.attributes)) {
    const name = attribute.name.toLowerCase();
    const value = attribute.value;
    const isEventHandler = name.startsWith("on");
    const isStyle = name === "style" || name === "srcdoc";
    const isUrlAttr = URL_ATTRS.has(name);
    const allowed =
      GLOBAL_ATTRS.has(name) ||
      ATTRS_BY_TAG[tagName]?.has(name) ||
      name.startsWith("data-") ||
      (SVG_TAGS.has(tagName) && !isEventHandler && !isStyle && !isUrlAttr);
    const isSafeHref = isUrlAttr && isSafeUrl(value);
    if (isEventHandler || isStyle || (!allowed && !isSafeHref) || (isUrlAttr && !isSafeHref)) {
      node.removeAttribute(attribute.name);
      continue;
    }
  }

  if (tagName === "a") {
    const target = node.getAttribute("target");
    if (target === "_blank") {
      node.setAttribute("rel", "noopener noreferrer");
    }
  }

  for (const child of Array.from(node.children)) {
    sanitizeElement(child);
  }
}

export function sanitizePreviewHtml(input: string | null | undefined): string {
  if (!input) {
    return "";
  }
  // Node / non-DOM hosts: never pass model HTML through.
  if (typeof document === "undefined") {
    return "";
  }
  const template = document.createElement("template");
  template.innerHTML = input;
  for (const child of Array.from(template.content.children)) {
    sanitizeElement(child);
  }
  return template.innerHTML;
}
