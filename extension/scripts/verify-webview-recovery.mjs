import { spawn, spawnSync } from "node:child_process";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const extensionDir = path.resolve(__dirname, "..");
const webviewDir = path.join(extensionDir, "webview");
const previewPath = "vscode-preview.html?view=coach&lang=en-US";
const previewViewport = { width: 420, height: 900 };
const waitTimeoutMs = 30_000;

let devServerProcess;
const devServerOutput = createRollingOutput();

try {
  const playwright = await loadPlaywright();
  const port = await findAvailablePort();
  devServerProcess = startWebviewDevServer(port);
  await waitForPreviewServer(port);

  const { browser, channel } = await launchPreviewBrowser(playwright);
  const context = await browser.newContext({ viewport: previewViewport });
  const page = await context.newPage();
  const previewUrl = `http://127.0.0.1:${port}/${previewPath}`;

  try {
    const cases = [];
    cases.push(await verifyOperationStatusBridge(page, previewUrl));
    cases.push(await verifyCompletedBootstrapRecovery(page, previewUrl));
    cases.push(await verifyRecoveredPatchRefresh(page, previewUrl));
    cases.push(await verifyErrorBootstrapRecovery(page, previewUrl));
    cases.push(await verifyInProgressBootstrapSilence(page, previewUrl));
    cases.push(await verifyInProgressBootstrapCoachRecovery(page, previewUrl));
    cases.push(await verifyInProgressPatchRefresh(page, previewUrl));
    cases.push(await verifyInteractiveCoachLoopProgression(page, previewUrl));
    cases.push(await verifyManualNoticePreserved(page, previewUrl));
    cases.push(await verifyStreamStartClearsRecoveredNotice(page, previewUrl));
    cases.push(await verifyRestoreTrainingView(page, previewUrl));
    cases.push(await verifyRestoreResourcesSandboxPreview(page, previewUrl));
    cases.push(await verifyPlanFirstViewport(page, previewUrl));

    console.log(
      JSON.stringify(
        {
          ok: true,
          previewUrl,
          browserChannel: channel,
          cases,
        },
        null,
        2,
      ),
    );
  } finally {
    await page.close();
    await context.close();
    await browser.close();
  }
} catch (error) {
  const detail = error instanceof Error ? error.message : String(error);
  const payload = {
    ok: false,
    error: detail,
    devServerOutput: devServerOutput.dump(),
  };
  console.error(JSON.stringify(payload, null, 2));
  process.exitCode = 1;
} finally {
  await stopWebviewDevServer(devServerProcess);
}

async function verifyOperationStatusBridge(page, previewUrl) {
  await resetPreviewPage(page, previewUrl);
  await injectPreviewHostMessage(page, {
    type: "operation/status",
    payload: { tone: "success", message: "hello notice bridge" },
  });
  const notice = await readNotice(page);
  assertEqual(notice.text, "hello notice bridge", "Preview bridge should surface operation status.");
  assertEqual(
    notice.className,
    "notice notice--success",
    "Preview bridge should preserve notice tone classes.",
  );
  return {
    id: "operation-status-bridge",
    notice,
  };
}

async function verifyCompletedBootstrapRecovery(page, previewUrl) {
  await resetPreviewPage(page, previewUrl);
  const payload = await buildPreviewBootstrap(page, {
    isStreaming: false,
    streamedContent: "Here is the grounded answer.",
    streamMessageId: "msg-complete",
    completionSummary: "Checked the workspace context first.",
    completionNextStep: "Apply the smallest verified patch.",
  });
  await injectPreviewHostMessage(page, { type: "bootstrap", payload });
  const notice = await readNotice(page);
  assertEqual(
    notice.text,
    "Checked the workspace context first. Next: Apply the smallest verified patch.",
    "Completed bootstrap should recover the coach loop summary notice.",
  );
  assertEqual(
    notice.className,
    "notice notice--success",
    "Completed bootstrap should recover as a success notice.",
  );
  return {
    id: "bootstrap-complete-recovery",
    notice,
  };
}

