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

test('settings stores context and output limits at the model level', () => {
  const source = fs.readFileSync(settingsViewPath, 'utf8');

  assert.match(source, /readProviderModelTokenLimit,/);
  assert.match(source, /withProviderModelTokenLimit,/);
  assert.match(source, /modelTokenLimits\?: Record<string, ProviderModelTokenLimit>;/);
  assert.match(source, /contextWindowTokens\?: number;/);
  assert.match(source, /maxOutputTokens\?: number;/);
  assert.match(source, /const modelLimitNames = filterProviderModelOptions\(/);
  assert.match(source, /const selectableModelOptions = filterProviderModelOptions\(/);
  assert.match(source, /const MODEL_PICKER_RECENT_OPTION_LIMIT = 5;/);
  assert.match(source, /const MODEL_PICKER_SEARCH_OPTION_LIMIT = 8;/);
  assert.match(source, /const matchingModelOptions = useMemo\(/);
  assert.match(source, /const visibleModelOptions = useMemo\(/);
  assert.match(
    source,
    /const \[modelPickerOpen, setModelPickerOpen\] = useState\(\(\) => !providerDraft\.model\.trim\(\)\);/,
  );
  assert.match(
    source,
    /<details\b(?=[^>]*className="settings-model-picker")(?=[^>]*open=\{modelPickerOpen\})[^>]*>/,
  );
  assert.match(source, /setModelPickerOpen\(picker\.open\);/);
  assert.doesNotMatch(source, /\{availableModels\.length > 0 \? \(/);
  assert.doesNotMatch(source, /\{selectableModelOptions\.length > 0 \? \(/);
  assert.match(source, /<span>\{currentDraftModel \|\| copy\.availableModels\}<\/span>/);
  assert.match(
    source,
    /<select\b(?=[^>]*aria-label=\{copy\.model\})(?=[^>]*value=\{visibleModelSelection\})[^>]*>/,
  );
  assert.match(source, /visibleModelOptions\.map\(\(modelName\) => \(/);
  assert.doesNotMatch(source, /shouldGuideModelConfiguration/);
  assert.doesNotMatch(source, /settings-sheet__model-limits-panel"\s+open=/);
  assert.match(
    source,
    /const updateDraftModelTokenLimit = \(\s*modelName: string,\s*patch: Partial<ProviderModelTokenLimit>,\s*\) => \{/s,
  );
  assert.match(
    source,
    /const nextModelTokenLimits = withProviderModelTokenLimit\(draftModelTokenLimits, normalizedModel, \{/,
  );
  assert.match(
    source,
    /if \(normalizedModel === currentDraftModel\) \{[\s\S]*?contextWindowTokens:[\s\S]*?"contextWindowTokens" in patch[\s\S]*?maxOutputTokens:[\s\S]*?"maxOutputTokens" in patch[\s\S]*?modelTokenLimits: nextModelTokenLimits,/,
  );
  assert.match(source, /const clearDraftModelTokenLimit = \(modelName: string\) => \{/);
  assert.match(source, /contextWindowTokens: parsePositiveIntegerInput\(event\.target\.value\),/);
  assert.match(source, /maxOutputTokens: parsePositiveIntegerInput\(event\.target\.value\),/);
});

test('settings keeps model allow and deny lists in the saved provider contract', () => {
  const source = fs.readFileSync(settingsViewPath, 'utf8');

  assert.match(source, /allowedModels\?: string\[\];/);
  assert.match(source, /deniedModels\?: string\[\];/);
  assert.match(source, /stringArrayKey\(providerDraft\.allowedModels \?\? provider\.allowedModels\) !==\s*stringArrayKey\(provider\.allowedModels\)/);
  assert.match(source, /stringArrayKey\(providerDraft\.deniedModels \?\? provider\.deniedModels\) !==\s*stringArrayKey\(provider\.deniedModels\)/);
  assert.match(source, /allowedModels: parseDraftStringList\(event\.target\.value\),/);
  assert.match(source, /deniedModels: parseDraftStringList\(event\.target\.value\),/);
});
