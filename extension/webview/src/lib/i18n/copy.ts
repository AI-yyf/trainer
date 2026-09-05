/**
 * Trainer 核心国际化翻译表
 * 支持 8 种语言：zh-CN, en-US, es-ES, fr-FR, de-DE, ja-JP, ko-KR, pt-BR
 */

import type { ComposerLanguage } from "../types";

// =============================================================================
// Copy Key 类型定义
// =============================================================================
export type CopyKey =
  // 核心角色
  | "coach"
  | "trainer"
  | "you"
  | "plan"
  | "settings"
  | "chat"
  | "workspace"
  | "viewNavigation"

  // 视图标签
  | "currentFocus"
  | "currentTask"
  | "latestReview"
  | "viewContextWorking"
  | "viewContextBlocker"
  | "viewContextLatest"
  | "viewContextCoach"
  | "backgroundAnalysis"
  | "backgroundCoachWork"
  | "firstLookBadge"
  | "firstLookProjectType"
  | "firstLookFolderRole"
  | "firstLookWhyGuess"
  | "firstLookEntryPoints"
  | "firstLookDirectoryAnchors"
  | "firstLookCoreModules"
  | "firstLookRiskZones"
  | "firstLookOpportunities"
  | "firstLookUnknowns"
  | "firstLookNextStep"
  | "workspaceAdmissionRootMissing"
  | "workspaceAdmissionRootMissingDetail"
  | "workspaceAdmissionGoalSaved"
  | "workspaceAdmissionProjectFound"
  | "workspaceAdmissionProjectFoundDetail"
  | "workspaceAdmissionManaged"
  | "workspaceAdmissionManagedDetail"
  | "workspaceAdmissionBrowse"
  | "workspaceAdmissionBrowseDetail"
  | "workspaceAdmissionIgnored"
  | "workspaceAdmissionIgnoredDetail"
  | "workspaceAdmissionProjectName"
  | "workspaceAdmissionProjectPath"
  | "workspaceAdmissionSelectRoot"
  | "workspaceAdmissionSelectProject"
  | "workspaceAdmissionAdd"
  | "workspaceAdmissionBrowseAction"
  | "workspaceAdmissionIgnore"
  | "workspaceAdmissionDelete"
  | "workspaceRootControl"
  | "workspaceRootReady"
  | "workspaceRootPath"
  | "workspaceRootMigrate"
  | "workspaceRootMigrateDetail"
  | "workspaceRootRecovery"
  | "workspaceRootBackup"
  | "workspaceRootBackupDetail"
  | "workspaceRootRestore"
  | "workspaceRootRestoreDetail"
  | "workspaceRootChange"
  | "workspaceRootChangeDetail"
  | "coachState"
  | "coachSignal"
  | "reviewQueue"
  | "reviewMemory"
  | "reviewRhythm"
  | "nextReview"
  | "teachingObservations"
  | "coachSummaryDoing"

  // 计划相关
  | "goals"
  | "constraints"
  | "acceptance"
  | "nextMove"
  | "recentWins"
  | "weakSpots"
  | "planStages"
  | "trainingWhyNow"
  | "trainingDeliverable"

  // 设置 - 界面
  | "language"
  | "answerMode"
  | "auto"
  | "teachingStyle"
  | "teachingGuided"
  | "teachingConceptFirst"
  | "teachingHandsOn"
  | "teachingChallenging"
  | "contextDetail"
  | "coachFirst"
  | "balanced"
  | "direct"
  | "detailFocused"
  | "detailBalanced"
  | "detailFull"
  | "attachments"
  | "currentContext"
  | "allContext"
  | "noContext"

  // 设置 - 文件上下文
  | "file"
  | "selection"
  | "diagnostics"
  | "relatedFiles"
  | "follow"
  | "theme"
  | "system"
  | "light"
  | "dark"

  // 设置 - Provider
  | "provider"
  | "protocol"
  | "baseUrl"
  | "chatModel"
  | "apiKey"
  | "apiKeySaved"
  | "apiKeyMissing"
  | "saveProvider"
  | "testProvider"
  | "clearProvider"
  | "openConfigFile"
  | "configured"
  | "notConfigured"
  | "refreshProviderProfiles"
  | "refreshWorkspaceAuthority"
  | "createProfileFromTemplate"

  // CoachSettingsView labels
  | "settingsSetupSection"
  | "settingsSetupTitleReady"
  | "settingsSetupTitleBlocked"
  | "settingsSetupDetailReady"
  | "settingsSetupDetailBlocked"
  | "settingsSetupAction"
  | "settingsInterfaceSection"
  | "settingsCoachSection"
  | "settingsModelSection"
  | "settingsFollowCurrentFile"
  | "settingsContextMode"
  | "settingsCurrentFile"
  | "settingsConnectionDetails"
  | "settingsLongTermMemory"
  | "settingsMemoryScope"
  | "settingsMemoryScopeProject"
  | "settingsMemoryScopePersonal"
  | "settingsMemoryScopeSession"
  | "settingsMemorySharing"
  | "settingsMemorySharingDetail"
  | "settingsMemorySharingNone"
  | "settingsMemorySharingActive"
  | "settingsMemorySharingUnavailable"
  | "settingsMemoryShareGrant"
  | "settingsMemoryShareRevoke"
  | "settingsMemorySharePreferences"
  | "settingsMemoryShareMastery"
  | "settingsRememberDecisions"
  | "settingsRememberPatterns"
  | "settingsRememberResources"
  | "settingsWorkingSet"
  | "settingsWorkingSetFocused"
  | "settingsWorkingSetBalanced"
  | "settingsWorkingSetBroad"
  | "settingsMemoryPreview"
  | "settingsMemoryPreviewEmpty"
  | "settingsTeachingSignal"
  | "settingsConfigFileNote"
  | "settingsContextSection"
  | "settingsMemoryRuntime"
  | "settingsMemoryRuntimeDetail"
  | "settingsAdvancedSection"
  | "settingsAdvancedIntro"
  | "settingsReviewRhythmPace"
  | "settingsReviewRhythmReminder"
  | "settingsReviewStrategy"
  | "settingsSystemActions"
  | "settingsRefreshMemory"
  | "settingsResetDefaults"
  | "settingsModelTools"
  | "settingsDefaultsHint"
  | "settingsContextHint"
  | "settingsModelHint"
  | "settingsThinking"
  | "settingsThinkingDetail"
  | "settingsThinkingOff"
  | "settingsThinkingAuto"
  | "settingsThinkingOn"
  | "settingsThinkingAdvanced"
  | "settingsThinkingEffort"
  | "settingsThinkingBudget"
  | "settingsThinkingUnsupported"
  | "settingsThinkingOpenAiEffort"
  | "settingsThinkingAnthropicBudget"
  | "settingsThinkingGeminiConfig"
  | "settingsThinkingMiniMaxDisabled"
  | "settingsAvailableModels"
  | "settingsDetectedModel"
  | "settingsModelFetchLoading"
  | "settingsModelFetchEmpty"
  | "settingsRefreshModels"
  | "settingsModelCache"
  | "settingsModelCacheSource"
  | "settingsModelCacheFetchedAt"
  | "settingsModelCacheExpiresAt"
  | "settingsModelCacheStatus"
  | "settingsModelCacheError"
  | "settingsModelCacheSourceLive"
  | "settingsModelCacheSourceCache"
  | "settingsModelCacheStatusFresh"
  | "settingsModelCacheStatusExpired"
  | "settingsModelCacheStatusUnknown"
  | "settingsModelCacheStatusLoading"
  | "settingsModelCacheStatusError"
  | "settingsRuntimeSection"
  | "settingsRuntimeHint"
  | "settingsMemoryStrategy"
  | "settingsMemoryStrategyHint"
  | "settingsReviewStrategyHint"
  | "settingsContextCurrentFileHint"
  | "settingsContextSelectionHint"
  | "settingsContextDiagnosticsHint"
  | "settingsContextRelatedFilesHint"
  | "settingsMemoryScopeRuntimeProject"
  | "settingsMemoryScopeRuntimePersonal"
  | "settingsMemoryScopeRuntimeSession"
  | "settingsMemoryScopeProjectHint"
  | "settingsMemoryScopePersonalHint"
  | "settingsMemoryScopeSessionHint"
  | "settingsWorkingSetFocusedHint"
  | "settingsWorkingSetBalancedHint"
  | "settingsWorkingSetBroadHint"
  | "settingsReviewCadenceLightHint"
  | "settingsReviewCadenceSteadyHint"
  | "settingsReviewCadenceActiveHint"
  | "settingsReviewReminderDueHint"
  | "settingsReviewReminderAheadHint"
  | "settingsReviewReminderDigestHint"
  | "settingsSavedState"
  | "settingsUnsavedState"
  | "settingsEmptyState"
  | "settingsEffectiveNow"
  | "settingsSavedInWorkspace"
  | "settingsEditingDraft"
  | "settingsCurrentWorkspace"
  | "settingsLocalThemeNote"
  | "settingsWorkspaceSaveNote"
  | "settingsProviderRuntimeNote"
  | "settingsLatestAction"
  | "settingsLastTest"
  | "settingsLastTestNever"
  | "settingsLastTestPassed"
  | "settingsLastTestFailed"
  | "settingsLastTestNeedsSetup"
  | "settingsFocused"
  | "settingsBalancedContext"
  | "settingsFullContext"
  | "settingsSaveCoachDefaults"

  // 设置文案
  | "settingsIntro"
  | "settingsGeneral"
  | "settingsCoachBehavior"
  | "settingsModelAccess"
  | "settingsWorkspaceNote"
  | "settingsProviderHint"
  | "settingsCoachHint"

  // 对话状态
  | "send"
  | "streaming"
  | "configureProviderFirst"
  | "configureProviderFirstPlan"
  | "providerRequiredHint"
  | "composerPlaceholder"
  | "composerPlaceholderPlan"

  // 斜杠命令
  | "slashCommands"
  | "runLocalCommand"
  | "switchView"
  | "setLanguage"
  | "setAnswerMode"
  | "setContextDetail"
  | "setAttachments"
  | "setLiveFollow"

  // 通用状态
  | "opened"
  | "updated"
  | "on"
  | "off"
  | "connected"
  | "starting"
  | "offline"
  | "pass"
  | "fail"
  | "warn"
  | "pending"

  // 快捷操作
  | "suggestedActions"
  | "generatePlan"
  | "nextTask"
  | "runReview"
  | "openCoach"
  | "openPlan"
  | "openSettings"

  // 快捷键提示
  | "shortcutSend"
  | "shortcutNewline"
  | "shortcutSlash"
  | "shortcutClear"

  // 错误提示
  | "reviewNeedsFile"
  | "reviewFileDisabled"
  | "selectionMissing"
  | "selectionDisabled"
  | "relatedMissing"

  // 训练相关
  | "training"
  | "flashcards"
  | "practice"
  | "review"
  | "startTraining"
  | "nextCard"
  | "previousCard"
  | "showAnswer"
  | "submitAnswer"
  | "skipCard"
  | "markAgain"
  | "markHard"
  | "markGood"
  | "markEasy"
  | "dueToday"
  | "cardsToReview"
  | "learningPath"
  | "masteryLevel"
  | "streak"
  | "totalReviews"
  | "accuracy"

  // 训练反馈与激励
  | "streakMessageBeginning"
  | "streakMessageBuilding"
  | "streakMessageStrong"
  | "streakMessageExcellent"
  | "streakMessageExpert"
  | "reviewReminderFew"
  | "reviewReminderSome"
  | "reviewReminderMany"
  | "timeGreetingMorning"
  | "timeGreetingAfternoon"
  | "timeGreetingEvening"
  | "timeGreetingNight"
  | "masteryMilestone10"
  | "masteryMilestone50"
  | "practiceEncouragement"
  | "growthMindset"
  | "winCelebration"
  | "practiceReady"
  | "progressTip"
  | "focusTime"
  | "conceptProgress"
  | "learningStreak"
  | "sessionSummary"

  // 强化学习相关
  | "reinforcementLearning"
  | "qLearning"
  | "dqn"
  | "policyGradient"
  | "actorCritic"
  | "ddpg"
  | "ppo"
  | "mcts"
  | "algorithm"
  | "state"
  | "action"
  | "reward"
  | "policy"
  | "valueFunction"
  | "qTable"
  | "epsilon"
  | "discountFactor"
  | "learningRate"
  | "exploration"
  | "exploitation"
  | "bellmanEquation"
  | "temporalDifference"
  | "monteCarlo"
  | "onPolicy"
  | "offPolicy"
  | "experienceReplay"
  | "targetNetwork"
  | "policyLoss"
  | "valueLoss"
  | "entropyBonus"
  | "clipping"
  | "gae"
  | "advantage"
  | "rollout"
  | "backpropagation"
  | "gradient"
  | "optimizer"
  | "adam"
  | "sgd"
  | "batchSize"
  | "episode"
  | "step"
  | "horizon"
  | "environment"
  | "agent"
  | "observation"
  | "episodeEnd"
  | "cumulativeReward"
  | "convergence"
  | "divergence"
  | "trainingCurve"
  | "evaluationMetric"
  | "hyperparameter"
  | "architecture"
  | "networkLayer"
  | "inputLayer"
  | "outputLayer"
  | "hiddenLayer"
  | "activation"
  | "relu"
  | "sigmoid"
  | "softmax"
  | "lossFunction"
  | "crossEntropy"
  | "mse"
  | "regularization"
  | "dropout"
  | "batchNorm"
  | "earlyStopping"
  | "checkpoint"
  | "saveModel"
  | "loadModel"
  | "export"
  | "import"

  // 会话相关
  | "newConversation"
  | "continueConversation"
  | "deleteConversation"
  | "renameConversation"
  | "searchConversations"
  | "noConversations"
  | "typing"
  | "coachThinking"
  | "coachTyping"
  | "coachArtifactFullDetails"
  | "regenerate"
  | "copyMessage"
  | "editMessage"
  | "deleteMessage"
  | "messageCopied"
  | "errorOccurred"
  | "tryAgain"
  | "cancel"
  | "confirm"
  | "save"
  | "close"
  | "back"
  | "next"
  | "loading"
  | "empty"
  | "noResults"
  | "searchResults"
  | "filter"
  | "sort"
  | "refresh"
  | "timeout"
  | "networkError"
  | "unknownError"

  // 证据相关
  | "evidenceOutcomePass"
  | "evidenceOutcomeFail"
  | "evidenceOutcomePartial"
  | "evidenceOutcomeInsight"
  | "evidenceOutcomeObservation"

  // 证据来源
  | "evidenceSourceCardResult"
  | "evidenceSourceEvaluation"
  | "evidenceSourceLearningSignal"
  | "evidenceSourceCoachingObservation"
  | "evidenceSourceResourceImport"
  | "evidenceSourceReviewQueue"

  // 人类友好状态
  | "reviewReminderNone"
  | "greetingMorning"
  | "greetingAfternoon"
  | "greetingEvening"
  | "greetingNight"
  | "masteryProgress"
  | "practiceTimeInvested"
  | "cardsMastered"
  | "signalsWaiting"
  // 新增人性化引导
  | "firstTimeWelcome"
  | "firstTimeSetupHint"
  | "quickStartGuide"
  | "providerConnected"
  | "providerDisconnected"
  | "modelReady"
  | "apiKeyStillMissing"
  | "progressToGoal"
  | "dailyGoalProgress"
  | "keepGoingMessage"
  | "almostThereMessage"
  | "greatJobMessage"
  | "newRecordMessage"
  | "coachLearningGoal"
  | "coachAssessingLevel"
  | "coachGeneratingPlan"
  | "coachAdjustingPlan"

  // 教练动作状态
  | "coachActionIdle"
  | "coachActionCheckingResources"
  | "coachActionSearchingResources"
  | "coachActionAligningPlan"
  | "coachActionPlanAlignment"
  | "coachActionSchedulingTraining"
  | "coachActionGeneratingCard"
  | "coachActionCardGeneration"
  | "coachActionEvaluatingResult"
  | "coachActionEvaluation"
  | "coachActionReviewingEvidence"
  | "coachActionResourceUpload"
  | "coachActionWorkspaceClassification"
  | "coachActionDoneIdle"
  | "coachActionDoneCheckingResources"
  | "coachActionDoneSearchingResources"
  | "coachActionDoneAligningPlan"
  | "coachActionDonePlanAlignment"
  | "coachActionDoneSchedulingTraining"
  | "coachActionDoneGeneratingCard"
  | "coachActionDoneCardGeneration"
  | "coachActionDoneEvaluatingResult"
  | "coachActionDoneEvaluation"
  | "coachActionDoneReviewingEvidence"
  | "coachActionDoneResourceUpload"
  | "coachActionDoneWorkspaceClassification"

  // 掌握度阶段
  | "masteryUnderstood"
  | "masteryRecalled"
  | "masteryPracticed"
  | "masteryApplied"
  | "masteryTransferable"
  | "masteryNotEstablished"

  // 学习旅程
  | "learningJourney"
  | "learningJourneyProgress"
  | "currentSuggestion"
  | "nextActionHintUnderstood"
  | "nextActionHintRecalled"
  | "nextActionHintPracticed"
  | "nextActionHintApplied"
  | "nextActionHintTransferable"
  | "sessionSummary"
  | "cardsCompleted"
  | "conceptsMastered"
  | "currentCard"
  | "practiceCard"
  | "flashCard"
  | "waitingForRouting"
  | "resourceRiskPaused"
  | "refreshResourceFirst"

  // 资源视图
  | "addFiles"
  | "addFolder"
  | "addUrl"
  | "resourcesEmpty"
  | "resourcesMenu"
  | "resourcesSummary"
  | "resourcesSandbox"
  | "resourcesSandboxRoot"
  | "resourcesSandboxRefresh"
  | "resourcesSandboxNewFile"
  | "resourcesSandboxNewFolder"
  | "resourcesSandboxRename"
  | "resourcesSandboxTrash"
  | "resourcesSandboxEmpty"
  | "resourcesSandboxBoundaryRefresh"
  | "resourcesSandboxOpenRoot"
  | "resourcesSandboxChooseRoot"
  | "resourcesSandboxResetRoot"
  | "resourcesSandboxActionBase"
  | "resourcesSandboxCreateIn"
  | "resourcesSandboxTargetCurrent"
  | "resourcesSandboxTargetRoot"
  | "resourcesSandboxParent"
  | "resourcesSandboxResolvedPath"
  | "resourcesSandboxSourcePath"
  | "resourcesSandboxWorkspaceRoot"
  | "resourcesSandboxSourceLabel"
  | "resourcesSandboxLedger"
  | "resourcesSandboxTrashRoot"
  | "resourcesSandboxMountedSources"
  | "resourcesSandboxNextSafeMove"
  | "resourcesSandboxFilePlaceholder"
  | "resourcesSandboxFolderPlaceholder"
  | "resourcesSandboxFileHint"
  | "resourcesSandboxFolderHint"
  | "resourcesSandboxRenamePlaceholder"
  | "resourcesSandboxRenameHint"
  | "resourcesSandboxManagedLayout"

  // 分析状态
  | "analysisReady"
  | "analysisStatus"
  | "analysisProgress"
  | "analysisFindings"
  | "analysisDecision"
  | "analysisNextStep"
  | "analysisAction"
  | "analysisThreads"
  | "advanceAnalysis"

  // 计划治理
  | "planLive"
  | "planFrozen"
  | "planFreeze"
  | "planSummary"
  | "planCurrentStage"
  | "planNextAction"
  | "planAdjust"
  | "planWhy"
  | "planCadence"
  | "approve"
  | "reject"

  // 阶段状态
  | "stageActive"
  | "stageDone"
  | "stageQueued"

  // 上下文
  | "contextMode"
  | "contextAutoNote"
  | "useFullContext"

  // 文件与诊断
  | "enableFile"
  | "enableSelection"
  | "enableRelated"
  | "relatedDisabled"
  | "diagnosticsMissing"
  | "maxFilesHint"

  // 视图与历史
  | "trainingView"
  | "trainingOpenCurrentCard"
  | "trainingReturnToCoach"
  | "trainingAnswerNow"
  | "trainingRecordStep"
  | "trainingStartStep"
  | "trainingEmptyTitle"
  | "trainingEmptyDescription"
  | "summaryEmpty"
  | "history"
  | "composerAccessibility"
  | "reviewNotFull"

  // Global plan relationship
  | "globalPlanLabel"
  | "globalPlanRelationship"
  | "globalPlanNotCreated"
  | "globalPlanNotLinked"
  | "globalPlanLinked"
  | "globalPlanCreate"
  | "globalPlanLinkCurrentProject"
  | "globalPlanLinkUnavailable"
  | "globalPlanFrozen"

  // Plan evidence governance
  | "evidenceConfidence"
  | "evidenceGovernance"
  | "evidenceFilterAll"
  | "evidenceFilterDeferred"
  | "evidenceFilterAdopted"
  | "evidenceFilterRejected"
  | "evidenceAdopt"
  | "evidenceDefer"
  | "evidenceTargetPrefix"
  | "evidenceNoMatches"

  // Provider capabilities
  | "capabilityChat"
  | "capabilityResponses"
  | "capabilityTools"
  | "capabilityStreaming"
  | "capabilityStructuredOutput"
  | "capabilityVision"
  | "capabilityEmbeddings"
  | "capabilityJsonSchema"
  | "capabilitySupported"
  | "capabilityNotSupported"

  // Learning feedback
  | "feedbackTooHard"
  | "feedbackTooSimple"
  | "feedbackMisunderstood"
  | "feedbackResourceIncorrect"
  | "feedbackPlanMismatch"
  | "feedbackCardUnrealistic"
  | "feedbackDisclosureSummary"
  | "feedbackDisclosureDetail"
  | "feedbackLearningLabel"
  | "feedbackRecording"
  | "feedbackRecorded"
  | "feedbackDismiss"

  // Orientation rail chrome
  | "orientationNow"
  | "orientationState"
  | "orientationNext"
  | "orientationMore"
  | "orientationStateNeedsSetup"
  | "orientationStateWaiting"
  | "orientationStateWorking"
  | "orientationStateBlocked"
  | "orientationStateReady"
  | "orientationStateInterrupted"
  | "leftoverNotLive"
  | "leftoverNotLiveHint"

  // Plan stage learning materials
  | "planStageMaterialsTitle"
  | "planStageMaterialsGenerate"
  | "planStageMaterialsGenerating"
  | "planStageMaterialsView"
  | "planStageMaterialsHide"
  | "planStageMaterialsEmpty"
  | "planStageCompletionLabel"
  | "planStageMaterialsBadgeTitle"

  // Plan progress dashboard (Plan view inner tab)
  | "planDashboardTabPlan"
  | "planDashboardTabProgress"
  | "planDashboardStagesTitle"
  | "planDashboardMasteryTitle"
  | "planDashboardReviewTitle"
  | "planDashboardMaterialsTitle"
  | "planDashboardMaterialsStages"
  | "planDashboardMasteryEmpty"
  | "planDashboardReviewDue"
  | "planDashboardReviewDone"
  | "planDashboardEmptyTitle"

  // Training card recovery
  | "trainingHandoffMismatchHint"
  | "trainingSwitchToCard"

  // Training card detail sections (CollapseSection titles)
  | "trainingCardDetailsApiHints"
  | "trainingCardDetailsSelfCheck"
  | "trainingCardDetailsRubric"
  | "trainingCardDetailsAcceptance"

  // Settings IA rebuild: status summary bar, answer-style presets, section titles
  | "settingsStatusRegionLabel"
  | "settingsStatusConnected"
  | "settingsStatusNotConnected"
  | "settingsStatusLanguage"
  | "settingsStatusMemory"
  | "settingsStatusNoApiKey"
  | "settingsStatusNeedsTest"
  | "settingsStatusTrust"
  | "settingsStatusUnsaved"
  | "settingsSectionConnection"
  | "settingsTeachingPrefs"
  | "settingsAnswerStyle"
  | "answerStyleSimple"
  | "answerStyleBalanced"
  | "answerStyleDeep"
  | "answerStyleCustom"
  | "settingsAnswerStyleHint"
  | "settingsAdvancedContext"
  | "settingsMemoryPrivacy"
  | "settingsAdvanced";

// =============================================================================
// 翻译表
// =============================================================================

export type Copy = Record<CopyKey, string>;
type LocaleCopy = Partial<Copy>;
type CopyTable = {
  "en-US": Copy;
} & Partial<Record<Exclude<ComposerLanguage, "en-US">, LocaleCopy>>;

