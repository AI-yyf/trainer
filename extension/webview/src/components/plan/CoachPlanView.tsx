import { LearningHome } from "../../templates/LearningHome";
import { SystemState } from "../../templates/SystemState";
import { templateCopy } from "../../templates/templateCopy";
import { trainingViewLabel } from "../../lib/viewLabels";
import {
  isValidElement,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import {
  describeSafeStructuredValue,
  sanitizeErrorSurfaceText,
} from "../../../../../shared/src/errorSurfaceSanitizer";

import { ActionButton } from "../common";
import { MessageRichContent } from "../coach/MessageRichContent";
import {
  CheckMarkIcon,
  ChevronDownIcon,
  ArrowRightIcon,
  LinkIcon,
  PlanIcon,
  TrashIcon,
} from "../icons";
import { useTranslation } from "../../lib/i18n/useTranslation";
import { resolvePlanViewCopy } from "../../lib/i18n/planViewCopy";
import { reviewConceptLabel } from "../../lib/reviewLabel";
import { useWorkbenchState } from "../../app/useWorkbenchState";
import type {
  EvidenceQueueView,
  GlobalPlan,
  PlanChangeCandidateView,
  GlobalPlanProjectLink,
  LearningPlan,
  PlanRuntimeReviewPoint,
  PlanStage,
  ReviewQueueItem,
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
  /** §30: navigate to internal routes (progress, training). */
  onNavigateToView?: (view: "coach" | "plan" | "resources" | "training" | "progress" | "settings") => void;
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
  | "backTo"
  | "narrowNext"
  | "needsConfirmation"
  | "evidenceUnchanged"
  | "evidenceUnchangedDetail"
  | "chatEvidenceNoRewrite"
  | "verifyFirst"
  | "reviewPending"
  | "planLocked"
  | "formalPlanFrozen"
  | "continueCurrent"
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
  | "leftoverOutlineMore"
  | "narrowNextHint"
  | "reviewFocusFallback"
  | "notesLabel"
  | "supportHint"
  | "revisitLabel"
  | "actionsLabel"
  | "resumeInCoach"
  | "returnLabel"
  | "moreLabel"
  | "followOneThread"
  | "currentThread"
  | "planStatusLabel"
  | "projectPlansLabel"
  | "thenPrefix"
  | "verifyFallback"
  | "returnFallback"
  | "stageProgress"
  | "trainerRemembers"
  | "teachingObservationsLabel"
  | "sourceShortlist"
  | "overviewLabel"
  | "currentPlanRoute"
  | "threadContext"
  | "planChangeCandidatesLabel"
  | "pendingConfirmation"
  | "candidateNeedsConfirmation"
  | "diffLabel"
  | "noVisibleDiff"
  | "impactLabel"
  | "noVisibleImpact"
  | "adoptAdjustment"
  | "dismissAdjustment"
  | "surfaceAhead"
  | "surfaceDigest"
  | "surfaceDue"
  | "masteryBandIndependent"
  | "masteryBandAssisted"
  | "masteryBandEmerging"
  | "intervalDays"
  | "reviewLaneFallback";

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
    backTo: "回到：{step}",
    narrowNext: "先收束下一步。",
    needsConfirmation: "待确认",
    evidenceUnchanged: "证据还没有改写计划",
    chatEvidenceNoRewrite: "聊天证据不会静默重写正式计划。",
    verifyFirst: "先验证：{step}",
    reviewPending: "先处理待确认内容。",
    planLocked: "计划已锁定",
    formalPlanFrozen: "正式计划已锁定",
    continueCurrent: "先继续当前步骤。",
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
    narrowNextHint: "先把这一步做完，再扩大范围。",
    reviewFocusFallback: "当前步骤稳了再回看。",
    notesLabel: "备注",
    supportHint: "先走完上面的当前主线。",
    revisitLabel: "回看",
    actionsLabel: "动作",
    resumeInCoach: "回到对话",
    returnLabel: "回流",
    moreLabel: "更多",
    followOneThread: "先只看这一条主线",
    currentThread: "当前主线",
    planStatusLabel: "计划状态",
    projectPlansLabel: "项目子计划",
    thenPrefix: "再后面：{step}",
    verifyFallback: "完成后做一次最小验证，确认这一步真的成立。",
    returnFallback: "带着验证结果回到对话，再决定这条主线的下一步。",
    stageProgress: "第 {index} / {total} 段",
    evidenceUnchangedDetail: "证据还没有改写计划。",
    trainerRemembers: "教练已记住",
    teachingObservationsLabel: "教学观察",
    sourceShortlist: "来源短名单",
    overviewLabel: "概览",
    currentPlanRoute: "当前计划路线",
    threadContext: "主线说明",
    planChangeCandidatesLabel: "计划变更候选",
    pendingConfirmation: "待确认",
    candidateNeedsConfirmation: "这条候选还需要确认。",
    diffLabel: "差异",
    noVisibleDiff: "没有可展示的差异。",
    impactLabel: "影响",
    noVisibleImpact: "没有可展示的影响。",
    adoptAdjustment: "采纳调整",
    dismissAdjustment: "忽略",
    surfaceAhead: "提前提醒",
    surfaceDigest: "合并回看",
    surfaceDue: "到期回看",
    masteryBandIndependent: "独立完成",
    masteryBandAssisted: "有辅助完成",
    masteryBandEmerging: "初步接触",
    intervalDays: "{days} 天间隔",
    reviewLaneFallback: "做完当前切片后，再安排这次回看。",
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
    backTo: "Back to: {step}",
    narrowNext: "Narrow the next step first.",
    needsConfirmation: "Needs confirmation",
    evidenceUnchanged: "Evidence has not changed the plan",
    chatEvidenceNoRewrite: "Chat evidence will not rewrite it silently.",
    verifyFirst: "Verify first: {step}",
    reviewPending: "Review pending items first.",
    planLocked: "Plan locked",
    formalPlanFrozen: "Formal plan is frozen",
    continueCurrent: "Continue the current step first.",
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
    narrowNextHint: "Narrow the next step first.",
    reviewFocusFallback: "Continue the current step first.",
    notesLabel: "Notes",
    supportHint: "Continue the current step first.",
    revisitLabel: "Revisit",
    actionsLabel: "Actions",
    resumeInCoach: "Resume in Coach",
    returnLabel: "Return",
    moreLabel: "More",
    followOneThread: "Follow one thread first",
    currentThread: "Current thread",
    planStatusLabel: "Plan status",
    projectPlansLabel: "Project plans",
    thenPrefix: "Then: {step}",
    verifyFallback: "Run one small verification to confirm this step really landed.",
    returnFallback: "Return to Coach with the verified result before moving the thread forward.",
    stageProgress: "Stage {index} of {total}",
    evidenceUnchangedDetail: "Evidence has not changed the plan",
    trainerRemembers: "Trainer remembers",
    teachingObservationsLabel: "Teaching observations",
    sourceShortlist: "Source shortlist",
    overviewLabel: "Overview",
    currentPlanRoute: "Current plan route",
    threadContext: "Thread context",
    planChangeCandidatesLabel: "Plan change candidates",
    pendingConfirmation: "Pending confirmation",
    candidateNeedsConfirmation: "This candidate still needs confirmation.",
    diffLabel: "Diff",
    noVisibleDiff: "No visible diff.",
    impactLabel: "Impact",
    noVisibleImpact: "No visible impact.",
    adoptAdjustment: "Adopt adjustment",
    dismissAdjustment: "Dismiss",
    surfaceAhead: "Ahead",
    surfaceDigest: "Digest",
    surfaceDue: "Due",
    masteryBandIndependent: "Independent",
    masteryBandAssisted: "Assisted",
    masteryBandEmerging: "Emerging",
    intervalDays: "{days}-day interval",
    reviewLaneFallback: "Schedule this revisit after the current slice lands.",
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
    backTo: "Volver a: {step}",
    narrowNext: "Aclara primero el siguiente paso.",
    needsConfirmation: "Necesita confirmación",
    evidenceUnchanged: "La evidencia aún no ha cambiado el plan",
    chatEvidenceNoRewrite: "La evidencia del chat no cambiará el plan formal en silencio.",
    verifyFirst: "Verifica primero: {step}",
    reviewPending: "Revisa primero los elementos pendientes.",
    planLocked: "Plan bloqueado",
    formalPlanFrozen: "El plan formal está congelado",
    continueCurrent: "Continúa primero con el paso actual.",
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
    narrowNextHint: "Completa primero este paso antes de ampliar el alcance.",
    reviewFocusFallback: "Continúa primero con el paso actual.",
    notesLabel: "Notas",
    supportHint: "Termina primero el hilo actual de arriba.",
    revisitLabel: "Repasar",
    actionsLabel: "Acciones",
    resumeInCoach: "Volver al coach",
    returnLabel: "Retorno",
    moreLabel: "Más",
    followOneThread: "Sigue primero un solo hilo",
    currentThread: "Hilo actual",
    planStatusLabel: "Estado del plan",
    projectPlansLabel: "Planes del proyecto",
    thenPrefix: "Después: {step}",
    verifyFallback: "Ejecuta una verificación mínima para confirmar que este paso realmente quedó hecho.",
    returnFallback:
      "Vuelve al coach con el resultado verificado antes de avanzar el hilo.",
    stageProgress: "Etapa {index} de {total}",
    evidenceUnchangedDetail: "La evidencia aún no ha cambiado el plan",
    trainerRemembers: "El trainer lo recuerda",
    teachingObservationsLabel: "Observaciones de enseñanza",
    sourceShortlist: "Lista corta de fuentes",
    overviewLabel: "Resumen",
    currentPlanRoute: "Ruta actual del plan",
    threadContext: "Contexto del hilo",
    planChangeCandidatesLabel: "Candidatos de cambio del plan",
    pendingConfirmation: "Pendiente de confirmación",
    candidateNeedsConfirmation: "Este candidato todavía necesita confirmación.",
    diffLabel: "Diff",
    noVisibleDiff: "No hay diff visible.",
    impactLabel: "Impacto",
    noVisibleImpact: "No hay impacto visible.",
    adoptAdjustment: "Aceptar el ajuste",
    dismissAdjustment: "Ignorar",
    surfaceAhead: "Anticipado",
    surfaceDigest: "Resumen",
    surfaceDue: "A vencer",
    masteryBandIndependent: "Independiente",
    masteryBandAssisted: "Con ayuda",
    masteryBandEmerging: "Primeros pasos",
    intervalDays: "intervalo de {days} días",
    reviewLaneFallback: "Programe este repaso cuando aterrice el fragmento actual.",
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
    blockerDetailMissing: "Le détail du blocage n’est pas disponible.",
    backTo: "Retour à : {step}",
    narrowNext: "Précisez d’abord la prochaine étape.",
    needsConfirmation: "À confirmer",
    evidenceUnchanged: "La preuve n’a pas encore modifié le plan",
    chatEvidenceNoRewrite: "Les preuves du chat ne réécrivent pas le plan formel en silence.",
    verifyFirst: "Vérifiez d’abord : {step}",
    reviewPending: "Examinez d’abord les éléments en attente.",
    planLocked: "Plan verrouillé",
    formalPlanFrozen: "Le plan formel est gelé",
    continueCurrent: "Continuez d’abord l’étape actuelle.",
    emptyOutlineLabel: "Ce que montrera le plan",
    connectFirst: "Connectez-vous d’abord",
    workingConnection: "Activez une connexion utilisable",
    formalPlanHonest: "Le plan formel reste honnête tant qu’aucune connexion n’est utilisable.",
    formalThread: "Fil formel",
    compressThread: "Le coach concentre d’abord un seul fil",
    noSilentMutation: "Il garde une seule action actuelle sans transformer silencieusement le chat en plan formel.",
    emptyVerify: "Vérifier",
    everyStepReturns: "Chaque étape revient à la vérification",
    completionFlow: "Les résultats comme les blocages reviennent au plan formel.",
    leftoverNotLive: "Ceci est un reste enregistré sur cet espace, pas le plan actuel.",
    leftoverOutlineMore: "Ce que le plan montrera",
    narrowNextHint: "Terminez d’abord cette étape avant d’élargir le périmètre.",
    reviewFocusFallback: "Continuez d’abord l’étape actuelle.",
    notesLabel: "Notes",
    supportHint: "Terminez d’abord le fil courant ci-dessus.",
    revisitLabel: "Réviser",
    actionsLabel: "Actions",
    resumeInCoach: "Reprendre dans Coach",
    returnLabel: "Retour",
    moreLabel: "Plus",
    followOneThread: "Suivez d’abord un seul fil",
    currentThread: "Fil courant",
    planStatusLabel: "Statut du plan",
    projectPlansLabel: "Plans de projet",
    thenPrefix: "Ensuite: {step}",
    verifyFallback: "Faites une petite vérification pour confirmer que cette étape est vraiment acquise.",
    returnFallback:
      "Revenez dans Coach avec le résultat vérifié avant de faire avancer le fil.",
    stageProgress: "Étape {index} sur {total}",
    evidenceUnchangedDetail: "La preuve n’a pas encore modifié le plan",
    trainerRemembers: "Trainer s’en souvient",
    teachingObservationsLabel: "Observations pédagogiques",
    sourceShortlist: "Présélection de sources",
    overviewLabel: "Aperçu",
    currentPlanRoute: "Parcours actuel du plan",
    threadContext: "Contexte du fil",
    planChangeCandidatesLabel: "Candidats de modification du plan",
    pendingConfirmation: "À confirmer",
    candidateNeedsConfirmation: "Ce candidat attend encore une confirmation.",
    diffLabel: "Diff",
    noVisibleDiff: "Aucun diff visible.",
    impactLabel: "Impact",
    noVisibleImpact: "Aucun impact visible.",
    adoptAdjustment: "Adopter l’ajustement",
    dismissAdjustment: "Ignorer",
    surfaceAhead: "En avance",
    surfaceDigest: "Synthèse",
    surfaceDue: "À échéance",
    masteryBandIndependent: "Indépendant",
    masteryBandAssisted: "Avec aide",
    masteryBandEmerging: "Premiers pas",
    intervalDays: "intervalle de {days} jours",
    reviewLaneFallback: "Programmez cette révision une fois le tronçon actuel terminé.",
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
    backTo: "Zurück zu: {step}",
    narrowNext: "Grenzen Sie zuerst den nächsten Schritt ein.",
    needsConfirmation: "Bestätigung nötig",
    evidenceUnchanged: "Die Evidenz hat den Plan noch nicht geändert",
    chatEvidenceNoRewrite: "Chat-Evidenz schreibt den formellen Plan nicht stillschweigend um.",
    verifyFirst: "Zuerst prüfen: {step}",
    reviewPending: "Prüfen Sie zuerst die offenen Punkte.",
    planLocked: "Plan gesperrt",
    formalPlanFrozen: "Der formelle Plan ist eingefroren",
    continueCurrent: "Fahren Sie zuerst mit dem aktuellen Schritt fort.",
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
    narrowNextHint: "Schließen Sie zuerst diesen Schritt ab, bevor Sie den Umfang erweitern.",
    reviewFocusFallback: "Fahren Sie zuerst mit dem aktuellen Schritt fort.",
    notesLabel: "Notizen",
    supportHint: "Laufen Sie zuerst den aktuellen Pfad oben zu Ende.",
    revisitLabel: "Wiederholen",
    actionsLabel: "Aktionen",
    resumeInCoach: "Im Coach fortsetzen",
    returnLabel: "Rückfluss",
    moreLabel: "Mehr",
    followOneThread: "Folgen Sie zuerst einem einzigen Pfad",
    currentThread: "Aktueller Pfad",
    planStatusLabel: "Planstatus",
    projectPlansLabel: "Projektpläne",
    thenPrefix: "Danach: {step}",
    verifyFallback: "Führen Sie eine kleine Prüfung durch, um zu bestätigen, dass dieser Schritt wirklich sitzt.",
    returnFallback:
      "Kehren Sie mit dem überprüften Ergebnis in den Coach zurück, bevor Sie den Pfad weiterführen.",
    stageProgress: "Phase {index} von {total}",
    evidenceUnchangedDetail: "Die Evidenz hat den Plan noch nicht geändert",
    trainerRemembers: "Trainer hat es behalten",
    teachingObservationsLabel: "Didaktische Beobachtungen",
    sourceShortlist: "Kurzauswahl der Quellen",
    overviewLabel: "Überblick",
    currentPlanRoute: "Aktuelle Planroute",
    threadContext: "Pfad-Kontext",
    planChangeCandidatesLabel: "Kandidaten für Planänderungen",
    pendingConfirmation: "Bestätigung ausstehend",
    candidateNeedsConfirmation: "Dieser Kandidat muss noch bestätigt werden.",
    diffLabel: "Diff",
    noVisibleDiff: "Kein sichtbarer Diff.",
    impactLabel: "Auswirkung",
    noVisibleImpact: "Keine sichtbare Auswirkung.",
    adoptAdjustment: "Anpassung übernehmen",
    dismissAdjustment: "Ignorieren",
    surfaceAhead: "Im Voraus",
    surfaceDigest: "Zusammenfassung",
    surfaceDue: "Fällig",
    masteryBandIndependent: "Selbstständig",
    masteryBandAssisted: "Mit Hilfe",
    masteryBandEmerging: "Erste Schritte",
    intervalDays: "{days}-Tage-Intervall",
    reviewLaneFallback: "Planen Sie diese Wiederholung, sobald der aktuelle Abschnitt landet.",
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
    backTo: "戻る：{step}",
    narrowNext: "次の一手を先に絞り込みます。",
    needsConfirmation: "確認待ち",
    evidenceUnchanged: "証拠はまだ計画を変えていません",
    chatEvidenceNoRewrite: "チャットの証拠で正式な計画を書き換えることはありません。",
    verifyFirst: "先に確認：{step}",
    reviewPending: "保留中の項目を先に確認します。",
    planLocked: "計画は固定されています",
    formalPlanFrozen: "正式な計画は固定されています",
    continueCurrent: "現在のステップを先に続けます。",
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
    narrowNextHint: "まずこの一手を終えてから、範囲を広げます。",
    reviewFocusFallback: "現在のステップを先に続けます。",
    notesLabel: "メモ",
    supportHint: "まず上の現在の流れを進めます。",
    revisitLabel: "復習",
    actionsLabel: "操作",
    resumeInCoach: "Coach に戻る",
    returnLabel: "回流",
    moreLabel: "さらに表示",
    followOneThread: "まず一本の流れだけを見る",
    currentThread: "現在の流れ",
    planStatusLabel: "計画の状態",
    projectPlansLabel: "プロジェクト計画",
    thenPrefix: "次回: {step}",
    verifyFallback: "小さな検証を一度行い、このステップが本当に成立したかを確かめます。",
    returnFallback:
      "検証結果を持って Coach に戻り、この流れの次の一手を決めます。",
    stageProgress: "ステージ {index} / {total}",
    evidenceUnchangedDetail: "証拠はまだ計画を変えていません",
    trainerRemembers: "Trainer が記憶しました",
    teachingObservationsLabel: "指導上の観察",
    sourceShortlist: "ソース短リスト",
    overviewLabel: "概要",
    currentPlanRoute: "現在の計画ルート",
    threadContext: "流れの補足",
    planChangeCandidatesLabel: "計画変更の候補",
    pendingConfirmation: "確認待ち",
    candidateNeedsConfirmation: "この候補はまだ確認が必要です。",
    diffLabel: "差分",
    noVisibleDiff: "表示できる差分はありません。",
    impactLabel: "影響",
    noVisibleImpact: "表示できる影響はありません。",
    adoptAdjustment: "調整を採用",
    dismissAdjustment: "無視",
    surfaceAhead: "先取り",
    surfaceDigest: "まとめ",
    surfaceDue: "期限",
    masteryBandIndependent: "自力で完了",
    masteryBandAssisted: "ヒント付き",
    masteryBandEmerging: "学び始め",
    intervalDays: "{days} 日間隔",
    reviewLaneFallback: "現在のスライスが終わったら、この復習を予定します。",
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
    backTo: "돌아가기: {step}",
    narrowNext: "다음 단계를 먼저 좁혀 보세요.",
    needsConfirmation: "확인 필요",
    evidenceUnchanged: "증거가 아직 계획을 바꾸지 않았습니다",
    chatEvidenceNoRewrite: "대화 증거가 공식 계획을 조용히 바꾸지 않습니다.",
    verifyFirst: "먼저 확인: {step}",
    reviewPending: "보류 중인 항목을 먼저 확인하세요.",
    planLocked: "계획이 고정되었습니다",
    formalPlanFrozen: "공식 계획이 고정되었습니다",
    continueCurrent: "현재 단계를 먼저 계속하세요.",
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
    narrowNextHint: "이 단계를 먼저 끝낸 다음 범위를 넓히세요.",
    reviewFocusFallback: "현재 단계를 먼저 계속하세요.",
    notesLabel: "메모",
    supportHint: "먼저 위의 현재 흐름을 끝내세요.",
    revisitLabel: "복습",
    actionsLabel: "동작",
    resumeInCoach: "코치로 돌아가기",
    returnLabel: "회류",
    moreLabel: "더 보기",
    followOneThread: "먼저 하나의 흐름만 보세요",
    currentThread: "현재 흐름",
    planStatusLabel: "계획 상태",
    projectPlansLabel: "프로젝트 계획",
    thenPrefix: "다음: {step}",
    verifyFallback: "작은 검증을 한 번 실행해 이 단계가 정말 자리 잡았는지 확인하세요.",
    returnFallback:
      "검증 결과를 가지고 코치로 돌아온 뒤 이 흐름의 다음 단계를 정하세요.",
    stageProgress: "{total}단계 중 {index}",
    evidenceUnchangedDetail: "증거가 아직 계획을 바꾸지 않았습니다",
    trainerRemembers: "Trainer가 기억합니다",
    teachingObservationsLabel: "학습 지도 관찰",
    sourceShortlist: "출처 후보 목록",
    overviewLabel: "개요",
    currentPlanRoute: "현재 계획 경로",
    threadContext: "흐름 설명",
    planChangeCandidatesLabel: "계획 변경 후보",
    pendingConfirmation: "확인 대기",
    candidateNeedsConfirmation: "이 후보는 아직 확인이 필요합니다.",
    diffLabel: "차이",
    noVisibleDiff: "표시할 차이가 없습니다.",
    impactLabel: "영향",
    noVisibleImpact: "표시할 영향이 없습니다.",
    adoptAdjustment: "조정 수용",
    dismissAdjustment: "무시",
    surfaceAhead: "예습",
    surfaceDigest: "요약",
    surfaceDue: "기한",
    masteryBandIndependent: "독립 완료",
    masteryBandAssisted: "도움 받음",
    masteryBandEmerging: "시작 단계",
    intervalDays: "{days}일 간격",
    reviewLaneFallback: "현재 조각이 끝나면 이 복습을 예약하세요.",
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
    backTo: "Voltar para: {step}",
    narrowNext: "Defina primeiro o próximo passo.",
    needsConfirmation: "Precisa de confirmação",
    evidenceUnchanged: "A evidência ainda não mudou o plano",
    chatEvidenceNoRewrite: "A evidência da conversa não reescreve o plano formal silenciosamente.",
    verifyFirst: "Verifique primeiro: {step}",
    reviewPending: "Revise primeiro os itens pendentes.",
    planLocked: "Plano bloqueado",
    formalPlanFrozen: "O plano formal está congelado",
    continueCurrent: "Continue primeiro a etapa atual.",
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
    narrowNextHint: "Conclua primeiro esta etapa antes de ampliar o escopo.",
    reviewFocusFallback: "Continue primeiro a etapa atual.",
    notesLabel: "Notas",
    supportHint: "Termine primeiro o fluxo atual acima.",
    revisitLabel: "Revisar",
    actionsLabel: "Ações",
    resumeInCoach: "Voltar ao coach",
    returnLabel: "Retorno",
    moreLabel: "Mais",
    followOneThread: "Siga primeiro um único fluxo",
    currentThread: "Fluxo atual",
    planStatusLabel: "Status do plano",
    projectPlansLabel: "Planos do projeto",
    thenPrefix: "Depois: {step}",
    verifyFallback: "Faça uma verificação mínima para confirmar que esta etapa realmente ficou pronta.",
    returnFallback:
      "Volte ao coach com o resultado verificado antes de avançar este fluxo.",
    stageProgress: "Estágio {index} de {total}",
    evidenceUnchangedDetail: "A evidência ainda não mudou o plano",
    trainerRemembers: "O trainer lembra",
    teachingObservationsLabel: "Observações de ensino",
    sourceShortlist: "Lista curta de fontes",
    overviewLabel: "Visão geral",
    currentPlanRoute: "Rota atual do plano",
    threadContext: "Contexto do fluxo",
    planChangeCandidatesLabel: "Candidatos a mudança do plano",
    pendingConfirmation: "Aguardando confirmação",
    candidateNeedsConfirmation: "Este candidato ainda precisa de confirmação.",
    diffLabel: "Diff",
    noVisibleDiff: "Nenhum diff visível.",
    impactLabel: "Impacto",
    noVisibleImpact: "Nenhum impacto visível.",
    adoptAdjustment: "Aceitar o ajuste",
    dismissAdjustment: "Ignorar",
    surfaceAhead: "Adiantado",
    surfaceDigest: "Resumo",
    surfaceDue: "A vencer",
    masteryBandIndependent: "Independente",
    masteryBandAssisted: "Com ajuda",
    masteryBandEmerging: "Primeiros passos",
    intervalDays: "intervalo de {days} dias",
    reviewLaneFallback: "Agende esta revisão quando a fatia atual ficar pronta.",
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
  language: PlanLanguage,
): string | undefined {
  if (mode === "ahead") {
    return planCopy(language, "surfaceAhead");
  }
  if (mode === "digest") {
    return planCopy(language, "surfaceDigest");
  }
  if (mode === "due") {
    return planCopy(language, "surfaceDue");
  }
  return undefined;
}

/**
 * §八: canonical capability band for review mastery scores — one honest state
 * label instead of a fake percentage. Unscored items stay unlabeled. Shared
 * wording with the progress surface: >=0.8 independent, >=0.5 assisted,
 * otherwise emerging. No numeric percent, no bars implying precision.
 */
function capabilityBandLabel(score: number | undefined, language: PlanLanguage): string | undefined {
  if (typeof score !== "number" || Number.isNaN(score) || score <= 0) {
    return undefined;
  }
  if (score >= 0.8) {
    return planCopy(language, "masteryBandIndependent");
  }
  if (score >= 0.5) {
    return planCopy(language, "masteryBandAssisted");
  }
  return planCopy(language, "masteryBandEmerging");
}

function intervalLabel(days: number | undefined, language: PlanLanguage): string | undefined {
  if (typeof days !== "number" || Number.isNaN(days)) {
    return undefined;
  }
  return planCopy(language, "intervalDays", { days });
}

function compactReviewMeta(item: PlanReviewItem, language: PlanLanguage): string | undefined {
  const meta = [
    item.meta,
    surfaceModeLabel(item.surfaceMode, language),
    intervalLabel(item.intervalDays, language),
    capabilityBandLabel(item.masteryScore, language),
  ].filter(Boolean) as string[];
  return meta.length > 0 ? meta.join(" · ") : undefined;
}

function compactReviewLane(item: PlanReviewItem, language: PlanLanguage): string {
  const lead =
    item.taskHint ??
    item.focusArea ??
    item.detail ??
    planCopy(language, "reviewLaneFallback");
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

const RECOVERED_PLAN_ACTION_IDS = new Set([
  "resume-plan",
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

/**
 * Decision card derived from real runtime facts only (pending evidence count,
 * frozen flag, blocker). No invented governance rows: when nothing needs
 * attention the strip is absent entirely.
 */
function resolvePlanDecisionStrip(input: {
  language: PlanLanguage;
  pendingEvidenceCount: number;
  currentStep: ReactNode;
  verifyNow: ReactNode;
  planFrozen: boolean;
  blockedReason?: string;
}): PlanDecisionStripState | null {
  const currentStep = inlineText(input.currentStep);
  const verifyNow = inlineText(input.verifyNow);
  const blockerDetail = input.blockedReason?.trim() ?? "";
  const hasBlocker = blockerDetail.length > 0;
  const hasPendingEvidence = input.pendingEvidenceCount > 0 && !input.planFrozen;

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
      detail: planCopy(input.language, "evidenceUnchangedDetail"),
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

  return null;
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
  const planViewText = resolvePlanViewCopy(language);
  const composerDraftReplacementCancelRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!composerDraftReplacement) {
      return;
    }

    composerDraftReplacementCancelRef.current?.focus();
  }, [composerDraftReplacement?.source, composerDraftReplacement?.title]);

  const resolvedEyebrow = props.eyebrow ?? t("plan");
  const resolvedEmptyTitle = props.title ?? t("plan");
  const resolvedCurrentStageLabel =
    props.currentStageLabel ?? t("planStages");
  const resolvedGoalLabel = props.goalLabel ?? t("goals");
  const resolvedNextStepLabel =
    props.nowLabel ?? props.nextStepLabel ?? t("nextMove");
  const resolvedNextStepHint =
    props.nextStepHint ?? planCopy(language, "narrowNextHint");
  const resolvedNextStepResumeThread = props.nextStepResumeThread?.trim();
  const resolvedStagesLabel = props.stagesLabel ?? t("planStages");
  const resolvedMemoryLabel = props.memoryLabel ?? t("currentFocus");
  const resolvedWinsLabel = props.winsLabel ?? t("recentWins");
  const resolvedWeakSpotsLabel = props.weakSpotsLabel ?? t("weakSpots");
  const resolvedReviewLabel = props.reviewLabel ?? t("reviewRhythm");
  const resolvedReviewFocusLabel =
    props.reviewFocusLabel ?? planCopy(language, "reviewFocusFallback");
  const resolvedCoachingStateLabel = props.coachingStateLabel ?? t("backgroundCoachWork");
  const resolvedSupportSummaryLabel = props.supportSummaryLabel ?? t("backgroundCoachWork");
  const resolvedNotesLabel = props.notesLabel ?? planCopy(language, "notesLabel");
  const resolvedSupportHint = props.supportHint ?? planCopy(language, "supportHint");
  const resolvedWhyNowLabel = props.whyNowLabel ?? props.summaryLabel ?? t("trainingWhyNow");
  const resolvedVerifyLabel = props.verifyLabel ?? t("acceptance");
  const resolvedReviewWindowLabel =
    props.reviewWindowLabel ?? planCopy(language, "revisitLabel");
  const resolvedActionsLabel = props.actionsLabel ?? planCopy(language, "actionsLabel");
  const resolvedResumeActionLabel =
    resumeActionLabel ?? planCopy(language, "resumeInCoach");
  const resolvedReturnLabel =
    props.returnLabel ??
    props.laterLabel ??
    props.pathSummaryLabel ??
    planCopy(language, "returnLabel");
  const resolvedDetailsSummaryLabel =
    props.detailsSummaryLabel ?? planCopy(language, "moreLabel");
  const resolvedLinearOverviewLabel =
    props.overviewLabel ?? planCopy(language, "followOneThread");
  const resolvedMainlineLabel =
    props.planAtGlanceLabel ?? planCopy(language, "currentThread");
  const shouldRepeatGoalLabel =
    resolvedGoalLabel.trim().length > 0 && resolvedGoalLabel.trim() !== resolvedMainlineLabel.trim();
  const resolvedRevisitSummaryLabel =
    props.revisitSummaryLabel ?? planCopy(language, "revisitLabel");
  const resolvedGovernanceLabel =
    props.governanceLabel ?? planCopy(language, "planStatusLabel");
  const resolvedProjectSubplansLabel =
    props.projectSubplansLabel ?? planCopy(language, "projectPlansLabel");
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
          // Demoted from accent: the NextAction "continue current step" stays
          // the single accent primary on this surface.
          tone: "ghost",
          onClick: props.onCreateGlobalPlan,
        }
      : undefined
    : !globalPlan.frozen && plan && !hasCurrentProjectPlanLink && props.onLinkCurrentProjectPlan
      ? {
          id: "link-current-project-plan",
          label: t("globalPlanLinkCurrentProject"),
          icon: <LinkIcon size={12} />,
          tone: "ghost",
          onClick: props.onLinkCurrentProjectPlan,
        }
      : undefined;
  const globalPlanContextKey = [
    globalPlan?.id ?? "none",
    plan?.id ?? "none",
    hasCurrentProjectPlanLink ? "linked" : "unlinked",
    globalPlan?.frozen ? "frozen" : "live",
  ].join(":");
  const shouldShowGlobalPlanContext = Boolean(
    globalPlan || props.onCreateGlobalPlan || props.onLinkCurrentProjectPlan,
  );
  // Always collapsed: the global↔project relationship must not compete with the
  // current step. The key forces a remount (and thus a re-collapse) when the
  // relationship state changes.
  const globalPlanContext = shouldShowGlobalPlanContext ? (
    <details
      key={globalPlanContextKey}
      className="coach-plan-view__details coach-plan-view__global-plan-context"
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
        onKeyDown={(event) => { if (event.key === "Escape" && composerDraftReplacement) { event.stopPropagation(); composerDraftReplacement.onCancel(); } }}
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

  const pendingEvidenceItems = useMemo(() => evidenceQueue?.pending ?? [], [evidenceQueue]);
  const settledEvidenceItems = useMemo(
    () => [
      ...(evidenceQueue?.deferred ?? []),
      ...(evidenceQueue?.adopted ?? []),
      ...(evidenceQueue?.rejected ?? []),
      ...(evidenceQueue?.unscoped ?? []),
      ...(evidenceQueue?.history ?? []),
    ],
    [evidenceQueue],
  );
  const evidenceCounts = useMemo(
    () => ({
      pending: evidenceQueue?.pending.length ?? 0,
      deferred: evidenceQueue?.deferred.length ?? 0,
      adopted: evidenceQueue?.adopted.length ?? 0,
      rejected: evidenceQueue?.rejected.length ?? 0,
      history: evidenceQueue?.history?.length ?? 0,
      unscoped: evidenceQueue?.unscoped?.length ?? 0,
      total: evidenceQueue?.totalCount ?? 0,
    }),
    [evidenceQueue],
  );
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
  if (!plan) {
    return (
      <section className="template-learning-home" data-template="LearningHome" data-plan-leftover-not-live={leftoverNote ? "true" : undefined}>
        <SystemState kind="empty" title={resolvedEmptyTitle} detail={leftoverNote ? <p data-plan-leftover-note="true">{leftoverNote}</p> : emptyState}
          action={emptyPrimaryAction?.onClick ? { label: emptyPrimaryAction.label, onClick: emptyPrimaryAction.onClick, disabled: emptyPrimaryAction.disabled } : undefined}>
          {emptyPrimaryAction?.id === "plan-review-evidence" ? liveEvidenceDecisionRow : null}
        </SystemState>
        {renderComposerDraftReplacement("stage")}
        {emptySecondaryActions.length ? <details className="template-disclosure"><summary>{resolvedActionsLabel}</summary><div>{emptySecondaryActions.map((action) => <ActionButton key={action.id} tone="ghost" label={action.label} disabled={action.disabled} onClick={action.onClick} />)}</div></details> : null}
        {globalPlanContext}
        <button type="button" className="template-back" onClick={() => props.onNavigateToView?.("training")}>{trainingViewLabel(language)}</button>
        <button type="button" className="template-back" onClick={() => props.onNavigateToView?.("progress")}>{templateCopy[language].growth}</button>
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
  const queuedStageCount = plan.stages.filter((stage) => stage.status === "queued").length;
  const totalStageCount = Math.max(plan.stages.length, 1);
  const activeStageIndex = Math.max(plan.stages.findIndex((stage) => stage.id === activeStage?.id), 0) + 1;
  const upcomingStages = plan.stages.filter((stage) => stage.status === "queued");
  const previewStages = upcomingStages.slice(0, 3);
  const laterSecondaryStage = previewStages[1] ?? null;
  const pathProgressNote =
    plan.stages.length === 0 ? "" : formatQueuedStageSummary(queuedStageCount, language);
  const laterContinuationNote = laterSecondaryStage
    ? planCopy(language, "thenPrefix", { step: laterSecondaryStage.title })
    : undefined;
  const verifyFallback = planCopy(language, "verifyFallback");
  const recoveredVerifyLocked =
    Boolean(plan.currentStep?.trim()) &&
    !(plan.verifyMethod ?? []).some((item) => Boolean(item.trim()));
  const returnFallback = planCopy(language, "returnFallback");
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
    : planCopy(language, "stageProgress", { index: activeStageIndex, total: totalStageCount });
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
  const planDecisionStrip = resolvePlanDecisionStrip({
    language,
    pendingEvidenceCount,
    currentStep: currentStepText,
    verifyNow: verifyText,
    planFrozen: plan.frozen,
    blockedReason,
  });
  const shouldShowDecisionCard = !hideDecisionStrip && planDecisionStrip !== null;
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
    return [compactPrimary ? "" : reviewFirst, queued].find((text) => text && text !== now && text !== done) ?? "";
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
          label: props.rememberedSummaryLabel ?? planCopy(language, "trainerRemembers"),
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
          label: props.teachingObservationsLabel ?? planCopy(language, "teachingObservationsLabel"),
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
  const detailSections = [
    hasStageDetails ? resolvedStagesLabel : null,
    hasReviewDetails ? resolvedRevisitSummaryLabel : null,
    hasTrajectoryDetails ? (props.trajectoryLabel ?? planCopy(language, "sourceShortlist")) : null,
    hasBackgroundDetails ? resolvedSupportSummaryLabel : null,
    hasEvidenceDetails ? planViewText.practiceRecordsLabel : null,
  ].filter(Boolean) as string[];
  const detailsSummary =
    compactPrimary && detailSections.length > 0
      ? resolvedDetailsSummaryLabel
      : `${resolvedDetailsSummaryLabel}${detailSections.length ? ` · ${detailSections.join(" / ")}` : ""}`;
  const primarySummaryChips = compactPrimary ? [] : summaryChips;
  const primaryRouteStripItems = routeStripItems;

  const nextAction = compactPrimaryAction ?? pickPlanPrimaryAction(actions);
  return (
    <LearningHome
      currentLabel={templateCopy[language].currentLearning}
      title={plan.title}
      stage={stageProgressText ? `${stageProgressText} · ${activeStageTitle}` : activeStageTitle}
      state={shouldShowDecisionCard && planDecisionStrip ? <SystemState kind={plan.frozen ? "read-only" : "recoverable-error"} title={planDecisionStrip.title} detail={planDecisionStrip.detail} /> : undefined}
      next={{ label: resolvedNextStepLabel, title: inlineText(currentLane.body) || activeStageTitle,
        detail: shouldShowDecisionCard && planDecisionStrip && (plan.frozen || blockedReason)
          ? <div data-plan-fact="next">{planDecisionStrip.next}</div>
          : <div data-plan-fact="next"><span>{templateCopy[language].complete}: </span>{verifyText}</div>,
        action: { label: nextAction?.label ?? templateCopy[language].askCoach, disabled: nextAction?.disabled,
          onClick: nextAction?.onClick ?? (() => props.onNavigateToView?.("coach")) } }}
      nextTools={nextAction?.id === "plan-review-evidence" ? liveEvidenceDecisionRow : undefined}
      review={hasReviewDetails ? { label: resolvedRevisitSummaryLabel, content: <>
        {reviewSupportRow ? renderNodeWithParagraph(reviewSupportRow.body) : null}
        {props.dueReviewItems?.slice(0, 4).map((item) => <div key={item.id}><strong>{item.title}</strong><p>{compactReviewLane(item, language)}</p></div>)}
        <button type="button" className="template-back" onClick={() => useWorkbenchState.getState().openTrainingReviewQueue()}>{templateCopy[language].startReview}</button>
      </> } : undefined}
      route={{ label: resolvedStagesLabel, content: <>
        {renderComposerDraftReplacement("stage")}
        {plan.stages.map((stage) => <PlanStageSection key={stage.id} stage={stage} planId={plan.id} isActive={stage.id === activeStage?.id} statusLabel={resolveStageStatusLabel(stage.status, stageStatusLabels?.[stage.status], language)} />)}
      </> }}
      growth={{ label: templateCopy[language].growth, content: (
        <button type="button" className="template-back" data-plan-growth-link="progress" onClick={() => props.onNavigateToView?.("progress")}>{planViewText.viewGrowth}</button>
      ) }}
      evidence={hasEvidenceDetails ? { label: `${planViewText.practiceRecordsLabel} (${evidenceCounts.total})`, content: <>
        {liveEvidenceDecisionRow}
        <section
          className={`coach-plan-view__details-group coach-plan-view__details-group--evidence is-${evidenceTone}`}
          aria-label={planViewText.practiceRecordsLabel}
        >
          {pendingEvidenceItems.length > 0 ? (
            <div className="coach-plan-view__evidence-list">
              {pendingEvidenceItems.map((item) => {
                const summary = inlineText(item.summary);
                const outcome = formatEvidenceOutcome(item.outcome, t);
                const time = formatEvidenceTime(item.timestamp, language);
                return (
                  <article key={item.id} className="coach-plan-view__evidence-row" data-plan-evidence-row="pending">
                    <div className="coach-plan-view__evidence-row-head">
                      <div>
                        <strong>{summary}</strong>
                        <p>{[outcome, time].filter(Boolean).join(" · ")}</p>
                      </div>
                      <StatusLabel label={t("pending")} />
                    </div>
                    {(evidenceActions?.onAdoptEvidence ||
                      evidenceActions?.onRejectEvidence ||
                      evidenceActions?.onDeferEvidence) &&
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
          ) : null}
          {settledEvidenceItems.length > 0 ? (
            <div className="coach-plan-view__evidence-list coach-plan-view__evidence-list--settled">
              {settledEvidenceItems.map((item) => {
                const summary = inlineText(item.summary);
                const outcome = formatEvidenceOutcome(item.outcome, t);
                const time = formatEvidenceTime(item.timestamp, language);
                const state = item.adopted
                  ? t("evidenceFilterAdopted")
                  : item.rejectedAt
                    ? t("evidenceFilterRejected")
                    : item.deferredAt
                      ? t("evidenceFilterDeferred")
                      : t("history");
                return (
                  <article key={item.id} className="coach-plan-view__evidence-row coach-plan-view__evidence-row--settled" data-plan-evidence-row="settled">
                    <div className="coach-plan-view__evidence-row-head">
                      <div>
                        <strong>{summary}</strong>
                        <p>{[state, outcome, time].filter(Boolean).join(" · ")}</p>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : null}
        </section>
      </> } : undefined}
    >
      {leftoverNote ? <p className="template-metadata" data-plan-leftover-note="true" role="status" aria-live="polite">{leftoverNote}</p> : null}
      {renderComposerDraftReplacement("project-subplan")}
      <details className="template-disclosure"><summary>{t("globalPlanLabel")}</summary><div>{globalPlanContext}</div></details>
      {projectSubplans.length > 0 ? <details className="template-disclosure coach-plan-view__project-subplans"><summary>{`${resolvedProjectSubplansLabel} (${projectSubplans.length})`}</summary><div>{projectSubplans.map((subplan) => {
        const detail = projectSubplanDetail(subplan, language);
        return <button key={subplan.id} type="button" className="template-back" disabled={!props.onProjectSubplanSelect} onClick={() => props.onProjectSubplanSelect?.(subplan)}><span>{subplan.title}</span>{detail ? <span className="template-metadata"> · {detail}</span> : null}</button>;
      })}</div></details> : null}
      <details className="template-disclosure" data-plan-governance-disclosure="true">
        <summary>{resolvedDetailsSummaryLabel}</summary>
        <div>
          {backgroundRows.map((row) => <div key={row.id}>{renderNodeWithParagraph(row.body)}</div>)}
          {noteRows.map((row) => <p key={row.id}>{row.label}: {row.value}</p>)}
          {(actions ?? []).filter((action) => action.id !== nextAction?.id).map((action) => <ActionButton key={action.id} tone="ghost" label={action.label} detail={action.detail} disabled={action.disabled} onClick={action.onClick} />)}
          {planChangeCandidates.map((candidate) => <div key={candidate.id}>
            <p>{sanitizeErrorSurfaceText(candidate.reason, language)}</p>
            <p>{describeSafeStructuredValue(candidate.diff, language, planCopy(language, "noVisibleDiff"))}</p>
            <p>{describeSafeStructuredValue(candidate.impact, language, planCopy(language, "noVisibleImpact"))}</p>
            {candidate.status === "pending" ? <>
              <ActionButton tone="ghost" label={planCopy(language, "adoptAdjustment")} onClick={() => onAcknowledgePlanChange?.(candidate.id)} />
              <ActionButton tone="ghost" label={planCopy(language, "dismissAdjustment")} onClick={() => onRejectPlanChange?.(candidate.id)} />
            </> : null}
          </div>)}
        </div>
      </details>
    </LearningHome>
  );
}

function StatusLabel({ label }: { label: string }) {
  return <span className="coach-plan-view__status">{label}</span>;
}

/** Staggered entrance delay: one step per item, capped at the first 8 items. */
function planStaggerDelay(index: number): string {
  return `calc(var(--motion-fast) / 4 * ${Math.min(Math.max(index, 0), 7)})`;
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
 * One plan stage as a simple text row: title plus one status word. The stage's
 * materials and the 生成资料 action live inside a nested <details> that is
 * closed by default, so the roadmap stays quiet until the learner opens it.
 * The active stage additionally gets the accent left-edge bar (.stage-row--active).
 */
function PlanStageSection({
  stage,
  planId,
  isActive,
  statusLabel,
}: {
  stage: PlanStage;
  planId: string;
  isActive: boolean;
  statusLabel: string;
}) {
  return (
    <div
      className={`stage-row${isActive ? " stage-row--active" : ""}`}
      data-plan-stage={stage.id}
      data-stage-status={stage.status}
    >
      <details
        className="template-disclosure coach-plan-view__stage-details"
      >
        <summary>
          <span className="stage-block__title-text">{stage.title}</span>
          <StatusLabel label={statusLabel} />
        </summary>
        <div className="coach-plan-view__details-body">
          {stage.objective ? <p className="coach-plan-view__lane-note">{stage.objective}</p> : null}
          <StageMaterialGenerateButton planId={planId} stageId={stage.id} />
          <StageMaterialsSection stageId={stage.id} />
        </div>
      </details>
    </div>
  );
}

/**
 * Per-stage generated study materials, rendered inside the stage's nested
 * details. Reads the shared workbench store directly so the plan view stays
 * prop-compatible while materials arrive via host state patches. Newly mounted
 * materials fade in with a capped stagger (.plan-material-enter).
 */
function StageMaterialsSection({ stageId }: { stageId: string }) {
  const { t, language } = useTranslation();
  const materials = useWorkbenchState((state) => state.stageMaterials[stageId]);
  const generating = useWorkbenchState((state) =>
    Boolean(state.stageMaterialGenerating[stageId]),
  );
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const items = materials ?? [];

  return (
    <div className="coach-plan-view__stage-materials" data-stage-materials={stageId}>
      {items.length === 0 ? (
        <div className="empty-state stage-material-empty" data-stage-materials-empty="true">
          <PlanIcon size={16} />
          <p className="empty-state__title">
            {generating ? t("planStageMaterialsGenerating") : t("planStageMaterialsEmpty")}
          </p>
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
                  </span>
                  {summary ? (
                    <span className="coach-plan-view__stage-material-summary">{summary}</span>
                  ) : null}
                  <span className="coach-plan-view__stage-material-action">
                    {expanded ? t("planStageMaterialsHide") : t("planStageMaterialsView")}
                  </span>
                </button>
                {expanded ? (
                  <div className="coach-plan-view__stage-material-content">
                    <MessageRichContent body={item.content} language={language} />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
