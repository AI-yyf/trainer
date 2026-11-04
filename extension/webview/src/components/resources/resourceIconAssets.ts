import fileIcon from "../../assets/resource-icons/file.svg?url";
import documentIcon from "../../assets/resource-icons/document.svg?url";
import markdownIcon from "../../assets/resource-icons/markdown.svg?url";
import pdfIcon from "../../assets/resource-icons/pdf.svg?url";
import urlIcon from "../../assets/resource-icons/url.svg?url";
import imageIcon from "../../assets/resource-icons/image.svg?url";
import videoIcon from "../../assets/resource-icons/video.svg?url";
import zipIcon from "../../assets/resource-icons/zip.svg?url";
import tableIcon from "../../assets/resource-icons/table.svg?url";
import wordIcon from "../../assets/resource-icons/word.svg?url";
import powerpointIcon from "../../assets/resource-icons/powerpoint.svg?url";
import lockIcon from "../../assets/resource-icons/lock.svg?url";
import pythonIcon from "../../assets/resource-icons/python.svg?url";
import typescriptIcon from "../../assets/resource-icons/typescript.svg?url";
import javascriptIcon from "../../assets/resource-icons/javascript.svg?url";
import jsonIcon from "../../assets/resource-icons/json.svg?url";
import htmlIcon from "../../assets/resource-icons/html.svg?url";
import cssIcon from "../../assets/resource-icons/css.svg?url";
import yamlIcon from "../../assets/resource-icons/yaml.svg?url";
import goIcon from "../../assets/resource-icons/go.svg?url";
import rustIcon from "../../assets/resource-icons/rust.svg?url";
import javaIcon from "../../assets/resource-icons/java.svg?url";
import kotlinIcon from "../../assets/resource-icons/kotlin.svg?url";
import cppIcon from "../../assets/resource-icons/cpp.svg?url";
import csharpIcon from "../../assets/resource-icons/csharp.svg?url";
import xmlIcon from "../../assets/resource-icons/xml.svg?url";
import vueIcon from "../../assets/resource-icons/vue.svg?url";
import svelteIcon from "../../assets/resource-icons/svelte.svg?url";
import folderIcon from "../../assets/resource-icons/folder.svg?url";
import folderOpenIcon from "../../assets/resource-icons/folder-open.svg?url";

export type ResourceIconKey =
  | "file"
  | "document"
  | "markdown"
  | "pdf"
  | "url"
  | "image"
  | "video"
  | "zip"
  | "table"
  | "word"
  | "powerpoint"
  | "lock"
  | "python"
  | "typescript"
  | "javascript"
  | "json"
  | "html"
  | "css"
  | "yaml"
  | "go"
  | "rust"
  | "java"
  | "kotlin"
  | "cpp"
  | "csharp"
  | "xml"
  | "vue"
  | "svelte";

type ResourceIconRecord = {
  kind?: string;
  fileType?: string;
  source?: string;
};

const ICON_URLS: Record<ResourceIconKey, string> = {
  file: fileIcon,
  document: documentIcon,
  markdown: markdownIcon,
  pdf: pdfIcon,
  url: urlIcon,
  image: imageIcon,
  video: videoIcon,
  zip: zipIcon,
  table: tableIcon,
  word: wordIcon,
  powerpoint: powerpointIcon,
  lock: lockIcon,
  python: pythonIcon,
  typescript: typescriptIcon,
  javascript: javascriptIcon,
  json: jsonIcon,
  html: htmlIcon,
  css: cssIcon,
  yaml: yamlIcon,
  go: goIcon,
  rust: rustIcon,
  java: javaIcon,
  kotlin: kotlinIcon,
  cpp: cppIcon,
  csharp: csharpIcon,
  xml: xmlIcon,
  vue: vueIcon,
  svelte: svelteIcon,
};

const CODE_ICONS: Record<string, ResourceIconKey> = {
  py: "python",
  pyw: "python",
  pyi: "python",
  ts: "typescript",
  tsx: "typescript",
  mts: "typescript",
  cts: "typescript",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  json: "json",
  jsonc: "json",
  html: "html",
  htm: "html",
  css: "css",
  scss: "css",
  less: "css",
  sass: "css",
  yaml: "yaml",
  yml: "yaml",
  go: "go",
  rs: "rust",
  java: "java",
  kt: "kotlin",
  kts: "kotlin",
  c: "cpp",
  cc: "cpp",
  cpp: "cpp",
  cxx: "cpp",
  h: "cpp",
  hpp: "cpp",
  cs: "csharp",
  xml: "xml",
  vue: "vue",
  svelte: "svelte",
};

const EXTRA_ICONS: Record<string, ResourceIconKey> = {
  zip: "zip",
  gz: "zip",
  tgz: "zip",
  tar: "zip",
  rar: "zip",
  "7z": "zip",
  xls: "table",
  xlsx: "table",
  csv: "table",
  tsv: "table",
  doc: "word",
  docx: "word",
  ppt: "powerpoint",
  pptx: "powerpoint",
  sha256: "lock",
  sha1: "lock",
  md5: "lock",
};

function sourceExtension(record: ResourceIconRecord): string {
  const raw = String(record.fileType || record.source || "").trim().toLowerCase();
  const clean = raw.split(/[?#]/)[0] ?? "";
  const match = clean.match(/\.([a-z0-9]+)$/);
  return match?.[1] ?? "";
}

/**
 * Map a library record to a Material Icon Theme glyph. The material icons
 * carry their own colour, so the tree stays native and readable in light/dark
 * without per-kind CSS.
 */
export function resourceIconKey(record: ResourceIconRecord): ResourceIconKey {
  const extension = sourceExtension(record);
  if (record.kind === "pdf") return "pdf";
  if (record.kind === "markdown") return "markdown";
  if (record.kind === "url") return "url";
  if (record.kind === "image") return "image";
  if (record.kind === "video") return "video";
  if (record.kind === "code") return CODE_ICONS[extension] ?? "document";
  return EXTRA_ICONS[extension] ?? (record.kind === "text" ? "document" : "file");
}

export function resourceIconUrl(record: ResourceIconRecord): string {
  return ICON_URLS[resourceIconKey(record)];
}

export const resourceFolderIconUrl = folderIcon;
export const resourceFolderOpenIconUrl = folderOpenIcon;
