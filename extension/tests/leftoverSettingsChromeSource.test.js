'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const workbenchDataPath = path.resolve(__dirname, '..', 'src', 'core', 'workbenchData.ts');
const workbenchStatePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'app',
  'useWorkbenchState.ts',
);
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const routersPath = path.resolve(__dirname, '..', '..', 'server', 'app', 'api', 'routers.py');
const bundledRoutersPath = path.resolve(
  __dirname,
  '..',
  'bundled',
  'server',
  'app',
  'api',
  'routers.py',
);
const bundledRecoveryPath = path.resolve(
  __dirname,
  '..',
  'bundled',
  'server',
  'app',
  'memory',
  'workspace_recovery.py',
);

test('workspace settings chrome does not leftover-fill language, answer mode, or coach defaults', () => {
  const workbenchData = fs.readFileSync(workbenchDataPath, 'utf8');
  const workbenchState = fs.readFileSync(workbenchStatePath, 'utf8');

  assert.match(
    workbenchData,
    /responseLanguage: responseLanguage \?\? \(sameWorkspace \? fallback\?\.responseLanguage : undefined\)/,
  );
  assert.match(
    workbenchData,
    /answerMode: answerMode \?\? \(sameWorkspace \? fallback\?\.answerMode : undefined\)/,
  );
  assert.match(workbenchData, /const chromeDefaults = sameWorkspace \? fallback\?\.coachDefaults : undefined;/);
  assert.doesNotMatch(
    workbenchData,
    /responseLanguage: responseLanguage \?\? fallback\?\.responseLanguage,/,
  );
  assert.doesNotMatch(workbenchData, /answerMode: answerMode \?\? fallback\?\.answerMode,/);

  assert.match(workbenchState, /function workspaceChromeAllowsLeftoverFill\(/);
  assert.match(
    workbenchState,
    /const previousWorkspaceId = state\.data\.memory\.workspace\?\.workspaceId;/,
  );
  assert.match(
    workbenchState,
    /syncLayoutFromBootstrap\(\s*state\.layout,\s*nextData,\s*previousWorkspaceId,/,
  );
  assert.match(workbenchState, /const layoutChrome = leftoverFill \? layout : defaultPersistedState;/);
  assert.doesNotMatch(
    workbenchState,
    /const nextLanguage = workspace\?\.responseLanguage \?\? layout\.composerLanguage;/,
  );
  assert.doesNotMatch(
    workbenchState,
    /const nextAnswerMode = workspace\?\.answerMode \?\? layout\.composerAnswerMode;/,
  );
  assert.doesNotMatch(workbenchState, /: layout\.coachDefaults;/);
});

test('leftover Settings profile/rhythm is not live Settings identity when recovered (empty or with-step)', () => {
  const workbenchData = fs.readFileSync(workbenchDataPath, 'utf8');
  const appSource = fs.readFileSync(appPath, 'utf8');

  assert.match(workbenchData, /leftoverSettingsProfileRhythmIsNotLive\(/);
  assert.match(workbenchData, /leftoverSettingsLearnerProjectOnboardingIsNotLive\(/);
  assert.match(workbenchData, /leftoverResourceSandboxPreviewIsNotLive\(/);
  assert.match(workbenchData, /leftoverResourceSandboxStateIsNotLive\(/);
  assert.match(workbenchData, /leftoverResourceLibraryListIsNotLive\(/);
  assert.match(workbenchData, /leftoverChromeIdentity/);
  assert.match(workbenchData, /leftoverTrainingHandoffNotLive/);
  assert.match(workbenchData, /selectedCardId: leftoverTrainingHandoffNotLive/);
  assert.match(workbenchData, /latestLearningVerifiedResult: leftoverTrainingHandoffNotLive/);
  assert.match(workbenchData, /latestLearningPartialProgress: leftoverTrainingHandoffNotLive/);
  assert.match(workbenchData, /reviewArtifact: leftoverTrainingHandoffNotLive/);
  assert.match(workbenchData, /leftoverCoachConversationIsNotLive\(/);
  assert.match(workbenchData, /leftoverSuggestedActionsIsNotLive\(/);
  assert.match(workbenchData, /leftoverMintingSuggestedActionsAreNotLive\(/);
  assert.match(workbenchData, /leftoverFirstLookHeadlineIsNotLive\(/);
  assert.match(workbenchData, /leftoverEvaluationHeadlineIsNotLive\(/);
  assert.match(workbenchData, /leftoverStreamingCheckpointIsNotLive\(/);
  assert.match(workbenchData, /leftoverTransferSkillIsNotLive\(/);
  assert.match(workbenchData, /preferRecoveredTransferSkill\(/);
  assert.match(workbenchData, /preferredRhythm: settingsProfileRhythmNotLive/);
  assert.match(workbenchData, /coachDefaults: settingsProfileRhythmNotLive/);
  assert.match(workbenchData, /learnerName: settingsLearnerProjectOnboardingNotLive/);
  assert.match(workbenchData, /onboardingRequest: settingsLearnerProjectOnboardingNotLive/);
  assert.match(workbenchData, /sandboxPreview: resourceSandboxPreviewNotLive/);
  assert.match(workbenchData, /sandboxState: resourceSandboxStateNotLive/);
  assert.match(workbenchData, /resources: resourceLibraryListNotLive \? \[\] : patch\.resources/);
  assert.match(workbenchData, /conversation: coachConversationNotLive \? \[\] : patch\.conversation/);
  assert.match(workbenchData, /suggestedActions: suggestedActionsNotLive \? \[\] : leftoverHonestSuggestedActions/);
  assert.match(workbenchData, /latestStreamingCheckpoint:/);
  assert.match(workbenchData, /streamingCheckpointNotLive && !patch\.streamingState\?\.isStreaming/);
  assert.match(
    workbenchData,
    /latestStreamingCheckpoint:\s+streamingCheckpointNotLive && !patch\.streamingState\?\.isStreaming/,
  );
  assert.match(workbenchData, /primaryAction === 'resume_checkpoint'/);
  assert.match(workbenchData, /latestTransferState: transferSkillNotLive/);
  assert.match(workbenchData, /firstLookSummary: undefined/);
  assert.match(workbenchData, /headline: evaluationHeadlineNotLive \? '' : patch\.evaluation\.headline/);
  assert.match(workbenchData, /activeThread: coachConversationNotLive \? undefined : patch\.memory\.activeThread/);

  assert.match(appSource, /leftoverSettingsProfileRhythmIsNotLive\(/);
  assert.match(appSource, /leftoverSettingsLearnerProjectOnboardingIsNotLive\(/);
  assert.match(appSource, /leftoverResourceSandboxPreviewIsNotLive\(/);
  assert.match(appSource, /leftoverResourceSandboxStateIsNotLive\(/);
  assert.match(appSource, /leftoverResourceLibraryListIsNotLive\(/);
  assert.match(appSource, /primaryAction: "open_coach"/);
  assert.match(appSource, /leftoverResourceLibraryListNotLive && resourcesOrientation/);
  assert.match(appSource, /leftoverNote=\{leftoverResourceLibraryListNotLive \? t\.leftoverNotLive : undefined\}/);
  assert.match(appSource, /leftoverNote=\{leftoverTrainingHandoffChromeNotLive \? t\.leftoverNotLive : undefined\}/);
  assert.match(appSource, /runtimePlanId: data\.memory\.workspace\?\.latestPlanRuntime\?\.planId,/);
  assert.match(appSource, /leftoverCoachConversationIsNotLive\(/);
  assert.match(appSource, /leftoverSuggestedActionsIsNotLive\(/);
  assert.match(appSource, /leftoverMintingSuggestedActionsAreNotLive\(/);
  assert.match(appSource, /leftoverFirstLookHeadlineIsNotLive\(/);
  assert.match(appSource, /leftoverEvaluationHeadlineIsNotLive\(/);
  assert.match(appSource, /leftoverStreamingCheckpointIsNotLive\(/);
  assert.match(appSource, /leftoverTransferSkillIsNotLive\(/);
  assert.match(appSource, /preferRecoveredTransferSkill\(/);
  assert.match(
    appSource,
    /leftoverSettingsProfileRhythmNotLive \? undefined : data\.profile\.preferredRhythm/,
  );
  assert.match(
    appSource,
    /leftoverSettingsProfileRhythmNotLive \? undefined : data\.profile\.preferredLearningMode/,
  );
  assert.match(appSource, /leftoverSettingsProfileRhythmNotLive\s*\?\s*"empty"/);
  assert.match(
    appSource,
    /leftoverSettingsProfileRhythmNotLive \? defaultCoachDefaults : layout\.coachDefaults/,
  );
  assert.match(appSource, /workspaceAuthority=\{liveSandboxState\?\.authority\}/);
  assert.match(appSource, /readWorkspaceTrustStateFromCapabilitySummary\(/);
  assert.match(
    appSource,
    /leftoverSandboxPreviewNotLive \? undefined : data\.memory\.sandboxPreview/,
  );
  assert.match(
    appSource,
    /const liveSandboxPreview = leftoverSandboxPreviewNotLive/,
  );
  assert.match(
    appSource,
    /const liveSelectedResourceDetail = leftoverResourceSelectedDetailNotLive/,
  );
  assert.match(
    appSource,
    /const liveResources = leftoverResourceLibraryListNotLive \? \[\] : data\.resources/,
  );
  assert.match(
    appSource,
    /const liveSandboxState = leftoverResourceSandboxStateNotLive/,
  );
  assert.match(appSource, /resources=\{liveResources\}/);
  assert.match(appSource, /sandboxState=\{liveSandboxState\}/);
  assert.match(
    appSource,
    /const liveConversation = leftoverCoachConversationNotLive \? \[\] : data\.conversation/,
  );
  assert.match(appSource, /leftoverMintingSuggestedActionsNotLive \|\| leftoverSuggestedActionNotLive/);
  // Pressure / leftover-not-live / closed-loop Return mint honesty: plan|task|next_task chips stay filtered
  // (backend stamps → leftoverSuggestedActionNotLive).
  assert.match(
    appSource,
    /leftoverMintingSuggestedActionsNotLive \|\| leftoverSuggestedActionNotLive\s*\?\s*data\.suggestedActions\.filter\(\s*\(item\) => !\["plan", "task", "next_task", "card"\]\.includes\(String\(item\.action \?\? ""\)\)/,
  );
  assert.match(appSource, /const liveFirstLookSummary = leftoverFirstLookHeadlineNotLive/);
  assert.match(appSource, /const liveEvaluationHeadline = leftoverEvaluationHeadlineNotLive/);
  assert.match(appSource, /const visibleActions = liveSuggestedActions/);
  assert.match(appSource, /const firstLookSummary = liveFirstLookSummary/);
  assert.match(appSource, /firstLookRecommendedNext: liveFirstLookSummary\?\.recommendedNextStep/);
  assert.match(appSource, /const liveLatestStreamingCheckpoint = leftoverStreamingCheckpointNotLive/);
  assert.match(appSource, /const leftoverTransferSkillNotLive = leftoverTransferSkillIsNotLive/);
  assert.match(appSource, /const liveTransferState = preferRecoveredTransferSkill/);
  assert.match(appSource, /transferState: liveTransferState/);
  assert.match(appSource, /transferState: liveTransferState\?\.state/);
  assert.match(appSource, /leftoverStreamingCheckpointNotLive\s*\?\s*false/);
  assert.match(
    appSource,
    /liveConversation\.map\(\(message\) => localizeConversationMessage/,
  );
  assert.match(
    appSource,
    /leftoverSettingsProfileRhythmNotLive\s*\?\s*null\s*:\s*data\.profile\.preferredRhythm/,
  );
  assert.match(
    appSource,
    /leftoverSettingsLearnerProjectOnboardingNotLive \? undefined : data\.profile\.learnerName/,
  );
  assert.match(
    appSource,
    /leftoverSettingsLearnerProjectOnboardingNotLive \? undefined : data\.profile\.targetProject/,
  );
  assert.match(
    appSource,
    /leftoverSettingsLearnerProjectOnboardingNotLive \? undefined : data\.profile\.onboardingRequest/,
  );
  assert.match(
    appSource,
    /leftoverSettingsLearnerProjectOnboardingNotLive \? undefined : data\.profile\.projectContext/,
  );
  assert.match(
    appSource,
    /leftoverSettingsLearnerProjectOnboardingNotLive\s*\?\s*null\s*:\s*data\.profile\.targetProject/,
  );
  assert.match(
    appSource,
    /leftoverSettingsLearnerProjectOnboardingNotLive\s*\?\s*null\s*:\s*data\.profile\.onboardingRequest/,
  );

  const routers = fs.readFileSync(routersPath, 'utf8');
  const bundledRouters = fs.readFileSync(bundledRoutersPath, 'utf8');
  assert.match(routers, /leftover_settings_profile_rhythm_is_not_live\(/);
  assert.match(routers, /leftover_settings_learner_project_onboarding_is_not_live\(/);
  assert.match(routers, /leftover_resource_sandbox_preview_is_not_live\(/);
  assert.match(routers, /leftover_resource_sandbox_state_is_not_live\(/);
  assert.match(routers, /leftover_resource_selected_detail_is_not_live\(/);
  assert.match(routers, /leftover_resource_library_list_is_not_live\(/);
  assert.match(routers, /leftover_training_handoff_chrome_is_not_live\(/);
  assert.match(routers, /leftover_coach_conversation_is_not_live\(/);
  assert.match(routers, /leftover_suggested_actions_is_not_live\(/);
  assert.match(routers, /leftover_minting_suggested_actions_are_not_live\(/);
  assert.match(routers, /honest_suggested_actions_without_live_object\(/);
  assert.match(routers, /leftover_first_look_headline_is_not_live\(/);
  assert.match(routers, /leftover_evaluation_headline_is_not_live\(/);
  assert.match(routers, /leftover_streaming_checkpoint_is_not_live\(/);
  assert.match(routers, /leftover_transfer_skill_is_not_live\(/);
  assert.match(routers, /prefer_recovered_transfer_skill\(/);
  assert.match(routers, /workspace_memory\.pop\("latest_streaming_checkpoint", None\)/);
  assert.ok(
    routers.indexOf('workspace_memory.pop("latest_streaming_checkpoint", None)') <
      routers.lastIndexOf('orientation = build_coach_orientation_from_snapshot('),
  );
  assert.ok(
    routers.indexOf('prefer_recovered_transfer_skill(') <
      routers.lastIndexOf('orientation = build_coach_orientation_from_snapshot('),
  );
  assert.match(routers, /"suggested_actions": \[\]/);
  assert.match(routers, /update=\{"first_look_summary": None\}/);
  assert.match(routers, /update=\{"summary": ""\}/);
  assert.match(routers, /workspace_memory\.pop\("coach_defaults", None\)/);
  assert.match(routers, /workspace_memory\.pop\("sandbox_preview", None\)/);
  assert.match(routers, /workspace_memory\.pop\("sandbox_state", None\)/);
  assert.match(routers, /workspace_memory\.pop\("selected_resource_detail", None\)/);
  assert.match(routers, /workspace_memory\.pop\("selected_card_id", None\)/);
  assert.match(routers, /update=\{"resources": kept_resources\}/);
  assert.match(routers, /snapshot\.messages = \[\]/);
  assert.match(routers, /update=\{"active_thread": None\}/);
  assert.match(routers, /"learner_name": ""/);
  assert.match(routers, /"onboarding_request": ""/);
  assert.match(routers, /"project_context": ""/);
  assert.match(bundledRouters, /leftover_settings_profile_rhythm_is_not_live\(/);
  assert.match(bundledRouters, /leftover_settings_learner_project_onboarding_is_not_live\(/);
  assert.match(bundledRouters, /leftover_resource_sandbox_preview_is_not_live\(/);
  assert.match(bundledRouters, /leftover_resource_sandbox_state_is_not_live\(/);
  assert.match(bundledRouters, /leftover_resource_selected_detail_is_not_live\(/);
  assert.match(bundledRouters, /leftover_resource_library_list_is_not_live\(/);
  assert.match(bundledRouters, /leftover_training_handoff_chrome_is_not_live\(/);
  assert.match(bundledRouters, /leftover_coach_conversation_is_not_live\(/);
  assert.match(bundledRouters, /leftover_suggested_actions_is_not_live\(/);
  assert.match(bundledRouters, /leftover_minting_suggested_actions_are_not_live\(/);
  assert.match(bundledRouters, /honest_suggested_actions_without_live_object\(/);
  assert.match(bundledRouters, /leftover_first_look_headline_is_not_live\(/);
  assert.match(bundledRouters, /leftover_evaluation_headline_is_not_live\(/);
  assert.match(bundledRouters, /leftover_streaming_checkpoint_is_not_live\(/);
  assert.match(bundledRouters, /leftover_transfer_skill_is_not_live\(/);
  assert.match(bundledRouters, /prefer_recovered_transfer_skill\(/);
  assert.match(bundledRouters, /workspace_memory\.pop\("latest_streaming_checkpoint", None\)/);
  assert.ok(
    bundledRouters.indexOf('workspace_memory.pop("latest_streaming_checkpoint", None)') <
      bundledRouters.lastIndexOf('orientation = build_coach_orientation_from_snapshot('),
  );
  assert.ok(
    bundledRouters.indexOf('prefer_recovered_transfer_skill(') <
      bundledRouters.lastIndexOf('orientation = build_coach_orientation_from_snapshot('),
  );
  assert.match(bundledRouters, /"suggested_actions": \[\]/);
  assert.match(bundledRouters, /update=\{"first_look_summary": None\}/);
  assert.match(bundledRouters, /update=\{"summary": ""\}/);
  assert.match(bundledRouters, /workspace_memory\.pop\("coach_defaults", None\)/);
  assert.match(bundledRouters, /workspace_memory\.pop\("sandbox_preview", None\)/);
  assert.match(bundledRouters, /workspace_memory\.pop\("sandbox_state", None\)/);
  assert.match(bundledRouters, /workspace_memory\.pop\("selected_resource_detail", None\)/);
  assert.match(bundledRouters, /workspace_memory\.pop\("selected_card_id", None\)/);
  const bundledRecovery = fs.readFileSync(bundledRecoveryPath, 'utf8');
  assert.match(bundledRecovery, /def leftover_streaming_checkpoint_is_not_live\(/);
  assert.match(bundledRecovery, /def leftover_transfer_skill_is_not_live\(/);
  assert.match(bundledRecovery, /def leftover_minting_suggested_actions_are_not_live\(/);
  assert.match(bundledRecovery, /def prefer_recovered_transfer_skill\(/);
  assert.match(
    bundledRecovery,
    /Recovered-with-step\s+also stays leftover-not-live: a recovered plan step is Plan identity, not\s+Resources library identity/,
  );
  assert.match(
    bundledRecovery,
    /Recovered-with-step\s+also stays leftover-not-live: a recovered plan step is Plan identity/,
  );
  const governancePath = path.resolve(
    __dirname,
    '..',
    '..',
    'shared',
    'src',
    'planOrientationGovernance.ts',
  );
  const governance = fs.readFileSync(governancePath, 'utf8');
  assert.match(governance, /Recovered-with-step is still leftover-not-live for Settings/);
  assert.match(governance, /A recovered plan step is Plan identity, not Settings identity/);
  assert.match(governance, /Recovered-with-step is still leftover-not-live for Resources/);
  assert.match(
    governance,
    /export function leftoverSettingsProfileRhythmIsNotLive\([\s\S]*?return Boolean\(input\.recovered\);/,
  );
  assert.match(governance, /function streakAdaptsWithoutInventingLiveObjects\(/);
  assert.match(governance, /function pressureAdaptsWithoutInventingLiveObjects\(/);
  assert.match(governance, /pressureBlocksLiveObjectMint/);
  assert.match(governance, /streakBlocksLiveObjectMint/);
  assert.match(appSource, /streakAdaptsWithoutInventingLiveObjects\(/);
  assert.match(appSource, /pressureAdaptsWithoutInventingLiveObjects\(/);
  assert.match(
    appSource,
    /streakBlocksLiveObjectMint:\s*data\.memory\.coachingAdaptation\?\.streakBlocksLiveObjectMint === true \|\|\s*data\.coachFocus\?\.streakBlocksLiveObjectMint === true/,
  );
  assert.match(
    appSource,
    /pressureBlocksLiveObjectMint:\s*data\.memory\.coachingAdaptation\?\.pressureBlocksLiveObjectMint === true \|\|\s*data\.coachFocus\?\.pressureBlocksLiveObjectMint === true/,
  );
  assert.match(
    appSource,
    /data\.memory\.coachingAdaptation\?\.closedLoopReturnBlocksTaskMint === true \|\|\s*data\.coachFocus\?\.closedLoopReturnBlocksTaskMint === true/,
  );
  assert.match(workbenchData, /pressure_blocks_live_object_mint/);
  assert.match(workbenchData, /pressureBlocksLiveObjectMint/);
  assert.match(workbenchData, /streak_blocks_live_object_mint/);
  assert.match(workbenchData, /streakBlocksLiveObjectMint/);
  assert.match(workbenchData, /closed_loop_return_blocks_task_mint/);
  assert.match(workbenchData, /closedLoopReturnBlocksTaskMint/);
  assert.match(
    workbenchData,
    /asBoolean\(record\.pressure_blocks_live_object_mint\)/,
  );
  assert.match(
    workbenchData,
    /asBoolean\(record\.streak_blocks_live_object_mint\)/,
  );
  assert.match(
    workbenchData,
    /asBoolean\(record\.closed_loop_return_blocks_task_mint\)/,
  );
});

test('card-status leftover-not-live identity is fail-closed in sidecar, bundled copy, and host', () => {
  const identityPath = path.resolve(__dirname, '..', '..', 'server', 'app', 'api', 'training_card_identity.py');
  const bundledIdentityPath = path.resolve(
    __dirname,
    '..',
    'bundled',
    'server',
    'app',
    'api',
    'training_card_identity.py',
  );
  const handoffPath = path.resolve(
    __dirname,
    '..',
    '..',
    'server',
    'app',
    'api',
    'routes',
    'training_handoff.py',
  );
  const bundledHandoffPath = path.resolve(
    __dirname,
    '..',
    'bundled',
    'server',
    'app',
    'api',
    'routes',
    'training_handoff.py',
  );
  const identity = fs.readFileSync(identityPath, 'utf8');
  const bundledIdentity = fs.readFileSync(bundledIdentityPath, 'utf8');
  const routers = fs.readFileSync(routersPath, 'utf8');
  const bundledRouters = fs.readFileSync(bundledRoutersPath, 'utf8');
  const handoff = fs.readFileSync(handoffPath, 'utf8');
  const bundledHandoff = fs.readFileSync(bundledHandoffPath, 'utf8');
  const trainingCommands = fs.readFileSync(
    path.resolve(__dirname, '..', 'src', 'commands', 'trainingCommands.ts'),
    'utf8',
  );

  assert.match(identity, /def require_live_selected_card_for_status\(/);
  assert.match(identity, /Recovered training card is leftover-not-live/);
  assert.match(identity, /reflect, return/);
  assert.match(bundledIdentity, /def require_live_selected_card_for_status\(/);
  assert.match(bundledIdentity, /Recovered training card is leftover-not-live/);
  assert.match(routers, /def require_live_selected_card_for_status\(/);
  assert.match(routers, /require_live_selected_card_for_status_impl\(runtime, workspace_id, card_id\)/);
  assert.match(routers, /require_live_selected_card_for_status\(request\.workspace_id, request\.card_id\)/);
  assert.match(handoff, /require_live_selected_card_for_status\(runtime, request\.workspace_id, request\.card_id\)/);
  assert.match(bundledHandoff, /require_live_selected_card_for_status\(runtime, request\.workspace_id, request\.card_id\)/);
  assert.match(bundledRouters, /def require_live_selected_card_for_status\(/);
  assert.match(bundledRouters, /require_live_selected_card_for_status\(request\.workspace_id, request\.card_id\)/);
  assert.match(trainingCommands, /leftover-not-live\|does not match live selected_card_id/);
  assert.match(
    trainingCommands,
    /Recovered training card is leftover-not-live\. Trainer will not skip, grade, reflect, return, or resurrect leftover as live\./,
  );
  const statusStart = trainingCommands.indexOf('export async function trainingCardStatusTransitionCommand(');
  const generateStart = trainingCommands.indexOf('export async function trainingGenerateCardCommand(');
  assert.ok(statusStart >= 0 && generateStart > statusStart);
  const statusBody = trainingCommands.slice(statusStart, generateStart);
  assert.match(statusBody, /leftoverCardStatusHttpFailure\(error\)/);
  assert.match(trainingCommands, /function leftoverCardStatusHttpFailure\(/);
  assert.match(statusBody, /await rehydrateTrainingSummary\(context, status\.port\);\s*await context\.workbench\.syncState\(\);\s*return \{ ok: true \};/);
  assert.doesNotMatch(
    statusBody,
    /await rehydrateTrainingSummary\(context, status\.port\);[\s\S]*leftover-not-live[\s\S]*return \{ ok: true \}/,
  );
  const reflectStart = trainingCommands.indexOf('export async function trainingReflectCommand(');
  const returnStart = trainingCommands.indexOf('export async function trainingReturnCommand(');
  const reliabilityStart = trainingCommands.indexOf('export async function trainingReliabilityControlCommand(');
  assert.ok(reflectStart >= 0 && returnStart > reflectStart && reliabilityStart > returnStart);
  const reflectBody = trainingCommands.slice(reflectStart, returnStart);
  const returnBody = trainingCommands.slice(returnStart, reliabilityStart);
  assert.match(reflectBody, /leftoverCardStatusHttpFailure\(error\)/);
  assert.match(returnBody, /leftoverCardStatusHttpFailure\(error\)/);
  assert.doesNotMatch(
    reflectBody,
    /await rehydrateTrainingSummary\(context, status\.port\);[\s\S]*leftover-not-live[\s\S]*return \{ ok: true \}/,
  );
  assert.doesNotMatch(
    returnBody,
    /await rehydrateTrainingSummary\(context, status\.port\);[\s\S]*leftover-not-live[\s\S]*return \{ ok: true \}/,
  );
});
