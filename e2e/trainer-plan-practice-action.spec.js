const { test, expect } = require("playwright/test");

test("Set as practice binds a live plan step after Return without minting a parallel task", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=coach&lang=zh-CN&connection=connected&run=plan-practice-action");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const bootstrap = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  await page.addInitScript(() => {
    window.__TRAINER_E2E_HOST_ACTIONS__ = [];
    window.acquireVsCodeApi = () => ({
      getState: () => ({ activeView: "coach", composerLanguage: "zh-CN", themePreference: "dark" }),
      setState: () => undefined,
      postMessage: message => window.__TRAINER_E2E_HOST_ACTIONS__.push(message),
    });
  });
  await page.goto("/");
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .some(action => action.type === "request/bootstrap"))).toBe(true);
  const step = "在 list_pairs.py 补充 hash 与字典键的 TypeError 用例，再运行 pytest。";
  const runtime = { recovered: true, planId: "current-plan", currentStep: step };
  const payload = {
    ...bootstrap, hasFormalPlan: true, sessionHistoryRestored: true,
    plan: { ...bootstrap.plan, id: "current-plan", frozen: false, currentStep: step, revision: 3,
      stages: [{ id: "current-stage", title: "验证不可哈希边界", status: "active" }] },
    planRuntimeStatus: runtime,
    memory: { ...bootstrap.memory,
      workspace: { ...bootstrap.memory.workspace, latestPlanRuntime: runtime },
      coachingAdaptation: { ...bootstrap.memory.coachingAdaptation, closedLoopReturnBlocksTaskMint: true },
    },
    coachFocus: { ...bootstrap.coachFocus, closedLoopReturnBlocksTaskMint: true },
    conversation: [{ id: "practice-action", role: "assistant", author: "Trainer", timestamp: "10:00",
      body: "按当前正式步骤继续。", artifacts: [{ kind: "next_step", title: "当前步骤",
        recommendedAction: "task", focusArea: "旧回复不能覆盖当前步骤", summary: "历史摘要" }] }],
  };
  async function apply() {
    await page.evaluate(data => window.postMessage({ type: "bootstrap", payload: data }, window.location.origin), payload);
  }
  await apply();
  await page.getByRole('button', { name: "下一步：设为练习", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(action => action.type === "command/execute" && action.payload.commandId === "trainer.training.generateCard").length)).toBe(1);
  const generated = await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .find(action => action.type === "command/execute" && action.payload.commandId === "trainer.training.generateCard"));
  expect(generated.payload.payload).toMatchObject({ cardType: "practice", submode: "practice",
    focusArea: "验证不可哈希边界", prompt: step, contextHint: step,
    source: "formal_plan_step", planBinding: {
      planId: "current-plan", stageId: "current-stage", step, revision: 3,
    } });
  expect(await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(action => action.type.startsWith("session/send") ||
      ["trainer.task.specify", "trainer.task.next"].includes(action.payload?.commandId)))).toEqual([]);
  payload.plan.frozen = true;
  await apply();
  await page.getByRole('button', { name: "下一步：设为练习", exact: true }).click();
  await expect(page.locator('#coach-composer')).toHaveValue("先继续当前复习项，不要新开正式任务。");
  expect(await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(action => action.type === "command/execute" && action.payload.commandId === "trainer.training.generateCard").length)).toBe(1);
  // Recovered leftovers have no authority to create a new card.
  payload.planRuntimeStatus = { recovered: true, currentStep: "" };
  payload.memory.workspace.latestPlanRuntime = { recovered: true, currentStep: "" };
  await apply();
  await page.getByRole('button', { name: "下一步：设为练习", exact: true }).click();
  await expect(page.locator('#coach-composer')).toHaveValue("先继续当前复习项，不要新开正式任务。");
  expect(await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(action => action.type === "command/execute" && action.payload.commandId === "trainer.training.generateCard").length)).toBe(1);
});

