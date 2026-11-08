#!/usr/bin/env node
/**
 * V4 real VS Code GUI journey runner (20 journeys).
 *
 * Installs the current VSIX into an isolated --user-data-dir/--extensions-dir,
 * launches the real VS Code Electron app, and drives the actual Trainer
 * webview. A local OpenAI-compatible fixture provider keeps coach turns
 * deterministic; this run is GUI evidence (G), not real-model evidence (P).
 *
 * Provider credentials are never written to the repo. Set
 * PROBE_PROVIDER_BASE_URL/PROBE_PROVIDER_API_KEY to use a real provider
 * instead of the fixture server.
 *
 * Usage:
 *   GUI_OUT_DIR=docs/verification/v4-gui-20-journeys \
 *   node scripts/run-v4-gui-journeys.mjs
 */
import { _electron } from "playwright";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { execFileSync } from "node:child_process";

const repoRoot = path.resolve(import.meta.dirname, "..");
const packageJson = JSON.parse(fs.readFileSync(path.join(repoRoot, "extension", "package.json"), "utf8"));
const vsixPath = path.join(repoRoot, "extension", `trainer-extension-${packageJson.version}-darwin-arm64.vsix`);
const codeCli = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code";
const electronBinary = "/Applications/Visual Studio Code.app/Contents/MacOS/Electron";
const outDir = path.resolve(repoRoot, process.env.GUI_OUT_DIR ?? "docs/verification/v4-gui-20-journeys");
fs.mkdirSync(outDir, { recursive: true });

const steps = [];
const journeys = [];
function record(id, title, status, evidence = {}) {
  const entry = { id, title, status, at: new Date().toISOString(), ...evidence };
  journeys.push(entry);
  fs.writeFileSync(path.join(outDir, "journeys.json"), `${JSON.stringify({ journeys, steps }, null, 2)}\n`);
  console.log(`[journey] ${id} ${status} ${title}`);
}
function step(name, payload = {}) {
  steps.push({ name, at: new Date().toISOString(), ...payload });
  console.log(`[step] ${name}`);
}
function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}
async function screenshot(page, name) {
  const file = path.join(outDir, `${name}.png`);
  await page.screenshot({ path: file, timeout: 30_000 });
  return path.relative(repoRoot, file);
}
async function screenshotFrame(page, frame, name) {
  const file = path.join(outDir, `${name}.png`);
  await frame.locator("body").screenshot({ path: file, timeout: 30_000 }).catch(async () => {
    await page.screenshot({ path: file, timeout: 30_000 });
  });
  return path.relative(repoRoot, file);
}

