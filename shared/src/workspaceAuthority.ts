export type WorkspaceAuthoritySurfaceLanguage = "zh-CN" | "en-US" | "es-ES" | "fr-FR" | "de-DE" | "ja-JP" | "ko-KR" | "pt-BR";

/**
 * Six-level permission gradient per docs/open-source-fit-and-provider-strategy.md §7.8
 *
 * - inspect: read/list/search/index/preview/summarize
 * - annotate: write notes/plans/evidence, no source code changes
 * - reorganize: mkdir/move/rename within root
 * - generate: create new files/cards/summaries/scripts
 * - apply: modify existing files
 * - destructive: delete/overwrite/bulk move (only via trash/review path)
 */
export type PermissionLevel = "inspect" | "annotate" | "reorganize" | "generate" | "apply" | "destructive";

export const PERMISSION_LEVELS: PermissionLevel[] = [
  "inspect",
  "annotate",
  "reorganize",
  "generate",
  "apply",
  "destructive",
];

export const PERMISSION_LEVEL_LABELS: Record<
  PermissionLevel,
  Record<WorkspaceAuthoritySurfaceLanguage, string>
> = {
  inspect: { "zh-CN": "查看", "en-US": "Inspect", "es-ES": "Inspeccionar", "fr-FR": "Inspecter", "de-DE": "Inspizieren", "ja-JP": "検査", "ko-KR": "검사", "pt-BR": "Inspecionar" },
  annotate: { "zh-CN": "批注", "en-US": "Annotate", "es-ES": "Anotar", "fr-FR": "Annoter", "de-DE": "Annotieren", "ja-JP": "注釈", "ko-KR": "주석", "pt-BR": "Anotar" },
  reorganize: { "zh-CN": "整理", "en-US": "Reorganize", "es-ES": "Reorganizar", "fr-FR": "Réorganiser", "de-DE": "Neuorganisieren", "ja-JP": "整理", "ko-KR": "재구성", "pt-BR": "Reorganizar" },
  generate: { "zh-CN": "生成", "en-US": "Generate", "es-ES": "Generar", "fr-FR": "Générer", "de-DE": "Generieren", "ja-JP": "生成", "ko-KR": "생성", "pt-BR": "Gerar" },
  apply: { "zh-CN": "修改", "en-US": "Apply", "es-ES": "Aplicar", "fr-FR": "Appliquer", "de-DE": "Anwenden", "ja-JP": "適用", "ko-KR": "적용", "pt-BR": "Aplicar" },
  destructive: { "zh-CN": "删除", "en-US": "Destructive", "es-ES": "Destructivo", "fr-FR": "Destructeur", "de-DE": "Destruktiv", "ja-JP": "破壊的", "ko-KR": "파괴적", "pt-BR": "Destrutivo" },
};

export const PERMISSION_LEVEL_ORDER: Record<PermissionLevel, number> = {
  inspect: 0,
  annotate: 1,
  reorganize: 2,
  generate: 3,
  apply: 4,
  destructive: 5,
};

export const DEFAULT_ENABLED_PERMISSIONS: PermissionLevel[] = ["inspect", "annotate"];

const LOCALIZED_PERMISSION_LEVEL_LABELS: Record<
  PermissionLevel,
  Record<WorkspaceAuthoritySurfaceLanguage, string>
> = {
  inspect: { "zh-CN": "查看", "en-US": "Inspect", "es-ES": "Inspeccionar", "fr-FR": "Inspecter", "de-DE": "Prüfen", "ja-JP": "確認", "ko-KR": "확인", "pt-BR": "Inspecionar" },
  annotate: { "zh-CN": "批注", "en-US": "Annotate", "es-ES": "Anotar", "fr-FR": "Annoter", "de-DE": "Notieren", "ja-JP": "注記", "ko-KR": "주석", "pt-BR": "Anotar" },
  reorganize: { "zh-CN": "整理", "en-US": "Reorganize", "es-ES": "Reorganizar", "fr-FR": "Réorganiser", "de-DE": "Neu ordnen", "ja-JP": "整理", "ko-KR": "재구성", "pt-BR": "Reorganizar" },
  generate: { "zh-CN": "生成", "en-US": "Generate", "es-ES": "Generar", "fr-FR": "Générer", "de-DE": "Erzeugen", "ja-JP": "生成", "ko-KR": "생성", "pt-BR": "Gerar" },
  apply: { "zh-CN": "修改", "en-US": "Apply", "es-ES": "Aplicar", "fr-FR": "Appliquer", "de-DE": "Ändern", "ja-JP": "適用", "ko-KR": "적용", "pt-BR": "Aplicar" },
  destructive: { "zh-CN": "高风险", "en-US": "Destructive", "es-ES": "Destructivo", "fr-FR": "Destructif", "de-DE": "Destruktiv", "ja-JP": "破壊的", "ko-KR": "파괴적", "pt-BR": "Destrutivo" },
};

const LOCALIZED_PERMISSION_LEVEL_DESCRIPTIONS: Record<
  PermissionLevel,
  Record<WorkspaceAuthoritySurfaceLanguage, string>
