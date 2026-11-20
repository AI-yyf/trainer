"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const {
  collectVsixSourceInputs,
  describeVsixFreshness,
  resolveVsixFreshness,
} = require("../../scripts/vsix-freshness.mjs");

/**
 * A packaged artifact that predates its sources verifies the wrong code, so
 * the GUI gate asks this module before it installs anything.
 */
function makeFixture() {
  const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-vsix-freshness-"));
  const write = (relative, content) => {
    const absolute = path.join(repoRoot, relative);
    fs.mkdirSync(path.dirname(absolute), { recursive: true });
    fs.writeFileSync(absolute, content, "utf8");
    return absolute;
  };
  write("extension/src/extension.ts", "export const extension = 1;\n");
  write("extension/package.json", "{}\n");
  write("extension/webview/src/App.tsx", "export const App = 1;\n");
  write("shared/src/models.ts", "export type Model = 1;\n");
  write("server/app/main.py", "app = 1\n");
  write("browser-extension/shared.js", "const shared = 1;\n");
  write("remote-extension/src/extension.ts", "export const remote = 1;\n");
  // Build outputs and dependency trees never ship as sources: their
  // timestamps must not make a fresh artifact look stale.
  write("extension/webview/dist/index.html", "<html></html>\n");
  write("extension/node_modules/dep/index.js", "module.exports = 1;\n");
  write("extension/webview/node_modules/dep/index.js", "module.exports = 1;\n");
  const vsixPath = path.join(repoRoot, "trainer-extension-test.vsix");
  fs.writeFileSync(vsixPath, "vsix", "utf8");
  return { repoRoot, vsixPath };
}

function age(file, secondsAgo) {
  const when = new Date(Date.now() - secondsAgo * 1000);
  fs.utimesSync(file, when, when);
}

test("a packaged artifact newer than every source is current", () => {
  const { repoRoot, vsixPath } = makeFixture();
  for (const input of collectVsixSourceInputs({ repoRoot })) {
    age(input.file, 120);
  }
  age(vsixPath, 10);
  const freshness = resolveVsixFreshness({ repoRoot, vsixPath });
  assert.equal(freshness.exists, true);
  assert.equal(freshness.stale, false);
  assert.equal(freshness.staleInputs.length, 0);
  assert.ok(freshness.inputCount > 0);
});

test("a source newer than the artifact is stale and is named", () => {
  const { repoRoot, vsixPath } = makeFixture();
  for (const input of collectVsixSourceInputs({ repoRoot })) {
    age(input.file, 600);
  }
  age(vsixPath, 300);
  const newer = path.join(repoRoot, "shared/src/models.ts");
  age(newer, 5);
  const freshness = resolveVsixFreshness({ repoRoot, vsixPath });
  assert.equal(freshness.stale, true);
  assert.equal(path.resolve(freshness.newestInput.file), path.resolve(newer));
  assert.ok(freshness.staleInputs.some((input) => path.resolve(input.file) === path.resolve(newer)));
  const report = describeVsixFreshness({ repoRoot, vsixPath });
  assert.match(report, /older than the sources it packages/);
  assert.match(report, /shared\/src\/models\.ts/);
  assert.match(report, /npm run package:vsix/);
});

test("a missing artifact is stale and the report names the packaging command", () => {
  const { repoRoot, vsixPath } = makeFixture();
  fs.rmSync(vsixPath);
  const freshness = resolveVsixFreshness({ repoRoot, vsixPath });
  assert.equal(freshness.exists, false);
  assert.equal(freshness.stale, true);
  assert.match(describeVsixFreshness({ repoRoot, vsixPath }), /missing/);
});

test("build outputs and dependency trees are never packaged sources", () => {
  const { repoRoot, vsixPath } = makeFixture();
  for (const input of collectVsixSourceInputs({ repoRoot })) {
    age(input.file, 120);
  }
  age(vsixPath, 10);
  // Only regenerated outputs moved past the artifact.
  for (const output of [
    path.join(repoRoot, "extension/webview/dist/index.html"),
    path.join(repoRoot, "extension/node_modules/dep/index.js"),
    path.join(repoRoot, "extension/webview/node_modules/dep/index.js"),
  ]) {
    age(output, 1);
  }
  const freshness = resolveVsixFreshness({ repoRoot, vsixPath });
  assert.equal(freshness.stale, false);
});

