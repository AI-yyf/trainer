const { test, expect } = require("playwright/test");

test("@ opens a resource/file picker and inserts the selected reference", async ({ page }) => {
  await page.goto("/?scenario=ready&lang=zh-CN");
  const composer = page.locator("#coach-composer");
  await expect(composer).toBeVisible();

  await composer.fill("请参考 @");
  const menu = page.getByRole("listbox", { name: "关联资料或文件" });
  await expect(menu).toBeVisible();

  const options = menu.getByRole("option");
  await expect(options.first()).toBeVisible();
  const firstLabel = (await options.first().innerText()).trim();
  await options.first().click();

  await expect(menu).toHaveCount(0);
  await expect(composer).toHaveValue(/@.+/);
  await expect(composer).not.toHaveValue(/@$/);
  expect(firstLabel.length).toBeGreaterThan(0);
});

test("@ can be escaped and keeps the typed text", async ({ page }) => {
  await page.goto("/?scenario=ready&lang=zh-CN");
  const composer = page.locator("#coach-composer");
  await composer.fill("请参考 @");
  await expect(page.getByRole("listbox", { name: "关联资料或文件" })).toBeVisible();
  await composer.press("Escape");
  await expect(page.getByRole("listbox", { name: "关联资料或文件" })).toHaveCount(0);
  await expect(composer).toHaveValue("请参考 @");
});

test("composer stays editable while a reply is streaming", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=coach&scenario=ready&lang=zh-CN&connection=connected");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const composer = page.locator("#coach-composer");

  await page.evaluate(() => {
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__?.({
      type: "stream/start",
      payload: { messageId: "e2e-mention-stream" },
    });
  });
  await expect(page.locator(".message-bubble--streaming")).toBeVisible();
  await expect(composer).toBeEnabled();
  await composer.fill("等待回复时继续编辑下一条");

  await expect(composer).toHaveValue("等待回复时继续编辑下一条");
  await expect(page.locator(".composer__send")).toHaveAttribute("aria-label", /取消/);
});

test("@ menu closes on a click outside the composer", async ({ page }) => {
  await page.goto("/?scenario=ready&lang=zh-CN");
  const composer = page.locator("#coach-composer");
  await composer.fill("请参考 @");
  await expect(page.getByRole("listbox", { name: "关联资料或文件" })).toBeVisible();
  await page.locator("body").click({ position: { x: 20, y: 20 } });
  await expect(page.getByRole("listbox", { name: "关联资料或文件" })).toHaveCount(0);
});

test("resource menu closes on an outside click", async ({ page }) => {
  await page.goto("/?scenario=ready&lang=zh-CN");
  await page.locator('.composer__leading-actions button[aria-label="资料"]').first().click();
  await expect(page.locator(".composer-menu-panel")).toBeVisible();
  await page.locator("body").click({ position: { x: 20, y: 20 } });
  await expect(page.locator(".composer-menu-panel")).toHaveCount(0);
});

test("streaming Markdown preserves code, math, tables and list continuations", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/vscode-preview.html?view=coach&scenario=ready&lang=en-US&connection=connected");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();

  const send = (type, payload = {}) => page.evaluate(({ type, payload }) => {
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
      type,
      payload: { messageId: "e2e-markdown", ...payload },
    });
  }, { type, payload });
  await send("stream/start");
  const opening = "Example\n\n```python\nvalue = 1\n\n";
  await send("stream/chunk", { chunk: opening });

  const reply = page.locator(".message-bubble--streaming .message-markdown");
  await expect(reply.locator(".code-block-wrapper")).toHaveCount(1);

  const list = "print(value)\n```\n\n1. First item\n\n   Continuation paragraph\n\n2. Second item\n\n";
  await send("stream/chunk", { chunk: list });
  const block = reply.locator(".code-block-wrapper");
  await expect(block).toHaveCount(1);
  await expect(block).toContainText("print(value)");
  await block.hover();
  await block.locator(".code-block-copy-btn").click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("value = 1\n\nprint(value)");
  await expect(reply.locator("ol > li").first()).toContainText("Continuation paragraph");

  const formulaAndHeader = "\\[\n\nE = mc^2\n\n\\]\n\n| Value | Result |\n| --- | --- |\n";
  await send("stream/chunk", { chunk: formulaAndHeader });
  await expect(reply.locator(".katex")).toHaveCount(1);
  await expect(reply.locator("table th")).toHaveCount(2);

  const table = reply.locator("table");
  const originalTable = await table.elementHandle();
  const ending = "| 1 | Ready |\n\nDone.";
  await send("stream/chunk", { chunk: ending });
  await expect(table.locator("tbody td")).toHaveText(["1", "Ready"]);
  expect(await table.evaluate((element, previous) => element === previous, originalTable)).toBe(true);
  await send("stream/complete", { tokens: 40 });
  await page.evaluate((body) => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
    type: "bootstrap",
    payload: {
      ...window.__TRAINER_BOOTSTRAP__,
      conversation: [{ id: "e2e-markdown", role: "assistant", author: "Trainer", timestamp: "10:00", body }],
    },
  }), opening + list + formulaAndHeader + ending);

  const completed = page.locator(".message-markdown").filter({ hasText: "Continuation paragraph" });
  await expect(completed.locator(".code-block-wrapper")).toHaveCount(1);
  await expect(completed.locator("table tbody td")).toHaveText(["1", "Ready"]);
  await expect(completed.locator(".katex")).toHaveCount(1);
});

test("the goal bar sends separate archive and complete commands", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=coach&scenario=ready&lang=en-US&connection=connected");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const bootstrap = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  const goal = {
    goalId: "goal-click", title: "Explain FIFO", status: "active", source: "user_explicit",
    concept: "", capability: "", currentPosition: "", activities: [], activityCount: 0,
    evidenceCount: 0, startedAt: "", updatedAt: "",
  };
  await page.addInitScript(({ bootstrap, goal }) => {
    window.goalCommands = [];
    window.acquireVsCodeApi = () => ({
      getState: () => ({ activeView: "coach", composerLanguage: "en-US" }),
      setState: () => undefined,
      postMessage: (message) => {
        if (message.type === "request/bootstrap") {
          window.postMessage({ type: "bootstrap", payload: { ...bootstrap, goal } }, location.origin);
        } else if (message.type === "command/execute" && message.payload.commandId === "trainer.goal.control") {
          window.goalCommands.push(message.payload.payload);
        }
      },
    });
  }, { bootstrap, goal });
  await page.goto("/");
  const bar = page.locator("[data-goal-bar]");
  await expect(bar).toBeVisible();
  await bar.getByRole("button", { name: "End and archive" }).click();
  await expect(bar).toBeVisible();
  await bar.getByRole("button", { name: "Show goal details" }).click();
  await bar.getByRole("button", { name: "Mark as complete" }).click();
  await expect.poll(() => page.evaluate(() => window.goalCommands)).toEqual([
    { action: "archive", goalId: goal.goalId },
    { action: "complete", goalId: goal.goalId },
  ]);
});
