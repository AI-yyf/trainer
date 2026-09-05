'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('Training source and coach chrome do not backfill leftover formal title', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');

  assert.match(appSource, /liveTrainingCoachSummary\(/);
  assert.match(appSource, /liveTrainingCoachChrome/);
  assert.match(
    appSource,
    /leftoverTrainingHandoffChromeNotLive\s*\?\s*undefined\s*:\s*trainingState\?\.latestTrainingHandoff\?\.handoffSummary/,
  );
  assert.match(appSource, /liveTrainingCoachChrome,\s*liveTrainingSource,/);
  assert.match(
    appSource,
    /pickLanguageAlignedTrainingText\(layout\.composerLanguage, liveTrainingCoachChrome\)/,
  );
  assert.doesNotMatch(
    appSource,
    /handoffSummary,\s*resolvedCoachSummary,\s*liveTrainingSource,/,
  );
});
