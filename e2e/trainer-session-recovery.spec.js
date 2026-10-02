const { test, expect } = require("playwright/test");

test("an English recovery step does not hide its matching formal plan in Chinese", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=plan&lang=zh-CN&connection=connected&run=plan-identity-language");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const step = "Resolve failing checks first: ruff.";
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: "bootstrap", payload: {
      ...current, sessionHistoryRestored: true,
      plan: { ...current.plan, id: "plan-language-identity", title: "列表与元组", currentStep: step },
      planRuntimeStatus: { recovered: true, currentStep: step, reviewPoints: [] },
      memory: { ...current.memory, workspace: { ...current.memory.workspace,
        latestPlanRuntime: { workspaceId: current.memory.workspace.workspaceId,
          planId: "plan-language-identity", currentStep: step, revision: 11, resumeState: "in_progress" },
      } },
    } });
  });
  await expect(page.getByText("这是此工作区里存下的旧痕迹，不是当前正式计划。", { exact: true })).toHaveCount(0);
  await expect(page.locator('[data-plan-stage-disclosure="true"]')).toBeVisible();
});

test("compact Plan keeps its stages reachable from a dedicated disclosure", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=plan&lang=zh-CN&connection=connected&run=compact-stages");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: "bootstrap", payload: {
      ...current, sessionHistoryRestored: true,
      plan: { id: "plan-stage-disclosure", title: "列表与元组", frozen: false, cadence: "每天20分钟",
        summary: "先验证，再实现，再覆盖边界", currentStageId: "stage-1", currentStep: "运行可变性验证",
        stages: [
          { id: "stage-1", title: "验证元组内列表", status: "active", objective: "运行两段代码" },
          { id: "stage-2", title: "实现嵌套求和", status: "queued", objective: "完成函数" },
          { id: "stage-3", title: "覆盖异常边界", status: "queued", objective: "添加断言" },
        ] },
      planRuntimeStatus: { recovered: false, currentStep: "运行可变性验证", reviewPoints: [] },
    } });
  });
  const stages = page.locator('[data-plan-stage-disclosure="true"]');
  await expect(stages).toBeVisible();
  await stages.locator('summary').click();
  await expect(stages.getByText('验证元组内列表', { exact: true })).toBeVisible();
  await expect(stages.getByText('实现嵌套求和', { exact: true })).toBeVisible();
  await expect(stages.getByText('覆盖异常边界', { exact: true })).toBeVisible();
  await expect(stages.locator('[data-stage-status]')).toHaveCount(3);
});

test("restored workspace settings show saved custom skills without a formal plan", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=settings&lang=en-US&connection=connected&run=restored-skills");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: "bootstrap", payload: {
      ...current, sessionHistoryRestored: true, plan: null,
      planRuntimeStatus: { recovered: true, currentStep: "", reviewPoints: [] },
      memory: { ...current.memory, workspace: {
        ...current.memory.workspace,
        coachDefaults: { ...current.memory.workspace.coachDefaults, customSkills: [{
          id: "custom-restored-check", trigger: "$restored-check", title: "Restored Python check",
          detail: "Review a submitted function", prompt: "Find one error and give a validation command.", keywords: [],
        }] },
      } },
    } });
  });
  await page.locator('.settings-nav').getByRole('tab').nth(2).click();
  await expect(page.getByText('$restored-check', { exact: true })).toBeVisible();
  await expect(page.getByText('Restored Python check', { exact: true })).toBeVisible();
});

test("restored conversation and uploaded resources remain visible without a formal plan", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=coach&lang=en-US&connection=connected&run=restored-history");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const payload = {
      ...current,
      sessionHistoryRestored: true,
      plan: null,
      planRuntimeStatus: { recovered: true, currentStep: "", reviewPoints: [] },
      conversation: [{ id: "durable-message", role: "user", author: "You",
        body: "My recorded list and tuple question", timestamp: "10:00" }],
      resources: [
        { id: "durable-upload", title: "Uploaded Python notes", kind: "markdown",
          status: "ready", sandboxPath: "/sandbox/sources/notes.md", indexState: "indexed" },
        { id: "stale-resource", title: "Unconfirmed old resource", kind: "markdown", status: "ready" },
      ],
      resourceSearch: { query: "qzx987nomatch", hits: [], total: 0, rankingStrategy: "lexical_first" },
    };
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: "bootstrap", payload });
  });
  await expect(page.getByText("My recorded list and tuple question", { exact: true })).toBeVisible();
  await page.getByTestId("trainer-view-nav-resources").click();
  await expect(page.getByText("Uploaded Python notes", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Unconfirmed old resource", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/qzx987nomatch/)).toHaveCount(0);
});

