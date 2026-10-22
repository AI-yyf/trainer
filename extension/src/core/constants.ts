import * as path from 'node:path';

import { trainerCommands } from '../../../shared/src/commands';

export const EXTENSION_ID = 'trainer';
export const OUTPUT_CHANNEL_NAME = 'Trainer';
export const WORKBENCH_VIEW_TYPE = 'trainer.workbench';
export const TRAINER_SIDEBAR_VIEW_ID = 'trainer.sidebar';

export const COMMAND_IDS = {
  openWorkbench: trainerCommands.openWorkbench,
  openViewInEditor: trainerCommands.openViewInEditor,
  configureProvider: trainerCommands.configureProvider,
  saveProvider: trainerCommands.saveProvider,
  clearProvider: trainerCommands.clearProvider,
  testProvider: trainerCommands.testProvider,
  refreshProviderModels: trainerCommands.refreshProviderModels,
  primeProviderModels: 'trainer.provider.primeModels',
  useProviderTemplate: trainerCommands.useProviderTemplate,
  switchProviderProfile: trainerCommands.switchProviderProfile,
  switchProviderModel: trainerCommands.switchProviderModel,
  setProviderThinking: trainerCommands.setProviderThinking,
  saveProviderProfile: trainerCommands.saveProviderProfile,
  refreshProviderProfiles: trainerCommands.refreshProviderProfiles,
  startProviderTrial: trainerCommands.startProviderTrial,
  setPersonalAccountTrust: trainerCommands.setPersonalAccountTrust,
  setTelemetryOptIn: trainerCommands.setTelemetryOptIn,
  refreshTelemetryStatus: trainerCommands.refreshTelemetryStatus,
  openWorkspaceConfig: trainerCommands.openWorkspaceConfig,
  restartSidecar: trainerCommands.restartSidecar,
  stopSidecar: trainerCommands.stopSidecar,
  sendMessage: trainerCommands.sendMessage,
  sendStreamMessage: 'trainer.session.sendStreamMessage',
  cancelStreamMessage: trainerCommands.cancelStreamMessage,
  resumeLatestCoachCheckpoint: trainerCommands.resumeLatestCoachCheckpoint,
  replayLatestCoachCheckpoint: trainerCommands.replayLatestCoachCheckpoint,
  listCoachSessions: trainerCommands.listCoachSessions,
  activateCoachSession: trainerCommands.activateCoachSession,
  newCoachSession: trainerCommands.newCoachSession,
  coachRemoteBoundary: trainerCommands.coachRemoteBoundary,
  remoteVerify: trainerCommands.remoteVerify,
  installRemoteCompanion: trainerCommands.remoteInstallCompanion,
  coachDebugLoop: trainerCommands.coachDebugLoop,
  coachFunctionContract: trainerCommands.coachFunctionContract,
  coachConceptMastery: trainerCommands.coachConceptMastery,
  coachVocabularyRecall: trainerCommands.coachVocabularyRecall,
  coachMathDerivation: trainerCommands.coachMathDerivation,
  coachWritingRevision: trainerCommands.coachWritingRevision,
  coachReadingTransfer: trainerCommands.coachReadingTransfer,
  generatePlan: trainerCommands.generatePlan,
  stageMaterialGenerate: trainerCommands.stageMaterialGenerate,
  updatePlan: trainerCommands.updatePlan,
  createGlobalPlan: trainerCommands.createGlobalPlan,
  linkCurrentProjectPlan: trainerCommands.linkCurrentProjectPlan,
  taskSpecify: trainerCommands.taskSpecify,
  nextTask: trainerCommands.nextTask,
  uploadResource: trainerCommands.uploadResource,
  captureResource: trainerCommands.captureResource,
  organizeResource: trainerCommands.organizeResource,
  exportResource: trainerCommands.exportResource,
  libraryFoldersList: trainerCommands.libraryFoldersList,
  libraryFoldersCreate: trainerCommands.libraryFoldersCreate,
  libraryFoldersRename: trainerCommands.libraryFoldersRename,
  libraryFoldersDelete: trainerCommands.libraryFoldersDelete,
  indexResources: trainerCommands.indexResources,
  searchResources: trainerCommands.searchResources,
  deleteResource: trainerCommands.deleteResource,
  confirmResourceOrganization: trainerCommands.confirmResourceOrganization,
  cancelResourceOrganization: trainerCommands.cancelResourceOrganization,
  restoreResource: trainerCommands.restoreResource,
  refreshResourceTrash: trainerCommands.refreshResourceTrash,
  openResource: trainerCommands.openResource,
  previewSandbox: trainerCommands.previewSandbox,
  createSandboxFile: trainerCommands.createSandboxFile,
  createSandboxDirectory: trainerCommands.createSandboxDirectory,
  renameSandboxPath: trainerCommands.renameSandboxPath,
  deleteSandboxPath: trainerCommands.deleteSandboxPath,
  deleteSandboxPaths: trainerCommands.deleteSandboxPaths,
  restoreSandboxPath: trainerCommands.restoreSandboxPath,
  refreshSandbox: trainerCommands.refreshSandbox,
  revealSandboxPath: trainerCommands.revealSandboxPath,
  chooseSandboxRoot: trainerCommands.chooseSandboxRoot,
  resetSandboxRoot: trainerCommands.resetSandboxRoot,
  chooseManagedDataFolder: trainerCommands.chooseManagedDataFolder,
  resetManagedDataFolder: trainerCommands.resetManagedDataFolder,
  moveManagedDataUnderRoot: trainerCommands.moveManagedDataUnderRoot,
  chooseTrainerWorkspaceRoot: trainerCommands.chooseTrainerWorkspaceRoot,
  migrateTrainerWorkspaceRoot: trainerCommands.migrateTrainerWorkspaceRoot,
  backupTrainerWorkspace: trainerCommands.backupTrainerWorkspace,
  restoreTrainerWorkspaceBackup: trainerCommands.restoreTrainerWorkspaceBackup,
  adoptWorkspaceProject: trainerCommands.adoptWorkspaceProject,
  chooseWorkspaceProject: trainerCommands.chooseWorkspaceProject,
  browseWorkspaceProject: trainerCommands.browseWorkspaceProject,
  ignoreWorkspaceProject: trainerCommands.ignoreWorkspaceProject,
  deleteWorkspaceProject: trainerCommands.deleteWorkspaceProject,
  retryWorkspaceAdmission: trainerCommands.retryWorkspaceAdmission,
  continueWorkspaceAdmission: trainerCommands.continueWorkspaceAdmission,
  abandonWorkspaceAdmission: trainerCommands.abandonWorkspaceAdmission,
  evaluateCurrentFile: trainerCommands.evaluateCurrentFile,
  remoteVerifyActiveFile: trainerCommands.remoteVerifyActiveFile,
  remoteVerifyCancel: trainerCommands.remoteVerifyCancel,
  remoteCompanionState: trainerCommands.remoteCompanionState,
  evaluateSelection: trainerCommands.evaluateSelection,
  refreshMemory: trainerCommands.refreshMemory,
  recordUserFeedback: trainerCommands.recordUserFeedback,
  refreshWorkspaceAuthority: trainerCommands.refreshWorkspaceAuthority,
  saveCoachSettings: trainerCommands.saveCoachSettings,
  generateSkillDraft: trainerCommands.generateSkillDraft,
  refreshLocalUsage: trainerCommands.refreshLocalUsage,
  grantMemoryShare: trainerCommands.grantMemoryShare,
  revokeMemoryShare: trainerCommands.revokeMemoryShare,
  evidenceEnqueue: trainerCommands.evidenceEnqueue,
  evidenceAdopt: trainerCommands.evidenceAdopt,
  evidenceReject: trainerCommands.evidenceReject,
  evidenceDefer: trainerCommands.evidenceDefer,
  evidenceRefreshQueue: trainerCommands.evidenceRefreshQueue,
  trainingCardStatusTransition: trainerCommands.trainingCardStatusTransition,
  trainingGenerateCard: trainerCommands.trainingGenerateCard,
  trainingFlashcardCreate: trainerCommands.trainingFlashcardCreate,
  trainingFlashcardAnswer: trainerCommands.trainingFlashcardAnswer,
  trainingTheoryDrillAnswer: trainerCommands.trainingTheoryDrillAnswer,
  trainingPracticeReturn: trainerCommands.trainingPracticeReturn,
  trainingReflect: trainerCommands.trainingReflect,
  trainingAttemptStart: trainerCommands.trainingAttemptStart,
  trainingAttemptUpdate: trainerCommands.trainingAttemptUpdate,
  trainingAttemptEvidence: trainerCommands.trainingAttemptEvidence,
  trainingAttemptRecover: trainerCommands.trainingAttemptRecover,
  trainingAttemptClose: trainerCommands.trainingAttemptClose,
  trainingAttemptProjection: trainerCommands.trainingAttemptProjection,
  trainingReturn: trainerCommands.trainingReturn,
  trainingReliabilityControl: trainerCommands.trainingReliabilityControl,
  trainingDependencySkillMapAction: trainerCommands.trainingDependencySkillMapAction,
  providerSpeedTest: trainerCommands.providerSpeedTest,
  trustWorkspaceWindow: trainerCommands.trustWorkspaceWindow,
  trainingReviewQueueAction: trainerCommands.trainingReviewQueueAction,
  trainingReviewArtifactAction: trainerCommands.trainingReviewArtifactAction,
  trainingScenarioLabAction: trainerCommands.trainingScenarioLabAction,
  // Internal recovery/training compatibility commands
  trainingRestoreOrchestration: 'trainer.trainingRestore.orchestrate',
  debugRestoreView: 'trainer.debug.restoreView',
  theoryDrillSubmitAnswer: trainerCommands.theoryDrillSubmitAnswer,
  reviewQueueAction: trainerCommands.reviewQueueAction,
  scenarioLabAction: trainerCommands.scenarioLabAction,
  // Browser capture lane (install bundle, pairing, revoke)
  browserCaptureInstall: 'trainer.browserCapture.install',
  browserCaptureOpenExtensionsPage: 'trainer.browserCapture.openExtensionsPage',
  browserCaptureStatus: 'trainer.browserCapture.status',
  browserCapturePairingCode: 'trainer.browserCapture.pairingCode',
  browserCaptureRevokePairing: 'trainer.browserCapture.revokePairing',
  // Research commands kept for internal compatibility
  createResearch: trainerCommands.createResearch,
  addResearchTheme: trainerCommands.addResearchTheme,
  activateResearchTheme: trainerCommands.activateResearchTheme,
  advanceResearch: trainerCommands.advanceResearch,
  researchMessage: trainerCommands.researchMessage,
  researchStreamMessage: 'trainer.research.messageStream',
  approveResearchDecision: trainerCommands.approveResearchDecision,
  getResearchStatus: trainerCommands.getResearchStatus,
} as const;