export const copyTable = {
  // ==========================================================================
  // 中文 (简体)
  // ==========================================================================
  "zh-CN": {
    settingsStatusRegionLabel: "当前状态",
    settingsStatusConnected: "已连接",
    settingsStatusNotConnected: "未连接",
    settingsStatusLanguage: "语言",
    settingsStatusMemory: "记忆",
    settingsStatusNoApiKey: "缺少 API key",
    settingsStatusNeedsTest: "连接未测试",
    settingsStatusTrust: "工作区不受信",
    settingsStatusUnsaved: "有未保存更改",
    settingsSectionConnection: "连接",
    settingsTeachingPrefs: "教学偏好",
    settingsAnswerStyle: "回答风格",
    answerStyleSimple: "简单",
    answerStyleBalanced: "均衡",
    answerStyleDeep: "深度",
    answerStyleCustom: "自定义",
    settingsAnswerStyleHint: "预设决定上下文强度与附带内容，保存后生效。",
    settingsAdvancedContext: "高级上下文",
    settingsMemoryPrivacy: "记忆与隐私",
    settingsAdvanced: "高级",
    settingsMemorySharing: "跨项目记忆",
    settingsMemorySharingDetail: "默认隔离；仅读取你明确授权项目的偏好和掌握信号。",
    settingsMemorySharingNone: "尚未授权其他项目。",
    settingsMemorySharingActive: "个已授权来源",
    settingsMemorySharingUnavailable: "先将当前项目加入 Trainer，才能授权跨项目记忆。",
    settingsMemoryShareGrant: "授权项目",
    settingsMemoryShareRevoke: "撤销授权",
    settingsMemorySharePreferences: "偏好",
    settingsMemoryShareMastery: "掌握信号",
    // 核心角色
    coach: "教练",
    coachArtifactFullDetails: "查看完整内容",
    trainer: "教练",
    you: "你",
    plan: "计划",
    settings: "设置",
    chat: "对话",
    workspace: "工作区",
    viewNavigation: "Trainer 视图导航",

    // 视图标签
    currentFocus: "当前聚焦",
    currentTask: "当前训练动作",
    latestReview: "最近检查",
    backgroundAnalysis: "后台准备",
    backgroundCoachWork: "教练准备",
    firstLookBadge: "项目概览",
    firstLookProjectType: "项目类型",
    firstLookFolderRole: "文件夹角色",
    firstLookWhyGuess: "为什么这样判断",
    firstLookEntryPoints: "入口",
    firstLookDirectoryAnchors: "重点位置",
    firstLookCoreModules: "核心模块 / 资料",
    firstLookRiskZones: "风险区",
    firstLookOpportunities: "训练机会",
    firstLookUnknowns: "未确认项",
    firstLookNextStep: "下一步",
    workspaceAdmissionRootMissing: "未设置工作区根目录",
    workspaceAdmissionRootMissingDetail: "先选一个保存学习记录的位置，再决定如何处理此项目。",
    workspaceAdmissionGoalSaved: "你的目标还在输入框里。先选一个保存学习记录的位置，回来后可以直接发送。",
    workspaceAdmissionProjectFound: "发现项目",
    workspaceAdmissionProjectFoundDetail: "请选择：加入 Trainer、仅浏览，或忽略。",
    workspaceAdmissionManaged: "已由 Trainer 管理",
    workspaceAdmissionManagedDetail: "这个项目的对话、计划和学习记录会独立保存。",
    workspaceAdmissionBrowse: "仅浏览",
    workspaceAdmissionBrowseDetail: "可以查看当前项目；不会启动项目对话，也不会保存学习记录。",
    workspaceAdmissionIgnored: "已忽略",
    workspaceAdmissionIgnoredDetail: "Trainer 不会读取或管理此项目；需要时可重新加入。",
    workspaceAdmissionProjectName: "项目",
    workspaceAdmissionProjectPath: "路径",
    workspaceAdmissionSelectRoot: "选择工作区根目录",
    workspaceAdmissionSelectProject: "选择项目文件夹",
    workspaceAdmissionAdd: "加入 Trainer",
    workspaceAdmissionBrowseAction: "仅浏览",
    workspaceAdmissionIgnore: "忽略项目",
    workspaceAdmissionDelete: "删除项目",
    workspaceRootControl: "Trainer 工作区",
    workspaceRootReady: "学习记录正保存在此工作区。",
    workspaceRootPath: "根目录",
    workspaceRootMigrate: "迁移工作区",
    workspaceRootMigrateDetail: "复制到新的空目录，并继续使用新根目录。",
    workspaceRootRecovery: "备份与恢复",
    workspaceRootBackup: "备份工作区",
    workspaceRootBackupDetail: "复制可恢复的学习记录，不改变当前根目录。",
    workspaceRootRestore: "恢复备份",
    workspaceRootRestoreDetail: "恢复到新的空目录，并将其设为当前根目录。",
    workspaceRootChange: "切换根目录",
    workspaceRootChangeDetail: "直接选择另一个根目录，不复制当前数据。",
    coachState: "教练状态",
    coachSignal: "学习信号",
    reviewQueue: "复习队列",
    reviewMemory: "记忆与复习节奏",
    reviewRhythm: "复习节奏",
    nextReview: "下次复习",
    teachingObservations: "教学观察",
    coachSummaryDoing: "正在做",

    // 计划相关
    goals: "目标",
    constraints: "约束",
    acceptance: "验收标准",
    nextMove: "下一步",
    recentWins: "最近进步",
    weakSpots: "薄弱点",
    planStages: "阶段",
    trainingWhyNow: "为什么是现在",
    trainingDeliverable: "交付物",
    planStageMaterialsTitle: "学习资料",
    planStageMaterialsGenerate: "生成资料",
    planStageMaterialsGenerating: "生成中…",
    planStageMaterialsView: "查看",
    planStageMaterialsHide: "收起",
    planStageMaterialsEmpty: "这个阶段还没有学习资料。",
    planStageCompletionLabel: "阶段完成度",
    planStageMaterialsBadgeTitle: "已生成资料",
    planDashboardTabPlan: "计划",
    planDashboardTabProgress: "进度",
    planDashboardStagesTitle: "阶段完成度",
    planDashboardMasteryTitle: "依赖掌握度",
    planDashboardReviewTitle: "FSRS 复习保持率",
    planDashboardMaterialsTitle: "资料使用次数",
    planDashboardMaterialsStages: "覆盖阶段",
    planDashboardMasteryEmpty: "还没有掌握度数据。完成训练卡片后会在这里积累。",
    planDashboardReviewDue: "到期",
    planDashboardReviewDone: "已完成",
    planDashboardEmptyTitle: "先生成计划",
    trainingHandoffMismatchHint: "当前卡片和训练交接不一致，可切换到交接所属的卡片。",
    trainingSwitchToCard: "切换到该卡",
    trainingCardDetailsApiHints: "API 提示",
    trainingCardDetailsSelfCheck: "自查",
    trainingCardDetailsRubric: "评分规则",
    trainingCardDetailsAcceptance: "验收标准",

    // 设置 - 界面
    language: "语言",
    answerMode: "反馈方式",
    auto: "自动",
    teachingStyle: "教学风格",
    teachingGuided: "引导式",
    teachingConceptFirst: "原理先行",
    teachingHandsOn: "实战优先",
    teachingChallenging: "挑战式",
    contextDetail: "上下文强度",
    coachFirst: "引导",
    balanced: "平衡",
    direct: "直接",
    detailFocused: "聚焦",
    detailBalanced: "标准",
    detailFull: "完整",
    attachments: "附带上下文",
    currentContext: "当前文件",
    allContext: "全部上下文",
    noContext: "不附带上下文",

    // 设置 - 文件上下文
    file: "文件",
    selection: "选区",
    diagnostics: "诊断",
    relatedFiles: "相关文件",
    follow: "实时跟随",
    theme: "主题",
    system: "跟随系统",
    light: "浅色",
    dark: "深色",

    // 设置 - Provider
    provider: "连接服务",
    protocol: "连接方式",
    baseUrl: "服务地址",
    chatModel: "聊天模型",
    apiKey: "访问密钥",
    apiKeySaved: "已保存",
    apiKeyMissing: "未配置",
    saveProvider: "保存配置",
    testProvider: "测试连接",
    clearProvider: "清空配置",
    openConfigFile: "打开配置文件",
    configured: "已配置",
    notConfigured: "未配置",
    refreshProviderProfiles: "刷新配置列表",
    refreshWorkspaceAuthority: "刷新工作区权限",
    createProfileFromTemplate: "从模板创建",

    // CoachSettingsView labels
    settingsSetupSection: "模型连接",
    settingsSetupTitleReady: "模型可用",
    settingsSetupTitleBlocked: "模型不可用",
    settingsSetupDetailReady: "对话、计划、训练可用。",
    settingsSetupDetailBlocked: "填写连接信息和访问密钥后，就可以开始。",
    settingsSetupAction: "保存连接",
    settingsInterfaceSection: "教练默认",
    settingsCoachSection: "默认上下文",
    settingsModelSection: "连接模型",
    settingsFollowCurrentFile: "实时跟随",
    settingsContextMode: "上下文强度",
    settingsCurrentFile: "当前文件",
    settingsConnectionDetails: "连接详情",
    settingsLongTermMemory: "长期记忆",
    settingsMemoryScope: "记忆范围",
    settingsMemoryScopeProject: "当前项目",
    settingsMemoryScopePersonal: "个人通用",
    settingsMemoryScopeSession: "仅本次会话",
    settingsRememberDecisions: "架构决策",
    settingsRememberPatterns: "常用模式",
    settingsRememberResources: "参考资料",
    settingsWorkingSet: "工作集范围",
    settingsWorkingSetFocused: "只跟当前任务",
    settingsWorkingSetBalanced: "兼顾邻近文件",
    settingsWorkingSetBroad: "允许更宽引用",
    settingsMemoryPreview: "优先保留",
    settingsMemoryPreviewEmpty: "当前主要跟随文件、选区和诊断。",
    settingsTeachingSignal: "学习信号",
    settingsConfigFileNote: "需要更细的设置时，可以继续在配置文件里调整。",
    settingsContextSection: "附带上下文",
    settingsMemoryRuntime: "后台运行",
    settingsMemoryRuntimeDetail: "随发送更新。",
    settingsAdvancedSection: "更多默认策略",
    settingsAdvancedIntro: "记忆、复习、主题。",
    settingsReviewRhythmPace: "提醒强度",
    settingsReviewRhythmReminder: "提醒策略",
    settingsReviewStrategy: "复习策略",
    settingsSystemActions: "整理当前状态",
    settingsRefreshMemory: "刷新当前记忆",
    settingsResetDefaults: "恢复推荐默认",
    settingsModelTools: "连接工具",
    settingsDefaultsHint: "语言、反馈、教学风格。",
    settingsContextHint: "默认消息上下文。",
    settingsModelHint: "连接服务、模型和访问密钥。",
    settingsThinking: "原生思考",
    settingsThinkingDetail: "只显示当前模型支持的原生设置。",
    settingsThinkingOff: "关闭",
    settingsThinkingAuto: "自动",
    settingsThinkingOn: "开启",
    settingsThinkingAdvanced: "高级控制",
    settingsThinkingEffort: "思考强度",
    settingsThinkingBudget: "思考预算",
    settingsThinkingUnsupported: "当前模型没有已确认的原生思考设置。",
    settingsThinkingOpenAiEffort: "OpenAI effort",
    settingsThinkingAnthropicBudget: "Anthropic budget",
    settingsThinkingGeminiConfig: "Gemini thinkingConfig",
    settingsThinkingMiniMaxDisabled: "MiniMax thinking（已禁用）",
    settingsAvailableModels: "可用模型",
    settingsDetectedModel: "实际使用",
    settingsModelFetchLoading: "正在拉取模型列表…",
    settingsModelFetchEmpty: "保存 API key 后拉取。",
    settingsRefreshModels: "刷新模型列表",
    settingsModelCache: "模型列表状态",
    settingsModelCacheSource: "来源",
    settingsModelCacheFetchedAt: "最近拉取",
    settingsModelCacheExpiresAt: "失效时间",
    settingsModelCacheStatus: "状态",
    settingsModelCacheError: "错误原因",
    settingsModelCacheSourceLive: "实时拉取",
    settingsModelCacheSourceCache: "缓存结果",
    settingsModelCacheStatusFresh: "有效",
    settingsModelCacheStatusExpired: "已过期",
    settingsModelCacheStatusUnknown: "未知",
    settingsModelCacheStatusLoading: "刷新中",
    settingsModelCacheStatusError: "失败",
    settingsRuntimeSection: "当前教练运行时",
    settingsRuntimeHint: "这描述了如果现在发消息，Trainer 会继续哪个线程",
    settingsMemoryStrategy: "记忆策略",
    settingsMemoryStrategyHint: "这控制 Trainer 倾向于记住什么，以及这些记忆是留在当前项目还是迁移到其他项目",
    settingsReviewStrategyHint: "这控制 Trainer 多久提醒你回看一次，以及这些提醒会不会更主动地打断当前主线",
    settingsContextCurrentFileHint: "优先带上当前正在写的文件",
    settingsContextSelectionHint: "有选区时附带你当前圈住的代码",
    settingsContextDiagnosticsHint: "在评审或排错时带上诊断信息",
    settingsContextRelatedFilesHint: "只在需要更宽上下文时带上相关文件",
    settingsMemoryScopeRuntimeProject: "主要跟随当前项目里的计划、主线和资料",
    settingsMemoryScopeRuntimePersonal: "会跨项目保留你的偏好、判断和训练轨迹",
    settingsMemoryScopeRuntimeSession: "只紧贴当前这次会话，不主动带入更早记忆",
    settingsMemoryScopeProjectHint: "只在当前项目内延续训练主线和判断",
    settingsMemoryScopePersonalHint: "把可复用的习惯和判断带到别的项目里继续用",
    settingsMemoryScopeSessionHint: "只服务当前这一段对话，不主动延续更早的记忆",
    settingsWorkingSetFocusedHint: "尽量只盯住最小可验证切片和最近的相关文件",
    settingsWorkingSetBalancedHint: "默认兼顾当前切片和相邻上下文，适合大多数开发对话",
    settingsWorkingSetBroadHint: "当验证需要时，允许引用更宽的相关文件和背景",
    settingsReviewCadenceLightHint: "更少打断，保留关键复习点",
    settingsReviewCadenceSteadyHint: "按正常训练节奏推进和提醒",
    settingsReviewCadenceActiveHint: "更频繁回看，适合短周期冲刺",
    settingsReviewReminderDueHint: "主要在真正到期时提醒",
    settingsReviewReminderAheadHint: "在你快要需要它之前先提醒",
    settingsReviewReminderDigestHint: "把相近的回看点合并成一次提醒",
    settingsSavedState: "已保存",
    settingsUnsavedState: "未保存修改",
    settingsEmptyState: "当前工作区未写入",
    settingsEffectiveNow: "当前生效",
    settingsSavedInWorkspace: "工作区已保存",
    settingsEditingDraft: "正在编辑",
    settingsCurrentWorkspace: "当前工作区",
    settingsLocalThemeNote: "主题只影响你现在看到的界面，不会写进工作区",
    settingsWorkspaceSaveNote: "保存教练默认时，也会一起保存这些工作区级控制，后面会自动沿用",
    settingsProviderRuntimeNote: "测试连接时，会使用当前工作区此刻真正生效的连接配置",
    settingsLatestAction: "最近动作",
    settingsLastTest: "最近测试",
    settingsLastTestNever: "还没有测试过",
    settingsLastTestPassed: "已通过",
    settingsLastTestFailed: "失败",
    settingsLastTestNeedsSetup: "待补全",
    settingsFocused: "聚焦",
    settingsBalancedContext: "标准",
    settingsFullContext: "扩展",
    settingsSaveCoachDefaults: "保存教练默认",
    globalPlanLabel: "\u603b\u8ba1\u5212",
    globalPlanRelationship: "\u603b\u8ba1\u5212 -> \u5f53\u524d\u9879\u76ee\u8ba1\u5212",
    globalPlanNotCreated: "\u5c1a\u672a\u5efa\u7acb",
    globalPlanNotLinked: "\u5f53\u524d\u9879\u76ee\u5c1a\u672a\u5173\u8054",
    globalPlanLinked: "\u5df2\u5173\u8054\u5f53\u524d\u9879\u76ee",
    globalPlanCreate: "\u521b\u5efa\u603b\u8ba1\u5212",
    globalPlanLinkCurrentProject: "\u5173\u8054\u5f53\u524d\u9879\u76ee\u8ba1\u5212",
    globalPlanLinkUnavailable: "\u8bf7\u5148\u751f\u6210\u5f53\u524d\u9879\u76ee\u8ba1\u5212",
    globalPlanFrozen: "\u603b\u8ba1\u5212\u5df2\u51bb\u7ed3",
    evidenceConfidence: "\u7f6e\u4fe1",
    evidenceGovernance: "\u8bc1\u636e\u6cbb\u7406",
    evidenceFilterAll: "\u5168\u90e8",
    evidenceFilterDeferred: "\u5df2\u5ef6\u671f",
    evidenceFilterAdopted: "\u5df2\u63a5\u7eb3",
    evidenceFilterRejected: "\u5df2\u9a73\u56de",
    evidenceAdopt: "\u63a5\u7eb3",
    evidenceDefer: "\u5ef6\u671f",
    evidenceTargetPrefix: "\u76ee\u6807",
    evidenceNoMatches: "\u8fd9\u4e2a\u7b5b\u9009\u4e0b\u6ca1\u6709\u8bc1\u636e\u3002",
    capabilityChat: "\u5bf9\u8bdd",
    capabilityResponses: "Responses API",
    capabilityTools: "\u5de5\u5177\u8c03\u7528",
    capabilityStreaming: "\u6d41\u5f0f\u8f93\u51fa",
    capabilityStructuredOutput: "\u7ed3\u6784\u5316\u8f93\u51fa",
    capabilityVision: "\u89c6\u89c9\u7406\u89e3",
    capabilityEmbeddings: "\u5411\u91cf\u5d4c\u5165",
    capabilityJsonSchema: "JSON Schema",
    capabilitySupported: "\u652f\u6301",
    capabilityNotSupported: "\u4e0d\u652f\u6301",
    feedbackTooHard: "\u592a\u96be",
    feedbackTooSimple: "\u592a\u7b80\u5355",
    feedbackMisunderstood: "\u6ca1\u7406\u89e3",
    feedbackResourceIncorrect: "\u8d44\u6599\u4e0d\u5bf9",
    feedbackPlanMismatch: "\u8ba1\u5212\u4e0d\u5408\u9002",
    feedbackCardUnrealistic: "\u5361\u7247\u4e0d\u771f\u5b9e",
    feedbackDisclosureSummary: "\u8fd9\u4e00\u6b65\u4e0d\u5408\u9002\uff1f\u544a\u8bc9 Trainer",
    feedbackDisclosureDetail: "\u53ea\u8bb0\u5f55\u6559\u5b66\u53cd\u9988\uff0c\u4e0d\u4f1a\u76f4\u63a5\u6539\u52a8\u6b63\u5f0f\u8ba1\u5212\u3002",
    feedbackLearningLabel: "\u5b66\u4e60\u53cd\u9988",
    feedbackRecording: "\u6b63\u5728\u8bb0\u5f55\u2026",
    feedbackRecorded: "\u5df2\u8bb0\u5f55\u3002\u4e0b\u4e00\u6b65\u4f1a\u636e\u6b64\u8c03\u6574\uff1b\u8ba1\u5212\u53d8\u5316\u4ecd\u9700\u786e\u8ba4\u3002",
    feedbackDismiss: "\u5ffd\u7565",

    // 设置文案
    settingsIntro: "连接与默认项。",
    settingsGeneral: "界面与回复",
    settingsCoachBehavior: "教练行为",
    settingsModelAccess: "模型与连接",
    settingsWorkspaceNote: "高频偏好保存在工作区。",
    settingsProviderHint: "大模型连接。",
    settingsCoachHint: "上下文与反馈默认项。",

    // 对话状态
    send: "发送",
    streaming: "教练思考中…",
    configureProviderFirst: "还不能开始对话。请在“设置”里完成模型连接。",
    configureProviderFirstPlan: "还不能生成或调整计划。请先完成模型连接。",
    providerRequiredHint: "还没有可用的模型连接。",
    composerPlaceholder: "问教练",
    composerPlaceholderPlan: "写下这一步",

    // 斜杠命令
    slashCommands: "斜杠指令",
    runLocalCommand: "将执行本地命令",
    switchView: "切换视图",
    setLanguage: "切换语言",
    setAnswerMode: "调整反馈方式",
    setContextDetail: "调整上下文强度",
    setAttachments: "调整附带上下文",
    setLiveFollow: "切换实时跟随",

    // 通用状态
    opened: "已打开",
    updated: "已更新",
    on: "开启",
    off: "关闭",
    connected: "已连接",
    starting: "连接中",
    offline: "离线",
    pass: "通过",
    fail: "失败",
    warn: "警告",
    pending: "待处理",

    // 快捷操作
    suggestedActions: "建议操作",
    generatePlan: "生成计划",
    nextTask: "下一步任务",
    runReview: "开始复习",
    openCoach: "打开教练",
    openPlan: "打开计划",
    openSettings: "打开设置",

    // 快捷键提示
    shortcutSend: "发送 (Ctrl+Enter)",
    shortcutNewline: "换行 (Ctrl+Shift+Enter)",
    shortcutSlash: "斜杠命令 (/)",
    shortcutClear: "清空 (Ctrl+L)",

    // 错误提示
    reviewNeedsFile: "复习需要打开文件或选区",
    reviewFileDisabled: "当前文件不可用于复习",
    selectionMissing: "没有选区",
    selectionDisabled: "选区功能已禁用",
    relatedMissing: "没有相关文件",

    // 训练相关
    training: "训练",
    flashcards: "闪卡",
    practice: "练习",
    review: "复习",
    startTraining: "开始训练",
    nextCard: "下一张",
    previousCard: "上一张",
    showAnswer: "显示答案",
    submitAnswer: "提交答案",
    skipCard: "跳过",
    markAgain: "再来一次",
    markHard: "困难",
    markGood: "良好",
    markEasy: "简单",
    dueToday: "今日待复习",
    cardsToReview: "张卡片待复习",
    learningPath: "学习路径",
    masteryLevel: "掌握程度",
    streak: "连续天数",

    // 训练反馈与激励
    streakMessageBeginning: "训练已开始",
    streakMessageBuilding: "坚持训练，习惯正在养成",
    streakMessageStrong: "训练节奏已建立",
    streakMessageExcellent: "你的坚持正在产生效果",
    streakMessageExpert: "训练节奏稳定",
    reviewReminderFew: "{n} 张卡片等待复习",
    reviewReminderSome: "{n} 张卡片需要复习",
    reviewReminderMany: "复习队列较长",
    timeGreetingMorning: "上午好，专注训练",
    timeGreetingAfternoon: "下午好，保持节奏",
    timeGreetingEvening: "晚间训练黄金时间",
    timeGreetingNight: "夜深了，注意休息",
    masteryMilestone10: "10+ 概念已掌握",
    masteryMilestone50: "50+ 概念已掌握",
    practiceEncouragement: "练习已记录",
    growthMindset: "每个错误都是学习机会",
    winCelebration: "已完成",
    practiceReady: "准备就绪",
    progressTip: "持续投入会带来质的飞跃",
    focusTime: "专注时间",
    conceptProgress: "技能成长",
    learningStreak: "专注投入",
    sessionSummary: "本次总结",
    reviewReminderNone: "暂无待复习卡片",
    masteryProgress: "掌握进度",
    practiceTimeInvested: "已投入专注时间",
    cardsMastered: "已掌握概念",
    signalsWaiting: "等待提升训练的信号",
    totalReviews: "总复习次数",
    accuracy: "正确率",

    // 人性化引导
    firstTimeWelcome: "开始训练",
    firstTimeSetupHint: "先配置大模型 API",
    quickStartGuide: "3 分钟快速上手指南",
    providerConnected: "模型连接成功",
    providerDisconnected: "模型未连接",
    modelReady: "模型已就绪",
    apiKeyStillMissing: "还需要 API key 才能开始",
    progressToGoal: "距离目标还有",
    dailyGoalProgress: "今日目标进度",
    keepGoingMessage: "进度已更新",
    almostThereMessage: "接近完成",
    greatJobMessage: "练习完成",
    newRecordMessage: "新纪录",
    coachLearningGoal: "学习目标",
    coachAssessingLevel: "正在评估你的水平",
    coachGeneratingPlan: "正在生成学习计划",
    coachAdjustingPlan: "正在调整计划",

    // 强化学习相关
    reinforcementLearning: "强化学习",
    qLearning: "Q学习",
    dqn: "深度Q网络",
    policyGradient: "策略梯度",
    actorCritic: "演员评论家",
    ddpg: "深度确定性策略梯度",
    ppo: "近端策略优化",
    mcts: "蒙特卡洛树搜索",
    algorithm: "算法",
    state: "状态",
    action: "动作",
    reward: "奖励",
    policy: "策略",
    valueFunction: "价值函数",
    qTable: "Q表",
    epsilon: "探索率",
    discountFactor: "折扣因子",
    learningRate: "学习率",
    exploration: "探索",
    exploitation: "利用",
    bellmanEquation: "贝尔曼方程",
    temporalDifference: "时序差分",
    monteCarlo: "蒙特卡洛",
    onPolicy: "在线策略",
    offPolicy: "离线策略",
    experienceReplay: "经验回放",
    targetNetwork: "目标网络",
    policyLoss: "策略损失",
    valueLoss: "价值损失",
    entropyBonus: "熵奖励",
    clipping: "裁剪",
    gae: "广义优势估计",
    advantage: "优势函数",
    rollout: "Rollout",
    backpropagation: "反向传播",
    gradient: "梯度",
    optimizer: "优化器",
    adam: "Adam",
    sgd: "随机梯度下降",
    batchSize: "批量大小",
    episode: "回合",
    step: "步",
    horizon: "视野",
    environment: "环境",
    agent: "智能体",
    observation: "观测",
    episodeEnd: "回合结束",
    cumulativeReward: "累计奖励",
    convergence: "收敛",
    divergence: "发散",
    trainingCurve: "训练曲线",
    evaluationMetric: "评估指标",
    hyperparameter: "超参数",
    architecture: "架构",
    networkLayer: "网络层",
    inputLayer: "输入层",
    outputLayer: "输出层",
    hiddenLayer: "隐藏层",
    activation: "激活函数",
    relu: "ReLU",
    sigmoid: "Sigmoid",
    softmax: "Softmax",
    lossFunction: "损失函数",
    crossEntropy: "交叉熵",
    mse: "均方误差",
    regularization: "正则化",
    dropout: "Dropout",
    batchNorm: "批归一化",
    earlyStopping: "早停",
    checkpoint: "检查点",
    saveModel: "保存模型",
    loadModel: "加载模型",
    export: "导出",
    import: "导入",

    // 会话相关
    newConversation: "新对话",
    continueConversation: "继续对话",
    deleteConversation: "删除对话",
    renameConversation: "重命名对话",
    searchConversations: "搜索对话",
    noConversations: "暂无对话",
    typing: "正在输入…",
    coachThinking: "教练思考中…",
    coachTyping: "教练正在输入…",
    regenerate: "重新生成",
    copyMessage: "复制消息",
    editMessage: "编辑消息",
    deleteMessage: "删除消息",
    messageCopied: "消息已复制",
    errorOccurred: "出了点问题",
    tryAgain: "重试",
    cancel: "取消",
    confirm: "确认",
    save: "保存",
    close: "关闭",
    back: "返回",
    next: "下一步",
    loading: "加载中…",
    empty: "暂无内容",
    noResults: "没有结果",
    searchResults: "搜索结果",
    filter: "筛选",
    sort: "排序",
    refresh: "刷新",
    timeout: "等得有点久，请再试一次",
    networkError: "没能连上服务，请检查网络后再试",
    unknownError: "暂时没能完成，请再试一次",

    // 证据相关
    evidenceOutcomePass: "通过",
    evidenceOutcomeFail: "失败",
    evidenceOutcomePartial: "部分通过",
    evidenceOutcomeInsight: "有洞见",
    evidenceOutcomeObservation: "有观察",

    // 教练动作状态
    coachActionIdle: "空闲",
    coachActionCheckingResources: "检查资料",
    coachActionSearchingResources: "搜索资料",
    coachActionAligningPlan: "对齐计划",
    coachActionPlanAlignment: "计划对齐",
    coachActionSchedulingTraining: "安排训练",
    coachActionGeneratingCard: "生成训练卡",
    coachActionCardGeneration: "训练卡生成",
    coachActionEvaluatingResult: "评估结果",
    coachActionEvaluation: "结果评估",
    coachActionReviewingEvidence: "审核证据",
    coachActionResourceUpload: "上传资料",
    coachActionWorkspaceClassification: "工作区分类",
    coachActionDoneIdle: "完成 - 空闲",
    coachActionDoneCheckingResources: "完成 - 检查资料",
    coachActionDoneSearchingResources: "完成 - 搜索资料",
    coachActionDoneAligningPlan: "完成 - 对齐计划",
    coachActionDonePlanAlignment: "完成 - 计划对齐",
    coachActionDoneSchedulingTraining: "完成 - 安排训练",
    coachActionDoneGeneratingCard: "完成 - 生成训练卡",
    coachActionDoneCardGeneration: "完成 - 训练卡生成",
    coachActionDoneEvaluatingResult: "完成 - 评估结果",
    coachActionDoneEvaluation: "完成 - 结果评估",
    coachActionDoneReviewingEvidence: "完成 - 审核证据",
    coachActionDoneResourceUpload: "完成 - 上传资料",
    coachActionDoneWorkspaceClassification: "完成 - 工作区分类",

    // 掌握度阶段
    masteryUnderstood: "已理解",
    masteryRecalled: "能回忆",
    masteryPracticed: "已练过",
    masteryApplied: "已落地",
    masteryTransferable: "可迁移",
    masteryNotEstablished: "待建立",

    // 学习旅程
    learningJourney: "学习旅程",
    learningJourneyProgress: "学习进度",
    currentSuggestion: "当前建议",
    cardsCompleted: "张卡片完成",
    conceptsMastered: "概念已掌握",
    currentCard: "当前卡片",
    practiceCard: "实战卡",
    flashCard: "闪记卡",
    waitingForRouting: "等待训练路由确认当前卡片",
    resourceRiskPaused: "这张训练卡因资料风险暂停",
    refreshResourceFirst: "先去资料页刷新，再继续这张训练卡",

    // 资源视图
    addFiles: "添加文件",
    addFolder: "添加文件夹",
    addUrl: "添加网址",
    resourcesEmpty: "资料库为空，导入文件或链接",
    resourcesMenu: "资料",
    resourcesSummary: "资料概要",
    resourcesSandbox: "沙箱",
    resourcesSandboxRoot: "沙箱根目录",
    resourcesSandboxRefresh: "刷新",
    resourcesSandboxNewFile: "新建文件",
    resourcesSandboxNewFolder: "新建文件夹",
    resourcesSandboxRename: "重命名",
    resourcesSandboxTrash: "移到 Trash",
    resourcesSandboxEmpty: "沙箱里还没有文件。",
    resourcesSandboxBoundaryRefresh: "边界",
    resourcesSandboxOpenRoot: "打开根目录",
    resourcesSandboxChooseRoot: "固定路径",
    resourcesSandboxResetRoot: "恢复默认",
    resourcesSandboxActionBase: "目标基准",
    resourcesSandboxCreateIn: "创建位置",
    resourcesSandboxTargetCurrent: "当前目录",
    resourcesSandboxTargetRoot: "沙箱根目录",
    resourcesSandboxParent: "上一级",
    resourcesSandboxResolvedPath: "结果路径",
    resourcesSandboxSourcePath: "来源路径",
    resourcesSandboxWorkspaceRoot: "Workspace 根目录",
    resourcesSandboxSourceLabel: "来源",
    resourcesSandboxLedger: "Ledger / checkpoints",
    resourcesSandboxTrashRoot: "Trash",
    resourcesSandboxMountedSources: "挂载来源",
    resourcesSandboxNextSafeMove: "下一步",
    resourcesSandboxFilePlaceholder: "输入文件路径，如 packs/remote/ssh/notes.md",
    resourcesSandboxFolderPlaceholder: "输入嵌套目录，如 packs/remote/ssh",
    resourcesSandboxFileHint: "在沙箱根目录内创建，支持多级路径。",
    resourcesSandboxFolderHint: "相对沙箱根目录创建，支持多级目录。",
    resourcesSandboxRenamePlaceholder: "输入新的相对路径，如 packs/debug/minimal-loop.md",
    resourcesSandboxRenameHint: "重命名也支持在沙箱内移动路径。",
    resourcesSandboxManagedLayout: "Trainer 布局",

    // 分析状态
    analysisReady: "分析就绪",
    analysisStatus: "分析状态",
    analysisProgress: "分析进度",
    analysisFindings: "分析发现",
    analysisDecision: "分析决定",
    analysisNextStep: "分析下一步",
    analysisAction: "分析动作",
    analysisThreads: "分析线程",
    advanceAnalysis: "推进分析",

    // 计划治理
    planLive: "进行中",
    planFrozen: "已冻结",
    planFreeze: "冻结计划",
    planSummary: "计划概要",
    planCurrentStage: "当前阶段",
    planNextAction: "下一步",
    planAdjust: "调整计划",
    planWhy: "原因",
    planCadence: "节奏",
    approve: "采纳",
    reject: "拒绝",

    // 阶段状态
    stageActive: "进行中",
    stageDone: "已完成",
    stageQueued: "待处理",

    // 上下文
    contextMode: "上下文模式",
    contextAutoNote: "自动备注",
    useFullContext: "使用完整上下文",
    viewContextWorking: "正在处理",
    viewContextBlocker: "当前阻塞",
    viewContextLatest: "最近状态",
    viewContextCoach: "教练上下文",

    // 文件与诊断
    enableFile: "启用文件",
    enableSelection: "启用选区",
    enableRelated: "启用相关文件",
    relatedDisabled: "相关文件已禁用",
    diagnosticsMissing: "缺少诊断",
    maxFilesHint: "文件数量已达上限",

    // 视图与历史
    trainingView: "训练视图",
    summaryEmpty: "暂无概要",
    history: "历史记录",
    composerAccessibility: "输入框",
    reviewNotFull: "复习未完成",
    evidenceSourceCardResult: "训练卡结果",
    evidenceSourceCoachingObservation: "教练观察",
    evidenceSourceEvaluation: "评估结果",
    evidenceSourceLearningSignal: "学习信号",
    evidenceSourceResourceImport: "资料导入",
    evidenceSourceReviewQueue: "复习队列",
    greetingMorning: "早上好",
    greetingAfternoon: "下午好",
    greetingEvening: "晚上好",
    greetingNight: "夜深了",
    nextActionHintUnderstood: "用自己的话确认这个想法。",
    nextActionHintRecalled: "不看笔记回忆这个想法。",
    nextActionHintPracticed: "在一个小任务中使用它。",
    nextActionHintApplied: "在当前项目中应用它。",
    nextActionHintTransferable: "迁移到新场景并解释取舍。",
    trainingOpenCurrentCard: "继续：打开当前训练卡",
    trainingReturnToCoach: "把结果带回教练",
    trainingAnswerNow: "现在回答",
    trainingRecordStep: "记录这一步",
    trainingStartStep: "开始这一步",
    trainingEmptyTitle: "还没有训练卡",
    trainingEmptyDescription: "开始训练，从当前焦点创建一个小而可验证的任务。",
  },

  // ==========================================================================
  // English (美国)
  // ==========================================================================
  "en-US": {
    settingsStatusRegionLabel: "Current status",
    settingsStatusConnected: "Connected",
    settingsStatusNotConnected: "Not connected",
    settingsStatusLanguage: "Language",
    settingsStatusMemory: "Memory",
    settingsStatusNoApiKey: "Missing API key",
    settingsStatusNeedsTest: "Connection untested",
    settingsStatusTrust: "Workspace not trusted",
    settingsStatusUnsaved: "Unsaved changes",
    settingsSectionConnection: "Connection",
    settingsTeachingPrefs: "Teaching preferences",
    settingsAnswerStyle: "Answer style",
    answerStyleSimple: "Simple",
    answerStyleBalanced: "Balanced",
    answerStyleDeep: "Deep",
    answerStyleCustom: "Custom",
    settingsAnswerStyleHint: "Presets set context depth and attachments. Save to apply.",
    settingsAdvancedContext: "Advanced context",
    settingsMemoryPrivacy: "Memory & privacy",
    settingsAdvanced: "Advanced",
    settingsMemorySharing: "Cross-project memory",
    settingsMemorySharingDetail: "Projects stay isolated by default. Only explicitly authorized preferences and mastery signals are read.",
    settingsMemorySharingNone: "No other project is authorized.",
    settingsMemorySharingActive: "authorized sources",
    settingsMemorySharingUnavailable: "Add the current project to Trainer before authorizing cross-project memory.",
    settingsMemoryShareGrant: "Allow a project",
    settingsMemoryShareRevoke: "Revoke",
    settingsMemorySharePreferences: "Preferences",
    settingsMemoryShareMastery: "Mastery signals",
    coach: "Coach",
    coachArtifactFullDetails: "Full details",
    trainer: "Trainer",
    you: "You",
    plan: "Plan",
    settings: "Settings",
    chat: "Chat",
    workspace: "Workspace",
    viewNavigation: "Trainer views",
    currentFocus: "Current Focus",
    currentTask: "Current Task",
    latestReview: "Latest Review",
    backgroundAnalysis: "Background Analysis",
    backgroundCoachWork: "Coach Preparation",
    firstLookBadge: "Project overview",
    firstLookProjectType: "Project type",
    firstLookFolderRole: "Folder role",
    firstLookWhyGuess: "Why this guess",
    firstLookEntryPoints: "Entry points",
    firstLookDirectoryAnchors: "Key locations",
    firstLookCoreModules: "Core modules / materials",
    firstLookRiskZones: "Risk zones",
    firstLookOpportunities: "Training opportunities",
    firstLookUnknowns: "Unknowns",
    firstLookNextStep: "Next step",
    workspaceAdmissionRootMissing: "Workspace root is not set",
    workspaceAdmissionRootMissingDetail: "Choose where Trainer keeps learning records, then decide how to handle this project.",
    workspaceAdmissionGoalSaved: "Your goal is still in the box. Choose where to keep learning records, then come back and send it.",
    workspaceAdmissionProjectFound: "Project found",
    workspaceAdmissionProjectFoundDetail: "Choose one: add it to Trainer, browse it, or ignore it.",
    workspaceAdmissionManaged: "Managed by Trainer",
    workspaceAdmissionManagedDetail: "This project's chat, plan, and learning records are kept separately.",
    workspaceAdmissionBrowse: "Browse only",
    workspaceAdmissionBrowseDetail: "You can inspect this project, but coaching and saved learning records stay off.",
    workspaceAdmissionIgnored: "Ignored",
    workspaceAdmissionIgnoredDetail: "Trainer will not read or manage this project. You can add it later.",
    workspaceAdmissionProjectName: "Project",
    workspaceAdmissionProjectPath: "Path",
    workspaceAdmissionSelectRoot: "Choose workspace root",
    workspaceAdmissionSelectProject: "Choose project folder",
    workspaceAdmissionAdd: "Add to Trainer",
    workspaceAdmissionBrowseAction: "Browse only",
    workspaceAdmissionIgnore: "Ignore project",
    workspaceAdmissionDelete: "Delete project",
    workspaceRootControl: "Trainer workspace",
    workspaceRootReady: "Learning records are being stored in this workspace.",
    workspaceRootPath: "Root",
    workspaceRootMigrate: "Migrate workspace",
    workspaceRootMigrateDetail: "Copy to a new empty folder and continue from the new root.",
    workspaceRootRecovery: "Backup and restore",
    workspaceRootBackup: "Back up workspace",
    workspaceRootBackupDetail: "Create a recoverable copy without changing the active root.",
    workspaceRootRestore: "Restore backup",
    workspaceRootRestoreDetail: "Restore into a new empty folder and make it the active root.",
    workspaceRootChange: "Change root",
    workspaceRootChangeDetail: "Choose another root without copying the current data.",
    coachState: "Coach State",
    coachSignal: "Learning Signal",
    reviewQueue: "Review Queue",
    reviewMemory: "Memory & Rhythm",
    reviewRhythm: "Review Rhythm",
    nextReview: "Next Review",
    teachingObservations: "Teaching Observations",
    coachSummaryDoing: "Doing",
    goals: "Goals",
    constraints: "Constraints",
    acceptance: "Acceptance Criteria",
    nextMove: "Next Move",
    recentWins: "Recent Wins",
    weakSpots: "Weak Spots",
    planStages: "Stages",
    trainingWhyNow: "Why now",
    trainingDeliverable: "Deliverable",
    planStageMaterialsTitle: "Study materials",
    planStageMaterialsGenerate: "Generate materials",
    planStageMaterialsGenerating: "Generating…",
    planStageMaterialsView: "View",
    planStageMaterialsHide: "Hide",
    planStageMaterialsEmpty: "No study materials for this stage yet.",
    planStageCompletionLabel: "Stage completion",
    planStageMaterialsBadgeTitle: "Materials generated",
    planDashboardTabPlan: "Plan",
    planDashboardTabProgress: "Progress",
    planDashboardStagesTitle: "Stage completion",
    planDashboardMasteryTitle: "Dependency mastery",
    planDashboardReviewTitle: "FSRS review retention",
    planDashboardMaterialsTitle: "Material usage",
    planDashboardMaterialsStages: "Stages covered",
    planDashboardMasteryEmpty: "No mastery data yet. It builds up as you finish training cards.",
    planDashboardReviewDue: "Due",
    planDashboardReviewDone: "Done",
    planDashboardEmptyTitle: "Generate a plan first",
    trainingHandoffMismatchHint: "This card does not match the current training handoff. Switch to the card that owns the handoff.",
    trainingSwitchToCard: "Switch to that card",
    trainingCardDetailsApiHints: "API hints",
    trainingCardDetailsSelfCheck: "Self-check",
    trainingCardDetailsRubric: "Grading rubric",
    trainingCardDetailsAcceptance: "Acceptance criteria",
    language: "Language",
    answerMode: "Feedback Mode",
    auto: "Auto",
    teachingStyle: "Teaching Style",
    teachingGuided: "Guided",
    teachingConceptFirst: "Concept First",
    teachingHandsOn: "Hands-On",
    teachingChallenging: "Challenging",
    contextDetail: "Context Detail",
    coachFirst: "Guided",
    balanced: "Balanced",
    direct: "Direct",
    detailFocused: "Focused",
    detailBalanced: "Standard",
    detailFull: "Complete",
    attachments: "Attachments",
    currentContext: "Current file",
    allContext: "All Context",
    noContext: "No Context",
    file: "File",
    selection: "Selection",
    diagnostics: "Diagnostics",
    relatedFiles: "Related Files",
    follow: "Live Follow",
    theme: "Theme",
    system: "System",
    light: "Light",
    dark: "Dark",
    provider: "Provider",
    protocol: "Protocol",
    baseUrl: "Base URL",
    chatModel: "Model",
    apiKey: "API Key",
    apiKeySaved: "Saved",
    apiKeyMissing: "Not configured",
    saveProvider: "Save Config",
    testProvider: "Test Connection",
    clearProvider: "Clear Config",
    openConfigFile: "Open Config",
    configured: "Configured",
    notConfigured: "Not configured",
    refreshProviderProfiles: "Refresh Profiles",
    refreshWorkspaceAuthority: "Refresh Workspace",
    createProfileFromTemplate: "Create from Template",
    settingsSetupSection: "Model connection",
    settingsSetupTitleReady: "Trainer is ready to start",
    settingsSetupTitleBlocked: "Trainer can't start without an API key",
    settingsSetupDetailReady: "Model connection is ready. You can start chatting, planning, and learning right away.",
    settingsSetupDetailBlocked: "Save the provider, base URL, model, and API key. Only then can Trainer start working with you.",
    settingsSetupAction: "Complete setup",
    settingsInterfaceSection: "How Trainer guides you",
    settingsCoachSection: "Default context for each turn",
    settingsModelSection: "Connect model",
    settingsFollowCurrentFile: "Live follow",
    settingsContextMode: "Context level",
    settingsCurrentFile: "Current file",
    settingsConnectionDetails: "Connection details",
    settingsLongTermMemory: "Long-term memory",
    settingsMemoryScope: "Memory scope",
    settingsMemoryScopeProject: "Current project",
    settingsMemoryScopePersonal: "Personal",
    settingsMemoryScopeSession: "Current session",
    settingsRememberDecisions: "Architecture decisions",
    settingsRememberPatterns: "Common patterns",
    settingsRememberResources: "References",
    settingsWorkingSet: "Working set",
    settingsWorkingSetFocused: "Current task only",
    settingsWorkingSetBalanced: "Nearby files",
    settingsWorkingSetBroad: "Wider references",
    settingsMemoryPreview: "Priority retention",
    settingsMemoryPreviewEmpty: "Currently follows file, selection, and diagnostics.",
    settingsTeachingSignal: "Learning signal",
    settingsConfigFileNote: "Need more control? You can fine-tune it in the config file.",
    settingsContextSection: "Attached context",
    settingsMemoryRuntime: "Background operation",
    settingsMemoryRuntimeDetail: "Updates as you send.",
    settingsAdvancedSection: "More defaults",
    settingsAdvancedIntro: "Memory, review, theme.",
    settingsReviewRhythmPace: "Reminder intensity",
    settingsReviewRhythmReminder: "Reminder strategy",
    settingsReviewStrategy: "Review strategy",
    settingsSystemActions: "Tidy current state",
    settingsRefreshMemory: "Refresh current memory",
    settingsResetDefaults: "Restore recommended defaults",
    settingsModelTools: "Connection tools",
    settingsDefaultsHint: "Define how Trainer talks and guides you. Most conversations will follow this rhythm.",
    settingsContextHint: "Only sets the default attachments per turn.",
    settingsModelHint: "Only handles model connection. The real coaching comes from plan, memory, and continuity.",
    settingsThinking: "Native thinking",
    settingsThinkingDetail: "Only show native controls confirmed for the current model.",
    settingsThinkingOff: "Off",
    settingsThinkingAuto: "Auto",
    settingsThinkingOn: "On",
    settingsThinkingAdvanced: "Advanced controls",
    settingsThinkingEffort: "Thinking effort",
    settingsThinkingBudget: "Thinking budget",
    settingsThinkingUnsupported: "No confirmed native thinking controls for this model.",
    settingsThinkingOpenAiEffort: "OpenAI effort",
    settingsThinkingAnthropicBudget: "Anthropic budget",
    settingsThinkingGeminiConfig: "Gemini thinkingConfig",
    settingsThinkingMiniMaxDisabled: "MiniMax thinking (disabled)",
    settingsAvailableModels: "Available models",
    settingsDetectedModel: "Detected model",
    settingsModelFetchLoading: "Fetching model list…",
    settingsModelFetchEmpty: "Model list will load automatically after saving API key.",
    settingsRefreshModels: "Refresh model list",
    settingsModelCache: "Model list status",
    settingsModelCacheSource: "Source",
    settingsModelCacheFetchedAt: "Fetched at",
    settingsModelCacheExpiresAt: "Expires at",
    settingsModelCacheStatus: "Status",
    settingsModelCacheError: "Error reason",
    settingsModelCacheSourceLive: "Live fetch",
    settingsModelCacheSourceCache: "Cached result",
    settingsModelCacheStatusFresh: "Fresh",
    settingsModelCacheStatusExpired: "Expired",
    settingsModelCacheStatusUnknown: "Unknown",
    settingsModelCacheStatusLoading: "Refreshing",
    settingsModelCacheStatusError: "Failed",
    settingsRuntimeSection: "Current coach runtime",
    settingsRuntimeHint: "Used by the next message.",
    settingsMemoryStrategy: "Memory strategy",
    settingsMemoryStrategyHint: "Memory location.",
    settingsReviewStrategyHint: "Review frequency and reminders.",
    settingsContextCurrentFileHint: "Attach current file.",
    settingsContextSelectionHint: "Attach selection.",
    settingsContextDiagnosticsHint: "Attach diagnostics.",
    settingsContextRelatedFilesHint: "Attach related files as needed.",
    settingsMemoryScopeRuntimeProject: "Current project plan, thread, resources.",
    settingsMemoryScopeRuntimePersonal: "Cross-project preferences and traces.",
    settingsMemoryScopeRuntimeSession: "Current session only.",
    settingsMemoryScopeProjectHint: "Keep the thread and judgment inside the current project.",
    settingsMemoryScopePersonalHint: "Carry reusable habits and judgment into other projects.",
    settingsMemoryScopeSessionHint: "Keep the memory local to the current conversation only.",
    settingsWorkingSetFocusedHint: "Stay on the smallest verifiable slice and the nearest files.",
    settingsWorkingSetBalancedHint: "Balance the current slice with nearby context for most coding turns.",
    settingsWorkingSetBroadHint: "Allow broader related context when verification needs it.",
    settingsReviewCadenceLightHint: "Interrupt less often while keeping the key review points.",
    settingsReviewCadenceSteadyHint: "Follow a normal training rhythm.",
    settingsReviewCadenceActiveHint: "Revisit more frequently for short sprints.",
    settingsReviewReminderDueHint: "Remind mainly when the review is actually due.",
    settingsReviewReminderAheadHint: "Send a heads-up before the review is due.",
    settingsReviewReminderDigestHint: "Bundle nearby reviews into a single digest.",
    settingsSavedState: "Saved",
    settingsUnsavedState: "Unsaved changes",
    settingsEmptyState: "Not written to workspace",
    settingsEffectiveNow: "Effective now",
    settingsSavedInWorkspace: "Saved in workspace",
    settingsEditingDraft: "Editing",
    settingsCurrentWorkspace: "Current workspace",
    settingsLocalThemeNote: "Theme only affects what you see now, not written to workspace.",
    settingsWorkspaceSaveNote: "Saving coach defaults also saves workspace-level controls that apply automatically.",
    settingsProviderRuntimeNote: "Test connection uses the provider config that's actually active in the workspace right now.",
    settingsLatestAction: "Recent action",
    settingsLastTest: "Last test",
    settingsLastTestNever: "Never tested",
    settingsLastTestPassed: "Passed",
    settingsLastTestFailed: "Failed",
    settingsLastTestNeedsSetup: "Needs setup",
    settingsFocused: "Focused",
    settingsBalancedContext: "Standard",
    settingsFullContext: "Extended",
    settingsSaveCoachDefaults: "Save coach defaults",
    globalPlanLabel: "Global plan",
    globalPlanRelationship: "Global plan -> Current project plan",
    globalPlanNotCreated: "Not created",
    globalPlanNotLinked: "Current project is not linked",
    globalPlanLinked: "Linked to current project",
    globalPlanCreate: "Create global plan",
    globalPlanLinkCurrentProject: "Link current project plan",
    globalPlanLinkUnavailable: "Generate a current project plan first",
    globalPlanFrozen: "Global plan is frozen",
    evidenceConfidence: "Confidence",
    evidenceGovernance: "Evidence governance",
    evidenceFilterAll: "All",
    evidenceFilterDeferred: "Deferred",
    evidenceFilterAdopted: "Adopted",
    evidenceFilterRejected: "Rejected",
    evidenceAdopt: "Adopt",
    evidenceDefer: "Defer",
    evidenceTargetPrefix: "Target",
    evidenceNoMatches: "No evidence matches this filter.",
    capabilityChat: "Chat",
    capabilityResponses: "Responses API",
    capabilityTools: "Tool Calls",
    capabilityStreaming: "Streaming",
    capabilityStructuredOutput: "Structured Output",
    capabilityVision: "Vision",
    capabilityEmbeddings: "Embeddings",
    capabilityJsonSchema: "JSON Schema",
    capabilitySupported: "Supported",
    capabilityNotSupported: "Not supported",
    feedbackTooHard: "Too hard",
    feedbackTooSimple: "Too simple",
    feedbackMisunderstood: "I didn't understand",
    feedbackResourceIncorrect: "Resource is wrong",
    feedbackPlanMismatch: "Plan doesn't fit",
    feedbackCardUnrealistic: "Card isn't realistic",
    feedbackDisclosureSummary: "Something off? Tell Trainer",
    feedbackDisclosureDetail: "This records teaching feedback; it does not change the formal plan.",
    feedbackLearningLabel: "Learning feedback",
    feedbackRecording: "Recording…",
    feedbackRecorded: "Recorded. The next step will adapt; plan changes still require confirmation.",
    feedbackDismiss: "Dismiss",
    settingsIntro: "Only the most common coach settings here.",
    settingsGeneral: "Interface & Response",
    settingsCoachBehavior: "Coach Behavior",
    settingsModelAccess: "Model & Connection",
    settingsWorkspaceNote: "Frontend only shows model connection and high-frequency preferences.",
    settingsProviderHint: "Focus on model connection. Deeper overrides go to config file.",
    settingsCoachHint: "These options control how much context the coach reads.",
    send: "Send",
    streaming: "Coach thinking…",
    configureProviderFirst: "Trainer isn't ready yet. Please save provider and API key in settings first.",
    configureProviderFirstPlan: "Trainer can't generate plans yet. Please complete model connection in settings.",
    providerRequiredHint: "No available provider or API key. Trainer can't work yet.",
    composerPlaceholder: "Ask the coach",
    composerPlaceholderPlan: "Write the next step",
    slashCommands: "Slash Commands",
    runLocalCommand: "Will execute local command",
    switchView: "Switch View",
    setLanguage: "Change Language",
    setAnswerMode: "Adjust Feedback",
    setContextDetail: "Adjust Context",
    setAttachments: "Adjust Attachments",
    setLiveFollow: "Toggle Live Follow",
    opened: "Opened",
    updated: "Updated",
    on: "On",
    off: "Off",
    connected: "Connected",
    starting: "Connecting",
    offline: "Offline",
    pass: "Pass",
    fail: "Fail",
    warn: "Warn",
    pending: "Pending",
    suggestedActions: "Suggested Actions",
    generatePlan: "Generate Plan",
    nextTask: "Next Task",
    runReview: "Start Review",
    openCoach: "Open Coach",
    viewContextWorking: "Working",
    viewContextBlocker: "Blocker",
    viewContextLatest: "Latest",
    viewContextCoach: "Coach context",
    openPlan: "Open Plan",
    openSettings: "Open Settings",
    shortcutSend: "Send (Ctrl+Enter)",
    shortcutNewline: "Newline (Ctrl+Shift+Enter)",
    shortcutSlash: "Slash (/)",
    shortcutClear: "Clear (Ctrl+L)",
    reviewNeedsFile: "Review requires open file or selection",
    reviewFileDisabled: "Current file not available for review",
    selectionMissing: "No selection",
    selectionDisabled: "Selection disabled",
    relatedMissing: "No related files",
    training: "Training",
    flashcards: "Flashcards",
    practice: "Practice",
    review: "Review",
    startTraining: "Start Training",
    nextCard: "Next Card",
    previousCard: "Previous Card",
    showAnswer: "Show Answer",
    submitAnswer: "Submit Answer",
    skipCard: "Skip",
    markAgain: "Again",
    markHard: "Hard",
    markGood: "Good",
    markEasy: "Easy",
    dueToday: "Due Today",
    cardsToReview: "cards to review",
    learningPath: "Learning Path",
    masteryLevel: "Mastery",
    streak: "Streak",
    totalReviews: "Total Reviews",
    accuracy: "Accuracy",

    // Humanized onboarding
    firstTimeWelcome: "Start training",
    firstTimeSetupHint: "Configure a model API first",
    quickStartGuide: "3-Minute Quick Start Guide",
    providerConnected: "Model connected",
    providerDisconnected: "Model not connected",
    modelReady: "Model ready",
    apiKeyStillMissing: "API key still needed to start",
    progressToGoal: "Progress to goal",
    dailyGoalProgress: "Daily goal progress",
    keepGoingMessage: "Progress is building",
    almostThereMessage: "Almost there",
    greatJobMessage: "Practice completed",
    newRecordMessage: "New personal best",
    coachLearningGoal: "Learning Goal",
    coachAssessingLevel: "Assessing your level",
    coachGeneratingPlan: "Generating learning plan",
    coachAdjustingPlan: "Adjusting plan",

    reinforcementLearning: "Reinforcement Learning",
    qLearning: "Q-Learning",
    dqn: "Deep Q-Network",
    policyGradient: "Policy Gradient",
    actorCritic: "Actor-Critic",
    ddpg: "DDPG",
    ppo: "PPO",
    mcts: "MCTS",
    algorithm: "Algorithm",
    state: "State",
    action: "Action",
    reward: "Reward",
    policy: "Policy",
    valueFunction: "Value Function",
    qTable: "Q-Table",
    epsilon: "Epsilon",
    discountFactor: "Discount Factor",
    learningRate: "Learning Rate",
    exploration: "Exploration",
    exploitation: "Exploitation",
    bellmanEquation: "Bellman Equation",
    temporalDifference: "Temporal Difference",
    monteCarlo: "Monte Carlo",
    onPolicy: "On-Policy",
    offPolicy: "Off-Policy",
    experienceReplay: "Experience Replay",
    targetNetwork: "Target Network",
    policyLoss: "Policy Loss",
    valueLoss: "Value Loss",
    entropyBonus: "Entropy Bonus",
    clipping: "Clipping",
    gae: "GAE",
    advantage: "Advantage",
    rollout: "Rollout",
    backpropagation: "Backpropagation",
    gradient: "Gradient",
    optimizer: "Optimizer",
    adam: "Adam",
    sgd: "SGD",
    batchSize: "Batch Size",
    episode: "Episode",
    step: "Step",
    horizon: "Horizon",
    environment: "Environment",
    agent: "Agent",
    observation: "Observation",
    episodeEnd: "Episode End",
    cumulativeReward: "Cumulative Reward",
    convergence: "Convergence",
    divergence: "Divergence",
    trainingCurve: "Training Curve",
    evaluationMetric: "Evaluation Metric",
    hyperparameter: "Hyperparameter",
    architecture: "Architecture",
    networkLayer: "Network Layer",
    inputLayer: "Input Layer",
    outputLayer: "Output Layer",
    hiddenLayer: "Hidden Layer",
    activation: "Activation",
    relu: "ReLU",
    sigmoid: "Sigmoid",
    softmax: "Softmax",
    lossFunction: "Loss Function",
    crossEntropy: "Cross Entropy",
    mse: "MSE",
    regularization: "Regularization",
    dropout: "Dropout",
    batchNorm: "Batch Norm",
    earlyStopping: "Early Stopping",
    checkpoint: "Checkpoint",
    saveModel: "Save Model",
    loadModel: "Load Model",
    export: "Export",
    import: "Import",
    newConversation: "New Chat",
    continueConversation: "Continue",
    deleteConversation: "Delete",
    renameConversation: "Rename",
    searchConversations: "Search",
    noConversations: "No conversations",
    typing: "Typing…",
    coachThinking: "Coach thinking…",
    coachTyping: "Coach typing…",
    regenerate: "Regenerate",
    copyMessage: "Copy",
    editMessage: "Edit",
    deleteMessage: "Delete",
    messageCopied: "Copied",
    errorOccurred: "Error occurred",
    tryAgain: "Try Again",
    cancel: "Cancel",
    confirm: "Confirm",
    save: "Save",
    close: "Close",
    back: "Back",
    next: "Next",
    loading: "Loading…",
    empty: "Empty",
    noResults: "No results",
    searchResults: "Search Results",
    filter: "Filter",
    sort: "Sort",
    refresh: "Refresh",
    timeout: "Timeout",
    networkError: "Network error",
    unknownError: "Unknown error",
    evidenceOutcomePass: "Pass",
    evidenceOutcomeFail: "Fail",
    evidenceOutcomePartial: "Partial",
    evidenceOutcomeInsight: "Insight",
    evidenceOutcomeObservation: "Observation",
    evidenceSourceCardResult: "Training card result",
    evidenceSourceEvaluation: "Server evaluation",
    evidenceSourceLearningSignal: "Learning signal",
    evidenceSourceCoachingObservation: "Coach observation",
    evidenceSourceResourceImport: "Resource import",
    evidenceSourceReviewQueue: "Review queue",

    // Human-friendly status
    streakMessageBeginning: "Training started",
    streakMessageBuilding: "Keep training, habits are forming",
    streakMessageStrong: "You've built a training rhythm!",
    streakMessageExcellent: "Your consistency is showing results",
    streakMessageExpert: "Strong training rhythm",
    reviewReminderNone: "No cards due for review",
    greetingMorning: "Good morning",
    greetingAfternoon: "Good afternoon",
    greetingEvening: "Good evening",
    greetingNight: "Good night",
    reviewReminderFew: "{n} card{s} waiting for review",
    reviewReminderSome: "{n} card{s} to review",
    reviewReminderMany: "Review queue is long",
    timeGreetingMorning: "Morning training",
    timeGreetingAfternoon: "Good afternoon, keep the rhythm",
    timeGreetingEvening: "Evening training hour",
    timeGreetingNight: "Late night. Remember to rest",
    masteryMilestone10: "10+ concepts mastered",
    masteryMilestone50: "50+ concepts mastered",
    practiceEncouragement: "Practice recorded",
    growthMindset: "Every mistake is a learning opportunity",
    winCelebration: "Completed",
    practiceReady: "Ready to practice",
    progressTip: "Consistent investment leads to breakthroughs",
    focusTime: "Focus time",
    conceptProgress: "Skill growth",
    learningStreak: "Dedicated investment",
    sessionSummary: "Session summary",
    masteryProgress: "Skill growth",
    practiceTimeInvested: "Focus time invested",
    cardsMastered: "concepts mastered",
    signalsWaiting: "signals waiting to boost your training",

    // Coach action status
    coachActionIdle: "Idle",
    coachActionCheckingResources: "Checking Resources",
    coachActionSearchingResources: "Searching Resources",
    coachActionAligningPlan: "Aligning Plan",
    coachActionPlanAlignment: "Plan Alignment",
    coachActionSchedulingTraining: "Scheduling Training",
    coachActionGeneratingCard: "Generating Card",
    coachActionCardGeneration: "Card Generation",
    coachActionEvaluatingResult: "Evaluating Result",
    coachActionEvaluation: "Evaluation",
    coachActionReviewingEvidence: "Reviewing Evidence",
    coachActionResourceUpload: "Uploading Resource",
    coachActionWorkspaceClassification: "Workspace Classification",
    coachActionDoneIdle: "Done - Idle",
    coachActionDoneCheckingResources: "Done - Checked Resources",
    coachActionDoneSearchingResources: "Done - Searched Resources",
    coachActionDoneAligningPlan: "Done - Aligned Plan",
    coachActionDonePlanAlignment: "Done - Plan Aligned",
    coachActionDoneSchedulingTraining: "Done - Scheduled Training",
    coachActionDoneGeneratingCard: "Done - Generated Card",
    coachActionDoneCardGeneration: "Done - Card Generated",
    coachActionDoneEvaluatingResult: "Done - Evaluated Result",
    coachActionDoneEvaluation: "Done - Evaluated",
    coachActionDoneReviewingEvidence: "Done - Reviewed Evidence",
    coachActionDoneResourceUpload: "Done - Uploaded Resource",
    coachActionDoneWorkspaceClassification: "Done - Classified Workspace",

    // Mastery stages
    masteryUnderstood: "Understood",
    masteryRecalled: "Recalled",
    masteryPracticed: "Practiced",
    masteryApplied: "Applied",
    masteryTransferable: "Transferable",
    masteryNotEstablished: "Not established",

    // Learning journey
    learningJourney: "Learning journey",
    learningJourneyProgress: "Learning progress",
    currentSuggestion: "Current suggestion",
    nextActionHintUnderstood: "Confirm the idea in your own words.",
    nextActionHintRecalled: "Recall the idea without notes.",
    nextActionHintPracticed: "Use it in one small task.",
    nextActionHintApplied: "Apply it in the current project.",
    nextActionHintTransferable: "Transfer it to a new context and explain the tradeoff.",
    cardsCompleted: "cards completed",
    conceptsMastered: "concepts mastered",
    currentCard: "Current card",
    practiceCard: "Practice card",
    flashCard: "Flash card",
    waitingForRouting: "Waiting for training router to confirm the card",
    resourceRiskPaused: "This training card is paused by resource risk",
    refreshResourceFirst: "Refresh the source material before continuing this card",

    // Resource view
    addFiles: "Add files",
    addFolder: "Add folder",
    addUrl: "Add URL",
    resourcesEmpty: "Library is empty, start importing here",
    resourcesMenu: "Resources",
    resourcesSummary: "Resources summary",
    resourcesSandbox: "Sandbox",
    resourcesSandboxRoot: "Sandbox root",
    resourcesSandboxRefresh: "Refresh",
    resourcesSandboxNewFile: "New file",
    resourcesSandboxNewFolder: "New folder",
    resourcesSandboxRename: "Rename",
    resourcesSandboxTrash: "Move to Trash",
    resourcesSandboxEmpty: "Sandbox is still empty.",
    resourcesSandboxBoundaryRefresh: "Boundary",
    resourcesSandboxOpenRoot: "Open root",
    resourcesSandboxChooseRoot: "Choose root",
    resourcesSandboxResetRoot: "Use default",
    resourcesSandboxActionBase: "Target base",
    resourcesSandboxCreateIn: "Create in",
    resourcesSandboxTargetCurrent: "Current folder",
    resourcesSandboxTargetRoot: "Sandbox root",
    resourcesSandboxParent: "Parent",
    resourcesSandboxResolvedPath: "Result path",
    resourcesSandboxSourcePath: "Source path",
    resourcesSandboxWorkspaceRoot: "Workspace root",
    resourcesSandboxSourceLabel: "Source",
    resourcesSandboxLedger: "Ledger / checkpoints",
    resourcesSandboxTrashRoot: "Trash",
    resourcesSandboxMountedSources: "Mounted sources",
    resourcesSandboxNextSafeMove: "Next safe move",
    resourcesSandboxFilePlaceholder: "New file path, for example packs/remote/ssh/notes.md",
    resourcesSandboxFolderPlaceholder: "Nested folder path, for example packs/remote/ssh",
    resourcesSandboxFileHint: "Create inside the sandbox root. Nested paths are supported.",
    resourcesSandboxFolderHint: "Create inside the sandbox root. Nested directories are supported.",
    resourcesSandboxRenamePlaceholder: "New relative path, for example packs/debug/minimal-loop.md",
    resourcesSandboxRenameHint: "Rename can also move the path within the sandbox.",
    resourcesSandboxManagedLayout: "Trainer layout",

    // Analysis status
    analysisReady: "Analysis ready",
    analysisStatus: "Analysis status",
    analysisProgress: "Analysis progress",
    analysisFindings: "Analysis findings",
    analysisDecision: "Analysis decision",
    analysisNextStep: "Analysis next step",
    analysisAction: "Analysis action",
    analysisThreads: "Analysis threads",
    advanceAnalysis: "Advance analysis",

    // Plan governance
    planLive: "Live",
    planFrozen: "Frozen",
    planFreeze: "Freeze plan",
    planSummary: "Plan summary",
    planCurrentStage: "Current stage",
    planNextAction: "Next action",
    planAdjust: "Adjust plan",
    planWhy: "Why",
    planCadence: "Cadence",
    approve: "Approve",
    reject: "Reject",

    // Stage status
    stageActive: "Active",
    stageDone: "Done",
    stageQueued: "Queued",

    // Context
    contextMode: "Context mode",
    contextAutoNote: "Auto note",
    useFullContext: "Use full context",

    // Files & diagnostics
    enableFile: "Enable file",
    enableSelection: "Enable selection",
    enableRelated: "Enable related",
    relatedDisabled: "Related files disabled",
    diagnosticsMissing: "Diagnostics missing",
    maxFilesHint: "File limit reached",

    // Views & history
    trainingView: "Training view",
    trainingOpenCurrentCard: "Continue: Open current card",
    trainingReturnToCoach: "Return result to Coach",
    trainingAnswerNow: "Answer now",
    trainingRecordStep: "Record this step",
    trainingStartStep: "Start this step",
    trainingEmptyTitle: "No training card yet",
    trainingEmptyDescription: "Ask Coach to turn the current thread into one verifiable card, then come back here to do it.",
    orientationNow: "Now",
    orientationState: "State",
    orientationNext: "Next",
    orientationMore: "More",
    orientationStateNeedsSetup: "Needs setup",
    orientationStateWaiting: "Waiting",
    orientationStateWorking: "Working",
    orientationStateBlocked: "Blocked",
    orientationStateReady: "Ready",
    orientationStateInterrupted: "Interrupted",
    leftoverNotLive: "This is stored leftover on this workspace, not the live plan.",
    leftoverNotLiveHint: "These chips are hints only. They do not create a plan or task.",
    summaryEmpty: "No summary yet",
    history: "History",
    composerAccessibility: "Composer",
    reviewNotFull: "Review incomplete",
  },

  // ==========================================================================
  // Español (西班牙)
  // ==========================================================================
  "es-ES": {
    settingsStatusRegionLabel: "Estado actual",
    settingsStatusConnected: "Conectado",
    settingsStatusNotConnected: "Sin conexión",
    settingsStatusLanguage: "Idioma",
    settingsStatusMemory: "Memoria",
    settingsStatusNoApiKey: "Falta la clave API",
    settingsStatusNeedsTest: "Conexión sin probar",
    settingsStatusTrust: "Espacio no confiable",
    settingsStatusUnsaved: "Cambios sin guardar",
    settingsSectionConnection: "Conexión",
    settingsTeachingPrefs: "Preferencias de enseñanza",
    settingsAnswerStyle: "Estilo de respuesta",
    answerStyleSimple: "Sencillo",
    answerStyleBalanced: "Equilibrado",
    answerStyleDeep: "Profundo",
    answerStyleCustom: "Personalizado",
    settingsAnswerStyleHint: "Los preajustes definen el contexto y los adjuntos. Guarda para aplicar.",
    settingsAdvancedContext: "Contexto avanzado",
    settingsMemoryPrivacy: "Memoria y privacidad",
    settingsAdvanced: "Avanzado",
    coach: "Entrenador",
    coachArtifactFullDetails: "Detalles completos",
    trainer: "Entrenador",
    you: "Tú",
    plan: "Plan",
    settings: "Ajustes",
    chat: "Chat",
    workspace: "Espacio",
    viewNavigation: "Vistas de Trainer",
    currentFocus: "Enfoque Actual",
    currentTask: "Tarea Actual",
    latestReview: "Última Revisión",
    backgroundAnalysis: "Análisis en Segundo Plano",
    backgroundCoachWork: "Preparación del Entrenador",
    firstLookBadge: "Resumen del proyecto",
    firstLookProjectType: "Tipo de proyecto",
    firstLookFolderRole: "Rol de la carpeta",
    firstLookWhyGuess: "Por qué esta suposición",
    firstLookEntryPoints: "Puntos de entrada",
    firstLookDirectoryAnchors: "Ubicaciones clave",
    firstLookCoreModules: "Módulos / materiales clave",
    firstLookRiskZones: "Zonas de riesgo",
    firstLookOpportunities: "Oportunidades de práctica",
    firstLookUnknowns: "Desconocidos",
    firstLookNextStep: "Siguiente paso",
    workspaceAdmissionRootMissing: "No se configuró la raíz del espacio",
    workspaceAdmissionRootMissingDetail: "Elige dónde Trainer guarda los registros de aprendizaje antes de decidir cómo tratar este proyecto.",
    workspaceAdmissionGoalSaved: "Tu objetivo sigue en el cuadro. Elige dónde guardar los registros de aprendizaje y vuelve para enviarlo.",
    workspaceAdmissionProjectFound: "Proyecto encontrado",
    workspaceAdmissionProjectFoundDetail: "Elige una opción: agregarlo a Trainer, explorarlo o ignorarlo.",
    workspaceAdmissionManaged: "Gestionado por Trainer",
    workspaceAdmissionManagedDetail: "El chat, el plan y los registros de aprendizaje de este proyecto se guardan por separado.",
    workspaceAdmissionBrowse: "Solo explorar",
    workspaceAdmissionBrowseDetail: "Puedes inspeccionar este proyecto, pero el coaching y los registros guardados permanecen desactivados.",
    workspaceAdmissionIgnored: "Ignorado",
    workspaceAdmissionIgnoredDetail: "Trainer no leerá ni gestionará este proyecto. Puedes agregarlo más tarde.",
    workspaceAdmissionProjectName: "Proyecto",
    workspaceAdmissionProjectPath: "Ruta",
    workspaceAdmissionSelectRoot: "Elegir raíz del espacio",
    workspaceAdmissionSelectProject: "Elegir carpeta del proyecto",
    workspaceAdmissionAdd: "Agregar a Trainer",
    workspaceAdmissionBrowseAction: "Solo explorar",
    workspaceAdmissionIgnore: "Ignorar proyecto",
    workspaceAdmissionDelete: "Eliminar proyecto",
    workspaceRootControl: "Espacio de Trainer",
    workspaceRootReady: "Los registros de aprendizaje se guardan en este espacio.",
    workspaceRootPath: "Raíz",
    workspaceRootMigrate: "Migrar espacio",
    workspaceRootMigrateDetail: "Copia a una carpeta vacía y continúa desde la nueva raíz.",
    workspaceRootRecovery: "Copia de seguridad y recuperación",
    workspaceRootBackup: "Crear copia",
    workspaceRootBackupDetail: "Crea una copia recuperable sin cambiar la raíz actual.",
    workspaceRootRestore: "Restaurar copia",
    workspaceRootRestoreDetail: "Restaura en una carpeta vacía y la convierte en la raíz activa.",
    workspaceRootChange: "Cambiar raíz",
    workspaceRootChangeDetail: "Elige otra raíz sin copiar los datos actuales.",
    coachState: "Estado del Entrenador",
    coachSignal: "Señal de Aprendizaje",
    reviewQueue: "Cola de Revisión",
    reviewMemory: "Memoria y Ritmo",
    reviewRhythm: "Ritmo de Revisión",
    nextReview: "Próxima Revisión",
    teachingObservations: "Observaciones de Enseñanza",
    coachSummaryDoing: "En curso",
    goals: "Objetivos",
    constraints: "Restricciones",
    acceptance: "Criterios de Aceptación",
    nextMove: "Próximo Movimiento",
    recentWins: "Victorias Recientes",
    weakSpots: "Puntos Débiles",
    planStages: "Etapas",
    trainingWhyNow: "Por qué ahora",
    trainingDeliverable: "Entregable",
    planStageMaterialsTitle: "Materiales de estudio",
    planStageMaterialsGenerate: "Generar materiales",
    planStageMaterialsGenerating: "Generando…",
    planStageMaterialsView: "Ver",
    planStageMaterialsHide: "Ocultar",
    planStageMaterialsEmpty: "Todavía no hay materiales de estudio para esta etapa.",
    planStageCompletionLabel: "Progreso de la etapa",
    planStageMaterialsBadgeTitle: "Materiales generados",
    planDashboardTabPlan: "Plan",
    planDashboardTabProgress: "Progreso",
    planDashboardStagesTitle: "Avance de etapas",
    planDashboardMasteryTitle: "Dominio de dependencias",
    planDashboardReviewTitle: "Retención de repaso FSRS",
    planDashboardMaterialsTitle: "Uso de materiales",
    planDashboardMaterialsStages: "Etapas cubiertas",
    planDashboardMasteryEmpty: "Aún no hay datos de dominio. Se acumulan al completar tarjetas de entrenamiento.",
    planDashboardReviewDue: "Pendiente",
    planDashboardReviewDone: "Completado",
    planDashboardEmptyTitle: "Genera primero un plan",
    trainingHandoffMismatchHint: "Esta tarjeta no coincide con el traspaso de entrenamiento actual. Cambia a la tarjeta propietaria del traspaso.",
    trainingSwitchToCard: "Cambiar a esa tarjeta",
    trainingCardDetailsApiHints: "Pistas de API",
    trainingCardDetailsSelfCheck: "Autoevaluación",
    trainingCardDetailsRubric: "Rúbrica de evaluación",
    trainingCardDetailsAcceptance: "Criterios de aceptación",
    language: "Idioma",
    answerMode: "Modo de Respuesta",
    teachingStyle: "Estilo de Enseñanza",
    teachingGuided: "Guiado",
    teachingConceptFirst: "Concepto Primero",
    teachingHandsOn: "Práctico",
    teachingChallenging: "Desafiante",
    contextDetail: "Detalle de Contexto",
    coachFirst: "Guiado",
    balanced: "Equilibrado",
    direct: "Directo",
    detailFocused: "Enfocado",
    detailBalanced: "Estándar",
    detailFull: "Completo",
    attachments: "Adjuntos",
    currentContext: "Contexto Actual",
    allContext: "Todo el Contexto",
    noContext: "Sin Contexto",
    file: "Archivo",
    selection: "Selección",
    diagnostics: "Diagnósticos",
    relatedFiles: "Archivos Relacionados",
    follow: "Seguimiento en Vivo",
    theme: "Tema",
    system: "Sistema",
    light: "Claro",
    dark: "Oscuro",
    provider: "Proveedor",
    baseUrl: "URL Base",
    chatModel: "Modelo",
    apiKey: "Clave API",
    apiKeySaved: "Guardada",
    apiKeyMissing: "No configurada",
    saveProvider: "Guardar",
    testProvider: "Probar",
    clearProvider: "Limpiar",
    openConfigFile: "Abrir Config",
    configured: "Configurado",
    notConfigured: "No configurado",
    protocol: "Protocolo",
    refreshProviderProfiles: "Actualizar perfiles",
    refreshWorkspaceAuthority: "Actualizar espacio",
    createProfileFromTemplate: "Crear desde plantilla",
    settingsIntro: "Solo los ajustes más comunes aquí.",
    settingsGeneral: "Interfaz",
    settingsCoachBehavior: "Comportamiento",
    settingsModelAccess: "Modelo y Conexión",
    settingsWorkspaceNote: "Frontend solo muestra conexión y preferencias frecuentes.",
    settingsProviderHint: "Enfoque en conexión del modelo.",
    settingsCoachHint: "Estos controles afectan el contexto que lee el entrenador.",
    send: "Enviar",
    streaming: "Pensando…",
    configureProviderFirst: "Trainer no está listo. Configure proveedor y API key.",
    configureProviderFirstPlan: "Trainer no puede generar planes. Complete la conexión.",
    providerRequiredHint: "Sin proveedor disponible. Trainer no puede trabajar.",
    composerPlaceholder: "Dile al entrenador qué quieres construir o dónde estás bloqueado.",
    composerPlaceholderPlan: "Cómo ajustar este plan.",
    slashCommands: "Comandos",
    runLocalCommand: "Ejecutará comando local",
    switchView: "Cambiar Vista",
    setLanguage: "Idioma",
    setAnswerMode: "Modo",
    setContextDetail: "Contexto",
    setAttachments: "Adjuntos",
    setLiveFollow: "Seguimiento",
    opened: "Abierto",
    updated: "Actualizado",
    on: "Activado",
    off: "Desactivado",
    connected: "Conectado",
    starting: "Conectando",
    offline: "Offline",
    pass: "Aprobado",
    fail: "Fallido",
    warn: "Advertencia",
    pending: "Pendiente",
    suggestedActions: "Acciones Sugeridas",
    generatePlan: "Generar Plan",
    nextTask: "Siguiente Tarea",
    runReview: "Revisar",
    openCoach: "Abrir Coach",
    openPlan: "Abrir Plan",
    openSettings: "Ajustes",
    shortcutSend: "Enviar",
    shortcutNewline: "Nueva Línea",
    shortcutSlash: "Comando (/)",
    shortcutClear: "Limpiar",
    reviewNeedsFile: "Revisión requiere archivo abierto",
    reviewFileDisabled: "Archivo no disponible",
    selectionMissing: "Sin selección",
    selectionDisabled: "Selección deshabilitada",
    relatedMissing: "Sin archivos relacionados",
    training: "Entrenamiento",
    flashcards: "Tarjetas",
    practice: "Práctica",
    review: "Revisión",
    startTraining: "Comenzar",
    nextCard: "Siguiente",
    previousCard: "Anterior",
    showAnswer: "Mostrar",
    submitAnswer: "Enviar",
    skipCard: "Saltar",
    markAgain: "Otra vez",
    markHard: "Difícil",
    markGood: "Bien",
    markEasy: "Fácil",
    dueToday: "Para hoy",
    cardsToReview: "tarjetas",
    learningPath: "Ruta de Aprendizaje",
    masteryLevel: "Dominio",
    streak: "Racha",
    totalReviews: "Total",
    accuracy: "Precisión",
    reinforcementLearning: "Aprendizaje por Refuerzo",
    qLearning: "Q-Learning",
    dqn: "DQN",
    policyGradient: "Gradiente de Política",
    actorCritic: "Actor-Crítico",
    ddpg: "DDPG",
    ppo: "PPO",
    mcts: "MCTS",
    algorithm: "Algoritmo",
    state: "Estado",
    action: "Acción",
    reward: "Recompensa",
    policy: "Política",
    valueFunction: "Función de Valor",
    qTable: "Tabla-Q",
    epsilon: "Epsilon",
    discountFactor: "Factor de Descuento",
    learningRate: "Tasa de Aprendizaje",
    exploration: "Exploración",
    exploitation: "Explotación",
    bellmanEquation: "Ecuación de Bellman",
    temporalDifference: "Diferencia Temporal",
    monteCarlo: "Monte Carlo",
    onPolicy: "On-Policy",
    offPolicy: "Off-Policy",
    experienceReplay: "Replay de Experiencia",
    targetNetwork: "Red Objetivo",
    policyLoss: "Pérdida de Política",
    valueLoss: "Pérdida de Valor",
    entropyBonus: "Bonus de Entropía",
    clipping: "Recorte",
    gae: "GAE",
    advantage: "Ventaja",
    rollout: "Rollout",
    backpropagation: "Retropropagación",
    gradient: "Gradiente",
    optimizer: "Optimizador",
    adam: "Adam",
    sgd: "SGD",
    batchSize: "Tamaño de Lote",
    episode: "Episodio",
    step: "Paso",
    horizon: "Horizonte",
    environment: "Entorno",
    agent: "Agente",
    observation: "Observación",
    episodeEnd: "Fin de Episodio",
    cumulativeReward: "Recompensa Acumulada",
    convergence: "Convergencia",
    divergence: "Divergencia",
    trainingCurve: "Curva de Entrenamiento",
    evaluationMetric: "Métrica",
    hyperparameter: "Hiperparámetro",
    architecture: "Arquitectura",
    networkLayer: "Capa",
    inputLayer: "Entrada",
    outputLayer: "Salida",
    hiddenLayer: "Oculta",
    activation: "Activación",
    relu: "ReLU",
    sigmoid: "Sigmoid",
    softmax: "Softmax",
    lossFunction: "Función de Pérdida",
    crossEntropy: "Entropía Cruzada",
    mse: "MSE",
    regularization: "Regularización",
    dropout: "Dropout",
    batchNorm: "Batch Norm",
    earlyStopping: "Early Stopping",
    checkpoint: "Checkpoint",
    saveModel: "Guardar",
    loadModel: "Cargar",
    export: "Exportar",
    import: "Importar",
    newConversation: "Nuevo Chat",
    continueConversation: "Continuar",
    deleteConversation: "Eliminar",
    renameConversation: "Renombrar",
    searchConversations: "Buscar",
    noConversations: "Sin conversaciones",
    typing: "Escribiendo…",
    coachThinking: "Pensando…",
    coachTyping: "Escribiendo…",
    regenerate: "Regenerar",
    copyMessage: "Copiar",
    editMessage: "Editar",
    deleteMessage: "Eliminar",
    messageCopied: "Copiado",
    errorOccurred: "Error",
    tryAgain: "Reintentar",
    cancel: "Cancelar",
    confirm: "Confirmar",
    save: "Guardar",
    close: "Cerrar",
    back: "Atrás",
    next: "Siguiente",
    loading: "Cargando…",
    empty: "Vacío",
    noResults: "Sin resultados",
    searchResults: "Resultados",
    filter: "Filtrar",
    sort: "Ordenar",
    refresh: "Actualizar",
    timeout: "Tiempo agotado",
    networkError: "Error de red",
    unknownError: "Error desconocido",
    evidenceOutcomePass: "Aprobado",
    evidenceOutcomeFail: "Fallido",
    evidenceOutcomePartial: "Parcial",
    evidenceOutcomeInsight: "Perspicacia",
    evidenceOutcomeObservation: "Observación",

    // Estado de acciones del coach
    coachActionIdle: "Inactivo",
    coachActionCheckingResources: "Revisando Recursos",
    coachActionSearchingResources: "Buscando Recursos",
    coachActionAligningPlan: "Alineando Plan",
    coachActionPlanAlignment: "Alineación del Plan",
    coachActionSchedulingTraining: "Programando Entrenamiento",
    coachActionGeneratingCard: "Generando Tarjeta",
    coachActionCardGeneration: "Generación de Tarjeta",
    coachActionEvaluatingResult: "Evaluando Resultado",
    coachActionEvaluation: "Evaluación",
    coachActionReviewingEvidence: "Revisando Evidencia",
    coachActionResourceUpload: "Subiendo Recurso",
    coachActionWorkspaceClassification: "Clasificación del Espacio",
    coachActionDoneIdle: "Hecho - Inactivo",
    coachActionDoneCheckingResources: "Hecho - Recursos Revisados",
    coachActionDoneSearchingResources: "Hecho - Recursos Buscados",
    coachActionDoneAligningPlan: "Hecho - Plan Alineado",
    coachActionDonePlanAlignment: "Hecho - Plan Alineado",
    coachActionDoneSchedulingTraining: "Hecho - Entrenamiento Programado",
    coachActionDoneGeneratingCard: "Hecho - Tarjeta Generada",
    coachActionDoneCardGeneration: "Hecho - Tarjeta Generada",
    coachActionDoneEvaluatingResult: "Hecho - Resultado Evaluado",
    coachActionDoneEvaluation: "Hecho - Evaluado",
    coachActionDoneReviewingEvidence: "Hecho - Evidencia Revisada",
    coachActionDoneResourceUpload: "Hecho - Recurso Subido",
    coachActionDoneWorkspaceClassification: "Hecho - Espacio Clasificado",

    // Mastery stages
    masteryUnderstood: "Comprendido",
    masteryRecalled: "Recordado",
    masteryPracticed: "Practicado",
    masteryApplied: "Aplicado",
    masteryTransferable: "Transferible",
    masteryNotEstablished: "Por establecer",

    // CoachSettingsView labels
    settingsSetupSection: "Conexión del modelo",
    settingsSetupTitleReady: "Trainer está listo para comenzar",
    settingsSetupTitleBlocked: "Trainer no puede iniciar sin una API key",
    settingsSetupDetailReady: "La conexión del modelo está lista. Puedes comenzar a chatear, planificar y aprender.",
    settingsSetupDetailBlocked: "Guarda el proveedor, URL base, modelo y API key. Solo así Trainer podrá trabajar.",
    settingsSetupAction: "Completar configuración",
    settingsInterfaceSection: "Cómo Trainer te guía",
    settingsCoachSection: "Contexto predeterminado por turno",
    settingsModelSection: "Conectar modelo",
    settingsFollowCurrentFile: "Seguimiento en vivo",
    settingsContextMode: "Nivel de contexto",
    settingsCurrentFile: "Archivo actual",
    settingsConnectionDetails: "Detalles de conexión",
    settingsLongTermMemory: "Memoria a largo plazo",
    settingsMemoryScope: "Alcance de memoria",
    settingsMemoryScopeProject: "Proyecto actual",
    settingsMemoryScopePersonal: "Personal",
    settingsMemoryScopeSession: "Sesión actual",
    settingsRememberDecisions: "Decisiones de arquitectura",
    settingsRememberPatterns: "Patrones comunes",
    settingsRememberResources: "Referencias",
    settingsWorkingSet: "Conjunto de trabajo",
    settingsWorkingSetFocused: "Solo tarea actual",
    settingsWorkingSetBalanced: "Archivos cercanos",
    settingsWorkingSetBroad: "Referencias más amplias",
    settingsMemoryPreview: "Retención prioritaria",
    settingsMemoryPreviewEmpty: "Actualmente sigue archivo, selección y diagnósticos.",
    settingsTeachingSignal: "Señal de aprendizaje",
    settingsConfigFileNote: "Necesitas más ajustes? Puedes afinarlos en el archivo de configuración.",
    settingsContextSection: "Contexto adjunto",
    settingsMemoryRuntime: "Operación en segundo plano",
    settingsMemoryRuntimeDetail: "Memoria, revisión y ritmo de enseñanza se actualizan automáticamente con cada turno.",
    settingsAdvancedSection: "Más estrategias predeterminadas",
    settingsAdvancedIntro: "No necesitas tocar estas opciones a menudo. Expande solo cuando quieras cambiar cómo Trainer continúa, recuerda y lee contexto.",
    settingsReviewRhythmPace: "Intensidad de recordatorio",
    settingsReviewRhythmReminder: "Estrategia de recordatorio",
    settingsReviewStrategy: "Estrategia de revisión",
    settingsSystemActions: "Organizar estado actual",
    settingsRefreshMemory: "Actualizar memoria actual",
    settingsResetDefaults: "Restaurar valores predeterminados",
    settingsModelTools: "Herramientas de conexión",
    settingsDefaultsHint: "Define cómo Trainer habla y te guía. La mayoría de las conversaciones seguirán este ritmo.",
    settingsContextHint: "Solo establece los archivos adjuntos predeterminados por turno.",
    settingsModelHint: "Solo maneja la conexión del modelo. El verdadero coaching viene del plan, memoria y continuidad.",
    settingsAvailableModels: "Modelos disponibles",
    settingsDetectedModel: "Modelo detectado",
    settingsModelFetchLoading: "Obteniendo lista de modelos…",
    settingsModelFetchEmpty: "La lista de modelos se cargará automáticamente después de guardar la API key.",
    settingsRefreshModels: "Actualizar lista de modelos",
    settingsModelCache: "Estado de lista de modelos",
    settingsModelCacheSource: "Fuente",
    settingsModelCacheFetchedAt: "Obtenido en",
    settingsModelCacheExpiresAt: "Expira en",
    settingsModelCacheStatus: "Estado",
    settingsModelCacheError: "Razón del error",
    settingsModelCacheSourceLive: "Obtención en vivo",
    settingsModelCacheSourceCache: "Resultado en caché",
    settingsModelCacheStatusFresh: "Vigente",
    settingsModelCacheStatusExpired: "Expirado",
    settingsModelCacheStatusUnknown: "Desconocido",
    settingsModelCacheStatusLoading: "Actualizando",
    settingsModelCacheStatusError: "Fallido",
    settingsRuntimeSection: "Runtime actual del coach",
    settingsRuntimeHint: "Esto describe qué hilo continuaría Trainer si enviaras un mensaje ahora.",
    settingsMemoryStrategy: "Estrategia de memoria",
    settingsMemoryStrategyHint: "Controla qué tiende a recordar Trainer y si esas memorias permanecen en este proyecto o viajan a otros.",
    settingsReviewStrategyHint: "Controla cada cuánto Trainer te pide revisar y qué tan intrusivos deben ser esos recordatorios.",
    settingsContextCurrentFileHint: "Siempre da prioridad al archivo que estás editando activamente.",
    settingsContextSelectionHint: "Incluye la selección actual cuando tengas una.",
    settingsContextDiagnosticsHint: "Adjunta diagnósticos cuando el turno sea sobre revisión o depuración.",
    settingsContextRelatedFilesHint: "Trae archivos relacionados solo cuando realmente se necesite un contexto más amplio.",
    settingsMemoryScopeRuntimeProject: "Sigue principalmente el plan, hilo y recursos del proyecto actual.",
    settingsMemoryScopeRuntimePersonal: "Mantiene preferencias, juicio y rastros de entrenamiento entre proyectos.",
    settingsMemoryScopeRuntimeSession: "Se mantiene dentro del hilo de la sesión actual.",
    settingsMemoryScopeProjectHint: "Mantén el hilo y juicio dentro del proyecto actual.",
    settingsMemoryScopePersonalHint: "Lleva hábitos y juicio reutilizables a otros proyectos.",
    settingsMemoryScopeSessionHint: "Mantén la memoria local solo para la conversación actual.",
    settingsWorkingSetFocusedHint: "Quédate en el fragmento verificable más pequeño y archivos cercanos.",
    settingsWorkingSetBalancedHint: "Equilibra el fragmento actual con contexto cercano para la mayoría de los turnos de código.",
    settingsWorkingSetBroadHint: "Permite contexto más amplio cuando la verificación lo necesite.",
    settingsReviewCadenceLightHint: "Interrumpe menos a menudo mientras mantienes los puntos clave de revisión.",
    settingsReviewCadenceSteadyHint: "Sigue un ritmo de entrenamiento normal.",
    settingsReviewCadenceActiveHint: "Revisa más frecuentemente para sprints cortos.",
    settingsReviewReminderDueHint: "Recuerda principalmente cuando la revisión esté realmente vencida.",
    settingsReviewReminderAheadHint: "Envía un aviso antes de que venza la revisión.",
    settingsReviewReminderDigestHint: "Agrupa revisiones cercanas en un solo digest.",
    settingsSavedState: "Guardado",
    settingsUnsavedState: "Cambios sin guardar",
    settingsEmptyState: "No escrito en workspace",
    settingsEffectiveNow: "Efectivo ahora",
    settingsSavedInWorkspace: "Guardado en workspace",
    settingsEditingDraft: "Editando",
    settingsCurrentWorkspace: "Workspace actual",
    settingsLocalThemeNote: "El tema solo afecta lo que ves ahora, no se escribe en workspace.",
    settingsWorkspaceSaveNote: "Guardar valores predeterminados del coach también guarda controles de nivel de workspace.",
    settingsProviderRuntimeNote: "Probar conexión usa la configuración del provider que está activa en el workspace ahora.",
    settingsLatestAction: "Acción reciente",
    settingsLastTest: "Última prueba",
    settingsLastTestNever: "Nunca probado",
    settingsLastTestPassed: "Aprobado",
    settingsLastTestFailed: "Fallido",
    settingsLastTestNeedsSetup: "Necesita configuración",
    settingsFocused: "Enfocado",
    settingsBalancedContext: "Estándar",
    settingsFullContext: "Extendido",
    settingsSaveCoachDefaults: "Guardar valores del coach",
    globalPlanLabel: "Plan global",
    globalPlanRelationship: "Plan global -> Plan del proyecto actual",
    globalPlanNotCreated: "Sin crear",
    globalPlanNotLinked: "El proyecto actual no est\u00e1 vinculado",
    globalPlanLinked: "Vinculado al proyecto actual",
    globalPlanCreate: "Crear plan global",
    globalPlanLinkCurrentProject: "Vincular el plan del proyecto actual",
    globalPlanLinkUnavailable: "Primero genera un plan para el proyecto actual",
    globalPlanFrozen: "El plan global est\u00e1 congelado",
    evidenceConfidence: "Confianza",
    evidenceGovernance: "Gobernanza de evidencia",
    evidenceFilterAll: "Todo",
    evidenceFilterDeferred: "Pospuesto",
    evidenceFilterAdopted: "Adoptado",
    evidenceFilterRejected: "Rechazado",
    evidenceAdopt: "Adoptar",
    evidenceDefer: "Posponer",
    evidenceTargetPrefix: "Objetivo",
    evidenceNoMatches: "No hay evidencia que coincida con este filtro.",
  },

  // ==========================================================================
  // Français (法国)
  // ==========================================================================
  "fr-FR": {
    settingsStatusRegionLabel: "État actuel",
    settingsStatusConnected: "Connecté",
    settingsStatusNotConnected: "Non connecté",
    settingsStatusLanguage: "Langue",
    settingsStatusMemory: "Mémoire",
    settingsStatusNoApiKey: "Clé API manquante",
    settingsStatusNeedsTest: "Connexion non testée",
    settingsStatusTrust: "Espace non approuvé",
    settingsStatusUnsaved: "Modifications non enregistrées",
    settingsSectionConnection: "Connexion",
    settingsTeachingPrefs: "Préférences pédagogiques",
    settingsAnswerStyle: "Style de réponse",
    answerStyleSimple: "Simple",
    answerStyleBalanced: "Équilibré",
    answerStyleDeep: "Approfondi",
    answerStyleCustom: "Personnalisé",
    settingsAnswerStyleHint: "Les préréglages définissent le contexte et les pièces jointes. Enregistrez pour appliquer.",
    settingsAdvancedContext: "Contexte avancé",
    settingsMemoryPrivacy: "Mémoire et confidentialité",
    settingsAdvanced: "Avancé",
    coach: "Coach",
    coachArtifactFullDetails: "Détails complets",
    trainer: "Trainer",
    you: "Vous",
    plan: "Plan",
    settings: "Paramètres",
    chat: "Discussion",
    workspace: "Espace de travail",
    viewNavigation: "Vues Trainer",
    currentFocus: "Focus actuel",
    currentTask: "Tâche actuelle",
    latestReview: "Dernière révision",
    backgroundAnalysis: "Analyse en arrière-plan",
    backgroundCoachWork: "Préparation du coach",
    firstLookBadge: "Aperçu du projet",
    firstLookProjectType: "Type de projet",
    firstLookFolderRole: "Rôle du dossier",
    firstLookWhyGuess: "Pourquoi cette estimation",
    firstLookEntryPoints: "Points d'entrée",
    firstLookDirectoryAnchors: "Emplacements clés",
    firstLookCoreModules: "Modules / supports clés",
    firstLookRiskZones: "Zones de risque",
    firstLookOpportunities: "Possibilités d'entraînement",
    firstLookUnknowns: "Inconnues",
    firstLookNextStep: "Prochaine étape",
    workspaceAdmissionRootMissing: "Racine de l'espace non définie",
    workspaceAdmissionRootMissingDetail: "Choisissez où Trainer conserve les suivis d’apprentissage avant de décider comment traiter ce projet.",
    workspaceAdmissionGoalSaved: "Votre objectif est toujours dans le champ. Choisissez où conserver les suivis, puis revenez l’envoyer.",
    workspaceAdmissionProjectFound: "Projet détecté",
    workspaceAdmissionProjectFoundDetail: "Choisissez : Ajouter à Trainer, Consultation seule ou Ignorer.",
    workspaceAdmissionManaged: "Géré par Trainer",
    workspaceAdmissionManagedDetail: "Les échanges, le plan et les suivis d’apprentissage de ce projet restent séparés.",
    workspaceAdmissionBrowse: "Consultation seule",
    workspaceAdmissionBrowseDetail: "Vous pouvez consulter ce projet, mais le coaching et les suivis enregistrés restent désactivés.",
    workspaceAdmissionIgnored: "Ignoré",
    workspaceAdmissionIgnoredDetail: "Trainer ne lira ni ne gérera ce projet. Vous pourrez l’ajouter plus tard.",
    workspaceAdmissionProjectName: "Projet",
    workspaceAdmissionProjectPath: "Chemin",
    workspaceAdmissionSelectRoot: "Choisir la racine",
    workspaceAdmissionSelectProject: "Choisir le dossier du projet",
    workspaceAdmissionAdd: "Ajouter à Trainer",
    workspaceAdmissionBrowseAction: "Consulter seulement",
    workspaceAdmissionIgnore: "Ignorer le projet",
    workspaceAdmissionDelete: "Supprimer le projet",
    workspaceRootControl: "Espace Trainer",
    workspaceRootReady: "Les dossiers d'apprentissage sont conservés dans cet espace.",
    workspaceRootPath: "Racine",
    workspaceRootMigrate: "Migrer l'espace",
    workspaceRootMigrateDetail: "Copiez vers un nouveau dossier vide et continuez depuis cette racine.",
    workspaceRootRecovery: "Sauvegarde et restauration",
    workspaceRootBackup: "Sauvegarder l'espace",
    workspaceRootBackupDetail: "Crée une copie récupérable sans modifier la racine active.",
    workspaceRootRestore: "Restaurer une sauvegarde",
    workspaceRootRestoreDetail: "Restaure dans un nouveau dossier vide et en fait la racine active.",
    workspaceRootChange: "Changer la racine",
    workspaceRootChangeDetail: "Choisissez une autre racine sans copier les données actuelles.",
    coachState: "État du coach",
    coachSignal: "Signal d'apprentissage",
    reviewQueue: "File de révision",
    runReview: "Commencer la révision",
    reviewMemory: "Mémoire et rythme",
    reviewRhythm: "Rythme de révision",
    nextReview: "Prochaine révision",
    teachingObservations: "Observations pédagogiques",
    coachSummaryDoing: "En cours",
    goals: "Objectifs",
    constraints: "Contraintes",
    acceptance: "Critères d'acceptation",
    nextMove: "Prochaine action",
    recentWins: "Gains récents",
    weakSpots: "Points faibles",
    planStages: "Étapes",
    trainingWhyNow: "Pourquoi maintenant",
    trainingDeliverable: "Livrable",
    planStageMaterialsTitle: "Supports d'étude",
    planStageMaterialsGenerate: "Générer les supports",
    planStageMaterialsGenerating: "Génération…",
    planStageMaterialsView: "Voir",
    planStageMaterialsHide: "Masquer",
    planStageMaterialsEmpty: "Il n'y a pas encore de supports d'étude pour cette étape.",
    planStageCompletionLabel: "Avancement de l'étape",
    planStageMaterialsBadgeTitle: "Supports générés",
    planDashboardTabPlan: "Plan",
    planDashboardTabProgress: "Progression",
    planDashboardStagesTitle: "Avancement des étapes",
    planDashboardMasteryTitle: "Maîtrise des dépendances",
    planDashboardReviewTitle: "Rétention des révisions FSRS",
    planDashboardMaterialsTitle: "Utilisation des supports",
    planDashboardMaterialsStages: "Étapes couvertes",
    planDashboardMasteryEmpty: "Pas encore de données de maîtrise. Elles s'accumulent à chaque carte d'entraînement terminée.",
    planDashboardReviewDue: "À revoir",
    planDashboardReviewDone: "Terminé",
    planDashboardEmptyTitle: "Générez d'abord un plan",
    trainingHandoffMismatchHint: "Cette carte ne correspond pas au transfert d'entraînement actuel. Passez à la carte qui détient le transfert.",
    trainingSwitchToCard: "Aller à cette carte",
    trainingCardDetailsApiHints: "Indices d'API",
    trainingCardDetailsSelfCheck: "Auto-vérification",
    trainingCardDetailsRubric: "Barème de notation",
    trainingCardDetailsAcceptance: "Critères d'acceptation",
    language: "Langue",
    answerMode: "Mode de réponse",
    teachingStyle: "Style pédagogique",
    teachingGuided: "Guidé",
    teachingConceptFirst: "Concept d'abord",
    teachingHandsOn: "Pratique d'abord",
    teachingChallenging: "Défiant",
    contextDetail: "Détail du contexte",
    coachFirst: "Guidé",
    balanced: "Équilibré",
    direct: "Direct",
    detailFocused: "Focalisé",
    detailBalanced: "Standard",
    detailFull: "Complet",
    attachments: "Pièces jointes",
    currentContext: "Contexte actuel",
    allContext: "Tout le contexte",
    noContext: "Pas de contexte",
    file: "Fichier",
    selection: "Sélection",
    diagnostics: "Diagnostics",
    relatedFiles: "Fichiers associés",
    follow: "Suivi en direct",
    theme: "Thème",
    system: "Système",
    light: "Clair",
    dark: "Sombre",
    provider: "Fournisseur",
    protocol: "Protocole",
    baseUrl: "URL de base",
    chatModel: "Modèle",
    apiKey: "Clé API",
    apiKeySaved: "Enregistré",
    apiKeyMissing: "Non configuré",
    saveProvider: "Enregistrer",
    testProvider: "Tester la connexion",
    clearProvider: "Effacer",
    openConfigFile: "Ouvrir le fichier",
    configured: "Configuré",
    notConfigured: "Non configuré",
    refreshProviderProfiles: "Actualiser les profils",
    refreshWorkspaceAuthority: "Actualiser l'autorité",
    createProfileFromTemplate: "Créer depuis un modèle",
    settingsSetupSection: "Connexion au modèle",
    settingsSetupTitleReady: "Trainer est prêt",
    settingsSetupTitleBlocked: "Sans clé API, Trainer ne peut pas démarrer",
    settingsSetupDetailReady: "La connexion au modèle est établie. Vous pouvez discuter, planifier et apprendre maintenant.",
    settingsSetupDetailBlocked: "Enregistrez le fournisseur, l'URL, le modèle et la clé API. Trainer ne peut travailler qu'ainsi.",
    settingsSetupAction: "Compléter la configuration",
    settingsInterfaceSection: "Comment Trainer vous guide",
    settingsCoachSection: "Contexte par défaut par tour",
    settingsModelSection: "Connecter le modèle",
    settingsFollowCurrentFile: "Suivi en direct",
    settingsContextMode: "Niveau de contexte",
    settingsCurrentFile: "Fichier actuel",
    settingsConnectionDetails: "Détails de connexion",
    settingsLongTermMemory: "Mémoire à long terme",
    settingsMemoryScope: "Portée de la mémoire",
    settingsMemoryScopeProject: "Projet actuel",
    settingsMemoryScopePersonal: "Personnel通用",
    settingsMemoryScopeSession: "Session actuelle",
    settingsRememberDecisions: "Décisions d'architecture",
    settingsRememberPatterns: "Modèles courants",
    settingsRememberResources: "Références",
    settingsWorkingSet: "Ensemble de travail",
    settingsWorkingSetFocused: "Tâche actuelle",
    settingsWorkingSetBalanced: "Fichiers proches",
    settingsWorkingSetBroad: "Références plus larges",
    settingsMemoryPreview: "Rétention prioritaire",
    settingsMemoryPreviewEmpty: "Actuellement suit fichier, sélection et diagnostics.",
    settingsTeachingSignal: "Signal d'apprentissage",
    settingsConfigFileNote: "Besoin de plus de réglages ? Vous pouvez les ajuster dans le fichier de configuration.",
    settingsContextSection: "Contexte attaché",
    settingsMemoryRuntime: "Exécution en arrière-plan",
    settingsMemoryRuntimeDetail: "Mémoire, révision et rythme se mettent à jour automatiquement à chaque tour.",
    settingsAdvancedSection: "Plus de stratégies par défaut",
    settingsAdvancedIntro: "Pas besoin de toucher souvent. Développez uniquement pour changer comment Trainer continue et se souvient.",
    settingsReviewRhythmPace: "Intensité du rappel",
    settingsReviewRhythmReminder: "Stratégie de rappel",
    settingsReviewStrategy: "Stratégie de révision",
    settingsSystemActions: "Organiser l'état actuel",
    settingsRefreshMemory: "Actualiser la mémoire",
    settingsResetDefaults: "Restaurer les valeurs",
    settingsModelTools: "Outils de connexion",
    settingsDefaultsHint: "Définissez comment Trainer parle et vous guide. La plupart des conversations suivront ce rythme.",
    settingsContextHint: "Définit uniquement les fichiers joints par défaut par tour.",
    settingsModelHint: "Gère uniquement la connexion. Le vrai coaching vient du plan et de la continuité.",
    settingsAvailableModels: "Modèles disponibles",
    settingsDetectedModel: "Modèle détecté",
    settingsModelFetchLoading: "Chargement des modèles…",
    settingsModelFetchEmpty: "La liste se chargera automatiquement après l'enregistrement de la clé API.",
    settingsRefreshModels: "Actualiser la liste",
    settingsModelCache: "État du cache des modèles",
    settingsModelCacheSource: "Source",
    settingsModelCacheFetchedAt: "Obtenu à",
    settingsModelCacheExpiresAt: "Expire à",
    settingsModelCacheStatus: "État",
    settingsModelCacheError: "Raison de l'erreur",
    settingsModelCacheSourceLive: "En direct",
    settingsModelCacheSourceCache: "En cache",
    settingsModelCacheStatusFresh: "À jour",
    settingsModelCacheStatusExpired: "Expiré",
    settingsModelCacheStatusUnknown: "Inconnu",
    settingsModelCacheStatusLoading: "Chargement",
    settingsModelCacheStatusError: "Erreur",
    settingsRuntimeSection: "Runtime actuel du coach",
    settingsRuntimeHint: "Décrit quel fil Trainer continuerait si vous envoyiez maintenant.",
    settingsMemoryStrategy: "Stratégie de mémoire",
    settingsMemoryStrategyHint: "Contrôle ce que Trainer tend à retenir et si ces souvenirs restent dans ce projet.",
    settingsReviewStrategyHint: "Contrôle la fréquence des révisions et l'intrusion des rappels.",
    settingsContextCurrentFileHint: "Priorité au fichier que vous modifiez.",
    settingsContextSelectionHint: "Inclut la sélection actuelle.",
    settingsContextDiagnosticsHint: "Joint les diagnostics pour les révisions.",
    settingsContextRelatedFilesHint: "Apporte les fichiers associés uniquement si nécessaire.",
    settingsMemoryScopeRuntimeProject: "Reste dans le projet actuel.",
    settingsMemoryScopeRuntimePersonal: "Maintient les préférences entre les projets.",
    settingsMemoryScopeRuntimeSession: "Reste dans la session actuelle.",
    settingsMemoryScopeProjectHint: "Gardez le fil dans le projet actuel.",
    settingsMemoryScopePersonalHint: "Portez les habitudes vers d'autres projets.",
    settingsMemoryScopeSessionHint: "Mémoire locale pour la conversation actuelle.",
    settingsWorkingSetFocusedHint: "Restez dans le fragment vérifiable le plus petit.",
    settingsWorkingSetBalancedHint: "Équilibrez le fragment actuel avec le contexte proche.",
    settingsWorkingSetBroadHint: "Permettez un contexte plus large si nécessaire.",
    settingsReviewCadenceLightHint: "Interrompt moins souvent.",
    settingsReviewCadenceSteadyHint: "Rythme normal.",
    settingsReviewCadenceActiveHint: "Révisions plus fréquentes.",
    settingsReviewReminderDueHint: "Rappelle principalement à l'échéance.",
    settingsReviewReminderAheadHint: "Envoie un avertissement avant.",
    settingsReviewReminderDigestHint: "Groupe les révisions proches.",
    settingsSavedState: "Enregistré",
    settingsUnsavedState: "Non enregistré",
    settingsEmptyState: "Non écrit dans l'espace de travail",
    settingsEffectiveNow: "Effectif maintenant",
    settingsSavedInWorkspace: "Enregistré dans l'espace de travail",
    settingsEditingDraft: "Édition en cours",
    settingsCurrentWorkspace: "Espace de travail actuel",
    settingsLocalThemeNote: "Le thème n'affecte que ce que vous voyez.",
    settingsWorkspaceSaveNote: "Enregistrer les valeurs du coach sauvegarde également les contrôles de niveau.",
    settingsProviderRuntimeNote: "Le test utilise la configuration active dans l'espace de travail.",
    settingsLatestAction: "Action récente",
    settingsLastTest: "Dernier test",
    settingsLastTestNever: "Jamais testé",
    settingsLastTestPassed: "Réussi",
    settingsLastTestFailed: "Échoué",
    settingsLastTestNeedsSetup: "Nécessite configuration",
    settingsFocused: "Focalisé",
    settingsBalancedContext: "Standard",
    settingsFullContext: "Étendu",
    settingsSaveCoachDefaults: "Enregistrer les valeurs du coach",
    globalPlanLabel: "Plan global",
    globalPlanRelationship: "Plan global -> Plan du projet actuel",
    globalPlanNotCreated: "Non cr\u00e9\u00e9",
    globalPlanNotLinked: "Le projet actuel n'est pas li\u00e9",
    globalPlanLinked: "Li\u00e9 au projet actuel",
    globalPlanCreate: "Cr\u00e9er le plan global",
    globalPlanLinkCurrentProject: "Lier le plan du projet actuel",
    globalPlanLinkUnavailable: "Cr\u00e9ez d'abord un plan pour le projet actuel",
    globalPlanFrozen: "Le plan global est gel\u00e9",
    evidenceConfidence: "Confiance",
    evidenceGovernance: "Gouvernance des preuves",
    evidenceFilterAll: "Tout",
    evidenceFilterDeferred: "Diff\u00e9r\u00e9",
    evidenceFilterAdopted: "Adopt\u00e9",
    evidenceFilterRejected: "Rejet\u00e9",
    evidenceAdopt: "Adopter",
    evidenceDefer: "Reporter",
    evidenceTargetPrefix: "Cible",
    evidenceNoMatches: "Aucune preuve ne correspond \u00e0 ce filtre.",
  },

  // ==========================================================================
  // Deutsch (德国)
  // ==========================================================================
  "de-DE": {
    settingsStatusRegionLabel: "Aktueller Status",
    settingsStatusConnected: "Verbunden",
    settingsStatusNotConnected: "Nicht verbunden",
    settingsStatusLanguage: "Sprache",
    settingsStatusMemory: "Gedächtnis",
    settingsStatusNoApiKey: "API-Key fehlt",
    settingsStatusNeedsTest: "Verbindung ungetestet",
    settingsStatusTrust: "Workspace nicht vertraut",
    settingsStatusUnsaved: "Ungespeicherte Änderungen",
    settingsSectionConnection: "Verbindung",
    settingsTeachingPrefs: "Unterrichtspräferenzen",
    settingsAnswerStyle: "Antwortstil",
    answerStyleSimple: "Einfach",
    answerStyleBalanced: "Ausgewogen",
    answerStyleDeep: "Ausführlich",
    answerStyleCustom: "Benutzerdefiniert",
    settingsAnswerStyleHint: "Presets legen Kontexttiefe und Anhänge fest. Zum Anwenden speichern.",
    settingsAdvancedContext: "Erweiterter Kontext",
    settingsMemoryPrivacy: "Speicher & Datenschutz",
    settingsAdvanced: "Erweitert",
    coach: "Coach",
    coachArtifactFullDetails: "Vollständige Details",
    trainer: "Trainer",
    you: "Du",
    plan: "Plan",
    settings: "Einstellungen",
    chat: "Chat",
    workspace: "Arbeitsbereich",
    viewNavigation: "Trainer-Ansichten",
    currentFocus: "Aktueller Fokus",
    currentTask: "Aktuelle Aufgabe",
    latestReview: "Letzte Überprüfung",
    backgroundAnalysis: "Hintergrundanalyse",
    backgroundCoachWork: "Coach-Vorbereitung",
    firstLookBadge: "Projektüberblick",
    firstLookProjectType: "Projekttyp",
    firstLookFolderRole: "Ordnerrolle",
    firstLookWhyGuess: "Warum diese Vermutung",
    firstLookEntryPoints: "Einstiegspunkte",
    firstLookDirectoryAnchors: "Wichtige Stellen",
    firstLookCoreModules: "Kernmodule / Materialien",
    firstLookRiskZones: "Risikobereiche",
    firstLookOpportunities: "Übungsmöglichkeiten",
    firstLookUnknowns: "Unbekanntes",
    firstLookNextStep: "Nächster Schritt",
    workspaceAdmissionRootMissing: "Arbeitsbereich-Stamm fehlt",
    workspaceAdmissionRootMissingDetail: "Wählen Sie zuerst, wo Trainer Lernaufzeichnungen speichert, und entscheiden Sie dann über dieses Projekt.",
    workspaceAdmissionGoalSaved: "Ihr Ziel steht noch im Eingabefeld. Wählen Sie den Speicherort und senden Sie es danach direkt.",
    workspaceAdmissionProjectFound: "Projekt gefunden",
    workspaceAdmissionProjectFoundDetail: "Wählen Sie: Zu Trainer hinzufügen, Nur ansehen oder Ignorieren.",
    workspaceAdmissionManaged: "Von Trainer verwaltet",
    workspaceAdmissionManagedDetail: "Unterhaltung, Plan und Lernaufzeichnungen dieses Projekts werden getrennt geführt.",
    workspaceAdmissionBrowse: "Nur ansehen",
    workspaceAdmissionBrowseDetail: "Sie können dieses Projekt ansehen, aber Coaching und gespeicherte Lernaufzeichnungen bleiben aus.",
    workspaceAdmissionIgnored: "Ignoriert",
    workspaceAdmissionIgnoredDetail: "Trainer wird dieses Projekt weder lesen noch verwalten. Sie können es später hinzufügen.",
    workspaceAdmissionProjectName: "Projekt",
    workspaceAdmissionProjectPath: "Pfad",
    workspaceAdmissionSelectRoot: "Arbeitsbereich-Stamm wählen",
    workspaceAdmissionSelectProject: "Projektordner wählen",
    workspaceAdmissionAdd: "Zu Trainer hinzufügen",
    workspaceAdmissionBrowseAction: "Nur ansehen",
    workspaceAdmissionIgnore: "Projekt ignorieren",
    workspaceAdmissionDelete: "Projekt löschen",
    workspaceRootControl: "Trainer-Arbeitsbereich",
    workspaceRootReady: "Lernaufzeichnungen werden in diesem Arbeitsbereich gespeichert.",
    workspaceRootPath: "Stammordner",
    workspaceRootMigrate: "Arbeitsbereich migrieren",
    workspaceRootMigrateDetail: "In einen neuen leeren Ordner kopieren und vom neuen Stamm fortfahren.",
    workspaceRootRecovery: "Sicherung und Wiederherstellung",
    workspaceRootBackup: "Arbeitsbereich sichern",
    workspaceRootBackupDetail: "Erstellt eine wiederherstellbare Kopie ohne den aktiven Stamm zu ändern.",
    workspaceRootRestore: "Sicherung wiederherstellen",
    workspaceRootRestoreDetail: "In einen neuen leeren Ordner wiederherstellen und ihn aktivieren.",
    workspaceRootChange: "Stamm ändern",
    workspaceRootChangeDetail: "Einen anderen Stamm ohne Kopie der aktuellen Daten auswählen.",
    coachState: "Coach-Status",
    coachSignal: "Lernsignal",
    reviewQueue: "Überprüfungswarteschlange",
    runReview: "Wiederholung starten",
    reviewMemory: "Gedächtnis & Rhythmus",
    reviewRhythm: "Überprüfungsrhythmus",
    nextReview: "Nächste Überprüfung",
    teachingObservations: "Pädagogische Beobachtungen",
    coachSummaryDoing: "In Arbeit",
    goals: "Ziele",
    constraints: "Einschränkungen",
    acceptance: "Akzeptanzkriterien",
    nextMove: "Nächster Schritt",
    recentWins: "Letzte Erfolge",
    weakSpots: "Schwachstellen",
    planStages: "Phasen",
    trainingWhyNow: "Warum jetzt",
    trainingDeliverable: "Abgabe",
    planStageMaterialsTitle: "Lernmaterialien",
    planStageMaterialsGenerate: "Materialien erstellen",
    planStageMaterialsGenerating: "Wird erstellt…",
    planStageMaterialsView: "Anzeigen",
    planStageMaterialsHide: "Ausblenden",
    planStageMaterialsEmpty: "Für diese Phase gibt es noch keine Lernmaterialien.",
    planStageCompletionLabel: "Phasenfortschritt",
    planStageMaterialsBadgeTitle: "Materialien erstellt",
    planDashboardTabPlan: "Plan",
    planDashboardTabProgress: "Fortschritt",
    planDashboardStagesTitle: "Phasen-Abschluss",
    planDashboardMasteryTitle: "Abhängigkeits-Beherrschung",
    planDashboardReviewTitle: "FSRS-Wiederholungsrate",
    planDashboardMaterialsTitle: "Materialnutzung",
    planDashboardMaterialsStages: "Abgedeckte Phasen",
    planDashboardMasteryEmpty: "Noch keine Beherrschungsdaten. Sie sammeln sich mit jeder abgeschlossenen Trainingskarte.",
    planDashboardReviewDue: "Fällig",
    planDashboardReviewDone: "Erledigt",
    planDashboardEmptyTitle: "Zuerst einen Plan erstellen",
    trainingHandoffMismatchHint: "Diese Karte passt nicht zum aktuellen Trainings-Handoff. Wechseln Sie zur Karte, die den Handoff besitzt.",
    trainingSwitchToCard: "Zu dieser Karte wechseln",
    trainingCardDetailsApiHints: "API-Hinweise",
    trainingCardDetailsSelfCheck: "Selbstprüfung",
    trainingCardDetailsRubric: "Bewertungsraster",
    trainingCardDetailsAcceptance: "Abnahmekriterien",
    language: "Sprache",
    answerMode: "Antwortmodus",
    teachingStyle: "Lehrstil",
    teachingGuided: "Geführt",
    teachingConceptFirst: "Konzept zuerst",
    teachingHandsOn: "Praktisch zuerst",
    teachingChallenging: "Herausfordernd",
    contextDetail: "Kontextdetail",
    coachFirst: "Geführt",
    balanced: "Ausgewogen",
    direct: "Direkt",
    detailFocused: "Fokussiert",
    detailBalanced: "Standard",
    detailFull: "Vollständig",
    attachments: "Anhänge",
    currentContext: "Aktueller Kontext",
    allContext: "Voller Kontext",
    noContext: "Kein Kontext",
    file: "Datei",
    selection: "Auswahl",
    diagnostics: "Diagnosen",
    relatedFiles: "Zugehörige Dateien",
    follow: "Live-Verfolgung",
    theme: "Thema",
    system: "System",
    light: "Hell",
    dark: "Dunkel",
    provider: "Anbieter",
    protocol: "Protokoll",
    baseUrl: "Basis-URL",
    chatModel: "Modell",
    apiKey: "API-Schlüssel",
    apiKeySaved: "Gespeichert",
    apiKeyMissing: "Nicht konfiguriert",
    saveProvider: "Speichern",
    testProvider: "Verbindung testen",
    clearProvider: "Löschen",
    openConfigFile: "Datei öffnen",
    configured: "Konfiguriert",
    notConfigured: "Nicht konfiguriert",
    refreshProviderProfiles: "Profile aktualisieren",
    refreshWorkspaceAuthority: "Autorität aktualisieren",
    createProfileFromTemplate: "Aus Vorlage erstellen",
    settingsSetupSection: "Modellverbindung",
    settingsSetupTitleReady: "Trainer ist bereit",
    settingsSetupTitleBlocked: "Ohne API-Schlüssel kann Trainer nicht starten",
    settingsSetupDetailReady: "Modellverbindung hergestellt. Du kannst jetzt chatten, planen und lernen.",
    settingsSetupDetailBlocked: "Speichere Anbieter, URL, Modell und API-Schlüssel. Nur so kann Trainer arbeiten.",
    settingsSetupAction: "Konfiguration abschließen",
    settingsInterfaceSection: "Wie Trainer dich führt",
    settingsCoachSection: "Standardkontext pro Runde",
    settingsModelSection: "Modell verbinden",
    settingsFollowCurrentFile: "Live-Verfolgung",
    settingsContextMode: "Kontextebene",
    settingsCurrentFile: "Aktuelle Datei",
    settingsConnectionDetails: "Verbindungsdetails",
    settingsLongTermMemory: "Langzeitgedächtnis",
    settingsMemoryScope: "Gedächtnisreichweite",
    settingsMemoryScopeProject: "Aktuelles Projekt",
    settingsMemoryScopePersonal: "Persönlich通用",
    settingsMemoryScopeSession: "Aktuelle Sitzung",
    settingsRememberDecisions: "Architekturentscheidungen",
    settingsRememberPatterns: "Häufige Muster",
    settingsRememberResources: "Referenzen",
    settingsWorkingSet: "Arbeitsmenge",
    settingsWorkingSetFocused: "Nur aktuelle Aufgabe",
    settingsWorkingSetBalanced: "Nahe Dateien",
    settingsWorkingSetBroad: "Breitere Referenzen",
    settingsMemoryPreview: "Prioritäre Beibehaltung",
    settingsMemoryPreviewEmpty: "Folgt aktuell Datei, Auswahl und Diagnosen.",
    settingsTeachingSignal: "Lernsignal",
    settingsConfigFileNote: "Sie brauchen mehr Einstellungen? Sie können sie in der Konfigurationsdatei anpassen.",
    settingsContextSection: "Angehängter Kontext",
    settingsMemoryRuntime: "Hintergrundbetrieb",
    settingsMemoryRuntimeDetail: "Gedächtnis, Überprüfung und Rhythmus aktualisieren sich automatisch.",
    settingsAdvancedSection: "Weitere Standardstrategien",
    settingsAdvancedIntro: "Hier musst du selten etwas ändern. Erweitere nur, wenn du ändern möchtest, wie Trainer fortfährt und sich erinnert.",
    settingsReviewRhythmPace: "Erinnerungsintensität",
    settingsReviewRhythmReminder: "Erinnerungsstrategie",
    settingsReviewStrategy: "Überprüfungsstrategie",
    settingsSystemActions: "Zustand organisieren",
    settingsRefreshMemory: "Gedächtnis aktualisieren",
    settingsResetDefaults: "Standardwerte wiederherstellen",
    settingsModelTools: "Verbindungstools",
    settingsDefaultsHint: "Definiere, wie Trainer spricht und dich führt. Die meisten Gespräche folgen diesem Rhythmus.",
    settingsContextHint: "Definiert nur die Standardanhänge pro Runde.",
    settingsModelHint: "Verwaltet nur die Verbindung. Das echte Coaching kommt von Plan und Kontinuität.",
    settingsAvailableModels: "Verfügbare Modelle",
    settingsDetectedModel: "Erkanntes Modell",
    settingsModelFetchLoading: "Lade Modelle…",
    settingsModelFetchEmpty: "Liste lädt automatisch nach API-Schlüssel-Speicherung.",
    settingsRefreshModels: "Liste aktualisieren",
    settingsModelCache: "Modell-Cache-Status",
    settingsModelCacheSource: "Quelle",
    settingsModelCacheFetchedAt: "Abgerufen um",
    settingsModelCacheExpiresAt: "Läuft ab um",
    settingsModelCacheStatus: "Status",
    settingsModelCacheError: "Fehlergrund",
    settingsModelCacheSourceLive: "Live",
    settingsModelCacheSourceCache: "Cache",
    settingsModelCacheStatusFresh: "Aktuell",
    settingsModelCacheStatusExpired: "Abgelaufen",
    settingsModelCacheStatusUnknown: "Unbekannt",
    settingsModelCacheStatusLoading: "Laden",
    settingsModelCacheStatusError: "Fehler",
    settingsRuntimeSection: "Aktuelle Coach-Laufzeit",
    settingsRuntimeHint: "Beschreibt, welchen Thread Trainer fortsetzen würde.",
    settingsMemoryStrategy: "Gedächtnisstrategie",
    settingsMemoryStrategyHint: "Kontrolliert, was Trainer sich merkt und ob diese Erinnerungen in diesem Projekt bleiben.",
    settingsReviewStrategyHint: "Kontrolliert, wie oft Trainer zur Überprüfung auffordert.",
    settingsContextCurrentFileHint: "Priorität auf die Datei, die du bearbeitest.",
    settingsContextSelectionHint: "Berücksichtigt aktuelle Auswahl.",
    settingsContextDiagnosticsHint: "Fügt Diagnosen für Überprüfungen hinzu.",
    settingsContextRelatedFilesHint: "Bringt zugehörige Dateien nur wenn nötig.",
    settingsMemoryScopeRuntimeProject: "Bleibt im aktuellen Projekt.",
    settingsMemoryScopeRuntimePersonal: "Pflegt Präferenzen projektübergreifend.",
    settingsMemoryScopeRuntimeSession: "Bleibt in der aktuellen Sitzung.",
    settingsMemoryScopeProjectHint: "Halte Thread und Urteil im aktuellen Projekt.",
    settingsMemoryScopePersonalHint: "Bringe Gewohnheiten in andere Projekte.",
    settingsMemoryScopeSessionHint: "Lokales Gedächtnis nur für aktuelles Gespräch.",
    settingsWorkingSetFocusedHint: "Bleib im kleinsten überprüfbaren Fragment.",
    settingsWorkingSetBalancedHint: "Ausgewogener Kontext für die meisten Code-Runden.",
    settingsWorkingSetBroadHint: "Erlaubt breiteren Kontext wenn nötig.",
    settingsReviewCadenceLightHint: "Unterbricht seltener.",
    settingsReviewCadenceSteadyHint: "Normaler Trainingsrhythmus.",
    settingsReviewCadenceActiveHint: "Häufigere Überprüfungen.",
    settingsReviewReminderDueHint: "Erinnert hauptsächlich bei Fälligkeit.",
    settingsReviewReminderAheadHint: "Warnt vor Fälligkeit.",
    settingsReviewReminderDigestHint: "Gruppiert naheliegende Überprüfungen.",
    settingsSavedState: "Gespeichert",
    settingsUnsavedState: "Nicht gespeichert",
    settingsEmptyState: "Nicht in Workspace geschrieben",
    settingsEffectiveNow: "Sofort wirksam",
    settingsSavedInWorkspace: "Im Workspace gespeichert",
    settingsEditingDraft: "Bearbeitung läuft",
    settingsCurrentWorkspace: "Aktueller Workspace",
    settingsLocalThemeNote: "Thema betrifft nur das, was du siehst.",
    settingsWorkspaceSaveNote: "Speichern der Coach-Werte speichert auch Workspace-Ebene.",
    settingsProviderRuntimeNote: "Test verwendet aktive Konfiguration im Workspace.",
    settingsLatestAction: "Letzte Aktion",
    settingsLastTest: "Letzter Test",
    settingsLastTestNever: "Nie getestet",
    settingsLastTestPassed: "Bestanden",
    settingsLastTestFailed: "Fehlgeschlagen",
    settingsLastTestNeedsSetup: "Benötigt Konfiguration",
    settingsFocused: "Fokussiert",
    settingsBalancedContext: "Standard",
    settingsFullContext: "Erweitert",
    settingsSaveCoachDefaults: "Coach-Werte speichern",
    globalPlanLabel: "Gesamtplan",
    globalPlanRelationship: "Gesamtplan -> Plan des aktuellen Projekts",
    globalPlanNotCreated: "Noch nicht erstellt",
    globalPlanNotLinked: "Aktuelles Projekt ist nicht verkn\u00fcpft",
    globalPlanLinked: "Mit aktuellem Projekt verkn\u00fcpft",
    globalPlanCreate: "Gesamtplan erstellen",
    globalPlanLinkCurrentProject: "Plan des aktuellen Projekts verkn\u00fcpfen",
    globalPlanLinkUnavailable: "Erstellen Sie zuerst einen Plan f\u00fcr das aktuelle Projekt",
    globalPlanFrozen: "Gesamtplan ist eingefroren",
    evidenceConfidence: "Konfidenz",
    evidenceGovernance: "Evidenzsteuerung",
    evidenceFilterAll: "Alle",
    evidenceFilterDeferred: "Zur\u00fcckgestellt",
    evidenceFilterAdopted: "\u00dcbernommen",
    evidenceFilterRejected: "Abgelehnt",
    evidenceAdopt: "\u00dcbernehmen",
    evidenceDefer: "Verschieben",
    evidenceTargetPrefix: "Ziel",
    evidenceNoMatches: "Keine Evidenz passt zu diesem Filter.",
  },

  // ==========================================================================
  // 日本語 (日本)
  // ==========================================================================
  "ja-JP": {
    settingsStatusRegionLabel: "現在の状態",
    settingsStatusConnected: "接続済み",
    settingsStatusNotConnected: "未接続",
    settingsStatusLanguage: "言語",
    settingsStatusMemory: "記憶",
    settingsStatusNoApiKey: "APIキーが未設定",
    settingsStatusNeedsTest: "接続未テスト",
    settingsStatusTrust: "ワークスペース未信頼",
    settingsStatusUnsaved: "未保存の変更があります",
    settingsSectionConnection: "接続",
    settingsTeachingPrefs: "指導の設定",
    settingsAnswerStyle: "回答スタイル",
    answerStyleSimple: "かんたん",
    answerStyleBalanced: "バランス",
    answerStyleDeep: "詳細",
    answerStyleCustom: "カスタム",
    settingsAnswerStyleHint: "プリセットはコンテキストの深さと添付を決めます。保存で適用されます。",
    settingsAdvancedContext: "詳細コンテキスト",
    settingsMemoryPrivacy: "記憶とプライバシー",
    settingsAdvanced: "詳細",
    coach: "コーチ",
    coachArtifactFullDetails: "詳細を表示",
    trainer: "トレーナー",
    you: "あなた",
    plan: "計画",
    settings: "設定",
    chat: "チャット",
    workspace: "ワークスペース",
    viewNavigation: "Trainer のビュー",
    currentFocus: "現在の焦点",
    currentTask: "現在のタスク",
    latestReview: "最新の復習",
    backgroundAnalysis: "バックグラウンド分析",
    backgroundCoachWork: "Coach準備",
    firstLookBadge: "プロジェクト概要",
    firstLookProjectType: "プロジェクト種別",
    firstLookFolderRole: "フォルダの役割",
    firstLookWhyGuess: "そう判断した理由",
    firstLookEntryPoints: "入口",
    firstLookDirectoryAnchors: "重要な場所",
    firstLookCoreModules: "主要モジュール / 資料",
    firstLookRiskZones: "リスク領域",
    firstLookOpportunities: "学習機会",
    firstLookUnknowns: "未確認項目",
    firstLookNextStep: "次の一手",
    workspaceAdmissionRootMissing: "ワークスペースのルートが未設定です",
    workspaceAdmissionRootMissingDetail: "このプロジェクトの扱いを決める前に、学習記録の保存場所を選択してください。",
    workspaceAdmissionGoalSaved: "目標は入力欄に残っています。保存場所を選んだ後、そのまま送信できます。",
    workspaceAdmissionProjectFound: "プロジェクトを検出しました",
    workspaceAdmissionProjectFoundDetail: "Trainer に追加、閲覧のみ、または無視を選んでください。",
    workspaceAdmissionManaged: "Trainer で管理中",
    workspaceAdmissionManagedDetail: "このプロジェクトの会話、計画、学習記録は別々に保存されます。",
    workspaceAdmissionBrowse: "閲覧のみ",
    workspaceAdmissionBrowseDetail: "このプロジェクトは確認できますが、コーチングと学習記録の保存は行われません。",
    workspaceAdmissionIgnored: "無視済み",
    workspaceAdmissionIgnoredDetail: "Trainer はこのプロジェクトを読み込まず、管理もしません。後で追加できます。",
    workspaceAdmissionProjectName: "プロジェクト",
    workspaceAdmissionProjectPath: "パス",
    workspaceAdmissionSelectRoot: "ワークスペースのルートを選択",
    workspaceAdmissionSelectProject: "プロジェクトフォルダーを選択",
    workspaceAdmissionAdd: "Trainer に追加",
    workspaceAdmissionBrowseAction: "閲覧のみ",
    workspaceAdmissionIgnore: "プロジェクトを無視",
    workspaceAdmissionDelete: "プロジェクトを削除",
    workspaceRootControl: "Trainer ワークスペース",
    workspaceRootReady: "学習記録はこのワークスペースに保存されます。",
    workspaceRootPath: "ルート",
    workspaceRootMigrate: "ワークスペースを移行",
    workspaceRootMigrateDetail: "新しい空のフォルダーへコピーし、新しいルートから続行します。",
    workspaceRootRecovery: "バックアップと復元",
    workspaceRootBackup: "ワークスペースをバックアップ",
    workspaceRootBackupDetail: "現在のルートを変えずに復元可能なコピーを作成します。",
    workspaceRootRestore: "バックアップを復元",
    workspaceRootRestoreDetail: "新しい空のフォルダーへ復元し、現在のルートにします。",
    workspaceRootChange: "ルートを変更",
    workspaceRootChangeDetail: "現在のデータをコピーせず別のルートを選びます。",
    coachState: "Coach状態",
    coachSignal: "学習シグナル",
    reviewQueue: "復習キュー",
    runReview: "復習を始める",
    reviewMemory: "記憶とリズム",
    reviewRhythm: "復習リズム",
    nextReview: "次の復習",
    teachingObservations: "教育観察",
    coachSummaryDoing: "進行中",
    goals: "目標",
    constraints: "制約",
    acceptance: "受入基準",
    nextMove: "次のアクション",
    recentWins: "最近の成果",
    weakSpots: "弱点",
    planStages: "ステージ",
    trainingWhyNow: "なぜ今か",
    trainingDeliverable: "成果物",
    planStageMaterialsTitle: "学習資料",
    planStageMaterialsGenerate: "資料を生成",
    planStageMaterialsGenerating: "生成中…",
    planStageMaterialsView: "表示",
    planStageMaterialsHide: "閉じる",
    planStageMaterialsEmpty: "このステージにはまだ学習資料がありません。",
    planStageCompletionLabel: "ステージ完了度",
    planStageMaterialsBadgeTitle: "資料の生成状況",
    planDashboardTabPlan: "計画",
    planDashboardTabProgress: "進捗",
    planDashboardStagesTitle: "ステージ完了度",
    planDashboardMasteryTitle: "依存の習熟度",
    planDashboardReviewTitle: "FSRS 復習定着率",
    planDashboardMaterialsTitle: "資料の使用回数",
    planDashboardMaterialsStages: "対象ステージ",
    planDashboardMasteryEmpty: "まだ習熟度データがありません。トレーニングカードを完了すると蓄積されます。",
    planDashboardReviewDue: "期限",
    planDashboardReviewDone: "完了",
    planDashboardEmptyTitle: "先に計画を生成",
    trainingHandoffMismatchHint: "このカードは現在のトレーニング引き継ぎと一致しません。引き継ぎを所有するカードに切り替えてください。",
    trainingSwitchToCard: "該当カードへ切り替え",
    trainingCardDetailsApiHints: "API ヒント",
    trainingCardDetailsSelfCheck: "セルフチェック",
    trainingCardDetailsRubric: "採点基準",
    trainingCardDetailsAcceptance: "合格基準",
    language: "言語",
    answerMode: "回答モード",
    teachingStyle: "Teachingスタイル",
    teachingGuided: "ガイド付き",
    teachingConceptFirst: "概念先行",
    teachingHandsOn: "実践優先",
    teachingChallenging: "挑戦的",
    contextDetail: "コンテキスト詳細",
    coachFirst: "ガイド",
    balanced: "バランス",
    direct: "直接",
    detailFocused: "フォーカス",
    detailBalanced: "標準",
    detailFull: "完全",
    attachments: "添付ファイル",
    currentContext: "現在のコンテキスト",
    allContext: "全コンテキスト",
    noContext: "コンテキストなし",
    file: "ファイル",
    selection: "選択",
    diagnostics: "診断",
    relatedFiles: "関連ファイル",
    follow: "ライブフォロー",
    theme: "テーマ",
    system: "システム",
    light: "ライト",
    dark: "ダーク",
    provider: "プロバイダー",
    protocol: "プロトコル",
    baseUrl: "ベースURL",
    chatModel: "モデル",
    apiKey: "APIキー",
    apiKeySaved: "保存済み",
    apiKeyMissing: "未設定",
    saveProvider: "保存",
    testProvider: "接続テスト",
    clearProvider: "クリア",
    openConfigFile: "ファイルを開く",
    configured: "設定済み",
    notConfigured: "未設定",
    refreshProviderProfiles: "プロファイルを更新",
    refreshWorkspaceAuthority: "権限を更新",
    createProfileFromTemplate: "テンプレートから作成",
    settingsSetupSection: "モデル接続",
    settingsSetupTitleReady: "Trainer準備完了",
    settingsSetupTitleBlocked: "APIキーなしでTrainerは開始できません",
    settingsSetupDetailReady: "モデル接続準備完了。チャット、計画、学習を始められます。",
    settingsSetupDetailBlocked: "プロバイダー、URL、モデル、APIキーを保存してください。",
    settingsSetupAction: "設定を完了",
    settingsInterfaceSection: "Trainerのガイド方法",
    settingsCoachSection: "ターンごとのデフォルトコンテキスト",
    settingsModelSection: "モデル接続",
    settingsFollowCurrentFile: "ライブフォロー",
    settingsContextMode: "コンテキストレベル",
    settingsCurrentFile: "現在のファイル",
    settingsConnectionDetails: "接続詳細",
    settingsLongTermMemory: "長期記憶",
    settingsMemoryScope: "記憶範囲",
    settingsMemoryScopeProject: "現在のプロジェクト",
    settingsMemoryScopePersonal: "個人汎用",
    settingsMemoryScopeSession: "現在のセッション",
    settingsRememberDecisions: "アーキテクチャ決定",
    settingsRememberPatterns: "共通パターン",
    settingsRememberResources: "参考资料",
    settingsWorkingSet: "作業セット",
    settingsWorkingSetFocused: "現在のタスクのみ",
    settingsWorkingSetBalanced: "近くのファイル",
    settingsWorkingSetBroad: "より広い参照",
    settingsMemoryPreview: "優先保持",
    settingsMemoryPreviewEmpty: "現在ファイル、選択、診断をフォロー中。",
    settingsTeachingSignal: "学習シグナル",
    settingsConfigFileNote: "さらに細かく調整したいときは、設定ファイルで変更できます。",
    settingsContextSection: "添付コンテキスト",
    settingsMemoryRuntime: "バックグラウンド実行",
    settingsMemoryRuntimeDetail: "記憶、復習、教育リズムは各ターンで自動更新。",
    settingsAdvancedSection: "追加のデフォルト戦略",
    settingsAdvancedIntro: "これらのオプションは頻繁に変更不要。Trainerの継続、記憶、コンテキスト取得方法を変更したい時のみ展開。",
    settingsReviewRhythmPace: "リマインダー強度",
    settingsReviewRhythmReminder: "リマインダー戦略",
    settingsReviewStrategy: "復習戦略",
    settingsSystemActions: "現在の状態を整理",
    settingsRefreshMemory: "記憶を更新",
    settingsResetDefaults: "デフォルトを復元",
    settingsModelTools: "接続ツール",
    settingsDefaultsHint: "Trainerがどのように話し、あなたをガイドするかを定義。",
    settingsContextHint: "ターンごとのデフォルト添付ファイルのみ設定。",
    settingsModelHint: "接続のみ処理。真のCoachは計画と継続性から。",
    settingsAvailableModels: "利用可能なモデル",
    settingsDetectedModel: "検出されたモデル",
    settingsModelFetchLoading: "モデル取得中…",
    settingsModelFetchEmpty: "APIキー保存後自動取得。",
    settingsRefreshModels: "リストを更新",
    settingsModelCache: "モデルキャッシュ状態",
    settingsModelCacheSource: "ソース",
    settingsModelCacheFetchedAt: "取得時刻",
    settingsModelCacheExpiresAt: "期限切れ時刻",
    settingsModelCacheStatus: "状態",
    settingsModelCacheError: "エラー理由",
    settingsModelCacheSourceLive: "ライブ取得",
    settingsModelCacheSourceCache: "キャッシュ",
    settingsModelCacheStatusFresh: "有効",
    settingsModelCacheStatusExpired: "期限切れ",
    settingsModelCacheStatusUnknown: "不明",
    settingsModelCacheStatusLoading: "取得中",
    settingsModelCacheStatusError: "エラー",
    settingsRuntimeSection: "現在のCoachランタイム",
    settingsRuntimeHint: "今メッセージを送った場合の継続スレッドを説明。",
    settingsMemoryStrategy: "記憶戦略",
    settingsMemoryStrategyHint: "Trainerが何を持ち越すか、このプロジェクトに残すかを制御。",
    settingsReviewStrategyHint: "Trainerがどのくらいの頻度で復習を求めるか、通知の邪魔さを制御。",
    settingsContextCurrentFileHint: " активно編集中のファイルを優先。",
    settingsContextSelectionHint: "現在の選択を含める。",
    settingsContextDiagnosticsHint: "復習やデバッグに診断を添付。",
    settingsContextRelatedFilesHint: "本当に必要時のみ関連ファイルを取得。",
    settingsMemoryScopeRuntimeProject: "現在のプロジェクト的计划、スレッド、リソースに従う。",
    settingsMemoryScopeRuntimePersonal: "プロジェクト間で偏好、 판단、训练足跡を維持。",
    settingsMemoryScopeRuntimeSession: "現在のセッション スレッド内に留まる。",
    settingsMemoryScopeProjectHint: "スレッドと判断を現在のプロジェクト内に維持。",
    settingsMemoryScopePersonalHint: " hábitoと判断を他のプロジェクトに携带。",
    settingsMemoryScopeSessionHint: "現在の会話のみローカル記憶。",
    settingsWorkingSetFocusedHint: "最小の検証可能なフラグメントと近くのファイルに留まる。",
    settingsWorkingSetBalancedHint: "現在のフラグメントと近くのコンテキストをバランス。",
    settingsWorkingSetBroadHint: "検証に必要な場合により広いコンテキストを許可。",
    settingsReviewCadenceLightHint: "重要な復習ポイントを維持しながら中断を减少。",
    settingsReviewCadenceSteadyHint: "通常のトレーニングリズム。",
    settingsReviewCadenceActiveHint: "短期間のスプリントでより頻繁に復習。",
    settingsReviewReminderDueHint: "復習が実際に期限を迎えた時のみリマインダー。",
    settingsReviewReminderAheadHint: "期限前に警告を送信。",
    settingsReviewReminderDigestHint: "近い復習を1つのダイジェストにグループ化。",
    settingsSavedState: "保存済み",
    settingsUnsavedState: "未保存",
    settingsEmptyState: "ワークスペースに未書き込み",
    settingsEffectiveNow: "即時有効",
    settingsSavedInWorkspace: "ワークスペースに保存済み",
    settingsEditingDraft: "編集中",
    settingsCurrentWorkspace: "現在のワークスペース",
    settingsLocalThemeNote: "テーマは今見ているものにのみ影響。",
    settingsWorkspaceSaveNote: "Coachデフォルト値を保存するとワークスペースレベルのコントロールも保存。",
    settingsProviderRuntimeNote: "接続テストは今ワークスペースでアクティブなprovider設定を使用。",
    settingsLatestAction: "最近のアクション",
    settingsLastTest: "最後のテスト",
    settingsLastTestNever: "未テスト",
    settingsLastTestPassed: "成功",
    settingsLastTestFailed: "失敗",
    settingsLastTestNeedsSetup: "設定が必要",
    settingsFocused: "フォーカス",
    settingsBalancedContext: "標準",
    settingsFullContext: "拡張",
    settingsSaveCoachDefaults: "Coachデフォルト値を保存",
    globalPlanLabel: "\u5168\u4f53\u8a08\u753b",
    globalPlanRelationship: "\u5168\u4f53\u8a08\u753b -> \u73fe\u5728\u306e\u30d7\u30ed\u30b8\u30a7\u30af\u30c8\u8a08\u753b",
    globalPlanNotCreated: "\u672a\u4f5c\u6210",
    globalPlanNotLinked: "\u73fe\u5728\u306e\u30d7\u30ed\u30b8\u30a7\u30af\u30c8\u306f\u672a\u95a2\u9023",
    globalPlanLinked: "\u73fe\u5728\u306e\u30d7\u30ed\u30b8\u30a7\u30af\u30c8\u306b\u95a2\u9023\u4ed8\u3051\u6e08\u307f",
    globalPlanCreate: "\u5168\u4f53\u8a08\u753b\u3092\u4f5c\u6210",
    globalPlanLinkCurrentProject: "\u73fe\u5728\u306e\u30d7\u30ed\u30b8\u30a7\u30af\u30c8\u8a08\u753b\u3092\u95a2\u9023\u4ed8\u3051",
    globalPlanLinkUnavailable: "\u5148\u306b\u73fe\u5728\u306e\u30d7\u30ed\u30b8\u30a7\u30af\u30c8\u8a08\u753b\u3092\u4f5c\u6210\u3057\u3066\u304f\u3060\u3055\u3044",
    globalPlanFrozen: "\u5168\u4f53\u8a08\u753b\u306f\u51cd\u7d50\u3055\u308c\u3066\u3044\u307e\u3059",
    evidenceConfidence: "\u4fe1\u983c\u5ea6",
    evidenceGovernance: "\u8a3c\u64da\u7ba1\u7406",
    evidenceFilterAll: "\u3059\u3079\u3066",
    evidenceFilterDeferred: "\u5ef6\u671f",
    evidenceFilterAdopted: "\u63a1\u7528\u6e08\u307f",
    evidenceFilterRejected: "\u5374\u4e0b\u6e08\u307f",
    evidenceAdopt: "\u63a1\u7528",
    evidenceDefer: "\u5ef6\u671f",
    evidenceTargetPrefix: "\u5bfe\u8c61",
    evidenceNoMatches: "\u3053\u306e\u30d5\u30a3\u30eb\u30bf\u306b\u4e00\u81f4\u3059\u308b\u8a3c\u62e0\u306f\u3042\u308a\u307e\u305b\u3093\u3002",
  },

  // ==========================================================================
  // 한국어 (韩国)
  // ==========================================================================
  "ko-KR": {
    settingsStatusRegionLabel: "현재 상태",
    settingsStatusConnected: "연결됨",
    settingsStatusNotConnected: "연결 안 됨",
    settingsStatusLanguage: "언어",
    settingsStatusMemory: "기억",
    settingsStatusNoApiKey: "API 키 없음",
    settingsStatusNeedsTest: "연결 미테스트",
    settingsStatusTrust: "작업 영역 미신뢰",
    settingsStatusUnsaved: "저장하지 않은 변경 있음",
    settingsSectionConnection: "연결",
    settingsTeachingPrefs: "학습 취향",
    settingsAnswerStyle: "답변 스타일",
    answerStyleSimple: "간단",
    answerStyleBalanced: "균형",
    answerStyleDeep: "심층",
    answerStyleCustom: "사용자 지정",
    settingsAnswerStyleHint: "프리셋은 컨텍스트 깊이와 첨부를 결정합니다. 저장하여 적용하세요.",
    settingsAdvancedContext: "고급 컨텍스트",
    settingsMemoryPrivacy: "기억 및 개인정보",
    settingsAdvanced: "고급",
    coach: "코치",
    coachArtifactFullDetails: "전체 내용 보기",
    trainer: "트레이너",
    you: "너",
    plan: "계획",
    settings: "설정",
    chat: "챗",
    workspace: "워크스페이스",
    viewNavigation: "Trainer 보기",
    currentFocus: "현재 초점",
    currentTask: "현재 작업",
    latestReview: "최근 복습",
    backgroundAnalysis: "백그라운드 분석",
    backgroundCoachWork: "코치 준비",
    firstLookBadge: "프로젝트 개요",
    firstLookProjectType: "프로젝트 유형",
    firstLookFolderRole: "폴더 역할",
    firstLookWhyGuess: "이렇게 본 이유",
    firstLookEntryPoints: "진입점",
    firstLookDirectoryAnchors: "주요 위치",
    firstLookCoreModules: "핵심 모듈 / 자료",
    firstLookRiskZones: "위험 구역",
    firstLookOpportunities: "학습 기회",
    firstLookUnknowns: "미확인 항목",
    firstLookNextStep: "다음 단계",
    workspaceAdmissionRootMissing: "작업 영역 루트가 설정되지 않았습니다",
    workspaceAdmissionRootMissingDetail: "이 프로젝트의 처리 방식을 정하기 전에 학습 기록을 저장할 위치를 선택하세요.",
    workspaceAdmissionGoalSaved: "목표는 입력창에 남아 있습니다. 저장 위치를 고른 뒤 바로 보낼 수 있습니다.",
    workspaceAdmissionProjectFound: "프로젝트를 찾았습니다",
    workspaceAdmissionProjectFoundDetail: "Trainer에 추가, 둘러보기만 또는 무시를 선택하세요.",
    workspaceAdmissionManaged: "Trainer에서 관리 중",
    workspaceAdmissionManagedDetail: "이 프로젝트의 대화, 계획 및 학습 기록은 따로 보관됩니다.",
    workspaceAdmissionBrowse: "둘러보기만",
    workspaceAdmissionBrowseDetail: "이 프로젝트는 살펴볼 수 있지만 코칭과 학습 기록 저장은 꺼져 있습니다.",
    workspaceAdmissionIgnored: "무시됨",
    workspaceAdmissionIgnoredDetail: "Trainer는 이 프로젝트를 읽거나 관리하지 않습니다. 나중에 추가할 수 있습니다.",
    workspaceAdmissionProjectName: "프로젝트",
    workspaceAdmissionProjectPath: "경로",
    workspaceAdmissionSelectRoot: "작업 영역 루트 선택",
    workspaceAdmissionSelectProject: "프로젝트 폴더 선택",
    workspaceAdmissionAdd: "Trainer에 추가",
    workspaceAdmissionBrowseAction: "둘러보기만",
    workspaceAdmissionIgnore: "프로젝트 무시",
    workspaceAdmissionDelete: "프로젝트 삭제",
    workspaceRootControl: "Trainer 작업 영역",
    workspaceRootReady: "학습 기록은 이 작업 영역에 저장됩니다.",
    workspaceRootPath: "루트",
    workspaceRootMigrate: "작업 영역 마이그레이션",
    workspaceRootMigrateDetail: "새 빈 폴더로 복사하고 새 루트에서 계속합니다.",
    workspaceRootRecovery: "백업 및 복원",
    workspaceRootBackup: "작업 영역 백업",
    workspaceRootBackupDetail: "현재 루트를 바꾸지 않고 복구 가능한 사본을 만듭니다.",
    workspaceRootRestore: "백업 복원",
    workspaceRootRestoreDetail: "새 빈 폴더에 복원하고 활성 루트로 설정합니다.",
    workspaceRootChange: "루트 변경",
    workspaceRootChangeDetail: "현재 데이터를 복사하지 않고 다른 루트를 선택합니다.",
    coachState: "코치 상태",
    coachSignal: "학습 신호",
    reviewQueue: "복습 대기열",
    runReview: "복습 시작",
    reviewMemory: "기억과 리듬",
    reviewRhythm: "복습 리듬",
    nextReview: "다음 복습",
    teachingObservations: "교육 관찰",
    coachSummaryDoing: "진행 중",
    goals: "목표",
    constraints: "제약조건",
    acceptance: "수용 기준",
    nextMove: "다음 행동",
    recentWins: "최근 성과",
    weakSpots: "취약점",
    planStages: "단계",
    trainingWhyNow: "왜 지금",
    trainingDeliverable: "제출물",
    planStageMaterialsTitle: "학습 자료",
    planStageMaterialsGenerate: "자료 생성",
    planStageMaterialsGenerating: "생성 중…",
    planStageMaterialsView: "보기",
    planStageMaterialsHide: "접기",
    planStageMaterialsEmpty: "이 단계에는 아직 학습 자료가 없습니다.",
    planStageCompletionLabel: "단계 완료도",
    planStageMaterialsBadgeTitle: "자료 생성 현황",
    planDashboardTabPlan: "계획",
    planDashboardTabProgress: "진도",
    planDashboardStagesTitle: "단계 완료도",
    planDashboardMasteryTitle: "의존성 숙달도",
    planDashboardReviewTitle: "FSRS 복습 유지율",
    planDashboardMaterialsTitle: "자료 사용 횟수",
    planDashboardMaterialsStages: "커버한 단계",
    planDashboardMasteryEmpty: "아직 숙련도 데이터가 없습니다. 훈련 카드를 완료하면 쌓입니다.",
    planDashboardReviewDue: "예정",
    planDashboardReviewDone: "완료",
    planDashboardEmptyTitle: "먼저 계획을 생성하세요",
    trainingHandoffMismatchHint: "이 카드는 현재 훈련 인계와 일치하지 않습니다. 인계를 소유한 카드로 전환하세요.",
    trainingSwitchToCard: "해당 카드로 전환",
    trainingCardDetailsApiHints: "API 힌트",
    trainingCardDetailsSelfCheck: "셀프 체크",
    trainingCardDetailsRubric: "채점 기준",
    trainingCardDetailsAcceptance: "수용 기준",
    language: "언어",
    answerMode: "응답 모드",
    teachingStyle: "가이드 스타일",
    teachingGuided: "가이드형",
    teachingConceptFirst: "개념 우선",
    teachingHandsOn: "실습 우선",
    teachingChallenging: "도전형",
    contextDetail: "컨텍스트 상세",
    coachFirst: "가이드",
    balanced: "균형",
    direct: "직접",
    detailFocused: "집중",
    detailBalanced: "표준",
    detailFull: "완전",
    attachments: "첨부 파일",
    currentContext: "현재 컨텍스트",
    allContext: "전체 컨텍스트",
    noContext: "컨텍스트 없음",
    file: "파일",
    selection: "선택 영역",
    diagnostics: "진단",
    relatedFiles: "관련 파일",
    follow: "실시간 추적",
    theme: "테마",
    system: "시스템",
    light: "라이트",
    dark: "다크",
    provider: "제공자",
    protocol: "프로토콜",
    baseUrl: "기본 URL",
    chatModel: "모델",
    apiKey: "API 키",
    apiKeySaved: "저장됨",
    apiKeyMissing: "미설정",
    saveProvider: "저장",
    testProvider: "연결 테스트",
    clearProvider: "지우기",
    openConfigFile: "파일 열기",
    configured: "설정됨",
    notConfigured: "미설정",
    refreshProviderProfiles: "프로필 새로고침",
    refreshWorkspaceAuthority: "권한 새로고침",
    createProfileFromTemplate: "템플릿에서 생성",
    settingsSetupSection: "모델 연결",
    settingsSetupTitleReady: "Trainer 준비 완료",
    settingsSetupTitleBlocked: "API 키 없이는 Trainer 시작 불가",
    settingsSetupDetailReady: "모델 연결 준비 완료. 지금부터 챗, 계획, 학습 가능.",
    settingsSetupDetailBlocked: "제공자, URL, 모델, API 키를 저장하세요.",
    settingsSetupAction: "설정 완료",
    settingsInterfaceSection: "Trainer의 안내 방식",
    settingsCoachSection: "턴별 기본 컨텍스트",
    settingsModelSection: "모델 연결",
    settingsFollowCurrentFile: "실시간 추적",
    settingsContextMode: "컨텍스트 수준",
    settingsCurrentFile: "현재 파일",
    settingsConnectionDetails: "연결 세부정보",
    settingsLongTermMemory: "장기 기억",
    settingsMemoryScope: "기억 범위",
    settingsMemoryScopeProject: "현재 프로젝트",
    settingsMemoryScopePersonal: "개인 공통",
    settingsMemoryScopeSession: "현재 세션",
    settingsRememberDecisions: "아키텍처 결정",
    settingsRememberPatterns: "공통 패턴",
    settingsRememberResources: "참고 자료",
    settingsWorkingSet: "작업 세트",
    settingsWorkingSetFocused: "현재 작업만",
    settingsWorkingSetBalanced: "근처 파일",
    settingsWorkingSetBroad: "더 넓은 참조",
    settingsMemoryPreview: "우선 보존",
    settingsMemoryPreviewEmpty: "현재 파일, 선택 영역, 진단 추적 중.",
    settingsTeachingSignal: "학습 신호",
    settingsConfigFileNote: "더 자세히 조정하려면 설정 파일에서 바꿀 수 있습니다.",
    settingsContextSection: "첨부 컨텍스트",
    settingsMemoryRuntime: "백그라운드 실행",
    settingsMemoryRuntimeDetail: "기억, 복습, 교육 리듬이 각 턴마다 자동 업데이트.",
    settingsAdvancedSection: "추가 기본 전략",
    settingsAdvancedIntro: "이 옵션은 자주 변경할 필요 없음. Trainer의 연속성, 기억, 컨텍스트 가져오기 방식을 변경하려는 경우에만 확장.",
    settingsReviewRhythmPace: "리마인더 강도",
    settingsReviewRhythmReminder: "리마인더 전략",
    settingsReviewStrategy: "복습 전략",
    settingsSystemActions: "현재 상태 정리",
    settingsRefreshMemory: "기억 새로고침",
    settingsResetDefaults: "기본값 복원",
    settingsModelTools: "연결 도구",
    settingsDefaultsHint: "Trainer가 어떻게 말하고 안내할지 정의.",
    settingsContextHint: "턴별 기본 첨부 파일만 설정.",
    settingsModelHint: "연결만 처리. 진정한 코치는 계획과 연속성에서 옴.",
    settingsAvailableModels: "사용 가능한 모델",
    settingsDetectedModel: "감지된 모델",
    settingsModelFetchLoading: "모델 가져오는 중…",
    settingsModelFetchEmpty: "API 키 저장 후 자동 가져옴.",
    settingsRefreshModels: "목록 새로고침",
    settingsModelCache: "모델 캐시 상태",
    settingsModelCacheSource: "소스",
    settingsModelCacheFetchedAt: "가져온 시간",
    settingsModelCacheExpiresAt: "만료 시간",
    settingsModelCacheStatus: "상태",
    settingsModelCacheError: "오류 이유",
    settingsModelCacheSourceLive: "실시간 가져옴",
    settingsModelCacheSourceCache: "캐시됨",
    settingsModelCacheStatusFresh: "유효",
    settingsModelCacheStatusExpired: "만료됨",
    settingsModelCacheStatusUnknown: "알 수 없음",
    settingsModelCacheStatusLoading: "가져오는 중",
    settingsModelCacheStatusError: "오류",
    settingsRuntimeSection: "현재 코치 런타임",
    settingsRuntimeHint: "지금 메시지를 보내면 어떤 스레드를 계속할지 설명.",
    settingsMemoryStrategy: "기억 전략",
    settingsMemoryStrategyHint: "Trainer가 무엇을 기억倾向于哪个项目，以及这些记忆是否会保留在这个项目中。",
    settingsReviewStrategyHint: "Trainer가 복습을 요청하는 빈도와 알림의 방해 정도를 제어.",
    settingsContextCurrentFileHint: "편집 중인 파일 우선.",
    settingsContextSelectionHint: "현재 선택 영역 포함.",
    settingsContextDiagnosticsHint: "복습이나 디버깅에 진단 첨부.",
    settingsContextRelatedFilesHint: "정말 필요할 때만 관련 파일 가져옴.",
    settingsMemoryScopeRuntimeProject: "현재 프로젝트의 계획, 스레드, 리소스를 주로 따름.",
    settingsMemoryScopeRuntimePersonal: "프로젝트 간 선호도, 판단, 훈련 흔적 유지.",
    settingsMemoryScopeRuntimeSession: "현재 세션 스레드 내에 유지.",
    settingsMemoryScopeProjectHint: "스레드와 판단을 현재 프로젝트 내에 유지.",
    settingsMemoryScopePersonalHint: " hábito와 판단을 다른 프로젝트로 이동.",
    settingsMemoryScopeSessionHint: "현재 대화를 위한 로컬 기억만 유지.",
    settingsWorkingSetFocusedHint: "가장 작은 검증 가능한 단편과 근처 파일에 유지.",
    settingsWorkingSetBalancedHint: "대부분의 코드 턴에 현재 단편과 근처 컨텍스트 균형.",
    settingsWorkingSetBroadHint: "검증에 필요하면 더 넓은 컨텍스트 허용.",
    settingsReviewCadenceLightHint: "중요한 복습 포인트를 유지하면서 덜 중단.",
    settingsReviewCadenceSteadyHint: "일반적인 훈련 리듬.",
    settingsReviewCadenceActiveHint: "짧은 스프린트에 더 자주 복습.",
    settingsReviewReminderDueHint: "복습이 실제로期满할 때만 리마인드.",
    settingsReviewReminderAheadHint: "期限 전에 경고を送信.",
    settingsReviewReminderDigestHint: "가까운 복습을 하나의 다이제스트로 그룹화.",
    settingsSavedState: "저장됨",
    settingsUnsavedState: "저장되지 않음",
    settingsEmptyState: "워크스페이스에 미작성",
    settingsEffectiveNow: "즉시 적용",
    settingsSavedInWorkspace: "워크스페이스에 저장됨",
    settingsEditingDraft: "편집 중",
    settingsCurrentWorkspace: "현재 워크스페이스",
    settingsLocalThemeNote: "테마는 지금 보는 것에만 영향.",
    settingsWorkspaceSaveNote: "코치 기본값 저장은 워크스페이스 수준 컨트롤도 저장.",
    settingsProviderRuntimeNote: "연결 테스트는 지금 워크스페이스에서 활성 provider 설정을 사용.",
    settingsLatestAction: "최근 작업",
    settingsLastTest: "마지막 테스트",
    settingsLastTestNever: "테스트 안 함",
    settingsLastTestPassed: "성공",
    settingsLastTestFailed: "실패",
    settingsLastTestNeedsSetup: "설정 필요",
    settingsFocused: "집중",
    settingsBalancedContext: "표준",
    settingsFullContext: "확장",
    settingsSaveCoachDefaults: "코치 기본값 저장",
    globalPlanLabel: "\uc804\uccb4 \uacc4\ud68d",
    globalPlanRelationship: "\uc804\uccb4 \uacc4\ud68d -> \ud604\uc7ac \ud504\ub85c\uc81d\ud2b8 \uacc4\ud68d",
    globalPlanNotCreated: "\uc544\uc9c1 \uc0dd\uc131\ub418\uc9c0 \uc54a\uc74c",
    globalPlanNotLinked: "\ud604\uc7ac \ud504\ub85c\uc81d\ud2b8\uac00 \uc5f0\uacb0\ub418\uc9c0 \uc54a\uc74c",
    globalPlanLinked: "\ud604\uc7ac \ud504\ub85c\uc81d\ud2b8\uc5d0 \uc5f0\uacb0\ub428",
    globalPlanCreate: "\uc804\uccb4 \uacc4\ud68d \ub9cc\ub4e4\uae30",
    globalPlanLinkCurrentProject: "\ud604\uc7ac \ud504\ub85c\uc81d\ud2b8 \uacc4\ud68d \uc5f0\uacb0",
    globalPlanLinkUnavailable: "\uba3c\uc800 \ud604\uc7ac \ud504\ub85c\uc81d\ud2b8 \uacc4\ud68d\uc744 \uc0dd\uc131\ud558\uc138\uc694",
    globalPlanFrozen: "\uc804\uccb4 \uacc4\ud68d\uc774 \ub3d9\uacb0\ub428",
    evidenceConfidence: "\uc2e0\ub8b0\ub3c4",
    evidenceGovernance: "\uc99d\uac70 \uad00\ub9ac",
    evidenceFilterAll: "\uc804\uccb4",
    evidenceFilterDeferred: "\ubcf4\ub958\ub428",
    evidenceFilterAdopted: "\ucc44\ud0dd\ub428",
    evidenceFilterRejected: "\uac70\ubd80\ub428",
    evidenceAdopt: "\ucc44\ud0dd",
    evidenceDefer: "\ubcf4\ub958",
    evidenceTargetPrefix: "\ub300\uc0c1",
    evidenceNoMatches: "\uc774 \ud544\ud130\uc5d0 \ub9de\ub294 \uc99d\uac70\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.",
  },

  // ==========================================================================
  // Português (巴西)
  // ==========================================================================
  "pt-BR": {
    settingsStatusRegionLabel: "Estado atual",
    settingsStatusConnected: "Conectado",
    settingsStatusNotConnected: "Não conectado",
    settingsStatusLanguage: "Idioma",
    settingsStatusMemory: "Memória",
    settingsStatusNoApiKey: "Chave de API ausente",
    settingsStatusNeedsTest: "Conexão não testada",
    settingsStatusTrust: "Workspace não confiável",
    settingsStatusUnsaved: "Alterações não salvas",
    settingsSectionConnection: "Conexão",
    settingsTeachingPrefs: "Preferências de ensino",
    settingsAnswerStyle: "Estilo de resposta",
    answerStyleSimple: "Simples",
    answerStyleBalanced: "Equilibrado",
    answerStyleDeep: "Profundo",
    answerStyleCustom: "Personalizado",
    settingsAnswerStyleHint: "Predefinições definem a profundidade do contexto e anexos. Salve para aplicar.",
    settingsAdvancedContext: "Contexto avançado",
    settingsMemoryPrivacy: "Memória e privacidade",
    settingsAdvanced: "Avançado",
    coach: "Treinador",
    coachArtifactFullDetails: "Detalhes completos",
    trainer: "Trainer",
    you: "Você",
    plan: "Plano",
    settings: "Configurações",
    chat: "Chat",
    workspace: "Workspace",
    viewNavigation: "Vistas do Trainer",
    currentFocus: "Foco atual",
    currentTask: "Tarefa atual",
    latestReview: "Última revisão",
    backgroundAnalysis: "Análise em segundo plano",
    backgroundCoachWork: "Preparação do Coach",
    firstLookBadge: "Visão geral do projeto",
    firstLookProjectType: "Tipo de projeto",
    firstLookFolderRole: "Papel da pasta",
    firstLookWhyGuess: "Por que esse palpite",
    firstLookEntryPoints: "Pontos de entrada",
    firstLookDirectoryAnchors: "Locais principais",
    firstLookCoreModules: "Módulos / materiais principais",
    firstLookRiskZones: "Zonas de risco",
    firstLookOpportunities: "Oportunidades de treino",
    firstLookUnknowns: "Desconhecidos",
    firstLookNextStep: "Próximo passo",
    workspaceAdmissionRootMissing: "Raiz do workspace não configurada",
    workspaceAdmissionRootMissingDetail: "Escolha onde o Trainer guarda os registros de aprendizagem antes de decidir como tratar este projeto.",
    workspaceAdmissionGoalSaved: "Seu objetivo continua no campo. Escolha onde guardar os registros e volte para enviá-lo.",
    workspaceAdmissionProjectFound: "Projeto encontrado",
    workspaceAdmissionProjectFoundDetail: "Escolha uma opção: adicionar ao Trainer, somente navegar ou ignorar.",
    workspaceAdmissionManaged: "Gerenciado pelo Trainer",
    workspaceAdmissionManagedDetail: "As conversas, o plano e os registros de aprendizagem deste projeto ficam separados.",
    workspaceAdmissionBrowse: "Somente navegar",
    workspaceAdmissionBrowseDetail: "Você pode inspecionar este projeto, mas o coaching e os registros salvos ficam desativados.",
    workspaceAdmissionIgnored: "Ignorado",
    workspaceAdmissionIgnoredDetail: "O Trainer não lerá nem gerenciará este projeto. Você pode adicioná-lo depois.",
    workspaceAdmissionProjectName: "Projeto",
    workspaceAdmissionProjectPath: "Caminho",
    workspaceAdmissionSelectRoot: "Escolher raiz do workspace",
    workspaceAdmissionSelectProject: "Escolher pasta do projeto",
    workspaceAdmissionAdd: "Adicionar ao Trainer",
    workspaceAdmissionBrowseAction: "Somente navegar",
    workspaceAdmissionIgnore: "Ignorar projeto",
    workspaceAdmissionDelete: "Excluir projeto",
    workspaceRootControl: "Espaço do Trainer",
    workspaceRootReady: "Os registros de aprendizagem são guardados neste espaço.",
    workspaceRootPath: "Raiz",
    workspaceRootMigrate: "Migrar espaço",
    workspaceRootMigrateDetail: "Copie para uma nova pasta vazia e continue pela nova raiz.",
    workspaceRootRecovery: "Backup e restauração",
    workspaceRootBackup: "Fazer backup do espaço",
    workspaceRootBackupDetail: "Cria uma cópia recuperável sem alterar a raiz ativa.",
    workspaceRootRestore: "Restaurar backup",
    workspaceRootRestoreDetail: "Restaura em uma nova pasta vazia e a torna a raiz ativa.",
    workspaceRootChange: "Alterar raiz",
    workspaceRootChangeDetail: "Escolha outra raiz sem copiar os dados atuais.",
    coachState: "Estado do Coach",
    coachSignal: "Sinal de aprendizado",
    reviewQueue: "Fila de revisão",
    runReview: "Iniciar revisão",
    reviewMemory: "Memória e ritmo",
    reviewRhythm: "Ritmo de revisão",
    nextReview: "Próxima revisão",
    teachingObservations: "Observações pedagógicas",
    coachSummaryDoing: "Em andamento",
    goals: "Objetivos",
    constraints: "Restrições",
    acceptance: "Critérios de aceite",
    nextMove: "Próxima ação",
    recentWins: "Ganhos recentes",
    weakSpots: "Pontos fracos",
    planStages: "Estágios",
    trainingWhyNow: "Por que agora",
    trainingDeliverable: "Entregável",
    planStageMaterialsTitle: "Materiais de estudo",
    planStageMaterialsGenerate: "Gerar materiais",
    planStageMaterialsGenerating: "Gerando…",
    planStageMaterialsView: "Ver",
    planStageMaterialsHide: "Ocultar",
    planStageMaterialsEmpty: "Ainda não há materiais de estudo para este estágio.",
    planStageCompletionLabel: "Progresso do estágio",
    planStageMaterialsBadgeTitle: "Materiais gerados",
    planDashboardTabPlan: "Plano",
    planDashboardTabProgress: "Progresso",
    planDashboardStagesTitle: "Conclusão de estágios",
    planDashboardMasteryTitle: "Domínio de dependências",
    planDashboardReviewTitle: "Retenção de revisões FSRS",
    planDashboardMaterialsTitle: "Uso de materiais",
    planDashboardMaterialsStages: "Estágios cobertos",
    planDashboardMasteryEmpty: "Ainda não há dados de domínio. Eles se acumulam ao concluir cartões de treino.",
    planDashboardReviewDue: "Pendente",
    planDashboardReviewDone: "Concluído",
    planDashboardEmptyTitle: "Gere um plano primeiro",
    trainingHandoffMismatchHint: "Este cartão não corresponde ao repasse de treino atual. Troque para o cartão que possui o repasse.",
    trainingSwitchToCard: "Trocar para esse cartão",
    trainingCardDetailsApiHints: "Dicas de API",
    trainingCardDetailsSelfCheck: "Autoavaliação",
    trainingCardDetailsRubric: "Rubrica de avaliação",
    trainingCardDetailsAcceptance: "Critérios de aceitação",
    language: "Idioma",
    answerMode: "Modo de resposta",
    teachingStyle: "Estilo de ensino",
    teachingGuided: "Guiado",
    teachingConceptFirst: "Conceito primeiro",
    teachingHandsOn: "Prática primeiro",
    teachingChallenging: "Desafiador",
    contextDetail: "Detalhe do contexto",
    coachFirst: "Guiado",
    balanced: "Equilibrado",
    direct: "Direto",
    detailFocused: "Focado",
    detailBalanced: "Padrão",
    detailFull: "Completo",
    attachments: "Anexos",
    currentContext: "Contexto atual",
    allContext: "Todo contexto",
    noContext: "Sem contexto",
    file: "Arquivo",
    selection: "Seleção",
    diagnostics: "Diagnósticos",
    relatedFiles: "Arquivos relacionados",
    follow: "Acompanhamento em tempo real",
    theme: "Tema",
    system: "Sistema",
    light: "Claro",
    dark: "Escuro",
    provider: "Provedor",
    protocol: "Protocolo",
    baseUrl: "URL base",
    chatModel: "Modelo",
    apiKey: "Chave API",
    apiKeySaved: "Salvo",
    apiKeyMissing: "Não configurado",
    saveProvider: "Salvar",
    testProvider: "Testar conexão",
    clearProvider: "Limpar",
    openConfigFile: "Abrir arquivo",
    configured: "Configurado",
    notConfigured: "Não configurado",
    refreshProviderProfiles: "Atualizar perfis",
    refreshWorkspaceAuthority: "Atualizar autoridade",
    createProfileFromTemplate: "Criar do modelo",
    settingsSetupSection: "Conexão do modelo",
    settingsSetupTitleReady: "Trainer está pronto",
    settingsSetupTitleBlocked: "Sem chave API, Trainer não pode iniciar",
    settingsSetupDetailReady: "Conexão do modelo pronta. Você pode chat, planejar e aprender agora.",
    settingsSetupDetailBlocked: "Salve provedor, URL, modelo e chave API. Só assim Trainer pode trabalhar.",
    settingsSetupAction: "Completar configuração",
    settingsInterfaceSection: "Como Trainer te guia",
    settingsCoachSection: "Contexto padrão por rodada",
    settingsModelSection: "Conectar modelo",
    settingsFollowCurrentFile: "Acompanhamento em tempo real",
    settingsContextMode: "Nível de contexto",
    settingsCurrentFile: "Arquivo atual",
    settingsConnectionDetails: "Detalhes de conexão",
    settingsLongTermMemory: "Memória de longo prazo",
    settingsMemoryScope: "Escopo de memória",
    settingsMemoryScopeProject: "Projeto atual",
    settingsMemoryScopePersonal: "Pessoal通用",
    settingsMemoryScopeSession: "Sessão atual",
    settingsRememberDecisions: "Decisões de arquitetura",
    settingsRememberPatterns: "Padrões comuns",
    settingsRememberResources: "Referências",
    settingsWorkingSet: "Conjunto de trabalho",
    settingsWorkingSetFocused: "Apenas tarefa atual",
    settingsWorkingSetBalanced: "Arquivos próximos",
    settingsWorkingSetBroad: "Referências mais amplas",
    settingsMemoryPreview: "Retenção prioritária",
    settingsMemoryPreviewEmpty: "Segue arquivo, seleção e diagnósticos atualmente.",
    settingsTeachingSignal: "Sinal de aprendizado",
    settingsConfigFileNote: "Precisa de mais ajustes? Você pode refiná-los no arquivo de configuração.",
    settingsContextSection: "Contexto anexado",
    settingsMemoryRuntime: "Execução em segundo plano",
    settingsMemoryRuntimeDetail: "Memória, revisão e ritmo de ensino atualizam automaticamente por rodada.",
    settingsAdvancedSection: "Mais estratégias padrão",
    settingsAdvancedIntro: "Não precisa mexer frequentemente. Expanda apenas quando quiser mudar como Trainer continua e se lembra.",
    settingsReviewRhythmPace: "Intensidade do lembrete",
    settingsReviewRhythmReminder: "Estratégia de lembrete",
    settingsReviewStrategy: "Estratégia de revisão",
    settingsSystemActions: "Organizar estado atual",
    settingsRefreshMemory: "Atualizar memória",
    settingsResetDefaults: "Restaurar padrões",
    settingsModelTools: "Ferramentas de conexão",
    settingsDefaultsHint: "Defina como Trainer fala e te guia. A maioria das conversas seguirá esse ritmo.",
    settingsContextHint: "Define apenas os anexos padrão por rodada.",
    settingsModelHint: "Gerencia apenas a conexão. O coaching real vem do plano e continuidade.",
    settingsAvailableModels: "Modelos disponíveis",
    settingsDetectedModel: "Modelo detectado",
    settingsModelFetchLoading: "Carregando modelos…",
    settingsModelFetchEmpty: "Lista carrega automaticamente após salvar chave API.",
    settingsRefreshModels: "Atualizar lista",
    settingsModelCache: "Estado do cache de modelos",
    settingsModelCacheSource: "Fonte",
    settingsModelCacheFetchedAt: "Obterido em",
    settingsModelCacheExpiresAt: "Expira em",
    settingsModelCacheStatus: "Estado",
    settingsModelCacheError: "Razão do erro",
    settingsModelCacheSourceLive: "Tempo real",
    settingsModelCacheSourceCache: "Em cache",
    settingsModelCacheStatusFresh: "Válido",
    settingsModelCacheStatusExpired: "Expirado",
    settingsModelCacheStatusUnknown: "Desconhecido",
    settingsModelCacheStatusLoading: "Carregando",
    settingsModelCacheStatusError: "Erro",
    settingsRuntimeSection: "Runtime atual do coach",
    settingsRuntimeHint: "Descreve qual thread Trainer continuaria se você enviasse agora.",
    settingsMemoryStrategy: "Estratégia de memória",
    settingsMemoryStrategyHint: "Controla o que Trainer tende a lembrar e se essas memórias permanecem neste projeto.",
    settingsReviewStrategyHint: "Controla com que frequência Trainer pede revisão e quão intrusivos são os lembretes.",
    settingsContextCurrentFileHint: "Prioridade para o arquivo que você está editando.",
    settingsContextSelectionHint: "Inclui seleção atual.",
    settingsContextDiagnosticsHint: "Anexa diagnósticos para revisões.",
    settingsContextRelatedFilesHint: "Traz arquivos relacionados apenas quando realmente necessário.",
    settingsMemoryScopeRuntimeProject: "Segue principalmente plano, thread e recursos do projeto atual.",
    settingsMemoryScopeRuntimePersonal: "Mantém preferências e vestígios de treinamento entre projetos.",
    settingsMemoryScopeRuntimeSession: "Mantém dentro do thread da sessão atual.",
    settingsMemoryScopeProjectHint: "Mantenha thread e julgamento dentro do projeto atual.",
    settingsMemoryScopePersonalHint: "Leve hábitos e julgamento para outros projetos.",
    settingsMemoryScopeSessionHint: "Memória local apenas para conversa atual.",
    settingsWorkingSetFocusedHint: "Fique no menor fragmento verificável.",
    settingsWorkingSetBalancedHint: "Equilibre fragmento atual com contexto próximo.",
    settingsWorkingSetBroadHint: "Permita contexto mais amplo quando necessário.",
    settingsReviewCadenceLightHint: "Interrompe menos frequentemente.",
    settingsReviewCadenceSteadyHint: "Ritmo normal de treinamento.",
    settingsReviewCadenceActiveHint: "Revisões mais frequentes.",
    settingsReviewReminderDueHint: "Lembra principalmente no vencimento.",
    settingsReviewReminderAheadHint: "Envia aviso antes do vencimento.",
    settingsReviewReminderDigestHint: "Agrupa revisões próximas.",
    settingsSavedState: "Salvo",
    settingsUnsavedState: "Não salvo",
    settingsEmptyState: "Não escrito no workspace",
    settingsEffectiveNow: "Efetivo agora",
    settingsSavedInWorkspace: "Salvo no workspace",
    settingsEditingDraft: "Editando",
    settingsCurrentWorkspace: "Workspace atual",
    settingsLocalThemeNote: "Tema afeta apenas o que você vê agora.",
    settingsWorkspaceSaveNote: "Salvar valores do coach salva controles de nível de workspace.",
    settingsProviderRuntimeNote: "Teste usa configuração ativa no workspace.",
    settingsLatestAction: "Ação recente",
    settingsLastTest: "Último teste",
    settingsLastTestNever: "Nunca testado",
    settingsLastTestPassed: "Aprovado",
    settingsLastTestFailed: "Falhou",
    settingsLastTestNeedsSetup: "Precisa configuração",
    settingsFocused: "Focado",
    settingsBalancedContext: "Padrão",
    settingsFullContext: "Estendido",
    settingsSaveCoachDefaults: "Salvar valores do coach",
    globalPlanLabel: "Plano global",
    globalPlanRelationship: "Plano global -> Plano do projeto atual",
    globalPlanNotCreated: "Ainda n\u00e3o criado",
    globalPlanNotLinked: "O projeto atual n\u00e3o est\u00e1 vinculado",
    globalPlanLinked: "Vinculado ao projeto atual",
    globalPlanCreate: "Criar plano global",
    globalPlanLinkCurrentProject: "Vincular plano do projeto atual",
    globalPlanLinkUnavailable: "Primeiro gere um plano para o projeto atual",
    globalPlanFrozen: "O plano global est\u00e1 congelado",
    evidenceConfidence: "Confian\u00e7a",
    evidenceGovernance: "Governan\u00e7a de evid\u00eancias",
    evidenceFilterAll: "Tudo",
    evidenceFilterDeferred: "Adiado",
    evidenceFilterAdopted: "Adotado",
    evidenceFilterRejected: "Rejeitado",
    evidenceAdopt: "Adotar",
    evidenceDefer: "Adiar",
    evidenceTargetPrefix: "Alvo",
    evidenceNoMatches: "Nenhuma evid\u00eancia corresponde a este filtro.",
  },
} satisfies CopyTable;

