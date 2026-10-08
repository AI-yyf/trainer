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
  await expect(page.locator('[data-template=ResourceReader]')).toBeVisible();
  await expect.poll(() => latestFacts(page).then(facts => facts?.activeSurface)).toBe('sandbox');
}

function latestFacts(page) {
  return page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(message => message.type === 'debug/visibleFacts' && message.payload.resources)
    .at(-1)?.payload.resources);
}

for (const mode of ['missing', 'wrong-path']) {
  test(`sandbox restore intent with ${mode} preview reports the actual reader only`, async ({ page }) => {
    await restoreSandboxReader(page, mode);
    const reader = page.locator('[data-template=ResourceReader]');
    await expect(reader).not.toContainText(previewBody);
    const facts = await latestFacts(page);
    expect(facts.activeSurface).toBe('sandbox'); // Logical restore scope remains supported.
    expect(facts.detailPaneVisible).toBe(true);
    expect(facts.sandboxPreviewVisible).toBe(false);
    expect(facts.sandboxPreviewEmbedded).toBe(false);
    expect(facts.sandboxPreviewPath).toBeUndefined();
    expect(facts.sandboxPaneVisible).toBe(false);
    expect(facts.previewPaneVisible).toBe(false);
  });
}

for (const mode of ['embedded', 'standalone']) {
  test(`matched ${mode} preview binds reported path to visible reader content`, async ({ page }) => {
    await restoreSandboxReader(page, mode);
    await expect(page.locator('[data-template=ResourceReader]')).toContainText(previewBody);
    const facts = await latestFacts(page);
    expect(facts.activeSurface).toBe('sandbox');
    expect(facts.detailPaneVisible).toBe(true);
    expect(facts.sandboxPreviewVisible).toBe(true);
    expect(facts.sandboxPreviewEmbedded).toBe(true);
    expect(facts.sandboxPreviewPath).toBe(previewPath);
    expect(facts.sandboxPaneVisible).toBe(false);
    expect(facts.previewPaneVisible).toBe(false);
    expect(facts.resourceDetailVisible).toBe(mode === 'embedded');
  });
}
