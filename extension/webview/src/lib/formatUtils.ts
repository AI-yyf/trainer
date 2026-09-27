/**
 * Formatting utilities (§四十八: extracted from App.tsx).
 * Pure functions — no React or state dependencies.
 */

export function formatTokenCount(value: number | undefined): string {
  const tokens = typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
  if (tokens >= 1000000) {
    return `${(tokens / 1000000).toFixed(tokens >= 10000000 ? 0 : 1)}M`;
  }
  if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(tokens >= 10000 ? 0 : 1)}k`;
  }
  return String(tokens);
}

export function providerDraftStringArrayKey(values: string[] | undefined): string {
  return JSON.stringify(
    Array.from(
      new Set(
        (values ?? [])
          .map((value) => value.trim())
          .filter(Boolean)
          .map((value) => value.toLowerCase()),
      ),
    ),
  );
}
