import { isValidElement, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  describeSafeStructuredValue,
  sanitizeErrorSurfaceText,
} from "../../../../../shared/src/errorSurfaceSanitizer";

import { ActionButton } from "../common";
import { CollapseSection } from "../common/CollapseSection";
import {
  CheckMarkIcon,
  ChevronDownIcon,
  ArrowRightIcon,
  LinkIcon,
  PlanIcon,
  RefreshIcon,
  TrashIcon,
  WarningIcon,
} from "../icons";
import { useTranslation } from "../../lib/i18n/useTranslation";
import { useWorkbenchState } from "../../app/useWorkbenchState";
import type {
  EvidenceItemView,
  EvidenceQueueView,
  GlobalPlan,
  PlanChangeCandidateView,
  GlobalPlanProjectLink,
  LearningPlan,
  PlanRuntimeReviewPoint,
  PlanStage,
  ReviewQueueItem,
  StageMaterialItem,
} from "../../lib/types";

export interface PlanReviewItem {
  id: string;
  title: string;
  detail?: string;
  meta?: string;
  surfaceMode?: "due" | "ahead" | "digest";
  taskHint?: string;
  focusArea?: string;
  linkedContext?: string[];
  intervalDays?: number;
  masteryScore?: number;
}

export interface PlanActionItem {
  id: string;
  label: string;
  detail?: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
  tone?: "accent" | "ghost";
  onClick?: () => void;
}

