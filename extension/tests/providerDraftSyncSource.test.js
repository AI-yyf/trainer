'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('provider draft sync only follows stable provider transport fields', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(
    source,
    /const providerDraftSource = useMemo\(\s*\(\) => \(\{[\s\S]*?configured: data\.providerConfig\.configured,[\s\S]*?profileId: data\.providerConfig\.profileId \?\? "",[\s\S]*?name: data\.providerConfig\.name,[\s\S]*?protocol: data\.providerConfig\.protocol \?\? "openai_chat_completions_compatible",[\s\S]*?baseUrl: data\.providerConfig\.baseUrl,[\s\S]*?model: data\.providerConfig\.model,[\s\S]*?modelTokenLimits: data\.providerConfig\.modelTokenLimits,[\s\S]*?credentialMode: data\.providerConfig\.credentialMode \?\? "ui_proxy",[\s\S]*?catalogModels: data\.providerConfig\.catalogModels \?\? \[\],[\s\S]*?allowedModels: data\.providerConfig\.allowedModels \?\? \[\],[\s\S]*?deniedModels: data\.providerConfig\.deniedModels \?\? \[\],[\s\S]*?embeddingModel: data\.providerConfig\.embeddingModel \?\? "",[\s\S]*?catalogSource: data\.providerConfig\.catalogSource \?\? "provider_live",[\s\S]*?cacheTtlSeconds: data\.providerConfig\.cacheTtlSeconds,[\s\S]*?requestDefaults: data\.providerConfig\.requestDefaults \?\? \{\},[\s\S]*?\}\),[\s\S]*?data\.providerConfig\.configured,[\s\S]*?data\.providerConfig\.profileId,[\s\S]*?data\.providerConfig\.name,[\s\S]*?data\.providerConfig\.protocol,[\s\S]*?data\.providerConfig\.baseUrl,[\s\S]*?data\.providerConfig\.model,[\s\S]*?data\.providerConfig\.modelTokenLimits,[\s\S]*?data\.providerConfig\.credentialMode,[\s\S]*?data\.providerConfig\.catalogModels,[\s\S]*?data\.providerConfig\.allowedModels,[\s\S]*?data\.providerConfig\.deniedModels,[\s\S]*?data\.providerConfig\.embeddingModel,[\s\S]*?data\.providerConfig\.catalogSource,[\s\S]*?data\.providerConfig\.cacheTtlSeconds,[\s\S]*?data\.providerConfig\.requestDefaults,[\s\S]*?\);/,
  );
  assert.match(
    source,
    /useEffect\(\(\) => \{[\s\S]*?providerDraftSourceKeyRef\.current === providerDraftSourceKey[\s\S]*?setProviderDraft\(\{[\s\S]*?name: providerDraftSource\.name,[\s\S]*?protocol: providerDraftSource\.protocol,[\s\S]*?baseUrl: providerDraftSource\.baseUrl,[\s\S]*?model: providerDraftSource\.model,[\s\S]*?modelTokenLimits: providerDraftSource\.modelTokenLimits,[\s\S]*?credentialMode: providerDraftSource\.credentialMode,[\s\S]*?catalogModels: providerDraftSource\.catalogModels,[\s\S]*?allowedModels: providerDraftSource\.allowedModels,[\s\S]*?deniedModels: providerDraftSource\.deniedModels,[\s\S]*?embeddingModel: providerDraftSource\.embeddingModel,[\s\S]*?catalogSource: providerDraftSource\.catalogSource,[\s\S]*?cacheTtlSeconds: providerDraftSource\.cacheTtlSeconds,[\s\S]*?requestDefaults: providerDraftSource\.requestDefaults,[\s\S]*?apiKey: "",[\s\S]*?\}\);[\s\S]*?\}, \[providerDraftSource, providerDraftSourceKey, settingsActionState\?\.kind\]\);/,
  );
  assert.match(
    source,
    /const providerSavePayload = useMemo\(\(\) => \{[\s\S]*?catalogModels: providerDraft\.catalogModels \?\? \[\],[\s\S]*?requestDefaults: providerDraft\.requestDefaults \?\? \{\},[\s\S]*?capabilities: data\.providerConfig\.capabilities,[\s\S]*?\}, \[data\.providerConfig\.capabilities, providerDraft\]\);/,
  );
  assert.doesNotMatch(
    source,
    /useEffect\(\(\) => \{[\s\S]*?setProviderDraft\(\{[\s\S]*?apiKey: "",[\s\S]*?\}\);[\s\S]*?\}, \[data\.providerConfig\]\);/,
  );
});

test('model discovery keeps a partially completed provider draft intact', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(source, /const providerDraftIsDirtyRef = useRef\(false\);/);
  assert.match(
    source,
    /const shouldKeepUnsavedProviderDraft =[\s\S]*?providerDraftIsDirtyRef\.current[\s\S]*?settingsActionState\?\.kind !== "save-provider"[\s\S]*?settingsActionState\?\.kind !== "clear-provider";/,
  );
  assert.match(
    source,
    /if \(shouldKeepUnsavedProviderDraft\) \{\s*return;\s*\}/,
  );
  assert.match(
    source,
    /onProviderDraftChange=\{\(patch\) => \{\s*providerDraftIsDirtyRef\.current = true;/,
  );
  assert.match(
    source,
    /settingsActionState\.kind === "save-provider"[\s\S]*?operationMessage\.tone === "success"[\s\S]*?setProviderDraft\(\(current\) => \(current\.apiKey \? \{ \.\.\.current, apiKey: "" \} : current\)\);/,
  );
});

test('provider save and test commands use the language currently shown in Settings', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(
    source,
    /commandId: "trainer\.provider\.save",\s*payload: \{ \.\.\.providerSavePayload, responseLanguage: layout\.composerLanguage \}/,
  );
  assert.match(
    source,
    /commandId: trainerCommands\.testProvider,\s*payload: \{\s*responseLanguage: layout\.composerLanguage,/,
  );
});
