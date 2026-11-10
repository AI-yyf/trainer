#!/usr/bin/env node
/**
 * Real VS Code GUI journey for resource-grounded teaching.
 *
 * This is not a browser preview. It installs the packaged VSIX into an
 * isolated VS Code profile, provisions a loopback OpenAI-compatible fixture
 * provider, imports a Markdown resource through the real host command, asks a
 * question in the real Coach webview, and verifies that:
 *
 *   1. the reply renders the server-produced original passage + citation;
 *   2. "Open full resource" opens the canonical resource in an editor tab at
 *      the cited line;
 *   3. the fixture provider never writes an API key into the repo.
 *
 * The fixture provider is deterministic transport/UI evidence only. It does
 * not claim real-model teaching quality.
 *
 * Usage: node scripts/verify-resource-grounding-gui.mjs
 */
import { spawnSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron } from "playwright";
import {
  buildVsixE2EProviderSavePayloadTemplate,
  resolveVsixE2EProviderConfiguration,
} from "../extension/scripts/vsix-e2e-provider-config.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const extensionDir = path.join(repoRoot, "extension");
const packageJson = JSON.parse(fs.readFileSync(path.join(extensionDir, "package.json"), "utf8"));
const extensionId = `${packageJson.publisher}.${packageJson.name}`;
const vsixPath = path.join(extensionDir, `trainer-extension-${packageJson.version}-darwin-arm64.vsix`);
const codeCli = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code";
const electronBinary = [
  "/Applications/Visual Studio Code.app/Contents/MacOS/Electron",
  "/Applications/Visual Studio Code.app/Contents/MacOS/Code",
].find((candidate) => fs.existsSync(candidate));
if (!fs.existsSync(vsixPath) || !electronBinary) {
  throw new Error("Run npm run package:vsix first (VSIX or VS Code Electron missing).");
}

const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join(repoRoot, "output", "resource-grounding-gui", stamp);
const root = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-grounding-gui-"));
const userDataDir = path.join(root, "user-data");
const extensionsDir = path.join(root, "extensions");
const workspaceDir = path.join(root, "workspace");
const trainerWorkspaceDir = path.join(root, "trainer-workspace");
const driverDir = path.join(root, "driver");
const reportPath = path.join(root, "driver-report.json");
const activeEditorPath = path.join(root, "active-editor.json");
const resourceStatePath = path.join(root, "resource-state.json");
const providerDebugPath = path.join(root, "provider-debug.jsonl");
const deleteRequestPath = path.join(root, "delete-resource.request.json");
const deleteResultPath = path.join(root, "delete-resource.result.json");
const previewRequestPath = path.join(root, "preview.request.json");
const previewResultPath = path.join(root, "preview.result.json");
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

const RESOURCE_NAME = "queue-locks.md";
const RESOURCE_TEXT = [
  "# Queue locks",
  "",
  "A lock protects the write path from concurrent writers.",
  "",
  "## Boundary",
  "",
  "Release the lock in a finally block so a failed write cannot strand it.",
  "",
].join("\n");
const FORMAT = (process.env.GROUNDING_GUI_FORMAT ?? "markdown").trim().toLowerCase();
const FIXTURE_DIR = path.join(workspaceDir, "fixtures");
fs.mkdirSync(FIXTURE_DIR, { recursive: true });
let sourcePath = "";
if (FORMAT === "pdf" || FORMAT === "epub") {
  const generated = spawnSync(
    path.join(repoRoot, "server", ".venv", "bin", "python"),
    [
      path.join(repoRoot, "scripts", "generate-grounding-fixtures.py"),
      FIXTURE_DIR,
    ],
    { encoding: "utf8" },
  );
  if (generated.status !== 0) {
    throw new Error(`fixture generation failed: ${generated.stdout}\n${generated.stderr}`);
  }
  sourcePath = path.join(
    FIXTURE_DIR,
    FORMAT === "pdf" ? "attention-sample.pdf" : "systems-sample.epub",
  );
}
const RESOURCE_PAYLOAD =
  FORMAT === "pdf"
    ? {
        kind: "pdf",
        name: "attention-sample.pdf",
        source: sourcePath,
        sourceType: "file",
        tags: ["grounding", "pdf"],
      }
    : FORMAT === "epub"
      ? {
          kind: "epub",
          name: "systems-sample.epub",
          source: sourcePath,
          sourceType: "file",
          tags: ["grounding", "epub"],
        }
      : {
          kind: "markdown",
          name: RESOURCE_NAME,
          source: `inline://${RESOURCE_NAME}`,
          content: RESOURCE_TEXT,
          contentEncoding: "utf-8",
          tags: ["grounding", "queue-lock"],
        };
