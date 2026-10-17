import { dockSendPreferenceCopy, type DockSendPreference } from "../../lib/composerDock";

export interface DockSendPreferenceSwitchProps {
  language: string;
  value: DockSendPreference;
  onChange: (preference: DockSendPreference) => void;
}

/**
 * Visible send-preference switch (§3.7 red line 5, default "jump"): shown in
 * the dock strip on Learning/Resources. "Jump to reply" follows the streamed
 * answer into Coach (historical default); "Stay here" keeps the working
 * surface and relies on the returnToSurface bar once the answer lands.
 * Coach never renders it — a send from the thread always stays in it.
 */
export function DockSendPreferenceSwitch({
  language,
  value,
  onChange,
}: DockSendPreferenceSwitchProps) {
  const copy = dockSendPreferenceCopy(language);
  return (
    <div
      className="template-context"
      role="group"
      aria-label={copy.label}
      data-dock-send-preference="true"
    >
      <span>{copy.label}</span>
      <button
        type="button"
        className="template-back"
        aria-pressed={value === "jump"}
        data-dock-send-preference-option="jump"
        onClick={() => onChange("jump")}
      >
        {copy.jump}
      </button>
      <button
        type="button"
        className="template-back"
        aria-pressed={value === "stay"}
        data-dock-send-preference-option="stay"
        onClick={() => onChange("stay")}
      >
        {copy.stay}
      </button>
    </div>
  );
}
