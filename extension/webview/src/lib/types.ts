import type { TrainerCommandCatalogItem } from "../../../../shared/src/commands";
import type { TrainerMessagePart, TrainerStreamingState } from "../../../../shared/src/protocol";
import type { ResourceSearchMode } from "../../../../shared/src/resourceSearch";
import type { ComposerLanguage as SharedComposerLanguage } from "../../../../shared/src/types";
import type {
  ProviderCapabilityEvidence,
  ProviderCapabilityVerificationState,
} from "../../../../shared/src/providerTest";

export type ThemePreference = "system" | "light" | "dark";
export type LearningSurfaceAlignment = "left" | "right";
export type TeachingStyle = "auto" | "guided" | "concept-first" | "hands-on" | "challenging";
export type CoachAnswerMode = "auto" | "coach-first" | "balanced" | "direct";

export function normalizeTeachingStyle(value: string | null | undefined): TeachingStyle {
  if (value === "auto" || value === "concept-first" || value === "hands-on" || value === "challenging") {
    return value;
  }
  if (value === "guided") {
    return value;
  }
  return "auto";
}

import type {
  FirstLookSummary as SharedFirstLookSummary,
  ProviderProtocol,
  ProjectSourceSuggestion,
  WorkspaceUnderstandingSnapshot as SharedWorkspaceUnderstandingSnapshot,
} from '../../../../shared/src/models';
export type { ProviderProtocol, ProjectSourceSuggestion } from '../../../../shared/src/models';
export type FirstLookSummary = SharedFirstLookSummary;
export type WorkspaceUnderstandingSnapshot = SharedWorkspaceUnderstandingSnapshot;

export interface CapabilityFlags {
  chat: boolean;
  responses: boolean;
  vision: boolean;
  embeddings: boolean;
  tools: boolean;
  jsonSchema: boolean;
  structuredOutput: boolean;
  streaming: boolean;
  thinking?: boolean;
}

export interface ProviderModelTokenLimit {
  contextWindowTokens?: number;
  maxOutputTokens?: number;
}

export interface ProviderSummary {
  name: string;
  model: string;
  capabilities: CapabilityFlags;
  protocol?: ProviderProtocol;
  protocolFamily?: string;
}

export interface ProviderLastTestResult {
  ok: boolean;
  status: string;
  detail: string;
  checkedAt: string;
  workspaceId?: string;
  profileId?: string;
  providerName: string;
  baseUrl: string;
  model: string;
  protocol?: ProviderProtocol;
  protocolFamily?: string;
  errorCategory?: string;
  retryable?: boolean;
  statusCode?: number;
  responseLanguage?: ComposerLanguage;
  capabilityEvidence?: ProviderCapabilityEvidence[];
  toolsReady?: boolean;
  toolProbeStatus?: ProviderCapabilityVerificationState;
  streamingReady?: boolean;
  streamProbeStatus?: ProviderCapabilityVerificationState;
  thinkingReady?: boolean;
  thinkingProbeStatus?: ProviderCapabilityVerificationState;
  visionReady?: boolean;
  visionProbeStatus?: ProviderCapabilityVerificationState;
}

export interface ProviderConfigView {
  configured: boolean;
  name: string;
  baseUrl: string;
  model: string;
  contextWindowTokens?: number;
  maxOutputTokens?: number;
  apiKeyConfigured: boolean;
  capabilities: CapabilityFlags;
  requestDefaults?: Record<string, unknown>;
  protocol?: ProviderProtocol;
  protocolFamily?: string;
  connectionType?: string;
  credentialMode?: "workspace_secret" | "ui_proxy";
  profileId?: string;
  profileLabel?: string;
  profileMode?: string;
  profileCount?: number;
  availableModels: string[];
  catalogModels?: string[];
  allowedModels?: string[];
  deniedModels?: string[];
  modelAliases?: Record<string, string>;
  resolvedModel?: string;
  modelCapabilities?: Record<string, CapabilityFlags>;
  modelTokenLimits?: Record<string, ProviderModelTokenLimit>;
  taskBindings?: Record<string, unknown>;
  embeddingModel?: string;
  catalogSource?: 'provider_live' | 'cached' | 'manual';
  cacheTtlSeconds?: number;
  modelListStatus: "idle" | "loading" | "ready" | "error";
  modelListDetail?: string;
  cacheFetchedAt?: string;
  cacheExpiresAt?: string;
  cacheSource?: "live" | "cache";
  modelErrorCategory?: string;
  modelStatusCode?: number;
  modelRetryable?: boolean;
  workspaceSecretConfigured?: boolean;
  protocolDiagnostic?: Record<string, unknown>;
  taskBindingDiagnostics?: Array<Record<string, unknown>>;
  modelDiagnostics?: Array<Record<string, unknown>>;
  modelTest?: Record<string, unknown>;
  modelListing?: Record<string, unknown>;
  diagnostics?: string[];
  warnings?: string[];
  profileHistory?: Array<Record<string, unknown>>;
  providerProfiles?: Array<Record<string, unknown>>;
  providerDashboard?: Record<string, unknown>;
  lastTestResult?: ProviderLastTestResult;
}

export interface ProviderConfig {
  name: string;
  baseUrl: string;
  apiKeyRef: string;
  model: string;
  protocol?: ProviderProtocol;
  label?: string;
  mode?: 'direct' | 'gateway';
  credentialMode?: 'workspace_secret' | 'ui_proxy';
  capabilities: CapabilityFlags;
  availableModels?: string[];
  catalogModels?: string[];
  allowedModels?: string[];
  deniedModels?: string[];
  modelAliases?: Record<string, string>;
  modelCapabilities?: Record<string, CapabilityFlags>;
  modelTokenLimits?: Record<string, ProviderModelTokenLimit>;
  taskBindings?: Record<string, unknown>;
  requestDefaults?: Record<string, unknown>;
  contextWindowTokens?: number;
  maxOutputTokens?: number;
  embeddingModel?: string;
  catalogSource?: 'provider_live' | 'cached' | 'manual';
  cacheTtlSeconds?: number;
  profileId?: string;
  profileLabel?: string;
  profileMode?: string;
  profileCount?: number;
  profileHistory?: Array<Record<string, unknown>>;
  providerProfiles?: Array<Record<string, unknown>>;
  providerDashboard?: Record<string, unknown>;
}

export interface UserProfile {
  learnerName: string;
  goals: string[];
  weeklyHours: number;
  preferredStyle: string;
  answerPolicy: CoachAnswerMode;
  focusAreas: string[];
  targetProject?: string;
  preferredRhythm?: string;
  preferredLearningMode?: string;
  onboardingRequest?: string;
  projectContext?: string;
}

export interface PlanStage {
  id: string;
  title: string;
  objective: string;
  status: "done" | "active" | "queued";
}

export interface SubPlan {
  id: string;
  parentPlanId: string;
  title: string;
  description: string;
  stages: PlanStage[];
  status: "draft" | "active" | "completed" | "archived";
  progressPercent: number;
  createdAt: string;
  updatedAt: string;
}

export interface LearningPlan {
  id: string;
  title: string;
  frozen: boolean;
  cadence: string;
  summary: string;
  stages: PlanStage[];
  currentStageId?: string;
  currentStep?: string;
  whyNow?: string;
  verifyMethod?: string[];
  blockedReason?: string;
  nextAfterCurrent?: string;
}

