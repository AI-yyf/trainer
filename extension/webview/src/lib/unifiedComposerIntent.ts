import { learnerActionText,learnerInstructionText,requestsLearningPlanChange } from "../../../../shared/src/learnerInstructions";
import { preparationRequested } from "../../../../shared/src/researchBrief";
import type { ActiveWorkbenchView,ResourceComposerIntentMode,ResourceRecord } from "./types";

export type UnifiedComposerIntent =
  | { kind: "continue" | "review" | "verify" | "hint" | "help" | "blocker" }
  | { kind: "practice"; referencesSource?: true }
  | { kind: "resource-search"; query: string }
  | { kind: "resource-turn"; mode: ResourceComposerIntentMode; preparation?: true }
  | { kind: "resource-delete" }
  | { kind: "resource-versions" }
  | { kind: "resource-link"; practiceAfterLink?: true }
  | { kind: "resource-move"; group: string }
  | { kind: "plan" }
  | { kind: "message" };

const COMMANDS = [
  { en: "/continue", zh: "/继续", kind: "continue" },
  { en: "/practice", zh: "/练习", kind: "practice" },
  { en: "/recall", zh: "/复习", kind: "review" },
  { en: "/verify", zh: "/验证", kind: "verify" },
  { en: "/hint", zh: "/提示", kind: "hint" },
  { en: "/search", zh: "/搜索资料", kind: "resource-search" },
  { en: "/versions", zh: "/核对版本", kind: "resource-versions" },
] as const;

const VERSION_CHECK_REQUESTS = [
  /(?:检查|核对|看看|查一下).{0,24}(?:新版本|版本更新|源站版本)/u,
  /\b(?:check|list|look for)\b.{0,48}\b(?:new versions?|versions? available|source versions?)\b/iu,
  /\b(?:comprueba|verifica|revisa|busca)\b.{0,55}\b(?:nuevas? versiones?|versiones? nuevas?|actualizaciones)\b/iu,
  /(?:vérifi(?:e|ez|er)|cherch(?:e|ez|er)).{0,55}(?:nouvelles? versions?|mises? à jour)/iu,
  /(?:prüf(?:e|en)?|überprüf(?:e|en)?|such(?:e|en)?).{0,55}(?:neue[nr]? versionen?|aktualisierungen|updates)/iu,
  /(?:新しい版|新しいバージョン|更新).{0,28}(?:確認|チェック|調べ)/u,
  /(?:새 버전|최신 버전|업데이트).{0,25}(?:확인|검사|찾아)/u,
  /\b(?:verifi(?:ca|car|que)|confir(?:a|me)|procur(?:a|ar|e))\b.{0,55}\b(?:novas? vers(?:ão|ões)|atualizaç(?:ão|ões))\b/iu,
];

const RESOURCE_LINK_REQUEST = /(?:把|将).{0,30}(?:资料|文档|论文|文章|网页|选段|摘录).{0,12}(?:加入|纳入|关联到).{0,8}(?:学习|计划|阶段)|\b(?:add|link|attach)\b.{0,40}\b(?:resources?|papers?|articles?|webpages?|documents?|sources?)\b.{0,24}\b(?:learning|study plan|current stage)\b/iu;
const PRACTICE_REQUEST = /(?:给我|来|出|生成|安排|设计).{0,14}(?:一道题|练习|训练卡)|(?:^|, )(?:(?:please |(?:can|could|would) you ))*(?:give me|create|generate|make|set)\b.{0,45}\b(?:exercise|practice card|training card)\b/iu;
const PRACTICE_SOURCE_REFERENCE = /(?:这|该)(?:篇|份|段|个)?(?:论文|文章|文档|资料|材料|选段|摘录|来源)|\b(?:this|the linked) (?:paper|article|document|resource|source|excerpt|material)\b/iu;
const RESOURCE_ANALYSIS_REQUEST = /比较|对比|总结|提取|解释|分析|\b(?:compare|summari[sz]e|extract|explain|analy[sz]e)\b/iu;
// Outside the Resources view, only treat explicit references to the learner's
// own saved library/papers as resource-library turns. Bare "library" or
// "resources" in code discussions (e.g. "Find a good HTTP library in Go",
// "Explain Python standard library asyncio") must remain normal Chat turns.
const USER_LIBRARY_ANALYSIS_REFERENCE =
  /资料库|资源库|我的资料|已上传的?(?:资料|文档|文件)|\b(?:my|the|this|our|trainer)\s+(?:resource\s+)?library\b|\b(?:saved|uploaded|linked)\s+(?:resources?|papers?|documents?)\b/iu;
