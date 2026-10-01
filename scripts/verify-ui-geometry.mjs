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
 *   4. Every top-level view is reachable from the tab row in every view and
 *      every scenario. 训练 and 成长 used to appear only once you were already
 *      inside them, so a fresh session had no way in.
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

  // ---- 2. settings labels stay whole ----------------------------------
  await page.goto(`${base}?view=settings&scenario=ready`, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  await page.getByRole("button", { name: "编辑配置", exact: true }).click().catch(() => {});
  await page.waitForTimeout(500);
  const settings = await page.evaluate((maxLabelLines) => {
    const nav = document.querySelector(".settings-nav");
    if (!nav) return { error: "no settings nav" };
    const items = [...nav.querySelectorAll(".settings-nav__item")].map((item) => {
      const label = item.querySelector(".settings-nav__label");
      const style = label ? getComputedStyle(label) : null;
      const box = label?.getBoundingClientRect();
      const itemBox = item.getBoundingClientRect();
      const lineHeight = style ? parseFloat(style.lineHeight) || 14 : 14;
      return {
        label: label?.textContent?.trim() ?? "",
        hidden: style?.display === "none",
        labelWidth: box ? Math.round(box.width) : 0,
        // Truncation is the real failure: the element is narrower than its own
        // content. Length-agnostic, so it holds for every language and for the
        // abbreviated dense labels.
        truncated: label ? label.scrollWidth > label.clientWidth + 1 : false,
        // CJK wrapping one glyph per line also inflates the box height.
        wrapped: box ? box.height > lineHeight * maxLabelLines : false,
        nowrap: style ? style.whiteSpace === "nowrap" : false,
        itemWidth: Math.round(itemBox.width),
      };
    });
    return { dense: nav.classList.contains("settings-nav--icon"), items };
  }, MAX_LABEL_LINES);
  const squashed = settings.items.filter(
    (item) => !item.hidden && (item.truncated || item.wrapped || !item.nowrap),
  );
  check(
    squashed.length === 0,
    squashed.length === 0
      ? `settings: all ${settings.items.length} category labels render whole (dense=${settings.dense})`
      : `settings: ${squashed.length} label(s) squashed: ${squashed
          .map((item) => `"${item.label}" ${item.labelWidth}px${item.truncated ? " truncated" : ""}${item.wrapped ? " wrapped" : ""}`)
          .join(", ")}`,
  );
  if (keepShots) await page.screenshot({ path: path.join(shotDir, "settings.png") });

  // ---- 3. $ palette does not cover the thread -------------------------
  await page.goto(`${base}?view=coach&scenario=ready`, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  await page.locator("#coach-composer").fill("$");
  await page.locator(".skill-deck").waitFor({ state: "visible" }).catch(() => {});
  await page.waitForTimeout(400);
  const palette = await page.evaluate(() => {
    const deck = document.querySelector(".skill-deck");
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

  // ---- 4. every top-level view is reachable everywhere -----------------
  const expectedTabs = ["对话", "学习", "资料", "训练", "成长"];
  for (const view of ["coach", "plan", "resources", "training", "progress", "settings"]) {
    for (const scenario of ["ready", "empty"]) {
      await page.goto(`${base}?view=${view}&scenario=${scenario}`, { waitUntil: "networkidle" });
      await page.waitForTimeout(420);
      const tabs = await page.evaluate(() =>
        [...document.querySelectorAll("header button")]
          .map((button) => button.textContent?.trim())
          .filter(Boolean),
      );
      const missing = expectedTabs.filter((tab) => !tabs.includes(tab));
      check(
        missing.length === 0,
        missing.length === 0
          ? `tabs: ${view}/${scenario} exposes all ${expectedTabs.length} destinations`
          : `tabs: ${view}/${scenario} is missing ${missing.join(", ")} (found ${tabs.join(", ") || "none"})`,
      );
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

  // ---- 7. the plan home states numbers, it does not narrate them --------
  await page.goto(`${base}?view=plan&scenario=ready`, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  const planHome = await page.evaluate(() => {
    const stats = [...document.querySelectorAll(".coach-plan-view__home-stat")];
    const stat = stats[0];
    if (!stat) return { error: "no plan stat grid" };
    const label = stat.querySelector("dt");
    const value = stat.querySelector("dd");
    const headline = document.querySelector(".coach-plan-view__home-message");
    const due = stats[0]?.querySelector("dd")?.textContent?.trim() ?? "";
    const text = headline?.textContent?.trim() ?? "";
    return {
      statCount: stats.length,
      hasLabel: Boolean(label),
      hasValue: Boolean(value),
      labelAbove: Boolean(
        label && value && label.getBoundingClientRect().top <= value.getBoundingClientRect().top,
      ),
      // The tile already states how many are due; the line beneath it must add
      // guidance rather than read the number back as prose.
      headlineRepeatsCount: /^\d/.test(due) ? new RegExp(`(^|\\D)${due}(\\D|$)`).test(text) : false,
    };
  });
  check(
    !planHome.error && planHome.hasLabel && planHome.hasValue && planHome.labelAbove,
    `plan: ${planHome.statCount} stats are label-over-value pairs, not one run-on sentence`,
  );
  check(
    !planHome.error && !planHome.headlineRepeatsCount,
    "plan: the line under the stats adds guidance instead of restating the due count",
  );

  // ---- 8. narrow sidebar keeps the same guarantees ---------------------
  await page.setViewportSize({ width: 340, height: 900 });
  await page.goto(`${base}?view=settings&scenario=ready`, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  await page.getByRole("button", { name: "编辑配置", exact: true }).click().catch(() => {});
  await page.waitForTimeout(500);
  const narrow = await page.evaluate((maxLabelLines) => {
    const nav = document.querySelector(".settings-nav");
    if (!nav) return { error: "no settings nav" };
    const squashed = [...nav.querySelectorAll(".settings-nav__label")].filter((label) => {
      const style = getComputedStyle(label);
      if (style.display === "none") return false;
      const lineHeight = parseFloat(style.lineHeight) || 14;
      const box = label.getBoundingClientRect();
      return (
        label.scrollWidth > label.clientWidth + 1 ||
        style.whiteSpace !== "nowrap" ||
        box.height > lineHeight * maxLabelLines
      );
    });
    return { squashed: squashed.length, dense: nav.classList.contains("settings-nav--icon") };
  }, MAX_LABEL_LINES);
  check(
    narrow.squashed === 0,
    `settings @340px: no squashed labels (dense=${narrow.dense}, squashed=${narrow.squashed})`,
  );
  if (keepShots) await page.screenshot({ path: path.join(shotDir, "settings-narrow.png") });

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
