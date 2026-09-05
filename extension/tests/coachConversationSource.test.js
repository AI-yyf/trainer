'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');
const agentActivityPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'AgentActivityStripSmart.tsx',
);
const coachMessageBubblePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'CoachMessageBubble.tsx',
);
const coachMessagePartsPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'CoachMessageParts.tsx',
);
const messageRichContentPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'MessageRichContent.tsx',
);
const coachArtifactBlockPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'CoachArtifactBlock.tsx',
);
const composerPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'composer',
  'CoachComposer.tsx',
);

test('coach streaming lane exposes trainer agent activity', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const renderStart = source.indexOf('<CoachConversationView');
  assert.ok(renderStart > -1, 'expected CoachConversationView render');
  const renderEnd = source.indexOf('onArtifactOpen', renderStart);
  assert.ok(renderEnd > renderStart, 'expected CoachConversationView props before artifact handler');
  const props = source.slice(renderStart, renderEnd);

  assert.match(props, /streamingMessage=\{/);
  assert.match(props, /agentActivity=\{streaming\.agentActivity\}/);
  assert.match(props, /agentStep=\{streaming\.agentStep\}/);
});

test('coach summary stays a compact horizontal context rail', () => {
  const styles = fs.readFileSync(stylesPath, 'utf8');
  const summaryStrip = styles.match(/\.coach-conversation-view__summary-strip\s*\{[\s\S]*?\n\}/);
  const summaryPill = styles.match(/\.coach-conversation-view__summary-pill\s*\{[\s\S]*?\n\}/);

  assert.ok(summaryStrip, 'expected summary strip styles');
  assert.ok(summaryPill, 'expected summary pill styles');
  assert.match(summaryStrip[0], /display:\s*flex/);
  assert.match(summaryStrip[0], /flex-wrap:\s*wrap/);
  assert.match(summaryStrip[0], /overflow:\s*visible/);
  assert.doesNotMatch(summaryStrip[0], /display:\s*grid/);
  assert.match(summaryPill[0], /display:\s*inline-flex/);
  assert.match(summaryPill[0], /background:\s*transparent/);
  assert.match(summaryPill[0], /border:\s*0/);
});

test('coach summary rail surfaces blocker guidance alongside the live thread', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /runtimeBlockedReason/);
  assert.match(source, /Current blocker/);
  assert.match(source, /How the next turn will resume/);
});

test('coach keeps the normal message thread free of a summary rail until a real transition, blocker, or stream exists', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const summaryStart = source.indexOf('const coachConversationSummaryBar');
  const summaryEnd = source.indexOf('const trainingState =', summaryStart);

  assert.ok(summaryStart >= 0, 'expected the coach summary rail derivation');
  assert.ok(summaryEnd > summaryStart, 'expected the coach summary rail derivation to end');
  const summary = source.slice(summaryStart, summaryEnd);
  assert.match(summary, /const coachConversationSummaryBar = undefined;/);
  assert.doesNotMatch(summary, /resolvedCoachSummary/);
  assert.doesNotMatch(summary, /resolvedCoachNextStep/);
});

test('coach composer keeps the resources button label short', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const blockStart = source.indexOf('icon: <ResourcesIcon size={16} />');
  assert.ok(blockStart > -1, 'expected composer resources action');
  const block = source.slice(blockStart - 80, blockStart + 140);

  assert.match(block, /label: t\.resourcesMenu/);
  assert.doesNotMatch(block, /label: t\.resourcesSummary/);
});

test('coach sidebar tabs keep the resources label short', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const tabsStart = source.indexOf('const sidebarViewTabs');
  const tabsEnd = source.indexOf('const handleBrowserUploads', tabsStart);
  assert.ok(tabsStart > -1, 'expected sidebarViewTabs definition');
  assert.ok(tabsEnd > tabsStart, 'expected sidebarViewTabs block before uploads');
  const tabsBlock = source.slice(tabsStart, tabsEnd);

  assert.match(tabsBlock, /const label = resourcesViewLabel\(layout\.composerLanguage\);/);
  assert.match(tabsBlock, /compactLabel:\s*compactSidebarViewLabel\(view, layout\.composerLanguage, label\)/);
  assert.doesNotMatch(tabsBlock, /label: t\.resourcesSummary/);
});

