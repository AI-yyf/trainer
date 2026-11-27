import { useCallback, useEffect, useMemo, useRef, type MutableRefObject } from "react";

import { trainerCommands } from "../../../../shared/src/commands";
import { sanitizeErrorSurfaceText } from "../../../../shared/src/errorSurfaceSanitizer";
import type {
  ResourceVersionCheckResult,
  ResourceVersionPin,
  TrainingPlanBinding,
} from "../../../../shared/src/models";
import type { TrainerOperationMessage } from "../../../../shared/src/protocol";
import { researchBriefResourceIds } from "../../../../shared/src/researchBrief";
import type { ResourceSearchMode } from "../../../../shared/src/resourceSearch";
import type {
  ResourceCaptureFocusOption,
  ResourceCaptureInput,
  ResourceMutationOutcome,
  ResourceOrganizeInput,
  ResourceSearchRequest,
} from "../components/resources/ResourcesWorkbenchView";
import { goalTitleFromConversation } from "../lib/coachGoalTitle";
import { appUiCopy } from "../lib/i18n/appUiCopy";
import {
  parseLibraryFolderTree,
  type LibraryFolderHostAnswer,
  type LibraryFolderListResult,
} from "../lib/libraryFolders";
import {
  recoverableFailureMessage,
  type OperationMessageSurface,
} from "../lib/operationMessageGovernance";
import { coachReplyMarkdown } from "../lib/shareUtils";
import type {
  ActiveWorkbenchView,
  BootstrapData,
  ComposerLanguage,
  ConversationMessage,
  HostMessage,
  LibraryMigrationHostAnswer,
  LibraryMigrationSummary,
  PlanStage,
  ResourceTrainingHandoffResult,
} from "../lib/types";
import { useHostOperationResolver } from "../lib/useHostOperationResolver";
import { postMessage } from "../lib/vscode";
import {
  CAPTURE_CONFIRMATION_TIMEOUT_MS,
  LIBRARY_FOLDER_OPERATION_TIMEOUT_MS,
  LIBRARY_MIGRATION_TIMEOUT_MS,
  ORGANIZE_CONFIRMATION_TIMEOUT_MS,
  RESOURCE_OPERATION_TIMEOUT_MS,
  RESOURCE_TRAINING_HANDOFF_TIMEOUT_MS,
  browserFileSupported,
  browserUploadLooksLikeFolder,
  captureTargetKind,
  describeSidecarFailure,
  exportDownloadName,
  loadBrowserPreviewModule,
  parseResourceOperationStatus,
  readBrowserFiles,
  triggerLocalDownload,
  waitForCapturedResource,
  waitForOrganizedResource,
  type PendingResourceOperation,
  type PendingResourceTrainingHandoff,
  type ResourceMutationOperationKind,
} from "./appHelpers";
import { useWorkbenchState } from "./useWorkbenchState";

export interface UseLibraryResourceControllerParams {
  resources: BootstrapData["resources"];
  planStages: PlanStage[] | undefined;
  workspaceId: string | undefined;
  composerLanguage: ComposerLanguage;
  resourceSearchMode: ResourceSearchMode;
  localizedResourceOperationFallback: string;
  isBrowserPreview: boolean;
  browserPreviewFixture: boolean;
  previewSessionId: string | undefined;
  setPreviewSessionId: (sessionId?: string) => void;
  setActiveView: (view: ActiveWorkbenchView) => void;
  setOperationMessage: (
    message?: TrainerOperationMessage,
    surface?: OperationMessageSurface,
  ) => void;
  applyRawHostMessage: (
    message: HostMessage,
    options?: { operationSurface?: OperationMessageSurface },
  ) => void;
  applyHostMessageRef: MutableRefObject<(message: HostMessage, isProviderActionOverride?: boolean) => void>;
}

