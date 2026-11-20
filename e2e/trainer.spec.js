const { openSettingsCategory } = require("./template-navigation");
const { planOnlyFixture } = require('./learning-fixtures');
const {
  closeLearningDrawer,
  expectTwoPrimaryDestinations: expectTwoPrimaryDestinationContract,
  openLearningDrawer,
} = require("./workbench-navigation");
/**
 * Trainer E2E acceptance coverage for the two-destination sidebar shell with six internal routes.
 * Run: npx playwright test e2e/trainer.spec.js
 */

const { test, expect } = require("playwright/test");

const PREVIEW_PATH = "/vscode-preview.html";

/** Legacy learning routes resolve to Chat with the learning drawer open. */
const LEGACY_LEARNING_ROUTES = ["plan", "training", "progress"];

const VIEW_LABELS = {
  "zh-CN": {
    coach: "对话",
    plan: "学习",
    resources: "资料",
    training: "训练",
    progress: "成长",
    settings: "设置",
  },
  "en-US": {
    coach: "Chat",
    plan: "Learning",
    resources: "Resources",
    training: "Training",
    progress: "Progress",
    settings: "Settings",
  },
  "es-ES": {
    coach: "Chat",
    plan: "Plan",
    resources: "Recursos",
    training: "Entrenamiento",
    progress: "Progreso",
    settings: "Ajustes",
  },
};

const RESOURCE_COPY = {
  "zh-CN": {
    library: "\u8d44\u6599\u5e93",
    resourceDetail: "\u8d44\u6599\u8be6\u60c5",
    searchLabel: "\u641c\u7d22\u6807\u9898\u3001\u6765\u6e90\u6216\u6458\u8981",
    searchPlaceholder: "\u641c\u7d22\u8d44\u6599",
    primaryResource: "\u767b\u5f55\u9519\u8bef\u7801\u5bf9\u7167",
    indexingResource: "\u5f53\u524d\u6587\u4ef6\u9519\u8bef\u5904\u7406\u7b14\u8bb0",
    noMatchesLabel: "\u6ca1\u6709\u5339\u914d\u7684\u8d44\u6599",
    restoreResource: "\u6062\u590d\u8d44\u6599",
    restoreUnavailable: "\u6d4f\u89c8\u5668\u9884\u89c8\u4e0d\u4f1a\u66f4\u6539\u771f\u5b9e\u8d44\u6599\u3002\u8bf7\u5728 VS Code \u4fa7\u680f\u4e2d\u64cd\u4f5c\u3002",
    trash: "\u56de\u6536\u7ad9",
    search: "搜索资料文件夹与文件",
    newFolder: "新建文件夹",
    noMatches: "没有匹配的文件夹或文件",
  },
  "en-US": {
    library: "Unified library",
    resourceDetail: "Resource detail",
    searchLabel: "Search title, source, or summary",
    searchPlaceholder: "Search",
    primaryResource: "Coach prompt patterns",
    indexingResource: "Project refactor brief",
    noMatchesLabel: "No matching resources",
    restoreResource: "Restore resource",
    restoreUnavailable: "Browser preview cannot change real resources. Use the VS Code sidebar.",
    trash: "Trash",
    search: "Search folders and files",
    newFolder: "New folder",
    noMatches: "No matching folders or files",
  },
};

const TRAINING_COPY = {
  "zh-CN": {
    card: "当前训练卡片",
    activeLearnStep: "学习",
    task: "当前任务",
    requirements: "具体要求",
    startThisStep: "开始这一步",
    verifyCurrentFile: "验证当前文件",
    returnToCoach: "带结果回到教练",
  },
  "en-US": {
    card: "Current training card",
    activeLearnStep: "Learn",
    task: "Current task",
    requirements: "Requirements",
    startThisStep: "Start this step",
    verifyCurrentFile: "Verify current file",
    returnToCoach: "Return result to Coach",
  },
};

const TRAINING_LOOP_KEYS = ["learn", "try", "verify", "reflect", "return"];
const TRAINING_CARD_FACTS = ["why-now", "deliverable", "verify", "return"];

function viewNavigationTestId(view) {
  return `trainer-view-nav-${view}`;
}

function buildPreviewUrl(view, params = {}) {
  const query = new URLSearchParams(params);
  if (view) {
    query.set("view", view);
  }
  return `${PREVIEW_PATH}?${query.toString()}`;
}

function attachConsoleErrorCollector(page) {
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  return errors;
}

async function openPreview(page, view, params = {}) {
  await page.goto(buildPreviewUrl(view, params));
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  await expect(page.locator("body")).toBeVisible();
}

async function expectActiveView(page, language, view, options = {}) {
  // Legacy learning routes resolve to Chat with the learning drawer open.
  const destination = LEGACY_LEARNING_ROUTES.includes(view) ? "coach" : view;
  const navigationItem = page.getByTestId(viewNavigationTestId(destination));
  await expect(navigationItem).toHaveAttribute("aria-current", "page");
  await expect(navigationItem).toHaveAttribute(
    "aria-label",
    VIEW_LABELS[language][destination],
  );
  // A test that closed the drawer to work in the conversation opts out.
  if (LEGACY_LEARNING_ROUTES.includes(view) && !options.drawerClosed) {
    await expect(page.locator('[data-template="LearningDrawer"]')).toBeVisible();
  }
}

async function expectTwoPrimaryDestinations(page, language) {
  await expectTwoPrimaryDestinationContract(page);
  const views = ["coach", "resources"];
  const tabs = page.locator(".app-shell-nav button");
  for (let i = 0; i < views.length; i++) {
    await expect(tabs.nth(i)).toBeVisible();
    await expect(tabs.nth(i)).toHaveAttribute("aria-label", VIEW_LABELS[language][views[i]]);
  }
  await expect(page.getByTestId("trainer-view-nav-settings")).toHaveAttribute("aria-label", VIEW_LABELS[language].settings);
}

async function expectHeaderLabelsVisible(page) {
  const displays = await page
    .locator(".app-shell-nav__item")
    .evaluateAll((nodes) => nodes.map((node) => window.getComputedStyle(node).display));
  expect(displays.every((display) => display !== "none")).toBeTruthy();
}

async function expectNoHorizontalOverflow(page) {
  const metrics = await page.evaluate(() => ({
    bodyClientWidth: document.body.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
    rootClientWidth: document.documentElement.clientWidth,
    rootScrollWidth: document.documentElement.scrollWidth,
  }));

  expect(metrics.bodyScrollWidth).toBeLessThanOrEqual(metrics.bodyClientWidth + 1);
  expect(metrics.rootScrollWidth).toBeLessThanOrEqual(metrics.rootClientWidth + 1);
}

async function expectNoConsoleErrors(errors) {
  expect(errors, `Console errors:\n${errors.join("\n")}`).toEqual([]);
}

function collectPreviewCommands(page) {
  const commands = [];
  page.on("console", (message) => {
    if (message.type() !== "debug" || !message.text().includes("[trainer:browser-preview]")) {
      return;
    }
    const payload = message.args()[1];
    if (!payload) {
      return;
    }
    void payload
      .jsonValue()
      .then((value) => {
        if (value?.type === "command/execute") {
          commands.push(value);
        }
      })
      .catch(() => undefined);
  });
  return commands;
}

async function revealTrainingCardDetails(card) {
  for (const summary of await card.locator(':scope > details > summary').all()) {
    if (!await summary.locator('..').evaluate(node => node.open)) await summary.click();
  }
}

async function openFocusedTraining(page, language = 'en-US') {
  // Training has no top-level tab and the growth section no longer carries a
  // Training button — the host restores the internal route directly.
  await page.evaluate(() =>
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__?.({
      type: 'ui/restoreView',
      payload: { activeView: 'training' },
    }),
  );
  await expectActiveView(page, language, 'training');
}

function resourceDetailName(language, title) {
  return `${RESOURCE_COPY[language].resourceDetail}. ${title}`;
}

async function expectTrainingLoop(card, activeStep) {
  await expect(card).toHaveAttribute('data-training-phase', activeStep);
  await expect(card.locator('.template-activity-header__phase')).toContainText(`${TRAINING_LOOP_KEYS.indexOf(activeStep) + 1}/5`);
  await expect(card.locator('.training-loop-rail')).toHaveCount(0);
}

async function expectTrainingCardFacts(card) {
  // One task-details disclosure carries the facts; it is absent while the
  // learn phase owns the card face.
  const details = card.locator('[data-training-card-details]');
  if ((await details.count()) === 0) return;
  await revealTrainingCardDetails(card);
  for (const fact of TRAINING_CARD_FACTS) {
    await expect(card.locator(`[data-training-card-fact="${fact}"]`)).toBeVisible();
  }
}

/** Open the learning card group's outer "More" disclosure in the drawer. */
async function openLearningMore(page) {
  const focusMore = page.locator('[data-learning-focus-more]').first();
  if ((await focusMore.count()) === 0) return;
  if ((await focusMore.getAttribute('open')) === null) {
    await focusMore.locator(':scope > summary').click();
  }
}

