/**
 * First-run browser-capture onboarding (owner direction, T-0050): when
 * Trainer activates and the capture extension has never been set up, surface
 * a one-time, dismissible prompt leading to the detected-browser picker.
 *
 * Pure decision module — no `vscode` import — so the exactly-once gate is
 * unit-testable without an extension host. The flag is written BEFORE the
 * prompt renders: a dropped notification must not turn into a nag every
 * launch, and the picker remains reachable from the command palette and the
 * Settings card regardless.
 */

export const CAPTURE_ONBOARDING_PROMPTED_FLAG = 'browserCapture.onboardingPrompted';

export interface CaptureOnboardingState {
  /** The one-time prompt was already shown (or dismissed) on any launch. */
  prompted: boolean;
  /** The capture bundle is already staged in the install dir. */
  prepared: boolean;
  /** The browser side already paired with this workspace. */
  paired: boolean;
}

export function shouldPromptCaptureOnboarding(state: CaptureOnboardingState): boolean {
  return !state.prompted && !state.prepared && !state.paired;
}
