import type { ResearchBriefView } from "../../../../shared/src/researchBrief";
import type { ResourceSearchMode } from "../../../../shared/src/resourceSearch";
import type {
  BootstrapData,
  BrowserUploadResourceInput,
  CoachSettingsRequest,
  HostMessage,
  ProviderConfigView,
  SessionMessageRequest,
} from "./types";

export type PreviewProviderActionResult = {
  sessionId: string;
  messages: HostMessage[];
};

export type PreviewProviderDraftInput = {
  name?: string;
  protocol?: string;
  baseUrl?: string;
  model?: string;
  contextWindowTokens?: number | null;
  maxOutputTokens?: number | null;
  modelTokenLimits?: ProviderConfigView["modelTokenLimits"];
  credentialMode?: ProviderConfigView["credentialMode"];
  ignoreSystemProxy?: boolean;
  allowedModels?: string[];
  deniedModels?: string[];
  catalogModels?: string[];
  embeddingModel?: string;
  catalogSource?: ProviderConfigView["catalogSource"];
  cacheTtlSeconds?: number | null;
  apiKey?: string;
  capabilities?: ProviderConfigView["capabilities"] | Record<string, unknown>;
  requestDefaults?: Record<string, unknown>;
  thinkingConfig?: ProviderConfigView["thinkingConfig"];
};

export interface BrowserPreviewResourceSearchRequest {
  query: string;
  requestId: string;
  mode?: ResourceSearchMode;
  topK?: number;
}

/**
 * Pure adapter contract for standalone developer browser-preview surfaces.
 *
 * Production surfaces (VS Code Webview and the Browser Extension Side Panel)
 * never register or bundle the `preview-sidecar` implementation; only the
 * standalone preview harness wires it at runtime.
 */
export interface BrowserPreviewAdapter {
  browserUploadLimit(): number;
  clearBrowserPreviewProvider(sessionId?: string): Promise<PreviewProviderActionResult>;
  ensureBrowserPreviewSidecar(): Promise<string>;
  fetchBrowserPreviewBootstrap(
    sessionId?: string,
    forceLive?: boolean,
  ): Promise<{ sessionId: string; message: HostMessage }>;
  generateBrowserPreviewSkillDraft(
    description: string,
  ): Promise<
    | {
        trigger: string;
        title: string;
        detail: string;
        prompt: string;
        source: "model" | "template";
      }
    | undefined
  >;
  listBrowserPreviewDraftModels(
    draft: PreviewProviderDraftInput,
    apiKey: string,
  ): Promise<string[]>;
  refreshBrowserPreviewProviderModels(
    draftOrSessionId?: PreviewProviderDraftInput | string,
    sessionId?: string,
  ): Promise<PreviewProviderActionResult>;
  refreshBrowserPreviewProviderProfiles(
    sessionId?: string,
  ): Promise<PreviewProviderActionResult>;
  saveBrowserPreviewCoachSettings(
    request: CoachSettingsRequest,
    sessionId?: string,
  ): Promise<{ sessionId: string; message: HostMessage }>;
  saveBrowserPreviewProvider(
    draft: PreviewProviderDraftInput,
    sessionId?: string,
  ): Promise<PreviewProviderActionResult>;
  saveBrowserPreviewProviderProfile(
    draft: PreviewProviderDraftInput,
    sessionId?: string,
  ): Promise<PreviewProviderActionResult>;
  saveBrowserPreviewResearchBrief(
    input: { researchGoal: string; reply: string; resourceIds: string[]; contextId?: string },
    sessionId?: string,
  ): Promise<ResearchBriefView>;
  searchBrowserPreviewResources(
    request: BrowserPreviewResourceSearchRequest,
    sessionId?: string,
  ): Promise<{ sessionId: string; message: HostMessage }>;
  sendBrowserPreviewMessage(
    request: SessionMessageRequest,
    sessionId?: string,
  ): Promise<{ sessionId: string; message: HostMessage }>;
  streamBrowserPreviewMessage(
    request: SessionMessageRequest,
    sessionId: string,
    callbacks: {
      onStart: (message: HostMessage) => void;
      onChunk: (message: HostMessage) => void;
      onComplete: (message: HostMessage, nextSessionId: string) => void;
      onError: (message: HostMessage) => void;
      onCancelled?: (message: HostMessage) => void;
    },
  ): Promise<void>;
  switchBrowserPreviewProviderModel(
    model: string,
    sessionId?: string,
  ): Promise<PreviewProviderActionResult>;
  switchBrowserPreviewProviderProfile(
    profileId: string,
    sessionId?: string,
  ): Promise<PreviewProviderActionResult>;
  testBrowserPreviewProvider(
    draftOrSessionId?: PreviewProviderDraftInput | string,
    sessionId?: string,
  ): Promise<PreviewProviderActionResult>;
  uploadBrowserPreviewResources(
    files: BrowserUploadResourceInput[],
    sessionId?: string,
  ): Promise<{
    sessionId: string;
    patch: Partial<BootstrapData>;
    uploadedCount: number;
    indexedCount: number;
    failedIndexCount: number;
    failedUploadCount: number;
    failedUploads: Array<{ fileName: string; message: string }>;
    truncated: boolean;
  }>;
  useBrowserPreviewProviderTemplate(
    templateLabel?: string,
    sessionId?: string,
  ): Promise<PreviewProviderActionResult>;
}

let registeredAdapter: BrowserPreviewAdapter | undefined;

export function registerBrowserPreviewAdapter(
  adapter: BrowserPreviewAdapter | undefined,
): void {
  registeredAdapter = adapter;
}

export function getBrowserPreviewAdapter(): BrowserPreviewAdapter | undefined {
  return registeredAdapter;
}

export async function requireBrowserPreviewAdapter(): Promise<BrowserPreviewAdapter> {
  if (!registeredAdapter) {
    throw new Error("Browser preview adapter is not installed in this host surface.");
  }
  return registeredAdapter;
}
