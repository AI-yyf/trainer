export type CoachOrientationObject =
  | "provider"
  | "workspace"
  | "conversation"
  | "plan"
  | "training";

export type CoachOrientationState =
  | "needs_setup"
  | "waiting"
  | "working"
  | "blocked"
  | "ready"
  | "interrupted";

export type CoachOrientationAction =
  | "open_settings"
  | "open_plan"
  | "open_training"
  | "compose"
  | "wait"
  | "retry"
  | "resume_checkpoint";

export interface CoachOrientationRecord {
  objectKind: CoachOrientationObject;
  objectLabel: string;
  state: CoachOrientationState;
  why: string;
  primaryAction: CoachOrientationAction;
  primaryActionLabel: string;
  nextStep: string;
  advancedWhere: string;
  source: "snapshot";
  revision: number;
}

const OBJECTS = new Set<CoachOrientationObject>([
  "provider",
  "workspace",
  "conversation",
  "plan",
  "training",
]);

const STATES = new Set<CoachOrientationState>([
  "needs_setup",
  "waiting",
  "working",
  "blocked",
  "ready",
  "interrupted",
]);

const ACTIONS = new Set<CoachOrientationAction>([
  "open_settings",
  "open_plan",
  "open_training",
  "compose",
  "wait",
  "retry",
  "resume_checkpoint",
]);

function text(value: string | undefined): string {
  return value?.trim() ?? "";
}

export function normalizeCoachOrientationRecord(
  value: unknown,
): CoachOrientationRecord | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  const objectKind = text(typeof record.objectKind === "string" ? record.objectKind : typeof record.object_kind === "string" ? record.object_kind : "");
  const state = text(typeof record.state === "string" ? record.state : "");
  const primaryAction = text(
    typeof record.primaryAction === "string"
      ? record.primaryAction
      : typeof record.primary_action === "string"
        ? record.primary_action
        : "",
  );
  if (
    !OBJECTS.has(objectKind as CoachOrientationObject) ||
    !STATES.has(state as CoachOrientationState) ||
    !ACTIONS.has(primaryAction as CoachOrientationAction)
  ) {
    return undefined;
  }
  const objectLabel = text(
    typeof record.objectLabel === "string"
      ? record.objectLabel
      : typeof record.object_label === "string"
        ? record.object_label
        : "",
  );
  const why = text(typeof record.why === "string" ? record.why : "");
  const nextStep = text(
    typeof record.nextStep === "string"
      ? record.nextStep
      : typeof record.next_step === "string"
        ? record.next_step
        : "",
  );
  if (!objectLabel || !why || !nextStep) {
    return undefined;
  }
  const revision =
    typeof record.revision === "number" && Number.isFinite(record.revision) ? record.revision : 1;
  return {
    objectKind: objectKind as CoachOrientationObject,
    objectLabel,
    state: state as CoachOrientationState,
    why,
    primaryAction: primaryAction as CoachOrientationAction,
    primaryActionLabel: text(
      typeof record.primaryActionLabel === "string"
        ? record.primaryActionLabel
        : typeof record.primary_action_label === "string"
          ? record.primary_action_label
          : "",
    ),
    nextStep,
    advancedWhere: text(
      typeof record.advancedWhere === "string"
        ? record.advancedWhere
        : typeof record.advanced_where === "string"
          ? record.advanced_where
          : "",
    ),
    source: "snapshot",
    revision,
  };
}

export function coachOrientationTone(
  state: CoachOrientationState,
): "blocker" | "activity" | "context" {
  if (state === "blocked" || state === "needs_setup" || state === "interrupted") {
    return "blocker";
  }
  if (state === "working" || state === "waiting") {
    return "activity";
  }
  return "context";
}