test("a new practice stays unverified when an older card has completed Return", async ({ page }) => {
  const { mergeMemorySummary } = require('../extension/dist/extension/src/core/workbenchData.js');
  await page.goto('/vscode-preview.html?view=training&lang=zh-CN&connection=connected&run=new-practice-proof');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const current = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  const workspaceId = 'workspace-new-practice-proof';
  current.memory.workspace = { ...current.memory.workspace, workspaceId };
  const card = { card_id: 'new-practice', card_type: 'practice', title: '验证不可哈希边界',
    status: 'active', learning_phase: 'try', learning_family: 'code', learning_subtype: 'implementation',
    files_to_touch: ['list_pairs.py'], expected_symbols: ['test_nested_mutability'],
    learner_deliverables: ['补齐 hash 和字典键的 TypeError 用例'], verification_steps: ['运行当前文件的 pytest'],
  };
  const patch = mergeMemorySummary(current, { context_id: workspaceId, memory: {
    workspace: { workspace_id: workspaceId, selected_card_id: card.card_id, selected_card_type: 'practice',
      selected_card_status: 'active', selected_card_title: '旧练习标题', latest_training_submode: 'practice',
      live_training_selection: { workspace_id: workspaceId, card_id: card.card_id, selected_at: '2026-10-02T05:15:00Z' },
      latest_training_handoff: { workspace_id: workspaceId, card_id: 'old-practice', handoff_id: 'old-handoff',
        learning_phase: 'return', handoff_status: 'verified', status: 'completed' },
      latest_training_next_hop: { workspace_id: workspaceId, selected_card_id: card.card_id, status: 'return_required' },
      latest_learning_verified_result: 'OLD_TRUSTED_PROOF',
    },
    training_card_candidates: [card],
    active_training_card_routing: { workspace_id: workspaceId, selected_card_id: card.card_id, selected_card: card },
    review_artifact: { id: 'old-recall', status: 'resolved', verified_result: 'OLD_RECALL_PROOF' },
  } });
  expect(patch.workspaceTrainingState.latestTrainingHandoff).toBeUndefined();
  expect(patch.workspaceTrainingState.latestLearningVerifiedResult).toBeUndefined();
  await page.evaluate(data => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: data }), {
    ...current, ...patch, conversation: [], sessionHistoryRestored: true,
  });
  await expect(page.getByRole('heading', { name: '验证不可哈希边界', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '验证当前文件', exact: true })).toBeVisible();
  await expect(page.getByPlaceholder('无需填写内容。核对可信验证结果后，点击完成回流。')).toHaveCount(0);
  await expect(page.getByText('OLD_TRUSTED_PROOF', { exact: true })).toHaveCount(0);
  await expect(page.getByText('OLD_RECALL_PROOF', { exact: true })).toHaveCount(0);
});

