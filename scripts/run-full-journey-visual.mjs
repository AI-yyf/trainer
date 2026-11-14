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
 * TRAINER_VISUAL_RECALL_SOURCE_DIR optionally points to a completed API
 * journey with an original passing implementation and recall response.
 * The installed host creates and verifies a fresh card, then the workbench
 * drives the scheduled answer and the script checks the actual database.
 *
 * Evidence lives in JOURNEY_OUT_DIR or output/maturity/full-journey-visual-<stamp>.
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
const recallSourceDir = process.env.TRAINER_VISUAL_RECALL_SOURCE_DIR?.trim();
const checkStreamRecovery = process.env.TRAINER_VISUAL_STREAM_RECOVERY === "1";
if (recallSourceDir && !usingRealProvider) {
  throw new Error("The scheduled-recall visual journey requires the real provider.");
}
if (checkStreamRecovery && usingRealProvider) {
  throw new Error("The stream recovery probe needs a local upstream whose connection the test can interrupt.");
}
let recallSource;
if (recallSourceDir) {
  const verification = JSON.parse(fs.readFileSync(path.join(recallSourceDir, "07-verify-current-file.json"), "utf8"));
  const attempts = verification.grading_attempts;
  const passingAttempt = Array.isArray(attempts) ? attempts.findIndex((attempt) => attempt.passed === true) : -1;
  const answer = fs.readFileSync(path.join(recallSourceDir, "11-recall-answer-raw.txt"), "utf8").trim();
  if (passingAttempt < 0 || !answer) throw new Error("The API journey has no passing implementation or recall response.");
  recallSource = { implementation: path.resolve(recallSourceDir, `06-submitted-${passingAttempt + 1}.py`), answer };
}

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
const interruptPrompt = "请讲解这个代码示例，保留空行、公式和表格。";
const interruptPrefix = [
  "代码示例包含两个步骤。",
  "```python\nfirst = 1\n\nsecond = first + 1\n```",
  "其中 $x + 1$ 对应第二步。",
  "| 步骤 | 值 |\n| --- | --- |\n| 一 | 1 |\n| 二 | 2 |",
  "更多说明会单独列出。".repeat(20),
].join("\n\n");
const recoveryPrompt = "请继续讲解第二步，给出一个新的小例子。";
const recoveryReply = "第二步使用第一步的结果。例如第一步得到 3，第二步得到 4。";
const heldStreams = [];
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
      let body;
      try {
        body = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
      } catch (error) {
        response.writeHead(400);
        response.end(String(error));
        return;
      }
      const created = Math.floor(Date.now() / 1000);
      const userText = JSON.stringify(body?.messages?.findLast((message) => message.role === "user")?.content ?? "");
      const holdOpen = checkStreamRecovery && body?.stream && userText.includes(interruptPrompt);
      const reply = holdOpen ? interruptPrefix : userText.includes(recoveryPrompt) ? recoveryReply : STUB_REPLY;
      if (body?.stream) {
        response.writeHead(200, { "content-type": "text/event-stream" });
        const delta = {
          id: "visual-stub-chunk",
          object: "chat.completion.chunk",
          created,
          model: "structural-stub",
          choices: [{ index: 0, delta: { content: reply }, finish_reason: null }],
        };
        if (holdOpen) {
          const held = { response, closed: false, initialContentSent: false };
          heldStreams.push(held);
          response.once("close", () => { held.closed = true; });
          // Split the fence, its blank line, the formula and the table across SSE events.
          for (const content of reply.match(/.{1,23}|\n/gu)) {
            response.write(`data: ${JSON.stringify({ ...delta, choices: [{ index: 0, delta: { content }, finish_reason: null }] })}\n\n`);
          }
          held.initialContentSent = true;
          return;
        }
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
            { index: 0, message: { role: "assistant", content: reply }, finish_reason: "stop" },
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
  for (const { response } of heldStreams) response.destroy();
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
const recallRequestPath = path.join(root, "recall-request.json");
const recallStatePath = path.join(root, "recall-state.json");
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
const path = require("node:path");
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
    const waitForSidecar = async () => {
      for (let attempt = 0; attempt < 150; attempt++) {
        const state = target.exports?.getDebugState?.().sidecar;
        if (state?.lifecycle === "ready") return;
        if (state?.lifecycle === "error") throw new Error(state.detail || "Sidecar failed to start.");
        await sleep(1000);
      }
      throw new Error("The isolated VS Code sidecar did not become ready.");
    };
    await waitForSidecar();
    const adoptProject = () => vscode.commands.executeCommand("trainer.workspace.adoptProject");
    let admitted = await adoptProject();
    if (!admitted?.ok && /workspace changed/i.test(admitted?.message || "")) {
      await waitForSidecar();
      admitted = await adoptProject();
    }
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
    if (process.env.TRAINER_VISUAL_STREAM_RECOVERY === "1") {
      const state = target.exports.getDebugState();
      const dataDir = state.bootstrap?.memory?.workspace?.resourceSandbox?.effectivePath;
      if (!dataDir) throw new Error("Missing the isolated database for stream recovery.");
      report.steps.push({ step: "stream-database", ok: true, database: path.join(dataDir, "trainer.sqlite3") });
    }
    if (process.env.FJ_VISUAL_IMPLEMENTATION) {
      const focus = "PPO 裁剪目标";
      const generate = () => vscode.commands.executeCommand("trainer.training.generateCard", {
        source: "conversation_gap", cardType: "practice", focusArea: focus,
        targetSkill: "解释 PPO clip 目标并手写损失函数",
        prompt: "请用 Python 标准库实现接收新旧对数概率列表、优势列表和裁剪阈值，返回逐项裁剪目标负均值的 PPO 损失函数。",
      });
      let generated = await generate();
      if (!generated?.ok && /provider request failed|timed out|temporarily unavailable/i.test(generated?.message || "")) {
        report.steps.push({ step: "retry-card-generation", reason: generated.message });
        await sleep(3000);
        generated = await generate();
      }
      const card = generated?.data?.card;
      if (!generated?.ok || card?.python_behavior_contract?.reference_id !== "trainer/ppo-clipped-loss/v1") {
        throw new Error("Native card generation did not create the reviewed practice contract. " + (generated?.message || ""));
      }
      const file = vscode.Uri.joinPath(vscode.workspace.workspaceFolders[0].uri, "ppo_clip_loss.py");
      fs.copyFileSync(process.env.FJ_VISUAL_IMPLEMENTATION, file.fsPath);
      await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(file));
      const verified = await vscode.commands.executeCommand("trainer.evaluate.currentFile", {
        source: "training", trainingPhase: "verify", cardId: card.card_id,
        filesToTouch: ["ppo_clip_loss.py"],
      });
      if (!verified?.data?.passed || verified.data.verification_scope !== "behavior") {
        throw new Error("Native verification failed. " + (verified?.data?.summary || verified?.message || ""));
      }
      const initialHostState = target.exports.getDebugState();
      const dataDir = initialHostState.bootstrap?.memory?.workspace?.resourceSandbox?.effectivePath;
      const workspaceId = initialHostState.bootstrap?.workspaceTrainingState?.workspaceId;
      if (!dataDir || !workspaceId || !card.question) throw new Error("Native state is missing the reviewed card or its data folder.");
      const beforeRestartPid = initialHostState.sidecar.pid;
      process.env.TRAINER_TEST_NOW = new Date(Date.now() + 2 * 86400000).toISOString();
      const restarted = await vscode.commands.executeCommand("trainer.sidecar.restart");
      if (!restarted?.ok) throw new Error("Could not restart the installed sidecar.");
      report.steps.push({ step: "prepare-scheduled-recall", ok: true, cardId: card.card_id,
        question: card.question, workspaceId, database: path.join(dataDir, "trainer.sqlite3"),
        clock: process.env.TRAINER_TEST_NOW,
        newSidecar: beforeRestartPid !== target.exports.getDebugState().sidecar.pid });

      const requestPath = process.env.FJ_VISUAL_RECALL_REQUEST;
      const statePath = process.env.FJ_VISUAL_RECALL_STATE;
      let checking = false;
      const watcher = setInterval(async () => {
        if (checking || !fs.existsSync(requestPath)) return;
        checking = true;
        clearInterval(watcher);
        try {
          const restart = await vscode.commands.executeCommand("trainer.sidecar.restart");
          const state = target.exports.getDebugState();
          const artifact = state.bootstrap?.workspaceTrainingState?.reviewArtifact;
          fs.writeFileSync(statePath, JSON.stringify({
            ok: restart?.ok === true, cardId: artifact?.trainingCardId, reviewId: artifact?.id,
            status: artifact?.status, detail: artifact?.verifiedResult,
          }));
        } catch (error) {
          fs.writeFileSync(statePath, JSON.stringify({ ok: false, error: String(error) }));
        }
      }, 500);
    }
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
    FJ_VISUAL_IMPLEMENTATION: recallSource?.implementation ?? "",
    FJ_VISUAL_RECALL_REQUEST: recallRequestPath,
    FJ_VISUAL_RECALL_STATE: recallStatePath,
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
    const deadline = Date.now() + (recallSource ? 600_000 : 180_000);
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
    if (recallSource) {
      const seeded = driverReport.steps.find((item) => item.step === "prepare-scheduled-recall");
      if (!seeded?.newSidecar) throw new Error("The installed sidecar did not restart before review.");
      const readPersistedRecall = () => {
        const database = new DatabaseSync(seeded.database, { readOnly: true });
        try {
          const memory = JSON.parse(database.prepare(
            "SELECT payload FROM structured_memory WHERE workspace_id = ?",
          ).get(seeded.workspaceId).payload);
          return {
            schedule: memory.workspace.latest_training_fsrs_states[seeded.cardId],
            review: memory.review_artifact,
            answer: memory.recent_flash_attempts.find((attempt) => attempt.card_id === seeded.cardId),
          };
        } finally {
          database.close();
        }
      };
      const before = readPersistedRecall();
      if (before.schedule?.reps !== 0) throw new Error("The verified practice must have an unreviewed FSRS schedule.");
      await frame.getByTestId("trainer-view-nav-plan").click();
      const learning = frame.locator('[data-template="LearningHome"]:visible');
      await learning.waitFor();
      const more = learning.locator("[data-learning-focus-more]").first();
      const startReview = learning.getByRole("button", { name: "开始复习", exact: true }).filter({ visible: true });
      if (!(await startReview.count()) && await more.count() && (await more.getAttribute("open")) === null) {
        await more.locator(":scope > summary").click();
      }
      try {
        await startReview.click({ timeout: 12_000 });
      } catch (error) {
        record("13f-native-review-entry", {
          ok: false, title: await learning.innerText(),
          screenshot: await screenshot(page, "13f-native-review-entry-missing"),
        });
        throw error;
      }
      const queue = frame.locator("[data-training-review-queue=true]");
      await queue.waitFor();
      const reviewRow = queue.locator(".training-review-row").filter({
        has: frame.getByRole("heading", { name: before.schedule.concept_id, exact: true }),
      });
      await reviewRow.locator(".training-review-row__actions-details > summary").click();
      await reviewRow.getByRole("button", { name: "开始复习", exact: true }).click();
      const form = frame.locator('[data-template="PracticeResponse"]').filter({ hasText: seeded.question });
      const submit = form.getByRole("button", { name: "提交回答", exact: true });
      await submit.waitFor({ timeout: 30_000 });
      const promptImage = await screenshot(page, "13f-native-scheduled-recall-question");
      const receipt = frame.getByText("复习已记录", { exact: true });
      const pending = form.getByText(/答案已保存，正确性尚未确认/).filter({ visible: true });
      const answerInput = form.getByRole("textbox");
      try {
        await answerInput.fill(recallSource.answer);
        await submit.click();
        await receipt.or(pending).first().waitFor({ timeout: 75_000 });
        if (await pending.count()) {
          const unconfirmed = readPersistedRecall();
          const draftRetained = await answerInput.inputValue() === recallSource.answer;
          record("13f1-native-recall-unconfirmed", {
            ok: unconfirmed.review?.status === "active" && unconfirmed.answer?.correct === null &&
              unconfirmed.answer.learner_answer === recallSource.answer &&
              unconfirmed.schedule?.reps === before.schedule.reps && draftRetained,
            reviewStatus: unconfirmed.review?.status,
            feedback: unconfirmed.answer?.feedback,
            draftRetained,
            screenshot: await screenshot(page, "13f1-native-scheduled-recall-unconfirmed"),
          });
          if (!draftRetained) throw new Error("The unconfirmed recall did not retain the learner's draft.");
          await submit.click();
        }
        await receipt.waitFor({ timeout: 75_000 });
      } catch (error) {
        const failed = readPersistedRecall();
        record("13f-native-scheduled-recall", {
          ok: false, reviewStatus: failed.review?.status, reviewedCardId: failed.review?.training_card_id,
          answerRecorded: Boolean(failed.answer?.learner_answer), feedback: failed.answer?.feedback,
          reps: failed.schedule?.reps,
          screenshot: await screenshot(page, "13f-native-scheduled-recall-failed"),
        });
        throw error;
      }
      const after = readPersistedRecall();
      record("13f-native-scheduled-recall", {
        ok: after.review?.training_card_id === seeded.cardId && after.review.status === "resolved" &&
          after.answer?.learner_answer === recallSource.answer && after.answer?.correct === true &&
          after.answer?.feedback?.grading_source === "model_review" && after.schedule?.reps === 1,
        question: seeded.question, cardId: seeded.cardId, reviewId: after.review?.id,
        sameAnswer: after.answer?.learner_answer === recallSource.answer,
        gradingSource: after.answer?.feedback?.grading_source,
        repsBefore: before.schedule.reps, repsAfter: after.schedule?.reps,
        screenshots: [promptImage, await screenshot(page, "13f-native-scheduled-recall-recorded")],
      });
      fs.writeFileSync(recallRequestPath, "{}");
      for (let attempt = 0; attempt < 150 && !fs.existsSync(recallStatePath); attempt++) {
        await page.waitForTimeout(1000);
      }
      const restored = JSON.parse(fs.readFileSync(recallStatePath, "utf8"));
      const restoredSchedule = readPersistedRecall().schedule;
      record("13g-native-scheduled-recall-restored", {
        ...restored, reps: restoredSchedule?.reps,
        ok: restored.ok && restored.cardId === seeded.cardId && restored.reviewId === after.review?.id &&
          restored.status === "resolved" && restoredSchedule?.reps === 1,
      });
      await frame.getByTestId("trainer-view-nav-coach").click();
    }
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

    if (checkStreamRecovery) {
      const databasePath = driverReport.steps.find((step) => step.step === "stream-database").database;
      const readTurns = () => {
        const database = new DatabaseSync(databasePath, { readOnly: true });
        try {
          return database.prepare("SELECT payload FROM sessions").all()
            .map(({ payload }) => JSON.parse(payload).snapshot.messages)
            .find((messages) => messages.some((message) => message.content === prompt)) ?? [];
        } finally {
          database.close();
        }
      };
      const waitFor = async (predicate, description) => {
        const deadline = Date.now() + 15_000;
        while (!await predicate()) {
          if (Date.now() > deadline) throw new Error(`Did not observe ${description}.`);
          await page.waitForTimeout(150);
        }
      };
      const send = async (text) => {
        await composer.fill(text);
        await composer.press("Enter");
      };
      const stop = frame.locator(".composer__send.is-busy");
      const live = frame.locator('[data-message-id="streaming"] .message-markdown').first();
      const partial = frame.locator('[data-template="Conversation"] .message-markdown')
        .filter({ hasText: "代码示例包含两个步骤。" });
      const startHeldTurn = async () => {
        const count = heldStreams.length;
        await send(interruptPrompt);
        await stop.waitFor();
        await waitFor(() => heldStreams.length > count, "the real upstream SSE request");
        return heldStreams.at(-1);
      };

      const cancelled = await startHeldTurn();
      await live.locator("table").waitFor({ timeout: 15_000 }).catch(async (error) => {
        record("13h-streaming-markdown", {
          ok: false, heldOpen: !cancelled.closed, initialContentSent: cancelled.initialContentSent,
          visible: await live.allTextContents(), screenshot: await screenshot(page, "13h-streaming-markdown-missing"),
        });
        throw error;
      });
      const code = await live.locator("pre code").innerText();
      record("13h-streaming-markdown", {
        ok: code.trim() === "first = 1\n\nsecond = first + 1" &&
          await live.locator(".katex-html").count() === 1 && !cancelled.closed,
        screenshot: await screenshot(page, "13h-streaming-markdown"),
      });
      await stop.click();
      await stop.waitFor({ state: "hidden" });
      const interruptedTurns = () => readTurns().filter((message) => message.content === interruptPrompt)
        .map((message) => message.metadata?.stream_state ?? "missing");
      let stopSettled = true;
      try {
        await waitFor(() => cancelled.closed && interruptedTurns()[0] === "cancelled",
          "upstream closure and a persisted cancellation");
      } catch {
        stopSettled = false;
      }
      record("13i-stop-stream", {
        ok: stopSettled && await partial.last().isVisible() && await composer.inputValue() === interruptPrompt,
        partialVisible: await partial.last().isVisible(), upstreamClosed: cancelled.closed, persisted: interruptedTurns(),
        screenshot: await screenshot(page, "13i-stop-stream"),
      });
      if (!stopSettled) cancelled.response.destroy();

      const dropped = await startHeldTurn();
      await live.locator("table").waitFor();
      dropped.response.destroy();
      await stop.waitFor({ state: "hidden" });
      let dropSettled = true;
      try {
        await waitFor(() => interruptedTurns()[1] === "failed", "the persisted network failure");
      } catch {
        dropSettled = false;
      }
      const draft = await composer.inputValue();
      record("13j-dropped-stream", {
        ok: dropSettled && await partial.last().isVisible() && draft === interruptPrompt && dropped.closed,
        partialVisible: await partial.last().isVisible(), draftRestored: draft === interruptPrompt,
        persisted: interruptedTurns(),
        screenshot: await screenshot(page, "13j-dropped-stream"),
      });

      await send(recoveryPrompt);
      await frame.locator('article[data-role="assistant"]').getByText(recoveryReply, { exact: true }).waitFor();
      await stop.waitFor({ state: "hidden" });
      const finalTurns = readTurns();
      record("13k-stream-recovery", {
        ok: finalTurns.filter((message) => message.role === "user" && message.content === recoveryPrompt).length === 1 &&
          finalTurns.filter((message) => message.role === "assistant" && message.content === recoveryReply).length === 1 &&
          !finalTurns.some((message) => message.role === "assistant" && message.content.includes("代码示例包含两个步骤。")) &&
          heldStreams.every((entry) => entry.closed),
        screenshot: await screenshot(page, "13k-stream-recovery"),
      });
    }

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
    ok: failures.length === 0 &&
      results.filter((item) => item.step !== "13f1-native-recall-unconfirmed").length ===
        (recallSource ? 9 : 7) + (checkStreamRecovery ? 4 : 0),
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