export interface GlobalPlan {
  id: string;
  title: string;
  summary: string;
  goals: string[];
  stages: PlanStage[];
  frozen: boolean;
  currentProjectPlanId?: string;
  currentStageId?: string;
  currentStep?: string;
  whyNow?: string;
  verifyMethod?: string[];
}

export interface GlobalPlanProjectLink {
  globalPlanId: string;
  workspaceId: string;
  projectPlanId: string;
  linkedAt: string;
  updatedAt: string;
}

export interface PlanRuntimeReviewPoint {
  concept: string;
  reason: string;
  severity?: "low" | "medium" | "high";
  dueAt?: string;
  source?: string;
  surfaceMode?: "due" | "ahead" | "digest";
  taskHint?: string;
  focusArea?: string;
  linkedContext?: string[];
  intervalDays?: number;
  masteryScore?: number;
}

export interface NextStepHint {
  title: string;
  summary?: string;
  recommendedAction?: SuggestedAction["action"];
  focusArea?: string;
  prompt?: string;
  resumeThread?: string;
  source?:
    | "agent_loop"
    | "coach_turn"
    | "active_thread"
    | "coaching_state"
    | "plan"
    | "implementation_guide"
    | "evaluation"
    | "task"
    | "review";
  continueIn?: "coach" | "plan" | "training";
  verification?: string[];
}

export interface PlanRuntimeStatus {
  currentStage?: {
    id?: string;
    title?: string;
    goal?: string;
    status?: string;
  };
  currentMainThread?: {
    scenario?: string;
    focusArea?: string;
    summary?: string;
    nextStep?: string;
    blocker?: string;
    currentStep?: string;
    whyNow?: string;
    verifyMethod?: string[];
    blockedReason?: string;
    nextAfterCurrent?: string;
    verifiedResult?: string;
  };
  reviewPoints: PlanRuntimeReviewPoint[];
  coachJudgment?: {
    summary?: string;
    teachingGoal?: string;
    interventionStrategy?: string;
    supportStrategy?: string;
    resumeThread?: string;
  };
  nextTrainingAction?: string;
  reviewQueueSummary?: string;
  nextReviewDue?: string;
  currentStep?: string;
  currentStageId?: string;
  whyNow?: string;
  verifyMethod?: string[];
  blockedReason?: string;
  nextAfterCurrent?: string;
  nextStepHint?: NextStepHint;
  recovered?: boolean;
  resumeState?: "interrupted" | "in_progress" | "waiting";
  requestId?: string;
  revision?: number;
  verifyPlanAdvance?: {
    advanced?: boolean;
    what?: string;
    why?: string;
    next?: string;
    planId?: string | null;
  };
}

export interface TaskSpec {
  id: string;
  title: string;
  description: string;
  constraints: string[];
  acceptanceCriteria: string[];
  nextActionLabel: string;
}

export interface EvaluationCheck {
  id: string;
  label: string;
  status: "pass" | "fail" | "warn" | "pending";
  detail: string;
}

export interface EvaluationReport {
  headline: string;
  summary: string;
  passRate: number;
  updatedAt: string;
  checks: EvaluationCheck[];
  nextStep: string;
}

export interface ReviewQueueItem {
  concept: string;
  reason: string;
  dueAt?: string;
  source: "weakness" | "mastery" | "reflection" | "plan";
  severity: "low" | "medium" | "high";
  surfaceMode?: "due" | "ahead" | "digest";
  taskHint?: string;
  focusArea?: string;
  linkedContext?: string[];
  intervalDays?: number;
  masteryScore?: number;
}

export interface CoachingState {
  scenario:
    | "general"
    | "onboarding"
    | "idea_implementation"
    | "project_idea"
    | "project_adaptation"
    | "project_sourcing"
    | "principle"
    | "remote_workspace"
    | "debug_loop"
    | "function_guidance"
    | "review"
    | "plan"
    | "task"
    | "next_task";
  answerMode: "guided" | "balanced" | "direct";
  learnerSignal: "steady" | "blocked" | "uncertain" | "curious";
  summary: string;
  nextStep: string;
  encouragement: string;
  interventionStrategy?: string;
  teachingGoal?: string;
  resumeThread?: string;
  decision?: string;
  blocker?: string;
  teachingNote?: string;
  confidence?: string;
  evidence?: string[];
  supportStrategy?: string;
  updatedAt: string;
}

export interface LearnerState {
  currentConfidence: number;
  frustrationLevel: number;
  attemptCountRecent: number;
  needsRescue: boolean;
  needsReview: boolean;
  preferredHintDepth: string;
  learnerSignal: "steady" | "blocked" | "uncertain" | "curious";
  activeFocus: string;
  evidence: string[];
}

export interface AffectState {
  frustrationLevel: number;
  confidenceLevel: number;
  momentumLevel: number;
  needsReassurance: boolean;
  urgencyLevel: "low" | "medium" | "high";
}

export interface TeachingDecision {
  mode:
    | "onboarding"
    | "idea_implementation"
    | "project_idea_mining"
    | "project_adaptation"
    | "planning"
    | "concept_teaching"
    | "engineering_challenge"
    | "review_reflection"
    | "project_sourcing"
    | "principle_explanation"
    | "guided"
    | "scaffold"
    | "balanced"
    | "direct_rescue"
    | "challenge"
    | "reflection";
  reason: string;
  primaryGoal: string;
  lessonShape: string;
  exerciseShape: string;
  teachingStrategy: string;
  closingMove: string;
  artifactPriority: string[];
  shouldEndWithQuestion: boolean;
  shouldGenerateExercise: boolean;
  shouldRevealCode: boolean;
  shouldProducePlanArtifact: boolean;
  shouldTriggerDeepAnalysis: boolean;
  shouldFocusOnImplementationSteps: boolean;
  toneProfile:
    | "steady"
    | "guided_build"
    | "proactive_coach"
    | "steady_migration"
    | "teaching_clarity"
    | "review_loop"
    | "concise_rescue";
  focusArea?: string;
}

export interface ToneDecision {
  tone: "steady" | "encouraging" | "concise_rescue" | "reflective";
  verbosityBias: "short" | "medium" | "expanded";
  acknowledgeProgress: boolean;
  avoidOverwhelm: boolean;
}

export interface ImplementationGuide {
  ideaSummary: string;
  scopeBoundary: string;
  mvpDefinition: string;
  currentStep: string;
  nextSteps: string[];
  validationStrategy: string[];
  openQuestions: string[];
  codebaseEntryPoints?: string[];
  riskNotes?: string[];
  teachingGoal?: string;
  successSignal?: string;
  fallbackStep?: string;
}

export interface ProjectIdea {
  id: string;
  title: string;
  summary: string;
  sourceArea: string;
  ideaKind: "feature" | "refactor" | "test" | "architecture" | "developer_experience";
  learningValue: string;
  engineeringValue: string;
  difficulty: string;
  suggestedScope: string;
  firstStep: string;
  acceptanceSignals: string[];
  whyNow: string;
}

export interface ProjectAdaptationGuide {
  targetOutcome: string;
  currentConstraints: string[];
  affectedAreas: string[];
  preserveAreas: string[];
  firstMigrationStep: string;
  migrationSequence: string[];
  validationCheckpoints: string[];
  rollbackNotes: string[];
}

