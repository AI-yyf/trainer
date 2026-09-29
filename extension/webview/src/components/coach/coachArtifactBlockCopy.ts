/** §十五: coach artifact block copy in eight languages (no zh/en binary). */

import type { ComposerLanguage } from "../../lib/types";

/**
 * Labels and sentences on artifact cards. The zh-CN source string is the
 * record key; {action} / {items} / {area} are positional slots and the
 * en-US "{s}" slot keeps the historical plural marker (empty for singular
 * counts). "原理" appears in both records on purpose: as an inline lead it
 * reads "The principle here is", as a kind chip it reads "Principle".
 */
export const ARTIFACT_BLOCK_TEXT: Record<string, Record<string, string>> = {
  // Recommended-action button labels
  "打开计划": {
    "en-US": "Open plan",
    "es-ES": "Abrir plan",
    "fr-FR": "Ouvrir le plan",
    "de-DE": "Plan öffnen",
    "ja-JP": "プランを開く",
    "ko-KR": "계획 열기",
    "pt-BR": "Abrir plano",
  },
  "给我下一题": {
    "en-US": "Next task",
    "es-ES": "Dame la siguiente tarea",
    "fr-FR": "Donne-moi la prochaine tâche",
    "de-DE": "Nächste Aufgabe",
    "ja-JP": "次のタスクを",
    "ko-KR": "다음 과제 주세요",
    "pt-BR": "Próxima tarefa",
  },
  "开始检查": {
    "en-US": "Run review",
    "es-ES": "Iniciar revisión",
    "fr-FR": "Lancer la révision",
    "de-DE": "Prüfung starten",
    "ja-JP": "チェックを開始",
    "ko-KR": "검사 시작",
    "pt-BR": "Iniciar revisão",
  },
  "给我更小提示": {
    "en-US": "Smaller hint",
    "es-ES": "Pista más pequeña",
    "fr-FR": "Indice plus petit",
    "de-DE": "Kleinerer Tipp",
    "ja-JP": "もっと小さいヒント",
    "ko-KR": "더 작은 힌트",
    "pt-BR": "Dica menor",
  },
  "再次检查": {
    "en-US": "Review again",
    "es-ES": "Revisar de nuevo",
    "fr-FR": "Réviser à nouveau",
    "de-DE": "Erneut prüfen",
    "ja-JP": "もう一度チェック",
    "ko-KR": "다시 검사",
    "pt-BR": "Revisar novamente",
  },
  "设为练习": {
    "en-US": "Turn into practice",
    "es-ES": "Convertir en práctica",
    "fr-FR": "Transformer en pratique",
    "de-DE": "In Übung umwandeln",
    "ja-JP": "練習に変える",
    "ko-KR": "연습으로 만들기",
    "pt-BR": "Transformar em prática",
  },

  // Detail meta labels
  "重点": {
    "en-US": "Focus",
    "es-ES": "Enfoque",
    "fr-FR": "Point clé",
    "de-DE": "Fokus",
    "ja-JP": "フォーカス",
    "ko-KR": "중점",
    "pt-BR": "Foco",
  },
  "原因": {
    "en-US": "Why",
    "es-ES": "Motivo",
    "fr-FR": "Raison",
    "de-DE": "Grund",
    "ja-JP": "理由",
    "ko-KR": "이유",
    "pt-BR": "Motivo",
  },
  "验证": {
    "en-US": "Check",
    "es-ES": "Verificar",
    "fr-FR": "Vérifier",
    "de-DE": "Prüfen",
    "ja-JP": "検証",
    "ko-KR": "검증",
    "pt-BR": "Verificar",
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
  "续接": {
    "en-US": "Resume",
    "es-ES": "Retomar",
    "fr-FR": "Reprendre",
    "de-DE": "Fortsetzen",
    "ja-JP": "再開",
    "ko-KR": "이어서",
    "pt-BR": "Retomar",
  },
  "教学提示": {
    "en-US": "Teaching note",
    "es-ES": "Nota didáctica",
    "fr-FR": "Note pédagogique",
    "de-DE": "Didaktischer Hinweis",
    "ja-JP": "教えるポイント",
    "ko-KR": "학습 팁",
    "pt-BR": "Nota de ensino",
  },
  "把握": {
    "en-US": "Confidence",
    "es-ES": "Confianza",
    "fr-FR": "Confiance",
    "de-DE": "Sicherheit",
    "ja-JP": "確度",
    "ko-KR": "확신도",
    "pt-BR": "Confiança",
  },
  "证据": {
    "en-US": "Evidence",
    "es-ES": "Evidencia",
    "fr-FR": "Preuve",
    "de-DE": "Beleg",
    "ja-JP": "根拠",
    "ko-KR": "근거",
    "pt-BR": "Evidência",
  },

  // Detail body sentence templates
  "下一步：{action}。": {
    "en-US": "Next: {action}.",
    "es-ES": "Siguiente: {action}.",
    "fr-FR": "Suivant : {action}.",
    "de-DE": "Weiter: {action}.",
    "ja-JP": "次：{action}。",
    "ko-KR": "다음: {action}.",
    "pt-BR": "Próximo: {action}.",
  },
  "下一步：{action}": {
    "en-US": "Next: {action}",
    "es-ES": "Siguiente: {action}",
    "fr-FR": "Suivant : {action}",
    "de-DE": "Weiter: {action}",
    "ja-JP": "次：{action}",
    "ko-KR": "다음: {action}",
    "pt-BR": "Próximo: {action}",
  },
  "判断依据": {
    "en-US": "Why",
    "es-ES": "Por qué",
    "fr-FR": "Pourquoi",
    "de-DE": "Warum",
    "ja-JP": "根拠",
    "ko-KR": "근거",
    "pt-BR": "Porquê",
  },
  "补充说明": {
    "en-US": "Note",
    "es-ES": "Nota",
    "fr-FR": "Note",
    "de-DE": "Hinweis",
    "ja-JP": "補足",
    "ko-KR": "참고",
    "pt-BR": "Observação",
  },
  "做完先看 {items}。": {
    "en-US": "Check this first after: {items}.",
    "es-ES": "Después revisa primero: {items}.",
    "fr-FR": "Ensuite, vérifie d'abord : {items}.",
    "de-DE": "Prüfe danach zuerst: {items}.",
    "ja-JP": "終わったらまず {items} を確認。",
    "ko-KR": "끝난 후 먼저 확인: {items}.",
    "pt-BR": "Depois, verifique primeiro: {items}.",
  },
  "先盯住 {area}": {
    "en-US": "Stay with {area}",
    "es-ES": "Concéntrate en {area}",
    "fr-FR": "Reste sur {area}",
    "de-DE": "Bleib bei {area}",
    "ja-JP": "まず {area} に集中",
    "ko-KR": "{area}에 집중",
    "pt-BR": "Foque em {area}",
  },

  // Kind chip labels
  "练习题": {
    "en-US": "Practice",
    "es-ES": "Práctica",
    "fr-FR": "Pratique",
    "de-DE": "Übung",
    "ja-JP": "練習",
    "ko-KR": "연습",
    "pt-BR": "Prática",
  },
  "检查": {
    "en-US": "Check",
    "es-ES": "Comprobación",
    "fr-FR": "Vérification",
    "de-DE": "Prüfung",
    "ja-JP": "チェック",
    "ko-KR": "검사",
    "pt-BR": "Verificação",
  },
  "实现": {
    "en-US": "Implementation",
    "es-ES": "Implementación",
    "fr-FR": "Implémentation",
    "de-DE": "Umsetzung",
    "ja-JP": "実装",
    "ko-KR": "구현",
    "pt-BR": "Implementação",
  },
  "练习想法": {
    "en-US": "Idea",
    "es-ES": "Idea",
    "fr-FR": "Idée",
    "de-DE": "Idee",
    "ja-JP": "アイデア",
    "ko-KR": "아이디어",
    "pt-BR": "Ideia",
  },
  "改造": {
    "en-US": "Adaptation",
    "es-ES": "Adaptación",
    "fr-FR": "Adaptation",
    "de-DE": "Anpassung",
    "ja-JP": "改造",
    "ko-KR": "변형",
    "pt-BR": "Adaptação",
  },
  "来源": {
    "en-US": "Source",
    "es-ES": "Fuente",
    "fr-FR": "Source",
    "de-DE": "Quelle",
    "ja-JP": "ソース",
    "ko-KR": "출처",
    "pt-BR": "Fonte",
  },
  "回看": {
    "en-US": "Review",
    "es-ES": "Revisión",
    "fr-FR": "Révision",
    "de-DE": "Überprüfung",
    "ja-JP": "振り返り",
    "ko-KR": "돌아보기",
    "pt-BR": "Revisão",
  },
  "计划": {
    "en-US": "Plan",
    "es-ES": "Plan",
    "fr-FR": "Plan",
    "de-DE": "Plan",
    "ja-JP": "プラン",
    "ko-KR": "계획",
    "pt-BR": "Plano",
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

  // Label/value punctuation separator (fullwidth colon in zh-CN)
  "：": {
    "en-US": ": ",
    "es-ES": ": ",
    "fr-FR": " : ",
    "de-DE": ": ",
    "ja-JP": "：",
    "ko-KR": ": ",
    "pt-BR": ": ",
  },
  // List join separator between verification items
  "；": {
    "en-US": "; ",
    "es-ES": "; ",
    "fr-FR": " ; ",
    "de-DE": "; ",
    "ja-JP": "；",
    "ko-KR": "; ",
    "pt-BR": "; ",
  },
};

/** Inline lead above an artifact card ("原理" doubles as a kind chip elsewhere). */
export const ARTIFACT_INLINE_LEAD_TEXT: Record<string, Record<string, string>> = {
  "原理": {
    "en-US": "The principle here is",
    "es-ES": "El principio aquí es",
    "fr-FR": "Le principe ici est",
    "de-DE": "Das Prinzip hier ist",
    "ja-JP": "ここでのポイントは",
    "ko-KR": "여기서의 원리는",
    "pt-BR": "O princípio aqui é",
  },
  "先看这个判断点": {
    "en-US": "Check this first",
    "es-ES": "Primero revisa esto",
    "fr-FR": "Vérifie d'abord ceci",
    "de-DE": "Prüfe zuerst dies",
    "ja-JP": "まずこの判断ポイントを確認",
    "ko-KR": "먼저 이 판단점을 확인",
    "pt-BR": "Verifique primeiro este ponto",
  },
};

export function artifactBlockCopy(language: ComposerLanguage, key: string): string {
  return ARTIFACT_BLOCK_TEXT[key]?.[language] ?? key;
}

export function artifactInlineLeadCopy(language: ComposerLanguage, key: string): string {
  return ARTIFACT_INLINE_LEAD_TEXT[key]?.[language] ?? key;
}
