const { test, expect } = require("playwright/test");

const RESOURCE_ID = "resource-lifecycle-42";
const RESOURCE_TITLE = "Trainer resource lifecycle.md";

function hostBootstrap(resources, deletedResources) {
  return {
    workspaceName: "Resource lifecycle workspace",
    sessionLabel: "Resource lifecycle",
    connection: {
      state: "connected",
      provider: {
        name: "Lifecycle provider",
        model: "lifecycle-model",
        capabilities: {
          chat: true,
          responses: false,
          vision: false,
          embeddings: false,
          tools: false,
          jsonSchema: false,
          structuredOutput: false,
          streaming: false,
        },
      },
    },
    providerConfig: {
      configured: true,
      name: "Lifecycle provider",
      baseUrl: "https://provider.invalid/v1",
      model: "lifecycle-model",
      apiKeyConfigured: true,
      capabilities: {
        chat: true,
        responses: false,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: false,
        structuredOutput: false,
        streaming: false,
      },
      availableModels: ["lifecycle-model"],
      modelListStatus: "ready",
    },
    resources,
    deletedResources,
    memory: {
      sandboxState: {
        authority: {
          authorityScope: "trainer_sandbox",
          resourceWriteAllowed: true,
          resourceWriteEvidence: {
            operation: "write",
            scope: "trainer_sandbox",
            allowed: true,
          },
        },
      },
    },
  };
}

function lifecycleResource(status) {
  return {
    id: RESOURCE_ID,
    title: RESOURCE_TITLE,
    kind: "markdown",
    status,
    summary: "A compact checklist for preserving resource identity through Trainer actions.",
    source: "workspace://resources/Trainer resource lifecycle.md",
    collectionPath: "Learning notes",
    tags: ["lifecycle", "resources"],
    trustState: "workspace",
    freshness: "fresh",
    previewTier: "rich",
    canInjectTrainingCard: true,
  };
}

async function hostActions(page) {
  return page.evaluate(() => window.__TRAINER_E2E_HOST_ACTIONS__ ?? []);
}

async function actionCount(page) {
  return (await hostActions(page)).length;
}

async function waitForHostAction(page, startIndex, predicate) {
  let matched;
  await expect
    .poll(async () => {
      const actions = await hostActions(page);
      matched = actions.slice(startIndex).find(predicate);
      return Boolean(matched);
    })
    .toBe(true);
  return matched;
}

async function sendHostMessage(page, message) {
  await page.evaluate((nextMessage) => {
    window.postMessage(nextMessage, window.location.origin);
  }, message);
}

async function sendResourceOperationStatus(page, kind, requestId, message) {
  await sendHostMessage(page, {
    type: "operation/status",
    payload: {
      tone: "success",
      message: `[[trainer-resource-operation:${kind}:${requestId}]] ${message}`,
    },
  });
}

