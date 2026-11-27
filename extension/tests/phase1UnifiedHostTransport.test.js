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

test("HostTransport resolves VS Code, Browser Side Panel, and DOM preview hosts cleanly", async () => {
  const originalWindow = global.window;
  try {
    global.window = {
      __TRAINER_SURFACE__: "sidebar",
      localStorage: {
        getItem: () => null,
        setItem: () => undefined,
      },
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => true,
    };

    const hostMod = await loadWebviewModule("src/lib/hostTransport.ts");
    const vscodeMod = await loadWebviewModule("src/lib/vscode.ts");

    hostMod.resetWorkbenchHostTransportForTests();
    assert.equal(hostMod.resolveWorkbenchHostTransport().id, "dom-preview");
    assert.equal(hostMod.resolveWorkbenchHostTransport().isNativeHost, false);
    assert.equal(hostMod.isBrowserSidePanelSurface(), false);

    const posted = [];
    vscodeMod.registerWorkbenchHostTransport({
      id: "chrome-sidepanel",
      surface: "browser-sidepanel",
      isNativeHost: true,
      getState: () => undefined,
      setState: () => undefined,
      postMessage: (msg) => posted.push(msg),
      subscribe: () => () => undefined,
    });

    assert.equal(vscodeMod.resolveWorkbenchHostTransport().id, "chrome-sidepanel");
    assert.equal(vscodeMod.inVsCodeWebview(), true);
    assert.equal(vscodeMod.isBrowserSidePanelSurface(), true);
    vscodeMod.announceReady();
    assert.equal(posted.length, 1);
    assert.equal(posted[0].type, "webview/ready");
    hostMod.resetWorkbenchHostTransportForTests();
  } finally {
    global.window = originalWindow;
  }
});

test("mapSidecarSnapshotToBootstrapData maps workspace provider readiness and active tab metadata cleanly", async () => {
  const { mapSidecarSnapshotToBootstrapData } = await loadWebviewModule(
    "src/lib/sidecarSnapshotMapper.ts",
  );

  const mapped = mapSidecarSnapshotToBootstrapData(
    {
      session_id: "sess-1",
      workspace_id: "ws-alpha",
      workspace_name: "Alpha Project",
      messages: [
        { id: "m1", role: "user", body: "问题一" },
        { id: "m2", role: "assistant", body: "回答一" },
      ],
      workspace_provider: {
        configured: true,
        name: "OpenAI",
        model: "gpt-5",
        protocol: "openai-responses",
        api_key_configured: true,
        capabilities: { chat: true, streaming: true, tools: true },
      },
    },
    {
      workspaceId: "ws-alpha",
      workspaceName: "Alpha Project",
      paired: true,
      activeTab: {
        url: "https://docs.python.org/3/tutorial/index.html",
        title: "Python Tutorial",
        selection: "list comprehensions",
      },
    },
  );

  assert.equal(mapped.providerConfig.configured, true);
  assert.equal(mapped.providerConfig.model, "gpt-5");
  assert.equal(mapped.providerConfig.capabilities.tools, true);
  assert.equal(mapped.memory.workspace.trainerWorkspace.status, "managed");
  assert.equal(mapped.memory.workspace.windowTrusted, true);
  assert.match(mapped.liveContext.activeFile, /Python Tutorial/);
  assert.equal(mapped.liveContext.selectionPreview, "list comprehensions");
  assert.equal(mapped.conversation.length, 2);
});

test("chromeSidePanelTransport bundles cleanly and exports install + factory entrypoints", async () => {
  const sidePanelMod = await loadWebviewModule(
    "src/lib/chromeSidePanelTransport.ts",
  );
  assert.equal(typeof sidePanelMod.createChromeSidePanelTransport, "function");
  assert.equal(typeof sidePanelMod.installChromeSidePanelTransport, "function");

  const appSource = fs.readFileSync(
    path.join(webviewRoot, "src/app/App.tsx"),
    "utf8",
  );
  assert.ok(appSource.includes("isBrowserSidePanelSurface()"));
});
