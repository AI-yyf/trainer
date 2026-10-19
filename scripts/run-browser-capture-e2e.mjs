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

function offlineEnv(extra = {}) {
  const env = { ...process.env };
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

    const registration = await registerPairCode(baseUrl);
    assert(registration.code === PAIR_CODE, "Pair-code registration did not echo the code.");
    ok("pair-code-registered", `workspace=${registration.workspace_id}`);

    context = await chromium.launchPersistentContext(profileDir, {
      headless: process.env.TRAINER_BROWSER_E2E_HEADLESS === "1",
      args: [
        `--disable-extensions-except=${extensionDir}`,
        `--load-extension=${extensionDir}`,
      ],
    });

    let [worker] = context.serviceWorkers();
    if (!worker) {
      worker = await context.waitForEvent("serviceworker", { timeout: 30000 });
    }
    const extensionId = new URL(worker.url()).host;
    ok("extension-worker", extensionId);

    const popup = await context.newPage();
    await popup.goto(`chrome-extension://${extensionId}/popup/popup.html`);
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
    ok("offline-queued");

    sidecar = spawnSidecar();
    await waitForHealth(baseUrl);
    const flush = await popup.evaluate(
      () =>
        new Promise((resolve) => {
          chrome.runtime.sendMessage({ type: "trainer:flush" }, resolve);
        }),
    );
    assert(
      flush && flush.ok === true && Number(flush.remaining) === 0,
      `Offline flush did not drain the queue: ${JSON.stringify(flush)}`,
    );
    ok("offline-flushed", `flushed=${flush.flushed}`);
    const flushedStatus = await browserStatus(baseUrl, credential);
    assert(
      flushedStatus.status === 200 && Number(flushedStatus.body?.library_count) >= 2,
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
  }

  const failed = checks.filter((check) => !check.ok);
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
