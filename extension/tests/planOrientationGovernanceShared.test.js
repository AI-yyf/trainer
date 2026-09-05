'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildRecoveredPlanResumeTurn,
  derivePlanOrientation,
  formalPlanIsLiveRuntimeIdentity,
  liveEvidenceBinding,
  liveFormalPlanCadence,
  liveFormalPlanFrozen,
  liveFormalPlanStages,
  liveFormalPlanSummary,
  liveFormalPlanTitle,
  liveTrainingFormalSummary,
  liveTrainingSourceFallback,
  liveTrainingFocusFallback,
  liveTrainingTargetSkill,
  liveTrainingTitleFallback,
  liveTrainingNextChallengeTitle,
  liveTrainingWhyNow,
  liveTrainingCoachSummary,
  formalTaskIsLiveRuntimeIdentity,
  leftoverTaskGuideFocusIsNotLive,
  leftoverCoachTurnChromeIsNotLive,
  leftoverCoachConversationIsNotLive,
  leftoverSuggestedActionsIsNotLive,
  leftoverMintingSuggestedActionsAreNotLive,
  leftoverBoundPlanCompetingIdentityLabels,
  leftoverFirstLookHeadlineIsNotLive,
  leftoverEvaluationHeadlineIsNotLive,
  leftoverStreamingCheckpointIsNotLive,
  leftoverTransferSkillIsNotLive,
  leftoverTransferSkillHasRealMultiSceneProof,
  preferRecoveredTransferSkill,
  leftoverTrainingFocusChromeIsNotLive,
  leftoverTrainingHandoffChromeIsNotLive,
  leftoverResourceSelectedDetailIsNotLive,
  leftoverResourceSandboxPreviewIsNotLive,
  leftoverResourceSandboxStateIsNotLive,
  leftoverResourceLibraryListIsNotLive,
  leftoverSettingsProfileRhythmIsNotLive,
  leftoverSettingsLearnerProjectOnboardingIsNotLive,
  streakAdaptsWithoutInventingLiveObjects,
  pressureAdaptsWithoutInventingLiveObjects,
  preferRecoveredCoachTaskChrome,
  preferRecoveredCoachTurnChrome,
  preferRecoveredTrainingFocusChrome,
  preferRecoveredTrainingHandoffChrome,
  preferRecoveredResourceSelectedDetail,
  preferRecoveredSettingsProfileRhythm,
  preferRecoveredSettingsLearnerProjectOnboarding,
  lockRecoveredPlanVerifyItems,
  normalizeRecoveredPlanResumeTurn,
  preferRecoveredPlanRuntimeFacts,
  scopeEvidenceQueueToRuntimeStep,
  recoveredPlanResumeMessage,
  resolveLivePlanStageChrome,
} = require('../dist/shared/src/planOrientationGovernance.js');

test('empty plan is not treated as ready', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: false,
    currentStep: 'Inferred theater step',
    language: 'en-US',
  });
  assert.equal(orientation.state, 'needs_setup');
  assert.equal(orientation.primaryAction, 'generate_plan');
  assert.notEqual(orientation.objectLabel, 'Inferred theater step');
});

test('first-look understand does not make generate-plan the only Plan next', () => {
  const firstLookNext = 'Add a token expiry test';
  const firstLookWhy = 'auth.py already checks expired tokens.';
  const orientation = derivePlanOrientation({
    hasFormalPlan: false,
    firstLookRecommendedNext: firstLookNext,
    firstLookWhy,
    language: 'en-US',
  });
  assert.notEqual(orientation.primaryAction, 'generate_plan');
  assert.equal(orientation.primaryAction, 'continue_without_plan');
  assert.equal(orientation.nextStep, firstLookNext);
  assert.equal(orientation.why, firstLookWhy);
  assert.notEqual(orientation.nextStep, 'Generate a mainline before choosing the current step.');
  const recoveredEmpty = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    currentStep: '',
    firstLookRecommendedNext: firstLookNext,
    firstLookWhy,
    language: 'en-US',
  });
  assert.equal(recoveredEmpty.primaryAction, 'wait');
  assert.notEqual(recoveredEmpty.primaryAction, 'generate_plan');
  assert.notEqual(recoveredEmpty.nextStep, firstLookNext);
  const liveStep = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: firstLookNext,
    whyNow: firstLookWhy,
    firstLookRecommendedNext: 'Invent a leftover first-look plan',
    language: 'en-US',
  });
  assert.equal(liveStep.primaryAction, 'continue_step');
  assert.notEqual(liveStep.primaryAction, 'generate_plan');
  assert.notEqual(liveStep.primaryAction, 'continue_without_plan');
});

test('recovered without a live step and without leftover first-look offers generate, not wait theater', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    currentStep: '',
    language: 'en-US',
  });
  assert.equal(orientation.primaryAction, 'generate_plan');
  assert.equal(orientation.state, 'needs_setup');
  assert.notEqual(orientation.primaryAction, 'wait');
});

test('finished recovered runtime leaves in_progress and asks to verify, not generate a plan', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'waiting',
    currentStep: 'Keep one auth check',
    whyNow: 'Expired tokens still leak the session.',
    verifyMethod: ['Run the focused auth check'],
    pendingEvidenceCount: 1,
    language: 'en-US',
  });
  assert.equal(orientation.state, 'waiting');
  assert.notEqual(orientation.state, 'working');
  assert.equal(orientation.primaryAction, 'adopt_evidence');
  assert.notEqual(orientation.primaryAction, 'continue_step');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
  assert.equal(orientation.objectLabel, 'Keep one auth check');
  assert.match(orientation.nextStep, /Run the focused auth check/);
});

test('waiting after defer does not claim adopt or continue as success', () => {
  const afterDefer = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'waiting',
    currentStep: 'Keep one auth check',
    whyNow: 'Expired tokens still leak the session.',
    verifyMethod: ['I ran the focused auth check on the login path.'],
    pendingEvidenceCount: 0,
    language: 'en-US',
  });
  assert.equal(afterDefer.state, 'waiting');
  assert.equal(afterDefer.primaryAction, 'wait');
  assert.notEqual(afterDefer.primaryAction, 'adopt_evidence');
  assert.notEqual(afterDefer.primaryAction, 'continue_step');
});

test('waiting after reject does not claim adopt until a replacement is pending', () => {
  const afterReject = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'waiting',
    currentStep: 'Keep one auth check',
    whyNow: 'Expired tokens still leak the session.',
    verifyMethod: ['I ran the focused auth check on the login path.'],
    pendingEvidenceCount: 0,
    language: 'en-US',
  });
  assert.equal(afterReject.state, 'waiting');
  assert.equal(afterReject.primaryAction, 'wait');
  assert.notEqual(afterReject.primaryAction, 'adopt_evidence');
  const afterReplacement = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'waiting',
    currentStep: 'Keep one auth check',
    whyNow: 'Expired tokens still leak the session.',
    verifyMethod: ['I reran the focused auth check with the expiry case.'],
    pendingEvidenceCount: 1,
    language: 'en-US',
  });
  assert.equal(afterReplacement.primaryAction, 'adopt_evidence');
  assert.notEqual(afterReplacement.primaryAction, 'wait');
});

test('waiting without pending evidence does not claim adopt', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'waiting',
    currentStep: 'Keep one auth check',
    whyNow: 'Expired tokens still leak the session.',
    verifyMethod: ['Run the focused auth check'],
    language: 'en-US',
  });
  assert.equal(orientation.state, 'waiting');
  assert.equal(orientation.primaryAction, 'wait');
  assert.notEqual(orientation.primaryAction, 'adopt_evidence');
  assert.notEqual(orientation.primaryAction, 'continue_step');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
  assert.match(orientation.nextStep, /Run the focused auth check/);
});

test('after verified adopt the recovered runtime continues the structured next, not waiting', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Add a token expiry test',
    whyNow: 'Expired tokens still leak the session.',
    language: 'en-US',
  });
  assert.equal(orientation.state, 'working');
  assert.notEqual(orientation.state, 'waiting');
  assert.equal(orientation.primaryAction, 'continue_step');
  assert.notEqual(orientation.primaryAction, 'adopt_evidence');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
  assert.equal(orientation.objectLabel, 'Add a token expiry test');
  assert.notEqual(orientation.objectLabel, 'Keep one auth check');
});

test('waiting recovered runtime without a structured next still asks to verify, not invent continue', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'waiting',
    currentStep: 'Keep one auth check',
    whyNow: 'Expired tokens still leak the session.',
    language: 'en-US',
  });
  assert.equal(orientation.state, 'waiting');
  assert.equal(orientation.primaryAction, 'wait');
  assert.notEqual(orientation.primaryAction, 'adopt_evidence');
  assert.notEqual(orientation.primaryAction, 'continue_step');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
  assert.equal(orientation.objectLabel, 'Keep one auth check');
});

test('after adopt a remaining blocker stays clear_blocker, not invented continue', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Add a token expiry test',
    blockedReason: 'Token refresh still returns 401.',
    whyNow: 'Expired tokens still leak the session.',
    language: 'en-US',
  });
  assert.equal(orientation.state, 'working');
  assert.equal(orientation.primaryAction, 'clear_blocker');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
  assert.match(orientation.why, /401/);
});

test('in-progress recovered runtime shows reply-updated step and next, not the pre-resume step', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Add a token expiry test',
    whyNow: 'Expired tokens still leak the session.',
    nextAfterCurrent: 'Wire the guard into the login path.',
    language: 'en-US',
  });
  assert.equal(orientation.state, 'working');
  assert.equal(orientation.objectLabel, 'Add a token expiry test');
  assert.equal(orientation.why, 'Expired tokens still leak the session.');
  assert.equal(orientation.nextStep, 'Wire the guard into the login path.');
  assert.notEqual(orientation.objectLabel, 'Keep one auth check');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
});

