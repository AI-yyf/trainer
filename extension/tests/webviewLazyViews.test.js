'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('Resources and Training stay out of the Coach entry bundle until their view opens', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(
    source,
    /const ResourcesWorkbenchView = lazy\(async \(\) => \{[\s\S]*?import\("\.\.\/components\/resources\/ResourcesWorkbenchView"\)/,
  );
  assert.match(
    source,
    /const TrainingWorkbenchView = lazy\(async \(\) => \{[\s\S]*?import\("\.\.\/components\/training\/TrainingWorkbenchView"\)/,
  );
  assert.doesNotMatch(
    source,
    /import \{\s*ResourcesWorkbenchView,[\s\S]*?\} from "\.\.\/components\/resources\/ResourcesWorkbenchView"/,
  );
  assert.doesNotMatch(
    source,
    /import \{\s*TrainingWorkbenchView,[\s\S]*?\} from "\.\.\/components\/training\/TrainingWorkbenchView"/,
  );
  assert.match(source, /<Suspense[\s\S]*?label=\{resourcesViewLabel\(layout\.composerLanguage\)\}/);
  assert.match(source, /<Suspense fallback=\{<ViewFallback label=\{t\.training\}/);
});
