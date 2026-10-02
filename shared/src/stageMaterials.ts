export interface StageMaterialItem {
  id: string;
  planStageId: string;
  kind: string;
  title: string;
  summary: string;
  content: string;
  focusArea?: string;
  createdAt?: string;
  generationSource?: 'model' | 'template';
}

/** Validate the host boundary while preserving code indentation and newlines. */
export function normalizeStageMaterials(value: unknown): Record<string, StageMaterialItem[]> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const result: Record<string, StageMaterialItem[]> = {};
  for (const [stageId, items] of Object.entries(value)) {
    if (!Array.isArray(items) || !stageId.trim()) continue;
    result[stageId] = [];
    for (const item of items.slice(0, 6)) {
      if (!item || typeof item !== 'object') continue;
      const record = item as Record<string, unknown>;
      const id = record.id;
      const kind = record.kind;
      const title = record.title;
      const content = record.content;
      const owner = record.planStageId ?? record.plan_stage_id;
      if (typeof id !== 'string' || !id.trim() || typeof kind !== 'string'
        || !['study_guide', 'cheat_sheet', 'exercise_set', 'code_examples'].includes(kind)
        || typeof title !== 'string' || !title.trim() || typeof content !== 'string'
        || !content.trim() || owner !== stageId) continue;
      const source = record.generationSource ?? record.generation_source;
      result[stageId].push({ id, kind, title, content, planStageId: stageId,
        summary: typeof record.summary === 'string' ? record.summary : '',
        focusArea: typeof (record.focusArea ?? record.focus_area) === 'string'
          ? String(record.focusArea ?? record.focus_area) : undefined,
        createdAt: typeof (record.createdAt ?? record.created_at) === 'string'
          ? String(record.createdAt ?? record.created_at) : undefined,
        generationSource: source === 'model' || source === 'template' ? source : undefined,
      });
    }
  }
  return result;
}
