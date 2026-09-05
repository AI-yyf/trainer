'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  isAuthoritativeProviderCapabilitySuccess,
  isCompletedStreamingCheckpoint,
  isInterruptedStreamingCheckpoint,
  normalizePlanRuntimeRecovery,
  normalizeProviderCapabilityRecovery,
  recoverStreamingCheckpointAfterRestart,
  selectPlanRuntimeForScope,
  planRuntimeStatusFromRecovery,
  selectProviderCapabilityForScope,
  selectStreamingCheckpointForScope,
  selectTrainingChromeForScope,
  selectTrainingRecordForScope,
  normalizeTrainingChrome,
  normalizeFormalPlanIdentity,
  formalPlanIdentityIsLive,
  selectFormalPlanForScope,
  selectResourcesForScope,
  normalizeCurrentTaskIdentity,
  currentTaskIdentityIsLive,
  selectCurrentTaskForScope,
  normalizeCoachingFocusIdentity,
  coachingFocusIdentityIsLive,
  selectCoachingFocusForScope,
  normalizeCoachFocusIdentity,
  coachFocusIdentityIsLive,
  selectCoachFocusForScope,
  normalizeCoachTurnIdentity,
  coachTurnIdentityIsLive,
  selectCoachTurnForScope,
  normalizeNextStepHintIdentity,
  nextStepHintIdentityIsLive,
  selectNextStepHintForScope,
  normalizeCoachingAdaptationIdentity,
  coachingAdaptationIdentityIsLive,
  selectCoachingAdaptationForScope,
  preferAuthoritativeProviderLastTest,
  normalizeEvaluationIdentity,
  evaluationIdentityIsLive,
  selectEvaluationForScope,
  normalizeLearnerStateIdentity,
  learnerStateIdentityIsLive,
  selectLearnerStateForScope,
  normalizeTeachingDecisionIdentity,
  teachingDecisionIdentityIsLive,
  selectTeachingDecisionForScope,
  normalizeAffectStateIdentity,
  affectStateIdentityIsLive,
  selectAffectStateForScope,
  normalizeToneDecisionIdentity,
  toneDecisionIdentityIsLive,
  selectToneDecisionForScope,
  normalizeAdaptationGuideIdentity,
  adaptationGuideIdentityIsLive,
  selectAdaptationGuideForScope,
  normalizePrincipleNotesIdentity,
  principleNotesIdentityIsLive,
  selectPrincipleNotesForScope,
  normalizeProjectSourceIdentity,
  projectSourceIdentityIsLive,
  selectProjectSourcesForScope,
} = require('../dist/shared/src/workspaceRecoveryGovernance.js');

