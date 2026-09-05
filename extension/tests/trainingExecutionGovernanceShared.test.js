'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  deriveTrainingExecutionState,
} = require('../dist/shared/src/trainingExecutionGovernance.js');

test('derives execution phases from the card evidence lifecycle', () => {
  const cases = [
    {
      name: 'holds a practice card in learn until its primer is cleared',
      input: {
        cardType: 'practice',
        trainingSubmode: 'learn-primer',
        selectedCardStatus: 'needs_primer',
      },
      phase: 'learn',
      needsPrimer: true,
    },
    {
      name: 'keeps an active practice card in try',
      input: { cardType: 'practice', selectedCardStatus: 'active' },
      phase: 'try',
    },
    {
      name: 'moves an implemented practice card into verification before reflection',
      input: { cardType: 'practice', selectedCardStatus: 'implemented' },
      phase: 'verify',
      verificationPending: true,
      verificationReason: 'practice_completed',
    },
    {
      name: 'keeps a learner-reported practice result in verification until it is checked',
      input: {
        cardType: 'practice',
        selectedCardStatus: 'active',
        latestTrainingHandoffStatus: 'needs_verification',
        latestTrainingNextHopStatus: 'verification_required',
      },
      phase: 'verify',
      verificationPending: true,
      verificationReason: 'practice_completed',
    },
    {
      name: 'moves recorded verification evidence into reflection',
      input: { cardType: 'practice', latestVerifiedResult: 'Focused checks passed.' },
      phase: 'reflect',
      verified: true,
      verificationPending: false,
      verificationReason: 'evidence_recorded',
      reflectReason: 'verification_passed',
    },
    {
      name: 'uses the current handoff reflection requirement ahead of an active card status',
      input: {
        cardType: 'practice',
        selectedCardStatus: 'active',
        latestTrainingHandoffStatus: 'needs_reflection',
        latestTrainingNextHopStatus: 'reflection_required',
      },
      phase: 'reflect',
      verified: true,
      reflectReason: 'verification_passed',
    },
    {
      name: 'uses the current handoff return requirement ahead of an active card status',
      input: {
        cardType: 'practice',
        selectedCardStatus: 'active',
        latestTrainingHandoffStatus: 'ready_to_return',
        latestTrainingNextHopStatus: 'return_required',
      },
      phase: 'return',
      verified: true,
    },
    {
      name: 'moves a reviewed card into reflect after verification',
      input: { cardType: 'practice', selectedCardStatus: 'reviewed' },
      phase: 'reflect',
      reflectReason: 'reviewed',
    },
    {
      name: 'keeps an incorrect flash answer in retry primer mode',
      input: { cardType: 'flash', selectedCardStatus: 'needs_primer' },
      phase: 'learn',
      needsPrimer: true,
      flashAnswered: false,
      verified: false,
      verificationPending: false,
    },
    {
      name: 'uses answer then verify for flash cards',
      input: { cardType: 'flash', selectedCardStatus: 'answered' },
      phase: 'verify',
      flashAnswered: true,
      verificationPending: true,
      verificationReason: 'flash_answered',
    },
    {
      name: 'keeps an unanswered flash card in answer',
      input: { cardType: 'flash', selectedCardStatus: 'active' },
      phase: 'answer',
    },
    {
      name: 'lets current recovery override stale verification evidence',
      input: {
        cardType: 'practice',
        selectedCardStatus: 'blocked',
        latestVerifiedResult: 'An earlier attempt passed.',
      },
      phase: 'reflect',
      reflectReason: 'blocked',
    },
    {
      name: 'lets terminal backflow override an in-flight verification handoff',
      input: {
        cardType: 'practice',
        latestTrainingHandoffStatus: 'verified',
        latestTrainingNextHopStatus: 'continued_in_chat',
      },
      phase: 'return',
    },
  ];

  for (const { name, input, ...expected } of cases) {
    const state = deriveTrainingExecutionState(input);

    assert.equal(state.composerPhase, expected.phase, name);
    for (const [key, value] of Object.entries(expected)) {
      if (key !== 'phase') {
        assert.equal(state[key], value, name);
      }
    }
  }
});

