'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const sourcePath = path.resolve(__dirname, '..', 'src', 'core', 'workspaceFileSnapshot.ts');

test('managed admission does not hardcode adopt for remote browse-only discovery', () => {
  const source = fs.readFileSync(
    path.resolve(__dirname, '..', 'src', 'commands', 'workspaceAdmissionCommands.ts'),
    'utf8',
  );
  assert.match(source, /function discoveryDecisionFromClassification/);
  assert.match(source, /decision: decisionKind/);
  assert.match(source, /kind === 'browse'/);
  assert.doesNotMatch(source, /decision:\s*'adopt'/);
});

test('remote workspace snapshots list and attach more files than local ones', () => {
  const source = fs.readFileSync(sourcePath, 'utf8');
  assert.match(source, /LIST_LIMIT_REMOTE = 200/);
  assert.match(source, /CONTENT_FILE_LIMIT_REMOTE = 48/);
  assert.match(source, /vscode\.env\?\.remoteName/);
  assert.match(source, /PRIORITY_BASENAMES/);
  assert.match(source, /rememberRequestedWorkspaceFiles/);
  assert.match(source, /consumeRequestedWorkspaceFiles/);
  assert.match(source, /snapshot_content_unavailable/);
});
