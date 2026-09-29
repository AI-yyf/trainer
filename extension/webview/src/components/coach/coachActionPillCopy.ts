/** §十五: coach action pill status labels in eight languages (no zh/en binary). */

import type { ComposerLanguage } from "../../lib/types";

export const COACH_ACTION_PILL_TEXT: Record<string, Record<string, string>> = {
  "完成": {
    "en-US": "Done",
    "es-ES": "Hecho",
    "fr-FR": "Terminé",
    "de-DE": "Fertig",
    "ja-JP": "完了",
    "ko-KR": "완료",
    "pt-BR": "Concluído",
  },
  "失败": {
    "en-US": "Failed",
    "es-ES": "Error",
    "fr-FR": "Échec",
    "de-DE": "Fehlgeschlagen",
    "ja-JP": "失敗",
    "ko-KR": "실패",
    "pt-BR": "Falhou",
  },
};

export function coachActionPillCopy(language: ComposerLanguage, key: string): string {
  return COACH_ACTION_PILL_TEXT[key]?.[language] ?? key;
}
