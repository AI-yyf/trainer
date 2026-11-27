import cppIcon from "../../assets/resource-icons/cpp.svg?url";
import csharpIcon from "../../assets/resource-icons/csharp.svg?url";
import cssIcon from "../../assets/resource-icons/css.svg?url";
import documentIcon from "../../assets/resource-icons/document.svg?url";
import fileIcon from "../../assets/resource-icons/file.svg?url";
import folderOpenIcon from "../../assets/resource-icons/folder-open.svg?url";
import folderIcon from "../../assets/resource-icons/folder.svg?url";
import goIcon from "../../assets/resource-icons/go.svg?url";
import htmlIcon from "../../assets/resource-icons/html.svg?url";
import imageIcon from "../../assets/resource-icons/image.svg?url";
import javaIcon from "../../assets/resource-icons/java.svg?url";
import javascriptIcon from "../../assets/resource-icons/javascript.svg?url";
import jsonIcon from "../../assets/resource-icons/json.svg?url";
import kotlinIcon from "../../assets/resource-icons/kotlin.svg?url";
import lockIcon from "../../assets/resource-icons/lock.svg?url";
import markdownIcon from "../../assets/resource-icons/markdown.svg?url";
import pdfIcon from "../../assets/resource-icons/pdf.svg?url";
import powerpointIcon from "../../assets/resource-icons/powerpoint.svg?url";
import pythonIcon from "../../assets/resource-icons/python.svg?url";
import rustIcon from "../../assets/resource-icons/rust.svg?url";
import svelteIcon from "../../assets/resource-icons/svelte.svg?url";
import tableIcon from "../../assets/resource-icons/table.svg?url";
import typescriptIcon from "../../assets/resource-icons/typescript.svg?url";
import urlIcon from "../../assets/resource-icons/url.svg?url";
import videoIcon from "../../assets/resource-icons/video.svg?url";
import vueIcon from "../../assets/resource-icons/vue.svg?url";
import wordIcon from "../../assets/resource-icons/word.svg?url";
import xmlIcon from "../../assets/resource-icons/xml.svg?url";
import yamlIcon from "../../assets/resource-icons/yaml.svg?url";
import zipIcon from "../../assets/resource-icons/zip.svg?url";

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




/**
 * The library is Markdown-only: every row uses the same Markdown glyph. The
 * original source format is provenance, never a visible library type.
 */
export function resourceIconKey(_record: ResourceIconRecord): ResourceIconKey {
  return "markdown";
}

export function resourceIconUrl(record: ResourceIconRecord): string {
  return ICON_URLS[resourceIconKey(record)];
}

export const resourceFolderIconUrl = folderIcon;
export const resourceFolderOpenIconUrl = folderOpenIcon;
