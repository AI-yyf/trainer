'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { spawn } = require('node:child_process');

const scriptPath = path.resolve(__dirname, '..', '..', 'scripts', 'resources-smoke.mjs');
const MARKER = 'RESOURCE-SMOKE-MARKER-ALPHA-7f3c';

function startMockTrainer({
  skipFtsHit = false,
  skipBadFileFail = false,
  skipCoachGrounding = false,
} = {}) {
  const sessions = new Map();
  let sessionCounter = 0;
  let resourceCounter = 0;
  const uploads = [];
  const indexes = [];
  const searches = [];
  const messages = [];

  const server = http.createServer((request, response) => {
    if (request.url === '/provider/test' && request.method === 'POST') {
      response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(JSON.stringify({
        ok: true,
        tools_ready: true,
      }));
      return;
    }

    if (request.url === '/session/start' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        sessionCounter += 1;
        const payload = JSON.parse(body);
        const sessionId = `session-${sessionCounter}`;
        sessions.set(sessionId, {
          workspaceId: payload.workspace_id,
          resources: new Map(),
        });
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({ session_id: sessionId }));
      });
      return;
    }

    if (request.url === '/resource/upload' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        uploads.push(payload);
        const session = sessions.get(payload.session_id);
        const source = String(payload.source || '');
        if (source.includes('does-not-exist')) {
          response.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' });
          response.end(JSON.stringify({
            detail: `Local resource source does not exist: ${source}`,
          }));
          return;
        }
        resourceCounter += 1;
        const resource = {
          id: `resource-${resourceCounter}`,
          name: payload.name,
          content: payload.content || '',
          index_status: 'pending',
        };
        if (session) {
          session.resources.set(resource.id, resource);
        }
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({
          id: resource.id,
          name: resource.name,
          index_status: 'pending',
          kind: payload.kind,
        }));
      });
      return;
    }

    if (request.url === '/resource/index' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        indexes.push(payload);
        if (payload.resource_id === 'resource-does-not-exist-xyz') {
          response.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
          response.end(JSON.stringify({
            detail: "'Unknown resource_id: resource-does-not-exist-xyz'",
          }));
          return;
        }
        const session = sessions.get(payload.session_id);
        const resource = session?.resources.get(payload.resource_id);
        if (!resource) {
          response.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
          response.end(JSON.stringify({ detail: `Unknown resource_id: ${payload.resource_id}` }));
          return;
        }
        const empty = !String(resource.content || '').trim();
        if (empty && !skipBadFileFail) {
          resource.index_status = 'failed';
          response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
          response.end(JSON.stringify({
            id: resource.id,
            index_status: 'failed',
            parse_status: 'failed',
            quality_flags: ['no_content'],
            warnings: ['Text resource had no inline content and no readable file path.'],
            trust_state: 'untrusted',
          }));
          return;
        }
        if (empty && skipBadFileFail) {
          resource.index_status = 'indexed';
          response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
          response.end(JSON.stringify({
            id: resource.id,
            index_status: 'indexed',
            parse_status: 'parsed',
            quality_flags: [],
            trust_state: 'trusted',
          }));
          return;
        }
        resource.index_status = 'indexed';
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({
          id: resource.id,
          index_status: 'indexed',
          parse_status: 'parsed',
          trust_state: 'trusted',
          freshness: 'fresh',
        }));
      });
      return;
    }

    if (request.url === '/resource/search' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        searches.push(payload);
        const session = [...sessions.values()].find((entry) => entry.workspaceId === payload.workspace_id)
          || [...sessions.values()][0];
        const indexed = [...(session?.resources.values() || [])].filter((item) => item.index_status === 'indexed');
        const hits = skipFtsHit
          ? []
          : indexed
            .filter((item) => String(item.content).includes(MARKER) || payload.query === MARKER)
            .map((item) => ({
              resource_id: item.id,
              title: item.name,
              citation_id: `citation:${item.id}`,
            }));
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({
          workspace_id: payload.workspace_id,
          total: hits.length,
          ranking_strategy: 'lexical_first',
          hits,
        }));
      });
      return;
    }

    if (request.url === '/session/message' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        messages.push(payload);
        const evidenceHits = skipCoachGrounding
          ? []
          : [{ title: 'coach-notes.md', resource_id: 'resource-1' }];
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({
          session_id: payload.session_id,
          reply: {
            content: skipCoachGrounding
              ? 'I cannot see any resources.'
              : `The marker is ${MARKER}. Resources must not invent missing files.`,
            metadata: {
              stop_reason: 'completed',
              auto_resource_lookup: !skipCoachGrounding,
              tool_events: skipCoachGrounding
                ? []
                : [{
                  name: 'search_resources',
                  result: { hits: evidenceHits, total: evidenceHits.length },
                }],
              coach_visible_status: {
                type: 'coach_visible_status',
                status: 'done',
                source: skipCoachGrounding ? 'agent_loop' : 'resource_context',
                stopReason: 'completed',
                toolNames: skipCoachGrounding ? [] : ['search_resources'],
              },
            },
          },
        }));
      });
      return;
    }

    response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end(`unexpected ${request.method} ${request.url}`);
  });

  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({
        server,
        port,
        uploads,
        indexes,
        searches,
        messages,
        close: () => new Promise((closeResolve, closeReject) => {
          server.close((error) => {
            if (error) {
              closeReject(error);
              return;
            }
            closeResolve();
          });
        }),
      });
    });
  });
}

