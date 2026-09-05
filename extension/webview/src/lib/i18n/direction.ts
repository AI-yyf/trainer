export type TextDirection = "ltr" | "rtl";

const RTL_LANGUAGE_CODES = new Set([
  "ar",
  "arc",
  "ckb",
  "dv",
  "fa",
  "he",
  "ku",
  "ps",
  "sd",
  "ug",
  "ur",
  "yi",
]);

function primaryLanguageSubtag(language: string | null | undefined): string | undefined {
  const normalized = language?.trim().toLowerCase().replace(/_/g, "-");
  if (!normalized) {
    return undefined;
  }

  return normalized.split("-", 1)[0] || undefined;
}

/**
 * Keeps direction independent from the currently translated language list.
 * Unknown locale tags deliberately remain LTR until their language is known.
 */
export function resolveTextDirection(language: string | null | undefined): TextDirection {
  const primary = primaryLanguageSubtag(language);
  return primary && RTL_LANGUAGE_CODES.has(primary) ? "rtl" : "ltr";
}

export function isRtlLanguage(language: string | null | undefined): boolean {
  return resolveTextDirection(language) === "rtl";
}
