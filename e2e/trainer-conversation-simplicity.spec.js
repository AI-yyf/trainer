const { test, expect } = require('playwright/test');

test('Coach shows the reply and usable next actions without duplicate explanations or management', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=coach&lang=zh-CN&connection=connected&run=concise-coach');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const current = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  const message = { id: 'concise-answer', role: 'assistant', author: 'Trainer', timestamp: '10:00',
    body: '先实现 **边界检查**，然后运行 `pytest`。',
    contextNote: 'HIDDEN_MANAGEMENT_CONTEXT', support: { lines: ['HIDDEN_HISTORY_RESULT'] },
    artifacts: [{ kind: 'next_step', title: '继续练习', recommendedAction: 'task',
      summary: 'HIDDEN_DUPLICATE_SUMMARY', content: 'HIDDEN_MANAGEMENT_TABLE',
      rationale: 'HIDDEN_REASON', metadata: { teachingNote: 'HIDDEN_TEACHING_NOTE' } },
      { kind: 'evaluation', title: 'HIDDEN_HISTORY_EVALUATION', summary: '历史结果' },
      { kind: 'review', title: 'HIDDEN_HISTORY_REVIEW', summary: '复习结果' }],
    parts: [{ type: 'test_result', title: 'HIDDEN_TEST_RESULT', summary: 'HIDDEN_TEST_RESULT',
      passed: true, checks: [] }],
  };
  await page.evaluate(data => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: data }),
    { ...current, conversation: [{ id: 'question', role: 'user', author: 'You', timestamp: '09:59',
      body: '帮我检查这个边界', contextNote: 'HIDDEN_USER_INTENT_AND_MODE',
      support: { lines: ['HIDDEN_USER_MANAGEMENT'] },
      attachments: [{ label: '文件', value: 'boundary.py' }] }, message], sessionHistoryRestored: true });
  await expect(page.getByText('文件：boundary.py', { exact: true })).toBeVisible();
  for (const width of [300, 360, 800]) {
    await page.setViewportSize({ width, height: 760 });
    await expect(page.locator('.message-bubble strong').filter({ hasText: '边界检查' })).toHaveCount(1);
    await expect(page.getByRole('button', { name: '下一步：设为练习', exact: true })).toBeVisible();
    await expect(page.getByText(/HIDDEN_/)).toHaveCount(0);
    await expect(page.locator('.message-bubble__tool-trail, .skill-projection-strip')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
});

test('Learning keeps its current step and action without statistics, history or management', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=plan&lang=zh-CN&connection=connected&run=concise-plan');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const primary = page.locator('[data-plan-primary="true"]');
  await expect(primary).toBeVisible();
  await expect(primary.locator('[data-plan-fact="next"]')).toBeVisible();
  await expect(primary.locator('.coach-plan-view__compact-primary-action button')).toBeVisible();
  await expect(page.locator('.coach-plan-view__governance, .coach-plan-view__summary-chips, .learning-home-overview, .skill-projection-strip, [data-view-context-rail="plan"], [data-view-agent-reply="plan"]')).toHaveCount(0);
  await expect(primary.locator('.coach-plan-view__empty-more')).toHaveCount(0);
  for (const width of [300, 360, 800]) {
    await page.setViewportSize({ width, height: 760 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
});

test('the single Learning action adopts only current step evidence and respects a frozen plan', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=plan&lang=zh-CN&connection=connected&run=current-adoption');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const bootstrap = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  await page.addInitScript(() => {
    window.__TRAINER_E2E_HOST_ACTIONS__ = [];
    window.acquireVsCodeApi = () => ({
      getState: () => ({ activeView: 'plan', composerLanguage: 'zh-CN' }),
      setState: () => undefined,
      postMessage: message => window.__TRAINER_E2E_HOST_ACTIONS__.push(message),
    });
  });
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .some(action => action.type === 'request/bootstrap'))).toBe(true);
  const step = '验证 hash 与字典键的异常边界';
  const runtime = { recovered: true, planId: 'adoption-plan', currentStep: step, frozen: false };
  const evidence = { id: 'current-return', source: 'training_handoff_return', summary: '当前文件检查通过',
    outcome: 'pass', verified: true, adopted: false, confidence: 1, concepts: [], targetPlanStep: step };
  const payload = { ...bootstrap, conversation: [], hasFormalPlan: true, sessionHistoryRestored: true,
    plan: { ...bootstrap.plan, id: 'adoption-plan', frozen: false, currentStep: step,
      stages: [{ id: 'adoption-stage', title: '验证当前边界', status: 'active' }] },
    planRuntimeStatus: runtime,
    memory: { ...bootstrap.memory, workspace: { ...bootstrap.memory.workspace, latestPlanRuntime: runtime },
      evidenceQueue: { pending: [{ ...evidence, id: 'old-return', targetPlanStep: '旧步骤' }, evidence],
        adopted: [], deferred: [], rejected: [], history: [], totalCount: 2 } },
  };
  async function apply() {
    await page.evaluate(data => window.postMessage({ type: 'bootstrap', payload: data }, location.origin), payload);
  }
  await apply();
  const primary = page.locator('[data-plan-primary="true"] .coach-plan-view__compact-primary-action button');
  await expect(primary).toContainText(/接纳|采纳/);
  await primary.click();
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(action => action.type === 'command/execute' && action.payload.commandId === 'trainer.evidence.adopt')))
    .toEqual([{ type: 'command/execute', payload: { commandId: 'trainer.evidence.adopt', payload: { evidenceId: 'current-return' } } }]);
  payload.plan.frozen = true; runtime.frozen = true;
  await apply();
  await expect(primary).toContainText('解冻计划');
  await primary.click();
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(action => action.type === 'plan/freeze')))
    .toEqual([{ type: 'plan/freeze', payload: { frozen: false } }]);
  expect(await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(action => action.type === 'command/execute' && action.payload.commandId === 'trainer.evidence.adopt').length)).toBe(1);
});

test('long stage titles wrap without generation buttons or empty material panels', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=plan&lang=zh-CN&connection=connected&run=stage-layout');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const current = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  const title = '验证嵌套列表修改与元组槽位赋值以及 hash 和字典键异常边界'.repeat(3);
  await page.evaluate(data => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: data }),
    { ...current, plan: { ...current.plan, stages: [{ id: 'long-stage', title, status: 'active' },
      { id: 'later-stage', title: '实现 sum_nested', status: 'queued' }] } });
  await page.locator('[data-plan-stage-disclosure] > summary').click();
  await expect(page.locator('.coach-plan-view__compact-stage')).toHaveCount(2);
  await expect(page.getByText(title, { exact: true })).toBeVisible();
  await expect(page.locator('[data-stage-materials], [data-stage-materials-generate], .stage-material-empty')).toHaveCount(0);
  for (const width of [300, 360, 800]) {
    await page.setViewportSize({ width, height: 760 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    const row = await page.locator('.coach-plan-view__compact-stage').first().boundingBox();
    const text = await page.locator('.coach-plan-view__compact-stage strong').first().boundingBox();
    expect(text.x + text.width).toBeLessThanOrEqual(row.x + row.width + 1);
  }
});
