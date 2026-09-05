import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';

export type CoachScenario =
  | 'remoteBoundary'
  | 'debugLoop'
  | 'functionContract'
  | 'conceptMastery'
  | 'vocabularyRecall'
  | 'mathDerivation'
  | 'writingRevision'
  | 'readingTransfer';

const coachScenarioPrompts: Record<CoachScenario, { en: string; zh: string }> = {
  remoteBoundary: {
    en:
      'Coach me through the current VS Code workspace boundary: first identify local, SSH, Tunnels, Dev Container, or WSL; then confirm file ownership, one real path or URI fact, and whether the API key should stay local or remote. Explain before asking me to verify anything. Do not change the formal plan.',
    zh:
      '请带我确认当前 VS Code 工作区边界：先判断本地、SSH、Tunnels、Dev Container 或 WSL；再确认文件归属、一个真实路径或 URI 事实，以及 API key 应留在本机还是远端。先讲解，再让我做最小验证；不要修改正式计划。',
  },
  debugLoop: {
    en:
      'Coach me through the smallest trustworthy debug loop for the current problem: reproduce it once, choose one pause point, and observe one bad state. Explain the evidence before suggesting a change. Do not guess a fix or change the formal plan.',
    zh:
      '请带我用最小可信 debug loop 检查当前问题：先复现一次，确定一个暂停点，再观察一个异常状态。先解释证据，再建议修改；不要猜测修复，也不要修改正式计划。',
  },
  functionContract: {
    en:
      'Coach me through recovering the current function contract with VS Code guidance: use hover, signature help, go to definition, and one real call site. Explain what each source proves before asking for one safe next edit. Do not change the formal plan.',
    zh:
      '请带我用 VS Code 的函数提示恢复当前函数契约：依次看 hover、signature help、go to definition 和一个真实 call site。先解释每条证据能证明什么，再让我给出一个安全的下一步修改；不要修改正式计划。',
  },
  conceptMastery: {
    en:
      'Teach this concept with a Learn -> Try -> Verify -> Reflect loop: begin with the smallest accurate explanation, contrast one nearby concept, and show one example or boundary. Only then ask me to explain it back and verify the gaps. Do not turn the conversation into a formal plan without my confirmation.',
    zh:
      '请带我用 Learn -> Try -> Verify -> Reflect 学透这个概念：先给最小且准确的解释，再对比一个相近概念，并给一个例子或边界。之后再让我复述并核验缺口。未经我确认，不要把对话变成正式计划。',
  },
  vocabularyRecall: {
    en:
      'Coach one vocabulary, term, or fact through Learn -> Recall -> Verify -> Reflect: teach its meaning and one grounded use first, then ask for retrieval, verify the answer shape, and name the next review. Do not start with a blind quiz or change the formal plan.',
    zh:
      '请带我把一个单词、术语或事实走完 Learn -> Recall -> Verify -> Reflect：先讲含义和一个真实用法，再让我回忆，核验答案结构，并说明下一次回看。不要一上来盲测，也不要修改正式计划。',
  },
  mathDerivation: {
    en:
      'Coach one mathematics or physics derivation through Learn -> Try -> Verify -> Reflect: state the target and assumptions, derive one justified step at a time, then let me reproduce the key steps on paper or in text. Verify each inference and make uncertainty explicit. Do not begin with a final-answer test or change the formal plan.',
    zh:
      '请带我把一个数学或物理推导走完 Learn -> Try -> Verify -> Reflect：先说明目标和假设，再逐步推导并解释每一步依据，然后让我在纸上或文本中复现关键步骤。逐项核验推理并明确不确定处。不要先考最终答案，也不要修改正式计划。',
  },
  writingRevision: {
    en:
      'Coach my writing with Learn -> Draft -> Verify -> Reflect: first identify audience, purpose, and constraints; show the smallest revision principle with an example; then let me revise it. Verify the revision against a short checklist and explain the next improvement. Do not rewrite everything for me or change the formal plan.',
    zh:
      '请带我用 Learn -> Draft -> Verify -> Reflect 修改写作：先判断读者、目的和约束；用一个例子讲清最小修改原则；再让我自己改写。按简短清单核验修改，并说明下一步提升。不要替我把全文重写，也不要修改正式计划。',
  },
  readingTransfer: {
    en:
      'Coach this reading through Learn -> Try -> Verify -> Reflect: identify the main claim, evidence, and structure first; then ask me to restate or transfer one idea to a new context. Verify against the source rather than impression, and name the smallest next reading action. Do not change the formal plan.',
    zh:
      '请带我用 Learn -> Try -> Verify -> Reflect 完成这次阅读：先找出主张、证据和结构；再让我复述或把一个观点迁移到新情境。依据原文而不是印象核验，并说明最小的下一步阅读动作。不要修改正式计划。',
  },
};

const coachScenarioMessages: Record<CoachScenario, { en: string; zh: string }> = {
  remoteBoundary: {
    en: 'Remote workspace guidance is ready in Coach.',
    zh: '已在 Coach 中准备远程工作区引导。',
  },
  debugLoop: {
    en: 'Debug-loop guidance is ready in Coach.',
    zh: '已在 Coach 中准备最小 debug loop 引导。',
  },
  functionContract: {
    en: 'Function-contract guidance is ready in Coach.',
    zh: '已在 Coach 中准备函数契约引导。',
  },
  conceptMastery: {
    en: 'Concept coaching is ready in Coach.',
    zh: '已在 Coach 中准备概念学习引导。',
  },
  vocabularyRecall: {
    en: 'Recall coaching is ready in Coach.',
    zh: '已在 Coach 中准备背诵与回忆引导。',
  },
  mathDerivation: {
    en: 'Derivation coaching is ready in Coach.',
    zh: '已在 Coach 中准备推导学习引导。',
  },
  writingRevision: {
    en: 'Writing coaching is ready in Coach.',
    zh: '已在 Coach 中准备写作修订引导。',
  },
  readingTransfer: {
    en: 'Reading coaching is ready in Coach.',
    zh: '已在 Coach 中准备阅读迁移引导。',
  },
};

export async function openCoachScenarioCommand(
  context: CommandContext,
  scenario: CoachScenario,
): Promise<CommandExecutionResult> {
  const responseLanguage = context.getHostState().bootstrap.memory.workspace?.responseLanguage;
  const localized = responseLanguage === 'zh-CN' ? 'zh' : 'en';

  await context.workbench.show();
  await context.workbench.syncState();
  await context.workbench.postMessage({
    type: 'ui/coachPrompt',
    payload: {
      draft: coachScenarioPrompts[scenario][localized],
      source: 'commandPalette',
    },
  });

  return {
    ok: true,
    message: coachScenarioMessages[scenario][localized],
  };
}
