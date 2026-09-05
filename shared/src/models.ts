export type ProviderProtocol =
  | "openai_responses"
  | "openai_chat_completions"
  | "anthropic_messages"
  | "openai_chat_completions_compatible"
  | "gemini_generate_content";

export type ProviderCredentialMode = "workspace_secret" | "ui_proxy";

export interface ProviderTaskBinding {
  alias: string;
  fallbackAliases: string[];
  requiredCapabilities: string[];
}

export type ProviderRequestDefaults = Record<string, unknown>;

export type CapabilityFlags = {
  chat: boolean;
  responses: boolean;
  vision: boolean;
  embeddings: boolean;
  tools: boolean;
  jsonSchema: boolean;
  structuredOutput: boolean;
  streaming: boolean;
  thinking?: boolean;
};

export type ProviderModelTokenLimit = {
  contextWindowTokens?: number;
  maxOutputTokens?: number;
};

export type ProviderConfig = {
  name: string;
  baseUrl: string;
  apiKeyRef: string;
  model: string;
  protocol?: ProviderProtocol;
  label?: string;
  mode?: "direct" | "gateway";
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
  contextWindowTokens?: number;
  maxOutputTokens?: number;
  embeddingModel?: string;
    catalogSource?: "provider_live" | "cached" | "manual";
    cacheTtlSeconds?: number;
    profileId?: string;
    profileLabel?: string;
    profileMode?: string;
    connectionType?: string;
  profileCount?: number;
  profileHistory?: Array<Record<string, unknown>>;
  providerProfiles?: Array<Record<string, unknown>>;
  providerDashboard?: Record<string, unknown>;
  capabilities: CapabilityFlags;
};

export interface ProviderProfileConfig extends Omit<ProviderConfig, "taskBindings" | "requestDefaults"> {
  id: string;
  label: string;
  credentialMode: ProviderCredentialMode;
  taskBindings: Record<string, ProviderTaskBinding>;
  requestDefaults: ProviderRequestDefaults;
}

export type UserProfile = {
  longTermGoal: string;
  background: string;
  weeklyHours: number;
  teachingStyle: string;
  answerPolicy: "auto" | "guided" | "balanced" | "direct";
  targetProject?: string;
  preferredLibraries: string[];
};

export type PlanStage = {
  id: string;
  title: string;
  goal: string;
  outcomes: string[];
  resources: string[];
  status: "pending" | "active" | "completed";
};

export type SubPlan = {
  id: string;
  parentPlanId: string;
  title: string;
  description: string;
  stages: PlanStage[];
  status: "draft" | "active" | "completed" | "archived";
  progressPercent: number;
  createdAt: string;
  updatedAt: string;
};

export type LearningPlan = {
  id: string;
  title: string;
  summary: string;
  stages: PlanStage[];
  cadence: string;
  frozen: boolean;
  currentStageId?: string;
  currentStep?: string;
  whyNow?: string;
  verifyMethod?: string[];
  blockedReason?: string;
  nextAfterCurrent?: string;
  workspaceId?: string;
};

export type GlobalPlan = {
  id: string;
  ownerId: string;
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
  createdAt: string;
  updatedAt: string;
};

export type GlobalPlanProjectLink = {
  globalPlanId: string;
  workspaceId: string;
  projectPlanId: string;
  linkedAt: string;
  updatedAt: string;
};

export type PlanRuntimeCurrentStage = {
  id?: string;
  title?: string;
  goal?: string;
  status?: string;
};