export interface PrincipleNote {
  currentPrinciple: string;
  whyItMatters: string;
  commonMistake: string;
  applyNow: string;
  transferTargets: string[];
  concreteAnchor?: string;
  transferableLesson?: string;
  relatedChecks?: string[];
  sourceAssetTitle?: string;
}

export interface CoachTurnSummaryView {
  scenario:
    | "general"
    | "onboarding"
    | "idea_implementation"
    | "project_idea"
    | "project_adaptation"
    | "project_sourcing"
    | "principle"
    | "remote_workspace"
    | "debug_loop"
    | "function_guidance"
    | "review"
    | "plan"
    | "task"
    | "next_task";
  learnerSignal: "steady" | "blocked" | "uncertain" | "curious";
  summary: string;
  nextStep: string;
  encouragement?: string;
  interventionStrategy?: string;
  teachingGoal?: string;
  resumeThread?: string;
  decision?: string;
  blocker?: string;
  teachingNote?: string;
  confidence?: string;
  evidence?: string[];
  supportStrategy?: string;
  decisionReason?: string;
  tone?: ToneDecision["tone"];
  verbosityBias?: ToneDecision["verbosityBias"];
  activeStage?: string;
  activeTask?: string;
  dueReviewCount?: number;
  reviewQueueSummary?: string;
  failingChecks?: string[];
  artifactKinds?: ConversationArtifactKind[];
  suggestedActionTypes?: SuggestedAction["action"][];
  backgroundMode?: "embedded";
}

export interface CoachOrientationView {
  objectKind?: "provider" | "workspace" | "conversation" | "plan" | "training";
  objectLabel?: string;
  state?: "needs_setup" | "waiting" | "working" | "blocked" | "ready" | "interrupted";
  why?: string;
  primaryAction?:
    | "open_settings"
    | "open_plan"
    | "open_training"
    | "compose"
    | "wait"
    | "retry"
    | "resume_checkpoint";
  primaryActionLabel?: string;
  nextStep?: string;
  advancedWhere?: string;
  source?: "snapshot";
  revision?: number;
}

export interface CoachFocusView {
  currentFocus?: string;
  reviewRhythm?: string;
  nextStep?: string;
  activeStage?: string;
  activeTask?: string;
  scenario?: CoachTurnSummaryView["scenario"];
  relationshipStage?: "intake" | "active";
  firstTurnPriority?: string;
  strategyPreferenceSummary?: string;
  continuitySummary?: string;
  recentTeachingSignals?: string[];
  teachingObservations?: string[];
  recentWins?: string[];
  dueReviewCount?: number;
  language?: string;
  /** Turn stamp from backend `pressure_blocks_live_object_mint`. */
  pressureBlocksLiveObjectMint?: boolean;
  /** Turn stamp from backend `streak_blocks_live_object_mint`. */
  streakBlocksLiveObjectMint?: boolean;
  /** Turn stamp from backend `closed_loop_return_blocks_task_mint`. */
  closedLoopReturnBlocksTaskMint?: boolean;
}

export interface ActiveThreadView {
  scenario?: string;
  focusArea?: string;
  summary?: string;
  nextStep?: string;
  blocker?: string;
  verifiedResult?: string;
  decision?: string;
  teachingNote?: string;
  confidence?: string;
  evidence?: string[];
  updatedAt?: string;
}

export interface ResourceRecord {
  id: string;
  title: string;
  kind: "pdf" | "image" | "markdown" | "text" | "code" | "url";
  status: "ready" | "indexing" | "attention";
  summary: string;
  source?: string;
  collectionPath?: string;
  collectionRoot?: string;
  canonicalSource?: string;
  sourceItems?: string[];
  tags?: string[];
  warnings?: string[];
  sourceType?: string;
  fileType?: string;
  projectScope?: string;
  trustState?: string;
  trustScore?: number;
  freshness?: "fresh" | "stale" | "unknown";
  indexState?: string;
  citationId?: string;
  previewTier?: "rich" | "converted" | "metadata";
  previewKind?: string;
  rankScore?: number;
  rankReasons?: string[];
  matchSummary?: string;
  canInjectTrainingCard?: boolean;
  qualityFlags?: string[];
  sandboxPath?: string;
  sandboxOrigin?: string;
  sandboxSyncedAt?: string;
  sandboxDirty?: boolean;
  extractedArtifactPath?: string;
  updatedAt?: string;
}

export interface ResourceDetailRecord extends ResourceRecord {}

export type ResourceTrainingHandoffOutcome = "ready" | "blocked" | "not-current" | "failed";
export type ResourceTrainingHandoffReason =
  | "resource_missing"
  | "resource_needs_refresh"
  | "connection"
  | "unavailable";

export interface ResourceTrainingHandoffResult {
  requestId: string;
  resourceId: string;
  outcome: ResourceTrainingHandoffOutcome;
  reason?: ResourceTrainingHandoffReason;
  generatedCardId?: string;
  selectedCardId?: string;
}

export interface ResourceSearchState {
  requestId?: string;
  workspaceId?: string;
  query: string;
  total: number;
  rankingStrategy?: string;
  filters: Record<string, string>;
  hits: ResourceDetailRecord[];
}

export interface DeletedResource {
  resourceId: string;
  title: string;
  deletedAt?: string;
  collectionPath?: string;
  recoverable: boolean;
}

export interface SandboxPreview {
  path: string;
  relativePath?: string;
  title?: string;
  fileKind?: string;
  previewTier?: string;
  previewKind?: string;
  languageHint?: string;
  renderedFrom?: string;
  content?: string;
  excerpt?: string;
  html?: string;
  isBinary?: boolean;
  isEditable?: boolean;
  canNativeOpen?: boolean;
  structuredData?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  assetUri?: string;
}

export interface WorkspaceAuthority {
  activeWorkspaceRoot?: string;
  rootUri?: string;
  authoritySource?: string;
  remoteName?: string;
  authorityMode?: string;
  authorityScope?: "project" | "trainer_sandbox" | string;
  resourceWriteAllowed?: boolean;
  resourceWriteEvidence?: {
    operation?: string;
    scope?: string;
    targetRoot?: string;
    allowed?: boolean;
    reason?: string;
  };
  permissionLevel?: string;
  permissionLabel?: string;
  allowedOperations?: string[];
  mountedSources?: string[];
  ledgerEntryCount?: number;
  checkpointCount?: number;
  trashRoot?: string;
  nextSafeAction?: string;
  projectAuthority?: WorkspaceAuthority | null;
  sandboxAuthority?: WorkspaceAuthority | null;
}

export type TrainerProjectAdmissionStatus =
  | "root-missing"
  | "project-found"
  | "managed"
  | "browse"
  | "ignored";

export type TrainerWorkspaceReconciliationState = "waiting" | "retry-required";
export type TrainerWorkspaceReconciliationAction = "continue-waiting" | "retry" | "abandon";

export interface TrainerWorkspaceReconciliation {
  reason: string;
  jobId?: string;
  updatedAt: string;
  state: TrainerWorkspaceReconciliationState;
  availableActions: readonly TrainerWorkspaceReconciliationAction[];
}

export interface TrainerWorkspaceAdmission {
  status: TrainerProjectAdmissionStatus;
  rootPath?: string;
  projectId?: string;
  projectName?: string;
  projectPath?: string;
  updatedAt?: string;
  reconciliation?: TrainerWorkspaceReconciliation;
}

