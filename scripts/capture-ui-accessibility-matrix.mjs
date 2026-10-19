#!/usr/bin/env node
/**
 * UI accessibility / locale matrix for the six shipped surfaces.
 *
 * For every supported language × view it captures:
 *   - normal light at 420×900
 *   - 200% font (--trainer-font-ui: 26px) dark at 420×900
 * and asserts the page itself never scrolls horizontally, that no visible
 * non-scrollable element overflows the viewport, and that no placeholder text
 * (`undefined`, `[object Object]`, U+FFFD) leaks into the UI.
 *
 * Output: output/ui-a11y/<mode>/<lang>/<view>.png plus a 3×2 contact sheet per
 * language/mode. report.json carries the per-page verdicts. This is screenshot
 * evidence for human review, not a substitute for it.
 *
 * Usage:
 *   node scripts/capture-ui-accessibility-matrix.mjs
 *   TRAINER_A11Y_PORT=4180 TRAINER_A11Y_URL=http://127.0.0.1:4180 node scripts/...
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
const outputDir = path.join(repoRoot, "output", "ui-a11y");
const PREVIEW_PATH = "/vscode-preview.html";
const VIEWS = ["coach", "plan", "resources", "training", "progress", "settings"];
const LANGUAGES = ["zh-CN", "en-US", "es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR", "pt-BR"];
const VIEWPORT = { width: 420, height: 900 };

function fail(message) {
  throw new Error(message);
}

function previewPort() {
  const raw = String(process.env.TRAINER_A11Y_PORT ?? "4180").trim();
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    fail("TRAINER_A11Y_PORT must be a valid local TCP port.");
  }
  return port;
}

function viteBin(name) {
  return path.join(
    webviewRoot,
    "node_modules",
    name,
    "bin",
    name === "vite" ? "vite.js" : "tsc",
  );
}

function buildPreviewBundle() {
  console.log("[ui-a11y] building the preview bundle…");
  for (const [label, args] of [
    ["tsc -b", [viteBin("typescript"), "-b"]],
    ["vite build --mode preview", [viteBin("vite"), "build", "--mode", "preview"]],
  ]) {
    const result = spawnSync(process.execPath, args, {
      cwd: webviewRoot,
      env: process.env,
      stdio: "inherit",
    });
    if (result.error) fail(`${label} could not start: ${result.error.message}`);
    if (result.status !== 0) fail(`${label} exited with status ${result.status}.`);
  }
}

function startPreviewServer(port) {
  const child = spawn(
    process.execPath,
    [viteBin("vite"), "preview", "--host", "127.0.0.1", "--port", String(port), "--strictPort"],
    { cwd: webviewRoot, env: process.env, stdio: ["ignore", "pipe", "pipe"] },
  );
  let output = "";
  child.stdout.on("data", (chunk) => {
    output += chunk.toString();
  });
  child.stderr.on("data", (chunk) => {
    output += chunk.toString();
  });
  child.on("exit", (code) => {
    if (code !== null && code !== 0 && code !== 143) {
      console.error(`[ui-a11y] preview server exited (${code}):\n${output.slice(-2000)}`);
    }
  });
  return child;
}

async function waitForServer(baseUrl, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}${PREVIEW_PATH}`, { method: "GET" });
      if (response.ok) return;
    } catch {
      // keep polling
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  fail(`Preview server at ${baseUrl} never became ready.`);
}

async function inspectPage(page) {
  return page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const skipped = new Set(["PRE", "CODE", "TEXTAREA", "INPUT", "SELECT", "SCRIPT", "STYLE", "SVG"]);
    const overflow = [];
    for (const element of document.querySelectorAll("body *")) {
      if (skipped.has(element.tagName)) continue;
      const style = getComputedStyle(element);
      if (style.display === "none" || style.visibility === "hidden") continue;
      if (style.overflowX === "auto" || style.overflowX === "scroll") continue;
      const rect = element.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) continue;
      if (rect.right > viewportWidth + 1 || rect.left < -1) {
        overflow.push({
          tag: element.tagName.toLowerCase(),
          className: String(element.className || "").slice(0, 120),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
        });
        if (overflow.length >= 8) break;
      }
    }
    const clone = document.body.cloneNode(true);
    clone.querySelectorAll("pre, code, script, style, textarea").forEach((node) => node.remove());
    const text = String(clone.innerText || "");
    const markers = [];
    for (const marker of ["undefined", "[object Object]", "\uFFFD", "NaN"]) {
      if (text.includes(marker)) markers.push(marker);
    }
    // Specific regression: the Progress row's count must never start inside
    // the label at 200% font or long translations.
    const progressRowOverlaps = [];
    for (const toggle of document.querySelectorAll(".progress-view__row-toggle")) {
      const main = toggle.querySelector(".progress-view__row-main");
      const evidence = toggle.querySelector(".progress-view__evidence");
      if (!main || !evidence) continue;
      const a = main.getBoundingClientRect();
      const b = evidence.getBoundingClientRect();
      const horizontal = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const vertical = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (horizontal > 1 && vertical > 1) {
        progressRowOverlaps.push({
          label: String(main.textContent || "").slice(0, 60),
          count: String(evidence.textContent || "").slice(0, 60),
        });
      }
    }
    return {
      viewportWidth,
      documentOverflow: document.documentElement.scrollWidth > viewportWidth + 1,
      overflowingElements: overflow,
      progressRowOverlaps,
      textMarkers: markers,
      textLength: text.length,
    };
  });
}

async function main() {
  const port = previewPort();
  const baseUrl = String(process.env.TRAINER_A11Y_URL || `http://127.0.0.1:${port}`).replace(/\/+$/, "");
  const manageServer = !process.env.TRAINER_A11Y_URL;
  let server = null;
  let browser = null;
  const pages = [];

  fs.rmSync(outputDir, { recursive: true, force: true });
  fs.mkdirSync(outputDir, { recursive: true });

  try {
    if (manageServer) {
      buildPreviewBundle();
      server = startPreviewServer(port);
      await waitForServer(baseUrl);
    }
    browser = await chromium.launch();
    const context = await browser.newContext({
      viewport: VIEWPORT,
      deviceScaleFactor: 1,
      reducedMotion: "reduce",
    });
    const page = await context.newPage();

    for (const mode of [
      { id: "normal-light", theme: "light", fontScale: false },
      { id: "font200-dark", theme: "dark", fontScale: true },
    ]) {
      for (const language of LANGUAGES) {
        for (const view of VIEWS) {
          const params = new URLSearchParams({
            view,
            lang: language,
            theme: mode.theme,
            scenario: "ready",
          });
          await page.goto(`${baseUrl}${PREVIEW_PATH}?${params.toString()}`, {
            waitUntil: "networkidle",
            timeout: 30_000,
          });
          if (mode.fontScale) {
            await page.addStyleTag({
              content: ":root{--trainer-font-ui:26px !important;}",
            });
          }
          await page.waitForTimeout(450);
          const inspection = await inspectPage(page);
          const dir = path.join(outputDir, mode.id, language);
          fs.mkdirSync(dir, { recursive: true });
          const shotPath = path.join(dir, `${view}.png`);
          await page.screenshot({ path: shotPath, fullPage: false });
          const ok =
            !inspection.documentOverflow &&
            inspection.overflowingElements.length === 0 &&
            inspection.progressRowOverlaps.length === 0 &&
            inspection.textMarkers.length === 0;
          const entry = {
            mode: mode.id,
            language,
            view,
            ok,
            screenshot: path.relative(repoRoot, shotPath),
            ...inspection,
          };
          pages.push(entry);
          console.log(
            `${ok ? "PASS" : "FAIL"} ${mode.id}/${language}/${view} ` +
              `docOverflow=${inspection.documentOverflow} ` +
              `elements=${inspection.overflowingElements.length} ` +
              `progressOverlaps=${inspection.progressRowOverlaps.length} ` +
              `markers=${inspection.textMarkers.join(",") || "-"}`,
          );
        }
      }
    }

    // 3×2 contact sheets (one per mode/language) for human review.
    for (const mode of ["normal-light", "font200-dark"]) {
      for (const language of LANGUAGES) {
        const dir = path.join(outputDir, mode, language);
        const files = VIEWS.map((view) => path.join(dir, `${view}.png`));
        const contact = path.join(dir, "contact.png");
        const montage = spawnSync(
          "montage",
          [
            ...files,
            "-font",
            process.platform === "darwin"
              ? "/System/Library/Fonts/Supplemental/Arial.ttf"
              : "DejaVu-Sans",
            "-tile",
            "3x2",
            "-geometry",
            "+4+4",
            "-background",
            "#111",
            contact,
          ],
          { encoding: "utf8" },
        );
        if (montage.status !== 0) {
          console.warn(`[ui-a11y] montage failed for ${mode}/${language}: ${montage.stderr}`);
        }
      }
    }
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server && server.exitCode === null) {
      server.kill("SIGTERM");
      await new Promise((resolve) => setTimeout(resolve, 500));
      if (server.exitCode === null) server.kill("SIGKILL");
    }
  }

  const failures = pages.filter((entry) => !entry.ok);
  const report = {
    generatedAt: new Date().toISOString(),
    viewport: VIEWPORT,
    languages: LANGUAGES,
    views: VIEWS,
    modes: ["normal-light", "font200-dark"],
    pages: pages.length,
    passed: pages.length - failures.length,
    failed: failures.length,
    failures,
  };
  fs.writeFileSync(
    path.join(outputDir, "report.json"),
    `${JSON.stringify(report, null, 1)}\n`,
    "utf8",
  );
  console.log(`\n[ui-a11y] ${report.passed}/${report.pages} pages pass; report=${path.relative(repoRoot, path.join(outputDir, "report.json"))}`);
  if (failures.length > 0) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(`[ui-a11y] ${error instanceof Error ? error.stack : String(error)}`);
  process.exitCode = 1;
});
