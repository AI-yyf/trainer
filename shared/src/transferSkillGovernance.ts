/** Fail-closed transferable-skill promotion after multi-scene evidence.
 * A scene is a distinct project/workspace. One project success is never global mastery.
 */
export type TransferSkillState = "project_only" | "awaiting_second_scene" | "transferable";

export type TransferSkillScene = {
  workspaceId: string;
  sceneKey: string;
};

export type TransferSkillStateRecord = {
  concept: string;
  state: TransferSkillState;
  sceneCount: number;
  workspaceIds: string[];
  sceneKeys: string[];
  why: string;
  next: string;
};

export type TransferSkillDecisionInput = {
  concept?: string;
  workspaceId?: string;
  currentSceneKey?: string;
  existingScenes?: TransferSkillScene[];
  outcomeSuccess?: boolean;
  transferSourceWorkspaceId?: string;
  transferTargetWorkspaceId?: string;
  transferSourceContext?: string;
  transferTargetContext?: string;
  transferEvidenceSummary?: string;
  scenario?: string;
};

export type TransferSkillCopy = {
  why: string;
  next: string;
  label: string;
};

export const DEFAULT_TRANSFER_SCENE_KEY = "default";

const STATES = new Set<TransferSkillState>([
  "project_only",
  "awaiting_second_scene",
  "transferable",
]);

function text(value: string | undefined): string {
  return value?.trim() ?? "";
}

function casefold(value: string | undefined): string {
  return text(value).toLowerCase();
}

export function normalizeTransferSkillState(value: string | undefined): TransferSkillState | undefined {
  const normalized = casefold(value).replace(/-/g, "_");
  if (STATES.has(normalized as TransferSkillState)) {
    return normalized as TransferSkillState;
  }
  return undefined;
}

export function resolveSkillSceneKey(input: TransferSkillDecisionInput): string {
  const sourceWorkspace = text(input.transferSourceWorkspaceId);
  const targetWorkspace = text(input.transferTargetWorkspaceId);
  const sourceContext = text(input.transferSourceContext);
  const targetContext = text(input.transferTargetContext);
  const evidence = text(input.transferEvidenceSummary);
  const scenario = casefold(input.scenario).replace(/-/g, "_");
  if (sourceContext && targetContext && casefold(sourceContext) !== casefold(targetContext) && evidence) {
    return `transfer:${casefold(targetContext)}`;
  }
  if (
    evidence &&
    sourceWorkspace &&
    targetWorkspace &&
    sourceWorkspace !== targetWorkspace &&
    (scenario === "cross_project_transfer" || sourceWorkspace !== targetWorkspace)
  ) {
    return `workspace:${casefold(targetWorkspace)}`;
  }
  return DEFAULT_TRANSFER_SCENE_KEY;
}

export function uniqueTransferScenes(scenes: TransferSkillScene[] | undefined): TransferSkillScene[] {
  const seen = new Set<string>();
  const unique: TransferSkillScene[] = [];
  for (const scene of scenes ?? []) {
    const workspaceId = text(scene.workspaceId);
    const sceneKey = text(scene.sceneKey) || DEFAULT_TRANSFER_SCENE_KEY;
    if (!workspaceId) {
      continue;
    }
    const key = casefold(workspaceId);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    unique.push({ workspaceId, sceneKey });
  }
  return unique;
}

export function uniqueTransferWorkspaceIds(scenes: TransferSkillScene[] | undefined): string[] {
  return uniqueTransferScenes(scenes).map((scene) => scene.workspaceId);
}

function sceneKeyDependsOnExcludedWorkspace(sceneKey: string, excluded: Set<string>): boolean {
  const key = casefold(sceneKey);
  if (!key) {
    return false;
  }
  if (excluded.has(key)) {
    return true;
  }
  for (const id of excluded) {
    if (key === `workspace:${id}` || key.endsWith(`:${id}`)) {
      return true;
    }
  }
  return false;
}

export function demoteTransferSkillAfterExcludedWorkspaces(
  transfer: TransferSkillStateRecord | undefined,
  excludedWorkspaceIds: readonly string[],
  options?: { language?: string; currentWorkspaceId?: string },
): TransferSkillStateRecord | undefined {
  if (!transfer) {
    return undefined;
  }
  const excluded = new Set(excludedWorkspaceIds.map((item) => casefold(item)).filter(Boolean));
  if (excluded.size === 0) {
    return transfer;
  }
  const remainingWorkspaceIds = transfer.workspaceIds.filter((id) => !excluded.has(casefold(id)));
  const remainingSceneKeys = transfer.sceneKeys.filter(
    (key) => !sceneKeyDependsOnExcludedWorkspace(key, excluded),
  );
  const removedProof =
    remainingWorkspaceIds.length !== transfer.workspaceIds.length ||
    remainingSceneKeys.length !== transfer.sceneKeys.length;
  if (!removedProof) {
    return transfer;
  }
  const currentWorkspaceId = text(options?.currentWorkspaceId);
  const localWorkspaceIds =
    remainingWorkspaceIds.length > 0
      ? remainingWorkspaceIds
      : currentWorkspaceId && !excluded.has(casefold(currentWorkspaceId))
        ? [currentWorkspaceId]
        : [];
  const localSceneKeys =
    remainingSceneKeys.length > 0
      ? remainingSceneKeys
      : localWorkspaceIds.length > 0
        ? [DEFAULT_TRANSFER_SCENE_KEY]
        : [];
  const remainingCount = localWorkspaceIds.length;
  if (remainingCount >= 2 && transfer.state === "transferable") {
    return {
      ...transfer,
      workspaceIds: localWorkspaceIds,
      sceneKeys: localSceneKeys,
      sceneCount: remainingCount,
    };
  }
  const copy = describeTransferSkillState("awaiting_second_scene", transfer.concept, options?.language);
  return {
    ...transfer,
    state: "awaiting_second_scene",
    sceneCount: Math.max(1, Math.min(remainingCount, 1)),
    workspaceIds: localWorkspaceIds,
    sceneKeys: localSceneKeys,
    why: copy.why,
    next: copy.next,
  };
}

