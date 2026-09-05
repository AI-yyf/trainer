import type { TrainingSubmode } from "./models";
import type { ComposerLanguage } from "./types";
import { summarizeTrainingNextHopCopy } from "./coachLanguage";
import { summarizeNarrowSidebarLead } from "./trainingCardCopy";

/**
 * Shared TrainingNextHopSummary type used by both shared governance logic
 * and the webview UI. Mirrors the webview's TrainingNextHopSummary interface.
 */
export type TrainingNextHopSummary = {
  candidateId?: string;
  candidateType?: "evidence_candidate" | "flash_candidate" | "practice_candidate";
  title?: string;
  summary?: string;
  whyNow?: string;
  projectScope?: "global" | "current_project" | "project_subplan" | "sandbox" | "unknown";
  continueIn?: "chat" | "training" | "plan";
  targetKind?: string;
  targetId?: string;
  acceptedInto?: string;
  status?:
    | "created"
    | "surfaced"
    | "accepted"
    | "continued_in_chat"
    | "verification_required"
    | "reflection_required"
    | "return_required"
    | "dismissed"
    | "deferred"
    | "blocked"
    | "expired"
    | "archived";
  statusReason?: string;
  blockedBy?: string;
  handoffStatus?: string;
  handoffSummary?: string;
  coachOnly?: boolean;
  cardType?: "practice" | "flash";
  cardTitle?: string;
  scenarioPack?: string;
  returnMode?: "result" | "blocker" | "verification_required" | "reflection_required" | "return_required";
  returnSummary?: string;
  judgedAt?: string;
  reviewArtifactId?: string;
  reviewArtifactStatus?: string;
  reviewRecoveryMode?: string;
  planEvidenceId?: string;
  nextAfterCompletion?: string;
  fallbackAction?: string;
  sourceChain?: string[];
  /** Humanized training metrics (may not be present in all contexts) */
  streakDays?: number;
  cardsMastered?: number;
  practiceMinutes?: number;
  todayProgress?: number;
  nextReviewAt?: string;
};

type ConversationCandidateType =
  | "project_context_candidate"
  | "resource_import_candidate"
  | "evidence_candidate"
  | "flash_candidate"
  | "practice_candidate"
  | "coach_visible_status"
  | "micro_drill_prompt"
  | "card_invocation";

type BlockedTrainingCardCandidate = {
  cardId: string;
  type: "practice" | "flash";
  title: string;
  reasons: string[];
};

type ActiveTrainingCardRoutingSummary = {
  selectedCardId?: string;
  selectedCard?: {
    title?: string;
    type?: "practice" | "flash";
  };
  whyThisCard?: string;
  blockedCandidates?: BlockedTrainingCardCandidate[];
  fallbackAction?: string;
  candidateCount?: number;
  eligibleCount?: number;
};

export type TrainingEventLedgerEntrySummary = {
  eventType?: string;
  candidateId?: string;
  candidateStatus?: string;
  candidateStatusReason?: string;
  candidateContinueIn?: "chat" | "training" | "plan" | "resources" | "none";
  candidateType?: ConversationCandidateType;
  selectedCardId?: string;
  selectedCardType?: "practice" | "flash";
  selectedCardTitle?: string;
  cardCandidateId?: string;
  cardCandidateType?: "practice" | "flash";
  cardCandidateTitle?: string;
  whyThisCard?: string;
  learnerDeliverables?: string[];
  verificationSteps?: string[];
  successSignal?: string;
  returnWith?: string;
  nextAfterCompletion?: string;
  fallbackAction?: string;
  planEvidenceId?: string;
  reviewArtifactId?: string;
  reviewArtifactStatus?: string;
  reviewRecoveryMode?: string;
  judgedAt?: string;
  sourceChain?: string[];
  returnMode?: "result" | "blocker" | "verification_required" | "reflection_required" | "return_required";
  returnSummary?: string;
  candidateTargetKind?: string;
  candidateTargetId?: string;
  candidateProjectScope?: "global" | "current_project" | "project_subplan" | "sandbox" | "unknown";
  scenarioPack?: string;
  candidateBlockedBy?: string;
  candidateAcceptedInto?: string;
  candidateWhyNow?: string;
  candidateTitle?: string;
  statusSummary?: string;
  statusDetail?: string;
  statusKind?: string;
  blockedCandidates?: BlockedTrainingCardCandidate[];
  createdAt?: string;
};

