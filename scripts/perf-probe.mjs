/**
 * Trainer webview performance probe — honest baseline for long-session
 * interaction latency and streaming render overhead.
 *
 * What it measures (against the same browser-preview bundle the Playwright e2e
 * suite serves, playwright.config.js webServer on http://127.0.0.1:4175):
 *   1. Long-session navigation latency — bootstrap 300 conversation messages,
 *      then click through the primary destinations and time click → target
 *      surface unhides (`data-surface` losing `hidden`). Cold = first visit of
 *      each surface (lazy chunk load included); warm = surfaces already kept
 *      alive by WorkbenchSurfaces.
 *   2. Streaming overhead — inject `stream/start` + 300 chunks × 100 chars at
 *      ~4ms cadence through window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__
 *      (exposed at extension/webview/src/lib/vscode.ts, e2e precedent
 *      e2e/trainer-template-navigation.spec.js:42), and count main-thread
 *      long tasks (>50ms) during the burst, in two configurations:
 *      coach-only visited vs all five surfaces kept alive.
 *   3. Nav latency while a stream is running (in-page rAF measurement).
 *
 * Budgets (regression red lines, evaluated into `budgets`):
 *   - streaming burst produces zero longtask(>50ms) entries
 *   - warm navigation p90 < 100ms
 * Default is report-only (exit 0); pass --strict to exit 1 on budget misses.
 *
 * Honest limitations (read before comparing numbers):
 *   - Headless Chromium, one machine, one sample per run — treat differences
 *     below ~20% as noise; this is evidence of "no jank at this scale", NOT
 *     proof that the architecture is free.
 *   - Chunks are synthetic store injections, not a live provider stream; the
 *     rendering path is real (bubble visibly streams, verified by e2e-style
 *     DOM checks) but token cadence differs from a real model.
 *   - PerformanceObserver longtask has a 50ms floor; per-chunk costs below it
 *     are invisible here.
 *
 * Usage:
 *   node scripts/perf-probe.mjs                     # manages its own server
 *   TRAINER_PERF_URL=http://127.0.0.1:4175 node scripts/perf-probe.mjs
 *   node scripts/perf-probe.mjs --out /tmp/perf-baseline.json --strict
 *
 * Environment:
 *   TRAINER_PERF_PORT   port for the managed preview server (default 4179,
 *                       deliberately NOT the e2e port 4175)
 *   TRAINER_PERF_URL    reuse an already-running preview server
 *   TRAINER_E2E_CHANNEL Playwright browser channel (same override as e2e)
 *
 * No git operations here — the orchestrator decides whether this joins the
 * regular suite and commits baselines.
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

const DEFAULT_PORT = 4179;
const PREVIEW_HOST = "127.0.0.1";
const PREVIEW_PATH = "/vscode-preview.html";

const CONVERSATION_SIZE = 300;
const STREAM_CHUNKS = 300;
const STREAM_CHUNK_CHARS = 100;
const STREAM_CHUNK_GAP_MS = 4;
const NAV_SAMPLE_ROUNDS = 3;

const BUDGETS = {
  streamingLongTasks: 0,
  warmNavP90Ms: 100,
};

const strictMode = process.argv.includes("--strict");
const outArgIndex = process.argv.indexOf("--out");
const outPath = outArgIndex > -1 ? process.argv[outArgIndex + 1] : undefined;

function fail(message) {
  throw new Error(message);
}

function previewPort() {
  const configuredPort = String(process.env.TRAINER_PERF_PORT ?? "").trim();
  if (!configuredPort) {
    return DEFAULT_PORT;
  }
  const port = Number(configuredPort);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    fail("TRAINER_PERF_PORT must be a valid local TCP port.");
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

function startPreviewServer(port) {
  // Serves the existing gitignored dist bundle; building is the e2e suite's
  // job (playwright.config.js webServer), not the probe's.
  if (!fs.existsSync(path.join(webviewRoot, "dist", "index.html"))) {
    fail("extension/webview/dist is missing — build the preview bundle first (e2e webServer or `npm run build:preview` in extension/webview).");
  }
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
    if (code !== null && code !== 0 && code !== 143) {
      console.error(`[perf-probe] preview server exited early (status ${code}):\n${output}`);
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
      lastError = `status ${response.status}`;
    } catch (error) {
      lastError = error.message;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  fail(`preview server not reachable at ${baseUrl}: ${lastError}`);
}

function buildConversation(size) {
  const messages = [];
  for (let i = 0; i < size; i++) {
    const user = i % 2 === 0;
    messages.push({
      id: `perf-probe-m${i}`,
      role: user ? "user" : "assistant",
      author: user ? "你" : "教练",
      body: user
        ? `第${i}问：请解释 React 里 memo 和 useMemo 的区别，以及什么时候该用哪个？顺便谈谈 key 的作用。`
        : `第${i}答：memo 缓存组件渲染结果，useMemo 缓存计算值。当父组件频繁重渲染而子组件 props 稳定时用 memo；昂贵计算依赖变化不频繁时用 useMemo。key 帮助 React 识别列表项身份，避免错误复用。The quick brown fox jumps over the lazy dog.`,
      timestamp: new Date(Date.now() - (size - i) * 60_000).toISOString(),
    });
  }
  return messages;
}

async function openProbePage(browser, baseUrl) {
  const page = await browser.newPage();
  await page.goto(
    `${baseUrl}${PREVIEW_PATH}?view=coach&scenario=ready&connection=connected&lang=zh-CN`,
  );
  await page.waitForSelector('#root[data-trainer-app-ready="true"]', { timeout: 20_000 });
  // Long session: replace the fixture conversation with a 300-message history
  // through the same host-message channel the webview already trusts.
  await page.evaluate((conversation) => {
    const current = window.__TRAINER_BOOTSTRAP__;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
      type: "bootstrap",
      payload: { ...current, conversation },
    });
  }, buildConversation(CONVERSATION_SIZE));
  await page.waitForTimeout(300);
  return page;
}

const NAV_SELECTORS = {
  coach: '[data-testid="trainer-view-nav-coach"]',
  plan: '[data-testid="trainer-view-nav-plan"]',
  resources: '[data-testid="trainer-view-nav-resources"]',
  settings: '[data-testid="trainer-view-nav-settings"]',
};

async function navLatency(page, target) {
  const started = Date.now();
  await page.click(NAV_SELECTORS[target]);
  await page.waitForFunction(
    (view) => {
      const surface = document.querySelector(`div[data-surface="${view}"]`);
      return Boolean(surface) && !surface.hidden;
    },
    target,
    { timeout: 10_000 },
  );
  return Date.now() - started;
}

// Training/progress have no primary-nav button (three-destination IA); visit
// them the way the product does from Learning, via host view restore.
async function visitViaHost(page, view) {
  const started = Date.now();
  await page.evaluate((target) => {
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({
      type: "ui/restoreView",
      payload: { activeView: target },
    });
  }, view);
  await page.waitForFunction(
    (target) => {
      const surface = document.querySelector(`div[data-surface="${target}"]`);
      return Boolean(surface) && !surface.hidden;
    },
    view,
    { timeout: 10_000 },
  );
  return Date.now() - started;
}

async function runStreamBurst(page, { navDuringStreamAt }) {
  return page.evaluate(async ({ chunks, chunkChars, gapMs, navAt }) => {
    const apply = (message) => window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__(message);
    const messageId = `perf-probe-stream-${Date.now()}`;
    const chunkText =
      "流式渲染开销探针：这一段文本会逐块追加到当前回复气泡里，用于测量每个 chunk 触发的重渲染成本与输入延迟。Lorem ipsum dolor sit amet. ";
    const text = chunkText.repeat(Math.ceil(chunkChars / chunkText.length)).slice(0, chunkChars);

    const longTasks = [];
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        longTasks.push(entry.duration);
      }
    });
    observer.observe({ entryTypes: ["longtask"] });

    const started = performance.now();
    apply({ type: "stream/start", payload: { messageId } });
    let navMs = null;
    for (let i = 0; i < chunks; i++) {
      apply({ type: "stream/chunk", payload: { messageId, chunk: text } });
      if (i === navAt) {
        const navStarted = performance.now();
        const button = document.querySelector('[data-testid="trainer-view-nav-plan"]');
        button.click();
        await new Promise((resolve) => {
          const check = () => {
            const surface = document.querySelector('div[data-surface="plan"]');
            if (surface && !surface.hidden) {
              resolve();
            } else {
              requestAnimationFrame(check);
            }
          };
          requestAnimationFrame(check);
        });
        navMs = performance.now() - navStarted;
      }
      await new Promise((resolve) => setTimeout(resolve, gapMs));
    }
    const streamWallMs = performance.now() - started;
    // Honest check that the burst really rendered: the streaming bubble is the
    // e2e-verified product behavior mid-stream; stream/complete clears it.
    const streamingRendered = Boolean(document.querySelector(".message-bubble--streaming"));
    apply({ type: "stream/complete", payload: { messageId, tokens: chunks * 24 } });
    await new Promise((resolve) => setTimeout(resolve, 150));
    const durations = longTasks.slice();
    observer.disconnect();
    return {
      streamWallMs: Math.round(streamWallMs),
      longtaskCount: durations.length,
      longtaskTotalMs: Math.round(durations.reduce((sum, value) => sum + value, 0)),
      longtaskMaxMs: Math.round(Math.max(0, ...durations)),
      navDuringStreamMs: navMs === null ? null : Math.round(navMs),
      streamingRendered,
    };
  }, { chunks: STREAM_CHUNKS, chunkChars: STREAM_CHUNK_CHARS, gapMs: STREAM_CHUNK_GAP_MS, navAt: navDuringStreamAt });
}

function percentile(samples, ratio) {
  const sorted = [...samples].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.floor(ratio * sorted.length));
  return sorted[index];
}

(async () => {
  const port = previewPort();
  const reusedUrl = process.env.TRAINER_PERF_URL?.trim();
  const baseUrl = reusedUrl || `http://${PREVIEW_HOST}:${port}`;
  let server;
  if (!reusedUrl) {
    server = startPreviewServer(port);
    await waitForServer(baseUrl);
  }

  let report;
  try {
    const browser = await chromium.launch({
      headless: true,
      channel: process.env.TRAINER_E2E_CHANNEL || undefined,
    });

    // ---- 1. Long-session navigation latency (cold first visits vs warm) ----
    const cold = {};
    const warmSamples = { plan: [], resources: [], training: [], settings: [] };
    {
      const page = await openProbePage(browser, baseUrl);
      for (const target of ["plan", "resources", "settings"]) {
        cold[target] = await navLatency(page, target);
        await navLatency(page, "coach");
      }
      cold.training = await visitViaHost(page, "training");
      await navLatency(page, "coach");
      for (let round = 0; round < NAV_SAMPLE_ROUNDS; round++) {
        for (const target of ["plan", "resources", "settings"]) {
          warmSamples[target].push(await navLatency(page, target));
          await navLatency(page, "coach");
        }
        warmSamples.training.push(await visitViaHost(page, "training"));
        await navLatency(page, "coach");
      }
      await page.close();
    }

    // ---- 2. Streaming overhead: coach-only vs all-visited (keep-alive) ----
    const page = await openProbePage(browser, baseUrl);
    const coachOnlyVisited = await runStreamBurst(page, { navDuringStreamAt: null });
    await page.close();

    const pageAll = await openProbePage(browser, baseUrl);
    for (const target of ["plan", "resources", "settings"]) {
      await navLatency(pageAll, target);
      await navLatency(pageAll, "coach");
    }
    await visitViaHost(pageAll, "training");
    await navLatency(pageAll, "coach");
    const allVisited = await runStreamBurst(pageAll, { navDuringStreamAt: 150 });
    await pageAll.close();

    await browser.close();

    const warmP90 = Math.max(
      ...Object.values(warmSamples).map((samples) => percentile(samples, 0.9)),
    );
    const budgets = {
      streamingLongTasks: {
        budget: BUDGETS.streamingLongTasks,
        observed: Math.max(coachOnlyVisited.longtaskCount, allVisited.longtaskCount),
        pass: Math.max(coachOnlyVisited.longtaskCount, allVisited.longtaskCount)
          <= BUDGETS.streamingLongTasks,
      },
      warmNavP90Ms: {
        budget: BUDGETS.warmNavP90Ms,
        observed: warmP90,
        pass: warmP90 < BUDGETS.warmNavP90Ms,
      },
    };

    report = {
      generatedAt: new Date().toISOString(),
      config: {
        baseUrl,
        conversationSize: CONVERSATION_SIZE,
        streamChunks: STREAM_CHUNKS,
        streamChunkChars: STREAM_CHUNK_CHARS,
        streamChunkGapMs: STREAM_CHUNK_GAP_MS,
        navSampleRounds: NAV_SAMPLE_ROUNDS,
      },
      longSessionNav: {
        coldFirstVisitMs: cold,
        warmMs: Object.fromEntries(
          Object.entries(warmSamples).map(([target, samples]) => [
            target,
            {
              n: samples.length,
              min: Math.min(...samples),
              p50: percentile(samples, 0.5),
              p90: percentile(samples, 0.9),
              max: Math.max(...samples),
            },
          ]),
        ),
      },
      streamingOverhead: {
        coachOnlyVisited,
        allVisited,
        hiddenSurfaceDelta: {
          longtaskCountDelta:
            allVisited.longtaskCount - coachOnlyVisited.longtaskCount,
          longtaskTotalMsDelta:
            allVisited.longtaskTotalMs - coachOnlyVisited.longtaskTotalMs,
        },
      },
      budgets,
      limitations: [
        "headless Chromium, single machine, single sample — deltas under ~20% are noise",
        "synthetic chunk injection through the store path, not a live provider stream",
        "longtask observer has a 50ms floor; sub-50ms per-chunk costs are invisible",
      ],
    };

    if (outPath) {
      fs.writeFileSync(outPath, `${JSON.stringify(report, null, 2)}\n`);
      console.log(`[perf-probe] report written to ${outPath}`);
    }
    console.log(JSON.stringify(report, null, 2));
    if (strictMode) {
      const failed = Object.entries(budgets).filter(([, value]) => !value.pass);
      if (failed.length > 0) {
        fail(`budget miss: ${failed.map(([name]) => name).join(", ")}`);
      }
    }
  } finally {
    if (server) {
      server.kill("SIGTERM");
    }
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
