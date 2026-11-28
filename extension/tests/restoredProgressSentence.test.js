// Restored behavioral regression test. Original file: extension/tests/progressSentence.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Progress sentence composition for every projection state and all eight languages.
//
// Restoration: whole - all 6 original test definitions, code and assertions unchanged.
// Target: webview TypeScript loaded through the inlined loadTsModule helper (in-memory transpile).
// Note: extension/tests/helpers/loadTsModule.js (deleted in df0a3e2a) is inlined above the tests: same in-memory TypeScript loader, logic unchanged.

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

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

let modulePromise = null;
function loadSummary() {
  modulePromise ??= loadTsModule(learningSummaryPath);
  return modulePromise;
}

const ALL_LANGUAGES = ["zh-CN", "en-US", "es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR", "pt-BR"];

test("empty or all-unverified projections produce no progress sentence", async () => {
  const { deriveProgressSentence, deriveLearningSummary } = await loadSummary();
  assert.equal(deriveProgressSentence("zh-CN", undefined), undefined);
  assert.equal(
    deriveProgressSentence("en-US", {
      dimensions: {
        comprehension: { state: "not_verified", verifiedCount: 0 },
        implementation: { state: "not_verified", verifiedCount: 0 },
      },
    }),
    undefined,
  );
  const summary = deriveLearningSummary({ language: "zh-CN", dueCount: 0 });
  assert.equal(summary.latestAchievement, undefined);
});

test("all five projection states map honestly with traceable evidence ID and zero fake percentages", async () => {
  const { deriveProgressSentence } = await loadSummary();

  const cases = [
    ["repeat_verified", "ev-repeat", 3, /连续 3 次独立验证通过/],
    ["independent", "ev-indep", 1, /已独立完成/],
    ["assisted", "ev-assist", 1, /已在辅助下完成/],
    ["needs_review", "ev-review", 1, /掌握尚不稳固/],
  ];

  for (const [state, evidenceId, verifiedCount, pattern] of cases) {
    const result = deriveProgressSentence("zh-CN", {
      dimensions: {
        implementation: {
          state,
          verifiedCount,
          evidence: [{ evidenceId, scenario: "识别重复写入", timestamp: "2026-11-20T10:00:00Z" }],
        },
      },
    });
    assert.ok(result, `expected sentence for ${state}`);
    assert.match(result.sentence, pattern);
    assert.ok(result.sentence.includes("识别重复写入"));
    assert.doesNotMatch(result.sentence, /%|分/);
    assert.equal(result.evidenceId, evidenceId);
    assert.equal(result.stateKey, state);
  }
});

test("prefers newest timestamped evidence across verified dimensions", async () => {
  const { deriveLearningSummary } = await loadSummary();
  const summary = deriveLearningSummary({
    language: "zh-CN",
    dueCount: 0,
    projection: {
      dimensions: {
        comprehension: {
          state: "repeat_verified",
          verifiedCount: 4,
          evidence: [{ evidenceId: "ev-older", scenario: "旧主题", timestamp: "2026-11-18T10:00:00Z" }],
        },
        debugging: {
          state: "independent",
          verifiedCount: 1,
          evidence: [{ evidenceId: "ev-newer", scenario: "定位超时竞态", timestamp: "2026-11-20T12:00:00Z" }],
        },
      },
    },
  });
  assert.ok(summary.latestAchievement);
  assert.equal(summary.latestAchievement.evidenceId, "ev-newer");
  assert.equal(summary.latestAchievement.dimensionKey, "debugging");
  assert.ok(summary.latestAchievement.sentence.includes("定位超时竞态"));
});

test("malformed non-string evidence fields degrade safely without throwing", async () => {
  const { deriveProgressSentence } = await loadSummary();
  const result = deriveProgressSentence("en-US", {
    dimensions: {
      comprehension: {
        state: "independent",
        verifiedCount: 1,
        evidence: [{ evidenceId: 123, scenario: { bad: true }, timestamp: "not-a-date" }],
      },
    },
  });
  assert.ok(result);
  assert.equal(result.evidenceId, undefined);
  assert.match(result.sentence, /Independent proficiency verified/i);
});

test("all eight supported languages produce natural sentences for each active state", async () => {
  const { deriveProgressSentence } = await loadSummary();
  for (const language of ALL_LANGUAGES) {
    for (const state of ["assisted", "independent", "repeat_verified", "needs_review"]) {
      const result = deriveProgressSentence(language, {
        dimensions: {
          transfer: {
            state,
            verifiedCount: state === "repeat_verified" ? 2 : 1,
            evidence: [{ evidenceId: `ev-${language}`, scenario: "retry()", timestamp: "2026-11-20T08:00:00Z" }],
          },
        },
      });
      assert.ok(result && result.sentence.length > 0, `missing sentence for ${language}/${state}`);
      assert.ok(result.sentence.includes("retry()"));
      assert.doesNotMatch(result.sentence, /%/);
    }
  }
});

test("dimension overview avoids robotic 'completed Comprehension' phrasing when topic is absent", async () => {
  const { deriveProgressSentence } = await loadSummary();
  const zh = deriveProgressSentence("zh-CN", {
    dimensions: {
      comprehension: { state: "repeat_verified", verifiedCount: 9 },
      implementation: { state: "assisted", verifiedCount: 4 },
      debugging: { state: "independent", verifiedCount: 6 },
      transfer: { state: "not_verified", verifiedCount: 0 },
    },
  });
  assert.ok(zh);
  assert.doesNotMatch(zh.sentence, /独立完成「理解」/);
  assert.match(zh.sentence, /理解、调试已达独立完成标准/);
  assert.match(zh.sentence, /实现仍需辅助/);
  assert.match(zh.sentence, /迁移尚未验证/);
});
