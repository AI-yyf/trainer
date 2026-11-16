#!/usr/bin/env node
/**
 * Two-window browser focus acceptance.
 *
 * Starts two real sidecars with distinct workspaces, focuses B then A, and
 * proves auto-pair follows the focused window instead of the lowest port.
 * Requires playwright + Chromium and the server venv. Local-only evidence;
 * not part of the cross-platform CI matrix.
 */

import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import { once } from 'node:events';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const serverDir = path.join(repoRoot, 'server');
const python = path.join(serverDir, '.venv', 'bin', 'python');
const extensionDir = path.join(repoRoot, 'browser-extension');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function portFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.listen(port, '127.0.0.1', () => server.close(() => resolve(true)));
  });
}

async function pickPorts() {
  const ports = [];
  for (let port = 34891; port <= 34911 && ports.length < 2; port += 1) {
    if (await portFree(port)) ports.push(port);
  }
  if (ports.length < 2) throw new Error('Two free Trainer sidecar ports are required.');
  return ports;
}

function extensionId(directory) {
  return crypto
    .createHash('sha256')
    .update(fs.realpathSync(directory))
    .digest('hex')
    .slice(0, 32)
    .split('')
    .map((digit) => String.fromCharCode(97 + Number.parseInt(digit, 16)))
    .join('');
}

async function waitHealth(port, token) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/health`, {
        headers: { 'x-trainer-token': token },
      });
      if (response.ok) return;
    } catch {
      // keep polling
    }
    await sleep(200);
  }
  throw new Error(`Sidecar health timed out on ${port}.`);
}

async function startSidecar(port, dataDir, token) {
  const proc = spawn(
    python,
    ['run_sidecar.py', '--host', '127.0.0.1', '--port', String(port)],
    {
      cwd: serverDir,
      env: {
        ...process.env,
        TRAINER_DATA_DIR: dataDir,
        TRAINER_SIDECAR_TOKEN: token,
        TRAINER_ENABLE_NETWORK_FETCH: '1',
      },
      stdio: 'ignore',
    },
  );
  await waitHealth(port, token);
  return proc;
}

async function post(port, token, pathName, body) {
  const response = await fetch(`http://127.0.0.1:${port}${pathName}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-trainer-token': token },
    body: JSON.stringify(body || {}),
  });
  if (!response.ok) {
    throw new Error(`${pathName} failed: HTTP ${response.status} ${await response.text()}`);
  }
  return response.json();
}

