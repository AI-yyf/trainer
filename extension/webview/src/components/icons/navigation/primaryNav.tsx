/**
 * The three primary destinations share one 20-box grammar so the top nav can
 * carry an optical 18px glyph without mixing the 16-box coach chrome.
 */
import { TrainerIconBase, type TrainerIconProps } from "../TrainerIconBase";

type PrimaryNavIconProps = Omit<TrainerIconProps, "active"> & { active?: boolean };

export function CoachNavIcon({ active, ...props }: PrimaryNavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      <path d="M4 4.2h12A1.8 1.8 0 0 1 17.8 6v5.8a1.8 1.8 0 0 1-1.8 1.8H9.2l-3.9 2.8v-2.8H4a1.8 1.8 0 0 1-1.8-1.8V6A1.8 1.8 0 0 1 4 4.2z" />
      {active ? (
        <circle cx="10" cy="8.9" r="1.5" fill="currentColor" stroke="none" />
      ) : (
        <path d="M7.2 8.9h5.6" />
      )}
    </TrainerIconBase>
  );
}

export function LearningNavIcon({ active, ...props }: PrimaryNavIconProps) {
  return (
    <TrainerIconBase {...props} active={active}>
      <path d="M10 5.2C8.5 4 6.6 3.5 4 3.5v10.2c2.6 0 4.5.5 6 1.7 1.5-1.2 3.4-1.7 6-1.7V3.5c-2.6 0-4.5.5-6 1.7z" />
      <path d="M10 5.2v10.2" />
      {active ? (
        <path d="M10 5.2c-1.5-1.2-3.4-1.7-6-1.7v10.2c2.6 0 4.5.5 6 1.7z" fill="currentColor" stroke="none" opacity={0.18} />
      ) : null}
    </TrainerIconBase>
  );
}