async function verifyRecoveredPatchRefresh(page, previewUrl) {
  await resetPreviewPage(page, previewUrl);
  const initialPayload = await buildPreviewBootstrap(page, {
    isStreaming: false,
    streamedContent: "Grounded answer.",
    streamMessageId: "msg-complete-initial",
    completionSummary: "Checked the workspace context first.",
    completionNextStep: "Apply the smallest verified patch.",
  });
  await injectPreviewHostMessage(page, { type: "bootstrap", payload: initialPayload });
  const before = await readNotice(page);

  const updatedPayload = await buildPreviewBootstrap(page, {
    isStreaming: false,
    streamedContent: "Grounded answer.",
    streamMessageId: "msg-complete-updated",
    completionSummary: "Re-checked the workspace context.",
    completionNextStep: "Verify the updated recovery path.",
  });
  await injectPreviewHostMessage(page, { type: "state/patch", payload: updatedPayload });
  const after = await readNotice(page);
  assertEqual(
    before.text,
    "Checked the workspace context first. Next: Apply the smallest verified patch.",
    "Initial recovered notice should match the first host snapshot.",
  );
  assertEqual(
    after.text,
    "Re-checked the workspace context. Next: Verify the updated recovery path.",
    "Recovered notice should follow newer host truth when it is still a recovered notice.",
  );
  return {
    id: "state-patch-refreshes-recovered-notice",
    before,
    after,
  };
}

async function verifyErrorBootstrapRecovery(page, previewUrl) {
  await resetPreviewPage(page, previewUrl);
  const payload = await buildPreviewBootstrap(page, {
    isStreaming: false,
    streamedContent: "",
    streamMessageId: "msg-error",
    streamError: "401 invalid_api_key",
  });
  await injectPreviewHostMessage(page, { type: "bootstrap", payload });
  const notice = await readNotice(page);
  assertEqual(
    notice.text,
    "The current API key is invalid or does not have access to this model. Open Settings and update the provider connection.",
    "Error bootstrap should recover the provider-access notice.",
  );
  assertEqual(
    notice.className,
    "notice notice--error",
    "Error bootstrap should recover as an error notice.",
  );
  return {
    id: "bootstrap-error-recovery",
    notice,
  };
}

async function verifyInProgressBootstrapSilence(page, previewUrl) {
  await resetPreviewPage(page, previewUrl);
  const payload = await buildPreviewBootstrap(page, {
    isStreaming: true,
    streamedContent: "Checking the workspace context...",
    streamMessageId: "msg-running",
    agentActivity: [],
  });
  await injectPreviewHostMessage(page, { type: "bootstrap", payload });
  const notice = await readNotice(page);
  assertEqual(notice.text, null, "In-progress bootstrap should not surface a completion notice.");
  return {
    id: "bootstrap-in-progress-silence",
    notice,
  };
}