export type MemoryShareCategory = "preferences" | "mastery";

export interface MemoryShareGrant {
  sourceWorkspaceId: string;
  targetWorkspaceId: string;
  categories: MemoryShareCategory[];
  createdAt?: string;
  updatedAt?: string;
}

export interface ManagedDataFolder {
  configuredPath?: string;
  effectivePath: string;
  defaultPath: string;
  source: "recommended" | "custom";
  status: "ready";
}

export interface SandboxState {
  rootPath?: string;
  sandboxRootPath?: string;
  workspaceRootPath?: string;
  activeWorkspaceRoot?: string;
  trashRootPath?: string;
  managedRoots?: string[];
  ready?: boolean;
  linkedResourceCount?: number;
  totalFiles?: number;
  totalDirectories?: number;
  totalSizeBytes?: number;
  lastUpdatedAt?: string;
  selectedPath?: string;
  nodes?: Array<Record<string, unknown>>;
  notes?: string[];
  preview?: SandboxPreview;
  recentCommands?: Array<Record<string, unknown>>;
  latestCommand?: Record<string, unknown> | null;
  authority?: WorkspaceAuthority;
  capabilitySummary?: Record<string, unknown>;
  threatSummary?: Record<string, unknown>;
}

export interface MemoryLayerView {
  layer: string;
  title: string;
  summary: string;
  status: "active" | "quiet" | "empty";
  evidenceCount: number;
  highlights: string[];
  canInjectTrainingCard?: boolean;
  resourceSignals?: Array<{ key: string; signal: string; sourceFocus?: string; scenario?: string }>;
  teachingAssets?: Array<{ id: string; title: string; focusArea?: string; trustScore?: number }>;
}

export interface TransferSkillStateView {
  concept?: string;
  state?: "project_only" | "awaiting_second_scene" | "transferable";
  sceneCount?: number;
  workspaceIds?: string[];
  sceneKeys?: string[];
  why?: string;
  next?: string;
}

export interface CoachingAdaptationView {
  challengeLevel?: "lower" | "steady" | "raise";
  hintDepth?: "direct" | "guided" | "lighter";
  reviewUrgency?: "high" | "normal" | "low";
  explanationMode?: "rebuild" | "grounded" | "transfer";
  nextStepBias?: "shrink" | "steady" | "widen";
  summary?: string;
  evidence?: string[];
  difficulty?: "easy" | "medium" | "hard";
  hintCount?: number;
  explanationDepth?: "rebuild" | "grounded" | "transfer";
  codeReveal?: "full" | "scaffold" | "withhold";
  practiceType?: "recover" | "focused" | "stretch";
  reviewFrequency?: "sooner" | "normal" | "later";
  materialRecommendation?: "simpler" | "current" | "transfer";
  nextPlanStep?: "shrink" | "hold" | "widen";
  shouldRevealCode?: boolean;
  successStreak?: number;
  failureStreak?: number;
  pedagogyMode?: "socratic" | "direct" | "debug_guide";
  transferSceneCount?: number;
  timeBudget?: "tight" | "normal" | "ample";
  projectComplexity?: "simple" | "moderate" | "complex";
  taskUrgency?: "low" | "medium" | "high";
  /** Turn stamp from backend `pressure_blocks_live_object_mint`. */
  pressureBlocksLiveObjectMint?: boolean;
  /** Turn stamp from backend `streak_blocks_live_object_mint`. */
  streakBlocksLiveObjectMint?: boolean;
  /** Turn stamp from backend `closed_loop_return_blocks_task_mint`. */
  closedLoopReturnBlocksTaskMint?: boolean;
}

export interface MemorySnapshot {
  currentFocus: string;
  weakSpots: string[];
  recentWins: string[];
  reviewSummary: string;
  reviewRhythm: string;
  dueReviews: ReviewQueueItem[];
  teachingObservations: string[];
  coachingAdaptation?: CoachingAdaptationView;
  coachAnchor?: string;
  topWeakness?: string;
  lowestMasteryConcepts?: string[];
  dueReviewCount?: number;
  paceSignal?: string;
  activeThread?: ActiveThreadView;
  memoryEvidence: string[];
  memoryShareGrants?: MemoryShareGrant[];
  evidenceQueue?: EvidenceQueueView;
  flashDeck?: { selectedCardId?: string; selected_card_id?: string };
  planChangeCandidates?: PlanChangeCandidateView[];
  subplans?: SubPlan[];
  providerDiagnostics?: Array<Record<string, unknown>>;
  selectedResourceDetail?: ResourceDetailRecord;
  sandboxPreview?: SandboxPreview;
  sandboxState?: SandboxState;
  workspaceUnderstanding?: WorkspaceUnderstandingSnapshot;
  workspace?: {
    workspaceId?: string;
    responseLanguage?: ComposerLanguage;
    answerMode?: CoachAnswerMode;
    resourceSearchMode?: ResourceSearchMode;
    followCurrentFile?: boolean;
    contextDetail?: "focused" | "balanced" | "full";
    includeCurrentFile?: boolean;
    includeSelection?: boolean;
    includeDiagnostics?: boolean;
    includeRelatedFiles?: boolean;
    learnerName?: string;
    projectContext?: string;
    preferredRhythm?: string;
    preferredLearningMode?: string;
    onboardingRequest?: string;
    latestLearningFocusArea?: string;
    latest_learning_focus_area?: string;
    latestTransferState?: TransferSkillStateView;
    latestPlanRuntime?: {
      revision?: number;
      workspaceId?: string;
      requestId?: string;
      planId?: string;
      currentStageId?: string;
      currentStep?: string;
      frozen?: boolean;
      blockedReason?: string;
      whyNow?: string;
      verifyMethod?: string[];
      nextAfterCurrent?: string;
      evidenceBinding?: string;
      updatedAt?: string;
    };
    latestProviderCapability?: {
      revision?: number;
      workspaceId?: string;
      providerProfileId?: string;
      providerName?: string;
      baseUrl?: string;
      model?: string;
      protocol?: string;
      ok?: boolean;
      checkedAt?: string;
      toolsReady?: boolean;
      toolProbeStatus?: string;
      streamingReady?: boolean;
      streamProbeStatus?: string;
      visionReady?: boolean;
      visionProbeStatus?: string;
      thinkingReady?: boolean;
      thinkingProbeStatus?: string;
      capabilityEvidence?: Array<{
        name: string;
        declared: boolean;
        observed: boolean | null;
        state: string;
      }>;
    };
    latestStreamingCheckpoint?: {
      revision?: number;
      workspaceId?: string;
      providerProfileId?: string;
      requestId?: string;
      checkpointId?: string;
      sessionId?: string;
      streamMessageId?: string;
      phase?: "streaming" | "interrupted" | "completed" | "cancelled";
      stopReason?: string;
      error?: string;
      updatedAt?: string;
    };
    resourceSandbox?: ManagedDataFolder;
    trainerWorkspace?: TrainerWorkspaceAdmission;
    coachDefaults?: Partial<CoachDefaults> & {
      workspaceMemoryToggles?: Partial<WorkspaceMemoryToggles>;
    };
  };
}