const USER_LIBRARY_SEARCH_REFERENCE =
  /资料库|资源库|我的资料|已上传|相关(?:论文|资料|文献|资源)|论文|文献|\b(?:my|the|this|our|trainer)\s+(?:resource\s+)?library\b|\b(?:saved|uploaded|linked)\s+(?:resources?|papers?|documents?)\b|\blibrary\s+(?:papers?|resources?|files?|documents?)\b/iu;
const USER_LIBRARY_TURN_REFERENCE =
  /资料库|资源库|我的资料|这些资料|这几篇|相关论文|\b(?:my|the|this|our|trainer)\s+(?:resource\s+)?library\b|\b(?:saved|uploaded|linked)\s+(?:resources?|papers?|documents?)\b|\blibrary\s+(?:papers?|resources?|files?|documents?|folders?)\b/iu;

export function unifiedComposerCommands(text: string, language: string): string[] {
  const prefix = text.trim().toLowerCase();
  if (!prefix.startsWith("/")) return [];
  return COMMANDS.filter(({ en, zh }) => en.startsWith(prefix) || zh.startsWith(prefix))
    .map(({ en, zh }) => (prefix === "/" ? language === "zh-CN" : zh.startsWith(prefix)) ? zh : en);
}

export function resolveUnifiedComposerIntent(
  text: string,
  view: ActiveWorkbenchView,
  options?: { inlineTrainingActive?: boolean },
): UnifiedComposerIntent {
  const clean = learnerInstructionText(text).trim();
  const token = clean.split(/\s+/, 1)[0]?.toLowerCase();
  const command = COMMANDS.find(({ en, zh }) => token === en || token === zh);
  if (command?.kind === "resource-search") return { kind: "resource-search", query: clean.slice(token.length).trim() };
  if (command && command.kind !== "practice") return { kind: command.kind };
  if (command?.kind === "practice") return practiceIntent(clean);

  const training = view === "training" || options?.inlineTrainingActive === true;
  const sentence = clean.replace(/[。.!！?？]+$/u, "");
  const actionText = learnerActionText(clean);
  const resourceLink = RESOURCE_LINK_REQUEST.exec(actionText);
  if (resourceLink) {
    const afterLink = actionText.slice(resourceLink.index + resourceLink[0].length);
    if (PRACTICE_REQUEST.test(afterLink)) return { kind: "resource-link", practiceAfterLink: true };
  }
  if (!resourceLink && !training && preparationRequested(clean)) {
    return { kind: "resource-turn", mode: "analyze", preparation: true };
  }
  const analysisRequested = RESOURCE_ANALYSIS_REQUEST.test(clean);
  if (!resourceLink && analysisRequested && (view === "resources" || USER_LIBRARY_ANALYSIS_REFERENCE.test(clean))) {
    return { kind: "resource-turn", mode: "analyze" };
  }
  if (/^(?:(?:我)?(?:已经)?(?:在\s*(?:VS\s*Code|IDE)\s*里?)?完成了[，, ]*)?(?:请|帮我|请帮我)?(?:验证|检查)(?:一下)?\s*(?:当前文件|实现|结果|(?:我)?(?:在\s*)?(?:VS\s*Code|IDE)\s*(?:里)?(?:写|改)的代码)?$/iu.test(sentence) ||
    /^(?:i(?:'ve| have) (?:finished|completed it)[, ]+)?(?:please )?(?:verify|check)(?: (?:it|the (?:current file|implementation|result|tests)))?$/iu.test(sentence)) return { kind: "verify" };
  if (!resourceLink && requestsLearningPlanChange(clean)) return { kind: "plan" };
  if (PRACTICE_REQUEST.test(actionText)) return practiceIntent(actionText);
  if (/^(?:请|帮我)?(?:继续|恢复)(?:昨天的|上次的|当前)?(?:学习|训练|练习)?$|^(?:please )?(?:continue|resume)(?: (?:learning|practice|training|yesterday.s lesson))?$/iu.test(sentence)) return { kind: "continue" };
  if (/^(?:请|帮我)?(?:开始|安排|继续|打开)?(?:一次|一下)?(?:复习|回忆练习)$|^(?:please )?(?:start|schedule|open) (?:a |my )?(?:review|recall)(?: session)?$/iu.test(sentence)) return { kind: "review" };
  if (/(?:给我|帮我|来点|一点).{0,8}提示|\b(?:give (?:me )?|need |can i have )(?:a |another |one )?hint\b/iu.test(clean)) return { kind: "hint" };
  if (training && /^(?:(?:我)?(?:卡在|卡住|受阻|遇到阻塞)|(?:i(?:'m| am) )?(?:stuck|blocked)\b)/iu.test(clean)) return { kind: "blocker" };
  if (training && /^(?:(?:请|帮我)?(?:解释|讲解|分析|为什么|怎么|我不理解|我不明白)|(?:please )?(?:explain|why|how|help me understand|analyze)\b)/iu.test(clean)) return { kind: "help" };
  if (resourceLink) return { kind: "resource-link" };

  if (view === "resources") {
    if (/^(?:请|帮我|请帮我)?删除(?:这些|选中|当前|这份)?(?:资料|资源|文件)$|^(?:please )?(?:delete|trash) (?:the |these |this )?(?:selected )?(?:resources?|files?)$/iu.test(sentence)) {
      return { kind: "resource-delete" };
    }
    const move = /^(?:请|帮我|请帮我)?把(?:这些|选中|当前|这份)?(?:资料|资源|文件)(?:移到|移动到|归入|归类到)\s*(.+)$/iu.exec(sentence) ??
      /^(?:please )?move (?:the |these |this )?(?:selected )?(?:resources?|files?) (?:into|to)\s+(.+)$/iu.exec(sentence);
    if (move) return { kind: "resource-move", group: move[1].trim() };
    if (VERSION_CHECK_REQUESTS.some((pattern) => pattern.test(sentence))) {
      return { kind: "resource-versions" };
    }
  }

  const resourceCommand = /^(?:请|帮我|请帮我)?(?:搜索|搜一下|查找|找出|检索)\s*(?:资料库(?:里|中|内)(?:的)?\s*)?(?:所有)?(?:关于)?\s*(.+)$/u.exec(sentence) ??
    /^(?:(?:please|can you) )?(?:search(?: the library)?(?: for)?|find(?: library)?|look up)\s+(.+)$/iu.exec(sentence);
  if (resourceCommand && !analysisRequested && (view === "resources" || USER_LIBRARY_SEARCH_REFERENCE.test(clean))) {
    return { kind: "resource-search", query: resourceCommand[1].replace(/(?:的)?相关(?:论文|资料|文献|资源)$|(?:related )?(?:papers|resources)\s*$/iu, "").trim() || resourceCommand[1].trim() };
  }
  if (view === "resources" || USER_LIBRARY_TURN_REFERENCE.test(clean)) {
    if (/归[入类]|移动|重命名|删除|标签|\b(?:move|rename|delete|tag)\b|(?:整理|organize).{0,24}(?:资料库|目录|文件夹|folders?|library)/iu.test(actionText)) return { kind: "resource-turn", mode: "organize" };
    if (/下载|导入|保存|\b(?:download|import|save|ingest)\b/iu.test(actionText)) return { kind: "resource-turn", mode: "download" };
    if (/闪卡|知识卡|\bflashcards?\b/iu.test(actionText)) return { kind: "resource-turn", mode: "cards" };
    if (view === "resources" && !analysisRequested && /^[\p{L}\p{N} -]{2,48}$/u.test(clean)) return { kind: "resource-search", query: clean };
    if (view === "resources" || actionText.length > 0) return { kind: "resource-turn", mode: "locate" };
  }
  return { kind: "message" };
}

function practiceIntent(text: string): UnifiedComposerIntent {
  return PRACTICE_SOURCE_REFERENCE.test(text) ? { kind: "practice", referencesSource: true } : { kind: "practice" };
}

type LinkedPracticeSource = Pick<ResourceRecord, "id" | "status" | "versionId" | "contentHash">;

export function resolveLinkedPracticeSource(linkedIds: readonly string[], library: readonly LinkedPracticeSource[]) {
  const matches = library.filter((resource) => linkedIds.includes(resource.id));
  const source = matches.length === 1 ? matches[0] : undefined;
  if (source?.status === "ready" && source.versionId && source.contentHash) {
    return { resourceId: source.id, versionId: source.versionId, contentHash: source.contentHash };
  }
  return undefined;
}
