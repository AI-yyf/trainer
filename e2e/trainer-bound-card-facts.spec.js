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
    if (mode === 'blank-bound') {
      for (const field of Object.keys(author)) delete card[field];
      card.title = ' ';
      card.problemStatement = 'Same_bound_problem';
      delete card.focusArea;
      delete card.targetSkill;
    }
    const route = mode === 'blank-bound' ? { ...author, cardId: 'foreign-card',
      title: 'foreign_workspace_id', focusArea: 'foreign_workspace_id',
      problemStatement: 'foreign_workspace_id', suggestedWorkspaceAction: 'foreign_workspace_id',
      deliverable: 'foreign_workspace_id', learnerDeliverables: ['foreign_workspace_id'],
      validationMethod: 'foreign_workspace_id', verificationSteps: ['foreign_workspace_id'] } : card;
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
        activeTrainingCardRouting: mode === 'missing' ? undefined : { selectedCardId: route.cardId, selectedCard: route },
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

// Reconstruct the installed Windows restore mismatch: the restored scenario
// supplies its own title/problem, while selected routing still points to Flash.
const scenarioSummary = '读取 FastAPI 收据并验证其请求边界。';
async function seedRestoredScenario(page, language, nativeHost = false, verificationSteps, summary = scenarioSummary) {
  await page.goto(`/vscode-preview.html?view=training&lang=${language}&connection=connected&run=missing-bound-${language}`);
  await expect(page.locator('#root[data-trainer-app-ready=true]')).toBeVisible();
  const foreignAction = language === 'zh-CN' ? '描述一次请求及其原始 workspace_id。' : 'Describe a request and its original workspace_id.';
  const bootstrap = await page.evaluate(({ foreignAction, nativeHost, verificationSteps, summary }) => {
    const current = /** @type {import('../extension/webview/src/lib/types').BootstrapData} */ (window.__TRAINER_BOOTSTRAP__);
    const workspaceId = 'workspace-restored-scenario';
    const oldFlash = { cardId: 'foreign-flash', type: 'flash', status: 'active', learningPhase: 'try',
      title: 'Fixture flash: workspace_id', problemStatement: foreignAction, suggestedWorkspaceAction: foreignAction,
      deliverable: foreignAction, learnerDeliverables: [foreignAction], validationMethod: foreignAction,
      verificationMethod: foreignAction, verificationSteps: [foreignAction], acceptanceCriteria: [foreignAction],
      successSignal: foreignAction, returnWith: foreignAction, nextAfterCompletion: foreignAction,
      reflectionPrompt: foreignAction, stuckRecovery: foreignAction, targetSkill: 'foreign_workspace_id',
      apiHints: ['foreign_workspace_id'], constraints: ['foreign_workspace_id'], selfCheck: ['foreign_workspace_id'],
      filesToTouch: ['foreign_workspace_id.py'], hintLadder: [foreignAction], commonMistakes: [foreignAction],
      expectedSymbols: ['foreign_workspace_id'], focusArea: 'workspace_id isolation', answerMode: 'text' };
    const next = { ...current, plan: null,
      sessionHistoryRestored: true, planRuntimeStatus: { recovered: true, currentStep: '', reviewPoints: [] },
      memory: { ...current.memory, workspace: { ...current.memory.workspace, workspaceId,
        liveTrainingSelection: { workspaceId, cardId: oldFlash.cardId, selectedAt: '2026-10-09T00:00:00Z' },
        latestPlanRuntime: undefined, latestTrainingHandoff: undefined, latestTrainingNextHop: undefined } },
      workspaceTrainingState: { workspaceId, selectedCardId: oldFlash.cardId, selectedCardTitle: oldFlash.title,
        selectedCardType: 'flash', selectedCardStatus: 'active', trainingCardCandidates: [oldFlash],
        activeTrainingCardRouting: { selectedCardId: oldFlash.cardId, selectedCard: oldFlash },
        scenarioLab: { id: 'restored-scenario', title: 'Scenario lab: FastAPI receipt', status: 'ready',
          lastAction: 'restore_history', reviewOutcome: 'CONTROL_REVIEW_OUTCOME', ...(summary === null ? {} : { summary }), focusArea: 'FastAPI receipt', verificationSteps } },
    };
    if (!nativeHost) window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: next });
    return next;
  }, { foreignAction, nativeHost, verificationSteps, summary });
  if (nativeHost) {
    await page.addInitScript(({ bootstrap, language }) => {
      window.__TRAINER_BOOTSTRAP__ = bootstrap;
      window.__TRAINER_E2E_HOST_ACTIONS__ = [];
      window.acquireVsCodeApi = () => ({ getState: () => ({ activeView: 'training', composerLanguage: language }),
        setState: () => undefined, postMessage: message => window.__TRAINER_E2E_HOST_ACTIONS__.push(message) });
    }, { bootstrap, language });
    await page.goto('/');
    await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
      .some(message => message.type === 'request/bootstrap'))).toBe(true);
    await page.evaluate(data => window.postMessage({ type: 'bootstrap', payload: data }, location.origin), bootstrap);
    await expect(page.locator('#root[data-trainer-app-ready=true]')).toBeVisible();
  }
  await page.evaluate(() => window.postMessage({ type: 'ui/restoreView', payload: {
    activeView: 'training', trainingRestoreTarget: 'scenario_lab', scenarioLabId: 'restored-scenario',
  } }, location.origin));
  return foreignAction;
}

