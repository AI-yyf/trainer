'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('coach suggested action footer keeps a direct training handoff when a current card exists', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(source, /const coachTrainingInlineAction = useMemo/);
  assert.match(source, /if \(leftoverTrainingHandoffChromeNotLive\) \{\s*return null;/);
  assert.match(source, /const selectedCardId = activeTrainingCardId;/);
  assert.match(source, /if \(!selectedCardId\) \{\s*return null;/);
  assert.match(source, /label: t\.trainingOpenCurrentCard,/);
  assert.match(source, /if \(latestCoachArtifact && !coachTrainingInlineAction\)/);
  assert.match(source, /title=\{coachTrainingInlineAction\.title\}/);
  assert.match(source, /onClick=\{\(\) => setActiveView\("training"\)\}/);
});
