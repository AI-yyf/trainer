// Restored behavioral regression test. Original file: extension/tests/hostTextNormalization.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Host text normalization: usable text kept, non-text dropped, training state text fields normalized.
//
// Restoration: whole - all 4 original test definitions, code and assertions unchanged.
// Target: webview TypeScript loaded through the inlined loadTsModule helper (in-memory transpile).
// Note: extension/tests/helpers/loadTsModule.js (deleted in df0a3e2a) is inlined above the tests: same in-memory TypeScript loader, logic unchanged.

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

// Inlined replacement for the deleted test helper extension/tests/helpers/loadTsModule.js:
// minimal CommonJS loader for the webview's TypeScript sources. Resolves relative
// imports recursively and delegates everything else to Node's require.
const { loadTsModule } = (() => {
  const fs = require('node:fs');
  const path = require('node:path');
  const vm = require('node:vm');

  const typescript = require(require.resolve('typescript', {
    paths: [path.resolve(__dirname, '..', 'webview')], // helpers/ depth removed: this file lives in extension/tests
  }));

  const WEBVIEW_ROOT = path.resolve(__dirname, '..', 'webview');

  function resolveRelative(fromDirectory, specifier) {
    const base = path.resolve(fromDirectory, specifier);
    const candidates = [
      `${base}.ts`,
      `${base}.tsx`,
      path.join(base, 'index.ts'),
      path.join(base, 'index.tsx'),
    ];
    const found = candidates.find((candidate) => fs.existsSync(candidate));
    if (!found) {
      throw new Error(`cannot resolve ${specifier} from ${fromDirectory}`);
    }
    return found;
  }

  function loadTsModule(entryPath, cache = new Map()) {
    const resolved = path.resolve(entryPath);
    const cached = cache.get(resolved);
    if (cached) {
      return cached.exports;
    }

    const source = fs.readFileSync(resolved, 'utf8');
    const output = typescript.transpileModule(source, {
      compilerOptions: {
        module: typescript.ModuleKind.CommonJS,
        target: typescript.ScriptTarget.ES2020,
        jsx: typescript.JsxEmit.ReactJSX,
      },
    }).outputText;

    const module = { exports: {} };
    cache.set(resolved, module);
    const localRequire = (specifier) => {
      if (specifier.startsWith('.')) {
        return loadTsModule(resolveRelative(path.dirname(resolved), specifier), cache);
      }
      return require(specifier);
    };

    vm.runInNewContext(
      output,
      { exports: module.exports, module, require: localRequire },
      { filename: resolved },
    );
    return module.exports;
  }

  return { loadTsModule, WEBVIEW_ROOT };
})();
const hostTextPath = require("node:path").resolve(
  __dirname,
  "..",
  "webview",
  "src",
  "lib",
  "hostText.ts",
);

/**
 * Host payloads cross a trust boundary. The view declares precise types, but a
 * field can carry a record, a number or a blank string at runtime — and the
 * learning path reads those fields the moment a practice settles.
 */
let modulePromise = null;
function loadHostText() {
  modulePromise ??= loadTsModule(hostTextPath);
  return modulePromise;
}

test("usable text survives normalization", async () => {
  const { normalizeHostText } = await loadHostText();
  assert.equal(normalizeHostText("  已验证:边界检查通过  "), "已验证:边界检查通过");
  assert.equal(normalizeHostText("tools"), "tools");
});

test("a value that is not text is dropped instead of reaching the view", async () => {
  const { normalizeHostText } = await loadHostText();
  assert.equal(normalizeHostText({ id: "malformed" }), undefined);
  assert.equal(normalizeHostText(42), undefined);
  assert.equal(normalizeHostText(true), undefined);
  assert.equal(normalizeHostText(["a"]), undefined);
  assert.equal(normalizeHostText(null), undefined);
  assert.equal(normalizeHostText(undefined), undefined);
  assert.equal(normalizeHostText("   "), undefined);
});

test("the training state's text fields are normalized and the rest is carried through", async () => {
  const { normalizeTrainingStateTextFields } = await loadHostText();
  const state = {
    workspaceId: "workspace-1",
    latestLearningVerifiedResult: { id: "malformed" },
    latestLearningBlocker: "  等教练确认  ",
    latestLearningPartialProgress: 7,
    selectedCardTitle: "Fixture 练习",
    selectedCardStatus: "active",
    trainingCardCandidates: [{ cardId: "card-1" }],
  };
  const normalized = normalizeTrainingStateTextFields(state);
  assert.equal(normalized.latestLearningVerifiedResult, undefined);
  assert.equal(normalized.latestLearningBlocker, "等教练确认");
  assert.equal(normalized.latestLearningPartialProgress, undefined);
  assert.equal(normalized.selectedCardTitle, "Fixture 练习");
  // Non-text fields are untouched.
  assert.equal(normalized.workspaceId, "workspace-1");
  assert.equal(normalized.selectedCardStatus, "active");
  assert.deepEqual(normalized.trainingCardCandidates, [{ cardId: "card-1" }]);
});

test("an absent training state stays absent", async () => {
  const { normalizeTrainingStateTextFields } = await loadHostText();
  assert.equal(normalizeTrainingStateTextFields(undefined), undefined);
});
