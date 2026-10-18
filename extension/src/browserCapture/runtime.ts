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
import { resolveBrowserCaptureCopyLanguage } from './hostCopy';
import {
  createTrainerUriHandler,
  handleTrainerDeepLink,
  type TrainerLibraryDeepLink,
} from './deepLink';

/**
 * One long-lived browser-capture runtime per extension host: the pairing
 * ledger, the draft poller and the deep-link entry all share the same sidecar
 * client and workbench facade.
 */

export interface BrowserCaptureWorkbench extends Pick<WorkbenchHost, 'show' | 'postMessage'> {
  isVisible?: () => boolean;
}

export interface BrowserCaptureRuntimeDeps {
  sidecarClient: Pick<SidecarHttpClient, 'getJson' | 'postJson' | 'deleteJson'>;
  /** Sidecar lifecycle without side effects: polling must never start it. */
  getSidecarStatus: () => Pick<SidecarStatus, 'lifecycle' | 'port'>;
  /** User-initiated commands (pairing/revoke) may start the sidecar. */
  ensureSidecarPort: () => Promise<number>;
  /**
   * The runtime workspace id: pairing binds it and the draft queue is polled
   * and acknowledged strictly scoped to it.
   */
  getWorkspaceId: () => string;
  workbench: BrowserCaptureWorkbench;
  outputChannel: Pick<vscode.OutputChannel, 'appendLine'>;
  /** Overrides the VS Code UI locale used for host-side copy (test seam). */
  hostLanguage?: string;
  intervalMs?: number;
  /** How long a forwarded draft waits for its applied receipt (test seam). */
  receiptTimeoutMs?: number;
}

export interface BrowserCaptureRuntime {
  pairing: BrowserPairingSession;
  drafts: BrowserDraftPoller;
  /**
   * Applied receipt for `ui/coachDraftPrefill` (from the workbench webview):
   * resolves the delivery wait of the draft with this id.
   */
  notifyDraftApplied(draftId: string): void;
  uriHandler: vscode.UriHandler;
  handleDeepLink(uri: { path?: string; query?: string; toString(): string }): Promise<{
    handled: boolean;
    resourceId?: string;
  }>;
  dispose(): void;
}

/** Sidecar-backed pairing transport shared by the runtime and command fallback. */
export function createSidecarPairingTransport(deps: {
  sidecarClient: Pick<SidecarHttpClient, 'postJson' | 'deleteJson'>;
  ensureSidecarPort: () => Promise<number>;
  /**
   * Binds the pairing code to the workspace the host is working in, so the
   * credential (and every capture it makes) belongs to exactly that workspace.
   */
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

/** VS Code UI locale, when the extension host exposes one. */
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
  const drafts = new BrowserDraftPoller({
    intervalMs: deps.intervalMs,
    getWorkspaceId: () => deps.getWorkspaceId(),
    getSidecarPort: () => {
      const status = deps.getSidecarStatus();
      return status.lifecycle === 'ready' ? status.port : undefined;
    },
    isWorkbenchVisible: () => deps.workbench.isVisible?.() === true,
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
      // Register the receipt wait before posting: a retried draft (posted
      // again after a lost receipt) may be answered before postMessage even
      // returns, and that answer still confirms this delivery.
      const receipt = receipts.waitForReceipt(draft.id, receiptTimeoutMs);
      await workbench.postMessage({
        type: COACH_DRAFT_PREFILL_MESSAGE,
        draftId: draft.id,
        text: draft.text,
      });
      if (!(await receipt)) {
        throw new Error(`draft ${draft.id} was not confirmed by the workbench`);
      }
    },
    onError: (message) => log(`draft forwarding skipped: ${message}`),
  });

  const deepLinkWorkbench = {
    show: () => workbench.show(),
    postMessage: (message: unknown) => workbench.postMessage(message),
    isVisible: workbench.isVisible,
  };
  const uriHandler = createTrainerUriHandler({ workbench: deepLinkWorkbench, outputChannel, language });

  return {
    pairing,
    drafts,
    notifyDraftApplied: (draftId: string) => receipts.notify(draftId),
    uriHandler,
    handleDeepLink: (uri) =>
      handleTrainerDeepLink({ workbench: deepLinkWorkbench, outputChannel, language }, uri),
    dispose: () => drafts.dispose(),
  };
}

export type { TrainerLibraryDeepLink };
