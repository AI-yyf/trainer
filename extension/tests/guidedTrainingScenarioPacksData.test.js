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

test('guided training scenario pack catalog covers the seven teaching domains', () => {
  const packs = Array.isArray(catalog.packs) ? catalog.packs : [];
  assert.equal(packs.length, 7);
  assert.deepEqual(
    packs.map((pack) => pack.previewScenario),
    [
      'training-remote',
      'training-debug',
      'training-function',
      'training-resource',
      'training-dependency',
      'training-close-reading',
      'training-theory-concept',
    ],
  );
});

test('literature scenario packs anchor every deliverable to the course text', () => {
  const byId = new Map(catalog.packs.map((pack) => [pack.id, pack]));
  const closeReading = byId.get('literature_close_reading');
  const theory = byId.get('literature_theory_concept');

  // P2 #16: literature packs carry ¶-anchor discipline, no code files, and the
  // same card shape as the engineering packs (zh-CN + en-US inline, eight
  // languages completed by the webview fallback copy).
  for (const pack of [closeReading, theory]) {
    assert.ok(pack, 'literature pack missing');
    assert.ok(pack.currentFocus?.['en-US']);
    assert.ok(pack.practice?.title?.['zh-CN']);
    assert.ok(pack.flash?.title?.['en-US']);
    assert.ok(pack.practice?.deliverable?.['en-US']);
    assert.deepEqual(pack.practice?.filesToTouch, []);
    assert.ok(pack.practice?.learnerDeliverables?.['en-US']);
    assert.ok(pack.practice?.validationMethod?.['zh-CN']);
    assert.ok(pack.flash?.question?.['en-US']);
    assert.ok(pack.flash?.feedback?.['zh-CN']?.correct);
    assert.ok(pack.flash?.feedback?.['en-US']?.incorrect);
  }

  assert.match(closeReading?.sourceChain?.['en-US']?.join(' ') ?? '', /¶ paragraph anchors/);
  assert.match(theory?.sourceChain?.['zh-CN']?.join(' ') ?? '', /两处 ¶ 锚点证据/);
  assert.equal(closeReading?.practiceNextStep?.['en-US'], 'Return with the three annotations');
  assert.equal(theory?.practiceNextStep?.['en-US'], 'Return with the definition and two anchors');
  assert.equal(closeReading?.practice?.cardId, 'card-training-close-reading-practice');
  assert.equal(theory?.flash?.knowledgeType?.['en-US'], 'literature_theory_concept');
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
