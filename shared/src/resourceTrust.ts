export type ResourceTrustState = "trusted" | "unknown" | "stale" | "untrusted";

export interface ResourceTrustFacts {
  trustScore?: number;
  freshness?: string;
  qualityFlags?: readonly string[];
}

export const resourceTrainingBlockingQualityFlags = new Set([
  "network_disabled",
  "fetch_failed",
  "blocked_source",
  "no_content",
  "source_conflict",
]);

export function deriveResourceTrustState({
  trustScore,
  freshness,
  qualityFlags,
}: ResourceTrustFacts): ResourceTrustState {
  const normalizedFlags = new Set(
    (qualityFlags ?? []).map((flag) => flag.trim().toLowerCase()).filter(Boolean),
  );
  if ([...normalizedFlags].some((flag) => resourceTrainingBlockingQualityFlags.has(flag))) {
    return "untrusted";
  }
  if (freshness?.trim().toLowerCase() === "stale") {
    return "stale";
  }
  if (typeof trustScore === "number" && trustScore >= 0.75 && normalizedFlags.size === 0) {
    return "trusted";
  }
  if (typeof trustScore === "number" && trustScore >= 0.45) {
    return "unknown";
  }
  return "untrusted";
}
