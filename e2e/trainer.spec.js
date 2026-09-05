/**
 * Trainer E2E acceptance coverage for the shipped five-view sidebar shell.
 * Run: npx playwright test e2e/trainer.spec.js
 */

const { test, expect } = require("playwright/test");

const PREVIEW_PATH = "/vscode-preview.html";

const VIEW_LABELS = {
  "zh-CN": {
    coach: "对话",
    plan: "计划",
    resources: "资料",
    training: "训练",
    settings: "设置",
  },
  "en-US": {
    coach: "Chat",
    plan: "Plan",
    resources: "Resources",
    training: "Training",
    settings: "Settings",
  },
  "es-ES": {
    coach: "Chat",
    plan: "Plan",
    resources: "Recursos",
    training: "Entrenamiento",
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
    indexingLabel: "\u7d22\u5f15\u4e2d",
    noMatchesLabel: "\u6ca1\u6709\u5339\u914d\u7684\u8d44\u6599",
    selectResource: "\u9009\u62e9\u8d44\u6599",
    selectedResourcesLabel: "\u5df2\u9009\u62e9\u8d44\u6599",
    selectAllVisible: "\u5168\u9009\u5f53\u524d\u8d44\u6599",
    clearSelection: "\u6e05\u7a7a\u9009\u62e9",
    deleteUnavailable: "\u6d4f\u89c8\u5668\u9884\u89c8\u4e0d\u4f1a\u66f4\u6539\u771f\u5b9e\u8d44\u6599\u3002\u8bf7\u5728 VS Code \u4fa7\u680f\u4e2d\u64cd\u4f5c\u3002",
    restoreUnavailable: "\u6d4f\u89c8\u5668\u9884\u89c8\u4e0d\u4f1a\u66f4\u6539\u771f\u5b9e\u8d44\u6599\u3002\u8bf7\u5728 VS Code \u4fa7\u680f\u4e2d\u64cd\u4f5c\u3002",
    trash: "\u56de\u6536\u7ad9",
    search: "搜索资料文件夹与文件",
    enableMultiSelect: "开启多选",
    disableMultiSelect: "退出多选",
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
    indexingLabel: "Indexing",
    noMatchesLabel: "No matching resources",
    selectResource: "Select resource",
    selectedResourcesLabel: "Selected resources",
    selectAllVisible: "Select all visible resources",
    clearSelection: "Clear selection",
    deleteUnavailable: "Browser preview cannot change real resources. Use the VS Code sidebar.",
    restoreUnavailable: "Browser preview cannot change real resources. Use the VS Code sidebar.",
    trash: "Trash",
    search: "Search folders and files",
    enableMultiSelect: "Turn on multi-select",
    disableMultiSelect: "Leave multi-select",
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
const TRAINING_CARD_FACTS = ["current", "why-now", "deliverable", "verify", "return"];

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

async function expectActiveView(page, language, view) {
  const navigationItem = page.getByTestId(viewNavigationTestId(view));
  await expect(navigationItem).toHaveAttribute("aria-current", "page");
  await expect(navigationItem).toHaveAttribute(
    "aria-label",
    VIEW_LABELS[language][view],
  );
}

async function expectFiveTopLevelViews(page, language) {
  const views = Object.keys(VIEW_LABELS[language]);
  const tabs = page.getByTestId(/^trainer-view-nav-(coach|plan|resources|training|settings)$/);
  await expect(tabs).toHaveCount(5);
  const testIds = await tabs.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-testid")),
  );
  expect(testIds).toEqual(views.map(viewNavigationTestId));
  const labels = await tabs.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("aria-label")),
  );
  expect(labels).toEqual(Object.values(VIEW_LABELS[language]));
}

async function expectHeaderLabelsVisible(page) {
  const displays = await page
    .locator(".header-switcher__label")
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
  const more = card.locator("details.training-current__more").first();
  if ((await more.count()) === 0) {
    return;
  }
  const isOpen = await more.evaluate((node) => node instanceof HTMLDetailsElement && node.open);
  if (!isOpen) {
    await more.locator(":scope > summary").click();
  }
}

function resourceDetailName(language, title) {
  return `${RESOURCE_COPY[language].resourceDetail}. ${title}`;
}