> = {
  inspect: {
    "zh-CN": "读取、列表、搜索、索引、预览、摘要",
    "en-US": "Read, list, search, index, preview, summarize",
    "es-ES": "Leer, listar, buscar, indexar, previsualizar, resumir",
    "fr-FR": "Lire, lister, rechercher, indexer, prévisualiser, résumer",
    "de-DE": "Lesen, auflisten, suchen, indizieren, Vorschau, zusammenfassen",
    "ja-JP": "読む、一覧、検索、索引、プレビュー、要約",
    "ko-KR": "읽기, 목록, 검색, 색인, 미리 보기, 요약",
    "pt-BR": "Ler, listar, buscar, indexar, visualizar, resumir",
  },
  annotate: {
    "zh-CN": "写笔记、计划、证据，不改源码",
    "en-US": "Write notes, plans, evidence - no source code changes",
    "es-ES": "Escribir notas, planes y evidencia, sin cambiar el código fuente",
    "fr-FR": "Écrire des notes, plans et preuves, sans modifier le code source",
    "de-DE": "Notizen, Pläne und Nachweise schreiben, ohne Quellcode zu ändern",
    "ja-JP": "メモ、計画、証拠を書く。ソースコードは変更しない",
    "ko-KR": "메모, 계획, 근거를 남기되 소스 코드는 바꾸지 않음",
    "pt-BR": "Escrever notas, planos e evidências, sem alterar o código-fonte",
  },
  reorganize: {
    "zh-CN": "新建目录、移动、重命名，在根目录内重组",
    "en-US": "Create folders, move, rename, and reorganize within the root",
    "es-ES": "Crear carpetas, mover, renombrar y reorganizar dentro de la raíz",
    "fr-FR": "Créer des dossiers, déplacer, renommer et réorganiser dans la racine",
    "de-DE": "Ordner anlegen, verschieben, umbenennen und innerhalb des Wurzelpfads neu ordnen",
    "ja-JP": "フォルダ作成、移動、名前変更。ルート内で再整理",
    "ko-KR": "폴더 생성, 이동, 이름 변경, 루트 안에서 재구성",
    "pt-BR": "Criar pastas, mover, renomear e reorganizar dentro da raiz",
  },
  generate: {
    "zh-CN": "生成新文件、卡片、摘要、脚本",
    "en-US": "Generate new files, cards, summaries, scripts",
    "es-ES": "Generar nuevos archivos, tarjetas, resúmenes y scripts",
    "fr-FR": "Générer de nouveaux fichiers, cartes, résumés et scripts",
    "de-DE": "Neue Dateien, Karten, Zusammenfassungen und Skripte erzeugen",
    "ja-JP": "新しいファイル、カード、要約、スクリプトを生成",
    "ko-KR": "새 파일, 카드, 요약, 스크립트 생성",
    "pt-BR": "Gerar novos arquivos, cartões, resumos e scripts",
  },
  apply: {
    "zh-CN": "修改已有文件",
    "en-US": "Modify existing files",
    "es-ES": "Modificar archivos existentes",
    "fr-FR": "Modifier les fichiers existants",
    "de-DE": "Vorhandene Dateien ändern",
    "ja-JP": "既存ファイルを修正",
    "ko-KR": "기존 파일 수정",
    "pt-BR": "Modificar arquivos existentes",
  },
  destructive: {
    "zh-CN": "删除、覆盖、批量移动，仅走 trash/review 路径",
    "en-US": "Delete, overwrite, or bulk move only through the trash/review path",
    "es-ES": "Eliminar, sobrescribir o mover en masa solo por la ruta de trash/review",
    "fr-FR": "Supprimer, écraser ou déplacer en masse uniquement via le chemin trash/review",
    "de-DE": "Löschen, überschreiben oder massenhaft verschieben nur über den Trash-/Review-Pfad",
    "ja-JP": "削除、上書き、一括移動は trash/review 経路のみ",
    "ko-KR": "삭제, 덮어쓰기, 대량 이동은 trash/review 경로로만 허용",
    "pt-BR": "Excluir, sobrescrever ou mover em massa apenas pela rota trash/review",
  },
};

type WorkspaceAuthorityPhraseKey =
  | "unknownSource"
  | "unconfigured"
  | "mountedSources"
  | "openWorkspaceFirst"
  | "inspectNext"
  | "annotateNext"
  | "destructiveNext"
  | "applyNext"
  | "generateNext"
  | "reorganizeNext"
  | "confirmBoundaryNext";

const WORKSPACE_AUTHORITY_PHRASES: Record<
  WorkspaceAuthoritySurfaceLanguage,
  Record<WorkspaceAuthorityPhraseKey, string>