test.describe("Trainer Resources lifecycle through the VS Code host bridge", () => {
  test("ranked results open and send the same current resource and line", async ({ page }) => {
    await page.addInitScript(() => {
      window.__TRAINER_E2E_HOST_ACTIONS__ = [];
      window.acquireVsCodeApi = () => ({
        getState: () => ({
          activeView: "resources",
          composerLanguage: "en-US",
          composerSendPreference: "stay",
        }),
        setState: () => undefined,
        postMessage: (message) => window.__TRAINER_E2E_HOST_ACTIONS__.push(message),
      });
    });
    await page.goto("/");
    await waitForHostAction(page, 0, (action) => action.type === "request/bootstrap");
    const a = { ...lifecycleResource("ready"), title: "A queue notes.md" };
    const b = { ...a, id: "resource-rotation", title: "B rotation notes.md", versionId: "rv-b" };
    await sendHostMessage(page, { type: "bootstrap", payload: hostBootstrap([a, b], []) });

    const rowA = page.getByRole("treeitem", { name: a.title, exact: true });
    await rowA.press("Enter");
    const anchor = page.locator("[data-dock-anchor]");
    await expect(anchor).toContainText(a.title);

    const start = await actionCount(page);
    const search = page.locator(".resources-knowledge__search input");
    await search.fill("owner");
    const action = await waitForHostAction(page, start, (item) =>
      item.type === "command/execute" && item.payload.commandId === "trainer.resource.search",
    );
    await sendHostMessage(page, {
      type: "state/patch",
      payload: {
        resourceSearch: {
          requestId: action.payload.payload.requestId,
          query: "owner",
          total: 2,
          filters: {},
          hits: [
            { ...b, location: { line_start: 3 }, snippet: "The <mark>owner</mark> is Amber Compass." },
            a,
          ],
        },
      },
    });
    const results = page.locator(".resources-search-results");
    await expect(results.getByRole("button").first()).toContainText(b.title);
    await expect(results).toContainText("The owner is Amber Compass.");
    await results.getByRole("button").first().click();
    const opened = await waitForHostAction(page, start, (item) => item.type === "resource/open");
    expect(opened.payload).toEqual({ resourceId: b.id, line: 3 });
    await expect(anchor).toContainText("B rotation notes.md · L3");

    const composer = page.locator("#coach-composer");
    await composer.fill("Who is the owner in this document?");
    await page.locator(".composer__send").click();
    const sent = await waitForHostAction(page, start, (item) => item.type === "session/sendStreamMessage");
    expect(sent.payload).toMatchObject({
      resourceIds: [b.id],
      resourceComposerIntent: { currentResource: { resourceId: b.id, versionId: "rv-b", line: 3 } },
    });
    await expect(anchor).toBeVisible();
    await anchor.getByRole("button", { name: "Clear", exact: true }).click();
    await expect(anchor).toHaveCount(0);
    await expect(results.getByRole("button").first()).not.toHaveAttribute("aria-current", "true");
  });

  test("34: preserves resource identity through upload, open, delete, and per-item restore", async ({ page }) => {
    const consoleErrors = [];
    page.on("console", (message) => {
      if (message.type() === "error") {
        consoleErrors.push(message.text());
      }
    });

    await page.addInitScript(() => {
      const persistedState = {
        themePreference: "dark",
        activeView: "resources",
        composerLanguage: "en-US",
        composerAnswerMode: "auto",
        teachingStyle: "auto",
        resourceSearchMode: "lexical",
        includeCurrentFile: true,
        includeSelection: true,
        includeDiagnostics: true,
        includeRelatedFiles: true,
        contextDetail: "balanced",
        followCurrentFile: true,
        coachDefaults: {
          memoryScope: "project",
          workingSetMode: "balanced",
          reviewCadence: "steady",
          reviewReminderMode: "due",
          workspaceMemoryToggles: { decisions: true, patterns: true, resources: true },
        },
        composerDraft: "",
      };
      window.__TRAINER_E2E_HOST_ACTIONS__ = [];
      window.acquireVsCodeApi = () => ({
        getState: () => persistedState,
        setState: () => undefined,
        postMessage: (message) => {
          window.__TRAINER_E2E_HOST_ACTIONS__.push(JSON.parse(JSON.stringify(message)));
        },
      });
    });

    await page.setViewportSize({ width: 360, height: 900 });
    await page.goto("/");
    await expect(page.locator("body")).toBeVisible();

    const bootstrapAction = await waitForHostAction(page, 0, (action) => action.type === "request/bootstrap");
    expect(bootstrapAction).toEqual({ type: "request/bootstrap" });
    await sendHostMessage(page, {
      type: "bootstrap",
      payload: hostBootstrap([], []),
    });

    const library = page.getByRole("region", { name: "Unified library", exact: true });
    const tree = library.getByRole("tree", { name: "Unified library", exact: true });
    await expect(library).toBeVisible();
    await expect(library).toContainText("No resources yet");
    await expect(library.getByRole("treeitem")).toHaveCount(0);
    await expect(tree.getByRole("treeitem")).toHaveCount(0);

    const importStart = await actionCount(page);
    await library.getByRole("button", { name: "Add resource", exact: true }).click();
    const importMenu = library.getByRole("menu", { name: "Add resource", exact: true });
    await expect(importMenu).toBeVisible();
    await importMenu.getByRole("menuitem", { name: "Add files", exact: true }).click();
    const uploadAction = await waitForHostAction(
      page,
      importStart,
      (action) => action.type === "resource/upload",
    );
    expect(uploadAction).toMatchObject({ type: "resource/upload", payload: { mode: "files" } });
    expect(uploadAction.payload.__trainerResourceOperationId).toMatch(/^resource-upload-/);

    await sendHostMessage(page, {
      type: "state/patch",
      payload: { resources: [lifecycleResource("indexing")], deletedResources: [] },
    });
    const resourceTreeItem = page.getByRole("treeitem", { name: RESOURCE_TITLE, exact: true, includeHidden: true });
    await expect(resourceTreeItem).toBeVisible();
    // Rows are plain entries now: no checkbox, no per-row index-status badge,
    // and no multi-select on the tree.
    await expect(tree).not.toHaveAttribute("aria-multiselectable");
    await expect(tree.getByRole("checkbox")).toHaveCount(0);
    await expect(resourceTreeItem.locator(".resources-library-tree__status")).toHaveCount(0);

    await sendHostMessage(page, {
      type: "state/patch",
      payload: { resources: [lifecycleResource("ready")], deletedResources: [] },
    });
    await expect(resourceTreeItem.locator(".resources-library-tree__status")).toHaveCount(0);

    // Space and Enter both open the source file through the host. No Reader
    // detail page is rendered, and the tree row stays in place.
    const openStart = await actionCount(page);
    await resourceTreeItem.press(" ");
    const openAction = await waitForHostAction(
      page,
      openStart,
      (action) => action.type === "resource/open",
    );
    expect(openAction).toEqual({ type: "resource/open", payload: { resourceId: RESOURCE_ID } });
    await expect(page.locator("[data-template=ResourceReader]")).toHaveCount(0);
    await expect(resourceTreeItem).toHaveAttribute("aria-current", "true");

    // Delete lives in the compact row menu next to the source-open action.
    const deleteMenuTrigger = resourceTreeItem.getByRole("button", {
      name: `File actions: ${RESOURCE_TITLE}`,
      exact: true,
    });
    await expect(deleteMenuTrigger).toBeVisible();
    await deleteMenuTrigger.click();
    const fileActions = page.getByRole("menu", { name: "File actions", exact: true });
    await expect(fileActions).toBeVisible();
    await fileActions.getByRole("menuitem", { name: "Delete resource", exact: true }).click();
    const deleteConfirmation = library.getByRole("alertdialog");
    await expect(deleteConfirmation).toBeVisible();

    const deleteStart = await actionCount(page);
    await deleteConfirmation.getByRole("button", { name: "Confirm", exact: true }).click();
    const deleteAction = await waitForHostAction(
      page,
      deleteStart,
      (action) =>
        action.type === "command/execute" && action.payload?.commandId === "trainer.resource.delete",
    );
    expect(deleteAction.payload.payload.resourceIds).toEqual([RESOURCE_ID]);
    const deleteRequestId = deleteAction.payload.payload.__trainerResourceOperationId;
    expect(deleteRequestId).toMatch(/^resource-operation-/);

    await sendHostMessage(page, {
      type: "state/patch",
      payload: {
        resources: [],
        deletedResources: [
          {
            resourceId: RESOURCE_ID,
            title: RESOURCE_TITLE,
            collectionPath: "Learning notes",
            recoverable: true,
          },
        ],
      },
    });
    await sendResourceOperationStatus(page, "delete", deleteRequestId, "Moved 1 resource to Trash.");
    await expect(tree.getByRole("treeitem", { name: RESOURCE_TITLE, exact: true })).toHaveCount(0);
    await expect(library.getByRole("status").filter({ hasText: /Moved|Restored/ })).toContainText("Moved 1 resource to Trash.");

    // Trash restores per item now; there is no bulk "Restore available resources".
    const trash = library.locator(".resources-knowledge__trash");
    await expect(trash).toContainText(RESOURCE_TITLE);
    await expect(trash.getByRole("button", { name: "Restore available resources", exact: true })).toHaveCount(0);
    const restoreStart = await actionCount(page);
    await trash.getByRole("button", { name: `Restore resource: ${RESOURCE_TITLE}`, exact: true }).click();
    const restoreAction = await waitForHostAction(
      page,
      restoreStart,
      (action) =>
        action.type === "command/execute" && action.payload?.commandId === "trainer.resource.restore",
    );
    expect(restoreAction.payload.payload.resourceIds).toEqual([RESOURCE_ID]);
    const restoreRequestId = restoreAction.payload.payload.__trainerResourceOperationId;
    expect(restoreRequestId).toMatch(/^resource-operation-/);

    await sendHostMessage(page, {
      type: "state/patch",
      payload: { resources: [lifecycleResource("ready")], deletedResources: [] },
    });
    await sendResourceOperationStatus(page, "restore", restoreRequestId, "Restored 1 resource.");
    const restoredTreeItem = tree.getByRole("treeitem", { name: RESOURCE_TITLE, exact: true });
    await expect(restoredTreeItem).toBeVisible();
    await expect(library.getByRole("status").filter({ hasText: /Moved|Restored/ })).toContainText("Restored 1 resource.");

    const restoredOpenStart = await actionCount(page);
    await restoredTreeItem.press("Enter");
    const restoredOpenAction = await waitForHostAction(
      page,
      restoredOpenStart,
      (action) => action.type === "resource/open",
    );
    expect(restoredOpenAction).toEqual({ type: "resource/open", payload: { resourceId: RESOURCE_ID } });

    const widths = await page.evaluate(() => ({
      bodyClientWidth: document.body.clientWidth,
      bodyScrollWidth: document.body.scrollWidth,
      rootClientWidth: document.documentElement.clientWidth,
      rootScrollWidth: document.documentElement.scrollWidth,
    }));
    expect(widths.bodyScrollWidth).toBeLessThanOrEqual(widths.bodyClientWidth + 1);
    expect(widths.rootScrollWidth).toBeLessThanOrEqual(widths.rootClientWidth + 1);
    expect(consoleErrors, `Console errors:\n${consoleErrors.join("\n")}`).toEqual([]);
  });
});