export function useLibraryResourceController({
  resources,
  planStages,
  workspaceId,
  composerLanguage,
  resourceSearchMode,
  localizedResourceOperationFallback,
  isBrowserPreview,
  browserPreviewFixture,
  previewSessionId,
  setPreviewSessionId,
  setActiveView,
  setOperationMessage,
  applyRawHostMessage,
  applyHostMessageRef,
}: UseLibraryResourceControllerParams) {
  const resourceOperationResolversRef = useRef(new Map<string, PendingResourceOperation>());
  const resourceOperationSequenceRef = useRef(0);
  const resourceTrainingHandoffResolversRef = useRef(
    new Map<string, PendingResourceTrainingHandoff>(),
  );
  const resourceTrainingHandoffSequenceRef = useRef(0);

  useEffect(() => {
    return () => {
      for (const operation of resourceOperationResolversRef.current.values()) {
        window.clearTimeout(operation.timeoutId);
        operation.reject(new Error("Resource operation was interrupted."));
      }
      resourceOperationResolversRef.current.clear();
      for (const handoff of resourceTrainingHandoffResolversRef.current.values()) {
        window.clearTimeout(handoff.timeoutId);
        handoff.resolve({
          requestId: "",
          resourceId: handoff.resourceId,
          outcome: "failed",
        });
      }
      resourceTrainingHandoffResolversRef.current.clear();
    };
  }, []);

  const libraryFolderOperations = useHostOperationResolver<LibraryFolderHostAnswer>({
    ok: false,
    message: "",
    unconfirmed: true,
  });
  const resolveLibraryFolderOperation = useCallback(
    (payload: { operationId?: string; ok: boolean; folders?: unknown; message?: string }) => {
      const operationId = String(payload.operationId ?? "").trim();
      if (!operationId) {
        return;
      }
      libraryFolderOperations.resolve(operationId, {
        ok: payload.ok,
        message: typeof payload.message === "string" ? payload.message.trim() : "",
        folders: payload.folders,
      });
    },
    [libraryFolderOperations],
  );

  const libraryMigrationOperations = useHostOperationResolver<LibraryMigrationHostAnswer>({
    ok: false,
    message: "",
    unconfirmed: true,
  });
  const resolveLibraryMigrationOperation = useCallback(
    (payload: {
      operationId?: string;
      ok: boolean;
      message?: string;
      summary?: LibraryMigrationSummary;
    }) => {
      const operationId = String(payload.operationId ?? "").trim();
      if (!operationId) {
        return;
      }
      libraryMigrationOperations.resolve(operationId, {
        ok: payload.ok,
        message: typeof payload.message === "string" ? payload.message.trim() : "",
        summary: payload.summary,
      });
    },
    [libraryMigrationOperations],
  );

  const resolveResourceTrainingHandoffMessage = useCallback(
    (payload: ResourceTrainingHandoffResult) => {
      const handoff = resourceTrainingHandoffResolversRef.current.get(payload.requestId);
      if (handoff?.resourceId === payload.resourceId) {
        resourceTrainingHandoffResolversRef.current.delete(payload.requestId);
        window.clearTimeout(handoff.timeoutId);
        handoff.resolve(payload);
      }
    },
    [],
  );

  const resolveResourceOperationStatus = useCallback(
    (message: HostMessage): HostMessage => {
      const status = parseResourceOperationStatus(message, localizedResourceOperationFallback);
      if (!status || message.type !== "operation/status") {
        return message;
      }
      const operation = resourceOperationResolversRef.current.get(status.requestId);
      if (operation?.kind === status.kind) {
        operation.statusMessage = status.message;
        if (message.payload.resourceCapture) {
          operation.onCapture?.(message.payload.resourceCapture);
        }
        if (message.payload.resourceVersionResults) {
          operation.onVersionResults?.(message.payload.resourceVersionResults);
        }
        resourceOperationResolversRef.current.delete(status.requestId);
        window.clearTimeout(operation.timeoutId);
        if (message.payload.tone === "error") {
          operation.reject(new Error(status.message));
        } else {
          operation.resolve();
        }
      }
      return {
        ...message,
        payload: { ...message.payload, message: status.message },
      };
    },
    [localizedResourceOperationFallback],
  );

  const requestResourceMutation = useCallback(
    (kind: ResourceMutationOperationKind, resourceIds: string[]): Promise<void> => {
      const requestId = `resource-operation-${Date.now().toString(36)}-${++resourceOperationSequenceRef.current}`;
      return new Promise<void>((resolve, reject) => {
        const timeoutId = window.setTimeout(() => {
          const operation = resourceOperationResolversRef.current.get(requestId);
          if (!operation || operation.kind !== kind) {
            return;
          }
          resourceOperationResolversRef.current.delete(requestId);
          operation.reject(new Error("Resource operation timed out."));
        }, RESOURCE_OPERATION_TIMEOUT_MS);
        resourceOperationResolversRef.current.set(requestId, { kind, resolve, reject, timeoutId });
        try {
          postMessage({
            type: "command/execute",
            payload: {
              commandId:
                kind === "delete" ? trainerCommands.deleteResource : trainerCommands.restoreResource,
              payload: { resourceIds, __trainerResourceOperationId: requestId },
            },
          });
        } catch (error) {
          const operation = resourceOperationResolversRef.current.get(requestId);
          resourceOperationResolversRef.current.delete(requestId);
          if (operation) {
            window.clearTimeout(operation.timeoutId);
            operation.reject(error);
          } else {
            reject(error);
          }
        }
      });
    },
    [],
  );

  const requestResourceIndex = useCallback((): Promise<void> => {
    const requestId = `resource-operation-${Date.now().toString(36)}-${++resourceOperationSequenceRef.current}`;
    return new Promise<void>((resolve, reject) => {
      const timeoutId = window.setTimeout(() => {
        const operation = resourceOperationResolversRef.current.get(requestId);
        if (!operation || operation.kind !== "index") {
          return;
        }
        resourceOperationResolversRef.current.delete(requestId);
        operation.reject(new Error("Resource indexing timed out."));
      }, RESOURCE_OPERATION_TIMEOUT_MS);
      resourceOperationResolversRef.current.set(requestId, {
        kind: "index",
        resolve,
        reject,
        timeoutId,
      });
      try {
        postMessage({
          type: "command/execute",
          payload: {
            commandId: trainerCommands.indexResources,
            payload: { __trainerResourceOperationId: requestId },
          },
        });
      } catch (error) {
        const operation = resourceOperationResolversRef.current.get(requestId);
        resourceOperationResolversRef.current.delete(requestId);
        if (operation) {
          window.clearTimeout(operation.timeoutId);
          operation.reject(error);
        } else {
          reject(error);
        }
      }
    });
  }, []);

  const requestCoachReplyUpload = useCallback(
    (message: ConversationMessage): Promise<void> => {
      const requestId = `resource-operation-${Date.now().toString(36)}-${++resourceOperationSequenceRef.current}`;
      return new Promise<void>((resolve, reject) => {
        const timeoutId = window.setTimeout(() => {
          const operation = resourceOperationResolversRef.current.get(requestId);
          if (!operation || operation.kind !== "upload") {
            return;
          }
          resourceOperationResolversRef.current.delete(requestId);
          operation.reject(new Error("Resource upload timed out."));
        }, RESOURCE_OPERATION_TIMEOUT_MS);
        resourceOperationResolversRef.current.set(requestId, {
          kind: "upload",
          resolve,
          reject,
          timeoutId,
        });
        try {
          const replyDoc = coachReplyMarkdown(message, composerLanguage);
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.uploadResource,
              payload: {
                uploads: [
                  {
                    kind: "markdown",
                    name: replyDoc.title,
                    source: "coach-reply",
                    content: replyDoc.markdown,
                    contentEncoding: "utf-8",
                    tags: ["coach-reply"],
                    sourceType: "file",
                  },
                ],
                __trainerResourceOperationId: requestId,
              },
            },
          });
        } catch (error) {
          const operation = resourceOperationResolversRef.current.get(requestId);
          resourceOperationResolversRef.current.delete(requestId);
          if (operation) {
            window.clearTimeout(operation.timeoutId);
            operation.reject(error);
          } else {
            reject(error);
          }
        }
      });
    },
    [composerLanguage],
  );

  const requestCoachResearchBrief = useCallback(
    (message: ConversationMessage): Promise<void> => {
      const requestId = `resource-operation-${Date.now().toString(36)}-${++resourceOperationSequenceRef.current}`;
      return new Promise<void>((resolve, reject) => {
        const timeoutMs = 135_000;
        const timeoutId = window.setTimeout(() => {
          const operation = resourceOperationResolversRef.current.get(requestId);
          if (!operation || operation.kind !== "save-research-brief") {
            return;
          }
          resourceOperationResolversRef.current.delete(requestId);
          operation.reject(new Error("Research brief timed out."));
        }, timeoutMs);
        resourceOperationResolversRef.current.set(requestId, {
          kind: "save-research-brief",
          resolve,
          reject,
          timeoutId,
        });
        try {
          const conversation = useWorkbenchState.getState().data.conversation;
          const researchGoal = goalTitleFromConversation(conversation, message.id);
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.saveResearchBrief,
              payload: {
                researchGoal: researchGoal.slice(0, 300),
                reply: message.body.slice(0, 12000),
                resourceIds: researchBriefResourceIds(message),
                __trainerResourceOperationId: requestId,
              },
            },
          });
        } catch (error) {
          const operation = resourceOperationResolversRef.current.get(requestId);
          resourceOperationResolversRef.current.delete(requestId);
          if (operation) {
            window.clearTimeout(operation.timeoutId);
            operation.reject(error);
          } else {
            reject(error);
          }
        }
      });
    },
    [],
  );

  const requestResourceSearch = useCallback(
    ({ query, requestId }: ResourceSearchRequest): Promise<void> => {
      return new Promise<void>((resolve, reject) => {
        const timeoutId = window.setTimeout(() => {
          const operation = resourceOperationResolversRef.current.get(requestId);
          if (!operation || operation.kind !== "search") {
            return;
          }
          resourceOperationResolversRef.current.delete(requestId);
          operation.reject(new Error("Resource search timed out."));
        }, RESOURCE_OPERATION_TIMEOUT_MS);
        resourceOperationResolversRef.current.set(requestId, {
          kind: "search",
          resolve,
          reject,
          timeoutId,
        });
        try {
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.searchResources,
              payload: { query, requestId, mode: resourceSearchMode },
            },
          });
        } catch (error) {
          const operation = resourceOperationResolversRef.current.get(requestId);
          resourceOperationResolversRef.current.delete(requestId);
          if (operation) {
            window.clearTimeout(operation.timeoutId);
            operation.reject(error);
          } else {
            reject(error);
          }
        }
      });
    },
    [resourceSearchMode],
  );

  const requestBrowserPreviewResourceSearch = useCallback(
    async ({ query, requestId }: ResourceSearchRequest): Promise<void> => {
      if (!isBrowserPreview) {
        return;
      }
      const browserPreview = await loadBrowserPreviewModule();
      const result = await browserPreview.searchBrowserPreviewResources(
        { query, requestId, mode: resourceSearchMode },
        previewSessionId,
      );
      setPreviewSessionId(result.sessionId);
      applyRawHostMessage(result.message);
    },
    [
      applyRawHostMessage,
      isBrowserPreview,
      previewSessionId,
      resourceSearchMode,
      setPreviewSessionId,
    ],
  );

  const requestResourceTrainingHandoff = useCallback(
    (
      resourceId: string,
      cardType: "flash" | "practice" = "flash",
      prompt?: string,
      linkedPractice?: {
        expectedResourceVersion: ResourceVersionPin;
        planBinding: TrainingPlanBinding;
        filePractice: boolean;
      },
    ): Promise<ResourceTrainingHandoffResult> => {
      const requestId = `resource-training-${Date.now().toString(36)}-${++resourceTrainingHandoffSequenceRef.current}`;
      const scope = useWorkbenchState.getState();
      return new Promise<ResourceTrainingHandoffResult>((resolve) => {
        const timeoutId = window.setTimeout(() => {
          const handoff = resourceTrainingHandoffResolversRef.current.get(requestId);
          if (!handoff) {
            return;
          }
          resourceTrainingHandoffResolversRef.current.delete(requestId);
          handoff.resolve({ requestId, resourceId, outcome: "failed" });
        }, cardType === "practice" ? 135_000 : RESOURCE_TRAINING_HANDOFF_TIMEOUT_MS);
        resourceTrainingHandoffResolversRef.current.set(requestId, {
          resourceId,
          resolve,
          timeoutId,
        });
        try {
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.trainingGenerateCard,
              payload: {
                source: linkedPractice?.filePractice ? "formal_plan_step" : "resource_knowledge",
                cardType,
                submode: cardType,
                resourceId,
                ...(linkedPractice
                  ? {
                      planBinding: linkedPractice.planBinding,
                      expectedResourceVersion: linkedPractice.expectedResourceVersion,
                    }
                  : {}),
                ...(prompt?.trim() ? { prompt, contextHint: prompt } : {}),
                __trainerResourceTrainingHandoffId: requestId,
              },
            },
          });
        } catch {
          const handoff = resourceTrainingHandoffResolversRef.current.get(requestId);
          resourceTrainingHandoffResolversRef.current.delete(requestId);
          if (handoff) {
            window.clearTimeout(handoff.timeoutId);
          }
          resolve({ requestId, resourceId, outcome: "failed" });
        }
      }).then((result) => {
        const current = useWorkbenchState.getState();
        if (
          result.outcome === "ready" &&
          scope.layout.activeView === current.layout.activeView &&
          scope.syncCursor.workspaceId === current.syncCursor.workspaceId &&
          scope.syncCursor.sessionId === current.syncCursor.sessionId
        ) {
          setActiveView("training");
        }
        return result;
      });
    },
    [setActiveView],
  );

  const handleBrowserUploads = useCallback(
    async (files: File[]) => {
      const importingFolder = browserUploadLooksLikeFolder(files);
      const supportedFiles = files.filter(browserFileSupported);
      const unsupportedCount = files.length - supportedFiles.length;
      try {
        const browserPreview = await loadBrowserPreviewModule();
        const uploadLimit = browserPreview.browserUploadLimit();
        const truncated = supportedFiles.length > uploadLimit;
        const limitedFiles = supportedFiles.slice(0, uploadLimit);
        if (limitedFiles.length === 0) {
          setOperationMessage(
            {
              tone: "error",
              message: appUiCopy(composerLanguage, "没有找到可导入的支持文件。"),
            },
            "resources",
          );
          return;
        }

        const uploads = await readBrowserFiles(limitedFiles);
        const {
          sessionId,
          patch,
          uploadedCount,
          indexedCount,
          failedIndexCount,
          failedUploadCount,
          truncated: uploadTruncated,
        } = await browserPreview.uploadBrowserPreviewResources(uploads, previewSessionId);
        setPreviewSessionId(sessionId);
        useWorkbenchState.getState().patchData(patch);
        const limitedCount = uploads.length;
        const finalTruncated = truncated || uploadTruncated;
        const skippedText =
          unsupportedCount > 0
            ? appUiCopy(composerLanguage, "跳过 {n} 个不支持的文件。")
                .replace("{n}", String(unsupportedCount))
                .replace("{s}", unsupportedCount === 1 ? "" : "s")
            : "";
        const truncationText = finalTruncated
          ? appUiCopy(composerLanguage, "仅导入前 {n} 个支持文件。")
              .replace("{n}", String(limitedCount))
              .replace("{s}", limitedCount === 1 ? "" : "s")
          : "";
        const indexingText =
          failedIndexCount > 0
            ? appUiCopy(composerLanguage, "其中 {i} 个已完成索引，{f} 个上传成功但索引未完成。")
                .replace("{i}", String(indexedCount))
                .replace("{f}", String(failedIndexCount))
                .replace("{s}", failedIndexCount === 1 ? "" : "s")
            : appUiCopy(composerLanguage, "已完成 {i} 个文件的索引并刷新资料状态。")
                .replace("{i}", String(indexedCount))
                .replace("{s}", indexedCount === 1 ? "" : "s");
        const uploadFailureText =
          failedUploadCount > 0
            ? appUiCopy(composerLanguage, "其中 {n} 个没有导入成功，其他资料已经可以使用。")
                .replace("{n}", String(failedUploadCount))
                .replace("{s}", failedUploadCount === 1 ? "" : "s")
            : "";
        const importedLead = appUiCopy(
          composerLanguage,
          importingFolder ? "已导入文件夹中的资料。" : "已导入资料。",
        );
        const uploadedText = appUiCopy(composerLanguage, "共上传 {n} 个支持文件。")
          .replace("{n}", String(uploadedCount))
          .replace("{s}", uploadedCount === 1 ? "" : "s");
        setOperationMessage(
          {
            tone: failedUploadCount > 0 || failedIndexCount > 0 ? "info" : "success",
            message: [
              importedLead,
              uploadedCount > 0 ? uploadedText : "",
              truncationText,
              skippedText,
              uploadFailureText,
              indexingText,
            ]
              .filter(Boolean)
              .map((fragment) => ` ${fragment}`)
              .join("")
              .trim(),
          },
          "resources",
        );
      } catch {
        setOperationMessage(
          {
            tone: "error",
            message: recoverableFailureMessage("upload", composerLanguage),
          },
          "resources",
        );
      }
    },
    [composerLanguage, previewSessionId, setOperationMessage, setPreviewSessionId],
  );

  const handleBrowserUrlImport = useCallback(async () => {
    if (!isBrowserPreview || browserPreviewFixture) {
      return;
    }

    const rawSource = window
      .prompt(appUiCopy(composerLanguage, "\u7c98\u8d34\u8981\u5bfc\u5165\u7684\u7f51\u9875 URL"))
      ?.trim();
    if (!rawSource) {
      return;
    }

    let parsedUrl: URL;
    try {
      parsedUrl = new URL(rawSource);
      if (parsedUrl.protocol !== "http:" && parsedUrl.protocol !== "https:") {
        throw new Error("unsupported protocol");
      }
    } catch {
      setOperationMessage(
        {
          tone: "error",
          message: appUiCopy(
            composerLanguage,
            "\u8bf7\u8f93\u5165\u6709\u6548\u7684 http \u6216 https URL\u3002",
          ),
        },
        "resources",
      );
      return;
    }

    const pathTitle = parsedUrl.pathname.split("/").filter(Boolean).pop();
    const title = pathTitle || parsedUrl.hostname || rawSource;
    try {
      const browserPreview = await loadBrowserPreviewModule();
      const result = await browserPreview.uploadBrowserPreviewResources(
        [
          {
            name: title,
            kind: "url",
            content: "",
            source: rawSource,
            tags: [],
          },
        ],
        previewSessionId,
      );
      setPreviewSessionId(result.sessionId);
      useWorkbenchState.getState().patchData(result.patch);
      setOperationMessage(
        {
          tone: result.failedIndexCount > 0 || result.failedUploadCount > 0 ? "info" : "success",
          message:
            result.failedIndexCount > 0 || result.failedUploadCount > 0
              ? appUiCopy(composerLanguage, "网页已导入，但索引未完全完成。已上传 {n} 项。").replace(
                  "{n}",
                  String(result.uploadedCount),
                )
              : appUiCopy(composerLanguage, "网页已导入并完成索引。"),
        },
        "resources",
      );
    } catch {
      setOperationMessage(
        {
          tone: "error",
          message: recoverableFailureMessage("upload", composerLanguage),
        },
        "resources",
      );
    }
  }, [
    browserPreviewFixture,
    composerLanguage,
    isBrowserPreview,
    previewSessionId,
    setOperationMessage,
    setPreviewSessionId,
  ]);

  const resourceCaptureFocusOptions = useMemo<ResourceCaptureFocusOption[]>(
    () =>
      (planStages ?? [])
        .filter((stage) => stage.id.trim() && stage.title.trim())
        .map((stage) => ({ id: stage.id, label: stage.title })),
    [planStages],
  );

  const refreshPreviewResources = useCallback(async () => {
    const browserPreview = await loadBrowserPreviewModule();
    const { sessionId, message } = await browserPreview.fetchBrowserPreviewBootstrap(
      previewSessionId,
      true,
    );
    setPreviewSessionId(sessionId);
    applyHostMessageRef.current(message);
  }, [applyHostMessageRef, previewSessionId, setPreviewSessionId]);

  const beginResourceOperationStatusWait = useCallback(
    (
      kind: "capture" | "organize" | "export" | "link-learning" | "check-versions",
      timeoutMs: number,
    ) => {
      const requestId = `resource-${kind}-${Date.now().toString(36)}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      const operation: {
        statusMessage: string;
        capture?: NonNullable<
          Extract<HostMessage, { type: "operation/status" }>["payload"]["resourceCapture"]
        >;
        versionResults?: ResourceVersionCheckResult[];
      } = {
        statusMessage: "",
      };
      let timedOut = false;
      const done = new Promise<void>((resolve, reject) => {
        const timeoutId = window.setTimeout(() => {
          timedOut = true;
          resourceOperationResolversRef.current.delete(requestId);
          resolve();
        }, timeoutMs);
        const settle = (settledMessage?: string) => {
          if (settledMessage) {
            operation.statusMessage = settledMessage;
          }
          resourceOperationResolversRef.current.delete(requestId);
          window.clearTimeout(timeoutId);
        };
        resourceOperationResolversRef.current.set(requestId, {
          kind,
          onCapture: (result) => {
            operation.capture = result;
          },
          onVersionResults: (results) => {
            operation.versionResults = results;
          },
          resolve: () => {
            settle();
            resolve();
          },
          reject: (reason) => {
            settle(reason instanceof Error ? reason.message : String(reason ?? ""));
            reject(reason);
          },
          timeoutId,
        });
      });
      const settle = () => {
        const pending = resourceOperationResolversRef.current.get(requestId);
        if (pending?.kind === kind) {
          resourceOperationResolversRef.current.delete(requestId);
          window.clearTimeout(pending.timeoutId);
        }
      };
      const statusMessage = (): string => operation.statusMessage;
      const hasTimedOut = (): boolean => timedOut;
      return {
        requestId,
        done,
        settle,
        statusMessage,
        hasTimedOut,
        capture: () => operation.capture,
        versionResults: () => operation.versionResults,
      };
    },
    [],
  );

  const captureResourceIntoLibrary = useCallback(
    async (input: ResourceCaptureInput): Promise<ResourceMutationOutcome> => {
      const url = input.url.trim();
      const title = input.title?.trim() || undefined;
      const download = input.download === true;
      const targetDir = download ? input.targetDir?.trim() || undefined : undefined;
      const clientCaptureId = input.browserSource
        ? ["composer-capture", input.browserSource.id, input.focusId, input.planBinding?.revision]
            .filter(Boolean)
            .join("-")
        : "library-capture-" +
          Date.now().toString(36) +
          "-" +
          Math.random().toString(36).slice(2, 8);
      const sourceFields = input.browserSource
        ? {
            capture_mode: input.browserSource.selection ? "selection" : "link",
            selection: input.browserSource.selection || undefined,
          }
        : {};
      const bindingFields = input.planBinding
        ? {
            bind_plan_id: input.planBinding.planId,
            bind_plan_revision: input.planBinding.revision,
          }
        : {};
      if (isBrowserPreview && !browserPreviewFixture) {
        try {
          const browserPreview = await loadBrowserPreviewModule();
          const baseUrl = await browserPreview.ensureBrowserPreviewSidecar();
          const response = await fetch(`${baseUrl}/resources/capture`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              url,
              kind: input.kind ?? captureTargetKind(url),
              ...sourceFields,
              ...bindingFields,
              ...(title ? { title } : {}),
              ...(input.focusId ? { bind_focus_id: input.focusId } : {}),
              ...(download ? { download: true } : {}),
              ...(targetDir ? { target_dir: targetDir } : {}),
              client_capture_id: clientCaptureId,
              session_id: previewSessionId,
            }),
          });
          if (!response.ok) {
            const detail = await response
              .json()
              .then((body: unknown) => describeSidecarFailure(body))
              .catch(() => "");
            return {
              ok: false,
              message:
                detail || sanitizeErrorSurfaceText(`HTTP ${response.status}`, composerLanguage),
            };
          }
          const payload = (await response.json()) as {
            name?: unknown;
            resource_id?: unknown;
            version_id?: unknown;
            content_hash?: unknown;
            deduped?: unknown;
            warnings?: string[];
            saved_path?: unknown;
          };
          const name =
            typeof payload.name === "string" && payload.name.trim() ? payload.name.trim() : url;
          await refreshPreviewResources().catch(() => undefined);
          return {
            ok: true,
            message: name,
            deduped: payload.deduped === true,
            focusBinding: payload.warnings
              ?.find((warning) => warning.startsWith("focus_binding:"))
              ?.slice("focus_binding:".length),
            resourceId: typeof payload.resource_id === "string" ? payload.resource_id : undefined,
            versionId: typeof payload.version_id === "string" ? payload.version_id : undefined,
            contentHash:
              typeof payload.content_hash === "string" ? payload.content_hash : undefined,
            savedPath:
              typeof payload.saved_path === "string" && payload.saved_path.trim()
                ? payload.saved_path.trim()
                : undefined,
          };
        } catch (error) {
          return {
            ok: false,
            message: error instanceof Error ? error.message : String(error),
          };
        }
      }

      const beforeIds = new Set(
        useWorkbenchState.getState().data.resources.map((resource) => resource.id),
      );
      const captureWait = beginResourceOperationStatusWait(
        "capture",
        CAPTURE_CONFIRMATION_TIMEOUT_MS,
      );
      postMessage({
        type: "command/execute",
        payload: {
          commandId: "trainer.resource.capture",
          payload: {
            url,
            kind: input.kind ?? captureTargetKind(url),
            ...sourceFields,
            ...bindingFields,
            ...(title ? { title } : {}),
            ...(input.focusId ? { bind_focus_id: input.focusId } : {}),
            ...(download ? { download: true } : {}),
            ...(targetDir ? { target_dir: targetDir } : {}),
            client_capture_id: clientCaptureId,
            workspace_id: workspaceId || undefined,
            __trainerResourceOperationId: captureWait.requestId,
          },
        },
      });
      if (input.browserSource) {
        try {
          await captureWait.done;
          const receipt = captureWait.capture();
          return receipt
            ? { ok: true, message: receipt.title ?? url, ...receipt }
            : { ok: false, unconfirmed: true, message: "" };
        } catch (error) {
          return { ok: false, message: error instanceof Error ? error.message : String(error) };
        } finally {
          captureWait.settle();
        }
      }
      let landed: Awaited<ReturnType<typeof waitForCapturedResource>>;
      let operationRejected: unknown;
      try {
        landed = await Promise.race([
          waitForCapturedResource(url, beforeIds),
          captureWait.done.then(() => undefined),
        ]);
        captureWait.settle();
        landed ??= await waitForCapturedResource(url, new Set(beforeIds), 10_000);
      } catch (error) {
        captureWait.settle();
        const reason = error instanceof Error ? error.message : String(error);
        return {
          ok: false,
          message: reason.replace("[[trainer-resource-failure]]", "").trim(),
        };
      }
      if (!landed) {
        return { ok: false, unconfirmed: true, message: "" };
      }
      if (landed.deduped) {
        if (!captureWait.hasTimedOut()) {
          try {
            await captureWait.done;
          } catch (error) {
            operationRejected = error;
          }
          if (operationRejected) {
            const reason =
              operationRejected instanceof Error
                ? operationRejected.message
                : String(operationRejected ?? "");
            return {
              ok: false,
              message: reason.replace("[[trainer-resource-failure]]", "").trim(),
            };
          }
          const refreshed = await waitForCapturedResource(url, new Set(), 2_000);
          if (refreshed && refreshed.resourceId === landed.resourceId) {
            landed = refreshed;
          }
        }
      }
      return {
        ok: true,
        message: landed.title,
        deduped: landed.deduped,
        resourceId: landed.resourceId,
        savedPath: landed.savedPath,
      };
    },
    [
      beginResourceOperationStatusWait,
      browserPreviewFixture,
      composerLanguage,
      isBrowserPreview,
      previewSessionId,
      refreshPreviewResources,
      workspaceId,
    ],
  );

  const requestLibraryMigration = useCallback(
    async (request: { dryRun: boolean; confirm: boolean }): Promise<LibraryMigrationHostAnswer> => {
      const operationId = `library-migration-${Date.now().toString(36)}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      return libraryMigrationOperations.request({
        operationId,
        timeoutMs: LIBRARY_MIGRATION_TIMEOUT_MS,
        send: () => {
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.markdownOnlyMigration,
              payload: { ...request, operationId },
            },
          });
        },
      });
    },
    [libraryMigrationOperations],
  );

  const requestLibraryFolderOperation = useCallback(
    (commandId: string, payload: Record<string, unknown>): Promise<LibraryFolderHostAnswer> => {
      const operationId = `library-folders-${Date.now().toString(36)}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      return libraryFolderOperations.request({
        operationId,
        timeoutMs: LIBRARY_FOLDER_OPERATION_TIMEOUT_MS,
        send: () => {
          postMessage({
            type: "command/execute",
            payload: { commandId, payload: { ...payload, operationId } },
          });
        },
      });
    },
    [libraryFolderOperations],
  );

  const mutatePreviewLibraryFolder = useCallback(
    async (
      method: "POST" | "DELETE",
      endpoint: string,
      body: Record<string, unknown>,
    ): Promise<ResourceMutationOutcome> => {
      try {
        const browserPreview = await loadBrowserPreviewModule();
        const baseUrl = await browserPreview.ensureBrowserPreviewSidecar();
        const response = await fetch(`${baseUrl}${endpoint}`, {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...body, session_id: previewSessionId }),
        });
        if (!response.ok) {
          const detail = await response
            .json()
            .then((payload: unknown) => describeSidecarFailure(payload))
            .catch(() => "");
          return {
            ok: false,
            message:
              detail || sanitizeErrorSurfaceText(`HTTP ${response.status}`, composerLanguage),
          };
        }
        return { ok: true, message: "" };
      } catch (error) {
        return {
          ok: false,
          message: error instanceof Error ? error.message : String(error),
        };
      }
    },
    [composerLanguage, previewSessionId],
  );

  const listLibraryFolders = useCallback(async (): Promise<LibraryFolderListResult> => {
    if (isBrowserPreview && !browserPreviewFixture) {
      if (!previewSessionId?.trim()) {
        return { ok: false, folders: [], message: "" };
      }
      try {
        const browserPreview = await loadBrowserPreviewModule();
        const baseUrl = await browserPreview.ensureBrowserPreviewSidecar();
        const response = await fetch(
          `${baseUrl}/library/groups?session_id=${encodeURIComponent(previewSessionId ?? "")}`,
        );
        if (!response.ok) {
          const detail = await response
            .json()
            .then((payload: unknown) => describeSidecarFailure(payload))
            .catch(() => "");
          return {
            ok: false,
            folders: [],
            message:
              detail || sanitizeErrorSurfaceText(`HTTP ${response.status}`, composerLanguage),
          };
        }
        const payload = await response.json().catch(() => undefined);
        return { ok: true, folders: parseLibraryFolderTree(payload), message: "" };
      } catch (error) {
        return {
          ok: false,
          folders: [],
          message: error instanceof Error ? error.message : String(error),
        };
      }
    }
    const answer = await requestLibraryFolderOperation("trainer.library.folders.list", {
      workspace_id: workspaceId || undefined,
    });
    if (answer.unconfirmed) {
      return { ok: false, folders: [], message: "" };
    }
    return {
      ok: answer.ok,
      folders: parseLibraryFolderTree(answer.folders),
      message: answer.message,
    };
  }, [
    browserPreviewFixture,
    composerLanguage,
    isBrowserPreview,
    previewSessionId,
    requestLibraryFolderOperation,
    workspaceId,
  ]);

  const createLibraryFolder = useCallback(
    async (path: string): Promise<ResourceMutationOutcome> => {
      const folderPath = path.trim();
      if (isBrowserPreview && !browserPreviewFixture) {
        return mutatePreviewLibraryFolder("POST", "/library/groups", { path: folderPath });
      }
      const answer = await requestLibraryFolderOperation("trainer.library.folders.create", {
        path: folderPath,
        workspace_id: workspaceId || undefined,
      });
      return {
        ok: answer.ok,
        message: answer.message,
        ...(answer.unconfirmed ? { unconfirmed: true } : {}),
      };
    },
    [
      browserPreviewFixture,
      isBrowserPreview,
      mutatePreviewLibraryFolder,
      requestLibraryFolderOperation,
      workspaceId,
    ],
  );

  const renameLibraryFolder = useCallback(
    async (path: string, nextPath: string): Promise<ResourceMutationOutcome> => {
      const folderPath = path.trim();
      const nextFolderPath = nextPath.trim();
      if (isBrowserPreview && !browserPreviewFixture) {
        return mutatePreviewLibraryFolder("POST", "/library/groups/rename", {
          path: folderPath,
          new_path: nextFolderPath,
        });
      }
      const answer = await requestLibraryFolderOperation("trainer.library.folders.rename", {
        path: folderPath,
        new_path: nextFolderPath,
        workspace_id: workspaceId || undefined,
      });
      return {
        ok: answer.ok,
        message: answer.message,
        ...(answer.unconfirmed ? { unconfirmed: true } : {}),
      };
    },
    [
      browserPreviewFixture,
      isBrowserPreview,
      mutatePreviewLibraryFolder,
      requestLibraryFolderOperation,
      workspaceId,
    ],
  );

  const deleteLibraryFolder = useCallback(
    async (path: string): Promise<ResourceMutationOutcome> => {
      const folderPath = path.trim();
      if (isBrowserPreview && !browserPreviewFixture) {
        return mutatePreviewLibraryFolder("DELETE", "/library/groups", { path: folderPath });
      }
      const answer = await requestLibraryFolderOperation("trainer.library.folders.delete", {
        path: folderPath,
        workspace_id: workspaceId || undefined,
      });
      return {
        ok: answer.ok,
        message: answer.message,
        ...(answer.unconfirmed ? { unconfirmed: true } : {}),
      };
    },
    [
      browserPreviewFixture,
      isBrowserPreview,
      mutatePreviewLibraryFolder,
      requestLibraryFolderOperation,
      workspaceId,
    ],
  );

  const revealLibraryPath = useCallback((path: string) => {
    postMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.revealSandboxPath, payload: { path } },
    });
  }, []);

  const organizeLibraryResource = useCallback(
    async (
      resourceId: string,
      request: ResourceOrganizeInput,
    ): Promise<ResourceMutationOutcome> => {
      if (isBrowserPreview && !browserPreviewFixture) {
        try {
          const browserPreview = await loadBrowserPreviewModule();
          const baseUrl = await browserPreview.ensureBrowserPreviewSidecar();
          const response = await fetch(`${baseUrl}/resource/organize`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: previewSessionId,
              resource_id: resourceId,
              action: request.action,
              ...(request.title !== undefined ? { title: request.title } : {}),
              ...(request.tags !== undefined ? { tags: request.tags } : {}),
              ...(request.group !== undefined ? { group: request.group } : {}),
            }),
          });
          if (!response.ok) {
            const detail = await response
              .json()
              .then((body: unknown) => describeSidecarFailure(body))
              .catch(() => "");
            return {
              ok: false,
              message:
                detail || sanitizeErrorSurfaceText(`HTTP ${response.status}`, composerLanguage),
            };
          }
          await refreshPreviewResources().catch(() => undefined);
          return {
            ok: true,
            message: "",
            resourceId,
          };
        } catch (error) {
          return {
            ok: false,
            message: error instanceof Error ? error.message : String(error),
          };
        }
      }

      const before = useWorkbenchState
        .getState()
        .data.resources.find((item) => item.id === resourceId);
      const beforeCollectionPath = (before?.collectionPath ?? "").trim();
      const organizeWait = beginResourceOperationStatusWait(
        "organize",
        ORGANIZE_CONFIRMATION_TIMEOUT_MS,
      );
      postMessage({
        type: "command/execute",
        payload: {
          commandId: "trainer.resource.organize",
          payload: {
            resource_id: resourceId,
            action: request.action,
            ...(request.title !== undefined ? { title: request.title } : {}),
            ...(request.tags !== undefined ? { tags: request.tags } : {}),
            ...(request.group !== undefined ? { group: request.group } : {}),
            workspace_id: workspaceId || undefined,
            __trainerResourceOperationId: organizeWait.requestId,
          },
        },
      });
      let confirmed: boolean;
      try {
        confirmed = await Promise.race([
          waitForOrganizedResource(resourceId, request, beforeCollectionPath),
          organizeWait.done.then(() => true),
        ]);
        organizeWait.settle();
      } catch (error) {
        organizeWait.settle();
        const reason = error instanceof Error ? error.message : String(error);
        return {
          ok: false,
          message: reason.replace("[[trainer-resource-failure]]", "").trim(),
        };
      }
      if (!confirmed) {
        return { ok: false, unconfirmed: true, message: "" };
      }
      return { ok: true, message: "", resourceId };
    },
    [
      beginResourceOperationStatusWait,
      browserPreviewFixture,
      composerLanguage,
      isBrowserPreview,
      previewSessionId,
      refreshPreviewResources,
      workspaceId,
    ],
  );

  const exportLibraryResource = useCallback(
    async (
      resourceId: string,
      format: "markdown" | "pdf" = "markdown",
    ): Promise<ResourceMutationOutcome> => {
      const resource = resources.find((item) => item.id === resourceId);
      const name = resource?.title?.trim() || resourceId;
      if (isBrowserPreview && !browserPreviewFixture) {
        try {
          const browserPreview = await loadBrowserPreviewModule();
          const baseUrl = await browserPreview.ensureBrowserPreviewSidecar();
          const formatParam = format === "pdf" ? "&format=pdf" : "";
          const response = await fetch(
            `${baseUrl}/resource/export?session_id=${encodeURIComponent(
              previewSessionId ?? "",
            )}&resource_id=${encodeURIComponent(resourceId)}${formatParam}`,
          );
          if (!response.ok) {
            const detail = await response
              .json()
              .then((body: unknown) => describeSidecarFailure(body))
              .catch(() => "");
            return {
              ok: false,
              message:
                detail || sanitizeErrorSurfaceText(`HTTP ${response.status}`, composerLanguage),
            };
          }
          const blob = await response.blob();
          const fallbackName = format === "pdf" ? `${name.replace(/\.md$/i, "")}.pdf` : name;
          const downloadName = exportDownloadName(response.headers) ?? fallbackName;
          triggerLocalDownload(blob, downloadName);
          return { ok: true, message: downloadName, resourceId };
        } catch (error) {
          return {
            ok: false,
            message: error instanceof Error ? error.message : String(error),
          };
        }
      }

      const exportWait = beginResourceOperationStatusWait("export", 120_000);
      postMessage({
        type: "command/execute",
        payload: {
          commandId: "trainer.resource.export",
          payload: {
            resource_id: resourceId,
            format,
            workspace_id: workspaceId || undefined,
            __trainerResourceOperationId: exportWait.requestId,
          },
        },
      });
      try {
        await exportWait.done;
        const landedMessage = exportWait
          .statusMessage()
          .replace("[[trainer-resource-failure]]", "")
          .trim();
        exportWait.settle();
        return { ok: true, requested: true, message: landedMessage, resourceId };
      } catch (error) {
        exportWait.settle();
        const reason = error instanceof Error ? error.message : String(error);
        return {
          ok: false,
          message: reason.replace("[[trainer-resource-failure]]", "").trim(),
        };
      }
    },
    [
      beginResourceOperationStatusWait,
      browserPreviewFixture,
      composerLanguage,
      isBrowserPreview,
      previewSessionId,
      resources,
      workspaceId,
    ],
  );

  return {
    resolveResourceOperationStatus,
    resolveResourceTrainingHandoffMessage,
    resolveLibraryFolderOperation,
    resolveLibraryMigrationOperation,
    requestResourceMutation,
    requestResourceIndex,
    requestCoachReplyUpload,
    requestCoachResearchBrief,
    requestResourceSearch,
    requestBrowserPreviewResourceSearch,
    requestResourceTrainingHandoff,
    handleBrowserUploads,
    handleBrowserUrlImport,
    resourceCaptureFocusOptions,
    refreshPreviewResources,
    beginResourceOperationStatusWait,
    captureResourceIntoLibrary,
    requestLibraryMigration,
    listLibraryFolders,
    createLibraryFolder,
    renameLibraryFolder,
    deleteLibraryFolder,
    revealLibraryPath,
    organizeLibraryResource,
    exportLibraryResource,
  };
}
