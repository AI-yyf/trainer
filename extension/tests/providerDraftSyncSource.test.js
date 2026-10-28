'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');
const { readAppModuleSource } = require('./helpers/appModuleSource');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
// Round 2: the editable draft, its facts projection and the hydration effect
// moved into the provider-connection controller (DESIGN.md §3).
const controllerSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'app',
  'useProviderConnectionController.ts',
);

function providerHydrationEffect(source) {
  const sourceFile = ts.createSourceFile(controllerSourcePath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
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
    'providerDraftSource', 'providerDraftSourceKey', 'settingsActionKind', 'settingsScopeKey', 'settingsActionScopeRef',
  ]);
  return ts.transpileModule(`(${effect.arguments[0].getText(sourceFile)})();`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
}

test('provider draft sync only follows stable provider transport fields', () => {
  const source = fs.readFileSync(controllerSourcePath, 'utf8');

  // One field table owns projection, comparison and reset — a new fact field
  // cannot be projected in one place and forgotten in another.
  assert.match(source, /const DRAFT_FIELDS: readonly DraftFieldDescriptor\[\] = \[/);
  const fieldKeys = [...source.matchAll(/^\s{2,4}key: "([a-zA-Z]+)",/gm)].map((match) => match[1]);
  assert.deepEqual(fieldKeys, [
    'name', 'protocol', 'baseUrl', 'model', 'contextWindowTokens', 'maxOutputTokens',
    'modelTokenLimits', 'credentialMode', 'catalogModels', 'allowedModels', 'deniedModels',
    'embeddingModel', 'catalogSource', 'cacheTtlSeconds', 'requestDefaults', 'thinkingConfig',
  ]);
  // The host's display fallback must never land in the editable draft.
  assert.match(source, /fromFacts: \(facts\) => \(facts\.configured \? facts\.name : ""\)/);
  assert.match(source, /fromFacts: \(facts\) => facts\.protocol \?\? "openai_chat_completions_compatible"/);
  assert.match(
    source,
    /useEffect\(\(\) => \{[\s\S]*?providerDraftSourceKeyRef\.current === providerDraftSourceKey[\s\S]*?setDraftState\(providerDraftSource\);[\s\S]*?providerDraftIsDirtyRef\.current = false;[\s\S]*?\}, \[[\s\S]*?providerDraftSource,[\s\S]*?providerDraftSourceKey,[\s\S]*?settingsActionKind,[\s\S]*?settingsScopeKey,[\s\S]*?settingsActionScopeRef,[\s\S]*?\]\);/,
  );
  assert.match(
    source,
    /const providerSavePayload = useMemo\(\(\) => \{[\s\S]*?catalogModels: providerDraft\.catalogModels \?\? \[\],[\s\S]*?requestDefaults: providerDraft\.requestDefaults \?\? \{\},[\s\S]*?capabilities: facts\.capabilities,[\s\S]*?\}, \[facts\.capabilities, providerDraft\]\);/,
  );
  // No second hydration path may reset the draft on raw fact changes.
  assert.doesNotMatch(
    source,
    /useEffect\(\(\) => \{[\s\S]*?setDraftState\([\s\S]*?\}, \[facts\]\);/,
  );
});

test('provider hydration preserves dirty drafts across discovery and scope changes, allowing current save/clear', () => {
  const source = fs.readFileSync(controllerSourcePath, 'utf8');
  const effect = providerHydrationEffect(source);
  const incoming = {
    name: 'Saved provider', protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://saved.example/v1', model: 'saved-model', contextWindowTokens: 100,
    maxOutputTokens: 20, modelTokenLimits: { 'saved-model': { contextWindowTokens: 100 } },
    credentialMode: 'ui_proxy', catalogModels: ['saved-model'], allowedModels: ['saved-model'],
    deniedModels: [], embeddingModel: '', catalogSource: 'provider_live', cacheTtlSeconds: 60,
    requestDefaults: { temperature: 0.2 }, thinkingConfig: { enabled: true }, apiKey: '',
  };

  for (const dirty of [false, true]) {
    for (const sameScope of [false, true]) {
      for (const kind of [undefined, 'list-models', 'test-provider', 'save-provider', 'clear-provider']) {
        const draft = { baseUrl: 'https://unsaved.example/v1', model: 'unsaved-model', apiKey: 'draft-key' };
        const calls = [];
        const context = {
          providerDraftSourceKeyRef: { current: 'previous' }, providerDraftSourceKey: 'incoming',
          providerDraftIsDirtyRef: { current: dirty }, settingsActionScopeRef: { current: sameScope ? 'current' : 'old' },
          settingsScopeKey: 'current', settingsActionKind: kind,
          providerDraftSource: incoming, setDraftState(next) { calls.push(next); },
        };
        vm.runInNewContext(effect, context, { filename: controllerSourcePath });
        const shouldHydrate = !dirty || (sameScope && ['save-provider', 'clear-provider'].includes(kind));
        const label = `dirty=${dirty}, sameScope=${sameScope}, action=${kind ?? 'idle'}`;
        assert.equal(calls.length, shouldHydrate ? 1 : 0, label);
        assert.equal(context.providerDraftSourceKeyRef.current, 'incoming', label);
        assert.equal(context.providerDraftIsDirtyRef.current, shouldHydrate ? false : dirty, label);
        assert.deepEqual(calls.length ? { ...calls[0] } : draft, shouldHydrate ? { ...incoming } : draft, label);
      }
    }
  }

  // The public setter marks the draft dirty (every learner edit, including the
  // settings panel's) so a host refresh cannot overwrite it.
  assert.match(
    source,
    /const setProviderDraft = useCallback\(\s*\(update[\s\S]*?\) => \{\s*providerDraftIsDirtyRef\.current = true;\s*setDraftState\(update\);\s*\},\s*\[\],\s*\);/,
  );
  assert.match(
    source,
    /const markProviderDraftSaved = useCallback\(\(\) => \{\s*providerDraftIsDirtyRef\.current = false;\s*setDraftState\(\(current\) => \(current\.apiKey \? \{ \.\.\.current, apiKey: "" \} : current\)\);\s*\}, \[\]\);/,
  );
  const appSource = readAppModuleSource();
  assert.match(appSource, /if \(next\) \{\s*settingsActionScopeRef\.current = settingsScopeKey;/);
  assert.match(
    appSource,
    /settingsActionState\.kind === "save-provider"[\s\S]*?operationMessage\.tone === "success"[\s\S]*?markProviderDraftSaved\(\);/,
  );
});

test('provider save and test commands use the language currently shown in Settings', () => {
  const source = readAppModuleSource();

  assert.match(
    source,
    /commandId: "trainer\.provider\.save",\s*payload: \{ \.\.\.providerSavePayload, responseLanguage: layout\.composerLanguage \}/,
  );
  assert.match(
    source,
    /commandId: trainerCommands\.testProvider,\s*payload: \{\s*responseLanguage: layout\.composerLanguage,/,
  );
});
