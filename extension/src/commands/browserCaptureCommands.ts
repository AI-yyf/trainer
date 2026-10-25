import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import * as vscode from 'vscode';

import type { ComposerLanguage } from '../../../shared/src/types';
import { BROWSER_CAPTURE } from '../core/constants';
import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';
import { getRuntimeWorkspaceContext } from './workspaceContext';
import {
  BrowserPairingSession,
  type BrowserPairingIssue,
} from '../browserCapture/pairingCode';
import { createSidecarPairingTransport } from '../browserCapture/runtime';
import {
  browserCaptureHostCopy,
  resolveBrowserCaptureCopyLanguage,
  type BrowserCaptureHostCopyKey,
} from '../browserCapture/hostCopy';
import {
  CaptureBundleSourceError,
  captureInstallGuide,
  readCaptureBundleMarker,
  resolveInstalledCaptureDir,
  installCaptureBundle,
  openCaptureFolder,
  resolveCaptureInstallDir,
} from '../browserCapture/installBundle';
import {
  detectChromiumBrowsers,
  openBrowserExtensionsPage,
  type ChromiumBrowser,
} from '../browserCapture/browserLauncher';
import {
  CAPTURE_ONBOARDING_PROMPTED_FLAG,
  shouldPromptCaptureOnboarding,
} from '../browserCapture/onboarding';

/** Host-side copy for the current VS Code UI locale (en-US fallback). */
function resolveHostLanguage(): ComposerLanguage {
  return resolveBrowserCaptureCopyLanguage(vscode.env?.language);
}

function hostCopy(
  language: ComposerLanguage,
): (key: BrowserCaptureHostCopyKey, params?: Record<string, string | number>) => string {
  return (key, params) => browserCaptureHostCopy(language, key, params);
}

/**
 * Fallback sessions keep the pairing ledger per command context when the host
 * runtime has not been wired (older activation paths, isolated tests). The
 * extension host always installs its runtime on `CommandContext.browserCapture`.
 */
const fallbackSessions = new WeakMap<object, BrowserPairingSession>();

export function resolveBrowserCapturePairingSession(context: CommandContext): BrowserPairingSession {
  const wired = context.browserCapture?.pairing;
  if (wired) {
    return wired;
  }
  let session = fallbackSessions.get(context);
  if (!session) {
    const copy = hostCopy(resolveHostLanguage());
    session = new BrowserPairingSession({
      transport: createSidecarPairingTransport({
        sidecarClient: context.sidecarClient,
        workspaceId: () => getRuntimeWorkspaceContext(context).workspaceId,
        ensureSidecarPort: async () => {
          const status = await context.sidecarManager.ensureRunning();
          if (status.lifecycle !== 'ready' || !status.port) {
            throw new Error(status.detail ?? copy('sidecarUnavailable'));
          }
          return status.port;
        },
      }),
    });
    fallbackSessions.set(context, session);
  }
  return session;
}

/**
 * `trainer.browserCapture.install`: copy the VSIX-bundled capture extension
 * into the managed `~/.trainer/browser-capture` directory, open that directory
 * in the OS file manager, and hand the user the three-step Load unpacked guide.
 */
interface PreparedCaptureBundle {
  targetDir: string;
  fileCount: number;
  version?: string;
}

/** Stage the bundled capture extension into the per-user install dir. */
function prepareCaptureBundle(context: CommandContext): PreparedCaptureBundle {
  const bundleDir = vscode.Uri.joinPath(
    context.extensionContext.extensionUri,
    BROWSER_CAPTURE.bundleDirName,
  ).fsPath;
  if (!fs.existsSync(path.join(bundleDir, 'manifest.json'))) {
    throw new CaptureBundleSourceError('missing-bundle');
  }
  const targetDir = resolveCaptureInstallDir({ homeDir: os.homedir() });
  return installCaptureBundle({ sourceDir: bundleDir, targetDir });
}