> = {
  "zh-CN": {
    unknownSource: "未知来源",
    unconfigured: "未配置",
    mountedSources: "{count} 个挂载来源",
    openWorkspaceFirst: "先打开或连接工作区根目录，再让我读取边界并决定下一步。",
    inspectNext: "先读、搜、预览关键信息，再挑第一条可验证任务。",
    annotateNext: "先把判断写成笔记、计划或证据，再决定要不要动源码。",
    destructiveNext: "先把高风险内容放进 trash 或 checkpoint，再做这一轮最小改动。",
    applyNext: "先做最薄的一次编辑，再立刻验证它是否站得住。",
    generateNext: "先生成最小可用的卡片、摘要或脚本，再检查是否贴合当前任务。",
    reorganizeNext: "先把工作区结构理顺，再把当前任务放进更清晰的目录。",
    confirmBoundaryNext: "先确认边界，再做最小且可验证的动作。",
  },
  "en-US": {
    unknownSource: "Unknown source",
    unconfigured: "Unconfigured",
    mountedSources: "{count} mounted sources",
    openWorkspaceFirst: "Open or connect a workspace root first so I can read the boundary and choose a next step.",
    inspectNext: "Start by reading, searching, and previewing the key material, then pick the first verifiable task.",
    annotateNext: "Write the judgment down as notes, a plan, or evidence first, then decide whether source code should move.",
    destructiveNext: "Move risky content into trash or a checkpoint first, then make the smallest change in this round.",
    applyNext: "Start with the thinnest edit, then verify immediately that it actually holds.",
    generateNext: "Generate the smallest useful card, summary, or script first, then check whether it matches the current task.",
    reorganizeNext: "First reorganize the workspace shape, then place the current task into a clearer folder.",
    confirmBoundaryNext: "Confirm the boundary first, then make the smallest verifiable move.",
  },
  "es-ES": {
    unknownSource: "Origen desconocido",
    unconfigured: "Sin configurar",
    mountedSources: "{count} fuentes montadas",
    openWorkspaceFirst: "Abre o conecta primero una raíz de workspace para que pueda leer el límite y elegir el siguiente paso.",
    inspectNext: "Empieza leyendo, buscando y previsualizando el material clave, luego elige la primera tarea verificable.",
    annotateNext: "Anota primero el juicio como notas, plan o evidencia, y luego decide si hace falta tocar el código fuente.",
    destructiveNext: "Mueve primero el contenido riesgoso a trash o a un checkpoint y luego haz el cambio más pequeño de esta ronda.",
    applyNext: "Empieza con la edición más pequeña y verifica enseguida que realmente se sostiene.",
    generateNext: "Genera primero la tarjeta, el resumen o el script más pequeño que sirva, y luego comprueba si encaja con la tarea actual.",
    reorganizeNext: "Primero ordena la estructura del workspace y luego coloca la tarea actual en una carpeta más clara.",
    confirmBoundaryNext: "Confirma primero el límite y luego haz el movimiento verificable más pequeño.",
  },
  "fr-FR": {
    unknownSource: "Source inconnue",
    unconfigured: "Non configuré",
    mountedSources: "{count} sources montées",
    openWorkspaceFirst: "Ouvrez ou connectez d'abord une racine de workspace pour que je puisse lire la limite et choisir la suite.",
    inspectNext: "Commencez par lire, rechercher et prévisualiser le contenu clé, puis choisissez la première tâche vérifiable.",
    annotateNext: "Notez d'abord le jugement sous forme de notes, plan ou preuves, puis décidez s'il faut toucher au code source.",
    destructiveNext: "Déplacez d'abord le contenu risqué vers trash ou un checkpoint, puis faites le plus petit changement possible pour ce tour.",
    applyNext: "Commencez par la modification la plus fine, puis vérifiez aussitôt qu'elle tient vraiment.",
    generateNext: "Générez d'abord la carte, le résumé ou le script utile le plus petit, puis vérifiez qu'il correspond à la tâche actuelle.",
    reorganizeNext: "Réorganisez d'abord la structure du workspace, puis placez la tâche actuelle dans un dossier plus clair.",
    confirmBoundaryNext: "Confirmez d'abord la limite, puis faites le plus petit mouvement vérifiable.",
  },
  "de-DE": {
    unknownSource: "Unbekannte Quelle",
    unconfigured: "Nicht konfiguriert",
    mountedSources: "{count} eingebundene Quellen",
    openWorkspaceFirst: "Öffnen oder verbinden Sie zuerst einen Workspace-Stamm, damit ich die Grenze lesen und den nächsten Schritt wählen kann.",
    inspectNext: "Lesen, suchen und prüfen Sie zuerst das wichtigste Material und wählen Sie dann die erste überprüfbare Aufgabe.",
    annotateNext: "Halten Sie die Einschätzung zuerst als Notizen, Plan oder Nachweis fest und entscheiden Sie dann, ob Quellcode geändert werden soll.",
    destructiveNext: "Verschieben Sie riskante Inhalte zuerst in den Trash oder in einen Checkpoint und machen Sie dann die kleinste Änderung dieser Runde.",
    applyNext: "Beginnen Sie mit der kleinsten Bearbeitung und prüfen Sie sofort, ob sie wirklich trägt.",
    generateNext: "Erzeugen Sie zuerst die kleinste nützliche Karte, Zusammenfassung oder das kleinste Skript und prüfen Sie dann, ob es zur aktuellen Aufgabe passt.",
    reorganizeNext: "Ordnen Sie zuerst die Workspace-Struktur neu und legen Sie dann die aktuelle Aufgabe in einen klareren Ordner.",
    confirmBoundaryNext: "Bestätigen Sie zuerst die Grenze und machen Sie dann die kleinste überprüfbare Aktion.",
  },
  "ja-JP": {
    unknownSource: "不明なソース",
    unconfigured: "未設定",
    mountedSources: "{count} 個のマウント元",
    openWorkspaceFirst: "先に workspace ルートを開くか接続してください。境界を読んで次の一手を決めます。",
    inspectNext: "まず重要な材料を読み、検索し、プレビューしてから、最初の検証可能な作業を選びます。",
    annotateNext: "まず判断をメモ、計画、証拠として残し、その後でソースコードを動かすか決めます。",
    destructiveNext: "まずリスクの高い内容を trash か checkpoint に移し、その後で今回の最小変更を行います。",
    applyNext: "まず最も薄い編集から始め、すぐにそれが本当に成り立つか確認します。",
    generateNext: "まず最小限で役に立つカード、要約、スクリプトを生成し、それが現在の作業に合うか確認します。",
    reorganizeNext: "まず workspace の構造を整え、その後で現在の作業をより分かりやすいフォルダに置きます。",
    confirmBoundaryNext: "まず境界を確認し、その後で最小かつ検証可能な動きをします。",
  },
  "ko-KR": {
    unknownSource: "알 수 없는 출처",
    unconfigured: "미설정",
    mountedSources: "마운트된 소스 {count}개",
    openWorkspaceFirst: "먼저 workspace 루트를 열거나 연결해 주세요. 그래야 경계를 읽고 다음 단계를 고를 수 있습니다.",
    inspectNext: "먼저 핵심 자료를 읽고, 찾고, 미리 본 뒤 첫 번째로 검증 가능한 작업을 고르세요.",
    annotateNext: "먼저 판단을 메모, 계획, 근거로 남긴 뒤 소스 코드를 건드릴지 결정하세요.",
    destructiveNext: "먼저 위험한 내용을 trash 또는 checkpoint로 옮기고, 그다음 이번 라운드의 가장 작은 변경을 하세요.",
    applyNext: "가장 얇은 편집부터 시작하고, 바로 그것이 실제로 유지되는지 검증하세요.",
    generateNext: "먼저 가장 작은 유용한 카드, 요약, 스크립트를 만들고, 그것이 현재 작업에 맞는지 확인하세요.",
    reorganizeNext: "먼저 workspace 구조를 정리한 다음 현재 작업을 더 분명한 폴더에 배치하세요.",
    confirmBoundaryNext: "먼저 경계를 확인한 뒤 가장 작고 검증 가능한 움직임을 하세요.",
  },
  "pt-BR": {
    unknownSource: "Origem desconhecida",
    unconfigured: "Não configurado",
    mountedSources: "{count} fontes montadas",
    openWorkspaceFirst: "Abra ou conecte primeiro uma raiz de workspace para que eu possa ler o limite e escolher o próximo passo.",
    inspectNext: "Comece lendo, buscando e visualizando o material principal, depois escolha a primeira tarefa verificável.",
    annotateNext: "Registre primeiro o julgamento como notas, plano ou evidência, e depois decida se o código-fonte precisa mudar.",
    destructiveNext: "Mova primeiro o conteúdo arriscado para trash ou checkpoint e depois faça a menor mudança desta rodada.",
    applyNext: "Comece com a edição mais fina e verifique imediatamente se ela realmente se sustenta.",
    generateNext: "Gere primeiro o menor cartão, resumo ou script útil e depois verifique se ele combina com a tarefa atual.",
    reorganizeNext: "Primeiro reorganize a estrutura do workspace e depois coloque a tarefa atual em uma pasta mais clara.",
    confirmBoundaryNext: "Confirme primeiro o limite e depois faça o menor movimento verificável.",
  },
};