type TrainingHandoffRecord = {
  candidateId?: string;
  candidateType?: ConversationCandidateType;
  targetKind?: string;
  targetId?: string;
  continueIn?: "chat" | "training" | "plan" | "resources" | "none";
  acceptedInto?: string;
  handoffStatus?: string;
  handoffSummary?: string;
  blockedBy?: string;
  coachOnly?: boolean;
  cardType?: "practice" | "flash";
  cardTitle?: string;
  scenarioPack?: string;
  learnerDeliverables?: string[];
  verificationSteps?: string[];
  successSignal?: string;
  returnWith?: string;
  nextAfterCompletion?: string;
  fallbackAction?: string;
};

type TrainingNextHopRecord = {
  candidateId?: string;
  candidateType?: "evidence_candidate" | "flash_candidate" | "practice_candidate";
  title?: string;
  summary?: string;
  whyNow?: string;
  projectScope?: "global" | "current_project" | "project_subplan" | "sandbox" | "unknown";
  continueIn?: "chat" | "training" | "plan";
  targetKind?: string;
  targetId?: string;
  acceptedInto?: string;
  status?:
    | "created"
    | "surfaced"
    | "accepted"
    | "continued_in_chat"
    | "verification_required"
    | "reflection_required"
    | "return_required"
    | "dismissed"
    | "deferred"
    | "blocked"
    | "expired"
    | "archived";
  statusReason?: string;
  blockedBy?: string;
  handoffStatus?: string;
  handoffSummary?: string;
  coachOnly?: boolean;
  cardType?: "practice" | "flash";
  cardTitle?: string;
  scenarioPack?: string;
  returnMode?: "result" | "blocker" | "verification_required" | "reflection_required" | "return_required";
  returnSummary?: string;
  judgedAt?: string;
  reviewArtifactId?: string;
  reviewArtifactStatus?: string;
  reviewRecoveryMode?: string;
  planEvidenceId?: string;
  nextAfterCompletion?: string;
  fallbackAction?: string;
  sourceChain?: string[];
};

export type TrainingHandoffInput = {
  latestTrainingHandoff?: TrainingHandoffRecord;
  latestConversationHandoff?: TrainingHandoffRecord;
  latestTrainingNextHop?: TrainingNextHopRecord;
  latestTrainingSubmode?: TrainingSubmode;
  selectedCardId?: string;
  selectedCardType?: "practice" | "flash";
  selectedCardTitle?: string;
  trainingCardCandidates?: Array<{
    id: string;
    type: "practice" | "flash";
    title: string;
    whyNow?: string;
  }>;
  activeTrainingCardRouting?: ActiveTrainingCardRoutingSummary;
  trainingEventLedger?: TrainingEventLedgerEntrySummary[];
};

export type ResolvedTrainingHandoff = {
  shouldRender: boolean;
  candidateId?: string;
  selectedCardId?: string;
  selectedCardTitle?: string;
  selectedCardType?: "practice" | "flash";
  targetId?: string;
  handoffStatus?: string;
  continueIn?: "chat" | "training" | "plan" | "resources" | "none";
  candidateType?: ConversationCandidateType;
  handoffSummary?: string;
  whyThisCard?: string;
  learnerDeliverables: string[];
  verificationSteps: string[];
  successSignal?: string;
  returnWith?: string;
  nextAfterCompletion?: string;
  fallbackAction?: string;
  blockedCandidate?: BlockedTrainingCardCandidate;
  blockedReason?: string;
  blockedCount: number;
  candidateCount: number;
  eligibleCount: number;
  blockedDueToResourceRisk: boolean;
  pausedByResourceRisk: boolean;
  resourceRiskReason?: string;
  coachOnly?: boolean;
  scenarioPack?: string;
  source: "training_handoff" | "conversation_handoff" | "ledger" | "none";
};

