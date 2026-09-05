/**
 * Central type definitions shared between extension host, webview, and sidecar.
 * This file should be kept minimal and contain only truly universal types.
 */

// =============================================================================
// Language / i18n
// =============================================================================

export type ComposerLanguage =
  | "zh-CN"
  | "en-US"
  | "es-ES"
  | "fr-FR"
  | "de-DE"
  | "ja-JP"
  | "ko-KR"
  | "pt-BR";

export const SUPPORTED_LANGUAGES: ComposerLanguage[] = [
  "zh-CN",
  "en-US",
  "es-ES",
  "fr-FR",
  "de-DE",
  "ja-JP",
  "ko-KR",
  "pt-BR",
];

export function isComposerLanguage(value: unknown): value is ComposerLanguage {
  return typeof value === "string" && SUPPORTED_LANGUAGES.includes(value as ComposerLanguage);
}

export const LANGUAGE_LABELS: Record<ComposerLanguage, string> = {
  "zh-CN": "简体中文",
  "en-US": "English",
  "es-ES": "Español",
  "fr-FR": "Français",
  "de-DE": "Deutsch",
  "ja-JP": "日本語",
  "ko-KR": "한국어",
  "pt-BR": "Português",
};
