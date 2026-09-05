'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('composer model switch prioritizes live models and excludes configured aliases after resolution', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(source, /const liveModels = Array\.isArray\(data\.providerConfig\.availableModels\)/);
  assert.match(source, /const fallbackModels = \[/);
  assert.match(
    source,
    /\.\.\.\(liveModels\.length > 0 \? liveModels : fallbackModels\),/,
  );
  assert.match(source, /\.\.\.\(Array\.isArray\(data\.providerConfig\.catalogModels\)/);
  assert.match(source, /\.\.\.Object\.keys\(data\.providerConfig\.modelTokenLimits \?\? \{\}\)/);
  assert.match(source, /const resolvedModel = data\.providerConfig\.resolvedModel\?\.trim\(\) \?\? "";/);
  assert.match(source, /const configuredModel = data\.providerConfig\.model\.trim\(\);/);
  assert.match(source, /\.\.\.\(resolvedModel \? \[\] : \[configuredModel\]\),/);
  assert.match(source, /const configuredModelIsAlias = Boolean\(/);
  assert.match(source, /\(configuredModelIsAlias && modelKey === configuredModelKey\)/);
  assert.match(source, /evaluateProviderModelPolicy,/);
  assert.match(source, /filterProviderModelOptions,/);
  assert.match(source, /const currentProviderModelPolicy = \{/);
  assert.match(
    source,
    /const filteredModelCandidates = filterProviderModelOptions\(\s*modelCandidates,\s*currentProviderModelPolicy,\s*\{ retainModels: activeModel \? \[activeModel\] : \[\] \},\s*\);/,
  );
  assert.match(source, /for \(const candidate of filteredModelCandidates\)/);
  assert.match(source, /const knownModelMap = new Map<string, string>\(\);/);
  assert.match(source, /knownModelMap\.has\(modelKey\)/);
  assert.match(source, /const knownModels = Array\.from\(knownModelMap\.values\(\)\);/);
  assert.doesNotMatch(source, /knownModelMap\.values\(\)\)\.sort\(/);
  assert.match(source, /data\.providerConfig\.availableModels/);
  assert.match(source, /knownModels\.length > 0/);
  assert.match(source, /const modelPolicy = evaluateProviderModelPolicy\(modelName, currentProviderModelPolicy\);/);
  assert.match(source, /isSelectable: modelPolicy\.allowed && !isActive,/);
  assert.match(source, /policyReason: modelPolicy\.reason,/);
  assert.match(source, /selectionKind:\s*"model"/);
  assert.match(source, /commandId:\s*trainerCommands\.switchProviderModel/);
  assert.match(source, /reason:\s*"composer_model_switch"/);
  assert.match(source, /profile\.selectionKind === "profile"/);
});

test('composer model switch keeps current provider models visible even when saved profiles exist', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(source, /const activeProviderModelItems =/);
  assert.match(source, /knownModels\.length > 0/);
  assert.match(source, /return \[\s*\.\.\.activeProviderModelItems,/);
  assert.match(source, /items\.filter\(\(item\) => !item\.isActive\)/);
});

test('composer model switch label stays honest about the active model', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(source, /const composerProviderProfileLabel = useMemo/);
  assert.match(source, /const resolvedModel = data\.providerConfig\.resolvedModel\?\.trim\(\);/);
  assert.match(source, /const configuredModel = data\.providerConfig\.model\.trim\(\);/);
  assert.match(source, /function compactComposerModelLabel\(/);
  assert.match(source, /const composerModelButtonDisplayLabel =\s*composerModelActionDensity === "compact"/);
  assert.match(source, /compactComposerModelLabel\(\s*composerModelButtonLabel,/);
  assert.doesNotMatch(source, /const currentSelectionSummaryLabel =/);
  assert.doesNotMatch(source, /composerModelActionDensity === "compact" \? "Auto" : composerModelButtonLabel/);
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
  assert.match(source, /layout\.composerLanguage === "zh-CN" \? "刷新模型" : "Refresh models"/);
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

  assert.match(source, /function composerModelPolicyHint\(/);
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
