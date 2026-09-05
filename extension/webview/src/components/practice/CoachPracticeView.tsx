import { useCallback, useEffect, useRef, useState } from "react";

import {
  GearIcon,
  CheckMarkIcon,
  PageIcon,
  PlayIcon,
  LaptopIcon,
} from "../icons";
import { postMessage } from "../../lib/vscode";
import type {
  ComposerLanguage,
  DependencyMastery,
  EvidencePack,
  ImplementationGuide,
  LearningOutcome,
  TaskSpec,
  TeachingDecision,
  WorkspaceUnderstanding,
} from "../../lib/types";
import type { TrainingCardStatus } from "../../../../../shared/src/trainingCardRouting";
import { preferRecoveredTrainingFocusChrome } from "../../../../../shared/src/planOrientationGovernance";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface PracticeCoachBridge {
  title: string;
  prompt: string;
  detail: string;
  ctaLabel: string;
  summaryLines: string[];
  trainingReturn?: import("../../../../../shared/src/trainingReturn").TrainingReturnPayload;
}

export interface PracticeFileVerificationRequest {
  cardId: string;
  cardTitle: string;
  acceptanceCriteria: string[];
  learnerDeliverables: string[];
}

export interface CoachPracticeViewProps {
  language: ComposerLanguage;
  task: TaskSpec;
  workspaceUnderstanding?: WorkspaceUnderstanding;
  evidencePack?: EvidencePack;
  teachingDecision?: TeachingDecision;
  recoveredRuntime?: boolean;
  runtimeCurrentStep?: string;
  implementationGuide?: ImplementationGuide;
  dependencyMastery: DependencyMastery[];
  learningOutcomes: LearningOutcome[];
  reviewSummary?: string;
  reviewMeta?: string[];
  latestReviewActionSummary?: string;

  /** Training verification result carried from workspace state. */
  latestVerifiedResult?: string;
  /** Follow-up from latest learning round. */
  latestLearningFollowup?: string;
  /** What to bring back to coach when done. */
  latestReturnWith?: string;
  /** Signal that indicates this card is passed. */
  latestSuccessSignal?: string;
  /** Next hop title after this card completes. */
  latestNextHop?: string;
  /** Metadata pills for the next hop (status, scope, continueIn labels). */
  latestNextHopMeta?: string[];
  /** Longer detail about the next hop. */
  latestNextHopDetail?: string;
  /** Learner deliverables from the resolved handoff. */
  latestLearnerDeliverables?: string[];
  /** Verification checklist steps from the resolved handoff. */
  latestVerificationSteps?: string[];

  /** Subset of ReviewArtifact relevant to practice view. */
  reviewArtifact?: {
    summary?: string;
    verifiedResult?: string;
    blocker?: string;
    abandonReason?: string;
    partialProgress?: string;
    rootCause?: string;
    nextSelfImplementationRule?: string;
    recommendedActions?: string[];
    status?: string;
  };