test("flash training shows the question before generic practice instructions", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=training&lang=en-US&connection=connected&run=flash-question");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const card = { cardId: "card-ui-training-1", type: "flash", title: "Tuple mutability",
      status: "active", learningPhase: "try", question: "Can a list inside a tuple still change?",
      problemStatement: "State one precise rule before expanding the topic.",
      deliverable: "An explanation comparing two operations",
      learnerDeliverables: ["Explain reference mutability"],
      targetSkill: "Python tuple references", focusArea: "Python tuples", answerMode: "text" };
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: "bootstrap", payload: {
      ...current,
      plan: null, planRuntimeStatus: { recovered: true, currentStep: "", reviewPoints: [] },
      memory: { ...current.memory, workspace: {
        ...current.memory.workspace,
        workspaceId: "workspace-independent-flash",
        liveTrainingSelection: { workspaceId: "workspace-independent-flash",
          cardId: card.cardId, selectedAt: "2026-10-02T03:00:00Z" },
      } },
      workspaceTrainingState: {
        ...current.workspaceTrainingState,
        workspaceId: "workspace-independent-flash",
        selectedCardId: card.cardId, selectedCardType: "flash", selectedCardTitle: card.title,
        selectedCardStatus: "active", trainingCardCandidates: [card],
        activeTrainingCardRouting: { selectedCardId: card.cardId, selectedCard: card, selectionScore: 100 },
      },
    } });
  });
  await expect(page.getByText("Can a list inside a tuple still change?", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tuple mutability", exact: true })).toBeVisible();
});

test("Chinese flash questions keep inline code identifiers visible", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=training&lang=zh-CN&connection=connected&run=flash-question");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const card = { cardId: "card-ui-training-1", type: "flash", title: "元组中嵌套列表的可变性边界",
      status: "active", learningPhase: "try", question: "给定 `pair = ([1, 2], 3)`，执行 `pair[0].append(4)` 与尝试 `pair[1] = 9` 各自的结果是什么？请说明为什么其中一条合法、另一条抛错。",
      problemStatement: "先说清一条规则再继续。",
      deliverable: "一段两条操作的运行结果对比说明，标注合法/异常及根因。",
      learnerDeliverables: ["解释引用对象的可变性。"],
      targetSkill: "Python 元组引用", focusArea: "Python 元组", answerMode: "text" };
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: "bootstrap", payload: {
      ...current,
      plan: null, planRuntimeStatus: { recovered: true, currentStep: "", reviewPoints: [] },
      memory: { ...current.memory, workspace: {
        ...current.memory.workspace,
        workspaceId: "workspace-independent-flash",
        liveTrainingSelection: { workspaceId: "workspace-independent-flash",
          cardId: card.cardId, selectedAt: "2026-10-02T03:00:00Z" },
      } },
      workspaceTrainingState: {
        ...current.workspaceTrainingState,
        workspaceId: "workspace-independent-flash",
        selectedCardId: card.cardId, selectedCardType: "flash", selectedCardTitle: card.title,
        selectedCardStatus: "active", trainingCardCandidates: [card],
        activeTrainingCardRouting: { selectedCardId: card.cardId, selectedCard: card, selectionScore: 100 },
      },
    } });
  });
  await expect(page.getByText("给定 `pair = ([1, 2], 3)`，执行 `pair[0].append(4)` 与尝试 `pair[1] = 9` 各自的结果是什么？请说明为什么其中一条合法、另一条抛错。", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "元组中嵌套列表的可变性边界", exact: true })).toBeVisible();
});


