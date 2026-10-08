import type { ComposerLanguage } from "./types";
import { learningActionCopy } from "./i18n/learningActionCopy";

export interface LearningScope {
  workspaceId: string;
  sessionId: string;
  generation: string;
}

/** Already admitted, identity-scoped facts. No stored title is an identity. */
export interface LearningFacts {
  scope: LearningScope;
  language: ComposerLanguage;
  workspace: { ready: boolean; detail?: string };
  provider: { ready: boolean; canGeneratePlan: boolean; detail?: string };
  freshness: "current" | "recovering" | "stale";
  connection: "ready" | "recovering" | "offline";
  connectionRecovery?: { title: string; label: string; detail: string };
  plan: {
    state: "absent" | "active" | "frozen";
    id?: string;
    revision?: number;
    currentStep?: string;
    blocker?: string;
    completion?: readonly string[];
  };
  evidence: {
    pending: readonly { id: string; summary: string }[];
    /** An authoritative runtime gate, never inferred from pending.length. */
    blockingId?: string;
  };
  training?: {
    workspaceId: string;
    cardId: string;
    title: string;
    status: "active" | "return_pending" | "completed";
  };
  dueReview?: { id: string; title: string };
  firstLookStep?: string;
  operationPending?: boolean;
}

export type LearningActionIntent =
  | "choose_workspace" | "configure_provider" | "restore_state" | "wait_for_restore"
  | "resume_training" | "finish_training" | "resume_plan" | "resolve_blocker"
  | "adopt_evidence" | "continue_step" | "continue_without_plan" | "start_review"
  | "return_to_coach" | "generate_plan" | "confirm_step";

export interface ActionDescriptor {
  intent: LearningActionIntent;
  scope: LearningScope;
  target: { planId?: string; revision?: number; step?: string; cardId?: string; evidenceId?: string; reviewId?: string };
  title: string;
  label: string;
  detail: string;
  disabled: boolean;
  busy: boolean;
}

const text = (value?: string) => value?.trim() ?? "";

/**
 * One priority authority for Learning. Existing work comes before new work;
 * a queue is supplemental unless the live runtime explicitly gates progress.
 * This function never writes, navigates, advances a phase, or creates evidence.
 */
export function resolveLearningPrimaryAction(facts: LearningFacts): ActionDescriptor {
  const copy = learningActionCopy(facts.language);
  const make = (intent: LearningActionIntent, title: string, label: string, detail: string,
    target: ActionDescriptor["target"] = {}, busy = Boolean(facts.operationPending)): ActionDescriptor => ({
      intent, scope: { ...facts.scope }, target, title, label, detail, disabled: busy, busy,
    });
  if (!facts.workspace.ready) {
    return make("choose_workspace", copy.workspaceTitle, copy.workspaceLabel,
      text(facts.workspace.detail) || copy.workspaceDetail, {}, false);
  }
  if (facts.freshness === "stale") {
    return make("restore_state", copy.staleTitle, copy.staleLabel, copy.staleDetail, {}, false);
  }
  if (facts.freshness === "recovering" || facts.connection === "recovering") {
    return make("wait_for_restore", copy.recoveringTitle, copy.recoveringLabel, copy.recoveringDetail, {}, true);
  }
  if (facts.connection === "offline") {
    return make("configure_provider", text(facts.connectionRecovery?.title) || copy.providerTitle,
      text(facts.connectionRecovery?.label) || copy.providerLabel,
      text(facts.connectionRecovery?.detail) || text(facts.provider.detail) || copy.providerDetail, {}, false);
  }

  const training = facts.training?.workspaceId === facts.scope.workspaceId && text(facts.training.cardId)
    ? facts.training : undefined;
  if (training && training.status !== "completed") {
    return training.status === "return_pending"
      ? make("finish_training", text(training.title) || copy.completedTitle, copy.returnLabel,
        copy.returnDetail, { cardId: training.cardId })
      : make("resume_training", text(training.title) || copy.completedTitle, copy.practiceLabel,
        copy.practiceDetail, { cardId: training.cardId });
  }

  const planTarget = facts.plan.state !== "absent" && text(facts.plan.id)
    ? { planId: facts.plan.id, revision: facts.plan.revision } : {};
  if (facts.plan.state === "frozen" && planTarget.planId) {
    return make("resume_plan", copy.frozenTitle, copy.frozenLabel, copy.frozenDetail, planTarget);
  }
  const withProvider = (action: ActionDescriptor, needsPlanTools = false) =>
    !facts.provider.ready || (needsPlanTools && !facts.provider.canGeneratePlan)
      ? make("configure_provider", copy.providerTitle, copy.providerLabel,
        text(facts.provider.detail) || copy.providerDetail, {}, false)
      : action;
  const step = text(facts.plan.currentStep);
  if (text(facts.plan.blocker)) {
    return withProvider(make("resolve_blocker", copy.blockerTitle, copy.blockerLabel,
      text(facts.plan.blocker), planTarget));
  }
  const gatedEvidence = facts.evidence.pending.find(item => item.id === facts.evidence.blockingId);
  const evidence = gatedEvidence ?? (!step ? facts.evidence.pending[0] : undefined);
  if (evidence) {
    return make("adopt_evidence", text(evidence.summary) || copy.evidenceTitle, copy.evidenceLabel,
      copy.evidenceDetail, { ...planTarget, evidenceId: evidence.id });
  }
  if (step) {
    const completion = (facts.plan.completion ?? []).map(item => item.trim()).filter(Boolean);
    return withProvider(make("continue_step", step, copy.continueLabel,
      completion.length ? `${copy.complete}: ${completion.join(" · ")}` : copy.continueDetail, { ...planTarget, step }));
  }
  if (facts.plan.state === "absent" && text(facts.firstLookStep)) {
    return withProvider(make("continue_without_plan", text(facts.firstLookStep), copy.directLabel, copy.directDetail));
  }
  if (facts.dueReview?.id) {
    return make("start_review", text(facts.dueReview.title) || copy.reviewTitle, copy.reviewLabel,
      copy.reviewDetail, { reviewId: facts.dueReview.id });
  }
  if (training?.status === "completed") {
    return make("return_to_coach", copy.completedTitle, copy.completedLabel, copy.completedDetail,
      { cardId: training.cardId });
  }
  if (facts.plan.state === "absent") {
    return withProvider(make("generate_plan", copy.generateTitle, copy.generateLabel, copy.generateDetail), true);
  }
  return withProvider(make("confirm_step", copy.restoreTitle, copy.restoreLabel, copy.restoreDetail, planTarget));
}

