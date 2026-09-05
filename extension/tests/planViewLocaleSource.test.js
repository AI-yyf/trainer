'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const localePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'i18n',
  'planViewCopy.ts',
);
const languages = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];

function sourceBetween(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);

  assert.ok(start >= 0, `expected ${startMarker}`);
  assert.ok(end > start, `expected ${endMarker} after ${startMarker}`);
  return source.slice(start, end);
}

test('Plan primary UI uses complete locale copy instead of a Chinese-English branch', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const localeSource = fs.readFileSync(localePath, 'utf8');
  const planView = sourceBetween(appSource, '  const renderPlanView = () => (', '  const renderSettingsView = () => (');

  for (const language of languages) {
    assert.match(localeSource, new RegExp(`"${language}":\\s*\\{`));
  }

  assert.match(appSource, /import \{ resolvePlanViewCopy \} from "\.\.\/lib\/i18n\/planViewCopy";/);
  assert.match(appSource, /const planText = resolvePlanViewCopy\(layout\.composerLanguage\);/);
  assert.match(planView, /goalHint=\{planText\.goalHint\}/);
  assert.match(planView, /supportSummaryLabel=\{planText\.supportSummaryLabel\}/);
  assert.match(planView, /composerDraftReplacement=\{[\s\S]*?pendingPlanComposerDraftReplacement/);
  assert.match(
    planView,
    /onStageSelect=\{\(stage\) => \{\s*requestPlanComposerGuidance\(stage\.title, "stage"\);\s*\}\}/,
  );
  assert.match(planView, /projectSubplansLabel=\{planText\.projectSubplansLabel\}/);
  assert.match(
    planView,
    /onProjectSubplanSelect=\{\(subplan\) => \{\s*requestPlanComposerGuidance\(subplan\.title, "project-subplan"\);\s*\}\}/,
  );
  assert.doesNotMatch(planView, /onStageSelect=\{[\s\S]*?setComposerDraft\(/);
  assert.doesNotMatch(planView, /layout\.composerLanguage === "zh-CN"/);
});
