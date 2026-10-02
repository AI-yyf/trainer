import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';

export async function generateSkillDraftCommand(
  context: CommandContext, payload?: unknown,
): Promise<CommandExecutionResult> {
  const input = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {};
  const requestId = typeof input.requestId === 'string' ? input.requestId.trim() : '';
  const description = typeof input.description === 'string' ? input.description.trim() : '';
  const language = context.getHostState().bootstrap.memory.workspace?.responseLanguage ?? 'en-US';
  const zh = language.startsWith('zh');
  if (payload === undefined) {
    await context.workbench.show();
    await context.workbench.postMessage({ type: 'ui/restoreView', payload: { activeView: 'settings' } });
    return { ok: true, message: zh ? '在教学偏好中描述技能，即可生成草稿。' : 'Describe a skill in Coaching settings to draft it.' };
  }
  const failure = zh ? '技能生成失败，请重试，也可以直接填写下方的技能内容。'
    : 'Skill generation failed. Retry, or enter the skill below.';
  if (!/^[a-z0-9-]{1,96}$/i.test(requestId)) {
    return { ok: false, message: zh ? '请在设置的教学偏好中生成技能草稿。' : 'Generate a skill draft in Settings → Coaching.' };
  }
  try {
    if (description.length < 2 || description.length > 2000) throw new Error('Invalid skill description');
    if (!(await context.trustGuard.ensureTrusted('draft a Trainer skill'))) throw new Error('Workspace trust is required');
    const provider = context.providerStore.getConfig();
    if (!provider) throw new Error('A saved provider is required');
    const status = await context.sidecarManager.ensureRunning();
    if (status.lifecycle !== 'ready' || !status.port) throw new Error('Sidecar unavailable');
    const apiKey = await context.providerStore.getApiKey();
    const draft = await context.sidecarClient.postJson<unknown>(status.port, '/provider/skill-draft', {
      provider, api_key: apiKey, description, response_language: language,
    }, { timeoutMs: 55_000 });
    await context.workbench.postMessage({ type: 'skills/draftResult', payload: { requestId, ok: true, draft } });
    return { ok: true, message: zh ? '已生成技能草稿，修改后再添加。' : 'Skill drafted. Review it before adding.' };
  } catch (error) {
    context.outputChannel.appendLine(`[skill-draft] ${error instanceof Error ? error.name : 'Request failed'}`);
    await context.workbench.postMessage({ type: 'skills/draftResult', payload: { requestId, ok: false, message: failure } });
    return { ok: false, message: failure };
  }
}
