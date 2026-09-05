'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildTrainingRecoveryRoute,
  buildTrainingRestoreOrchestrationSteps,
} = require('../dist/shared/src/trainingRecoveryGovernance.js');

test('buildTrainingRecoveryRoute creates a governed recovery sequence before returning to project practice', () => {
  const route = buildTrainingRecoveryRoute({
    latestTrainingSubmode: 'review',
    latestFlashcardRecoveryMode: 'flashcards',
    latestLearningFocusArea: 'dependency injection',
    latestLearningScenario: 'FastAPI route dependency wiring',
    latestLearningBlocker: 'The learner still wires Depends into the wrong parameter boundary.',
    latestLearningFollowup: 'Return to the route slice after the minimum recovery loop.',
    reviewArtifact: {
      id: 'review-1',
      focusArea: 'dependency injection',
      scenario: 'FastAPI route dependency wiring',
      blocker: 'The route stalled because the dependency was attached at the wrong layer.',
      rootCause: 'Parameter semantics are still unstable.',
      nextSelfImplementationRule: 'Name the dependency boundary before writing the handler.',
      recommendedRecoveryMode: 'flashcards',
      recommendedActions: ['Review the dependency boundary, then rebuild the route slice.'],
      linkedDependencyKeys: ['fastapi'],
      linkedReviewConcepts: ['Depends'],
    },
    topSkillMap: {
      dependencyKey: 'fastapi',
      dependencyName: 'FastAPI Depends',
      masteryStage: 'recalled',
      masteryScore: 0.36,
      confidence: 0.38,
      coveredLayers: ['concept'],
      weakestLayers: ['parameter', 'scenario'],
      prioritySummary: 'Parameters and route boundary decisions still drift under pressure.',
      projectFirstCut: 'Return to the route handler and wire one dependency end-to-end yourself.',
      suggestedScenarioLab: 'Make one tiny app that injects a dependency into a single route.',
      items: [],
      topReviewItems: [
        {
          key: 'depends-parameter',
          label: 'Depends parameter semantics',
          layer: 'parameter',
          confidence: 0.2,
          answerModeHint: 'text',
          acceptedAnswers: ['Explain which parameter owns the dependency and why.'],
          evidence: [],
          gaps: ['The learner still mixes up where Depends should be attached.'],
          nextActions: ['Answer one parameter card without looking at notes.'],
          relatedApi: 'Depends',
          scenario: 'FastAPI route dependency wiring',
          sourceKinds: ['flashcard_failure'],
        },
        {
          key: 'depends-scenario',
          label: 'Route dependency minimum scenario',
          layer: 'scenario',
          confidence: 0.22,
          answerModeHint: 'text',
          acceptedAnswers: ['Build one route and one dependency in isolation.'],
          evidence: [],
          gaps: ['The concept exists but collapses in a real route.'],
          nextActions: ['Build the smallest route + dependency lab and verify it.'],
          relatedApi: 'Depends',
          scenario: 'FastAPI route dependency wiring',
          sourceKinds: ['weakness'],
        },
      ],
    },
    topSkillItems: [
      {
        key: 'depends-parameter',
        label: 'Depends parameter semantics',
        layer: 'parameter',
        confidence: 0.2,
        answerModeHint: 'text',
        acceptedAnswers: ['Explain which parameter owns the dependency and why.'],
        evidence: [],
        gaps: ['The learner still mixes up where Depends should be attached.'],
        nextActions: ['Answer one parameter card without looking at notes.'],
        relatedApi: 'Depends',
        scenario: 'FastAPI route dependency wiring',
        sourceKinds: ['flashcard_failure'],
      },
      {
        key: 'depends-scenario',
        label: 'Route dependency minimum scenario',
        layer: 'scenario',
        confidence: 0.22,
        answerModeHint: 'text',
        acceptedAnswers: ['Build one route and one dependency in isolation.'],
        evidence: [],
        gaps: ['The concept exists but collapses in a real route.'],
        nextActions: ['Build the smallest route + dependency lab and verify it.'],
        relatedApi: 'Depends',
        scenario: 'FastAPI route dependency wiring',
        sourceKinds: ['weakness'],
      },
    ],
    theoryWeakItems: [
      {
        key: 'depends-parameter',
        label: 'Depends parameter semantics',
        layer: 'parameter',
        confidence: 0.2,
        answerModeHint: 'text',
        acceptedAnswers: ['Explain which parameter owns the dependency and why.'],
        evidence: [],
        gaps: ['The learner still mixes up where Depends should be attached.'],
        nextActions: ['Answer one parameter card without looking at notes.'],
        relatedApi: 'Depends',
        scenario: 'FastAPI route dependency wiring',
        sourceKinds: ['flashcard_failure'],
      },
    ],
    practiceWeakItems: [
      {
        key: 'depends-scenario',
        label: 'Route dependency minimum scenario',
        layer: 'scenario',
        confidence: 0.22,
        answerModeHint: 'text',
        acceptedAnswers: ['Build one route and one dependency in isolation.'],
        evidence: [],
        gaps: ['The concept exists but collapses in a real route.'],
        nextActions: ['Build the smallest route + dependency lab and verify it.'],
        relatedApi: 'Depends',
        scenario: 'FastAPI route dependency wiring',
        sourceKinds: ['weakness'],
      },
    ],
    recentNeedsMorePractice: [
      {
        actionId: 'rq-1',
        concept: 'Depends',
        action: 'reset',
        outcome: 'needs_more_practice',
        focusArea: 'dependency injection',
        note: 'The learner still needs one tighter recovery loop.',
        createdAt: '2026-05-14T10:00:00Z',
      },
    ],
    topDueReview: {
      concept: 'Depends',
      reason: 'Return to the dependency boundary and verify the route slice.',
      source: 'weakness',
      severity: 'high',
      surfaceMode: 'due',
      focusArea: 'dependency injection',
      taskHint: 'Queue the route dependency slice and verify it before widening scope.',
    },
    reviewRecoveryCandidate: {
      mode: 'focus_area_batch',
      item: {
        concept: 'Depends',
        reason: 'The same dependency lane keeps resurfacing.',
        source: 'weakness',
        severity: 'high',
        surfaceMode: 'due',
        focusArea: 'dependency injection',
        taskHint: 'Recover the whole focus area together.',
      },
      focusArea: 'dependency injection',
      itemCount: 2,
      highCount: 2,
      dueCount: 1,
      weaknessCount: 2,
      needsMorePracticeCount: 1,
      recentActionCount: 2,
      recoveryScore: 18,
    },
  });

  assert.equal(route.recommendedStartSubmode, 'review');
  assert.equal(route.steps[0].kind, 'review');
  assert.equal(route.steps[1].kind, 'flashcards');
  assert.equal(route.steps[2].kind, 'scenario_lab');
  assert.equal(route.steps[3].kind, 'review_queue_batch');
  assert.equal(route.steps.at(-1).kind, 'project_return');
  assert.match(route.stallReason, /dependency/i);
  assert.match(route.returnTarget, /route/i);
});