export const CONTEXT_KEYS = {
  providerConfigured: 'trainer.providerConfigured',
  workspaceTrusted: 'trainer.workspaceTrusted',
  sidecarReady: 'trainer.sidecarReady',
} as const;

export const STORAGE_KEYS = {
  providerConfig: 'trainer.provider.config',
  providerModelCache: 'trainer.provider.modelCache',
  providerProfileRegistry: 'trainer.provider.profileRegistry',
  providerActiveProfileId: 'trainer.provider.activeProfileId',
  providerProfileSwitchHistory: 'trainer.provider.profileSwitchHistory',
  memoryPersonalAccountTrust: 'trainer.memory.personalAccountTrust',
  sessionByWorkspacePrefix: 'trainer.session.byWorkspace',
  managedDataFolderByWorkspacePrefix: 'trainer.managedDataFolder.byWorkspace',
  pendingTransferPromotionScope: 'trainer.transfer.pendingPromotionScope',
} as const;

export const SECRET_KEYS = {
  providerApiKeyPrefix: 'trainer.provider.apiKey',
} as const;

export const BROWSER_CAPTURE = {
  /** Directory inside the VSIX/extension bundle that carries the unpacked capture extension. */
  bundleDirName: 'browser-capture',
  /** Marker file written by the packaging step and copied into the installed directory. */
  versionFileName: 'trainer-browser-capture.json',
  /** Managed install location (relative to the user's home directory). */
  installedRelativeDir: path.join('.trainer', 'browser-capture'),
  /** Pairing codes are displayed on an information bar; 10 minutes is the whole window. */
  pairingCodeTtlMs: 10 * 60 * 1_000,
  /** Draft forwarding cadence while a workbench surface is visible. */
  draftPollIntervalMs: 3_000,
  /**
   * How long a forwarded draft waits for the workbench's applied receipt
   * before the poll retries. The queue entry stays unacknowledged until the
   * receipt arrives, so a dropped delivery can never look delivered.
   */
  draftReceiptTimeoutMs: 4_000,
  /** Sidecar contract paths (see the pair_api_contract in the delivery notes). */
  pairCodePath: '/browser/pair-code',
  pairPath: '/browser/pair',
  pendingDraftsPath: '/browser/pending-drafts',
  pendingDraftsAckPath: '/browser/pending-drafts/ack',
} as const;