test('formal plan stage is not live current after recovered runtime advances', () => {
  const movedOn = resolveLivePlanStageChrome({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    planStageTitle: 'Auth',
    planStageGoal: 'Keep one check',
  });
  assert.equal(movedOn.stageIsCurrent, false);
  assert.equal(movedOn.liveCurrent, 'Add a token expiry test');
  assert.notEqual(movedOn.liveCurrent, 'Auth');
  const orientation = derivePlanOrientation({
    hasFormalPlan: true,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: movedOn.liveCurrent,
    language: 'en-US',
  });
  assert.equal(orientation.objectLabel, 'Add a token expiry test');
  assert.notEqual(orientation.objectLabel, 'Auth');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
  const stillOnStage = resolveLivePlanStageChrome({
    recovered: true,
    runtimeCurrentStep: 'Keep one auth check',
    planCurrentStep: 'Keep one auth check',
    planStageTitle: 'Auth',
    planStageGoal: 'Keep one check',
  });
  assert.equal(stillOnStage.stageIsCurrent, true);
  assert.equal(stillOnStage.liveCurrent, 'Keep one auth check');
});

test('leftover adopted evidenceBinding is not live Review evidence', () => {
  const leftover = liveEvidenceBinding({
    binding: 'ev-old-auth',
    pendingIds: [],
    recovered: true,
    currentStep: 'Add a token expiry test',
  });
  assert.equal(leftover, '');
  const live = liveEvidenceBinding({
    binding: 'ev-pending-1',
    pendingIds: ['ev-pending-1'],
    recovered: true,
    currentStep: 'Keep one auth check',
  });
  assert.equal(live, 'ev-pending-1');
  const orientation = derivePlanOrientation({
    hasFormalPlan: true,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Add a token expiry test',
    evidenceBinding: 'ev-old-auth',
    pendingEvidenceIds: [],
    pendingEvidenceCount: 0,
    language: 'en-US',
  });
  assert.equal(orientation.primaryAction, 'continue_step');
  assert.notEqual(orientation.primaryAction, 'adopt_evidence');
  assert.doesNotMatch(orientation.nextStep, /ev-old-auth/);
});

test('after advance previous adopted evidence is history not live review', () => {
  const scoped = scopeEvidenceQueueToRuntimeStep({
    recovered: true,
    currentStep: 'Add a token expiry test',
    queue: {
      pending: [],
      deferred: [],
      adopted: [
        {
          id: 'ev-old-auth',
          concepts: ['Keep one auth check'],
        },
      ],
      rejected: [],
      totalCount: 1,
    },
  });
  assert.deepEqual(scoped.pending, []);
  assert.deepEqual(scoped.adopted, []);
  assert.equal(scoped.history[0]?.id, 'ev-old-auth');
  const orientation = derivePlanOrientation({
    hasFormalPlan: true,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Add a token expiry test',
    pendingEvidenceCount: scoped.pending.length,
    verifyMethod: [],
    language: 'en-US',
  });
  assert.equal(orientation.primaryAction, 'continue_step');
  assert.notEqual(orientation.primaryAction, 'adopt_evidence');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
});

test('advanced recovered empty verify does not keep old verify or invent adopt', () => {
  const items = lockRecoveredPlanVerifyItems({
    recovered: true,
    currentStep: 'Add a token expiry test',
    verifyMethod: [],
    fallbacks: [
      ['Run the focused auth check'],
      ['I ran the focused auth check on the login path.'],
      ['Review the odd status mapping.'],
    ],
  });
  assert.deepEqual(items, []);
  assert.ok(!items.includes('Run the focused auth check'));
  const unlocked = lockRecoveredPlanVerifyItems({
    recovered: false,
    currentStep: 'Keep one auth check',
    verifyMethod: [],
    fallbacks: [['Run the focused auth check']],
  });
  assert.deepEqual(unlocked, ['Run the focused auth check']);
  const orientation = derivePlanOrientation({
    hasFormalPlan: true,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Add a token expiry test',
    verifyMethod: [],
    pendingEvidenceCount: 0,
    language: 'en-US',
  });
  assert.equal(orientation.primaryAction, 'continue_step');
  assert.notEqual(orientation.primaryAction, 'adopt_evidence');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
  assert.ok(!orientation.nextStep.includes('Run the focused auth check'));
  const waitingEmpty = derivePlanOrientation({
    hasFormalPlan: true,
    recoveredRuntime: true,
    resumeState: 'waiting',
    currentStep: 'Add a token expiry test',
    verifyMethod: [],
    pendingEvidenceCount: 0,
    language: 'en-US',
  });
  assert.equal(waitingEmpty.primaryAction, 'wait');
  assert.notEqual(waitingEmpty.primaryAction, 'adopt_evidence');
});

test('formal plan old why loses to advanced recovered runtime', () => {
  const facts = preferRecoveredPlanRuntimeFacts({
    recovered: true,
    runtime: {
      currentStep: 'Add a token expiry test',
      whyNow: '',
      nextAfterCurrent: '',
      blockedReason: '',
      verifyMethod: [],
    },
    plan: {
      currentStep: 'Keep one auth check',
      whyNow: 'Expired tokens still leak the session.',
      nextAfterCurrent: 'Add a token expiry test',
      blockedReason: 'The auth guard still fails on expired tokens.',
      verifyMethod: ['Run the focused auth check'],
    },
  });
  assert.equal(facts.currentStep, 'Add a token expiry test');
  assert.equal(facts.whyNow, undefined);
  assert.notEqual(facts.whyNow, 'Expired tokens still leak the session.');
  assert.equal(facts.nextAfterCurrent, undefined);
  assert.deepEqual(facts.verifyMethod, []);
  const cleared = derivePlanOrientation({
    hasFormalPlan: true,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: facts.currentStep,
    whyNow: facts.whyNow,
    nextAfterCurrent: facts.nextAfterCurrent,
    verifyMethod: facts.verifyMethod,
    language: 'en-US',
  });
  assert.equal(cleared.state, 'working');
  assert.equal(cleared.objectLabel, 'Add a token expiry test');
  assert.notEqual(cleared.objectLabel, 'Keep one auth check');
  assert.notEqual(cleared.why, 'Expired tokens still leak the session.');
  assert.equal(cleared.why, 'This is the current mainline step.');
  assert.equal(cleared.primaryAction, 'continue_step');
  assert.notEqual(cleared.primaryAction, 'generate_plan');
  const structured = preferRecoveredPlanRuntimeFacts({
    recovered: true,
    runtime: {
      currentStep: 'Add a token expiry test',
      whyNow: 'Expiry cases still skip the refresh path.',
    },
    plan: {
      currentStep: 'Keep one auth check',
      whyNow: 'Expired tokens still leak the session.',
    },
  });
  assert.equal(structured.whyNow, 'Expiry cases still skip the refresh path.');
  assert.notEqual(structured.whyNow, 'Expired tokens still leak the session.');
});

test('leftover formal plan is not live when recovered current_step is empty', () => {
  const leftoverTitle = 'Keep the current stage';
  const leftoverStep = 'Keep one auth check';
  const leftoverWhy = 'Keep the leftover why';
  const leftoverBlocked = 'Keep the leftover blocker';
  const emptyIdentity = {
    recovered: true,
    runtimeCurrentStep: '',
    planCurrentStep: leftoverStep,
    runtimePlanId: '',
    planId: 'plan-formal-old',
  };
  assert.equal(formalPlanIsLiveRuntimeIdentity(emptyIdentity), false);
  assert.equal(liveFormalPlanFrozen({ ...emptyIdentity, frozen: true }), false);
  assert.equal(liveFormalPlanTitle({ ...emptyIdentity, planTitle: leftoverTitle }), '');
  assert.notEqual(liveFormalPlanTitle({ ...emptyIdentity, planTitle: leftoverTitle }), leftoverTitle);
  assert.equal(
    liveFormalPlanSummary({
      ...emptyIdentity,
      planSummary: 'Leftover formal summary of the old stage path',
    }),
    '',
  );
  assert.equal(
    formalTaskIsLiveRuntimeIdentity({
      recovered: true,
      runtimeCurrentStep: '',
      taskTitle: leftoverTitle,
    }),
    false,
  );
  const facts = preferRecoveredPlanRuntimeFacts({
    recovered: true,
    runtime: {
      currentStep: '',
      whyNow: leftoverWhy,
      nextAfterCurrent: leftoverStep,
      blockedReason: leftoverBlocked,
      verifyMethod: ['Keep the leftover verify'],
    },
    plan: {
      currentStep: leftoverStep,
      whyNow: leftoverWhy,
      nextAfterCurrent: leftoverStep,
      blockedReason: leftoverBlocked,
      verifyMethod: ['Keep the leftover verify'],
    },
  });
  assert.equal(facts.currentStep, undefined);
  assert.equal(facts.whyNow, undefined);
  assert.equal(facts.blockedReason, undefined);
  assert.deepEqual(facts.verifyMethod, []);
  const orientation = derivePlanOrientation({
    hasFormalPlan: true,
    frozen: true,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: facts.currentStep,
    planCurrentStep: leftoverStep,
    planId: 'plan-formal-old',
    runtimePlanId: '',
    whyNow: facts.whyNow,
    blockedReason: leftoverBlocked,
    verifyMethod: facts.verifyMethod,
    language: 'en-US',
  });
  assert.notEqual(orientation.objectLabel, leftoverTitle);
  assert.notEqual(orientation.objectLabel, leftoverStep);
  assert.notEqual(orientation.why, leftoverWhy);
  assert.notEqual(orientation.why, leftoverBlocked);
  assert.equal(orientation.primaryAction, 'wait');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
  assert.notEqual(orientation.primaryAction, 'open_plan');
  assert.notEqual(orientation.primaryAction, 'continue_step');
  assert.notEqual(orientation.primaryAction, 'unfreeze_plan');
  const live = {
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    planCurrentStep: leftoverStep,
    runtimePlanId: '',
    planId: 'plan-formal-old',
  };
  assert.equal(formalPlanIsLiveRuntimeIdentity(live), false);
  assert.equal(
    liveFormalPlanTitle({ ...live, planTitle: leftoverTitle }),
    'Add a token expiry test',
  );
  const matchingStepWithoutPlanId = {
    recovered: true,
    runtimeCurrentStep: leftoverStep,
    planCurrentStep: leftoverStep,
    runtimePlanId: '',
    planId: 'plan-formal-old',
  };
  assert.equal(formalPlanIsLiveRuntimeIdentity(matchingStepWithoutPlanId), false);
  assert.equal(
    liveFormalPlanTitle({ ...matchingStepWithoutPlanId, planTitle: leftoverTitle }),
    leftoverStep,
  );
  const stillOnPlan = {
    recovered: true,
    runtimeCurrentStep: leftoverStep,
    planCurrentStep: leftoverStep,
    runtimePlanId: 'plan-formal-old',
    planId: 'plan-formal-old',
  };
  assert.equal(formalPlanIsLiveRuntimeIdentity(stillOnPlan), true);
  assert.equal(liveFormalPlanTitle({ ...stillOnPlan, planTitle: leftoverTitle }), leftoverTitle);
  const emptyChrome = resolveLivePlanStageChrome({
    ...emptyIdentity,
    planStageTitle: leftoverTitle,
    planStageGoal: leftoverStep,
  });
  assert.equal(emptyChrome.liveCurrent, '');
  assert.equal(emptyChrome.stageIsCurrent, false);
});

