const { test, expect } = require('playwright/test');

/**
 * The library's one capture entry: paste an address, choose the target
 * knowledge base, then add. The source is recognized from the address (and
 * from the picked file), never chosen from a list — the dialog says what it
 * recognized and the sidecar captures exactly that.
 */
test('the capture entry recognizes the source and offers a target knowledge base', async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 900 });
  await page.goto('/vscode-preview.html?view=resources&scenario=ready&lang=zh-CN&connection=connected');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();

  await page.getByRole('button', { name: '添加资料', exact: true }).click();
  const menu = page.getByRole('menu', { name: '添加资料', exact: true });
  await expect(menu).toBeVisible();
  await menu.locator('[data-capture-entry="true"]').click();

  const dialog = page.locator('[role="dialog"][aria-label="添加到资料库"]');
  await expect(dialog).toBeVisible();

  // One address field and one file field: no source picker to choose from.
  await expect(dialog.locator('#resource-capture-url')).toBeVisible();
  await expect(dialog.locator('[data-capture-file="true"]')).toBeVisible();
  await expect(dialog.locator('[data-capture-source]')).toHaveCount(0);
  await expect(dialog.locator('input[type="file"]')).toHaveCount(1);

  // The address decides what is captured, and the dialog says so.
  const hint = dialog.locator('.resource-capture__hint').first();
  await dialog.locator('#resource-capture-url').fill('https://gitlab.com/group/subgroup/project');
  await expect(hint).toContainText('GitLab');
  await dialog.locator('#resource-capture-url').fill('https://example.org/paper.pdf');
  await expect(hint).toContainText('PDF');
  await dialog.locator('#resource-capture-url').fill('https://example.org/article');
  await expect(hint).toContainText('网页');

  // The target is a knowledge base, not a free-text path.
  await expect(dialog.getByRole('radiogroup', { name: '目标知识库' })).toBeVisible();
  await expect(dialog.getByText('资料库根目录', { exact: true })).toBeVisible();
  await expect(dialog.locator('input[name="resource-capture-target"]').first()).toBeChecked();

  // One primary action.
  await expect(dialog.locator('[data-capture-submit="true"]')).toBeVisible();
  await expect(dialog.locator('button.button--accent')).toHaveCount(1);
});
