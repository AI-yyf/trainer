'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const workbenchDataModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'workbenchData.js',
);

const {
  createDefaultBootstrapData,
  mergeMemorySummary,
  mergeSessionMessage,
} = require(workbenchDataModulePath);

function createWorkspaceSnapshot() {
  return {
    trusted: true,
    workspaceFolder: 'F:\\trainer',
    activeFile: 'F:\\trainer\\server\\app\\main.py',
  };
}

function createProvider() {
  return {
    name: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    apiKeyRef: 'trainer.default',
    model: 'demo-model',
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: true,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
  };
}

function createSidecarStatus() {
  return {
    lifecycle: 'ready',
    host: '127.0.0.1',
    port: 34891,
    canStart: true,
  };
}

function createBootstrap() {
  return createDefaultBootstrapData(
    createWorkspaceSnapshot(),
    createProvider(),
    createSidecarStatus(),
  );
}

test('mergeMemorySummary maps authoritative workspace training state from memory snapshots', () => {
  const bootstrap = createBootstrap();

  const patch = mergeMemorySummary(bootstrap, {
    memory: {
      workspace: {
        workspace_id: 'F:\\trainer',
        latest_conversation_handoff: {
          candidate_id: 'candidate-conversation-1',
          continue_in: 'training',
          card_title: 'Bridge the route boundary',
          learner_deliverables: ['Restate the route boundary before touching code.'],
        },
        latest_training_handoff: {
          handoff_id: 'handoff-practice-1',
          candidate_id: 'candidate-practice-1',
          continue_in: 'training',
          card_type: 'practice',
          card_title: 'Practice dependency boundary',
          scenario_pack: 'remote_workspace',
          learner_deliverables: [
            'Implement one route with a single dependency boundary.',
          ],
          verification_steps: ['Run the minimum route test.'],
          return_with: 'Bring back the test output and one open question.',
          next_after_completion: 'Return with the route diff and the test output.',
        },
        latest_training_next_hop: {
          candidate_id: 'candidate-practice-2',
          candidate_type: 'practice_candidate',
          continue_in: 'training',
          target_kind: 'training_card',
          target_id: 'card-practice-2',
          status: 'verification_required',
          why_now: 'Keep the same boundary and verify it one more time.',
          scenario_pack: 'remote_workspace',
        },
        latest_training_submode: 'practice',
        latest_learning_focus_area: 'dependency injection',
        latest_learning_followup: 'Return with the route diff and the test output.',
        latest_learning_verified_result:
          'One route now respects the dependency boundary.',
        latest_learning_blocker: 'Still mixing service creation into the route.',
        latest_learning_partial_progress: 'The dependency function already exists.',
        latest_learning_abandon_reason: 'Scope widened too early.',
        selected_card_id: 'card-practice-1',
        selected_card_type: 'practice',
        selected_card_title: 'Practice dependency boundary',
        selected_card_status: 'active',
      },
      training_card_candidates: [
        {
          card_id: 'card-practice-1',
          card_type: 'practice',
          title: 'Practice dependency boundary',
          question: 'What boundary should this route keep stable first?',
          scenario_pack: 'remote_workspace',
          why_now: 'Highest leverage next card.',
          status: 'active',
          api_hints: ['debounceSearch(input)'],
          learner_deliverables: [
            'Implement `debounceSearch` and keep normalizedQuery updated.',
          ],
          verification_steps: ['Confirm debounceSearch is called from the current IDE file.'],
          return_with: 'Bring back the route diff plus one blocker you still had to reason through.',
          next_after_completion: 'Return with the route diff and the test output.',
          stuck_recovery: 'If the boundary is blurry again, write down one input, one output, and one owner.',
          reflection_prompt: 'What changed once you separated the dependency boundary from the route?',
          hint_ladder: [
            'Find the smallest boundary first.',
            'Then verify only the current file.',
          ],
          common_mistakes: [
            'Mixing service creation into the route.',
            'Trying to solve two boundaries at once.',
          ],
          expected_symbols: ['debounceSearch', 'normalizedQuery'],
          files_to_touch: ['extension/webview/src/search.ts'],
        },
        {
          card_id: 'card-flash-1',
          card_type: 'flash',
          title: 'Flash dependency boundary',
          question: 'Which call site proves the dependency boundary is correct?',
          options: ['The route call site', 'The package.json file'],
          answer_mode: 'choice',
          expected_answer: 'The route call site proves the boundary.',
          scenario_pack: 'remote_workspace',
          why_now: 'Keep the same boundary in memory.',
          status: 'candidate',
        },
      ],
      active_training_card_routing: {
        selected_card_id: 'card-practice-1',
        selected_card: {
          card_id: 'card-practice-1',
          type: 'practice',
          title: 'Practice dependency boundary',
          question: 'What boundary should this route keep stable first?',
          scenario_pack: 'remote_workspace',
          next_after_completion: 'Return with the route diff and the test output.',
          expected_symbols: ['debounceSearch'],
          api_hints: ['normalizedQuery'],
        },
        why_this_card: 'Highest leverage next card.',
        next_after_completion: 'Return with the route diff and the test output.',
        candidate_count: 3,
        eligible_count: 1,
        blocked_candidates: [
          {
            card_id: 'card-flash-1',
            type: 'flash',
            title: 'Recall route boundary',
            reasons: ['needs more evidence'],
          },
        ],
      },
      training_event_ledger: [
        {
          event_id: 'ledger-1',
          event_type: 'training_next_hop_materialized',
          candidate_id: 'candidate-practice-2',
          candidate_type: 'practice_candidate',
          candidate_status: 'surfaced',
          selected_card_title: 'Practice dependency boundary',
          expected_symbols: ['debounceSearch'],
          files_to_touch: ['extension/webview/src/search.ts'],
          learner_deliverables: [
            'Implement one route with a single dependency boundary.',
          ],
          verification_steps: ['Run the minimum route test.'],
        },
      ],
      review_artifact: {
        id: 'review-1',
        title: 'Governed review',
        status: 'resolved',
        focus_area: 'dependency injection',
        verified_result: 'The route resolves the dependency correctly.',
        next_self_implementation_rule: 'Repeat the same route slice once more.',
      },
      scenario_lab: {
        id: 'scenario-1',
        title: 'Sandbox the dependency boundary',
        status: 'ready',
        learner_deliverables: ['Build one route plus one dependency.'],
        verification_steps: ['Call the route once.'],
        migrate_back_guidance: ['Move the same boundary back into the project.'],
      },
      theory_drill: {
        id: 'theory-1',
        title: 'Why this boundary?',
        status: 'in_progress',
        questions: [
          {
            question_id: 'q1',
            prompt:
              'Why does this dependency belong in the route instead of the service layer?',
          },
        ],
      },
      due_reviews: [
        {
          concept: 'fastapi Depends',
          reason: 'Review the boundary choice.',
          source: 'plan',
          severity: 'medium',
        },
      ],
    },
  });

  assert.equal(patch.workspaceTrainingState.workspaceId, 'F:\\trainer');
  assert.equal(patch.workspaceTrainingState.selectedCardId, 'card-practice-1');
  assert.equal(patch.workspaceTrainingState.selectedCardType, 'practice');
  assert.equal(patch.workspaceTrainingState.selectedCardStatus, 'active');
  assert.equal(
    patch.workspaceTrainingState.latestTrainingHandoff.learnerDeliverables[0],
    'Implement one route with a single dependency boundary.',
  );
  assert.equal(
    patch.workspaceTrainingState.latestTrainingHandoff.handoffId,
    'handoff-practice-1',
  );
  assert.equal(
    patch.workspaceTrainingState.latestTrainingHandoff.verificationSteps[0],
    'Run the minimum route test.',
  );
  assert.equal(
    patch.workspaceTrainingState.latestTrainingHandoff.nextAfterCompletion,
    'Return with the route diff and the test output.',
  );
  assert.equal(
    patch.workspaceTrainingState.latestTrainingHandoff.scenarioPack,
    'remote_workspace',
  );
  assert.equal(
    patch.workspaceTrainingState.latestTrainingNextHop.targetId,
    'card-practice-2',
  );
  assert.equal(
    patch.workspaceTrainingState.latestTrainingNextHop.status,
    'verification_required',
  );
  assert.equal(
    patch.workspaceTrainingState.latestTrainingNextHop.scenarioPack,
    'remote_workspace',
  );
  assert.equal(
    patch.workspaceTrainingState.activeTrainingCardRouting.whyThisCard,
    'Highest leverage next card.',
  );
  assert.equal(
    patch.workspaceTrainingState.trainingCardCandidates[0].cardId,
    'card-practice-1',
  );
  assert.equal(
    patch.workspaceTrainingState.trainingCardCandidates[0].question,
    'What boundary should this route keep stable first?',
  );
  assert.deepEqual(
    patch.workspaceTrainingState.trainingCardCandidates[0].expectedSymbols,
    ['debounceSearch', 'normalizedQuery'],
  );
  assert.deepEqual(
    patch.workspaceTrainingState.trainingCardCandidates[0].filesToTouch,
    ['extension/webview/src/search.ts'],
  );
  assert.equal(
    patch.workspaceTrainingState.trainingCardCandidates[0].returnWith,
    'Bring back the route diff plus one blocker you still had to reason through.',
  );
  assert.equal(
    patch.workspaceTrainingState.trainingCardCandidates[0].scenarioPack,
    'remote_workspace',
  );
  assert.equal(
    patch.workspaceTrainingState.trainingCardCandidates[1].question,
    'Which call site proves the dependency boundary is correct?',
  );
  assert.deepEqual(
    patch.workspaceTrainingState.trainingCardCandidates[1].choices,
    ['The route call site', 'The package.json file'],
  );
  assert.equal(
    patch.workspaceTrainingState.trainingCardCandidates[1].answerMode,
    'choice',
  );
  assert.equal(
    patch.workspaceTrainingState.trainingCardCandidates[1].expectedAnswer,
    'The route call site proves the boundary.',
  );
  assert.equal(
    patch.workspaceTrainingState.trainingCardCandidates[0].nextAfterCompletion,
    'Return with the route diff and the test output.',
  );
  assert.equal(
    patch.workspaceTrainingState.trainingCardCandidates[0].stuckRecovery,
    'If the boundary is blurry again, write down one input, one output, and one owner.',
  );
  assert.equal(
    patch.workspaceTrainingState.trainingCardCandidates[0].reflectionPrompt,
    'What changed once you separated the dependency boundary from the route?',
  );
  assert.deepEqual(
    patch.workspaceTrainingState.trainingCardCandidates[0].hintLadder,
    ['Find the smallest boundary first.', 'Then verify only the current file.'],
  );
  assert.deepEqual(
    patch.workspaceTrainingState.trainingCardCandidates[0].commonMistakes,
    ['Mixing service creation into the route.', 'Trying to solve two boundaries at once.'],
  );
  assert.deepEqual(
    patch.workspaceTrainingState.activeTrainingCardRouting.selectedCard.expectedSymbols,
    ['debounceSearch'],
  );
  assert.equal(
    patch.workspaceTrainingState.activeTrainingCardRouting.selectedCard.question,
    'What boundary should this route keep stable first?',
  );
  assert.equal(
    patch.workspaceTrainingState.activeTrainingCardRouting.nextAfterCompletion,
    'Return with the route diff and the test output.',
  );
  assert.equal(
    patch.workspaceTrainingState.activeTrainingCardRouting.selectedCard.nextAfterCompletion,
    'Return with the route diff and the test output.',
  );
  assert.equal(
    patch.workspaceTrainingState.activeTrainingCardRouting.selectedCard.scenarioPack,
    'remote_workspace',
  );
  assert.deepEqual(
    patch.workspaceTrainingState.trainingEventLedger[0].expectedSymbols,
    ['debounceSearch'],
  );
  assert.equal(patch.workspaceTrainingState.reviewArtifact.status, 'resolved');
  assert.equal(
    patch.workspaceTrainingState.scenarioLab.title,
    'Sandbox the dependency boundary',
  );
  assert.equal(
    patch.workspaceTrainingState.theoryDrill.questions[0].prompt,
    'Why does this dependency belong in the route instead of the service layer?',
  );
  assert.equal(patch.workspaceTrainingState.dueReviews[0].concept, 'fastapi Depends');
});

