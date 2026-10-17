/**
 * P2 #21: subject-scoped skill dimension registry (webview side).
 *
 * The server projects evidence onto the dimensions declared by the
 * workspace's SubjectProfile (code: comprehension/implementation/debugging/
 * transfer; literature: comprehension/expression/appreciation/transfer).
 * Growth rows follow the registry order, filtered to what the projection
 * actually carries; snapshots that predate the registry keep the historical
 * four-row layout. Pure data + pure function — no React, no VS Code.
 */

export type DimensionKey = import("./types").TrainingSkillDimensionKey;

export interface ProjectionDimensionsCarrier {
  dimensions?: Record<string, unknown>;
}

export const REGISTRY_ORDER: DimensionKey[] = [
  "comprehension",
  "implementation",
  "debugging",
  "expression",
  "appreciation",
  "transfer",
];

export const LEGACY_CODE_ORDER: DimensionKey[] = [
  "comprehension",
  "implementation",
  "debugging",
  "transfer",
];

export function dimensionKeysFor(projection: ProjectionDimensionsCarrier | undefined): DimensionKey[] {
  const dims = projection?.dimensions;
  if (!dims || typeof dims !== "object") return LEGACY_CODE_ORDER;
  const carried = Object.keys(dims) as DimensionKey[];
  const known = carried.filter((key) => REGISTRY_ORDER.includes(key));
  return known.length > 0
    ? REGISTRY_ORDER.filter((key) => known.includes(key))
    : LEGACY_CODE_ORDER;
}
