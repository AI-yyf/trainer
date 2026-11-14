import type { ComposerLanguage } from "../lib/types";

export type TrainerStageKind =
  | "retrieve"
  | "download"
  | "organize"
  | "cards"
  | "finalize"
  | "waiting"
  | "responding"
  | "interrupted";

export type TrainerStage = {
  kind: TrainerStageKind;
  label: string;
};

type StageCopy = Record<TrainerStageKind, string>;

const STAGE_COPY: Record<ComposerLanguage, StageCopy> = {
  "zh-CN": {
    retrieve: "正在检索资料",
    download: "正在下载资料",
    organize: "正在整理资料",
    cards: "正在生成训练卡",
    finalize: "正在整理回答",
    waiting: "等待模型响应",
    responding: "正在回复",
    interrupted: "回复未完成",
  },
  "en-US": {
    retrieve: "Searching resources",
    download: "Downloading a source",
    organize: "Organizing the library",
    cards: "Creating a training card",
    finalize: "Shaping the answer",
    waiting: "Waiting for the model",
    responding: "Writing a reply",
    interrupted: "Incomplete reply",
  },
  "es-ES": {
    retrieve: "Buscando recursos",
    download: "Descargando una fuente",
    organize: "Organizando la biblioteca",
    cards: "Creando una tarjeta",
    finalize: "Preparando la respuesta",
    waiting: "Esperando al modelo",
    responding: "Redactando la respuesta",
    interrupted: "Respuesta incompleta",
  },
  "fr-FR": {
    retrieve: "Recherche des ressources",
    download: "Téléchargement d'une source",
    organize: "Organisation de la bibliothèque",
    cards: "Création d'une carte",
    finalize: "Préparation de la réponse",
    waiting: "En attente du modèle",
    responding: "Rédaction de la réponse",
    interrupted: "Réponse incomplète",
  },
  "de-DE": {
    retrieve: "Ressourcen werden durchsucht",
    download: "Quelle wird geladen",
    organize: "Bibliothek wird organisiert",
    cards: "Trainingskarte wird erstellt",
    finalize: "Antwort wird formuliert",
    waiting: "Wartet auf das Modell",
    responding: "Antwort wird geschrieben",
    interrupted: "Unvollständige Antwort",
  },
  "ja-JP": {
    retrieve: "資料を検索中",
    download: "ソースをダウンロード中",
    organize: "ライブラリを整理中",
    cards: "トレーニングカードを作成中",
    finalize: "回答を整えています",
    waiting: "モデルの応答を待っています",
    responding: "回答を作成中",
    interrupted: "未完了の回答",
  },
  "ko-KR": {
    retrieve: "자료 검색 중",
    download: "소스 다운로드 중",
    organize: "라이브러리 정리 중",
    cards: "트레이닝 카드 생성 중",
    finalize: "답변 정리 중",
    waiting: "모델 응답 대기 중",
    responding: "답변 작성 중",
    interrupted: "완료되지 않은 답변",
  },
  "pt-BR": {
    retrieve: "Buscando recursos",
    download: "Baixando uma fonte",
    organize: "Organizando a biblioteca",
    cards: "Criando um cartão",
    finalize: "Preparando a resposta",
    waiting: "Aguardando o modelo",
    responding: "Escrevendo a resposta",
    interrupted: "Resposta incompleta",
  },
};

const TOOL_STAGES: Record<string, TrainerStageKind> = {
  search_resources: "retrieve",
  list_resources: "retrieve",
  read_resource_excerpt: "retrieve",
  list_workspace_files: "retrieve",
  read_workspace_file: "retrieve",
  inspect_current_file: "retrieve",
  recall_memory: "retrieve",
  inspect_plan: "retrieve",
  search_learning_materials: "retrieve",
  compare_with_anchor: "retrieve",
  run_rubric_review: "retrieve",
  import_resource_url: "download",
  import_workspace_file: "download",
  organize_resources: "organize",
  delete_resource: "organize",
  restore_resource: "organize",
  refresh_resource_index: "organize",
  write_sandbox_file: "organize",
  index_sandbox_file: "organize",
  generate_training_card: "cards",
  generate_cards: "cards",
  card_generation: "cards",
  coach_finalize: "finalize",
  save_formal_plan: "finalize",
  specify_task: "finalize",
  next_task: "finalize",
};

export function trainerStageKindForTool(toolName: string | undefined): TrainerStageKind {
  return TOOL_STAGES[String(toolName ?? "").trim()] ?? "waiting";
}

export function trainerStageLabel(kind: TrainerStageKind, language: ComposerLanguage): string {
  return STAGE_COPY[language]?.[kind] ?? STAGE_COPY["en-US"][kind];
}

type ActivityLike = {
  name?: string;
  status?: string;
};

/**
 * Prefer the currently running tool and wait for a response when no known
 * work has been reported.
 */
export function currentTrainerStage(
  activities: readonly ActivityLike[] | undefined,
  language: ComposerLanguage,
): TrainerStage {
  const list = activities ?? [];
  const running = [...list].reverse().find((activity) => activity.status === "running");
  const latest = running ?? [...list].reverse().find((activity) => activity.status === "succeeded");
  const kind = latest ? trainerStageKindForTool(latest.name) : "waiting";
  return { kind, label: trainerStageLabel(kind, language) };
}
