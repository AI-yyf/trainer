/** §十五: coach session recap copy in eight languages (no zh/en binary). */

import type { ComposerLanguage } from "../../lib/types";

/**
 * Turn-recap tone chips, fact labels, and title. The zh-CN source string is
 * the record key.
 */
export const COACH_SESSION_RECAP_TEXT: Record<string, Record<string, string>> = {
  "受阻": {
    "en-US": "Blocked",
    "es-ES": "Bloqueado",
    "fr-FR": "Bloqué",
    "de-DE": "Blockiert",
    "ja-JP": "ブロック",
    "ko-KR": "막힘",
    "pt-BR": "Bloqueado",
  },
  "进行中": {
    "en-US": "Working",
    "es-ES": "En curso",
    "fr-FR": "En cours",
    "de-DE": "Läuft",
    "ja-JP": "実行中",
    "ko-KR": "진행 중",
    "pt-BR": "Em andamento",
  },
  "已收口": {
    "en-US": "Done",
    "es-ES": "Listo",
    "fr-FR": "Terminé",
    "de-DE": "Fertig",
    "ja-JP": "完了",
    "ko-KR": "완료",
    "pt-BR": "Concluído",
  },
  "等待": {
    "en-US": "Waiting",
    "es-ES": "Esperando",
    "fr-FR": "En attente",
    "de-DE": "Warten",
    "ja-JP": "待機中",
    "ko-KR": "대기 중",
    "pt-BR": "Aguardando",
  },
  "决策": {
    "en-US": "Decision",
    "es-ES": "Decisión",
    "fr-FR": "Décision",
    "de-DE": "Entscheidung",
    "ja-JP": "決定",
    "ko-KR": "결정",
    "pt-BR": "Decisão",
  },
  "卡点": {
    "en-US": "Blocker",
    "es-ES": "Bloqueo",
    "fr-FR": "Blocage",
    "de-DE": "Blocker",
    "ja-JP": "つまずき",
    "ko-KR": "막힌 지점",
    "pt-BR": "Bloqueio",
  },
  "下一步": {
    "en-US": "Next step",
    "es-ES": "Siguiente paso",
    "fr-FR": "Prochaine étape",
    "de-DE": "Nächster Schritt",
    "ja-JP": "次のステップ",
    "ko-KR": "다음 단계",
    "pt-BR": "Próximo passo",
  },
  "续接": {
    "en-US": "Resume",
    "es-ES": "Retomar",
    "fr-FR": "Reprendre",
    "de-DE": "Fortsetzen",
    "ja-JP": "再開",
    "ko-KR": "이어서",
    "pt-BR": "Retomar",
  },
  "本次总结": {
    "en-US": "Session summary",
    "es-ES": "Resumen de sesión",
    "fr-FR": "Résumé de session",
    "de-DE": "Sitzungszusammenfassung",
    "ja-JP": "今回のまとめ",
    "ko-KR": "이번 요약",
    "pt-BR": "Resumo da sessão",
  },
};

export function coachSessionRecapCopy(language: ComposerLanguage, key: string): string {
  return COACH_SESSION_RECAP_TEXT[key]?.[language] ?? key;
}
