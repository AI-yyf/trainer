#!/usr/bin/env node
/**
 * Local action latency gate: every check/restore/navigation action in the
 * workbench must settle within 1 second on the local preview.
 *
 * Network-bound provider tests are excluded by design: their dispatch is
 * immediate, the result is streamed, and remote latency is not a local budget.
 *
 * Usage:
 *   npm run verify:local-latency
 * Exit 1 when any measured action exceeds 1000 ms.
 */
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import path from "node:path";
import fs from "node:fs";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const BUDGET_MS = 1000;
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const webviewRoot = path.join(repoRoot, "extension", "webview");
const HOST = "127.0.0.1";

function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, HOST, () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}
async function waitForServer(url, timeoutMs = 30_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // not ready yet
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`preview server did not start at ${url}`);
}

const port = await freePort();
const preview = spawn(
  path.join(webviewRoot, "node_modules", ".bin", "vite"),
  ["preview", "--port", String(port), "--host", HOST, "--strictPort"],
  { cwd: webviewRoot, stdio: "ignore", detached: true },
);
const stopPreview = () => {
  try {
    process.kill(-preview.pid, "SIGTERM");
  } catch {
    // already gone
  }
};
process.on("exit", stopPreview);
process.on("SIGINT", () => {
  stopPreview();
  process.exit(130);
});

let browser;
try {
  await waitForServer(`http://${HOST}:${port}/vscode-preview.html`);
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 460, height: 900 } });
  await page.goto(
    `http://${HOST}:${port}/vscode-preview.html?scenario=ready&lang=zh-CN&theme=dark&view=coach&connection=connected`,
  );
  await page.locator('#root[data-trainer-app-ready="true"]').waitFor({ timeout: 20_000 });
  await page.waitForTimeout(1000);

  const results = [];
  async function timed(name, action, check) {
    const started = performance.now();
    await action();
    await check();
    results.push({ name, ms: Math.round(performance.now() - started) });
  }

  await timed(
    "coach->learning-drawer",
    () => page.getByTestId("trainer-learning-toggle").first().click(),
    () => page.locator('[data-template="LearningDrawer"]').first().waitFor({ timeout: 5000 }),
  );
  await timed(
    "learning-drawer->resources",
    () => page.getByTestId("trainer-view-nav-resources").first().click(),
    () => page.getByText("资料库", { exact: true }).first().waitFor({ timeout: 5000 }),
  );
  await timed(
    "resources->settings",
    () => page.getByTestId("trainer-view-nav-settings").first().click(),
    () =>
      page
        .locator('[data-template="SettingsDetail"], [data-template="SettingsIndex"]')
        .first()
        .waitFor({ timeout: 5000 }),
  );
  await timed(
    "settings->teaching",
    async () => {
      const categoryRow = page.locator('[data-settings-category="teaching"]');
      if ((await categoryRow.count()) === 0) {
        const backButton = page.locator(
          '[data-template="SettingsDetail"] .template-activity-header > .template-back',
        );
        if ((await backButton.count()) > 0) {
          await backButton.first().click();
        }
      }
      await categoryRow.first().click();
    },
    () => page.locator('[data-settings-detail="teaching"]').first().waitFor({ timeout: 5000 }),
  );
  await timed(
    "settings->coach",
    () => page.getByTestId("trainer-view-nav-coach").first().click(),
    () => page.locator("#coach-composer, .composer-shell textarea").first().waitFor({ timeout: 5000 }),
  );

  const overBudget = results.filter((result) => result.ms > BUDGET_MS);
  fs.mkdirSync(path.join(repoRoot, "output"), { recursive: true });
  fs.writeFileSync(
    path.join(repoRoot, "output", "local-action-latency.json"),
    `${JSON.stringify({ budgetMs: BUDGET_MS, results }, null, 2)}\n`,
  );
  for (const result of results) {
    console.log(`${result.ms <= BUDGET_MS ? "PASS" : "FAIL"}  ${result.name}: ${result.ms}ms`);
  }
  if (overBudget.length > 0) {
    console.error(`\n[verify-local-latency] ${overBudget.length} action(s) exceeded ${BUDGET_MS}ms`);
    process.exitCode = 1;
  } else {
    console.log(`\n[verify-local-latency] OK ${results.length} actions within ${BUDGET_MS}ms`);
  }
} finally {
  await browser?.close().catch(() => {});
  stopPreview();
}
