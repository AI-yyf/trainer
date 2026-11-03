'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(
  path.resolve(__dirname, '../webview/src/app/App.tsx'),
  'utf8',
);

assert.match(
  source,
  /const handleNextTrainingCard = useCallback\(\(\) => \{[\s\S]*?formalPlanLive[\s\S]*?!livePlanFrozen[\s\S]*?activePlanStage\?\.id[\s\S]*?handleGenerateTrainingCard\(activePlanStage\.title, step, \{[\s\S]*?planId: data\.plan\.id,[\s\S]*?stageId: activePlanStage\.id,[\s\S]*?step,[\s\S]*?revision: data\.plan\.revision,/,
  'next card binds the live formal plan stage',
);
assert.match(source, /onNextCard=\{handleNextTrainingCard\}/);
assert.match(
  source,
  /handleNextTrainingCard = useCallback[\s\S]*?handleGenerateTrainingCard\(\);\n  \}, \[/,
  'next card still falls back to a manual request without a live plan step',
);
