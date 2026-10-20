#!/usr/bin/env node
/**
 * Real browser-capture acceptance (Chrome + MV3 extension + real sidecar).
 *
 * Exercises the shipped extension source, not a stub:
 *   discover sidecar → register a single-use pairing code → pair in the popup
 *   → capture a public page through the background worker → verify the
 *   library through the paired `/browser/status` → revoke → old credential 401.
 *
 * The capture target is https://example.com/ (a stable public documentation
 * page). The sidecar must be started with TRAINER_ENABLE_NETWORK_FETCH=1; the
 * controlled fetcher pins public addresses and refuses loopback/private hosts.
 *
 * Exit codes: 0 = green; 1 = failure. Requires `playwright` and its Chromium.
 */

import { spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const serverDir = path.join(repoRoot, "server");
const extensionDir = process.env.TRAINER_BROWSER_E2E_EXTENSION_DIR
  ? path.resolve(process.env.TRAINER_BROWSER_E2E_EXTENSION_DIR)
  : path.join(repoRoot, "extension", "browser-capture");
const python = path.join(serverDir, ".venv", "bin", "python");
const PAIR_CODE = "123456";
const CAPTURE_URL = "https://example.com/";
const PDF_URL = "https://pdfobject.com/pdf/sample.pdf";
const RETRY_PDF_URL = "https://www.orimi.com/pdf-test.pdf";
const MISSING_PDF_URL = "https://pdfobject.com/pdf/does-not-exist.pdf";
const REPO_URL = "https://github.com/octocat/Hello-World";
const DOWNLOAD_DIR = "Trainer Library/Downloads";
const REPO_DIR = "Trainer Library/Repos";
const WORKSPACE_ID = "browser-capture-e2e";
const WORKSPACE_NAME = "Browser Capture E2E";

const checks = [];
function ok(name, detail = "") {
  checks.push({ name, ok: true, detail });
  console.log(`  ok  ${name}${detail ? ` — ${detail}` : ""}`);
}
function fail(name, detail) {
  checks.push({ name, ok: false, detail });
  console.error(`  ✖  ${name}: ${detail}`);
}
function assert(condition, message) {
  if (!condition) throw new Error(message);
}
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Chrome derives an unpacked extension's ID from its real absolute path. */
function unpackedExtensionId(directory) {
  const real = fs.realpathSync(directory);
  const hash = crypto.createHash("sha256").update(real).digest("hex").slice(0, 32);
  return hash
    .split("")
    .map((digit) => String.fromCharCode(97 + Number.parseInt(digit, 16)))
    .join("");
}

function offlineEnv(extra = {}) {  const env = { ...process.env };
  for (const key of [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
  ]) {
    delete env[key];
  }
  return { ...env, ...extra };
}

function portFree(port) {
  return new Promise((resolve) => {
    const server = spawn("node", [
      "-e",
      `const net=require('net');const s=net.createServer();s.once('error',()=>process.exit(1));s.listen(${port},'127.0.0.1',()=>s.close(()=>process.exit(0)));`,
    ]);
    server.on("exit", (code) => resolve(code === 0));
    server.on("error", () => resolve(false));
  });
}

async function choosePort() {
  const candidates = [8765];
  for (let port = 34891; port <= 34911; port += 1) candidates.push(port);
  for (const port of candidates) {
    if (await portFree(port)) return port;
  }
  throw new Error("No free Trainer sidecar port (8765 or 34891–34911).");
}

async function waitForHealth(baseUrl, deadlineMs = 30000) {
  const deadline = Date.now() + deadlineMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/health`);
      if (response.ok) return await response.json();
    } catch {
      // keep polling
    }
    await sleep(250);
  }
  throw new Error(`Sidecar health did not become ready at ${baseUrl}.`);
}

async function registerPairCode(baseUrl) {
  const response = await fetch(`${baseUrl}/browser/pair-code`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      workspace_id: WORKSPACE_ID,
      workspace_name: WORKSPACE_NAME,
      code: PAIR_CODE,
    }),
  });
  if (!response.ok) {
    throw new Error(
      `Pair-code registration failed: HTTP ${response.status} ${await response.text()}`,
    );
  }
  return await response.json();
}

async function startSession(baseUrl, projectDir) {
  const response = await fetch(`${baseUrl}/session/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      workspace_id: WORKSPACE_ID,
      workspace_name: WORKSPACE_NAME,
      workspace_path: projectDir,
      workspace_trusted: true,
    }),
  });
  if (!response.ok) {
    throw new Error(
      `Session start failed: HTTP ${response.status} ${await response.text()}`,
    );
  }
  return await response.json();
}

