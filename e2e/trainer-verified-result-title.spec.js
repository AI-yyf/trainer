const { test, expect } = require('playwright/test');
const { planOnlyFixture } = require('./learning-fixtures');

for (const [language, title] of [['zh-CN', '确认这次验证结果'], ['en-US', 'Confirm this verification result']]) {
  test(`verified training return uses a clear ${language} primary title and keeps raw evidence in disclosure`, async ({ page }) => {
    await page.goto(`/vscode-preview.html?view=plan&lang=${language}&connection=connected&run=verified-result-title-${language}`);
    await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
    const source = planOnlyFixture(await page.evaluate(() => window.__TRAINER_BOOTSTRAP__));
    const rawSummary = 'Execution stdout /tmp/fixture-check.py pass (exit 0)';
    const payload = { ...source, sessionHistoryRestored: true,
      plan: null,
      planRuntimeStatus: { recovered: true, currentStep: '', reviewPoints: [] },
      memory: { ...source.memory, workspace: { ...source.memory.workspace,
        latestPlanRuntime: { planId: source.plan.id, workspaceId: source.memory.workspace.workspaceId,
          currentStep: '', resumeState: 'in_progress' } },
        evidenceQueue: { pending: [{ id: 'verified-result-exact', workspaceId: source.memory.workspace.workspaceId,
          summary: rawSummary, source: 'training_handoff_return', sourceCardId: 'same-verified-card',
          outcome: 'pass', verified: true, verificationSource: 'test_runner', concepts: [] }],
          adopted: [], rejected: [], deferred: [], totalCount: 1 } } };
    await page.addInitScript(({ payload, language }) => {
      window.__VERIFIED_RESULT_ACTIONS__ = [];
      window.acquireVsCodeApi = () => ({
        getState: () => ({ activeView: 'plan', composerLanguage: language }), setState() {},
        postMessage(message) {
          window.__VERIFIED_RESULT_ACTIONS__.push(message);
          if (message.type === 'request/bootstrap') setTimeout(() => window.postMessage({ type: 'bootstrap',
            sync: { generation: 1, revision: 1, baseRevision: 0, messageId: 'verified-result-bootstrap',
              workspaceId: payload.memory.workspace.workspaceId, sessionId: 'verified-result-session' }, payload }, location.origin), 0);
        },
      });
    }, { payload, language });
    await page.goto('/');
    const primary = page.locator('[data-surface=plan] [data-template=NextAction]');
    await expect(primary.locator('h3')).toHaveText(title);
    await expect(primary.getByRole('button')).toHaveAttribute('data-action-intent', 'adopt_evidence');
    const evidence = page.locator('[data-learning-section=evidence]');
    await expect(evidence.getByText(rawSummary, { exact: true })).not.toBeVisible();
    await evidence.locator(':scope > summary').click();
    await expect(evidence.getByText(rawSummary, { exact: true })).toBeVisible();
    await primary.getByRole('button').click();
    const sent = await page.evaluate(() => window.__VERIFIED_RESULT_ACTIONS__
      .filter(message => message.payload?.commandId === 'trainer.evidence.adopt'));
    expect(sent).toHaveLength(1);
    expect(sent[0].payload.payload.evidenceId).toBe('verified-result-exact');
    expect(sent[0].operation.sessionId).toBe('verified-result-session');
    const record = payload.memory.evidenceQueue.pending[0];
    await page.evaluate(({ payload, record }) => window.postMessage({ type: 'bootstrap',
      sync: { generation: 1, revision: 2, baseRevision: 0, messageId: 'verified-result-adopted',
        workspaceId: payload.memory.workspace.workspaceId, sessionId: 'verified-result-session' },
      payload: { ...payload, memory: { ...payload.memory, evidenceQueue: {
        pending: [], adopted: [{ ...record, adopted: true }], deferred: [], rejected: [], totalCount: 1,
      } } } }, location.origin), { payload, record });
    await expect(primary.locator('h3')).not.toHaveText(title);
    await expect(evidence).toContainText(rawSummary);
    await expect(evidence.locator('[data-plan-evidence-id]')).toHaveAttribute('data-plan-evidence-id', 'verified-result-exact');
  });
}
