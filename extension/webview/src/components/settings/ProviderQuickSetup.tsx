import { useMemo, useState } from "react";
import { parseProviderConnectionPaste } from "../../../../../shared/src/providerGateway";
import type { ComposerLanguage } from "../../../../../shared/src/types";
import { CheckMarkIcon } from "../icons";
import { DoneIcon } from "../icons/inline";
import { QUICK_SETUP_COPY, type QuickSetupLanguage } from "../../lib/i18n/segments/settingsInlineText";

interface ProviderQuickSetupDraft {
  name: string;
  baseUrl: string;
  model: string;
  apiKey: string;
}

interface ProviderQuickSetupProps {
  language: ComposerLanguage;
  draft: ProviderQuickSetupDraft;
  savedBaseUrl: string;
  savedModel: string;
  connected: boolean;
  hasStoredApiKey: boolean;
  trusted: boolean;
  onTrustWindow?: () => void;
  busy: boolean;
  onDraftChange: (patch: Partial<ProviderQuickSetupDraft & { apiKey: string }>) => void;
  onSave: () => void;
}

function copy(language: ComposerLanguage, key: string): string {
  const table = QUICK_SETUP_COPY[(language as QuickSetupLanguage) ?? "en-US"] ?? QUICK_SETUP_COPY["en-US"];
  return table[key] ?? QUICK_SETUP_COPY["en-US"][key] ?? key;
}

export function ProviderQuickSetup({
  language,
  draft,
  savedBaseUrl,
  savedModel,
  connected,
  hasStoredApiKey,
  trusted = false,
  busy,
  onTrustWindow,
  onDraftChange,
  onSave,
}: ProviderQuickSetupProps) {
  const [open, setOpen] = useState(false);
  const [pasteHint, setPasteHint] = useState<string | null>(null);

  const baseUrlReady = draft.baseUrl.trim().length > 0;
  const keyReady = draft.apiKey.trim().length > 0 || hasStoredApiKey;
  const step1Done = baseUrlReady;
  const step2Done = keyReady;
  const canSave = baseUrlReady && keyReady;

  const connectedSummary = useMemo(
    () => Boolean(connected && savedBaseUrl),
    [connected, savedBaseUrl],
  );
  const collapsed = connectedSummary && !open && !draft.baseUrl.trim() && !draft.apiKey.trim();

  const handlePasteOrType = (value: string) => {
    const parsed = parseProviderConnectionPaste(value);
    if (parsed) {
      onDraftChange({ baseUrl: parsed.baseUrl, apiKey: parsed.apiKey });
      setPasteHint(copy(language, "parsedHint"));
      return;
    }
    setPasteHint(null);
    onDraftChange({ baseUrl: value });
  };

  if (collapsed) {
    return (
      <div className="settings-quick-setup settings-quick-setup--connected">
        <span
          className="settings-quick-setup__connected-dot"
          aria-hidden="true"
          style={{ color: "var(--pass, var(--trainer-fallback-success))" }}
        >
          <DoneIcon size={14} />
        </span>
        <span className="settings-quick-setup__connected-line">
          {copy(language, "connectedLine")}
        </span>
        <button
          type="button"
          className="toolbar-button"
          onClick={() => setOpen(true)}
        >
          {copy(language, "change")}
        </button>
      </div>
    );
  }

  return (
    <form className="settings-quick-setup" onSubmit={(event) => {
      event.preventDefault();
      if (canSave && !busy) onSave();
    }}>
      <div className="settings-quick-setup__head">
        <strong>{copy(language, "title")}</strong>
        {connectedSummary ? (
          <button
            type="button"
            className="toolbar-button"
            onClick={() => setOpen(false)}
          >
            {copy(language, "collapse")}
          </button>
        ) : null}
      </div>

      <label className="settings-field">
        <span>
          {copy(language, "pasteLabel")}
          {step1Done ? (
            <span className="settings-quick-setup__done" aria-hidden="true">
              <DoneIcon size={12} />
            </span>
          ) : (
            ""
          )}
        </span>
        <input
          type="text"
          value={draft.baseUrl}
          placeholder={copy(language, "pastePlaceholder")}
          onChange={(event) => handlePasteOrType(event.target.value)}
        />
        {pasteHint ? (
          <p className="settings-sheet__note settings-sheet__note--compact">{pasteHint}</p>
        ) : null}
      </label>

      <label className="settings-field">
        <span>
          {copy(language, "keyLabel")}
          {step2Done ? (
            <span className="settings-quick-setup__done" aria-hidden="true">
              <DoneIcon size={12} />
            </span>
          ) : (
            ""
          )}
        </span>
        <input
          type="password"
          value={draft.apiKey}
          placeholder={hasStoredApiKey && !draft.apiKey ? copy(language, "keyStored") : copy(language, "keyPlaceholder")}
          onChange={(event) => onDraftChange({ apiKey: event.target.value })}
        />
        <p className="settings-sheet__note settings-sheet__note--compact">
          {copy(language, "modelHint")}
        </p>
      </label>

      {/* r1-g2-3: the trust step is a real control, not gray prose — an
          unconfirmed marker + button before trusting, a confirmed state after. */}
      {onTrustWindow ? (
        trusted ? (
          <p className="settings-quick-setup__trust is-trusted" data-settings-trust-action="true">
            <span className="settings-trust-action__state" data-trust-state="trusted" aria-hidden="true" />
            <span>{copy(language, "trustDone")}</span>
          </p>
        ) : (
          <button
            type="button"
            className="button button--ghost button--compact settings-quick-setup__trust settings-trust-action"
            data-settings-trust-action="true"
            onClick={() => onTrustWindow()}
          >
            <span className="settings-trust-action__state" data-trust-state="untrusted" aria-hidden="true" />
            <span>{copy(language, "trustTitle")}</span>
          </button>
        )
      ) : null}

      <button
        type="submit"
        className="action-button action-button--accent"
        disabled={!canSave || busy}
      >
        {busy ? (
          <>
            <span aria-hidden="true" className="trainer-spinner trainer-spinner--sm" />
            {copy(language, "saving")}
          </>
        ) : (
          <>
            <CheckMarkIcon size={14} />
            {copy(language, "saveLabel")}
          </>
        )}
      </button>

    </form>
  );
}
