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

async function isDisclosureOpen(locator) {
  return locator.evaluate((element) =>
    element instanceof HTMLDetailsElement
      ? element.open
      : (element.matches(".collapse-section")
          ? element
          : element.querySelector(".collapse-section")
        )?.classList.contains("is-open") ?? false,
  );
}

async function clickDisclosureToggle(locator) {
  const isDetails = await locator.evaluate(
    (element) => element instanceof HTMLDetailsElement,
  );
  if (isDetails) {
    await locator.locator(":scope > summary").first().click();
    return;
  }
  await locator.locator(".collapse-section__header").first().click();
}

async function openProviderDetails(page) {
  const editButton = page.getByRole("button", { name: "Edit configuration", exact: true });
  if (await editButton.count()) {
    await editButton.click();
  }
  const detail = page.locator(".coach-settings-view__provider-detail");
  await expect(detail).toBeVisible();
  if (!(await isDisclosureOpen(detail))) {
    await clickDisclosureToggle(detail);
  }
  const connectionFields = providerConnectionFields(page);
  await expect(connectionFields.getByLabel("Connection name (optional)", { exact: true })).toBeVisible();
  return page;
}

async function openProviderProfiles(page) {
  const profiles = page.locator(".settings-sheet__provider-profiles");
  await expect(profiles).toBeVisible();
  return profiles;
}

function providerConnectionFields(root) {
  return root.locator('[data-settings-section="connection"]');
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

function providerManualModelInput(root) {
  return root.locator('label.settings-field:has(> span:text-is("Model")) > input');
}

async function setProviderModel(detail, model) {
  const picker = providerModelPicker(detail);
  if ((await picker.count()) === 0) {
    await providerManualModelInput(providerConnectionFields(detail)).fill(model);
    return;
  }
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

    // Connected state shows the compact summary card; the details fold only
    // exists once the edit form is opened.
    const editButton = page.getByRole("button", { name: "Edit configuration", exact: true });
    await expect(editButton).toBeVisible();
    await editButton.click();
    const collapsedProviderDetail = page.locator(".coach-settings-view__provider-detail");
    await expect(collapsedProviderDetail).toBeVisible();
    expect(await isDisclosureOpen(collapsedProviderDetail)).toBe(false);

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
    if ((await providerModelPicker(reloadedDetail).count()) === 0) {
      await expect(
        providerManualModelInput(providerConnectionFields(reloadedDetail)),
      ).toHaveValue(rejectedModel);
    } else {
      await expect(
        providerModelPicker(reloadedDetail).locator(":scope > summary"),
      ).toContainText(rejectedModel);
    }
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
    await expect(page.locator(".settings-availability-strip")).toContainText(
      "No model is available right now",
    );

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

    // The failed-test host update returns the view to the summary card;
    // re-enter edit mode before adjusting the model.
    await openProviderDetails(page);
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
    await expect(page.locator(".settings-availability-strip")).toContainText(
      "use this connection",
    );
    await expect(page.locator(".settings-availability-strip")).not.toContainText(
      "No model is available right now",
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
