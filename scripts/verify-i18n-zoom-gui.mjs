#!/usr/bin/env node
/**
 * Real VS Code GUI gate: 200% zoom × all eight workbench languages.
 *
 * Installs the packaged VSIX into an isolated profile, sets
 * `window.zoomLevel` to 4 (~200%), then walks the eight supported languages
 * through the extension's own settings command. For each language it opens
 * each primary destination at 460px-equivalent width, measures horizontal
 * overflow inside the real webview, and captures a window screenshot.
 *
 * Evidence: output/i18n-zoom/<stamp>/{report.json,*.png}
 */
import { spawnSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron } from "playwright";
import { requireVSCodeElectronBinary } from "./vscode-electron.mjs";

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

const LANGUAGES = [
  { code: "zh-CN", resources: "资料", coach: "对话", plan: "学习" },
  { code: "en-US", resources: "Resources", coach: "Chat", plan: "Learning" },
  { code: "es-ES", resources: "Recursos", coach: "Chat", plan: "Plan" },
  { code: "fr-FR", resources: "Ressources", coach: "Chat", plan: "Plan" },
  { code: "de-DE", resources: "Materialien", coach: "Chat", plan: "Plan" },
  { code: "ja-JP", resources: "資料", coach: "対話", plan: "計画" },
  { code: "ko-KR", resources: "자료", coach: "대화", plan: "계획" },
  { code: "pt-BR", resources: "Recursos", coach: "Chat", plan: "Plano" },
];

const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join(repoRoot, "output", "i18n-zoom", stamp);
const root = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-i18n-zoom-"));
const userDataDir = path.join(root, "user-data");
const extensionsDir = path.join(root, "extensions");
const workspaceDir = path.join(root, "workspace");
const trainerWorkspaceDir = path.join(root, "trainer-workspace");
const driverDir = path.join(root, "driver");
const setupReportPath = path.join(root, "setup-report.json");
const nextPath = path.join(root, "next.json");
const readyPath = path.join(root, "ready.json");
const donePath = path.join(root, "done.json");
for (const dir of [
  path.join(userDataDir, "User"),
  path.join(userDataDir, "User", "globalStorage"),
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

function seedTrainerWorkspaceRoot() {
  const database = new DatabaseSync(path.join(userDataDir, "User", "globalStorage", "state.vscdb"));
  try {
    database.exec(
      "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)",
    );
    const read = (value) => {
      if (value === undefined || value === null) return undefined;
      try {
        return JSON.parse(typeof value === "string" ? value : Buffer.from(value).toString("utf8"));
      } catch {
        return undefined;
      }
    };
    const existing = read(
      database.prepare("SELECT value FROM ItemTable WHERE key = ?").get(extensionId)?.value,
    );
    const extensionState = existing && typeof existing === "object" ? existing : {};
    extensionState["trainer.workspace.root.v1"] = trainerWorkspaceDir;
    database
      .prepare("INSERT INTO ItemTable (key, value) VALUES (?, ?)")
      .run(extensionId, JSON.stringify(extensionState));
    const keyIndex = `extensionKeys/${extensionId}@${packageJson.version}`;
    const existingKeys = read(
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

function writeDriverExtension() {
  fs.writeFileSync(
    path.join(driverDir, "package.json"),
    `${JSON.stringify(
      {
        name: "trainer-i18n-zoom-driver",
        displayName: "Trainer i18n Zoom Driver",
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
  const targetId = process.env.I18N_ZOOM_TARGET_EXTENSION_ID;
  const setupPath = process.env.I18N_ZOOM_SETUP;
  const nextPath = process.env.I18N_ZOOM_NEXT;
  const readyPath = process.env.I18N_ZOOM_READY;
  const donePath = process.env.I18N_ZOOM_DONE;
  const report = { ok: false, steps: [] };
  try {
    const target = vscode.extensions.getExtension(targetId);
    if (!target) throw new Error("Trainer extension not installed: " + targetId);
    await target.activate();
    await sleep(12000);
    const admitted = await vscode.commands.executeCommand("trainer.workspace.adoptProject", {
      projectPath: process.env.I18N_ZOOM_PROJECT_PATH || undefined,
    });
    report.steps.push({ step: "admit-project", ok: Boolean(admitted && admitted.ok) });
    await sleep(2000);
    await vscode.workspace
      .getConfiguration("window")
      .update("zoomLevel", 4, vscode.ConfigurationTarget.Global);
    await sleep(1500);
    report.zoomLevel = vscode.workspace.getConfiguration("window").get("zoomLevel");
    await vscode.commands.executeCommand("trainer.openWorkbench");
    await sleep(2500);
    report.ok = true;
    fs.writeFileSync(setupPath, JSON.stringify(report));

    while (true) {
      if (!fs.existsSync(nextPath)) {
        await sleep(250);
        continue;
      }
      const request = JSON.parse(fs.readFileSync(nextPath, "utf8"));
      fs.unlinkSync(nextPath);
      const saved = await vscode.commands.executeCommand("trainer.memory.saveCoachSettings", {
        responseLanguage: request.lang,
        answerMode: "coach-first",
      });
      await sleep(2200);
      fs.writeFileSync(readyPath, JSON.stringify({ lang: request.lang, ok: Boolean(saved && saved.ok) }));
      while (!fs.existsSync(donePath)) {
        await sleep(200);
      }
      fs.unlinkSync(donePath);
    }
  } catch (error) {
    report.error = error && error.stack ? error.stack : String(error);
    fs.writeFileSync(setupPath, JSON.stringify(report));
  }
}
module.exports = { activate, deactivate() {} };
`,
  );
}
writeDriverExtension();

function runCode(args) {
  const result = spawnSync(codeCli, args, { encoding: "utf8" });
  if (result.status !== 0) throw new Error(`code CLI failed: ${result.stdout}\n${result.stderr}`);
}
runCode(["--user-data-dir", userDataDir, "--extensions-dir", extensionsDir, "--install-extension", vsixPath, "--force"]);

const results = [];
const record = (step, payload) => results.push({ step, ...payload, at: new Date().toISOString() });

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
  env: {
    ...process.env,
    I18N_ZOOM_TARGET_EXTENSION_ID: extensionId,
    I18N_ZOOM_SETUP: setupReportPath,
    I18N_ZOOM_NEXT: nextPath,
    I18N_ZOOM_READY: readyPath,
    I18N_ZOOM_DONE: donePath,
    I18N_ZOOM_PROJECT_PATH: workspaceDir,
  },
  timeout: 120_000,
});

const screenshot = async (page, name) => {
  const file = path.join(outDir, `${name}.png`);
  await page.screenshot({ path: file, timeout: 40_000 });
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
        if (text.trim().length > 0 && /data-trainer|trainer/i.test(await candidate.content())) {
          return candidate;
        }
      } catch {
        // loading
      }
    }
    await page.waitForTimeout(800);
  }
  throw new Error("Trainer webview frame not found");
};
const clickLabel = async (frame, label) => {
  const buttons = frame.locator("button, a");
  const count = await buttons.count();
  for (let index = 0; index < count; index += 1) {
    const candidate = buttons.nth(index);
    const text = ((await candidate.innerText().catch(() => "")) || "").trim();
    if (text === label) {
      await candidate.click();
      return true;
    }
  }
  return false;
};
const measureOverflow = (frame) =>
  frame.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    bodyScrollWidth: document.body ? document.body.scrollWidth : 0,
  }));

