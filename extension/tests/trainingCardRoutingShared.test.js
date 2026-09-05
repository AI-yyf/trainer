'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildTrainingCardRouting,
} = require('../dist/shared/src/trainingCardRouting.js');

function baseCandidate(overrides) {
  return {
    id: 'practice-1',
    type: 'practice',
    title: 'Implement one FastAPI route slice',
    prompt: 'Create the route yourself and bring back the verification output.',
    createdFrom: 'plan',
    sourceChain: ['plan:s2', 'dependency:fastapi'],
    scoreFactors: {
      planRelevance: 0.8,
      blockingPower: 0.7,
      evidenceGap: 0.72,
      recencyNeed: 0.5,
      resourceTrust: 0.8,
      difficultyFit: 0.74,
      projectFit: 0.82,
      transferValue: 0.4,
      recoveryPriority: 0.5,
      repeatedWeaknessPriority: 0,
    },
    coachOnly: true,
    hasPrompt: true,
    hasDeliverable: true,
    hasVerification: true,
    ...overrides,
  };
}

test('buildTrainingCardRouting selects the highest eligible active card with explanation', () => {
  const route = buildTrainingCardRouting({
    currentSubmode: 'practice',
    candidates: [
      baseCandidate({
        id: 'practice-low',
        title: 'Lower priority practice',
        scoreFactors: {
          planRelevance: 0.5,
          blockingPower: 0.3,
          evidenceGap: 0.4,
          recencyNeed: 0.2,
          resourceTrust: 0.8,
          difficultyFit: 0.8,
          projectFit: 0.7,
          transferValue: 0.2,
          recoveryPriority: 0.2,
        },
      }),
      baseCandidate({
        id: 'practice-high',
        title: 'Recover response_model through one route',
        whyNow: 'This card unlocks the current FastAPI blocker.',
        scenarioPack: 'remote_workspace',
        nextAfterCompletion: 'Record the verification evidence.',
      }),
    ],
  });

  assert.equal(route.selectedCardId, 'practice-high');
  assert.equal(route.selectedCard.type, 'practice');
  assert.equal(route.selectedCard.scenarioPack, 'remote_workspace');
  assert.equal(route.selectedCard.nextAfterCompletion, 'Record the verification evidence.');
  assert.equal(route.nextAfterCompletion, 'Record the verification evidence.');
  assert.match(route.whyThisCard, /unlocks/i);
  assert.ok(route.selectionScore > 60);
  assert.equal(route.eligibleCount, 2);
  assert.ok(route.whyNotOthers.some((item) => item.includes('Lower priority practice')));
});

test('buildTrainingCardRouting keeps the current deck authoritative when it has eligible cards', () => {
  const route = buildTrainingCardRouting({
    currentSubmode: 'flash',
    candidates: [
      baseCandidate({
        id: 'practice-higher-score',
        title: 'Higher score practice',
        scoreFactors: {
          planRelevance: 1,
          blockingPower: 1,
          evidenceGap: 1,
          recencyNeed: 1,
          resourceTrust: 1,
          difficultyFit: 1,
          projectFit: 1,
          transferValue: 1,
          recoveryPriority: 1,
        },
      }),
      {
        id: 'flash-ready',
        type: 'flash',
        title: 'Recall Depends boundary',
        prompt: 'When should Depends be introduced?',
        createdFrom: 'dependency_mastery',
        sourceChain: ['dependency:fastapi'],
        scoreFactors: {
          planRelevance: 0.58,
          blockingPower: 0.6,
          evidenceGap: 0.62,
          recencyNeed: 0.7,
          resourceTrust: 0.8,
          difficultyFit: 0.74,
          projectFit: 0.7,
          transferValue: 0.32,
          recoveryPriority: 0.66,
        },
        coachOnly: true,
        hasPrompt: true,
        hasReferenceAnswer: true,
        hasRubric: true,
        hasHintLadder: true,
      },
    ],
  });

  assert.equal(route.selectedCardId, 'flash-ready');
  assert.equal(route.selectedCard.type, 'flash');
  assert.ok(route.whyNotOthers.some((item) => item.includes('current deck is flash')));
});