const defaultCopy = copyTable["en-US"];

const resourceViewLocaleOverrides: Partial<Record<ComposerLanguage, Partial<Copy>>> = {
  "es-ES": {
    settingsMemorySharing: "Memoria entre proyectos",
    settingsMemorySharingDetail: "Los proyectos permanecen aislados por defecto. Solo se leen preferencias y señales de dominio autorizadas explícitamente.",
    settingsMemorySharingNone: "No hay otros proyectos autorizados.",
    settingsMemorySharingActive: "fuentes autorizadas",
    settingsMemorySharingUnavailable: "Agrega el proyecto actual a Trainer antes de autorizar memoria entre proyectos.",
    settingsMemoryShareGrant: "Autorizar proyecto",
    settingsMemoryShareRevoke: "Revocar",
    settingsMemorySharePreferences: "Preferencias",
    settingsMemoryShareMastery: "Señales de dominio",
    addFiles: "Agregar archivos",
    addFolder: "Agregar carpeta",
    addUrl: "Agregar URL",
    resourcesEmpty: "La biblioteca está vacía. Empieza importando aquí",
    resourcesMenu: "Menú de recursos",
    resourcesSummary: "Resumen de recursos",
    resourcesSandbox: "Sandbox",
    resourcesSandboxRoot: "Raíz del sandbox",
    resourcesSandboxRefresh: "Actualizar",
    resourcesSandboxNewFile: "Nuevo archivo",
    resourcesSandboxNewFolder: "Nueva carpeta",
    resourcesSandboxRename: "Renombrar",
    resourcesSandboxTrash: "Mover a Trash",
    resourcesSandboxEmpty: "El sandbox sigue vacío.",
    resourcesSandboxBoundaryRefresh: "Límite",
    resourcesSandboxOpenRoot: "Abrir raíz",
    resourcesSandboxChooseRoot: "Elegir raíz",
    resourcesSandboxResetRoot: "Usar predeterminado",
    resourcesSandboxActionBase: "Base de destino",
    resourcesSandboxCreateIn: "Crear en",
    resourcesSandboxTargetCurrent: "Carpeta actual",
    resourcesSandboxTargetRoot: "Raíz del sandbox",
    resourcesSandboxParent: "Superior",
    resourcesSandboxResolvedPath: "Ruta resultante",
    resourcesSandboxSourcePath: "Ruta de origen",
    resourcesSandboxWorkspaceRoot: "Raíz del workspace",
    resourcesSandboxSourceLabel: "Origen",
    resourcesSandboxLedger: "Ledger / checkpoints",
    resourcesSandboxTrashRoot: "Trash",
    resourcesSandboxMountedSources: "Orígenes montados",
    resourcesSandboxNextSafeMove: "Siguiente paso seguro",
    resourcesSandboxFilePlaceholder: "Ruta del archivo, por ejemplo packs/remote/ssh/notes.md",
    resourcesSandboxFolderPlaceholder: "Ruta de carpeta anidada, por ejemplo packs/remote/ssh",
    resourcesSandboxFileHint: "Crea dentro de la raíz del sandbox. Se admiten rutas anidadas.",
    resourcesSandboxFolderHint: "Crea dentro de la raíz del sandbox. Se admiten carpetas anidadas.",
    resourcesSandboxRenamePlaceholder: "Nueva ruta relativa, por ejemplo packs/debug/minimal-loop.md",
    resourcesSandboxRenameHint: "Renombrar también puede mover la ruta dentro del sandbox.",
    resourcesSandboxManagedLayout: "Diseño de Trainer",
  },
  "fr-FR": {
    settingsMemorySharing: "Mémoire inter-projets",
    settingsMemorySharingDetail: "Les projets restent isolés par défaut. Seules les préférences et signaux de maîtrise explicitement autorisés sont lus.",
    settingsMemorySharingNone: "Aucun autre projet n'est autorisé.",
    settingsMemorySharingActive: "sources autorisées",
    settingsMemorySharingUnavailable: "Ajoutez le projet actuel à Trainer avant d'autoriser la mémoire inter-projets.",
    settingsMemoryShareGrant: "Autoriser un projet",
    settingsMemoryShareRevoke: "Révoquer",
    settingsMemorySharePreferences: "Préférences",
    settingsMemoryShareMastery: "Signaux de maîtrise",
    addFiles: "Ajouter des fichiers",
    addFolder: "Ajouter un dossier",
    addUrl: "Ajouter une URL",
    resourcesEmpty: "La bibliothèque est vide. Commencez l'import ici",
    resourcesMenu: "Menu des ressources",
    resourcesSummary: "Résumé des ressources",
    resourcesSandbox: "Sandbox",
    resourcesSandboxRoot: "Racine du sandbox",
    resourcesSandboxRefresh: "Actualiser",
    resourcesSandboxNewFile: "Nouveau fichier",
    resourcesSandboxNewFolder: "Nouveau dossier",
    resourcesSandboxRename: "Renommer",
    resourcesSandboxTrash: "Déplacer vers Trash",
    resourcesSandboxEmpty: "Le sandbox est encore vide.",
    resourcesSandboxBoundaryRefresh: "Frontière",
    resourcesSandboxOpenRoot: "Ouvrir la racine",
    resourcesSandboxChooseRoot: "Choisir la racine",
    resourcesSandboxResetRoot: "Utiliser la valeur par défaut",
    resourcesSandboxActionBase: "Base cible",
    resourcesSandboxCreateIn: "Créer dans",
    resourcesSandboxTargetCurrent: "Dossier actuel",
    resourcesSandboxTargetRoot: "Racine du sandbox",
    resourcesSandboxParent: "Parent",
    resourcesSandboxResolvedPath: "Chemin obtenu",
    resourcesSandboxSourcePath: "Chemin source",
    resourcesSandboxWorkspaceRoot: "Racine du workspace",
    resourcesSandboxSourceLabel: "Source",
    resourcesSandboxLedger: "Ledger / checkpoints",
    resourcesSandboxTrashRoot: "Trash",
    resourcesSandboxMountedSources: "Sources montées",
    resourcesSandboxNextSafeMove: "Prochaine action sûre",
    resourcesSandboxFilePlaceholder: "Chemin du fichier, par exemple packs/remote/ssh/notes.md",
    resourcesSandboxFolderPlaceholder: "Chemin du dossier imbriqué, par exemple packs/remote/ssh",
    resourcesSandboxFileHint: "Créer dans la racine du sandbox. Les chemins imbriqués sont pris en charge.",
    resourcesSandboxFolderHint: "Créer dans la racine du sandbox. Les dossiers imbriqués sont pris en charge.",
    resourcesSandboxRenamePlaceholder: "Nouveau chemin relatif, par exemple packs/debug/minimal-loop.md",
    resourcesSandboxRenameHint: "Renommer peut aussi déplacer le chemin dans le sandbox.",
    resourcesSandboxManagedLayout: "Structure Trainer",
  },
  "de-DE": {
    settingsMemorySharing: "Projektübergreifender Speicher",
    settingsMemorySharingDetail: "Projekte bleiben standardmäßig getrennt. Nur ausdrücklich erlaubte Präferenzen und Kompetenzsignale werden gelesen.",
    settingsMemorySharingNone: "Es sind keine anderen Projekte autorisiert.",
    settingsMemorySharingActive: "autorisierte Quellen",
    settingsMemorySharingUnavailable: "Fügen Sie das aktuelle Projekt zu Trainer hinzu, bevor Sie projektübergreifenden Speicher erlauben.",
    settingsMemoryShareGrant: "Projekt erlauben",
    settingsMemoryShareRevoke: "Widerrufen",
    settingsMemorySharePreferences: "Präferenzen",
    settingsMemoryShareMastery: "Kompetenzsignale",
    addFiles: "Dateien hinzufügen",
    addFolder: "Ordner hinzufügen",
    addUrl: "URL hinzufügen",
    resourcesEmpty: "Die Bibliothek ist leer. Hier mit dem Import beginnen",
    resourcesMenu: "Ressourcenmenü",
    resourcesSummary: "Ressourcenübersicht",
    resourcesSandbox: "Sandbox",
    resourcesSandboxRoot: "Sandbox-Stamm",
    resourcesSandboxRefresh: "Aktualisieren",
    resourcesSandboxNewFile: "Neue Datei",
    resourcesSandboxNewFolder: "Neuer Ordner",
    resourcesSandboxRename: "Umbenennen",
    resourcesSandboxTrash: "In Trash verschieben",
    resourcesSandboxEmpty: "Die Sandbox ist noch leer.",
    resourcesSandboxBoundaryRefresh: "Grenze",
    resourcesSandboxOpenRoot: "Stamm öffnen",
    resourcesSandboxChooseRoot: "Stamm wählen",
    resourcesSandboxResetRoot: "Standard verwenden",
    resourcesSandboxActionBase: "Zielbasis",
    resourcesSandboxCreateIn: "Erstellen in",
    resourcesSandboxTargetCurrent: "Aktueller Ordner",
    resourcesSandboxTargetRoot: "Sandbox-Stamm",
    resourcesSandboxParent: "Übergeordnet",
    resourcesSandboxResolvedPath: "Ergebnispfad",
    resourcesSandboxSourcePath: "Quellpfad",
    resourcesSandboxWorkspaceRoot: "Workspace-Stamm",
    resourcesSandboxSourceLabel: "Quelle",
    resourcesSandboxLedger: "Ledger / checkpoints",
    resourcesSandboxTrashRoot: "Trash",
    resourcesSandboxMountedSources: "Eingehängte Quellen",
    resourcesSandboxNextSafeMove: "Nächster sicherer Schritt",
    resourcesSandboxFilePlaceholder: "Dateipfad, zum Beispiel packs/remote/ssh/notes.md",
    resourcesSandboxFolderPlaceholder: "Verschachtelter Ordnerpfad, zum Beispiel packs/remote/ssh",
    resourcesSandboxFileHint: "Innerhalb des Sandbox-Stamms erstellen. Verschachtelte Pfade werden unterstützt.",
    resourcesSandboxFolderHint: "Innerhalb des Sandbox-Stamms erstellen. Verschachtelte Ordner werden unterstützt.",
    resourcesSandboxRenamePlaceholder: "Neuer relativer Pfad, zum Beispiel packs/debug/minimal-loop.md",
    resourcesSandboxRenameHint: "Umbenennen kann den Pfad auch innerhalb der Sandbox verschieben.",
    resourcesSandboxManagedLayout: "Trainer-Struktur",
  },
  "ja-JP": {
    settingsMemorySharing: "プロジェクト間メモリ",
    settingsMemorySharingDetail: "プロジェクトは既定で分離されます。明示的に許可した設定と習熟シグナルだけを読み取ります。",
    settingsMemorySharingNone: "許可した別プロジェクトはありません。",
    settingsMemorySharingActive: "件の許可済みソース",
    settingsMemorySharingUnavailable: "プロジェクト間メモリを許可する前に、現在のプロジェクトを Trainer に追加してください。",
    settingsMemoryShareGrant: "プロジェクトを許可",
    settingsMemoryShareRevoke: "取り消す",
    settingsMemorySharePreferences: "設定",
    settingsMemoryShareMastery: "習熟シグナル",
    addFiles: "ファイルを追加",
    addFolder: "フォルダを追加",
    addUrl: "URL を追加",
    resourcesEmpty: "ライブラリは空です。ここから取り込みを始めてください",
    resourcesMenu: "リソースメニュー",
    resourcesSummary: "リソース概要",
    resourcesSandbox: "Sandbox",
    resourcesSandboxRoot: "Sandbox ルート",
    resourcesSandboxRefresh: "更新",
    resourcesSandboxNewFile: "新しいファイル",
    resourcesSandboxNewFolder: "新しいフォルダ",
    resourcesSandboxRename: "名前を変更",
    resourcesSandboxTrash: "Trash へ移動",
    resourcesSandboxEmpty: "Sandbox はまだ空です。",
    resourcesSandboxBoundaryRefresh: "境界",
    resourcesSandboxOpenRoot: "ルートを開く",
    resourcesSandboxChooseRoot: "ルートを選択",
    resourcesSandboxResetRoot: "既定を使う",
    resourcesSandboxActionBase: "作成基準",
    resourcesSandboxCreateIn: "作成先",
    resourcesSandboxTargetCurrent: "現在のフォルダ",
    resourcesSandboxTargetRoot: "Sandbox ルート",
    resourcesSandboxParent: "親へ",
    resourcesSandboxResolvedPath: "結果パス",
    resourcesSandboxSourcePath: "元のパス",
    resourcesSandboxWorkspaceRoot: "Workspace ルート",
    resourcesSandboxSourceLabel: "ソース",
    resourcesSandboxLedger: "Ledger / checkpoints",
    resourcesSandboxTrashRoot: "Trash",
    resourcesSandboxMountedSources: "マウント済みソース",
    resourcesSandboxNextSafeMove: "次の安全な一手",
    resourcesSandboxFilePlaceholder: "ファイルパス。例: packs/remote/ssh/notes.md",
    resourcesSandboxFolderPlaceholder: "ネストしたフォルダパス。例: packs/remote/ssh",
    resourcesSandboxFileHint: "Sandbox ルート内に作成します。ネストしたパスに対応します。",
    resourcesSandboxFolderHint: "Sandbox ルート内に作成します。ネストしたフォルダに対応します。",
    resourcesSandboxRenamePlaceholder: "新しい相対パス。例: packs/debug/minimal-loop.md",
    resourcesSandboxRenameHint: "名前の変更では、Sandbox 内での移動もできます。",
    resourcesSandboxManagedLayout: "Trainer レイアウト",
  },
  "ko-KR": {
    settingsMemorySharing: "프로젝트 간 메모리",
    settingsMemorySharingDetail: "프로젝트는 기본적으로 분리됩니다. 명시적으로 허용한 환경설정과 숙련 신호만 읽습니다.",
    settingsMemorySharingNone: "허용된 다른 프로젝트가 없습니다.",
    settingsMemorySharingActive: "개의 허용된 소스",
    settingsMemorySharingUnavailable: "프로젝트 간 메모리를 허용하기 전에 현재 프로젝트를 Trainer에 추가하세요.",
    settingsMemoryShareGrant: "프로젝트 허용",
    settingsMemoryShareRevoke: "취소",
    settingsMemorySharePreferences: "환경설정",
    settingsMemoryShareMastery: "숙련 신호",
    addFiles: "파일 추가",
    addFolder: "폴더 추가",
    addUrl: "URL 추가",
    resourcesEmpty: "라이브러리가 비어 있습니다. 여기서 가져오기를 시작하세요",
    resourcesMenu: "리소스 메뉴",
    resourcesSummary: "리소스 요약",
    resourcesSandbox: "Sandbox",
    resourcesSandboxRoot: "Sandbox 루트",
    resourcesSandboxRefresh: "새로 고침",
    resourcesSandboxNewFile: "새 파일",
    resourcesSandboxNewFolder: "새 폴더",
    resourcesSandboxRename: "이름 바꾸기",
    resourcesSandboxTrash: "Trash로 이동",
    resourcesSandboxEmpty: "Sandbox가 아직 비어 있습니다.",
    resourcesSandboxBoundaryRefresh: "경계",
    resourcesSandboxOpenRoot: "루트 열기",
    resourcesSandboxChooseRoot: "루트 선택",
    resourcesSandboxResetRoot: "기본값 사용",
    resourcesSandboxActionBase: "대상 기준",
    resourcesSandboxCreateIn: "생성 위치",
    resourcesSandboxTargetCurrent: "현재 폴더",
    resourcesSandboxTargetRoot: "Sandbox 루트",
    resourcesSandboxParent: "상위",
    resourcesSandboxResolvedPath: "결과 경로",
    resourcesSandboxSourcePath: "원본 경로",
    resourcesSandboxWorkspaceRoot: "Workspace 루트",
    resourcesSandboxSourceLabel: "소스",
    resourcesSandboxLedger: "Ledger / checkpoints",
    resourcesSandboxTrashRoot: "Trash",
    resourcesSandboxMountedSources: "마운트된 소스",
    resourcesSandboxNextSafeMove: "다음 안전한 단계",
    resourcesSandboxFilePlaceholder: "파일 경로. 예: packs/remote/ssh/notes.md",
    resourcesSandboxFolderPlaceholder: "중첩 폴더 경로. 예: packs/remote/ssh",
    resourcesSandboxFileHint: "Sandbox 루트 안에 만듭니다. 중첩 경로를 지원합니다.",
    resourcesSandboxFolderHint: "Sandbox 루트 안에 만듭니다. 중첩 폴더를 지원합니다.",
    resourcesSandboxRenamePlaceholder: "새 상대 경로. 예: packs/debug/minimal-loop.md",
    resourcesSandboxRenameHint: "이름 바꾸기는 Sandbox 안에서 경로를 이동하는 데도 쓸 수 있습니다.",
    resourcesSandboxManagedLayout: "Trainer 레이아웃",
  },
  "pt-BR": {
    settingsMemorySharing: "Memória entre projetos",
    settingsMemorySharingDetail: "Os projetos permanecem isolados por padrão. Apenas preferências e sinais de domínio autorizados explicitamente são lidos.",
    settingsMemorySharingNone: "Nenhum outro projeto está autorizado.",
    settingsMemorySharingActive: "fontes autorizadas",
    settingsMemorySharingUnavailable: "Adicione o projeto atual ao Trainer antes de autorizar memória entre projetos.",
    settingsMemoryShareGrant: "Autorizar projeto",
    settingsMemoryShareRevoke: "Revogar",
    settingsMemorySharePreferences: "Preferências",
    settingsMemoryShareMastery: "Sinais de domínio",
    addFiles: "Adicionar arquivos",
    addFolder: "Adicionar pasta",
    addUrl: "Adicionar URL",
    resourcesEmpty: "A biblioteca está vazia. Comece a importar aqui",
    resourcesMenu: "Menu de recursos",
    resourcesSummary: "Resumo dos recursos",
    resourcesSandbox: "Sandbox",
    resourcesSandboxRoot: "Raiz do sandbox",
    resourcesSandboxRefresh: "Atualizar",
    resourcesSandboxNewFile: "Novo arquivo",
    resourcesSandboxNewFolder: "Nova pasta",
    resourcesSandboxRename: "Renomear",
    resourcesSandboxTrash: "Mover para Trash",
    resourcesSandboxEmpty: "O sandbox ainda está vazio.",
    resourcesSandboxBoundaryRefresh: "Limite",
    resourcesSandboxOpenRoot: "Abrir raiz",
    resourcesSandboxChooseRoot: "Escolher raiz",
    resourcesSandboxResetRoot: "Usar padrão",
    resourcesSandboxActionBase: "Base de destino",
    resourcesSandboxCreateIn: "Criar em",
    resourcesSandboxTargetCurrent: "Pasta atual",
    resourcesSandboxTargetRoot: "Raiz do sandbox",
    resourcesSandboxParent: "Pai",
    resourcesSandboxResolvedPath: "Caminho resultante",
    resourcesSandboxSourcePath: "Caminho de origem",
    resourcesSandboxWorkspaceRoot: "Raiz do workspace",
    resourcesSandboxSourceLabel: "Origem",
    resourcesSandboxLedger: "Ledger / checkpoints",
    resourcesSandboxTrashRoot: "Trash",
    resourcesSandboxMountedSources: "Origens montadas",
    resourcesSandboxNextSafeMove: "Próximo passo seguro",
    resourcesSandboxFilePlaceholder: "Caminho do arquivo, por exemplo packs/remote/ssh/notes.md",
    resourcesSandboxFolderPlaceholder: "Caminho de pasta aninhada, por exemplo packs/remote/ssh",
    resourcesSandboxFileHint: "Crie dentro da raiz do sandbox. Caminhos aninhados são aceitos.",
    resourcesSandboxFolderHint: "Crie dentro da raiz do sandbox. Pastas aninhadas são aceitas.",
    resourcesSandboxRenamePlaceholder: "Novo caminho relativo, por exemplo packs/debug/minimal-loop.md",
    resourcesSandboxRenameHint: "Renomear também pode mover o caminho dentro do sandbox.",
    resourcesSandboxManagedLayout: "Layout do Trainer",
  },
};

