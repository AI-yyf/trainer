#!/usr/bin/env node
/**
 * Real VS Code GUI journey for the Coach status line (isolated profile).
 *
 * Installs the packaged VSIX, points it at a delayed local fixture provider
 * (loopback, test-only), sends a message, and captures the moment where the
 * user message and the single current-stage line are visible. Then it verifies
 * the reply, starts a new chat, and immediately sends the first message to
 * prove it is not dropped.
 *
 * Evidence: output/coach-gui/<stamp>/{report.json,*.png}
 */
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import { StringDecoder } from "node:string_decoder";
import { fileURLToPath } from "node:url";
import { _electron, chromium } from "playwright";
import { requireVSCodeElectronBinary } from "./vscode-electron.mjs";
import { buildVsixE2EProviderSavePayloadTemplate } from "../extension/scripts/vsix-e2e-provider-config.mjs";
import {
  resolveVsixE2EProviderRuntime,
  withVsixE2EFixtureLoopbackBypass,
} from "../extension/scripts/vsix-e2e-provider-runtime.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const extensionDir = path.join(repoRoot, "extension");
const packageJson = JSON.parse(fs.readFileSync(path.join(extensionDir, "package.json"), "utf8"));
const extensionId = `${packageJson.publisher}.${packageJson.name}`;
const vsixPath = process.env.TRAINER_VSIX_OUTPUT_PATH || path.join(extensionDir, `trainer-extension-${packageJson.version}-darwin-arm64.vsix`);
const codeCli = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code";
const electronBinary = requireVSCodeElectronBinary();
if (!fs.existsSync(vsixPath)) {
  throw new Error(`Packaged VSIX not found: ${vsixPath}. Run npm run package:vsix first.`);
}

const paperJourney = process.argv.includes("--paper");
const goalJourney = process.argv.includes("--goal");
const compoundPractice = process.argv.includes("--compound-practice");
const linkFromBrowserDraft = process.argv.includes("--link-from-browser-draft");
const unified = paperJourney || process.argv.includes("--unified");
const checkpointPath = process.argv.find((option) => option.startsWith("--resume-paper-from="))
  ?.slice("--resume-paper-from=".length);
const checkpoint = checkpointPath ? JSON.parse(fs.readFileSync(checkpointPath, "utf8")) : undefined;
const linkedCheckpoint = checkpoint?.results?.find((step) => step.step === "unified-resource-linked" && step.ok);
if (linkFromBrowserDraft && (!unified || !compoundPractice || checkpoint)) {
  throw new Error("Use --link-from-browser-draft with a fresh --unified or --paper --compound-practice run.");
}
if (checkpoint && (!paperJourney || checkpoint.providerSource !== "external" ||
    !/^\/tmp\/trainer-gui-[0-9A-Za-z]+\/user-data$/.test(checkpoint.isolatedProfile?.userDataDir ?? "") ||
    !checkpoint.results?.some((step) => step.step === "browser-selection" && step.ok) ||
    checkpoint.results?.some((step) => step.step === "unified-practice" && step.ok))) {
  throw new Error("Use a real paper journey report that reached browser selection or resource linking.");
}
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join(repoRoot, "output", "coach-gui", stamp);
const root = checkpoint
  ? path.dirname(checkpoint.isolatedProfile.userDataDir)
  : fs.mkdtempSync("/tmp/trainer-gui-");
const userDataDir = path.join(root, "user-data");
const extensionsDir = path.join(root, "extensions");
const workspaceDir = path.join(root, "workspace");
const trainerWorkspaceDir = path.join(root, "trainer-workspace");
const driverDir = path.join(root, "driver");
const reportPath = path.join(root, "report.json");
for (const dir of [
  path.join(userDataDir, "User"),
  extensionsDir,
  workspaceDir,
  trainerWorkspaceDir,
  driverDir,
  outDir,
]) {
  fs.mkdirSync(dir, { recursive: true });
}

if (!checkpoint) fs.writeFileSync(
  path.join(userDataDir, "User", "settings.json"),
  `${JSON.stringify(
    {
      "security.workspace.trust.enabled": false,
      "telemetry.telemetryLevel": "off",
      "update.mode": "none",
      "extensions.autoCheckUpdates": false,
      "extensions.autoUpdate": false,
      "workbench.startupEditor": "none",
      "workbench.colorTheme": "Default Dark Modern",
      "chat.disableAIFeatures": true,
      ...(unified ? { "python.defaultInterpreterPath": path.join(repoRoot, "server", ".venv", "bin", "python") } : {}),
    },
    null,
    2,
  )}\n`,
);

