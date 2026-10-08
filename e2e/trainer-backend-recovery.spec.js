const { openSettingsCategory } = require("./template-navigation");
const { test, expect } = require("playwright/test");

test("Settings recovers an offline backend before provider setup and stops offering restart while starting", async ({ page }) => {
  await page.goto("/vscode-preview.html?view=settings&lang=zh-CN&connection=connected&run=backend-recovery");
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
  const bootstrap = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__);
  bootstrap.plan = { id: "plan-pending", title: "计划尚未开始", summary: "等待连接", stages: [], frozen: false, cadence: "" };
  bootstrap.hasFormalPlan = false;
  bootstrap.coachingState = { ...bootstrap.coachingState, nextStep: "错误提示：重新填写 API key" };
  await page.addInitScript(() => {
    window.__TRAINER_E2E_HOST_ACTIONS__ = [];
    window.acquireVsCodeApi = () => ({
      getState: () => ({ activeView: "settings", composerLanguage: "zh-CN", themePreference: "dark" }),
      setState: () => undefined,
      postMessage: (message) => window.__TRAINER_E2E_HOST_ACTIONS__.push(message),
    });
  });
  await page.goto("/");
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .some(action => action.type === "request/bootstrap"))).toBe(true);
  const providerConfig = { ...bootstrap.providerConfig, configured: false, apiKeyConfigured: false, profiles: [], lastTestResult: undefined };
  async function update(state, provider = providerConfig) {
    await page.evaluate(payload => window.postMessage({ type: "bootstrap", payload }, window.location.origin), {
      ...bootstrap, providerConfig: provider, connection: { ...bootstrap.connection, state },
    });
  }
  await update("offline");
  const strip = page.locator('[data-settings-availability=true]:visible');
  await expect(strip).toContainText("Trainer 暂时还不能继续");
  await expect(strip).toContainText("重新启动本地后端");
  await strip.getByRole('button', { name: "重新启动 Trainer", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__
    .filter(action => action.type === "command/execute" && action.payload.commandId === "trainer.sidecar.restart").length)).toBe(1);
  await page.getByRole('button', { name: "学习", exact: true }).click();
  // Learning owns one canonical NextAction for recovery.
  const planRecovery = page.locator('[data-plan-primary="true"] [data-template="NextAction"]');
  await expect(planRecovery).toHaveCount(1);
  await expect(planRecovery).toContainText("Trainer 暂时还不能继续");
  await expect(planRecovery).toContainText("检查连接");
  await expect(planRecovery).not.toContainText("重新填写 API key");
  await planRecovery.getByRole('button', { name: "打开设置", exact: true }).click();
  await expect(strip.getByRole('button', { name: "重新启动 Trainer", exact: true })).toBeVisible();
  await update("starting");
  await expect(strip).toContainText("Trainer 正在准备中");
  await expect(strip.getByRole('button')).toHaveCount(0);
  await expect(strip.getByRole('button', { name: "重新启动 Trainer", exact: true })).toHaveCount(0);
  await update("connected", { ...bootstrap.providerConfig, lastTestResult: undefined });
  await expect(page.getByRole('button', { name: "重新启动 Trainer", exact: true })).toHaveCount(0);
  await expect(page.locator('[data-settings-availability=true]:visible')).not.toContainText("Trainer 暂时还不能继续");
});
