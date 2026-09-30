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

/** Canonical gear body, shared by the Preferences category and the header gear. */
const GEAR_BODY =
  "M8.25 2.25h3.5l.5 2.13c.5.12 1 .37 1.38.75l2.12-.75 1.5 2.63-1.63 1.37c.13.5.13 1 .13 1.62s0 1.13-.13 1.63l1.63 1.37-1.5 2.63-2.13-.75c-.37.37-.87.62-1.37.75l-.5 2.12h-3.5l-.5-2.12c-.5-.13-1-.38-1.38-.75l-2.12.75-1.5-2.63 1.62-1.37c-.12-.5-.12-1-.12-1.63s0-1.12.12-1.62L4 5.88l1.5-2.63 2.13.75c.37-.38.87-.63 1.37-.75z";

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

export function SettingsPreferencesIcon({ active, ...props }: SettingsNavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      {/* Gear body */}
      <path d={GEAR_BODY} />
      {/* Gear hub: fills when active */}
      {active ? (
        <circle cx="10" cy="10" r="2.4" fill="currentColor" stroke="none" />
      ) : (
        <circle cx="10" cy="10" r="2.4" />
      )}
    </TrainerIconBase>
  );
}

/** Header/sidebar gear — the canonical gear, same geometry as Preferences. */
export function SettingsIcon({ active, ...props }: SettingsNavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      <path d={GEAR_BODY} />
      {active ? (
        <circle cx="10" cy="10" r="2.4" fill="currentColor" stroke="none" />
      ) : (
        <circle cx="10" cy="10" r="2.4" />
      )}
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
