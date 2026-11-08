const { test, expect } = require('playwright/test');

const previewPath = '/owned-sandbox/preview-proof.md';
const previewBody = 'ACTUAL_MATCHED_PREVIEW_BODY';

async function restoreSandboxReader(page, mode) {
  await page.goto(`/vscode-preview.html?view=resources&lang=en-US&connection=connected&run=resource-facts-${mode}`);
  await expect(page.locator('#root[data-trainer-app-ready=true]')).toBeVisible();
  const bootstrap = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  await page.addInitScript(() => {
    window.__TRAINER_E2E_HOST_ACTIONS__ = [];
    window.acquireVsCodeApi = () => ({
      getState: () => ({ activeView: 'resources', composerLanguage: 'en-US' }),
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
      previewPath,
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
    expect(facts.activeSurface).toBe('sandbox'); // Logical restore scope remains supported.
    expect(facts.sandboxPaneVisible).toBe(false);
    expect(facts.previewPaneVisible).toBe(false);
    expect(facts.sandboxPreviewVisible).toBeUndefined();
    expect(facts.sandboxPreviewEmbedded).toBeUndefined();
    expect(facts.sandboxPreviewPath).toBeUndefined();
    if (mode === 'standalone') {
      await expect(reader).toHaveCount(0);
      await expect(page.locator('.resources-inline-context')).toBeVisible();
    } else {
      await expect(reader).toBeVisible();
      await expect(reader.getByRole('button', { name: 'Open in VS Code', exact: true })).toBeVisible();
    }
  });
}