async function expectTrainingLoop(card, activeStep) {
  await revealTrainingCardDetails(card);
  const steps = card.locator(".training-loop-rail .training-loop-step");
  if ((await steps.count()) === 0) {
    await expect(card.locator("[data-view-object]").first()).toBeVisible();
    return;
  }
  await expect(steps).toHaveCount(TRAINING_LOOP_KEYS.length);

  const states = await steps.evaluateAll((nodes) =>
    nodes.map((node) => ({
      key: node.getAttribute("data-training-loop-step"),
      state: node.getAttribute("data-training-loop-state"),
    })),
  );
  const activeIndex = TRAINING_LOOP_KEYS.indexOf(activeStep);

  expect(states).toEqual(
    TRAINING_LOOP_KEYS.map((key, index) => ({
      key,
      state: index < activeIndex ? "done" : index === activeIndex ? "active" : "upcoming",
    })),
  );
}

async function expectTrainingCardFacts(card) {
  await revealTrainingCardDetails(card);
  const facts = card.locator("[data-training-card-fact]");
  if ((await facts.count()) === 0) {
    await expect(card.locator("[data-view-object]").first()).toBeVisible();
    return;
  }
  await expect(facts).toHaveCount(TRAINING_CARD_FACTS.length);
  for (const fact of TRAINING_CARD_FACTS) {
    await expect(card.locator(`[data-training-card-fact="${fact}"]`)).toBeVisible();
  }
}

async function submitPlanComposerRequest(page, mode, message) {
  const modeLabels = {
    explain: "Explain",
    evidence: "Evidence",
    blocker: "Shrink blocker",
    generate: "Generate",
  };

  await page.locator("#plan-composer-mode").click();
  await page
    .getByRole("menu", { name: "Plan", exact: true })
    .getByRole("menuitemradio", { name: modeLabels[mode] })
    .click();
  await expect(page.locator("#plan-composer-mode")).toHaveAttribute(
    "aria-label",
    `Plan: ${modeLabels[mode]}`,
  );
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
}

