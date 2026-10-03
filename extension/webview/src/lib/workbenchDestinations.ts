import type { ActiveWorkbenchView } from "./types";

/** Navigation is a product map; routes remain the compatibility contract. */
export const PRIMARY_DESTINATIONS = ["coach", "plan", "resources"] as const;
export type PrimaryDestination = (typeof PRIMARY_DESTINATIONS)[number];

export const WORKBENCH_DESTINATIONS: Record<ActiveWorkbenchView, {
  primary: PrimaryDestination | null;
  template: "Conversation" | "LearningHome" | "Library" | "FocusedPractice" | "GrowthEvidence" | "SettingsIndex";
}> = {
  coach: { primary: "coach", template: "Conversation" },
  plan: { primary: "plan", template: "LearningHome" },
  resources: { primary: "resources", template: "Library" },
  training: { primary: "plan", template: "FocusedPractice" },
  progress: { primary: "plan", template: "GrowthEvidence" },
  settings: { primary: null, template: "SettingsIndex" },
};

export function primaryDestinationForRoute(route: ActiveWorkbenchView): PrimaryDestination | null {
  return WORKBENCH_DESTINATIONS[route].primary;
}

export function ownsCoachComposer(route: ActiveWorkbenchView): boolean {
  return route === "coach";
}
