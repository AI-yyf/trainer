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

export function isPdfPreviewPath(value: string | undefined): boolean {
  return hasPreviewSuffix(value, PDF_EXTENSIONS);
}

export function isDocxPreviewPath(value: string | undefined): boolean {
  return hasPreviewSuffix(value, DOCX_EXTENSIONS);
}
