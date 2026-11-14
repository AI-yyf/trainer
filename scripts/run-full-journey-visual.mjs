#!/usr/bin/env node
/**
 * Visual leg of the full teaching journey: real VS Code + real workbench.
 *
 * Boots an isolated profile with the packaged VSIX, saves the provider via
 * trainer.provider.save — real PROBE_* credentials when present, otherwise a
 * local scripted stub whose reply is deliberately formula-laden (declared in
 * every record; it proves the KaTeX render pipeline, not model quality).
 * Sends the formula question in Coach, screenshots the rendered reply and the
 * Learning route at two widths, and asserts no raw LaTeX and no visible
 * KaTeX MathML twin anywhere.
 *
 * Evidence: <JOURNEY_OUT_DIR | output/maturity/full-journey-visual-<stamp>>/
 *   13-visual-katex.json + report.json + 13a/13b/13c screenshots
 */
import { spawnSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron } from "playwright";
import { requireVSCodeElectronBinary } from "./vscode-electron.mjs";
import { withVsixE2EFixtureLoopbackBypass } from "../extension/scripts/vsix-e2e-provider-runtime.mjs";
import { resolveVsixOutputPath } from "../extension/scripts/package-vsix.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const extensionDir = path.join(repoRoot, "extension");
const packageJson = JSON.parse(fs.readFileSync(path.join(extensionDir, "package.json"), "utf8"));
const extensionId = `${packageJson.publisher}.${packageJson.name}`;
const vsixPath = resolveVsixOutputPath({ extensionDir, packageJson });
const codeCli = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code";
const electronBinary = requireVSCodeElectronBinary();
if (!fs.existsSync(vsixPath)) {
  throw new Error(`Packaged VSIX not found: ${vsixPath}. Run npm run package:vsix first.`);
}

const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir =
  process.env.JOURNEY_OUT_DIR ??
  path.join(repoRoot, "output/maturity", `full-journey-visual-${stamp}`);
fs.mkdirSync(outDir, { recursive: true });

const realBaseUrl = process.env.PROBE_PROVIDER_BASE_URL ?? "";
const realApiKey = process.env.PROBE_PROVIDER_API_KEY ?? "";
const realModel = process.env.PROBE_PROVIDER_MODEL ?? "MiniMax-M3.1-Flash";
const usingRealProvider = Boolean(realBaseUrl && realApiKey);

// Formula-laden scripted reply for the no-key mode. It exists so the render
// pipeline can be verified without credentials; the report labels it.
const STUB_REPLY = [
  "好的，我们把裁剪目标拆开看。",
  "$$L^{CLIP}(\\theta)=\\hat{\\mathbb{E}}_t\\left[\\min\\left(r_t(\\theta)\\hat{A}_t,\\ \\mathrm{clip}(r_t(\\theta),1-\\epsilon,1+\\epsilon)\\hat{A}_t\\right)\\right]$$",
  "其中比值 $r_t(\\theta)=\\frac{\\pi_\\theta(a_t|s_t)}{\\pi_{\\theta_{old}}(a_t|s_t)}$ 把新旧策略拉到同一尺度：",
  "当 $\\hat{A}_t>0$ 时，优势动作的收益被 $1+\\epsilon$ 封顶；当 $\\hat{A}_t<0$ 时，惩罚被 $1-\\epsilon$ 封顶。",
].join("\n");

