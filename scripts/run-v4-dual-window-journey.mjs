#!/usr/bin/env node
/**
 * V4 real GUI journey 18: two real VS Code windows, one Trainer workspace.
 *
 * Window 1 opens the project folder directly. Window 2 opens the same folder
 * through a generated .code-workspace file, which forces VS Code to create a
 * second real window in the same app instance instead of focusing the first
 * one. Both windows share the same --user-data-dir, so they share the learning
 * root, provider credentials, and the sidecar data directory.
 *
 * The script then generates a formal plan through the real sidecar planner,
 * confirms both windows render it, and races the "freeze plan" action from
 * both windows. Evidence:
 *   - exactly one committed plan revision (revision +1, never +2);
 *   - the losing window renders the localized plan_revision_conflict copy;
 *   - after reload both windows show the same frozen plan.
 *
 * Usage:
 *   node scripts/run-v4-dual-window-journey.mjs
 *   GUI_OUT_DIR=docs/verification/v4-gui-dual-window-journey \
 *     node scripts/run-v4-dual-window-journey.mjs
 */
import { _electron } from "playwright";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";

const repoRoot = path.resolve(import.meta.dirname, "..");
const packageJson = JSON.parse(fs.readFileSync(path.join(repoRoot, "extension", "package.json"), "utf8"));
const vsixPath = path.join(repoRoot, "extension", `trainer-extension-${packageJson.version}-darwin-arm64.vsix`);
const codeCli = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code";
const electronBinary = "/Applications/Visual Studio Code.app/Contents/MacOS/Electron";
const outDir = path.resolve(repoRoot, process.env.GUI_OUT_DIR ?? "docs/verification/v4-gui-dual-window-journey");
fs.mkdirSync(outDir, { recursive: true });

// Real-provider mode: uses the gateway from the environment and never writes
// the key into the report. Without it the deterministic fixture is used.
const realProviderBaseUrl = (process.env.PROBE_PROVIDER_BASE_URL || process.env.TRAINER_TEST_BASE_URL || "").trim();
const realProviderApiKey = (process.env.PROBE_PROVIDER_API_KEY || process.env.TRAINER_TEST_API_KEY || "").trim();
const realProviderModel = (process.env.PROBE_PROVIDER_MODEL || process.env.TRAINER_TEST_MODEL || "deepseek-v4.1-flash").trim();
const useRealProvider = Boolean(realProviderBaseUrl && realProviderApiKey);
const providerApiKey = useRealProvider ? realProviderApiKey : "fixture-key";
const providerModel = useRealProvider ? realProviderModel : "fixture-v4-gui";

const steps = [];
function step(name, payload = {}) {
  steps.push({ name, at: new Date().toISOString(), ...payload });
  console.log(`[step] ${name}${Object.keys(payload).length ? ` ${JSON.stringify(payload).slice(0, 240)}` : ""}`);
}
async function screenshot(page, name) {
  const file = path.join(outDir, `${name}.png`);
  await page.screenshot({ path: file, timeout: 30_000 });
  return path.relative(repoRoot, file);
}

