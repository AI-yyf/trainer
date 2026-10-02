import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult, StageMaterialItem } from '../core/types';
import { COMMAND_IDS } from '../core/constants';
import { normalizeStageMaterials } from '../../../shared/src/stageMaterials';
import { getRuntimeWorkspaceId } from './workspaceContext';

function readNonEmptyString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

export async function generateStageMaterialCommand(
  context: CommandContext, payload: unknown,
): Promise<CommandExecutionResult> {
  const input = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {};
  const planId = readNonEmptyString(input.planId);
  const stageId = readNonEmptyString(input.stageId);
  const workspaceId = getRuntimeWorkspaceId(context);
  const language = context.getHostState().bootstrap.memory.workspace?.responseLanguage ?? 'en-US';
  const zh = language.startsWith('zh');
  const failure = zh ? '资料生成失败，请重试并检查模型连接。' : 'Material generation failed. Retry and check the model connection.';
  if (!planId || !stageId) return { ok: false, message: failure };
  try {
    if (readNonEmptyString(input.workspaceId) && input.workspaceId !== workspaceId) throw new Error('Workspace changed');
    if (!(await context.trustGuard.ensureTrusted('generate stage learning materials'))) throw new Error('Workspace trust required');
    const status = await context.sidecarManager.ensureRunning();
    if (status.lifecycle !== 'ready' || !status.port) throw new Error('Sidecar unavailable');
    const provider = context.providerStore.getConfig();
    if (!provider) throw new Error('Saved provider required');
    const apiKey = await context.providerStore.getApiKey();
    const response = await context.sidecarClient.postJson<{ materials?: StageMaterialItem[] }>(
      status.port,
      `/plan/${encodeURIComponent(planId)}/stages/${encodeURIComponent(stageId)}/material/generate`,
      { workspace_id: workspaceId, session_id: context.getSessionId(),
        provider, api_key: apiKey, response_language: language },
      { timeoutMs: 100_000 },
    );
    const materials = normalizeStageMaterials({ [stageId]: response?.materials })[stageId] ?? [];
    if (materials.length === 0) throw new Error('No materials returned');
    if (getRuntimeWorkspaceId(context) !== workspaceId
      || context.getHostState().bootstrap.plan.id !== planId) {
      return { ok: false, cancelled: true, message: zh ? '计划已切换。' : 'The plan has changed.' };
    }
    await context.patchWorkbenchData({ stageMaterials: {
      ...context.getHostState().bootstrap.stageMaterials, [stageId]: materials,
    } });
    const templates = materials.some(item => item.generationSource === 'template');
    return { ok: true, message: templates
      ? (zh ? '模型未完成生成，已提供阶段模板；可以重试生成完整资料。' : 'The model did not complete generation. Stage templates are available; retry for full materials.')
      : (zh ? `已生成 ${materials.length} 份学习资料。` : `Generated ${materials.length} learning materials.`),
      data: { stageId, materials } };
  } catch (error) {
    context.outputChannel.appendLine(`[stage-material] ${error instanceof Error ? error.name : 'Request failed'}`);
    return { ok: false, message: failure };
  } finally {
    await context.workbench.postMessage({ type: 'stageMaterials/settled', payload: { workspaceId, planId, stageId } });
  }
}

export const stageMaterialCommandIds = [COMMAND_IDS.stageMaterialGenerate];