test('mergeSessionMessage carries training handoff truth through session snapshots', () => {
  const bootstrap = createBootstrap();

  const result = mergeSessionMessage(
    bootstrap,
    {
      session_id: 'session-training-state',
      reply: {
        id: 'assistant-training-state',
        role: 'assistant',
        content: 'Keep the route boundary narrow and verifiable.',
      },
      snapshot: {
        messages: [],
        memory: {
          workspace: {
            latest_training_handoff: {
              candidate_id: 'candidate-practice-1',
              continue_in: 'training',
              card_type: 'practice',
              card_title: 'Practice dependency boundary',
              scenario_pack: 'remote_workspace',
              learner_deliverables: [
                'Implement one route with a single dependency boundary.',
              ],
              verification_steps: ['Run the minimum route test.'],
            },
            latest_training_next_hop: {
              candidate_id: 'candidate-practice-2',
              candidate_type: 'practice_candidate',
              continue_in: 'training',
              target_kind: 'training_card',
              target_id: 'card-practice-2',
              status: 'surfaced',
              scenario_pack: 'remote_workspace',
              next_after_completion:
                'Review the blocker, then continue the practice card.',
            },
            latest_training_submode: 'practice',
            selected_card_id: 'card-practice-1',
            selected_card_type: 'practice',
            selected_card_title: 'Practice dependency boundary',
            selected_card_status: 'active',
          },
          active_training_card_routing: {
            selected_card_id: 'card-practice-1',
            why_this_card: 'Highest leverage next card.',
          },
          review_artifact: {
            id: 'review-1',
            title: 'Governed review',
            status: 'active',
            focus_area: 'dependency injection',
          },
        },
      },
    },
    'What should I implement next?',
  );

  assert.equal(result.sessionId, 'session-training-state');
  assert.equal(
    result.patch.workspaceTrainingState.latestTrainingHandoff.cardTitle,
    'Practice dependency boundary',
  );
  assert.equal(
    result.patch.workspaceTrainingState.latestTrainingHandoff.scenarioPack,
    'remote_workspace',
  );
  assert.equal(
    result.patch.workspaceTrainingState.latestTrainingNextHop.candidateType,
    'practice_candidate',
  );
  assert.equal(
    result.patch.workspaceTrainingState.latestTrainingNextHop.scenarioPack,
    'remote_workspace',
  );
  assert.equal(
    result.patch.workspaceTrainingState.latestTrainingNextHop.nextAfterCompletion,
    'Review the blocker, then continue the practice card.',
  );
  assert.equal(
    result.patch.workspaceTrainingState.activeTrainingCardRouting.selectedCardId,
    'card-practice-1',
  );
  assert.equal(result.patch.workspaceTrainingState.reviewArtifact.status, 'active');
});
