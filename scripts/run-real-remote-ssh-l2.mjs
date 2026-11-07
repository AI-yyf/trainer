#!/usr/bin/env node
/**
 * Real Remote-SSH L2 run (141s) — steps 2–6.
 *
 * Launches the actual VS Code Electron app against `ssh-remote+141s`
 * (workspace /mnt/vdb1/yunfei.yan/trainer-e2e) with an isolated profile,
 * seeds only the local Trainer data root (the native folder picker cannot be
 * driven headlessly), and drives the real workbench through Playwright.
 *
 * Requirements on the host: Remote-SSH (classic exec-server disabled for the
 * 1.127/0.124 navigator migration shim), companion installed in the remote
 * server's extensions dir, local Trainer VSIX installed in the isolated dir.
 *
 * Usage:
 *   PROBE_PROVIDER_BASE_URL=... PROBE_PROVIDER_API_KEY=... \
 *   PROBE_PROVIDER_MODEL=MiniMax-M2.7 \
 *   GUI_OUT_DIR=output/remote-ssh-l2/2026-11-07 \
 *   node scripts/run-real-remote-ssh-l2.mjs
 */
import { _electron } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";

const repoRoot = path.resolve(import.meta.dirname, "..");
const packageJson = JSON.parse(
  fs.readFileSync(path.join(repoRoot, "extension", "package.json"), "utf8"),
);
const electronicBinary = "/Applications/Visual Studio Code.app/Contents/MacOS/Electron";
const outDir = path.resolve(
  repoRoot,
  process.env.GUI_OUT_DIR ?? "output/remote-ssh-l2/run",
);
const profileRoot = "/tmp/trainer-remote-profile";
const userDataDir = path.join(profileRoot, "user");
const extensionsDir = path.join(profileRoot, "extensions");
const learningRoot = path.join(profileRoot, "learning");
const remoteHost = process.env.REMOTE_SSH_HOST ?? "141s";
const remoteFolder = process.env.REMOTE_SSH_FOLDER ?? "/mnt/vdb1/yunfei.yan/trainer-e2e";
fs.mkdirSync(outDir, { recursive: true });
fs.mkdirSync(learningRoot, { recursive: true });

const baseUrl = required("PROBE_PROVIDER_BASE_URL");
const apiKey = required("PROBE_PROVIDER_API_KEY");
const model = process.env.PROBE_PROVIDER_MODEL ?? "MiniMax-M2.7";
const steps = [];

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}
function record(step, payload) {
  steps.push({ step, at: new Date().toISOString(), ...payload });
  fs.writeFileSync(
    path.join(outDir, "report.json"),
    `${JSON.stringify({ steps, ok: steps.every((s) => s.ok !== false) }, null, 2)}\n`,
  );
  const safe = { ...payload };
  delete safe.apiKey;
  console.log(`[step] ${step}`, JSON.stringify(safe).slice(0, 480));
}
function readMementoObject(value) {
  const text = Buffer.isBuffer(value) ? value.toString("utf8") : typeof value === "string" ? value : "";
  if (!text) return {};
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}
function readMementoKeys(value) {
  const text = Buffer.isBuffer(value) ? value.toString("utf8") : typeof value === "string" ? value : "";
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed.filter((k) => typeof k === "string") : [];
  } catch {
    return [];
  }
}
function seedLearningFolder() {
  const directories = [
    "Projects", "Knowledge", "Skills", "Agents", "Assets", ".trainer",
    path.join(".trainer", "memory"), path.join(".trainer", "plans"),
    path.join(".trainer", "indexes"), path.join(".trainer", "checkpoints"),
    path.join(".trainer", "logs"), path.join(".trainer", "cache"),
  ];
  for (const directory of directories) fs.mkdirSync(path.join(learningRoot, directory), { recursive: true });
  const now = new Date().toISOString();
  fs.writeFileSync(
    path.join(learningRoot, ".trainer", "workspace.json"),
    `${JSON.stringify({
      schemaVersion: 2, kind: "trainer-workspace", rootPath: learningRoot,
      canonicalRootPath: learningRoot, legacyRootPaths: [], manifestRevision: 1,
      pathRevision: 0, identityStatus: "pending", createdAt: now, updatedAt: now,
      directories, projects: {},
    }, null, 2)}\n`,
  );
  const globalStorageDir = path.join(userDataDir, "User", "globalStorage");
  fs.mkdirSync(globalStorageDir, { recursive: true });
  const database = new DatabaseSync(path.join(globalStorageDir, "state.vscdb"));
  try {
    database.exec("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)");
    const extensionId = "local.trainer-extension";
    const extensionState = readMementoObject(
      database.prepare("SELECT value FROM ItemTable WHERE key = ?").get(extensionId)?.value,
    );
    extensionState["trainer.workspace.root.v1"] = learningRoot;
    database.prepare("INSERT INTO ItemTable (key, value) VALUES (?, ?)").run(
      extensionId, JSON.stringify(extensionState),
    );
    const keyIndex = `extensionKeys/${extensionId}@${packageJson.version}`;
    const mementoKeys = readMementoKeys(
      database.prepare("SELECT value FROM ItemTable WHERE key = ?").get(keyIndex)?.value,
    );
    if (!mementoKeys.includes("trainer.workspace.root.v1")) mementoKeys.push("trainer.workspace.root.v1");
    database.prepare("INSERT INTO ItemTable (key, value) VALUES (?, ?)").run(
      keyIndex, JSON.stringify(mementoKeys),
    );
  } finally {
    database.close();
  }
}