for (const language of ['zh-CN', 'en-US']) {
  test(`missing bound restored scenario fields never borrow foreign Flash ${language}`, async ({ page }) => {
    await page.setViewportSize({ width: language === 'zh-CN' ? 460 : 340, height: 900 });
    const foreignAction = await seedRestoredScenario(page, language);
    const card = page.locator('[data-training-card-id]');
    await expect(card).toHaveAttribute('data-training-card-id', 'restored-scenario');
    await expect(card.locator('.template-activity-header')).toContainText('Scenario lab: FastAPI receipt');
    const details = page.locator('[data-training-card-details=true]');
    await details.locator(':scope > summary').click();
    await expect(details).toContainText(scenarioSummary);
    const observed = await card.evaluate(el => ({ text: el.innerText,
      body: el.querySelector('.template-focused-practice__phase')?.innerText,
      completion: el.querySelector('[data-training-card-fact=deliverable]')?.textContent,
      verification: el.querySelector('[data-training-card-fact=verify]')?.textContent }));
    await test.info().attach('actual-restored-scenario-fields', { body: JSON.stringify(observed, null, 2), contentType: 'application/json' });
    const shot = test.info().outputPath('restored-scenario-missing-fields.png');
    await page.screenshot({ path: shot, animations: 'disabled' });
    await test.info().attach('restored-scenario-missing-fields', { path: shot, contentType: 'image/png' });
    await expect(card.locator('.template-focused-practice__phase')).toContainText(scenarioSummary);
    await expect(card).not.toContainText('restore_history');
    await expect(card).not.toContainText('CONTROL_REVIEW_OUTCOME');
    await expect(card).not.toContainText(foreignAction);
    await expect(card).not.toContainText('foreign_workspace_id');
    await expect(details.locator('[data-training-card-fact=deliverable]')).toHaveText(scenarioSummary);
    await expect(details.locator('[data-training-card-fact=focus]')).toHaveText('FastAPI receipt');
    await page.getByRole('button', { name: language === 'zh-CN' ? '学习' : 'Learning', exact: true }).click();
    const next = page.locator('[data-template=NextAction]').filter({ has: page.locator('[data-action-intent=resume_training]') });
    await expect(next).toContainText('Scenario lab: FastAPI receipt');
    await next.locator('[data-action-intent=resume_training]').click();
    await expect(card).toHaveAttribute('data-training-card-id', 'restored-scenario');
    await expect(card).not.toContainText(foreignAction);
  });
}