const OPERATION_LABELS: Record<string, Record<WorkspaceAuthoritySurfaceLanguage, string>> = {
  read: { "zh-CN": "读取", "en-US": "Read", "es-ES": "Leer", "fr-FR": "Lire", "de-DE": "Lesen", "ja-JP": "読む", "ko-KR": "읽기", "pt-BR": "Ler" },
  list: { "zh-CN": "列表", "en-US": "List", "es-ES": "Listar", "fr-FR": "Lister", "de-DE": "Auflisten", "ja-JP": "一覧", "ko-KR": "목록", "pt-BR": "Listar" },
  search: { "zh-CN": "搜索", "en-US": "Search", "es-ES": "Buscar", "fr-FR": "Rechercher", "de-DE": "Suchen", "ja-JP": "検索", "ko-KR": "검색", "pt-BR": "Buscar" },
  index: { "zh-CN": "索引", "en-US": "Index", "es-ES": "Indexar", "fr-FR": "Indexer", "de-DE": "Indizieren", "ja-JP": "索引", "ko-KR": "색인", "pt-BR": "Indexar" },
  preview: { "zh-CN": "预览", "en-US": "Preview", "es-ES": "Vista previa", "fr-FR": "Prévisualiser", "de-DE": "Vorschau", "ja-JP": "プレビュー", "ko-KR": "미리 보기", "pt-BR": "Visualizar" },
  summarize: { "zh-CN": "摘要", "en-US": "Summarize", "es-ES": "Resumir", "fr-FR": "Résumer", "de-DE": "Zusammenfassen", "ja-JP": "要約", "ko-KR": "요약", "pt-BR": "Resumir" },
  annotate: { "zh-CN": "批注", "en-US": "Annotate", "es-ES": "Anotar", "fr-FR": "Annoter", "de-DE": "Notieren", "ja-JP": "注記", "ko-KR": "주석", "pt-BR": "Anotar" },
  write: { "zh-CN": "写入", "en-US": "Write", "es-ES": "Escribir", "fr-FR": "Écrire", "de-DE": "Schreiben", "ja-JP": "書き込む", "ko-KR": "쓰기", "pt-BR": "Escrever" },
  modify: { "zh-CN": "修改", "en-US": "Modify", "es-ES": "Modificar", "fr-FR": "Modifier", "de-DE": "Ändern", "ja-JP": "修正", "ko-KR": "수정", "pt-BR": "Modificar" },
  delete: { "zh-CN": "删除", "en-US": "Delete", "es-ES": "Eliminar", "fr-FR": "Supprimer", "de-DE": "Löschen", "ja-JP": "削除", "ko-KR": "삭제", "pt-BR": "Excluir" },
  restore: { "zh-CN": "恢复", "en-US": "Restore", "es-ES": "Restaurar", "fr-FR": "Restaurer", "de-DE": "Wiederherstellen", "ja-JP": "復元", "ko-KR": "복원", "pt-BR": "Restaurar" },
  mkdir: { "zh-CN": "建目录", "en-US": "mkdir", "es-ES": "crear carpeta", "fr-FR": "créer dossier", "de-DE": "Ordner anlegen", "ja-JP": "フォルダ作成", "ko-KR": "폴더 생성", "pt-BR": "criar pasta" },
  move: { "zh-CN": "移动", "en-US": "Move", "es-ES": "Mover", "fr-FR": "Déplacer", "de-DE": "Verschieben", "ja-JP": "移動", "ko-KR": "이동", "pt-BR": "Mover" },
  rename: { "zh-CN": "重命名", "en-US": "Rename", "es-ES": "Renombrar", "fr-FR": "Renommer", "de-DE": "Umbenennen", "ja-JP": "名前変更", "ko-KR": "이름 변경", "pt-BR": "Renomear" },
  generate: { "zh-CN": "生成", "en-US": "Generate", "es-ES": "Generar", "fr-FR": "Générer", "de-DE": "Erzeugen", "ja-JP": "生成", "ko-KR": "생성", "pt-BR": "Gerar" },
};

