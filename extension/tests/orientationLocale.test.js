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

test('every orientation locale has complete coach, plan, and resources keys', () => {
  assert.deepEqual([...ORIENTATION_LOCALES], [
    'zh-CN',
    'en-US',
    'es-ES',
    'fr-FR',
    'de-DE',
    'ja-JP',
    'ko-KR',
    'pt-BR',
  ]);
  const englishCoach = collectStrings(coachOrientationCopy('en-US'));
  const englishPlan = collectStrings(planOrientationCopy('en-US'));
  const englishResources = collectStrings(resourcesOrientationCopy('en-US'));
  for (const language of ORIENTATION_LOCALES) {
    const coach = collectStrings(coachOrientationCopy(language));
    const plan = collectStrings(planOrientationCopy(language));
    const resources = collectStrings(resourcesOrientationCopy(language));
    assert.equal(coach.length, englishCoach.length, `${language} coach key count`);
    assert.equal(plan.length, englishPlan.length, `${language} plan key count`);
    assert.equal(resources.length, englishResources.length, `${language} resources key count`);
    for (const text of [...coach, ...plan, ...resources]) {
      assert.ok(String(text).trim(), `${language} has an empty orientation string`);
    }
    if (language !== 'en-US') {
      assert.notDeepEqual(coach, englishCoach, `${language} coach copy must not be English-only`);
      assert.notDeepEqual(plan, englishPlan, `${language} plan copy must not be English-only`);
      assert.notDeepEqual(resources, englishResources, `${language} resources copy must not be English-only`);
    }
    if (language !== 'zh-CN') {
      for (const text of [...coach, ...plan, ...resources]) {
        assert.doesNotMatch(String(text), CJK_LEFTOVER, `${language} leaked zh-CN copy: ${text}`);
      }
    }
  }
});

test('language switch keeps snapshot state and does not invent readiness', () => {
  const coachInput = {
    sidecarStatus: 'ready',
    hasProviderModel: true,
    conversationCount: 2,
    planCurrentStep: 'Ship the parser guard',
  };
  const planInput = {
    hasFormalPlan: false,
    currentStep: 'Inferred theater step',
  };
  const resourcesInput = {
    resourceCount: 0,
    selectedResourceTitle: 'Theater leftover.pdf',
    indexState: 'indexed',
  };
  const coachStates = [];
  const planStates = [];
  const resourceStates = [];
  for (const language of ORIENTATION_LOCALES) {
    const coach = deriveCoachOrientation({ ...coachInput, language });
    const plan = derivePlanOrientation({ ...planInput, language });
    const resources = deriveResourcesOrientation({ ...resourcesInput, language });
    assertOrientationSurface(coach);
    assertOrientationSurface(plan);
    assertOrientationSurface(resources);
    coachStates.push(`${coach.objectKind}:${coach.state}:${coach.primaryAction}`);
    planStates.push(`${plan.objectKind}:${plan.state}:${plan.primaryAction}`);
    resourceStates.push(`${resources.objectKind}:${resources.state}:${resources.primaryAction}`);
    assert.equal(plan.state, 'needs_setup');
    assert.notEqual(plan.state, 'ready');
    assert.equal(resources.state, 'needs_setup');
    assert.notEqual(resources.state, 'ready');
    assert.notEqual(plan.objectLabel, 'Inferred theater step');
    assert.notEqual(resources.objectLabel, 'Theater leftover.pdf');
  }
  assert.ok(coachStates.every((value) => value === coachStates[0]));
  assert.ok(planStates.every((value) => value === planStates[0]));
  assert.ok(resourceStates.every((value) => value === resourceStates[0]));
});

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

test('latin orientation locales do not keep Chinese as the only rail copy', () => {
  const han = /[\u4e00-\u9fff]/;
  for (const language of LATIN_LOCALES) {
    const coach = deriveCoachOrientation({
      sidecarStatus: 'error',
      hasProviderModel: true,
      language,
    });
    const plan = derivePlanOrientation({ hasFormalPlan: false, language });
    const resources = deriveResourcesOrientation({ resourceCount: 0, language });
    for (const text of [coach.why, coach.nextStep, plan.why, plan.nextStep, resources.why, resources.nextStep]) {
      assert.doesNotMatch(text, han, `${language} still shows Han in "${text}"`);
    }
  }
});
