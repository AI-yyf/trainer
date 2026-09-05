'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const sendIntelligenceModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'sendIntelligence.js',
);

const { analyzeSendIntent, shouldAttachCurrentFile } = require(sendIntelligenceModulePath);

function createInput(overrides = {}) {
  return {
    draft: 'Help me review this.',
    activeView: 'coach',
    hasResearchProject: false,
    activeFile: '/workspace/src/app.ts',
    selectionRange: '12:1-24:2',
    relatedFilesCount: 2,
    includeCurrentFile: true,
    includeSelection: true,
    includeDiagnostics: true,
    includeRelatedFiles: true,
    contextDetail: 'balanced',
    diagnosticErrors: 1,
    diagnosticWarnings: 0,
    ...overrides,
  };
}

test('analyzeSendIntent classifies local sidebar commands separately', () => {
  const result = analyzeSendIntent(
    createInput({
      draft: '/open review',
    }),
  );

  assert.equal(result.target, 'local_command');
  assert.equal(result.intent, 'local_command');
  assert.equal(result.localCommandId, 'open-coach');
});

test('analyzeSendIntent keeps remote review slash command as trainer intent', () => {
  const result = analyzeSendIntent(
    createInput({
      draft: '/review focus on naming',
    }),
  );

  assert.equal(result.target, 'trainer');
  assert.equal(result.intent, 'review');
  assert.equal(result.draftBody, 'focus on naming');
});

test('analyzeSendIntent recognizes natural-language review requests', () => {
  const result = analyzeSendIntent(
    createInput({
      draft: 'Please review this change and tell me what is off.',
    }),
  );

  assert.equal(result.target, 'trainer');
  assert.equal(result.intent, 'review');
});

test('analyzeSendIntent keeps natural-language next-step prompts in coach', () => {
  const nextStep = analyzeSendIntent(
    createInput({
      draft: 'What should I do next after this slice?',
    }),
  );
  const understand = analyzeSendIntent(
    createInput({
      draft: 'Help me understand this VS Code remote workspace first, then verify one tiny step.',
    }),
  );
  const diagnose = analyzeSendIntent(
    createInput({
      draft: 'Diagnose this VS Code debug loop. Learn first, then continue from one checkpoint.',
    }),
  );

  assert.equal(nextStep.target, 'trainer');
  assert.equal(nextStep.intent, 'coach');
  assert.notEqual(nextStep.intent, 'next_task');
  assert.equal(understand.intent, 'coach');
  assert.notEqual(understand.intent, 'next_task');
  assert.equal(diagnose.intent, 'coach');
  assert.notEqual(diagnose.intent, 'next_task');
});

test('analyzeSendIntent keeps explicit next-task slash and hint as next_task', () => {
  const slash = analyzeSendIntent(
    createInput({
      draft: '/next',
    }),
  );
  const hinted = analyzeSendIntent(
    createInput({
      draft: 'Help me understand this first.',
      intentHint: 'next_task',
    }),
  );

  assert.equal(slash.intent, 'next_task');
  assert.equal(hinted.intent, 'next_task');
});

test('analyzeSendIntent keeps natural-language planning prompts conversational', () => {
  const result = analyzeSendIntent(
    createInput({
      draft: '帮我做个计划，把这个 refactor 分成几步。',
    }),
  );

  assert.equal(result.target, 'trainer');
  assert.equal(result.intent, 'coach');
});

test('analyzeSendIntent keeps Plan-view discussion out of the formal mutation route', () => {
  const result = analyzeSendIntent(
    createInput({
      activeView: 'plan',
      draft: '请解释当前阶段，并指出最小验证方式。',
    }),
  );

  assert.equal(result.target, 'trainer');
  assert.equal(result.intent, 'coach');
});

test('analyzeSendIntent warns when review has no active file', () => {
  const result = analyzeSendIntent(
    createInput({
      draft: '/review',
      activeFile: undefined,
    }),
  );

  assert.ok(result.warnings.some((warning) => warning.id === 'review-needs-file'));
});

test('analyzeSendIntent warns when review file context is disabled', () => {
  const result = analyzeSendIntent(
    createInput({
      draft: '/review',
      includeCurrentFile: false,
    }),
  );

  assert.ok(result.warnings.some((warning) => warning.id === 'review-file-disabled'));
});

test('analyzeSendIntent warns when selection exists but is not attached', () => {
  const result = analyzeSendIntent(
    createInput({
      includeSelection: false,
    }),
  );

  assert.ok(result.warnings.some((warning) => warning.id === 'selection-available-but-disabled'));
});

test('analyzeSendIntent warns when related files exist but are not attached', () => {
  const result = analyzeSendIntent(
    createInput({
      includeRelatedFiles: false,
    }),
  );

  assert.ok(result.warnings.some((warning) => warning.id === 'related-available-but-disabled'));
});

test('analyzeSendIntent keeps coach-first routing even when legacy research state is present', () => {
  const result = analyzeSendIntent(
    createInput({
      draft: 'Investigate the API design tradeoffs.',
      activeView: 'coach',
      hasResearchProject: true,
    }),
  );

  assert.equal(result.target, 'trainer');
  assert.equal(result.intent, 'coach');
});

test('analyzeSendIntent keeps resources and training views in coach mode by default', () => {
  const resourceTurn = analyzeSendIntent(
    createInput({
      draft: 'Which resource should guide this refactor first?',
      activeView: 'resources',
    }),
  );
  const trainingTurn = analyzeSendIntent(
    createInput({
      draft: 'I finished the slice and need the next move.',
      activeView: 'training',
    }),
  );

  assert.equal(resourceTurn.intent, 'coach');
  assert.equal(trainingTurn.intent, 'coach');
});

test('shouldAttachCurrentFile keeps ordinary coaching lean while preserving explicit code work', () => {
  assert.equal(shouldAttachCurrentFile('Explain the difference between a closure and a callback.', 'coach'), false);
  assert.equal(shouldAttachCurrentFile('Explain the current file.', 'coach'), true);
  assert.equal(shouldAttachCurrentFile('\u8bf7\u89e3\u91ca\u8fd9\u6bb5\u4ee3\u7801\u7684\u4f5c\u7528\u3002', 'coach'), true);
  assert.equal(shouldAttachCurrentFile('Find the next practice task.', 'task'), true);
  assert.equal(shouldAttachCurrentFile('Review this change.', 'review'), true);
});
