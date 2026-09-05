import { resourceTrainingBlockingQualityFlags } from "./resourceTrust";
import { coachOrientationTone, type CoachOrientationState } from "./coachOrientationGovernance";
import { resolveMaterialOrientationKey } from "./materialRecommendationGovernance";
import { resourcesOrientationCopy } from "./orientationCopy";
import { liveEvidenceBinding } from "./planOrientationGovernance";

export type ResourcesOrientationAction =
  | "import_resource"
  | "wait_index"
  | "retry_index"
  | "preview_resource"
  | "select_resource"
  | "open_plan"
  | "open_training"
  | "open_coach"
  | "wait";

export interface ResourcesOrientationInput {
  resourceCount?: number;
  selectedResourceId?: string;
  selectedResourceTitle?: string;
  indexState?: string;
  resourceStatus?: "ready" | "indexing" | "attention" | string;
  trustState?: string;
  freshness?: "fresh" | "stale" | "unknown" | string;
  qualityFlags?: readonly string[];
  searchQuery?: string;
  searchHitCount?: number;
  searchWorkspaceId?: string;
  currentWorkspaceId?: string;
  hasPreview?: boolean;
  boundPlanId?: string;
  boundTrainingCardId?: string;
  language?: string;
  materialRecommendation?: string;
  transferSceneCount?: number;
  transferState?: string;
}

export interface ResourcesOrientationRecord {
  objectKind: "resources";
  objectLabel: string;
  state: CoachOrientationState;
  why: string;
  primaryAction: ResourcesOrientationAction;
  primaryActionLabel: string;
  nextStep: string;
  advancedWhere: string;
  source: "snapshot";
  revision: number;
}

const ACTIONS = new Set<ResourcesOrientationAction>([
  "import_resource",
  "wait_index",
  "retry_index",
  "preview_resource",
  "select_resource",
  "open_plan",
  "open_training",
  "open_coach",
  "wait",
]);

function text(value: string | undefined): string {
  return value?.trim() ?? "";
}

function normalizeIndexState(value: string | undefined, status: string | undefined): string {
  const index = text(value).toLowerCase();
  const resourceStatus = text(status).toLowerCase();
  if (index === "failed" || resourceStatus === "attention") {
    return "failed";
  }
  if (index === "pending") {
    return "pending";
  }
  if (index === "indexing" || resourceStatus === "indexing") {
    return "indexing";
  }
  if (index === "indexed") {
    return "indexed";
  }
  return index;
}

function blockingFlags(flags: readonly string[] | undefined): string[] {
  return (flags ?? [])
    .map((flag) => flag.trim().toLowerCase())
    .filter((flag) => resourceTrainingBlockingQualityFlags.has(flag));
}

function searchIsCurrent(input: ResourcesOrientationInput): boolean {
  const searchWorkspaceId = text(input.searchWorkspaceId);
  const currentWorkspaceId = text(input.currentWorkspaceId);
  if (!text(input.searchQuery)) {
    return false;
  }
  if (searchWorkspaceId && currentWorkspaceId && searchWorkspaceId !== currentWorkspaceId) {
    return false;
  }
  return true;
}

function record(
  input: Omit<ResourcesOrientationRecord, "objectKind" | "source" | "revision"> & { revision?: number },
  materialNext = "",
): ResourcesOrientationRecord {
  const nextStep =
    materialNext && !input.nextStep.includes(materialNext)
      ? `${input.nextStep} ${materialNext}`.trim()
      : input.nextStep;
  return {
    objectKind: "resources",
    objectLabel: input.objectLabel,
    state: input.state,
    why: input.why,
    primaryAction: input.primaryAction,
    primaryActionLabel: input.primaryActionLabel,
    nextStep,
    advancedWhere: input.advancedWhere,
    source: "snapshot",
    revision: input.revision ?? 1,
  };
}