export interface PlanComposerDraftReplacementPrompt {
  source: "stage" | "project-subplan";
  title: string;
  detail: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export interface PlanGovernanceItem {
  id: string;
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: "neutral" | "good" | "warning" | "danger" | "muted";
}

export type ProjectSubplanStatus = "active" | "pending" | "blocked" | "frozen";

/**
 * A concise projection of a project subplan. Keep detailed stages and backend metadata
 * out of this view; selecting a row lets the owning surface open the fuller context.
 */
export interface ProjectSubplanView {
  id: string;
  title: string;
  status: ProjectSubplanStatus;
  nextStep?: string;
  blockedReason?: string;
  frozenReason?: string;
}

export interface EvidenceQueueActionHandlers {
  onRefreshQueue?: () => void;
  onAdoptEvidence?: (evidenceId: string) => void;
  onRejectEvidence?: (evidenceId: string, reason?: string) => void;
  onDeferEvidence?: (evidenceId: string, reason?: string) => void;
}

interface PlanDecisionStripState {
  tone: "good" | "warning" | "danger" | "muted";
  eyebrow: string;
  title: string;
  detail: string;
  next: string;
}

export interface CoachPlanViewProps {
  plan: LearningPlan | null;
  className?: string;
  eyebrow?: string;
  title?: string;
  titleNote?: ReactNode;
  composerDraftReplacement?: PlanComposerDraftReplacementPrompt;
  goalLabel?: string;
  goalSummary?: ReactNode;
  goalHint?: string;
  overviewLabel?: string;
  currentStageLabel?: string;
  liveStageIsCurrent?: boolean;
  nextStepLabel?: string;
  nextStepHint?: string;
  nextStepResumeThread?: string;
  summaryLabel?: string;
  cadenceLabel?: string;
  stagesLabel?: string;
  frozenLabel?: string;
  actionsLabel?: string;
  freezeStateLabel?: string;
  liveStateLabel?: string;
  memoryLabel?: string;
  winsLabel?: string;
  weakSpotsLabel?: string;
  reviewLabel?: string;
  coachingStateLabel?: string;
  coachingStateSummary?: ReactNode;
  trajectoryLabel?: string;
  trajectoryItems?: Array<{ id: string; label: string; value: ReactNode; detail?: ReactNode }>;
  pathLabel?: string;
  dueReviewItems?: PlanReviewItem[];
  dueReviewSummaryLabel?: string;
  reviewRhythm?: ReactNode;
  teachingObservationsLabel?: string;
  teachingObservations?: string[];
  emptyState?: ReactNode;
  actions?: PlanActionItem[];
  resumeActionLabel?: string;
  onResumeThread?: () => void;
  stageStatusLabels?: Partial<Record<PlanStage["status"], string>>;
  onStageSelect?: (stage: PlanStage) => void;
  nextStep?: ReactNode;
  memorySummary?: ReactNode;
  weakSpots?: string[];
  recentWins?: string[];
  supportSummaryLabel?: string;
  supportHint?: string;
  notesLabel?: string;
  whyNowLabel?: string;
  verifyLabel?: string;
  reviewWindowLabel?: string;
  pathHint?: string;
  whyNow?: ReactNode;
  verifyNow?: ReactNode;
  reviewWindow?: ReactNode;
  compactPrimary?: boolean;
  leftoverNote?: string;
  hideDecisionStrip?: boolean;
  planAtGlanceLabel?: string;
  planAtGlanceHint?: string;
  stageProgressLabel?: string;
  reviewQueueCountLabel?: string;
  currentFocusLabel?: string;
  reviewFocusLabel?: string;
  pathSummaryLabel?: string;
  pathSummaryHint?: string;
  returnLabel?: string;
  returnPath?: ReactNode;
  laterLabel?: string;
  detailsSummaryLabel?: string;
  currentStageHint?: string;
  nowLabel?: string;
  revisitSummaryLabel?: string;
  rememberedSummaryLabel?: string;
  rememberedSummary?: ReactNode;
  governanceLabel?: string;
  governanceItems?: PlanGovernanceItem[];
  evidenceQueue?: EvidenceQueueView;
  evidenceActions?: EvidenceQueueActionHandlers;
  planChangeCandidates?: readonly PlanChangeCandidateView[];
  onAcknowledgePlanChange?: (candidateId: string) => void;
  onRejectPlanChange?: (candidateId: string) => void;
  projectSubplans?: readonly ProjectSubplanView[];
  projectSubplansLabel?: string;
  projectSubplanStatusLabels?: Partial<Record<ProjectSubplanStatus, string>>;
  onProjectSubplanSelect?: (subplan: ProjectSubplanView) => void;
  globalPlan?: GlobalPlan;
  projectPlanLink?: GlobalPlanProjectLink;
  onCreateGlobalPlan?: () => void;
  onLinkCurrentProjectPlan?: () => void;
}

type PlanLanguage = ReturnType<typeof useTranslation>["language"];

function hasChinese(value: string | undefined): boolean {
  return Boolean(value && /[\u3400-\u9fff]/u.test(value));
}

type PlanCopyKey =
  | "done"
  | "active"
  | "notStarted"
  | "pending"
  | "blocked"
  | "frozen"
  | "blockerUnspecified"
  | "projectLaneFrozen"
  | "currentWorkInProgress"
  | "waitingMainPlan"
  | "lastStage"
  | "queuedStages"
  | "planBlocked"
  | "blockerDetailMissing"
  | "noPlanBlocker"
  | "backTo"
  | "narrowNext"
  | "needsConfirmation"
  | "evidenceUnchanged"
  | "chatEvidenceNoRewrite"
  | "verifyFirst"
  | "reviewPending"
  | "planLocked"
  | "formalPlanFrozen"
  | "formalPlan"
  | "evidence"
  | "blocker"
  | "clear"
  | "continueCurrent"
  | "ready"
  | "planReady"
  | "continueThread"
  | "emptyOutlineLabel"
  | "connectFirst"
  | "workingConnection"
  | "formalPlanHonest"
  | "formalThread"
  | "compressThread"
  | "noSilentMutation"
  | "emptyVerify"
  | "everyStepReturns"
  | "completionFlow"
  | "leftoverNotLive"
  | "leftoverOutlineMore";

const PLAN_COPY: Record<PlanLanguage, Record<PlanCopyKey, string>> = {
  "zh-CN": {
    done: "已完成",
    active: "进行中",
    notStarted: "未开始",
    pending: "待开始",
    blocked: "有卡点",
    frozen: "已锁定",
    blockerUnspecified: "还没有说明卡点。",
    projectLaneFrozen: "这条项目路线已锁定。",
    currentWorkInProgress: "当前工作正在进行。",
    waitingMainPlan: "正在等待主计划推进。",
    lastStage: "当前已经是最后一段。",
    queuedStages: "后面还有 {count} 段会继续推进。",
    planBlocked: "计划被卡住了",
    blockerDetailMissing: "还没有收到可执行的下一步。",
    noPlanBlocker: "目前没有计划卡点。",
    backTo: "回到：{step}",
    narrowNext: "先收束下一步。",
    needsConfirmation: "待确认",
    evidenceUnchanged: "证据还没有改写计划",
    chatEvidenceNoRewrite: "聊天证据不会静默重写正式计划。",
    verifyFirst: "先验证：{step}",
    reviewPending: "先处理待确认内容。",
    planLocked: "计划已锁定",
    formalPlanFrozen: "正式计划已锁定",
    formalPlan: "正式计划",
    evidence: "证据",
    blocker: "卡点",
    clear: "可推进",
    continueCurrent: "先继续当前步骤。",
    ready: "可推进",
    planReady: "计划可以前进了",
    continueThread: "继续当前主线。",
    emptyOutlineLabel: "计划会包含的内容",
    connectFirst: "先连通",
    workingConnection: "先启用一组可用连接",
    formalPlanHonest: "没有可用连接之前，正式计划不会假装已经开始。",
    formalThread: "正式主线",
    compressThread: "Coach 先压成一条主线",
    noSilentMutation: "先只保留一个当前动作，不把聊天静默改成正式计划。",
    emptyVerify: "怎么验",
    everyStepReturns: "做完先回到验证",
    completionFlow: "完成或受阻都会回流到正式计划。",
    leftoverNotLive: "这是此工作区里存下的旧痕迹，不是当前正式计划。",
    leftoverOutlineMore: "计划会怎么展开",
  },
  "en-US": {
    done: "Done",
    active: "Active",
    notStarted: "Not started",
    pending: "Pending",
    blocked: "Blocked",
    frozen: "Frozen",
    blockerUnspecified: "Blocker not specified.",
    projectLaneFrozen: "This project lane is frozen.",
    currentWorkInProgress: "Current work is in progress.",
    waitingMainPlan: "Waiting for the main plan.",
    lastStage: "You are already in the last stage.",
    queuedStages: "{count} more stages come after this.",
    planBlocked: "Plan is blocked",
    blockerDetailMissing: "No blocker detail is available.",
    noPlanBlocker: "No plan blocker is reported.",
    backTo: "Back to: {step}",
    narrowNext: "Narrow the next step first.",
    needsConfirmation: "Needs confirmation",
    evidenceUnchanged: "Evidence has not changed the plan",
    chatEvidenceNoRewrite: "Chat evidence will not rewrite it silently.",
    verifyFirst: "Verify first: {step}",
    reviewPending: "Review pending items first.",
    planLocked: "Plan locked",
    formalPlanFrozen: "Formal plan is frozen",
    formalPlan: "Formal plan",
    evidence: "Evidence",
    blocker: "Blocker",
    clear: "Clear",
    continueCurrent: "Continue the current step first.",
    ready: "Ready",
    planReady: "Plan can move",
    continueThread: "Continue the current thread.",
    emptyOutlineLabel: "What the plan will show",
    connectFirst: "Connect first",
    workingConnection: "Apply a working connection",
    formalPlanHonest: "The formal plan stays honest until a provider is actually usable.",
    formalThread: "Formal thread",
    compressThread: "Coach compresses one thread first",
    noSilentMutation: "It keeps one current move instead of silently turning chat into the formal plan.",
    emptyVerify: "Verify",
    everyStepReturns: "Every step returns to verification",
    completionFlow: "Completion or blockers both flow back into the formal plan.",
    leftoverNotLive: "This is stored leftover on this workspace, not the live plan.",
    leftoverOutlineMore: "What the plan will show",
  },
  "es-ES": {
    done: "Completado",
    active: "En curso",
    notStarted: "Sin iniciar",
    pending: "Pendiente",
    blocked: "Bloqueado",
    frozen: "Congelado",
    blockerUnspecified: "No se especificó el bloqueo.",
    projectLaneFrozen: "Esta ruta del proyecto está congelada.",
    currentWorkInProgress: "El trabajo actual está en curso.",
    waitingMainPlan: "Esperando el plan principal.",
    lastStage: "Ya estás en la última etapa.",
    queuedStages: "Quedan {count} etapas después de esta.",
    planBlocked: "El plan está bloqueado",
    blockerDetailMissing: "No hay detalles del bloqueo disponibles.",
    noPlanBlocker: "No se informa ningún bloqueo del plan.",
    backTo: "Volver a: {step}",
    narrowNext: "Aclara primero el siguiente paso.",
    needsConfirmation: "Necesita confirmación",
    evidenceUnchanged: "La evidencia aún no ha cambiado el plan",
    chatEvidenceNoRewrite: "La evidencia del chat no cambiará el plan formal en silencio.",
    verifyFirst: "Verifica primero: {step}",
    reviewPending: "Revisa primero los elementos pendientes.",
    planLocked: "Plan bloqueado",
    formalPlanFrozen: "El plan formal está congelado",
    formalPlan: "Plan formal",
    evidence: "Evidencia",
    blocker: "Bloqueo",
    clear: "Sin bloqueo",
    continueCurrent: "Continúa primero con el paso actual.",
    ready: "Listo",
    planReady: "El plan puede avanzar",
    continueThread: "Continúa con el hilo actual.",
    emptyOutlineLabel: "Lo que mostrará el plan",
    connectFirst: "Conecta primero",
    workingConnection: "Activa una conexión que funcione",
    formalPlanHonest: "El plan formal se mantiene honesto hasta que haya una conexión disponible.",
    formalThread: "Hilo formal",
    compressThread: "El coach concentra primero una sola línea",
    noSilentMutation: "Mantiene una sola acción actual y no convierte el chat en el plan formal sin avisar.",
    emptyVerify: "Verificar",
    everyStepReturns: "Cada paso vuelve a la verificación",
    completionFlow: "Los resultados y los bloqueos vuelven al plan formal.",
    leftoverNotLive: "Esto es un resto guardado en este espacio, no el plan en vivo.",
    leftoverOutlineMore: "Qué mostrará el plan",
  },
  "fr-FR": {
    done: "Terminé",
    active: "En cours",
    notStarted: "Pas commencé",
    pending: "En attente",
    blocked: "Bloqué",
    frozen: "Gelé",
    blockerUnspecified: "Le blocage n'est pas précisé.",
    projectLaneFrozen: "Cette piste de projet est gelée.",
    currentWorkInProgress: "Le travail en cours avance.",
    waitingMainPlan: "En attente du plan principal.",
    lastStage: "Vous êtes déjà à la dernière étape.",
    queuedStages: "Il reste {count} étapes après celle-ci.",
    planBlocked: "Le plan est bloqué",
    blockerDetailMissing: "Le détail du blocage n'est pas disponible.",
    noPlanBlocker: "Aucun blocage du plan n'est signalé.",
    backTo: "Retour à : {step}",
    narrowNext: "Précisez d'abord la prochaine étape.",
    needsConfirmation: "À confirmer",
    evidenceUnchanged: "La preuve n'a pas encore modifié le plan",
    chatEvidenceNoRewrite: "Les preuves du chat ne réécrivent pas le plan formel en silence.",
    verifyFirst: "Vérifiez d'abord : {step}",
    reviewPending: "Examinez d'abord les éléments en attente.",
    planLocked: "Plan verrouillé",
    formalPlanFrozen: "Le plan formel est gelé",
    formalPlan: "Plan formel",
    evidence: "Preuve",
    blocker: "Blocage",
    clear: "Sans blocage",
    continueCurrent: "Continuez d'abord l'étape actuelle.",
    ready: "Prêt",
    planReady: "Le plan peut avancer",
    continueThread: "Continuez le fil actuel.",
    emptyOutlineLabel: "Ce que montrera le plan",
    connectFirst: "Connectez-vous d'abord",
    workingConnection: "Activez une connexion utilisable",
    formalPlanHonest: "Le plan formel reste honnête tant qu'aucune connexion n'est utilisable.",
    formalThread: "Fil formel",
    compressThread: "Le coach concentre d'abord un seul fil",
    noSilentMutation: "Il garde une seule action actuelle sans transformer silencieusement le chat en plan formel.",
    emptyVerify: "Vérifier",
    everyStepReturns: "Chaque étape revient à la vérification",
    completionFlow: "Les résultats comme les blocages reviennent au plan formel.",
    leftoverNotLive: "Ceci est un reste enregistré sur cet espace, pas le plan actuel.",
    leftoverOutlineMore: "Ce que le plan montrera",
  },
  "de-DE": {
    done: "Erledigt",
    active: "Aktiv",
    notStarted: "Nicht begonnen",
    pending: "Ausstehend",
    blocked: "Blockiert",
    frozen: "Eingefroren",
    blockerUnspecified: "Der Blocker wurde nicht beschrieben.",
    projectLaneFrozen: "Dieser Projektpfad ist eingefroren.",
    currentWorkInProgress: "Die aktuelle Arbeit läuft.",
    waitingMainPlan: "Wartet auf den Hauptplan.",
    lastStage: "Sie befinden sich bereits in der letzten Phase.",
    queuedStages: "Nach dieser folgen noch {count} Phasen.",
    planBlocked: "Der Plan ist blockiert",
    blockerDetailMissing: "Es gibt keine Details zum Blocker.",
    noPlanBlocker: "Es wurde kein Plan-Blocker gemeldet.",
    backTo: "Zurück zu: {step}",
    narrowNext: "Grenzen Sie zuerst den nächsten Schritt ein.",
    needsConfirmation: "Bestätigung nötig",
    evidenceUnchanged: "Die Evidenz hat den Plan noch nicht geändert",
    chatEvidenceNoRewrite: "Chat-Evidenz schreibt den formellen Plan nicht stillschweigend um.",
    verifyFirst: "Zuerst prüfen: {step}",
    reviewPending: "Prüfen Sie zuerst die offenen Punkte.",
    planLocked: "Plan gesperrt",
    formalPlanFrozen: "Der formelle Plan ist eingefroren",
    formalPlan: "Formeller Plan",
    evidence: "Evidenz",
    blocker: "Blocker",
    clear: "Frei",
    continueCurrent: "Fahren Sie zuerst mit dem aktuellen Schritt fort.",
    ready: "Bereit",
    planReady: "Der Plan kann weitergehen",
    continueThread: "Setzen Sie den aktuellen Pfad fort.",
    emptyOutlineLabel: "Was der Plan zeigen wird",
    connectFirst: "Zuerst verbinden",
    workingConnection: "Eine nutzbare Verbindung aktivieren",
    formalPlanHonest: "Der formelle Plan bleibt ehrlich, bis eine Verbindung wirklich nutzbar ist.",
    formalThread: "Formeller Pfad",
    compressThread: "Der Coach verdichtet zuerst einen Pfad",
    noSilentMutation: "Er hält eine aktuelle Aktion fest und macht aus dem Chat nicht stillschweigend einen formellen Plan.",
    emptyVerify: "Prüfen",
    everyStepReturns: "Jeder Schritt führt zurück zur Prüfung",
    completionFlow: "Ergebnisse und Blocker fließen beide zurück in den formellen Plan.",
    leftoverNotLive: "Das ist ein gespeicherter Rest in diesem Arbeitsbereich, nicht der aktuelle Plan.",
    leftoverOutlineMore: "Was der Plan zeigen wird",
  },
  "ja-JP": {
    done: "完了",
    active: "進行中",
    notStarted: "未開始",
    pending: "保留中",
    blocked: "停止中",
    frozen: "固定済み",
    blockerUnspecified: "停止理由はまだ説明されていません。",
    projectLaneFrozen: "このプロジェクトの経路は固定されています。",
    currentWorkInProgress: "現在の作業を進めています。",
    waitingMainPlan: "メイン計画の進行を待っています。",
    lastStage: "すでに最後のステージです。",
    queuedStages: "この後に {count} ステージあります。",
    planBlocked: "計画が止まっています",
    blockerDetailMissing: "停止理由の詳細はまだありません。",
    noPlanBlocker: "計画の停止理由は報告されていません。",
    backTo: "戻る：{step}",
    narrowNext: "次の一手を先に絞り込みます。",
    needsConfirmation: "確認待ち",
    evidenceUnchanged: "証拠はまだ計画を変えていません",
    chatEvidenceNoRewrite: "チャットの証拠で正式な計画を書き換えることはありません。",
    verifyFirst: "先に確認：{step}",
    reviewPending: "保留中の項目を先に確認します。",
    planLocked: "計画は固定されています",
    formalPlanFrozen: "正式な計画は固定されています",
    formalPlan: "正式な計画",
    evidence: "証拠",
    blocker: "停止理由",
    clear: "問題なし",
    continueCurrent: "現在のステップを先に続けます。",
    ready: "進められます",
    planReady: "計画を進められます",
    continueThread: "現在の流れを続けます。",
    emptyOutlineLabel: "計画に表示される内容",
    connectFirst: "先に接続",
    workingConnection: "使える接続を有効にする",
    formalPlanHonest: "使える接続ができるまで、正式な計画が始まったふりをしません。",
    formalThread: "正式な流れ",
    compressThread: "Coach はまず一つの流れにまとめます",
    noSilentMutation: "現在の行動を一つに絞り、チャットを正式な計画に勝手に変えません。",
    emptyVerify: "確認方法",
    everyStepReturns: "各ステップは確認に戻ります",
    completionFlow: "完了と停止のどちらも正式な計画に戻ります。",
    leftoverNotLive: "これはこのワークスペースに残った記録であり、現在の正式な計画ではありません。",
    leftoverOutlineMore: "計画に含まれる内容",
  },
  "ko-KR": {
    done: "완료",
    active: "진행 중",
    notStarted: "시작 전",
    pending: "대기 중",
    blocked: "막힘",
    frozen: "고정됨",
    blockerUnspecified: "막힌 이유가 아직 설명되지 않았습니다.",
    projectLaneFrozen: "이 프로젝트 경로는 고정되어 있습니다.",
    currentWorkInProgress: "현재 작업을 진행하고 있습니다.",
    waitingMainPlan: "주 계획의 진행을 기다리고 있습니다.",
    lastStage: "이미 마지막 단계입니다.",
    queuedStages: "이후에 {count}단계가 더 남아 있습니다.",
    planBlocked: "계획이 막혔습니다",
    blockerDetailMissing: "막힌 이유의 세부 정보가 없습니다.",
    noPlanBlocker: "계획이 막혔다는 보고가 없습니다.",
    backTo: "돌아가기: {step}",
    narrowNext: "다음 단계를 먼저 좁혀 보세요.",
    needsConfirmation: "확인 필요",
    evidenceUnchanged: "증거가 아직 계획을 바꾸지 않았습니다",
    chatEvidenceNoRewrite: "대화 증거가 공식 계획을 조용히 바꾸지 않습니다.",
    verifyFirst: "먼저 확인: {step}",
    reviewPending: "보류 중인 항목을 먼저 확인하세요.",
    planLocked: "계획이 고정되었습니다",
    formalPlanFrozen: "공식 계획이 고정되었습니다",
    formalPlan: "공식 계획",
    evidence: "증거",
    blocker: "막힌 이유",
    clear: "문제 없음",
    continueCurrent: "현재 단계를 먼저 계속하세요.",
    ready: "진행 가능",
    planReady: "계획을 진행할 수 있습니다",
    continueThread: "현재 흐름을 계속하세요.",
    emptyOutlineLabel: "계획에 표시될 내용",
    connectFirst: "먼저 연결",
    workingConnection: "사용 가능한 연결 활성화",
    formalPlanHonest: "사용 가능한 연결이 있기 전에는 공식 계획이 시작된 것처럼 보이지 않습니다.",
    formalThread: "공식 흐름",
    compressThread: "Coach가 먼저 하나의 흐름으로 정리합니다",
    noSilentMutation: "현재 행동 하나만 남기고 대화를 공식 계획으로 조용히 바꾸지 않습니다.",
    emptyVerify: "확인 방법",
    everyStepReturns: "각 단계는 확인으로 돌아갑니다",
    completionFlow: "완료와 막힘 모두 공식 계획으로 돌아갑니다.",
    leftoverNotLive: "이건 이 작업 공간에 남은 기록이지, 현재 공식 계획이 아닙니다.",
    leftoverOutlineMore: "계획에 담길 내용",
  },
  "pt-BR": {
    done: "Concluído",
    active: "Em andamento",
    notStarted: "Não iniciado",
    pending: "Pendente",
    blocked: "Bloqueado",
    frozen: "Congelado",
    blockerUnspecified: "O bloqueio não foi informado.",
    projectLaneFrozen: "Esta trilha do projeto está congelada.",
    currentWorkInProgress: "O trabalho atual está em andamento.",
    waitingMainPlan: "Aguardando o plano principal.",
    lastStage: "Você já está no último estágio.",
    queuedStages: "Há mais {count} estágios depois deste.",
    planBlocked: "O plano está bloqueado",
    blockerDetailMissing: "Não há detalhes sobre o bloqueio.",
    noPlanBlocker: "Nenhum bloqueio do plano foi informado.",
    backTo: "Voltar para: {step}",
    narrowNext: "Defina primeiro o próximo passo.",
    needsConfirmation: "Precisa de confirmação",
    evidenceUnchanged: "A evidência ainda não mudou o plano",
    chatEvidenceNoRewrite: "A evidência da conversa não reescreve o plano formal silenciosamente.",
    verifyFirst: "Verifique primeiro: {step}",
    reviewPending: "Revise primeiro os itens pendentes.",
    planLocked: "Plano bloqueado",
    formalPlanFrozen: "O plano formal está congelado",
    formalPlan: "Plano formal",
    evidence: "Evidência",
    blocker: "Bloqueio",
    clear: "Sem bloqueio",
    continueCurrent: "Continue primeiro a etapa atual.",
    ready: "Pronto",
    planReady: "O plano pode avançar",
    continueThread: "Continue o fluxo atual.",
    emptyOutlineLabel: "O que o plano mostrará",
    connectFirst: "Conecte primeiro",
    workingConnection: "Ative uma conexão que funcione",
    formalPlanHonest: "O plano formal permanece honesto até haver uma conexão utilizável.",
    formalThread: "Fluxo formal",
    compressThread: "O coach concentra primeiro um único fluxo",
    noSilentMutation: "Ele mantém uma ação atual e não transforma a conversa em plano formal silenciosamente.",
    emptyVerify: "Verificar",
    everyStepReturns: "Cada etapa volta para a verificação",
    completionFlow: "Resultados e bloqueios voltam ao plano formal.",
    leftoverNotLive: "Isto é um resto guardado neste espaço, não o plano ao vivo.",
    leftoverOutlineMore: "O que o plano vai mostrar",
  },
};

function planCopy(
  language: PlanLanguage,
  key: PlanCopyKey,
  values: Record<string, string | number> = {},
): string {
  return Object.entries(values).reduce(
    (copy, [name, value]) => copy.replace(`{${name}}`, String(value)),
    PLAN_COPY[language][key],
  );
}

function defaultStageLabel(status: PlanStage["status"], language: PlanLanguage): string {
  if (status === "done") {
    return planCopy(language, "done");
  }
  if (status === "active") {
    return planCopy(language, "active");
  }
  return status === "queued" ? planCopy(language, "pending") : planCopy(language, "notStarted");
}

function resolveStageStatusLabel(
  status: PlanStage["status"],
  suppliedLabel: string | undefined,
  language: PlanLanguage,
): string {
  const label = suppliedLabel?.trim();
  const englishFallback =
    status === "done" ? "Done" : status === "active" ? "Active" : status === "queued" ? "Queued" : undefined;
  if (label && !(language !== "en-US" && label === englishFallback)) {
    return label;
  }
  return defaultStageLabel(status, language);
}

function defaultProjectSubplanStatusLabel(
  status: ProjectSubplanStatus,
  language: PlanLanguage,
): string {
  if (status === "active") {
    return planCopy(language, "active");
  }
  if (status === "pending") {
    return planCopy(language, "pending");
  }
  if (status === "blocked") {
    return planCopy(language, "blocked");
  }
  return planCopy(language, "frozen");
}

function projectSubplanDetail(subplan: ProjectSubplanView, language: PlanLanguage): string {
  if (subplan.status === "blocked") {
    return subplan.blockedReason?.trim() || planCopy(language, "blockerUnspecified");
  }
  if (subplan.status === "frozen") {
    return subplan.frozenReason?.trim() || planCopy(language, "projectLaneFrozen");
  }
  if (subplan.nextStep?.trim()) {
    return subplan.nextStep.trim();
  }
  return subplan.status === "active"
    ? planCopy(language, "currentWorkInProgress")
    : planCopy(language, "waitingMainPlan");
}

function formatQueuedStageSummary(count: number, language: PlanLanguage): string {
  if (count <= 0) {
    return planCopy(language, "lastStage");
  }
  return planCopy(language, "queuedStages", { count });
}

function surfaceModeLabel(
  mode: PlanReviewItem["surfaceMode"],
  isChinese: boolean,
): string | undefined {
  if (mode === "ahead") {
    return isChinese ? "\u63d0\u524d\u63d0\u9192" : "Ahead";
  }
  if (mode === "digest") {
    return isChinese ? "\u5408\u5e76\u56de\u770b" : "Digest";
  }
  if (mode === "due") {
    return isChinese ? "\u5230\u671f\u56de\u770b" : "Due";
  }
  return undefined;
}

function masteryLabel(score: number | undefined, isChinese: boolean): string | undefined {
  if (typeof score !== "number" || Number.isNaN(score)) {
    return undefined;
  }
  const percent = `${Math.round(score * 100)}%`;
  return isChinese ? `\u638c\u63e1\u5ea6 ${percent}` : `Mastery ${percent}`;
}

function intervalLabel(days: number | undefined, isChinese: boolean): string | undefined {
  if (typeof days !== "number" || Number.isNaN(days)) {
    return undefined;
  }
  return isChinese ? `${days} \u5929\u95f4\u9694` : `${days}-day interval`;
}

function compactReviewMeta(item: PlanReviewItem, isChinese: boolean): string | undefined {
  const meta = [
    item.meta,
    surfaceModeLabel(item.surfaceMode, isChinese),
    intervalLabel(item.intervalDays, isChinese),
    masteryLabel(item.masteryScore, isChinese),
  ].filter(Boolean) as string[];
  return meta.length > 0 ? meta.join(" · ") : undefined;
}

function compactReviewLane(item: PlanReviewItem, isChinese: boolean): string {
  const lead =
    item.taskHint ??
    item.focusArea ??
    item.detail ??
    (isChinese
      ? "\u505a\u5b8c\u5f53\u524d\u5207\u7247\u540e\uff0c\u518d\u5b89\u6392\u8fd9\u6b21\u56de\u770b\u3002"
      : "Schedule this revisit after the current slice lands.");
  const context = item.linkedContext?.slice(0, 2).join(" · ");
  return [lead, context].filter(Boolean).join(" · ");
}

function isTextNode(value: ReactNode): value is string | number {
  return typeof value === "string" || typeof value === "number";
}

function nodeText(value: ReactNode | undefined): string {
  if (value === undefined || value === null || typeof value === "boolean") {
    return "";
  }
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => nodeText(item)).filter(Boolean).join(" ");
  }
  if (isValidElement<{ children?: ReactNode }>(value)) {
    return nodeText(value.props.children);
  }
  return "";
}

