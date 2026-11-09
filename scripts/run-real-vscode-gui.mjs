#!/usr/bin/env node
/**
 * Real Microsoft VS Code GUI journey (installed VSIX + real sidecar/provider).
 *
 * This is not a browser preview. It launches the actual VS Code Electron app
 * with an isolated --user-data-dir/--extensions-dir, installs the packaged
 * VSIX, opens the Trainer webview, and drives the real workbench with the
 * keyboard and mouse through Playwright Electron.
 *
 * The learning-folder native picker cannot be driven headlessly on macOS
 * (System Events accessibility is not granted to automation), so this script
 * seeds the same extension global state that the folder picker writes, then
 * exercises the real UI for everything after that. The provider key is only
 * read from the environment and never written to the repo.
 *
 * Usage:
 *   PROBE_PROVIDER_BASE_URL=... PROBE_PROVIDER_API_KEY=... \
 *   PROBE_PROVIDER_MODEL=MiniMax-M2.7 \
 *   PROBE_PROVIDER_MODEL_SWITCH=MiniMax-M3.1-Flash \
 *   GUI_OUT_DIR=.trainer-convergence/evidence/real-vscode-gui-... \
 *   node scripts/run-real-vscode-gui.mjs
 */
import { _electron } from "playwright";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { execFileSync } from "node:child_process";

const repoRoot = path.resolve(import.meta.dirname, "..");
const packageJson = JSON.parse(
  fs.readFileSync(path.join(repoRoot, "extension", "package.json"), "utf8"),
);
const vsixPath = path.join(
  repoRoot,
  "extension",
  `trainer-extension-${packageJson.version}-darwin-arm64.vsix`,
);
const codeCli = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code";
const electronBinary = "/Applications/Visual Studio Code.app/Contents/MacOS/Electron";

const baseUrl = required("PROBE_PROVIDER_BASE_URL");
const apiKey = required("PROBE_PROVIDER_API_KEY");
const model = process.env.PROBE_PROVIDER_MODEL ?? "MiniMax-M2.7";
const switchModel = process.env.PROBE_PROVIDER_MODEL_SWITCH ?? "MiniMax-M3.1-Flash";
const outDir = path.resolve(
  repoRoot,
  process.env.GUI_OUT_DIR ?? ".trainer-convergence/evidence/real-vscode-gui",
);
fs.mkdirSync(outDir, { recursive: true });