let stubServer = null;
let stubBaseUrl = "";
function startStubProvider() {
  stubServer = http.createServer((request, response) => {
    const url = request.url ?? "";
    if ((request.method ?? "").toUpperCase() === "GET" && url.includes("/models")) {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ data: [{ id: "structural-stub" }] }));
      return;
    }
    if (!url.includes("/chat/completions")) {
      response.writeHead(404, { "content-type": "application/json" });
      response.end(JSON.stringify({ error: "visual stub: not found" }));
      return;
    }
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      let stream = false;
      try {
        const body = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
        stream = Boolean(body?.stream);
      } catch { /* default to non-stream */ }
      const created = Math.floor(Date.now() / 1000);
      if (stream) {
        response.writeHead(200, { "content-type": "text/event-stream" });
        const delta = {
          id: "visual-stub-chunk",
          object: "chat.completion.chunk",
          created,
          model: "structural-stub",
          choices: [{ index: 0, delta: { content: STUB_REPLY }, finish_reason: null }],
        };
        response.write(`data: ${JSON.stringify(delta)}\n\n`);
        response.write(
          `data: ${JSON.stringify({
            ...delta,
            choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
          })}\n\n`,
        );
        response.write("data: [DONE]\n\n");
        response.end();
        return;
      }
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({
          id: "visual-stub-completion",
          object: "chat.completion",
          created,
          model: "structural-stub",
          choices: [
            { index: 0, message: { role: "assistant", content: STUB_REPLY }, finish_reason: "stop" },
          ],
          usage: { prompt_tokens: 24, completion_tokens: 96, total_tokens: 120 },
        }),
      );
    });
  });
  return new Promise((resolve) => {
    stubServer.listen(0, "127.0.0.1", () => {
      stubBaseUrl = `http://127.0.0.1:${stubServer.address().port}`;
      resolve(stubBaseUrl);
    });
  });
}
async function stopStubProvider() {
  if (!stubServer) return;
  const server = stubServer;
  stubServer = null;
  await new Promise((done) => server.close(() => done()));
}

const providerApiKey = usingRealProvider ? realApiKey : "structural-stub-key";
const providerModel = usingRealProvider ? realModel : "structural-stub";
const providerLabel = usingRealProvider
  ? `real provider (${realModel})`
  : "local scripted stub (formula-laden reply; render pipeline only)";

// macOS caps unix socket paths (~104 chars); VS Code puts its main IPC sock
// under <profile>/user-data/, so the profile root must stay short. $TMPDIR on
// this machine is deep enough to blow the limit (listen EINVAL at startup).
const root = fs.mkdtempSync("/tmp/fjv-");
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