for (const language of ['zh-CN', 'en-US']) {
  test(`bound missing title and focus use neutral defaults ${language}`, async ({ page }) => {
    await seed(page, language, true, 'blank-bound');
    const card = page.locator('[data-training-card-id]');
    await expect(card).toHaveAttribute('data-training-card-id', 'author-card');
    await expect(card.locator('.template-activity-header')).toContainText(language === 'zh-CN' ? '训练' : 'Training');
    await expect(card).not.toContainText('foreign_workspace_id');
    await expect(card).not.toContainText('OLD_AMBIENT_FOCUS');
    await expect(card).not.toContainText('UNBOUND_TITLE');
    await expect(card).toContainText('2/5');
  });
  for (const verificationSteps of [undefined, ['verify_FastAPI_receipt']]) {
    test(`bound local verification payload rejects foreign fields ${language}, ownChecks=${!!verificationSteps}`, async ({ page }) => {
      const foreignAction = await seedRestoredScenario(page, language, true, verificationSteps);
      const card = page.locator('[data-training-card-id]');
      await expect(card).toHaveAttribute('data-training-card-id', 'restored-scenario');
      await card.getByRole('button', { name: language === 'zh-CN' ? '验证当前文件' : 'Verify current file', exact: true }).click();
      await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.filter(message =>
        message.type === 'command/execute' && message.payload.commandId === 'trainer.evaluate.currentFile').length)).toBe(1);
      const posted = await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.find(message =>
        message.type === 'command/execute' && message.payload.commandId === 'trainer.evaluate.currentFile'));
      expect(posted.payload.payload).toMatchObject({ source: 'training', cardId: 'restored-scenario',
        cardTitle: 'Scenario lab: FastAPI receipt', acceptanceCriteria: verificationSteps ?? [],
        learnerDeliverables: [], expectedSymbols: [], filesToTouch: [] });
      expect(JSON.stringify(posted)).not.toContain(foreignAction);
      expect(JSON.stringify(posted)).not.toContain('foreign_workspace_id');
      await expect(card).toHaveAttribute('data-training-card-id', 'restored-scenario');
      await test.info().attach('actual-local-verify-payload', { body: JSON.stringify(posted, null, 2), contentType: 'application/json' });
    });
  }
}

const linkLabels = {
  'zh-CN': ['训练', '成长'], 'en-US': ['Training', 'Growth'],
  'es-ES': ['Entrenamiento', 'Crecimiento'], 'fr-FR': ['Entraînement', 'Progression'],
  'de-DE': ['Training', 'Entwicklung'], 'ja-JP': ['訓練', '成長'],
  'ko-KR': ['훈련', '성장'], 'pt-BR': ['Treinamento', 'Crescimento'],
};
const continueCopy = {
  'zh-CN': '可以继续当前练习。', 'en-US': 'You can continue the current practice.',
  'es-ES': 'Puedes continuar con el ejercicio actual.', 'fr-FR': 'Vous pouvez continuer l’exercice en cours.',
  'de-DE': 'Du kannst die aktuelle Übung fortsetzen.', 'ja-JP': '現在の練習を続けられます。',
  'ko-KR': '현재 연습을 계속할 수 있어요.', 'pt-BR': 'Você pode continuar o exercício atual.',
};
for (const language of Object.keys(continueCopy)) {
  test(`current recovered practice note and independent Learning links ${language}`, async ({ page }) => {
    await page.setViewportSize({ width: 340, height: 820 });
    await seed(page, language, true);
    await page.locator('[data-testid=trainer-view-nav-plan]').click();
    const primary = page.locator('[data-action-intent=resume_training]');
    await expect(primary).toBeEnabled();
    await expect(page.locator('[data-plan-leftover-note]')).toHaveText(continueCopy[language]);
    const links = page.locator('[data-learning-navigation=practice-growth]');
    await expect(links.getByRole('button')).toHaveCount(2);
    const practice = links.locator('[data-learning-link=training]');
    const growth = links.locator('[data-learning-link=progress]');
    await expect(practice).toHaveAccessibleName(linkLabels[language][0]);
    await expect(growth).toHaveAccessibleName(linkLabels[language][1]);
    const bounds = await links.evaluate(el => {
      const [first, second] = Array.from(el.querySelectorAll('button')).map(button => button.getBoundingClientRect());
      return { gap: second.x - first.right, sameRow: Math.abs(second.y - first.y) < 1,
        display: getComputedStyle(el).display, scrollWidth: el.scrollWidth, width: el.clientWidth };
    });
    expect(bounds.display).toBe('flex'); expect(bounds.sameRow).toBe(true); expect(bounds.gap).toBeGreaterThanOrEqual(11.5);
    expect(bounds.scrollWidth).toBeLessThanOrEqual(bounds.width);
    if (language === 'zh-CN' || language === 'en-US') {
      const shot = test.info().outputPath('current-practice-note-and-links.png');
      await page.screenshot({ path: shot, animations: 'disabled' });
      await test.info().attach('current-practice-note-and-links', { path: shot, contentType: 'image/png' });
    }
    await practice.click();
    await expect(page.locator('[data-training-card-id]')).toHaveAttribute('data-training-card-id', 'author-card');
    await page.locator('[data-testid=trainer-view-nav-plan]').click();
    await growth.click();
    await expect(page.locator('[data-template=GrowthEvidence]')).toBeVisible();
  });
}