async function submitPlanComposerRequest(page, _mode, message) {
  // The learning drawer is a reading surface without drawer governance folds:
  // close the drawer and act directly in the shared conversation composer.
  await expect(page.getByTestId('trainer-view-nav-coach')).toHaveAttribute('aria-current', 'page');
  await expect(page.locator('[data-template="LearningDrawer"]')).toBeVisible();
  await closeLearningDrawer(page);
  const userCountBefore = await page.evaluate(() =>
    window.__TRAINER_BOOTSTRAP__?.conversation?.filter((entry) => entry.role === "user").length ?? 0,
  );
  await page.locator("#coach-composer").fill(message);
  await page.locator(".composer__send").click();
  await expect.poll(() =>
    page.evaluate((previousCount) =>
      (window.__TRAINER_BOOTSTRAP__?.conversation?.filter((entry) => entry.role === "user").length ?? 0) > previousCount,
    userCountBefore),
  ).toBe(true);
  await expect.poll(() =>
    page.evaluate(() =>
      window.__TRAINER_BOOTSTRAP__?.conversation?.some(
        (entry) =>
          entry.role === "assistant" &&
          typeof entry.body === "string" &&
          entry.body.trim().length > 0,
      ) ?? false,
    ),
  ).toBe(true);
  await expect(page.locator("#coach-composer")).toHaveValue("");
  return true;
}