test('buildTrainingRecoveryRoute can start from the review queue and still end at project practice', () => {
  const route = buildTrainingRecoveryRoute({
    latestTrainingSubmode: 'review_queue',
    latestLearningFocusArea: 'state restore',
    latestLearningFollowup: 'Rebuild one restore path in the project after recovery.',
    topDueReview: {
      concept: 'restore history',
      reason: 'The learner keeps forgetting the restore ordering.',
      source: 'reflection',
      severity: 'medium',
      surfaceMode: 'due',
      focusArea: 'state restore',
      taskHint: 'Pull one restore-history case into training and verify the order.',
    },
    reviewRecoveryCandidate: {
      mode: 'single_item',
      item: {
        concept: 'restore history',
        reason: 'One concrete restore-history point is due now.',
        source: 'reflection',
        severity: 'medium',
        surfaceMode: 'due',
        focusArea: 'state restore',
        taskHint: 'Recover the restore-history sequence first.',
      },
      focusArea: 'state restore',
      itemCount: 1,
      highCount: 0,
      dueCount: 1,
      weaknessCount: 0,
      needsMorePracticeCount: 0,
      recentActionCount: 0,
      recoveryScore: 5,
    },
  });

  assert.equal(route.recommendedStartSubmode, 'review_queue');
  assert.equal(route.steps[0].kind, 'review_queue_item');
  assert.equal(route.steps.at(-1).targetSubmode, 'practice');
});

