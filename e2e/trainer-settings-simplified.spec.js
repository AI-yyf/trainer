const { test, expect } = require("playwright/test");

test("connection editing exposes required fields first and keeps optional tools in details", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=settings&lang=en-US&connection=connected&run=simplified-settings");
  await page.getByRole("button", { name: "Edit configuration", exact: true }).click();
  await expect(page.getByLabel("Service root")).toBeVisible();
  await expect(page.getByLabel("API Key", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Connection name (optional)", { exact: true })).toHaveCount(0);
  await expect(page.locator(".settings-endpoint-speed")).toHaveCount(0);
  const details = page.locator(".coach-settings-view__provider-detail .collapse-section__header").first();
  await details.click();
  await expect(page.getByLabel("Connection name (optional)", { exact: true })).toBeVisible();
  await expect(page.locator(".settings-endpoint-speed")).toBeVisible();
  await expect(page.getByLabel("Service root")).toHaveCount(0);
  await details.click();
  await expect(page.getByLabel("Service root")).toBeVisible();
});

test('remote support uses the host window identity and is absent in a local window', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=settings&lang=en-US&connection=connected&run=remote-settings-identity');
  await page.locator('.settings-nav').getByRole('tab', { name: 'Workspace', exact: true }).click();
  const remotePanel = page.locator('[data-settings-subsection="remote-support"]');
  await expect(remotePanel).toHaveCount(0);
  await page.evaluate(() => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'state/patch', payload: {
    workspace: { isRemoteWorkspace: true, remoteName: 'ssh-remote' },
  } }));
  await expect(remotePanel).toBeVisible();
  await expect(remotePanel.getByText('ssh-remote', { exact: true })).toBeVisible();
  await page.evaluate(() => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'state/patch', payload: {
    workspace: { isRemoteWorkspace: false, remoteName: undefined },
  } }));
  await expect(remotePanel).toHaveCount(0);
});

test("settings keyboard navigation cycles only through visible destinations", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=settings&lang=en-US&connection=connected&run=settings-keyboard");
  const tabs = page.locator(".settings-nav").getByRole("tab");
  await expect(tabs).toHaveCount(4);
  await tabs.last().click();
  await tabs.last().press("ArrowRight");
  await expect(tabs.first()).toHaveAttribute("aria-selected", "true");
  await expect(tabs.first()).toBeFocused();
  await tabs.first().press("ArrowLeft");
  await expect(tabs.last()).toHaveAttribute("aria-selected", "true");
});

test("closed folding regions cannot retain keyboard focus in hidden controls", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=settings&lang=en-US&connection=connected&run=settings-fold-focus");
  await page.locator(".settings-nav").getByRole("tab").last().click();
  const section = page.locator('.collapse-section.is-open').first();
  const header = section.locator('.collapse-section__header').first();
  const bodyId = await header.getAttribute('aria-controls');
  await header.click();
  const body = page.locator(`[id="${bodyId}"]`);
  await expect(body).toHaveAttribute('aria-hidden', 'true');
  await expect(body).toHaveAttribute("inert", "");
  const control = body.locator("input,button,select,textarea").first();
  const focused = await control.evaluate((element) => {
    element.focus();
    return document.activeElement === element;
  });
  expect(focused).toBe(false);
});

test("mouse-opened preference menus move from the selected choice with arrow keys", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=settings&lang=en-US&connection=connected&run=preference-arrows");
  await page.locator(".settings-nav").getByRole("tab").last().click();
  const choice = page.locator(".settings-choice").first();
  const trigger = choice.getByRole("button");
  await trigger.click();
  const options = choice.getByRole("option");
  const selected = await options.evaluateAll(elements => elements.findIndex(element => element.getAttribute("aria-selected") === "true"));
  const labels = await options.allTextContents();
  await trigger.press("ArrowDown");
  await expect(options.nth((selected + 1) % labels.length)).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(trigger).toHaveText(labels[(selected + 1) % labels.length]);
  await expect(choice.getByRole("listbox")).toHaveCount(0);
});
