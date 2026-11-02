'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const {
  normalizeTrainingFilePath,
  trainingFileMatchesEditorPath,
} = require(path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'trainingFilePaths.js',
));

test('normalizes markdown-wrapped and relative card paths', () => {
  assert.equal(normalizeTrainingFilePath('`queue_lock.py`'), 'queue_lock.py');
  assert.equal(normalizeTrainingFilePath(' `./src/queue_lock.py` '), 'src/queue_lock.py');
  assert.equal(normalizeTrainingFilePath('src\\queue_lock.py'), 'src/queue_lock.py');
  assert.equal(normalizeTrainingFilePath('"src/queue_lock.py"'), 'src/queue_lock.py');
});

test('matches the active nested editor for a leaf-only card path', () => {
  assert.equal(
    trainingFileMatchesEditorPath({
      filePath: '`queue_lock.py`',
      editorPath: '/tmp/workspace/src/queue_lock.py',
      workspaceFolder: '/tmp/workspace',
    }),
    true,
  );
});

test('matches an exact workspace-relative path', () => {
  assert.equal(
    trainingFileMatchesEditorPath({
      filePath: 'src/queue_lock.py',
      editorPath: '/tmp/workspace/src/queue_lock.py',
      workspaceFolder: '/tmp/workspace',
    }),
    true,
  );
});

test('rejects a different leaf file instead of guessing', () => {
  assert.equal(
    trainingFileMatchesEditorPath({
      filePath: 'conversation_router.py',
      editorPath: '/tmp/workspace/src/queue_lock.py',
      workspaceFolder: '/tmp/workspace',
    }),
    false,
  );
});

test('rejects a partial directory mismatch', () => {
  assert.equal(
    trainingFileMatchesEditorPath({
      filePath: 'src/queue_lock.py',
      editorPath: '/tmp/workspace/other/queue_lock.py',
      workspaceFolder: '/tmp/workspace',
    }),
    false,
  );
});

test('rejects the same leaf outside the managed workspace', () => {
  assert.equal(
    trainingFileMatchesEditorPath({
      filePath: 'queue_lock.py',
      editorPath: '/work/outside/queue_lock.py',
      workspaceFolder: '/work/project',
    }),
    false,
  );
});

test('rejects a relative card path outside the managed workspace', () => {
  assert.equal(
    trainingFileMatchesEditorPath({
      filePath: 'src/queue_lock.py',
      editorPath: '/work/outside/src/queue_lock.py',
      workspaceFolder: '/work/project',
    }),
    false,
  );
});

test('accepts an absolute target inside the managed workspace', () => {
  assert.equal(
    trainingFileMatchesEditorPath({
      filePath: '/work/project/src/queue_lock.py',
      editorPath: '/work/project/src/queue_lock.py',
      workspaceFolder: '/work/project',
    }),
    true,
  );
});