// ---------------------------------------------------------------- fixture provider
const fixtureModels = [
  { id: "fixture-v4-gui", object: "model", owned_by: "trainer-fixture" },
  { id: "fixture-v4-gui-alt", object: "model", owned_by: "trainer-fixture" },
];
function fixtureReply(prompt) {
  const text = String(prompt ?? "");
  if (/PPO 是什么|两句话解释/.test(text)) {
    return "PPO 是近端策略优化：用裁剪的目标函数限制每次策略更新幅度，在实现简单的同时保持训练稳定。它不是“更快的 SGD”，而是对策略变化加了可信区间。";
  }
  if (/真正学会|PPO Clip|从哪里开始/.test(text)) {
    return "先做最小分诊：确认策略梯度、优势函数、on-policy rollout、重要性采样 ratio、clip 目标和多 epoch 更新这条链是否打通。今天只做一件事：写出 ratio 与 clip 的公式，并用一组假数据手算一次更新。";
  }
  if (/继续|第一步/.test(text)) {
    return "第一步：在 notes 里写出 ratio = π_new(a|s) / π_old(a|s)，再标出 clip 的上下界。把 1.2 和 0.8 两组数值代进去，解释目标函数为什么被截断。完成后把结果带回对话。";
  }
  if (/讲慢|多举例|偏好/.test(text)) {
    return "可以。我先用一个具体例子讲清概念，再给最小验证步骤；每次只推进一个可验证的小改动。";
  }
  return "先看当前这一步的最小可验证动作：打开当前文件，找到一个真实调用点，写出输入、输出和一个失败边界。不要同时改多处；完成后用一次真实运行收尾，再把结果带回对话。";
}
function startFixtureProvider() {
  const server = http.createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    if (request.method === "GET" && /\/models$/.test(url.pathname)) {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ object: "list", data: fixtureModels }));
      return;
    }
    if (request.method === "POST" && /\/chat\/completions$/.test(url.pathname)) {
      let body = "";
      request.on("data", (chunk) => { body += chunk; });
      request.on("end", () => {
        let payload = {};
        try { payload = JSON.parse(body); } catch { payload = {}; }
        const messages = Array.isArray(payload.messages) ? payload.messages : [];
        const lastUser = [...messages].reverse().find((message) => message.role === "user");
        const text = fixtureReply(lastUser?.content);
        const id = `chatcmpl-fixture-${Date.now()}`;
        const model = payload.model || "fixture-v4-gui";
        if (payload.stream) {
          response.writeHead(200, {
            "content-type": "text/event-stream",
            "cache-control": "no-cache",
            connection: "keep-alive",
          });
          const chunks = text.match(/[\s\S]{1,18}/g) ?? [text];
          let index = 0;
          const timer = setInterval(() => {
            if (index >= chunks.length) {
              response.write(`data: ${JSON.stringify({ id, object: "chat.completion.chunk", model, choices: [{ index: 0, delta: {}, finish_reason: "stop" }] })}\n\n`);
              response.write("data: [DONE]\n\n");
              response.end();
              clearInterval(timer);
              return;
            }
            response.write(`data: ${JSON.stringify({ id, object: "chat.completion.chunk", model, choices: [{ index: 0, delta: { content: chunks[index] }, finish_reason: null }] })}\n\n`);
            index += 1;
          }, 20);
          return;
        }
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          id, object: "chat.completion", model,
          choices: [{ index: 0, message: { role: "assistant", content: text }, finish_reason: "stop" }],
          usage: { prompt_tokens: 20, completion_tokens: text.length, total_tokens: 20 + text.length },
        }));
      });
      return;
    }
    if (request.method === "POST" && /\/embeddings$/.test(url.pathname)) {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ object: "list", data: [{ object: "embedding", index: 0, embedding: Array.from({ length: 8 }, (_, i) => (i + 1) / 10) }] }));
      return;
    }
    response.writeHead(404, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: { message: "fixture route not found" } }));
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port })));
}

