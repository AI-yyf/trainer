const { test, expect } = require("playwright/test");
const { SCENARIOS } = require("./trainer-experience-matrix");

const PREVIEW_PATH = "/vscode-preview.html";
const LANGUAGE_LABELS = {
  "zh-CN": "简体中文",
  "en-US": "English",
};
const PROVIDER_ACTION_LABELS = {
  "zh-CN": "\u53e6\u5b58\u4e3a\u8fde\u63a5",
  "en-US": "Save as connection",
};
const VIEW_LABELS = {
  "zh-CN": {
    coach: "\u5bf9\u8bdd",
    plan: "\u8ba1\u5212",
    resources: "\u8d44\u6599",
    training: "\u8bad\u7ec3",
    settings: "\u8bbe\u7f6e",
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
  "fr-FR": {
    coach: "Chat",
    plan: "Plan",
    resources: "Ressources",
    training: "Entra\u00eenement",
    settings: "Param\u00e8tres",
  },
  "de-DE": {
    coach: "Chat",
    plan: "Plan",
    resources: "Materialien",
    training: "Training",
    settings: "Einstellungen",
  },
  "ja-JP": {
    coach: "\u5bfe\u8a71",
    plan: "\u8a08\u753b",
    resources: "\u8cc7\u6599",
    training: "\u8a13\u7df4",
    settings: "\u8a2d\u5b9a",
  },
  "ko-KR": {
    coach: "\ub300\ud654",
    plan: "\uacc4\ud68d",
    resources: "\uc790\ub8cc",
    training: "\ud6c8\ub828",
    settings: "\uc124\uc815",
  },
  "pt-BR": {
    coach: "Chat",
    plan: "Plano",
    resources: "Recursos",
    training: "Treinamento",
    settings: "Configura\u00e7\u00f5es",
  },
};
const PREVIEW_SWITCH_MODEL = "gpt-4.1";
const PREVIEW_DEFAULT_MODEL = "gpt-4.1-mini-compatible";
const TOP_LEVEL_VIEW_TEST_ID = /^trainer-view-nav-(coach|plan|resources|training|settings)$/;
const ACTIVE_TOP_LEVEL_VIEW_SELECTOR = '[data-testid^="trainer-view-nav-"][aria-current="page"]';

async function expectSingleVisible(locator) {
  await expect(locator).toHaveCount(1);
  await expect(locator).toBeVisible();
  return locator;
}

function scenarioUrl(scenario) {
  const query = new URLSearchParams({
    view: scenario.view,
    lang: scenario.language,
    scenario: scenario.state,
    theme: scenario.theme,
    connection: "connected",
    run: `experience-${scenario.id}`,
  });
  if (scenario.workspaceAdmission) {
    query.set("workspaceAdmission", scenario.workspaceAdmission);
  }
  return `${PREVIEW_PATH}?${query.toString()}`;
}

function collectConsoleErrors(page) {
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  return errors;
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

async function openScenario(page, scenario) {
  await page.setViewportSize(scenario.viewport);
  await page.goto(scenarioUrl(scenario));
  await expect(page.locator("body")).toBeVisible();
  await expect(page.getByTestId(TOP_LEVEL_VIEW_TEST_ID)).toHaveCount(5);
  await expect(page.locator(ACTIVE_TOP_LEVEL_VIEW_SELECTOR)).toHaveCount(1);
}

async function assertVisibleContract(page, scenario, contract) {
  switch (contract.id) {
    case "five_top_level_views":
      await expect(page.getByTestId(TOP_LEVEL_VIEW_TEST_ID)).toHaveCount(5);
      return;
    case "one_active_view":
      await expect(page.locator(ACTIVE_TOP_LEVEL_VIEW_SELECTOR)).toHaveCount(1);
      return;
    case "coach_composer":
      await expect(page.locator(".composer-shell")).toBeVisible();
      return;
    case "coach_recovery_surface":
      await expectSingleVisible(page.locator(".composer-shell"));
      return;
    case "workspace_admission":
      await expect(page.locator(".workspace-admission")).toBeVisible();
      return;
    case "plan_surface":
      await expectSingleVisible(page.locator(".plan-view"));
      return;
    case "resources_surface":
      await expectSingleVisible(page.locator(".resources-knowledge"));
      return;
    case "training_card":
      await expect(page.locator(".training-pane--card-only")).toBeVisible();
      return;
    case "settings_surface":
      await expect(page.locator(".coach-settings-view")).toBeVisible();
      return;
    case "provider_profiles":
      await expect.poll(() => page.locator(".settings-provider-profile").count()).toBeGreaterThanOrEqual(2);
      return;
    default:
      throw new Error(`${scenario.id} has an unknown visible contract: ${contract.id}`);
  }
}

async function assertVisibleContracts(page, scenario) {
  for (const contract of scenario.expected.visible) {
    await assertVisibleContract(page, scenario, contract);
  }
}

async function exerciseCoach(page, scenario) {
  const composer = page.locator(".composer-shell textarea");
  await expectSingleVisible(page.locator(".composer-shell"));
  await expectSingleVisible(composer);

  if (scenario.userAction.kind !== "send_coach_message") {
    return { kind: scenario.userAction.kind };
  }

  const draft = scenario.userAction.input;
  const send = page.locator(".composer__send");
  if (!(await composer.isEditable())) {
    await expect(composer).toBeDisabled();
    await expect(send).toHaveAttribute("aria-label", /发送消息|Send message|取消回复|Cancel reply/);
    return { kind: "send_coach_message", blocked: true };
  }

  await composer.fill(draft);
  await expect(composer).toHaveValue(draft);
  await expect(send).toBeEnabled();

  const userMessages = page.locator('[data-role="user"]');
  const userCountBefore = await userMessages.count();
  const composerSurface = page.locator(".composer-shell");
  await send.click();
  await expect.poll(
    async () => {
      if ((await userMessages.count()) > userCountBefore) {
        return true;
      }
      return /\u8fde\u63a5|connection|\u9a8c\u8bc1|verified/i.test(await composerSurface.innerText());
    },
    { timeout: 30_000, intervals: [100, 250, 500, 1_000] },
  ).toBe(true);

  const userMessage = userMessages.nth(userCountBefore);
  if (await userMessage.count()) {
    await expect(userMessage).toContainText(draft);
    await expect(page.locator('[data-role="assistant"]').last()).toContainText(/\S/);
    return { kind: "send_coach_message", draft };
  }

  await expect(page.locator(".composer-shell")).toBeVisible();
  await expect(page.locator(".composer-shell")).toContainText(/连接|connection|验证|verified/i);
  return { kind: "send_coach_message", blocked: true };
}

async function exercisePlan(page, scenario) {
  await expectSingleVisible(page.locator(".plan-view"));
  return { kind: scenario.userAction.kind };
}

async function exerciseResources(page, scenario) {
  await expectSingleVisible(page.locator(".resources-knowledge"));
  const search = page.locator('.resources-knowledge__search input[type="search"]');
  await expectSingleVisible(search);
  const query = scenario.userAction.input;
  await search.fill(query);
  await expect(search).toHaveValue(query);
  return { kind: scenario.userAction.kind, query };
}

async function exerciseTraining(page, scenario) {
  const card = page.locator(".training-pane--card-only");
  await expect(card).toBeVisible();
  await expect(card.locator("[data-training-card-fact]")).toHaveCount(5);
  // The narrow card-only surface answers the five learner questions directly;
  // the full Learn/Try/Verify/Reflect/Return rail belongs to the expanded view.
  await expect(card.locator(".training-loop-step")).toHaveCount(0);
  return { kind: scenario.userAction.kind, card };
}

async function openConnectionDetails(page) {
  const detail = page.locator(".coach-settings-view__provider-detail");
  await expectSingleVisible(detail);
  if (!(await detail.evaluate((element) => element.open))) {
    await detail.locator(":scope > summary").click();
  }
  await expect.poll(() => detail.evaluate((element) => element.open)).toBe(true);
  return detail;
}

async function openProviderConnectionFields(detail) {
  const fields = detail.locator('details.settings-sheet__minor-panel:has(input[type="password"])');
  await expectSingleVisible(fields);
  if (!(await fields.evaluate((element) => element.open))) {
    await fields.locator(":scope > summary").click();
  }
  await expect.poll(() => fields.evaluate((element) => element.open)).toBe(true);
  return fields;
}

async function exerciseSettings(page, scenario) {
  await expect(page.locator(".coach-settings-view")).toBeVisible();
  const detail = await openConnectionDetails(page);

  if (scenario.userAction.kind === "switch_provider_profile") {
    const fields = await openProviderConnectionFields(detail);
    const modelPicker = fields.locator("details.settings-model-picker");
    await expectSingleVisible(modelPicker);
    if (!(await modelPicker.evaluate((element) => element.open))) {
      await modelPicker.locator(":scope > summary").click();
    }
    const model = modelPicker.locator("select");
    await expectSingleVisible(model);
    await expect(model.locator(`option[value="${PREVIEW_SWITCH_MODEL}"]`)).toHaveCount(1);
    await model.selectOption(PREVIEW_SWITCH_MODEL);
    await expect(model).toHaveValue(PREVIEW_SWITCH_MODEL);
    const profiles = page.locator(".settings-sheet__provider-profiles");
    await expectSingleVisible(profiles);
    if (!(await profiles.evaluate((element) => element.open))) {
      await profiles.locator(":scope > summary").click();
    }
    const saveProfile = profiles.getByRole("button", {
      name: PROVIDER_ACTION_LABELS[scenario.language],
    });
    await expect(saveProfile).toHaveCount(1);
    await expect(saveProfile).toBeEnabled();
    await saveProfile.click();
    await expect.poll(() => profiles.locator(".settings-provider-profile").count()).toBeGreaterThan(1);
    const savedModel = profiles.getByText(PREVIEW_SWITCH_MODEL, { exact: true });
    await expect(savedModel).toHaveCount(1);
    const savedProfile = savedModel.locator(
      "xpath=ancestor::button[contains(concat(' ', normalize-space(@class), ' '), ' settings-provider-profile ')]",
    );
    await expectSingleVisible(savedProfile);
    await expect(savedProfile.locator(".settings-provider-profile__model")).toHaveText(PREVIEW_SWITCH_MODEL);
    await expect(savedProfile).toHaveAttribute("aria-pressed", "true");
    const defaultModel = profiles.getByText(PREVIEW_DEFAULT_MODEL, { exact: true });
    await expect(defaultModel).toHaveCount(1);
    const selectedProfile = defaultModel.locator(
      "xpath=ancestor::button[contains(concat(' ', normalize-space(@class), ' '), ' settings-provider-profile ')]",
    );
    await expectSingleVisible(selectedProfile);
    await expect(selectedProfile.locator(".settings-provider-profile__model")).toHaveText(PREVIEW_DEFAULT_MODEL);
    await expect(selectedProfile).toBeEnabled();
    await selectedProfile.click();
    await expect(selectedProfile).toHaveAttribute("aria-pressed", "true");
    return { kind: "switch_provider_profile", profile: selectedProfile, model: PREVIEW_DEFAULT_MODEL };
  }

  if (scenario.userAction.kind === "switch_language") {
    const targetLanguage = scenario.language === "en-US" ? "zh-CN" : "en-US";
    const defaultsPanel = page.locator(
      `details.settings-sheet__defaults-panel:has(summary[aria-label*="${LANGUAGE_LABELS[scenario.language]}"])`,
    );
    await expectSingleVisible(defaultsPanel);
    if (!(await defaultsPanel.evaluate((element) => element.open))) {
      await defaultsPanel.locator(":scope > summary").click();
    }
    const choice = defaultsPanel.getByRole("button", { name: LANGUAGE_LABELS[targetLanguage], exact: true });
    await expectSingleVisible(choice);
    await choice.click();
    const appliedChoice = page.getByRole("button", { name: LANGUAGE_LABELS[targetLanguage], exact: true });
    await expectSingleVisible(appliedChoice);
    await expect(appliedChoice).toHaveAttribute("aria-pressed", "true");
    return { kind: "switch_language", targetLanguage };
  }

  return { kind: scenario.userAction.kind, detail };
}

async function exerciseCrossView(page, scenario) {
  const targetLabel = VIEW_LABELS[scenario.language][scenario.userAction.targetView];
  const target = page.getByRole("button", { name: targetLabel, exact: true });
  await expect(target).toHaveCount(1);
  await target.click();
  await expect(target).toHaveAttribute("aria-current", "page");
  await expect.poll(() =>
    page.evaluate(() => {
      const key = window.__TRAINER_PREVIEW_STORAGE_KEY__;
      const raw = key ? window.localStorage.getItem(key) : undefined;
      return raw ? JSON.parse(raw).activeView : undefined;
    }),
  ).toBe(scenario.userAction.targetView);
  return { kind: "navigate_to_view", targetView: scenario.userAction.targetView };
}

async function assertRecoveryContract(page, scenario) {
  const recovery = scenario.expected.recovery;
  if (recovery.verification !== "PW") {
    return;
  }
  switch (recovery.kind) {
    case "show_provider_recovery":
      if (scenario.runner === "coach") {
        await expectSingleVisible(page.locator(".composer-shell"));
      } else if (scenario.runner === "resources") {
        await expectSingleVisible(page.locator(".resources-knowledge"));
      } else if (scenario.runner === "plan") {
        await expectSingleVisible(page.locator(".plan-view"));
      } else {
        await expectSingleVisible(page.locator(".coach-settings-view"));
      }
      return;
    case "admit_workspace":
      if (scenario.expected.visible.some((contract) => contract.id === "workspace_admission")) {
        await expect(page.locator(".workspace-admission")).toBeVisible();
      }
      return;
    case "preserve_card":
      if (scenario.runner === "training") {
        await expect(page.locator(".training-pane--card-only")).toBeVisible();
      }
      return;
    case "keep_context":
      await expect(page.locator("main")).toBeVisible();
      return;
    default:
      throw new Error(`${scenario.id} has an unknown recovery contract: ${recovery.kind}`);
  }
}

async function assertPersistenceContract(page, scenario, actionResult) {
  const persistence = scenario.expected.persistence;
  if (persistence.verification !== "PW") {
    return;
  }
  switch (persistence.kind) {
    case "conversation_after_stream":
      if (actionResult.draft) {
        await expect(page.locator('[data-role="user"]').last()).toContainText(actionResult.draft);
        await expect(page.locator('[data-role="assistant"]').last()).toContainText(/\S/);
      } else {
        await expect(page.locator(".composer-shell")).toBeVisible();
      }
      return;
    case "surface_context":
      await expectSingleVisible(page.locator(".plan-view"));
      return;
    case "resource_query":
      await expectSingleVisible(page.locator('.resources-knowledge__search input[type="search"]'));
      await expect(page.locator('.resources-knowledge__search input[type="search"]')).toHaveValue(actionResult.query);
      return;
    case "current_training_card":
      await expect(page.locator(".training-pane--card-only [data-training-card-fact]")).toHaveCount(5);
      return;
    case "settings_detail":
      await expectSingleVisible(page.locator(".coach-settings-view__provider-detail"));
      await expect.poll(() => page.locator(".coach-settings-view__provider-detail").evaluate((element) => element.open)).toBe(true);
      return;
    case "preview_active_view":
      await expect.poll(() =>
        page.evaluate(() => {
          const key = window.__TRAINER_PREVIEW_STORAGE_KEY__;
          const raw = key ? window.localStorage.getItem(key) : undefined;
          return raw ? JSON.parse(raw).activeView : undefined;
        }),
      ).toBe(actionResult.targetView);
      return;
    case "provider_profile":
      await expect(actionResult.profile).toHaveAttribute("aria-pressed", "true");
      return;
    case "locale_session": {
      const expectedLabel = LANGUAGE_LABELS[actionResult.targetLanguage];
      await expect(page.getByRole("button", { name: expectedLabel, exact: true })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      return;
    }
    default:
      throw new Error(`${scenario.id} has an unknown Preview persistence contract: ${persistence.kind}`);
  }
}

async function assertForbiddenContracts(page, scenario, consoleErrors) {
  for (const forbidden of scenario.expected.forbidden) {
    if (forbidden.verification !== "PW") {
      continue;
    }
    switch (forbidden.id) {
      case "no_sixth_top_level_view":
        await expect(page.getByTestId(TOP_LEVEL_VIEW_TEST_ID)).toHaveCount(5);
        break;
      case "no_horizontal_overflow":
        await expectNoHorizontalOverflow(page);
        break;
      case "no_preview_as_real_sidecar":
        expect(scenario.primaryLayer).toBe("PW");
        expect(scenario.evidence.realSidecar).toBe(false);
        break;
      default:
        throw new Error(`${scenario.id} marked ${forbidden.id} as Preview-verifiable without a runner assertion.`);
    }
  }
  expect(consoleErrors, `Console errors for ${scenario.id}:\n${consoleErrors.join("\n")}`).toEqual([]);
}

const runners = {
  coach: exerciseCoach,
  plan: exercisePlan,
  resources: exerciseResources,
  training: exerciseTraining,
  settings: exerciseSettings,
  cross: exerciseCrossView,
};

test.describe.parallel("Trainer 200-scenario user experience matrix (Preview layer)", () => {
  for (const scenario of SCENARIOS) {
    test(`${scenario.id}: ${scenario.title}`, async ({ page }) => {
      const consoleErrors = collectConsoleErrors(page);
      await openScenario(page, scenario);
      const actionResult = await runners[scenario.runner](page, scenario);
      await assertVisibleContracts(page, scenario);
      await assertRecoveryContract(page, scenario);
      await assertPersistenceContract(page, scenario, actionResult);
      await assertForbiddenContracts(page, scenario, consoleErrors);
    });
  }
});