type ContextRailCopy = Pick<
  Copy,
  | "openCoach"
  | "openSettings"
  | "composerPlaceholder"
  | "composerPlaceholderPlan"
  | "streaming"
  | "viewContextWorking"
  | "viewContextBlocker"
  | "viewContextLatest"
  | "viewContextCoach"
>;

const contextRailLocaleOverrides: Record<ComposerLanguage, ContextRailCopy> = {
  "zh-CN": {
    openSettings: "打开设置",
    composerPlaceholder: "问教练",
    composerPlaceholderPlan: "写下这一步",
    streaming: "教练正在思考…",
    openCoach: "\u6253\u5f00\u6559\u7ec3",
    viewContextWorking: "\u6b63\u5728\u5904\u7406",
    viewContextBlocker: "\u53d7\u963b",
    viewContextLatest: "\u6700\u8fd1\u7ed3\u679c",
    viewContextCoach: "\u6559\u7ec3\u4e0a\u4e0b\u6587",
  },
  "en-US": {
    openSettings: "Open Settings",
    composerPlaceholder: "Ask the coach",
    composerPlaceholderPlan: "Write the next step",
    streaming: "Coach thinking…",
    openCoach: "Open Coach",
    viewContextWorking: "Working",
    viewContextBlocker: "Blocker",
    viewContextLatest: "Latest",
    viewContextCoach: "Coach context",
  },
  "es-ES": {
    openSettings: "Abrir Ajustes",
    composerPlaceholder: "Dile al entrenador qué quieres construir o dónde estás bloqueado.",
    composerPlaceholderPlan: "Explica cómo ajustar este plan o cuál debería ser el siguiente paso.",
    streaming: "El entrenador está pensando…",
    openCoach: "Abrir Coach",
    viewContextWorking: "En curso",
    viewContextBlocker: "Bloqueado",
    viewContextLatest: "\u00daltimo resultado",
    viewContextCoach: "Contexto del coach",
  },
  "fr-FR": {
    openSettings: "Ouvrir les réglages",
    composerPlaceholder: "Dites au coach ce que vous voulez construire ou où vous êtes bloqué.",
    composerPlaceholderPlan: "Expliquez comment ajuster ce plan ou clarifiez la prochaine étape.",
    streaming: "Le coach réfléchit…",
    openCoach: "Ouvrir le coach",
    viewContextWorking: "En cours",
    viewContextBlocker: "Bloqu\u00e9",
    viewContextLatest: "Dernier r\u00e9sultat",
    viewContextCoach: "Contexte du coach",
  },
  "de-DE": {
    openSettings: "Einstellungen öffnen",
    composerPlaceholder: "Sag dem Coach, was du bauen möchtest oder wo du festhängst.",
    composerPlaceholderPlan: "Besprich, wie dieser Plan angepasst werden soll, oder kläre den nächsten Schritt.",
    streaming: "Coach denkt nach…",
    openCoach: "Coach \u00f6ffnen",
    viewContextWorking: "Wird verarbeitet",
    viewContextBlocker: "Blockiert",
    viewContextLatest: "Neuestes Ergebnis",
    viewContextCoach: "Coach-Kontext",
  },
  "ja-JP": {
    openSettings: "設定を開く",
    composerPlaceholder: "作りたいものや、行き詰まっている箇所をコーチに伝えてください。",
    composerPlaceholderPlan: "この計画の調整方法や次の一歩をコーチと整理してください。",
    streaming: "コーチが考えています…",
    openCoach: "\u30b3\u30fc\u30c1\u3092\u958b\u304f",
    viewContextWorking: "\u51e6\u7406\u4e2d",
    viewContextBlocker: "\u30d6\u30ed\u30c3\u30af\u4e2d",
    viewContextLatest: "\u6700\u65b0\u306e\u7d50\u679c",
    viewContextCoach: "\u30b3\u30fc\u30c1\u306e\u30b3\u30f3\u30c6\u30ad\u30b9\u30c8",
  },
  "ko-KR": {
    openSettings: "설정 열기",
    composerPlaceholder: "만들고 싶은 것 또는 막힌 지점을 코치에게 알려 주세요.",
    composerPlaceholderPlan: "이 계획을 어떻게 조정할지 또는 다음 단계를 코치와 정리하세요.",
    streaming: "코치가 생각 중입니다…",
    openCoach: "\ucf54\uce58 \uc5f4\uae30",
    viewContextWorking: "\ucc98\ub9ac \uc911",
    viewContextBlocker: "\ucc28\ub2e8\ub428",
    viewContextLatest: "\ucd5c\uadfc \uacb0\uacfc",
    viewContextCoach: "\ucf54\uce58 \ucee8\ud14d\uc2a4\ud2b8",
  },
  "pt-BR": {
    openSettings: "Abrir configurações",
    composerPlaceholder: "Diga ao coach o que você quer construir ou onde está bloqueado.",
    composerPlaceholderPlan: "Explique como ajustar este plano ou esclareça o próximo passo.",
    streaming: "O coach está pensando…",
    openCoach: "Abrir coach",
    viewContextWorking: "Em andamento",
    viewContextBlocker: "Bloqueado",
    viewContextLatest: "Resultado recente",
    viewContextCoach: "Contexto do coach",
  },
};

