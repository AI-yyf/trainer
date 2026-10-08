const { test, expect } = require('playwright/test');

// Preview proves action semantics and state wiring, never real learning evidence.
async function openLearning(page, language = 'en-US') {
  await page.goto(`/vscode-preview.html?view=plan&lang=${language}&scenario=ready&connection=connected&run=learning-actions-${language}`);
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const source = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  const workspaceId = 'workspace-actions';
  const step = {
    'zh-CN': '在 parser_test.py 补充边界测试',
    'en-US': 'Add boundary tests to parser_test.py',
    'es-ES': 'Añadir pruebas de límites en parser_test.py',
    'fr-FR': 'Ajouter les tests de limites dans parser_test.py',
    'de-DE': 'Grenztests in parser_test.py ergänzen',
    'ja-JP': 'parser_test.py に境界テストを追加する',
    'ko-KR': 'parser_test.py에 경계 테스트 추가',
    'pt-BR': 'Adicionar testes de limites em parser_test.py',
  }[language];
  const runtime = { recovered: true, planId: 'plan-actions', currentStep: step, reviewPoints: [], resumeState: 'in_progress' };
  const workspace = { ...source.memory.workspace, workspaceId, latestPlanRuntime: runtime };
  for (const key of ['latestTrainingHandoff','latestTrainingNextHop','liveTrainingSelection','latestConversationHandoff']) delete workspace[key];
  const payload = { ...source, sessionLabel: 'actions-session', sessionHistoryRestored: true, hasFormalPlan: true,
    conversation: [], planRuntimeStatus: runtime,
    // This fixture changes workspace identity, so its simulated host readiness
    // result must be bound to the same workspace and current provider profile.
    providerConfig: { ...source.providerConfig, lastTestResult: {
      ...source.providerConfig.lastTestResult, workspaceId,
      profileId: source.providerConfig.profileId, responseLanguage: language,
    } },
    plan: { ...source.plan, id: 'plan-actions', revision: 3, currentStep: step, frozen: false,
      stages: [{ id: 'stage-actions', title: 'Boundary rules', status: 'active' }] },
    memory: { ...source.memory, workspace, dueReviews: [],
      evidenceQueue: { pending: [], adopted: [], deferred: [], rejected: [], totalCount: 0 } },
    workspaceTrainingState: { workspaceId, selectedCardId: '', trainingCardCandidates: [], dueReviews: [] },
  };
  await page.addInitScript(({ payload, language, workspaceId }) => {
    window.__ACTION_TEST_PAYLOAD__ = payload;
    window.__ACTION_TEST_HOST_ACTIONS__ = [];
    window.__ACTION_TEST_REVISION__ = 0;
    window.__ACTION_TEST_APPLY__ = next => {
      window.__ACTION_TEST_PAYLOAD__ = next;
      const revision = ++window.__ACTION_TEST_REVISION__;
      window.postMessage({ type: 'bootstrap', sync: { generation: 1, revision, baseRevision: 0,
        messageId: `actions-${revision}`, workspaceId, sessionId: 'actions-session' }, payload: next }, location.origin);
    };
    window.acquireVsCodeApi = () => ({
      getState: () => ({ activeView: 'plan', composerLanguage: language, themePreference: 'dark' }),
      setState() {},
      postMessage(message) {
        window.__ACTION_TEST_HOST_ACTIONS__.push(message);
        if (message.type === 'request/bootstrap') setTimeout(() => window.__ACTION_TEST_APPLY__(window.__ACTION_TEST_PAYLOAD__), 0);
      },
    });
  }, { payload, language, workspaceId });
  await page.goto('/');
  await expect(page.locator('[data-surface=plan] [data-action-intent=continue_step]')).toBeVisible();
  return { payload, step };
}

async function apply(page, payload) {
  await page.evaluate(next => window.__ACTION_TEST_APPLY__(next), payload);
}

for (const [language, label] of [
  ['zh-CN', '继续当前步骤'], ['en-US', 'Continue current step'], ['es-ES', 'Continuar el paso actual'],
  ['fr-FR', 'Continuer l’étape actuelle'], ['de-DE', 'Aktuellen Schritt fortsetzen'],
  ['ja-JP', '現在の手順を続ける'], ['ko-KR', '현재 단계 계속'], ['pt-BR', 'Continuar a etapa atual'],
]) test(`optional evidence keeps one coherent next step in ${language}`, async ({ page }) => {
  const { payload, step } = await openLearning(page, language);
  payload.memory.evidenceQueue = { pending: [{ id: 'e1', summary: 'Unconfirmed test report',
    outcome: 'self_reported', targetPlanStep: step, timestamp: '2026-10-08T08:00:00Z' }], adopted: [], deferred: [], rejected: [], totalCount: 1 };
  await apply(page, payload);
  const next = page.locator('[data-surface=plan] [data-template=NextAction]');
  await expect(next.locator('h3')).toHaveText(step);
  await expect(next.getByRole('button')).toHaveText(label);
  await expect(next.getByRole('button')).toBeEnabled();
  await expect(page.locator('[data-surface=plan] [data-primary-action=true]')).toHaveCount(1);
  await next.getByRole('button').click();
  await expect(page.locator('[data-surface=coach]')).toBeVisible();
  const actions = await page.evaluate(() => window.__ACTION_TEST_HOST_ACTIONS__);
  const resume = actions.find(message => message.type.startsWith('session/send'));
  expect(resume.payload.planRuntimeRecovery).toMatchObject({ action: 'continue_step', currentStep: step });
  expect(resume.payload.formalPlanMutation).toBe(false);
  expect(actions.filter(message => message.payload?.commandId === 'trainer.evidence.adopt')).toHaveLength(0);
});

