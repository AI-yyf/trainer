const { expect } = require("playwright/test");

// Follow the same index/detail controls as a learner; do not patch UI state.
async function waitForSettingsSurface(page) {
  await expect(page.locator('[data-template=SettingsIndex]:visible, [data-template=SettingsDetail]:visible').first()).toBeVisible();
}

async function openSettingsIndex(page) {
  await waitForSettingsSurface(page);
  const anyDetail = page.locator('[data-template=SettingsDetail]:visible');
  if (await anyDetail.count()) await anyDetail.locator('.template-back').first().click();
  await expect(page.locator('[data-template=SettingsIndex]')).toBeVisible();
}

async function openSettingsCategory(page, category) {
  await waitForSettingsSurface(page);
  const detail = page.locator(`[data-settings-detail="${category}"]`);
  if (await detail.isVisible()) return;
  await openSettingsIndex(page);
  const entry = page.locator(`[data-settings-category="${category}"]`);
  await expect(entry).toBeVisible();
  await entry.click();
  await expect(detail).toBeVisible();
}
module.exports = { openSettingsCategory, openSettingsIndex };