function renderNodeWithParagraph(value: ReactNode): ReactNode {
  return isTextNode(value) ? <p>{value}</p> : value;
}

function inlineText(value: ReactNode | undefined, fallback = ""): string {
  return nodeText(value).replace(/\s+/g, " ").trim() || fallback;
}

function findGovernanceItem(items: PlanGovernanceItem[], id: string): PlanGovernanceItem | undefined {
  return items.find((item) => item.id === id);
}

function formatEvidenceSource(value: string, t: (key: string) => string): string {
  const normalized = value.trim();
  if (normalized === "card_result") {
    return t("evidenceSourceCardResult");
  }
  if (normalized === "learning_signal") {
    return t("evidenceSourceLearningSignal");
  }
  if (normalized === "coaching_observation") {
    return t("evidenceSourceCoachingObservation");
  }
  if (normalized === "resource_import") {
    return t("evidenceSourceResourceImport");
  }
  if (normalized === "review_queue") {
    return t("evidenceSourceReviewQueue");
  }
  return normalized.replace(/_/g, " ");
}

function formatEvidenceOutcome(value: string, t: (key: string) => string): string {
  const normalized = value.trim();
  if (normalized === "pass") {
    return t("evidenceOutcomePass");
  }
  if (normalized === "partial") {
    return t("evidenceOutcomePartial");
  }
  if (normalized === "fail") {
    return t("evidenceOutcomeFail");
  }
  if (normalized === "observation") {
    return t("evidenceOutcomeObservation");
  }
  if (normalized === "insight") {
    return t("evidenceOutcomeInsight");
  }
  return normalized;
}

function formatEvidenceConfidence(value: number, t: (key: string) => string): string {
  const percent = `${Math.round(Math.max(0, Math.min(value, 1)) * 100)}%`;
  return `${t("evidenceConfidence")} ${percent}`;
}

