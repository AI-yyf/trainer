import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import * as vscode from 'vscode';

import type { ComposerLanguage } from '../../../shared/src/types';
import { BROWSER_CAPTURE, SIDECAR_DEFAULTS } from '../core/constants';
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
  installCaptureBundle,
  openCaptureFolder,
  readCaptureBundleMarker,
  resolveCaptureInstallDir,
  resolveInstalledCaptureDir,
  resolveManagedBrowserProfileDir,
  writeBootstrapPairSeed,
  type BootstrapPairSeed,
} from '../browserCapture/installBundle';
import {
  detectChromiumBrowsers,
  launchBrowserWithExtension,
  openBrowserExtensionsPage,
  type ChromiumBrowser,
} from '../browserCapture/browserLauncher';
import {
  CAPTURE_ONBOARDING_PROMPTED_FLAG,
  shouldPromptCaptureOnboarding,
} from '../browserCapture/onboarding';

function resolveHostLanguage(): ComposerLanguage {
  return resolveBrowserCaptureCopyLanguage(vscode.env?.language);
}

function hostCopy(
  language: ComposerLanguage,
): (key: BrowserCaptureHostCopyKey, params?: Record<string, string | number>) => string {
  return (key, params) => browserCaptureHostCopy(language, key, params);
}

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

interface PreparedCaptureBundle {
  targetDir: string;
  fileCount: number;
  version?: string;
}

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

/**
 * Mint a single-use cryptographic handshake token on the running Sidecar and
 * write `bootstrap-pair.json` into `~/.trainer/browser-capture` so the browser
 * extension pairs automatically on load with zero 6-digit code entry.
 */
export async function seedBootstrapHandshake(
  context: CommandContext,
  targetDir: string,
): Promise<BootstrapPairSeed | undefined> {
  try {
    const status = await context.sidecarManager.ensureRunning();
    if (status.lifecycle !== 'ready' || !status.port) {
      return undefined;
    }
    const runtimeWorkspace = getRuntimeWorkspaceContext(context);
    const workspaceId = runtimeWorkspace.workspaceId.trim();
    if (!workspaceId) {
      return undefined;
    }
    const issue = await resolveBrowserCapturePairingSession(context).issueBootstrapToken();
    const hostState = context.getHostState();
    const workspaceName =
      hostState.bootstrap?.workspaceName?.trim() ||
      path.basename(hostState.workspace?.workspaceFolder || workspaceId) ||
      workspaceId;
    const seed: BootstrapPairSeed = {
      schemaVersion: 1,
      code: issue.code,
      baseUrl: `http://${SIDECAR_DEFAULTS.host}:${status.port}`,
      workspaceId,
      workspaceName,
      issuedAt: Date.now(),
      expiresAt: issue.expiresAt,
    };
    writeBootstrapPairSeed(targetDir, seed);
    context.outputChannel.appendLine(
      `[browser-capture] pre-seeded single-use handshake in ${path.join(targetDir, BROWSER_CAPTURE.bootstrapPairFileName)}`,
    );
    return seed;
  } catch (error) {
    context.outputChannel.appendLine(
      `[browser-capture] bootstrap handshake pre-seed skipped: ${error instanceof Error ? error.message : String(error)}`,
    );
    return undefined;
  }
}

async function pickDetectedBrowser(
  detected: ChromiumBrowser[],
  placeHolder: string,
  preferredBrowserId?: string,
): Promise<ChromiumBrowser | 'cancelled' | undefined> {
  if (detected.length === 0) {
    return undefined;
  }
  if (preferredBrowserId) {
    const matched = detected.find((item) => item.id === preferredBrowserId);
    if (matched) {
      return matched;
    }
  }
  if (detected.length === 1) {
    return detected[0];
  }
  const picked = await vscode.window.showQuickPick(
    detected.map((browser) => ({
      label: `$(${browser.id === 'edge' ? 'edge' : 'browser'}) ${browser.label}`,
      description: browser.extensionsUrl,
      browser,
    })),
    { placeHolder },
  );
  return picked ? picked.browser : 'cancelled';
}

/**
 * `trainer.browserCapture.launch`: One-click launch an adapted Chromium browser
 * profile (`~/.trainer/browser-profile`) with the shared Trainer Side Panel
 * extension pre-loaded (`--load-extension`) and pre-paired (`bootstrap-pair.json`).
 */