function provisionTrainerWorkspace() {
  const directories = [
    "Projects",
    "Knowledge",
    "Skills",
    "Agents",
    "Assets",
    ".trainer",
    path.join(".trainer", "memory"),
    path.join(".trainer", "plans"),
    path.join(".trainer", "indexes"),
    path.join(".trainer", "checkpoints"),
    path.join(".trainer", "logs"),
    path.join(".trainer", "cache"),
  ];
  for (const directory of directories) {
    fs.mkdirSync(path.join(trainerWorkspaceDir, directory), { recursive: true });
  }
  const now = new Date().toISOString();
  fs.writeFileSync(
    path.join(trainerWorkspaceDir, ".trainer", "workspace.json"),
    `${JSON.stringify(
      {
        schemaVersion: 2,
        kind: "trainer-workspace",
        rootPath: trainerWorkspaceDir,
        canonicalRootPath: trainerWorkspaceDir,
        legacyRootPaths: [],
        manifestRevision: 1,
        pathRevision: 0,
        identityStatus: "pending",
        createdAt: now,
        updatedAt: now,
        directories,
        projects: {},
      },
      null,
      2,
    )}\n`,
  );
}
if (!checkpoint) provisionTrainerWorkspace();
const paperUrl = "https://arxiv.org/html/2407.17032v3";
const boundaryFile = path.join(workspaceDir, paperJourney ? "episode-bootstrap.py" : "unified-boundary.py");
const exercise = paperJourney ? {
  initial: "def should_bootstrap(terminated, truncated):\n    return not (terminated or truncated)\n",
  solved: "def should_bootstrap(terminated, truncated):\n    return not terminated\n",
  check: [
    "def test_episode_bootstrapping():",
    '    applies = run_path(str(Path(__file__).with_name("episode-bootstrap.py")))["should_bootstrap"]',
    "    assert applies(False, False)",
    "    assert applies(False, True)",
    "    assert not applies(True, False)",
    "    assert not applies(True, True)",
  ],
} : {
  initial: "def applies_to_workspace(workspace_id, returned_workspace_id):\n    return False\n",
  solved: "def applies_to_workspace(workspace_id, returned_workspace_id):\n    return workspace_id == returned_workspace_id\n",
  check: [
    "def test_workspace_boundary():",
    '    applies = run_path(str(Path(__file__).with_name("unified-boundary.py")))["applies_to_workspace"]',
    '    assert applies("original", "original")',
    '    assert not applies("original", "different")',
  ],
};
if (unified && !checkpoint) {
  fs.writeFileSync(boundaryFile, exercise.initial);
  fs.writeFileSync(path.join(workspaceDir, "test_unified_boundary.py"), [
    "from pathlib import Path",
    "from runpy import run_path",
    "",
    "",
    ...exercise.check,
    "",
  ].join("\n"));
}
if (unified && linkedCheckpoint) fs.writeFileSync(boundaryFile, exercise.initial);

function readMemento(value) {
  if (value === undefined || value === null) return undefined;
  try {
    return JSON.parse(typeof value === "string" ? value : Buffer.from(value).toString("utf8"));
  } catch {
    return undefined;
  }
}
function seedTrainerWorkspaceRoot() {
  const globalStorageDir = path.join(userDataDir, "User", "globalStorage");
  fs.mkdirSync(globalStorageDir, { recursive: true });
  const database = new DatabaseSync(path.join(globalStorageDir, "state.vscdb"));
  try {
    database.exec(
      "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)",
    );
    const existing = readMemento(
      database.prepare("SELECT value FROM ItemTable WHERE key = ?").get(extensionId)?.value,
    );
    const extensionState = existing && typeof existing === "object" ? existing : {};
    extensionState["trainer.workspace.root.v1"] = trainerWorkspaceDir;
    database
      .prepare("INSERT INTO ItemTable (key, value) VALUES (?, ?)")
      .run(extensionId, JSON.stringify(extensionState));
    const keyIndex = `extensionKeys/${extensionId}@${packageJson.version}`;
    const existingKeys = readMemento(
      database.prepare("SELECT value FROM ItemTable WHERE key = ?").get(keyIndex)?.value,
    );
    const mementoKeys = Array.isArray(existingKeys) ? existingKeys : [];
    if (!mementoKeys.includes("trainer.workspace.root.v1")) {
      mementoKeys.push("trainer.workspace.root.v1");
    }
    database
      .prepare("INSERT INTO ItemTable (key, value) VALUES (?, ?)")
      .run(keyIndex, JSON.stringify(mementoKeys));
  } finally {
    database.close();
  }
}
if (!checkpoint) seedTrainerWorkspaceRoot();

const modelCalls = [...(checkpoint?.modelCalls ?? [])];

function modelResponseObserver(modelCall) {
  const decoder = new StringDecoder("utf8");
  const tools = new Set();
  const finishReasons = new Set();
  let pending = "";
  let cardText = "";
  function observe(event) {
    try {
      const choice = JSON.parse(event).choices?.[0];
      const response = choice?.delta ?? choice?.message;
      if (modelCall.card && typeof response?.content === "string" && cardText.length < 30_000) {
        cardText += response.content;
      }
      if (choice?.finish_reason) finishReasons.add(choice.finish_reason);
      for (const tool of (choice?.delta ?? choice?.message)?.tool_calls ?? []) {
        if (tool.function?.name) tools.add(tool.function.name);
      }
    } catch {
      // Ignore upstream error bodies and non-JSON stream frames.
    }
  }
  return new Transform({
    transform(chunk, _encoding, callback) {
      pending += decoder.write(chunk);
      if (modelCall.stream) {
        const lines = pending.split("\n");
        pending = lines.pop();
        for (const line of lines) {
          if (line.startsWith("data: {")) observe(line.slice(6));
        }
      }
      if (pending.length > 256_000) pending = pending.slice(-256_000);
      callback(null, chunk);
    },
    flush(callback) {
      pending += decoder.end();
      if (!modelCall.stream) observe(pending);
      else if (pending.startsWith("data: {")) observe(pending.slice(6));
      modelCall.tools = [...tools];
      modelCall.finishReasons = [...finishReasons];
      if (cardText.includes("{") && cardText.includes("}")) {
        try {
          const card = JSON.parse(cardText.slice(cardText.indexOf("{"), cardText.lastIndexOf("}") + 1));
          modelCall.cardFields = Object.fromEntries(Object.entries(card)
            .map(([key, value]) => [key, Array.isArray(value) ? value.map((item) => typeof item) : typeof value]));
          modelCall.cardFieldsWithoutChinese = Object.entries(card).filter(([, value]) =>
            (Array.isArray(value) ? value : [value]).some((text) => typeof text === "string" && !/[\u3400-\u9fff]/u.test(text)))
            .map(([key]) => key);
        } catch {
          modelCall.cardFields = "invalid_json";
        }
      }
      if (paperJourney) console.error("Model response", JSON.stringify(modelCall));
      callback();
    },
  });
}

