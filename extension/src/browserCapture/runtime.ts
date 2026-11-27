import * as vscode from 'vscode';

import { BROWSER_CAPTURE } from '../core/constants';
import type { WorkbenchHost } from '../core/commandContext';
import type { SidecarHttpClient } from '../core/httpClient';
import type { SidecarStatus } from '../core/types';
import { BrowserPairingSession, type BrowserPairingTransport } from './pairingCode';
import {
  BrowserDraftPoller,
  COACH_DRAFT_PREFILL_MESSAGE,
  DraftReceiptChannel,
  type PendingBrowserDraft,
} from './draftPoller';
import {
  BrowserWorkspaceEventStream,
  type OpenWorkspaceEventStreamFn,
} from './eventStream';
import { resolveBrowserCaptureCopyLanguage } from './hostCopy';
import { BrowserLibraryPoller } from './libraryPoller';
import {
  createTrainerUriHandler,
  handleTrainerDeepLink,
  type TrainerLibraryDeepLink,
} from './deepLink';

export interface BrowserCaptureWorkbench extends Pick<WorkbenchHost, 'show' | 'postMessage'> {
  isVisible?: () => boolean;
}

export interface BrowserCaptureRuntimeDeps {
  sidecarClient: Pick<SidecarHttpClient, 'getJson' | 'postJson' | 'deleteJson'> & {
    openEventStream?: OpenWorkspaceEventStreamFn;
  };
  getSidecarStatus: () => Pick<SidecarStatus, 'lifecycle' | 'port'>;
  ensureSidecarPort: () => Promise<number>;
  getWorkspaceId: () => string;
  workbench: BrowserCaptureWorkbench;
  outputChannel: Pick<vscode.OutputChannel, 'appendLine'>;
  hostLanguage?: string;
  intervalMs?: number;
  receiptTimeoutMs?: number;
  refreshLibrary?: () => Promise<void>;
}

export interface BrowserCaptureRuntime {
  pairing: BrowserPairingSession;
  drafts: BrowserDraftPoller;
  library: BrowserLibraryPoller;
  events: BrowserWorkspaceEventStream;
  notifyDraftApplied(draftId: string): void;
  uriHandler: vscode.UriHandler;
  handleDeepLink(uri: { path?: string; query?: string; toString(): string }): Promise<{
    handled: boolean;
    resourceId?: string;
  }>;
  dispose(): void;
}

export function createSidecarPairingTransport(deps: {
  sidecarClient: Pick<SidecarHttpClient, 'postJson' | 'deleteJson'>;
  ensureSidecarPort: () => Promise<number>;
  workspaceId?: () => string;
}): BrowserPairingTransport {
  return {
    async registerPairingCode(request) {
      const port = await deps.ensureSidecarPort();
      const workspaceId = deps.workspaceId?.().trim();
      await deps.sidecarClient.postJson(port, BROWSER_CAPTURE.pairCodePath, {
        ...request,
        ...(workspaceId ? { workspace_id: workspaceId } : {}),
      });
    },
    async revokePairing() {
      const port = await deps.ensureSidecarPort();
      await deps.sidecarClient.deleteJson(port, BROWSER_CAPTURE.pairPath);
    },
  };
}

function readVscodeUiLanguage(): string | undefined {
  try {
    const language = vscode.env?.language;
    return typeof language === 'string' ? language : undefined;
  } catch {
    return undefined;
  }
}

