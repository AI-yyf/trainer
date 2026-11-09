import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import * as vscode from 'vscode';

import type { TrainerHostState } from './types';
import { toBootstrapPayload } from './workbenchData';

export type WorkbenchWebviewSurface = 'sidebar' | 'editor';

export async function buildWorkbenchHtml(
  extensionContext: vscode.ExtensionContext,
  webview: vscode.Webview,
  state: TrainerHostState,
  options?: { surface?: WorkbenchWebviewSurface },
): Promise<string> {
  const distDir = path.join(extensionContext.extensionPath, 'webview', 'dist');
  const htmlPath = path.join(distDir, 'index.html');
  const nonce = createNonce();
  const bootstrap = JSON.stringify(toBootstrapPayload(state)).replace(/</g, '\\u003c');
  // The webview adapts surface controls (expand vs. collapse) from this flag;
  // it is not state, so it stays out of the ACK-governed bootstrap payload.
  const surface: WorkbenchWebviewSurface = options?.surface ?? 'sidebar';

  if (await exists(htmlPath)) {
    let html = await fs.readFile(htmlPath, 'utf8');
    const assetUriMap = new Map<string, string>();
    for (const assetPath of await collectDistAssets(distDir)) {
      const resourceUri = webview.asWebviewUri(vscode.Uri.file(assetPath));
      assetUriMap.set(path.relative(distDir, assetPath).replace(/\\/g, '/'), resourceUri.toString());
    }

    html = html.replace(
      /<head>/i,
      `<head>
    <meta
      http-equiv="Content-Security-Policy"
      content="default-src 'none'; img-src ${webview.cspSource} https: data:; style-src ${webview.cspSource} 'unsafe-inline'; font-src ${webview.cspSource} data:; script-src ${webview.cspSource} 'nonce-${nonce}'; worker-src blob:; form-action 'none'; connect-src https: http://127.0.0.1:* http://localhost:*;"
    />`,
    );
    html = html.replace(
      /<\/head>/i,
      `    <style nonce="${nonce}">
      html, body, #root {
        min-height: 100%;
        height: 100%;
        margin: 0;
        background: var(--vscode-sideBar-background, var(--vscode-editor-background));
        color: var(--vscode-sideBar-foreground, var(--vscode-foreground));
        font-family: var(--vscode-font-family, "Segoe UI", sans-serif);
      }
      .trainer-webview-fallback {
        display: grid;
        align-content: start;
        gap: 10px;
        min-height: 100%;
        padding: 14px;
        background: var(--vscode-sideBar-background, var(--vscode-editor-background));
        color: var(--vscode-sideBar-foreground, var(--vscode-foreground));
      }
      .trainer-webview-fallback__eyebrow {
        font-size: 13px;
        letter-spacing: 0;
        text-transform: none;
        color: var(--vscode-descriptionForeground, var(--vscode-foreground));
      }
      .trainer-webview-fallback__card {
        display: grid;
        gap: 8px;
        padding: 12px;
        border: 1px solid var(--vscode-sideBar-border, var(--vscode-panel-border));
        border-radius: 6px;
        background: var(--vscode-editorWidget-background, var(--vscode-editor-background));
      }
      .trainer-webview-fallback__card strong {
        font-size: 13px;
        line-height: 1.4;
        font-weight: 400;
      }
      .trainer-webview-fallback__card p {
        margin: 0;
        font-size: 13px;
        line-height: 1.55;
        color: var(--vscode-descriptionForeground, var(--vscode-foreground));
        white-space: pre-wrap;
      }
    </style>
  </head>`,
    );
    html = html.replace(
      /(src|href)="([^"]+)"/g,
      (fullMatch, attribute: string, assetPath: string) => {
        if (assetPath.startsWith('http')) {
          return fullMatch;
        }
        const normalizedAssetPath = assetPath.replace(/^\.?\//, '');
        const mapped = assetUriMap.get(normalizedAssetPath);
        if (mapped) {
          return `${attribute}="${mapped}"`;
        }
        const resourceUri = webview.asWebviewUri(
          vscode.Uri.file(path.join(distDir, normalizedAssetPath)),
        );
        return `${attribute}="${resourceUri.toString()}"`;
      },
    );
    // Vite emits external module scripts without a nonce. VS Code webviews
    // enforce the CSP above on external scripts as well as inline scripts.
    html = html.replace(/<script(?![^>]*\bnonce=)([^>]*)>/gi, `<script nonce="${nonce}"$1>`);
    html = html.replace(
      /<body([^>]*)>/i,
      `<body$1>
    <script nonce="${nonce}">
      window.__TRAINER_BOOTSTRAP__ = ${bootstrap};
      window.__TRAINER_SURFACE__ = "${surface}";
      window.__TRAINER_WEBVIEW_READY__ = true;
    </script>`,
    );
    html = html.replace(
      /<div id="root"><\/div>/i,
      `<div id="root"><div class="trainer-webview-fallback" aria-hidden="true"></div></div>`,
    );
    return html;
  }

  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta
      http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';"
    />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Trainer Workbench</title>
    <style>
      :root {
        color-scheme: light dark;
        --trainer-recovery-bg: var(--vscode-sideBar-background, var(--vscode-editor-background));
        --trainer-recovery-surface: var(--vscode-editorWidget-background, var(--vscode-editor-background));
        --trainer-recovery-fg: var(--vscode-sideBar-foreground, var(--vscode-foreground));
        --trainer-recovery-muted: var(--vscode-descriptionForeground, var(--vscode-foreground));
        --trainer-recovery-border: var(--vscode-sideBar-border, var(--vscode-panel-border));
        --trainer-recovery-button: var(--vscode-button-background, var(--vscode-focusBorder));
        --trainer-recovery-button-fg: var(--vscode-button-foreground, var(--vscode-foreground));
        --trainer-recovery-focus: var(--vscode-focusBorder, var(--vscode-button-background));
      }
      * { box-sizing: border-box; }
      html, body { min-height: 100%; }
      body {
        margin: 0;
        background: var(--trainer-recovery-bg);
        color: var(--trainer-recovery-fg);
        font: 13px/1.5 var(--vscode-font-family, "Segoe UI", sans-serif);
      }
      .trainer-webview-recovery {
        display: grid;
        align-content: start;
        gap: 12px;
        min-height: 100vh;
        max-width: 480px;
        margin: 0 auto;
        padding: 14px;
      }
      .trainer-webview-recovery__eyebrow {
        margin: 0;
        color: var(--trainer-recovery-muted);
        font-size: 13px;
        font-weight: 400;
        letter-spacing: 0;
      }
      .trainer-webview-recovery__panel {
        display: grid;
        gap: 10px;
        padding: 12px;
        border: 1px solid var(--trainer-recovery-border);
        border-radius: 6px;
        background: var(--trainer-recovery-surface);
      }
      .trainer-webview-recovery__title,
      .trainer-webview-recovery__copy,
      .trainer-webview-recovery__hint,
      .trainer-webview-recovery__status {
        margin: 0;
      }
      .trainer-webview-recovery__title {
        color: var(--trainer-recovery-fg);
        font-size: 13px;
        font-weight: 400;
        line-height: 1.4;
      }
      .trainer-webview-recovery__copy,
      .trainer-webview-recovery__hint,
      .trainer-webview-recovery__status {
        color: var(--trainer-recovery-muted);
        font-size: 13px;
        overflow-wrap: anywhere;
      }
      .trainer-webview-recovery__action {
        width: 100%;
        min-height: 32px;
        padding: 6px 10px;
        border: 1px solid var(--trainer-recovery-button);
        border-radius: 4px;
        background: var(--trainer-recovery-button);
        color: var(--trainer-recovery-button-fg);
        cursor: pointer;
        font: inherit;
      }
      .trainer-webview-recovery__action:disabled {
        cursor: default;
        opacity: 0.7;
      }
      .trainer-webview-recovery__action:focus-visible {
        outline: 2px solid var(--trainer-recovery-focus);
        outline-offset: 2px;
      }
    </style>
  </head>
  <body>
    <main class="trainer-webview-recovery" aria-labelledby="trainer-webview-recovery-title">
      <p class="trainer-webview-recovery__eyebrow">Trainer</p>
      <section class="trainer-webview-recovery__panel" aria-describedby="trainer-webview-recovery-copy trainer-webview-recovery-hint">
        <h1 id="trainer-webview-recovery-title" class="trainer-webview-recovery__title">Trainer needs a quick refresh</h1>
        <p id="trainer-webview-recovery-copy" class="trainer-webview-recovery__copy">The Trainer interface bundle is unavailable, so the coach cannot open yet. Your workspace has not been changed.</p>
        <button class="trainer-webview-recovery__action" type="button" data-recovery>Check Trainer startup</button>
        <p id="trainer-webview-recovery-status" class="trainer-webview-recovery__status" aria-live="polite"></p>
        <p id="trainer-webview-recovery-hint" class="trainer-webview-recovery__hint">If it does not open, reload the VS Code window and open Trainer again.</p>
      </section>
    </main>
    <script nonce="${nonce}">
      const vscode = acquireVsCodeApi();
      const recoveryButton = document.querySelector('[data-recovery]');
      const recoveryStatus = document.getElementById('trainer-webview-recovery-status');
      vscode.postMessage({ type: 'webview/ready' });
      window.__TRAINER_WEBVIEW_READY__ = true;
      if (recoveryButton instanceof HTMLButtonElement && recoveryStatus) {
        recoveryButton.addEventListener('click', () => {
          recoveryButton.disabled = true;
          recoveryStatus.textContent = 'Checking the current Trainer startup state...';
          vscode.postMessage({ type: 'request/bootstrap' });
          window.setTimeout(() => {
            recoveryButton.disabled = false;
            recoveryStatus.textContent = 'The interface is still unavailable. Reload the VS Code window, then open Trainer again.';
          }, 1200);
        });
      }
    </script>
  </body>
</html>`;
}

async function exists(filePath: string): Promise<boolean> {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function collectDistAssets(distDir: string): Promise<string[]> {
  const assetsDir = path.join(distDir, 'assets');
  try {
    const entries = await fs.readdir(assetsDir, { withFileTypes: true });
    return entries
      .filter((entry) => entry.isFile())
      .map((entry) => path.join(assetsDir, entry.name));
  } catch {
    return [];
  }
}

declare global {
  interface Window {
    __TRAINER_WEBVIEW_READY__?: boolean;
  }
}

function createNonce(): string {
  const alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  let output = '';
  for (let index = 0; index < 32; index += 1) {
    output += alphabet[Math.floor(Math.random() * alphabet.length)];
  }
  return output;
}
