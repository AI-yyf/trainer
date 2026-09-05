'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const catalog = require(path.resolve(
  __dirname,
  '..',
  '..',
  'server',
  'app',
  'training',
  'guided_training_scenario_packs.json',
));

test('guided training scenario pack catalog covers the five teaching domains', () => {
  const packs = Array.isArray(catalog.packs) ? catalog.packs : [];
  assert.equal(packs.length, 5);
  assert.deepEqual(
    packs.map((pack) => pack.previewScenario),
    [
      'training-remote',
      'training-debug',
      'training-function',
      'training-resource',
      'training-dependency',
    ],
  );
});

test('guided training scenario pack catalog keeps key English teaching cues intact', () => {
  const byId = new Map(catalog.packs.map((pack) => [pack.id, pack]));

  assert.equal(
    byId.get('remote_workspace')?.practice?.title?.['en-US'],
    'Practice: Verify the remote workspace boundary',
  );
  assert.equal(
    byId.get('remote_workspace')?.practiceNextStep?.['en-US'],
    'Return with the remote boundary proof',
  );
  assert.ok(
    byId.get('remote_workspace')?.practice?.filesToTouch?.includes('shared/src/remoteWorkspace.ts'),
  );
  assert.ok(
    byId.get('debug_loop')?.practice?.apiHints?.includes('launch.json configurations'),
  );
  assert.equal(
    byId.get('debug_loop')?.practiceNextStep?.['en-US'],
    'Return with the debug evidence',
  );
  assert.ok(
    byId.get('function_guidance')?.practice?.apiHints?.includes('Hover / Peek Definition'),
  );
  assert.equal(
    byId.get('function_guidance')?.practiceNextStep?.['en-US'],
    'Return with the function contract',
  );
  assert.equal(
    byId.get('resource_knowledge')?.practice?.title?.['en-US'],
    'Practice: Turn a resource into trusted knowledge',
  );
  assert.equal(
    byId.get('dependency_mastery')?.flash?.title?.['en-US'],
    'Flash: Dependency/API safe usage',
  );
  assert.ok(
    byId.get('resource_knowledge')?.sourceChain?.['en-US']?.includes('Resource trust state'),
  );
  assert.ok(
    byId.get('dependency_mastery')?.sourceChain?.['en-US']?.includes('Verification target'),
  );
});

test('guided training scenario pack catalog keeps localized Chinese copy populated', () => {
  for (const pack of catalog.packs) {
    assert.ok(pack.currentFocus?.['zh-CN']);
    assert.ok(pack.practice?.title?.['zh-CN']);
    assert.ok(pack.flash?.title?.['zh-CN']);
  }
});
