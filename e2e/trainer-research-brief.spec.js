/**
 * P2 (Trainer 2.0): the "Save prep brief" reply action turns one finished
 * analysis reply into a Research Brief library asset. The webview flow is
 * exercised against a route-mocked draft endpoint; the endpoint's own
 * drafting/normalization contract is covered by server tests
 * (server/tests/test_research_brief_assets.py).
 */
const { test, expect } = require("playwright/test");

const DRAFT_URL_PATTERN = /\/resource\/research-brief\/draft$/;
const quotation = "Shard ownership is checked before contention is resolved.";
const asset = {
  id: "asset-brief-e2e", assetType: "research_brief", title: "Thread locks brief", status: "active",
  payload: {
    researchGoal: "Thread locks", openQuestions: ["How does the lease expire?"],
    findings: [
      { statement: "Check ownership before taking the lock.", claimStatus: "sourced", sourceRefs: [{
        kind: "resource", ref: "lock-source", label: "Lock Notes",
        metadata: { resource_id: "lock-source", version_id: "rv-1", content_hash: "hash-1",
          excerpt: quotation, location: { line_start: 7, line_end: 7, page: 2 } },
      }] },
      { statement: "The old claim has a label without a pinned excerpt.", claimStatus: "sourced", sourceRefs: [{
        kind: "resource", ref: "lock-source", label: "Lock Notes", metadata: { location: "Chapter 1" },
      }] },
      { statement: "A lease may make recovery easier.", claimStatus: "inferred" },
    ],
  },
};

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
        asset,
      }),
    });
  });

  await page.setViewportSize({ width: 420, height: 761 });
  await page.goto("/?view=coach&scenario=ready&lang=zh-CN&connection=connected");
  const lastTools = page.locator(".message-bubble__quick-tools").last();
  await lastTools.locator("[data-message-quick-action='more']").click();
  const saveBrief = lastTools.locator(
    ".message-bubble__more-menu [data-message-quick-action='save-research-brief']",
  );
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

  await page.getByTestId("trainer-view-nav-resources").click();
  const briefs = page.locator("[data-research-briefs]");
  await briefs.locator(":scope > summary").click();
  await briefs.locator("[data-research-brief-id] > summary").click();
  await expect(briefs.getByText(quotation)).toBeVisible();
  await expect(briefs.locator("[data-brief-claim-status=unverified]")).toContainText("The old claim");
  await expect(briefs.locator("[data-brief-claim-status=inferred]")).toContainText("A lease may");
  await expect(briefs.getByText("第 2 页 · 第 7 行")).toBeVisible();
  for (const surface of [
    briefs.locator("[data-research-brief-id]"),
    briefs.locator(".resource-briefs__findings > li").first(),
    briefs.locator(".resource-citation-chip").first(),
  ]) {
    expect(await surface.evaluate((element) => {
      const style = getComputedStyle(element);
      return [style.borderInlineStartWidth, style.borderInlineEndWidth, style.borderRadius, style.backgroundColor];
    })).toEqual(["0px", "0px", "0px", "rgba(0, 0, 0, 0)"]);
  }
  await expect(briefs.locator("blockquote").first()).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
});

test("Resources restores saved briefs and forwards only current, pinned citations", async ({ page }) => {
  const workspaceId = "brief-restore-workspace";
  let version = "rv-1";
  await page.addInitScript((id) => {
    sessionStorage.setItem("trainer:webview:preview:workspace-id", id);
    window.addEventListener("trainer:webview-action", (event) => {
      if (event.detail.type !== "resource/open") return;
      window.lastBriefSource = event.detail.payload;
      event.stopImmediatePropagation();
    });
  }, workspaceId);
  await page.route("http://127.0.0.1:34907/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/session/start") return route.fulfill({ json: { session_id: "brief-restore-session" } });
    if (path === "/memory/summary") return route.fulfill({ json: { memory: {
      workspace: { workspace_id: workspaceId },
      assetCatalog: { active: [{ asset }] },
      resources: [{ id: "lock-source", name: "Lock Notes", kind: "markdown", source: "lock-notes.md",
        index_status: "indexed", version_id: version, content_hash: "hash-1" }],
    } } });
    return route.fulfill({ json: { status: "ok" } });
  });

  const openBrief = async () => {
    const briefs = page.locator("[data-research-briefs]");
    await briefs.locator(":scope > summary").click();
    await briefs.locator("[data-research-brief-id] > summary").click();
    return briefs;
  };
  await page.setViewportSize({ width: 340, height: 820 });
  await page.goto("/vscode-preview.html?view=resources&live=1&lang=en-US&sidecarPort=34907");
  const briefs = await openBrief();
  await briefs.getByRole("button", { name: "Open source Lock Notes" }).click();
  expect(await page.evaluate(() => window.lastBriefSource)).toEqual({
    resourceId: "lock-source", line: 7,
    researchCitation: { versionId: "rv-1", contentHash: "hash-1", excerpt: quotation, lineEnd: 7 },
  });
  await briefs.locator("[data-research-brief-id] .template-disclosure > summary").click();
  await expect(briefs.getByText("How does the lease expire?")).toBeVisible();

  version = "rv-2";
  await page.reload();
  const restored = await openBrief();
  await expect(restored.locator("[data-citation-invalid=true]")).toBeVisible();
  await expect(restored.getByRole("button", { name: "Open source Lock Notes" })).toHaveCount(0);
});

test("a preparation reply opens the exact saved brief in Resources", async ({ page }) => {
  const workspaceId = "prepared-reply-workspace";
  const other = { ...asset, id: "asset-earlier-brief", title: "Earlier brief" };
  await page.addInitScript((id) => {
    sessionStorage.setItem("trainer:webview:preview:workspace-id", id);
  }, workspaceId);
  await page.route("http://127.0.0.1:34907/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/session/start") return route.fulfill({ json: { session_id: "prepared-reply-session" } });
    if (path === "/memory/summary") return route.fulfill({ json: {
      messages: [{
        id: "completed-preparation", role: "assistant", content: "I compared the two locking approaches.",
        metadata: { active_view: "coach", research_preparation: { status: "saved", asset_id: asset.id, title: asset.title } },
      }],
      memory: { workspace: { workspace_id: workspaceId }, assetCatalog: { active: [{ asset: other }, { asset }] } },
    } });
    return route.fulfill({ json: { status: "ok" } });
  });

  await page.setViewportSize({ width: 340, height: 820 });
  await page.goto("/vscode-preview.html?view=coach&live=1&lang=en-US&sidecarPort=34907");
  await page.getByRole("button", { name: "Open saved research brief" }).click();
  const saved = page.locator(`[data-research-brief-id="${asset.id}"]`);
  await expect(saved.getByText(quotation)).toBeVisible();
  await expect(saved.locator(":scope > summary")).toBeFocused();
  await expect(page.locator(`[data-research-brief-id="${other.id}"]`)).not.toHaveAttribute("open", "");
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
  const lastTools = page.locator(".message-bubble__quick-tools").last();
  await lastTools.locator("[data-message-quick-action='more']").click();
  const saveBrief = lastTools.locator(
    ".message-bubble__more-menu [data-message-quick-action='save-research-brief']",
  );
  await saveBrief.click();

  // Raw failure text is sanitized by design; the recoverable-operation copy is
  // the honest surface a learner gets when the brief cannot be prepared.
  await expect(page.getByRole("alert")).toContainText("这一步暂时没完成。再试一次。", {
    timeout: 30000,
  });
});
