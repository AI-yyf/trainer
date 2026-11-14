import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';
import { normalizeGoalSession } from '../core/workbenchData';
import { getRuntimeWorkspaceId } from './workspaceContext';

type GoalAction = 'start' | 'pause' | 'resume' | 'complete' | 'archive';

type GoalControlPayload = {
  action?: unknown;
  title?: unknown;
  goalId?: unknown;
};

const GOAL_ACTIONS = new Set<GoalAction>(['start', 'pause', 'resume', 'complete', 'archive']);

export async function goalControlCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('control the Trainer learning goal'))) {
    return { ok: false, message: 'Workspace trust is required to control the learning goal.' };
  }
  const input = (payload && typeof payload === 'object' ? payload : {}) as GoalControlPayload;
  const action = String(input.action ?? '').trim().toLowerCase();
  if (!GOAL_ACTIONS.has(action as GoalAction)) {
    return { ok: false, message: 'A supported goal action is required.' };
  }
  const title = typeof input.title === 'string' ? input.title.trim() : '';
  if (action === 'start' && !title) {
    return { ok: false, message: 'A goal title is required.' };
  }
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }
  try {
    const result = await context.sidecarClient.postJson<{ goal?: unknown; currentGoal?: unknown }>(
      status.port,
      '/goal/action',
      {
        session_id: context.getSessionId(),
        workspace_id: getRuntimeWorkspaceId(context),
        action,
        ...(title ? { title } : {}),
        ...(typeof input.goalId === 'string' && input.goalId.trim()
          ? { goal_id: input.goalId.trim() }
          : {}),
      },
    );
    await context.patchWorkbenchData({
      goal: normalizeGoalSession('currentGoal' in result ? result.currentGoal : result.goal),
    });
    return { ok: true, message: '', data: result };
  } catch (error) {
    return {
      ok: false,
      message: error instanceof Error ? error.message : String(error),
    };
  }
}
