const { openSettingsCategory } = require("./template-navigation");
const { test, expect } = require("playwright/test");
const { planOnlyFixture } = require('./learning-fixtures');
const { closeLearningDrawer, openLearningDrawer } = require('./workbench-navigation');

/**
 * Learning is no longer a destination: the plan card lives in the learning
 * drawer, which the learner opens from the header icon beside the history
 * utility. The drawer overlays the shell, so it is closed before it is
 * reopened on the goal section.
 */
async function openLearningGoal(page) {
  await closeLearningDrawer(page);
  await openLearningDrawer(page, 'goal');
}

/** Legacy learning route → the learning drawer section it opens. */
const LEGACY_ROUTE_SECTIONS = { plan: 'goal', training: 'practice', progress: 'progress' };

// The learning drawer has no catch-all disclosure any more: the plan's stages
// and evidence are plain rows, and every adjustment starts in the composer.
async function openLearningMore(page) {
  await expect(page.locator('[data-template="LearningDrawer"]')).toBeVisible();
}

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
  await openLearningMore(page);
  await expect(page.locator('[data-learning-section=route]')).toBeVisible();
});

test("compact Goals view shows its learning path on entry", async ({ page }) => {
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
  const stages = page.locator('[data-learning-section=route]');
  await openLearningMore(page);
  await expect(stages).toBeVisible();
  // The route group is a plain row group inside the drawer: the learning path
  // is readable without opening a fold.
  await expect(stages.locator(':scope > summary')).toHaveCount(0);
  await expect(stages.getByText('验证元组内列表', { exact: true })).toBeVisible();
  await expect(stages.getByText('实现嵌套求和', { exact: true })).toBeVisible();
  // The third stage stays behind the group's own "more" disclosure.
  await expect(stages.getByText('覆盖异常边界', { exact: true })).toHaveCount(1);
  await stages.locator('[data-learning-section="more-route-stages"] > summary').click();
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
  await openSettingsCategory(page, "teaching");
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
  await expect(page.locator('[data-training-card-id]').getByRole("heading", { name: "Tuple mutability", exact: true })).toBeVisible();
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
  const question = page.locator('.template-focused-practice__phase p').filter({ hasText: '请说明为什么其中一条合法、另一条抛错。' }).first();
  await expect(question).toBeVisible();
  await expect(question).toContainText('各自的结果是什么？');
  await expect(question.locator('code')).toHaveText(['pair = ([1, 2], 3)', 'pair[0].append(4)', 'pair[1] = 9']);
  await expect(page.locator('[data-training-card-id]').getByRole("heading", { name: "元组中嵌套列表的可变性边界", exact: true })).toBeVisible();
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
  // Every adjustment starts in the one composer: the learner types the plan
  // request, the intent is recognized, and the confirmation stays governed.
  // The learning drawer is a modal sheet: the composer is reachable once it is
  // closed. Every adjustment starts there.
  await closeLearningDrawer(page);
  await page.locator("#coach-composer").fill("生成正式学习计划");
  await page.locator(".composer__send").click();
  const planPreview = page.locator('[data-unified-action-preview="plan"]');
  await planPreview.waitFor();
  await planPreview.getByRole("button", { name: "确认并执行" }).click();
  // Learning is not a destination any more: the plan intent lands on Chat
  // with the learning drawer open on the goal section.
  await expect(page.getByTestId("trainer-view-nav-coach")).toHaveAttribute("aria-current", "page");
  await expect(page.locator('[data-template="LearningDrawer"]')).toBeVisible();
  await expect(page.locator('[data-learning-section="goal"]')).toBeVisible();
});

test("browser selection prefill lands in Coach and keeps the shared draft in the learning drawer", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=plan&lang=en-US&connection=connected&scenario=ready");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const textbox = page.locator("#coach-composer");
  await textbox.fill("MY PLAN DRAFT");
  await page.evaluate(() => {
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
      type: "ui/coachDraftPrefill",
      draftId: "browser-prefill-1",
      text: "BROWSER SELECTION",
    });
  });
  await expect(page.getByTestId("trainer-view-nav-coach")).toHaveAttribute("aria-current", "page");
  // A browser selection never destroys the words the learner already typed.
  await expect(textbox).toHaveValue("MY PLAN DRAFT\n\nBROWSER SELECTION");
  // The learning drawer is a surface over Chat: it shares the one Chat draft.
  await openLearningGoal(page);
  await expect(page.locator('[data-template="LearningDrawer"]')).toBeVisible();
  await expect(textbox).toHaveValue("MY PLAN DRAFT\n\nBROWSER SELECTION");
});

