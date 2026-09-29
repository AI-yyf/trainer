/** §十五: quick-action labels in eight languages (no zh/en binary). */

import type { ComposerLanguage } from "../../lib/types";

export const QUICK_ACTIONS_TEXT: Record<string, Record<string, string>> = {
  "设置": {
    "en-US": "Settings",
    "es-ES": "Ajustes",
    "fr-FR": "Paramètres",
    "de-DE": "Einstellungen",
    "ja-JP": "設定",
    "ko-KR": "설정",
    "pt-BR": "Configurações",
  },
  "开始对话": {
    "en-US": "Chat",
    "es-ES": "Conversar",
    "fr-FR": "Discuter",
    "de-DE": "Chat starten",
    "ja-JP": "会話を始める",
    "ko-KR": "대화 시작",
    "pt-BR": "Conversar",
  },
  "查看计划": {
    "en-US": "Plan",
    "es-ES": "Ver plan",
    "fr-FR": "Voir le plan",
    "de-DE": "Plan ansehen",
    "ja-JP": "プランを見る",
    "ko-KR": "계획 보기",
    "pt-BR": "Ver plano",
  },
  "生成训练": {
    "en-US": "Train",
    "es-ES": "Entrenar",
    "fr-FR": "S'entraîner",
    "de-DE": "Trainieren",
    "ja-JP": "トレーニング",
    "ko-KR": "훈련",
    "pt-BR": "Treinar",
  },
  "资料库": {
    "en-US": "Resources",
    "es-ES": "Recursos",
    "fr-FR": "Ressources",
    "de-DE": "Ressourcen",
    "ja-JP": "資料",
    "ko-KR": "자료",
    "pt-BR": "Recursos",
  },
  "搜索资料...": {
    "en-US": "Search resources...",
    "es-ES": "Buscar recursos...",
    "fr-FR": "Rechercher des ressources...",
    "de-DE": "Ressourcen durchsuchen...",
    "ja-JP": "資料を検索...",
    "ko-KR": "자료 검색...",
    "pt-BR": "Buscar recursos...",
  },
  "清除搜索": {
    "en-US": "Clear search",
    "es-ES": "Limpiar búsqueda",
    "fr-FR": "Effacer la recherche",
    "de-DE": "Suche löschen",
    "ja-JP": "検索をクリア",
    "ko-KR": "검색 지우기",
    "pt-BR": "Limpar busca",
  },
};

export function quickActionsCopy(language: ComposerLanguage, key: string): string {
  return QUICK_ACTIONS_TEXT[key]?.[language] ?? key;
}
