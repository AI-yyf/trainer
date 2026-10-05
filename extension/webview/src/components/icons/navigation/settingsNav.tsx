/**
 * §四十六 Settings category icons — the Settings nav entries in the Trainer
 * visual language (Premium Soft Outline + Selective Fill, 20px optical canvas).
 *
 * Motifs carry over from the first-generation nav set so recognition survives
 * the migration; geometry is re-drawn on the TrainerIconBase grammar
 * (1.4 stroke on the 20-box, rounded joins, one selective-fill accent):
 * - Connection: two nodes joined by a guide arc (was NavConnectionIcon)
 * - Workspace: folder with a branch glyph (was NavWorkspaceIcon)
 * - Teaching: graduation cap with a tassel bead (was NavTeachingIcon)
 * - Skills: a lightning bolt that fills when active (was LightningIcon)
 * - Preferences: a gear whose hub fills when active (was GearIcon)
 * - Advanced: mixer sliders with a filled thumb accent (was NavAdvancedIcon)
 * - SettingsIcon: the header/sidebar gear — the same canonical gear as
 *   Preferences (was the CoachIcons SettingsIcon 16-box sketch)
 *
 * Each icon accepts `active` to show its Selective Fill element.
 */
import { TrainerIconBase, type TrainerIconProps } from "../TrainerIconBase";

type SettingsNavIconProps = Omit<TrainerIconProps, "active"> & { active?: boolean };

export function SettingsConnectionIcon({ active, ...props }: SettingsNavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      {/* Guide arc between the local node and the remote node */}
      <path d="M6.3 13.9c2.1-1.6 4.5-2 5.9-3.9 1.2-1.7 1.2-3.1 1.9-4" />
      {/* Local node: fills when active */}
      {active ? (
        <circle cx="4.6" cy="15.4" r="1.75" fill="currentColor" stroke="none" />
      ) : (
        <circle cx="4.6" cy="15.4" r="1.75" />
      )}
      <circle cx="15.4" cy="4.6" r="1.75" />
    </TrainerIconBase>
  );
}

export function SettingsWorkspaceIcon({ active, ...props }: SettingsNavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      {/* Folder silhouette */}
      <path d="M3 6.8a1.2 1.2 0 0 1 1.2-1.2h3.6l1.7 1.7h4.3a1.2 1.2 0 0 1 1.2 1.2v5.8a1.2 1.2 0 0 1-1.2 1.2H4.2a1.2 1.2 0 0 1-1.2-1.2z" />
      {/* Branch glyph: stem plus two descendant legs */}
      <path d="M10 9.9v2.6" />
      <path d="M10 12.5H8.2v1.9" />
      <path d="M10 12.5h1.8v1.9" />
      {/* Root node: fills when active */}
      {active ? (
        <circle cx="10" cy="8.7" r="1.15" fill="currentColor" stroke="none" />
      ) : (
        <circle cx="10" cy="8.7" r="1.15" />
      )}
    </TrainerIconBase>
  );
}

export function SettingsTeachingIcon({ active, ...props }: SettingsNavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      {/* Mortarboard */}
      <path d="M10 3.8 17.8 7.5 10 11.2 2.2 7.5z" />
      {/* Cap band */}
      <path d="M6.1 9.4v2.9c0 1.1 1.75 2.1 3.9 2.1s3.9-1 3.9-2.1V9.4" />
      {/* Tassel */}
      <path d="M17.8 7.5v3.6" />
      {/* Tassel bead: fills when active */}
      {active ? (
        <circle cx="17.8" cy="12.4" r="1.05" fill="currentColor" stroke="none" />
      ) : (
        <circle cx="17.8" cy="12.4" r="1.05" />
      )}
    </TrainerIconBase>
  );
}

export function SettingsSkillsIcon({ active, ...props }: SettingsNavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      {/* Lightning bolt: the single accent element fills when active */}
      {active ? (
        <path d="M11.1 3.5 6 10h3.5l-.6 6.5L14 10h-3.5z" fill="currentColor" stroke="none" />
      ) : (
        <path d="M11.1 3.5 6 10h3.5l-.6 6.5L14 10h-3.5z" />
      )}
    </TrainerIconBase>
  );
}

/**
 * Canonical cog (20-box): a single square-tooth gear ring + center hole.
 * r2-g0-2: radial hub-and-spoke sketches kept reading as a sun at 16px — a
 * real toothed silhouette (outer tip radius 9.1, root 6.9, eight teeth) reads
 * as a gear at header size. currentColor stroke and the active fill semantic
 * (the center hole fills) are unchanged.
 */
function CogGlyph({ active }: { active?: boolean }) {
  return (
    <>
      <path d="M8.34 1.05 L11.66 1.05 L11.55 3.28 L13.66 4.15 L15.15 2.5 L17.5 4.85 L15.85 6.34 L16.72 8.45 L18.95 8.34 L18.95 11.66 L16.72 11.55 L15.85 13.66 L17.5 15.15 L15.15 17.5 L13.66 15.85 L11.55 16.72 L11.66 18.95 L8.34 18.95 L8.45 16.72 L6.34 15.85 L4.85 17.5 L2.5 15.15 L4.15 13.66 L3.28 11.55 L1.05 11.66 L1.05 8.34 L3.28 8.45 L4.15 6.34 L2.5 4.85 L4.85 2.5 L6.34 4.15 L8.45 3.28 Z" />
      {active ? (
        <circle cx="10" cy="10" r="2" fill="currentColor" stroke="none" />
      ) : (
        <circle cx="10" cy="10" r="2" />
      )}
    </>
  );
}

export function SettingsPreferencesIcon({ active, ...props }: SettingsNavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      <CogGlyph active={active} />
    </TrainerIconBase>
  );
}

/** Header/sidebar gear — the canonical cog, same geometry as Preferences. */
export function SettingsIcon({ active, ...props }: SettingsNavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      <CogGlyph active={active} />
    </TrainerIconBase>
  );
}

export function SettingsAdvancedIcon({ active, ...props }: SettingsNavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      {/* Mixer tracks */}
      <path d="M5.5 3.5v13" />
      <path d="M10 3.5v13" />
      <path d="M14.5 3.5v13" />
      <path d="M4 12.5h3" />
      <path d="M13 14.25h3" />
      {/* Middle thumb: fills when active */}
      {active ? (
        <rect x="8.4" y="5.85" width="3.2" height="1.8" rx="0.9" fill="currentColor" stroke="none" />
      ) : (
        <path d="M8.5 6.75h3" />
      )}
    </TrainerIconBase>
  );
}
