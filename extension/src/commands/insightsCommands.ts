import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';

const REQUEST_ID_PATTERN = /^[a-z0-9-]{1,96}$/i;
const DEFAULT_WINDOW_DAYS = 30;
const MIN_WINDOW_DAYS = 1;
const MAX_WINDOW_DAYS = 365;

function resolveWindowDays(value: unknown): number {
  const parsed = typeof value === 'number' ? Math.trunc(value) : Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed)) return DEFAULT_WINDOW_DAYS;
  return Math.min(MAX_WINDOW_DAYS, Math.max(MIN_WINDOW_DAYS, parsed));
}

/**
 * Local usage insights bridge (P1 #12, §6.1). Read-only: the sidecar endpoint
 * aggregates the machine's own event ledger into coarse counts, so this
 * command never needs workspace trust, provider credentials, or writes. The
 * result is addressed back to the webview by requestId, mirroring the skill
 * draft round trip.
 */
export async function refreshLocalUsageCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const input = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {};
  const requestId = typeof input.requestId === 'string' ? input.requestId.trim() : '';
  const windowDays = resolveWindowDays(input.windowDays);
  const language = context.getHostState().bootstrap.memory.workspace?.responseLanguage ?? 'en-US';
  const zh = language.startsWith('zh');
  const failure = zh ? '暂时无法读取本地使用数据。' : 'Local usage data is unavailable right now.';
  if (!REQUEST_ID_PATTERN.test(requestId)) {
    return { ok: false, message: zh ? '请在设置的偏好页查看使用洞察。' : 'Open Usage insights under Settings → Preferences.' };
  }
  try {
    const status = await context.sidecarManager.ensureRunning();
    if (status.lifecycle !== 'ready' || !status.port) throw new Error(status.detail ?? 'Sidecar unavailable');
    const insights = await context.sidecarClient.getJson<unknown>(
      status.port,
      `/insights/local-usage?window_days=${windowDays}`,
    );
    await context.workbench.postMessage({
      type: 'insights/localUsageResult',
      payload: { requestId, ok: true, insights },
    });
    return { ok: true };
  } catch (error) {
    context.outputChannel.appendLine(`[insights] ${error instanceof Error ? error.name : 'Request failed'}`);
    await context.workbench.postMessage({
      type: 'insights/localUsageResult',
      payload: { requestId, ok: false, message: failure },
    });
    return { ok: false, message: failure };
  }
}