export function createBrowserCaptureRuntime(
  deps: BrowserCaptureRuntimeDeps,
): BrowserCaptureRuntime {
  const { sidecarClient, workbench, outputChannel } = deps;
  const language = resolveBrowserCaptureCopyLanguage(deps.hostLanguage ?? readVscodeUiLanguage());
  const log = (message: string): void => outputChannel.appendLine(`[browser-capture] ${message}`);

  const transport = createSidecarPairingTransport({
    sidecarClient,
    ensureSidecarPort: deps.ensureSidecarPort,
    workspaceId: deps.getWorkspaceId,
  });

  const pairing = new BrowserPairingSession({ transport });
  const receipts = new DraftReceiptChannel();
  const receiptTimeoutMs = deps.receiptTimeoutMs ?? BROWSER_CAPTURE.draftReceiptTimeoutMs;
  const resolveReadyPort = (): number | undefined => {
    const status = deps.getSidecarStatus();
    return status.lifecycle === 'ready' ? status.port : undefined;
  };
  const isWorkbenchVisible = (): boolean => deps.workbench.isVisible?.() === true;

  let eventsRef: BrowserWorkspaceEventStream | undefined;

  const drafts = new BrowserDraftPoller({
    intervalMs: deps.intervalMs,
    getWorkspaceId: () => deps.getWorkspaceId(),
    getSidecarPort: resolveReadyPort,
    isWorkbenchVisible,
    shouldSkipTimerPoll: () => eventsRef?.connected === true,
    fetchPendingDrafts: (port, workspaceId) =>
      sidecarClient.getJson(
        port,
        `${BROWSER_CAPTURE.pendingDraftsPath}?workspace_id=${encodeURIComponent(workspaceId)}`,
      ),
    acknowledgeDrafts: (port, workspaceId, ids) =>
      sidecarClient.postJson(port, BROWSER_CAPTURE.pendingDraftsAckPath, {
        workspace_id: workspaceId,
        ids,
      }),
    forwardDraft: async (draft: PendingBrowserDraft) => {
      const receipt = receipts.waitForReceipt(draft.id, receiptTimeoutMs);
      await workbench.postMessage({
        type: COACH_DRAFT_PREFILL_MESSAGE,
        draftId: draft.id,
        text: draft.text,
        workspaceId: draft.workspaceId,
        ...(draft.source ? { source: draft.source } : {}),
      });
      if (!(await receipt)) {
        throw new Error(`draft ${draft.id} was not confirmed by the workbench`);
      }
    },
    onError: (message) => log(`draft forwarding skipped: ${message}`),
  });

  const library = new BrowserLibraryPoller({
    getSidecarPort: resolveReadyPort,
    isWorkbenchVisible,
    getWorkspaceId: () => deps.getWorkspaceId(),
    shouldSkipTimerPoll: () => eventsRef?.connected === true,
    fetchLibraryRevision: (port, workspaceId) =>
      sidecarClient.getJson(
        port,
        `${BROWSER_CAPTURE.libraryRevisionPath}?workspace_id=${encodeURIComponent(workspaceId)}`,
      ),
    refreshLibrary: async () => {
      if (deps.refreshLibrary) {
        await deps.refreshLibrary();
      }
    },
    intervalMs: deps.intervalMs,
    onError: (message) => log(`library refresh skipped: ${message}`),
  });

  const events = new BrowserWorkspaceEventStream({
    openEventStream: sidecarClient.openEventStream
      ? (port, path, options) => sidecarClient.openEventStream!(port, path, options)
      : undefined,
    getSidecarPort: resolveReadyPort,
    isWorkbenchVisible,
    getWorkspaceId: () => deps.getWorkspaceId(),
    onDraftsPayload: async (payload) => {
      await drafts.pushDraftsPayload(payload);
    },
    onLibraryPayload: async (payload) => {
      await library.pushLibraryPayload(payload);
    },
    onError: (message) => log(`event stream reconnecting: ${message}`),
  });
  eventsRef = events;

  const deepLinkWorkbench = {
    show: () => workbench.show(),
    postMessage: (message: unknown) => workbench.postMessage(message),
    isVisible: workbench.isVisible,
  };
  const uriHandler = createTrainerUriHandler({ workbench: deepLinkWorkbench, outputChannel, language });

  return {
    pairing,
    drafts,
    library,
    events,
    notifyDraftApplied: (draftId: string) => receipts.notify(draftId),
    uriHandler,
    handleDeepLink: (uri) =>
      handleTrainerDeepLink({ workbench: deepLinkWorkbench, outputChannel, language }, uri),
    dispose: () => {
      events.dispose();
      drafts.dispose();
      library.dispose();
    },
  };
}

export type { TrainerLibraryDeepLink };