test('leftover current_task and Coach chrome are not live when recovered current_step is empty', () => {
  const leftoverTask = 'Ship one auth check';
  const leftoverGuide = 'Keep the leftover A implementation step';
  const leftoverFocus = 'Keep the leftover A coach focus';
  const leftoverActiveTask = leftoverTask;
  const emptyRecovered = {
    recovered: true,
    runtimeCurrentStep: '',
    taskTitle: leftoverTask,
    ideaSummary: 'Keep the leftover A implementation idea',
    scopeBoundary: leftoverGuide,
    guideCurrentStep: leftoverGuide,
    teachingGoal: leftoverTask,
    successSignal: leftoverGuide,
    fallbackStep: leftoverGuide,
    currentFocus: leftoverFocus,
    activeTask: leftoverActiveTask,
    nextStep: leftoverGuide,
    activeStage: leftoverFocus,
  };
  assert.equal(leftoverTaskGuideFocusIsNotLive(emptyRecovered), true);
  assert.equal(
    formalTaskIsLiveRuntimeIdentity({
      recovered: true,
      runtimeCurrentStep: '',
      taskTitle: leftoverTask,
    }),
    false,
  );
  const emptyChrome = preferRecoveredCoachTaskChrome(emptyRecovered);
  assert.equal(emptyChrome.liveTaskTitle, '');
  assert.equal(emptyChrome.currentStep, undefined);
  assert.equal(emptyChrome.scopeBoundary, undefined);
  assert.equal(emptyChrome.currentFocus, undefined);
  assert.equal(emptyChrome.activeTask, undefined);
  assert.notEqual(emptyChrome.liveTaskTitle, leftoverTask);
  assert.notEqual(emptyChrome.currentStep, leftoverGuide);
  assert.notEqual(emptyChrome.activeTask, leftoverActiveTask);
  const live = preferRecoveredCoachTaskChrome({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    taskTitle: leftoverTask,
    guideCurrentStep: leftoverGuide,
    currentFocus: leftoverFocus,
    activeTask: leftoverActiveTask,
  });
  assert.equal(live.liveTaskTitle, '');
  assert.equal(live.currentStep, undefined);
  assert.equal(live.currentFocus, undefined);
  assert.equal(live.activeTask, undefined);
  assert.notEqual(live.activeTask, leftoverActiveTask);
  const matching = preferRecoveredCoachTaskChrome({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    taskTitle: 'Add a token expiry test',
    guideCurrentStep: 'Add a token expiry test',
    currentFocus: 'Add a token expiry test',
    activeTask: 'Add a token expiry test',
  });
  assert.equal(matching.liveTaskTitle, 'Add a token expiry test');
  assert.equal(matching.currentStep, 'Add a token expiry test');
  assert.equal(matching.currentFocus, 'Add a token expiry test');
  assert.equal(matching.activeTask, 'Add a token expiry test');
});

test('leftover coachTurn coachingState and evaluation nextStep are not live when recovered current_step is empty', () => {
  const leftoverTurn = 'Keep the leftover A coach turn next';
  const leftoverState = 'Stay on leftover A';
  const leftoverEval = 'Stay on leftover A eval';
  const leftoverSummary = 'Keep the leftover A coach turn summary';
  const leftoverResume = 'Keep the leftover A resume thread';
  const leftoverSupport = 'Keep the leftover A support strategy';
  const leftoverReview = 'Keep the leftover A review queue';
  const leftoverTeaser = 'Keep the leftover A artifact teaser';
  const leftoverRationale = 'Keep the leftover A artifact rationale';
  const leftoverContinuity = 'Keep the leftover A coach focus summary';
  const leftoverJudgment = 'Keep the leftover A coach judgment';
  const leftoverJudgmentGoal = 'Ship leftover A';
  const emptyRecovered = {
    recovered: true,
    runtimeCurrentStep: '',
    coachTurnNextStep: leftoverTurn,
    coachTurnSummary: leftoverSummary,
    coachTurnTeachingGoal: leftoverTurn,
    coachingStateNextStep: leftoverState,
    coachingStateSummary: leftoverSummary,
    evaluationNextStep: leftoverEval,
    nextStepHintTitle: leftoverTurn,
    nextStepHintSummary: leftoverState,
    resumeThread: leftoverResume,
    supportStrategy: leftoverSupport,
    reviewQueueSummary: leftoverReview,
    artifactTeaser: leftoverTeaser,
    artifactRationale: leftoverRationale,
    continuitySummary: leftoverContinuity,
    coachJudgmentSummary: leftoverJudgment,
    coachJudgmentTeachingGoal: leftoverJudgmentGoal,
  };
  assert.equal(leftoverCoachTurnChromeIsNotLive(emptyRecovered), true);
  const emptyChrome = preferRecoveredCoachTurnChrome(emptyRecovered);
  assert.equal(emptyChrome.coachTurnNextStep, undefined);
  assert.equal(emptyChrome.coachingStateNextStep, undefined);
  assert.equal(emptyChrome.evaluationNextStep, undefined);
  assert.equal(emptyChrome.nextStepHintTitle, undefined);
  assert.equal(emptyChrome.resumeThread, undefined);
  assert.equal(emptyChrome.supportStrategy, undefined);
  assert.equal(emptyChrome.reviewQueueSummary, undefined);
  assert.equal(emptyChrome.artifactTeaser, undefined);
  assert.equal(emptyChrome.artifactRationale, undefined);
  assert.equal(emptyChrome.continuitySummary, undefined);
  assert.equal(emptyChrome.coachJudgmentSummary, undefined);
  assert.equal(emptyChrome.coachJudgmentTeachingGoal, undefined);
  assert.notEqual(emptyChrome.coachTurnNextStep, leftoverTurn);
  assert.notEqual(emptyChrome.coachingStateNextStep, leftoverState);
  assert.notEqual(emptyChrome.evaluationNextStep, leftoverEval);
  assert.notEqual(emptyChrome.resumeThread, leftoverResume);
  assert.notEqual(emptyChrome.supportStrategy, leftoverSupport);
  assert.notEqual(emptyChrome.reviewQueueSummary, leftoverReview);
  assert.notEqual(emptyChrome.artifactTeaser, leftoverTeaser);
  assert.notEqual(emptyChrome.artifactRationale, leftoverRationale);
  assert.notEqual(emptyChrome.continuitySummary, leftoverContinuity);
  assert.notEqual(emptyChrome.coachJudgmentSummary, leftoverJudgment);
  assert.notEqual(emptyChrome.coachJudgmentTeachingGoal, leftoverJudgmentGoal);
  const live = preferRecoveredCoachTurnChrome({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    coachTurnNextStep: leftoverTurn,
    coachingStateNextStep: leftoverState,
    evaluationNextStep: leftoverEval,
    resumeThread: leftoverResume,
    supportStrategy: leftoverSupport,
    reviewQueueSummary: leftoverReview,
    artifactTeaser: leftoverTeaser,
    artifactRationale: leftoverRationale,
    continuitySummary: leftoverContinuity,
    coachJudgmentSummary: leftoverJudgment,
    coachJudgmentTeachingGoal: leftoverJudgmentGoal,
  });
  assert.equal(live.coachTurnNextStep, undefined);
  assert.equal(live.coachingStateNextStep, undefined);
  assert.equal(live.evaluationNextStep, undefined);
  assert.equal(live.resumeThread, undefined);
  assert.equal(live.supportStrategy, undefined);
  assert.equal(live.reviewQueueSummary, undefined);
  assert.equal(live.artifactTeaser, undefined);
  assert.equal(live.artifactRationale, undefined);
  assert.equal(live.continuitySummary, undefined);
  assert.equal(live.coachJudgmentSummary, undefined);
  assert.equal(live.coachJudgmentTeachingGoal, undefined);
  const matching = preferRecoveredCoachTurnChrome({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    coachTurnNextStep: 'Add a token expiry test',
    coachingStateNextStep: 'Add a token expiry test',
    evaluationNextStep: 'Add a token expiry test',
    resumeThread: 'Add a token expiry test',
    supportStrategy: 'Add a token expiry test',
    reviewQueueSummary: 'Add a token expiry test',
    artifactTeaser: 'Add a token expiry test',
    artifactRationale: 'Add a token expiry test',
    continuitySummary: 'Add a token expiry test',
    coachJudgmentSummary: 'Add a token expiry test',
    coachJudgmentTeachingGoal: 'Add a token expiry test',
  });
  assert.equal(matching.coachTurnNextStep, 'Add a token expiry test');
  assert.equal(matching.coachingStateNextStep, 'Add a token expiry test');
  assert.equal(matching.evaluationNextStep, 'Add a token expiry test');
  assert.equal(matching.resumeThread, 'Add a token expiry test');
  assert.equal(matching.supportStrategy, 'Add a token expiry test');
  assert.equal(matching.reviewQueueSummary, 'Add a token expiry test');
  assert.equal(matching.artifactTeaser, 'Add a token expiry test');
  assert.equal(matching.artifactRationale, 'Add a token expiry test');
  assert.equal(matching.continuitySummary, 'Add a token expiry test');
  assert.equal(matching.coachJudgmentSummary, 'Add a token expiry test');
  assert.equal(matching.coachJudgmentTeachingGoal, 'Add a token expiry test');
});

