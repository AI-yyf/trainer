/**
 * P2 (Trainer 2.0): the "Save prep brief" reply action turns one finished
 * analysis reply into a Research Brief library asset. The webview flow is
 * exercised against a route-mocked draft endpoint; the endpoint's own
 * drafting/normalization contract is covered by server tests
 * (server/tests/test_research_brief_assets.py).
 */
const { test, expect } = require("playwright/test");

const DRAFT_URL_PATTERN = /\/resource\/research-brief\/draft$/;

test("saving a reply as a prep brief reaches the draft endpoint and confirms", async ({ page }) => {
  const briefRequests = [];
  await page.route(DRAFT_URL_PATTERN, async (route) => {
    briefRequests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        saved: true,
        brief: { researchGoal: "Thread locks", findings: [] },
        asset: { id: "asset-brief-e2e", assetType: "research_brief" },
      }),
    });
  });

  await page.setViewportSize({ width: 420, height: 761 });
  await page.goto("/?view=coach&scenario=ready&lang=zh-CN&connection=connected");
  const saveBrief = page
    .locator(".message-bubble__icon-action[data-message-quick-action='save-research-brief']")
    .last();
  await expect(saveBrief).toBeVisible();
  await saveBrief.click();

  await expect(
    page.locator(".template-global-state").getByText("备课简报已存入资料库。"),
  ).toBeVisible({ timeout: 30000 });
  expect(briefRequests).toHaveLength(1);
  const payload = briefRequests[0];
  expect(payload.save).toBe(true);
  expect((payload.reply ?? "").length).toBeGreaterThan(0);
  expect((payload.researchGoal ?? "").length).toBeGreaterThan(0);
  expect(payload.context_id ?? payload.workspace_id).toBeTruthy();
});

test("a failed brief save surfaces the honest error", async ({ page }) => {
  await page.route(DRAFT_URL_PATTERN, async (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: { code: "provider_unavailable" } }),
    }));
  await page.setViewportSize({ width: 420, height: 761 });
  await page.goto("/?view=coach&scenario=ready&lang=zh-CN&connection=connected");
  const saveBrief = page
    .locator(".message-bubble__icon-action[data-message-quick-action='save-research-brief']")
    .last();
  await saveBrief.click();

  // Raw failure text is sanitized by design; the recoverable-operation copy is
  // the honest surface a learner gets when the brief cannot be prepared.
  await expect(page.getByRole("alert")).toContainText("这一步暂时没完成。再试一次。", {
    timeout: 30000,
  });
});
