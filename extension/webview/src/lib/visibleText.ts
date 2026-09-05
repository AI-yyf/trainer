const LATIN1_MOJIBAKE_PATTERN =
  /(?:[\u00c2\u00c3\u00c4\u00c5\u00c6\u00c7\u00c8\u00c9\u00cf\u00d0\u00e2\u00e3\u00e4\u00e5\u00e6\u00e7\u00e8\u00e9\u00ef\u00f0][\u0080-\u00bf]{1,2}){2,}/u;

const GBK_MOJIBAKE_MARKERS = [
  "\u6d93",
  "\u7f01",
  "\u93c8",
  "\u59e3",
  "\u8930",
  "\u93b4",
  "\u9410",
  "\u7487",
  "\u95c4",
  "\u9359",
  "\u9365",
  "\u5a0c",
  "\u741b",
  "\u5bf0",
] as const;

const GBK_MOJIBAKE_FRAGMENTS = [
  "\u6d93\u5b29\u7af4",
  "\u7f01\u0445\u753b",
  "\u6fe1\u509b\u7049",
  "\u8930\u64b3\u58a0",
  "\u59e3\u5fd3\u59e9",
  "\u93c8\u20ac",
  "\u95c4\u52eb",
  "\u9365\u5267\u5896",
  "\u741b\u30e4\u7af5",
] as const;

export function isLikelyMojibake(value: unknown): boolean {
  if (typeof value !== "string") {
    return false;
  }

  const text = value.trim();
  if (!text) {
    return false;
  }

  return (
    /[\ufffd\ue000-\uf8ff]/u.test(text) ||
    GBK_MOJIBAKE_FRAGMENTS.some((fragment) => text.includes(fragment)) ||
    GBK_MOJIBAKE_MARKERS.filter((marker) => text.includes(marker)).length >= 2 ||
    LATIN1_MOJIBAKE_PATTERN.test(text)
  );
}

export function sanitizeVisibleText(value: unknown, fallback = ""): string {
  return typeof value === "string" && !isLikelyMojibake(value) ? value : fallback;
}

export function sanitizeVisibleData<T>(value: T): T {
  if (typeof value === "string") {
    return sanitizeVisibleText(value) as T;
  }
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeVisibleData(item)) as T;
  }
  if (!value || typeof value !== "object") {
    return value;
  }

  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    return value;
  }

  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [key, sanitizeVisibleData(item)]),
  ) as T;
}

export function splitSafeVisibleStreamText(
  pending: string,
  incoming: string,
): { visible: string; pending: string; rejected: boolean } {
  const candidate = `${pending}${incoming}`;
  if (isLikelyMojibake(candidate)) {
    return { visible: "", pending: "", rejected: true };
  }

  const heldSuffixLength = Math.max(
    0,
    ...GBK_MOJIBAKE_FRAGMENTS.flatMap((fragment) => {
      const maxLength = Math.min(candidate.length, fragment.length - 1);
      for (let length = maxLength; length > 0; length -= 1) {
        if (candidate.endsWith(fragment.slice(0, length))) {
          return [length];
        }
      }
      return [];
    }),
  );

  return heldSuffixLength > 0
    ? {
        visible: candidate.slice(0, -heldSuffixLength),
        pending: candidate.slice(-heldSuffixLength),
        rejected: false,
      }
    : { visible: candidate, pending: "", rejected: false };
}
