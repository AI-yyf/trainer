const { test, expect } = require('playwright/test');

const previewPath = '/owned-sandbox/roots/root-3dc25b18c4864de0975fbb6d78a296ee/sandboxes/context-1e916fbe790646da96d18c43dcda79b8/sources/inbox/preview-proof.md';
const previewBody = 'ACTUAL_MATCHED_PREVIEW_BODY';

async function restoreSandboxReader(page, mode) {
  await page.setViewportSize({ width: 340, height: 800 });
  await page.goto(`/vscode-preview.html?view=resources&lang=zh-CN&connection=connected&run=resource-facts-${mode}`);
  await expect(page.locator('#root[data-trainer-app-ready=true]')).toBeVisible();
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
    .some(message => message.type === 'request/bootstrap'))).toBe(true);
  await page.evaluate(({ bootstrap, mode, previewPath, previewBody }) => {
    const preview = mode === 'missing' ? undefined : {
      path: mode === 'wrong-path' ? '/owned-sandbox/other.md' : previewPath,
      relativePath: 'preview-proof.md', previewKind: 'markdown', content: previewBody,
    };
    window.postMessage({ type: 'bootstrap', payload: {
      ...bootstrap, conversation: [], sessionHistoryRestored: true,
      resources: mode === 'standalone' ? [] : [{ id: 'preview-resource',
        title: 'preview-proof.md', source: '/original/preview-proof.md', sandboxPath: previewPath,
        kind: 'markdown', status: 'ready', summary: 'RESOURCE_SUMMARY_WITHOUT_PREVIEW' }],
      memory: { ...bootstrap.memory, selectedResourceDetail: undefined, sandboxPreview: preview },
    } }, location.origin);
    window.postMessage({ type: 'ui/restoreView', payload: {
      activeView: 'resources', resourceSurface: 'sandbox', sandboxPath: previewPath,
      previewPath, focusArea: 'resource sandbox',
    } }, location.origin);
  }, { bootstrap, mode, previewPath, previewBody });
  await expect.poll(() => latestFacts(page).then(facts => facts?.activeSurface)).toBe('sandbox');
}

function latestFacts(page) {
  return page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(message => message.type === 'debug/visibleFacts' && message.payload.resources)
    .at(-1)?.payload.resources);
}

for (const mode of ['missing', 'wrong-path', 'embedded', 'standalone']) {
  test(`sandbox restore intent with ${mode} preview never renders resource content`, async ({ page }) => {
    await restoreSandboxReader(page, mode);
    const reader = page.locator('[data-template=ResourceReader]');
    await expect(page.locator('.resources-knowledge__content-preview')).toHaveCount(0);
    await expect(page.locator('[data-template=ResourceReader] iframe')).toHaveCount(0);
    await expect(page.locator('text=' + previewBody)).toHaveCount(0);

    const facts = await latestFacts(page);
    expect(facts.selectedSandboxPath).toBe(previewPath);
    expect(facts.activeSurface).toBe('sandbox'); // Logical restore scope remains supported.
    expect(facts.sandboxPaneVisible).toBe(false);
    expect(facts.previewPaneVisible).toBe(false);
    expect(facts.sandboxPreviewVisible).toBeUndefined();
    expect(facts.sandboxPreviewEmbedded).toBeUndefined();
    expect(facts.sandboxPreviewPath).toBeUndefined();
    // The shipped library has no Reader detail page at all; every mode keeps
    // the logical restore scope without rendering resource content.
    await expect(reader).toHaveCount(0);
    await expect(page.locator('.resources-inline-context')).toHaveCount(0);
    const library = page.locator('.resources-knowledge');
    await expect(library).toBeVisible();
    await expect(library).not.toContainText(/沙箱上下文已恢复|Sandbox context restored|resource sandbox/);
    await expect(library).not.toContainText(previewPath);
    await expect(library.getByRole('searchbox')).toBeVisible();
    if (mode !== 'standalone') {
      await expect(page.getByRole('treeitem', { name: 'preview-proof.md', exact: true })).toBeVisible();
    }
  });
}
