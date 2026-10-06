/**
 * §四十五 §四十八 Core navigation icons — redesigned per the Trainer visual
 * language (§四十六 Premium Soft Outline + Selective Fill).
 *
 * Design notes per icon:
 * - Resources: layered knowledge pages (not a bar chart)
 * - Training: focused practice frame with a center diamond (not a checklist)
 *
 * Each icon accepts `active` to show its Selective Fill element.
 */
import { TrainerIconBase, type TrainerIconProps } from "../TrainerIconBase";

type NavIconProps = Omit<TrainerIconProps, "active"> & { active?: boolean };

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