function formatEvidenceTime(
  value: string | null | undefined,
  language: string,
): string | undefined {
  if (!value) {
    return undefined;
  }
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString(language, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function collectEvidenceItems(queue: EvidenceQueueView | undefined): EvidenceItemView[] {
  if (!queue) {
    return [];
  }
  return [...queue.pending, ...queue.deferred, ...queue.adopted, ...queue.rejected, ...(queue.history ?? [])];
}

const RECOVERED_PLAN_ACTION_IDS = new Set([
  "plan-review-evidence",
  "plan-clear-blocker",
  "plan-continue-step",
  "plan-needs-evidence",
]);

function pickPlanPrimaryAction(actions: PlanActionItem[] | undefined): PlanActionItem | undefined {
  const list = actions ?? [];
  const enabled = (id: string) => list.find((action) => action.id === id && !action.disabled);
  return (
    enabled("open-settings") ??
    list.find((action) => !action.disabled && RECOVERED_PLAN_ACTION_IDS.has(action.id)) ??
    enabled("plan-continue-without-plan") ??
    enabled("refresh-plan") ??
    list.find((action) => !action.disabled && action.id === "plan-next-task") ??
    list.find((action) => !action.disabled && action.tone === "accent") ??
    list.find((action) => !action.disabled)
  );
}

function LiveEvidenceDecisionRow({
  pendingId,
  pendingSummary,
  deferLabel,
  rejectLabel,
  onDefer,
  onReject,
}: {
  pendingId: string;
  pendingSummary: string;
  deferLabel: string;
  rejectLabel: string;
  onDefer?: (evidenceId: string, reason?: string) => void;
  onReject?: (evidenceId: string, reason?: string) => void;
}) {
  return (
    <div className="coach-plan-view__compact-evidence-decisions" data-plan-evidence-decisions="true">
      {onDefer ? (
        <button
          type="button"
          className="button button--quiet button--micro"
          data-plan-evidence-decision="defer"
          onClick={() => onDefer(pendingId, pendingSummary)}
        >
          {deferLabel}
        </button>
      ) : null}
      {onReject ? (
        <button
          type="button"
          className="button button--quiet button--micro"
          data-plan-evidence-decision="reject"
          onClick={() => onReject(pendingId, pendingSummary)}
        >
          {rejectLabel}
        </button>
      ) : null}
    </div>
  );
}

function resolvePlanDecisionStrip(input: {
  language: PlanLanguage;
  governanceItems: PlanGovernanceItem[];
  currentStep: ReactNode;
  verifyNow: ReactNode;
  planFrozen: boolean;
  blockedReason?: string;
}): PlanDecisionStripState {
  const blockerItem = findGovernanceItem(input.governanceItems, "blocker-state");
  const evidenceItem = findGovernanceItem(input.governanceItems, "evidence-adoption");
  const currentStep = inlineText(input.currentStep);
  const verifyNow = inlineText(input.verifyNow);
  const blockerDetail = inlineText(blockerItem?.detail, input.blockedReason ?? "");
  const evidenceDetail = inlineText(evidenceItem?.detail);
  const hasBlocker = Boolean(input.blockedReason?.trim()) || blockerItem?.tone === "danger";
  const hasPendingEvidence = evidenceItem?.tone === "warning" && !input.planFrozen;

  if (hasBlocker) {
    return {
      tone: "danger",
      eyebrow: planCopy(input.language, "blocked"),
      title: planCopy(input.language, "planBlocked"),
      detail: blockerDetail || planCopy(input.language, "blockerDetailMissing"),
      next: currentStep
        ? planCopy(input.language, "backTo", { step: currentStep })
        : planCopy(input.language, "narrowNext"),
    };
  }

  if (hasPendingEvidence) {
    return {
      tone: "warning",
      eyebrow: planCopy(input.language, "needsConfirmation"),
      title: planCopy(input.language, "evidenceUnchanged"),
      detail: evidenceDetail || planCopy(input.language, "chatEvidenceNoRewrite"),
      next: verifyNow
        ? planCopy(input.language, "verifyFirst", { step: verifyNow })
        : planCopy(input.language, "reviewPending"),
    };
  }

  if (input.planFrozen) {
    return {
      tone: "warning",
      eyebrow: planCopy(input.language, "planLocked"),
      title: planCopy(input.language, "formalPlanFrozen"),
      detail: planCopy(input.language, "chatEvidenceNoRewrite"),
      next: currentStep || planCopy(input.language, "continueCurrent"),
    };
  }

  return {
    tone: "good",
    eyebrow: planCopy(input.language, "ready"),
    title: planCopy(input.language, "planReady"),
    detail: planCopy(input.language, "noPlanBlocker"),
    next: verifyNow || currentStep || planCopy(input.language, "continueThread"),
  };
}

export function CoachPlanView(props: CoachPlanViewProps) {
  const {
    plan,
    className,
    titleNote,
    composerDraftReplacement,
    emptyState,
    actions,
    resumeActionLabel,
    onResumeThread,
    onStageSelect,
    stageStatusLabels,
    compactPrimary = false,
    hideDecisionStrip = false,
    evidenceQueue,
    evidenceActions,
    planChangeCandidates = [],
    onAcknowledgePlanChange,
    onRejectPlanChange,
  } = props;
  const { t, language } = useTranslation();
  const [evidenceFilter, setEvidenceFilter] = useState<"all" | "pending" | "deferred" | "adopted" | "rejected" | "history">(
    "pending",
  );
  const [planTab, setPlanTab] = useState<"plan" | "progress">("plan");
  const composerDraftReplacementCancelRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!composerDraftReplacement) {
      return;
    }

    composerDraftReplacementCancelRef.current?.focus();
  }, [composerDraftReplacement?.source, composerDraftReplacement?.title]);

  const uiLanguageSignals = [
    props.eyebrow,
    props.currentStageLabel,
    props.nextStepLabel,
    props.nextStepHint,
    props.cadenceLabel,
    props.reviewLabel,
    props.coachingStateLabel,
    props.supportSummaryLabel,
    props.whyNowLabel,
    props.verifyLabel,
    props.reviewWindowLabel,
    props.pathSummaryLabel,
    props.projectSubplansLabel,
    ...Object.values(props.projectSubplanStatusLabels ?? {}),
  ];
  const contentLanguageSignals = [props.title, props.goalSummary, plan?.title, plan?.summary].map(nodeText);
  const hasExplicitUiLanguage = uiLanguageSignals.some((value) => Boolean(nodeText(value).trim()));
  const isChinese = hasExplicitUiLanguage
    ? uiLanguageSignals.some((value) => hasChinese(nodeText(value)))
    : contentLanguageSignals.some(hasChinese);

  const resolvedEyebrow = props.eyebrow ?? t("plan");
  const resolvedEmptyTitle = props.title ?? t("plan");
  const resolvedCurrentStageLabel =
    props.currentStageLabel ?? t("planStages");
  const resolvedGoalLabel = props.goalLabel ?? t("goals");
  const resolvedNextStepLabel =
    props.nowLabel ?? props.nextStepLabel ?? t("nextMove");
  const resolvedNextStepHint =
    props.nextStepHint ??
    (isChinese
      ? "先把这一步做完，再扩大范围。"
      : planCopy(language, "narrowNext"));
  const resolvedNextStepResumeThread = props.nextStepResumeThread?.trim();
  const resolvedStagesLabel = props.stagesLabel ?? t("planStages");
  const resolvedFreezeStateLabel = props.freezeStateLabel ?? planCopy(language, "frozen");
  const resolvedLiveStateLabel = props.liveStateLabel ?? planCopy(language, "active");
  const resolvedMemoryLabel = props.memoryLabel ?? t("currentFocus");
  const resolvedWinsLabel = props.winsLabel ?? t("recentWins");
  const resolvedWeakSpotsLabel = props.weakSpotsLabel ?? t("weakSpots");
  const resolvedReviewLabel = props.reviewLabel ?? t("reviewRhythm");
  const resolvedReviewFocusLabel =
    props.reviewFocusLabel ??
    (isChinese
      ? "\u5f53\u524d\u6b65\u9aa4\u7a33\u4e86\u518d\u56de\u770b\u3002"
      : planCopy(language, "continueCurrent"));
  const resolvedCoachingStateLabel = props.coachingStateLabel ?? t("backgroundCoachWork");
  const resolvedSupportSummaryLabel = props.supportSummaryLabel ?? t("backgroundCoachWork");
  const resolvedNotesLabel = props.notesLabel ?? (isChinese ? "\u5907\u6ce8" : "Notes");
  const resolvedSupportHint =
    props.supportHint ??
    (isChinese
      ? "\u5148\u8d70\u5b8c\u4e0a\u9762\u7684\u5f53\u524d\u4e3b\u7ebf\u3002"
      : planCopy(language, "continueCurrent"));
  const resolvedWhyNowLabel = props.whyNowLabel ?? props.summaryLabel ?? t("trainingWhyNow");
  const resolvedVerifyLabel = props.verifyLabel ?? t("acceptance");
  const resolvedReviewWindowLabel =
    props.reviewWindowLabel ?? (isChinese ? "\u56de\u770b" : "Revisit");
  const resolvedActionsLabel = props.actionsLabel ?? (isChinese ? "\u52a8\u4f5c" : "Actions");
  const resolvedResumeActionLabel =
    resumeActionLabel ?? (isChinese ? "\u56de\u5230\u5bf9\u8bdd" : "Resume in Coach");
  const resolvedReturnLabel =
    props.returnLabel ??
    props.laterLabel ??
    props.pathSummaryLabel ??
    (isChinese ? "\u56de\u6d41" : "Return");
  const resolvedDetailsSummaryLabel =
    props.detailsSummaryLabel ?? (isChinese ? "\u66f4\u591a" : "More");
  const resolvedLinearOverviewLabel =
    props.overviewLabel ?? (isChinese ? "\u5148\u53ea\u770b\u8fd9\u4e00\u6761\u4e3b\u7ebf" : "Follow one thread first");
  const resolvedMainlineLabel =
    props.planAtGlanceLabel ?? (isChinese ? "\u5f53\u524d\u4e3b\u7ebf" : "Current thread");
  const shouldRepeatGoalLabel =
    resolvedGoalLabel.trim().length > 0 && resolvedGoalLabel.trim() !== resolvedMainlineLabel.trim();
  const resolvedRevisitSummaryLabel =
    props.revisitSummaryLabel ?? (isChinese ? "\u56de\u770b" : "Revisit");
  const resolvedGovernanceLabel =
    props.governanceLabel ?? (isChinese ? "\u8ba1\u5212\u72b6\u6001" : "Plan status");
  const resolvedProjectSubplansLabel =
    props.projectSubplansLabel ?? (isChinese ? "\u9879\u76ee\u5b50\u8ba1\u5212" : "Project plans");
  const projectSubplans = (props.projectSubplans ?? []).filter(
    (subplan) => subplan.id.trim().length > 0 && subplan.title.trim().length > 0,
  );
  const showEyebrow = resolvedEyebrow.trim().length > 0;
  const resolvedTitleText = nodeText(props.title ?? plan?.title).trim();
  const showHeader = showEyebrow || Boolean(resolvedTitleText) || Boolean(titleNote);
  const classes = ["section-block", "coach-plan-view", className].filter(Boolean).join(" ");
  const globalPlan = props.globalPlan;
  const globalPlanTitle = globalPlan?.title.trim() || t("globalPlanLabel");
  const hasCurrentProjectPlanLink = Boolean(
    globalPlan &&
      plan &&
      props.projectPlanLink?.globalPlanId === globalPlan.id &&
      props.projectPlanLink.projectPlanId === plan.id,
  );
  const globalPlanStatus = !globalPlan
    ? t("globalPlanNotCreated")
    : globalPlan.frozen
      ? t("globalPlanFrozen")
      : hasCurrentProjectPlanLink
        ? t("globalPlanLinked")
        : !plan
          ? t("globalPlanLinkUnavailable")
          : t("globalPlanNotLinked");
  const globalPlanRelationshipSummary = !globalPlan
    ? `${t("globalPlanLabel")} -> ${t("globalPlanNotCreated")}`
    : hasCurrentProjectPlanLink
      ? `${globalPlanTitle} -> ${plan?.title ?? t("globalPlanLabel")}`
      : `${globalPlanTitle} -> ${t("globalPlanNotLinked")}`;
  const globalPlanAction: PlanActionItem | undefined = !globalPlan
    ? props.onCreateGlobalPlan
      ? {
          id: "create-global-plan",
          label: t("globalPlanCreate"),
          icon: <PlanIcon size={12} />,
          tone: "accent",
          onClick: props.onCreateGlobalPlan,
        }
      : undefined
    : !globalPlan.frozen && plan && !hasCurrentProjectPlanLink && props.onLinkCurrentProjectPlan
      ? {
          id: "link-current-project-plan",
          label: t("globalPlanLinkCurrentProject"),
          icon: <LinkIcon size={12} />,
          tone: "accent",
          onClick: props.onLinkCurrentProjectPlan,
        }
      : undefined;
  const globalPlanNeedsAction = !globalPlan || (!hasCurrentProjectPlanLink && Boolean(plan) && !globalPlan.frozen);
  const globalPlanContextKey = [
    globalPlan?.id ?? "none",
    plan?.id ?? "none",
    hasCurrentProjectPlanLink ? "linked" : "unlinked",
    globalPlan?.frozen ? "frozen" : "live",
  ].join(":");
  const shouldShowGlobalPlanContext = Boolean(
    globalPlan || props.onCreateGlobalPlan || props.onLinkCurrentProjectPlan,
  );
  const memoryScopeContext = (
    <section className="coach-plan-view__memory-scope" aria-label={t("globalPlanRelationship")}>
      <div className="coach-plan-view__memory-scope-row">
        <span>{isChinese ? "全局记忆" : "Global memory"}</span>
        <strong>{isChinese ? "已接入" : "Connected"}</strong>
      </div>
      <span className="coach-plan-view__memory-scope-arrow" aria-hidden="true">→</span>
      <div className="coach-plan-view__memory-scope-row">
        <span>{isChinese ? "当前项目记忆" : "Current project memory"}</span>
        <strong>{plan ? (isChinese ? "已隔离" : "Isolated") : (isChinese ? "待建立" : "Not established")}</strong>
      </div>
      <p className="coach-plan-view__lane-note coach-plan-view__lane-note--quiet">
        {plan
          ? isChinese
            ? "项目证据先留在当前项目；只有可信、可迁移的结果才回流全局。"
            : "Project evidence stays here first; only trusted, transferable results flow back globally."
          : isChinese
            ? "建立项目计划后，这里会显示当前项目的独立记忆状态。"
            : "Create a project plan to show this project's isolated memory state."}
      </p>
    </section>
  );
  const globalPlanContext = shouldShowGlobalPlanContext ? (
    <details
      key={globalPlanContextKey}
      className="coach-plan-view__details coach-plan-view__global-plan-context"
      open={globalPlanNeedsAction}
      aria-label={t("globalPlanRelationship")}
    >
      <summary>{globalPlanRelationshipSummary}</summary>
      <div className="coach-plan-view__details-body">
        <section className="coach-plan-view__details-group">
          <div className="coach-plan-view__global-plan-copy">
            <span>{t("globalPlanRelationship")}</span>
            <strong>{globalPlanTitle}</strong>
            <p>{globalPlanStatus}</p>
            {globalPlan?.summary.trim() ? (
              <p className="coach-plan-view__lane-note coach-plan-view__lane-note--quiet">
                {globalPlan.summary}
              </p>
            ) : null}
          </div>
          {globalPlanAction ? (
            <div className="coach-plan-view__actions-stack">
              <ActionButton
                className="coach-plan-view__action-button"
                tone={globalPlanAction.tone}
                icon={globalPlanAction.icon}
                label={globalPlanAction.label}
                detail={globalPlanAction.detail}
                onClick={globalPlanAction.onClick}
                fullWidth
              />
            </div>
          ) : null}
        </section>
      </div>
    </details>
  ) : null;

  const renderComposerDraftReplacement = (source: PlanComposerDraftReplacementPrompt["source"]) => {
    if (!composerDraftReplacement || composerDraftReplacement.source !== source) {
      return null;
    }

    return (
      <div
        className="coach-plan-view__decision-strip is-warning"
        role="alertdialog"
        aria-modal="false"
        aria-label={composerDraftReplacement.title}
      >
        <span className="coach-plan-view__decision-rail" aria-hidden="true" />
        <div className="coach-plan-view__decision-copy">
          <strong>{composerDraftReplacement.title}</strong>
          <em title={composerDraftReplacement.detail}>{composerDraftReplacement.detail}</em>
          <div className="coach-plan-view__actions-stack">
            <button
              ref={composerDraftReplacementCancelRef}
              className="button button--compact"
              type="button"
              onClick={composerDraftReplacement.onCancel}
            >
              <span>{composerDraftReplacement.cancelLabel}</span>
            </button>
            <button
              className="button button--primary button--compact"
              type="button"
              onClick={composerDraftReplacement.onConfirm}
            >
              <span>{composerDraftReplacement.confirmLabel}</span>
            </button>
          </div>
        </div>
      </div>
    );
  };

  const evidenceItems = useMemo(() => collectEvidenceItems(evidenceQueue), [evidenceQueue]);
  const evidenceCounts = useMemo(
    () => ({
      pending: evidenceQueue?.pending.length ?? 0,
      deferred: evidenceQueue?.deferred.length ?? 0,
      adopted: evidenceQueue?.adopted.length ?? 0,
      rejected: evidenceQueue?.rejected.length ?? 0,
      history: evidenceQueue?.history?.length ?? 0,
      total: evidenceQueue?.totalCount ?? 0,
    }),
    [evidenceQueue],
  );
  const filteredEvidenceItems = useMemo(() => {
    switch (evidenceFilter) {
      case "all":
        return evidenceItems;
      case "pending":
        return evidenceQueue?.pending ?? [];
      case "deferred":
        return evidenceQueue?.deferred ?? [];
      case "adopted":
        return evidenceQueue?.adopted ?? [];
      case "rejected":
        return evidenceQueue?.rejected ?? [];
      case "history":
        return evidenceQueue?.history ?? [];
      default:
        return evidenceItems;
    }
  }, [evidenceFilter, evidenceItems, evidenceQueue]);
  const livePendingEvidence = evidenceQueue?.pending[0];
  const livePendingEvidenceId = livePendingEvidence?.id?.trim() ?? "";
  const reviewEvidenceAction = (actions ?? []).find((action) => action.id === "plan-review-evidence");
  const showLiveEvidenceDecisions = Boolean(
    reviewEvidenceAction &&
      livePendingEvidenceId &&
      (evidenceActions?.onRejectEvidence || evidenceActions?.onDeferEvidence),
  );
  const liveEvidenceDecisionRow = showLiveEvidenceDecisions && livePendingEvidence ? (
    <LiveEvidenceDecisionRow
      pendingId={livePendingEvidenceId}
      pendingSummary={inlineText(livePendingEvidence.summary)}
      deferLabel={t("evidenceDefer")}
      rejectLabel={t("reject")}
      onDefer={evidenceActions?.onDeferEvidence}
      onReject={evidenceActions?.onRejectEvidence}
    />
  ) : null;
  const emptyPlanActions = reviewEvidenceAction
    ? (actions ?? []).filter((action) => action.id !== "plan-review-evidence")
    : (actions ?? []);
  const leftoverNote = props.leftoverNote?.trim() || "";
  const emptyPrimaryAction = reviewEvidenceAction ?? pickPlanPrimaryAction(emptyPlanActions);
  const emptySecondaryActions = emptyPlanActions.filter((action) => action.id !== emptyPrimaryAction?.id);
  // Reuse the plan-generate action the host already supplies; never invent a new command.
  const planGenerateAction =
    (actions ?? []).find((action) => action.id === "refresh-plan") ?? emptyPrimaryAction;
  const planTabBar = (
    <div className="plan-dashboard__tabs" role="tablist" aria-label={t("planDashboardTabProgress")}>
      <button
        type="button"
        role="tab"
        aria-selected={planTab === "plan"}
        data-plan-tab="plan"
        className={`plan-dashboard__tab${planTab === "plan" ? " is-active" : ""}`}
        onClick={() => setPlanTab("plan")}
      >
        {t("planDashboardTabPlan")}
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={planTab === "progress"}
        data-plan-tab="progress"
        className={`plan-dashboard__tab${planTab === "progress" ? " is-active" : ""}`}
        onClick={() => setPlanTab("progress")}
      >
        {t("planDashboardTabProgress")}
      </button>
    </div>
  );

  if (!plan) {
    return (
      <section
        className={classes}
        data-plan-leftover-not-live={leftoverNote ? "true" : undefined}
      >
        {compactPrimary ? null : (
        <div className="section-block__header">
          <div>
            {showEyebrow ? <span className="eyebrow">{resolvedEyebrow}</span> : null}
            <h2>{resolvedEmptyTitle}</h2>
          </div>
        </div>
        )}
        {planTabBar}
        {planTab === "progress" ? (
          <div className="plan-dashboard__empty" data-plan-dashboard-empty="true">
            <PlanIcon size={20} />
            <p>{t("planDashboardEmptyTitle")}</p>
            {planGenerateAction ? (
              <ActionButton
                className="plan-dashboard__empty-action"
                tone={planGenerateAction.tone ?? "accent"}
                icon={planGenerateAction.icon}
                label={planGenerateAction.label}
                detail={planGenerateAction.detail}
                disabled={planGenerateAction.disabled}
                onClick={planGenerateAction.onClick}
              />
            ) : null}
          </div>
        ) : (
          <>
        <div className="coach-plan-view__empty">
          <div className="coach-plan-view__empty-card coach-plan-view__empty-card--quiet">
            {leftoverNote ? (
              <p
                className="coach-plan-view__leftover-note"
                data-plan-leftover-note="true"
                role="status"
                aria-live="polite"
              >
                {leftoverNote}
              </p>
            ) : (
              emptyState
            )}
            {leftoverNote ? null : compactPrimary && emptyPrimaryAction ? (
              <div className="coach-plan-view__compact-primary-action">
                <ActionButton
                  className="coach-plan-view__action-button"
                  tone={emptyPrimaryAction.tone ?? "accent"}
                  icon={emptyPrimaryAction.icon}
                  label={emptyPrimaryAction.label}
                  detail={emptyPrimaryAction.detail}
                  disabled={emptyPrimaryAction.disabled}
                  onClick={emptyPrimaryAction.onClick}
                  fullWidth
                />
              </div>
            ) : leftoverNote ? null : (
            <details className="coach-plan-view__empty-more">
              <summary>{planCopy(language, "leftoverOutlineMore")}</summary>
              <div className="coach-plan-view__empty-outline" aria-label={planCopy(language, "emptyOutlineLabel")}>
                <div className="coach-plan-view__empty-outline-row is-current">
                  <span>{planCopy(language, "connectFirst")}</span>
                  <strong>{planCopy(language, "workingConnection")}</strong>
                  <p>{planCopy(language, "formalPlanHonest")}</p>
                </div>
                <div className="coach-plan-view__empty-outline-row">
                  <span>{planCopy(language, "formalThread")}</span>
                  <strong>{planCopy(language, "compressThread")}</strong>
                  <p>{planCopy(language, "noSilentMutation")}</p>
                </div>
                <div className="coach-plan-view__empty-outline-row">
                  <span>{planCopy(language, "emptyVerify")}</span>
                  <strong>{planCopy(language, "everyStepReturns")}</strong>
                  <p>{planCopy(language, "completionFlow")}</p>
                </div>
              </div>
            </details>
            )}
          </div>
        </div>
        {compactPrimary ? null : memoryScopeContext}
        {compactPrimary ? null : globalPlanContext}
        {compactPrimary ? null : emptyPrimaryAction || emptySecondaryActions.length ? (
          <section
            className="coach-plan-view__actions-inline"
            aria-label={props.actionsLabel ?? resolvedNextStepLabel}
          >
            {emptyPrimaryAction ? (
              <div className="coach-plan-view__compact-primary-action">
                <ActionButton
                  className="coach-plan-view__action-button"
                  tone={emptyPrimaryAction.tone ?? "accent"}
                  icon={emptyPrimaryAction.icon}
                  label={emptyPrimaryAction.label}
                  detail={emptyPrimaryAction.detail}
                  disabled={emptyPrimaryAction.disabled}
                  onClick={emptyPrimaryAction.onClick}
                  fullWidth
                />
                {emptyPrimaryAction.id === "plan-review-evidence" ? liveEvidenceDecisionRow : null}
              </div>
            ) : null}
            {emptySecondaryActions.length ? (
              <details className="coach-plan-view__empty-more">
                <summary>{resolvedActionsLabel}</summary>
                <div className="coach-plan-view__actions-stack">
                  {emptySecondaryActions.map((action) => (
                    <ActionButton
                      key={action.id}
                      className="coach-plan-view__action-button"
                      tone="ghost"
                      icon={action.icon}
                      label={action.label}
                      detail={action.detail}
                      disabled={action.disabled}
                      onClick={action.onClick}
                      fullWidth
                    />
                  ))}
                </div>
              </details>
            ) : null}
          </section>
        ) : null}
          </>
        )}
      </section>
    );
  }

  const activeStage =
    (plan.currentStageId
      ? plan.stages.find((stage) => stage.id === plan.currentStageId)
      : undefined) ??
    plan.stages.find((stage) => stage.status === "active") ??
    plan.stages[0];
  const liveStageIsCurrent = props.liveStageIsCurrent !== false;
  const liveCurrentStep = plan.currentStep?.trim() || "";
  const activeStageTitle = liveStageIsCurrent
    ? activeStage?.title ?? (props.title ?? plan.title)
    : liveCurrentStep;
  const activeStageObjective = liveStageIsCurrent
    ? activeStage?.objective ?? plan.summary
    : "";
  const currentGoalSummary = props.goalSummary ?? (compactPrimary ? undefined : activeStageObjective);
  const planStateValue = plan.frozen ? resolvedFreezeStateLabel : resolvedLiveStateLabel;
  const queuedStageCount = plan.stages.filter((stage) => stage.status === "queued").length;
  const totalStageCount = Math.max(plan.stages.length, 1);
  const activeStageIndex = Math.max(plan.stages.findIndex((stage) => stage.id === activeStage?.id), 0) + 1;
  const upcomingStages = plan.stages.filter((stage) => stage.status === "queued");
  const previewStages = upcomingStages.slice(0, 3);
  const laterSecondaryStage = previewStages[1] ?? null;
  const pathProgressNote =
    plan.stages.length === 0 ? "" : formatQueuedStageSummary(queuedStageCount, language);
  const laterContinuationNote = laterSecondaryStage
    ? isChinese
      ? `\u518d\u540e\u9762\uff1a${laterSecondaryStage.title}`
      : `Then: ${laterSecondaryStage.title}`
    : undefined;
  const verifyFallback = isChinese
    ? "\u5b8c\u6210\u540e\u505a\u4e00\u6b21\u6700\u5c0f\u9a8c\u8bc1\uff0c\u786e\u8ba4\u8fd9\u4e00\u6b65\u771f\u7684\u6210\u7acb\u3002"
    : "Run one small verification to confirm this step really landed.";
  const recoveredVerifyLocked =
    Boolean(plan.currentStep?.trim()) &&
    !(plan.verifyMethod ?? []).some((item) => Boolean(item.trim()));
  const returnFallback = isChinese
    ? "\u5e26\u7740\u9a8c\u8bc1\u7ed3\u679c\u56de\u5230\u5bf9\u8bdd\uff0c\u518d\u51b3\u5b9a\u8fd9\u6761\u4e3b\u7ebf\u7684\u4e0b\u4e00\u6b65\u3002"
    : "Return to Coach with the verified result before moving the thread forward.";
  const currentStepText = props.nextStep ?? activeStageObjective;
  const verifyNowInline = inlineText(props.verifyNow);
  const verifyText = verifyNowInline
    ? props.verifyNow
    : recoveredVerifyLocked
      ? planCopy(language, "continueCurrent")
      : verifyFallback;
  const returnPathText = props.returnPath ?? returnFallback;
  const stageProgressText = !liveStageIsCurrent
    ? ""
    : isChinese
      ? `\u7b2c ${activeStageIndex} / ${totalStageCount} \u6bb5`
      : `Stage ${activeStageIndex} of ${totalStageCount}`;
  const currentGoalText = inlineText(currentGoalSummary, compactPrimary ? "" : activeStageObjective || activeStageTitle);
  const currentMainlineText = currentGoalText || activeStageTitle;
  const showGoalSummary = Boolean(!compactPrimary && currentGoalText && currentGoalText !== activeStageTitle);
  const showGoalLead = Boolean(currentMainlineText);
  const currentStepInline = inlineText(currentStepText, activeStageObjective);
  const recoveredWhyLocked = Boolean(plan.currentStep?.trim()) && !plan.whyNow?.trim();
  const whyFallback = recoveredWhyLocked ? "" : (plan.whyNow?.trim() || activeStageObjective);
  const whyNowInline = inlineText(props.whyNow, whyFallback);
  const verifyInline = inlineText(verifyText, recoveredVerifyLocked ? "" : verifyFallback);
  const returnInline = inlineText(returnPathText, returnFallback);
  const whyNowBody =
    props.whyNow && whyNowInline && whyNowInline !== currentStepInline
      ? props.whyNow
      : whyFallback && whyFallback !== currentStepInline
        ? whyFallback
        : pathProgressNote;
  const summaryChips = [stageProgressText, plan.cadence].filter(Boolean) as string[];
  const blockedReason = plan.blockedReason?.trim();
  const pendingEvidenceCount = evidenceQueue?.pending.length ?? 0;
  const fallbackGovernanceItems: PlanGovernanceItem[] = [
    {
      id: "formal-plan",
      label: isChinese ? "\u6b63\u5f0f\u8ba1\u5212" : planCopy(language, "formalPlan"),
      value: planStateValue,
      detail: plan.frozen
        ? isChinese
          ? "\u6b63\u5f0f\u8ba1\u5212\u5df2\u9501\u5b9a\u3002\u804a\u5929\u8bc1\u636e\u4e0d\u4f1a\u9759\u9ed8\u91cd\u5199\u5b83\u3002"
          : `${planCopy(language, "formalPlanFrozen")}. ${planCopy(language, "chatEvidenceNoRewrite")}`
        : isChinese
          ? "\u5bf9\u8bdd\u4e0d\u4f1a\u9759\u9ed8\u91cd\u5199\u5b83\u3002"
          : planCopy(language, "chatEvidenceNoRewrite"),
      tone: plan.frozen ? "warning" : "good",
    },
    {
      id: "evidence-adoption",
      label: isChinese ? "\u8bc1\u636e" : planCopy(language, "evidence"),
      value: isChinese ? "\u5f85\u786e\u8ba4" : planCopy(language, "needsConfirmation"),
      detail: isChinese
        ? "\u8bc1\u636e\u8fd8\u6ca1\u6539\u5199\u8ba1\u5212\u3002"
        : planCopy(language, "evidenceUnchanged"),
      tone: "muted",
    },
    {
      id: "blocker-state",
      label: isChinese ? "\u5361\u70b9" : planCopy(language, "blocker"),
      value: blockedReason
        ? isChinese
          ? "\u6709\u5361\u70b9"
          : planCopy(language, "blocked")
        : isChinese
          ? "\u53ef\u63a8\u8fdb"
          : planCopy(language, "clear"),
      detail: blockedReason || (isChinese ? "\u76ee\u524d\u6ca1\u6709\u8ba1\u5212\u5361\u70b9\u3002" : planCopy(language, "noPlanBlocker")),
      tone: blockedReason ? "danger" : "good",
    },
  ];
  const governanceItems =
    props.governanceItems && props.governanceItems.length > 0
      ? props.governanceItems
      : fallbackGovernanceItems;
  const planDecisionStrip = resolvePlanDecisionStrip({
    language,
    governanceItems,
    currentStep: currentStepText,
    verifyNow: verifyText,
    planFrozen: plan.frozen,
    blockedReason,
  });
  const shouldShowDecisionCard =
    !hideDecisionStrip &&
    (compactPrimary
      ? plan.frozen || Boolean(blockedReason) || planDecisionStrip.tone === "danger"
      : planDecisionStrip.tone !== "good" || plan.frozen || Boolean(blockedReason) || pendingEvidenceCount > 0);
  const mainLanes: Array<{
    id: string;
    label: string;
    body: ReactNode;
    detail?: ReactNode;
    accent?: boolean;
  }> = [
    {
      id: "current",
      label: resolvedNextStepLabel,
      body: currentStepText,
      detail: compactPrimary ? verifyText : resolvedNextStepHint,
      accent: true,
    },
    {
      id: "why",
      label: resolvedWhyNowLabel,
      body: whyNowBody,
    },
    {
      id: "verify",
      label: resolvedVerifyLabel,
      body: verifyText,
    },
    {
      id: "return",
      label: resolvedReturnLabel,
      body: returnPathText,
      detail: !compactPrimary && laterContinuationNote ? laterContinuationNote : undefined,
    },
  ];
  const currentLane = mainLanes[0];
  const compactLaterText = (() => {
    const now = inlineText(currentLane.body);
    const done = inlineText(currentLane.detail);
    const reviewText = inlineText(props.reviewWindow);
    const reviewFirst = reviewText.match(/^[\s\S]*?[。.!?]/)?.[0]?.trim() || reviewText;
    const queued = upcomingStages[0]?.title?.trim() ?? "";
    return [reviewFirst, queued].find((text) => text && text !== now && text !== done) ?? "";
  })();
  const routeStripItems = [
    {
      id: "current",
      label: resolvedCurrentStageLabel,
      body: activeStageTitle,
      detail: stageProgressText,
    },
    {
      id: "why",
      label: resolvedWhyNowLabel,
      body: whyNowBody,
      detail: undefined,
    },
    {
      id: "verify",
      label: resolvedVerifyLabel,
      body: verifyText,
      detail: undefined,
    },
    {
      id: "return",
      label: resolvedReturnLabel,
      body: returnPathText,
      detail: laterContinuationNote,
    },
  ];
  const supportRows = [
    props.reviewWindow
      ? {
          id: "review-window",
          label: resolvedReviewWindowLabel,
          body: props.reviewWindow,
        }
      : null,
    props.coachingStateSummary
      ? {
          id: "coach-state",
          label: resolvedCoachingStateLabel,
          body: props.coachingStateSummary,
        }
      : null,
    props.memorySummary
      ? {
          id: "memory-summary",
          label: resolvedMemoryLabel,
          body: props.memorySummary,
        }
      : null,
    props.reviewRhythm
      ? {
          id: "review-rhythm",
          label: resolvedReviewLabel,
          body: props.reviewRhythm,
        }
      : null,
    props.rememberedSummary
      ? {
          id: "remembered-summary",
          label: props.rememberedSummaryLabel ?? (isChinese ? "\u6559\u7ec3\u5df2\u8bb0\u4f4f" : "Trainer remembers"),
          body: props.rememberedSummary,
        }
      : null,
  ].filter(Boolean) as Array<{ id: string; label: string; body: ReactNode }>;
  const reviewSupportRow = supportRows.find((row) => row.id === "review-window") ?? null;
  const backgroundRows = supportRows.filter((row) => row.id !== "review-window");

  const noteRows = [
    props.teachingObservations?.length
      ? {
          id: "observations",
          label: props.teachingObservationsLabel ?? (isChinese ? "\u6559\u5b66\u89c2\u5bdf" : "Teaching observations"),
          value: props.teachingObservations.slice(0, 3).join(" · "),
        }
      : null,
    props.weakSpots?.length
      ? {
          id: "weak-spots",
          label: resolvedWeakSpotsLabel,
          value: props.weakSpots.slice(0, 3).join(" · "),
        }
      : null,
    props.recentWins?.length
      ? {
          id: "recent-wins",
          label: resolvedWinsLabel,
          value: props.recentWins.slice(0, 3).join(" · "),
        }
      : null,
  ].filter(Boolean) as Array<{ id: string; label: string; value: string }>;
  const trajectoryRows = (props.trajectoryItems ?? []).slice(0, 3).map((item) => ({
    id: item.id,
    label: item.label,
    value: inlineText(item.value),
    detail: inlineText(item.detail),
  }));

  const hasStageDetails = plan.stages.length > 1;
  const hasReviewDetails = Boolean(props.dueReviewItems?.length) || Boolean(reviewSupportRow);
  const hasTrajectoryDetails = trajectoryRows.length > 0;
  const hasBackgroundDetails = backgroundRows.length > 0 || noteRows.length > 0 || hasTrajectoryDetails;
  const evidenceTone = evidenceCounts.pending > 0 ? "warning" : evidenceCounts.deferred > 0 ? "muted" : "good";
  const hasEvidenceDetails = evidenceCounts.total > 0;
  const pendingEvidenceAction = (actions ?? []).find(
    (action) => action.id === "plan-review-evidence" || action.id === "plan-needs-evidence",
  );
  const compactPrimaryAction = compactPrimary
    ? evidenceCounts.pending > 0 && pendingEvidenceAction
      ? pendingEvidenceAction
      : onResumeThread && resolvedNextStepResumeThread
      ? {
          id: "resume-thread",
          label: resolvedResumeActionLabel,
          detail: resolvedNextStepResumeThread,
          icon: <ArrowRightIcon size={12} />,
          tone: "accent" as const,
          disabled: false,
          onClick: onResumeThread,
        }
      : pickPlanPrimaryAction(actions)
    : undefined;
  const compactSecondaryActions = compactPrimary
    ? (actions ?? []).filter((action) => action.id !== compactPrimaryAction?.id)
    : [];
  const compactBlockerText = blockedReason || inlineText(findGovernanceItem(governanceItems, "blocker-state")?.value);
  const compactDetailRows: Array<{ id: string; label: string; body: ReactNode }> = compactPrimary
    ? [
        {
          id: "stage",
          label: resolvedCurrentStageLabel,
          body: stageProgressText ? `${activeStageTitle} · ${stageProgressText}` : activeStageTitle,
        },
        {
          id: "blocker",
          label: isChinese ? "卡点" : planCopy(language, "blocker"),
          body: compactBlockerText || (isChinese ? "可推进" : planCopy(language, "clear")),
        },
        ...mainLanes.slice(1).map((lane) => ({
          id: lane.id,
          label: lane.label,
          body: lane.body,
        })),
      ]
    : [];
  const hasCompactGovernance = compactPrimary && governanceItems.length > 0;
  const hasDetails =
    hasStageDetails ||
    hasReviewDetails ||
    hasBackgroundDetails ||
    hasEvidenceDetails ||
    compactDetailRows.length > 0 ||
    compactSecondaryActions.length > 0 ||
    hasCompactGovernance ||
    planChangeCandidates.length > 0;
  const detailSections = [
    hasStageDetails ? resolvedStagesLabel : null,
    hasReviewDetails ? resolvedRevisitSummaryLabel : null,
    hasTrajectoryDetails ? (props.trajectoryLabel ?? (isChinese ? "来源短名单" : "Source shortlist")) : null,
    hasBackgroundDetails ? resolvedSupportSummaryLabel : null,
    hasEvidenceDetails ? t("evidenceGovernance") : null,
  ].filter(Boolean) as string[];
  const detailsSummary =
    compactPrimary && detailSections.length > 0
      ? resolvedDetailsSummaryLabel
      : `${resolvedDetailsSummaryLabel}${detailSections.length ? ` · ${detailSections.join(" / ")}` : ""}`;
  const primarySummaryChips = compactPrimary ? [] : summaryChips;
  const primaryRouteStripItems = routeStripItems;

  return (
    <section
      className={classes}
      data-plan-leftover-not-live={leftoverNote ? "true" : undefined}
      aria-labelledby={!compactPrimary && resolvedTitleText ? "coach-plan-view-title" : undefined}
      onKeyDown={(event) => {
        if (event.key === "Escape" && composerDraftReplacement) {
          event.preventDefault();
          composerDraftReplacement.onCancel();
        }
      }}
    >
      {showHeader && !compactPrimary ? (
        <div className="section-block__header">
          <div>
            {showEyebrow ? <span className="eyebrow">{resolvedEyebrow}</span> : null}
            {resolvedTitleText ? <h2 id="coach-plan-view-title">{resolvedTitleText}</h2> : null}
            {titleNote ? <p className="inline-note">{titleNote}</p> : null}
          </div>
        </div>
      ) : null}

      {planTabBar}

      {planTab === "progress" ? (
        <PlanDashboard plan={plan} />
      ) : (
      <div className="coach-plan-view__flow coach-plan-view__flow--linear">
        <article
          className="coach-plan-view__main-card"
          data-plan-primary={compactPrimary ? "true" : undefined}
          aria-label={resolvedLinearOverviewLabel}
          aria-labelledby={compactPrimary ? undefined : "coach-plan-view-mainline-heading"}
        >
          <div className="coach-plan-view__main-card-head">
              <div className="coach-plan-view__main-card-title">
                {!compactPrimary ? (
                  <h3 id="coach-plan-view-mainline-heading" className="coach-plan-view__mainline-heading">
                    {resolvedMainlineLabel}
                  </h3>
                ) : null}
                {!compactPrimary && resolvedNextStepResumeThread ? (
                  <div className="coach-plan-view__resume-banner">
                    <span className="eyebrow">{resolvedResumeActionLabel}</span>
                  <p className="coach-plan-view__resume-copy">{resolvedNextStepResumeThread}</p>
                  {onResumeThread ? (
                    <ActionButton
                      tone="accent"
                      icon={<ArrowRightIcon size={12} />}
                      label={resolvedResumeActionLabel}
                      detail={resolvedNextStepHint}
                      onClick={onResumeThread}
                      fullWidth={false}
                    />
                  ) : null}
                </div>
              ) : null}
              {!compactPrimary && showGoalLead ? (
                <>
                  {shouldRepeatGoalLabel ? (
                    <p className="coach-plan-view__lane-note coach-plan-view__lane-note--quiet">
                      {resolvedGoalLabel}
                    </p>
                  ) : null}
                  <div className="coach-plan-view__goal-title">
                    <p>{currentMainlineText}</p>
                  </div>
                </>
              ) : null}
              {!compactPrimary && showGoalSummary ? renderNodeWithParagraph(currentGoalSummary) : null}
              {primarySummaryChips.length ? (
                <div className="coach-plan-view__summary-chips" aria-label={isChinese ? "概览" : "Overview"}>
                  {primarySummaryChips.map((chip) => (
                    <StatusLabel key={chip} label={chip} />
                  ))}
                </div>
              ) : null}
              {governanceItems.length && !compactPrimary ? (
                <div className="coach-plan-view__governance-strip" aria-label={resolvedGovernanceLabel}>
                  {governanceItems.slice(0, 4).map((item) => {
                    const detail = inlineText(item.detail);
                    return (
                      <div
                        key={item.id}
                        className={`coach-plan-view__governance-item is-${item.tone ?? "neutral"}`}
                        title={[item.label, inlineText(item.value), detail].filter(Boolean).join(" · ")}
                      >
                        <span>{item.label}</span>
                        <strong>{inlineText(item.value)}</strong>
                      </div>
                    );
                  })}
                </div>
              ) : null}
              {shouldShowDecisionCard && !compactPrimary ? (
                <div
                  className={`coach-plan-view__decision-strip is-${planDecisionStrip.tone}`}
                  role="status"
                  aria-live="polite"
                >
                  <span className="coach-plan-view__decision-rail" aria-hidden="true" />
                  <div className="coach-plan-view__decision-copy">
                    <span>{planDecisionStrip.eyebrow}</span>
                    <strong>{planDecisionStrip.title}</strong>
                    <p>{planDecisionStrip.detail}</p>
                    <em>{planDecisionStrip.next}</em>
                  </div>
                </div>
              ) : null}
              {!compactPrimary ? (
              <div
                className="coach-plan-view__now-card"
                data-plan-fact="next"
                title={inlineText(currentLane.body)}
              >
                <span>{currentLane.label}</span>
                <strong>{currentLane.body}</strong>
                {currentLane.detail ? <em>{inlineText(currentLane.detail)}</em> : null}
                {resolvedNextStepResumeThread ? (
                  <p className="inline-note">{resolvedNextStepResumeThread}</p>
                ) : null}
              </div>
              ) : null}
              {compactPrimary ? (
                <div className="coach-plan-view__compact-summary">
                  {leftoverNote ? (
                    <p
                      className="coach-plan-view__leftover-note"
                      data-plan-leftover-note="true"
                      role="status"
                      aria-live="polite"
                    >
                      {leftoverNote}
                    </p>
                  ) : null}
                  <div
                    className="coach-plan-view__now-card"
                    data-plan-fact="next"
                    title={inlineText(currentLane.body)}
                  >
                    <strong>{currentLane.body}</strong>
                    {currentLane.detail &&
                    inlineText(currentLane.detail) !== inlineText(currentLane.body) ? (
                      <p className="coach-plan-view__now-done">{inlineText(currentLane.detail)}</p>
                    ) : null}
                    {compactLaterText ? (
                      <p className="coach-plan-view__now-next">{compactLaterText}</p>
                    ) : null}
                  </div>
                  {compactPrimaryAction ? (
                    <div className="coach-plan-view__compact-primary-action">
                      <ActionButton
                        className="coach-plan-view__action-button"
                        tone={compactPrimaryAction.tone ?? "accent"}
                        icon={compactPrimaryAction.icon}
                        label={compactPrimaryAction.label}
                        detail={compactPrimaryAction.detail}
                        disabled={compactPrimaryAction.disabled}
                        onClick={compactPrimaryAction.onClick}
                        fullWidth
                      />
                    </div>
                  ) : null}
                  {compactSecondaryActions.length ? (
                    <details className="coach-plan-view__empty-more">
                      <summary>{resolvedActionsLabel}</summary>
                      <div className="coach-plan-view__actions-stack">
                        {compactSecondaryActions.map((action) => (
                          <ActionButton
                            key={action.id}
                            className="coach-plan-view__action-button"
                            tone={action.tone ?? "ghost"}
                            icon={action.icon}
                            label={action.label}
                            detail={action.detail}
                            disabled={action.disabled}
                            onClick={action.onClick}
                            fullWidth
                          />
                        ))}
                      </div>
                    </details>
                  ) : null}
                </div>
              ) : null}
              {!hideDecisionStrip && !shouldShowDecisionCard && !compactPrimary ? (
                <div className={`coach-plan-view__decision-inline is-${planDecisionStrip.tone}`} role="status" aria-live="polite">
                  <span>{planDecisionStrip.eyebrow}</span>
                  <strong>{planDecisionStrip.detail}</strong>
                </div>
              ) : null}
              {!compactPrimary ? (
                <div className="coach-plan-view__route-strip" aria-label={isChinese ? "\u5f53\u524d\u8ba1\u5212\u8def\u7ebf" : "Current plan route"}>
                {primaryRouteStripItems.map((item) => (
                  <div
                    key={item.id}
                    className="coach-plan-view__route-item"
                    data-plan-fact={item.id}
                    title={[item.label, item.body, item.detail]
                      .map((value) => inlineText(value))
                      .filter(Boolean)
                      .join(" · ")}
                  >
                    <span>{item.label}</span>
                    <strong>{item.body}</strong>
                    {item.detail ? <em>{item.detail}</em> : null}
                  </div>
                ))}
                </div>
              ) : null}
            </div>
          </div>
          {compactPrimary ? null : memoryScopeContext}
          {compactPrimary ? null : globalPlanContext}
          {!hasStageDetails && plan.stages.length === 1 && plan.stages[0] ? (
            <PlanStageSection
              stage={plan.stages[0]}
              planId={plan.id}
              isActive={plan.stages[0].id === activeStage?.id}
              statusLabel={resolveStageStatusLabel(
                plan.stages[0].status,
                stageStatusLabels?.[plan.stages[0].status],
                language,
              )}
              onStageSelect={onStageSelect}
            />
          ) : null}
          {projectSubplans.length > 0 ? (
            <details className="coach-plan-view__details coach-plan-view__project-subplans">
              <summary>{`${resolvedProjectSubplansLabel} (${projectSubplans.length})`}</summary>
              <div className="coach-plan-view__details-body">
                <section className="coach-plan-view__details-group">
                  {renderComposerDraftReplacement("project-subplan")}
                  <div className="coach-plan-view__stage-list">
                    {projectSubplans.map((subplan) => {
                      const statusLabel =
                        props.projectSubplanStatusLabels?.[subplan.status] ??
                        defaultProjectSubplanStatusLabel(subplan.status, language);
                      const detail = projectSubplanDetail(subplan, language);

                      return (
                        <button
                          key={subplan.id}
                          className={`coach-plan-view__stage-row is-${subplan.status}`}
                          type="button"
                          disabled={!props.onProjectSubplanSelect}
                          title={[subplan.title, statusLabel, detail].join(" / ")}
                          onClick={() => props.onProjectSubplanSelect?.(subplan)}
                        >
                          <span className="coach-plan-view__stage-dot" aria-hidden="true" />
                          <div className="coach-plan-view__stage-copy">
                            <div className="coach-plan-view__stage-topline">
                              <strong>{subplan.title}</strong>
                              <StatusLabel label={statusLabel} />
                            </div>
                            <p>{detail}</p>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </section>
              </div>
            </details>
          ) : null}
          {compactPrimary ? null : hasDetails ? (
          <details className="coach-plan-view__details">
            <summary>{detailsSummary}</summary>
            {hasDetails ? (
            <div className="coach-plan-view__details-body">
              <div className="coach-plan-view__details-intro">
                <p className="coach-plan-view__lane-note coach-plan-view__lane-note--quiet coach-plan-view__details-hint">
                  {resolvedSupportHint}
                </p>
              </div>

              {compactDetailRows.length && !compactPrimary ? (
                <section className="coach-plan-view__details-group">
                  <div className="coach-plan-view__details-group-head">
                    <span>{isChinese ? "主线说明" : "Thread context"}</span>
                  </div>
                  <div className="coach-plan-view__micro-list">
                    {compactDetailRows.map((lane) => (
                      <div key={lane.id} className="coach-plan-view__micro-item">
                        <span>{lane.label}</span>
                        <div>{renderNodeWithParagraph(lane.body)}</div>
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}

              {hasCompactGovernance ? (
                <section className="coach-plan-view__details-group">
                  <div className="coach-plan-view__details-group-head">
                    <span>{resolvedGovernanceLabel}</span>
                  </div>
                  <div className="coach-plan-view__governance-strip" aria-label={resolvedGovernanceLabel}>
                    {governanceItems.map((item) => {
                      const detail = inlineText(item.detail);
                      return (
                        <div
                          key={item.id}
                          className={`coach-plan-view__governance-item is-${item.tone ?? "neutral"}`}
                          title={[item.label, inlineText(item.value), detail].filter(Boolean).join(" · ")}
                        >
                          <span>{item.label}</span>
                          <strong>{inlineText(item.value)}</strong>
                        </div>
                      );
                    })}
                  </div>
                </section>
              ) : null}

              {compactSecondaryActions.length ? (
                <section className="coach-plan-view__details-group">
                  <div className="coach-plan-view__details-group-head">
                    <span>{resolvedActionsLabel}</span>
                  </div>
                  <div className="coach-plan-view__actions-stack">
                    {compactSecondaryActions.map((action) => (
                      <ActionButton
                        key={action.id}
                        className="coach-plan-view__action-button"
                        tone={action.tone}
                        icon={action.icon}
                        label={action.label}
                        detail={action.detail}
                        disabled={action.disabled}
                        onClick={action.onClick}
                        fullWidth
                      />
                    ))}
                  </div>
                </section>
              ) : null}

              {hasStageDetails ? (
                <section className="coach-plan-view__details-group">
                  <div className="coach-plan-view__details-group-head">
                    <span>{resolvedStagesLabel}</span>
                  </div>
                  {renderComposerDraftReplacement("stage")}
                  <div className="coach-plan-view__stage-list">
                    {plan.stages.map((stage) => {
                      const stageLabel = resolveStageStatusLabel(
                        stage.status,
                        stageStatusLabels?.[stage.status],
                        language,
                      );

                      return (
                        <PlanStageSection
                          key={stage.id}
                          stage={stage}
                          planId={plan.id}
                          isActive={stage.id === activeStage?.id}
                          statusLabel={stageLabel}
                          onStageSelect={onStageSelect}
                        />
                      );
                    })}
                  </div>
                </section>
              ) : null}

              {hasReviewDetails ? (
                <section className="coach-plan-view__details-group">
                  <div className="coach-plan-view__details-group-head">
                    <span>{resolvedRevisitSummaryLabel}</span>
                  </div>
                  <div className="coach-plan-view__review-list">
                    <p className="coach-plan-view__lane-note coach-plan-view__lane-note--quiet">
                      {resolvedReviewFocusLabel}
                    </p>
                    {reviewSupportRow ? (
                      <div className="coach-plan-view__micro-item">
                        <span>{resolvedReviewWindowLabel}</span>
                        <div>{renderNodeWithParagraph(reviewSupportRow.body)}</div>
                      </div>
                    ) : null}
                    {props.dueReviewItems?.slice(0, 4).map((item) => {
                      const meta = compactReviewMeta(item, isChinese);
                      const lane = compactReviewLane(item, isChinese);
                      return (
                        <div key={item.id} className="coach-plan-view__review-row">
                          <strong>{item.title}</strong>
                          <p>{lane}</p>
                          {meta ? <span>{meta}</span> : null}
                        </div>
                      );
                    })}
                  </div>
                </section>
              ) : null}

              {hasBackgroundDetails ? (
                <section className="coach-plan-view__details-group">
                  <div className="coach-plan-view__details-group-head">
                    <span>{resolvedSupportSummaryLabel}</span>
                  </div>
                  <div className="coach-plan-view__micro-list">
                    {trajectoryRows.length ? (
                      <div className="coach-plan-view__note-line">
                        <p className="coach-plan-view__lane-note coach-plan-view__lane-note--quiet">
                          {props.trajectoryLabel ?? (isChinese ? "来源短名单" : "Source shortlist")}
                        </p>
                        {trajectoryRows.map((row) => (
                          <div key={row.id} className="coach-plan-view__note-item">
                            <span>{row.label}</span>
                            <strong>{row.value}</strong>
                            {row.detail ? <em>{row.detail}</em> : null}
                          </div>
                        ))}
                      </div>
                    ) : null}
                    {backgroundRows.map((row) => (
                      <div key={row.id} className="coach-plan-view__micro-item">
                        <span>{row.label}</span>
                        <div>{renderNodeWithParagraph(row.body)}</div>
                      </div>
                    ))}

                    {noteRows.length ? (
                      <div className="coach-plan-view__note-line">
                        <p className="coach-plan-view__lane-note coach-plan-view__lane-note--quiet">
                          {resolvedNotesLabel}
                        </p>
                        {noteRows.map((row) => (
                          <div key={row.id} className="coach-plan-view__note-item">
                            <span>{row.label}</span>
                            <strong>{row.value}</strong>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </section>
              ) : null}

              {planChangeCandidates.length > 0 ? (
                <section className="coach-plan-view__details-group coach-plan-view__details-group--evidence">
                  <div className="coach-plan-view__details-group-head">
                    <span>{isChinese ? "计划变更候选" : "Plan change candidates"}</span>
                    <StatusLabel label={`${planChangeCandidates.filter((item) => item.status === "pending").length}`} />
                  </div>
                  {planChangeCandidates.map((candidate) => (
                    <div key={candidate.id} className="coach-plan-view__evidence-item">
                      <strong>{candidate.status === "pending" ? (isChinese ? "待确认" : "Pending confirmation") : candidate.status}</strong>
                      <p>
                        {sanitizeErrorSurfaceText(candidate.reason, language) ||
                          (isChinese ? "这条候选还需要确认。" : "This candidate still needs confirmation.")}
                      </p>
                      <p>
                        {isChinese ? "差异" : "Diff"}:{" "}
                        {describeSafeStructuredValue(
                          candidate.diff,
                          language,
                          isChinese ? "没有可展示的差异。" : "No visible diff.",
                        )}
                      </p>
                      <p>
                        {isChinese ? "影响" : "Impact"}:{" "}
                        {describeSafeStructuredValue(
                          candidate.impact,
                          language,
                          isChinese ? "没有可展示的影响。" : "No visible impact.",
                        )}
                      </p>
                      {candidate.status === "pending" ? (
                        <div className="coach-plan-view__evidence-actions">
                          {onAcknowledgePlanChange ? <ActionButton tone="accent" label={isChinese ? "确认候选" : "Acknowledge candidate"} onClick={() => onAcknowledgePlanChange(candidate.id)} fullWidth={false} /> : null}
                          {onRejectPlanChange ? <ActionButton tone="ghost" label={isChinese ? "拒绝候选" : "Reject candidate"} onClick={() => onRejectPlanChange(candidate.id)} fullWidth={false} /> : null}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </section>
              ) : null}

              {hasEvidenceDetails ? (
                <details className="coach-plan-view__nested-details coach-plan-view__evidence-details">
                  <summary>
                    <span>{t("evidenceGovernance")}</span>
                    <StatusLabel label={`${evidenceCounts.total}`} />
                  </summary>
                  <section
                    className={`coach-plan-view__details-group coach-plan-view__details-group--evidence is-${evidenceTone}`}
                  >
                  <div className="coach-plan-view__details-group-head">
                    <span>{t("evidenceGovernance")}</span>
                    <StatusLabel label={`${evidenceCounts.total}`} />
                    {evidenceActions?.onRefreshQueue ? (
                      <ActionButton
                        tone="ghost"
                        icon={<RefreshIcon size={12} />}
                        label={t("refresh")}
                        onClick={evidenceActions.onRefreshQueue}
                        fullWidth={false}
                      />
                    ) : null}
                  </div>
                  <div className="coach-plan-view__evidence-toolbar">
                    {(["pending", "deferred", "adopted", "rejected", "history", "all"] as const)
                      .filter((filter) => filter !== "history" || evidenceCounts.history > 0)
                      .map((filter) => {
                      const active = evidenceFilter === filter;
                      const count =
                        filter === "all"
                          ? evidenceCounts.total
                          : evidenceCounts[filter];
                      const filterLabel =
                        filter === "all"
                          ? t("evidenceFilterAll")
                          : filter === "pending"
                            ? t("pending")
                            : filter === "deferred"
                              ? t("evidenceFilterDeferred")
                              : filter === "adopted"
                                ? t("evidenceFilterAdopted")
                                : filter === "history"
                                  ? t("history")
                                  : t("evidenceFilterRejected");
                      return (
                        <button
                          key={filter}
                          type="button"
                          className={`coach-plan-view__evidence-filter ${active ? "is-active" : ""}`}
                          onClick={() => setEvidenceFilter(filter)}
                        >
                          <span>{filterLabel}</span>
                          <strong>{count}</strong>
                        </button>
                      );
                    })}
                  </div>
                  {filteredEvidenceItems.length > 0 ? (
                    <div className="coach-plan-view__evidence-list">
                      {filteredEvidenceItems.map((item) => {
                        const summary = inlineText(item.summary);
                        const concepts = item.concepts.slice(0, 3).join(" · ");
                        const source = formatEvidenceSource(item.source, t);
                        const outcome = formatEvidenceOutcome(item.outcome, t);
                        const confidence = formatEvidenceConfidence(item.confidence, t);
                        const time = formatEvidenceTime(item.timestamp, language);
                        const stage = item.targetPlanStageId
                          ? `${t("evidenceTargetPrefix")}: ${item.targetPlanStageId}`
                          : "";
                        return (
                          <article key={item.id} className="coach-plan-view__evidence-row">
                            <div className="coach-plan-view__evidence-row-head">
                              <div>
                                <strong>{summary}</strong>
                                <p>
                                  {[source, outcome, confidence, time, stage].filter(Boolean).join(" · ")}
                                </p>
                              </div>
                              <StatusLabel
                                label={
                                  item.adopted
                                    ? t("evidenceFilterAdopted")
                                    : item.rejectedAt
                                      ? t("evidenceFilterRejected")
                                      : item.deferredAt
                                        ? t("evidenceFilterDeferred")
                                        : t("pending")
                                }
                              />
                            </div>
                            {concepts ? <p className="coach-plan-view__evidence-concepts">{concepts}</p> : null}
                            {(evidenceActions?.onAdoptEvidence ||
                              evidenceActions?.onRejectEvidence ||
                              evidenceActions?.onDeferEvidence) &&
                            !item.adopted &&
                            !item.rejectedAt &&
                            !(showLiveEvidenceDecisions && !item.deferredAt) ? (
                              <div className="coach-plan-view__evidence-actions">
                                {evidenceActions?.onAdoptEvidence ? (
                                  <ActionButton
                                    tone="accent"
                                    icon={<CheckMarkIcon size={12} />}
                                    label={t("evidenceAdopt")}
                                    onClick={() => evidenceActions.onAdoptEvidence?.(item.id)}
                                    fullWidth={false}
                                  />
                                ) : null}
                                {evidenceActions?.onDeferEvidence ? (
                                  <ActionButton
                                    tone="ghost"
                                    icon={<ChevronDownIcon size={12} />}
                                    label={t("evidenceDefer")}
                                    onClick={() => evidenceActions.onDeferEvidence?.(item.id, summary)}
                                    fullWidth={false}
                                  />
                                ) : null}
                                {evidenceActions?.onRejectEvidence ? (
                                  <ActionButton
                                    tone="ghost"
                                    icon={<TrashIcon size={12} />}
                                    label={t("reject")}
                                    onClick={() => evidenceActions.onRejectEvidence?.(item.id, summary)}
                                    fullWidth={false}
                                  />
                                ) : null}
                              </div>
                            ) : null}
                          </article>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="coach-plan-view__evidence-empty">
                      <WarningIcon size={14} />
                      <p>
                        {t("evidenceNoMatches")}
                      </p>
                    </div>
                  )}
                  </section>
                </details>
              ) : null}
            </div>
            ) : null}
          </details>
        ) : null}
        </article>
      </div>
      )}

      {!compactPrimary && planTab === "plan" && actions?.length ? (
        <section className="coach-plan-view__actions-inline" aria-label={resolvedActionsLabel}>
          <div className="coach-plan-view__actions-stack">
            {actions.map((action) => (
              <ActionButton
                key={action.id}
                className="coach-plan-view__action-button"
                tone={action.tone}
                icon={action.icon}
                label={action.label}
                detail={action.detail}
                disabled={action.disabled}
                onClick={action.onClick}
                fullWidth
              />
            ))}
          </div>
        </section>
      ) : null}
    </section>
  );
}

interface PlanMasteryEntry {
  concept: string;
  score: number;
}

/**
 * Merge FSRS mastery scores already present in the store (plan runtime review
 * points + due review queue) into one score per concept. No fetching: when the
 * store carries no scores the dashboard renders its empty note.
 */
function collectPlanMastery(
  reviewPoints: PlanRuntimeReviewPoint[] | undefined,
  dueReviews: ReviewQueueItem[] | undefined,
): Map<string, number> {
  const masteryByConcept = new Map<string, number>();
  const consider = (concept: string | undefined, score: number | undefined) => {
    const key = concept?.trim();
    if (!key || typeof score !== "number" || !Number.isFinite(score)) {
      return;
    }
    const normalized = Math.max(0, Math.min(score, 1));
    const existing = masteryByConcept.get(key);
    if (existing === undefined || normalized > existing) {
      masteryByConcept.set(key, normalized);
    }
  };
  (dueReviews ?? []).forEach((item) => consider(item.concept, item.masteryScore));
  (reviewPoints ?? []).forEach((item) => consider(item.concept, item.masteryScore));
  return masteryByConcept;
}

/**
 * Learning progress dashboard for the Plan view "进度" tab. Reads the shared
 * workbench store directly (same pattern as StageMaterialsSection) so the plan
 * view props stay untouched.
 */
function PlanDashboard({ plan }: { plan: LearningPlan }) {
  const { t } = useTranslation();
  const stageMaterials = useWorkbenchState((state) => state.stageMaterials);
  const dueReviewCount = useWorkbenchState((state) => state.data.memory.dueReviewCount);
  const dueReviews = useWorkbenchState((state) => state.data.memory.dueReviews);
  const reviewPoints = useWorkbenchState((state) => state.data.planRuntimeStatus?.reviewPoints);

  const totalStages = plan.stages.length;
  const doneStages = plan.stages.filter((stage) => stage.status === "done").length;
  const stagePercent = totalStages > 0 ? Math.round((doneStages / totalStages) * 100) : 0;

  const masteryByConcept = useMemo(
    () => collectPlanMastery(reviewPoints, dueReviews),
    [reviewPoints, dueReviews],
  );
  const masteryEntries = useMemo(
    () =>
      [...masteryByConcept.entries()]
        .map(([concept, score]): PlanMasteryEntry => ({ concept, score }))
        .sort((left, right) => left.score - right.score)
        .slice(0, 5),
    [masteryByConcept],
  );

  const dueCount = typeof dueReviewCount === "number" ? dueReviewCount : dueReviews.length;
  const reviewedCount = masteryByConcept.size;
  const materialCount = Object.values(stageMaterials).reduce(
    (sum, items) => sum + items.length,
    0,
  );
  const stagesWithMaterials = Object.values(stageMaterials).filter(
    (items) => items.length > 0,
  ).length;

  return (
    <section
      className="plan-dashboard"
      data-plan-dashboard="true"
      aria-label={t("planDashboardTabProgress")}
    >
      <div className="plan-dashboard__grid">
        <article
          className="plan-dashboard__block plan-material-enter"
          data-plan-dashboard-block="stages"
          style={{ animationDelay: planStaggerDelay(0) }}
        >
          <h4 className="plan-dashboard__block-title">{t("planDashboardStagesTitle")}</h4>
          <p className="plan-dashboard__metric">
            {doneStages} / {totalStages}
          </p>
          <div
            className="plan-dashboard__bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={stagePercent}
          >
            <div className="plan-dashboard__bar-fill" style={{ width: `${stagePercent}%` }} />
          </div>
        </article>

        <article
          className="plan-dashboard__block plan-material-enter"
          data-plan-dashboard-block="mastery"
          style={{ animationDelay: planStaggerDelay(1) }}
        >
          <h4 className="plan-dashboard__block-title">{t("planDashboardMasteryTitle")}</h4>
          {masteryEntries.length > 0 ? (
            <ul className="plan-dashboard__mastery-list">
              {masteryEntries.map((entry) => {
                const percent = Math.round(entry.score * 100);
                return (
                  <li key={entry.concept} className="plan-dashboard__mastery-item">
                    <span className="plan-dashboard__mastery-name" title={entry.concept}>
                      {entry.concept}
                    </span>
                    <div className="plan-dashboard__bar">
                      <div className="plan-dashboard__bar-fill" style={{ width: `${percent}%` }} />
                    </div>
                    <span className="plan-dashboard__mastery-score">{percent}%</span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="empty-state stage-dashboard-empty">
              <PlanIcon size={16} />
              <p className="empty-state__title">{t("planDashboardMasteryEmpty")}</p>
            </div>
          )}
        </article>

        <article
          className="plan-dashboard__block plan-material-enter"
          data-plan-dashboard-block="reviews"
          style={{ animationDelay: planStaggerDelay(2) }}
        >
          <h4 className="plan-dashboard__block-title">{t("planDashboardReviewTitle")}</h4>
          <p className="plan-dashboard__metric">
            <span>{t("planDashboardReviewDue")} {dueCount}</span>
            <span aria-hidden="true">·</span>
            <span>{t("planDashboardReviewDone")} {reviewedCount}</span>
          </p>
        </article>

        <article
          className="plan-dashboard__block plan-material-enter"
          data-plan-dashboard-block="materials"
          style={{ animationDelay: planStaggerDelay(3) }}
        >
          <h4 className="plan-dashboard__block-title">{t("planDashboardMaterialsTitle")}</h4>
          <p className="plan-dashboard__metric">{materialCount}</p>
          <p className="plan-dashboard__stat">
            {t("planDashboardMaterialsStages")} {stagesWithMaterials} / {totalStages}
          </p>
        </article>
      </div>
    </section>
  );
}

function StatusLabel({ label }: { label: string }) {
  return <span className="coach-plan-view__status">{label}</span>;
}

const STAGE_MATERIAL_KIND_CLASSES: Record<string, string> = {
  study_guide: "stage-material-badge--study-guide",
  cheat_sheet: "stage-material-badge--cheat-sheet",
  exercise_set: "stage-material-badge--exercise-set",
  code_examples: "stage-material-badge--code-examples",
};

function stageMaterialKindClass(kind: string): string {
  return STAGE_MATERIAL_KIND_CLASSES[kind] ?? "stage-material-badge--other";
}

function stageMaterialKindLabel(kind: string, isChinese: boolean): string {
  const labels: Record<string, [string, string]> = {
    study_guide: ["学习指南", "Study guide"],
    cheat_sheet: ["速查卡", "Cheat sheet"],
    exercise_set: ["练习集", "Exercises"],
    code_examples: ["代码示例", "Code examples"],
  };
  const entry = labels[kind];
  if (entry) {
    return isChinese ? entry[0] : entry[1];
  }
  return kind.replace(/_/g, " ").trim() || kind;
}

/** Nominal material kinds a stage can carry — the completion ring and badge count these. */
const STAGE_MATERIAL_KIND_SEQUENCE = [
  "study_guide",
  "cheat_sheet",
  "exercise_set",
  "code_examples",
];

function stageMaterialProgress(
  materials: StageMaterialItem[] | undefined,
  status: PlanStage["status"],
): { completed: number; total: number; percent: number } {
  const total = STAGE_MATERIAL_KIND_SEQUENCE.length;
  if (status === "done") {
    return { completed: total, total, percent: 100 };
  }
  const generatedKinds = new Set((materials ?? []).map((item) => item.kind));
  const completed = STAGE_MATERIAL_KIND_SEQUENCE.filter((kind) => generatedKinds.has(kind)).length;
  return { completed, total, percent: Math.round((completed / total) * 100) };
}

/** Staggered entrance delay: one step per item, capped at the first 8 items. */
function planStaggerDelay(index: number): string {
  return `calc(var(--motion-fast) / 4 * ${Math.min(Math.max(index, 0), 7)})`;
}

function StageProgressRing({ percent, ariaLabel }: { percent: number; ariaLabel: string }) {
  const radius = 7;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(percent, 100));
  return (
    <svg
      className="stage-ring"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      role="img"
      aria-label={`${ariaLabel} ${clamped}%`}
    >
      <circle className="stage-ring__track" cx="8" cy="8" r={radius} strokeWidth="2" />
      <circle
        className="stage-ring__value"
        cx="8"
        cy="8"
        r={radius}
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - clamped / 100)}
        transform="rotate(-90 8 8)"
      />
    </svg>
  );
}

/**
 * The 生成资料 action for one stage. While generation runs the label is replaced
 * by a shimmering skeleton strip that collapses its width (see
 * .stage-material-generate__shimmer), and the button reports busy state.
 */
function StageMaterialGenerateButton({ planId, stageId }: { planId: string; stageId: string }) {
  const { t } = useTranslation();
  const generating = useWorkbenchState((state) =>
    Boolean(state.stageMaterialGenerating[stageId]),
  );
  const requestStageMaterialGeneration = useWorkbenchState(
    (state) => state.requestStageMaterialGeneration,
  );
  const label = generating ? t("planStageMaterialsGenerating") : t("planStageMaterialsGenerate");
  return (
    <button
      type="button"
      className="button button--ghost button--micro stage-material-generate"
      data-stage-materials-generate="true"
      disabled={generating}
      aria-busy={generating}
      aria-label={label}
      onClick={() => requestStageMaterialGeneration(planId, stageId)}
    >
      {generating ? (
        <span className="skeleton stage-material-generate__shimmer" aria-hidden="true" />
      ) : (
        <span>{label}</span>
      )}
    </button>
  );
}

/**
 * One plan stage as a level-1 CollapseSection: the header carries the progress
 * ring, the title/objective, a completed-material-count badge and the 生成资料
 * action; the stage's learning materials render inside as a level-2 section.
 * The active stage additionally gets the accent left-edge bar (.stage-row--active).
 */
function PlanStageSection({
  stage,
  planId,
  isActive,
  statusLabel,
  onStageSelect,
}: {
  stage: PlanStage;
  planId: string;
  isActive: boolean;
  statusLabel: string;
  onStageSelect?: (stage: PlanStage) => void;
}) {
  const { t } = useTranslation();
  const materials = useWorkbenchState((state) => state.stageMaterials[stage.id]);
  const progress = stageMaterialProgress(materials, stage.status);
  const badgeTitle = `${t("planStageMaterialsBadgeTitle")} ${progress.completed}/${progress.total}`;
  return (
    <div
      className={`stage-row${isActive ? " stage-row--active" : ""}`}
      data-plan-stage={stage.id}
      data-stage-status={stage.status}
    >
      <CollapseSection
        level={1}
        persistenceKey={`stage-${stage.id}`}
        defaultOpen={isActive}
        title={
          <span className="stage-block__head">
            <StageProgressRing
              percent={progress.percent}
              ariaLabel={t("planStageCompletionLabel")}
            />
            <span className="stage-block__title-text">{stage.title}</span>
          </span>
        }
        subtitle={
          <span className="stage-block__subtitle">
            <StatusLabel label={statusLabel} />
            <span>{stage.objective}</span>
          </span>
        }
        badge={<span title={badgeTitle}>{progress.completed}/{progress.total}</span>}
        actions={<StageMaterialGenerateButton planId={planId} stageId={stage.id} />}
        onToggle={() => onStageSelect?.(stage)}
      >
        <StageMaterialsSection stageId={stage.id} planId={planId} />
      </CollapseSection>
    </div>
  );
}

/**
 * Per-stage generated study materials as a level-2 CollapseSection. Reads the
 * shared workbench store directly so the plan view stays prop-compatible while
 * materials arrive via host state patches. Newly mounted materials fade in with
 * a capped stagger (.plan-material-enter).
 */
function StageMaterialsSection({ stageId, planId }: { stageId: string; planId: string }) {
  const { t, language } = useTranslation();
  const materials = useWorkbenchState((state) => state.stageMaterials[stageId]);
  const generating = useWorkbenchState((state) =>
    Boolean(state.stageMaterialGenerating[stageId]),
  );
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const items = materials ?? [];
  const isChinese = language === "zh-CN";

  return (
    <CollapseSection
      level={2}
      persistenceKey={`stage-materials-${stageId}`}
      title={t("planStageMaterialsTitle")}
      badge={items.length > 0 ? items.length : undefined}
      defaultOpen
    >
      <div className="coach-plan-view__stage-materials" data-stage-materials={stageId}>
        {items.length === 0 ? (
          <div className="empty-state stage-material-empty" data-stage-materials-empty="true">
            <PlanIcon size={16} />
            <p className="empty-state__title">
              {generating ? t("planStageMaterialsGenerating") : t("planStageMaterialsEmpty")}
            </p>
            <div className="empty-state__action">
              <StageMaterialGenerateButton planId={planId} stageId={stageId} />
            </div>
          </div>
        ) : (
          <ul className="coach-plan-view__stage-material-list">
            {items.map((item, index) => {
              const expanded = expandedId === item.id;
              const summary = item.summary.replace(/\s+/g, " ").trim();
              return (
                <li
                  key={item.id}
                  className="coach-plan-view__stage-material-item plan-material-enter"
                  style={{ animationDelay: planStaggerDelay(index) }}
                >
                  <button
                    type="button"
                    className="coach-plan-view__stage-material-toggle"
                    aria-expanded={expanded}
                    onClick={() => setExpandedId(expanded ? null : item.id)}
                  >
                    <span className="coach-plan-view__stage-material-title">
                      <strong>{item.title}</strong>
                      <span className={`stage-material-badge ${stageMaterialKindClass(item.kind)}`}>
                        {stageMaterialKindLabel(item.kind, isChinese)}
                      </span>
                    </span>
                    {summary ? (
                      <span className="coach-plan-view__stage-material-summary">{summary}</span>
                    ) : null}
                    <span className="coach-plan-view__stage-material-action">
                      {expanded ? t("planStageMaterialsHide") : t("planStageMaterialsView")}
                    </span>
                  </button>
                  {expanded ? (
                    <pre className="coach-plan-view__stage-material-content">{item.content}</pre>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </CollapseSection>
  );
}