test("empty Plan honors an explicit Generate plan action", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=plan&lang=zh-CN&connection=connected&run=first-plan");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: "bootstrap", payload: {
      ...current, plan: null,
      providerConfig: { ...current.providerConfig, lastTestResult: {
        ...current.providerConfig.lastTestResult, ok: true, status: "connected",
        workspaceId: current.memory.workspace.workspaceId,
        profileId: current.providerConfig.profileId, checkedAt: new Date().toISOString(),
        providerName: current.providerConfig.name, baseUrl: current.providerConfig.baseUrl,
        model: current.providerConfig.model, protocol: current.providerConfig.protocol,
        toolsReady: true, toolProbeStatus: "verified", streamingReady: true,
        capabilityEvidence: [{ name: "tools", state: "verified", observed: true }],
      } },
      planRuntimeStatus: { recovered: false, currentStep: "", reviewPoints: [] },
      memory: { ...current.memory, evidenceQueue: { pending: [], adopted: [], rejected: [], deferred: [] },
        sandboxState: { ...current.memory.sandboxState, authority: {
          ...current.memory.sandboxState.authority, authorityScope: "trainer_sandbox",
          resourceWriteAllowed: true,
          resourceWriteEvidence: { operation: "write", scope: "trainer_sandbox", allowed: true },
        } },
        workspaceUnderstanding: undefined, workspace: { ...current.memory.workspace,
        latestPlanRuntime: undefined, activeThread: undefined, firstLookSummary: undefined,
      } },
      workspaceTrainingState: { workspaceId: current.memory.workspace.workspaceId, trainingCardCandidates: [] },
      evidenceQueue: { pending: [], adopted: [], rejected: [], deferred: [] },
    } });
  });
  await expect(page.getByText(/先启用一组可用连接/)).toHaveCount(0);
  await page.getByRole("button", { name: "生成计划", exact: true }).click();
  await expect(page.getByRole("button", { name: /计划.*生成/ })).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveValue(/生成正式计划/);
});

test("training generation keeps raw card JSON out of the conversation surface", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=training&lang=en-US&connection=connected&run=card-stream");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'stream/start', payload: { messageId: 'training_raw_card' } });
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'stream/chunk', payload: { messageId: 'training_raw_card', chunk: '{"title":"INTERNAL_CARD_JSON_123"' } });
  });
  await expect(page.getByText(/INTERNAL_CARD_JSON_123/)).toHaveCount(0);
  await expect(page.getByText(/Thinking through your prompt/).first()).toBeVisible();
  await page.evaluate(() => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
    type: 'stream/cancelled', payload: { messageId: 'training_raw_card' },
  }));
  await expect(page.getByRole("textbox")).toBeEnabled();
});

test("generated documents do not count as completed learning and old plan materials clear", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=plan&lang=zh-CN&connection=connected&run=material-progress");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: {
      ...current, sessionHistoryRestored: true,
      plan: { id: 'plan-material-progress', title: '列表和元组', frozen: false, cadence: '每天20分钟',
        currentStageId: 'stage-1', currentStep: '亲手运行验证', stages: [
          { id: 'stage-1', title: '验证引用', objective: '运行代码', status: 'active' },
          { id: 'stage-2', title: '已经验证的阶段', objective: '完成断言', status: 'done' },
        ] },
      planRuntimeStatus: { recovered: false, currentStep: '亲手运行验证', reviewPoints: [] },
      stageMaterials: { 'stage-1': ['study_guide', 'cheat_sheet', 'exercise_set', 'code_examples'].map((kind, i) => ({
        id: 'material-' + i, planStageId: 'stage-1', kind, title: '生成资料' + i, summary: '真正的学习内容',
        generationSource: i === 0 ? 'template' : 'model', content: '## 正文\n\n```python\nif True:\n    print(1)\n```',
      })) },
    } });
  });
  const stages = page.locator('[data-plan-stage-disclosure="true"]');
  await stages.locator('summary').click();
  const active = stages.locator('[data-plan-stage="stage-1"]');
  await expect(active.getByRole('img', { name: '阶段完成度 0%', exact: true })).toBeVisible();
  await expect(active.locator('[title="已生成资料 4/4"]')).toBeVisible();
  const done = stages.locator('[data-plan-stage="stage-2"]');
  await expect(done.getByRole('img', { name: '阶段完成度 100%', exact: true })).toBeVisible();
  await expect(done.locator('[title="已生成资料 0/4"]')).toBeVisible();
  await active.getByRole('button', { name: /生成资料0/ }).click();
  await expect(active.getByRole('heading', { name: '正文' })).toBeVisible();
  await expect(active.getByText('模板 · 可重新生成', { exact: true })).toBeVisible();
  await page.evaluate(() => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'state/patch', payload: {
    plan: { id: 'replacement-plan', title: '新的计划', currentStageId: 'stage-1',
      currentStep: '新的验证', stages: [{ id: 'stage-1', title: '新的阶段', status: 'active', objective: '新的验证' }] },
  } }));
  await expect(page.getByText('生成资料0', { exact: true })).toHaveCount(0);
});