async function main() {
  if (!fs.existsSync(python)) throw new Error(`Missing server venv: ${python}`);
  const [portA, portB] = await pickPorts();
  const tokenA = crypto.randomBytes(12).toString('hex');
  const tokenB = crypto.randomBytes(12).toString('hex');
  const dataA = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-focus-a-'));
  const dataB = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-focus-b-'));
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-focus-profile-'));
  let sidecarA;
  let sidecarB;
  let context;

  try {
    sidecarA = await startSidecar(portA, dataA, tokenA);
    sidecarB = await startSidecar(portB, dataB, tokenB);
    await post(portA, tokenA, '/session/start', {
      workspace_id: 'workspace-a',
      workspace_name: 'Workspace A',
    });
    await post(portB, tokenB, '/session/start', {
      workspace_id: 'workspace-b',
      workspace_name: 'Workspace B',
    });
    await post(portA, tokenA, '/browser/host-focus', { workspace_id: 'workspace-a' });
    await sleep(60);
    await post(portB, tokenB, '/browser/host-focus', { workspace_id: 'workspace-b' });

    const headless = process.env.TRAINER_BROWSER_E2E_HEADLESS === '1';
    context = await chromium.launchPersistentContext(profile, {
      headless,
      channel: process.env.TRAINER_BROWSER_E2E_CHANNEL || (headless ? 'chromium' : undefined),
      args: [
        `--disable-extensions-except=${extensionDir}`,
        `--load-extension=${extensionDir}`,
      ],
    });
    const page = await context.newPage();
    let id = extensionId(extensionDir);
    try {
      await page.goto(`chrome-extension://${id}/popup/popup.html`, { timeout: 15000 });
    } catch {
      let [worker] = context.serviceWorkers();
      if (!worker) worker = await context.waitForEvent('serviceworker', { timeout: 30000 });
      id = new URL(worker.url()).host;
      await page.goto(`chrome-extension://${id}/popup/popup.html`);
    }
    await page.locator('#capture-page').waitFor({ state: 'visible', timeout: 30000 });
    const readAuth = () =>
      page.evaluate(
        () =>
          new Promise((resolve) => {
            chrome.storage.local.get(
              ['trainerCapture.baseUrl', 'trainerCapture.workspaceId'],
              resolve,
            );
          }),
      );
    for (let attempt = 0; attempt < 50; attempt += 1) {
      const auth = await readAuth();
      if (auth['trainerCapture.baseUrl']) break;
      await sleep(200);
    }
    const first = await readAuth();
    if (
      first['trainerCapture.workspaceId'] !== 'workspace-b' ||
      !String(first['trainerCapture.baseUrl']).endsWith(`:${portB}`)
    ) {
      throw new Error(`Auto-pair did not follow focus B: ${JSON.stringify(first)}`);
    }

    // A normal user capture must leave a dead stored sidecar and land in the
    // live focused window; no manual revoke/clear is involved.
    await post(portA, tokenA, '/browser/host-focus', { workspace_id: 'workspace-a' });
    sidecarB.kill('SIGKILL');
    await sleep(400);
    const capture = await page.evaluate(
      () =>
        new Promise((resolve) => {
          chrome.runtime.sendMessage(
            {
              type: 'trainer:capture',
              url: 'https://example.com/?focus-switch=1',
              kind: 'web',
              title: 'Focus switch capture',
            },
            resolve,
          );
        }),
    );
    if (!capture || !['ok', 'duplicated', 'queued'].includes(capture.status)) {
      throw new Error(`Focus-switch capture did not run: ${JSON.stringify(capture)}`);
    }
    const second = await readAuth();
    if (
      second['trainerCapture.workspaceId'] !== 'workspace-a' ||
      !String(second['trainerCapture.baseUrl']).endsWith(`:${portA}`)
    ) {
      throw new Error(`Auto-pair did not follow focus A: ${JSON.stringify(second)}`);
    }
    console.log(
      `[PASS] focus ranking: B -> ${portB}/workspace-b, A -> ${portA}/workspace-a`,
    );
    sidecarB = await startSidecar(portB, dataB, tokenB);
    await post(portB, tokenB, '/session/start', { workspace_id: 'workspace-b', workspace_name: 'Workspace B' });
    const exited = once(sidecarA, 'exit');
    sidecarA.kill('SIGTERM');
    await exited;

    const sourceUrl = 'https://trainer-context.example.org/selection';
    const article = await context.newPage();
    const selection = 'A queued source belongs to the workspace where it was captured.';
    await article.route(sourceUrl, (route) => route.fulfill({
      contentType: 'text/html', body: `<title>Workspace scope</title><p>${selection}</p>`,
    }));
    await article.goto(sourceUrl);
    await article.locator('p').evaluate((element) => {
      const range = document.createRange();
      range.selectNodeContents(element);
      getSelection().removeAllRanges();
      getSelection().addRange(range);
    });
    await article.bringToFront();
    const send = (type) => page.evaluate((message) => chrome.runtime.sendMessage({ type: message }), type);
    const queued = await send('trainer:send-tab-context');
    const browserState = await send('trainer:state');
    const queuedDraft = browserState.drafts?.find((draft) => draft.selection === selection);
    if (queued.status !== 'queued' || queuedDraft?.workspaceId !== 'workspace-a') {
      throw new Error('The offline selection was not queued for workspace A.');
    }
    const pendingDrafts = async (port, token, workspaceId) => {
      const response = await fetch(`http://127.0.0.1:${port}/browser/pending-drafts?workspace_id=${workspaceId}`, {
        headers: { 'x-trainer-token': token },
      });
      if (!response.ok) throw new Error(`Could not read pending drafts for ${workspaceId}.`);
      return (await response.json()).drafts;
    };
    await post(portB, tokenB, '/browser/host-focus', { workspace_id: 'workspace-b' });
    await send('trainer:auto-pair');
    await send('trainer:flush');
    if ((await pendingDrafts(portB, tokenB, 'workspace-b')).length !== 0) {
      throw new Error('Workspace B received the browser selection queued for A.');
    }
    sidecarA = await startSidecar(portA, dataA, tokenA);
    await post(portA, tokenA, '/session/start', { workspace_id: 'workspace-a', workspace_name: 'Workspace A' });
    await post(portA, tokenA, '/browser/host-focus', { workspace_id: 'workspace-a' });
    await send('trainer:auto-pair');
    await send('trainer:flush');
    const delivered = await pendingDrafts(portA, tokenA, 'workspace-a');
    if (delivered.length !== 1 || delivered[0].selection !== selection || delivered[0].url !== sourceUrl) {
      throw new Error('The queued selection did not return to workspace A exactly once.');
    }
    console.log('[PASS] offline draft stayed in workspace A across a focus switch and restart');
  } finally {
    if (context) await context.close().catch(() => {});
    for (const proc of [sidecarA, sidecarB]) {
      if (proc && proc.exitCode === null) proc.kill('SIGKILL');
    }
    for (const directory of [dataA, dataB, profile]) {
      fs.rmSync(directory, { recursive: true, force: true });
    }
  }
}

main().catch((error) => {
  console.error(`[browser-focus-e2e] ${error instanceof Error ? error.stack : String(error)}`);
  process.exit(1);
});