export type ResolvedTrainingNextHop = {
  shouldRender: boolean;
  hasRenderableCopy: boolean;
  hasStructuredTarget: boolean;
  candidateId?: string;
  candidateType?: "evidence_candidate" | "flash_candidate" | "practice_candidate";
  title?: string;
  summary?: string;
  whyNow?: string;
  projectScope?: "global" | "current_project" | "project_subplan" | "sandbox" | "unknown";
  continueIn?: "chat" | "training" | "plan";
  targetKind?: string;
  targetId?: string;
  acceptedInto?: string;
  status?:
    | "created"
    | "surfaced"
    | "accepted"
    | "continued_in_chat"
    | "verification_required"
    | "reflection_required"
    | "return_required"
    | "dismissed"
    | "deferred"
    | "blocked"
    | "expired"
    | "archived";
  statusReason?: string;
  blockedBy?: string;
  handoffStatus?: string;
  handoffSummary?: string;
  coachOnly?: boolean;
  cardType?: "practice" | "flash";
  cardTitle?: string;
  returnMode?: "result" | "blocker" | "verification_required" | "reflection_required" | "return_required";
  returnSummary?: string;
  judgedAt?: string;
  reviewArtifactId?: string;
  reviewArtifactStatus?: string;
  reviewRecoveryMode?: string;
  planEvidenceId?: string;
  nextAfterCompletion?: string;
  fallbackAction?: string;
  scenarioPack?: string;
  sourceChain: string[];
  canContinue: boolean;
  source: "latest_training_next_hop" | "training_event_ledger" | "none";
};

function compact(value?: string): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  return normalized || undefined;
}