export async function installBrowserCaptureCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const language = resolveHostLanguage();
  const copy = hostCopy(language);
  let installed: PreparedCaptureBundle;
  try {
    installed = prepareCaptureBundle(context);
  } catch (error) {
    const reason =
      error instanceof CaptureBundleSourceError
        ? copy('installBundleMissing')
        : error instanceof Error
          ? error.message
          : String(error);
    context.outputChannel.appendLine(`[browser-capture] install failed: ${reason}`);
    return { ok: false, message: copy('installFailed', { reason }) };
  }

  const opened = openCaptureFolder(installed.targetDir);
  context.outputChannel.appendLine(
    `[browser-capture] installed ${installed.fileCount} files to ${installed.targetDir} (folder opener: ${opened.command}, spawned: ${opened.spawned})`,
  );

  let guide = captureInstallGuide({ targetDir: installed.targetDir, version: installed.version, language });
  if (!opened.spawned) {
    // Headless hosts without open/explorer/xdg-open: the path on the bar is the
    // degraded fallback, said in the user's language.
    guide = `${guide}\n${copy('installFolderFallback', { dir: installed.targetDir })}`;
  }
  const copyPathLabel = copy('copyFolderPath');
  const openPageLabel = copy('openExtensionsPage');
  void vscode.window.showInformationMessage(guide, copyPathLabel, openPageLabel).then((choice) => {
    if (choice === copyPathLabel) {
      void vscode.env.clipboard.writeText(installed.targetDir);
    } else if (choice === openPageLabel) {
      void openBrowserExtensionsPageCommand(context);
    }
  });

  const label = installed.version ? `Trainer Capture ${installed.version}` : 'Trainer Capture';
  return {
    ok: true,
    message: copy('installSucceeded', { label, dir: installed.targetDir }),
    data: { targetDir: installed.targetDir, version: installed.version, fileCount: installed.fileCount },
  };
}

/**
 * Owner-directed per-browser install (T-0050): detect the installed
 * Chromium-family browsers, let the user pick one, stage the bundle, and open
 * THAT browser's own extensions page with the install path already on the
 * clipboard. Branded browsers refuse silent installs, so the remaining
 * developer-mode steps are stated in one message — this is the closest a
 * non-store install can get to one click; the store publish later turns it
 * into a literal one-click.
 */
export async function installBrowserCaptureForBrowserCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const language = resolveHostLanguage();
  const copy = hostCopy(language);
  const detected = detectChromiumBrowsers();
  if (detected.length === 0) {
    void vscode.window.showInformationMessage(copy('noChromiumBrowserFound'));
    return { ok: false, message: copy('noChromiumBrowserFound') };
  }
  const pick = await vscode.window.showQuickPick(
    detected.map((browser) => ({ label: `$(${browser.id === 'edge' ? 'edge' : 'browser'}) ${browser.label}`, browser })),
    { placeHolder: copy('pickBrowserPlaceholder') },
  );
  if (!pick) {
    return { ok: false, message: 'cancelled' };
  }
  let installed: PreparedCaptureBundle;
  try {
    installed = prepareCaptureBundle(context);
  } catch (error) {
    const reason =
      error instanceof CaptureBundleSourceError
        ? copy('installBundleMissing')
        : error instanceof Error
          ? error.message
          : String(error);
    context.outputChannel.appendLine(`[browser-capture] install failed: ${reason}`);
    return { ok: false, message: copy('installFailed', { reason }) };
  }
  const opened = openBrowserExtensionsPage(pick.browser);
  await vscode.env.clipboard.writeText(installed.targetDir).then(() => undefined, () => undefined);
  context.outputChannel.appendLine(
    `[browser-capture] per-browser install: ${installed.fileCount} files to ${installed.targetDir}; opened ${pick.browser.label} extensions page (spawned: ${opened.spawned})`,
  );
  const doneMessage = copy('installForBrowserDone', {
    browser: pick.browser.label,
    dir: installed.targetDir,
  });
  const openFolderLabel = copy('copyFolderPath');
  void vscode.window
    .showInformationMessage(doneMessage, openFolderLabel)
    .then((choice) => {
      if (choice === openFolderLabel) {
        openCaptureFolder(installed.targetDir);
      }
    });
  const label = installed.version ? `Trainer Capture ${installed.version}` : 'Trainer Capture';
  return {
    ok: true,
    message: copy('installSucceeded', { label, dir: installed.targetDir }),
    data: {
      targetDir: installed.targetDir,
      version: installed.version,
      fileCount: installed.fileCount,
      browser: pick.browser.id,
    },
  };
}

