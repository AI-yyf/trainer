import assert from "node:assert/strict";
import { browserBridgeState, launchInstalledCapture, startSidecarProxy, until } from "./source-learning-journey.mjs";

export async function runSourceFocusJourney({ app, windows, root, installedRoot, record, screenshot }) {
  const [first, second] = windows;
  assert.notEqual(first.setup.workspaceId, second.setup.workspaceId);
  assert.notEqual(first.setup.port, second.setup.port);
  assert.notEqual(first.setup.pid, second.setup.pid);
  assert.equal(first.setup.database, second.setup.database);
  const proxy = await startSidecarProxy(first.setup.port, second.setup.port);
  const composers = windows.map(({ frame }) => frame.locator("#coach-composer").first());
  const messages = windows.map(({ frame }) => frame.locator('article[data-role="user"]'));
  const counts = await Promise.all(messages.map(locator => locator.count()));
  let browser;
  try {
    browser = await launchInstalledCapture({ root, installedRoot, proxy });
    const worker = browser.serviceWorkers()[0] ?? await browser.waitForEvent("serviceworker");
    const webpage = await browser.newPage();
    const url = "https://example.com/trainer-paper/window-focus";
    const title = "Trainer · 浏览器工作区切换";
    const selections = ["甲窗口选段：分析裁剪条件。", "乙窗口选段：检查比值范围。", "甲窗口离线选段：比较两种优势符号。"];
    await webpage.route(url, route => route.fulfill({
      contentType: "text/html",
      body: `<!doctype html><meta charset="utf-8"><title>${title}</title>${selections.map(text => `<p>${text}</p>`).join("")}`,
    }));
    await webpage.goto(url);

    const candidate = ({ setup }) => worker.evaluate(port =>
      TrainerCapture.fetchAutoPairCandidate(`http://127.0.0.1:${port}`), setup.port);
    const focus = async target => {
      const previous = await candidate(target);
      await app.focus(target.page);
      await until(() => target.page.evaluate(() => document.hasFocus()), "the native renderer to gain focus");
      const focused = await until(async () => {
        const current = await candidate(target);
        return current?.focusAt > (previous?.focusAt ?? 0) && current;
      }, `VS Code to report focus for ${target.setup.workspaceId} (previous ${JSON.stringify(previous)})`);
      assert.equal(focused.workspaceId, target.setup.workspaceId);
      return focused.focusAt;
    };
    const pair = target => worker.evaluate(async expected => {
      await ensureAutoPair({ force: true });
      const auth = await TrainerCapture.loadAuth();
      return Boolean(auth.credential && auth.workspaceId === expected.workspaceId &&
        new URL(auth.baseUrl).port === String(expected.port));
    }, { workspaceId: target.setup.workspaceId, port: target.setup.port });
    const selectAndAsk = async index => {
      const selected = await webpage.locator("p").nth(index).evaluate(node => {
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(node);
        selection.removeAllRanges();
        selection.addRange(range);
        return { selectionText: selection.toString(), pageUrl: location.href };
      });
      assert.equal(selected.selectionText, selections[index]);
      return worker.evaluate(({ selection, title }) => handleMenuClick(
        { ...selection, menuItemId: MENU_IDS.selectionCoach }, { title, url: selection.pageUrl },
      ), { selection: selected, title });
    };
    const acknowledgedFor = index => {
      const { setup } = windows[index];
      const bridge = browserBridgeState(setup.database);
      return bridge.acked_draft_client_ids.filter(key => key.startsWith(`${setup.workspaceId}\0`));
    };
    const expectDraft = async (index, selectionIndex, acknowledged) => {
      const text = selections[selectionIndex];
      await until(async () => (await composers[index].inputValue()).includes(text), `the draft to reach window ${index + 1}`);
      await windows[index].frame.getByRole("link", { name: title, exact: true }).waitFor();
      await until(() => {
        const bridge = browserBridgeState(windows[index].setup.database);
        return bridge.pending_drafts.length === 0 && acknowledgedFor(index).length === acknowledged;
      }, `the durable acknowledgement from window ${index + 1}`);
      assert.equal((await composers[1 - index].inputValue()).includes(text), false);
    };
    const drafts = () => worker.evaluate(() => TrainerCapture.loadDraftQueue());

    // The second window starts in front. Focus the original window in the same
    // Electron process and wait for the production extension to report it.
    const firstFocus = await focus(first);
    assert.ok(firstFocus > (await candidate(second))?.focusAt);
    await selectAndAsk(0);
    await expectDraft(0, 0, 1);
    assert.ok(await pair(first));
    await composers[0].evaluate(composer => { composer.scrollTop = 0; });
    record("browser-draft-follows-first-native-window", { ok: true, screenshot: await screenshot(first.page, "source-focus-first") });
    await composers[0].fill("");

    // Keep both VS Code windows alive while the browser loses both connections.
    proxy.disconnect(first.setup.port);
    proxy.disconnect(second.setup.port);
    await selectAndAsk(2);
    const queued = (await drafts()).find(item => item.selection === selections[2]);
    assert.equal(queued?.workspaceId, first.setup.workspaceId);
    assert.ok(proxy.droppedRequests() > 0);

    proxy.reconnect(first.setup.port);
    proxy.reconnect(second.setup.port);
    const secondFocus = await focus(second);
    assert.ok(secondFocus > firstFocus);
    await selectAndAsk(1);
    await expectDraft(1, 1, 1);
    assert.ok(await pair(second));
    await worker.evaluate(() => flushQueue());
    assert.deepEqual((await drafts()).map(item => item.clientDraftId), [queued.clientDraftId]);
    assert.equal((await composers[1].inputValue()).includes(selections[2]), false);
    assert.equal(browserBridgeState(second.setup.database).pending_drafts.length, 0);
    await composers[1].evaluate(composer => { composer.scrollTop = 0; });
    record("browser-switches-native-workspace-without-moving-queued-draft", {
      ok: true, screenshot: await screenshot(second.page, "source-focus-second"),
    });

    assert.ok(await focus(first) > secondFocus);
    assert.ok(await pair(first));
    await worker.evaluate(() => flushQueue());
    await expectDraft(0, 2, 2);
    assert.deepEqual(await drafts(), []);
    assert.equal(acknowledgedFor(1).length, 1);
    assert.deepEqual(await Promise.all(messages.map(locator => locator.count())), counts);
    record("original-native-workspace-recovers-its-draft-without-sending", { ok: true });
  } finally {
    try {
      await browser?.close();
    } finally {
      await proxy.close();
    }
  }
}
