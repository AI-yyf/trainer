'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const settingsViewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);
const copyPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'i18n', 'copy.ts');

function readSettingsSource() {
  return fs.readFileSync(settingsViewPath, 'utf8');
}

function presetTableSource(source) {
  const start = source.indexOf('const ANSWER_STYLE_PRESETS');
  const end = source.indexOf('function deriveAnswerStylePreset', start);
  assert.ok(start >= 0 && end > start, 'expected the answer style preset table');
  return source.slice(start, end);
}

test('settings opens with a live status summary bar before the availability strip', () => {
  const source = readSettingsSource();
  const barStart = source.indexOf('data-settings-status-bar="true"');
  const stripStart = source.indexOf('className={`settings-availability-strip');
  const bodyStart = source.indexOf('settings-sheet__body settings-sheet__body--hierarchical');

  assert.ok(barStart > bodyStart, 'expected the status bar inside the settings body');
  assert.ok(stripStart > barStart, 'expected the status bar before the availability strip');
  assert.match(source, /role="region"\s+aria-label=\{settingsGlobalCopy\.settingsStatusRegionLabel\}/);
  assert.match(source, /settingsStatusConnectionReady\s*=\s*providerCoachReady && !providerHasDraftChanges/);
  assert.match(source, /\{appliedProviderFactValue\} \· \{appliedModelFactValue\}/);
  assert.match(source, /settingsStatusIssues\.push\(\{\s*id: "key",\s*label: settingsGlobalCopy\.settingsStatusNoApiKey,\s*target: "connection",\s*\}\)/);
  assert.match(source, /providerSaved && !providerTestPassed/);
  assert.match(source, /resolvedWorkspaceTrustState !== "trusted"/);
  assert.match(source, /onClick=\{\(\) => revealSettingsSection\(issue\.target\)\}/);
});

test('status bar anomaly jumps smooth-scroll and flash once, honoring reduced motion', () => {
  const source = readSettingsSource();

  assert.match(source, /node\.scrollIntoView\(\{ behavior: reduced \? "auto" : "smooth", block: "start" \}\)/);
  assert.match(source, /const SETTINGS_SECTION_FLASH_MS = 600;/);
  assert.match(source, /setSectionFlash\(target\);/);
  assert.match(source, /window\.setTimeout\(\(\) => \{\s*setSectionFlash\(null\);\s*sectionFlashTimerRef\.current = null;\s*\}, SETTINGS_SECTION_FLASH_MS\)/);
  assert.match(source, /function prefersReducedMotion\(\)/);
  assert.match(source, /window\.matchMedia\("\(prefers-reduced-motion: reduce\)"\)/);
  assert.doesNotMatch(source, /behavior: "smooth", block: "start" \}\);[\s\S]{0,80}if \(!reduced/);
});

test('answer style presets map exactly to the five context knobs', () => {
  const source = readSettingsSource();
  const table = presetTableSource(source);

  assert.match(
    table,
    /simple: \{\s*contextDetail: "focused",\s*includeCurrentFile: true,\s*includeSelection: false,\s*includeDiagnostics: false,\s*includeRelatedFiles: false,\s*\}/,
  );
  assert.match(
    table,
    /balanced: \{\s*contextDetail: "balanced",\s*includeCurrentFile: true,\s*includeSelection: true,\s*includeDiagnostics: true,\s*includeRelatedFiles: false,\s*\}/,
  );
  assert.match(
    table,
    /deep: \{\s*contextDetail: "full",\s*includeCurrentFile: true,\s*includeSelection: true,\s*includeDiagnostics: true,\s*includeRelatedFiles: true,\s*\}/,
  );
});

test('preset derivation covers every legacy combination without dropping values', () => {
  const source = readSettingsSource();
  const start = source.indexOf('function deriveAnswerStylePreset');
  const end = source.indexOf('function readStoredAnswerStyle', start);
  assert.ok(start >= 0 && end > start, 'expected the preset derivation helper');
  const derivation = source.slice(start, end);

  // Rare legacy "all attachments off + focused" resolves to 简单.
  assert.match(
    derivation,
    /values\.contextDetail === "focused" &&\s*!values\.includeSelection &&\s*!values\.includeDiagnostics &&\s*!values\.includeRelatedFiles/,
  );
  assert.match(derivation, /return "custom";/);
  assert.match(source, /const answerStyle: AnswerStylePreset = answerStyleCustomSelected \? "custom" : derivedAnswerStyle;/);
  assert.match(source, /const ANSWER_STYLE_STORAGE_KEY = "trainer\.settings\.answerStyle";/);
  assert.match(source, /window\.localStorage\.setItem\(ANSWER_STYLE_STORAGE_KEY, preset\)/);
  // Manual knob edits switch to 自定义 through the existing callbacks only.
  assert.match(source, /const tuneAdvancedContextKnob = \(apply: \(\) => void\) => \{\s*setAnswerStyleCustomSelected\(true\);\s*writeStoredAnswerStyle\("custom"\);\s*apply\(\);\s*\};/);
  assert.doesNotMatch(source, /onIncludeCurrentFileChange\?\.\(target\.includeCurrentFile\) : undefined/);
});

