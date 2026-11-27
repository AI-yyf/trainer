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

function createMockWindow(postedMessages = []) {
  const storage = new Map();
  return {
    localStorage: {
      getItem: (key) => (storage.has(key) ? storage.get(key) : null),
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: (key) => storage.delete(key),
    },
    location: { search: "", href: "vscode-webview://test" },
    matchMedia: () => ({
      matches: false,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }),
    acquireVsCodeApi: () => ({
      postMessage: (msg) => postedMessages.push(msg),
      getState: () => undefined,
      setState: () => undefined,
    }),
  };
}

async function loadWebviewModule(entryRelativePath) {
  const entryPath = path.join(webviewRoot, entryRelativePath);
  const bundled = await esbuild.build({
    entryPoints: [entryPath],
    bundle: true,
    platform: "node",
    format: "cjs",
    write: false,
    logLevel: "silent",
    tsconfig: path.join(webviewRoot, "tsconfig.json"),
    loader: {
      ".svg": "text",
      ".png": "text",
    },
    plugins: [
      {
        name: "stub-vite-asset-urls",
        setup(build) {
          build.onResolve({ filter: /\?(url|raw)$/ }, (args) => ({
            path: args.path,
            namespace: "vite-asset-stub",
          }));
          build.onLoad({ filter: /.*/, namespace: "vite-asset-stub" }, () => ({
            contents: 'module.exports = "stub-asset-url";',
            loader: "js",
          }));
        },
      },
    ],
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

test("buildProviderSettingsActions dispatches host commands cleanly without baselineMessageKey churn", async () => {
  const postedMessages = [];
  const originalWindow = global.window;
  global.window = createMockWindow(postedMessages);

  try {
    const { buildProviderSettingsActions } = await loadWebviewModule(
      "src/app/providerSettingsActions.ts",
    );
    const actionStates = [];
    const persistedCalls = [];
    const defaultCoachDefaults = {
      memoryScope: "project",
      workingSetMode: "balanced",
      reviewCadence: "steady",
      reviewReminderMode: "due",
      workspaceMemoryToggles: {
        decisions: true,
        patterns: true,
        resources: true,
      },
    };

    const actions = buildProviderSettingsActions({
      language: "zh-CN",
      isBrowserPreview: false,
      previewSessionId: undefined,
      providerSavePayload: {
        name: "OpenAI",
        protocol: "openai-responses",
        baseUrl: "https://api.openai.com/v1",
        model: "gpt-5",
      },
      providerDraftHasChanges: true,
      providerConfigured: true,
      setSettingsActionState: (next) => actionStates.push(next),
      setPreviewSessionId: () => undefined,
      applyPreviewHostMessages: () => undefined,
      persistCoachSettings: (overrides) => persistedCalls.push(overrides),
      defaultCoachDefaults,
    });

    actions.onTestProvider();
    assert.equal(actionStates.length, 1);
    assert.equal(actionStates[0].kind, "test-provider");
    assert.deepEqual(actionStates[0].targets, ["provider"]);
    assert.equal("baselineMessageKey" in actionStates[0], false);
    assert.match(actionStates[0].requestId, /^provider-test-/);

    const lastMessage = postedMessages.at(-1);
    assert.equal(lastMessage.type, "command/execute");
    assert.equal(lastMessage.payload.commandId, "trainer.provider.test");
    assert.equal(lastMessage.payload.payload.requestId, actionStates[0].requestId);
    assert.equal(lastMessage.payload.payload.draft.model, "gpt-5");

    actions.onResetDefaults();
    assert.equal(actionStates.at(-1).kind, "reset-defaults");
    assert.equal(persistedCalls.length, 1);
    assert.deepEqual(persistedCalls[0].coachDefaults, defaultCoachDefaults);
  } finally {
    global.window = originalWindow;
  }
});

test("extracted workspace admission and coach settings controllers bundle cleanly with expected exports", async () => {
  const originalWindow = global.window;
  global.window = createMockWindow();
  try {
    const coachSettingsMod = await loadWebviewModule(
      "src/app/useCoachSettingsController.ts",
    );
    assert.equal(typeof coachSettingsMod.useCoachSettingsState, "function");
    assert.equal(typeof coachSettingsMod.useProviderReadinessState, "function");
    assert.equal(typeof coachSettingsMod.useCoachSettingsController, "function");

    const workspaceAdmissionMod = await loadWebviewModule(
      "src/app/useWorkspaceAdmissionController.tsx",
    );
    assert.equal(
      typeof workspaceAdmissionMod.useWorkspaceAdmissionState,
      "function",
    );
    assert.equal(
      typeof workspaceAdmissionMod.useWorkspaceAdmissionFlow,
      "function",
    );
  } finally {
    global.window = originalWindow;
  }
});

test("App.tsx delegates workspace admission & coach settings controllers and drops dead skill-authoring state", () => {
  const appPath = path.join(webviewRoot, "src/app/App.tsx");
  const source = fs.readFileSync(appPath, "utf8");
  const lineCount = source.split("\n").length;

  assert.ok(
    lineCount < 9600,
    `Expected App.tsx to shrink below 9,600 lines in Round 2 Slice A, got ${lineCount}`,
  );

  for (const hookName of [
    "useCoachSettingsState(",
    "useProviderReadinessState(",
    "useCoachSettingsController(",
    "useWorkspaceAdmissionState(",
    "useWorkspaceAdmissionFlow(",
  ]) {
    assert.ok(
      source.includes(hookName),
      `Expected App.tsx to invoke extracted hook ${hookName}`,
    );
  }

  for (const deadSymbol of [
    "pendingDeleteSkillId",
    "skillDraftFields",
    "saveCustomSkillDraft",
    "removeCustomSkill",
    "onGenerateSkillDraft",
    "baselineConnectedMessage",
  ]) {
    assert.equal(
      source.includes(deadSymbol),
      false,
      `Expected dead symbol ${deadSymbol} to be removed from App.tsx`,
    );
  }

  // Verify all 5 templateAssertions.js contracts remain preserved in App.tsx.
  assert.match(source, /activityDrafts\?\.\[activityDraftKey\]/);
  assert.match(source, /<CoachComposer[\s\S]*?composerUsesTrainingFlow \? activityDraft : draft/);
  assert.match(source, /triggerToken === "\$" \? 6 : 10/);
  assert.match(source, /skillSharing:\s*renderSkillSharing\(\),/);
  assert.match(source, /setActiveView\("settings"\)/);
});
