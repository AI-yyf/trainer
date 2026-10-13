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
  // The dead coachSummary card prop is gone; the coach chrome still reaches
  // the learner only through the host-text source-summary chain (the sidecar
  // localizes these templates per the workspace response language).
  const sourceSummaryStart = appSource.indexOf('const localizedSourceSummary');
  assert.ok(sourceSummaryStart >= 0, 'expected the localized source-summary chain');
  assert.match(
    appSource.slice(sourceSummaryStart, sourceSummaryStart + 900),
    /pickFirstText\(\s*leftoverTrainingHandoffChromeNotLive\s*\?\s*undefined\s*:[\s\S]*?liveTrainingCoachChrome,/,
  );
  assert.doesNotMatch(
    appSource,
    /handoffSummary,\s*resolvedCoachSummary,\s*liveTrainingSource,/,
  );
});
