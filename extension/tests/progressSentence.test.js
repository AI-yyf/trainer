"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { loadTsModule } = require("./helpers/loadTsModule");

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
    ["repeat_verified", "ev-repeat", 3, /3 次独立完成/],
    ["independent", "ev-indep", 1, /独立完成/],
    ["assisted", "ev-assist", 1, /提示下完成/],
    ["needs_review", "ev-review", 1, /还需要一次回顾/],
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
  assert.match(result.sentence, /independently completed/i);
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
