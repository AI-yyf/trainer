import type { ComposerLanguage } from "../lib/types";

export type TrainerStageKind =
  | "retrieve"
  | "download"
  | "organize"
  | "cards"
  | "finalize"
  | "reason"
  | "think";

export type TrainerStage = {
  kind: TrainerStageKind;
  label: string;
};

// `inspect_file` is a label only: the stage stays `retrieve`, the line names the file being read.
type StageLabelKey = TrainerStageKind | "inspect_file";
type StageCopy = Record<TrainerStageKind, string> & { inspect_file: string };

const STAGE_COPY: Record<ComposerLanguage, StageCopy> = {
  "zh-CN": {
    retrieve: "正在检索资料",
    download: "正在下载资料",
    inspect_file: "正在查看 {file}",
    organize: "正在整理资料",
    cards: "正在生成训练卡",
    finalize: "正在整理回答",
    reason: "正在推演思路",
    think: "正在思考",
  },
  "en-US": {
    retrieve: "Searching resources",
    download: "Downloading a source",
    inspect_file: "Reading {file}",
    organize: "Organizing the library",
    cards: "Creating a training card",
    finalize: "Shaping the answer",
    reason: "Reasoning",
    think: "Thinking",
  },
  "es-ES": {
    retrieve: "Buscando recursos",
    download: "Descargando una fuente",
    inspect_file: "Leyendo {file}",
    organize: "Organizando la biblioteca",
    cards: "Creando una tarjeta",
    finalize: "Preparando la respuesta",
    reason: "Razonando",
    think: "Pensando",
  },
  "fr-FR": {
    retrieve: "Recherche des ressources",
    download: "Téléchargement d'une source",
    inspect_file: "Lecture de {file}",
    organize: "Organisation de la bibliothèque",
    cards: "Création d'une carte",
    finalize: "Préparation de la réponse",
    reason: "Raisonnement",
    think: "Réflexion",
  },
  "de-DE": {
    retrieve: "Ressourcen werden durchsucht",
    download: "Quelle wird geladen",
    inspect_file: "{file} wird gelesen",
    organize: "Bibliothek wird organisiert",
    cards: "Trainingskarte wird erstellt",
    finalize: "Antwort wird formuliert",
    reason: "Überlegt",
    think: "Denkt nach",
  },
  "ja-JP": {
    retrieve: "資料を検索中",
    download: "ソースをダウンロード中",
    inspect_file: "{file} を確認中",
    organize: "ライブラリを整理中",
    cards: "トレーニングカードを作成中",
    finalize: "回答を整えています",
    reason: "推論中",
    think: "考えています",
  },
  "ko-KR": {
    retrieve: "자료 검색 중",
    download: "소스 다운로드 중",
    inspect_file: "{file} 확인 중",
    organize: "라이브러리 정리 중",
    cards: "트레이닝 카드 생성 중",
    finalize: "답변 정리 중",
    reason: "추론 중",
    think: "생각 중",
  },
  "pt-BR": {
    retrieve: "Buscando recursos",
    download: "Baixando uma fonte",
    inspect_file: "Lendo {file}",
    organize: "Organizando a biblioteca",
    cards: "Criando um cartão",
    finalize: "Preparando a resposta",
    reason: "Raciocinando",
    think: "Pensando",
  },
};

