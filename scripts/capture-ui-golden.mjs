/**
 * Capture localized UI screenshot baselines across all 8 supported Trainer
 * locales (`assets/screenshots/<locale>/*.png`) from the same preview bundle
 * the Playwright e2e suite uses (`vite build --mode preview`), plus the Chrome
 * MV3 Browser Capture popup (`browser-extension/popup/popup.html`).
 *
 * Usage:
 *   node scripts/capture-ui-golden.mjs
 *   node scripts/capture-ui-golden.mjs --locales en-US,zh-CN
 *   TRAINER_CAPTURE_URL=http://127.0.0.1:4175 node scripts/capture-ui-golden.mjs
 */

import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import {
  SUPPORTED_SCREENSHOT_LOCALES,
  browserExtensionTabForLocale,
  buildLocalizedShowcaseBootstrap,
} from "./capture-ui-golden-locales.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const webviewRoot = path.join(repoRoot, "extension", "webview");
const browserExtensionRoot = path.join(repoRoot, "browser-extension");
const outputRootDir = path.join(repoRoot, "assets", "screenshots");

const DEFAULT_PORT = 4175;
const PREVIEW_HOST = "127.0.0.1";
const PREVIEW_PATH = "/vscode-preview.html";
const FIXED_CLOCK_ISO = "2026-11-22T08:00:00.000Z";
const VIEWPORT = { width: 420, height: 900 };
const NARROW_VIEWPORT = { width: 340, height: 900 };
const BROWSER_CAPTURE_VIEWPORT = { width: 312, height: 340 };
const DEVICE_SCALE_FACTOR = 2;
const MIN_PNG_BYTES = 8192;

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".json": "application/json; charset=utf-8",
};

function fail(message) {
  throw new Error(message);
}

function parseSelectedLocales(argv) {
  const index = argv.indexOf("--locales");
  if (index === -1 || !argv[index + 1]) {
    return [...SUPPORTED_SCREENSHOT_LOCALES];
  }
  const requested = argv[index + 1]
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  for (const loc of requested) {
    if (!SUPPORTED_SCREENSHOT_LOCALES.includes(loc)) {
      fail(`Unsupported locale '${loc}'. Expected one of: ${SUPPORTED_SCREENSHOT_LOCALES.join(", ")}`);
    }
  }
  return requested;
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
  const child = spawn(
    process.execPath,
    [viteBin("vite"), "preview", "--host", PREVIEW_HOST, "--port", String(port), "--strictPort"],
    {
      cwd: webviewRoot,
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let output = "";
  child.stdout.on("data", (chunk) => {
    output += chunk;
  });
  child.stderr.on("data", (chunk) => {
    output += chunk;
  });
  child.on("exit", (code) => {
    if (code !== null && code !== 0 && code !== 143) {
      console.error(`[capture-ui-golden] preview server exited early (status ${code}):\n${output}`);
    }
  });
  return child;
}

function startStaticServer(rootDir) {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const reqUrl = new URL(req.url || "/", "http://127.0.0.1");
      const cleanPath = decodeURIComponent(reqUrl.pathname).replace(/^\/+/, "");
      const targetPath = path.resolve(rootDir, cleanPath || "popup/popup.html");
      if (!targetPath.startsWith(path.resolve(rootDir))) {
        res.writeHead(403);
        res.end("Forbidden");
        return;
      }
      if (!fs.existsSync(targetPath) || fs.statSync(targetPath).isDirectory()) {
        res.writeHead(404);
        res.end("Not Found");
        return;
      }
      const ext = path.extname(targetPath).toLowerCase();
      res.writeHead(200, { "Content-Type": MIME_TYPES[ext] || "application/octet-stream" });
      fs.createReadStream(targetPath).pipe(res);
    });
    server.on("error", reject);
    server.listen(0, PREVIEW_HOST, () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("Could not bind static server"));
        return;
      }
      resolve({ server, baseUrl: `http://${PREVIEW_HOST}:${address.port}` });
    });
  });
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

