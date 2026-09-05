import type { ComposerLanguage } from "./types";

// Re-export ComposerLanguage with domain-specific aliases for type safety
export type TrainingCardCopyLanguage = ComposerLanguage;
export type NarrowSidebarCopyLanguage = ComposerLanguage;

type TrainingCardCopyOptions = {
  maxLength?: number;
  maxItems?: number;
};

const TRAINING_SCENARIO_PACK_LABELS: Record<
  string,
  {
    zh: string;
    en: string;
  }
> = {
  remote_workspace: {
    zh: "远程边界",
    en: "Remote boundary",
  },
  debug_loop: {
    zh: "调试闭环",
    en: "Minimal debug loop",
  },
  function_guidance: {
    zh: "函数契约恢复",
    en: "Function contract recovery",
  },
};

const COPY_TRANSLATIONS: Array<{ zh: string; en: string }> = [
  {
    zh: "改登录失败的提示",
    en: "Fix the login error message",
  },
  {
    zh: "改当前文件里这段错误处理",
    en: "Fix the login error message",
  },
  {
    zh: "打开当前文件，把错误提示改成和真实返回一致。",
    en: "Open the current file and make the message match the status code.",
  },
  {
    zh: "用错误账号登录一次，提示要和返回码对上。",
    en: "Sign in with a wrong account and see if the message matches.",
  },
  {
    zh: "错误提示已经对上真实返回码。",
    en: "The message already matches the status code.",
  },
  {
    zh: "打开当前文件，让提示跟返回码一致。",
    en: "Open the current file and make the message match the status code.",
  },
  {
    zh: "打开当前文件，让提示跟返回码一致。",
    en: "Open the current file and make the message match the status code.",
  },
  {
    zh: "实现一个 response_model 路由切片",
    en: "Implement one response_model route slice",
  },
  {
    zh: "目标模型已返回，聚焦测试通过。",
    en: "The route returns the target model and the focused test passes.",
  },
  {
    zh: "目标模型已返回，聚焦测试通过。",
    en: "Route returns the expected model and the focused test passes.",
  },
  {
    zh: "同一套响应契约检查，现在能在另一条受控只读路由里复现。",
    en: "The same response-contract check now repeats in another governed read-only route.",
  },
  {
    zh: "聚焦测试输出",
    en: "Focused test output",
  },
  {
    zh: "响应载荷",
    en: "Response payload",
  },
  {
    zh: "你亲手改动过的路由切片",
    en: "One route slice you changed yourself",
  },
  {
    zh: "运行聚焦测试",
    en: "Run the focused test",
  },
  {
    zh: "确认返回字段符合 response_model",
    en: "Confirm the returned fields match response_model",
  },
  {
    zh: "不要在这张卡里顺手扩更多业务逻辑",
    en: "Do not widen extra business logic in this card",
  },
  {
    zh: "带回聚焦测试输出、响应载荷，以及一个仍未解决的问题。",
    en: "Bring back the focused test output, the response payload, and one open question.",
  },
  {
    zh: "聚焦测试输出、响应载荷，以及你实际改动的路由文件",
    en: "The focused test output, the response payload, and the route file you changed",
  },
  {
    zh: "把这次结果记成计划证据，再决定是否补一张 response_model 闪记卡。",
    en: "Log this result as plan evidence, then decide whether response_model needs one flash card.",
  },
  {
    zh: "如果测试没过，先把失败输出带回教练，不要继续盲改。",
    en: "If the test still fails, bring the failing output back to coach before changing more code.",
  },
  {
    zh: "先完成最小 route 契约切片，再把结果回带给教练判定下一跳。",
    en: "Finish the smallest route-contract slice first, then bring it back so the coach can choose the next hop.",
  },
  {
    zh: "这条 route 仍然失败，因为 response model 的结构不对。",
    en: "The route still fails because the response model shape is wrong.",
  },
  {
    zh: "当前进度已经压到单文件 route 切片。",
    en: "The route body is already narrowed to one file.",
  },
  {
    zh: "完成前几轮教练回合后，这里会出现稳定的复习节奏。",
    en: "A stable review rhythm will appear after the first few coaching turns.",
  },
  {
    zh: "还没有形成复习节奏。",
    en: "No review schedule yet.",
  },
  {
    zh: "先把安装和启动链路跑通。",
    en: "Finish the setup first.",
  },
  {
    zh: "先从更小的规格切片开始。",
    en: "Start with a smaller spec.",
  },
  {
    zh: "保持当前可见界面收敛。",
    en: "Keep the visible surface narrow.",
  },
  {
    zh: "让复杂度留在后端。",
    en: "Let the backend hold the complexity.",
  },
];

function compact(value?: string): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  return normalized ? normalized : undefined;
}

