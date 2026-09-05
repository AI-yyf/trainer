/**
 * Visible failure-surface contract for Coach tool failures and Settings provider-test
 * failures. Uses the browser preview harness — no VSIX and no real secrets.
 *
 * Run: npx playwright test e2e/trainer-error-surface.spec.js
 */

const { test, expect } = require("playwright/test");

const PREVIEW_PATH = "/vscode-preview.html";
const FAKE_KEY = "sk-test-not-a-real-key-aaaaaaaa";
const LEAK_TEXT = [
  "Traceback (most recent call last):",
  '  File "app.py", line 12, in run',
  "KeyError: boom",
  '{"choices":[{"message":{"content":"hidden","token":"fake-token-zzzz"}}]}',
  `api_key=${FAKE_KEY}`,
].join("\n");

function buildPreviewUrl(view, extra = {}) {
  const query = new URLSearchParams({
    lang: "en-US",
    connection: "connected",
    scenario: "ready",
    ...extra,
  });
  if (view) {
    query.set("view", view);
  }
  return `${PREVIEW_PATH}?${query.toString()}`;
}

function jsonResponse(body) {
  return {
    contentType: "application/json",
    headers: {
      "access-control-allow-origin": "*",
    },
    body: JSON.stringify(body),
  };
}

async function openPreview(page, view, extra) {
  await page.goto(buildPreviewUrl(view, extra));
  await expect(page.locator('#root[data-trainer-app-ready="true"]')).toBeVisible();
}

async function dispatchHostMessage(page, message) {
  await page.evaluate((detail) => {
    if (typeof window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__ === "function") {
      window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__(detail);
      return;
    }
    window.dispatchEvent(new CustomEvent("trainer:host-message", { detail }));
  }, message);
}

async function patchPreviewBootstrap(page, patch) {
  await page.evaluate((nextPatch) => {
    const current =
      window.__TRAINER_BOOTSTRAP__ && typeof window.__TRAINER_BOOTSTRAP__ === "object"
        ? window.__TRAINER_BOOTSTRAP__
        : {};
    const payload = {
      ...current,
      ...nextPatch,
      memory: {
        ...(current.memory ?? {}),
        ...(nextPatch.memory ?? {}),
      },
    };
    window.__TRAINER_BOOTSTRAP__ = payload;
    const message = { type: "bootstrap", payload };
    if (typeof window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__ === "function") {
      window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__(message);
      return;
    }
    window.dispatchEvent(new CustomEvent("trainer:host-message", { detail: message }));
  }, patch);
}

function assertNoLeak(text) {
  expect(text).not.toContain(FAKE_KEY);
  expect(text).not.toMatch(/Traceback \(most recent call last\)/i);
  expect(text).not.toMatch(/File "app\.py"/);
  expect(text).not.toMatch(/"choices"/);
  expect(text).not.toMatch(/fake-token-zzzz/);
  expect(text).not.toMatch(/api_key=sk-/i);
}

test.describe("Trainer error-surface contract", () => {
  test.setTimeout(60_000);

  test("Coach tool failure never shows traceback, JSON body, or a key-shaped token", async ({
    page,
  }) => {
    await openPreview(page, "coach");
    await patchPreviewBootstrap(page, {
      conversation: [
        {
          id: "leak-tool-failure",
          role: "assistant",
          author: "Trainer",
          body: "The last tool step did not finish.",
          timestamp: "09:40",
          parts: [
            {
              type: "tool_result",
              callId: "call-leak-1",
              name: "read_file",
              error: LEAK_TEXT,
              result: { ok: false, error: LEAK_TEXT },
            },
          ],
        },
      ],
    });

    await expect(page.getByText("The last tool step did not finish.")).toBeVisible();
    const runDetails = page.getByText("See run details", { exact: false }).first();
    await expect(runDetails).toBeVisible();
    await runDetails.click();
    const activity = page.locator(".agent-activity-strip, .message-part--tool-result").first();
    await expect(activity).toBeVisible();
    await expect(page.getByText(/Needs another try|did not finish|keep asking|try again/i).first()).toBeVisible();
    const visible = await page.locator("body").innerText();
    assertNoLeak(visible);
  });

  test("Settings provider-test failure never shows traceback, JSON body, or a key-shaped token", async ({
    page,
  }) => {
    await page.route("**/health", async (route) => {
      await route.fulfill(jsonResponse({ status: "ok" }));
    });
    await page.route("**/session/start", async (route) => {
      await route.fulfill(jsonResponse({ session_id: "error-surface-preview-session" }));
    });
    await page.route("**/provider/test", async (route) => {
      await route.fulfill(
        jsonResponse({
          ok: false,
          status: "failed",
          detail: LEAK_TEXT,
          error_category: "invalid_key_or_permission",
          retryable: false,
          status_code: 401,
        }),
      );
    });

    await openPreview(page, "settings", { live: "1", run: "error-surface" });
    await dispatchHostMessage(page, {
      type: "operation/status",
      payload: {
        tone: "error",
        message: LEAK_TEXT,
      },
    });

    const notice = page.locator(".notice.notice--error");
    await expect(notice).toBeVisible();
    const noticeText = await notice.innerText();
    assertNoLeak(noticeText);
    expect(noticeText.trim().length).toBeGreaterThan(0);
    expect(noticeText).toMatch(/Settings|try again|failed|hidden|connection/i);

    const pageText = await page.locator("body").innerText();
    assertNoLeak(pageText);
  });

  test("Plan change-candidate diffs never dump JSON, traceback, or a key-shaped token", async ({
    page,
  }) => {
    await openPreview(page, "plan");
    await patchPreviewBootstrap(page, {
      memory: {
        planChangeCandidates: [
          {
            id: "cand-leak-1",
            reason: "Shrink the next step after the last failed check.",
            status: "pending",
            diff: {
              title: "Keep the current slice",
              api_key: FAKE_KEY,
              dump: LEAK_TEXT,
            },
            impact: {
              next: "Open Plan and confirm or reject this candidate.",
              token: FAKE_KEY,
            },
          },
        ],
      },
    });

    const details = page.locator("details.coach-plan-view__details").first();
    await expect(details).toBeVisible();
    if (!(await details.evaluate((element) => element.open))) {
      await details.locator(":scope > summary").click();
    }
    const item = page.locator(".coach-plan-view__evidence-item").first();
    await expect(item).toBeVisible();
    await expect(item).toContainText("Shrink the next step after the last failed check.");
    await expect(item).toContainText("Keep the current slice");
    const visible = await item.innerText();
    assertNoLeak(visible);
    expect(visible).not.toMatch(/^\s*\{/);
  });
});