test("Ask Trainer draft with a learner question lands in the shared Coach composer", async ({ page }) => {
  // P4: the browser side panel stages page context + the learner's question
  // through the existing coach-draft channel. With a source attached the
  // staged ask follows the visible work context — opened on Coach it lands
  // in the Coach conversation, the question replaces the default ask line,
  // and the learning drawer shares that one draft.
  await page.goto("/vscode-preview.html?view=coach&lang=en-US&connection=connected&scenario=ready");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const textbox = page.locator("#coach-composer");
  await textbox.fill("MY COACH DRAFT");
  await page.evaluate(() => {
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
      type: "ui/coachDraftPrefill",
      draftId: "ask-trainer-1",
      text: [
        "Help me understand this excerpt (from \u201cEpisode boundaries\u201d):",
        "",
        "> Episode boundaries decide whether reward keeps accumulating.",
        "",
        "Source: https://rl.example.com/episodes",
        "",
        "Explain truncation versus termination in the training objective.",
      ].join("\n"),
      source: {
        url: "https://rl.example.com/episodes",
        title: "Episode boundaries",
        selection: "Episode boundaries decide whether reward keeps accumulating.",
      },
    });
  });
  await expect(page.getByTestId("trainer-view-nav-coach")).toHaveAttribute("aria-current", "page");
  await expect(textbox).toHaveValue(/Explain truncation versus termination in the training objective\./);
  await expect(textbox).toHaveValue(
    /Episode boundaries decide whether reward keeps accumulating\./,
  );
  await expect(textbox).toHaveValue(/Source: https:\/\/rl\.example\.com\/episodes/);
  // The learner's own words replace the default ask template.
  await expect(textbox).not.toHaveValue(/Explain the key ideas here/);
  // The learning drawer is a surface over Chat: there is one shared draft, so
  // the staged ask survives opening and closing the drawer.
  await openLearningGoal(page);
  await expect(page.locator('[data-template="LearningDrawer"]')).toBeVisible();
  await expect(textbox).toHaveValue(/Explain truncation versus termination/);
  await closeLearningDrawer(page);
  await expect(textbox).toHaveValue(/Explain truncation versus termination/);
});

test("host coach prompt lands in the shared Coach composer", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=plan&lang=en-US&connection=connected&scenario=ready");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const textbox = page.locator("#coach-composer");
  await textbox.fill("PLAN DRAFT");
  await page.evaluate(() => {
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
      type: "ui/coachPrompt",
      payload: { draft: "HOST PROMPT" },
    });
  });
  await expect(page.getByTestId("trainer-view-nav-coach")).toHaveAttribute("aria-current", "page");
  await expect(textbox).toHaveValue("HOST PROMPT");
  // There is one shared Chat draft now, so the learning drawer shows the same
  // host prompt instead of a second, separate Learning draft.
  await openLearningGoal(page);
  await expect(page.locator('[data-template="LearningDrawer"]')).toBeVisible();
  await expect(textbox).toHaveValue("HOST PROMPT");
});

test("browser selection prefill appends to an unsent Coach draft", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=coach&lang=en-US&connection=connected&scenario=ready");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.locator("#coach-composer").fill("MY COACH DRAFT");
  await page.evaluate(() => {
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
      type: "ui/coachDraftPrefill",
      draftId: "browser-prefill-coach-1",
      text: "BROWSER SELECTION",
    });
  });
  await expect(page.locator("#coach-composer")).toHaveValue(
    "MY COACH DRAFT\n\nBROWSER SELECTION",
  );
  await expect(page.getByTestId("trainer-view-nav-coach")).toHaveAttribute("aria-current", "page");
});

test("the learning drawer keeps an unsent Coach draft instead of overwriting it", async ({ page }) => {
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
  // The learning drawer overlays the shell: close it before Chat is selected.
  await closeLearningDrawer(page);
  await page.getByTestId("trainer-view-nav-coach").click();
  await page.locator("#coach-composer").fill("我的教练草稿");
  await openLearningGoal(page);
  // The learning drawer is a reading surface: opening and closing it never
  // overwrites the learner's unsent Coach draft.
  await expect(page.locator("#coach-composer")).toHaveValue("我的教练草稿");
  await closeLearningDrawer(page);
  await expect(page.getByTestId("trainer-view-nav-coach")).toHaveAttribute("aria-current", "page");
  await expect(page.locator("#coach-composer")).toHaveValue("我的教练草稿");
});