export function resolveTransferSkillState(sceneCount: number): TransferSkillState {
  if (sceneCount >= 2) {
    return "transferable";
  }
  if (sceneCount === 1) {
    return "awaiting_second_scene";
  }
  return "project_only";
}

export function shouldPromoteTransferableSkill(input: TransferSkillDecisionInput): boolean {
  if (!input.outcomeSuccess) {
    return false;
  }
  const concept = text(input.concept);
  const workspaceId = text(input.workspaceId);
  if (!concept || !workspaceId) {
    return false;
  }
  const currentScene: TransferSkillScene = {
    workspaceId,
    sceneKey: text(input.currentSceneKey) || resolveSkillSceneKey(input),
  };
  return uniqueTransferWorkspaceIds([...(input.existingScenes ?? []), currentScene]).length >= 2;
}

export function describeTransferSkillState(
  state: TransferSkillState,
  concept?: string,
  language?: string,
): TransferSkillCopy {
  const zh = language === "zh-CN";
  const named = text(concept);
  if (state === "transferable") {
    return {
      label: zh ? "可迁移" : "Transferable",
      why: named
        ? zh
          ? `「${named}」已在多个场景得到验证。`
          : `"${named}" has evidence in more than one scene.`
        : zh
          ? "这项能力已在多个场景得到验证。"
          : "This skill has evidence in more than one scene.",
      next: zh
        ? "安排复习，或在新挑战里再应用一次。"
        : "Schedule a review, or apply it in a new challenge.",
    };
  }
  if (state === "awaiting_second_scene") {
    return {
      label: zh ? "仍属当前项目" : "Project-scoped",
      why: named
        ? zh
          ? `「${named}」目前只在这个项目里验证过。`
          : `"${named}" is verified in this project only.`
        : zh
          ? "这次成功只停在当前项目。"
          : "This success stays in the current project.",
      next: zh
        ? "再到另一个工作区验证，才能记为可迁移能力。"
        : "Confirm it in another workspace before treating it as transferable.",
    };
  }
  return {
    label: zh ? "项目内证据" : "Project evidence",
    why: zh ? "这条证据留在当前项目。" : "This evidence stays in the current project.",
    next: zh
      ? "继续在这里做；全局迁移需要第二个场景。"
      : "Keep working here; global transfer needs a second scene.",
  };
}

export function buildTransferSkillStateRecord(input: {
  concept: string;
  scenes: TransferSkillScene[];
  language?: string;
}): TransferSkillStateRecord {
  const unique = uniqueTransferScenes(input.scenes);
  const state = resolveTransferSkillState(uniqueTransferWorkspaceIds(unique).length);
  const copy = describeTransferSkillState(state, input.concept, input.language);
  return {
    concept: text(input.concept),
    state,
    sceneCount: unique.length,
    workspaceIds: [...new Set(unique.map((scene) => scene.workspaceId))],
    sceneKeys: [...new Set(unique.map((scene) => scene.sceneKey))],
    why: copy.why,
    next: copy.next,
  };
}

export function normalizeTransferSkillStateRecord(value: unknown): TransferSkillStateRecord | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  const state = normalizeTransferSkillState(
    typeof record.state === "string" ? record.state : undefined,
  );
  const concept = text(typeof record.concept === "string" ? record.concept : "");
  if (!state || !concept) {
    return undefined;
  }
  const sceneCountRaw = record.sceneCount ?? record.scene_count;
  const sceneCount = typeof sceneCountRaw === "number" && Number.isFinite(sceneCountRaw) ? sceneCountRaw : 0;
  const workspaceIds = Array.isArray(record.workspaceIds)
    ? record.workspaceIds
    : Array.isArray(record.workspace_ids)
      ? record.workspace_ids
      : [];
  const sceneKeys = Array.isArray(record.sceneKeys)
    ? record.sceneKeys
    : Array.isArray(record.scene_keys)
      ? record.scene_keys
      : [];
  return {
    concept,
    state,
    sceneCount: Math.max(0, Math.floor(sceneCount)),
    workspaceIds: workspaceIds.filter((item): item is string => typeof item === "string" && item.trim().length > 0),
    sceneKeys: sceneKeys.filter((item): item is string => typeof item === "string" && item.trim().length > 0),
    why: text(typeof record.why === "string" ? record.why : ""),
    next: text(typeof record.next === "string" ? record.next : ""),
  };
}

export function applyTransferSkillToCoachOrientation<T extends {
  objectKind?: string;
  state?: string;
  nextStep?: string;
  advancedWhere?: string;
}>(
  orientation: T,
  transfer: TransferSkillStateRecord | undefined,
): T {
  if (!transfer || !orientation.state || orientation.state !== "ready") {
    return orientation;
  }
  const advanced = [orientation.advancedWhere?.trim(), transfer.why].filter(Boolean).join(" · ");
  if (transfer.state === "transferable" && (orientation.objectKind === "conversation" || orientation.objectKind === "plan")) {
    return {
      ...orientation,
      nextStep: transfer.next || orientation.nextStep,
      advancedWhere: advanced,
    };
  }
  if (transfer.state === "awaiting_second_scene" || transfer.state === "transferable") {
    return {
      ...orientation,
      advancedWhere: advanced,
    };
  }
  return orientation;
}
