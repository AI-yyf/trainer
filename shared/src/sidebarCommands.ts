export type SidebarControlCommandId =
  | "open-coach"
  | "open-plan"
  | "open-resources"
  | "open-training"
  | "open-settings"
  | "lang-zh"
  | "lang-en"
  | "mode-auto"
  | "mode-coach"
  | "mode-balanced"
  | "mode-direct"
  | "detail-focused"
  | "detail-balanced"
  | "detail-full"
  | "attach-all"
  | "attach-none"
  | "file-on"
  | "file-off"
  | "selection-on"
  | "selection-off"
  | "diagnostics-on"
  | "diagnostics-off"
  | "related-on"
  | "related-off"
  | "follow-on"
  | "follow-off";

import type { ComposerLanguage } from "./types";

export interface SidebarControlCommandDefinition {
  id: SidebarControlCommandId;
  aliases: string[];
  primaryLabel: {
    "zh-CN": string;
    "en-US": string;
  };
}

const definitions: SidebarControlCommandDefinition[] = [
  command("open-coach", ["/open coach", "/view coach", "/打开 教练"], "/打开 教练", "/open coach"),
  command("open-plan", ["/open plan", "/view plan", "/打开 计划"], "/打开 计划", "/open plan"),
  command("open-resources", ["/open resources", "/view resources", "/打开 资源"], "/打开 资源", "/open resources"),
  command("open-training", ["/open training", "/view training", "/打开 训练"], "/打开 训练", "/open training"),
  command("open-settings", ["/open settings", "/view settings", "/打开 设置"], "/打开 设置", "/open settings"),
  command("lang-zh", ["/lang zh", "/lang chinese", "/语言 中文"], "/语言 中文", "/lang zh"),
  command("lang-en", ["/lang en", "/lang english", "/语言 英文"], "/语言 英文", "/lang en"),
  command("mode-auto", ["/mode auto", "/mode 自动"], "/mode 自动", "/mode auto"),
  command("mode-coach", ["/mode coach", "/模式 引导"], "/模式 引导", "/mode coach"),
  command("mode-balanced", ["/mode balanced", "/模式 平衡"], "/模式 平衡", "/mode balanced"),
  command("mode-direct", ["/mode direct", "/模式 直接"], "/模式 直接", "/mode direct"),
  command("detail-focused", ["/detail focused", "/强度 聚焦"], "/强度 聚焦", "/detail focused"),
  command("detail-balanced", ["/detail balanced", "/强度 标准"], "/强度 标准", "/detail balanced"),
  command("detail-full", ["/detail full", "/强度 完整"], "/强度 完整", "/detail full"),
  command("attach-all", ["/attach all", "/附带 全部"], "/附带 全部", "/attach all"),
  command("attach-none", ["/attach none", "/附带 关闭"], "/附带 关闭", "/attach none"),
  command("file-on", ["/file on", "/文件 开"], "/文件 开", "/file on"),
  command("file-off", ["/file off", "/文件 关"], "/文件 关", "/file off"),
  command("selection-on", ["/selection on", "/选区 开"], "/选区 开", "/selection on"),
  command("selection-off", ["/selection off", "/选区 关"], "/选区 关", "/selection off"),
  command("diagnostics-on", ["/diagnostics on", "/诊断 开"], "/诊断 开", "/diagnostics on"),
  command("diagnostics-off", ["/diagnostics off", "/诊断 关"], "/诊断 关", "/diagnostics off"),
  command("related-on", ["/related on", "/相关 开"], "/相关 开", "/related on"),
  command("related-off", ["/related off", "/相关 关"], "/相关 关", "/related off"),
  command("follow-on", ["/follow on", "/跟随 开"], "/跟随 开", "/follow on"),
  command("follow-off", ["/follow off", "/跟随 关"], "/跟随 关", "/follow off"),
];

const legacyAliasRedirects = new Map<string, SidebarControlCommandId>([
  ["/open task", "open-coach"],
  ["/view task", "open-coach"],
  ["/打开 任务", "open-coach"],
  ["/open review", "open-coach"],
  ["/view review", "open-coach"],
  ["/打开 评审", "open-coach"],
  ["/open memory", "open-coach"],
  ["/view memory", "open-coach"],
  ["/打开 记忆", "open-coach"],
  ["/open research", "open-coach"],
  ["/view research", "open-coach"],
  ["/打开 研究", "open-coach"],
]);

const definitionMap = new Map(definitions.map((definition) => [definition.id, definition]));

export function normalizeSidebarCommandInput(value: string): string {
  return value.trim().replace(/\s+/g, " ").toLowerCase();
}

export function listSidebarControlCommands(): SidebarControlCommandDefinition[] {
  return definitions.map((definition) => ({ ...definition, aliases: [...definition.aliases] }));
}

export function findSidebarControlCommand(
  value: string,
): SidebarControlCommandDefinition | undefined {
  const normalized = normalizeSidebarCommandInput(value);
  if (!normalized.startsWith("/")) {
    return undefined;
  }
  const redirectedId = legacyAliasRedirects.get(normalized);
  if (redirectedId) {
    const redirected = definitionMap.get(redirectedId);
    if (redirected) {
      return { ...redirected, aliases: [...redirected.aliases] };
    }
  }
  return definitions.find((definition) =>
    definition.aliases.some((alias) => normalizeSidebarCommandInput(alias) === normalized),
  );
}

export function filterSidebarControlCommands(
  value: string,
  limit = 8,
): SidebarControlCommandDefinition[] {
  const normalized = normalizeSidebarCommandInput(value);
  if (!normalized.startsWith("/")) {
    return [];
  }
  const results = definitions
    .filter((definition) =>
      definition.aliases.some((alias) => normalizeSidebarCommandInput(alias).startsWith(normalized)),
    )
    .map((definition) => ({ ...definition, aliases: [...definition.aliases] }));
  const redirectedIds = Array.from(legacyAliasRedirects.entries())
    .filter(([alias]) => alias.startsWith(normalized))
    .map(([, id]) => id);
  for (const redirectedId of redirectedIds) {
    const definition = definitionMap.get(redirectedId);
    if (definition && !results.some((result) => result.id === redirectedId)) {
      results.push({ ...definition, aliases: [...definition.aliases] });
    }
  }
  return results.slice(0, limit);
}

export function sidebarControlCommandLabel(
  id: SidebarControlCommandId,
  language: ComposerLanguage,
): string {
  const definition = definitionMap.get(id);
  if (!definition) {
    return "";
  }
  return definition.primaryLabel[language === "zh-CN" ? "zh-CN" : "en-US"];
}

function command(
  id: SidebarControlCommandId,
  aliases: string[],
  chinese: string,
  english: string,
): SidebarControlCommandDefinition {
  return {
    id,
    aliases,
    primaryLabel: {
      "zh-CN": chinese,
      "en-US": english,
    },
  };
}
