const { expect } = require("playwright/test");

// Follow the same index/detail controls as a learner; do not patch UI state.
async function openSettingsCategory(page, category) {
  const detail = page.locator(`[data-settings-detail="${category}"]`);
  if (await detail.isVisible()) return;
  const anyDetail = page.locator('[data-template=SettingsDetail]:visible');
  if (await anyDetail.count()) await anyDetail.locator('.template-back').first().click();
  const entry = page.locator(`[data-settings-category="${category}"]`);
  await expect(entry).toBeVisible();
  await entry.click();
  await expect(detail).toBeVisible();
}
module.exports = { openSettingsCategory };
