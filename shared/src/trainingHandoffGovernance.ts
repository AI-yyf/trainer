import type { ComposerLanguage } from "./types";

function compact(value?: string): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  return normalized || undefined;
}

type TrainingNextHopLocaleCopy = {
  fallbackTitle: string;
  fallbackSummary: string;
  status: Record<string, string>;
  continueIn: Record<string, string>;
  projectScope: Record<string, string>;
  targetKind: {
    training: string;
    plan: string;
    review: string;
    fallback: string;
  };
  candidateType: Record<string, string>;
};

type TrainingNextHopLocaleLabelKind =
  | "fallback_title"
  | "fallback_summary"
  | "status"
  | "continue_in"
  | "project_scope"
  | "target_kind"
  | "candidate_type";

const trainingNextHopLocaleCopy: Record<ComposerLanguage, TrainingNextHopLocaleCopy> = {
  "zh-CN": {
    fallbackTitle: "下一步已成形",
    fallbackSummary: "下一步目标已由结构化证据明确记录。",
    status: {
      created: "已创建",
      surfaced: "已呈现",
      accepted: "已接受",
      continued_in_chat: "已回到对话",
      verification_required: "还需验证",
      reflection_required: "先复盘一下",
      return_required: "带回教练",
      dismissed: "已忽略",
      deferred: "已延后",
      blocked: "已阻塞",
      expired: "已过期",
      archived: "已归档",
    },
    continueIn: {
      chat: "回到对话",
      plan: "继续计划",
      training: "继续训练",
    },
    projectScope: {
      global: "全局",
      current_project: "当前项目",
      project_subplan: "项目子计划",
      sandbox: "沙箱",
      unknown: "未标记",
    },
    targetKind: {
      training: "训练卡片",
      plan: "计划证据",
      review: "复盘工件",
      fallback: "下一步",
    },
    candidateType: {
      evidence_candidate: "证据候选",
      flash_candidate: "闯关记忆",
      practice_candidate: "实战候选",
    },
  },
  "en-US": {
    fallbackTitle: "Next hop materialized",
    fallbackSummary: "The next hop is recorded as structured evidence.",
    status: {
      created: "Created",
      surfaced: "Surfaced",
      accepted: "Accepted",
      continued_in_chat: "Back in coach",
      verification_required: "Needs a check",
      reflection_required: "Reflect first",
      return_required: "Return to coach",
      dismissed: "Dismissed",
      deferred: "Deferred",
      blocked: "Blocked",
      expired: "Expired",
      archived: "Archived",
    },
    continueIn: {
      chat: "Return to coach",
      plan: "Continue in plan",
      training: "Continue in training",
    },
    projectScope: {
      global: "Global",
      current_project: "Current project",
      project_subplan: "Project subplan",
      sandbox: "Sandbox",
      unknown: "Unknown",
    },
    targetKind: {
      training: "Training card",
      plan: "Plan evidence",
      review: "Review artifact",
      fallback: "Next hop",
    },
    candidateType: {
      evidence_candidate: "Evidence candidate",
      flash_candidate: "Flash candidate",
      practice_candidate: "Practice candidate",
    },
  },
  "es-ES": {
    fallbackTitle: "Siguiente paso definido",
    fallbackSummary: "El siguiente paso se registró como evidencia estructurada.",
    status: {
      created: "Creado",
      surfaced: "Mostrado",
      accepted: "Aceptado",
      continued_in_chat: "De vuelta al coach",
      verification_required: "Pendiente de revisión",
      reflection_required: "Reflexiona primero",
      return_required: "Vuelve al coach",
      dismissed: "Descartado",
      deferred: "Aplazado",
      blocked: "Bloqueado",
      expired: "Vencido",
      archived: "Archivado",
    },
    continueIn: {
      chat: "Volver al coach",
      plan: "Continuar en el plan",
      training: "Continuar en el entrenamiento",
    },
    projectScope: {
      global: "Global",
      current_project: "Proyecto actual",
      project_subplan: "Subplan del proyecto",
      sandbox: "Entorno aislado",
      unknown: "Sin alcance",
    },
    targetKind: {
      training: "Tarjeta de entrenamiento",
      plan: "Evidencia del plan",
      review: "Artefacto de revisión",
      fallback: "Siguiente paso",
    },
    candidateType: {
      evidence_candidate: "Candidato de evidencia",
      flash_candidate: "Candidato de tarjeta",
      practice_candidate: "Candidato de práctica",
    },
  },
  "fr-FR": {
    fallbackTitle: "Prochaine étape définie",
    fallbackSummary: "La prochaine étape est enregistrée comme preuve structurée.",
    status: {
      created: "Créé",
      surfaced: "Affiché",
      accepted: "Accepté",
      continued_in_chat: "Retour au coach",
      verification_required: "À vérifier",
      reflection_required: "Réfléchir d'abord",
      return_required: "Retour au coach",
      dismissed: "Ignoré",
      deferred: "Reporté",
      blocked: "Bloqué",
      expired: "Expiré",
      archived: "Archivé",
    },
    continueIn: {
      chat: "Revenir au coach",
      plan: "Continuer dans le plan",
      training: "Continuer l'entraînement",
    },
    projectScope: {
      global: "Global",
      current_project: "Projet actuel",
      project_subplan: "Sous-plan du projet",
      sandbox: "Bac à sable",
      unknown: "Sans périmètre",
    },
    targetKind: {
      training: "Carte d'entraînement",
      plan: "Preuve du plan",
      review: "Artefact de revue",
      fallback: "Prochaine étape",
    },
    candidateType: {
      evidence_candidate: "Candidat de preuve",
      flash_candidate: "Candidat de carte mémoire",
      practice_candidate: "Candidat d'exercice",
    },
  },
  "de-DE": {
    fallbackTitle: "Nächster Schritt festgelegt",
    fallbackSummary: "Der nächste Schritt ist als strukturierter Nachweis erfasst.",
    status: {
      created: "Erstellt",
      surfaced: "Angezeigt",
      accepted: "Akzeptiert",
      continued_in_chat: "Zurück zum Coach",
      verification_required: "Prüfung ausstehend",
      reflection_required: "Erst reflektieren",
      return_required: "Zum Coach zurück",
      dismissed: "Verworfen",
      deferred: "Verschoben",
      blocked: "Blockiert",
      expired: "Abgelaufen",
      archived: "Archiviert",
    },
    continueIn: {
      chat: "Zurück zum Coach",
      plan: "Im Plan fortfahren",
      training: "Training fortsetzen",
    },
    projectScope: {
      global: "Global",
      current_project: "Aktuelles Projekt",
      project_subplan: "Projekt-Teilplan",
      sandbox: "Sandbox",
      unknown: "Ohne Bereich",
    },
    targetKind: {
      training: "Trainingskarte",
      plan: "Plan-Nachweis",
      review: "Review-Artefakt",
      fallback: "Nächster Schritt",
    },
    candidateType: {
      evidence_candidate: "Nachweis-Kandidat",
      flash_candidate: "Karteikarten-Kandidat",
      practice_candidate: "Übungskandidat",
    },
  },
  "ja-JP": {
    fallbackTitle: "次の一手を設定",
    fallbackSummary: "次の一手は構造化された証拠として記録されています。",
    status: {
      created: "作成済み",
      surfaced: "表示済み",
      accepted: "受け入れ済み",
      continued_in_chat: "コーチとの対話に戻る",
      verification_required: "確認待ち",
      reflection_required: "先に振り返る",
      return_required: "コーチに戻る",
      dismissed: "非表示",
      deferred: "保留中",
      blocked: "ブロック中",
      expired: "期限切れ",
      archived: "アーカイブ済み",
    },
    continueIn: {
      chat: "コーチとの対話に戻る",
      plan: "計画を続ける",
      training: "トレーニングを続ける",
    },
    projectScope: {
      global: "全体",
      current_project: "現在のプロジェクト",
      project_subplan: "プロジェクトのサブプラン",
      sandbox: "サンドボックス",
      unknown: "未指定",
    },
    targetKind: {
      training: "トレーニングカード",
      plan: "計画の証拠",
      review: "レビュー成果物",
      fallback: "次の一手",
    },
    candidateType: {
      evidence_candidate: "証拠候補",
      flash_candidate: "フラッシュカード候補",
      practice_candidate: "練習候補",
    },
  },
  "ko-KR": {
    fallbackTitle: "다음 단계가 준비됨",
    fallbackSummary: "다음 단계가 구조화된 근거로 기록되었습니다.",
    status: {
      created: "생성됨",
      surfaced: "표시됨",
      accepted: "수락됨",
      continued_in_chat: "코치 대화로 돌아감",
      verification_required: "확인 대기",
      reflection_required: "먼저 돌아보기",
      return_required: "코치에게 돌아가기",
      dismissed: "무시됨",
      deferred: "보류됨",
      blocked: "차단됨",
      expired: "만료됨",
      archived: "보관됨",
    },
    continueIn: {
      chat: "코치 대화로 돌아가기",
      plan: "계획에서 계속",
      training: "훈련 계속하기",
    },
    projectScope: {
      global: "전체",
      current_project: "현재 프로젝트",
      project_subplan: "프로젝트 하위 계획",
      sandbox: "샌드박스",
      unknown: "범위 미지정",
    },
    targetKind: {
      training: "훈련 카드",
      plan: "계획 근거",
      review: "리뷰 산출물",
      fallback: "다음 단계",
    },
    candidateType: {
      evidence_candidate: "근거 후보",
      flash_candidate: "플래시카드 후보",
      practice_candidate: "실습 후보",
    },
  },
  "pt-BR": {
    fallbackTitle: "Próxima etapa definida",
    fallbackSummary: "A próxima etapa foi registrada como evidência estruturada.",
    status: {
      created: "Criado",
      surfaced: "Exibido",
      accepted: "Aceito",
      continued_in_chat: "De volta ao coach",
      verification_required: "Aguardando verificação",
      reflection_required: "Reflita primeiro",
      return_required: "Volte ao coach",
      dismissed: "Descartado",
      deferred: "Adiado",
      blocked: "Bloqueado",
      expired: "Expirado",
      archived: "Arquivado",
    },
    continueIn: {
      chat: "Voltar ao coach",
      plan: "Continuar no plano",
      training: "Continuar no treinamento",
    },
    projectScope: {
      global: "Global",
      current_project: "Projeto atual",
      project_subplan: "Subplano do projeto",
      sandbox: "Sandbox",
      unknown: "Sem escopo",
    },
    targetKind: {
      training: "Cartão de treinamento",
      plan: "Evidência do plano",
      review: "Artefato de revisão",
      fallback: "Próxima etapa",
    },
    candidateType: {
      evidence_candidate: "Candidato de evidência",
      flash_candidate: "Candidato de cartão",
      practice_candidate: "Candidato de prática",
    },
  },
};

