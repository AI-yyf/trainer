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

test('settings provider catalog keeps manually saved models in the per-model panel', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');

  assert.match(
    source,
    /const draftCatalogModels =\s*providerDraft\.catalogModels \?\? \(canUseSavedModelMetadata \? provider\.catalogModels \?\? \[\] : \[\]\);/,
  );
  assert.match(
    source,
    /const liveCatalogModels = canUseSavedModelMetadata \? provider\.catalogModels \?\? \[\] : \[\];/,
  );
  assert.match(source, /\.\.\.draftCatalogModels,/);
  assert.match(source, /\.\.\.liveCatalogModels,/);
  assert.match(
    source,
    /const handleAddManualModel = \(\) => \{[\s\S]*?const model = manualModelDraft\.trim\(\);[\s\S]*?catalogModels: mergeDraftStringList\(draftCatalogModels, model\),[\s\S]*?model,[\s\S]*?setManualModelDraft\(""\);/,
  );
  assert.match(source, /catalogModels: mergeDraftStringList\(draftCatalogModels, modelName\)/);
  assert.match(source, /catalogModels: draftCatalogModels\.filter\(/);
  assert.match(source, /const localizedCatalogSavedModelsLabel: Record<ComposerLanguage, string> = \{/);
  const localizedSavedModelsLabels = {
    "zh-CN": "\u5df2\u4fdd\u5b58\u6a21\u578b",
    "en-US": "Saved models",
    "es-ES": "Modelos guardados",
    "fr-FR": "Modeles enregistres",
    "de-DE": "Gespeicherte Modelle",
    "ja-JP": "\u4fdd\u5b58\u6e08\u307f\u30e2\u30c7\u30eb",
    "ko-KR": "\uc800\uc7a5\ub41c \ubaa8\ub378",
    "pt-BR": "Modelos salvos",
  };
  for (const [language, label] of Object.entries(localizedSavedModelsLabels)) {
    assert.match(source, new RegExp(`"${language}": "${label}"`));
  }
  assert.match(
    source,
    /catalogModelsSummary\s*\?\s*\{\s*label: localizedCatalogSavedModelsLabel\[language\],/,
  );
  assert.match(
    source,
    /catalogModelsSummary\s*\?\s*\{\s*label: localizedCatalogSavedModelsLabel\[language\],\s*value: shortenSummary\(catalogModelsSummary, 80\),\s*\}\s*:\s*null/,
  );
  assert.match(source, /Remove model/);
});

test('settings does not reuse saved model metadata for a changed provider transport', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');

  assert.match(source, /const canUseSavedModelMetadata = !providerHasDraftChanges \|\| sameDraftTransportAsSaved;/);
  assert.match(
    source,
    /const liveModelTokenLimits = canUseSavedModelMetadata \? provider\.modelTokenLimits : undefined;/,
  );
  assert.match(
    source,
    /const currentLiveModel = canUseSavedModelMetadata \? provider\.model\.trim\(\) : "";/,
  );
  assert.match(
    source,
    /canUseSavedModelMetadata \? provider\.resolvedModel\?\.trim\(\) \?\? "" : "",/,
  );
  assert.match(
    source,
    /const canNestModelLimitsInCatalog =\s*canUseSavedModelMetadata && providerCatalogRows\.length > 0;/,
  );
  assert.match(source, /const providerCatalogPanel =\s*canNestModelLimitsInCatalog \? \(/);
});
