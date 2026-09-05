'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');

function read(relativePath) {
  return fs.readFileSync(path.join(webviewRoot, relativePath), 'utf8');
}

test('composer and five-view navigation have accessible names and visible focus', () => {
  const app = read('app/App.tsx');
  const resources = read('components/resources/ResourcesWorkbenchView.tsx');
  const training = read('components/training/TrainingWorkbenchView.tsx');
  const settings = read('components/settings/CoachSettingsView.tsx');
  const composer = read('components/composer/CoachComposer.tsx');
  const action = read('components/common/ActionButton.tsx');
  const styles = read('styles.css');
  const types = read('lib/types.ts');

  assert.match(app, /aria-label=\{t\.viewNavigation\}/);
  assert.match(app, /aria-pressed=\{activeView === view\}/);
  assert.match(app, /data-testid=\{`trainer-view-nav-\$\{view\}`\}/);
  assert.match(
    types,
    /export const COACH_FIRST_SIDEBAR_VIEWS = \[\s*"coach",\s*"plan",\s*"resources",\s*"training",\s*"settings",\s*\] as const;/s,
  );
  assert.doesNotMatch(app, /<CoachOrientationRail/);

  assert.match(resources, /className="resources-knowledge__current-object"/);
  assert.match(resources, /localize\(language, "resourceDetail"\)/);
  assert.match(
    resources,
    /aria-label=\{\[localize\(language, "resourceDetail"\), selectedResource\.title\]/,
  );
  assert.match(training, /data-view-primary=/);
  assert.match(action, /aria-label=\{ariaLabel \?\? accessibleName\}/);
  assert.match(settings, /aria-labelledby="coach-settings-view-title"/);
  assert.match(composer, /aria-label=\{busy \? resolvedCancelLabel : resolvedSubmitButtonLabel\}/);
  assert.match(composer, /aria-label=\{localizedCopy\.clear\}/);

  assert.match(styles, /\.header-switcher__item:focus-visible/);
  assert.match(styles, /\.composer__send:focus-visible/);
  assert.match(styles, /outline:\s*2px solid var\(--focus-ring/);
});

test('language switch keeps the active view and composer stays the super-entry', () => {
  const state = read('app/useWorkbenchState.ts');
  const app = read('app/App.tsx');
  const types = read('lib/types.ts');
  const settings = read('components/settings/CoachSettingsView.tsx');

  assert.match(
    state,
    /setComposerLanguage:\s*\(composerLanguage\)\s*=>\s*set\(\(state\)\s*=>\s*\(\{\s*layout:\s*persistLayout\(\{\s*\.\.\.state\.layout,\s*composerLanguage,/,
  );
  assert.match(app, /showComposerShell = activeView !== "settings"/);
  assert.match(settings, /data-settings-language="true"/);
  assert.doesNotMatch(
    types,
    /export const COACH_FIRST_SIDEBAR_VIEWS = \[[^\]]*"research"/s,
  );
});
