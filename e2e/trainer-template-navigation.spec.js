const { test, expect } = require('playwright/test');
const { openSettingsCategory } = require('./template-navigation');
const { closeLearningDrawer, openLearningDrawer } = require('./workbench-navigation');

test('Learning reads saved flash prompts and candidate criteria from sidecar records', async ({ page }) => {
  const workspaceId = 'learning-sidecar-preview';
  const current = {
    card_id: 'saved-flash', card_type: 'flash', title: 'Value targets',
    status: 'active', review_state: 'saved', learning_phase: 'try', answer_mode: 'text',
    question: 'What value should follow a true terminal state?',
  };
  const candidate = {
    card_id: 'pending-flash', card_type: 'flash', title: 'Model inputs',
    status: 'candidate', review_state: 'pending', question: 'What goes into the dynamics model?',
    answer_mode: 'text', acceptance_criteria: ['Name the current latent state.', 'Name the executed action.'],
  };
  await page.addInitScript((id) => sessionStorage.setItem('trainer:webview:preview:workspace-id', id), workspaceId);
  await page.route('http://127.0.0.1:34907/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/session/start') return route.fulfill({ json: { session_id: 'learning-session' } });
    if (path === '/memory/summary') return route.fulfill({ json: { memory: {
      workspace: {
        workspace_id: workspaceId, selected_card_id: current.card_id,
        selected_card_status: 'active', selected_card_title: current.title, latest_training_submode: 'flash',
        live_training_selection: { workspace_id: workspaceId, card_id: current.card_id, selected_at: '2026-10-01T00:00:00Z' },
      },
      training_card_candidates: [current, candidate],
      active_training_card_routing: { selected_card_id: current.card_id, selected_card: current },
    } } });
    return route.fulfill({ json: { status: 'ok' } });
  });
  await page.setViewportSize({ width: 340, height: 820 });
  await page.goto('/vscode-preview.html?view=training&live=1&lang=en-US&sidecarPort=34907');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  // The legacy training route opens the learning drawer over the conversation;
  // the practice card itself lives inline in the message flow.
  await closeLearningDrawer(page);
  const practice = page.locator('[data-template=FocusedPractice]');
  await expect(practice.getByText(current.question, { exact: true })).toBeVisible();
  // Product contract v2.1: inline conversation stays calm without card-library CRUD chrome
  // and routes answers through the single bottom composer.
  await expect(page.locator('[data-training-library]')).toHaveCount(0);
  await expect(page.locator('[data-inline-practice-answer="true"] textarea')).toHaveCount(0);
  await expect(page.locator('#coach-composer')).toBeVisible();
});

