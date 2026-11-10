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
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron } from "playwright";
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
const vsixPath = path.join(extensionDir, `trainer-extension-${packageJson.version}-darwin-arm64.vsix`);
const codeCli = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code";
const electronBinary = requireVSCodeElectronBinary();
if (!fs.existsSync(vsixPath)) {
  throw new Error(`Packaged VSIX not found: ${vsixPath}. Run npm run package:vsix first.`);
}

const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join(repoRoot, "output", "coach-gui", stamp);
const root = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-coach-gui-"));
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

fs.writeFileSync(
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
provisionTrainerWorkspace();

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
seedTrainerWorkspaceRoot();

// Delayed loopback proxy in front of the fixture provider: the UI needs a
// moment of real in-flight work so the single status line can be observed.
function startDelayedProxy(targetBaseUrl, delayMs) {
  const server = http.createServer(async (request, response) => {
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
    const payload = Buffer.from(await upstream.arrayBuffer());
    if ((request.url ?? "").includes("/chat/completions")) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
    response.writeHead(upstream.status, Object.fromEntries(upstream.headers.entries()));
    response.end(payload);
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
    const admitted = await vscode.commands.executeCommand("trainer.workspace.adoptProject", {
      projectPath: process.env.COACH_GUI_PROJECT_PATH || undefined,
    });
    report.steps.push({ step: "admit-project", ok: Boolean(admitted && admitted.ok), message: admitted && admitted.message });
    await sleep(1500);
    const saved = await vscode.commands.executeCommand("trainer.provider.save", {
      ...provider.payload,
      baseUrl: provider.baseUrl,
      model: provider.model,
      apiKey: provider.apiKey,
      replaceApiKey: true,
    });
    report.steps.push({ step: "save-provider", ok: Boolean(saved && saved.ok), message: saved && saved.message });
    await sleep(1000);
    const settings = await vscode.commands.executeCommand("trainer.memory.saveCoachSettings", {
      responseLanguage: "zh-CN",
      answerMode: "coach-first",
    });
    report.steps.push({ step: "coach-settings", ok: Boolean(settings && settings.ok) });
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
const results = [];
const record = (step, payload) => {
  results.push({ step, ...payload, at: new Date().toISOString() });
};

try {
  providerRuntime = await resolveVsixE2EProviderRuntime({ extensionDir });
  proxy = await startDelayedProxy(providerRuntime.baseUrl, 1400);
  const providerPayload = buildVsixE2EProviderSavePayloadTemplate(providerRuntime.configuration);
  const launchEnv = withVsixE2EFixtureLoopbackBypass({
    ...process.env,
    COACH_GUI_REPORT: reportPath,
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

  const app = await _electron.launch({
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
    env: launchEnv,
    timeout: 120_000,
  });

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

  try {
    const page = await app.firstWindow({ timeout: 120_000 });
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
    const prompt = "用一句话解释什么是幂等，并说明为什么重试是安全的。";
    await composer.fill(prompt);
    await composer.press("Enter");
    await page.waitForTimeout(350);

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
  isolatedProfile: { userDataDir, extensionsDir, workspaceDir },
  results,
  failures: failures.length,
  ok: failures.length === 0 && results.some((r) => r.step === "sending-status" && r.ok),
  artifacts: { screenshots: fs.readdirSync(outDir).filter((n) => n.endsWith(".png")) },
};
fs.writeFileSync(path.join(outDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ ok: report.ok, outDir: path.relative(repoRoot, outDir), failures }, null, 2));
process.exit(report.ok ? 0 : 1);