export interface EvidenceItemView {
  id: string;
  workspaceId?: string;
  summary: string;
  source: string;
  sourceCardId?: string;
  concepts: string[];
  outcome: string;
  confidence: number;
  verified?: boolean;
  verificationSource?: string;
  timestamp?: string;
  targetPlanStageId?: string;
  adopted?: boolean;
  adoptedAt?: string | null;
  deferredAt?: string | null;
  deferralReason?: string;
  rejectedAt?: string | null;
  rejectionReason?: string;
}

export interface EvidenceQueueView {
  pending: EvidenceItemView[];
  deferred: EvidenceItemView[];
  adopted: EvidenceItemView[];
  rejected: EvidenceItemView[];
  history?: EvidenceItemView[];
  totalCount: number;
}

export interface PlanChangeCandidateView {
  id: string;
  workspaceId?: string;
  planId?: string;
  reason: string;
  diff: Record<string, unknown>;
  impact: Record<string, unknown>;
  status: "pending" | "acknowledged" | "rejected";
  createdAt?: string;
  acknowledgedAt?: string | null;
  acknowledgementNote?: string;
}

export type TrainingConversationCandidateType =
  | "project_context_candidate"
  | "resource_import_candidate"
  | "evidence_candidate"
  | "flash_candidate"
  | "practice_candidate"
  | "coach_visible_status"
  | "micro_drill_prompt"
  | "card_invocation";

export type TrainingCardType = "practice" | "flash";
export type TrainingLearningFamily = "code" | "theory";
export type TrainingLearningSubtype = string;

export type TrainingNextHopCandidateType =
  | "evidence_candidate"
  | "flash_candidate"
  | "practice_candidate";

export type TrainingProjectScope =
  | "global"
  | "current_project"
  | "project_subplan"
  | "sandbox"
  | "unknown";

export interface TrainingBlockedCardCandidate {
  cardId: string;
  type: TrainingCardType;
  title: string;
  reasons: string[];
}

export interface TrainingHandoff {
  handoffId?: string;
  learningPhase?: "learn" | "try" | "verify" | "reflect" | "return";
  candidateId?: string;
  candidateType?: TrainingConversationCandidateType;
  targetKind?: string;
  targetId?: string;
  continueIn?: "chat" | "training" | "plan" | "resources" | "none";
  acceptedInto?: string;
  handoffStatus?: string;
  handoffSummary?: string;
  blockedBy?: string;
  coachOnly?: boolean;
  cardType?: TrainingCardType;
  cardTitle?: string;
  scenarioPack?: string;
  learnerDeliverables?: string[];
  verificationSteps?: string[];
  successSignal?: string;
  returnWith?: string;
  nextAfterCompletion?: string;
  fallbackAction?: string;
  returnMode?: "result" | "blocker" | "verification_required" | "reflection_required" | "return_required";
  returnSummary?: string;
  judgedAt?: string;
  sourceChain?: string[];
}

export interface TrainingNextHop {
  candidateId?: string;
  candidateType?: TrainingNextHopCandidateType;
  title?: string;
  summary?: string;
  whyNow?: string;
  projectScope?: TrainingProjectScope;
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
  cardType?: TrainingCardType;
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
}

export interface TrainingCardCandidate {
  cardId: string;
  type: TrainingCardType;
  title: string;
  whyNow?: string;
  status?: string;
  learningPhase?: "learn" | "try" | "verify" | "reflect" | "return";
  learningFamily?: TrainingLearningFamily;
  learningSubtype?: TrainingLearningSubtype;
  knowledgeType?: string;
  question?: string;
  choices?: string[];
  answerMode?: string;
  expectedAnswer?: string;
  focusArea?: string;
  targetSkill?: string;
  scenarioPack?: string;
  scenario?: string;
  problemStatement?: string;
  suggestedWorkspaceAction?: string;
  apiHints?: string[];
  constraints?: string[];
  deliverable?: string;
  selfCheck?: string[];
  expectedAnswerShape?: string;
  validationMethod?: string;
  verificationMethod?: string;
  filesToTouch?: string[];
  learnerDeliverables?: string[];
  verificationSteps?: string[];
  successSignal?: string;
  expectedSymbols?: string[];
  returnWith?: string;
  nextAfterCompletion?: string;
  trainerReviewInput?: string;
  stuckRecovery?: string;
  reflectionPrompt?: string;
  hintLadder?: string[];
  commonMistakes?: string[];
}

export interface ActiveTrainingCardRouting {
  selectedCardId?: string;
  selectedCard?: {
    cardId?: string;
    title?: string;
    type?: TrainingCardType;
    learningPhase?: "learn" | "try" | "verify" | "reflect" | "return";
    learningFamily?: TrainingLearningFamily;
    learningSubtype?: TrainingLearningSubtype;
    knowledgeType?: string;
    question?: string;
    choices?: string[];
    answerMode?: string;
    expectedAnswer?: string;
    focusArea?: string;
    targetSkill?: string;
    scenarioPack?: string;
    scenario?: string;
    problemStatement?: string;
    suggestedWorkspaceAction?: string;
    apiHints?: string[];
    constraints?: string[];
    deliverable?: string;
    selfCheck?: string[];
    expectedAnswerShape?: string;
    validationMethod?: string;
    verificationMethod?: string;
    filesToTouch?: string[];
    learnerDeliverables?: string[];
    verificationSteps?: string[];
    successSignal?: string;
    expectedSymbols?: string[];
    returnWith?: string;
    nextAfterCompletion?: string;
    trainerReviewInput?: string;
    stuckRecovery?: string;
    reflectionPrompt?: string;
    hintLadder?: string[];
    commonMistakes?: string[];
  };
  whyThisCard?: string;
  blockedCandidates?: TrainingBlockedCardCandidate[];
  fallbackAction?: string;
  nextAfterCompletion?: string;
  candidateCount?: number;
  eligibleCount?: number;
}

export interface TrainingEventLedgerEntry {
  eventId?: string;
  eventType?: string;
  candidateId?: string;
  candidateStatus?: string;
  candidateStatusReason?: string;
  candidateContinueIn?: "chat" | "training" | "plan" | "resources" | "none";
  candidateType?: TrainingConversationCandidateType;
  selectedCardId?: string;
  selectedCardType?: TrainingCardType;
  selectedCardTitle?: string;
  cardCandidateId?: string;
  cardCandidateType?: TrainingCardType;
  cardCandidateTitle?: string;
  whyThisCard?: string;
  learnerDeliverables?: string[];
  verificationSteps?: string[];
  successSignal?: string;
  expectedSymbols?: string[];
  filesToTouch?: string[];
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
  candidateProjectScope?: TrainingProjectScope;
  candidateBlockedBy?: string;
  candidateAcceptedInto?: string;
  candidateWhyNow?: string;
  candidateTitle?: string;
  statusSummary?: string;
  statusDetail?: string;
  statusKind?: string;
  blockedCandidates?: TrainingBlockedCardCandidate[];
  createdAt?: string;
}

export interface ReviewArtifactSummary {
  id?: string;
  title?: string;
  focusArea?: string;
  source?: string;
  status?: string;
  summary?: string;
  rootCause?: string;
  guardrail?: string;
  nextSelfImplementationRule?: string;
  recommendedRecoveryMode?: string;
  recommendedActions?: string[];
  verifiedResult?: string;
  blockedReason?: string;
  partialProgress?: string;
  lastAction?: string;
  updatedAt?: string;
}

