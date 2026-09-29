/** §十五: agent activity strip sentences in eight languages (no zh/en binary). */

import type { ComposerLanguage } from "../../lib/types";

/**
 * Sentence templates shared by the agent activity strip. The zh-CN source
 * string is the record key; {label} / {n} / {reason} are positional slots.
 */
export const AGENT_ACTIVITY_STRIP_TEXT: Record<string, Record<string, string>> = {
  "正在核对上下文，同时有一步需要重试": {
    "en-US": "Checking context while one step needs another try",
    "es-ES": "Comprobando el contexto mientras un paso necesita reintentarse",
    "fr-FR": "Vérification du contexte pendant qu'une étape doit être réessayée",
    "de-DE": "Kontext wird geprüft, während ein Schritt erneut versucht werden muss",
    "ja-JP": "コンテキストを確認しています。1 つのステップの再試行が必要です",
    "ko-KR": "컨텍스트를 확인하는 중입니다. 한 단계를 다시 시도해야 합니다",
    "pt-BR": "Verificando o contexto enquanto uma etapa precisa de nova tentativa",
  },
  "正在{label}": {
    "en-US": "Trainer is {label}",
    "es-ES": "{label} en curso",
    "fr-FR": "{label} en cours",
    "de-DE": "{label} läuft",
    "ja-JP": "{label}を実行中",
    "ko-KR": "{label} 진행 중",
    "pt-BR": "{label} em andamento",
  },
  "正在核对 {n} 项上下文": {
    "en-US": "Trainer is checking {n} things",
    "es-ES": "El entrenador está comprobando {n} elementos",
    "fr-FR": "Le formateur vérifie {n} éléments",
    "de-DE": "Der Trainer prüft {n} Dinge",
    "ja-JP": "Trainer が {n} 項目を確認しています",
    "ko-KR": "Trainer가 {n}가지를 확인하는 중입니다",
    "pt-BR": "O treinador está verificando {n} coisas",
  },
  "已完成 {n} 个步骤，正在整理回复": {
    "en-US": "Trainer checked {n} items and is shaping the reply",
    "es-ES": "El entrenador revisó {n} elementos y está preparando la respuesta",
    "fr-FR": "Le formateur a vérifié {n} éléments et prépare la réponse",
    "de-DE": "Der Trainer hat {n} Einträge geprüft und formuliert die Antwort",
    "ja-JP": "Trainer は {n} 項目を確認し、回答をまとめています",
    "ko-KR": "Trainer가 {n}개 항목을 확인하고 답변을 정리하는 중입니다",
    "pt-BR": "O treinador verificou {n} itens e está preparando a resposta",
  },
  "已完成：{label}": {
    "en-US": "Trainer has the key context from {label}",
    "es-ES": "El entrenador ya tiene el contexto clave de {label}",
    "fr-FR": "Le formateur a le contexte clé de {label}",
    "de-DE": "Der Trainer hat den wichtigsten Kontext aus {label}",
    "ja-JP": "Trainer は {label} から主要なコンテキストを取得しました",
    "ko-KR": "Trainer가 {label}에서 핵심 컨텍스트를 확보했습니다",
    "pt-BR": "O treinador tem o contexto principal de {label}",
  },
  "正在准备回复": {
    "en-US": "Trainer is preparing a reply",
    "es-ES": "El entrenador está preparando una respuesta",
    "fr-FR": "Le formateur prépare une réponse",
    "de-DE": "Der Trainer bereitet eine Antwort vor",
    "ja-JP": "Trainer が回答を準備しています",
    "ko-KR": "Trainer가 답변을 준비하는 중입니다",
    "pt-BR": "O treinador está preparando uma resposta",
  },
  "结束原因：{reason}": {
    "en-US": "Stopped: {reason}",
    "es-ES": "Detenido: {reason}",
    "fr-FR": "Arrêté : {reason}",
    "de-DE": "Gestoppt: {reason}",
    "ja-JP": "終了理由: {reason}",
    "ko-KR": "종료 이유: {reason}",
    "pt-BR": "Interrompido: {reason}",
  },
  "正在核对上下文...": {
    "en-US": "Checking context...",
    "es-ES": "Comprobando el contexto...",
    "fr-FR": "Vérification du contexte...",
    "de-DE": "Kontext wird geprüft...",
    "ja-JP": "コンテキストを確認しています...",
    "ko-KR": "컨텍스트를 확인하는 중...",
    "pt-BR": "Verificando o contexto...",
  },
  "第 {n} 步": {
    "en-US": "Step {n}",
    "es-ES": "Paso {n}",
    "fr-FR": "Étape {n}",
    "de-DE": "Schritt {n}",
    "ja-JP": "ステップ {n}",
    "ko-KR": "{n}단계",
    "pt-BR": "Passo {n}",
  },
};

export function agentActivityStripCopy(language: ComposerLanguage, key: string): string {
  return AGENT_ACTIVITY_STRIP_TEXT[key]?.[language] ?? key;
}