function runSmoke(env) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [scriptPath], {
      env: {
        ...process.env,
        ...env,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
    });
    child.on('error', reject);
    child.on('close', (code) => {
      resolve({ code, stdout, stderr });
    });
  });
}

function parseLastJson(text) {
  const lines = String(text || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    try {
      return JSON.parse(lines[index]);
    } catch {
      // keep scanning
    }
  }
  return null;
}

function baseEnv(port) {
  return {
    TRAINER_RESOURCES_SMOKE_SIDECAR_URL: `http://127.0.0.1:${port}`,
    TRAINER_RESOURCES_SMOKE_PROVIDER_BASE_URL: 'http://127.0.0.1:9/v1',
    TRAINER_RESOURCES_SMOKE_PROVIDER_API_KEY: 'sk-test-not-a-real-key',
    TRAINER_RESOURCES_SMOKE_PROVIDER_MODEL: 'gpt-test',
    TRAINER_RESOURCES_SMOKE_PROVIDER_PROTOCOL: 'openai_chat_completions_compatible',
    TRAINER_RESOURCES_SMOKE_DEAD_SIDECAR_URL: 'http://127.0.0.1:17999',
  };
}

test('resources smoke script exists', () => {
  assert.equal(fs.existsSync(scriptPath), true);
});

test('resources smoke passes load + FTS + failure categories + coach handoff on mock sidecar', async () => {
  const mock = await startMockTrainer();
  try {
    const result = await runSmoke(baseEnv(mock.port));
    const report = parseLastJson(result.stdout);
    assert.equal(result.code, 0, result.stderr || result.stdout);
    assert.equal(report?.ok, true);
    assert.equal(report?.checks?.resource_load, 'passed');
    assert.equal(report?.checks?.fts_search, 'passed');
    assert.equal(report?.checks?.failure_bad_file, 'passed');
    assert.equal(report?.checks?.failure_missing, 'passed');
    assert.equal(report?.checks?.failure_sidecar_down, 'passed');
    assert.equal(report?.checks?.coach_handoff, 'passed');
    assert.equal(report?.checks?.session_continuity, 'passed');
    assert.equal(report?.sessionContinuity?.preserved, true);
    assert.ok(Number(report?.elapsedMs) >= 0);
    assert.equal(report?.failureCategories?.bad_file?.category, 'bad_file');
    assert.equal(report?.failureCategories?.missing?.category, 'missing');
    assert.equal(report?.failureCategories?.sidecar_down?.category, 'sidecar_down');
    assert.ok(mock.uploads.length >= 2);
    assert.ok(mock.indexes.length >= 2);
    assert.ok(mock.searches.length >= 1);
    assert.equal(mock.messages.length, 1);
    assert.equal(mock.messages[0].session_id, report.sessionContinuity.sessionId);
    assert.ok(!JSON.stringify(report).includes('sk-test-not-a-real-key'));
  } finally {
    await mock.close();
  }
});

test('resources smoke fails honestly when FTS misses indexed resource', async () => {
  const mock = await startMockTrainer({ skipFtsHit: true });
  try {
    const result = await runSmoke(baseEnv(mock.port));
    const report = parseLastJson(result.stderr) || parseLastJson(result.stdout);
    assert.notEqual(result.code, 0);
    assert.equal(report?.ok, false);
    assert.equal(report?.step, 'resource_fts_search');
    assert.equal(report?.category, 'fts_missed_indexed_resource');
  } finally {
    await mock.close();
  }
});

test('resources smoke fails honestly when bad_file is not classified', async () => {
  const mock = await startMockTrainer({ skipBadFileFail: true });
  try {
    const result = await runSmoke(baseEnv(mock.port));
    const report = parseLastJson(result.stderr) || parseLastJson(result.stdout);
    assert.notEqual(result.code, 0);
    assert.equal(report?.ok, false);
    assert.equal(report?.step, 'failure_bad_file');
    assert.equal(report?.category, 'bad_file_not_classified');
  } finally {
    await mock.close();
  }
});

test('resources smoke fails honestly when coach lacks resource grounding', async () => {
  const mock = await startMockTrainer({ skipCoachGrounding: true });
  try {
    const result = await runSmoke(baseEnv(mock.port));
    const report = parseLastJson(result.stderr) || parseLastJson(result.stdout);
    assert.notEqual(result.code, 0);
    assert.equal(report?.ok, false);
    assert.equal(report?.step, 'coach_handoff');
    assert.equal(report?.category, 'coach_missing_resource_grounding');
  } finally {
    await mock.close();
  }
});