function workspaceAuthorityPhrase(
  language: WorkspaceAuthoritySurfaceLanguage,
  key: WorkspaceAuthorityPhraseKey,
): string {
  return WORKSPACE_AUTHORITY_PHRASES[language]?.[key] ?? WORKSPACE_AUTHORITY_PHRASES["en-US"][key];
}

function formatPhraseCount(template: string, count: number): string {
  return template.replace("{count}", String(count));
}

function localizeOperation(operation: string, language: WorkspaceAuthoritySurfaceLanguage): string {
  return OPERATION_LABELS[operation]?.[language] ?? OPERATION_LABELS[operation]?.["en-US"] ?? operation;
}

function normalizePermissionLevelToken(value: string | null | undefined): PermissionLevel | undefined {
  const normalized = normalizeText(value).toLowerCase();
  if (!normalized) {
    return undefined;
  }

  const exactMatch = PERMISSION_LEVELS.find((level) => level === normalized);
  if (exactMatch) {
    return exactMatch;
  }

  return PERMISSION_LEVELS.find((level) => normalized.includes(level));
}

function formatPermissionBadge(
  permissionLabel: string | null | undefined,
  permissionLevel: string | null | undefined,
  allowedOperations: string[],
  language: WorkspaceAuthoritySurfaceLanguage,
): string {
  const level =
    normalizePermissionLevelToken(permissionLevel) ?? normalizePermissionLevelToken(permissionLabel);
  if (level) {
    return getPermissionLabel(level, language);
  }

  const localizedOperations = normalizeOperations(allowedOperations)
    .slice(0, language === "zh-CN" ? 2 : 3)
    .map((operation) => localizeOperation(operation, language))
    .filter(Boolean);
  if (localizedOperations.length > 0) {
    return localizedOperations.join(" / ");
  }

  return permissionLabel || permissionLevel || workspaceAuthorityPhrase(language, "unconfigured");
}

export function getPermissionLabel(
  level: PermissionLevel,
  language: WorkspaceAuthoritySurfaceLanguage,
): string {
  return LOCALIZED_PERMISSION_LEVEL_LABELS[level][language];
}

export function getPermissionDescription(
  level: PermissionLevel,
  language: WorkspaceAuthoritySurfaceLanguage,
): string {
  return LOCALIZED_PERMISSION_LEVEL_DESCRIPTIONS[level][language];

  const descriptions: Record<
    PermissionLevel,
    Record<WorkspaceAuthoritySurfaceLanguage, string>
  > = {
    inspect: {
      "zh-CN": "读取、列表、搜索、索引、预览、摘要",
      "en-US": "Read, list, search, index, preview, summarize",
      "es-ES": "Leer, listar, buscar, indexar, previsualizar, resumir",
      "fr-FR": "Lire, lister, rechercher, indexer, prévisualiser, résumer",
      "de-DE": "Lesen, auflisten, suchen, indexieren, Vorschau, zusammenfassen",
      "ja-JP": "読み取り、一覧、搜索、インデックス、プレビュー、要約",
      "ko-KR": "읽기, 목록, 검색, 인덱싱, 미리보기, 요약",
      "pt-BR": "Ler, listar, buscar, indexar, visualizar, resumir",
    },
    annotate: {
      "zh-CN": "写笔记、计划、证据，不改源码",
      "en-US": "Write notes, plans, evidence — no source code changes",
      "es-ES": "Escribir notas, planes, evidencia — sin cambios en código fuente",
      "fr-FR": "Écrire des notes, plans, preuves — sans modification du code source",
      "de-DE": "Notizen, Pläne, Beweise schreiben — keine Quellcode-Änderungen",
      "ja-JP": "メモ、計画、証拠を書く、ソースコードは変更しない",
      "ko-KR": "메모, 계획, 증거 작성 — 소스 코드 변경 없음",
      "pt-BR": "Escrever notas, planos, evidências — sem alterações no código-fonte",
    },
    reorganize: {
      "zh-CN": "新建目录、移动、重命名，在 root 内重组资料",
      "en-US": "mkdir/move/rename — reorganize within root",
      "es-ES": "mkdir/mover/renombrar — reorganizar dentro de root",
      "fr-FR": "mkdir/déplacer/renommer — réorganiser dans root",
      "de-DE": "mkdir/verschieben/umbenennen — innerhalb root neuorganisieren",
      "ja-JP": "mkdir/移動/名前変更 — root 内で再整理",
      "ko-KR": "mkdir/이동/이름 변경 — root 내에서 재구성",
      "pt-BR": "mkdir/mover/renomear — reorganizar dentro do root",
    },
    generate: {
      "zh-CN": "生成新文件、卡片、总结、脚本",
      "en-US": "Generate new files, cards, summaries, scripts",
      "es-ES": "Generar nuevos archivos, tarjetas, resúmenes, scripts",
      "fr-FR": "Générer de nouveaux fichiers, cartes, résumés, scripts",
      "de-DE": "Neue Dateien, Karten, Zusammenfassungen, Skripte generieren",
      "ja-JP": "新しいファイル、カード、まとめ、スクリプトを生成",
      "ko-KR": "새 파일, 카드, 요약, 스크립트 생성",
      "pt-BR": "Gerar novos arquivos, cartões, resumos, scripts",
    },
    apply: {
      "zh-CN": "修改已有文件",
      "en-US": "Modify existing files",
      "es-ES": "Modificar archivos existentes",
      "fr-FR": "Modifier les fichiers existants",
      "de-DE": "Vorhandene Dateien ändern",
      "ja-JP": "既存のファイルを修正",
      "ko-KR": "기존 파일 수정",
      "pt-BR": "Modificar arquivos existentes",
    },
    destructive: {
      "zh-CN": "删除、覆盖、批量移动 — 仅通过 trash / review 路径",
      "en-US": "Delete, overwrite, bulk move — via trash/review only",
      "es-ES": "Eliminar, sobrescribir, mover en masa — solo vía trash/review",
      "fr-FR": "Supprimer, écraser, déplacer en masse — via trash/review uniquement",
      "de-DE": "Löschen, überschreiben, Massenverschieben — nur über trash/review",
      "ja-JP": "削除、上書き、一括移動 — trash/review 経由のみ",
      "ko-KR": "삭제, 덮어쓰기, 대량 이동 — trash/review 경로만",
      "pt-BR": "Excluir, sobrescrever, mover em massa — apenas via trash/review",
    },
  };
  return descriptions[level][language];
}