export async function launchBrowserCaptureCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const language = resolveHostLanguage();
  const copy = hostCopy(language);
  const detected = detectChromiumBrowsers();
  if (detected.length === 0) {
    void vscode.window.showInformationMessage(copy('noChromiumBrowserFound'));
    return { ok: false, message: copy('noChromiumBrowserFound') };
  }
  const record =
    payload && typeof payload === 'object' && !Array.isArray(payload)
      ? (payload as Record<string, unknown>)
      : {};
  const preferredBrowserId =
    typeof record.browserId === 'string' ? record.browserId.trim() : undefined;
  const initialUrl =
    typeof record.initialUrl === 'string' && /^https?:\/\//i.test(record.initialUrl.trim())
      ? record.initialUrl.trim()
      : undefined;

  const selected = await pickDetectedBrowser(
    detected,
    copy('pickLaunchBrowserPlaceholder'),
    preferredBrowserId,
  );
  if (!selected) {
    return { ok: false, message: copy('noChromiumBrowserFound') };
  }
  if (selected === 'cancelled') {
    return { ok: true, cancelled: true, message: 'cancelled' };
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
    context.outputChannel.appendLine(`[browser-capture] launch stage failed: ${reason}`);
    return { ok: false, message: copy('installFailed', { reason }) };
  }

  const seed = await seedBootstrapHandshake(context, installed.targetDir);
  const profileDir = resolveManagedBrowserProfileDir({ homeDir: os.homedir() });
  const launched = launchBrowserWithExtension(selected, {
    extensionDir: installed.targetDir,
    profileDir,
    initialUrl,
  });
  if (!launched.spawned) {
    const message = copy('browserOpenFailed', {
      browser: selected.label,
      reason: `${launched.command} ${launched.args.join(' ')}`,
    });
    context.outputChannel.appendLine(`[browser-capture] ${message}`);
    void vscode.window.showWarningMessage(message);
    return { ok: false, message };
  }

  const doneMessage = copy('launchBrowserDone', { browser: selected.label });
  context.outputChannel.appendLine(
    `[browser-capture] launched ${selected.label} with --load-extension=${installed.targetDir} (profile=${profileDir}, handshakeSeeded=${Boolean(seed)})`,
  );
  void vscode.window.showInformationMessage(doneMessage);
  return {
    ok: true,
    message: doneMessage,
    data: {
      browser: selected.id,
      targetDir: installed.targetDir,
      profileDir,
      version: installed.version,
      handshakeSeeded: Boolean(seed),
    },
  };
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

  const seed = await seedBootstrapHandshake(context, installed.targetDir);
  const opened = openCaptureFolder(installed.targetDir);
  await vscode.env.clipboard.writeText(installed.targetDir).then(() => undefined, () => undefined);
  context.outputChannel.appendLine(
    `[browser-capture] installed ${installed.fileCount} files to ${installed.targetDir} (folder opener: ${opened.command}, spawned: ${opened.spawned}, handshakeSeeded: ${Boolean(seed)})`,
  );

  let guide = captureInstallGuide({ targetDir: installed.targetDir, version: installed.version, language });
  if (!opened.spawned) {
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
    data: {
      targetDir: installed.targetDir,
      version: installed.version,
      fileCount: installed.fileCount,
      handshakeSeeded: Boolean(seed),
    },
  };
}

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
  const selected = await pickDetectedBrowser(detected, copy('pickBrowserPlaceholder'));
  if (!selected || selected === 'cancelled') {
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
  const seed = await seedBootstrapHandshake(context, installed.targetDir);
  const opened = openBrowserExtensionsPage(selected);
  const folderOpened = openCaptureFolder(installed.targetDir);
  await vscode.env.clipboard.writeText(installed.targetDir).then(() => undefined, () => undefined);
  context.outputChannel.appendLine(
    `[browser-capture] per-browser install: ${installed.fileCount} files to ${installed.targetDir}; opened ${selected.label} extensions page (spawned: ${opened.spawned}, folderSpawned: ${folderOpened.spawned}, handshakeSeeded: ${Boolean(seed)})`,
  );
  const doneMessage = copy('installForBrowserDone', {
    browser: selected.label,
    dir: installed.targetDir,
  });
  const openFolderLabel = copy('copyFolderPath');
  void vscode.window
    .showInformationMessage(doneMessage, openFolderLabel)
    .then((choice) => {
      if (choice === openFolderLabel) {
        void vscode.env.clipboard.writeText(installed.targetDir);
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
      browser: selected.id,
      handshakeSeeded: Boolean(seed),
    },
  };
}

export async function maybePromptCaptureOnboarding(context: CommandContext): Promise<void> {
  const language = resolveHostLanguage();
  const copy = hostCopy(language);
  const prompted = Boolean(
    context.extensionContext.globalState.get(CAPTURE_ONBOARDING_PROMPTED_FLAG),
  );
  const prepared = fs.existsSync(
    path.join(resolveInstalledCaptureDir(os.homedir()), 'manifest.json'),
  );
  if (!shouldPromptCaptureOnboarding({ prompted, prepared, paired: false })) {
    return;
  }
  await context.extensionContext.globalState.update(CAPTURE_ONBOARDING_PROMPTED_FLAG, true);
  const launchLabel = copy('onboardingLaunch');
  const installLabel = copy('onboardingInstall');
  const choice = await vscode.window.showInformationMessage(
    copy('onboardingPrompt'),
    launchLabel,
    installLabel,
    copy('onboardingNotNow'),
  );
  if (choice === launchLabel) {
    await launchBrowserCaptureCommand(context);
  } else if (choice === installLabel) {
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

export async function browserCaptureInstallStatus(
  context: CommandContext,
): Promise<BrowserCaptureInstallStatus> {
  const installDir = resolveInstalledCaptureDir(os.homedir());
  const marker = readCaptureBundleMarker(installDir);
  const prepared = fs.existsSync(path.join(installDir, 'manifest.json'));
  const status = context.sidecarManager.getStatus();
  let paired = false;
  let capturedCount: number | null = null;
  if (status.lifecycle === 'ready' && status.port) {
    try {
      const workspaceId = getRuntimeWorkspaceContext(context).workspaceId;
      const revision = await context.sidecarClient.getJson<{
        count?: number;
      }>(
        status.port,
        `${BROWSER_CAPTURE.libraryRevisionPath}?workspace_id=${encodeURIComponent(workspaceId)}`,
      );
      capturedCount = typeof revision.count === 'number' ? revision.count : null;
      if (context.sidecarClient.openEventStream) {
        for await (const frame of context.sidecarClient.openEventStream(
          status.port,
          `${BROWSER_CAPTURE.eventsStreamPath}?workspace_id=${encodeURIComponent(workspaceId)}&once=true`,
          { connectTimeoutMs: 2_000 },
        )) {
          if (frame.event === 'snapshot') {
            const parsed = JSON.parse(frame.data) as { paired_credentials?: number };
            paired = Number(parsed.paired_credentials ?? 0) > 0;
            break;
          }
        }
      }
    } catch (error) {
      context.outputChannel.appendLine(
        `[browser-capture] status probe failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }
  return { prepared, paired, capturedCount, version: marker?.version, installDir };
}

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

export async function openBrowserExtensionsPageCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const copy = hostCopy(resolveHostLanguage());
  const browsers = detectChromiumBrowsers();
  if (browsers.length === 0) {
    void vscode.window.showInformationMessage(copy('noChromiumBrowserFound'));
    return { ok: false, message: copy('noChromiumBrowserFound') };
  }

  const selected = await pickDetectedBrowser(browsers, copy('openExtensionsPage'));
  if (!selected) {
    return { ok: false, message: copy('noChromiumBrowserFound') };
  }
  if (selected === 'cancelled') {
    return { ok: true, cancelled: true };
  }

  const opened = openBrowserExtensionsPage(selected);
  if (!opened.spawned) {
    const message = copy('browserOpenFailed', {
      browser: selected.label,
      reason: `${opened.command} ${opened.args.join(' ')}`,
    });
    context.outputChannel.appendLine(`[browser-capture] ${message}`);
    void vscode.window.showWarningMessage(message);
    return { ok: false, message };
  }
  context.outputChannel.appendLine(
    `[browser-capture] opened ${selected.label} extensions page (${selected.extensionsUrl})`,
  );
  return {
    ok: true,
    message: `${selected.label} · ${selected.extensionsUrl}`,
    data: { browserId: selected.id, extensionsUrl: selected.extensionsUrl },
  };
}

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