try {
  const page = await app.firstWindow({ timeout: 120_000 });
  await page.waitForTimeout(8000);
  const deadline = Date.now() + 180_000;
  while (!fs.existsSync(setupReportPath) && Date.now() < deadline) {
    await page.waitForTimeout(1500);
  }
  if (!fs.existsSync(setupReportPath)) throw new Error("Driver setup report missing.");
  const setup = JSON.parse(fs.readFileSync(setupReportPath, "utf8"));
  record("setup", { ok: setup.ok === true, zoomLevel: setup.zoomLevel, steps: setup.steps, error: setup.error });
  if (!setup.ok) throw new Error(`Driver setup failed: ${setup.error || "unknown"}`);

  await commandPalette(page, "Trainer: Open Coach Sidebar");
  await page.waitForTimeout(5000);
  const frame = await findFrame(page);

  for (const language of LANGUAGES) {
    fs.writeFileSync(nextPath, JSON.stringify({ lang: language.code }));
    const readyDeadline = Date.now() + 60_000;
    while (!fs.existsSync(readyPath) && Date.now() < readyDeadline) {
      await page.waitForTimeout(400);
    }
    if (!fs.existsSync(readyPath)) throw new Error(`Language switch timed out: ${language.code}`);
    const ready = JSON.parse(fs.readFileSync(readyPath, "utf8"));
    fs.unlinkSync(readyPath);
    await page.waitForTimeout(1500);

    const overflow = {};
    for (const view of ["coach", "plan", "resources"]) {
      const clicked = await clickLabel(frame, language[view]);
      await page.waitForTimeout(600);
      overflow[view] = { clicked, ...(await measureOverflow(frame)) };
    }
    await clickLabel(frame, language.resources);
    await page.waitForTimeout(700);
    const bodyText = (await frame.locator("body").innerText()).replace(/\s+/g, " ").trim();
    const navMetrics = await frame.evaluate(() =>
      Array.from(document.querySelectorAll(".app-shell-nav__item")).map((element) => {
        const range = document.createRange();
        range.selectNodeContents(element);
        const tops = new Set(
          Array.from(range.getClientRects()).map((rect) => Math.round(rect.top)),
        );
        return {
          text: (element.textContent || "").trim(),
          lines: tops.size,
          height: element.getBoundingClientRect().height,
        };
      }),
    );
    const navSingleLine =
      navMetrics.length === 3 && navMetrics.every((entry) => entry.lines === 1);
    record("language", {
      ok:
        ready.ok === true &&
        overflow.resources.clicked === true &&
        overflow.coach.clicked === true &&
        overflow.plan.clicked === true &&
        Object.values(overflow).every((entry) => entry.scrollWidth <= entry.clientWidth + 1) &&
        navSingleLine &&
        bodyText.includes(language.resources),
      language: language.code,
      labels: { resources: language.resources, coach: language.coach, plan: language.plan },
      overflow,
      navMetrics,
      navSingleLine,
      text: bodyText.slice(0, 300),
      screenshot: await screenshot(page, `zoom200-${language.code}`),
    });
    fs.writeFileSync(donePath, "done");
    await page.waitForTimeout(500);
  }
} catch (error) {
  record("fatal", { ok: false, error: error instanceof Error ? error.stack : String(error) });
} finally {
  try {
    await app.close();
  } catch {
    // evidence stays
  }
}

const failures = results.filter((item) => item.ok === false);
const report = {
  stamp,
  vsixPath,
  extensionId,
  zoomLevel: 4,
  isolatedProfile: { userDataDir, extensionsDir, workspaceDir },
  results,
  failures: failures.length,
  ok: failures.length === 0 && results.filter((item) => item.step === "language").length === 8,
  artifacts: { screenshots: fs.readdirSync(outDir).filter((name) => name.endsWith(".png")) },
};
fs.writeFileSync(path.join(outDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ ok: report.ok, outDir: path.relative(repoRoot, outDir), failures }, null, 2));
process.exit(report.ok ? 0 : 1);
