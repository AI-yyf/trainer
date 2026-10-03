/**
 * UI geometry gate — asserts the layout defects this workbench actually shipped
 * stay fixed, by measuring real boxes in the browser preview instead of
 * eyeballing screenshots.
 *
 * Each rule below pins a regression that shipped and was invisible to the
 * 4675 unit tests:
 *
 *   1. Coach thread has no dead zone. Messages used to be bottom-anchored by a
 *      `::before { flex: 1 0 0 }` spacer while the resume banner rendered
 *      *outside* the list, opening a ~540px hole between banner and first
 *      message in a 900px sidebar.
 *   2. Settings category labels are never truncated or wrapped per glyph. Six
 *      categories sharing a row with the action cluster squeezed each label to
 *      18px wide, so "高级上下文" rendered as "高级" and "工作区" as 工/做 on two
 *      lines — the overflow detector compared the nav's scrollWidth to its
 *      clientWidth, which never differ once items are allowed to shrink.
 *   3. The $ skill palette never covers the conversation, and matches the
 *      composer's own width.
 *   4. Exactly three primary destinations remain stable across all six routes.
 *      Training and Growth select Learning, and Settings uses its utility.
 *   5. No action is rendered twice in the plan view.
 *
 * Usage:
 *   node scripts/verify-ui-geometry.mjs
 *   node scripts/verify-ui-geometry.mjs --keep-shots   # write failures to .tmp/
 */

import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:net";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const webviewRoot = path.join(repoRoot, "extension", "webview");
const shotDir = path.join(repoRoot, ".tmp", "ui-geometry");
const PORT = Number(process.env.TRAINER_GEOMETRY_PORT ?? 4178);
const HOST = "127.0.0.1";
const keepShots = process.argv.includes("--keep-shots");
/** Hard ceiling: the gate builds the preview bundle, so it is not instant. */
const OVERALL_BUDGET_MS = Number(process.env.TRAINER_GEOMETRY_BUDGET_MS ?? 420_000);

const budgetTimer = setTimeout(() => {
  console.error(`\n[verify-ui-geometry] FAIL exceeded the ${OVERALL_BUDGET_MS}ms budget\n`);
  process.exit(1);
}, OVERALL_BUDGET_MS);
budgetTimer.unref?.();

/** A gap larger than this between the resume banner and the first message is a hole. */
const MAX_RESUME_GAP = 24;
/** Palette may not extend past the composer it belongs to. */
const PALETTE_WIDTH_TOLERANCE = 4;
/** A label taller than this has wrapped onto a second line. */
const MAX_LABEL_LINES = 1.6;

const failures = [];
const notes = [];

function check(ok, message) {
  if (ok) {
    notes.push(`  PASS  ${message}`);
  } else {
    failures.push(message);
    notes.push(`  FAIL  ${message}`);
  }
}

function viteBin(name) {
  return path.join(webviewRoot, "node_modules", name, "bin", name === "vite" ? "vite.js" : "tsc");
}

function buildPreviewBundle() {
  // Quiet on success. A full `vite build` narrates every emitted font chunk —
  // ~36KB of noise for a few seconds of work, which drowns the gate's own
  // output in any log-capturing harness. Failures still print in full.
  for (const [bin, args] of [
    ["typescript", ["-b"]],
    ["vite", ["build", "--mode", "preview", "--logLevel", "error"]],
  ]) {
    const result = spawnSync(process.execPath, [viteBin(bin), ...args], {
      cwd: webviewRoot,
      stdio: "pipe",
      encoding: "utf8",
    });
    if (result.status !== 0) {
      process.stdout.write(result.stdout ?? "");
      process.stderr.write(result.stderr ?? "");
      console.error(`[verify-ui-geometry] preview build failed (${bin})`);
      process.exit(result.status ?? 1);
    }
  }
}

/** Children we spawned, so nothing survives us — including on a signal. */
const spawned = new Set();

function track(child) {
  spawned.add(child);
  child.once("exit", () => spawned.delete(child));
  return child;
}

function killTree(child, signal) {
  if (!child?.pid) return;
  try {
    // Negative pid targets the process group: `vite preview` spawns workers
    // and `python run_sidecar.py` may too, so killing only the direct child
    // leaked servers that kept burning CPU for the rest of the session.
    process.kill(-child.pid, signal);
  } catch {
    try {
      child.kill(signal);
    } catch {
      /* already gone */
    }
  }
}

function killAll(signal = "SIGKILL") {
  for (const child of spawned) killTree(child, signal);
  spawned.clear();
}

/**
 * Reclaim our port from a previous, SIGKILL-ed run.
 *
 * No signal handler can run when the harness SIGKILLs this process, so a
 * detached `vite preview` can survive. Left alone these accumulate across
 * runs: a dozen idle preview servers is enough to starve the machine and make
 * later gates time out for no reason of their own. Killing whatever already
 * holds our port makes the gate self-healing.
 */
