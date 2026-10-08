'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const planViewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'plan',
  'CoachPlanView.tsx',
);
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const planViewCopyPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'i18n',
  'planViewCopy.ts',
);

function sourceBetween(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);

  assert.ok(start >= 0, `expected source marker: ${startMarker}`);
  assert.ok(end > start, `expected source marker after ${startMarker}: ${endMarker}`);

  return source.slice(start, end);
}

test('Plan keeps formal truth, evidence, and blockers distinct without silent mutation', () => {
  const source = fs.readFileSync(planViewPath, 'utf8');

  assert.match(source, /export interface PlanGovernanceItem/);
  assert.match(source, /governanceItems\?: PlanGovernanceItem\[\]/);
  // Priority is domain-owned; optional facts never silently advance the plan.
  const { learningAction, learningPlan } = require('./templateAssertions');
  const pending = learningAction({ evidence: { pending: [{ id: 'e1', summary: 'Result pending' }] } });
  assert.equal(pending.intent, 'continue_step');
  const blocked = learningAction({ plan: { state: 'active', id: 'plan', currentStep: 'Write tests', blocker: 'Runner is missing' } });
  assert.equal(blocked.intent, 'resolve_blocker');
  const html = learningPlan(blocked);
  assert.ok(html.includes('Runner is missing'));
  assert.ok(html.includes('Resolve with coach'));
  assert.equal((html.match(/data-primary-action="true"/g) || []).length, 1);
  assert.doesNotMatch(source, /fallbackGovernanceItems|resolvePlanDecisionStrip|pickPlanPrimaryAction/);
  assert.match(source, /next=\{props\.primaryAction\}/);
});

test('Plan localizes its own honest empty, blocked, frozen, and stage fallback states', () => {
  const source = fs.readFileSync(planViewPath, 'utf8');
  const copyStart = source.indexOf('const PLAN_COPY:');
  const copyEnd = source.indexOf('function planCopy(', copyStart);

  assert.ok(copyStart >= 0 && copyEnd > copyStart, 'expected Plan locale copy');
  const planCopy = source.slice(copyStart, copyEnd);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    const start = planCopy.indexOf(`  "${language}": {`);
    const end = planCopy.indexOf('\n  },', start);
    assert.ok(start >= 0 && end > start, `expected ${language} Plan copy`);
    const localeCopy = planCopy.slice(start, end);
    for (const key of ['planBlocked', 'formalPlanFrozen', 'emptyOutlineLabel', 'done', 'pending']) {
      assert.match(localeCopy, new RegExp(`${key}:`), `${language} must localize ${key}`);
    }
  }

  const { learningAction } = require('./templateAssertions');
  const labels = new Set();
  for (const language of ['zh-CN','en-US','es-ES','fr-FR','de-DE','ja-JP','ko-KR','pt-BR']) {
    const frozen = learningAction({ language, plan: { state: 'frozen', id: 'plan' } });
    const empty = learningAction({ language, plan: { state: 'absent' } });
    assert.ok(frozen.title && frozen.detail && empty.title && empty.detail);
    labels.add(frozen.label);
  }
  assert.equal(labels.size, 8);
  assert.match(source, /function resolveStageStatusLabel/);
  assert.match(source, /status === "queued" \? planCopy\(language, "pending"\)/);
});

test('Plan keeps the compact first viewport focused on governed route facts', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').learning();
});

test('Plan calls its hooks before the empty-state early return', () => {
  const source = fs.readFileSync(planViewPath, 'utf8');
  const emptyStateReturnIndex = source.indexOf('  if (!plan) {');

  assert.ok(emptyStateReturnIndex >= 0, 'expected empty-state return');
  for (const hookMarker of [
    'const pendingEvidenceItems = useMemo(',
    'const settledEvidenceItems = useMemo(',
    'const evidenceCounts = useMemo(',
  ]) {
    const hookIndex = source.indexOf(hookMarker);
    assert.ok(hookIndex >= 0, `expected hook marker: ${hookMarker}`);
    assert.ok(
      hookIndex < emptyStateReturnIndex,
      `expected ${hookMarker} before the empty-state early return`,
    );
  }
});

