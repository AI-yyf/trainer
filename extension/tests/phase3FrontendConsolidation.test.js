"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const esbuild = require(
  fs.existsSync(path.resolve(__dirname, "../webview/node_modules/esbuild"))
    ? path.resolve(__dirname, "../webview/node_modules/esbuild")
    : "esbuild",
);

const repoRoot = path.resolve(__dirname, "../..");
const webviewRoot = path.join(repoRoot, "extension/webview");
const webviewSrcRoot = path.join(webviewRoot, "src");
const browserPkgDirName = ["browser", "extension"].join("-");

function collectSourceFiles(dir) {
  const results = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...collectSourceFiles(fullPath));
    } else if (/\.(ts|tsx)$/.test(entry.name)) {
      results.push(fullPath);
    }
  }
  return results;
}

async function loadWebviewTsModule(entryRelativePath) {
  const entryPath = path.join(webviewRoot, entryRelativePath);
  const bundled = await esbuild.build({
    entryPoints: [entryPath],
    bundle: true,
    platform: "node",
    format: "cjs",
    write: false,
    logLevel: "silent",
    tsconfig: path.join(webviewRoot, "tsconfig.json"),
  });
  const code = bundled.outputFiles[0].text;
  const mod = { exports: {} };
  const fn = new Function(
    "require",
    "module",
    "exports",
    "__filename",
    "__dirname",
    code,
  );
  fn(require, mod, mod.exports, entryPath, path.dirname(entryPath));
  return mod.exports;
}

test("Production controllers, components, and shared bootstrap contain zero browserSidecar references", () => {
  const productionRoots = [
    path.join(webviewSrcRoot, "app"),
    path.join(webviewSrcRoot, "components"),
  ];
  const standaloneProductionFiles = [
    path.join(webviewSrcRoot, "bootstrapWorkbench.tsx"),
    path.join(webviewSrcRoot, "main.tsx"),
    path.join(webviewSrcRoot, "sidepanel-main.tsx"),
    path.join(webviewSrcRoot, "lib/browserPreviewAdapter.ts"),
  ];

  const filesToCheck = [
    ...productionRoots.flatMap((dir) => collectSourceFiles(dir)),
    ...standaloneProductionFiles,
  ];

  assert.ok(filesToCheck.length > 20, "Expected production source files to be scanned");
  for (const filePath of filesToCheck) {
    const rel = path.relative(webviewSrcRoot, filePath);
    const content = fs.readFileSync(filePath, "utf8");
    assert.equal(
      content.includes("browserSidecar"),
      false,
      `Production file ${rel} must not reference browserSidecar`,
    );
    assert.equal(
      content.includes("loadBrowserPreviewModule"),
      false,
      `Production file ${rel} must not use legacy loadBrowserPreviewModule`,
    );
  }
});

test("Compiled production webview & Side Panel runtime chunks exclude browserSidecar references and VSIX blocks dev chunks", async () => {
  const sidepanelAssetsDir = path.join(repoRoot, browserPkgDirName, "sidepanel", "assets");
  assert.ok(fs.existsSync(sidepanelAssetsDir), "Expected synced sidepanel assets directory");
  const sidepanelJsFiles = fs
    .readdirSync(sidepanelAssetsDir)
    .filter((name) => name.endsWith(".js"));
  assert.ok(sidepanelJsFiles.length >= 3, "Expected compiled sidepanel JS assets");

  for (const name of sidepanelJsFiles) {
    const js = fs.readFileSync(path.join(sidepanelAssetsDir, name), "utf8");
    assert.equal(
      js.includes("browserSidecar"),
      false,
      `Side Panel chunk ${name} must not reference browserSidecar`,
    );
    assert.equal(
      js.includes("browserPreviewHarness"),
      false,
      `Side Panel chunk ${name} must not reference browserPreviewHarness`,
    );
  }

  const distAssetsDir = path.join(webviewRoot, "dist", "assets");
  assert.ok(fs.existsSync(distAssetsDir), "Expected built webview dist/assets directory");
  const appChunks = fs
    .readdirSync(distAssetsDir)
    .filter((name) => /^(App|bootstrapWorkbench|sidepanel)-.*\.js$/.test(name));
  assert.ok(appChunks.length >= 2, "Expected built App/bootstrap chunks in dist/assets");
  for (const name of appChunks) {
    const js = fs.readFileSync(path.join(distAssetsDir, name), "utf8");
    assert.equal(
      js.includes("browserSidecar"),
      false,
      `Production dist chunk ${name} must not reference browserSidecar`,
    );
  }

  const { findDevelopmentOnlyVsixEntries } = await import(
    path.join(repoRoot, "extension/scripts/package-vsix.mjs")
  );
  const detected = findDevelopmentOnlyVsixEntries([
    "extension/webview/dist/index.html",
    "extension/webview/dist/assets/App-abc123.js",
    "extension/webview/dist/vscode-preview.html",
    "extension/webview/dist/browserSidecar-test.js",
    "extension/webview/dist/assets/browserSidecar-xyz987.js",
    "extension/webview/dist/assets/browserPreviewHarness-def456.js",
  ]);
  assert.deepEqual(detected, [
    "extension/webview/dist/assets/browserPreviewHarness-def456.js",
    "extension/webview/dist/assets/browserSidecar-xyz987.js",
    "extension/webview/dist/browserSidecar-test.js",
    "extension/webview/dist/vscode-preview.html",
  ]);
});

