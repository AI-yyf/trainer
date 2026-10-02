const { test, expect } = require('playwright/test');

test('the reading library opens one file directly and removes management panels', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=resources&lang=zh-CN&connection=connected&run=resource-reader');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const bootstrap = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  await page.addInitScript(() => {
    window.__TRAINER_E2E_HOST_ACTIONS__ = [];
    window.acquireVsCodeApi = () => ({
      getState: () => ({ activeView: 'resources', composerLanguage: 'zh-CN' }),
      setState: () => undefined,
      postMessage: message => window.__TRAINER_E2E_HOST_ACTIONS__.push(message),
    });
  });
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .some(action => action.type === 'request/bootstrap'))).toBe(true);
  await page.evaluate(data => window.postMessage({ type: 'bootstrap', payload: data }, location.origin), {
    ...bootstrap, resources: [
      { id: 'reader-note', title: '边界验证.md', kind: 'markdown', source: '/tmp/reader-note.md', status: 'indexed', summary: 'HIDDEN_MANAGEMENT_SUMMARY' },
      { id: 'reader-snapshot', title: '网页快照.md', kind: 'url', source: 'https://example.com', sandboxPath: '/tmp/captured.md', status: 'indexed' },
    ], conversation: [], sessionHistoryRestored: true,
  });
  await expect(page.locator('.resources-reader')).toBeVisible();
  expect(await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(action => action.type === 'command/execute' && action.payload.commandId === 'trainer.resource.refreshTrash'))).toEqual([]);
  await expect(page.locator('.resources-reader__list button')).toHaveCount(2);
  await expect(page.locator('.resources-knowledge__facts, .resources-knowledge__detail, .resources-knowledge__trash, input[type="checkbox"]')).toHaveCount(0);
  await expect(page.getByText('HIDDEN_MANAGEMENT_SUMMARY', { exact: true })).toHaveCount(0);
  const note = page.getByRole('button', { name: '边界验证.md', exact: true });
  await note.focus(); await page.keyboard.press('Enter');
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(action => action.type === 'resource/open'))).toEqual([{ type: 'resource/open', payload: { resourceId: 'reader-note' } }]);
  await expect(page.locator('.resources-reader')).toBeVisible();
  for (const width of [300, 360, 800]) {
    await page.setViewportSize({ width, height: 760 });
    const search = page.locator('.resources-reader__search input');
    const icon = page.locator('.resources-reader__search > svg');
    const fieldBounds = await search.boundingBox();
    const iconBounds = await icon.boundingBox();
    expect(Math.abs(fieldBounds.y + fieldBounds.height / 2 - iconBounds.y - iconBounds.height / 2)).toBeLessThanOrEqual(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
});

test('nested folders stay distinct, support keyboard navigation and open their file directly', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=resources&lang=zh-CN&connection=connected&run=nested-reader');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const bootstrap = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  await page.addInitScript(() => {
    window.__TRAINER_E2E_HOST_ACTIONS__ = [];
    window.acquireVsCodeApi = () => ({ getState: () => ({ activeView: 'resources', composerLanguage: 'zh-CN' }),
      setState: () => undefined, postMessage: message => window.__TRAINER_E2E_HOST_ACTIONS__.push(message) });
  });
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .some(action => action.type === 'request/bootstrap'))).toBe(true);
  await page.evaluate(data => window.postMessage({ type: 'bootstrap', payload: data }, location.origin), {
    ...bootstrap, resources: [
      { id: 'nested-note', title: '边界验证.md', kind: 'markdown', status: 'ready', summary: '',
        source: '/tmp/course/Python/基础/容器/边界验证.md', collectionRoot: '/tmp/course',
        collectionPath: 'Python/基础/容器/边界验证.md' },
      { id: 'other-note', title: '进阶.md', kind: 'markdown', status: 'ready', summary: '',
        source: '/tmp/course/Python/进阶/进阶.md', collectionRoot: '/tmp/course',
        collectionPath: 'Python/进阶/进阶.md' },
      { id: 'loose-note', title: '随手笔记.md', kind: 'markdown', status: 'ready', summary: '', source: '/tmp/loose.md' },
    ], conversation: [], sessionHistoryRestored: true,
  });
  await expect(page.locator('[data-library-folder]')).toHaveCount(1);
  await expect(page.getByRole('button', { name: '随手笔记.md', exact: true })).toBeVisible();
  for (const name of ['Python', '基础', '容器']) {
    const folder = page.locator(`[data-library-folder="${name}"]`);
    await folder.focus(); await page.keyboard.press('Enter');
  }
  await expect(page.locator('.resources-reader__breadcrumb')).toContainText('资料库/Python/基础/容器');
  const file = page.getByRole('button', { name: '边界验证.md', exact: true });
  await expect(file).toBeVisible();
  await file.click();
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(action => action.type === 'resource/open')))
    .toEqual([{ type: 'resource/open', payload: { resourceId: 'nested-note' } }]);
  for (const width of [300, 360, 800]) {
    await page.setViewportSize({ width, height: 760 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
  await page.getByRole('button', { name: '返回', exact: true }).click();
  await expect(page.locator('[data-library-folder="容器"]')).toBeVisible();
  await page.locator('.resources-reader__breadcrumb').getByRole('button', { name: '资料库', exact: true }).click();
  await expect(page.locator('[data-library-folder="Python"]')).toBeVisible();
  await page.getByRole('button', { name: '添加文件夹', exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(action => action.type === 'resource/upload').map(action => action.payload.mode))).toEqual(['folder']);
});
