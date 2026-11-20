const { test, expect } = require('playwright/test');
const path = require('node:path');

/**
 * The browser panel's practice card must complete a practice, not merely talk
 * about one.
 *
 * The client contract is proven here against a stubbed sidecar: the panel
 * answers on the card, so the answer travels the training chain (attempt
 * start → draft → evidence → practice return) and the recorded practice
 * leaves a progress receipt in the conversation. The server side of the same
 * chain — including the trust level it decides — is proven by
 * `server/tests/test_browser_chat.py`.
 */

const panelUrl = `file://${path.resolve(__dirname, "..", "browser-extension", "sidepanel", "sidepanel.html")}`;

const SNAPSHOT = {
  session_id: 'session-browser-panel',
  contextId: 'workspace-browser-panel',
  plan: { title: 'Browser panel journey' },
  workspaceTrainingState: {
    workspaceId: 'workspace-browser-panel',
    selectedCardId: 'browser-practice-1',
    selectedCardType: 'practice',
    selectedCardTitle: 'Fixture 练习:边界检查',
    selectedCardStatus: 'active',
    latestLearningFocusArea: '边界检查',
    skillProjection: {
      dimensions: {
        comprehension: { state: 'repeat_verified', verifiedCount: 3 },
        implementation: { state: 'assisted', verifiedCount: 1 },
        debugging: { state: 'not_verified', verifiedCount: 0 },
        transfer: { state: 'not_verified', verifiedCount: 0 },
      },
    },
  },
  memory: { reviews: [] },
};

/** The panel runs from a file:// page, so the stubbed sidecar answers with CORS. */
function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  };
}

function stubbedSidecar(calls) {
  return async (input, init) => {
    const url = typeof input === 'string' ? input : String(input && input.url);
    const method = (init && init.method) || 'GET';
    const body = init && init.body ? JSON.parse(init.body) : {};
    const record = { url, method, body };
    calls.push(record);

    const json = (payload) => new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });

    if (url.includes('/browser/chat/bootstrap')) {
      return json(SNAPSHOT);
    }
    if (url.includes('/browser/chat/training/attempt/start')) {
      return json({ ok: true, attempt: { attempt_id: 'attempt-browser-1' } });
    }
    if (url.includes('/browser/chat/training/attempt/update')) {
      return json({ ok: true });
    }
    if (url.includes('/browser/chat/training/attempt/evidence')) {
      return json({ ok: true, evidence: { trust_level: 'self_reported' } });
    }
    if (url.includes('/browser/chat/training/practice-return')) {
      return json({ ok: true, workspace: { workspace_id: 'workspace-browser-panel' } });
    }
    if (url.includes('/browser/chat/sessions')) {
      return json({ sessions: [] });
    }
    if (url.includes('/browser/chat/message/stream')) {
      return new Response(
        'event: complete\ndata: {"response":{"reply":{"content":"这一轮的边界检查已经覆盖。"}}}\n\n',
        { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
      );
    }
    return json({});
  };
}