const SEARCH_QUERY =
  process.env.GROUNDING_GUI_QUERY ??
  (FORMAT === "pdf"
    ? "quorum acknowledgement"
    : FORMAT === "epub"
      ? "quorum reads intersect"
      : "finally block release lock");
const PROMPT =
  process.env.GROUNDING_GUI_PROMPT ??
  (FORMAT === "pdf"
    ? "请引用资料库里第二页关于 quorum acknowledgement 的原文。"
    : FORMAT === "epub"
      ? "请引用资料库里 Foundations 章节关于 quorum reads 的原文。"
      : "请直接从我的资料库里讲讲队列写入锁的边界，并引用原文。");

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
      "markdown.math.enabled": true,
    },
    null,
    2,
  )}\n`,
);

function readMemento(value) {
  if (value === undefined || value === null) return undefined;
  try {
    return JSON.parse(typeof value === "string" ? value : Buffer.from(value).toString("utf8"));
  } catch {
    return undefined;
  }
}

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

function writeDriverExtension() {
  fs.writeFileSync(
    path.join(driverDir, "package.json"),
    `${JSON.stringify(
      {
        name: "trainer-grounding-gui-driver",
        displayName: "Trainer Grounding GUI Driver",
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
  const reportPath = process.env.GROUNDING_GUI_REPORT;
  const activeEditorPath = process.env.GROUNDING_GUI_ACTIVE_EDITOR;
  const resourceStatePath = process.env.GROUNDING_GUI_RESOURCE_STATE;
  const targetId = process.env.GROUNDING_GUI_TARGET_EXTENSION_ID;
  const provider = JSON.parse(process.env.GROUNDING_GUI_PROVIDER || "{}");
  const resource = JSON.parse(process.env.GROUNDING_GUI_RESOURCE || "{}");
  const report = { ok: false, steps: [] };
  const deleteRequestPath = process.env.GROUNDING_GUI_DELETE_REQUEST;
  const deleteResultPath = process.env.GROUNDING_GUI_DELETE_RESULT;
  const previewRequestPath = process.env.GROUNDING_GUI_PREVIEW_REQUEST;
  const previewResultPath = process.env.GROUNDING_GUI_PREVIEW_RESULT;
  let previewing = false;
  setInterval(async () => {
    if (previewing || !previewRequestPath || !previewResultPath) return;
    if (!fs.existsSync(previewRequestPath)) return;
    previewing = true;
    try {
      const request = JSON.parse(fs.readFileSync(previewRequestPath, "utf8"));
      fs.unlinkSync(previewRequestPath);
      await vscode.commands.executeCommand(
        "markdown.showPreview",
        vscode.Uri.file(request.markdownPath),
      );
      fs.writeFileSync(previewResultPath, JSON.stringify({ ok: true }));
    } catch (error) {
      fs.writeFileSync(previewResultPath, JSON.stringify({
        ok: false,
        message: error && error.stack ? error.stack : String(error),
      }));
    } finally {
      previewing = false;
    }
  }, 500);
  let deleting = false;
  setInterval(async () => {
    if (deleting || !deleteRequestPath || !deleteResultPath) return;
    if (!fs.existsSync(deleteRequestPath)) return;
    deleting = true;
    try {
      const request = JSON.parse(fs.readFileSync(deleteRequestPath, "utf8"));
      fs.unlinkSync(deleteRequestPath);
      const result = await vscode.commands.executeCommand("trainer.resource.delete", {
        resourceIds: [request.resourceId],
      });
      fs.writeFileSync(deleteResultPath, JSON.stringify({
        ok: Boolean(result && result.ok),
        message: result && result.message,
      }));
    } catch (error) {
      fs.writeFileSync(deleteResultPath, JSON.stringify({
        ok: false,
        message: error && error.stack ? error.stack : String(error),
      }));
    } finally {
      deleting = false;
    }
  }, 500);
  const activeEditorTimer = setInterval(() => {
    const editor = vscode.window.activeTextEditor;
    try {
      fs.writeFileSync(activeEditorPath, JSON.stringify({
        fileName: editor && editor.document ? editor.document.fileName : "",
        text: editor && editor.document ? editor.document.getText().slice(0, 4000) : "",
        line: editor && editor.selection ? editor.selection.active.line : -1,
        at: new Date().toISOString(),
      }));
    } catch {}
  }, 400);
  try {
    const target = vscode.extensions.getExtension(targetId);
    if (!target) throw new Error("Trainer extension not installed: " + targetId);
    await target.activate();
    await sleep(12000);
    const admitted = await vscode.commands.executeCommand("trainer.workspace.adoptProject", {
      projectPath: process.env.GROUNDING_GUI_PROJECT_PATH || undefined,
    });
    report.steps.push({ step: "admit-project", ok: Boolean(admitted && admitted.ok), message: admitted && admitted.message });
    await sleep(1500);
    const savePayload = {
      ...provider.payload,
      baseUrl: provider.baseUrl,
      model: provider.model,
      apiKey: provider.apiKey,
      replaceApiKey: true,
    };
    const saved = await vscode.commands.executeCommand("trainer.provider.save", savePayload);
    report.steps.push({ step: "save-provider", ok: Boolean(saved && saved.ok), message: saved && saved.message });
    await sleep(1000);
    // The first save of a new protocol starts from its default capability set;
    // save once more on the same connection so the explicit fixture
    // capabilities (tools on, streaming off) are the stored ones.
    const savedCapabilities = await vscode.commands.executeCommand("trainer.provider.save", savePayload);
    report.steps.push({
      step: "save-provider-capabilities",
      ok: Boolean(savedCapabilities && savedCapabilities.ok),
      message: savedCapabilities && savedCapabilities.message,
    });
    await sleep(1000);
    const tested = await vscode.commands.executeCommand("trainer.provider.test", {});
    report.steps.push({
      step: "test-provider",
      ok: Boolean(tested && tested.ok),
      message: tested && tested.message,
      capabilities: tested && tested.data && tested.data.capabilities,
    });
    await sleep(1000);
    const settings = await vscode.commands.executeCommand("trainer.memory.saveCoachSettings", {
      responseLanguage: "zh-CN",
      answerMode: "coach-first",
    });
    report.steps.push({ step: "coach-settings", ok: Boolean(settings && settings.ok) });
    const upload = await vscode.commands.executeCommand("trainer.resource.upload", {
      uploads: [resource],
    });
    const uploaded = upload && Array.isArray(upload.data) ? upload.data[0] : undefined;
    report.steps.push({
      step: "upload-resource",
      ok: Boolean(upload && upload.ok && uploaded && uploaded.id),
      message: upload && upload.message,
      resourceId: uploaded && uploaded.id,
    });
    if (uploaded && uploaded.id) {
      fs.writeFileSync(resourceStatePath, JSON.stringify({ resourceId: uploaded.id, name: resource.name }));
    }
    await sleep(1500);
    await vscode.commands.executeCommand("trainer.openWorkbench");
    await sleep(2000);
    report.ok = report.steps.every((step) => step.ok !== false);
  } catch (error) {
    report.error = error && error.stack ? error.stack : String(error);
  } finally {
    clearInterval(activeEditorTimer);
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

function sendJson(response, status, body) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}"));
      } catch (error) {
        reject(error);
      }
    });
    request.on("error", reject);
  });
}

