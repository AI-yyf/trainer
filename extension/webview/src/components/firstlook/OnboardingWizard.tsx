import { useMemo, useState } from "react";
import { parseProviderConnectionPaste } from "../../../../../shared/src/providerGateway";
import type { OnboardingStep } from "../../../../../shared/src/onboarding";
import { useTranslation } from "../../lib/i18n/useTranslation";
import type { CopyKey } from "../../lib/i18n/copy";

/**
 * Unified cold-start wizard: workspace root → trust window → connect model.
 * One progress rail, one visible action per step; steps flip to "done" as the
 * host patches bootstrap state in, so finishing a step auto-advances.
 */

export interface OnboardingWizardProps {
  steps: OnboardingStep[];
  activeStepId?: OnboardingWizardStepId;
  complete: boolean;
  busy: boolean;
  trialBusy: boolean;
  draftBaseUrl: string;
  draftApiKey: string;
  hasStoredApiKey: boolean;
  onDraftChange: (patch: { baseUrl?: string; apiKey?: string }) => void;
  onChooseWorkspaceRoot?: () => void;
  onTrustWindow?: () => void;
  onSaveConnection: () => void;
  onStartTrial?: () => void;
  onOpenSettings?: () => void;
}

export type OnboardingWizardStepId = OnboardingStep["id"];

const STEP_LABEL_KEY: Record<OnboardingWizardStepId, CopyKey> = {
  workspace_root: "onboardingStepWorkspaceRoot",
  trust_window: "onboardingStepTrust",
  connect_model: "onboardingStepConnectModel",
};

export function OnboardingWizard({
  steps,
  activeStepId,
  complete,
  busy,
  trialBusy,
  draftBaseUrl,
  draftApiKey,
  hasStoredApiKey,
  onDraftChange,
  onChooseWorkspaceRoot,
  onTrustWindow,
  onSaveConnection,
  onStartTrial,
  onOpenSettings,
}: OnboardingWizardProps) {
  const { t } = useTranslation();
  const [pasteHint, setPasteHint] = useState<string | null>(null);

  const trustDone = useMemo(
    () => steps.find((step) => step.id === "trust_window")?.status === "done",
    [steps],
  );
  const connectionReady = Boolean(draftBaseUrl.trim()) && (Boolean(draftApiKey.trim()) || hasStoredApiKey);

  if (complete) {
    return null;
  }

  const handlePaste = (value: string) => {
    const parsed = parseProviderConnectionPaste(value);
    if (parsed) {
      onDraftChange({ baseUrl: parsed.baseUrl, apiKey: parsed.apiKey });
      setPasteHint(t("onboardingModelParsed"));
      return;
    }
    setPasteHint(null);
    onDraftChange({ baseUrl: value });
  };

  return (
    <div className="onboarding-wizard" role="group" aria-label={t("onboardingTitle")}>
      <p className="onboarding-wizard__title">{t("onboardingTitle")}</p>
      <ol className="onboarding-wizard__steps">
        {steps.map((step, index) => (
          <li
            key={step.id}
            className={`onboarding-wizard__step onboarding-wizard__step--${step.status}`}
            aria-current={step.status === "active" ? "step" : undefined}
          >
            <span className="onboarding-wizard__marker" aria-hidden>
              {step.status === "done" ? "✓" : String(index + 1)}
            </span>
            <span className="onboarding-wizard__step-label">{t(STEP_LABEL_KEY[step.id])}</span>
          </li>
        ))}
      </ol>

      {activeStepId === "workspace_root" ? (
        <div className="onboarding-wizard__panel">
          <p className="onboarding-wizard__detail">{t("onboardingRootDetail")}</p>
          <button
            type="button"
            className="button button--accent"
            disabled={busy}
            onClick={() => onChooseWorkspaceRoot?.()}
          >
            {t("onboardingRootAction")}
          </button>
          {!trustDone && onTrustWindow ? (
            <div className="onboarding-wizard__inline-trust">
              <p className="onboarding-wizard__detail">{t("onboardingTrustInlineHint")}</p>
              <button type="button" className="button button--ghost" onClick={() => onTrustWindow()}>
                {t("onboardingTrustAction")}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {activeStepId === "trust_window" ? (
        <div className="onboarding-wizard__panel">
          <p className="onboarding-wizard__detail">{t("onboardingTrustDetail")}</p>
          {onTrustWindow ? (
            <button type="button" className="button button--accent" onClick={() => onTrustWindow()}>
              {t("onboardingTrustAction")}
            </button>
          ) : null}
        </div>
      ) : null}

      {activeStepId === "connect_model" ? (
        <div className="onboarding-wizard__panel">
          <p className="onboarding-wizard__detail">{t("onboardingModelDetail")}</p>
          <label className="onboarding-wizard__field">
            <span>{t("onboardingModelPasteLabel")}</span>
            <input
              type="text"
              value={draftBaseUrl}
              placeholder={t("onboardingModelPastePlaceholder")}
              onChange={(event) => handlePaste(event.target.value)}
            />
          </label>
          {pasteHint ? <p className="onboarding-wizard__hint">{pasteHint}</p> : null}
          <label className="onboarding-wizard__field">
            <span>{t("onboardingModelKeyLabel")}</span>
            <input
              type="password"
              value={draftApiKey}
              placeholder={hasStoredApiKey && !draftApiKey ? t("onboardingModelKeyStored") : t("onboardingModelKeyPlaceholder")}
              onChange={(event) => onDraftChange({ apiKey: event.target.value })}
            />
          </label>
          <button
            type="button"
            className="button button--accent"
            disabled={!connectionReady || busy}
            onClick={() => onSaveConnection()}
          >
            {t("onboardingModelSave")}
          </button>
          {onStartTrial ? (
            <div className="onboarding-wizard__trial">
              <button
                type="button"
                className="button button--ghost"
                disabled={trialBusy}
                onClick={() => onStartTrial()}
              >
                {t("onboardingTrialAction")}
              </button>
              <p className="onboarding-wizard__hint">{t("onboardingTrialHint")}</p>
            </div>
          ) : null}
          {onOpenSettings ? (
            <button type="button" className="onboarding-wizard__link" onClick={() => onOpenSettings()}>
              {t("onboardingOpenSettings")}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