test('leftover teachingDecision.focusArea and learnerState.activeFocus are not live when recovered current_step is empty', () => {
  const leftoverFocus = 'Keep the leftover A teaching focus';
  const leftoverLearner = 'Keep the leftover A learner focus';
  const leftoverLearning = 'Keep the leftover A learning focus';
  const leftoverCard = 'Keep the leftover A card focus';
  const emptyRecovered = {
    recovered: true,
    runtimeCurrentStep: '',
    teachingDecisionFocusArea: leftoverFocus,
    learnerStateActiveFocus: leftoverLearner,
    latestLearningFocusArea: leftoverLearning,
    cardFocusArea: leftoverCard,
  };
  assert.equal(leftoverTrainingFocusChromeIsNotLive(emptyRecovered), true);
  const emptyChrome = preferRecoveredTrainingFocusChrome(emptyRecovered);
  assert.equal(emptyChrome.teachingDecisionFocusArea, undefined);
  assert.equal(emptyChrome.learnerStateActiveFocus, undefined);
  assert.equal(emptyChrome.latestLearningFocusArea, undefined);
  assert.equal(emptyChrome.cardFocusArea, undefined);
  assert.notEqual(emptyChrome.teachingDecisionFocusArea, leftoverFocus);
  assert.notEqual(emptyChrome.learnerStateActiveFocus, leftoverLearner);
  assert.notEqual(emptyChrome.latestLearningFocusArea, leftoverLearning);
  assert.notEqual(emptyChrome.cardFocusArea, leftoverCard);
  const live = preferRecoveredTrainingFocusChrome({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    teachingDecisionFocusArea: leftoverFocus,
    learnerStateActiveFocus: leftoverLearner,
    latestLearningFocusArea: leftoverLearning,
    cardFocusArea: leftoverCard,
  });
  assert.equal(live.teachingDecisionFocusArea, undefined);
  assert.equal(live.learnerStateActiveFocus, undefined);
  assert.equal(live.latestLearningFocusArea, undefined);
  assert.equal(live.cardFocusArea, undefined);
  const matching = preferRecoveredTrainingFocusChrome({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    teachingDecisionFocusArea: 'Add a token expiry test',
    learnerStateActiveFocus: 'Add a token expiry test',
    latestLearningFocusArea: 'Add a token expiry test',
    cardFocusArea: 'Add a token expiry test',
  });
  assert.deepEqual(matching, {});
});

