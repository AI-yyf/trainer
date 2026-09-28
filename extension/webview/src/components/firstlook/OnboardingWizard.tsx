import { useMemo, useState } from "react";
import { parseProviderConnectionPaste } from "../../../../../shared/src/providerGateway";
import type { OnboardingStep } from "../../../../../shared/src/onboarding";
import { useTranslation } from "../../lib/i18n/useTranslation";
import type { CopyKey } from "../../lib/i18n/copy";

/**
 * §十六 conversation-first cold start (§四十八: extracted component).
 *
 * The composer leads — the learner can type before any setup exists and the
 * draft stays in the box. Setup is a two-row status card, not a 1→2→3
 * ladder: each row expands into the existing full panel (workspace root,
 * trust, paste-to-connect) only when the learner asks for it, and flips to a
 * quiet ✓ as the host patches bootstrap state in.
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
  const [expandedPanel, setExpandedPanel] = useState<"model" | "workspace" | null>(null);

  const stepById = useMemo(
    () => new Map(steps.map((step) => [step.id, step] as const)),
    [steps],
  );
  const modelStep = stepById.get("connect_model");
  const workspaceStep = stepById.get("workspace_root");
  const trustDone = useMemo(
    () => steps.find((step) => step.id === "trust_window")?.status === "done",
    [steps],
  );
  const modelDone = modelStep?.status === "done";
  const rootDone = workspaceStep?.status === "done";
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

  const togglePanel = (panel: "model" | "workspace") => {
    setExpandedPanel((current) => (current === panel ? null : panel));
  };

  const rowState = (done: boolean) => (done ? "onboarding-setup__row is-done" : "onboarding-setup__row");

  return (
    <div className="onboarding-setup" role="group" aria-label={t("onboardingTitle")}>
      <p className="onboarding-setup__invite">{t("onboardingSetupInvite")}</p>
      <p className="onboarding-setup__hint">{t("onboardingSetupCaption")}</p>

      <div className="onboarding-setup__rows">
        <div
          className={rowState(modelDone)}
          aria-current={modelStep?.status === "active" && !modelDone ? "step" : undefined}
        >
          <span className="onboarding-setup__marker" aria-hidden>
            {modelDone ? "✓" : "○"}
          </span>
          <span className="onboarding-setup__name">{t(STEP_LABEL_KEY.connect_model)}</span>
          <button
            type="button"
            className="button button--ghost onboarding-setup__action"
            aria-expanded={expandedPanel === "model"}
            onClick={() => togglePanel("model")}
          >
            {modelDone ? t("onboardingSetupModelDone") : t("onboardingSetupModelAction")}
          </button>
        </div>
        {expandedPanel === "model" ? (
          <div className="onboarding-setup__panel">
            <p className="onboarding-setup__detail">{t("onboardingModelDetail")}</p>
            <label className="onboarding-setup__field">
              <span>{t("onboardingModelPasteLabel")}</span>
              <input
                type="text"
                value={draftBaseUrl}
                placeholder={t("onboardingModelPastePlaceholder")}
                onChange={(event) => handlePaste(event.target.value)}
              />
            </label>
            {pasteHint ? <p className="onboarding-setup__hint">{pasteHint}</p> : null}
            <label className="onboarding-setup__field">
              <span>{t("onboardingModelKeyLabel")}</span>
              <input
                type="password"
                value={draftApiKey}
                placeholder={
                  hasStoredApiKey && !draftApiKey
                    ? t("onboardingModelKeyStored")
                    : t("onboardingModelKeyPlaceholder")
                }
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
              <div className="onboarding-setup__trial">
                <button
                  type="button"
                  className="button button--ghost"
                  disabled={trialBusy}
                  onClick={() => onStartTrial()}
                >
                  {t("onboardingTrialAction")}
                </button>
                <p className="onboarding-setup__hint">{t("onboardingTrialHint")}</p>
              </div>
            ) : null}
            {onOpenSettings ? (
              <button
                type="button"
                className="onboarding-setup__link"
                onClick={() => onOpenSettings()}
              >
                {t("onboardingOpenSettings")}
              </button>
            ) : null}
          </div>
        ) : null}

        <div
          className={rowState(rootDone)}
          aria-current={workspaceStep?.status === "active" && !rootDone ? "step" : undefined}
        >
          <span className="onboarding-setup__marker" aria-hidden>
            {rootDone ? "✓" : "○"}
          </span>
          <span className="onboarding-setup__name">{t(STEP_LABEL_KEY.workspace_root)}</span>
          <button
            type="button"
            className="button button--ghost onboarding-setup__action"
            aria-expanded={expandedPanel === "workspace"}
            onClick={() => togglePanel("workspace")}
          >
            {rootDone ? t("onboardingSetupRootDone") : t("onboardingSetupRootAction")}
          </button>
        </div>
        {expandedPanel === "workspace" ? (
          <div className="onboarding-setup__panel">
            <p className="onboarding-setup__detail">{t("onboardingRootDetail")}</p>
            <button
              type="button"
              className="button button--accent"
              disabled={busy}
              onClick={() => onChooseWorkspaceRoot?.()}
            >
              {t("onboardingRootAction")}
            </button>
            {!trustDone && onTrustWindow ? (
              <div className="onboarding-setup__trust">
                <p className="onboarding-setup__detail">{t("onboardingTrustInlineHint")}</p>
                <button
                  type="button"
                  className="button button--ghost"
                  onClick={() => onTrustWindow()}
                >
                  {t("onboardingTrustAction")}
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
