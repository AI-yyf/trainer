import * as vscode from 'vscode';

import { TRAINER_OPERATION_COMPLETED_MARKER } from '../../../shared/src/protocol';
import { sanitizeErrorSurfaceText } from '../../../shared/src/errorSurfaceSanitizer';
import type { CommandRegistry } from './commandRegistry';
import { WORKBENCH_VIEW_TYPE } from './constants';
import type { TrainerHostState, TrainerWebviewMessage } from './types';
import { buildWorkbenchHtml } from './webviewContent';
import { resolveWebviewCommand } from './webviewCommandRouting';
import { WebviewStateTransport } from './webviewStateTransport';
import { toBootstrapPayload, toOperationStatus } from './workbenchData';
import { getRuntimeWorkspaceContext } from '../commands/workspaceContext';

/** The six internal routes can all surface in the editor panel. */
export const WORKBENCH_PANEL_VIEWS = [
  'coach',
  'plan',
  'resources',
  'training',
  'progress',
  'settings',
] as const;

export type WorkbenchPanelView = (typeof WORKBENCH_PANEL_VIEWS)[number];

export function normalizeWorkbenchPanelView(value: unknown): WorkbenchPanelView | undefined {
  return typeof value === 'string' && (WORKBENCH_PANEL_VIEWS as readonly string[]).includes(value)
    ? (value as WorkbenchPanelView)
    : undefined;
}

/**
 * Full-width workbench surface: the same webview bundle, bootstrap payload,
 * command registry and ACK-governed state transport as the sidebar view, but
 * hosted in an editor tab (`vscode.window.createWebviewPanel`, column Active).
 *
 * Deliberate boundary: this is a second surface, not a mirror. Messages the
 * sidebar controller receives directly (streaming chunks pushed through
 * `CommandContext.workbench.postMessage`) do not fan out here; the panel
 * re-syncs on ready, on becoming visible, after every command it runs, and
 * whenever a registered command finishes (the composed workbench host syncs
 * both surfaces). The "back to sidebar" control disposes the panel and reveals
 * the sidebar so the governed single-surface flow stays reachable.
 */
export class WorkbenchEditorPanel implements vscode.Disposable {
  private panel?: vscode.WebviewPanel;
  private ready = false;
  private pendingFocusView?: WorkbenchPanelView;
  private focusedView: WorkbenchPanelView = 'plan';
  private disposed = false;
  private readonly stateTransport: WebviewStateTransport;
  private readonly disposables: vscode.Disposable[] = [];

  constructor(
    private readonly extensionContext: vscode.ExtensionContext,
    private readonly commandRegistry: CommandRegistry,
    private readonly getState: () => TrainerHostState,
    private readonly outputChannel: vscode.OutputChannel,
    private readonly revealSidebar: () => Promise<void>,
  ) {
    this.stateTransport = new WebviewStateTransport({
      send: async (message) => this.deliverStateMessage(message),
      received: () => undefined,
      attempt: () => undefined,
      acknowledged: () => undefined,
      status: (status, generation) => {
        if (status === 'stale') {
          this.outputChannel.appendLine(
            `[workbench-panel] state apply acknowledgement exhausted (generation ${generation})`,
          );
        }
      },
    });
    this.disposables.push(this.stateTransport);
  }

  get isOpen(): boolean {
    return Boolean(this.panel);
  }

  get visibleView(): WorkbenchPanelView | undefined {
    return this.isOpen ? this.focusedView : undefined;
  }

  async open(view?: unknown): Promise<void> {
    if (this.disposed) {
      return;
    }
    const target = normalizeWorkbenchPanelView(view) ?? 'plan';
    this.focusedView = target;

    if (!this.panel) {
      const panel = vscode.window.createWebviewPanel(
        WORKBENCH_VIEW_TYPE,
        'Trainer',
        vscode.ViewColumn.Active,
        {
          enableScripts: true,
          localResourceRoots: [this.extensionContext.extensionUri],
          retainContextWhenHidden: true,
        },
      );
      this.panel = panel;
      this.ready = false;
      this.pendingFocusView = target;

      panel.onDidDispose(() => {
        if (this.panel === panel) {
          this.panel = undefined;
          this.ready = false;
          this.pendingFocusView = undefined;
        }
        this.stateTransport.reset();
      });

      panel.onDidChangeViewState(() => {
        if (panel.active || panel.visible) {
          void this.syncState();
        }
      });

      panel.webview.onDidReceiveMessage((message: TrainerWebviewMessage) => {
        void this.handleMessage(message);
      });

      this.outputChannel.appendLine('[workbench-panel] opening editor surface');
      try {
        panel.webview.html = await buildWorkbenchHtml(
          this.extensionContext,
          panel.webview,
          this.getState(),
          { surface: 'editor' },
        );
      } catch (error) {
        this.outputChannel.appendLine(
          `[workbench-panel] html build failed: ${sanitizeErrorSurfaceText(error)}`,
        );
      }
      return;
    }

    try {
      this.panel.reveal(vscode.ViewColumn.Active);
    } catch {
      // A panel in the process of being disposed is replaced on the next open.
    }
    await this.focusView(target);
    await this.syncState();
  }

