const { test, expect } = require("playwright/test");

test("Coach keeps the actual recall reply without displaying review records or grading identities", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=coach&lang=zh-CN&connection=connected&run=recall-display");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: "bootstrap", payload: {
      ...current, sessionHistoryRestored: true,
      conversation: [{ id: "recall-display", role: "assistant", author: "Trainer", timestamp: "10:00",
        body: "这个概念解释准确。", artifacts: [
          { kind: "review", title: "复习：trainer-python:next-step", focusArea: "trainer-python:next-step",
            summary: "当前概念回忆", metadata: { evidence_scope: "self_reported_recall", review_artifact_id: "recall-id" } },
          { kind: "review", title: "我自己的复习标题", focusArea: "trainer-python:next-step",
            metadata: { evidence_scope: "self_reported_recall" } },
          { kind: "evaluation", title: "trainer-python:next-step", focusArea: "trainer-python:next-step" },
        ] }],
    } });
  });
  await expect(page.getByText('这个概念解释准确。', { exact: true })).toBeVisible();
  await expect(page.locator('.coach-artifact-card').filter({ visible: true })).toHaveCount(0);
  await page.locator('.template-reply-evidence > summary').click();
  await expect(page.locator('.coach-artifact-card')).toHaveCount(3);
  await page.locator('.template-reply-evidence > summary').click();
  expect(await page.locator('.message-bubble').innerText()).not.toContain('trainer-python:next-step');
  expect(await page.locator('.message-bubble').innerText()).not.toContain('我自己的复习标题');
});

test("a saved plan reply remains visible without the historical tool panel", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=coach&lang=zh-CN&connection=connected&run=plan-tool-label");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: "bootstrap", payload: {
      ...current, sessionHistoryRestored: true,
      conversation: [{ id: "saved-plan-label", role: "assistant", author: "Trainer", timestamp: "10:00",
        body: "正式计划已保存。", parts: [{ type: "tool_result", callId: "save-call", name: "save_formal_plan",
          result: { ok: true, committed: true }, step: 1 }] }],
    } });
  });
  await expect(page.getByText('正式计划已保存。', { exact: true })).toBeVisible();
  await expect(page.locator('.message-bubble__tool-trail, .agent-activity-pill')).toHaveCount(0);
});

test("Learning keeps historical and independent records out of the current action", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=plan&lang=zh-CN&connection=connected&run=evidence-display");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const evidenceQueue = { pending: [], deferred: [], adopted: [], rejected: [], totalCount: 2,
      history: [{ id: "earlier-check", source: "evaluation", summary: "旧阶段的文件检查", concepts: [], outcome: "pass",
        confidence: 0.9, targetPlanStageId: "earlier-step", verified: true }],
      unscoped: [{ id: "independent-check", source: "evaluation", summary: "未绑定计划的独立检查", concepts: [], outcome: "pass",
        confidence: 0.7, verified: false }],
    };
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: "bootstrap", payload: {
      ...current, sessionHistoryRestored: true, evidenceQueue,
      memory: { ...current.memory, evidenceQueue },
    } });
  });
  const primary = page.locator('[data-plan-primary="true"]');
  await expect(primary).toBeVisible();
  await expect(primary.locator('[data-template=NextAction] > button')).not.toHaveText(/接纳|采纳/);
  await expect(page.locator('.coach-plan-view__evidence-row, [data-plan-governance-disclosure][open]').filter({ visible: true })).toHaveCount(0);
  await expect(page.getByText('旧阶段的文件检查', { exact: true }).filter({ visible: true })).toHaveCount(0);
  await expect(page.getByText('未绑定计划的独立检查', { exact: true }).filter({ visible: true })).toHaveCount(0);
  await expect(page.locator('#coach-composer')).toHaveCount(0);
});

test("long historical records cannot overflow or take over the current Learning view", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=plan&lang=zh-CN&connection=connected&run=evidence-geometry");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const evidenceQueue = { pending: [], deferred: [], adopted: [], rejected: [], unscoped: [], totalCount: 1,
      history: [{ id: "long-record", source: "evaluation", summary: "旧阶段的文件检查" + "long_unbroken_identifier".repeat(16),
        concepts: [], outcome: "pass", confidence: 0.9, targetPlanStageId: "long-stage-".repeat(16), verified: true }],
    };
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: "bootstrap", payload: {
      ...current, sessionHistoryRestored: true, evidenceQueue, memory: { ...current.memory, evidenceQueue },
    } });
  });
  await expect(page.locator('.coach-plan-view__evidence-row, [data-plan-governance-disclosure][open]').filter({ visible: true })).toHaveCount(0);
  await expect(page.getByText(/long_unbroken_identifier/).filter({ visible: true })).toHaveCount(0);
  const primary = page.locator('[data-plan-primary="true"]');
  await expect(primary).toBeVisible();
  for (const width of [300, 360, 800]) {
    await page.setViewportSize({ width, height: 1000 });
    const geometry = await primary.evaluate(element => ({
      overflow: element.scrollWidth - element.clientWidth,
      right: element.getBoundingClientRect().right, viewport: innerWidth,
    }));
    expect(geometry.overflow).toBeLessThanOrEqual(1);
    expect(geometry.right).toBeLessThanOrEqual(geometry.viewport + 1);
  }
});