function pickFirstText(...values: Array<string | undefined>): string | undefined {
  for (const value of values) {
    if (value) {
      return value;
    }
  }
  return undefined;
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

function buildStructuredNextHopCopy(
  language: ComposerLanguage,
  nextHop: Pick<
    TrainingNextHopRecord,
    "candidateType" | "continueIn" | "targetKind" | "status" | "statusReason" | "blockedBy" | "handoffSummary" | "nextAfterCompletion" | "fallbackAction" | "title" | "summary" | "cardTitle"
  >,
): { title?: string; summary?: string; detail?: string } {
  const title =
    compact(nextHop.title) ??
    compact(nextHop.cardTitle) ??
    localizeTrainingNextHopLabel(language, "continue_in", nextHop.continueIn) ??
    localizeTrainingNextHopLabel(language, "fallback_title");
  const summary =
    compact(nextHop.summary) ??
    localizeTrainingNextHopLabel(language, "target_kind", nextHop.targetKind) ??
    localizeTrainingNextHopLabel(language, "candidate_type", nextHop.candidateType) ??
    localizeTrainingNextHopLabel(language, "fallback_summary");
  const detail = summarizeNarrowSidebarLead(
    language,
    pickFirstText(
      nextHop.nextAfterCompletion,
      nextHop.handoffSummary,
      nextHop.statusReason,
      nextHop.blockedBy,
      nextHop.fallbackAction,
      nextHop.status ? `${nextHop.status}` : undefined,
    ),
    { maxLength: 88 },
  );
  return { title, summary, detail };
}

function findBlockedCandidate(
  blockedCandidates: BlockedTrainingCardCandidate[] | undefined,
  targetId?: string,
): BlockedTrainingCardCandidate | undefined {
  if (!targetId || !blockedCandidates?.length) {
    return undefined;
  }
  return blockedCandidates.find((item) => item.cardId === targetId);
}

function isResourceRiskReason(reason?: string): boolean {
  const normalized = compact(reason)?.toLowerCase();
  if (!normalized) {
    return false;
  }
  return normalized.includes("stale") ||
    normalized.includes("untrusted") ||
    (normalized.includes("resource") &&
      (normalized.includes("trust") || normalized.includes("fresh")));
}

function findResourceRiskBlockedCandidate(
  blockedCandidates: BlockedTrainingCardCandidate[] | undefined,
): BlockedTrainingCardCandidate | undefined {
  return blockedCandidates?.find((item) => item.reasons.some((reason) => isResourceRiskReason(reason)));
}

function resolveCardTitle(
  input: TrainingHandoffInput,
  targetId?: string,
  preferred?: string,
): string | undefined {
  const direct = compact(preferred);
  if (direct) {
    return direct;
  }
  const routingSelected = compact(input.activeTrainingCardRouting?.selectedCard?.title);
  if (routingSelected && input.activeTrainingCardRouting?.selectedCardId === targetId) {
    return routingSelected;
  }
  return compact(input.trainingCardCandidates?.find((item) => item.id === targetId)?.title);
}

function latestRelevantLedgerEntry(
  ledger: TrainingHandoffInput["trainingEventLedger"],
): TrainingEventLedgerEntrySummary | undefined {
  return [...(ledger ?? [])]
    .filter(
      (entry) =>
        entry.eventType === "conversation_candidate_handoff_executed" ||
        entry.eventType === "active_card_selected",
    )
    .sort((left, right) => {
      const leftTime = Date.parse(left.createdAt ?? "") || 0;
      const rightTime = Date.parse(right.createdAt ?? "") || 0;
      return rightTime - leftTime;
    })[0];
}

export function resolveTrainingHandoff(input: TrainingHandoffInput): ResolvedTrainingHandoff {
  const blockedCandidates = input.activeTrainingCardRouting?.blockedCandidates ?? [];
  const primary =
    input.latestTrainingHandoff?.continueIn === "training" ||
    input.latestTrainingHandoff?.targetKind === "training_card"
      ? input.latestTrainingHandoff
      : input.latestConversationHandoff?.continueIn === "training" ||
          input.latestConversationHandoff?.targetKind === "training_card"
        ? input.latestConversationHandoff
        : undefined;

  if (primary) {
    const targetId = compact(primary.targetId);
    const selectedCardId =
      compact(input.selectedCardId) ??
      targetId ??
      compact(input.activeTrainingCardRouting?.selectedCardId);
    const blockedCandidate =
      findBlockedCandidate(blockedCandidates, targetId) ??
      (blockedCandidates.length === 1 ? blockedCandidates[0] : undefined);
    const candidateCount =
      input.activeTrainingCardRouting?.candidateCount ?? input.trainingCardCandidates?.length ?? 0;
    const eligibleCount =
      input.activeTrainingCardRouting?.eligibleCount ??
      Math.max(0, candidateCount - blockedCandidates.length);
    const resourceRiskCandidate = findResourceRiskBlockedCandidate(blockedCandidates);
    const pausedBlockedCandidate =
      blockedCandidate?.reasons.some((reason) => isResourceRiskReason(reason))
        ? blockedCandidate
        : undefined;
    const resourceRiskReason =
      compact(pausedBlockedCandidate?.reasons.find((reason) => isResourceRiskReason(reason))) ??
      compact(resourceRiskCandidate?.reasons.find((reason) => isResourceRiskReason(reason)));
    const pausedByResourceRisk =
      Boolean(pausedBlockedCandidate) || (!selectedCardId && eligibleCount === 0 && Boolean(resourceRiskCandidate));
    return {
      shouldRender: true,
      candidateId: compact(primary.candidateId),
      selectedCardId,
      selectedCardTitle: resolveCardTitle(
        input,
        selectedCardId ?? targetId,
        input.selectedCardTitle ?? primary.cardTitle,
      ),
      selectedCardType:
        primary.cardType ?? input.selectedCardType ?? input.activeTrainingCardRouting?.selectedCard?.type,
      targetId,
      handoffStatus: compact(primary.handoffStatus),
      continueIn: primary.continueIn,
      candidateType: primary.candidateType,
      handoffSummary: compact(primary.handoffSummary),
      whyThisCard: compact(input.activeTrainingCardRouting?.whyThisCard),
      learnerDeliverables: primary.learnerDeliverables ?? [],
      verificationSteps: primary.verificationSteps ?? [],
      successSignal: compact(primary.successSignal),
      returnWith: compact(primary.returnWith),
      nextAfterCompletion: compact(primary.nextAfterCompletion),
      fallbackAction: compact(primary.fallbackAction),
      blockedCandidate,
      blockedReason:
        resourceRiskReason ??
        compact(blockedCandidate?.reasons?.[0]) ??
        compact(primary.blockedBy) ??
        compact(input.activeTrainingCardRouting?.fallbackAction),
      blockedCount: blockedCandidates.length,
      candidateCount,
      eligibleCount,
      blockedDueToResourceRisk: Boolean(resourceRiskCandidate),
      pausedByResourceRisk,
      resourceRiskReason,
      coachOnly: primary.coachOnly,
      scenarioPack: compact(primary.scenarioPack),
      source: primary === input.latestTrainingHandoff ? "training_handoff" : "conversation_handoff",
    };
  }

  const ledgerEntry = latestRelevantLedgerEntry(input.trainingEventLedger);
  if (!ledgerEntry) {
    return {
      shouldRender: false,
      learnerDeliverables: [],
      verificationSteps: [],
      blockedCount: blockedCandidates.length,
      candidateCount: input.activeTrainingCardRouting?.candidateCount ?? input.trainingCardCandidates?.length ?? 0,
      eligibleCount: input.activeTrainingCardRouting?.eligibleCount ?? 0,
      blockedDueToResourceRisk: Boolean(findResourceRiskBlockedCandidate(blockedCandidates)),
      pausedByResourceRisk: false,
      source: "none",
    };
  }

  const ledgerTargetId = compact(ledgerEntry.cardCandidateId) ?? compact(ledgerEntry.selectedCardId);
  const ledgerBlockedCandidates = blockedCandidates.length ? blockedCandidates : ledgerEntry.blockedCandidates;
  const blockedCandidate = findBlockedCandidate(ledgerBlockedCandidates, ledgerTargetId);
  const resourceRiskCandidate = findResourceRiskBlockedCandidate(ledgerBlockedCandidates);
  const pausedBlockedCandidate =
    blockedCandidate?.reasons.some((reason) => isResourceRiskReason(reason))
      ? blockedCandidate
      : undefined;
  const resourceRiskReason =
    compact(pausedBlockedCandidate?.reasons.find((reason) => isResourceRiskReason(reason))) ??
    compact(resourceRiskCandidate?.reasons.find((reason) => isResourceRiskReason(reason)));
  return {
    shouldRender: true,
    candidateId: compact(ledgerEntry.candidateId),
    selectedCardId: compact(input.selectedCardId) ?? compact(ledgerEntry.selectedCardId),
    selectedCardTitle:
      compact(input.selectedCardTitle) ??
      compact(ledgerEntry.selectedCardTitle) ??
      compact(ledgerEntry.cardCandidateTitle) ??
      resolveCardTitle(input, ledgerTargetId, input.selectedCardTitle),
    selectedCardType:
      input.selectedCardType ?? ledgerEntry.selectedCardType ?? ledgerEntry.cardCandidateType,
    targetId: compact(input.selectedCardId) ?? ledgerTargetId,
    handoffStatus: compact(ledgerEntry.candidateStatus),
    continueIn: ledgerEntry.candidateContinueIn,
    candidateType: ledgerEntry.candidateType,
    handoffSummary: compact(ledgerEntry.candidateStatusReason),
    whyThisCard:
      compact(ledgerEntry.whyThisCard) ?? compact(input.activeTrainingCardRouting?.whyThisCard),
    learnerDeliverables: ledgerEntry.learnerDeliverables ?? [],
    verificationSteps: ledgerEntry.verificationSteps ?? [],
    successSignal: compact(ledgerEntry.successSignal),
    returnWith: compact(ledgerEntry.returnWith),
    nextAfterCompletion: compact(ledgerEntry.nextAfterCompletion),
    fallbackAction: compact(ledgerEntry.fallbackAction),
    scenarioPack: compact(ledgerEntry.scenarioPack),
    blockedCandidate,
    blockedReason: resourceRiskReason ?? compact(blockedCandidate?.reasons?.[0]),
    blockedCount: ledgerBlockedCandidates?.length ?? 0,
    candidateCount: input.activeTrainingCardRouting?.candidateCount ?? input.trainingCardCandidates?.length ?? 0,
    eligibleCount: input.activeTrainingCardRouting?.eligibleCount ?? 0,
    blockedDueToResourceRisk: Boolean(resourceRiskCandidate),
    pausedByResourceRisk: Boolean(pausedBlockedCandidate),
    resourceRiskReason,
    source: "ledger",
  };
}

export function resolveTrainingNextHop(
  input: Pick<TrainingHandoffInput, "latestTrainingNextHop" | "trainingEventLedger"> & {
    language?: ComposerLanguage;
  },
): ResolvedTrainingNextHop {
  const latestNextHop = input.latestTrainingNextHop;
  const ledgerNextHop = [...(input.trainingEventLedger ?? [])]
    .filter((entry) => entry.eventType === "training_next_hop_materialized")
    .sort((left, right) => {
      const leftTime = Date.parse(left.createdAt ?? "") || 0;
      const rightTime = Date.parse(right.createdAt ?? "") || 0;
      return rightTime - leftTime;
    })[0];
  const nextHop: TrainingNextHopRecord | undefined = latestNextHop
    ? latestNextHop
    : ledgerNextHop
      ? {
          candidateId: compact(ledgerNextHop.candidateId),
          candidateType:
            ledgerNextHop.candidateType === "evidence_candidate" ||
            ledgerNextHop.candidateType === "flash_candidate" ||
            ledgerNextHop.candidateType === "practice_candidate"
              ? ledgerNextHop.candidateType
              : undefined,
          title: compact(ledgerNextHop.candidateTitle),
          summary: compact(ledgerNextHop.statusSummary ?? ledgerNextHop.statusDetail),
          whyNow: compact(ledgerNextHop.candidateWhyNow),
          projectScope: ledgerNextHop.candidateProjectScope,
          continueIn:
            ledgerNextHop.candidateContinueIn === "chat" ||
            ledgerNextHop.candidateContinueIn === "training" ||
            ledgerNextHop.candidateContinueIn === "plan"
              ? ledgerNextHop.candidateContinueIn
              : undefined,
          targetKind: compact(ledgerNextHop.candidateTargetKind),
          targetId: compact(ledgerNextHop.candidateTargetId),
          acceptedInto: compact(ledgerNextHop.candidateAcceptedInto),
          status:
            ledgerNextHop.candidateStatus === "created" ||
            ledgerNextHop.candidateStatus === "surfaced" ||
            ledgerNextHop.candidateStatus === "accepted" ||
            ledgerNextHop.candidateStatus === "continued_in_chat" ||
            ledgerNextHop.candidateStatus === "verification_required" ||
            ledgerNextHop.candidateStatus === "reflection_required" ||
            ledgerNextHop.candidateStatus === "return_required" ||
            ledgerNextHop.candidateStatus === "dismissed" ||
            ledgerNextHop.candidateStatus === "deferred" ||
            ledgerNextHop.candidateStatus === "blocked" ||
            ledgerNextHop.candidateStatus === "expired" ||
            ledgerNextHop.candidateStatus === "archived"
              ? ledgerNextHop.candidateStatus
              : undefined,
          statusReason: compact(ledgerNextHop.candidateStatusReason),
          blockedBy: compact(ledgerNextHop.candidateBlockedBy),
          handoffStatus: compact(ledgerNextHop.statusKind),
          handoffSummary: compact(ledgerNextHop.statusSummary),
          cardType:
            ledgerNextHop.selectedCardType === "practice" ||
            ledgerNextHop.selectedCardType === "flash"
              ? ledgerNextHop.selectedCardType
              : undefined,
          cardTitle:
            compact(ledgerNextHop.selectedCardTitle) ??
            compact(ledgerNextHop.cardCandidateTitle),
          scenarioPack: compact(ledgerNextHop.scenarioPack),
          returnMode: ledgerNextHop.returnMode,
          returnSummary: compact(ledgerNextHop.returnSummary),
          judgedAt: compact(ledgerNextHop.judgedAt),
          reviewArtifactId: compact(ledgerNextHop.reviewArtifactId),
          reviewArtifactStatus: compact(ledgerNextHop.reviewArtifactStatus),
          reviewRecoveryMode: compact(ledgerNextHop.reviewRecoveryMode),
          planEvidenceId: compact(ledgerNextHop.planEvidenceId),
          nextAfterCompletion: compact(ledgerNextHop.nextAfterCompletion),
          fallbackAction: compact(ledgerNextHop.fallbackAction),
          sourceChain: ledgerNextHop.sourceChain ?? [],
        }
      : undefined;
  if (!nextHop) {
    return {
      shouldRender: false,
      hasRenderableCopy: false,
      hasStructuredTarget: false,
      sourceChain: [],
      canContinue: false,
      source: "none",
    };
  }
  const source: ResolvedTrainingNextHop["source"] = latestNextHop
    ? "latest_training_next_hop"
    : "training_event_ledger";

  const language = input.language ?? "en-US";
  const hasExplicitCopy = Boolean(
    compact(nextHop.title) ||
      compact(nextHop.cardTitle) ||
      compact(nextHop.summary) ||
      compact(nextHop.returnSummary) ||
      compact(nextHop.handoffSummary) ||
      compact(nextHop.nextAfterCompletion) ||
      compact(nextHop.whyNow) ||
      compact(nextHop.statusReason) ||
      compact(nextHop.blockedBy) ||
      compact(nextHop.fallbackAction),
  );
  const compacted = hasExplicitCopy
    ? summarizeTrainingNextHopCopy(language, {
        title: compact(nextHop.title) ?? compact(nextHop.cardTitle) ?? compact(nextHop.summary),
        summary:
          compact(nextHop.summary) ??
          compact(nextHop.returnSummary) ??
          compact(nextHop.handoffSummary),
        nextAfterCompletion: compact(nextHop.nextAfterCompletion),
        whyNow: compact(nextHop.whyNow),
        statusReason: compact(nextHop.statusReason),
        blockedBy: compact(nextHop.blockedBy),
        handoffSummary: compact(nextHop.handoffSummary),
        fallbackAction: compact(nextHop.fallbackAction),
      })
    : buildStructuredNextHopCopy(language, {
        candidateType: nextHop.candidateType,
        continueIn: nextHop.continueIn,
        targetKind: compact(nextHop.targetKind),
        status: nextHop.status,
        statusReason: compact(nextHop.statusReason),
        blockedBy: compact(nextHop.blockedBy),
        handoffSummary: compact(nextHop.handoffSummary),
        nextAfterCompletion: compact(nextHop.nextAfterCompletion),
        fallbackAction: compact(nextHop.fallbackAction),
        title: compact(nextHop.title),
        summary: compact(nextHop.summary),
        cardTitle: compact(nextHop.cardTitle),
      });
  const title =
    compacted.title ??
    compact(nextHop.title) ??
    compact(nextHop.cardTitle) ??
    compact(nextHop.summary) ??
    localizeTrainingNextHopLabel(language, "continue_in", nextHop.continueIn) ??
    localizeTrainingNextHopLabel(language, "fallback_title");
  const summary =
    compacted.summary ??
    compact(nextHop.summary) ??
    compact(nextHop.returnSummary) ??
    compact(nextHop.handoffSummary) ??
    localizeTrainingNextHopLabel(language, "target_kind", nextHop.targetKind) ??
    localizeTrainingNextHopLabel(language, "candidate_type", nextHop.candidateType);
  const whyNow = compacted.detail ?? compact(nextHop.whyNow);
  const targetId = compact(nextHop.targetId);
  const targetKind = compact(nextHop.targetKind);
  const status = nextHop.status;
  const continueIn = nextHop.continueIn;
  const candidateType = nextHop.candidateType;
  const reviewArtifactId = compact(nextHop.reviewArtifactId);
  const planEvidenceId = compact(nextHop.planEvidenceId);
  const cardTitle = compact(nextHop.cardTitle);
  const hasRenderableCopy = Boolean(title || summary || whyNow || cardTitle);
  const hasStructuredTarget = Boolean(
    candidateType ||
      targetKind ||
      targetId ||
      continueIn ||
      status ||
      reviewArtifactId ||
      planEvidenceId,
  );
  const canContinue = Boolean(
    continueIn &&
      status &&
      [
        "created",
        "surfaced",
        "deferred",
        "blocked",
        "verification_required",
        "reflection_required",
        "return_required",
      ].includes(status),
  );

  return {
    shouldRender: hasStructuredTarget,
    hasRenderableCopy: Boolean(hasExplicitCopy || title || summary || whyNow),
    hasStructuredTarget,
    candidateId: compact(nextHop.candidateId),
    candidateType,
    title,
    summary,
    whyNow,
    projectScope: nextHop.projectScope,
    continueIn,
    targetKind,
    targetId,
    acceptedInto: compact(nextHop.acceptedInto),
    status,
    statusReason: compact(nextHop.statusReason),
    blockedBy: compact(nextHop.blockedBy),
    handoffStatus: compact(nextHop.handoffStatus),
    handoffSummary: compact(nextHop.handoffSummary),
    coachOnly: nextHop.coachOnly,
    cardType: nextHop.cardType,
    cardTitle,
    scenarioPack: compact(nextHop.scenarioPack),
    returnMode: nextHop.returnMode,
    returnSummary: compact(nextHop.returnSummary),
    judgedAt: compact(nextHop.judgedAt),
    reviewArtifactId,
    reviewArtifactStatus: compact(nextHop.reviewArtifactStatus),
    reviewRecoveryMode: compact(nextHop.reviewRecoveryMode),
    planEvidenceId,
    nextAfterCompletion: compact(nextHop.nextAfterCompletion),
    fallbackAction: compact(nextHop.fallbackAction),
    sourceChain: nextHop.sourceChain?.map((item) => item.trim()).filter(Boolean) ?? [],
    canContinue,
    source,
  };
}
