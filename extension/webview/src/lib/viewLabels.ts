/**
 * View labels for the sidebar navigation, extracted from App.tsx (§四十八).
 * Pure data + helpers — no React dependencies.
 */

import type { ActiveWorkbenchView, ComposerLanguage } from "./types";

export type ViewLabelKey =
  | "coach"
  | "plan"
  | "resources"
  | "training"
  | "progress"
  | "settings";

export const viewLabels: Record<
  ComposerLanguage,
  Record<ViewLabelKey, string>
> = {
  "zh-CN": { coach: "\u5bf9\u8bdd", plan: "\u5b66\u4e60", resources: "\u8d44\u6599", training: "\u8bad\u7ec3", progress: "\u6210\u957f", settings: "\u8bbe\u7f6e" },
  "en-US": { coach: "Chat", plan: "Learning", resources: "Resources", training: "Training", progress: "Progress", settings: "Settings" },
  "es-ES": { coach: "Chat", plan: "Plan", resources: "Recursos", training: "Entrenamiento", progress: "Progreso", settings: "Ajustes" },
  "fr-FR": { coach: "Chat", plan: "Plan", resources: "Ressources", training: "Entra\u00eenement", progress: "Progr\u00e8s", settings: "Param\u00e8tres" },
  "de-DE": { coach: "Chat", plan: "Plan", resources: "Materialien", training: "Training", progress: "Fortschritt", settings: "Einstellungen" },
  "ja-JP": { coach: "\u5bfe\u8a71", plan: "\u8a08\u753b", resources: "\u8cc7\u6599", training: "\u8a13\u7df4", progress: "\u6210\u9577", settings: "\u8a2d\u5b9a" },
  "ko-KR": { coach: "\ub300\ud654", plan: "\uacc4\ud68d", resources: "\uc790\ub8cc", training: "\ud6c8\ub828", progress: "\uc131\uc7a5", settings: "\uc124\uc815" },
  "pt-BR": { coach: "Chat", plan: "Plano", resources: "Recursos", training: "Treinamento", progress: "Progresso", settings: "Configura\u00e7\u00f5es" },
};

export function resourcesViewLabel(language: ComposerLanguage): string {
  return viewLabels[language].resources;
}

export function coachViewLabel(language: ComposerLanguage): string {
  return viewLabels[language].coach;
}

export function planViewLabel(language: ComposerLanguage): string {
  return viewLabels[language].plan;
}

export function trainingViewLabel(language: ComposerLanguage): string {
  return viewLabels[language].training;
}

export function settingsViewLabel(language: ComposerLanguage): string {
  return viewLabels[language].settings;
}

export function progressViewLabel(language: ComposerLanguage): string {
  return viewLabels[language].progress;
}

export function compactSidebarViewLabel(
  _view: ActiveWorkbenchView,
  _language: ComposerLanguage,
  fullLabel: string,
): string {
  return fullLabel;
}
