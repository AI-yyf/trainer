'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

function providerHydrationEffect(source) {
  const sourceFile = ts.createSourceFile(appSourcePath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const matches = [];
  function visit(node) {
    if (ts.isCallExpression(node) && node.expression.getText(sourceFile) === 'useEffect') {
      const callback = node.arguments[0];
      if (callback && callback.getText(sourceFile).includes('providerDraftSourceKeyRef.current === providerDraftSourceKey')) {
        matches.push(node);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  assert.equal(matches.length, 1, 'one canonical provider hydration effect');
  const effect = matches[0];
  const dependencies = effect.arguments[1];
  assert.ok(dependencies && ts.isArrayLiteralExpression(dependencies), 'hydration has explicit dependencies');
  assert.deepEqual(dependencies.elements.map((node) => node.getText(sourceFile)), [
    'providerDraftSource', 'providerDraftSourceKey', 'settingsActionState?.kind', 'settingsScopeKey',
  ]);
  return ts.transpileModule(`(${effect.arguments[0].getText(sourceFile)})();`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
}

test('provider draft sync only follows stable provider transport fields', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(
    source,
    /const providerDraftSource = useMemo\(\s*\(\) => \(\{[\s\S]*?configured: data\.providerConfig\.configured,[\s\S]*?profileId: data\.providerConfig\.profileId \?\? "",[\s\S]*?name: data\.providerConfig\.configured \? data\.providerConfig\.name : "",[\s\S]*?protocol: data\.providerConfig\.protocol \?\? "openai_chat_completions_compatible",[\s\S]*?baseUrl: data\.providerConfig\.baseUrl,[\s\S]*?model: data\.providerConfig\.model,[\s\S]*?modelTokenLimits: data\.providerConfig\.modelTokenLimits,[\s\S]*?credentialMode: data\.providerConfig\.credentialMode \?\? "ui_proxy",[\s\S]*?catalogModels: data\.providerConfig\.catalogModels \?\? \[\],[\s\S]*?allowedModels: data\.providerConfig\.allowedModels \?\? \[\],[\s\S]*?deniedModels: data\.providerConfig\.deniedModels \?\? \[\],[\s\S]*?embeddingModel: data\.providerConfig\.embeddingModel \?\? "",[\s\S]*?catalogSource: data\.providerConfig\.catalogSource \?\? "provider_live",[\s\S]*?cacheTtlSeconds: data\.providerConfig\.cacheTtlSeconds,[\s\S]*?requestDefaults: data\.providerConfig\.requestDefaults \?\? \{\},[\s\S]*?\}\),[\s\S]*?data\.providerConfig\.configured,[\s\S]*?data\.providerConfig\.profileId,[\s\S]*?data\.providerConfig\.name,[\s\S]*?data\.providerConfig\.protocol,[\s\S]*?data\.providerConfig\.baseUrl,[\s\S]*?data\.providerConfig\.model,[\s\S]*?data\.providerConfig\.modelTokenLimits,[\s\S]*?data\.providerConfig\.credentialMode,[\s\S]*?data\.providerConfig\.catalogModels,[\s\S]*?data\.providerConfig\.allowedModels,[\s\S]*?data\.providerConfig\.deniedModels,[\s\S]*?data\.providerConfig\.embeddingModel,[\s\S]*?data\.providerConfig\.catalogSource,[\s\S]*?data\.providerConfig\.cacheTtlSeconds,[\s\S]*?data\.providerConfig\.requestDefaults,[\s\S]*?\);/,
  );
  assert.match(
    source,
    /useEffect\(\(\) => \{[\s\S]*?providerDraftSourceKeyRef\.current === providerDraftSourceKey[\s\S]*?setProviderDraft\(\{[\s\S]*?name: providerDraftSource\.name,[\s\S]*?protocol: providerDraftSource\.protocol,[\s\S]*?baseUrl: providerDraftSource\.baseUrl,[\s\S]*?model: providerDraftSource\.model,[\s\S]*?modelTokenLimits: providerDraftSource\.modelTokenLimits,[\s\S]*?credentialMode: providerDraftSource\.credentialMode,[\s\S]*?catalogModels: providerDraftSource\.catalogModels,[\s\S]*?allowedModels: providerDraftSource\.allowedModels,[\s\S]*?deniedModels: providerDraftSource\.deniedModels,[\s\S]*?embeddingModel: providerDraftSource\.embeddingModel,[\s\S]*?catalogSource: providerDraftSource\.catalogSource,[\s\S]*?cacheTtlSeconds: providerDraftSource\.cacheTtlSeconds,[\s\S]*?requestDefaults: providerDraftSource\.requestDefaults,[\s\S]*?apiKey: "",[\s\S]*?\}\);[\s\S]*?\}, \[providerDraftSource, providerDraftSourceKey, settingsActionState\?\.kind, settingsScopeKey\]\);/,
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

test('provider hydration preserves dirty drafts across discovery and scope changes, allowing current save/clear', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const effect = providerHydrationEffect(source);
  const incoming = {
    name: 'Saved provider', protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://saved.example/v1', model: 'saved-model', contextWindowTokens: 100,
    maxOutputTokens: 20, modelTokenLimits: { 'saved-model': { contextWindowTokens: 100 } },
    credentialMode: 'ui_proxy', catalogModels: ['saved-model'], allowedModels: ['saved-model'],
    deniedModels: [], embeddingModel: '', catalogSource: 'provider_live', cacheTtlSeconds: 60,
    requestDefaults: { temperature: 0.2 }, thinkingConfig: { enabled: true },
  };

  for (const dirty of [false, true]) {
    for (const sameScope of [false, true]) {
      for (const kind of [undefined, 'list-models', 'test-provider', 'save-provider', 'clear-provider']) {
        const draft = { baseUrl: 'https://unsaved.example/v1', model: 'unsaved-model', apiKey: 'draft-key' };
        const calls = [];
        const context = {
          providerDraftSourceKeyRef: { current: 'previous' }, providerDraftSourceKey: 'incoming',
          providerDraftIsDirtyRef: { current: dirty }, settingsActionScopeRef: { current: sameScope ? 'current' : 'old' },
          settingsScopeKey: 'current', settingsActionState: kind ? { kind } : undefined,
          providerDraftSource: incoming, setProviderDraft(next) { calls.push(next); },
        };
        vm.runInNewContext(effect, context, { filename: appSourcePath });
        const shouldHydrate = !dirty || (sameScope && ['save-provider', 'clear-provider'].includes(kind));
        const label = `dirty=${dirty}, sameScope=${sameScope}, action=${kind ?? 'idle'}`;
        assert.equal(calls.length, shouldHydrate ? 1 : 0, label);
        assert.equal(context.providerDraftSourceKeyRef.current, 'incoming', label);
        assert.equal(context.providerDraftIsDirtyRef.current, shouldHydrate ? false : dirty, label);
        assert.deepEqual(calls.length ? { ...calls[0] } : draft, shouldHydrate ? { ...incoming, apiKey: '' } : draft, label);
      }
    }
  }

  assert.match(source, /const providerDraftIsDirtyRef = useRef\(false\);/);
  assert.match(source, /if \(next\) \{\s*settingsActionScopeRef\.current = settingsScopeKey;/);
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
