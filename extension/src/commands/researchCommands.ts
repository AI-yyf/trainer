import * as vscode from 'vscode';

import { COMMAND_IDS, SIDECAR_DEFAULTS } from '../core/constants';
import type { CommandExecutionResult, TrainerHostState } from '../core/types';
import type { SidecarHttpClient } from '../core/httpClient';
import type { WorkbenchHost } from '../core/commandContext';
import type { CommandRegistry } from '../core/commandRegistry';
import { sanitizeErrorSurfaceText } from '../../../shared/src/errorSurfaceSanitizer';

function getPort(state: TrainerHostState): number {
  return state.sidecar.port ?? SIDECAR_DEFAULTS.portStart;
}

async function showCompatibilityNotice(action: string): Promise<void> {
  await vscode.window.showInformationMessage(
    `Research is now a background compatibility lane. ${action} still works, but coach-first flows are the primary surface.`,
  );
}

// Handler functions for CommandRegistry
export function createResearchHandler(
  httpClient: SidecarHttpClient,
  getState: () => TrainerHostState,
): (ctx: unknown, payload?: unknown) => Promise<CommandExecutionResult> {
  return async (_ctx, rawPayload): Promise<CommandExecutionResult> => {
    await showCompatibilityNotice('Creating a research project');
    const payload = rawPayload as { title?: string; description?: string } | undefined;
    const state = getState();
    if (state.sidecar.lifecycle !== 'ready') {
      return { ok: false, message: 'Sidecar is not ready' };
    }
    const title = payload?.title ?? (await vscode.window.showInputBox({
      prompt: 'Research project title',
      placeHolder: 'e.g., Climate Change Study',
    }));
    if (!title) {
      return { ok: false, message: 'Title is required' };
    }
    const description = payload?.description ?? (await vscode.window.showInputBox({
      prompt: 'Research project description',
      placeHolder: 'e.g., Multi-theme climate change research',
    })) ?? '';
    try {
      const port = getPort(state);
      const data = await httpClient.postJson<{ project: { id: string; title: string }; message: string }>(
        port,
        '/research/create',
        { title, description },
      );
      return {
        ok: true,
        message: data.message,
        data: data.project,
      };
    } catch (error) {
      return { ok: false, message: `Failed to create research project: ${error}` };
    }
  };
}

export function addResearchThemeHandler(
  httpClient: SidecarHttpClient,
  getState: () => TrainerHostState,
): (ctx: unknown, payload?: unknown) => Promise<CommandExecutionResult> {
  return async (_ctx, rawPayload): Promise<CommandExecutionResult> => {
    await showCompatibilityNotice('Adding a research theme');
    const payload = rawPayload as { projectId?: string; title?: string; description?: string; duration_weeks?: number; cadence?: string } | undefined;
    const state = getState();
    if (state.sidecar.lifecycle !== 'ready') {
      return { ok: false, message: 'Sidecar is not ready' };
    }
    const projectId = payload?.projectId ?? await vscode.window.showInputBox({ prompt: 'Project ID' });
    if (!projectId) {
      return { ok: false, message: 'Project ID is required' };
    }
    const title = payload?.title ?? (await vscode.window.showInputBox({
      prompt: 'Theme title',
      placeHolder: 'e.g., Historical Trends',
    }));
    if (!title) {
      return { ok: false, message: 'Theme title is required' };
    }
    const description = payload?.description ?? (await vscode.window.showInputBox({
      prompt: 'Theme description',
      placeHolder: 'e.g., 50-year trend analysis',
    })) ?? '';
    const durationWeeks = payload?.duration_weeks ?? 4;
    const cadence = payload?.cadence ?? 'weekly';
    try {
      const port = getPort(state);
      const data = await httpClient.postJson<{ theme: { id: string } }>(
        port,
        `/research/${projectId}/theme`,
        { title, description, duration_weeks: durationWeeks, cadence },
      );
      return { ok: true, message: `Theme "${title}" added`, data: data.theme };
    } catch (error) {
      return { ok: false, message: `Failed to add theme: ${error}` };
    }
  };
}

