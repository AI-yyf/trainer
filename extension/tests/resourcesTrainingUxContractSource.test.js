'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
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

function cardOnlyRender(source) {
  const start = source.indexOf('{cardOnly ? (');
  const end = source.indexOf('{!cardOnly ? (', start);

  assert.ok(start >= 0, 'expected the card-only render branch');
  assert.ok(end > start, 'expected the card-only render branch to close before secondary content');
  return source.slice(start, end);
}

test('resources stay a searchable knowledge library with a controlled sandbox disclosure', () => {
  const source = fs.readFileSync(resourcesPath, 'utf8');
  const appSource = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /resources: ResourceRecord\[\];/);
  assert.match(source, /resources-pane--library resources-knowledge/);
  assert.match(source, /className="resources-search resources-search--hero resources-knowledge__search"/);
  assert.match(source, /"en-US": "Search"/);
  assert.doesNotMatch(source, /"en-US": "Search resources"/);
  assert.match(source, /const visibleResources = useMemo/);
  assert.match(source, /function sourceChain\(resource: ResourceRecord\)/);
  assert.match(source, /const openResourceInVsCode = \(resource: ResourceRecord\) =>/);
  assert.match(source, /function buildResourceTree\(/);
  assert.match(source, /role="tree"/);
  assert.match(source, /hasSearchQuery/);
  assert.match(source, /className="resources-knowledge__detail"/);
  assert.match(source, /className="resources-knowledge__facts"/);
  assert.match(source, /onImportFiles/);
  assert.match(source, /onImportFolder/);
  assert.match(source, /onImportUrl/);
  assert.match(source, /onOpenResource\?\.\(resource\.id\)/);
  assert.match(source, /onPreviewResource\(selectedResource\.id\)/);
  assert.match(source, /sandboxPreview\?: SandboxPreview/);
  assert.match(source, /onClick=\{\(\) => openResourceInVsCode\(selectedResource\)\}/);
  assert.match(source, /openInVsCode/);
  assert.doesNotMatch(source, /renderResourcePreviewBody|renderStructuredPreview/);
  assert.match(source, /sandboxPreviewEmbedded: false/);
  assert.match(source, /sandboxPreviewVisible: false/);
  assert.doesNotMatch(source, /resources-(?:dashboard|metrics|analytics)/);
  assert.doesNotMatch(source, /resources-sandbox-tree/);
  assert.doesNotMatch(source, /onDeleteSandboxPath/);
  assert.match(appSource, /<ResourcesWorkbenchView[\s\S]*?resources=\{liveResources\}/);
  assert.match(appSource, /sandboxState=\{liveSandboxState\}/);
  assert.match(appSource, /sandboxPreview=\{leftoverSandboxPreviewNotLive \? undefined : data\.memory\.sandboxPreview\}/);
  assert.match(appSource, /onPreviewResource=/);
  assert.match(appSource, /onImportFiles=\{\(\) =>/);
  assert.match(appSource, /type ResourcesComposerMode = "locate" \| "download" \| "organize" \| "cards";/);
  assert.match(appSource, /id: "locate"/);
  assert.match(appSource, /id: "download"/);
  assert.match(appSource, /id: "organize"/);
  assert.match(appSource, /id: "cards"/);
  assert.match(appSource, /activeView === "resources"/);
  assert.doesNotMatch(appSource, /id: "resources-composer-mode"/);
  assert.match(appSource, /activeResourcesComposerMode\.(?:placeholder|summary|hint|accessibilityLabel)/);
});

test('training defaults to a five-stage single-card loop with one visible, state-driven next action', () => {
  const source = fs.readFileSync(trainingPath, 'utf8');
  const appSource = fs.readFileSync(appPath, 'utf8');
  const cardOnly = cardOnlyRender(source);
  const cardSectionsStart = source.indexOf('const cardOnlyBodySections');
  const cardSectionsEnd = source.indexOf('const hasAdjustmentOutcome', cardSectionsStart);
  const cardSections = source.slice(cardSectionsStart, cardSectionsEnd);

  assert.match(cardSections, /key: "current"/);
  assert.match(cardSections, /key: "why-now"/);
  assert.match(cardSections, /key: "deliverable"/);
  assert.match(cardSections, /key: "verify"/);
  assert.match(cardSections, /key: "return"/);
  assert.match(cardSections, /title: cardOnlyTask/);
  assert.doesNotMatch(cardOnly, /training-loop-rail--card-only/);
  assert.match(source, /const order: TrainingLoopStepKey\[\] = \["learn", "try", "verify", "reflect", "return"\];/);
  assert.doesNotMatch(cardOnly, /trainingLoopSteps\.map/);
  assert.doesNotMatch(cardOnly, /data-training-loop-step=\{step\.key\}/);
  assert.match(cardOnly, /data-view-primary=""/);
  assert.match(cardOnly, /training-current__done/);
  assert.doesNotMatch(cardOnly, /flashProofSurface|practiceProofSurface|Verify current file/);
  assert.match(appSource, /<TrainingWorkbenchView[\s\S]*?cardOnly=\{true\}/);
  assert.match(appSource, /primaryAction=\{/);
  assert.match(appSource, /trainingPrimaryAction/);
  assert.match(appSource, /const trainingPrimaryAction = !hasTrainingCard \? undefined/);
  assert.match(appSource, /t\.trainingReturnToCoach/);
  assert.match(appSource, /trainingPracticeVerificationMode === "file"/);
  assert.match(appSource, /id: "composer-verify-file"/);
  assert.match(appSource, /onClick: handleVerifyTrainingFromIde/);
  assert.doesNotMatch(
    appSource,
    /<button className="button button--accent" type="button" onClick=\{handleVerifyTrainingFromIde\}/,
  );
  assert.match(appSource, /const trainingComposerUsesAnswerMode = trainingComposerPhase === "answer";/);
  assert.match(appSource, /const trainingComposerManualPracticeMode =/);
  assert.match(appSource, /if \(!trainingComposerManualPracticeMode\) \{/);
  assert.match(appSource, /setTrainingComposerPracticeReturnMode\("result"\)/);
  assert.match(appSource, /setTrainingComposerPracticeReturnMode\("blocked"\)/);
  assert.match(appSource, /commandId: trainerCommands\.trainingPracticeReturn/);
  assert.doesNotMatch(appSource, /id: "training-verify-current-file"/);
  assert.equal(
    (appSource.match(/handleVerifyTrainingFromIde/g) ?? []).length >= 2,
    true,
    'verify stays wired through composer, not a card farm',
  );
});

test('each workbench view keeps its own primary object instead of embedding the coach transcript', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  assert.match(appSource, /view-stack--single/);
  assert.doesNotMatch(appSource, /showEmbeddedCoachTranscript/);
  assert.doesNotMatch(appSource, /coach-pane coach-pane--embedded coach-pane--secondary/);
  assert.doesNotMatch(appSource, /view-stack__divider/);
});
