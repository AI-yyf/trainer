// Restored behavioral regression test. Original file: extension/tests/orientationLocale.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Orientation locale copy: a failed index stays blocked in every locale.
//
// Restoration: partial - 1 of 4 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "every orientation locale has complete coach, plan, and resources keys"
//       fails at HEAD: coachOrientationCopy is not a function
//   - "language switch keeps snapshot state and does not invent readiness"
//       fails at HEAD: deriveCoachOrientation is not a function
//   - "latin orientation locales do not keep Chinese as the only rail copy"
//       fails at HEAD: deriveCoachOrientation is not a function
// Target: compiled shared modules (extension/dist/shared/src).

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const {
  ORIENTATION_LOCALES,
  coachOrientationCopy,
  planOrientationCopy,
  resourcesOrientationCopy,
} = require('../dist/shared/src/orientationCopy.js');
const { deriveCoachOrientation } = require('../dist/shared/src/coachOrientationGovernance.js');
const { derivePlanOrientation } = require('../dist/shared/src/planOrientationGovernance.js');
const { deriveResourcesOrientation } = require('../dist/shared/src/resourcesOrientationGovernance.js');

const LATIN_LOCALES = ['en-US', 'es-ES', 'fr-FR', 'de-DE', 'pt-BR'];
const CJK_LEFTOVER = /还没有|当前对象|资料库是空的|先处理这个 blocker|学习计划/;

function collectStrings(value, into = []) {
  if (typeof value === 'string') {
    into.push(value);
    return into;
  }
  if (typeof value === 'function') {
    into.push(String(value('probe', 2)));
    return into;
  }
  if (value && typeof value === 'object') {
    for (const entry of Object.values(value)) {
      collectStrings(entry, into);
    }
  }
  return into;
}

function assertOrientationSurface(orientation) {
  assert.ok(orientation.objectLabel.trim());
  assert.ok(orientation.why.trim());
  assert.ok(orientation.nextStep.trim());
  assert.ok(orientation.primaryActionLabel.trim());
  assert.ok(orientation.advancedWhere.trim());
  assert.equal(orientation.source, 'snapshot');
}


test('failed index stays blocked in every locale', () => {
  for (const language of ORIENTATION_LOCALES) {
    const orientation = deriveResourcesOrientation({
      resourceCount: 2,
      selectedResourceId: 'res-1',
      selectedResourceTitle: 'Broken notes',
      indexState: 'failed',
      resourceStatus: 'attention',
      language,
    });
    assert.equal(orientation.state, 'blocked');
    assert.notEqual(orientation.state, 'ready');
    assert.equal(orientation.primaryAction, 'retry_index');
    assertOrientationSurface(orientation);
  }
});