export interface ScenarioLabSummary {
  id?: string;
  title?: string;
  focusArea?: string;
  status?: string;
  successSignal?: string;
  reviewOutcome?: string;
  learnerDeliverables?: string[];
  verificationSteps?: string[];
  migrateBackGuidance?: string[];
  dependencyKeys?: string[];
  relatedApis?: string[];
  lastAction?: string;
  updatedAt?: string;
}

export interface TheoryDrillQuestion {
  id?: string;
  prompt: string;
  choices?: string[];
  answer?: string;
  explanation?: string;
}

export interface TheoryDrillSummary {
  id?: string;
  title?: string;
  focusArea?: string;
  status?: string;
  summary?: string;
  successSignal?: string;
  returnWith?: string;
  questions?: TheoryDrillQuestion[];
  lastAction?: string;
  updatedAt?: string;
}

export interface TrainingReliability {
  requestId?: string;
  idempotencyKey?: string;
  commandId?: string;
  cardId?: string;
  handoffId?: string;
  phase?:
    | "intent"
    | "pending"
    | "executing"
    | "succeeded"
    | "failed"
    | "acked"
    | "cancelled";
  revision?: number;
  snapshotRevision?: number;
  createdAt?: string;
  updatedAt?: string;
  ackedAt?: string;
  timeoutAt?: string;
  cancelRequested?: boolean;
  outcome?: "success" | "failure" | "cancelled" | "timeout" | "";
  error?: string;
  recoverable?: boolean;
  recoveryAction?: string;
  learningPhase?: string;
}

export interface WorkspaceTrainingState {
  workspaceId?: string;
  latestConversationHandoff?: TrainingHandoff;
  latestTrainingHandoff?: TrainingHandoff;
  latestTrainingReliability?: TrainingReliability;
  latestTransferState?: TransferSkillStateView;
  latestTrainingNextHop?: TrainingNextHop;
  latestTrainingSubmode?: string;
  latestLearningFocusArea?: string;
  latestLearningFollowup?: string;
  latestLearningVerifiedResult?: string;
  latestLearningBlocker?: string;
  latestLearningAbandonReason?: string;
  latestLearningPartialProgress?: string;
  selectedCardId?: string;
  selectedCardType?: TrainingCardType;
  selectedCardTitle?: string;
  selectedCardStatus?: string;
  trainingCardCandidates?: TrainingCardCandidate[];
  activeTrainingCardRouting?: ActiveTrainingCardRouting;
  trainingEventLedger?: TrainingEventLedgerEntry[];
  reviewArtifact?: ReviewArtifactSummary;
  scenarioLab?: ScenarioLabSummary;
  theoryDrill?: TheoryDrillSummary;
  dueReviews?: ReviewQueueItem[];
}

export interface ConversationMessage {
  id: string;
  role: "system" | "assistant" | "user";
  author: string;
  body: string;
  timestamp: string;
  sourceView?: ActiveWorkbenchView;
  parts?: TrainerMessagePart[];
  attachments?: Array<{
    label: string;
    value: string;
  }>;
  artifacts?: Array<{
    kind:
      | "task"
      | "plan"
      | "evaluation"
      | "note"
      | "idea_implementation"
      | "project_idea"
      | "project_adaptation"
      | "project_source"
      | "principle"
      | "review"
      | "plan_update"
      | "next_step";
    title: string;
    summary?: string;
    content?: string;
    bullets?: string[];
    teaser?: string;
    recommendedAction?: SuggestedAction["action"];
    rationale?: string;
    focusArea?: string;
    verification?: string[];
    metadata?: Record<string, unknown>;
  }>;
  contextNote?: string;
  support?: {
    preview?: string;
    lines?: string[];
  };
}

export type ConversationArtifactKind =
  | "task"
  | "plan"
  | "evaluation"
  | "note"
  | "idea_implementation"
  | "project_idea"
  | "project_adaptation"
  | "project_source"
  | "principle"
  | "review"
  | "plan_update"
  | "next_step";

export interface SuggestedAction {
  id: string;
  label: string;
  action: "plan" | "next_task" | "review" | "hint" | "retry_review" | "task";
  rationale?: string;
  artifactKind?: ConversationArtifactKind;
  prompt?: string;
  focusArea?: string;
}

export interface LiveContext {
  activeFile?: string;
  activeLanguageId?: string;
  selectionRange?: string;
  selectionPreview?: string;
  diagnosticsSummary: string;
  documentVersion?: number;
  recentFiles: string[];
  recentEditedFiles: string[];
  relatedFiles: string[];
  diagnosticErrors?: number;
  diagnosticWarnings?: number;
}

export type ComposerLanguage = SharedComposerLanguage;
export type CoachMemoryScope = "project" | "personal" | "session";
export type WorkingSetMode = "focused" | "balanced" | "broad";
export type ReviewCadence = "light" | "steady" | "active";
export type ReviewReminderMode = "due" | "ahead" | "digest";

export const RESOURCE_COMPOSER_INTENT_MODES = [
  "locate",
  "download",
  "organize",
  "cards",
] as const;
export type ResourceComposerIntentMode = (typeof RESOURCE_COMPOSER_INTENT_MODES)[number];

/**
 * Semantic direction for a Resources composer turn. This deliberately carries
 * only an action and opaque resource identifiers; it cannot authorize a path,
 * network operation, or sandbox write.
 */
export interface ResourceComposerIntent {
  mode: ResourceComposerIntentMode;
  resourceIds?: string[];
}

export interface WorkspaceMemoryToggles {
  decisions: boolean;
  patterns: boolean;
  resources: boolean;
}

export interface CoachDefaults {
  memoryScope: CoachMemoryScope;
  workingSetMode: WorkingSetMode;
  reviewCadence: ReviewCadence;
  reviewReminderMode: ReviewReminderMode;
  workspaceMemoryToggles: WorkspaceMemoryToggles;
}

export const COACH_FIRST_SIDEBAR_VIEWS = [
  "coach",
  "plan",
  "resources",
  "training",
  "settings",
] as const;
export type SidebarView = (typeof COACH_FIRST_SIDEBAR_VIEWS)[number];
export type ActiveWorkbenchView = SidebarView;

export function normalizeSidebarView(
  value: SidebarView | string | null | undefined,
): SidebarView {
  if (value === "practice") {
    return "training";
  }
  if (
    value === "plan" ||
    value === "resources" ||
    value === "training" ||
    value === "settings"
  ) {
    return value;
  }
  return "coach";
}

export interface MessageAttachment {
  id: string;
  kind: "image" | "file";
  mimeType: string;
  dataBase64?: string;
  sourcePath?: string;
  name?: string;
  caption?: string;
  byteSize?: number;
}

export interface SessionMessageRequest {
  text: string;
  intent?: "coach" | "next_task" | "review" | "plan" | "task" | "resources";
  goals?: string[];
  formalPlanMutation?: boolean;
  planComposerMode?: "explain" | "generate" | "evidence" | "blocker";
  activeView?: ActiveWorkbenchView;
  resourceIds?: string[];
  resourceComposerIntent?: ResourceComposerIntent;
  includeCurrentFile?: boolean;
  includeSelection?: boolean;
  includeDiagnostics?: boolean;
  includeRelatedFiles?: boolean;
  contextDetail?: "focused" | "balanced" | "full";
  responseLanguage?: ComposerLanguage;
  answerMode?: CoachAnswerMode;
  teachingStyle?: TeachingStyle;
  coachDefaults?: CoachDefaults;
  attachments?: MessageAttachment[];
  useAgentLoop?: boolean;
  requestId?: string;
  planRuntimeRecovery?: {
    action: "continue_step" | "clear_blocker";
    recovered: true;
    formalPlanMutation: false;
    currentStep?: string;
    currentStepId?: string;
    blockedReason?: string;
    whyNow?: string;
  };
}

