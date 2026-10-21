export * from "./CoachIcons";

// §五十六 wave 2: Progress + Settings shell glyphs redrawn on the canonical
// TrainerIconBase grammar. The old-grammar CoachIcons versions were dead
// after the migration, so these are the only exports under these names.
export { HistoryIcon, ResourcesNavIcon } from "./navigation/coreNav";
export { CoachNavIcon, LearningNavIcon } from "./navigation/primaryNav";
export { SettingsIcon } from "./navigation/settingsNav";