async function verifyInProgressBootstrapCoachRecovery(page, previewUrl) {
  await resetPreviewPage(page, previewUrl);
  const payload = await buildPreviewBootstrap(page, {
    isStreaming: true,
    streamedContent: "Checking the workspace context...",
    streamMessageId: "msg-running-ui",
    agentStep: 1,
    agentActivity: [
      {
        id: "inspect-plan",
        name: "inspect_plan",
        status: "succeeded",
        result: { summary: "Plan anchor found." },
        step: 1,
      },
      {
        id: "recall-memory",
        name: "recall_memory",
        status: "running",
        step: 1,
      },
    ],
  });
  await injectPreviewHostMessage(page, { type: "bootstrap", payload });
  const notice = await readNotice(page);
  const surface = await readStreamingSurface(page);
  assertEqual(notice.text, null, "In-progress coach recovery should not surface a completion notice.");
  assertEqual(
    surface.hasStreamingBubble,
    true,
    "In-progress coach recovery should restore the streaming assistant bubble.",
  );
  assertIncludes(
    surface.messageText,
    "Checking the workspace context...",
    "Streaming recovery should keep the current streamed coach text visible.",
  );
  assertIncludes(
    surface.activityText,
    "Step 2",
    "Streaming recovery should restore the current agent step.",
  );
  assertIncludes(
    surface.activityText,
    "Inspect plan",
    "Streaming recovery should restore completed tool labels.",
  );
  assertIncludes(
    surface.activityText,
    "Recall memory",
    "Streaming recovery should restore running tool labels.",
  );
  assertIncludes(
    surface.activityText,
    "Plan anchor found.",
    "Streaming recovery should restore completed tool hints.",
  );
  assertIncludes(
    surface.activityText,
    "Checking context...",
    "Streaming recovery should keep the running-status footer attached to the coach stream.",
  );
  return {
    id: "bootstrap-in-progress-coach-recovery",
    notice,
    surface,
  };
}

async function verifyInProgressPatchRefresh(page, previewUrl) {
  await resetPreviewPage(page, previewUrl);
  const initialPayload = await buildPreviewBootstrap(page, {
    isStreaming: true,
    streamedContent: "Checking the workspace context...",
    streamMessageId: "msg-running-before-patch",
    agentStep: 1,
    agentActivity: [
      {
        id: "inspect-plan",
        name: "inspect_plan",
        status: "running",
        step: 1,
      },
    ],
  });
  await injectPreviewHostMessage(page, { type: "bootstrap", payload: initialPayload });
  const before = await readStreamingSurface(page);

  const updatedPayload = await buildPreviewBootstrap(page, {
    isStreaming: true,
    streamedContent: "I found the plan anchor and the current weak spot.",
    streamMessageId: "msg-running-after-patch",
    agentStep: 2,
    agentActivity: [
      {
        id: "inspect-plan",
        name: "inspect_plan",
        status: "succeeded",
        result: { summary: "Plan anchor found." },
        step: 2,
      },
      {
        id: "recall-memory",
        name: "recall_memory",
        status: "succeeded",
        result: { note: "Weak spot: recovery truth." },
        step: 2,
      },
      {
        id: "search-resources",
        name: "search_resources",
        status: "running",
        step: 2,
      },
    ],
  });
  await injectPreviewHostMessage(page, { type: "state/patch", payload: updatedPayload });
  const after = await readStreamingSurface(page);
  const notice = await readNotice(page);

  assertIncludes(
    before.messageText,
    "Checking the workspace context...",
    "Pre-patch streaming recovery should start from the initial host truth.",
  );
  assertIncludes(
    after.messageText,
    "I found the plan anchor and the current weak spot.",
    "Streaming state patches should refresh the visible coach stream body.",
  );
  assertIncludes(
    after.activityText,
    "Step 3",
    "Streaming state patches should refresh the visible agent step.",
  );
  assertIncludes(
    after.activityText,
    "Inspect plan",
    "Streaming state patches should preserve prior tool pills.",
  );
  assertIncludes(
    after.activityText,
    "Recall memory",
    "Streaming state patches should add newly completed tool pills.",
  );
  assertIncludes(
    after.activityText,
    "Search resources",
    "Streaming state patches should show newly running tool pills.",
  );
  assertIncludes(
    after.activityText,
    "Weak spot: recovery truth.",
    "Streaming state patches should refresh completed tool hints from host truth.",
  );
  assertIncludes(
    after.activityText,
    "Checking context...",
    "Streaming state patches should keep the running footer while work is still active.",
  );
  assertEqual(
    notice.text,
    null,
    "Streaming state patches should not surface a completion notice while the loop is still running.",
  );
  return {
    id: "state-patch-refreshes-in-progress-coach-ui",
    before,
    after,
    notice,
  };
}

