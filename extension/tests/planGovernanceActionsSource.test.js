'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const coachPlanPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'plan',
  'CoachPlanView.tsx',
);
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');
const planComposerCopyPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'i18n',
  'planComposerCopy.ts',
);

test('Plan exposes formal evidence actions and an explicit freeze control', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /evidenceQueue=\{liveEvidenceQueue\}/);
  assert.match(source, /commandId: trainerCommands\.evidenceRefreshQueue/);
  assert.match(source, /commandId: trainerCommands\.evidenceAdopt/);
  assert.match(source, /commandId: trainerCommands\.evidenceDefer/);
  assert.match(source, /commandId: trainerCommands\.evidenceReject/);
  assert.match(source, /type: "plan\/freeze"/);
  assert.match(source, /payload: \{ frozen: !livePlanFrozen \}/);
});

test('Plan composer modes are selectable and Plan and Settings keep a single primary surface', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const styles = fs.readFileSync(stylesPath, 'utf8');

  assert.doesNotMatch(source, /showEmbeddedCoachTranscript/);
  assert.match(source, /view-stack--single/);
  assert.match(source, /modeControl=\{/);
  assert.match(source, /!composerUsesTrainingFlow && activeView === "plan"/);
  assert.match(source, /id: "plan-composer-mode",/);
  assert.match(source, /planComposerModes\.map\(\(mode\) =>/);
  assert.match(source, /const nextMode = planComposerModes\.find\(\(mode\) => mode\.id === value\);/);
  assert.match(source, /setPlanComposerMode\(nextMode\.id\)/);
  assert.match(styles, /\.view-stack--single\s*\{[\s\S]*?grid-template-rows:\s*minmax\(0, 1fr\);/);
});

test('Plan composer uses complete eight-language copy for modes, placeholders, and accessibility labels', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const copySource = fs.readFileSync(planComposerCopyPath, 'utf8');
  const start = appSource.indexOf('  const planComposerModes = useMemo');
  const end = appSource.indexOf('  const activePlanComposerMode =', start);

  assert.ok(start >= 0 && end > start, 'expected the Plan composer mode block');
  const modesSource = appSource.slice(start, end);
  assert.match(appSource, /import \{ resolvePlanComposerCopy \} from "\.\.\/lib\/i18n\/planComposerCopy";/);
  assert.match(copySource, /const planComposerCopy: Record<ComposerLanguage, PlanComposerCopy> = \{/);
  assert.match(copySource, /export function resolvePlanComposerCopy\(language: ComposerLanguage\)/);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(copySource, new RegExp(`"${language}": \\{`));
  }
  for (const mode of ['explain', 'generate', 'evidence', 'blocker']) {
    assert.match(copySource, new RegExp(`${mode}: \\{`));
  }

  assert.match(modesSource, /const planComposerText = resolvePlanComposerCopy\(layout\.composerLanguage\);/);
  assert.match(modesSource, /const explainMode = planComposerText\.modes\.explain;/);
  assert.match(modesSource, /const generateMode = planComposerText\.modes\.generate;/);
  assert.match(modesSource, /const evidenceMode = planComposerText\.modes\.evidence;/);
  assert.match(modesSource, /const blockerMode = planComposerText\.modes\.blocker;/);
  assert.match(modesSource, /placeholder: explainMode\.placeholder,/);
  assert.match(modesSource, /placeholder: generateMode\.placeholder,/);
  assert.match(modesSource, /placeholder: evidenceMode\.placeholder,/);
  assert.match(modesSource, /placeholder: blockerMode\.placeholder,/);
  assert.match(modesSource, /accessibilityLabel: explainMode\.accessibilityLabel,/);
  assert.match(modesSource, /accessibilityLabel: generateMode\.accessibilityLabel,/);
  assert.match(modesSource, /accessibilityLabel: evidenceMode\.accessibilityLabel,/);
  assert.match(modesSource, /accessibilityLabel: blockerMode\.accessibilityLabel,/);
  assert.doesNotMatch(modesSource, /"Explain"|"Generate"|"Evidence"|"Blocker"/);
  assert.match(appSource, /activePlanComposerMode\.placeholder/);
  assert.match(appSource, /activePlanComposerMode\.accessibilityLabel/);
});

test('formal plan generation is explicit while Plan discussion stays conversational', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(
    source,
    /id: "refresh-plan",[\s\S]*?onClick: \(\) => handlePlanOrientationAction\("generate_plan"\)/,
  );
  assert.match(source, /if \(action === "generate_plan"\) \{\s*openPlanComposerMode\("generate"\);/);
  assert.match(source, /if \(action === "continue_without_plan"\) \{\s*setActiveView\("coach"\);\s*focusComposerInput\(\);/);
  assert.match(source, /const planComposerSubmission = activeView === "plan";/);
  assert.match(
    source,
    /const formalPlanGeneration =\s*planComposerSubmission && resolvedPlanComposerMode === "generate";/,
  );
  assert.match(source, /function providerHasVerifiedToolsProbe\([\s\S]*?lastTest\.toolsReady === true[\s\S]*?lastTest\.toolProbeStatus === "verified"[\s\S]*?toolsEvidence\?\.state === "verified"[\s\S]*?toolsEvidence\.observed === true/);
  assert.match(source, /const providerSupportsFormalPlanTools = providerHasVerifiedToolsProbe\(\{\s*lastTestResult: scopedProviderLastTest,\s*\}\);/);
  assert.match(source, /const providerCanMutateFormalPlan = capabilityVerdict\.formalPlan;/);
  assert.match(source, /const agentToolsCapabilityMessage = useMemo\(/);
  assert.match(source, /const requiresVerifiedAgentTools = Boolean\(resolvedFormalPlanMutation\);/);
  assert.match(source, /const resolvedFormalPlanMutation = recoveredResume \? false : formalPlanMutation;/);
  assert.doesNotMatch(source, /const requiresVerifiedAgentTools = [^;]*turnActiveView/);
  assert.doesNotMatch(source, /const requiresVerifiedAgentTools = [^;]*activeView/);
  assert.match(
    source,
    /if \(requiresVerifiedAgentTools && !providerSupportsFormalPlanTools\) \{[\s\S]*?message: agentToolsCapabilityMessage,[\s\S]*?return;/,
  );
  assert.doesNotMatch(source, /const providerSupportsFormalPlanTools = data\.providerConfig\.capabilities\.tools === true;/);
  assert.match(
    source,
    /const previewPlanCandidateGeneration =\s*formalPlanGeneration && isBrowserPreview && Boolean\(window\.__TRAINER_BOOTSTRAP__\);/,
  );
  assert.match(
    source,
    /if \(formalPlanGeneration && !previewPlanCandidateGeneration && !providerCanMutateFormalPlan\) \{[\s\S]*?message: formalPlanCapabilityMessage,[\s\S]*?return;/,
  );
  assert.match(
    source,
    /if \(formalPlanGeneration && !previewPlanCandidateGeneration && !capabilityVerdict\.formalPlan\) \{[\s\S]*?message: formalPlanCapabilityMessage,[\s\S]*?return;/,
  );
  assert.match(source, /const formalPlanSkill = submittedSkill\.commandId === trainerCommands\.generatePlan;/);
  assert.match(source, /if \(formalPlanSkill && !providerCanMutateFormalPlan\) \{/);
  assert.match(source, /formalPlanMutation: formalPlanSkill,/);
  assert.match(source, /const intent = formalPlanGeneration \? "plan" : analyzedIntent;/);
  assert.match(source, /formalPlanMutation: formalPlanGeneration && !previewPlanCandidateGeneration,/);
  assert.doesNotMatch(
    source,
    /formalPlanMutation: formalPlanGeneration,\s*planComposerMode:/,
  );
  assert.doesNotMatch(source, /const intent = analyzedIntent === "plan" \? "coach" : analyzedIntent;/);
  const planActionStart = source.indexOf('if (action === "plan")');
  const nextTaskActionStart = source.indexOf('if (action === "next_task")', planActionStart);
  const planAction = source.slice(planActionStart, nextTaskActionStart);
  assert.ok(planActionStart >= 0 && nextTaskActionStart > planActionStart);
  assert.doesNotMatch(planAction, /sendTurn\(/);
});

test('an empty Plan starts in discussion mode and only an explicit action selects generation', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(
    source,
    /const resolvedPlanComposerMode: PlanComposerMode = !planHasFormalThread\s*\?\s*recoveredRuntime && \(planComposerMode === "blocker" \|\| planComposerMode === "evidence"\)\s*\?\s*planComposerMode\s*:\s*"explain"/,
  );
  assert.match(source, /openPlanComposerMode\("generate"\);/);
});

test('recovered runtime makes orientation the primary Plan action and folds generate', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const start = source.indexOf('  const renderPlanView = () => (');
  const end = source.indexOf('  const renderSettingsView = () => (', start);
  assert.ok(start >= 0 && end > start, 'expected the Plan view block');
  const planView = source.slice(start, end);

  assert.match(
    source,
    /const recoveredPlanPrimary =\s*recoveredRuntime &&\s*\(planOrientation\.primaryAction === "clear_blocker" \|\|\s*planOrientation\.primaryAction === "continue_step" \|\|\s*planOrientation\.primaryAction === "adopt_evidence" \|\|\s*planOrientation\.primaryAction === "wait"\)\s*\?\s*planOrientation\.primaryAction\s*:\s*null;/,
  );
  assert.doesNotMatch(planView, /showAction=\{recoveredAdoptPrimary \|\| !recoveredPlanPrimary\}/);
  assert.match(source, /const recoveredAdoptPrimary = recoveredPlanPrimary === "adopt_evidence";/);
  assert.match(planView, /recoveredPlanPrimary && !recoveredAdoptPrimary/);
  assert.match(planView, /!recoveredAdoptPrimary && \(!hasFormalPlan \|\| !livePlanFrozen\)/);
  assert.match(planView, /recoveredAdoptPrimary/);
  assert.match(
    planView,
    /id:\s*recoveredPlanPrimary === "clear_blocker"\s*\?\s*"plan-clear-blocker"\s*:\s*recoveredPlanPrimary === "wait"\s*\?\s*"plan-needs-evidence"\s*:\s*"plan-continue-step"/,
  );
  assert.match(planView, /label: planOrientation\.primaryActionLabel/);
  assert.match(planView, /tone: "accent" as const/);
  assert.match(planView, /onClick: \(\) => handlePlanOrientationAction\(recoveredPlanPrimary\)/);
  assert.match(source, /firstLookRecommendedNext: liveFirstLookSummary\?\.recommendedNextStep/);
  assert.match(source, /firstLookWhy: liveFirstLookSummary\?\.whyThisGuess/);
  assert.match(source, /const firstLookContinuePrimary = planOrientation\.primaryAction === "continue_without_plan"/);
  assert.match(planView, /id: "plan-continue-without-plan"/);
  assert.match(planView, /tone:\s*recoveredPlanPrimary \|\| firstLookContinuePrimary/);
  assert.match(planView, /firstLookContinuePrimary\s*\?\s*planOrientation\.nextStep/);
  const bundledPlanOrientation = fs.readFileSync(
    path.resolve(__dirname, '..', 'bundled', 'server', 'app', 'pedagogy', 'plan_orientation.py'),
    'utf8',
  );
  assert.match(bundledPlanOrientation, /def derive_plan_orientation\(/);
  assert.match(bundledPlanOrientation, /continue_without_plan/);
  assert.match(bundledPlanOrientation, /first_look_recommended_next/);
  assert.match(planView, /plan=\{shouldShowNeutralEmptyState \? null : visibleFormalPlan\}/);
  assert.match(source, /preferRecoveredPlanRuntimeFacts\(/);
  assert.match(source, /lockRecoveredPlanVerifyItems\(/);
  assert.match(source, /scopeEvidenceQueueToRuntimeStep\(/);
  assert.match(source, /liveEvidenceBinding\(/);
  assert.match(source, /pendingEvidenceIds: liveEvidenceQueue\.pending\.map\(\(item\) => item\.id\)/);
  assert.match(source, /pendingEvidenceCount: liveEvidenceQueue\.pending\.length/);
  assert.match(source, /evidenceQueue=\{liveEvidenceQueue\}/);
  assert.match(
    source,
    /liveCoachTurnChrome\.evaluationNextStep \? \(\s*<p>\{liveCoachTurnChrome\.evaluationNextStep\}<\/p>\s*\) : undefined/,
  );
  assert.match(source, /leftoverCoachTurnChromeIsNotLive\(/);
  assert.match(source, /preferRecoveredCoachTurnChrome\(/);
  assert.match(source, /leftoverTrainingFocusChromeIsNotLive\(/);
  assert.match(source, /preferRecoveredTrainingFocusChrome\(/);
  assert.match(source, /leftoverTrainingHandoffChromeIsNotLive\(/);
  assert.match(source, /preferRecoveredTrainingHandoffChrome\(/);
  assert.match(source, /leftoverResourceSelectedDetailIsNotLive\(/);
  assert.match(source, /leftoverResourceSandboxPreviewIsNotLive\(/);
  assert.match(source, /leftoverResourceSandboxStateIsNotLive\(/);
  assert.match(source, /leftoverResourceLibraryListIsNotLive\(/);
  assert.match(source, /leftoverCoachConversationIsNotLive\(/);
  assert.match(source, /leftoverSuggestedActionsIsNotLive\(/);
  assert.match(source, /leftoverMintingSuggestedActionsAreNotLive\(/);
  assert.match(source, /leftoverFirstLookHeadlineIsNotLive\(/);
  assert.match(source, /leftoverEvaluationHeadlineIsNotLive\(/);
  assert.match(source, /leftoverStreamingCheckpointIsNotLive\(/);
  assert.match(source, /leftoverTransferSkillIsNotLive\(/);
  assert.match(source, /preferRecoveredTransferSkill\(/);
  assert.match(source, /leftoverSettingsProfileRhythmIsNotLive\(/);
  assert.match(source, /leftoverSettingsLearnerProjectOnboardingIsNotLive\(/);
  assert.match(source, /resumeThread: data\.coachTurn\?\.resumeThread \?\? data\.coachingState\?\.resumeThread/);
  assert.match(source, /supportStrategy: data\.coachTurn\?\.supportStrategy \?\? data\.coachingState\?\.supportStrategy/);
  assert.match(source, /artifactTeaser: latestCoachArtifact\?\.teaser/);
  assert.match(source, /artifactRationale: latestCoachArtifact\?\.rationale/);
  assert.match(source, /liveCoachTurnChrome\.resumeThread/);
  assert.match(source, /liveCoachTurnChrome\.supportStrategy/);
  assert.match(source, /liveCoachTurnChrome\.reviewQueueSummary/);
  assert.match(source, /liveCoachTurnChrome\.artifactRationale/);
  assert.match(source, /const latestArtifactTeaser = liveCoachTurnChrome\.artifactTeaser/);
  assert.match(source, /leftoverCoachTurnChromeNotLive \? undefined : latestCoachArtifact\?\.title/);
  assert.match(source, /if \(!latestCoachArtifact \|\| leftoverCoachTurnChromeNotLive\)/);
  assert.match(source, /continuitySummary: data\.coachFocus\?\.continuitySummary/);
  assert.match(source, /coachJudgmentSummary: planRuntimeStatus\?\.coachJudgment\?\.summary/);
  assert.match(source, /coachJudgmentTeachingGoal: planRuntimeStatus\?\.coachJudgment\?\.teachingGoal/);
  assert.match(source, /liveCoachTurnChrome\.coachJudgmentSummary/);
  assert.match(source, /liveCoachTurnChrome\.coachJudgmentTeachingGoal/);
  assert.match(source, /const coachContinuitySummary = liveCoachTurnChrome\.continuitySummary/);
  assert.match(source, /resolveLivePlanStageChrome\(/);
  assert.match(source, /liveStageIsCurrent=\{liveStageChrome\.stageIsCurrent\}/);
  assert.match(
    source,
    /currentStageId:\s*formalPlanLive && liveStageChrome\.stageIsCurrent \? data\.plan\.currentStageId : undefined/,
  );
  assert.match(source, /const visibleFormalPlan = useMemo\(\(\) => \{/);
  assert.match(
    source,
    /if \(leftoverPlanNotLive && !recoveredDisplayFacts\.currentStep\) \{\s*return null;/,
  );
  assert.match(source, /if \(!recoveredRuntime\) \{\s*return data\.plan;/);
  assert.match(source, /whyNow: recoveredDisplayFacts\.whyNow \?\? ""/);
  assert.match(source, /liveFormalPlanFrozen\(/);
  assert.match(source, /formalPlanIsLiveRuntimeIdentity\(/);
  assert.match(source, /leftoverTaskGuideFocusIsNotLive\(/);
  assert.match(source, /preferRecoveredCoachTaskChrome\(/);
  assert.match(source, /liveCoachTaskChrome\.currentFocus/);
  assert.match(source, /liveCoachTaskChrome\.activeTask/);
  assert.match(source, /frozen: livePlanFrozen/);
  assert.match(source, /liveFormalPlanTitle\(/);
  assert.match(source, /liveFormalPlanSummary\(/);
  assert.match(source, /liveFormalPlanStages\(/);
  assert.match(source, /liveFormalPlanCadence\(/);
  assert.match(source, /title: livePlanTitle/);
  assert.match(source, /summary: livePlanSummary/);
  assert.match(source, /cadence: livePlanCadence/);
  assert.match(source, /stages: livePlanStages/);
  assert.match(source, /formalPlanLive && !recoveredAdoptPrimary && !shouldShowNeutralEmptyState/);
  assert.match(
    planView,
    /recoveredRuntime \? null : liveCoachTaskChrome\.scopeBoundary/,
  );
  assert.match(
    planView,
    /recoveredDisplayFacts\.currentStep \|\|\s*liveCoachTaskChrome\.currentStep \|\|\s*resolvedCoachNextStep \|\|\s*latestArtifactTeaser/,
  );
  const resumeStart = source.indexOf('sendRecoveredPlanResumeRef.current = (action) => {');
  const resumeEnd = source.indexOf('const sendTrainingFeedback', resumeStart);
  assert.ok(resumeStart >= 0 && resumeEnd > resumeStart, 'expected recovered plan resume send');
  const resumeSend = source.slice(resumeStart, resumeEnd);
  assert.match(
    source,
    /if \(action === "clear_blocker" \|\| action === "continue_step"\) \{\s*sendRecoveredPlanResumeRef\.current\(action\);/,
  );
  assert.match(
    source,
    /if \(action === "adopt_evidence"\) \{\s*const pendingEvidenceId = liveEvidenceQueue\.pending\[0\]\?\.id\?\.trim\(\);/,
  );
  assert.match(source, /commandId: trainerCommands\.evidenceAdopt,/);
  assert.match(source, /payload: \{ evidenceId: pendingEvidenceId \}/);
  assert.match(
    source,
    /if \(action === "adopt_evidence"\) \{\s*const pendingEvidenceId = liveEvidenceQueue\.pending\[0\]\?\.id\?\.trim\(\);\s*if \(pendingEvidenceId\) \{/,
  );
  assert.doesNotMatch(
    source,
    /if \(action === "adopt_evidence"\) \{[\s\S]{0,800}sendTurn\(/,
  );
  assert.match(
    source,
    /\(action: PlanOrientationAction \| string \| null\) => \{\s*if \(!action\) \{\s*return;/,
  );
  assert.match(source, /if \(action === "wait"\) \{\s*openPlanComposerMode\("evidence"\);/);
  assert.match(source, /openPlanComposerMode\("evidence"\);/);
  assert.match(
    source,
    /const waitingComposerEvidence =\s*activeView === "plan" &&\s*resolvedPlanComposerMode === "evidence" &&\s*recoveredRuntime &&\s*planRuntimeStatus\?\.resumeState === "waiting" &&\s*Boolean\(planRuntimeStatus\?\.currentStep\?\.trim\(\)\) &&\s*liveEvidenceQueue\.pending\.length === 0;/,
  );
  assert.match(source, /trainerCommands\.evidenceEnqueue/);
  assert.match(source, /waitingComposer: true,/);
  assert.match(
    source,
    /if \(waitingComposerEvidence\) \{[\s\S]{0,900}requestTrainingPersistence\(trainerCommands\.evidenceEnqueue/,
  );
  assert.match(
    source,
    /if \(waitingComposerEvidence\) \{[\s\S]{0,1200}waitingComposerEnqueueFailureText\(error, layout\.composerLanguage\)/,
  );
  assert.match(
    source,
    /if \(waitingComposerEvidence\) \{[\s\S]{0,1200}setOperationMessage\(\{\s*tone: "error"/,
  );
  assert.doesNotMatch(
    source,
    /if \(waitingComposerEvidence\) \{[\s\S]{0,900}sendTurn\(/,
  );
  assert.doesNotMatch(
    source,
    /if \(waitingComposerEvidence\) \{[\s\S]{0,900}(?:pending\.push|id:\s*[`'"])/,
  );
  assert.doesNotMatch(
    source,
    /if \(action === "adopt_evidence"\) \{[\s\S]{0,800}resumeState:\s*["']in_progress["']/,
  );
  assert.match(
    resumeSend,
    /const resume = buildRecoveredPlanResumeTurn\(action, \{\s*recovered: planRuntimeStatus\?\.recovered === true,/,
  );
  assert.match(resumeSend, /currentStep: planRuntimeStatus\?\.currentStep,/);
  assert.match(resumeSend, /blockedReason: planRuntimeStatus\?\.blockedReason,/);
  assert.match(
    resumeSend,
    /if \(!resume\) \{\s*openPlanComposerMode\(action === "clear_blocker" \? "blocker" : "explain"\);/,
  );
  assert.match(resumeSend, /intent: "plan",/);
  assert.match(resumeSend, /formalPlanMutation: false,/);
  assert.match(resumeSend, /planRuntimeRecovery: resume,/);
  assert.match(resumeSend, /recoveredPlanResumeMessage\(resume, layout\.composerLanguage\)/);
  assert.doesNotMatch(resumeSend, /formalPlanMutation: true/);
  assert.doesNotMatch(resumeSend, /generate_plan|\/plan\/generate|LearningPlan\(/);
  assert.doesNotMatch(planView, /LearningPlan\(/);
  assert.doesNotMatch(
    planView,
    /tone: recoveredPlanPrimary \? \("accent" as const\) : \("ghost" as const\)/,
  );
});

test('a frozen plan does not offer the replacement generation action', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const start = source.indexOf('  const renderPlanView = () => (');
  const end = source.indexOf('  const renderSettingsView = () => (', start);

  assert.ok(start >= 0 && end > start, 'expected the Plan view block');
  const planView = source.slice(start, end);

  assert.match(planView, /!hasFormalPlan \|\| !livePlanFrozen/);
  assert.match(
    planView,
    /!hasFormalPlan \|\| !livePlanFrozen[\s\S]*?id: "refresh-plan",[\s\S]*?handlePlanOrientationAction\("generate_plan"\)/,
  );
  assert.match(source, /const planIsFrozen = hasFormalPlan && livePlanFrozen;/);
  assert.match(source, /planIsFrozen \? modes\.filter\(\(mode\) => mode\.id !== "generate"\) : modes/);
  assert.doesNotMatch(
    planView,
    /hasFormalPlan && formalPlanLive[\s\S]{0,120}id: "refresh-plan"/,
  );
  assert.match(
    planView,
    /!recoveredAdoptPrimary && hasFormalPlan && formalPlanLive[\s\S]*?id: "plan-next-task"/,
  );
  assert.match(
    source,
    /hasFormalPlan && formalPlanLive && !recoveredAdoptPrimary && !shouldShowNeutralEmptyState[\s\S]*?id: livePlanFrozen \? "resume-plan" : "freeze-plan"/,
  );
});

test('waiting live pending keeps adopt primary and exposes reject/defer beside it', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const coachPlanSource = fs.readFileSync(coachPlanPath, 'utf8');
  const compactPrimaryStart = coachPlanSource.indexOf('const compactPrimaryAction = compactPrimary');
  const compactPrimaryEnd = coachPlanSource.indexOf('const compactSecondaryActions', compactPrimaryStart);
  assert.ok(compactPrimaryStart >= 0 && compactPrimaryEnd > compactPrimaryStart);
  const compactPrimary = coachPlanSource.slice(compactPrimaryStart, compactPrimaryEnd);
  assert.match(compactPrimary, /pickPlanPrimaryAction\(actions\)/);
  const pickerStart = coachPlanSource.indexOf('function pickPlanPrimaryAction');
  const pickerEnd = coachPlanSource.indexOf('function LiveEvidenceDecisionRow', pickerStart);
  assert.ok(pickerStart >= 0 && pickerEnd > pickerStart, 'expected pickPlanPrimaryAction');
  const picker = coachPlanSource.slice(pickerStart, pickerEnd);
  assert.match(picker, /RECOVERED_PLAN_ACTION_IDS\.has\(action\.id\)/);
  assert.ok(
    picker.indexOf('RECOVERED_PLAN_ACTION_IDS') < picker.indexOf('plan-next-task'),
    'recovered adopt/continue must beat next-task as the compact primary',
  );
  assert.match(coachPlanSource, /const reviewEvidenceAction = \(actions \?\? \[\]\)\.find\(\(action\) => action\.id === "plan-review-evidence"\)/);
  assert.match(coachPlanSource, /data-plan-evidence-decisions="true"/);
  assert.match(coachPlanSource, /data-plan-evidence-decision="defer"/);
  assert.match(coachPlanSource, /data-plan-evidence-decision="reject"/);
  assert.match(
    coachPlanSource,
    /emptyPrimaryAction\.id === "plan-review-evidence" \? liveEvidenceDecisionRow : null/,
  );
  assert.match(
    coachPlanSource,
    /!\(showLiveEvidenceDecisions && !item\.deferredAt\)/,
  );
  const decisionRowStart = coachPlanSource.indexOf('function LiveEvidenceDecisionRow');
  const decisionRowEnd = coachPlanSource.indexOf('function resolvePlanDecisionStrip', decisionRowStart);
  assert.ok(decisionRowStart >= 0 && decisionRowEnd > decisionRowStart);
  const decisionRow = coachPlanSource.slice(decisionRowStart, decisionRowEnd);
  assert.match(decisionRow, /button--quiet/);
  assert.doesNotMatch(decisionRow, /tone="accent"/);
  assert.doesNotMatch(decisionRow, /ActionButton/);
  const evidenceDetailsStart = coachPlanSource.indexOf(
    '<details className="coach-plan-view__nested-details coach-plan-view__evidence-details">',
  );
  assert.ok(
    coachPlanSource.indexOf('data-plan-evidence-decisions="true"') < evidenceDetailsStart,
    'reject/defer must sit next to adopt, not only inside the buried evidence dump',
  );
  assert.match(
    source,
    /id:\s*recoveredPlanPrimary === "clear_blocker"\s*\?\s*"plan-clear-blocker"\s*:\s*recoveredPlanPrimary === "wait"\s*\?\s*"plan-needs-evidence"/,
  );
  assert.match(source, /commandId: trainerCommands\.evidenceDefer/);
  assert.match(source, /commandId: trainerCommands\.evidenceReject/);
  assert.doesNotMatch(
    source,
    /if \(action === "adopt_evidence"\) \{[\s\S]{0,800}resumeState:\s*["']in_progress["']/,
  );
});

test('Plan moves next-task replies to Coach and protects an unsent composer draft', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const coachPlanSource = fs.readFileSync(coachPlanPath, 'utf8');
  const planStart = appSource.indexOf('  const renderPlanView = () => (');
  const planEnd = appSource.indexOf('  const renderSettingsView = () => (', planStart);
  const planView = appSource.slice(planStart, planEnd);

  assert.ok(planStart >= 0 && planEnd > planStart, 'expected the Plan view block');
  assert.match(
    planView,
    /id: "plan-next-task",[\s\S]*?onClick: \(\) => \{\s*setActiveView\("coach"\);[\s\S]*?activeView: "coach",/,
  );
  assert.match(appSource, /!recoveredAdoptPrimary && hasFormalPlan && formalPlanLive/);
  assert.doesNotMatch(
    planView,
    /!recoveredAdoptPrimary && hasFormalPlan\s*\?\s*\[/,
  );
  assert.match(appSource, /const \[pendingPlanComposerDraftReplacement, setPendingPlanComposerDraftReplacement\] =/);
  assert.match(
    appSource,
    /if \(normalizedDraft\) \{\s*setPendingPlanComposerDraftReplacement\(\{ source, targetTitle: normalizedTargetTitle \}\);/,
  );
  assert.match(appSource, /const confirmPlanComposerDraftReplacement = \(\) => \{/);
  assert.match(appSource, /const cancelPlanComposerDraftReplacement = \(\) => \{/);
  assert.match(coachPlanSource, /export interface PlanComposerDraftReplacementPrompt/);
  assert.match(coachPlanSource, /role="alertdialog"/);
  assert.match(coachPlanSource, /event\.key === "Escape" && composerDraftReplacement/);
  assert.match(coachPlanSource, /renderComposerDraftReplacement\("stage"\)/);
  assert.match(coachPlanSource, /renderComposerDraftReplacement\("project-subplan"\)/);
});

test('Plan first screen keeps one primary action and leftover-not-live honesty', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const coachPlanSource = fs.readFileSync(coachPlanPath, 'utf8');
  const resourcesPath = path.resolve(
    __dirname,
    '..',
    'webview',
    'src',
    'components',
    'resources',
    'ResourcesWorkbenchView.tsx',
  );
  const trainingPath = path.resolve(
    __dirname,
    '..',
    'webview',
    'src',
    'components',
    'training',
    'TrainingWorkbenchView.tsx',
  );
  const resourcesSource = fs.readFileSync(resourcesPath, 'utf8');
  const trainingSource = fs.readFileSync(trainingPath, 'utf8');

  assert.match(coachPlanSource, /function pickPlanPrimaryAction\(/);
  assert.match(coachPlanSource, /enabled\("open-settings"\)/);
  assert.match(coachPlanSource, /enabled\("refresh-plan"\)/);
  assert.match(coachPlanSource, /const emptyPrimaryAction = reviewEvidenceAction \?\? pickPlanPrimaryAction\(emptyPlanActions\)/);
  assert.match(coachPlanSource, /leftoverNote\?: string/);
  assert.match(coachPlanSource, /data-plan-leftover-not-live=/);
  assert.match(coachPlanSource, /data-plan-leftover-note="true"/);
  assert.match(coachPlanSource, /leftoverNote \? \(\s*[\s\S]*?emptyState/);
  assert.match(coachPlanSource, /leftoverNote \? null : \(/);
  assert.match(coachPlanSource, /coach-plan-view__leftover-note/);
  assert.match(
    coachPlanSource,
    /data-plan-leftover-note="true"\s*[\s\S]*?role="status"\s*[\s\S]*?aria-live="polite"/,
  );
  assert.match(coachPlanSource, /leftoverNotLive: "This is stored leftover on this workspace, not the live plan."/);
  assert.match(appSource, /const leftoverPlanNotLive = Boolean\(recoveredRuntime\) && !formalPlanLive/);
  assert.match(appSource, /leftoverNote=\{leftoverPlanNotLive \? t\.leftoverNotLive : undefined\}/);
  assert.match(appSource, /hasFormalPlan: hasFormalPlan && formalPlanLive/);
  assert.match(appSource, /if \(leftoverPlanNotLive && !recoveredDisplayFacts\.currentStep\) \{\s*return null;/);
  assert.match(appSource, /data-coach-leftover-note="true"/);
  assert.match(
    appSource,
    /data-coach-leftover-note="true"\s*[\s\S]*?role="status"\s*[\s\S]*?aria-live="polite"/,
  );
  assert.match(appSource, /aria-label=\{t\.openCoach\}/);
  assert.match(resourcesSource, /leftoverNote\?: string/);
  assert.match(resourcesSource, /data-resources-leftover-not-live=/);
  assert.match(resourcesSource, /data-resources-leftover-note="true"/);
  assert.match(
    resourcesSource,
    /data-resources-leftover-note="true"\s*[\s\S]*?role="status"\s*[\s\S]*?aria-live="polite"/,
  );
  assert.match(resourcesSource, /leftoverStoredNote \? null : \(/);
  assert.match(trainingSource, /leftoverNote\?: string/);
  assert.match(trainingSource, /data-training-leftover-not-live=/);
  assert.match(trainingSource, /data-training-leftover-note="true"/);
  assert.match(
    trainingSource,
    /data-training-leftover-note="true"\s*[\s\S]*?role="status"\s*[\s\S]*?aria-live="polite"/,
  );
  // Leftover first-screen: sentence + Open Coach only — never fall through to card dump.
  assert.match(trainingSource, /\{leftoverStoredNote \? \(/);
  assert.doesNotMatch(trainingSource, /leftoverStoredNote && !hasPrimaryLoop/);
  assert.match(
    trainingSource,
    /leftoverStoredNote \? \([\s\S]*?aria-label=\{t\.openCoach\}/,
  );
  assert.match(resourcesSource, /leftoverStoredNote \? null : \(/);
  assert.match(
    resourcesSource,
    /leftoverStoredNote \? \(\s*<p[\s\S]*?data-resources-leftover-note="true"/,
  );
  assert.match(appSource, /primaryAction: "open_coach"/);
  assert.match(appSource, /primaryActionLabel: t\.openCoach/);
  assert.match(appSource, /leftoverNote=\{leftoverResourceLibraryListNotLive \? t\.leftoverNotLive : undefined\}/);
  assert.match(appSource, /leftoverNote=\{leftoverTrainingHandoffChromeNotLive \? t\.leftoverNotLive : undefined\}/);
  assert.match(
    appSource,
    /leftoverTrainingHandoffChromeNotLive \? \(\s*<button[\s\S]*?aria-label=\{t\.openCoach\}/,
  );
  assert.match(appSource, /if \(leftoverPlanNotLive && !recoveredDisplayFacts\.currentStep\) \{\s*return null;/);
  assert.match(appSource, /runtimePlanId: data\.memory\.workspace\?\.latestPlanRuntime\?\.planId,/);
  assert.doesNotMatch(
    appSource,
    /runtimePlanId: data\.memory\.workspace\?\.latestPlanRuntime\?\.planId \?\? planRuntimeStatus\?\.planId/,
  );
  assert.match(appSource, /leftoverTrainingHandoffChromeNotLive\s*\?\s*false/);
  assert.match(appSource, /leftoverChromeIdentity/);
  assert.match(appSource, /leftoverResourceLibraryListIsNotLive\([\s\S]*?\) \|\| leftoverTrainingHandoffChromeNotLive/);
});

test('Plan first screen prefers verifyPlanAdvance what/why/next after snake→camel adapter', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const workbenchDataPath = path.resolve(__dirname, '..', 'src', 'core', 'workbenchData.ts');
  const typesPath = path.resolve(__dirname, '..', 'src', 'core', 'types.ts');
  const workbenchData = fs.readFileSync(workbenchDataPath, 'utf8');
  const types = fs.readFileSync(typesPath, 'utf8');

  assert.match(types, /verifyPlanAdvance\?:/);
  assert.match(workbenchData, /verifyPlanAdvance:\s*mapVerifyPlanAdvance/);
  assert.match(workbenchData, /record\.verify_plan_advance\s*\?\?\s*record\.verifyPlanAdvance/);
  assert.match(source, /planRuntimeStatus\?\.verifyPlanAdvance/);
  assert.match(source, /verifyAdvance\?\.what,\s*verifyAdvance\?\.why/);
  assert.match(source, /verifyPlanAdvanceNext/);
  assert.match(source, /\{verifyPlanAdvanceNext\s*\|\|/);
});
