import { LearningHome } from "../../templates/LearningHome";
import { NextAction, type NextActionProps } from "../../templates/NextAction";
import { SystemState } from "../../templates/SystemState";
import { templateCopy } from "../../templates/templateCopy";
import { trainingViewLabel } from "../../lib/viewLabels";
import { isVerifiedTrainingReturn } from "../../lib/learningActionResolver";
import {
  isValidElement,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import {
  describeSafeStructuredValue,
  sanitizeErrorSurfaceText,
} from "../../../../../shared/src/errorSurfaceSanitizer";

import { ActionButton, WorkbenchSurfaceButton } from "../common";
import { MessageRichContent } from "../coach/MessageRichContent";
import {
  CheckMarkIcon,
  ChevronDownIcon,
  ArrowRightIcon,
  LinkIcon,
  PlanIcon,
  TrashIcon,
} from "../icons";
import { useTranslation } from "../../lib/i18n/useTranslation";
import { resolvePlanViewCopy } from "../../lib/i18n/planViewCopy";
import {
  PLAN_COPY,
  type PlanCopyKey,
  type PlanLanguage,
} from "../../lib/i18n/segments/planInlineText";
import { reviewConceptLabel } from "../../lib/reviewLabel";
import { useWorkbenchState } from "../../app/useWorkbenchState";
import type {
  EvidenceQueueView,
  GlobalPlan,
  PlanChangeCandidateView,
  GlobalPlanProjectLink,
  LearningPlan,
  PlanRuntimeReviewPoint,
  PlanStage,
  ReviewQueueItem,
} from "../../lib/types";

export interface PlanReviewItem {
  id: string;
  title: string;
  detail?: string;
  meta?: string;
  surfaceMode?: "due" | "ahead" | "digest";
  taskHint?: string;
  focusArea?: string;
  linkedContext?: string[];
  intervalDays?: number;
  masteryScore?: number;
}

export interface PlanActionItem {
  id: string;
  label: string;
  detail?: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
  tone?: "accent" | "ghost";
  onClick?: () => void;
}

export interface PlanComposerDraftReplacementPrompt {
  source: "stage" | "project-subplan";
  title: string;
  detail: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export interface PlanGovernanceItem {
  id: string;
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: "neutral" | "good" | "warning" | "danger" | "muted";
}

export type ProjectSubplanStatus = "active" | "pending" | "blocked" | "frozen";

/**
 * A concise projection of a project subplan. Keep detailed stages and backend metadata
 * out of this view; selecting a row lets the owning surface open the fuller context.
 */
export interface ProjectSubplanView {
  id: string;
  title: string;
  status: ProjectSubplanStatus;
  nextStep?: string;
  blockedReason?: string;
  frozenReason?: string;
}

export interface EvidenceQueueActionHandlers {
  onRefreshQueue?: () => void;
  onAdoptEvidence?: (evidenceId: string) => void;
  onRejectEvidence?: (evidenceId: string, reason?: string) => void;
  onDeferEvidence?: (evidenceId: string, reason?: string) => void;
}

interface PlanDecisionStripState {
  tone: "good" | "warning" | "danger" | "muted";
  eyebrow: string;
  title: string;
  /** Optional: the merged evidence strip states the fact in the title alone. */
  detail?: string;
  next: string;
}

export interface CoachPlanViewProps {
  plan: LearningPlan | null;
  /** Resolved by the domain controller; the view never ranks actions. */
  primaryAction: NextActionProps;
  primaryEvidenceId?: string;
  /** §30: navigate to internal routes (progress, training). */
  onNavigateToView?: (view: "coach" | "plan" | "resources" | "training" | "progress" | "settings") => void;
  className?: string;
  eyebrow?: string;
  title?: string;
  titleNote?: ReactNode;
  composerDraftReplacement?: PlanComposerDraftReplacementPrompt;
  goalLabel?: string;
  goalSummary?: ReactNode;
  goalHint?: string;
  overviewLabel?: string;
  currentStageLabel?: string;
  liveStageIsCurrent?: boolean;
  nextStepLabel?: string;
  nextStepHint?: string;
  nextStepResumeThread?: string;
  summaryLabel?: string;
  cadenceLabel?: string;
  stagesLabel?: string;
  frozenLabel?: string;
  actionsLabel?: string;
  freezeStateLabel?: string;
  liveStateLabel?: string;
  memoryLabel?: string;
  winsLabel?: string;
  weakSpotsLabel?: string;
  reviewLabel?: string;
  coachingStateLabel?: string;
  coachingStateSummary?: ReactNode;
  trajectoryLabel?: string;
  trajectoryItems?: Array<{ id: string; label: string; value: ReactNode; detail?: ReactNode }>;
  pathLabel?: string;
  dueReviewItems?: PlanReviewItem[];
  dueReviewSummaryLabel?: string;
  reviewRhythm?: ReactNode;
  teachingObservationsLabel?: string;
  teachingObservations?: string[];
  emptyState?: ReactNode;
  actions?: PlanActionItem[];
  resumeActionLabel?: string;
  onResumeThread?: () => void;
  stageStatusLabels?: Partial<Record<PlanStage["status"], string>>;
  onStageSelect?: (stage: PlanStage) => void;
  nextStep?: ReactNode;
  memorySummary?: ReactNode;
  weakSpots?: string[];
  recentWins?: string[];
  supportSummaryLabel?: string;
  supportHint?: string;
  notesLabel?: string;
  whyNowLabel?: string;
  verifyLabel?: string;
  reviewWindowLabel?: string;
  pathHint?: string;
  whyNow?: ReactNode;
  verifyNow?: ReactNode;
  reviewWindow?: ReactNode;
  compactPrimary?: boolean;
  leftoverNote?: string;
  hideDecisionStrip?: boolean;
  planAtGlanceLabel?: string;
  planAtGlanceHint?: string;
  stageProgressLabel?: string;
  reviewQueueCountLabel?: string;
  currentFocusLabel?: string;
  reviewFocusLabel?: string;
  pathSummaryLabel?: string;
  pathSummaryHint?: string;
  returnLabel?: string;
  returnPath?: ReactNode;
  laterLabel?: string;
  detailsSummaryLabel?: string;
  currentStageHint?: string;
  nowLabel?: string;
  revisitSummaryLabel?: string;
  rememberedSummaryLabel?: string;
  rememberedSummary?: ReactNode;
  governanceLabel?: string;
  governanceItems?: PlanGovernanceItem[];
  evidenceQueue?: EvidenceQueueView;
  evidenceActions?: EvidenceQueueActionHandlers;
  planChangeCandidates?: readonly PlanChangeCandidateView[];
  onAcknowledgePlanChange?: (candidateId: string) => void;
  onRejectPlanChange?: (candidateId: string) => void;
  projectSubplans?: readonly ProjectSubplanView[];
  projectSubplansLabel?: string;
  projectSubplanStatusLabels?: Partial<Record<ProjectSubplanStatus, string>>;
  onProjectSubplanSelect?: (subplan: ProjectSubplanView) => void;
  globalPlan?: GlobalPlan;
  projectPlanLink?: GlobalPlanProjectLink;
  onCreateGlobalPlan?: () => void;
  onLinkCurrentProjectPlan?: () => void;
  /**
   * Host surface control: when provided (and the host can open editor tabs),
   * the header renders the "open full width in an editor tab" button.
   */
  onExpandToEditor?: () => void;
  expandToEditorLabel?: string;
}

function planCopy(
  language: PlanLanguage,
  key: PlanCopyKey,
  values: Record<string, string | number> = {},
): string {
  return Object.entries(values).reduce(
    (copy, [name, value]) => copy.replace(`{${name}}`, String(value)),
    PLAN_COPY[language][key],
  );
}

function defaultStageLabel(status: PlanStage["status"], language: PlanLanguage): string {
  if (status === "done") {
    return planCopy(language, "done");
  }
  if (status === "active") {
    return planCopy(language, "active");
  }
  return status === "queued" ? planCopy(language, "pending") : planCopy(language, "notStarted");
}

function resolveStageStatusLabel(
  status: PlanStage["status"],
  suppliedLabel: string | undefined,
  language: PlanLanguage,
): string {
  const label = suppliedLabel?.trim();
  const englishFallback =
    status === "done" ? "Done" : status === "active" ? "Active" : status === "queued" ? "Queued" : undefined;
  if (label && !(language !== "en-US" && label === englishFallback)) {
    return label;
  }
  return defaultStageLabel(status, language);
}

function defaultProjectSubplanStatusLabel(
  status: ProjectSubplanStatus,
  language: PlanLanguage,
): string {
  if (status === "active") {
    return planCopy(language, "active");
  }
  if (status === "pending") {
    return planCopy(language, "pending");
  }
  if (status === "blocked") {
    return planCopy(language, "blocked");
  }
  return planCopy(language, "frozen");
}

function projectSubplanDetail(subplan: ProjectSubplanView, language: PlanLanguage): string {
  if (subplan.status === "blocked") {
    return subplan.blockedReason?.trim() || planCopy(language, "blockerUnspecified");
  }
  if (subplan.status === "frozen") {
    return subplan.frozenReason?.trim() || planCopy(language, "projectLaneFrozen");
  }
  if (subplan.nextStep?.trim()) {
    return subplan.nextStep.trim();
  }
  return subplan.status === "active"
    ? planCopy(language, "currentWorkInProgress")
    : planCopy(language, "waitingMainPlan");
}

function formatQueuedStageSummary(count: number, language: PlanLanguage): string {
  if (count <= 0) {
    return planCopy(language, "lastStage");
  }
  return planCopy(language, "queuedStages", { count });
}

function surfaceModeLabel(
  mode: PlanReviewItem["surfaceMode"],
  language: PlanLanguage,
): string | undefined {
  if (mode === "ahead") {
    return planCopy(language, "surfaceAhead");
  }
  if (mode === "digest") {
    return planCopy(language, "surfaceDigest");
  }
  if (mode === "due") {
    return planCopy(language, "surfaceDue");
  }
  return undefined;
}

/**
 * §八: canonical capability band for review mastery scores — one honest state
 * label instead of a fake percentage. Unscored items stay unlabeled. Shared
 * wording with the progress surface: >=0.8 independent, >=0.5 assisted,
 * otherwise emerging. No numeric percent, no bars implying precision.
 */
function capabilityBandLabel(score: number | undefined, language: PlanLanguage): string | undefined {
  if (typeof score !== "number" || Number.isNaN(score) || score <= 0) {
    return undefined;
  }
  if (score >= 0.8) {
    return planCopy(language, "masteryBandIndependent");
  }
  if (score >= 0.5) {
    return planCopy(language, "masteryBandAssisted");
  }
  return planCopy(language, "masteryBandEmerging");
}

function intervalLabel(days: number | undefined, language: PlanLanguage): string | undefined {
  if (typeof days !== "number" || Number.isNaN(days)) {
    return undefined;
  }
  return planCopy(language, "intervalDays", { days });
}

function compactReviewMeta(item: PlanReviewItem, language: PlanLanguage): string | undefined {
  const meta = [
    item.meta,
    surfaceModeLabel(item.surfaceMode, language),
    intervalLabel(item.intervalDays, language),
    capabilityBandLabel(item.masteryScore, language),
  ].filter(Boolean) as string[];
  return meta.length > 0 ? meta.join(" · ") : undefined;
}

function compactReviewLane(item: PlanReviewItem, language: PlanLanguage): string {
  const lead =
    item.taskHint ??
    item.focusArea ??
    item.detail ??
    planCopy(language, "reviewLaneFallback");
  const context = item.linkedContext?.slice(0, 2).join(" · ");
  return [lead, context].filter(Boolean).join(" · ");
}

function isTextNode(value: ReactNode): value is string | number {
  return typeof value === "string" || typeof value === "number";
}

function nodeText(value: ReactNode | undefined): string {
  if (value === undefined || value === null || typeof value === "boolean") {
    return "";
  }
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => nodeText(item)).filter(Boolean).join(" ");
  }
  if (isValidElement<{ children?: ReactNode }>(value)) {
    return nodeText(value.props.children);
  }
  return "";
}

