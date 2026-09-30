/**
 * §五十六 Inline panel icons — UI-chrome glyphs redrawn on the canonical
 * TrainerIconBase grammar (20-box working canvas, 1.4 currentColor stroke,
 * round joins, one selective-fill accent) so panels match the §四十五/四十六
 * nav and settings language.
 *
 * Motifs carry over from the first-generation CoachIcons set so recognition
 * survives the migration:
 * - Reload: circular arrow with a corner arrowhead (was RefreshIcon)
 * - Done: single check stroke (was CheckIcon / CheckMarkIcon)
 * - AlertTriangle: warning triangle with an exclamation (was WarningIcon /
 *   DiagnosticsIcon)
 * - DataFolder: folder silhouette (was FolderIcon; shares the silhouette
 *   with SettingsWorkspaceIcon)
 * - SettingsShare: share-nodes triangle (was ShareIcon)
 *
 * Each icon accepts `active` to show its Selective Fill element. Import this
 * module directly; the ../icons barrel still owns the old-grammar names for
 * not-yet-migrated surfaces.
 */
import { TrainerIconBase, type TrainerIconProps } from "./TrainerIconBase";

type InlineIconProps = Omit<TrainerIconProps, "active"> & { active?: boolean };

/** Circular reload arrow; the corner arrowhead turns solid when active. */
export function ReloadIcon({ active, ...props }: InlineIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      <path d="M15 10a5 5 0 1 1-1.5-3.75" />
      {active ? (
        <path d="M11.3 3.6h3.8v3.9z" fill="currentColor" stroke="none" />
      ) : (
        <path d="M11.3 3.6h3.8v3.9" />
      )}
    </TrainerIconBase>
  );
}

/** Single check stroke; turns solid when active. */
export function DoneIcon({ active, ...props }: InlineIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      {active ? (
        <path d="m4.4 10.3 3.6 3.6 7.6-7.8" fill="currentColor" stroke="none" />
      ) : (
        <path d="m4.4 10.3 3.6 3.6 7.6-7.8" />
      )}
    </TrainerIconBase>
  );
}

/** Warning triangle; the body washes in when active (EvidenceIcon pattern). */
export function AlertTriangleIcon({ active, ...props }: InlineIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      <path d="M10 3.25 16.4 15H3.6z" />
      <path d="M10 7.4v3.5" />
      <circle cx="10" cy="13" r="1" fill="currentColor" stroke="none" />
      {active ? (
        <path d="M10 3.25 16.4 15H3.6z" fill="currentColor" stroke="none" opacity={0.18} />
      ) : null}
    </TrainerIconBase>
  );
}

/** Plain folder (managed-data directories); the label slot fills when active. */
export function DataFolderIcon({ active, ...props }: InlineIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      <path d="M2.8 6.3a1.2 1.2 0 0 1 1.2-1.2h3.6l1.7 1.7h5.9a1.2 1.2 0 0 1 1.2 1.2v6.3a1.2 1.2 0 0 1-1.2 1.2H4a1.2 1.2 0 0 1-1.2-1.2z" />
      {active ? (
        <rect x="5.9" y="10" width="8.2" height="1.8" rx="0.9" fill="currentColor" stroke="none" />
      ) : (
        <path d="M5.9 10.9h8.2" />
      )}
    </TrainerIconBase>
  );
}

/** Share-nodes triangle; the origin node fills when active. */
export function SettingsShareIcon({ active, ...props }: InlineIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      <path d="m6.7 8.9 6.7-2.9" />
      <path d="m6.7 11.1 6.7 2.9" />
      {active ? (
        <circle cx="4.9" cy="10" r="1.9" fill="currentColor" stroke="none" />
      ) : (
        <circle cx="4.9" cy="10" r="1.9" />
      )}
      <circle cx="15.3" cy="5" r="1.9" />
      <circle cx="15.3" cy="15" r="1.9" />
    </TrainerIconBase>
  );
}