/**
 * First-run onboarding (owner direction): on the first activation after
 * install, offer the browser capture setup once. The flag is written before
 * the prompt renders so a dropped notification can never become a nag; the
 * picker stays reachable from the command palette and the Settings card.
 */
export async function maybePromptCaptureOnboarding(context: CommandContext): Promise<void> {
  const language = resolveHostLanguage();
  const copy = hostCopy(language);
  const prompted = Boolean(
    context.extensionContext.globalState.get(CAPTURE_ONBOARDING_PROMPTED_FLAG),
  );
  const prepared = fs.existsSync(
    path.join(resolveInstalledCaptureDir(os.homedir()), 'manifest.json'),
  );
  // Pairing state needs the sidecar; checking it here would couple first-run
  // to service readiness (§5.1 UI never waits on network). The prompted flag
  // keeps this exactly-once either way, and an already-paired user pays at
  // most one dismiss.
  if (!shouldPromptCaptureOnboarding({ prompted, prepared, paired: false })) {
    return;
  }
  await context.extensionContext.globalState.update(CAPTURE_ONBOARDING_PROMPTED_FLAG, true);
  const installLabel = copy('onboardingInstall');
  const choice = await vscode.window.showInformationMessage(
    copy('onboardingPrompt'),
    installLabel,
    copy('onboardingNotNow'),
  );
  if (choice === installLabel) {
    await installBrowserCaptureForBrowserCommand(context);
  }
}

export interface BrowserCaptureInstallStatus {
  prepared: boolean;
  paired: boolean;
  capturedCount: number | null;
  version?: string;
  installDir: string;
}

/**
 * Real install/pair state for the Settings card (T-0024). "Loaded in the
 * browser" is intentionally unknowable from the host — the card treats the
 * pairing state as the actionable signal instead of inventing a step we
 * cannot observe.
 */