test('restored trusted verification advances to reflection and carries its full record to Coach', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=training&lang=zh-CN&connection=connected&run=verified-reflection');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const reflection = 'tuple 位置赋值会抛 TypeError，append 修改内层 list。\nbefore: ([1, 2], 3)\nafter: ([1, 2, 4], 3)';
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const card = { cardId: 'card-ui-training-1', type: 'practice', title: '元组可变性验证',
      status: 'active', learningPhase: 'verify', problemStatement: '确认槽位赋值与内层对象修改的区别。',
      focusArea: 'Python 元组', targetSkill: '引用边界', filesToTouch: ['list_pairs.py'],
      verificationSteps: ['运行当前测试'], learnerDeliverables: ['解释操作结果'] };
    const payload = {
      ...current, plan: null, planRuntimeStatus: { recovered: true, currentStep: '', reviewPoints: [] },
      memory: { ...current.memory, workspace: { ...current.memory.workspace,
        workspaceId: 'verified-reflection-workspace', liveTrainingSelection: {
          workspaceId: 'verified-reflection-workspace', cardId: card.cardId, selectedAt: '2026-10-02T07:00:00Z' },
      } },
      workspaceTrainingState: { workspaceId: 'verified-reflection-workspace',
        selectedCardId: card.cardId, selectedCardType: 'practice', selectedCardTitle: card.title,
        selectedCardStatus: 'active', trainingCardCandidates: [card],
        activeTrainingCardRouting: { selectedCardId: card.cardId, selectedCard: card, selectionScore: 100 },
        latestTrainingHandoff: { handoffId: 'handoff-verified', cardId: card.cardId,
          candidateId: card.cardId, learningPhase: 'verify', handoffStatus: 'needs_reflection',
          returnMode: 'reflection_required', cardTitle: card.title },
        latestTrainingNextHop: { status: 'reflection_required', targetId: card.cardId },
      },
    };
    window.__TRAINER_BOOTSTRAP__ = payload;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload });
  });
  await expect(page.getByRole('textbox', { name: '记录当前训练复盘', exact: true })).toBeEditable();
  await page.evaluate((reflection) => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const state = current.workspaceTrainingState;
    const payload = {
      ...current, workspaceTrainingState: { ...state, selectedCardStatus: 'implemented',
        trainingCardCandidates: state.trainingCardCandidates.map(card => ({ ...card, status: 'implemented' })),
        latestLearningVerifiedResult: 'Executable checks passed: ruff, pyright, pytest.',
        latestTrainingHandoff: { ...state.latestTrainingHandoff, learningPhase: 'return',
          handoffStatus: 'verified', returnMode: 'result', reflection },
        latestTrainingNextHop: { ...state.latestTrainingNextHop, status: 'continued_in_chat', continueIn: 'chat' },
      },
    };
    window.__TRAINER_BOOTSTRAP__ = payload;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload });
  }, reflection);
  const carryResult = page.getByRole('button', { name: '带结果回到教练', exact: true });
  await expect(carryResult).toHaveCount(1);
  await carryResult.click();
  const draft = page.getByRole('textbox', { name: '消息输入框', exact: true });
  await expect(draft).toHaveValue(/Executable checks passed/);
  await expect(draft).toHaveValue(new RegExp('我的复盘是：'));
  expect(await draft.inputValue()).toContain(reflection);
});

test('switching conversations isolates unsent drafts and restores each one when returning', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=coach&lang=en-US&connection=connected&run=session-drafts');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const switchSession = async id => page.evaluate(sessionLabel => {
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'state/patch', payload: { sessionLabel } });
  }, id);
  await switchSession('session-draft-a');
  const input = page.getByRole('textbox');
  await input.fill('Tuple reflection, still unsent.\nKeep this output intact.');
  await switchSession('session-draft-b');
  await expect(input).toHaveValue('');
  await input.fill('A separate new question.');
  await switchSession('session-draft-a');
  await expect(input).toHaveValue('Tuple reflection, still unsent.\nKeep this output intact.');
  await switchSession('session-draft-b');
  await expect(input).toHaveValue('A separate new question.');
});

