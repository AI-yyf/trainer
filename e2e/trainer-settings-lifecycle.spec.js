/**
 * Browser-preview coverage for Settings scenarios 32 and 33 in the 50-case matrix.
 *
 * Fixture preview verifies saved connection metadata. Live preview routes only the
 * sidecar responses so the failed test and corrected retry stay deterministic.
 */

const { randomUUID } = require("node:crypto");
const { test, expect } = require("playwright/test");

const PREVIEW_PATH = "/vscode-preview.html";

function buildPreviewUrl({ live = false } = {}) {
  const query = new URLSearchParams({
    view: "settings",
    lang: "en-US",
    connection: "connected",
    run: "settings-lifecycle",
  });
  if (live) {
    query.set("live", "1");
  }
  return `${PREVIEW_PATH}?${query.toString()}`;
}

function jsonResponse(body) {
  return {
    contentType: "application/json",
    headers: {
      "access-control-allow-origin": "*",
    },
    body: JSON.stringify(body),
  };
}

function collectConsoleErrors(page) {
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  return errors;
}

async function openProviderDetails(page) {
  const detail = page.locator(".coach-settings-view__provider-detail");
  await expect(detail).toBeVisible();
  if (!(await detail.evaluate((element) => element.open))) {
    await detail.locator(":scope > summary").click();
  }
  const connectionFields = providerConnectionFields(detail);
  if (!(await connectionFields.evaluate((element) => element.open))) {
    await connectionFields.locator(":scope > summary").click();
  }
  await expect(connectionFields.getByLabel("Connection name (optional)", { exact: true })).toBeVisible();
  return detail;
}

async function openProviderProfiles(page) {
  const profiles = page.locator(".settings-sheet__provider-profiles");
  await expect(profiles).toBeVisible();
  if (!(await profiles.evaluate((element) => element.open))) {
    await profiles.locator(":scope > summary").click();
  }
  return profiles;
}

function providerConnectionFields(detail) {
  return detail.locator("details.settings-sheet__minor-panel").filter({
    hasText: "Connection fields and key",
  });
}

function providerModelPicker(detail) {
  return providerConnectionFields(detail).locator("details.settings-model-picker");
}

function providerTestButton(page) {
  return page.getByRole("button", { name: "Test Connection", exact: true }).first();
}

async function expectPreviewHarness(page) {
  const storageKey = await page.evaluate(() => window.__TRAINER_PREVIEW_STORAGE_KEY__);
  const expectedStorageKey = `trainer:webview:preview:${new URL(page.url()).search || "default"}`;
  expect(storageKey, "The browser preview entry must be built before this test runs.").toBe(
    expectedStorageKey,
  );
}

async function setProviderModel(detail, model) {
  const picker = providerModelPicker(detail);
  await expect(picker).toBeVisible();
  if (!(await picker.evaluate((element) => element.open))) {
    await picker.locator(":scope > summary").click();
  }
  const summary = picker.locator(":scope > summary");
  if (await summary.textContent().then((text) => text?.includes(model) ?? false)) {
    await expect(summary).toContainText(model);
    return;
  }

  const select = picker.getByRole("combobox", { name: "Model", exact: true });
  if (await select.isVisible()) {
    const hasMatchingOption = await select.locator("option").evaluateAll(
      (options, expectedModel) =>
        options.some((option) => option.textContent?.trim() === expectedModel || option.value === expectedModel),
      model,
    );
    if (hasMatchingOption) {
      await select.selectOption({ label: model });
      await expect(picker.locator(":scope > summary")).toContainText(model);
      return;
    }
  }

  let search = picker.getByRole("searchbox", { name: "Filter models", exact: true });
  if (!(await search.isVisible())) {
    const manualEntryButton = picker.getByRole("button", { name: "Enter a full model name", exact: true });
    await expect(manualEntryButton).toBeVisible();
    await manualEntryButton.click();
    search = picker.getByRole("searchbox", { name: "Filter models", exact: true });
  }

  await search.fill(model);
  await picker.getByRole("button", { name: `Use ${model}`, exact: true }).click();
  await expect(picker.locator(":scope > summary")).toContainText(model);
}

async function openProviderModelLimits(detail) {
  const catalog = detail.locator("details.settings-sheet__provider-catalog");
  if ((await catalog.count()) > 0) {
    if (!(await catalog.evaluate((element) => element.open))) {
      await catalog.locator(":scope > summary").click();
    }
  }
  const limits = detail.locator("details.settings-sheet__model-limits-panel");
  if (!(await limits.evaluate((element) => element.open))) {
    await limits.locator(":scope > summary").click();
  }
  await expect(limits.locator(":scope > summary")).toBeVisible();
  return limits;
}

function providerContextWindowInput(limits) {
  return limits.locator('input[type="number"]').nth(0);
}

function providerMaxOutputInput(limits) {
  return limits.locator('input[type="number"]').nth(1);
}

