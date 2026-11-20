/** §十五: coach message bubble chrome copy in eight languages (no zh/en binary). */

import type { ComposerLanguage } from "../../types";
import type { CoachMessageAction } from "../../../components/coach/CoachMessageBubble";

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
  "这一轮没有返回可显示的回复。可以重试或换一种问法。": {
    "en-US": "This turn returned no visible reply. Retry or rephrase the question.",
    "es-ES": "Este turno no devolvió una respuesta visible. Reintenta o reformula la pregunta.",
    "fr-FR": "Ce tour n’a renvoyé aucune réponse visible. Réessayez ou reformulez la question.",
    "de-DE": "Dieser Zug hat keine sichtbare Antwort geliefert. Versuche es erneut oder formuliere die Frage anders.",
    "ja-JP": "このターンは表示できる回答を返しませんでした。再試行するか、質問を言い換えてください。",
    "ko-KR": "이번 턴에는 표시할 수 있는 답변이 없습니다. 다시 시도하거나 질문을 바꿔 주세요.",
    "pt-BR": "Este turno não retornou uma resposta visível. Tente novamente ou reformule a pergunta.",
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

export const RESEARCH_PREPARATION_TEXT = {
  "zh-CN": { saved: "备课简报已存入资料库。", needs_sources: "添加已建立索引的资料后即可备课。", needs_context: "请在学习项目中保存备课简报。", unavailable: "简报暂未保存，可重试或补充资料。" },
  "en-US": { saved: "Research brief saved in Resources.", needs_sources: "Attach indexed sources to prepare a brief.", needs_context: "Open a learning project to save the brief.", unavailable: "The brief could not be saved. Retry or add sources." },
  "es-ES": { saved: "Informe guardado en Recursos.", needs_sources: "Adjunta fuentes indexadas para preparar el informe.", needs_context: "Abre un proyecto de aprendizaje para guardar el informe.", unavailable: "No se pudo guardar el informe. Reintenta o añade fuentes." },
  "fr-FR": { saved: "Note de recherche enregistrée dans Ressources.", needs_sources: "Joignez des sources indexées pour préparer la note.", needs_context: "Ouvrez un projet d’apprentissage pour enregistrer la note.", unavailable: "La note n’a pas pu être enregistrée. Réessayez ou ajoutez des sources." },
  "de-DE": { saved: "Recherchebericht in Ressourcen gespeichert.", needs_sources: "Füge indexierte Quellen für den Bericht hinzu.", needs_context: "Öffne ein Lernprojekt, um den Bericht zu speichern.", unavailable: "Der Bericht konnte nicht gespeichert werden. Versuche es erneut oder füge Quellen hinzu." },
  "ja-JP": { saved: "調査メモを資料に保存しました。", needs_sources: "調査メモを作成するには、索引済みの資料を添付してください。", needs_context: "学習プロジェクトを開いて調査メモを保存してください。", unavailable: "調査メモを保存できませんでした。再試行するか、資料を追加してください。" },
  "ko-KR": { saved: "연구 브리프를 자료에 저장했습니다.", needs_sources: "브리프를 준비하려면 색인된 자료를 첨부하세요.", needs_context: "학습 프로젝트를 열어 브리프를 저장하세요.", unavailable: "브리프를 저장하지 못했습니다. 다시 시도하거나 자료를 추가하세요." },
  "pt-BR": { saved: "Relatório salvo em Recursos.", needs_sources: "Anexe fontes indexadas para preparar o relatório.", needs_context: "Abra um projeto de aprendizagem para salvar o relatório.", unavailable: "Não foi possível salvar o relatório. Tente novamente ou adicione fontes." },
} satisfies Record<ComposerLanguage, Record<"saved" | "needs_sources" | "needs_context" | "unavailable", string>>;

export const OPEN_RESEARCH_PREPARATION_TEXT = {
  "zh-CN": "查看已保存的备课简报",
  "en-US": "Open saved research brief",
  "es-ES": "Abrir el informe guardado",
  "fr-FR": "Ouvrir la note enregistrée",
  "de-DE": "Gespeicherten Bericht öffnen",
  "ja-JP": "保存済みの調査メモを開く",
  "ko-KR": "저장한 연구 브리프 열기",
  "pt-BR": "Abrir relatório salvo",
} satisfies Record<ComposerLanguage, string>;

export const MORE_ACTIONS_TEXT: Record<ComposerLanguage, string> = {
  "zh-CN": "更多操作",
  "en-US": "More actions",
  "es-ES": "Más acciones",
  "fr-FR": "Plus d’actions",
  "de-DE": "Weitere Aktionen",
  "ja-JP": "その他の操作",
  "ko-KR": "추가 작업",
  "pt-BR": "Mais ações",
};

/**
 * The five quick-action icon labels stay a single source of truth: the bubble
 * uses them for `aria-label` and for the `data-action-label` attribute that the
 * CSS hover/focus label renders (`.message-bubble__icon-action::after`) — no
 * native title tooltip, and no second label dictionary.
 */
export const COACH_MESSAGE_ACTION_LABELS: Record<
  ComposerLanguage,
  Record<Exclude<CoachMessageAction, "open-research-brief">, string>
> = {
  "zh-CN": { copy: "复制", share: "分享", "save-resource": "加入资料库", "save-research-brief": "保存备课简报", "flash-card": "生成闪记卡", "training-card": "生成训练卡候选", "set-goal": "设为目标", retry: "重新生成" },
  "en-US": { copy: "Copy", share: "Share", "save-resource": "Save to Resources", "save-research-brief": "Save prep brief", "flash-card": "Draft a flash card", "training-card": "Draft a training card", "set-goal": "Set as goal", retry: "Regenerate" },
  "es-ES": { copy: "Copiar", share: "Compartir", "save-resource": "Guardar en Recursos", "save-research-brief": "Guardar preparación", "flash-card": "Proponer una tarjeta flash", "training-card": "Proponer una tarjeta", "set-goal": "Establecer como objetivo", retry: "Regenerar" },
  "fr-FR": { copy: "Copier", share: "Partager", "save-resource": "Ajouter aux Ressources", "save-research-brief": "Enregistrer la préparation", "flash-card": "Proposer une carte flash", "training-card": "Proposer une carte", "set-goal": "Définir comme objectif", retry: "Régénérer" },
  "de-DE": { copy: "Kopieren", share: "Teilen", "save-resource": "In Bibliothek speichern", "save-research-brief": "Vorbereitung speichern", "flash-card": "Lernkarte entwerfen", "training-card": "Kartenentwurf erstellen", "set-goal": "Als Ziel setzen", retry: "Neu generieren" },
  "ja-JP": { copy: "コピー", share: "共有", "save-resource": "ライブラリに保存", "save-research-brief": "研究ブリーフを保存", "flash-card": "フラッシュカードを作成", "training-card": "カード案を作成", "set-goal": "目標にする", retry: "再生成" },
  "ko-KR": { copy: "복사", share: "공유", "save-resource": "라이브러리에 저장", "save-research-brief": "준비 브리프 저장", "flash-card": "플래시 카드 초안 만들기", "training-card": "카드 초안 만들기", "set-goal": "목표로 설정", retry: "다시 생성" },
  "pt-BR": { copy: "Copiar", share: "Compartilhar", "save-resource": "Salvar na Biblioteca", "save-research-brief": "Salvar preparação", "flash-card": "Propor um cartão flash", "training-card": "Propor um cartão", "set-goal": "Definir como meta", retry: "Regenerar" },
};