test.describe("Trainer two-destination shell", () => {
  for (const language of ["zh-CN", "en-US"]) {
    test(`exposes the two localized primary destinations in ${language}`, async ({ page }) => {
      const errors = attachConsoleErrorCollector(page);

      await openPreview(page, "coach", {
        lang: language,
        scenario: "ready",
        connection: "connected",
      });

      await expectTwoPrimaryDestinations(page, language);
      await expectActiveView(page, language, "coach");
      await expectNoHorizontalOverflow(page);
      await expectNoConsoleErrors(errors);
    });
  }

  test("opens a URL-only ready preview through the fixture harness", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await page.goto("/?scenario=ready&lang=zh-CN");
    await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();

    await expect(page).toHaveURL(/\/vscode-preview\.html\?scenario=ready&lang=zh-CN/);
    await expectActiveView(page, "zh-CN", "coach");
    await expect.poll(() =>
      page.evaluate(() => window.__TRAINER_BOOTSTRAP__?.connection?.state),
    ).toBe("connected");
    await expect(page.locator("#coach-composer")).toBeEnabled();
    await expectNoConsoleErrors(errors);
  });

  test("sends a local Coach reply from a ready Chinese preview URL", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const sidecarRequests = [];
    const sendMessageLabel = "\u53d1\u9001\u6d88\u606f";
    const draft = "\u8bf7\u5e2e\u6211\u5148\u67e5\u9a8c\u4e00\u4e2a\u6700\u5c0f\u6539\u52a8";
    const localReply = "\u6559\u7ec3\u521a\u521a\u5148\u5b8c\u6210\u4e00\u4e2a\u53ef\u4ea4\u4ed8\u7ed3\u679c\uff0c\u518d\u7ec3\u4e60\u3001\u9a8c\u8bc1\u548c\u590d\u76d8\u3002";

    page.on("request", (request) => {
      if (/^http:\/\/127\.0\.0\.1:34891(?:\/|$)/.test(request.url())) {
        sidecarRequests.push(request.url());
      }
    });

    await openPreview(page, "coach", {
      lang: "zh-CN",
      scenario: "ready",
      connection: "connected",
      theme: "dark",
    });

    const previewUrl = new URL(page.url());
    expect(previewUrl.pathname).toBe(PREVIEW_PATH);
    expect(previewUrl.searchParams.get("scenario")).toBe("ready");
    expect(previewUrl.searchParams.get("lang")).toBe("zh-CN");
    expect(previewUrl.searchParams.get("connection")).toBe("connected");
    expect(previewUrl.searchParams.get("theme")).toBe("dark");
    expect(previewUrl.searchParams.get("view")).toBe("coach");
    await expect(page.locator("body")).toHaveClass(/vscode-dark/);
    await expectActiveView(page, "zh-CN", "coach");

    const composer = page.locator("#coach-composer");
    const sendButton = page.getByRole("button", { name: sendMessageLabel, exact: true });
    await expect(composer).toBeEnabled();
    await composer.fill(draft);
    await expect(sendButton).toBeEnabled();
    await sendButton.click();

    await expect(page.locator('[data-role="user"]').last()).toContainText(draft);
    await expect(page.locator('[data-role="assistant"]').last()).toContainText(localReply);
    await expect(composer).toBeEnabled();
    await expect(composer).toHaveValue("");
    expect(sidecarRequests).toEqual([]);
    await expectNoConsoleErrors(errors);
  });

  test("keeps two primary destinations, persists the active view, and omits the Settings composer", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, undefined, {
      lang: "en-US",
      scenario: "ready",
      connection: "connected",
    });

    for (const view of ["coach", "resources"]) {
      const tabs = page
        .locator(".app-shell-nav")
        .getByTestId(/^trainer-view-nav-(coach|resources)$/);
      await expectTwoPrimaryDestinations(page, "en-US");

      await page.getByTestId(viewNavigationTestId(view)).click();
      await expectActiveView(page, "en-US", view);
      await expect(tabs.first()).toBeVisible();
      await expect(page.locator(".composer-shell")).toHaveCount(1);
      await expect(page.locator("[data-dock-send-preference]")).toHaveCount(0);
    }

    // The legacy learning route is not a destination: it resolves to Chat with
    // the learning drawer open on the goal section.
    await page.getByTestId(viewNavigationTestId("coach")).click();
    await openLearningDrawer(page, "goal");
    await expectActiveView(page, "en-US", "plan");
    await expect(page.locator(".composer-shell")).toHaveCount(1);
    await expect(page.locator("[data-dock-send-preference]")).toHaveCount(0);
    await closeLearningDrawer(page);

    // Settings lives in the header gear and is not a chat surface.
    await page.getByTestId("trainer-view-nav-settings").click();
    await expectActiveView(page, "en-US", "settings");
    await expect(page.locator(".composer-shell")).toHaveCount(0);

    await page.reload();
    await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
    await expectTwoPrimaryDestinations(page, "en-US");
    await expectActiveView(page, "en-US", "settings");
    await expect(page.locator(".composer-shell")).toHaveCount(0);
    await expectNoConsoleErrors(errors);
  });

  test("learning replies land in the Chat conversation and stay there", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "plan", {
      lang: "en-US",
      scenario: "ready",
      connection: "connected",
    });
    await expectActiveView(page, "en-US", "plan");

    // The learning drawer overlays the shell: close it to work in the
    // conversation.
    await closeLearningDrawer(page);
    const prompt = "How should I reason about the current learning step?";
    await page.locator("#coach-composer").fill(prompt);
    await page.locator(".composer__send").click();
    // Learning replies live in the main conversation flow now.
    await expect(page.locator('[data-surface="coach"] .message-bubble__body').last()).toBeVisible({ timeout: 30000 });
    await expect(page.locator('[data-surface="coach"]').getByText(prompt, { exact: true })).toHaveCount(1);
    await expectActiveView(page, "en-US", "coach");
    await expectNoConsoleErrors(errors);
  });

  test("instant practice stays in the Coach conversation and mints no training card", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "coach", {
      lang: "en-US",
      scenario: "ready",
      connection: "connected",
    });
    await expectActiveView(page, "en-US", "coach");
    const cardBefore = await page.evaluate(
      () => window.__TRAINER_BOOTSTRAP__?.workspaceTrainingState?.selectedCardId ?? null,
    );
    const inlineCardsBefore = await page.locator('[data-template="FocusedPractice"]').count();

    await page.locator("#coach-composer").fill("Give me a practice exercise about thread locks.");
    const bubblesBefore = await page.locator(".message-bubble__body").count();
    await page.locator(".composer__send").click();

    // P0: a plain exercise request is instant practice — inline conversation
    // reply, no card, no navigation into the training surface.
    await expect.poll(
      () => page.locator(".message-bubble__body").count(),
      { timeout: 30000 },
    ).toBeGreaterThan(bubblesBefore);
    await expectActiveView(page, "en-US", "coach");
    // The practice card that already lives in Chat is untouched: the exercise
    // request minted no new one.
    expect(await page.locator('[data-template="FocusedPractice"]').count()).toBe(inlineCardsBefore);
    const cardAfter = await page.evaluate(
      () => window.__TRAINER_BOOTSTRAP__?.workspaceTrainingState?.selectedCardId ?? null,
    );
    expect(cardAfter).toBe(cardBefore);
    await expectNoConsoleErrors(errors);
  });

  test("Learning presents progress, practice, and goals as three drawer sections", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "plan", {
      lang: "zh-CN",
      scenario: "ready",
      connection: "connected",
    });
    await expectActiveView(page, "zh-CN", "plan");

    // P1: 进度 / 练习 / 目标 are three sections of one learning drawer, not
    // three tabs and not three destinations.
    const drawer = page.locator('[data-template="LearningDrawer"]');
    await expect(drawer).toBeVisible();
    for (const section of ["goal", "practice", "progress"]) {
      await expect(page.locator(`[data-template="LearningDrawer"] > [data-learning-section="${section}"]`)).toBeVisible();
    }
    await expect(page.getByRole("tablist", { name: "当前学习" })).toHaveCount(0);

    // Three sections, one unified composer.
    await expect(page.locator("#coach-composer")).toHaveCount(1);
    await expectNoConsoleErrors(errors);
  });

  test("comparing library papers keeps the shared composer and reply in place", async ({ page }) => {
    await page.setViewportSize({ width: 420, height: 761 });
    await openPreview(page, "plan", { lang: "en-US", scenario: "ready", connection: "connected" });
    // The learning drawer overlays the shell: close it to work in the
    // conversation.
    await closeLearningDrawer(page);
    const input = page.locator('#coach-composer');
    await input.evaluate((element) => element.dataset.libraryAnalysisProbe = "same-composer");
    await input.fill("Search my library for papers about sequence modeling and compare their approaches.");
    await page.locator(".composer__send").click();

    const reply = page.locator('[data-surface="coach"] .message-bubble__body').filter({ visible: true }).last();
    await expect(reply).toBeVisible({ timeout: 30000 });
    await expect(reply).toBeInViewport();
    await expectActiveView(page, "en-US", "coach");
    await expect(input).toHaveAttribute("data-library-analysis-probe", "same-composer");
    const replyText = await reply.textContent();
    expect(replyText.trim()).not.toBe("");

    // The drawer overlays the shell: close it before using the nav.
    await closeLearningDrawer(page);
    await page.getByTestId(viewNavigationTestId("resources")).click();
    await expect(page.locator('[data-surface="resources"] .message-bubble__body')).toHaveCount(0);
    // The reply belongs to the one conversation: it comes back unchanged.
    await page.getByTestId(viewNavigationTestId("coach")).click();
    await expect(reply).toHaveText(replyText);
    await openLearningDrawer(page, "goal");
    await expect(reply).toHaveText(replyText);
  });

  test("searching the library from the composer shows the sources in Resources", async ({ page }) => {
    await page.setViewportSize({ width: 420, height: 761 });
    await openPreview(page, "plan", { lang: "en-US", scenario: "resource-preview-loaded", connection: "connected" });
    // The learning drawer overlays the shell: close it to work in the
    // conversation.
    await closeLearningDrawer(page);
    const input = page.locator('#coach-composer');
    await input.evaluate((element) => element.dataset.librarySearchProbe = "same-composer");
    await input.fill("/search Coach prompt patterns");
    await page.locator(".composer__send").click();

    // The library search belongs to the Resources destination now.
    const results = page.locator('[data-surface="resources"]');
    await expect(results.getByRole("button", { name: /coach prompt patterns/i }).first()).toBeVisible();
    await expectActiveView(page, "en-US", "resources");
    await expect(input).toHaveAttribute("data-library-search-probe", "same-composer");
    await input.fill("/search a source that definitely does not exist");
    await page.locator(".composer__send").click();
    await expect(results.getByText("No matching resources")).toBeVisible();
    await expect(results.locator("[data-citation-part]")).toHaveCount(0);
  });

  test("keeps an explicit preview view authoritative over saved browser-preview state", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const params = {
      lang: "en-US",
      scenario: "ready",
      connection: "connected",
    };

    await openPreview(page, "coach", params);
    await page.getByTestId(viewNavigationTestId("settings")).click();
    await expectActiveView(page, "en-US", "settings");

    await page.reload();
    await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
    await expectTwoPrimaryDestinations(page, "en-US");
    await expectActiveView(page, "en-US", "coach");
    await expect(page.locator(".composer-shell")).toBeVisible();
    await expectNoConsoleErrors(errors);
  });

  test("keeps Plan composer intent explicit without mutating the formal plan in the fixture", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const sidecarRequests = [];
    const modes = ["explain", "generate"];

    page.on("request", (request) => {
      if (/^http:\/\/127\.0\.0\.1:34891(?:\/|$)/.test(request.url())) {
        sidecarRequests.push(request.url());
      }
    });

    for (const mode of modes) {
      await openPreview(page, "plan", {
        lang: "en-US",
        scenario: "ready",
        connection: "connected",
      });
      await expectActiveView(page, "en-US", "plan");

      await expect(page.locator("[data-template=LearningHome]").first()).toBeVisible();
      // The route group is a collapsible card inside the learning drawer.
      await openLearningMore(page);
      const route = page.locator('[data-learning-section="route"]');
      // The route group is a plain row group in the drawer: the live stages are
      // readable without opening a fold.
      await expect(route.locator(':scope > summary')).toHaveCount(0);
      await expect(page.locator('[data-learning-section="route"] [data-plan-stage]').first()).toBeVisible();
      await expect(page.locator("[data-template=NextAction]").first()).toBeVisible();
      await expect(page.locator("[data-plan-governance-disclosure]")).toHaveCount(0);
      await expect(page.locator("[data-plan-evidence-list]").filter({ visible: true })).toHaveCount(0);
      const formalPlanBefore = await page.evaluate(() => {
        const plan = window.__TRAINER_BOOTSTRAP__?.plan;
        return {
          id: plan?.id,
          title: plan?.title,
          frozen: plan?.frozen,
          stageIds: plan?.stages?.map((stage) => stage.id),
          currentStageId: plan?.currentStageId,
        };
      });
      const message = `Local fixture assertion for ${mode} mode.`;
      const submitted = await submitPlanComposerRequest(page, mode, message);
      const formalPlanAfter = await page.evaluate(() => {
        const plan = window.__TRAINER_BOOTSTRAP__?.plan;
        return {
          id: plan?.id,
          title: plan?.title,
          frozen: plan?.frozen,
          stageIds: plan?.stages?.map((stage) => stage.id),
          currentStageId: plan?.currentStageId,
        };
      });
      expect(formalPlanAfter).toEqual(formalPlanBefore);
      if (!submitted) {
        // §3.7: the dock composer stays mounted on Learning; the disabled plan
        // intent only means no plan-composer draft is seeded.
        await expect(page.locator("#coach-composer")).toHaveCount(1);
        continue;
      }
      await expect.poll(() =>
        page.evaluate((expectedMessage) =>
          window.__TRAINER_BOOTSTRAP__?.conversation?.some(
            (entry) => entry.role === "user" && entry.body.includes(expectedMessage),
          ) ?? false,
        message),
      ).toBe(true);
      await expect.poll(() =>
        page.evaluate(() =>
          window.__TRAINER_BOOTSTRAP__?.conversation?.some(
            (entry) => entry.role === "assistant" && typeof entry.body === "string" && entry.body.trim().length > 0,
          ) ?? false,
        ),
      ).toBe(true);
    }

    expect(sidecarRequests).toEqual([]);
    await expectNoConsoleErrors(errors);
  });

  test("a failed connection test stays a non-blocking diagnostic in Coach", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "coach", {
      lang: "en-US",
      scenario: "provider-auth-failure-empty",
      connection: "connected",
    });

    await expectTwoPrimaryDestinations(page, "en-US");
    await expectActiveView(page, "en-US", "coach");
    // ProviderStatus contract: a historical failed test is a diagnostic, not a
    // send gate. The first real send is the live confirmation.
    await expect(page.locator(".coach-empty-state--blocked")).toHaveCount(0);
    await expect(page.locator(".composer-shell")).toBeVisible();
    await expect(page.locator("#coach-composer")).toBeVisible();
    await expectNoConsoleErrors(errors);
  });

  test("keeps a blocked Chinese Coach recovery short and moves to the one next step", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "coach", {
      lang: "zh-CN",
      scenario: "provider-auth-failure-empty",
      connection: "connected",
    });

    // A 401 test result is diagnostic history: it must not take over the
    // thread or turn a saved connection into a blocked empty state.
    await expect(page.locator(".coach-empty-state--blocked")).toHaveCount(0);
    await expect(page.locator(".composer-presencebar__blocked")).toHaveCount(0);
    await expect(page.locator("#coach-composer")).toBeVisible();
    await expect(page.locator(".composer-shell")).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/gateway|base URL|HTTP/i);
    await expectNoConsoleErrors(errors);
  });

  test("shows workspace admission once in Coach while keeping the composer disabled", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "coach", {
      lang: "zh-CN",
      scenario: "workspace-admission",
      workspaceAdmission: "project-found",
      connection: "connected",
      run: "workspace-admission-single-surface",
    });

    await expect(page.locator(".coach-workspace-admission")).toBeVisible();
    await expect(page.getByRole("button", { name: "加入 Trainer", exact: true })).toBeVisible();
    await expect(page.locator(".composer-presencebar__blocked")).toHaveCount(0);
    await expect(page.locator(".composer-shell textarea")).toBeDisabled();
    await expectNoHorizontalOverflow(page);
    await expectNoConsoleErrors(errors);
  });

  for (const language of ["zh-CN", "en-US"]) {
    for (const width of [300, 360, 420]) {
      test(`keeps two readable primary destinations at ${width}px in ${language}`, async ({ page }) => {
        const errors = attachConsoleErrorCollector(page);

        await page.setViewportSize({ width, height: 800 });
        await openPreview(page, "coach", {
          lang: language,
          scenario: "ready",
          connection: "connected",
        });

        await expectTwoPrimaryDestinations(page, language);
        await expectActiveView(page, language, "coach");
        // Usability contract at any width: the switcher either shows readable
        // labels or swaps to icons — every entry stays reachable either way.
        const switcher = page.locator(".app-shell-nav");
        const switcherClass = (await switcher.getAttribute("class")) ?? "";
        if (/header-switcher--icon/.test(switcherClass)) {
          const icons = switcher.locator(".app-shell-nav__icon");
          const iconCount = await icons.count();
          for (let index = 0; index < iconCount; index += 1) {
            await expect(icons.nth(index)).toBeVisible();
          }
        } else {
          await expectHeaderLabelsVisible(page);
        }
        await expectNoHorizontalOverflow(page);
        await expectNoConsoleErrors(errors);
      });
    }
  }

  for (const language of ["zh-CN", "en-US"]) {
    test(`keeps Resources as a compact searchable workspace tree in ${language}`, async ({ page }) => {
      const errors = attachConsoleErrorCollector(page);
      const copy = RESOURCE_COPY[language];

      await page.setViewportSize({ width: 360, height: 800 });
      await openPreview(page, "resources", {
        lang: language,
        scenario: "resource-preview-loaded",
        connection: "connected",
      });
      await expectActiveView(page, language, "resources");

      const library = page.getByRole("region", { name: copy.library, exact: true });
      const search = page.locator("#coach-composer");
      const librarySearchInput = library.locator("input[type=search]");
      const tree = library.getByRole("tree", { name: copy.library, exact: true });
      const toolbarButtons = library.locator(".resources-knowledge__actions").getByRole("button");
      const addResource = library.getByRole("button", {
        name: language === "zh-CN" ? "添加资料" : "Add resource",
        exact: true,
      });

      await expect(search).toBeVisible();
      await expect(librarySearchInput).toHaveCount(1);
      await expect(librarySearchInput).toBeVisible();
      await expect(addResource).toBeVisible();
      // The toolbar is one action now — the standalone refresh-index button is gone.
      await expect(toolbarButtons).toHaveCount(1);
      await expect(
        library.getByRole("button", { name: language === "zh-CN" ? "刷新索引" : "Refresh index", exact: true }),
      ).toHaveCount(0);
      await addResource.click();
      const importMenu = page.getByRole("menu", {
        name: language === "zh-CN" ? "添加资料" : "Add resource",
        exact: true,
      });
      await expect(importMenu).toBeVisible();
      // The menu is the library's only entry point: add files, add a folder,
      // add to the library (link / PDF / scan / repo) and — where the host can
      // run it — migrate an old library to Markdown.
      await expect(importMenu.getByRole("menuitem")).toHaveCount(4);
      await expect(importMenu.locator("[data-capture-entry='true']")).toHaveCount(1);
      await addResource.click();
      await expect(importMenu).toHaveCount(0);
      // Rows are plain entries: no multi-select tree and no checkboxes.
      await expect(tree).not.toHaveAttribute("aria-multiselectable");
      await expect(tree.getByRole("checkbox")).toHaveCount(0);

      const primaryTreeItem = tree.getByRole("treeitem", {
        name: copy.primaryResource,
        exact: true,
      });
      await expect(primaryTreeItem).toBeVisible();
      await expect(primaryTreeItem.locator("strong")).toHaveText(copy.primaryResource);
      // The kind glyph is an alpha-mask span, not an inline SVG.
      await expect(
        primaryTreeItem.locator(".resources-library-tree__kind[data-resource-kind]"),
      ).toHaveCount(1);

      await librarySearchInput.fill(copy.indexingResource);
      const indexingTreeItem = tree.getByRole("treeitem", {
        name: copy.indexingResource,
        exact: true,
      });
      await expect(indexingTreeItem).toBeVisible();
      await page.locator("[data-clear-resource-search]").click();
      await expect(librarySearchInput).toHaveValue("");

      await search.fill("/search " + copy.indexingResource);
      await search.press("Enter");
      await expect(indexingTreeItem).toBeVisible();
      // Per-row index-status badges are gone; the reader holds the status line.
      await expect(indexingTreeItem.locator(".resources-library-tree__status")).toHaveCount(0);

      await search.fill("/search no-resource-match");
      await search.press("Enter");
      await expect(tree.getByRole("treeitem")).toHaveCount(0);
      await expect(tree).toContainText(copy.noMatchesLabel);
      await page.locator("[data-clear-resource-search]").click();
      await expect(primaryTreeItem).toBeVisible();

      // Enter and Space both open the original source through the host; the
      // library never enters a Reader detail page.
      await primaryTreeItem.press("Enter");
      await expect(page.locator("[data-template=ResourceReader]")).toHaveCount(0);
      await primaryTreeItem.press(" ");
      await expect(page.locator("[data-template=ResourceReader]")).toHaveCount(0);
      await expect(primaryTreeItem).toBeVisible();
      await expect(library).toBeVisible();

      // Trash stays collapsed with per-item restore actions only; the bulk
      // restore and its refresh button are gone. The browser preview cannot
      // mutate real resources, so it offers no restore action at all — the
      // host bridge exercises the per-item restore in the lifecycle spec.
      const trash = library.locator(".resources-knowledge__trash");
      await expect(trash.locator("summary")).toContainText(copy.trash);
      await expect(trash.locator("summary")).toContainText("1");
      await trash.locator("summary").click();
      await expect(trash.getByText("Archived reference notes", { exact: true })).toBeVisible();
      await expect(
        trash.getByRole("button", { name: "Restore available resources", exact: true }),
      ).toHaveCount(0);
      await expect(trash.getByRole("button")).toHaveCount(0);

      await expectNoHorizontalOverflow(page);
      await expectNoConsoleErrors(errors);
    });
  }

  test("opens a resource source directly and keeps the library through a view round trip", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const copy = RESOURCE_COPY["zh-CN"];

    await openPreview(page, "resources", {
      lang: "zh-CN",
      scenario: "resource-preview-loaded",
      connection: "connected",
    });

    const library = page.getByRole("region", { name: copy.library, exact: true });
    await library.getByRole("treeitem", { name: copy.primaryResource, exact: true }).press("Enter");
    await expect(page.locator("[data-template=ResourceReader]")).toHaveCount(0);
    await expect(library).toBeVisible();

    await page.getByRole("button", { name: "对话", exact: true }).click();
    await expectActiveView(page, "zh-CN", "coach");
    await page.getByTestId("trainer-view-nav-resources").click();
    await expectActiveView(page, "zh-CN", "resources");
    await expect(page.locator("[data-template=ResourceReader]")).toHaveCount(0);
    await expectNoConsoleErrors(errors);
  });

  test("opens a Chinese resource source directly and keeps the library through Training and Settings", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const labels = {
      resources: "\u8d44\u6599",
      training: "\u8bad\u7ec3",
      settings: "\u8bbe\u7f6e",
      library: "\u8d44\u6599\u5e93",
      resource: "\u9879\u76ee\u6539\u9020\u7b14\u8bb0",
    };

    await openPreview(page, "resources", {
      lang: "zh-CN",
      scenario: "ready",
      connection: "connected",
      theme: "dark",
    });

    await expect(page.locator("body")).toHaveClass(/vscode-dark/);
    const library = page.getByRole("region", { name: labels.library, exact: true });
    await library.getByRole("treeitem", { name: labels.resource, exact: true }).press("Enter");
    await expect(page.locator("[data-template=ResourceReader]")).toHaveCount(0);

    for (const view of ["training", "settings", "resources"]) {
      if (view === "training") await openFocusedTraining(page, "zh-CN");
      else {
        // The learning drawer overlays the shell: close it before the header.
        await closeLearningDrawer(page);
        await page.getByTestId(viewNavigationTestId(view)).click();
      }
      await expectActiveView(page, "zh-CN", view);
    }

    await expect(page.locator("[data-template=ResourceReader]")).toHaveCount(0);
    await expect(library).toBeVisible();
    await expectNoConsoleErrors(errors);
  });

  test("keeps the Training return state after an ordinary view round trip", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "training", {
      lang: "en-US",
      scenario: "done",
      connection: "connected",
    });

    const card = page.getByRole("group", { name: "Current training card", exact: true });
    const returnAction = card.getByRole("button", { name: "Return result to Coach", exact: true }).first();
    await expect(card).toBeVisible();
    await expect(returnAction).toBeVisible();

    // The learning drawer overlays the shell: close it before the Chat nav.
    await closeLearningDrawer(page);
    await page.getByRole("button", { name: "Chat", exact: true }).click();
    await expectActiveView(page, "en-US", "coach");
    await openFocusedTraining(page);
    await expectActiveView(page, "en-US", "training");
    await expect(card).toBeVisible();
    await expect(returnAction).toBeVisible();
    await expectNoConsoleErrors(errors);
  });

  test("keeps fixture provider controls local and stays in Settings", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "settings", {
      lang: "zh-CN",
      scenario: "ready",
      connection: "connected",
    });
    await expectActiveView(page, "zh-CN", "settings");
    await openSettingsCategory(page, "connection");

    // The connection editor owns test/save now; no separate trust gate.
    await page.locator('[data-settings-detail="connection"] .settings-sheet__pane')
      .getByRole("button", { name: "编辑配置", exact: true }).click();
    await page.getByRole("button", { name: /测试连接|重新测试/ }).first().click();
    await expectActiveView(page, "zh-CN", "settings");
    await expect(page.locator(".template-global-state [data-template=SystemState]")).toContainText(
      "浏览器预览无法验证真实连接；开始对话前请在 VS Code 中测试。",
    );
    await expectNoConsoleErrors(errors);
  });

  for (const language of ["zh-CN", "en-US"]) {
    test(`keeps Training single-card and Learn-first in ${language}`, async ({ page }) => {
      const errors = attachConsoleErrorCollector(page);
      const copy = TRAINING_COPY[language];

      await openPreview(page, "training", {
        lang: language,
        scenario: "training-debug",
        submode: "learn-primer",
        connection: "connected",
      });
      await expectActiveView(page, language, "training");

      await page.evaluate(() => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
        type: "state/patch",
        payload: { workspaceTrainingState: {
          ...window.__TRAINER_BOOTSTRAP__.workspaceTrainingState,
          selectedCardStatus: "needs_primer",
        } },
      }));

      const card = page.getByRole("group", { name: copy.card, exact: true });
      await expect(card).toHaveCount(1);
      await expectTrainingLoop(card, "learn");
      await expect(card.locator(".template-activity-header__phase")).toContainText(copy.activeLearnStep);
      await expectTrainingCardFacts(card);
      await expect(page.locator(".training-card-nav")).toHaveCount(0);
      // Next Card lives only on the Return/terminal state, never during learn.
      await expect(card.locator('[data-training-next-card="true"]')).toHaveCount(0);
      await expect(card.locator('[data-training-card-fact="current"]')).toHaveCount(0);
      await expect(card.getByRole("button", { name: copy.startThisStep, exact: true })).toBeVisible();
      await expect(card.getByText(copy.verifyCurrentFile, { exact: true })).toHaveCount(0);
      await expectNoHorizontalOverflow(page);
      await expectNoConsoleErrors(errors);
    });
  }

  for (const language of ["zh-CN", "en-US"]) {
    test(`keeps Learning verification beside the shared composer in ${language}`, async ({ page }) => {
      const errors = attachConsoleErrorCollector(page);
      const copy = TRAINING_COPY[language];

      await openPreview(page, "training", {
        lang: language,
        scenario: "training-debug",
        connection: "connected",
      });
      await expectActiveView(page, language, "training");

      const card = page.getByRole("group", { name: copy.card, exact: true });
      const composer = page.locator(".composer-shell");
      await expect(card).toHaveCount(1);
      await expect(card.getByRole("button", { name: copy.verifyCurrentFile, exact: true })).toBeVisible();
      await expect(composer.locator('#coach-composer')).toBeVisible();
      // One Chat composer plus the practice card's own answer field.
      await expect(page.locator('#coach-composer')).toHaveCount(1);
      await expect(page.locator('[data-template="FocusedPractice"] textarea')).toHaveCount(1);
      await expect(composer.getByRole("button", { name: copy.verifyCurrentFile, exact: true })).toHaveCount(0);
      await expectNoConsoleErrors(errors);
    });
  }

  test("keeps Learn -> Try -> Verify -> Reflect -> Return evidence visible", async ({ page }) => {
    test.setTimeout(90_000);
    const errors = attachConsoleErrorCollector(page);
    const previewCommands = collectPreviewCommands(page);

    await openPreview(page, "training", {
      lang: "en-US",
      scenario: "training-debug",
      connection: "connected",
    });
    // The learning drawer overlays the shell: close it so the practice card is
    // reachable again.
    await closeLearningDrawer(page);
    let card = page.getByRole("group", { name: "Current training card", exact: true });
    await expectTrainingLoop(card, "try");
    await expectTrainingCardFacts(card);
    await expect(card).toContainText("Build one minimal debug loop");
    await expect(card.locator('[data-training-card-fact="verify"]')).toContainText("Verify");
    await revealTrainingCardDetails(card);
    await expect(card.locator('[data-training-card-fact="return"]')).toContainText(
      "Return with the repro step",
    );

    await openPreview(page, "training", {
      lang: "en-US",
      scenario: "training-debug",
      submode: "learn-primer",
      connection: "connected",
    });
    card = page.getByRole("group", { name: "Current training card", exact: true });
    await expectTrainingLoop(card, "learn");
    // The learn face owns the card; the task-details disclosure is hidden.
    await expect(card.locator('[data-training-card-details]')).toHaveCount(0);
    await expectTrainingCardFacts(card);

  });

  test("reflect pass records a local reflection and flows to return", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const previewCommands = collectPreviewCommands(page);

    await openPreview(page, "training", {
      lang: "en-US",
      scenario: "training-debug",
      submode: "review",
      connection: "offline",
    });
    // The learning drawer overlays the shell: close it so the practice card is
    // reachable again.
    await closeLearningDrawer(page);
    let card = page.getByRole("group", { name: "Current training card", exact: true });
    await expectTrainingLoop(card, "reflect");
    await expectTrainingCardFacts(card);
    const reflection = "The focused check proves the boundary before the result can return.";
    // The reflection lives in the practice card's own answer field now.
    const reflectionInput = page.getByRole("textbox", {
      name: "Response",
      exact: true,
    });
    // The reflection is submitted from the practice card's own answer form.
    const emptyReflectButton = page.locator('[data-inline-practice-answer="true"] button[type="submit"]');
    await expect(reflectionInput).toBeEditable();
    await expect(emptyReflectButton).toBeDisabled();
    await reflectionInput.fill(reflection);
    const reflectButton = page.locator('[data-inline-practice-answer="true"] button[type="submit"]');
    await expect(reflectButton).toBeEnabled();
    await reflectButton.click();
    await expect.poll(() =>
      page.evaluate(() => {
        const state = window.__TRAINER_BOOTSTRAP__?.workspaceTrainingState;
        return {
          eventType: state?.trainingEventLedger?.at(-1)?.eventType,
          selectedCardStatus: state?.selectedCardStatus,
          handoffStatus: state?.latestTrainingHandoff?.handoffStatus,
          nextHopStatus: state?.latestTrainingNextHop?.status,
        };
      }),
    ).toEqual({
      eventType: "training_reflect",
      selectedCardStatus: "reflected",
      handoffStatus: "ready_to_return",
      nextHopStatus: "return_required",
    });
    await expect.poll(() =>
      page.evaluate(() =>
        window.__TRAINER_BOOTSTRAP__?.workspaceTrainingState?.trainingEventLedger?.at(-1)?.statusDetail,
      ),
    ).toContain("Reflection captured locally");
    await expect.poll(() =>
      page.evaluate(() =>
        window.__TRAINER_BOOTSTRAP__?.workspaceTrainingState?.latestTrainingHandoff?.returnMode,
      ),
    ).toBe("return_required");
    expect(
      previewCommands.some(
        (command) => command?.payload?.commandId === "trainer.training.reflect",
      ),
    ).toBeTruthy();

    card = page.getByRole("group", { name: "Current training card", exact: true });
    await expectTrainingLoop(card, "return");
    await revealTrainingCardDetails(card);
    await expect(card.locator('[data-training-card-fact="return"]')).toContainText(
      "Return with the repro step",
    );
    await card.getByRole("button", { name: TRAINING_COPY["en-US"].returnToCoach, exact: true }).first().click();
    await expect.poll(() =>
      page.evaluate(() => {
        const state = window.__TRAINER_BOOTSTRAP__?.workspaceTrainingState;
        return {
          eventType: state?.trainingEventLedger?.at(-1)?.eventType,
          selectedCardStatus: state?.selectedCardStatus,
          handoffStatus: state?.latestTrainingHandoff?.handoffStatus,
          nextHopStatus: state?.latestTrainingNextHop?.status,
        };
      }),
    ).toEqual({
      eventType: "training_return",
      selectedCardStatus: "returned",
      handoffStatus: "returned",
      nextHopStatus: "continued_in_chat",
    });
    expect(
      previewCommands.some(
        (command) => command?.payload?.commandId === "trainer.training.return",
      ),
    ).toBeTruthy();
    // No auto-jump to Coach: the card settles in its terminal state and the
    // Training route stays active, with Next Card available from there.
    const complete = card.locator('[data-training-return-complete="true"]');
    await expect(complete).toBeVisible();
    await expect(complete).toContainText("Done");
    await expect(complete).toContainText("Your result is with the coach");
    await expect(complete.locator('[data-training-next-card="true"]')).toBeVisible();
    await expectActiveView(page, "en-US", "training", { drawerClosed: true });
    await expectNoConsoleErrors(errors);
  });

  test("keeps task details lightweight beside the one current card", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await page.setViewportSize({ width: 360, height: 900 });
    await openPreview(page, "training", {
      lang: "zh-CN",
      scenario: "training-remote",
      connection: "connected",
    });
    // The learning drawer overlays the shell: close it so the practice card is
    // reachable again.
    await closeLearningDrawer(page);

    const training = page.locator(".training-pane--card-only");
    await expect(training.locator(".template-activity-header h2")).toBeVisible();
    await expect(training.locator("[data-training-next-hop=\"true\"]")).toHaveCount(0);
    await expect(training.locator(":scope > .training-carryover-row")).toHaveCount(0);
    // The three background disclosures collapsed into one task-details
    // disclosure, closed by default; the "More → Next Card" disclosure is gone
    // because Next Card now lives only on the Return/terminal state.
    const taskDetails = training.locator("[data-training-card-details]");
    await expect(training.locator(".template-focused-practice > details")).toHaveCount(1);
    await expect(taskDetails).toHaveCount(1);
    await expect(taskDetails).not.toHaveAttribute("open", "");
    await expect(taskDetails.locator(":scope > summary")).toContainText("任务详情");
    await expect(training.locator(".training-current__more")).toHaveCount(0);
    await expect(training.locator(".training-loop-rail")).toHaveCount(0);
    await expect(training.locator('[data-training-next-card]')).toHaveCount(0);
    await expect(training.getByText("更多", { exact: true })).toHaveCount(0);
    await taskDetails.locator(":scope > summary").click();
    await expectTrainingCardFacts(training);
    await expectNoHorizontalOverflow(page);
    await expectNoConsoleErrors(errors);
  });

  for (const scenario of [
    {
      id: "remote",
      preview: "training-remote",
      title: "Verify the remote workspace boundary",
      taskEvidence: "Prove which machine owns the workspace files",
      returnEvidence: "Return with the remote type",
    },
    {
      id: "debug",
      preview: "training-debug",
      title: "Narrow the debug loop",
      taskEvidence: "Build one minimal debug loop",
      returnEvidence: "Return with the repro step",
    },
    {
      id: "function",
      preview: "training-function",
      title: "Recover a function contract with editor guidance",
      taskEvidence: "Open a real call site, then use hover and Go to Definition to see the parameters and return value",
      returnEvidence: "Return with the function contract",
      // The function pack ships only placeholder file targets ("<live call
      // site>"), so r1-g1-5 keeps it a manual practice: the card shows no raw
      // placeholder and no card-level action — the answer flows through the
      // unified composer ("Submit the current training note").
      answerFlow: "composer",
      rawPlaceholder: "<live call site>",
    },
  ]) {
    test(`renders the ${scenario.id} training scenario with concrete evidence`, async ({ page }) => {
      const errors = attachConsoleErrorCollector(page);

      await openPreview(page, "training", {
        lang: "en-US",
        scenario: scenario.preview,
        connection: "connected",
      });
      // The learning drawer overlays the shell: close it so the practice card
      // is reachable again.
      await closeLearningDrawer(page);

      const card = page.getByRole("group", { name: "Current training card", exact: true });
      await expect(card.getByRole("heading", { name: scenario.title, exact: true })).toBeVisible();
      await expectTrainingLoop(card, "try");
      await expectTrainingCardFacts(card);
      await expect(card).toContainText(scenario.taskEvidence);
      await expect(card.locator('[data-training-card-fact="verify"]')).toContainText("Verify");
      await expect(card.locator('[data-training-card-fact="return"]')).toContainText(
        scenario.returnEvidence,
      );
      // File-bound practices answer with the in-card Verify action; manual
      // practices answer through the unified composer. Neither surfaces a
      // verify button in the composer shell.
      if (scenario.answerFlow === "composer") {
        if (scenario.rawPlaceholder) {
          await expect(card).not.toContainText(scenario.rawPlaceholder);
        }
        // A manual practice answers in the practice card's own answer field.
        await expect(page.locator('[data-inline-practice-answer="true"]')).toBeVisible();
        await expect(card.getByRole("button", { name: "Verify current file", exact: true })).toHaveCount(0);
      } else {
        await expect(card.getByRole("button", { name: "Verify current file", exact: true })).toBeVisible();
      }
      await expect(
        page.locator(".composer-shell").getByRole("button", {
          name: "Verify current file",
          exact: true,
        }),
      ).toHaveCount(0);
      await expectNoConsoleErrors(errors);
    });
  }

  test("candidate management discloses merge, importance, and priority on a candidate card", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const commands = collectPreviewCommands(page);

    await page.setViewportSize({ width: 420, height: 761 });
    await page.goto("/vscode-preview.html?view=training&lang=en-US&connection=connected&run=candidate-manage");
    await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
    await page.evaluate(() => {
      const current = window.__TRAINER_BOOTSTRAP__;
      const workspaceId = "workspace-candidate-manage";
      const keeper = {
        cardId: "card-candidate-e2e",
        type: "practice",
        title: "Candidate management card",
        status: "candidate",
        learningPhase: "learn",
        focusArea: "candidate management",
        targetSkill: "candidate management",
        problemStatement: "Decide which candidates are worth keeping.",
        suggestedWorkspaceAction: "Review the candidate.",
        answerMode: "text",
      };
      const duplicate = {
        ...keeper,
        cardId: "card-dup-e2e",
        title: "Duplicate candidate",
      };
      window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({ type: "bootstrap", payload: {
        ...current, plan: null, sessionHistoryRestored: true,
        memory: { ...current.memory, workspace: {
          ...current.memory.workspace, workspaceId,
          liveTrainingSelection: { workspaceId, cardId: keeper.cardId, selectedAt: "2026-11-17T00:00:00Z" },
        } },
        workspaceTrainingState: {
          workspaceId,
          selectedCardId: keeper.cardId,
          selectedCardType: "practice",
          selectedCardTitle: keeper.title,
          selectedCardStatus: "candidate",
          trainingCardCandidates: [keeper, duplicate],
          activeTrainingCardRouting: { selectedCardId: keeper.cardId, selectedCard: keeper,
            candidateCount: 2, eligibleCount: 2 },
        },
      } });
    });

    // The learning drawer overlays the shell: close it before working with the
    // card, then open the candidate-management disclosure on the card itself.
    await closeLearningDrawer(page);
    const card = page.getByRole("group", { name: "Current training card", exact: true });
    const manage = card.locator("[data-candidate-management=true]");
    await expect(manage).toBeVisible();
    await manage.locator(":scope > summary").click();
    await expect(manage).toHaveAttribute("open", "");
    await expect(manage.locator("[data-candidate-merge='card-dup-e2e']")).toBeVisible();

    // The learner's decisions travel to the host as management commands; the
    // sidecar owns the card records and the ledger.
    await manage.locator("[data-candidate-action=important]").click();
    await expect.poll(() => commands.some((command) =>
      command?.payload?.commandId === "trainer.trainingCard.markImportant" &&
      command?.payload?.payload?.cardId === "card-candidate-e2e" &&
      command?.payload?.payload?.important === true)).toBe(true);

    await manage.locator("[data-candidate-priority=true] select").selectOption("-1");
    await expect.poll(() => commands.some((command) =>
      command?.payload?.commandId === "trainer.trainingCard.setPriority" &&
      command?.payload?.payload?.priority === -1)).toBe(true);

    await manage.locator("[data-candidate-merge='card-dup-e2e']").click();
    await expect.poll(() => commands.some((command) =>
      command?.payload?.commandId === "trainer.trainingCard.merge" &&
      command?.payload?.payload?.keepCardId === "card-candidate-e2e" &&
      JSON.stringify(command?.payload?.payload?.duplicateCardIds) === JSON.stringify(["card-dup-e2e"]))).toBe(true);
    await expectActiveView(page, "en-US", "training", { drawerClosed: true });
    await expectNoConsoleErrors(errors);
  });

  test("keeps a selected Spanish training card and composer in Spanish", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "training", {
      lang: "es-ES",
      scenario: "training-remote",
      connection: "connected",
    });

    await expectTwoPrimaryDestinations(page, "es-ES");
    await expectActiveView(page, "es-ES", "training");
    // The learning drawer overlays the shell: close it to work with the card.
    await closeLearningDrawer(page);
    const card = page.getByRole("group", { name: "Tarjeta de entrenamiento actual", exact: true });
    const composer = page.locator(".composer-shell");
    await expect(card.getByRole("heading", { name: /Práctica: espacio de trabajo remoto de VS Code/ })).toBeVisible();
    await revealTrainingCardDetails(card);
    await expectTrainingLoop(card, "try");
    await expectTrainingCardFacts(card);
    await expect(composer.locator('#coach-composer')).toBeVisible();
    // One Chat composer plus the practice card's own answer field.
    await expect(page.locator('#coach-composer')).toHaveCount(1);
    await expect(page.locator('[data-template="FocusedPractice"] textarea')).toHaveCount(1);
    const verifyButton = card.getByRole("button", {
      name: "Verificar archivo actual",
      exact: true,
    });
    if ((await verifyButton.count()) > 0) {
      await expect(verifyButton).toBeVisible();
    }
    await expectNoConsoleErrors(errors);
  });

  test("keeps the composer model switch inside the coach input shell", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    for (const language of ["zh-CN", "en-US"]) {
      await openPreview(page, "coach", {
        lang: language,
        scenario: "ready",
        connection: "connected",
      });

      await expectActiveView(page, language, "coach");
      await expect(page.locator(".composer-shell .composer__buttons")).toBeVisible();
      const modelButton = page.getByRole("button", { name: "gpt-4.1-mini" }).first();
      await expect(modelButton).toBeVisible();
      await expect(
        page.getByRole("button", {
          name: language === "zh-CN" ? "打开模型设置" : "Open model settings",
        }),
      ).toHaveCount(0);
      await modelButton.click();
      await expect(page.locator(".composer-menu-panel--provider")).toBeVisible();
    }

    await expectNoConsoleErrors(errors);
  });

  test("collapses the composer model switch to an accessible icon in a narrow sidebar", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await page.setViewportSize({ width: 360, height: 800 });
    await openPreview(page, "coach", {
      lang: "zh-CN",
      scenario: "ready",
      connection: "connected",
    });

    const modelButton = page.getByRole("button", { name: /切换模型：gpt-4\.1-mini/ }).first();
    await expect(modelButton).toBeVisible();
    await expect(modelButton).toHaveClass(/icon-button/);
    await expect(modelButton.locator("svg")).toBeVisible();
    await expect(modelButton.locator(".composer-secondary-button__label")).toHaveCount(0);
    await modelButton.click();
    await expect(page.locator(".composer-menu-panel--provider")).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await expectNoConsoleErrors(errors);
  });

  test("restores a requested five-view destination from a host message", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "coach", {
      lang: "en-US",
      scenario: "ready",
      connection: "connected",
    });

    await page.evaluate(() => {
      window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__?.({
        type: "ui/restoreView",
        payload: { activeView: "training" },
      });
    });

    await expectActiveView(page, "en-US", "training");
    await expectNoConsoleErrors(errors);
  });

  test("attaches a scratch-paper image from the Add menu and sends it to the preview coach", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const sidecarRequests = [];

    page.on("request", (request) => {
      if (/^http:\/\/127\.0\.0\.1:34891(?:\/|$)/.test(request.url())) {
        sidecarRequests.push(request.url());
      }
    });

    await openPreview(page, "coach", {
      lang: "en-US",
      scenario: "vision-ready",
      connection: "connected",
    });

    const image = await page.evaluate(() => {
      const canvas = document.createElement("canvas");
      canvas.width = 320;
      canvas.height = 80;
      const context = canvas.getContext("2d");
      context.fillStyle = "white";
      context.fillRect(0, 0, 320, 80);
      context.fillStyle = "black";
      context.font = "24px monospace";
      context.fillText("HTTP 401: wrong password", 8, 40);
      return canvas.toDataURL("image/png").split(",")[1];
    });
    await page.getByRole("button", { name: "Add", exact: true }).click();
    const fileChooser = page.waitForEvent("filechooser");
    await page.getByRole("menuitem", { name: "Attachment", exact: true }).click();
    await (await fileChooser).setFiles({ name: "scratch-paper.png", mimeType: "image/png", buffer: Buffer.from(image, "base64") });
    await expect(page.locator(".composer__attachment-chip")).toContainText("scratch-paper.png");
    await expect(page.locator(".composer__send")).toBeEnabled();
    await page.locator(".composer__send").click();

    await expect(page.locator('[data-role="assistant"]').last()).toContainText(
      "Inspect the attached image.",
    );
    await expect(page.locator(".composer__attachment-chip")).toHaveCount(0);
    await expect(page.locator("#coach-composer")).toBeEnabled();
    await expect(page.locator("#coach-composer")).toHaveValue("");
    expect(sidecarRequests).toEqual([]);
    await expectNoConsoleErrors(errors);
  });

  test("image staging rejects a malformed batch without changing the coach draft", async ({ page }) => {
    await openPreview(page, "coach", { lang: "en-US", scenario: "vision-ready", connection: "connected" });
    await page.locator("#coach-composer").fill("Keep this explanation while I attach a screenshot.");
    await page.locator(".composer__frame").evaluate(async (frame) => {
      const canvas = document.createElement("canvas");
      canvas.width = 20;
      canvas.height = 20;
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
      const transfer = new DataTransfer();
      transfer.items.add(new File([blob], "valid.png", { type: "image/png" }));
      transfer.items.add(new File([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])], "broken.png", { type: "image/png" }));
      frame.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: transfer }));
    });
    await expect(page.locator('.composer [data-template="SystemState"]')).toContainText("PNG");
    await expect(page.locator(".composer__attachment-chip")).toHaveCount(0);
    await expect(page.locator("#coach-composer")).toHaveValue("Keep this explanation while I attach a screenshot.");
    await expect(page.locator(".composer__send")).toBeEnabled();
  });

  test("offers scoped context when @ is typed in the coach composer", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    for (const language of ["zh-CN", "en-US"]) {
      await openPreview(page, "coach", {
        lang: language,
        scenario: "ready",
        connection: "connected",
      });

      await page.locator("#coach-composer").press("@");
      await expect(page.locator(".composer__mention-item").first()).toBeVisible();
    }

    await expectNoConsoleErrors(errors);
  });

  test("shows protocol truth inside Settings connection details", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "settings", {
      lang: "en-US",
      scenario: "ready",
      connection: "connected",
    });

    await expectActiveView(page, "en-US", "settings");
    // The connected state shows the compact summary card — edit mode is the
    // single complete configuration surface.
    await openSettingsCategory(page, "connection");
    const editButton = page.getByRole("button", { name: "Edit configuration", exact: true });
    await expect(editButton).toBeVisible();
    await editButton.click();
    await expect(page.locator("main")).toContainText("Protocol");
    await expect(page.locator("main")).toContainText("Connection diagnostics");
    await expect(page.locator("main")).toContainText("Add provider");
    await expect(page.locator("main")).toContainText("Final capabilities");
    await expect(page.locator("main")).toContainText(/chat\s*Ready/);
    await expect(page.getByText("Connection needs test", { exact: true })).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
    await expectNoConsoleErrors(errors);
  });

  test("keeps the connected preview provider identity internally consistent", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "settings", {
      lang: "en-US",
      scenario: "ready",
      connection: "connected",
      run: "provider-identity-truth",
    });

    const main = page.locator("main");
    await expect(main).toContainText("Local compatible service");
    await expect(main).toContainText("gpt-4.1-mini-compatible");
    await expect(main).not.toContainText("MiniMax Core");
    await expectNoConsoleErrors(errors);
  });

  test("composer-only Chinese send shows a user bubble and does not echo the full sentence", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const draft = "卡在验证上了";

    await openPreview(page, "coach", {
      lang: "zh-CN",
      scenario: "ready",
      connection: "connected",
    });

    await expect(page.getByText("开始说", { exact: true })).toHaveCount(0);
    const composer = page.locator("#coach-composer");
    await composer.fill(draft);
    await page.getByRole("button", { name: "发送消息", exact: true }).click();
    await expect(page.locator('[data-role="user"]').last()).toContainText(draft);
    await expect(composer).toHaveValue("");
    const assistant = page.locator('[data-role="assistant"]').last();
    await expect(assistant).toBeVisible();
    const assistantText = (await assistant.innerText()).trim();
    expect(assistantText === draft).toBe(false);
    expect(assistantText.includes(`\n${draft}`) || assistantText.endsWith(draft)).toBe(false);
    await expectNoConsoleErrors(errors);
  });

  test("keeps stream progress in the Coach thread and reserves the global notice for failures", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "coach", {
      lang: "zh-CN",
      scenario: "ready",
      connection: "connected",
    });

    await page.evaluate(() => {
      window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__?.({
        type: "stream/start",
        payload: { messageId: "e2e-stream-progress" },
      });
      window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__?.({
        type: "operation/status",
        payload: {
          tone: "info",
          message: "正在等待回复",
          phase: "awaiting_response",
          surface: "stream",
        },
      });
    });

    await expect(page.locator(".notice")).toHaveCount(0);
    await expect(page.locator(".message-bubble--streaming")).toBeVisible();
    // No canned sentence before the first chunk: one quiet working label.
    await expect(page.locator(".message-bubble--streaming .coach-working__label")).toHaveText("正在思考");
    await expect(page.locator(".message-bubble--streaming")).not.toContainText(
      "正在梳理你的问题",
    );

    await page.evaluate(() => {
      window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__?.({
        type: "operation/status",
        payload: {
          tone: "error",
          message: "本次回复失败，请重试。",
          phase: "failed",
          surface: "stream",
        },
      });
    });

    await expect(page.locator("[data-system-state=recoverable-error]")).toBeVisible();
    await expect(page.locator("[data-system-state=recoverable-error]")).toContainText("再试一次");
    await expectNoConsoleErrors(errors);
  });

  test("plan evidence click reveals pending evidence and matches composer mode", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "plan", {
      lang: "zh-CN",
      scenario: "ready",
      connection: "connected",
    });

    const source = planOnlyFixture(await page.evaluate(() => window.__TRAINER_BOOTSTRAP__));
    const workspaceId = source.memory.workspace.workspaceId;
    const step = '核对当前文件的边界检查结果';
    const runtime = { recovered: true, planId: 'evidence-context-plan', currentStep: step, resumeState: 'in_progress' };
    const payload = { ...source, conversation: [], sessionHistoryRestored: true, hasFormalPlan: true,
      plan: { ...source.plan, id: runtime.planId, currentStep: step, frozen: false }, planRuntimeStatus: runtime,
      memory: { ...source.memory, workspace: { ...source.memory.workspace, latestPlanRuntime: runtime },
        evidenceQueue: { pending: [{ id: 'current-evidence', summary: '当前结果尚待核对', targetPlanStep: step,
          outcome: 'self_reported', timestamp: new Date().toISOString() },
          { id: 'old-evidence', summary: '其它步骤的结果', targetPlanStep: '其它步骤', outcome: 'self_reported' }],
        adopted: [], rejected: [], deferred: [], totalCount: 2 } },
    };
    await page.addInitScript(({ payload, workspaceId }) => {
      window.__EVIDENCE_CONTEXT_ACTIONS__ = [];
      window.acquireVsCodeApi = () => ({ getState: () => ({ activeView: 'plan', composerLanguage: 'zh-CN' }),
        setState() {}, postMessage(message) {
          window.__EVIDENCE_CONTEXT_ACTIONS__.push(message);
          if (message.type === 'request/bootstrap') setTimeout(() => window.postMessage({ type: 'bootstrap',
            sync: { generation: 1, revision: 1, baseRevision: 0, messageId: 'evidence-context', workspaceId,
              sessionId: 'evidence-context-session' }, payload }, location.origin), 0);
        } });
    }, { payload, workspaceId });
    await page.goto('/');
    // Learning is not a destination any more: the legacy learning route
    // resolves to Chat with the learning drawer opened on the goal section.
    await openLearningDrawer(page, 'goal');
    const primary = page.locator('[data-template="LearningDrawer"] [data-template=NextAction]');
    await expect(primary.locator('h3')).toHaveText(step);
    await expect(primary.getByRole('button')).toHaveAttribute('data-action-intent', 'continue_step');
    await expect(page.locator('[data-plan-governance-disclosure]')).toHaveCount(0);
    await expect(page.locator('[data-plan-evidence-row="pending"]')).toHaveCount(0);
    await expect(page.getByTestId("trainer-view-nav-coach")).toHaveAttribute("aria-current", "page");
    await expect(page.locator("#coach-composer")).toBeEditable();
    expect(await page.evaluate(() => window.__EVIDENCE_CONTEXT_ACTIONS__
      .filter(message => message.type.startsWith('session/send') || message.payload?.commandId === 'trainer.evidence.adopt'))).toEqual([]);
    // The learning drawer overlays the shell: close it before sending from the
    // single shared conversation composer.
    await closeLearningDrawer(page);
    await page.locator("#coach-composer").fill('请帮我整理当前待核对的证据。');
    await page.locator('.composer__send').click();
    await expect.poll(() => page.evaluate(() => window.__EVIDENCE_CONTEXT_ACTIONS__
      .some(message => message.type.startsWith('session/send')))).toBe(true);
    const sent = await page.evaluate(() => window.__EVIDENCE_CONTEXT_ACTIONS__
      .find(message => message.type.startsWith('session/send')));
    expect(sent.payload).toMatchObject({ formalPlanMutation: false });
    expect(sent.operation).toMatchObject({ workspaceId, sessionId: 'evidence-context-session' });
    expect(await page.evaluate(() => window.__EVIDENCE_CONTEXT_ACTIONS__
      .filter(message => message.payload?.commandId === 'trainer.evidence.adopt'))).toEqual([]);
    await expectNoConsoleErrors(errors);
  });

  test("resources row opens the source without a Reader title or English write-authority leftover", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const copy = RESOURCE_COPY["zh-CN"];

    await openPreview(page, "resources", {
      lang: "zh-CN",
      scenario: "resource-preview-loaded",
      connection: "connected",
    });

    await page.getByRole("treeitem", { name: copy.primaryResource, exact: true }).press("Enter");
    await expect(page.locator("[data-template=ResourceReader]")).toHaveCount(0);
    await expect(page.locator("main")).not.toContainText("write authority has not been verified");
    await expect(page.getByRole("button", { name: "添加资料", exact: true })).toBeVisible();
    await expectNoConsoleErrors(errors);
  });

  test("training verify names a concrete reason and does not leak to Settings", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "training", {
      lang: "zh-CN",
      scenario: "training-debug",
      connection: "connected",
    });
    // The learning drawer overlays the shell: close it so the practice card is
    // reachable again.
    await closeLearningDrawer(page);

    await page.getByRole("button", { name: "验证当前文件", exact: true }).click();
    await expect(page.locator("[data-template=VerificationResult]")).toContainText(/没有可验证的当前文件|预览不能验|验证未通过/);
    await expect(page.locator("main")).not.toContainText("这一步暂时没完成。再试一次。");
    await page.getByTestId(viewNavigationTestId("settings")).click();
    await expectActiveView(page, "zh-CN", "settings");
    await expect(page.locator(".template-global-state [data-template=SystemState]")).toHaveCount(0);
    await expectNoConsoleErrors(errors);
  });

  test("settings first-screen language switch stays on Settings", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "settings", {
      lang: "zh-CN",
      scenario: "ready",
      connection: "connected",
    });

    await openSettingsCategory(page, "preferences");
    const languageRow = page.locator("[data-settings-language]");
    await expect(languageRow).toBeVisible();
    await languageRow.getByRole("button").click();
    await languageRow.getByRole("option", { name: "English", exact: true }).click();
    await expectActiveView(page, "en-US", "settings");
    await expect(page.getByTestId(viewNavigationTestId("settings"))).toHaveAttribute("aria-label", "Settings");
    await expectNoConsoleErrors(errors);
  });

  test("settings without a workspace root does not claim the model is ready", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "settings", {
      lang: "zh-CN",
      scenario: "workspace-admission",
      workspaceAdmission: "root-missing",
      connection: "connected",
    });

    await expectActiveView(page, "zh-CN", "settings");
    await openSettingsCategory(page, "connection");
    // The connection category reports provider readiness truthfully, but never
    // upgrades that into a workspace-wide "model ready" claim.
    const connection = page.locator('[data-settings-detail="connection"]');
    await expect(connection).toContainText("已就绪");
    await expect(connection).not.toContainText("模型已就绪");
    // The missing root is surfaced where the learner can act on it.
    await openSettingsCategory(page, "workspace");
    await expect(page.locator('[data-settings-detail="workspace"]')).toContainText(
      /工作区|根目录|学习文件夹/,
    );
    await expectNoConsoleErrors(errors);
  });

  test("blocked connection keeps one next step without FirstLook percentage", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "coach", {
      lang: "zh-CN",
      scenario: "provider-auth-failure-empty",
      connection: "connected",
    });

    await expect(page.locator(".coach-empty-state--blocked")).toHaveCount(0);
    await expect(page.locator("#coach-composer")).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/桌面应用\s*94%/);
    await expect(page.locator(".first-look-summary, .firstlook-summary, .FirstLookSummaryPanel")).toHaveCount(0);
    await expectNoConsoleErrors(errors);
  });

  test("empty canvas does not claim the current project is ready", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "coach", {
      lang: "zh-CN",
      scenario: "empty",
      connection: "connected",
    });

    await expect(page.locator("main")).not.toContainText("当前项目就绪");
    await expect(page.getByText("开始说", { exact: true })).toHaveCount(0);
    await expect(page.locator(".coach-empty-state")).toContainText("你在做什么？");
    await expect(page.locator("#coach-composer")).toBeVisible();
    await expectNoConsoleErrors(errors);
  });

  test("360px training keeps two primary destinations and one action with no overflow", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await page.setViewportSize({ width: 360, height: 800 });
    await openPreview(page, "training", {
      lang: "zh-CN",
      scenario: "training-debug",
      connection: "connected",
    });

    await expectTwoPrimaryDestinations(page, "zh-CN");
    await expectHeaderLabelsVisible(page);
    await expect(page.getByRole("button", { name: "验证当前文件", exact: true })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await expectNoConsoleErrors(errors);
  });

  test("history drawer groups sessions and offers a new chat entry", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "coach", { lang: "zh-CN", connection: "connected" });

    await page.getByRole("button", { name: "会话历史", exact: true }).click();
    const panel = page.locator(".app-shell-overlay__panel");
    await expect(panel).toBeVisible();
    // ChatGPT-style header: new chat on top, search below.
    await expect(panel.getByText("新对话", { exact: true })).toBeVisible();
    await expect(panel.getByPlaceholder("搜索会话…")).toBeVisible();
    // The preview session bucket lands in the "Today" group.
    await expect(panel.getByText("今天", { exact: true })).toBeVisible();
    // Searching hides the non-matching current session list but keeps the group shell honest.
    await panel.getByPlaceholder("搜索会话…").fill("绝对不存在的会话关键字");
    await expect(panel.getByText("没有匹配的会话。", { exact: true })).toBeVisible();
    await expectNoConsoleErrors(errors);
  });

  test("hint ladder reveals one hint at a time on the practice surface", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "training", {
      lang: "zh-CN",
      scenario: "training-debug",
      connection: "connected",
    });
    // The learning drawer overlays the shell: close it so the practice card is
    // reachable again.
    await closeLearningDrawer(page);

    // §五: hidden by default, advanced one step at a time.
    const revealGroup = page.getByRole("group", { name: "提示阶梯" });
    await expect(revealGroup).toBeVisible();
    await expect(revealGroup.locator("li")).toHaveCount(0);
    const revealButton = revealGroup.getByRole("button");
    const labelText = (await revealButton.textContent()) || "";
    const total = Number(labelText.match(/\d+$/)?.[0]) || 0;
    expect(total).toBeGreaterThan(0);
    for (let revealed = 1; revealed <= total; revealed += 1) {
      await revealButton.click();
      await expect(revealGroup.locator("li")).toHaveCount(revealed);
    }
    await expect(revealButton).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
    await expectNoConsoleErrors(errors);
  });

  test("progress view presents capability states with evidence counts", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "progress", { lang: "zh-CN", connection: "connected" });

    // Growth is the learning drawer's progress section now — the separate
    // Growth page is gone.
    const progress = page.locator('[data-template="LearningDrawer"] [data-learning-section="progress"]');
    await expect(progress).toBeVisible();
    await expect(progress.locator('[data-capability-bar="true"]')).toHaveCount(1);
    await expect(progress.getByText("理解", { exact: true })).toBeVisible();
    await expect(progress.getByText("稳定掌握", { exact: true })).toBeVisible();
    await expect(progress.getByText("调试", { exact: true })).toBeVisible();
    await expect(progress.getByText("独立完成", { exact: true })).toBeVisible();
    await expect(progress.getByText("迁移", { exact: true })).toBeVisible();
    // §25: evidence counts are expressed as coaching language.
    await expect(progress.getByText("9 次", { exact: true })).toBeVisible();
    // §66 restraint: no gamified score bars on this surface.
    await expect(progress.locator(".progress-bar")).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
    await expectNoConsoleErrors(errors);
  });
});
