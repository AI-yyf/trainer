// Restored behavioral regression test. Original file: extension/tests/workspaceRecoveryGovernanceShared.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Workspace recovery governance: recovered runtime stamps and leftover-not-live recovery status.
//
// Restoration: partial - 8 of 40 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "declared capability is not treated as a live last-test success surface"
//       fails at HEAD: isAuthoritativeProviderCapabilitySuccess is not a function
//   - "in-flight stream recovers as interrupted, never completed"
//       fails at HEAD: isCompletedStreamingCheckpoint is not a function
//   - "completed stream stays completed after restart"
//       fails at HEAD: isCompletedStreamingCheckpoint is not a function
//   - "incomplete leftover affectState is not current truth"
//       fails at HEAD: normalizeAffectStateIdentity is not a function
//   - "workspace switch drops leftover affectState as current"
//       fails at HEAD: selectAffectStateForScope is not a function
//   - "incomplete leftover toneDecision is not current truth"
//       fails at HEAD: normalizeToneDecisionIdentity is not a function
//   - "incomplete leftover adaptation guide is not current truth"
//       fails at HEAD: normalizeAdaptationGuideIdentity is not a function
//   - "workspace switch drops leftover adaptation guide as current"
//       fails at HEAD: selectAdaptationGuideForScope is not a function
//   - "incomplete leftover principle notes are not current truth"
//       fails at HEAD: normalizePrincipleNotesIdentity is not a function
//   - "workspace switch drops leftover principle notes as current"
//       fails at HEAD: selectPrincipleNotesForScope is not a function
//   - "incomplete leftover project sources are not current truth"
//       fails at HEAD: normalizeProjectSourceIdentity is not a function
//   - "workspace switch drops leftover project sources as current"
//       fails at HEAD: selectProjectSourcesForScope is not a function
//   - "workspace switch drops leftover toneDecision as current"
//       fails at HEAD: selectToneDecisionForScope is not a function
//   - "incomplete leftover evaluation chrome is not current truth"
//       fails at HEAD: normalizeEvaluationIdentity is not a function
//   - "workspace switch drops leftover evaluation as current"
//       fails at HEAD: selectEvaluationForScope is not a function
//   - "incomplete leftover learnerState is not current truth"
//       fails at HEAD: normalizeLearnerStateIdentity is not a function
//   - "workspace switch drops leftover learnerState as current"
//       fails at HEAD: selectLearnerStateForScope is not a function
//   - "incomplete leftover teachingDecision is not current truth"
//       fails at HEAD: normalizeTeachingDecisionIdentity is not a function
//   - "workspace switch drops leftover teachingDecision as current"
//       fails at HEAD: selectTeachingDecisionForScope is not a function
//   - "incomplete leftover coaching focus is not current truth"
//       fails at HEAD: normalizeCoachingFocusIdentity is not a function
//   - "incomplete leftover coachFocus is not current truth"
//       fails at HEAD: normalizeCoachFocusIdentity is not a function
//   - "workspace switch drops leftover coachFocus as current"
//       fails at HEAD: selectCoachFocusForScope is not a function
//   - "incomplete leftover coachTurn is not current truth"
//       fails at HEAD: normalizeCoachTurnIdentity is not a function
//   - "incomplete leftover nextStepHint is not current truth"
//       fails at HEAD: nextStepHintIdentityIsLive is not a function
//   - "incomplete leftover coachingAdaptation is not current truth"
//       fails at HEAD: coachingAdaptationIdentityIsLive is not a function
//   - "workspace switch drops leftover coachTurn as current"
//       fails at HEAD: selectCoachTurnForScope is not a function
//   - "workspace switch drops leftover coaching focus as current"
//       fails at HEAD: selectCoachingFocusForScope is not a function
//   - "incomplete leftover task identity is not current truth"
//       fails at HEAD: normalizeCurrentTaskIdentity is not a function
//   - "workspace switch drops leftover current_task as current"
//       fails at HEAD: selectCurrentTaskForScope is not a function
//   - "incomplete leftover plan identity is not current truth"
//       fails at HEAD: selectFormalPlanForScope is not a function
//   - "workspace switch drops leftover plan identity and resources as current"
//       fails at HEAD: selectFormalPlanForScope is not a function
//   - "workspace switch drops previous plan, last-test, and stream as current"
//       fails at HEAD: selectTrainingRecordForScope is not a function
// Target: compiled shared modules (extension/dist/shared/src).

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