export function normalizeResourcesOrientationRecord(value: unknown): ResourcesOrientationRecord | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const row = value as Record<string, unknown>;
  const objectLabel = text(
    typeof row.objectLabel === "string"
      ? row.objectLabel
      : typeof row.object_label === "string"
        ? row.object_label
        : "",
  );
  const state = text(typeof row.state === "string" ? row.state : "");
  const why = text(typeof row.why === "string" ? row.why : "");
  const primaryAction = text(
    typeof row.primaryAction === "string"
      ? row.primaryAction
      : typeof row.primary_action === "string"
        ? row.primary_action
        : "",
  ) as ResourcesOrientationAction;
  const primaryActionLabel = text(
    typeof row.primaryActionLabel === "string"
      ? row.primaryActionLabel
      : typeof row.primary_action_label === "string"
        ? row.primary_action_label
        : "",
  );
  const nextStep = text(
    typeof row.nextStep === "string" ? row.nextStep : typeof row.next_step === "string" ? row.next_step : "",
  );
  if (!objectLabel || !state || !why || !ACTIONS.has(primaryAction) || !nextStep) {
    return undefined;
  }
  return {
    objectKind: "resources",
    objectLabel,
    state: state as CoachOrientationState,
    why,
    primaryAction,
    primaryActionLabel,
    nextStep,
    advancedWhere: text(
      typeof row.advancedWhere === "string"
        ? row.advancedWhere
        : typeof row.advanced_where === "string"
          ? row.advanced_where
          : "",
    ),
    source: "snapshot",
    revision: typeof row.revision === "number" && row.revision > 0 ? Math.floor(row.revision) : 1,
  };
}

function materialNextLine(
  copy: ReturnType<typeof resourcesOrientationCopy>,
  input: ResourcesOrientationInput,
): string {
  const key = resolveMaterialOrientationKey({
    materialRecommendation: input.materialRecommendation,
    transferSceneCount: input.transferSceneCount,
    transferState: input.transferState,
  });
  if (key === "simpler") {
    return copy.materialSimpler;
  }
  if (key === "current") {
    return copy.materialCurrent;
  }
  if (key === "transfer") {
    return copy.materialTransfer;
  }
  if (key === "transfer_blocked") {
    return copy.materialTransferBlocked;
  }
  return "";
}

export function deriveResourcesOrientation(input: ResourcesOrientationInput): ResourcesOrientationRecord {
  const copy = resourcesOrientationCopy(input.language);
  const resourceCount = input.resourceCount ?? 0;
  const materialNext = resourceCount > 0 ? materialNextLine(copy, input) : "";
  const emit = (
    fields: Omit<ResourcesOrientationRecord, "objectKind" | "source" | "revision"> & { revision?: number },
  ) => record(fields, materialNext);
  const selectedId = text(input.selectedResourceId);
  const selectedTitle = text(input.selectedResourceTitle);
  const indexState = normalizeIndexState(input.indexState, input.resourceStatus);
  const trustState = text(input.trustState).toLowerCase();
  const freshness = text(input.freshness).toLowerCase();
  const blockedFlags = blockingFlags(input.qualityFlags);
  const boundPlanId = text(input.boundPlanId);
  const boundTrainingCardId = text(input.boundTrainingCardId);
  const currentSearch = searchIsCurrent(input);
  const searchQuery = currentSearch ? text(input.searchQuery) : "";
  const searchHits = currentSearch ? input.searchHitCount ?? 0 : 0;

  if (resourceCount <= 0) {
    return emit({
      objectLabel: copy.resourceLibrary,
      state: "needs_setup",
      why: copy.libraryEmpty,
      primaryAction: "import_resource",
      primaryActionLabel: copy.importResource,
      nextStep: copy.importThenIndex,
      advancedWhere: copy.resourcesEmptyLibrary,
    });
  }

  if (selectedId && indexState === "failed") {
    return emit({
      objectLabel: selectedTitle || copy.currentResource,
      state: "blocked",
      why: copy.indexFailed,
      primaryAction: "retry_index",
      primaryActionLabel: copy.retryIndex,
      nextStep: copy.fixIndexFirst,
      advancedWhere: copy.resourcesFailedIndex,
    });
  }

  if (selectedId && (trustState === "untrusted" || blockedFlags.length > 0)) {
    return emit({
      objectLabel: selectedTitle || copy.currentResource,
      state: "blocked",
      why: copy.sourceUntrusted,
      primaryAction: "retry_index",
      primaryActionLabel: copy.refreshSource,
      nextStep: copy.confirmSourceFirst,
      advancedWhere: copy.resourcesTrust,
    });
  }

  if (selectedId && (indexState === "indexing" || indexState === "pending")) {
    return emit({
      objectLabel: selectedTitle || copy.currentResource,
      state: "working",
      why: copy.stillIndexing,
      primaryAction: "wait",
      primaryActionLabel: copy.wait,
      nextStep: copy.waitIndexThenBind,
      advancedWhere: copy.resourcesIndexing,
    });
  }

  if (selectedId && freshness === "stale") {
    return emit({
      objectLabel: selectedTitle || copy.currentResource,
      state: "waiting",
      why: copy.resourceStale,
      primaryAction: "retry_index",
      primaryActionLabel: copy.refreshIndex,
      nextStep: copy.refreshThenBind,
      advancedWhere: copy.resourcesStale,
    });
  }

  if (searchQuery && searchHits === 0) {
    return emit({
      objectLabel: copy.resourceSearch,
      state: "waiting",
      why: copy.noHits(searchQuery),
      primaryAction: "import_resource",
      primaryActionLabel: copy.importResource,
      nextStep: copy.changeQueryOrImport,
      advancedWhere: copy.resourcesSearch,
    });
  }

  if (searchQuery && !selectedId) {
    return emit({
      objectLabel: copy.resourceSearch,
      state: "waiting",
      why: copy.hitsFound(searchHits),
      primaryAction: "select_resource",
      primaryActionLabel: copy.chooseOne,
      nextStep: copy.selectThenPreview,
      advancedWhere: copy.resourcesSearchHits,
    });
  }

  if (!selectedId) {
    return emit({
      objectLabel: copy.resourceLibrary,
      state: "waiting",
      why: copy.libraryHasItems(resourceCount),
      primaryAction: "select_resource",
      primaryActionLabel: copy.chooseOne,
      nextStep: copy.selectBeforePreview,
      advancedWhere: copy.resourcesList,
    });
  }

  if (boundPlanId) {
    return emit({
      objectLabel: selectedTitle || selectedId,
      state: "ready",
      why: copy.boundToPlan(boundPlanId),
      primaryAction: "open_plan",
      primaryActionLabel: copy.openPlan,
      nextStep: copy.reviewOnPlan,
      advancedWhere: copy.resourcesPlanBinding,
    });
  }

  if (boundTrainingCardId) {
    return emit({
      objectLabel: selectedTitle || selectedId,
      state: "ready",
      why: copy.boundToCard(boundTrainingCardId),
      primaryAction: "open_training",
      primaryActionLabel: copy.openTraining,
      nextStep: copy.continueCard,
      advancedWhere: copy.resourcesTrainingBinding,
    });
  }

  if (!input.hasPreview) {
    return emit({
      objectLabel: selectedTitle || selectedId,
      state: "waiting",
      why: copy.indexedNoPreview,
      primaryAction: "preview_resource",
      primaryActionLabel: copy.preview,
      nextStep: copy.previewBeforeBind,
      advancedWhere: copy.resourcesPreview,
    });
  }

  return emit({
    objectLabel: selectedTitle || selectedId,
    state: "ready",
    why: copy.indexedReadable,
    primaryAction: "preview_resource",
    primaryActionLabel: copy.keepReading,
    nextStep: copy.readThenBindWhenLinked,
    advancedWhere: copy.resourcesCurrentItem,
  });
}

