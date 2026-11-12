#!/usr/bin/env node
/**
 * Structural teaching journey against a real sidecar + real SQLite.
 *
 * Provider-gated steps are recorded as BLOCKED, never PASS: this script does
 * not pretend a dead/invalid key produced a real teaching turn. The UI
 * surfaces are covered separately by the Playwright journey specs.
 *
 * Steps 18-21 drive one coach turn through a local scripted OpenAI-compatible
 * stub (declared in every step detail). They prove the unified ledger wiring
 * (goal_started / coach_turn_recorded / goal_activity_recorded /
 * training_evidence_recorded, plus idempotent replay) over real HTTP and real
 * SQLite — they make no claim about model teaching quality.
 */

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const serverDir = path.join(repoRoot, 'server');
const python = path.join(serverDir, '.venv', 'bin', 'python');
const port = Number(process.env.TRAINER_STRUCTURAL_PORT ?? 34978);
const baseUrl = `http://127.0.0.1:${port}`;
const outDir = path.resolve(
  process.env.TRAINER_STRUCTURAL_OUT ??
    path.join(repoRoot, '.trainer-convergence', 'evidence', 'journey-structural-current'),
);
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-structural-'));
const steps = [];
let sidecar;
let sidecarLog = '';

fs.mkdirSync(outDir, { recursive: true });

function record(id, status, detail) {
  steps.push({ id, status, detail });
  fs.writeFileSync(path.join(outDir, `${id}.json`), JSON.stringify({ id, status, ...detail }, null, 2) + '\n');
  console.log(`[${status}] ${id}${detail && detail.reason ? ` — ${detail.reason}` : ''}`);
}

