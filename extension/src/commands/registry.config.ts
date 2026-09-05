import {
  createProviderProfileFromDraftCommand,
  clearProviderCommand,
  configureProviderCommand,
  createProviderProfileFromTemplateCommand,
  switchProviderProfileCommand,
  testProviderCommand,
} from './providerCommands';
import {
  openWorkspaceConfigCommand,
  primeProviderModelsState,
  refreshProviderProfilesCommand,
  refreshProviderModelsCommand,
  saveProviderFromWebviewCommand,
  switchProviderModelCommand,
} from './providerWebviewCommands';
import { evaluateCurrentFileCommand, evaluateSelectionCommand } from './evaluationCommands';
import {
  debugRestoreViewCommand,
  grantMemoryShareCommand,
  recordUserFeedbackCommand,
  refreshMemoryCommand,
  refreshWorkspaceAuthorityCommand,
  revokeMemoryShareCommand,
  trainingRestoreOrchestrationCommand,
} from './memoryCommands';
import { openWorkbenchCommand } from './openWorkbench';
import { openCoachScenarioCommand } from './coachScenarioCommands';
import {
  chooseSandboxRootCommand,
  createSandboxFileCommand,
  createSandboxDirectoryCommand,
  chooseManagedDataFolderCommand,
  deleteSandboxPathsCommand,
  deleteSandboxPathCommand,
  deleteResourceCommand,
  confirmResourceOrganizationCommand,
  cancelResourceOrganizationCommand,
  restoreResourceCommand,
  refreshResourceTrashCommand,
  indexResourcesCommand,
  openResourceCommand,
  previewResourceCommand,
  refreshSandboxCommand,
  revealSandboxPathCommand,
  renameSandboxPathCommand,
  resetManagedDataFolderCommand,
  resetSandboxRootCommand,
  restoreSandboxPathCommand,
  searchResourcesCommand,
  uploadResourceCommand,
} from './resourceCommands';
import {
  createGlobalPlanCommand,
  generatePlanCommand,
  linkCurrentProjectPlanCommand,
  nextTaskCommand,
  replayLatestCoachCheckpointCommand,
  resumeLatestCoachCheckpointCommand,
  saveCoachSettingsCommand,
  sendMessageCommand,
  sendStreamMessageCommand,
  cancelStreamMessageCommand,
  specifyTaskCommand,
  updatePlanCommand,
} from './sessionCommands';
import { generateStageMaterialCommand } from './stageMaterialCommands';
import { restartSidecarCommand, stopSidecarCommand } from './sidecarCommands';
import {
  createResearchHandler,
  addResearchThemeHandler,
  activateResearchThemeHandler,
  advanceResearchHandler,
  researchMessageHandler,
  researchStreamMessageHandler,
  approveResearchDecisionHandler,
  getResearchStatusHandler,
} from './researchCommands';
import {
  flashcardCreateCommand,
  evidenceAdoptCommand,
  evidenceDeferCommand,
  evidenceEnqueueCommand,
  evidenceRefreshQueueCommand,
  evidenceRejectCommand,
  trainingCardStatusTransitionCommand,
  trainingDependencySkillMapActionCommand,
  trainingFlashcardAnswerCommand,
  trainingGenerateCardCommand,
  trainingPracticeReturnCommand,
  trainingReflectCommand,
  trainingReliabilityControlCommand,
  trainingReviewArtifactActionCommand,
  trainingReviewQueueActionCommand,
  trainingReturnCommand,
  trainingScenarioLabActionCommand,
  trainingTheoryDrillAnswerCommand,
} from './trainingCommands';
import { COMMAND_IDS } from '../core/constants';
import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';
import {
  adoptWorkspaceProjectCommand,
  backupTrainerWorkspaceCommand,
  browseWorkspaceProjectCommand,
  chooseTrainerWorkspaceRootCommand,
  chooseWorkspaceProjectCommand,
  ignoreWorkspaceProjectCommand,
  deleteWorkspaceProjectCommand,
  retryWorkspaceAdmissionCommand,
  continueWorkspaceAdmissionCommand,
  abandonWorkspaceAdmissionCommand,
  migrateTrainerWorkspaceRootCommand,
  restoreTrainerWorkspaceBackupCommand,
} from './workspaceAdmissionCommands';