test('coach next-step artifact exposes finalize metadata without becoming a visible status part', () => {
  const source = fs.readFileSync(coachArtifactBlockPath, 'utf8');

  assert.match(source, /artifactMetadataRecord/);
  assert.match(source, /artifactMetadataText/);
  assert.match(source, /artifactMetadataList/);
  assert.match(source, /artifactMetaLabel\("decision"/);
  assert.match(source, /artifactMetaLabel\("blocker"/);
  assert.match(source, /artifactMetaLabel\("resumeThread"/);
  assert.match(source, /artifactMetadataText\(metadata, \["resumeThread", "resume_thread"\]\)/);
  assert.match(source, /artifactMetaLabel\("teachingNote"/);
  assert.match(source, /artifactMetaLabel\("confidence"/);
  assert.match(source, /artifact\.metadata/);
});

test('coach agent activity renders as a normalized lightweight progress rail', () => {
  const source = fs.readFileSync(agentActivityPath, 'utf8');
  const styles = fs.readFileSync(stylesPath, 'utf8');
  const activityStrip = styles.match(/(?:^|\n)\.agent-activity-strip\s*\{[\s\S]*?\n\}/);
  assert.ok(activityStrip, 'expected main agent activity strip style block');
  const activityMeta = styles.match(/\.agent-activity-strip__meta\s*\{[\s\S]*?\n\}/);
  const activityWorking = styles.match(/\.agent-activity-strip__working\s*\{[\s\S]*?\n\}/);

  assert.match(source, /const displayStep/);
  assert.match(source, /step >= activities\.length \? step : step \+ 1/);
  assert.match(source, /`Step \$\{displayStep\}`/);
  assert.doesNotMatch(source, /`Step \$\{step \+ 1\}`/);
  assert.match(activityStrip[0], /border-left/);
  assert.doesNotMatch(activityStrip[0], /border:\s*1px/);
  assert.ok(activityMeta, 'expected meta styles');
  assert.match(activityMeta[0], /display:\s*none/);
  assert.ok(activityWorking, 'expected working styles');
  assert.match(activityWorking[0], /display:\s*none/);
});

test('coach activity details collapse completed tool work while keeping live work open', () => {
  const source = fs.readFileSync(agentActivityPath, 'utf8');
  const conversation = fs.readFileSync(
    path.resolve(__dirname, '..', 'webview', 'src', 'components', 'coach', 'CoachConversationView.tsx'),
    'utf8',
  );

  assert.match(source, /collapsible\?: boolean/);
  assert.match(source, /<CollapsibleBlock/);
  assert.match(source, /defaultOpen=\{hasRunningItems\}/);
  assert.match(source, /运行详情/);
  assert.match(conversation, /collapsible[\s\S]*?step=\{agentStep\}/);
});

test('coach context status does not become a second transcript message', () => {
  const source = fs.readFileSync(
    path.resolve(__dirname, '..', 'webview', 'src', 'components', 'coach', 'CoachConversationView.tsx'),
    'utf8',
  );
  const appSource = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /latestAssistantHasStatus/);
  assert.match(source, /showSummaryBar/);
  assert.match(source, /coach-conversation-view__summary--context/);
  assert.doesNotMatch(source, /\{summaryBar \? <div className="coach-conversation-view__summary">/);
  assert.match(source, /latestAssistantHasStatus/);
  assert.match(source, /Boolean\(summaryBar\) && \(Boolean\(streamingMessage\) \|\| !latestAssistantHasStatus\)/);
});

test('coach visible status renders an explicit recovery resume line', () => {
  const source = fs.readFileSync(coachMessagePartsPath, 'utf8');

  assert.match(source, /part\.resumeThread/);
  assert.doesNotMatch(source, /part\.status !== "done"/);
  assert.match(source, /part\.decision/);
  assert.match(source, /part\.blocker/);
  assert.match(source, /part\.teachingNote/);
  assert.match(source, /part\.confidence/);
  assert.match(source, /part\.evidence/);
});

test('coach rich content keeps markdown code blocks on the highlighted renderer path', () => {
  const source = fs.readFileSync(messageRichContentPath, 'utf8');
  const styles = fs.readFileSync(stylesPath, 'utf8');

  assert.match(source, /import \{ RichCodeBlock \} from "\.\/RichCodeBlock"/);
  assert.match(source, /languageId === "mermaid"/);
  assert.match(source, /<RichCodeBlock/);
  assert.match(source, /remarkPlugins=\{\[plugins\.remarkGfm, plugins\.remarkMath\]\}/);
  assert.match(source, /rehypePlugins=\{\[plugins\.rehypeKatex\]\}/);
  assert.match(styles, /\.message-markdown__code-block--shiki/);
  assert.match(styles, /\.message-markdown \.katex-display/);
});

test('coach rich tables expose header associations and responsive column hooks', () => {
  const source = fs.readFileSync(messageRichContentPath, 'utf8');

  assert.match(source, /const RichTableContext = createContext/);
  assert.match(source, /<caption className="sr-only">\{copy\.table\}<\/caption>/);
  assert.match(source, /scope="col"/);
  assert.match(source, /headers=\{column\?\.id\}/);
  assert.match(source, /data-column-label=\{column\?\.label\}/);
  assert.match(source, /data-column-index=\{column \? column\.index \+ 1 : undefined\}/);
});

test('coach typed parts reuse rich renderers for code math and tables', () => {
  const source = fs.readFileSync(coachMessagePartsPath, 'utf8');

  assert.match(source, /import \{ StructuredTable \} from "\.\/parts\/StructuredTable"/);
  assert.match(source, /inferCodeLanguage/);
  assert.match(source, /mathMarkdown/);
  assert.match(source, /<RichCodeBlock/);
  assert.match(source, /<StructuredTable/);
  assert.match(source, /body=\{mathMarkdown\(part\.tex, Boolean\(part\.display\)\)\}/);
});

test('coach message bubble keeps recovery resume guidance visible inline', () => {
  const source = fs.readFileSync(coachMessageBubblePath, 'utf8');

  assert.match(source, /statusResumeThread/);
  assert.match(source, /normalizeStatusComparisonText/);
  assert.match(source, /isStatusResumeThreadRedundant/);
  assert.match(source, /message-bubble__agent-status-resume/);
  assert.match(source, /statusToneLabel/);
  assert.match(source, /statusSourceLabel/);
  assert.match(source, /statusCounters/);
  assert.match(source, /statusDetailsPreview/);
  assert.match(source, /hasStatusDetails/);
  assert.match(source, /message-bubble__agent-status-disclosure/);
  assert.match(source, /coachVisibleStatusDetailsTitle/);
  assert.doesNotMatch(source, /coachVisibleStatus\?\.status !== "done"/);
  assert.match(source, /statusDecision/);
  assert.match(source, /statusBlocker/);
  assert.match(source, /statusTeachingNote/);
  assert.match(source, /statusConfidence/);
  assert.match(source, /hasEvidenceFacts/);
  assert.match(source, /statusTone/);
  assert.match(source, /statusInlineSummary/);
  assert.match(source, /statusInlineResume/);
  assert.match(source, /key: "decision"/);
  assert.match(source, /preferCollapse=\{!hasAgentStatus && statusTone !== "working"\}/);
  assert.match(source, /summaryOverride=\{undefined\}/);
  assert.match(source, /message-bubble__agent-status-facts/);
  assert.match(source, /message-bubble__agent-status-fact--evidence/);
  assert.match(source, /part\.type === "coach_visible_status"/);
  assert.match(source, /part\.type === "tool_call" \|\| part\.type === "tool_result"/);
  assert.match(source, /statusDetailCandidate/);
  assert.match(source, /statusResumeThreadCandidate/);
});

test('coach message bubble collapses repeated status prose before rendering the answer body', () => {
  const source = fs.readFileSync(coachMessageBubblePath, 'utf8');

  assert.match(source, /function compactAssistantBody\(/);
  assert.match(source, /normalizedBlock === previousBlock/);
  assert.match(source, /excludedStatusLines\.has\(normalizedBlock\)/);
  assert.match(source, /const visibleBody =/);
  assert.match(source, /body=\{visibleBody\}/);
});

test('coach user timestamps stay attached to the identity rail instead of a detached right edge', () => {
  const source = fs.readFileSync(coachMessageBubblePath, 'utf8');

  assert.doesNotMatch(source, /message-bubble__meta-main/);
  assert.match(source, /<div className="message-bubble__identity">[\s\S]*showTimestampInline \? <span className="message-bubble__timestamp">/);
});

test('docked views retain a compact Coach context rail without docking the full transcript', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const railStart = source.indexOf('const renderContextualResultRail');
  const railEnd = source.indexOf('const renderDockedView');
  const railSource = source.slice(railStart, railEnd);

  assert.doesNotMatch(source, /showEmbeddedCoachTranscript/);
  assert.match(source, /const renderContextualResultRail = \(view: "plan" \| "resources" \| "training" \| "settings"\) =>/);
  assert.match(source, /data-view-context-rail=\{view\}/);
  assert.match(source, /data-view-context-rail-open-coach/);
  assert.match(source, /renderContextualResultRail\("plan"\)/);
  assert.match(source, /renderContextualResultRail\("resources"\)/);
  assert.match(source, /const \[lastTurnView, setLastTurnView\] = useState<ActiveWorkbenchView>\(\);/);
  assert.match(source, /setLastTurnView\(turnActiveView\);/);
  assert.match(
    source,
    /const isResourcesContextWorthSurfacing =\s*!isResources \|\| streaming\.isStreaming \|\| lastTurnView === "resources";/,
  );
  assert.match(source, /renderContextualResultRail\("training"\)/);
  assert.match(source, /renderContextualResultRail\("settings"\)/);
  assert.match(source, /view-stack--single/);
  assert.match(
    railSource,
    /if \([\s\S]*?!isResourcesContextWorthSurfacing[\s\S]*?!isSettingsContextWorthSurfacing[\s\S]*?\) \{\s*return null;\s*\}/,
  );
  assert.doesNotMatch(railSource, /id: "current"/);
  assert.doesNotMatch(railSource, /id: "next"/);
  assert.match(railSource, /latestLearningPartialProgress/);
  assert.match(railSource, /const activitySource = liveValue \?\? blockerValue \?\? resultValue;/);
  assert.match(
    railSource,
    /isTraining && !liveValue\s*\? activitySource\?\.trim\(\)\s*:\s*truncateInlineText\(activitySource, textLimit\)/,
  );
  assert.match(
    fs.readFileSync(stylesPath, 'utf8'),
    /@media \(max-width: 420px\) \{[\s\S]*?\.view-context-rail__fact > strong \{[\s\S]*?white-space: normal;[\s\S]*?overflow-wrap: anywhere;/,
  );
});

test('formal Plan generation requires a current verified tools probe, not declared capability flags', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const helperStart = source.indexOf('function providerHasVerifiedToolsProbe(');
  const helperEnd = source.indexOf('\ntype ProviderSettingsLocale', helperStart);
  const gateStart = source.indexOf('const providerSupportsFormalPlanTools =');
  const gateEnd = source.indexOf('const formalPlanCapabilityMessage', gateStart);

  assert.ok(helperStart >= 0 && helperEnd > helperStart, 'expected tools probe helper');
  assert.ok(gateStart >= 0 && gateEnd > gateStart, 'expected formal Plan capability gate');

  const helper = source.slice(helperStart, helperEnd);
  const gate = source.slice(gateStart, gateEnd);
  assert.match(helper, /lastTest\?\.ok === true/);
  assert.match(helper, /lastTest\.toolsReady === true/);
  assert.match(helper, /lastTest\.toolProbeStatus === "verified"/);
  assert.match(helper, /toolsEvidence\?\.state === "verified"/);
  assert.match(helper, /toolsEvidence\.observed === true/);
  assert.match(gate, /providerHasVerifiedToolsProbe\(\{\s*lastTestResult: scopedProviderLastTest,/);
  assert.doesNotMatch(gate, /capabilities\.tools/);
  assert.match(source, /const providerCanMutateFormalPlan = capabilityVerdict\.formalPlan;/);
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
    /if \(formalPlanGeneration && !previewPlanCandidateGeneration && !providerCanMutateFormalPlan\) \{[\s\S]*?message: formalPlanCapabilityMessage,[\s\S]*?return;/,
  );
  assert.match(source, /const formalPlanSkill = submittedSkill\.commandId === trainerCommands\.generatePlan;/);
  assert.match(
    source,
    /if \(formalPlanSkill && !providerCanMutateFormalPlan\) \{[\s\S]*?message: formalPlanCapabilityMessage,[\s\S]*?return;/,
  );
  assert.match(source, /formalPlanMutation: formalPlanSkill,/);
  assert.match(source, /formalPlanMutation: formalPlanGeneration && !previewPlanCandidateGeneration,/);
  assert.match(source, /const intent = formalPlanGeneration \? "plan" : analyzedIntent;/);
});

test('coach composer exposes a recovery path when streaming has not been verified', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  assert.match(
    source,
    /function providerHasVerifiedStreamingProbe\([\s\S]*?lastTest\.streamingReady === true[\s\S]*?lastTest\.streamProbeStatus === "verified"[\s\S]*?streamingEvidence\?\.state === "verified"[\s\S]*?streamingEvidence\.observed === true/,
  );
  assert.match(source, /function streamingCapabilityBlockReason\(language: ComposerLanguage\)/);
  assert.match(
    source,
    /provider\.configured && provider\.apiKeyConfigured && !providerHasVerifiedStreamingProbe\(provider\)/,
  );
});

test('Coach interrupted recovery exposes checkpoint resume and replay without resending the draft', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  assert.match(source, /function isCoachCheckpointRecoveryState\(/);
  assert.match(source, /streaming\.streamError/);
  assert.match(source, /completionStopReason/);
  assert.match(source, /trainerCommands\.resumeLatestCoachCheckpoint/);
  assert.match(source, /trainerCommands\.replayLatestCoachCheckpoint/);
  assert.match(source, /恢复最近进度/);
  assert.match(source, /查看本轮记录/);
  assert.match(source, /不会重新发送当前草稿/);
  assert.match(source, /does not resend your draft/);
  assert.match(source, /action === "resume"/);
  assert.doesNotMatch(
    source.slice(source.indexOf('const coachCheckpointRecoveryActions'), source.indexOf('const renderCoachConversationPane')),
    /sendStreamMessage|handleSubmit|composerDraft/,
  );
});

test('Plan next-step copy prefers the live current step before stale artifact teasers', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const nextStepStart = source.indexOf('nextStep={');
  const nextStepEnd = source.indexOf('whyNow={', nextStepStart);

  assert.ok(nextStepStart > -1 && nextStepEnd > nextStepStart, 'expected Plan next-step block');
  const nextStepBlock = source.slice(nextStepStart, nextStepEnd);

  assert.match(
    nextStepBlock,
    /recoveredDisplayFacts\.currentStep \|\|\s*liveCoachTaskChrome\.currentStep \|\|\s*resolvedCoachNextStep \|\|\s*latestArtifactTeaser/,
  );
  assert.doesNotMatch(
    nextStepBlock,
    /implementationGuide\?\.currentStep \|\| resolvedCoachNextStep/,
  );
});

test('Coach first-run state does not render recommendation buttons', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.doesNotMatch(source, /coach-empty-state__starters/);
  assert.doesNotMatch(source, /onboardingStarterPrompts/);
  assert.doesNotMatch(source, /onboardingStarters/);
});

test('Coach first-run state starts from the learner goal before optional code context', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /const coachFirstComposerPlaceholder: Record<ComposerLanguage, string>/);
  assert.match(source, /\? coachFirstComposerPlaceholder\[layout\.composerLanguage\]/);
  assert.doesNotMatch(source, /Give me the current slice first/);
  assert.doesNotMatch(source, /先给我当前这一小段/);
});

test('Training keeps card submission default while allowing a contextual Coach route', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /type TrainingComposerRoute = "card" \| "coach"/);
  assert.match(source, /useState<TrainingComposerRoute>\("card"\)/);
  assert.match(source, /trainingComposerTalkMode = trainingComposerEnabled && trainingComposerRoute === "coach"/);
  assert.match(source, /composerUsesTrainingFlow = trainingComposerEnabled && !trainingComposerTalkMode/);
  assert.doesNotMatch(source, /id: "training-composer-route"/);
  assert.match(source, /type TrainingComposerRoute = "card" \| "coach"/);
  assert.match(source, /if \(composerUsesTrainingFlow\)/);
});

test('Training review entry uses shared localized copy and hides mismatched review prose', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /const primaryDueReviewTitle = primaryDueReview/);
  assert.match(source, /pickLanguageAlignedTrainingText\(layout\.composerLanguage, primaryDueReview\.concept\) \?\?\s*t\.reviewQueue/);
  assert.match(source, /pickLanguageAlignedTrainingText\(layout\.composerLanguage, primaryDueReview\.concept\) \?\?\s*t\.reviewQueue/);
  assert.match(source, /const primaryDueReviewTitle = primaryDueReview/);
  assert.doesNotMatch(source, /layout\.composerLanguage === "zh-CN" \? "待回顾" : "Due review"/);
});

test('Composer keeps slash and skill discovery on demand, not as persistent controls', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const composerSource = fs.readFileSync(composerPath, 'utf8');

  assert.match(appSource, /normalizedDraft\.startsWith\("\/"\)/);
  assert.match(appSource, /normalizedDraft\.startsWith\("\$"\)/);
  assert.match(appSource, /renderCommandDeck\(\)/);
  assert.match(appSource, /renderSkillDeck\(\)/);
  assert.doesNotMatch(composerSource, /composer__entry-tools/);
  assert.doesNotMatch(composerSource, /composer__entry-trigger/);
  assert.doesNotMatch(composerSource, /startStructuredEntry/);
});

