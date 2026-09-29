/**
 * §四十五 Trainer brand icon — expresses Guide + Practice + Feedback,
 * not "AI document tool". A compass-star inside an open frame.
 */
import { TrainerIconBase, type TrainerIconProps } from "../TrainerIconBase";

export function TrainerMarkIcon({ active, ...props }: TrainerIconProps & { active?: boolean }) {
  return (
    <TrainerIconBase {...props} active={active}>
      {/* Open frame: not a closed document, suggests forward movement */}
      <path d="M5 2.5h7a2 2 0 0 1 2 2v8" />
      <path d="M5 2.5a2 2 0 0 0-2 2v11l3-2.5h6a2 2 0 0 0 2-2" />
      {/* Compass star: guide + practice + feedback */}
      <path d="M10 6.5 11 9.5 14 10.5 11 11.5 10 14.5 9 11.5 6 10.5 9 9.5z" />
      {active ? <circle cx="10" cy="10.5" r="1" fill="currentColor" stroke="none" /> : null}
    </TrainerIconBase>
  );
}

/** §五十: model icon — stacked layers (not a brain). */
export function ModelLayersIcon({ active, ...props }: TrainerIconProps & { active?: boolean }) {
  return (
    <TrainerIconBase {...props} active={active}>
      <path d="M10 3 3.5 6.5 10 10l6.5-3.5z" />
      <path d="M3.5 10 10 13.5 16.5 10" opacity={0.6} />
      <path d="M3.5 13.5 10 17l6.5-3.5" opacity={0.35} />
      {active ? <circle cx="10" cy="6.8" r="1" fill="currentColor" stroke="none" /> : null}
    </TrainerIconBase>
  );
}

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
