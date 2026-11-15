import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { chromium } from "playwright";

const SOURCE_URL = "https://example.com/trainer-paper/ppo";
const SOURCE_TITLE = "PPO 裁剪目标 · 已选段落";
const SELECTION = "正优势和负优势都要比较原始目标与裁剪目标。两者的裁剪方向不同，因此需要分别检查正常输入和边界输入。";
const ID = "native-source-learning-plan";
const STAGE_ID = "native-source-learning-stage";

export function prepareSourceLearningFixture({ repoRoot, workspaceDir, root }) {
  const serverDir = path.join(repoRoot, "server");
  const python = path.join(serverDir, ".venv", "bin", "python");
  assert.ok(fs.existsSync(python), "The project-test fixture needs the repository Python environment.");
  fs.symlinkSync(path.join(serverDir, ".venv"), path.join(workspaceDir, ".venv"), "dir");
  const seedPath = path.join(root, "source-learning-plan.py");
  const controlDir = path.join(root, "sidecar-lifecycle");
  fs.mkdirSync(controlDir);
  fs.writeFileSync(seedPath, `
import sys
from pathlib import Path
from app.core.models import LearningPlan, PlanStage
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService

database, workspace = sys.argv[1:]
repository = TrainerRepository(Path(database))
plan = LearningPlan(
    id="${ID}", title="理解 PPO 裁剪行为", current_stage_id="${STAGE_ID}",
    stages=[PlanStage(
        id="${STAGE_ID}", title="对比正常输入和边界", goal="检查裁剪范围",
        outcomes=["检查两个输入"], status="active",
    )],
)
repository.save_plan(workspace, plan)
assert MemoryService(repository).bind_explicit_generated_plan(workspace, plan)
`);
  const implementation = path.join(workspaceDir, "ratio.py");
  // The test fixture is the learner's independent submission, staged only after
  // the installed Coach has generated the practice and before the user verifies.
  const learnerContents = "def bounded_ratio(ratio, margin):\n    return max(1 - margin, min(ratio, 1 + margin))\n";
  fs.writeFileSync(path.join(workspaceDir, "test_ratio.py"), [
    "from ratio import bounded_ratio",
    "",
    "def test_interior_and_boundaries():",
    "    assert bounded_ratio(1.1, 0.2) == 1.1",
    "    assert bounded_ratio(1.4, 0.2) == 1.2",
    "    assert bounded_ratio(0.6, 0.2) == 0.8",
    "",
  ].join("\n"));
  return { serverDir, python, seedPath, controlDir, planId: ID, implementation, learnerContents };
}

function readDatabase(database, callback) {
  const db = new DatabaseSync(database, { readOnly: true });
  db.exec("PRAGMA busy_timeout = 1500");
  try {
    return callback(db);
  } finally {
    db.close();
  }
}

function browserBridgeState(database) {
  return JSON.parse(fs.readFileSync(path.join(path.dirname(database), "browser_bridge.json"), "utf8"));
}

