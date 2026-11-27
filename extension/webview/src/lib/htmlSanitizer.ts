import { REMOTE_IMAGE_ATTRIBUTE,classifyImageUrl,createRemoteImagePlaceholder } from "./remoteImages";

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

// SVG presentation attributes can carry a CSS paint-server reference:
// fill="url(https://attacker.example/p.svg#g)" is fetched by the browser as
// soon as the element renders, without a click. Only same-document fragment
// references are allowed on SVG elements.
const LOCAL_SVG_FRAGMENT_PATTERN = /^#[A-Za-z_][\w:.-]*$/;

// Attributes whose values are parsed as CSS and can fetch a paint server or
// geometry transform. Other SVG attributes (ids, labels, path data) may
// legitimately contain parentheses, so they are only checked when a plain
// url() appears.
const SVG_CSS_REFERENCE_ATTRS = new Set([
  "clip-path",
  "color-profile",
  "cursor",
  "fill",
  "filter",
  "gradienttransform",
  "marker-end",
  "marker-mid",
  "marker-start",
  "mask",
  "patterntransform",
  "stroke",
  "transform",
]);

// Only geometry functions are legitimate in presentation attributes. CSS
// escapes (`u\72l(...)`) and comments can hide a function name from a naive
// `url(` scan, so any backslash or unconsumed parenthesis fails closed.
const SAFE_SVG_FUNCTIONS = new Set([
  "matrix",
  "rotate",
  "scale",
  "scalex",
  "scaley",
  "skewx",
  "skewy",
  "translate",
  "translatex",
  "translatey",
]);
const SVG_FUNCTION_PATTERN = /([A-Za-z][\w-]*)\s*\(([^()]*)\)/g;

function isLocalFragmentUrl(value: string): boolean {
  return LOCAL_SVG_FRAGMENT_PATTERN.test(value.trim());
}

function isLocalSvgReference(value: string): boolean {
  const trimmed = value.trim();
  if (trimmed.includes("\\")) {
    return false;
  }
  if (!trimmed.includes("(")) {
    return true;
  }
  const matches = Array.from(trimmed.matchAll(SVG_FUNCTION_PATTERN));
  if (matches.length === 0) {
    return false;
  }
  for (const match of matches) {
    const name = match[1].toLowerCase();
    if (name === "url") {
      const reference = match[2].trim().replace(/^['"]|['"]$/g, "");
      if (!isLocalFragmentUrl(reference)) {
        return false;
      }
    } else if (!SAFE_SVG_FUNCTIONS.has(name)) {
      return false;
    }
  }
  const remainder = trimmed.replace(SVG_FUNCTION_PATTERN, "");
  return !remainder.includes("(") && !remainder.includes(")");
}

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

  const isSvgTag = SVG_TAGS.has(tagName);
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
      (isSvgTag && !isEventHandler && !isStyle && !isUrlAttr);
    const isSafeHref =
      isUrlAttr && isSafeUrl(value) && (!isSvgTag || isLocalFragmentUrl(value));
    const isSvgExternalReference =
      isSvgTag &&
      !isEventHandler &&
      !isUrlAttr &&
      (SVG_CSS_REFERENCE_ATTRS.has(name)
        ? !isLocalSvgReference(value)
        : /url\s*\(/i.test(value) && !isLocalSvgReference(value));
    // The delegated click handler trusts these to recognise a placeholder the
    // sanitizer itself built. Untrusted markup must not be able to forge one:
    // a forged element turns any click into a remote load that looks like
    // the learner's consent.
    const isInternalImageTrigger =
      name === REMOTE_IMAGE_ATTRIBUTE || name.startsWith("data-remote-");
    if (
      isInternalImageTrigger ||
      isEventHandler ||
      isStyle ||
      isSvgExternalReference ||
      (!allowed && !isSafeHref) ||
      (isUrlAttr && !isSafeHref)
    ) {
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

  if (tagName === "img") {
    // Safe to show is not the same as safe to fetch: an image on another
    // site reports the learner's reading to that site. It becomes a
    // placeholder that loads only when the learner clicks it.
    const source = node.getAttribute("src") ?? "";
    if (classifyImageUrl(source) === "remote") {
      node.replaceWith(
        createRemoteImagePlaceholder(node.ownerDocument, source, {
          alt: node.getAttribute("alt") ?? undefined,
          width: node.getAttribute("width") ?? undefined,
          height: node.getAttribute("height") ?? undefined,
        }),
      );
    }
    return;
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
