'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const sharedProtocolModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'protocol.js',
);

test('trainer message parts normalize into the typed registry contract', () => {
  const {
    createEmptyTrainerStreamingState,
    deriveTrainerStreamingOperationMessage,
    deriveTrainerToolActivity,
    findCoachVisibleStatusPart,
    normalizeTrainerStreamingState,
    normalizeNextStepHint,
    trainerMessagePartTypes,
    normalizeTrainerMessageParts,
    upsertTrainerToolActivity,
  } = require(sharedProtocolModulePath);

  assert.deepEqual(trainerMessagePartTypes, [
    'markdown',
    'code',
    'diff',
    'math',
    'mermaid',
    'table',
    'citation',
    'tool_call',
    'tool_result',
    'reasoning',
    'coach_visible_status',
    'training_card',
    'plan_update',
    'test_result',
    'file_preview',
    'checklist',
    'alert',
  ]);

  const parts = normalizeTrainerMessageParts([
    { type: 'toolCall', id: 'call-1', name: 'search', state: 'running', parameters: { query: 'FSRS' } },
    { type: 'toolResults', callId: 'call-1', name: 'search', output: { ok: true, rows: 3 } },
    { type: 'tool_result', callId: 'call-2', name: 'inspect_plan', error: 'timed out', step: 2 },
    {
      type: 'reasoningSummary',
      content: 'Keep the next slice small.',
      redacted: true,
      detail: 'Stay inside one visible branch.',
      source_chain: ['scenario: review', 'stage: Coach flow'],
      hint_ladder: ['Keep it small', 'Use the active evidence'],
      verification_steps: ['Run the focused check', 'Confirm the branch still fits'],
    },
    {
      type: 'coachVisibleStatus',
      state: 'degraded',
      summary: 'Coach fell back safely after a deeper check degraded.',
      detail: 'Used recall_memory and inspect_plan before narrowing the answer.',
      next_step: 'Land one verifiable patch.',
      source: 'agent_loop',
      tool_names: ['recall_memory', 'inspect_plan'],
      step_count: 2,
      decision: 'Use the existing evidence path and keep the thread tight.',
      blocker: 'The provider returned a partial answer.',
      teaching_note: 'Show the recovery path without hiding the reason.',
      confidence: 'medium',
      evidence: ['recall_memory', 'inspect_plan'],
    },
    {
      type: 'trainingCard',
      cardId: 'card-1',
      title: 'Review rhythm',
      status: 'active',
      whyNow: 'Due soon',
      scenarioPack: 'debug_loop',
    },
    { type: 'planUpdate', planId: 'plan-1', change: { field: 'currentStep' } },
    { type: 'testResult', command: 'npm test', status: 'pass', outputRef: 'logs/test.txt', detail: '42 tests passed' },
    { type: 'filePreview', resourceId: 'file-1', path: '/tmp/notes.csv', previewKind: 'table', canNativeOpen: true },
    { type: 'checkList', checklist: ['Lock behavior', { text: 'Verify UI', done: true }] },
    { type: 'alert', severity: 'warn', title: 'Heads up', detail: 'Follow-up required' },
  ]);

  assert.ok(parts);
  assert.deepEqual(parts.map((part) => part.type), [
    'tool_call',
    'tool_result',
    'tool_result',
    'reasoning',
    'coach_visible_status',
    'training_card',
    'plan_update',
    'test_result',
    'file_preview',
    'checklist',
    'alert',
  ]);
  assert.equal(parts[0].status, 'called');
  assert.deepEqual(parts[0].args, { query: 'FSRS' });
  assert.equal(parts[1].name, 'search');
  assert.deepEqual(parts[1].result, { ok: true, rows: 3 });
  assert.equal(parts[2].name, 'inspect_plan');
  assert.equal(parts[2].error, 'timed out');
  assert.equal(parts[3].summary, 'Keep the next slice small.');
  assert.equal(parts[3].detail, 'Stay inside one visible branch.');
  assert.deepEqual(parts[3].sourceChain, ['scenario: review', 'stage: Coach flow']);
  assert.deepEqual(parts[3].hintLadder, ['Keep it small', 'Use the active evidence']);
  assert.deepEqual(parts[3].verificationSteps, ['Run the focused check', 'Confirm the branch still fits']);
  assert.equal(parts[4].status, 'degraded');
  assert.equal(parts[4].nextStep, 'Land one verifiable patch.');
  assert.deepEqual(parts[4].toolNames, ['recall_memory', 'inspect_plan']);
  assert.equal(parts[4].stepCount, 2);
  assert.equal(parts[4].decision, 'Use the existing evidence path and keep the thread tight.');
  assert.equal(parts[4].blocker, 'The provider returned a partial answer.');
  assert.equal(parts[4].teachingNote, 'Show the recovery path without hiding the reason.');
  assert.equal(parts[4].confidence, 'medium');
  assert.deepEqual(parts[4].evidence, ['recall_memory', 'inspect_plan']);
  assert.equal(parts[5].title, 'Review rhythm');
  assert.equal(parts[5].scenarioPack, 'debug_loop');
  assert.equal(parts[6].changes.length, 1);
  assert.equal(parts[7].outputRef, 'logs/test.txt');
  assert.equal(parts[7].detail, '42 tests passed');
  assert.equal(parts[8].previewKind, 'table');
  assert.equal(parts[9].items.length, 2);
  assert.equal(parts[9].items[0].done, false);
  assert.equal(parts[10].level, 'warn');

  assert.deepEqual(deriveTrainerToolActivity(parts), [
    {
      id: 'call-1',
      name: 'search',
      status: 'succeeded',
      args: { query: 'FSRS' },
      result: { ok: true, rows: 3 },
    },
    {
      id: 'call-2',
      name: 'inspect_plan',
      status: 'failed',
      step: 2,
    },
  ]);
  let streamingActivities = [];
  streamingActivities = upsertTrainerToolActivity(streamingActivities, {
    id: 'call-1',
    name: 'search',
    status: 'running',
    args: { query: 'FSRS' },
  });
  streamingActivities = upsertTrainerToolActivity(streamingActivities, {
    id: 'call-1',
    name: 'search',
    status: 'succeeded',
    result: { ok: true, rows: 3 },
  });
  streamingActivities = upsertTrainerToolActivity(streamingActivities, {
    id: 'call-2',
    name: 'inspect_plan',
    status: 'failed',
    step: 2,
  });
  assert.deepEqual(streamingActivities, [
    {
      id: 'call-1',
      name: 'search',
      status: 'succeeded',
      args: { query: 'FSRS' },
      result: { ok: true, rows: 3 },
    },
    {
      id: 'call-2',
      name: 'inspect_plan',
      status: 'failed',
      step: 2,
    },
  ]);
  assert.deepEqual(
    normalizeTrainerStreamingState({
      isStreaming: true,
      streamedContent: 'Checking context',
      streamMessageId: 'msg-stream-1',
      agentActivity: streamingActivities,
      agentStep: 2,
      toolCount: 2,
    }),
    {
      ...createEmptyTrainerStreamingState(),
      isStreaming: true,
      streamedContent: 'Checking context',
      streamMessageId: 'msg-stream-1',
      agentActivity: streamingActivities,
      agentStep: 2,
      toolCount: 2,
    },
  );
  assert.equal(
    deriveTrainerStreamingOperationMessage("en-US", {
      isStreaming: true,
      streamedContent: "Checking context",
      streamMessageId: "msg-stream-1",
    }),
    undefined,
  );
  assert.deepEqual(
    deriveTrainerStreamingOperationMessage("en-US", {
      isStreaming: false,
      streamedContent: "Here is the grounded answer.",
      streamMessageId: "msg-stream-2",
      completionSummary: "Checked the workspace context first.",
      completionNextStep: "Apply the smallest verified patch.",
    }),
    {
      tone: "success",
      message: "Checked the workspace context first. Next: Apply the smallest verified patch.",
    },
  );
  assert.deepEqual(
    deriveTrainerStreamingOperationMessage("en-US", {
      isStreaming: false,
      streamedContent: "Done.",
      streamMessageId: "msg-stream-3",
      agentActivity: streamingActivities,
      toolCount: 2,
      agentic: true,
    }),
    {
      tone: "success",
      message: "Coach loop completed after 2 tool steps.",
    },
  );
  assert.deepEqual(
    deriveTrainerStreamingOperationMessage("en-US", {
      isStreaming: false,
      streamedContent: "Answer ready.",
      streamMessageId: "msg-stream-4",
    }),
    {
      tone: "success",
      message: "Coach reply completed.",
    },
  );
  assert.deepEqual(
    deriveTrainerStreamingOperationMessage(
      "en-US",
      {
        isStreaming: false,
        streamedContent: "",
        streamMessageId: "msg-stream-5",
        streamError: "401 invalid_api_key",
      },
      { errorCategory: "invalid_key_or_permission" },
    ),
    {
      tone: "error",
      message:
        "The current API key is invalid or does not have access to this model. Open Settings and update the provider connection.",
    },
  );
  const rawStreamFailure = deriveTrainerStreamingOperationMessage("en-US", {
    isStreaming: false,
    streamedContent: "",
    streamMessageId: "msg-stream-raw-error",
    streamError: 'HTTP 502: <html>Traceback {"token":"hidden"}</html>',
  });
  assert.deepEqual(rawStreamFailure, {
    tone: "error",
    message: "Trainer could not finish this reply. Try again in a moment.",
  });
  assert.doesNotMatch(rawStreamFailure.message, /http|html|traceback|token/i);
  assert.deepEqual(
    deriveTrainerStreamingOperationMessage("en-US", {
      isStreaming: false,
      streamedContent: "Repair the provider in Settings.",
      streamMessageId: "msg-stream-honest-failure",
      reliabilityPhase: "acked",
      reliabilityOutcome: "failure",
    }),
    {
      tone: "error",
      message: "Coach reply completed.",
    },
  );
  assert.deepEqual(
    deriveTrainerStreamingOperationMessage("en-US", {
      isStreaming: false,
      streamedContent: "",
      streamMessageId: "msg-stream-truncated",
      completionSummary: "Model stopped mid thought.",
      completionStopReason: "truncated",
      reliabilityPhase: "acked",
      reliabilityOutcome: "success",
    }),
    {
      tone: "error",
      message: "Coach loop closed: Model stopped mid thought. (truncated)",
    },
  );
  assert.deepEqual(findCoachVisibleStatusPart(parts), parts[4]);

  const hint = normalizeNextStepHint({
    title: 'Patch the smallest async iterator call site.',
    summary: 'Keep the current slice narrow and rerun the focused check.',
    recommended_action: 'task',
    focus_area: 'async iterator boundary',
    resume_thread: 'Resume the live thread around the async iterator boundary. Next: Patch the smallest async iterator call site.',
    continue_in: 'plan',
    source: 'agent_loop',
    verification: ['Run the focused test'],
  });
  assert.deepEqual(hint, {
    title: 'Patch the smallest async iterator call site.',
    summary: 'Keep the current slice narrow and rerun the focused check.',
    recommendedAction: 'task',
    focusArea: 'async iterator boundary',
    prompt: undefined,
    resumeThread: 'Resume the live thread around the async iterator boundary. Next: Patch the smallest async iterator call site.',
    source: 'agent_loop',
    continueIn: 'plan',
    verification: ['Run the focused test'],
  });
});
