export type TransferWorkspaceOption = {
  workspaceId: string;
  label: string;
  detail?: string;
  recommended?: boolean;
};

type TransferWorkspaceContribution = {
  workspaceId: string;
  workspaceLabel?: string;
  title?: string;
  status?: "active" | "blocked" | "completed" | "idle";
  topFocusArea?: string;
  latestSummary?: string;
};

type TransferEvidenceSeed = {
  sourceWorkspaceId?: string;
  targetWorkspaceId?: string;
  sourceContext?: string;
  targetContext?: string;
  relatedApi?: string;
  scenario?: string;
  verifiedResult?: string;
  evidenceSummary?: string;
};

type TransferWeakItem = {
  key?: string;
  label?: string;
  relatedApi?: string;
  scenario?: string;
  nextAction?: string;
};

type TransferDependencySeed = {
  dependencyKey: string;
  dependencyName: string;
  projectFirstCut?: string;
  suggestedScenarioLab?: string;
  prioritySummary?: string;
};

export type TransferEvidenceDraft = {
  dependencyKey: string;
  sourceWorkspaceId: string;
  targetWorkspaceId: string;
  sourceContext: string;
  targetContext: string;
  verifiedResult: string;
  evidenceSummary: string;
  focusItemKey?: string;
  relatedApi?: string;
  scenario?: string;
};

function normalizeText(value?: string): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  return normalized ? normalized : undefined;
}

function uniqueParts(values: Array<string | undefined>): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const normalized = normalizeText(value);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

export function buildTransferWorkspaceOptions(input: {
  currentWorkspaceId?: string;
  currentProject?: TransferWorkspaceContribution;
  otherProjects?: TransferWorkspaceContribution[];
  recommendedWorkspaceId?: string;
}): TransferWorkspaceOption[] {
  const currentWorkspaceId = normalizeText(input.currentWorkspaceId);
  const recommendedWorkspaceId = normalizeText(input.recommendedWorkspaceId);
  const contributions = [input.currentProject, ...(input.otherProjects ?? [])].filter(
    (item): item is TransferWorkspaceContribution => Boolean(item?.workspaceId),
  );
  const options = new Map<string, TransferWorkspaceOption>();

  for (const item of contributions) {
    const workspaceId = normalizeText(item.workspaceId);
    if (!workspaceId || workspaceId === currentWorkspaceId) {
      continue;
    }
    const label = normalizeText(item.workspaceLabel) || normalizeText(item.title) || workspaceId;
    const detail = uniqueParts([
      item.topFocusArea,
      item.latestSummary,
      item.status === "blocked"
        ? "Blocked"
        : item.status === "completed"
          ? "Completed"
          : item.status === "active"
            ? "Active"
            : undefined,
    ]).join(" | ");
    const previous = options.get(workspaceId);
    options.set(workspaceId, {
      workspaceId,
      label: previous?.label || label,
      detail: previous?.detail || detail,
      recommended: workspaceId === recommendedWorkspaceId || previous?.recommended,
    });
  }

  return [...options.values()].sort((left, right) => {
    if (left.recommended !== right.recommended) {
      return left.recommended ? -1 : 1;
    }
    return left.label.localeCompare(right.label);
  });
}

export function buildTransferEvidenceDraft(input: {
  currentWorkspaceId?: string;
  coachFocus?: string;
  returnTarget?: string;
  dependency: TransferDependencySeed;
  workspaceOptions?: TransferWorkspaceOption[];
  latestTransfer?: {
    sourceWorkspaceId?: string;
    targetWorkspaceId?: string;
    verifiedResult?: string;
  };
  latestEvidence?: TransferEvidenceSeed;
  weakItem?: TransferWeakItem;
}): TransferEvidenceDraft {
  const sourceWorkspaceId =
    normalizeText(input.currentWorkspaceId) ||
    normalizeText(input.latestTransfer?.sourceWorkspaceId) ||
    normalizeText(input.latestEvidence?.sourceWorkspaceId) ||
    "";
  const workspaceOptions = input.workspaceOptions ?? [];
  const latestTargetWorkspaceId =
    normalizeText(input.latestTransfer?.targetWorkspaceId) ||
    normalizeText(input.latestEvidence?.targetWorkspaceId);
  const targetWorkspaceId =
    latestTargetWorkspaceId &&
    latestTargetWorkspaceId !== sourceWorkspaceId &&
    workspaceOptions.some((item) => item.workspaceId === latestTargetWorkspaceId)
      ? latestTargetWorkspaceId
      : workspaceOptions.find((item) => item.workspaceId !== sourceWorkspaceId)?.workspaceId || "";
  const targetContext =
    normalizeText(input.latestEvidence?.targetContext) ||
    normalizeText(input.weakItem?.scenario) ||
    normalizeText(input.weakItem?.nextAction) ||
    normalizeText(input.returnTarget) ||
    normalizeText(input.dependency.suggestedScenarioLab) ||
    normalizeText(input.dependency.projectFirstCut) ||
    normalizeText(input.dependency.prioritySummary) ||
    "";
  const verifiedResult =
    normalizeText(input.latestTransfer?.verifiedResult) ||
    normalizeText(input.latestEvidence?.verifiedResult) ||
    normalizeText(input.weakItem?.nextAction) ||
    normalizeText(input.returnTarget) ||
    normalizeText(input.dependency.projectFirstCut) ||
    "";

  return {
    dependencyKey: input.dependency.dependencyKey,
    sourceWorkspaceId,
    targetWorkspaceId,
    sourceContext:
      normalizeText(input.latestEvidence?.sourceContext) ||
      uniqueParts([input.dependency.dependencyName, input.coachFocus]).join(" | "),
    targetContext,
    verifiedResult,
    evidenceSummary:
      normalizeText(input.latestEvidence?.evidenceSummary) ||
      uniqueParts([input.dependency.dependencyName, input.weakItem?.label, targetContext, verifiedResult]).join(
        " | ",
      ),
    focusItemKey: normalizeText(input.weakItem?.key),
    relatedApi:
      normalizeText(input.weakItem?.relatedApi) || normalizeText(input.latestEvidence?.relatedApi),
    scenario:
      normalizeText(input.weakItem?.scenario) || normalizeText(input.latestEvidence?.scenario),
  };
}
