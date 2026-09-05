function normalizePreviewPath(value: string | undefined): string {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

function hasPreviewSuffix(value: string | undefined, suffixes: Iterable<string>): boolean {
  const normalized = normalizePreviewPath(value);
  if (!normalized) {
    return false;
  }
  for (const suffix of suffixes) {
    if (normalized.endsWith(suffix)) {
      return true;
    }
  }
  return false;
}

const PDF_EXTENSIONS = new Set([".pdf"]);
const DOCX_EXTENSIONS = new Set([".docx", ".docm"]);
const TABULAR_EXTENSIONS = new Set([".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".ods"]);
const SPREADSHEET_EXTENSIONS = new Set([".xlsx", ".xlsm", ".xls", ".ods"]);
const PRESENTATION_EXTENSIONS = new Set([".pptx", ".pptm", ".ppt", ".odp"]);
const NOTEBOOK_EXTENSIONS = new Set([".ipynb"]);
const ARCHIVE_EXTENSIONS = new Set([
  ".zip",
  ".tar",
  ".tar.gz",
  ".tar.bz2",
  ".tar.xz",
  ".tgz",
  ".tbz2",
  ".txz",
  ".7z",
  ".rar",
  ".gz",
  ".bz2",
]);

export function isPdfPreviewPath(value: string | undefined): boolean {
  return hasPreviewSuffix(value, PDF_EXTENSIONS);
}

export function isDocxPreviewPath(value: string | undefined): boolean {
  return hasPreviewSuffix(value, DOCX_EXTENSIONS);
}

export function isTabularPreviewPath(value: string | undefined): boolean {
  return hasPreviewSuffix(value, TABULAR_EXTENSIONS);
}

export function isSpreadsheetPreviewPath(value: string | undefined): boolean {
  return hasPreviewSuffix(value, SPREADSHEET_EXTENSIONS);
}

export function isPresentationPreviewPath(value: string | undefined): boolean {
  return hasPreviewSuffix(value, PRESENTATION_EXTENSIONS);
}

export function isNotebookPreviewPath(value: string | undefined): boolean {
  return hasPreviewSuffix(value, NOTEBOOK_EXTENSIONS);
}

export function isArchivePreviewPath(value: string | undefined): boolean {
  return hasPreviewSuffix(value, ARCHIVE_EXTENSIONS);
}

export function getStructuredPreviewFormat(
  structuredData: Record<string, unknown> | undefined,
): string | undefined {
  const format = structuredData?.format;
  return typeof format === "string" && format.trim().length > 0
    ? format.trim().toLowerCase()
    : undefined;
}

export type PreviewLanguage = "en" | "en-US" | "zh-CN" | "es-ES" | "fr-FR" | "de-DE" | "ja-JP" | "ko-KR" | "pt-BR";

function isZh(language: PreviewLanguage): boolean {
  return language === "zh-CN";
}

function getPreviewSubject(kindLabel: string | undefined, formatBadge: string | undefined): string {
  if (kindLabel && formatBadge) {
    if (["Spreadsheet", "Table", "Presentation", "Notebook", "Archive"].includes(kindLabel)) {
      return `${formatBadge} ${kindLabel.toLowerCase()}`;
    }
    if (["电子表格", "表格", "演示文稿", "压缩包", "Notebook"].includes(kindLabel)) {
      return `${formatBadge} ${kindLabel}`;
    }
  }
  return kindLabel ?? formatBadge ?? "preview";
}

function getPreviewFormatFromPath(path: string | undefined): string | undefined {
  const normalized = normalizePreviewPath(path);
  if (!normalized) {
    return undefined;
  }
  const compoundExtensions = [
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
  ];
  for (const extension of compoundExtensions) {
    if (normalized.endsWith(extension)) {
      return extension.slice(1).toUpperCase();
    }
  }
  const extension = normalized.slice(normalized.lastIndexOf(".") + 1);
  if (!extension || extension === normalized) {
    return undefined;
  }
  return extension.toUpperCase();
}

export function getPreviewFormatBadge(
  structuredData: Record<string, unknown> | undefined,
  path?: string,
): string | undefined {
  const structuredFormat = getStructuredPreviewFormat(structuredData);
  if (structuredFormat) {
    if (
      [
        "xlsx",
        "xlsm",
        "xls",
        "ods",
        "pptx",
        "pptm",
        "ppt",
        "odp",
        "ipynb",
        "zip",
        "tar",
        "tar.gz",
        "tar.bz2",
        "tar.xz",
        "tgz",
        "tbz2",
        "txz",
        "7z",
        "rar",
        "gz",
        "bz2",
        "csv",
        "tsv",
      ].includes(structuredFormat)
    ) {
      return structuredFormat.toUpperCase();
    }
  }

  const fallbackFormat = getPreviewFormatFromPath(path);
  if (
    fallbackFormat &&
    [
      "XLSX",
      "XLSM",
      "XLS",
      "ODS",
      "PPTX",
      "PPTM",
      "PPT",
      "ODP",
      "IPYNB",
      "ZIP",
      "TAR",
      "TAR.GZ",
      "TAR.BZ2",
      "TAR.XZ",
      "TGZ",
      "TBZ2",
      "TXZ",
      "7Z",
      "RAR",
      "GZ",
      "BZ2",
      "CSV",
      "TSV",
    ].includes(fallbackFormat)
  ) {
    return fallbackFormat;
  }

  return undefined;
}

export function getPreviewTierLabel(
  previewTier: "rich" | "converted" | "metadata" | undefined,
  language: PreviewLanguage = "en",
): string | undefined {
  if (!previewTier) {
    return undefined;
  }
  if (previewTier === "rich") {
    return isZh(language) ? "Tier A · 富预览" : "Tier A · Rich preview";
  }
  if (previewTier === "converted") {
    return isZh(language) ? "Tier B · 转换预览" : "Tier B · Converted preview";
  }
  return isZh(language) ? "Tier C · 元数据回退" : "Tier C · Metadata fallback";
}

export function getPreviewKindLabel(
  previewKind: string | undefined,
  previewPath: string | undefined,
  language: PreviewLanguage = "en",
): string | undefined {
  const kind = typeof previewKind === "string" ? previewKind.trim() : "";
  if (!kind) {
    return undefined;
  }
  if (kind === "document" && isPdfPreviewPath(previewPath)) {
    return "PDF";
  }
  if (kind === "document" && isDocxPreviewPath(previewPath)) {
    return "DOCX";
  }
  if (kind === "table" && isSpreadsheetPreviewPath(previewPath)) {
    return isZh(language) ? "电子表格" : "Spreadsheet";
  }
  if (kind === "table" && isTabularPreviewPath(previewPath)) {
    return isZh(language) ? "表格" : "Table";
  }
  if (kind === "notebook" || isNotebookPreviewPath(previewPath)) {
    return isZh(language) ? "Notebook" : "Notebook";
  }
  if (kind === "archive" || isArchivePreviewPath(previewPath)) {
    return isZh(language) ? "压缩包" : "Archive";
  }
  if (kind === "document" && isPresentationPreviewPath(previewPath)) {
    return isZh(language) ? "演示文稿" : "Presentation";
  }

  const labels: Record<string, Record<string, string>> = {
    en: {
      markdown: "Markdown",
      code: "Code",
      table: "Table",
      document: "Document",
      notebook: "Notebook",
      image: "Image",
      audio: "Audio",
      video: "Video",
      archive: "Archive",
      "structured-text": "Structured text",
      markup: "Markup",
      text: "Text",
      directory: "Directory",
    },
    "en-US": {
      markdown: "Markdown",
      code: "Code",
      table: "Table",
      document: "Document",
      notebook: "Notebook",
      image: "Image",
      audio: "Audio",
      video: "Video",
      archive: "Archive",
      "structured-text": "Structured text",
      markup: "Markup",
      text: "Text",
      directory: "Directory",
    },
    "zh-CN": {
      markdown: "Markdown",
      code: "代码",
      table: "Table",
      document: "文档",
      notebook: "Notebook",
      image: "图片",
      audio: "音频",
      video: "视频",
      archive: "压缩包",
      "structured-text": "结构化文本",
      markup: "Markup",
      text: "文本",
      directory: "目录",
    },
  };
  return labels[language]?.[kind] ?? labels.en[kind] ?? kind;
}

export function getPreviewModeSummary(
  preview: {
    previewKind?: string;
    previewTier?: "rich" | "converted" | "metadata";
    path?: string;
    assetUri?: string;
    structuredData?: Record<string, unknown>;
  } | undefined,
  language: PreviewLanguage = "en",
): string | undefined {
  if (!preview) {
    return undefined;
  }

  const kind = preview.previewKind?.trim() || "";
  const formatBadge = getPreviewFormatBadge(preview.structuredData, preview.path);
  const subject = getPreviewSubject(
    getPreviewKindLabel(kind, preview.path, language),
    formatBadge,
  );
  const structuredFormat = getStructuredPreviewFormat(preview.structuredData);

  if ((kind === "image" || kind === "audio" || kind === "video") && preview.previewTier === "metadata") {
    return isZh(language)
      ? "当前预览只保留元数据和打开建议。需要高保真查看时，直接打开 VS Code 原生编辑器。"
      : "This quick preview stays at metadata and native-open guidance. Open the VS Code editor for high-fidelity viewing.";
  }

  if (kind === "document" && isPdfPreviewPath(preview.path) && preview.assetUri) {
    return isZh(language)
      ? "Trainer 正在用 PDF.js 直接渲染这个文档，以便在侧边栏里保持富预览。"
      : "Trainer is rendering this document with PDF.js so the sidebar can keep a rich preview.";
  }

  if (kind === "document" && isDocxPreviewPath(preview.path) && preview.assetUri) {
    return isZh(language)
      ? "Trainer 正在用 DOCX 富预览直接渲染这个文档，以便在侧边栏里保持可读结构。"
      : "Trainer is rendering this DOCX with a rich document viewer so the sidebar can keep readable structure.";
  }

  if (kind === "table" && preview.previewTier === "rich") {
    return isZh(language)
      ? `Trainer 正在把这个${subject}渲染成行列视图，方便在侧边栏里直接教学。`
      : `Trainer is rendering this ${subject} as rows and columns so the sidebar can teach from the cells directly.`;
  }

  if (kind === "notebook" && preview.previewTier === "rich") {
    return isZh(language)
      ? `Trainer 正在把这个${subject}渲染成紧凑的单元轮廓，方便在侧边栏里直接教学。`
      : `Trainer is rendering this ${subject} as a compact cell outline so the sidebar can teach from notebook structure directly.`;
  }

  if (kind === "archive" && preview.previewTier === "rich") {
    return isZh(language)
      ? `Trainer 正在把这个${subject}渲染成受控条目索引，方便在侧边栏里直接教学。`
      : `Trainer is rendering this ${subject} as a governed entry index so the sidebar can teach from entries without unpacking everything inline.`;
  }

  if (kind === "document" && isPresentationPreviewPath(preview.path) && preview.previewTier === "rich") {
    return isZh(language)
      ? `Trainer 正在把这个${subject}渲染成结构化轮廓，先看标题和讲稿要点。`
      : `Trainer is rendering this ${subject} as a structured outline so the sidebar can teach from titles and slide notes first.`;
  }

  if ((kind === "notebook" || isNotebookPreviewPath(preview.path)) && preview.previewTier === "metadata") {
    return isZh(language)
      ? `当前这个${subject}只展示元数据和受控边界，后续再进入更细的结构化预览。`
      : `This ${subject} stays at metadata and guarded-boundary context before deeper structural preview.`;
  }

  if ((kind === "archive" || isArchivePreviewPath(preview.path)) && preview.previewTier === "metadata") {
    return isZh(language)
      ? `当前这个${subject}只展示元数据和受控边界，后续再进入更细的结构化预览。`
      : `This ${subject} stays at metadata and guarded-boundary context before deeper structural preview.`;
  }

  if ((kind === "archive" || isArchivePreviewPath(preview.path)) && preview.previewTier === "converted") {
    return isZh(language)
      ? `Trainer 正在使用受控的${subject}条目索引做教学和引用，会先从条目与片段开始，再决定是否打开原始文件。`
      : `Trainer is using a governed ${subject} entry index for teaching and citation, starting from entries and snippets before opening the original file.`;
  }

  if (preview.previewTier === "converted") {
    if (kind === "document" && structuredFormat === "pptx") {
      return isZh(language)
        ? `Trainer 正在把这个${subject}转成结构化轮廓，先看标题和要点，再决定是否打开原稿。`
        : `Trainer is turning this ${subject} into a structured outline, starting from titles and key points before opening the source.`;
    }
    if (kind === "table" && ["xlsx", "xlsm", "xls", "ods"].includes(structuredFormat ?? "")) {
      return isZh(language)
        ? `Trainer 正在把这个${subject}转成表格视图，先看列与样例行，再决定是否进入原始文件。`
        : `Trainer is turning this ${subject} into a table view, starting with columns and sample rows before opening the source.`;
    }
    if ((kind === "notebook" || isNotebookPreviewPath(preview.path)) && structuredFormat === "ipynb") {
      return isZh(language)
        ? `Trainer 正在把这个${subject}转成结构化单元轮廓，先看 cells 和 outputs，再决定是否打开原稿。`
        : `Trainer is turning this ${subject} into a structured cell outline, starting from cells and outputs before opening the source.`;
    }
    if ((kind === "archive" || isArchivePreviewPath(preview.path)) && (structuredFormat === "zip" || !structuredFormat)) {
      return isZh(language)
        ? `Trainer 正在把这个${subject}转成受控条目索引，先看条目和片段，再决定是否打开原稿。`
        : `Trainer is turning this ${subject} into a governed entry index, starting from entries and snippets before opening the source.`;
    }
    return isZh(language)
      ? "Trainer 正在使用转换后的结构化文本做教学和引用，同时保留打开原文件的路径。"
      : "Trainer is using converted structured text for teaching and citation, while the original file stays available to open.";
  }

  if (preview.previewTier === "metadata") {
    return isZh(language)
      ? `这是当前${subject}的快速预览。先在这里保持轻量理解，需要完整细节时再打开原生编辑器。`
      : `This is the quick preview for the current ${subject}. Keep it lightweight here, then open the native editor when you need full fidelity.`;
  }

  if (kind === "notebook" || isNotebookPreviewPath(preview.path)) {
    return isZh(language)
      ? `Trainer 正在把这个${subject}渲染成紧凑的单元轮廓，方便在侧边栏里直接教学。`
      : `Trainer is rendering this ${subject} as a compact cell outline so the sidebar can teach from notebook structure directly.`;
  }

  if (kind === "archive" || isArchivePreviewPath(preview.path)) {
    return isZh(language)
      ? `Trainer 正在把这个${subject}渲染成受控条目索引，方便在侧边栏里直接教学。`
      : `Trainer is rendering this ${subject} as a governed entry index so the sidebar can teach from entries without unpacking everything inline.`;
  }

  if (kind === "document" && isPresentationPreviewPath(preview.path)) {
    return isZh(language)
      ? `Trainer 正在把这个${subject}渲染成结构化轮廓，先看标题和讲稿要点。`
      : `Trainer is rendering this ${subject} as a structured outline so the sidebar can teach from titles and slide notes first.`;
  }

  return isZh(language)
    ? "这是当前资料的快速预览。先在这里保持轻量理解，需要完整细节时再打开原生编辑器。"
    : "This is the quick preview for the current resource. Keep it lightweight here, then open the native editor when you need full fidelity.";
}