export const SIDECAR_DEFAULTS = {
  host: '127.0.0.1',
  portStart: 34891,
  portEnd: 34911,
  healthPath: '/health',
  // Health probes answer "is the HTTP endpoint up" — they must fail fast so a
  // busy sidecar event loop cannot stall UI actions for a full request window.
  healthProbeTimeoutMs: 2_000,
  // When the sidecar reported ready recently, skip re-probing before each
  // command and trust the cached status.
  healthCheckTtlMs: 10_000,
  // First launch after an install/update validates the bundled native
  // libraries; macOS exceeded 60s during the native regression, and Windows
  // hosted runners exceed 20s while the ~245 MB bundled tree is first opened
  // (AV scanning). Keep one bounded first-launch window on every platform,
  // separate from the fast health probes above.
  startupTimeoutMs: 120_000,
  requestTimeoutMs: 15_000,
  providerRequestTimeoutMs: 90_000,
  // A full coach turn runs the ReAct loop server-side; reasoning-first
  // models (kimi/m2-class) can legitimately spend minutes before the
  // first visible frame, so the coach lane gets its own generous window
  // instead of the single-probe 90s budget.
  coachTurnRequestTimeoutMs: 480_000,
  // Upper clamp for every sidecar request; only the coach turn opts into it
  // (all other lanes pass <= 90s, so the min() clamp leaves them untouched).
  maxRequestTimeoutMs: 480_000,
} as const;