async function verifyInteractiveCoachLoopProgression(page, previewUrl) {
  await resetPreviewPage(page, previewUrl);
  await injectPreviewHostMessage(page, {
    type: "stream/start",
    payload: { messageId: "msg-live-loop" },
  });
  await injectPreviewHostMessage(page, {
    type: "stream/step",
    payload: { index: 0 },
  });
  await injectPreviewHostMessage(page, {
    type: "stream/chunk",
    payload: { chunk: "Checking the workspace context..." },
  });
  await injectPreviewHostMessage(page, {
    type: "stream/tool_call",
    payload: {
      id: "inspect-plan",
      name: "inspect_plan",
      arguments: { target: "current plan" },
      step: 0,
    },
  });
  const runningSurface = await readStreamingSurface(page);
  assertEqual(
    runningSurface.hasStreamingBubble,
    true,
    "A live coach loop should show the streaming assistant bubble after stream/start.",
  );
  assertIncludes(
    runningSurface.messageText,
    "Checking the workspace context...",
    "A live coach loop should append streamed content into the assistant bubble.",
  );
  assertIncludes(
    runningSurface.activityText,
    "Step 1",
    "A live coach loop should surface the current tool step.",
  );
  assertIncludes(
    runningSurface.activityText,
    "Inspect plan",
    "A live coach loop should surface running tool labels.",
  );
  assertIncludes(
    runningSurface.activityText,
    "Checking context...",
    "A live coach loop should show the running footer while work is active.",
  );

  await injectPreviewHostMessage(page, {
    type: "stream/tool_result",
    payload: {
      id: "inspect-plan",
      name: "inspect_plan",
      ok: true,
      result: { summary: "Plan anchor found." },
      step: 0,
    },
  });
  await injectPreviewHostMessage(page, {
    type: "stream/tool_call",
    payload: {
      id: "recall-memory",
      name: "recall_memory",
      arguments: { scope: "project" },
      step: 0,
    },
  });
  await injectPreviewHostMessage(page, {
    type: "stream/chunk",
    payload: { chunk: " I found the plan anchor." },
  });
  const progressedSurface = await readStreamingSurface(page);
  assertIncludes(
    progressedSurface.messageText,
    "Checking the workspace context... I found the plan anchor.",
    "A live coach loop should keep streaming text cumulative between chunks.",
  );
  assertIncludes(
    progressedSurface.activityText,
    "Plan anchor found.",
    "A live coach loop should surface completed tool hints after tool results arrive.",
  );
  assertIncludes(
    progressedSurface.activityText,
    "Recall memory",
    "A live coach loop should append later tool calls into the same activity strip.",
  );

  await injectPreviewHostMessage(page, {
    type: "stream/complete",
    payload: {
      tokens: 256,
      summary: "Checked the workspace context first.",
      nextStep: "Apply the smallest verified patch.",
      toolCount: 2,
      agentic: true,
    },
  });
  const after = await readStreamingSurface(page);
  const notice = await readNotice(page);
  assertEqual(
    after.hasStreamingBubble,
    false,
    "Completing the coach loop should remove the streaming bubble.",
  );
  assertEqual(
    notice.text,
    "Checked the workspace context first. Next: Apply the smallest verified patch.",
    "Completing the coach loop should surface the coach summary notice.",
  );
  assertEqual(
    notice.className,
    "notice notice--success",
    "Completing the coach loop should surface a success notice.",
  );
  return {
    id: "interactive-coach-loop-progression",
    runningSurface,
    progressedSurface,
    after,
    notice,
  };
}