test('buildTrainingRestoreOrchestrationSteps keeps multiple dependency histories in one governed sequence', () => {
  const steps = buildTrainingRestoreOrchestrationSteps({
    currentDependencyKey: 'fastapi',
    maxSteps: 4,
    dependencySkillMapHistory: [
      {
        entryId: 'react-history-4',
        dependencyKey: 'react',
        dependencyName: 'React',
        action: 'mark_practiced',
        version: 4,
        masteryStage: 'practiced',
        beforeSnapshot: { dependency_key: 'react', mastery_stage: 'recalled' },
        afterSnapshot: { dependency_key: 'react', mastery_stage: 'practiced' },
        createdAt: '2026-05-16T08:00:00Z',
      },
      {
        entryId: 'fastapi-history-2',
        dependencyKey: 'fastapi',
        dependencyName: 'FastAPI',
        action: 'send_to_flashcards',
        version: 2,
        masteryStage: 'recalled',
        beforeSnapshot: { dependency_key: 'fastapi', mastery_stage: 'understood' },
        afterSnapshot: { dependency_key: 'fastapi', mastery_stage: 'recalled' },
        createdAt: '2026-05-16T09:00:00Z',
      },
      {
        entryId: 'fastapi-history-1',
        dependencyKey: 'fastapi',
        dependencyName: 'FastAPI',
        action: 'synced',
        version: 1,
        masteryStage: 'understood',
        beforeSnapshot: { dependency_key: 'fastapi', mastery_stage: 'understood' },
        afterSnapshot: { dependency_key: 'fastapi', mastery_stage: 'understood' },
        createdAt: '2026-05-15T09:00:00Z',
      },
      {
        entryId: 'audit-only',
        dependencyKey: 'zod',
        dependencyName: 'Zod',
        action: 'mark_practiced',
        version: 3,
        masteryStage: 'practiced',
        createdAt: '2026-05-16T10:00:00Z',
      },
    ],
    scenarioLabHistory: [
      {
        entryId: 'scenario-history-3',
        scenarioLabId: 'scenario-1',
        action: 'started',
        status: 'in_progress',
        version: 3,
        beforeSnapshot: { id: 'scenario-1', status: 'ready' },
        afterSnapshot: { id: 'scenario-1', status: 'in_progress' },
        createdAt: '2026-05-16T10:30:00Z',
      },
    ],
    theoryDrillHistory: [
      {
        entryId: 'theory-history-2',
        theoryDrillId: 'theory-1',
        action: 'submitted',
        status: 'in_progress',
        version: 2,
        beforeSnapshot: { id: 'theory-1', current_question_index: 0 },
        afterSnapshot: { id: 'theory-1', current_question_index: 1 },
        createdAt: '2026-05-16T10:35:00Z',
      },
    ],
    reviewArtifactHistory: [
      {
        entryId: 'review-history-2',
        reviewArtifactId: 'review-1',
        action: 'updated',
        status: 'active',
        version: 2,
        beforeSnapshot: { id: 'review-1', blocker: 'old' },
        afterSnapshot: { id: 'review-1', blocker: 'new' },
        createdAt: '2026-05-16T10:40:00Z',
      },
    ],
  });

  assert.deepEqual(
    steps.map((step) => `${step.action}:${step.entryId}`),
    [
      'restore_dependency_skill_map:fastapi-history-2',
      'restore_dependency_skill_map:react-history-4',
      'restore_scenario_lab:scenario-history-3',
      'restore_theory_drill:theory-history-2',
    ],
  );
  assert.equal(steps[0].dependencyKey, 'fastapi');
  assert.equal(steps[1].dependencyKey, 'react');
  assert.ok(!steps.some((step) => step.entryId === 'audit-only'));
});

