/**
 * Capture the golden UI screenshot baseline served from the same browser-preview
 * bundle the Playwright e2e suite uses (playwright.config.js webServer:
 * `vite build --mode preview` + `vite preview` on http://127.0.0.1:4175).
 *
 * The script re-captures every app-UI PNG under assets/screenshots/ in place
 * (same filenames, so README links keep working) from the current zh-CN dark UI:
 *
 *   chat-first-run.png        Coach view, ready scenario
 *   plan.png                  Plan (学习) view
 *   resources.png             Resources (资料) view with a loaded library
 *   training.png              Training (训练) view with the active card
 *   settings-connected.png    Settings connection summary (connected)
 *   settings-quick-setup.png  Settings connection edit level (quick setup)
 *   message-actions.png       Coach reply with its action overflow opened
 *   message-actions-row.png   Element close-up of the action overflow
 *   skill-deck.png            `$` skill palette open in the composer
 *   skill-manager.png         Settings → Coach custom Skill manager
 *   progress.png              Progress (成长) view
 *   coach-narrow.png          Coach view at the 340px narrow width
 *
 * Usage:
 *   node scripts/capture-ui-golden.mjs
 *   TRAINER_CAPTURE_URL=http://127.0.0.1:4175 node scripts/capture-ui-golden.mjs
 *
 * Environment:
 *   TRAINER_CAPTURE_PORT   port for the managed preview server (default 4175,
 *                          same default port the e2e config uses)
 *   TRAINER_CAPTURE_URL    reuse an already-running preview server instead of
 *                          building + starting one
 *   TRAINER_E2E_CHANNEL    Playwright browser channel (same override as e2e)
 *
 * Determinism: the clock is pinned so scenario timestamps ("checked just now",
 * model-cache freshness) render identically between runs, entrance animations
 * are disabled at screenshot time, and the reduced-motion media preference is
 * set for the whole context. Re-running the script must produce byte-stable
 * PNG sizes (modulo PNG encoder noise).
 *
 * No git operations here — the orchestrator commits the refreshed PNGs.
 */

import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const webviewRoot = path.join(repoRoot, "extension", "webview");
const outputDir = path.join(repoRoot, "assets", "screenshots");

const DEFAULT_PORT = 4175;
const PREVIEW_HOST = "127.0.0.1";
const PREVIEW_PATH = "/vscode-preview.html";
/** Fixed clock: model-cache mock data (fetched 2026-06-21T08:45Z, expires
 * 2026-06-22T08:45Z) stays fresh, and relative labels stop moving. */
const FIXED_CLOCK_ISO = "2026-06-22T08:00:00.000Z";
const VIEWPORT = { width: 420, height: 900 };
const NARROW_VIEWPORT = { width: 340, height: 900 };
const DEVICE_SCALE_FACTOR = 2;
/** A uniform (blank) viewport PNG compresses to a few KB; every real capture
 * carries text, chrome, and cards and lands far above this floor. */
const MIN_PNG_BYTES = 8192;

function fail(message) {
  throw new Error(message);
}

function previewPort() {
  const configuredPort = String(process.env.TRAINER_CAPTURE_PORT ?? "").trim();
  if (!configuredPort) {
    return DEFAULT_PORT;
  }
  const port = Number(configuredPort);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    fail("TRAINER_CAPTURE_PORT must be a valid local TCP port.");
  }
  return port;
}

function viteBin(name) {
  const bin = path.join(webviewRoot, "node_modules", name, "package.json");
  if (!fs.existsSync(bin)) {
    fail(`${name} is missing under extension/webview/node_modules — run npm install first.`);
  }
  return path.join(webviewRoot, "node_modules", name, "bin", name === "vite" ? "vite.js" : "tsc");
}

function buildPreviewBundle() {
  console.log("[capture-ui-golden] building the browser preview bundle…");
  // Same steps as `npm run build:preview` (tsc -b && vite build --mode preview),
  // invoked through node so the child processes stay directly killable.
  for (const [label, args] of [
    ["tsc -b", [viteBin("typescript"), "-b"]],
    ["vite build --mode preview", [viteBin("vite"), "build", "--mode", "preview"]],
  ]) {
    const result = spawnSync(process.execPath, args, {
      cwd: webviewRoot,
      env: process.env,
      stdio: "inherit",
    });
    if (result.error) {
      fail(`${label} could not start: ${result.error.message}`);
    }
    if (result.status !== 0) {
      fail(`${label} exited with status ${result.status}.`);
    }
  }
}

