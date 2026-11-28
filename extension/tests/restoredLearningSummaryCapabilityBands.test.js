// Restored behavioral regression test. Original file: extension/tests/learningSummaryCapabilityBands.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: undefined
//
// Restoration: partial - 4 of 5 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "every state the server projection emits has a band"
//       source-text guard: reads server/app/training/skill_projection.py and asserts on its text (out of
//       scope by rule).
// Target: webview TypeScript loaded through the inlined loadTsModule helper (in-memory transpile).
// Note: extension/tests/helpers/loadTsModule.js (deleted in df0a3e2a) is inlined above the tests: same in-memory TypeScript loader, logic unchanged.

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");

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
const learningSummaryPath = path.resolve(__dirname, "..", "webview", "src", "lib", "learningSummary.ts");
const skillProjectionPath = path.resolve(__dirname, "..", "..", "server", "app", "training", "skill_projection.py");

let modulePromise = null;
function loadLearningSummary() {
  modulePromise ??= loadTsModule(learningSummaryPath);
  return modulePromise;
}

/** The states the server projection can return, read from its source of truth. */
function serverProjectionStates() {
  const source = fs.readFileSync(skillProjectionPath, "utf8");
  const body = source.slice(source.indexOf("def _state_from_evidence("));
  const end = body.indexOf("\ndef ", 1);
  const fn = end === -1 ? body : body.slice(0, end);
  return [...new Set([...fn.matchAll(/return "([a-z_]+)"/g)].map((match) => match[1]))].sort();
}

function projectionWith(states) {
  const dimensions = {};
  for (const [key, state, verifiedCount] of states) {
    dimensions[key] = { state, verifiedCount };
  }
  return { dimensions };
}

test("the evidence ladder only climbs: not verified < assisted < independent < repeatedly verified", async () => {
  const { capabilityLevel, MAX_CAPABILITY_LEVEL } = await loadLearningSummary();
  const ladder = ["not_verified", "assisted", "independent", "repeat_verified"].map(capabilityLevel);
  for (let index = 1; index < ladder.length; index += 1) {
    assert.ok(ladder[index] > ladder[index - 1], `ladder must climb at step ${index}: ${ladder}`);
  }
  assert.equal(ladder.at(-1), MAX_CAPABILITY_LEVEL, "repeatedly verified fills the whole column");
});

test("a repeatedly verified dimension never draws as an empty column", async () => {
  const { deriveLearningSummary } = await loadLearningSummary();
  const summary = deriveLearningSummary({
    language: "zh-CN",
    dueCount: 0,
    projection: projectionWith([
      ["comprehension", "repeat_verified", 9],
      ["implementation", "assisted", 4],
      ["debugging", "independent", 6],
      ["transfer", "not_verified", 0],
    ]),
  });
  const byState = Object.fromEntries(summary.progressRows.map((row) => [row.stateKey, row]));
  assert.equal(byState.repeat_verified.level, 3);
  assert.equal(byState.repeat_verified.state, "稳定掌握");
  assert.equal(byState.repeat_verified.evidenceCount, 9);
  assert.equal(byState.independent.level, 2);
  assert.equal(byState.assisted.level, 1);
  assert.equal(byState.not_verified.level, 0);
  assert.equal(summary.evidenceCount, 19);
});

test("needs review claims no progress and says so in words", async () => {
  const { deriveLearningSummary } = await loadLearningSummary();
  const summary = deriveLearningSummary({
    language: "en-US",
    dueCount: 0,
    projection: projectionWith([["debugging", "needs_review", 1]]),
  });
  const row = summary.progressRows.find((candidate) => candidate.stateKey === "needs_review");
  assert.ok(row, "the needs-review dimension is listed");
  assert.equal(row.level, 0);
  assert.equal(row.state, "Needs review");
});

test("an unknown or legacy band key draws as nothing, never as progress", async () => {
  const { capabilityLevel } = await loadLearningSummary();
  assert.equal(capabilityLevel("emerging"), 0);
  assert.equal(capabilityLevel("mastered"), 0);
  assert.equal(capabilityLevel(""), 0);
  assert.equal(capabilityLevel("toString"), 0);
});