// Allow time to inspect the in-flight UI while preserving upstream streaming.
function startDelayedProxy(targetBaseUrl, delayMs) {
  const server = http.createServer(async (request, response) => {
    try {
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      const body = Buffer.concat(chunks);
      const target = new URL(request.url ?? "/", targetBaseUrl);
      const headers = { ...request.headers, host: target.host };
      const upstream = await fetch(target, {
        method: request.method,
        headers,
        body: body.length ? body : undefined,
      });
      const framing = new Set(["connection", "content-encoding", "content-length", "transfer-encoding"]);
      let modelCall;
      if (target.pathname.endsWith("/chat/completions")) {
        const sent = JSON.parse(body.toString("utf8"));
        modelCall = {
          model: sent.model, status: upstream.status, stream: sent.stream === true,
          ...(sent.messages?.some((entry) => typeof entry.content === "string" &&
            entry.content.includes("You are generating one learn-first grounded training card")) ? { card: true } : {}),
        };
        modelCalls.push(modelCall);
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
      response.writeHead(upstream.status, Object.fromEntries(
        [...upstream.headers.entries()].filter(([name]) => !framing.has(name)),
      ));
      if (upstream.body) {
        const stream = Readable.fromWeb(upstream.body);
        if (modelCall) await pipeline(stream, modelResponseObserver(modelCall), response);
        else await pipeline(stream, response);
      } else response.end();
    } catch {
      if (!response.headersSent) response.writeHead(502);
      response.end();
    }
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      resolve({
        baseUrl: `http://127.0.0.1:${address.port}/v1`,
        stop: () => new Promise((done) => server.close(() => done())),
      });
    });
  });
}

function writeDriverExtension() {
  fs.writeFileSync(
    path.join(driverDir, "package.json"),
    `${JSON.stringify(
      {
        name: "trainer-coach-gui-driver",
        displayName: "Trainer Coach GUI Driver",
        version: "0.0.0",
        publisher: "local",
        engines: { vscode: "^1.96.0" },
        activationEvents: ["onStartupFinished"],
        main: "./extension.js",
      },
      null,
      2,
    )}\n`,
  );
  fs.writeFileSync(
    path.join(driverDir, "extension.js"),
    String.raw`
const fs = require("node:fs");
const vscode = require("vscode");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function activate() {
  const reportPath = process.env.COACH_GUI_REPORT;
  const targetId = process.env.COACH_GUI_TARGET_EXTENSION_ID;
  const provider = JSON.parse(process.env.COACH_GUI_PROVIDER || "{}");
  const report = { ok: false, steps: [] };
  try {
    const target = vscode.extensions.getExtension(targetId);
    if (!target) throw new Error("Trainer extension not installed: " + targetId);
    await target.activate();
    await sleep(12000);
    if (process.env.TRAINER_GUI_RESUME === "1") {
      report.ok = true;
      if (reportPath) fs.writeFileSync(reportPath, JSON.stringify(report));
      return;
    }
    if (process.env.TRAINER_GUI_CONTINUE !== "1") {
      const admitted = await vscode.commands.executeCommand("trainer.workspace.adoptProject", {
        projectPath: process.env.COACH_GUI_PROJECT_PATH || undefined,
      });
      report.steps.push({ step: "admit-project", ok: Boolean(admitted && admitted.ok), message: admitted && admitted.message });
    }
    await sleep(1500);
    const saved = await vscode.commands.executeCommand("trainer.provider.save", {
      ...provider.payload,
      baseUrl: provider.baseUrl,
      model: provider.model,
      apiKey: provider.apiKey,
      replaceApiKey: true,
    });
    report.steps.push({ step: "save-provider", ok: Boolean(saved && saved.ok), message: saved && saved.message });
    if (process.env.TRAINER_GUI_ACTIVE_FILE) {
      const tested = await vscode.commands.executeCommand("trainer.provider.test");
      report.steps.push({ step: "test-provider", ok: Boolean(tested && tested.ok) });
    }
    await sleep(1000);
    const settings = await vscode.commands.executeCommand("trainer.memory.saveCoachSettings", {
      responseLanguage: "zh-CN",
      answerMode: "coach-first",
    });
    report.steps.push({ step: "coach-settings", ok: Boolean(settings && settings.ok) });
    if (process.env.TRAINER_GUI_ACTIVE_FILE) {
      const document = await vscode.workspace.openTextDocument(process.env.TRAINER_GUI_ACTIVE_FILE);
      await vscode.window.showTextDocument(document, { preview: false });
    }
    await vscode.commands.executeCommand("trainer.openWorkbench");
    await sleep(2000);
    report.ok = report.steps.every((step) => step.ok !== false);
  } catch (error) {
    report.error = error && error.stack ? error.stack : String(error);
  }
  if (reportPath) fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
}
module.exports = { activate, deactivate() {} };
`,
  );
}
writeDriverExtension();

