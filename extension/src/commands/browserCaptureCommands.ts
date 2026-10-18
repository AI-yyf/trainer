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
  installCaptureBundle,
  openCaptureFolder,
  resolveCaptureInstallDir,
} from '../browserCapture/installBundle';

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
export async function installBrowserCaptureCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const language = resolveHostLanguage();
  const copy = hostCopy(language);
  const bundleDir = vscode.Uri.joinPath(
    context.extensionContext.extensionUri,
    BROWSER_CAPTURE.bundleDirName,
  ).fsPath;
  if (!fs.existsSync(path.join(bundleDir, 'manifest.json'))) {
    return { ok: false, message: copy('installBundleMissing') };
  }

  const targetDir = resolveCaptureInstallDir({ homeDir: os.homedir() });
  let installed: { targetDir: string; fileCount: number; version?: string };
  try {
    installed = installCaptureBundle({ sourceDir: bundleDir, targetDir });
  } catch (error) {
    const reason =
      error instanceof CaptureBundleSourceError
        ? error.message
        : error instanceof Error
          ? error.message
          : String(error);
    context.outputChannel.appendLine(`[browser-capture] install failed: ${reason}`);
    return { ok: false, message: copy('installFailed', { reason }) };
  }

  const opened = openCaptureFolder(targetDir);
  context.outputChannel.appendLine(
    `[browser-capture] installed ${installed.fileCount} files to ${targetDir} (folder opener: ${opened.command}, spawned: ${opened.spawned})`,
  );

  let guide = captureInstallGuide({ targetDir, version: installed.version, language });
  if (!opened.spawned) {
    // Headless hosts without open/explorer/xdg-open: the path on the bar is the
    // degraded fallback, said in the user's language.
    guide = `${guide}\n${copy('installFolderFallback', { dir: targetDir })}`;
  }
  const copyPathLabel = copy('copyFolderPath');
  void vscode.window.showInformationMessage(guide, copyPathLabel).then((choice) => {
    if (choice === copyPathLabel) {
      void vscode.env.clipboard.writeText(targetDir);
    }
  });

  const label = installed.version ? `Trainer Capture ${installed.version}` : 'Trainer Capture';
  return {
    ok: true,
    message: copy('installSucceeded', { label, dir: targetDir }),
    data: { targetDir: installed.targetDir, version: installed.version, fileCount: installed.fileCount },
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
