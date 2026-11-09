import { Suspense, type ComponentProps, type ReactNode } from "react";

import { CoachSettingsView, ViewFallback } from "./appHelpers";
import type { ComposerLanguage } from "../lib/types";

type CoachSettingsViewProps = ComponentProps<typeof CoachSettingsView>;

export interface SettingsRouteProps {
  language: ComposerLanguage;
  fallbackLabel: string;
  settingsProps: CoachSettingsViewProps;
  contextualRail?: ReactNode;
}

/** Settings destination shell: one lazy editor plus its contextual rail. */
export function SettingsRoute({
  language,
  fallbackLabel,
  settingsProps,
  contextualRail,
}: SettingsRouteProps) {
  return (
    <section className="settings-view">
      <Suspense fallback={<ViewFallback label={fallbackLabel} language={language} />}>
        <CoachSettingsView {...settingsProps} />
      </Suspense>
      {contextualRail}
    </section>
  );
}