test('training reads Markdown and keeps Next below the card without management sections', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/vscode-preview.html?view=training&lang=zh-CN&connection=connected&run=markdown-training');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const current = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  const card = { cardId: 'markdown-practice', type: 'practice', title: '验证列表的可变性', status: 'active',
    learningPhase: 'try', learningFamily: 'code', learningSubtype: 'implementation',
    problemStatement: '保留 **一个测试函数**。\n\n1. 调用 `pair[0].append(4)`。\n2. 捕获 `TypeError`。\n\n```python\npair = ([1, 2], 3)\n```',
    learnerDeliverables: ['一个可执行测试'], verificationSteps: ['运行 `pytest -q`'],
    whyNow: 'SHOULD_NOT_SHOW_REASON' };
  const data = { ...current, conversation: [], sessionHistoryRestored: true,
    workspaceTrainingState: { workspaceId: current.memory.workspace.workspaceId,
      selectedCardId: card.cardId, selectedCardType: 'practice', selectedCardStatus: 'active',
      latestTrainingSubmode: 'practice', selectedCardTitle: card.title, trainingCardCandidates: [card],
      dueReviews: [{ concept: 'SHOULD_NOT_SHOW_REVIEW', focusArea: 'Python' }],
    },
  };
  await page.evaluate(data => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: data }), data);
  for (const [widthIndex, width] of [300, 360, 800].entries()) {
    await page.setViewportSize({ width, height: 760 });
    const face = page.locator('.template-focused-practice__phase');
    await expect(face.getByText('一个测试函数', { exact: true })).toBeVisible();
    await expect(face.locator('strong').filter({ hasText: '一个测试函数' })).toHaveCount(1);
    await expect(face.locator('ol > li')).toHaveCount(2);
    await expect(face.locator('pre')).toHaveCount(1);
    await expect(face.locator('[data-training-next-card]').filter({ visible: true })).toHaveCount(0);
    // No "More → Next Card" disclosure anymore: an active card has no next-card
    // control anywhere, and the single task-details disclosure sits below the
    // card face, closed until opened.
    await expect(page.locator('[data-training-next-card]')).toHaveCount(0);
    await expect(page.locator('.template-focused-practice > details')).toHaveCount(1);
    const details = page.locator('[data-training-card-details]');
    await expect(details).toHaveCount(1);
    if (widthIndex === 0) await expect(details).not.toHaveAttribute('open', '');
    if (!await details.evaluate(el => el.open)) await details.locator(':scope > summary').click();
    const bottom = await face.boundingBox(); const next = await details.boundingBox();
    expect(next.y).toBeGreaterThanOrEqual(bottom.y + bottom.height - 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await expect(page.locator('[data-training-review-queue], .training-loop-rail, .skill-projection-strip')).toHaveCount(0);
    // The card face never shows the made-up reason; the card's own whyNow may
    // live inside the user-opened task-details disclosure.
    await expect(face.getByText('SHOULD_NOT_SHOW_REASON', { exact: true })).toHaveCount(0);
    await expect(page.getByText('SHOULD_NOT_SHOW_REVIEW', { exact: true })).toHaveCount(0);
  }
  // An explicit action belongs to this card; a prior plan step must not replace
  // the task when the card supplies only a Markdown problem statement.
  card.suggestedWorkspaceAction = '在 `list_pairs.py` 添加 **负向断言**，再运行测试。';
  card.problemStatement = 'SHOULD_NOT_SHOW_BACKGROUND_REASON';
  await page.evaluate(data => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: data }), data);
  await expect(page.locator('.template-focused-practice__phase strong').filter({ hasText: '负向断言' })).toHaveCount(1);
  await expect(
    page.locator('.template-focused-practice__phase').getByText('SHOULD_NOT_SHOW_BACKGROUND_REASON', { exact: true }),
  ).toHaveCount(0);
});

test('the active practice shows verification failure without borrowing an older result', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=training&lang=zh-CN&connection=connected&run=verification-failure');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const current = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  const card = { cardId: 'script-current', type: 'practice', title: '运行递归脚本', status: 'active',
    learningPhase: 'try', learningFamily: 'code', learningSubtype: 'implementation',
    problemStatement: '运行 `sum_nested.py`。', filesToTouch: ['sum_nested.py'],
    learnerDeliverables: ['脚本输出'], verificationSteps: ['运行 Python'] };
  const failure = '脚本输出不符合要求：第二行应为 6，实际为 99。';
  const payload = { ...current, conversation: [], sessionHistoryRestored: true,
    workspaceTrainingState: { workspaceId: current.memory.workspace.workspaceId,
      selectedCardId: card.cardId, selectedCardType: 'practice', selectedCardStatus: 'active',
      latestTrainingSubmode: 'practice', selectedCardTitle: card.title, trainingCardCandidates: [card],
      latestLearningBlocker: '',
      latestTrainingNextHop: { candidateId: card.cardId, status: 'verification_required',
        statusReason: failure, summary: failure },
    },
  };
  await page.evaluate(data => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: data }), payload);
  await expect(page.locator('[data-template=VerificationResult] > p')).toHaveText(failure);
  await expect(page.getByRole('button', { name: '验证当前文件', exact: true })).toBeVisible();
  payload.workspaceTrainingState.latestTrainingNextHop.candidateId = 'script-older';
  await page.evaluate(data => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: data }), payload);
  await expect(page.locator('[data-template=VerificationResult]')).toHaveCount(0);
});