for (const blocked of ['stale', 'busy', 'return_pending', 'no_live_card']) {
  test(`Learning note cannot claim practice readiness when ${blocked}`, async ({ page }) => {
    await seed(page, 'en-US', true, blocked === 'no_live_card' ? 'stale' : 'matching');
    await page.evaluate(blocked => {
      if (blocked === 'stale') window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'state/syncStatus', payload: { generation: 1, status: 'stale' } });
      if (blocked === 'busy') window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'stream/start', payload: { messageId: 'bound-practice-busy' } });
      if (blocked === 'return_pending') {
        const current = window.__TRAINER_BOOTSTRAP__;
        const workspaceId = 'workspace-authored-card';
        const card = { cardId: 'author-card', title: 'Current bound return', type: 'practice', status: 'active', learningPhase: 'return' };
        window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: { ...current, plan: null,
          sessionHistoryRestored: true, planRuntimeStatus: { recovered: true, currentStep: '', reviewPoints: [] },
          memory: { ...current.memory, workspace: { ...current.memory.workspace, workspaceId,
            liveTrainingSelection: { workspaceId, cardId: card.cardId, selectedAt: '2026-10-09T00:00:00Z' } } },
          workspaceTrainingState: { workspaceId, selectedCardId: card.cardId, selectedCardType: 'practice',
            selectedCardTitle: card.title, selectedCardStatus: 'active', trainingCardCandidates: [card],
            activeTrainingCardRouting: { selectedCardId: card.cardId, selectedCard: card } },
        } });
      }
    }, blocked);
    await page.locator('[data-testid=trainer-view-nav-plan]').click();
    await expect(page.locator('[data-plan-leftover-note]')).not.toHaveText(continueCopy['en-US']);
  });
}

for (const language of ['zh-CN', 'en-US']) {
  test(`restored scenario without authored summary has no control-enum task ${language}`, async ({ page }) => {
    const foreignAction = await seedRestoredScenario(page, language, false, undefined, null);
    const card = page.locator('[data-training-card-id=restored-scenario]');
    await expect(card).toBeVisible();
    await expect(card.locator('[data-training-card-details=true]')).toHaveCount(0);
    await expect(card).not.toContainText('restore_history');
    await expect(card).not.toContainText('CONTROL_REVIEW_OUTCOME');
    await expect(card).not.toContainText(foreignAction);
    await expect(card).not.toContainText('foreign_workspace_id');
    await expect(card.getByRole('heading', { name: language === 'zh-CN' ? '还没有明确的训练卡片' : 'No training card yet', exact: true })).toBeVisible();
  });
}

const remoteScope = { generation: 1, revision: 1, baseRevision: 0,
  messageId: 'remote-fixture-1', workspaceId: 'workspace-restored-scenario', sessionId: 'remote-fixture-session' };