test('same-context backups isolate growth evidence and unsent drafts by database', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=coach&lang=zh-CN&connection=connected&run=database-isolation');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const switchDatabase = async (root, generation, verified) => page.evaluate(({ root, generation, verified }) => {
    const current = window.__TRAINER_BOOTSTRAP__;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: {
      ...current, runtimeDataGeneration: generation, sessionLabel: 'session-same-id',
      memory: { ...current.memory, workspace: { workspaceId: 'same-context', responseLanguage: 'zh-CN',
        resourceSandbox: { effectivePath: root, defaultPath: root, source: 'custom', status: 'ready' },
      } },
      workspaceTrainingState: { workspaceId: 'same-context', ...(verified ? { skillProjection: {
        workspaceId: 'same-context', dimensions: { implementation: { state: 'assisted', verifiedCount: 1 } },
      } } : {}) },
    } });
  }, { root, generation, verified });
  const input = page.getByRole('textbox', { name: '消息输入框', exact: true });
  await switchDatabase('/original/data', 'original-one', true);
  await input.fill('原目录草稿，尚未发送。');
  await page.getByTestId('trainer-view-nav-progress').click();
  await expect(page.getByRole('button', { name: '实现 有辅助完成 1 次验证通过', exact: true })).toBeVisible();
  await switchDatabase('/backup/data', 'backup-one', false);
  await expect(page.getByText('完成一次练习的验证后，这里会显示你在理解、实现、调试和迁移上的真实成长。', { exact: true })).toBeVisible();
  await expect(page.getByText('1 次验证通过', { exact: true })).toHaveCount(0);
  await page.getByTestId('trainer-view-nav-coach').click();
  await expect(input).toHaveValue('');
  await input.fill('恢复目录的另一份草稿。');
  await switchDatabase('/original/data', 'original-two', true);
  await expect(input).toHaveValue('原目录草稿，尚未发送。');
  await switchDatabase('/backup/data', 'backup-two', false);
  await expect(input).toHaveValue('恢复目录的另一份草稿。');
});

test('an unbound evaluation cannot replace the formal plan next step', async ({ page }) => {
  await page.goto('/vscode-preview.html?view=plan&lang=zh-CN&connection=connected&run=unbound-plan-evaluation');
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const step = '增加 hash(pair) 与字典键的负向断言，然后实际运行 pytest。';
    const reason = '当前阶段尚缺这两条边界证据。';
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: {
      ...current, sessionHistoryRestored: true,
      plan: { ...current.plan, id: 'formal-current-plan', currentStep: step, whyNow: reason },
      planRuntimeStatus: { recovered: true, currentStep: step, whyNow: reason, verifyPlanAdvance: {
        advanced: false, planId: 'formal-current-plan', what: 'Plan progress unchanged',
        why: 'This file evaluation is not bound to the current formal task.',
        next: 'Record a reflection on the verified result, then bring it back to Coach.',
      } },
      memory: { ...current.memory, workspace: { ...current.memory.workspace, latestPlanRuntime: {
        workspaceId: current.memory.workspace.workspaceId, planId: 'formal-current-plan',
        currentStep: step, whyNow: reason, revision: 19, resumeState: 'in_progress',
      } } },
    } });
  });
  await expect(page.getByText('增加 hash(pair) 与字典键的负向断言，然后实际运行 pytest。', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Record a reflection on the verified result, then bring it back to Coach.', { exact: true })).toHaveCount(0);
});