  /** Dispose the editor surface and return to the governed sidebar view. */
  async collapseToSidebar(): Promise<void> {
    this.outputChannel.appendLine('[workbench-panel] collapsing back to the sidebar');
    this.panel?.dispose();
    this.panel = undefined;
    this.ready = false;
    await this.revealSidebar();
  }

  async syncState(options?: { forceFull?: boolean }): Promise<void> {
    if (this.disposed || !this.panel || !this.ready) {
      return;
    }
    const hostState = this.getState();
    const payload = toBootstrapPayload(hostState) as unknown as Record<string, unknown>;
    await this.stateTransport.publish(
      {
        payload,
        hostState,
        workspaceId: getRuntimeWorkspaceContext({ getHostState: () => hostState }).workspaceId,
        sessionId: hostState.sessionId ?? '',
        runtimeGeneration: payload.runtimeDataGeneration,
      },
      options?.forceFull === true,
    );
  }

  dispose(): void {
    this.disposed = true;
    this.panel?.dispose();
    this.panel = undefined;
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
  }

  /**
   * Deliver a host-authored message (ui/restoreView, operation/status,
   * streaming chunks pushed by commands) to the open panel. No-op when the
   * panel is closed or its webview has not reported ready yet — the ready
   * handshake then replaces state with a full snapshot.
   */
  async postHostMessage(message: unknown): Promise<boolean> {
    return this.postMessage(message);
  }

  private async focusView(view: WorkbenchPanelView): Promise<void> {
    if (!this.ready) {
      this.pendingFocusView = view;
      return;
    }
    await this.postMessage({ type: 'ui/restoreView', payload: { activeView: view } });
  }

  private async handleMessage(message: TrainerWebviewMessage): Promise<void> {
    if (!this.panel) {
      return;
    }
    try {
      switch (message.type) {
        case 'webview/ready': {
          this.ready = true;
          const pending = this.pendingFocusView ?? this.focusedView;
          this.pendingFocusView = undefined;
          await this.postMessage({ type: 'ui/restoreView', payload: { activeView: pending } });
          await this.syncState({ forceFull: true });
          return;
        }
        case 'state/ack':
          this.stateTransport.acknowledge(message.payload);
          return;
        case 'request/bootstrap':
          await this.syncState({ forceFull: true });
          return;
        case 'ui/collapseToSidebar':
          await this.collapseToSidebar();
          return;
        case 'debug/error':
          this.outputChannel.appendLine(
            `[workbench-panel:${message.payload.source}] ${sanitizeErrorSurfaceText(message.payload.message)}`,
          );
          return;
        case 'debug/visibleFacts':
          return;
        case 'ui/liveFollow':
          return;
        default:
          break;
      }

      const command = resolveWebviewCommand(message);
      if (!command) {
        this.outputChannel.appendLine(
          `[workbench-panel] unknown message: ${sanitizeErrorSurfaceText(message.type)}`,
        );
        return;
      }
      const result = await this.commandRegistry.execute(command.commandId, command.payload);
      if (!result.cancelled) {
        await this.postMessage(
          toOperationStatus(
            result.ok,
            result.message ?? TRAINER_OPERATION_COMPLETED_MARKER,
            result.providerTest,
          ),
        );
      }
      await this.syncState();
    } catch (error) {
      this.outputChannel.appendLine(
        `[workbench-panel] message handling failed: ${sanitizeErrorSurfaceText(error)}`,
      );
    }
  }

  private async deliverStateMessage(message: unknown): Promise<boolean> {
    const delivered = await this.postMessage(message);
    if (!delivered) {
      this.outputChannel.appendLine('[workbench-panel] state delivery returned false');
    }
    return delivered;
  }

  private async postMessage(message: unknown): Promise<boolean> {
    const panel = this.panel;
    if (!panel || !this.ready) {
      return false;
    }
    try {
      return await panel.webview.postMessage(message);
    } catch (error) {
      this.outputChannel.appendLine(
        `[workbench-panel] postMessage failed: ${sanitizeErrorSurfaceText(error)}`,
      );
      return false;
    }
  }
}