async function seedRemoteScenario(page, language) {
  await seedRestoredScenario(page, language, true);
  await page.evaluate(({ scope, summary }) => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const oldFlash = { cardId: 'foreign-flash', title: 'Foreign live Flash', type: 'flash', status: 'active' };
    const next = { ...current, sessionLabel: scope.sessionId, plan: null, sessionHistoryRestored: true,
      planRuntimeStatus: { recovered: true, currentStep: '', reviewPoints: [] },
      workspace: { ...current.workspace, isRemoteWorkspace: true, remoteName: 'fixture-ssh' },
      memory: { ...current.memory, workspace: { ...current.memory.workspace, workspaceId: scope.workspaceId,
        liveTrainingSelection: { workspaceId: scope.workspaceId, cardId: oldFlash.cardId, selectedAt: '2026-10-09T00:00:00Z' },
        latestPlanRuntime: undefined, latestTrainingHandoff: undefined, latestTrainingNextHop: undefined } },
      workspaceTrainingState: { workspaceId: scope.workspaceId, selectedCardId: oldFlash.cardId,
        selectedCardTitle: oldFlash.title, selectedCardType: 'flash', selectedCardStatus: 'active',
        trainingCardCandidates: [oldFlash], activeTrainingCardRouting: { selectedCardId: oldFlash.cardId, selectedCard: oldFlash },
        scenarioLab: { id: 'restored-scenario', title: 'Scenario lab: FastAPI receipt', summary,
          status: 'ready', lastAction: 'restore_history', focusArea: 'FastAPI receipt' } } };
    window.__TRAINER_E2E_REMOTE_BOOTSTRAP__ = next;
    window.postMessage({ type: 'bootstrap', sync: scope, payload: next }, location.origin);
    window.postMessage({ type: 'ui/restoreView', payload: { activeView: 'training',
      trainingRestoreTarget: 'scenario_lab', scenarioLabId: 'restored-scenario' } }, location.origin);
  }, { scope: remoteScope, summary: scenarioSummary });
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.some(message =>
    message.type === 'state/ack' && message.payload.status === 'applied' && message.payload.messageId === 'remote-fixture-1'))).toBe(true);
  await expect(page.locator('[data-training-card-id]')).toHaveAttribute('data-training-card-id', 'restored-scenario');
}
async function remoteClick(page) {
  await page.locator('[data-training-card-id]').getByRole('button', { name: /fixture-ssh/ }).click();
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.filter(message =>
    message.type === 'command/execute' && message.payload.commandId === 'trainer.remote.verifyActiveFile').length)).toBeGreaterThan(0);
  return page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.filter(message =>
    message.type === 'command/execute' && message.payload.commandId === 'trainer.remote.verifyActiveFile').at(-1));
}
async function remoteEvent(page, type, cardId, operation, extra = {}) {
  const payload = type === 'started' ? { sessionId: 'companion-run', cardId, spec: { executable: 'python3', args: ['check.py'] } }
    : type === 'stream' ? { sessionId: 'companion-run', cardId, stream: 'stdout', text: 'current_stdout' }
      : { sessionId: 'companion-run', cardId, state: 'completed', exitCode: 0, passed: true, summary: 'current_result' };
  await page.evaluate(message => window.postMessage(message, location.origin), {
    type: `remoteVerification/${type}`, payload: { ...payload, ...extra }, operation,
  });
}
const mismatchCopy = {
  'zh-CN': '这张练习与当前任务不一致。验证没有启动；请重新打开当前练习。',
  'en-US': 'This practice no longer matches the current task. Verification was not started; reopen the current practice.',
  'es-ES': 'Esta práctica ya no coincide con la tarea actual. La verificación no se inició; vuelve a abrir la práctica actual.',
  'fr-FR': 'Cet exercice ne correspond plus à la tâche actuelle. La vérification n’a pas démarré ; rouvrez l’exercice actuel.',
  'de-DE': 'Diese Übung entspricht nicht mehr der aktuellen Aufgabe. Die Verifizierung wurde nicht gestartet; öffne die aktuelle Übung erneut.',
  'ja-JP': 'この練習は現在のタスクと一致しません。検証は開始されていません。現在の練習を開き直してください。',
  'ko-KR': '이 연습은 현재 과제와 일치하지 않습니다. 검증이 시작되지 않았습니다. 현재 연습을 다시 여세요.',
  'pt-BR': 'Esta prática não corresponde mais à tarefa atual. A verificação não foi iniciada; reabra a prática atual.',
};
for (const language of Object.keys(mismatchCopy)) {
  test(`remote mismatch clears only current request with Training notice ${language}`, async ({ page }) => {
    await page.setViewportSize({ width: language === 'zh-CN' ? 460 : 340, height: 900 });
    await seedRemoteScenario(page, language);
    const posted = await remoteClick(page);
    expect(posted.payload.payload).toEqual({ expectedCardId: 'restored-scenario' });
    expect(posted.operation.targetId).toBe('restored-scenario');
    await page.evaluate(operation => window.postMessage({ type: 'operation/status', operation,
      payload: { tone: 'error', message: '[[trainer-training-verification-target-mismatch]]' } }, location.origin), posted.operation);
    const card = page.locator('[data-training-card-id=restored-scenario]');
    await expect(card.getByRole('button', { name: /fixture-ssh/ })).toBeEnabled();
    await expect(page.locator('.template-global-state')).toContainText(mismatchCopy[language]);
    await expect(page.locator('[data-template=VerificationResult]')).toHaveCount(0);
    await expect(page.locator('#root')).not.toContainText('[[trainer-');
    if (language === 'zh-CN' || language === 'en-US') {
      await page.locator('.template-global-state').scrollIntoViewIfNeeded();
      const shot = test.info().outputPath('remote-mismatch-current-training.png');
      await page.screenshot({ path: shot, animations: 'disabled' });
      await test.info().attach('remote-mismatch-current-training', { path: shot, contentType: 'image/png' });
    }
    await page.locator('[data-testid=trainer-view-nav-coach]').click();
    await expect(page.locator('.template-global-state')).toHaveCount(0);
    await expect(page.locator('[data-surface=coach]')).not.toContainText(mismatchCopy[language]);
  });
}