test('buildTrainingRestoreOrchestrationSteps restores latest non-dependency training assets first', () => {
  const steps = buildTrainingRestoreOrchestrationSteps({
    currentDependencyKey: 'fastapi',
    maxSteps: 4,
    dependencySkillMapHistory: [
      {
        entryId: 'fastapi-history-1',
        dependencyKey: 'fastapi',
        dependencyName: 'FastAPI',
        action: 'mark_practiced',
        version: 1,
        masteryStage: 'practiced',
        beforeSnapshot: { dependency_key: 'fastapi', mastery_stage: 'recalled' },
        afterSnapshot: { dependency_key: 'fastapi', mastery_stage: 'practiced' },
        createdAt: '2026-05-15T08:00:00Z',
      },
    ],
    scenarioLabHistory: [
      {
        entryId: 'scenario-old',
        scenarioLabId: 'scenario-1',
        action: 'started',
        status: 'in_progress',
        version: 1,
        beforeSnapshot: { id: 'scenario-1', status: 'ready' },
        afterSnapshot: { id: 'scenario-1', status: 'in_progress' },
        createdAt: '2026-05-15T08:10:00Z',
      },
      {
        entryId: 'scenario-new',
        scenarioLabId: 'scenario-1',
        action: 'completed',
        status: 'completed',
        version: 3,
        beforeSnapshot: { id: 'scenario-1', status: 'in_progress' },
        afterSnapshot: { id: 'scenario-1', status: 'completed' },
        createdAt: '2026-05-16T08:10:00Z',
      },
    ],
    theoryDrillHistory: [
      {
        entryId: 'theory-old',
        theoryDrillId: 'theory-1',
        action: 'submitted',
        status: 'in_progress',
        version: 1,
        beforeSnapshot: { id: 'theory-1', current_question_index: 0 },
        afterSnapshot: { id: 'theory-1', current_question_index: 1 },
        createdAt: '2026-05-15T08:20:00Z',
      },
      {
        entryId: 'theory-new',
        theoryDrillId: 'theory-1',
        action: 'completed',
        status: 'completed',
        version: 4,
        beforeSnapshot: { id: 'theory-1', current_question_index: 2 },
        afterSnapshot: { id: 'theory-1', current_question_index: 3 },
        createdAt: '2026-05-16T08:20:00Z',
      },
    ],
    reviewArtifactHistory: [
      {
        entryId: 'review-old',
        reviewArtifactId: 'review-1',
        action: 'reviewed',
        status: 'active',
        version: 1,
        beforeSnapshot: { id: 'review-1', blocker: 'old' },
        afterSnapshot: { id: 'review-1', blocker: 'still old' },
        createdAt: '2026-05-15T08:30:00Z',
      },
      {
        entryId: 'review-new',
        reviewArtifactId: 'review-1',
        action: 'resolved',
        status: 'resolved',
        version: 5,
        beforeSnapshot: { id: 'review-1', blocker: 'new' },
        afterSnapshot: { id: 'review-1', blocker: 'resolved' },
        createdAt: '2026-05-16T08:30:00Z',
      },
    ],
  });

  assert.deepEqual(
    steps.map((step) => `${step.action}:${step.entryId}`),
    [
      'restore_dependency_skill_map:fastapi-history-1',
      'restore_scenario_lab:scenario-new',
      'restore_theory_drill:theory-new',
      'restore_review_artifact:review-new',
    ],
  );
});