function startPreviewServer(port) {
  const child = spawn(process.execPath, [
    viteBin("vite"),
    "preview",
    "--host",
    PREVIEW_HOST,
    "--port",
    String(port),
    "--strictPort",
  ], {
    cwd: webviewRoot,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  child.stdout.on("data", (chunk) => {
    output += chunk;
  });
  child.stderr.on("data", (chunk) => {
    output += chunk;
  });
  child.on("exit", (code) => {
    // status 143 (SIGTERM) is the script's own teardown at the end of a run.
    if (code !== null && code !== 0 && code !== 143) {
      console.error(`[capture-ui-golden] preview server exited early (status ${code}):\n${output}`);
    }
  });
  return child;
}

async function waitForServer(baseUrl, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "server did not respond";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}${PREVIEW_PATH}`, { method: "GET" });
      if (response.ok) {
        return;
      }
      lastError = `HTTP ${response.status}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  fail(`Preview server at ${baseUrl} never became ready (${lastError}).`);
}

/**
 * Shot list. Every `urlParams` entry runs against the same fixture harness the
 * e2e specs use (`openPreview` in e2e/trainer.spec.js): scenario=ready gives the
 * connected fake workspace/provider/plan/training environment from
 * lib/browserPreviewHarness.ts + lib/mockData.ts.
 */
const SHOTS = [
  {
    name: "chat-first-run",
    file: "chat-first-run.png",
    title: "Coach view (ready)",
    urlParams: { view: "coach", scenario: "ready" },
  },
  {
    name: "plan",
    file: "plan.png",
    title: "Plan view",
    urlParams: { view: "plan", scenario: "ready" },
  },
  {
    name: "resources",
    file: "resources.png",
    title: "Resources view (loaded library)",
    urlParams: { view: "resources", scenario: "resource-preview-loaded" },
  },
  {
    name: "training",
    file: "training.png",
    title: "Training view (active card)",
    urlParams: { view: "training", scenario: "training-debug" },
  },
  {
    name: "settings-connected",
    file: "settings-connected.png",
    title: "Settings connection summary (connected)",
    async interact(page) {
      // r-final: a configured connection skips the index and lands directly on
      // the connection detail (CoachSettingsView settingsIndexOpen gate) — the
      // index row only exists on the cold-start surface (same fallback the
      // geometry gate uses).
      const indexRow = page.locator('[data-settings-category="connection"]');
      if (await indexRow.count()) await indexRow.click();
    },
    urlParams: { view: "settings", scenario: "ready" },
  },
  {
    name: "settings-quick-setup",
    file: "settings-quick-setup.png",
    title: "Settings quick setup (edit level)",
    urlParams: { view: "settings", scenario: "ready" },
    async interact(page) {
      // Connected state shows the compact summary card; the README quick-setup
      // shot is the edit level below it (same entry the settings e2e uses).
      const indexRow = page.locator('[data-settings-category="connection"]');
      if (await indexRow.count()) await indexRow.click();
      await page.getByRole("button", { name: "编辑配置", exact: true }).click();
    },
  },
  {
    // The ready coach seed is one compact reply. r2-g0-4: the overflow is
    // opened so this shot shows the expanded per-message actions instead of
    // duplicating the chat-first-run capture (same urlParams otherwise).
    name: "message-actions",
    file: "message-actions.png",
    title: "Coach reply with per-message actions open (ready)",
    urlParams: { view: "coach", scenario: "ready" },
    async interact(page) { await page.locator(".template-overflow > summary").last().click(); },
  },
  {
    name: "message-actions-row",
    file: "message-actions-row.png",
    title: "Per-message overflow actions",
    async interact(page) { await page.locator(".template-overflow > summary").last().click(); },
    urlParams: { view: "coach", scenario: "ready" },
    elementSelector: ".template-overflow >> nth=-1",
  },
  {
    name: "skill-deck",
    file: "skill-deck.png",
    title: "$ skill palette",
    urlParams: { view: "coach", scenario: "ready" },
    async interact(page) {
      await page.locator("#coach-composer").fill("$");
      await page.locator(".template-command-palette").waitFor({ state: "visible" });
    },
  },
  {
    name: "skill-manager",
    file: "skill-manager.png",
    title: "Settings Coach custom skill management",
    urlParams: { view: "coach", scenario: "ready" },
    async interact(page) {
      await page.locator("#coach-composer").fill("$");
      await page.locator(".template-command-palette").waitFor({ state: "visible" });
      await page.locator(".template-command-palette__footer button").click();
      await page.locator('[data-settings-detail="teaching"]').waitFor({ state: "visible" });
    },
  },
  {
    name: "progress",
    file: "progress.png",
    title: "Progress view (capability states)",
    urlParams: { view: "progress", scenario: "ready" },
  },
  {
    name: "coach-narrow",
    file: "coach-narrow.png",
    title: "Coach view at 340px",
    urlParams: { view: "coach", scenario: "ready" },
    viewport: NARROW_VIEWPORT,
  },
];

function pngSize(filePath) {
  const buffer = fs.readFileSync(filePath);
  // Bytes 16-23 of a PNG hold the IHDR width/height big-endian.
  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20),
    bytes: buffer.length,
  };
}

