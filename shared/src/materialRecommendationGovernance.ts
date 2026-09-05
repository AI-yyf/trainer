export type MaterialRecommendation = "simpler" | "current" | "transfer";
export type MaterialOrientationKey = "simpler" | "current" | "transfer" | "transfer_blocked";

function text(value: string | number | undefined): string {
  return String(value ?? "").trim();
}

export function normalizeMaterialRecommendation(value: string | undefined): MaterialRecommendation {
  const normalized = text(value).toLowerCase();
  if (normalized === "simpler") {
    return "simpler";
  }
  if (normalized === "transfer") {
    return "transfer";
  }
  return "current";
}

export function canRecommendTransferMaterials(input: {
  transferSceneCount?: number;
  transferState?: string;
}): boolean {
  const sceneCount = Number(input.transferSceneCount ?? 0);
  const state = text(input.transferState).toLowerCase().replace(/-/g, "_");
  return sceneCount >= 2 || state === "transferable";
}

export function resolveMaterialOrientationKey(input: {
  materialRecommendation?: string;
  transferSceneCount?: number;
  transferState?: string;
}): MaterialOrientationKey | undefined {
  const raw = text(input.materialRecommendation);
  if (!raw) {
    return undefined;
  }
  const requested = normalizeMaterialRecommendation(raw);
  if (requested === "transfer" && !canRecommendTransferMaterials(input)) {
    return "transfer_blocked";
  }
  return requested;
}