export interface CoachSettingsRequest {
  responseLanguage?: ComposerLanguage;
  answerMode?: CoachAnswerMode;
  resourceSearchMode?: ResourceSearchMode;
  teachingStyle?: TeachingStyle;
  coachDefaults?: CoachDefaults;
  followCurrentFile?: boolean;
  contextDetail?: "focused" | "balanced" | "full";
  includeCurrentFile?: boolean;
  includeSelection?: boolean;
  includeDiagnostics?: boolean;
  includeRelatedFiles?: boolean;
}

export interface BrowserUploadResourceInput {
  name: string;
  kind: ResourceRecord["kind"];
  content: string;
  contentEncoding?: "utf-8" | "base64";
  source?: string;
  tags?: string[];
}

// Streaming types
export interface StreamMessageRequest extends SessionMessageRequest {
  stream: true;
  sessionId?: string;
}

export interface TrainingPersistenceAck {
  requestId: string;
  commandId: string;
  ok: boolean;
  data?: unknown;
  message?: string;
}

export interface StreamChunkEvent {
  messageId?: string;
  chunk: string;
}

export interface StreamCompleteEvent {
  messageId?: string;
  tokens: number;
  agentic?: boolean;
  summary?: string;
  nextStep?: string;
  stopReason?: string;
  toolCount?: number;
  reliabilityPhase?: string;
  reliabilityOutcome?: string;
}

export interface StreamErrorEvent {
  messageId?: string;
  error: string;
  category?: string;
  statusCode?: number;
  retryable?: boolean;
  reliabilityPhase?: string;
  reliabilityOutcome?: string;
}

export interface StreamAgentToolCallEvent {
  messageId?: string;
  id: string;
  name: string;
  arguments?: unknown;
  step?: number;
}

export interface StreamAgentToolResultEvent {
  messageId?: string;
  id: string;
  name: string;
  ok: boolean;
  result?: unknown;
  step?: number;
}

export interface StreamAgentStepEvent {
  messageId?: string;
  index: number;
  stop_reason?: string | null;
}

export interface StageMaterialItem {
  id: string;
  planStageId: string;
  kind: 'study_guide' | 'cheat_sheet' | 'exercise_set' | 'code_examples' | string;
  title: string;
  summary: string;
  content: string;
  createdAt?: string;
}

export interface ConnectionStatus {
  state: "starting" | "connected" | "offline";
  provider: ProviderSummary;
}

export interface BootstrapData {
  workspaceName: string;
  sessionLabel: string;
  connection: ConnectionStatus;
  providerConfig: ProviderConfigView;
  liveContext: LiveContext;
  profile: UserProfile;
  plan: LearningPlan;
  globalPlan?: GlobalPlan;
  projectPlanLink?: GlobalPlanProjectLink;
  task: TaskSpec;
  evaluation: EvaluationReport;
  memory: MemorySnapshot;
  workspaceTrainingState?: WorkspaceTrainingState;
  coachingState?: CoachingState;
  learnerState?: LearnerState;
  affectState?: AffectState;
  teachingDecision?: TeachingDecision;
  toneDecision?: ToneDecision;
  implementationGuide?: ImplementationGuide;
  projectIdeas?: ProjectIdea[];
  projectAdaptationGuide?: ProjectAdaptationGuide;
  projectSources?: ProjectSourceSuggestion[];
  principleNotes?: PrincipleNote;
  coachTurn?: CoachTurnSummaryView;
  coachFocus?: CoachFocusView;
  coachOrientation?: CoachOrientationView;
  planRuntimeStatus?: PlanRuntimeStatus;
  nextStepHint?: NextStepHint;
  reviewQueueSummary: string;
  nextReviewDue?: string;
  streamingState: TrainerStreamingState;
  resources: ResourceRecord[];
  deletedResources?: DeletedResource[];
  resourceSearch?: ResourceSearchState;
  conversation: ConversationMessage[];
  suggestedActions: SuggestedAction[];
  commands: TrainerCommandCatalogItem[];
  /** Generated stage learning materials keyed by plan stage id (host state/patch). */
  stageMaterials?: Record<string, StageMaterialItem[]>;
  // Background analysis context for the coach. This is no longer a first-class top-level view.
  research?: ResearchState;
}

// Research types

export type AgentRole = "researcher" | "editor" | "critic" | "synthesizer";
export type ThemeStatus = "planning" | "active" | "paused" | "completed";
export type ScheduleCadence = "daily" | "weekly" | "biweekly" | "monthly";

export interface ResearchCheckpoint {
  id: string;
  label: string;
  due_date: string;
  completed: boolean;
}

export interface ResearchSchedule {
  start_date: string | null;
  end_date: string | null;
  cadence: ScheduleCadence | null;
  checkpoints: ResearchCheckpoint[];
}

export interface ResearchThread {
  id: string;
  angle: string;
  depth: "shallow" | "medium" | "deep";
  status: string;
  findings_count: number;
}

export interface ResearchTheme {
  id: string;
  title: string;
  description: string;
  duration_weeks: number;
  status: ThemeStatus;
  schedule: ResearchSchedule;
  threads: ResearchThread[];
  artifacts_count: number;
  created_at: string;
  updated_at: string;
}

export interface ThinkingEntry {
  id: string;
  role: AgentRole;
  question: string;
  conclusion: string;
  created_at: string;
}

export interface AgentState {
  current_role: AgentRole;
  thinking_log: ThinkingEntry[];
  pending_questions: string[];
  self_review_count: number;
  current_iteration: number;
  max_review_rounds: number;
}

export interface ResearchApproval {
  id: string;
  title: string;
  description: string;
  created_at: string;
}

export interface WorkbenchGate {
  messages: ConversationMessage[];
  pending_approvals: string[];
  notifications: string[];
}

export interface ResearchProject {
  id: string;
  title: string;
  description: string;
  themes: ResearchTheme[];
  agent_state: AgentState;
  gate: WorkbenchGate;
  active_themes_count: number;
  created_at: string;
  updated_at: string;
}

export interface ResearchScheduleThemeStatus {
  theme_id: string;
  theme_title: string;
  status: ThemeStatus;
  duration_weeks: number;
  progress_percentage: number;
  time_elapsed_percentage: number;
  next_checkpoint: ResearchCheckpoint | null;
  overdue_checkpoints: ResearchCheckpoint[];
  threads_count: number;
  artifacts_count: number;
}

export interface ResearchState {
  project: ResearchProject | null;
  scheduleStatus: {
    themes: ResearchScheduleThemeStatus[];
    themes_needing_advance: string[];
    total_checkpoints: number;
    completed_checkpoints: number;
  };
}

// End research types

