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

test('settings opens on a blocker banner that only renders when something is wrong', () => {
  const source = readSettingsSource();
  const barStart = source.indexOf('data-settings-status-bar="true"');
  const stripStart = source.indexOf('className={`settings-availability-strip');
  const bodyStart = source.indexOf('settings-sheet__body settings-sheet__body--hierarchical');

  assert.ok(barStart > bodyStart, 'expected the banner inside the settings body');
  assert.ok(stripStart > barStart, 'expected the banner before the availability strip');
  // Healthy Settings opens straight on content: the banner is gated on issues.
  assert.match(source, /\{settingsStatusIssues\.length > 0 \? \(\s*<div\s+className="settings-status-bar settings-status-bar--blockers"/);
  assert.match(source, /role="region"\s+aria-label=\{settingsGlobalCopy\.settingsStatusRegionLabel\}/);
  assert.match(source, /settingsStatusConnectionReady\s*=\s*providerCoachReady && !providerHasDraftChanges/);
  // No always-on "connected · language · memory" line any more.
  assert.doesNotMatch(source, /settingsGlobalCopy\.settingsStatusLanguage/);
  assert.doesNotMatch(source, /settingsGlobalCopy\.settingsStatusMemory/);
  // Each blocker carries the action that clears it.
  assert.match(source, /settingsStatusIssues\.push\(\{\s*id: "key",\s*label: settingsGlobalCopy\.settingsStatusNoApiKey,\s*target: "connection",\s*action: openProviderApiKey,\s*\}\)/);
  assert.match(source, /providerSaved && !providerTestPassed/);
  assert.match(source, /resolvedWorkspaceTrustState !== "trusted"/);
  assert.match(source, /target: "workspace",\s*action: onTrustWindow,/);
  // Trust is stated once — inside the banner — and nowhere else on the sheet.
  assert.equal((source.match(/data-settings-workspace-trust="true"/g) ?? []).length, 1);
  assert.doesNotMatch(source, /settings-availability-strip__trust/);
  // Teaching/preferences save on change, so "unsaved" only ever means the connection draft.
  assert.match(source, /if \(connectionDirty\) \{\s*settingsStatusIssues\.push\(\{\s*id: "unsaved"/);
  assert.match(source, /revealSettingsSection\(issue\.target\)/);
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

test('teaching is a flat section: preset radio, feedback + style, language, advanced-context fold', () => {
  const source = readSettingsSource();
  const start = source.indexOf('data-settings-section="teaching"');
  const end = source.indexOf('data-settings-section="preferences"', start);
  assert.ok(start >= 0 && end > start, 'expected the teaching section before preferences');
  const section = source.slice(start, end);

  assert.match(section, /role="radiogroup"/);
  assert.match(section, /role="radio"/);
  assert.match(section, /aria-checked=\{answerStyle === option\.value\}/);
  // Feedback mode and teaching style moved here from the dissolved Advanced tab.
  assert.match(section, /onChange=\{onAnswerModeChange\}/);
  assert.match(section, /onChange=\{onTeachingStyleChange\}/);
  assert.match(section, /data-settings-language="true"/);
  assert.match(section, /onChange=\{onLanguageChange\}/);
  assert.match(section, /persistenceKey="settings-advanced-context"/);
  assert.match(section, /open=\{answerStyle === "custom" \|\| advancedContextPinned\}/);
  // The five legacy knobs live inside the advanced-context fold, values intact.
  assert.match(section, /<ContextList rows=\{contextRows\} onLabel=\{copy\.on\} offLabel=\{copy\.off\} \/>/);
  assert.match(section, /tuneAdvancedContextKnob\(\(\) => onContextDetailChange\?\.\(value\)\)/);
  // Save-on-change: no per-section Save button or dirty dot; a live status
  // span reports saving / saved / sanitized failure instead.
  assert.doesNotMatch(section, /onClick=\{onSaveCoachSettings\}/);
  assert.doesNotMatch(section, /settings-section-save/);
  assert.doesNotMatch(section, /settings-section-dot/);
  assert.match(section, /\{coachSettingsAutosaveNode\}/);
  assert.match(source, /sanitizeErrorSurfaceText\(coachSettingsSaveFailure\.detail\)/);
  // No collapsible card shell around a single-card category.
  assert.doesNotMatch(section, /persistenceKey="settings-teaching-prefs"/);
});

test('settings navigation is six flat categories saved on change', () => {
  const source = readSettingsSource();
  const app = fs.readFileSync(path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx'), 'utf8');

  // §64: Connection / Workspace / Teaching / Skills / Preferences / Advanced.
  assert.match(
    source,
    /type SettingsCategory =\s*\n?\s*\| "connection"\s*\n?\s*\| "workspace"\s*\n?\s*\| "teaching"\s*\n?\s*\| "skills"\s*\n?\s*\| "preferences"\s*\n?\s*\| "advanced";/,
  );
  assert.doesNotMatch(source, /id: "memory",/);
  assert.match(source, /id: "skills",/);
  assert.match(source, /id: "advanced",/);
  assert.doesNotMatch(source, /useState\(false\);\s*\n\s*type SettingsCategory/);
  for (const id of ['connection', 'workspace', 'teaching', 'skills', 'preferences', 'advanced']) {
    assert.match(source, new RegExp(`data-settings-section="${id}"`));
  }
  // Every choice-type setting persists as soon as it changes.
  for (const cb of [
    'onLanguageChange',
    'onAnswerModeChange',
    'onTeachingStyleChange',
    'onFollowCurrentFileChange',
    'onCoachDefaultsChange',
    'onContextDetailChange',
    'onIncludeCurrentFileChange',
    'onIncludeSelectionChange',
    'onIncludeDiagnosticsChange',
    'onIncludeRelatedFilesChange',
  ]) {
    assert.match(app, new RegExp(`${cb}=\\{autosaving\\(`), `${cb} must autosave`);
  }
  assert.match(app, /const COACH_SETTINGS_AUTOSAVE_DELAY_MS = \d+;/);
  assert.match(app, /persistCoachSettingsRef\.current\(\);/);
});

test('connection details live behind an explicit advanced level', () => {
  const source = readSettingsSource();

  // The drill-in entry stays collapsed in the edit level; the advanced level
  // header is the expanded counterpart that returns to the previous level.
  assert.match(source, /aria-expanded="false"/);
  assert.match(source, /onClick=\{openProviderDetails\}/);
  assert.match(source, /aria-expanded="true"/);
  assert.match(source, /onClick=\{\(\) => setConnectionView\(advancedReturnView\)\}/);
  assert.doesNotMatch(source, /providerDetailRequested/);
  assert.match(source, /data-settings-section="connection"/);
  // The advanced level holds protocol plus the read-only truth tables.
  const detailsStart = source.indexOf('connectionView === "advanced" ? (');
  const detailsEnd = source.indexOf('{providerPrimaryActions}', detailsStart);
  const details = source.slice(detailsStart, detailsEnd);
  assert.match(details, /settingsSupportPhrase\(language, "protocol"\)/);
  assert.match(details, /\{!canNestModelLimitsInCatalog \? providerModelLimitsPanel : null\}/);
  assert.match(details, /modelAndTestDetail/);
  // Saved profiles + templates live in the top provider bar and the add-level
  // directory, not inside the advanced level.
  assert.doesNotMatch(details, /settings-provider-profile/);
  const connectionStart = source.indexOf('data-settings-section="connection"');
  const connectionEnd = source.indexOf('<form', connectionStart);
  const connection = source.slice(connectionStart, connectionEnd);
  assert.match(connection, /\{providerDirectory\}/);
});

test('preferences groups appearance, memory, review and maintenance with original handlers', () => {
  const source = readSettingsSource();
  const start = source.indexOf('data-settings-section="preferences"');
  const end = source.indexOf('<nav', start);
  assert.ok(start >= 0 && end > start, 'expected the preferences section');
  const section = source.slice(start, end);

  for (const sub of ['appearance', 'memory', 'review', 'maintenance']) {
    assert.match(section, new RegExp(`data-settings-subsection="${sub}"`));
  }
  assert.match(section, /onChange=\{onThemePreferenceChange\}/);
  assert.match(section, /onChange=\{onLearningSurfaceAlignmentChange\}/);
  // Memory scope, sharing grants, migration and sandbox authority keep their
  // original handlers; no merged save was introduced.
  assert.match(section, /onCoachDefaultsChange\?\.\(\{ memoryScope: value \}\)/);
  assert.match(section, /onCoachDefaultsChange\?\.\(\{ workingSetMode: value \}\)/);
  assert.match(section, /onCoachDefaultsChange\?\.\(\{ reviewCadence: value \}\)/);
  assert.match(section, /updateWorkspaceMemoryToggles\(\{ decisions: !workspaceMemoryToggles\.decisions \}\)/);
  assert.match(section, /<MemorySharingPanel/);
  assert.match(section, /onClick=\{onRefreshMemory\}/);
  assert.match(section, /onClick=\{onResetDefaults\}/);
  assert.doesNotMatch(section, /onClick=\{onSaveCoachSettings\}/);
  const memoryPanelSource = fs.readFileSync(
    path.resolve(__dirname, '..', 'webview', 'src', 'components', 'settings', 'MemorySharingPanel.tsx'),
    'utf8',
  );
  assert.match(memoryPanelSource, /onClick=\{\(\) => onRevokeMemoryShare\?\.\(grant\.sourceWorkspaceId\)\}/);
  assert.match(source, /onClick=\{onChooseManagedDataFolder\}/);
  assert.match(source, /onClick=\{onRefreshWorkspaceAuthority\}/);
});

test('empty connection state is one screen: paste card plus a template entry', () => {
  const source = readSettingsSource();
  assert.match(source, /const showQuickSetup = !providerSaved && connectionView === "auto";/);
  assert.match(source, /const showProviderTemplates = Boolean\(onUseProviderTemplateLabel\) && connectionView === "add";/);
  assert.match(source, /const showConnectionForm = providerSaved\s*\? providerHasDraftChanges \|\| connectionView === "edit"\s*: connectionView === "edit";/);
  assert.match(source, /data-settings-template-entry="true"/);
  assert.match(source, /settingsPhrase\(language, "startFromTemplate"\)/);
  // The quick-setup card no longer repeats the trust warning; the banner owns it.
  const card = fs.readFileSync(
    path.resolve(__dirname, '..', 'webview', 'src', 'components', 'settings', 'ProviderQuickSetup.tsx'),
    'utf8',
  );
  assert.doesNotMatch(card, /settings-quick-setup__untrusted-wrap/);
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
    'settingsPreferences',
    'settingsAppearance',
    'settingsAutosaving',
    'settingsAutosaved',
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
