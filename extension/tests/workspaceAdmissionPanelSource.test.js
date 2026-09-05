'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const panelPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'firstlook',
  'WorkspaceAdmissionPanel.tsx',
);

test('managed projects offer delete and do not offer browse or ignore', () => {
  const source = fs.readFileSync(panelPath, 'utf8');
  const start = source.indexOf('    case "managed":');
  const end = source.indexOf('    case "browse":', start);

  assert.ok(start >= 0 && end > start, 'expected the managed admission action branch');
  const managedBranch = source.slice(start, end);
  assert.match(source, /asAction\("workspaceAdmissionDelete"/);
  assert.match(managedBranch, /remove \? \[remove\]/);
  assert.doesNotMatch(managedBranch, /browse|ignore/);
});