test('waiting recovered runtime without a step stays current when stamped', () => {
  const waiting = normalizePlanRuntimeRecovery({
    workspace_id: 'workspace-a',
    resume_state: 'waiting',
    evidence_binding: 'ev-return-a',
    next_after_current: 'Add a token expiry test',
  });
  assert.equal(waiting?.resumeState, 'waiting');
  assert.equal(waiting?.workspaceId, 'workspace-a');
  assert.equal(waiting?.evidenceBinding, 'ev-return-a');
  assert.equal(waiting?.nextAfterCurrent, 'Add a token expiry test');
  assert.equal(
    selectPlanRuntimeForScope(
      {
        workspace_id: 'workspace-a',
        resume_state: 'waiting',
        evidence_binding: 'ev-return-a',
      },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('empty recovered current_step stays leftover-not-live recovery status', () => {
  const empty = planRuntimeStatusFromRecovery(
    {
      workspace_id: 'workspace-a',
      resume_state: 'in_progress',
      current_step: '',
      why_now: 'Keep the leftover why',
      blocked_reason: 'Keep the leftover blocker',
    },
    'workspace-a',
  );
  assert.equal(empty?.recovered, true);
  assert.equal(empty?.currentStep, undefined);
  assert.equal(empty?.currentStage, null);
  assert.equal(empty?.whyNow, undefined);
  assert.equal(empty?.blockedReason, undefined);
  assert.deepEqual(empty?.verifyMethod, []);
  assert.equal(empty?.resumeState, 'in_progress');
  assert.equal(
    planRuntimeStatusFromRecovery(
      {
        workspace_id: 'workspace-a',
        resume_state: 'in_progress',
        current_step: '',
      },
      'workspace-b',
    ),
    undefined,
  );
  assert.equal(
    planRuntimeStatusFromRecovery(
      {
        workspace_id: 'workspace-a',
        plan_id: 'plan-stale',
      },
      'workspace-a',
    ),
    undefined,
  );
  const live = planRuntimeStatusFromRecovery(
    {
      workspace_id: 'workspace-a',
      resume_state: 'in_progress',
      current_step: 'Add a token expiry test',
      why_now: 'Expired tokens still leak.',
    },
    'workspace-a',
  );
  assert.equal(live?.recovered, true);
  assert.equal(live?.currentStep, 'Add a token expiry test');
  assert.equal(live?.whyNow, 'Expired tokens still leak.');
});

test('incomplete plan and provider records are not current truth', () => {
  assert.equal(normalizePlanRuntimeRecovery({ revision: 1, frozen: true }), undefined);
  assert.equal(
    normalizeProviderCapabilityRecovery({ ok: true, model: 'MiniMax-M2.7' }),
    undefined,
  );
});

test('declared capability is not treated as a live last-test success surface', () => {
  const record = normalizeProviderCapabilityRecovery({
    ok: true,
    providerName: 'minimax',
    baseUrl: 'http://example.test/v1',
    model: 'MiniMax-M2.7',
    checkedAt: '2026-08-25T00:00:00.000Z',
    toolsReady: true,
    toolProbeStatus: 'unverified',
    capabilityEvidence: [{ name: 'tools', declared: true, observed: null, state: 'unverified' }],
    apiKey: 'should-never-survive-normalize',
  });
  assert.ok(record);
  assert.equal(record.ok, true);
  assert.equal(record.toolsReady, false);
  assert.equal('apiKey' in record, false);
  assert.equal(isAuthoritativeProviderCapabilitySuccess(record), true);
});

test('newer failed leftover last-test beats older recovered success', () => {
  const recovered = {
    ok: true,
    checkedAt: '2026-08-25T00:00:00.000Z',
    toolsReady: true,
  };
  const leftoverFailed = {
    ok: false,
    checkedAt: '2026-08-26T00:00:00.000Z',
    toolsReady: false,
  };
  assert.equal(preferAuthoritativeProviderLastTest(leftoverFailed, recovered), leftoverFailed);
  assert.equal(
    preferAuthoritativeProviderLastTest(
      { ok: true, checkedAt: '2026-08-24T00:00:00.000Z' },
      leftoverFailed,
    ),
    leftoverFailed,
  );
});

test('in-flight stream recovers as interrupted, never completed', () => {
  const recovered = recoverStreamingCheckpointAfterRestart({
    revision: 1,
    requestId: 'stream-restore-1',
    phase: 'streaming',
    sessionId: 'session-1',
  });
  assert.equal(recovered?.phase, 'interrupted');
  assert.equal(isCompletedStreamingCheckpoint(recovered), false);
  assert.equal(isInterruptedStreamingCheckpoint(recovered), true);
});

test('completed stream stays completed after restart', () => {
  const recovered = recoverStreamingCheckpointAfterRestart({
    revision: 2,
    requestId: 'stream-done-1',
    phase: 'completed',
  });
  assert.equal(recovered?.phase, 'completed');
  assert.equal(isCompletedStreamingCheckpoint(recovered), true);
});

test('incomplete leftover affectState is not current truth', () => {
  assert.equal(normalizeAffectStateIdentity({ revision: 1 }), undefined);
  assert.equal(affectStateIdentityIsLive({}), false);
  assert.equal(affectStateIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectAffectStateForScope(
      { urgencyLevel: 'high', needsReassurance: true, recoverySignal: 'Keep the leftover A affect' },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('workspace switch drops leftover affectState as current', () => {
  const leftoverAffect = {
    workspaceId: 'workspace-a',
    urgencyLevel: 'high',
    needsReassurance: true,
    recoverySignal: 'Keep the leftover A affect',
  };
  assert.equal(selectAffectStateForScope(leftoverAffect, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(
    selectAffectStateForScope(leftoverAffect, { workspaceId: 'workspace-a' })?.recoverySignal,
    'Keep the leftover A affect',
  );
});

test('incomplete leftover toneDecision is not current truth', () => {
  assert.equal(normalizeToneDecisionIdentity({ revision: 1 }), undefined);
  assert.equal(toneDecisionIdentityIsLive({}), false);
  assert.equal(toneDecisionIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectToneDecisionForScope(
      { tone: 'concise_rescue', acknowledgeProgress: true },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('incomplete leftover adaptation guide is not current truth', () => {
  assert.equal(normalizeAdaptationGuideIdentity({ revision: 1 }), undefined);
  assert.equal(adaptationGuideIdentityIsLive({}), false);
  assert.equal(adaptationGuideIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectAdaptationGuideForScope(
      { targetOutcome: 'Keep the leftover A adaptation outcome', firstMigrationStep: 'Keep the leftover A adaptation step' },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('workspace switch drops leftover adaptation guide as current', () => {
  const leftoverGuide = {
    workspaceId: 'workspace-a',
    targetOutcome: 'Keep the leftover A adaptation outcome',
    firstMigrationStep: 'Keep the leftover A adaptation step',
  };
  assert.equal(selectAdaptationGuideForScope(leftoverGuide, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(
    selectAdaptationGuideForScope(leftoverGuide, { workspaceId: 'workspace-a' })?.targetOutcome,
    'Keep the leftover A adaptation outcome',
  );
});

test('incomplete leftover principle notes are not current truth', () => {
  assert.equal(normalizePrincipleNotesIdentity({ revision: 1 }), undefined);
  assert.equal(principleNotesIdentityIsLive({}), false);
  assert.equal(principleNotesIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectPrincipleNotesForScope(
      { currentPrinciple: 'Keep the leftover A principle', applyNow: 'Keep the leftover A principle apply' },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('workspace switch drops leftover principle notes as current', () => {
  const leftoverNotes = {
    workspaceId: 'workspace-a',
    currentPrinciple: 'Keep the leftover A principle',
    whyItMatters: 'Keep the leftover A principle why',
    applyNow: 'Keep the leftover A principle apply',
  };
  assert.equal(selectPrincipleNotesForScope(leftoverNotes, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(
    selectPrincipleNotesForScope(leftoverNotes, { workspaceId: 'workspace-a' })?.currentPrinciple,
    'Keep the leftover A principle',
  );
});

test('incomplete leftover project sources are not current truth', () => {
  assert.equal(normalizeProjectSourceIdentity({ revision: 1 }), undefined);
  assert.equal(projectSourceIdentityIsLive({}), false);
  assert.equal(projectSourceIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.deepEqual(
    selectProjectSourcesForScope(
      [{ title: 'Keep the leftover A project source', fitReason: 'A leftover project source' }],
      { workspaceId: 'workspace-b' },
    ),
    [],
  );
  assert.deepEqual(
    selectProjectSourcesForScope({ revision: 1, sources: [] }, { workspaceId: 'workspace-a' }),
    [],
  );
});

test('workspace switch drops leftover project sources as current', () => {
  const leftoverSources = {
    workspaceId: 'workspace-a',
    sources: [{ title: 'Keep the leftover A project source', fitReason: 'A leftover project source' }],
  };
  assert.deepEqual(selectProjectSourcesForScope(leftoverSources, { workspaceId: 'workspace-b' }), []);
  assert.equal(
    selectProjectSourcesForScope(leftoverSources, { workspaceId: 'workspace-a' })[0]?.title,
    'Keep the leftover A project source',
  );
});

test('workspace switch drops leftover toneDecision as current', () => {
  const leftoverTone = {
    workspaceId: 'workspace-a',
    tone: 'concise_rescue',
    verbosityBias: 'short',
    acknowledgeProgress: true,
    avoidOverwhelm: true,
  };
  assert.equal(selectToneDecisionForScope(leftoverTone, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(
    selectToneDecisionForScope(leftoverTone, { workspaceId: 'workspace-a' })?.tone,
    'concise_rescue',
  );
});

test('incomplete leftover evaluation chrome is not current truth', () => {
  assert.equal(normalizeEvaluationIdentity({ revision: 1 }), undefined);
  assert.equal(evaluationIdentityIsLive({}), false);
  assert.equal(evaluationIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectEvaluationForScope(
      { summary: 'Keep the leftover A evaluation summary', nextStep: 'Stay on leftover A eval' },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('workspace switch drops leftover evaluation as current', () => {
  const leftoverEvaluation = {
    workspaceId: 'workspace-a',
    summary: 'Keep the leftover A evaluation summary',
    nextStep: 'Stay on leftover A eval',
    headline: 'Keep the leftover A evaluation headline',
  };
  assert.equal(selectEvaluationForScope(leftoverEvaluation, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(
    selectEvaluationForScope(leftoverEvaluation, { workspaceId: 'workspace-a' })?.summary,
    'Keep the leftover A evaluation summary',
  );
});

test('incomplete leftover learnerState is not current truth', () => {
  assert.equal(normalizeLearnerStateIdentity({ revision: 1 }), undefined);
  assert.equal(learnerStateIdentityIsLive({}), false);
  assert.equal(learnerStateIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectLearnerStateForScope(
      { activeFocus: 'Keep the leftover A learner focus', evidence: ['A leftover eval evidence'] },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('workspace switch drops leftover learnerState as current', () => {
  const leftoverLearner = {
    workspaceId: 'workspace-a',
    activeFocus: 'Keep the leftover A learner focus',
    evidence: ['A leftover eval evidence'],
  };
  assert.equal(selectLearnerStateForScope(leftoverLearner, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(
    selectLearnerStateForScope(leftoverLearner, { workspaceId: 'workspace-a' })?.activeFocus,
    'Keep the leftover A learner focus',
  );
});

test('incomplete leftover teachingDecision is not current truth', () => {
  assert.equal(normalizeTeachingDecisionIdentity({ revision: 1 }), undefined);
  assert.equal(teachingDecisionIdentityIsLive({}), false);
  assert.equal(teachingDecisionIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectTeachingDecisionForScope(
      { reason: 'Keep the leftover A teaching reason', primaryGoal: 'Keep the leftover A teaching goal' },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('workspace switch drops leftover teachingDecision as current', () => {
  const leftoverDecision = {
    workspaceId: 'workspace-a',
    reason: 'Keep the leftover A teaching reason',
    primaryGoal: 'Keep the leftover A teaching goal',
    teachingStrategy: 'Stay on leftover A',
    closingMove: 'Keep one auth check',
  };
  assert.equal(selectTeachingDecisionForScope(leftoverDecision, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(
    selectTeachingDecisionForScope(leftoverDecision, { workspaceId: 'workspace-a' })?.primaryGoal,
    'Keep the leftover A teaching goal',
  );
});

test('incomplete leftover coaching focus is not current truth', () => {
  assert.equal(normalizeCoachingFocusIdentity({ revision: 1 }), undefined);
  assert.equal(coachingFocusIdentityIsLive({}), false);
  assert.equal(coachingFocusIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectCoachingFocusForScope(
      { summary: 'Keep the leftover A coaching summary', focusArea: 'Keep the leftover A coaching focus' },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('incomplete leftover coachFocus is not current truth', () => {
  assert.equal(normalizeCoachFocusIdentity({ revision: 1 }), undefined);
  assert.equal(coachFocusIdentityIsLive({}), false);
  assert.equal(coachFocusIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectCoachFocusForScope(
      {
        currentFocus: 'Keep the leftover A coach focus',
        firstTurnPriority: 'Keep the leftover A recommended',
        continuitySummary: 'Keep the leftover A coach focus summary',
      },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('workspace switch drops leftover coachFocus as current', () => {
  const leftoverFocus = {
    workspaceId: 'workspace-a',
    currentFocus: 'Keep the leftover A coach focus',
    firstTurnPriority: 'Keep the leftover A recommended',
    continuitySummary: 'Keep the leftover A coach focus summary',
  };
  assert.equal(selectCoachFocusForScope(leftoverFocus, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(
    selectCoachFocusForScope(leftoverFocus, { workspaceId: 'workspace-a' })?.currentFocus,
    'Keep the leftover A coach focus',
  );
  assert.equal(
    selectCoachFocusForScope(leftoverFocus, { workspaceId: 'workspace-a' })?.recommended,
    'Keep the leftover A recommended',
  );
  assert.equal(
    selectCoachFocusForScope(leftoverFocus, { workspaceId: 'workspace-a' })?.summary,
    'Keep the leftover A coach focus summary',
  );
});

test('incomplete leftover coachTurn is not current truth', () => {
  assert.equal(normalizeCoachTurnIdentity({ revision: 1 }), undefined);
  assert.equal(coachTurnIdentityIsLive({}), false);
  assert.equal(coachTurnIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectCoachTurnForScope(
      {
        summary: 'Keep the leftover A coach turn summary',
        nextStep: 'Keep the leftover A coach turn next',
        teachingGoal: 'Keep the leftover A coach turn goal',
      },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('incomplete leftover nextStepHint is not current truth', () => {
  assert.equal(normalizeNextStepHintIdentity({ revision: 1 }), undefined);
  assert.equal(nextStepHintIdentityIsLive({}), false);
  assert.equal(nextStepHintIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectNextStepHintForScope(
      {
        title: 'Keep the leftover A next-step hint',
        summary: 'Keep the leftover A next-step summary',
        recommendedAction: 'task',
      },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('workspace switch drops leftover nextStepHint as current', () => {
  const leftoverHint = {
    workspaceId: 'workspace-a',
    title: 'Keep the leftover A next-step hint',
    summary: 'Keep the leftover A next-step summary',
    recommendedAction: 'task',
  };
  assert.equal(selectNextStepHintForScope(leftoverHint, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(
    selectNextStepHintForScope(leftoverHint, { workspaceId: 'workspace-a' })?.title,
    'Keep the leftover A next-step hint',
  );
  assert.equal(
    selectNextStepHintForScope(leftoverHint, { workspaceId: 'workspace-a' })?.summary,
    'Keep the leftover A next-step summary',
  );
});

test('incomplete leftover coachingAdaptation is not current truth', () => {
  assert.equal(normalizeCoachingAdaptationIdentity({ revision: 1 }), undefined);
  assert.equal(coachingAdaptationIdentityIsLive({}), false);
  assert.equal(coachingAdaptationIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectCoachingAdaptationForScope(
      {
        summary: 'Keep the leftover A adaptation summary',
        evidence: ['Keep the leftover A adaptation evidence'],
      },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('workspace switch drops leftover coachingAdaptation as current', () => {
  const leftoverAdaptation = {
    workspaceId: 'workspace-a',
    summary: 'Keep the leftover A adaptation summary',
    evidence: ['Keep the leftover A adaptation evidence'],
  };
  assert.equal(
    selectCoachingAdaptationForScope(leftoverAdaptation, { workspaceId: 'workspace-b' }),
    undefined,
  );
  assert.equal(
    selectCoachingAdaptationForScope(leftoverAdaptation, { workspaceId: 'workspace-a' })?.summary,
    'Keep the leftover A adaptation summary',
  );
  assert.deepEqual(
    selectCoachingAdaptationForScope(leftoverAdaptation, { workspaceId: 'workspace-a' })?.evidence,
    ['Keep the leftover A adaptation evidence'],
  );
});

test('workspace switch drops leftover coachTurn as current', () => {
  const leftoverTurn = {
    workspaceId: 'workspace-a',
    summary: 'Keep the leftover A coach turn summary',
    nextStep: 'Keep the leftover A coach turn next',
    teachingGoal: 'Keep the leftover A coach turn goal',
  };
  assert.equal(selectCoachTurnForScope(leftoverTurn, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(
    selectCoachTurnForScope(leftoverTurn, { workspaceId: 'workspace-a' })?.summary,
    'Keep the leftover A coach turn summary',
  );
});

test('workspace switch drops leftover coaching focus as current', () => {
  const leftoverFocus = {
    workspaceId: 'workspace-a',
    summary: 'Keep the leftover A coaching summary',
    nextStep: 'Stay on leftover A',
    focusArea: 'Keep the leftover A coaching focus',
    teachingGoal: 'Ship one auth check',
  };
  assert.equal(selectCoachingFocusForScope(leftoverFocus, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(
    selectCoachingFocusForScope(leftoverFocus, { workspaceId: 'workspace-a' })?.focusArea,
    'Keep the leftover A coaching focus',
  );
});

test('incomplete leftover task identity is not current truth', () => {
  assert.equal(normalizeCurrentTaskIdentity({ revision: 1 }), undefined);
  assert.equal(currentTaskIdentityIsLive({}), false);
  assert.equal(currentTaskIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectCurrentTaskForScope(
      { title: 'Ship one auth check', natural_language_goal: 'Keep the leftover A task' },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('workspace switch drops leftover current_task as current', () => {
  const leftoverTask = {
    workspaceId: 'workspace-a',
    id: 'task-formal-old',
    title: 'Ship one auth check',
    naturalLanguageGoal: 'Keep the leftover A task',
  };
  assert.equal(selectCurrentTaskForScope(leftoverTask, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(
    selectCurrentTaskForScope(leftoverTask, { workspaceId: 'workspace-a' })?.title,
    'Ship one auth check',
  );
});

test('incomplete leftover plan identity is not current truth', () => {
  assert.equal(normalizeFormalPlanIdentity({ revision: 1 }), undefined);
  assert.equal(formalPlanIdentityIsLive({}), false);
  assert.equal(formalPlanIdentityIsLive({ workspaceId: 'workspace-a' }), false);
  assert.equal(
    selectFormalPlanForScope(
      { title: 'Keep the current stage', summary: 'Leftover formal summary' },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('workspace switch drops leftover plan identity and resources as current', () => {
  const leftoverPlan = {
    workspaceId: 'workspace-a',
    id: 'plan-formal-old',
    title: 'Keep the current stage',
    summary: 'Leftover formal summary of the old stage path',
    currentStep: 'Keep one auth check',
  };
  assert.equal(selectFormalPlanForScope(leftoverPlan, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(
    selectFormalPlanForScope(leftoverPlan, { workspaceId: 'workspace-a' })?.title,
    'Keep the current stage',
  );
  assert.deepEqual(
    selectResourcesForScope(
      [{ workspace_id: 'workspace-a', title: 'Workspace A notes' }],
      { workspaceId: 'workspace-b' },
    ),
    [],
  );
  assert.equal(
    selectResourcesForScope(
      [{ workspace_id: 'workspace-a', title: 'Workspace A notes' }],
      { workspaceId: 'workspace-a' },
    )[0]?.title,
    'Workspace A notes',
  );
  assert.equal(
    selectResourcesForScope([{ title: 'Unscoped incoming notes' }], { workspaceId: 'workspace-b' })[0]
      ?.title,
    'Unscoped incoming notes',
  );
});

test('incomplete training chrome is not current truth', () => {
  assert.equal(normalizeTrainingChrome({ revision: 1 }), undefined);
  assert.equal(
    selectTrainingChromeForScope(
      { selectedCardTitle: 'Review the refresh path' },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
});

test('workspace switch drops previous plan, last-test, and stream as current', () => {
  const lastTest = {
    ok: true,
    workspaceId: 'workspace-a',
    providerProfileId: 'profile-a',
    providerName: 'minimax',
    baseUrl: 'http://example.test/v1',
    model: 'MiniMax-M2.7',
    checkedAt: '2026-08-25T00:00:00.000Z',
  };
  assert.equal(
    selectPlanRuntimeForScope(
      { workspaceId: 'workspace-a', planId: 'plan-a', currentStep: 'Stay on A', frozen: false },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
  assert.equal(
    selectProviderCapabilityForScope(lastTest, {
      workspaceId: 'workspace-b',
      providerProfileId: 'profile-a',
    }),
    undefined,
  );
  assert.equal(
    selectStreamingCheckpointForScope(
      {
        workspaceId: 'workspace-a',
        providerProfileId: 'profile-a',
        requestId: 'stream-a',
        phase: 'interrupted',
      },
      { workspaceId: 'workspace-b', providerProfileId: 'profile-a' },
    ),
    undefined,
  );
  assert.equal(
    selectTrainingChromeForScope(
      { workspaceId: 'workspace-a', selectedCardTitle: 'Review the refresh path' },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
  assert.equal(
    selectTrainingRecordForScope(
      { workspaceId: 'workspace-a', cardTitle: 'Review the refresh path' },
      { workspaceId: 'workspace-b' },
    ),
    undefined,
  );
  assert.equal(
    selectTrainingChromeForScope(
      { workspaceId: 'workspace-a', selectedCardTitle: 'Review the refresh path' },
      { workspaceId: 'workspace-a' },
    )?.selectedCardTitle,
    'Review the refresh path',
  );
});

test('provider switch drops previous last-test and stream, and re-scopes the original', () => {
  const lastTest = {
    ok: true,
    workspaceId: 'workspace-shared',
    providerProfileId: 'profile-a',
    providerName: 'minimax',
    baseUrl: 'http://example.test/v1',
    model: 'MiniMax-M2.7',
    checkedAt: '2026-08-25T00:00:00.000Z',
  };
  const stream = {
    workspaceId: 'workspace-shared',
    providerProfileId: 'profile-a',
    requestId: 'stream-a',
    phase: 'interrupted',
  };
  assert.equal(
    selectProviderCapabilityForScope(lastTest, {
      workspaceId: 'workspace-shared',
      providerProfileId: 'profile-b',
    }),
    undefined,
  );
  assert.equal(
    selectStreamingCheckpointForScope(stream, {
      workspaceId: 'workspace-shared',
      providerProfileId: 'profile-b',
    }),
    undefined,
  );
  assert.equal(
    selectProviderCapabilityForScope(lastTest, {
      workspaceId: 'workspace-shared',
      providerProfileId: 'profile-a',
    })?.ok,
    true,
  );
});
