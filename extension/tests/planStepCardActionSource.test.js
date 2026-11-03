'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../webview/src');
const app = fs.readFileSync(path.join(root, 'app/App.tsx'), 'utf8');
const planView = fs.readFileSync(path.join(root, 'components/plan/CoachPlanView.tsx'), 'utf8');

assert.match(app, /const handleGeneratePlanStepCard = useCallback\(\(\) => \{/);
assert.match(
  app,
  /setActiveView\("training"\);\s*handleGenerateTrainingCard\(activePlanStage\.title, step, \{[\s\S]*?planId: data\.plan\.id,[\s\S]*?stageId: activePlanStage\.id,[\s\S]*?step,[\s\S]*?revision: data\.plan\.revision,/,
);
assert.match(
  app,
  /onPracticePlanStep=\{[\s\S]*?learningPrimaryAction\.intent === "continue_step"[\s\S]*?handleGeneratePlanStepCard[\s\S]*?\}/,
);
assert.match(planView, /data-plan-step-card-action="true"/);
assert.match(planView, /planViewText\.practiceStepLabel/);
assert.match(planView, /planViewText\.practiceStepDetail/);
assert.match(planView, /onClick=\{props\.onPracticePlanStep\}/);
