import type { ComposerLanguage } from "./types";
import type { SidebarViewName } from "./sendIntelligence";
import { trainerCommands, type TrainerCommand } from "./commands";

export type TrainerSkillSection =
  | "Coach"
  | "Plan"
  | "Training"
  | "Resources"
  | "Workspace"
  | "Provider";

export interface TrainerSkillContext {
  activeView: SidebarViewName;
  hasActiveFile: boolean;
  hasSelection: boolean;
  relatedFilesCount: number;
  resourceCount: number;
}

export interface TrainerSkillCatalogItem {
  id: string;
  trigger: `$${string}`;
  section: TrainerSkillSection;
  title: TrainerSkillText;
  detail: TrainerSkillText;
  keywords: string[];
  commandId: TrainerCommand;
  payload?: Record<string, unknown>;
  prompt?: TrainerSkillText;
  source?: TrainerSkillSource;
  when?: (context: TrainerSkillContext) => boolean;
}

export interface TrainerSkillSource {
  repo: string;
  license: string;
  note: string;
}

export type TrainerSkillText = Partial<Record<ComposerLanguage, string>>;

export function resolveTrainerSkillText(
  value: TrainerSkillText | undefined,
  language: ComposerLanguage,
): string {
  if (!value) {
    return "";
  }

  return (
    value[language] ??
    value["en-US"] ??
    value["zh-CN"] ??
    Object.values(value).find((entry): entry is string => typeof entry === "string" && entry.trim().length > 0) ??
    ""
  );
}

export function trainerSkillSectionLabel(
  section: TrainerSkillSection,
  language: ComposerLanguage,
): string {
  if (language === "zh-CN") {
    switch (section) {
      case "Coach":
        return "教练";
      case "Plan":
        return "计划";
      case "Training":
        return "训练";
      case "Resources":
        return "资料";
      case "Workspace":
        return "工作区";
      case "Provider":
        return "模型";
    }
  }

  return section;
}