test('Composer candidate decks keep Codex-style draft ownership and keyboard dismissal', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const styles = fs.readFileSync(stylesPath, 'utf8');
  const commandDeck = source.slice(source.indexOf('const renderCommandDeck'), source.indexOf('const renderSkillDeck'));
  const skillDeck = source.slice(source.indexOf('const renderSkillDeck'), source.indexOf('const renderSuggestedActions'));
  const keydown = source.slice(source.indexOf('onKeyDown={(event) =>'), source.indexOf('leadingActions={['));

  assert.match(source, /const \[dismissedComposerDeck, setDismissedComposerDeck\] = useState<ComposerDeckKind>/);
  assert.match(source, /const composerDeckRef = useRef<HTMLDivElement \| null>\(null\);/);
  assert.match(source, /scrollIntoView\(\{ block: "nearest" \}\)/);
  assert.match(commandDeck, /dismissedComposerDeck === "command"/);
  assert.match(skillDeck, /dismissedComposerDeck === "skill"/);
  assert.match(
    styles,
    /\.composer__accessory :is\(\.command-deck__header, \.skill-deck__header, \.skill-deck__empty\)\s*\{[\s\S]*?display:\s*none/,
  );
  assert.match(source, /const selectSkillSuggestion = \(skill: LocalSkillSuggestion\) => \{[\s\S]*?setComposerDraft\(`\$\{skill\.trigger\} `\)/);
  assert.doesNotMatch(source, /skill\.run\(\)/);
  assert.match(source, /trainerSkillCatalog\.find\(\(skill\) =>/);
  assert.match(source, /if \(submittedSkill\) \{/);
  assert.match(source, /submittedSkill\.commandId === trainerCommands\.sendStreamMessage/);
  const submittedSkillDispatch = source.slice(
    source.indexOf("const submittedSkillTrigger"),
    source.indexOf("if (composerUsesTrainingFlow)"),
  );
  assert.match(
    submittedSkillDispatch,
    /resolveTrainerSkillText\(submittedSkill\.prompt, layout\.composerLanguage\)/,
  );
  assert.match(
    submittedSkillDispatch,
    /const skillMessageText = \[skillPrompt, followupText\]\.filter\(Boolean\)\.join\("\\n\\n"\);/,
  );
  assert.match(
    submittedSkillDispatch,
    /sendTurn\(\{[\s\S]*?text: skillMessageText,[\s\S]*?stream: true/,
  );
  assert.doesNotMatch(submittedSkillDispatch, /!hasImageAttachments && submittedSkillTrigger\.startsWith/);
  assert.match(submittedSkillDispatch, /attachments: composerAttachments/);
  assert.match(
    submittedSkillDispatch,
    /else if \(followupText \|\| hasImageAttachments\) \{[\s\S]*?const skillMessageText = \[skillPrompt, followupText\]\.filter\(Boolean\)\.join\("\\n\\n"\);[\s\S]*?sendTurn\(\{[\s\S]*?text: skillMessageText,[\s\S]*?stream: true/,
  );
  assert.match(
    submittedSkillDispatch,
    /submittedSkill\.commandId === trainerCommands\.evaluateCurrentFile[\s\S]*?\? "review"/,
  );
  assert.match(
    submittedSkillDispatch,
    /else \{[\s\S]*?postMessage\(\{[\s\S]*?type: "command\/execute",[\s\S]*?commandId: submittedSkill\.commandId,[\s\S]*?payload: submittedSkill\.payload/,
  );
  assert.match(keydown, /event\.key === "Escape" && \(hasCommandDeck \|\| hasSkillDeck\)/);
  assert.doesNotMatch(keydown, /event\.key === "Escape"[\s\S]*?setComposerDraft\(""\)/);
  assert.doesNotMatch(keydown, /insertDraftAtCursor/);
  assert.doesNotMatch(source, /const insertDraftAtCursor/);
  assert.match(keydown, /event\.key === "Enter" && !event\.shiftKey[\s\S]*?handleSubmit\(\)/);
  const shortcutHint = source.slice(source.indexOf("function composerShortcutHint"), source.indexOf("function focusComposerInput"));
  assert.match(shortcutHint, /return "";/);
  assert.doesNotMatch(shortcutHint, /\/ commands|\/ 指令/);
});

test('Composer expansion lists stay anchored, bounded, scrollable, and keyboard-visible', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const styles = fs.readFileSync(stylesPath, 'utf8');

  const accessory = styles.match(/\.composer__accessory\s*\{[\s\S]*?\n\}/);
  const panels = styles.match(
    /\.composer__accessory > :is\(\.composer-menu-panel, \.command-deck, \.skill-deck\)\s*\{[\s\S]*?\n\}/,
  );
  assert.ok(accessory, 'expected a composer-anchored accessory layer');
  assert.ok(panels, 'expected bounded expansion panel styles');
  assert.match(accessory[0], /position:\s*absolute/);
  assert.match(accessory[0], /bottom:\s*calc\(100% \+ 6px\)/);
  assert.match(panels[0], /inline-size:\s*min\(calc\(100% - 12px\), 320px\)/);
  assert.match(panels[0], /max-inline-size:\s*calc\(100% - 12px\)/);
  assert.match(panels[0], /max-block-size:\s*min\(36vh, 220px\)/);
  assert.match(panels[0], /overflow:\s*auto/);
  assert.match(panels[0], /overflow-x:\s*hidden/);
  assert.match(panels[0], /overscroll-behavior:\s*contain/);
  assert.match(styles, /\.composer__accessory :is\(\.command-deck__item, \.skill-deck__item\):focus-visible/);
  assert.match(styles, /@media \(max-width: 360px\)[\s\S]*?\.composer__accessory > :is\(\.composer-menu-panel, \.command-deck, \.skill-deck\)/);
  assert.match(source, /title=\{\[command\.command, command\.title, command\.description\]/);
  assert.match(source, /title=\{\[\s*skill\.trigger,/);
});

test('Composer expansion decks keep idle rows flat while preserving explicit interaction states', () => {
  const styles = fs.readFileSync(stylesPath, 'utf8');
  const commandItem = styles.match(/\.command-deck__item\s*\{[\s\S]*?\n\}/);
  const skillItem = [...styles.matchAll(/\.skill-deck__item\s*\{[\s\S]*?\n\}/g)].find((match) =>
    match[0].includes('display: grid'),
  );
  const commandTrigger = styles.match(/\.command-deck__command\s*\{[\s\S]*?\n\}/);
  const skillTrigger = styles.match(/\.skill-deck__trigger\s*\{[\s\S]*?\n\}/);

  assert.ok(commandItem, 'expected command deck item styles');
  assert.ok(skillItem, 'expected skill deck item styles');
  assert.ok(commandTrigger, 'expected command trigger styles');
  assert.ok(skillTrigger, 'expected skill trigger styles');
  assert.match(commandItem[0], /border:\s*1px solid transparent/);
  assert.match(commandItem[0], /background:\s*transparent/);
  assert.match(skillItem[0], /border:\s*1px solid transparent/);
  assert.match(skillItem[0], /background:\s*transparent/);
  assert.match(commandTrigger[0], /border:\s*0/);
  assert.match(skillTrigger[0], /border:\s*0/);
  assert.match(styles, /\.command-deck__item:hover,[\s\S]*?background:/);
  assert.match(styles, /\.skill-deck__item\.is-active\s*\{[\s\S]*?background:/);
  assert.match(styles, /\.composer__accessory :is\(\.command-deck__item, \.skill-deck__item\):focus-visible/);
});

test('Unavailable image capability stays accessible and only surfaces inline after a paste or drop attempt', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const composerSource = fs.readFileSync(composerPath, 'utf8');
  const styles = fs.readFileSync(stylesPath, 'utf8');

  assert.match(
    composerSource,
    /const \[showAttachmentCapabilityNote, setShowAttachmentCapabilityNote\] = useState\(false\);/,
  );
  assert.match(composerSource, /showAttachmentCapabilityNote && attachmentCapabilityText/);
  assert.match(composerSource, /setShowAttachmentCapabilityNote\(true\)/);
  assert.match(composerSource, /const handlePaste[\s\S]*?revealAttachmentCapabilityNote\(\);[\s\S]*?return;/);
  assert.match(composerSource, /const handleDrop[\s\S]*?revealAttachmentCapabilityNote\(\);[\s\S]*?return;/);
  assert.match(composerSource, /composer__drop-prompt/);
  assert.doesNotMatch(composerSource, /fileInputRef/);
  assert.doesNotMatch(composerSource, /composer__attach-btn/);
  assert.doesNotMatch(composerSource, /aria-disabled=/);
  assert.doesNotMatch(composerSource, /onUnavailableAttachmentAttempt/);
  assert.doesNotMatch(appSource, /onUnavailableAttachmentAttempt=/);
  assert.match(styles, /\.composer__capability-note\s*\{[\s\S]*?display:\s*flex[\s\S]*?overflow-wrap:\s*anywhere/);
  assert.match(styles, /\.composer__drop-prompt\s*\{[\s\S]*?animation:/);
  assert.match(styles, /@keyframes composer-drop-pulse/);
  assert.match(appSource, /"当前连接还不能验证图片。"/);
  assert.doesNotMatch(appSource, /褰撳墠杩炴帴/);
});

test('hint suggested action fills the composer and does not mint a task turn', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const start = source.indexOf('const handleSuggestedAction');
  const end = source.indexOf('const handleSubmit', start);
  assert.ok(start > -1 && end > start, 'expected handleSuggestedAction before handleSubmit');
  const handler = source.slice(start, end);
  const hintStart = handler.indexOf('if (action === "hint")');
  const planStart = handler.indexOf('if (action === "plan")');
  assert.ok(hintStart > -1 && planStart > hintStart, 'expected hint branch before plan branch');
  const hintBlock = handler.slice(hintStart, planStart);
  assert.match(hintBlock, /setComposerDraft/);
  assert.doesNotMatch(hintBlock, /sendTurn/);
  assert.doesNotMatch(hintBlock, /intent:\s*"task"/);
  assert.doesNotMatch(hintBlock, /intent:\s*"next_task"/);
});

test('handleSuggestedAction does not sendTurn task or next_task when leftover is not live', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const gateStart = source.indexOf('const leftoverSuggestedActionNotLive');
  const submitStart = source.indexOf('const handleSubmit', gateStart);
  assert.ok(gateStart > -1 && submitStart > gateStart, 'expected leftoverSuggestedActionNotLive before handleSubmit');
  const consume = source.slice(gateStart, submitStart);
  assert.match(
    consume,
    /const leftoverSuggestedActionNotLive =\s*\(Boolean\(recoveredRuntime\) && !formalPlanLive && !liveTask\) \|\|\s*streakAdaptsWithoutInventingLiveObjects\([\s\S]*?streakBlocksLiveObjectMint:[\s\S]*?\)\s*\|\|\s*pressureAdaptsWithoutInventingLiveObjects\([\s\S]*?pressureBlocksLiveObjectMint:[\s\S]*?\)\s*\|\|\s*data\.memory\.coachingAdaptation\?\.closedLoopReturnBlocksTaskMint === true \|\|\s*data\.coachFocus\?\.closedLoopReturnBlocksTaskMint === true/,
  );
  const nextStart = consume.indexOf('if (action === "next_task")');
  const reviewStart = consume.indexOf('if (action === "review"');
  assert.ok(nextStart > -1 && reviewStart > nextStart, 'expected next_task before review');
  const nextBlock = consume.slice(nextStart, reviewStart);
  assert.match(nextBlock, /if \(leftoverSuggestedActionNotLive\) \{[\s\S]*?setComposerDraft\(reviewOnlyDraft\);[\s\S]*?return;/);
  assert.match(nextBlock, /intent:\s*"next_task"/);
  const leftoverNext = nextBlock.slice(
    nextBlock.indexOf('if (leftoverSuggestedActionNotLive)'),
    nextBlock.indexOf('sendTurn'),
  );
  assert.ok(leftoverNext.includes('return;'), 'expected leftover next_task to return before sendTurn');
  assert.doesNotMatch(leftoverNext, /intent:\s*"next_task"/);
  const taskStart = consume.lastIndexOf('setActiveView("coach")');
  const taskBlock = consume.slice(taskStart);
  assert.match(taskBlock, /if \(leftoverSuggestedActionNotLive\) \{[\s\S]*?setComposerDraft\(reviewOnlyDraft\);[\s\S]*?return;/);
  assert.match(taskBlock, /intent:\s*"task"/);
  const leftoverTask = taskBlock.slice(
    taskBlock.indexOf('if (leftoverSuggestedActionNotLive)'),
    taskBlock.indexOf('sendTurn'),
  );
  assert.ok(leftoverTask.includes('return;'), 'expected leftover task to return before sendTurn');
  assert.doesNotMatch(leftoverTask, /intent:\s*"task"/);
});