function renderNodeWithParagraph(value: ReactNode): ReactNode {
  return isTextNode(value) ? <p>{value}</p> : value;
}

function inlineText(value: ReactNode | undefined, fallback = ""): string {
  return nodeText(value).replace(/\s+/g, " ").trim() || fallback;
}

function formatEvidenceOutcome(value: string, t: (key: string) => string): string {
  const normalized = value.trim();
  if (normalized === "pass") {
    return t("evidenceOutcomePass");
  }
  if (normalized === "partial") {
    return t("evidenceOutcomePartial");
  }
  if (normalized === "fail") {
    return t("evidenceOutcomeFail");
  }
  if (normalized === "observation") {
    return t("evidenceOutcomeObservation");
  }
  if (normalized === "insight") {
    return t("evidenceOutcomeInsight");
  }
  return normalized;
}

function formatEvidenceTime(
  value: string | null | undefined,
  language: string,
): string | undefined {
  if (!value) {
    return undefined;
  }
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString(language, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function LiveEvidenceDecisionRow({
  pendingId,
  pendingSummary,
  deferLabel,
  rejectLabel,
  onDefer,
  onReject,
}: {
  pendingId: string;
  pendingSummary: string;
  deferLabel: string;
  rejectLabel: string;
  onDefer?: (evidenceId: string, reason?: string) => void;
  onReject?: (evidenceId: string, reason?: string) => void;
}) {
  return (
    <div className="coach-plan-view__compact-evidence-decisions" data-plan-evidence-decisions="true">
      {onDefer ? (
        <button
          type="button"
          className="button button--quiet button--micro"
          data-plan-evidence-decision="defer"
          onClick={() => onDefer(pendingId, pendingSummary)}
        >
          {deferLabel}
        </button>
      ) : null}
      {onReject ? (
        <button
          type="button"
          className="button button--quiet button--micro"
          data-plan-evidence-decision="reject"
          onClick={() => onReject(pendingId, pendingSummary)}
        >
          {rejectLabel}
        </button>
      ) : null}
    </div>
  );
}

export function CoachPlanView(props: CoachPlanViewProps) {
  const {
    plan,
    className,
    titleNote,
    composerDraftReplacement,
    emptyState,
    actions,
    resumeActionLabel,
    onResumeThread,
    onStageSelect,
    stageStatusLabels,
    compactPrimary = false,
    hideDecisionStrip = false,
    evidenceQueue,
    evidenceActions,
    planChangeCandidates = [],
    onAcknowledgePlanChange,
    onRejectPlanChange,
  } = props;
  const { t, language } = useTranslation();
  const planViewText = resolvePlanViewCopy(language);
  const composerDraftReplacementCancelRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!composerDraftReplacement) {
      return;
    }

    composerDraftReplacementCancelRef.current?.focus();
  }, [composerDraftReplacement?.source, composerDraftReplacement?.title]);

  const resolvedEyebrow = props.eyebrow ?? t("plan");
  const resolvedEmptyTitle = props.title ?? t("plan");
  const resolvedCurrentStageLabel =
    props.currentStageLabel ?? t("planStages");
  const resolvedGoalLabel = props.goalLabel ?? t("goals");
  const resolvedNextStepLabel =
    props.nowLabel ?? props.nextStepLabel ?? t("nextMove");
  const resolvedNextStepHint =
    props.nextStepHint ?? planCopy(language, "narrowNextHint");
  const resolvedNextStepResumeThread = props.nextStepResumeThread?.trim();
  const resolvedStagesLabel = props.stagesLabel ?? t("planStages");
  const resolvedMemoryLabel = props.memoryLabel ?? t("currentFocus");
  const resolvedWinsLabel = props.winsLabel ?? t("recentWins");
  const resolvedWeakSpotsLabel = props.weakSpotsLabel ?? t("weakSpots");
  const resolvedReviewLabel = props.reviewLabel ?? t("reviewRhythm");
  const resolvedReviewFocusLabel =
    props.reviewFocusLabel ?? planCopy(language, "reviewFocusFallback");
  const resolvedCoachingStateLabel = props.coachingStateLabel ?? t("backgroundCoachWork");
  const resolvedSupportSummaryLabel = props.supportSummaryLabel ?? t("backgroundCoachWork");
  const resolvedNotesLabel = props.notesLabel ?? planCopy(language, "notesLabel");
  const resolvedSupportHint = props.supportHint ?? planCopy(language, "supportHint");
  const resolvedWhyNowLabel = props.whyNowLabel ?? props.summaryLabel ?? t("trainingWhyNow");
  const resolvedVerifyLabel = props.verifyLabel ?? t("acceptance");
  const resolvedReviewWindowLabel =
    props.reviewWindowLabel ?? planCopy(language, "revisitLabel");
  const resolvedActionsLabel = props.actionsLabel ?? planCopy(language, "actionsLabel");
  const resolvedResumeActionLabel =
    resumeActionLabel ?? planCopy(language, "resumeInCoach");
  const resolvedReturnLabel =
    props.returnLabel ??
    props.laterLabel ??
    props.pathSummaryLabel ??
    planCopy(language, "returnLabel");
  const resolvedDetailsSummaryLabel =
    props.detailsSummaryLabel ?? planCopy(language, "moreLabel");
  const resolvedLinearOverviewLabel =
    props.overviewLabel ?? planCopy(language, "followOneThread");
  const resolvedMainlineLabel =
    props.planAtGlanceLabel ?? planCopy(language, "currentThread");
  const shouldRepeatGoalLabel =
    resolvedGoalLabel.trim().length > 0 && resolvedGoalLabel.trim() !== resolvedMainlineLabel.trim();
  const resolvedRevisitSummaryLabel =
    props.revisitSummaryLabel ?? planCopy(language, "revisitLabel");
  const resolvedGovernanceLabel =
    props.governanceLabel ?? planCopy(language, "planStatusLabel");
  const resolvedProjectSubplansLabel =
    props.projectSubplansLabel ?? planCopy(language, "projectPlansLabel");
  const projectSubplans = (props.projectSubplans ?? []).filter(
    (subplan) => subplan.id.trim().length > 0 && subplan.title.trim().length > 0,
  );
  const showEyebrow = resolvedEyebrow.trim().length > 0;
  const resolvedTitleText = nodeText(props.title ?? plan?.title).trim();
  const showHeader = showEyebrow || Boolean(resolvedTitleText) || Boolean(titleNote);
  const classes = ["section-block", "coach-plan-view", className].filter(Boolean).join(" ");
  const globalPlan = props.globalPlan;
  const globalPlanTitle = globalPlan?.title.trim() || t("globalPlanLabel");
  const hasCurrentProjectPlanLink = Boolean(
    globalPlan &&
      plan &&
      props.projectPlanLink?.globalPlanId === globalPlan.id &&
      props.projectPlanLink.projectPlanId === plan.id,
  );
  const globalPlanStatus = !globalPlan
    ? t("globalPlanNotCreated")
    : globalPlan.frozen
      ? t("globalPlanFrozen")
      : hasCurrentProjectPlanLink
        ? t("globalPlanLinked")
        : !plan
          ? t("globalPlanLinkUnavailable")
          : t("globalPlanNotLinked");
  const globalPlanRelationshipSummary = !globalPlan
    ? `${t("globalPlanLabel")} -> ${t("globalPlanNotCreated")}`
    : hasCurrentProjectPlanLink
      ? `${globalPlanTitle} -> ${plan?.title ?? t("globalPlanLabel")}`
      : `${globalPlanTitle} -> ${t("globalPlanNotLinked")}`;
  const globalPlanAction: PlanActionItem | undefined = !globalPlan
    ? props.onCreateGlobalPlan
      ? {
          id: "create-global-plan",
          label: t("globalPlanCreate"),
          icon: <PlanIcon size={12} />,
          // Demoted from accent: the NextAction "continue current step" stays
          // the single accent primary on this surface.
          tone: "ghost",
          onClick: props.onCreateGlobalPlan,
        }
      : undefined
    : !globalPlan.frozen && plan && !hasCurrentProjectPlanLink && props.onLinkCurrentProjectPlan
      ? {
          id: "link-current-project-plan",
          label: t("globalPlanLinkCurrentProject"),
          icon: <LinkIcon size={12} />,
          tone: "ghost",
          onClick: props.onLinkCurrentProjectPlan,
        }
      : undefined;
  const globalPlanContextKey = [
    globalPlan?.id ?? "none",
    plan?.id ?? "none",
    hasCurrentProjectPlanLink ? "linked" : "unlinked",
    globalPlan?.frozen ? "frozen" : "live",
  ].join(":");
  const shouldShowGlobalPlanContext = Boolean(
    globalPlan || props.onCreateGlobalPlan || props.onLinkCurrentProjectPlan,
  );
  // Always collapsed: the global↔project relationship must not compete with the
  // current step. The key forces a remount (and thus a re-collapse) when the
  // relationship state changes.
  const globalPlanContext = shouldShowGlobalPlanContext ? (
    <details
      key={globalPlanContextKey}
      className="coach-plan-view__details coach-plan-view__global-plan-context"
      aria-label={t("globalPlanRelationship")}
    >
      <summary>{globalPlanRelationshipSummary}</summary>
      <div className="coach-plan-view__details-body">
        <section className="coach-plan-view__details-group">
          <div className="coach-plan-view__global-plan-copy">
            <span>{t("globalPlanRelationship")}</span>
            <strong>{globalPlanTitle}</strong>
            <p>{globalPlanStatus}</p>
            {globalPlan?.summary.trim() ? (
              <p className="coach-plan-view__lane-note coach-plan-view__lane-note--quiet">
                {globalPlan.summary}
              </p>
            ) : null}
          </div>
          {globalPlanAction ? (
            <div className="coach-plan-view__actions-stack">
              <ActionButton
                className="coach-plan-view__action-button"
                tone={globalPlanAction.tone}
                icon={globalPlanAction.icon}
                label={globalPlanAction.label}
                detail={globalPlanAction.detail}
                onClick={globalPlanAction.onClick}
                fullWidth
              />
            </div>
          ) : null}
        </section>
      </div>
    </details>
  ) : null;

  const renderComposerDraftReplacement = (source: PlanComposerDraftReplacementPrompt["source"]) => {
    if (!composerDraftReplacement || composerDraftReplacement.source !== source) {
      return null;
    }

    return (
      <div
        className="coach-plan-view__decision-strip is-warning"
        role="alertdialog"
        aria-modal="false"
        aria-label={composerDraftReplacement.title}
        onKeyDown={(event) => { if (event.key === "Escape" && composerDraftReplacement) { event.stopPropagation(); composerDraftReplacement.onCancel(); } }}
      >
        <span className="coach-plan-view__decision-rail" aria-hidden="true" />
        <div className="coach-plan-view__decision-copy">
          <strong>{composerDraftReplacement.title}</strong>
          <em title={composerDraftReplacement.detail}>{composerDraftReplacement.detail}</em>
          <div className="coach-plan-view__actions-stack">
            <button
              ref={composerDraftReplacementCancelRef}
              className="button button--compact"
              type="button"
              onClick={composerDraftReplacement.onCancel}
            >
              <span>{composerDraftReplacement.cancelLabel}</span>
            </button>
            <button
              className="button button--primary button--compact"
              type="button"
              onClick={composerDraftReplacement.onConfirm}
            >
              <span>{composerDraftReplacement.confirmLabel}</span>
            </button>
          </div>
        </div>
      </div>
    );
  };

  const pendingEvidenceItems = useMemo(() => evidenceQueue?.pending ?? [], [evidenceQueue]);
  const settledEvidenceItems = useMemo(
    () => [
      ...(evidenceQueue?.deferred ?? []),
      ...(evidenceQueue?.adopted ?? []),
      ...(evidenceQueue?.rejected ?? []),
      ...(evidenceQueue?.unscoped ?? []),
      ...(evidenceQueue?.history ?? []),
    ],
    [evidenceQueue],
  );
  const evidenceCounts = useMemo(
    () => ({
      pending: evidenceQueue?.pending.length ?? 0,
      deferred: evidenceQueue?.deferred.length ?? 0,
      adopted: evidenceQueue?.adopted.length ?? 0,
      rejected: evidenceQueue?.rejected.length ?? 0,
      history: evidenceQueue?.history?.length ?? 0,
      unscoped: evidenceQueue?.unscoped?.length ?? 0,
      total: evidenceQueue?.totalCount ?? 0,
    }),
    [evidenceQueue],
  );
  const livePendingEvidence = evidenceQueue?.pending.find(item => item.id === props.primaryEvidenceId);
  const livePendingEvidenceId = livePendingEvidence?.id?.trim() ?? "";
  const showLiveEvidenceDecisions = Boolean(
    livePendingEvidenceId &&
      (evidenceActions?.onRejectEvidence || evidenceActions?.onDeferEvidence),
  );
  const liveEvidenceDecisionRow = showLiveEvidenceDecisions && livePendingEvidence ? (
    <LiveEvidenceDecisionRow
      pendingId={livePendingEvidenceId}
      pendingSummary={inlineText(livePendingEvidence.summary)}
      deferLabel={t("evidenceDefer")}
      rejectLabel={t("reject")}
      onDefer={evidenceActions?.onDeferEvidence}
      onReject={evidenceActions?.onRejectEvidence}
    />
  ) : null;
  const leftoverNote = props.leftoverNote?.trim() || "";
  const expandToEditorControl =
    props.onExpandToEditor && props.expandToEditorLabel ? (
      <WorkbenchSurfaceButton
        mode="expand"
        label={props.expandToEditorLabel}
        onClick={props.onExpandToEditor}
      />
    ) : null;
  if (!plan) {
    const verifiedReturns = [...new Map([...pendingEvidenceItems, ...settledEvidenceItems]
      .filter(isVerifiedTrainingReturn).map(item => [item.id, item])).values()];
    return (
      <section className="template-learning-home" data-template="LearningHome" data-plan-leftover-not-live={leftoverNote ? "true" : undefined}>
        {expandToEditorControl ? <div className="coach-plan-view__surface-control">{expandToEditorControl}</div> : null}
        <NextAction {...props.primaryAction} />
        {leftoverNote ? <p className="template-metadata" data-plan-leftover-note="true" role="status" aria-live="polite">{leftoverNote}</p> : null}
        {liveEvidenceDecisionRow}
        {verifiedReturns.length ? (
          <details className="template-disclosure" data-learning-section="evidence">
            <summary>{planViewText.practiceRecordsLabel} ({verifiedReturns.length})</summary>
            <div>{verifiedReturns.map(item => (
              <article key={item.id} data-plan-evidence-id={item.id}>
                <p>{item.summary}</p>
                <p className="template-metadata">{formatEvidenceOutcome(item.outcome, t)}</p>
              </article>
            ))}</div>
          </details>
        ) : null}
        {renderComposerDraftReplacement("stage")}
        {actions?.length ? <details className="template-disclosure"><summary>{resolvedActionsLabel}</summary><div>{actions.map((action) => <ActionButton key={action.id} tone="ghost" label={action.label} disabled={action.disabled} onClick={action.onClick} />)}</div></details> : null}
        {globalPlanContext}
        <div className="template-secondary-links" data-learning-navigation="practice-growth">
          <button type="button" className="template-back" data-learning-link="training" onClick={() => props.onNavigateToView?.("training")}>{trainingViewLabel(language)}</button>
          <button type="button" className="template-back" data-learning-link="progress" onClick={() => props.onNavigateToView?.("progress")}>{templateCopy[language].growth}</button>
        </div>
      </section>
    );
  }

  const activeStage =
    (plan.currentStageId
      ? plan.stages.find((stage) => stage.id === plan.currentStageId)
      : undefined) ??
    plan.stages.find((stage) => stage.status === "active") ??
    plan.stages[0];
  const liveStageIsCurrent = props.liveStageIsCurrent !== false;
  const liveCurrentStep = plan.currentStep?.trim() || "";
  const activeStageTitle = liveStageIsCurrent
    ? activeStage?.title ?? (props.title ?? plan.title)
    : liveCurrentStep;
  const activeStageObjective = liveStageIsCurrent
    ? activeStage?.objective ?? plan.summary
    : "";
  const currentGoalSummary = props.goalSummary ?? (compactPrimary ? undefined : activeStageObjective);
  const queuedStageCount = plan.stages.filter((stage) => stage.status === "queued").length;
  const totalStageCount = Math.max(plan.stages.length, 1);
  const activeStageIndex = Math.max(plan.stages.findIndex((stage) => stage.id === activeStage?.id), 0) + 1;
  const upcomingStages = plan.stages.filter((stage) => stage.status === "queued");
  const previewStages = upcomingStages.slice(0, 3);
  const laterSecondaryStage = previewStages[1] ?? null;
  const pathProgressNote =
    plan.stages.length === 0 ? "" : formatQueuedStageSummary(queuedStageCount, language);
  const laterContinuationNote = laterSecondaryStage
    ? planCopy(language, "thenPrefix", { step: laterSecondaryStage.title })
    : undefined;
  const verifyFallback = planCopy(language, "verifyFallback");
  const recoveredVerifyLocked =
    Boolean(plan.currentStep?.trim()) &&
    !(plan.verifyMethod ?? []).some((item) => Boolean(item.trim()));
  const returnFallback = planCopy(language, "returnFallback");
  const currentStepText = props.nextStep ?? activeStageObjective;
  const verifyNowInline = inlineText(props.verifyNow);
  const verifyText = verifyNowInline
    ? props.verifyNow
    : recoveredVerifyLocked
      ? planCopy(language, "continueCurrent")
      : verifyFallback;
  const returnPathText = props.returnPath ?? returnFallback;
  const stageProgressText = !liveStageIsCurrent
    ? ""
    : planCopy(language, "stageProgress", { index: activeStageIndex, total: totalStageCount });
  const currentGoalText = inlineText(currentGoalSummary, compactPrimary ? "" : activeStageObjective || activeStageTitle);
  const currentMainlineText = currentGoalText || activeStageTitle;
  const showGoalSummary = Boolean(!compactPrimary && currentGoalText && currentGoalText !== activeStageTitle);
  const showGoalLead = Boolean(currentMainlineText);
  const currentStepInline = inlineText(currentStepText, activeStageObjective);
  const recoveredWhyLocked = Boolean(plan.currentStep?.trim()) && !plan.whyNow?.trim();
  const whyFallback = recoveredWhyLocked ? "" : (plan.whyNow?.trim() || activeStageObjective);
  const whyNowInline = inlineText(props.whyNow, whyFallback);
  const verifyInline = inlineText(verifyText, recoveredVerifyLocked ? "" : verifyFallback);
  const returnInline = inlineText(returnPathText, returnFallback);
  const whyNowBody =
    props.whyNow && whyNowInline && whyNowInline !== currentStepInline
      ? props.whyNow
      : whyFallback && whyFallback !== currentStepInline
        ? whyFallback
        : pathProgressNote;
  const summaryChips = [stageProgressText, plan.cadence].filter(Boolean) as string[];
  const mainLanes: Array<{
    id: string;
    label: string;
    body: ReactNode;
    detail?: ReactNode;
    accent?: boolean;
  }> = [
    {
      id: "current",
      label: resolvedNextStepLabel,
      body: currentStepText,
      detail: compactPrimary ? verifyText : resolvedNextStepHint,
      accent: true,
    },
    {
      id: "why",
      label: resolvedWhyNowLabel,
      body: whyNowBody,
    },
    {
      id: "verify",
      label: resolvedVerifyLabel,
      body: verifyText,
    },
    {
      id: "return",
      label: resolvedReturnLabel,
      body: returnPathText,
      detail: !compactPrimary && laterContinuationNote ? laterContinuationNote : undefined,
    },
  ];
  const currentLane = mainLanes[0];
  const compactLaterText = (() => {
    const now = inlineText(currentLane.body);
    const done = inlineText(currentLane.detail);
    const reviewText = inlineText(props.reviewWindow);
    const reviewFirst = reviewText.match(/^[\s\S]*?[。.!?]/)?.[0]?.trim() || reviewText;
    const queued = upcomingStages[0]?.title?.trim() ?? "";
    return [compactPrimary ? "" : reviewFirst, queued].find((text) => text && text !== now && text !== done) ?? "";
  })();
  const routeStripItems = [
    {
      id: "current",
      label: resolvedCurrentStageLabel,
      body: activeStageTitle,
      detail: stageProgressText,
    },
    {
      id: "why",
      label: resolvedWhyNowLabel,
      body: whyNowBody,
      detail: undefined,
    },
    {
      id: "verify",
      label: resolvedVerifyLabel,
      body: verifyText,
      detail: undefined,
    },
    {
      id: "return",
      label: resolvedReturnLabel,
      body: returnPathText,
      detail: laterContinuationNote,
    },
  ];
  const supportRows = [
    props.reviewWindow
      ? {
          id: "review-window",
          label: resolvedReviewWindowLabel,
          body: props.reviewWindow,
        }
      : null,
    props.coachingStateSummary
      ? {
          id: "coach-state",
          label: resolvedCoachingStateLabel,
          body: props.coachingStateSummary,
        }
      : null,
    props.memorySummary
      ? {
          id: "memory-summary",
          label: resolvedMemoryLabel,
          body: props.memorySummary,
        }
      : null,
    props.reviewRhythm
      ? {
          id: "review-rhythm",
          label: resolvedReviewLabel,
          body: props.reviewRhythm,
        }
      : null,
    props.rememberedSummary
      ? {
          id: "remembered-summary",
          label: props.rememberedSummaryLabel ?? planCopy(language, "trainerRemembers"),
          body: props.rememberedSummary,
        }
      : null,
  ].filter(Boolean) as Array<{ id: string; label: string; body: ReactNode }>;
  const reviewSupportRow = supportRows.find((row) => row.id === "review-window") ?? null;
  const backgroundRows = supportRows.filter((row) => row.id !== "review-window");

  const noteRows = [
    props.teachingObservations?.length
      ? {
          id: "observations",
          label: props.teachingObservationsLabel ?? planCopy(language, "teachingObservationsLabel"),
          value: props.teachingObservations.slice(0, 3).join(" · "),
        }
      : null,
    props.weakSpots?.length
      ? {
          id: "weak-spots",
          label: resolvedWeakSpotsLabel,
          value: props.weakSpots.slice(0, 3).join(" · "),
        }
      : null,
    props.recentWins?.length
      ? {
          id: "recent-wins",
          label: resolvedWinsLabel,
          value: props.recentWins.slice(0, 3).join(" · "),
        }
      : null,
  ].filter(Boolean) as Array<{ id: string; label: string; value: string }>;
  const trajectoryRows = (props.trajectoryItems ?? []).slice(0, 3).map((item) => ({
    id: item.id,
    label: item.label,
    value: inlineText(item.value),
    detail: inlineText(item.detail),
  }));

  const hasStageDetails = plan.stages.length > 1;
  const hasReviewDetails = Boolean(props.dueReviewItems?.length) || Boolean(reviewSupportRow);
  const hasTrajectoryDetails = trajectoryRows.length > 0;
  const hasBackgroundDetails = backgroundRows.length > 0 || noteRows.length > 0 || hasTrajectoryDetails;
  const evidenceTone = evidenceCounts.pending > 0 ? "warning" : evidenceCounts.deferred > 0 ? "muted" : "good";
  const hasEvidenceDetails = evidenceCounts.total > 0;
  return (
    <LearningHome
      currentLabel={templateCopy[language].currentLearning}
      title={plan.title}
      stage={stageProgressText ? `${stageProgressText} · ${activeStageTitle}` : activeStageTitle}
      headerActions={expandToEditorControl}
      next={props.primaryAction}
      nextTools={liveEvidenceDecisionRow}
      review={hasReviewDetails ? { label: resolvedRevisitSummaryLabel, content: <>
        {reviewSupportRow ? renderNodeWithParagraph(reviewSupportRow.body) : null}
        {props.dueReviewItems?.slice(0, 4).map((item) => <div key={item.id}><strong>{item.title}</strong><p>{compactReviewLane(item, language)}</p></div>)}
        <button type="button" className="template-back" onClick={() => useWorkbenchState.getState().openTrainingReviewQueue()}>{templateCopy[language].startReview}</button>
      </> } : undefined}
      route={{ label: resolvedStagesLabel, content: <>
        {renderComposerDraftReplacement("stage")}
        {plan.stages.map((stage) => <PlanStageSection key={stage.id} stage={stage} planId={plan.id} isActive={stage.id === activeStage?.id} statusLabel={resolveStageStatusLabel(stage.status, stageStatusLabels?.[stage.status], language)} />)}
      </> }}
      growth={{ label: templateCopy[language].growth, content: (
        <button type="button" className="template-back" data-plan-growth-link="progress" onClick={() => props.onNavigateToView?.("progress")}>{planViewText.viewGrowth}</button>
      ) }}
      evidence={hasEvidenceDetails ? { label: `${planViewText.practiceRecordsLabel} (${evidenceCounts.total})`, content: <>
        <section
          className={`coach-plan-view__details-group coach-plan-view__details-group--evidence is-${evidenceTone}`}
          aria-label={planViewText.practiceRecordsLabel}
        >
          {pendingEvidenceItems.length > 0 ? (
            <div className="coach-plan-view__evidence-list">
              {pendingEvidenceItems.map((item) => {
                const summary = inlineText(item.summary);
                const outcome = formatEvidenceOutcome(item.outcome, t);
                const time = formatEvidenceTime(item.timestamp, language);
                return (
                  <article key={item.id} className="coach-plan-view__evidence-row" data-plan-evidence-row="pending">
                    <div className="coach-plan-view__evidence-row-head">
                      <div>
                        <strong>{summary}</strong>
                        <p>{[outcome, time].filter(Boolean).join(" · ")}</p>
                      </div>
                      <StatusLabel label={t("pending")} />
                    </div>
                    {(evidenceActions?.onAdoptEvidence ||
                      evidenceActions?.onRejectEvidence ||
                      evidenceActions?.onDeferEvidence) &&
                    !(showLiveEvidenceDecisions && !item.deferredAt) ? (
                      <div className="coach-plan-view__evidence-actions">
                        {evidenceActions?.onAdoptEvidence ? (
                          <ActionButton
                            tone="accent"
                            icon={<CheckMarkIcon size={12} />}
                            label={t("evidenceAdopt")}
                            onClick={() => evidenceActions.onAdoptEvidence?.(item.id)}
                            fullWidth={false}
                          />
                        ) : null}
                        {evidenceActions?.onDeferEvidence ? (
                          <ActionButton
                            tone="ghost"
                            icon={<ChevronDownIcon size={12} />}
                            label={t("evidenceDefer")}
                            onClick={() => evidenceActions.onDeferEvidence?.(item.id, summary)}
                            fullWidth={false}
                          />
                        ) : null}
                        {evidenceActions?.onRejectEvidence ? (
                          <ActionButton
                            tone="ghost"
                            icon={<TrashIcon size={12} />}
                            label={t("reject")}
                            onClick={() => evidenceActions.onRejectEvidence?.(item.id, summary)}
                            fullWidth={false}
                          />
                        ) : null}
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          ) : null}
          {settledEvidenceItems.length > 0 ? (
            <div className="coach-plan-view__evidence-list coach-plan-view__evidence-list--settled">
              {settledEvidenceItems.map((item) => {
                const summary = inlineText(item.summary);
                const outcome = formatEvidenceOutcome(item.outcome, t);
                const time = formatEvidenceTime(item.timestamp, language);
                const state = item.adopted
                  ? t("evidenceFilterAdopted")
                  : item.rejectedAt
                    ? t("evidenceFilterRejected")
                    : item.deferredAt
                      ? t("evidenceFilterDeferred")
                      : t("history");
                return (
                  <article key={item.id} className="coach-plan-view__evidence-row coach-plan-view__evidence-row--settled" data-plan-evidence-row="settled">
                    <div className="coach-plan-view__evidence-row-head">
                      <div>
                        <strong>{summary}</strong>
                        <p>{[state, outcome, time].filter(Boolean).join(" · ")}</p>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : null}
        </section>
      </> } : undefined}
    >
      {leftoverNote ? <p className="template-metadata" data-plan-leftover-note="true" role="status" aria-live="polite">{leftoverNote}</p> : null}
      {renderComposerDraftReplacement("project-subplan")}
      <details className="template-disclosure"><summary>{t("globalPlanLabel")}</summary><div>{globalPlanContext}</div></details>
      {projectSubplans.length > 0 ? <details className="template-disclosure coach-plan-view__project-subplans"><summary>{`${resolvedProjectSubplansLabel} (${projectSubplans.length})`}</summary><div>{projectSubplans.map((subplan) => {
        const detail = projectSubplanDetail(subplan, language);
        return <button key={subplan.id} type="button" className="template-back" disabled={!props.onProjectSubplanSelect} onClick={() => props.onProjectSubplanSelect?.(subplan)}><span>{subplan.title}</span>{detail ? <span className="template-metadata"> · {detail}</span> : null}</button>;
      })}</div></details> : null}
      <details className="template-disclosure" data-plan-governance-disclosure="true">
        <summary>{resolvedDetailsSummaryLabel}</summary>
        <div>
          {backgroundRows.map((row) => <div key={row.id}>{renderNodeWithParagraph(row.body)}</div>)}
          {noteRows.map((row) => <p key={row.id}>{row.label}: {row.value}</p>)}
          {(actions ?? []).map((action) => <ActionButton key={action.id} tone="ghost" label={action.label} detail={action.detail} disabled={action.disabled} onClick={action.onClick} />)}
          {planChangeCandidates.map((candidate) => <div key={candidate.id}>
            <p>{sanitizeErrorSurfaceText(candidate.reason, language)}</p>
            <p>{describeSafeStructuredValue(candidate.diff, language, planCopy(language, "noVisibleDiff"))}</p>
            <p>{describeSafeStructuredValue(candidate.impact, language, planCopy(language, "noVisibleImpact"))}</p>
            {candidate.status === "pending" ? <>
              <ActionButton tone="ghost" label={planCopy(language, "adoptAdjustment")} onClick={() => onAcknowledgePlanChange?.(candidate.id)} />
              <ActionButton tone="ghost" label={planCopy(language, "dismissAdjustment")} onClick={() => onRejectPlanChange?.(candidate.id)} />
            </> : null}
          </div>)}
        </div>
      </details>
    </LearningHome>
  );
}

function StatusLabel({ label }: { label: string }) {
  return <span className="coach-plan-view__status">{label}</span>;
}

/** Staggered entrance delay: one step per item, capped at the first 8 items. */
function planStaggerDelay(index: number): string {
  return `calc(var(--motion-fast) / 4 * ${Math.min(Math.max(index, 0), 7)})`;
}

/**
 * The 生成资料 action for one stage. While generation runs the label is replaced
 * by a shimmering skeleton strip that collapses its width (see
 * .stage-material-generate__shimmer), and the button reports busy state.
 */
function StageMaterialGenerateButton({ planId, stageId }: { planId: string; stageId: string }) {
  const { t } = useTranslation();
  const generating = useWorkbenchState((state) =>
    Boolean(state.stageMaterialGenerating[stageId]),
  );
  const requestStageMaterialGeneration = useWorkbenchState(
    (state) => state.requestStageMaterialGeneration,
  );
  const label = generating ? t("planStageMaterialsGenerating") : t("planStageMaterialsGenerate");
  return (
    <button
      type="button"
      className="button button--ghost button--micro stage-material-generate"
      data-stage-materials-generate="true"
      disabled={generating}
      aria-busy={generating}
      aria-label={label}
      onClick={() => requestStageMaterialGeneration(planId, stageId)}
    >
      {generating ? (
        <span className="skeleton stage-material-generate__shimmer" aria-hidden="true" />
      ) : (
        <span>{label}</span>
      )}
    </button>
  );
}

/**
 * One plan stage as a simple text row: title plus one status word. The stage's
 * materials and the 生成资料 action live inside a nested <details> that is
 * closed by default, so the roadmap stays quiet until the learner opens it.
 * The active stage additionally gets the accent left-edge bar (.stage-row--active).
 */
function PlanStageSection({
  stage,
  planId,
  isActive,
  statusLabel,
}: {
  stage: PlanStage;
  planId: string;
  isActive: boolean;
  statusLabel: string;
}) {
  return (
    <div
      className={`stage-row${isActive ? " stage-row--active" : ""}`}
      data-plan-stage={stage.id}
      data-stage-status={stage.status}
    >
      <details
        className="template-disclosure coach-plan-view__stage-details"
      >
        <summary>
          <span className="stage-block__title-text">{stage.title}</span>
          <StatusLabel label={statusLabel} />
        </summary>
        <div className="coach-plan-view__details-body">
          {stage.objective ? <p className="coach-plan-view__lane-note">{stage.objective}</p> : null}
          <StageMaterialGenerateButton planId={planId} stageId={stage.id} />
          <StageMaterialsSection stageId={stage.id} />
        </div>
      </details>
    </div>
  );
}

/**
 * Per-stage generated study materials, rendered inside the stage's nested
 * details. Reads the shared workbench store directly so the plan view stays
 * prop-compatible while materials arrive via host state patches. Newly mounted
 * materials fade in with a capped stagger (.plan-material-enter).
 */
function StageMaterialsSection({ stageId }: { stageId: string }) {
  const { t, language } = useTranslation();
  const materials = useWorkbenchState((state) => state.stageMaterials[stageId]);
  const generating = useWorkbenchState((state) =>
    Boolean(state.stageMaterialGenerating[stageId]),
  );
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const items = materials ?? [];

  return (
    <div className="coach-plan-view__stage-materials" data-stage-materials={stageId}>
      {items.length === 0 ? (
        <div className="empty-state stage-material-empty" data-stage-materials-empty="true">
          <PlanIcon size={16} />
          <p className="empty-state__title">
            {generating ? t("planStageMaterialsGenerating") : t("planStageMaterialsEmpty")}
          </p>
        </div>
      ) : (
        <ul className="coach-plan-view__stage-material-list">
          {items.map((item, index) => {
            const expanded = expandedId === item.id;
            const summary = item.summary.replace(/\s+/g, " ").trim();
            return (
              <li
                key={item.id}
                className="coach-plan-view__stage-material-item plan-material-enter"
                style={{ animationDelay: planStaggerDelay(index) }}
              >
                <button
                  type="button"
                  className="coach-plan-view__stage-material-toggle"
                  aria-expanded={expanded}
                  onClick={() => setExpandedId(expanded ? null : item.id)}
                >
                  <span className="coach-plan-view__stage-material-title">
                    <strong>{item.title}</strong>
                  </span>
                  {summary ? (
                    <span className="coach-plan-view__stage-material-summary">{summary}</span>
                  ) : null}
                  <span className="coach-plan-view__stage-material-action">
                    {expanded ? t("planStageMaterialsHide") : t("planStageMaterialsView")}
                  </span>
                </button>
                {expanded ? (
                  <div className="coach-plan-view__stage-material-content">
                    <MessageRichContent body={item.content} language={language} />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
