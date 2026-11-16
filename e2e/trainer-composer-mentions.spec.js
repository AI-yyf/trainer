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
  await page.getByRole("button", { name: "添加", exact: true }).click();
  await page.getByRole("menuitemcheckbox", { name: "资料", exact: true }).click();
  await expect(page.locator(".composer-menu-panel")).toBeVisible();
  await page.locator("body").click({ position: { x: 20, y: 20 } });
  await expect(page.locator(".composer-menu-panel")).toHaveCount(0);
});

test("the single Add menu exposes attachments and skills directly", async ({ page }) => {
  await page.setViewportSize({ width: 340, height: 640 });
  await page.goto("/?scenario=ready&lang=en-US&theme=light");
  const composer = page.locator("#coach-composer");
  const add = page.getByRole("button", { name: "Add", exact: true });
  const menu = page.getByRole("menu", { name: "Add", exact: true });
  await expect(page.locator(".composer__leading-actions button")).toHaveCount(1);
  await add.focus();
  await add.press("ArrowDown");
  await expect(menu.getByRole("menuitem", { name: "Attachment" })).toBeFocused();
  // Workflows is no longer a product entry (§十: automatic skills, typed / only).
  await expect(menu.getByRole("menuitem", { name: "Workflows" })).toHaveCount(0);
  await expect(menu.getByText("Skills", { exact: true })).toBeAttached();
  await expect(menu.getByText(/View all|See all/i)).toHaveCount(0);
  const bounds = await menu.boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.y).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(340);
  await page.keyboard.press("Escape");
  await expect(add).toBeFocused();

  // The accelerator survives as a typed shortcut, not as a menu.
  await composer.fill("/sea");
  const deck = page.getByRole("list", { name: "Slash Commands" });
  await expect(deck).toBeVisible();
  await deck.getByRole("button", { name: "/search" }).click();
  await expect(composer).toBeFocused();
  await expect(composer).toHaveValue("/search ");
  await composer.fill("");

  await composer.fill("threads and locks");
  await add.click();
  await menu.getByRole("menuitem", { name: /explain/i }).first().click();
  await expect(composer).toHaveValue(/^\$[^ ]+ threads and locks$/);
  await expect(menu).toHaveCount(0);
});

test("Goal mode keeps an existing draft and explicitly sends the first goal as coaching", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=coach&scenario=ready&lang=zh-CN&connection=connected");
  const composer = page.locator("#coach-composer");
  const goal = "制定学习计划来掌握 Python 锁";
  const bar = page.locator("[data-goal-bar=true]");
  const openGoalMode = async () => {
    await page.getByRole("button", { name: "添加", exact: true }).click();
    await page.getByRole("menuitemcheckbox", { name: "目标模式", exact: true }).click();
  };
  await composer.fill(goal);
  await openGoalMode();
  await expect(bar).toHaveAttribute("data-goal-pending", "true");
  await expect(composer).toBeFocused();
  await expect(composer).toHaveValue(goal);
  await bar.getByRole("button", { name: "退出目标模式" }).click();
  await expect(bar).toHaveCount(0);
  await expect(composer).toHaveValue(goal);
  await openGoalMode();
  await composer.press("Enter");
  await expect(bar).toHaveAttribute("data-goal-pending", "false");
  await expect(bar).toContainText(goal);
  await expect(page.locator("main").getByText(goal, { exact: true })).toBeVisible();
  await bar.getByRole("button", { name: "暂停目标" }).click();
  await expect(bar).toHaveAttribute("data-goal-paused", "true");
  await bar.getByRole("button", { name: "继续目标" }).click();
  await expect(bar).toHaveAttribute("data-goal-paused", "false");
  await bar.getByRole("button", { name: "结束目标" }).click();
  await expect(bar).toHaveCount(0);
});
