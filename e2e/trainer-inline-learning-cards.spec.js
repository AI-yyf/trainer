const { test, expect } = require('playwright/test');

/**
 * The learning surfaces that live inside the conversation.
 *
 * Two acceptance facts are proven here, both of them about what the learner
 * sees in the message flow rather than on a page of its own:
 *
 *   1. A practice answers inside its own card, and a settled practice leaves a
 *      progress receipt in the same flow — both in the conversation, never on
 *      a separate Learning surface.
 *   2. A sent message keeps its source as an auditable footnote, while the
 *      internal management context stays hidden.
 */

const author = {
  title: 'Fixture 练习:workspace_id isolation',
  problemStatement: '练习workspace_id isolation时,为什么一次请求必须保留原来的 workspace_id?',
  suggestedWorkspaceAction: '描述一次请求及其原始 workspace_id。',
  deliverable: '说明原始 workspace_id、收到的 workspace_id,以及不匹配时如何拒绝结果。',
  learnerDeliverables: ['说明原始 workspace_id、收到的 workspace_id,以及不匹配时如何拒绝结果。'],
  validationMethod: '应用结果前比较 `workspace_id`;不匹配的结果必须保持拒绝。',
  verificationSteps: ['应用结果前比较 `workspace_id`;不匹配的结果必须保持拒绝。'],
};

async function seedSettledPractice(page) {
  await page.goto('/vscode-preview.html?view=coach&lang=zh-CN&connection=connected&run=inline-progress');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate((author) => {
    const current = /** @type {import('../extension/webview/src/lib/types').BootstrapData} */ (window.__TRAINER_BOOTSTRAP__);
    const workspaceId = 'workspace-inline-progress';
    const card = {
      ...author,
      cardId: 'author-card',
      type: 'practice',
      status: 'active',
      learningPhase: 'try',
      focusArea: 'workspace_id isolation',
      answerMode: 'text',
      targetSkill: 'workspace boundary',
    };
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: {
      ...current,
      sessionHistoryRestored: true,
      plan: null,
      task: { ...current.task, title: 'OLD_FORMAL_TASK_TITLE' },
      planRuntimeStatus: { recovered: true, currentStep: '', reviewPoints: [] },
      memory: {
        ...current.memory,
        currentFocus: 'OLD_AMBIENT_FOCUS',
        workspace: {
          ...current.memory.workspace,
          workspaceId,
          liveTrainingSelection: { workspaceId, cardId: 'author-card', selectedAt: '2026-10-09T00:00:00Z' },
          latestPlanRuntime: undefined,
          latestTrainingHandoff: undefined,
          latestTrainingNextHop: undefined,
        },
      },
      workspaceTrainingState: {
        workspaceId,
        selectedCardId: 'author-card',
        selectedCardType: 'practice',
        selectedCardTitle: card.title,
        selectedCardStatus: 'active',
        trainingCardCandidates: [card],
        activeTrainingCardRouting: { selectedCardId: 'author-card', selectedCard: card },
        // The growth projection is the evidence the progress receipt reports.
        skillProjection: current.workspaceTrainingState?.skillProjection,
        // A settled practice: the card has a verified result. The field is a
        // host string (the verified summary), not a structured record.
        latestLearningVerifiedResult: '已验证:边界检查通过',
      },
    } });
  }, author);
  await expect(page.locator('[data-inline-practice="true"]')).toBeVisible();
}

test('a settled practice leaves its progress receipt inside the conversation', async ({ page }) => {
  await seedSettledPractice(page);

  // The practice answers in its own card, in the message flow.
  await expect(page.locator('[data-training-card-id="author-card"]')).toBeVisible();
  await expect(page.locator('[data-inline-practice-answer="true"]')).toBeVisible();

  // The progress receipt is part of the same flow, not a separate surface.
  const receipt = page.locator('[data-inline-progress="true"]');
  await expect(receipt).toBeVisible();
  await expect(receipt).toHaveCount(1);
  await expect(receipt.locator('.inline-progress-card__rows li')).not.toHaveCount(0);
  // It is a receipt, not a page: it names the dimensions and hands management
  // to the learning drawer instead of repeating the whole growth view.
  await expect(receipt.getByRole('button')).toHaveCount(1);

  // No third learning surface appeared anywhere.
  await expect(page.locator('.app-shell-nav button')).toHaveCount(2);
});

test('a sent message keeps its source as an auditable footnote and hides internal context', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=coach&lang=zh-CN&connection=connected&run=message-footnote');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = /** @type {import('../extension/webview/src/lib/types').BootstrapData} */ (window.__TRAINER_BOOTSTRAP__);
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: {
      ...current,
      sessionHistoryRestored: true,
      conversation: [
        { id: 'question', role: 'user', author: 'You', timestamp: '09:59',
          body: '帮我检查这个边界',
          sourceNote: '来自资料:boundary.md',
          contextNote: 'HIDDEN_USER_INTENT_AND_MODE',
          attachments: [{ label: '文件', value: 'boundary.py' }] },
      ],
    } });
  });
  await expect(page.locator('.message-support-line').first()).toBeVisible();

  // The source stays auditable next to the sent message.
  await expect(page.getByText('来自资料:boundary.md', { exact: true })).toBeVisible();
  // The internal management context never reaches the conversation.
  await expect(page.getByText(/HIDDEN_/).filter({ visible: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.body.innerText)).not.toContain('HIDDEN_USER_INTENT_AND_MODE');
});

test('a malformed host field does not take the workbench down', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=coach&lang=zh-CN&connection=connected&run=malformed-host-field');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = /** @type {import('../extension/webview/src/lib/types').BootstrapData} */ (window.__TRAINER_BOOTSTRAP__);
    const workspaceId = 'workspace-malformed-field';
    const card = { cardId: 'author-card', type: 'practice', status: 'active', learningPhase: 'try',
      title: 'Fixture 练习', problemStatement: 'p', deliverable: 'd', answerMode: 'text' };
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: {
      ...current,
      sessionHistoryRestored: true,
      plan: null,
      memory: { ...current.memory, workspace: { ...current.memory.workspace, workspaceId,
        liveTrainingSelection: { workspaceId, cardId: 'author-card', selectedAt: '2026-10-09T00:00:00Z' } } },
      workspaceTrainingState: { workspaceId, selectedCardId: 'author-card', selectedCardType: 'practice',
        selectedCardTitle: card.title, selectedCardStatus: 'active', trainingCardCandidates: [card],
        activeTrainingCardRouting: { selectedCardId: 'author-card', selectedCard: card },
        // The declared type is a string. A host that sends a record instead
        // must not blank the whole workbench.
        latestLearningVerifiedResult: { id: 'malformed', outcome: 'pass' } },
    } });
  });
  await page.waitForTimeout(500);

  // The error boundary is not the answer: the conversation still renders.
  await expect(page.getByText('Trainer 暂时无法打开')).toHaveCount(0);
  await expect(page.locator('.trainer-body')).toBeVisible();
  await expect(page.locator('.app-shell-nav button')).toHaveCount(2);
});