export const trainerSkillCatalog: TrainerSkillCatalogItem[] = [
  {
    id: "explain-principle",
    trigger: "$explain",
    section: "Coach",
    title: {
      "zh-CN": "解释原理",
      "en-US": "Explain principle",
    },
    detail: {
      "zh-CN": "解释当前代码背后的原理，并指出最关键的阻塞点。",
      "en-US": "Explain the principle behind the current code and name the key blocker.",
    },
    keywords: ["explain", "principle", "why", "how", "understand", "原理", "解释"],
    commandId: trainerCommands.sendStreamMessage,
    prompt: {
      "zh-CN": "解释当前代码背后的原理，并指出最关键的阻塞点。",
      "en-US": "Explain the principle behind the current code and name the key blocker.",
    },
  },
  {
    id: "deep-lecture",
    trigger: "$lecture",
    section: "Coach",
    title: {
      "zh-CN": "讲透主题",
      "en-US": "Deep lecture",
    },
    detail: {
      "zh-CN": "先搜索并筛选资料，再按状态流把理论和代码讲明白。",
      "en-US": "Search, filter, then explain theory and code through a state-driven walkthrough.",
    },
    keywords: [
      "lecture",
      "deep explain",
      "theory",
      "walkthrough",
      "teach",
      "讲透",
      "讲明白",
      "理论讲解",
      "代码讲解",
    ],
    commandId: trainerCommands.sendStreamMessage,
    prompt: {
      "zh-CN":
        "先搜索并筛选相关资料，再按“当前状态 -> 缺口 -> 对象或约束 -> 代码或 API -> 验证 -> 新状态”的顺序，把这个主题讲明白。不要先下定义。每 2-3 个新对象做一次状态回收。输出语言跟随当前默认语言，technical terms 如 API、protocol、remote、debug、hover、signature help 可保留英文。",
      "en-US":
        "Search and filter the relevant material first, then explain the topic in the order current state -> gap -> object or constraint -> code or API -> verification -> new state. Do not lead with definitions. Recycle the state every 2-3 new objects. Match the active language, keeping technical terms like API, protocol, remote, debug, hover, and signature help in English when clearer.",
    },
  },
  {
    id: "reach-pass",
    trigger: "$reach",
    section: "Resources",
    title: {
      "zh-CN": "\u5148\u505a reach \u68c0\u7d22",
      "en-US": "Run a reach pass",
    },
    detail: {
      "zh-CN":
        "\u5148\u626b\u8fc7\u8d44\u6599\u5e93\u3001\u9879\u76ee\u4e0a\u4e0b\u6587\u548c\u5df2\u6709\u7b14\u8bb0\uff0c\u5fc5\u8981\u65f6\u518d\u8865 governed web search\u3002",
      "en-US":
        "Sweep the library, project context, and saved notes first, then add governed web search only if a real gap remains.",
    },
    keywords: [
      "reach",
      "retrieval",
      "search",
      "source map",
      "grounding",
      "agent reach",
      "\u68c0\u7d22",
      "\u8d44\u6599",
      "\u6765\u6e90",
      "\u7d22\u5f15",
    ],
    commandId: trainerCommands.sendStreamMessage,
    prompt: {
      "zh-CN":
        "\u5148\u505a\u4e00\u8f6e retrieval-first reach\uff1a\u5148\u641c\u5f53\u524d\u8d44\u6599\u5e93\u3001\u5f53\u524d\u9879\u76ee\u4e0a\u4e0b\u6587\u548c\u5df2\u6709\u7b14\u8bb0\uff1b\u5982\u679c\u8fd8\u6709\u7f3a\u53e3\uff0c\u518d\u8865 governed web search\u3002\u628a\u6240\u6709\u76f8\u5173\u6765\u6e90\u6309\u6700\u76f8\u5173\u3001\u6700\u53ef\u4fe1\u3001\u6700\u9002\u5408\u5f53\u524d\u4e0b\u4e00\u6b65\u6392\u5e8f\uff0c\u53ea\u4fdd\u7559\u524d 3 \u4e2a\u5e76\u8bf4\u6e05\u695a\u4e3a\u4ec0\u4e48\u3002",
      "en-US":
        "Run a retrieval-first reach pass: search the current library, project context, and saved notes first; if gaps remain, add governed web search. Rank every relevant source by relevance, trust, and fit for the immediate next step, then keep only the top three and explain why.",
    },
    source: {
      repo: "https://github.com/Panniantong/agent-reach",
      license: "MIT",
      note: "Retrieval-first reach pattern",
    },
  },
  {
    id: "source-map",
    trigger: "$map",
    section: "Resources",
    title: {
      "zh-CN": "\u6784\u5efa source map",
      "en-US": "Build a source map",
    },
    detail: {
      "zh-CN":
        "\u628a\u5f53\u524d\u4e3b\u9898\u62c6\u6210 official docs\u3001code examples\u3001failure cases \u548c tutorials\uff0c\u5148\u770b\u5168\u5c40\u518d\u51b3\u5b9a\u8bfb\u54ea\u4e2a\u3002",
      "en-US":
        "Cluster the topic into official docs, code examples, failure cases, and tutorials before deciding what to read next.",
    },
    keywords: [
      "map",
      "source map",
      "cluster",
      "official docs",
      "examples",
      "failure cases",
      "\u6765\u6e90\u56fe",
      "\u805a\u7c7b",
      "\u5b98\u65b9\u6587\u6863",
    ],
    commandId: trainerCommands.sendStreamMessage,
    prompt: {
      "zh-CN":
        "\u5148\u7ed9\u6211\u505a\u4e00\u4e2a source map\uff1a\u628a\u5f53\u524d\u4e3b\u9898\u5206\u6210 official docs\u3001code examples\u3001failure cases\u3001tutorials \u8fd9\u56db\u7ec4\uff0c\u8bf4\u6e05\u695a\u5404\u7ec4\u73b0\u5728\u6700\u503c\u5f97\u770b\u7684\u6765\u6e90\u662f\u54ea\u4e9b\uff0c\u8fd8\u7f3a\u4ec0\u4e48\uff0c\u4ee5\u53ca\u4e0b\u4e00\u6b65\u5e94\u8be5\u5148\u8bfb\u54ea\u4e00\u7ec4\u3002",
      "en-US":
        "Build a source map first: split the current topic into official docs, code examples, failure cases, and tutorials. Name the best sources in each group, what is still missing, and which group should be read first for the current next step.",
    },
    source: {
      repo: "https://github.com/heilcheng/awesome-agent-skills",
      license: "MIT",
      note: "Skill discovery and curation patterns",
    },
  },
  {
    id: "distill-sources",
    trigger: "$distill",
    section: "Resources",
    title: {
      "zh-CN": "\u628a\u8d44\u6599\u538b\u6210\u6559\u5b66\u8d44\u4ea7",
      "en-US": "Distill sources into teaching assets",
    },
    detail: {
      "zh-CN":
        "\u628a\u5f53\u524d\u8d44\u6599\u538b\u6210 note\u3001flash candidate\u3001practice card candidate \u548c plan evidence candidate\u3002",
      "en-US":
        "Compress the current sources into one note, one flash candidate, one practice-card candidate, and one plan-evidence candidate.",
    },
    keywords: [
      "distill",
      "digest",
      "note",
      "flash",
      "practice card",
      "evidence",
      "\u63d0\u70bc",
      "\u7b14\u8bb0",
      "\u5361\u7247",
      "\u8bc1\u636e",
    ],
    commandId: trainerCommands.sendStreamMessage,
    prompt: {
      "zh-CN":
        "\u628a\u5f53\u524d\u8d44\u6599\u538b\u6210\u53ef\u590d\u7528\u6559\u5b66\u8d44\u4ea7\uff1a1 \u6761 compact note\uff0c1 \u4e2a flash candidate\uff0c1 \u4e2a practice card candidate\uff0c1 \u4e2a plan evidence candidate\u3002\u5148\u4fdd\u6301\u7c92\u5ea6\u5c0f\uff0c\u4e0d\u8981\u62c9\u6210\u5927\u800c\u5168\u6458\u8981\u3002",
      "en-US":
        "Distill the current sources into reusable teaching assets: one compact note, one flash candidate, one practice-card candidate, and one plan-evidence candidate. Keep the grain small instead of writing a broad summary.",
    },
    source: {
      repo: "https://github.com/microsoft/markitdown",
      license: "MIT",
      note: "Document normalization and teaching-asset extraction",
    },
  },
  {
    id: "bundle-skill",
    trigger: "$bundle",
    section: "Resources",
    title: {
      "zh-CN": "打包 skill bundle",
      "en-US": "Package a skill bundle",
    },
    detail: {
      "zh-CN": "把当前主题整理成可复用的 skill bundle，写清 trigger、scope、输入、输出、例子和 guardrails。",
      "en-US":
        "Turn the current topic into a reusable skill bundle with trigger, scope, inputs, outputs, examples, and guardrails.",
    },
    keywords: ["bundle", "skill", "package", "manifest", "skill.md", "openskills", "打包", "技能"],
    commandId: trainerCommands.sendStreamMessage,
    prompt: {
      "zh-CN":
        "把当前主题整理成一个可复用的 skill bundle candidate：写清 trigger、scope、inputs、outputs、examples、guardrails 和 provenance，并建议应该放进 Resources 还是单独保存。先给最小可用版本。",
      "en-US":
        "Turn the current topic into a reusable skill bundle candidate: write down trigger, scope, inputs, outputs, examples, guardrails, and provenance. Suggest whether it belongs in Resources or should stay separate. Start with the smallest usable version.",
    },
    source: {
      repo: "https://github.com/numman-ali/openskills",
      license: "Apache-2.0",
      note: "Portable skill-file packaging",
    },
  },
  {
    id: "settings-audit",
    trigger: "$settings",
    section: "Provider",
    title: {
      "zh-CN": "检查 settings 真相",
      "en-US": "Audit settings truth",
    },
    detail: {
      "zh-CN": "核对 provider、model、protocol、API key、runtime 和 workspace control 是否真的可用。",
      "en-US": "Verify whether the provider, model, protocol, API key, runtime, and workspace controls are truly usable.",
    },
    keywords: ["settings", "provider", "model", "protocol", "api", "runtime", "truth", "config", "配置", "真实"],
    commandId: trainerCommands.sendStreamMessage,
    prompt: {
      "zh-CN":
        "请检查 Settings 里的 provider、model、protocol、API key、runtime 和 workspace control 真相；告诉我哪些可用、哪些被阻断、下一步该怎么修。不要假设可用。",
      "en-US":
        "Check the truth of provider, model, protocol, API key, runtime, and workspace control in Settings. Tell me what is usable, what is blocked, and what to fix next. Do not assume availability.",
    },
  },
  {
    id: "review-file",
    trigger: "$review",
    section: "Coach",
    title: {
      "zh-CN": "审阅当前文件",
      "en-US": "Review current file",
    },
    detail: {
      "zh-CN": "直接读取 IDE 当前文件和诊断，做一次有依据的审阅。",
      "en-US": "Read the active IDE file and diagnostics for a grounded review.",
    },
    keywords: ["review", "inspect", "check", "audit", "file", "review current file", "审阅", "文件"],
    commandId: trainerCommands.evaluateCurrentFile,
    when: (context) => context.hasActiveFile,
  },
  {
    id: "review-selection",
    trigger: "$selection",
    section: "Coach",
    title: {
      "zh-CN": "审阅选中内容",
      "en-US": "Review selection",
    },
    detail: {
      "zh-CN": "只看当前选区，适合片段和局部验证。",
      "en-US": "Review only the current selection for focused checks.",
    },
    keywords: ["selection", "snippet", "review", "range", "选区", "片段"],
    commandId: trainerCommands.evaluateSelection,
    when: (context) => context.hasSelection,
  },
  {
    id: "generate-plan",
    trigger: "$plan",
    section: "Plan",
    title: {
      "zh-CN": "刷新计划",
      "en-US": "Refresh plan",
    },
    detail: {
      "zh-CN": "重新整理当前学习计划，聚焦下一步。",
      "en-US": "Regenerate the current learning plan and sharpen the next step.",
    },
    keywords: ["plan", "roadmap", "refresh", "schedule", "计划", "整理"],
    commandId: trainerCommands.generatePlan,
  },
  {
    id: "specify-task",
    trigger: "$task",
    section: "Plan",
    title: {
      "zh-CN": "转成任务",
      "en-US": "Turn into task",
    },
    detail: {
      "zh-CN": "把一个目标改写成可执行、可验证的小任务。",
      "en-US": "Convert a goal into a concrete, verifiable task.",
    },
    keywords: ["task", "spec", "goal", "implement", "目标", "任务"],
    commandId: trainerCommands.taskSpecify,
    payload: {
      source: "skill",
    },
  },
  {
    id: "next-task",
    trigger: "$next",
    section: "Training",
    title: {
      "zh-CN": "下一步任务",
      "en-US": "Next task",
    },
    detail: {
      "zh-CN": "根据当前计划和进度，直接给出下一步。",
      "en-US": "Generate the next step from the current plan and progress.",
    },
    keywords: ["next", "task", "practice", "advance", "continue", "下一步", "训练"],
    commandId: trainerCommands.nextTask,
  },
  {
    id: "practice-card",
    trigger: "$practice",
    section: "Training",
    title: {
      "zh-CN": "实战卡",
      "en-US": "Practice card",
    },
    detail: {
      "zh-CN": "生成一张实战卡，让训练围绕当前项目出题并验收。",
      "en-US": "Generate a practice card grounded in the current project.",
    },
    keywords: ["practice", "card", "training", "exercise", "实战", "练习"],
    commandId: trainerCommands.trainingGenerateCard,
    payload: {
      submode: "practice",
    },
  },
  {
    id: "flash-card",
    trigger: "$flash",
    section: "Training",
    title: {
      "zh-CN": "闪记卡",
      "en-US": "Flash card",
    },
    detail: {
      "zh-CN": "生成一张闪记卡，适合选择、填空和简答。",
      "en-US": "Generate a flash card for choice, fill, or short-answer recall.",
    },
    keywords: ["flash", "memory", "card", "recall", "闪记", "记忆"],
    commandId: trainerCommands.trainingGenerateCard,
    payload: {
      submode: "flash",
    },
  },
  {
    id: "refresh-memory",
    trigger: "$memory",
    section: "Workspace",
    title: {
      "zh-CN": "刷新记忆",
      "en-US": "Refresh memory",
    },
    detail: {
      "zh-CN": "重新读取当前画像、计划和工作区摘要。",
      "en-US": "Reload the current profile, plan, and workspace summary.",
    },
    keywords: ["memory", "profile", "summary", "refresh", "记忆", "摘要"],
    commandId: trainerCommands.refreshMemory,
    source: {
      repo: "https://github.com/mem0ai/mem0",
      license: "Apache-2.0",
      note: "Long-lived memory and recovery patterns",
    },
  },
  {
    id: "refresh-sandbox",
    trigger: "$sandbox",
    section: "Resources",
    title: {
      "zh-CN": "刷新沙箱",
      "en-US": "Refresh sandbox",
    },
    detail: {
      "zh-CN": "重新生成受控沙箱能力摘要。",
      "en-US": "Rebuild the governed sandbox capability summary.",
    },
    keywords: ["sandbox", "refresh", "guard", "capability", "沙箱"],
    commandId: trainerCommands.refreshSandbox,
  },
  {
    id: "upload-resource",
    trigger: "$resource",
    section: "Resources",
    title: {
      "zh-CN": "添加资料",
      "en-US": "Add resource",
    },
    detail: {
      "zh-CN": "导入文件、文件夹或链接作为教练资料。",
      "en-US": "Import files, folders, or links into the resource library.",
    },
    keywords: ["resource", "upload", "file", "folder", "url", "资料", "导入"],
    commandId: trainerCommands.uploadResource,
  },
  {
    id: "index-resources",
    trigger: "$index",
    section: "Resources",
    title: {
      "zh-CN": "索引资料",
      "en-US": "Index resources",
    },
    detail: {
      "zh-CN": "重新索引已附加的资料，刷新搜索命中。",
      "en-US": "Re-index attached resources and refresh search hits.",
    },
    keywords: ["index", "resources", "search", "chunk", "索引", "搜索"],
    commandId: trainerCommands.indexResources,
  },
  {
    id: "test-provider",
    trigger: "$provider",
    section: "Provider",
    title: {
      "zh-CN": "测试模型",
      "en-US": "Test provider",
    },
    detail: {
      "zh-CN": "检查当前 provider、模型和 API key 是否可用。",
      "en-US": "Check that the configured provider, model, and API key are ready.",
    },
    keywords: ["provider", "test", "model", "api", "key", "模型", "测试"],
    commandId: trainerCommands.testProvider,
  },
  {
    id: "refresh-models",
    trigger: "$models",
    section: "Provider",
    title: {
      "zh-CN": "刷新模型",
      "en-US": "Refresh models",
    },
    detail: {
      "zh-CN": "重新拉取当前 provider 的模型列表。",
      "en-US": "Reload the current provider model list.",
    },
    keywords: ["model", "models", "refresh", "list", "cache", "模型", "刷新"],
    commandId: trainerCommands.refreshProviderModels,
  },
];