test('Start review opens the due queue while preserving the current practice card', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 760 });
  await loadHostFixture(page, 'plan', 'review-queue-current-card');
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const workspaceId = current.memory.workspace.workspaceId;
    const card = { cardId: 'card-due-review', type: 'practice', title: '保留当前元组练习',
      status: 'active', learningPhase: 'try', problemStatement: '验证嵌套对象修改及元组槽位赋值的异常边界。'.repeat(30),
      verificationSteps: ['旧练习的文件校验契约'], deliverable: '一次实际运行的结果', targetSkill: '元组引用', focusArea: 'Python 元组' };
    const dueReviews = [{ concept: '元组赋值边界', reason: '解释槽位赋值的异常。',
      taskHint: '回忆 TypeError 的触发行。', focusArea: 'Python 元组',
      source: 'weakness', severity: 'high', surfaceMode: 'due', dueAt: '2026-10-01T00:00:00Z' }];
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: {
      ...current,
      memory: { ...current.memory, dueReviewCount: 1, dueReviews, reviewSummary: '旧主线的重复提示。'.repeat(80), workspace: { ...current.memory.workspace,
        liveTrainingSelection: { workspaceId, cardId: card.cardId, selectedAt: '2026-10-02T03:00:00Z' },
      } },
      workspaceTrainingState: { ...current.workspaceTrainingState, workspaceId, dueReviews,
        latestTrainingSubmode: 'practice', selectedCardId: card.cardId, selectedCardType: 'practice',
        selectedCardTitle: card.title, selectedCardStatus: 'active', trainingCardCandidates: [card],
        activeTrainingCardRouting: { selectedCardId: card.cardId, selectedCard: card, selectionScore: 100 },
      },
    } });
  });
  await page.getByRole('button', { name: '开始复习', exact: true }).click();
  await expect(page.getByRole('heading', { name: '保留当前元组练习', exact: true })).toBeVisible();
  const queue = page.locator('[data-training-review-queue="true"]');
  await expect(queue).toHaveAttribute('open', '');
  await expect(queue.getByRole('heading', { name: '元组赋值边界', exact: true })).toBeVisible();
  await expect(queue.getByRole('button', { name: '开始复习', exact: true })).toBeVisible();
  await expect(queue.getByRole('button', { name: '开始复习', exact: true })).toBeInViewport();
  const geometry = await page.evaluate(() => {
    const card = document.querySelector('.training-current--single-card').getBoundingClientRect();
    const queue = document.querySelector('[data-training-review-queue="true"]').getBoundingClientRect();
    return { cardBottom: card.bottom, queueTop: queue.top };
  });
  expect(geometry.queueTop).toBeGreaterThanOrEqual(geometry.cardBottom);
  await page.evaluate(() => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'ui/restoreView', payload: {
    activeView: 'training', trainingRestoreTarget: 'next_hop',
    latestTrainingNextHop: { targetId: 'card-due-review', cardType: 'practice', title: '旧恢复卡' },
  } }));
  await queue.getByRole('button', { name: '开始复习', exact: true }).click();
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'state/patch', payload: {
      workspaceTrainingState: { ...current.workspaceTrainingState, latestTrainingSubmode: 'review_queue',
        reviewArtifact: { id: 'review-tuple-slot', title: '复习：元组赋值边界', focusArea: '元组赋值边界',
          source: 'review_queue', status: 'active', summary: '不看笔记解释 tuple 槽位为何不可写。',
          guardrail: '先闭卷回忆，再用例子核对。', recommendedActions: ['用一句话说明预期异常。'], nextSelfImplementationRule: '先回忆，再核对例子。',
        },
      },
    } });
  });
  const currentCard = page.locator('.training-current--single-card');
  await expect(currentCard.getByRole('heading', { name: '复习：元组赋值边界', exact: true })).toBeInViewport();
  await expect(currentCard.getByText('不看笔记解释 tuple 槽位为何不可写。', { exact: true }).first()).toBeVisible();
  await expect(currentCard.getByRole('button', { name: '验证当前文件', exact: true })).toHaveCount(0);
  await expect(page.getByRole('textbox').last()).toHaveAttribute('placeholder', '写下你刚确认的规则，以及下次如何复用它。');
  expect(await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.filter(
    (message) => message.payload?.commandId === 'trainer.training.attempt.start' &&
      message.payload.payload?.cardId === 'review-tuple-slot',
  ))).toHaveLength(0);
  const accept = await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.find(
    (message) => message.payload?.commandId === 'trainer.training.reviewQueueAction',
  ));
  await page.evaluate((message) => window.postMessage(message, window.location.origin), {
    type: 'training/persistenceAck', payload: { commandId: accept.payload.commandId, ok: true,
      requestId: accept.payload.payload.__trainerTrainingPersistenceId },
  });
  await page.getByRole('textbox').last().fill('元组槽位不能替换，但它引用的列表仍然可变。');
  await page.getByRole('button', { name: '记录训练复盘', exact: true }).click();
  await expect.poll(async () => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.find(
    (message) => message.payload?.commandId === 'trainer.training.reviewArtifactAction',
  )?.payload.payload)).toMatchObject({
    reviewArtifactId: 'review-tuple-slot', action: 'resolved', note: '元组槽位不能替换，但它引用的列表仍然可变。',
  });
  const resolved = await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.find(
    (message) => message.payload?.commandId === 'trainer.training.reviewArtifactAction',
  ));
  await page.evaluate((message) => window.postMessage(message, window.location.origin), {
    type: 'training/persistenceAck', payload: { commandId: resolved.payload.commandId, ok: true,
      requestId: resolved.payload.payload.__trainerTrainingPersistenceId },
  });
  await expect.poll(async () => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.find(
    (message) => message.type === 'session/sendStreamMessage',
  )?.payload.text)).toContain('先回忆，再核对例子。');
  const feedback = await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.find(
    (message) => message.type === 'session/sendStreamMessage',
  ).payload.text);
  expect(feedback).not.toContain('旧练习的文件校验契约');
});