test('the browser panel answers a practice through the training chain', async ({ page }) => {
  const calls = [];
  await page.addInitScript(() => {
    const auth = { credential: 'credential-test', baseUrl: 'http://127.0.0.1:9', workspaceId: 'workspace-browser-panel' };
    window.chrome = {
      storage: {
        local: {
          // Chrome's API serves both a callback and a promise form.
          get: (keys, callback) => {
            const value = {
              'trainerCapture.credential': auth.credential,
              'trainerCapture.baseUrl': auth.baseUrl,
              'trainerCapture.workspaceId': auth.workspaceId,
            };
            if (typeof callback === 'function') {
              callback(value);
              return undefined;
            }
            return Promise.resolve(value);
          },
          set: (_items, callback) => {
            if (typeof callback === 'function') {
              callback();
              return undefined;
            }
            return Promise.resolve();
          },
        },
      },
      // The panel follows the browser locale; pin it so the assertions can
      // name the localized dimension labels.
      i18n: { getUILanguage: () => 'zh-CN' },
      runtime: {
        sendMessage: (message, callback) => {
          if (message && message.type === 'trainer:state') {
            callback({ workspaceName: 'Browser panel journey', workspaceId: 'workspace-browser-panel' });
            return;
          }
          callback && callback({});
        },
      },
      tabs: {
        query: async () => [],
        onActivated: { addListener: () => undefined },
        onUpdated: { addListener: () => undefined },
      },
    };
  });
  await page.route('**/browser/chat/**', async (route) => {
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: corsHeaders() });
      return;
    }
    const response = await stubbedSidecar(calls)(route.request().url(), {
      method: route.request().method(),
      body: route.request().postData() || undefined,
    });
    await route.fulfill({
      status: response.status,
      headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
      body: await response.text(),
    });
  });

  await page.goto(panelUrl);
  await expect(page.locator('#practice-card')).toBeVisible();

  await page.locator('#practice-answer').fill('边界检查已覆盖：拒绝时保留原始 workspace_id。');
  await page.locator('#practice-submit').click();

  // The answer travels the training chain, not only the chat.
  await expect.poll(() => calls.filter((call) => call.url.includes('/training/attempt/start')).length).toBe(1);
  await expect.poll(() => calls.filter((call) => call.url.includes('/training/attempt/update')).length).toBe(1);
  await expect.poll(() => calls.filter((call) => call.url.includes('/training/attempt/evidence')).length).toBe(1);
  await expect.poll(() => calls.filter((call) => call.url.includes('/training/practice-return')).length).toBe(1);

  const start = calls.find((call) => call.url.includes('/training/attempt/start'));
  expect(start.body.card_id).toBe('browser-practice-1');
  const update = calls.find((call) => call.url.includes('/training/attempt/update'));
  expect(update.body.attempt_id).toBe('attempt-browser-1');
  expect(update.body.answer_draft).toContain('边界检查已覆盖');
  const evidence = calls.find((call) => call.url.includes('/training/attempt/evidence'));
  expect(evidence.body.attempt_id).toBe('attempt-browser-1');
  // The evidence binds to what the learner wrote and says who produced it.
  expect(String(evidence.body.artifact_hash)).toMatch(/^[0-9a-f]{64}$/);
  expect(evidence.body.runner_version).toBe('trainer-browser-panel');
  expect(evidence.body.limitations).toContain('learner_self_report');
  const practiceReturn = calls.find((call) => call.url.includes('/training/practice-return'));
  expect(practiceReturn.body.card_id).toBe('browser-practice-1');
  expect(practiceReturn.body.passed).toBe(true);
  expect(practiceReturn.body.evidence_source).toBe('learner_return');

  // The panel says what happened, and the practice leaves a receipt.
  await expect(page.locator('#practice-notice')).toBeVisible();
  await expect(page.locator('[data-progress-receipt="true"]')).toBeVisible();
  await expect(page.locator('[data-progress-receipt="true"]')).toContainText('理解');
  await expect(page.locator('[data-progress-receipt="true"]')).toContainText('实现');
  // The band text is localized, like the workbench's own progress rows.
  await expect(page.locator('[data-progress-receipt="true"]')).toContainText('反复验证');
  await expect(page.locator('[data-progress-receipt="true"]')).toContainText('有辅助完成');
  await expect(page.locator('[data-progress-receipt="true"]')).toContainText('4 条证据');
  // A receipt names the dimensions with evidence; it never repeats the
  // dimensions that have none.
  await expect(page.locator('[data-progress-receipt="true"]')).not.toContainText('迁移');
});

test('a practice the sidecar refuses is reported, not claimed', async ({ page }) => {
  const calls = [];
  await page.addInitScript(() => {
    const auth = { credential: 'credential-test', baseUrl: 'http://127.0.0.1:9', workspaceId: 'workspace-browser-panel' };
    window.chrome = {
      storage: {
        local: {
          // Chrome's API serves both a callback and a promise form.
          get: (keys, callback) => {
            const value = {
              'trainerCapture.credential': auth.credential,
              'trainerCapture.baseUrl': auth.baseUrl,
              'trainerCapture.workspaceId': auth.workspaceId,
            };
            if (typeof callback === 'function') {
              callback(value);
              return undefined;
            }
            return Promise.resolve(value);
          },
          set: (_items, callback) => {
            if (typeof callback === 'function') {
              callback();
              return undefined;
            }
            return Promise.resolve();
          },
        },
      },
      // The panel follows the browser locale; pin it so the assertions can
      // name the localized dimension labels.
      i18n: { getUILanguage: () => 'zh-CN' },
      runtime: {
        sendMessage: (message, callback) => {
          if (message && message.type === 'trainer:state') {
            callback({ workspaceName: 'Browser panel journey', workspaceId: 'workspace-browser-panel' });
            return;
          }
          callback && callback({});
        },
      },
      tabs: {
        query: async () => [],
        onActivated: { addListener: () => undefined },
        onUpdated: { addListener: () => undefined },
      },
    };
  });
  await page.route('**/browser/chat/**', async (route) => {
    const url = route.request().url();
    calls.push({ url });
    const headers = { ...corsHeaders(), 'Content-Type': 'application/json' };
    if (url.includes('/browser/chat/bootstrap')) {
      await route.fulfill({ status: 200, headers, body: JSON.stringify(SNAPSHOT) });
      return;
    }
    if (url.includes('/training/practice-return')) {
      await route.fulfill({ status: 409, headers, body: JSON.stringify({ detail: 'not allowed' }) });
      return;
    }
    if (url.includes('/training/attempt/start')) {
      await route.fulfill({ status: 200, headers, body: JSON.stringify({ ok: true, attempt: { attempt_id: 'attempt-browser-1' } }) });
      return;
    }
    await route.fulfill({ status: 200, headers, body: JSON.stringify({ ok: true }) });
  });

  await page.goto(panelUrl);
  await expect(page.locator('#practice-card')).toBeVisible();
  await page.locator('#practice-answer').fill('这次没有记录上。');
  await page.locator('#practice-submit').click();

  // The panel reports the failure instead of claiming a completed practice.
  await expect(page.locator('#practice-notice')).toBeVisible();
  await expect(page.locator('[data-progress-receipt="true"]')).toHaveCount(0);
  // And no coaching turn is sent for an answer that was never recorded.
  await expect.poll(() => calls.filter((call) => call.url.includes('/message/stream')).length).toBe(0);
});
