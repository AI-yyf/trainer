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
  test("34: preserves identity and selection through upload, index, open, delete, and restore", async ({ page }) => {
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
    await expect(tree).toContainText("No resources yet");

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
    const resourceTreeItem = tree.getByRole("treeitem", { name: RESOURCE_TITLE, exact: true });
    await expect(resourceTreeItem).toBeVisible();
    await expect(resourceTreeItem.locator(".resources-library-tree__status")).toHaveText("Indexing");

    const indexStart = await actionCount(page);
    await library.getByRole("button", { name: "Refresh index", exact: true }).click();
    const indexAction = await waitForHostAction(
      page,
      indexStart,
      (action) =>
        action.type === "command/execute" && action.payload?.commandId === "trainer.resource.index",
    );
    expect(indexAction.payload).toMatchObject({ commandId: "trainer.resource.index" });
    expect(indexAction.payload.payload.__trainerResourceOperationId).toMatch(/^resource-operation-/);

    await sendHostMessage(page, {
      type: "state/patch",
      payload: { resources: [lifecycleResource("ready")], deletedResources: [] },
    });
    await expect(resourceTreeItem.locator(".resources-library-tree__status")).toHaveCount(0);

    await resourceTreeItem.click();
    await expect(resourceTreeItem).toHaveAttribute("aria-current", "true");
    const detail = library.getByRole("region", { name: RESOURCE_TITLE, exact: true });
    await expect(detail).toBeVisible();

    const openStart = await actionCount(page);
    await detail.getByRole("button", { name: `Open in VS Code: ${RESOURCE_TITLE}`, exact: true }).click();
    const openAction = await waitForHostAction(
      page,
      openStart,
      (action) => action.type === "resource/open",
    );
    expect(openAction).toEqual({ type: "resource/open", payload: { resourceId: RESOURCE_ID } });

    const resourceCheckbox = tree.getByRole("checkbox", {
      name: `Select resource: ${RESOURCE_TITLE}`,
      exact: true,
    });
    await resourceCheckbox.check();
    await expect(resourceTreeItem).toHaveAttribute("aria-checked", "true");
    await expect(library.locator(".resources-knowledge__selection-count")).toHaveAttribute(
      "aria-label",
      "Selected resources: 1",
    );

    const batchActions = library.locator(".resources-knowledge__batch-actions");
    if (!(await batchActions.evaluate((element) => element.open))) {
      await batchActions.locator(":scope > summary").click();
    }
    await library.getByRole("button", { name: "Delete selected resources", exact: true }).click();
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
    await expect(library.locator(".resources-knowledge__selection-count")).toHaveCount(0);
    await expect(library.getByRole("status")).toContainText("Moved 1 resource to Trash.");

    const trash = library.locator(".resources-knowledge__trash");
    await expect(trash).toContainText(RESOURCE_TITLE);
    const restoreStart = await actionCount(page);
    await trash.getByRole("button", { name: "Restore available resources", exact: true }).click();
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
    await expect(restoredTreeItem).toHaveAttribute("aria-checked", "false");
    await expect(library.getByRole("status")).toContainText("Restored 1 resource.");

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