test('Plan keeps project subplans collapsed, concise, and truthfully selectable', () => {
  const source = fs.readFileSync(planViewPath, 'utf8');

  assert.match(source, /export type ProjectSubplanStatus = "active" \| "pending" \| "blocked" \| "frozen";/);
  assert.match(source, /export interface ProjectSubplanView \{[\s\S]*?id: string;[\s\S]*?title: string;[\s\S]*?status: ProjectSubplanStatus;/);
  assert.match(source, /projectSubplans\?: readonly ProjectSubplanView\[\];/);
  assert.match(source, /projectSubplanStatusLabels\?: Partial<Record<ProjectSubplanStatus, string>>;/);
  assert.match(source, /onProjectSubplanSelect\?: \(subplan: ProjectSubplanView\) => void;/);
  assert.match(source, /function defaultProjectSubplanStatusLabel/);
  assert.match(source, /function resolveStageStatusLabel/);
  assert.match(source, /language !== "en-US" && label === englishFallback/);
  assert.match(source, /status === "active"/);
  assert.match(source, /status === "pending"/);
  assert.match(source, /status === "blocked"/);
  assert.match(source, /status === "frozen"/);
  assert.match(source, /<details className="template-disclosure coach-plan-view__project-subplans">/);
  assert.match(source, /projectSubplans\.length > 0/);
  assert.match(source, /disabled=\{!props\.onProjectSubplanSelect\}/);
  assert.match(source, /onClick=\{\(\) => props\.onProjectSubplanSelect\?\.\(subplan\)\}/);
  assert.doesNotMatch(source, /subplan\.(?:stages|description|progressPercent|createdAt|updatedAt)/);
});

test('Plan keeps project subplans inside the master current-plan card and outside evidence rendering', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').learning();
});

