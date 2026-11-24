/** §十五: rich message content chrome copy in eight languages (no zh/en binary). */

import type { ComposerLanguage } from "../../types";

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
  "配图": {
    "en-US": "Figure",
    "es-ES": "Figura",
    "fr-FR": "Figure",
    "de-DE": "Abbildung",
    "ja-JP": "図解",
    "ko-KR": "그림",
    "pt-BR": "Figura",
  },
  "点击放大查看": {
    "en-US": "Click to zoom",
    "es-ES": "Haz clic para ampliar",
    "fr-FR": "Cliquer pour agrandir",
    "de-DE": "Zum Vergrößern klicken",
    "ja-JP": "クリックして拡大",
    "ko-KR": "클릭하여 확대",
    "pt-BR": "Clique para ampliar",
  },
  "关闭预览": {
    "en-US": "Close preview",
    "es-ES": "Cerrar vista previa",
    "fr-FR": "Fermer l'aperçu",
    "de-DE": "Vorschau schließen",
    "ja-JP": "プレビューを閉じる",
    "ko-KR": "미리 보기 닫기",
    "pt-BR": "Fechar visualização",
  },
  "图片加载失败": {
    "en-US": "Image could not be displayed.",
    "es-ES": "No se pudo mostrar la imagen.",
    "fr-FR": "Impossible d'afficher l'image.",
    "de-DE": "Bild konnte nicht angezeigt werden.",
    "ja-JP": "画像を表示できませんでした。",
    "ko-KR": "이미지를 표시할 수 없습니다.",
    "pt-BR": "Não foi possível exibir a imagem.",
  },
  "加载远程图片": {
    "en-US": "Load remote image",
    "es-ES": "Cargar imagen remota",
    "fr-FR": "Charger l’image distante",
    "de-DE": "Externes Bild laden",
    "ja-JP": "外部画像を読み込む",
    "ko-KR": "원격 이미지 불러오기",
    "pt-BR": "Carregar imagem remota",
  },
  "远程图片在你点击之前不会加载，以免对方站点得知你正在阅读。": {
    "en-US": "Remote images stay unloaded until you click, so the site does not learn that you are reading this.",
    "es-ES": "Las imágenes remotas no se cargan hasta que haces clic, para que el sitio no sepa que estás leyendo esto.",
    "fr-FR": "Les images distantes restent déchargées tant que vous ne cliquez pas, pour que le site ne sache pas que vous lisez ceci.",
    "de-DE": "Externe Bilder werden erst nach einem Klick geladen, damit die Seite nicht erfährt, dass du dies liest.",
    "ja-JP": "外部画像はクリックするまで読み込まれません。サイトに閲覧を知られないためです。",
    "ko-KR": "원격 이미지는 클릭하기 전에는 불러오지 않아, 사이트가 이 글을 읽고 있다는 사실을 알지 못합니다.",
    "pt-BR": "Imagens remotas só são carregadas quando você clica, para o site não descobrir que você está lendo isto.",
  },
};

export function messageRichContentCopy(language: ComposerLanguage, key: string): string {
  return MESSAGE_RICH_CONTENT_TEXT[key]?.[language] ?? key;
}
