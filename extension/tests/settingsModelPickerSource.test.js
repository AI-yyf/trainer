'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const settingsSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);

test('Settings keeps model selection compact, searchable, and recoverable with a full name', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');

  assert.match(source, /const MODEL_PICKER_RECENT_OPTION_LIMIT = 5;/);
  assert.match(source, /const MODEL_PICKER_SEARCH_OPTION_LIMIT = 8;/);
  assert.match(
    source,
    /const draftModelPolicy = \{\s*allowedModels: providerDraft\.allowedModels \?\? provider\.allowedModels \?\? \[\],\s*deniedModels: providerDraft\.deniedModels \?\? provider\.deniedModels \?\? \[\],\s*\};/,
  );
  assert.match(
    source,
    /const selectableModelOptions = filterProviderModelOptions\(\s*mergeDraftStringList\(\s*currentDraftModel,\s*draftCatalogModels,\s*liveCatalogModels,\s*availableModels,\s*\),\s*draftModelPolicy,\s*\{ retainModels: currentDraftModel \? \[currentDraftModel\] : \[\] \},\s*\);/,
  );
  assert.match(
    source,
    /const modelPickerDefaultOptionLimit =\s*MODEL_PICKER_RECENT_OPTION_LIMIT \+ \(currentDraftModel \? 1 : 0\);/,
  );
  assert.match(source, /const modelPickerHasOverflow = selectableModelOptions\.length > modelPickerDefaultOptionLimit;/);
  assert.match(source, /return matchingModelOptions\.slice\(0, MODEL_PICKER_SEARCH_OPTION_LIMIT\);/);
  assert.match(source, /return selectableModelOptions\.slice\(0, modelPickerDefaultOptionLimit\);/);
  assert.match(source, /const showModelSearchInput = modelPickerHasOverflow \|\| manualModelEntryOpen;/);
  assert.match(source, /const exactMatchingModel = selectableModelOptions\.find\(/);
  assert.match(source, /const exactMatchingModelIsVisible = Boolean\(/);
  assert.match(
    source,
    /const typedModelPolicy = evaluateProviderModelPolicy\(modelSearchQuery, draftModelPolicy\);/,
  );
  assert.match(source, /const hasMatchingModelOptions = matchingModelOptions\.length > 0;/);
  assert.match(
    source,
    /const canUseTypedModel =\s*Boolean\(normalizedModelSearchQuery\) &&\s*typedModelPolicy\.allowed &&\s*\(!hasMatchingModelOptions \|\| Boolean\(exactMatchingModel\)\);/,
  );
  assert.match(
    source,
    /const showTypedModelAction =\s*canUseTypedModel && \(!exactMatchingModel \|\| !exactMatchingModelIsVisible\);/,
  );
  assert.match(
    source,
    /const visibleModelSelection =\s*normalizedModelSearchQuery && !currentDraftModelIsVisible \? "" : providerDraft\.model;/,
  );
  assert.match(source, /value=\{visibleModelSelection\}/);
  assert.match(source, /const handleUseTypedModel = \(\) => \{/);
  assert.match(source, /const model = exactMatchingModel \?\? modelSearchQuery\.trim\(\);/);
  assert.match(source, /exactMatchingModel\s*\? \{\}\s*:\s*\{ catalogModels: mergeDraftStringList\(draftCatalogModels, model\) \}/);
  assert.match(source, /setModelSearchQuery\(""\);\s*setManualModelEntryOpen\(false\);/);
  assert.match(source, /normalizedModelSearchQuery && hiddenMatchingModelCount > 0/);
  assert.match(source, /modelPickerCopy\.moreMatchesHint\(hiddenMatchingModelCount\)/);
  assert.match(source, /\{showTypedModelAction \? \(/);
  assert.doesNotMatch(source, /allModelsHint/);
});

test('Settings applies the connection model policy without hiding an already selected invalid model', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');

  assert.match(source, /evaluateProviderModelPolicy,/);
  assert.match(source, /filterProviderModelOptions,/);
  assert.match(source, /const currentDraftModelPolicy = evaluateProviderModelPolicy\(currentDraftModel, draftModelPolicy\);/);
  assert.match(source, /retainModels: currentDraftModel \? \[currentDraftModel\] : \[\]/);
  assert.match(source, /if \(!evaluateProviderModelPolicy\(selectedModel, draftModelPolicy\)\.allowed\) \{\s*return;\s*\}/);
  assert.match(source, /currentDraftModel && !currentDraftModelPolicy\.allowed/);
  assert.match(source, /modelPolicyHint\(/);
});

test('Settings commits an exact search with Enter and a list choice with its native change event', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');

  assert.match(
    source,
    /if \(event\.key !== "Enter" \|\| !canUseTypedModel\) \{\s*return;\s*\}\s*event\.preventDefault\(\);\s*handleUseTypedModel\(\);/,
  );
  assert.match(
    source,
    /const canUseTypedModel =\s*Boolean\(normalizedModelSearchQuery\) &&\s*typedModelPolicy\.allowed &&\s*\(!hasMatchingModelOptions \|\| Boolean\(exactMatchingModel\)\);/,
  );
  assert.match(
    source,
    /const selectedModel = event\.target\.value;[\s\S]*?onProviderDraftChange\(\{ model: selectedModel \}\);[\s\S]*?setModelPickerOpen\(false\);/,
  );
});

test('Settings does not let manual per-model limits bypass the connection model policy', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');

  assert.match(
    source,
    /const manualModelPolicy = evaluateProviderModelPolicy\(\s*normalizedManualModelDraft,\s*draftModelPolicy,\s*\);/,
  );
  assert.match(source, /const manualModelBlockedByPolicy =\s*Boolean\(normalizedManualModelDraft\) && !manualModelPolicy\.allowed;/);
  assert.match(
    source,
    /const canAddManualModel =\s*normalizedManualModelDraft\.length > 0 &&\s*manualModelPolicy\.allowed &&\s*!modelLimitKeySet\.has\(normalizedManualModelDraft\.toLowerCase\(\)\);/,
  );

  const manualModelHandler = source.match(
    /const handleAddManualModel = \(\) => \{([\s\S]*?)\n  \};/,
  );
  assert.ok(manualModelHandler, 'expected manual model handler');
  assert.match(
    manualModelHandler[1],
    /const modelPolicy = evaluateProviderModelPolicy\(model, draftModelPolicy\);/,
  );
  assert.match(manualModelHandler[1], /!modelPolicy\.allowed/);
  assert.match(manualModelHandler[1], /catalogModels: mergeDraftStringList\(draftCatalogModels, model\),/);
  assert.match(manualModelHandler[1], /model,/);
  assert.match(source, /manualModelBlockedByPolicy\s*\? modelPolicyHint\(/);
});

test('Settings localizes model picker actions in every supported language', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');
  const start = source.indexOf('function providerModelPickerCopy(');
  const end = source.indexOf('\nfunction providerModelCardCopy', start);

  assert.ok(start >= 0 && end > start, 'expected model picker locale copy');
  const pickerCopy = source.slice(start, end);
  for (const language of ["zh-CN", "en-US", "es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR", "pt-BR"]) {
    assert.match(pickerCopy, new RegExp(`"${language}": \\{`));
  }
  assert.match(pickerCopy, /refreshListDetail:/);
  assert.match(pickerCopy, /enterModelName:/);
  assert.match(pickerCopy, /useTypedModel:/);
  assert.match(pickerCopy, /saveAndUse:/);
});

test('Settings turns successful discovery into model selection without auto-selecting a model', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');

  assert.match(
    source,
    /const hasDiscoveredDraftModels = draftNeedsModelChoice && availableModels\.length > 0;/,
  );
  assert.match(
    source,
    /const canFindDraftModels = draftNeedsModelChoice && !hasDiscoveredDraftModels && canRefreshModels;/,
  );
  assert.match(source, /hasDiscoveredDraftModels\s*\? settingsPhrase\(language, "chooseModel"\)/);
  assert.match(source, /hasDiscoveredDraftModels\s*\? focusDraftModelPicker/);
  assert.match(source, /const modelPickerRef = useRef<HTMLDetailsElement \| null>\(null\);/);
  assert.match(source, /const modelSearchInputRef = useRef<HTMLInputElement \| null>\(null\);/);
  assert.match(source, /const modelSelectRef = useRef<HTMLSelectElement \| null>\(null\);/);
  assert.match(source, /picker\.scrollIntoView\(\{ block: "nearest" \}\);/);
  assert.match(source, /if \(showModelSearchInput\) \{\s*modelSearchInputRef\.current\?\.focus\(\);\s*return;\s*\}/);
  assert.match(source, /modelSelectRef\.current\?\.focus\(\);/);
  assert.match(source, /ref=\{modelPickerRef\}/);
  assert.match(source, /ref=\{modelSelectRef\}/);
  assert.doesNotMatch(source, /onProviderDraftChange\(\{ model: availableModels\[0\]/);
});

test('Settings keeps first-time manual model entry compact until the user asks for it', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');

  assert.match(source, /manualFallback: string;/);
  assert.match(source, /const modelListingCompletedForDraft = providerHasDraftChanges/);
  assert.match(source, /const shouldShowManualModelFallback =/);
  assert.match(
    source,
    /providerDraftReadyForModelDiscovery &&\s*\(modelListingCompletedForDraft \|\| modelSelectionNeedsRecovery\)/,
  );
  assert.match(source, /const modelDiscoveryGuidance = !shouldShowModelDiscoveryGuidance/);
  assert.match(source, /modelDiscoveryCopy\.missingBaseUrl/);
  assert.match(source, /modelDiscoveryCopy\.missingApiKey/);
  assert.match(source, /modelDiscoveryCopy\.modelOptional/);
  assert.match(source, /modelDiscoveryCopy\.manualFallback/);
  assert.match(source, /<details\s+ref=\{modelPickerRef\}\s+className="settings-model-picker"\s+open=\{modelPickerOpen\}/);
  assert.match(source, /\{showModelSearchInput \|\| visibleModelOptions\.length > 0 \? \(/);
  assert.match(
    source,
    /const showManualModelEntryAction =\s*!showModelSearchInput &&\s*\(selectableModelOptions\.length === 0 \|\| modelSelectionNeedsRecovery\);/,
  );
  assert.match(source, /\{showManualModelEntryAction \? \(\s*<div className="settings-model-picker__filter">/);
  assert.match(source, /\{modelPickerCopy\.enterModelName\}/);
  assert.match(source, /\{modelPickerCopy\.useTypedModel\(modelSearchQuery\.trim\(\)\)\}/);
  assert.match(source, /\{modelDiscoveryGuidance \? \(/);
});

test('Settings keeps per-model limits out of the primary model choice when a catalog is available', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');

  assert.match(
    source,
    /const canNestModelLimitsInCatalog =\s*canUseSavedModelMetadata && providerCatalogRows\.length > 0;/,
  );
  assert.match(source, /canNestModelLimitsInCatalog \? \(/);
  assert.match(source, /\{providerModelLimitsPanel\}\s*<details className="settings-sheet__minor-panel">/);
  assert.match(source, /\{!canNestModelLimitsInCatalog \? providerModelLimitsPanel : null\}/);
});

test('Settings never lets per-model limits bypass the connection model policy', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');

  assert.match(
    source,
    /const modelLimitNames = filterProviderModelOptions\([\s\S]*?draftModelPolicy,[\s\S]*?retainModels: currentDraftModel \? \[currentDraftModel\] : \[\]/,
  );
  assert.match(
    source,
    /if \(!normalizedModel \|\| !evaluateProviderModelPolicy\(normalizedModel, draftModelPolicy\)\.allowed\) \{\s*return;/,
  );
  assert.match(source, /const modelLimitPolicy = evaluateProviderModelPolicy\(modelName, draftModelPolicy\);/);
  assert.match(source, /const modelLimitBlockedByPolicy = !modelLimitPolicy\.allowed;/);
  assert.match(source, /disabled=\{modelLimitBlockedByPolicy\}/);
  assert.match(source, /if \(modelLimitBlockedByPolicy\) \{\s*return;/);
});

test('Settings clears a model filter when the picker closes or the saved connection changes', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');

  assert.match(source, /const \[modelPickerOpen, setModelPickerOpen\] = useState\(\(\) => !providerDraft\.model\.trim\(\)\);/);
  assert.match(
    source,
    /useEffect\(\(\) => \{\s*setModelSearchQuery\(""\);\s*setManualModelEntryOpen\(false\);\s*\}, \[provider\.profileId\]\);/,
  );
  assert.match(source, /if \(!picker\.open\) \{\s*resetModelPickerSearch\(\);\s*return;/);
  assert.match(
    source,
    /onClick=\{\(\) => \{\s*resetModelPickerSearch\(\);\s*setModelPickerOpen\(false\);\s*onSwitchProviderProfile\?\.\(profile\.id\);/,
  );
});

test('Settings keeps the long model list searchable and defers inner save or test actions during discovery', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');

  assert.match(source, /refreshListDetail: string;/);
  assert.match(source, /modelPickerCopy\.refreshListDetail/);
  assert.match(source, /saveAndUse: \(model: string\) => string;/);
  assert.match(source, /const saveProviderConnectionLabel = currentDraftModel/);
  assert.match(source, /label=\{saveProviderConnectionLabel\}/);
  assert.match(source, /const modelDiscoveryGuidanceActive = canFindDraftModels \|\| hasDiscoveredDraftModels;/);
  assert.match(source, /const showProviderDetailActions =\s*!modelDiscoveryGuidanceActive \|\| showSecondaryModelDiscoveryAction;/);
  assert.match(source, /\{!modelDiscoveryGuidanceActive \? \(\s*<ActionButton/);
  assert.match(source, /\{!modelDiscoveryGuidanceActive && showProviderDetailTestAction \? \(/);
});

test('Settings clears stale model state when the provider transport changes', () => {
  const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(
    source,
    /const hasProtocol = Object\.prototype\.hasOwnProperty\.call\(patch, "protocol"\);/,
  );
  assert.match(
    source,
    /const hasBaseUrl = Object\.prototype\.hasOwnProperty\.call\(patch, "baseUrl"\);/,
  );
  assert.match(
    source,
    /\(hasProtocol && normalizeProviderProtocol\(current\.protocol\) !== nextProtocol\) \|\|[\s\S]*?\(hasBaseUrl && normalizedCurrentBaseUrl !== normalizedNextBaseUrl\)/,
  );

  const transportReset = source.match(
    /if \(transportChanged\) \{\s*return \{([\s\S]*?)\n\s*\};\s*\}/,
  );
  assert.ok(transportReset, 'transport changes should reset the draft model state');
  assert.match(transportReset[1], /model: "",/);
  assert.match(transportReset[1], /contextWindowTokens: undefined,/);
  assert.match(transportReset[1], /maxOutputTokens: undefined,/);
  assert.match(transportReset[1], /modelTokenLimits: undefined,/);
  assert.match(transportReset[1], /catalogModels: \[\],/);
  assert.doesNotMatch(transportReset[1], /resolveProviderModelTokenState|apiKey:/);
});
