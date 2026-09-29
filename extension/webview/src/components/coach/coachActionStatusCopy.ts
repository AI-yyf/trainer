/** §十五: deprecated conversation-candidate chrome copy in eight languages (no zh/en binary). */

import type { ComposerLanguage } from "../../lib/types";

/**
 * Labels for the deprecated ConversationCandidate / BoundaryNote chrome.
 * The zh-CN source string is the record key.
 */
export const COACH_ACTION_STATUS_TEXT: Record<string, Record<string, string>> = {
  "自动": {
    "en-US": "Auto",
    "es-ES": "Auto",
    "fr-FR": "Auto",
    "de-DE": "Auto",
    "ja-JP": "自動",
    "ko-KR": "자동",
    "pt-BR": "Auto",
  },
  "目标能力": {
    "en-US": "Target skill",
    "es-ES": "Habilidad objetivo",
    "fr-FR": "Compétence cible",
    "de-DE": "Zielfähigkeit",
    "ja-JP": "対象スキル",
    "ko-KR": "목표 역량",
    "pt-BR": "Habilidade-alvo",
  },
  "忽略": {
    "en-US": "Dismiss",
    "es-ES": "Descartar",
    "fr-FR": "Ignorer",
    "de-DE": "Verwerfen",
    "ja-JP": "閉じる",
    "ko-KR": "닫기",
    "pt-BR": "Dispensar",
  },
};

export function coachActionStatusCopy(language: ComposerLanguage, key: string): string {
  return COACH_ACTION_STATUS_TEXT[key]?.[language] ?? key;
}