test('leftover training handoff card chrome is not live when recovered current_step is empty', () => {
  const leftoverSignal = 'Keep the leftover A success signal';
  const leftoverReturn = 'Keep the leftover A return with';
  const leftoverCard = 'Keep the leftover A handoff card';
  const leftoverSelected = 'Review the leftover A selected card';
  const leftoverFollowup = 'Keep the leftover A learning followup';
  const leftoverBlocker = 'Keep the leftover A learning blocker';
  const leftoverSummary = 'Keep the leftover A handoff summary';
  const leftoverNextAfter = 'Keep the leftover A next after completion';
  const leftoverFallback = 'Keep the leftover A fallback action';
  const leftoverNextHopTitle = 'Keep the leftover A next hop title';
  const leftoverNextHopCard = 'Keep the leftover A next hop card';
  const leftoverWhy = 'Keep the leftover A why this card';
  const leftoverReturnSummary = 'Keep the leftover A return summary';
  const leftoverNextHopSummary = 'Keep the leftover A next hop summary';
  const leftoverNextHopWhy = 'Keep the leftover A next hop why';
  const leftoverResourceTitle = 'Workspace A notes';
  const emptyRecovered = {
    recovered: true,
    runtimeCurrentStep: '',
    successSignal: leftoverSignal,
    returnWith: leftoverReturn,
    cardTitle: leftoverCard,
    selectedCardTitle: leftoverSelected,
    followup: leftoverFollowup,
    blocker: leftoverBlocker,
    handoffSummary: leftoverSummary,
    nextAfterCompletion: leftoverNextAfter,
    fallbackAction: leftoverFallback,
    nextHopTitle: leftoverNextHopTitle,
    nextHopCardTitle: leftoverNextHopCard,
    nextHopHandoffSummary: leftoverSummary,
    nextHopNextAfterCompletion: leftoverNextAfter,
    nextHopFallbackAction: leftoverFallback,
    routingNextAfterCompletion: leftoverNextAfter,
    routingFallbackAction: leftoverFallback,
    whyThisCard: leftoverWhy,
    ledgerWhyThisCard: leftoverWhy,
    returnSummary: leftoverReturnSummary,
    nextHopReturnSummary: leftoverReturnSummary,
    nextHopSummary: leftoverNextHopSummary,
    nextHopWhyNow: leftoverNextHopWhy,
  };
  assert.equal(leftoverTrainingHandoffChromeIsNotLive(emptyRecovered), true);
  const emptyChrome = preferRecoveredTrainingHandoffChrome(emptyRecovered);
  assert.equal(emptyChrome.successSignal, undefined);
  assert.equal(emptyChrome.returnWith, undefined);
  assert.equal(emptyChrome.cardTitle, undefined);
  assert.equal(emptyChrome.selectedCardTitle, undefined);
  assert.equal(emptyChrome.followup, undefined);
  assert.equal(emptyChrome.blocker, undefined);
  assert.equal(emptyChrome.handoffSummary, undefined);
  assert.equal(emptyChrome.nextAfterCompletion, undefined);
  assert.equal(emptyChrome.fallbackAction, undefined);
  assert.equal(emptyChrome.nextHopTitle, undefined);
  assert.equal(emptyChrome.nextHopCardTitle, undefined);
  assert.equal(emptyChrome.nextHopHandoffSummary, undefined);
  assert.equal(emptyChrome.nextHopNextAfterCompletion, undefined);
  assert.equal(emptyChrome.nextHopFallbackAction, undefined);
  assert.equal(emptyChrome.routingNextAfterCompletion, undefined);
  assert.equal(emptyChrome.routingFallbackAction, undefined);
  assert.equal(emptyChrome.whyThisCard, undefined);
  assert.equal(emptyChrome.returnSummary, undefined);
  assert.equal(emptyChrome.nextHopSummary, undefined);
  assert.equal(emptyChrome.nextHopWhyNow, undefined);
  assert.notEqual(emptyChrome.whyThisCard, leftoverWhy);
  assert.notEqual(emptyChrome.returnSummary, leftoverReturnSummary);
  assert.notEqual(emptyChrome.nextHopSummary, leftoverNextHopSummary);
  assert.equal(leftoverResourceSelectedDetailIsNotLive(emptyRecovered), true);
  assert.equal(leftoverResourceSandboxPreviewIsNotLive(emptyRecovered), true);
  assert.equal(leftoverResourceSandboxStateIsNotLive(emptyRecovered), true);
  assert.equal(leftoverResourceLibraryListIsNotLive(emptyRecovered), true);
  assert.equal(leftoverCoachConversationIsNotLive(emptyRecovered), true);
  assert.equal(leftoverSuggestedActionsIsNotLive(emptyRecovered), true);
  assert.equal(
    leftoverMintingSuggestedActionsAreNotLive({
      recovered: true,
      runtimeCurrentStep: '',
      planId: 'plan-formal-old',
      runtimePlanId: '',
      taskTitle: 'Keep one auth check',
    }),
    true,
  );
  assert.equal(leftoverFirstLookHeadlineIsNotLive(emptyRecovered), true);
  assert.equal(leftoverEvaluationHeadlineIsNotLive(emptyRecovered), true);
  assert.equal(leftoverStreamingCheckpointIsNotLive(emptyRecovered), true);
  assert.equal(leftoverTransferSkillIsNotLive(emptyRecovered), true);
  assert.equal(leftoverSettingsProfileRhythmIsNotLive(emptyRecovered), true);
  assert.equal(leftoverSettingsLearnerProjectOnboardingIsNotLive(emptyRecovered), true);
  const leftoverRhythm = 'Keep the leftover A rhythm';
  const leftoverLearningMode = 'Keep the leftover A learning mode';
  const leftoverScope = 'personal';
  const leftoverCadence = 'active';
  const emptySettings = preferRecoveredSettingsProfileRhythm({
    ...emptyRecovered,
    preferredRhythm: leftoverRhythm,
    preferredLearningMode: leftoverLearningMode,
    memoryScope: leftoverScope,
    reviewCadence: leftoverCadence,
    workingSetMode: 'broad',
    reviewReminderMode: 'ahead',
  });
  assert.equal(emptySettings.preferredRhythm, undefined);
  assert.equal(emptySettings.memoryScope, undefined);
  assert.equal(emptySettings.reviewCadence, undefined);
  assert.notEqual(emptySettings.preferredRhythm, leftoverRhythm);
  assert.notEqual(emptySettings.memoryScope, leftoverScope);
  assert.notEqual(emptySettings.reviewCadence, leftoverCadence);
  const leftoverLearner = 'Keep the leftover A learner';
  const leftoverOnboarding = 'Keep the leftover A onboarding';
  const leftoverProject = 'Keep the leftover A project context';
  const emptyLearnerProject = preferRecoveredSettingsLearnerProjectOnboarding({
    ...emptyRecovered,
    learnerName: leftoverLearner,
    targetProject: leftoverProject,
    onboardingRequest: leftoverOnboarding,
    projectContext: leftoverProject,
  });
  assert.equal(emptyLearnerProject.learnerName, undefined);
  assert.equal(emptyLearnerProject.targetProject, undefined);
  assert.equal(emptyLearnerProject.onboardingRequest, undefined);
  assert.equal(emptyLearnerProject.projectContext, undefined);
  assert.notEqual(emptyLearnerProject.learnerName, leftoverLearner);
  assert.notEqual(emptyLearnerProject.onboardingRequest, leftoverOnboarding);
  const emptyResource = preferRecoveredResourceSelectedDetail({
    ...emptyRecovered,
    title: leftoverResourceTitle,
    summary: leftoverNextHopSummary,
    matchSummary: leftoverNextHopSummary,
  });
  assert.equal(emptyResource.title, undefined);
  assert.notEqual(emptyResource.title, leftoverResourceTitle);
  assert.notEqual(emptyChrome.successSignal, leftoverSignal);
  assert.notEqual(emptyChrome.returnWith, leftoverReturn);
  assert.notEqual(emptyChrome.cardTitle, leftoverCard);
  assert.notEqual(emptyChrome.selectedCardTitle, leftoverSelected);
  assert.notEqual(emptyChrome.followup, leftoverFollowup);
  assert.notEqual(emptyChrome.blocker, leftoverBlocker);
  assert.notEqual(emptyChrome.handoffSummary, leftoverSummary);
  assert.notEqual(emptyChrome.nextAfterCompletion, leftoverNextAfter);
  assert.notEqual(emptyChrome.fallbackAction, leftoverFallback);
  assert.notEqual(emptyChrome.nextHopTitle, leftoverNextHopTitle);
  assert.notEqual(emptyChrome.nextHopCardTitle, leftoverNextHopCard);
  const live = preferRecoveredTrainingHandoffChrome({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    successSignal: leftoverSignal,
    returnWith: leftoverReturn,
    cardTitle: leftoverCard,
    selectedCardTitle: leftoverSelected,
    followup: leftoverFollowup,
    blocker: leftoverBlocker,
    handoffSummary: leftoverSummary,
    nextAfterCompletion: leftoverNextAfter,
    fallbackAction: leftoverFallback,
    nextHopTitle: leftoverNextHopTitle,
    nextHopCardTitle: leftoverNextHopCard,
    nextHopNextAfterCompletion: leftoverNextAfter,
    nextHopFallbackAction: leftoverFallback,
  });
  assert.equal(leftoverSettingsProfileRhythmIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
  }), true);
  assert.equal(leftoverSettingsLearnerProjectOnboardingIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
  }), true);
  const liveSettings = preferRecoveredSettingsProfileRhythm({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    preferredRhythm: leftoverRhythm,
    preferredLearningMode: leftoverLearningMode,
    memoryScope: leftoverScope,
    reviewCadence: leftoverCadence,
    workingSetMode: 'broad',
    reviewReminderMode: 'ahead',
  });
  assert.equal(liveSettings.preferredRhythm, undefined);
  assert.notEqual(liveSettings.preferredRhythm, leftoverRhythm);
  assert.notEqual(liveSettings.memoryScope, leftoverScope);
  assert.notEqual(liveSettings.reviewCadence, leftoverCadence);
  const liveLearnerProject = preferRecoveredSettingsLearnerProjectOnboarding({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    learnerName: leftoverLearner,
    targetProject: leftoverProject,
    onboardingRequest: leftoverOnboarding,
    projectContext: leftoverProject,
  });
  assert.equal(liveLearnerProject.learnerName, undefined);
  assert.notEqual(liveLearnerProject.learnerName, leftoverLearner);
  assert.notEqual(liveLearnerProject.onboardingRequest, leftoverOnboarding);
  assert.equal(leftoverResourceSandboxPreviewIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
  }), true);
  assert.equal(leftoverResourceSandboxStateIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
  }), true);
  assert.equal(leftoverResourceLibraryListIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
  }), true);
  assert.equal(leftoverTrainingHandoffChromeIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    runtimePlanId: '',
    planId: 'plan-formal-old',
    planCurrentStep: leftoverCard,
  }), true);
  assert.equal(leftoverTrainingFocusChromeIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    runtimePlanId: '',
    planId: 'plan-formal-old',
    planCurrentStep: leftoverCard,
  }), true);
  assert.equal(leftoverResourceSandboxPreviewIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    runtimePlanId: '',
    planId: 'plan-formal-old',
    planCurrentStep: leftoverCard,
  }), true);
  assert.deepEqual(
    preferRecoveredTrainingHandoffChrome({
      recovered: true,
      runtimeCurrentStep: 'Add a token expiry test',
      runtimePlanId: '',
      planId: 'plan-formal-old',
      planCurrentStep: leftoverCard,
      cardTitle: leftoverCard,
      selectedCardTitle: leftoverSelected,
      successSignal: leftoverSignal,
    }),
    {},
  );
  assert.equal(leftoverTrainingHandoffChromeIsNotLive({
    recovered: true,
    runtimeCurrentStep: leftoverCard,
    planCurrentStep: leftoverCard,
  }), true);
  assert.equal(leftoverTrainingHandoffChromeIsNotLive({
    recovered: true,
    runtimeCurrentStep: leftoverCard,
    runtimePlanId: 'plan-formal-old',
    planId: 'plan-formal-old',
    planCurrentStep: leftoverCard,
  }), false);
  assert.equal(leftoverResourceLibraryListIsNotLive({
    recovered: true,
    runtimeCurrentStep: leftoverCard,
    runtimePlanId: 'plan-formal-old',
    planId: 'plan-formal-old',
    planCurrentStep: leftoverCard,
  }), true);
  const stillLiveMatching = preferRecoveredTrainingHandoffChrome({
    recovered: true,
    runtimeCurrentStep: leftoverCard,
    runtimePlanId: 'plan-formal-old',
    planId: 'plan-formal-old',
    planCurrentStep: leftoverCard,
    successSignal: leftoverCard,
    cardTitle: leftoverCard,
    selectedCardTitle: leftoverCard,
  });
  assert.equal(stillLiveMatching.successSignal, leftoverCard);
  assert.equal(stillLiveMatching.cardTitle, leftoverCard);
  assert.equal(leftoverCoachConversationIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
  }), false);
  assert.equal(leftoverSuggestedActionsIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
  }), false);
  assert.equal(
    leftoverMintingSuggestedActionsAreNotLive({
      recovered: true,
      runtimeCurrentStep: 'Add a token expiry test',
      planCurrentStep: 'Keep one auth check',
      planId: 'plan-formal-old',
      runtimePlanId: '',
      taskTitle: 'Keep one auth check',
    }),
    true,
  );
  assert.equal(
    leftoverMintingSuggestedActionsAreNotLive({
      recovered: true,
      runtimeCurrentStep: 'Inspect one refresh boundary',
      planCurrentStep: 'Inspect one refresh boundary',
      planId: 'plan-live',
      runtimePlanId: 'plan-live',
      taskTitle: 'Inspect one refresh boundary',
    }),
    false,
  );
  assert.equal(leftoverFirstLookHeadlineIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
  }), false);
  assert.equal(leftoverEvaluationHeadlineIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
  }), false);
  assert.equal(leftoverStreamingCheckpointIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
  }), false);
  assert.equal(leftoverTransferSkillIsNotLive({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
  }), false);
  assert.equal(live.successSignal, undefined);
  assert.equal(live.returnWith, undefined);
  assert.equal(live.cardTitle, undefined);
  assert.equal(live.selectedCardTitle, undefined);
  assert.equal(live.followup, undefined);
  assert.equal(live.blocker, undefined);
  assert.equal(live.handoffSummary, undefined);
  assert.equal(live.nextAfterCompletion, undefined);
  assert.equal(live.fallbackAction, undefined);
  assert.equal(live.nextHopTitle, undefined);
  assert.equal(live.nextHopCardTitle, undefined);
  const matching = preferRecoveredTrainingHandoffChrome({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    successSignal: 'Add a token expiry test',
    returnWith: 'Add a token expiry test',
    cardTitle: 'Add a token expiry test',
    selectedCardTitle: 'Add a token expiry test',
    followup: 'Add a token expiry test',
    blocker: 'Add a token expiry test',
    handoffSummary: 'Add a token expiry test',
    nextAfterCompletion: 'Add a token expiry test',
    fallbackAction: 'Add a token expiry test',
    nextHopTitle: 'Add a token expiry test',
    nextHopCardTitle: 'Add a token expiry test',
    nextHopHandoffSummary: 'Add a token expiry test',
    nextHopNextAfterCompletion: 'Add a token expiry test',
    nextHopFallbackAction: 'Add a token expiry test',
    routingNextAfterCompletion: 'Add a token expiry test',
    routingFallbackAction: 'Add a token expiry test',
    whyThisCard: 'Add a token expiry test',
    ledgerWhyThisCard: 'Add a token expiry test',
    returnSummary: 'Add a token expiry test',
    nextHopReturnSummary: 'Add a token expiry test',
    nextHopSummary: 'Add a token expiry test',
    nextHopWhyNow: 'Add a token expiry test',
  });
  assert.deepEqual(matching, {});
  const matchingResource = preferRecoveredResourceSelectedDetail({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    title: 'Add a token expiry test',
    summary: 'Add a token expiry test',
    matchSummary: 'Add a token expiry test',
  });
  assert.deepEqual(matchingResource, {});
});