test('teaching preferences shows only the preset radio, language, and advanced-context fold', () => {
  const source = readSettingsSource();
  const start = source.indexOf('persistenceKey="settings-teaching-prefs"');
  const end = source.indexOf('persistenceKey="settings-advanced"', start);
  assert.ok(start >= 0 && end > start, 'expected the teaching preferences section');
  const section = source.slice(start, end);

  assert.match(section, /role="radiogroup"/);
  assert.match(section, /role="radio"/);
  assert.match(section, /aria-checked=\{answerStyle === option\.value\}/);
  assert.match(section, /data-settings-language="true"/);
  assert.match(section, /onChange=\{onLanguageChange\}/);
  assert.match(section, /persistenceKey="settings-advanced-context"/);
  assert.match(section, /open=\{answerStyle === "custom" \|\| advancedContextPinned\}/);
  // The five legacy knobs live inside the advanced-context fold, values intact.
  assert.match(section, /<ContextList rows=\{contextRows\} onLabel=\{copy\.on\} offLabel=\{copy\.off\} \/>/);
  assert.match(section, /tuneAdvancedContextKnob\(\(\) => onContextDetailChange\?\.\(value\)\)/);
  // The dissolved workspace section keeps its save flow through the header action.
  assert.match(section, /onClick=\{onSaveCoachSettings\}/);
  assert.match(section, /settings-section-dot"/);
  assert.match(section, /settings-section-save/);
});

test('connection details stay toggle-driven while the required trio renders open', () => {
  const source = readSettingsSource();

  assert.match(source, /open=\{providerDetailRequested\}/);
  assert.match(source, /onToggle=\{setProviderDetailRequested\}/);
  assert.doesNotMatch(source, /const providerDetailOpen =/);
  assert.match(source, /level=\{2\}\s+persistenceKey="settings-provider"/);
  assert.match(source, /data-settings-section="connection"/);
  // The collapsed details hold protocol plus the read-only truth tables.
  const detailsStart = source.indexOf('persistenceKey="settings-provider"');
  const detailsEnd = source.indexOf('</CollapseSection>', detailsStart);
  const details = source.slice(detailsStart, detailsEnd);
  assert.match(details, /settingsSupportPhrase\(language, "protocol"\)/);
  assert.match(details, /\{!canNestModelLimitsInCatalog \? providerModelLimitsPanel : null\}/);
  assert.match(details, /modelAndTestDetail/);
  assert.match(details, /\{providerProfilesPanel\}/);
});

test('memory privacy and advanced sections default collapsed and keep their save endpoints', () => {
  const source = readSettingsSource();

  assert.match(source, /const \[memoryPrivacyOpen, setMemoryPrivacyOpen\] = useState\(false\);/);
  assert.match(source, /const \[advancedOpen, setAdvancedOpen\] = useState\(false\);/);
  assert.match(source, /persistenceKey="settings-memory-privacy"/);
  assert.match(source, /persistenceKey="settings-advanced"/);
  // Memory scope, sharing grants, migration and sandbox authority keep their
  // original handlers; no merged save was introduced.
  assert.match(source, /onCoachDefaultsChange\?\.\(\{ memoryScope: value \}\)/);
  assert.match(source, /onClick=\{\(\) => onRevokeMemoryShare\?\.\(grant\.sourceWorkspaceId\)\}/);
  assert.match(source, /onClick=\{onChooseManagedDataFolder\}/);
  assert.match(source, /onClick=\{onRefreshWorkspaceAuthority\}/);
  assert.match(source, /updateWorkspaceMemoryToggles\(\{ decisions: !workspaceMemoryToggles\.decisions \}\)/);
});

test('new settings copy ships in all eight languages', () => {
  const copySource = fs.readFileSync(copyPath, 'utf8');
  const keys = [
    'settingsStatusRegionLabel',
    'settingsStatusConnected',
    'settingsStatusNotConnected',
    'settingsStatusLanguage',
    'settingsStatusMemory',
    'settingsStatusNoApiKey',
    'settingsStatusNeedsTest',
    'settingsStatusTrust',
    'settingsStatusUnsaved',
    'settingsSectionConnection',
    'settingsTeachingPrefs',
    'settingsAnswerStyle',
    'answerStyleSimple',
    'answerStyleBalanced',
    'answerStyleDeep',
    'answerStyleCustom',
    'settingsAnswerStyleHint',
    'settingsAdvancedContext',
    'settingsMemoryPrivacy',
    'settingsAdvanced',
  ];
  for (const key of keys) {
    let count = 0;
    let index = copySource.indexOf(`${key}: "`);
    while (index >= 0) {
      count += 1;
      index = copySource.indexOf(`${key}: "`, index + 1);
    }
    assert.equal(count, 8, `${key} must be translated in all 8 languages`);
  }
});
