'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

function sourceBetween(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  return start >= 0 && end >= 0 ? source.slice(start, end) : '';
}

test('provider settings actions and model menu use the complete locale copy', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const settingsFeedback = sourceBetween(
    source,
    'function buildSettingsFeedback(',
    'function providerBlockingReason(',
  );
  const providerStatus = sourceBetween(
    source,
    '  const providerStatus = useMemo<SettingsSectionStatus>(() => {',
    '  const coachDefaultsStatus = useMemo<SettingsSectionStatus>(() => {',
  );
  const modelMenu = sourceBetween(
    source,
    '  const composerProviderCopy = providerSettingsLocale(layout.composerLanguage);',
    '  const composerProviderMenuItems = useMemo<ComposerProviderMenuItem[]>(() => {',
  );

  assert.match(source, /const providerSettingsCopy: Record<ComposerLanguage, ProviderSettingsLocale> = \{/);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(source, new RegExp(`"${language}": \\{`));
  }

  assert.match(settingsFeedback, /const copy = providerSettingsLocale\(language\);/);
  assert.match(settingsFeedback, /copy\.feedback\.save/);
  assert.match(settingsFeedback, /copy\.feedback\.refresh/);
  assert.match(settingsFeedback, /copy\.feedback\.test/);
  assert.match(settingsFeedback, /copy\.feedback\.clear/);
  assert.doesNotMatch(settingsFeedback, /language === "zh-CN"/);

  assert.match(providerStatus, /const copy = providerSettingsLocale\(layout\.composerLanguage\);/);
  assert.match(providerStatus, /copy\.pending\.save/);
  assert.match(providerStatus, /copy\.pending\.refresh/);
  assert.match(providerStatus, /copy\.pending\.test/);
  assert.match(providerStatus, /copy\.pending\.clear/);
  assert.doesNotMatch(providerStatus, /layout\.composerLanguage === "zh-CN"/);

  assert.match(modelMenu, /composerProviderCopy\.menu\.chooseModel/);
  assert.match(modelMenu, /composerProviderCopy\.menu\.saveConnectionFirst/);
  assert.doesNotMatch(modelMenu, /layout\.composerLanguage === "zh-CN"/);
});
