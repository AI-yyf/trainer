import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';

/**
 * Opt-in anonymous telemetry consent (P2 #18).
 *
 * The sidecar owns the truth: consent lives in the sidecar data dir and is
 * audited there. The host never mirrors consent into workspace-scoped state
 * and never sends event data anywhere — the only two operations surfaced to
 * the workbench are "read the consent fact" and "change the consent fact".
 * The sidecar is never woken just to read the fact (a dark sidecar stays
 * dark); the settings surface refreshes lazily when the sidecar is already
 * running.
 */

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

export async function refreshTelemetryStatusCommand(
  context: CommandContext,
  _payload?: unknown,
): Promise<CommandExecutionResult> {
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== 'ready' || !status.port) {
    // Deliberately do NOT start the sidecar to read consent: the default is
    // off, so showing "off/unknown" on a dark sidecar is fail-closed.
    return { ok: false, message: 'Sidecar is not running; telemetry stays off until asked.' };
  }
  let consent: unknown;
  try {
    consent = await context.sidecarClient.getJson<unknown>(status.port, '/telemetry/status');
  } catch (error) {
    return { ok: false, message: 'Telemetry status could not be read.' };
  }
  const optIn = asRecord(consent)?.opt_in === true;
  await context.patchWorkbenchData({ telemetryOptIn: optIn });
  await context.workbench.syncState();
  return { ok: true, message: optIn ? 'Telemetry opt-in is on.' : 'Telemetry opt-in is off.' };
}

export async function setTelemetryOptInCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const enabled = asRecord(payload)?.enabled === true;
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }
  let consent: unknown;
  try {
    consent = await context.sidecarClient.postJson<unknown>(status.port, '/telemetry/consent', {
      opt_in: enabled,
      source: 'settings',
    });
  } catch (error) {
    return { ok: false, message: 'Telemetry consent could not be recorded.' };
  }
  const optIn = asRecord(consent)?.opt_in === true;
  if (optIn !== enabled) {
    // The sidecar is the single source of truth; the UI must never show a
    // consent state the server did not answer.
    return { ok: false, message: 'Telemetry consent did not apply.' };
  }
  await context.patchWorkbenchData({ telemetryOptIn: optIn });
  await context.workbench.syncState();
  return {
    ok: true,
    message: optIn
      ? 'Opt-in anonymous telemetry enabled (coarse local counts only).'
      : 'Opt-in anonymous telemetry stays off.',
  };
}