function reclaimPort(port) {
  const pids = new Set();
  const collect = (command) => {
    try {
      const out = spawnSync(command[0], command.slice(1), { encoding: "utf8" });
      for (const line of (out.stdout ?? "").split("\n")) {
        const pid = Number.parseInt(line.trim(), 10);
        if (Number.isInteger(pid) && pid > 1 && pid !== process.pid) pids.add(pid);
      }
    } catch {
      /* tool unavailable; the strictPort retry below still covers it */
    }
  };
  collect(["lsof", "-ti", `:${port}`]);
  if (pids.size === 0) collect(["fuser", "-n", "tcp", String(port)]);
  for (const pid of pids) {
    try {
      process.kill(pid, "SIGKILL");
      console.log(`[verify-ui-geometry] reclaimed port ${port} from pid ${pid}`);
    } catch {
      /* it exited on its own */
    }
  }
  if (pids.size) spawnSync(process.execPath, ["-e", "setTimeout(()=>{},300)"]);
}

for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
  process.on(signal, () => {
    killAll("SIGKILL");
    process.exit(1);
  });
}
process.on("exit", () => killAll("SIGKILL"));

async function startServer() {
  // A crashed or interrupted run can leave the preview server holding the port,
  // which made the next run die on --strictPort instead of reporting anything.
  const freePort = () =>
    new Promise((resolve, reject) => {
      const probe = createServer();
      probe.on("error", reject);
      probe.listen(0, HOST, () => {
        const { port } = probe.address();
        probe.close(() => resolve(port));
      });
    });

  let port = PORT;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    reclaimPort(port);
    const child = track(
      spawn(
        process.execPath,
        [viteBin("vite"), "preview", "--port", String(port), "--host", HOST, "--strictPort"],
        // Its own process group, so killTree(-pid) reaches vite's workers.
        { cwd: webviewRoot, stdio: ["ignore", "pipe", "pipe"], detached: true },
      ),
    );
    const started = await new Promise((resolve) => {
      const timer = setTimeout(() => resolve(false), 30000);
      child.stdout.on("data", (chunk) => {
        if (String(chunk).includes(`:${port}`) || String(chunk).includes(` ${port} `)) {
          clearTimeout(timer);
          resolve(true);
        }
      });
      child.on("exit", () => {
        clearTimeout(timer);
        resolve(false);
      });
    });
    if (started) {
      if (port !== PORT) {
        console.log(`[verify-ui-geometry] port ${PORT} busy, using ${port}`);
      }
      return child;
    }
    killTree(child, "SIGKILL");
    port = await freePort();
  }
  throw new Error(`preview server could not start on ${HOST}:${PORT}`);
}

