import type { ComposerLanguage } from "./types";

export type CoachToolActivitySendSnapshot = {
  name: string;
  status: "running" | "succeeded" | "failed" | string;
};

const TOOL_LABELS: Record<string, { zh: string; en: string }> = {
  search_resources: { zh: "搜索资料", en: "search resources" },
  search: { zh: "搜索", en: "search" },
  read_workspace_file: { zh: "读取文件", en: "read a file" },
  list_workspace_files: { zh: "浏览文件", en: "list files" },
  recall_memory: { zh: "回顾记忆", en: "recall memory" },
  record_learning_note: { zh: "保存观察", en: "save a note" },
  inspect_plan: { zh: "查看计划", en: "inspect the plan" },
  verify_practice_current_file: { zh: "验证实战", en: "verify practice" },
  generate_training_card: { zh: "生成训练卡", en: "generate a training card" },
  generate_cards: { zh: "生成训练卡", en: "generate cards" },
  run_diagnostics: { zh: "运行诊断", en: "run diagnostics" },
  align_plan: { zh: "对齐计划", en: "align the plan" },
  plan_alignment: { zh: "对齐计划", en: "align the plan" },
  card_generation: { zh: "生成训练卡", en: "generate a training card" },
  evaluation: { zh: "评估结果", en: "evaluate results" },
  coach_finalize: { zh: "收束回复", en: "finalize the reply" },
  debug_loop: { zh: "调试闭环", en: "run the debug loop" },
};

function toolVerb(name: string, language: ComposerLanguage): string {
  const entry = TOOL_LABELS[name.trim()];
  if (entry) {
    return language === "zh-CN" ? entry.zh : entry.en;
  }
  return language === "zh-CN" ? "处理工具步骤" : "run a tool step";
}

/**
 * Composer send-busy copy while Coach is mid tool-use / thinking / tool failure.
 * Prefer specific activity over a generic "thinking" label.
 */
export function describeCoachToolActivitySendBusy(
  language: ComposerLanguage,
  activities: readonly CoachToolActivitySendSnapshot[] | undefined,
): string | undefined {
  const items = (activities ?? []).filter((item) => Boolean(item?.name?.trim()));
  if (items.length === 0) {
    return undefined;
  }

  const zh = language === "zh-CN";
  const running = items.filter((item) => item.status === "running");
  const failed = items.filter((item) => item.status === "failed");
  const succeeded = items.filter((item) => item.status === "succeeded");

  if (failed.length > 0) {
    if (running.length > 0) {
      return zh
        ? "工具步骤失败，仍在核对上下文（发送暂不可用）"
        : "A tool step failed; still checking context (send paused)";
    }
    const label = toolVerb(failed[0].name, language);
    return zh
      ? `工具失败：${label}。发送暂不可用，等本轮结束后可重试`
      : `Tool failed: ${label}. Send paused until this turn finishes, then retry`;
  }

  if (running.length > 0) {
    if (running.length === 1) {
      const label = toolVerb(running[0].name, language);
      return zh ? `正在调用工具：${label}（发送暂不可用）` : `Calling tool: ${label} (send paused)`;
    }
    return zh
      ? `正在并行调用 ${running.length} 个工具（发送暂不可用）`
      : `Calling ${running.length} tools (send paused)`;
  }

  if (succeeded.length > 0) {
    return zh
      ? "工具已完成，正在整理回复（发送暂不可用）"
      : "Tools finished; shaping the reply (send paused)";
  }

  return undefined;
}

/** Thinking-only busy copy when no tool activity is present yet. */
export function describeCoachThinkingSendBusy(language: ComposerLanguage): string {
  return language === "zh-CN"
    ? "正在思考（发送暂不可用）"
    : "Thinking (send paused)";
}