function normalizeTrainingNextHopLabelValue(value?: string): string | undefined {
  return compact(value)?.toLowerCase().replace(/-/g, "_");
}

export function localizeTrainingNextHopLabel(
  language: ComposerLanguage,
  kind: "fallback_title" | "fallback_summary",
): string;
export function localizeTrainingNextHopLabel(
  language: ComposerLanguage,
  kind: Exclude<TrainingNextHopLocaleLabelKind, "fallback_title" | "fallback_summary">,
  value?: string,
): string | undefined;
export function localizeTrainingNextHopLabel(
  language: ComposerLanguage,
  kind: TrainingNextHopLocaleLabelKind,
  value?: string,
): string | undefined {
  const copy = trainingNextHopLocaleCopy[language] ?? trainingNextHopLocaleCopy["en-US"];
  if (kind === "fallback_title") {
    return copy.fallbackTitle;
  }
  if (kind === "fallback_summary") {
    return copy.fallbackSummary;
  }

  const normalized = normalizeTrainingNextHopLabelValue(value);
  if (!normalized) {
    return undefined;
  }
  if (kind === "status") {
    return copy.status[normalized] ?? compact(value);
  }
  if (kind === "continue_in") {
    return copy.continueIn[normalized];
  }
  if (kind === "project_scope") {
    return copy.projectScope[normalized] ?? compact(value);
  }
  if (kind === "candidate_type") {
    return copy.candidateType[normalized];
  }
  if (normalized.includes("training")) {
    return copy.targetKind.training;
  }
  if (normalized.includes("plan")) {
    return copy.targetKind.plan;
  }
  if (normalized.includes("review")) {
    return copy.targetKind.review;
  }
  return copy.targetKind.fallback;
}
