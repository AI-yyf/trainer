'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const resourcesPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);
const trainingPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'TrainingWorkbenchView.tsx',
);

function cardOnlyRender(source) {
  const start = source.indexOf('{cardOnly ? (');
  const end = source.indexOf('{!cardOnly ? (', start);

  assert.ok(start >= 0, 'expected the card-only render branch');
  assert.ok(end > start, 'expected the card-only render branch to close before secondary content');
  return source.slice(start, end);
}

test('resources stay a searchable knowledge library with a controlled sandbox disclosure', () => {
  // Product-level template contract replaces the previous layout grammar.
  const { read } = require('./templateAssertions');
  const source = read('components/resources/ResourcesWorkbenchView.tsx');
  for (const marker of ['<Library', '<ResourceReader', 'type="search"', 'onSelect={selectResource}', 'onToggleSelection={toggleResourceSelection}', 'onRestore', 'onStartTrainingFromResource', 'openResourceInVsCode']) assert.ok(source.includes(marker), marker);
  assert.ok(!source.includes('didAutoSelectResource'));
  assert.ok(source.includes('onAskCoach([selectedResource.id])'));
});

test('training defaults to a five-stage single-card loop with one visible, state-driven next action', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').practice();
});

test('each workbench view keeps its own primary object instead of embedding the coach transcript', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  assert.match(appSource, /view-stack--single/);
  assert.doesNotMatch(appSource, /showEmbeddedCoachTranscript/);
  assert.doesNotMatch(appSource, /coach-pane coach-pane--embedded coach-pane--secondary/);
  assert.doesNotMatch(appSource, /view-stack__divider/);
});
