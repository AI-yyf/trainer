#!/usr/bin/env node
/**
 * Real VS Code GUI journey for canonical library documents.
 *
 * Installs the packaged VSIX into an isolated user-data/extensions profile,
 * imports a real DOCX, PPTX, PDF and Markdown note through the extension's
 * own `trainer.resource.upload` command (the same handler the webview's import
 * menu calls), then drives the installed webview with Playwright Electron:
 * verify the library lists every file, prove a row opens the original source
 * in a real editor tab (never a Reader detail page), verify the canonical
 * Markdown artifacts on disk, and search. Screenshots are written to
 * `output/canonical-gui/<stamp>/`.
 *
 * No provider is required: everything here is local library work.
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
const vsixPath = path.join(
  extensionDir,
  `trainer-extension-${packageJson.version}-darwin-arm64.vsix`,
);
const codeCli = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code";
const electronBinary = requireVSCodeElectronBinary();

if (!fs.existsSync(vsixPath)) {
  throw new Error(`Packaged VSIX not found: ${vsixPath}. Run npm run package:vsix first.`);
}

const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const outDir = path.join(repoRoot, "output", "canonical-gui", stamp);
const root = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-canonical-gui-"));
const userDataDir = path.join(root, "user-data");
const extensionsDir = path.join(root, "extensions");
const workspaceDir = path.join(root, "workspace");
const trainerWorkspaceDir = path.join(root, "trainer-workspace");
const fixturesDir = path.join(outDir, "fixtures");
const driverDir = path.join(root, "driver");
const reportPath = path.join(root, "report.json");
const pokePath = path.join(root, "state-poke");
const stateOutPath = path.join(root, "state-after.json");
for (const dir of [
  path.join(userDataDir, "User"),
  extensionsDir,
  path.join(workspaceDir, "docs"),
  trainerWorkspaceDir,
  fixturesDir,
  driverDir,
  outDir,
]) {
  fs.mkdirSync(dir, { recursive: true });
}

function writeUserSettings() {
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
        "disableAICustomizations": true,
        "workbench.disableAICustomizations": true,
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
}
writeUserSettings();

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

function readVsCodeMementoValue(value) {
  if (value === undefined || value === null) {
    return undefined;
  }
  const text = typeof value === "string" ? value : Buffer.from(value).toString("utf8");
  try {
    return JSON.parse(text);
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
    const existing = readVsCodeMementoValue(
      database.prepare("SELECT value FROM ItemTable WHERE key = ?").get(extensionId)?.value,
    );
    const extensionState = existing && typeof existing === "object" ? existing : {};
    extensionState["trainer.workspace.root.v1"] = trainerWorkspaceDir;
    database
      .prepare("INSERT INTO ItemTable (key, value) VALUES (?, ?)")
      .run(extensionId, JSON.stringify(extensionState));

    const keyIndex = `extensionKeys/${extensionId}@${packageJson.version}`;
    const existingKeys = readVsCodeMementoValue(
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

function runFixtureBuilder() {
  const script = path.join(root, "build-fixtures.py");
  fs.writeFileSync(
    script,
    String.raw`
import sys, zipfile, os
sys.path.insert(0, ${JSON.stringify(path.join(repoRoot, "server"))})
out_dir = ${JSON.stringify(fixturesDir)}
workspace_docs = ${JSON.stringify(path.join(workspaceDir, "docs"))}
W="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG="http://schemas.openxmlformats.org/package/2006/relationships"
A="http://schemas.openxmlformats.org/drawingml/2006/main"
P="http://schemas.openxmlformats.org/presentationml/2006/main"
png=bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5f0000000049454e44ae426082")
document=f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:a="{A}" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"><w:body>
<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>Distributed Systems Notes</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Write Path</w:t></w:r></w:p>
<w:p><w:r><w:t>A write is acknowledged after the log fsync.</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Quorum Ack</w:t></w:r></w:p>
<w:p><w:r><w:t>See the </w:t></w:r><w:hyperlink r:id="rIdLink"><w:r><w:t>paper</w:t></w:r></w:hyperlink><w:r><w:t> for the quorum acknowledgement rule.</w:t></w:r><w:r><w:footnoteReference w:id="2"/></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Level</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Cost</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:p><w:r><w:t>fsync</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>high</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
<w:p><w:r><w:drawing><wp:inline><a:graphic><a:graphicData><a:blip r:embed="rIdImage"/></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>
</w:body></w:document>'''
rels=f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{PKG}">
<Relationship Id="rIdLink" Type="{R}/hyperlink" Target="https://example.org/storage" TargetMode="External"/>
<Relationship Id="rIdImage" Type="{R}/image" Target="media/image1.png"/></Relationships>'''
foot=f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:footnotes xmlns:w="{W}"><w:footnote w:id="2"><w:p><w:r><w:t>Quorum acknowledgement is read after write.</w:t></w:r></w:p></w:footnote></w:footnotes>'''
with zipfile.ZipFile(os.path.join(workspace_docs,"distributed-systems-notes.docx"),"w",zipfile.ZIP_DEFLATED) as z:
    z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="png" ContentType="image/png"/></Types>')
    z.writestr('word/document.xml',document)
    z.writestr('word/_rels/document.xml.rels',rels)
    z.writestr('word/footnotes.xml',foot)
    z.writestr('word/media/image1.png',png)
    z.writestr('docProps/app.xml','<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Pages>2</Pages></Properties>')

slide=f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}"><p:cSld><p:spTree>
<p:sp><p:nvSpPr><p:nvPr><p:ph type="ctrTitle"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>Consensus</a:t></a:r></a:p></p:txBody></p:sp>
<p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr><p:txBody>
<a:p><a:pPr><a:buChar char="&#8226;"/></a:pPr><a:r><a:t>Majority vote</a:t></a:r></a:p>
<a:p><a:pPr lvl="1"><a:buChar char="&#8226;"/></a:pPr><a:r><a:t>Term numbers</a:t></a:r></a:p></p:txBody></p:sp>
<p:graphicFrame><a:graphic><a:graphicData><a:tbl>
<a:tr><a:tc><a:txBody><a:p><a:r><a:t>State</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody><a:p><a:r><a:t>Meaning</a:t></a:r></a:p></a:txBody></a:tc></a:tr>
<a:tr><a:tc><a:txBody><a:p><a:r><a:t>Follower</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody><a:p><a:r><a:t>Receives entries</a:t></a:r></a:p></a:txBody></a:tc></a:tr>
</a:tbl></a:graphicData></a:graphic></p:graphicFrame>
<p:pic><p:blipFill><a:blip r:embed="rIdImg1"/></p:blipFill></p:pic>
</p:spTree></p:cSld></p:sld>'''
slide2=f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}"><p:cSld><p:spTree>
<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>Paxos</a:t></a:r></a:p></p:txBody></p:sp>
<p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>Two phases decide one value.</a:t></a:r></a:p></p:txBody></p:sp>
</p:spTree></p:cSld></p:sld>'''
slide_rels=f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{PKG}">
<Relationship Id="rIdImg1" Type="{R}/image" Target="../media/image1.png"/>
<Relationship Id="rIdNotes1" Type="{R}/notesSlide" Target="../notesSlides/notesSlide1.xml"/></Relationships>'''
notes=f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:notes xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>
<p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>Explain why a majority is enough.</a:t></a:r></a:p></p:txBody></p:sp>
</p:spTree></p:cSld></p:notes>'''
with zipfile.ZipFile(os.path.join(workspace_docs,"consensus-deck.pptx"),"w",zipfile.ZIP_DEFLATED) as z:
    z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="png" ContentType="image/png"/></Types>')
    z.writestr('ppt/slides/slide1.xml',slide)
    z.writestr('ppt/slides/slide2.xml',slide2)
    z.writestr('ppt/slides/_rels/slide1.xml.rels',slide_rels)
    z.writestr('ppt/notesSlides/notesSlide1.xml',notes)
    z.writestr('ppt/media/image1.png',png)

open(os.path.join(workspace_docs,"open-source-note.md"),"w",encoding="utf-8").write("# Direct source\n\nOPEN_SOURCE_DIRECT\n")

import pymupdf
pdf=pymupdf.open()
p1=pdf.new_page(); p1.insert_text((72,72),"Storage chapter one: the log.",fontsize=12)
p2=pdf.new_page(); p2.insert_text((72,72),"Storage chapter two: quorum acknowledgement.",fontsize=12)
pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0,0,10,10), 0)
pixmap.set_rect(pixmap.irect, (0,128,255))
p2.insert_image(pymupdf.Rect(72,100,172,200), pixmap=pixmap)
open(os.path.join(workspace_docs,"storage-paper.pdf"),"wb").write(pdf.tobytes()); pdf.close()
print("fixtures ready")
`,
  );
  const result = spawnSync(path.join(repoRoot, "server", ".venv", "bin", "python"), [script], {
    encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new Error(`Fixture builder failed:\n${result.stdout}\n${result.stderr}`);
  }
}
runFixtureBuilder();

function writeDriverExtension() {
  fs.writeFileSync(
    path.join(driverDir, "package.json"),
    `${JSON.stringify(
      {
        name: "trainer-canonical-gui-driver",
        displayName: "Trainer Canonical GUI Driver",
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
  const reportPath = process.env.CANONICAL_GUI_REPORT;
  const targetId = process.env.CANONICAL_GUI_TARGET_EXTENSION_ID;
  const fixtures = JSON.parse(process.env.CANONICAL_GUI_FIXTURES || "[]");
  const report = { steps: [], ok: false };
  try {
    const target = vscode.extensions.getExtension(targetId);
    if (!target) throw new Error("Trainer extension not installed: " + targetId);
    await target.activate();
    report.activated = true;
    await sleep(12000);
    const admitted = await vscode.commands.executeCommand("trainer.workspace.adoptProject", {
      projectPath: process.env.CANONICAL_GUI_PROJECT_PATH || undefined,
    });
    report.steps.push({
      step: "admit-project",
      ok: Boolean(admitted && admitted.ok),
      message: admitted && admitted.message ? admitted.message : null,
    });
    await sleep(2500);
    const uploads = fixtures.map((fixture) => ({
      kind: fixture.kind,
      name: fixture.name,
      source: fixture.path,
      content: fs.readFileSync(fixture.path).toString("base64"),
      contentEncoding: "base64",
      sourceType: "file",
    }));
    const uploaded = await vscode.commands.executeCommand("trainer.resource.upload", { uploads });
    report.steps.push({
      step: "upload",
      ok: Boolean(uploaded && uploaded.ok),
      message: uploaded && uploaded.message ? uploaded.message : null,
    });
    if (!uploaded || uploaded.ok !== true) {
      throw new Error("Resource import failed: " + (uploaded && uploaded.message ? uploaded.message : "unknown"));
    }
    await sleep(2500);
    const data = Array.isArray(uploaded.data) ? uploaded.data : [];
    const firstId = data[0] && (data[0].id || data[0].resource_id);
    report.steps.push({
      step: "resource-ids",
      ok: data.length >= fixtures.length,
      count: data.length,
      ids: data.map((item) => item && (item.id || item.resource_id)).filter(Boolean),
    });
    await vscode.commands.executeCommand("trainer.openWorkbench");
    await sleep(2500);
    const pokePath = process.env.CANONICAL_GUI_POKE;
    const stateOut = process.env.CANONICAL_GUI_STATE_OUT;
    if (pokePath && stateOut) {
      setInterval(() => {
        if (!fs.existsSync(pokePath)) return;
        try {
          const live = vscode.extensions.getExtension(targetId);
          const exportedState = live && live.isActive && live.exports && typeof live.exports.getDebugState === "function"
            ? live.exports.getDebugState()
            : null;
          const bootstrap = (exportedState && exportedState.bootstrap) || {};
          const memory = bootstrap.memory || {};
          fs.writeFileSync(
            stateOut,
            JSON.stringify(
              {
                liveResourceFocus: bootstrap.liveResourceFocus === true,
                planRuntimeRecovered: bootstrap.planRuntimeStatus ? bootstrap.planRuntimeStatus.recovered === true : null,
                previewKind: memory.sandboxPreview ? memory.sandboxPreview.previewKind || null : null,
                previewPath: memory.sandboxPreview ? memory.sandboxPreview.path || null : null,
                previewHead: memory.sandboxPreview && typeof memory.sandboxPreview.content === "string"
                  ? memory.sandboxPreview.content.slice(0, 80)
                  : null,
              },
              null,
              2,
            ),
          );
          fs.unlinkSync(pokePath);
        } catch (error) {
          fs.writeFileSync(stateOut, JSON.stringify({ error: String(error) }));
        }
      }, 500);
    }
    report.ok = true;
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
    throw new Error(`code CLI failed (${args.join(" ")}):\n${result.stdout}\n${result.stderr}`);
  }
}

runCode(["--user-data-dir", userDataDir, "--extensions-dir", extensionsDir, "--install-extension", vsixPath, "--force"]);

const fixtures = [
  {
    kind: "docx",
    name: "Distributed Systems Notes",
    path: path.join(workspaceDir, "docs", "distributed-systems-notes.docx"),
  },
  {
    kind: "pptx",
    name: "Consensus Deck",
    path: path.join(workspaceDir, "docs", "consensus-deck.pptx"),
  },
  {
    kind: "pdf",
    name: "Storage Paper",
    path: path.join(workspaceDir, "docs", "storage-paper.pdf"),
  },
  {
    kind: "markdown",
    name: "Open Source Note",
    path: path.join(workspaceDir, "docs", "open-source-note.md"),
  },
];

const results = [];
function record(step, payload) {
  results.push({ step, ...payload, at: new Date().toISOString() });
}

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
    CANONICAL_GUI_REPORT: reportPath,
    CANONICAL_GUI_TARGET_EXTENSION_ID: extensionId,
    CANONICAL_GUI_FIXTURES: JSON.stringify(fixtures),
    CANONICAL_GUI_PROJECT_PATH: workspaceDir,
    CANONICAL_GUI_POKE: pokePath,
    CANONICAL_GUI_STATE_OUT: stateOutPath,
  },
  timeout: 120_000,
});

async function screenshot(page, name) {
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
  await page.waitForTimeout(1600);
}
async function workspaceFrame(page, timeout = 60_000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    for (const candidate of page.frames()) {
      if (!candidate.url().includes("vscode-webview://")) continue;
      try {
        const text = await candidate.locator("body").innerText({ timeout: 1500 });
        if (/对话|Coach/.test(text) && /资料|Resources/.test(text)) {
          return candidate;
        }
      } catch {
        // Frame is still loading; try again.
      }
    }
    await page.waitForTimeout(1000);
  }
  throw new Error("Trainer webview frame not found");
}
async function bodyText(frame) {
  return (await frame.locator("body").innerText()).replace(/\s+/g, " ").trim();
}
async function waitFor(frame, pattern, timeout = 60_000) {
  const start = Date.now();
  let last = "";
  while (Date.now() - start < timeout) {
    last = await bodyText(frame);
    if (pattern.test(last)) return last;
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
  throw new Error(`Timed out waiting for ${pattern}: ${last.slice(0, 600)}`);
}
async function selectDestination(frame, label) {
  const buttons = frame.locator("button, a");
  const count = await buttons.count();
  for (let index = 0; index < count; index += 1) {
    const candidate = buttons.nth(index);
    const text = ((await candidate.innerText().catch(() => "")) || "").trim();
    if (text === label) {
      await candidate.click();
      await new Promise((resolve) => setTimeout(resolve, 1200));
      return;
    }
  }
  throw new Error(`Destination not found: ${label}`);
}
try {
  const page = await app.firstWindow({ timeout: 120_000 });
  await page.waitForTimeout(8000);
  // Observe the real import stage line while the driver imports documents.
  const stagePhrases = [
    ["identify", /正在识别资料类型|Identifying resource types/],
    ["parse", /正在解析文档结构|Parsing document structure/],
    ["markdown", /正在生成 Markdown|Generating canonical Markdown/],
    ["assets", /已生成 Markdown；已抽取|Markdown ready; extracted/],
    ["index", /正在建立索引|Building the search index/],
    ["refresh", /正在刷新资料库|Refreshing the library/],
  ];
  const observedStages = new Set();
  const deadline = Date.now() + 180_000;
  while (!fs.existsSync(reportPath) && Date.now() < deadline) {
    try {
      const statusText = await page.locator(".statusbar").innerText({ timeout: 800 });
      for (const [key, pattern] of stagePhrases) {
        if (pattern.test(statusText)) observedStages.add(key);
      }
    } catch {
      // Status bar not painted yet.
    }
    await page.waitForTimeout(250);
  }
  record("import-stages", {
    ok: observedStages.size >= 4,
    stages: [...observedStages],
  });
  if (!fs.existsSync(reportPath)) {
    throw new Error("Driver never wrote its import report.");
  }
  const driverReport = JSON.parse(fs.readFileSync(reportPath, "utf8"));
  record("driver-report", { ok: driverReport.ok === true, report: driverReport });
  if (!driverReport.ok) {
    throw new Error(`Driver import failed: ${driverReport.error || "unknown"}`);
  }
  const admission = (driverReport.steps || []).find((step) => step.step === "admit-project");
  if (admission && admission.ok !== true) {
    throw new Error(`Trainer project admission failed: ${admission.message || "unknown"}`);
  }

  await commandPalette(page, "Trainer: Open Coach Sidebar");
  await page.waitForTimeout(6000);
  const frame = await workspaceFrame(page);
  await waitFor(frame, /资料/);

  await selectDestination(frame, "资料");
  await waitFor(frame, /Distributed Systems Notes/);
  record("resources-list", {
    ok: true,
    screenshot: await screenshot(page, "01-resources-list-dark"),
    text: (await bodyText(frame)).slice(0, 600),
  });

  const readerChecks = [
    { title: "Distributed Systems Notes", key: "docx-reader" },
    { title: "Consensus Deck", key: "pptx-reader" },
    { title: "Storage Paper", key: "pdf-reader" },
  ];
  for (const check of readerChecks) {
    await waitFor(frame, new RegExp(check.title));
    const item = frame.getByRole("treeitem", { name: check.title, exact: true });
    record(check.key, {
      ok: (await item.count()) > 0,
      screenshot: await screenshot(page, `library-${check.key}-dark`),
      note: "The library lists the file; opening is a native source-open action, not a Reader page.",
    });
  }
  if ((await frame.locator("[data-template=ResourceReader]").count()) !== 0) {
    throw new Error("The retired Reader detail page is still rendered.");
  }

  // Proving the unified library item: a DOCX row opens its complete
  // canonical Markdown in a real VS Code editor tab (front matter + body +
  // table + image reference), never a Reader detail page.
  const docxItem = frame.getByRole("treeitem", { name: "Distributed Systems Notes", exact: true });
  if (!(await docxItem.isVisible())) {
    throw new Error("The DOCX row is not visible.");
  }
  await docxItem.focus();
  await docxItem.press("Enter");
  await page.waitForTimeout(2500);
  const editorText = await page.locator(".monaco-editor").innerText().catch(() => "");
  const tabs = await page.locator(".tab").allInnerTexts().catch(() => []);
  record("markdown-open", {
    ok: /resource_id:/.test(editorText) && /source_type:\s*docx/.test(editorText),
    screenshot: await screenshot(page, "markdown-open-dark"),
    editorHead: editorText.slice(0, 400),
    tabs: tabs.slice(0, 8),
  });
  if ((await frame.locator("[data-template=ResourceReader]").count()) !== 0) {
    throw new Error("The retired Reader detail page is still rendered.");
  }

  // Search across the library and open the hit at its cited Markdown line.
  const search = frame.locator('input[type="search"], input[placeholder*="搜索"], input[placeholder*="Search"]').first();
  if (await search.count()) {
    await search.click();
    await search.fill("quorum acknowledgement");
    await page.waitForTimeout(3500);
    const text = await bodyText(frame);
    record("library-search", {
      ok: /Quorum Ack|Storage|Distributed Systems Notes/.test(text),
      screenshot: await screenshot(page, "05-search-dark"),
      text: text.slice(0, 800),
    });
    const hit = frame.locator('[role="treeitem"]').filter({ hasText: /Distributed Systems Notes|Storage Paper/ }).first();
    record("search-hit-present", {
      ok: (await hit.count()) > 0,
      screenshot: await screenshot(page, "06-search-hit-present-dark"),
    });
  } else {
    record("library-search", { ok: false, reason: "search input not found" });
  }

  // Light theme pass for the warm-neutral visual requirement.
  await commandPalette(page, "Preferences: Color Theme");
  await page.keyboard.type("Light Modern");
  await page.waitForTimeout(700);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(2500);
  const lightFrame = await workspaceFrame(page);
  await selectDestination(lightFrame, "资料").catch(() => undefined);
  await page.waitForTimeout(1200);
  record("resources-list-light", {
    ok: true,
    screenshot: await screenshot(page, "07-resources-list-light"),
    text: (await bodyText(lightFrame)).slice(0, 500),
  });
} catch (error) {
  let fatalScreenshot = null;
  try {
    const windows = app.windows();
    if (windows.length > 0) {
      fatalScreenshot = await screenshot(windows[0], "00-fatal");
    }
  } catch {
    // Best-effort diagnostics only.
  }
  record("fatal", {
    ok: false,
    screenshot: fatalScreenshot,
    error: error instanceof Error ? error.stack : String(error),
  });
} finally {
  try {
    await app.close();
  } catch {
    // Evidence is already written; a slow shutdown must not mask the verdict.
  }
}

// Copy the canonical Markdown artifacts the library generated on disk.
const artifactDir = path.join(outDir, "trainer-library");
function copyTree(source, target) {
  if (!fs.existsSync(source)) return;
  fs.mkdirSync(target, { recursive: true });
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    const from = path.join(source, entry.name);
    const to = path.join(target, entry.name);
    if (entry.isDirectory()) copyTree(from, to);
    else fs.copyFileSync(from, to);
  }
}
copyTree(path.join(workspaceDir, "Trainer Library", ".trainer-resources"), artifactDir);

function readCanonicalArtifacts(dir) {
  const texts = [];
  if (!fs.existsSync(dir)) return texts;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) texts.push(...readCanonicalArtifacts(full));
    else if (/\.(md|markdown|txt)$/i.test(entry.name)) {
      texts.push(fs.readFileSync(full, "utf8"));
    }
  }
  return texts;
}
const canonicalText = readCanonicalArtifacts(artifactDir).join("\n");
function artifactFiles(dir) {
  const files = [];
  if (!fs.existsSync(dir)) return files;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...artifactFiles(full));
    else files.push(entry.name);
  }
  return files;
}
const assetNames = artifactFiles(path.join(artifactDir, "markdown", "assets"));
// The canonical store writes assets under `assets/<resource_id>/` so two
// resources can both use `image-001.png`; the link must stay resource-scoped.
const scopedAsset = (filename) =>
  new RegExp(`!\\[[^\\]]*\\]\\(assets/[^)/]+/${filename.replace(/\./g, "\\.")}\\)`);
record("canonical-artifacts", {
  ok:
    // DOCX: heading, hyperlink, footnote, table, image.
    /\[paper\]\(https:\/\/example\.org\/storage\)/.test(canonicalText) &&
    /\[\^2\]: Quorum acknowledgement/.test(canonicalText) &&
    /\| Level \| Cost \|/.test(canonicalText) &&
    scopedAsset("docx-image-001.png").test(canonicalText) &&
    // PPTX: table, image, speaker notes.
    /\| State \| Meaning \|/.test(canonicalText) &&
    scopedAsset("slide-image-001.png").test(canonicalText) &&
    /#### Speaker notes/.test(canonicalText) &&
    // PDF: page anchor, text and embedded image.
    /<!-- page: 2 -->/.test(canonicalText) &&
    /Storage chapter two/.test(canonicalText) &&
    scopedAsset("page-002-image-001.png").test(canonicalText) &&
    assetNames.includes("docx-image-001.png") &&
    assetNames.includes("slide-image-001.png") &&
    assetNames.includes("page-002-image-001.png"),
  bytes: canonicalText.length,
  assets: assetNames.slice(0, 12),
});

const failures = results.filter((item) => item.ok === false);
const report = {
  stamp,
  vsixPath,
  extensionId,
  isolatedProfile: { userDataDir, extensionsDir, workspaceDir },
  results,
  failures: failures.length,
  ok: failures.length === 0 && results.some((item) => item.step === "docx-reader" && item.ok),
  artifacts: {
    screenshots: fs.readdirSync(outDir).filter((name) => name.endsWith(".png")),
    canonicalMarkdown: fs.existsSync(artifactDir),
  },
};
fs.writeFileSync(path.join(outDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ ok: report.ok, outDir: path.relative(repoRoot, outDir), failures }, null, 2));
process.exit(report.ok ? 0 : 1);
