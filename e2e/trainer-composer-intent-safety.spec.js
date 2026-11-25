const { test, expect } = require('playwright/test');
const { planOnlyFixture } = require('./learning-fixtures');

async function openConnectedHost(page, admissionStatus) {
  await page.goto('/vscode-preview.html?view=coach&lang=en-US&connection=connected&run=intent-safety');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const source = planOnlyFixture(await page.evaluate(() => window.__TRAINER_BOOTSTRAP__));
  const payload = { ...source, conversation: [], sessionHistoryRestored: true,
    providerConfig: { ...source.providerConfig, lastTestResult: {
      ...source.providerConfig.lastTestResult, ok: true, status: 'connected', checkedAt: new Date().toISOString(),
      workspaceId: source.memory.workspace.workspaceId, profileId: source.providerConfig.profileId,
      providerName: source.providerConfig.name, baseUrl: source.providerConfig.baseUrl,
      model: source.providerConfig.model, protocol: source.providerConfig.protocol,
      toolsReady: true, toolProbeStatus: 'verified', streamingReady: true,
      capabilityEvidence: [{ name: 'tools', declared: true, observed: true, state: 'verified' }],
    } },
    memory: { ...source.memory,
      workspace: { ...source.memory.workspace, ...(admissionStatus ? { trainerWorkspace: { status: admissionStatus } } : {}) },
      sandboxState: { ...source.memory.sandboxState, authority: {
      authorityScope: 'trainer_sandbox', resourceWriteAllowed: true,
      resourceWriteEvidence: { operation: 'write', scope: 'trainer_sandbox', allowed: true },
    } } },
  };
  await page.addInitScript(payload => {
    window.__INTENT_ACTIONS__ = [];
    window.acquireVsCodeApi = () => ({
      getState: () => ({ activeView: 'coach', composerLanguage: 'en-US' }),
      setState() {},
      postMessage(message) {
        window.__INTENT_ACTIONS__.push(message);
        if (message.type === 'request/bootstrap') {
          setTimeout(() => window.postMessage({ type: 'bootstrap', payload }, location.origin), 0);
        }
      },
    });
  }, payload);
  await page.goto('/');
  await expect(page.locator('#coach-composer')).toBeEditable();
}

for (const text of [
  '不要给我生成一道练习，只解释这段代码。',
  '请解释如何修改学习计划。',
  'Explain this example:\n```text\n给我生成一道练习\n```',
]) test(`conversation does not execute an example or refusal: ${text.split('\n')[0]}`, async ({ page }) => {
  await openConnectedHost(page);
  await page.locator('#coach-composer').fill(text);
  await page.locator('.composer__send').click();
  await expect.poll(() => page.evaluate(() => window.__INTENT_ACTIONS__
    .filter(message => message.type.startsWith('session/send')).length)).toBe(1);
  const actions = await page.evaluate(() => window.__INTENT_ACTIONS__);
  const sent = actions.find(message => message.type.startsWith('session/send'));
  expect(sent.payload).toMatchObject({ text, formalPlanMutation: false });
  expect(actions.some(message => message.payload?.commandId === 'trainer.training.generateCard')).toBe(false);
  await expect(page.locator('[data-unified-action-preview]')).toHaveCount(0);
});

for (const status of ['root-missing', 'project-found']) test(`first conversation works before ${status} admission`, async ({ page }) => {
  await openConnectedHost(page, status);
  const text = 'Explain the current function before we start a learning plan.';
  await page.locator('#coach-composer').fill(text);
  await page.locator('.composer__send').click();
  await expect.poll(() => page.evaluate(() => window.__INTENT_ACTIONS__
    .filter(message => message.type.startsWith('session/send')).length)).toBe(1);
  const actions = await page.evaluate(() => window.__INTENT_ACTIONS__);
  expect(actions.find(message => message.type.startsWith('session/send')).payload.text).toBe(text);
  expect(actions.some(message => /(?:adopt|choose).*Project/i.test(message.payload?.commandId || ''))).toBe(false);
});

test('a queued plan request can be confirmed after the current reply completes', async ({ page }) => {
  await openConnectedHost(page);
  await page.evaluate(() => window.postMessage({ type: 'stream/start', payload: { messageId: 'busy-turn' } }, location.origin));
  const input = page.locator('#coach-composer');
  await expect(page.locator('.composer__send')).toHaveClass(/is-busy/);
  const request = 'Please save the learning plan we just discussed.';
  await input.fill(request);
  await page.locator('.composer__queue-btn').click();
  await expect(input).toHaveValue('');
  await page.evaluate(() => window.postMessage({ type: 'stream/complete', payload: { messageId: 'busy-turn', tokens: 0 } }, location.origin));
  const preview = page.locator('[data-unified-action-preview="plan"]');
  await expect(preview).toBeVisible();
  expect(await page.evaluate(() => window.__INTENT_ACTIONS__.some(message => message.type.startsWith('session/send')))).toBe(false);
  await preview.getByRole('button', { name: 'Confirm and run', exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__INTENT_ACTIONS__
    .filter(message => message.type.startsWith('session/send')).length)).toBe(1);
  const sent = await page.evaluate(() => window.__INTENT_ACTIONS__.find(message => message.type.startsWith('session/send')));
  expect(sent.payload).toMatchObject({ text: request, intent: 'plan', formalPlanMutation: true });
});

test('a queued follow-up sends its own text and keeps a newer unsent draft', async ({ page }) => {
  await openConnectedHost(page);
  await page.evaluate(() => window.postMessage({ type: 'stream/start', payload: { messageId: 'busy-turn' } }, location.origin));
  const input = page.locator('#coach-composer');
  const request = 'Explain why retries need an idempotency key.';
  await input.fill(request);
  await page.locator('.composer__queue-btn').click();
  await input.fill('Keep this newer question unsent.');
  await page.evaluate(() => window.postMessage({ type: 'stream/complete', payload: { messageId: 'busy-turn', tokens: 0 } }, location.origin));
  await expect.poll(() => page.evaluate(() => window.__INTENT_ACTIONS__
    .filter(message => message.type.startsWith('session/send')).length)).toBe(1);
  const sent = await page.evaluate(() => window.__INTENT_ACTIONS__.find(message => message.type.startsWith('session/send')));
  expect(sent.payload).toMatchObject({ text: request, intent: 'coach', formalPlanMutation: false });
  await expect(input).toHaveValue('Keep this newer question unsent.');
});

test('the queue waits for a plan decision before sending the next question', async ({ page }) => {
  await openConnectedHost(page);
  await page.evaluate(() => window.postMessage({ type: 'stream/start', payload: { messageId: 'busy-turn' } }, location.origin));
  const input = page.locator('#coach-composer');
  for (const text of ['Please save the learning plan we just discussed.', 'Explain idempotency.']) {
    await input.fill(text);
    await page.locator('.composer__queue-btn').click();
  }
  await page.evaluate(() => window.postMessage({ type: 'stream/complete', payload: { messageId: 'busy-turn', tokens: 0 } }, location.origin));
  const preview = page.locator('[data-unified-action-preview="plan"]');
  await expect(preview).toBeVisible();
  expect(await page.evaluate(() => window.__INTENT_ACTIONS__.some(message => message.type.startsWith('session/send')))).toBe(false);
  await preview.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__INTENT_ACTIONS__
    .filter(message => message.type.startsWith('session/send')).map(message => message.payload.text))).toEqual(['Explain idempotency.']);
});