// Deterministic fixtures validate presentation and navigation, not real evidence.
for (const width of [340, 420, 460]) {
  for (const theme of ['dark', 'light']) {
    for (const language of ['zh-CN', 'en-US']) {
      test(`two stable destinations and composer ownership: ${width}/${theme}/${language}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 800 });
        const labels = language === 'zh-CN' ? ['对话', '资料'] : ['Chat', 'Resources'];
        for (const route of ['coach', 'plan', 'resources', 'training', 'progress', 'settings']) {
          await page.goto(`/vscode-preview.html?view=${route}&scenario=ready&connection=connected&theme=${theme}&lang=${language}`);
          await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
          const nav = page.locator('.app-shell-nav');
          await expect(nav.getByRole('button')).toHaveText(labels);
          const ownsComposer = route !== 'settings';
          await expect(page.locator('#coach-composer')).toHaveCount(ownsComposer ? 1 : 0);
          const current = nav.locator('[aria-current="page"]');
          if (route === 'settings') await expect(current).toHaveCount(0);
          // Resources keeps its own destination; every legacy learning route
          // resolves to Chat with the learning drawer open.
          else await expect(current).toHaveAttribute(
            'data-testid',
            route === 'resources' ? 'trainer-view-nav-resources' : 'trainer-view-nav-coach',
          );
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
          // A legacy learning route opens the learning drawer. It is modal, so
          // its backdrop covers the header utilities until it is closed.
          if (['plan', 'training', 'progress'].includes(route)) {
            await expect(page.locator('[data-template="LearningDrawer"]')).toBeVisible();
            await closeLearningDrawer(page);
          }
          await page.getByTestId('trainer-history-toggle').click();
          await expect(page.locator('.app-shell-overlay__panel')).toBeVisible();
          await page.locator('.app-shell-overlay__backdrop').click({ position: { x: 2, y: 2 } });
          await expect(page.locator('.app-shell-overlay')).toHaveCount(0);
        }
      });
    }
  }
}

test('surface switches retain the Coach draft and resource search without sharing activity input', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=coach&scenario=ready&connection=connected&lang=en-US');
  await expect(page.locator('#coach-composer')).toBeVisible();
  await page.locator('#coach-composer').fill('Keep my question while I read');
  await page.getByTestId('trainer-view-nav-resources').click();
  await expect(page.locator('[data-surface=resources] input[type=search]')).toHaveCount(1);
  await page.locator('#coach-composer').fill('/search boundary');
  await page.locator('#coach-composer').press('Enter');
  const search = page.locator('[data-clear-resource-search]');
  await expect(search).toContainText('boundary');
  await expect(page.locator('[data-surface=resources] input[type=search]')).toHaveValue('boundary');
  await openLearningDrawer(page, 'goal');
  // The drawer is modal: close it before using the nav.
  await closeLearningDrawer(page);
  await page.getByTestId('trainer-view-nav-resources').click();
  await expect(search).toContainText('boundary');
  await page.getByTestId('trainer-view-nav-coach').click();
  await expect(page.locator('#coach-composer')).toHaveValue('Keep my question while I read');
  // Learning is a drawer over Chat, not a surface of its own: the composer
  // and the drawer survive a legacy route restore unchanged.
  await openLearningDrawer(page, 'goal');
  const learning = page.locator('[data-template="LearningDrawer"]');
  await page.locator('#coach-composer').evaluate((input) => input.setAttribute('data-same-learning-input', 'true'));
  await learning.evaluate((surface) => surface.setAttribute('data-same-learning-surface', 'true'));
  await page.evaluate(() => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'ui/restoreView', payload: { activeView: 'training' } }));
  await expect(page.locator('#coach-composer')).toHaveAttribute('data-same-learning-input', 'true');
  await expect(learning).toHaveAttribute('data-same-learning-surface', 'true');
  await expect(page.locator('[data-learning-section="practice"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const workspaceId = current.memory.workspace?.workspaceId ?? 'workspace-template-nav';
    const card = {
      cardId: 'card-template-nav', type: 'practice', title: 'Boundary check card',
      status: 'active', learningPhase: 'try', learningFamily: 'concept',
      problemStatement: 'State one precise rule before expanding the topic.',
      deliverable: 'One precise rule', learnerDeliverables: ['Explain the invariant'],
      verificationSteps: ['Compare against the written rule'],
      targetSkill: 'Boundaries', focusArea: 'Boundaries',
    };
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: {
      ...current,
      plan: null,
      planRuntimeStatus: { recovered: true, currentStep: '', reviewPoints: [] },
      memory: { ...current.memory, workspace: { ...current.memory.workspace,
        workspaceId,
        liveTrainingSelection: { workspaceId, cardId: card.cardId, selectedAt: '2026-10-02T03:00:00Z' } } },
      workspaceTrainingState: { ...current.workspaceTrainingState, workspaceId,
        selectedCardId: card.cardId, selectedCardType: 'practice', selectedCardTitle: card.title,
        selectedCardStatus: 'active', trainingCardCandidates: [card],
        activeTrainingCardRouting: { selectedCardId: card.cardId, selectedCard: card, selectionScore: 100 } },
    } });
  });
  // Single-composer sovereignty: no second competing textarea inside the card.
  const cardDetails = page.locator('[data-training-card-details]');
  await expect(cardDetails).toHaveCount(1);
  await expect(cardDetails.locator(':scope > summary')).toContainText(/任务详情|Task details/);
  await expect(cardDetails).not.toHaveAttribute('open', '');
  await expect(page.locator('[data-inline-practice-answer="true"] textarea')).toHaveCount(0);
  await expect(page.locator('#coach-composer')).toBeVisible();
  await expect(page.locator('textarea:visible')).toHaveCount(1);
  // The drawer is modal: close it before using the nav.
  await closeLearningDrawer(page);
  await page.getByTestId('trainer-view-nav-coach').click();
  await expect(page.locator('#coach-composer')).toHaveValue('Keep my question while I read');
  const toggle = page.locator('[data-inline-practice-toggle="true"]');
  await toggle.click();
  await expect(page.locator('[data-inline-practice-collapsed="true"]')).toBeVisible();
  await expect(page.locator('#coach-composer')).toHaveValue('Keep my question while I read');
});

test('reload restores the same session draft and reading position; history returns keyboard focus', async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 800 });
  await page.goto('/vscode-preview.html?view=coach&lang=en-US&connection=connected&run=scroll-restore');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const bootstrap = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  const payload = { ...bootstrap, sessionLabel: 'scroll-session', sessionHistoryRestored: true,
    conversation: Array.from({ length: 60 }, (_, i) => ({ id: `reading-${i}`, role: 'assistant', author: 'Trainer', timestamp: '10:00', body: `Reading paragraph ${i}.\n\nKeep the exact reading position while switching surfaces and reloading.` })) };
  await page.addInitScript(data => {
    window.acquireVsCodeApi = () => ({
      getState: () => JSON.parse(localStorage.getItem('trainer-ux-scroll-state') || '{"activeView":"coach","composerLanguage":"en-US"}'),
      setState: value => localStorage.setItem('trainer-ux-scroll-state', JSON.stringify(value)),
      postMessage: message => { if (message.type === 'request/bootstrap') setTimeout(() => window.postMessage({ type: 'bootstrap', payload: data }, location.origin), 0); },
    });
  }, payload);
  await page.goto('/');
  const input = page.locator('#coach-composer');
  await expect(input).toBeVisible();
  await expect(page.locator('.coach-conversation-view__item')).toHaveCount(60);
  await input.fill('Unsent question in this session');
  const content = page.locator('[data-surface=coach] .coach-conversation-view__list');
  await content.hover();
  await page.mouse.wheel(0, -1500);
  await expect.poll(() => content.evaluate(node => node.scrollTop < node.scrollHeight - node.clientHeight - 100)).toBe(true);
  // Wheel scrolling runs on the compositor. Capture the settled reading
  // position, rather than an intermediate frame of the same wheel gesture.
  const saved = await content.evaluate(async node => {
    let previous = node.scrollTop;
    let stableFrames = 0;
    for (let frame = 0; frame < 120; frame += 1) {
      await new Promise(resolve => requestAnimationFrame(resolve));
      const current = node.scrollTop;
      stableFrames = current === previous ? stableFrames + 1 : 0;
      previous = current;
      if (stableFrames >= 4) return current;
    }
    throw new Error('Reading position did not settle after the wheel gesture');
  });
  // Learning is a drawer over Chat now: switching to it and back must keep
  // the thread's reading position.
  await openLearningDrawer(page, 'goal');
  await closeLearningDrawer(page);
  await expect.poll(() => content.evaluate(node => node.scrollTop)).toBeCloseTo(saved, 0);
  await page.reload();
  await expect(input).toHaveValue('Unsent question in this session');
  await expect.poll(() => content.evaluate(node => node.scrollTop)).toBeCloseTo(saved, 0);
  const history = page.getByTestId('trainer-history-toggle');
  await history.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('textbox')).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(dialog.locator(':focus')).toHaveCount(1);
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(history).toBeFocused();
  // Reload immediately, before the draft persistence debounce can expire.
  await input.fill('Last keystrokes survive an immediate reload');
  await page.reload();
  await expect(input).toHaveValue('Last keystrokes survive an immediate reload');
});

for (const width of [340, 420, 460]) {
  for (const theme of ['dark', 'light']) {
    for (const language of ['zh-CN', 'en-US']) {
      test(`Settings details have a usable reading pane: ${width}/${theme}/${language}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 800 });
        await page.goto(`/vscode-preview.html?view=settings&scenario=ready&connection=connected&theme=${theme}&lang=${language}`);
        for (const category of ['connection', 'teaching', 'workspace', 'preferences']) {
          await openSettingsCategory(page, category);
          const detail = page.locator(`[data-settings-detail=${category}]`);
          await expect(detail).toBeVisible();
          const pane = detail.locator('.settings-sheet__pane');
          if (category === 'connection') {
            // A saved connection initially shows only its compact identity.
            // Enter the editor to check the actual connection reading pane.
            await pane.getByRole('button', { name: /^(Edit configuration|编辑配置)$/ }).click();
            await expect(pane.locator('form.settings-sheet__minor-body')).toBeVisible();
          }
          expect(await pane.evaluate(node => node.clientHeight)).toBeGreaterThan(120);
          const box = await pane.boundingBox();
          expect(box.y).toBeLessThan(700);
          const surface = page.locator('[data-surface=settings] .settings-pane');
          expect(await surface.evaluate(node => node.clientHeight)).toBeGreaterThan(600);
          await detail.locator('.template-activity-header > .template-back').click();
        }
      });
    }
  }
}
