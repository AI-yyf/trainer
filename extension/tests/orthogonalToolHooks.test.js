'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');
const { load } = require('./templateAssertions');

const workspaceSnapshotModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'workspaceFileSnapshot.js',
);

const sessionCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'sessionCommands.js',
);

const { requestsLearningPlanChange } = require('../dist/shared/src/learnerInstructions');
const { parseAcceptanceFeedbackFromToolResult } = require('../dist/shared/src/acceptanceFeedback');
const { currentTrainerStage, trainerStageKindForTool } = load('lib/trainerStage.ts');
const { resolveToolActivityLabel } = load('lib/i18n/segments/agentActivityStripCopy.ts');

test('workspaceFileSnapshot captures missing snapshot paths from project_read and library_write', () => {
  const vscodeMock = {
    workspace: { workspaceFolders: [] },
    env: {},
  };
  const {
    consumeRequestedWorkspaceFiles,
    noteRequestedWorkspaceFileToolResult,
  } = loadWithVscodeMock(workspaceSnapshotModulePath, vscodeMock);

  const owner = {};
  noteRequestedWorkspaceFileToolResult(owner, 'project_read', {
    ok: false,
    action: 'read',
    error: 'snapshot_content_unavailable',
    path: './src/engine/raft.py',
  });
  noteRequestedWorkspaceFileToolResult(owner, 'library_write', {
    ok: false,
    action: 'import_workspace',
    error: 'snapshot_content_unavailable',
    paths: ['docs/spec.md', 'docs/notes.md'],
  });
  noteRequestedWorkspaceFileToolResult(owner, 'library_read', {
    ok: false,
    action: 'read_file',
    error: 'snapshot_content_unavailable',
    path: 'ignored.md',
  });

  assert.deepEqual(consumeRequestedWorkspaceFiles(owner), [
    'src/engine/raft.py',
    'docs/spec.md',
    'docs/notes.md',
  ]);
});

test('sessionCommands tracks library_write(organize) confirmation and mutating activity hooks', () => {
  const vscodeMock = {
    commands: { async executeCommand() {} },
  };
  const {
    isLibraryMutatingActivity,
    noteResourceOrganizationToolResult,
  } = loadWithVscodeMock(sessionCommandsModulePath, vscodeMock);

  const context = {};
  const proposed = noteResourceOrganizationToolResult(context, 'library_write', {
    ok: true,
    action: 'organize',
    requires_confirmation: true,
    operations: [{ action: 'move', path: 'a.md', new_path: 'notes/a.md' }],
  });
  assert.deepEqual(proposed, { pending: true, operationCount: 1 });

  // Unrelated library_write actions must not clear or trigger organize confirmation state.
  const unrelatedWrite = noteResourceOrganizationToolResult(context, 'library_write', {
    ok: true,
    action: 'write',
    committed: true,
    path: 'notes/summary.md',
  });
  assert.equal(unrelatedWrite, null);

  const committed = noteResourceOrganizationToolResult(context, 'library_write', {
    ok: true,
    action: 'organize',
    committed: true,
  });
  assert.deepEqual(committed, { pending: false });

  assert.equal(isLibraryMutatingActivity('library_write', { action: 'save_lecture_note' }), true);
  assert.equal(isLibraryMutatingActivity('library_exec', { command: 'python3 parse.py' }), true);
  assert.equal(isLibraryMutatingActivity('web_fetch', { action: 'import_url' }), true);
  assert.equal(isLibraryMutatingActivity('web_fetch', { action: 'search' }), false);
  assert.equal(isLibraryMutatingActivity('learning_action', { action: 'generate_image' }), true);
  assert.equal(isLibraryMutatingActivity('learning_action', { action: 'save_formal_plan' }), false);
  assert.equal(isLibraryMutatingActivity('project_read', { action: 'read' }), false);
  assert.equal(isLibraryMutatingActivity('library_read', { action: 'search' }), false);
});

test('webview stage and activity labels cover all 8 orthogonal primitives and sub-actions', () => {
  assert.equal(trainerStageKindForTool('project_read', { action: 'read' }), 'retrieve');
  assert.equal(trainerStageKindForTool('project_verify', { action: 'verify_practice' }), 'retrieve');
  assert.equal(trainerStageKindForTool('library_read', { action: 'grep' }), 'retrieve');
  assert.equal(trainerStageKindForTool('library_write', { action: 'write' }), 'organize');
  assert.equal(trainerStageKindForTool('library_write', { action: 'import_url' }), 'download');
  assert.equal(trainerStageKindForTool('library_exec', { command: 'wc -l notes.md' }), 'organize');
  assert.equal(trainerStageKindForTool('web_fetch', { action: 'papers' }), 'retrieve');
  assert.equal(trainerStageKindForTool('web_fetch', { action: 'import_url' }), 'download');
  assert.equal(trainerStageKindForTool('learning_inspect', { action: 'truth' }), 'retrieve');
  assert.equal(trainerStageKindForTool('learning_action', { action: 'invoke_skill' }), 'reason');
  assert.equal(trainerStageKindForTool('learning_action', { action: 'record_note' }), 'organize');
  assert.equal(trainerStageKindForTool('learning_action', { action: 'save_formal_plan' }), 'finalize');

  const liveStage = currentTrainerStage(
    [{ name: 'library_write', status: 'running', args: { action: 'import_workspace' } }],
    'zh-CN',
  );
  assert.equal(liveStage.kind, 'download');
  assert.equal(liveStage.label, '正在下载资料');

  assert.equal(
    resolveToolActivityLabel('library_write', 'zh-CN', { action: 'save_lecture_note' }),
    '保存讲稿到资料库',
  );
  assert.equal(
    resolveToolActivityLabel('learning_action', 'en-US', undefined, { action: 'save_formal_plan' }),
    'Save formal plan',
  );
  assert.equal(
    resolveToolActivityLabel('project_verify', 'zh-CN', { action: 'verify_practice' }),
    '验证实战代码',
  );
  assert.equal(
    requestsLearningPlanChange('请立即调用 learning_action 保存正式学习计划。'),
    true,
  );
  const feedback = parseAcceptanceFeedbackFromToolResult(
    {
      ok: true,
      tool: 'project_verify',
      action: 'verify_practice',
      criteria: [
        { text: 'handles empty input', status: 'matched' },
        { text: 'raises ValueError on negative depth', status: 'missing' },
      ],
      next_step: 'Add the negative-depth guard.',
    },
    'project_verify',
  );
  assert.deepEqual(feedback, {
    matched: 1,
    total: 2,
    matchedItems: ['handles empty input'],
    missingItems: ['raises ValueError on negative depth'],
    nextStep: 'Add the negative-depth guard.',
  });
});