async function readPreviewPersistence(page, credential) {
  return page.evaluate((ephemeralCredential) => {
    const storageKey = `trainer:webview:preview:${window.location.search || "default"}`;
    const serialized = window.localStorage.getItem(storageKey) ?? "";
    const parsed = serialized ? JSON.parse(serialized) : {};
    const provider = parsed.previewProviderConfig ?? {};
    return {
      hasStorageKey: Boolean(serialized),
      hasEphemeralCredential: serialized.includes(ephemeralCredential),
      provider: {
        name: provider.name,
        baseUrl: provider.baseUrl,
        model: provider.model,
        protocol: provider.protocol,
        contextWindowTokens: provider.contextWindowTokens,
        maxOutputTokens: provider.maxOutputTokens,
        lastTestOk: provider.lastTestResult?.ok,
        profileNames: Array.isArray(provider.providerProfiles)
          ? provider.providerProfiles.map((profile) => profile?.name)
          : [],
      },
    };
  }, credential);
}

test.describe("Trainer Settings provider lifecycle", () => {
  test.setTimeout(60_000);

  test("32/33: saves reusable metadata, shows a failed test, then clears it after a corrected retry", async ({
    page,
  }) => {
    const consoleErrors = collectConsoleErrors(page);
    const ephemeralCredential = `preview-run-${randomUUID()}`;
    const providerName = "Lifecycle preview provider";
    const providerBaseUrl = "https://provider.invalid/v1";
    const rejectedModel = "lifecycle-rejected-model";
    const correctedModel = "lifecycle-corrected-model";
    const failedDetail = "The selected model is unavailable in this test transport.";
    const providerTestPayloads = [];

    await page.addInitScript(() => {
      const initializationKey = "trainer-settings-lifecycle-storage-cleared";
      if (window.sessionStorage.getItem(initializationKey)) {
        return;
      }
      window.localStorage.clear();
      window.sessionStorage.setItem(initializationKey, "true");
    });
    await page.route("**/health", async (route) => {
      await route.fulfill(jsonResponse({ status: "ok" }));
    });
    await page.route("**/session/start", async (route) => {
      await route.fulfill(
        jsonResponse({
          session_id: "settings-lifecycle-preview-session",
        }),
      );
    });
    await page.route("**/memory/settings", async (route) => {
      await route.fulfill(jsonResponse({}));
    });
    await page.route("**/memory/summary**", async (route) => {
      await route.fulfill(jsonResponse({}));
    });
    await page.route("**/provider/test", async (route) => {
      const payload = JSON.parse(route.request().postData() || "{}");
      providerTestPayloads.push(payload);
      const failed = providerTestPayloads.length === 1;
      await route.fulfill(
        jsonResponse(
          failed
            ? {
                ok: false,
                status: "model_not_found",
                detail: failedDetail,
                error_category: "model_not_found",
                retryable: true,
                status_code: 404,
              }
            : {
                ok: true,
                status: "connected",
                diagnostics: ["Mock transport accepted the corrected model."],
                capability_evidence: [
                  { name: "tools", declared: true, observed: true, state: "verified" },
                  { name: "streaming", declared: true, observed: true, state: "verified" },
                ],
                tools_ready: true,
                streaming_ready: true,
              },
        ),
      );
    });

    await page.goto(buildPreviewUrl());
    await page.waitForLoadState("networkidle");
    await expectPreviewHarness(page);

    const collapsedProviderDetail = page.locator(".coach-settings-view__provider-detail");
    await expect(collapsedProviderDetail).toBeVisible();
    expect(await collapsedProviderDetail.evaluate((element) => element.open)).toBe(false);

    const detail = await openProviderDetails(page);
    await providerConnectionFields(detail)
      .getByLabel("Connection name (optional)", { exact: true })
      .fill(providerName);
    await providerConnectionFields(detail).getByLabel("Service root").fill(providerBaseUrl);
    await setProviderModel(detail, rejectedModel);
    const modelLimits = await openProviderModelLimits(detail);
    await providerContextWindowInput(modelLimits).fill("24000");
    await providerMaxOutputInput(modelLimits).fill("2048");
    await providerConnectionFields(detail).getByLabel("API Key", { exact: true }).fill(ephemeralCredential);

    const profiles = await openProviderProfiles(page);
    await profiles.getByRole("button", { name: "Save as connection", exact: true }).click();
    await expect(page.locator(".notice.notice--success")).toContainText("Saved");
    await expect(
      profiles.locator(".settings-provider-profile").filter({ hasText: providerName }),
    ).toBeVisible();

    const savedPersistence = await readPreviewPersistence(page, ephemeralCredential);
    expect(savedPersistence).toMatchObject({
      hasStorageKey: true,
      hasEphemeralCredential: false,
      provider: {
        name: providerName,
        baseUrl: providerBaseUrl,
        model: rejectedModel,
        protocol: "openai_chat_completions_compatible",
        contextWindowTokens: 24000,
        maxOutputTokens: 2048,
      },
    });
    expect(savedPersistence.provider.profileNames).toContain(providerName);

    await page.reload();
    await page.waitForLoadState("networkidle");
    const reloadedDetail = await openProviderDetails(page);
    await expect(
      providerConnectionFields(reloadedDetail).getByLabel("Connection name (optional)", { exact: true }),
    ).toHaveValue(providerName);
    await expect(
      providerConnectionFields(reloadedDetail).getByLabel("Service root"),
    ).toHaveValue(providerBaseUrl);
    await expect(providerModelPicker(reloadedDetail).locator(":scope > summary")).toContainText(rejectedModel);
    const reloadedModelLimits = await openProviderModelLimits(reloadedDetail);
    await expect(providerContextWindowInput(reloadedModelLimits)).toHaveValue("24000");
    await expect(providerMaxOutputInput(reloadedModelLimits)).toHaveValue("2048");
    await expect(providerConnectionFields(reloadedDetail).getByLabel("API Key", { exact: true })).toHaveValue("");

    await page.goto(buildPreviewUrl({ live: true }));
    await page.waitForLoadState("networkidle");
    await expectPreviewHarness(page);
    const liveDetail = await openProviderDetails(page);
    await providerConnectionFields(liveDetail)
      .getByLabel("Connection name (optional)", { exact: true })
      .fill(providerName);
    await providerConnectionFields(liveDetail).getByLabel("Service root").fill(providerBaseUrl);
    await setProviderModel(liveDetail, rejectedModel);
    await providerConnectionFields(liveDetail)
      .getByLabel("API Key", { exact: true })
      .fill(ephemeralCredential);
    const liveProfiles = await openProviderProfiles(page);
    await liveProfiles.getByRole("button", { name: "Save as connection", exact: true }).click();
    await expect(
      liveProfiles.locator(".settings-provider-profile").filter({ hasText: providerName }),
    ).toBeVisible();

    const firstTestButton = providerTestButton(page);
    await expect(firstTestButton).toBeEnabled();
    const firstTestRequest = page.waitForRequest(
      (request) => new URL(request.url()).pathname === "/provider/test",
    );
    await firstTestButton.click();
    await firstTestRequest;
    await expect(page.locator(".notice.notice--error")).toBeVisible();
    await expect(page.locator(".notice.notice--error")).not.toContainText(failedDetail);
    await expect(page.locator('[data-availability-fact="test"]')).toContainText("Failed");
    await expect(page.locator(".settings-availability-strip")).toContainText("Model is unavailable right now");

    const failedPayload = providerTestPayloads[0];
    expect(failedPayload).toMatchObject({
      provider: {
        name: providerName,
        baseUrl: providerBaseUrl,
        model: rejectedModel,
        protocol: "openai_chat_completions_compatible",
      },
      response_language: "en-US",
    });
    expect(typeof failedPayload.api_key).toBe("string");
    expect(failedPayload.api_key.length).toBeGreaterThan(0);
    expect(failedPayload.provider).not.toHaveProperty("apiKey");

    await setProviderModel(liveDetail, correctedModel);
    await page
      .getByRole("button", { name: `Save and use ${correctedModel}`, exact: true })
      .first()
      .click();
    await expect(page.locator(".notice.notice--success")).toBeVisible();
    const secondTestButton = providerTestButton(page);
    await expect(secondTestButton).toBeEnabled();
    const secondTestRequest = page.waitForRequest(
      (request) => new URL(request.url()).pathname === "/provider/test",
    );
    await secondTestButton.click();
    await secondTestRequest;
    await expect(page.locator(".notice.notice--success")).toBeVisible();
    await expect(page.locator('[data-availability-fact="test"]')).toContainText("Passed");
    await expect(page.locator(".settings-availability-strip")).toContainText("Ready");
    await expect(page.locator(".settings-availability-strip")).not.toContainText(
      "Model is unavailable right now",
    );

    const correctedPayload = providerTestPayloads[1];
    expect(correctedPayload).toMatchObject({
      provider: {
        name: providerName,
        baseUrl: providerBaseUrl,
        model: correctedModel,
        protocol: "openai_chat_completions_compatible",
      },
      response_language: "en-US",
    });
    expect(typeof correctedPayload.api_key).toBe("string");
    expect(correctedPayload.api_key.length).toBeGreaterThan(0);
    expect(correctedPayload.provider).not.toHaveProperty("apiKey");

    const correctedPersistence = await readPreviewPersistence(page, ephemeralCredential);
    expect(correctedPersistence).toMatchObject({
      hasEphemeralCredential: false,
      provider: {
        name: providerName,
        baseUrl: providerBaseUrl,
        model: correctedModel,
        lastTestOk: true,
      },
    });
    expect(consoleErrors).toEqual([]);
  });
});
