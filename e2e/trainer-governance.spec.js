/**
 * Browser-preview coverage for the plan governance scenarios in the 50-case matrix.
 * Run: npx playwright test e2e/trainer-governance.spec.js
 */

const { test, expect } = require("playwright/test");

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

    const emptyState = page.locator(".coach-empty-state--welcome");
    const composer = page.locator("#coach-composer");
    const sendButton = page.locator(".composer__send");

    await expect(emptyState.getByRole("heading", { name: "Start with what you want to achieve" })).toBeVisible();
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

    const plan = page.locator(".plan-pane");
    const openSettings = page.getByRole("button", { name: "Open Settings", exact: true });

    await expect(plan.getByText("The formal plan stays honest until a provider is actually usable.", { exact: true })).toBeVisible();
    await expect(openSettings).toBeEnabled();
    await expect(page.getByRole("button", { name: "Generate Plan", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Next task", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Freeze plan", exact: true })).toHaveCount(0);

    await openSettings.click();
    const settingsNavigationItem = page.getByTestId("trainer-view-nav-settings");
    await expect(settingsNavigationItem).toHaveAttribute("aria-current", "page");
    await expect(settingsNavigationItem).toHaveAttribute(
      "aria-label",
      "Settings",
    );
    expect(errors).toEqual([]);
  });

  test("30: a frozen formal plan exposes only the explicit return-to-live control", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const messages = collectPreviewMessages(page);

    await openPreview(page, "plan", {
      scenario: "plan-frozen",
      connection: "connected",
    });

    const plan = page.locator(".plan-pane");
    await expect(plan.locator(".coach-plan-view__decision-strip")).toContainText("Formal plan is frozen");
    await expect(plan.getByText("Next Move", { exact: true })).toBeVisible();

    await plan.getByText("More", { exact: true }).click();
    await expect(plan.locator(".coach-plan-view__governance-item").filter({ hasText: "Formal plan" })).toContainText(
      "Frozen",
    );
    const liveControl = page.getByRole("button", { name: "Live", exact: true });
    await expect(liveControl).toBeEnabled();
    await expect(page.getByRole("button", { name: "Freeze plan", exact: true })).toHaveCount(0);

    await liveControl.click();
    await expectPreviewMessage(
      messages,
      (message) => message?.type === "plan/freeze" && message?.payload?.frozen === false,
    );
    expect(errors).toEqual([]);
  });

  test("31: a blocked plan keeps its blocker and pending evidence actionable", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const messages = collectPreviewMessages(page);

    await openPreview(page, "plan", {
      scenario: "plan-blocked",
      connection: "connected",
    });

    const plan = page.locator(".plan-pane");
    await expect(plan.locator(".coach-plan-view__decision-strip")).toContainText("Plan is blocked");
    await expect(
      plan
        .locator(".coach-plan-view__decision-strip")
        .getByText("The current file verification does not yet support this plan step.", { exact: true }),
    ).toBeVisible();

    await plan.getByText("More", { exact: true }).click();
    const evidenceDetails = plan.locator(".coach-plan-view__evidence-details");
    await expect(evidenceDetails).toBeVisible();
    await evidenceDetails.locator(":scope > summary").click();
    const evidenceSection = evidenceDetails.locator(".coach-plan-view__details-group--evidence");
    await expect(evidenceSection).toBeVisible();
    await expect(evidenceSection.locator(".coach-plan-view__evidence-filter").filter({ hasText: "Pending" })).toContainText(
      "2",
    );
    await expect(evidenceSection.getByText("Current plan thread now points at a single file boundary", { exact: true })).toBeVisible();

    const adopt = evidenceSection.getByRole("button", { name: "Adopt", exact: true }).first();
    await expect(adopt).toBeEnabled();
    await adopt.click();
    await expectPreviewMessage(
      messages,
      (message) =>
        message?.type === "command/execute" &&
        message?.payload?.commandId === "trainer.evidence.adopt" &&
        message?.payload?.payload?.evidenceId === "evidence-plan-1",
    );
    expect(errors).toEqual([]);
  });

  test("32: the blocked-plan preview stays localized in zh-CN, en-US, and de-DE", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const cases = [
      {
        language: "zh-CN",
        title: "计划被卡住了",
        blocker: "当前文件的验证证据还无法支撑该计划步骤。",
        nextStepPrefix: "回到：",
        leak: "The current file verification does not yet support this plan step.",
      },
      {
        language: "en-US",
        title: "Plan is blocked",
        blocker: "The current file verification does not yet support this plan step.",
        nextStepPrefix: "Back to:",
        leak: "Die Überprüfung der aktuellen Datei unterstützt diesen Planschritt noch nicht.",
      },
      {
        language: "de-DE",
        title: "Der Plan ist blockiert",
        blocker: "Die Überprüfung der aktuellen Datei unterstützt diesen Planschritt noch nicht.",
        nextStepPrefix: "Zurück zu:",
        leak: "The current file verification does not yet support this plan step.",
      },
    ];

    for (const testCase of cases) {
      await openPreview(page, "plan", {
        scenario: "plan-blocked",
        connection: "connected",
        lang: testCase.language,
      });

      const plan = page.locator(".plan-pane");
      const decisionStrip = plan.locator(".coach-plan-view__decision-strip");
      await expect(decisionStrip).toContainText(testCase.title);
      await expect(decisionStrip).toContainText(testCase.blocker);
      await expect(decisionStrip).toContainText(testCase.nextStepPrefix);
      await expect(decisionStrip).not.toContainText(testCase.leak);
    }
    expect(errors).toEqual([]);
  });
});
