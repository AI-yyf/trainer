'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { readAppModuleSource } = require('./helpers/appModuleSource');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const trainingViewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'TrainingWorkbenchView.tsx',
);

test('Training why-now does not backfill leftover formal title or focus', () => {
  const appSource = readAppModuleSource();
  const viewSource = fs.readFileSync(trainingViewPath, 'utf8');

  assert.match(appSource, /liveTrainingWhyNow\(/);
  assert.match(appSource, /readTrainingCardText\(boundTrainingCardFacts, "whyNow", \(\) => liveTrainingWhy\)/);
  assert.doesNotMatch(
    appSource,
    /const localizedWhyNow = hasRenderableTrainingCard\s*\?\s*pickLanguageAlignedTrainingText\(\s*layout\.composerLanguage,\s*trainingWhyThisCard,/,
  );
  assert.match(viewSource, /const cardOnlyWhyNowSummary = compactCardText\(firstText\(resolvedWhyNow\), 120\);/);
  assert.doesNotMatch(
    viewSource,
    /resolvedWhyNow \|\|\s*sourceSummary \|\|\s*currentFocus \|\|\s*coachSummary/,
  );
});