test('remote decoder ignores foreign and unbound events but shows current authoritative result', async ({ page }) => {
  await seedRemoteScenario(page, 'en-US');
  const posted = await remoteClick(page);
  for (const cardId of ['foreign-flash', undefined]) {
    await remoteEvent(page, 'started', cardId, posted.operation);
    await remoteEvent(page, 'stream', cardId, posted.operation, { text: 'FOREIGN_STREAM' });
    await remoteEvent(page, 'finished', cardId, posted.operation, { summary: 'FOREIGN_RESULT' });
  }
  const card = page.locator('[data-training-card-id=restored-scenario]');
  await expect(card.getByRole('button', { name: /fixture-ssh/ })).toBeDisabled();
  await expect(card).not.toContainText('FOREIGN_STREAM'); await expect(card).not.toContainText('FOREIGN_RESULT');
  for (const operation of [{ ...posted.operation, requestId: 'older-request' },
    { ...posted.operation, generation: 0 }, { ...posted.operation, workspaceId: 'foreign-workspace' },
    { ...posted.operation, sessionId: 'foreign-session' },
    { ...posted.operation, commandId: 'trainer.remote.verifyCancel' }]) {
    await remoteEvent(page, 'finished', 'restored-scenario', operation, { summary: 'FOREIGN_OPERATION_RESULT' });
  }
  await expect(card).not.toContainText('FOREIGN_OPERATION_RESULT');
  await expect(card.getByRole('button', { name: /fixture-ssh/ })).toBeDisabled();
  await remoteEvent(page, 'started', 'restored-scenario', posted.operation);
  await remoteEvent(page, 'stream', 'restored-scenario', posted.operation);
  await remoteEvent(page, 'finished', 'restored-scenario', posted.operation);
  await expect(card.locator('[data-template=VerificationResult]')).toContainText('current_result');
  await expect(card.getByRole('button', { name: /fixture-ssh/ })).toBeEnabled();
  await expect(card.locator('[data-template=VerificationResult]')).toContainText('passed');
  await card.locator('[data-template=VerificationResult] details > summary').click();
  await expect(card.locator('.remote-verify-panel__output')).toHaveText('current_stdout');
});

