import { resourceTrainingBlockingQualityFlags } from "./resourceTrust";
import { type CoachOrientationState } from "./coachOrientationGovernance";
import { resolveMaterialOrientationKey } from "./materialRecommendationGovernance";
import { resourcesOrientationCopy } from "./orientationCopy";
import { liveEvidenceBinding } from "./planOrientationGovernance";

export type ResourcesOrientationAction =
  | "import_resource"
  | "wait_index"
  | "retry_index"
  | "open_resource"
  | "select_resource"
  | "open_plan"
  | "open_training"
  | "open_coach"
  | "wait"
  | "bind_learning_folder";

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
  canOpenResource?: boolean;
  boundPlanId?: string;
  boundTrainingCardId?: string;
  language?: string;
  materialRecommendation?: string;
  transferSceneCount?: number;
  transferState?: string;
  /** Present when the workspace is not admitted for a managed library (see deriveAdmissionBindOrientation). */
  admission?: AdmissionBindOrientation;
}

/** The one host step that moves an un-admitted workspace toward a managed library. */
export type AdmissionBindStep = "choose_learning_folder" | "add_current_project" | "choose_project_folder";

export interface AdmissionBindOrientation {
  step: AdmissionBindStep;
  why: string;
  primaryActionLabel: string;
  nextStep: string;
}

const UNADMITTED_WITH_PROJECT = new Set(["browse", "ignored"]);

/**
 * Zero-interception cold start (product contract §4): nothing is saved until the learner binds a
 * learning folder, so the first screen that needs a save offers exactly that step. Without a root
 * the step is choosing one; once a project is known the step is adding it, which leads to the root.
 * A managed or unknown status yields nothing and leaves the normal orientation in place.
 */
export function deriveAdmissionBindOrientation(input: {
  status?: string;
  projectPath?: string;
  language?: string;
}): AdmissionBindOrientation | undefined {
  const status = text(input.status);
  if (!status || status === "managed") {
    return undefined;
  }
  const copy = resourcesOrientationCopy(input.language);
  if (status === "root-missing") {
    return {
      step: "choose_learning_folder",
      why: copy.libraryNeedsLearningFolder,
      primaryActionLabel: copy.chooseLearningFolder,
      nextStep: copy.bindThenImport,
    };
  }
  if (status === "project-found" && !text(input.projectPath)) {
    return {
      step: "choose_project_folder",
      why: copy.libraryNeedsProjectDecision,
      primaryActionLabel: copy.chooseProjectFolder,
      nextStep: copy.bindThenImport,
    };
  }
  if (status !== "project-found" && !UNADMITTED_WITH_PROJECT.has(status)) {
    return undefined;
  }
  return {
    step: "add_current_project",
    why: copy.libraryNeedsProjectDecision,
    primaryActionLabel: copy.addCurrentProject,
    nextStep: copy.bindThenImport,
  };
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
  /** Set only for `bind_learning_folder`: which admission step the action runs. */
  admissionStep?: AdmissionBindStep;
}

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
    ...(input.admissionStep ? { admissionStep: input.admissionStep } : {}),
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

  if (input.admission) {
    // Nothing can be saved yet, so no other action is honest — not even for a library that already
    // has resources. The material line is left out: it is advice for a working library.
    return record({
      objectLabel: copy.resourceLibrary,
      state: "needs_setup",
      why: input.admission.why,
      primaryAction: "bind_learning_folder",
      primaryActionLabel: input.admission.primaryActionLabel,
      nextStep: input.admission.nextStep,
      advancedWhere: copy.resourcesEmptyLibrary,
      admissionStep: input.admission.step,
    });
  }

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

  if (!input.canOpenResource) {
    return emit({
      objectLabel: selectedTitle || selectedId,
      state: "waiting",
      why: copy.indexedNoPreview,
      primaryAction: "open_resource",
      primaryActionLabel: copy.preview,
      nextStep: copy.previewBeforeBind,
      advancedWhere: copy.resourcesPreview,
    });
  }

  return emit({
    objectLabel: selectedTitle || selectedId,
    state: "ready",
    why: copy.indexedReadable,
    primaryAction: "open_resource",
    primaryActionLabel: copy.keepReading,
    nextStep: copy.readThenBindWhenLinked,
    advancedWhere: copy.resourcesCurrentItem,
  });
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