export function activateResearchThemeHandler(
  httpClient: SidecarHttpClient,
  getState: () => TrainerHostState,
): (ctx: unknown, payload?: unknown) => Promise<CommandExecutionResult> {
  return async (_ctx, rawPayload): Promise<CommandExecutionResult> => {
    await showCompatibilityNotice('Activating a research theme');
    const payload = rawPayload as { projectId?: string; themeId?: string } | undefined;
    const state = getState();
    if (state.sidecar.lifecycle !== 'ready') {
      return { ok: false, message: 'Sidecar is not ready' };
    }
    const projectId = payload?.projectId ?? await vscode.window.showInputBox({ prompt: 'Project ID' });
    const themeId = payload?.themeId ?? await vscode.window.showInputBox({ prompt: 'Theme ID' });
    if (!projectId || !themeId) {
      return { ok: false, message: 'Project ID and Theme ID are required' };
    }
    try {
      const port = getPort(state);
      const data = await httpClient.postJson<{ theme: { title: string }; message: string }>(
        port,
        `/research/${projectId}/theme/${themeId}/activate`,
        {},
      );
      return { ok: true, message: data.message, data: data.theme };
    } catch (error) {
      return { ok: false, message: `Failed to activate theme: ${error}` };
    }
  };
}

export function advanceResearchHandler(
  httpClient: SidecarHttpClient,
  getState: () => TrainerHostState,
): (ctx: unknown, payload?: unknown) => Promise<CommandExecutionResult> {
  return async (_ctx, rawPayload): Promise<CommandExecutionResult> => {
    await showCompatibilityNotice('Advancing research');
    const payload = rawPayload as { projectId?: string; themeId?: string } | undefined;
    const state = getState();
    if (state.sidecar.lifecycle !== 'ready') {
      return { ok: false, message: 'Sidecar is not ready' };
    }
    const projectId = payload?.projectId ?? await vscode.window.showInputBox({ prompt: 'Project ID' });
    if (!projectId) {
      return { ok: false, message: 'Project ID is required' };
    }
    try {
      const port = getPort(state);
      const data = await httpClient.postJson<{ message: string; themes_advanced: unknown[] }>(
        port,
        `/research/${projectId}/advance`,
        { theme_id: payload?.themeId },
      );
      return {
        ok: true,
        message: data.message,
        data: { advancedCount: data.themes_advanced.length },
      };
    } catch (error) {
      return { ok: false, message: `Failed to advance research: ${error}` };
    }
  };
}

export function researchMessageHandler(
  httpClient: SidecarHttpClient,
  getState: () => TrainerHostState,
): (ctx: unknown, payload?: unknown) => Promise<CommandExecutionResult> {
  return async (_ctx, rawPayload): Promise<CommandExecutionResult> => {
    await showCompatibilityNotice('Sending a research message');
    const payload = rawPayload as { projectId?: string; message?: string } | undefined;
    const state = getState();
    if (state.sidecar.lifecycle !== 'ready') {
      return { ok: false, message: 'Sidecar is not ready' };
    }
    const projectId = payload?.projectId ?? await vscode.window.showInputBox({ prompt: 'Project ID' });
    if (!projectId) {
      return { ok: false, message: 'Project ID is required' };
    }
    const message = payload?.message ?? await vscode.window.showInputBox({
      prompt: 'Message to research agent',
      placeHolder: 'e.g., What should I focus on next?',
    });
    if (!message) {
      return { ok: false, message: 'Message is required' };
    }
    try {
      const port = getPort(state);
      const data = await httpClient.postJson<{ response: string }>(
        port,
        `/research/${projectId}/message`,
        { message },
      );
      return { ok: true, message: data.response };
    } catch (error) {
      return { ok: false, message: `Failed to send message: ${error}` };
    }
  };
}