test("packaged sources cover the extension, webview, shared, server and browser trees", () => {
  const { repoRoot } = makeFixture();
  const files = collectVsixSourceInputs({ repoRoot }).map((input) =>
    path.relative(repoRoot, input.file).split(path.sep).join("/"));
  for (const expected of [
    "extension/src/extension.ts",
    "extension/package.json",
    "extension/webview/src/App.tsx",
    "shared/src/models.ts",
    "server/app/main.py",
    "browser-extension/shared.js",
    "remote-extension/src/extension.ts",
  ]) {
    assert.ok(files.includes(expected), `missing packaged source: ${expected}`);
  }
  assert.ok(!files.some((file) => file.includes("/node_modules/")));
  assert.ok(!files.some((file) => file.includes("/webview/dist/")));
});

/**
 * The gate entry point: a packaged artifact that no longer matches the
 * sources must stop the gate instead of letting it verify the wrong code.
 *
 * The module reaches `package-vsix.mjs`, which has a top-level await, so it
 * is loaded dynamically instead of through `require`.
 */
let ensureFreshVsixPromise = null;
function loadEnsureFreshVsix() {
  ensureFreshVsixPromise ??= import("../scripts/prepare-current-vsix.mjs")
    .then((loaded) => loaded.ensureFreshVsix);
  return ensureFreshVsixPromise;
}
function makeGateFixture() {
  const { repoRoot, vsixPath } = makeFixture();
  const extensionDir = path.join(repoRoot, "extension");
  fs.mkdirSync(extensionDir, { recursive: true });
  fs.writeFileSync(path.join(extensionDir, "package.json"), JSON.stringify({
    name: "trainer-extension", version: "9.9.9", publisher: "local",
  }), "utf8");
  return { repoRoot, extensionDir, vsixPath };
}

test("the gate entry point accepts an artifact that matches the sources", async () => {
  const ensureFreshVsix = await loadEnsureFreshVsix();
  const { repoRoot, extensionDir, vsixPath } = makeGateFixture();
  for (const input of collectVsixSourceInputs({ repoRoot })) {
    age(input.file, 600);
  }
  age(vsixPath, 10);
  const result = ensureFreshVsix({
    vsixPath,
    repoRoot,
    extensionDir,
    env: { TRAINER_SKIP_VSIX_REBUILD: "1" },
  });
  assert.equal(result.rebuilt, false);
  assert.equal(result.freshness.stale, false);
  assert.equal(path.resolve(result.vsixPath), path.resolve(vsixPath));
});

test("the gate entry point refuses an artifact that predates its sources", async () => {
  const ensureFreshVsix = await loadEnsureFreshVsix();
  const { repoRoot, extensionDir, vsixPath } = makeGateFixture();
  for (const input of collectVsixSourceInputs({ repoRoot })) {
    age(input.file, 600);
  }
  age(vsixPath, 300);
  const newer = path.join(repoRoot, "shared/src/models.ts");
  age(newer, 5);
  assert.throws(
    () => ensureFreshVsix({
      vsixPath,
      repoRoot,
      extensionDir,
      env: { TRAINER_SKIP_VSIX_REBUILD: "1" },
    }),
    (error) => {
      assert.match(error.message, /older than the sources it packages/);
      assert.match(error.message, /shared\/src\/models\.ts/);
      assert.match(error.message, /TRAINER_SKIP_VSIX_REBUILD=1/);
      return true;
    },
  );
});

test("the gate entry point refuses a missing artifact", async () => {
  const ensureFreshVsix = await loadEnsureFreshVsix();
  const { repoRoot, extensionDir, vsixPath } = makeGateFixture();
  fs.rmSync(vsixPath);
  assert.throws(
    () => ensureFreshVsix({
      vsixPath,
      repoRoot,
      extensionDir,
      env: { TRAINER_SKIP_VSIX_REBUILD: "1" },
    }),
    /missing/,
  );
});