// ---------------------------------------------------------------- fixture provider
const fixtureModels = [{ id: "fixture-v4-gui", object: "model", owned_by: "trainer-fixture" }];
function fixtureReply(prompt) {
  const text = String(prompt ?? "");
  if (/PPO 是什么|两句话解释/.test(text)) {
    return "PPO 是近端策略优化：用裁剪的目标函数限制每次策略更新幅度，在实现简单的同时保持训练稳定。";
  }
  if (/真正学会|PPO Clip|从哪里开始/.test(text)) {
    return "先做最小分诊：确认策略梯度、优势函数、on-policy rollout、重要性采样 ratio、clip 目标和多 epoch 更新这条链是否打通。今天只做一件事：写出 ratio 与 clip 的公式，并用一组假数据手算一次更新。";
  }
  return "先看当前这一步的最小可验证动作：打开当前文件，找到一个真实调用点，写出输入、输出和一个失败边界。完成后用一次真实运行收尾，再把结果带回对话。";
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
        const output = fixtureReply(lastUser?.content);
        const id = `chatcmpl-fixture-${Date.now()}`;
        const model = payload.model || "fixture-v4-gui";
        const tools = Array.isArray(payload.tools) ? payload.tools : [];
        const toolNames = tools.map((tool) => tool?.function?.name).filter(Boolean);
        const hasToolResult = messages.some((message) => message.role === "tool");
        const savePlanRequested = toolNames.includes("save_formal_plan") && !hasToolResult;
        if (savePlanRequested) {
          const planArgs = {
            title: "PPO Clip 实现计划",
            summary: "用最小切片实现 PPO Clip，并逐步接入训练循环。",
            cadence: "每周 4 小时",
            current_step: "写出 ratio 与 clip 的公式，并手算一次更新。",
            why_now: "先打通 PPO 的最小更新链，再扩展到训练循环。",
            verify_method: ["手算结果与代码输出一致", "能解释 clip 如何限制策略更新幅度"],
            blocked_reason: "",
            next_after_current: "把 clip 接入一个最小 PPO 训练步骤，并用真实运行验证。",
            stages: [
              { id: "stage-foundation", title: "基础", goal: "理解并手算 PPO Clip 目标。", outcomes: ["写出 ratio 与 clip 公式", "手算一次更新"], resources: [], status: "active" },
              { id: "stage-practice", title: "练习", goal: "实现最小 PPO 更新。", outcomes: ["运行通过并解释 clip 边界"], resources: [], status: "pending" },
            ],
          };
          if (payload.stream) {
            response.writeHead(200, {
              "content-type": "text/event-stream",
              "cache-control": "no-cache",
              connection: "keep-alive",
            });
            const base = { id, object: "chat.completion.chunk", model };
            response.write(`data: ${JSON.stringify({ ...base, choices: [{ index: 0, delta: { role: "assistant", tool_calls: [{ index: 0, id: "call_save_formal_plan", type: "function", function: { name: "save_formal_plan", arguments: "" } }] }, finish_reason: null }] })}\n\n`);
            response.write(`data: ${JSON.stringify({ ...base, choices: [{ index: 0, delta: { tool_calls: [{ index: 0, function: { arguments: JSON.stringify(planArgs) } }] }, finish_reason: null }] })}\n\n`);
            response.write(`data: ${JSON.stringify({ ...base, choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }] })}\n\n`);
            response.write("data: [DONE]\n\n");
            response.end();
            return;
          }
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({
            id, object: "chat.completion", model,
            choices: [{
              index: 0,
              message: {
                role: "assistant",
                content: null,
                tool_calls: [{
                  id: "call_save_formal_plan",
                  type: "function",
                  function: { name: "save_formal_plan", arguments: JSON.stringify(planArgs) },
                }],
              },
              finish_reason: "tool_calls",
            }],
            usage: { prompt_tokens: 20, completion_tokens: 40, total_tokens: 60 },
          }));
          return;
        }
        if (hasToolResult) {
          const finalText = "正式计划已保存。先完成第一阶段：写出 ratio 与 clip 的公式，并手算一次更新。";
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({
            id, object: "chat.completion", model,
            choices: [{ index: 0, message: { role: "assistant", content: finalText }, finish_reason: "stop" }],
            usage: { prompt_tokens: 20, completion_tokens: 30, total_tokens: 50 },
          }));
          return;
        }
        const probeRequested = tools.some((tool) => tool?.function?.name === "trainer_capability_probe");
        if (probeRequested) {
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({
            id, object: "chat.completion", model,
            choices: [{
              index: 0,
              message: {
                role: "assistant",
                content: null,
                tool_calls: [{
                  id: "call_trainer_capability_probe",
                  type: "function",
                  function: { name: "trainer_capability_probe", arguments: JSON.stringify({ probe: "ok" }) },
                }],
              },
              finish_reason: "tool_calls",
            }],
            usage: { prompt_tokens: 20, completion_tokens: 8, total_tokens: 28 },
          }));
          return;
        }
        if (payload.stream) {
          response.writeHead(200, {
            "content-type": "text/event-stream",
            "cache-control": "no-cache",
            connection: "keep-alive",
          });
          const chunks = output.match(/[\s\S]{1,18}/g) ?? [output];
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
          choices: [{ index: 0, message: { role: "assistant", content: output }, finish_reason: "stop" }],
          usage: { prompt_tokens: 20, completion_tokens: output.length, total_tokens: 20 + output.length },
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

// ---------------------------------------------------------------- profiles
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
function seedLearningFolder(userDataDir, rootPath, extensionId, version) {
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

// ---------------------------------------------------------------- webview helpers
function workspaceFrame(page) {
  return page.frames().find((candidate) => candidate.url().includes("vscode-webview://") && candidate.url().includes("fake.html"));
}
async function waitForTrainerFrame(page, timeout = 90_000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const frame = workspaceFrame(page);
    if (frame) return frame;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("Trainer webview frame not found");
}
async function bodyText(frame) { return (await frame.locator("body").innerText()).replace(/\s+/g, " ").trim(); }
async function commandPalette(page, command) {
  await page.bringToFront().catch(() => undefined);
  await page.keyboard.press("Meta+Shift+P");
  await page.waitForTimeout(800);
  await page.keyboard.type(command);
  await page.waitForTimeout(900);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(2500);
}
async function waitForLocator(locator, timeout = 30_000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if ((await locator.count()) > 0) return;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error("Locator did not appear");
}
async function dismissVsCodeWelcome(page) {
  const dialog = page.locator('[role="dialog"][aria-modal="true"]').first();
  if ((await dialog.count()) > 0) {
    await page.keyboard.press("Escape").catch(() => undefined);
    await page.waitForTimeout(800);
    if ((await dialog.count()) > 0) {
      const close = dialog.locator('button[aria-label*="Close"], button[aria-label*="close"], button[title*="Close"]').first();
      if ((await close.count()) > 0) await close.click().catch(() => undefined);
    }
  }
}
async function openSidebar(page) {
  await page.bringToFront().catch(() => undefined);
  await dismissVsCodeWelcome(page);
  await page.locator("body").click({ position: { x: 400, y: 300 } }).catch(() => undefined);
  await page.waitForTimeout(500);
  await commandPalette(page, "Trainer: Open Coach Sidebar");
  for (let attempt = 0; attempt < 45; attempt += 1) {
    const frame = workspaceFrame(page);
    if (frame) {
      await page.waitForTimeout(2500);
      return frame;
    }
    await page.waitForTimeout(1000);
  }
  throw new Error("Trainer sidebar did not open");
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
  await waitForLocator(service, 30_000);
  await service.fill(baseUrl);
  const key = frame.locator('input[placeholder="连接已保存，还需要 API key。"]').first();
  if ((await key.count()) > 0) await key.fill(apiKey);
  const modelInput = frame.locator('input[placeholder*="kimi-k3"]').first();
  if ((await modelInput.count()) > 0) await modelInput.fill(model);
  await page.waitForTimeout(800);
  const save = frame.locator("button:visible").filter({ hasText: /保存|Save/ });
  if ((await save.count()) === 0) throw new Error("provider save button missing");
  await save.last().click();
  await page.waitForTimeout(3000);
}
async function ensureJoined(page, frame) {
  await frame.getByRole("button", { name: "对话", exact: true }).first().click();
  await page.waitForTimeout(2500);
  // The discovery card can paint before the sidecar is ready to provision.
  await page.waitForTimeout(8000);
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const join = frame.getByRole("button", { name: "加入 Trainer", exact: true });
    if ((await join.count()) === 0) {
      await page.waitForTimeout(5000);
      if ((await join.count()) === 0) return;
    }
    await join.first().click().catch(() => undefined);
    await page.waitForTimeout(10000);
  }
  throw new Error(`workspace admission did not become managed: ${(await bodyText(frame)).slice(0, 400)}`);
}
async function sendCoach(page, frame, text) {
  await frame.getByRole("button", { name: "对话", exact: true }).first().click().catch(() => undefined);
  await page.waitForTimeout(1500);
  const composer = frame.locator('textarea:visible, [contenteditable="true"]:visible').first();
  const beforeBubbleCount = await frame.locator(".message-bubble__body").count();
  await composer.click();
  await composer.fill(text);
  await page.waitForTimeout(400);
  await frame.getByRole("button", { name: /发送|Send/ }).first().click();
  await page.waitForTimeout(1500);
  const start = Date.now();
  let last = "";
  while (Date.now() - start < 120_000) {
    const bodies = frame.locator(".message-bubble__body");
    const count = await bodies.count();
    if (count > beforeBubbleCount) {
      for (let index = count - 1; index >= 0; index -= 1) {
        const body = (await bodies.nth(index).innerText()).replace(/\s+/g, " ").trim();
        if (body.length > 40 && !/^正在|第一段可见回复|教练正在思考/.test(body)) { last = body; break; }
      }
      if (last) return last;
    }
    await page.waitForTimeout(1200);
  }
  throw new Error(`assistant reply did not arrive: ${(await bodyText(frame)).slice(0, 600)}`);
}
async function openLearningMore(page, frame) {
  await frame.evaluate(() => {
    const scope = window;
    if (!scope.__trainerFunctionErrors) {
      scope.__trainerFunctionErrors = [];
      const OriginalFunction = scope.Function;
      scope.Function = function (...args) {
        try {
          return OriginalFunction(...args);
        } catch (error) {
          try {
            scope.__trainerFunctionErrors.push({
              source: args.map((value) => String(value)).join("\n").slice(0, 5000),
              error: String(error),
            });
          } catch { /* best effort */ }
          throw error;
        }
      };
    }
    if (!scope.__trainerConsoleErrors) {
      scope.__trainerConsoleErrors = [];
      const original = console.error;
      console.error = (...args) => {
        try {
          scope.__trainerConsoleErrors.push(args.map((value) => {
            if (typeof value === "string") return value;
            if (value && typeof value === "object" && "stack" in value) return String(value.stack);
            try { return JSON.stringify(value); } catch { return String(value); }
          }).join(" "));
        } catch { /* best effort */ }
        original(...args);
      };
    }
  }).catch(() => undefined);
  await frame.getByRole("button", { name: "学习", exact: true }).first().click();
  await page.waitForTimeout(2500);
  const focusMore = frame.locator('[data-learning-focus-more] > summary').first();
  if ((await focusMore.count()) > 0) { await focusMore.click(); await page.waitForTimeout(900); }
  const more = frame.locator('[data-learning-section="more"] > summary').first();
  if ((await more.count()) > 0) { await more.click(); await page.waitForTimeout(900); }
  const governance = frame.locator('[data-plan-governance-disclosure] > summary').first();
  if ((await governance.count()) > 0) { await governance.click(); await page.waitForTimeout(900); }
  const errors = await frame.evaluate(() => window.__trainerConsoleErrors ?? []).catch(() => []);
  if (errors.length) console.log("LEARNING_CONSOLE_ERRORS", JSON.stringify(errors.map((item) => item.slice(0, 1200))));
  const functionErrors = await frame.evaluate(() => window.__trainerFunctionErrors ?? []).catch(() => []);
  if (functionErrors.length) console.log("FUNCTION_ERRORS", JSON.stringify(functionErrors).slice(0, 6000));
}
async function visibleButtons(frame) {
  return frame.locator("button:visible").evaluateAll((els) => els.map((element) => element.innerText.replace(/\s+/g, " ").trim()).filter(Boolean));
}

// ---------------------------------------------------------------- sidecar helpers
function findSidecar(extensionsDir) {
  const lines = execFileSync("ps", ["-axo", "pid,command"], { encoding: "utf8" }).split("\n");
  const line = lines.find((candidate) => candidate.includes(`${extensionsDir}${path.sep}`) && candidate.includes("trainer-sidecar"));
  if (!line) return undefined;
  const pid = line.trim().split(/\s+/)[0];
  const port = /--port\s+(\d+)/.exec(line)?.[1];
  const envText = execFileSync("ps", ["eww", "-p", pid, "-o", "command="], { encoding: "utf8", maxBuffer: 8 * 1024 * 1024 });
  const token = /TRAINER_SIDECAR_TOKEN=(\S+)/.exec(envText)?.[1];
  return { pid, port: port ? Number(port) : undefined, token };
}

function readSessionId(dbPath, workspaceId) {
  const database = new DatabaseSync(dbPath);
  try {
    const rows = database.prepare("SELECT session_id, workspace_id FROM sessions").all();
    return rows.find((row) => row.workspace_id === workspaceId)?.session_id;
  } finally { database.close(); }
}


function readPlanRevision(dbPath) {
  const database = new DatabaseSync(dbPath);
  try {
    const rows = database.prepare("SELECT plan_id, workspace_id, payload FROM learning_plan").all();
    return rows.map((row) => {
      const payload = JSON.parse(row.payload);
      return { planId: row.plan_id, workspaceId: row.workspace_id, revision: payload._plan_revision ?? 0, frozen: payload.frozen === true, title: payload.title };
    });
  } finally { database.close(); }
}

async function testProviderInUi(page, frame) {
  await openSettingsCategory(page, frame, "connection", "连接");
  const edit = frame.getByRole("button", { name: /编辑配置|Edit configuration/ }).filter({ visible: true });
  if ((await edit.count()) > 0) {
    await edit.first().click();
    await page.waitForTimeout(1800);
  }
  const test = frame.getByRole("button", { name: /测试连接|Test connection/ }).filter({ visible: true });
  if ((await test.count()) === 0) {
    const buttons = await visibleButtons(frame);
    throw new Error(`provider test button missing: ${JSON.stringify(buttons)}`);
  }
  await test.first().click();
  await page.waitForTimeout(12000);
  return bodyText(frame);
}
async function waitForNewReply(page, frame, beforeCount, timeout = 180_000) {
  const start = Date.now();
  let last = "";
  while (Date.now() - start < timeout) {
    const bodies = frame.locator(".message-bubble__body");
    const count = await bodies.count();
    if (count > beforeCount) {
      for (let index = count - 1; index >= beforeCount; index -= 1) {
        const body = (await bodies.nth(index).innerText()).replace(/\s+/g, " ").trim();
        if (body.length > 20 && !/^正在|第一段可见回复|教练正在思考/.test(body)) { last = body; break; }
      }
      if (last) return last;
    }
    await page.waitForTimeout(1200);
  }
  throw new Error(`plan reply did not arrive: ${(await bodyText(frame)).slice(0, 600)}`);
}
async function generatePlanInUi(page, frame) {
  await openLearningMore(page, frame);
  const generate = frame.getByRole("button", { name: /生成计划|Generate Plan/ }).filter({ visible: true });
  if ((await generate.count()) === 0) throw new Error(`generate-plan action missing: ${JSON.stringify(await visibleButtons(frame))}`);
  if (await generate.first().isDisabled().catch(() => false)) {
    throw new Error(`generate-plan action disabled: ${(await bodyText(frame)).slice(0, 500)}`);
  }
  await generate.first().click();
  await page.waitForTimeout(2500);
  const composer = frame.locator('textarea:visible, [contenteditable="true"]:visible').first();
  const prompt = await composer.inputValue().catch(() => "");
  const before = await frame.locator(".message-bubble__body").count();
  await frame.getByRole("button", { name: /发送|Send/ }).first().click();
  await page.waitForTimeout(1500);
  const reply = await waitForNewReply(page, frame, before);
  return { prompt, reply };
}

// ---------------------------------------------------------------- run
const fixture = useRealProvider ? undefined : await startFixtureProvider();
const fixtureBaseUrl = fixture ? `http://127.0.0.1:${fixture.port}/v1` : "";
const providerBaseUrl = useRealProvider ? realProviderBaseUrl : fixtureBaseUrl;
step("provider", { mode: useRealProvider ? "real" : "fixture", baseUrl: useRealProvider ? realProviderBaseUrl : "fixture", model: providerModel });

const root = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-dw-"));
const userDataDir = path.join(root, "user-data");
const extensionsDir = path.join(root, "extensions");
const workspaceDir = path.join(root, "workspace");
const learningDir = path.join(root, "learning");
const workspaceFilePath = path.join(root, "dual-window.code-workspace");
fs.mkdirSync(path.join(workspaceDir, "src"), { recursive: true });
fs.mkdirSync(learningDir, { recursive: true });
fs.writeFileSync(path.join(workspaceDir, "README.md"), "# Dual-window concurrency practice\n\nSmall project for learning locks.\n");
fs.writeFileSync(path.join(workspaceDir, "src", "queue_lock.py"), ["import threading", "", "class Queue:", "    def __init__(self):", "        self._items = []", "        self._lock = threading.Lock()", "", "    def push(self, item):", "        with self._lock:", "            self._items.append(item)", ""].join("\n"));
fs.writeFileSync(workspaceFilePath, `${JSON.stringify({ folders: [{ path: workspaceDir }] }, null, 2)}\n`);
seedLearningFolder(userDataDir, learningDir, "local.trainer-extension", packageJson.version);
execFileSync(codeCli, ["--user-data-dir", userDataDir, "--extensions-dir", extensionsDir, "--install-extension", vsixPath, "--force"], { stdio: "ignore" });
step("profile-ready", { root, userDataDir, extensionsDir, workspaceDir, learningDir, workspaceFilePath });

const report = {
  schemaVersion: 1,
  journey: "G18",
  title: "多窗口并发，不重复推进计划/复习",
  recordedAt: new Date().toISOString(),
  vsix: path.relative(repoRoot, vsixPath),
  vsixVersion: packageJson.version,
  provider: { mode: useRealProvider ? "real" : "fixture", baseUrl: useRealProvider ? realProviderBaseUrl : "fixture", model: providerModel },
  environment: { root, userDataDir, extensionsDir, workspaceDir, learningDir, workspaceFilePath, vscode: electronBinary },
  windows: [],
  plan: {},
  concurrency: {},
  assertions: {},
  status: "FAIL",
  steps,
};

const app = await _electron.launch({
  executablePath: electronBinary,
  args: ["--user-data-dir", userDataDir, "--extensions-dir", extensionsDir, "--disable-workspace-trust", "--skip-welcome", "--skip-release-notes", "--new-window", workspaceDir],
  timeout: 90_000,
});
let page2;
try {
  const page1 = await app.firstWindow({ timeout: 90_000 });
  page1.on("console", (message) => {
    if (message.type() === "error") console.log("PAGE_CONSOLE", message.text().slice(0, 400));
  });
  await page1.waitForTimeout(7000);
  let frame1 = await openSidebar(page1);
  step("window-1-sidebar", { body: (await bodyText(frame1)).slice(0, 240) });
  // Warm the lazy Learning chunk while the webview is fresh. Subsequent
  // Learning opens reuse the loaded chunk.
  await openLearningMore(page1, frame1);
  step("pre-plan-learning-first-open", { body: (await bodyText(frame1)).slice(0, 400) });
  await configureProvider(page1, frame1, providerBaseUrl, providerApiKey, providerModel);
  frame1 = workspaceFrame(page1);
  await ensureJoined(page1, frame1);
  const firstReply = await sendCoach(page1, frame1, "PPO 是什么？请用两句话解释。");
  step("window-1-provider-verified", { reply: firstReply.slice(0, 160) });
  report.windows.push({ id: "window-1", openedAs: "folder", title: await page1.title(), trainerReady: true, screenshot: await screenshot(page1, "window-1") });

  // Resolve the shared managed context, then generate the formal plan through
  // the real agent loop and the real save_formal_plan tool. The webview stays
  // out of this setup step; one real coach turn below binds the live plan into
  // the host state.
  const registry = JSON.parse(fs.readFileSync(path.join(learningDir, ".trainer", "workspace.json"), "utf8"));
  const project = Object.values(registry.projects ?? {})[0];
  const contextId = project?.contextId;
  if (!contextId) throw new Error("managed project contextId missing after window 1 joined");
  step("shared-context", { contextId, projectPath: project?.projectPath, projectId: project?.projectId });
  report.plan.workspaceId = contextId;

  const sidecar = findSidecar(extensionsDir);
  if (!sidecar?.port || !sidecar.token) throw new Error("Trainer sidecar port/token not found");
  step("sidecar", { pid: sidecar.pid, port: sidecar.port });
  const sidecarRoot = path.join(userDataDir, "User", "globalStorage", "local.trainer-extension", "sidecar", "roots", registry.rootId ?? project?.rootId ?? "");
  const dbPath = path.join(sidecarRoot, "trainer.sqlite3");
  if (!fs.existsSync(dbPath)) throw new Error(`trainer db missing at ${dbPath}`);
  const sessionId = readSessionId(dbPath, contextId);
  step("workspace-session", { sessionId: sessionId ?? null });
  if (!sessionId) throw new Error("workspace session id missing");

  // Test the provider through the real Settings button. The fixture answers
  // the forced tool probe, so the host records tools=verified and enables the
  // formal plan action.
  const testedBody = await testProviderInUi(page1, frame1);
  step("provider-tested", { body: testedBody.slice(-500) });
  if (!/已通过|连接正常|tools|工具|通过/.test(testedBody)) {
    throw new Error(`provider test did not report a passing state: ${testedBody.slice(-600)}`);
  }

  // Generate the formal plan through the real Learning action. The streamed
  // turn asks the fixture for save_formal_plan; the real tool commits it.
  const planGeneration = await generatePlanInUi(page1, frame1);
  step("plan-generated", { prompt: planGeneration.prompt.slice(0, 160), reply: planGeneration.reply.slice(0, 200) });

  const planRows = readPlanRevision(dbPath);
  const targetPlan = planRows.find((row) => row.workspaceId === contextId);
  if (!targetPlan) throw new Error("generated plan row not found for the shared workspace");
  report.plan.id = targetPlan.planId;
  report.plan.title = targetPlan.title;
  step("plan-stored", { planId: targetPlan.planId, revision: targetPlan.revision });

  // A real coach turn is the host's snapshot refresh path; a page reload would
  // restore the cached bootstrap and keep the plan stale. This turn must add a
  // new assistant reply, not reuse the earlier PPO bubble.
  const syncReply = await sendCoach(page1, frame1, "继续");
  await openLearningMore(page1, frame1);
  const buttons1 = await visibleButtons(frame1);
  const freeze1 = frame1.getByRole("button", { name: "冻结计划", exact: true }).filter({ visible: true });
  report.windows[0].learningButtons = buttons1;
  report.windows[0].freezeVisible = (await freeze1.count()) > 0;
  report.windows[0].syncReply = syncReply.slice(0, 200);
  report.windows[0].screenshot = await screenshot(page1, "window-1-learning");
  step("window-1-plan-visible", { freeze: report.windows[0].freezeVisible, buttons: buttons1 });
  if (!report.windows[0].freezeVisible) throw new Error(`window 1 did not render the formal plan: ${JSON.stringify(buttons1)}`);

  // Open the second real window only after the plan is live. Its extension host
  // restores the same managed session from the shared sidecar database.
  const ipc = await app.evaluate(() => ({
    hook: globalThis.process?.env?.VSCODE_IPC_HOOK_CLI ?? null,
    ipc: globalThis.process?.env?.VSCODE_IPC_HOOK ?? null,
  }));
  const secondWindowPromise = app.waitForEvent("window", { timeout: 90_000 });
  execFileSync(codeCli, ["--user-data-dir", userDataDir, "--disable-workspace-trust", "--new-window", workspaceFilePath], {
    stdio: "ignore",
    timeout: 30_000,
    env: { ...process.env, VSCODE_IPC_HOOK: ipc.ipc ?? "", VSCODE_IPC_HOOK_CLI: ipc.ipc ?? ipc.hook ?? "" },
  });
  page2 = await secondWindowPromise;
  await page2.waitForTimeout(12_000);
  await page2.bringToFront();
  await dismissVsCodeWelcome(page2);
  let frame2 = await openSidebar(page2);
  await ensureJoined(page2, frame2);
  step("window-2-sidebar", { body: (await bodyText(frame2)).slice(0, 240) });
  report.windows.push({ id: "window-2", openedAs: "code-workspace-file", title: await page2.title(), trainerReady: true });

  async function ensureWindow2Plan() {
    await openLearningMore(page2, frame2);
    let freeze = frame2.getByRole("button", { name: "冻结计划", exact: true }).filter({ visible: true });
    if ((await freeze.count()) === 0) {
      const reply = await sendCoach(page2, frame2, "继续");
      report.windows[1].syncReply = reply.slice(0, 200);
      await openLearningMore(page2, frame2);
      freeze = frame2.getByRole("button", { name: "冻结计划", exact: true }).filter({ visible: true });
    }
    const buttons = await visibleButtons(frame2);
    report.windows[1].learningButtons = buttons;
    report.windows[1].freezeVisible = (await freeze.count()) > 0;
    report.windows[1].screenshot = await screenshot(page2, "window-2-learning");
    step("window-2-plan-visible", { freeze: report.windows[1].freezeVisible, buttons });
    return freeze;
  }
  const freeze2 = await ensureWindow2Plan();
  if (!report.windows[1].freezeVisible) throw new Error(`window 2 did not render the formal plan: ${JSON.stringify(report.windows[1].learningButtons)}`);

  const beforeRaceRows = readPlanRevision(dbPath);
  const beforeRace = beforeRaceRows.find((row) => row.planId === targetPlan.planId);
  report.plan.revisionBefore = beforeRace?.revision;

  // Race the same plan mutation from both real windows. Each window holds the
  // revision it last bootstrapped; SQLite's checked write may commit once.
  await Promise.all([
    freeze1.first().evaluate((element) => element.click()),
    freeze2.first().evaluate((element) => element.click()),
  ]);
  await page1.waitForTimeout(8000);
  const body1 = await bodyText(frame1);
  const body2 = await bodyText(frame2);
  const conflictPattern = /另一个窗口|another window|otra ventana|autre fenêtre|anderem Fenster|別のウィンドウ|다른 창|outra janela/i;
  const conflict1 = conflictPattern.test(body1);
  const conflict2 = conflictPattern.test(body2);
  const after = readPlanRevision(dbPath);
  const committed = after.find((row) => row.planId === targetPlan.planId);
  step("plan-race", { conflict1, conflict2, revisionAfter: committed?.revision, frozen: committed?.frozen });
  report.concurrency = {
    clickedAt: new Date().toISOString(),
    window1ConflictCopy: conflict1,
    window2ConflictCopy: conflict2,
    window1Body: body1.slice(0, 800),
    window2Body: body2.slice(0, 800),
    revisionAfter: committed?.revision,
    frozenAfter: committed?.frozen,
  };
  report.windows[0].screenshotAfterRace = await screenshot(page1, "window-1-after-race");
  report.windows[1].screenshotAfterRace = await screenshot(page2, "window-2-after-race");

  // Both windows already paint the frozen plan after the race. A same-state
  // freeze can be idempotent on the losing side, so a conflict copy is
  // recorded but not required; the invariant is one committed revision.
  const bothWindowsObservedFrozen = /计划已暂停|恢复计划/.test(body1) && /计划已暂停|恢复计划/.test(body2);
  const afterReload = readPlanRevision(dbPath);
  const final = afterReload.find((row) => row.planId === targetPlan.planId);
  report.plan.revisionAfter = committed?.revision;
  report.plan.revisionAfterReload = final?.revision;
  report.plan.frozenAfterReload = final?.frozen;
  report.concurrency.converged = [
    { name: "window-1", body: body1.slice(0, 500) },
    { name: "window-2", body: body2.slice(0, 500) },
  ];
  report.assertions = {
    twoRealWindows: app.windows().length === 2,
    sameManagedContext: Boolean(contextId),
    bothWindowsRenderedPlan: report.windows[0].freezeVisible && report.windows[1].freezeVisible,
    exactlyOneCommittedRevision:
      typeof report.plan.revisionBefore === "number" &&
      report.plan.revisionAfter === report.plan.revisionBefore + 1 &&
      report.plan.revisionAfterReload === report.plan.revisionAfter,
    noDoubleAdvance: report.plan.revisionAfter === report.plan.revisionBefore + 1,
    bothWindowsObservedFrozen,
    frozenStatePersisted: final?.frozen === true,
  };
  report.concurrency.conflictCopyObserved = conflict1 || conflict2;
  report.status = Object.values(report.assertions).every(Boolean) ? "PASS" : "FAIL";
  step("assertions", report.assertions);
} catch (error) {
  report.error = String(error).slice(0, 1200);
  report.windows[0] && (report.windows[0].error = report.windows[0].error ?? String(error).slice(0, 400));
  console.error("DUAL_WINDOW_JOURNEY_ERROR", String(error));
} finally {
  report.finishedAt = new Date().toISOString();
  report.steps = steps;
  fs.writeFileSync(path.join(outDir, "journey.json"), `${JSON.stringify(report, null, 2)}\n`);
  fs.writeFileSync(path.join(outDir, "environment.json"), JSON.stringify(report.environment, null, 2));
  const markdown = [
    `# V4 真实双窗口 GUI 旅程 18（${report.recordedAt.slice(0, 10)}）`,
    "",
    `- VSIX: \`${report.vsix}\` (v${report.vsixVersion})`,
    `- Provider: ${report.provider?.mode === "real" ? `real \`${report.provider.baseUrl}\` / \`${report.provider.model}\`` : "fixture（GUI 证据，不是真实模型证据）"}`,
    "- 窗口 1：直接打开项目文件夹；窗口 2：通过同一文件夹的 `.code-workspace` 在同一个 VS Code 实例中打开第二个真实窗口。",
    "- 两个窗口共享同一个 `--user-data-dir`，因此共享学习根目录、Provider 凭据与 sidecar 数据目录。",
    "",
    "## 结果",
    "",
    `- 状态：**${report.status}**`,
    `- 计划：\`${report.plan.id ?? "?"}\`，并发前 revision ${report.plan.revisionBefore ?? "?"}，并发后 ${report.plan.revisionAfter ?? "?"}，重载后 ${report.plan.revisionAfterReload ?? "?"}`,
    `- 窗口 1 冲突文案：${report.concurrency.window1ConflictCopy ?? "?"}`,
    `- 窗口 2 冲突文案：${report.concurrency.window2ConflictCopy ?? "?"}`,
    "",
    "## 断言",
    "",
    ...Object.entries(report.assertions ?? {}).map(([key, value]) => `- ${key}: ${value}`),
    "",
    report.error ? `## 错误\n\n\`${report.error}\`` : "",
    "",
    "> 本文件只记录真实 VS Code 窗口中的 GUI 证据。Fixture provider 的回复不构成真实模型（P）证据。",
    "",
  ].join("\n");
  fs.writeFileSync(path.join(outDir, "README.md"), markdown);
  await app.close().catch(() => undefined);
  fixture?.server.close();
  console.log(`DUAL_WINDOW_JOURNEY_${report.status} ${path.relative(repoRoot, outDir)}`);
  if (report.status !== "PASS") process.exitCode = 1;
}