function translateKnownCopy(language: TrainingCardCopyLanguage, value: string): string {
  let translated = value;
  for (const pair of COPY_TRANSLATIONS) {
    if (language === "zh-CN" && translated.includes(pair.en)) {
      translated = translated.split(pair.en).join(pair.zh);
    }
    if (language === "en-US" && translated.includes(pair.zh)) {
      translated = translated.split(pair.zh).join(pair.en);
    }
  }
  return translated;
}

export function normalizeNarrowSidebarCopy(
  language: NarrowSidebarCopyLanguage,
  value?: string,
): string | undefined {
  const normalized = compact(value);
  if (!normalized) {
    return undefined;
  }
  return translateKnownCopy(language, normalized);
}

function truncateAtBoundary(value: string, limit: number): string {
  if (value.length <= limit) {
    return value;
  }

  const boundaryChars = ["。", "！", "？", ".", "!", "?", "；", ";", "：", ":", "，", ",", "、", " "];
  let boundary = -1;
  for (const char of boundaryChars) {
    const index = value.lastIndexOf(char, limit);
    if (index > boundary) {
      boundary = index;
    }
  }

  if (boundary >= Math.floor(limit * 0.55)) {
    return value.slice(0, Math.min(boundary + 1, limit)).trim();
  }

  return `${value.slice(0, Math.max(0, limit - 3)).trimEnd()}...`;
}

function preferredLead(value: string, language: TrainingCardCopyLanguage): string {
  const patterns =
    language === "zh-CN"
      ? [/，同时/u, /，再/u, /，并且/u, /，并/u, /；/u, /。/u]
      : [/, then /iu, /, and /iu, /; /u, /\. /u];

  for (const pattern of patterns) {
    const parts = value.split(pattern);
    const first = compact(parts[0]);
    if (first && first.length >= 18) {
      return first;
    }
  }

  return value;
}

export function compactTrainingCardText(
  language: TrainingCardCopyLanguage,
  value?: string,
  options?: TrainingCardCopyOptions,
): string | undefined {
  return compactNarrowSidebarText(language, value, {
    maxLength: options?.maxLength ?? 88,
  });
}

export function summarizeTrainingCardLead(
  language: TrainingCardCopyLanguage,
  value?: string,
  options?: TrainingCardCopyOptions,
): string | undefined {
  return summarizeNarrowSidebarLead(language, value, {
    maxLength: options?.maxLength ?? 96,
  });
}

export function summarizeTrainingScenarioPack(
  language: TrainingCardCopyLanguage,
  scenarioPack?: string,
): string | undefined {
  const normalized = compact(scenarioPack);
  if (!normalized) {
    return undefined;
  }

  const knownLabel = TRAINING_SCENARIO_PACK_LABELS[normalized];
  if (knownLabel) {
    return language === "zh-CN" ? knownLabel.zh : knownLabel.en;
  }

  return undefined;
}

export function compactTrainingCardList(
  language: TrainingCardCopyLanguage,
  values: readonly string[] | undefined,
  options?: TrainingCardCopyOptions,
): string[] {
  return compactNarrowSidebarList(language, values, {
    maxItems: options?.maxItems ?? 3,
    maxLength: options?.maxLength ?? 72,
  });
}

export function compactNarrowSidebarText(
  language: NarrowSidebarCopyLanguage,
  value?: string,
  options?: TrainingCardCopyOptions,
): string | undefined {
  const localized = normalizeNarrowSidebarCopy(language, value);
  if (!localized) {
    return undefined;
  }
  const maxLength = options?.maxLength ?? 88;
  return truncateAtBoundary(localized, maxLength);
}

export function summarizeNarrowSidebarLead(
  language: NarrowSidebarCopyLanguage,
  value?: string,
  options?: TrainingCardCopyOptions,
): string | undefined {
  const localized = normalizeNarrowSidebarCopy(language, value);
  if (!localized) {
    return undefined;
  }
  const focused = preferredLead(localized, language);
  const maxLength = options?.maxLength ?? 96;
  return truncateAtBoundary(focused, maxLength);
}

export function compactNarrowSidebarList(
  language: NarrowSidebarCopyLanguage,
  values: readonly string[] | undefined,
  options?: TrainingCardCopyOptions,
): string[] {
  const maxItems = options?.maxItems ?? 3;
  const seen = new Set<string>();
  const items: string[] = [];

  for (const value of values ?? []) {
    const item = compactTrainingCardText(language, value, { maxLength: options?.maxLength ?? 72 });
    if (!item || seen.has(item)) {
      continue;
    }
    seen.add(item);
    items.push(item);
    if (items.length >= maxItems) {
      break;
    }
  }

  return items;
}
