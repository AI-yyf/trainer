import type { CommandContext } from '../core/commandContext';
import { normalizeWorkbenchPanelView } from '../core/workbenchPanel';
import type { CommandExecutionResult } from '../core/types';

/**
 * Expand a governed workbench view (Learning / Resources) into a full-width
 * editor tab. The host command is the only entry point: the sidebar button and
 * any future surface post the same `command/execute` payload, so the panel
 * keeps the same command governance as the sidebar.
 */
export async function openViewInEditorCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const rawView = payload && typeof payload === 'object' ? (payload as { view?: unknown }).view : undefined;
  const view = normalizeWorkbenchPanelView(rawView) ?? 'plan';
  if (!context.workbench.openInEditor) {
    return {
      ok: false,
      message: 'Trainer cannot open an editor panel in this host.',
    };
  }
  await context.workbench.openInEditor(view);
  return {
    ok: true,
    message: 'Trainer opened the view full width in an editor tab.',
  };
}