export interface UiLayoutState {
  themePreference: ThemePreference;
  learningSurfaceAlignment: LearningSurfaceAlignment;
  activeView: ActiveWorkbenchView;
  composerLanguage: ComposerLanguage;
  composerAnswerMode: CoachAnswerMode;
  teachingStyle: TeachingStyle;
  resourceSearchMode: ResourceSearchMode;
  includeCurrentFile: boolean;
  includeSelection: boolean;
  includeDiagnostics: boolean;
  includeRelatedFiles: boolean;
  contextDetail: "focused" | "balanced" | "full";
  followCurrentFile: boolean;
  coachDefaults: CoachDefaults;
}

export interface PersistedWorkbenchState extends UiLayoutState {
  composerDraft: string;
  previewProviderConfig?: Partial<ProviderConfigView>;
}

export interface RestoreViewPayload {
  sessionId?: string;
  activeView?: string;
  focusProviderApiKey?: boolean;
  trainingSubmode?: string;
  trainingRestoreTarget?: "theory_drill" | "scenario_lab" | "review_artifact" | "next_hop";
  theoryDrillId?: string;
  scenarioLabId?: string;
  reviewArtifactId?: string;
  latestTrainingNextHop?: TrainingNextHop;
  resourceSurface?: string;
  resourceId?: string;
  resourceDetailId?: string;
  sandboxPath?: string;
  previewPath?: string;
  workspaceLabel?: string;
  resumeReason?: string;
  focusArea?: string;
  currentStageTitle?: string;
  latestSummary?: string;
}

export interface DebugVisibleTrainingFacts {
  surface: "training";
  activeView: string;
  restoreKind?: string;
  surfaceMode?: string;
  activeSubmode?: string;
  visibleTitle?: string;
  visibleSummary?: string;
  visibleMeta?: string;
  visibleCaption?: string;
  latestReviewQueueActionSummary?: string;
  latestReviewQueueEventType?: string;
  latestReviewQueueAttemptKind?: string;
  latestReviewQueueAuthoritySource?: string;
  latestReviewQueueCurrentSubmode?: string;
  theoryDrillVisible?: boolean;
  theoryDrillId?: string;
  theoryDrillTitle?: string;
  theoryDrillStatus?: string;
  theoryQuestionPrompt?: string;
  scenarioLabVisible?: boolean;
  scenarioLabId?: string;
  scenarioLabTitle?: string;
  scenarioLabStatus?: string;
  scenarioLabScenario?: string;
  reviewArtifactVisible?: boolean;
  reviewArtifactId?: string;
  reviewArtifactStatus?: string;
  nextHopVisible?: boolean;
  nextHopTitle?: string;
  nextHopStatus?: string;
  nextHopContinueIn?: string;
  nextHopCandidateType?: string;
  nextHopTargetKind?: string;
  nextHopTargetId?: string;
  nextHopReviewArtifactId?: string;
  nextHopPlanEvidenceId?: string;
  singleCardImmersive?: boolean;
  routeStripCollapsedByDefault?: boolean;
  cardOnlyMode?: boolean;
  secondaryPanelsCollapsedByDefault?: boolean;
}

export interface DebugVisibleResourcesFacts {
  surface: "resources";
  activeView: string;
  activeSurface?: string;
  visibleTitle?: string;
  visibleSummary?: string;
  visibleMeta?: string;
  resourceDetailVisible?: boolean;
  resourceDetailId?: string;
  resourceDetailTitle?: string;
  selectedResourceId?: string;
  sandboxPreviewEmbedded?: boolean;
  sandboxPreviewVisible?: boolean;
  sandboxPreviewPath?: string;
  selectedSandboxPath?: string;
  previewPath?: string;
  capabilityHeadline?: string;
  capabilityFacts?: string[];
  networkCapabilityFacts?: string[];
  degradationNote?: string;
  skillGateStatusText?: string;
  skillGateOperationText?: string;
  permissionState?: string;
  networkExecutionStatus?: string;
  networkReasonCode?: string;
  diagnosticsDefaultOpen?: boolean;
  singleWorkbenchSurface?: boolean;
  compactMode?: boolean;
  modebarHiddenInCompact?: boolean;
  detailPaneVisible?: boolean;
  sandboxPaneVisible?: boolean;
  previewPaneVisible?: boolean;
}

export interface DebugVisibleWorkbenchFacts {
  activeView: string;
  training?: DebugVisibleTrainingFacts;
  resources?: DebugVisibleResourcesFacts;
}

export type WebviewAction =
  | { type: "request/bootstrap" }
  | { type: "settings/primeProviderModels" }
  | { type: "command/execute"; payload: { commandId: string; payload?: unknown } }
  | { type: "session/sendMessage"; payload: SessionMessageRequest }
  | { type: "session/sendStreamMessage"; payload: StreamMessageRequest }
  | { type: "session/cancelStreamMessage"; payload?: { messageId?: string } }
  | { type: "settings/saveCoach"; payload: CoachSettingsRequest }
  | { type: "ui/liveFollow"; payload: { enabled: boolean } }
  | { type: "plan/generate" }
  | { type: "plan/freeze"; payload: { frozen: boolean } }
  | { type: "task/specify"; payload: { text?: string } }
  | { type: "task/next" }
  | { type: "task/evaluateCurrentFile"; payload: { taskId: string } }
  | {
      type: "resource/upload";
      payload?: {
        mode?: "files" | "folder" | "url";
        __trainerResourceOperationId?: string;
      };
    }
  | { type: "resource/open"; payload: { resourceId: string } }
  | { type: "ui/focus"; payload: { target: "conversation" | "task" | "evaluation" } }
  // Research actions
  | { type: "research/create"; payload: { title: string; description: string } }
  | { type: "research/addTheme"; payload: { projectId: string; title: string; description: string; duration_weeks?: number; cadence?: string } }
  | { type: "research/activateTheme"; payload: { projectId: string; themeId: string } }
  | { type: "research/advance"; payload: { projectId: string; themeId?: string } }
  | { type: "research/message"; payload: { projectId: string; message: string } }
  | { type: "research/streamMessage"; payload: { projectId: string; message: string } }
  | { type: "research/approve"; payload: { projectId: string; approvalId: string; approved: boolean } }
  | { type: "research/getStatus"; payload: { projectId: string } };

export type HostMessage =
  | { type: "bootstrap"; payload: BootstrapData }
  | { type: "state/patch"; payload: Partial<BootstrapData> }
  | {
      type: "operation/status";
      payload: { tone: "info" | "success" | "error"; message: string; phase?: string };
    }
  | { type: "training/resourceHandoff"; payload: ResourceTrainingHandoffResult }
  | { type: "training/persistenceAck"; payload: TrainingPersistenceAck }
  | { type: "ui/restoreView"; payload: RestoreViewPayload }
  | {
      type: "ui/coachPrompt";
      payload: { draft: string; source?: "commandPalette" | "recovery" };
    }
  // Streaming messages
  | { type: "stream/start"; payload: { messageId: string } }
  | { type: "stream/chunk"; payload: StreamChunkEvent }
  | { type: "stream/complete"; payload: StreamCompleteEvent }
  | { type: "stream/error"; payload: StreamErrorEvent }
  | { type: "stream/cancelled"; payload: { messageId?: string } }
  // Agent-loop events
  | { type: "stream/tool_call"; payload: StreamAgentToolCallEvent }
  | { type: "stream/tool_result"; payload: StreamAgentToolResultEvent }
  | { type: "stream/step"; payload: StreamAgentStepEvent }
  | {
      type: "resourceOrganization/pending";
      payload: { pending: boolean; operationCount?: number };
    };
