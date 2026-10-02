export type ResourceWorkbenchSurface = "list" | "detail" | "sandbox";

/** Match the sidecar's acknowledged-upload rule when removing recovered UI chrome. */
export function resourceRecordIsAcknowledgedUpload(item: {
  sandboxPath?: string;
  canonicalSource?: string;
  sourceType?: string;
  indexState?: string;
  source?: string;
}): boolean {
  return Boolean(
    item.sandboxPath?.trim() || item.canonicalSource?.trim() || item.sourceType?.trim() ||
    ["indexed", "parsed"].includes(item.indexState?.trim().toLowerCase() ?? "") ||
    /^(inline|https?|file|workspace):\/\//i.test(item.source?.trim() ?? ""),
  );
}

export interface ResourceWorkbenchGovernanceInput {
  preferredSurface?: ResourceWorkbenchSurface;
  hasSelectedResource: boolean;
  hasDetail: boolean;
  hasSandbox: boolean;
}

export interface ResourceWorkbenchGovernanceResult {
  activeSurface: ResourceWorkbenchSurface;
  canOpenDetail: boolean;
  canOpenSandbox: boolean;
  showDetail: boolean;
  showSandbox: boolean;
}

export function resolveResourceWorkbenchGovernance(
  input: ResourceWorkbenchGovernanceInput,
): ResourceWorkbenchGovernanceResult {
  const canOpenDetail = input.hasSelectedResource;
  const canOpenSandbox = input.hasSandbox;
  let activeSurface: ResourceWorkbenchSurface = input.preferredSurface ?? "list";

  if (activeSurface === "detail" && !canOpenDetail) {
    activeSurface = canOpenSandbox ? "sandbox" : "list";
  }

  if (activeSurface === "sandbox" && !canOpenSandbox) {
    activeSurface = canOpenDetail ? "detail" : "list";
  }

  const showDetail = activeSurface === "detail" && input.hasDetail;
  const showSandbox = activeSurface === "sandbox" && input.hasSandbox;

  return {
    activeSurface,
    canOpenDetail,
    canOpenSandbox,
    showDetail,
    showSandbox,
  };
}
