/** §十五: rich message content chrome copy in eight languages (no zh/en binary). */

import type { ComposerLanguage } from "../../lib/types";

/**
 * Labels around markdown rendering (tables, diagrams, fallback notices).
 * The zh-CN source string is the record key.
 */
export const MESSAGE_RICH_CONTENT_TEXT: Record<string, Record<string, string>> = {
  "图表": {
    "en-US": "Diagram",
    "es-ES": "Diagrama",
    "fr-FR": "Diagramme",
    "de-DE": "Diagramm",
    "ja-JP": "図",
    "ko-KR": "다이어그램",
    "pt-BR": "Diagrama",
  },
  "思维导图": {
    "en-US": "Mind map",
    "es-ES": "Mapa mental",
    "fr-FR": "Carte mentale",
    "de-DE": "Mindmap",
    "ja-JP": "マインドマップ",
    "ko-KR": "마인드맵",
    "pt-BR": "Mapa mental",
  },
  "表格": {
    "en-US": "Table",
    "es-ES": "Tabla",
    "fr-FR": "Tableau",
    "de-DE": "Tabelle",
    "ja-JP": "表",
    "ko-KR": "표",
    "pt-BR": "Tabela",
  },
  "图表渲染失败，已回退为原始内容。": {
    "en-US": "Diagram render failed. Showing the raw content instead.",
    "es-ES": "Error al renderizar el diagrama. Se muestra el contenido original.",
    "fr-FR": "Échec du rendu du diagramme. Le contenu brut est affiché à la place.",
    "de-DE": "Diagramm-Rendering fehlgeschlagen. Der Rohinhalt wird angezeigt.",
    "ja-JP": "図の描画に失敗しました。元の内容を表示しています。",
    "ko-KR": "다이어그램 렌더링에 실패했습니다. 원본 내용을 대신 표시합니다.",
    "pt-BR": "Falha ao renderizar o diagrama. Exibindo o conteúdo original.",
  },
  "正在整理显示…": {
    "en-US": "Rendering…",
    "es-ES": "Preparando la vista…",
    "fr-FR": "Mise en forme…",
    "de-DE": "Wird aufbereitet…",
    "ja-JP": "表示を整理しています…",
    "ko-KR": "표시를 정리하는 중…",
    "pt-BR": "Organizando a exibição…",
  },
  "列": {
    "en-US": "column",
    "es-ES": "columna",
    "fr-FR": "colonne",
    "de-DE": "Spalte",
    "ja-JP": "列",
    "ko-KR": "열",
    "pt-BR": "coluna",
  },
};

export function messageRichContentCopy(language: ComposerLanguage, key: string): string {
  return MESSAGE_RICH_CONTENT_TEXT[key]?.[language] ?? key;
}