async function verifyManualNoticePreserved(page, previewUrl) {
  await resetPreviewPage(page, previewUrl);
  await injectPreviewHostMessage(page, {
    type: "operation/status",
    payload: { tone: "success", message: "Provider settings saved." },
  });
  const payload = await buildPreviewBootstrap(page, {
    isStreaming: false,
    streamedContent: "Grounded answer.",
    streamMessageId: "msg-patch-complete",
    completionSummary: "Checked the workspace context first.",
    completionNextStep: "Apply the smallest verified patch.",
  });
  await injectPreviewHostMessage(page, { type: "state/patch", payload });
  const notice = await readNotice(page);
  assertEqual(
    notice.text,
    "Provider settings saved.",
    "Manual notices should not be overwritten by recovered host patches.",
  );
  return {
    id: "manual-notice-preserved",
    notice,
  };
}

async function verifyStreamStartClearsRecoveredNotice(page, previewUrl) {
  await resetPreviewPage(page, previewUrl);
  const payload = await buildPreviewBootstrap(page, {
    isStreaming: false,
    streamedContent: "Grounded answer.",
    streamMessageId: "msg-recovered-before-start",
    completionSummary: "Checked the workspace context first.",
    completionNextStep: "Apply the smallest verified patch.",
  });
  await injectPreviewHostMessage(page, { type: "bootstrap", payload });
  const before = await readNotice(page);
  await injectPreviewHostMessage(page, {
    type: "stream/start",
    payload: { messageId: "msg-new-stream" },
  });
  const after = await readNotice(page);
  assertEqual(
    before.text,
    "Checked the workspace context first. Next: Apply the smallest verified patch.",
    "Recovered notice should exist before a new stream starts.",
  );
  assertEqual(after.text, null, "Starting a new stream should clear the recovered notice.");
  return {
    id: "stream-start-clears-recovered-notice",
    before,
    after,
  };
}

async function verifyRestoreTrainingView(page, previewUrl) {
  await resetPreviewPage(page, previewUrl);
  await injectPreviewHostMessage(page, {
    type: "ui/restoreView",
    payload: {
      activeView: "practice",
      trainingSubmode: "practice",
      trainingRestoreTarget: "next_hop",
      focusArea: "provider truth",
      currentStageTitle: "Verification",
      latestSummary: "Carry the verified result back to coach.",
      latestTrainingNextHop: {
        cardTitle: "Return to provider truth",
        summary: "Re-open the smallest provider check before widening scope.",
        continueIn: "training",
        status: "surfaced",
        targetId: "card-provider-truth",
      },
    },
  });
  await page.waitForSelector(".training-pane", { timeout: waitTimeoutMs });
  const surface = await readTrainingRestoreSurface(page);
  assertEqual(
    surface.heading,
    "Return to provider truth",
    "Restoring a training view should surface the restored training title.",
  );
  assertEqual(
    surface.cardTitle,
    "Return to provider truth",
    "Restoring a training next hop should surface the restored focus card title.",
  );
  assertEqual(
    surface.cardDetail,
    "Re-open the smallest provider check before widening scope.",
    "Restoring a training next hop should surface the restored focus card detail.",
  );
  assertIncludes(
    surface.cardMeta,
    "provider truth",
    "Restoring a training next hop should keep the focus area visible in the restored card meta.",
  );
  return {
    id: "restore-training-view",
    surface,
  };
}

async function verifyRestoreResourcesSandboxPreview(page, previewUrl) {
  await resetPreviewPage(page, previewUrl);
  await injectPreviewHostMessage(page, {
    type: "ui/restoreView",
    payload: {
      activeView: "resources",
      resourceSurface: "sandbox",
      focusArea: "research sandbox",
      sandboxPath: "/workspace/server/app/research/web_search.py",
      previewPath: "/preview/resources/web-search",
      latestSummary: "Preview the resource-linked sandbox before reusing it.",
    },
  });
  await page.waitForSelector(".resources-pane", { timeout: waitTimeoutMs });
  const surface = await readResourcesRestoreSurface(page);
  assertEqual(
    surface.heading,
    "Unified library",
    "Restoring a resources view should land on the resources library heading.",
  );
  assertEqual(
    surface.cardTitle,
    "Sandbox preview restored",
    "Restoring a sandbox preview should surface the restored sandbox title.",
  );
  assertEqual(
    surface.cardDetail,
    "/preview/resources/web-search",
    "Restoring a sandbox preview should surface the preview path as the first visible detail.",
  );
  assertIncludes(
    surface.cardMeta,
    "research sandbox",
    "Restoring a sandbox preview should keep the focus area visible in the spotlight meta.",
  );
  assertIncludes(
    surface.cardMeta,
    "/workspace/server/app/research/web_search.py",
    "Restoring a sandbox preview should keep the sandbox path visible in the spotlight meta.",
  );
  return {
    id: "restore-resources-sandbox-preview",
    surface,
  };
}

