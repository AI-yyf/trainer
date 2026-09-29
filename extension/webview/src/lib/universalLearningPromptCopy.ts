/**
 * §十五: training feedback prompt fragments in eight locales.
 *
 * These are LLM-facing prompts, which are English-first by design: every
 * non-zh locale resolves to the exact English source string, while the
 * zh-CN string is the record key itself.
 */

import type { ComposerLanguage } from "./types";

export const TRAINING_FEEDBACK_PROMPT_TEXT: Record<string, Record<string, string>> = {
  "作答": {
    "en-US": "answer",
    "es-ES": "answer",
    "fr-FR": "answer",
    "de-DE": "answer",
    "ja-JP": "answer",
    "ko-KR": "answer",
    "pt-BR": "answer",
  },
  "复盘": {
    "en-US": "reflection",
    "es-ES": "reflection",
    "fr-FR": "reflection",
    "de-DE": "reflection",
    "ja-JP": "reflection",
    "ko-KR": "reflection",
    "pt-BR": "reflection",
  },
  "证据记录": {
    "en-US": "evidence note",
    "es-ES": "evidence note",
    "fr-FR": "evidence note",
    "de-DE": "evidence note",
    "ja-JP": "evidence note",
    "ko-KR": "evidence note",
    "pt-BR": "evidence note",
  },
  "我刚提交了本轮训练{phase}。请基于同一训练线程给出可见的教练反馈。": {
    "en-US": "I just submitted a training {phase}. Continue the same learning thread with a visible coaching response.",
    "es-ES": "I just submitted a training {phase}. Continue the same learning thread with a visible coaching response.",
    "fr-FR": "I just submitted a training {phase}. Continue the same learning thread with a visible coaching response.",
    "de-DE": "I just submitted a training {phase}. Continue the same learning thread with a visible coaching response.",
    "ja-JP": "I just submitted a training {phase}. Continue the same learning thread with a visible coaching response.",
    "ko-KR": "I just submitted a training {phase}. Continue the same learning thread with a visible coaching response.",
    "pt-BR": "I just submitted a training {phase}. Continue the same learning thread with a visible coaching response.",
  },
  "训练卡：{title}": {
    "en-US": "Training card: {title}",
    "es-ES": "Training card: {title}",
    "fr-FR": "Training card: {title}",
    "de-DE": "Training card: {title}",
    "ja-JP": "Training card: {title}",
    "ko-KR": "Training card: {title}",
    "pt-BR": "Training card: {title}",
  },
  "题目或任务：{q}": {
    "en-US": "Question or task: {q}",
    "es-ES": "Question or task: {q}",
    "fr-FR": "Question or task: {q}",
    "de-DE": "Question or task: {q}",
    "ja-JP": "Question or task: {q}",
    "ko-KR": "Question or task: {q}",
    "pt-BR": "Question or task: {q}",
  },
  "我的提交：{a}": {
    "en-US": "Learner submission: {a}",
    "es-ES": "Learner submission: {a}",
    "fr-FR": "Learner submission: {a}",
    "de-DE": "Learner submission: {a}",
    "ja-JP": "Learner submission: {a}",
    "ko-KR": "Learner submission: {a}",
    "pt-BR": "Learner submission: {a}",
  },
  "核验线索": {
    "en-US": "Verification signals",
    "es-ES": "Verification signals",
    "fr-FR": "Verification signals",
    "de-DE": "Verification signals",
    "ja-JP": "Verification signals",
    "ko-KR": "Verification signals",
    "pt-BR": "Verification signals",
  },
  "不要静默修改正式计划。说明这次提交证明了什么、仍有哪些不确定性，以及最小的下一步。答案不完整时要如实说明，回复保持足够精炼，便于马上行动。": {
    "en-US": "Do not silently change the formal plan. Explain what the submission proves, what is still uncertain, and the smallest next action. Be honest when the answer is incomplete; keep the response concise enough to act on.",
    "es-ES": "Do not silently change the formal plan. Explain what the submission proves, what is still uncertain, and the smallest next action. Be honest when the answer is incomplete; keep the response concise enough to act on.",
    "fr-FR": "Do not silently change the formal plan. Explain what the submission proves, what is still uncertain, and the smallest next action. Be honest when the answer is incomplete; keep the response concise enough to act on.",
    "de-DE": "Do not silently change the formal plan. Explain what the submission proves, what is still uncertain, and the smallest next action. Be honest when the answer is incomplete; keep the response concise enough to act on.",
    "ja-JP": "Do not silently change the formal plan. Explain what the submission proves, what is still uncertain, and the smallest next action. Be honest when the answer is incomplete; keep the response concise enough to act on.",
    "ko-KR": "Do not silently change the formal plan. Explain what the submission proves, what is still uncertain, and the smallest next action. Be honest when the answer is incomplete; keep the response concise enough to act on.",
    "pt-BR": "Do not silently change the formal plan. Explain what the submission proves, what is still uncertain, and the smallest next action. Be honest when the answer is incomplete; keep the response concise enough to act on.",
  },
};

export function trainingFeedbackPromptCopy(language: ComposerLanguage, key: string): string {
  return TRAINING_FEEDBACK_PROMPT_TEXT[key]?.[language] ?? key;
}