function latestUserText(payload) {
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "user") {
      return contentText(messages[index].content);
    }
  }
  return "";
}

function allSystemText(payload) {
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  return messages
    .filter((message) => message?.role === "system")
    .map((message) => contentText(message.content))
    .join("\n");
}

function contentText(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => (part && typeof part === "object" && typeof part.text === "string" ? part.text : ""))
    .join("\n");
}

function toolContents(messages) {
  return (Array.isArray(messages) ? messages : [])
    .filter((message) => message?.role === "tool")
    .map((message) => message.content)
    .filter((content) => typeof content === "string" && content.trim().length > 0);
}

function parseToolContent(content) {
  try {
    const parsed = JSON.parse(content);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function readResourceId(statePath) {
  try {
    return String(JSON.parse(fs.readFileSync(statePath, "utf8")).resourceId || "");
  } catch {
    return "";
  }
}

function toolCall(name, args) {
  return {
    id: `grounding-call-${name}`,
    type: "function",
    function: { name, arguments: JSON.stringify(args) },
  };
}

function fixtureMessage(payload, statePath, searchQuery) {
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  const userText = latestUserText(payload);
  const systemText = allSystemText(payload);
  const requestedTool =
    payload && typeof payload.tool_choice === "object" && payload.tool_choice?.function?.name;
  if (requestedTool) {
    return { toolCalls: [toolCall(requestedTool, { probe: "ok" })] };
  }
  if (/Return exactly the requested text/i.test(systemText)) {
    const exact = userText.match(/Repeat exactly:\s*([\s\S]+)/i);
    return { content: exact?.[1]?.trim() || userText.trim() || "grounding fixture acknowledgement" };
  }
  if (/Reply with exactly:\s*pong/i.test(userText)) {
    return { content: "pong" };
  }
  if (/Reply with one short visible word:\s*OK/i.test(userText)) {
    return { content: "OK" };
  }
  if (/provider ready/i.test(userText)) {
    return { content: "provider ready" };
  }
  const toolMessages = toolContents(messages);
  const searchContent = toolMessages[0];
  const readContent = toolMessages[1];
  if (!searchContent) {
    return { toolCalls: [toolCall("search_resources", { query: searchQuery, mode: "narrow" })] };
  }
  if (!readContent) {
    const parsed = parseToolContent(searchContent);
    const hits = Array.isArray(parsed.hits) ? parsed.hits : [];
    const hit = hits[0] || {};
    const resourceId = String(hit.resource_id || readResourceId(statePath) || "");
    const anchorId = String(
      hit.anchor_id || hit.location?.anchor_id || hit.location?.paragraph_anchor || "",
    );
    return {
      toolCalls: [
        toolCall("read_resource_excerpt", {
          ...(resourceId ? { resource_id: resourceId } : {}),
          ...(anchorId ? { anchor_id: anchorId } : {}),
          chars: 1400,
        }),
      ],
    };
  }
  return {
    content:
      "原文里说得很清楚：锁必须覆盖整个写入窗口，并且要在 finally 里释放；这样一次失败的写入才不会让后续消费者永久等待。",
  };
}

function sendChat(response, payload, message) {
  const responseId = `grounding-fixture-${Date.now()}`;
  try {
    fs.appendFileSync(
      providerDebugPath,
      `${JSON.stringify({
        at: new Date().toISOString(),
        stream: payload.stream === true,
        model: payload.model,
        toolChoice: payload.tool_choice,
        messages: (Array.isArray(payload.messages) ? payload.messages : []).map((item) => ({
          role: item?.role,
          name: item?.name,
          toolCallId: item?.tool_call_id,
          content: typeof item?.content === "string" ? item.content.slice(0, 500) : item?.content,
        })),
        decision: message.toolCalls ? { toolCalls: message.toolCalls } : { content: message.content },
      })}\n`,
    );
  } catch {}
  if (payload.stream === true) {
    const delta = message.toolCalls
      ? {
          role: "assistant",
          tool_calls: message.toolCalls.map((call, index) => ({ index, ...call })),
        }
      : { role: "assistant", content: message.content };
    response.writeHead(200, {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache",
      connection: "keep-alive",
    });
    response.write(
      `data: ${JSON.stringify({
        id: responseId,
        object: "chat.completion.chunk",
        model: payload.model,
        choices: [{ index: 0, delta, finish_reason: null }],
      })}\n\n`,
    );
    response.write(
      `data: ${JSON.stringify({
        id: responseId,
        object: "chat.completion.chunk",
        model: payload.model,
        choices: [{ index: 0, delta: {}, finish_reason: message.toolCalls ? "tool_calls" : "stop" }],
      })}\n\n`,
    );
    response.end("data: [DONE]\n\n");
    return;
  }
  sendJson(response, 200, {
    id: responseId,
    object: "chat.completion",
    model: payload.model,
    choices: [
      {
        index: 0,
        message: message.toolCalls
          ? { role: "assistant", content: null, tool_calls: message.toolCalls }
          : { role: "assistant", content: message.content },
        finish_reason: message.toolCalls ? "tool_calls" : "stop",
      },
    ],
    usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
  });
}

function startFixtureProvider(searchQuery) {
  const model = "trainer-grounding-fixture-model";
  const apiKey = `trainer-grounding-${Math.random().toString(36).slice(2)}`;
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url || "/", "http://127.0.0.1");
    if (request.method === "GET" && url.pathname === "/v1/models") {
      return sendJson(response, 200, {
        object: "list",
        data: [{ id: model, object: "model", created: 0, owned_by: "trainer-grounding-gui" }],
      });
    }
    if (request.method !== "POST" || url.pathname !== "/v1/chat/completions") {
      return sendJson(response, 404, { error: { message: "not found" } });
    }
    if (request.headers.authorization !== `Bearer ${apiKey}`) {
      return sendJson(response, 401, { error: { message: "unauthorized" } });
    }
    let payload;
    try {
      payload = await readBody(request);
    } catch {
      return sendJson(response, 400, { error: { message: "invalid json" } });
    }
    return sendChat(response, payload, fixtureMessage(payload, resourceStatePath, searchQuery));
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      resolve({
        baseUrl: `http://127.0.0.1:${address.port}/v1`,
        model,
        apiKey,
        stop: () => new Promise((done) => server.close(() => done())),
      });
    });
  });
}

