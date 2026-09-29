/** §十五: humanized empty-state copy in eight languages (no zh/en binary). */

import type { ComposerLanguage } from "../../lib/types";

/** {q} is the failed search query slot. */
export const HUMANIZED_EMPTY_STATES_TEXT: Record<string, Record<string, string>> = {
  // WelcomeEmptyState
  "准备开始": {
    "en-US": "Ready to start",
    "es-ES": "Listo para empezar",
    "fr-FR": "Prêt à commencer",
    "de-DE": "Bereit zum Start",
    "ja-JP": "始める準備ができました",
    "ko-KR": "시작할 준비가 되었습니다",
    "pt-BR": "Pronto para começar",
  },
  "先连接模型，然后发送一个目标。": {
    "en-US": "Connect a model, then send a goal.",
    "es-ES": "Conecta un modelo y envía un objetivo.",
    "fr-FR": "Connectez un modèle, puis envoyez un objectif.",
    "de-DE": "Verbinde ein Modell und sende dann ein Ziel.",
    "ja-JP": "モデルを接続して、目標を送信してください。",
    "ko-KR": "모델을 연결한 뒤 목표를 보내세요.",
    "pt-BR": "Conecte um modelo e envie uma meta.",
  },
  "配置模型": {
    "en-US": "Configure Model",
    "es-ES": "Configurar modelo",
    "fr-FR": "Configurer le modèle",
    "de-DE": "Modell konfigurieren",
    "ja-JP": "モデルを設定",
    "ko-KR": "모델 설정",
    "pt-BR": "Configurar modelo",
  },
  "开始": {
    "en-US": "Start",
    "es-ES": "Empezar",
    "fr-FR": "Commencer",
    "de-DE": "Starten",
    "ja-JP": "開始",
    "ko-KR": "시작",
    "pt-BR": "Começar",
  },

  // SearchEmptyState
  "没有找到相关结果": {
    "en-US": "No results found",
    "es-ES": "No se encontraron resultados",
    "fr-FR": "Aucun résultat trouvé",
    "de-DE": "Keine Ergebnisse gefunden",
    "ja-JP": "関連する結果が見つかりません",
    "ko-KR": "관련 결과를 찾을 수 없습니다",
    "pt-BR": "Nenhum resultado encontrado",
  },
  "没有找到与\"{q}\"相关的资料。尝试其他关键词或调整搜索范围。": {
    "en-US": "No results for \"{q}\". Try different keywords or adjust your search.",
    "es-ES": "No hay resultados para \"{q}\". Prueba otras palabras clave o ajusta la búsqueda.",
    "fr-FR": "Aucun résultat pour \"{q}\". Essayez d'autres mots-clés ou ajustez la recherche.",
    "de-DE": "Keine Ergebnisse für \"{q}\". Andere Suchbegriffe ausprobieren oder die Suche anpassen.",
    "ja-JP": "\"{q}\" に関連する資料は見つかりませんでした。別のキーワードを試すか、検索範囲を調整してください。",
    "ko-KR": "\"{q}\"에 관련된 자료를 찾지 못했습니다. 다른 키워드를 시도하거나 검색 범위를 조정하세요.",
    "pt-BR": "Nenhum resultado para \"{q}\". Tente outras palavras-chave ou ajuste sua busca.",
  },
  "试试输入关键词，或者浏览现有的资料库。": {
    "en-US": "Try searching for a keyword, or browse your existing resources.",
    "es-ES": "Prueba a buscar una palabra clave o explora tus recursos existentes.",
    "fr-FR": "Essayez de saisir un mot-clé ou parcourez vos ressources existantes.",
    "de-DE": "Gib ein Stichwort ein oder stöbere durch die vorhandenen Ressourcen.",
    "ja-JP": "キーワードを入力するか、既存の資料を眺めてみてください。",
    "ko-KR": "키워드를 입력하거나 기존 자료를 둘러보세요.",
    "pt-BR": "Tente buscar uma palavra-chave ou navegue pelos seus recursos existentes.",
  },
  "清除搜索": {
    "en-US": "Clear Search",
    "es-ES": "Limpiar búsqueda",
    "fr-FR": "Effacer la recherche",
    "de-DE": "Suche löschen",
    "ja-JP": "検索をクリア",
    "ko-KR": "검색 지우기",
    "pt-BR": "Limpar busca",
  },
  "尝试其他关键词": {
    "en-US": "Try Different Keywords",
    "es-ES": "Probar otras palabras clave",
    "fr-FR": "Essayer d'autres mots-clés",
    "de-DE": "Andere Suchbegriffe versuchen",
    "ja-JP": "別のキーワードを試す",
    "ko-KR": "다른 키워드 시도",
    "pt-BR": "Tentar outras palavras-chave",
  },

  // LearningEmptyState
  "还没有学习资料": {
    "en-US": "No learning materials yet",
    "es-ES": "Aún no hay materiales de aprendizaje",
    "fr-FR": "Pas encore de supports d'apprentissage",
    "de-DE": "Noch keine Lernmaterialien",
    "ja-JP": "学習教材がまだありません",
    "ko-KR": "아직 학습 자료가 없습니다",
    "pt-BR": "Ainda não há materiais de aprendizagem",
  },
  "导入代码、文档或网页。": {
    "en-US": "Import code, docs, or web pages.",
    "es-ES": "Importa código, documentos o páginas web.",
    "fr-FR": "Importez du code, des documents ou des pages web.",
    "de-DE": "Code, Dokumente oder Webseiten importieren.",
    "ja-JP": "コード、ドキュメント、Web ページを取り込みましょう。",
    "ko-KR": "코드, 문서, 웹 페이지를 가져오세요.",
    "pt-BR": "Importe código, documentos ou páginas web.",
  },
  "导入资料": {
    "en-US": "Import Resources",
    "es-ES": "Importar recursos",
    "fr-FR": "Importer des ressources",
    "de-DE": "Ressourcen importieren",
    "ja-JP": "資料を取り込む",
    "ko-KR": "자료 가져오기",
    "pt-BR": "Importar recursos",
  },
  "开始学习": {
    "en-US": "Start Learning",
    "es-ES": "Empezar a aprender",
    "fr-FR": "Commencer à apprendre",
    "de-DE": "Lernen starten",
    "ja-JP": "学習を開始",
    "ko-KR": "학습 시작",
    "pt-BR": "Começar a aprender",
  },

  // SettingsEmptyState
  "需要配置": {
    "en-US": "Configuration Required",
    "es-ES": "Configuración requerida",
    "fr-FR": "Configuration requise",
    "de-DE": "Konfiguration erforderlich",
    "ja-JP": "設定が必要です",
    "ko-KR": "설정 필요",
    "pt-BR": "Configuração necessária",
  },
  "在使用 Trainer 之前，需要先配置你的 provider。请设置 provider、model 和 API key。": {
    "en-US": "Before using Trainer, you need to configure your provider. Please set up your provider, model, and API key.",
    "es-ES": "Antes de usar Trainer, debes configurar tu proveedor. Configura el proveedor, el modelo y la clave de API.",
    "fr-FR": "Avant d'utiliser Trainer, vous devez configurer votre fournisseur. Renseignez le fournisseur, le modèle et la clé d'API.",
    "de-DE": "Bevor du Trainer nutzt, musst du deinen Provider konfigurieren. Lege Provider, Modell und API-Schlüssel fest.",
    "ja-JP": "Trainer を使う前に、まず provider を設定する必要があります。provider、model、API キーを設定してください。",
    "ko-KR": "Trainer 를 사용하기 전에 provider 를 먼저 설정해야 합니다. provider, model, API 키를 설정하세요.",
    "pt-BR": "Antes de usar o Trainer, você precisa configurar seu provedor. Defina o provedor, o modelo e a chave de API.",
  },
  "去配置": {
    "en-US": "Configure",
    "es-ES": "Configurar",
    "fr-FR": "Configurer",
    "de-DE": "Konfigurieren",
    "ja-JP": "設定へ",
    "ko-KR": "설정하기",
    "pt-BR": "Configurar",
  },
};

export function humanizedEmptyStatesCopy(language: ComposerLanguage, key: string): string {
  return HUMANIZED_EMPTY_STATES_TEXT[key]?.[language] ?? key;
}