test('a recorded review resumes as recall without a coding verification or empty Return action', async ({ page }) => {
  await loadHostFixture(page, 'training', 'resolved-recall-review');
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    window.postMessage({ type: 'bootstrap', payload: { ...current,
      workspaceTrainingState: { ...current.workspaceTrainingState, latestTrainingSubmode: 'review_queue',
        reviewArtifact: { id: 'review-recorded', title: '复习：元组槽位', focusArea: '元组槽位',
          status: 'resolved', source: 'review_queue', summary: '解释引用与槽位的边界。',
          verifiedResult: '元组槽位不可写，内层列表仍可变。', guardrail: '先回忆，再核对例子。',
        },
      },
    } }, window.location.origin);
  });
  await expect(page.getByRole('heading', { name: '复习：元组槽位', exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: '就当前训练卡片向教练提问', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '完成训练回流', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '验证当前文件', exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.filter(
    (message) => message.payload?.commandId === 'trainer.training.attempt.start' &&
      message.payload.payload?.cardId === 'review-recorded',
  ))).toHaveLength(0);
});

test('an explicit saved-plan correction from Coach uses the formal mutation route', async ({ page }) => {
  await loadHostFixture(page, 'coach', 'explicit-plan-save');
  await page.getByRole('textbox', { name: '消息输入框', exact: true }).fill(
    '请明确修正并保存当前正式学习计划。4/4是四种检查，不能虚构 pytest 用例数量。',
  );
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect.poll(async () => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.filter(
    (action) => action.type === 'session/sendStreamMessage',
  ).length)).toBe(1);
  const submitted = await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.find(
    (action) => action.type === 'session/sendStreamMessage',
  ).payload);
  expect(submitted.intent).toBe('plan');
  expect(submitted.formalPlanMutation).toBe(true);
});

// Keep these state-transition regressions on the real host message bridge.
// The preview transport otherwise performs asynchronous sidecar refreshes.
async function loadHostFixture(page, view, run) {
  await page.goto(`/vscode-preview.html?view=${view}&lang=zh-CN&connection=connected&run=${run}`);
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const bootstrap = await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    return { ...current,
      providerConfig: { ...current.providerConfig, lastTestResult: {
        ...current.providerConfig.lastTestResult, ok: true, status: 'connected',
        workspaceId: current.memory.workspace.workspaceId, profileId: current.providerConfig.profileId,
        checkedAt: new Date().toISOString(), protocol: 'openai_chat_completions_compatible',
        toolsReady: true, toolProbeStatus: 'verified', streamingReady: true, streamProbeStatus: 'verified',
        capabilityEvidence: [
          { name: 'tools', declared: true, state: 'verified', observed: true },
          { name: 'streaming', declared: true, state: 'verified', observed: true },
        ],
      } },
      memory: { ...current.memory, sandboxState: { ...current.memory.sandboxState, authority: {
        authorityScope: 'trainer_sandbox', resourceWriteAllowed: true,
        resourceWriteEvidence: { operation: 'write', scope: 'trainer_sandbox', allowed: true },
      } } },
    };
  });
  await page.addInitScript(({ bootstrap, view }) => {
    window.__TRAINER_BOOTSTRAP__ = bootstrap;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__ = (message) => window.postMessage(message, window.location.origin);
    window.__TRAINER_E2E_HOST_ACTIONS__ = [];
    window.acquireVsCodeApi = () => ({
      getState: () => ({ activeView: view, composerLanguage: 'zh-CN' }),
      setState: () => undefined,
      postMessage: (message) => window.__TRAINER_E2E_HOST_ACTIONS__.push(message),
    });
  }, { bootstrap, view });
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.some(
    (message) => message.type === 'request/bootstrap',
  ))).toBe(true);
  await page.evaluate(() => window.postMessage({ type: 'bootstrap', payload: window.__TRAINER_BOOTSTRAP__ }, window.location.origin));
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
}