export function getDefaultPermissionLevel(): PermissionLevel {
  return "annotate";
}

export function isPermissionLevelEnabled(
  enabled: PermissionLevel[],
  level: PermissionLevel,
): boolean {
  return enabled.includes(level);
}

export function enablePermissionLevel(
  enabled: PermissionLevel[],
  level: PermissionLevel,
): PermissionLevel[] {
  if (enabled.includes(level)) return enabled;
  return [...enabled, level].sort(
    (a, b) => PERMISSION_LEVEL_ORDER[a] - PERMISSION_LEVEL_ORDER[b],
  );
}

export function disablePermissionLevel(
  enabled: PermissionLevel[],
  level: PermissionLevel,
): PermissionLevel[] {
  if (level === "destructive") return enabled.filter((p) => p !== level);
  return enabled.filter((p) => p !== level && p !== "destructive");
}

export interface WorkspaceAuthoritySurfaceInput {
  activeWorkspaceRoot?: string | null;
  rootUri?: string | null;
  workspaceRootFallback?: string | null;
  authoritySource?: string | null;
  remoteName?: string | null;
  authorityMode?: string | null;
  permissionLevel?: string | null;
  permissionLabel?: string | null;
  allowedOperations?: string[] | null;
  mountedSources?: string[] | null;
  mountPoints?: string[] | null;
  ledgerEntryCount?: number | null;
  checkpointCount?: number | null;
  trashRoot?: string | null;
  trashRootFallback?: string | null;
  nextSafeAction?: string | null;
  enabledPermissions?: PermissionLevel[] | null;
}

export interface WorkspaceAuthoritySummaryView {
  hasWorkspaceRoot: boolean;
  root: string;
  rootDetail: string;
  source: string;
  sourceDetail: string;
  permission: string;
  permissionDetail: string;
  authorityMode: string;
  allowedOperations: string[];
  allowedOperationsText: string;
  mountedSources: string[];
  mountedSourceCount: number;
  mountedSourcesText: string;
  mountedSourcesDetail: string;
  ledgerEntryCount: number;
  checkpointCount: number;
  countsText: string;
  trashRoot: string;
  trashDetail: string;
  nextSafeAction: string;
  summaryText: string;
}

function text(language: WorkspaceAuthoritySurfaceLanguage, zh: string, en: string): string {
  return language === "zh-CN" ? zh : en;
}

function normalizeText(value: string | null | undefined): string {
  return typeof value === "string" ? value.trim() : "";
}

function joinParts(parts: Array<string | null | undefined>, language: WorkspaceAuthoritySurfaceLanguage): string {
  void language;
  return parts.filter((part): part is string => Boolean(part && part.trim())).join(" · ");
}

function normalizeOperations(items: string[] | null | undefined): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];
  for (const item of items ?? []) {
    const value = normalizeText(item);
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    normalized.push(value);
  }
  return normalized;
}

function normalizeMountedSources(items: string[] | null | undefined): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];
  for (const item of items ?? []) {
    const value = normalizeText(item);
    if (!value) {
      continue;
    }
    const key = value.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    normalized.push(value);
  }
  return normalized;
}

