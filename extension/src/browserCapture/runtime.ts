import * as vscode from 'vscode';

import { BROWSER_CAPTURE } from '../core/constants';
import type { WorkbenchHost } from '../core/commandContext';
import type { SidecarHttpClient } from '../core/httpClient';
import type { SidecarStatus } from '../core/types';
import { BrowserPairingSession, type BrowserPairingTransport } from './pairingCode';
import { BrowserDraftPoller, COACH_DRAFT_PREFILL_MESSAGE } from './draftPoller';
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
  workbench: BrowserCaptureWorkbench;
  outputChannel: Pick<vscode.OutputChannel, 'appendLine'>;
  /** Overrides the VS Code UI locale used for host-side copy (test seam). */
  hostLanguage?: string;
  intervalMs?: number;
}

export interface BrowserCaptureRuntime {
  pairing: BrowserPairingSession;
  drafts: BrowserDraftPoller;
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
}): BrowserPairingTransport {
  return {
    async registerPairingCode(request) {
      const port = await deps.ensureSidecarPort();
      await deps.sidecarClient.postJson(port, BROWSER_CAPTURE.pairCodePath, request);
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
  });

  const pairing = new BrowserPairingSession({ transport });
  const drafts = new BrowserDraftPoller({
    intervalMs: deps.intervalMs,
    getSidecarPort: () => {
      const status = deps.getSidecarStatus();
      return status.lifecycle === 'ready' ? status.port : undefined;
    },
    isWorkbenchVisible: () => deps.workbench.isVisible?.() === true,
    fetchPendingDrafts: (port) => sidecarClient.getJson(port, BROWSER_CAPTURE.pendingDraftsPath),
    acknowledgeDrafts: (port, ids) =>
      sidecarClient.postJson(port, BROWSER_CAPTURE.pendingDraftsAckPath, { ids }),
    forwardDraft: (text) => workbench.postMessage({ type: COACH_DRAFT_PREFILL_MESSAGE, text }),
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
    uriHandler,
    handleDeepLink: (uri) =>
      handleTrainerDeepLink({ workbench: deepLinkWorkbench, outputChannel, language }, uri),
    dispose: () => drafts.dispose(),
  };
}

export type { TrainerLibraryDeepLink };