async function applyLocalizedPatch(page, locale, shotName) {
  const base = await page.evaluate(() => window.__TRAINER_BOOTSTRAP__ ?? null);
  if (!base) {
    return;
  }
  const patched = buildLocalizedShowcaseBootstrap(base, locale, { shotName });
  await page.evaluate((payload) => {
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__?.({
      type: "bootstrap",
      payload,
    });
  }, patched);
  await page.waitForTimeout(220);
}

async function collapseInlinePracticeIfOpen(page) {
  const slot = page.locator('[data-inline-practice="true"]');
  if (await slot.count()) {
    const collapsed = await slot.getAttribute("data-inline-practice-collapsed");
    if (collapsed !== "true") {
      const toggle = page.locator('[data-inline-practice-toggle="true"]');
      if (await toggle.count()) {
        await toggle.click();
        await page.waitForTimeout(150);
      }
    }
  }
}

async function ensureInlinePracticeOpen(page) {
  const slot = page.locator('[data-inline-practice="true"]');
  if (await slot.count()) {
    const collapsed = await slot.getAttribute("data-inline-practice-collapsed");
    if (collapsed === "true") {
      const toggle = page.locator('[data-inline-practice-toggle="true"]');
      if (await toggle.count()) {
        await toggle.click();
        await page.waitForTimeout(150);
      }
    }
  }
}

const WEBVIEW_SHOTS = [
  {
    name: "chat-first-run",
    file: "chat-first-run.png",
    title: "Two-destination Coach first-run empty state",
    urlParams: { view: "coach", scenario: "empty" },
  },
  {
    name: "coach-teach",
    file: "coach-teach.png",
    title: "RethinkFun state-flow lecture, saved note & per-message actions",
    urlParams: { view: "coach", scenario: "ready" },
    async interact(page) {
      await collapseInlinePracticeIfOpen(page);
      await page.evaluate(() => {
        const scroller = document.querySelector(".conversation-thread") ?? document.querySelector(".view-content");
        if (scroller) scroller.scrollTop = scroller.scrollHeight;
      });
    },
  },
  {
    name: "plan",
    file: "plan.png",
    title: "Learning Drawer (Goal, Due Practice & Mastery overview)",
    urlParams: { view: "plan", scenario: "ready" },
  },
  {
    name: "resources",
    file: "resources.png",
    title: "Resources library unified under <LibraryRoot>",
    urlParams: { view: "resources", scenario: "resource-preview-loaded" },
    async interact(page) {
      for (let round = 0; round < 6; round++) {
        const collapsed = page.locator('[data-template="Library"] button.collapse-section__header[aria-expanded="false"]');
        const count = await collapsed.count();
        if (count === 0) break;
        await collapsed.first().click();
        await page.waitForTimeout(100);
      }
    },
  },
  {
    name: "training",
    file: "training.png",
    title: "Inline FocusedPractice card inside Chat + Single Composer",
    urlParams: { view: "coach", scenario: "ready" },
    async interact(page) {
      await ensureInlinePracticeOpen(page);
      await page.evaluate(() => {
        const card = document.querySelector('[data-inline-practice="true"]');
        card?.scrollIntoView({ block: "end", behavior: "instant" });
      });
    },
  },
  {
    name: "settings-connected",
    file: "settings-connected.png",
    title: "Settings Connection summary (connected)",
    urlParams: { view: "settings", scenario: "ready" },
    async interact(page) {
      const indexRow = page.locator('[data-settings-category="connection"]');
      if (await indexRow.count()) await indexRow.click();
    },
  },
  {
    name: "settings-quick-setup",
    file: "settings-quick-setup.png",
    title: "Settings Connection edit form + Proxy direct bypass",
    urlParams: { view: "settings", scenario: "ready" },
    async interact(page) {
      const indexRow = page.locator('[data-settings-category="connection"]');
      if (await indexRow.count()) await indexRow.click();
      const summaryButtons = page.locator(".settings-section--summary .settings-actions--compact button");
      const count = await summaryButtons.count();
      if (count > 0) {
        await summaryButtons.nth(count - 1).click();
      } else {
        await page.locator(".settings-provider-bar__add, .settings-provider-bar__icon-button").first().click();
      }
      await page.locator("form.settings-model-editor").waitFor({ state: "visible" });
      await page.evaluate(() => {
        const scroller = document.querySelector(".view-content");
        if (scroller) scroller.scrollTop = 180;
      });
    },
  },
  {
    name: "settings-workspace",
    file: "settings-workspace.png",
    title: "Settings Workspace & unified <LibraryRoot>",
    urlParams: { view: "settings", scenario: "ready" },
    async interact(page) {
      const wsRow = page.locator('[data-settings-category="workspace"]');
      if (await wsRow.count()) await wsRow.click();
      await page.locator('[data-settings-section="workspace"]').waitFor({ state: "visible" });
    },
  },
  {
    name: "skill-deck",
    file: "skill-deck.png",
    title: "$ skill palette in Coach composer",
    urlParams: { view: "coach", scenario: "ready" },
    async interact(page) {
      await collapseInlinePracticeIfOpen(page);
      await page.locator("#coach-composer").fill("$");
      await page.locator(".template-command-palette").waitFor({ state: "visible" });
    },
  },
  {
    name: "skill-manager",
    file: "skill-manager.png",
    title: "Settings Coach custom skill manager",
    urlParams: { view: "coach", scenario: "ready" },
    async interact(page) {
      await page.locator("#coach-composer").fill("$");
      await page.locator(".template-command-palette").waitFor({ state: "visible" });
      await page.locator(".template-command-palette__footer button").click();
      await page.locator('[data-settings-detail="teaching"]').waitFor({ state: "visible" });
    },
  },
  {
    name: "coach-narrow",
    file: "coach-narrow.png",
    title: "Narrow 340px sidebar layout",
    urlParams: { view: "coach", scenario: "ready" },
    viewport: NARROW_VIEWPORT,
    async interact(page) {
      await collapseInlinePracticeIfOpen(page);
    },
  },
];