test('leftover one-scene transferable is not live when recovered current_step is empty', () => {
  const leftoverConcept = 'Keep the leftover A transfer skill';
  const leftoverWhy = 'Keep the leftover A transfer why';
  const leftoverNext = 'Keep the leftover A transfer next';
  const leftover = {
    concept: leftoverConcept,
    state: 'transferable',
    sceneCount: 1,
    workspaceIds: ['workspace-a'],
    sceneKeys: ['default'],
    why: leftoverWhy,
    next: leftoverNext,
  };
  assert.equal(leftoverTransferSkillHasRealMultiSceneProof(leftover), false);
  const empty = preferRecoveredTransferSkill({
    recovered: true,
    runtimeCurrentStep: '',
    transfer: leftover,
  });
  assert.notEqual(empty?.state, 'transferable');
  assert.equal(empty?.state, 'awaiting_second_scene');
  assert.notEqual(empty?.next, leftoverNext);
  assert.notEqual(empty?.why, leftoverWhy);
  assert.deepEqual(empty?.workspaceIds, ['workspace-a']);
  const fakeMulti = {
    ...leftover,
    sceneCount: 2,
    workspaceIds: ['workspace-a', 'workspace-a'],
    sceneKeys: ['default', 'default'],
  };
  assert.equal(leftoverTransferSkillHasRealMultiSceneProof(fakeMulti), false);
  const fakeSceneKeys = {
    ...leftover,
    sceneCount: 2,
    workspaceIds: ['workspace-a'],
    sceneKeys: ['default', 'transfer:docs sandbox'],
  };
  assert.equal(leftoverTransferSkillHasRealMultiSceneProof(fakeSceneKeys), false);
  const demotedFake = preferRecoveredTransferSkill({
    recovered: true,
    runtimeCurrentStep: '',
    transfer: fakeMulti,
  });
  assert.equal(demotedFake?.state, 'awaiting_second_scene');
  const multi = {
    ...leftover,
    sceneCount: 2,
    workspaceIds: ['workspace-a', 'workspace-c'],
    sceneKeys: ['default', 'workspace:workspace-c'],
  };
  assert.equal(leftoverTransferSkillHasRealMultiSceneProof(multi), true);
  const kept = preferRecoveredTransferSkill({
    recovered: true,
    runtimeCurrentStep: '',
    transfer: multi,
  });
  assert.equal(kept?.state, 'transferable');
  assert.deepEqual(kept?.workspaceIds, ['workspace-a', 'workspace-c']);
  const live = preferRecoveredTransferSkill({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    transfer: leftover,
  });
  assert.equal(live?.state, 'transferable');
  assert.equal(live?.next, leftoverNext);
  const awaiting = preferRecoveredTransferSkill({
    recovered: true,
    runtimeCurrentStep: '',
    transfer: { ...leftover, state: 'awaiting_second_scene' },
  });
  assert.equal(awaiting?.state, 'awaiting_second_scene');
});

test('leftover formal frozen does not mark advanced recovered step as frozen', () => {
  const identity = {
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: '',
    planId: 'plan-formal-old',
  };
  assert.equal(formalPlanIsLiveRuntimeIdentity(identity), false);
  assert.equal(liveFormalPlanFrozen({ ...identity, frozen: true }), false);
  const stillOnPlan = {
    recovered: true,
    runtimeCurrentStep: 'Keep one auth check',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: 'plan-formal-old',
    planId: 'plan-formal-old',
  };
  assert.equal(formalPlanIsLiveRuntimeIdentity(stillOnPlan), true);
  assert.equal(liveFormalPlanFrozen({ ...stillOnPlan, frozen: true }), true);
  const orientation = derivePlanOrientation({
    hasFormalPlan: true,
    frozen: true,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    planId: 'plan-formal-old',
    runtimePlanId: '',
    language: 'en-US',
  });
  assert.equal(orientation.objectLabel, 'Add a token expiry test');
  assert.equal(orientation.primaryAction, 'continue_step');
  assert.notEqual(orientation.primaryAction, 'unfreeze_plan');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
  assert.notEqual(orientation.state, 'waiting');
});

test('leftover formal title does not label advanced recovered current_step', () => {
  const identity = {
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: '',
    planId: 'plan-formal-old',
  };
  assert.equal(
    liveFormalPlanTitle({ ...identity, planTitle: 'Keep the current stage' }),
    'Add a token expiry test',
  );
  assert.notEqual(
    liveFormalPlanTitle({ ...identity, planTitle: 'Keep the current stage' }),
    'Keep the current stage',
  );
  assert.equal(
    liveFormalPlanSummary({
      ...identity,
      planSummary: 'First finish the leftover auth stage.',
      planGoal: 'Keep one check',
    }),
    '',
  );
  const stillOnPlan = {
    recovered: true,
    runtimeCurrentStep: 'Keep one auth check',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: 'plan-formal-old',
    planId: 'plan-formal-old',
  };
  assert.equal(
    liveFormalPlanTitle({ ...stillOnPlan, planTitle: 'Keep the current stage' }),
    'Keep the current stage',
  );
  assert.equal(
    liveFormalPlanSummary({
      ...stillOnPlan,
      planSummary: 'First finish the leftover auth stage.',
    }),
    'First finish the leftover auth stage.',
  );
  const orientation = derivePlanOrientation({
    hasFormalPlan: true,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    planId: 'plan-formal-old',
    language: 'en-US',
  });
  assert.equal(orientation.objectLabel, 'Add a token expiry test');
  assert.notEqual(orientation.objectLabel, 'Keep the current stage');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
});

test('leftover formal summary does not label Training why or source after recovered advance', () => {
  const leftoverSummary = 'First finish the leftover auth stage.';
  const identity = {
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: '',
    planId: 'plan-formal-old',
  };
  assert.equal(
    liveTrainingFormalSummary({
      ...identity,
      planSummary: leftoverSummary,
      planGoal: 'Keep one check',
    }),
    '',
  );
  assert.equal(
    liveTrainingSourceFallback({ ...identity, planSummary: leftoverSummary }),
    'Add a token expiry test',
  );
  assert.notEqual(
    liveTrainingSourceFallback({ ...identity, planSummary: leftoverSummary }),
    leftoverSummary,
  );
  const stillOnPlan = {
    recovered: true,
    runtimeCurrentStep: 'Keep one auth check',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: 'plan-formal-old',
    planId: 'plan-formal-old',
  };
  assert.equal(
    liveTrainingFormalSummary({ ...stillOnPlan, planSummary: leftoverSummary }),
    leftoverSummary,
  );
  assert.equal(
    liveTrainingSourceFallback({ ...stillOnPlan, planSummary: leftoverSummary }),
    leftoverSummary,
  );
});

test('leftover formal title does not label Training card after recovered advance', () => {
  const leftoverTitle = 'Keep the current stage';
  const leftoverTask = leftoverTitle;
  const identity = {
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: '',
    planId: 'plan-formal-old',
  };
  assert.equal(formalTaskIsLiveRuntimeIdentity({
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    taskTitle: leftoverTask,
  }), false);
  assert.equal(
    liveTrainingTitleFallback({
      ...identity,
      planTitle: leftoverTitle,
      taskTitle: leftoverTask,
    }),
    'Add a token expiry test',
  );
  assert.notEqual(
    liveTrainingTitleFallback({
      ...identity,
      planTitle: leftoverTitle,
      taskTitle: leftoverTask,
    }),
    leftoverTitle,
  );
  assert.equal(
    liveTrainingTitleFallback({
      ...identity,
      runtimeCurrentStep: '',
      planTitle: leftoverTitle,
      taskTitle: leftoverTask,
    }),
    '',
  );
  const stillOnPlan = {
    recovered: true,
    runtimeCurrentStep: 'Keep one auth check',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: 'plan-formal-old',
    planId: 'plan-formal-old',
  };
  assert.equal(
    liveTrainingTitleFallback({
      ...stillOnPlan,
      planTitle: leftoverTitle,
      taskTitle: leftoverTask,
    }),
    leftoverTitle,
  );
  assert.equal(
    liveTrainingTitleFallback({
      recovered: true,
      runtimeCurrentStep: leftoverTask,
      planCurrentStep: 'Keep one auth check',
      runtimePlanId: '',
      planId: 'plan-formal-old',
      planTitle: leftoverTitle,
      taskTitle: leftoverTask,
    }),
    leftoverTask,
  );
  assert.equal(
    liveTrainingNextChallengeTitle({
      ...identity,
      planTitle: leftoverTitle,
      taskTitle: leftoverTask,
      cardTitle: `Practice: ${leftoverTitle}`,
    }),
    'Add a token expiry test',
  );
  assert.equal(
    liveTrainingNextChallengeTitle({
      ...identity,
      runtimeCurrentStep: '',
      planTitle: leftoverTitle,
      taskTitle: leftoverTask,
      cardTitle: `Practice: ${leftoverTitle}`,
    }),
    '',
  );
  assert.equal(
    liveTrainingNextChallengeTitle({
      ...stillOnPlan,
      planTitle: leftoverTitle,
      taskTitle: leftoverTask,
      cardTitle: `Practice: ${leftoverTitle}`,
    }),
    `Practice: ${leftoverTitle}`,
  );
  assert.equal(
    liveTrainingNextChallengeTitle({
      recovered: true,
      runtimeCurrentStep: 'Add a token expiry test',
      planCurrentStep: leftoverTask,
      runtimePlanId: 'plan-formal-old',
      planId: 'plan-formal-old',
      planTitle: leftoverTitle,
      taskTitle: leftoverTask,
      cardTitle: `Practice: ${leftoverTitle}`,
    }),
    'Add a token expiry test',
  );
});

test('leftover formal title does not label Training currentFocus after recovered advance', () => {
  const leftoverFocus = 'Keep the current stage';
  const identity = {
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: '',
    planId: 'plan-formal-old',
  };
  assert.equal(
    liveTrainingFocusFallback({
      ...identity,
      taskTitle: leftoverFocus,
      coachFocus: leftoverFocus,
      memoryFocus: leftoverFocus,
    }),
    'Add a token expiry test',
  );
  assert.notEqual(
    liveTrainingFocusFallback({
      ...identity,
      taskTitle: leftoverFocus,
      coachFocus: leftoverFocus,
      memoryFocus: leftoverFocus,
    }),
    leftoverFocus,
  );
  assert.equal(
    liveTrainingFocusFallback({
      ...identity,
      runtimeCurrentStep: '',
      taskTitle: leftoverFocus,
      coachFocus: leftoverFocus,
      memoryFocus: leftoverFocus,
    }),
    '',
  );
  const stillOnPlan = {
    recovered: true,
    runtimeCurrentStep: 'Keep one auth check',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: 'plan-formal-old',
    planId: 'plan-formal-old',
  };
  assert.equal(
    liveTrainingFocusFallback({
      ...stillOnPlan,
      taskTitle: leftoverFocus,
      coachFocus: leftoverFocus,
      memoryFocus: leftoverFocus,
    }),
    leftoverFocus,
  );
});

