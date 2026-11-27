#!/usr/bin/env node
/**
 * Sync the compiled `extension/webview` sidebar bundle (`dist/sidepanel.html` +
 * `dist/assets/*`) directly into `browser-extension/sidepanel/`, so the Browser
 * Extension MV3 Side Panel runs the exact same React Workbench as VS Code with
 * zero duplicated sidepanel UI code and zero inline scripts.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const defaultRepoRoot = path.resolve(__dirname, "..");

export function syncBrowserSidepanelBundle({ repoRoot = defaultRepoRoot } = {}) {
  const webviewDistDir = path.join(repoRoot, "extension", "webview", "dist");
  const builtHtmlPath = path.join(webviewDistDir, "sidepanel.html");
  const builtAssetsDir = path.join(webviewDistDir, "assets");
  const targetSidepanelDir = path.join(repoRoot, "browser-extension", "sidepanel");

  if (!fs.existsSync(builtHtmlPath) || !fs.existsSync(builtAssetsDir)) {
    throw new Error(
      `Compiled webview sidepanel bundle not found at ${webviewDistDir}. Run "npm run build --prefix extension/webview" first.`,
    );
  }

  // Clean out legacy handwritten sidepanel files and any stale hashed chunks.
  fs.rmSync(targetSidepanelDir, { recursive: true, force: true });
  fs.mkdirSync(path.join(targetSidepanelDir, "assets"), { recursive: true });

  // Vite emits `./assets/...` relative to `dist/`; since `sidepanel.html` lives
  // inside `browser-extension/sidepanel/`, `./assets/...` resolves cleanly to
  // `browser-extension/sidepanel/assets/...`.
  const html = fs.readFileSync(builtHtmlPath, "utf8");
  fs.writeFileSync(path.join(targetSidepanelDir, "sidepanel.html"), html, "utf8");

  // Copy only runtime chunks needed by the shared workbench (exclude preview
  // mock sidecar chunks that are never loaded by `sidepanel-main.tsx`).
  const assetEntries = fs
    .readdirSync(builtAssetsDir)
    .filter(
      (name) =>
        !name.startsWith("browserPreview") &&
        !name.startsWith("browserSidecar") &&
        !name.startsWith("preview-") &&
        !name.startsWith("main-"),
    )
    .sort();

  for (const name of assetEntries) {
    const src = path.join(builtAssetsDir, name);
    if (fs.statSync(src).isFile()) {
      fs.copyFileSync(src, path.join(targetSidepanelDir, "assets", name));
    }
  }

  return {
    targetSidepanelDir,
    copiedAssets: assetEntries.length,
  };
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  const summary = syncBrowserSidepanelBundle();
  console.log(
    `Synced shared webview sidebar into browser-extension/sidepanel (${summary.copiedAssets} runtime assets).`,
  );
}