async function startSidecarProxy(initialPort) {
  let allowedOrigin = `http://127.0.0.1:${initialPort}`;
  let online = true;
  let dropped = 0;
  const server = http.createServer((request, response) => {
    let target;
    try {
      target = new URL(request.url);
    } catch {
      response.writeHead(403).end();
      return;
    }
    if (target.origin !== allowedOrigin) {
      response.writeHead(403).end();
      return;
    }
    if (!online) {
      dropped++;
      request.destroy();
      return;
    }
    const upstream = http.request(target, { method: request.method, headers: request.headers }, reply => {
      response.writeHead(reply.statusCode, reply.headers);
      reply.pipe(response);
    });
    upstream.on("error", error => response.destroy(error));
    request.pipe(upstream);
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    disconnect() { online = false; },
    droppedRequests() { return dropped; },
    reconnect(port) { allowedOrigin = `http://127.0.0.1:${port}`; online = true; },
    async close() {
      server.closeAllConnections();
      await new Promise(resolve => server.close(resolve));
    },
  };
}

async function until(read, description, timeout = 30_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = await read();
    if (value) return value;
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  throw new Error(`Timed out waiting for ${description}`);
}

export async function runSourceLearningJourney({
  fixture, setup, frame, page, root, installedRoot, openInCode, record, screenshot,
}) {
  assert.ok(setup?.port && setup.workspaceId && setup.database);
  const restartSidecar = async () => {
    fs.writeFileSync(path.join(fixture.controlDir, "restart.request"), "");
    const file = path.join(fixture.controlDir, "restart.json");
    const state = await until(() => fs.existsSync(file) && JSON.parse(fs.readFileSync(file, "utf8")),
      "the native host's sidecar restart", 75_000);
    assert.ok(state.ok, state.error);
    return state;
  };
  const extensionDir = path.join(installedRoot, "browser-capture");
  const proxy = await startSidecarProxy(setup.port);
  let browser;
  try {
    browser = await chromium.launchPersistentContext(path.join(root, "chromium"), {
    channel: "chromium",
    headless: true,
    args: [
      `--disable-extensions-except=${extensionDir}`,
      `--load-extension=${extensionDir}`,
      `--proxy-server=${proxy.url}`,
      "--proxy-bypass-list=<-loopback>",
    ],
    });
    const worker = browser.serviceWorkers()[0] ?? await browser.waitForEvent("serviceworker");
    await worker.evaluate(() => ensureAutoPair({ force: true }));
    const pairing = await until(() => worker.evaluate(async () => {
      const auth = await TrainerCapture.loadAuth();
      return auth.credential && { workspaceId: auth.workspaceId, baseUrl: auth.baseUrl };
    }), "installed browser auto-pairing");
    assert.equal(pairing.workspaceId, setup.workspaceId);
    assert.equal(new URL(pairing.baseUrl).port, String(setup.port));
    record("browser-auto-pairs-with-installed-host", { ok: true, workspaceId: pairing.workspaceId });

    const sourcePage = await browser.newPage();
    await sourcePage.route(SOURCE_URL, route => route.fulfill({
      contentType: "text/html",
      body: `<!doctype html><meta charset="utf-8"><title>${SOURCE_TITLE}</title><p>${SELECTION}</p>`,
    }));
    await sourcePage.goto(SOURCE_URL);
    const selectionInfo = await sourcePage.locator("p").evaluate(node => {
      const range = document.createRange();
      range.selectNodeContents(node);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      return { selectionText: selection.toString(), pageUrl: location.href, title: document.title };
    });
    assert.equal(selectionInfo.selectionText, SELECTION);
    const composer = frame.locator("#coach-composer").first();
    await composer.waitFor({ timeout: 30_000 });
    const userMessages = frame.locator('article[data-role="user"]');
    const userCount = await userMessages.count();
    await worker.evaluate(info => handleMenuClick(
      { ...info, menuItemId: MENU_IDS.selectionCoach }, { title: info.title, url: info.pageUrl },
    ), selectionInfo);
    await until(async () => (await composer.inputValue()).includes(SELECTION), "selected text in the installed Coach composer");
    await frame.getByRole("link", { name: SOURCE_TITLE, exact: true }).waitFor();
    assert.equal(await userMessages.count(), userCount);
    await until(() => {
      const bridge = browserBridgeState(setup.database);
      return bridge.pending_drafts.length === 0 && bridge.acked_draft_client_ids.length === 1;
    }, "the workbench's durable applied receipt");
    record("selection-prefills-with-source-without-sending", {
      ok: true, screenshot: await screenshot(page, "source-coach-prefill"),
    });
    await composer.press("Enter");
    const coachReply = frame.locator('article[data-role="assistant"]').last();
    await coachReply.waitFor({ timeout: 75_000 });
    await until(async () => (await coachReply.innerText()).includes("裁剪"), "grounded Coach reply", 75_000);
    assert.equal(await userMessages.count(), userCount + 1);
    assert.equal(await coachReply.locator("pre code").count(), 0);
    const persistedSource = await until(() => readDatabase(setup.database, db => {
      const row = db.prepare("SELECT payload FROM sessions WHERE session_id = ? AND workspace_id = ?")
        .get(setup.sessionId, setup.workspaceId);
      const message = row && JSON.parse(row.payload).snapshot.messages.findLast(item => item.role === "user");
      return message?.metadata?.browser_sources?.some(source =>
        source.url === SOURCE_URL && source.selection === SELECTION && source.provenance === "temporary_web");
    }), "the browser provenance on the saved conversation");
    record("learner-sends-and-coach-replies-without-implementation", { ok: true, persistedSource });

    await worker.evaluate(info => handleMenuClick(
      { ...info, menuItemId: MENU_IDS.selectionLibrary }, { title: info.title, url: info.pageUrl },
    ), selectionInfo);
    const link = await until(() => worker.evaluate(async () => {
      const links = await readNotificationLinks();
      return Object.values(links).find(url => url.startsWith("vscode://local.trainer-extension/library/"));
    }), "the saved selection notification deep link");
    const resourceId = decodeURIComponent(new URL(link).pathname.split("/").at(-1));
    record("browser-saves-selected-excerpt", { ok: true, resourceId });
    openInCode(["--reuse-window", "--open-url", link]);
    const reader = frame.locator('[data-template="ResourceReader"]');
    await reader.waitFor({ timeout: 45_000 });
    const join = reader.getByRole("button", { name: "加入当前学习", exact: true });
    await until(() => join.isEnabled(), "the current stage action on the native Reader");
    await join.click();
    await reader.getByText(/已加入/).waitFor();
    record("browser-capture-opens-reader-and-binds-stage", {
      ok: true, resourceId, screenshot: await screenshot(page, "source-reader-joined"),
    });
    await reader.getByRole("button", { name: "基于资料练习", exact: true }).click();
    const card = frame.locator('[data-training-card-id]');
    await card.waitFor({ timeout: 60_000 });
    const cardId = await card.getAttribute("data-training-card-id");
    assert.ok(cardId);
    assert.equal(await card.getByRole("button", { name: SOURCE_TITLE, exact: true }).count(), 1);
    assert.equal(fs.existsSync(fixture.implementation), false);
    record("source-linked-card-created-without-an-implementation", {
      ok: true, cardId, screenshot: await screenshot(page, "source-training"),
    });

    fs.writeFileSync(fixture.implementation, fixture.learnerContents);
    const hash = () => createHash("sha256").update(fs.readFileSync(fixture.implementation)).digest("hex");
    const savedHash = hash();
    openInCode(["--reuse-window", fixture.implementation]);
    await page.getByRole("tab", { name: /ratio\.py/ }).waitFor({ timeout: 30_000 });
    await card.getByRole("button", { name: "验证当前文件", exact: true }).click();
    await card.locator('[data-template="VerificationResult"][data-verdict="passed"]').waitFor({ timeout: 75_000 });
    const readVerification = () => readDatabase(setup.database, db => {
      const rows = db.prepare("SELECT payload FROM training_evidence WHERE workspace_id = ?")
        .all(setup.workspaceId).map(row => JSON.parse(row.payload));
      const evidence = rows.find(row => row.card_id === cardId && row.evidence_kind === "saved_project_tests");
      const memory = JSON.parse(db.prepare("SELECT payload FROM structured_memory WHERE workspace_id = ?")
        .get(setup.workspaceId)?.payload ?? "{}").workspace;
      const schedule = memory?.latest_training_fsrs_states?.[cardId];
      return evidence && schedule && { evidence, schedule, projection: memory.training_skill_projection };
    });
    const state = await until(readVerification, "workspace Evidence Ledger and FSRS state", 75_000);
    assert.equal(state.evidence.result, "passed");
    assert.equal(state.evidence.trust_level, "controlled_check");
    assert.equal(state.evidence.artifact_hash, savedHash);
    assert.equal(state.evidence.resource_id, resourceId);
    assert.equal(state.evidence.environment.scope, "test_suite");
    assert.equal(hash(), savedHash);
    assert.ok(state.evidence.resource_version_id && state.schedule.next_due_at);
    const matchedStage = readDatabase(setup.database, db => {
      const row = db.prepare("SELECT payload FROM learning_plan WHERE plan_id = ? AND workspace_id = ?")
        .get(fixture.planId, setup.workspaceId);
      const stage = row && JSON.parse(row.payload).stages.find(item => item.id === STAGE_ID);
      return stage?.resource_anchors.some(anchor => anchor.resource_id === resourceId
        && anchor.version_id === state.evidence.resource_version_id
        && anchor.content_hash === state.evidence.resource_content_hash);
    });
    assert.equal(matchedStage, true);
    assert.equal(state.schedule.reps, 0);
    assert.equal(state.projection.dimensions.implementation.verified_count, 0);
    record("saved-file-attested-and-review-scheduled", {
      ok: true, cardId, savedHash, dueAt: state.schedule.next_due_at,
      evidenceId: state.evidence.evidence_id,
      screenshot: await screenshot(page, "source-verification"),
    });

    await frame.getByTestId("trainer-view-nav-coach").click();
    proxy.disconnect();
    const offlineSelection = `${SELECTION}【断线恢复】`;
    const queued = await worker.evaluate(async info => {
      const result = await coachDraft(info, { title: info.title, url: info.pageUrl });
      const draft = (await TrainerCapture.loadDraftQueue()).find(item => item.selection === info.selectionText);
      return { status: result.status, draft };
    }, { ...selectionInfo, selectionText: offlineSelection });
    assert.equal(queued.status, "queued");
    assert.ok(proxy.droppedRequests() > 0);
    assert.equal(queued.draft.workspaceId, setup.workspaceId);
    assert.equal((await composer.inputValue()).includes(offlineSelection), false);
    record("offline-selection-remains-in-browser-queue", { ok: true });

    const restarted = await restartSidecar();
    assert.equal(restarted.lifecycle, "ready");
    assert.equal(restarted.workspaceId, setup.workspaceId);
    assert.notEqual(restarted.pid, setup.pid);
    proxy.reconnect(restarted.port);
    await worker.evaluate(() => ensureAutoPair({ force: true }));
    const flushed = await worker.evaluate(() => flushQueue());
    assert.equal(flushed.remaining, 0);
    await until(async () => (await composer.inputValue()).includes(offlineSelection),
      "the recovered offline selection in Coach", 45_000);
    await until(() => {
      const bridge = browserBridgeState(setup.database);
      return bridge.pending_drafts.length === 0 && bridge.acked_draft_client_ids.length === 2;
    }, "acknowledgement of the recovered selection");
    const restored = readVerification();
    assert.deepEqual(restored.schedule, state.schedule);
    assert.equal(restored.evidence.evidence_id, state.evidence.evidence_id);
    assert.equal(await userMessages.count(), userCount + 1);
    record("restart-recovers-draft-and-keeps-attested-evidence", { ok: true, evidenceId: restored.evidence.evidence_id });

    const replayed = await worker.evaluate(async draft => {
      const auth = await TrainerCapture.loadAuth();
      const result = await TrainerCapture.requestJson({
        baseUrl: auth.baseUrl, path: "/browser/coach-draft", method: "POST", credential: auth.credential,
        body: TrainerCapture.buildCoachDraftPayload({ ...draft, clientId: draft.clientDraftId }),
      });
      return Boolean(result.ok && result.body?.duplicate);
    }, queued.draft);
    assert.ok(replayed);
    assert.equal(browserBridgeState(setup.database).pending_drafts.length, 0);
    assert.equal((await composer.inputValue()).split(offlineSelection).length - 1, 1);
    record("replayed-browser-draft-is-not-applied-twice", { ok: true });
  } finally {
    try {
      await browser?.close();
    } finally {
      await proxy.close();
    }
  }
}
