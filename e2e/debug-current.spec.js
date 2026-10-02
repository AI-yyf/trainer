const { test, expect } = require("playwright/test");

// Diagnostic regressions use the same visible controls as learners.
test("compact blocked Plan keeps its next action reachable without management panels", async ({ page }) => {
  const actions = [];
  page.on("console", message => {
    if (message.type() === "debug" && message.text().includes("[trainer:browser-preview]")) {
      const payload = message.args()[1];
      if (payload) void payload.jsonValue().then(value => actions.push(value));
    }
  });
  await page.goto("/vscode-preview.html?view=plan&lang=en-US&scenario=plan-blocked&connection=connected");
  const primary = page.locator('[data-plan-primary="true"] .coach-plan-view__compact-primary-action button');
  await expect(primary).toBeVisible();
  await primary.click();
  await expect(page.locator('.composer-shell textarea')).toBeFocused();
  await expect(page.locator('details[data-plan-governance-disclosure]')).toHaveCount(0);
});

test("Provider configuration has editable service, key and model fields", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=settings&lang=en-US&connection=connected&run=provider-edit-controls");
  await page.getByRole("button", { name: "Edit configuration", exact: true }).click();
  const fields = page.locator("form.settings-sheet__minor-body");
  await expect(fields).toBeVisible();
  const service = fields.getByLabel("Service root");
  await service.fill("https://provider.invalid/v1");
  await expect(service).toHaveValue("https://provider.invalid/v1");
  await expect(fields.getByLabel("API Key", { exact: true })).toBeVisible();
  const model = fields.getByRole("textbox", { name: /^Model\b/ });
  await model.fill("test-model");
  await expect(model).toHaveValue("test-model");
  await expect(page.locator('[data-settings-nav="connection"]')).toHaveAttribute("aria-selected", "true");
});