/** Re-resolve at click time; a retained callback cannot act on replaced work. */
export function learningActionIsCurrent(action: ActionDescriptor, facts: LearningFacts): boolean {
  const current = resolveLearningPrimaryAction(facts);
  return !action.disabled && !action.busy && !current.disabled && !current.busy &&
    action.intent === current.intent &&
    action.scope.workspaceId === current.scope.workspaceId &&
    action.scope.sessionId === current.scope.sessionId &&
    action.scope.generation === current.scope.generation &&
    action.title === current.title &&
    action.detail === current.detail &&
    action.target.planId === current.target.planId &&
    action.target.revision === current.target.revision &&
    action.target.step === current.target.step &&
    action.target.cardId === current.target.cardId &&
    action.target.evidenceId === current.target.evidenceId &&
    action.target.reviewId === current.target.reviewId;
}

export interface LearningActionHandlers {
  chooseWorkspace(): void;
  configureProvider(): void;
  restoreState(): void;
  openTraining(cardId: string): void;
  resumePlan(planId: string, revision?: number): void;
  resolveBlocker(): void;
  adoptEvidence(evidenceId: string): void;
  continueStep(step: string): void;
  continueWithoutPlan(): void;
  startReview(reviewId: string): void;
  returnToCoach(): void;
  generatePlan(): void;
  confirmStep(): void;
}

/** Preserve existing governed handlers; dispatch has no fallback command. */
export function executeLearningPrimaryAction(action: ActionDescriptor, facts: LearningFacts,
  handlers: LearningActionHandlers): boolean {
  if (!learningActionIsCurrent(action, facts)) return false;
  switch (action.intent) {
    case "choose_workspace": handlers.chooseWorkspace(); break;
    case "configure_provider": handlers.configureProvider(); break;
    case "restore_state": handlers.restoreState(); break;
    case "wait_for_restore": return false;
    case "resume_training": case "finish_training":
      if (!action.target.cardId) return false;
      handlers.openTraining(action.target.cardId); break;
    case "resume_plan":
      if (!action.target.planId) return false;
      handlers.resumePlan(action.target.planId, action.target.revision); break;
    case "resolve_blocker": handlers.resolveBlocker(); break;
    case "adopt_evidence":
      if (!action.target.evidenceId) return false;
      handlers.adoptEvidence(action.target.evidenceId); break;
    case "continue_step":
      if (!action.target.step) return false;
      handlers.continueStep(action.target.step); break;
    case "continue_without_plan": handlers.continueWithoutPlan(); break;
    case "start_review":
      if (!action.target.reviewId) return false;
      handlers.startReview(action.target.reviewId); break;
    case "return_to_coach": handlers.returnToCoach(); break;
    case "generate_plan": handlers.generatePlan(); break;
    case "confirm_step": handlers.confirmStep(); break;
  }
  return true;
}