test('buildTrainingCardRouting blocks unsafe or incomplete candidates before scoring', () => {
  const route = buildTrainingCardRouting({
    currentSubmode: 'practice',
    candidates: [
      baseCandidate({
        id: 'unsafe-practice',
        title: 'Trainer edits the project directly',
        coachOnly: false,
        scoreFactors: {
          planRelevance: 1,
          blockingPower: 1,
          evidenceGap: 1,
          recencyNeed: 1,
          resourceTrust: 1,
          difficultyFit: 1,
          projectFit: 1,
          transferValue: 1,
          recoveryPriority: 1,
        },
      }),
      {
        id: 'flash-missing-answer',
        type: 'flash',
        title: 'Missing answer flash card',
        prompt: 'What does response_model validate?',
        createdFrom: 'dependency_mastery',
        sourceChain: ['dependency:fastapi'],
        scoreFactors: {
          planRelevance: 0.9,
          blockingPower: 0.9,
          evidenceGap: 0.9,
          recencyNeed: 0.9,
          resourceTrust: 0.9,
          difficultyFit: 0.9,
          projectFit: 0.9,
          transferValue: 0.4,
          recoveryPriority: 0.9,
        },
        coachOnly: true,
        hasPrompt: true,
        hasReferenceAnswer: false,
        hasRubric: true,
        hasHintLadder: true,
      },
    ],
  });

  assert.equal(route.selectedCardId, undefined);
  assert.equal(route.eligibleCount, 0);
  assert.equal(route.blockedCandidates.length, 2);
  assert.match(route.blockedCandidates[0].reasons.join(' '), /coach-only/i);
  assert.match(route.blockedCandidates[1].reasons.join(' '), /reference answer/i);
});

test('buildTrainingCardRouting respects pure conversation mode and does not force training', () => {
  const route = buildTrainingCardRouting({
    pureConversationMode: true,
    currentSubmode: 'practice',
    candidates: [baseCandidate({ id: 'practice-ready' })],
  });

  assert.equal(route.selectedCardId, undefined);
  assert.equal(route.eligibleCount, 0);
  assert.match(route.whyThisCard, /pure conversation/i);
});

test('buildTrainingCardRouting exposes stale resource blockers', () => {
  const route = buildTrainingCardRouting({
    currentSubmode: 'flash',
    candidates: [
      {
        id: 'flash-stale-resource',
        type: 'flash',
        title: 'Old API behavior card',
        prompt: 'What changed in this API?',
        createdFrom: 'resource',
        sourceChain: ['resource:old-api-doc'],
        scoreFactors: {
          planRelevance: 1,
          blockingPower: 1,
          evidenceGap: 1,
          recencyNeed: 1,
          resourceTrust: 0,
          difficultyFit: 1,
          projectFit: 1,
          transferValue: 1,
          recoveryPriority: 1,
        },
        coachOnly: true,
        hasPrompt: true,
        hasReferenceAnswer: true,
        hasRubric: true,
        hasHintLadder: true,
        trustState: 'stale',
        trustAcknowledged: false,
      },
    ],
  });

  assert.equal(route.selectedCardId, undefined);
  assert.equal(route.blockedCandidates[0].cardId, 'flash-stale-resource');
  assert.match(route.blockedCandidates[0].reasons.join(' '), /trusted|fresh/i);
});

test('buildTrainingCardRouting lets repeated weakness priority break otherwise close card ties', () => {
  const route = buildTrainingCardRouting({
    currentSubmode: 'practice',
    candidates: [
      baseCandidate({
        id: 'practice-standard',
        title: 'Standard route slice',
        scoreFactors: {
          planRelevance: 0.8,
          blockingPower: 0.7,
          evidenceGap: 0.72,
          recencyNeed: 0.5,
          resourceTrust: 0.8,
          difficultyFit: 0.74,
          projectFit: 0.82,
          transferValue: 0.4,
          recoveryPriority: 0.5,
          repeatedWeaknessPriority: 0,
        },
      }),
      baseCandidate({
        id: 'practice-repeated-weakness',
        title: 'Stop widening scope before verification',
        repeatedWeaknessKey: 'scope control',
        repeatedWeaknessSummary: 'Scope control repeats across 2 workspace(s).',
        scoreFactors: {
          planRelevance: 0.8,
          blockingPower: 0.7,
          evidenceGap: 0.72,
          recencyNeed: 0.5,
          resourceTrust: 0.8,
          difficultyFit: 0.74,
          projectFit: 0.82,
          transferValue: 0.4,
          recoveryPriority: 0.5,
          repeatedWeaknessPriority: 1,
        },
      }),
    ],
  });

  assert.equal(route.selectedCardId, 'practice-repeated-weakness');
  assert.equal(route.selectedCard.repeatedWeaknessKey, 'scope control');
  assert.equal(route.selectedCard.repeatedWeaknessSummary, 'Scope control repeats across 2 workspace(s).');
  assert.equal(route.selectedCard.scoreFactors.repeatedWeaknessPriority, 1);
  assert.ok(route.selectionScore > 0);
});
