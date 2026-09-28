
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const settingsRoot = path.resolve(
  __dirname, '..', 'webview', 'src', 'components', 'settings',
);
const copyPath = path.join(settingsRoot, 'remoteSupportCopy.ts');
const viewPath = path.join(settingsRoot, 'CoachSettingsView.tsx');

test('remote-support settings panel is record-driven with eight-language copy (§十五)', () => {
  const copy = fs.readFileSync(copyPath, 'utf8');
  const view = fs.readFileSync(viewPath, 'utf8');

  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(copy, new RegExp(`"${language}": \{`));
  }
  // All eight install states carry button + disabled; no zh branch in the module.
  for (const state of ['not_installed', 'installing', 'await_reload', 'preparing', 'ready', 'version_incompatible', 'connection_lost', 'upgrade_available']) {
    assert.match(copy, new RegExp(`${state}:\\s*\\{\\s*button:`));
  }
  assert.doesNotMatch(copy, /=== "zh-CN"/);
  // The view consumes the record; the old zh/en ternary block is gone from the section.
  const sectionStart = view.indexOf('data-settings-subsection="remote-support"');
  const section = view.slice(sectionStart, view.indexOf('</section>', sectionStart));
  assert.match(section, /REMOTE_SUPPORT_COPY\[language\]/);
  assert.match(section, /remoteSupportStateView\(language, companionInstallState\)/);
  assert.doesNotMatch(section, /language === "zh-CN"/);
});
