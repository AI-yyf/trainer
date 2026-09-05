'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const settingsViewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);

function extractProviderProfilesPanel(source) {
  const start = source.indexOf('const providerProfilesPanel =');
  if (start < 0) {
    return '';
  }
  const end = source.indexOf('  return (', start);
  return end >= 0 ? source.slice(start, end) : source.slice(start);
}

function sourceBetween(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  return start >= 0 && end >= 0 ? source.slice(start, end) : '';
}

test('settings provider profile actions are wired through App and rendered in Settings', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const settingsSource = fs.readFileSync(settingsViewPath, 'utf8');
  const providerProfilesPanel = extractProviderProfilesPanel(settingsSource);

  assert.match(appSource, /onSaveProviderProfile=\{\(\) => \{/);
  assert.match(appSource, /commandId:\s*trainerCommands\.saveProviderProfile/);
  assert.match(appSource, /onUseProviderTemplate=\{\(\) => \{/);
  assert.match(appSource, /commandId:\s*trainerCommands\.useProviderTemplate/);
  assert.match(appSource, /templateLabel:\s*"MiniMax"/);
  assert.match(appSource, /skipPicker:\s*true/);
  assert.match(appSource, /onRefreshProviderProfiles=\{\(\) => \{/);
  assert.match(appSource, /commandId:\s*trainerCommands\.refreshProviderProfiles/);
  assert.match(appSource, /onSwitchProviderProfile=\{\(profileId\) => \{/);
  assert.match(appSource, /commandId:\s*trainerCommands\.switchProviderProfile/);
  assert.match(appSource, /reason:\s*"settings_switch"/);

  assert.match(settingsSource, /onSaveProviderProfile\?: \(\) => void;/);
  assert.match(settingsSource, /const canSaveProviderProfile = Boolean\(/);
  assert.match(settingsSource, /const canSaveProviderConnection = Boolean\(/);
  assert.match(
    settingsSource,
    /const saveProviderConnectionLabel = currentDraftModel\s*\?\s*modelPickerCopy\.saveAndUse\(shortenSummary\(currentDraftModel, 32\)\)\s*:\s*copy\.setupAction;/,
  );
  assert.match(settingsSource, /label=\{saveProviderConnectionLabel\}/);
  assert.match(settingsSource, /title=\{saveProviderConnectionTitle\}/);
  assert.match(settingsSource, /onClick=\{onSaveProvider\}/);
  assert.match(settingsSource, /localizedSaveProfileLabel/);
  assert.match(settingsSource, /onClick=\{onSaveProviderProfile\}/);
  assert.match(
    settingsSource,
    /const localizedProviderProfilesLabel = providerDetailLabel\(language, "savedProfiles"\);/,
  );
  assert.match(providerProfilesPanel, /settings-provider-profile-panel__note/);
  assert.doesNotMatch(providerProfilesPanel, /settings-sheet__summary-grid/);
  assert.doesNotMatch(providerProfilesPanel, /open=\{providerProfileCount > 1 \|\| \(!providerSaved && providerProfileCount > 0\)\}/);
});

test('provider details keep connection status labels localized in every supported language', () => {
  const settingsSource = fs.readFileSync(settingsViewPath, 'utf8');
  const truthCopy = sourceBetween(
    settingsSource,
    'function providerConnectionTruthCopy(',
    'type ProviderDetailLabelKey =',
  );
  const detailLabels = sourceBetween(
    settingsSource,
    'function providerDetailLabel(',
    'function providerBaseUrlGuidance(',
  );

  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(truthCopy, new RegExp(`"${language}": \\{`));
    assert.match(detailLabels, new RegExp(`"${language}": \\{`));
  }

  assert.match(truthCopy, /"ja-JP": \{[\s\S]*protocol: "プロトコル"/);
  assert.match(truthCopy, /"ko-KR": \{[\s\S]*diagnostics: "연결 확인"/);
  assert.match(detailLabels, /"ja-JP": \{[\s\S]*baseUrl: "サービスのルート URL"/);
  assert.match(settingsSource, /const providerBaseUrlLabel = providerDetailLabel\(language, "baseUrl"\);/);
  assert.match(settingsSource, /const providerTruthCopy = providerConnectionTruthCopy\(language\);/);
});

test('settings provider copy is valid UTF-8 and keeps readable localized text', () => {
  const raw = fs.readFileSync(settingsViewPath);
  const settingsSource = raw.toString('utf8');

  assert.deepEqual(
    Buffer.from(settingsSource, 'utf8'),
    raw,
    'Settings source must remain valid UTF-8.',
  );
  assert.doesNotMatch(settingsSource, /\uFFFD/u);
  assert.doesNotMatch(settingsSource, /(?:涓嬩竴|銉|銆|妫€|鞐瓣|氇|靹滊)/u);

  for (const text of [
    '连接检查',
    'Comprobación de conexión',
    'Vérification de connexion',
    'Verbindungsprüfung',
    'プロトコル',
    '연결 확인',
    'Verificação da conexão',
  ]) {
    assert.match(settingsSource, new RegExp(text));
  }
});
