/**
 * Browser-preview coverage for the plan governance scenarios in the 50-case matrix.
 * Run: npx playwright test e2e/trainer-governance.spec.js
 */

const { test, expect } = require("playwright/test");
const { applyPlanOnlyFixture } = require('./learning-fixtures');

const PREVIEW_PATH = "/vscode-preview.html";

function buildPreviewUrl(view, params = {}) {
  const query = new URLSearchParams({ lang: "en-US", ...params });
  query.set("view", view);
  return `${PREVIEW_PATH}?${query.toString()}`;
}

async function openPreview(page, view, params = {}) {
  await page.goto(buildPreviewUrl(view, params));
  await page.waitForLoadState("networkidle");
  await expect(page.locator("body")).toBeVisible();
  if (view === 'plan' && ['plan-frozen', 'plan-blocked'].includes(params.scenario)) {
    await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
    await applyPlanOnlyFixture(page);
  }
}

function collectPreviewMessages(page) {
  const messages = [];
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
      .then((value) => messages.push(value))
      .catch(() => undefined);
  });
  return messages;
}

async function expectPreviewMessage(messages, predicate) {
  await expect.poll(() => messages.some(predicate)).toBe(true);
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

test.describe("Trainer preview plan governance", () => {
  test("28: first-use empty state keeps the composer honest and ready for context", async ({ page }) => {
    const errors = collectConsoleErrors(page);

    await openPreview(page, "coach", {
      scenario: "empty",
      connection: "connected",
    });

    const composer = page.locator("#coach-composer");
    const sendButton = page.locator(".composer__send");

    // Phase-C product contract (design §16): first use stays honest — no
    // onboarding wizard chrome, no blocked takeover, just a usable composer.
    await expect(page.locator(".onboarding-wizard")).toHaveCount(0);
    await expect(page.locator(".coach-empty-state--blocked")).toHaveCount(0);
    await expect(composer).toBeEditable();
    await expect(sendButton).toBeDisabled();
    await composer.fill("Help me start with a small repository slice.");
    await expect(sendButton).toBeEnabled();
    expect(errors).toEqual([]);
  });

  test("29: no formal plan offers connection recovery without fake plan controls", async ({ page }) => {
    const errors = collectConsoleErrors(page);

    await openPreview(page, "plan", {
      scenario: "provider-failure-empty",
      connection: "connected",
    });

    const plan = page.locator(".plan-view");
    const composer = page.locator("#coach-composer");
    const settingsGear = page.getByTestId("trainer-view-nav-settings");

    // First contact with a failing provider: honest empty state (no durable
    // plan to continue), composer stays usable, and the settings gear is the
    // reachable recovery path. No controls pretend a formal plan exists.
    await expect(plan.getByRole("button", { name: "Freeze plan", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Freeze plan", exact: true })).toHaveCount(0);
    await expect(composer).toHaveCount(0);

    await settingsGear.click();
    await expect(settingsGear).toHaveAttribute("aria-current", "page");
    await expect(settingsGear).toHaveAttribute("aria-label", "Settings");
    expect(errors).toEqual([]);
  });

  test("30: a frozen formal plan exposes only the explicit return-to-live control", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const messages = collectPreviewMessages(page);

    await openPreview(page, "plan", {
      scenario: "plan-frozen",
      connection: "connected",
    });

    const plan = page.locator(".plan-view");
    const next = plan.locator('[data-template=NextAction]');
    await expect(next.locator('h3')).toHaveText('The plan is paused');
    await expect(next).toContainText('Resume the current step without creating a new plan.');

    const liveControl = plan.locator('[data-template=NextAction] > button');
    await expect(liveControl).toHaveText("Resume plan");
    await expect(liveControl).toHaveAttribute('data-action-intent', 'resume_plan');
    await expect(plan.locator('.coach-plan-view__governance')).toHaveCount(0);
    await expect(liveControl).toBeEnabled();
    await expect(page.getByRole("button", { name: "Freeze plan", exact: true })).toHaveCount(0);

    await liveControl.click();
    await expectPreviewMessage(
      messages,
      (message) => message?.type === "plan/freeze" && message?.payload?.frozen === false,
    );
    expect(errors).toEqual([]);
  });

  test("31: a blocked plan keeps its blocker and recovery action without adopting unchecked evidence", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const messages = collectPreviewMessages(page);

    await openPreview(page, "plan", {
      scenario: "plan-blocked",
      connection: "connected",
    });

    const plan = page.locator(".plan-view");
    const next = plan.locator('[data-template=NextAction]');
    await expect(next.locator('h3')).toHaveText('Resolve the current blocker');
    await expect(
      plan
        .locator("[data-template=NextAction]")
        .getByText("The current file verification does not yet support this plan step.", { exact: true }),
    ).toBeVisible();

    const recovery = plan.locator('[data-template=NextAction] > button');
    await expect(recovery).toHaveText('Resolve with coach');
    await expect(recovery).toHaveAttribute('data-action-intent', 'resolve_blocker');
    await expect(recovery).toBeEnabled();
    await recovery.click();
    await expect(page.locator('#coach-composer')).toBeFocused();
    await expect(page.locator('#coach-composer')).not.toHaveValue('');
    await expect(plan.locator('.coach-plan-view__evidence-details, .coach-plan-view__governance')).toHaveCount(0);
    expect(messages.filter(message => message?.type === 'command/execute' &&
      message?.payload?.commandId === 'trainer.evidence.adopt')).toEqual([]);
    expect(errors).toEqual([]);
  });

  test("32: the blocked-plan preview stays localized in zh-CN, en-US, and de-DE", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const cases = [
      {
        language: "zh-CN",
        title: "先解决当前阻塞",
        blocker: "当前文件的验证证据还无法支撑该计划步骤。",
        action: "与教练解决阻塞",
        leak: "The current file verification does not yet support this plan step.",
      },
      {
        language: "en-US",
        title: "Resolve the current blocker",
        blocker: "The current file verification does not yet support this plan step.",
        action: "Resolve with coach",
        leak: "Die Überprüfung der aktuellen Datei unterstützt diesen Planschritt noch nicht.",
      },
      {
        language: "de-DE",
        title: "Aktuelle Blockade lösen",
        blocker: "Die Überprüfung der aktuellen Datei unterstützt diesen Planschritt noch nicht.",
        action: "Mit dem Coach lösen",
        leak: "The current file verification does not yet support this plan step.",
      },
    ];

    for (const testCase of cases) {
      await openPreview(page, "plan", {
        scenario: "plan-blocked",
        connection: "connected",
        lang: testCase.language,
      });

      const plan = page.locator(".plan-view");
      const decisionStrip = plan.locator("[data-template=NextAction]");
      await expect(decisionStrip).toContainText(testCase.title);
      await expect(decisionStrip).toContainText(testCase.blocker);
      await expect(decisionStrip.getByRole('button')).toHaveText(testCase.action);
      await expect(decisionStrip.getByRole('button')).toHaveAttribute('data-action-intent', 'resolve_blocker');
      await expect(decisionStrip).not.toContainText(testCase.leak);
    }
    expect(errors).toEqual([]);
  });
});