async function verifyPlanFirstViewport(page, previewUrl) {
  const planPreviewUrl = previewUrl.replace("view=coach", "view=plan").replace("lang=en-US", "lang=en-US&scenario=ready");
  const initialViewport = page.viewportSize() ?? previewViewport;
  const widths = [300, 360];
  const surfaces = [];

  try {
    for (const width of widths) {
      await page.setViewportSize({ width, height: 800 });
      await resetPreviewPage(page, planPreviewUrl);
      await page.waitForSelector('[data-plan-primary="true"]', { timeout: waitTimeoutMs });
      const surface = await readPlanFirstViewport(page);
      const visibleFactIds = surface.facts.filter((fact) => fact.visible && !fact.insideDetails).map((fact) => fact.id);

      assertIncludes(
        visibleFactIds.join(","),
        "next",
        `Plan first viewport at ${width}px must expose the current next move without expanding More.`,
      );
      assertEqual(
        surface.compactVerificationVisible,
        true,
        `Plan first viewport at ${width}px must keep the current verification line visible.`,
      );
      assertEqual(
        surface.compactPrimaryActionVisible,
        true,
        `Plan first viewport at ${width}px must keep one primary action visible.`,
      );
      assertEqual(
        surface.compactPrimaryActionDisabled,
        false,
        `Plan first viewport at ${width}px must keep the primary action executable.`,
      );
      assertEqual(
        surface.compactVerificationIsClipped,
        false,
        `Plan verification text at ${width}px must wrap instead of clipping.`,
      );
      surfaces.push({ width, ...surface });
    }
  } finally {
    await page.setViewportSize(initialViewport);
  }

  return {
    id: "plan-first-viewport",
    surfaces,
  };
}

async function resetPreviewPage(page, previewUrl) {
  await page.goto(previewUrl, { waitUntil: "networkidle" });
  await page.waitForFunction(
    () => typeof window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__ === "function",
    undefined,
    { timeout: waitTimeoutMs },
  );
  await page.waitForTimeout(250);
}

async function buildPreviewBootstrap(page, streamingState) {
  return await page.evaluate((state) => {
    const payload = structuredClone(window.__TRAINER_BOOTSTRAP__ ?? {});
    payload.streamingState = state;
    return payload;
  }, streamingState);
}

async function injectPreviewHostMessage(page, message) {
  await page.evaluate((payload) => {
    const applyHostMessage = window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__;
    if (typeof applyHostMessage !== "function") {
      throw new Error("Trainer preview host-message bridge is unavailable.");
    }
    applyHostMessage(payload);
  }, message);
  await page.waitForTimeout(200);
}

async function readNotice(page) {
  return await page.evaluate(() => ({
    text: document.querySelector(".notice")?.textContent?.trim() ?? null,
    className: document.querySelector(".notice")?.className ?? null,
  }));
}

async function readStreamingSurface(page) {
  return await page.evaluate(() => {
    const normalize = (value) => value?.replace(/\s+/g, " ").trim() ?? null;
    const streamingBubble = document.querySelector('[data-message-id="streaming"]');
    const activityStrip = document.querySelector(
      ".coach-conversation-view__item:last-child .agent-activity-strip",
    );
    return {
      hasStreamingBubble: Boolean(streamingBubble),
      messageText: normalize(streamingBubble?.textContent),
      activityText: normalize(activityStrip?.textContent),
    };
  });
}