type TrainingUiCopy = Pick<
  Copy,
  | "trainingOpenCurrentCard"
  | "trainingReturnToCoach"
  | "trainingAnswerNow"
  | "trainingRecordStep"
  | "trainingStartStep"
  | "trainingEmptyTitle"
  | "trainingEmptyDescription"
>;

const trainingUiLocaleOverrides: Record<ComposerLanguage, TrainingUiCopy> = {
  "zh-CN": {
    trainingOpenCurrentCard: "\u7ee7\u7eed\uff1a\u6253\u5f00\u5f53\u524d\u5361\u7247",
    trainingReturnToCoach: "\u5e26\u7ed3\u679c\u56de\u5230\u6559\u7ec3",
    trainingAnswerNow: "\u73b0\u5728\u4f5c\u7b54",
    trainingRecordStep: "\u8bb0\u5f55\u8fd9\u4e00\u6b65",
    trainingStartStep: "\u5f00\u59cb\u8fd9\u4e00\u6b65",
    trainingEmptyTitle: "\u8fd8\u6ca1\u6709\u660e\u786e\u7684\u8bad\u7ec3\u5361\u7247",
    trainingEmptyDescription:
      "\u5f00\u59cb\u8bad\u7ec3\u540e\uff0c\u4f1a\u6309\u5f53\u524d\u91cd\u70b9\u751f\u6210\u4e00\u5f20\u5c0f\u800c\u53ef\u9a8c\u8bc1\u7684\u4efb\u52a1\u3002",
  },
  "en-US": {
    trainingOpenCurrentCard: "Continue: Open current card",
    trainingReturnToCoach: "Return result to Coach",
    trainingAnswerNow: "Answer now",
    trainingRecordStep: "Record this step",
    trainingStartStep: "Start this step",
    trainingEmptyTitle: "No training card yet",
    trainingEmptyDescription: "Start training to create one small, verifiable task from your current focus.",
  },
  "es-ES": {
    trainingOpenCurrentCard: "Continuar: abrir la tarjeta actual",
    trainingReturnToCoach: "Volver al coach con el resultado",
    trainingAnswerNow: "Responder ahora",
    trainingRecordStep: "Registrar este paso",
    trainingStartStep: "Empezar este paso",
    trainingEmptyTitle: "A\u00fan no hay una tarjeta de entrenamiento",
    trainingEmptyDescription:
      "Inicia el entrenamiento para crear una tarea peque\u00f1a y verificable a partir de tu enfoque actual.",
  },
  "fr-FR": {
    trainingOpenCurrentCard: "Continuer : ouvrir la carte actuelle",
    trainingReturnToCoach: "Ramener le r\u00e9sultat au coach",
    trainingAnswerNow: "R\u00e9pondre maintenant",
    trainingRecordStep: "Noter cette \u00e9tape",
    trainingStartStep: "Commencer cette \u00e9tape",
    trainingEmptyTitle: "Aucune carte d'entra\u00eenement pour le moment",
    trainingEmptyDescription:
      "Commencez l'entra\u00eenement pour cr\u00e9er une petite t\u00e2che v\u00e9rifiable depuis votre objectif actuel.",
  },
  "de-DE": {
    trainingOpenCurrentCard: "Weiter: Aktuelle Karte \u00f6ffnen",
    trainingReturnToCoach: "Ergebnis zum Coach zur\u00fcckbringen",
    trainingAnswerNow: "Jetzt antworten",
    trainingRecordStep: "Diesen Schritt festhalten",
    trainingStartStep: "Diesen Schritt beginnen",
    trainingEmptyTitle: "Noch keine Trainingskarte",
    trainingEmptyDescription:
      "Starte das Training, um aus deinem aktuellen Fokus eine kleine, \u00fcberpr\u00fcfbare Aufgabe zu erstellen.",
  },
  "ja-JP": {
    trainingOpenCurrentCard: "\u7d9a\u3051\u308b\uff1a\u73fe\u5728\u306e\u30ab\u30fc\u30c9\u3092\u958b\u304f",
    trainingReturnToCoach: "\u7d50\u679c\u3092\u30b3\u30fc\u30c1\u306b\u623b\u3059",
    trainingAnswerNow: "\u4eca\u3059\u3050\u56de\u7b54\u3059\u308b",
    trainingRecordStep: "\u3053\u306e\u30b9\u30c6\u30c3\u30d7\u3092\u8a18\u9332\u3059\u308b",
    trainingStartStep: "\u3053\u306e\u30b9\u30c6\u30c3\u30d7\u3092\u59cb\u3081\u308b",
    trainingEmptyTitle: "\u307e\u3060\u30c8\u30ec\u30fc\u30cb\u30f3\u30b0\u30ab\u30fc\u30c9\u304c\u3042\u308a\u307e\u305b\u3093",
    trainingEmptyDescription:
      "\u958b\u59cb\u3059\u308b\u3068\u3001\u73fe\u5728\u306e\u5b66\u7fd2\u306e\u7126\u70b9\u304b\u3089\u5c0f\u3055\u304f\u78ba\u8a8d\u3067\u304d\u308b\u8ab2\u984c\u3092\u4e00\u3064\u4f5c\u308a\u307e\u3059\u3002",
  },
  "ko-KR": {
    trainingOpenCurrentCard: "\uacc4\uc18d: \ud604\uc7ac \uce74\ub4dc \uc5f4\uae30",
    trainingReturnToCoach: "\uacb0\uacfc\ub97c \ucf54\uce58\uc5d0\uac8c \uac00\uc838\uac00\uae30",
    trainingAnswerNow: "\uc9c0\uae08 \ub2f5\ud558\uae30",
    trainingRecordStep: "\uc774 \ub2e8\uacc4 \uae30\ub85d\ud558\uae30",
    trainingStartStep: "\uc774 \ub2e8\uacc4 \uc2dc\uc791\ud558\uae30",
    trainingEmptyTitle: "\uc544\uc9c1 \ud6c8\ub828 \uce74\ub4dc\uac00 \uc5c6\uc2b5\ub2c8\ub2e4",
    trainingEmptyDescription:
      "\uc2dc\uc791\ud558\uba74 \ud604\uc7ac \ud559\uc2b5 \ucd08\uc810\uc5d0\uc11c \uc791\uace0 \ud655\uc778 \uac00\ub2a5\ud55c \uacfc\uc81c \ud558\ub098\ub97c \ub9cc\ub4ed\ub2c8\ub2e4.",
  },
  "pt-BR": {
    trainingOpenCurrentCard: "Continuar: abrir o cart\u00e3o atual",
    trainingReturnToCoach: "Levar o resultado ao coach",
    trainingAnswerNow: "Responder agora",
    trainingRecordStep: "Registrar esta etapa",
    trainingStartStep: "Come\u00e7ar esta etapa",
    trainingEmptyTitle: "Ainda n\u00e3o h\u00e1 um cart\u00e3o de treinamento",
    trainingEmptyDescription:
      "Inicie o treino para criar uma tarefa pequena e verific\u00e1vel a partir do seu foco atual.",
  },
};