test("training generation keeps raw card JSON out of the conversation surface", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=coach&lang=en-US&connection=connected&run=card-stream");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await page.evaluate(() => {
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'stream/start', payload: { messageId: 'training_raw_card' } });
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'stream/chunk', payload: { messageId: 'training_raw_card', chunk: '{"title":"INTERNAL_CARD_JSON_123"' } });
  });
  await expect(page.getByText(/INTERNAL_CARD_JSON_123/)).toHaveCount(0);
  await expect(page.locator('.coach-working__label')).toHaveText('Thinking');
  await page.evaluate(() => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
    type: 'stream/cancelled', payload: { messageId: 'training_raw_card' },
  }));
  await expect(page.locator('#coach-composer')).toBeEnabled();
});

test("stage materials live inside per-stage disclosures and old plan materials clear", async ({ page }) => {
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
  const stages = page.locator('[data-learning-section=route]');
  await openLearningMore(page);
  // The route group holds the live stages; the finished one moved into the
  // completed-stages disclosure.
  await expect(stages.locator('[data-plan-stage]')).toHaveCount(1);
  const completed = page.locator('[data-learning-section="completed-stages"]');
  await expect(completed.locator('[data-plan-stage="stage-2"]')).toHaveCount(1);
  await expect(stages.getByRole('meter')).toHaveCount(0);
  await expect(stages.locator('[title^="已生成资料"]')).toHaveCount(0);
  const active = stages.locator('[data-plan-stage="stage-1"]');
  await expect(active).toHaveAttribute('data-stage-status', 'active');
  const done = completed.locator('[data-plan-stage="stage-2"]');
  await expect(done).toHaveAttribute('data-stage-status', 'done');
  // Stage details are user-controlled now: open the active stage to reach its
  // objective, 生成资料 action and generated materials.
  const activeDetails = active.locator('details');
  if (!(await activeDetails.evaluate(el => el.open))) {
    await activeDetails.locator(':scope > summary').click();
  }
  await expect(activeDetails).toHaveJSProperty('open', true);
  await expect(done.locator('details')).toHaveJSProperty('open', false);
  // CSS locator on purpose: role queries skip content inside a closed details.
  await expect(activeDetails.locator('button:has-text("生成资料0")')).toHaveCount(1);
  // Old plan materials clear when the formal plan is replaced.
  await page.evaluate(() => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'state/patch', payload: {
    plan: { id: 'replacement-plan', title: '新的计划', currentStageId: 'stage-1',
      currentStep: '新的验证', stages: [{ id: 'stage-1', title: '新的阶段', status: 'active', objective: '新的验证' }] },
  } }));
  await expect(page.getByText('生成资料0', { exact: true })).toHaveCount(0);
  // Restage the materials and open the stage details to read one.
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
      stageMaterials: { 'stage-1': ['study_guide'].map((kind, i) => ({
        id: 'material-' + i, planStageId: 'stage-1', kind, title: '生成资料' + i, summary: '真正的学习内容',
        generationSource: 'template', content: '## 正文\n\n```python\nif True:\n    print(1)\n```',
      })) },
    } });
  });
  const reopenedDetails = stages.locator('[data-plan-stage="stage-1"]').locator('details');
  if (!(await reopenedDetails.evaluate((el) => el.open))) {
    await reopenedDetails.locator(':scope > summary').click();
  }
  await expect(reopenedDetails.getByText('运行代码', { exact: true })).toBeVisible();
  await expect(reopenedDetails.locator('[data-stage-materials-generate]')).toBeVisible();
  await reopenedDetails.getByRole('button', { name: /生成资料0/ }).click();
  await expect(reopenedDetails.getByRole('heading', { name: '正文' })).toBeVisible();
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
  // The legacy Training route opens the learning drawer, and the drawer
  // overlays the shell: close it so the practice card is reachable again.
  await closeLearningDrawer(page);
  // The reflection now lives in the card's own answer field.
  const reflectionInput = page.getByRole('textbox', { name: '你的作答', exact: true });
  await expect(reflectionInput).toBeEditable();
  await expect(reflectionInput).toHaveAttribute('placeholder', '写下你刚确认的规则，以及下次如何复用它。');
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
  const input = page.locator('#coach-composer');
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
  await openLearningGoal(page);
  // Growth is the drawer's progress section now — the separate Growth page is
  // gone.
  const progress = page.locator('[data-template="LearningDrawer"] [data-learning-section="progress"]');
  const growthRow = progress.locator('li').filter({ hasText: '实现' });
  await expect(growthRow).toBeVisible();
  await expect(growthRow).toContainText('需提示');
  await expect(growthRow).toContainText('1 次');
  await switchDatabase('/backup/data', 'backup-one', false);
  // The backup database carries no projection: no proven dimension remains.
  await expect(progress.getByText('需提示', { exact: true })).toHaveCount(0);
  await expect(progress.getByText('1 次', { exact: true })).toHaveCount(0);
  await closeLearningDrawer(page);
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
  const source = planOnlyFixture(await page.evaluate(() => window.__TRAINER_BOOTSTRAP__));
  await page.evaluate(current => {
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
  }, source);
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
  await openLearningMore(page);
  await page.getByRole('button', { name: '开始复习', exact: true }).click();
  // The due queue has no Training panel any more: "Start review" opens the
  // learning drawer on the practice section and keeps the practice card.
  await expect(page.locator('[data-template="LearningDrawer"]')).toBeVisible();
  await expect(page.locator('[data-learning-section="practice"]')).toBeVisible();
  await expect(page.locator('[data-training-card-id]').getByRole('heading', { name: '保留当前元组练习', exact: true })).toBeVisible();
  await page.evaluate(() => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'ui/restoreView', payload: {
    activeView: 'training', trainingRestoreTarget: 'next_hop',
    latestTrainingNextHop: { targetId: 'card-due-review', cardType: 'practice', title: '旧恢复卡' },
  } }));
  // The restored route opens the learning drawer; close it so the practice
  // card is reachable again.
  await closeLearningDrawer(page);
  await page.evaluate(() => {
    const current = window.__TRAINER_BOOTSTRAP__;
    const artifact = { cardId: 'review-tuple-slot', type: 'practice', title: '复习：元组赋值边界',
      status: 'active', learningPhase: 'recall', focusArea: '元组赋值边界' };
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'state/patch', payload: {
      workspaceTrainingState: { ...current.workspaceTrainingState, latestTrainingSubmode: 'review_queue',
        // The review artifact is the foreground card: the due-queue panel
        // that used to promote it is gone with the Training surface.
        selectedCardId: artifact.cardId,
        selectedCardTitle: artifact.title,
        selectedCardStatus: 'active',
        trainingCardCandidates: [...(current.workspaceTrainingState.trainingCardCandidates ?? []), artifact],
        activeTrainingCardRouting: { selectedCardId: artifact.cardId, selectedCard: artifact },
        reviewArtifact: { id: 'review-tuple-slot', title: '复习：元组赋值边界', focusArea: '元组赋值边界',
          source: 'review_queue', status: 'active', summary: '不看笔记解释 tuple 槽位为何不可写。',
          guardrail: '先闭卷回忆，再用例子核对。', recommendedActions: ['用一句话说明预期异常。'], nextSelfImplementationRule: '先回忆，再核对例子。',
        },
      },
    } });
  });
  const currentCard = page.locator('.training-current--single-card');
  // The conversation keeps its reading position: bring the card into view
  // before asserting that the review card is what the learner reads.
  await currentCard.scrollIntoViewIfNeeded();
  await expect(currentCard.getByRole('heading', { name: '复习：元组赋值边界', exact: true })).toBeInViewport();
  await expect(currentCard.getByText('不看笔记解释 tuple 槽位为何不可写。', { exact: true }).filter({ visible: true }).first()).toBeVisible();
  await expect(currentCard.getByRole('button', { name: '验证当前文件', exact: true })).toHaveCount(0);
  await expect(page.locator('#coach-composer')).toBeEditable();
  await expect(page.locator('[data-template=FocusedPractice]')).toContainText('不看笔记解释 tuple 槽位为何不可写。');
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
  // The reflection is recorded in the card's own answer field, not in the
  // dock composer.
  await page.locator('[data-inline-practice-answer="true"] textarea').fill('元组槽位不能替换，但它引用的列表仍然可变。');
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
  await expect(page.getByText('元组槽位不可写，内层列表仍可变。', { exact: true }).filter({ visible: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '问教练', exact: true })).toBeVisible();
  await expect(page.locator('#coach-composer')).toHaveCount(1);
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
  const preview = page.locator('[data-unified-action-preview="plan"]');
  await expect(preview).toBeVisible();
  expect(await page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__.some(
    (action) => action.type === 'session/sendStreamMessage',
  ))).toBe(false);
  await preview.getByRole('button', { name: '确认并执行' }).click();
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
  // Learning is not a destination any more: a legacy learning route resolves
  // to Chat with the learning drawer opened on the matching section.
  if (LEGACY_ROUTE_SECTIONS[view]) {
    await openLearningDrawer(page, LEGACY_ROUTE_SECTIONS[view]);
  }
}

