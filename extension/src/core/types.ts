import type { TrainerCommandCatalogItem } from '../../../shared/src/commands';
import type {
  CoachingAdaptationProfile,
  FirstLookSummary as SharedFirstLookSummary,
  ProviderProtocol,
  ProjectSourceSuggestion,
  WorkspaceUnderstandingSnapshot as SharedWorkspaceUnderstandingSnapshot,
} from '../../../shared/src/models';
import type { TrainerMessagePart, TrainerStreamingState } from '../../../shared/src/protocol';
import type { ResourceSearchMode } from '../../../shared/src/resourceSearch';
import type { ComposerLanguage } from '../../../shared/src/types';
import type { TransferSkillStateRecord } from '../../../shared/src/transferSkillGovernance';
import type {
  PlanRuntimeRecoveryRecord,
  ProviderCapabilityRecoveryRecord,
  StreamingCheckpointRecord,
} from '../../../shared/src/workspaceRecoveryGovernance';
import type {
  ProviderCapabilityEvidence,
  ProviderCapabilityVerificationState,
} from '../../../shared/src/providerTest';
export type { ProviderProtocol, ProjectSourceSuggestion } from '../../../shared/src/models';
export type { ProviderCapabilityVerificationState } from '../../../shared/src/providerTest';
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

export interface ProviderTaskBinding {
  alias: string;
  fallbackAliases: string[];
  requiredCapabilities: string[];
}

export type ProviderRequestDefaults = Record<string, unknown>;

export interface ProviderThinkingConfig {
  mode: 'disabled' | 'enabled' | 'auto';
  budgetTokens?: number | 'auto';
  reasoningEffort?: 'low' | 'medium' | 'high';
}

export type ProviderCredentialMode = 'workspace_secret' | 'ui_proxy';

export interface ProviderModelTokenLimit {
  contextWindowTokens?: number;
  maxOutputTokens?: number;
}

