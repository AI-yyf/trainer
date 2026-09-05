'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('Training card title does not use leftover formal plan or task title', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const titleStart = source.indexOf('const title = hasRenderableTrainingCard');
  const titleEnd = source.indexOf('const currentStep = hasRenderableTrainingCard', titleStart);

  assert.ok(titleStart >= 0 && titleEnd > titleStart, 'expected Training title picker');
  const titleBlock = source.slice(titleStart, titleEnd);
  assert.match(source, /liveTrainingTitleFallback\(/);
  assert.match(source, /liveTrainingNextChallengeTitle\(/);
  assert.match(source, /const visibleTrainingCardTitle = liveTrainingNextChallengeTitle\(\{/);
  assert.match(source, /formalTaskIsLiveRuntimeIdentity\(/);
  assert.match(titleBlock, /liveTrainingTitle/);
  assert.doesNotMatch(titleBlock, /data\.task\.title/);
  assert.doesNotMatch(titleBlock, /data\.plan\.title/);
  assert.match(titleBlock, /formalPlanLive \|\| liveTask \? resolvedCoachFocus : undefined/);
});