function normalizePermissionSignal(
  permissionLabel: string | null | undefined,
  permissionLevel: string | null | undefined,
): string {
  return [permissionLabel, permissionLevel]
    .map((part) => normalizeText(part).toLowerCase())
    .filter(Boolean)
    .join(" ")
    .replace(/[_/\\-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function inferAllowedOperationsFromAuthority(
  input: WorkspaceAuthoritySurfaceInput | null | undefined,
): string[] {
  const signal = normalizePermissionSignal(input?.permissionLabel, input?.permissionLevel);
  if (!signal) {
    return [];
  }

  const inferred = new Set<string>();
  const add = (...operations: string[]): void => {
    for (const operation of operations) {
      inferred.add(operation);
    }
  };

  if (
    signal.includes("destructive") ||
    signal.includes("delete") ||
    signal.includes("trash") ||
    signal.includes("restore")
  ) {
    add("delete", "restore");
    return [...inferred];
  }

  if (
    signal.includes("write") ||
    signal.includes("modify") ||
    signal.includes("apply") ||
    (signal.includes("read") && signal.includes("write"))
  ) {
    add("read", "write", "modify");
    return [...inferred];
  }

  if (signal.includes("generate") || signal.includes("create") || signal.includes("draft")) {
    add("generate");
    return [...inferred];
  }

  if (
    signal.includes("mkdir") ||
    signal.includes("move") ||
    signal.includes("rename") ||
    signal.includes("reorganize") ||
    signal.includes("organize")
  ) {
    add("mkdir", "move", "rename");
    return [...inferred];
  }

  if (signal.includes("annotate") || signal.includes("note") || signal.includes("plan") || signal.includes("evidence")) {
    add("annotate");
    return [...inferred];
  }

  if (
    signal.includes("inspect") ||
    signal.includes("read") ||
    signal.includes("list") ||
    signal.includes("search") ||
    signal.includes("index") ||
    signal.includes("preview") ||
    signal.includes("summarize")
  ) {
    add("read", "list", "search", "index", "preview", "summarize");
    return [...inferred];
  }

  return [];
}

function resolveAllowedOperations(
  input: WorkspaceAuthoritySurfaceInput | null | undefined,
  allowedOperations: string[],
): string[] {
  return allowedOperations.length > 0 ? allowedOperations : inferAllowedOperationsFromAuthority(input);
}

function formatMountedSourcesText(
  mountedSources: string[],
  language: WorkspaceAuthoritySurfaceLanguage,
): string {
  const count = mountedSources.length;
  if (count === 0) {
    return "";
  }
  return formatPhraseCount(workspaceAuthorityPhrase(language, "mountedSources"), count);

  if (language === "zh-CN") {
    return `${count} 个挂载来源`;
  }
  return count === 1 ? "1 mounted source" : `${count} mounted sources`;
}

function formatMountedSourcesDetail(mountedSources: string[]): string {
  return mountedSources.join(" | ");
}

function deriveNextSafeAction(
  input: WorkspaceAuthoritySurfaceInput | null | undefined,
  allowedOperations: string[],
  root: string,
  language: WorkspaceAuthoritySurfaceLanguage,
): string {
  if (!root) {
    return workspaceAuthorityPhrase(language, "openWorkspaceFirst");
  }

  if (!root) {
    return text(
      language,
      "先连接或打开工作区根目录，再让我读取边界并决定下一步。",
      "Open or connect a workspace root first so I can read the boundary and choose a next step.",
    );
  }

  const permissionLabel = normalizeText(input?.permissionLabel).toLowerCase();
  const permissionLevel = normalizeText(input?.permissionLevel).toLowerCase();
  const resolvedAllowedOperations = resolveAllowedOperations(input, allowedOperations);
  const hasAny = (...operations: string[]): boolean =>
    operations.some((operation) => resolvedAllowedOperations.includes(operation));
  const hasInspectOnly = !hasAny(
    "annotate",
    "mkdir",
    "move",
    "rename",
    "generate",
    "write",
    "modify",
    "delete",
    "restore",
  );
  if (hasInspectOnly || permissionLevel === "inspect" || permissionLabel.includes("inspect")) {
    return workspaceAuthorityPhrase(language, "inspectNext");
  }

  const legacyHasAnnotateOnly = hasAny("annotate") && !hasAny("mkdir", "move", "rename", "generate", "write", "modify", "delete", "restore");
  if (legacyHasAnnotateOnly || permissionLevel === "annotate" || permissionLabel.includes("annotate")) {
    return workspaceAuthorityPhrase(language, "annotateNext");
  }

  if (hasAny("delete", "restore") || permissionLevel === "destructive" || permissionLabel.includes("trash") || permissionLabel.includes("delete")) {
    return workspaceAuthorityPhrase(language, "destructiveNext");
  }

  if (hasAny("write", "modify") || permissionLevel === "apply" || permissionLabel.includes("write") || permissionLabel.includes("modify") || permissionLabel.includes("apply")) {
    return workspaceAuthorityPhrase(language, "applyNext");
  }

  if (hasAny("generate") || permissionLevel === "generate" || permissionLabel.includes("generate")) {
    return workspaceAuthorityPhrase(language, "generateNext");
  }

  if (hasAny("mkdir", "move", "rename") || permissionLevel === "reorganize" || permissionLabel.includes("mkdir") || permissionLabel.includes("move") || permissionLabel.includes("rename")) {
    return workspaceAuthorityPhrase(language, "reorganizeNext");
  }

  return workspaceAuthorityPhrase(language, "confirmBoundaryNext");

  if (hasInspectOnly || permissionLevel === "inspect" || permissionLabel.includes("inspect")) {
    return text(
      language,
      "先读取、搜索和预览最关键的资料，再把第一条可验证的任务挑出来。",
      "Start by reading, searching, and previewing the key material, then pick the first verifiable task.",
    );
  }

  const legacyHasAnnotateOnlyFallback =
    hasAny("annotate") &&
    !hasAny("mkdir", "move", "rename", "generate", "write", "modify", "delete", "restore");
  if (
    legacyHasAnnotateOnlyFallback ||
    permissionLevel === "annotate" ||
    permissionLabel.includes("annotate")
  ) {
    return text(
      language,
      "先把判断写成笔记、计划或证据，再决定要不要动源代码。",
      "Write the judgment down as notes, a plan, or evidence first, then decide whether source code should move.",
    );
  }

  if (hasAny("delete", "restore") || permissionLevel === "destructive" || permissionLabel.includes("trash") || permissionLabel.includes("delete")) {
    return text(
      language,
      "先把风险内容放进 trash 或 checkpoint，再执行这轮里最小的一步改动。",
      "Move risky content into trash or a checkpoint first, then make the smallest change in this round.",
    );
  }

  if (hasAny("write", "modify") || permissionLevel === "apply" || permissionLabel.includes("write") || permissionLabel.includes("modify") || permissionLabel.includes("apply")) {
    return text(
      language,
      "先做最薄的一次编辑，再立刻验证它是否真的站得住。",
      "Start with the thinnest edit, then verify immediately that it actually holds.",
    );
  }

  if (hasAny("generate") || permissionLevel === "generate" || permissionLabel.includes("generate")) {
    return text(
      language,
      "先生成最小可用的卡片、摘要或脚本，再检查它是不是贴合当前任务。",
      "Generate the smallest useful card, summary, or script first, then check whether it matches the current task.",
    );
  }

  if (hasAny("mkdir", "move", "rename") || permissionLevel === "reorganize" || permissionLabel.includes("mkdir") || permissionLabel.includes("move") || permissionLabel.includes("rename")) {
    return text(
      language,
      "先理顺工作区结构，再把当前任务放进更清晰的文件夹。",
      "First reorganize the workspace shape, then place the current task into a clearer folder.",
    );
  }

  return text(
    language,
    "先确认边界，再做最小的可验证动作。",
    "Confirm the boundary first, then make the smallest verifiable move.",
  );
}

export function describeWorkspaceAuthoritySummary(
  input: WorkspaceAuthoritySurfaceInput | null | undefined,
  language: WorkspaceAuthoritySurfaceLanguage,
): WorkspaceAuthoritySummaryView {
  const activeWorkspaceRoot = normalizeText(input?.activeWorkspaceRoot);
  const rootUri = normalizeText(input?.rootUri);
  const workspaceRootFallback = normalizeText(input?.workspaceRootFallback);
  const authoritySource = normalizeText(input?.authoritySource);
  const remoteName = normalizeText(input?.remoteName);
  const authorityMode = normalizeText(input?.authorityMode);
  const permissionLevel = normalizeText(input?.permissionLevel);
  const permissionLabel = normalizeText(input?.permissionLabel);
  const allowedOperations = normalizeOperations(input?.allowedOperations);
  const mountedSources = normalizeMountedSources([...(input?.mountedSources ?? []), ...(input?.mountPoints ?? [])]);
  const ledgerEntryCount = input?.ledgerEntryCount ?? 0;
  const checkpointCount = input?.checkpointCount ?? 0;
  const trashRoot = normalizeText(input?.trashRoot);
  const trashRootFallback = normalizeText(input?.trashRootFallback);
  const nextSafeActionOverride = normalizeText(input?.nextSafeAction);
  const root = activeWorkspaceRoot || rootUri || workspaceRootFallback;
  const resolvedAllowedOperations = root ? resolveAllowedOperations(input, allowedOperations) : allowedOperations;
  const source =
    authoritySource || (root ? "workspace_authority_service" : "") || remoteName || workspaceAuthorityPhrase(language, "unknownSource");
  const permission = formatPermissionBadge(
    permissionLabel,
    permissionLevel,
    resolvedAllowedOperations,
    language,
  );
  const mountedSourceCount = mountedSources.length;
  const mountedSourcesText = formatMountedSourcesText(mountedSources, language);
  const mountedSourcesDetail = formatMountedSourcesDetail(mountedSources);
  const rootDetail = joinParts([
    rootUri && rootUri !== root ? `rootUri: ${rootUri}` : null,
    source ? `source: ${source}` : null,
    remoteName && remoteName !== source ? `remote: ${remoteName}` : null,
  ], language);
  const sourceDetail = joinParts([
    authoritySource && authoritySource !== source ? `authoritySource: ${authoritySource}` : null,
    remoteName ? `remote: ${remoteName}` : null,
    authorityMode ? `mode: ${authorityMode}` : null,
  ], language);
  const permissionDetail = authorityMode || permissionLevel || "";
  const allowedOperationsText =
    resolvedAllowedOperations.length > 0
      ? resolvedAllowedOperations.slice(0, 6).map((operation) => localizeOperation(operation, language)).join(" / ")
      : "";
  const countsText = `${ledgerEntryCount} / ${checkpointCount}`;
  const trash = trashRoot || trashRootFallback;
  const trashDetail = trash ? `trash: ${trash}` : "";
  const nextSafeAction = nextSafeActionOverride || deriveNextSafeAction(input, resolvedAllowedOperations, root, language);
  const summaryText = joinParts([root, permission, source], language);

  return {
    hasWorkspaceRoot: Boolean(root),
    root,
    rootDetail,
    source,
    sourceDetail,
    permission,
    permissionDetail,
    authorityMode,
    allowedOperations: resolvedAllowedOperations,
    allowedOperationsText,
    mountedSources,
    mountedSourceCount,
    mountedSourcesText,
    mountedSourcesDetail,
    ledgerEntryCount,
    checkpointCount,
    countsText,
    trashRoot: trash,
    trashDetail,
    nextSafeAction,
    summaryText,
  };
}

/**
 * Returns the effective enabled permissions, falling back to defaults.
 * Reference: docs/open-source-fit-and-provider-strategy.md \u00a77.8
 */
export function getEffectiveEnabledPermissions(
  input: WorkspaceAuthoritySurfaceInput | null | undefined,
): PermissionLevel[] {
  return input?.enabledPermissions && input.enabledPermissions.length > 0
    ? input.enabledPermissions
    : DEFAULT_ENABLED_PERMISSIONS;
}
