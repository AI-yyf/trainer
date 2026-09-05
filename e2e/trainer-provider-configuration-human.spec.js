/**
 * Human-style Provider setup lifecycle in the browser preview.
 *
 * All provider traffic is mocked at the local preview boundary. The credential is
 * intentionally ephemeral and must never enter persisted provider metadata.
 */

const { randomUUID } = require("node:crypto");
const { test, expect } = require("playwright/test");

const PREVIEW_PATH = "/vscode-preview.html";

function previewUrl() {
  const query = new URLSearchParams({
    view: "settings",
    lang: "en-US",
    connection: "connected",
    live: "1",
    run: `provider-human-${randomUUID()}`,
  });
  return `${PREVIEW_PATH}?${query.toString()}`;
}

function jsonResponse(body, status = 200) {
  return {
    status,
    contentType: "application/json",
    headers: { "access-control-allow-origin": "*" },
    body: JSON.stringify(body),
  };
}

function providerDetail(page) {
  return page.locator(".coach-settings-view__provider-detail");
}

function connectionFields(detail) {
  return detail.locator("details.settings-sheet__minor-panel").filter({
    hasText: "Connection fields and key",
  });
}

async function openDetails(page) {
  const detail = providerDetail(page);
  await expect(detail).toBeVisible();
  if (!(await detail.evaluate((element) => element.open))) {
    await detail.locator(":scope > summary").click();
  }
  const fields = connectionFields(detail);
  if (!(await fields.evaluate((element) => element.open))) {
    await fields.locator(":scope > summary").click();
  }
  return { detail, fields };
}

async function openModelPicker(detail) {
  const fields = connectionFields(detail);
  const picker = fields.locator("details.settings-model-picker");
  if (!(await picker.evaluate((element) => element.open))) {
    await picker.locator(":scope > summary").click();
  }
  return picker;
}

async function openProfiles(page) {
  const profiles = page.locator(".settings-sheet__provider-profiles");
  await expect(profiles).toBeVisible();
  if (!(await profiles.evaluate((element) => element.open))) {
    await profiles.locator(":scope > summary").click();
  }
  return profiles;
}

async function persistedProvider(page) {
  return page.evaluate(() => {
    const key = window.__TRAINER_PREVIEW_STORAGE_KEY__;
    const raw = key ? window.localStorage.getItem(key) : null;
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed.previewProviderConfig ?? {};
  });
}