test.describe("Trainer Five-View Shell", () => {
  for (const language of ["zh-CN", "en-US"]) {
    test(`exposes the five localized top-level views in ${language}`, async ({ page }) => {
      const errors = attachConsoleErrorCollector(page);

      await openPreview(page, "coach", {
        lang: language,
        scenario: "ready",
        connection: "connected",
      });

      await expectFiveTopLevelViews(page, language);
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
    await expect(page.getByRole("textbox")).toBeEnabled();
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

  test("keeps five clickable views, persists the active view, and omits the Settings composer", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, undefined, {
      lang: "en-US",
      scenario: "ready",
      connection: "connected",
    });

    for (const view of Object.keys(VIEW_LABELS["en-US"])) {
      const tabs = page.getByTestId(/^trainer-view-nav-(coach|plan|resources|training|settings)$/);
      await expectFiveTopLevelViews(page, "en-US");

      await page.getByTestId(viewNavigationTestId(view)).click();
      await expectActiveView(page, "en-US", view);
      await expect(tabs).toHaveCount(5);

      if (view === "settings") {
        await expect(page.locator(".composer-shell")).toHaveCount(0);
      } else {
        await expect(page.locator(".composer-shell")).toBeVisible();
      }
    }

    await page.reload();
    await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
    await expectFiveTopLevelViews(page, "en-US");
    await expectActiveView(page, "en-US", "settings");
    await expect(page.locator(".composer-shell")).toHaveCount(0);
    await expectNoConsoleErrors(errors);
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
    await expectFiveTopLevelViews(page, "en-US");
    await expectActiveView(page, "en-US", "coach");
    await expect(page.locator(".composer-shell")).toBeVisible();
    await expectNoConsoleErrors(errors);
  });

  test("keeps Plan composer intent explicit without mutating the formal plan in the fixture", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const sidecarRequests = [];
    const modes = ["explain", "evidence", "blocker", "generate"];

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

      await expect(page.locator(".coach-plan-view__now-card").first()).toBeVisible();
      await expect(page.locator(".coach-plan-view__compact-primary-action").first()).toBeVisible();
      await expect(page.locator(".coach-plan-view__compact-more")).toHaveCount(0);
      await expect(page.locator("[data-plan-evidence-list]")).toHaveCount(0);
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
      await submitPlanComposerRequest(page, mode, message);
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
      await expect.poll(() =>
        page.evaluate((expectedMessage) =>
          window.__TRAINER_BOOTSTRAP__?.conversation?.some(
            (entry) => entry.role === "user" && entry.body === expectedMessage,
          ) ?? false,
        message),
      ).toBe(true);
      await expect.poll(() =>
        page.evaluate(() =>
          window.__TRAINER_BOOTSTRAP__?.conversation?.some(
            (entry) => entry.role === "assistant" && typeof entry.body === "string" && entry.body.includes("formal plan"),
          ) ?? false,
        ),
      ).toBe(true);
    }

    expect(sidecarRequests).toEqual([]);
    await expectNoConsoleErrors(errors);
  });

  test("keeps missing-key recovery honest in the Coach main line", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "coach", {
      lang: "en-US",
      scenario: "recovery",
      connection: "connected",
    });

    await expectFiveTopLevelViews(page, "en-US");
    await expectActiveView(page, "en-US", "coach");
    await expect(page.locator("main")).toContainText("This saved connection still needs its key, so Trainer cannot continue yet.");
    await expect(page.locator("main")).toContainText("Add the key in Settings, then return to this thread.");
    await expect(page.locator(".composer-shell")).toBeVisible();
    await expectNoConsoleErrors(errors);
  });

  test("keeps a blocked Chinese Coach recovery short and moves to the one next step", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "coach", {
      lang: "zh-CN",
      scenario: "provider-auth-failure-empty",
      connection: "connected",
    });

    const recovery = page.locator(".coach-empty-state--blocked");
    await expect(recovery).toBeVisible();
    await expect(recovery.getByRole("button")).toHaveCount(1);
    await expect(recovery).toContainText("\u68c0\u67e5\u8fde\u63a5");
    await expect(recovery).toContainText("\u8fd9\u7ec4\u8fde\u63a5\u6682\u65f6\u4e0d\u80fd\u7528");
    await expect(recovery).not.toContainText(/gateway|base URL|HTTP|provider/i);
    await expect(page.locator(".composer-presencebar__blocked")).toHaveCount(0);
    const blockedPlaceholder = await page.locator("#coach-composer").getAttribute("placeholder");
    expect(blockedPlaceholder ?? "").not.toMatch(/检查连接|provider/i);

    await recovery.getByRole("button", { name: /\u68c0\u67e5\u8fde\u63a5/ }).click();
    await expectActiveView(page, "zh-CN", "settings");
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
      test(`keeps five visible top-level labels at ${width}px in ${language}`, async ({ page }) => {
        const errors = attachConsoleErrorCollector(page);

        await page.setViewportSize({ width, height: 800 });
        await openPreview(page, "coach", {
          lang: language,
          scenario: "ready",
          connection: "connected",
        });

        await expectFiveTopLevelViews(page, language);
        await expectActiveView(page, language, "coach");
        await expect(page.locator(".header-switcher")).not.toHaveClass(/header-switcher--icons/);
        await expectHeaderLabelsVisible(page);
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
      const search = library.getByRole("searchbox", { name: copy.searchLabel, exact: true });
      const tree = library.getByRole("tree", { name: copy.library, exact: true });
      const toolbarButtons = library.locator(".resources-knowledge__actions").getByRole("button");
      const addResource = library.getByRole("button", {
        name: language === "zh-CN" ? "添加资料" : "Add resource",
        exact: true,
      });
      const refreshResources = library.getByRole("button", { name: language === "zh-CN" ? "刷新索引" : "Refresh index", exact: true });

      await expect(search).toBeVisible();
      await expect(search).toHaveAttribute("placeholder", copy.searchPlaceholder);
      await expect(addResource).toBeVisible();
      await expect(toolbarButtons).toHaveCount(2);
      const resourcesMore = library.locator(".resources-knowledge__toolbar .resources-knowledge__more > summary");
      if ((await resourcesMore.count()) > 0) {
        await resourcesMore.click();
      }
      await expect(refreshResources).toBeVisible();
      await addResource.click();
      const importMenu = page.getByRole("menu", {
        name: language === "zh-CN" ? "添加资料" : "Add resource",
        exact: true,
      });
      await expect(importMenu).toBeVisible();
      await expect(importMenu.getByRole("menuitem")).toHaveCount(3);
      await addResource.click();
      await expect(importMenu).toHaveCount(0);
      await expect(tree).toHaveAttribute("aria-multiselectable", "true");

      const primaryTreeItem = tree.getByRole("treeitem", {
        name: copy.primaryResource,
        exact: true,
      });
      const primaryCheckbox = tree.getByRole("checkbox", {
        name: `${copy.selectResource}: ${copy.primaryResource}`,
        exact: true,
      });
      await expect(primaryTreeItem).toBeVisible();
      await expect(primaryTreeItem.locator("strong")).toHaveText(copy.primaryResource);
      await expect(primaryTreeItem.locator("svg")).toHaveCount(0);
      await expect(primaryCheckbox).toBeVisible();
      const checkboxCountBeforeSelection = await tree.getByRole("checkbox").count();
      expect(checkboxCountBeforeSelection).toBeGreaterThan(1);

      await search.fill(copy.indexingResource);
      const indexingTreeItem = tree.getByRole("treeitem", {
        name: copy.indexingResource,
        exact: true,
      });
      await expect(indexingTreeItem).toBeVisible();
      await expect(indexingTreeItem.locator(".resources-library-tree__status")).toHaveText(
        copy.indexingLabel,
      );

      await search.fill("no-resource-match");
      await expect(tree.getByRole("treeitem")).toHaveCount(0);
      await expect(tree).toContainText(copy.noMatchesLabel);
      await search.fill("");
      await expect(primaryCheckbox).toBeVisible();

      await primaryCheckbox.click();
      await expect(primaryTreeItem).toHaveAttribute("aria-checked", "true");
      const selectionCount = library.locator(".resources-knowledge__selection-count");
      await expect(selectionCount).toHaveAttribute(
        "aria-label",
        `${copy.selectedResourcesLabel}: 1`,
      );
      const batchActions = library.locator(".resources-knowledge__batch-actions");
      await expect(batchActions).not.toHaveAttribute("open", "");
      await batchActions.locator(":scope > summary").click();
      const deleteButton = library.getByRole("button", { name: copy.deleteUnavailable, exact: true });
      await expect(deleteButton).toBeDisabled();
      await expect(deleteButton).toHaveAttribute("title", copy.deleteUnavailable);

      await library.getByRole("button", { name: copy.selectAllVisible, exact: true }).click();
      await expect(selectionCount).toHaveAttribute(
        "aria-label",
        `${copy.selectedResourcesLabel}: 3`,
      );
      await library.getByRole("button", { name: copy.clearSelection, exact: true }).click();
      await expect(selectionCount).toHaveCount(0);
      await expect(tree.getByRole("checkbox")).toHaveCount(checkboxCountBeforeSelection);
      await expect(primaryCheckbox).toBeVisible();

      const trash = library.locator(".resources-knowledge__trash");
      await expect(trash.locator("summary")).toContainText(copy.trash);
      await expect(trash.locator("summary")).toContainText("1");
      await trash.locator("summary").click();
      await expect(trash.getByText("Archived reference notes", { exact: true })).toBeVisible();
      const restoreButton = trash.getByRole("button", { name: copy.restoreUnavailable, exact: true });
      await expect(restoreButton).toBeDisabled();
      await expect(restoreButton).toHaveAttribute("title", copy.restoreUnavailable);

      await expectNoHorizontalOverflow(page);
      await expectNoConsoleErrors(errors);
    });
  }

  test("keeps a selected resource detail after an ordinary view round trip", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const copy = RESOURCE_COPY["zh-CN"];

    await openPreview(page, "resources", {
      lang: "zh-CN",
      scenario: "resource-preview-loaded",
      connection: "connected",
    });

    const library = page.getByRole("region", { name: copy.library, exact: true });
    await library.getByRole("treeitem", { name: copy.primaryResource, exact: true }).click();
    const detail = library.getByRole("region", {
      name: resourceDetailName("zh-CN", copy.primaryResource),
      exact: true,
    });
    await expect(detail).toBeVisible();

    await page.getByRole("button", { name: "对话", exact: true }).click();
    await expectActiveView(page, "zh-CN", "coach");
    await page.getByRole("button", { name: "资料", exact: true }).click();
    await expectActiveView(page, "zh-CN", "resources");
    await expect(detail).toBeVisible();
    await expectNoConsoleErrors(errors);
  });

  test("keeps a selected Chinese resource detail through Training and Settings", async ({ page }) => {
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
    await library.getByRole("treeitem", { name: labels.resource, exact: true }).click();
    const detail = library.getByRole("region", {
      name: resourceDetailName("zh-CN", labels.resource),
      exact: true,
    });
    await expect(detail).toBeVisible();

    for (const view of ["training", "settings", "resources"]) {
      await page.getByRole("button", { name: labels[view], exact: true }).click();
      await expectActiveView(page, "zh-CN", view);
    }

    await expect(detail).toBeVisible();
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
    const returnAction = card.getByRole("button", { name: "Return result to Coach", exact: true });
    await expect(card).toBeVisible();
    await expect(returnAction).toBeVisible();

    await page.getByRole("button", { name: "Chat", exact: true }).click();
    await expectActiveView(page, "en-US", "coach");
    await page.getByRole("button", { name: "Training", exact: true }).click();
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

    await page.getByRole("button", { name: /测试连接|重新测试/ }).first().click();
    await expectActiveView(page, "zh-CN", "settings");
    await expect(page.locator(".notice[role=\"status\"]")).toContainText(
      "连接还没有通过。请检查服务地址、API key 和模型名称，然后再试一次。",
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

      const card = page.getByRole("group", { name: copy.card, exact: true });
      await expect(card).toHaveCount(1);
      await expectTrainingLoop(card, "learn");
      const activeLearnStep = card.locator('[data-training-loop-step="learn"]');
      await expect(activeLearnStep).toHaveAttribute("aria-current", "step");
      await expect(activeLearnStep).toHaveText(copy.activeLearnStep);
      await expectTrainingCardFacts(card);
      await expect(page.locator(".training-card-nav")).toHaveCount(0);
      await expect(card.getByRole("button", { name: copy.startThisStep, exact: true })).toBeVisible();
      await expect(card.getByText(copy.verifyCurrentFile, { exact: true })).toHaveCount(0);
      await expectNoHorizontalOverflow(page);
      await expectNoConsoleErrors(errors);
    });
  }

  for (const language of ["zh-CN", "en-US"]) {
    test(`keeps Training verification visible on the card and in the composer in ${language}`, async ({ page }) => {
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
      await expect(composer).toBeVisible();
      await expect(card.getByRole("button", { name: copy.verifyCurrentFile, exact: true })).toBeVisible();
      await expect(composer.getByRole("button", { name: copy.verifyCurrentFile, exact: true })).toHaveCount(0);
      await expectNoConsoleErrors(errors);
    });
  }

  test("keeps Learn -> Try -> Verify -> Reflect -> Return evidence visible", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const previewCommands = collectPreviewCommands(page);

    await openPreview(page, "training", {
      lang: "en-US",
      scenario: "training-debug",
      connection: "connected",
    });
    let card = page.getByRole("group", { name: "Current training card", exact: true });
    await expectTrainingLoop(card, "try");
    await expectTrainingCardFacts(card);
    await expect(card).toContainText("Build one minimal debug loop");
    await expect(card.locator('[data-training-card-fact="verify"]')).toContainText("Verify");
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
    await expectTrainingCardFacts(card);

    await openPreview(page, "training", {
      lang: "en-US",
      scenario: "training-debug",
      submode: "review",
      connection: "offline",
    });
    card = page.getByRole("group", { name: "Current training card", exact: true });
    await expectTrainingLoop(card, "reflect");
    await expectTrainingCardFacts(card);
    await card.getByRole("button", { name: "Record this step", exact: true }).click();
    const reflection = "The focused check proves the boundary before the result can return.";
    const reflectionInput = page.getByRole("textbox", {
      name: "Record the current training reflection",
      exact: true,
    });
    const emptyReflectButton = page.getByRole("button", {
      name: "Write a training reflection before recording it",
      exact: true,
    });
    await expect(reflectionInput).toBeEditable();
    await expect(emptyReflectButton).toBeDisabled();
    await reflectionInput.fill(reflection);
    const reflectButton = page.getByRole("button", {
      name: "Record training reflection",
      exact: true,
    });
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
    await expect(card.locator('[data-training-card-fact="return"]')).toContainText(
      "Return with the repro step",
    );
    await card.getByRole("button", { name: TRAINING_COPY["en-US"].returnToCoach, exact: true }).click();
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
    await expectActiveView(page, "en-US", "coach");
    await expectNoConsoleErrors(errors);
  });

  test("keeps the next training step lightweight beside the one current card", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await page.setViewportSize({ width: 360, height: 900 });
    await openPreview(page, "training", {
      lang: "zh-CN",
      scenario: "training-remote",
      connection: "connected",
    });

    const training = page.locator(".training-pane--card-only");
    await expect(training.locator("[data-view-object]").first()).toBeVisible();
    await expect(training.locator("[data-training-next-hop=\"true\"]")).toHaveCount(0);
    await expect(training.locator(":scope > .training-carryover-row")).toHaveCount(0);
    await expect(training.locator(":scope > .training-details")).toHaveCount(0);
    await expect(training.locator(".training-current__more")).toHaveCount(0);
    await expect(training.locator(".training-loop-rail")).toHaveCount(0);
    await expect(training.getByText("后续和回看", { exact: true })).toHaveCount(0);
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
      taskEvidence: "Use VS Code function guidance to recover one function's contract",
      returnEvidence: "Return with the function contract",
    },
  ]) {
    test(`renders the ${scenario.id} training scenario with concrete evidence`, async ({ page }) => {
      const errors = attachConsoleErrorCollector(page);

      await openPreview(page, "training", {
        lang: "en-US",
        scenario: scenario.preview,
        connection: "connected",
      });

      const card = page.getByRole("group", { name: "Current training card", exact: true });
      await expect(card.getByRole("heading", { name: scenario.title, exact: true })).toBeVisible();
      await expectTrainingLoop(card, "try");
      await expectTrainingCardFacts(card);
      await expect(card).toContainText(scenario.taskEvidence);
      await expect(card.locator('[data-training-card-fact="verify"]')).toContainText("Verify");
      await expect(card.locator('[data-training-card-fact="return"]')).toContainText(
        scenario.returnEvidence,
      );
      await expect(card.getByRole("button", { name: "Verify current file", exact: true })).toBeVisible();
      await expect(
        page.locator(".composer-shell").getByRole("button", {
          name: "Verify current file",
          exact: true,
        }),
      ).toHaveCount(0);
      await expectNoConsoleErrors(errors);
    });
  }

  test("keeps a selected Spanish training card and composer in Spanish", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "training", {
      lang: "es-ES",
      scenario: "training-remote",
      connection: "connected",
    });

    await expectFiveTopLevelViews(page, "es-ES");
    await expectActiveView(page, "es-ES", "training");
    const card = page.getByRole("group", { name: "Tarjeta de entrenamiento actual", exact: true });
    const composer = page.locator(".composer-shell");
    await expect(card.getByRole("heading", { name: /Práctica: espacio de trabajo remoto de VS Code/ })).toBeVisible();
    await revealTrainingCardDetails(card);
    await expect(card.locator(".training-loop-rail")).toHaveAttribute(
      "aria-label",
      "Ciclo de aprendizaje",
    );
    await expectTrainingCardFacts(card);
    await expect(composer.getByRole("textbox")).toHaveAttribute(
      "placeholder",
      /Primero logra el resultado más pequeño/,
    );
    await expect(
      card.getByRole("button", { name: "Verificar archivo actual", exact: true }),
    ).toBeVisible();
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

  test("sends a staged scratch-paper image through the local preview coach path", async ({ page }) => {
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

    await page.locator(".composer__frame").evaluate((frame) => {
      const image = new File(
        [new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])],
        "scratch-paper.png",
        { type: "image/png" },
      );
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(image);
      for (const type of ["dragenter", "dragover", "drop"]) {
        frame.dispatchEvent(
          new DragEvent(type, {
            bubbles: true,
            cancelable: true,
            dataTransfer,
          }),
        );
      }
    });
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

  test("opens context and resource panels from the coach input shell", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    for (const language of ["zh-CN", "en-US"]) {
      await openPreview(page, "coach", {
        lang: language,
        scenario: "ready",
        connection: "connected",
      });

      const iconButtons = page.locator(".composer__leading-actions .icon-button");
      await expect(iconButtons).toHaveCount(2);

      await iconButtons.nth(0).click();
      await expect(page.locator(".composer-menu-panel .menu-row")).toHaveCount(2);

      await iconButtons.nth(1).click();
      await expect(page.locator(".composer-menu-panel--resources")).toBeVisible();
      await expect(page.locator(".composer-menu-panel--resources .menu-list__item")).toHaveCount(2);
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
    const detailSummary = page
      .locator(".settings-view")
      .locator("summary")
      .filter({ hasText: "Model and test detail" })
      .first();
    await detailSummary.focus();
    await detailSummary.press("Enter");
    await expect(page.locator("main")).toContainText("Protocol");
    await expect(page.locator("main")).toContainText("Diagnostics");
    await expect(page.locator("main")).toContainText("Profiles");
    await expect(page.locator("main")).toContainText("Model ready");
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

  test("plan evidence click reveals pending evidence and matches composer mode", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "plan", {
      lang: "zh-CN",
      scenario: "ready",
      connection: "connected",
    });

    const evidenceButton = page.locator(".coach-plan-view__compact-primary-action button").first();
    await expect(evidenceButton).toBeVisible();
    await evidenceButton.click();
    const evidenceList = page.locator("[data-plan-evidence-list]");
    await expect(evidenceList).toHaveCount(0);
    await expect(page.locator("#plan-composer-mode")).toHaveAttribute("aria-label", /证据|Evidence/);
    const visibleMore = page.locator("main summary").filter({ hasText: /^(更多|More)$/ });
    let visibleMoreCount = 0;
    for (let index = 0; index < await visibleMore.count(); index += 1) {
      if (await visibleMore.nth(index).isVisible()) {
        visibleMoreCount += 1;
      }
    }
    expect(visibleMoreCount).toBeLessThanOrEqual(1);
    await expectNoConsoleErrors(errors);
  });

  test("resources click shows the selected title without English write-authority leftover", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);
    const copy = RESOURCE_COPY["zh-CN"];

    await openPreview(page, "resources", {
      lang: "zh-CN",
      scenario: "resource-preview-loaded",
      connection: "connected",
    });

    await page.getByRole("treeitem", { name: copy.primaryResource, exact: true }).click();
    await expect(page.locator(".resources-knowledge__current-object")).toHaveText(copy.primaryResource);
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

    await page.getByRole("button", { name: "验证当前文件", exact: true }).click();
    await expect(page.locator(".training-current__verify-result")).toContainText(/没有可验证的当前文件|预览不能验|验证未通过/);
    await expect(page.locator("main")).not.toContainText("这一步暂时没完成。再试一次。");
    await page.getByTestId(viewNavigationTestId("settings")).click();
    await expectActiveView(page, "zh-CN", "settings");
    await expect(page.locator(".notice[role=\"status\"]")).toHaveCount(0);
    await expectNoConsoleErrors(errors);
  });

  test("settings first-screen language switch stays on Settings", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "settings", {
      lang: "zh-CN",
      scenario: "ready",
      connection: "connected",
    });

    const languageRow = page.locator("[data-settings-language]");
    await expect(languageRow).toBeVisible();
    await languageRow.getByRole("button", { name: "English", exact: true }).click();
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
    await expect(page.locator(".settings-availability-strip [data-view-object]")).not.toHaveText("模型已就绪");
    await expect(page.locator(".settings-availability-strip [data-view-object]")).toContainText(/工作区|根目录/);
    await expectNoConsoleErrors(errors);
  });

  test("blocked connection keeps one next step without FirstLook percentage", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await openPreview(page, "coach", {
      lang: "zh-CN",
      scenario: "provider-auth-failure-empty",
      connection: "connected",
    });

    const recovery = page.locator(".coach-empty-state--blocked");
    await expect(recovery.getByRole("button")).toHaveCount(1);
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
    await expect(page.locator(".coach-empty-state")).toContainText("先在下面说你现在卡在哪");
    await expect(page.locator("#coach-composer")).toBeVisible();
    await expectNoConsoleErrors(errors);
  });

  test("360px training keeps five nav words and a primary with no overflow", async ({ page }) => {
    const errors = attachConsoleErrorCollector(page);

    await page.setViewportSize({ width: 360, height: 800 });
    await openPreview(page, "training", {
      lang: "zh-CN",
      scenario: "training-debug",
      connection: "connected",
    });

    await expectFiveTopLevelViews(page, "zh-CN");
    await expectHeaderLabelsVisible(page);
    await expect(page.getByRole("button", { name: "验证当前文件", exact: true })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await expectNoConsoleErrors(errors);
  });
});