const TOOL_STAGES: Record<string, TrainerStageKind> = {
  // 8 dual-domain orthogonal primitives (Trainer 2.0)
  project_read: "retrieve",
  project_verify: "retrieve",
  library_read: "retrieve",
  library_write: "organize",
  library_exec: "organize",
  web_fetch: "retrieve",
  learning_inspect: "retrieve",
  learning_action: "finalize",
  // Legacy transcript compatibility
  search_resources: "retrieve",
  list_resources: "retrieve",
  read_resource_excerpt: "retrieve",
  list_workspace_files: "retrieve",
  read_workspace_file: "retrieve",
  list_project_modules: "retrieve",
  read_project_symbol: "retrieve",
  analyze_project_impact: "retrieve",
  assess_research_evidence: "retrieve",
  list_sandbox: "retrieve",
  read_sandbox_file: "retrieve",
  web_search: "retrieve",
  search_academic_papers: "retrieve",
  fetch_web_page: "retrieve",
  list_library_folders: "retrieve",
  list_skills: "retrieve",
  invoke_skill: "reason",
  inspect_current_file: "retrieve",
  recall_memory: "retrieve",
  inspect_plan: "retrieve",
  inspect_learning_truth: "retrieve",
  search_learning_materials: "retrieve",
  compare_with_anchor: "retrieve",
  run_rubric_review: "retrieve",
  run_diagnostics: "retrieve",
  verify_practice_current_file: "retrieve",
  import_resource_url: "download",
  import_workspace_file: "download",
  organize_resources: "organize",
  curate_library_resources: "organize",
  delete_resource: "organize",
  restore_resource: "organize",
  refresh_resource_index: "organize",
  write_sandbox_file: "organize",
  index_sandbox_file: "organize",
  save_lecture_note: "organize",
  record_learning_note: "organize",
  generate_image: "finalize",
  generate_training_card: "cards",
  generate_cards: "cards",
  card_generation: "cards",
  coach_finalize: "finalize",
  save_formal_plan: "finalize",
  specify_task: "finalize",
  next_task: "finalize",
};

export function trainerStageKindForTool(
  toolName: string | undefined,
  args?: Record<string, unknown> | null,
): TrainerStageKind {
  const normalized = String(toolName ?? "").trim();
  const action =
    args && typeof args === "object" ? String(args.action ?? "").trim().toLowerCase() : "";
  if (normalized === "library_write") {
    if (action === "import_url" || action === "import_workspace") {
      return "download";
    }
    return "organize";
  }
  if (normalized === "web_fetch") {
    return action === "import_url" ? "download" : "retrieve";
  }
  if (normalized === "learning_action") {
    if (action === "invoke_skill") {
      return "reason";
    }
    if (action === "record_note") {
      return "organize";
    }
    return "finalize";
  }
  return TOOL_STAGES[normalized] ?? "think";
}

export function trainerStageLabel(kind: StageLabelKey, language: ComposerLanguage): string {
  return STAGE_COPY[language]?.[kind] ?? STAGE_COPY["en-US"][kind];
}

type ActivityLike = {
  name?: string;
  status?: string;
  args?: Record<string, unknown>;
};

/**
 * Prefer the currently running tool; once tools have finished, the model is
 * shaping the answer. An empty activity list is still a real "thinking" stage.
 */
/**
 * The single project file a running `project_read` is looking at, as a file name; empty for
 * listings, module maps and anything that is not a project read of one file. Only the name is
 * shown: a folder path says nothing a learner needs while waiting.
 */
function projectFileBeingRead(activity: ActivityLike): string {
  if (String(activity.name ?? "").trim() !== "project_read") {
    return "";
  }
  const args = activity.args;
  if (!args || typeof args !== "object") {
    return "";
  }
  const action = String(args.action ?? "").trim().toLowerCase();
  if (action && action !== "read" && action !== "inspect_current" && action !== "symbol") {
    return "";
  }
  const rawPath = String(args.path ?? "").trim().replace(/\\/g, "/");
  const name = rawPath.split("/").pop() ?? "";
  if (!name || name === "." || name === ".." || name.length > 80 || /\s/.test(name)) {
    return "";
  }
  return name;
}

export function currentTrainerStage(
  activities: readonly ActivityLike[] | undefined,
  language: ComposerLanguage,
  fallbackKind?: TrainerStageKind,
): TrainerStage {
  const list = activities ?? [];
  const running = [...list].reverse().find((activity) => activity.status === "running");
  const latest = running ?? [...list].reverse().find((activity) => activity.status === "succeeded");
  const kind = latest
    ? trainerStageKindForTool(latest.name, latest.args)
    : (fallbackKind ?? "think");
  // Real progress beats a generic stage (contract §5): while a project file is being read, say which.
  const file = running ? projectFileBeingRead(running) : "";
  if (file) {
    return { kind, label: trainerStageLabel("inspect_file", language).replace("{file}", file) };
  }
  return { kind, label: trainerStageLabel(kind, language) };
}