  /** Current card status from training card routing. */
  cardStatus?: TrainingCardStatus;
  /** Callback to transition the card status. */
  onCardStatusTransition?: (cardId: string, newStatus: TrainingCardStatus, reason?: string) => void;
  /** Run the authoritative IDE-file check before this card can advance. */
  onVerifyCurrentFile?: (request: PracticeFileVerificationRequest) => void;
  /** Whether a card status transition is in flight. */
  cardStatusBusy?: boolean;
  /** Refresh the task / practice content. */
  onRefreshTask: (focusArea?: string) => void;
  /** Open the coach conversation with a practice bridge. */
  onOpenCoach?: (bridge: PracticeCoachBridge) => void;
  /** Switch to flash submode. */
  onOpenFlash?: () => void;
  /** Whether the practice data is loading. */
  busy?: boolean;
  /** Compact mode (narrow sidebar). */
  compact?: boolean;
  /** Card-only mode (hide chrome). */
  cardOnly?: boolean;
  /** Metadata: source chain labels. */
  cardSourceChain?: string[];
  /** Metadata: why this card now. */
  cardWhyNow?: string;
  /** Metadata: target skill badge. */
  cardTargetSkill?: string;
  /** Metadata: scenario pack badge. */
  scenarioPackLabel?: string;
  /** Metadata: feedback checklist targets. */
  cardFeedbackTargets?: string[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isZh(lang: ComposerLanguage): boolean {
  return lang === "zh-CN";
}

function t(lang: ComposerLanguage, zh: string, en: string): string {
  return isZh(lang) ? zh : en;
}

function normalizeText(value: string | undefined): string | undefined {
  const n = value?.replace(/\s+/g, " ").trim();
  return n || undefined;
}

function uniqueCompact(values: Array<string | undefined>, limit?: number): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  for (const value of values) {
    const normalized = normalizeText(value);
    if (!normalized) {
      continue;
    }
    const key = normalized.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    output.push(normalized);
    if (typeof limit === "number" && output.length >= limit) {
      break;
    }
  }
  return output;
}

function cardStatusLabel(lang: ComposerLanguage, status: TrainingCardStatus): string {
  const labels: Record<string, { zh: string; en: string }> = {
    candidate: { zh: "候选", en: "Candidate" },
    active: { zh: "进行中", en: "Active" },
    answered: { zh: "已作答", en: "Answered" },
    implemented: { zh: "已完成", en: "Completed" },
    skipped: { zh: "已跳过", en: "Skipped" },
    reviewed: { zh: "已复盘", en: "Reviewed" },
    fed_back: { zh: "已反馈", en: "Fed back" },
    archived: { zh: "已归档", en: "Archived" },
  };
  const entry = labels[status];
  return entry ? (isZh(lang) ? entry.zh : entry.en) : status;
}

/** Tier label for the hint ladder. L1 = direction, L2 = API, L3 = pseudocode, L4 = debug clues. */
function hintTierLabel(lang: ComposerLanguage, tier: number): string {
  const labels = [
    t(lang, "方向提示", "Direction hint"),
    t(lang, "API 提示", "API hint"),
    t(lang, "伪代码提示", "Pseudocode hint"),
    t(lang, "调试线索", "Debug clue"),
  ];
  return labels[Math.min(tier, labels.length - 1)];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CoachPracticeView({
  language,
  task,
  workspaceUnderstanding,
  evidencePack,
  teachingDecision,
  recoveredRuntime,
  runtimeCurrentStep,
  implementationGuide,
  dependencyMastery,
  learningOutcomes,
  reviewSummary,
  reviewMeta,
  latestReviewActionSummary,
  latestVerifiedResult,
  latestReturnWith,
  latestSuccessSignal,
  latestNextHop,
  latestNextHopMeta,
  latestNextHopDetail,
  latestLearnerDeliverables,
  latestVerificationSteps,
  reviewArtifact,
  cardStatus,
  onCardStatusTransition,
  onVerifyCurrentFile,
  cardStatusBusy = false,
  onRefreshTask,
  onOpenCoach,
  onOpenFlash,
  busy = false,
  compact = false,
  cardOnly = false,
  cardSourceChain,
  cardWhyNow,
  cardTargetSkill,
  scenarioPackLabel,
  cardFeedbackTargets,
}: CoachPracticeViewProps) {
  // --- Hint tier disclosure state ---
  const [revealedHintTier, setRevealedTier] = useState(0);

  // --- Self-check checklist state ---
  const [checkedSteps, setCheckedSteps] = useState<Record<string, boolean>>({});

  // --- Completed state ---
  const isCompleted = cardStatus === "implemented" || cardStatus === "reviewed" || cardStatus === "fed_back" || cardStatus === "archived";

  const toggleCheck = useCallback((step: string) => {
    setCheckedSteps((prev) => ({ ...prev, [step]: !prev[step] }));
  }, []);

  const allChecksDone = (latestVerificationSteps ?? []).length > 0
    ? (latestVerificationSteps ?? []).every((s) => checkedSteps[s])
    : false;

  const checkedCount = (latestVerificationSteps ?? []).filter((s) => checkedSteps[s]).length;

  const hasSelfChecks = (latestVerificationSteps ?? []).length > 0;
  const showIncompleteWarning = hasSelfChecks && !allChecksDone;

  // --- Derived data ---
  const liveTrainingFocusChrome = preferRecoveredTrainingFocusChrome({
    recovered: recoveredRuntime,
    runtimeCurrentStep,
    teachingDecisionFocusArea: teachingDecision?.focusArea,
  });
  const whyNow = normalizeText(
    cardWhyNow ||
    workspaceUnderstanding?.currentStep ||
    liveTrainingFocusChrome.teachingDecisionFocusArea,
  );

  const problemStatement = normalizeText(task.description) ?? task.title;

  const suggestedAction = normalizeText(
    (task.metadata?.suggestedWorkspaceAction as string | undefined) ||
    implementationGuide?.codebaseEntryPoints?.[0] ||
    (task.metadata?.workspaceAction as string | undefined),
  );

  const constraints: string[] = task.constraints ?? [];
  const acceptance: string[] = task.acceptanceCriteria ?? [];

  const deliverables = latestLearnerDeliverables ?? [];
  const verificationSteps = latestVerificationSteps ?? [];
  const dependencyApis = uniqueCompact(
    dependencyMastery.flatMap((item) => item.currentApis ?? []),
    4,
  );
  const studyIntro =
    normalizeText(
      implementationGuide?.teachingGoal ||
      implementationGuide?.ideaSummary ||
      implementationGuide?.currentStep,
    ) ??
    t(
      language,
      "\u5148\u770b\u6e05\u8fd9\u4e2a\u6700\u5c0f\u5207\u7247\uff0c\u518d\u8fdb\u5165\u5b9e\u9645\u7f16\u8f91\u3002",
      "Read the smallest slice first, then start editing.",
    );
  const studySignals = uniqueCompact(
    [
      implementationGuide?.scopeBoundary,
      implementationGuide?.currentStep,
      ...(implementationGuide?.nextSteps ?? []).slice(0, 2),
      ...learningOutcomes.slice(0, 2).map((outcome) =>
        outcome.summary ? `${outcome.concept}: ${outcome.summary}` : outcome.concept,
      ),
      ...dependencyApis.map((api) => `API: ${api}`),
    ],
    4,
  );
  const studyFiles = uniqueCompact(
    [
      ...(implementationGuide?.codebaseEntryPoints ?? []),
      ...(task.suggestedFiles ?? []),
    ],
    4,
  );
  const hasExecutionSection = Boolean(
    suggestedAction ||
    deliverables.length > 0 ||
    constraints.length > 0,
  );
  const hasVerificationSection = Boolean(
    acceptance.length > 0 ||
    task.validationMethod ||
    verificationSteps.length > 0,
  );

  // Hints: sourced from implementationGuide, or from task metadata
  const rawHints: string[] =
    implementationGuide?.validationStrategy?.filter(Boolean) ??
    (task.metadata?.hints as string[] | undefined) ??
    [];

  // If no explicit hints, synthesize from learning outcomes and dependency APIs
  const hints = rawHints.length > 0
    ? rawHints
    : dependencyApis.length > 0
      ? dependencyApis.slice(0, 4)
      : [];

  // Fallback action from handoff or task metadata
  const fallbackAction = normalizeText(
    (task.metadata?.fallbackAction as string | undefined),
  );

  const nextAfterCompletion = normalizeText(
    latestNextHop ??
    (task.metadata?.nextAfterCompletion as string | undefined),
  );

  // --- Handlers ---

  function handleVerifyCurrentFile(): void {
    if (!onVerifyCurrentFile) return;
    onVerifyCurrentFile({
      cardId: task.id,
      cardTitle: task.title,
      acceptanceCriteria: uniqueCompact([
        ...(task.acceptanceCriteria ?? []),
        ...(latestVerificationSteps ?? []),
      ]),
      learnerDeliverables: uniqueCompact(latestLearnerDeliverables ?? []),
    });
  }

  function handleSkip(): void {
    if (!onCardStatusTransition) return;
    onCardStatusTransition(task.id, "skipped", t(language, "学员跳过", "Learner skipped"));
  }

  function handleAskCoach(): void {
    if (!onOpenCoach) return;
    const bridge: PracticeCoachBridge = {
      title: t(language, "把「" + task.title + "」带回教练", "Bring \"" + task.title + "\" back to coach"),
      prompt: t(
        language,
        "请围绕「" + task.title + "」继续做 coach-only 评估。不要替我改代码。",
        "Keep coaching me on \"" + task.title + "\" and stay coach-only. Do not edit code for me.",
      ),
      detail: t(
        language,
        "让教练判断这次结果是通过、部分通过、降级，还是应该转成计划证据。",
        "Let the coach judge whether this was a pass, partial pass, downgrade, or plan evidence.",
      ),
      ctaLabel: t(language, "返回对话让教练判断", "Return to coach"),
      summaryLines: [
        latestVerifiedResult
          ? t(language, "验证结果：" + latestVerifiedResult, "Verified: " + latestVerifiedResult)
          : undefined,
        latestReturnWith
          ? t(language, "带回内容：" + latestReturnWith, "Bring back: " + latestReturnWith)
          : undefined,
        latestSuccessSignal
          ? t(language, "通过信号：" + latestSuccessSignal, "Pass signal: " + latestSuccessSignal)
          : undefined,
        reviewArtifact?.blocker
          ? t(language, "当前卡点：" + reviewArtifact.blocker, "Blocker: " + reviewArtifact.blocker)
          : undefined,
      ].filter((line): line is string => Boolean(line)),
    };
    onOpenCoach(bridge);
  }

  function handleRevealNextTier(): void {
    setRevealedTier((prev) => Math.min(prev + 1, hints.length));
  }

  function handleOpenFile(filePath: string): void {
    postMessage({
      type: "command/execute",
      payload: { commandId: "vscode.open", payload: filePath },
    });
  }

  // --- Keyboard navigation ---
  const checklistRef = useRef<HTMLUListElement | null>(null);
  const [checklistFocusIdx, setChecklistFocusIdx] = useState(0);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA' || target?.isContentEditable) {
        return;
      }

      if (isCompleted) return;

      switch (event.key) {
        case 'Enter':
        case ' ': {
          if (!allChecksDone && hasSelfChecks) {
            const firstUnchecked = verificationSteps.findIndex((s) => !checkedSteps[s]);
            if (firstUnchecked >= 0) {
              event.preventDefault();
              setChecklistFocusIdx(firstUnchecked);
              const checkbox = checklistRef.current?.querySelectorAll('input[type="checkbox"]')[firstUnchecked] as HTMLElement | undefined;
              checkbox?.focus();
            }
          } else if (onVerifyCurrentFile) {
            event.preventDefault();
            handleVerifyCurrentFile();
          }
          break;
        }
        case 'h':
        case 'H': {
          if (revealedHintTier < hints.length) {
            event.preventDefault();
            handleRevealNextTier();
          }
          break;
        }
        case 's':
        case 'S': {
          event.preventDefault();
          handleSkip();
          break;
        }
        case 'c':
        case 'C': {
          if (onOpenCoach) {
            event.preventDefault();
            handleAskCoach();
          }
          break;
        }
        case 'ArrowDown': {
          event.preventDefault();
          if (verificationSteps.length > 0) {
            const nextIdx = Math.min(checklistFocusIdx + 1, verificationSteps.length - 1);
            setChecklistFocusIdx(nextIdx);
            const checkbox = checklistRef.current?.querySelectorAll('input[type="checkbox"]')[nextIdx] as HTMLElement | undefined;
            checkbox?.focus();
          }
          break;
        }
        case 'ArrowUp': {
          event.preventDefault();
          if (verificationSteps.length > 0) {
            const prevIdx = Math.max(checklistFocusIdx - 1, 0);
            setChecklistFocusIdx(prevIdx);
            const checkbox = checklistRef.current?.querySelectorAll('input[type="checkbox"]')[prevIdx] as HTMLElement | undefined;
            checkbox?.focus();
          }
          break;
        }
        case '1':
        case '2':
        case '3':
        case '4':
        case '5':
        case '6':
        case '7':
        case '8':
        case '9': {
          const idx = parseInt(event.key, 10) - 1;
          if (idx < verificationSteps.length) {
            event.preventDefault();
            toggleCheck(verificationSteps[idx]);
          }
          break;
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isCompleted, allChecksDone, hasSelfChecks, verificationSteps, checkedSteps, onVerifyCurrentFile, revealedHintTier, hints.length, onOpenCoach, checklistFocusIdx, toggleCheck]);

  // --- Loading / empty states ---

  if (busy) {
    return (
      <div className="practice-card practice-card--loading" role="status" aria-busy="true">
        <div className="practice-card__pulse" />
        <p className="practice-card__loading-text">
          {t(language, "正在准备练习卡片…", "Preparing practice card…")}
        </p>
      </div>
    );
  }

  if (!task.id && !task.title) {
    return (
      <div className="practice-card practice-card--empty" role="status">
        <div className="practice-empty__icon" aria-hidden="true"><LaptopIcon size={32} /></div>
        <p className="practice-card__empty-text">
          {t(language, "暂无实战卡片", "No practice card right now")}
        </p>
        <p className="practice-card__empty-hint">
          {t(
            language,
            "教练会根据你的对话、计划和项目上下文为你生成定制化的实战题。先和教练聊聊你想练习的方向。",
            "The coach generates practice cards based on your conversations, plan, and project context. Start by telling the coach what you want to practice.",
          )}
        </p>
        <div className="practice-card__empty-actions">
          {onOpenCoach ? (
            <button
              className="button button--accent"
              type="button"
              onClick={() => onOpenCoach({
                title: t(language, "请求实战题", "Request a practice card"),
                prompt: t(language, "请为我生成一张实战练习卡", "Generate a practice card for me"),
                detail: "",
                ctaLabel: t(language, "返回对话", "Return to coach"),
                summaryLines: [],
              })}
            >
              {t(language, "去找教练聊聊", "Chat with coach")}
            </button>
          ) : null}
          <button
            className="button button--ghost"
            type="button"
            onClick={() => onRefreshTask()}
            disabled={busy}
          >
            {t(language, "刷新", "Refresh")}
          </button>
        </div>
      </div>
    );
  }

  // --- Main render ---
// --- Main render ---
  const rootClasses = [
    "practice-card",
    "card-enter",
    compact ? "practice-card--compact" : "",
    cardOnly ? "practice-card--card-only" : "",
    isCompleted ? "practice-card--completed" : "",
  ].filter(Boolean).join(" ");

  return (
    <article key={task.id} className={rootClasses} aria-label={task.title} role="region">
      {/* ── Practice card type strip (prominent) ── */}
      <div className="practice-card__type-strip">
        <span className="practice-card__type-badge-main">
          <LaptopIcon size={14} />
          {t(language, "实战卡", "Practice")}
        </span>
        <span className="practice-card__type-desc">
          {t(language, "动手练习 · 验证成果", "Hands-on · Verify results")}
        </span>
      </div>

      {/* ── Header ── */}
      <header className="practice-card__header">
        <div className="practice-card__badge-row">
          {cardStatus ? (
            <span className="practice-card__status-badge">{cardStatusLabel(language, cardStatus)}</span>
          ) : null}
        </div>
        {(cardSourceChain?.length || cardTargetSkill || cardFeedbackTargets?.length) ? (
          <div className="card-metadata">
            <div className="card-metadata__row">
              {cardSourceChain?.length ? (
                <span className="card-metadata__source">
                  {t(language, `来源: ${cardSourceChain.join(" → ")}`, `Source: ${cardSourceChain.join(" → ")}`)}
                </span>
              ) : null}
              {cardTargetSkill ? (
                <span className="card-metadata__skill">{cardTargetSkill}</span>
              ) : null}
              {scenarioPackLabel ? (
                <span className="message-part__status-chip">
                  {t(language, `场景包 · ${scenarioPackLabel}`, `Scenario pack · ${scenarioPackLabel}`)}
                </span>
              ) : null}
            </div>
            {cardFeedbackTargets?.length ? (
              <div className="card-metadata__feedback">
                {cardFeedbackTargets.map((target) => (
                  <span key={target} className="card-metadata__feedback-item">
                    <CheckMarkIcon size={12} />
                    {target}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
        <h2 className="practice-card__title">{task.title}</h2>
        {whyNow ? (
          <p className="practice-card__why-now">
            {whyNow}
          </p>
        ) : null}
      </header>

      {/* ── Problem Statement ── */}
      <section className="practice-card__section practice-card__study-first">
        <h3 className="practice-card__section-label">
          {t(language, "\u5148\u5b66\u8fd9\u4e2a", "Study this first")}
        </h3>
        <p className="practice-card__section-intro">{studyIntro}</p>
        <div className="practice-card__study-stack">
          <div className="practice-card__study-block">
            <span className="practice-card__subsection-label">
              {t(language, "\u5148\u7406\u89e3", "Understand")}
            </span>
            <p className="practice-card__study-copy">{problemStatement}</p>
          </div>
          {studySignals.length > 0 ? (
            <div className="practice-card__study-block">
              <span className="practice-card__subsection-label">
                {t(language, "\u5148\u7559\u610f", "Notice first")}
              </span>
              <ul className="practice-card__micro-list">
                {studySignals.map((signal, index) => (
                  <li key={`study-signal-${index}`} className="practice-card__list-item">
                    <span className="practice-card__list-marker" aria-hidden="true"><GearIcon size={14} /></span>
                    {signal}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {studyFiles.length > 0 ? (
            <div className="practice-card__study-block">
              <span className="practice-card__subsection-label">
                {t(language, "\u5148\u6253\u5f00", "Open first")}
              </span>
              <div className="practice-card__file-grid">
                {studyFiles.map((file) => (
                  <button
                    key={file}
                    type="button"
                    className="practice-card__file-path practice-card__file-path--clickable practice-card__file-path--study"
                    onClick={() => handleOpenFile(file)}
                    title={t(language, `在 VS Code 中打开 ${file}`, `Open ${file} in VS Code`)}
                  >
                    <PageIcon size={14} />
                    <span>{file}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </section>

      {hasExecutionSection ? (
        <section className="practice-card__section practice-card__execution">
          <h3 className="practice-card__section-label">
            {t(language, "\u518d\u52a8\u624b", "Then try it")}
          </h3>
          {suggestedAction ? (
            <p className="practice-card__section-intro practice-card__workspace-action-body">
              {suggestedAction}
            </p>
          ) : null}
          {deliverables.length > 0 ? (
            <div className="practice-card__subsection">
              <span className="practice-card__subsection-label">
                {t(language, "\u4f60\u8981\u4ea4\u4ed8", "Deliver")}
              </span>
              <ul className="practice-card__list">
                {deliverables.map((deliverable, index) => (
                  <li key={`deliverable-${index}`} className="practice-card__list-item practice-card__list-item--deliverable">
                    <span className="practice-card__list-marker" aria-hidden="true"><PlayIcon size={14} /></span>
                    {deliverable}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {constraints.length > 0 ? (
            <div className="practice-card__subsection">
              <span className="practice-card__subsection-label">
                {t(language, "\u9650\u5236\u6761\u4ef6", "Constraints")}
              </span>
              <ul className="practice-card__list">
                {constraints.map((constraint, index) => (
                  <li key={`constraint-${index}`} className="practice-card__list-item practice-card__list-item--constraint">
                    <span className="practice-card__list-marker" aria-hidden="true"><GearIcon size={14} /></span>
                    {constraint}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ) : null}

      {/* ── Tiered Hints ── */}
      {hints.length > 0 ? (
        <section className="practice-card__section practice-card__hints">
          <h3 className="practice-card__section-label">
            {t(language, "\u5361\u4f4f\u65f6\u518d\u770b\u63d0\u793a", "Hints if you need them")}
          </h3>
          <div className="practice-card__hint-ladder">
            {hints.slice(0, revealedHintTier).map((hint, i) => (
              <div key={`hint-${i}`} className="practice-card__hint-tier" role="listitem">
                <span className="practice-card__hint-tier-label">
                  L{i + 1} · {hintTierLabel(language, i)}
                </span>
                <p className="practice-card__hint-body">{hint}</p>
              </div>
            ))}
            {revealedHintTier < hints.length ? (
              <button
                className="button button--ghost button--micro practice-card__hint-reveal-btn"
                type="button"
                onClick={handleRevealNextTier}
                aria-label={t(
                  language,
                  `显示第 ${revealedHintTier + 1} 级提示`,
                  `Reveal hint tier ${revealedHintTier + 1}`,
                )}
              >
                {t(
                  language,
                  `显示第 ${revealedHintTier + 1} 级提示`,
                  `Reveal L${revealedHintTier + 1} hint`,
                )}
              </button>
            ) : null}
          </div>
        </section>
      ) : null}

      {hasVerificationSection ? (
        <section className="practice-card__section practice-card__verification">
          <h3 className="practice-card__section-label">
            {t(language, "\u6700\u540e\u9a8c\u8bc1", "Verify after editing")}
          </h3>
          {acceptance.length > 0 ? (
            <div className="practice-card__subsection">
              <span className="practice-card__subsection-label">
                {t(language, "\u901a\u8fc7\u4fe1\u53f7", "Pass signals")}
              </span>
              <ul className="practice-card__list">
                {acceptance.map((criterion, index) => (
                  <li key={`acceptance-${index}`} className="practice-card__list-item practice-card__list-item--acceptance">
                    <span className="practice-card__list-marker" aria-hidden="true"><CheckMarkIcon size={14} /></span>
                    {criterion}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {task.validationMethod ? (
            <div className="practice-card__subsection">
              <span className="practice-card__subsection-label">
                {t(language, "\u8fd9\u6837\u9a8c\u8bc1", "Validation method")}
              </span>
              <p className="practice-card__validation-body">{task.validationMethod}</p>
            </div>
          ) : null}
          {verificationSteps.length > 0 ? (
            <div className="practice-card__subsection practice-card__self-check">
              <div className="practice-card__subsection-heading">
                <span className="practice-card__subsection-label">
                  {t(language, "\u81ea\u68c0\u6e05\u5355", "Self-check")}
                </span>
                <span className={`practice-card__self-check-progress ${allChecksDone ? "practice-card__self-check-progress--done" : ""}`}>
                  {t(language, `${checkedCount}/${verificationSteps.length} 已完成`, `${checkedCount}/${verificationSteps.length} done`)}
                </span>
              </div>
              <ul className="practice-card__checklist" role="list" ref={checklistRef}>
                {verificationSteps.map((step, idx) => (
                  <li
                    key={`check-${idx}-${step}`}
                    className={`practice-card__checklist-item ${checkedSteps[step] ? "practice-card__checklist-item--checked" : ""}`}
                  >
                    <label className="practice-card__checklist-label">
                      <input
                        type="checkbox"
                        checked={Boolean(checkedSteps[step])}
                        onChange={() => toggleCheck(step)}
                        className="practice-card__checkbox"
                        aria-label={step}
                      />
                      <span className="practice-card__checklist-text">{step}</span>
                    </label>
                  </li>
                ))}
              </ul>
              {allChecksDone ? (
                <p className="practice-card__self-check-complete">
                  {t(language, "全部自检项已勾选。", "All self-checks passed.")}
                </p>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}

      {/* ── Review Artifact (if exists) ── */}
      {reviewArtifact ? (
        <section className="practice-card__section practice-card__review-artifact">
          <h3 className="practice-card__section-label">
            {t(language, "复盘结果", "Review result")}
          </h3>
          {reviewArtifact.verifiedResult ? (
            <p className="practice-card__review-body">
              {reviewArtifact.verifiedResult}
            </p>
          ) : null}
          {reviewArtifact.blocker ? (
            <p className="practice-card__review-blocker">
              {t(language, `卡点：${reviewArtifact.blocker}`, `Blocker: ${reviewArtifact.blocker}`)}
            </p>
          ) : null}
          {reviewArtifact.recommendedActions && reviewArtifact.recommendedActions.length > 0 ? (
            <ul className="practice-card__list">
              {reviewArtifact.recommendedActions.map((action, i) => (
                <li key={`rec-${i}`} className="practice-card__list-item">
                  {action}
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      {/* ── Action Area ── */}
      {!isCompleted ? (
        <section className="card-status-nav" aria-label={t(language, "操作", "Actions")}>
          <div className="practice-card__kbd-hint" aria-hidden="true">
            <span className="practice-card__kbd">Enter</span>
            <span>{t(language, "验证", "Verify")}</span>
            {hints.length > 0 ? <><span className="practice-card__kbd">H</span><span>{t(language, "提示", "Hint")}</span></> : null}
            {onOpenCoach ? <><span className="practice-card__kbd">C</span><span>{t(language, "问教练", "Coach")}</span></> : null}
            <span className="practice-card__kbd">S</span>
            <span>{t(language, "跳过", "Skip")}</span>
            {verificationSteps.length > 0 ? <><span className="practice-card__kbd">1–9</span><span>{t(language, "勾选", "Check")}</span></> : null}
          </div>
          {showIncompleteWarning ? (
            <p className="practice-card__verification-warning" role="alert">
              {t(language, "请先完成所有自检项", "Please complete all self-checks first")}
            </p>
          ) : null}
          <button
            className={`card-status-nav__btn card-status-nav__btn--primary ${showIncompleteWarning ? "practice-card__action-btn--warned" : ""}`}
            type="button"
            onClick={handleVerifyCurrentFile}
            disabled={cardStatusBusy || !onVerifyCurrentFile}
            aria-label={t(language, "验证当前文件", "Verify current file")}
          >
            {showIncompleteWarning
              ? t(language, "→ 仍要验证当前文件", "→ Verify current file anyway")
              : t(language, "→ 验证当前文件", "→ Verify current file")}
          </button>
          <button
            className="card-status-nav__btn"
            type="button"
            onClick={handleAskCoach}
            disabled={!onOpenCoach}
            aria-label={t(language, "卡住了，问教练", "I'm stuck, ask coach")}
          >
            {t(language, "卡住了，问教练", "I'm stuck, ask coach")}
          </button>
          <button
            className="card-status-nav__btn"
            type="button"
            onClick={handleSkip}
            disabled={cardStatusBusy || !onCardStatusTransition}
            aria-label={t(language, "跳过", "Skip")}
          >
            {t(language, "→ 跳过", "→ Skip")}
          </button>
        </section>
      ) : null}

      {/* ── Completed state: reflection + next hop ── */}
      {isCompleted ? (
        <section className="practice-card__completed-summary">
          {latestVerifiedResult ? (
            <p className="practice-card__verified-result">
              {t(language, `验证结果：${latestVerifiedResult}`, `Verified: ${latestVerifiedResult}`)}
            </p>
          ) : null}
          {latestSuccessSignal ? (
            <p className="practice-card__success-signal">
              {t(language, `过关信号：${latestSuccessSignal}`, `Pass signal: ${latestSuccessSignal}`)}
            </p>
          ) : null}
          {latestReturnWith ? (
            <p className="practice-card__return-note">
              {t(language, `回带：${latestReturnWith}`, `Bring back: ${latestReturnWith}`)}
            </p>
          ) : null}
          {nextAfterCompletion ? (
            <div className="practice-card__next-hop">
              <h4 className="practice-card__section-label">
                {t(language, "完成后接下来", "Next after completion")}
              </h4>
              <p className="practice-card__next-hop-title">{nextAfterCompletion}</p>
              {latestNextHopDetail ? (
                <p className="practice-card__next-hop-detail">{latestNextHopDetail}</p>
              ) : null}
              {latestNextHopMeta && latestNextHopMeta.length > 0 ? (
                <div className="practice-card__next-hop-meta">
                  {latestNextHopMeta.map((meta, i) => (
                    <span key={`meta-${i}`} className="practice-card__meta-pill">{meta}</span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          {fallbackAction && !nextAfterCompletion ? (
            <p className="practice-card__fallback">
              {t(language, `备选路径：${fallbackAction}`, `Fallback: ${fallbackAction}`)}
            </p>
          ) : null}
        </section>
      ) : null}

      {/* ── Fallback action (when not completed) ── */}
      {fallbackAction && !isCompleted ? (
        <p className="practice-card__fallback-note">
          {t(language, `如果卡住了：${fallbackAction}`, `If stuck: ${fallbackAction}`)}
        </p>
      ) : null}

      {/* ── Review Summary (bottom) ── */}
      {!cardOnly && (reviewSummary || latestReviewActionSummary || (reviewMeta?.length ?? 0) > 0) ? (
        <section className="practice-card__section practice-card__review-summary">
          <h3 className="practice-card__section-label">
            {t(language, "教练总结", "Coach summary")}
          </h3>
          {reviewSummary ? <p className="practice-card__review-summary-body">{reviewSummary}</p> : null}
          {reviewMeta && reviewMeta.length > 0 ? (
            <div className="practice-card__review-meta">
              {reviewMeta.map((meta) => (
                <span key={meta} className="practice-card__meta-pill">{meta}</span>
              ))}
            </div>
          ) : null}
          {latestReviewActionSummary ? (
            <p className="practice-card__review-followup">{latestReviewActionSummary}</p>
          ) : null}
        </section>
      ) : null}

      {/* ── Evidence Pack (collapsible) ── */}
      {!cardOnly && evidencePack && (evidencePack.verifiedResults?.length ?? 0) > 0 ? (
        <details className="practice-card__details">
          <summary className="practice-card__details-summary">
            {t(language, "已有证据", "Evidence so far")} ({evidencePack.verifiedResults?.length ?? 0})
          </summary>
          <ul className="practice-card__list">
            {evidencePack.verifiedResults?.map((ev, i) => (
              <li key={`ev-${i}`} className="practice-card__list-item">{ev}</li>
            ))}
          </ul>
        </details>
      ) : null}

      {/* ── Learning Outcomes (collapsible) ── */}
      {!cardOnly && learningOutcomes.length > 0 ? (
        <details className="practice-card__details">
          <summary className="practice-card__details-summary">
            {t(language, "学习成果", "Learning outcomes")} ({learningOutcomes.length})
          </summary>
          <ul className="practice-card__list">
            {learningOutcomes.map((lo) => (
              <li key={lo.concept} className="practice-card__list-item">
                <span className="practice-card__lo-status">{lo.outcome}</span>
                {" "}
                <span className="practice-card__lo-concept">{lo.concept}</span>
                {lo.summary ? <span className="practice-card__lo-evidence"> — {lo.summary}</span> : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {/* ── Dependency Mastery (collapsible) ── */}
      {!cardOnly && dependencyMastery.length > 0 ? (
        <details className="practice-card__details">
          <summary className="practice-card__details-summary">
            {t(language, "依赖掌握度", "Dependency mastery")} ({dependencyMastery.length})
          </summary>
          <ul className="practice-card__list">
            {dependencyMastery.slice(0, 5).map((dep) => (
              <li key={dep.dependencyKey} className="practice-card__list-item practice-card__dep-item">
                <strong>{dep.dependencyName}</strong>
                <span className="practice-card__dep-stage">
                  {dep.masteryStage ?? t(language, "待建立", "Not established")}
                </span>
                <span className="practice-card__dep-score">
                  {Math.round(dep.masteryScore * 100)}%
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {!cardOnly ? (
        <div className="practice-card__footer-actions">
          <button
            className="button button--ghost button--micro"
            type="button"
            onClick={() => onRefreshTask(liveTrainingFocusChrome.teachingDecisionFocusArea)}
            aria-label={t(language, "刷新这张实战卡", "Refresh this practice card")}
          >
            {t(language, "换一张", "Refresh")}
          </button>
          {onOpenFlash ? (
            <button
              className="button button--ghost button--micro"
              type="button"
              onClick={onOpenFlash}
              aria-label={t(language, "切到闪记卡片", "Switch to flash cards")}
            >
              {t(language, "闪记卡", "Flash cards")}
            </button>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