test('remote A-B-A ignores old same-card events and failure without cancelling an execution', async ({ page }) => {
  await seedRemoteScenario(page, 'en-US');
  const first = await remoteClick(page);
  await remoteEvent(page, 'started', 'restored-scenario', first.operation);
  for (const [revision, cardId] of [[2, 'scenario-B'], [3, 'restored-scenario']]) {
    await page.evaluate(({ revision, cardId, scope, summary }) => {
      const original = window.__TRAINER_E2E_REMOTE_BOOTSTRAP__;
      window.postMessage({ type: 'bootstrap', sync: { ...scope, revision, baseRevision: 0, messageId: `remote-fixture-${revision}` },
        payload: { ...original, workspaceTrainingState: { ...original.workspaceTrainingState,
          scenarioLab: { id: cardId, title: `Scenario ${cardId}`, summary, status: 'ready', focusArea: 'FastAPI receipt' } } } }, location.origin);
      window.postMessage({ type: 'ui/restoreView', payload: { activeView: 'training', trainingRestoreTarget: 'scenario_lab', scenarioLabId: cardId } }, location.origin);
    }, { revision, cardId, scope: remoteScope, summary: scenarioSummary });
    await expect(page.locator('[data-training-card-id]')).toHaveAttribute('data-training-card-id', cardId);
    await expect(page.locator('[data-training-card-id]').getByRole('button', { name: /fixture-ssh/ })).toBeEnabled();
  }
  const second = await remoteClick(page);
  expect(second.operation.requestId).not.toBe(first.operation.requestId);
  await remoteEvent(page, 'started', 'restored-scenario', first.operation);
  await remoteEvent(page, 'stream', 'restored-scenario', first.operation, { text: 'OLD_A_STREAM' });
  await remoteEvent(page, 'finished', 'restored-scenario', first.operation, { summary: 'OLD_A_RESULT' });
  await page.evaluate(operation => window.postMessage({ type: 'operation/status', operation,
    payload: { tone: 'error', message: '[[trainer-training-verification-target-mismatch]]' } }, location.origin), first.operation);
  const card = page.locator('[data-training-card-id=restored-scenario]');
  await expect(card.getByRole('button', { name: /fixture-ssh/ })).toBeDisabled();
  await expect(card).not.toContainText('OLD_A_STREAM'); await expect(card).not.toContainText('OLD_A_RESULT');
  await expect(card).not.toContainText(mismatchCopy['en-US']);
  await page.evaluate(operation => window.postMessage({ type: 'operation/status', operation,
    payload: { tone: 'error', message: 'preflight command failed' } }, location.origin), second.operation);
  await expect(card.getByRole('button', { name: /fixture-ssh/ })).toBeEnabled();
  expect(await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.filter(message =>
    message.type === 'command/execute' && message.payload.commandId === 'trainer.remote.verifyCancel'))).toEqual([]);
  await expect(card.locator('[data-template=VerificationResult]')).toHaveCount(0);
});

test('palette remote result still requires exact displayed card and current host scope', async ({ page }) => {
  await seedRemoteScenario(page, 'en-US');
  await page.evaluate(scope => window.postMessage({ type: 'remoteVerification/finished', scope: { ...scope, generation: 0 },
    payload: { sessionId: 'old-scope', cardId: 'restored-scenario', state: 'completed', exitCode: 0, passed: true, summary: 'OLD_SCOPE_RESULT' } }, location.origin), remoteScope);
  await remoteEvent(page, 'finished', undefined, undefined, { summary: 'UNBOUND_PALETTE_RESULT' });
  const card = page.locator('[data-training-card-id=restored-scenario]');
  await expect(card).not.toContainText('OLD_SCOPE_RESULT'); await expect(card).not.toContainText('UNBOUND_PALETTE_RESULT');
  await remoteEvent(page, 'finished', 'restored-scenario', undefined, { summary: 'CURRENT_PALETTE_RESULT' });
  await expect(card.locator('[data-template=VerificationResult]')).toContainText('CURRENT_PALETTE_RESULT');
});