function webviewFrame(page) {
  const frame = page
    .frames()
    .find((candidate) => candidate.url().includes("vscode-webview://") && candidate.url().includes("fake.html"));
  if (!frame) throw new Error("Trainer webview frame not found");
  return frame;
}
async function bodyText(frame) {
  return (await frame.locator("body").innerText()).replace(/\s+/g, " ").trim();
}
async function pageScreenshot(page, name) {
  const file = path.join(outDir, `${name}.png`);
  await page.screenshot({ path: file, timeout: 30_000 });
  return path.relative(repoRoot, file);
}
async function commandPalette(page, command) {
  await page.keyboard.press("Meta+Shift+P");
  await page.waitForTimeout(700);
  await page.keyboard.type(command);
  await page.waitForTimeout(700);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(1500);
}
async function waitForBody(frame, pattern, timeout = 120_000) {
  const start = Date.now();
  let last = "";
  while (Date.now() - start < timeout) {
    last = await bodyText(frame);
    if (pattern.test(last)) return last;
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  throw new Error(`Timed out waiting for ${pattern}; body=${last.slice(0, 700)}`);
}
async function waitForAssistantReply(frame, timeout = 300_000) {
  const start = Date.now();
  let lastText = "";
  let stableTicks = 0;
  while (Date.now() - start < timeout) {
    const assistantBodies = frame
      .locator(".message-bubble__body")
      .filter({ has: frame.locator(".message-bubble__assistant-rail") });
    const count = await assistantBodies.count();
    if (count > 0) {
      let current = "";
      let streaming = 0;
      for (let index = count - 1; index >= 0; index -= 1) {
        const bubble = assistantBodies.nth(index);
        const text = (await bubble.innerText()).replace(/\s+/g, " ").trim();
        if (text.length < 20 || /^正在|第一段可见回复|教练正在思考/.test(text)) continue;
        current = text;
        streaming = await bubble.locator(".coach-streaming-dots:visible, .coach-cursor:visible").count();
        break;
      }
      if (current) {
        stableTicks = current === lastText ? stableTicks + 1 : 0;
        lastText = current;
        if (lastText.length > 80 && streaming === 0 && stableTicks >= 4) return lastText;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  throw new Error(`Assistant reply did not finish; last=${lastText.slice(0, 600)}`);
}
async function acceptTrust(page) {
  const trust = page.getByRole("button", { name: /Trust Folder & Continue|Yes, I trust|信任/i }).first();
  if (await trust.count().catch(() => 0)) {
    await trust.click().catch(() => {});
    await page.waitForTimeout(4000);
  }
  const reload = page.getByRole("button", { name: /Reload Window/i }).first();
  if (await reload.count().catch(() => 0)) {
    await reload.click().catch(() => {});
    await page.waitForTimeout(8000);
  }
}
async function openCoach(page) {
  await commandPalette(page, "Trainer: Open Coach Sidebar");
  await page.waitForTimeout(7000);
  return webviewFrame(page);
}
async function runProviderTest(page, frame, attempts = 3) {
  let lastText = "";
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const button = frame.locator("button:visible").filter({ hasText: /测试连接|重新测试/ }).last();
    if (!(await button.count())) throw new Error("Provider test button is not visible");
    await button.click();
    await page.waitForTimeout(2500);
    lastText = await waitForBody(frame, /模型已就绪|最近测试 通过|暂时出错|连接需要检查|测试失败|未通过/, 180_000);
    if (/模型已就绪|最近测试 通过/.test(lastText)) return { ok: true, attempt, text: lastText };
    record("provider-test-retry", { ok: false, attempt, text: lastText.slice(-500) });
    await page.waitForTimeout(2000);
  }
  return { ok: false, attempts, text: lastText };
}

seedLearningFolder();

const app = await _electron.launch({
  executablePath: electronicBinary,
  args: [
    "--user-data-dir", userDataDir,
    "--extensions-dir", extensionsDir,
    "--skip-welcome",
    "--skip-release-notes",
    "--new-window",
    "--remote", `ssh-remote+${remoteHost}`, remoteFolder,
  ],
  timeout: 180_000,
});

try {
  const page = await app.firstWindow({ timeout: 120_000 });
  await page.waitForTimeout(12_000);
  await acceptTrust(page);
  // Wait for the remote extension host / sidebar.
  const start = Date.now();
  let frame;
  let lastPageText = "";
  while (Date.now() - start < 240_000) {
    lastPageText = (await page.locator("body").innerText()).replace(/\s+/g, " ").trim();
    if (/EXTENSIONS|EXPLORER/.test(lastPageText) && !/Opening Remote|Connect to VS Code Server/.test(lastPageText)) {
      break;
    }
    await page.waitForTimeout(5000);
  }
  await page.waitForTimeout(5000);
  frame = await openCoach(page);

  // Step 2 — activity bar / Coach sidebar.
  const step2Text = await bodyText(frame);
  record("l2-02-coach-sidebar", {
    ok: step2Text.includes("对话") && step2Text.includes("学习") && step2Text.includes("资料"),
    text: step2Text.slice(0, 600),
    pageTitle: await page.title(),
    screenshot: await pageScreenshot(page, "02-coach-sidebar"),
  });

  // Step 3 — five views.
  await frame.getByRole("button", { name: "学习", exact: true }).first().click();
  await page.waitForTimeout(2500);
  const planText = await bodyText(frame);
  await pageScreenshot(page, "03-plan");
  // Training lives inside Learning; open it before leaving the destination.
  await frame.getByRole("button", { name: "训练", exact: true }).first().click();
  await page.waitForTimeout(2500);
  const trainingText = await bodyText(frame);
  await pageScreenshot(page, "03-training");
  await frame.getByRole("button", { name: "资料", exact: true }).first().click();
  await page.waitForTimeout(2500);
  const resourcesText = await bodyText(frame);
  await pageScreenshot(page, "03-resources");
  await frame.getByRole("button", { name: "对话", exact: true }).first().click();
  await page.waitForTimeout(2000);
  const coachText = await bodyText(frame);
  await frame.locator("button[title*='设置'], button[aria-label*='设置']").first().click().catch(async () => {
    await frame.getByRole("button", { name: "设置", exact: true }).first().click();
  });
  await page.waitForTimeout(3000);
  const settingsText = await bodyText(frame);
  await pageScreenshot(page, "03-settings");
  record("l2-03-five-views", {
    ok:
      /当前学习|选择工作区/.test(planText) &&
      /资料库/.test(resourcesText) &&
      /训练/.test(trainingText) &&
      /对话/.test(coachText) &&
      /Trainer 设置|设置/.test(settingsText),
    planText: planText.slice(0, 240),
    resourcesText: resourcesText.slice(0, 240),
    trainingText: trainingText.slice(0, 240),
    settingsText: settingsText.slice(0, 300),
    screenshot: await pageScreenshot(page, "03-five-views"),
  });

  // Provider setup inside the remote window's local UI host.
  const category = frame.locator("[data-settings-category=connection]");
  if (await category.count()) {
    await category.first().click();
    await page.waitForTimeout(2000);
  }
  const quickPaste = frame.locator('input[placeholder*="连接信息"]').first();
  if (await quickPaste.count()) {
    await quickPaste.fill(JSON.stringify({ url: baseUrl, key: apiKey }));
    await page.waitForTimeout(1800);
  }
  const servicePlaceholder = 'input[placeholder="例如 localhost:1234/v1 或 api.deepseek.com/v1"]';
  for (let attempt = 0; attempt < 3; attempt += 1) {
    if (await frame.locator(servicePlaceholder).count()) break;
    const edit = frame.getByRole("button", { name: "编辑配置", exact: true });
    if (await edit.count()) {
      await edit.first().click();
      await page.waitForTimeout(2500);
    } else {
      await page.waitForTimeout(2000);
    }
  }
  const serviceRoot = frame.locator(servicePlaceholder).first();
  if (!(await serviceRoot.count())) {
    record("l2-provider-form-missing", { ok: false, text: (await bodyText(frame)).slice(0, 1200) });
    throw new Error("Provider form did not render");
  }
  await serviceRoot.fill(baseUrl);
  await frame.locator('input[placeholder="连接已保存，还需要 API key。"]').first().fill(apiKey);
  await frame.locator('input[placeholder="例如 kimi-k3"]').first().fill(model);
  await page.waitForTimeout(1000);
  await frame.locator("button:visible", { hasText: "保存并使用此连接" }).last().click();
  await page.waitForTimeout(5000);
  const savedText = await bodyText(frame);
  record("l2-provider-saved", {
    ok: savedText.includes(model),
    text: savedText.slice(0, 700),
    screenshot: await pageScreenshot(page, "04-provider-saved"),
  });
  const test = await runProviderTest(page, frame, 3);
  record("l2-provider-test", {
    ok: test.ok,
    attempt: test.attempt,
    text: test.text.slice(-700),
    screenshot: await pageScreenshot(page, "04-provider-test"),
  });
  if (!test.ok) throw new Error("Provider test failed in remote window");

  // Step 4 — real message about the remote project.
  await frame.getByRole("button", { name: "对话", exact: true }).first().click();
  await page.waitForTimeout(2500);
  const discovery = frame.getByRole("button", { name: "加入 Trainer", exact: true }).first();
  let attached = false;
  if (await discovery.count()) {
    await discovery.click();
    await page.waitForTimeout(5000);
    attached = true;
  }
  const composer = frame.locator('textarea, input[placeholder*="消息"], [contenteditable="true"]').first();
  await composer.click();
  await composer.fill("这个远程项目的 Queue.pop 在什么情况下会抛 IndexError？请结合 src/queue_lock.py 讲清楚。");
  await page.waitForTimeout(600);
  await frame.getByRole("button", { name: /发送/ }).first().click();
  let reply = "";
  try {
    reply = await waitForAssistantReply(frame, 240_000);
  } catch (error) {
    reply = (await bodyText(frame)).slice(-800);
    record("l2-04-remote-reply-partial", {
      ok: false, attached, reason: String(error).slice(0, 260), text: reply,
      screenshot: await pageScreenshot(page, "04-remote-reply-partial"),
    });
  }
  if (reply) {
    record("l2-04-remote-reply", {
      ok: reply.length > 80 && /IndexError|None|_lock|queue_lock/.test(reply),
      attached,
      chars: reply.length,
      text: reply.slice(0, 1200),
      screenshot: await pageScreenshot(page, "04-remote-reply"),
    });
  }

  // Step 5 — attach the remote workspace + trust state in Settings.
  await frame.locator("button[title*='设置'], button[aria-label*='设置']").first().click().catch(async () => {
    await frame.getByRole("button", { name: "设置", exact: true }).first().click();
  });
  await page.waitForTimeout(2500);
  const workspaceCategory = frame.locator("[data-settings-category=workspace]");
  if (await workspaceCategory.count()) {
    await workspaceCategory.first().click();
    await page.waitForTimeout(2500);
  }
  const workspaceSettings = await bodyText(frame);
  const windowText = (await page.locator("body").innerText()).replace(/\s+/g, " ").trim();
  const windowTrusted = !/Restricted Mode/.test(windowText);
  await pageScreenshot(page, "05-workspace-settings");
  record("l2-05-workspace-trust", {
    ok:
      /trainer-e2e/.test(workspaceSettings) &&
      /vscode-remote:\/\/ssh-remote\+/.test(workspaceSettings) &&
      windowTrusted,
    windowTrusted,
    text: workspaceSettings.slice(0, 900),
    screenshot: await pageScreenshot(page, "05-workspace-trust"),
  });

  // Step 6 — companion handshake in the remote support section.
  const remoteSupport = frame.locator("[data-settings-subsection=remote-support]");
  let companionText = await bodyText(frame);
  if (await remoteSupport.count()) {
    companionText = (await remoteSupport.first().innerText()).replace(/\s+/g, " ").trim();
    const install = remoteSupport.getByRole("button", { name: /安装远程支持|远程支持已就绪|等待 Reload/ }).first();
    if ((await install.count()) && /安装远程支持/.test(await install.innerText())) {
      await install.click();
      await page.waitForTimeout(12_000);
      await acceptTrust(page);
      await page.waitForTimeout(5000);
      companionText = (await remoteSupport.first().innerText().catch(() => companionText))
        .replace(/\s+/g, " ").trim();
    }
  }
  record("l2-06-companion-handshake", {
    ok: /远程支持已就绪|已就绪/.test(companionText),
    text: companionText.slice(0, 900),
    screenshot: await pageScreenshot(page, "06-companion"),
  });
} finally {
  fs.writeFileSync(
    path.join(outDir, "report.json"),
    `${JSON.stringify({ steps, ok: steps.every((s) => s.ok !== false) }, null, 2)}\n`,
  );
  await app.close().catch(() => {});
}
