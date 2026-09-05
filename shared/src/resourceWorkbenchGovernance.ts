export type ResourceWorkbenchSurface = "list" | "detail" | "sandbox";

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