function runCode(args) {
  const result = spawnSync(codeCli, args, { encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(`code CLI failed: ${result.stdout}\n${result.stderr}`);
  }
}

let providerRuntime = null;
let proxy = null;
const results = (checkpoint?.results ?? []).filter((step) => step.ok);
const record = (step, payload) => {
  results.push({ step, ...payload, at: new Date().toISOString() });
};

try {
  if (unified && !paperJourney) process.env.TRAINER_VSIX_E2E_FILE_FIXTURE = "1";
  providerRuntime = await resolveVsixE2EProviderRuntime({ extensionDir });
  if (paperJourney && providerRuntime.source !== "external") {
    throw new Error("--paper requires an explicit real model configured through TRAINER_E2E_PROVIDER_*.");
  }
  if (checkpoint && checkpoint.providerModel !== providerRuntime.model) {
    throw new Error("Resume with the same configured model as the browser checkpoint.");
  }
  proxy = await startDelayedProxy(providerRuntime.baseUrl, 1400);
  const providerPayload = buildVsixE2EProviderSavePayloadTemplate(providerRuntime.configuration);
  if (paperJourney) {
    providerPayload.requestDefaults = { ...providerPayload.requestDefaults, clientTimeoutSeconds: 150 };
  }
  const launchEnv = withVsixE2EFixtureLoopbackBypass({
    ...process.env,
    COACH_GUI_REPORT: reportPath,
    ...(unified ? { TRAINER_GUI_ACTIVE_FILE: boundaryFile } : {}),
    ...(checkpoint ? { TRAINER_GUI_CONTINUE: "1" } : {}),
    COACH_GUI_TARGET_EXTENSION_ID: extensionId,
    COACH_GUI_PROJECT_PATH: workspaceDir,
    COACH_GUI_PROVIDER: JSON.stringify({
      payload: providerPayload,
      baseUrl: proxy.baseUrl,
      model: providerRuntime.model,
      apiKey: providerRuntime.apiKey,
    }),
  });

  runCode(["--user-data-dir", userDataDir, "--extensions-dir", extensionsDir, "--install-extension", vsixPath, "--force"]);
  fs.rmSync(reportPath, { force: true });

  const launch = (env) => _electron.launch({
    executablePath: electronBinary,
    args: [
      "--user-data-dir",
      userDataDir,
      "--extensions-dir",
      extensionsDir,
      "--disable-workspace-trust",
      "--skip-welcome",
      "--skip-release-notes",
      "--extensionDevelopmentPath",
      driverDir,
      "--new-window",
      workspaceDir,
    ],
    env,
    timeout: 120_000,
  });
  let app = await launch(launchEnv);

  const screenshot = async (page, name) => {
    const file = path.join(outDir, `${name}.png`);
    await page.screenshot({ path: file, timeout: 30_000 });
    return path.relative(repoRoot, file);
  };
  const commandPalette = async (page, command) => {
    await page.keyboard.press("Meta+Shift+P");
    await page.waitForTimeout(700);
    await page.keyboard.type(command);
    await page.waitForTimeout(600);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(1500);
  };
  const findFrame = async (page, timeout = 60_000) => {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      for (const candidate of page.frames()) {
        if (!candidate.url().includes("vscode-webview://")) continue;
        try {
          const text = await candidate.locator("body").innerText({ timeout: 1500 });
          if (/对话|Coach/.test(text)) return candidate;
        } catch {
          // still loading
        }
      }
      await page.waitForTimeout(800);
    }
    throw new Error("Trainer webview frame not found");
  };
  const waitForReply = async (page, frame, timeout = 120_000) => {
    const start = Date.now();
    let last = "";
    while (Date.now() - start < timeout) {
      last = (await frame.locator("body").innerText()).replace(/\s+/g, " ").trim();
      const busy = await frame.locator(".coach-working, .agent-activity-strip").count();
      const assistant = await frame
        .locator(".message-bubble__body")
        .filter({ has: frame.locator(".message-bubble__assistant-rail") })
        .count();
      if (busy === 0 && assistant > 0 && last.length > 40) return last;
      await page.waitForTimeout(700);
    }
    throw new Error(`Timed out waiting for the coach reply: ${last.slice(0, 500)}`);
  };

  async function stageBrowserSelection(frame) {
    const sourceUrl = paperJourney ? paperUrl : "https://trainer-source.example.org/workspace-scopes";
    const extensionPath = path.join(repoRoot, "browser-extension");
    let browser;
    try {
      browser = await chromium.launchPersistentContext(path.join(root, "browser"), {
        channel: "chromium", headless: true,
        args: ["--disable-extensions-except=" + extensionPath, "--load-extension=" + extensionPath],
      });
      const worker = browser.serviceWorkers()[0] ?? await browser.waitForEvent("serviceworker", { timeout: 15_000 });
      const article = await browser.newPage();
      if (!paperJourney) {
        await article.route(sourceUrl, (route) => route.fulfill({
          contentType: "text/html",
          body: "<title>Workspace scopes</title><p id=source>Always compare the original workspace_id to the returned workspace_id.</p>",
        }));
      }
      const response = await article.goto(sourceUrl, { waitUntil: "domcontentloaded", timeout: 45_000 });
      if (!response?.ok()) throw new Error("The browser source could not be loaded.");
      const selectedParagraph = paperJourney
        ? article.locator('p[id="S4.SS2.p5.1"]')
        : article.locator("#source");
      await selectedParagraph.evaluate((element) => {
        const range = document.createRange();
        range.selectNodeContents(element);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      });
      // In Chromium the extension's own page can send the same command as
      // its popup. Evaluate in an extension page, with the article active.
      const control = await browser.newPage();
      await control.goto(new URL("popup/popup.html", worker.url()).toString());
      await article.bringToFront();
      const delivery = await control.evaluate(() => chrome.runtime.sendMessage({ type: "trainer:send-tab-context" }));
      if (delivery?.status !== "sent") throw new Error("Browser delivery did not reach Trainer: " + String(delivery?.status));
      await frame.getByTitle(paperJourney ? /arxiv\.org\/html\/2407/ : /trainer-source\.example\.org/)
        .first().waitFor({ timeout: 25_000 });
      const composer = frame.locator("#coach-composer");
      const draft = await composer.inputValue();
      if (!draft.includes(paperJourney ? "episode is truncated" : "original workspace_id")) {
        throw new Error("The draft omitted the selected source.");
      }
      return draft;
    } finally {
      await browser?.close();
    }
  }

  function readPersistedLearning(workspaceCallback) {
    const roots = path.join(userDataDir, "User", "globalStorage", extensionId, "sidecar", "roots");
    for (const rootName of fs.readdirSync(roots)) {
      const file = path.join(roots, rootName, "trainer.sqlite3");
      if (!fs.existsSync(file)) continue;
      const db = new DatabaseSync(file, { readOnly: true });
      try {
        const record = workspaceCallback(db);
        if (record) return record;
      } finally {
        db.close();
      }
    }
    return undefined;
  }

  let activePage;
  try {
    const page = await app.firstWindow({ timeout: 120_000 });
    activePage = page;
    await page.waitForTimeout(8000);
    const deadline = Date.now() + 180_000;
    while (!fs.existsSync(reportPath) && Date.now() < deadline) {
      await page.waitForTimeout(2000);
    }
    if (!fs.existsSync(reportPath)) throw new Error("Driver never wrote its report.");
    const driverReport = JSON.parse(fs.readFileSync(reportPath, "utf8"));
    record("driver-report", { ok: driverReport.ok === true, steps: driverReport.steps, error: driverReport.error });
    if (!driverReport.ok) throw new Error(`Driver setup failed: ${driverReport.error || "unknown"}`);

    await commandPalette(page, "Trainer: Open Coach Sidebar");
    await page.waitForTimeout(5000);
    const frame = await findFrame(page);
    const coachTab = frame.locator("button, a").filter({ hasText: /^对话$/ }).first();
    if (await coachTab.count()) await coachTab.click();
    await page.waitForTimeout(800);

    const composer = frame.locator("#coach-composer").first();
    await composer.waitFor({ timeout: 30_000 });
    if (goalJourney) {
      const goal = "掌握 Python 重入锁的用法";
      await composer.fill(goal);
      await frame.getByRole("button", { name: "添加", exact: true }).click();
      const menu = frame.getByRole("menu", { name: "添加", exact: true });
      await menu.getByRole("menuitem", { name: "附件", exact: true }).waitFor();
      await menu.getByRole("menuitem", { name: "工作流", exact: true }).waitFor();
      if (await menu.getByText("查看全部", { exact: true }).count()) throw new Error("Unexpected View all entry.");
      const menuScreenshot = await screenshot(page, "01-add-menu");
      await menu.getByRole("menuitemcheckbox", { name: "目标模式", exact: true }).click();
      const goalBar = frame.locator("[data-goal-bar=true]");
      await frame.locator('[data-goal-pending="true"]').waitFor();
      if (await composer.inputValue() !== goal) throw new Error("Goal mode changed the existing draft.");
      await composer.press("Enter");
      const readGoal = async (status) => {
        const deadline = Date.now() + 30_000;
        while (Date.now() < deadline) {
          const row = readPersistedLearning((db) => db.prepare(
            "SELECT goal_id, status, payload FROM goal_sessions WHERE json_extract(payload, '$.title') = ?",
          ).get(goal));
          if (row?.status === status) return row;
          await page.waitForTimeout(250);
        }
        throw new Error(`Goal did not persist with status ${status}.`);
      };
      const active = await readGoal("active");
      if (JSON.parse(active.payload).source !== "user_explicit") throw new Error("Goal was not created explicitly.");
      await frame.locator('[data-goal-pending="false"]').getByText(goal, { exact: true }).waitFor();
      await waitForReply(page, frame);
      const goalScreenshot = await screenshot(page, "02-active-goal");
      await goalBar.getByRole("button", { name: "暂停目标" }).click();
      const paused = await readGoal("paused");
      await goalBar.getByRole("button", { name: "继续目标" }).click();
      const resumed = await readGoal("active");
      await goalBar.getByRole("button", { name: "结束目标" }).click();
      const completed = await readGoal("completed");
      await goalBar.waitFor({ state: "hidden" });
      record("goal-mode", {
        ok: [paused, resumed, completed].every((row) => row.goal_id === active.goal_id),
        goalId: active.goal_id,
        source: "user_explicit",
        lifecycle: [active.status, paused.status, resumed.status, completed.status],
        menuScreenshot,
        goalScreenshot,
      });
    } else if (!checkpoint) {
      const prompt = "用一句话解释什么是幂等，并说明为什么重试是安全的。";
      await composer.fill(prompt);
      await composer.press("Enter");
      await frame.locator(".coach-working, .agent-activity-strip").first().waitFor({ timeout: 15_000 });

      const sendingFacts = await frame.evaluate((needle) => {
        const bodyText = (document.body.innerText || "").replace(/\s+/g, " ");
        const statusNodes = document.querySelectorAll(".coach-working, .agent-activity-strip");
        return {
          userMessageVisible: bodyText.includes(needle.slice(0, 12)),
          statusNodeCount: statusNodes.length,
          statusText:
            statusNodes.length === 1
              ? (statusNodes[0].textContent || "").trim().slice(0, 120)
              : "",
          skeletonCount: document.querySelectorAll(".skeleton").length,
          stepNumberCount: document.querySelectorAll("[data-step-number]").length,
        };
      }, prompt);
      record("sending-status", {
        ok:
          sendingFacts.userMessageVisible === true &&
          sendingFacts.statusNodeCount === 1 &&
          sendingFacts.skeletonCount === 0,
        facts: sendingFacts,
        screenshot: await screenshot(page, "01-sending-status"),
      });

      await waitForReply(page, frame);
      await page.waitForTimeout(2500);
      const replyText = (await frame.locator("body").innerText()).replace(/\s+/g, " ").trim();
      record("coach-reply", {
        ok: replyText.length > 40,
        screenshot: await screenshot(page, "02-coach-reply"),
        text: replyText.slice(0, 500),
      });
    }

    if (unified) {
      const send = async (text) => {
        await composer.fill(text);
        await frame.locator('.composer__send[type="submit"]').click();
      };
      const compoundPrompt = paperJourney
        ? "把这篇文章加入我的学习计划，再根据它生成一道练习，检查当前 Python 文件的 should_bootstrap 函数。"
        : "把这篇文章加入我的学习计划，再根据它生成一道练习，检查当前文件对 workspace_id 的比较。";
      await frame.getByTestId("trainer-view-nav-plan").click();
      const settledReply = '[data-view-agent-reply="plan"] [data-message-id]:not([data-message-id^="streaming-"])';
      if (!checkpoint) {
        await send(paperJourney
          ? "生成并保存正式学习计划：Gymnasium 的终止与截断。只安排 1 个阶段，共一周，每周 1 小时。目标是用 pytest 验证当前 Python 文件，只基于当前代码，先不查资料。"
          : "生成正式学习计划：工作区范围验证。");
        await frame.locator('[data-unified-action-preview="plan"]').getByRole("button", { name: "确认并执行" }).click();
        await frame.locator('[data-template="LearningHome"]').getByText(paperJourney
          ? /should_bootstrap|truncated|截断|价值估计|Gymnasium/i : /工作区范围验证|确认工作区范围/).first().waitFor({
          timeout: paperJourney ? 300_000 : 90_000,
        });
        await frame.locator(settledReply).first().waitFor({ timeout: paperJourney ? 180_000 : 45_000 });
        const persistedPlan = readPersistedLearning((db) => db.prepare("SELECT plan_id FROM learning_plan LIMIT 1").get());
        if (!persistedPlan?.plan_id) throw new Error("The formal learning plan was not persisted.");
        record("unified-formal-plan", {
          ok: !paperJourney || modelCalls.some((call) => call.tools?.includes("save_formal_plan")),
          planId: persistedPlan.plan_id,
          screenshot: await screenshot(page, "02a-saved-learning-plan"),
        });
        await stageBrowserSelection(frame);
        record("browser-selection", {
          ok: true,
          ...(paperJourney ? { source: paperUrl } : {}),
          screenshot: await screenshot(page, "03-browser-selection-prefilled"),
        });
      } else {
        const previousPlan = checkpoint.results.find((step) => step.step === "unified-formal-plan")?.planId;
        const persistedPlan = readPersistedLearning((db) => db.prepare(
          "SELECT plan_id FROM learning_plan WHERE plan_id = ?",
        ).get(previousPlan));
        if (!persistedPlan) throw new Error("The checkpoint's learning plan was not restored.");
        if (!linkedCheckpoint) {
          await frame.getByTitle(/arxiv\.org\/html\/2407/).first().waitFor({ timeout: 25_000 });
          record("unified-browser-draft-restored", {
            ok: true, planId: previousPlan, screenshot: await screenshot(page, "03a-browser-source-restored"),
          });
        }
      }
      if (!linkedCheckpoint) {
        const existingReply = frame.locator(settledReply).first();
        const planReplyId = await existingReply.isVisible() ? await existingReply.getAttribute("data-message-id") : null;
        await send(paperJourney
          ? "用两句话解释这段论文选文。结合当前任务，说清楚为什么截断后仍应估计后续价值。"
          : "解释这段浏览器选文，结合当前学习目标。");
        const explanation = frame.locator(`${settledReply}:not([data-message-id=${JSON.stringify(planReplyId)}]) .message-bubble__body`).first();
        await explanation.waitFor({ timeout: paperJourney ? 240_000 : 45_000 });
        await frame.locator('.composer__send[type="button"].is-busy').waitFor({ state: "hidden", timeout: paperJourney ? 240_000 : 45_000 });
        if (paperJourney && !/截断|truncat/i.test(await explanation.innerText())) {
          throw new Error("The explanation did not discuss the selected paper passage.");
        }
        if (linkFromBrowserDraft) {
          await send(compoundPrompt);
          await frame.locator('[data-unified-action-preview="browser"]').getByRole("button", { name: "确认并执行" }).click();
        } else {
          await send("把这段内容保存到资料库");
          await frame.locator('[data-surface="resources"]:visible').waitFor({ timeout: 60_000 });
          await send(paperJourney ? "/搜索资料 Gymnasium" : "/搜索资料 workspace");
          await frame.locator("[data-clear-resource-search]").waitFor({ timeout: 25_000 });
          record("unified-resource-search", {
            ok: (await frame.locator("#coach-composer:visible").count()) === 1,
            screenshot: await screenshot(page, "04-resource-search"),
          });
          await send("检查哪些资料有新版本");
          await frame.locator('[data-resource-version-check] [data-resource-version-status="no_baseline"]')
            .first().waitFor({ timeout: 25_000 });
          const versionPanel = frame.locator("[data-resource-version-check]");
          record("unified-version-check", {
            ok: true, status: "no_baseline",
            screenshot: await screenshot(page, "04a-source-version-check"),
          });
          await versionPanel.getByRole("button", { name: "关闭" }).click();
          await send(compoundPractice ? compoundPrompt : "把这份资料加入当前学习");
          await frame.locator('[data-unified-action-preview="library"]').getByRole("button", { name: "确认并执行" }).click();
        }
        await frame.locator('[data-surface="plan"]:visible').waitFor({ timeout: 45_000 });
      }
      const readLinkedSource = () => readPersistedLearning((db) => db.prepare(`
        SELECT json_extract(payload_ref_json, '$.resource_id') AS resourceId,
               json_extract(payload_ref_json, '$.version_id') AS versionId,
               json_extract(payload_ref_json, '$.content_hash') AS contentHash
        FROM event_ledger WHERE event_type = 'resource_linked' LIMIT 1
      `).get());
      const linkDeadline = Date.now() + 45_000;
      let linked = readLinkedSource();
      while (!linked && Date.now() < linkDeadline) {
        await page.waitForTimeout(250);
        linked = readLinkedSource();
      }
      if (!linked?.resourceId || !linked.versionId || !linked.contentHash) {
        throw new Error("Learning did not record the precise saved resource version.");
      }
      if (linkedCheckpoint && (linked.resourceId !== linkedCheckpoint.resourceId ||
        linked.versionId !== linkedCheckpoint.versionId || linked.contentHash !== linkedCheckpoint.contentHash)) {
        throw new Error("The linked paper's identity changed after restarting.");
      }
      record("unified-resource-linked", {
        ok: true, ...linked,
        screenshot: await screenshot(page, "04a-resource-linked"),
      });
      await composer.evaluate((input) => input.setAttribute("data-journey-composer", "true"));
      await frame.locator('[data-primary-surface="plan"]:visible').evaluate((surface) => {
        surface.setAttribute("data-journey-learning", "true");
      });
      const generationStartedAt = new Date().toISOString();
      if (!compoundPractice || linkedCheckpoint) {
        await send(paperJourney
          ? "/练习 基于这份论文修复当前 Python 文件的 should_bootstrap。限定改一个函数，解释终止与截断会怎样改变后续价值估计。"
          : "/练习 检查当前文件对 workspace_id 的比较");
      }
      const card = frame.locator('[data-template="FocusedPractice"]:visible').first();
      if (paperJourney) {
        const generationDeadline = Date.now() + 150_000;
        while (!(await card.isVisible()) && Date.now() < generationDeadline) {
          const failure = readPersistedLearning((db) => db.prepare(`
            SELECT json_extract(payload_ref_json, '$.reason') AS reason
            FROM event_ledger WHERE event_type = 'card_generation_failed' AND occurred_at > ?
            ORDER BY occurred_at DESC LIMIT 1
          `).get(generationStartedAt));
          if (failure?.reason) throw new Error(`Training card generation failed: ${failure.reason}`);
          await page.waitForTimeout(400);
        }
      }
      await card.waitFor({ timeout: paperJourney ? 1000 : 90_000 });
      const start = card.getByRole("button", { name: /开始|Start/ }).first();
      if (await start.isVisible()) await start.click();
      await composer.waitFor({ timeout: 30_000 });
      const sameLearningInput = (await composer.getAttribute("data-journey-composer")) === "true" &&
        (await frame.locator('[data-primary-surface="plan"]:visible').getAttribute("data-journey-learning")) === "true";
      if (!sameLearningInput || (await frame.locator("textarea:visible").count()) !== 1) {
        throw new Error("Practice did not keep the same Learning surface and its single composer.");
      }
      const cardId = await card.locator("xpath=ancestor::*[@data-training-card-id][1]").getAttribute("data-training-card-id");
      const authored = paperJourney ? readPersistedLearning((db) => db.prepare(`
        SELECT json_extract(payload_ref_json, '$.generation_source') AS generationSource,
               json_extract(payload_ref_json, '$.resource_id') AS resourceId,
               json_extract(payload_ref_json, '$.resource_version_id') AS versionId,
               json_extract(payload_ref_json, '$.resource_content_hash') AS contentHash
        FROM event_ledger
        WHERE event_type = 'card_candidate_created'
          AND json_extract(payload_ref_json, '$.card_id') = ?
        ORDER BY occurred_at DESC LIMIT 1
      `).get(cardId)) : undefined;
      if (paperJourney && (authored?.generationSource !== "model" || authored.resourceId !== linked.resourceId ||
        authored.versionId !== linked.versionId || authored.contentHash !== linked.contentHash)) {
        throw new Error("The displayed practice was not model-authored against the exact linked paper version.");
      }
      const visibleTask = authored ? (await card.innerText()).trim() : undefined;
      const checks = card.locator('[data-training-card-fact="verify"]');
      if (authored) await card.locator("[data-training-card-details] summary").click();
      const verificationChecks = authored ? (await checks.innerText()).trim() : undefined;
      if (paperJourney && (!verificationChecks?.includes("assert should_bootstrap(False, True)") ||
        !verificationChecks.includes("assert not should_bootstrap(True, False)"))) {
        throw new Error("The practice did not show both independently specified episode-boundary checks.");
      }
      record("unified-practice", {
        ok: Boolean(cardId) && sameLearningInput,
        ...(authored ? { cardId, ...authored, visibleTask, verificationChecks } : {}),
        screenshot: await screenshot(page, "05-learning-practice"),
      });
      await proxy.stop();
      proxy = null;
      // Simulate an independent learner edit in the isolated project.
      fs.writeFileSync(boundaryFile, exercise.solved);
      await page.waitForTimeout(1600);
      await send("我已经在 VS Code 里完成了，帮我验证。");
      const activity = frame.locator('[data-surface="training"]:visible [data-learning-activity]');
      await activity.locator("summary").click();
      const evidence = activity.locator('[data-learning-event="training_evidence_recorded"]');
      const readVerification = () => readPersistedLearning((db) => db.prepare(`
        SELECT json_extract(evidence.payload, '$.result') AS verdict,
               json_extract(evidence.payload, '$.trust_level') AS trustLevel,
               json_extract(evidence.payload, '$.artifact_hash') AS artifactHash,
               json_extract(evidence.payload, '$.resource_id') AS resourceId,
               json_extract(evidence.payload, '$.resource_version_id') AS versionId,
               json_extract(evidence.payload, '$.resource_content_hash') AS contentHash,
               json_extract(event.payload_ref_json, '$.next_due') AS nextDue
        FROM training_evidence evidence JOIN event_ledger event
          ON event.workspace_id = evidence.workspace_id
         AND json_extract(event.payload_ref_json, '$.card_id') = json_extract(evidence.payload, '$.card_id')
        WHERE event.event_type = 'review_scheduled'
          AND json_extract(evidence.payload, '$.card_id') = ?
        ORDER BY event.occurred_at DESC LIMIT 1
      `).get(cardId));
      const verificationDeadline = Date.now() + 90_000;
      let persisted = readVerification();
      while (!persisted && Date.now() < verificationDeadline) {
        await page.waitForTimeout(400);
        persisted = readVerification();
      }
      const artifactHash = createHash("sha256").update(fs.readFileSync(boundaryFile)).digest("hex");
      if (persisted?.verdict !== "passed" || persisted.trustLevel !== "controlled_check" ||
        persisted.artifactHash !== artifactHash || !Number.isFinite(Date.parse(persisted.nextDue)) ||
        persisted.resourceId !== linked.resourceId || persisted.versionId !== linked.versionId ||
        persisted.contentHash !== linked.contentHash) {
        throw new Error("The verification evidence does not match the file, card, saved source version and FSRS schedule.");
      }
      await evidence.first().waitFor({ timeout: 30_000 });
      await activity.locator('[data-learning-event="evaluation_feedback_recorded"]').first().waitFor({ timeout: 30_000 });
      await activity.locator('[data-learning-event="review_scheduled"]').first().waitFor({ timeout: 30_000 });
      await evidence.first().scrollIntoViewIfNeeded();
      record("unified-verification-and-review", {
        ok: true, cardId, providerAvailable: false, ...persisted,
        screenshot: await screenshot(page, "06-verification-and-review"),
      });
      const recoveryDraft = paperJourney ? "重启后继续比较终止与截断" : "重启后继续检查边界条件";
      const practiceInput = composer;
      const canRestorePracticeDraft = await practiceInput.isVisible();
      if (canRestorePracticeDraft) await practiceInput.fill(recoveryDraft);
      await app.close();
      await providerRuntime.stop();
      fs.rmSync(reportPath, { force: true });
      app = await launch({ ...launchEnv, TRAINER_GUI_RESUME: "1" });
      const reopened = await app.firstWindow({ timeout: 120_000 });
      activePage = reopened;
      const resumeDeadline = Date.now() + 60_000;
      while (!fs.existsSync(reportPath) && Date.now() < resumeDeadline) {
        await reopened.waitForTimeout(500);
      }
      if (!fs.existsSync(reportPath) || !JSON.parse(fs.readFileSync(reportPath, "utf8")).ok) {
        throw new Error("Trainer did not activate after restarting VS Code.");
      }
      const restored = await findFrame(reopened).catch(async () => {
        await commandPalette(reopened, "Trainer: Open Coach Sidebar");
        return findFrame(reopened);
      });
      const restoredCard = restored.locator('[data-template="FocusedPractice"]:visible');
      await restoredCard.waitFor({ timeout: 45_000 });
      const restoredCardId = await restoredCard.locator("xpath=ancestor::*[@data-training-card-id][1]").getAttribute("data-training-card-id");
      const restoredDraft = canRestorePracticeDraft
        ? await restored.locator("#coach-composer").inputValue() : undefined;
      if ((canRestorePracticeDraft && restoredDraft !== recoveryDraft) || restoredCardId !== cardId) {
        throw new Error("Reopening VS Code did not restore the training card and its draft.");
      }
      const restoredActivity = restored.locator('[data-surface="training"]:visible [data-learning-activity]');
      await restoredActivity.locator("summary").click();
      await restoredActivity.locator('[data-learning-event="review_scheduled"]').first().waitFor({ timeout: 15_000 });
      record("unified-restart", {
        ok: true, cardId, providerAvailable: false,
        screenshot: await screenshot(reopened, "07-reopened-learning"),
      });
    } else if (!goalJourney) {

    // New chat + immediate first send: the first message must survive.
    const historyToggle = frame.locator('[data-testid="trainer-history-toggle"]').first();
    if (await historyToggle.count()) {
      await historyToggle.click();
      await page.waitForTimeout(800);
      const newChat = frame.locator("button").filter({ hasText: /新对话|New chat/ }).first();
      if (await newChat.count()) {
        await newChat.click();
        await page.waitForTimeout(700);
      }
    }
    const freshComposer = frame.locator("#coach-composer").first();
    await freshComposer.fill("这是新会话的第一条消息：请给我一个最小练习。");
    await freshComposer.press("Enter");
    await page.waitForTimeout(600);
    const firstMessageFacts = await frame.evaluate(() => {
      const bodyText = (document.body.innerText || "").replace(/\s+/g, " ");
      const statusNodes = document.querySelectorAll(".coach-working, .agent-activity-strip");
      return {
        firstMessageVisible: bodyText.includes("这是新会话的第一条消息"),
        statusNodeCount: statusNodes.length,
        skeletonCount: document.querySelectorAll(".skeleton").length,
      };
    });
    record("new-session-first-send", {
      ok: firstMessageFacts.firstMessageVisible === true,
      facts: firstMessageFacts,
      screenshot: await screenshot(page, "03-new-session-first-send"),
    });
    await page.waitForTimeout(9000);
    const afterReply = (await frame.locator("body").innerText()).replace(/\s+/g, " ").trim();
    record("new-session-reply", {
      ok: afterReply.length > 80 && afterReply.includes("这是新会话的第一条消息"),
      screenshot: await screenshot(page, "04-new-session-reply"),
      text: afterReply.slice(0, 500),
    });
    }
  } catch (error) {
    if (activePage) await screenshot(activePage, "failure").catch(() => undefined);
    throw error;
  } finally {
    try {
      await app.close();
    } catch {
      // Evidence stays.
    }
  }
} catch (error) {
  record("fatal", { ok: false, error: error instanceof Error ? error.stack : String(error) });
} finally {
  if (proxy) await proxy.stop().catch(() => undefined);
  if (providerRuntime) await providerRuntime.stop().catch(() => undefined);
}

const failures = results.filter((item) => item.ok === false);
const report = {
  stamp,
  vsixPath,
  extensionId,
  providerSource: providerRuntime?.source,
  providerModel: providerRuntime?.model,
  ...(compoundPractice ? { compoundPractice: true } : {}),
  ...(linkFromBrowserDraft ? { linkFromBrowserDraft: true } : {}),
  ...(checkpointPath ? { continuedFrom: checkpointPath } : {}),
  modelCalls,
  isolatedProfile: { userDataDir, extensionsDir, workspaceDir },
  results,
  failures: failures.length,
  ok: failures.length === 0 && results.some((r) => r.step === (goalJourney ? "goal-mode" : "sending-status") && r.ok),
  artifacts: { screenshots: fs.readdirSync(outDir).filter((n) => n.endsWith(".png")) },
};
fs.writeFileSync(path.join(outDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ ok: report.ok, outDir: path.relative(repoRoot, outDir), failures }, null, 2));
process.exit(report.ok ? 0 : 1);
