'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const helpersSource = fs.readFileSync(path.resolve(webviewRoot, 'lib', 'composerModelHelpers.ts'), 'utf8');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('composer model switch prioritizes live models and excludes configured aliases after resolution', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  // §四十八: menu item construction lives in lib/composerModelHelpers.ts.
  const helpers = helpersSource;

  assert.match(helpers, /const liveModels = Array\.isArray\(provider\.availableModels\)/);
  assert.match(helpers, /const fallbackModels = \[/);
  assert.match(
    helpers,
    /\.\.\.\(liveModels\.length > 0 \? liveModels : fallbackModels\),/,
  );
  assert.match(helpers, /\.\.\.\(Array\.isArray\(provider\.catalogModels\)/);
  assert.match(helpers, /\.\.\.Object\.keys\(provider\.modelTokenLimits \?\? \{\}\)/);
  assert.match(helpers, /const resolvedModel = provider\.resolvedModel\?\.trim\(\) \?\? "";/);
  assert.match(helpers, /const configuredModel = provider\.model\.trim\(\);/);
  assert.match(helpers, /\.\.\.\(resolvedModel \? \[\] : \[configuredModel\]\),/);
  assert.match(helpers, /const configuredModelIsAlias = Boolean\(/);
  assert.match(helpers, /\(configuredModelIsAlias && modelKey === configuredModelKey\)/);
  assert.match(helpers, /evaluateProviderModelPolicy,/);
  assert.match(helpers, /filterProviderModelOptions,/);
  assert.match(helpers, /const currentProviderModelPolicy = \{/);
  assert.match(
    helpers,
    /const filteredModelCandidates = filterProviderModelOptions\(\s*modelCandidates,\s*currentProviderModelPolicy,\s*\{ retainModels: activeModel \? \[activeModel\] : \[\] \},\s*\);/,
  );
  assert.match(helpers, /for \(const candidate of filteredModelCandidates\)/);
  assert.match(helpers, /const knownModelMap = new Map<string, string>\(\);/);
  assert.match(helpers, /knownModelMap\.has\(modelKey\)/);
  assert.match(helpers, /const knownModels = Array\.from\(knownModelMap\.values\(\)\);/);
  assert.doesNotMatch(helpers, /knownModelMap\.values\(\)\)\.sort\(/);
  assert.match(helpers, /knownModels\.length > 0/);
  assert.match(helpers, /const modelPolicy = evaluateProviderModelPolicy\(modelName, currentProviderModelPolicy\);/);
  assert.match(helpers, /isSelectable: modelPolicy\.allowed && !isActive,/);
  assert.match(helpers, /policyReason: modelPolicy\.reason,/);
  assert.match(helpers, /selectionKind:\s*"model"/);
  assert.match(source, /buildComposerProviderMenuItems\(data\.providerConfig, layout\.composerLanguage\)/);
  assert.match(source, /commandId:\s*trainerCommands\.switchProviderModel/);
  assert.match(source, /reason:\s*"composer_model_switch"/);
  assert.match(source, /profile\.selectionKind === "profile"/);
});

test('composer model switch keeps current provider models visible even when saved profiles exist', () => {
  const helpers = helpersSource;

  assert.match(helpers, /export function buildComposerProviderMenuItems/);
  assert.match(helpers, /const activeProviderModelItems =/);
  assert.match(helpers, /knownModels\.length > 0/);
  assert.match(helpers, /return \[\s*\.\.\.activeProviderModelItems,/);
  assert.match(helpers, /items\.filter\(\(item\) => !item\.isActive\)/);
});

test('composer model switch label stays honest about the active model', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(source, /const composerProviderProfileLabel = useMemo/);
  assert.match(source, /const resolvedModel = data\.providerConfig\.resolvedModel\?\.trim\(\);/);
  assert.match(source, /const configuredModel = data\.providerConfig\.model\.trim\(\);/);
  assert.match(helpersSource, /function compactComposerModelLabel\(/);
  assert.match(source, /const composerModelButtonDisplayLabel =\s*composerModelActionDensity === "compact"/);
  assert.match(source, /compactComposerModelLabel\(\s*composerModelButtonLabel,/);
  assert.doesNotMatch(source, /const currentSelectionSummaryLabel =/);
  assert.doesNotMatch(source, /composerModelActionDensity === "compact" \? "Auto" : composerModelButtonLabel/);
});

test('composer model switch becomes an accessible icon action in a narrow sidebar', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(source, /density=\{composerModelActionDensity\}/);
  assert.match(source, /id: "model-switch",\s*compact: composerModelActionDensity === "compact",/);
  assert.match(source, /icon: <BrainIcon size=\{16\} \/>/);
  assert.match(source, /ariaLabel: composerModelButtonTitle/);
  assert.match(source, /setComposerModelActionDensity\(width < 430 \? "compact" : "default"\)/);
});

test('Coach composer keeps model selection focused while setup stays in Settings', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(source, /const openComposerModelSettings = useCallback\(\(\) => \{/);
  assert.match(source, /setActiveView\("settings"\);/);
  assert.match(
    source,
    /if \(!data\.providerConfig\.configured && !composerHasSavedProfiles\) \{\s*openComposerModelSettings\(\);\s*return;/,
  );
  assert.match(source, /toggleComposerModelMenu/);
  assert.match(source, /id: "model-switch",/);
  assert.match(source, /label: composerModelButtonDisplayLabel,/);
  assert.match(source, /onClick: toggleComposerModelMenu,/);
  assert.match(source, /onClick=\{\(\) => switchComposerProviderModel\(profile\.model\)\}/);
  assert.match(source, /onClick=\{\(\) => switchComposerProviderProfile\(profile\.id\)\}/);
  assert.match(source, /const hasModelQuery = composerModelQuery\.trim\(\)\.length > 0;/);
  assert.match(
    source,
    /const visibleModels = visibleSelections\.filter\(\s*\(profile\) => profile\.selectionKind === "model",\s*\);/,
  );
  assert.match(source, /const defaultVisibleModels = composerProviderMenuItems/);
  assert.match(source, /const COMPOSER_MODEL_PICKER_INITIAL_OPTION_LIMIT = 6;/);
  assert.match(source, /\.slice\(0, COMPOSER_MODEL_PICKER_INITIAL_OPTION_LIMIT\);/);
  assert.match(source, /const retainedBlockedActiveModel =/);
  assert.match(source, /const displayedModels = hasModelQuery/);
  assert.match(source, /retainedBlockedActiveModel \? \[retainedBlockedActiveModel\] : \[\]/);
  assert.match(source, /const nonActiveModelCount = composerProviderMenuItems\.filter\(/);
  assert.match(
    source,
    /\(item\) => item\.selectionKind === "model" && !item\.isActive,/,
  );
  assert.match(source, /const showSearch = nonActiveModelCount > COMPOSER_MODEL_PICKER_INITIAL_OPTION_LIMIT;/);
  assert.match(source, /const activeModelItem = composerProviderMenuItems\.find\(/);
  assert.match(source, /const hasOnlyCurrentModel =/);
  assert.match(
    source,
    /Boolean\(activeModelItem\) && nonActiveModelCount === 0 && savedProfiles\.length === 0/,
  );
  assert.match(source, /const showModelSection =/);
  assert.match(source, /hasModelQuery \|\| defaultVisibleModels\.length > 0 \|\| hasOnlyCurrentModel/);
  assert.match(source, /composerProviderCopy\.modelPicker\.onlyCurrentModel/);
  assert.match(source, /composerProviderCopy\.modelPicker\.currentModel/);
  assert.match(source, /\{showSearch \|\| hasModelQuery \? \(/);
  assert.match(source, /appUiCopy\(layout\.composerLanguage, "刷新模型"\)/);
  assert.match(source, /\{showModelSection \? \(/);
  assert.doesNotMatch(source, /searchMoreModelsHint/);
  assert.match(source, /!hasModelQuery && savedProfiles\.length > 0/);
  assert.match(source, /<details className="composer-provider-group">/);
  assert.doesNotMatch(source, /<div className="composer-provider-summary">/);
  assert.match(source, /const modelDisabled = profile\.isActive \|\| profile\.isSelectable === false;/);
  assert.match(source, /disabled=\{modelDisabled\}/);
  assert.match(source, /composer-provider-list__label">\{policyHint\}/);
  assert.match(source, /aria-current=\{profile\.isActive \? "true" : undefined\}/);
  assert.doesNotMatch(source, /providerMenuTokenBadges/);
  assert.doesNotMatch(source, /composer-provider-list__detail/);
  assert.doesNotMatch(source, /composer-provider-badge/);
  assert.doesNotMatch(
    source,
    /<span>\{providerRecoveryLocale\(layout\.composerLanguage\)\.connectionStillWorks\}<\/span>/,
  );
});

test('composer model switch retains a restricted active model but blocks a stale selection before host dispatch', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(helpersSource, /function composerModelPolicyHint\(/);
  assert.match(source, /const composerActiveModelPolicy = useMemo\(\(\) => \{/);
  assert.match(source, /const composerActiveModelPolicyHint = composerModelPolicyHint\(/);
  assert.match(source, /composerActiveModelPolicyHint \?\?/);
  assert.match(source, /const activeModelPolicyHint = composerModelPolicyHint\(/);

  const callbackStart = source.indexOf('const switchComposerProviderModel = useCallback');
  const callbackEnd = source.indexOf('\n  const handleVerifyTrainingFromIde', callbackStart);
  assert.ok(callbackStart >= 0 && callbackEnd > callbackStart);
  const callback = source.slice(callbackStart, callbackEnd);
  assert.match(callback, /const modelPolicy = evaluateProviderModelPolicy\(model, \{/);
  assert.match(callback, /if \(!modelPolicy\.allowed\) \{[\s\S]*?setOperationMessage\([\s\S]*?return;/);
  assert.ok(callback.indexOf('if (!modelPolicy.allowed)') < callback.indexOf('setOpenMenu(undefined)'));
  assert.ok(
    callback.indexOf('if (!modelPolicy.allowed)') <
      callback.indexOf('commandId: trainerCommands.switchProviderModel'),
  );
  assert.match(callback, /model: modelPolicy\.model,/);
});

test('composer model menu localizes current and single-model states for every supported language', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const languages = ["zh-CN", "en-US", "es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR", "pt-BR"];

  for (const language of languages) {
    assert.match(
      source,
      new RegExp(`"${language}": \\{\\s*modelPicker: \\{\\s*currentModel: [^\\n]+,\\s*onlyCurrentModel:`),
    );
  }
});