// Provision the trainer workspace + seed the workspace-root memento so the
// sidebar is fully functional on a fresh profile (verify-coach-gui pattern).
(function provisionTrainerWorkspace() {
  const directories = [
    "Projects", "Knowledge", "Skills", "Agents", "Assets",
    ".trainer", path.join(".trainer", "memory"), path.join(".trainer", "plans"),
    path.join(".trainer", "indexes"), path.join(".trainer", "checkpoints"),
    path.join(".trainer", "logs"), path.join(".trainer", "cache"),
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
})();

function readMemento(value) {
  if (value === undefined || value === null) return undefined;
  try {
    return JSON.parse(typeof value === "string" ? value : Buffer.from(value).toString("utf8"));
  } catch {
    return undefined;
  }
}
(function seedTrainerWorkspaceRoot() {
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
})();

(function writeDriverExtension() {
  fs.writeFileSync(
    path.join(driverDir, "package.json"),
    `${JSON.stringify(
      {
        name: "trainer-full-journey-visual-driver",
        displayName: "Trainer Full Journey Visual Driver",
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
  const reportPath = process.env.FJ_VISUAL_REPORT;
  const targetId = process.env.FJ_VISUAL_TARGET_EXTENSION_ID;
  const provider = JSON.parse(process.env.FJ_VISUAL_PROVIDER || "{}");
  const report = { ok: false, steps: [] };
  try {
    const target = vscode.extensions.getExtension(targetId);
    if (!target) throw new Error("Trainer extension not installed: " + targetId);
    await target.activate();
    await sleep(12000);
    const admitted = await vscode.commands.executeCommand("trainer.workspace.adoptProject", {
      projectPath: process.env.FJ_VISUAL_PROJECT_PATH || undefined,
    });
    report.steps.push({ step: "admit-project", ok: Boolean(admitted && admitted.ok), message: admitted && admitted.message });
    await sleep(1500);
    const saved = await vscode.commands.executeCommand("trainer.provider.save", {
      ...(provider.payload || {}),
      name: provider.name || "journey",
      protocol: provider.protocol || "openai_chat_completions_compatible",
      baseUrl: provider.baseUrl,
      model: provider.model,
      apiKey: provider.apiKey,
      replaceApiKey: true,
    });
    report.steps.push({
      step: "save-provider",
      ok: Boolean(saved && saved.ok),
      message: saved && saved.message,
      // baseUrl/model are loopback identifiers, not secrets; the key is never
      // echoed into the report.
      diag: {
        env_provider_present: Boolean(process.env.FJ_VISUAL_PROVIDER),
        base_url: provider.baseUrl || "",
        model: provider.model || "",
        protocol: provider.protocol || "",
      },
    });
    await sleep(1000);
    const settings = await vscode.commands.executeCommand("trainer.memory.saveCoachSettings", {
      responseLanguage: "zh-CN",
      answerMode: "coach-first",
    });
    report.steps.push({ step: "coach-settings", ok: Boolean(settings && settings.ok) });
    report.ok = report.steps.every((step) => step.ok !== false);
  } catch (error) {
    report.error = error instanceof Error ? error.stack : String(error);
  } finally {
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  }
}

exports.activate = activate;
`,
  );
})();

function runCode(args) {
  const result = spawnSync(codeCli, args, { stdio: "ignore", timeout: 120_000 });
  if (result.status !== 0) {
    throw new Error(`code CLI failed (${result.status}) for: ${args.join(" ")}`);
  }
}

async function main() {
  // Resolved here: the stub binds inside startStubProvider() before main() is
  // entered, so the base URL is only correct at call time.
  const providerBaseUrl = usingRealProvider ? realBaseUrl : stubBaseUrl;
  const results = [];
  const record = (step, payload) => {
    results.push({ step, ...payload });
    fs.writeFileSync(
      path.join(outDir, "13-visual-katex.json"),
      `${JSON.stringify({ provider: providerLabel, vsixPath, results }, null, 2)}\n`,
    );
    console.log(`[visual] ${step}`, JSON.stringify(payload).slice(0, 240));
  };
  const screenshot = async (page, name) => {
    const file = path.join(outDir, `${name}.png`);
    await page.screenshot({ path: file, timeout: 60_000 });
    return path.relative(repoRoot, file);
  };

  runCode(["--user-data-dir", userDataDir, "--extensions-dir", extensionsDir, "--install-extension", vsixPath, "--force"]);

  const launchEnv = withVsixE2EFixtureLoopbackBypass({
    ...process.env,
    FJ_VISUAL_REPORT: reportPath,
    FJ_VISUAL_TARGET_EXTENSION_ID: extensionId,
    FJ_VISUAL_PROJECT_PATH: workspaceDir,
    // The provider config (with the key) travels only through the process
    // environment of the extension host — never into repo files, logs or
    // screenshots.
    FJ_VISUAL_PROVIDER: JSON.stringify({
      name: "journey",
      protocol: "openai_chat_completions_compatible",
      baseUrl: providerBaseUrl,
      model: providerModel,
      apiKey: providerApiKey,
    }),
  });

  launchEnv.TRAINER_FILE_STORE_ROOT = path.join(root, "file-store");
  const app = await _electron.launch({
    executablePath: electronBinary,
    args: [
      "--user-data-dir", userDataDir,
      "--extensions-dir", extensionsDir,
      "--disable-workspace-trust",
      "--skip-welcome",
      "--skip-release-notes",
      "--extensionDevelopmentPath", driverDir,
      "--new-window", workspaceDir,
    ],
    env: launchEnv,
    timeout: 120_000,
  });
  // Capture the app's own stdout/stderr so an early exit is diagnosable.
  const appLog = path.join(outDir, "visual-vscode.log");
  const appProcess = app.process();
  appProcess.stdout?.on("data", (c) => fs.appendFileSync(appLog, c));
  appProcess.stderr?.on("data", (c) => fs.appendFileSync(appLog, c));

  let page = null;
  const windowDeadline = Date.now() + 180_000;
  while (!page && Date.now() < windowDeadline) {
    try {
      page = await app.firstWindow({ timeout: 15_000 });
    } catch {
      if (appProcess.exitCode !== null) {
        throw new Error(
          `VS Code exited early (code=${appProcess.exitCode}); log: ${appLog} — ` +
            fs.readFileSync(appLog, "utf8").slice(-2000),
        );
      }
    }
  }
  if (!page) throw new Error("No VS Code window appeared within 180s.");

  try {
    await page.waitForTimeout(8000);
    const deadline = Date.now() + 180_000;
    while (!fs.existsSync(reportPath) && Date.now() < deadline) {
      await page.waitForTimeout(2000);
    }
    if (!fs.existsSync(reportPath)) throw new Error("Driver never wrote its report.");
    const driverReport = JSON.parse(fs.readFileSync(reportPath, "utf8"));
    record("driver-report", {
      ok: driverReport.ok === true,
      // Never echo the provider payload back into evidence.
      steps: driverReport.steps,
      error: driverReport.error,
    });
    if (!driverReport.ok) throw new Error(`Driver setup failed: ${driverReport.error || "unknown"}`);

    await page.keyboard.press("Meta+Shift+P");
    await page.waitForTimeout(700);
    await page.keyboard.type("Trainer: Open Coach Sidebar");
    await page.waitForTimeout(700);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(7000);

    const findFrame = async (timeout = 60_000) => {
      const start = Date.now();
      while (Date.now() - start < timeout) {
        for (const candidate of page.frames()) {
          if (!candidate.url().includes("vscode-webview://")) continue;
          try {
            if (await candidate.getByTestId("trainer-view-nav-coach").isVisible()) return candidate;
          } catch { /* still loading */ }
        }
        await page.waitForTimeout(800);
      }
      throw new Error("Trainer webview frame not found");
    };
    const frame = await findFrame();
    const composer = frame.locator("#coach-composer").first();
    await composer.waitFor({ timeout: 30_000 });
    const prompt =
      "请写出 PPO 裁剪目标的公式，并逐项解释 r_t、A_t 和 clip 各自限制了什么。";
    await composer.fill(prompt);
    await composer.press("Enter");
    await page.waitForTimeout(500);

    const waitForReply = async (timeout = 180_000) => {
      const start = Date.now();
      while (Date.now() - start < timeout) {
        const busy = await frame.locator(".coach-working, .agent-activity-strip").count();
        const assistant = await frame.locator('article[data-role="assistant"] .katex').count();
        if (busy === 0 && assistant > 0) return true;
        await page.waitForTimeout(800);
      }
      return false;
    };
    const replied = await waitForReply();
    await page.waitForTimeout(3000);
    const coachBody = (await frame.locator("body").innerText()).replace(/\s+/g, " ").trim();
    const coachRawLatex = /\\pi_\theta|\\frac|\\operatorname|L\^\{CLIP\}\(\\theta\)/.test(coachBody);
    record("13a-coach-formula-reply", {
      ok: replied && coachBody.length > 40 && !coachRawLatex,
      provider: providerLabel,
      replied,
      reply_chars: coachBody.length,
      has_raw_latex: coachRawLatex,
      preview: coachBody.slice(0, 300),
      screenshot: await screenshot(page, "13a-coach-formula"),
    });

    const mathTwinFacts = await frame.evaluate(() => {
      // The f79dc47 defense clips each KaTeX MathML twin to a 1px absolute
      // box (screen-reader accessible, visually inert). "Visible" therefore
      // means anything bigger than that clipped box.
      const twins = [...document.querySelectorAll(".katex-mathml")];
      const visible = twins.filter((node) => {
        const style = getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        const clipped =
          (style.clip || "").includes("1px") ||
          (Number.parseInt(style.width, 10) || 0) <= 2 ||
          (Number.parseInt(style.height, 10) || 0) <= 2;
        const onScreen =
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          rect.width > 2 &&
          rect.height > 2;
        return onScreen && !clipped;
      });
      return {
        mathml_total: twins.length,
        mathml_visible: visible.length,
        katex_rendered: document.querySelectorAll(".katex").length,
      };
    });
    record("13a2-katex-mathml-defense", {
      ok: mathTwinFacts.katex_rendered > 0 && mathTwinFacts.mathml_visible === 0,
      facts: mathTwinFacts,
    });

    await frame.getByTestId("trainer-view-nav-plan").click();
    await frame.locator('[data-template="LearningHome"]:visible').first().waitFor();
    await page.waitForTimeout(4000);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.waitForTimeout(2500);
    const wideBody = (await frame.locator("body").innerText()).replace(/\s+/g, " ").trim();
    const wideSidebar = await frame.evaluate(() => innerWidth);
    const wideRawLatex = /\\pi_\theta|\\frac|\\operatorname/.test(wideBody);
    record("13b-learning-wide", {
      ok: !wideRawLatex,
      window_width: 1280,
      sidebar_width: wideSidebar,
      has_raw_latex: wideRawLatex,
      text_head: wideBody.slice(0, 300),
      screenshot: await screenshot(page, "13b-learning-wide"),
    });

    await page.setViewportSize({ width: 400, height: 900 });
    await page.waitForTimeout(3000);
    const narrowBody = (await frame.locator("body").innerText()).replace(/\s+/g, " ").trim();
    const narrowSidebar = await frame.evaluate(() => innerWidth);
    const narrowRawLatex = /\\pi_\theta|\\frac|\\operatorname/.test(narrowBody);
    record("13c-learning-narrow", {
      ok: !narrowRawLatex && narrowSidebar <= wideSidebar,
      window_width: 400,
      sidebar_width: narrowSidebar,
      has_raw_latex: narrowRawLatex,
      text_head: narrowBody.slice(0, 300),
      screenshot: await screenshot(page, "13c-learning-narrow"),
    });

    await page.setViewportSize({ width: 1280, height: 900 });
    await frame.getByTestId("trainer-view-nav-resources").click();
    const library = frame.locator('[data-resource-library-container="true"]');
    await library.waitFor();
    const resourcesFacts = await library.evaluate((element) => ({
      width: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      restoresBanner: Boolean(element.querySelector(".resources-inline-context")),
    }));
    record("13d-resources-library", {
      ok: !resourcesFacts.restoresBanner && resourcesFacts.scrollWidth <= resourcesFacts.width + 1,
      facts: resourcesFacts,
      screenshot: await screenshot(page, "13d-resources-library"),
    });

    await frame.getByTestId("trainer-view-nav-settings").click();
    await frame.locator('[data-settings-category="teaching"]').click();
    const habit = frame.locator(".settings-coach-habit");
    const habitInput = habit.locator("input");
    const demoHabit = "先给一个最小例子，再讲公式";
    await habitInput.fill(demoHabit);
    await habit.getByRole("button", { name: "保存", exact: true }).click();
    const disable = habit.getByRole("button", { name: "停用", exact: true });
    const enable = habit.getByRole("button", { name: "启用", exact: true });
    await disable.click();
    await enable.waitFor();
    const retained = await habitInput.inputValue();
    const settingsScreenshot = await screenshot(page, "13e-coach-habit-disabled");
    await enable.click();
    await disable.waitFor();
    const forget = habit.getByRole("button", { name: "忘记", exact: true });
    await forget.click();
    await forget.waitFor({ state: "detached" });
    record("13e-coach-habit", {
      ok: retained === demoHabit && await habitInput.inputValue() === "",
      screenshot: settingsScreenshot,
    });
  } finally {
    try {
      await app.close();
    } catch { /* evidence stays */ }
  }

  const failures = results.filter((item) => item.ok === false);
  const report = {
    generatedAt: new Date().toISOString(),
    provider: providerLabel,
    vsixPath,
    using_real_provider: usingRealProvider,
    results,
    failures: failures.length,
    ok: failures.length === 0 && results.length === 7,
    artifacts: fs.readdirSync(outDir).filter((name) => name.endsWith(".png")),
  };
  fs.writeFileSync(path.join(outDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
  console.log(`${report.ok ? "FULL_JOURNEY_VISUAL_OK" : "FULL_JOURNEY_VISUAL_FAILED"} ${outDir}`);
  return report.ok;
}

try {
  if (!usingRealProvider) await startStubProvider();
  const ok = await main();
  process.exitCode = ok ? 0 : 1;
} catch (error) {
  console.error("FULL_JOURNEY_VISUAL_FAILED", error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
} finally {
  await stopStubProvider();
  fs.rmSync(root, { recursive: true, force: true });
}