export function researchStreamMessageHandler(
  httpClient: SidecarHttpClient,
  getState: () => TrainerHostState,
  workbench?: WorkbenchHost,
): (ctx: unknown, payload?: unknown) => Promise<CommandExecutionResult> {
  return async (_ctx, rawPayload): Promise<CommandExecutionResult> => {
    await showCompatibilityNotice('Streaming a research message');
    const payload = rawPayload as { projectId?: string; message?: string } | undefined;
    const state = getState();
    if (state.sidecar.lifecycle !== 'ready') {
      return { ok: false, message: 'Sidecar is not ready' };
    }
    const projectId = payload?.projectId ?? await vscode.window.showInputBox({ prompt: 'Project ID' });
    if (!projectId) {
      return { ok: false, message: 'Project ID is required' };
    }
    const message = payload?.message ?? await vscode.window.showInputBox({
      prompt: 'Message to research agent (streaming)',
      placeHolder: 'e.g., What should I focus on next?',
    });
    if (!message) {
      return { ok: false, message: 'Message is required' };
    }

    const messageId = `research_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

    if (workbench) {
      await workbench.postMessage({
        type: 'stream/start',
        payload: { messageId },
      });
    }

    try {
      const port = getPort(state);
      let totalTokens = 0;

      for await (const chunk of httpClient.fetchSSE(
        port,
        `/research/${projectId}/message/stream`,
        { message },
      )) {
        if (chunk.event === 'error') {
          let errorMessage = chunk.data || 'Research stream failed.';
          try {
            const parsed = JSON.parse(chunk.data) as { error?: unknown };
            if (typeof parsed.error === 'string' && parsed.error.trim()) {
              errorMessage = parsed.error;
            }
          } catch {
            // Keep the raw SSE payload when the error envelope is malformed.
          }
          const safeError = sanitizeErrorSurfaceText(errorMessage) || 'Research stream failed.';
          if (workbench) {
            await workbench.postMessage({
              type: 'stream/error',
              payload: { error: safeError },
            });
          }
          return { ok: false, message: `Stream error: ${safeError}` };
        }

        if (chunk.event === 'complete') {
          try {
            const parsed = JSON.parse(chunk.data) as { tokens?: number };
            if (typeof parsed.tokens === 'number') {
              totalTokens = parsed.tokens;
            }
          } catch {
            // Ignore malformed completion payloads and keep the counted total.
          }
          continue;
        }

        try {
          const parsed = JSON.parse(chunk.data) as { chunk?: unknown };
          if (typeof parsed.chunk === 'string') {
            totalTokens += parsed.chunk.length;
            if (workbench) {
              await workbench.postMessage({
                type: 'stream/chunk',
                payload: { chunk: parsed.chunk },
              });
            }
          }
        } catch {
          if (workbench) {
            await workbench.postMessage({
              type: 'stream/chunk',
              payload: { chunk: chunk.data },
            });
          }
        }
      }

      if (workbench) {
        await workbench.postMessage({
          type: 'stream/complete',
          payload: { tokens: totalTokens },
        });
      }

      return { ok: true, message: 'Stream message completed' };
    } catch (error) {
      const safeError = sanitizeErrorSurfaceText(error) || 'Research stream failed.';
      if (workbench) {
        await workbench.postMessage({
          type: 'stream/error',
          payload: { error: safeError },
        });
      }
      return { ok: false, message: `Stream error: ${safeError}` };
    }
  };
}

export function approveResearchDecisionHandler(
  httpClient: SidecarHttpClient,
  getState: () => TrainerHostState,
): (ctx: unknown, payload?: unknown) => Promise<CommandExecutionResult> {
  return async (_ctx, rawPayload): Promise<CommandExecutionResult> => {
    const payload = rawPayload as { projectId?: string; approvalId?: string; approved?: boolean } | undefined;
    const state = getState();
    if (state.sidecar.lifecycle !== 'ready') {
      return { ok: false, message: 'Sidecar is not ready' };
    }
    const projectId = payload?.projectId ?? await vscode.window.showInputBox({ prompt: 'Project ID' });
    const approvalId = payload?.approvalId ?? await vscode.window.showInputBox({ prompt: 'Approval ID' });
    if (!projectId || !approvalId) {
      return { ok: false, message: 'Project ID and Approval ID are required' };
    }
    const approved = payload?.approved ?? true;
    try {
      const port = getPort(state);
      const data = await httpClient.postJson<{ status: string }>(
        port,
        `/research/${projectId}/approve/${approvalId}`,
        { approved },
      );
      return { ok: true, message: `Decision ${data.status}`, data };
    } catch (error) {
      return { ok: false, message: `Failed to resolve approval: ${error}` };
    }
  };
}

export function getResearchStatusHandler(
  httpClient: SidecarHttpClient,
  getState: () => TrainerHostState,
): (ctx: unknown, payload?: unknown) => Promise<CommandExecutionResult> {
  return async (_ctx, rawPayload): Promise<CommandExecutionResult> => {
    const payload = rawPayload as { projectId?: string } | undefined;
    const state = getState();
    if (state.sidecar.lifecycle !== 'ready') {
      return { ok: false, message: 'Sidecar is not ready' };
    }
    const projectId = payload?.projectId ?? await vscode.window.showInputBox({ prompt: 'Project ID' });
    if (!projectId) {
      return { ok: false, message: 'Project ID is required' };
    }
    try {
      const port = getPort(state);
      const data = await httpClient.getJson<{ project: unknown; schedule_status: unknown }>(
        port,
        `/research/${projectId}`,
      );
      return { ok: true, message: 'Status retrieved', data };
    } catch (error) {
      return { ok: false, message: `Failed to get status: ${error}` };
    }
  };
}