test('leftover formal title does not label Training targetSkill after recovered advance', () => {
  const leftoverTitle = 'Keep the current stage';
  const identity = {
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: '',
    planId: 'plan-formal-old',
  };
  assert.equal(
    liveTrainingTargetSkill({
      ...identity,
      taskTitle: leftoverTitle,
      cardSkill: '',
      liveFocus: leftoverTitle,
    }),
    '',
  );
  assert.notEqual(
    liveTrainingTargetSkill({
      ...identity,
      taskTitle: leftoverTitle,
      cardSkill: '',
      liveFocus: leftoverTitle,
    }),
    leftoverTitle,
  );
  assert.equal(
    liveTrainingTargetSkill({
      ...identity,
      taskTitle: leftoverTitle,
      cardSkill: 'Expiry-token coverage',
      liveFocus: leftoverTitle,
    }),
    'Expiry-token coverage',
  );
  const stillOnPlan = {
    recovered: true,
    runtimeCurrentStep: 'Keep one auth check',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: 'plan-formal-old',
    planId: 'plan-formal-old',
  };
  assert.equal(
    liveTrainingTargetSkill({
      ...stillOnPlan,
      taskTitle: leftoverTitle,
      cardSkill: '',
      liveFocus: leftoverTitle,
    }),
    leftoverTitle,
  );
});

test('leftover formal title does not label Training why-now after recovered advance', () => {
  const leftoverTitle = 'Keep the current stage';
  const identity = {
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: '',
    planId: 'plan-formal-old',
  };
  assert.equal(
    liveTrainingWhyNow({
      ...identity,
      taskTitle: leftoverTitle,
      cardWhy: '',
      liveWhy: leftoverTitle,
    }),
    '',
  );
  assert.notEqual(
    liveTrainingWhyNow({
      ...identity,
      taskTitle: leftoverTitle,
      cardWhy: '',
      liveWhy: leftoverTitle,
    }),
    leftoverTitle,
  );
  assert.equal(
    liveTrainingWhyNow({
      ...identity,
      taskTitle: leftoverTitle,
      cardWhy: 'Expiry cases still skip the refresh path.',
      liveWhy: leftoverTitle,
    }),
    'Expiry cases still skip the refresh path.',
  );
  assert.equal(
    liveTrainingWhyNow({
      recovered: true,
      runtimeCurrentStep: '',
      taskTitle: leftoverTitle,
      cardWhy: leftoverTitle,
      liveWhy: leftoverTitle,
    }),
    '',
  );
  const stillOnPlan = {
    recovered: true,
    runtimeCurrentStep: 'Keep one auth check',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: 'plan-formal-old',
    planId: 'plan-formal-old',
  };
  assert.equal(
    liveTrainingWhyNow({
      ...stillOnPlan,
      taskTitle: leftoverTitle,
      cardWhy: '',
      liveWhy: leftoverTitle,
    }),
    leftoverTitle,
  );
});

test('leftover formal title does not label Training source or coach chrome after recovered advance', () => {
  const leftoverTitle = 'Keep the current stage';
  const identity = {
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: '',
    planId: 'plan-formal-old',
  };
  assert.equal(
    liveTrainingCoachSummary({
      ...identity,
      taskTitle: leftoverTitle,
      coachSummary: leftoverTitle,
    }),
    '',
  );
  assert.notEqual(
    liveTrainingCoachSummary({
      ...identity,
      taskTitle: leftoverTitle,
      coachSummary: leftoverTitle,
    }),
    leftoverTitle,
  );
  assert.equal(
    liveTrainingSourceFallback({
      ...identity,
      planSummary: leftoverTitle,
    }),
    'Add a token expiry test',
  );
  const stillOnPlan = {
    recovered: true,
    runtimeCurrentStep: 'Keep one auth check',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: 'plan-formal-old',
    planId: 'plan-formal-old',
  };
  assert.equal(
    liveTrainingCoachSummary({
      ...stillOnPlan,
      taskTitle: leftoverTitle,
      coachSummary: leftoverTitle,
    }),
    leftoverTitle,
  );
});

test('leftover formal stages do not paint advanced recovered current_step as that path', () => {
  const leftoverStages = [
    { id: 'stage-auth', title: 'Auth', status: 'active' },
    { id: 'stage-tokens', title: 'Tokens', status: 'queued' },
  ];
  const identity = {
    recovered: true,
    runtimeCurrentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: '',
    planId: 'plan-formal-old',
  };
  assert.deepEqual(
    liveFormalPlanStages({ ...identity, stages: leftoverStages }),
    [],
  );
  assert.equal(liveFormalPlanCadence({ ...identity, cadence: '4 hours / week' }), '');
  const chrome = resolveLivePlanStageChrome({
    ...identity,
    planStageTitle: 'Auth',
    planStageGoal: 'Keep one check',
  });
  assert.equal(chrome.liveCurrent, 'Add a token expiry test');
  assert.equal(chrome.stageIsCurrent, false);
  assert.notEqual(chrome.liveCurrent, 'Auth');
  const stillOnPlan = {
    recovered: true,
    runtimeCurrentStep: 'Keep one auth check',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: 'plan-formal-old',
    planId: 'plan-formal-old',
  };
  assert.deepEqual(
    liveFormalPlanStages({ ...stillOnPlan, stages: leftoverStages }),
    leftoverStages,
  );
  assert.equal(
    liveFormalPlanCadence({ ...stillOnPlan, cadence: '4 hours / week' }),
    '4 hours / week',
  );
  const stillOnChrome = resolveLivePlanStageChrome({
    ...stillOnPlan,
    planStageTitle: 'Auth',
    planStageGoal: 'Keep one check',
  });
  assert.equal(stillOnChrome.stageIsCurrent, true);
  assert.equal(stillOnChrome.liveCurrent, 'Keep one auth check');
  const orientation = derivePlanOrientation({
    hasFormalPlan: true,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    planId: 'plan-formal-old',
    language: 'en-US',
  });
  assert.equal(orientation.objectLabel, 'Add a token expiry test');
  assert.notEqual(orientation.objectLabel, 'Auth');
  assert.notEqual(orientation.objectLabel, 'Tokens');
  assert.notEqual(orientation.objectLabel, '4 hours / week');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
});

test('after advance Plan why matches the new step or clears, never the old step reason', () => {
  const cleared = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Add a token expiry test',
    language: 'en-US',
  });
  assert.equal(cleared.state, 'working');
  assert.equal(cleared.objectLabel, 'Add a token expiry test');
  assert.equal(cleared.primaryAction, 'continue_step');
  assert.notEqual(cleared.why, 'Expired tokens still leak the session.');
  assert.notEqual(cleared.objectLabel, 'Keep one auth check');
  assert.notEqual(cleared.primaryAction, 'generate_plan');
  assert.notEqual(cleared.primaryAction, 'clear_blocker');
  const structured = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Add a token expiry test',
    whyNow: 'Expiry cases still skip the refresh path.',
    language: 'en-US',
  });
  assert.equal(structured.objectLabel, 'Add a token expiry test');
  assert.equal(structured.why, 'Expiry cases still skip the refresh path.');
  assert.notEqual(structured.why, 'Expired tokens still leak the session.');
  assert.equal(structured.primaryAction, 'continue_step');
});

test('resumed recovered runtime is in progress, not the same interrupted state', () => {
  const interrupted = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    currentStep: 'Keep one auth check',
    whyNow: 'The auth guard still fails on expired tokens.',
    language: 'en-US',
  });
  const resumed = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Keep one auth check',
    whyNow: 'The auth guard still fails on expired tokens.',
    language: 'en-US',
  });
  assert.equal(interrupted.state, 'interrupted');
  assert.equal(resumed.state, 'working');
  assert.notEqual(resumed.state, interrupted.state);
  assert.equal(resumed.primaryAction, 'continue_step');
  assert.notEqual(resumed.primaryAction, 'generate_plan');
});

test('recovered runtime step is interrupted, not a generated plan', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    currentStep: 'Keep one auth check',
    whyNow: 'The auth guard still fails on expired tokens.',
    nextAfterCurrent: 'Return with the focused test.',
    language: 'en-US',
  });
  assert.equal(orientation.objectLabel, 'Keep one auth check');
  assert.equal(orientation.state, 'interrupted');
  assert.notEqual(orientation.state, 'ready');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
  assert.equal(orientation.primaryAction, 'continue_step');
  assert.equal(orientation.why, 'The auth guard still fails on expired tokens.');
  assert.equal(orientation.nextStep, 'Return with the focused test.');
});

test('recovered runtime blocker stays blocked without inventing a plan', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    currentStep: 'Keep one auth check',
    blockedReason: 'The auth guard still fails on expired tokens.',
    language: 'en-US',
  });
  assert.equal(orientation.state, 'blocked');
  assert.equal(orientation.primaryAction, 'clear_blocker');
  assert.match(orientation.why, /auth guard/);
});

test('persisted blocker beats current-step theater', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: true,
    currentStep: 'Tighten the parser guard',
    whyNow: 'The current file still leaks the boundary.',
    blockedReason: 'Need a failing test first.',
    language: 'en-US',
  });
  assert.equal(orientation.state, 'blocked');
  assert.equal(orientation.primaryAction, 'clear_blocker');
  assert.match(orientation.why, /failing test/);
});

test('recovered in-progress without pending return evidence is not adopt', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: false,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    planId: 'plan-formal-old',
    whyNow: 'Keep the leftover why',
    pendingEvidenceCount: 0,
    language: 'en-US',
  });
  assert.equal(orientation.primaryAction, 'continue_step');
  assert.notEqual(orientation.primaryAction, 'adopt_evidence');
  assert.notEqual(orientation.primaryAction, 'generate_plan');
  assert.equal(orientation.objectLabel, 'Add a token expiry test');
  assert.notEqual(orientation.objectLabel, 'Keep the current stage');
});