function previewUrl({ scenario, view }) {
  const query = new URLSearchParams({
    view,
    lang: "zh-CN",
    scenario,
    connection: "connected",
    theme: "dark",
  });
  return `${PREVIEW_PATH}?${query.toString()}`;
}

async function openShot(page, baseUrl, shot) {
  const expectedViewport = shot.viewport ?? VIEWPORT;
  if (
    page.viewportSize()?.width !== expectedViewport.width ||
    page.viewportSize()?.height !== expectedViewport.height
  ) {
    await page.setViewportSize(expectedViewport);
  }
  await page.goto(`${baseUrl}${previewUrl(shot.urlParams)}`, { waitUntil: "networkidle" });
  await page.locator('#root[data-trainer-app-ready="true"]').waitFor({ state: "attached" });
  await page.evaluate(() => document.fonts.ready);
  if (shot.interact) {
    await shot.interact(page);
  }
  await page.waitForTimeout(300);
}

async function captureShot(page, shot) {
  const target = path.join(outputDir, shot.file);
  if (shot.elementSelector) {
    await page.locator(shot.elementSelector).screenshot({ path: target, animations: "disabled" });
  } else {
    await page.screenshot({ path: target, animations: "disabled" });
  }
}

async function main() {
  fs.mkdirSync(outputDir, { recursive: true });

  const port = previewPort();
  const reuseUrl = String(process.env.TRAINER_CAPTURE_URL ?? "").trim();
  const baseUrl = reuseUrl || `http://${PREVIEW_HOST}:${port}`;
  let server = null;

  if (reuseUrl) {
    console.log(`[capture-ui-golden] reusing preview server at ${reuseUrl}`);
    await waitForServer(reuseUrl);
  } else {
    buildPreviewBundle();
    server = startPreviewServer(port);
    await waitForServer(baseUrl);
    console.log(`[capture-ui-golden] preview server ready at ${baseUrl}`);
  }

  const consoleErrors = [];
  const failures = [];
  const captured = [];

  const channel = String(process.env.TRAINER_E2E_CHANNEL ?? "").trim() || undefined;
  const browser = await chromium.launch({ channel });
  try {
    const context = await browser.newContext({
      viewport: VIEWPORT,
      deviceScaleFactor: DEVICE_SCALE_FACTOR,
      reducedMotion: "reduce",
      locale: "zh-CN",
      timezoneId: "Asia/Shanghai",
    });
    const page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error") {
        consoleErrors.push(message.text());
      }
    });
    await page.clock.setFixedTime(new Date(FIXED_CLOCK_ISO));

    for (const shot of SHOTS) {
      try {
        await openShot(page, baseUrl, shot);
        await captureShot(page, shot);
        const { width, height, bytes } = pngSize(path.join(outputDir, shot.file));
        if (bytes < MIN_PNG_BYTES && shot.name !== "message-actions-row") {
          fail(`${shot.file} looks blank (${bytes} bytes).`);
        }
        captured.push({ shot, width, height, bytes });
        console.log(`[capture-ui-golden] ${shot.file} <- ${shot.title} (${width}x${height}, ${bytes} bytes)`);
      } catch (error) {
        failures.push(`${shot.name}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }

    await context.close();
  } finally {
    await browser.close();
    if (server) {
      server.kill("SIGTERM");
    }
  }

  if (consoleErrors.length > 0) {
    failures.push(`Browser console errors:\n${consoleErrors.join("\n")}`);
  }

  if (failures.length > 0) {
    fail(`Capture failed:\n${failures.join("\n")}`);
  }

  console.log(
    `[capture-ui-golden] done — ${captured.length} screenshots refreshed in ${path.relative(repoRoot, outputDir)}${path.sep}`,
  );
}

main().catch((error) => {
  console.error(`[capture-ui-golden] ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