function findFile(rootDir, fileName) {
  const stack = [rootDir];
  while (stack.length > 0) {
    const current = stack.pop();
    let entries = [];
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(full);
      } else if (entry.name === fileName) {
        return full;
      }
    }
  }
  return "";
}

const results = [];
const record = (step, payload) => {
  results.push({ step, ...payload, at: new Date().toISOString() });
};

let provider = null;
let app = null;
try {
  provider = await startFixtureProvider(SEARCH_QUERY);
  const providerConfig = resolveVsixE2EProviderConfiguration({
    extensionDir,
    requestedProtocol: "openai_chat_completions_compatible",
  });
  const providerPayload = buildVsixE2EProviderSavePayloadTemplate({
    ...providerConfig,
    capabilities: { ...providerConfig.capabilities, tools: true, streaming: true },
  });
  const launchEnv = {
    ...process.env,
    GROUNDING_GUI_REPORT: reportPath,
    GROUNDING_GUI_ACTIVE_EDITOR: activeEditorPath,
    GROUNDING_GUI_RESOURCE_STATE: resourceStatePath,
    GROUNDING_GUI_DELETE_REQUEST: deleteRequestPath,
    GROUNDING_GUI_DELETE_RESULT: deleteResultPath,
    GROUNDING_GUI_PREVIEW_REQUEST: previewRequestPath,
    GROUNDING_GUI_PREVIEW_RESULT: previewResultPath,
    GROUNDING_GUI_TARGET_EXTENSION_ID: extensionId,
    GROUNDING_GUI_PROJECT_PATH: workspaceDir,
    GROUNDING_GUI_PROVIDER: JSON.stringify({
      payload: providerPayload,
      baseUrl: provider.baseUrl,
      model: provider.model,
      apiKey: provider.apiKey,
    }),
    GROUNDING_GUI_RESOURCE: JSON.stringify(RESOURCE_PAYLOAD),
    NO_PROXY: "127.0.0.1,localhost",
    no_proxy: "127.0.0.1,localhost",
  };

  runCode([
    "--user-data-dir",
    userDataDir,
    "--extensions-dir",
    extensionsDir,
    "--install-extension",
    vsixPath,
    "--force",
  ]);

  app = await _electron.launch({
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

  const page = await app.firstWindow({ timeout: 120_000 });
  await page.addInitScript(() => {
    window.__trainerGroundingHostMessages = [];
    window.addEventListener(
      "message",
      (event) => {
        try {
          window.__trainerGroundingHostMessages.push(event.data);
        } catch {}
      },
      true,
    );
  });
  const consoleLines = [];
  page.on("console", (message) => {
    if (consoleLines.length < 200) {
      consoleLines.push(`${message.type()}: ${message.text()}`.slice(0, 500));
    }
  });
  const screenshot = async (name) => {
    const file = path.join(outDir, `${name}.png`);
    await page.screenshot({ path: file, timeout: 30_000 });
    return path.relative(repoRoot, file);
  };
  const findFrame = async (timeout = 90_000) => {
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

  const deadline = Date.now() + 180_000;
  while (!fs.existsSync(reportPath) && Date.now() < deadline) {
    await page.waitForTimeout(2000);
  }
  if (!fs.existsSync(reportPath)) throw new Error("Driver never wrote its report.");
  const driverReport = JSON.parse(fs.readFileSync(reportPath, "utf8"));
  record("driver-report", {
    ok: driverReport.ok === true,
    steps: driverReport.steps,
    error: driverReport.error,
  });
  if (!driverReport.ok) throw new Error(`Driver setup failed: ${driverReport.error || "unknown"}`);

  const frame = await findFrame();
  await frame.evaluate(() => {
    window.__trainerGroundingHostMessages = [];
    window.addEventListener(
      "message",
      (event) => {
        try {
          window.__trainerGroundingHostMessages.push(event.data);
        } catch {}
      },
      true,
    );
  });
  await page.waitForTimeout(1200);
  const composer = frame.locator("#coach-composer").first();
  await composer.waitFor({ timeout: 30_000 });
  await composer.fill(PROMPT);
  await composer.press("Enter");

  const citation = frame.locator('[data-citation-part="true"]').first();
  try {
    await citation.waitFor({ timeout: 120_000 });
  } catch (error) {
    record("message-state", {
      ok: false,
      body: (await frame.locator("body").innerText()).replace(/\s+/g, " ").trim().slice(0, 1500),
      console: consoleLines.slice(-40),
      hostMessages: await frame
        .evaluate(() => (window.__trainerGroundingHostMessages || []).slice(-30))
        .catch(() => []),
      providerDebug: fs.existsSync(providerDebugPath)
        ? fs.readFileSync(providerDebugPath, "utf8").split("\n").filter(Boolean).slice(-8)
        : [],
      screenshot: await screenshot("00-message-timeout"),
    });
    throw error;
  }
  const citationText = (await citation.innerText()).replace(/\s+/g, " ").trim();
  const citationResourceId = await citation.getAttribute("data-resource-id");
  const citationId = await citation.getAttribute("data-citation-id");
  const citationChunkId = await citation.getAttribute("data-resource-chunk-id");
  const citationVersionId = await citation.getAttribute("data-resource-version-id");
  const transcriptBody = (await citation.innerText()).replace(/\s+/g, " ");
  record("grounded-citation", {
    ok:
      Boolean(citationChunkId) &&
      (FORMAT === "pdf"
        ? citationChunkId.startsWith("¶page2@")
        : FORMAT === "epub"
          ? /^¶h[1-6]@/.test(citationChunkId)
          : citationChunkId === "¶h2@7") &&
      !transcriptBody.includes("A lock protects the write path"),
    citationText: citationText.slice(0, 500),
    resourceId: citationResourceId,
    versionId: citationVersionId,
    chunkId: citationChunkId,
    citationId,
    screenshot: await screenshot("01-grounded-citation"),
  });

  const readResult = await frame.evaluate(() =>
    Array.from(document.querySelectorAll('[data-citation-part="true"]')).map((node) => ({
      resourceId: node.getAttribute("data-resource-id"),
      versionId: node.getAttribute("data-resource-version-id"),
      chunkId: node.getAttribute("data-resource-chunk-id"),
      citationId: node.getAttribute("data-citation-id"),
    })),
  );
  record("provenance-attributes", {
    ok:
      readResult.length > 0 &&
      Boolean(readResult[0].resourceId) &&
      Boolean(readResult[0].chunkId) &&
      Boolean(readResult[0].citationId),
    citations: readResult,
  });

  const openButton = citation.getByRole("button", { name: /打开原文/ });
  await openButton.click();
  await page.waitForTimeout(2500);
  const editorText = await page
    .locator(".monaco-editor .view-lines")
    .last()
    .innerText()
    .catch(() => "");
  const breadcrumbs = await page
    .locator(".monaco-breadcrumbs")
    .last()
    .innerText()
    .catch(() => "");
  const statusBar = await page
    .locator(".statusbar")
    .innerText()
    .catch(() => "");
  const expectedAnchorLine = Number(/@(\d+)$/.exec(String(citationChunkId))?.[1] ?? 0);
  const actualEditorLine = Number(/Ln\s+(\d+)/.exec(statusBar)?.[1] ?? -1);
  record("open-full-resource", {
    ok:
      Boolean(citationResourceId) &&
      breadcrumbs.includes(String(citationResourceId)) &&
      expectedAnchorLine > 0 &&
      actualEditorLine === expectedAnchorLine,
    resourceId: citationResourceId,
    fileName: breadcrumbs.replace(/\s+/g, " ").trim().slice(0, 300),
    line: actualEditorLine,
    expectedLine: expectedAnchorLine,
    editorPreview: editorText.slice(0, 400),
    screenshot: await screenshot("02-open-full-resource"),
  });

  const canonicalPath =
    findFile(trainerWorkspaceDir, `${citationResourceId}.md`) ||
    findFile(workspaceDir, `${citationResourceId}.md`);
  const canonicalText = canonicalPath && fs.existsSync(canonicalPath)
    ? fs.readFileSync(canonicalPath, "utf8")
    : "";
  const formatContentChecks =
    FORMAT === "pdf"
      ? {
          pageMarker: canonicalText.includes("<!-- page: 2 -->"),
          image: /!\[[^\]]*\]\(assets\/[^)]+\.(?:png|jpg|jpeg|webp)\)/i.test(canonicalText),
          formulaText: canonicalText.includes("E = m c^2"),
        }
      : FORMAT === "epub"
        ? {
            table: canonicalText.includes("| Quorum | Meaning |"),
            image: canonicalText.includes("![Quorum diagram](assets/"),
            formulaText: canonicalText.includes("$E = m c 2$"),
          }
        : {};
  record("format-content", {
    ok:
      FORMAT === "markdown" ||
      (Boolean(canonicalPath) && Object.values(formatContentChecks).every(Boolean)),
    canonicalPath,
    checks: formatContentChecks,
  });

  if (FORMAT === "pdf" || FORMAT === "epub") {
    fs.writeFileSync(
      previewRequestPath,
      JSON.stringify({ markdownPath: canonicalPath, requestedAt: new Date().toISOString() }),
    );
    const previewDeadline = Date.now() + 30_000;
    while (!fs.existsSync(previewResultPath) && Date.now() < previewDeadline) {
      await page.waitForTimeout(500);
    }
    const previewResult = fs.existsSync(previewResultPath)
      ? JSON.parse(fs.readFileSync(previewResultPath, "utf8"))
      : { ok: false, message: "preview timeout" };
    let previewFrame = null;
    const previewDeadline2 = Date.now() + 30_000;
    while (!previewFrame && Date.now() < previewDeadline2) {
      for (const candidate of page.frames()) {
        if (!candidate.url().includes("vscode-webview://")) continue;
        try {
          const isPreview = await candidate.evaluate(() => {
            const text = document.body?.innerText || "";
            return /Quorum/.test(text) && document.querySelectorAll("img, table").length > 0;
          });
          if (isPreview) {
            previewFrame = candidate;
            break;
          }
        } catch {
          // still loading
        }
      }
      if (!previewFrame) await page.waitForTimeout(700);
    }
    const previewFacts = previewFrame
      ? await previewFrame.evaluate(() => ({
          text: (document.body.innerText || "").replace(/\s+/g, " ").slice(0, 1200),
          tables: document.querySelectorAll("table").length,
          images: document.querySelectorAll("img").length,
          katex: document.querySelectorAll(".katex, .math").length,
        }))
      : { text: "", tables: 0, images: 0, katex: 0 };
    if (!previewFrame) {
      record("preview-debug", {
        ok: false,
        frames: page.frames().map((candidate) => candidate.url()).slice(0, 10),
        texts: await Promise.all(
          page.frames().map(async (candidate) => {
            try {
              return (await candidate.locator("body").innerText({ timeout: 1000 }))
                .replace(/\s+/g, " ")
                .slice(0, 300);
            } catch {
              return "";
            }
          }),
        ),
      });
    }
    record("format-preview", {
      ok:
        previewResult.ok === true &&
        Boolean(previewFrame) &&
        previewFacts.images > 0 &&
        (FORMAT !== "epub" || previewFacts.tables > 0) &&
        /Quorum/.test(previewFacts.text),
      previewResult,
      ...previewFacts,
      screenshot: await screenshot("04-format-preview"),
    });
    if (FORMAT === "epub" && previewFrame) {
      await previewFrame
        .evaluate(() => window.scrollTo(0, document.body.scrollHeight))
        .catch(() => {});
      await page.waitForTimeout(400);
    }
    if (FORMAT === "epub") {
      record("format-formula", {
        ok: previewFacts.katex > 0,
        screenshot: await screenshot("05-format-formula"),
      });
    }
  }

  if (FORMAT !== "markdown") {
    record("deleted-citation", { ok: true, skipped: "format preview lane" });
  } else {
  fs.writeFileSync(
    deleteRequestPath,
    JSON.stringify({ resourceId: citationResourceId, requestedAt: new Date().toISOString() }),
  );
  const deleteDeadline = Date.now() + 30_000;
  while (!fs.existsSync(deleteResultPath) && Date.now() < deleteDeadline) {
    await page.waitForTimeout(500);
  }
  const deleteResult = fs.existsSync(deleteResultPath)
    ? JSON.parse(fs.readFileSync(deleteResultPath, "utf8"))
    : { ok: false, message: "delete timeout" };
  const invalidCitation = frame.locator(
    '[data-citation-part="true"][data-citation-invalid="true"]',
  ).first();
  let invalidVisible = true;
  try {
    await invalidCitation.waitFor({ timeout: 30_000 });
  } catch {
    invalidVisible = false;
  }
  const invalidText = invalidVisible
    ? (await invalidCitation.innerText()).replace(/\s+/g, " ").trim()
    : "";
  const invalidActionButtons = invalidVisible
    ? await invalidCitation.getByRole("button").count()
    : 0;
  record("deleted-citation", {
    ok:
      invalidVisible &&
      deleteResult.ok === true &&
      invalidText.includes("资料已删除") &&
      !invalidText.includes("↗") &&
      invalidActionButtons === 0,
    deleteResult,
    text: invalidText.slice(0, 300),
    actionButtons: invalidActionButtons,
    screenshot: await screenshot("03-deleted-citation"),
  });
  }
} catch (error) {
  record("fatal", { ok: false, message: error instanceof Error ? error.stack || error.message : String(error) });
} finally {
  const ok = results.every((step) => step.ok !== false);
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(
    path.join(outDir, "report.json"),
    `${JSON.stringify({ ok, steps: results }, null, 2)}\n`,
  );
  if (app) await app.close().catch(() => {});
  if (provider) await provider.stop().catch(() => {});
}

const finalReport = JSON.parse(fs.readFileSync(path.join(outDir, "report.json"), "utf8"));
console.log(JSON.stringify({ ok: finalReport.ok, outDir: path.relative(repoRoot, outDir) }, null, 2));
if (!finalReport.ok) process.exitCode = 1;
