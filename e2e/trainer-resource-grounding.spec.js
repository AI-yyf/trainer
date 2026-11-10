const { test, expect } = require("playwright/test");

test("grounded library reference stays compact and keeps provenance", async ({ page }) => {
  await page.goto("/?scenario=resource-grounding&lang=zh-CN");

  const citation = page.locator('[data-citation-part="true"]').first();
  await expect(citation).toBeVisible();
  await expect(citation).toContainText("并发队列的锁边界");
  await expect(citation).toContainText("¶spine:ch1:/body/p[3]");
  await expect(citation).toHaveAttribute(
    "title",
    /citation:resource-queue-locks:rv-2026-11-10:9f8e7d6c/,
  );
  await expect(citation).toHaveAttribute("title", /rv-2026-11-10/);
  // The transcript must not repeat the library passage itself.
  await expect(page.locator('figure[data-resource-excerpt="true"]')).toHaveCount(0);
  await expect(page.getByText("锁必须覆盖整个写入窗口")).toHaveCount(0);
  await expect(citation.getByText("引用详情")).toHaveCount(0);

  const webSource = page.locator(
    '[data-citation-part="true"][data-reference-origin="web_research"]',
  );
  await expect(webSource).toBeVisible();
  await expect(webSource.getByRole("link", { name: /打开原文 SQLite locking/ })).toHaveAttribute(
    "href",
    "https://sqlite.org/lockingv3.html",
  );
});

test("opening the source carries the real resource id and line", async ({ page }) => {
  await page.addInitScript(() => {
    window.__capturedPreviewActions = [];
    const originalDebug = console.debug.bind(console);
    console.debug = (...args) => {
      if (args[0] === "[trainer:browser-preview]" && args[1]) {
        window.__capturedPreviewActions.push(args[1]);
      }
      originalDebug(...args);
    };
  });
  await page.goto("/?scenario=resource-grounding&lang=zh-CN");

  const citation = page.locator('[data-citation-part="true"]').first();
  await citation.getByRole("button", { name: /打开原文 并发队列的锁边界/ }).click();

  const action = await page.evaluate(() =>
    window.__capturedPreviewActions.find((item) => item.type === "resource/open"),
  );
  expect(action).toMatchObject({
    type: "resource/open",
    payload: { resourceId: "resource-queue-locks", line: 4 },
  });
});

test("updated resource invalidates an older citation without opening it", async ({ page }) => {
  await page.goto("/?scenario=resource-grounding-updated&lang=zh-CN");

  const citation = page.locator('[data-citation-part="true"]').first();
  await expect(citation).toBeVisible();
  await expect(citation).toHaveAttribute("data-citation-invalid", "true");
  await expect(citation).toContainText("资料已更新");
  await expect(citation).not.toContainText("↗");
  await expect(citation.getByRole("button")).toHaveCount(0);
  await expect(citation).toHaveAttribute("title", /当前版本: rv-current/);
});
