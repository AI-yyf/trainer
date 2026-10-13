/** §十五: agent activity strip sentences in eight languages (no zh/en binary). */

import type { ComposerLanguage } from "../../types";

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

/** §十五: per-tool labels in eight languages (keyed by tool id; zh keys collide). */
export const TOOL_LABELS: Record<string, Record<ComposerLanguage, string>> = {
  search_resources: {
    "zh-CN": "搜索资料", "en-US": "Search resources", "es-ES": "Buscar recursos",
    "fr-FR": "Rechercher des ressources", "de-DE": "Ressourcen durchsuchen",
    "ja-JP": "資料を検索", "ko-KR": "자료 검색", "pt-BR": "Buscar recursos",
  },
  search: {
    "zh-CN": "搜索", "en-US": "Search", "es-ES": "Buscar",
    "fr-FR": "Rechercher", "de-DE": "Suchen",
    "ja-JP": "検索", "ko-KR": "검색", "pt-BR": "Buscar",
  },
  read_workspace_file: {
    "zh-CN": "读取文件", "en-US": "Read file", "es-ES": "Leer archivo",
    "fr-FR": "Lire le fichier", "de-DE": "Datei lesen",
    "ja-JP": "ファイルを読み取り", "ko-KR": "파일 읽기", "pt-BR": "Ler arquivo",
  },
  list_workspace_files: {
    "zh-CN": "浏览文件", "en-US": "List files", "es-ES": "Listar archivos",
    "fr-FR": "Lister les fichiers", "de-DE": "Dateien auflisten",
    "ja-JP": "ファイル一覧", "ko-KR": "파일 목록", "pt-BR": "Listar arquivos",
  },
  recall_memory: {
    "zh-CN": "回顾记忆", "en-US": "Recall memory", "es-ES": "Recordar memoria",
    "fr-FR": "Retrouver la mémoire", "de-DE": "Erinnerung abrufen",
    "ja-JP": "記憶を思い出す", "ko-KR": "기억 불러오기", "pt-BR": "Recordar memória",
  },
  record_learning_note: {
    "zh-CN": "保存观察", "en-US": "Save note", "es-ES": "Guardar observación",
    "fr-FR": "Enregistrer l'observation", "de-DE": "Beobachtung speichern",
    "ja-JP": "観察を保存", "ko-KR": "관찰 저장", "pt-BR": "Salvar observação",
  },
  inspect_plan: {
    "zh-CN": "查看计划", "en-US": "Inspect plan", "es-ES": "Inspeccionar plan",
    "fr-FR": "Inspecter le plan", "de-DE": "Plan prüfen",
    "ja-JP": "プランを確認", "ko-KR": "계획 검사", "pt-BR": "Inspecionar plano",
  },
  save_formal_plan: {
    "zh-CN": "保存计划", "en-US": "Save plan", "es-ES": "Guardar plan",
    "fr-FR": "Enregistrer le plan", "de-DE": "Plan speichern",
    "ja-JP": "プランを保存", "ko-KR": "계획 저장", "pt-BR": "Salvar plano",
  },
  verify_practice_current_file: {
    "zh-CN": "验证实战", "en-US": "Verify practice", "es-ES": "Verificar práctica",
    "fr-FR": "Vérifier la pratique", "de-DE": "Praxis prüfen",
    "ja-JP": "実践を検証", "ko-KR": "실습 검증", "pt-BR": "Verificar prática",
  },
  generate_training_card: {
    "zh-CN": "生成训练卡", "en-US": "Generate card", "es-ES": "Generar tarjeta",
    "fr-FR": "Générer une carte", "de-DE": "Karte erstellen",
    "ja-JP": "カードを生成", "ko-KR": "카드 생성", "pt-BR": "Gerar cartão",
  },
  generate_cards: {
    "zh-CN": "生成训练卡", "en-US": "Generate cards", "es-ES": "Generar tarjetas",
    "fr-FR": "Générer des cartes", "de-DE": "Karten erstellen",
    "ja-JP": "カードを生成", "ko-KR": "카드 생성", "pt-BR": "Gerar cartões",
  },
  card_generation: {
    "zh-CN": "生成训练卡", "en-US": "Card generation", "es-ES": "Generación de tarjeta",
    "fr-FR": "Génération de carte", "de-DE": "Kartenerstellung",
    "ja-JP": "カード生成", "ko-KR": "카드 생성", "pt-BR": "Geração de cartão",
  },
  run_diagnostics: {
    "zh-CN": "运行诊断", "en-US": "Run diagnostics", "es-ES": "Ejecutar diagnóstico",
    "fr-FR": "Exécuter le diagnostic", "de-DE": "Diagnose ausführen",
    "ja-JP": "診断を実行", "ko-KR": "진단 실행", "pt-BR": "Executar diagnóstico",
  },
  align_plan: {
    "zh-CN": "对齐计划", "en-US": "Align plan", "es-ES": "Alinear plan",
    "fr-FR": "Aligner le plan", "de-DE": "Plan abstimmen",
    "ja-JP": "プランを整合", "ko-KR": "계획 정렬", "pt-BR": "Alinhar plano",
  },
  plan_alignment: {
    "zh-CN": "对齐计划", "en-US": "Align plan", "es-ES": "Alinear plan",
    "fr-FR": "Aligner le plan", "de-DE": "Plan abstimmen",
    "ja-JP": "プランを整合", "ko-KR": "계획 정렬", "pt-BR": "Alinhar plano",
  },
  evaluation: {
    "zh-CN": "评估结果", "en-US": "Evaluation", "es-ES": "Evaluación",
    "fr-FR": "Évaluation", "de-DE": "Auswertung",
    "ja-JP": "評価", "ko-KR": "평가", "pt-BR": "Avaliação",
  },
  coach_finalize: {
    "zh-CN": "收束回复", "en-US": "Finalize", "es-ES": "Finalizar",
    "fr-FR": "Finaliser", "de-DE": "Abschließen",
    "ja-JP": "まとめ", "ko-KR": "마무리", "pt-BR": "Finalizar",
  },
};