export type PlanRuntimeCurrentThread = {
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

export type FolderRole =
  | "empty_new_project"
  | "existing_engineering"
  | "algorithm_model"
  | "idea_scratchpad"
  | "learning_materials"
  | "mixed_uncertain";

export type ProjectTypeGuess =
  | "web_app"
  | "api_service"
  | "cli_tool"
  | "library_package"
  | "ml_model"
  | "notebook_research"
  | "mobile_app"
  | "desktop_app"
  | "embedded_iot"
  | "data_pipeline"
  | "monorepo"
  | "documentation"
  | "game"
  | "config_dotfiles"
  | "unknown";

export type ActiveThreadSnapshot = {
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
};

export type FirstLookSummary = {
  folderRole: FolderRole;
  projectTypeGuess: ProjectTypeGuess;
  confidence: number;
  whyThisGuess: string;
  entryPoints: string[];
  directoryAnchors: string[];
  coreModulesOrMaterials: string[];
  riskZones: string[];
  trainingOpportunities: string[];
  unknowns: string[];
  recommendedNextStep: string;
  classificationMethod: "heuristic" | "llm_enhanced";
  classifiedAt: string;
};

export type WorkspaceUnderstandingSnapshot = {
  repoSummary: string;
  entryPoints: string[];
  featureLanes: string[];
  riskZones: string[];
  trainingOpportunities: string[];
  resourceBrief: string;
  firstLookSummary?: FirstLookSummary;
  updatedAt: string;
};

export type PlanRuntimeReviewPoint = {
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
};

export type PlanRuntimeCoachJudgment = {
  summary?: string;
  teachingGoal?: string;
  interventionStrategy?: string;
  supportStrategy?: string;
  resumeThread?: string;
};

export type PlanRuntimeStatus = {
  currentStage?: PlanRuntimeCurrentStage;
  currentMainThread?: PlanRuntimeCurrentThread;
  reviewPoints: PlanRuntimeReviewPoint[];
  coachJudgment?: PlanRuntimeCoachJudgment;
  nextTrainingAction?: string;
  reviewQueueSummary?: string;
  nextReviewDue?: string;
  currentStep?: string;
  currentStageId?: string;
  whyNow?: string;
  verifyMethod?: string[];
  blockedReason?: string;
  nextAfterCurrent?: string;
  recovered?: boolean;
  resumeState?: "interrupted" | "in_progress" | "waiting";
  requestId?: string;
  revision?: number;
};

export type ResourceRecord = {
  id: string;
  kind: "pdf" | "image" | "text" | "markdown" | "code" | "url";
  name: string;
  source: string;
  tags: string[];
  sourceItems?: string[];
  collectionPath?: string;
  collectionRoot?: string;
  summary: string;
  parseStatus: "pending" | "parsed" | "failed";
  indexStatus: "pending" | "indexed" | "failed";
  sourceType?: string;
  canonicalSource?: string;
  fetchedAt?: string;
  trustScore?: number;
  freshness?: "fresh" | "stale" | "unknown";
  duplicateKey?: string;
  qualityFlags?: string[];
  warnings?: string[];
  sandboxPath?: string;
  sandboxOrigin?: string;
  sandboxSyncedAt?: string;
  sandboxDirty?: boolean;
  extractedArtifactPath?: string;
  knowledgeFragments?: Array<{
    id: string;
    snippet: string;
    source: string;
    kind: string;
    trustScore: number;
    freshness: "fresh" | "stale" | "unknown";
    whyItMatters: string;
  }>;
};

export type TaskSpec = {
  id: string;
  title: string;
  naturalLanguageGoal: string;
  inputs: string[];
  outputs: string[];
  constraints: string[];
  edgeCases: string[];
  failureConditions: string[];
  verificationStrategy: string[];
  workspaceId?: string;
};

export type EvaluationCheck = {
  id: string;
  label: string;
  status: "passed" | "failed" | "warning" | "skipped";
  detail: string;
};

export type EvaluationReport = {
  taskSpecId?: string;
  summary: string;
  staticChecks: EvaluationCheck[];
  dynamicChecks: EvaluationCheck[];
  semanticChecks: EvaluationCheck[];
  nextStep: string;
  reflection?: string;
  passed: boolean;
  workspaceId?: string;
};

export type ReviewQueueItem = {
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
};

export type ReviewQueueActionSnapshot = {
  action: "accept" | "snooze" | "done" | "skip" | "reset";
  outcome: "queued" | "completed" | "needs_more_practice" | "deferred" | "dismissed";
};

export type ReviewArtifactSnapshot = {
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
  blocker?: string;
  abandonReason?: string;
  partialProgress?: string;
  scenario?: string;
  lastAction?: string;
  updatedAt?: string;
};

export type ReviewArtifactHistoryEntry = {
  entryId?: string;
  id?: string;
  reviewArtifactId?: string;
  action: "created" | "updated" | "reviewed" | "resolved" | "reopened" | "archived" | "restore_history";
  version?: number;
  createdAt?: string;
  beforeSnapshot?: Record<string, unknown>;
  afterSnapshot?: Record<string, unknown>;
};

export type DependencySkillItemSnapshot = {
  key?: string;
  label?: string;
  scenario?: string;
  gaps?: string[];
  nextActions?: string[];
  acceptedAnswers?: string[];
  canonicalAnswer?: string;
  relatedApi?: string;
  whyNow?: string;
  projectFirstCut?: string;
  prioritySummary?: string;
  suggestedScenarioLab?: string;
};

export type DependencySkillMapSnapshot = {
  dependencyKey?: string;
  dependencyName?: string;
  projectFirstCut?: string;
  prioritySummary?: string;
  suggestedScenarioLab?: string;
};

export type DependencySkillMapHistoryEntry = {
  entryId?: string;
  id?: string;
  dependencyKey?: string;
  action?: "created" | "updated" | "restore_history";
  version?: number;
  createdAt?: string;
  beforeSnapshot?: Record<string, unknown>;
  afterSnapshot?: Record<string, unknown>;
};

export type ScenarioLab = {
  id?: string;
  title?: string;
  focusArea?: string;
  status?: string;
  scenario?: string;
  whyNow?: string;
  learnerDeliverables?: string[];
  verificationSteps?: string[];
  successSignal?: string;
  reviewOutcome?: string;
  migrateBackGuidance?: string[];
  dependencyKeys?: string[];
  relatedApis?: string[];
  lastAction?: string;
  updatedAt?: string;
};

export type ScenarioLabHistoryEntry = {
  entryId?: string;
  id?: string;
  scenarioLabId?: string;
  action?: string;
  version?: number;
  createdAt?: string;
  beforeSnapshot?: Record<string, unknown>;
  afterSnapshot?: Record<string, unknown>;
};

export type TheoryDrillHistoryEntry = {
  entryId?: string;
  id?: string;
  theoryDrillId?: string;
  action?: string;
  version?: number;
  createdAt?: string;
  beforeSnapshot?: Record<string, unknown>;
  afterSnapshot?: Record<string, unknown>;
};

export type LearnerSignal = "steady" | "blocked" | "uncertain" | "curious";

export type CoachingScenario =
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

export type CoachingState = {
  scenario: CoachingScenario;
  answerMode: "guided" | "balanced" | "direct";
  learnerSignal: LearnerSignal;
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
};

export type MemoryShareCategory = "preferences" | "mastery";

export type MemoryShareGrant = {
  sourceWorkspaceId: string;
  targetWorkspaceId: string;
  categories: MemoryShareCategory[];
  createdAt?: string;
  updatedAt?: string;
};

export type CoachingAdaptationProfile = {
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
};

export type MemorySnapshot = {
  profile?: UserProfile;
  activePlan?: LearningPlan;
  subplans?: SubPlan[];
  resources: ResourceRecord[];
  weaknesses: string[];
  reflections: string[];
  recentSummary: string;
  currentFocus: string;
  coachAnchor?: string;
  topWeakness?: string;
  lowestMasteryConcepts?: string[];
  recentWins: string[];
  reviewRhythm: string;
  dueReviews: ReviewQueueItem[];
  dueReviewCount?: number;
  paceSignal?: string;
  teachingObservations: string[];
  activeThread?: ActiveThreadSnapshot;
  memoryEvidence: string[];
  memoryShareGrants?: MemoryShareGrant[];
  evidenceQueue?: EvidenceQueueSnapshot;
  providerDiagnostics?: Array<Record<string, unknown>>;
  workspaceUnderstanding?: WorkspaceUnderstandingSnapshot;
  coachingAdaptation?: CoachingAdaptationProfile;
};

export type EvidenceItem = {
  id: string;
  workspaceId?: string;
  summary: string;
  source: "card_result" | "evaluation" | "learning_signal" | "coaching_observation" | "resource_import" | "review_queue" | string;
  sourceCardId?: string;
  concepts: string[];
  outcome: "pass" | "fail" | "partial" | "insight" | "observation" | string;
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
};

export type EvidenceQueueSnapshot = {
  pending: EvidenceItem[];
  deferred: EvidenceItem[];
  adopted: EvidenceItem[];
  rejected: EvidenceItem[];
  history?: EvidenceItem[];
  totalCount: number;
};

export type LearnerState = {
  currentConfidence: number;
  frustrationLevel: number;
  attemptCountRecent: number;
  needsRescue: boolean;
  needsReview: boolean;
  preferredHintDepth: string;
  learnerSignal: LearnerSignal;
  activeFocus: string;
  evidence: string[];
};

export type TeachingMode =
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

export type ToneProfile =
  | "steady"
  | "guided_build"
  | "proactive_coach"
  | "steady_migration"
  | "teaching_clarity"
  | "review_loop"
  | "concise_rescue";

export type AffectState = {
  frustrationLevel: number;
  confidenceLevel: number;
  momentumLevel: number;
  needsReassurance: boolean;
  urgencyLevel: "low" | "medium" | "high";
  recoverySignal: "steady" | "recovering" | "fragile" | "overloaded";
};

export type ToneDecision = {
  tone: "steady" | "encouraging" | "concise_rescue" | "reflective";
  verbosityBias: "short" | "medium" | "expanded";
  acknowledgeProgress: boolean;
  avoidOverwhelm: boolean;
};

export type TeachingDecision = {
  mode: TeachingMode;
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
  toneProfile: ToneProfile;
  focusArea?: string;
};

export type ImplementationGuide = {
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
};

export type ProjectIdeaKind =
  | "feature"
  | "refactor"
  | "test"
  | "architecture"
  | "developer_experience";

export type ProjectIdea = {
  id: string;
  title: string;
  summary: string;
  sourceArea: string;
  ideaKind: ProjectIdeaKind;
  learningValue: string;
  engineeringValue: string;
  difficulty: string;
  suggestedScope: string;
  firstStep: string;
  acceptanceSignals: string[];
  whyNow: string;
};

export type ProjectAdaptationGuide = {
  targetOutcome: string;
  currentConstraints: string[];
  affectedAreas: string[];
  preserveAreas: string[];
  firstMigrationStep: string;
  migrationSequence: string[];
  validationCheckpoints: string[];
  rollbackNotes: string[];
};

export type ProjectSourceSuggestion = {
  title: string;
  sourceKind: "reference_repo" | "reference_impl" | "training_repo";
  repoHint: string;
  fitReason: string;
  trainingValue: string;
  firstFilter: string;
  firstTask: string;
  caution: string;
  tags: string[];
  sourceUrl: string;
  retrievedAt: string;
  trustScore: number;
  qualityFlags: string[];
};

export type PrincipleNote = {
  currentPrinciple: string;
  whyItMatters: string;
  commonMistake: string;
  applyNow: string;
  transferTargets: string[];
  concreteAnchor?: string;
  transferableLesson?: string;
  relatedChecks?: string[];
  sourceAssetTitle?: string;
};

export type TrainingSubmode =
  | "practice"
  | "flash"
  | "review"
  | "review_queue"
  | "learn_primer"
  | "learn-primer"
  | "scenario"
  | "transfer";

export type FlashcardRecoveryMode =
  | "flashcards"
  | "scenario_lab_or_project"
  | "transfer"
  | "review";