test("browserPreviewAdapter fails closed when unregistered and resolves registered preview adapter", async () => {
  const adapterMod = await loadWebviewTsModule("src/lib/browserPreviewAdapter.ts");
  adapterMod.registerBrowserPreviewAdapter(undefined);
  assert.equal(adapterMod.getBrowserPreviewAdapter(), undefined);

  await assert.rejects(
    () => adapterMod.requireBrowserPreviewAdapter(),
    /Browser preview adapter is not installed/,
  );

  const stubAdapter = {
    browserUploadLimit: () => 42,
  };
  adapterMod.registerBrowserPreviewAdapter(stubAdapter);
  assert.equal(adapterMod.getBrowserPreviewAdapter(), stubAdapter);
  const resolved = await adapterMod.requireBrowserPreviewAdapter();
  assert.equal(resolved.browserUploadLimit(), 42);
  adapterMod.registerBrowserPreviewAdapter(undefined);
});

test("App.tsx (< 3,000 lines) and CoachSettingsView.tsx (< 2,500 lines) converge cleanly into cohesive modules", () => {
  const appSource = fs.readFileSync(path.join(webviewSrcRoot, "app/App.tsx"), "utf8");
  const appLines = appSource.split("\n").length;
  assert.ok(
    appLines < 3000,
    `Expected App.tsx to shrink below 3,000 lines in Phase 3, got ${appLines}`,
  );
  for (const requiredModule of [
    "useWorkbenchHostMessageHandler(",
    "useWorkbenchLifecycleEffects(",
    "useWorkbenchRuntimeDerivedState(",
    "useTrainingWorkbenchDerivedState(",
    "useWorkbenchTurnSenderAndHistory(",
    "useTrainingAttemptAndComposerModes(",
    "useWorkbenchSurfaceRenderers(",
    "createWorkbenchSubmitHandler(",
  ]) {
    assert.ok(
      appSource.includes(requiredModule),
      `Expected App.tsx to delegate to ${requiredModule}`,
    );
  }

  const settingsSource = fs.readFileSync(
    path.join(webviewSrcRoot, "components/settings/CoachSettingsView.tsx"),
    "utf8",
  );
  const settingsLines = settingsSource.split("\n").length;
  assert.ok(
    settingsLines < 2500,
    `Expected CoachSettingsView.tsx to shrink below 2,500 lines in Phase 3, got ${settingsLines}`,
  );
  for (const anchor of [
    'data-settings-section="connection"',
    'data-settings-section="workspace"',
    'data-settings-section="teaching"',
    'data-settings-section="preferences"',
    'data-settings-section="skills"',
    'data-settings-section="advanced"',
    "useCoachSettingsSheetController(",
    "<ConnectionSettingsSectionBody",
    "<WorkspaceSettingsSection",
    "<TeachingSettingsSection",
    "<PreferencesSettingsSection",
    "<SkillsSettingsSection",
    "<AdvancedSettingsSection",
  ]) {
    assert.ok(
      settingsSource.includes(anchor),
      `Expected CoachSettingsView.tsx to preserve ${anchor}`,
    );
  }
});
