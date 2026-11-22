const { test, expect } = require("playwright/test");

async function loadMockHostBootstrap(page, lang = "zh-CN") {
  await page.goto(`/vscode-preview.html?view=coach&lang=${lang}&connection=connected&run=admission-e2e`);
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const bootstrap = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  await page.addInitScript((initialLang) => {
    window.__TRAINER_E2E_HOST_ACTIONS__ = [];
    window.acquireVsCodeApi = () => ({
      getState: () => ({ activeView: "coach", composerLanguage: initialLang, themePreference: "dark" }),
      setState: () => undefined,
      postMessage: (message) => window.__TRAINER_E2E_HOST_ACTIONS__.push(message),
    });
  }, lang);
  await page.goto("/");
  await expect.poll(() =>
    page.evaluate(() =>
      window.__TRAINER_E2E_HOST_ACTIONS__.some((action) => action.type === "request/bootstrap"),
    ),
  ).toBe(true);
  return bootstrap;
}

function withAdmission(bootstrap, trainerWorkspace) {
  return {
    ...bootstrap,
    connection: { ...bootstrap.connection, state: "connected" },
    memory: {
      ...bootstrap.memory,
      workspace: {
        ...bootstrap.memory.workspace,
        trainerWorkspace,
      },
    },
  };
}

test("empty window or unresolved multi-root shows Choose project folder and auto-sends queued first message once managed", async ({ page }) => {
  const bootstrap = await loadMockHostBootstrap(page, "zh-CN");
  await page.evaluate(
    (payload) => window.postMessage({ type: "bootstrap", payload }, window.location.origin),
    withAdmission(bootstrap, {
      status: "project-found",
      rootPath: "/Users/test/TrainerLibrary",
      projectPath: undefined,
      projectName: undefined,
    }),
  );

  // Primary CTA must be "选择项目文件夹" (not broken "加入 Trainer").
  const admission = page.locator(".workspace-admission");
  await expect(admission).toBeVisible();
  await expect(admission.locator(".workspace-admission__primary-action")).toHaveText("选择项目文件夹");
  await expect(admission.getByRole("button", { name: "加入 Trainer", exact: true })).toHaveCount(0);

  // Typing and submitting in composer dispatches chooseWorkspaceProject (never adoptWorkspaceProject).
  const composer = page.locator("#coach-composer");
  await composer.fill("帮我讲明白幂等键为什么需要状态流");
  await composer.press("Enter");

  await expect.poll(() =>
    page.evaluate(() =>
      window.__TRAINER_E2E_HOST_ACTIONS__.some(
        (action) =>
          action.type === "command/execute" &&
          action.payload?.commandId === "trainer.workspace.chooseProject",
      ),
    ),
  ).toBe(true);
  const adoptedDirectly = await page.evaluate(() =>
    window.__TRAINER_E2E_HOST_ACTIONS__.some(
      (action) =>
        action.type === "command/execute" &&
        action.payload?.commandId === "trainer.workspace.adoptProject",
    ),
  );
  expect(adoptedDirectly).toBe(false);

  // Once host transitions trainerWorkspace to managed, the queued message auto-sends without a second click.
  await page.evaluate(
    (payload) => window.postMessage({ type: "bootstrap", payload }, window.location.origin),
    withAdmission(bootstrap, {
      status: "managed",
      rootPath: "/Users/test/TrainerLibrary",
      projectPath: "/Users/test/projects/payments",
      projectName: "payments",
    }),
  );

  await expect.poll(() =>
    page.evaluate(() =>
      window.__TRAINER_E2E_HOST_ACTIONS__.find(
        (action) => action.type === "session/sendStreamMessage",
      )?.payload?.text,
    ),
  ).toBe("帮我讲明白幂等键为什么需要状态流");
  await expect(composer).toHaveValue("");
});

test("single-folder cold start auto-adopts and auto-sends once managed, or keeps draft if admission errors", async ({ page }) => {
  const bootstrap = await loadMockHostBootstrap(page, "en-US");
  await page.evaluate(
    (payload) => window.postMessage({ type: "bootstrap", payload }, window.location.origin),
    withAdmission(bootstrap, {
      status: "project-found",
      rootPath: "/Users/test/TrainerLibrary",
      projectPath: "/Users/test/projects/payments",
      projectName: "payments",
    }),
  );

  const composer = page.locator("#coach-composer");
  await composer.fill("Explain idempotency keys from first principles");
  await composer.press("Enter");

  await expect.poll(() =>
    page.evaluate(() =>
      window.__TRAINER_E2E_HOST_ACTIONS__.some(
        (action) =>
          action.type === "command/execute" &&
          action.payload?.commandId === "trainer.workspace.adoptProject",
      ),
    ),
  ).toBe(true);

  // Simulate host error: draft must survive and NOT fire on a later unrelated transition.
  await page.evaluate(
    () =>
      window.postMessage(
        {
          type: "operation/status",
          payload: { tone: "error", message: "Folder could not be linked." },
        },
        window.location.origin,
      ),
  );
  await expect(page.locator("[data-system-state=recoverable-error]")).toBeVisible();
  await expect(composer).toHaveValue("Explain idempotency keys from first principles");

  // Retry submit and succeed -> auto-sends immediately once managed.
  await composer.press("Enter");
  await expect.poll(() =>
    page.evaluate(() =>
      window.__TRAINER_E2E_HOST_ACTIONS__.filter(
        (action) =>
          action.type === "command/execute" &&
          action.payload?.commandId === "trainer.workspace.adoptProject",
      ).length,
    ),
  ).toBe(2);
  await page.evaluate(
    (payload) => window.postMessage({ type: "bootstrap", payload }, window.location.origin),
    withAdmission(bootstrap, {
      status: "managed",
      rootPath: "/Users/test/TrainerLibrary",
      projectPath: "/Users/test/projects/payments",
      projectName: "payments",
    }),
  );

  await expect.poll(() =>
    page.evaluate(() =>
      window.__TRAINER_E2E_HOST_ACTIONS__.filter(
        (action) => action.type === "session/sendStreamMessage",
      ).map((action) => action.payload?.text),
    ),
  ).toEqual(["Explain idempotency keys from first principles"]);
});

test("browse and ignored workspaces keep 1-click Add to Trainer directly in Chat", async ({ page }) => {
  const bootstrap = await loadMockHostBootstrap(page, "zh-CN");
  for (const status of ["browse", "ignored"]) {
    await page.evaluate(
      (payload) => window.postMessage({ type: "bootstrap", payload }, window.location.origin),
      withAdmission(bootstrap, {
        status,
        rootPath: "/Users/test/TrainerLibrary",
        projectPath: "/Users/test/projects/payments",
        projectName: "payments",
      }),
    );
    const primary = page.locator(".workspace-admission .workspace-admission__primary-action");
    await expect(primary).toBeVisible();
    await expect(primary).toHaveText("加入 Trainer");
  }
});
