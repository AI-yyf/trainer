/**
 * Remote images and the learner's privacy.
 *
 * An `<img>` that points at another site tells that site who is reading and
 * when — and, through the address itself, what the model or an imported
 * document was talking about. Model output and imported documents are not
 * trusted with that, so a remote image never loads on its own: it becomes a
 * placeholder until the learner clicks it.
 *
 * Local sources load as before: data URIs, blobs, the extension's own webview
 * resources and the sidecar on loopback.
 */

import type { ComposerLanguage } from "./types";
import { messageRichContentCopy } from "./i18n/segments/messageRichContentCopy";

const LOCAL_IMAGE_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);
/** `webview.asWebviewUri()` addresses: the extension's own files, served by VS Code. */
const LOCAL_IMAGE_HOST_SUFFIX = ".vscode-cdn.net";
const LOCAL_IMAGE_SCHEMES = ["data:", "blob:", "vscode-resource:", "vscode-webview-resource:"];

export type ImageSourceKind = "local" | "remote";

/** `"local"` loads on its own, `"remote"` waits for a click, `null` is not an image address. */
export function classifyImageUrl(src: string | null | undefined): ImageSourceKind | null {
  const raw = String(src ?? "").trim();
  if (!raw) {
    return null;
  }
  const lower = raw.toLowerCase();
  if (LOCAL_IMAGE_SCHEMES.some((scheme) => lower.startsWith(scheme))) {
    return "local";
  }
  // Classify the address the browser will actually fetch. `new URL` applies
  // the browser's own normalization: `https:\\host\\x.png` and `http:host/x.png`
  // are absolute network addresses even though they do not start with
  // "https://", a network-path reference ("//host/x.png") inherits the page's
  // scheme, and tab/newline characters inside the address are ignored. A
  // prefix test missed every one of them and left the image live, loading
  // without the learner's click.
  let resolved: URL;
  try {
    resolved = new URL(raw);
  } catch {
    const base = typeof document !== "undefined" ? document.baseURI : "";
    if (!base) {
      return null;
    }
    try {
      resolved = new URL(raw, base);
    } catch {
      return null;
    }
  }
  if (resolved.protocol !== "http:" && resolved.protocol !== "https:") {
    return null;
  }
  const host = resolved.hostname.toLowerCase();
  if (LOCAL_IMAGE_HOSTS.has(host) || host.endsWith(LOCAL_IMAGE_HOST_SUFFIX)) {
    return "local";
  }
  return "remote";
}

/** The part of a remote address a learner recognises: its host. */
export function describeRemoteImageHost(src: string): string {
  try {
    return new URL(src).host;
  } catch {
    return "";
  }
}

export interface RemoteImageLabels {
  load: string;
  hint: string;
}

let languageResolver: () => ComposerLanguage = () => "en-US";

/** The workbench store is the one place that knows the UI language outside React. */
export function setRemoteImageLanguageResolver(resolver: () => ComposerLanguage): void {
  languageResolver = resolver;
}

export function remoteImageLabels(): RemoteImageLabels {
  const language = languageResolver();
  return {
    load: messageRichContentCopy(language, "加载远程图片"),
    hint: messageRichContentCopy(language, "远程图片在你点击之前不会加载，以免对方站点得知你正在阅读。"),
  };
}

export const REMOTE_IMAGE_ATTRIBUTE = "data-trainer-remote-image";
export const REMOTE_IMAGE_SOURCE_ATTRIBUTE = "data-remote-src";

/** Build the placeholder an HTML preview shows in place of a remote image. */
export function createRemoteImagePlaceholder(
  owner: Document,
  src: string,
  options: { alt?: string; width?: string; height?: string } = {},
): HTMLButtonElement {
  const labels = remoteImageLabels();
  const button = owner.createElement("button");
  button.setAttribute("type", "button");
  button.setAttribute("class", "trainer-remote-image");
  button.setAttribute(REMOTE_IMAGE_ATTRIBUTE, "true");
  button.setAttribute(REMOTE_IMAGE_SOURCE_ATTRIBUTE, src);
  button.setAttribute("title", labels.hint);
  const alt = String(options.alt ?? "").trim();
  if (alt) {
    button.setAttribute("data-remote-alt", alt);
  }
  for (const dimension of ["width", "height"] as const) {
    const value = String(options[dimension] ?? "").trim();
    if (/^\d{1,5}$/.test(value)) {
      button.setAttribute(`data-remote-${dimension}`, value);
    }
  }
  button.setAttribute("aria-label", `${labels.load} · ${describeRemoteImageHost(src)}`);

  button.appendChild(textPart(owner, "trainer-remote-image__icon", "▣", { "aria-hidden": "true" }));
  const text = owner.createElement("span");
  text.setAttribute("class", "trainer-remote-image__text");
  text.appendChild(textPart(owner, "trainer-remote-image__label", labels.load));
  const host = describeRemoteImageHost(src);
  if (host) {
    text.appendChild(textPart(owner, "trainer-remote-image__host", host));
  }
  if (alt) {
    text.appendChild(textPart(owner, "trainer-remote-image__alt", alt));
  }
  button.appendChild(text);
  return button;
}

function textPart(owner: Document, className: string, text: string, extra: Record<string, string> = {}): HTMLElement {
  const part = owner.createElement("span");
  part.setAttribute("class", className);
  for (const [name, value] of Object.entries(extra)) {
    part.setAttribute(name, value);
  }
  part.textContent = text;
  return part;
}

/** Swap one placeholder for the image it stands for. The learner asked for it. */
export function activateRemoteImage(placeholder: Element): HTMLImageElement | null {
  const owner = placeholder.ownerDocument;
  const src = placeholder.getAttribute(REMOTE_IMAGE_SOURCE_ATTRIBUTE) ?? "";
  if (classifyImageUrl(src) !== "remote") {
    return null;
  }
  const image = owner.createElement("img");
  image.setAttribute("src", src);
  image.setAttribute("alt", placeholder.getAttribute("data-remote-alt") ?? "");
  image.setAttribute("loading", "lazy");
  image.setAttribute("class", "trainer-remote-image--loaded");
  for (const dimension of ["width", "height"] as const) {
    const value = placeholder.getAttribute(`data-remote-${dimension}`);
    if (value) {
      image.setAttribute(dimension, value);
    }
  }
  placeholder.replaceWith(image);
  return image;
}

let activationInstalled = false;

/**
 * One delegated listener covers every sanitized HTML preview: placeholders
 * are plain markup without React handlers, so a click anywhere in the document
 * that lands on one loads that one image.
 */
export function installRemoteImageActivation(root: Document | HTMLElement = document): () => void {
  if (activationInstalled && root === document) {
    return () => undefined;
  }
  const handleClick = (event: Event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const placeholder = target.closest(`[${REMOTE_IMAGE_ATTRIBUTE}]`);
    if (placeholder) {
      event.preventDefault();
      activateRemoteImage(placeholder);
    }
  };
  root.addEventListener("click", handleClick);
  if (root === document) {
    activationInstalled = true;
  }
  return () => {
    root.removeEventListener("click", handleClick);
    if (root === document) {
      activationInstalled = false;
    }
  };
}
