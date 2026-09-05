import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { resolveNpmExecPath } from "./package-vsix.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export function buildWebviewPackage({
  extensionDir = path.resolve(__dirname, ".."),
  env = process.env,
  runBuild,
} = {}) {
  const webviewDir = path.join(extensionDir, "webview");
  const distDir = path.join(webviewDir, "dist");
  const stagingDir = fs.mkdtempSync(path.join(webviewDir, ".dist-staging-"));
  const buildEnv = {
    ...env,
    TRAINER_WEBVIEW_OUT_DIR: stagingDir,
    TRAINER_WEBVIEW_INCLUDE_TEST_ENTRY: "0",
  };

  try {
    (runBuild ?? defaultBuild)(webviewDir, buildEnv);
    removeTestOnlyEntries(stagingDir);
    assertBuildEntries(stagingDir);
    replaceDistAtomically({ distDir, stagingDir });
    return { distDir, stagingDir, entries: ["index.html", "vscode-preview.html"] };
  } catch (error) {
    fs.rmSync(stagingDir, { recursive: true, force: true });
    throw error;
  }
}

function defaultBuild(webviewDir, env) {
  const result = spawnSync(process.execPath, [resolveNpmExecPath(), "run", "build:preview"], {
    cwd: webviewDir,
    env,
    encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new Error(
      [
        "Deterministic webview package build failed.",
        result.error ? `${result.error.name}: ${result.error.message}` : "",
        (result.stdout ?? "").trim(),
        (result.stderr ?? "").trim(),
      ].filter(Boolean).join("\n"),
    );
  }
}

function removeTestOnlyEntries(stagingDir) {
  fs.rmSync(path.join(stagingDir, "browserSidecar-test.js"), { force: true });
}

function assertBuildEntries(stagingDir) {
  for (const entry of ["index.html", "vscode-preview.html"]) {
    const entryPath = path.join(stagingDir, entry);
    if (!fs.existsSync(entryPath)) {
      throw new Error(`Deterministic webview build did not produce ${entry}.`);
    }
  }
}

function replaceDistAtomically({ distDir, stagingDir }) {
  const backupDir = `${distDir}.previous-${process.pid}-${Date.now()}`;
  let movedExisting = false;
  try {
    if (fs.existsSync(distDir)) {
      renameWithRetry(distDir, backupDir);
      movedExisting = true;
    }
    renameWithRetry(stagingDir, distDir);
  } catch (error) {
    if (movedExisting && fs.existsSync(backupDir) && !fs.existsSync(distDir)) {
      renameWithRetry(backupDir, distDir);
    }
    if (error?.code === "EPERM" || error?.code === "EACCES") {
      replaceDistByCopy({ distDir, stagingDir });
      return;
    }
    throw error;
  }
  if (movedExisting) {
    fs.rmSync(backupDir, { recursive: true, force: true });
  }
}

function replaceDistByCopy({ distDir, stagingDir }) {
  fs.mkdirSync(distDir, { recursive: true });
  const stagingEntries = new Set(fs.readdirSync(stagingDir));
  for (const entry of fs.readdirSync(distDir)) {
    if (!stagingEntries.has(entry)) {
      fs.rmSync(path.join(distDir, entry), { recursive: true, force: true });
    }
  }
  for (const entry of stagingEntries) {
    const source = path.join(stagingDir, entry);
    const destination = path.join(distDir, entry);
    fs.rmSync(destination, { recursive: true, force: true });
    fs.cpSync(source, destination, { recursive: true, force: true });
  }
  fs.rmSync(stagingDir, { recursive: true, force: true });
}

function renameWithRetry(source, destination) {
  let lastError;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      fs.renameSync(source, destination);
      return;
    } catch (error) {
      lastError = error;
      if (error?.code !== "EPERM" && error?.code !== "EACCES") {
        throw error;
      }
      const waitUntil = Date.now() + 250 * (attempt + 1);
      while (Date.now() < waitUntil) {
        // Allow Windows antivirus/indexer handles to release the directory.
      }
    }
  }
  throw lastError;
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  try {
    const result = buildWebviewPackage();
    console.log(`Deterministic webview package build passed: ${result.entries.join(", ")}.`);
  } catch (error) {
    console.error(`Deterministic webview package build failed.\n${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}