async function main() {
  buildPreviewBundle();
  const browser = await chromium.launch();
  const server = await startServer();
  const stopServer = () => killAll("SIGKILL");
  const serverPort = Number(
    (server.spawnargs ?? []).find((arg) => /^\d+$/.test(arg) && Number(arg) !== 0) ?? PORT,
  );
  const base = `http://${HOST}:${serverPort}/vscode-preview.html`;
  const context = await browser.newContext({
    viewport: { width: 420, height: 900 },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  if (keepShots) fs.mkdirSync(shotDir, { recursive: true });

  // ---- 1. coach thread has no dead zone -------------------------------
  await page.goto(`${base}?view=coach&scenario=ready`, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  const coach = await page.evaluate(() => {
    const list = document.querySelector(".coach-conversation-view__list");
    const resume = document.querySelector(".coach-training-resume");
    const first = document.querySelector(".coach-conversation-view__item");
    if (!list) return { error: "no message list" };
    const listBox = list.getBoundingClientRect();
    return {
      listHeight: Math.round(listBox.height),
      firstOffsetTop: first ? Math.round(first.getBoundingClientRect().top - listBox.top) : null,
      gapAfterBanner: resume && first
        ? Math.round(first.getBoundingClientRect().top - resume.getBoundingClientRect().bottom)
        : null,
    };
  });
  check(
    coach.gapAfterBanner === null || coach.gapAfterBanner <= MAX_RESUME_GAP,
    `coach: banner→first-message gap ${coach.gapAfterBanner}px (limit ${MAX_RESUME_GAP}px); first item offset ${coach.firstOffsetTop}px in a ${coach.listHeight}px list`,
  );

  // Settings index rows remain whole; detail is a separate destination.
  await page.goto(`${base}?view=settings&scenario=ready`, { waitUntil: "networkidle" });
  const settings = await page.locator('[data-template="SettingsIndex"] button').evaluateAll(items =>
    items.map(item => ({ label: item.querySelector('strong')?.textContent, width: item.clientWidth, scroll: item.scrollWidth })));
  check(settings.length === 4 && settings.every(item => item.scroll <= item.width + 1), "settings: four full-width index destinations stay readable");
  await page.locator('[data-settings-category="connection"]').click();
  check(await page.locator('[data-settings-detail="connection"]').isVisible(), "settings: connection opens through the index with a back action");
  for (const category of ["connection", "teaching", "workspace", "preferences"]) {
    if (category !== "connection") {
      await page.locator('[data-template="SettingsDetail"] .template-activity-header > .template-back').click();
      await page.locator(`[data-settings-category="${category}"]`).click();
    }
    const height = await page.locator('.settings-sheet__pane').evaluate(node => node.clientHeight);
    check(height > 120, `settings/${category}: actual content pane is usable (${height}px)`);
  }
  if (keepShots) await page.screenshot({ path: path.join(shotDir, "settings.png") });

  // ---- 3. $ palette does not cover the thread -------------------------
  await page.goto(`${base}?view=coach&scenario=ready`, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  await page.locator("#coach-composer").fill("$");
  await page.locator(".template-command-palette").waitFor({ state: "visible" }).catch(() => {});
  await page.waitForTimeout(400);
  const palette = await page.evaluate(() => {
    const deck = document.querySelector(".template-command-palette");
    const composer = document.querySelector(".composer");
    if (!deck || !composer) return { error: "missing deck or composer" };
    const deckBox = deck.getBoundingClientRect();
    const composerBox = composer.getBoundingClientRect();
    const first = document.querySelector(".coach-conversation-view__item")?.getBoundingClientRect();
    const covers = (box) =>
      box ? !(box.bottom < deckBox.top || box.top > deckBox.bottom) : false;
    return {
      deckWidth: Math.round(deckBox.width),
      composerWidth: Math.round(composerBox.width),
      coversThread: covers(first),
      leftInsideViewport: deckBox.left >= 0,
    };
  });
  check(
    palette.coversThread === false,
    `palette: does not cover the coach thread (coversThread=${palette.coversThread})`,
  );
  check(
    Math.abs(palette.deckWidth - palette.composerWidth) <= PALETTE_WIDTH_TOLERANCE,
    `palette width ${palette.deckWidth}px tracks composer ${palette.composerWidth}px (tolerance ${PALETTE_WIDTH_TOLERANCE}px)`,
  );
  if (keepShots) await page.screenshot({ path: path.join(shotDir, "skill-deck.png") });

  // Every internal route maps to exactly three stable primary destinations.
  for (const view of ["coach", "plan", "resources", "training", "progress", "settings"]) {
    for (const scenario of ["ready", "empty"]) {
      await page.goto(`${base}?view=${view}&scenario=${scenario}`, { waitUntil: "networkidle" });
      const tabs = await page.locator('.app-shell-nav button').allTextContents();
      check(tabs.join('|') === '对话|学习|资料', `navigation: ${view}/${scenario} has three stable destinations`);
      check(await page.locator('.composer-shell').count() === (view === 'coach' ? 1 : 0), `composer: ${view}/${scenario} has the correct owner`);
    }
  }

  // ---- 5. the plan view never renders an action group twice -------------
  await page.goto(`${base}?view=plan&scenario=ready`, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  await page.evaluate(() => document.querySelectorAll("details").forEach((d) => (d.open = true)));
  await page.waitForTimeout(400);
  const duplicates = await page.evaluate(() => {
    // Repeating a label down a list is correct — every stage row has its own
    // 生成资料, every evidence row its own 接纳/拒绝/延期. The defect is one
    // logical action group rendered in two different containers, which is how
    // 生成计划 used to appear both under the 动作 disclosure and again inside
    // 更多. So: ignore per-row repeats, and flag a label that shows up under
    // two *different* group containers.
    const PER_ROW = ["stage-row", "coach-plan-view__evidence-row", "coach-plan-view__subplan-row"];
    const GROUP = [
      "coach-plan-view__actions-stack",
      "coach-plan-view__actions-inline",
      "coach-plan-view__details-group",
      "coach-plan-view__empty-more",
    ];
    const containers = new Map();
    for (const button of document.querySelectorAll("button")) {
      const label = (button.textContent ?? "").trim().split("\n")[0].trim();
      if (!label) continue;
      let node = button;
      let inPerRow = false;
      let group = null;
      while (node && node !== document.body) {
        const classes = typeof node.className === "string" ? node.className : "";
        if (PER_ROW.some((marker) => classes.includes(marker))) inPerRow = true;
        if (!group && GROUP.some((marker) => classes.includes(marker))) group = classes;
        node = node.parentElement;
      }
      if (inPerRow || !group) continue;
      const key = group.split(" ").filter(Boolean).sort().join(".");
      if (!containers.has(label)) containers.set(label, new Set());
      containers.get(label).add(key);
    }
    return [...containers.entries()]
      .filter(([, groups]) => groups.size > 1)
      .map(([label, groups]) => `${label} in ${groups.size} groups`);
  });
  check(
    duplicates.length === 0,
    duplicates.length === 0
      ? "plan: no action group renders twice with all disclosures open"
      : `plan: same action in multiple groups: ${duplicates.join(", ")}`,
  );
  if (keepShots) {
    await page.screenshot({ path: path.join(shotDir, "plan-expanded.png"), fullPage: true });
  }

  // ---- 6. capability rows read as one comparable set -------------------
  await page.setViewportSize({ width: 420, height: 900 });
  await page.goto(`${base}?view=progress&scenario=ready`, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  const progress = await page.evaluate(() => {
    // The nudge line reuses .progress-view__row, so scope to the real
    // capability rows: those are the ones carrying an evidence count.
    const rows = [...document.querySelectorAll(".progress-view__row")].filter((row) =>
      row.querySelector(".progress-view__evidence"),
    );
    if (rows.length < 4) return { error: "no capability rows" };
    const heights = rows.map((row) => Math.round(row.getBoundingClientRect().height));
    const counts = rows.map((row) => {
      const el = row.querySelector(".progress-view__evidence");
      const style = el ? getComputedStyle(el) : null;
      return {
        width: el ? Math.round(el.getBoundingClientRect().width) : 0,
        align: style?.textAlign,
      };
    });
    return {
      heights,
      countWidths: counts.map((c) => c.width),
      aligns: [...new Set(counts.map((c) => c.align))],
    };
  });
  check(
    !progress.error && new Set(progress.heights).size === 1,
    `progress: all ${progress.heights?.length} capability rows share one height ` +
      `(${[...new Set(progress.heights ?? [])].join("/")}px) so the set scans as a set`,
  );
  check(
    !progress.error &&
      new Set(progress.countWidths).size === 1 &&
      progress.aligns.every((align) => align === "end"),
    `progress: evidence counts share one right-aligned column ` +
      `(${[...new Set(progress.countWidths ?? [])].join("/")}px, align=${progress.aligns?.join("/")})`,
  );
  if (keepShots) await page.screenshot({ path: path.join(shotDir, "progress.png") });

  // Learning presents the current task before closed secondary destinations.
  await page.goto(`${base}?view=plan&scenario=ready`, { waitUntil: "networkidle" });
  check(await page.locator('[data-template="LearningHome"]').isVisible(), "learning: current learning uses the shared home template");
  const learningDisclosures = await page.locator('[data-template="LearningHome"] > [data-learning-section]').evaluateAll(items => items.map(item => item.open));
  check(learningDisclosures.length === 4 && learningDisclosures.every(open => !open), "learning: review, route, growth and evidence start closed");

  // Visual fixtures validate geometry, not native/backend completion.
  for (const width of [340, 420, 460]) for (const theme of ['dark', 'light']) for (const lang of ['zh-CN', 'en-US']) {
    await page.setViewportSize({ width, height: 900 });
    for (const view of ['coach', 'plan', 'resources', 'training', 'progress', 'settings']) {
      await page.goto(`${base}?view=${view}&scenario=ready&theme=${theme}&lang=${lang}`, { waitUntil: 'domcontentloaded' });
      await page.locator('#root[data-trainer-app-ready="true"]').waitFor();
      await page.waitForTimeout(100);
      const metrics = await page.evaluate(() => {
        const visible = [...document.querySelectorAll('[data-primary-action="true"], .button--accent, .button--primary, .composer__send')].filter(el => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0 && r.top < innerHeight && r.bottom > 0;
        });
        return { overflow: document.documentElement.scrollWidth - innerWidth, primary: new Set(visible).size };
      });
      check(metrics.overflow <= 1, `${view}/${width}/${theme}/${lang}: no horizontal overflow`);
      check(metrics.primary <= 1, `${view}/${width}/${theme}/${lang}: ${metrics.primary} primary action(s) in the first viewport`);
      if (keepShots) await page.screenshot({ path: path.join(shotDir, `${view}-${width}-${theme}-${lang}.png`) });
    }
  }

  await browser.close();
  stopServer();

  console.log("\n[verify-ui-geometry]");
  console.log(notes.join("\n"));
  if (failures.length) {
    console.error(`\n[verify-ui-geometry] FAIL ${failures.length} geometry regression(s)\n`);
    process.exit(1);
  }
  console.log(`\n[verify-ui-geometry] OK ${notes.length} geometry assertions passed\n`);
  clearTimeout(budgetTimer);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