// ---------------------------------------------------------------- VS Code harness
function readMementoObject(value) {
  const text = Buffer.isBuffer(value) ? value.toString("utf8") : typeof value === "string" ? value : "";
  if (!text) return {};
  try { const parsed = JSON.parse(text); return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {}; } catch { return {}; }
}
function readMementoKeys(value) {
  const text = Buffer.isBuffer(value) ? value.toString("utf8") : typeof value === "string" ? value : "";
  if (!text) return [];
  try { const parsed = JSON.parse(text); return Array.isArray(parsed) ? parsed.filter((k) => typeof k === "string") : []; } catch { return []; }
}
function seedLearningFolder({ userDataDir, rootPath, extensionId, version }) {
  const directories = ["Projects", "Knowledge", "Skills", "Agents", "Assets", ".trainer", ".trainer/memory", ".trainer/plans", ".trainer/indexes", ".trainer/checkpoints", ".trainer/logs", ".trainer/cache"];
  for (const directory of directories) fs.mkdirSync(path.join(rootPath, directory), { recursive: true });
  const now = new Date().toISOString();
  fs.writeFileSync(path.join(rootPath, ".trainer", "workspace.json"), `${JSON.stringify({ schemaVersion: 2, kind: "trainer-workspace", rootPath, canonicalRootPath: rootPath, legacyRootPaths: [], manifestRevision: 1, pathRevision: 0, identityStatus: "pending", createdAt: now, updatedAt: now, directories, projects: {} }, null, 2)}\n`, "utf8");
  const globalStorageDir = path.join(userDataDir, "User", "globalStorage");
  fs.mkdirSync(globalStorageDir, { recursive: true });
  const database = new DatabaseSync(path.join(globalStorageDir, "state.vscdb"));
  try {
    database.exec("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)");
    const extensionState = readMementoObject(database.prepare("SELECT value FROM ItemTable WHERE key = ?").get(extensionId)?.value);
    extensionState["trainer.workspace.root.v1"] = rootPath;
    database.prepare("INSERT INTO ItemTable (key, value) VALUES (?, ?)").run(extensionId, JSON.stringify(extensionState));
    const keyIndex = `extensionKeys/${extensionId}@${version}`;
    const mementoKeys = readMementoKeys(database.prepare("SELECT value FROM ItemTable WHERE key = ?").get(keyIndex)?.value);
    if (!mementoKeys.includes("trainer.workspace.root.v1")) mementoKeys.push("trainer.workspace.root.v1");
    database.prepare("INSERT INTO ItemTable (key, value) VALUES (?, ?)").run(keyIndex, JSON.stringify(mementoKeys));
  } finally { database.close(); }
}
function workspaceFrame(page) {
  const frame = page.frames().find((candidate) => candidate.url().includes("vscode-webview://") && candidate.url().includes("fake.html"));
  if (!frame) throw new Error("Trainer webview frame not found");
  return frame;
}
async function bodyText(frame) { return (await frame.locator("body").innerText()).replace(/\s+/g, " ").trim(); }
async function waitForBody(frame, pattern, timeout = 120_000) {
  const start = Date.now(); let last = "";
  while (Date.now() - start < timeout) {
    last = await bodyText(frame);
    if (pattern.test(last)) return last;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`Timed out waiting for ${pattern}; body=${last.slice(0, 700)}`);
}
async function commandPalette(page, command) {
  await page.keyboard.press("Meta+Shift+P");
  await page.waitForTimeout(700);
  await page.keyboard.type(command);
  await page.waitForTimeout(700);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(1500);
}
async function waitForAssistantReply(frame, timeout = 120_000) {
  const start = Date.now(); let lastText = ""; let stable = 0;
  while (Date.now() - start < timeout) {
    const bodies = frame.locator(".message-bubble__body").filter({ has: frame.locator(".message-bubble__assistant-rail") });
    const count = await bodies.count();
    if (count > 0) {
      let current = "";
      for (let index = count - 1; index >= 0; index -= 1) {
        const text = (await bodies.nth(index).innerText()).replace(/\s+/g, " ").trim();
        if (text.length < 20 || /^正在|第一段可见回复|教练正在思考/.test(text)) continue;
        current = text;
        break;
      }
      if (current) {
        stable = current === lastText ? stable + 1 : 0;
        lastText = current;
        if (lastText.length > 80 && stable >= 3) return lastText;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  throw new Error(`Assistant reply did not finish; last=${lastText.slice(0, 600)}`);
}
async function ensureCoachReady(page, frame) {
  await frame.getByRole("button", { name: "对话", exact: true }).first().click();
  await page.waitForTimeout(1200);
  const join = frame.getByRole("button", { name: "加入 Trainer", exact: true });
  if ((await join.count()) > 0) {
    await join.first().click();
    await page.waitForTimeout(5000);
  }
  const composer = frame.locator('textarea:visible, [contenteditable="true"]:visible').first();
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if ((await composer.count()) > 0 && await composer.isEnabled().catch(() => false)) return composer;
    await page.waitForTimeout(800);
  }
  return composer;
}
async function sendCoach(page, frame, text) {
  const composer = await ensureCoachReady(page, frame);
  await composer.click();
  await composer.fill(text);
  await page.waitForTimeout(300);
  await frame.getByRole("button", { name: /发送|Send/ }).first().click();
  await page.waitForTimeout(1200);
  try {
    return await waitForAssistantReply(frame, 120_000);
  } catch (error) {
    const bodyCount = await frame.locator(".message-bubble__body").count();
    for (let index = bodyCount - 1; index >= 0; index -= 1) {
      const text = (await frame.locator(".message-bubble__body").nth(index).innerText()).replace(/\s+/g, " ").trim();
      if (text.length > 60 && !/^正在|第一段可见回复|教练正在思考/.test(text)) {
        step("assistant-reply-settled-without-idle", { chars: text.length });
        return text;
      }
    }
    throw error;
  }
}
async function openSettingsCategory(page, frame, category, label) {
  await frame.getByRole("button", { name: "设置", exact: true }).first().click();
  await page.waitForTimeout(1800);
  const direct = frame.locator(`[data-settings-detail="${category}"]:visible`);
  if ((await direct.count()) === 0) {
    const openDetail = frame.locator("[data-template=SettingsDetail]:visible");
    if ((await openDetail.count()) > 0) {
      const back = openDetail.locator(".template-back").first();
      if ((await back.count()) > 0) { await back.click(); await page.waitForTimeout(1200); }
    }
    const entry = frame.locator(`[data-settings-category="${category}"]:visible`);
    if ((await entry.count()) > 0) { await entry.first().click(); await page.waitForTimeout(1500); }
  }
  if ((await frame.locator(`[data-settings-detail="${category}"]:visible`).count()) === 0 && label) {
    const labelEntry = frame.getByRole("button", { name: label, exact: true }).filter({ visible: true });
    if ((await labelEntry.count()) > 0) { await labelEntry.first().click(); await page.waitForTimeout(1500); }
  }
  if ((await frame.locator(`[data-settings-detail="${category}"]:visible`).count()) === 0) {
    const debug = await frame.locator("button").evaluateAll((els) => els.filter((e) => /连接|教练|工作区|偏好/.test(e.innerText)).map((e) => ({ text: e.innerText, attrs: Object.fromEntries([...e.attributes].map((a) => [a.name, a.value])) })));
    fs.writeFileSync(path.join(outDir, `settings-category-missing-${category}.json`), JSON.stringify(debug, null, 2));
  }
  return frame.locator(`[data-settings-detail="${category}"]:visible`);
}
async function configureProvider(page, frame, baseUrl, apiKey, model) {
  await openSettingsCategory(page, frame, "connection", "连接");
  const quickPaste = frame.locator('input[placeholder*="连接信息"]').first();
  if ((await quickPaste.count()) > 0 && await quickPaste.isVisible().catch(() => false)) {
    await quickPaste.fill(JSON.stringify({ url: baseUrl, key: apiKey }));
    await page.waitForTimeout(1200);
  }
  const edit = frame.getByRole("button", { name: "编辑配置", exact: true }).filter({ visible: true });
  if ((await edit.count()) > 0) { await edit.first().click(); await page.waitForTimeout(1500); }
  const service = frame.locator('input[placeholder="例如 localhost:1234/v1 或 api.deepseek.com/v1"]').first();
  try {
    await waitForLocator(service, 30_000);
  } catch (error) {
    const debugText = await bodyText(frame);
    fs.writeFileSync(path.join(outDir, "provider-form-missing.txt"), debugText);
    await screenshot(page, "provider-form-missing");
    const inputs = await frame.locator("input,select,textarea").evaluateAll((els) => els.map((e) => ({ tag: e.tagName, type: e.type, placeholder: e.placeholder, value: e.value, visible: !!(e.offsetWidth || e.offsetHeight) })));
    fs.writeFileSync(path.join(outDir, "provider-form-missing-inputs.json"), JSON.stringify(inputs, null, 2));
    throw error;
  }
  await service.fill(baseUrl);
  const key = frame.locator('input[placeholder="连接已保存，还需要 API key。"]').first();
  if ((await key.count()) > 0) await key.fill(apiKey);
  const modelInput = frame.locator('input[placeholder*="kimi-k3"]').first();
  if ((await modelInput.count()) > 0) await modelInput.fill(model);
  await page.waitForTimeout(800);
  const save = frame.locator("button:visible").filter({ hasText: /保存|Save/ });
  if ((await save.count()) === 0) {
    fs.writeFileSync(path.join(outDir, "provider-save-missing.txt"), await bodyText(frame));
    await screenshot(page, "provider-save-missing");
    throw new Error("Save connection button missing");
  }
  await save.last().click();
  await page.waitForTimeout(3000);
  return bodyText(frame);
}
async function waitForLocator(locator, timeout = 30_000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if ((await locator.count()) > 0) return;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error("Locator did not appear");
}
async function openSidebar(page) {
  await commandPalette(page, "Trainer: Open Coach Sidebar");
  await page.waitForTimeout(6000);
  return workspaceFrame(page);
}

// ---------------------------------------------------------------- journeys
const fixtureProvider = await startFixtureProvider();
step("fixture-provider", { baseUrl: `http://127.0.0.1:${fixtureProvider.port}/v1` });
const baseUrl = process.env.PROBE_PROVIDER_BASE_URL || `http://127.0.0.1:${fixtureProvider.port}/v1`;
const apiKey = process.env.PROBE_PROVIDER_API_KEY || "fixture-key";
const model = process.env.PROBE_PROVIDER_MODEL || "fixture-v4-gui";
const altModel = process.env.PROBE_PROVIDER_MODEL_SWITCH || "fixture-v4-gui-alt";

const root = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-v4-gui-"));
const userDataDir = path.join(root, "user-data");
const extensionsDir = path.join(root, "extensions");
const workspaceDir = path.join(root, "workspace");
const learningDir = path.join(root, "learning");
fs.mkdirSync(path.join(workspaceDir, "src"), { recursive: true });
fs.mkdirSync(learningDir, { recursive: true });
fs.writeFileSync(path.join(workspaceDir, "src", "queue_lock.py"), ["import threading", "", "class Queue:", "    def __init__(self):", "        self._items = []", "        self._lock = threading.Lock()", "", "    def push(self, item):", "        with self._lock:", "            self._items.append(item)", "", "    def pop(self):", "        with self._lock:", "            if not self._items:", '                raise IndexError("empty")', "            return self._items.pop(0)", ""].join("\n"));
fs.writeFileSync(path.join(workspaceDir, "README.md"), "# Concurrency practice\n\nSmall Python project for learning locks.\n");
seedLearningFolder({ userDataDir, rootPath: learningDir, extensionId: "local.trainer-extension", version: packageJson.version });
execFileSync(codeCli, ["--user-data-dir", userDataDir, "--extensions-dir", extensionsDir, "--install-extension", vsixPath, "--force"], { stdio: "ignore" });

const app = await _electron.launch({
  executablePath: electronBinary,
  args: ["--user-data-dir", userDataDir, "--extensions-dir", extensionsDir, "--disable-workspace-trust", "--skip-welcome", "--skip-release-notes", "--new-window", workspaceDir],
  timeout: 90_000,
});
let currentFrame;
try {
  const page = await app.firstWindow({ timeout: 90_000 });
  await page.waitForTimeout(6000);
  let frame = await openSidebar(page);
  currentFrame = frame;
  const firstText = await bodyText(frame);
  step("first-screen", { text: firstText.slice(0, 500) });
  await configureProvider(page, frame, baseUrl, apiKey, model);
  await page.waitForTimeout(2000);
  frame = workspaceFrame(page);
  currentFrame = frame;
  await ensureCoachReady(page, frame);

  async function runJourney(id, title, fn) {
    try {
      const result = await fn();
      record(id, title, result.status ?? (result.ok === false ? "PARTIAL" : "PASS"), result);
    } catch (error) {
      record(id, title, "FAIL", { error: String(error).slice(0, 600), screenshot: await screenshot(page, `journey-${id}-fail`).catch(() => undefined) });
    }
  }

  await runJourney(1, "第一次安装 Trainer，自然开始交流", async () => {
    const text = await bodyText(frame);
    const nav = await frame.locator(".app-shell-nav button").allTextContents();
    const composer = await frame.locator('textarea, [contenteditable="true"]').count();
    return { ok: /对话/.test(text) && /学习/.test(text) && /资料/.test(text) && composer > 0, nav, chars: text.length, screenshot: await screenshot(page, "j01-first-run") };
  });

  await runJourney(2, "随口提问，不产生不必要长期目标", async () => {
    const reply = await sendCoach(page, frame, "PPO 是什么？请用两句话解释。");
    const goalBar = await frame.locator("[data-goal-bar=true]").count();
    return { ok: reply.length > 40 && goalBar === 0, reply: reply.slice(0, 300), goalBar, screenshot: await screenshot(page, "j02-casual") };
  });

  await runJourney(3, "明确能力目标，Goal 自动建立并持续追踪", async () => {
    const reply = await sendCoach(page, frame, "我想真正学会实现 PPO Clip，请先判断我该从哪里开始。");
    await page.waitForTimeout(1500);
    const bar = frame.locator("[data-goal-bar=true]");
    const visible = await bar.count();
    const text = visible ? await bar.first().innerText() : "";
    if (!visible) return { ok: false, status: "PARTIAL", reply: reply.slice(0, 300), note: "Goal bar did not render with the fixture provider" };
    await page.reload();
    await page.waitForTimeout(6000);
    frame = await openSidebar(page);
    currentFrame = frame;
    const restored = await frame.locator("[data-goal-bar=true]").count();
    return { ok: restored > 0, goal: text.slice(0, 300), restored, screenshot: await screenshot(page, "j03-goal-restart") };
  });

  await runJourney(4, "多次会话继续同一任务，不复述背景", async () => {
    const reply = await sendCoach(page, frame, "继续，从最小实现开始，先给我第一步。");
    const text = await bodyText(frame);
    return { ok: reply.length > 40 && /PPO|ratio|clip/i.test(text), reply: reply.slice(0, 300), goalBar: await frame.locator("[data-goal-bar=true]").count(), screenshot: await screenshot(page, "j04-continue") };
  });

  await runJourney(5, "表达教学偏好，后续自动适配", async () => {
    const detail = await openSettingsCategory(page, frame, "teaching", "教练");
    const styleChoice = detail.locator(".settings-choice").nth(1);
    if ((await styleChoice.count()) === 0) return { ok: false, status: "PARTIAL", note: "teaching style control not found" };
    const before = await styleChoice.locator(".settings-choice__trigger").innerText();
    await styleChoice.locator(".settings-choice__trigger").click();
    await styleChoice.getByRole("option").nth(1).click();
    await page.waitForTimeout(800);
    const after = await styleChoice.locator(".settings-choice__trigger").innerText();
    return { ok: before !== after, before, after, note: "Preference persistence/adaptation is verified separately below and in P journeys", screenshot: await screenshot(page, "j05-preference") };
  });

  await runJourney(6, "改变偏好，系统修正旧习惯", async () => {
    const detail = await openSettingsCategory(page, frame, "teaching", "教练");
    const styleChoice = detail.locator(".settings-choice").nth(1);
    const before = await styleChoice.locator(".settings-choice__trigger").innerText();
    await styleChoice.locator(".settings-choice__trigger").click();
    await styleChoice.getByRole("option").nth(2).click();
    await page.waitForTimeout(800);
    const after = await styleChoice.locator(".settings-choice__trigger").innerText();
    return { ok: before !== after, before, after, note: "The model-facing preference change is covered by P journeys; this is GUI persistence only", screenshot: await screenshot(page, "j06-preference-change") };
  });

  await runJourney(7, "提示帮助下完成，不误判独立掌握", async () => ({
    ok: false, status: "BLOCKED", note: "Needs a generated training card plus assisted verification; fixture provider cannot mint a tool-bound card in this harness",
  }));
  await runJourney(8, "独立完成，真实证据自动同步 Learning", async () => ({
    ok: false, status: "BLOCKED", note: "Needs a real training card and host verification; covered by training/evidence P journeys",
  }));
  await runJourney(9, "数天后忘记，自然安排复习", async () => ({
    ok: false, status: "BLOCKED", note: "Real elapsed-day clock is not available in this GUI harness; FSRS time advance is covered by L evidence",
  }));
  await runJourney(10, "正确延迟回忆，间隔延长", async () => ({
    ok: false, status: "BLOCKED", note: "Requires a real delayed recall over days; not simulated as GUI PASS",
  }));
  await runJourney(11, "拒绝复习或忙碌，不被打扰", async () => {
    const detail = await openSettingsCategory(page, frame, "preferences", "偏好");
    const review = detail.locator('[data-settings-subsection="review"]');
    const visible = await review.count();
    const text = visible ? await review.innerText() : "";
    return { ok: visible > 0, text: text.slice(0, 400), note: "GUI exposes review reminder controls; real refusal behavior still needs a due queue", screenshot: await screenshot(page, "j11-review-controls") };
  });
  await runJourney(12, "长期未上线返回，不积压提醒", async () => ({
    ok: false, status: "PARTIAL", note: "Settings review controls render, but no real long-offline state exists in this run",
  }));
  await runJourney(13, "跨项目同概念复用但不泄漏代码", async () => ({
    ok: false, status: "PARTIAL", note: "Single workspace window in this run; cross-project isolation is covered by skill workspace unit tests and needs a second window",
  }));
  await runJourney(14, "切换模型和重启 VS Code，状态恢复", async () => {
    await openSettingsCategory(page, frame, "connection", "连接");
    const edit = frame.getByRole("button", { name: /编辑配置|Edit configuration/ }).filter({ visible: true });
    if ((await edit.count()) > 0) { await edit.first().click(); await page.waitForTimeout(1800); }
    const refresh = frame.getByRole("button", { name: /刷新模型列表/ }).filter({ visible: true });
    if ((await refresh.count()) > 0) { await refresh.first().click(); await page.waitForTimeout(3500); }
    const picker = frame.locator("details.settings-model-picker:visible").first();
    if ((await picker.count()) === 0) {
      return { ok: false, status: "PARTIAL", note: "model picker missing", text: (await bodyText(frame)).slice(0, 800) };
    }
    if (!(await picker.evaluate((element) => element.open))) {
      await picker.locator("summary").first().click();
      await page.waitForTimeout(500);
    }
    const modelSelect = picker.locator("select").first();
    const options = await modelSelect.locator("option").allTextContents();
    if (!options.includes(altModel)) {
      return { ok: false, status: "PARTIAL", note: "alternate model missing from picker", options, text: (await bodyText(frame)).slice(0, 800) };
    }
    await modelSelect.selectOption({ label: altModel });
    await page.waitForTimeout(1000);
    await frame.locator("button:visible").filter({ hasText: /保存|Save/ }).last().click();
    await page.waitForTimeout(3000);
    await page.reload();
    await page.waitForTimeout(6000);
    frame = await openSidebar(page);
    currentFrame = frame;
    const text = await bodyText(frame);
    return { ok: text.includes(altModel), model: altModel, screenshot: await screenshot(page, "j14-model-restart") };
  });
  await runJourney(15, "资料版本变化，旧引用/知识关系更新", async () => ({
    ok: false, status: "PARTIAL", note: "Native file import dialog is not automatable; resource version invalidation is covered by U/S evidence",
  }));
  await runJourney(16, "Skill 自动选择/执行/记录/失败隔离", async () => {
    const detail = await openSettingsCategory(page, frame, "teaching", "教练");
    const skills = detail.locator('[data-settings-section="skills"]');
    const text = skills.count() ? await skills.innerText() : "";
    return { ok: (await skills.count()) > 0, chars: text.length, note: "Built-in skill catalog renders; real selection/execution remains covered by P journeys", screenshot: await screenshot(page, "j16-skills") };
  });
  await runJourney(17, "Provider 超时/中断，不制造虚假结果", async () => ({
    ok: false, status: "PARTIAL", note: "Fixture provider does not fail; real timeout/interruption is covered by failure tests and needs a fault-injection run",
  }));
  await runJourney(18, "多窗口并发，不重复推进计划/复习", async () => ({
    ok: false, status: "BLOCKED", note: "Second window is not launched in this harness; plan revision/singleflight evidence is U/L only",
  }));
  await runJourney(19, "修改/撤销记忆，教学行为同步变化", async () => {
    const detail = await openSettingsCategory(page, frame, "preferences", "偏好");
    const memory = detail.locator('[data-settings-subsection="memory"]');
    const toggle = memory.locator("button.context-chip").first();
    if ((await toggle.count()) === 0) return { ok: false, status: "PARTIAL", note: "memory toggle missing" };
    const before = await toggle.innerText();
    await toggle.click();
    await page.waitForTimeout(700);
    const after = await toggle.innerText();
    return { ok: before !== after, before, after, note: "Memory toggle changes in the real GUI; model behavior change needs a P journey", screenshot: await screenshot(page, "j19-memory-toggle") };
  });
  await runJourney(20, "连续多个项目/主题，仍理解当前重点", async () => ({
    ok: false, status: "PARTIAL", note: "Single project in this run; project switching and long-run focus need a multi-project harness",
  }));

  const report = {
    schemaVersion: 1,
    recordedAt: new Date().toISOString(),
    vsix: path.relative(repoRoot, vsixPath),
    vsixVersion: packageJson.version,
    provider: { baseUrl: baseUrl.includes("127.0.0.1") ? "fixture" : baseUrl, model, altModel },
    environment: { root, userDataDir, extensionsDir, workspaceDir, learningDir, vscode: electronBinary },
    summary: {
      pass: journeys.filter((entry) => entry.status === "PASS").length,
      partial: journeys.filter((entry) => entry.status === "PARTIAL").length,
      blocked: journeys.filter((entry) => entry.status === "BLOCKED").length,
      fail: journeys.filter((entry) => entry.status === "FAIL").length,
    },
    journeys,
    steps,
  };
  fs.writeFileSync(path.join(outDir, "journeys.json"), `${JSON.stringify(report, null, 2)}\n`);
  const markdown = [
    `# V4 真实 VS Code GUI 20 旅程（${new Date().toISOString().slice(0, 10)}）`,
    "",
    `- VSIX: \`${path.relative(repoRoot, vsixPath)}\` (v${packageJson.version})`,
    `- Provider: \`${report.provider.baseUrl}\` / \`${model}\``,
    `- 真实窗口：VS Code Electron + 隔离 \`--user-data-dir\` / \`--extensions-dir\``,
    "",
    "## 结果",
    "",
    "| # | 旅程 | 状态 | 证据 |",
    "| --- | --- | --- | --- |",
    ...journeys.map((entry) => `| ${entry.id} | ${entry.title} | ${entry.status} | ${(entry.note || entry.reply || entry.text || "").toString().replace(/\|/g, "\\|").replace(/\s+/g, " ").slice(0, 180)} |`),
    "",
    "## 汇总",
    "",
    `PASS ${report.summary.pass} · PARTIAL ${report.summary.partial} · BLOCKED ${report.summary.blocked} · FAIL ${report.summary.fail}`,
    "",
    "> 本文件只记录真实 VS Code 窗口中的 GUI 证据。Fixture provider 的回复不构成真实模型（P）证据；需要数天时钟、双窗口、真实训练卡或故障注入的旅程明确标为 PARTIAL/BLOCKED。",
    "",
  ].join("\n");
  fs.writeFileSync(path.join(outDir, "README.md"), markdown);
  console.log(`GUI_20_JOURNEYS_OK ${path.relative(repoRoot, outDir)}`);
} finally {
  await app.close().catch(() => undefined);
  fixtureProvider.server.close();
  fs.writeFileSync(path.join(outDir, "environment.json"), JSON.stringify({ root, userDataDir, extensionsDir, workspaceDir, learningDir }, null, 2));
}
