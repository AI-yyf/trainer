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
  assert.match(source, /const fallbackGovernanceItems: PlanGovernanceItem\[\] = \[/);
  assert.match(
    source,
    /id: "formal-plan",[\s\S]*?value: planStateValue,[\s\S]*?tone: plan\.frozen \? "warning" : "good"/,
  );
  assert.match(source, /id: "evidence-adoption",/);
  assert.match(source, /id: "blocker-state",/);
  assert.match(
    source,
    /props\.governanceItems && props\.governanceItems\.length > 0[\s\S]*?: fallbackGovernanceItems/,
  );
  assert.match(source, /function resolvePlanDecisionStrip/);
  assert.match(source, /planFrozen: plan\.frozen/);
  assert.match(source, /hasPendingEvidence = evidenceItem\?\.tone === "warning" && !input\.planFrozen/);
  assert.match(source, /Plan is blocked/);
  assert.match(source, /Evidence has not changed the plan/);
  assert.match(source, /Formal plan is frozen/);
  assert.match(source, /Plan can move/);
  assert.match(source, /(?:Ordinary chat|Chat evidence) will not rewrite it silently/);
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

  assert.match(source, /function resolvePlanDecisionStrip\(input: \{[\s\S]*?language: PlanLanguage;/);
  assert.doesNotMatch(source, /input\.isChinese/);
  assert.match(source, /aria-label=\{planCopy\(language, "emptyOutlineLabel"\)\}/);
  assert.match(source, /function resolveStageStatusLabel/);
  assert.match(source, /status === "queued" \? planCopy\(language, "pending"\)/);
});

test('Plan keeps the compact first viewport focused on governed route facts', () => {
  const source = fs.readFileSync(planViewPath, 'utf8');

  assert.doesNotMatch(source, /compactPlanText/, 'first-screen facts must not use character truncation');
  assert.match(source, /governanceItems\.length && !compactPrimary/);
  assert.match(source, /const shouldShowDecisionCard =/);
  assert.match(source, /coach-plan-view__decision-strip/);
  assert.match(source, /coach-plan-view__decision-inline/);
  assert.match(source, /data-plan-fact="next"/);
  assert.match(source, /data-plan-fact=\{item\.id\}/);
  assert.match(source, /data-plan-primary=\{compactPrimary \? "true" : undefined\}/);
  assert.match(source, /const primaryRouteStripItems = routeStripItems;/);
  assert.doesNotMatch(source, /const compactPrimaryFactRows/);
  assert.match(
    source,
    /const compactDetailRows: Array<\{ id: string; label: string; body: ReactNode \}> = compactPrimary/,
  );
  assert.match(
    source,
    /id: "stage",\s*label: resolvedCurrentStageLabel,\s*body: stageProgressText \? `\$\{activeStageTitle\} · \$\{stageProgressText\}` : activeStageTitle,/s,
  );
  assert.match(source, /const liveStageIsCurrent = props\.liveStageIsCurrent !== false;/);
  assert.match(source, /const liveCurrentStep = plan\.currentStep\?\.trim\(\) \|\| "";/);
  assert.match(source, /const recoveredVerifyLocked =/);
  assert.match(source, /\.\.\.\(queue\.history \?\? \[\]\)/);
  assert.match(source, /case "history":\s*return evidenceQueue\?\.history \?\? \[\];/);
  assert.match(source, /planCopy\(language, "continueCurrent"\)/);
  assert.match(source, /\.\.\.mainLanes\.slice\(1\)\.map\(\(lane\) => \(\{/);
  assert.match(source, /compactDetailRows\.length > 0/);
  assert.match(source, /compactDetailRows\.map\(\(lane\) => \(/);
  assert.match(source, /<div>\{renderNodeWithParagraph\(lane\.body\)\}<\/div>/);
  assert.match(source, /id: "current",\s*label: resolvedCurrentStageLabel,\s*body: activeStageTitle,/s);
  assert.match(source, /id: "why",\s*label: resolvedWhyNowLabel,\s*body: whyNowBody,/s);
  assert.match(
    source,
    /const recoveredWhyLocked = Boolean\(plan\.currentStep\?\.trim\(\)\) && !plan\.whyNow\?\.trim\(\);/,
  );
  assert.match(
    source,
    /const whyFallback = recoveredWhyLocked \? "" : \(plan\.whyNow\?\.trim\(\) \|\| activeStageObjective\);/,
  );
  assert.match(source, /id: "verify",\s*label: resolvedVerifyLabel,\s*body: verifyText,/s);
  assert.match(source, /id: "return",\s*label: resolvedReturnLabel,\s*body: returnPathText,/s);
  assert.match(source, /<strong>\{currentLane\.body\}<\/strong>/);
  assert.match(source, /<strong>\{item\.body\}<\/strong>/);
  const compactSummary = sourceBetween(
    source,
    '<div className="coach-plan-view__compact-summary">',
    '!hideDecisionStrip && !shouldShowDecisionCard && !compactPrimary',
  );
  assert.match(compactSummary, /coach-plan-view__now-card/);
  assert.doesNotMatch(compactSummary, /data-plan-evidence-list/);
  assert.doesNotMatch(compactSummary, /coach-plan-view__compact-fact/);
  assert.doesNotMatch(source, /coach-plan-view__compact-more/);
  assert.match(source, /<details className="coach-plan-view__details">/);
  assert.match(source, /<details className="coach-plan-view__nested-details coach-plan-view__evidence-details">/);
  assert.match(source, /evidenceActions\?\.onAdoptEvidence/);
  assert.match(source, /evidenceActions\?\.onDeferEvidence/);
  assert.match(source, /evidenceActions\?\.onRejectEvidence/);
  assert.match(source, /data-plan-evidence-decisions="true"/);
  assert.match(source, /const compactBlockerText = blockedReason/);
  assert.doesNotMatch(source, /<textarea\b/i, 'Plan view must not embed a chat composer');
});

test('Plan calls its hooks before the empty-state early return', () => {
  const source = fs.readFileSync(planViewPath, 'utf8');
  const emptyStateReturnIndex = source.indexOf('  if (!plan) {');

  assert.ok(emptyStateReturnIndex >= 0, 'expected empty-state return');
  for (const hookMarker of [
    'const evidenceItems = useMemo(',
    'const evidenceCounts = useMemo(',
    'const filteredEvidenceItems = useMemo(',
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
  assert.match(source, /<details className="coach-plan-view__details coach-plan-view__project-subplans">/);
  assert.match(source, /projectSubplans\.length > 0/);
  assert.match(source, /disabled=\{!props\.onProjectSubplanSelect\}/);
  assert.match(source, /onClick=\{\(\) => props\.onProjectSubplanSelect\?\.\(subplan\)\}/);
  assert.doesNotMatch(source, /subplan\.(?:stages|description|progressPercent|createdAt|updatedAt)/);
});

test('Plan keeps project subplans inside the master current-plan card and outside evidence rendering', () => {
  const source = fs.readFileSync(planViewPath, 'utf8');
  const masterCardStart = source.indexOf('<article\n          className="coach-plan-view__main-card"');
  const masterCardEnd = source.indexOf('\n        </article>\n      </div>', masterCardStart);
  const subplansStart = source.indexOf(
    '<details className="coach-plan-view__details coach-plan-view__project-subplans">',
  );
  const evidenceStart = source.indexOf('{hasEvidenceDetails ? (');

  assert.ok(masterCardStart >= 0, 'expected master current-plan card');
  assert.ok(masterCardEnd > masterCardStart, 'expected master current-plan card closing tag');
  assert.ok(subplansStart > masterCardStart && subplansStart < masterCardEnd);
  assert.ok(evidenceStart > subplansStart, 'project subplans must not be nested in evidence rendering');
  assert.match(source, /<summary>\{`\$\{resolvedProjectSubplansLabel\} \(\$\{projectSubplans\.length\}\)`\}<\/summary>/);
  assert.match(source, /const detail = projectSubplanDetail\(subplan, language\);/);
});

test('Plan keeps the global-to-project relationship compact and explicitly actionable', () => {
  const source = fs.readFileSync(planViewPath, 'utf8');
  const appSource = fs.readFileSync(appPath, 'utf8');
  const masterCardStart = source.indexOf('<article\n          className="coach-plan-view__main-card"');
  const masterCardEnd = source.indexOf('\n        </article>\n      </div>', masterCardStart);
  const globalContextStart = source.indexOf('globalPlanContext', masterCardStart);
  const subplansStart = source.indexOf('coach-plan-view__project-subplans');

  assert.match(source, /globalPlan\?: GlobalPlan;/);
  assert.match(source, /projectPlanLink\?: GlobalPlanProjectLink;/);
  assert.match(source, /onCreateGlobalPlan\?: \(\) => void;/);
  assert.match(source, /onLinkCurrentProjectPlan\?: \(\) => void;/);
  assert.match(source, /const hasCurrentProjectPlanLink = Boolean\(/);
  assert.match(source, /coach-plan-view__global-plan-context/);
  assert.match(source, /globalPlanAction: PlanActionItem \| undefined/);
  assert.ok(globalContextStart > masterCardStart && globalContextStart < masterCardEnd);
  assert.ok(globalContextStart < subplansStart, 'global context must appear before project subplans');
  assert.match(source, /const globalPlanNeedsAction = !globalPlan \|\| \(!hasCurrentProjectPlanLink/);
  assert.match(source, /const globalPlanContextKey = \[/);
  assert.match(source, /key=\{globalPlanContextKey\}/);
  assert.match(source, /open=\{globalPlanNeedsAction\}/);
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
  assert.match(source, /const globalPlanNeedsAction = !globalPlan \|\| \(!hasCurrentProjectPlanLink/);
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
  assert.match(planSource, /plan=\{shouldShowNeutralEmptyState \? null : visibleFormalPlan\}/);
  assert.match(planSource, /compactPrimary/);
  assert.match(
    planSource,
    /title=\{\s*shouldShowNeutralEmptyState \|\| !hasFormalPlan\s*\?\s*t\.plan\s*:\s*formalPlanLive\s*\?\s*data\.plan\.title\s*:\s*livePlanTitle\s*\}/,
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