type ComposerAccessibilityCopy = Pick<Copy, "composerAccessibility">;

type OrientationRailCopy = Pick<
  Copy,
  | "orientationNow"
  | "orientationState"
  | "orientationNext"
  | "orientationMore"
  | "orientationStateNeedsSetup"
  | "orientationStateWaiting"
  | "orientationStateWorking"
  | "orientationStateBlocked"
  | "orientationStateReady"
  | "orientationStateInterrupted"
>;

const orientationRailLocaleOverrides: Record<ComposerLanguage, OrientationRailCopy> = {
  "zh-CN": {
    orientationNow: "对象",
    orientationState: "状态",
    orientationNext: "下一步",
    orientationMore: "更多",
    orientationStateNeedsSetup: "待设置",
    orientationStateWaiting: "等待",
    orientationStateWorking: "进行中",
    orientationStateBlocked: "受阻",
    orientationStateReady: "就绪",
    orientationStateInterrupted: "中断",
  },
  "en-US": {
    orientationNow: "Now",
    orientationState: "State",
    orientationNext: "Next",
    orientationMore: "More",
    orientationStateNeedsSetup: "Needs setup",
    orientationStateWaiting: "Waiting",
    orientationStateWorking: "Working",
    orientationStateBlocked: "Blocked",
    orientationStateReady: "Ready",
    orientationStateInterrupted: "Interrupted",
  },
  "es-ES": {
    orientationNow: "Ahora",
    orientationState: "Estado",
    orientationNext: "Siguiente",
    orientationMore: "Más",
    orientationStateNeedsSetup: "Falta configurar",
    orientationStateWaiting: "Esperando",
    orientationStateWorking: "En curso",
    orientationStateBlocked: "Bloqueado",
    orientationStateReady: "Listo",
    orientationStateInterrupted: "Interrumpido",
  },
  "fr-FR": {
    orientationNow: "Maintenant",
    orientationState: "État",
    orientationNext: "Suite",
    orientationMore: "Plus",
    orientationStateNeedsSetup: "À configurer",
    orientationStateWaiting: "En attente",
    orientationStateWorking: "En cours",
    orientationStateBlocked: "Bloqué",
    orientationStateReady: "Prêt",
    orientationStateInterrupted: "Interrompu",
  },
  "de-DE": {
    orientationNow: "Jetzt",
    orientationState: "Stand",
    orientationNext: "Weiter",
    orientationMore: "Mehr",
    orientationStateNeedsSetup: "Einrichtung nötig",
    orientationStateWaiting: "Warten",
    orientationStateWorking: "Läuft",
    orientationStateBlocked: "Blockiert",
    orientationStateReady: "Bereit",
    orientationStateInterrupted: "Unterbrochen",
  },
  "ja-JP": {
    orientationNow: "対象",
    orientationState: "状態",
    orientationNext: "次",
    orientationMore: "詳細",
    orientationStateNeedsSetup: "要設定",
    orientationStateWaiting: "待機",
    orientationStateWorking: "進行中",
    orientationStateBlocked: "停止",
    orientationStateReady: "準備完了",
    orientationStateInterrupted: "中断",
  },
  "ko-KR": {
    orientationNow: "대상",
    orientationState: "상태",
    orientationNext: "다음",
    orientationMore: "더보기",
    orientationStateNeedsSetup: "설정 필요",
    orientationStateWaiting: "대기",
    orientationStateWorking: "진행 중",
    orientationStateBlocked: "차단됨",
    orientationStateReady: "준비됨",
    orientationStateInterrupted: "중단됨",
  },
  "pt-BR": {
    orientationNow: "Agora",
    orientationState: "Estado",
    orientationNext: "Próximo",
    orientationMore: "Mais",
    orientationStateNeedsSetup: "Precisa configurar",
    orientationStateWaiting: "Aguardando",
    orientationStateWorking: "Em andamento",
    orientationStateBlocked: "Bloqueado",
    orientationStateReady: "Pronto",
    orientationStateInterrupted: "Interrompido",
  },
};

