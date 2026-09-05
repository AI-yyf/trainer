const { test, expect } = require("playwright/test");

const PREVIEW_PATH = "/vscode-preview.html";

async function expectNoHorizontalOverflow(page) {
  const metrics = await page.evaluate(() => ({
    bodyClientWidth: document.body.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
    rootClientWidth: document.documentElement.clientWidth,
    rootScrollWidth: document.documentElement.scrollWidth,
  }));

  expect(metrics.bodyScrollWidth).toBeLessThanOrEqual(metrics.bodyClientWidth + 1);
  expect(metrics.rootScrollWidth).toBeLessThanOrEqual(metrics.rootClientWidth + 1);
}

test("RTL preview keeps the 360px Trainer shell readable and bounded", async ({ page }) => {
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });

  await page.setViewportSize({ width: 360, height: 760 });
  await page.goto(`${PREVIEW_PATH}?view=coach&lang=en-US&dir=rtl&scenario=rtl-i18n`);

  await expect(page.locator(".trainer-shell")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("body")).toHaveAttribute("dir", "rtl");
  await expect(page.getByTestId(/^trainer-view-nav-(coach|plan|resources|training|settings)$/)).toHaveCount(5);
  await expect(page.locator(".composer-shell textarea").first()).toBeVisible();
  await expectNoHorizontalOverflow(page);

  const shellDirection = await page.locator(".trainer-shell").evaluate((element) => {
    return window.getComputedStyle(element).direction;
  });
  expect(shellDirection).toBe("rtl");
  expect(consoleErrors).toEqual([]);
});