async function readTrainingRestoreSurface(page) {
  return await page.evaluate(() => {
    const normalize = (value) => value?.replace(/\s+/g, " ").trim() ?? null;
    const pane = document.querySelector(".training-pane");
    const currentCard = pane?.querySelector(".training-current__card-stack");
    const nextHop = pane?.querySelector('[data-training-next-hop="true"]');
    const restoredCardDetail =
      currentCard?.querySelector('p[data-view-why]')?.textContent?.trim() ??
      currentCard?.querySelector('[data-training-card-fact="current"] p')?.textContent?.trim() ??
      null;
    return {
      heading: normalize(pane?.querySelector(".training-current h2")?.textContent),
      cardTitle: normalize(currentCard?.querySelector("h2")?.textContent),
      cardDetail: normalize(nextHop?.querySelector("strong")?.textContent ?? restoredCardDetail),
      cardMeta: normalize(nextHop?.textContent ?? currentCard?.querySelector("h2")?.textContent),
    };
  });
}

async function readResourcesRestoreSurface(page) {
  return await page.evaluate(() => {
    const normalize = (value) => value?.replace(/\s+/g, " ").trim() ?? null;
    const pane = document.querySelector(".resources-pane");
    const spotlight = pane?.querySelector(".resources-inline-context");
    return {
      heading: normalize(pane?.querySelector(".workbench-pane__heading h2")?.textContent),
      cardTitle: normalize(spotlight?.querySelector(".resources-inline-context__title")?.textContent),
      cardDetail: normalize(
        spotlight?.querySelector("p:not(.resources-inline-context__title):not(.resources-inline-context__meta)")?.textContent,
      ),
      cardMeta: normalize(spotlight?.querySelector(".resources-inline-context__meta")?.textContent),
    };
  });
}

async function readPlanFirstViewport(page) {
  return await page.evaluate(() => {
    const primary = document.querySelector('[data-plan-primary="true"]');
    const facts = ["next", "stage", "why", "verify"].map((id) => {
      const element = primary?.querySelector(`[data-plan-fact="${id}"]`);
      const rect = element?.getBoundingClientRect();
      return {
        id,
        visible: Boolean(rect && rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight),
        insideDetails: Boolean(element?.closest("details")),
        text: element?.textContent?.replace(/\s+/g, " ").trim() ?? null,
      };
    });
    const compactVerification = primary?.querySelector('.coach-plan-view__now-done');
    const compactPrimaryAction = primary?.querySelector(
      '.coach-plan-view__compact-primary-action button',
    );

    return {
      facts,
      compactVerificationVisible: Boolean(
        compactVerification &&
          (() => {
            const rect = compactVerification.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight;
          })(),
      ),
      compactPrimaryActionVisible: Boolean(
        compactPrimaryAction &&
          (() => {
            const rect = compactPrimaryAction.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight;
          })(),
      ),
      compactPrimaryActionDisabled: compactPrimaryAction?.hasAttribute('disabled') ?? null,
      compactVerificationIsClipped: Boolean(
        compactVerification && compactVerification.scrollHeight > compactVerification.clientHeight + 1,
      ),
    };
  });
}

async function loadPlaywright() {
  try {
    return await import("playwright");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(
      [
        "Playwright is not available for verify-webview-recovery.",
        "Run this script through npm exec so the temporary package is available:",
        "npm exec --yes --package playwright -- node ./scripts/verify-webview-recovery.mjs",
        message,
      ].join("\n"),
    );
  }
}

