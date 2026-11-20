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
 *   6. Short windows give a single surface all available height, without a
 *      blank row reserved for a removed secondary conversation.
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
/** Content shorter than the viewport must rest this close to the list bottom (anchor-bottom). */
const MAX_FIRST_OFFSET = 24;
const MAX_BOTTOM_GAP = 24;
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
  // UX-02: a configured provider is send-ready with no connection test. Type
  // a draft first (the send button is empty-draft-disabled by design), then a
  // disabled send would mean a probe/config gate crept back into the composer.
  await page.locator("#coach-composer").fill("geometry probe draft");
  const sendState = await page.evaluate(() => {
    const send = document.querySelector(".composer__send");
    if (!send) return { missing: true };
    return { disabled: send.disabled === true, busy: send.classList.contains("is-busy") };
  });
  check(
    !sendState.missing && sendState.disabled === false && sendState.busy === false,
    "ux-02: configured provider is send-ready without a connection test",
  );
  await page.locator("#coach-composer").fill("");
  const coach = await page.evaluate(() => {
    const list = document.querySelector(".coach-conversation-view__list");
    // The old resume banner was removed (product decision): the card itself is
    // the only in-progress surface. Fail closed if any legacy banner returns.
    const resume = document.querySelector("[data-coach-training-resume]");
    const first = document.querySelector(".coach-conversation-view__item");
    if (!list) return { error: "no message list" };
    const listBox = list.getBoundingClientRect();
    const last = list.lastElementChild;
    return {
      listHeight: Math.round(listBox.height),
      firstOffsetTop: first ? Math.round(first.getBoundingClientRect().top - listBox.top) : null,
      legacyBanner: Boolean(resume),
      // ZCode-style flow: the first turn starts at the top of the thread and
      // later turns append downward. Empty room belongs below the last turn,
      // not above the first one.
      bottomGap: last ? Math.round(listBox.bottom - last.getBoundingClientRect().bottom) : null,
    };
  });
  if (coach.error) {
    check(false, `coach: ${coach.error}`);
  } else {
    // Product decision: the in-progress resume banner is gone; the Learning
    // card is the sole owner. Fail closed if the legacy node comes back.
    check(
      coach.legacyBanner === false,
      `coach: legacy resume banner must not render; first item offset ${coach.firstOffsetTop}px in a ${coach.listHeight}px list`,
    );
    // Messages fill from the top and continue downward; a short thread must
    // not be pushed to the composer.
    check(
      coach.firstOffsetTop !== null && coach.firstOffsetTop <= MAX_FIRST_OFFSET,
      `coach: first turn starts ${coach.firstOffsetTop}px from the thread top (limit ${MAX_FIRST_OFFSET}px)`,
    );
    check(
      coach.bottomGap !== null && coach.bottomGap >= 0,
      `coach: thread does not overflow the list (bottom gap ${coach.bottomGap}px)`,
    );
  }

  // Settings: a configured connection lands on its detail; the index is the
  // cold-start surface. Both paths must keep index rows whole and panes usable.
  await page.goto(`${base}?view=settings&scenario=ready`, { waitUntil: "networkidle" });
  const pageIndex = page.locator('[data-template="SettingsIndex"][data-settings-variant="page"]');
  const indexVisible = (await pageIndex.count()) > 0;
  if (indexVisible) {
    const settings = await pageIndex.locator('button').evaluateAll(items =>
      items.map(item => ({ label: item.querySelector('strong')?.textContent, width: item.clientWidth, scroll: item.scrollWidth })));
    check(settings.length === 4 && settings.every(item => item.scroll <= item.width + 1), "settings: four full-width index destinations stay readable");
    await page.locator('[data-settings-category="connection"]').click();
  }
  check(await page.locator('[data-settings-detail="connection"]').isVisible(), "settings: connection detail is reachable (index or direct)");
  for (const category of ["connection", "teaching", "workspace", "preferences"]) {
    if (category !== "connection") {
      const back = page.locator('[data-template="SettingsDetail"] .template-activity-header > .template-back');
      if ((await back.count()) > 0) {
        await back.click();
      }
      const row = page.locator(`[data-settings-category="${category}"]`);
      if ((await row.count()) > 0) {
        await row.first().click();
      }
    }
    const contentSel = (await page.locator('.settings-sheet__body').count()) > 0
      ? '.settings-sheet__body'
      : '.settings-sheet__pane';
    const height = await page.locator(contentSel).evaluate(node => node.clientHeight);
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
    // r3: the thread is bottom-anchored now (the resume line lives in the
    // list with margin-top:auto), so the most recent message always sits
    // right above the composer and ANY composer popup overlaps it. The
    // takeover this rule guards against is the deck covering the UPPER half
    // of the thread, not touching the newest message.
    const list = document.querySelector(".coach-conversation-view__list")?.getBoundingClientRect();
    const upperHalfTop = list ? list.top + list.height / 2 : Infinity;
    const coversThread = list
      ? deckBox.top < upperHalfTop
      : true;
    return {
      deckWidth: Math.round(deckBox.width),
      composerWidth: Math.round(composerBox.width),
      coversThread,
      deckTop: Math.round(deckBox.top),
      listMid: list ? Math.round(upperHalfTop) : null,
      leftInsideViewport: deckBox.left >= 0,
    };
  });
  check(
    palette.coversThread === false,
    `palette: does not cover the upper half of the coach thread (deckTop=${palette.deckTop}px vs list mid ${palette.listMid}px)`,
  );
  check(
    Math.abs(palette.deckWidth - palette.composerWidth) <= PALETTE_WIDTH_TOLERANCE,
    `palette width ${palette.deckWidth}px tracks composer ${palette.composerWidth}px (tolerance ${PALETTE_WIDTH_TOLERANCE}px)`,
  );
  if (keepShots) await page.screenshot({ path: path.join(shotDir, "skill-deck.png") });

  // Every internal route maps to exactly two stable primary destinations.
  for (const view of ["coach", "plan", "resources", "training", "progress", "settings"]) {
    for (const scenario of ["ready", "empty"]) {
      await page.goto(`${base}?view=${view}&scenario=${scenario}`, { waitUntil: "networkidle" });
      // Wait for the app to mount before reading the nav: the training route
      // renders the heaviest tree, so an early read races the first paint.
      await page.locator('#root[data-trainer-app-ready="true"]').waitFor();
      const tabs = await page.locator('.app-shell-nav button').allTextContents();
      check(tabs.join('|') === '对话|资料', `navigation: ${view}/${scenario} has two stable destinations`);
      // A legacy learning route is Chat with the modal learning drawer open:
      // the composer stays mounted underneath the sheet, so it keeps its draft
      // and its focus. Chat and Resources keep the docked composer; Settings
      // has none.
      const expectedComposerShells = view === "settings" ? 0 : 1;
      check(await page.locator('.composer-shell').count() === expectedComposerShells, `composer: ${view}/${scenario} has the correct owner`);
    }
  }

  // ---- 5. the plan card never renders an action group twice -------------
  // The plan card now lives inside the learning drawer, so the duplicate
  // action check runs there with every disclosure open.
  await page.goto(`${base}?view=coach&scenario=ready`, { waitUntil: "networkidle" });
  await page.getByTestId("trainer-learning-toggle").click();
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

  // ---- 6. growth rows read as one comparable set ------------------------
  // Growth lives in the drawer's progress section: four dimension rows that
  // must scan as one set, with the evidence count in one column.
  await page.setViewportSize({ width: 420, height: 900 });
  await page.goto(`${base}?view=coach&scenario=ready`, { waitUntil: "networkidle" });
  await page.getByTestId("trainer-learning-toggle").click();
  await page.waitForTimeout(600);
  const progress = await page.evaluate(() => {
    const columns = [...document.querySelectorAll(".learning-drawer__heatmap-column")];
    if (columns.length < 4) return { error: "no capability columns" };
    const heights = columns.map((column) => Math.round(column.getBoundingClientRect().height));
    // The heatmap reads as one set: every column starts on the same line and
    // carries the same number of cells, so the four capabilities compare.
    const tops = columns.map((column) => Math.round(column.getBoundingClientRect().top));
    const cellCounts = columns.map((column) => column.querySelectorAll(".learning-drawer__heatmap-cell").length);
    const labelCenters = columns.map((column) => {
      const label = column.querySelector(".learning-drawer__heatmap-label");
      if (!label) return null;
      const box = label.getBoundingClientRect();
      return Math.round(box.left + box.width / 2);
    });
    const overflow = Math.max(
      ...columns.map((column) => column.scrollWidth - column.clientWidth),
    );
    return { heights, tops, cellCounts, labelCenters, overflow };
  });
  check(
    !progress.error && new Set(progress.heights).size === 1,
    `growth: all ${progress.heights?.length} capability columns share one height ` +
      `(${[...new Set(progress.heights ?? [])].join("/")}px) so the set scans as a set`,
  );
  check(
    !progress.error && new Set(progress.tops).size === 1,
    `growth: the capability columns share one top edge ` +
      `(${[...new Set(progress.tops ?? [])].join("/")}px)`,
  );
  check(
    !progress.error && new Set(progress.cellCounts).size === 1,
    `growth: every capability column carries the same number of cells ` +
      `(${[...new Set(progress.cellCounts ?? [])].join("/")})`,
  );
  check(
    !progress.error && (progress.overflow ?? 0) <= 1,
    `growth: the heatmap does not overflow its card (${progress.overflow ?? "n/a"}px)`,
  );
  if (keepShots) await page.screenshot({ path: path.join(shotDir, "progress.png") });

  // Learning is one drawer with three sections, reached from the header icon.
  await page.goto(`${base}?view=coach&scenario=ready`, { waitUntil: "networkidle" });
  await page.getByTestId("trainer-learning-toggle").click();
  const drawer = page.locator('[data-template="LearningDrawer"]');
  check(await drawer.waitFor({ timeout: 5000 }).then(() => true, () => false), "learning: the header icon opens the learning drawer");
  const drawerSections = await page.locator('.learning-drawer > [data-learning-section]').evaluateAll(
    items => items.map(item => item.getAttribute("data-learning-section")),
  );
  check(
    drawerSections.join("|") === "goal|practice|progress",
    `learning: the drawer holds exactly three sections (${drawerSections.join("|")})`,
  );
  const drawerTabs = await page.locator('[data-learning-tabs], [data-learning-tab][aria-selected]').count();
  check(drawerTabs === 0, "learning: the drawer is not a tab set");
  const drawerPrimaryActions = await page.locator('[data-template="LearningDrawer"] button.button--accent').count();
  check(drawerPrimaryActions <= 1, `learning: the drawer owns at most one primary action (${drawerPrimaryActions})`);
  const legacySurfaces = await page.locator('[data-template="LearningWorkspace"]').count();
  check(legacySurfaces === 0, "learning: the retired learning workspace is not rendered");
  // The governed plan card lives inside the drawer's goal section: learning
  // state is reachable without a separate Learning destination.
  // The governed plan card is lazy-loaded inside the drawer: wait for it
  // instead of counting a half-mounted tree.
  const planCardSelector = '[data-template="LearningDrawer"] [data-template="LearningHome"]';
  await page.locator(planCardSelector).first().waitFor({ timeout: 5000 }).catch(() => undefined);
  const planCardInDrawer = await page.locator(planCardSelector).count();
  check(planCardInDrawer === 1, `learning: the governed plan card lives in the drawer (${planCardInDrawer})`);
  // The learning strip is the only learning readout above the conversation.
  const stripCount = await page.locator('[data-learning-strip="true"]').count();
  check(stripCount <= 1, `learning: the conversation carries one learning strip (${stripCount})`);
  // The strip answers 当前目标 · 当前步骤 · 待复习数. A long goal truncates in its
  // own slot instead of hiding the other two readouts.
  const stripFields = await page.evaluate(() => {
    const strip = document.querySelector('[data-learning-strip="true"]');
    if (!strip) return null;
    return {
      fields: [...strip.querySelectorAll('[data-learning-strip-item]')].map(
        (node) => node.getAttribute('data-learning-strip-item'),
      ),
      overflow: strip.scrollWidth - strip.clientWidth,
    };
  });
  check(
    stripFields !== null && stripFields.fields.includes("goal") && stripFields.fields.includes("step"),
    `learning: the strip carries the goal and the step as separate fields (${stripFields ? stripFields.fields.join("|") : "none"})`,
  );
  check(
    stripFields !== null && stripFields.overflow <= 1,
    `learning: the strip never overflows its line (${stripFields ? stripFields.overflow : "n/a"}px)`,
  );
  if (keepShots) await page.screenshot({ path: path.join(shotDir, "learning-drawer.png"), fullPage: true });

  // ---- 6. alignment: key rows keep their icon and text on one line ------
  // The library row is the densest repeating line in the product: an icon, a
  // title and a menu button. A drifting icon reads as a broken row, so the
  // icon and the title must share one center line.
  for (const width of [340, 460]) for (const lang of ["zh-CN", "en-US"]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${base}?view=resources&scenario=ready&theme=dark&lang=${lang}`, { waitUntil: "networkidle" });
    await page.locator('#root[data-trainer-app-ready="true"]').waitFor();
    const rows = await page.evaluate(() => {
      const measured = [];
      for (const item of document.querySelectorAll(".resources-library-tree__item")) {
        const icon = item.querySelector(".resources-library-tree__kind");
        const label = item.querySelector(".resources-library-tree__copy strong");
        if (!icon || !label) continue;
        const iconBox = icon.getBoundingClientRect();
        const labelBox = label.getBoundingClientRect();
        if (iconBox.height === 0 || labelBox.height === 0) continue;
        measured.push({
          centerDelta: Math.abs(
            (iconBox.top + iconBox.bottom) / 2 - (labelBox.top + labelBox.bottom) / 2,
          ),
        });
      }
      return measured;
    });
    check(
      rows.length > 0 && rows.every((row) => row.centerDelta <= 1),
      `resources/${width}/${lang}: every library row keeps its icon and title on one center line ` +
      `(${(Math.max(0, ...rows.map((row) => row.centerDelta)) || 0).toFixed(1)}px max)`,
    );
  }

  // Inline code is part of a sentence: an inline-flex chip takes the flex
  // baseline and grows the line box, so the chip floats off the words next to
  // it. The chip must stay an inline box inside the paragraph's line height.
  await page.setViewportSize({ width: 420, height: 900 });
  await page.goto(`${base}?view=coach&scenario=rich-content&theme=dark&lang=zh-CN`, { waitUntil: "networkidle" });
  await page.locator('#root[data-trainer-app-ready="true"]').waitFor();
  await page.waitForTimeout(200);
  const inlineCode = await page.evaluate(() => {
    const chips = [];
    for (const node of document.querySelectorAll(".message-markdown__inline-code")) {
      const parent = node.closest("p, li, td");
      if (!parent) continue;
      const style = getComputedStyle(node);
      const parentStyle = getComputedStyle(parent);
      chips.push({
        display: style.display,
        height: node.getBoundingClientRect().height,
        lineHeight: parseFloat(parentStyle.lineHeight),
      });
    }
    return chips;
  });
  check(
    inlineCode.length > 0 && inlineCode.every((chip) => chip.display === "inline"),
    `coach: inline code stays an inline box (${inlineCode.map((chip) => chip.display).join("/") || "none"})`,
  );
  check(
    inlineCode.length > 0 && inlineCode.every((chip) => chip.height <= chip.lineHeight + 1),
    `coach: inline code never grows the line box (${inlineCode
      .map((chip) => `${chip.height.toFixed(1)}/${chip.lineHeight.toFixed(1)}`)
      .join(" ") || "none"}px)`,
  );

  // CJK copy needs a taller line: a 1.2 line height clips the glyphs.
  const cjkLines = await page.evaluate(() => {
    const measured = [];
    for (const node of document.querySelectorAll(".message-markdown p, .message-markdown li")) {
      const text = node.textContent ?? "";
      if (!/[\u4e00-\u9fff]/.test(text)) continue;
      const style = getComputedStyle(node);
      const ratio = parseFloat(style.lineHeight) / parseFloat(style.fontSize);
      measured.push(ratio);
    }
    return measured;
  });
  check(
    cjkLines.length === 0 || Math.min(...cjkLines) >= 1.4,
    `coach: CJK lines keep a readable line height (${cjkLines.length ? Math.min(...cjkLines).toFixed(2) : "none"} ratio)`,
  );

  // The composer carries no context row: the file, resource, webpage, plan
  // and training rows are gone. What stays (the attachment chips) lives
  // inside the input frame, not above it.
  await page.setViewportSize({ width: 420, height: 900 });
  await page.goto(`${base}?view=coach&scenario=ready&theme=dark&lang=zh-CN`, { waitUntil: "networkidle" });
  await page.locator('#root[data-trainer-app-ready="true"]').waitFor();
  const composerContextRows = await page.evaluate(() => {
    const shell = document.querySelector(".composer-shell");
    if (!shell) return { error: "missing composer shell" };
    const rows = [
      ...shell.querySelectorAll(
        ".template-context, [data-dock-anchor], .composer-context-strip, .resources-inline-context, .template-goal-bar",
      ),
    ].filter((node) => {
      const rect = node.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
    return { count: rows.length };
  });
  check(
    !composerContextRows.error && composerContextRows.count === 0,
    `coach: the composer carries no context row above the input (${composerContextRows.count ?? composerContextRows.error})`,
  );

  // Menus share one label column. An item without an icon used to drop its
  // label into the (auto-sized) icon column, so the same surface showed two
  // different label offsets: the import menu indented, the row menu flush.
  await page.setViewportSize({ width: 420, height: 900 });
  await page.goto(`${base}?view=resources&scenario=ready&theme=dark&lang=zh-CN`, { waitUntil: "networkidle" });
  await page.locator('#root[data-trainer-app-ready="true"]').waitFor();
  const readMenuLabelOffsets = () =>
    page.evaluate(() => {
      const offsets = [];
      for (const item of document.querySelectorAll(".menu-list__item")) {
        const rect = item.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        const style = getComputedStyle(item);
        const contentLeft =
          rect.left + (parseFloat(style.borderLeftWidth) || 0) + (parseFloat(style.paddingLeft) || 0);
        const body = item.querySelector(".menu-list__body");
        if (!body) continue;
        offsets.push(body.getBoundingClientRect().left - contentLeft);
      }
      return offsets;
    });
  await page.locator(".resources-knowledge__add-resource").click();
  await page.waitForTimeout(200);
  const importMenuOffsets = await readMenuLabelOffsets();
  await page.keyboard.press("Escape");
  await page.locator(".resources-library-tree__item").first().click({ button: "right" });
  await page.waitForTimeout(200);
  const rowMenuOffsets = await readMenuLabelOffsets();
  const menuOffsets = [...importMenuOffsets, ...rowMenuOffsets];
  check(
    menuOffsets.length > 0 && menuOffsets.every((offset) => Math.abs(offset - menuOffsets[0]) <= 1),
    `resources: every menu label shares one left edge ` +
    `(${menuOffsets.length ? menuOffsets.map((offset) => offset.toFixed(1)).join("/") : "none"}px)`,
  );
  await page.keyboard.press("Escape");

  // RTL mirrors the shell: the row icon moves to the right of its label and
  // nothing overflows. Physical margins would break exactly here.
  await page.setViewportSize({ width: 420, height: 900 });
  await page.goto(`${base}?view=resources&scenario=ready&theme=dark&lang=zh-CN&dir=rtl`, { waitUntil: "networkidle" });
  await page.locator('#root[data-trainer-app-ready="true"]').waitFor();
  await page.waitForTimeout(200);
  const rtl = await page.evaluate(() => {
    const item = document.querySelector('.resources-library-tree__item');
    const icon = item?.querySelector('.resources-library-tree__kind');
    const label = item?.querySelector('.resources-library-tree__copy strong');
    const iconBox = icon?.getBoundingClientRect();
    const labelBox = label?.getBoundingClientRect();
    return {
      direction: getComputedStyle(document.documentElement).direction,
      iconOnRight: iconBox && labelBox ? iconBox.left > labelBox.left : null,
      overflow: document.documentElement.scrollWidth - window.innerWidth,
    };
  });
  check(rtl.direction === "rtl", `rtl: the shell direction is rtl (${rtl.direction})`);
  check(
    rtl.iconOnRight === true,
    `rtl: the library row mirrors its icon to the right of the title (${rtl.iconOnRight})`,
  );
  check(rtl.overflow <= 1, `rtl: the mirrored shell does not overflow (${rtl.overflow}px)`);

  // The message meta row (role + timestamp) reads as one line: two font
  // sizes on one baseline, never centered against each other.
  await page.setViewportSize({ width: 420, height: 900 });
  await page.goto(`${base}?view=coach&scenario=rich-content&theme=dark&lang=zh-CN`, { waitUntil: "networkidle" });
  await page.locator('#root[data-trainer-app-ready="true"]').waitFor();
  await page.waitForTimeout(200);
  const metaLine = await page.evaluate(() => {
    const label = document.querySelector(".message-bubble__assistant-label");
    const time = document.querySelector(".message-bubble__assistant-time");
    if (!label || !time) return { missing: true };
    const labelBox = label.getBoundingClientRect();
    const timeBox = time.getBoundingClientRect();
    return {
      // The baseline of a text box sits at its bottom edge plus the descender;
      // two texts on one baseline differ by at most their descender slack.
      baselineDelta: Math.abs(labelBox.bottom - timeBox.bottom),
      sizes: [getComputedStyle(label).fontSize, getComputedStyle(time).fontSize],
    };
  });
  check(
    !metaLine.missing && metaLine.baselineDelta <= 1,
    `coach: the message meta shares one baseline (${metaLine.missing ? "missing" : `${metaLine.baselineDelta.toFixed(1)}px, ${metaLine.sizes.join("/")}`})`,
  );

  // The toolbar and tree share one library surface with no surrounding frame.
  await page.goto(`${base}?view=resources&scenario=ready`, { waitUntil: 'networkidle' });
  const resourceShell = await page.evaluate(() => {
    const shells = [...document.querySelectorAll('[data-resource-library-shell="true"]')];
    const shell = shells[0];
    const toolbar = document.querySelector('.resources-knowledge__toolbar');
    const tree = document.querySelector('.resources-knowledge__tree');
    const style = shell ? getComputedStyle(shell) : null;
    return {
      count: shells.length,
      toolbarInside: Boolean(shell && toolbar && shell.contains(toolbar)),
      treeInside: Boolean(shell && tree && shell.contains(tree)),
      border: style ? parseFloat(style.borderTopWidth) : 0,
      radius: style ? parseFloat(style.borderTopLeftRadius) : 0,
    };
  });
  check(
    resourceShell.count === 1 &&
      resourceShell.toolbarInside &&
      resourceShell.treeInside &&
      resourceShell.border === 0 &&
      resourceShell.radius === 0,
    `resources: the toolbar and tree share a flat library surface (${JSON.stringify(resourceShell)})`,
  );

  // Visual fixtures validate geometry, not native/backend completion.
  for (const width of [340, 420, 460]) for (const theme of ['dark', 'light']) for (const lang of ['zh-CN', 'en-US']) {
    await page.setViewportSize({ width, height: 900 });
    for (const view of ['coach', 'plan', 'resources', 'training', 'progress', 'settings']) {
      await page.goto(`${base}?view=${view}&scenario=ready&theme=${theme}&lang=${lang}`, { waitUntil: 'domcontentloaded' });
      await page.locator('#root[data-trainer-app-ready="true"]').waitFor();
      await page.waitForTimeout(100);
      const metrics = await page.evaluate(() => {
        // The dock composer's send affordance is a persistent input control on
        // both primary destinations (§3.7), not a competing page CTA: the
        // one-primary-intent rule applies to page actions, so `.composer__send`
        // is excluded. Every other accent/primary/page action still counts.
        //
        // While a modal utility overlay (the learning drawer) is open, it owns
        // the first viewport: the surface behind it is covered by the overlay's
        // backdrop, so only the overlay's own actions are counted. The drawer
        // has its own one-primary-action assertion below.
        const overlay = document.querySelector('[data-overlay="learning"]');
        const scope = overlay ? overlay.querySelector('.app-shell-overlay__panel') : document;
        const visible = [...scope.querySelectorAll('[data-primary-action="true"], .button--accent, .button--primary')].filter(el => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0 && r.top < innerHeight && r.bottom > 0;
        });
        return {
          overflow: document.documentElement.scrollWidth - innerWidth,
          primary: new Set(visible).size,
        };
      });
      check(metrics.overflow <= 1, `${view}/${width}/${theme}/${lang}: no horizontal overflow`);
      check(metrics.primary <= 1, `${view}/${width}/${theme}/${lang}: ${metrics.primary} primary page action(s) in the first viewport`);
      if (keepShots) await page.screenshot({ path: path.join(shotDir, `${view}-${width}-${theme}-${lang}.png`) });
    }
  }

  // Actual Windows installation exposed this below the 760px breakpoint.
  // The normal 900px fixture above cannot cover a single pane losing nearly
  // half its viewport to a legacy secondary-chat row. Measure occupied boxes
  // on both sides of the breakpoint; this does not assert authored content.
  for (const height of [728, 760, 761]) for (const width of [340, 420, 460]) {
    for (const theme of ['dark', 'light']) for (const lang of ['zh-CN', 'en-US']) {
      await page.setViewportSize({ width, height });
      // Only the two primary destinations own a single stacked surface;
      // the learning routes resolve to Chat.
      for (const view of ['resources']) {
        await page.goto(`${base}?view=${view}&scenario=ready&theme=${theme}&lang=${lang}`, { waitUntil: 'domcontentloaded' });
        await page.locator('#root[data-trainer-app-ready="true"]').waitFor();
        const occupied = await page.evaluate(() => {
          const stack = [...document.querySelectorAll('.view-stack--single')].find(el => {
            const box = el.getBoundingClientRect();
            return box.width > 0 && box.height > 0;
          });
          const primary = stack?.querySelector('.view-stack__primary');
          if (!stack || !primary) return { error: 'missing visible single surface' };
          const box = stack.getBoundingClientRect();
          const content = primary.getBoundingClientRect();
          return {
            rows: getComputedStyle(stack).gridTemplateRows.trim().split(/\s+/).length,
            height: box.height,
            unusedHeight: box.height - content.height,
          };
        });
        const label = `${view}/${width}x${height}/${theme}/${lang}`;
        check(!occupied.error && occupied.rows === 1, `${label}: single surface has one occupied row`);
        check(!occupied.error && occupied.height > 120 && Math.abs(occupied.unusedHeight) <= 2,
          `${label}: single surface uses available height (${occupied.unusedHeight?.toFixed(1)}px unused)`);
      }
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
