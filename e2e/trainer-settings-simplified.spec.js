const { openSettingsCategory, openSettingsIndex } = require("./template-navigation");
const { test, expect } = require("playwright/test");

test("connection editing is one complete surface", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=settings&lang=en-US&connection=connected&run=simplified-settings");
  await openSettingsCategory(page, "connection");
  await page.locator('[data-settings-detail="connection"]').getByRole("button", { name: "Edit configuration", exact: true }).click();
  await expect(page.getByLabel("Service root")).toBeVisible();
  await expect(page.getByLabel("API Key", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Connection name (optional)", { exact: true })).toBeVisible();
  await expect(page.locator(".settings-advanced-card")).toBeVisible();
  await expect(page.locator(".settings-endpoint-speed")).toBeVisible();
  await expect(page.getByLabel("Service root")).toBeVisible();
});

test("settings index names the learning folder, not the managed data path", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=settings&lang=zh-CN&scenario=workspace-admission&workspaceAdmission=project-found&connection=connected&run=settings-workspace-summary");
  await openSettingsIndex(page);
  const workspaceRow = page.locator('[data-template=SettingsIndex][data-settings-variant=page] li').nth(2);
  await expect(workspaceRow).toContainText("D:\\TrainerWorkspace");
  await expect(page.locator('[data-template=SettingsIndex][data-settings-variant=page]')).not.toContainText("globalStorage");
  await expect(page.locator('[data-template=SettingsIndex][data-settings-variant=page]')).not.toContainText("sidecar");

  await page.goto("/vscode-preview.html?view=settings&lang=zh-CN&scenario=workspace-admission&workspaceAdmission=root-missing&connection=connected&run=settings-workspace-missing");
  await openSettingsIndex(page);
  const missingRow = page.locator('[data-template=SettingsIndex][data-settings-variant=page] li').nth(2);
  await expect(missingRow).toContainText("未选择学习文件夹");
  await expect(missingRow.getByRole("button", { name: "选择学习文件夹", exact: true })).toBeVisible();
});

test('remote support uses the host window identity and is absent in a local window', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=settings&lang=en-US&connection=connected&run=remote-settings-identity');
  await openSettingsCategory(page, "workspace");
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
  await openSettingsIndex(page);
  const entries = page.locator('[data-template=SettingsIndex][data-settings-variant=page] button');
  await expect(entries).toHaveCount(4);
  await entries.first().focus();
  await page.keyboard.press("Tab");
  await expect(entries.nth(1)).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator('[data-settings-detail="teaching"]')).toBeVisible();
  await page.locator('[data-template=SettingsDetail] .template-back').first().click();
  await expect(entries).toHaveCount(4);
  await entries.last().press("Enter");
  await expect(page.locator('[data-settings-detail="preferences"]')).toBeVisible();
});

test("closed folding regions cannot retain keyboard focus in hidden controls", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=settings&lang=en-US&connection=connected&run=settings-fold-focus");
  await openSettingsCategory(page, "preferences");
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
  await openSettingsCategory(page, "preferences");
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