test('derives verification truth from the evidence lifecycle in precedence order', () => {
  const cases = [
    {
      name: 'awaits evidence after a practice implementation',
      input: { cardType: 'practice', selectedCardStatus: 'implemented' },
      verification: { status: 'awaiting_evidence', source: 'card_status', evidenceRecorded: false },
      phase: 'verify',
      verified: false,
      verificationPending: true,
      verificationReason: 'practice_completed',
    },
    {
      name: 'awaits evidence after a flash answer',
      input: { cardType: 'flash', selectedCardStatus: 'answered' },
      verification: { status: 'awaiting_evidence', source: 'flash_answer', evidenceRecorded: false },
      phase: 'verify',
      verified: false,
      verificationPending: true,
      verificationReason: 'flash_answered',
    },
    {
      name: 'uses a concrete verified result over an implementation status',
      input: {
        cardType: 'practice',
        selectedCardStatus: 'implemented',
        latestVerifiedResult: 'Focused route test passed.',
      },
      verification: { status: 'passed', source: 'verified_result', evidenceRecorded: true },
      phase: 'reflect',
      verified: true,
      verificationPending: false,
      verificationReason: 'evidence_recorded',
      reflectReason: 'verification_passed',
    },
    {
      name: 'uses a verified handoff when no result text is available',
      input: { cardType: 'practice', latestTrainingHandoffStatus: 'verified' },
      verification: { status: 'passed', source: 'handoff', evidenceRecorded: true },
      phase: 'reflect',
      verified: true,
      verificationPending: false,
      verificationReason: 'evidence_recorded',
      reflectReason: 'verification_passed',
    },
    {
      name: 'does not let an active card inherit an unscoped earlier result',
      input: {
        cardType: 'practice',
        selectedCardStatus: 'active',
        latestVerifiedResult: 'A previous card passed.',
      },
      verification: { status: 'not_started', source: 'none', evidenceRecorded: false },
      phase: 'try',
      verified: false,
      verificationPending: false,
    },
    {
      name: 'lets a current blocker override stale passing evidence',
      input: {
        cardType: 'practice',
        selectedCardStatus: 'implemented',
        latestVerifiedResult: 'Earlier attempt passed.',
        latestLearningBlocker: 'Current focused check failed.',
      },
      verification: { status: 'failed', source: 'blocker', evidenceRecorded: true },
      phase: 'reflect',
      verified: false,
      verificationPending: false,
      reflectReason: 'blocked',
    },
    {
      name: 'keeps a reviewed legacy card honest when no evidence was recorded',
      input: { cardType: 'practice', selectedCardStatus: 'reviewed' },
      verification: { status: 'evidence_missing', source: 'card_status', evidenceRecorded: false },
      phase: 'reflect',
      verified: false,
      verificationPending: false,
      reflectReason: 'reviewed',
    },
    {
      name: 'failed return evidence write stays unverified',
      input: {
        cardType: 'practice',
        selectedCardStatus: 'active',
        latestTrainingHandoffStatus: 'unverified',
        latestTrainingNextHopStatus: 'evidence_unverified',
      },
      verification: { status: 'evidence_missing', source: 'handoff', evidenceRecorded: false },
      phase: 'return',
      verified: false,
      verificationPending: false,
    },
    {
      name: 'lets completed return backflow override an open verification state',
      input: {
        cardType: 'practice',
        selectedCardStatus: 'implemented',
        latestTrainingHandoffStatus: 'verified',
        latestTrainingNextHopStatus: 'continued_in_chat',
      },
      verification: { status: 'passed', source: 'handoff', evidenceRecorded: true },
      phase: 'return',
      verified: true,
      verificationPending: false,
      verificationReason: 'evidence_recorded',
    },
  ];

  for (const { name, input, verification, phase, ...expected } of cases) {
    const state = deriveTrainingExecutionState(input);

    assert.equal(state.composerPhase, phase, name);
    assert.deepEqual(state.verification, verification, name);
    for (const [key, value] of Object.entries(expected)) {
      assert.equal(state[key], value, name);
    }
  }
});

test('skipped practice cards reflect without being treated as blocked', () => {
  const state = deriveTrainingExecutionState({
    cardType: 'practice',
    selectedCardStatus: 'skipped',
  });

  assert.equal(state.skipped, true);
  assert.equal(state.blocked, false);
  assert.equal(state.composerPhase, 'reflect');
  assert.equal(state.reflectReason, 'skipped');
});

test('flash answers await verification before reflection', () => {
  const state = deriveTrainingExecutionState({
    cardType: 'flash',
    selectedCardStatus: 'answered',
  });

  assert.equal(state.flashAnswered, true);
  assert.equal(state.blocked, false);
  assert.equal(state.composerPhase, 'verify');
  assert.equal(state.verificationReason, 'flash_answered');
});

test('verified evidence remains pending plan confirmation until training return', () => {
  const practice = deriveTrainingExecutionState({
    cardType: 'practice',
    latestVerifiedResult: 'IDE checks passed',
  });
  const flash = deriveTrainingExecutionState({
    cardType: 'flash',
    latestVerifiedResult: 'answer checked',
  });

  for (const state of [practice, flash]) {
    assert.equal(state.verification.evidenceRecorded, true);
    assert.equal(state.verified, true);
    // Recorded evidence is not formal Plan adoption; that remains pending.
    assert.equal(state.pendingPlanConfirmation, true);
    assert.equal(state.composerPhase, 'reflect');
  }
});

test('persisted learning phase wins over stale card status', () => {
  const state = deriveTrainingExecutionState({
    cardType: 'practice',
    selectedCardStatus: 'active',
    learningPhase: 'reflect',
  });

  assert.equal(state.composerPhase, 'reflect');
  assert.equal(state.selectedStatus, 'active');
});

test('persisted learn phase keeps an active card in learn', () => {
  const state = deriveTrainingExecutionState({
    cardType: 'practice',
    selectedCardStatus: 'active',
    learningPhase: 'learn',
  });

  assert.equal(state.composerPhase, 'learn');
});

test('persisted try maps unanswered flash cards to answer', () => {
  const state = deriveTrainingExecutionState({
    cardType: 'flash',
    selectedCardStatus: 'active',
    learningPhase: 'try',
  });

  assert.equal(state.composerPhase, 'answer');
});

test('verified cards return only after their backflow is recorded', () => {
  const practice = deriveTrainingExecutionState({
    cardType: 'practice',
    selectedCardStatus: 'implemented',
    latestTrainingNextHopStatus: 'continued_in_chat',
  });
  const flash = deriveTrainingExecutionState({
    cardType: 'flash',
    latestVerifiedResult: 'rule retained',
    latestTrainingHandoffStatus: 'resolved',
  });

  assert.equal(practice.verified, true);
  assert.equal(practice.composerPhase, 'return');
  assert.equal(flash.verified, true);
  assert.equal(flash.composerPhase, 'return');
});
