'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('Training why and source do not use leftover formal plan.summary', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const whyStart = source.indexOf('const localizedWhyNow = hasRenderableTrainingCard');
  const whyEnd = source.indexOf('const localizedSourceSummary = hasRenderableTrainingCard', whyStart);
  const sourceStart = source.indexOf('const localizedSourceSummary = hasRenderableTrainingCard');
  const sourceEnd = source.indexOf('const localizedCurrentFocus = hasRenderableTrainingCard', sourceStart);

  assert.ok(whyStart >= 0 && whyEnd > whyStart, 'expected Training why picker');
  assert.ok(sourceStart >= 0 && sourceEnd > sourceStart, 'expected Training source picker');

  const whyBlock = source.slice(whyStart, whyEnd);
  const sourceBlock = source.slice(sourceStart, sourceEnd);
  assert.match(source, /liveTrainingFormalSummary\(/);
  assert.match(source, /liveTrainingSourceFallback\(/);
  assert.match(source, /const liveTrainingWhy = liveTrainingWhyNow\(\{[\s\S]*?liveWhy: liveTrainingSummary/);
  assert.match(whyBlock, /liveTrainingWhy/);
  assert.doesNotMatch(whyBlock, /data\.plan\.summary/);
  assert.match(sourceBlock, /liveTrainingSource/);
  assert.doesNotMatch(sourceBlock, /data\.plan\.summary/);
});