test('a bound evidence gate approves the visible candidate; blocker and frozen states keep their own meaning', async ({ page }) => {
  const { payload, step } = await openLearning(page);
  payload.memory.evidenceQueue = { pending: [{ id: 'e1', summary: 'Actual result to inspect',
    outcome: 'passed', targetPlanStep: step, timestamp: '2026-10-08T08:00:00Z' }], adopted: [], deferred: [], rejected: [], totalCount: 1 };
  payload.planRuntimeStatus.resumeState = 'waiting';
  payload.memory.workspace.latestPlanRuntime = { ...payload.planRuntimeStatus, evidenceBinding: 'e1' };
  await apply(page, payload);
  const surface = page.locator('[data-surface=plan]');
  const next = surface.locator('[data-template=NextAction]');
  await expect(next.locator('h3')).toHaveText('Actual result to inspect');
  await expect(next.getByRole('button')).toHaveText('Approve this evidence');
  await expect(surface.locator('[data-plan-evidence-decision=defer]')).toBeVisible();
  await expect(surface.locator('[data-plan-evidence-decision=reject]')).toBeVisible();
  await next.getByRole('button').click();
  await expect.poll(() => page.evaluate(() => window.__ACTION_TEST_HOST_ACTIONS__
    .some(message => message.payload?.commandId === 'trainer.evidence.adopt'))).toBe(true);
  const approval = await page.evaluate(() => window.__ACTION_TEST_HOST_ACTIONS__
    .find(message => message.payload?.commandId === 'trainer.evidence.adopt'));
  expect(approval.payload.payload).toEqual({ evidenceId: 'e1' });
  payload.planRuntimeStatus.blockedReason = 'The project test runner is missing';
  payload.memory.workspace.latestPlanRuntime = { ...payload.planRuntimeStatus, evidenceBinding: 'e1' };
  await apply(page, payload);
  await expect(next.getByRole('button')).toHaveText('Resolve with coach');
  await expect(next).toContainText('The project test runner is missing');
  payload.plan.frozen = true;
  await apply(page, payload);
  await expect(next.getByRole('button')).toHaveText('Resume plan');
  await expect(next.locator('h3')).toHaveText('The plan is paused');
});

test('stale Learning cannot start work and offers a full state refresh', async ({ page }) => {
  await openLearning(page);
  await page.evaluate(() => window.postMessage({ type: 'state/syncStatus', payload: { generation: 1, status: 'stale' } }, location.origin));
  const button = page.locator('[data-surface=plan] [data-action-intent=restore_state]');
  await expect(button).toHaveText('Refresh state');
  await button.click();
  await expect(page.locator('[data-surface=plan] [data-action-intent=continue_step]')).toBeVisible();
  expect(await page.evaluate(() => window.__ACTION_TEST_HOST_ACTIONS__
    .filter(message => message.type.startsWith('session/send')).length)).toBe(0);
});

test('an idle sidecar preserves current work for a verified provider', async ({ page }) => {
  const { payload, step } = await openLearning(page);
  payload.connection.state = 'offline';
  await apply(page, payload);
  const button = page.locator('[data-surface=plan] [data-action-intent=continue_step]');
  await expect(button).toBeEnabled();
  await button.click();
  const resume = await page.evaluate(() => window.__ACTION_TEST_HOST_ACTIONS__
    .find(message => message.type.startsWith('session/send')));
  expect(resume.payload.planRuntimeRecovery).toMatchObject({ action: 'continue_step', currentStep: step });
});

test('an earlier notice exit cannot dismiss the new notice; delivery uncertainty belongs to Training', async ({ page }) => {
  await openLearning(page);
  const post = message => page.evaluate(message => window.postMessage(message, location.origin), message);
  await post({ type: 'operation/status', payload: { tone: 'error', message: 'first failure' } });
  const notice = page.locator('.template-global-state');
  await expect(notice).toBeVisible();
  await notice.getByRole('button').click();
  await post({ type: 'operation/status', payload: { tone: 'error', message: '[[trainer-attestation-undelivered]] hidden backend exception' } });
  await expect(notice).toHaveCount(0);
  await page.evaluate(() => window.postMessage({ type: 'ui/restoreView', payload: { activeView: 'training' } }, location.origin));
  await expect(notice).toContainText('has not been confirmed as saved');
  await expect(notice).not.toContainText('hidden backend exception');
  await expect(notice).not.toContainText('[[trainer-attestation-undelivered]]');
  // Wait beyond the actual exit animation by polling a stable browser-frame window.
  await notice.evaluate(async node => {
    const until = performance.now() + 250;
    while (performance.now() < until) await new Promise(resolve => requestAnimationFrame(resolve));
    if (!node.isConnected) throw new Error('A prior dismissal removed the current notice');
  });
  await expect(notice).toBeVisible();
});
