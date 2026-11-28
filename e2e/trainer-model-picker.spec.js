const { test, expect } = require("playwright/test");

/**
 * The composer context ring opens one calm model list: provider identity,
 * search, flat model rows (vision badge + active check), multiple saved
 * providers as their own groups, and a single thinking-intensity slider.
 *
 * These cases drive the real preview harness; they prove the layout and the
 * cross-provider selection path, not the host credential storage.
 */

const MODELS = [
  "minimax-m3.1-flash",
  "kimi-k3.1-pro",
  "glm-5.3-flash",
  "glm-5.3",
  "kimi-k3",
  "deepseek-v4.1-flash",
  "mimo-v2.6-pro",
];

async function openModelPicker(page, lang = "zh-CN") {
  await page.goto(
    `/vscode-preview.html?view=coach&lang=${lang}&connection=connected&run=model-picker`,
  );
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate((models) => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const capabilities = {
      chat: true,
      responses: true,
      vision: true,
      embeddings: false,
      tools: true,
      jsonSchema: false,
      structuredOutput: true,
      streaming: true,
      thinking: true,
    };
    const modelCapabilities = Object.fromEntries(models.map((model) => [model, capabilities]));
    const providerProfiles = [
      {
        id: "opencode-go-chat",
        label: "OpenCode Go (Chat)",
        protocol: "openai_chat_completions_compatible",
        mode: "direct",
        credentialMode: "ui_proxy",
        baseUrl: "https://opencode.example/v1",
        model: "deepseek-v4.1-flash",
        availableModels: models,
      },
      {
        id: "kimi-core",
        label: "Kimi Core",
        protocol: "openai_chat_completions_compatible",
        mode: "direct",
        credentialMode: "ui_proxy",
        baseUrl: "https://api.moonshot.cn/v1",
        model: "kimi-k3",
        availableModels: ["kimi-k3", "kimi-k2.7-code"],
        capabilities,
        modelCapabilities,
        modelThinkingConfig: { "kimi-k3": { mode: "enabled", reasoningEffort: "low" } },
      },
      {
        id: "glm-workspace",
        label: "GLM Workspace",
        protocol: "openai_chat_completions_compatible",
        mode: "direct",
        credentialMode: "ui_proxy",
        baseUrl: "https://glm.example/v1",
        model: "glm-5.3",
        availableModels: ["glm-5.3", "glm-5.3-flash"],
        capabilities,
      },
    ];
    const providerConfig = {
      ...current.providerConfig,
      configured: true,
      name: "OpenCode Go (Chat)",
      profileId: "opencode-go-chat",
      profileLabel: "OpenCode Go (Chat)",
      profileCount: providerProfiles.length,
      model: "deepseek-v4.1-flash",
      resolvedModel: "deepseek-v4.1-flash",
      availableModels: models,
      capabilities,
      modelCapabilities,
      providerProfiles,
      thinkingConfig: { mode: "enabled", reasoningEffort: "high" },
      modelThinkingConfig: {
        "deepseek-v4.1-flash": { mode: "enabled", reasoningEffort: "high" },
        "kimi-k3": { mode: "enabled", reasoningEffort: "low" },
      },
      lastTestResult: {
        ...(current.providerConfig.lastTestResult || {}),
        ok: true,
        status: "ok",
        detail: "ok",
        providerName: "OpenCode Go (Chat)",
        baseUrl: "https://opencode.example/v1",
        model: "deepseek-v4.1-flash",
        protocol: "openai_chat_completions_compatible",
        profileId: "opencode-go-chat",
        streamingReady: true,
        toolsReady: true,
        thinkingReady: true,
        visionReady: true,
        capabilityEvidence: [
          { name: "thinking", declared: true, observed: true, state: "verified" },
          { name: "vision", declared: true, observed: true, state: "verified" },
          { name: "streaming", declared: true, observed: true, state: "verified" },
        ],
      },
    };
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
      type: "bootstrap",
      payload: { ...current, providerConfig },
    });
  }, MODELS);
  await page.waitForTimeout(400);
  await page
    .getByRole("button", { name: /切换模型|Switch model|选择模型|Manage models/ })
    .first()
    .click();
  await expect(page.locator(".composer-model-menu")).toBeVisible();
}