test('recovered in-progress return evidence is adopt, not leftover live identity', () => {
  const leftover = derivePlanOrientation({
    hasFormalPlan: true,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Add a token expiry test',
    planCurrentStep: 'Keep one auth check',
    planId: 'plan-formal-old',
    whyNow: 'Keep the leftover why',
    pendingEvidenceCount: 1,
    pendingEvidenceIds: ['ev-return-1'],
    evidenceBinding: 'ev-return-1',
    language: 'en-US',
  });
  assert.equal(leftover.state, 'waiting');
  assert.equal(leftover.primaryAction, 'adopt_evidence');
  assert.equal(leftover.objectLabel, 'Add a token expiry test');
  assert.notEqual(leftover.objectLabel, 'Keep the current stage');
  assert.notEqual(leftover.objectLabel, 'Keep one auth check');
  assert.notEqual(leftover.why, 'Keep the leftover why');
  assert.match(leftover.why, /evidence item/);
  assert.notEqual(leftover.primaryAction, 'generate_plan');
  assert.notEqual(leftover.primaryAction, 'continue_step');
  const stillOnPlan = derivePlanOrientation({
    hasFormalPlan: true,
    recoveredRuntime: true,
    resumeState: 'in_progress',
    currentStep: 'Keep one auth check',
    planCurrentStep: 'Keep one auth check',
    planId: 'plan-formal-still',
    pendingEvidenceCount: 1,
    pendingEvidenceIds: ['ev-return-still'],
    evidenceBinding: 'ev-return-still',
    language: 'en-US',
  });
  assert.equal(stillOnPlan.primaryAction, 'adopt_evidence');
  assert.equal(stillOnPlan.objectLabel, 'Keep one auth check');
});

test('pending evidence is waiting, not adopted readiness', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: true,
    frozen: false,
    currentStep: 'Tighten the parser guard',
    pendingEvidenceCount: 2,
    pendingEvidenceIds: ['evidence-guard-1'],
    evidenceBinding: 'evidence-guard-1',
    language: 'en-US',
  });
  assert.equal(orientation.state, 'waiting');
  assert.equal(orientation.primaryAction, 'adopt_evidence');
  assert.match(orientation.nextStep, /evidence-guard-1/);
});

test('ready plan uses persisted step, why, and next', () => {
  const orientation = derivePlanOrientation({
    hasFormalPlan: true,
    currentStep: 'Tighten the parser guard',
    whyNow: 'The current file still leaks the boundary.',
    nextAfterCurrent: 'Return with the focused test.',
    verifyMethod: ['Run the focused test'],
    language: 'en-US',
  });
  assert.equal(orientation.objectLabel, 'Tighten the parser guard');
  assert.equal(orientation.state, 'ready');
  assert.equal(orientation.primaryAction, 'continue_step');
  assert.equal(orientation.why, 'The current file still leaks the boundary.');
  assert.equal(orientation.nextStep, 'Return with the focused test.');
});

test('transferable overlay does not steal a blocker', () => {
  const blocked = derivePlanOrientation({
    hasFormalPlan: true,
    currentStep: 'Tighten the parser guard',
    blockedReason: 'Need a failing test first.',
    transferState: {
      state: 'transferable',
      sceneCount: 2,
      workspaceIds: ['workspace-a', 'workspace-b'],
      sceneKeys: ['default', 'task-2'],
      why: 'Ready in a second scene.',
      next: 'Try the same skill in the other workspace.',
    },
    language: 'en-US',
  });
  assert.equal(blocked.state, 'blocked');
  assert.equal(blocked.primaryAction, 'clear_blocker');
});

test('continue_step resume payload keeps the recovered step and never mutates a plan', () => {
  const resume = buildRecoveredPlanResumeTurn('continue_step', {
    recovered: true,
    currentStep: 'Keep one auth check',
    currentStepId: 'step-auth-1',
    whyNow: 'The auth guard still fails on expired tokens.',
  });
  assert.ok(resume);
  assert.equal(resume.action, 'continue_step');
  assert.equal(resume.currentStep, 'Keep one auth check');
  assert.equal(resume.currentStepId, 'step-auth-1');
  assert.equal(resume.formalPlanMutation, false);
  assert.match(recoveredPlanResumeMessage(resume, 'en-US'), /Keep one auth check/);
  assert.equal(
    buildRecoveredPlanResumeTurn('continue_step', {
      recovered: true,
      blockedReason: 'Need a failing test first.',
    }),
    undefined,
  );
  assert.equal(
    buildRecoveredPlanResumeTurn('continue_step', {
      currentStep: 'Invented theater step',
    }),
    undefined,
  );
});

test('clear_blocker resume payload keeps the recovered blocker and never mutates a plan', () => {
  const resume = buildRecoveredPlanResumeTurn('clear_blocker', {
    recovered: true,
    currentStep: 'Keep one auth check',
    blockedReason: 'The auth guard still fails on expired tokens.',
  });
  assert.ok(resume);
  assert.equal(resume.action, 'clear_blocker');
  assert.equal(resume.blockedReason, 'The auth guard still fails on expired tokens.');
  assert.equal(resume.currentStep, 'Keep one auth check');
  assert.equal(resume.formalPlanMutation, false);
  assert.match(recoveredPlanResumeMessage(resume, 'en-US'), /auth guard/);
  assert.equal(
    normalizeRecoveredPlanResumeTurn({
      action: 'clear_blocker',
      recovered: true,
      formalPlanMutation: true,
      blockedReason: 'The auth guard still fails on expired tokens.',
    }),
    undefined,
  );
  assert.equal(
    buildRecoveredPlanResumeTurn('clear_blocker', {
      recovered: true,
      currentStep: 'Keep one auth check',
    }),
    undefined,
  );
});

test('leftover bound plan competing labels omit leftover identity after a new live plan', () => {
  const leftoverTitle = 'Keep the current stage';
  const leftoverStep = 'Keep one auth check';
  const liveStep = 'Inspect one refresh boundary';
  assert.deepEqual(
    leftoverBoundPlanCompetingIdentityLabels({
      livePlanId: 'plan-generated-new',
      liveCurrentStep: liveStep,
      livePlanTitle: 'Token-refresh learning path',
      leftoverPlanId: 'plan-formal-old',
      leftoverPlanTitle: leftoverTitle,
      leftoverPlanStep: leftoverStep,
      leftoverCardTitles: [leftoverStep, 'Keep the leftover A sandbox preview'],
    }).sort(),
    ['Keep the current stage', 'Keep the leftover A sandbox preview', leftoverStep].sort(),
  );
  assert.deepEqual(
    leftoverBoundPlanCompetingIdentityLabels({
      livePlanId: 'plan-formal-old',
      liveCurrentStep: leftoverStep,
      livePlanTitle: leftoverTitle,
      leftoverPlanId: 'plan-formal-old',
      leftoverPlanTitle: leftoverTitle,
      leftoverPlanStep: leftoverStep,
      leftoverCardTitles: [leftoverStep],
    }),
    [],
  );
  assert.deepEqual(
    leftoverBoundPlanCompetingIdentityLabels({
      livePlanId: '',
      liveCurrentStep: 'Add a token expiry test',
      leftoverPlanId: 'plan-formal-old',
      leftoverPlanTitle: leftoverTitle,
      leftoverPlanStep: leftoverStep,
      leftoverCardTitles: [leftoverStep, 'Keep the leftover A sandbox preview'],
    }).sort(),
    ['Keep the current stage', leftoverStep, 'Keep the leftover A sandbox preview'].sort(),
  );
  assert.equal(
    liveTrainingNextChallengeTitle({
      recovered: true,
      runtimeCurrentStep: liveStep,
      planCurrentStep: liveStep,
      runtimePlanId: 'plan-generated-new',
      planId: 'plan-generated-new',
      planTitle: 'Token-refresh learning path',
      taskTitle: leftoverTitle,
      cardTitle: '',
    }),
    '',
  );
});

test('streak adapts without inventing live objects', () => {
  assert.equal(
    streakAdaptsWithoutInventingLiveObjects({
      failureStreak: 2,
      livePlan: false,
      liveTask: false,
      liveCard: false,
    }),
    true,
  );
  assert.equal(
    streakAdaptsWithoutInventingLiveObjects({
      failureStreak: 2,
      livePlan: true,
      liveTask: false,
      liveCard: false,
    }),
    false,
  );
  assert.equal(
    streakAdaptsWithoutInventingLiveObjects({
      successStreak: 2,
      livePlan: false,
      liveTask: false,
      liveCard: false,
    }),
    true,
  );
  assert.equal(
    streakAdaptsWithoutInventingLiveObjects({
      successStreak: 2,
      liveCard: true,
    }),
    false,
  );
  // Backend stamp alone fails closed even when streak fields are missing/stale.
  assert.equal(
    streakAdaptsWithoutInventingLiveObjects({
      streakBlocksLiveObjectMint: true,
      livePlan: false,
      liveTask: false,
      liveCard: false,
    }),
    true,
  );
  assert.equal(
    streakAdaptsWithoutInventingLiveObjects({
      streakBlocksLiveObjectMint: true,
      livePlan: true,
      liveTask: false,
      liveCard: false,
    }),
    false,
  );
});

test('pressure adapts without inventing live objects', () => {
  assert.equal(
    pressureAdaptsWithoutInventingLiveObjects({
      timeBudget: 'tight',
      livePlan: false,
      liveTask: false,
      liveCard: false,
    }),
    true,
  );
  assert.equal(
    pressureAdaptsWithoutInventingLiveObjects({
      taskUrgency: 'high',
      livePlan: false,
      liveTask: false,
      liveCard: false,
    }),
    true,
  );
  assert.equal(
    pressureAdaptsWithoutInventingLiveObjects({
      taskUrgency: 'high',
      livePlan: true,
      liveTask: false,
      liveCard: false,
    }),
    false,
  );
  assert.equal(
    pressureAdaptsWithoutInventingLiveObjects({
      timeBudget: 'normal',
      taskUrgency: 'medium',
      livePlan: false,
      liveTask: false,
      liveCard: false,
    }),
    false,
  );
  // Backend stamp alone fails closed even when urgency fields are missing/stale.
  assert.equal(
    pressureAdaptsWithoutInventingLiveObjects({
      pressureBlocksLiveObjectMint: true,
      livePlan: false,
      liveTask: false,
      liveCard: false,
    }),
    true,
  );
  assert.equal(
    pressureAdaptsWithoutInventingLiveObjects({
      pressureBlocksLiveObjectMint: true,
      timeBudget: 'normal',
      taskUrgency: 'medium',
      livePlan: false,
      liveTask: false,
      liveCard: false,
    }),
    true,
  );
  assert.equal(
    pressureAdaptsWithoutInventingLiveObjects({
      pressureBlocksLiveObjectMint: true,
      livePlan: true,
      liveTask: false,
      liveCard: false,
    }),
    false,
  );
});
