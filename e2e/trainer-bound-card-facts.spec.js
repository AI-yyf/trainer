const { test, expect } = require('playwright/test');

// Authored values mirror the installed native mixed-language fixture. This
// tests presentation/identity boundaries, never model or mastery quality.
const author = {
  title: 'Fixture 练习：workspace_id isolation',
  problemStatement: '练习workspace_id isolation时，为什么一次请求必须保留原来的 workspace_id？',
  suggestedWorkspaceAction: '描述一次请求及其原始 workspace_id。',
  deliverable: '说明原始 workspace_id、收到的 workspace_id，以及不匹配时如何拒绝结果。',
  learnerDeliverables: ['说明原始 workspace_id、收到的 workspace_id，以及不匹配时如何拒绝结果。'],
  validationMethod: '应用结果前比较 `workspace_id`；不匹配的结果必须保持拒绝。',
  verificationSteps: ['应用结果前比较 `workspace_id`；不匹配的结果必须保持拒绝。'],
};

async function seed(page, language, recovered, mode = 'matching') {
  await page.goto(`/vscode-preview.html?view=training&lang=${language}&connection=connected&run=bound-card-${language}-${recovered}-${mode}`);
  await expect(page.locator('#root[data-trainer-app-ready=true]')).toBeVisible();
  await page.evaluate(({ author, recovered, mode }) => {
    const current = /** @type {import('../extension/webview/src/lib/types').BootstrapData} */ (window.__TRAINER_BOOTSTRAP__);
    const workspaceId = 'workspace-authored-card';
    const card = { ...author, cardId: mode === 'foreign' ? 'other-card' : 'author-card',
      type: 'practice', status: 'active', learningPhase: 'try', focusArea: 'workspace_id isolation',
      answerMode: 'text', targetSkill: 'workspace boundary' };
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: {
      ...current, sessionHistoryRestored: true, plan: null,
      task: { ...current.task, title: 'OLD_FORMAL_TASK_TITLE' },
      planRuntimeStatus: { recovered, currentStep: '', reviewPoints: [] },
      memory: { ...current.memory, currentFocus: 'OLD_AMBIENT_FOCUS', workspace: {
        ...current.memory.workspace, workspaceId,
        liveTrainingSelection: mode === 'stale' ? undefined : { workspaceId, cardId: 'author-card', selectedAt: '2026-10-09T00:00:00Z' },
        latestPlanRuntime: undefined, latestTrainingHandoff: undefined, latestTrainingNextHop: undefined,
      } },
      workspaceTrainingState: { workspaceId, selectedCardId: mode === 'missing' ? undefined : 'author-card',
        selectedCardType: 'practice', selectedCardTitle: mode === 'matching' ? card.title : 'UNBOUND_TITLE', selectedCardStatus: 'active',
        trainingCardCandidates: mode === 'missing' ? [] : [card],
        activeTrainingCardRouting: mode === 'missing' ? undefined : { selectedCardId: card.cardId, selectedCard: card },
      },
    } });
  }, { author, recovered, mode });
}

for (const language of ['zh-CN', 'en-US']) {
  for (const recovered of [true, false]) {
    test(`bound authored practice facts survive UI locale ${language}, recovered=${recovered}`, async ({ page }) => {
      await page.setViewportSize({ width: language === 'zh-CN' ? 460 : 340, height: 820 });
      await seed(page, language, recovered);
      const card = page.locator('[data-training-card-id]');
      await expect(card).toHaveAttribute('data-training-card-id', 'author-card');
      const details = page.locator('[data-training-card-details=true]');
      if (await details.count()) await details.locator(':scope > summary').click();
      await expect(card.locator('.template-activity-header')).toContainText(author.title);
      await expect(details.locator('[data-training-card-fact=focus]')).toHaveText('workspace_id isolation');
      await expect(details).toContainText(author.problemStatement);
      await expect(details.locator('[data-training-card-fact=deliverable]')).toHaveText(author.deliverable);
      await expect(details.locator('[data-training-card-fact=verify]')).toContainText(author.validationMethod.replace(/`/g, ''));
      await expect(card.locator('[data-template=NextAction]')).toContainText(author.deliverable);
      await expect(card).not.toContainText('OLD_FORMAL_TASK_TITLE');
      const screenshot = test.info().outputPath('actual-mixed-author-card.png');
      await page.screenshot({ path: screenshot, animations: 'disabled' });
      await test.info().attach('actual-mixed-author-card', { path: screenshot, contentType: 'image/png' });
      await page.getByRole('button', { name: language === 'zh-CN' ? '学习' : 'Learning', exact: true }).click();
      const primary = page.locator('[data-template=NextAction]').filter({ has: page.locator('[data-action-intent=resume_training]') });
      await expect(primary).toContainText(author.title);
      await primary.locator('[data-action-intent=resume_training]').click();
      await expect(card).toHaveAttribute('data-training-card-id', 'author-card');
      await expect(card).toContainText('2/5');
    });
  }
}

for (const mode of ['foreign', 'missing', 'stale']) {
  test(`unbound ${mode} practice cannot promote authored card facts`, async ({ page }) => {
    await seed(page, 'en-US', true, mode);
    const card = page.locator('.training-pane');
    await expect(card).toBeVisible();
    if (mode === 'missing') {
      await expect(card).not.toHaveAttribute('data-training-card-id', /.+/);
    } else {
      await expect(card).toHaveAttribute('data-training-card-id', 'author-card');
    }
    if (mode === 'stale') await expect(card).toHaveAttribute('data-training-leftover-not-live', 'true');
    await expect(page.locator('.template-surface[data-surface=training]')).not.toContainText(author.title);
    await expect(page.locator('.template-surface[data-surface=training]')).not.toContainText(author.deliverable);
  });
}

for (const status of ['recovering', 'stale']) {
  test(`explicit sync ${status} does not elevate mixed-language author facts`, async ({ page }) => {
    await seed(page, 'en-US', false);
    await expect(page.locator('.template-activity-header')).toContainText(author.title);
    await page.evaluate(status => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
      type: 'state/syncStatus', payload: { generation: 1, status },
    }), status);
    await expect(page.locator('.training-pane')).toHaveAttribute('data-training-card-id', 'author-card');
    await expect(page.locator('.template-activity-header')).not.toContainText(author.title);
    await expect(page.locator('.training-pane')).not.toContainText(author.deliverable);
  });
}