export async function browserCaptureInstallStatus(
  context: CommandContext,
): Promise<BrowserCaptureInstallStatus> {
  const installDir = resolveInstalledCaptureDir(os.homedir());
  const marker = readCaptureBundleMarker(path.join(installDir, BROWSER_CAPTURE.versionFileName));
  const prepared = fs.existsSync(path.join(installDir, 'manifest.json'));
  const status = context.sidecarManager.getStatus();
  let paired = false;
  let capturedCount: number | null = null;
  if (status.lifecycle === 'ready' && status.port) {
    try {
      const workspaceId = getRuntimeWorkspaceContext(context).workspaceId;
      const summary = await context.sidecarClient.getJson<{
        library_count?: number;
      }>(status.port, `/browser/status?workspace_id=${encodeURIComponent(workspaceId)}`);
      capturedCount = typeof summary.library_count === 'number' ? summary.library_count : null;
      paired = true;
    } catch (error) {
      // 401/absent pairing both land here: the card shows "not paired".
      context.outputChannel.appendLine(
        `[browser-capture] status probe failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }
  return { prepared, paired, capturedCount, version: marker?.version, installDir };
}

/**
 * `trainer.browserCapture.status`: JSON payload for the Settings card.
 */
export async function browserCaptureStatusCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const status = await browserCaptureInstallStatus(context);
  await context.workbench.postMessage({
    type: 'browserCapture/statusResult',
    payload: {
      prepared: status.prepared,
      paired: status.paired,
      capturedCount: status.capturedCount,
      version: status.version,
    },
  });
  return { ok: true, data: status, message: '' };
}

/**
 * `trainer.browserCapture.openExtensionsPage`: open the correct native
 * extensions page in a detected Chromium browser. Branded browsers do not
 * allow silent unpacked installs, so this removes the URL-typing and
 * browser-choosing steps while keeping the user in control of the actual
 * "Load unpacked" confirmation.
 */
export async function openBrowserExtensionsPageCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const copy = hostCopy(resolveHostLanguage());
  const browsers = detectChromiumBrowsers();
  if (browsers.length === 0) {
    void vscode.window.showInformationMessage(copy('noChromiumBrowserFound'));
    return { ok: false, message: copy('noChromiumBrowserFound') };
  }

  let browser: ChromiumBrowser = browsers[0];
  if (browsers.length > 1) {
    const picked = await vscode.window.showQuickPick(
      browsers.map((candidate) => ({
        label: candidate.label,
        description: candidate.extensionsUrl,
        browser: candidate,
      })),
      { placeHolder: copy('openExtensionsPage') },
    );
    if (!picked) {
      return { ok: true, cancelled: true };
    }
    browser = picked.browser;
  }

  const opened = openBrowserExtensionsPage(browser);
  if (!opened.spawned) {
    const message = copy('browserOpenFailed', {
      browser: browser.label,
      reason: `${opened.command} ${opened.args.join(' ')}`,
    });
    context.outputChannel.appendLine(`[browser-capture] ${message}`);
    void vscode.window.showWarningMessage(message);
    return { ok: false, message };
  }
  context.outputChannel.appendLine(
    `[browser-capture] opened ${browser.label} extensions page (${browser.extensionsUrl})`,
  );
  return {
    ok: true,
    message: `${browser.label} · ${browser.extensionsUrl}`,
    data: { browserId: browser.id, extensionsUrl: browser.extensionsUrl },
  };
}

/**
 * `trainer.browserCapture.pairingCode`: mint a 6-digit, 10-minute, single-use
 * code, register it with the sidecar (`POST /browser/pair-code`) and show it on
 * an information bar with a copy action. The browser redeems it itself via
 * `POST /browser/pair {code}`.
 */
export async function browserCapturePairingCodeCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const copy = hostCopy(resolveHostLanguage());
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? copy('sidecarUnavailable') };
  }

  let issue: BrowserPairingIssue;
  try {
    issue = await resolveBrowserCapturePairingSession(context).issuePairingCode();
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    context.outputChannel.appendLine(`[browser-capture] pairing code registration failed: ${reason}`);
    return { ok: false, message: copy('pairingRegisterFailed', { reason }) };
  }

  const summary = copy(
    issue.expiresInMinutes === 1 ? 'pairingCodeSummaryOne' : 'pairingCodeSummaryMany',
    { minutes: issue.expiresInMinutes },
  );
  const copyCodeLabel = copy('copyCode');
  void vscode.window.showInformationMessage(`${issue.code} — ${summary}`, copyCodeLabel).then((choice) => {
    if (choice === copyCodeLabel) {
      void vscode.env.clipboard.writeText(issue.code);
    }
  });
  context.outputChannel.appendLine(
    `[browser-capture] pairing code issued (expires at ${new Date(issue.expiresAt).toISOString()})`,
  );

  return {
    ok: true,
    message: copy('pairingCodeIssued'),
    data: {
      expiresAt: issue.expiresAt,
      expiresInSeconds: issue.expiresInSeconds,
      regenerated: issue.regenerated,
    },
  };
}

/**
 * `trainer.browserCapture.revokePairing`: `DELETE /browser/pair`, then drop the
 * local ledger entry so the host stops offering the revoked code.
 */
export async function revokeBrowserCapturePairingCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const copy = hostCopy(resolveHostLanguage());
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? copy('sidecarUnavailable') };
  }

  const result = await resolveBrowserCapturePairingSession(context).revokePairing();
  if (!result.revoked) {
    context.outputChannel.appendLine(`[browser-capture] pairing revocation failed: ${result.error ?? 'unknown'}`);
    return {
      ok: false,
      message: copy('pairingRevokeFailed', { reason: result.error ?? 'unknown' }),
    };
  }

  return {
    ok: true,
    message: result.hadRegistration ? copy('pairingRevokedHadCode') : copy('pairingRevokedIdle'),
    data: { hadRegistration: result.hadRegistration },
  };
}