function pngSize(filePath) {
  const buffer = fs.readFileSync(filePath);
  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20),
    bytes: buffer.length,
  };
}

function previewUrl({ scenario, view }, lang) {
  const query = new URLSearchParams({
    view,
    lang,
    scenario,
    connection: "connected",
    theme: "dark",
  });
  return `${PREVIEW_PATH}?${query.toString()}`;
}

async function openShot(page, baseUrl, shot, lang) {
  const expectedViewport = shot.viewport ?? VIEWPORT;
  if (
    page.viewportSize()?.width !== expectedViewport.width ||
    page.viewportSize()?.height !== expectedViewport.height
  ) {
    await page.setViewportSize(expectedViewport);
  }
  await page.goto(`${baseUrl}${previewUrl(shot.urlParams, lang)}`, { waitUntil: "networkidle" });
  await page.locator('#root[data-trainer-app-ready="true"]').waitFor({ state: "attached" });
  await page.evaluate(() => document.fonts.ready);
  await applyLocalizedPatch(page, lang, shot.name);
  if (shot.interact) {
    await shot.interact(page);
  }
  await page.waitForTimeout(250);
}

async function captureBrowserCapturePopup(browser, staticBaseUrl, locale, outFile) {
  const tab = browserExtensionTabForLocale(locale);
  const context = await browser.newContext({
    viewport: BROWSER_CAPTURE_VIEWPORT,
    deviceScaleFactor: DEVICE_SCALE_FACTOR,
    reducedMotion: "reduce",
    colorScheme: "dark",
    locale,
  });
  try {
    await context.addInitScript(
      ({ loc, tabInfo }) => {
        window.chrome = {
          i18n: {
            getUILanguage: () => loc,
          },
          tabs: {
            query: async () => [{ id: 1, url: tabInfo.url, title: tabInfo.title }],
          },
          runtime: {
            lastError: null,
            sendMessage: (msg, cb) => {
              if (msg?.type === "trainer:state" || msg?.type === "trainer:refresh") {
                cb({ paired: true, downloadTarget: "Trainer Library/" });
                return;
              }
              cb({ ok: true });
            },
          },
        };
      },
      { loc: locale, tabInfo: tab },
    );
    const page = await context.newPage();
    await page.goto(`${staticBaseUrl}/popup/popup.html`, { waitUntil: "networkidle" });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(200);
    await page.locator("#capture-panel").waitFor({ state: "visible" });
    const box = await page.locator("main.card").boundingBox();
    if (box) {
      await page.setViewportSize({
        width: Math.max(280, Math.ceil(box.width)),
        height: Math.max(180, Math.ceil(box.height)),
      });
      await page.waitForTimeout(80);
    }
    await page.screenshot({ path: outFile, animations: "disabled" });
  } finally {
    await context.close();
  }
}

