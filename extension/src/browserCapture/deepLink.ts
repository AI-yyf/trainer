import type * as vscode from 'vscode';

import type { ComposerLanguage } from '../../../shared/src/types';
import type { WorkbenchHost } from '../core/commandContext';
import {
  browserCaptureHostCopy,
  type BrowserCaptureHostCopyKey,
} from './hostCopy';

/**
 * Deep-link host for the browser capture lane.
 *
 * `vscode://local.trainer-extension/library/<resourceId>` focuses the Trainer
 * workbench and hands the resource to the webview as a host-authored message.
 * The message is flat by contract (`{type, resourceId}`), because the webview
 * landing point is implemented alongside the capture extension.
 */

export const OPEN_RESOURCE_MESSAGE = 'ui/openResource';

export interface TrainerLibraryDeepLink {
  kind: 'library';
  resourceId: string;
}

const RESOURCE_ID_PATTERN = /^[A-Za-z0-9._~:@+-]{1,256}$/;

export function parseTrainerDeepLink(uri: { path?: string; query?: string }): TrainerLibraryDeepLink | undefined {
  const rawPath = typeof uri.path === 'string' ? uri.path : '';
  const match = /^\/library\/([^/]+)\/?$/.exec(rawPath);
  let candidate = match?.[1];
  if (!candidate) {
    // Tolerate the query form (`...?resourceId=<id>`) that some clients mint.
    const query = typeof uri.query === 'string' ? uri.query : '';
    const params = new URLSearchParams(query);
    candidate = params.get('resourceId') ?? undefined;
  }
  if (!candidate) {
    return undefined;
  }
  let resourceId: string;
  try {
    resourceId = decodeURIComponent(candidate);
  } catch {
    return undefined;
  }
  if (!RESOURCE_ID_PATTERN.test(resourceId)) {
    return undefined;
  }
  return { kind: 'library', resourceId };
}

export interface TrainerUriHandlerDeps {
  workbench: Pick<WorkbenchHost, 'show' | 'postMessage'> & { isVisible?: () => boolean };
  outputChannel: Pick<vscode.OutputChannel, 'appendLine'>;
  /** Copy language for the output-channel diagnostics (defaults to en-US). */
  language?: ComposerLanguage;
  /** Test seam: awaited between delivery attempts (defaults to a real timer). */
  delayFn?: (milliseconds: number) => Promise<void>;
}

/** Output-channel diagnostics in the caller's language (en-US when unset). */
function logCopy(
  deps: TrainerUriHandlerDeps,
): (key: BrowserCaptureHostCopyKey, params?: Record<string, string | number>) => string {
  const language = deps.language ?? 'en-US';
  return (key, params) => browserCaptureHostCopy(language, key, params);
}

const MAX_DELIVERY_ATTEMPTS = 6;
const DELIVERY_RETRY_MS = 300;

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

/**
 * A deep link can be the first thing that touches the workbench in a window:
 * `show()` reveals the container and VS Code resolves the webview view
 * asynchronously, so the first post can land before any surface exists. Retry
 * (bounded) until the workbench reports itself visible; an openResource
 * message is idempotent for the webview, so a repeat is harmless.
 */
async function deliverOpenResource(
  deps: TrainerUriHandlerDeps,
  resourceId: string,
): Promise<number> {
  const message = { type: OPEN_RESOURCE_MESSAGE, resourceId };
  for (let attempt = 0; attempt < MAX_DELIVERY_ATTEMPTS; attempt += 1) {
    await deps.workbench.postMessage(message);
    if (deps.workbench.isVisible?.() !== false) {
      return attempt + 1;
    }
    if (attempt < MAX_DELIVERY_ATTEMPTS - 1) {
      await (deps.delayFn ?? delay)(DELIVERY_RETRY_MS);
    }
  }
  deps.outputChannel.appendLine(
    `[browser-capture] ${logCopy(deps)('deepLinkUnconfirmedLog', {
      resourceId,
      attempts: MAX_DELIVERY_ATTEMPTS,
    })}`,
  );
  return MAX_DELIVERY_ATTEMPTS;
}

export function createTrainerUriHandler(deps: TrainerUriHandlerDeps): vscode.UriHandler {
  return {
    async handleUri(uri: vscode.Uri): Promise<void> {
      await handleTrainerDeepLink(deps, uri);
    },
  };
}

export async function handleTrainerDeepLink(
  deps: TrainerUriHandlerDeps,
  uri: { path?: string; query?: string; toString(): string },
): Promise<{ handled: boolean; resourceId?: string; deliveryAttempts?: number }> {
  const target = parseTrainerDeepLink(uri);
  if (!target) {
    deps.outputChannel.appendLine(
      `[browser-capture] ${logCopy(deps)('deepLinkIgnoredLog', { uri: uri.toString() })}`,
    );
    return { handled: false };
  }
  await deps.workbench.show();
  const deliveryAttempts = await deliverOpenResource(deps, target.resourceId);
  deps.outputChannel.appendLine(
    `[browser-capture] ${logCopy(deps)('deepLinkOpenedLog', {
      resourceId: target.resourceId,
      attempts: deliveryAttempts,
    })}`,
  );
  return { handled: true, resourceId: target.resourceId, deliveryAttempts };
}
