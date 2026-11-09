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