const SECTION_ORDER: TrainerSkillSection[] = [
  "Coach",
  "Plan",
  "Training",
  "Resources",
  "Workspace",
  "Provider",
];

export function normalizeSkillQuery(value: string): string {
  return value.trim().replace(/^\$+/, "").replace(/\s+/g, " ").toLowerCase();
}

export function filterTrainerSkills(
  value: string,
  context: TrainerSkillContext,
  limit = 8,
): TrainerSkillCatalogItem[] {
  const normalized = normalizeSkillQuery(value);
  const candidates = trainerSkillCatalog.filter((skill) => !skill.when || skill.when(context));
  const ranked = candidates
    .map((skill, index) => ({
      skill,
      index,
      score: scoreSkill(skill, normalized),
    }))
    .sort((left, right) => {
      if (right.score !== left.score) {
        return right.score - left.score;
      }
      const leftSection = SECTION_ORDER.indexOf(left.skill.section);
      const rightSection = SECTION_ORDER.indexOf(right.skill.section);
      if (leftSection !== rightSection) {
        return leftSection - rightSection;
      }
      return left.index - right.index;
    });

  if (!normalized) {
    return ranked.map((entry) => entry.skill).slice(0, limit);
  }

  return ranked.filter((entry) => entry.score > 0).map((entry) => entry.skill).slice(0, limit);
}

function scoreSkill(skill: TrainerSkillCatalogItem, normalizedQuery: string): number {
  if (!normalizedQuery) {
    return 0;
  }

  const normalizedTrigger = skill.trigger.toLowerCase().replace(/^\$+/, "");
  if (normalizedTrigger === normalizedQuery) {
    return 200;
  }
  if (normalizedTrigger.startsWith(normalizedQuery)) {
    return 160;
  }

  let score = 0;
  const pools = [
    resolveTrainerSkillText(skill.title, "en-US"),
    resolveTrainerSkillText(skill.title, "zh-CN"),
    resolveTrainerSkillText(skill.detail, "en-US"),
    resolveTrainerSkillText(skill.detail, "zh-CN"),
    ...skill.keywords,
  ].map((value) => value.toLowerCase());

  for (const candidate of pools) {
    if (!candidate) {
      continue;
    }
    if (candidate === normalizedQuery) {
      score = Math.max(score, 140);
      continue;
    }
    if (candidate.startsWith(normalizedQuery)) {
      score = Math.max(score, 120);
      continue;
    }
    if (candidate.includes(normalizedQuery)) {
      score = Math.max(score, 80);
    }
  }

  return score;
}