async function launchPreviewBrowser(playwright) {
  const requestedChannel = process.env.TRAINER_RECOVERY_BROWSER_CHANNEL?.trim();
  const channels = requestedChannel ? [requestedChannel] : ["msedge", "chrome"];
  const failures = [];
  for (const channel of channels) {
    try {
      const browser = await playwright.chromium.launch({
        channel,
        headless: true,
      });
      return { browser, channel };
    } catch (error) {
      failures.push(
        `${channel}: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }
  throw new Error(
    [
      "Could not launch a system Chromium browser for webview recovery verification.",
      "Tried channels:",
      ...failures.map((item) => `- ${item}`),
      "Set TRAINER_RECOVERY_BROWSER_CHANNEL to a valid Playwright channel if your system uses a different browser.",
    ].join("\n"),
  );
}

function startWebviewDevServer(port) {
  const child =
    process.platform === "win32"
      ? spawn(
          process.env.ComSpec ?? "cmd.exe",
          ["/d", "/c", `npm run dev -- --host 127.0.0.1 --port ${port}`],
          {
            cwd: webviewDir,
            env: {
              ...process.env,
              BROWSER: "none",
            },
            stdio: ["ignore", "pipe", "pipe"],
          },
        )
      : spawn(
          "npm",
          ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(port)],
          {
            cwd: webviewDir,
            env: {
              ...process.env,
              BROWSER: "none",
            },
            stdio: ["ignore", "pipe", "pipe"],
          },
        );
  child.stdout?.setEncoding("utf8");
  child.stderr?.setEncoding("utf8");
  child.stdout?.on("data", (chunk) => devServerOutput.pushStdout(chunk));
  child.stderr?.on("data", (chunk) => devServerOutput.pushStderr(chunk));
  child.on("exit", (code, signal) => {
    if (code !== 0 && signal == null) {
      devServerOutput.pushStderr(`webview dev server exited with code ${code}`);
    }
  });
  return child;
}

async function waitForPreviewServer(port) {
  const deadline = Date.now() + waitTimeoutMs;
  const url = `http://127.0.0.1:${port}/${previewPath}`;
  while (Date.now() < deadline) {
    if (devServerProcess?.exitCode != null) {
      throw new Error(
        `Webview dev server exited early.\n${JSON.stringify(devServerOutput.dump(), null, 2)}`,
      );
    }
    try {
      const response = await fetch(url, { method: "GET" });
      if (response.ok) {
        return;
      }
    } catch {
      // keep polling until the server is ready
    }
    await sleep(250);
  }
  throw new Error(
    `Timed out waiting for webview preview server on ${url}.\n${JSON.stringify(devServerOutput.dump(), null, 2)}`,
  );
}

async function findAvailablePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close(() => reject(new Error("Could not determine a free localhost port.")));
        return;
      }
      const { port } = address;
      server.close((error) => {
        if (error) {
          reject(error);
          return;
        }
        resolve(port);
      });
    });
  });
}

async function stopWebviewDevServer(child) {
  if (!child || child.exitCode != null) {
    return;
  }
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(child.pid), "/t", "/f"], {
      stdio: "ignore",
    });
    return;
  }
  child.kill("SIGTERM");
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(
      `${message}\nExpected: ${JSON.stringify(expected)}\nReceived: ${JSON.stringify(actual)}`,
    );
  }
}

function assertIncludes(actual, expected, message) {
  if (typeof actual !== "string" || !actual.includes(expected)) {
    throw new Error(
      `${message}\nExpected to include: ${JSON.stringify(expected)}\nReceived: ${JSON.stringify(actual)}`,
    );
  }
}

function createRollingOutput(limit = 60) {
  const stdout = [];
  const stderr = [];
  return {
    pushStdout(chunk) {
      pushLines(stdout, chunk, limit);
    },
    pushStderr(chunk) {
      pushLines(stderr, chunk, limit);
    },
    dump() {
      return {
        stdout,
        stderr,
      };
    },
  };
}

function pushLines(target, chunk, limit) {
  const lines = String(chunk)
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter(Boolean);
  for (const line of lines) {
    target.push(line);
    if (target.length > limit) {
      target.shift();
    }
  }
}

async function sleep(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}