function workspaceFilePath(projectDir, relativePath) {
  return path.join(projectDir, ...String(relativePath).split("/"));
}

function sha256File(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

async function browserStatus(baseUrl, credential) {
  const response = await fetch(`${baseUrl}/browser/status`, {
    headers: { authorization: `Bearer ${credential}` },
  });
  return { status: response.status, body: await response.json().catch(() => null) };
}

async function main() {
  if (!fs.existsSync(python)) {
    throw new Error(`Server venv python is missing: ${python}. Run npm run bootstrap.`);
  }
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-browser-e2e-data-"));
  const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-browser-e2e-profile-"));
  const projectDir = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-browser-e2e-project-"));
  const port = await choosePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  let sidecar = null;
  let context = null;
  let sidecarLog = "";
  const spawnSidecar = () => {
    sidecarLog = "";
    const proc = spawn(
      python,
      ["run_sidecar.py", "--host", "127.0.0.1", "--port", String(port)],
      {
        cwd: serverDir,
        env: offlineEnv({
          TRAINER_DATA_DIR: dataDir,
          TRAINER_ENABLE_NETWORK_FETCH: "1",
        }),
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    proc.stdout.on("data", (chunk) => {
      sidecarLog += chunk.toString();
    });
    proc.stderr.on("data", (chunk) => {
      sidecarLog += chunk.toString();
    });
    proc.on("exit", (code) => {
      if (code !== null && code !== 0) {
        console.error(`[sidecar] exited with ${code}\n${sidecarLog.slice(-4000)}`);
      }
    });
    return proc;
  };
  const stopSidecar = async () => {
    if (!sidecar || sidecar.exitCode !== null) return;
    sidecar.kill("SIGTERM");
    await sleep(1000);
    if (sidecar.exitCode === null) sidecar.kill("SIGKILL");
    await sleep(500);
  };

  try {
    sidecar = spawnSidecar();

    await waitForHealth(baseUrl);
    ok("sidecar-health", baseUrl);

    const session = await startSession(baseUrl, projectDir);
    assert(session.contextId === WORKSPACE_ID, `Unexpected session context: ${session.contextId}`);
    ok("workspace-session", projectDir);

    const registration = await registerPairCode(baseUrl);
    assert(registration.code === PAIR_CODE, "Pair-code registration did not echo the code.");
    ok("pair-code-registered", `workspace=${registration.workspace_id}`);

    context = await chromium.launchPersistentContext(profileDir, {
      headless: process.env.TRAINER_BROWSER_E2E_HEADLESS === "1",
      channel: process.env.TRAINER_BROWSER_E2E_CHANNEL || undefined,
      args: [
        `--disable-extensions-except=${extensionDir}`,
        `--load-extension=${extensionDir}`,
      ],
    });

    let extensionId = unpackedExtensionId(extensionDir);
    const popup = await context.newPage();
    try {
      await popup.goto(`chrome-extension://${extensionId}/popup/popup.html`, {
        timeout: 15000,
      });
    } catch {
      let [worker] = context.serviceWorkers();
      if (!worker) {
        worker = await context.waitForEvent("serviceworker", { timeout: 30000 });
      }
      extensionId = new URL(worker.url()).host;
      await popup.goto(`chrome-extension://${extensionId}/popup/popup.html`);
    }
    ok("extension-worker", extensionId);
    await popup.locator("#pair-panel").waitFor({ state: "visible", timeout: 30000 });
    await popup.locator("#pair-code").waitFor({ state: "visible", timeout: 30000 });

    // Detection probes the managed port range; wait until the field is usable.
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      if (await popup.locator("#pair-submit").isEnabled()) break;
      await sleep(250);
    }
    assert(await popup.locator("#pair-submit").isEnabled(), "Pair button never became enabled.");

    await popup.locator("#pair-code").fill(PAIR_CODE);
    await popup.locator("#pair-submit").click();
    await popup.locator("#capture-page").waitFor({ state: "visible", timeout: 30000 });
    ok("paired-in-popup");

    let auth = {};
    const authDeadline = Date.now() + 15000;
    while (Date.now() < authDeadline) {
      auth = await popup.evaluate(
        () =>
          new Promise((resolve) => {
            chrome.storage.local.get(
              ["trainerCapture.credential", "trainerCapture.baseUrl"],
              resolve,
            );
          }),
      );
      if (auth["trainerCapture.credential"]) break;
      await sleep(250);
    }
    assert(auth["trainerCapture.credential"], "The extension did not store a credential.");
    assert(
      String(auth["trainerCapture.baseUrl"]).includes(`:${port}`),
      `Extension paired with an unexpected base URL: ${auth["trainerCapture.baseUrl"]}`,
    );
    const credential = auth["trainerCapture.credential"];
    ok("credential-stored");

    const capture = await popup.evaluate(
      (url) =>
        new Promise((resolve) => {
          chrome.runtime.sendMessage(
            { type: "trainer:capture", url, kind: "web", title: "Example Domain" },
            resolve,
          );
        }),
      CAPTURE_URL,
    );
    assert(
      capture && (capture.status === "ok" || capture.status === "duplicated"),
      `Capture failed: ${JSON.stringify(capture)}`,
    );
    assert(
      typeof capture.deepLink === "string" &&
        capture.deepLink.startsWith("vscode://local.trainer-extension/library/"),
      `Capture returned an unexpected deepLink: ${JSON.stringify(capture.deepLink)}`,
    );
    ok("capture-indexed", capture.status);

    const status = await browserStatus(baseUrl, credential);
    assert(status.status === 200, `Paired status failed: HTTP ${status.status}`);
    assert(
      Number(status.body?.library_count) >= 1,
      `Library count did not increase: ${JSON.stringify(status.body)}`,
    );
    ok("library-status", `count=${status.body.library_count}`);

    const sendCapture = (payload) =>
      popup.evaluate(
        (body) =>
          new Promise((resolve) => {
            chrome.runtime.sendMessage(
              { type: "trainer:capture", ...body },
              resolve,
            );
          }),
        payload,
      );

    const captureLane = async (url, kind, title) => {
      const result = await sendCapture({ url, kind, title });
      assert(
        result && (result.status === "ok" || result.status === "duplicated"),
        `${kind} capture failed: ${JSON.stringify(result)}`,
      );
      return result;
    };
    await captureLane(
      "https://github.com/AI-yyf/trainer",
      "github_repo",
      "AI-yyf/trainer",
    );
    ok("github-readme-captured");
    await captureLane(
      "https://pdfobject.com/pdf/sample.pdf",
      "pdf",
      "Sample PDF",
    );
    ok("pdf-captured");
    const multiStatus = await browserStatus(baseUrl, credential);
    assert(
      Number(multiStatus.body?.library_count) >= 3,
      `Multi-kind captures are missing: ${JSON.stringify(multiStatus.body)}`,
    );
    ok("multi-kind-library-status", `count=${multiStatus.body.library_count}`);

    // --- Download-to-project lane -----------------------------------------
    const pdfDownload = await sendCapture({
      url: PDF_URL,
      kind: "pdf",
      title: "Sample PDF",
      download: true,
      targetDir: DOWNLOAD_DIR,
    });
    assert(
      pdfDownload &&
        (pdfDownload.status === "ok" || pdfDownload.status === "duplicated"),
      `PDF download failed: ${JSON.stringify(pdfDownload)}`,
    );
    assert(
      typeof pdfDownload.savedPath === "string" &&
        pdfDownload.savedPath.startsWith(`${DOWNLOAD_DIR}/`),
      `PDF saved outside the requested folder: ${JSON.stringify(pdfDownload.savedPath)}`,
    );
    const pdfPath = workspaceFilePath(projectDir, pdfDownload.savedPath);
    assert(fs.existsSync(pdfPath) && fs.statSync(pdfPath).isFile(), `PDF is missing: ${pdfPath}`);
    assert(
      fs.readFileSync(pdfPath).subarray(0, 4).toString("latin1") === "%PDF",
      "Downloaded PDF does not start with %PDF",
    );
    const pdfHash = sha256File(pdfPath);
    ok("pdf-downloaded", pdfDownload.savedPath);

    const pdfAgain = await sendCapture({
      url: PDF_URL,
      kind: "pdf",
      title: "Sample PDF",
      download: true,
      targetDir: DOWNLOAD_DIR,
    });
    assert(
      pdfAgain &&
        (pdfAgain.status === "ok" ||
          pdfAgain.status === "duplicated" ||
          pdfAgain.status === "duplicate-local"),
      `PDF re-download failed: ${JSON.stringify(pdfAgain)}`,
    );
    assert(
      String(pdfAgain.message || "").includes(pdfDownload.savedPath),
      `PDF re-download did not report the existing path: ${JSON.stringify(pdfAgain.message)}`,
    );
    const pdfFiles = fs
      .readdirSync(path.dirname(pdfPath))
      .filter((name) => name.toLowerCase().endsWith(".pdf"));
    assert(pdfFiles.length === 1, `PDF overwrite created duplicates: ${pdfFiles.join(", ")}`);
    assert(sha256File(pdfPath) === pdfHash, "PDF re-download overwrote existing bytes");
    ok("pdf-not-overwritten", `${pdfFiles[0]}`);

    const repo = await sendCapture({
      url: REPO_URL,
      kind: "github_repo",
      title: "octocat/Hello-World",
      download: true,
      targetDir: REPO_DIR,
    });
    assert(
      repo && (repo.status === "ok" || repo.status === "duplicated"),
      `GitHub repo download failed: ${JSON.stringify(repo)}`,
    );
    assert(
      typeof repo.savedPath === "string" && repo.savedPath.startsWith(`${REPO_DIR}/`),
      `Repo saved outside the requested folder: ${JSON.stringify(repo.savedPath)}`,
    );
    const repoPath = workspaceFilePath(projectDir, repo.savedPath);
    assert(fs.existsSync(repoPath) && fs.statSync(repoPath).isDirectory(), "Repo folder is missing");
    const readme = fs.readdirSync(repoPath).find((name) => /^readme/i.test(name));
    assert(Boolean(readme), `Repo folder has no README: ${fs.readdirSync(repoPath).join(", ")}`);
    ok("github-repo-downloaded", repo.savedPath);

    const repoAgain = await sendCapture({
      url: REPO_URL,
      kind: "github_repo",
      title: "octocat/Hello-World",
      download: true,
      targetDir: REPO_DIR,
    });
    assert(
      repoAgain &&
        (repoAgain.status === "duplicated" ||
          repoAgain.status === "duplicate-local" ||
          repoAgain.status === "ok"),
      `Repo re-download failed: ${JSON.stringify(repoAgain)}`,
    );
    assert(
      String(repoAgain.message || "").includes(repo.savedPath),
      `Repo re-download did not report the existing folder: ${JSON.stringify(repoAgain.message)}`,
    );
    assert(fs.existsSync(path.join(repoPath, readme)), "Repo re-download damaged the first folder");
    ok("github-repo-not-overwritten", repo.savedPath);

    const missing = await sendCapture({
      url: MISSING_PDF_URL,
      kind: "pdf",
      title: "Missing PDF",
      download: true,
      targetDir: DOWNLOAD_DIR,
    });
    assert(
      missing && missing.status === "failed",
      `404 download was not a non-retryable failure: ${JSON.stringify(missing)}`,
    );
    assert(
      !fs.existsSync(path.join(projectDir, DOWNLOAD_DIR, "Missing PDF.pdf")),
      "404 download left a file behind",
    );
    ok("download-404-not-retried");

    const traversal = await fetch(`${baseUrl}/resources/capture`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${credential}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        url: `${PDF_URL}?trav=1`,
        kind: "pdf",
        title: "Traversal",
        download: true,
        target_dir: "../outside",
      }),
    });
    assert(traversal.status === 422, `Traversal target_dir was not refused: HTTP ${traversal.status}`);
    assert(
      !fs.existsSync(path.join(projectDir, "..", "outside")),
      "Traversal wrote outside the workspace",
    );
    ok("download-path-traversal-refused");

    // Offline queue: with the sidecar down the extension must persist the
    // capture, and a later flush must deliver it to the same library.
    await stopSidecar();
    ok("sidecar-stopped-for-offline");
    const queued = await popup.evaluate(
      (url) =>
        new Promise((resolve) => {
          chrome.runtime.sendMessage(
            { type: "trainer:capture", url, kind: "web", title: "Example Domain Offline" },
            resolve,
          );
        }),
      `${CAPTURE_URL}?offline=1`,
    );
    assert(
      queued && queued.status === "queued",
      `Offline capture was not queued: ${JSON.stringify(queued)}`,
    );
    const queuedPdf = await sendCapture({
      url: RETRY_PDF_URL,
      kind: "pdf",
      title: "Retry PDF",
      download: true,
      targetDir: DOWNLOAD_DIR,
    });
    assert(
      queuedPdf && queuedPdf.status === "queued",
      `Offline PDF download was not queued: ${JSON.stringify(queuedPdf)}`,
    );
    ok("offline-queued", "web + pdf download");

    sidecar = spawnSidecar();
    await waitForHealth(baseUrl);
    // A restarted sidecar must re-register the host workspace before a queued
    // download can resolve its target folder.
    await startSession(baseUrl, projectDir);
    const flush = await popup.evaluate(
      () =>
        new Promise((resolve) => {
          chrome.runtime.sendMessage({ type: "trainer:flush" }, resolve);
        }),
    );
    assert(
      flush && flush.ok === true && Number(flush.flushed) >= 2 && Number(flush.remaining) === 0,
      `Offline flush did not drain the queue: ${JSON.stringify(flush)}`,
    );
    ok("offline-flushed", `flushed=${flush.flushed}`);
    const retryPdfPath = path.join(projectDir, DOWNLOAD_DIR, "Retry PDF.pdf");
    assert(
      fs.existsSync(retryPdfPath) && fs.statSync(retryPdfPath).isFile(),
      `Queued PDF download did not land: ${retryPdfPath}`,
    );
    ok("offline-pdf-retried", "Retry PDF.pdf");
    const flushedStatus = await browserStatus(baseUrl, credential);
    assert(
      flushedStatus.status === 200 && Number(flushedStatus.body?.library_count) >= 5,
      `Flushed capture is missing from the library: ${JSON.stringify(flushedStatus.body)}`,
    );
    ok("offline-library-status", `count=${flushedStatus.body.library_count}`);

    const revoke = await popup.evaluate(
      () =>
        new Promise((resolve) => {
          chrome.runtime.sendMessage({ type: "trainer:revoke" }, resolve);
        }),
    );
    assert(revoke && revoke.ok !== false, `Revoke failed: ${JSON.stringify(revoke)}`);

    const revokedStatus = await browserStatus(baseUrl, credential);
    assert(revokedStatus.status === 401, `Revoked credential still works: HTTP ${revokedStatus.status}`);
    ok("revoked-credential-rejected");
  } finally {
    if (context) {
      await context.close().catch(() => {});
    }
    if (sidecar && sidecar.exitCode === null) {
      sidecar.kill("SIGTERM");
      await sleep(1000);
      if (sidecar.exitCode === null) sidecar.kill("SIGKILL");
    }
    fs.rmSync(dataDir, { recursive: true, force: true });
    fs.rmSync(profileDir, { recursive: true, force: true });
    fs.rmSync(projectDir, { recursive: true, force: true });
  }

  const failed = checks.filter((check) => !check.ok);
  const report = {
    ok: failed.length === 0,
    browser: process.env.TRAINER_BROWSER_E2E_CHANNEL || "playwright-chromium",
    extensionDir,
    target: CAPTURE_URL,
    checks,
    generatedAt: new Date().toISOString(),
  };
  const reportPath = String(process.env.TRAINER_BROWSER_E2E_REPORT || "").trim();
  if (reportPath) {
    fs.writeFileSync(path.resolve(reportPath), `${JSON.stringify(report, null, 1)}\n`, "utf8");
  }
  console.log(
    `\n[${failed.length === 0 ? "PASS" : "FAIL"}] ${checks.length - failed.length}/${checks.length} browser-capture checks`,
  );
  if (failed.length > 0) {
    for (const check of failed) console.error(`  - ${check.name}: ${check.detail}`);
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(`[browser-capture-e2e] ${error instanceof Error ? error.stack : String(error)}`);
  process.exitCode = 1;
});
