'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(
  path.resolve(__dirname, '../webview/src/components/training/TrainingWorkbenchView.tsx'),
  'utf8',
);

assert.match(
  source,
  /const degradedCard = \/确定性降级卡\|deterministic fallback\/i\.test\(whyNow \?\? ""\)/,
);
assert.match(source, /data-training-degraded="true"/);
assert.match(source, /trainingWorkbenchText\(language, "degradedCardEyebrow"\)/);
assert.match(source, /trainingWorkbenchText\(language, "degradedCardBody"\)/);
assert.match(source, /trainingWorkbenchText\(language, "degradedCardRetry"\)/);
assert.match(source, /onClick=\{onNextCard\}/);
