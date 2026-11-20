"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { loadTsModule } = require("./helpers/loadTsModule");

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