export function resourcesOrientationTone(
  state: CoachOrientationState,
): ReturnType<typeof coachOrientationTone> {
  return coachOrientationTone(state);
}

export function resolveResourcesBindingIds(input: {
  selectedResourceId?: string;
  selectedCitationId?: string;
  planEvidenceBinding?: string;
  livePendingEvidenceIds?: readonly string[];
  recoveredRuntime?: boolean;
  currentStep?: string;
  trainingTargetId?: string;
  trainingTargetKind?: string;
  trainingSourceChain?: readonly string[];
}): { boundPlanId?: string; boundTrainingCardId?: string } {
  const selectedId = text(input.selectedResourceId);
  const citationId = text(input.selectedCitationId);
  const evidenceBinding = liveEvidenceBinding({
    binding: input.planEvidenceBinding,
    pendingIds: input.livePendingEvidenceIds,
    recovered: input.recoveredRuntime,
    currentStep: input.currentStep,
  });
  const trainingTargetId = text(input.trainingTargetId);
  const trainingTargetKind = text(input.trainingTargetKind).toLowerCase();
  const sourceChain = (input.trainingSourceChain ?? []).map((item) => item.trim()).filter(Boolean);
  const boundPlanId =
    selectedId && (evidenceBinding === selectedId || (citationId && evidenceBinding === citationId))
      ? evidenceBinding
      : undefined;
  const namesSelected =
    Boolean(selectedId) &&
    (sourceChain.includes(selectedId) ||
      (trainingTargetKind.includes("resource") && trainingTargetId === selectedId));
  const boundTrainingCardId = namesSelected
    ? trainingTargetId && trainingTargetId !== selectedId
      ? trainingTargetId
      : selectedId
    : undefined;
  return { boundPlanId, boundTrainingCardId };
}