test("the context ring opens the flat provider/model list", async ({ page }) => {
  await openModelPicker(page);

  await expect(page.locator(".composer-model-menu__provider-name")).toHaveText(
    "OpenCode Go (Chat)",
  );
  await expect(page.locator(".composer-model-menu__provider-pill").first()).toHaveText("API");
  // Search is part of the first screen, not a disclosure after a limit.
  await expect(page.locator(".composer-model-menu__search input")).toBeVisible();

  // Current selection keeps its check; every verified vision model gets a badge.
  const active = page.locator(".composer-provider-list__item.is-active").first();
  await expect(active).toContainText("deepseek-v4.1-flash");
  await expect(page.locator(".composer-model-menu__vision").first()).toBeVisible();
  // Thinking intensity is one provider-level slider at the bottom of the menu
  // (f4713414 replaced the per-model thinking badges with it).
  await expect(page.locator(".composer-model-menu__thinking-range").first()).toBeVisible();

  // Other saved providers are groups, not a hidden "saved connections" fold.
  await expect(page.locator(".composer-model-menu__provider-group")).toHaveCount(2);
  await expect(
    page.locator(".composer-model-menu__group-name").filter({ hasText: "Kimi Core" }),
  ).toBeVisible();
  const kimiGroup = page
    .locator(".composer-model-menu__provider-group")
    .filter({ hasText: "Kimi Core" });
  await expect(kimiGroup.locator(".composer-model-menu__vision").first()).toBeVisible();
  await expect(
    page.locator(".composer-model-menu__group-name").filter({ hasText: "GLM Workspace" }),
  ).toBeVisible();

  // Thinking intensity is one slider with the current effort on the right.
  await expect(page.locator(".composer-model-menu__thinking")).toBeVisible();
  await expect(page.locator(".composer-model-menu__thinking-value")).toHaveText("最高");
  await expect(page.locator(".composer-model-menu__thinking-range")).toHaveValue("2");
});

test("search filters every provider group from one field", async ({ page }) => {
  await openModelPicker(page);
  const search = page.locator(".composer-model-menu__search input");
  await search.fill("glm");
  // glm-5.3 / glm-5.3-flash exist in the active provider and the GLM group.
  await expect(
    page.locator(".composer-provider-list__item").filter({ hasText: "glm-5.3" }),
  ).toHaveCount(4);
  // The active model stays pinned even when the query does not match it.
  await expect(
    page.locator(".composer-provider-list__item").filter({ hasText: "deepseek" }),
  ).toHaveCount(1);
  await expect(
    page.locator(".composer-provider-list__item").filter({ hasText: "deepseek" }).first(),
  ).toHaveClass(/is-active/);
});

test("the model picker fits a narrow sidebar without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 340, height: 760 });
  await openModelPicker(page);
  const panel = page.locator(".composer-model-menu");
  const box = await panel.boundingBox();
  expect(box.width).toBeLessThanOrEqual(340);
  const overflow = await panel.evaluate((element) => element.scrollWidth - element.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await expect(page.locator(".composer-model-menu__thinking-range")).toBeVisible();
});

test("the model picker keeps its provider identity at 200% zoom width", async ({ page }) => {
  await page.setViewportSize({ width: 170, height: 700 });
  await openModelPicker(page);
  const panel = page.locator(".composer-model-menu");
  const box = await panel.boundingBox();
  expect(box.width).toBeLessThanOrEqual(170);
  expect(await panel.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
  await expect(page.locator(".composer-model-menu__provider-name")).toBeVisible();
  await expect(page.locator(".composer-model-menu__provider-name")).not.toHaveText("");
  await expect(page.locator(".composer-model-menu__thinking-range")).toBeVisible();
});

test("selecting a model in another provider switches the provider too", async ({ page }) => {
  await openModelPicker(page);
  await page
    .locator(".composer-model-menu__provider-group")
    .filter({ hasText: "Kimi Core" })
    .locator(".composer-provider-list__item")
    .filter({ hasText: "kimi-k2.7-code" })
    .click();
  await expect(
    page.getByRole("button", { name: /kimi-k2\.7-code/ }).first(),
  ).toHaveAttribute("aria-label", /Kimi Core/);

  await page
    .getByRole("button", { name: /切换模型|Switch model|选择模型|Manage models/ })
    .first()
    .click();
  await expect(page.locator(".composer-model-menu__provider-name")).toHaveText("Kimi Core");
  await expect(page.locator(".composer-provider-list__item.is-active").first()).toContainText(
    "kimi-k2.7-code",
  );
});
