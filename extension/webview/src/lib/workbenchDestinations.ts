import type { ActiveWorkbenchView,LearningSection } from "./types";

/**
 * Navigation is a product map; routes remain the compatibility contract.
 * Learning is no longer a destination: plan/training/progress are legacy
 * aliases that redirect into Chat with the learning drawer opened on the
 * matching section.
 */
export const PRIMARY_DESTINATIONS = ["coach", "resources"] as const;
export type PrimaryDestination = (typeof PRIMARY_DESTINATIONS)[number];

/**
 * Only the surfaces that still exist. The legacy learning routes resolve to
 * Conversation, so no route can select a Learning page any more.
 */
export type WorkbenchSurfaceTemplate = "Conversation" | "Library" | "SettingsIndex";

export const WORKBENCH_DESTINATIONS: Record<ActiveWorkbenchView, {
  primary: PrimaryDestination | null;
  template: WorkbenchSurfaceTemplate;
}> = {
  coach: { primary: "coach", template: "Conversation" },
  plan: { primary: "coach", template: "Conversation" },
  resources: { primary: "resources", template: "Library" },
  training: { primary: "coach", template: "Conversation" },
  progress: { primary: "coach", template: "Conversation" },
  settings: { primary: null, template: "SettingsIndex" },
};

export function primaryDestinationForRoute(route: ActiveWorkbenchView): PrimaryDestination | null {
  return WORKBENCH_DESTINATIONS[route].primary;
}

/** Legacy route → learning drawer section. New routes return null. */
export function learningSectionForRoute(route: ActiveWorkbenchView | string | null | undefined): LearningSection | null {
  if (route === "plan") return "goal";
  if (route === "training" || route === "practice") return "practice";
  if (route === "progress") return "progress";
  return null;
}