test('Plan keeps the global-to-project relationship compact and explicitly actionable', () => {
  const source = fs.readFileSync(planViewPath, 'utf8');
  const appSource = fs.readFileSync(appPath, 'utf8');
  const masterCardStart = source.indexOf('<LearningHome');
  const masterCardEnd = source.indexOf('</LearningHome>', masterCardStart);
  const globalContextStart = source.indexOf('{globalPlanContext}', masterCardStart);
  const subplansStart = source.indexOf('coach-plan-view__project-subplans', masterCardStart);

  assert.match(source, /globalPlan\?: GlobalPlan;/);
  assert.match(source, /projectPlanLink\?: GlobalPlanProjectLink;/);
  assert.match(source, /onCreateGlobalPlan\?: \(\) => void;/);
  assert.match(source, /onLinkCurrentProjectPlan\?: \(\) => void;/);
  assert.match(source, /const hasCurrentProjectPlanLink = Boolean\(/);
  assert.match(source, /coach-plan-view__global-plan-context/);
  assert.match(source, /globalPlanAction: PlanActionItem \| undefined/);
  assert.ok(globalContextStart > masterCardStart && globalContextStart < masterCardEnd);
  assert.ok(globalContextStart < subplansStart, 'global context must appear before project subplans');
  // Always collapsed: the global-plan disclosure must not compete with the current step.
  assert.doesNotMatch(source, /open=\{globalPlanNeedsAction\}/);
  assert.match(source, /coach-plan-view__global-plan-context"\s*\n\s*aria-label=/);
  // The create/link action is demoted to ghost so the NextAction stays the single accent primary.
  assert.match(source, /id: "create-global-plan",[\s\S]{0,300}tone: "ghost"/);
  assert.match(source, /id: "link-current-project-plan",[\s\S]{0,300}tone: "ghost"/);
  assert.match(source, /const globalPlanContextKey = \[/);
  assert.match(source, /key=\{globalPlanContextKey\}/);
  assert.match(source, /label: t\("globalPlanCreate"\)/);
  assert.match(source, /label: t\("globalPlanLinkCurrentProject"\)/);
  assert.match(appSource, /globalPlan=\{data\.globalPlan\}/);
  assert.match(appSource, /projectPlanLink=\{data\.projectPlanLink\}/);
  assert.match(appSource, /commandId: trainerCommands\.createGlobalPlan/);
  assert.match(appSource, /commandId: trainerCommands\.linkCurrentProjectPlan/);
});

test('Plan global-plan copy stays honest across missing, unlinked, and linked states', () => {
  const source = fs.readFileSync(planViewPath, 'utf8');

  assert.match(source, /const globalPlanStatus = !globalPlan/);
  assert.match(source, /:\s*globalPlan\.frozen\s*\n\s*\? t\("globalPlanFrozen"\)/);
  assert.match(source, /:\s*hasCurrentProjectPlanLink\s*\n\s*\? t\("globalPlanLinked"\)/);
  assert.match(source, /:\s*!plan\s*\n\s*\? t\("globalPlanLinkUnavailable"\)\s*\n\s*:\s*t\("globalPlanNotLinked"\)/);
  assert.match(source, /const globalPlanRelationshipSummary = !globalPlan/);
  assert.match(source, /t\("globalPlanNotCreated"\)/);
  assert.match(source, /t\("globalPlanNotLinked"\)/);
  assert.match(source, /globalPlanAction: PlanActionItem \| undefined/);
  assert.match(source, /t\("globalPlanCreate"\)/);
  assert.match(source, /t\("globalPlanLinkCurrentProject"\)/);
  assert.match(source, /t\("globalPlanLinked"\)/);
  assert.match(source, /t\("globalPlanNotCreated"\)/);
  assert.match(source, /t\("globalPlanNotLinked"\)/);
  assert.match(source, /t\("globalPlanLinkUnavailable"\)/);
});

test('App shows an honest empty Plan and supplies every compact Plan label from the eight-language copy', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const planViewSource = fs.readFileSync(planViewPath, 'utf8');
  const planViewCopySource = fs.readFileSync(planViewCopyPath, 'utf8');
  const planSource = sourceBetween(source, '  const renderPlanView = () => (', '  const renderSettingsView = () => (');
  const stageSelectSource = sourceBetween(planSource, '        onStageSelect={(stage) => {', '        nextStep={');

  assert.match(source, /const planText = resolvePlanViewCopy\(layout\.composerLanguage\);/);
  assert.match(planViewCopySource, /const planViewCopy: Record<ComposerLanguage, PlanViewCopy> = \{/);
  assert.match(planViewCopySource, /export function resolvePlanViewCopy\(language: ComposerLanguage\)/);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(planViewCopySource, new RegExp(`"${language}": \\{`));
  }
  assert.match(planSource, /plan=\{workspaceSessionBlocked \? null : visibleFormalPlan\}/);
  assert.match(planSource, /compactPrimary/);
  assert.match(
    planSource,
    /title=\{\s*workspaceSessionBlocked \|\| !hasFormalPlan\s*\?\s*t\.plan\s*:\s*formalPlanLive\s*\?\s*data\.plan\.title\s*:\s*livePlanTitle\s*\}/,
  );
  assert.match(planSource, /goalLabel=\{t\.currentFocus\}/);
  assert.match(planSource, /emptyState=\{[\s\S]*?planText\.emptyState\(coachViewLabel\(layout\.composerLanguage\)\)/);
  assert.match(planSource, /goalHint=\{planText\.goalHint\}/);
  assert.match(planSource, /overviewLabel=\{planText\.overviewLabel\}/);
  assert.match(planSource, /nextStepHint=\{planText\.nextStepHint\}/);
  assert.match(planSource, /returnLabel=\{planText\.returnLabel\}/);
  assert.match(planSource, /projectSubplansLabel=\{planText\.projectSubplansLabel\}/);
  assert.doesNotMatch(planSource, /layout\.composerLanguage === "zh-CN"/);
  assert.match(
    planViewSource,
    /const resolvedTitleText = nodeText\(props\.title \?\? plan\?\.title\)\.trim\(\);/,
  );
  assert.match(planSource, /goalSummary=\{/);
  assert.match(planSource, /nextStep=\{/);
  assert.match(planSource, /whyNow=\{/);
  assert.match(planSource, /verifyNow=\{/);
  assert.match(planSource, /returnPath=\{/);
  assert.match(planSource, /reviewWindow=\{/);
  assert.match(planSource, /evidenceQueue=\{liveEvidenceQueue\}/);
  assert.match(planSource, /evidenceActions=\{\{/);
  assert.match(planSource, /type: "plan\/freeze"/);
  assert.match(stageSelectSource, /requestPlanComposerGuidance\(stage\.title, "stage"\)/);
  assert.doesNotMatch(stageSelectSource, /setComposerDraft\(/);
  assert.doesNotMatch(stageSelectSource, /postMessage\(|sendTurn\(|setActiveView\(/);
});