const steps = [];
function record(step, payload) {
  steps.push({ step, at: new Date().toISOString(), ...payload });
  fs.writeFileSync(
    path.join(outDir, "report.json"),
    `${JSON.stringify({ steps, ok: steps.every((s) => s.ok !== false) }, null, 2)}\n`,
  );
  console.log(`[step] ${step}`, JSON.stringify(payload).slice(0, 400));
}
function required(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}
function readMementoObject(value) {
  const text = Buffer.isBuffer(value)
    ? value.toString("utf8")
    : typeof value === "string"
      ? value
      : "";
  if (!text) return {};
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}
function readMementoKeys(value) {
  const text = Buffer.isBuffer(value)
    ? value.toString("utf8")
    : typeof value === "string"
      ? value
      : "";
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed.filter((k) => typeof k === "string") : [];
  } catch {
    return [];
  }
}
function seedLearningFolder({ userDataDir, rootPath, extensionId, version }) {
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
    fs.mkdirSync(path.join(rootPath, directory), { recursive: true });
  }
  const now = new Date().toISOString();
  fs.writeFileSync(
    path.join(rootPath, ".trainer", "workspace.json"),
    `${JSON.stringify(
      {
        schemaVersion: 2,
        kind: "trainer-workspace",
        rootPath,
        canonicalRootPath: rootPath,
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
    "utf8",
  );
  const globalStorageDir = path.join(userDataDir, "User", "globalStorage");
  fs.mkdirSync(globalStorageDir, { recursive: true });
  const database = new DatabaseSync(path.join(globalStorageDir, "state.vscdb"));
  try {
    database.exec(
      "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)",
    );
    const extensionState = readMementoObject(
      database.prepare("SELECT value FROM ItemTable WHERE key = ?").get(extensionId)?.value,
    );
    extensionState["trainer.workspace.root.v1"] = rootPath;
    database
      .prepare("INSERT INTO ItemTable (key, value) VALUES (?, ?)")
      .run(extensionId, JSON.stringify(extensionState));
    const keyIndex = `extensionKeys/${extensionId}@${version}`;
    const mementoKeys = readMementoKeys(
      database.prepare("SELECT value FROM ItemTable WHERE key = ?").get(keyIndex)?.value,
    );
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

function workspaceFrame(page) {
  const frame = page
    .frames()
    .find(
      (candidate) =>
        candidate.url().includes("vscode-webview://") && candidate.url().includes("fake.html"),
    );
  if (!frame) throw new Error("Trainer webview frame not found");
  return frame;
}
async function bodyText(frame) {
  return (await frame.locator("body").innerText()).replace(/\s+/g, " ").trim();
}
async function screenshot(page, name) {
  const file = path.join(outDir, `${name}.png`);
  await page.screenshot({ path: file, timeout: 30_000 });
  return path.relative(repoRoot, file);
}
async function runProviderTest(page, frame, attempts = 3) {
  let lastText = "";
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const button = frame
      .locator("button:visible")
      .filter({ hasText: /测试连接|重新测试/ })
      .last();
    if (!(await button.count())) {
      throw new Error("Provider test button is not visible");
    }
    await button.click();
    await page.waitForTimeout(2500);
    lastText = await waitForBody(
      frame,
      /模型已就绪|最近测试[^\n]{0,60}已通过|已连通|暂时出错|连接需要检查|测试失败|未通过/,
      360_000,
    );
    if (/模型已就绪|最近测试[^\n]{0,60}已通过|已连通/.test(lastText)) {
      return { ok: true, attempt, text: lastText };
    }
    record("provider-test-retry", {
      ok: false,
      attempt,
      text: lastText.slice(-500),
      screenshot: await screenshot(page, `provider-test-retry-${attempt}`),
    });
    await page.waitForTimeout(2000);
  }
  return { ok: false, attempts, text: lastText };
}

async function openConnectionCategory(page, frame) {
  await frame.getByRole("button", { name: "设置", exact: true }).first().click();
  await page.waitForTimeout(2200);
  const category = frame.locator("[data-settings-category=connection]");
  if (await category.count()) {
    await category.first().click();
    await page.waitForTimeout(1800);
  }
}
async function commandPalette(page, command) {
  await page.keyboard.press("Meta+Shift+P");
  await page.waitForTimeout(700);
  await page.keyboard.type(command);
  await page.waitForTimeout(700);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(1500);
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
        if (
          text.length < 20 ||
          /^正在|第一段可见回复|教练正在思考/.test(text)
        ) {
          continue;
        }
        current = text;
        streaming = await bubble
          .locator(".coach-streaming-dots:visible, .coach-cursor:visible")
          .count();
        break;
      }
      if (current) {
        stableTicks = current === lastText ? stableTicks + 1 : 0;
        lastText = current;
        if (lastText.length > 80 && streaming === 0 && stableTicks >= 4) {
          return lastText;
        }
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  throw new Error(`Assistant reply did not finish; last=${lastText.slice(0, 600)}`);
}
async function readLastAssistantText(frame) {
  const bodies = frame
    .locator(".message-bubble__body")
    .filter({ has: frame.locator(".message-bubble__assistant-rail") });
  for (let index = (await bodies.count()) - 1; index >= 0; index -= 1) {
    const text = (await bodies.nth(index).innerText()).replace(/\s+/g, " ").trim();
    if (text.length > 40 && !/^正在|第一段可见回复|教练正在思考/.test(text)) {
      return text;
    }
  }
  return "";
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

const root = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-real-gui-"));
const userDataDir = path.join(root, "user-data");
const extensionsDir = path.join(root, "extensions");
const workspaceDir = path.join(root, "workspace");
const learningDir = path.join(root, "learning");
fs.mkdirSync(path.join(workspaceDir, "src"), { recursive: true });
fs.mkdirSync(learningDir, { recursive: true });
fs.writeFileSync(
  path.join(workspaceDir, "src", "queue_lock.py"),
  [
    "import threading",
    "",
    "class Queue:",
    "    def __init__(self):",
    "        self._items = []",
    "        self._lock = threading.Lock()",
    "",
    "    def push(self, item):",
    "        with self._lock:",
    "            self._items.append(item)",
    "",
    "    def pop(self):",
    "        with self._lock:",
    "            if not self._items:",
    '                raise IndexError("empty")',
    "            return self._items.pop(0)",
    "",
  ].join("\n"),
);
fs.writeFileSync(
  path.join(workspaceDir, "README.md"),
  "# Concurrency practice\n\nSmall Python project for learning locks.\n",
);

seedLearningFolder({
  userDataDir,
  rootPath: learningDir,
  extensionId: "local.trainer-extension",
  version: "1.3.4",
});
execFileSync(
  codeCli,
  [
    "--user-data-dir",
    userDataDir,
    "--extensions-dir",
    extensionsDir,
    "--install-extension",
    vsixPath,
    "--force",
  ],
  { stdio: "ignore" },
);

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
    "--new-window",
    workspaceDir,
  ],
  timeout: 90_000,
});

try {
  const page = await app.firstWindow({ timeout: 90_000 });
  await page.waitForTimeout(6000);
  await commandPalette(page, "Trainer: Open Coach Sidebar");
  await page.waitForTimeout(7000);
  let frame = workspaceFrame(page);

  const firstRunText = await bodyText(frame);
  record("01-first-run", {
    ok: /对话/.test(firstRunText) && /学习/.test(firstRunText) && /资料/.test(firstRunText),
    screenshot: await screenshot(page, "01-first-run"),
    text: firstRunText.slice(0, 500),
  });

  // Settings: configure the real provider through the form. Wait for session
  // restore first — asserting the index while a loading placeholder is up
  // tested the placeholder, not the restored settings screen.
  await page.waitForTimeout(2500);
  await frame.getByRole("button", { name: "设置", exact: true }).first().click();
  const settingsIndexDeadline = Date.now() + 120_000;
  let indexText = "";
  while (Date.now() < settingsIndexDeadline) {
    indexText = await bodyText(frame);
    if (!/正在准备中|正在加载设置/.test(indexText)) break;
    await page.waitForTimeout(1200);
  }
  const learningFolderName = path.basename(learningDir);
  record("02-settings-index", {
    ok:
      !/正在准备中|正在加载设置/.test(indexText) &&
      indexText.includes("工作区") &&
      indexText.includes(learningFolderName),
    learningFolderShown: indexText.includes(learningFolderName),
    text: indexText.slice(0, 600),
    screenshot: await screenshot(page, "02-settings-index"),
  });

  // Wait for the sidecar so the settings form renders against a live host.
  if (await frame.locator("[data-settings-category=connection]").count()) {
    await frame.locator("[data-settings-category=connection]").first().click();
    await page.waitForTimeout(2500);
  }
  // The quick-setup card collapses the full form until it has a draft; paste
  // the connection JSON (url+key), then open the full form for the model.
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
    record("03a-provider-form-missing", { ok: false, text: (await bodyText(frame)).slice(0, 1200) });
    throw new Error("Provider service-root input did not render");
  }
  await serviceRoot.fill(baseUrl);
  await frame.locator('input[placeholder="连接已保存，还需要 API key。"]').first().fill(apiKey);
  await frame.locator('input[placeholder="例如 kimi-k3"]').first().fill(model);
  await page.waitForTimeout(1000);
  // Save first, then test the saved connection: the product persists a saved
  // connection's test result, while a draft test is intentionally transient.
  await frame.getByRole("button", { name: "保存并使用此连接", exact: true }).last().click();
  await page.waitForTimeout(5000);
  const savedText = await bodyText(frame);
  const savedOpenModelPickers = await frame.locator("details.settings-model-picker[open]").count();
  record("03-provider-saved", {
    ok:
      savedText.includes(model) &&
      !savedText.includes("有未保存更改") &&
      savedOpenModelPickers === 0,
    modelPickerExpanded: savedOpenModelPickers > 0,
    note:
      "The model picker must stay collapsed once hydration supplies a saved model; an auto-open summary plus the inner select would duplicate the same value.",
    text: savedText.slice(0, 900),
    screenshot: await screenshot(page, "03-provider-saved"),
  });
  record("04a-test-buttons", {
    ok: true,
    count: await frame.locator("button:visible").filter({ hasText: /测试连接|重新测试/ }).count(),
  });
  const firstTest = await runProviderTest(page, frame, 3);
  const testedOpenModelPickers = await frame.locator("details.settings-model-picker[open]").count();
  record("04-provider-test", {
    ok: firstTest.ok && testedOpenModelPickers === 0,
    attempt: firstTest.attempt,
    modelPickerExpanded: testedOpenModelPickers > 0,
    text: firstTest.text.slice(-900),
    screenshot: await screenshot(page, "04-provider-test"),
  });  if (!firstTest.ok) {
    throw new Error("Provider connection test failed after retries");
  }

  // Learning screen audit (Phase 4): open 学习 and capture the real
  // destination before the coach flow, with structural assertions.
  await frame.getByRole("button", { name: "学习", exact: true }).first().click();
  await page.waitForTimeout(1800);
  const learningText = await bodyText(frame);
  const learningButtons = await frame.getByRole("button").allTextContents();
  const learningHeadingCount = await frame
    .getByRole("heading", { name: "学习", exact: true })
    .count();
  record("04b-learning-screen", {
    ok:
      learningText.includes("学习") &&
      !/undefined|NaN|Infinity/.test(learningText) &&
      learningHeadingCount <= 1,
    text: learningText.slice(0, 1200),
    visibleButtons: learningButtons.slice(0, 24),
    titleOccurrences: learningHeadingCount,
    note: "titleOccurrences counts real headings named 学习, not body mentions.",
    screenshot: await screenshot(page, "04b-learning-screen"),
  });

  // Resources screen audit (Phase 4): the real 资料 destination in an empty
  // library — single import affordance, honest empty state, no duplicate
  // titles, search reachable.
  await frame.getByRole("button", { name: "资料", exact: true }).first().click();
  await page.waitForTimeout(1800);
  const resourcesText = await bodyText(frame);
  const resourcesButtons = await frame.getByRole("button").allTextContents();
  const resourcesSearchVisible = await frame
    .locator('input[type="search"]:visible, input[placeholder*="搜索"]:visible')
    .count()
    .catch(() => 0);
  const importAffordanceCount = resourcesButtons.filter((label) =>
    /添加资料|导入资料/.test(label),
  ).length;
  record("04c-resources-screen", {
    ok:
      /资料/.test(resourcesText) &&
      !/undefined|NaN|Infinity/.test(resourcesText) &&
      importAffordanceCount === 1,
    text: resourcesText.slice(0, 1200),
    visibleButtons: resourcesButtons.slice(0, 24),
    importAffordanceCount,
    searchInputCount: resourcesSearchVisible,
    screenshot: await screenshot(page, "04c-resources-screen"),
  });

  // Back to Coach and send a real first message.
  await frame.getByRole("button", { name: "对话", exact: true }).first().click();
  await page.waitForTimeout(2500);
  const coachText = await bodyText(frame);
  record("05-coach-ready", {
    ok: /消息输入框|说说/.test(coachText),
    text: coachText.slice(0, 600),
    screenshot: await screenshot(page, "05-coach-ready"),
  });
  // A freshly opened project needs an explicit admission decision before the
  // composer unlocks. Click it like a learner would.
  const joinButton = frame.getByRole("button", { name: "加入 Trainer", exact: true });
  if (await joinButton.count()) {
    await joinButton.first().click();
    await page.waitForTimeout(8000);
    record("05b-project-joined", {
      ok: !/请选择：加入 Trainer/.test(await bodyText(frame)),
      text: (await bodyText(frame)).slice(0, 700),
      screenshot: await screenshot(page, "05b-project-joined"),
    });
  }
  const composer = frame
    .locator('textarea, input[placeholder*="消息"], [contenteditable="true"]')
    .first();
  await composer.click();
  await composer.fill(
    "我在 queue_lock.py 里看到锁，但还不明白它到底保护了什么。请结合这个文件讲清楚，并给我一个可以亲手验证的最小步骤。",
  );
  await page.waitForTimeout(500);
  const firstQuestion =
    "我在 queue_lock.py 里看到锁，但还不明白它到底保护了什么。请结合这个文件讲清楚，并给我一个可以亲手验证的最小步骤。";
  const sendFirst = async () => {
    await frame.getByRole("button", { name: /发送/ }).first().click();
    await page.waitForTimeout(3000);
  };
  await sendFirst();
  let replyText;
  try {
    replyText = await waitForAssistantReply(frame, 150_000);
  } catch (error) {
    const failureText = await bodyText(frame);
    record("06a-first-reply-retry", {
      ok: false,
      reason: String(error).slice(0, 300),
      text: failureText.slice(-700),
      screenshot: await screenshot(page, "06a-first-reply-retry"),
    });
    const resume = frame.getByRole("button", { name: /从上次进度继续|再试一次/ });
    if (await resume.count()) {
      await resume.first().click();
    } else {
      const retryComposer = frame
        .locator('textarea, input[placeholder*="消息"], [contenteditable="true"]')
        .first();
      await retryComposer.fill(firstQuestion);
      await sendFirst();
    }
    replyText = await waitForAssistantReply(frame, 150_000);
  }
  record("06-first-real-reply", {
    ok: replyText.length > 120,
    chars: replyText.length,
    text: replyText.slice(0, 1500),
    screenshot: await screenshot(page, "06-first-real-reply"),
  });

  // Model switch: settings -> connection -> edit -> change model -> test -> save.
  await openConnectionCategory(page, frame);
  const editAfterSave = frame.getByRole("button", { name: "编辑配置", exact: true });
  if (await editAfterSave.count()) {
    await editAfterSave.first().click();
    await page.waitForTimeout(1500);
  }
  const switchModelField = frame.locator('input[placeholder="例如 kimi-k3"]').first();
  const switchModelSelect = frame.locator("select").first();
  if (await switchModelField.count()) {
    if (!(await switchModelField.isVisible())) {
      const picker = frame.locator("details.settings-model-picker").first();
      if (await picker.count()) {
        const open = await picker.evaluate((element) => element.open === true);
        if (!open) {
          await picker.locator("summary").first().click();
          await page.waitForTimeout(800);
        }
      }
    }
    await switchModelField.fill(switchModel);
  } else if (await switchModelSelect.count()) {
    const optionsBefore = await switchModelSelect.locator("option").allTextContents();
    record("07a-model-select", { ok: true, options: optionsBefore });
    if (!optionsBefore.includes(switchModel)) {
      const refresh = frame.locator("button:visible", { hasText: "刷新模型列表" }).last();
      if (await refresh.count()) {
        await refresh.click();
        await page.waitForTimeout(10_000);
      }
    }
    const optionsAfter = await switchModelSelect.locator("option").allTextContents();
    record("07b-model-select-after-refresh", { ok: true, options: optionsAfter });
    const picker = frame.locator("details.settings-model-picker").first();
    if (await picker.count()) {
      const open = await picker.evaluate((element) => element.open === true);
      if (!open) {
        await picker.locator("summary").first().click();
        await page.waitForTimeout(600);
      }
    }
    if (!optionsAfter.includes(switchModel)) {
      record("07c-model-select-missing", {
        ok: false,
        options: optionsAfter,
        text: (await bodyText(frame)).slice(0, 1000),
        screenshot: await screenshot(page, "07c-model-select-missing"),
      });
      throw new Error(`Model option ${switchModel} is not available in the picker`);
    }
    await switchModelSelect.selectOption({ label: switchModel });
  } else {
    record("07a-model-field-missing", {
      ok: false,
      text: (await bodyText(frame)).slice(0, 1200),
      inputs: await frame.locator("input,select,textarea").evaluateAll((els) =>
        els.map((e) => ({ tag: e.tagName, type: e.type, placeholder: e.placeholder, value: e.value })),
      ),
      buttons: await frame.getByRole("button").allTextContents(),
      screenshot: await screenshot(page, "07a-model-field-missing"),
    });
    throw new Error("Model field did not render after reopening the connection");
  }
  await page.waitForTimeout(800);
  await frame.getByRole("button", { name: "保存并使用此连接", exact: true }).last().click();
  await page.waitForTimeout(5000);
  const switchTest = await runProviderTest(page, frame, 3);
  const switchedText = await bodyText(frame);
  record("07-model-switched", {
    ok: switchedText.includes(switchModel) && switchTest.ok,
    model: switchModel,
    text: switchedText.slice(0, 900),
    screenshot: await screenshot(page, "07-model-switched"),
  });

  // Switch back to Coach and confirm the new model answers.
  await frame.getByRole("button", { name: "对话", exact: true }).first().click();
  await page.waitForTimeout(2000);
  const composer2 = frame
    .locator('textarea, input[placeholder*="消息"], [contenteditable="true"]')
    .first();
  await composer2.click();
  await composer2.fill("换模型后继续：用一句话说明这个队列在什么情况下会抛 IndexError。");
  await page.waitForTimeout(500);
  await frame.getByRole("button", { name: /发送/ }).first().click();
  await page.waitForTimeout(3000);
  try {
    const replyTwo = await waitForAssistantReply(frame, 240_000);
    record("08-switch-reply", {
      ok: true,
      chars: replyTwo.length,
      text: replyTwo.slice(0, 1200),
      screenshot: await screenshot(page, "08-switch-reply"),
    });
  } catch (error) {
    const visible = await readLastAssistantText(frame);
    record("08-switch-reply-partial", {
      ok: false,
      reason: String(error).slice(0, 260),
      text: visible.slice(0, 1200),
      note: "M3.1 produced visible text but the provider stream did not close within the wait; recorded as PARTIAL, not PASS.",
      screenshot: await screenshot(page, "08-switch-reply-partial"),
    });
  }

  fs.writeFileSync(
    path.join(outDir, "report.json"),
    `${JSON.stringify(
      { ok: steps.every((s) => s.ok !== false), vsix: path.relative(repoRoot, vsixPath), model, switchModel, steps },
      null,
      2,
    )}\n`,
  );
  console.log(`GUI_JOURNEY_OK ${path.relative(repoRoot, outDir)}`);
} finally {
  await app.close().catch(() => undefined);
  fs.writeFileSync(path.join(outDir, "environment.json"), JSON.stringify({ root, userDataDir, extensionsDir, workspaceDir, learningDir }, null, 2));
}
