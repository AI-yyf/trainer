/**
 * §四十五 §四十八 Core navigation icons — redesigned per the Trainer visual
 * language (§四十六 Premium Soft Outline + Selective Fill).
 *
 * Design notes per icon:
 * - Coach: conversation arc + a guide-point dot (not a speech bubble + sparkle)
 * - Learning: progressive learning path (3 ascending nodes, not a flag)
 * - Resources: layered knowledge pages (not a bar chart)
 * - Training: focused practice frame with a center diamond (not a checklist)
 * - Progress: trend line rising into a corner arrow with a position node
 *   (was the CoachIcons NavProgressIcon step-dash sketch)
 *
 * Each icon accepts `active` to show its Selective Fill element.
 */
import { TrainerIconBase, type TrainerIconProps } from "../TrainerIconBase";

type NavIconProps = Omit<TrainerIconProps, "active"> & { active?: boolean };

export function CoachNavIcon({ active, ...props }: NavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      {/* Conversation arc: open curve suggesting dialogue */}
      <path d="M4 14.5V7a5 5 0 0 1 10 0v.5a4.5 4.5 0 0 1-4.5 4.5H8.2" />
      {/* Guide point: a small dot that fills when active */}
      <circle cx="13.5" cy="15" r="1.4" />
      {active ? <circle cx="13.5" cy="15" r="1.4" fill="currentColor" stroke="none" /> : null}
    </TrainerIconBase>
  );
}

export function LearningNavIcon({ active, ...props }: NavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      {/* Progressive learning path: three ascending nodes connected */}
      <circle cx="5" cy="14.5" r="1.6" />
      <path d="M6.2 13.2 9 10" />
      <circle cx="10" cy="9" r="1.6" />
      <path d="M11.2 7.7 13.5 5.5" />
      {active ? <circle cx="14.5" cy="4.5" r="1.6" fill="currentColor" stroke="none" /> : <circle cx="14.5" cy="4.5" r="1.6" />}
    </TrainerIconBase>
  );
}

export function ResourcesNavIcon({ active, ...props }: NavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      {/* Layered knowledge pages: offset rectangles suggesting stacked layers */}
      <path d="M6 3.5h8v9H6z" />
      <path d="M4 5.5v9h8" opacity={0.55} />
      {active ? <path d="M8.5 6h3v3h-3z" fill="currentColor" stroke="none" /> : <path d="M8.5 6h3v3h-3z" />}
    </TrainerIconBase>
  );
}

export function TrainingNavIcon({ active, ...props }: NavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      {/* Focused practice frame with center diamond */}
      <path d="M7 3.5H4.5a1 1 0 0 0-1 1V7" />
      <path d="M13 3.5h2.5a1 1 0 0 1 1 1V7" />
      <path d="M7 16.5H4.5a1 1 0 0 1-1-1V13" />
      <path d="M13 16.5h2.5a1 1 0 0 0 1-1V13" />
      {/* Center diamond: fills when active */}
      {active ? (
        <path d="M10 7.5 12.5 10 10 12.5 7.5 10z" fill="currentColor" stroke="none" />
      ) : (
        <path d="M10 7.5 12.5 10 10 12.5 7.5 10z" />
      )}
    </TrainerIconBase>
  );
}

export function NavProgressIcon({ active, ...props }: NavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      {/* Upward trend line rising into a corner arrow */}
      <path d="M3 15.5 7.6 10.9l2.9 2.7 6.5-7" />
      <path d="M13 6.6h4v4" />
      {/* Current-position node on the trend: fills when active */}
      {active ? (
        <circle cx="10.5" cy="13.6" r="1.5" fill="currentColor" stroke="none" />
      ) : (
        <circle cx="10.5" cy="13.6" r="1.5" />
      )}
    </TrainerIconBase>
  );
}

/** Rewind-clock history glyph (20-box): counter-clockwise arc out of a
  corner bracket, clock hands at the center. Replaces the old plain-clock
  sketch from the previous icon grammar. */
export function HistoryIcon({ active, ...props }: NavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      {/* Rewind arc sweeping out of the corner bracket */}
      <path d="M2.6 10a7.4 7.4 0 1 0 7.4-7.4 8 8 0 0 0-5.53 2.25L2.6 6.6" />
      {/* Arrow bracket the arc rewinds into */}
      <path d="M2.6 2.7v3.9h3.9" />
      {/* Clock hands */}
      <path d="M10 5.9v4.1l3.2 1.6" />
    </TrainerIconBase>
  );
}