export interface CommandRegistration {
  commandId: string;
  register: (
    ctx: CommandContext,
    payload?: unknown,
  ) => CommandExecutionResult | Promise<CommandExecutionResult>;
}

/**
 * Declarative command registration table. Order matters: entries are registered
 * in array order and must match the historical registration order exactly.
 */
export function buildCommandRegistrations(context: CommandContext): CommandRegistration[] {
  const httpClient = context.sidecarClient;
  const getState = context.getHostState;

  return [
    { commandId: COMMAND_IDS.openWorkbench, register: (ctx) => openWorkbenchCommand(ctx) },
    { commandId: COMMAND_IDS.configureProvider, register: (ctx) => configureProviderCommand(ctx) },
    { commandId: COMMAND_IDS.saveProvider, register: (ctx, payload) => saveProviderFromWebviewCommand(ctx, payload) },
    { commandId: COMMAND_IDS.clearProvider, register: (ctx) => clearProviderCommand(ctx) },
    {
      commandId: COMMAND_IDS.testProvider,
      register: (ctx, payload) =>
        testProviderCommand(ctx, payload as Parameters<typeof testProviderCommand>[1]),
    },
    {
      commandId: COMMAND_IDS.refreshProviderModels,
      register: (ctx, payload) =>
        refreshProviderModelsCommand(ctx, payload as Parameters<typeof refreshProviderModelsCommand>[1]),
    },
    {
      commandId: COMMAND_IDS.primeProviderModels,
      register: (ctx) => primeProviderModelsState(ctx).then(() => ({ ok: true })),
    },
    {
      commandId: COMMAND_IDS.useProviderTemplate,
      register: (ctx, payload) =>
        createProviderProfileFromTemplateCommand(
          ctx,
          payload as Parameters<typeof createProviderProfileFromTemplateCommand>[1],
        ),
    },
    {
      commandId: COMMAND_IDS.switchProviderProfile,
      register: (ctx, payload) =>
        switchProviderProfileCommand(ctx, payload as Parameters<typeof switchProviderProfileCommand>[1]),
    },
    {
      commandId: COMMAND_IDS.switchProviderModel,
      register: (ctx, payload) =>
        switchProviderModelCommand(ctx, payload as Parameters<typeof switchProviderModelCommand>[1]),
    },
    {
      commandId: COMMAND_IDS.saveProviderProfile,
      register: (ctx, payload) =>
        createProviderProfileFromDraftCommand(
          ctx,
          payload as Parameters<typeof createProviderProfileFromDraftCommand>[1],
        ),
    },
    { commandId: COMMAND_IDS.refreshProviderProfiles, register: (ctx) => refreshProviderProfilesCommand(ctx) },
    { commandId: COMMAND_IDS.openWorkspaceConfig, register: (ctx) => openWorkspaceConfigCommand(ctx) },
    { commandId: COMMAND_IDS.restartSidecar, register: (ctx) => restartSidecarCommand(ctx) },
    { commandId: COMMAND_IDS.stopSidecar, register: (ctx) => stopSidecarCommand(ctx) },
    { commandId: COMMAND_IDS.sendMessage, register: (ctx, payload) => sendMessageCommand(ctx, payload) },
    {
      commandId: COMMAND_IDS.sendStreamMessage,
      register: (ctx, payload) => sendStreamMessageCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.cancelStreamMessage,
      register: (ctx, payload) => cancelStreamMessageCommand(ctx, payload),
    },
    { commandId: COMMAND_IDS.resumeLatestCoachCheckpoint, register: (ctx) => resumeLatestCoachCheckpointCommand(ctx) },
    { commandId: COMMAND_IDS.replayLatestCoachCheckpoint, register: (ctx) => replayLatestCoachCheckpointCommand(ctx) },
    { commandId: COMMAND_IDS.coachRemoteBoundary, register: (ctx) => openCoachScenarioCommand(ctx, 'remoteBoundary') },
    { commandId: COMMAND_IDS.coachDebugLoop, register: (ctx) => openCoachScenarioCommand(ctx, 'debugLoop') },
    {
      commandId: COMMAND_IDS.coachFunctionContract,
      register: (ctx) => openCoachScenarioCommand(ctx, 'functionContract'),
    },
    {
      commandId: COMMAND_IDS.coachConceptMastery,
      register: (ctx) => openCoachScenarioCommand(ctx, 'conceptMastery'),
    },
    {
      commandId: COMMAND_IDS.coachVocabularyRecall,
      register: (ctx) => openCoachScenarioCommand(ctx, 'vocabularyRecall'),
    },
    {
      commandId: COMMAND_IDS.coachMathDerivation,
      register: (ctx) => openCoachScenarioCommand(ctx, 'mathDerivation'),
    },
    {
      commandId: COMMAND_IDS.coachWritingRevision,
      register: (ctx) => openCoachScenarioCommand(ctx, 'writingRevision'),
    },
    {
      commandId: COMMAND_IDS.coachReadingTransfer,
      register: (ctx) => openCoachScenarioCommand(ctx, 'readingTransfer'),
    },
    { commandId: COMMAND_IDS.generatePlan, register: (ctx, payload) => generatePlanCommand(ctx, payload) },
    {
      commandId: COMMAND_IDS.stageMaterialGenerate,
      register: (ctx, payload) => generateStageMaterialCommand(ctx, payload),
    },
    { commandId: COMMAND_IDS.updatePlan, register: (ctx, payload) => updatePlanCommand(ctx, payload) },
    { commandId: COMMAND_IDS.createGlobalPlan, register: (ctx, payload) => createGlobalPlanCommand(ctx, payload) },
    { commandId: COMMAND_IDS.linkCurrentProjectPlan, register: (ctx) => linkCurrentProjectPlanCommand(ctx) },
    { commandId: COMMAND_IDS.taskSpecify, register: (ctx, payload) => specifyTaskCommand(ctx, payload) },
    { commandId: COMMAND_IDS.nextTask, register: (ctx, payload) => nextTaskCommand(ctx, payload) },
    { commandId: COMMAND_IDS.uploadResource, register: (ctx, payload) => uploadResourceCommand(ctx, payload) },
    { commandId: COMMAND_IDS.indexResources, register: (ctx) => indexResourcesCommand(ctx) },
    { commandId: COMMAND_IDS.searchResources, register: (ctx, payload) => searchResourcesCommand(ctx, payload) },
    { commandId: COMMAND_IDS.deleteResource, register: (ctx, payload) => deleteResourceCommand(ctx, payload) },
    {
      commandId: COMMAND_IDS.confirmResourceOrganization,
      register: (ctx, payload) => confirmResourceOrganizationCommand(ctx, payload),
    },
    { commandId: COMMAND_IDS.cancelResourceOrganization, register: (ctx) => cancelResourceOrganizationCommand(ctx) },
    { commandId: COMMAND_IDS.restoreResource, register: (ctx, payload) => restoreResourceCommand(ctx, payload) },
    { commandId: COMMAND_IDS.refreshResourceTrash, register: (ctx) => refreshResourceTrashCommand(ctx) },
    { commandId: COMMAND_IDS.openResource, register: (ctx, payload) => openResourceCommand(ctx, payload) },
    { commandId: COMMAND_IDS.previewSandbox, register: (ctx, payload) => previewResourceCommand(ctx, payload) },
    { commandId: COMMAND_IDS.createSandboxFile, register: (ctx, payload) => createSandboxFileCommand(ctx, payload) },
    {
      commandId: COMMAND_IDS.createSandboxDirectory,
      register: (ctx, payload) => createSandboxDirectoryCommand(ctx, payload),
    },
    { commandId: COMMAND_IDS.renameSandboxPath, register: (ctx, payload) => renameSandboxPathCommand(ctx, payload) },
    { commandId: COMMAND_IDS.deleteSandboxPath, register: (ctx, payload) => deleteSandboxPathCommand(ctx, payload) },
    {
      commandId: COMMAND_IDS.deleteSandboxPaths,
      register: (ctx, payload) => deleteSandboxPathsCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.restoreSandboxPath,
      register: (ctx, payload) => restoreSandboxPathCommand(ctx, payload),
    },
    { commandId: COMMAND_IDS.refreshSandbox, register: (ctx) => refreshSandboxCommand(ctx) },
    { commandId: COMMAND_IDS.revealSandboxPath, register: (ctx, payload) => revealSandboxPathCommand(ctx, payload) },
    { commandId: COMMAND_IDS.chooseSandboxRoot, register: (ctx) => chooseSandboxRootCommand(ctx) },
    { commandId: COMMAND_IDS.resetSandboxRoot, register: (ctx) => resetSandboxRootCommand(ctx) },
    { commandId: COMMAND_IDS.chooseManagedDataFolder, register: (ctx) => chooseManagedDataFolderCommand(ctx) },
    { commandId: COMMAND_IDS.resetManagedDataFolder, register: (ctx) => resetManagedDataFolderCommand(ctx) },
    { commandId: COMMAND_IDS.chooseTrainerWorkspaceRoot, register: (ctx) => chooseTrainerWorkspaceRootCommand(ctx) },
    { commandId: COMMAND_IDS.migrateTrainerWorkspaceRoot, register: (ctx) => migrateTrainerWorkspaceRootCommand(ctx) },
    { commandId: COMMAND_IDS.backupTrainerWorkspace, register: (ctx) => backupTrainerWorkspaceCommand(ctx) },
    {
      commandId: COMMAND_IDS.restoreTrainerWorkspaceBackup,
      register: (ctx) => restoreTrainerWorkspaceBackupCommand(ctx),
    },
    {
      commandId: COMMAND_IDS.adoptWorkspaceProject,
      register: (ctx, payload) =>
        adoptWorkspaceProjectCommand(ctx, payload as Parameters<typeof adoptWorkspaceProjectCommand>[1]),
    },
    { commandId: COMMAND_IDS.chooseWorkspaceProject, register: (ctx) => chooseWorkspaceProjectCommand(ctx) },
    { commandId: COMMAND_IDS.browseWorkspaceProject, register: (ctx) => browseWorkspaceProjectCommand(ctx) },
    { commandId: COMMAND_IDS.ignoreWorkspaceProject, register: (ctx) => ignoreWorkspaceProjectCommand(ctx) },
    {
      commandId: COMMAND_IDS.deleteWorkspaceProject,
      register: (ctx, payload) =>
        deleteWorkspaceProjectCommand(ctx, payload as Parameters<typeof deleteWorkspaceProjectCommand>[1]),
    },
    {
      commandId: COMMAND_IDS.retryWorkspaceAdmission,
      register: (ctx, payload) =>
        retryWorkspaceAdmissionCommand(ctx, payload as Parameters<typeof retryWorkspaceAdmissionCommand>[1]),
    },
    {
      commandId: COMMAND_IDS.continueWorkspaceAdmission,
      register: (ctx, payload) =>
        continueWorkspaceAdmissionCommand(ctx, payload as Parameters<typeof continueWorkspaceAdmissionCommand>[1]),
    },
    { commandId: COMMAND_IDS.abandonWorkspaceAdmission, register: (ctx) => abandonWorkspaceAdmissionCommand(ctx) },
    {
      commandId: COMMAND_IDS.evaluateCurrentFile,
      register: (ctx, payload) => evaluateCurrentFileCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.evaluateSelection,
      register: (ctx, payload) => evaluateSelectionCommand(ctx, payload),
    },
    { commandId: COMMAND_IDS.refreshMemory, register: (ctx) => refreshMemoryCommand(ctx) },
    { commandId: COMMAND_IDS.recordUserFeedback, register: (ctx, payload) => recordUserFeedbackCommand(ctx, payload) },
    { commandId: COMMAND_IDS.refreshWorkspaceAuthority, register: (ctx) => refreshWorkspaceAuthorityCommand(ctx) },
    { commandId: COMMAND_IDS.saveCoachSettings, register: (ctx, payload) => saveCoachSettingsCommand(ctx, payload) },
    { commandId: COMMAND_IDS.grantMemoryShare, register: (ctx) => grantMemoryShareCommand(ctx) },
    { commandId: COMMAND_IDS.revokeMemoryShare, register: (ctx, payload) => revokeMemoryShareCommand(ctx, payload) },
    { commandId: COMMAND_IDS.evidenceEnqueue, register: (ctx, payload) => evidenceEnqueueCommand(ctx, payload) },
    { commandId: COMMAND_IDS.evidenceAdopt, register: (ctx, payload) => evidenceAdoptCommand(ctx, payload) },
    { commandId: COMMAND_IDS.evidenceReject, register: (ctx, payload) => evidenceRejectCommand(ctx, payload) },
    { commandId: COMMAND_IDS.evidenceDefer, register: (ctx, payload) => evidenceDeferCommand(ctx, payload) },
    {
      commandId: COMMAND_IDS.evidenceRefreshQueue,
      register: (ctx, payload) => evidenceRefreshQueueCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.trainingRestoreOrchestration,
      register: (ctx, payload) => trainingRestoreOrchestrationCommand(ctx, payload),
    },
    { commandId: COMMAND_IDS.debugRestoreView, register: (ctx, payload) => debugRestoreViewCommand(ctx, payload) },
    {
      commandId: COMMAND_IDS.trainingCardStatusTransition,
      register: (ctx, payload) => trainingCardStatusTransitionCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.trainingGenerateCard,
      register: (ctx, payload) => trainingGenerateCardCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.trainingFlashcardCreate,
      register: (ctx, payload) => flashcardCreateCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.trainingFlashcardAnswer,
      register: (ctx, payload) => trainingFlashcardAnswerCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.trainingTheoryDrillAnswer,
      register: (ctx, payload) => trainingTheoryDrillAnswerCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.trainingPracticeReturn,
      register: (ctx, payload) => trainingPracticeReturnCommand(ctx, payload),
    },
    { commandId: COMMAND_IDS.trainingReflect, register: (ctx, payload) => trainingReflectCommand(ctx, payload) },
    { commandId: COMMAND_IDS.trainingReturn, register: (ctx, payload) => trainingReturnCommand(ctx, payload) },
    {
      commandId: COMMAND_IDS.trainingReliabilityControl,
      register: (ctx, payload) => trainingReliabilityControlCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.trainingDependencySkillMapAction,
      register: (ctx, payload) => trainingDependencySkillMapActionCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.trainingReviewQueueAction,
      register: (ctx, payload) => trainingReviewQueueActionCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.trainingReviewArtifactAction,
      register: (ctx, payload) => trainingReviewArtifactActionCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.trainingScenarioLabAction,
      register: (ctx, payload) => trainingScenarioLabActionCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.theoryDrillSubmitAnswer,
      register: (ctx, payload) => trainingTheoryDrillAnswerCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.reviewQueueAction,
      register: (ctx, payload) => trainingReviewQueueActionCommand(ctx, payload),
    },
    {
      commandId: COMMAND_IDS.scenarioLabAction,
      register: (ctx, payload) => trainingScenarioLabActionCommand(ctx, payload),
    },
    // Research compatibility commands stay registered so legacy bridges still work,
    // but they are no longer part of the primary coach-first command surface.
    { commandId: COMMAND_IDS.createResearch, register: createResearchHandler(httpClient, getState) },
    { commandId: COMMAND_IDS.addResearchTheme, register: addResearchThemeHandler(httpClient, getState) },
    { commandId: COMMAND_IDS.activateResearchTheme, register: activateResearchThemeHandler(httpClient, getState) },
    { commandId: COMMAND_IDS.advanceResearch, register: advanceResearchHandler(httpClient, getState) },
    { commandId: COMMAND_IDS.researchMessage, register: researchMessageHandler(httpClient, getState) },
    {
      commandId: COMMAND_IDS.researchStreamMessage,
      register: researchStreamMessageHandler(httpClient, getState, context.workbench),
    },
    { commandId: COMMAND_IDS.approveResearchDecision, register: approveResearchDecisionHandler(httpClient, getState) },
    { commandId: COMMAND_IDS.getResearchStatus, register: getResearchStatusHandler(httpClient, getState) },
  ];
}