test.describe("human Provider configuration preview", () => {
  test.setTimeout(60_000);

  test("empty state, template, model, native thinking, intercepted failure/retry, profile switch, Coach", async ({
    page,
  }) => {
    const credential = `preview-ephemeral-${randomUUID()}`;
    const consoleErrors = [];
    const testPayloads = [];
    let testCount = 0;

    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    await page.addInitScript(() => {
      window.localStorage.clear();
      window.sessionStorage.clear();
    });
    await page.route("**/health", (route) => route.fulfill(jsonResponse({ status: "ok" })));
    await page.route("**/session/start", (route) =>
      route.fulfill(jsonResponse({ session_id: "provider-human-preview" })),
    );
    await page.route("**/memory/settings", (route) => route.fulfill(jsonResponse({})));
    await page.route("**/memory/summary**", (route) => route.fulfill(jsonResponse({})));
    await page.route("**/provider/test", async (route) => {
      const payload = JSON.parse(route.request().postData() || "{}");
      testPayloads.push(payload);
      testCount += 1;
      if (testCount === 1) {
        await route.fulfill(
          jsonResponse({
            ok: false,
            status: "model_not_found",
            error_category: "model_not_found",
            retryable: true,
            status_code: 404,
            detail: "mock upstream model failure",
          }),
        );
        return;
      }
      await route.fulfill(
        jsonResponse({
          ok: true,
          status: "connected",
          diagnostics: ["Mock provider accepted the retry."],
          capability_evidence: [
            { name: "streaming", declared: true, observed: true, state: "verified" },
            { name: "tools", declared: true, observed: true, state: "verified" },
          ],
          streaming_ready: true,
          tools_ready: true,
        }),
      );
    });

    await page.goto(previewUrl());
    await page.waitForLoadState("networkidle");

    const initial = await openDetails(page);
    await expect(initial.fields.getByLabel("API Key", { exact: true })).toHaveValue("");
    await expect(page.locator(".settings-provider-profile")).toHaveCount(0);

    await page.getByRole("button", { name: /Use MiniMax profile|MiniMax template/i }).click();
    await expect(initial.fields.getByLabel("Service root")).toHaveValue("https://api.minimaxi.com/v1");
    await expect(initial.fields.getByLabel("Connection name (optional)")).toHaveValue("MiniMax");

    const picker = await openModelPicker(initial.detail);
    const modelSelect = picker.getByRole("combobox", { name: "Model", exact: true });
    const hasReasoningOption =
      (await modelSelect.count()) > 0 &&
      (await modelSelect.locator("option").evaluateAll((options) =>
        options.some((option) => option.textContent?.trim() === "preview-reasoning" || option.value === "preview-reasoning"),
      ));
    if (hasReasoningOption) {
      await modelSelect.selectOption({ label: "preview-reasoning" });
    } else {
      await expect(picker.locator(":scope > summary")).toContainText("MiniMax-M3");
    }
    const selectedModel = hasReasoningOption ? "preview-reasoning" : "MiniMax-M3";
    await expect(picker.locator(":scope > summary")).toContainText(selectedModel);

    const advanced = initial.detail.locator("details.settings-sheet__provider-catalog");
    await expect(advanced).toBeVisible();
    if (!(await advanced.evaluate((element) => element.open))) {
      await advanced.locator(":scope > summary").click();
    }
    const advancedRouting = advanced.locator("details.settings-sheet__minor-panel").last();
    if (!(await advancedRouting.evaluate((element) => element.open))) {
      await advancedRouting.locator(":scope > summary").click();
    }
    const requestDefaults = advancedRouting.locator("textarea").last();
    await expect(requestDefaults).toBeVisible();
    const nativeThinking = '{"thinking":{"type":"enabled","budget_tokens":2048}}';
    await requestDefaults.fill(nativeThinking);
    await initial.fields.getByLabel("API Key", { exact: true }).fill(credential);

    const profiles = await openProfiles(page);
    await profiles.getByRole("button", { name: "Save as connection", exact: true }).click();
    await expect(profiles.locator(".settings-provider-profile")).toHaveCount(2);

    const saved = await persistedProvider(page);
    expect(JSON.stringify(saved)).not.toContain(credential);
    expect(saved.requestDefaults).toMatchObject({ extra_body: { thinking: { type: "disabled" } } });

    const testButton = page.getByRole("button", { name: "Test Connection", exact: true }).first();
    await expect(testButton).toBeEnabled();
    await testButton.click();
    await expect(page.locator('[data-availability-fact="test"]')).toContainText("Failed");
    await expect(page.locator(".notice.notice--error")).toBeVisible();
    expect(testPayloads[0].api_key).toBe(credential);
    expect(testPayloads[0].provider.apiKey).toBeUndefined();
    expect(JSON.stringify(testPayloads[0].provider)).not.toContain(credential);
    expect(await persistedProvider(page)).not.toHaveProperty("lastTestResult.ok", true);

    await openModelPicker(initial.detail);
    const retryPicker = initial.detail.locator("details.settings-model-picker");
    const retrySelect = retryPicker.getByRole("combobox", { name: "Model", exact: true });
    const hasChatOption =
      (await retrySelect.count()) > 0 &&
      (await retrySelect.locator("option").evaluateAll((options) =>
        options.some((option) => option.textContent?.trim() === "preview-chat" || option.value === "preview-chat"),
      ));
    const retryModel = hasChatOption ? "preview-chat" : "MiniMax-M3";
    if (hasChatOption) {
      await retrySelect.selectOption({ label: retryModel });
    }
    await expect(page.getByRole("button", { name: `Save and use ${retryModel}`, exact: true })).toBeVisible();
    const retrySave = page.getByRole("button", { name: `Save and use ${retryModel}`, exact: true });
    if (await retrySave.isEnabled()) await retrySave.click();
    await testButton.click();
    await expect(page.locator('[data-availability-fact="test"]')).toContainText("Passed");
    await expect(page.locator(".settings-availability-strip")).toContainText("Ready");
    expect(testPayloads[1].provider.model).toBe(retryModel);
    expect(testPayloads[1].api_key).toBe(credential);

    const secondProfileName = "Preview fallback profile";
    const secondDraft = await openDetails(page);
    await secondDraft.fields.getByLabel("Connection name (optional)").fill(secondProfileName);
    await secondDraft.fields.getByLabel("API Key", { exact: true }).fill(credential);
    const secondProfiles = await openProfiles(page);
    await secondProfiles.getByRole("button", { name: "Save as connection", exact: true }).click();
    await expect(secondProfiles.locator(".settings-provider-profile")).toHaveCount(3);
    const fallbackProfile = secondProfiles.locator(".settings-provider-profile").filter({ hasText: secondProfileName });
    await expect(fallbackProfile).toHaveAttribute("aria-pressed", "true");
    const switchTarget = secondProfiles.locator(".settings-provider-profile:not([disabled])").first();
    await expect(switchTarget).toBeVisible();
    await switchTarget.click();
    await expect(secondProfiles.locator('.settings-provider-profile[aria-pressed="true"]')).toHaveCount(1);

    await page.getByTestId("trainer-view-nav-coach").click();
    await expect(page.locator('[data-testid="trainer-view-nav-coach"]')).toHaveAttribute("aria-current", "page");
    expect(consoleErrors).toEqual([]);
    const finalProvider = await persistedProvider(page);
    expect(JSON.stringify(finalProvider)).not.toContain(credential);
  });
});