async function main() {
  const selectedLocales = parseSelectedLocales(process.argv.slice(2));
  const fullRun = selectedLocales.length === SUPPORTED_SCREENSHOT_LOCALES.length;
  fs.mkdirSync(outputRootDir, { recursive: true });

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

  const staticExt = await startStaticServer(browserExtensionRoot);
  const consoleErrors = [];
  const failures = [];
  const captured = [];

  const channel = String(process.env.TRAINER_E2E_CHANNEL ?? "").trim() || undefined;
  const browser = await chromium.launch({ channel });
  try {
    for (const locale of selectedLocales) {
      const localeDir = path.join(outputRootDir, locale);
      fs.mkdirSync(localeDir, { recursive: true });
      const context = await browser.newContext({
        viewport: VIEWPORT,
        deviceScaleFactor: DEVICE_SCALE_FACTOR,
        reducedMotion: "reduce",
        locale,
        timezoneId: "Asia/Shanghai",
      });
      const page = await context.newPage();
      page.on("console", (message) => {
        if (message.type() === "error") {
          consoleErrors.push(`[${locale}] ${message.text()}`);
        }
      });
      await page.clock.setFixedTime(new Date(FIXED_CLOCK_ISO));

      for (const shot of WEBVIEW_SHOTS) {
        const target = path.join(localeDir, shot.file);
        try {
          await openShot(page, baseUrl, shot, locale);
          await page.screenshot({ path: target, animations: "disabled" });
          const { width, height, bytes } = pngSize(target);
          if (bytes < MIN_PNG_BYTES) {
            fail(`${locale}/${shot.file} looks blank (${bytes} bytes).`);
          }
          captured.push({ locale, file: shot.file, width, height, bytes });
          console.log(`[capture-ui-golden] ${locale}/${shot.file} <- ${shot.title} (${width}x${height}, ${bytes} bytes)`);
        } catch (error) {
          failures.push(`${locale}/${shot.name}: ${error instanceof Error ? error.message : String(error)}`);
        }
      }
      await context.close();

      // Browser Capture Extension popup screenshot in this locale
      const popupOut = path.join(localeDir, "browser-capture.png");
      try {
        await captureBrowserCapturePopup(browser, staticExt.baseUrl, locale, popupOut);
        const { width, height, bytes } = pngSize(popupOut);
        captured.push({ locale, file: "browser-capture.png", width, height, bytes });
        console.log(`[capture-ui-golden] ${locale}/browser-capture.png <- Browser Capture popup (${width}x${height}, ${bytes} bytes)`);
      } catch (error) {
        failures.push(`${locale}/browser-capture: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
  } finally {
    await browser.close();
    staticExt.server.close();
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

  if (fullRun) {
    for (const entry of fs.readdirSync(outputRootDir)) {
      if (entry.endsWith(".png")) {
        fs.unlinkSync(path.join(outputRootDir, entry));
      }
    }
  }

  console.log(
    `[capture-ui-golden] done — ${captured.length} screenshots across ${selectedLocales.length} locale(s) refreshed in ${path.relative(repoRoot, outputRootDir)}${path.sep}`,
  );
}

main().catch((error) => {
  console.error(`[capture-ui-golden] ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
