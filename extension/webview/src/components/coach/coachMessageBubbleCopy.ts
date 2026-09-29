/** §十五: coach message bubble chrome copy in eight languages (no zh/en binary). */

import type { ComposerLanguage } from "../../lib/types";

/**
 * Chrome copy on a message bubble: the running line, the support-attachment
 * line template, the tool-trail summary, and the quick-actions group label.
 * The zh-CN source string is the record key; {label} / {value} / {n} / {f}
 * are positional slots and the en-US "{s}" slot keeps the historical plural
 * marker (empty for singular counts).
 */
export const COACH_MESSAGE_BUBBLE_TEXT: Record<string, Record<string, string>> = {
  "正在核对上下文…": {
    "en-US": "Checking context…",
    "es-ES": "Comprobando el contexto…",
    "fr-FR": "Vérification du contexte…",
    "de-DE": "Kontext wird geprüft…",
    "ja-JP": "コンテキストを確認しています…",
    "ko-KR": "컨텍스트를 확인하는 중…",
    "pt-BR": "Verificando o contexto…",
  },
  "{label}：{value}": {
    "en-US": "{label}: {value}",
    "es-ES": "{label}: {value}",
    "fr-FR": "{label} : {value}",
    "de-DE": "{label}: {value}",
    "ja-JP": "{label}：{value}",
    "ko-KR": "{label}: {value}",
    "pt-BR": "{label}: {value}",
  },
  "已核对 {n} 项上下文": {
    "en-US": "Checked {n} item{s}",
    "es-ES": "Se comprobaron {n} elementos",
    "fr-FR": "{n} éléments vérifiés",
    "de-DE": "{n} Einträge geprüft",
    "ja-JP": "{n} 項目を確認しました",
    "ko-KR": "{n}개 항목을 확인했습니다",
    "pt-BR": "Foram verificados {n} itens",
  },
  "，其中 {f} 步需要重试": {
    "en-US": ", {f} need{s} a retry",
    "es-ES": ", {f} con necesidad de reintento",
    "fr-FR": ", {f} à retenter",
    "de-DE": ", davon {f} erneut zu versuchen",
    "ja-JP": "、うち {f} ステップは再試行が必要",
    "ko-KR": ", 이 중 {f}단계는 재시도 필요",
    "pt-BR": ", {f} precisando de nova tentativa",
  },
  "这条回复的快捷操作": {
    "en-US": "Quick actions for this reply",
    "es-ES": "Acciones rápidas para esta respuesta",
    "fr-FR": "Actions rapides pour cette réponse",
    "de-DE": "Schnellaktionen für diese Antwort",
    "ja-JP": "この返信のクイック操作",
    "ko-KR": "이 답변의 빠른 작업",
    "pt-BR": "Ações rápidas para esta resposta",
  },
};

export function coachMessageBubbleCopy(language: ComposerLanguage, key: string): string {
  return COACH_MESSAGE_BUBBLE_TEXT[key]?.[language] ?? key;
}
