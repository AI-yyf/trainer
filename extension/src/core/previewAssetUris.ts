import * as path from "node:path";
import type { FilePreviewPart, TrainerMessagePart } from "../../../shared/src/protocol";
import type { BootstrapData, ConversationMessageView, SandboxPreviewView } from "./types";
import { isDocxPreviewPath, isPdfPreviewPath } from "../../../shared/src/previewAssets";

const HOST_DOCX_FILE_PREVIEW_MESSAGE_ID = "host-file-preview-docx";

function shouldAttachPreviewAsset(kind: string | undefined, filePath: string | undefined): boolean {
  return (
    kind === "image" ||
    kind === "audio" ||
    kind === "video" ||
    isPdfPreviewPath(filePath) ||
    isDocxPreviewPath(filePath)
  );
}

function shouldInventDocxFilePreview(preview: SandboxPreviewView | undefined): preview is SandboxPreviewView & {
  path: string;
  assetUri: string;
} {
  return (
    Boolean(preview?.path) &&
    preview?.previewKind === "document" &&
    isDocxPreviewPath(preview.path) &&
    Boolean(preview.assetUri)
  );
}

function previewTierForPart(
  value: string | undefined,
): FilePreviewPart["previewTier"] | undefined {
  return value === "rich" || value === "converted" || value === "metadata" ? value : undefined;
}

function asOptionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0 ? value : undefined;
}

/**
 * Fail-closed: Coach DocxPreview gates on camelCase previewKind + assetUri.
 * Map snake_case inbound file_preview fields so DocxPreview can mount.
 */
function normalizeFilePreviewPartCamel(part: TrainerMessagePart): TrainerMessagePart {
  if (part.type !== "file_preview") {
    return part;
  }
  const raw = part as FilePreviewPart & Record<string, unknown>;
  const resourceId =
    asOptionalString(part.resourceId) ?? asOptionalString(raw.resource_id) ?? part.resourceId;
  const assetUri = asOptionalString(part.assetUri) ?? asOptionalString(raw.asset_uri);
  const previewKind = asOptionalString(part.previewKind) ?? asOptionalString(raw.preview_kind);
  const previewTier =
    previewTierForPart(part.previewTier) ??
    previewTierForPart(asOptionalString(raw.preview_tier));
  const canNativeOpen =
    typeof part.canNativeOpen === "boolean"
      ? part.canNativeOpen
      : typeof raw.can_native_open === "boolean"
        ? raw.can_native_open
        : part.canNativeOpen;
  const structuredData =
    part.structuredData ??
    (raw.structured_data && typeof raw.structured_data === "object"
      ? (raw.structured_data as Record<string, unknown>)
      : part.structuredData);

  return {
    ...part,
    resourceId,
    assetUri: assetUri ?? part.assetUri,
    previewKind: previewKind ?? part.previewKind,
    previewTier: previewTier ?? part.previewTier,
    canNativeOpen,
    structuredData,
  };
}

function buildDocxFilePreviewPart(
  preview: SandboxPreviewView & { path: string; assetUri: string },
  resourceId: string,
): FilePreviewPart {
  return {
    type: "file_preview",
    resourceId,
    path: preview.path,
    title: preview.title,
    content: preview.content,
    html: preview.html,
    assetUri: preview.assetUri,
    previewTier: previewTierForPart(preview.previewTier),
    previewKind: "document",
    canNativeOpen: preview.canNativeOpen,
    structuredData: preview.structuredData,
  };
}

/**
 * When conversation is explicitly provided (live preview path), ensure a Coach-renderable
 * file_preview part exists for document+.docx sandbox previews. Sidecar never emits these.
 * Call sites that omit conversation (mkdir/refresh/leftover dumps) stay fail-closed.
 */
function ensureDocxConversationFilePreview(
  conversation: ConversationMessageView[],
  preview: SandboxPreviewView & { path: string; assetUri: string },
  resourceId: string,
): ConversationMessageView[] {
  const part = buildDocxFilePreviewPart(preview, resourceId);

  let foundPath = false;
  const updated = conversation.map((message) => {
    if (!message.parts?.some((entry) => entry.type === "file_preview" && entry.path === preview.path)) {
      return message;
    }
    foundPath = true;
    return {
      ...message,
      parts: message.parts.map((entry) =>
        entry.type === "file_preview" && entry.path === preview.path
          ? { ...entry, ...part }
          : entry,
      ),
    };
  });
  if (foundPath) {
    return updated;
  }

  const hostMessage: ConversationMessageView = {
    id: HOST_DOCX_FILE_PREVIEW_MESSAGE_ID,
    role: "assistant",
    author: "Trainer",
    body: preview.title?.trim() || path.basename(preview.path),
    timestamp: new Date().toISOString(),
    sourceView: "resources",
    parts: [part],
  };

  const hostIndex = updated.findIndex((message) => message.id === HOST_DOCX_FILE_PREVIEW_MESSAGE_ID);
  if (hostIndex >= 0) {
    const next = [...updated];
    next[hostIndex] = hostMessage;
    return next;
  }

  return [...updated, hostMessage];
}

export function attachPreviewAssetUris(
  patch: Partial<BootstrapData>,
  resolveUri: (filePath: string) => string | undefined,
): Partial<BootstrapData> {
  let next: Partial<BootstrapData> = patch;

  const sandboxPreview = patch.memory?.sandboxPreview;
  if (
    sandboxPreview &&
    !sandboxPreview.assetUri &&
    shouldAttachPreviewAsset(sandboxPreview.previewKind, sandboxPreview.path)
  ) {
    const uri = resolveUri(sandboxPreview.path);
    if (uri) {
      next = {
        ...next,
        memory: {
          ...patch.memory,
          sandboxPreview: {
            ...sandboxPreview,
            assetUri: uri,
          },
        } as Partial<BootstrapData>["memory"],
      };
    }
  }

  if (Array.isArray(patch.conversation)) {
    next = {
      ...next,
      conversation: patch.conversation.map((message) => ({
        ...message,
        parts: message.parts?.map((part) => {
          const normalized = normalizeFilePreviewPartCamel(part);
          if (
            normalized.type !== "file_preview" ||
            normalized.assetUri ||
            !shouldAttachPreviewAsset(normalized.previewKind, normalized.path)
          ) {
            return normalized;
          }
          const uri = resolveUri(normalized.path);
          return uri ? { ...normalized, assetUri: uri } : normalized;
        }),
      })),
    };
  }

  // Opt-in: only invent when the call site passed conversation (live preview / resource open).
  const conversation = Array.isArray(next.conversation) ? next.conversation : undefined;
  const livePreview = next.memory?.sandboxPreview ?? sandboxPreview;
  if (conversation && shouldInventDocxFilePreview(livePreview)) {
    const resourceId =
      next.memory?.selectedResourceDetail?.id?.trim() ||
      patch.memory?.selectedResourceDetail?.id?.trim() ||
      `sandbox:${livePreview.path}`;
    next = {
      ...next,
      conversation: ensureDocxConversationFilePreview(conversation, livePreview, resourceId),
    };
  }

  return next;
}
