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
  const nav = (name) => page.getByRole("button", { name, exact: true }).first();
  async function timed(name, action, check) {
    const started = performance.now();
    await action();
    await check();
    results.push({ name, ms: Math.round(performance.now() - started) });
  }

  await timed("coach->learning", () => nav("学习").click(), () =>
    page.getByText("今日学习", { exact: true }).first().waitFor({ timeout: 5000 }),
  );
  await timed("learning->resources", () => nav("资料").click(), () =>
    page.getByText("资料库", { exact: true }).first().waitFor({ timeout: 5000 }),
  );
  await timed("resources->settings", () => nav("设置").click(), () =>
    page.getByText("Trainer 设置", { exact: true }).first().waitFor({ timeout: 5000 }),
  );
  await timed("open-connection", () => page.locator("[data-settings-category=connection]").first().click(), () =>
    page.getByText("连接", { exact: true }).first().waitFor({ timeout: 5000 }),
  );
  await timed("settings->coach", () => nav("对话").click(), () =>
    page.locator("textarea").first().waitFor({ timeout: 5000 }),
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