async function request(method, pathName, body, headers = {}) {
  const response = await fetch(`${baseUrl}${pathName}`, {
    method,
    headers: { 'content-type': 'application/json', ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let json = null;
  try { json = text ? JSON.parse(text) : null; } catch { /* non-JSON */ }
  return { status: response.status, json, text };
}

async function waitHealth() {
  for (let attempt = 0; attempt < 240; attempt += 1) {
    try {
      const response = await fetch(`${baseUrl}/health`);
      if (response.ok) return;
    } catch { /* keep polling */ }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error('sidecar did not become healthy');
}

function startSidecar() {
  sidecar = spawn(python, ['run_sidecar.py', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: serverDir,
    env: { ...process.env, TRAINER_DATA_DIR: dataDir, TRAINER_ENABLE_NETWORK_FETCH: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  sidecar.stdout.on('data', (chunk) => { sidecarLog += chunk.toString(); });
  sidecar.stderr.on('data', (chunk) => { sidecarLog += chunk.toString(); });
}

async function stopSidecar() {
  if (!sidecar || sidecar.exitCode !== null) return;
  sidecar.kill('SIGTERM');
  for (let attempt = 0; attempt < 20 && sidecar.exitCode === null; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  if (sidecar.exitCode === null) sidecar.kill('SIGKILL');
}

// ---- Scripted OpenAI-compatible stub provider (ledger wiring only) ----
// The reply text is fixed and self-describing: these steps exercise the real
// sidecar pipeline (provider transport -> coach turn -> goal observation ->
// ledger) without claiming a real model produced the content.
let stubServer = null;
let stubBaseUrl = '';
const STUB_REPLY =
  '结构性验证回合：这是本地脚本化回复，不代表真实模型；' +
  '只用于证明教练轮次与统一学习事件账本的接线。';

function startStubProvider() {
  stubServer = http.createServer((request, response) => {
    const url = request.url ?? '';
    if ((request.method ?? '').toUpperCase() === 'GET' && url.includes('/models')) {
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ data: [{ id: 'structural-stub' }] }));
      return;
    }
    if (!url.includes('/chat/completions')) {
      response.writeHead(404, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ error: 'structural stub: not found' }));
      return;
    }
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      let stream = false;
      try {
        const body = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
        stream = Boolean(body?.stream);
      } catch { /* default to non-stream */ }
      const created = Math.floor(Date.now() / 1000);
      if (stream) {
        response.writeHead(200, { 'content-type': 'text/event-stream' });
        const delta = {
          id: 'structural-stub-chunk',
          object: 'chat.completion.chunk',
          created,
          model: 'structural-stub',
          choices: [{ index: 0, delta: { content: STUB_REPLY }, finish_reason: null }],
        };
        response.write(`data: ${JSON.stringify(delta)}\n\n`);
        response.write(
          `data: ${JSON.stringify({
            ...delta,
            choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
          })}\n\n`,
        );
        response.write('data: [DONE]\n\n');
        response.end();
        return;
      }
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(
        JSON.stringify({
          id: 'structural-stub-completion',
          object: 'chat.completion',
          created,
          model: 'structural-stub',
          choices: [
            { index: 0, message: { role: 'assistant', content: STUB_REPLY }, finish_reason: 'stop' },
          ],
          usage: { prompt_tokens: 16, completion_tokens: 32, total_tokens: 48 },
        }),
      );
    });
  });
  return new Promise((resolve) => {
    stubServer.listen(0, '127.0.0.1', () => {
      const address = stubServer.address();
      stubBaseUrl = `http://127.0.0.1:${address.port}`;
      resolve(stubBaseUrl);
    });
  });
}

async function stopStubProvider() {
  if (!stubServer) return;
  const server = stubServer;
  stubServer = null;
  await new Promise((done) => server.close(() => done()));
}

function openLedgerDb() {
  const primary = path.join(dataDir, 'trainer.sqlite3');
  if (fs.existsSync(primary)) return new DatabaseSync(primary);
  const found = fs.readdirSync(dataDir).find((name) => name.endsWith('.sqlite3'));
  if (!found) throw new Error(`no sqlite db under ${dataDir}`);
  return new DatabaseSync(path.join(dataDir, found));
}

function ledgerInventory(db) {
  return db
    .prepare('SELECT event_type, COUNT(*) AS n FROM event_ledger GROUP BY event_type')
    .all()
    .reduce((acc, row) => {
      acc[row.event_type] = row.n;
      return acc;
    }, {});
}

try {
  try {
    const stale = await fetch(`${baseUrl}/health`);
    if (stale.ok) throw new Error(`port ${port} is already served; kill the stale sidecar first`);
  } catch (error) {
    if (String(error?.message || '').includes('already served')) throw error;
  }

  startSidecar();
  await waitHealth();

  const startA = await request('POST', '/session/start', {
    workspace_id: 'journey-structural-a',
    workspace_name: 'Journey Structural A',
  });
  if (startA.status !== 200) throw new Error(`session A failed: ${startA.status} ${startA.text}`);
  const sessionA = startA.json.session_id;
  record('01-session-start', 'PASS', { status: startA.status, session_id: sessionA });

  const upload = await request('POST', '/resource/upload', {
    session_id: sessionA,
    workspace_id: 'journey-structural-a',
    name: 'queue_lock.py',
    kind: 'code',
    source: 'file',
    content:
      'import threading\n\nclass Queue:\n    def __init__(self):\n        self._items = []\n        self._lock = threading.Lock()\n\n    def push(self, item):\n        with self._lock:\n            self._items.append(item)\n\n    def pop(self):\n        with self._lock:\n            if not self._items:\n                raise IndexError("empty")\n            return self._items.pop(0)\n',
  });
  const resourceId = upload.json?.id ?? upload.json?.resource_id ?? null;
  if (upload.status !== 200 || !resourceId) throw new Error(`resource upload failed: ${upload.status} ${upload.text}`);
  record('02-resource-upload', 'PASS', { status: upload.status, resource_id: resourceId });

  const index = await request('POST', '/resource/index', {
    workspace_id: 'journey-structural-a',
    resource_id: resourceId,
    enable_network: false,
  });
  record('02b-resource-index', index.status === 200 ? 'PASS' : 'FAIL', {
    status: index.status,
    index_status: index.json?.index_status ?? null,
  });

  const search = await request('POST', '/resource/search', {
    session_id: sessionA,
    workspace_id: 'journey-structural-a',
    query: 'threading Lock',
  });
  const hitIds = (search.json?.hits ?? []).map((hit) => hit.id);
  record('03-resource-search', search.status === 200 && hitIds.includes(resourceId) ? 'PASS' : 'FAIL', {
    status: search.status,
    hit_count: hitIds.length,
    indexed_resource_found: hitIds.includes(resourceId),
  });

  const globalPlan = await request('POST', '/plan/global', {
    workspace_id: 'journey-structural-a',
    title: 'Python concurrency foundations',
    summary: 'Structural plan persistence check; no provider-generated content.',
    goals: ['Understand locks and queues', 'Verify with a minimal threaded example'],
    stages: [{
      id: 'stage-1',
      title: 'Locks and queues',
      goal: 'Explain why a lock guards the queue.',
      outcomes: ['Name the critical section', 'Run one verification'],
      resources: [],
      status: 'active',
    }],
    current_stage_id: 'stage-1',
    current_step: 'Read the queue lock example',
    verify_method: ['Run a two-thread push/pop smoke test'],
  });
  record(globalPlan.status === 200 ? '04-global-plan' : '04-global-plan', globalPlan.status === 200 ? 'PASS' : 'FAIL', {
    status: globalPlan.status,
    plan_titles: (globalPlan.json?.stages ?? []).map((stage) => stage.title),
  });

  // Provider-gated by design: without a real key Trainer must refuse rather
  // than fabricate a plan/card.
  const planGenerate = await request('POST', '/plan/generate', {
    session_id: sessionA,
    workspace_id: 'journey-structural-a',
    profile: { long_term_goal: 'Python concurrency', weekly_hours: 5, teaching_style: 'guided', answer_policy: 'guided' },
    goals: ['Understand locks and queues'],
  });
  record('05-real-plan-generate', 'BLOCKED', {
    status: planGenerate.status,
    reason: 'No real provider key in this session; fail-closed response recorded.',
    error: planGenerate.text.slice(0, 240),
  });

  const card = await request('POST', '/training/generate-card', {
    workspace_id: 'journey-structural-a',
    session_id: sessionA,
  });
  record('06-real-training-card', 'BLOCKED', {
    status: card.status,
    reason: 'Card generation is provider-gated; no real key in this session.',
    error: card.text.slice(0, 240),
  });

  // Real attempt/evidence persistence with a synthetic card id. This proves
  // the Training -> Verification -> projection path without claiming teaching
  // quality or a generated card.
  const attemptStart = await request('POST', '/training/attempt/start', {
    workspace_id: 'journey-structural-a',
    card_id: 'structural-card-1',
    assistance_level: 'independent',
  });
  const attemptId = attemptStart.json?.attempt?.attempt_id;
  record(attemptStart.status === 200 && attemptId ? '07-attempt-start' : '07-attempt-start', attemptStart.status === 200 && attemptId ? 'PASS' : 'FAIL', {
    status: attemptStart.status,
    attempt_id: attemptId,
    note: 'synthetic card id; structural persistence only',
  });
  if (attemptId) {
    await request('POST', '/training/attempt/update', {
      attempt_id: attemptId,
      workspace_id: 'journey-structural-a',
      answer_draft: 'The lock guards the critical section around _items.',
      status: 'submitted',
    });
    const evidence = await request('POST', '/training/attempt/evidence', {
      attempt_id: attemptId,
      workspace_id: 'journey-structural-a',
      artifact_hash: 'sha256:structural-probe',
      result: 'pass',
      runner_version: 'structural-probe',
      execution_location: 'workspace',
      limitations: ['structural probe; no real provider or generated card'],
    });
    record(evidence.status === 200 ? '08-attempt-evidence' : '08-attempt-evidence', evidence.status === 200 ? 'PASS' : 'FAIL', {
      status: evidence.status,
      trust_level: evidence.json?.trust_level ?? null,
      note: 'self_reported by design; not host-attested',
    });
  }

  const browserPair = await request('POST', '/browser/auto-pair', {}, {
    Origin: 'chrome-extension://structuraljourney',
  });
  const browserToken = browserPair.json?.credential ?? '';
  record(browserPair.status === 200 && browserToken ? '09-browser-pair' : '09-browser-pair', browserPair.status === 200 && browserToken ? 'PASS' : 'FAIL', {
    status: browserPair.status,
    workspace_id: browserPair.json?.workspace_id ?? null,
  });
  if (browserToken) {
    const draft = await request('POST', '/browser/coach-draft', {
      selection: 'The lock guards the critical section around _items.',
      url: 'https://example.com/queue-lock',
      title: 'Queue lock example',
      client_id: 'structural-draft-1',
    }, { Authorization: `Bearer ${browserToken}` });
    const draftId = draft.json?.draft_id ?? draft.json?.id ?? '';
    record('10-browser-draft', draft.status === 200 && draftId ? 'PASS' : 'FAIL', {
      status: draft.status,
      draft_id: draftId,
    });
    const pending = await fetch(
      `${baseUrl}/browser/pending-drafts?workspace_id=journey-structural-a`,
    );
    const pendingJson = await pending.json().catch(() => null);
    const pendingIds = (pendingJson?.drafts ?? []).map((item) => item.id ?? item.draft_id);
    record('11-draft-visible-to-host', pendingIds.includes(draftId) ? 'PASS' : 'FAIL', {
      status: pending.status,
      pending_ids: pendingIds,
    });
    if (draftId) {
      const ack = await request('POST', '/browser/pending-drafts/ack', {
        workspace_id: 'journey-structural-a',
        ids: [draftId],
      });
      record(ack.status === 200 ? '12-draft-ack' : '12-draft-ack', ack.status === 200 ? 'PASS' : 'FAIL', {
        status: ack.status,
      });
    }
  }

  await request('POST', '/training/attempt/update', {
    attempt_id: attemptId,
    workspace_id: 'journey-structural-a',
    answer_draft: 'with lock: self._items.append(item)',
  });
  const memory = await fetch(`${baseUrl}/memory/summary?workspace_id=journey-structural-a`);
  const memoryJson = await memory.json().catch(() => null);
  record(memory.status === 200 ? '13-memory-summary' : '13-memory-summary', memory.status === 200 ? 'PASS' : 'FAIL', {
    status: memory.status,
    has_summary: Boolean(memoryJson),
    resource_ids: (memoryJson?.memory?.resources ?? []).map((item) => item.id),
  });

  await stopSidecar();
  startSidecar();
  await waitHealth();
  const restored = await request('POST', '/session/start', {
    session_id: sessionA,
    workspace_id: 'journey-structural-a',
    workspace_name: 'Journey Structural A',
  });
  record(restored.status === 200 && restored.json?.session_id === sessionA ? '14-restart-restore' : '14-restart-restore', restored.status === 200 && restored.json?.session_id === sessionA ? 'PASS' : 'FAIL', {
    status: restored.status,
    same_session: restored.json?.session_id === sessionA,
  });

  const startB = await request('POST', '/session/start', {
    workspace_id: 'journey-structural-b',
    workspace_name: 'Journey Structural B',
  });
  const searchB = await request('POST', '/resource/search', {
    session_id: startB.json?.session_id,
    workspace_id: 'journey-structural-b',
    query: 'threading Lock',
  });
  const memoryB = await fetch(`${baseUrl}/memory/summary?workspace_id=journey-structural-b`);
  const memoryBJson = await memoryB.json().catch(() => null);
  const bResourceIds = (memoryBJson?.memory?.resources ?? []).map((item) => item.id);
  record(searchB.status === 200 && !bResourceIds.includes(resourceId) ? '15-workspace-isolation' : '15-workspace-isolation', searchB.status === 200 && !bResourceIds.includes(resourceId) ? 'PASS' : 'FAIL', {
    search_status: searchB.status,
    workspace_b_resource_ids: bResourceIds,
    cross_workspace_leak: bResourceIds.includes(resourceId),
  });

  record('16-real-model-switch', 'BLOCKED', {
    reason: 'No real provider key in this session; UI model-switch path is covered by trainer-settings-lifecycle / provider configuration specs.',
  });
  record('17-remote-ssh-l2', 'BLOCKED', { reason: 'No real Remote-SSH window in this environment.' });

  // ---- Unified ledger wiring over real HTTP (scripted stub provider) ----
  // Steps 18-21 prove the event families land in the real SQLite ledger via
  // the real HTTP pipeline: coach turn -> goal observation -> goal activity,
  // plus the attempt-evidence bridge (step 08) and idempotent replay.
  const stubUrl = await startStubProvider();
  const coachMessage = {
    session_id: sessionA,
    workspace_id: 'journey-structural-a',
    message: '请开始第一课：为什么队列需要锁？',
    goal_mode: true,
    goal_text: '两周内掌握 threading.Lock 与队列',
    request_id: 'structural-ledger-turn-1',
    provider: { name: 'structural-stub', base_url: stubUrl, model: 'structural-stub' },
    api_key: 'structural-stub-key',
  };
  const turn1 = await request('POST', '/session/message', coachMessage);
  const db = openLedgerDb();
  const inventory1 = ledgerInventory(db);
  const goalRows = db.prepare('SELECT COUNT(*) AS n FROM goal_sessions').all();
  const turnKeyRows = db
    .prepare("SELECT COUNT(*) AS n FROM event_ledger WHERE event_type = 'coach_turn_recorded' AND idempotency_key LIKE '%structural-ledger-turn-1'")
    .all();
  record('18-coach-turn-ledger', turn1.status === 200
      && (inventory1.goal_started ?? 0) >= 1
      && (inventory1.coach_turn_recorded ?? 0) >= 1
      && (turnKeyRows[0]?.n ?? 0) === 1
      && (goalRows[0]?.n ?? 0) >= 1
    ? 'PASS' : 'FAIL', {
    status: turn1.status,
    provider: 'structural-stub (scripted reply; wiring only)',
    goal_sessions: goalRows[0]?.n ?? 0,
    goal_started_events: inventory1.goal_started ?? 0,
    coach_turn_events: inventory1.coach_turn_recorded ?? 0,
    turn_key_rows: turnKeyRows[0]?.n ?? 0,
  });

  const turnReplay = await request('POST', '/session/message', coachMessage);
  const inventory2 = ledgerInventory(db);
  const replayIdempotent = (inventory2.coach_turn_recorded ?? 0) === (inventory1.coach_turn_recorded ?? 0)
    && (inventory2.goal_started ?? 0) === (inventory1.goal_started ?? 0);
  record('19-coach-turn-idempotent', turnReplay.status === 200 && replayIdempotent ? 'PASS' : 'FAIL', {
    status: turnReplay.status,
    provider: 'structural-stub (scripted reply; wiring only)',
    coach_turn_events_after_replay: inventory2.coach_turn_recorded ?? 0,
    goal_started_events_after_replay: inventory2.goal_started ?? 0,
  });

  const evaluation = await request('POST', '/evaluate/snippet', {
    session_id: sessionA,
    workspace_id: 'journey-structural-a',
    language_id: 'python',
    content: 'from queue import Queue\nq = Queue()\nq.push(1)\nassert q.pop() == 1\n',
  });
  const inventory3 = ledgerInventory(db);
  record('20-goal-activity-ledger', evaluation.status === 200 && (inventory3.goal_activity_recorded ?? 0) >= 1 ? 'PASS' : 'FAIL', {
    status: evaluation.status,
    provider: 'not needed (local evaluator; stub still attached)',
    goal_activity_events: inventory3.goal_activity_recorded ?? 0,
  });

  const requiredFamilies = [
    'goal_started',
    'coach_turn_recorded',
    'goal_activity_recorded',
    'training_evidence_recorded',
  ];
  const missingFamilies = requiredFamilies.filter((family) => (inventory3[family] ?? 0) < 1);
  fs.writeFileSync(
    path.join(outDir, 'event_ledger.json'),
    `${JSON.stringify({ inventory: inventory3, requiredFamilies, missing: missingFamilies }, null, 2)}\n`,
  );
  record('21-ledger-inventory', missingFamilies.length === 0 ? 'PASS' : 'FAIL', {
    inventory: inventory3,
    missing: missingFamilies,
    training_evidence_note: 'from step 08 attempt evidence via the ledger bridge',
  });
  db.close();
} catch (error) {
  record('00-probe', 'FAIL', { error: error instanceof Error ? error.message : String(error), sidecar_log: sidecarLog.slice(-3000) });
  process.exitCode = 1;
} finally {
  await stopStubProvider();
  await stopSidecar();
  fs.rmSync(dataDir, { recursive: true, force: true });
  const summary = {
    generatedAt: new Date().toISOString(),
    baseUrl,
    steps,
    blocked: steps.filter((step) => step.status === 'BLOCKED').map((step) => step.id),
    failed: steps.filter((step) => step.status === 'FAIL').map((step) => step.id),
    stubProviderSteps: steps
      .filter((step) => String(step.provider || '').includes('structural-stub'))
      .map((step) => step.id),
  };
  fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n');
  console.log(`[structural] ${steps.filter((step) => step.status === 'PASS').length} PASS, ${summary.blocked.length} BLOCKED, ${summary.failed.length} FAIL -> ${outDir}`);
}