for (const language of ['zh-CN', 'en-US']) {
  for (const recovered of [true, false]) {
    test(`restored ${language} training preserves its English technical focus and exact card identity, recovered=${recovered}`, async ({ page }) => {
      await page.goto(`/vscode-preview.html?view=training&lang=${language}&connection=connected&run=technical-focus-${language}-${recovered}`);
      await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
      await page.evaluate(({ language, recovered }) => {
        const current = window.__TRAINER_BOOTSTRAP__;
        const workspaceId = 'workspace-technical-focus';
        const unrelatedFocus = language === 'zh-CN'
          ? '当前聚焦：继续顺着最近的对话主线往前走，特别注意最早的用户请求。'
          : 'Current focus: continue the earlier conversation narrative rather than the card task.';
        const card = { cardId: `restored-technical-focus-${language}`, type: 'practice',
          title: language === 'zh-CN' ? '工作区边界练习' : 'Workspace boundary practice',
          status: 'active', learningPhase: 'try', focusArea: 'workspace_id isolation',
          targetSkill: 'workspace_id boundary', problemStatement: language === 'zh-CN' ? '验证返回值的工作区边界。' : 'Verify the workspace boundary of a returned result.',
          deliverable: 'One boundary assertion', verificationRecipe: ['python lesson.py'], answerMode: 'text' };
        window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: 'bootstrap', payload: {
          ...current, sessionHistoryRestored: true, plan: null,
          task: { ...current.task, title: 'OLD_FORMAL_TASK_TITLE' },
          coachFocus: { ...current.coachFocus, currentFocus: unrelatedFocus },
          teachingDecision: { ...current.teachingDecision, focusArea: 'OLD_TEACHING_FOCUS' },
          learnerState: { ...current.learnerState, activeFocus: unrelatedFocus },
          planRuntimeStatus: { recovered, currentStep: '', reviewPoints: [] },
          memory: { ...current.memory, currentFocus: unrelatedFocus, workspace: { ...current.memory.workspace,
            workspaceId, liveTrainingSelection: { workspaceId, cardId: card.cardId, selectedAt: '2026-10-09T00:00:00Z' },
            latestPlanRuntime: undefined, latestTrainingHandoff: undefined, latestTrainingNextHop: undefined } },
          workspaceTrainingState: { workspaceId, selectedCardId: card.cardId, selectedCardType: card.type,
            selectedCardTitle: card.title, selectedCardStatus: card.status, trainingCardCandidates: [card],
            latestLearningFocusArea: unrelatedFocus,
            activeTrainingCardRouting: { selectedCardId: card.cardId, selectedCard: card, selectionScore: 100 } },
        } });
      }, { language, recovered });
      // The legacy Training route opens the learning drawer, and the drawer
      // overlays the shell: close it so the practice card is reachable again.
      await closeLearningDrawer(page);
      const card = page.locator('[data-training-card-id]');
      await expect(card).toHaveAttribute('data-training-card-id', `restored-technical-focus-${language}`);
      const details = page.locator('[data-training-card-details=true]');
      await details.locator(':scope > summary').click();
      await expect(details.locator('[data-training-card-fact=focus]')).toHaveText('workspace_id isolation');
      await expect(details).not.toContainText('OLD_');
      await page.getByTestId('trainer-view-nav-resources').click();
      // Learning is not a destination any more: the learner comes back to
      // Chat and reopens the learning drawer on the goal section.
      await openLearningGoal(page);
      await page.locator('[data-template="LearningDrawer"] [data-template=NextAction] button').click();
      await expect(card).toHaveAttribute('data-training-card-id', `restored-technical-focus-${language}`);
      await expect(details.locator('[data-training-card-fact=focus]')).toHaveText('workspace_id isolation');
      await expect(details).not.toContainText('OLD_');
    });
  }
}