export interface ProviderConfig {
  name: string;
  baseUrl: string;
  apiKeyRef: string;
  model: string;
  protocol?: ProviderProtocol;
  label?: string;
  mode?: 'direct' | 'gateway';
  connectionType?: string;
  capabilities: CapabilityFlags;
  credentialMode?: ProviderCredentialMode;
  availableModels?: string[];
  catalogModels?: string[];
  allowedModels?: string[];
  deniedModels?: string[];
  modelAliases?: Record<string, string>;
  modelCapabilities?: Record<string, CapabilityFlags>;
  modelTokenLimits?: Record<string, ProviderModelTokenLimit>;
  taskBindings?: Record<string, unknown>;
  requestDefaults?: Record<string, unknown>;
  thinkingConfig?: ProviderThinkingConfig;
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

export interface ResolvedProviderConfig extends ProviderConfig {
  apiKey?: string;
}

export interface ProviderModelCache {
  providerFingerprint: string;
  availableModels: string[];
  resolvedModel?: string;
  modelTokenLimits?: Record<string, ProviderModelTokenLimit>;
  fetchedAt: string;
  expiresAt: string;
  source: 'live' | 'cache';
  apiKeyDigest?: string;
  lastError?: string;
  lastErrorCategory?: string;
  lastStatusCode?: number;
  retryable?: boolean;
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
  responseLanguage?: string;
  capabilityEvidence?: ProviderCapabilityEvidence[];
  toolsReady?: boolean;
  toolProbeStatus?: ProviderCapabilityVerificationState;
  streamingReady?: boolean;
  streamProbeStatus?: ProviderCapabilityVerificationState;
  visionReady?: boolean;
  visionProbeStatus?: ProviderCapabilityVerificationState;
  thinkingReady?: boolean;
  thinkingProbeStatus?: ProviderCapabilityVerificationState;
}

export type SidecarLifecycle =
  | 'idle'
  | 'starting'
  | 'ready'
  | 'stopped'
  | 'unavailable'
  | 'error';

export interface SidecarStatus {
  lifecycle: SidecarLifecycle;
  host: string;
  port?: number;
  pid?: number;
  detail?: string;
  commandLine?: string;
  canStart: boolean;
  lastHealthcheckAt?: string;
}

export interface WorkspaceSnapshot {
  trusted: boolean;
  workspaceFolder?: string;
  activeWorkspaceRoot?: string;
  activeFile?: string;
  activeLanguageId?: string;
  remoteName?: string;
  isRemoteWorkspace?: boolean;
  selectionRange?: string;
  selectionText?: string;
  diagnosticErrors?: number;
  diagnosticWarnings?: number;
  documentVersion?: number;
  recentFiles?: string[];
  recentEditedFiles?: string[];
  relatedFiles?: string[];
}

export interface TrainerHostState {
  provider?: ProviderConfig;
  providerApiKeyConfigured: boolean;
  sidecar: SidecarStatus;
  workspace: WorkspaceSnapshot;
  sessionId?: string;
  streamingState: TrainerStreamingState;
  bootstrap: BootstrapData;
}

export interface CommandExecutionResult<T = unknown> {
  ok: boolean;
  cancelled?: boolean;
  message?: string;
  data?: T;
  ui?: {
    focusProviderApiKey?: boolean;
  };
}

export interface ProviderSummary {
  name: string;
  model: string;
  capabilities: CapabilityFlags;
  protocol?: ProviderProtocol;
  protocolFamily?: string;
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
  profileId?: string;
  profileLabel?: string;
  profileMode?: string;
  credentialMode?: ProviderCredentialMode;
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
  modelListStatus: 'idle' | 'loading' | 'ready' | 'error';
  modelListDetail?: string;
  cacheFetchedAt?: string;
  cacheExpiresAt?: string;
  cacheSource?: 'live' | 'cache';
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
  lastTestResult?: ProviderLastTestResult;
}

export interface LiveContextView {
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

export interface ConversationAttachmentView {
  label: string;
  value: string;
}

export type CoachActionView =
  | 'plan'
  | 'next_task'
  | 'review'
  | 'hint'
  | 'retry_review'
  | 'task';

export interface ConversationArtifactView {
  kind:
    | 'task'
    | 'plan'
    | 'evaluation'
    | 'note'
    | 'idea_implementation'
    | 'project_idea'
    | 'project_adaptation'
    | 'project_source'
    | 'principle'
    | 'review'
    | 'plan_update'
    | 'next_step';
  title: string;
  summary?: string;
  content?: string;
  bullets?: string[];
  teaser?: string;
  recommendedAction?: CoachActionView;
  rationale?: string;
  focusArea?: string;
  verification?: string[];
  metadata?: Record<string, unknown>;
}

export interface NextStepHintView {
  title: string;
  summary?: string;
  recommendedAction?: CoachActionView;
  focusArea?: string;
  prompt?: string;
  resumeThread?: string;
  source?:
    | 'agent_loop'
    | 'coach_turn'
    | 'active_thread'
    | 'coaching_state'
    | 'plan'
    | 'implementation_guide'
    | 'evaluation'
    | 'task'
    | 'review';
  continueIn?: 'coach' | 'plan' | 'training';
  verification?: string[];
}

export interface LearnerStateView {
  currentConfidence: number;
  frustrationLevel: number;
  attemptCountRecent: number;
  needsRescue: boolean;
  needsReview: boolean;
  preferredHintDepth: string;
  learnerSignal: 'steady' | 'blocked' | 'uncertain' | 'curious';
  activeFocus: string;
  evidence: string[];
}

export interface AffectStateView {
  frustrationLevel: number;
  confidenceLevel: number;
  momentumLevel: number;
  needsReassurance: boolean;
  urgencyLevel: 'low' | 'medium' | 'high';
}

export interface ToneDecisionView {
  tone: 'steady' | 'encouraging' | 'concise_rescue' | 'reflective';
  verbosityBias: 'short' | 'medium' | 'expanded';
  acknowledgeProgress: boolean;
  avoidOverwhelm: boolean;
}

export interface TeachingDecisionView {
  mode:
    | 'onboarding'
    | 'idea_implementation'
    | 'project_idea_mining'
    | 'project_adaptation'
    | 'planning'
    | 'concept_teaching'
    | 'engineering_challenge'
    | 'review_reflection'
    | 'project_sourcing'
    | 'principle_explanation'
    | 'guided'
    | 'scaffold'
    | 'balanced'
    | 'direct_rescue'
    | 'challenge'
    | 'reflection';
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
    | 'steady'
    | 'guided_build'
    | 'proactive_coach'
    | 'steady_migration'
    | 'teaching_clarity'
    | 'review_loop'
    | 'concise_rescue';
  focusArea?: string;
}

export interface ImplementationGuideView {
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

export interface ProjectIdeaView {
  id: string;
  title: string;
  summary: string;
  sourceArea: string;
  ideaKind: 'feature' | 'refactor' | 'test' | 'architecture' | 'developer_experience';
  learningValue: string;
  engineeringValue: string;
  difficulty: string;
  suggestedScope: string;
  firstStep: string;
  acceptanceSignals: string[];
  whyNow: string;
}

export interface ProjectAdaptationGuideView {
  targetOutcome: string;
  currentConstraints: string[];
  affectedAreas: string[];
  preserveAreas: string[];
  firstMigrationStep: string;
  migrationSequence: string[];
  validationCheckpoints: string[];
  rollbackNotes: string[];
}

export interface PrincipleNoteView {
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

export interface SuggestedActionView {
  id: string;
  label: string;
  action: CoachActionView;
  rationale?: string;
  artifactKind?: ConversationArtifactView['kind'];
  prompt?: string;
  focusArea?: string;
}

export interface UserProfileView {
  learnerName: string;
  goals: string[];
  weeklyHours: number;
  preferredStyle: string;
  answerPolicy: 'auto' | 'coach-first' | 'balanced' | 'direct';
  focusAreas: string[];
  targetProject?: string;
  preferredRhythm?: string;
  preferredLearningMode?: string;
  onboardingRequest?: string;
  projectContext?: string;
}

export interface PlanStageView {
  id: string;
  title: string;
  objective: string;
  status: 'done' | 'active' | 'queued';
}

export interface SubPlanView {
  id: string;
  parentPlanId: string;
  title: string;
  description: string;
  stages: PlanStageView[];
  status: 'draft' | 'active' | 'completed' | 'archived';
  progressPercent: number;
  createdAt: string;
  updatedAt: string;
}

export interface LearningPlanView {
  id: string;
  title: string;
  frozen: boolean;
  cadence: string;
  summary: string;
  stages: PlanStageView[];
  currentStageId?: string;
  currentStep?: string;
  whyNow?: string;
  verifyMethod?: string[];
  blockedReason?: string;
  nextAfterCurrent?: string;
}

export interface GlobalPlanView {
  id: string;
  title: string;
  summary: string;
  goals: string[];
  stages: PlanStageView[];
  frozen: boolean;
  currentProjectPlanId?: string;
  currentStageId?: string;
  currentStep?: string;
  whyNow?: string;
  verifyMethod?: string[];
}

export interface GlobalPlanProjectLinkView {
  globalPlanId: string;
  workspaceId: string;
  projectPlanId: string;
  linkedAt: string;
  updatedAt: string;
}

export interface PlanRuntimeReviewPointView {
  concept: string;
  reason: string;
  severity?: 'low' | 'medium' | 'high';
  dueAt?: string;
  source?: string;
  surfaceMode?: 'due' | 'ahead' | 'digest';
  taskHint?: string;
  focusArea?: string;
  linkedContext?: string[];
  intervalDays?: number;
  masteryScore?: number;
}

export interface PlanRuntimeStatusView {
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
  reviewPoints: PlanRuntimeReviewPointView[];
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
  nextStepHint?: NextStepHintView;
  recovered?: boolean;
  resumeState?: 'interrupted' | 'in_progress' | 'waiting';
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

export interface TaskSpecView {
  id: string;
  title: string;
  description: string;
  constraints: string[];
  acceptanceCriteria: string[];
  nextActionLabel: string;
}

export interface EvaluationCheckView {
  id: string;
  label: string;
  status: 'pass' | 'fail' | 'warn' | 'pending';
  detail: string;
}

export interface EvaluationReportView {
  headline: string;
  summary: string;
  passRate: number;
  updatedAt: string;
  checks: EvaluationCheckView[];
  nextStep: string;
}

export interface ReviewQueueItemView {
  concept: string;
  reason: string;
  dueAt?: string;
  source: 'weakness' | 'mastery' | 'reflection' | 'plan';
  severity: 'low' | 'medium' | 'high';
  surfaceMode?: 'due' | 'ahead' | 'digest';
  taskHint?: string;
  focusArea?: string;
  linkedContext?: string[];
  intervalDays?: number;
  masteryScore?: number;
}

export interface CoachingStateView {
  scenario:
    | 'general'
    | 'onboarding'
    | 'idea_implementation'
    | 'project_idea'
    | 'project_adaptation'
    | 'project_sourcing'
    | 'principle'
    | 'review'
    | 'plan'
    | 'task'
    | 'next_task';
  answerMode: 'guided' | 'balanced' | 'direct';
  learnerSignal: 'steady' | 'blocked' | 'uncertain' | 'curious';
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

export interface CoachTurnSummaryView {
  scenario:
    | 'general'
    | 'onboarding'
    | 'idea_implementation'
    | 'project_idea'
    | 'project_adaptation'
    | 'project_sourcing'
    | 'principle'
    | 'review'
    | 'plan'
    | 'task'
    | 'next_task';
  learnerSignal: 'steady' | 'blocked' | 'uncertain' | 'curious';
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
  tone?: ToneDecisionView['tone'];
  verbosityBias?: ToneDecisionView['verbosityBias'];
  activeStage?: string;
  activeTask?: string;
  dueReviewCount?: number;
  reviewQueueSummary?: string;
  failingChecks?: string[];
  artifactKinds?: ConversationArtifactView['kind'][];
  suggestedActionTypes?: CoachActionView[];
  backgroundMode?: 'embedded';
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
  scenario?: CoachTurnSummaryView['scenario'];
  relationshipStage?: 'intake' | 'active';
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

export interface ResourceRecordView {
  id: string;
  title: string;
  kind: 'pdf' | 'image' | 'markdown' | 'text' | 'code' | 'url';
  status: 'ready' | 'indexing' | 'attention';
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
  freshness?: 'fresh' | 'stale' | 'unknown';
  indexState?: string;
  citationId?: string;
  previewTier?: 'rich' | 'converted' | 'metadata';
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

export interface ResourceDetailRecordView extends ResourceRecordView {}

export type ResourceTrainingHandoffOutcome = 'ready' | 'blocked' | 'not-current' | 'failed';
export type ResourceTrainingHandoffReason =
  | 'resource_missing'
  | 'resource_needs_refresh'
  | 'connection'
  | 'unavailable';

export interface ResourceTrainingHandoffResult {
  requestId: string;
  resourceId: string;
  outcome: ResourceTrainingHandoffOutcome;
  reason?: ResourceTrainingHandoffReason;
  generatedCardId?: string;
  selectedCardId?: string;
}

export interface DeletedResourceView {
  resourceId: string;
  title: string;
  deletedAt?: string;
  collectionPath?: string;
  recoverable: boolean;
}

export interface ResourceSearchStateView {
  requestId?: string;
  workspaceId?: string;
  query: string;
  total: number;
  rankingStrategy?: string;
  filters: Record<string, string>;
  hits: ResourceDetailRecordView[];
}

export interface WorkspaceAuthorityView {
  activeWorkspaceRoot?: string;
  rootUri?: string;
  authoritySource?: string;
  remoteName?: string;
  authorityMode?: string;
  permissionLevel?: string;
  permissionLabel?: string;
  allowedOperations?: string[];
  mountedSources?: string[];
  ledgerEntryCount?: number;
  checkpointCount?: number;
  trashRoot?: string;
  nextSafeAction?: string;
}

export interface ManagedDataFolderView {
  configuredPath?: string;
  effectivePath: string;
  defaultPath: string;
  source: 'recommended' | 'custom';
  status: 'ready';
}

export type TrainerProjectAdmissionStatus =
  | 'root-missing'
  | 'project-found'
  | 'managed'
  | 'browse'
  | 'ignored';

export type TrainerWorkspaceReconciliationState = 'waiting' | 'retry-required';

export type TrainerWorkspaceReconciliationAction = 'continue-waiting' | 'retry' | 'abandon';

export interface TrainerWorkspaceReconciliationView {
  reason: string;
  jobId?: string;
  updatedAt: string;
  state: TrainerWorkspaceReconciliationState;
  availableActions: readonly TrainerWorkspaceReconciliationAction[];
}

export interface TrainerWorkspaceAdmissionView {
  status: TrainerProjectAdmissionStatus;
  rootPath?: string;
  rootId?: string;
  projectId?: string;
  contextId?: string;
  projectName?: string;
  projectPath?: string;
  canonicalProjectPath?: string;
  identityStatus?: 'pending' | 'verified' | 'reconcile-required';
  manifestRevision?: number;
  pathRevision?: number;
  updatedAt?: string;
  reconciliation?: TrainerWorkspaceReconciliationView;
}

export type MemoryShareCategoryView = 'preferences' | 'mastery';

export interface MemoryShareGrantView {
  sourceWorkspaceId: string;
  targetWorkspaceId: string;
  categories: MemoryShareCategoryView[];
  createdAt?: string;
  updatedAt?: string;
}

export interface SandboxPreviewView {
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

export interface SandboxStateView {
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
  preview?: SandboxPreviewView;
  recentCommands?: Array<Record<string, unknown>>;
  latestCommand?: Record<string, unknown> | null;
  authority?: WorkspaceAuthorityView;
  capabilitySummary?: Record<string, unknown>;
  threatSummary?: Record<string, unknown>;
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

export interface MemorySnapshotView {
  currentFocus: string;
  weakSpots: string[];
  recentWins: string[];
  reviewSummary: string;
  reviewRhythm: string;
  dueReviews: ReviewQueueItemView[];
  teachingObservations: string[];
  coachingAdaptation?: CoachingAdaptationProfile;
  coachAnchor?: string;
  topWeakness?: string;
  lowestMasteryConcepts?: string[];
  dueReviewCount?: number;
  paceSignal?: string;
  activeThread?: ActiveThreadView;
  memoryEvidence: string[];
  memoryShareGrants?: MemoryShareGrantView[];
  evidenceQueue?: EvidenceQueueView;
  subplans?: SubPlanView[];
  providerDiagnostics?: Array<Record<string, unknown>>;
  selectedResourceDetail?: ResourceDetailRecordView;
  sandboxPreview?: SandboxPreviewView;
  sandboxState?: SandboxStateView;
  workspaceUnderstanding?: WorkspaceUnderstandingSnapshot;
  workspace?: {
    workspaceId?: string;
    responseLanguage?: ComposerLanguage;
    answerMode?: 'auto' | 'coach-first' | 'balanced' | 'direct';
    resourceSearchMode?: ResourceSearchMode;
    followCurrentFile?: boolean;
    contextDetail?: 'focused' | 'balanced' | 'full';
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
    latestTransferState?: TransferSkillStateRecord;
    latestPlanRuntime?: PlanRuntimeRecoveryRecord;
    latestProviderCapability?: ProviderCapabilityRecoveryRecord;
    latestStreamingCheckpoint?: StreamingCheckpointRecord;
    resourceSandbox?: ManagedDataFolderView;
    trainerWorkspace?: TrainerWorkspaceAdmissionView;
    coachDefaults?: {
      memoryScope?: 'project' | 'personal' | 'session';
      workingSetMode?: 'focused' | 'balanced' | 'broad';
      reviewCadence?: 'light' | 'steady' | 'active';
      reviewReminderMode?: 'due' | 'ahead' | 'digest';
      workspaceMemoryToggles?: {
        decisions?: boolean;
        patterns?: boolean;
        resources?: boolean;
      };
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

export type TrainingConversationCandidateTypeView =
  | 'project_context_candidate'
  | 'resource_import_candidate'
  | 'evidence_candidate'
  | 'flash_candidate'
  | 'practice_candidate'
  | 'coach_visible_status'
  | 'micro_drill_prompt'
  | 'card_invocation';

export type TrainingCardTypeView = 'practice' | 'flash';

export type TrainingNextHopCandidateTypeView =
  | 'evidence_candidate'
  | 'flash_candidate'
  | 'practice_candidate';

export type TrainingProjectScopeView =
  | 'global'
  | 'current_project'
  | 'project_subplan'
  | 'sandbox'
  | 'unknown';

export interface TrainingBlockedCardCandidateView {
  cardId: string;
  type: TrainingCardTypeView;
  title: string;
  reasons: string[];
}

export interface TrainingHandoffView {
  handoffId?: string;
  learningPhase?: 'learn' | 'try' | 'verify' | 'reflect' | 'return';
  candidateId?: string;
  candidateType?: TrainingConversationCandidateTypeView;
  targetKind?: string;
  targetId?: string;
  continueIn?: 'chat' | 'training' | 'plan' | 'resources' | 'none';
  acceptedInto?: string;
  handoffStatus?: string;
  handoffSummary?: string;
  blockedBy?: string;
  coachOnly?: boolean;
  cardType?: TrainingCardTypeView;
  cardTitle?: string;
  scenarioPack?: string;
  learnerDeliverables?: string[];
  verificationSteps?: string[];
  successSignal?: string;
  returnWith?: string;
  nextAfterCompletion?: string;
  fallbackAction?: string;
  returnMode?: 'result' | 'blocker' | 'verification_required' | 'reflection_required' | 'return_required';
  returnSummary?: string;
  judgedAt?: string;
  sourceChain?: string[];
}

export interface TrainingNextHopView {
  candidateId?: string;
  candidateType?: TrainingNextHopCandidateTypeView;
  title?: string;
  summary?: string;
  whyNow?: string;
  projectScope?: TrainingProjectScopeView;
  continueIn?: 'chat' | 'training' | 'plan';
  targetKind?: string;
  targetId?: string;
  acceptedInto?: string;
  status?:
    | 'created'
    | 'surfaced'
    | 'accepted'
    | 'continued_in_chat'
    | 'verification_required'
    | 'reflection_required'
    | 'return_required'
    | 'dismissed'
    | 'deferred'
    | 'blocked'
    | 'expired'
    | 'archived';
  statusReason?: string;
  blockedBy?: string;
  handoffStatus?: string;
  handoffSummary?: string;
  coachOnly?: boolean;
  cardType?: TrainingCardTypeView;
  cardTitle?: string;
  scenarioPack?: string;
  returnMode?: 'result' | 'blocker' | 'verification_required' | 'reflection_required' | 'return_required';
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

export interface TrainingCardCandidateView {
  cardId: string;
  type: TrainingCardTypeView;
  title: string;
  whyNow?: string;
  status?: string;
  learningPhase?: 'learn' | 'try' | 'verify' | 'reflect' | 'return';
  question?: string;
  choices?: string[];
  answerMode?: string;
  expectedAnswer?: string;
  learningFamily?: 'code' | 'theory';
  learningSubtype?: string;
  knowledgeType?: string;
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

export interface ActiveTrainingCardRoutingView {
  selectedCardId?: string;
  selectedCard?: {
    cardId?: string;
    title?: string;
    type?: TrainingCardTypeView;
    learningPhase?: 'learn' | 'try' | 'verify' | 'reflect' | 'return';
    question?: string;
    choices?: string[];
    answerMode?: string;
    expectedAnswer?: string;
    learningFamily?: 'code' | 'theory';
    learningSubtype?: string;
    knowledgeType?: string;
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
  blockedCandidates?: TrainingBlockedCardCandidateView[];
  fallbackAction?: string;
  nextAfterCompletion?: string;
  candidateCount?: number;
  eligibleCount?: number;
}

export interface TrainingEventLedgerEntryView {
  eventId?: string;
  eventType?: string;
  candidateId?: string;
  candidateStatus?: string;
  candidateStatusReason?: string;
  candidateContinueIn?: 'chat' | 'training' | 'plan' | 'resources' | 'none';
  candidateType?: TrainingConversationCandidateTypeView;
  selectedCardId?: string;
  selectedCardType?: TrainingCardTypeView;
  selectedCardTitle?: string;
  cardCandidateId?: string;
  cardCandidateType?: TrainingCardTypeView;
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
  returnMode?: 'result' | 'blocker' | 'verification_required' | 'reflection_required' | 'return_required';
  returnSummary?: string;
  candidateTargetKind?: string;
  candidateTargetId?: string;
  candidateProjectScope?: TrainingProjectScopeView;
  candidateBlockedBy?: string;
  candidateAcceptedInto?: string;
  candidateWhyNow?: string;
  candidateTitle?: string;
  statusSummary?: string;
  statusDetail?: string;
  statusKind?: string;
  blockedCandidates?: TrainingBlockedCardCandidateView[];
  createdAt?: string;
}

export interface ReviewArtifactSummaryView {
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

export interface ScenarioLabSummaryView {
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

export interface TheoryDrillQuestionView {
  id?: string;
  prompt: string;
  choices?: string[];
  answer?: string;
  explanation?: string;
}

export interface TheoryDrillSummaryView {
  id?: string;
  title?: string;
  focusArea?: string;
  status?: string;
  summary?: string;
  successSignal?: string;
  returnWith?: string;
  questions?: TheoryDrillQuestionView[];
  lastAction?: string;
  updatedAt?: string;
}

export interface TrainingReliabilityView {
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

export interface WorkspaceTrainingStateView {
  workspaceId?: string;
  latestConversationHandoff?: TrainingHandoffView;
  latestTrainingHandoff?: TrainingHandoffView;
  latestTrainingReliability?: TrainingReliabilityView;
  latestTransferState?: TransferSkillStateRecord;
  latestTrainingNextHop?: TrainingNextHopView;
  latestTrainingSubmode?: string;
  latestLearningFocusArea?: string;
  latestLearningFollowup?: string;
  latestLearningVerifiedResult?: string;
  latestLearningBlocker?: string;
  latestLearningAbandonReason?: string;
  latestLearningPartialProgress?: string;
  selectedCardId?: string;
  selectedCardType?: TrainingCardTypeView;
  selectedCardTitle?: string;
  selectedCardStatus?: string;
  trainingCardCandidates?: TrainingCardCandidateView[];
  activeTrainingCardRouting?: ActiveTrainingCardRoutingView;
  trainingEventLedger?: TrainingEventLedgerEntryView[];
  reviewArtifact?: ReviewArtifactSummaryView;
  scenarioLab?: ScenarioLabSummaryView;
  theoryDrill?: TheoryDrillSummaryView;
  dueReviews?: ReviewQueueItemView[];
}

export interface ConversationMessageView {
  id: string;
  role: 'system' | 'assistant' | 'user';
  author: string;
  body: string;
  timestamp: string;
  sourceView?: 'coach' | 'plan' | 'resources' | 'training' | 'settings';
  parts?: TrainerMessagePart[];
  attachments?: ConversationAttachmentView[];
  artifacts?: ConversationArtifactView[];
  contextNote?: string;
  support?: {
    preview?: string;
    lines?: string[];
  };
}

export interface StageMaterialItem {
  id: string;
  planStageId: string;
  kind: string;
  title: string;
  summary: string;
  content: string;
  focusArea?: string;
  createdAt?: string;
}

export interface BootstrapData {
  workspaceName: string;
  sessionLabel: string;
  connection: {
    state: 'starting' | 'connected' | 'offline';
    provider: ProviderSummary;
  };
  providerConfig: ProviderConfigView;
  liveContext: LiveContextView;
  profile: UserProfileView;
  plan: LearningPlanView;
  globalPlan?: GlobalPlanView;
  projectPlanLink?: GlobalPlanProjectLinkView;
  task: TaskSpecView;
  evaluation: EvaluationReportView;
  memory: MemorySnapshotView;
  workspaceTrainingState?: WorkspaceTrainingStateView;
  stageMaterials?: Record<string, StageMaterialItem[]>;
  coachingState?: CoachingStateView;
  learnerState?: LearnerStateView;
  affectState?: AffectStateView;
  teachingDecision?: TeachingDecisionView;
  toneDecision?: ToneDecisionView;
  implementationGuide?: ImplementationGuideView;
  projectIdeas?: ProjectIdeaView[];
  projectAdaptationGuide?: ProjectAdaptationGuideView;
  projectSources?: ProjectSourceSuggestion[];
  principleNotes?: PrincipleNoteView;
  coachTurn?: CoachTurnSummaryView;
  coachFocus?: CoachFocusView;
  coachOrientation?: CoachOrientationView;
  planRuntimeStatus?: PlanRuntimeStatusView;
  nextStepHint?: NextStepHintView;
  reviewQueueSummary: string;
  nextReviewDue?: string;
  streamingState: TrainerStreamingState;
  resources: ResourceRecordView[];
  deletedResources?: DeletedResourceView[];
  resourceSearch?: ResourceSearchStateView;
  conversation: ConversationMessageView[];
  suggestedActions: SuggestedActionView[];
  commands: TrainerCommandCatalogItem[];
  /**
   * Compatibility-only research state.
   * Keep optional and visually separated from the main coach-first bootstrap shape.
   */
  research?: ResearchStateView;
}

/**
 * Research compatibility surface
 *
 * These view/message types are retained so older/internal research flows can
 * continue compiling, but they are not part of the primary coach / plan /
 * settings reading path.
 */

export type AgentRole = 'researcher' | 'editor' | 'critic' | 'synthesizer';
export type ThemeStatus = 'planning' | 'active' | 'paused' | 'completed';

export interface ResearchCheckpointView {
  id: string;
  label: string;
  due_date: string;
  completed: boolean;
}

export interface ResearchScheduleView {
  start_date: string | null;
  end_date: string | null;
  cadence: string | null;
  checkpoints: ResearchCheckpointView[];
}

export interface ResearchThreadView {
  id: string;
  angle: string;
  depth: string;
  status: string;
  findings_count: number;
}

export interface ResearchThemeView {
  id: string;
  title: string;
  description: string;
  duration_weeks: number;
  status: ThemeStatus;
  schedule: ResearchScheduleView;
  threads: ResearchThreadView[];
  artifacts_count: number;
  created_at: string;
  updated_at: string;
}

export interface ThinkingEntryView {
  id: string;
  role: AgentRole;
  question: string;
  conclusion: string;
  created_at: string;
}

export interface AgentStateView {
  current_role: AgentRole;
  thinking_log: ThinkingEntryView[];
  pending_questions: string[];
  self_review_count: number;
  current_iteration: number;
  max_review_rounds: number;
}

export interface WorkbenchGateView {
  messages: ConversationMessageView[];
  pending_approvals: string[];
  notifications: string[];
}

export interface ResearchProjectView {
  id: string;
  title: string;
  description: string;
  themes: ResearchThemeView[];
  agent_state: AgentStateView;
  gate: WorkbenchGateView;
  active_themes_count: number;
  created_at: string;
  updated_at: string;
}

export interface ResearchScheduleStatusThemeView {
  theme_id: string;
  theme_title: string;
  status: ThemeStatus;
  progress_percentage: number;
  time_elapsed_percentage: number;
}

export interface ResearchScheduleStatusView {
  themes: ResearchScheduleStatusThemeView[];
  themes_needing_advance: string[];
}

export interface ResearchStateView {
  project: ResearchProjectView | null;
  schedule_status: ResearchScheduleStatusView;
}

// End research compatibility surface

export type ResearchWebviewMessage =
  | { type: 'research/create'; payload: { title: string; description: string } }
  | {
      type: 'research/addTheme';
      payload: { projectId: string; title: string; description: string; duration_weeks?: number; cadence?: string };
    }
  | { type: 'research/activateTheme'; payload: { projectId: string; themeId: string } }
  | { type: 'research/advance'; payload: { projectId: string; themeId?: string } }
  | { type: 'research/message'; payload: { projectId: string; message: string } }
  | { type: 'research/streamMessage'; payload: { projectId: string; message: string } }
  | { type: 'research/approve'; payload: { projectId: string; approvalId: string; approved: boolean } }
  | { type: 'research/getStatus'; payload: { projectId: string } };

export interface MessageAttachmentPayload {
  id: string;
  kind: 'image' | 'file';
  mimeType: string;
  dataBase64?: string;
  sourcePath?: string;
  name?: string;
  caption?: string;
  byteSize?: number;
}

export interface SessionMessagePayload {
  text: string;
  intent?: 'coach' | 'next_task' | 'review' | 'plan' | 'task';
  goals?: string[];
  formalPlanMutation?: boolean;
  activeView?: 'coach' | 'plan' | 'resources' | 'training' | 'settings';
  resourceIds?: string[];
  includeCurrentFile?: boolean;
  includeSelection?: boolean;
  includeDiagnostics?: boolean;
  includeRelatedFiles?: boolean;
  contextDetail?: 'focused' | 'balanced' | 'full';
  responseLanguage?: ComposerLanguage;
  answerMode?: 'auto' | 'coach-first' | 'balanced' | 'direct';
  teachingStyle?: 'auto' | 'guided' | 'concept-first' | 'hands-on' | 'challenging';
  coachDefaults?: {
    memoryScope?: 'project' | 'personal' | 'session';
    workingSetMode?: 'focused' | 'balanced' | 'broad';
    reviewCadence?: 'light' | 'steady' | 'active';
    reviewReminderMode?: 'due' | 'ahead' | 'digest';
    workspaceMemoryToggles?: {
      decisions?: boolean;
      patterns?: boolean;
      resources?: boolean;
    };
  };
  attachments?: MessageAttachmentPayload[];
  useAgentLoop?: boolean;
  requestId?: string;
  planRuntimeRecovery?: {
    action: 'continue_step' | 'clear_blocker';
    recovered: true;
    formalPlanMutation: false;
    currentStep?: string;
    currentStepId?: string;
    blockedReason?: string;
    whyNow?: string;
  };
}

export interface CoachSettingsPayload {
  responseLanguage?: ComposerLanguage;
  answerMode?: 'auto' | 'coach-first' | 'balanced' | 'direct';
  resourceSearchMode?: ResourceSearchMode;
  teachingStyle?: 'auto' | 'guided' | 'concept-first' | 'hands-on' | 'challenging';
  coachDefaults?: {
    memoryScope?: 'project' | 'personal' | 'session';
    workingSetMode?: 'focused' | 'balanced' | 'broad';
    reviewCadence?: 'light' | 'steady' | 'active';
    reviewReminderMode?: 'due' | 'ahead' | 'digest';
    workspaceMemoryToggles?: {
      decisions?: boolean;
      patterns?: boolean;
      resources?: boolean;
    };
  };
  followCurrentFile?: boolean;
  contextDetail?: 'focused' | 'balanced' | 'full';
  includeCurrentFile?: boolean;
  includeSelection?: boolean;
  includeDiagnostics?: boolean;
  includeRelatedFiles?: boolean;
}

export interface StreamMessagePayload extends SessionMessagePayload {
  text: string;
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

export type TrainerWebviewMessage =
  | { type: 'webview/ready' }
  | { type: 'debug/error'; payload: { source: string; message: string; stack?: string } }
  | { type: 'debug/visibleFacts'; payload: DebugVisibleWorkbenchFacts }
  | { type: 'request/bootstrap' }
  | { type: 'settings/primeProviderModels' }
  | { type: 'command/execute'; payload: { commandId: string; payload?: unknown } }
  | { type: 'session/sendMessage'; payload: SessionMessagePayload }
  | { type: 'session/sendStreamMessage'; payload: StreamMessagePayload }
  | { type: 'session/cancelStreamMessage'; payload?: { messageId?: string } }
  | { type: 'settings/saveCoach'; payload: CoachSettingsPayload }
  | { type: 'ui/liveFollow'; payload: { enabled: boolean } }
  | { type: 'plan/generate' }
  | { type: 'plan/freeze'; payload: { frozen: boolean } }
  | { type: 'task/specify'; payload: { text?: string } }
  | { type: 'task/next' }
  | { type: 'task/evaluateCurrentFile'; payload: { taskId?: string } }
  | {
      type: 'resource/upload';
      payload?: {
        mode?: 'files' | 'folder' | 'url';
        __trainerResourceOperationId?: string;
      };
    }
  | { type: 'resource/open'; payload: { resourceId: string } }
  | { type: 'ui/focus'; payload: { target: 'conversation' | 'task' | 'evaluation' } }
  /**
   * Compatibility-only research traffic.
   * Grouped under a named alias so the primary union reads as coach-first.
   */
  | ResearchWebviewMessage;

export interface StreamChunkPayload {
  messageId?: string;
  chunk: string;
}

export interface StreamCompletePayload {
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

export interface StreamErrorPayload {
  messageId?: string;
  error: string;
  category?: string;
  statusCode?: number;
  retryable?: boolean;
  reliabilityPhase?: string;
  reliabilityOutcome?: string;
}

/** Agent-loop SSE events surfaced to the webview. */
export interface StreamAgentToolCallPayload {
  messageId?: string;
  id: string;
  name: string;
  arguments?: unknown;
  step?: number;
}

export interface StreamAgentToolResultPayload {
  messageId?: string;
  id: string;
  name: string;
  ok: boolean;
  result?: unknown;
  step?: number;
}

export interface StreamAgentStepPayload {
  messageId?: string;
  index: number;
  stop_reason?: string | null;
}

export interface RestoreViewPayload {
  sessionId?: string;
  activeView?: string;
  focusProviderApiKey?: boolean;
  trainingSubmode?: string;
  trainingRestoreTarget?: 'theory_drill' | 'scenario_lab' | 'review_artifact' | 'next_hop';
  theoryDrillId?: string;
  scenarioLabId?: string;
  reviewArtifactId?: string;
  latestTrainingNextHop?: Record<string, unknown>;
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
  surface: 'training';
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
  surface: 'resources';
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

export type HostMessage =
  | { type: 'bootstrap'; payload: BootstrapData }
  | { type: 'state/patch'; payload: Partial<BootstrapData> }
  | {
      type: 'operation/status';
      payload: { tone: 'info' | 'success' | 'error'; message: string; phase?: string };
    }
  | { type: 'training/resourceHandoff'; payload: ResourceTrainingHandoffResult }
  | { type: 'training/persistenceAck'; payload: TrainingPersistenceAck }
  | { type: 'ui/restoreView'; payload: RestoreViewPayload }
  | {
      type: 'ui/coachPrompt';
      payload: { draft: string; source?: 'commandPalette' | 'recovery' };
    }
  // Streaming messages
  | { type: 'stream/start'; payload: { messageId: string } }
  | { type: 'stream/chunk'; payload: StreamChunkPayload }
  | { type: 'stream/complete'; payload: StreamCompletePayload }
  | { type: 'stream/error'; payload: StreamErrorPayload }
  | { type: 'stream/cancelled'; payload: { messageId?: string } }
  // Agent-loop events
  | { type: 'stream/tool_call'; payload: StreamAgentToolCallPayload }
  | { type: 'stream/tool_result'; payload: StreamAgentToolResultPayload }
  | { type: 'stream/step'; payload: StreamAgentStepPayload }
  | {
      type: 'resourceOrganization/pending';
      payload: { pending: boolean; operationCount?: number };
    };
