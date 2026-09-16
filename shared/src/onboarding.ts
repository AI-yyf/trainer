/**
 * Cold-start onboarding derivation shared by the webview wizard and host tests.
 *
 * Step precedence mirrors the CoachGuidance priority ladder
 * (extension/webview/src/components/coach/CoachGuidance.tsx): the provider
 * setup item is the highest-priority guidance, but a learner cannot even save
 * a provider until a Trainer workspace root is selected and the window is
 * trusted, so the wizard walks: workspace root → trust window → connect model.
 */

export type OnboardingStepId = "workspace_root" | "trust_window" | "connect_model";

export type OnboardingStepStatus = "done" | "active" | "pending";

export type OnboardingTrustState = "unknown" | "untrusted" | "remote" | "trusted";

export interface OnboardingStep {
  id: OnboardingStepId;
  status: OnboardingStepStatus;
}

export interface OnboardingDerivationInput {
  /** `memory.workspace.trainerWorkspace.status` from the bootstrap snapshot. */
  workspaceAdmissionStatus?: string;
  /** Trust state resolved from the live capability summary. */
  workspaceTrustState?: OnboardingTrustState;
  providerConfigured?: boolean;
  providerApiKeyConfigured?: boolean;
  /** `describeProviderSendState(...).blocked` for the current provider view. */
  providerSendBlocked?: boolean;
}

export interface OnboardingDerivation {
  steps: OnboardingStep[];
  activeStepId?: OnboardingStepId;
  complete: boolean;
}

export const ONBOARDING_STEP_ORDER: OnboardingStepId[] = [
  "workspace_root",
  "trust_window",
  "connect_model",
];

const TRUSTED_TRUST_STATES: ReadonlySet<OnboardingTrustState> = new Set(["trusted", "remote"]);

export function isOnboardingStepDone(
  stepId: OnboardingStepId,
  input: OnboardingDerivationInput,
): boolean {
  switch (stepId) {
    case "workspace_root":
      return (
        typeof input.workspaceAdmissionStatus === "string" &&
        input.workspaceAdmissionStatus.trim().length > 0 &&
        input.workspaceAdmissionStatus !== "root-missing"
      );
    case "trust_window":
      return input.workspaceTrustState === "unknown"
        ? false
        : TRUSTED_TRUST_STATES.has(input.workspaceTrustState ?? "unknown");
    case "connect_model":
      return (
        input.providerConfigured === true &&
        input.providerApiKeyConfigured === true &&
        input.providerSendBlocked !== true
      );
    default:
      return false;
  }
}

/**
 * Derive the three wizard steps from live workbench state. The first
 * not-done step becomes `active`; earlier steps are `done`, later ones
 * `pending`. Completion is a pure function of state, so the wizard
 * auto-advances as host patches arrive.
 */
export function deriveOnboardingSteps(
  input: OnboardingDerivationInput,
): OnboardingDerivation {
  const steps: OnboardingStep[] = ONBOARDING_STEP_ORDER.map((id) => ({
    id,
    status: isOnboardingStepDone(id, input) ? "done" : "pending",
  }));
  const activeStep = steps.find((step) => step.status !== "done");
  if (activeStep) {
    activeStep.status = "active";
  }
  return {
    steps,
    activeStepId: activeStep?.id,
    complete: !activeStep,
  };
}
