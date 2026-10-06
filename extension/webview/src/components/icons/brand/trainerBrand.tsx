/**
 * §四十五 Brand-adjacent status icons.
 *
 * The TSX brand-mark mirror (TrainerMarkIcon) was removed as dead code; the
 * canonical mark still lives in extension/media/trainer-icon.svg (Activity
 * Bar), extension/media/trainer.svg and media/trainer-icon.png — change all
 * of them together if the mark is ever re-introduced as a component.
 */
import { TrainerIconBase, type TrainerIconProps } from "../TrainerIconBase";

/** §四十五: Evidence icon — a shield-check suggesting verified truth. */
export function EvidenceIcon({ active, ...props }: TrainerIconProps & { active?: boolean }) {
  return (
    <TrainerIconBase {...props} active={active}>
      <path d="M10 2.5 4 5v5c0 3.5 2.5 6 6 7.5 3.5-1.5 6-4 6-7.5V5z" />
      <path d="m7.5 10 2 2 3.5-3.5" />
      {active ? <path d="M10 2.5 4 5v2l6-2 6 2V5z" fill="currentColor" stroke="none" opacity={0.2} /> : null}
    </TrainerIconBase>
  );
}

/** §四十五: Remote icon — two nodes connected by an arc (local ↔ remote). */
export function RemoteIcon({ active, ...props }: TrainerIconProps & { active?: boolean }) {
  return (
    <TrainerIconBase {...props} active={active}>
      <rect x="2" y="12" width="6" height="5" rx="1" />
      <rect x="12" y="3" width="6" height="5" rx="1" />
      <path d="M5 12V8a3 3 0 0 1 3-3h4" />
      {active ? <circle cx="10" cy="5" r="1.2" fill="currentColor" stroke="none" /> : null}
    </TrainerIconBase>
  );
}