const composerAccessibilityLocaleOverrides: Record<ComposerLanguage, ComposerAccessibilityCopy> = {
  "zh-CN": { composerAccessibility: "\u6d88\u606f\u8f93\u5165\u6846" },
  "en-US": { composerAccessibility: "Message composer" },
  "es-ES": { composerAccessibility: "Campo de mensaje" },
  "fr-FR": { composerAccessibility: "Zone de message" },
  "de-DE": { composerAccessibility: "Nachrichtenfeld" },
  "ja-JP": { composerAccessibility: "\u30e1\u30c3\u30bb\u30fc\u30b8\u5165\u529b\u6b04" },
  "ko-KR": { composerAccessibility: "\uba54\uc2dc\uc9c0 \uc785\ub825\ub780" },
  "pt-BR": { composerAccessibility: "Campo de mensagem" },
};

type LeftoverHonestyCopy = Pick<Copy, "leftoverNotLive" | "leftoverNotLiveHint">;

const leftoverHonestyLocaleOverrides: Record<ComposerLanguage, LeftoverHonestyCopy> = {
  "zh-CN": {
    leftoverNotLive: "这是此工作区里存下的旧痕迹，不是当前正式计划。",
    leftoverNotLiveHint: "这些只是提示，不会生成计划或任务。",
  },
  "en-US": {
    leftoverNotLive: "This is stored leftover on this workspace, not the live plan.",
    leftoverNotLiveHint: "These chips are hints only. They do not create a plan or task.",
  },
  "es-ES": {
    leftoverNotLive: "Esto es un resto guardado en este espacio, no el plan en vivo.",
    leftoverNotLiveHint: "Estas son solo pistas. No crean un plan ni una tarea.",
  },
  "fr-FR": {
    leftoverNotLive: "Ceci est un reste enregistré sur cet espace, pas le plan actuel.",
    leftoverNotLiveHint: "Ce sont seulement des indices. Ils ne créent ni plan ni tâche.",
  },
  "de-DE": {
    leftoverNotLive: "Das ist ein gespeicherter Rest in diesem Arbeitsbereich, nicht der aktuelle Plan.",
    leftoverNotLiveHint: "Das sind nur Hinweise. Sie erzeugen keinen Plan und keine Aufgabe.",
  },
  "ja-JP": {
    leftoverNotLive: "これはこのワークスペースに残った記録であり、現在の正式な計画ではありません。",
    leftoverNotLiveHint: "これは手がかりだけです。計画やタスクは作りません。",
  },
  "ko-KR": {
    leftoverNotLive: "이건 이 작업 공간에 남은 기록이지, 현재 공식 계획이 아닙니다.",
    leftoverNotLiveHint: "이건 힌트일 뿐입니다. 계획이나 과제를 만들지 않습니다.",
  },
  "pt-BR": {
    leftoverNotLive: "Isto é um resto guardado neste espaço, não o plano ao vivo.",
    leftoverNotLiveHint: "Isto são só dicas. Não criam plano nem tarefa.",
  },
};

export function resolveCopy(language: ComposerLanguage): Copy {
  return {
    ...defaultCopy,
    ...(copyTable[language] ?? {}),
    ...(resourceViewLocaleOverrides[language] ?? {}),
    ...contextRailLocaleOverrides[language],
    ...trainingUiLocaleOverrides[language],
    ...composerAccessibilityLocaleOverrides[language],
    ...orientationRailLocaleOverrides[language],
    ...leftoverHonestyLocaleOverrides[language],
  };
}
