/**
 * TelemetryOptInPanel — the opt-in anonymous telemetry consent surface
 * (P2 #18), rendered inside the Settings sheet next to the memory-sharing
 * disclosure. Consent is opt-in by default (display fails closed to "off"),
 * the sidecar is the single source of truth, and the panel reuses the
 * existing settings disclosure classes — no new CSS.
 */

import { useEffect } from "react";
import { telemetrySettingsCopy } from "./telemetrySettingsCopy";

interface TelemetryOptInPanelProps {
  language: string;
  connectionState: "starting" | "connected" | "offline";
  telemetryOptIn: boolean | undefined;
  onTelemetryOptInChange?: (enabled: boolean) => void;
  onTelemetryStatusRefresh?: () => void;
}

export function TelemetryOptInPanel({
  language,
  connectionState,
  telemetryOptIn,
  onTelemetryOptInChange,
  onTelemetryStatusRefresh,
}: TelemetryOptInPanelProps) {
  const copy = telemetrySettingsCopy(language);
  // Lazy status read: only when the sidecar is already connected and the
  // consent fact has not been answered yet (never wakes a dark sidecar).
  useEffect(() => {
    if (connectionState === "connected" && telemetryOptIn === undefined) {
      onTelemetryStatusRefresh?.();
    }
  }, [connectionState, telemetryOptIn, onTelemetryStatusRefresh]);
  const optIn = telemetryOptIn === true;
  const stateLabel =
    telemetryOptIn === true ? copy.stateOn : telemetryOptIn === undefined ? copy.stateUnknown : copy.stateOff;
  return (
    <details className="settings-sheet__minor-panel settings-telemetry-opt-in" data-telemetry-opt-in-panel="">
      <summary className="settings-memory-sharing__summary">
        <span className="eyebrow">{copy.title}</span>
        <span className="settings-sheet__remembered-preview">{stateLabel}</span>
      </summary>
      <div className="settings-sheet__minor-body settings-memory-sharing__body">
        <p className="settings-sheet__note settings-sheet__note--compact">{copy.detail}</p>
        {onTelemetryOptInChange ? (
          <button
            type="button"
            className={`settings-memory-sharing__trust ${optIn ? "is-on" : "is-off"}`}
            data-telemetry-opt-in-row=""
            aria-pressed={optIn}
            onClick={() => onTelemetryOptInChange(!optIn)}
          >
            <span>
              <strong>{copy.rowLabel}</strong>
              <small>{copy.detail}</small>
            </span>
            <em>{stateLabel}</em>
          </button>
        ) : null}
      </div>
    </details>
  );
}
